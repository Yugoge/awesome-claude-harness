#!/usr/bin/env python3
"""hooks/pretool-bash-views-guard.py recognises spec-check.py, the cp-state writer, in
the quoted CLAUDE_HOME channel spelling P2 R6 gave every command line, as it
recognised the old `~/.claude/scripts/spec-check.py` spelling.

The line is agents/spec.md's `checkpoints` call, read from the file. A checkpoint
action that names a view behind an arrow (`-> docs/dev/specs/<id>/views/...`) is
what the guard's redirect patterns see; the spec-check whitelist is what lets it
pass. Both spellings get the same decision; a writer outside the channel, an
unquoted channel and a plain redirect into a view stay blocked."""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "pretool-bash-views-guard.py"
CHANNEL = '"${CLAUDE_HOME:-$HOME/.claude}/'
ACTION = '"Write the dev role view -> docs/dev/specs/spec-1/views/dev.md"'


def _decide(command: str) -> subprocess.CompletedProcess:
    payload = {"tool_name": "Bash", "session_id": "views-guard-test", "tool_input": {"command": command}}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True,
                          capture_output=True, cwd=str(ROOT), check=False)


def _checkpoints_line() -> str:
    lines = (ROOT / "agents" / "spec.md").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if 'spec-check.py" checkpoints' in line)
    end = start
    while lines[end].rstrip().endswith("\\"):
        end += 1
    command = "\n".join(lines[start:end + 1])
    command = command.replace('"<first checkpoint action>"', ACTION).replace(
        '"<second checkpoint action>"', '"Run spec-verify on the views"')
    filled = {"<spec-id>": "spec-1", "<agent>": "dev", "<agent-id>": "a1"}
    command = re.sub(r"<[a-z-]+>", lambda m: filled.get(m.group(0), m.group(0)), command)
    assert command.startswith("source " + CHANNEL + "venv/bin/activate\" && python3 " + CHANNEL), command
    assert ACTION in command and "<" not in command.replace("<<", ""), command
    return command


def test_spec_check_channel_and_old_spelling_get_the_same_decision():
    new = _checkpoints_line()
    old = re.sub(r'"\$\{CLAUDE_HOME:-\$HOME/\.claude\}/([^"]*)"', r"~/.claude/\1", new)
    assert old.startswith("source ~/.claude/venv/bin/activate && python3 ~/.claude/scripts/spec-check.py checkpoints")
    new_rc, old_rc = _decide(new), _decide(old)
    assert (new_rc.returncode, old_rc.returncode) == (0, 0), (new_rc.stderr, old_rc.stderr)


def test_writers_outside_the_quoted_channel_stay_blocked():
    new = _checkpoints_line()
    for blocked in (
        new.replace(CHANNEL + "scripts/spec-check.py\"", '"/tmp/elsewhere/scripts/spec-check.py"'),
        new.replace(CHANNEL + "scripts/spec-check.py\"", "${CLAUDE_HOME:-$HOME/.claude}/scripts/spec-check.py"),
        "echo note > docs/dev/specs/spec-1/views/dev.md",
    ):
        result = _decide(blocked)
        assert result.returncode == 2 and "BLOCKED" in result.stderr, blocked
