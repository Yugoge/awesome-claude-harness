"""hooks/pretool-harness-switch-guard.py: the switch program and a nested Claude Code session
count only where a Bash command RUNS them.

The switch program (scripts/harness-switch, hooks/userprompt-harness-switch.sh, or any file with
the same real path, inode or content: a copy or a link) is run by a command whose command word is
it (after env, command, exec, nice, timeout, setsid, xargs, ...), by an interpreter or shell given
it as its script operand, a process substitution or a command substitution that prints it, or on
its stdin (`<`, a pipe, a here-string), and by `source` / `.`. A command that only names it
(sed -n, shellcheck, bash -n, grep, git log) runs nothing. A command that
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


# Round 2: a command the parent rule refused (a word naming the switch, outside a reader) passes only
# when the whole command provably only reads the switch program; else the parent's refusal stands.
# Each of these ran the switch (or may have) and passed on the round-1 head.
RUNS_THE_SWITCH = [
    # a copy, link or write of it, then run (a fresh path too)
    "cp ~/.claude/scripts/harness-switch /tmp/x; python3 /tmp/x hook <<< '{\"prompt\": \"/harness off\"}'",
    "cp ~/.claude/scripts/harness-switch /tmp/x && python3 /tmp/x hook <<< '{\"prompt\": \"/harness off\"}'",
    "ln -s ~/.claude/scripts/harness-switch /tmp/x && /tmp/x off",
    "ln ~/.claude/scripts/harness-switch /tmp/x && /tmp/x off",
    "install ~/.claude/scripts/harness-switch /tmp/x && /tmp/x off",
    "cp ~/.claude/scripts/harness-switch /tmp/x; /tmp/x off",
    "dd if=~/.claude/scripts/harness-switch of=/tmp/x; python3 /tmp/x off",
    "tee /tmp/x < ~/.claude/scripts/harness-switch; python3 /tmp/x off",
    "rsync ~/.claude/scripts/harness-switch /tmp/x; python3 /tmp/x off",
    "cp ~/.claude/scripts/harness-switch /tmp/l34v-new; python3 /tmp/l34v-new off",
    "cp ~/.claude/scripts/harness-switch {O}/fresh && python3 {O}/fresh off",
    # interpreter code on the command line
    "python3 -c 'import os; os.system(\"~/.claude/scripts/harness-switch off\")'",
    "perl -e 'system(\"~/.claude/scripts/harness-switch off\")'",
    "node -e 'require(\"child_process\").execSync(\"~/.claude/scripts/harness-switch off\")'",
    # positional arguments to a shell's -c
    "sh -c 'exec \"$0\" off' ~/.claude/scripts/harness-switch",
    "bash -c '\"$1\" off' x ~/.claude/scripts/harness-switch",
    "bash -c 'S=$1; python3 $S off' _ ~/.claude/scripts/harness-switch",
    # exec redirect, a descriptor of the program's own
    "exec < ~/.claude/scripts/harness-switch",
    "exec 0< ~/.claude/scripts/harness-switch; python3",
    "exec < ~/.claude/scripts/harness-switch; python3 -",
    "python3 /dev/fd/3 3< ~/.claude/scripts/harness-switch",
    # find -exec
    "find ~/.claude/scripts -name harness-switch -exec python3 {} off \;",
    "find ~/.claude/scripts -name harness-switch -exec {} off \;",
    # startup-file variables
    "BASH_ENV=~/.claude/hooks/userprompt-harness-switch.sh bash -c true",
    "ENV=~/.claude/hooks/userprompt-harness-switch.sh sh -i",
    "PYTHONSTARTUP=~/.claude/scripts/harness-switch python3 -i",
    # options this reading does not know, a check flag with another
    "python3 --check-hash-based-pycs never ~/.claude/scripts/harness-switch off",
    "bash -nx ~/.claude/hooks/userprompt-harness-switch.sh",
    # multi-stage pipes, unknown runners
    "gzip -c ~/.claude/scripts/harness-switch | gunzip | python3 -",
    "uv run ~/.claude/scripts/harness-switch off",
    "pypy3 ~/.claude/scripts/harness-switch off",
    # a reader beside something that runs what it wrote or printed
    "sed -n 1p ~/.claude/scripts/harness-switch; cp ~/.claude/scripts/harness-switch /tmp/l34y; cd /tmp && ./l34y off",
    "cp ~/.claude/scripts/harness-switch /tmp/l34y; uv run python -c 'import os; os.system(\"/tmp/l34y\")'",
    "sed -n p ~/.claude/scripts/harness-switch > /tmp/l34y; python3 /tmp/l34y off",
    "sed -n p ~/.claude/scripts/harness-switch >/tmp/l34y && env python3 /tmp/l34y off",
    "sed -n p ~/.claude/scripts/harness-switch | head -1000 | python3 -",
    "sed -n p ~/.claude/scripts/harness-switch | sh",
    "sed -n p ~/.claude/scripts/harness-switch |& python3 -",
    "sed -n p ~/.claude/scripts/harness-switch | (python3 -)",
    "{ sed -n p ~/.claude/scripts/harness-switch; } | python3 -",
    "cat <(sed -n p ~/.claude/scripts/harness-switch) | python3 -",
    "sed -n p ~/.claude/scripts/harness-switch > >(python3 -)",
    "shellcheck ~/.claude/scripts/harness-switch; ls /tmp | xargs -I{} sh -c '/tmp/{}'",
    "shellcheck ~/.claude/scripts/harness-switch; find /tmp -maxdepth 1 -exec {} \;",
    "cp ~/.claude/scripts/harness-switch /tmp/l34y; find /tmp -name l34y -exec {} off \;",
    "cp ~/.claude/scripts/harness-switch /tmp/l34y; f=/tmp/l34y; $f off",
    "cp ~/.claude/scripts/harness-switch /tmp/l34y; python3 /tmp/l34?",
    "cp -t /tmp ~/.claude/scripts/harness-switch; python3 /tmp/harness-switch off",
    "cp ~/.claude/scripts/harness-switch /tmp/l34y; bash -c 'cd /tmp; python3 l34y off'",
    "cp ~/.claude/scripts/harness-switch /tmp/l34y; eval 'python3 /tmp/l34y'",
    "cp ~/.claude/scripts/harness-switch /tmp/l34y; nohup sudo python3 /tmp/l34y off",
    "cp ~/.claude/scripts/harness-switch /tmp/l34y; python3 - <<'X'\nimport os; os.system('/tmp/l34y off')\nX",
    "shellcheck ~/.claude/scripts/harness-switch; export BASH_ENV=/tmp/l34y; bash -n /tmp/z",
    "shellcheck ~/.claude/scripts/harness-switch > /tmp/l34y; . /tmp/l34y",
    "cd ~/.claude/scripts && sed -n 1p harness-switch && ./harness-switch off",
    # a reader's option that runs a program or writes the file
    "rg --pre python3 x ~/.claude/scripts/harness-switch",
    "rg --pre=sh x ~/.claude/scripts/harness-switch",
    "ruff check --fix ~/.claude/scripts/harness-switch",
    "pylint --init-hook='import os; os.system(\"x\")' ~/.claude/scripts/harness-switch",
    "sed -n '1e python3 /tmp/x' ~/.claude/scripts/harness-switch",
    "awk 'BEGIN{system(\"x\")}' ~/.claude/scripts/harness-switch",
    "vim -R -c '!sh' ~/.claude/scripts/harness-switch",
    "bash -n ~/.claude/hooks/userprompt-harness-switch.sh x",
    "python3 -I -m py_compile ~/.claude/scripts/harness-switch",
]

# Not proven a read (not on the reader allow-list): the parent's refusal stands.
PARENT_KEEPS = [
    "python3 -c 'import ast; ast.parse(open(\"x\").read())' ~/.claude/scripts/harness-switch",
    "vim ~/.claude/scripts/harness-switch",
    "code ~/.claude/scripts/harness-switch",
    "xargs grep -n off <<< ~/.claude/scripts/harness-switch",
    "find ~/.claude -name harness-switch -exec ls -l {} \;",
    "python3 tools/x.py --check ~/.claude/scripts/harness-switch",
    "bash scripts/lint.sh ~/.claude/scripts/harness-switch",
    "git commit -m 'fix harness-switch' -- scripts/harness-switch",
    "git stash -- scripts/harness-switch",
]

# Proven reads the parent refused: they pass.
PROVEN_READS = [
    "vim -R ~/.claude/scripts/harness-switch",
    "view ~/.claude/scripts/harness-switch",
    "sed -n 1,5p ~/.claude/scripts/harness-switch ~/.claude/hooks/userprompt-harness-switch.sh | grep -n x | wc -l",
    "timeout 9 shellcheck ~/.claude/scripts/harness-switch",
]


# Round 3: the proof allow-list holds no interpreter and nothing that writes. A python -m module runs
# a planted or copied <module>.py (the directory is first on sys.path); pylint and flake8 read rc files
# and plugin options from the directory; ruff check -o writes; cp plants a copy into ~/.bashrc, a PATH
# directory or as <module>.py; rg reads abbreviated long options. Each passed on the round-2 head.
NARROWED = [
    # formerly proven reads, now the parent's refusal
    "python3 -m py_compile ~/.claude/scripts/harness-switch",
    "python3 -m py_compile x.py ~/.claude/scripts/harness-switch",
    "python3 -mpy_compile ~/.claude/scripts/harness-switch",
    "pylint ~/.claude/scripts/harness-switch",
    "ruff check ~/.claude/scripts/harness-switch",
    "cp ~/.claude/scripts/harness-switch /tmp/backup-switch",
    "cp ~/.claude/scripts/harness-switch /tmp/l34-bak && diff /tmp/l34-bak ~/.claude/scripts/harness-switch",
    # 1: a python -m module planted or copied into the directory
    "printf 'import sys,runpy\\nrunpy.run_path(sys.argv[1])\\n' > py_compile.py; "
    "python3 -m py_compile ~/.claude/scripts/harness-switch",
    "cp ~/.claude/scripts/harness-switch {O}/py_compile.py; python3 -m py_compile hook <<< '{\"prompt\": \"/harness off\"}'",
    "cp ~/.claude/scripts/harness-switch tokenize.py; python3 -m tokenize hook <<< '{\"prompt\": \"/harness off\"}'",
    "cp ~/.claude/scripts/harness-switch pyclbr.py; python3 -mpyclbr hook < /tmp/p",
    "python3 -m tokenize ~/.claude/scripts/harness-switch",
    "python3 -m dis ~/.claude/scripts/harness-switch",
    "python3 -m pyflakes ~/.claude/scripts/harness-switch",
    # 2: pylint / flake8 / pyflakes and their rc files, abbreviated or config options
    "printf '[MAIN]\\ninit-hook=import runpy\\n' > .pylintrc; pylint ~/.claude/scripts/harness-switch",
    "pylint --rc /tmp/x ~/.claude/scripts/harness-switch",
    "pylint --init-hoo='import os' ~/.claude/scripts/harness-switch",
    "pylint --load-plugin=x ~/.claude/scripts/harness-switch",
    "flake8 --config /tmp/cfg ~/.claude/scripts/harness-switch",
    "flake8 --append-config=/tmp/cfg ~/.claude/scripts/harness-switch",
    "pyflakes ~/.claude/scripts/harness-switch",
    # 3: rg's program options, abbreviated, in a command the proof must cover (a lone rg is the
    # parent's reader: its --pre check reads the exact spelling alone, a gap this lane leaves)
    "shellcheck ~/.claude/scripts/harness-switch; rg --hostname-bin ~/.claude/scripts/harness-switch x /tmp",
    "shellcheck ~/.claude/scripts/harness-switch; rg --hostname-b=~/.claude/scripts/harness-switch x /tmp",
    "shellcheck ~/.claude/scripts/harness-switch; rg --pr ~/.claude/scripts/harness-switch x /tmp",
    "shellcheck ~/.claude/scripts/harness-switch; rg --pr=~/.claude/scripts/harness-switch x /tmp",
    "shellcheck ~/.claude/scripts/harness-switch; rg --pre-g '*' x ~/.claude/scripts/harness-switch",
    "shellcheck ~/.claude/scripts/harness-switch; rg --hyperlink-f=x y ~/.claude/scripts/harness-switch",
    "shellcheck ~/.claude/scripts/harness-switch; rg --no-such-option y ~/.claude/scripts/harness-switch",
    "shellcheck ~/.claude/scripts/harness-switch; rg -z x ~/.claude/scripts/harness-switch",
    # 4: cp planting a copy where a shell, PATH or python finds it
    "cp ~/.claude/scripts/harness-switch ~/.bashrc",
    "cp ~/.claude/scripts/harness-switch ~/.local/bin/python3",
    "cp ~/.claude/scripts/harness-switch {O}/sitecustomize.py; python3 -c 1",
    "cp ~/.claude/scripts/harness-switch ~/.local/bin/sw; sw off",
    "cp -l ~/.claude/scripts/harness-switch /tmp/q",
    "cp -s ~/.claude/scripts/harness-switch /tmp/q",
    "cp ~/.claude/scripts/harness-switch ~/.claude/scripts/harness-switch.bak",
    # 5: a reader writing a file, the ruff and git writes
    "ruff check -o /tmp/q ~/.claude/scripts/harness-switch",
    "ruff check --output-file=/tmp/q ~/.claude/scripts/harness-switch",
    "sed -n 1p ~/.claude/scripts/harness-switch > /tmp/q; grep -n x ~/.claude/scripts/harness-switch",
    "shellcheck ~/.claude/scripts/harness-switch | tee /tmp/q",
    "git diff --no-index --output=/tmp/q ~/.claude/scripts/harness-switch /dev/null",
    "shellcheck ~/.claude/scripts/harness-switch; git diff --no-index --out=/tmp/q ~/.claude/scripts/harness-switch /dev/null",
    "shellcheck ~/.claude/scripts/harness-switch; git log -p --ext -- ~/.claude/scripts/harness-switch",
    "vi -R ~/.claude/scripts/harness-switch",
    "nvim -R ~/.claude/scripts/harness-switch",
    "zsh -n ~/.claude/hooks/userprompt-harness-switch.sh",
]

# Still proven reads after the narrowing.
STILL_PROVEN = [
    "rg -n --hidden --glob '*.sh' harness ~/.claude/scripts/harness-switch",
    "shellcheck ~/.claude/scripts/harness-switch 2>&1 | head -5",
    "sed -n 1p ~/.claude/scripts/harness-switch 2>/dev/null",
    "bash -n ~/.claude/hooks/userprompt-harness-switch.sh < /dev/null",
    "less -R ~/.claude/scripts/harness-switch",
    "shellcheck ~/.claude/scripts/harness-switch; rg -n --hidden x ~/.claude/scripts/harness-switch",
    "shellcheck ~/.claude/scripts/harness-switch; git log --oneline -- ~/.claude/scripts/harness-switch",
]


@pytest.mark.parametrize("command", NARROWED)
@pytest.mark.parametrize("actor", ["main", "subagent"])
def test_narrowed_allow_list_refuses(box, command, actor):
    command = fill(box, command)
    for cwd in (box["other"], box["h"]):
        rc, err = hook(box, command, cwd, actor)
        assert rc == 2 and "harness-switch:" in err, (command, cwd, err)


@pytest.mark.parametrize("command", STILL_PROVEN)
@pytest.mark.parametrize("actor", ["main", "subagent"])
def test_kept_reader_still_passes(box, command, actor):
    command = fill(box, command)
    for cwd in (box["other"], box["h"], box["home"]):
        rc, err = hook(box, command, cwd, actor)
        assert rc == 0 and "harness-switch:" not in err, (command, cwd, err)


@pytest.mark.parametrize("command", RUNS_THE_SWITCH + PARENT_KEEPS)
@pytest.mark.parametrize("actor", ["main", "subagent"])
def test_unproven_read_keeps_the_parent_refusal(box, command, actor):
    command = fill(box, command)
    for cwd in (box["other"], box["h"]):
        rc, err = hook(box, command, cwd, actor)
        assert rc == 2 and "harness-switch:" in err, (command, cwd, err)


@pytest.mark.parametrize("command", PROVEN_READS)
@pytest.mark.parametrize("actor", ["main", "subagent"])
def test_proven_read_passes(box, command, actor):
    command = fill(box, command)
    for cwd in (box["other"], box["h"], box["home"]):
        rc, err = hook(box, command, cwd, actor)
        assert rc == 0 and "harness-switch:" not in err, (command, cwd, err)


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
