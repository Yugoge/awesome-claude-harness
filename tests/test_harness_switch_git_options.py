"""hooks/pretool-harness-switch-guard.py: git's global options come before its subcommand.

`git -C <dir> diff ...` reads; `-C <dir>` (or `-c k=v`, `--git-dir=`, `--no-pager`, ...) is no
subcommand. A read-only subcommand passes even where its words name the home's settings files; a
writing one (checkout, restore, reset, stash push, apply, am, ...) or a reader given an option
that writes or runs a configured program (`--output`, `--ext-diff`, `--textconv`, `-O`) stays
refused, its pathspecs read from the -C directory too. A `-c` / `--config-env` that sets a key
naming a program (alias.*, core.hooksPath, core.fsmonitor, core.sshCommand, core.pager,
core.editor, diff.external, ...) or a value starting with `!` makes git never read-only, and is
refused outright where git runs in the harness home or Claude Code's config dir.

Each case runs the hook as Claude Code does (a PreToolUse payload on stdin) with a throwaway
HOME whose ~/.claude holds a settings.json, and a project with a .claude/settings.json.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "pretool-harness-switch-guard.py"


@pytest.fixture()
def box(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text('{"env": {"A": "1"}}\n')
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    (proj / ".claude" / "settings.json").write_text('{"env": {"A": "1"}}\n')
    other = tmp_path / "other"
    other.mkdir()
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDE_CONFIG_DIR", "CLAUDE_PROJECT_DIR") and not k.startswith("GIT_")}
    env["HOME"] = str(home)
    return {"home": home, "proj": proj, "other": other, "env": env}


def hook(box, command, cwd):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}
    proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                          text=True, env=box["env"], cwd=str(cwd), timeout=60)
    return proc.returncode, proc.stderr


def cwds(box):
    return (box["other"], box["proj"], box["home"] / ".claude")


MUST_PASS = [
    "git -C ~/.claude diff --stat -- ~/.claude/settings.json",
    "git -C ~/.claude log --oneline -3 -- scripts/harness-switch",
    "git -C {proj} log --oneline -- .claude/settings.json",
    # other global-option spellings before a read-only subcommand
    "git -C ~/.claude --no-pager diff -- settings.json",
    "git -P -C ~/.claude show HEAD:settings.json",
    "git --git-dir=$HOME/.claude/.git --work-tree=$HOME/.claude status",
    "git --git-dir ~/.claude/.git log -- settings.json",
    "git --literal-pathspecs -C ~/.claude blame settings.json",
    "git -C ~/.claude -c color.ui=never diff -- settings.json",
    "git -C ~/.claude --no-optional-locks status --porcelain -- settings.json",
    "git -C ~ -C .claude diff settings.json",
    "git -C ~/.claude stash list",
    "git -C ~/.claude stash show -p",
    "cd {proj} && git -C . log -p -- .claude/settings.json | head",
    "env LC_ALL=C git -C ~/.claude log -- settings.json",
    "git -C ~/.claude diff --output-indicator-new=+ -- settings.json",
]


@pytest.mark.parametrize("command", MUST_PASS)
def test_read_only_git_after_global_options_passes(box, command):
    command = command.format(proj=box["proj"])
    for cwd in cwds(box):
        rc, err = hook(box, command, cwd)
        assert rc == 0, (command, cwd, err)


MUST_REFUSE = [
    "git -C ~/.claude checkout -- settings.json",
    "git -C ~/.claude -c alias.x='!sh' x",
    "git -C ~/.claude restore settings.json",
    "git -C ~/.claude restore --source=HEAD~1 -- settings.json",
    "git -C ~/.claude reset -- settings.json",
    "git -C ~/.claude stash push -- settings.json",
    "git -C ~/.claude stash -- settings.json",
    "git -C ~/.claude apply settings.json.patch -- settings.json",
    "git -C ~/.claude am settings.json",
    "git -C ~/.claude diff --output=settings.json",
    "git -C ~/.claude diff --output settings.json",
    "git -C ~/.claude log --output=settings.json -p",
    "git -C ~/.claude show --output=settings.json HEAD:settings.json",
    "git -C ~/.claude diff --ext-diff -- settings.json",
    "git -C ~/.claude -c diff.x.textconv=sh diff --textconv -- settings.json",
    "git -C ~/.claude cat-file --textconv --path=settings.json HEAD",
    "git -C ~/.claude cat-file --filters --path=settings.json HEAD",
    "git -C ~/.claude grep -O'sh -c' env -- settings.json",
    "git -C ~/.claude --git-dir=.git checkout -- settings.json",
    "git --git-dir=$HOME/.claude/.git --work-tree=$HOME/.claude checkout -- settings.json",
    "git -C {proj} checkout -- .claude/settings.json",
    "env git -C ~/.claude checkout -- settings.json",
    "command git -C ~/.claude checkout -- settings.json",
    "timeout 5 git -C ~/.claude checkout -- settings.json",
    "bash -c 'git -C ~/.claude checkout -- settings.json'",
    "git -C \"$HOME/.claude\" checkout -- settings.json",
    "git -C ~ -C .claude checkout -- settings.json",
    "git -C ~/.claude --no-pager checkout -- settings.json",
]


@pytest.mark.parametrize("command", MUST_REFUSE)
def test_writing_git_after_global_options_refused(box, command):
    command = command.format(proj=box["proj"])
    for cwd in cwds(box):
        rc, err = hook(box, command, cwd)
        assert rc == 2, (command, cwd, err)
        assert "BLOCKED: harness-switch" in err


DANGEROUS_CONFIG = [
    "-c alias.x='!sh' x",
    "-c alias.st=status st",
    "-c core.hooksPath=/tmp/h status",
    "-c core.hookspath=/tmp/h status",
    "-c core.fsmonitor=/tmp/fs status",
    "-c core.sshCommand=/tmp/s log",
    "-c core.pager='sh -c x' log",
    "-c core.editor=/tmp/e diff",
    "-c diff.external=/tmp/d diff",
    "-c diff.x.textconv=/tmp/t diff",
    "-c pager.log='!sh' log",
    "-c x.y='!sh' log",
    "-calias.x='!sh' x",
    "--config-env=alias.x=EVIL x",
    "--config-env alias.x=EVIL x",
    "--config-env=core.fsmonitor=EVIL status",
]


@pytest.mark.parametrize("opts", DANGEROUS_CONFIG)
def test_program_config_in_home_refused(box, opts):
    for command in ("git -C ~/.claude %s" % opts, "cd ~/.claude && git %s" % opts):
        for cwd in cwds(box):
            rc, err = hook(box, command, cwd)
            assert rc == 2, (command, cwd, err)
    rc, err = hook(box, "git %s" % opts, box["home"] / ".claude")
    assert rc == 2, err


@pytest.mark.parametrize("opts", DANGEROUS_CONFIG)
def test_program_config_never_read_only(box, opts):
    """A reader's words that name a settings file stop being reads under such a -c."""
    command = "git -C ~/.claude %s -- settings.json" % opts
    rc, err = hook(box, command, box["other"])
    assert rc == 2, (command, err)


def test_program_config_outside_home_not_widened(box):
    """Outside the harness home a program-setting -c that names no protected file is not this
    rule's: it passed on the base and still does."""
    for command in ("git -c core.pager=less log --oneline -3", "git -C {proj} -c alias.st=status st"):
        rc, err = hook(box, command.format(proj=box["proj"]), box["other"])
        assert rc == 0, (command, err)


def test_git_env_config_never_read_only(box):
    for command in ("GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=diff.external GIT_CONFIG_VALUE_0=/tmp/d "
                    "git -C ~/.claude diff -- settings.json",
                    "GIT_EXTERNAL_DIFF=/tmp/d git -C ~/.claude diff -- settings.json",
                    "GIT_CONFIG_PARAMETERS=\"'core.pager'='sh'\" git -C ~/.claude log -- settings.json"):
        rc, err = hook(box, command, box["other"])
        assert rc == 2, (command, err)
