"""OB-L05: every policy role has one nameable scratch location of its own.

hooks/subagentstart-record.py names each dispatch its directory,
<project>/.claude/scratch/<session>/<role>/<agent_id>/ (hooks/lib/dispatch_scratch.py),
and creates it with tmp/, the dispatch's TMPDIR. hooks/pretool-tool-policy.py judges
a $VAR Bash write target as the path it names, lets a dispatch write its own
scratch, a flat .claude/scratch/<file> and a name mktemp creates, and keeps
refusing shared /tmp names, a sibling dispatch's scratch, harness state
(hooks/lib/harness_temp_state.py) and an unresolvable word for a restricted role.

Every hook runs as a process with a throwaway HOME and project.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
POLICY_HOOK = REPO / "hooks" / "pretool-tool-policy.py"
START_HOOK = REPO / "hooks" / "subagentstart-record.py"
SID = "sess-obl05"
STATE_OUTSIDE_TEMP = "/nonexistent-obl05/state"  # a state dir below no temp root


@pytest.fixture()
def env_base(tmp_path):
    home, project = tmp_path / "home", tmp_path / "project"
    home.mkdir()
    project.mkdir()
    env = {k: v for k, v in os.environ.items()
           if k not in ("CLAUDE_PROJECT_DIR", "TMPDIR", "CLAUDE_TMPDIR", "CLAUDE_CODE_TMPDIR", "CLAUDE_STATE_DIR")}
    env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), CLAUDE_PROJECT_DIR=str(project),
               PYTHONDONTWRITEBYTECODE="1")
    return env, project


def own_scratch(project: Path, role: str, agent_id: str) -> Path:
    return project / ".claude" / "scratch" / SID / role / agent_id


def run_policy(env_base, role, agent_id, command=None, *, extra_env=None, write=None):
    env, project = env_base
    env = {**env, **(extra_env or {})}
    if write is not None:
        tool, tool_input = "Write", {"file_path": write, "content": "x"}
    else:
        tool, tool_input = "Bash", {"command": command}
    payload = {"tool_name": tool, "tool_input": tool_input, "agent_type": role, "agent_id": agent_id,
               "session_id": SID, "cwd": str(project)}
    return subprocess.run([sys.executable, str(POLICY_HOOK)], input=json.dumps(payload), capture_output=True,
                          text=True, env=env, cwd=str(project), timeout=60)


def allowed(done):
    assert done.returncode == 0, done.stderr
    assert "BLOCKED" not in done.stderr, done.stderr


def refused(done, fragment=""):
    assert done.returncode == 2, (done.returncode, done.stderr)
    assert "BLOCKED by tool-policy.v1" in done.stderr and fragment in done.stderr, done.stderr


# --- must pass ---------------------------------------------------------------------------------------------------

def test_dev_writes_tmpdir_out_when_tmpdir_is_its_own_scratch(env_base):
    _, project = env_base
    tmpdir = own_scratch(project, "dev", "adev1") / "tmp"
    allowed(run_policy(env_base, "dev", "adev1", 'python3 -m pytest -q > "$TMPDIR/out.txt" 2>&1',
                       extra_env={"TMPDIR": str(tmpdir)}))


def test_dev_exports_its_own_scratch_as_tmpdir_in_the_command(env_base):
    _, project = env_base
    tmpdir = own_scratch(project, "dev", "adev1") / "tmp"
    allowed(run_policy(env_base, "dev", "adev1",
                       f'export TMPDIR={tmpdir} && python3 -m pytest -q > "$TMPDIR/out.txt" 2>&1',
                       extra_env={"TMPDIR": "/var/tmp/claude-scratch"}))


def test_qa_writes_below_tmpdir_when_tmpdir_is_its_own_scratch(env_base):
    _, project = env_base
    allowed(run_policy(env_base, "qa", "aqa1", "python3 -m pytest -q > $TMPDIR/qa/out.txt 2>&1",
                       extra_env={"TMPDIR": str(own_scratch(project, "qa", "aqa1"))}))


def test_dev_writes_a_mktemp_name(env_base):
    allowed(run_policy(env_base, "dev", "adev1", 'f=$(mktemp) && python3 -m pytest -q > "$f"',
                       extra_env={"TMPDIR": "/var/tmp/claude-scratch"}))
    allowed(run_policy(env_base, "dev", "adev1", 'd=$(mktemp -d) && python3 -m pytest -q > "$d/out.txt"'))


def test_qa_writes_a_mktemp_name_in_its_own_scratch(env_base):
    _, project = env_base
    tmpdir = own_scratch(project, "qa", "aqa1") / "tmp"
    allowed(run_policy(env_base, "qa", "aqa1", f'export TMPDIR={tmpdir} && f=$(mktemp) && python3 -m pytest -q > "$f"'))


def test_dev_writes_a_flat_scratch_file(env_base):
    allowed(run_policy(env_base, "dev", "adev1", "python3 -m pytest -q > .claude/scratch/out.txt"))
    allowed(run_policy(env_base, "qa", "aqa1", "python3 -m pytest -q > .claude/scratch/out.txt"))


def test_each_role_writes_its_own_dispatch_scratch(env_base):
    _, project = env_base
    for role in ("dev", "qa", "ba", "test-executor", "push-analyst"):
        allowed(run_policy(env_base, role, "aown1", write=str(own_scratch(project, role, "aown1") / "notes.md")))
    allowed(run_policy(env_base, "test-executor", "aown1", f"python3 -m pytest -q > {own_scratch(project, 'test-executor', 'aown1')}/run.txt"))


# --- must still refuse -------------------------------------------------------------------------------------------

def test_dev_shared_tmp_name_is_refused(env_base):
    refused(run_policy(env_base, "dev", "adev1", "rg -n foo > /tmp/hits.txt"), "arbitrary /tmp")


def test_dev_tmpdir_that_is_shared_temp_is_refused(env_base):
    # the $VAR word is judged as the path it names: $TMPDIR=/tmp is the shared /tmp
    refused(run_policy(env_base, "dev", "adev1", 'python3 -m pytest -q > "$TMPDIR/out.txt" 2>&1',
                       extra_env={"TMPDIR": "/tmp"}), "arbitrary /tmp")


def test_another_dispatchs_scratch_is_refused(env_base):
    _, project = env_base
    target = f".claude/scratch/{SID}/qa/aqa-other/x"
    refused(run_policy(env_base, "qa", "aqa1", f"echo x > {target}"), "sibling scratch")
    refused(run_policy(env_base, "dev", "adev1", f"echo x > {target}"), "sibling scratch")
    refused(run_policy(env_base, "qa", "aqa1", write=str(project / target)), "sibling scratch")
    refused(run_policy(env_base, "qa", "aqa1", "echo x > $TMPDIR/x",
                       extra_env={"TMPDIR": str(own_scratch(project, "qa", "aqa-other"))}), "sibling scratch")


@pytest.mark.parametrize("state", [None, STATE_OUTSIDE_TEMP])
@pytest.mark.parametrize("name", ["claude-do-task-x.json", "agentic-commit/push/x.json", "agentic-commit/x"])
def test_harness_state_is_refused(env_base, state, name):
    extra = {"CLAUDE_STATE_DIR": state} if state else {}
    root = state or "/tmp"
    refused(run_policy(env_base, "dev", "adev1", f"echo x > {root}/{name}", extra_env=extra))
    refused(run_policy(env_base, "dev", "adev1", f"S={root} && echo x > $S/{name}", extra_env=extra))
    if state:
        refused(run_policy(env_base, "dev", "adev1", f"echo x > $CLAUDE_STATE_DIR/{name}", extra_env=extra))


@pytest.mark.parametrize("template", ["claude-do-task-XXXXXX.json", "claude-tool-streak-XXXXXX.json"])
def test_a_mktemp_name_that_is_harness_state_is_refused(env_base, template):
    refused(run_policy(env_base, "dev", "adev1", f'f=$(mktemp -p /tmp {template}) && echo x > "$f"'))


def test_mktemp_dry_run_is_no_unique_name(env_base):
    refused(run_policy(env_base, "dev", "adev1", 'f=$(mktemp -u) && echo x > "$f"',
                       extra_env={"TMPDIR": "/tmp"}), "arbitrary /tmp")


def test_restricted_role_unresolved_variable_is_refused(env_base):
    refused(run_policy(env_base, "qa", "aqa1", "echo x > $UNRESOLVED/x"), "not in allowed_write_path_prefixes")


def test_an_analysts_own_grant_dir_stays_writable_outside_temp(env_base):
    allowed(run_policy(env_base, "push-analyst", "apush1",
                       write=f"{STATE_OUTSIDE_TEMP}/agentic-commit/push-analyst/grant.json",
                       extra_env={"CLAUDE_STATE_DIR": STATE_OUTSIDE_TEMP}))


# --- handed over at dispatch -------------------------------------------------------------------------------------

def run_start(env_base, role, agent_id):
    env, project = env_base
    payload = {"agent_id": agent_id, "agent_type": role, "cwd": str(project), "session_id": SID,
               "transcript_path": str(project / "t.jsonl")}
    return subprocess.run([sys.executable, str(START_HOOK)], input=json.dumps(payload), capture_output=True,
                          text=True, env=env, timeout=60)


def _context(done) -> str:
    assert done.returncode == 0 and not done.stderr, done.stderr
    return json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"] if done.stdout.strip() else ""


@pytest.mark.parametrize("role", ["dev", "qa", "spec", "graphify"])
def test_start_names_and_creates_the_dispatch_scratch_the_policy_accepts(env_base, role):
    _, project = env_base
    scratch = own_scratch(project, role, "astart1")
    text = _context(run_start(env_base, role, "astart1"))
    assert f"{scratch}/" in text and f"export TMPDIR={scratch}/tmp" in text, text
    assert (scratch / "tmp").is_dir()
    allowed(run_policy(env_base, role, "astart1", 'python3 -m pytest -q > "$TMPDIR/out.txt" 2>&1',
                       extra_env={"TMPDIR": str(scratch / "tmp")}))
    refused(run_policy(env_base, role, "astart2", 'python3 -m pytest -q > "$TMPDIR/out.txt" 2>&1',
                       extra_env={"TMPDIR": str(scratch / "tmp")}), "sibling scratch")


def test_start_names_no_scratch_for_an_unlisted_role_a_role_without_write_or_an_unsafe_id(env_base):
    _, project = env_base
    assert "Your scratch" not in _context(run_start(env_base, "Explore", "aexp1"))
    assert "Your scratch" not in _context(run_start(env_base, "pull-analyst", "apull1"))
    assert "Your scratch" not in _context(run_start(env_base, "dev", "../escape"))
    assert not (project / ".claude" / "scratch" / SID / "Explore").exists()
