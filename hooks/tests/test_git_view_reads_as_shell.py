"""The git classifier reads a command's words as the shell does.

Each case is a decision that changed when the classifier moved from a
quote-blind split onto the shared shell lexer, pinned at its new value:

  - O5: a commit message stays text when `-c`/`--config-env` precedes `commit`;
  - a quoted word is one word (`-C "my dir"`, `-m 'a b c'`), and a quote ending a
    `-c` string is not part of its last word (`--hard`, not `--hard"`);
  - a quoted or escaped subcommand is the subcommand git runs (`git "clean"`);
  - a quoted assignment value does not hide the command after it
    (`GIT_EXTERNAL_DIFF='/bin/rm -rf x' git diff`);
  - `$'git'` and a backtick command word are residuals, as `g\\it` and `$(...)` are;
  - an ANSI-C `-c` string is read, not left unresolved;
  - a `-c alias.<name>=` value is read as what the alias runs;
  - an abbreviated long option reads as its full name (`--har` is `--hard`);
  - the command word is found past every wrapper in the parser's one table
    (`env -C <dir>`, `strace -f`, `chrt -b 0`), and a run-time command word a
    wrapper runs inside a `-c` string is a residual (`timeout 5 $X`).

The guard runs as a subprocess with a scratch HOME, state dir and repository.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
GUARD = HOOKS / "pretool-git-privilege-guard.py"
sys.path.insert(0, str(HOOKS))

from lib.git_command_classifier import classify_git_command  # noqa: E402


def subcommands(command):
    invocations, _residuals = classify_git_command(command)
    return [inv.subcommand for inv in invocations]


def residual_kinds(command):
    return [kind for kind, _text in classify_git_command(command)[1]]


@pytest.mark.parametrize("command", [
    'git -c a=b commit -m "x; git push origin"',
    'git --config-env=a=B commit -m "x; git push origin"',
    'git -c core.editor=vi commit -m "a; git push origin main"',
])
def test_a_commit_message_stays_text_after_a_config_option(command):
    assert subcommands(command) == ["commit"]


@pytest.mark.parametrize("command,subcommand,args", [
    ('git -C "my dir" push --force', "push", ["--force"]),
    ('python3 -c "x; git reset --hard"', "reset", ["--hard"]),
    ("git commit -m 'a b c'", "commit", ["-m", "'a b c'"]),
    ('git "clean" -fd', "clean", ["-fd"]),
    ("git cl''ean -fd", "clean", ["-fd"]),
    ("GIT_EXTERNAL_DIFF='/bin/rm -rf /tmp/qa-t' git diff", "diff", []),
    ("bash -c $'git commit -m y'", "commit", ["-m", "y"]),
])
def test_words_are_read_as_the_shell_reads_them(command, subcommand, args):
    (inv,) = classify_git_command(command)[0]
    assert (inv.subcommand, inv.args) == (subcommand, args)
    assert residual_kinds(command) == []


@pytest.mark.parametrize("command,subcommand,args", [
    ("git reset --har", "reset", ["--hard"]),
    ("git branch --del x", "branch", ["--delete", "x"]),
    ("git push --forc origin main", "push", ["--force", "origin", "main"]),
    ("env -C /tmp/B git clean -fd", "clean", ["-fd"]),
    ("strace -f git push", "push", []),
    ("chrt -b 0 git clean -fd", "clean", ["-fd"]),
])
def test_options_and_wrappers_read_from_the_parsers_tables(command, subcommand, args):
    (inv,) = classify_git_command(command)[0]
    assert (inv.subcommand, inv.args) == (subcommand, args)


@pytest.mark.parametrize("command", [
    'bash -c "timeout 5 $X"', 'bash -c "sudo $X arg"', 'bash -c "chroot /jail $X arg"',
])
def test_a_wrapper_running_a_run_time_word_in_a_layer_is_a_residual(command):
    assert "unresolved_shell_string" in residual_kinds(command)


@pytest.mark.parametrize("command,kind", [
    ("$'git' push --force", "obfuscated_git_token"),
    ("`which git` push", "substituted_git_token"),
    ("$(which git) -C x push", "substituted_git_token"),
])
def test_a_command_word_the_scan_cannot_resolve_is_a_residual(command, kind):
    assert classify_git_command(command) == ([], [(kind, command)])


@pytest.mark.parametrize("command,expected", [
    ('git -c "alias.ci=!git commit" ci -m x', ["ci", "commit"]),
    ("git -c 'alias.x=!git config core.hooksPath .githooks' x", ["x", "config"]),
    ('git -c alias.ci=commit -c "alias.p=!git ci -n" p -m x', ["p", "ci", "commit"]),
    ("git --config-env=alias.ci=CI_VALUE ci", ["ci"]),
])
def test_an_alias_defined_on_the_command_line_is_read(command, expected):
    assert subcommands(command) == expected


@pytest.fixture(scope="module")
def guard_env(tmp_path_factory):
    base = tmp_path_factory.mktemp("git-view")
    repo = base / "repo"
    for path in (repo, base / "home", base / "state"):
        path.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_"))}
    env.update(HOME=str(base / "home"), CLAUDE_STATE_DIR=str(base / "state"),
               CLAUDE_PROJECT_DIR=str(repo), PYTHONDONTWRITEBYTECODE="1",
               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, env=env, check=True)
    return repo, env


def run_guard(command, guard_env):
    repo, env = guard_env
    payload = {"session_id": "git-view-0001", "cwd": str(repo), "transcript_path": "",
               "hook_event_name": "PreToolUse", "permission_mode": "default",
               "tool_name": "Bash", "tool_input": {"command": command}}
    return subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload),
                          capture_output=True, text=True, cwd=repo, env=env, timeout=120)


def test_o5_the_guard_refuses_the_commit_not_a_push_in_its_message(guard_env):
    proc = run_guard('git -c a=b commit -m "x; git push origin"', guard_env)
    assert proc.returncode == 2 and "agent git commit" in proc.stderr, proc.stderr
    assert "agent git push" not in proc.stderr, proc.stderr


@pytest.mark.parametrize("command,reason", [
    ('git -C "my dir" push --force', "agent git push"),
    ('git -c "alias.ci=!git commit" ci -m x', "agent git commit"),
])
def test_the_guard_refuses_what_the_shell_would_run(command, reason, guard_env):
    proc = run_guard(command, guard_env)
    assert proc.returncode == 2 and reason in proc.stderr, proc.stderr
