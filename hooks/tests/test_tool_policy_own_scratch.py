"""A refused write to system temp or to another actor's scratch names the caller's own directory.

hooks/pretool-tool-policy.py refuses every role a write under /tmp or /var/tmp (the shipped
TMPDIR, /var/tmp/claude-scratch, included) and a write into scratch that is not the caller's own
<project>/.claude/scratch/<...>/<role>/<agent id>/. The refusal names that own directory as a
literal path, and the same actor's next write there, by the Write tool or a shell redirect, is
allowed; another actor's is not. Only paths are judged: the projects are never created.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
HOOK = os.path.join(ROOT, "hooks", "pretool-tool-policy.py")
SID = "5e6f7a8b-1c2d-4e3f-9a0b-1c2d3e4f5a6b"
PROJECTS = ("/nonexistent-own-scratch/proj", "/dev/shm/nonexistent-own-scratch/proj")
NAMED = re.compile(r"your own scratch directory is (/\S+?)/ ")


def run(tmp_path, project, tool, tool_input, caller=("a1b2c3d4e5f60718", "dev")):
    home = tmp_path / "home"
    payload = {"session_id": SID, "cwd": project, "hook_event_name": "PreToolUse", "tool_name": tool,
               "tool_input": tool_input}
    if caller:
        payload.update(agent_id=caller[0], agent_type=caller[1], subagent_type=caller[1])
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), CLAUDE_PROJECT_DIR=project,
               CLAUDE_STATE_DIR=str(tmp_path / "state"), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, HOOK], input=json.dumps(payload), capture_output=True, text=True,
                          cwd=str(tmp_path), env=env, timeout=60)


def writes(path):
    return [("Write", {"file_path": f"{path}/next.txt", "content": "x"}),
            ("Bash", {"command": f"mkdir -p {path} && echo x > {path}/next.txt"})]


@pytest.mark.parametrize("project", PROJECTS)
@pytest.mark.parametrize("role", ["dev", "ba", "qa"])
@pytest.mark.parametrize("guess", ["{p}/.claude/scratch/dev-20261117-173256/{r}/r00/probe.txt",
                                   "{p}/.claude/scratch/r00-baseline.txt",
                                   "/var/tmp/claude-scratch/r13/build.py", "/tmp/ba_r05/an.py"])
def test_refusal_names_a_literal_own_directory_the_next_write_may_use(tmp_path, project, role, guess):
    caller = ("a" + role.ljust(15, "0"), role)
    target = guess.format(p=project, r=role)
    for tool, tool_input in [("Write", {"file_path": target, "content": "x"}),
                             ("Bash", {"command": f"cd {project}; echo x > {target}"})]:
        refused = run(tmp_path, project, tool, tool_input, caller)
        assert refused.returncode == 2, refused.stderr
        found = NAMED.search(refused.stderr)
        assert found, refused.stderr
        own = found.group(1)
        assert "<" not in own and own.startswith(f"{project}/.claude/scratch/") and caller[0] in own
        for next_tool, next_input in writes(own):
            proc = run(tmp_path, project, next_tool, next_input, caller)
            assert proc.returncode == 0, (next_tool, proc.stderr)


@pytest.mark.parametrize("project", PROJECTS)
def test_another_actor_is_still_refused_the_named_directory(tmp_path, project):
    refused = run(tmp_path, project, "Write", {"file_path": "/tmp/x.py", "content": "x"})
    own = NAMED.search(refused.stderr).group(1)
    for other in [("a9999999999999999", "dev"), ("a1b2c3d4e5f60718", "qa")]:
        for tool, tool_input in writes(own):
            proc = run(tmp_path, project, tool, tool_input, other)
            assert proc.returncode == 2, (other, tool, proc.stderr)
            assert "sibling scratch target denied" in proc.stderr or "allowed_write_path_prefixes" in proc.stderr


def test_a_program_that_honours_tmpdir_runs_with_tmpdir_set_to_the_named_directory(tmp_path):
    project = PROJECTS[0]
    refused = run(tmp_path, project, "Bash", {"command": f"cd {project}; python3 -m pytest -q > "
                                                         "/var/tmp/claude-scratch/r02-ci.txt 2>&1"})
    assert refused.returncode == 2 and "TMPDIR=" in refused.stderr
    own = NAMED.search(refused.stderr).group(1)
    proc = run(tmp_path, project, "Bash", {"command": f"cd {project}; mkdir -p {own}; TMPDIR={own} "
                                                      f"python3 -m pytest -q > {own}/r02-ci.txt 2>&1"})
    assert proc.returncode == 0, proc.stderr


def test_the_main_agents_session_scratch_is_unchanged(tmp_path):
    project = PROJECTS[0]
    proc = run(tmp_path, project, "Write", {"file_path": f"/var/tmp/claude-scratch/{SID}/notes.md",
                                            "content": "x"}, caller=None)
    assert proc.returncode == 0, proc.stderr
