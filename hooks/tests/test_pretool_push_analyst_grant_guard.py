"""hooks/pretool-push-analyst-grant-guard.py, retired to an exit-0 stub (P1b): settings.json still
registers it at PreToolUse Bash; scripts/execute-push.py validates and spends the grant."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "pretool-push-analyst-grant-guard.py"


def test_the_registered_stub_decides_nothing(tmp_path):
    """One `# STUB:` line; a Bash call that runs execute-push.py, and malformed stdin: exit 0, no output."""
    assert sum(line.startswith("# STUB:") for line in HOOK.read_text().splitlines()) == 1
    settings = json.loads((ROOT / "settings.json").read_text())
    assert any("pretool-push-analyst-grant-guard.py" in h["command"]
               for g in settings["hooks"]["PreToolUse"] for h in g["hooks"])
    payload = {"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(tmp_path),
               "tool_input": {"command": "python3 ~/.claude/scripts/execute-push.py --grant /tmp/grant.json"}}
    for raw in (json.dumps(payload), "{not json"):
        done = subprocess.run([sys.executable, str(HOOK)], input=raw, capture_output=True, text=True,
                              env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
        assert (done.returncode, done.stdout, done.stderr) == (0, "", "")
