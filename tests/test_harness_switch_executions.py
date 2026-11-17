"""hooks/pretool-harness-switch-guard.py: the switch program and a nested Claude Code session
count only where a Bash command RUNS them.

The switch program (scripts/harness-switch, hooks/userprompt-harness-switch.sh, or any file with
the same real path, inode or content: a copy or a link) is run by a command whose command word is
it (after env, command, exec, nice, timeout, setsid, xargs, ...), by an interpreter or shell given
it as its script operand, a process substitution or a command substitution that prints it, or on
its stdin (`<`, a pipe, a here-string), and by `source` / `.`. A command that only names it
(sed -n, shellcheck, bash -n, grep, python3 -m py_compile, git log) runs nothing. A command that
writes it is still refused.

A nested `claude` starts a session wherever it is the command word, unless its first argument is
one of the non-session forms (--version, -v, --help, -h, doctor, mcp, config); with `/harness`
text anywhere in the command, such a session is refused (the text may reach it through a
variable or a file). `which claude` or a grep for `/harness` starts nothing.

Each case runs the hook as Claude Code does (a PreToolUse payload on stdin) from a harness home at
~/.claude in a throwaway HOME (a copy of the tree's hooks/, scripts/harness-switch and
commands/harness.md).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    root = tmp_path_factory.mktemp("executions")
    home = root / "home"
    h = home / ".claude"
    shutil.copytree(ROOT / "hooks", h / "hooks", ignore=shutil.ignore_patterns("tests", "__pycache__"))
    (h / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts" / "harness-switch", h / "scripts" / "harness-switch")
    (h / "commands").mkdir()
    shutil.copy2(ROOT / "commands" / "harness.md", h / "commands" / "harness.md")
    (h / "settings.json").write_text('{"env": {"A": "1"}, "hooks": {}}\n')
    other = root / "other"
    other.mkdir()
    shutil.copy2(h / "scripts" / "harness-switch", other / "sw-copy")       # same content
    os.symlink(h / "scripts" / "harness-switch", other / "sw-link")          # same real path
    os.link(h / "scripts" / "harness-switch", other / "sw-hard")             # same inode
    (other / "notes.txt").write_text("plain text\n")
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDE_CONFIG_DIR", "CLAUDE_PROJECT_DIR", "CLAUDE_HOME", "CLAUDE_TASK_ID",
                        "CLAUDE_SESSION_ID", "CLAUDE_AGENT_ID") and not k.startswith("GIT_")}
    env["HOME"] = str(home)
    return {"home": home, "h": h, "other": other, "env": env,
            "hook": h / "hooks" / "pretool-harness-switch-guard.py"}


def hook(box, command, cwd, actor="main"):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd), "session_id": "S1"}
    if actor == "subagent":
        payload["agent_id"] = "sub-1"
    proc = subprocess.run([sys.executable, str(box["hook"])], input=json.dumps(payload), capture_output=True,
                          text=True, env=box["env"], cwd=str(cwd), timeout=60)
    return proc.returncode, proc.stderr


def fill(box, command):
    return command.replace("{O}", str(box["other"]))


MUST_PASS = [
    # the lane's must-pass examples
    "sed -n '1,60p' ~/.claude/scripts/harness-switch ; shellcheck ~/.claude/scripts/harness-switch ; "
    "bash -n ~/.claude/hooks/userprompt-harness-switch.sh",
    "sed -n '1,60p' ~/.claude/scripts/harness-switch",
    "shellcheck ~/.claude/scripts/harness-switch",
    "bash -n ~/.claude/hooks/userprompt-harness-switch.sh",
    "grep -n '/harness' ~/.claude/commands/harness.md; claude --version",
    "rg -n '/harness off' ~/.claude/commands; which claude",
    # the same reads, spelled otherwise
    "cd ~/.claude && sed -n 1,20p scripts/harness-switch",
    "cd ~/.claude/scripts && shellcheck -x harness-switch",
    "env bash -n ~/.claude/hooks/userprompt-harness-switch.sh",
    "sh -n ~/.claude/hooks/userprompt-harness-switch.sh",
    "python3 -m py_compile ~/.claude/scripts/harness-switch",
    "wc -l ~/.claude/scripts/harness-switch ~/.claude/hooks/userprompt-harness-switch.sh",
    "diff ~/.claude/scripts/harness-switch {O}/sw-copy",
    "cat {O}/sw-copy | head -5",
    "git log --oneline -- scripts/harness-switch hooks/userprompt-harness-switch.sh",
    "awk 'NR<5' ~/.claude/scripts/harness-switch",
    "grep -c '/harness off' ~/.claude/commands/harness.md && claude --help",
    "echo '/harness off is typed by the owner' ; claude doctor",
    "grep -rn '/harness on' ~/.claude/commands | head; claude mcp list",
    "grep -n '/harness' ~/.claude/commands/harness.md; claude -v; claude config list",
    "command -v claude && grep -n '/harness status' ~/.claude/commands/harness.md",
    "type claude; grep '/harness' ~/.claude/commands/harness.md",
    "claude -p 'summarize the repository'",
    "echo 'scripts/harness-switch runs on /harness off'",
    "python3 {O}/notes.txt",
]

MUST_REFUSE = [
    # the lane's must-still-refuse examples
    "~/.claude/scripts/harness-switch hook <<< '{\"prompt\": \"/harness off\"}'",
    "env harness-switch off",
    "python3 <(cat ~/.claude/scripts/harness-switch) hook <<< '{\"prompt\": \"/harness off\"}'",
    "p='/harness off'; setsid claude -p \"$p\"",
    "printf '/harness off' > /tmp/p; setsid claude -p < /tmp/p",
    # the switch program as the command word, behind wrappers
    "command ~/.claude/scripts/harness-switch off",
    "exec ~/.claude/scripts/harness-switch off",
    "nice -n 5 timeout 9 nohup ~/.claude/scripts/harness-switch off",
    "env -i FOO=1 setsid ~/.claude/scripts/harness-switch off",
    "echo off | xargs ~/.claude/scripts/harness-switch",
    "bash -c '~/.claude/scripts/harness-switch off'",
    "cd ~/.claude/scripts && ./harness-switch off",
    "\"$(echo ~/.claude/scripts/harness-switch)\" off",
    "S=~/.claude/scripts/harness-switch; $S off",
    "watch -n 1 '~/.claude/scripts/harness-switch off'",
    # an interpreter's script operand
    "python3 ~/.claude/scripts/harness-switch off",
    "python3 -W ignore -u ~/.claude/scripts/harness-switch off",
    "cd ~/.claude && python3 scripts/harness-switch hook < p.json",
    "bash ~/.claude/hooks/userprompt-harness-switch.sh < p.json",
    "S=~/.claude/scripts/harness-switch; python3 \"$S\" off",
    "python3 \"$(echo ~/.claude/scripts/harness-switch)\" off",
    "python3 <(sed -n p ~/.claude/scripts/harness-switch) off",
    # source / .
    "source ~/.claude/hooks/userprompt-harness-switch.sh",
    ". ~/.claude/hooks/userprompt-harness-switch.sh",
    # stdin-fed
    "python3 < ~/.claude/scripts/harness-switch",
    "python3 - off < ~/.claude/scripts/harness-switch",
    "python3 /dev/stdin hook < ~/.claude/scripts/harness-switch",
    "cat ~/.claude/scripts/harness-switch | python3 - hook",
    "bash < ~/.claude/hooks/userprompt-harness-switch.sh",
    "cat ~/.claude/hooks/userprompt-harness-switch.sh | sh -s",
    "python3 <<< \"$(cat ~/.claude/scripts/harness-switch)\"",
    # copies and links of the switch program
    "python3 {O}/sw-copy off",
    "{O}/sw-link off",
    "python3 {O}/sw-hard off",
    "cat {O}/sw-copy | python3 -",
    # writing the switch program
    "sed -i 's/a/b/' ~/.claude/scripts/harness-switch",
    "perl -pi -e 's/a/b/' ~/.claude/scripts/harness-switch",
    "cp /tmp/x ~/.claude/scripts/harness-switch",
    "echo x > ~/.claude/hooks/userprompt-harness-switch.sh",
    # a nested session given /harness
    "claude -p '/harness off'",
    "bash -c \"claude -p '/harness off'\"",
    "echo '/harness off' | claude -p",
    "claude -p \"$(printf '/harness off')\"",
    "nohup claude -p '/harness on' &",
    "env FOO=1 claude --print '/harness off'",
    "xargs claude -p < /tmp/p; echo /harness off",
    "watch -n 9 \"claude -p '/harness off'\"",
]


@pytest.mark.parametrize("command", MUST_PASS)
@pytest.mark.parametrize("actor", ["main", "subagent"])
def test_naming_the_switch_or_claude_runs_nothing(box, command, actor):
    command = fill(box, command)
    for cwd in (box["other"], box["h"], box["home"]):
        rc, err = hook(box, command, cwd, actor)
        assert rc == 0 and "harness-switch:" not in err, (command, cwd, err)


@pytest.mark.parametrize("command", MUST_REFUSE)
@pytest.mark.parametrize("actor", ["main", "subagent"])
def test_running_the_switch_or_a_session_given_harness_is_refused(box, command, actor):
    command = fill(box, command)
    for cwd in (box["other"], box["h"]):
        rc, err = hook(box, command, cwd, actor)
        assert rc == 2 and "harness-switch:" in err, (command, cwd, err)
