"""hooks/notification-idle-overnight.py, retired to an exit-0 stub (P1b): settings.json still registers it."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "notification-idle-overnight.py"


def test_the_registered_stub_writes_nothing_and_exits_0(tmp_path):
    """One `# STUB:` line; an idle_prompt Notification of a live overnight session, and malformed stdin:
    exit 0, no output, no logs/overnight-idle.jsonl (nothing under the harness home or HOME is written)."""
    assert sum(line.startswith("# STUB:") for line in HOOK.read_text().splitlines()) == 1
    settings = json.loads((ROOT / "settings.json").read_text())
    assert any("notification-idle-overnight.py" in h["command"]
               for g in settings["hooks"]["Notification"] for h in g["hooks"])
    home = tmp_path / "home"
    (home / ".claude" / "logs").mkdir(parents=True)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "CLAUDE_HOME": str(home / ".claude"),
           "CLAUDE_STATE_DIR": str(tmp_path / "state")}
    for raw in (json.dumps({"session_id": "s1", "hook_event_name": "Notification",
                            "notification_type": "idle_prompt", "message": "waiting"}), "{not json"):
        done = subprocess.run([sys.executable, str(HOOK)], input=raw, capture_output=True, text=True, env=env)
        assert (done.returncode, done.stdout, done.stderr) == (0, "", "")
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")) == [
        "home", "home/.claude", "home/.claude/logs"]
