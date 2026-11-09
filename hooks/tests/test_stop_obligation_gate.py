#!/usr/bin/env python3
"""Tests for hooks/stop-obligation-gate.py, G4's former Stop hook, an exit-0
stub (P1b row 3, D15) that settings.json no longer registers (P5 R12).

Its re-validation of every dispatch's declared artifacts at the session's
Stop is gone: each artifact is decided at its producer's own stop (G2) and at
the next dispatch (G3), and the command's own completion is the Stop gate's
(hooks/stop-command-gate.py, test_stop_command_gate.py). A session that loaded
an older hook list still runs this file, so it stays: one stub case.

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


def test_the_unregistered_stub_decides_nothing(tmp_path):
    """One `# STUB:` line, no Stop registration, and every Stop (a dev session whose
    declared report is missing, malformed or empty stdin, any CLAUDE_OBLIGATION_TERMINAL):
    exit 0, no output, nothing written."""
    text = HOOK.read_text()
    assert sum(line.startswith("# STUB:") for line in text.splitlines()) == 1
    settings = json.loads((REPO_ROOT / "settings.json").read_text())
    assert not any("stop-obligation-gate.py" in h["command"] for g in settings["hooks"]["Stop"] for h in g["hooks"])
    project, home = tmp_path / "project", tmp_path / "home"
    project.mkdir()
    home.mkdir()
    token = "20260930-132644-l4"
    doc = fx.build_obligation_doc(task_id=token, artifact_path="docs/dev/dev-report-MISSING-a.json")
    transcript = fx.make_dev_family_transcript(tmp_path, project, token, obligation_doc=doc)
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    payload = json.dumps({"transcript_path": str(transcript), "session_id": "s", "cwd": str(project)})
    for raw, mode in ((payload, "block"), (payload, None), ("", "block"), ("{not json", "off")):
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project), "HOME": str(home),
               "CLAUDE_CONFIG_DIR": str(home / ".claude")}
        env.pop("CLAUDE_OBLIGATION_TERMINAL", None)
        env.update({"CLAUDE_OBLIGATION_TERMINAL": mode} if mode else {})
        done = subprocess.run([sys.executable, str(HOOK)], input=raw, capture_output=True, text=True, env=env,
                              timeout=30)
        assert (done.returncode, done.stdout, done.stderr) == (0, "", "")
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before
