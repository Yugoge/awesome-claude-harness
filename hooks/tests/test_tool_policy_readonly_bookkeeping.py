"""Every role's allowed_tools admits the CLI's read-only and bookkeeping tools (OB-L22).

policies/tool-policy.v1.json is default-deny per role: lib/policy_registry._check_tool_lists refuses
a tool its role's allowed_tools does not name. Rows written for the file tools left out the tools a
subagent uses to search, keep its own task list, or watch and stop its own background jobs, so
graphify's Grep and Glob, any role's TodoWrite and a dev's TaskOutput / TaskStop on its own `Bash
run_in_background` job exited 2. Each name below changes no file, runs no command, reaches no
network and dispatches no agent:

- Grep, Glob: search file contents and names (read-only; Read was already allowed everywhere).
- TodoWrite, TodoRead: the agent's own todo list (TodoRead is the older read-only half the harness
  still recognises, hooks/pretool-workflow-gate.py).
- TaskCreate, TaskGet, TaskList, TaskUpdate: the task-list tools the CLI offers in TodoWrite's place
  while CLAUDE_CODE_ENABLE_TASKS is on (hooks/stop-command-gate.py), same bookkeeping.
- TaskOutput, BashOutput: read the output of the caller's own background task (BashOutput is the
  older name).
- TaskStop, KillShell: stop the caller's own background task (KillShell is the older name); they
  end a command already allowed to run, they start none.
- ToolSearch: loads a deferred tool's schema; the loaded tool's own call is still judged by its row.

The hook-level cases run the real hooks/pretool-tool-policy.py for a subagent of each role, with a
throwaway HOME; the refusals that must stay are proven the same way.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
HOOK = os.path.join(ROOT, "hooks", "pretool-tool-policy.py")
sys.path.insert(0, os.path.join(ROOT, "hooks", "lib"))
import policy_registry  # noqa: E402

SID = "7c1e2d3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f"
# A product repository outside /tmp and /var/tmp, never created; only paths are judged.
PRODUCT = "/nonexistent-ob-l22/product"
READ_ONLY_AND_BOOKKEEPING = (
    "Grep", "Glob", "TodoWrite", "TodoRead", "TaskCreate", "TaskGet", "TaskList", "TaskUpdate",
    "TaskOutput", "BashOutput", "TaskStop", "KillShell", "ToolSearch",
)
# Tools that write files, run commands, reach the network or dispatch agents: none is in the set above.
NEVER_IN_SET = ("Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "Monitor", "WebFetch", "WebSearch",
                "Agent", "Task", "SendMessage", "Skill", "CronCreate", "EnterWorktree")


def run(tmp_path, role: str, tool: str, tool_input: dict):
    home = tmp_path / "home"
    payload = {"session_id": SID, "transcript_path": str(home / ".claude" / "projects" / "-p" / f"{SID}.jsonl"),
               "cwd": PRODUCT, "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
               "agent_id": f"a0{role}", "agent_type": role, "subagent_type": role}
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), CLAUDE_PROJECT_DIR=PRODUCT,
               CLAUDE_STATE_DIR=str(tmp_path / "state"), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, HOOK], input=json.dumps(payload), capture_output=True, text=True,
                          cwd=str(tmp_path), env=env, timeout=60)


MUST_PASS = [
    ("graphify", "Grep", {"pattern": "def main", "path": PRODUCT}),
    ("graphify", "Glob", {"pattern": "**/*.py", "path": PRODUCT}),
    ("dev", "TodoWrite", {"todos": [{"content": "a", "activeForm": "a", "status": "in_progress"}]}),
    ("qa", "TodoWrite", {"todos": [{"content": "a", "activeForm": "a", "status": "in_progress"}]}),
    ("dev", "TaskOutput", {"task_id": "b1", "block": False}),
    ("dev", "BashOutput", {"bash_id": "b1"}),
    ("dev", "TaskStop", {"task_id": "b1"}),
    ("dev", "KillShell", {"shell_id": "b1"}),
]

MUST_REFUSE = [
    ("graphify", "Edit", {"file_path": f"{PRODUCT}/README.md", "old_string": "a", "new_string": "b"}),
    ("qa", "Edit", {"file_path": f"{PRODUCT}/src/app.py", "old_string": "a", "new_string": "b"}),
    ("user", "Read", {"file_path": f"{PRODUCT}/src/app.py"}),
]


@pytest.mark.parametrize("role,tool,tool_input", MUST_PASS, ids=[f"{r}-{t}" for r, t, _ in MUST_PASS])
def test_read_only_and_bookkeeping_tool_passes(tmp_path, role, tool, tool_input):
    result = run(tmp_path, role, tool, tool_input)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("role,tool,tool_input", MUST_REFUSE, ids=[f"{r}-{t}" for r, t, _ in MUST_REFUSE])
def test_refusal_stays(tmp_path, role, tool, tool_input):
    result = run(tmp_path, role, tool, tool_input)
    assert result.returncode == 2, result.stderr
    assert result.stderr.startswith("BLOCKED by tool-policy.v1: "), result.stderr


def _use_current_policy(monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", ROOT)
    policy_registry._reset_cache_for_tests()
    assert policy_registry.load_policy() is not None


def test_every_role_admits_every_read_only_and_bookkeeping_tool(monkeypatch):
    _use_current_policy(monkeypatch)
    for role in policy_registry.load_policy()["roles"]:
        for tool in READ_ONLY_AND_BOOKKEEPING:
            assert policy_registry.is_allowed(role, tool, None) == (True, "ok"), (role, tool)


def test_the_set_holds_no_writing_running_network_or_dispatching_tool():
    assert not set(READ_ONLY_AND_BOOKKEEPING) & set(NEVER_IN_SET)


def test_the_lane_opens_no_network_or_mcp_tool(monkeypatch):
    # Context7, WebFetch and WebSearch are lane L23's, which grants them to dev and qa (owner decision,
    # hooks/tests/test_tool_policy_docs_and_web.py); this lane leaves graphify without them.
    _use_current_policy(monkeypatch)
    for role in ("graphify",):
        for tool in ("WebFetch", "WebSearch", "mcp__context7__resolve-library-id", "mcp__context7__query-docs"):
            allowed, reason = policy_registry.is_allowed(role, tool, None)
            assert not allowed and reason.endswith("not in allowed_tools"), (role, tool)
    allowed, reason = policy_registry.is_allowed("graphify", "Edit", None)
    assert not allowed and reason.endswith("not in allowed_tools")
