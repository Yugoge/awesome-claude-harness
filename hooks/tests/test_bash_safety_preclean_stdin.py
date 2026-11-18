"""MB-1: a command over the kernel's per-string limit (~128 KiB) reaches every bash-safety check intact.

An exec'd process gets its environment and argv strings through the kernel, which refuses one string over
MAX_ARG_STRLEN (128 KiB) with E2BIG. MB-1a (commit guard) and MB-1b (context stripper) were fixed when the rules
moved in-process and the payload went over stdin; these tests pin that. MB-1c: under /do consent the pre-clean
snapshot guard took the command in CMD_INPUT, so a large harmless /do command failed to exec the guard (rc 126)
and was refused as an unclassifiable clean. The guard now reads the command on stdin.

Refusals stay: a redirected clean, a consented clean whose snapshot fails, and a guard that cannot run (a distinct
deployment-error message, still refusing).

Every call runs through the real hook entry with a scratch HOME, state dir, git config and working repository.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "pretool-bash-safety.sh"
SID = "preclean-stdin-test"
BIG = 138 * 1024  # over MAX_ARG_STRLEN (32 pages = 131072 bytes)


def _heredoc_write(size=BIG, tail=""):
    line = "fixture line with harmless text 0123456789 abcdefghijklmnopqrstuvwxyz\n"
    # Whole lines, so `EOF` is a line of its own. A body cut mid-line puts it on
    # that line: bash then reads the heredoc to the end of the text, tail included.
    body = line * (size // len(line) + 1)
    return "cat > fixture.txt <<'EOF'\n" + body + "EOF\n" + tail


@pytest.fixture
def sandbox(tmp_path):
    home, state, repo, tmp, plain = (tmp_path / n for n in ("home", "state", "repo", "tmp", "plain"))
    for d in (home / ".claude", state, repo, tmp, plain):
        d.mkdir(parents=True)
    (tmp_path / "gitconfig").write_text("[user]\n\tname = sandbox\n\temail = sandbox@example.invalid\n")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home),
           "CLAUDE_CONFIG_DIR": str(home / ".claude"), "CLAUDE_STATE_DIR": str(state),
           "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1", "TMPDIR": str(tmp),
           "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8", "CLAUDE_PYTHON_BIN": sys.executable}
    (repo / "README.md").write_text("toy\n")
    for step in (["init", "-q", "-b", "master"], ["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run(["git", *step], cwd=repo, env=env, check=True, capture_output=True)
    return {"env": env, "repo": str(repo), "plain": str(plain), "state": state, "tmp": tmp_path}


def _consent(sandbox):
    (sandbox["state"] / ("claude-orchestrator-consent-%s.flag" % SID)).write_text("true")


def run(sandbox, command, cwd=None, env=None):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": SID,
               "cwd": cwd or sandbox["repo"], "hook_event_name": "PreToolUse"}
    return subprocess.run(["bash", str(HOOK)], input=json.dumps(payload), capture_output=True, text=True,
                          env=env or sandbox["env"], cwd=cwd or sandbox["repo"], timeout=120)


# ── MB-1c: the /do pre-clean guard reads the command on stdin ────────────────

def test_do_large_heredoc_fixture_without_clean_passes(sandbox):
    _consent(sandbox)
    command = _heredoc_write()
    assert len(command.encode()) > 131072
    proc = run(sandbox, command)
    assert proc.returncode == 0, proc.stderr[-2000:]


def test_do_large_heredoc_then_clean_is_still_snapshotted(sandbox):
    """Size does not hide a clean from the guard: a large consented clean in this repo is snapshotted first."""
    _consent(sandbox)
    Path(sandbox["repo"], "wip.txt").write_text("untracked work\n")
    proc = run(sandbox, _heredoc_write(tail="git clean -fd\n"))
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "[pre-clean-snapshot]" in proc.stderr


def test_do_large_heredoc_then_redirected_clean_refused(sandbox):
    _consent(sandbox)
    proc = run(sandbox, _heredoc_write(tail="git -C /x clean -fd\n"))
    assert proc.returncode == 2
    assert "no protective pre-clean WIP snapshot is possible" in proc.stderr


def test_do_redirected_clean_refused(sandbox):
    _consent(sandbox)
    proc = run(sandbox, "git -C /x clean -fd")
    assert proc.returncode == 2
    assert "no protective pre-clean WIP snapshot is possible" in proc.stderr


def test_do_clean_whose_snapshot_fails_refused(sandbox):
    """A consented clean outside a git repository cannot be snapshotted, so it is refused."""
    _consent(sandbox)
    proc = run(sandbox, "git clean -fd", cwd=sandbox["plain"])
    assert proc.returncode == 2
    assert "pre-clean WIP snapshot FAILED" in proc.stderr


def test_ambient_cmd_input_does_not_replace_the_command(sandbox):
    """An inherited CMD_INPUT must not stand in for the real command the guard classifies."""
    _consent(sandbox)
    env = {**sandbox["env"], "CMD_INPUT": "echo harmless"}
    proc = run(sandbox, "git -C /x clean -fd", env=env)
    assert proc.returncode == 2
    assert "no protective pre-clean WIP snapshot is possible" in proc.stderr


@pytest.mark.parametrize("rc", [126, 127])
def test_guard_that_cannot_run_gives_deployment_error(sandbox, rc):
    """An interpreter that cannot run the guard (rc 126/127) is a deployment error, still refused."""
    _consent(sandbox)
    shim = sandbox["tmp"] / "python-shim"
    shim.write_text('#!/bin/bash\ncase "$1" in *git_clean_guard.py) exit %d ;; esac\nexec %s "$@"\n'
                    % (rc, sys.executable))
    shim.chmod(0o755)
    env = {**sandbox["env"], "CLAUDE_PYTHON_BIN": str(shim)}
    proc = run(sandbox, "echo harmless", env=env)
    assert proc.returncode == 2
    assert "pre-clean guard could not run" in proc.stderr
    assert "rc=%d" % rc in proc.stderr
    assert "no protective pre-clean WIP snapshot is possible" not in proc.stderr




# ── MB-1a / MB-1b pins: the in-process rules see a large payload whole, with no /do ──
# A large heredoc without /do is not pinned here: the removal-policy analyzer still takes the command in CMD_INPUT
# and fails closed on it, which another lane owns. A single-quoted argument of the same size reaches the same rules.

def _big_quoted(prefix=""):
    return "echo '" + prefix + "abc " * (BIG // 4) + "'"


def test_large_plain_command_without_consent_passes(sandbox):
    proc = run(sandbox, _big_quoted())
    assert proc.returncode == 0, proc.stderr[-2000:]


def test_large_command_commit_guard_still_reads_the_whole_payload(sandbox):
    """MB-1a: the commit guard once failed to exec on a payload this size and refused as FAIL-CLOSED."""
    proc = run(sandbox, _big_quoted() + "; git commit --no-verify -m x")
    assert proc.returncode == 2
    assert "commit-hook-bypass" in proc.stderr
    assert "commit-guard FAIL-CLOSED" not in proc.stderr


def test_large_quoted_clean_is_stripped_as_data(sandbox):
    """MB-1b: the stripper once failed to exec on a payload this size, so quoted text read as a command."""
    proc = run(sandbox, _big_quoted("git clean -fd "))
    assert proc.returncode == 0, proc.stderr[-2000:]


def test_large_command_then_real_clean_refused_without_consent(sandbox):
    """Size never fails open: a real clean after a large argument is refused without a grant."""
    proc = run(sandbox, _big_quoted() + "; git clean -fd")
    assert proc.returncode == 2
