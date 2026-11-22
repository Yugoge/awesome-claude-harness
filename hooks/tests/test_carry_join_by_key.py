"""The carry-over joins the score log by the log's own repeat rule (score_log.append_all: the first row per key wins, a
rating row yields to a rating row of the same canonical task id), not by identical line: an event the new version records
again after the takeover has another timestamp and must not be scored twice. Running the step again changes nothing.

Safety: HOME, the state locations and both old places are directories of tmp_path; nothing of this machine is read or moved."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hooks" / "lib"))
sys.path.insert(0, str(ROOT / "scripts" / "install"))

PROJECT, AS_OF = "p0", "2027-01-01T00:00:00Z"


def _event(ts, key="k-qa-fail-1"):
    return {"kind": "event", "ts": ts, "project": PROJECT, "task_id": "dev-20260101-000000", "role": "dev",
            "event": "qa_fail", "points": -6, "key": key, "why": "criterion 2 not met"}


def _rating(ts, tool_use_id):
    return {"kind": "rating", "ts": ts, "project": PROJECT, "task_id": "dev-20260101-000000", "rating": 4,
            "roles": ["dev"], "tool_use_id": tool_use_id}


def _jsonl(rows) -> str:
    return "".join(json.dumps(r) + "\n" for r in rows)


@pytest.fixture
def step(tmp_path, monkeypatch):
    """The configured harness is this tree; home, state and the earlier version's places are throwaway."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(ROOT))
    for var in ("CLAUDE_STATE_DIR", "CLAUDE_RESTART_STATE_DIR", "XDG_STATE_HOME"):
        monkeypatch.delenv(var, raising=False)
    import carry_state
    import score_log
    old_tmp, records = tmp_path / "old-tmp", tmp_path / "old-records"
    old_tmp.mkdir()
    (records / "logs").mkdir(parents=True)
    log = score_log.log_path()
    assert str(log).startswith(str(tmp_path))
    log.parent.mkdir(parents=True, exist_ok=True)

    def run(old_rows):
        (records / "logs" / "lifecycle.jsonl").write_text(_jsonl(old_rows))
        return carry_state.carry_over(old_state_root=str(old_tmp), old_records=str(records))
    return run, log, score_log


def test_an_event_recorded_again_after_the_takeover_is_scored_once(step):
    run, log, score_log = step
    log.write_text(_jsonl([_event("2026-01-02T00:00:00Z")]))  # the new version recorded it again, later
    out = run([_event("2026-01-01T00:00:00Z")])
    rows = [r for _, r in score_log.read_lines(str(log))]
    assert score_log.score(rows, "dev", PROJECT, AS_OF) == 44  # 50 - 6, not 38
    assert [r["ts"] for r in rows] == ["2026-01-02T00:00:00Z"]  # what the log holds wins, as in append_all
    assert out["repeats_dropped"] == 1


def test_a_rating_of_the_same_task_is_kept_once(step):
    run, log, score_log = step
    log.write_text(_jsonl([_rating("2026-01-02T00:00:00Z", "toolu_new")]))
    out = run([_rating("2026-01-01T00:00:00Z", "toolu_old"), {"row": "unkeyed"}])
    rows = [r for _, r in score_log.read_lines(str(log))]
    assert [r.get("tool_use_id") for r in rows] == [None, "toolu_new"]
    assert out["repeats_dropped"] == 1


def test_a_second_run_changes_nothing(step):
    run, log, score_log = step
    log.write_text(_jsonl([_event("2026-01-02T00:00:00Z"), _event("2026-01-02T00:00:01Z", key="k-other")]))
    run([_event("2026-01-01T00:00:00Z")])
    after = log.read_text()
    out = run([_event("2026-01-03T00:00:00Z")])  # the earlier version recorded the same event once more
    assert log.read_text() == after
    assert out["repeats_dropped"] == 1
    out = run([])
    assert log.read_text() == after and out["repeats_dropped"] == 0
