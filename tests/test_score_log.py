"""The score log's one module (hooks/lib/score_log.py): its reader, its one writer, the score function and the
two renderers (owner summary, /rating view); and the reader's two callers.

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


@pytest.mark.parametrize(
    ("role", "pipeline", "expected"),
    [("qa", "close", "close-qa"), ("qa", "dev", "qa"), ("qa", None, "qa"), ("dev", "close", "dev"), ("ba", "dev", "ba"),
     ("main", "close", "main"), ("close-qa", "close", "close-qa"), ("", "close", None), (None, "close", None), (None, None, None)],
)
def test_the_scored_identity_is_the_role_except_for_the_close_pipelines_qa(role, pipeline, expected) -> None:
    assert score_log.identity(role, pipeline) == expected


def test_log_path_follows_the_config_directory_variable_and_creates_nothing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
    assert score_log.log_path() == tmp_path / "config" / "logs" / "lifecycle.jsonl"
    home_log = tmp_path / "home" / ".claude" / "logs" / "lifecycle.jsonl"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "")  # empty and unset both fall back to ~/.claude
    assert score_log.log_path() == home_log
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    assert score_log.log_path() == home_log
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("task", ["20261101-100000", "dev-20261101-100000", "20261101-100000-l2", "login-fix", "t1"])
def test_why_is_one_line_without_a_task_id_and_cut_to_80_characters(task: str) -> None:
    why = f"QA failed {task} and\nthen again for dev-command-20261101-100000-l1 because " + "the edge case was not tested " * 6
    miss = score_log._why(_event(-6, task=task, why=why))
    assert len(miss) == 80 and "\n" not in miss and miss.startswith("QA failed")
    assert not re.search(r"\d{8}-\d{6}", miss) and not re.search(rf"(?<![\w-]){re.escape(task)}(?![\w-])", miss)
    assert score_log._why(_event(-6, task=task, why=task)) == ""  # nothing is left of a why that is only a task id


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


# --------------------------------------------------------------------------
# /rating: the glyph line and the owner's terminal view
# --------------------------------------------------------------------------

NO_RECORDS = "Scores (this project): no records yet."
RATINGS_HEAD = "Your latest ratings, newest first"


def _view(rows, project=PROJECT, as_of=END) -> list[str]:
    return score_log.render_rating_view(rows, project, as_of).split("\n")


def _heads(lines: list[str]) -> list[tuple]:
    """(identity, score, rank text) of each agent's first line."""
    return [m.groups() for m in map(re.compile(r"(\S+): (-?\d+) \[Rank: (.+)\]").fullmatch, lines) if m]


def _run(deltas, role="dev") -> list:
    """One event of the role per task, a task a minute from 2026-11-01, with the reason "why <n>"."""
    return [_event(p, role, f"202611{n:02d}-100000", _ts(n), event="qa_fail" if p < 0 else "qa_first_pass", key=f"{role}{n}", why=f"why {n}")
            for n, p in enumerate(deltas, start=1)]


@pytest.mark.parametrize(
    ("values", "line"),
    [([1, 2, 3, 4, 5], "▁▂▃▅▇"), ([5, 4, 3, 2, 1], "▇▅▃▂▁"), (list(range(9)), "▁▂▂▃▃▅▅▇▇"), ([7, 7, 7], "▃▃▃"), ([42], "▃"),
     ([], ""), ([0, 100], "▁▇"), ([-10, 0, 10], "▁▃▇"), ([0.0, 0.5, 1.0], "▁▃▇"), ([50, 52, 50, 54], "▁▃▁▇")],
)
def test_the_glyph_line_scales_the_numbers_between_their_lowest_and_highest(values: list, line: str) -> None:
    assert score_log.glyphs(values) == line


def test_the_glyph_line_has_one_of_five_glyphs_per_number_and_never_falls_where_the_numbers_rise() -> None:
    for values in ([3, -1, 4, 1, -5, 9, 2, 6], list(range(-20, 21)), [1, 1, 2], [10**6, 0], [-3, -3]):
        line = score_log.glyphs(values)
        index = ["▁▂▃▅▇".index(glyph) for glyph in line]  # raises for any other glyph
        assert len(line) == len(values)
        assert [index[i] for i in sorted(range(len(values)), key=values.__getitem__)] == sorted(index)
        if len(set(values)) > 1:
            assert line[values.index(min(values))] == "▁" and line[values.index(max(values))] == "▇"


def test_agents_are_listed_from_the_lowest_score_to_the_highest_with_score_and_rank() -> None:
    rows = [_event(-6, "dev", key="1"), _event(1, "qa", event="qa_catch", key="2"),
            _event(3, "ba", event="ba_option_chosen", key="3"), _event(-40, "scribe", event="escaped", key="4"),
            _rating(5, roles=("qa",))]  # qa +3 and main +3 from the rating
    out = _view(rows)
    assert out[0] == "Scores (this project), lowest first"
    assert _heads(out) == [("scribe", "10", "Apprentice, 0-20"), ("dev", "44", "Skilled Craftsman, 41-60"),
                           ("ba", "53", "Skilled Craftsman, 41-60"), ("main", "53", "Skilled Craftsman, 41-60"),  # equal scores: by name
                           ("qa", "54", "Skilled Craftsman, 41-60")]
    assert _view([_event(2, "ba", key="1"), _event(-2, "dev", key="2")]) == _view([_event(-2, "dev", key="2"), _event(2, "ba", key="1")])  # not file order


@pytest.mark.parametrize(
    ("value", "rank"),
    [(-1, "Disgraced, <0"), (0, "Apprentice, 0-20"), (20, "Apprentice, 0-20"), (21, "Journeyman, 21-40"), (40, "Journeyman, 21-40"),
     (41, "Skilled Craftsman, 41-60"), (61, "Senior Craftsman, 61-80"), (81, "Master, 81-100"), (100, "Master, 81-100")],
)
def test_the_view_names_the_rank_and_its_range(value: int, rank: str) -> None:
    assert _view([_event(value - 50)])[1] == f"dev: {value} [Rank: {rank}]"


@pytest.mark.parametrize(
    ("deltas", "line"),
    [([2] * 5, "▁▂▃▅▇"), ([-6] * 5, "▇▅▃▂▁"), ([0] * 4, "▃▃▃▃"), ([2], "▃"), ([2, -6], "▇▁"),
     ([2] * 10, "▁▁▂▂▃▃▅▅▇▇"), ([40, 40] + [-6] * 10, "▇▇▅▅▃▃▂▂▁▁")],  # twelve cycles: only the last ten are drawn
)
def test_the_trend_line_draws_the_score_after_each_of_the_last_ten_cycles(deltas: list, line: str) -> None:
    out = _view(_run(deltas))
    assert out[2] == "  trend " + line
    assert len(line) == min(len(deltas), 10)


def test_a_cycle_is_one_step_whatever_its_lanes_and_late_rating_rows() -> None:
    rows = [_event(2, task="20261101-100000-l1", ts=_ts(1), key="1"), _event(2, task="20261101-100000-l2", ts=_ts(2), key="2"),
            _event(2, task="20261102-100000", ts=_ts(3), key="3"), _rating(5, roles=("dev",), task="dev-20261101-100000", ts=_ts(4))]
    # after the first cycle 54 (its rating comes later and counts from the second cycle on), at the end 54 + 2 + 3
    out = _view(rows)
    assert out[out.index("dev: 59 [Rank: Skilled Craftsman, 41-60]") + 1] == "  trend ▁▇"


def test_each_agent_shows_its_last_five_events_newest_first_with_task_id_event_points_and_reason() -> None:
    out = _view(_run([-6, 2, -6, 2, 2, -6, 2]))
    assert out == [
        "Scores (this project), lowest first",
        "dev: 40 [Rank: Journeyman, 21-40]",
        "  trend ▅▇▂▃▅▁▂",
        "  20261107-100000  qa_first_pass  +2  why 7",
        "  20261106-100000  qa_fail  -6  why 6",
        "  20261105-100000  qa_first_pass  +2  why 5",
        "  20261104-100000  qa_first_pass  +2  why 4",
        "  20261103-100000  qa_fail  -6  why 3",
        "Your ratings: none yet",
    ]
    # fewer than five: all of them; events at one instant: the later row first
    assert _view(_run([2, -6])[:1])[3:5] == ["  20261101-100000  qa_first_pass  +2  why 1", "Your ratings: none yet"]
    tie = [_event(2, ts=_ts(1), key="a", why="first written"), _event(2, ts=_ts(1), key="b", why="second written")]
    assert [line.split("  ")[-1] for line in _view(tie)[3:5]] == ["second written", "first written"]


def test_only_event_rows_are_listed_as_events_and_a_rating_changes_the_score_not_the_list() -> None:
    assert _view([_event(2, key="a", why="good"), _rating(5, roles=("dev",), ts=_ts(2))]) == [
        "Scores (this project), lowest first",
        "main: 53 [Rank: Skilled Craftsman, 41-60]", "  trend ▃", "  no events",
        "dev: 55 [Rank: Skilled Craftsman, 41-60]", "  trend ▃", "  20261101-100000  qa_fail  +2  good",
        RATINGS_HEAD, "  20261101-100000  5"]


def test_the_reason_is_the_rows_why_on_one_printable_line_cut_at_80_characters() -> None:
    why = "QA failed 20261101-100000:\n\tedge \x1b[31mcase\x1b[0m not tested " + "x" * 100
    out = _view([_event(-6, why=why)])
    assert len(out) == 5 and "\x1b" not in "".join(out)
    assert out[3].startswith("  20261101-100000  qa_fail  -6  QA failed 20261101-100000: edge [31mcase [0m not tested xxx")
    assert len(out[3].split("  -6  ")[1]) == 80
    assert _view([_event(-6, why="", key="a")])[3] == "  20261101-100000  qa_fail  -6"  # no reason: no trailing space


def test_the_owners_last_five_ratings_newest_first_with_task_id_and_rating() -> None:
    rows = [_rating(r, roles=("dev",), task=f"2026110{n}-100000", ts=_ts(n)) for n, r in enumerate([5, 4, 3, 1, 5, 4, 3], start=1)]
    out = _view(rows)
    assert _heads(out) == [("dev", "46", "Skilled Craftsman, 41-60"), ("main", "46", "Skilled Craftsman, 41-60")]
    assert out[out.index(RATINGS_HEAD):] == [RATINGS_HEAD, "  20261107-100000  3", "  20261106-100000  4", "  20261105-100000  5",
                                             "  20261104-100000  1", "  20261103-100000  3"]
    assert len(_view(rows[:2])) == len(_view(rows[:1])) + 1  # fewer than five: all of them
    assert _view(rows + [_rating(1, ("dev",), "20261108-100000", _ts(8), project=ELSEWHERE)]) == out  # another project's rating


def test_rows_of_other_projects_rows_without_kind_and_rows_from_as_of_on_are_never_shown() -> None:
    rows = _cycle()
    noise = [_event(-90, "intruder", "20269999-100000", _ts(5), project=ELSEWHERE, key="x"),
             _rating(1, ("intruder",), "20269999-100000", _ts(6), project=ELSEWHERE),
             {"ts": _ts(1), "agent": "ghost", "event": "old", "delta": -50, "new_score": 0},  # score-update.sh's nine keys, no kind
             {"ts": _ts(1), "project": PROJECT, "role": "ghost", "event": "qa_fail", "points": -50, "task_id": "20269998-100000"},
             _event(-90, "tardy", "20261101-100000", _ts(9), key="y")]
    text = "\n".join(_view(rows + noise, as_of=_ts(9)))
    assert text.split("\n") == _view(rows)
    assert not any(word in text for word in ("intruder", "ghost", "tardy", "20269999", "20269998"))


def test_main_appears_when_the_owner_rated_and_every_role_of_a_rating_is_an_agent() -> None:
    assert [h[0] for h in _heads(_view([_event(2, key="1")]))] == ["dev"]
    out = _view([_event(2, key="1"), _rating(4, roles=("scribe",))])
    assert [h[0] for h in _heads(out)] == ["main", "scribe", "dev"]  # 51, 51 (by name), 52
    assert out[out.index("scribe: 51 [Rank: Skilled Craftsman, 41-60]"):][1:3] == ["  trend ▃", "  no events"]


def test_an_empty_or_unknown_project_gets_one_line() -> None:
    assert score_log.render_rating_view([], PROJECT, END) == NO_RECORDS
    assert score_log.render_rating_view(_cycle(), ELSEWHERE, END) == NO_RECORDS
    assert score_log.render_rating_view(_cycle(), PROJECT, _ts(0)) == NO_RECORDS  # nothing is dated before as_of
    assert score_log.render_rating_view([{"agent": "dev"}, {"kind": "note", "project": PROJECT}, {"kind": "event"}], PROJECT, END) == NO_RECORDS


def test_a_role_that_is_not_a_name_is_not_an_agent() -> None:
    odd = [_event(2, role=["dev"], key="a"), _event(2, role=7, key="b"), _event(2, role=None, key="c"), _event(2, role="", key="d")]
    assert score_log.render_rating_view(odd, PROJECT, END) == NO_RECORDS
    assert [h[0] for h in _heads(_view(odd + [_rating(5, roles=(None, 7, "dev"))]))] == ["dev", "main"]


def test_an_identity_with_no_scored_row_shows_a_dash_for_its_trend_and_no_events() -> None:
    assert _view([_rating(2, roles=())]) == [
        "Scores (this project), lowest first", "main: 50 [Rank: Skilled Craftsman, 41-60]", "  trend -", "  no events",
        RATINGS_HEAD, "  20261101-100000  2"]


def test_ten_agents_stay_a_handful_of_lines_each() -> None:
    rows = [_event(-1, f"agent{i}", f"2026110{n}-100000", _ts(n), event="rerun_gap", key=f"{i}-{n}") for i in range(10) for n in range(1, 9)]
    out = _view(rows)
    assert len(out) == 1 + 10 * 7 + 1  # a head, the trend and five events for each, the ratings line
    assert [h[0] for h in _heads(out)] == [f"agent{i}" for i in range(10)] and max(map(len, out)) < 80


def test_the_view_is_plain_text_and_only_reads_the_rows() -> None:
    rows = _cycle() + [_rating(1, ("ba",), "20261102-100000", _ts(6)), _event(-60, "dev", ts=_ts(7), key="z", why="needs a fix")]
    before = json.dumps(rows, sort_keys=True)
    text = score_log.render_rating_view(rows, PROJECT, END)
    assert "[Rank: Disgraced, <0]" in text  # a rank range may hold "<"; a tag never opens
    assert not re.search(r"</?[A-Za-z!][^>]*>", text) and "\x1b" not in text
    assert not re.search(r"[\x00-\x09\x0b-\x1f\x7f]", text) and {c for c in text if ord(c) > 127} <= set("▁▂▃▅▇")
    assert json.dumps(rows, sort_keys=True) == before and score_log.render_rating_view(rows, PROJECT, END) == text
