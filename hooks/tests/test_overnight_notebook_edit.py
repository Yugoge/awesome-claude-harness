#!/usr/bin/env python3
"""NotebookEdit is a file-writing tool for the overnight boundary (hardcode audit 2026-11-19, finding 10).

The guard named Write, Edit and MultiEdit at five places and read `file_path`; its write-gate row
named the same three. An overnight actor's Edit of `<main>/analysis/model.ipynb` was refused and its
NotebookEdit of the same file passed, and bubblewrap covers Bash only, so this rule is what keeps
tool writes out of main. The guard now reads the tool's target from lib/command_span.EDIT_TOOLS
(four tools, NotebookEdit's `notebook_path`), and the row is the gate's WRITE_TOOLS.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
HOOK = HOOKS / "pretool-overnight-hook-guard.py"
SID = "s-notebook"
FUTURE = "2099-01-01T00:00:00Z"
GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV}, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    """A product checkout (main), a linked worktree of it, and a live overnight record that binds the
    session to the worktree."""
    main = tmp_path / "toy"
    main.mkdir()
    _git("init", "-q", "-b", "master", cwd=main)
    _git("commit", "-q", "--allow-empty", "-m", "init", cwd=main)
    _git("worktree", "add", "-q", "-b", "night-work", str(tmp_path / "wt"), cwd=main)
    (main / ".claude").mkdir()
    (main / ".claude" / f"overnight-state-{SID}.json").write_text(json.dumps({
        "schema_version": 9, "session_id": SID, "isolation_kind": "registered_worktree", "main_root": str(main),
        "main_git_dir": str(main / ".git"), "worktree_path": str(tmp_path / "wt"), "worktree_branch": "night-work",
        "protected_branch": "master", "end_time": FUTURE, "isolation_active_until": FUTURE, "current_cycle": 1}))
    return main


def _hook(main: Path, tool: str, tool_input: dict, cwd: Path, agent: bool = False, session: str = SID):
    payload = {"session_id": session, "tool_name": tool, "tool_input": tool_input, "cwd": str(cwd),
               "transcript_path": str(main / "t.jsonl")}
    if agent:
        payload.update(agent_id="a1b2c3d4e5", agent_type="dev")
    env = {**os.environ, **GIT_ENV, "CLAUDE_PROJECT_DIR": str(main), "PWD": str(cwd)}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True, text=True,
                          env=env, cwd=cwd, timeout=120)


def _calls(path: Path):
    """The Edit and the NotebookEdit of one file."""
    return (("Edit", {"file_path": str(path), "old_string": "a", "new_string": "b"}),
            ("NotebookEdit", {"notebook_path": str(path), "new_source": "x = 1"}))


@pytest.mark.parametrize("agent", [False, True], ids=["main agent", "subagent"])
def test_a_notebook_edit_in_main_is_refused_as_the_edit_of_the_same_file_is(repo, agent):
    wt, target = repo.parent / "wt", repo / "analysis" / "model.ipynb"
    for tool, tool_input in _calls(target):
        r = _hook(repo, tool, tool_input, wt, agent=agent)
        assert r.returncode == 2 and "OVERNIGHT WORKTREE ENFORCEMENT" in r.stderr, (tool, r.stderr)
        assert f"Attempted: {tool} to {target}" in r.stderr, (tool, r.stderr)


@pytest.mark.parametrize("agent", [False, True], ids=["main agent", "subagent"])
def test_a_notebook_edit_inside_the_worktree_passes(repo, agent):
    wt = repo.parent / "wt"
    for tool, tool_input in _calls(wt / "analysis" / "model.ipynb"):
        r = _hook(repo, tool, tool_input, wt, agent=agent)
        assert r.returncode == 0 and not r.stderr, (tool, r.stderr)


def test_another_session_keeps_its_notebook_edits_in_main(repo):
    """A concurrent session on main is no overnight actor: the boundary is not its rule."""
    for tool, tool_input in _calls(repo / "analysis" / "model.ipynb"):
        r = _hook(repo, tool, tool_input, repo, session="someone-else")
        assert r.returncode == 0 and not r.stderr, (tool, r.stderr)


def test_a_notebook_edit_of_the_actors_git_config_is_refused(repo):
    target = repo / ".git" / "config"
    r = _hook(repo, "NotebookEdit", {"notebook_path": str(target), "new_source": "x"}, repo.parent / "wt")
    assert r.returncode == 2 and str(target) in r.stderr, r.stderr


def test_a_notebook_edit_of_an_overnight_state_file_is_refused_for_every_session(repo):
    target = repo / ".claude" / f"overnight-state-{SID}.json"
    for tool, tool_input in _calls(target):
        r = _hook(repo, tool, tool_input, repo, session="someone-else")
        assert r.returncode == 2 and "OVERNIGHT STATE PROTECTION" in r.stderr, (tool, r.stderr)


def test_the_gate_sends_every_file_writing_tool_to_the_rule():
    sys.path.insert(0, str(HOOKS))
    try:
        from lib import write_gate
    finally:
        sys.path.pop(0)
    rule = next(r for r in write_gate.RULES if r.name == "overnight-boundary")
    assert rule.tools == write_gate.WRITE_TOOLS | {"Bash", "AskUserQuestion"}
    assert all(rule.applies(tool) for tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"))
