"""The score log (logs/lifecycle.jsonl) has one module: its reader, its one writer, the point values and the rules.
Scores, ranks, trends and the text views are computed on read, never stored. Rows: event {kind, ts, project, task_id,
role, event, points, key, why, ref}; rating {kind, ts, project, task_id, rating, roles, tool_use_id}. A row without
``kind`` (score-update.sh's nine keys, P4's four) is read and never scored. ts and as_of are UTC ``%Y-%m-%dT%H:%M:%SZ``."""

from __future__ import annotations

import fcntl
import hashlib
import importlib
import json
import os
import re
import subprocess
from contextlib import contextmanager
from pathlib import Path

START, CAP = 50, 100
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
    """Every entry of the log with its 1-based line number, in file order. A final line that does not parse is
    skipped: a crash mid-append leaves at most the last line partial."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw_lines = handle.readlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ScoreLogError(f"cannot read {path}: {exc}") from exc
    entries = []
    for index, raw_line in enumerate(raw_lines):
        stripped = raw_line.rstrip("\n")
        if not stripped:
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
    """First 12 hex digits of the sha256 of the resolved git common directory of cwd, which a repository's linked working copies share (cwd itself outside one)."""
    common = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--git-common-dir"], capture_output=True, text=True).stdout.strip()
    return hashlib.sha256(os.path.realpath(os.path.join(cwd, common)).encode()).hexdigest()[:12]


def points_for(event: str, role: str) -> int | None:
    """The table's points for the event and role; None when it gives that role nothing."""
    return POINTS[event].get(role, POINTS[event].get("*"))


def identity(role, pipeline) -> str | None:
    """The scored identity of a dispatch: its role; qa in the close pipeline is "close-qa", scored apart from lane qa."""
    return "close-qa" if (role, pipeline) == ("qa", "close") else role or None


def log_path() -> Path:
    """The score log: <CLAUDE_CONFIG_DIR when set and non-empty, else ~/.claude>/logs/lifecycle.jsonl. Creates nothing."""
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "logs" / "lifecycle.jsonl"


@contextmanager
def locked(log):
    """The caller's exclusive lock on <log>.lock (the file score-update.sh locks), held for the with-block."""
    os.makedirs(os.path.dirname(os.path.abspath(log)), exist_ok=True)
    with open(f"{log}.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _ob(name):  # obligation is imported late: score-update.sh puts hooks/lib on the path only after this module
    return getattr(importlib.import_module(".obligation" if __package__ else "obligation", __package__ or None), name)


def append(log, row: dict) -> bool:
    """Append one line (flushed, fsynced) under the caller's ``locked(log)``; True when written. The first row per "key" wins;
    a rating row yields only to a RATING row of the same canonical task id; a row with neither (score-update.sh's) is written as is."""
    rating, key = row.get("kind") == "rating", row.get("key")
    if (rating or key is not None) and os.path.exists(log):
        canonical = _ob("canonical_task_id")
        for _, old in read_lines(str(log)):
            if (key is not None and old.get("key") == key) or (rating and old.get("kind") == "rating"
                                                                and canonical(old.get("task_id")) == canonical(row.get("task_id"))):
                return False
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return True


def _live(rows, project, as_of):
    """Event and rating rows of the project dated before as_of, in ts order (file order breaks ties)."""
    return sorted((r for r in rows if r.get("kind") in ("event", "rating") and r.get("project") == project
                   and isinstance(r.get("ts"), str) and r["ts"] < as_of), key=lambda r: r["ts"])


def _mine(rows, identity, project, as_of):
    """(row, points) of each live row that counts for the identity: its event rows; rating rows naming it in "roles" (all for main)."""
    pairs = []
    for r in _live(rows, project, as_of):
        if r["kind"] == "event" and r.get("role") == identity:
            points = r.get("points")
        elif r["kind"] == "rating" and (identity == "main" or identity in (r.get("roles") or ())):
            points = RATING_POINTS.get(r.get("rating"))
        else:
            continue
        if type(points) is int:
            pairs.append((r, points))
    return pairs


def _fold(pairs):
    value = START
    for _, points in pairs:
        value = min(CAP, value + points)
    return value


def score(rows, identity, project, as_of) -> int:
    """Fold the identity's rows (dicts) before as_of in ts order: start 50, then s = min(100, s + points); no lower bound."""
    return _fold(_mine(rows, identity, project, as_of))


def trend(rows, identity, project, as_of) -> int:
    """The score now minus the score before the identity's 5 most recent tasks (cycles by task family, in order of first appearance)."""
    pairs, family = _mine(rows, identity, project, as_of), _ob("task_family")
    recent = list(dict.fromkeys(family(r.get("task_id")) for r, _ in pairs))[-5:]
    return _fold(pairs) - _fold(pairs[:next((i for i, (r, _) in enumerate(pairs) if family(r.get("task_id")) in recent), 0)])


def _rank(value):
    return next(r for r in RANKS if r[2] is None or value < r[2])


def tier(value) -> str:
    """Disgraced below 0; Apprentice 0-20; Journeyman 21-40; Skilled Craftsman 41-60; Senior Craftsman 61-80; Master 81-100."""
    return _rank(value)[0]


def _why(row):
    """The row's why on one line, without a task id, cut to 80 characters."""
    tid = re.escape(str(row.get("task_id") or "\0"))
    stamp = r"(?:dev-(?:command-)?)?\d{8}-\d{6}(?:-l?\d+)?"
    return " ".join(re.sub(rf"(?<![\w-]){tid}(?![\w-])|{stamp}", "", str(row.get("why") or "")).split())[:80]


def _last_miss(pairs):
    return next((_why(r) for r, points in reversed(pairs) if r["kind"] == "event" and points < 0), "")


def render_dispatch_line(rows, identity, project, as_of) -> str:
    """One or two lines for an agent at dispatch: its record and rank, then its latest negative event's why (80 characters, no task id)."""
    pairs = _mine(rows, identity, project, as_of)
    value, miss = _fold(pairs), _last_miss(pairs)
    name, span, _ = _rank(value)
    line = f"Your record ({identity}, this project): " + (
        f"{value} [Rank: {name}, {span}], trend {trend(rows, identity, project, as_of):+d} over 5 tasks." if pairs
        else f"no record yet [Rank: {name}, {span}].")
    return f'{line}\nMost recent miss: "{miss}"' if miss else line


def render_owner_summary(rows, project, as_of, task_id) -> str:
    """Three lines for the owner after a rating: every identity's score, rank, trend; the rated cycle's points and reasons; the worst and why."""
    live, family = _live(rows, project, as_of), _ob("task_family")
    names = {n for r in live for n in ([r.get("role")] if r["kind"] == "event" else ["main", *(r.get("roles") or ())])}
    stats = {n: (score(live, n, project, as_of), trend(live, n, project, as_of)) for n in sorted(filter(None, names))}
    if not stats:
        return "Scores (this project): no record yet."
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
    """The numbers as one line of ▁▂▃▅▇, each scaled between the lowest and the highest of them (rounded half up); all equal gives ▃ throughout."""
    low, high = min(values, default=0), max(values, default=0)
    return "".join("▁▂▃▅▇"[int((v - low) * 4 / (high - low) + .5) if high > low else 2] for v in values)


def _after_cycles(pairs):
    """The identity's score after each of its cycles (task families, in order of first appearance): the fold up to the next cycle's first row, the whole fold for the last."""
    family, first = _ob("task_family"), {}
    for i, (r, _) in enumerate(pairs):
        first.setdefault(family(r.get("task_id")), i)
    starts = list(first.values())
    return [_fold(pairs[:i]) for i in starts[1:] + [len(pairs)] if starts]


def render_rating_view(rows, project, as_of) -> str:
    """Plain text for the owner's /rating: each identity of the project, lowest score first (score and rank, the score's glyphs over its last 10 cycles, its last 5 events newest first), then the last 5 ratings."""
    live = _live(rows, project, as_of)
    names = {n for r in live for n in ([r.get("role")] if r["kind"] == "event" else ["main", *(r.get("roles") or ())]) if n and isinstance(n, str)}
    if not names:
        return "Scores (this project): no records yet."
    mine, lines = {n: _mine(live, n, project, as_of) for n in names}, ["Scores (this project), lowest first"]
    for n in sorted(mine, key=lambda n: (_fold(mine[n]), n)):
        rank, span, _ = _rank(value := _fold(mine[n]))
        lines += [f"{n}: {value} [Rank: {rank}, {span}]", "  trend " + (glyphs(_after_cycles(mine[n])[-10:]) or "-")]
        lines += [f"  {r.get('task_id')}  {r.get('event')}  {pts:+d}  {' '.join(str(r.get('why') or '').split())[:80]}".rstrip() for r, pts in reversed(mine[n]) if r["kind"] == "event"][:5] or ["  no events"]
    rated = [f"  {r.get('task_id')}  {r.get('rating')}" for r in reversed(live) if r["kind"] == "rating"][:5]
    return "\n".join(lines + (["Your latest ratings, newest first"] + rated if rated else ["Your ratings: none yet"]))
