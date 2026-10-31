#!/usr/bin/env python3
"""Tests for hooks/stop-obligation-gate.py, G4's registered Stop hook, now an
exit-0 stub (P1b row 3, Correction 6, D15).

Its re-validation of every dispatch's declared artifacts at the session's
Stop is gone: each artifact is decided at its producer's own stop (G2) and at
the next dispatch (G3). The file stays registered, reads nothing and decides
nothing, whatever the session holds and whatever CLAUDE_OBLIGATION_TERMINAL
says.

Run: pytest hooks/tests/test_stop_obligation_gate.py -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _fixtures_obligation_terminal as fx  # noqa: E402

HOOK = Path(__file__).resolve().parent.parent / "stop-obligation-gate.py"
REPO_ROOT = HOOK.parent.parent


def _run_gate(transcript_path, project_dir, home, mode=None, session_id="gate-test-sess",
              raw_stdin=None):
    # Pin HOME and the configuration directory (CLAUDE_CONFIG_DIR, else
    # ~/.claude) to the scratch home so the gate never sees the real one.
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir), "HOME": str(home),
           "CLAUDE_CONFIG_DIR": str(home / ".claude")}
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
        input=raw_stdin if raw_stdin is not None else json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _written_files(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


# --------------------------------------------------------------------------
# AC1: registration + validity (Must-Have item 1)
# --------------------------------------------------------------------------

def test_hook_registered_and_valid(tmp_path):
    """AC-L4-01: hook file exists, compiles, and settings.json's hooks.Stop
    array registers it in the existing no-matcher shape; D15: its text holds
    a line starting `# STUB:` saying what replaced it."""
    assert HOOK.is_file()
    assert any(line.startswith("# STUB:") for line in HOOK.read_text().splitlines())
    # py_compile writes its .pyc even under PYTHONDONTWRITEBYTECODE; redirect it
    # out of the checkout's hooks/__pycache__/ (which may be read-only).
    compiled = subprocess.run(
        [sys.executable, "-m", "py_compile", str(HOOK)],
        capture_output=True, text=True,
        env=dict(os.environ, PYTHONPYCACHEPREFIX=str(tmp_path)),
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


def _unresolved_dev_session(tmp_path, project_dir):
    token = "20260930-132644-l4"
    doc = fx.build_obligation_doc(task_id=token, artifact_path="docs/dev/dev-report-MISSING-a.json")
    return fx.make_dev_family_transcript(tmp_path, project_dir, token, obligation_doc=doc)


def _unresolved_close_session(tmp_path, project_dir):
    token = "20260930-132644-l4"
    doc = fx.build_obligation_doc(task_id=token, artifact_path="docs/dev/dev-report-MISSING-c.json")
    return fx.make_dev_family_transcript(tmp_path, project_dir, token, obligation_doc=doc,
                                         first_user_message="/close")


def _corrupt_transcript(tmp_path, project_dir):
    path = tmp_path / "corrupt.jsonl"
    path.write_text("{this is not valid json\n{neither is this\n")
    return path


SESSIONS = {
    "dev_session_missing_declared_report": _unresolved_dev_session,
    "close_session_missing_declared_report": _unresolved_close_session,
    "no_dev_family_dispatch": lambda tmp_path, project_dir: fx.make_non_dev_family_transcript(tmp_path),
    "corrupt_transcript": _corrupt_transcript,
    "missing_transcript": lambda tmp_path, project_dir: tmp_path / "does-not-exist.jsonl",
}


@pytest.mark.parametrize("mode", [None, "advisory", "block", "off"])
@pytest.mark.parametrize("session", sorted(SESSIONS))
def test_stub_decides_nothing(tmp_path, session, mode):
    """Every Stop, armed or not, with or without a dispatch whose declared
    artifact is missing: exit 0, no output, nothing written."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    transcript = SESSIONS[session](tmp_path, project_dir)
    before = _written_files(tmp_path)

    result = _run_gate(transcript, project_dir, home, mode=mode)

    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert _written_files(tmp_path) == before


def test_stub_reads_no_stdin_it_could_fail_on(tmp_path):
    """Malformed or empty stdin: exit 0 as well."""
    for raw in ("", "{not json", "[]"):
        result = _run_gate(tmp_path / "t.jsonl", tmp_path, tmp_path, mode="block", raw_stdin=raw)
        assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
