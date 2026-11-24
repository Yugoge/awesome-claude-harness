"""Two callers of write_checkpoint when a snapshot leaves a file out (the private-literal rule names it).

The pre-clean guard (hooks/pretool-bash-safety.sh, a granted `git clean`): a snapshot that left a file out is
written for the rest, but the clean would remove the left-out file unrecoverably, so the clean is refused,
naming the files (never a value). A complete snapshot still allows it, and every case the guard decided
before keeps its decision: not a repository, a failed snapshot, a redirected clean are refused.

The manual /checkpoint (hooks/checkpoint.sh): a snapshot that left a file out is written and the command
prints one warning line naming the files; a complete one prints none.

Every run goes through the real script with a scratch HOME, state dir, git config and repository.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GUARD = REPO / "hooks" / "pretool-bash-safety.sh"
MANUAL = REPO / "hooks" / "checkpoint.sh"
SID = "left-out-callers-test"
STANDIN = "acct-test-123"  # stand-in listed literal
REF = "refs/checkpoints/master"
LEFT_OUT = "left out 1 file(s) holding a private literal: leak.txt"


@pytest.fixture
def sandbox(tmp_path):
    home, state, repo, tmp, plain = (tmp_path / n for n in ("home", "state", "repo", "tmp", "plain"))
    for d in (home / ".claude" / "logs", state, repo, tmp, plain):
        d.mkdir(parents=True)
    (tmp_path / "gitconfig").write_text("[user]\n\tname = sandbox\n\temail = sandbox@example.invalid\n")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home),
           "CLAUDE_CONFIG_DIR": str(home / ".claude"), "CLAUDE_STATE_DIR": str(state),
           "CHECKPOINT_LOG_DIR": str(home / ".claude" / "logs"),
           "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1", "TMPDIR": str(tmp),
           "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8", "CLAUDE_PYTHON_BIN": sys.executable,
           "GIT_CEILING_DIRECTORIES": str(tmp_path)}  # `plain` is no repository, whatever holds tmp_path
    (repo / ".gitignore").write_text("/private-literals.txt\n")
    (repo / "README.md").write_text("toy\n")
    for step in (["init", "-q", "-b", "master"], ["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run(["git", *step], cwd=repo, env=env, check=True, capture_output=True)
    (repo / "private-literals.txt").write_text(f"# stand-in list\n{STANDIN}\n")
    (repo / "wip.txt").write_text("untracked work\n")
    (state / ("claude-orchestrator-consent-%s.flag" % SID)).write_text("true")  # the clean is granted
    return {"env": env, "repo": repo, "plain": plain, "home": home}


def _git(sandbox, *args):
    return subprocess.run(["git", "-C", str(sandbox["repo"]), *args], env=sandbox["env"], text=True,
                          capture_output=True).stdout.strip()


def _guard(sandbox, command, cwd=None):
    cwd = str(cwd or sandbox["repo"])
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": SID, "cwd": cwd,
               "hook_event_name": "PreToolUse"}
    return subprocess.run(["bash", str(GUARD)], input=json.dumps(payload), capture_output=True, text=True,
                          env=sandbox["env"], cwd=cwd, timeout=120)


def _leak(sandbox):
    (sandbox["repo"] / "leak.txt").write_text(f"ticket for {STANDIN}\n")


# ── the pre-clean guard ─────────────────────────────────────────────────────

def test_guard_refuses_a_clean_whose_snapshot_left_a_file_out(sandbox):
    _leak(sandbox)
    proc = _guard(sandbox, "git clean -fd")
    assert proc.returncode == 2, proc.stderr
    assert "pre-clean WIP snapshot FAILED" in proc.stderr
    assert f"written, but it {LEFT_OUT}" in proc.stderr
    assert STANDIN not in proc.stdout + proc.stderr
    # the rest is snapshotted all the same; the left-out file is not in the ref
    assert _git(sandbox, "show", f"{REF}:wip.txt") == "untracked work"
    assert "leak.txt" not in _git(sandbox, "ls-tree", "-r", "--name-only", REF).splitlines()


def test_guard_allows_a_clean_whose_snapshot_is_complete(sandbox):
    proc = _guard(sandbox, "git clean -fd")
    assert proc.returncode == 0, proc.stderr
    assert "[pre-clean-snapshot]" in proc.stderr and "BLOCKED" not in proc.stderr
    assert _git(sandbox, "show", f"{REF}:wip.txt") == "untracked work"


@pytest.mark.parametrize("case", ["not-a-repo", "snapshot-fails", "redirected", "no-clean"])
def test_guard_keeps_every_earlier_decision(sandbox, case):
    expect = {"not-a-repo": (2, "write_checkpoint rc=2"),
              "snapshot-fails": (2, "write_checkpoint rc=1"),
              "redirected": (2, "no protective pre-clean WIP snapshot is possible"),
              "no-clean": (0, "")}[case]
    cwd, command = None, "git clean -fd"
    if case == "not-a-repo":
        cwd = sandbox["plain"]
    elif case == "snapshot-fails":
        log = sandbox["home"] / ".claude" / "logs" / "checkpoint.log"
        log.mkdir()  # every `2>>checkpoint.log` redirect fails: read-tree fails, rc 1
    elif case == "redirected":
        command = "git -C /x clean -fd"
    else:
        command = "echo harmless"
    proc = _guard(sandbox, command, cwd)
    assert proc.returncode == expect[0], proc.stderr
    assert expect[1] in proc.stderr


# ── the manual /checkpoint ──────────────────────────────────────────────────

def _manual(sandbox):
    return subprocess.run(["bash", str(MANUAL), "manual save"], capture_output=True, text=True,
                          env=sandbox["env"], cwd=str(sandbox["repo"]), timeout=120)


def test_manual_checkpoint_warns_naming_the_files_it_left_out(sandbox):
    _leak(sandbox)
    proc = _manual(sandbox)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    warnings = [line for line in proc.stdout.splitlines() if line.startswith("⚠️  Checkpoint snapshot")]
    assert len(warnings) == 1, proc.stdout
    assert warnings[0].startswith(f"⚠️  Checkpoint snapshot {LEFT_OUT}, see logs/checkpoint.log; ")
    assert warnings[0].endswith("(1 in a row)")
    assert STANDIN not in proc.stdout + proc.stderr
    assert _git(sandbox, "show", f"{REF}:wip.txt") == "untracked work"


def test_manual_checkpoint_of_a_complete_snapshot_prints_no_warning(sandbox):
    proc = _manual(sandbox)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "⚠️" not in proc.stdout and "Checkpoint created" in proc.stdout
    assert _git(sandbox, "show", f"{REF}:wip.txt") == "untracked work"
