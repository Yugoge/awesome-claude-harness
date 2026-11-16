#!/usr/bin/env python3
"""The overnight guard reads a Bash command through the shared parser (lib/shell_parse.py).

Each decision that changed when the guard's Bash path moved onto the parser is pinned here, with
the hook run as the runtime runs it (JSON on stdin) against a toy checkout with a linked worktree
and live overnight-state records:

* a rule judges what a command writes or runs, not the words it mentions (O7);
* a write the parser reads into the main checkout is refused like `echo x > <main>/a` (Q3 (a));
* the rules other hooks own are refused there, not here (OG-01, OG-02 by
  pretool-claude-config-guard.py; OG-19..OG-21 by pretool-git-privilege-guard.py);
* a command the parser cannot read, or whose directory it cannot read, fails closed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "pretool-overnight-hook-guard.py"
CONFIG_GUARD = ROOT / "hooks" / "pretool-claude-config-guard.py"
STAND_IN = ROOT / "tests" / "replay" / "bin"  # the replays' bubblewrap stand-in
GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid"}
FAR = "2099-01-01T00:00:00Z"


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV}, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    """main (a checkout on master) with a linked worktree wt; an isolated record s-iso (worktree
    wt) and an in-place record s-inp (main), both protecting master."""
    main, wt = tmp_path / "main", tmp_path / "wt"
    main.mkdir()
    _git("init", "-q", "-b", "master", cwd=main)
    _git("commit", "-q", "--allow-empty", "-m", "init", cwd=main)
    _git("worktree", "add", "-q", "-b", "night", str(wt), cwd=main)
    (main / ".claude").mkdir()
    for sid, kind, work in (("s-iso", "registered_worktree", wt), ("s-inp", "in_place", main)):
        (main / ".claude" / f"overnight-state-{sid}.json").write_text(json.dumps({
            "schema_version": 9, "session_id": sid, "isolation_kind": kind, "main_root": str(main),
            "main_git_dir": str(main / ".git"), "worktree_path": str(work), "worktree_branch": "night",
            "protected_branch": "master", "end_time": FAR, "isolation_active_until": FAR,
            "current_cycle": 1}))
    return main, wt


def _run(hook: Path, main: Path, command: str, cwd: Path, session: str, bwrap: bool, agent: bool = False):
    payload = {"session_id": session, "tool_name": "Bash", "tool_input": {"command": command},
               "cwd": str(cwd), "transcript_path": str(main / "t.jsonl")}
    if agent:
        payload["agent_id"] = "a1b2c3d4"
    env = {**os.environ, **GIT_ENV, "CLAUDE_PROJECT_DIR": str(main), "PWD": str(cwd),
           "CLAUDE_HOME": str(ROOT)}
    if bwrap:
        env["PATH"] = f"{STAND_IN}{os.pathsep}{env['PATH']}"
    else:
        env["CLAUDE_OVERNIGHT_FORCE_NO_BWRAP"] = "1"
    return subprocess.run([sys.executable, str(hook)], input=json.dumps(payload), capture_output=True,
                          text=True, env=env, cwd=str(cwd), timeout=120)


def _isolated(repo, command, bwrap=True, agent=False):
    main, wt = repo
    return _run(HOOK, main, command, wt, "s-iso", bwrap, agent)


WHO = pytest.mark.parametrize("agent", [False, True], ids=["main agent", "subagent"])


# ---- O7: writes, not mentions ---------------------------------------------------------------------

@pytest.mark.parametrize("session", ["s-iso", "s-other"])
def test_reading_a_state_file_after_a_redirect_is_not_a_state_write(repo, session):
    main, wt = repo
    r = _run(HOOK, main, "git log > /tmp/l; cat .claude/overnight-state-x.json", main, session, True)
    assert "STATE PROTECTION" not in r.stderr, r.stderr


@pytest.mark.parametrize("command", [
    "rm .claude/overnight-state-s-iso.json", "mv .claude/overnight-state-s-iso.json /tmp/",
    "echo x > .claude/overnight-state-s-iso.json", "sed -i s/a/b/ .claude/overnight-state-s-iso.json",
    "dd of=.claude/overnight-state-x.json", "bash -c 'echo {} > .claude/overnight-state-x.json'",
])
def test_every_write_of_a_state_file_is_refused_for_every_session(repo, command):
    main, _wt = repo
    r = _run(HOOK, main, command, main, "s-other", False)
    assert r.returncode == 2 and "OVERNIGHT STATE PROTECTION" in r.stderr, (command, r.stderr)


@WHO
@pytest.mark.parametrize("command", ["git worktree list", "git worktree list --porcelain"])
def test_listing_worktrees_passes(repo, command, agent):
    assert _isolated(repo, command, agent=agent).returncode == 0


@WHO
@pytest.mark.parametrize("command", ["git worktree add ../x", "git worktree remove ../x", "git worktree prune",
                                     "bash -c 'git worktree move a b'"])
def test_changing_worktrees_is_refused(repo, command, agent):
    r = _isolated(repo, command, agent=agent)
    assert r.returncode == 2 and "OVERNIGHT WORKTREE BLOCK" in r.stderr, (command, r.stderr)


@pytest.mark.parametrize("bwrap", [False, True], ids=["no bwrap", "bwrap"])
def test_a_harness_script_run_through_python3_is_not_an_interpreter_hiding_git(repo, bwrap):
    """The script operand is the harness's own code; its arguments name what it works on."""
    r = _isolated(repo, f"python3 {ROOT}/hooks/lib/overnight.py --help master checkout", bwrap)
    assert "SUBPROCESS GIT BLOCK" not in r.stderr and "WRITE-BOUNDARY" not in r.stderr, r.stderr


@pytest.mark.parametrize("command", ['git commit -m "update the bash script"', "echo sh", "env FOO=1 ls",
                                     'git commit -m "explain python3 usage"'])
def test_an_interpreter_named_as_a_word_is_not_a_launch_without_bwrap(repo, command):
    assert _isolated(repo, command, bwrap=False).returncode == 0


@pytest.mark.parametrize("command", ["python3 -c 'print(1)'", "ksh -c 'ls'", "bash x.sh", "node a.js"])
def test_an_interpreter_launch_still_fails_closed_without_bwrap(repo, command):
    r = _isolated(repo, command, bwrap=False)
    assert r.returncode == 2 and "WRITE-BOUNDARY FAIL-CLOSED" in r.stderr, (command, r.stderr)


def test_a_docker_compose_output_redirect_passes_but_not_another_command_s(repo):
    """An actor in a worktree (no session of its own) writing outside every worktree: QA's
    `docker compose up|build` output redirection passes, any other command's write does not."""
    main, wt = repo
    assert _run(HOOK, main, "docker compose up -d > /srv/overnight-compose-log", wt, "s-other", False).returncode == 0
    r = _run(HOOK, main, "docker compose up -d; echo x > /srv/overnight-elsewhere", wt, "s-other", False)
    assert r.returncode == 2 and "OVERNIGHT WORKTREE ENFORCEMENT" in r.stderr, r.stderr


# ---- Q3 (a): writes the parser reads -----------------------------------------------------------

@WHO
@pytest.mark.parametrize("form", [
    "echo x > {m}/a.txt", "dd if=/dev/zero of={m}/a.txt", "truncate -s0 {m}/a.txt", "ln -sf /x {m}/a.txt",
    "curl -o {m}/a.txt http://example.invalid", "echo x >| {m}/a.txt", "git checkout HEAD -- {m}/a.txt",
    "git restore {m}/a.txt", "bash -c 'echo x > {m}/a.txt'",
])
def test_a_write_into_the_main_checkout_is_refused_without_bwrap(repo, form, agent):
    main, _wt = repo
    r = _isolated(repo, form.format(m=main), bwrap=False, agent=agent)
    assert r.returncode == 2, (form, r.stderr)


# ---- reading through `bash -c`, `cd` and wrappers ----------------------------------------------

@pytest.mark.parametrize("command", ["bash -c 'cd {m} && git log'", "sh -c 'git -C {m} status'",
                                     "bash -c 'pushd {m}; git status'"])
def test_a_shell_payload_is_read_like_the_command_line(repo, command):
    main, _wt = repo
    r = _isolated(repo, command.format(m=main))
    assert r.returncode == 2 and "MAIN-ROOT BLOCK" in r.stderr, (command, r.stderr)


@pytest.mark.parametrize("command", ["env -C /tmp git clean -fd", "env --chdir=/tmp git checkout night",
                                     "bash -c 'cd - ; git stash pop'", "cd $X && git reset --hard"])
def test_a_directory_the_parser_cannot_read_fails_closed_for_head_movers(repo, command):
    r = _isolated(repo, command)
    assert r.returncode == 2 and "AMBIGUOUS-CWD" in r.stderr, (command, r.stderr)


@pytest.mark.parametrize("command", ["git con\\fig core.hooks\\Path /x",
                                     "(export X=1); git config 'includeIf.gitdir:/a b/.path' x.cfg"])
def test_a_keystone_config_write_is_read_past_escapes_and_quotes(repo, command):
    r = _isolated(repo, command)
    assert r.returncode == 2 and "KEYSTONE CONFIG BLOCK" in r.stderr, (command, r.stderr)


@pytest.mark.parametrize("command", ["git grep -c core.hooksPath= .", "git -ccore.hookspath=/x status"])
def test_a_config_word_that_is_no_config_override_passes(repo, command):
    """`-c` after the subcommand is the subcommand's flag; git refuses a glued `-c` and runs nothing."""
    assert "CONFIG FIREWALL" not in _isolated(repo, command).stderr


@pytest.mark.parametrize("command", ['echo "$(case x in x) rm b;; esac)"', "git log --format %(refname)", "then git status"])
def test_a_command_the_parser_cannot_read_fails_closed(repo, command):
    r = _isolated(repo, command)
    assert r.returncode == 2 and "UNREADABLE COMMAND" in r.stderr, (command, r.stderr)


def test_a_commit_message_naming_a_git_command_is_a_message(repo):
    assert _isolated(repo, 'git commit -q --allow-empty -m "run git checkout master later"').returncode == 0


@pytest.mark.parametrize("command", ['echo "git checkout master"', ". /dev/stdin <<< 'git checkout master'",
                                     "xargs -i git checkout master"])
def test_git_named_to_a_command_that_is_not_git_is_read(repo, command):
    r = _isolated(repo, command)
    assert r.returncode == 2 and ("BRANCH-SWITCH BLOCK" in r.stderr or "AMBIGUOUS-CWD" in r.stderr), (
        command, r.stderr)


# ---- the rules other hooks own -------------------------------------------------------------------

@WHO
@pytest.mark.parametrize("command", ["echo x > .claude/hooks/x.py", "cp a .claude/commands/x.md",
                                     "cp .claude/hooks/x.py /tmp/b.py", "bash -c 'echo x > .claude/hooks/y.py'"])
def test_a_bash_write_to_hooks_or_commands_is_the_config_guard_s(repo, command, agent):
    main, wt = repo
    assert "HOOK PROTECTION" not in _run(HOOK, main, command, main, "s-other", True, agent).stderr
    r = _run(CONFIG_GUARD, main, command, main, "s-other", True, agent)
    assert r.returncode == 2 and "claude config guard" in r.stderr, (command, r.stderr)
