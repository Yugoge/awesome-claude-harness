#!/usr/bin/env python3
"""Tests for hooks/stop-obligation-gate.py (G4 session-terminal obligation
gate, ticket 20260930-132644-l4).

Covers Must-Have item 8's required scenarios (a), (c), (e), (f), (g) for
this hook (scenarios (b), (d), (h) are the overnight-loop half, covered by
test_posttool_overnight_loop_terminal_gate.py), plus the AC1 registration/
validity check.

Run: pytest hooks/tests/test_stop_obligation_gate.py -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _fixtures_obligation_terminal as fx  # noqa: E402

HOOK = Path(__file__).resolve().parent.parent / "stop-obligation-gate.py"
REPO_ROOT = HOOK.parent.parent


def _run_gate(transcript_path, project_dir, home, mode=None, session_id="gate-test-sess"):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir), "HOME": str(home)}
    if mode is None:
        env.pop("CLAUDE_OBLIGATION_TERMINAL", None)
    else:
        env["CLAUDE_OBLIGATION_TERMINAL"] = mode
    payload = {
        "transcript_path": str(transcript_path),
        "session_id": session_id,
        "cwd": str(project_dir),
    }
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _advisory_log(home):
    return home / ".claude" / "logs" / "obligation-terminal-gate-advisory.jsonl"


# --------------------------------------------------------------------------
# AC1: registration + validity (Must-Have item 1)
# --------------------------------------------------------------------------

def test_hook_registered_and_valid():
    """AC-L4-01: hook file exists, compiles, and settings.json's hooks.Stop
    array registers it in the existing no-matcher shape."""
    assert HOOK.is_file()
    compiled = subprocess.run(
        [sys.executable, "-m", "py_compile", str(HOOK)],
        capture_output=True, text=True,
    )
    assert compiled.returncode == 0, compiled.stderr

    settings = json.loads((REPO_ROOT / "settings.json").read_text())
    stop_entries = settings["hooks"]["Stop"]
    commands = [h["command"] for entry in stop_entries for h in entry["hooks"]]
    assert any("stop-obligation-gate.py" in c for c in commands)
    # Mirrors the no-matcher shape of every existing Stop entry.
    for entry in stop_entries:
        if any("stop-obligation-gate.py" in h["command"] for h in entry["hooks"]):
            assert "matcher" not in entry


# --------------------------------------------------------------------------
# Scenario (a): unresolved obligation -- advisory logs+passes, block rejects
# with a three-element message (AC-L4-02)
# --------------------------------------------------------------------------

def test_unresolved_obligation_advisory_logs_and_block_exits2(tmp_path):
    """Scenario (a) / AC-L4-02."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    token = "20260930-132644-l4"
    doc = fx.build_obligation_doc(
        task_id=token, lane="l4", role="dev",
        artifact_path="docs/dev/dev-report-MISSING-a.json",
    )
    transcript = fx.make_dev_family_transcript(tmp_path, project_dir, token, obligation_doc=doc)
    # Deliberately do NOT create docs/dev/dev-report-MISSING-a.json.

    advisory_log = _advisory_log(home)
    if advisory_log.exists():
        advisory_log.unlink()

    unset_result = _run_gate(transcript, project_dir, home, mode=None)
    assert unset_result.returncode == 0
    assert advisory_log.is_file()
    lines = [line for line in advisory_log.read_text().splitlines() if line.strip()]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record.get("artifact_path") == "docs/dev/dev-report-MISSING-a.json"

    block_result = _run_gate(transcript, project_dir, home, mode="block")
    assert block_result.returncode == 2
    stderr = block_result.stderr
    assert "docs/dev/dev-report-MISSING-a.json" in stderr  # what is unmet
    assert "dev" in stderr and "l4" in stderr  # whose responsibility (role + lane)
    assert "fix:" in stderr  # how to satisfy it


# --------------------------------------------------------------------------
# Scenario (c), UPDATED (ticket 20261001-161041-r21, M1): the unconditional
# /close and /commit exemption is REMOVED. A /close- or /commit-first-message
# session with an unresolved obligation is now classified and re-checked
# exactly like any other dev-family session (AC1); a /close- or
# /commit-first-message session with NO dev-family obligation at all still
# exits 0 in every mode -- LOW-10 fail-open for genuinely non-obligated
# sessions, preserved (AC2).
# --------------------------------------------------------------------------

def test_close_commit_session_with_unresolved_obligation_now_blocks(tmp_path):
    """AC1: removing the exemption makes G4 reachable in block mode for a
    /close or /commit session carrying an unresolved obligation -- advisory
    mode still only logs, block mode exits 2 naming the artifact."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    token = "20260930-132644-l4"
    doc = fx.build_obligation_doc(task_id=token, artifact_path="docs/dev/dev-report-MISSING-c.json")

    for index, first_message in enumerate(("/close", "/commit --bulk")):
        transcript_dir = tmp_path / f"formerly-exempt-{index}"
        transcript_dir.mkdir()
        transcript = fx.make_dev_family_transcript(
            transcript_dir, project_dir, token, obligation_doc=doc,
            first_user_message=first_message,
        )
        advisory_log = _advisory_log(home)
        if advisory_log.exists():
            advisory_log.unlink()

        advisory_result = _run_gate(transcript, project_dir, home, mode=None)
        assert advisory_result.returncode == 0, (first_message, advisory_result.stderr)
        assert advisory_log.is_file(), first_message

        block_result = _run_gate(transcript, project_dir, home, mode="block")
        assert block_result.returncode == 2, (first_message, block_result.stderr)
        assert "docs/dev/dev-report-MISSING-c.json" in block_result.stderr


def test_close_commit_non_obligated_session_still_exits_zero(tmp_path):
    """AC2: a true non-obligated /close or /commit session (no dev-family
    obligation at all) still exits 0 in any mode -- the former exemption is
    gone, but LOW-10's fail-open for non-obligated sessions is unaffected."""
    for index, first_message in enumerate(("/close", "/commit --bulk")):
        case_dir = tmp_path / f"nonobligated-{index}"
        case_dir.mkdir()
        project_dir = case_dir / "project"
        project_dir.mkdir()
        home = case_dir / "home"
        home.mkdir()
        transcript = fx.make_non_dev_family_transcript(
            case_dir, first_user_message=first_message
        )
        for mode in (None, "block", "off"):
            result = _run_gate(transcript, project_dir, home, mode=mode)
            assert result.returncode == 0, (first_message, mode, result.stderr)


# --------------------------------------------------------------------------
# Scenario (e): no dev-registry reference anywhere -> exit 0 immediately,
# any mode, no advisory write (AC-L4-09)
# --------------------------------------------------------------------------

def test_non_dev_family_session_exits_silently(tmp_path):
    """Scenario (e) / AC-L4-09."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    transcript = fx.make_non_dev_family_transcript(tmp_path)
    advisory_log = _advisory_log(home)

    for mode in (None, "block", "off"):
        if advisory_log.exists():
            advisory_log.unlink()
        result = _run_gate(transcript, project_dir, home, mode=mode)
        assert result.returncode == 0
        assert not advisory_log.exists()


# --------------------------------------------------------------------------
# Scenario (f) (stop-hook half): off mode skips the new logic entirely --
# no log write even when an unresolved obligation is present
# --------------------------------------------------------------------------

def test_off_mode_skips_entirely_stop_hook(tmp_path):
    """Scenario f (stop-hook half): CLAUDE_OBLIGATION_TERMINAL=off is a
    no-op, byte-identical to pre-lane behavior, even with an unresolved
    obligation present."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    token = "20260930-132644-l4"
    doc = fx.build_obligation_doc(task_id=token, artifact_path="docs/dev/dev-report-MISSING-f.json")
    transcript = fx.make_dev_family_transcript(tmp_path, project_dir, token, obligation_doc=doc)
    advisory_log = _advisory_log(home)
    if advisory_log.exists():
        advisory_log.unlink()

    result = _run_gate(transcript, project_dir, home, mode="off")
    assert result.returncode == 0
    assert not advisory_log.exists()


# --------------------------------------------------------------------------
# Scenario (g) (stop-hook half): malformed/corrupted transcript or any
# unexpected exception -> fail open (exit 0)
# --------------------------------------------------------------------------

def test_stop_hook_fails_open_on_malformed_transcript(tmp_path):
    """Scenario g (stop-hook half) / AC-L4-06."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    transcript = tmp_path / "corrupt.jsonl"
    transcript.write_text("{this is not valid json\n{neither is this\n")

    for mode in (None, "block"):
        result = _run_gate(transcript, project_dir, home, mode=mode)
        assert result.returncode == 0


def test_stop_hook_fails_open_on_missing_transcript(tmp_path):
    """AC-L4-06 variant: a transcript_path that does not exist on disk at
    all must also fail open, not raise."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    missing_transcript = tmp_path / "does-not-exist.jsonl"

    for mode in (None, "block"):
        result = _run_gate(missing_transcript, project_dir, home, mode=mode)
        assert result.returncode == 0
