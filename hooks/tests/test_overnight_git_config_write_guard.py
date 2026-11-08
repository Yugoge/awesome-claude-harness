#!/usr/bin/env python3
"""An overnight actor's Write, Edit or MultiEdit of its checkout's git config is refused (P2 R13).

The keystone's core.hooksPath lives in the repository's git config. bubblewrap's
read-only rebind keeps the actor's Bash off it, but an Edit runs in the CLI, outside
bubblewrap: replayed with a stand-in that applies the binds, both `.git/config` Edits
(main agent and subagent) still removed the key. So the guard refuses a Write, Edit or
MultiEdit whose target is the `config` or `config.worktree` of the git dir or the
common dir of the checkout the target lies in, for the actors its Bash rewrite
governs; other files, other sessions and a released record pass.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "pretool-overnight-hook-guard.py"
SID = "s-git-config"
FUTURE, PAST = "2099-01-01T00:00:00Z", "2000-01-01T00:00:00Z"
GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid"}
KEY = "\thooksPath = /keystone-hooks\n"


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV}, check=True, capture_output=True)


def _state(main: Path, worktree: Path, kind: str, until: str = FUTURE) -> None:
    (main / ".claude").mkdir(exist_ok=True)
    (main / ".claude" / f"overnight-state-{SID}.json").write_text(json.dumps({
        "schema_version": 9, "session_id": SID, "isolation_kind": kind, "main_root": str(main),
        "main_git_dir": str(main / ".git"), "worktree_path": str(worktree), "worktree_branch": "night-work",
        "protected_branch": "master", "end_time": until, "isolation_active_until": until, "current_cycle": 1}))


@pytest.fixture
def repo(tmp_path):
    """A product checkout with the keystone in its git config, and a linked worktree of it."""
    main = tmp_path / "toy"
    main.mkdir()
    _git("init", "-q", "-b", "master", cwd=main)
    _git("config", "core.hooksPath", "/keystone-hooks", cwd=main)
    _git("commit", "-q", "--allow-empty", "-m", "init", cwd=main)
    _git("worktree", "add", "-q", "-b", "night-work", str(tmp_path / "wt"), cwd=main)
    (main / "config").write_text("not git's\n")
    return main


def _hook(main: Path, tool: str, tool_input: dict, cwd: Path, agent: bool = False, session: str = SID):
    payload = {"session_id": session, "tool_name": tool, "tool_input": tool_input, "cwd": str(cwd),
               "transcript_path": str(main / "t.jsonl")}
    if agent:
        payload.update(agent_id="a1b2c3d4e5", agent_type="dev")
    env = {**os.environ, **GIT_ENV, "CLAUDE_PROJECT_DIR": str(main), "PWD": str(cwd)}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True, text=True,
                          env=env, cwd=cwd, timeout=120)


def _edit(path: Path) -> tuple[str, dict]:
    return "Edit", {"file_path": str(path), "old_string": KEY, "new_string": ""}


@pytest.mark.parametrize("agent", [False, True], ids=["main agent", "subagent"])
@pytest.mark.parametrize("tool", ["Edit", "Write", "MultiEdit"])
def test_in_place_actor_cannot_write_the_git_config(repo, agent, tool):
    _state(repo, repo, "in_place")
    target = repo / ".git" / "config"
    tool_input = {"Edit": _edit(target)[1], "Write": {"file_path": str(target), "content": ""},
                  "MultiEdit": {"file_path": str(target), "edits": [{"old_string": KEY, "new_string": ""}]}}[tool]
    r = _hook(repo, tool, tool_input, repo, agent=agent)
    assert r.returncode == 2 and "OVERNIGHT GIT CONFIG PROTECTION" in r.stderr, r.stderr
    assert "hooksPath = /keystone-hooks" in target.read_text()


def test_config_worktree_not_yet_there_and_a_symlink_are_refused(repo):
    _state(repo, repo, "in_place")
    (repo / "link").symlink_to(repo / ".git" / "config")
    for target in (repo / ".git" / "config.worktree", repo / "link"):
        r = _hook(repo, "Write", {"file_path": str(target), "content": "[core]\n\thooksPath = /dev/null\n"}, repo)
        assert r.returncode == 2 and "OVERNIGHT GIT CONFIG PROTECTION" in r.stderr, (target, r.stderr)


def test_linked_worktree_actor_cannot_write_its_git_dir_or_common_dir_config(repo):
    wt = repo.parent / "wt"
    _state(repo, wt, "registered_worktree")
    for target in (repo / ".git" / "config", repo / ".git" / "worktrees" / "wt" / "config.worktree"):
        r = _hook(repo, "Write", {"file_path": str(target), "content": ""}, wt)
        assert r.returncode == 2 and "OVERNIGHT GIT CONFIG PROTECTION" in r.stderr, (target, r.stderr)


def test_other_files_named_config_pass(repo):
    _state(repo, repo, "in_place")
    for target in (repo / "config", repo / "toy" / "config.worktree", repo / "README.md"):
        r = _hook(repo, "Write", {"file_path": str(target), "content": "x\n"}, repo)
        assert r.returncode == 0, (target, r.stderr)


def test_another_session_and_a_released_record_pass(repo):
    _state(repo, repo, "in_place")
    assert _hook(repo, *_edit(repo / ".git" / "config"), repo, session="someone-else").returncode == 0
    _state(repo, repo, "in_place", until=PAST)
    r = _hook(repo, *_edit(repo / ".git" / "config"), repo)
    assert r.returncode == 0, r.stderr
