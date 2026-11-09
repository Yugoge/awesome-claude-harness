"""The score log's one module (hooks/lib/score_log.py): its reader, its one writer, the score function and the
two renderers; and the reader's two callers.

scripts/score-update.sh and scripts/score-inject.sh both call read_lines (through the scripts/lib/score_log.py
re-export) in place of a parse of their own and keep their own exit code for a refused log: 2 and 1.
The callers run from a scratch copy whose venv/bin/activate is empty, so the
test needs no installed venv and runs the python3 on PATH."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "hooks" / "lib"))
import score_log  # noqa: E402

LINE = (
    '{"ts":"2026-05-2%dT10:00:00Z","agent":"dev","event":"close_success_qa_pass",'
    '"prev_score":50,"new_score":52,"delta":2,"unclamped_score":52,"actor":"orchestrator","reason":"test"}'
)
# tests/score-inject-contract/test-inject-branches.sh's malformed ledger.
MALFORMED = (
    '{"ts":"2026-05-20T10:00:00Z","agent":"dev","event":"score_baseline_import","prev_score":50,'
    '"new_score":50,"delta":0,"unclamped_score":50,"actor":"migration","reason":"baseline import"}\n'
    "{invalid: not, json,,\n" + LINE % 1 + "\n"
)


def _log(tmp_path: Path, text: str | bytes) -> str:
    path = tmp_path / "lifecycle.jsonl"
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    return str(path)


def test_entries_keep_their_line_numbers_and_a_partial_last_line_is_skipped(
    tmp_path: Path,
) -> None:
    path = _log(tmp_path, LINE % 1 + "\n\n" + LINE % 2 + '\n{"ts": "2026-05-2')
    assert [(number, entry["ts"]) for number, entry in score_log.read_lines(path)] == [
        (1, "2026-05-21T10:00:00Z"),
        (3, "2026-05-22T10:00:00Z"),
    ]


@pytest.mark.parametrize("bad", ["{invalid: not, json,,", "[1, 2]", "7"])
def test_a_malformed_line_before_the_last_is_refused(tmp_path: Path, bad: str) -> None:
    path = _log(tmp_path, LINE % 1 + "\n" + bad + "\n" + LINE % 2 + "\n")
    with pytest.raises(score_log.ScoreLogError, match="line 2 .*not final line"):
        score_log.read_lines(path)


@pytest.mark.parametrize("kind", ["directory", "undecodable"])
def test_an_unreadable_log_is_refused(tmp_path: Path, kind: str) -> None:
    if kind == "directory":
        path = tmp_path / "lifecycle.jsonl"
        path.mkdir()
        path = str(path)
    else:
        path = _log(tmp_path, b"\xff\xfe" + (LINE % 1).encode())
    with pytest.raises(score_log.ScoreLogError, match="cannot read"):
        score_log.read_lines(path)


@pytest.fixture()
def scratch_scripts(tmp_path: Path) -> Path:
    root = tmp_path / "home"
    (root / "scripts" / "lib").mkdir(parents=True)
    (root / "venv" / "bin").mkdir(parents=True)
    (root / "venv" / "bin" / "activate").write_text("", encoding="utf-8")
    for name in ("score-update.sh", "score-inject.sh"):
        shutil.copy2(REPO_ROOT / "scripts" / name, root / "scripts" / name)
    shutil.copy2(REPO_ROOT / "scripts" / "lib" / "score_log.py", root / "scripts" / "lib")
    # score-update.sh's agents are the roster: hooks/lib/roster.py over agents/; the re-export loads the one
    # module, hooks/lib/score_log.py; its rows go through close_rating.py's append_row.
    (root / "hooks" / "lib").mkdir(parents=True)
    for name in ("roster.py", "close_rating.py", "score_log.py"):
        shutil.copy2(REPO_ROOT / "hooks" / "lib" / name, root / "hooks" / "lib")
    shutil.copytree(REPO_ROOT / "agents", root / "agents")
    return root


@pytest.mark.skipif(shutil.which("flock") is None, reason="needs util-linux flock")
@pytest.mark.parametrize(
    ("script", "arguments", "refused_exit"),
    [
        ("score-inject.sh", ["--agent", "dev"], 1),
        ("score-update.sh", ["--agent", "dev", "--event", "qa_first_pass"], 2),
    ],
)
def test_each_caller_keeps_its_exit_code_and_its_use_of_the_lines(
    tmp_path: Path, scratch_scripts: Path, script: str, arguments: list, refused_exit: int
) -> None:
    def run(text: str) -> subprocess.CompletedProcess:
        path = _log(tmp_path, text)
        return subprocess.run(
            ["bash", str(scratch_scripts / "scripts" / script), *arguments, "--lifecycle-file", path],
            capture_output=True,
            text=True,
            timeout=60,
        )

    refused = run(MALFORMED)
    assert refused.returncode == refused_exit, refused.stderr
    assert "malformed JSONL at line 2" in refused.stderr and "INJECTION_PROOF" not in refused.stdout

    accepted = run(LINE % 1 + "\n" + '{"ts": "partial')
    assert accepted.returncode == 0, accepted.stderr
    if script == "score-inject.sh":
        assert "Recent events: close_success_qa_pass(+2)" in accepted.stdout
    else:
        assert accepted.stdout.strip() == "dev:qa_first_pass:52->52 (delta=0, unclamped=52)"


@pytest.mark.skipif(shutil.which("flock") is None, reason="needs util-linux flock")
def test_score_update_agents_are_the_roster(tmp_path: Path, scratch_scripts: Path) -> None:
    # P1b row 18: an agent is scored because agents/<agent>.md declares it, so
    # the script keeps no list: graphify scores, an undeclared name is refused
    # until its agent file exists.
    log = tmp_path / "lifecycle.jsonl"

    def run(agent: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(scratch_scripts / "scripts" / "score-update.sh"), "--agent", agent,
             "--event", "qa_first_pass", "--lifecycle-file", str(log)],
            capture_output=True, text=True, timeout=60,
        )

    assert run("graphify").returncode == 0
    refused = run("wizard")
    assert refused.returncode == 1 and "unknown agent 'wizard'" in refused.stderr
    (scratch_scripts / "agents" / "wizard.md").write_text("---\nname: wizard\n---\n", encoding="utf-8")
    assert run("wizard").returncode == 0


# --------------------------------------------------------------------------
# The one module: rows, the score function, tiers, trend, the two views, the one writer
# --------------------------------------------------------------------------

PROJECT, ELSEWHERE, END = "a" * 12, "b" * 12, "2999-01-01T00:00:00Z"


def _ts(n: int) -> str:
    return f"2026-11-01T{n // 3600:02d}:{n % 3600 // 60:02d}:{n % 60:02d}Z"


def _event(points=-4, role="dev", task="20261101-100000", ts=None, project=PROJECT, why="edge case not tested",
           event="qa_fail", key=None) -> dict:
    ts = ts or _ts(1)
    return {"kind": "event", "ts": ts, "project": project, "task_id": task, "role": role, "event": event,
            "points": points, "key": key or f"{task}:{event}:{role}:{ts}", "why": why, "ref": "ref"}


def _rating(rating=5, roles=("dev", "qa"), task="20261101-100000", ts=None, project=PROJECT) -> dict:
    return {"kind": "rating", "ts": ts or _ts(2), "project": project, "task_id": task, "rating": rating,
            "roles": list(roles), "tool_use_id": "toolu_1"}


def _score(rows, identity="dev", project=PROJECT, as_of=END) -> int:
    return score_log.score(rows, identity, project, as_of)


def _log_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_the_scripts_name_re_exports_the_one_module(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("score_log_scripts_name", REPO_ROOT / "scripts" / "lib" / "score_log.py")
    shim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shim)
    for name in ("read_lines", "ScoreLogError", "append", "locked", "score", "tier", "trend", "project_key"):
        assert callable(getattr(shim, name)), name
    good = _log(tmp_path, LINE % 1 + "\n" + LINE % 2 + '\n{"ts": "partial')
    assert shim.read_lines(good) == score_log.read_lines(good) != []
    with pytest.raises(shim.ScoreLogError, match="line 2 .*not final line"):
        shim.read_lines(_log(tmp_path, MALFORMED))


def test_rows_without_kind_are_read_and_never_scored(tmp_path: Path) -> None:
    nine_keys = json.loads(LINE % 1)
    four_keys = {"ts": _ts(5), "task_id": "20261101-100000", "rating": 1, "tool_use_id": "toolu_1"}
    # not a legacy shape, but with every scored field and no kind: still not scored
    no_kind = {k: v for k, v in _event(points=-40).items() if k != "kind"}
    rows = [nine_keys, four_keys, no_kind, {**_rating(1), "kind": None}]
    path = _log(tmp_path, "".join(json.dumps(row) + "\n" for row in rows))
    assert [row for _, row in score_log.read_lines(path)] == rows
    assert _score(rows) == _score(rows, "main") == 50
    assert score_log.render_dispatch_line(rows, "dev", PROJECT, END) == \
        "Your record (dev, this project): no record yet [Rank: Skilled Craftsman, 41-60]."
    assert score_log.render_owner_summary(rows, PROJECT, END, "20261101-100000") == "Scores (this project): no record yet."


@pytest.mark.parametrize(
    ("points", "expected"),
    [
        ([], 50),
        ([2, -4, 3], 51),
        ([60, 60], 100),
        ([60, 60, -6], 94),  # the cap bites at each step: 100 - 6, not 110 - 6 capped once
        ([-30, -30, -30], -40),  # no lower bound
        ([-60, 60], 50),
    ],
)
def test_the_fold_starts_at_50_caps_at_100_and_has_no_floor(points: list, expected: int) -> None:
    rows = [_event(p, ts=_ts(n + 1), task=f"2026110{n % 9 + 1}-100000") for n, p in enumerate(points)]
    assert _score(rows) == expected


def test_as_of_is_exclusive_and_rows_fold_in_ts_order_with_file_order_breaking_ties() -> None:
    first, second, third = _event(10, ts=_ts(1)), _event(10, ts=_ts(2)), _event(10, ts=_ts(3))
    assert [_score([first, second, third], as_of=_ts(n)) for n in (1, 2, 3, 4)] == [50, 60, 70, 80]
    # a row later in the file but earlier in time folds first: -10 then +60 is 100; file order would give 90
    late_file_order = [_event(60, ts=_ts(2), key="a"), _event(-10, ts=_ts(1), key="b")]
    assert _score(late_file_order) == 100
    # equal ts: file order decides (+60 -10 = 90, -10 +60 = 100)
    assert _score([_event(60, ts=_ts(1), key="a"), _event(-10, ts=_ts(1), key="b")]) == 90
    assert _score([_event(-10, ts=_ts(1), key="b"), _event(60, ts=_ts(1), key="a")]) == 100


def test_rows_of_another_project_or_identity_do_not_count() -> None:
    rows = [_event(5, role="dev", key="1"), _event(7, role="qa", key="2"), _event(-30, project=ELSEWHERE, key="3"),
            _event(9, role="close-qa", key="4"), _event(1, role="main", key="5")]
    assert [_score(rows, who) for who in ("dev", "qa", "close-qa", "main", "ba")] == [55, 57, 59, 51, 50]
    assert _score(rows, "dev", ELSEWHERE) == 20
    assert _score(rows, "dev", "c" * 12) == 50


def test_rating_rows_count_for_the_identities_in_roles_and_for_main() -> None:
    def seen(rating: int) -> list:
        row = _rating(rating, roles=("dev", "qa"))
        return [_score([row], who) for who in ("dev", "qa", "main", "ba")]

    assert seen(5) == [53, 53, 53, 50] and seen(4) == [51, 51, 51, 50]
    assert seen(3) == [47, 47, 47, 50] and seen(1) == [44, 44, 44, 50]
    assert seen(2) == [50, 50, 50, 50]  # the owner's "1-2" is stored as 1; a stray 2 is not scored
    assert _score([_rating(5, roles=())], "main") == 53
    assert _score([_rating(5, project=ELSEWHERE)], "main") == 50
    # an event row with the rating's task id and the rating fold together in ts order
    assert _score([_event(-6, ts=_ts(1)), _rating(5, ts=_ts(2))]) == 47


@pytest.mark.parametrize(
    ("value", "name"),
    [(-1, "Disgraced"), (0, "Apprentice"), (20, "Apprentice"), (21, "Journeyman"), (40, "Journeyman"),
     (41, "Skilled Craftsman"), (60, "Skilled Craftsman"), (61, "Senior Craftsman"), (80, "Senior Craftsman"),
     (81, "Master"), (100, "Master"), (-130, "Disgraced")],
)
def test_tiers_at_their_boundaries(value: int, name: str) -> None:
    assert score_log.tier(value) == name


def test_trend_is_the_score_now_minus_the_score_before_the_five_most_recent_tasks() -> None:
    def trend(rows) -> int:
        return score_log.trend(rows, "dev", PROJECT, END)

    rows = [_event(2, ts=_ts(n), task=f"2026110{n}-100000") for n in range(1, 8)]
    assert (_score(rows), trend(rows), trend(rows[:3]), trend([])) == (64, 10, 6, 0)
    # a late rating of the oldest task is part of the change since the 5th most recent task began
    assert trend(rows[:6] + [_rating(5, roles=("dev",), task="20261101-100000", ts=_ts(10))]) == 13
    # lanes of one cycle and its rating (any id prefix) are one task; five tasks reach back to the start
    cycle = [_event(2, ts=_ts(5), task="20261105-100000-l1", key="x"), _event(2, ts=_ts(6), task="20261105-100000-l2", key="y"),
             _rating(4, roles=("dev",), task="dev-20261105-100000", ts=_ts(7))]
    five = [_event(2, ts=_ts(n), task=f"2026110{n}-100000") for n in range(1, 5)] + cycle
    assert (_score(five), trend(five)) == (63, 13)
    # at the cap the trend is the real change: 30 tasks of +2 end at 100, and so did the score 5 tasks earlier
    full = [_event(2, ts=_ts(n), task=f"2026{n // 28 + 10:02d}{n % 28 + 1:02d}-100000-x{n}") for n in range(30)]
    assert (_score(full), trend(full)) == (100, 0)


@pytest.mark.parametrize(
    ("event", "role", "points"),
    [("qa_first_pass", "dev", 2), ("qa_first_pass", "ba", 1), ("qa_fail", "dev", -6), ("qa_fail", "ba", -6),
     ("qa_catch", "qa", 1), ("escaped", "dev", -7), ("escaped", "ba", -7), ("escaped", "qa", -3),
     ("close_catch", "close-qa", 1), ("rerun_gap", "dev", -2), ("rerun_gap", "qa", -2), ("stop_blocked", "ba", -1),
     ("main_refused", "main", -1), ("main_stop_blocked", "main", -1), ("ba_option_chosen", "ba", 3),
     ("ba_root_cause_refuted", "ba", -4), ("qa_catch", "dev", None), ("qa_fail", "qa", None)],
)
def test_the_point_table(event: str, role: str, points: int | None) -> None:
    assert score_log.points_for(event, role) == points


def test_the_rating_points_and_the_proportions_between_events() -> None:
    assert score_log.RATING_POINTS == {5: 3, 4: 1, 3: -3, 1: -6}
    pts = score_log.points_for
    # a defect found only at close costs more than one lane QA caught; a spec fault weighs as an implementation fault
    assert pts("escaped", "dev") < pts("qa_fail", "dev") == pts("qa_fail", "ba") < pts("ba_root_cause_refuted", "ba") < 0
    assert pts("escaped", "qa") > pts("escaped", "dev")


def test_two_lane_qa_failures_in_three_tasks_drop_dev_exactly_one_rank_and_only_positive_events_raise_it() -> None:
    def dev_after(*events) -> list:
        rows = [_event(score_log.points_for(name, "dev"), ts=_ts(n + 1), task=f"2026110{n + 1}-100000", event=name,
                       key=f"k{n}") for n, name in enumerate(events)]
        return [_score(rows), score_log.tier(_score(rows)), rows]

    for order in (("qa_fail", "qa_fail", "qa_first_pass"), ("qa_fail", "qa_first_pass", "qa_fail"),
                  ("qa_first_pass", "qa_fail", "qa_fail")):
        value, name, rows = dev_after(*order)
        assert (value, name) == (40, "Journeyman")  # one rank below Skilled Craftsman (50 at the start), not two
        assert _score(rows, as_of="2027-01-01T00:00:00Z") == _score(rows, as_of=END) == 40  # time heals nothing
    rows = dev_after("qa_fail", "qa_fail", "qa_first_pass")[2]
    assert score_log.tier(_score(rows + [_event(0, ts=_ts(9), key="zero")])) == "Journeyman"
    assert score_log.tier(_score(rows + [_event(-6, ts=_ts(9), key="again")])) == "Journeyman"
    assert _score(rows + [_event(score_log.points_for("qa_first_pass", "dev"), ts=_ts(9), key="up")]) == 42
    assert score_log.tier(42) == "Skilled Craftsman"


def test_failing_tasks_keep_falling_below_zero_and_a_long_good_run_stops_at_100() -> None:
    def run(*per_task) -> list:
        rows, seen = [], []
        for n in range(40):
            task = f"2026{n // 28 + 11:02d}{n % 28 + 1:02d}-100000"
            rows += [_event(p, ts=_ts(2 * n + 1), task=task, key=f"{n}:{i}") for i, p in enumerate(per_task)]
            seen.append(_score(rows))
        return seen

    failing = run(score_log.points_for("qa_fail", "dev"))
    assert all(a > b for a, b in zip(failing, failing[1:])) and failing[8] < 0 and failing[-1] == 50 - 40 * 6
    assert score_log.tier(failing[-1]) == "Disgraced"
    good = run(score_log.points_for("qa_first_pass", "dev") + score_log.RATING_POINTS[5])
    assert good[9] == 100 and good[-1] == 100 and max(good) == 100


@pytest.mark.skipif(shutil.which("flock") is None, reason="needs util-linux flock")
def test_the_fold_equals_the_running_new_score_of_score_update(tmp_path: Path, scratch_scripts: Path) -> None:
    log = tmp_path / "lifecycle.jsonl"
    deltas = [40, 40, 40, -60, -60, -60, 30, -5]  # caps at 100 twice, passes below 0, no floor
    for delta in deltas:
        run = subprocess.run(
            ["bash", str(scratch_scripts / "scripts" / "score-update.sh"), "--agent", "dev", "--delta", str(delta),
             "--reason", "fold check", "--lifecycle-file", str(log)], capture_output=True, text=True, timeout=60)
        assert run.returncode == 0, run.stderr
    legacy = _log_rows(log)
    events = [_event(row["delta"], ts=row["ts"], task=f"2026110{n + 1}-100000", key=f"k{n}") for n, row in enumerate(legacy)]
    assert [row["new_score"] for row in legacy] == [90, 100, 100, 40, -20, -80, -50, -55]
    assert [_score(events[: n + 1]) for n in range(len(events))] == [row["new_score"] for row in legacy]
    assert _score(events, as_of=_ts(0)) == 50 and len({row["ts"] for row in legacy}) < len(legacy)  # ties kept file order
    assert score_log.read_lines(str(log))  # the script's rows still read; none of them is scored
    assert _score(legacy) == 50


def test_append_writes_one_line_and_the_first_row_per_key_wins(tmp_path: Path) -> None:
    log = tmp_path / "logs" / "lifecycle.jsonl"
    with score_log.locked(log):  # makes the log's directory
        assert score_log.append(log, _event(-4, key="k1", why="naïve")) is True
        assert score_log.append(log, _event(-9, key="k1", why="again")) is False
        assert score_log.append(log, _event(-4, key="k2")) is True
    assert [(row["key"], row["points"]) for row in _log_rows(log)] == [("k1", -4), ("k2", -4)]
    assert "naïve" in log.read_text(encoding="utf-8")  # not escaped
    assert [row["key"] for _, row in score_log.read_lines(str(log))] == ["k1", "k2"]
    assert Path(f"{log}.lock").exists()


def test_a_row_with_neither_kind_nor_key_is_written_unchanged_without_reading_the_log(tmp_path: Path) -> None:
    log = tmp_path / "lifecycle.jsonl"
    log.write_text("{damaged\n" + LINE % 1 + "\n", encoding="utf-8")
    row = json.loads(LINE % 2)
    with score_log.locked(log):
        assert score_log.append(log, row) is True
        assert score_log.append(log, row) is True  # no key, no dedup
    assert log.read_text(encoding="utf-8").splitlines()[2:] == [json.dumps(row, ensure_ascii=False)] * 2


def test_a_damaged_log_is_refused_by_the_dedup_read_but_not_for_a_row_that_needs_none(tmp_path: Path) -> None:
    log = tmp_path / "lifecycle.jsonl"
    log.write_text("{damaged\n" + json.dumps(_event(key="k1")) + "\n", encoding="utf-8")
    for row in (_event(key="k1"), _event(key="k2"), _rating()):
        with pytest.raises(score_log.ScoreLogError, match="line 1 .*not final line"):
            score_log.append(log, row)
    assert score_log.append(log, json.loads(LINE % 1)) is True  # score-update.sh's row: no dedup, no read
    assert len(log.read_text(encoding="utf-8").splitlines()) == 3


def test_rating_dedup_compares_rating_rows_only_by_canonical_task_id(tmp_path: Path) -> None:
    log = tmp_path / "lifecycle.jsonl"
    task = "20261101-100000"
    log.write_text(
        # P4's four-key rating row and event rows of the same task: none of them stops a rating row
        json.dumps({"ts": _ts(1), "task_id": task, "rating": 4, "tool_use_id": "p4"}) + "\n"
        + json.dumps(_event(task=task, key="e1")) + "\n" + json.dumps(_event(task=f"dev-{task}", key="e2")) + "\n",
        encoding="utf-8")
    assert score_log.append(log, _rating(4, task=task, ts=_ts(3))) is True
    assert score_log.append(log, _rating(5, task=f"dev-{task}", ts=_ts(4))) is False  # same canonical id
    assert score_log.append(log, _rating(5, task=f"dev-command-{task}", ts=_ts(4))) is False
    assert score_log.append(log, _rating(5, task="20261102-100000", ts=_ts(5))) is True
    assert score_log.append(log, _event(task=task, key="e3")) is True  # a rating never stops an event
    assert [(row.get("kind"), row["task_id"]) for row in _log_rows(log)][3:] == [
        ("rating", task), ("rating", "20261102-100000"), ("event", task)]


CHILD = """
import os, sys, time
sys.path.insert(0, sys.argv[1])
import score_log
log, number, key, gate = sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5]
row = {"kind": "event", "ts": "2026-11-01T00:00:01Z", "project": "p", "task_id": "t%d" % number, "role": "dev",
       "event": "qa_fail", "points": -6, "key": key if key != "-" else "k%d" % number, "why": "x" * 20000, "ref": "r"}
print("ready", flush=True)
while not os.path.exists(gate):
    time.sleep(0.0005)
with score_log.locked(log):
    print(score_log.append(log, row))
"""


def _children(log: Path, key: str, count: int = 20) -> list:
    """Start the writers, let them all load the module, then release them together."""
    gate = log.parent.parent / "go"
    log.parent.mkdir(parents=True, exist_ok=True)
    procs = [subprocess.Popen([sys.executable, "-B", "-c", CHILD, str(REPO_ROOT / "hooks" / "lib"), str(log), str(n), key,
                               str(gate)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for n in range(count)]
    assert [proc.stdout.readline().strip() for proc in procs] == ["ready"] * count
    gate.touch()
    results = [(proc.wait(timeout=120), proc.stdout.read().strip(), proc.stderr.read()) for proc in procs]
    assert [code for code, _, _ in results] == [0] * count, results
    return [out for _, out, _ in results]


def test_locked_holds_the_exclusive_lock_on_the_log_lock_file(tmp_path: Path) -> None:
    import fcntl

    log = tmp_path / "logs" / "lifecycle.jsonl"
    with score_log.locked(log):
        with open(f"{log}.lock", "a") as other, pytest.raises(BlockingIOError):
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with open(f"{log}.lock", "a") as other:
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)  # released with the block


@pytest.mark.skipif(shutil.which("flock") is None, reason="needs util-linux flock")
def test_twenty_parallel_appends_from_separate_processes_give_twenty_intact_rows(tmp_path: Path) -> None:
    log = tmp_path / "logs" / "lifecycle.jsonl"
    assert _children(log, "-") == ["True"] * 20
    rows = _log_rows(log)  # every line parses
    assert len(rows) == 20 and {row["key"] for row in rows} == {f"k{n}" for n in range(20)}
    assert all(row["why"] == "x" * 20000 for row in rows)
    assert len(score_log.read_lines(str(log))) == 20


@pytest.mark.skipif(shutil.which("flock") is None, reason="needs util-linux flock")
def test_twenty_parallel_appends_of_one_key_write_it_once(tmp_path: Path) -> None:
    log = tmp_path / "logs" / "lifecycle.jsonl"
    assert sorted(_children(log, "same")) == ["False"] * 19 + ["True"]
    assert len(_log_rows(log)) == 1


def _git(repo: Path, *args: str) -> None:
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "PATH": os.environ["PATH"], "HOME": str(repo.parent)}
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=test", "-c", "user.email=test@example.invalid", *args],
                   check=True, capture_output=True, env=env)


def test_project_key_is_the_hash_of_the_resolved_git_common_directory(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("needs git")
    one, two, plain = tmp_path / "one", tmp_path / "two", tmp_path / "plain"
    for repo in (one, two):
        subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    _git(one, "commit", "-q", "--allow-empty", "-m", "first")
    _git(one, "worktree", "add", "-q", "--detach", str(tmp_path / "linked"))  # a linked working copy of one, no branch
    (one / "src" / "deep").mkdir(parents=True)
    plain.mkdir()
    (tmp_path / "link").symlink_to(one)
    key = score_log.project_key(one)
    assert re.fullmatch(r"[0-9a-f]{12}", key)
    assert key == hashlib.sha256(str((one / ".git").resolve()).encode()).hexdigest()[:12]
    # the main checkout, a subdirectory of it, a symlink to it and its linked working copy are one project
    assert {score_log.project_key(path) for path in (one / "src" / "deep", tmp_path / "link", tmp_path / "linked")} == {key}
    assert score_log.project_key(two) != key and score_log.project_key(plain) != key
    # outside a repository the directory itself is the identity
    assert score_log.project_key(plain) == hashlib.sha256(str(plain.resolve()).encode()).hexdigest()[:12]
    assert str(tmp_path) not in key


def test_the_dispatch_line_is_one_line_with_no_record_and_two_with_a_miss() -> None:
    assert score_log.render_dispatch_line([], "dev", PROJECT, END) == \
        "Your record (dev, this project): no record yet [Rank: Skilled Craftsman, 41-60]."
    good = [_event(2, event="qa_first_pass", key="a")]
    assert score_log.render_dispatch_line(good, "dev", PROJECT, END) == \
        "Your record (dev, this project): 52 [Rank: Skilled Craftsman, 41-60], trend +2 over 5 tasks."
    rows = [_event(-6, ts=_ts(1), why="old miss", key="a"), _event(-6, ts=_ts(2), why="edge case not tested", key="b"),
            _event(3, ts=_ts(3), why="a good one", key="c")]
    assert score_log.render_dispatch_line(rows, "dev", PROJECT, END).split("\n") == [
        "Your record (dev, this project): 41 [Rank: Skilled Craftsman, 41-60], trend -9 over 5 tasks.",
        'Most recent miss: "edge case not tested"']
    assert score_log.render_dispatch_line(rows, "dev", PROJECT, _ts(3)).splitlines()[0].startswith("Your record (dev, this project): 38 [Rank: Journeyman")
    assert len(score_log.render_dispatch_line(rows, "qa", PROJECT, END).splitlines()) == 1  # no row of qa's own


@pytest.mark.parametrize(
    ("value", "rank"),
    [(-1, "Disgraced, <0"), (0, "Apprentice, 0-20"), (20, "Apprentice, 0-20"), (21, "Journeyman, 21-40"),
     (41, "Skilled Craftsman, 41-60"), (61, "Senior Craftsman, 61-80"), (81, "Master, 81-100"), (100, "Master, 81-100")],
)
def test_the_dispatch_line_names_the_rank_and_its_range(value: int, rank: str) -> None:
    line = score_log.render_dispatch_line([_event(value - 50)], "dev", PROJECT, END)
    assert line.split("\n")[0].startswith(f"Your record (dev, this project): {value} [Rank: {rank}]")


@pytest.mark.parametrize("task", ["20261101-100000", "dev-20261101-100000", "20261101-100000-l2", "login-fix", "t1"])
def test_the_miss_line_has_no_task_id_is_one_line_and_is_cut_to_80_characters(task: str) -> None:
    why = f"QA failed {task} and\nthen again for dev-command-20261101-100000-l1 because " + "the edge case was not tested " * 6
    row = _event(-6, task=task, why=why)
    line = score_log.render_dispatch_line([row], "dev", PROJECT, END)
    assert len(line.split("\n")) == 2
    miss = re.fullmatch(r'Most recent miss: "(.*)"', line.split("\n")[1]).group(1)
    assert len(miss) == 80 and "\n" not in miss
    assert not re.search(r"\d{8}-\d{6}", line) and not re.search(rf"(?<![\w-]){re.escape(task)}(?![\w-])", miss)
    assert miss.startswith("QA failed")


def test_a_miss_with_no_why_left_gives_one_line() -> None:
    assert len(score_log.render_dispatch_line([_event(-6, why="", key="a")], "dev", PROJECT, END).splitlines()) == 1
    assert len(score_log.render_dispatch_line([_event(-6, why="20261101-100000", key="a")], "dev", PROJECT, END).splitlines()) == 1


def _cycle() -> list:
    task = "20261101-100000"
    return [
        _event(2, "ba", task, _ts(1), event="qa_first_pass", key="1", why="spec passed"),
        _event(-6, "dev", task, _ts(2), why="edge case not tested", key="2"),
        _event(1, "qa", task, _ts(3), event="qa_catch", why="caught it", key="3"),
        _rating(4, ("ba", "dev", "qa"), task, _ts(4)),
        _event(-1, "main", "20261031-090000", _ts(0), event="main_refused", why="old cycle", key="4"),
    ]


def test_the_owner_summary_has_scores_the_cycle_points_and_the_worst_identity() -> None:
    summary = score_log.render_owner_summary(_cycle(), PROJECT, END, "20261101-100000")
    lines = summary.split("\n")
    assert len(lines) <= 5
    assert lines[0] == ("Scores (this project): ba 53 Skilled Craftsman (+3) | dev 45 Skilled Craftsman (-5) | "
                        "main 50 Skilled Craftsman (+0) | qa 52 Skilled Craftsman (+2)")
    assert lines[1].startswith("This cycle 20261101-100000: ") and "dev -6 (edge case not tested)" in lines[1]
    assert "qa +1 (caught it)" in lines[1] and lines[1].endswith("rating 4: +1 each") and "old cycle" not in lines[1]
    assert lines[2] == 'Worst: dev (Skilled Craftsman, 45); last miss: "edge case not tested"'


def test_the_owner_summary_edges() -> None:
    task = "20261101-100000"
    rows = _cycle()
    # rows of another project, and rows from as_of on, do not appear
    other = rows + [_event(-90, "dev", task, _ts(5), project=ELSEWHERE, key="x"), _event(-90, "qa", task, _ts(9), key="y")]
    assert score_log.render_owner_summary(other, PROJECT, _ts(9), task) == score_log.render_owner_summary(rows, PROJECT, END, task)
    # a worst identity with no negative event; a cycle with no rows
    fine = [_event(2, "dev", task, _ts(1), event="qa_first_pass", key="1")]
    lines = score_log.render_owner_summary(fine, PROJECT, END, "20261102-100000").split("\n")
    assert lines[1] == "This cycle 20261102-100000: no scored events"
    assert lines[2] == "Worst: dev (Skilled Craftsman, 52); no negative event"
    # equal scores: the worse trend is the worst, whatever the names ("ba" sorts first but is on the way up)
    tie = [_event(10 if who == "qa" else -10, who, "20261101-100000", _ts(1), key=f"{who}0", event="qa_fail") for who in ("qa", "ba")]
    for n in range(2, 7):
        tie += [_event(-2 if who == "qa" else 2, who, f"2026110{n}-100000", _ts(n), key=f"{who}{n}", event="qa_fail") for who in ("qa", "ba")]
    lines = score_log.render_owner_summary(tie, PROJECT, END, "20261106-100000").split("\n")
    assert lines[0] == "Scores (this project): ba 50 Skilled Craftsman (+10) | qa 50 Skilled Craftsman (-10)"
    assert lines[2].startswith("Worst: qa (Skilled Craftsman, 50)")
    # many identities stay within five lines; lanes and the dev- prefix belong to the rated cycle
    many = [_event(-1, name, f"dev-{task}-l1", _ts(n + 1), event="rerun_gap", key=str(n), why=f"{name} was rerun")
            for n, name in enumerate(("ba", "dev", "qa", "close-qa", "graphify", "main", "scribe"))]
    lines = score_log.render_owner_summary(many, PROJECT, END, task).split("\n")
    assert len(lines) <= 5 and lines[1].count(" -1 (") == 7
    assert lines[2].startswith("Worst: ba (")  # equal scores and trends: the first name
