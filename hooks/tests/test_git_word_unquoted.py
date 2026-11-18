"""OB-L26 (GIT-5): the git command word, its subcommand and its options are read
as git receives them, quotes and backslashes removed, before any rule judges them.

The shell removes quotes before it runs a word, so `\\git push`, `g'i't push`,
`git 'push'`, `git p\\ush` and `git $'\\x70ush'` all run `git push`, and
`git reset '--hard'` runs a hard reset. Operands (`'a b c'`) stay as written.
Before this lane:
  - a quoted or escaped command word (`\\git`, `g'i't`, `$'git'`) was the residual
    obfuscated_git_token, so `\\git status` was refused as an unknown binary and
    `\\git push --force` reached no push rule at all (a residual override, once
    issued, let it through unjudged);
  - a quoted option kept its quotes in the invocation's args, so the guard's
    `'--hard' in args` and branch-flag checks missed `git reset '--hard'` and
    `git branch '-D' master`, which passed every PreToolUse hook.

Each case runs the real privilege guard as a subprocess, for a main-agent and a
subagent payload, in a scratch HOME, state dir and repository, and checks the
rule that refuses it, not only the exit code.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hooks" / "lib"))

from git_command_classifier import classify_git_command  # noqa: E402

GUARD = ROOT / "hooks" / "pretool-git-privilege-guard.py"

PUSH = "BLOCKED: agent git push"
FORCE_PUSH = "BLOCKED: agent git push - force/delete/ref-rewrite push is forbidden."
RESET = "BLOCKED: agent git reset --hard"
REF = "BLOCKED: agent direct git ref mutation"
COMMIT = "BLOCKED: agent git commit"
MERGE = "BLOCKED: agent git merge"
UNCLASSIFIED = "could not be statically classified"

# (command, subcommand the classifier reads, the guard's refusal line)
MUST_REFUSE = [
    ("\\git push origin master", "push", PUSH),
    ("\\git 'push'", "push", PUSH),
    ("git 'push' --force origin master", "push", FORCE_PUSH),
    ("git p\\ush origin master", "push", PUSH),
    ('git "pu"sh origin master', "push", PUSH),
    ("git 'reset' --hard HEAD~1", "reset", RESET),
    ("git 'branch' -D master", "branch", REF),
    ("git 'commit' -am x", "commit", COMMIT),
    ("git 'merge' feature", "merge", MERGE),
    # the git word spelled other ways
    ('"git" push origin master', "push", PUSH),
    ("g'i't push origin master", "push", PUSH),
    ("$'git' $'push' origin master", "push", PUSH),
    ("git $'\\x70ush' origin master", "push", PUSH),
    ('"git" reset --hard HEAD~1', "reset", RESET),
    ("g'i't branch -D master", "branch", REF),
    ("$'git' $'commit' -am x", "commit", COMMIT),
    ("\\git merge feature", "merge", MERGE),
    ("g\\it push --force", "push", FORCE_PUSH),
    ("$'git' push --force", "push", FORCE_PUSH),
    # global options before a quoted subcommand
    ("git -C . 'push' origin master", "push", PUSH),
    ("git -c a=b 'commit' -m x", "commit", COMMIT),
    ("\\git -C . 'reset' --hard", "reset", RESET),
    # quoted options a decision depends on
    ("git push '--force' origin master", "push", FORCE_PUSH),
    ("git push --force-with-lease origin master", "push", FORCE_PUSH),
    ("git push '--force-with-lease' origin master", "push", FORCE_PUSH),
    ("git reset '--hard'", "reset", RESET),
    ("git reset '--har'", "reset", RESET),
    ("git reset \"--hard\" HEAD~1", "reset", RESET),
    ("git branch '-D' master", "branch", REF),
    ("git branch \"--delete\" master", "branch", REF),
]

MUST_PASS = [
    ("\\git status", "status"),
    ("git 'log' --oneline", "log"),
    ('git "status"', "status"),
    ("g'i't diff --stat", "diff"),
]


def test_must_refuse_cases_are_distinct():
    commands = [c for c, _s, _m in MUST_REFUSE]
    assert len(commands) == len(set(commands))


@pytest.mark.parametrize("command,subcommand,_line", MUST_REFUSE)
def test_the_classifier_reads_the_unquoted_subcommand(command, subcommand, _line):
    invocations, residuals = classify_git_command(command)
    assert residuals == []
    assert [inv.subcommand for inv in invocations] == [subcommand]
    options = [a for a in invocations[0].args if a.lstrip("'\"\\").startswith("-")]
    assert not any(q in a for a in options for q in "'\"\\")


@pytest.mark.parametrize("command,subcommand", MUST_PASS)
def test_a_respelled_read_only_command_is_classified_not_residual(command, subcommand):
    invocations, residuals = classify_git_command(command)
    assert residuals == []
    assert [inv.subcommand for inv in invocations] == [subcommand]


@pytest.mark.parametrize("command", [
    "$GIT push", "${G}it commit", "$(which git) push", "`which git` push",
])
def test_a_run_time_command_word_is_still_a_residual(command):
    assert classify_git_command(command)[1]


def test_a_run_time_argument_stays_as_written():
    (inv,), _res = classify_git_command('git commit -m "$msg"')
    assert inv.args == ["-m", '"$msg"']


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("git-word-unquoted")
    home, state, repo = tmp / "home", tmp / "state", tmp / "proj"
    for d in (home, state, repo):
        d.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_", "PYTHON"))}
    env.update(HOME=str(home), CLAUDE_HOME=str(ROOT), CLAUDE_STATE_DIR=str(state),
               CLAUDE_PROJECT_DIR=str(repo), PYTHONDONTWRITEBYTECODE="1",
               GIT_CEILING_DIRECTORIES=str(tmp), GIT_CONFIG_NOSYSTEM="1")
    subprocess.run(["git", "init", "-q", "-b", "master", str(repo)], check=True, env=env)
    return {"env": env, "repo": repo}


def _run(sandbox, hook, command, who):
    payload = {"session_id": "git-word-unquoted-0001", "tool_name": "Bash",
               "tool_input": {"command": command}, "cwd": str(sandbox["repo"]),
               "hook_event_name": "PreToolUse", "transcript_path": "",
               "permission_mode": "default"}
    if who == "subagent":
        payload.update(agent_id="agent-l26", agent_type="general-purpose")
    argv = ["bash", str(hook)] if hook.suffix == ".sh" else [sys.executable, "-B", str(hook)]
    return subprocess.run(argv, input=json.dumps(payload), text=True, capture_output=True,
                          cwd=str(sandbox["repo"]), env=sandbox["env"], timeout=120)


@pytest.mark.parametrize("who", ["main", "subagent"])
@pytest.mark.parametrize("command,_sub,line", MUST_REFUSE)
def test_the_guard_refuses_by_the_rule_for_the_unquoted_command(sandbox, command, _sub, line, who):
    proc = _run(sandbox, GUARD, command, who)
    assert proc.returncode == 2, (command, proc.stderr)
    assert line in proc.stderr, (command, proc.stderr)
    assert UNCLASSIFIED not in proc.stderr, (command, proc.stderr)


@pytest.mark.parametrize("who", ["main", "subagent"])
@pytest.mark.parametrize("command,_sub", MUST_PASS)
def test_the_guard_passes_a_respelled_read_only_command(sandbox, command, _sub, who):
    proc = _run(sandbox, GUARD, command, who)
    assert proc.returncode == 0, (command, proc.stderr)


@pytest.mark.parametrize("command", [
    "git reset '--hard'", "git 'reset' --hard HEAD~1", "\\git reset --hard", "git reset '--har'",
])
def test_the_guard_reads_the_unquoted_reset_option(sandbox, command):
    # The hard reset has one refusal, the privilege guard's (ledger H-031): pretool-bash-safety.sh's own
    # reset rule (BS-40) was merged into it, and hooks/tests/test_bash_safety_rules.py pins that hand-over.
    proc = _run(sandbox, GUARD, command, "subagent")
    assert proc.returncode == 2, (command, proc.stderr)
    assert "BLOCKED: agent git reset --hard - hard reset is forbidden from agent flow" in proc.stderr, proc.stderr
    assert UNCLASSIFIED not in proc.stderr, (command, proc.stderr)


@pytest.mark.parametrize("command,kept", [
    ("git reset '--hard'", ("reset", ["--hard"])),
    ("git 'reset' --hard HEAD~1", ("reset", ["--hard", "HEAD~1"])),
    ("g'i't 'push' '--force'", ("push", ["--force"])),
    ("git -C '.' 'push' -f", ("push", ["-f"])),
])
def test_the_context_view_keeps_a_git_commands_own_words(command, kept):
    # pretool-bash-safety.sh's git rules read lib/shell_parse.py's git_invocations (the view
    # lib/bash_context_strip.py gave them before it was deleted); reading `'--hard'` as data hid the reset.
    from shell_parse import git_invocations, parse
    assert [(g.subcommand, list(g.args)) for g in git_invocations(parse(command))] == [kept]


@pytest.mark.parametrize("command,stripped", [
    ("git commit -m 'rm -rf / and git push'", ["commit"]),
    ("git log --grep='x y' --oneline", ["log"]),
    ("echo 'git push --force'", []),
])
def test_the_context_view_still_strips_a_git_commands_text(command, stripped):
    # The text a git command or echo carries is no git invocation of its own.
    from shell_parse import git_invocations, parse
    assert [g.subcommand for g in git_invocations(parse(command))] == stripped
