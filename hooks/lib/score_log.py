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
from contextlib import contextmanager
from functools import reduce
from pathlib import Path

START, CAP = 50, 100  # a score starts at START, never exceeds CAP and has no lower bound
POINTS = {  # event -> points by role ("*": any other role); per-event caps (qa_catch +2 a task) are the writer's
    "qa_first_pass": {"dev": 2, "ba": 1}, "qa_fail": {"dev": -6, "ba": -6}, "qa_catch": {"qa": 1},
    "escaped": {"*": -7, "qa": -3}, "close_catch": {"close-qa": 1}, "rerun_gap": {"*": -2}, "stop_blocked": {"*": -1},
    "main_refused": {"main": -1}, "main_stop_blocked": {"main": -1}, "ba_option_chosen": {"ba": 3},
    "ba_root_cause_refuted": {"ba": -4},
}
RATING_POINTS = {5: 3, 4: 1, 3: -3, 1: -6}  # to each role in the rating row's "roles" and to "main"
RANKS = (("Disgraced", "<0", 0), ("Apprentice", "0-20", 21), ("Journeyman", "21-40", 41),  # name, range, next rank's
         ("Skilled Craftsman", "41-60", 61), ("Senior Craftsman", "61-80", 81), ("Master", "81-100", None))  # first score


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
        try:
            entry = json.loads(stripped)
        except json.JSONDecodeError:
            entry = None
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
    return POINTS[event].get(role, POINTS[event].get("*"))


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


def append(log, row: dict) -> bool:
    """Under ``locked(log)``: append one fsynced line, True when written. The first row per "key" wins; a rating row yields
    only to a RATING row of the same canonical task id; a row with neither (score-update.sh's) is written as is."""
    rating, key = row.get("kind") == "rating", row.get("key")
    if (rating or key is not None) and os.path.exists(log):
        canonical = _ob("canonical_task_id")
        if any((key is not None and old.get("key") == key) or (rating and old.get("kind") == "rating"
               and canonical(old.get("task_id")) == canonical(row.get("task_id"))) for _, old in read_lines(str(log))):
            return False
    with open(log, "a", encoding="utf-8") as handle:
        print(json.dumps(row, ensure_ascii=False), file=handle, flush=True)
        os.fsync(handle.fileno())
    return True


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
    """The score at the start, then after each cycle (task family, by first appearance): the fold up to the next cycle's first row."""
    family, first = _ob("task_family"), {}
    for i, (r, _) in enumerate(pairs):
        first.setdefault(family(r.get("task_id")), i)
    return [START] + [_fold(pairs[:end]) for end in [*list(first.values())[1:], len(pairs)] if first]


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


def _why(row):
    """The row's why on one line, without a task id, cut to 80 characters."""
    tid = re.escape(str(row.get("task_id") or "\0"))
    stamp = r"(?:dev-(?:command-)?)?\d{8}-\d{6}(?:-l?\d+)?"
    return " ".join(re.sub(rf"(?<![\w-]){tid}(?![\w-])|{stamp}", "", str(row.get("why") or "")).split())[:80]


def _last_miss(pairs):
    return next((_why(r) for r, points in reversed(pairs) if r["kind"] == "event" and points < 0), "")


def _by_identity(rows, project, as_of):
    """(live rows, sorted names of every identity with a row: event roles; the roles of rating rows, and main)."""
    live = _live(rows, project, as_of)
    names = {n for r in live for n in ([r.get("role")] if r["kind"] == "event" else ["main", *(r.get("roles") or ())]) if n and isinstance(n, str)}
    return live, sorted(names)


def render_dispatch_line(rows, identity, project, as_of) -> str:
    """An agent's record and rank at dispatch, then its latest negative event's why (80 characters, no task id) when it has one."""
    pairs = _mine(rows, identity, project, as_of)
    rank, miss = "[Rank: %s, %s]" % _rank(_fold(pairs)), _last_miss(pairs)
    line = f"Your record ({identity}, this project): " + (
        f"{_fold(pairs)} {rank}, trend {trend(rows, identity, project, as_of):+d} over 5 tasks." if pairs else f"no record yet {rank}.")
    return f'{line}\nMost recent miss: "{miss}"' if miss else line


def render_owner_summary(rows, project, as_of, task_id) -> str:
    """Three lines for the owner after a rating: every identity's score, rank, trend; the rated cycle's points; the worst and why."""
    live, names = _by_identity(rows, project, as_of)
    if not names:
        return "Scores (this project): no record yet."
    stats, family = {n: (score(live, n, project, as_of), trend(live, n, project, as_of)) for n in names}, _ob("task_family")
    cycle = [r for r in live if family(r.get("task_id")) == family(task_id)]
    items = [f"{r['role']} {r['points']:+d}" + (_why(r) and f" ({_why(r)})") for r in cycle
             if r["kind"] == "event" and type(r.get("points")) is int]
    items += [f"rating {r['rating']}: {RATING_POINTS[r['rating']]:+d} each" for r in cycle if r.get("rating") in RATING_POINTS]
    worst = min(stats, key=lambda n: (*stats[n], n))
    miss = _last_miss(_mine(live, worst, project, as_of))
    return "\n".join((
        "Scores (this project): " + " | ".join(f"{n} {s} {tier(s)} ({t:+d})" for n, (s, t) in stats.items()),
        f"This cycle {task_id}: " + (", ".join(items) or "no scored events"),
        f"Worst: {worst} ({tier(stats[worst][0])}, {stats[worst][0]}); " + (f'last miss: "{miss}"' if miss else "no negative event"),
    ))


def glyphs(values) -> str:
    """One line of ▁▂▃▅▇, each number scaled between the lowest and the highest (rounded half up); all equal gives ▃ throughout."""
    low, high = min(values, default=0), max(values, default=0)
    return "".join("▁▂▃▅▇"[int((v - low) * 4 / (high - low) + .5) if high > low else 2] for v in values)


def _plain(value) -> str:  # one line of printable text: control characters and runs of white space become one space
    return " ".join("".join(c if c.isprintable() else " " for c in str(value)).split())


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
    return "\n".join(lines + (["Your latest ratings, newest first"] + rated if rated else ["Your ratings: none yet"]))
