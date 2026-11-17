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


# --- rework: readers, -O, abbreviations, config keys, config sources ---------------------------

READERS_PASS = [
    "git -C ~/.claude ls-tree HEAD settings.json",
    "git -C ~/.claude ls-tree -r --name-only HEAD -- settings.json",
    "git -C ~/.claude rev-list --count HEAD -- settings.json",
    "git -C ~/.claude shortlog -sn -- settings.json",
    "git -C ~/.claude reflog -- settings.json",
    "git -C ~/.claude reflog show -- settings.json",
    "git -C ~/.claude reflog list",
    "git -C ~/.claude whatchanged -1 -- settings.json",
    "git -C ~/.claude diff-tree -p HEAD -- settings.json",
    "git -C ~/.claude diff-index -p HEAD -- settings.json",
    "git -C ~/.claude diff-files -p -- settings.json",
    "git -C ~/.claude annotate settings.json",
    "git -C ~/.claude name-rev HEAD -- settings.json",
    "git -C ~/.claude describe --always -- settings.json",
    "git -C ~/.claude merge-base HEAD HEAD -- settings.json",
    "git -C ~/.claude for-each-ref -- settings.json",
    "git -C ~/.claude show-ref -- settings.json",
    "git -C ~/.claude cherry -v -- settings.json",
    "git -C ~/.claude range-diff HEAD~1...HEAD -- settings.json",
    "git -C ~/.claude count-objects -v -- settings.json",
    "git -C ~/.claude verify-commit HEAD -- settings.json",
    "git -C ~/.claude show-branch -- settings.json",
    "git -C ~/.claude check-ignore -v settings.json",
    # -O names an order file for diff, log and show; only git grep's -O runs a pager
    "git -C ~/.claude diff -O/tmp/order -- settings.json",
    "git -C ~/.claude log -p -O/tmp/order -- settings.json",
    "git -C ~/.claude show -O /tmp/order HEAD -- settings.json",
    "git -C ~/.claude diff-tree -p -Oorder HEAD -- settings.json",
    # harmless options that only look like a writing option's prefix
    "git -C ~/.claude diff --text -- settings.json",
    "git -C ~/.claude grep --text -e x -- settings.json",
    "git -C ~/.claude grep --or -e x -e y -- settings.json",
    "git -C ~/.claude grep -o -e x -- settings.json",
    "git -C ~/.claude grep -e O -- settings.json",
    "git -C ~/.claude grep -eO -- settings.json",
    "git -C ~/.claude diff --no-ext-diff --no-textconv -- settings.json",
    "git -C ~/.claude cat-file --batch-check -- settings.json",
    # config keys that name no program
    "git -C ~/.claude -c protocol.version=2 log -- settings.json",
    "git -C ~/.claude -c remote.origin.prune=true log -- settings.json",
    "git -C ~/.claude -c url.https://x/.insteadOf=git://x/ log -- settings.json",
    "git -C ~/.claude -c man.viewer=x log -- settings.json",
    "git -C ~/.claude -c credential.helper= log -- settings.json",
    "git -C ~/.claude -c credential.helper=  diff -- settings.json",
    "git -C ~/.claude -c filter.lfs.required=true diff -- settings.json",
]


@pytest.mark.parametrize("command", READERS_PASS)
def test_more_readers_pass(box, command):
    for cwd in cwds(box):
        rc, err = hook(box, command, cwd)
        assert rc == 0, (command, cwd, err)


WRITERS_REFUSED = [
    "git -C ~/.claude reflog expire --all -- settings.json",
    "git -C ~/.claude reflog delete HEAD@{0} -- settings.json",
    "git -C ~/.claude diff-tree --output=settings.json -p HEAD",
    "git -C ~/.claude shortlog --output=settings.json HEAD",
    "git -C ~/.claude blame --output=settings.json settings.json",
    "git -C ~/.claude grep --open='cp /tmp/evil.json' -e . -- ~/.claude/settings.json",
    "git -C ~/.claude grep --open-files='cp /tmp/evil.json' -e . -- settings.json",
    "git -C ~/.claude grep --op='cp /tmp/evil.json' -e . -- settings.json",
    "git -C ~/.claude grep --open-files-in-pager='cp /tmp/evil.json' -e . -- settings.json",
    "git -C ~/.claude grep -O -e . -- settings.json",
    "git -C ~/.claude grep -nO'cp /tmp/evil.json' -e . -- settings.json",
    "git -C ~/.claude grep -iwO'cp /tmp/evil.json' -e . -- settings.json",
    "git -C ~/.claude grep --textc -e . -- settings.json",
    "git -C ~/.claude cat-file --textc --path=settings.json HEAD",
    "git -C ~/.claude cat-file --tex --path=settings.json HEAD",
    "git -C ~/.claude cat-file --t --path=settings.json HEAD",
    "git -C ~/.claude cat-file --filt --path=settings.json HEAD",
    "git -C ~/.claude cat-file --fi --path=settings.json HEAD",
    "git -C ~/.claude range-diff --ext HEAD~1...HEAD -- settings.json",
    "env git -C ~/.claude grep --open='cp /tmp/evil.json' -e . -- settings.json",
    "bash -c \"git -C ~/.claude grep --open='cp /tmp/evil.json' -e . -- settings.json\"",
]


@pytest.mark.parametrize("command", WRITERS_REFUSED)
def test_writing_reader_options_refused(box, command):
    for cwd in cwds(box):
        rc, err = hook(box, command, cwd)
        assert rc == 2, (command, cwd, err)
        assert "BLOCKED: harness-switch" in err


STILL_PROGRAM = [
    "-c credential.helper=/tmp/h log",
    "-c credential.https://x.helper='!sh' log",
    "-c core.askPass=/tmp/a log",
    "-c core.gitProxy=/tmp/p log",
    "-c merge.x.driver=/tmp/m log",
    "-c filter.x.clean=/tmp/c diff",
    "-c filter.x.smudge=/tmp/c diff",
    "-c filter.x.process=/tmp/c diff",
    "-c include.path=/tmp/cfg log",
    "-c includeIf.gitdir:/.path=/tmp/cfg log",
    "-c gpg.program=/tmp/g log",
    "-c submodule.x.update=/tmp/u log",
    "-c man.x.cmd=/tmp/m log",
    "-c protocol.version='!sh' log",
]


@pytest.mark.parametrize("opts", STILL_PROGRAM)
def test_program_keys_still_refused_in_home(box, opts):
    for command in ("git -C ~/.claude %s" % opts, "cd ~/.claude && git %s" % opts):
        rc, err = hook(box, command, box["other"])
        assert rc == 2, (command, err)


CONFIG_SOURCES = [
    "HOME=/tmp/evil git -C ~/.claude diff --no-index /tmp/a ~/.claude/settings.json",
    "HOME=/tmp/evil git -C ~/.claude log -p",
    "HOME=/tmp/evil git diff --no-index /tmp/a ~/.claude/settings.json",
    "XDG_CONFIG_HOME=/tmp/evil git -C ~/.claude diff",
    "GIT_CONFIG_GLOBAL=/tmp/evil git -C ~/.claude diff",
    "GIT_CONFIG_SYSTEM=/tmp/evil git -C ~/.claude status",
    "GIT_DIR=/tmp/evil/.git git -C ~/.claude diff",
    "git -C ~/.claude --git-dir=/tmp/evil/.git diff",
    "git --git-dir=/tmp/evil/.git -C ~/.claude log -p",
    "git --git-dir /tmp/evil/.git --work-tree ~/.claude diff",
    "cd ~/.claude && HOME=/tmp/evil git diff",
    "env HOME=/tmp/evil git -C ~/.claude diff",
    "env -u PAGER HOME=/tmp/evil git -C ~/.claude diff",
    "timeout 5 env XDG_CONFIG_HOME=/tmp/evil git -C ~/.claude diff",
    "export HOME=/tmp/evil; git -C ~/.claude diff",
    "export GIT_CONFIG_GLOBAL=/tmp/evil && git -C ~/.claude log -p",
    "bash -c 'HOME=/tmp/evil git -C ~/.claude diff'",
    "HOME=/tmp/evil git -C /tmp diff --no-index /tmp/a ~/.claude/settings.json",
]


@pytest.mark.parametrize("command", CONFIG_SOURCES)
def test_agent_config_source_in_home_refused(box, command):
    for cwd in cwds(box):
        rc, err = hook(box, command, cwd)
        assert rc == 2, (command, cwd, err)
        assert "BLOCKED: harness-switch" in err


CONFIG_SOURCES_ELSEWHERE = [
    "HOME=/tmp/x git -C {proj} log --oneline -3",
    "HOME=/tmp/x git -C /tmp status",
    "XDG_CONFIG_HOME=/tmp/x git -C {other} status",
    "GIT_CONFIG_NOSYSTEM=1 git -C {proj} log",
    "GIT_DIR=/tmp/x/.git git log --oneline",
    "git --git-dir=/tmp/x/.git log --oneline",
    "HOME=/tmp/x git diff --no-index /tmp/a /tmp/b",
    "git --git-dir=$HOME/.claude/.git log -- settings.json",
]


@pytest.mark.parametrize("command", CONFIG_SOURCES_ELSEWHERE)
def test_config_source_away_from_home_passes(box, command):
    command = command.format(proj=box["proj"], other=box["other"])
    for cwd in (box["other"], box["proj"]):
        rc, err = hook(box, command, cwd)
        assert rc == 0, (command, cwd, err)


def test_grep_open_really_runs_pager_in_sandbox(box, tmp_path):
    """The verifier's proof, kept as the reason: git runs grep's --open value through the shell."""
    import shutil
    if not shutil.which("git"):
        pytest.skip("git not installed")
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "s.json").write_text("{}\n")
    evil = tmp_path / "evil.json"
    evil.write_text('{"env": {"EVIL": "1"}}\n')
    env = dict(box["env"], GIT_CONFIG_NOSYSTEM="1")
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "grep", "--no-index", "--open=cp %s" % evil, "-e", ".", "--", "s.json"],
                   env=env, capture_output=True, timeout=60)
    assert "EVIL" in (repo / "s.json").read_text()


# --- round 3: fd redirects, a foreign repository over the home, git's environment, harmless -c ---

REDIRECT_REFUSED = [
    "git -C ~/.claude show HEAD:settings.json 1>~/.claude/settings.json",
    "git -C ~/.claude show HEAD:settings.json 1> ~/.claude/settings.json",
    "git -C ~/.claude cat-file -p HEAD:settings.json 1>~/.claude/settings.json",
    "git -C ~/.claude show HEAD:x 1>~/.claude/.harness-switch/off",
    "git show HEAD:settings.json 1>~/.claude/settings.json",
    "git -C ~/.claude show HEAD:settings.json 1>>~/.claude/settings.json",
    "git -C ~/.claude show HEAD:settings.json 2>~/.claude/settings.json",
    "git -C ~/.claude show HEAD:settings.json &>~/.claude/settings.json",
    "git -C ~/.claude show HEAD:settings.json &>>~/.claude/settings.json",
    "git -C ~/.claude show HEAD:settings.json >|~/.claude/settings.json",
    "git -C ~/.claude log -1 2>>~/.claude/.harness-switch/off",
    "env git -C ~/.claude show HEAD:settings.json 1>~/.claude/settings.json",
    "bash -c 'git -C ~/.claude show HEAD:settings.json 1>~/.claude/settings.json'",
    "cd ~/.claude && git show HEAD:settings.json 1>settings.json",
    "cd ~/.claude && git show HEAD:settings.json 1> settings.json",
    "cd ~/.claude && git show HEAD:x 2>.harness-switch/off",
]


@pytest.mark.parametrize("command", REDIRECT_REFUSED)
def test_fd_redirect_after_reader_refused(box, command):
    for cwd in cwds(box):
        rc, err = hook(box, command, cwd)
        assert rc == 2, (command, cwd, err)
        assert "BLOCKED: harness-switch" in err


HOME_CWD_REDIRECT_REFUSED = [
    "git -C ~/.claude show HEAD:settings.json 1>settings.json",
    "git -C ~/.claude show HEAD:settings.json 2>settings.json",
    "git -C ~/.claude show HEAD:settings.json &>settings.json",
    "git -C ~/.claude show HEAD:x 1>.harness-switch/off",
    "git show HEAD:x 1>settings.json",
    "git cat-file -p HEAD:settings.json 1>settings.local.json",
]


@pytest.mark.parametrize("command", HOME_CWD_REDIRECT_REFUSED)
def test_fd_redirect_in_home_cwd_refused(box, command):
    rc, err = hook(box, command, box["home"] / ".claude")
    assert rc == 2, (command, err)


REDIRECT_PASS = [
    "git -C ~/.claude log --oneline 1>/tmp/log.txt",
    "git -C ~/.claude log -- settings.json 2>/dev/null",
    "git -C ~/.claude diff -- settings.json 2>&1 | head",
    "git -C ~/.claude show HEAD:settings.json 1>/tmp/settings.json.bak",
    "cat ~/.claude/settings.json 2>/dev/null",
]


@pytest.mark.parametrize("command", REDIRECT_PASS)
def test_fd_redirect_elsewhere_passes(box, command):
    for cwd in cwds(box):
        rc, err = hook(box, command, cwd)
        assert rc == 0, (command, cwd, err)


FOREIGN_TREE_REFUSED = [
    "git -C /tmp/evil --work-tree=~/.claude diff -- settings.json",
    "git -C /tmp/evil --work-tree ~/.claude log -p",
    "GIT_WORK_TREE=~/.claude git -C /tmp/evil diff -- settings.json",
    "env GIT_WORK_TREE=~/.claude git -C /tmp/evil diff",
    "cd /tmp/evil && git --work-tree ~/.claude diff -- settings.json",
    "git -C /tmp/evil -c core.worktree=~/.claude diff -- settings.json",
    "git --git-dir=/tmp/evil/.git --work-tree=~/.claude status",
    "GIT_WORK_TREE=~/.claude git checkout -- settings.json",
    "git -c core.worktree=~/.claude checkout -- settings.json",
]


@pytest.mark.parametrize("command", FOREIGN_TREE_REFUSED)
def test_foreign_repository_over_home_work_tree_refused(box, command):
    for cwd in cwds(box):
        rc, err = hook(box, command, cwd)
        assert rc == 2, (command, cwd, err)
        assert "BLOCKED: harness-switch" in err


FOREIGN_TREE_PASS = [
    "git -C ~/.claude --work-tree=~/.claude status",
    "GIT_WORK_TREE=~/.claude git -C ~/.claude status",
    "git --git-dir=$HOME/.claude/.git --work-tree=$HOME/.claude diff -- settings.json",
    "git -C {proj} --work-tree={proj} status",
    "GIT_WORK_TREE=/tmp/w git -C {proj} status",
    "git -C ~/.claude -c core.worktree=/tmp/w diff -- settings.json",
]


@pytest.mark.parametrize("command", FOREIGN_TREE_PASS)
def test_own_repository_work_tree_passes(box, command):
    command = command.format(proj=box["proj"])
    for cwd in cwds(box):
        rc, err = hook(box, command, cwd)
        assert rc == 0, (command, cwd, err)


ENV_PROGRAM = [
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.x GIT_CONFIG_VALUE_0='!sh' git -C ~/.claude x",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/tmp/h git -C ~/.claude status",
    "GIT_CONFIG_PARAMETERS=\"'alias.x'='!sh'\" git -C ~/.claude x",
    "GIT_CONFIG_PARAMETERS=\"'core.pager'='/tmp/p'\" git -C ~/.claude log",
    "GIT_CONFIG_PARAMETERS='garbage' git -C ~/.claude log",
    "export GIT_CONFIG_PARAMETERS=\"'alias.x'='!sh'\"; git -C ~/.claude x",
    "GIT_EXTERNAL_DIFF=/tmp/d git -C ~/.claude diff",
    "GIT_SSH_COMMAND=/tmp/s git -C ~/.claude fetch",
    "GIT_SSH=/tmp/s git -C ~/.claude fetch",
    "GIT_PAGER=/tmp/p git -C ~/.claude log",
    "GIT_PAGER='cp /tmp/evil.json settings.json;' git -C ~/.claude -p log -1",
    "PAGER=/tmp/p git -C ~/.claude log",
    "GIT_EDITOR=/tmp/e git -C ~/.claude commit",
    "EDITOR=/tmp/e git -C ~/.claude commit",
    "VISUAL=/tmp/e git -C ~/.claude commit",
    "GIT_ASKPASS=/tmp/a git -C ~/.claude fetch",
    "SSH_ASKPASS=/tmp/a git -C ~/.claude fetch",
    "env GIT_PAGER=/tmp/p git -C ~/.claude log",
    "timeout 5 env GIT_EXTERNAL_DIFF=/tmp/d git -C ~/.claude diff",
    "export GIT_PAGER=/tmp/p && git -C ~/.claude log",
    "GIT_PAGER=/tmp/p; git -C ~/.claude log",
    "declare -x GIT_EXTERNAL_DIFF=/tmp/d; git -C ~/.claude diff",
    "cd ~/.claude && GIT_EXTERNAL_DIFF=/tmp/d git diff",
    "GIT_PAGER=/tmp/p bash -c 'git -C ~/.claude log'",
]


@pytest.mark.parametrize("command", ENV_PROGRAM)
def test_program_environment_in_home_refused(box, command):
    for cwd in cwds(box):
        rc, err = hook(box, command, cwd)
        assert rc == 2, (command, cwd, err)
        assert "BLOCKED: harness-switch" in err


ENV_HARMLESS = [
    "GIT_PAGER=cat git -C ~/.claude log -3",
    "PAGER=less git -C ~/.claude log -3",
    "GIT_PAGER= git -C ~/.claude log -3 -- settings.json",
    "GIT_EDITOR=more git -C ~/.claude log -3",
    "export PAGER=cat; git -C ~/.claude log -3",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=color.ui GIT_CONFIG_VALUE_0=never git -C ~/.claude log -3",
    "GIT_CONFIG_PARAMETERS=\"'core.pager'='cat'\" git -C ~/.claude log -3",
    "GIT_PAGER=/tmp/p git -C {proj} log -3",
    "GIT_EXTERNAL_DIFF=/tmp/d git -C {proj} diff",
]


@pytest.mark.parametrize("command", ENV_HARMLESS)
def test_harmless_or_away_environment_passes(box, command):
    command = command.format(proj=box["proj"])
    for cwd in (box["other"], box["proj"]):
        rc, err = hook(box, command, cwd)
        assert rc == 0, (command, cwd, err)


HARMLESS_CONFIG_PASS = [
    "git -C ~/.claude -c core.pager=cat log -3",
    "git -C ~/.claude -c core.pager=less log -3",
    "git -C ~/.claude -c core.pager=more log -3",
    "git -C ~/.claude -c core.pager= log -3",
    "git -C ~/.claude -c pager.log=false log -3",
    "git -C ~/.claude -c core.editor=cat log -3",
    "git -C ~/.claude rev-list --filter=blob:none --objects HEAD -- settings.json",
    "git -C ~/.claude log --filter=blob:none -- settings.json",
    "git -C ~/.claude -c gpg.format=ssh log --show-signature",
    "git -C ~/.claude -c core.fsmonitor=true status",
    "git -C ~/.claude -c core.FSMonitor=false status",
    "git -C ~/.claude -c core.fsmonitor status",
    "git -C ~/.claude grep --fi=x -e y -- settings.json",
    "cd ~/.claude && git -c core.pager=cat log -1",
    # log, diff and the others take no abbreviation: git refuses these words and runs nothing
    "git -C ~/.claude log --outp settings.json",
    "git -C ~/.claude diff-index --o=settings.json HEAD",
]


@pytest.mark.parametrize("command", HARMLESS_CONFIG_PASS)
def test_harmless_config_and_options_pass(box, command):
    for cwd in cwds(box):
        rc, err = hook(box, command, cwd)
        assert rc == 0, (command, cwd, err)


def test_harmless_pager_in_home_cwd_passes(box):
    rc, err = hook(box, "git -c core.pager=cat log --oneline -3", box["home"] / ".claude")
    assert rc == 0, err


STILL_REFUSED_CONFIG = [
    "-c core.pager=/tmp/p log -3",
    "-c core.pager='cat; cp /tmp/evil.json settings.json' log -3",
    "-c core.pager='less x' log -3",
    "-c core.fsmonitor=/tmp/fs status",
    "-c core.fsmonitor='!sh' status",
    "-c pager.log=/tmp/p log",
    "-c gpg.program=/tmp/g log",
    "-c gpg.ssh.program=/tmp/g log",
    "-c gpg.x509.program=/tmp/g log",
    "-c gpg.ssh.defaultKeyCommand=/tmp/k log",
    "-c core.editor=/tmp/e commit",
    "--config-env=core.pager=X log",
]


@pytest.mark.parametrize("opts", STILL_REFUSED_CONFIG)
def test_program_values_still_refused(box, opts):
    for command in ("git -C ~/.claude %s" % opts, "cd ~/.claude && git %s" % opts):
        for cwd in cwds(box):
            rc, err = hook(box, command, cwd)
            assert rc == 2, (command, cwd, err)


def test_abbreviating_readers_still_refused(box):
    for command in ("git -C ~/.claude cat-file --filter --path=settings.json HEAD",
                    "git -C ~/.claude grep --textc -e x -- settings.json",
                    "git -C ~/.claude range-diff --outp=settings.json A...B",
                    "git -C ~/.claude log --output settings.json"):
        for cwd in cwds(box):
            rc, err = hook(box, command, cwd)
            assert rc == 2, (command, cwd, err)


def test_nested_shell_carries_config_source(box):
    home = box["home"] / ".claude"
    for command in ("HOME=/tmp/evil bash -c 'git -C %s diff'" % home,
                    "HOME=/tmp/evil sh -c 'cd %s && git diff'" % home,
                    "env XDG_CONFIG_HOME=/tmp/evil bash -c 'git -C %s log -1'" % home,
                    "GIT_CONFIG_GLOBAL=/tmp/evil nice -n 5 bash -c 'git -C %s diff'" % home):
        for cwd in cwds(box):
            rc, err = hook(box, command, cwd)
            assert rc == 2, (command, cwd, err)
    rc, err = hook(box, "HOME=/tmp/x bash -c 'git -C %s log -1'" % box["proj"], box["other"])
    assert rc == 0, err


# --- round 4: a redirect elsewhere writes no path word; harmless pagers and editors; more config
# sources, wrappers and program keys; variables exported without a readable value; grep -O ---

READER_REDIRECT_ELSEWHERE_PASS = [
    "git -C ~/.claude log --oneline -- settings.json > /tmp/x.log",
    "git -C ~/.claude grep -n hooks -- settings.json > /tmp/g",
    "git -C ~/.claude diff -- settings.json > /tmp/settings.diff",
    "git --work-tree=~/.claude --git-dir=~/.claude/.git log -- settings.json > /tmp/x",
    "git -C ~/.claude log -- settings.json 2>/tmp/err >/tmp/out",
    "git -C ~/.claude show HEAD:settings.json >> /tmp/s.bak",
    "git -C ~/.claude log -- settings.json &>/tmp/x.log",
    "cd ~/.claude && git log --oneline -- settings.json > /tmp/x.log",
    "env LC_ALL=C git -C ~/.claude diff -- settings.json >/tmp/d",
]


@pytest.mark.parametrize("command", READER_REDIRECT_ELSEWHERE_PASS)
def test_reader_with_redirect_elsewhere_passes(box, command):
    for cwd in cwds(box):
        rc, err = hook(box, command, cwd)
        assert rc == 0, (command, cwd, err)


READER_REDIRECT_PROTECTED_REFUSED = [
    "git -C ~/.claude log -- settings.json > ~/.claude/settings.json",
    "git -C ~/.claude diff -- settings.json 2> ~/.claude/settings.json",
    "git -C ~/.claude log -- x >/tmp/x 2>~/.claude/settings.local.json",
    "git -C ~/.claude log > /tmp/x 1>>~/.claude/.harness-switch/off",
    "cd ~/.claude && git log -- settings.json > /tmp/x 2>settings.json",
    "git -C ~/.claude log > ~/.claude/settings.json 2>/dev/null",
]


@pytest.mark.parametrize("command", READER_REDIRECT_PROTECTED_REFUSED)
def test_reader_redirect_onto_protected_file_still_refused(box, command):
    for cwd in cwds(box):
        rc, err = hook(box, command, cwd)
        assert rc == 2, (command, cwd, err)


HARMLESS_VIEWER_PASS = [
    "git -C ~/.claude -c core.pager='less -R' log -3",
    "git -C ~/.claude -c core.pager='less -FRX' log -3",
    "git -C ~/.claude -c core.pager='less -F -R -X' log -3",
    "git -C ~/.claude -c pager.log='less -S' log -3",
    "GIT_PAGER='less -R' git -C ~/.claude log -3",
    "PAGER='more -d' git -C ~/.claude log -3",
    "export GIT_PAGER='less -FRX'; git -C ~/.claude log -3",
    "EDITOR=vim git -C ~/.claude log -3",
    "export EDITOR=vim; git -C ~/.claude log -3 -- settings.json",
    "VISUAL=code GIT_EDITOR=nano git -C ~/.claude status",
    "GIT_SEQUENCE_EDITOR=vim git -C ~/.claude diff -- settings.json",
    "GIT_CONFIG_NOSYSTEM=1 git -C ~/.claude diff -- settings.json",
    "export GIT_CONFIG_NOSYSTEM=1; git -C ~/.claude log -3",
    "GIT_PAGER=cat; export GIT_PAGER; git -C ~/.claude log -3",
    "export GIT_DIR=~/.claude/.git; git -C ~/.claude log -- settings.json",
    "export GIT_WORK_TREE=~/.claude; git -C ~/.claude status",
    "git -C ~/.claude grep -Oless -e x",
    "git -C ~/.claude grep --open-files-in-pager -e x",
    "env -iu X git -C ~/.claude log -3",
    "xargs git -C ~/.claude log --oneline -3",
    "sudo -u root git -C ~/.claude log -3",
    "GIT_TRACE=1 git -C ~/.claude log -3",
    "GIT_TRACE=/tmp/trace.log git -C ~/.claude log -3",
]


@pytest.mark.parametrize("command", HARMLESS_VIEWER_PASS)
def test_round4_harmless_passes(box, command):
    for cwd in cwds(box):
        rc, err = hook(box, command, cwd)
        assert rc == 0, (command, cwd, err)


VIEWER_STILL_REFUSED = [
    "git -C ~/.claude -c core.pager='less +!sh' log -3",
    "git -C ~/.claude -c core.pager='less -o /tmp/x' log -3",
    "git -C ~/.claude -c core.pager='less -Ro/tmp/x' log -3",
    "git -C ~/.claude -c core.pager='less -O/tmp/x' log -3",
    "git -C ~/.claude -c core.pager='less --log-file=/tmp/x' log -3",
    "git -C ~/.claude -c core.pager='less --LOG-FILE=/tmp/x' log -3",
    "git -C ~/.claude -c core.pager='less -k /tmp/k' log -3",
    "git -C ~/.claude -c core.pager='less -R; sh' log -3",
    "git -C ~/.claude -c core.pager='less -R /tmp/x' log -3",
    "git -C ~/.claude -c core.pager='more +/x' log -3",
    "LESSOPEN='|/tmp/p %s' GIT_PAGER='less -R' git -C ~/.claude log -3",
    "export LESSKEY=/tmp/k; git -C ~/.claude -c core.pager='less -R' log -3",
    "LESS=-o/tmp/x git -C ~/.claude -c core.pager='less -R' log -3",
    "GIT_PAGER='vim -R' git -C ~/.claude log -3",
    "EDITOR=vim git -C ~/.claude commit",
    "EDITOR=vim git -C ~/.claude add -e",
    "export EDITOR=vim; git -C ~/.claude rebase -i HEAD~2",
    "GIT_SEQUENCE_EDITOR=vim git -C ~/.claude rebase -i HEAD~2",
    "git -C ~/.claude -c core.editor=vim commit",
    "git -C ~/.claude -c core.editor=vim tag -a v1",
]


@pytest.mark.parametrize("command", VIEWER_STILL_REFUSED)
def test_round4_viewer_with_program_still_refused(box, command):
    for cwd in cwds(box):
        rc, err = hook(box, command, cwd)
        assert rc == 2, (command, cwd, err)


ROUND4_REFUSED = [
    # GIT_COMMON_DIR as GIT_DIR; --exec-path=<dir> as GIT_EXEC_PATH; exported GIT_WORK_TREE
    "GIT_COMMON_DIR=/tmp/evil/.git git -C ~/.claude log",
    "export GIT_COMMON_DIR=/tmp/evil/.git; git -C ~/.claude log",
    "cd ~/.claude && GIT_COMMON_DIR=/tmp/evil/.git git log",
    "env GIT_COMMON_DIR=/tmp/evil/.git git -C ~/.claude log",
    "git --exec-path=/tmp/evil -C ~/.claude log",
    "git -C ~/.claude --exec-path=/tmp/evil status",
    "cd ~/.claude && git --exec-path=/tmp/evil log",
    "export GIT_WORK_TREE=~/.claude; git -C /tmp/evil diff -- settings.json",
    "GIT_WORK_TREE=~/.claude; export GIT_WORK_TREE; git -C /tmp/evil diff",
    "declare -x GIT_WORK_TREE=~/.claude; git -C /tmp/evil log -p",
    "export GIT_DIR=/tmp/evil/.git; git -C ~/.claude log",
    "git -C ~/.claude -c core.attributesFile=/tmp/a diff",
    # env clustered short options, xargs, sudo, doas
    "env -iu X git -C ~/.claude -c alias.x='!sh' x",
    "env -vu X GIT_PAGER=/tmp/p git -C ~/.claude log",
    "env -0u X git -C ~/.claude -c core.pager=/tmp/p log",
    "env -iC ~/.claude git -c alias.x='!sh' x",
    "env -iC ~/.claude git checkout -- settings.json",
    "env -iu X git -C ~/.claude checkout -- settings.json",
    "xargs git -C ~/.claude -c alias.x='!sh' x",
    "xargs -0 -n1 git -C ~/.claude -c core.pager=/tmp/p log",
    "echo x | xargs -I{} git -C ~/.claude -c alias.x='!sh' x",
    "xargs git -C ~/.claude checkout -- settings.json",
    "sudo git -C ~/.claude -c alias.x='!sh' x",
    "sudo -u root -E git -C ~/.claude -c core.pager=/tmp/p log",
    "sudo -D ~/.claude git checkout -- settings.json",
    "sudo git -C ~/.claude checkout -- settings.json",
    "sudo GIT_PAGER=/tmp/p git -C ~/.claude log",
    "doas -u root git -C ~/.claude -c alias.x='!sh' x",
    "GIT_PAGER=/tmp/p xargs git -C ~/.claude log",
    "GIT_PAGER=/tmp/p sudo git -C ~/.claude log",
    "HOME=/tmp/evil sudo git -C ~/.claude diff",
    # program keys
    "git -C ~/.claude -c trailer.x.cmd=/tmp/c log",
    "git -C ~/.claude -c trailer.x.command=/tmp/c log",
    "git -C ~/.claude -c tar.tgz.command=/tmp/c archive HEAD",
    "git -C ~/.claude -c imap.tunnel=/tmp/c log",
    "git -C ~/.claude -c guitool.x.cmd=/tmp/c log",
    "git -C ~/.claude -c init.templateDir=/tmp/t log",
    "git -C ~/.claude -c diff.guitool=x log",
    "git -C ~/.claude -c http.sslKeyLogFile=/tmp/k log",
    # a program-carrying variable exported without a readable value
    "printf -v GIT_PAGER %s /tmp/p; export GIT_PAGER; git -C ~/.claude log",
    "read -r GIT_EXTERNAL_DIFF <<< /tmp/d; export GIT_EXTERNAL_DIFF; git -C ~/.claude diff",
    "declare -n r=GIT_PAGER; r=/tmp/p; export GIT_PAGER; git -C ~/.claude log",
    "mapfile -t GIT_SSH_COMMAND < /tmp/f; export GIT_SSH_COMMAND; git -C ~/.claude fetch",
    "printf -v GIT_DIR %s /tmp/evil/.git; export GIT_DIR; git -C ~/.claude log",
    "printf -v GIT_COMMON_DIR %s /tmp/evil/.git; export GIT_COMMON_DIR; git -C ~/.claude log",
    "printf -v HOME %s /tmp/evil; export HOME; git -C ~/.claude diff",
    "printf -v XDG_CONFIG_HOME %s /tmp/evil; declare -x XDG_CONFIG_HOME; git -C ~/.claude diff",
    "read -r GIT_WORK_TREE <<< x; export GIT_WORK_TREE; git -C /tmp/evil diff",
    "printf -v GIT_CONFIG_PARAMETERS %s x; export GIT_CONFIG_PARAMETERS; git -C ~/.claude log",
    "GIT_PAGER=cat; printf -v GIT_PAGER %s /tmp/p; export GIT_PAGER; git -C ~/.claude log",
    "printf -v EDITOR %s /tmp/e; export EDITOR; git -C ~/.claude commit",
    "set -a; read -r GIT_PAGER <<< /tmp/p; git -C ~/.claude log",
    # git grep's -O / --open value is a program run where git runs
    "git -C ~/.claude grep -O/tmp/p -e x",
    "git -C ~/.claude grep -nO/tmp/p -e x",
    "git -C ~/.claude grep --open=/tmp/p -e x",
    "git -C ~/.claude grep --open-files-in-pager=/tmp/p -e x",
    "cd ~/.claude && git grep -O'sh -c x' -e x",
    # git's trace variables append to the file they name
    "GIT_TRACE=~/.claude/settings.json git -C /tmp log",
    "GIT_TRACE2_EVENT=$HOME/.claude/settings.json git status",
    "export GIT_TRACE_PERFORMANCE=~/.claude/settings.json; git status",
    "GIT_TRACE=~/.claude/.harness-switch/off git status",
]


@pytest.mark.parametrize("command", ROUND4_REFUSED)
def test_round4_under_defence_refused(box, command):
    for cwd in cwds(box):
        rc, err = hook(box, command, cwd)
        assert rc == 2, (command, cwd, err)
        assert "BLOCKED: harness-switch" in err


ROUND4_AWAY_PASS = [
    "GIT_COMMON_DIR=/tmp/x/.git git -C {proj} log",
    "git --exec-path=/tmp/x -C {proj} log",
    "git -C {proj} grep -O/tmp/p -e x",
    "sudo git -C {proj} -c core.pager=/tmp/p log",
    "xargs git -C {proj} -c alias.x='!sh' x",
    "printf -v GIT_PAGER %s /tmp/p; export GIT_PAGER; git -C {proj} log",
    "git -C {proj} -c trailer.x.cmd=/tmp/c log",
]


@pytest.mark.parametrize("command", ROUND4_AWAY_PASS)
def test_round4_away_from_home_passes(box, command):
    command = command.format(proj=box["proj"])
    for cwd in (box["other"], box["proj"]):
        rc, err = hook(box, command, cwd)
        assert rc == 0, (command, cwd, err)
