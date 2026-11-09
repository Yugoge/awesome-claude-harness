"""hooks/stop-overnight-timelock.py, retired to an exit-0 stub (P5 R11).

Its time-lock and wake check are the Stop gate's step 4 (hooks/stop-command-gate.py,
tested in test_stop_command_gate.py and test_overnight_wake.py), its exact-session
state selection is the overnight locator's (test_stop_command_gate.py), and its
terminal receipt is the coordinator's call on the gate's terminal line
(test_laneb_stop_coordinator.py). Its state-field release (`status:
cancelled_by_user`) went with its code: only the human-typed /stop releases.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[2] / "hooks" / "stop-overnight-timelock.py"


def test_the_stub_decides_nothing_whatever_the_state(tmp_path: Path) -> None:
    """A live window, a cancelled record or none: exit 0, no output, no file written."""
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "overnight-state-s.json").write_text(json.dumps(
        {"session_id": "s", "end_time": "2099-01-01T00:00:00", "status": "running"}))
    before = sorted(p.name for p in tmp_path.rglob("*"))
    for payload in ("", json.dumps({"session_id": "s"}), "not json"):
        done = subprocess.run([sys.executable, str(HOOK)], input=payload, capture_output=True, text=True,
                              cwd=str(tmp_path), env={"CLAUDE_PROJECT_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"})
        assert (done.returncode, done.stdout, done.stderr) == (0, "", "")
    assert sorted(p.name for p in tmp_path.rglob("*")) == before
