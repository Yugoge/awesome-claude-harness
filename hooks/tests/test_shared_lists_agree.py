#!/usr/bin/env python3
"""Lists two rules kept apart now have one definition (hardcode audit 2026-11-19, findings 15, 20, 21).

- Finding 15, devices no write changes: the overnight boundary knew /dev/null, tool-policy's rows
  /dev/null, /dev/stderr, /dev/stdout, so `echo warn > /dev/stderr` was refused by one and passed by
  the other, and `> /dev/tty` or `> /dev/fd/2` the other way round. Both read
  lib/shell_parse.is_sink_device.
- Finding 20, the names of standard input: the session_dirs.txt mention rule took `git commit -F -`
  and `-F /dev/stdin` for a message from stdin, not `-F /dev/fd/0` or `-F /proc/self/fd/0`. It reads
  lib/shell_parse._STDIN_FILES.
- Finding 21, the directories a plain program is written with: /usr/local/bin/rg was a plain program
  for the mention rule and not for the bulk sentinel's strict shape. The three patterns of
  lib/bash_safety_rules read its one list, _SD_HEAD_DIRS.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / "hooks"
sys.path.insert(0, str(HOOKS))
from lib import bash_safety_rules as rules, shell_parse as sp  # noqa: E402
from lib.runtime_guard.config import REQUIRED_KEYS  # noqa: E402

SINKS = ["/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty", "/dev/fd/1", "/dev/fd/2", "/dev/fd/9"]
NOT_SINKS = ["/dev/sda", "/dev/shm/planted", "/dev/fd/", "/dev/fd/x", "/dev/ttyS0", "/dev/stdin", "/dev/nullx", "dev/null"]
GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid"}


# ---------------------------------------------------------------------------------- finding 15

def test_the_one_definition_of_a_device_no_write_changes():
    assert all(sp.is_sink_device(p) for p in SINKS)
    assert not any(sp.is_sink_device(p) for p in NOT_SINKS)


@pytest.fixture(scope="module")
def overnight(tmp_path_factory):
    """A checkout, a linked worktree and a live overnight record binding session S to the worktree, on a
    host where bubblewrap is not available: the guard's own path check decides (with bubblewrap the
    command is rewritten into the sandbox instead)."""
    tmp = tmp_path_factory.mktemp("sink-overnight")
    main, wt = tmp / "toy", tmp / "wt"
    main.mkdir()
    for args in (["init", "-q", "-b", "master"], ["commit", "-q", "--allow-empty", "-m", "init"],
                 ["worktree", "add", "-q", "-b", "night-work", str(wt)]):
        subprocess.run(["git", *args], cwd=main, env={**os.environ, **GIT_ENV}, check=True, capture_output=True)
    (main / ".claude").mkdir()
    (main / ".claude" / "overnight-state-S.json").write_text(json.dumps({
        "schema_version": 9, "session_id": "S", "isolation_kind": "registered_worktree", "main_root": str(main),
        "main_git_dir": str(main / ".git"), "worktree_path": str(wt), "worktree_branch": "night-work",
        "protected_branch": "master", "end_time": "2099-01-01T00:00:00Z",
        "isolation_active_until": "2099-01-01T00:00:00Z", "current_cycle": 1}))

    def run(command):
        payload = {"session_id": "S", "tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(wt),
                   "transcript_path": str(main / "t.jsonl")}
        env = {**os.environ, **GIT_ENV, "CLAUDE_PROJECT_DIR": str(main), "PWD": str(wt),
               "CLAUDE_OVERNIGHT_FORCE_NO_BWRAP": "1"}
        return subprocess.run([sys.executable, str(HOOKS / "pretool-overnight-hook-guard.py")],
                              input=json.dumps(payload), capture_output=True, text=True, env=env, cwd=wt, timeout=120)
    run.main = main
    return run


def _policy(tmp_path, command, role="qa"):
    proj = tmp_path / "proj"
    (proj / "src").mkdir(parents=True, exist_ok=True)
    payload = {"session_id": "s", "cwd": str(proj), "hook_event_name": "PreToolUse", "agent_id": "a1",
               "agent_type": role, "subagent_type": role, "tool_name": "Bash", "tool_input": {"command": command}}
    return subprocess.run([sys.executable, str(HOOKS / "pretool-tool-policy.py")], input=json.dumps(payload),
                          capture_output=True, text=True, cwd=str(proj),
                          env=dict(os.environ, CLAUDE_PROJECT_DIR=str(proj)), timeout=120)


@pytest.mark.parametrize("device", SINKS)
def test_a_redirect_to_such_a_device_gets_one_answer_from_both_guards(overnight, tmp_path, device):
    command = "echo warn > " + device
    boundary, rows = overnight(command), _policy(tmp_path, command)
    assert (boundary.returncode, rows.returncode) == (0, 0), (boundary.stderr, rows.stderr)


@pytest.mark.parametrize("role", ["dev", "qa"])
@pytest.mark.parametrize("command", ["echo warn > /dev/stderr", "ls 2>/dev/stderr", "echo x | tee /dev/stdout",
                                     "echo warn > /dev/fd/2"])
def test_a_redirect_to_a_standard_stream_passes_the_registered_gate(tmp_path, role, command):
    """Through the gate a rule's own stderr is a file under the temp root, and /dev/stderr was read
    through it: the raw-temp rule refused the redirect for every role, dev's `*` row included."""
    payload = {"session_id": "s", "cwd": "/nonexistent-shared-lists/proj", "hook_event_name": "PreToolUse",
               "agent_id": "a1", "agent_type": role, "subagent_type": role, "tool_name": "Bash",
               "tool_input": {"command": command}}
    proc = subprocess.run([sys.executable, str(HOOKS / "pretool-write-gate.py")], input=json.dumps(payload),
                          capture_output=True, text=True, cwd=str(tmp_path), timeout=300,
                          env=dict(os.environ, CLAUDE_PROJECT_DIR="/nonexistent-shared-lists/proj"))
    assert proc.returncode == 0 and "BLOCKED" not in proc.stderr, proc.stderr


def test_a_write_tool_aimed_at_the_terminal_meets_no_role_row(tmp_path):
    payload = {"session_id": "s", "cwd": str(tmp_path), "hook_event_name": "PreToolUse", "agent_id": "a1",
               "agent_type": "qa", "subagent_type": "qa", "tool_name": "Write",
               "tool_input": {"file_path": "/dev/tty", "content": "x"}}
    proc = subprocess.run([sys.executable, str(HOOKS / "pretool-tool-policy.py")], input=json.dumps(payload),
                          capture_output=True, text=True, cwd=str(tmp_path), timeout=120,
                          env=dict(os.environ, CLAUDE_PROJECT_DIR=str(tmp_path)))
    assert proc.returncode == 0, proc.stderr


def test_a_file_and_a_device_that_holds_data_stay_refused(overnight, tmp_path):
    for target in (str(overnight.main / "planted.txt"), "/dev/shm/planted-by-a-test", "/dev/sda"):
        assert overnight("echo x > " + target).returncode == 2, target
    assert overnight("echo x > notes.txt").returncode == 0  # inside the worktree
    for target in ("src/planted.py", "/dev/shm/planted-by-a-test", "/dev/sda"):
        proc = _policy(tmp_path, "echo x > " + target)
        assert proc.returncode == 2 and "BLOCKED by tool-policy" in proc.stderr, (target, proc.stderr)


# ----------------------------------------------------------------------------- findings 20, 21

@pytest.fixture(scope="module")
def bash_safety(tmp_path_factory):
    """The real bash-safety hook with a scratch HOME, state dir, git config and repository (as
    hooks/tests/test_bash_safety_session_dirs.py builds them). No command is executed."""
    base = tmp_path_factory.mktemp("shared-lists")
    home, state, repo, tmp = base / "home", base / "state", base / "repo", base / "tmp"
    for d in (home / ".claude", state, repo, tmp):
        d.mkdir(parents=True)
    (base / "gitconfig").write_text("[user]\n\tname = sandbox\n\temail = sandbox@example.invalid\n")
    runtime = base / "protected-runtime.json"
    runtime.write_text(json.dumps({"schema_version": 1, **{k: [] for k in REQUIRED_KEYS}}))
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
           "CLAUDE_STATE_DIR": str(state), "GIT_CONFIG_GLOBAL": str(base / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1",
           "TMPDIR": str(tmp), "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8",
           "CLAUDE_PROTECTED_RUNTIME_FILE": str(runtime)}
    (repo / "README.md").write_text("toy\n")
    for step in (["init", "-q", "-b", "master"], ["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run(["git", *step], cwd=repo, env=env, check=True, capture_output=True)

    def run(command):
        payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": "shared-lists",
                   "cwd": str(repo), "hook_event_name": "PreToolUse"}
        return subprocess.run(["bash", str(HOOKS / "pretool-bash-safety.sh")], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, cwd=repo, timeout=300)
    return run


MESSAGE = " <<'EOF'\ndocs: session_dirs.txt\nEOF"


@pytest.mark.parametrize("option", ["-F -", "-F /dev/stdin", "-F /dev/fd/0", "-F /proc/self/fd/0",
                                    "--file=/dev/fd/0", "--file /proc/self/fd/0"])
def test_a_commit_message_from_stdin_is_a_mention_under_each_name_of_stdin(bash_safety, option):
    proc = bash_safety("git commit " + option + MESSAGE)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("command", ["git commit -F session_dirs.txt", "git commit -F /dev/fd/3" + MESSAGE])
def test_a_commit_that_reads_the_file_or_another_descriptor_stays_refused(bash_safety, command):
    proc = bash_safety(command)
    assert proc.returncode == 2 and "session_dirs.txt is never read" in proc.stderr, proc.stderr


def test_one_list_of_the_directories_a_plain_program_is_written_with():
    assert rules._SD_HEAD_DIRS == ("/bin", "/usr/bin", "/usr/local/bin", "/opt/homebrew/bin")
    for d in rules._SD_HEAD_DIRS:
        assert rules._SHAPE_HEAD_RE.fullmatch(d + "/rg") and rules._HB_SHELL_WORD.fullmatch(d + "/bash"), d
    for word in ("./rg", "/tmp/x/rg", "/usr/bin/x/rg", "bin/rg", "/usr/local/bin/"):
        assert not rules._SHAPE_HEAD_RE.fullmatch(word), word
    for word in ("./bash", "/tmp/x/bash", "/usr/local/bin/zsh", "/opt/homebrew/bin/bash2"):
        assert not rules._HB_SHELL_WORD.fullmatch(word), word
    assert rules._SHAPE_HEAD_RE.fullmatch("rg") and rules._HB_SHELL_WORD.fullmatch("sh")


@pytest.mark.parametrize("command", [
    "/usr/bin/grep -rn claude-bulk-commit-sentinel- docs/",       # passed before: the control
    "/usr/local/bin/rg -n claude-bulk-commit-sentinel- docs/",
    "/opt/homebrew/bin/rg -n claude-bulk-commit-sentinel- docs/",
    "/usr/local/bin/rg -n session_dirs.txt docs/",                # the mention rule already took these two
    "/opt/homebrew/bin/rg -n session_dirs.txt docs/",
    "/usr/local/bin/bash -n session-recovery.sh",                 # passed before: the control
    "/opt/homebrew/bin/bash -n session-recovery.sh",
])
def test_a_plain_program_is_one_in_each_rule_that_asks(bash_safety, command):
    proc = bash_safety(command)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("command", [
    "/tmp/x/rg -n claude-bulk-commit-sentinel- docs/",
    "./rg -n claude-bulk-commit-sentinel- docs/",
    "/tmp/x/bash -n session-recovery.sh",
    "/opt/homebrew/bin/bash session-recovery.sh",                 # no -n: it runs the script
])
def test_a_program_from_any_other_directory_stays_refused(bash_safety, command):
    proc = bash_safety(command)
    assert proc.returncode == 2 and "BLOCKED" in proc.stderr, proc.stderr
