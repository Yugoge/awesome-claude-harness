"""hooks/pretool-bulk-commit-detector.py, retired to an exit-0 stub: no registration runs it (its rule
of hooks/pretool-launch.py, and of the Monitor rule's Bash list, went), and the file stays for a hook
list loaded or copied before its retirement (D15); hooks/pretool-git-privilege-guard.py refuses or
reviews every agent commit it read."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "pretool-bulk-commit-detector.py"
NAME = HOOK.name
sys.path.insert(0, str(ROOT / "hooks"))
from lib import launch_settings  # noqa: E402  (the launchers' static table reader)


def test_the_unregistered_stub_decides_nothing(tmp_path):
    """One `# STUB:` line; no registration, a launcher's rule included; the commit shape it warned on,
    another Bash call and malformed stdin: exit 0, no output."""
    assert sum(line.startswith("# STUB:") for line in HOOK.read_text().splitlines()) == 1
    settings = launch_settings.expand(json.loads((ROOT / "settings.json").read_text()), str(ROOT))
    assert not [h["command"] for groups in settings["hooks"].values() for g in groups for h in g["hooks"]
                if NAME in h["command"]]
    assert NAME not in (ROOT / "hooks" / "pretool-monitor-command.py").read_text()
    commit = "git " + "commit -m 'chore(claude): sync all uncommitted config, hooks, scripts, docs'"
    for command in (commit, "ls -la"):
        payload = {"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(tmp_path),
                   "tool_input": {"command": command}}
        for raw in (json.dumps(payload), "{not json"):
            done = subprocess.run([sys.executable, str(HOOK)], input=raw, capture_output=True, text=True,
                                  cwd=tmp_path, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                                                     "HOME": str(tmp_path)})
            assert (done.returncode, done.stdout, done.stderr) == (0, "", "")
