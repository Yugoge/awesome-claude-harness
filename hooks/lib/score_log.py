"""The score log (logs/lifecycle.jsonl): its reader, its one writer, the point values and every rule on its rows. Scores, ranks
and views are computed on read, never stored. Rows: event {kind, ts, project, task_id, role, event, points, key, why, ref};
rating {kind, ts, project, task_id, rating, roles, tool_use_id}. A row without ``kind`` is read, never scored. ts, as_of: UTC text."""

from __future__ import annotations

import fcntl
import hashlib
import importlib
import json
import os
import re
import subprocess
from contextlib import contextmanager, suppress
from functools import reduce
from pathlib import Path

START, CAP = 50, 100  # a score starts at START, never exceeds CAP and has no lower bound
POINTS = {  # (event, role) -> points ("*": any other role); per-event caps (qa_catch +2 a task) are the writer's
    ("qa_first_pass", "dev"): 2, ("qa_first_pass", "ba"): 1, ("qa_fail", "dev"): -6, ("qa_fail", "ba"): -6, ("qa_catch", "qa"): 1,
    ("escaped", "*"): -7, ("escaped", "qa"): -3, ("close_catch", "close-qa"): 1, ("rerun_gap", "*"): -2, ("stop_blocked", "*"): -1,
    ("main_refused", "main"): -1, ("main_stop_blocked", "main"): -1, ("ba_option_chosen", "ba"): 3, ("ba_root_cause_refuted", "ba"): -4,
}
RATING_POINTS = {5: 3, 4: 1, 3: -3, 1: -6}  # to each role in the rating row's "roles" and to "main"
RANKS = (("Disgraced", "<0", 0), ("Apprentice", "0-20", 21), ("Journeyman", "21-40", 41),  # name, range, next rank's
         ("Skilled Craftsman", "41-60", 61), ("Senior Craftsman", "61-80", 81), ("Master", "81-100", None))  # first score
LOW_BELOW = 21  # D32: below this (the two lowest ranks, Disgraced and Apprentice) a record is low; the experiment that tunes it is in the P13-3 PR
REMINDERS = {  # rank -> its one-line reminder at a dispatch (D29): the next step, no threat (D32)
    "Disgraced": "Reminder: your work keeps failing review; re-check each acceptance criterion against the code and name any you could not verify.",
    "Apprentice": "Reminder: your work often fails review; re-read the requirement and the acceptance criteria before you start, and test each.",
    "Journeyman": "Reminder: your work failed review more than once lately; check every criterion before you stop.",
    "Skilled Craftsman": "Reminder: an average record; do not repeat any miss listed above.",
    "Senior Craftsman": "Reminder: a good record; keep the checks that earned it.",
    "Master": "Reminder: an excellent record; do not cut corners to stay fast, one escaped defect costs more than a task earns.",
}
CONSEQUENCES = {  # role -> what a low record costs it (D32), added to its reminder; the Stop gate and the Codex gate hold it (score_view)
    "dev": "An independent QA round follows your normal QA.", "ba": "An independent QA round follows your normal BA-QA check.",
    "qa": "This round includes a Codex debate, --codex or not: follow templates/prompt-includes/codex-consultation.md (harness home) before you stop.",
}


class ScoreLogError(Exception):
    """The log cannot be read, or a line before the last is malformed."""


def read_lines(path: str) -> list[tuple[int, dict]]:
    """Every entry with its 1-based line number; a final line that does not parse is skipped (a crash mid-append)."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw_lines = handle.readlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ScoreLogError(f"cannot read {path}: {exc}") from exc
    entries = []
    for index, raw_line in enumerate(raw_lines):
        if not (stripped := raw_line.rstrip("\n")):
            continue
        entry = None
        with suppress(json.JSONDecodeError):
            entry = json.loads(stripped)
        if isinstance(entry, dict):
            entries.append((index + 1, entry))
        elif index != len(raw_lines) - 1:
            raise ScoreLogError(f"malformed JSONL at line {index + 1} of {path} (not final line)")
    return entries


def project_key(cwd) -> str:
    """First 12 hex of the sha256 of cwd's resolved git common directory, which linked working copies share (else cwd)."""
    common = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--git-common-dir"], capture_output=True, text=True).stdout.strip()
    return hashlib.sha256(os.path.realpath(os.path.join(cwd, common)).encode()).hexdigest()[:12]


def points_for(event: str, role: str) -> int | None:
    return POINTS.get((event, role), POINTS.get((event, "*")))


def identity(role, pipeline) -> str | None:
    """The scored identity of a dispatch: its role; qa in the close pipeline is "close-qa", scored apart from lane qa."""
    return "close-qa" if (role, pipeline) == ("qa", "close") else role or None


def log_path() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "logs" / "lifecycle.jsonl"


@contextmanager
def locked(log):
    """The exclusive lock on <log>.lock (the file score-update.sh locks) that ``append`` needs its caller to hold."""
    os.makedirs(os.path.dirname(os.path.abspath(log)), exist_ok=True)
    with open(f"{log}.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _ob(name):  # obligation is imported late: score-update.sh puts hooks/lib on the path only after this module
    return getattr(importlib.import_module(".obligation" if __package__ else "obligation", __package__ or None), name)


def append_all(log, rows) -> int:
    """Under ``locked(log)``: write the rows (a list) with one write and one fsync; returns how many. The first row per "key" wins; a
    rating row yields only to a RATING row of the same canonical task id; a row with neither goes as is; an unserialisable one is skipped."""
    def marks(row):  # what makes a row a repeat: its key, and for a rating row its canonical task id
        found = {("key", row["key"])} if isinstance(row.get("key"), str) else set()
        return found | {("rating", _ob("canonical_task_id")(row.get("task_id")))} if row.get("kind") == "rating" else found
    data = Path(log).read_bytes() if os.path.exists(log) else b""
    if data and not data.endswith(b"\n"):  # a crash left a fragment: cut it back to the last newline, or the next row is glued to it
        os.truncate(log, len(data := data[:data.rfind(b"\n") + 1]))
    seen, lines = set(), []
    for line in data.decode("utf-8", "replace").split("\n") if any(isinstance(r, dict) and marks(r) for r in rows) else ():
        with suppress(ValueError, AttributeError):  # a damaged line, or one that is no object: passed over, never raised
            seen |= marks(json.loads(line))
    for row in rows:
        with suppress(TypeError, ValueError, AttributeError):  # an unserialisable row is skipped, the others still go
            line, new = json.dumps(row, ensure_ascii=False).encode("utf-8", "backslashreplace"), marks(row)  # lone surrogates: \udXXX
            if not new & seen:
                lines.append(line + b"\n")
                seen |= new
    if lines:
        with open(log, "ab", buffering=0) as handle:
            handle.write(b"".join(lines))
            os.fsync(handle.fileno())
    return len(lines)


def append(log, row: dict) -> bool:
    return append_all(log, [row]) == 1


def _live(rows, project, as_of):
    return sorted((r for r in rows if r.get("kind") in ("event", "rating") and r.get("project") == project
                   and isinstance(r.get("ts"), str) and r["ts"] < as_of), key=lambda r: r["ts"])


def _mine(rows, identity, project, as_of):
    """(row, points) of each live row counting for the identity: its event rows; rating rows naming it in "roles" (all for main)."""
    pairs = []
    for r in _live(rows, project, as_of):
        event = r["kind"] == "event"
        mine = r.get("role") == identity if event else identity == "main" or identity in (r.get("roles") or ())
        points = mine and (r.get("points") if event else RATING_POINTS.get(r.get("rating")))  # read only for its own rows
        if type(points) is int:
            pairs.append((r, points))
    return pairs


def _fold(pairs):
    return reduce(lambda value, pair: min(CAP, value + pair[1]), pairs, START)


def _history(pairs):
    """The score before each cycle (task family, by first appearance), then at the end: one pass, one running fold."""
    family, before, value = _ob("task_family"), {}, START
    for r, points in pairs:
        before.setdefault(family(r.get("task_id")), value)
        value = min(CAP, value + points)
    return [*before.values(), value]


def score(rows, identity, project, as_of) -> int:
    return _fold(_mine(rows, identity, project, as_of))


def trend(rows, identity, project, as_of) -> int:
    """The score now minus the score before the identity's 5 most recent cycles (task families)."""
    history = _history(_mine(rows, identity, project, as_of))
    return history[-1] - history[max(len(history) - 6, 0)]


def _rank(value):
    return next((name, span) for name, span, below in RANKS if below is None or value < below)


def tier(value) -> str:
    return _rank(value)[0]


def _plain(value) -> str:  # one line of printable text: control and format characters, separators and runs of white space become one space
    return " ".join("".join(c if c.isprintable() else " " for c in str(value)).split())


def _why(row):
    """The row's why as plain text, without a task id, cut to 80 characters."""
    tid, stamped = re.escape(str(row.get("task_id") or "\0")), _ob("task_stamp")  # an id is a run of [\w-] that holds a stamp, or the row's own
    return _plain(re.sub(rf"(?P<own>(?<![\w-]){tid}(?![\w-]))|[\w-]+", lambda m: "" if m["own"] or stamped(m[0]) else m[0], str(row.get("why") or "")))[:80]


def _by_identity(rows, project, as_of):
    """(live rows, sorted names of every identity with a row: event roles; the roles of rating rows, and main)."""
    live = _live(rows, project, as_of)
    names = {n for r in live for n in ([r.get("role")] if r["kind"] == "event" else ["main", *(r.get("roles") or ())]) if n and isinstance(n, str)}
    return live, sorted(names)


def render_owner_summary(rows, project, as_of, task_id) -> str:
    """Three lines for the owner after a rating: every identity's score, rank, trend; the rated cycle's points; the worst and why."""
    live, names = _by_identity(rows, project, as_of)
    if not names:
        return "Scores (this project): no record yet."
    stats, family = {n: (score(live, n, project, as_of), trend(live, n, project, as_of)) for n in names}, _ob("task_family")
    cycle = [r for r in live if family(r.get("task_id")) == family(task_id)]
    items = [f"rating {r['rating']}: {RATING_POINTS[r['rating']]:+d} each" for r in cycle if r.get("rating") in RATING_POINTS]  # first: the cut at 200 characters never drops it
    items += [f"{_plain(r.get('role'))} {r['points']:+d}" + (_why(r) and f" ({_why(r)})") for r in cycle
              if r["kind"] == "event" and type(r.get("points")) is int]
    worst = min(stats, key=lambda n: (*stats[n], n))
    miss = next((_why(r) for r, points in reversed(_mine(live, worst, project, as_of)) if r["kind"] == "event" and points < 0), "")
    more = f", +{len(items) - 5} more" if len(items) > 5 else ""
    return "\n".join((
        "Scores (this project): " + " | ".join(f"{_plain(n)[:24]} {s} {tier(s)} ({t:+d})" for n, (s, t) in stats.items()),
        (f"This cycle {_plain(task_id)}: " + (", ".join(items[:5]) or "no scored events"))[:200 - len(more)] + more,
        f"Worst: {_plain(worst)[:24]} ({tier(stats[worst][0])}, {stats[worst][0]}); " + (f'last miss: "{miss}"' if miss else "no negative event"),
    ))


def low(rows, identity, project, as_of) -> bool:
    return score(rows, identity, project, as_of) < LOW_BELOW


def _facts(pairs, cap):
    """(up to two of the newest good facts, the newest miss) of an identity's (row, points) pairs, each cut to cap characters: an event's why, or the owner's rating."""
    def fact(row):
        return ((_why(row) or _plain(row.get("event"))) if row["kind"] == "event" else f"the owner rated a cycle {'1-2' if row.get('rating') == 1 else row.get('rating')} stars")[:cap]
    newest = [(fact(r), p > 0) for r, p in reversed(pairs) if p]
    return [f for f, good in newest if good][:2], next((f for f, good in newest if not good), "")


def render_dispatch_line(rows, identity, project, as_of) -> str:
    """The dispatch view, at most 3 lines and 400 bytes: score, rank, trend; the newest good event and the newest miss, as facts; the rank's
    reminder, with the role's consequence when the record is low (D32). An identity with no rows gets the one line "no record yet"."""
    pairs, name = _mine(rows, identity, project, as_of), _plain(identity)[:24]
    value = _fold(pairs)
    rank, band = _rank(value)
    reminder = REMINDERS[rank] + (" " + CONSEQUENCES[identity] if value < LOW_BELOW and identity in CONSEQUENCES else "")
    if not pairs:
        return f"No record yet for {name} in this project: Rank {rank}, {band}. {reminder}"
    for cap in (80, 40, 20, 0):  # the facts give way first when the 400 bytes are short
        good, miss = _facts(pairs, cap)
        facts = " ".join(x for x in (good and f"Recent good: {'; '.join(good)}.", miss and f"Recent miss: {miss}.") if x)
        text = "\n".join(x for x in (f"Your record ({name}, this project): {value} [Rank: {rank}, {band}], trend {trend(rows, identity, project, as_of):+d} over 5 tasks.",
                                      facts, reminder) if x)
        if len(text.encode()) <= 400:
            break
    return text


def render_main_line(rows, project, as_of, roles=("dev", "ba", "qa")) -> str:
    """One line for the main agent at the start of an ask span: its own score, rank and newest miss, then the roles whose record is low (D32)."""
    pairs = _mine(rows, "main", project, as_of)
    value = _fold(pairs)
    rank, band = _rank(value)
    miss = _facts(pairs, 80)[1]
    extra = [r for r in roles if r != "qa" and low(rows, r, project, as_of)]
    notice = ([f"{'/'.join(extra)}: one more independent QA round after the normal one"] if extra else []) + (
        ["qa: a Codex debate every round, --codex or not"] if "qa" in roles and low(rows, "qa", project, as_of) else [])
    return f"Your record (main): {value} [Rank: {rank}, {band}]." + (f" Recent miss: {miss}." if miss else "") + (f" Low record: {'; '.join(notice)}." if notice else "")


def glyphs(values) -> str:
    """One line of ▁▂▃▅▇, each number scaled between the lowest and the highest (rounded half up); all equal gives ▃ throughout."""
    low, high = min(values, default=0), max(values, default=0)
    return "".join("▁▂▃▅▇"[int((v - low) * 4 / (high - low) + .5) if high > low else 2] for v in values)


def render_rating_view(rows, project, as_of) -> str:
    """Plain text for /rating: each identity, lowest score first (score, rank, glyphs of its last 10 cycles, its last 5 events), then the last 5 ratings."""
    live, names = _by_identity(rows, project, as_of)
    if not names:
        return "Scores (this project): no records yet."
    mine, lines = {n: _mine(live, n, project, as_of) for n in names}, ["Scores (this project), lowest first"]
    for n in sorted(mine, key=lambda n: (_fold(mine[n]), n)):
        lines += [f"{_plain(n)}: {_fold(mine[n])} " + "[Rank: %s, %s]" % _rank(_fold(mine[n])),
                  "  trend " + (glyphs(_history(mine[n])[1:][-10:]) or "-")]
        lines += [f"  {_plain(r.get('task_id'))}  {_plain(r.get('event'))}  {pts:+d}  {_plain(r.get('why') or '')[:80]}".rstrip()
                  for r, pts in reversed(mine[n]) if r["kind"] == "event"][:5] or ["  no events"]
    rated = [f"  {_plain(r.get('task_id'))}  {_plain(r.get('rating'))}" for r in reversed(live) if r["kind"] == "rating"][:5]
    return "\n".join(line[:200] for line in lines + (["Your latest ratings, newest first"] + rated if rated else ["Your ratings: none yet"]))
