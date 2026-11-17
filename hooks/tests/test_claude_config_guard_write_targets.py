"""hooks/pretool-claude-config-guard.py judges a Bash command by what it really writes (OB-L31, F07).

On the base the guard refused any command where a cp, mv or tee word came anywhere before a
`.claude/hooks/` or `.claude/commands/` path, so reading a hook (`cp ~/.claude/hooks/x /tmp/`,
`grep -rn 'mv ' ~/.claude/hooks/`) was refused, while `rm`, `sed -i`, `install`, `ln`, `dd of=`,
`rsync` into those folders and writes after `cd .claude/hooks` went through. The guard now asks the
shared shell parser (hooks/lib/shell_parse.py) which paths the command writes, removes or moves away,
resolves a relative one against every `cd` target in the command, and refuses when one of them lies
in a protected folder. Where the parser cannot settle it (a parse failure, a command it cannot read
statically that names a protected folder) the base reading still decides, so the guard stays
fail-closed.

Each case runs the real hook as a subprocess, with a scratch HOME and CLAUDE_HOME.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "pretool-claude-config-guard.py"
BLOCK = "BLOCKED: claude config guard: agent Bash write to .claude/"
ACTORS = {"main": None, "subagent": ("a0123456789abcdef", "dev")}


@pytest.fixture(scope="module")
def scratch(tmp_path_factory):
    root = tmp_path_factory.mktemp("config-guard-targets")
    home, project = root / "home", root / "proj"
    (home / ".claude" / "commands").mkdir(parents=True)
    (home / ".claude" / "hooks").mkdir()
    (project / ".claude" / "commands").mkdir(parents=True)
    (project / ".claude" / "hooks").mkdir()
    (project / "docs").mkdir()
    return home, project


def _run(scratch, command: str, actor=None):
    home, project = scratch
    payload = {"session_id": "sess-write-targets", "transcript_path": str(project / "t.jsonl"),
               "cwd": str(project), "hook_event_name": "PreToolUse", "tool_name": "Bash",
               "tool_input": {"command": command}}
    if actor:
        payload.update(agent_id=actor[0], agent_type=actor[1])
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update(HOME=str(home), CLAUDE_HOME=str(home / ".claude"), CLAUDE_PROJECT_DIR=str(project),
               PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                          text=True, cwd=str(project), env=env, timeout=30)


# Reads of the protected folders: nothing under them is written, removed or moved away.
MUST_PASS = [
    "cp ~/.claude/hooks/pretool-launch.py /tmp/launch-copy.py",
    "cp -r ~/.claude/commands/ /tmp/commands-snapshot",
    "grep -rn 'mv ' ~/.claude/hooks/ | head -20",
    "rg -n 'tee ' ~/.claude/hooks/",
    "cp README.md docs/README-copy.md && ls ~/.claude/hooks/",
    "cp .claude/commands/hello.md docs/hello-command.md",
    "cp .claude/hooks/x.py /tmp/b.py",
    # variants of the same reads
    'cp "$HOME/.claude/hooks/pretool-launch.py" /tmp/launch-copy.py',
    'cp "${CLAUDE_HOME:-$HOME/.claude}/commands/dev.md" /tmp/dev.md',
    "cp -t /tmp/out ~/.claude/hooks/a.py",
    "cp --target-directory=/tmp/out .claude/commands/x.md",
    "env LC_ALL=C cp ~/.claude/hooks/a.py /tmp/a.py",
    "timeout 5 cp ~/.claude/hooks/a.py /tmp/a.py",
    "bash -c 'cp ~/.claude/hooks/a.py /tmp/a.py'",
    "cat ~/.claude/hooks/a.py | tee /tmp/a.py",
    "grep -n 'echo x > ' ~/.claude/hooks/*.py > /tmp/hits.txt",
    "diff ~/.claude/hooks/a.py .claude/hooks/a.py > /tmp/d.txt 2>&1",
    "cd ~/.claude/hooks && grep -rn 'cp ' . > /tmp/hits.txt",
    "cd ~/.claude/hooks && cp a.py /tmp/a.py",
    "rsync -a ~/.claude/commands/ /tmp/commands-backup/",
    "ln -s ~/.claude/hooks/a.py /tmp/a-link.py",
    "mv /tmp/a /tmp/b && ls .claude/commands/",
    "# cp x .claude/hooks/y\nls",
    "\"$PY\" .claude/hooks/a.py --check",
]

# Writes into a protected folder: every one of them refused.
MUST_REFUSE = [
    "cp x ~/.claude/hooks/y.py",
    "cp -t .claude/hooks/ x",
    "cp --target-directory=.claude/commands x",
    "echo x > .claude/hooks/a.sh",
    "tee .claude/commands/x.md",
    "sed -i s/a/b/ .claude/hooks/x.py",
    "mv .claude/hooks/a /tmp/",
    "rm .claude/commands/x.md",
    "cd .claude/hooks && cat > x.py <<'EOF'\nprint(1)\nEOF",
    # attached redirects, appends and other write verbs
    "x>.claude/hooks/a",
    "echo x>>.claude/commands/a.md",
    "install -m 755 x .claude/hooks/a.py",
    "ln -sf /tmp/evil.py .claude/hooks/a.py",
    "dd if=/tmp/x of=.claude/hooks/a.py",
    "rsync -a /tmp/x/ .claude/commands/",
    "rm -rf ~/.claude/hooks/",
    "unlink .claude/hooks/a.py",
    "truncate -s 0 .claude/hooks/a.py",
    "chmod -x ~/.claude/hooks/a.py",
    "sed -i.bak -e s/a/b/ ~/.claude/commands/dev.md",
    "cp x .claude/hooks",
    "mv -t .claude/commands x.md",
    "cp --target-directory .claude/hooks x",
    # wrappers
    "env FOO=1 cp x .claude/hooks/a.py",
    "command cp x .claude/hooks/a.py",
    "exec cp x .claude/hooks/a.py",
    "nice -n 5 cp x .claude/hooks/a.py",
    "timeout 3 tee .claude/commands/x.md < x",
    "setsid rm .claude/hooks/a.py",
    "nohup sed -i s/a/b/ .claude/hooks/x.py",
    # nested shells and substitutions
    "bash -c 'echo x > .claude/hooks/a.sh'",
    "sh -c \"rm .claude/commands/x.md\"",
    "eval 'cp x .claude/hooks/a.py'",
    "echo $(cp x .claude/hooks/a.py)",
    "bash <<'EOF'\nrm .claude/hooks/a.py\nEOF",
    "find /tmp -name '*.py' -exec cp {} .claude/hooks/ \\;",
    "echo a.py | xargs cp -t .claude/hooks/",
    # cd chains: relative writes resolve against every cd target
    "cd .claude/hooks && cp /tmp/x.py y.py",
    "cd ~/.claude && rm hooks/a.py",
    "cd .claude && cd commands && echo x > a.md",
    "cd \"$CLAUDE_HOME\" && sed -i s/a/b/ commands/dev.md",
    "pushd .claude/hooks && echo x > a.py",
    "cd .claude/hooks; mv a.py b.py",
    # quoting, home spellings, globs and dynamic targets naming the folders
    "cp x '.claude/hooks/a.py'",
    "cp x .claude/\"hooks\"/a.py",
    "rm \"$CLAUDE_HOME/hooks/a.py\"",
    "rm ${CLAUDE_HOME:-$HOME/.claude}/commands/x.md",
    "cp x ~/.claude/hooks/*.py",
    "D=.claude/hooks; cp x $D/a.py",
    "cp x $(echo .claude/hooks)/a.py",
    # the folders reached through a command the parser cannot read statically: the base reading
    "watch 'cp x .claude/hooks/a.py'",
    "cp x .claude/hooks/a.py 'unterminated",
]


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("command", MUST_PASS)
def test_a_read_of_a_protected_folder_goes_through(scratch, command, actor):
    proc = _run(scratch, command, ACTORS[actor])
    assert proc.returncode == 0, (command, proc.stderr)


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("command", MUST_REFUSE)
def test_a_write_into_a_protected_folder_is_refused(scratch, command, actor):
    proc = _run(scratch, command, ACTORS[actor])
    assert proc.returncode == 2, (command, proc.returncode, proc.stderr)
    assert BLOCK in proc.stderr, proc.stderr


def test_the_refusal_names_the_folder_written(scratch):
    assert "Bash write to .claude/commands/" in _run(scratch, "rm .claude/commands/x.md").stderr
    assert "Bash write to .claude/hooks/" in _run(scratch, "sed -i s/a/b/ .claude/hooks/x.py").stderr


def test_the_sentinel_still_lets_a_write_through(scratch):
    sentinel = scratch[1] / ".claude" / ".hook-refactor-allow"
    sentinel.write_text("")
    try:
        assert _run(scratch, "rm .claude/commands/x.md").returncode == 0
        assert _run(scratch, "cd .claude/hooks && echo x > a.py").returncode == 0
    finally:
        sentinel.unlink()
