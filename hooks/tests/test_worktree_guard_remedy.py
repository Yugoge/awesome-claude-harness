"""hooks/pretool-worktree-guard.sh: with an agent worktree behind master the guard refuses every call
and names its remedy, `git worktree remove <path> --force`; that remedy is itself a call, so the guard
lets a Bash call that removes or prunes a worktree through (else no call clears the alert: a dead end,
D25 (3), tests/replay/test_no_dead_end.py case stale-worktree). Every other call stays refused.
"""
import json
import os
import subprocess
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "pretool-worktree-guard.sh"


def _git(cwd, *args, env):
    subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True)


def _setup(tmp_path):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path / "home"),
           "CLAUDE_STATE_DIR": str(tmp_path / "state"), "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    for d in ("home", "state", "repo"):
        (tmp_path / d).mkdir()
    repo = tmp_path / "repo"
    _git(repo, "init", "-q", "-b", "master", env=env)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "one", env=env)
    wt = repo / ".claude" / "worktrees" / "agent-0123456789abcdef"
    _git(repo, "worktree", "add", "-q", "--detach", str(wt), env=env)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "master moves on", env=env)
    return repo, wt, env


def _run(repo, env, tool, tool_input):
    payload = {"session_id": "s", "hook_event_name": "PreToolUse", "cwd": str(repo),
               "tool_name": tool, "tool_input": tool_input}
    return subprocess.run(["bash", str(HOOK)], input=json.dumps(payload), cwd=repo, env=env,
                          capture_output=True, text=True, timeout=60)


def test_stale_worktree_refuses_calls_but_not_its_remedy(tmp_path):
    repo, wt, env = _setup(tmp_path)
    read = _run(repo, env, "Read", {"file_path": str(repo / "x")})
    assert read.returncode == 2 and "STALE WORKTREE ALERT" in read.stderr, read.stderr
    other = _run(repo, env, "Bash", {"command": "git status"})
    assert other.returncode == 2, "a Bash call other than the remedy stays refused"
    remedy = _run(repo, env, "Bash", {"command": f"git worktree remove {wt} --force"})
    assert remedy.returncode == 0, remedy.stderr
    prune = _run(repo, env, "Bash", {"command": f"git -C {repo} worktree prune"})
    assert prune.returncode == 0, prune.stderr
    _git(repo, "worktree", "remove", str(wt), "--force", env=env)
    after = _run(repo, env, "Read", {"file_path": str(repo / "x")})
    assert after.returncode == 0, "with the worktree removed nothing is refused"


def test_a_remedy_mentioned_only_in_text_is_still_refused(tmp_path):
    repo, wt, env = _setup(tmp_path)
    write = _run(repo, env, "Write", {"file_path": str(repo / "n.md"), "content": "git worktree remove x"})
    assert write.returncode == 2, "only a Bash command runs the remedy"
