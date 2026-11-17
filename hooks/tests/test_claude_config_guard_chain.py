"""hooks/pretool-claude-config-guard.py: the proof cannot be chained (OB-L31 round 4).

The proof (_proven_harmless) lets a Bash command the base reading refuses through when every write it
makes is read and lies outside the protected folders. Round 3 left four ways to chain a proven write
into a protected one, all refused by the base and passed by the proof:

1. an alias: `cp -l`, `cp -s`, `--link`, `--symbolic-link` (or a recursive, archive or no-dereference
   copy, or a move, carrying a symlink) makes a path outside the folders that a later proven write
   writes through into one;
2. git code the same command planted: `.git/hooks/pre-commit` then `git commit`, `.git/config`,
   `~/.gitconfig` or `.gitattributes` then `git diff`;
3. rg options that run a program (`--pre`, `--hostname-bin`, `--search-zip`) or a config file named by
   RIPGREP_CONFIG_PATH;
4. any file written outside a temp location and then a tool that reads config or runs files (git, gh,
   a `bash -c` under BASH_ENV), or any write into a directory on PATH.

Each of these is now not proven, so the base reading decides (and refuses). Each case runs the real
hook as a subprocess, with a scratch HOME and CLAUDE_HOME.
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
    root = tmp_path_factory.mktemp("config-guard-chain")
    home, project, t = root / "home", root / "proj", root / "t"
    for d in (home / ".claude" / "commands", home / ".claude" / "hooks", home / ".local" / "bin",
              home / ".config" / "git", project / ".claude" / "commands", project / ".claude" / "hooks",
              project / "docs", t / "dir", t / "repo" / ".git"):
        d.mkdir(parents=True)
    (project / ".claude" / "hooks" / "x.py").write_text("x = 1\n")
    (home / ".claude" / "hooks" / "x.py").write_text("x = 1\n")
    for name in ("evil.sh", "gc", "gattr", "x"):
        (t / name).write_text("x\n")
    os.symlink(project / ".claude" / "hooks" / "x.py", t / "lnk")
    os.symlink(project / ".claude" / "hooks" / "x.py", t / "dir" / "lnk")
    return home, project


def _run(scratch, command: str, actor=None, extra_env=None):
    home, project = scratch
    payload = {"session_id": "sess-chain", "transcript_path": str(project / "t.jsonl"),
               "cwd": str(project), "hook_event_name": "PreToolUse", "tool_name": "Bash",
               "tool_input": {"command": command}}
    if actor:
        payload.update(agent_id=actor[0], agent_type=actor[1])
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE", "GIT_", "RIPGREP")) and k not in ("CDPATH", "BASH_ENV", "ENV")}
    env.update(HOME=str(home), CLAUDE_HOME=str(home / ".claude"), CLAUDE_PROJECT_DIR=str(project),
               PYTHONDONTWRITEBYTECODE="1")
    for key, value in (extra_env or {}).items():
        env[key] = value.replace("@HOME@", str(home))
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                          text=True, cwd=str(project), env=env, timeout=30)


TAIL = "; cp .claude/hooks/x.py /tmp/y"

# 1. a link or a copied symlink makes an alias of a protected file that a later write writes through
ALIASES = [
    "cp -l .claude/hooks/x.py ../t/h && cp /tmp/evil ../t/h",
    "cp -l .claude/hooks/x.py ../t/h; echo pwned >> ../t/h",
    "cp --link .claude/hooks/x.py ../t/h2 && truncate -s 0 ../t/h2",
    "cp --li .claude/hooks/x.py ../t/h2 && truncate -s 0 ../t/h2",
    "cp -s \"$PWD/.claude/hooks/x.py\" ../t/s && echo pwned | tee ../t/s",
    "cp -s .claude/hooks/x.py ../t/s && echo pwned | tee ../t/s",
    "cp --symbolic-link .claude/hooks/x.py ../t/s2; echo pwned > ../t/s2",
    "cp --sym .claude/hooks/x.py ../t/s2; echo pwned > ../t/s2",
    "cp -s .claude/hooks/ ../t/sd && cp /tmp/evil ../t/sd/new.py",
    "cp -rl .claude/hooks/ ../t/hl && echo pwned >> ../t/hl/x.py",
    "cp -fl .claude/hooks/x.py /tmp/hl && echo pwned >> /tmp/hl",
    "cp -l ~/.claude/hooks/x.py ../t/hh && echo pwned >> ../t/hh",
    "cp -l \"$HOME/.claude/hooks/x.py\" ../t/hh3 && echo pwned >> ../t/hh3",
    "cp -s \"$HOME/.claude/hooks/x.py\" /tmp/hh4 && echo pwned >> /tmp/hh4",
    "env cp -l .claude/hooks/x.py /tmp/hl2 && echo pwned >> /tmp/hl2",
    "bash -c 'cp -l .claude/hooks/x.py /tmp/hl3' && echo pwned >> /tmp/hl3",
    # a copy or move that carries an existing symlink into the folder
    "cp -P ../t/lnk /tmp/z1 && echo pwned > /tmp/z1" + TAIL,
    "cp -d ../t/lnk /tmp/z2 && echo pwned > /tmp/z2" + TAIL,
    "cp --no-dereference ../t/lnk /tmp/z3 && echo pwned > /tmp/z3" + TAIL,
    "cp -a ../t/lnk /tmp/z4 && echo pwned > /tmp/z4" + TAIL,
    "cp --preserve=links -P ../t/lnk /tmp/z5; echo pwned > /tmp/z5" + TAIL,
    "cp -r ../t/dir /tmp/d1 && echo pwned > /tmp/d1/lnk" + TAIL,
    "cp -R ../t/dir /tmp/d2 && sed -i s/x/y/ /tmp/d2/lnk" + TAIL,
    "cp -a ../t/dir/. /tmp/d3 && tee /tmp/d3/lnk < /dev/null" + TAIL,
    "cp -H -r ../t/dir /tmp/d4 && echo pwned >> /tmp/d4/lnk" + TAIL,
    "mv ../t/dir /tmp/d5 && echo pwned > /tmp/d5/lnk" + TAIL,
    "cp -a .claude/hooks/ /tmp/d6 && echo pwned >> /tmp/d6/x.py",
    # install runs a strip program; a BSD install links
    "install -s --strip-program=/tmp/w.sh ../t/x /tmp/i1" + TAIL,
    "install --strip ../t/x /tmp/i2" + TAIL,
    "install -l s ../t/x /tmp/i3" + TAIL,
]

# 2. git code the same command planted, and git subcommands that run hooks
GIT_PLANTED = [
    "install -m 755 ../t/evil.sh .git/hooks/pre-commit && git commit --allow-empty -m 'cp a .claude/hooks/b'",
    "cp ../t/gc ~/.gitconfig && git diff" + TAIL,
    "cp ../t/gc .git/config && git diff" + TAIL,
    "cp ../t/gattr .gitattributes && git diff" + TAIL,
    "cp ../t/gattr docs/.gitattributes && git log -p" + TAIL,
    "cp ../t/gc .gitmodules && git log" + TAIL,
    "cp ../t/gc ~/.config/git/config && git log" + TAIL,
    "cp ../t/gc ~/.config/git/attributes && git show" + TAIL,
    "cd /tmp && cp ../t/gc .git/config && git diff" + TAIL,
    "cp ../t/gc /tmp/r/.git/config && git -C /tmp/r log" + TAIL,
    "cp -r ../t/repo /tmp/r2 && cd /tmp/r2 && git log" + TAIL,
    "mv /tmp/r3 /tmp/r4 && cd /tmp/r4 && git log" + TAIL,
    "git commit --allow-empty -m 'cp a .claude/hooks/b'",
    "git commit -m \"fix cp into .claude/hooks/\"",
    "git status" + TAIL,
    "git add -A" + TAIL,
]

# 3. rg options that run a program or read a config file
RG_RUNS = [
    "install -m 755 ../t/evil.sh /tmp/w.sh && rg --hostname-bin=/tmp/w.sh --hyperlink-format=default x README"
    + TAIL,
    "rg --hostname-bin=../t/evil.sh --hyperlink-format=default x README" + TAIL,
    "rg --hyperlink-format=default x README" + TAIL,
    "rg --pre /tmp/w.sh x README" + TAIL,
    "rg --pre-glob '*.py' x README" + TAIL,
    "rg -z x README" + TAIL,
    "rg -nz x README" + TAIL,
    "rg --search-zip x README" + TAIL,
    "rg --unknown-option x README" + TAIL,
]

# 4. a non-temp write, then a tool that reads config or runs files
CHAINED = [
    "cp ../t/evil.sh conv.sh && git log -p" + TAIL,
    "cp a b && git log --oneline -- .claude/hooks/",
    "cp a b && git -C .claude/hooks/ log --oneline -5",
    "echo x > docs/a.txt && git diff --stat" + TAIL,
    "git log -1 > docs/l.txt" + TAIL,
    "cp ../t/x ~/.config/gh/config.yml && gh pr view 1" + TAIL,
    "cp ../t/x docs/y && gh pr list" + TAIL,
]

# 4. env-dependent: PATH, BASH_ENV and RIPGREP_CONFIG_PATH name files a command may write
ENV_CHAINED = [
    ("cp ../t/evil.sh ~/.local/bin/grep && grep x README" + TAIL, {"PATH": "@HOME@/.local/bin:/usr/bin:/bin"}),
    ("cp ../t/evil.sh /tmp/pbin/ls && ls" + TAIL, {"PATH": "/tmp/pbin:/usr/bin:/bin"}),
    ("mv /tmp/q ~/.local/bin && ls" + TAIL, {"PATH": "@HOME@/.local/bin:/usr/bin:/bin"}),
    ("cp ../t/evil.sh ./cat && cat README" + TAIL, {"PATH": ".:/usr/bin:/bin"}),
    ("cp ../t/evil.sh ~/.benv && bash -c 'ls'" + TAIL, {"BASH_ENV": "@HOME@/.benv"}),
    ("rg -n x README > /tmp/r" + TAIL, {"RIPGREP_CONFIG_PATH": "@HOME@/.ripgreprc"}),
]

# Harmless commands that must keep passing (the base refuses most: a cp word before the folder).
STILL_PROVEN = [
    "cp .claude/hooks/x.py /tmp/a",
    "cp -r .claude/commands/ /tmp/cmds && tee /tmp/l < /dev/null",
    "cp -r .claude/hooks/ /tmp/bk && ls /tmp/bk",
    "cp -L ../t/lnk /tmp/z && cat /tmp/z" + TAIL,
    "cp a /tmp/b && git log --oneline -- .claude/hooks/",
    "cp a /tmp/b && git -C .claude/hooks/ log --oneline -5",
    "git log --oneline -5 > /tmp/l.txt" + TAIL,
    "cp a b && rg -n x .claude/hooks/ > /tmp/r.txt",
    "rg -n -i --hidden -g '*.py' -A 2 'tee ' .claude/hooks/ > /tmp/r; cp a /tmp/b",
    "rg -nw --type=py -e 'mv ' --max-count 3 .claude/hooks/; cp .claude/hooks/x.py /tmp/y",
    "cp a b && ls .claude/hooks/ | sort -n > /tmp/l",
    "cp .claude/hooks/x.py /tmp/y.py && sed -i s/a/b/ /tmp/y.py",
    "gh pr create --title x --body \"mv .claude/commands/a b\"",
]


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("command", ALIASES)
def test_an_alias_into_a_protected_folder_is_not_proven(scratch, command, actor):
    proc = _run(scratch, command, ACTORS[actor])
    assert proc.returncode == 2, (command, proc.returncode, proc.stderr)
    assert BLOCK in proc.stderr, proc.stderr


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("command", GIT_PLANTED)
def test_git_running_planted_code_is_not_proven(scratch, command, actor):
    proc = _run(scratch, command, ACTORS[actor])
    assert proc.returncode == 2, (command, proc.returncode, proc.stderr)
    assert BLOCK in proc.stderr, proc.stderr


@pytest.mark.parametrize("command", RG_RUNS)
def test_rg_beyond_its_read_options_is_not_proven(scratch, command):
    proc = _run(scratch, command)
    assert proc.returncode == 2, (command, proc.returncode, proc.stderr)
    assert BLOCK in proc.stderr, proc.stderr


@pytest.mark.parametrize("command", CHAINED)
def test_a_write_chained_into_a_config_reader_is_not_proven(scratch, command):
    proc = _run(scratch, command)
    assert proc.returncode == 2, (command, proc.returncode, proc.stderr)
    assert BLOCK in proc.stderr, proc.stderr


@pytest.mark.parametrize("command,extra", ENV_CHAINED)
def test_a_write_to_a_file_the_environment_runs_is_not_proven(scratch, command, extra):
    proc = _run(scratch, command, extra_env=extra)
    assert proc.returncode == 2, (command, proc.returncode, proc.stderr)
    assert BLOCK in proc.stderr, proc.stderr


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("command", STILL_PROVEN)
def test_a_harmless_command_is_still_proven(scratch, command, actor):
    proc = _run(scratch, command, ACTORS[actor])
    assert proc.returncode == 0, (command, proc.stderr)


def test_the_same_commands_pass_without_the_environment_hazard(scratch):
    """The env-dependent refusals come from the environment: without it the same text is proven."""
    assert _run(scratch, "rg -n x README > /tmp/r" + TAIL).returncode == 0
    assert _run(scratch, "cp ../t/evil.sh /tmp/pbin/ls && ls" + TAIL).returncode == 0
