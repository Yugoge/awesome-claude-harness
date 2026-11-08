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
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
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


def _locate(project_dir: Path, session_id: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    return timelock.overnight.locate(session_id, {"cwd": str(project_dir)})[1]


def test_locate_matches_exact_session_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_state(tmp_path, "session-a", end_time="2099-01-01T00:00:00")
    state = _locate(tmp_path, "session-a", monkeypatch)
    assert state is not None
    assert state["session_id"] == "session-a"


def test_locate_never_falls_back_to_a_different_sessions_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pre-fix behavior globbed ALL overnight-state-*.json files and
    returned the first one found when no exact match existed. The time-lock
    reads only the stopping session's own record (lib/overnight's locator): a
    caller asking for a session_id that has no state file of its own must get
    None, even though a DIFFERENT session's state file exists on disk."""
    _write_state(tmp_path, "session-other", end_time="2099-01-01T00:00:00")
    assert _locate(tmp_path, "session-mine", monkeypatch) is None


def test_locate_rejects_content_session_id_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defense in depth: even if the FILENAME matches, a state file whose
    OWN session_id field disagrees is rejected, not trusted."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True)
    path = claude_dir / "overnight-state-session-a.json"
    path.write_text(json.dumps({"session_id": "session-b", "end_time": "2099-01-01T00:00:00"}))
    assert _locate(tmp_path, "session-a", monkeypatch) is None


def test_locate_missing_session_id_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _locate(tmp_path, "", monkeypatch) is None


def _typed_stop_transcript(path: Path) -> Path:
    """A main transcript whose human typed /dev-overnight, then /stop."""
    records = [
        {"type": "user", "isSidechain": False, "origin": {"kind": "human"},
         "message": {"role": "user", "content": (
             f"<command-message>{name}</command-message>\n<command-name>/{name}</command-name>\n"
             f"<command-args>{args}</command-args>")}}
        for name, args in (("dev-overnight", "8h"), ("stop", ""))
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def test_status_fields_release_nothing_and_a_typed_stop_publishes_cancelled_by_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """status/terminal_status are fields an agent can write: inside the window
    they free nothing (exit 2). The human-typed /stop record releases the lock
    with no closeout check and calls session_resources.publish_overnight_receipt
    with the cancelled_by_user status, then allows stop (exit 0)."""
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
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    _write_state(tmp_path, "session-cancel", end_time=future, status="cancelled",
                 terminal_status="cancelled_by_user", current_phase="completed")

    def stop(payload: dict) -> int:
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
        with pytest.raises(SystemExit) as exc:
            timelock.main()
        return exc.value.code

    assert stop({"session_id": "session-cancel"}) == 2
    assert calls == []
    transcript = _typed_stop_transcript(tmp_path / "transcript.jsonl")
    assert stop({"session_id": "session-cancel", "transcript_path": str(transcript)}) == 0
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


# ---------------------------------------------------------------------------
# Ticket 20261001-161041-r10 (AC1/AC2): the core block/allow exit-code
# decision itself -- previously exercised nowhere in this repo. Run via
# direct subprocess invocation of the real hook script (not the in-process
# module import above), matching this spec's dev constraint that the
# closeout-artifact-gate interaction (AC2) must be reproduced live rather
# than re-derived from source reading alone.
# ---------------------------------------------------------------------------

_STOP_HOOK_PATH = HOOKS / "stop-overnight-timelock.py"


def _run_stop_hook(project_dir: Path, session_id: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    return subprocess.run(
        [sys.executable, str(_STOP_HOOK_PATH)],
        input=json.dumps({"session_id": session_id}),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


def _closeout_on_disk(root: Path, session_id: str) -> None:
    """Step 20's PM retrospective and Step 21's summary, under the working root."""
    retro = root / "docs" / "dev" / "overnight" / session_id / "retro-report-cycle1.json"
    retro.parent.mkdir(parents=True, exist_ok=True)
    retro.write_text("{}")
    (root / "docs" / "dev" / "overnight-summary-2026-11-01.md").write_text("done")


def test_stop_hook_blocks_while_end_time_is_future(tmp_path: Path) -> None:
    """AC1: a live session whose end_time has not yet arrived blocks Stop
    (exit 2, stderr contains 'TIME-LOCK ACTIVE')."""
    session_id = "ac1-future"
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    _write_state(tmp_path, session_id, end_time=future)
    result = _run_stop_hook(tmp_path, session_id)
    assert result.returncode == 2
    assert "TIME-LOCK ACTIVE" in result.stderr


def test_stop_hook_does_not_revalidate_the_cycle_contract(tmp_path: Path) -> None:
    """P1b row 13: the Stop no longer re-validates the subagents' reports a
    cycle contract lists (G2 at each producer's stop and the collection check,
    posttool-overnight-file-check.py, decide on them). Inside the window a
    contract entry whose dispatch never ran blocks only by the time-lock's own
    rule, with its own message; after end_time, with the closeout on disk, it
    allows stop (P2: the pending-required-calls block stays dropped)."""
    session_id = "row13-contract"
    contract = (tmp_path / "docs" / "dev" / "overnight" / session_id / "cycle-1"
                / "cycle-contract.json")
    contract.parent.mkdir(parents=True)
    contract.write_text(json.dumps({"cycle_id": 1, "required_calls": [
        {"step": "12", "role": "dev", "mode": None, "pipeline_id": "pipeline-0",
         "expected_output_path": "docs/dev/dev-report-missing.json",
         "schema_name": "dev-report.v2"}]}))
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    start = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    _write_state(tmp_path, session_id, end_time=future, start_time=start, worktree_path=str(tmp_path))
    inside = _run_stop_hook(tmp_path, session_id)
    assert inside.returncode == 2
    assert "TIME-LOCK ACTIVE" in inside.stderr
    assert "required_calls" not in inside.stderr

    _closeout_on_disk(tmp_path, session_id)
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    _write_state(tmp_path, session_id, end_time=past, start_time=start, worktree_path=str(tmp_path))
    after = _run_stop_hook(tmp_path, session_id)
    assert after.returncode == 0, after.stderr


def _write_closeout(root: Path, session_id: str) -> None:
    """What Step 21 leaves on disk under the working root: the overnight summary."""
    summary = root / "docs" / "dev" / "overnight-summary-2026-01-01.md"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text("# Overnight Development Summary\n")


def test_stop_hook_allows_once_end_time_passed_and_closeout_complete(
    tmp_path: Path,
) -> None:
    """AC2: once end_time has passed, the closeout is decided on disk
    (lib/overnight closeout_gaps), never on self-declared state fields: with
    no retro report or summary the hook blocks naming both gaps on stderr,
    whatever final_summary_path, pm_retro_reports or
    artifact_checkpoint_status say; with Step 20's retro report and Step 21's
    summary written since start_time it allows stop (exit 0, no
    'TIME-LOCK ACTIVE')."""
    session_id = "ac2-past-complete"
    summary = tmp_path / "summary.md"
    summary.write_text("done")
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    start = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
    _write_state(
        tmp_path,
        session_id,
        end_time=past,
        start_time=start,
        worktree_path=str(tmp_path),
        final_summary_path=str(summary),
        pm_retro_reports=["retro-1"],
        artifact_checkpoint_status="intentionally_uncommitted",
    )
    blocked = _run_stop_hook(tmp_path, session_id)
    assert blocked.returncode == 2
    assert "CLOSEOUT GATE" in blocked.stderr
    assert "retro-report-cycle*.json" in blocked.stderr and "overnight-summary-*.md" in blocked.stderr

    _closeout_on_disk(tmp_path, session_id)
    result = _run_stop_hook(tmp_path, session_id)
    assert result.returncode == 0, result.stderr
    assert "TIME-LOCK ACTIVE" not in result.stderr


def test_stop_hook_after_end_time_names_the_missing_summary(tmp_path: Path) -> None:
    """After end_time the Stop is refused until Step 21's summary is on disk; the
    refusal names it by path. Self-declared state fields (final_summary_path,
    pm_retro_reports, artifact_checkpoint_status) release nothing, a summary older
    than start_time is not this session's, and an empty one is no summary (P1c).
    The summary alone still leaves Step 20's PM retrospective named (P2 R7)."""
    session_id = "closeout-gaps"
    past = (datetime.now() - timedelta(hours=2)).isoformat()
    _write_state(tmp_path, session_id, start_time=past, end_time=past, worktree_path=str(tmp_path),
                 final_summary_path=str(tmp_path), pm_retro_reports=["retro-1"],
                 artifact_checkpoint_status="checkpointed")
    old = tmp_path / "docs" / "dev" / "overnight-summary-2020-01-01.md"
    old.parent.mkdir(parents=True)
    old.write_text("an earlier session's")
    os.utime(old, (0, 0))
    first = _run_stop_hook(tmp_path, session_id)
    assert first.returncode == 2
    assert "CLOSEOUT GATE" in first.stderr and "no summary written since start_time" in first.stderr
    assert "overnight-summary-*.md" in first.stderr
    (tmp_path / "docs" / "dev" / "overnight-summary-2026-01-02.md").write_text("")
    assert _run_stop_hook(tmp_path, session_id).returncode == 2

    _write_closeout(tmp_path, session_id)
    summary_only = _run_stop_hook(tmp_path, session_id)
    assert summary_only.returncode == 2
    assert "retro-report-cycle*.json" in summary_only.stderr
    assert "overnight-summary-*.md" not in summary_only.stderr
    _closeout_on_disk(tmp_path, session_id)
    assert _run_stop_hook(tmp_path, session_id).returncode == 0
