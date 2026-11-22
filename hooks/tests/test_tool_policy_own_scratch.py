"""A refused write to system temp or to another actor's scratch names the caller's own directory.

hooks/pretool-tool-policy.py refuses every role a write under /tmp or /var/tmp (the shipped
TMPDIR, /var/tmp/claude-scratch, included) and a write into scratch that is not the caller's own.
A subagent's own scratch directory is <session scratch directory>/<role>/<agent id>/ below the
session scratch root (the hooks' TMPDIR), outside every project and the harness home;
hooks/subagentstart-scratch.py makes it when the agent starts. The refusal names it as a literal
path and advises no temp directory, and the same actor's next write there, by the Write tool or a
shell redirect, is allowed; another actor's is not. An agent an earlier version sent to
<project>/.claude/scratch/<session>/<role>/<agent id>/ keeps that directory. Only paths are
judged: the projects are never created.
"""
from __future__ import annotations

import importlib.util
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
               CLAUDE_STATE_DIR=str(tmp_path / "state"), TMPDIR=str(session_root(tmp_path)), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, HOOK], input=json.dumps(payload), capture_output=True, text=True,
                          cwd=str(tmp_path), env=env, timeout=60)


def session_root(tmp_path):
    """The session scratch root as the hooks see it (TMPDIR), on the disk pytest's temp lies on."""
    root = tmp_path / "session-root"
    root.mkdir(exist_ok=True)
    return root.resolve()


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
        assert own == str(session_root(tmp_path) / SID / role / caller[0]), refused.stderr
        assert not own.startswith(project + "/") and "TMPDIR" not in refused.stderr, refused.stderr
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


def test_the_refusal_advises_no_temp_directory_and_the_command_needs_none(tmp_path):
    project = PROJECTS[0]
    refused = run(tmp_path, project, "Bash", {"command": f"cd {project}; python3 -m pytest -q > "
                                                         "/var/tmp/claude-scratch/r02-ci.txt 2>&1"})
    assert refused.returncode == 2 and "TMPDIR" not in refused.stderr, refused.stderr
    own = NAMED.search(refused.stderr).group(1)
    proc = run(tmp_path, project, "Bash", {"command": f"cd {project}; python3 -m pytest -q > {own}/r02-ci.txt 2>&1"})
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("project", PROJECTS)
def test_an_agent_sent_into_the_project_by_an_earlier_version_keeps_that_directory(tmp_path, project):
    """<project>/.claude/scratch/<session>/<role>/<agent id>/ stays the agent's own (written, overwritten and
    removed in as before); another agent's there stays refused; neither is named any more."""
    caller, old = ("a1b2c3d4e5f60718", "dev"), f"{project}/.claude/scratch/{SID}/dev/a1b2c3d4e5f60718"
    for tool, tool_input in writes(old):
        proc = run(tmp_path, project, tool, tool_input, caller)
        assert proc.returncode == 0 and "own scratch directory" not in proc.stderr, (tool, proc.stderr)
        other = run(tmp_path, project, tool, tool_input, ("a9999999999999999", "dev"))
        assert other.returncode == 2 and "sibling scratch target denied" in other.stderr, (tool, other.stderr)
        assert NAMED.search(other.stderr).group(1) == str(session_root(tmp_path) / SID / "dev" / "a9999999999999999")


def test_the_main_agents_session_scratch_is_unchanged(tmp_path):
    project = PROJECTS[0]
    proc = run(tmp_path, project, "Write", {"file_path": f"/var/tmp/claude-scratch/{SID}/notes.md",
                                            "content": "x"}, caller=None)
    assert proc.returncode == 0, proc.stderr


# -- the main agent: its session's scratch directory -----------------------------------------
INIT = os.path.join(ROOT, "hooks", "session-scratch-init.sh")


def _session_scratch(tmp_path):
    """hooks/session-scratch-init.sh run for SID with TMPDIR on tmp_path: (TMPDIR, the env file it wrote)."""
    root, env_file = tmp_path / "tmpdir", tmp_path / "env-file"
    root.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update(HOME=str(tmp_path / "home"), TMPDIR=str(root), CLAUDE_ENV_FILE=str(env_file))
    proc = subprocess.run(["bash", INIT], input=json.dumps({"session_id": SID}), capture_output=True, text=True,
                          env=env, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return root, env_file


def test_the_session_start_points_tmpdir_at_the_main_agents_own_scratch(tmp_path):
    """The session's programs, pytest's temp root among them, write in the main agent's own scratch directory."""
    root, env_file = _session_scratch(tmp_path)
    own = root / SID
    assert (own / ".owner").is_file()
    probe = "import tempfile; print(tempfile.gettempdir())"
    out = subprocess.run(["bash", "-c", f". {env_file}; python3 -c '{probe}'"], capture_output=True, text=True,
                         env={"PATH": os.environ["PATH"]}, timeout=60).stdout.strip()
    assert out == str(own)


def test_the_main_agents_own_scratch_is_its_session_scratch(tmp_path):
    root, _env_file = _session_scratch(tmp_path)
    own = root / SID
    other = root / "0f0e0d0c-0b0a-4908-8706-050403020100"
    other.mkdir()
    (other / ".owner").write_text(json.dumps({"sid": other.name}))
    sys.path.insert(0, os.path.join(ROOT, "hooks"))
    try:
        from lib import locations
        spec = importlib.util.spec_from_file_location("_tool_policy_main", HOOK)
        policy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(policy)
        policy._bootstrap_security()
        os.environ["TMPDIR"], saved = str(root), os.environ.get("TMPDIR")
        try:
            main = {"session_id": SID}
            assert policy._scratch_status(None, str(own / "pytest-of-root" / "x"), main) == "owner"
            for path in (other / "x", root / "x", "/tmp/tmp.AbC123/x"):
                assert policy._scratch_status(None, str(path), main) != "owner", path
            assert policy._scratch_status("dev", str(own / "x"), dict(main, agent_id="a1")) != "owner"
        finally:
            os.environ.pop("TMPDIR") if saved is None else os.environ.__setitem__("TMPDIR", saved)
        # With no TMPDIR (a default install), the policy and the session start agree on the root.
        env = {k: v for k, v in os.environ.items() if k != "TMPDIR"}
        out = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); from lib import "
                              "locations; print(locations.session_scratch_dir('s'))", os.path.join(ROOT, "hooks")],
                             capture_output=True, text=True, env=env, timeout=60).stdout.strip()
        assert out == os.path.join(os.path.realpath(locations.SESSION_SCRATCH_ROOT), "s")
        assert '"${TMPDIR:-' + locations.SESSION_SCRATCH_ROOT + '}"' in open(INIT, encoding="utf-8").read()
    finally:
        sys.path.remove(os.path.join(ROOT, "hooks"))


def test_a_main_agent_write_in_its_session_scratch_is_allowed(tmp_path):
    root, _env_file = _session_scratch(tmp_path)
    proc = run(tmp_path, PROJECTS[0], "Write", {"file_path": str(root / SID / "notes.md"), "content": "x"}, None)
    assert proc.returncode == 0, proc.stderr


# -- a subagent: its own scratch directory is made at its start, its commands' temp files stay there ---------
START = os.path.join(ROOT, "hooks", "subagentstart-launch.py")


def test_the_agents_own_scratch_directory_exists_when_it_starts_and_is_the_one_named(tmp_path):
    """SubagentStart makes <session scratch directory>/<role>/<agent id>/ (the agent makes nothing), outside the
    project; the directory a refused write names is that one."""
    root, _env_file = _session_scratch(tmp_path)
    project, agent = PROJECTS[0], ("a0a1a2a3a4a5a6a7", "qa")
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update(HOME=str(tmp_path / "home"), TMPDIR=str(root), CLAUDE_STATE_DIR=str(tmp_path / "state"))
    payload = {"session_id": SID, "agent_id": agent[0], "agent_type": agent[1], "cwd": str(tmp_path),
               "hook_event_name": "SubagentStart", "transcript_path": ""}
    proc = subprocess.run([sys.executable, START], input=json.dumps(payload), capture_output=True, text=True,
                          env=env, cwd=str(tmp_path), timeout=120)
    assert proc.returncode == 0, proc.stderr
    own = root.resolve() / SID / agent[1] / agent[0]
    assert own.is_dir() and (root / SID / ".owner").is_file()
    env.update(CLAUDE_PROJECT_DIR=project, HOME=str(tmp_path / "home"))
    refused = subprocess.run([sys.executable, HOOK], capture_output=True, text=True, cwd=str(tmp_path), env=env,
                             input=json.dumps(dict(payload, hook_event_name="PreToolUse", tool_name="Write", cwd=project,
                                                   tool_input={"file_path": "/tmp/x.py", "content": "x"})), timeout=60)
    assert refused.returncode == 2 and NAMED.search(refused.stderr).group(1) == str(own), refused.stderr


def test_a_subagents_command_that_sets_no_temp_directory_writes_its_temp_files_in_the_session_root(tmp_path):
    """The CLI runs every Bash command of the session, a subagent's included, after sourcing the session's env
    file; hooks/session-scratch-init.sh points TMPDIR there at the session's scratch directory. A command that
    sets no TMPDIR itself (here a project test that refuses a temp root inside its project, as the project of
    2026-11-20 does) makes its temp files under the session root: not in system temp, not in the project."""
    root, env_file = _session_scratch(tmp_path)
    project = tmp_path / "proj"
    project.mkdir()
    probe = ("import os, sys, tempfile; d = os.path.realpath(tempfile.mkdtemp(prefix='map-')); "
             "sys.exit('temp root inside the project') if d.startswith(os.getcwd() + os.sep) else print(d)")
    out = subprocess.run(["bash", "-c", f". {env_file}; python3 -c \"{probe}\""], capture_output=True, text=True,
                         env={"PATH": os.environ["PATH"]}, cwd=str(project), timeout=60)
    assert out.returncode == 0, out.stderr
    made = out.stdout.strip()
    assert made.startswith(str(root.resolve() / SID) + os.sep), made
    assert not made.startswith(("/tmp/", str(project) + os.sep)), made
