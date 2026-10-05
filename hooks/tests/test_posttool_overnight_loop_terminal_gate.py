#!/usr/bin/env python3
"""Tests for the G4 terminal-gate additions to hooks/posttool-overnight-loop.py
(ticket 20260930-132644-l4).

Covers Must-Have item 8's required scenarios (b), (d), (f), (g), (h) for
this hook (scenarios (a), (c), (e) are the stop-hook half, covered by
test_stop_obligation_gate.py), plus the explicit expiry-precedence test the
ticket's Edge Cases & Risks section calls for.

Run: pytest hooks/tests/test_posttool_overnight_loop_terminal_gate.py -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _fixtures_obligation_terminal as fx  # noqa: E402

HOOK = Path(__file__).resolve().parent.parent / "posttool-overnight-loop.py"


def _run_loop(payload, project_dir, home, mode=None):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir), "HOME": str(home)}
    if mode is None:
        env.pop("CLAUDE_OBLIGATION_TERMINAL", None)
    else:
        env["CLAUDE_OBLIGATION_TERMINAL"] = mode
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _state_path(project_dir, session_id):
    return project_dir / ".claude" / f"overnight-state-{session_id}.json"


def _read_state(project_dir, session_id):
    return json.loads(_state_path(project_dir, session_id).read_text())


def _advisory_log(home):
    return home / ".claude" / "logs" / "obligation-terminal-gate-advisory.jsonl"


# --------------------------------------------------------------------------
# Scenario (b): SAME unresolved-obligation scenario as the stop-hook half --
# in block mode, overnight loop does NOT update_state_cycle; in advisory
# mode (unset, default), the ORIGINAL reset still occurs (AC-L4-04)
# --------------------------------------------------------------------------

def test_unresolved_obligation_block_skips_reset_advisory_resets_and_logs(tmp_path):
    """Scenario (b) / AC-L4-04."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    session_id = "overnight-sess-b"
    token = "20260930-132644-l4"
    doc = fx.build_obligation_doc(task_id=token, artifact_path="docs/dev/dev-report-MISSING-b.json")
    transcript = fx.make_dev_family_transcript(tmp_path, project_dir, token, obligation_doc=doc)
    # Deliberately do NOT create docs/dev/dev-report-MISSING-b.json.

    state_path = _state_path(project_dir, session_id)
    fx.write_overnight_state(state_path, session_id, cycle_count=3, current_issues=[])
    payload = fx.all_completed_todo_payload(session_id, transcript_path=str(transcript))

    advisory_log = _advisory_log(home)
    if advisory_log.exists():
        advisory_log.unlink()

    # block mode: reset is skipped, reason is populated.
    block_result = _run_loop(payload, project_dir, home, mode="block")
    assert block_result.returncode == 0
    blocked_state = _read_state(project_dir, session_id)
    assert blocked_state["cycle_count"] == 3
    assert blocked_state.get("terminal_gate_blocked_reason")
    assert "condition (a)" in blocked_state["terminal_gate_blocked_reason"]

    # advisory (unset, default): ORIGINAL reset still happens, plus a log entry.
    fx.write_overnight_state(state_path, session_id, cycle_count=3, current_issues=[])
    if advisory_log.exists():
        advisory_log.unlink()
    advisory_result = _run_loop(payload, project_dir, home, mode=None)
    assert advisory_result.returncode == 0
    advisory_state = _read_state(project_dir, session_id)
    assert advisory_state["cycle_count"] == 4
    assert advisory_log.is_file()
    lines = [line for line in advisory_log.read_text().splitlines() if line.strip()]
    assert any(json.loads(line).get("event") == "would_block_reset" for line in lines)


# --------------------------------------------------------------------------
# Scenario (d): negative control -- a "blocked" lane (zero unresolved
# obligations, all todos completed) DOES reset normally; "blocked" alone
# never blocks (AC-L4-05)
# --------------------------------------------------------------------------

def test_blocked_lane_status_is_terminal_resets_normally(tmp_path):
    """Scenario (d) / AC-L4-05."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    session_id = "overnight-sess-d"
    current_issues = [
        {"index": 0, "timestamp_suffix": "ts-d-0", "description": "lane zero"},
        {"index": 1, "timestamp_suffix": "ts-d-1", "description": "lane one"},
    ]
    fx.write_dev_report(project_dir, "ts-d-0", status="completed")
    fx.write_dev_report(project_dir, "ts-d-1", status="blocked")

    state_path = _state_path(project_dir, session_id)
    fx.write_overnight_state(state_path, session_id, cycle_count=5, current_issues=current_issues)
    payload = fx.all_completed_todo_payload(session_id, transcript_path="")

    result = _run_loop(payload, project_dir, home, mode="block")
    assert result.returncode == 0
    state = _read_state(project_dir, session_id)
    assert state["cycle_count"] == 6
    assert "terminal_gate_blocked_reason" not in state


# --------------------------------------------------------------------------
# Scenario (h): positive control for condition (b) -- a genuinely
# non-terminal lane status (zero unresolved obligations) DOES block the
# reset, and the reason names the lane and condition (b) (AC-L4-10)
# --------------------------------------------------------------------------

def test_non_terminal_lane_blocks_reset_condition_b(tmp_path):
    """Scenario (h) / AC-L4-10."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    session_id = "overnight-sess-h"
    current_issues = [
        {"index": 0, "timestamp_suffix": "ts-h-0", "description": "lane zero"},
        {"index": 1, "timestamp_suffix": "ts-h-1", "description": "needs review lane"},
    ]
    fx.write_dev_report(project_dir, "ts-h-0", status="completed")
    fx.write_dev_report(project_dir, "ts-h-1", status="needs_review")

    state_path = _state_path(project_dir, session_id)
    fx.write_overnight_state(state_path, session_id, cycle_count=2, current_issues=current_issues)
    payload = fx.all_completed_todo_payload(session_id, transcript_path="")

    result = _run_loop(payload, project_dir, home, mode="block")
    assert result.returncode == 0
    state = _read_state(project_dir, session_id)
    assert state["cycle_count"] == 2  # unchanged
    reason = state.get("terminal_gate_blocked_reason", "")
    assert "condition (b)" in reason
    assert "ts-h-1" in reason or "pipeline[1]" in reason


def test_non_terminal_lane_missing_status_field_blocks_reset_condition_b(tmp_path):
    """AC-L4-10 variant: a lane entry present in current_issues with NO
    per-lane status field recorded at all -- explicitly NOT "completed" and
    NOT "blocked" -- also blocks, under condition (b)."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    session_id = "overnight-sess-h2"
    current_issues = [
        {"index": 0, "timestamp_suffix": "ts-h2-0", "description": "lane with no report at all"},
    ]
    # Deliberately do NOT write any dev-report for ts-h2-0 -- no status field
    # recorded anywhere.

    state_path = _state_path(project_dir, session_id)
    fx.write_overnight_state(state_path, session_id, cycle_count=7, current_issues=current_issues)
    payload = fx.all_completed_todo_payload(session_id, transcript_path="")

    result = _run_loop(payload, project_dir, home, mode="block")
    assert result.returncode == 0
    state = _read_state(project_dir, session_id)
    assert state["cycle_count"] == 7
    reason = state.get("terminal_gate_blocked_reason", "")
    assert "condition (b)" in reason
    assert "ts-h2-0" in reason or "pipeline[0]" in reason


# --------------------------------------------------------------------------
# Scenario (f) (overnight-loop half): off mode skips both new conditions
# entirely -- behavior byte-identical to pre-lane (unresolved obligation AND
# a non-terminal lane both present, yet the reset still proceeds)
# --------------------------------------------------------------------------

def test_off_mode_skips_entirely_overnight_loop(tmp_path):
    """Scenario f (overnight-loop half)."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    session_id = "overnight-sess-f"
    token = "20260930-132644-l4"
    doc = fx.build_obligation_doc(task_id=token, artifact_path="docs/dev/dev-report-MISSING-f.json")
    transcript = fx.make_dev_family_transcript(tmp_path, project_dir, token, obligation_doc=doc)
    current_issues = [{"index": 0, "timestamp_suffix": "ts-f-0", "description": "non-terminal"}]
    # No dev-report written for ts-f-0 -- non-terminal AND an unresolved
    # obligation is present -- "off" must still reset as if neither existed.

    state_path = _state_path(project_dir, session_id)
    fx.write_overnight_state(state_path, session_id, cycle_count=1, current_issues=current_issues)
    payload = fx.all_completed_todo_payload(session_id, transcript_path=str(transcript))

    advisory_log = _advisory_log(home)
    if advisory_log.exists():
        advisory_log.unlink()

    result = _run_loop(payload, project_dir, home, mode="off")
    assert result.returncode == 0
    state = _read_state(project_dir, session_id)
    assert state["cycle_count"] == 2
    assert "terminal_gate_blocked_reason" not in state
    assert not advisory_log.exists()


# --------------------------------------------------------------------------
# Scenario (g) (overnight-loop half): malformed transcript (unresolvable by
# the obligation scan) or any unexpected exception inside the new logic ->
# fail open to the ORIGINAL unconditional reset (AC-L4-07)
# --------------------------------------------------------------------------

def test_overnight_loop_fails_open_on_malformed_transcript(tmp_path):
    """Scenario g (overnight-loop half) / AC-L4-07."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    session_id = "overnight-sess-g"
    corrupt_transcript = tmp_path / "corrupt.jsonl"
    corrupt_transcript.write_text("{not json at all\n")

    state_path = _state_path(project_dir, session_id)
    fx.write_overnight_state(state_path, session_id, cycle_count=9, current_issues=[])
    payload = fx.all_completed_todo_payload(session_id, transcript_path=str(corrupt_transcript))

    result = _run_loop(payload, project_dir, home, mode="block")
    assert result.returncode == 0
    state = _read_state(project_dir, session_id)
    # A malformed transcript still yields unresolved == [] (the scan itself
    # is fail-safe), so with zero obligations and zero lanes this resets
    # normally -- the key assertion is no crash and no spurious block.
    assert state["cycle_count"] == 10


def test_overnight_loop_fails_open_on_malformed_current_issues(tmp_path):
    """AC-L4-07 variant: current_issues holding a non-dict entry must not
    crash condition (b) -- degrades to the ORIGINAL reset behavior being
    preserved (the malformed-entry label still blocks in block mode, but
    main() must not raise past the single outer try/except)."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    session_id = "overnight-sess-g2"
    state_path = _state_path(project_dir, session_id)
    fx.write_overnight_state(state_path, session_id, cycle_count=1, current_issues=["not-a-dict"])
    payload = fx.all_completed_todo_payload(session_id, transcript_path="")

    result = _run_loop(payload, project_dir, home, mode="block")
    assert result.returncode == 0  # never raises past main()


# --------------------------------------------------------------------------
# Overnight expiry precedence: the pre-existing guard
# (_check_end_time -> _mark_session_complete) must keep firing exactly as
# before, regardless of the new conditions' state.
# --------------------------------------------------------------------------

def test_expiry_precedence_overrides_new_conditions(tmp_path):
    """A session past end_time still completes even with an unresolved
    obligation AND a non-terminal lane present (BA Edge Cases & Risks)."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    session_id = "overnight-sess-expiry"
    token = "20260930-132644-l4"
    doc = fx.build_obligation_doc(task_id=token, artifact_path="docs/dev/dev-report-MISSING-exp.json")
    transcript = fx.make_dev_family_transcript(tmp_path, project_dir, token, obligation_doc=doc)
    current_issues = [{"index": 0, "timestamp_suffix": "ts-exp-0", "description": "non-terminal"}]

    state_path = _state_path(project_dir, session_id)
    past_end_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    state = fx.write_overnight_state(state_path, session_id, cycle_count=4, current_issues=current_issues)
    state["end_time"] = past_end_time
    state_path.write_text(json.dumps(state, indent=2))
    payload = fx.all_completed_todo_payload(session_id, transcript_path=str(transcript))

    result = _run_loop(payload, project_dir, home, mode="block")
    assert result.returncode == 0
    final_state = _read_state(project_dir, session_id)
    assert final_state["current_phase"] == "complete"
    assert final_state["cycle_count"] == 4  # _mark_session_complete never touches cycle_count
    assert "terminal_gate_blocked_reason" not in final_state
