"""The privilege guard reads a commit's target and message from the commit itself.

An auto-bulk commit is one whose own message carries the `auto-bulk:` subject: an
`-m` given to another command of the same call (`echo -m "auto-bulk: ..."`) makes
no commit an auto-bulk one, and every commit in the call must carry the subject.
A commit the grant path cannot locate (one inside `bash -c`) stays refused.

The guard runs as a subprocess with a scratch HOME, state dir and repository; the
bulk-commit sentinel is written as /commit --bulk's capability hook writes it.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
GUARD = HOOKS / "pretool-git-privilege-guard.py"
SID = "one-reader-session-0001"
IDENTITY = ("-c", "user.name=sandbox", "-c", "user.email=sandbox@example.invalid")
BRIDGE = "auto-bulk: end-of-cycle commit for feat"


class Box:
    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.state = tmp_path / "state"
        self.repo = tmp_path / "toyproj"
        home = tmp_path / "home"
        for d in (self.state, self.repo, home):
            d.mkdir()
        (home / "gitconfig").write_text("")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_"))}
        self.env.update(HOME=str(home), CLAUDE_STATE_DIR=str(self.state),
                        CLAUDE_PROJECT_DIR=str(self.repo), PYTHONDONTWRITEBYTECODE="1",
                        GIT_CONFIG_GLOBAL=str(home / "gitconfig"), GIT_CONFIG_NOSYSTEM="1",
                        GIT_CEILING_DIRECTORIES=str(tmp_path))
        subprocess.run(["git", "-C", str(self.repo), "init", "-q", "-b", "master"], check=True,
                       env=self.env)
        subprocess.run(["git", "-C", str(self.repo), *IDENTITY, "commit", "-q", "--allow-empty",
                        "-m", "init"], check=True, env=self.env)

    def sentinel(self) -> Path:
        now = datetime.now(timezone.utc)
        path = self.state / f"claude-bulk-commit-sentinel-{SID}-00aa.json"
        path.write_text(json.dumps({
            "kind": "bulk-commit", "sid": SID, "nonce": "00aa", "origin": "userpromptsubmit-hook",
            "created_at": now.isoformat(), "expires_at": (now + timedelta(minutes=30)).isoformat()}))
        return path

    def commit_grant(self) -> Path:
        """A live grant bound to another HEAD: no commit spends it, and the guard's
        binding check on it names why the commit cannot be checked."""
        now = datetime.now(timezone.utc)
        path = self.state / f"claude-commit-grant-{SID}-00bb.json"
        path.write_text(json.dumps({
            "repo_root": str(self.repo), "branch": "master", "sid": SID,
            "expected_head": "0" * 40,
            "created_at": now.isoformat(), "expires_at": (now + timedelta(minutes=30)).isoformat()}))
        return path

    def run(self, command: str):
        data = {"session_id": SID, "agent_id": "agent-1", "tool_name": "Bash",
                "tool_input": {"command": command}, "cwd": str(self.repo),
                "hook_event_name": "PreToolUse"}
        return subprocess.run([sys.executable, "-B", str(GUARD)], input=json.dumps(data),
                              text=True, capture_output=True, cwd=str(self.repo), env=self.env,
                              timeout=120)


@pytest.fixture
def box(tmp_path):
    return Box(tmp_path)


@pytest.mark.parametrize("command", [
    f'git commit -m "{BRIDGE}"',
    f"git commit -m '{BRIDGE}' -m 'second paragraph'",
    f'git commit --message="{BRIDGE}"',
    f'if ! git commit -m "{BRIDGE}"; then echo failed; fi',
])
def test_an_auto_bulk_commit_passes_on_a_live_sentinel(box, command):
    box.sentinel()
    proc = box.run(command)
    assert proc.returncode == 0, (command, proc.stderr)


def test_an_auto_bulk_message_file_passes_on_a_live_sentinel(box):
    msg = box.tmp / "commit-msg-bulk.txt"
    msg.write_text(f"{BRIDGE}\n\nTask-id: bulk\n")
    box.sentinel()
    assert box.run(f'git -C "{box.repo}" commit -F "{msg}"').returncode == 0


@pytest.mark.parametrize("command", [
    # The subject is on another command's -m, not on the commit's.
    f'echo -m "{BRIDGE}"; git commit -m "evil"',
    f'printf %s --message="{BRIDGE}" && git commit -m evil',
    # One auto-bulk commit does not carry a second one.
    f'git commit -m "{BRIDGE}"; git commit -m "evil"',
    # The first -m is the subject.
    f'git commit -m evil -m "{BRIDGE}"',
])
def test_only_the_commits_own_subject_makes_it_auto_bulk(box, command):
    box.sentinel()
    proc = box.run(command)
    assert proc.returncode == 2, (command, proc.stderr)
    assert "BLOCKED: agent git commit" in proc.stderr, (command, proc.stderr)


def test_an_auto_bulk_subject_without_a_sentinel_is_refused(box):
    proc = box.run(f'git commit -m "{BRIDGE}"')
    assert proc.returncode == 2
    assert "auto-bulk commit requires a bulk-commit sentinel" in proc.stderr


@pytest.mark.parametrize("command", [
    'bash -c "git commit -F msg"',
    "sh -c 'git -C /elsewhere commit -m x'",
])
def test_a_commit_the_grant_path_cannot_locate_stays_refused(box, command):
    box.commit_grant()
    proc = box.run(command)
    assert proc.returncode == 2, (command, proc.stderr)
    assert "effective target repository could not be resolved" in proc.stderr, proc.stderr


@pytest.mark.parametrize("command,why", [
    ("git commit -m one ; git commit -m two", "2 commit invocations in ONE command"),
    ("cd sub && git commit -m x", "cd/pushd cwd-change before commit"),
    ("GIT_DIR=/x git commit -m x", "inline-env GIT_DIR/GIT_WORK_TREE"),
    ("git --git-dir /x commit -m x", "--git-dir/--work-tree/--namespace flag"),
    ("git --work-tree=/x commit -m x", "--git-dir/--work-tree/--namespace flag"),
    ("git -C a -C b commit -m x", "multiple -C directory overrides"),
    ('git -C "${GIT_ROOT}" commit -m x', "unresolved shell variable reference"),
])
def test_a_commit_under_a_grant_is_refused_where_the_grant_cannot_be_checked(box, command, why):
    box.commit_grant()
    proc = box.run(command)
    assert proc.returncode == 2, (command, proc.stderr)
    assert why in proc.stderr, (command, proc.stderr)


def _guard():
    if str(HOOKS) not in sys.path:
        sys.path.insert(0, str(HOOKS))
    spec = importlib.util.spec_from_file_location("privilege_guard_one_reader", GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_commit_word_in_a_message_is_not_a_commit():
    guard = _guard()
    assert len(guard._commit_records('git commit -m "please git commit later; git commit"')) == 1
    assert len(guard._commit_records("git -C /a commit -m a ; git -C /b commit -m b")) == 2
    (rec,) = guard._commit_records('/usr/bin/git --attr-source HEAD -C "/o p" commit -m x')
    assert rec["dirs"] == ["/o p"] and rec["args"] == ["-m", "x"]
