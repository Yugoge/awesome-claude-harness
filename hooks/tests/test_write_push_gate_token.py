"""scripts/write-push-gate-token.py: the push-gate token's one writer.

changelog-analyst (under /commit) and the cleaner (under /clean) both call it after
their own commit. It resolves the token path under harness_state_dir() -- where
hooks/push.sh reads it -- and writes only a token that would authorize /push: the
commit is a commit object and live HEAD (the rule hooks/posttool-push-gate-token-verify.py
applied after the fact), and no other session's token is replaced (DO NOT rule 7).
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WRITER = ROOT / "scripts" / "write-push-gate-token.py"
PUSH_SH = ROOT / "hooks" / "push.sh"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "feat/x")
    git(path, "config", "user.email", "t@example.invalid")
    git(path, "config", "user.name", "test")
    (path / "f.txt").write_text("x\n")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "init")
    return path


def run(state, repo, commit, sid="sid-one", *extra):
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID")}
    env.update(CLAUDE_STATE_DIR=str(state), CLAUDE_CODE_SESSION_ID=sid, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, str(WRITER), "--repo-root", str(repo), "--branch",
                           git(repo, "branch", "--show-current"), "--commit", commit, *extra],
                          capture_output=True, text=True, env=env)


def expected_path(state, repo, sid):
    repo_hash = hashlib.sha256(os.path.realpath(git(repo, "rev-parse", "--show-toplevel")).encode()).hexdigest()[:16]
    return (Path(state) / "agentic-commit" / "push" / repo_hash
            / hashlib.sha256(sid.encode()).hexdigest()[:16] / "feat__x.json")


def test_writes_the_token_where_push_sh_reads_it(tmp_path, repo):
    head = git(repo, "rev-parse", "HEAD")
    proc = run(tmp_path / "state", repo, head)
    assert proc.returncode == 0, proc.stderr
    path = expected_path(tmp_path / "state", repo, "sid-one")
    assert proc.stdout.strip() == str(path)
    assert json.loads(path.read_text()) == {
        "commit_sha": head, "branch": "feat/x",
        "repo_root": git(repo, "rev-parse", "--show-toplevel"), "session_id": "sid-one"}
    # push.sh builds its candidate directory from the same state root and hash.
    assert '$(harness_state_dir)/agentic-commit/push/${_REPO_HASH}' in PUSH_SH.read_text()
    assert [p.name for p in path.parent.iterdir()] == ["feat__x.json"]


def test_a_commit_that_is_not_live_head_is_not_written(tmp_path, repo):
    old = git(repo, "rev-parse", "HEAD")
    (repo / "f.txt").write_text("y\n")
    git(repo, "commit", "-qam", "later")
    proc = run(tmp_path / "state", repo, old)
    assert proc.returncode == 3 and "push_gate_race" in proc.stderr
    assert not (tmp_path / "state" / "agentic-commit").exists()
    proc = run(tmp_path / "state", repo, "0" * 40)
    assert proc.returncode == 3


def test_another_sessions_token_is_never_overwritten(tmp_path, repo):
    head = git(repo, "rev-parse", "HEAD")
    path = expected_path(tmp_path / "state", repo, "sid-one")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"commit_sha": "x", "session_id": "sid-other"}))
    proc = run(tmp_path / "state", repo, head)
    assert proc.returncode == 4 and "push_gate_collision" in proc.stderr
    assert json.loads(path.read_text())["session_id"] == "sid-other"
    path.write_text(json.dumps({"commit_sha": "x", "session_id": "sid-one"}))
    assert run(tmp_path / "state", repo, head).returncode == 0
    assert json.loads(path.read_text())["commit_sha"] == head


def test_print_path_writes_nothing(tmp_path, repo):
    proc = run(tmp_path / "state", repo, "anything", "sid-one", "--print-path")
    assert proc.returncode == 0
    assert proc.stdout.strip() == str(expected_path(tmp_path / "state", repo, "sid-one"))
    assert not (tmp_path / "state").exists()


def test_not_a_repository_is_a_usage_error(tmp_path):
    proc = subprocess.run([sys.executable, str(WRITER), "--repo-root", str(tmp_path), "--branch", "b",
                           "--commit", "c"], capture_output=True, text=True,
                          env=dict(os.environ, CLAUDE_STATE_DIR=str(tmp_path / "s"), GIT_CEILING_DIRECTORIES=str(tmp_path)))
    assert proc.returncode == 2


def test_the_retired_verify_hook_is_an_exit_0_stub():
    hook = ROOT / "hooks" / "posttool-push-gate-token-verify.py"
    assert any(line.startswith("# STUB:") for line in hook.read_text().splitlines())
    proc = subprocess.run([sys.executable, str(hook)], input='{"tool_input": {"file_path": "/x"}}',
                          capture_output=True, text=True)
    assert proc.returncode == 0
