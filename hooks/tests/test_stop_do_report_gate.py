"""hooks/stop-do-report-gate.py, retired to an exit-0 stub (P5 R21).

The /do span is the Stop gate's (hooks/stop-command-gate.py, test_stop_command_gate.py's
A4 and R8 cases): the task is the opener's hook-minted id, never the sidecar, and the span
is complete when the do-report validates, do.status is completed (the schema's one value)
and its file lists equal the span's write set. A session that loaded an older hook list
still runs this file: one stub case.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "stop-do-report-gate.py"


def test_the_unregistered_stub_decides_nothing_with_a_missing_report(tmp_path):
    """One `# STUB:` line, no Stop registration; a /do session whose sidecar names a task
    with no do-report, in every DO_REPORT_GATE_MODE, and malformed stdin: exit 0, no output,
    nothing written."""
    assert sum(line.startswith("# STUB:") for line in HOOK.read_text().splitlines()) == 1
    settings = json.loads((ROOT / "settings.json").read_text())
    assert not any("stop-do-report-gate.py" in h["command"] for g in settings["hooks"]["Stop"] for h in g["hooks"])
    state, project = tmp_path / "state", tmp_path / "project"
    state.mkdir()
    (project / "docs" / "dev").mkdir(parents=True)
    (state / "claude-do-task-s1.json").write_text(json.dumps({"task_id": "20261101-091500"}))
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    for raw, mode in ((json.dumps({"session_id": "s1", "cwd": str(project)}), None),
                      (json.dumps({"session_id": "s1"}), "block"), ("{not json", "advisory")):
        env = {**os.environ, "CLAUDE_STATE_DIR": str(state), "CLAUDE_PROJECT_DIR": str(project)}
        env.pop("DO_REPORT_GATE_MODE", None)
        env.update({"DO_REPORT_GATE_MODE": mode} if mode else {})
        done = subprocess.run([sys.executable, str(HOOK)], input=raw, capture_output=True, text=True, env=env)
        assert (done.returncode, done.stdout, done.stderr) == (0, "", "")
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before
