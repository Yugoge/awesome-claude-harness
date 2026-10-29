#!/usr/bin/env python3
"""Tests for hooks/posttool-overnight-loop.py's cycle reset, which no longer
re-checks any artifact (P1b row 3: the G4 terminal-lane block is gone).

The reset decides only from the all-completed todo list and the overnight
window. An obligation whose declared artifact is missing, or a lane whose dev
report is absent or not terminal, is decided where it is made: G2 at its
producer's own stop, G3 at the next dispatch. CLAUDE_OBLIGATION_TERMINAL,
whatever its value, changes nothing.

Run: pytest hooks/tests/test_posttool_overnight_loop_terminal_gate.py -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _fixtures_obligation_terminal as fx  # noqa: E402

HOOK = Path(__file__).resolve().parent.parent / "posttool-overnight-loop.py"


def _run_loop(payload, project_dir, home, mode=None):
    # Pin HOME and the configuration directory (CLAUDE_CONFIG_DIR, else
    # ~/.claude) to the scratch home so the hook never sees the real one.
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir), "HOME": str(home),
           "CLAUDE_CONFIG_DIR": str(home / ".claude")}
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


def _retro_reports(project_dir, session_id, done):
    """Cycles 1..done have ended: their PM retrospectives are on disk."""
    base = project_dir / "docs" / "dev" / "overnight" / session_id
    base.mkdir(parents=True, exist_ok=True)
    for n in range(1, done + 1):
        (base / f"retro-report-cycle{n}.json").write_text("{}")


def _written_logs(home):
    """Files under the scratch home's logs/ directory: the hook writes none."""
    logs = home / ".claude" / "logs"
    return sorted(p.name for p in logs.rglob("*")) if logs.is_dir() else []


def _continued(result):
    return "Starting cycle" in result.stdout


def _unresolved_obligation(tmp_path, project_dir):
    token = "20260930-132644-l4"
    doc = fx.build_obligation_doc(task_id=token, artifact_path="docs/dev/dev-report-MISSING-b.json")
    return str(fx.make_dev_family_transcript(tmp_path, project_dir, token, obligation_doc=doc)), []


def _lanes(*statuses):
    def build(tmp_path, project_dir):
        issues = []
        for index, status in enumerate(statuses):
            suffix = f"ts-{index}"
            issues.append({"index": index, "timestamp_suffix": suffix, "description": f"lane {index}"})
            if status is not None:
                fx.write_dev_report(project_dir, suffix, status=status)
        return "", issues
    return build


def _corrupt_transcript(tmp_path, project_dir):
    path = tmp_path / "corrupt.jsonl"
    path.write_text("{not json at all\n")
    return str(path), ["not-a-dict"]


CYCLES = {
    "missing_declared_report": _unresolved_obligation,
    "blocked_lane": _lanes("completed", "blocked"),
    "needs_review_lane": _lanes("completed", "needs_review"),
    "lane_without_report": _lanes(None),
    "malformed_transcript_and_lane": _corrupt_transcript,
}


@pytest.mark.parametrize("mode", [None, "block", "off"])
@pytest.mark.parametrize("cycle", sorted(CYCLES))
def test_reset_continues_whatever_the_artifacts(tmp_path, cycle, mode):
    """Formerly scenarios (b), (d), (f), (g), (h): the continuation prints,
    armed or not, and the state record is not written."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    session_id = f"overnight-sess-{cycle}"
    transcript, issues = CYCLES[cycle](tmp_path, project_dir)
    state_path = _state_path(project_dir, session_id)
    fx.write_overnight_state(state_path, session_id, cycle_count=3, current_issues=issues)
    _retro_reports(project_dir, session_id, 3)
    before = state_path.read_bytes()
    payload = fx.all_completed_todo_payload(session_id, transcript_path=transcript)

    result = _run_loop(payload, project_dir, home, mode=mode)

    assert result.returncode == 0, result.stderr
    assert "Cycle 3 complete (PM retro filed). Starting cycle 4." in result.stdout
    assert "BLOCKED" not in result.stdout
    assert state_path.read_bytes() == before
    assert _written_logs(home) == []


# --------------------------------------------------------------------------
# A closed window (lib.overnight.state_verdicts) ends the session.
# --------------------------------------------------------------------------

def test_closed_window_completes_the_session(tmp_path):
    """A session past end_time completes, with an unresolved obligation AND a
    non-terminal lane present as before."""
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
    before = state_path.read_bytes()
    payload = fx.all_completed_todo_payload(session_id, transcript_path=str(transcript))

    result = _run_loop(payload, project_dir, home, mode="block")
    assert result.returncode == 0
    assert "OVERNIGHT SESSION COMPLETE" in result.stdout
    assert "BLOCKED" not in result.stdout
    assert not _continued(result)
    assert state_path.read_bytes() == before
