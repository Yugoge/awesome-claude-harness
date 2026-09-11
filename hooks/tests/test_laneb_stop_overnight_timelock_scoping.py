"""LANE-B (20260808-035658) regression coverage for hooks/stop-overnight-timelock.py.

Blast-radius-map.json (dev-20260910-111227/blast-radius-map-20260808-035658-laneb)
flags this file as a "critical", no_automated_test coverage_gap with
behavioral_test_only=True. That gap's canonical exemption text
("file not modified this cycle") does not apply here -- LANE-B *did* modify
this file (session_resources import + terminal-receipt publish on
cancelled/deadline exit + tightened load_state()) -- so this file supplies
direct, targeted regression coverage for exactly the two behaviors LANE-B
changed, rather than relying on canary-verify.sh's broader SessionStart smoke
check alone.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"

_spec = importlib.util.spec_from_file_location(
    "laneb_stop_overnight_timelock", HOOKS / "stop-overnight-timelock.py"
)
assert _spec and _spec.loader
timelock = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = timelock
_spec.loader.exec_module(timelock)


def _write_state(project_dir: Path, session_id: str, **extra) -> Path:
    claude_dir = project_dir / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    path = claude_dir / f"overnight-state-{session_id}.json"
    payload = {"session_id": session_id, **extra}
    path.write_text(json.dumps(payload))
    return path


def test_load_state_matches_exact_session_id(tmp_path: Path) -> None:
    _write_state(tmp_path, "session-a", end_time="2099-01-01T00:00:00")
    state = timelock.load_state(tmp_path, "session-a")
    assert state is not None
    assert state["session_id"] == "session-a"


def test_load_state_no_longer_falls_back_to_a_different_sessions_file(
    tmp_path: Path,
) -> None:
    """The pre-fix behavior globbed ALL overnight-state-*.json files and
    returned the first one found when no exact match existed. LANE-B tightened
    this to an exact-session lookup only (session/actor confinement, matching
    the scratch-namespace rationale). A caller asking for a session_id that
    has no state file of its own must get None, even though a DIFFERENT
    session's state file exists on disk."""
    _write_state(tmp_path, "session-other", end_time="2099-01-01T00:00:00")
    state = timelock.load_state(tmp_path, "session-mine")
    assert state is None


def test_load_state_rejects_content_session_id_mismatch(tmp_path: Path) -> None:
    """Defense in depth: even if the FILENAME matches, a state file whose
    OWN session_id field disagrees is rejected, not trusted."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True)
    path = claude_dir / "overnight-state-session-a.json"
    path.write_text(json.dumps({"session_id": "session-b", "end_time": "2099-01-01T00:00:00"}))
    assert timelock.load_state(tmp_path, "session-a") is None


def test_load_state_missing_session_id_returns_none(tmp_path: Path) -> None:
    assert timelock.load_state(tmp_path, "") is None


def test_publish_terminal_receipt_invoked_on_cancelled_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_enforce_timelock's new cancelled-by-user branch must call
    session_resources.publish_overnight_receipt with the right terminal
    status and then allow stop (exit 0), not fall through to the normal
    timelock/closeout gates."""
    calls = []

    class _StubSessionResources:
        @staticmethod
        def publish_overnight_receipt(project_dir, *, claude_session_id, state, terminal_status):
            calls.append(
                {
                    "project_dir": project_dir,
                    "claude_session_id": claude_session_id,
                    "terminal_status": terminal_status,
                }
            )
            return {"status": "pass"}

    monkeypatch.setattr(timelock, "session_resources", _StubSessionResources)
    monkeypatch.setattr(timelock, "_invoke_closeout", lambda *_a, **_k: False)

    state = {"session_id": "session-cancel", "status": "cancelled_by_user"}
    with pytest.raises(SystemExit) as exc:
        timelock._enforce_timelock("session-cancel", state, tmp_path)

    assert exc.value.code == 0
    assert calls == [
        {
            "project_dir": tmp_path,
            "claude_session_id": "session-cancel",
            "terminal_status": "cancelled_by_user",
        }
    ]


def test_publish_terminal_receipt_degrades_gracefully_when_session_resources_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the session_resources import failed at module load (module-level
    try/except sets it to None), the receipt publish must no-op rather than
    raising -- this writer must never finalize/signal resources itself and
    must never turn an absent library into a hard error."""
    monkeypatch.setattr(timelock, "session_resources", None)
    published = timelock._publish_terminal_receipt(
        tmp_path, "session-x", {"session_id": "session-x"}, "completed_by_deadline"
    )
    assert published is False
