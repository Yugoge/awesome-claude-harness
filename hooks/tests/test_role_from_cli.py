"""P6 R1/R2: a subagent's role is what Claude Code records, through the hooks that read it.

The role is the payload's agent_type when it carries an agent_id, else the agentType of
the CLI's agent meta file, else the older registries (hooks/lib/agent_resolver.py); a
payload without agent_id is the main agent whatever agent_type says. A Read of a
dev-registry sentinel no longer writes a role into agent-index.json for such a payload
(hooks/pretool-cp-checkin.py), so a QA that reads dev's sentinel stays a QA.

Each case runs the real hook processes with the payload shape the prompt gives
(acceptance tests A3, A4, A5's role parts). Write targets lie under a project path
outside /tmp, which the policy denies for every role, and need not exist: the policy
decides on the path.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
TARGET = Path("/nonexistent-p6-role-from-cli") / "proj"
SID = "p6-role-from-cli"


def _env(tmp_path: Path, project: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update({"HOME": str(tmp_path / "home"), "CLAUDE_CONFIG_DIR": str(tmp_path / "home" / ".claude"),
                "CLAUDE_STATE_DIR": str(tmp_path / "state"), "CLAUDE_PROJECT_DIR": str(project),
                "PYTHONDONTWRITEBYTECODE": "1"})
    return env


def _hook(tmp_path: Path, project: Path, name: str, payload: dict) -> subprocess.CompletedProcess:
    payload = {"session_id": SID, "hook_event_name": "PreToolUse", "cwd": str(project), **payload}
    return subprocess.run([sys.executable, str(HOOKS / name)], input=json.dumps(payload), capture_output=True,
                          text=True, cwd=str(tmp_path), env=_env(tmp_path, project), timeout=60)


def _policy(tmp_path: Path, project: Path, agent: dict, tool: str, tool_input: dict) -> int:
    return _hook(tmp_path, project, "pretool-tool-policy.py",
                 {**agent, "tool_name": tool, "tool_input": tool_input}).returncode


def _edit(rel: str) -> dict:
    return {"file_path": str(TARGET / rel), "old_string": "x = 1", "new_string": "x = 2"}


@pytest.fixture
def project(tmp_path) -> Path:
    path = tmp_path / "toyproj"
    (path / ".claude" / "dev-registry").mkdir(parents=True)
    return path


def test_a3_a_qa_reading_devs_sentinel_stays_qa(tmp_path, project):
    """T2: {agent_id: a-qa2, agent_type: qa} Reads dev's absent sentinel: no index entry
    maps a-qa2 to dev and its Edit of src/app.py is refused (exit 2; 0 before P6, when
    the Read registered it as dev). An index entry an older hook wrote does not change it."""
    qa2 = {"agent_id": "a-qa2", "agent_type": "qa"}
    registry = project / ".claude" / "dev-registry" / "dev-X"
    registry.mkdir()
    read = _hook(tmp_path, project, "pretool-cp-checkin.py",
                 {**qa2, "tool_name": "Read", "tool_input": {"file_path": str(registry / "dev.json")}})
    assert read.returncode == 0, read.stderr
    index = project / ".claude" / "dev-registry" / "agent-index.json"
    assert not index.exists()
    assert (registry / "dev.json").is_file(), "the hook still creates the sentinel the read asks for"
    assert _policy(tmp_path, project, qa2, "Edit", _edit("src/app.py")) == 2
    index.write_text(json.dumps({"a-qa2": {"agent_type": "dev", "dev_session_id": "dev-X"}}))
    assert _policy(tmp_path, project, qa2, "Edit", _edit("src/app.py")) == 2


def test_a4_the_cli_role_decides_without_a_sentinel_read(tmp_path, project):
    """T1a: no sentinel Read; a QA's Edit of src/x.py is refused (exit 2; 0 before P6,
    an unregistered subagent), a dev's is allowed."""
    assert _policy(tmp_path, project, {"agent_id": "a-qa4", "agent_type": "qa"}, "Edit", _edit("src/x.py")) == 2
    assert _policy(tmp_path, project, {"agent_id": "a-dev4", "agent_type": "dev"}, "Edit", _edit("src/x.py")) == 0


def test_an_older_cli_role_comes_from_the_agent_meta(tmp_path, project):
    """No agent_type in the payload: the agentType of the meta file beside the session's
    transcript decides, as a payload role would."""
    sub = tmp_path / "transcripts" / SID / "subagents"
    sub.mkdir(parents=True)
    for agent_id, kind in (("a-meta-qa", "qa"), ("a-meta-dev", "dev")):
        (sub / f"agent-{agent_id}.meta.json").write_text(json.dumps({"agentType": kind, "toolUseId": "toolu_" + kind}))
    transcript = str(tmp_path / "transcripts" / f"{SID}.jsonl")
    assert _policy(tmp_path, project, {"agent_id": "a-meta-qa", "transcript_path": transcript},
                   "Edit", _edit("src/x.py")) == 2
    assert _policy(tmp_path, project, {"agent_id": "a-meta-dev", "transcript_path": transcript},
                   "Edit", _edit("src/x.py")) == 0


@pytest.mark.parametrize("role", ["Explore", "Plan", "demo-plugin:reviewer"])
def test_a5_roles_the_policy_does_not_list_keep_their_calls(tmp_path, project, role):
    """A built-in or plugin role the policy lists no row for keeps origin/master's
    outcome for ordinary calls (exit 0), now that the CLI names it."""
    agent = {"agent_id": "a-" + role.replace(":", "-").lower(), "agent_type": role}
    calls = [("Read", {"file_path": str(TARGET / "src" / "app.py")}), ("Grep", {"pattern": "x", "path": str(TARGET)}),
             ("Bash", {"command": "ls"}), ("Write", {"file_path": str(TARGET / "src" / "y.py"), "content": "y\n"})]
    assert [(tool, _policy(tmp_path, project, agent, tool, ti)) for tool, ti in calls] == [(t, 0) for t, _ in calls]


def test_a5_main_thread_agent_type_without_agent_id_is_the_main_agent(tmp_path, project):
    """Main thread, agent_type reviewer, no agent_id: the main agent's outcome, as with
    neither field."""
    write = {"file_path": str(TARGET / "docs" / "dev" / "do-report-20261012-000000.json"), "content": "{}"}
    assert _policy(tmp_path, project, {"agent_type": "reviewer"}, "Write", write) == \
        _policy(tmp_path, project, {}, "Write", write) == 0


def test_the_overnight_guard_takes_no_role_from_the_environment(monkeypatch):
    """The guard's self-repair role is the one role reader's: an environment variable
    names no role, the main agent has none."""
    spec = importlib.util.spec_from_file_location("overnight_guard_p6", HOOKS / "pretool-overnight-hook-guard.py")
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    monkeypatch.setenv("CLAUDE_AGENT_TYPE", "dev")
    assert guard._resolve_role({"agent_type": "dev"}) == ""
    assert guard._resolve_role({"agent_id": "a-guard", "agent_type": "qa"}) == "qa"
