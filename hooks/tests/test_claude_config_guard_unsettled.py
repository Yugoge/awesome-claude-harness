"""hooks/pretool-claude-config-guard.py settles a Bash command only where it knows every write (OB-L31 rework).

The first OB-L31 change read each Bash command through the shared shell parser and let it through
unless a protected-folder site was in a short list of opaque commands. That passed real writes the
base refused: code fed to an interpreter on stdin (`python3 <<< "..."`, `echo ... | perl`), schedulers
(`at`, `batch`, `crontab -`), runners the parser does not peel (`runuser`, `caffeinate`, `uv run`,
`tmux new`), commands git or a tool runs (`git -c alias.x='!cp ...'`, `GIT_EDITOR=...`,
`tar --to-command=...`, `rsync -e ...`, `sed 'e ...'`) and shell functions (`f(){ cp "$@"; }; f x
.claude/hooks/a.py`). It also dropped the parser's targets on a parse error (the unterminated
`cd .claude/hooks && cat > x.py <<'EOF'` passed), and applied every `cd` to every relative write, so
`echo x > out.txt; cd .claude/hooks && ls` was refused.

Now a command is settled only if every simple command naming a protected folder is a reader, a
plain path operand of a command whose writes are read, or a payload walked on its own; anything else
falls back to the base raw-text reading. A `cd` applies only to what follows it in its own shell, and
the parser's targets count even when it reports an error. Writes the parser has no rule for (touch,
perl -i, patch, tar -x -C, unzip -d, git checkout into a folder, sed's w command, find -fprint,
`.claude/./hooks` spellings, `env -C`) are read too.

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
    root = tmp_path_factory.mktemp("config-guard-unsettled")
    home, project = root / "home", root / "proj"
    (home / ".claude" / "commands").mkdir(parents=True)
    (home / ".claude" / "hooks").mkdir()
    (project / ".claude" / "commands").mkdir(parents=True)
    (project / ".claude" / "hooks").mkdir()
    return home, project


def _run(scratch, command: str, actor=None):
    home, project = scratch
    payload = {"session_id": "sess-unsettled", "transcript_path": str(project / "t.jsonl"),
               "cwd": str(project), "hook_event_name": "PreToolUse", "tool_name": "Bash",
               "tool_input": {"command": command}}
    if actor:
        payload.update(agent_id=actor[0], agent_type=actor[1])
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_"))}
    env.update(HOME=str(home), CLAUDE_HOME=str(home / ".claude"), CLAUDE_PROJECT_DIR=str(project),
               PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                          text=True, cwd=str(project), env=env, timeout=30)


# Writes the base refused and the first OB-L31 change passed: the parser cannot settle them, so the
# base reading of the raw text decides again.
UNSETTLED_WRITES = [
    # code fed to an interpreter on stdin
    "python3 <<< \"import os; os.system('cp x .claude/hooks/a.py')\"",
    "python3 - <<'E'\nimport os; os.system('cp x .claude/hooks/a.py')\nE",
    "echo \"import os; os.system('cp x .claude/hooks/a.py')\" | python3",
    "perl <<< 'system \"cp x .claude/hooks/a.py\"'",
    "echo 'system \"cp x .claude/hooks/a.py\"' | perl",
    "node <<< 'require(\"child_process\").execSync(\"cp x .claude/hooks/a.py\")'",
    "php <<< '<?php system(\"cp x .claude/hooks/a.py\");'",
    "tclsh <<< 'exec cp x .claude/hooks/a.py'",
    "echo 'exec cp x .claude/hooks/a.py' | tclsh",
    "awk -f /dev/stdin <<< 'BEGIN{system(\"cp x .claude/hooks/a.py\")}'",
    "make -f /dev/stdin <<< 'a:;cp x .claude/hooks/a.py'",
    "make -f - <<'E'\na:\n\tcp x .claude/hooks/a.py\nE",
    "echo 'a:;cp x .claude/hooks/a.py' | make -f -",
    # schedulers
    "echo 'cp x .claude/hooks/a.py' | at now",
    "at now <<< 'cp x .claude/hooks/a.py'",
    "at now <<'E'\ncp x .claude/hooks/a.py\nE",
    "batch <<< 'cp x .claude/hooks/a.py'",
    "echo 'cp x .claude/hooks/a.py' | batch",
    "echo '* * * * * cp x ~/.claude/hooks/a.py' | crontab -",
    "crontab <<< '* * * * * cp x .claude/hooks/a.py'",
    # runners the parser does not peel
    "runuser -u root -- cp x .claude/hooks/a.py",
    "runuser -u root cp x .claude/hooks/a.py",
    "sudo -s 'cp x .claude/hooks/a.py'",
    "caffeinate cp x .claude/hooks/a.py",
    "gdb -batch -ex run --args cp x .claude/hooks/a.py",
    "uv run cp x .claude/hooks/a.py",
    "npx cp x .claude/hooks/a.py",
    "poetry run cp x .claude/hooks/a.py",
    "direnv exec . cp x .claude/hooks/a.py",
    "nix-shell --run 'cp x .claude/hooks/a.py'",
    "tmux new -d 'cp x .claude/hooks/a.py'",
    "screen -dm cp x .claude/hooks/a.py",
    # commands git or another tool runs
    "git -c alias.c='!cp x .claude/hooks/a.py' c",
    "git config alias.c '!cp x .claude/hooks/a.py'",
    "git config alias.c '!cp x .claude/hooks/a.py'; git c",
    "git -c core.pager='cp x .claude/hooks/a.py' log -1",
    "git -c core.editor='cp x .claude/hooks/a.py' commit --amend",
    "GIT_EDITOR='cp x .claude/hooks/a.py' git commit --amend",
    "GIT_EXTERNAL_DIFF='cp x .claude/hooks/a.py' git diff",
    "PAGER='cp x .claude/hooks/a.py' man ls",
    "tar --to-command='cp x .claude/hooks/a.py' -xf a.tar",
    "rsync -e 'cp x .claude/hooks/a.py #' a b:",
    "sed 'e cp x .claude/hooks/a.py' x",
    "sed '1e cp x .claude/hooks/a.py' x",
    "sed -e 'e cp x .claude/hooks/a.py' x",
    # shell functions
    "f(){ cp \"$@\"; }; f x .claude/hooks/a.py",
    "f(){ \"$@\"; }; f cp x .claude/hooks/a.py",
    "g(){ tee \"$1\"; }; g .claude/hooks/a.py",
    # variants: other folder, wrappers around the unknown runner, a here-string inside bash -c
    "python3 <<< \"import os; os.system('cp x .claude/commands/a.md')\"",
    "timeout 5 caffeinate cp x .claude/hooks/a.py",
    "bash -c \"python3 <<< 'import os; os.system(\\\"cp x .claude/hooks/a.py\\\")'\"",
    "c='cp x .claude/hooks/a.py'; $c",
]

# The audit's own example, a heredoc left unterminated: the parser's targets count with its error.
UNTERMINATED = [
    "cd .claude/hooks && cat > x.py <<'EOF'",
    "cd .claude/hooks && cat > x.py <<'EOF'\nprint(1)",
    "cd .claude/commands && tee x.md <<'EOF'",
    "echo x > .claude/hooks/a.py; echo 'unterminated",
]

# A cd applies only to what follows it in its own shell.
CD_SCOPED_PASS = [
    "cd .claude/hooks && ls; cd /tmp/work && echo x > out.txt",
    "echo x > out.txt; cd .claude/hooks && ls",
    "cd .claude/hooks && ls && cd - && echo x > out.txt",
    "(cd .claude/hooks && ls); echo x > out.txt",
    "(cd .claude/hooks; ls) && echo x > out.txt",
    "cd .claude/hooks && ls | wc -l; cd /tmp && echo x > out.txt",
    "cd .claude/hooks & echo x > out.txt",
    "bash -c 'cd .claude/hooks && ls'; echo x > out.txt",
    "pushd .claude/hooks && ls && popd >/dev/null; cd /tmp && echo x > out.txt",
    "cd ~/.claude/commands && ls; cd /tmp/x && cp a b",
]

# Where the cd cannot be followed exactly, every candidate directory counts for a later relative write.
CD_SCOPED_REFUSE = [
    "cd .claude/hooks; echo x > a.py",
    "cd .claude/hooks || exit; echo x > a.py",
    "cd /tmp && cd - && echo x > .claude/hooks/a",
    "cd .claude/hooks && cd - && cd - && echo x > a.py",
    "{ cd .claude/hooks; }; echo x > a.py",
    "eval 'cd .claude/hooks'; echo x > a.py",
    "if true; then cd .claude/hooks; fi; echo x > a.py",
    "cd .claude/hooks && f(){ echo x > a.py; }; cd /tmp; f",
    "x=$(cd .claude/hooks; echo x > a.py)",
    "bash -c 'cd .claude/hooks && echo x > a.py'",
    "cd .claude && popd; echo x > hooks/a.py",
    "CDPATH=.claude cd hooks && touch a",
    "cd -- .claude/hooks && cp x a",
    "cd .claude/hooks/../hooks && touch a",
]

# Writes the parser has no rule for, read by the guard itself.
OTHER_WRITES = [
    "touch .claude/hooks/a",
    "cd .claude/hooks && touch a",
    "pushd .claude/hooks && touch a",
    "perl -i -pe s/a/b/ .claude/hooks/x",
    "perl -pi -e s/a/b/ .claude/commands/x",
    "perl -i.bak -pe s/a/b/ .claude/hooks/x",
    "patch .claude/hooks/a < p.diff",
    "patch -d .claude/hooks -p1 < p.diff",
    "patch -o .claude/hooks/a x < p.diff",
    "tar -xf a.tar -C .claude/hooks",
    "tar -C .claude/hooks -xf a.tar",
    "tar xzf a.tgz --directory=.claude/commands",
    "unzip a.zip -d .claude/hooks",
    "git checkout HEAD .claude/commands",
    "git -C .claude/hooks checkout -- a",
    "git apply --directory=.claude/hooks p.diff",
    "sed -n 'w .claude/hooks/a.py' x",
    "sed -n '/x/w .claude/commands/a.md' x",
    "find . -fprint .claude/hooks/a.py",
    "find .claude/hooks -name '*.pyc' -delete",
    "cp x .claude/./hooks/a",
    "cp x .claude//hooks/a",
    "env -C .claude/hooks tee a",
    "env --chdir=.claude/hooks cp /tmp/x .",
]

# Reads and harmless commands next to the protected folders: none of them is refused.
STILL_PASS = [
    "cat .claude/hooks/a",
    "cp -r .claude/hooks /tmp/backup",
    "tar -cf /tmp/h.tar .claude/hooks",
    "tar -tf a.tar -C .claude/hooks",
    "git diff -- .claude/hooks",
    "git log --oneline -- .claude/commands",
    "cp ~/.claude/hooks/x .",
    "cp .claude/hooks/x .claude/hooks.bak/",
    "cd .claude/hooks; python3 -m pytest -q > /tmp/out.txt",
    "find .claude/hooks -name '*.py' | xargs grep -l x",
    "echo \"cp x .claude/hooks/a\" > /tmp/note.txt",
    "git commit -m \"fix cp into .claude/hooks/\"",
    "gh pr create --title x --body \"mv .claude/commands/a b\"",
    "cd .claude/hooks && ls; cd ../../src && make",
    "cd .claude/hooks && git status",
    "cd .claude/hooks && git checkout -b topic",
    "patch -o /tmp/out.py .claude/hooks/a.py < p.diff",
    "perl -ne 'print' .claude/hooks/a.py",
    "sed -n '/x/w /tmp/hits' .claude/hooks/a.py",
    "find .claude/hooks -name '*.py' -fprint /tmp/list",
    "unzip -l a.zip",
    "touch /tmp/stamp && ls .claude/hooks",
    "cat .claude/hooks/a.py | python3 -c 'import sys; print(len(sys.stdin.read()))'",
]


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("command", UNSETTLED_WRITES)
def test_an_unsettled_command_falls_back_to_the_base_reading(scratch, command, actor):
    proc = _run(scratch, command, ACTORS[actor])
    assert proc.returncode == 2, (command, proc.returncode, proc.stderr)
    assert BLOCK in proc.stderr, proc.stderr


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("command", UNTERMINATED)
def test_a_write_target_counts_despite_a_parse_error(scratch, command, actor):
    proc = _run(scratch, command, ACTORS[actor])
    assert proc.returncode == 2, (command, proc.returncode, proc.stderr)
    assert BLOCK in proc.stderr, proc.stderr


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("command", CD_SCOPED_PASS)
def test_a_cd_does_not_reach_a_write_outside_its_scope(scratch, command, actor):
    proc = _run(scratch, command, ACTORS[actor])
    assert proc.returncode == 0, (command, proc.stderr)


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("command", CD_SCOPED_REFUSE)
def test_a_cd_reaches_every_write_it_may_precede(scratch, command, actor):
    proc = _run(scratch, command, ACTORS[actor])
    assert proc.returncode == 2, (command, proc.returncode, proc.stderr)
    assert BLOCK in proc.stderr, proc.stderr


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("command", OTHER_WRITES)
def test_a_write_the_parser_has_no_rule_for_is_refused(scratch, command, actor):
    proc = _run(scratch, command, ACTORS[actor])
    assert proc.returncode == 2, (command, proc.returncode, proc.stderr)
    assert BLOCK in proc.stderr, proc.stderr


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("command", STILL_PASS)
def test_a_read_or_harmless_command_still_passes(scratch, command, actor):
    proc = _run(scratch, command, ACTORS[actor])
    assert proc.returncode == 0, (command, proc.stderr)
