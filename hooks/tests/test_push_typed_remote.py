"""hooks/push.sh counts a remote it is given ahead of that remote's own tracking ref (P5 R14).

execute-push.py hands push.sh the resolved remote as its argument. The ahead count is taken against
refs/remotes/<remote>/<BRANCH>, so a remote that lacks HEAD is pushed even when nothing is ahead of
the upstream, and a remote with no such ref is a first push to it. Each case runs the real script
past its chain-B sentinel and push-gate token (both written as their producers write them) in a
scratch HOME and state dir; the remotes are local bare repositories.
"""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

PUSH_SH = Path(__file__).resolve().parents[1] / "push.sh"
REQUEST_ID = "req-typed-remote"


@pytest.fixture
def world(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "CLAUDE_"))}
    env.update({"HOME": str(tmp_path / "home"), "CLAUDE_STATE_DIR": str(tmp_path / "state"),
                "CLAUDE_PUSH_REQUEST_ID": REQUEST_ID, "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"})
    (tmp_path / "home").mkdir()
    for bare in ("origin.git", "fork.git"):
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(tmp_path / bare)], env=env, check=True)
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], env=env, check=True)

    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], env=env, check=True,
                              capture_output=True, text=True).stdout.strip()

    git("remote", "add", "origin", str(tmp_path / "origin.git"))
    git("remote", "add", "fork", str(tmp_path / "fork.git"))
    git("commit", "-q", "--allow-empty", "-m", "one")
    git("push", "-q", "-u", "origin", "main")
    return tmp_path, env, repo, git


def push(world, remote):
    """push.sh <remote> with its sentinel and a push-gate token for HEAD in place."""
    tmp_path, env, repo, git = world
    head = git("rev-parse", "HEAD")
    repo_hash = hashlib.sha256(os.path.realpath(repo).encode()).hexdigest()[:16]
    sentinel = tmp_path / "state" / "agentic-commit" / "push-analyst" / repo_hash
    sentinel.mkdir(parents=True, exist_ok=True)
    (sentinel / "main-chainB.validated.sentinel.json").write_text(json.dumps(
        {"result": "PASS", "request_id": REQUEST_ID, "head": head, "branch": "main", "remote": remote}))
    token = tmp_path / "state" / "agentic-commit" / "push" / repo_hash / "s"
    token.mkdir(parents=True, exist_ok=True)
    (token / "main.json").write_text(json.dumps({"commit_sha": head, "branch": "main"}))
    r = subprocess.run(["bash", str(PUSH_SH), remote], cwd=repo, env=env, capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=120)
    return r, head


def remote_tip(world, remote):
    tmp_path, env, _, _ = world
    r = subprocess.run(["git", "--git-dir", str(tmp_path / f"{remote}.git"), "rev-parse", "-q", "--verify",
                        "refs/heads/main"], env=env, capture_output=True, text=True)
    return r.stdout.strip()


def test_a_remote_lacking_head_is_pushed_though_nothing_is_ahead_of_the_upstream(world):
    r, head = push(world, "fork")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "is not on fork yet" in r.stdout, r.stdout
    assert remote_tip(world, "fork") == head


def test_nothing_ahead_of_the_remotes_own_tracking_ref_pushes_nothing(world):
    r, head = push(world, "origin")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Nothing to push" in r.stdout, r.stdout
    assert remote_tip(world, "origin") == head


def test_commits_ahead_of_the_remotes_tracking_ref_are_pushed_to_it(world):
    assert push(world, "fork")[0].returncode == 0
    _, _, _, git = world
    git("commit", "-q", "--allow-empty", "-m", "two")
    r, head = push(world, "fork")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 commit(s) ahead of remote" in r.stdout, r.stdout
    assert remote_tip(world, "fork") == head
