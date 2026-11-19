"""A specialist without Edit repairs its own declared report, and nothing else opens (audit C2).

/dev-overnight Step 3 (commands/dev-overnight.md, the specialist template) dispatches architect,
product-owner and user with an obligation that declares docs/dev/overnight/<session>/<type>-report.json;
G2 returns a faulty first version to the subagent. Their rows list Write but no Edit, and the overwrite
guard refuses a second Write of an existing file, so the repair had no permitted means. Their rows'
declared_artifact_tools grants Edit on a path the caller's own dispatch declares, and nowhere else.

The tool-policy cases run the registered write gate (hooks/pretool-write-gate.py) on a project that is
never created (tool-policy denies every role a write under /tmp, where tmp_path lives); the overwrite
case runs the guard's rule on a real file.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "hooks" / "pretool-write-gate.py"
OVERWRITE = ROOT / "hooks" / "lib" / "write_gate" / "overwrite.py"
_spec = importlib.util.spec_from_file_location(
    "derived_permission_helpers", Path(__file__).with_name("test_tool_policy_derived_permission.py"))
_dp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dp)
Session, PROJECT, BLOCK = _dp.Session, _dp.PROJECT, _dp.BLOCK

TS = "20261119-010203"
OVERNIGHT = "docs/dev/overnight/sess-night"
SPECIALISTS = ("architect", "product-owner", "user")


def _report(role: str) -> str:
    return f"{OVERNIGHT}/{role}-report.json"


def _obligation(role: str) -> str:
    doc = {"task_id": TS, "lane": None, "lane_set": None, "role": role, "pipeline": "dev-overnight",
           "profile": "overnight", "dispatched_at": "2026-11-19T01:02:03Z",
           "artifacts": [{"kind": "json", "path": _report(role), "schema": "specialist-report.v1",
                          "identity": {"task_id": TS}}]}
    return f'<obligation v="1">\n{json.dumps(doc)}\n</obligation>'


@pytest.fixture()
def night(tmp_path):
    """An exploration cycle's specialist dispatches and a dev dispatch."""
    s = Session(tmp_path / "projects")
    s.command("dev-overnight")
    s.agents = {role: s.dispatch(f"You are the {role} specialist.\n" + _obligation(role), role)
                for role in SPECIALISTS + ("ui-specialist",)}
    s.agents["dev"] = s.dispatch("You are the dev subagent.", "dev")
    return s


def _gate(s: Session, tmp_path: Path, tool: str, tool_input: dict, role: str | None):
    payload = {"session_id": s.sid, "transcript_path": str(s.transcript), "cwd": str(PROJECT),
               "hook_event_name": "PreToolUse", "permission_mode": "default", "tool_name": tool,
               "tool_input": tool_input, "tool_use_id": "toolu_" + uuid.uuid4().hex[:24]}
    if role:
        payload.update(agent_id=s.agents[role], agent_type=role, subagent_type=role)
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_"))}
    env.update({"HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
                "CLAUDE_STATE_DIR": str(tmp_path / "state"), "CLAUDE_PROJECT_DIR": str(PROJECT),
                "PYTHONDONTWRITEBYTECODE": "1"})
    proc = subprocess.run([sys.executable, str(GATE)], input=json.dumps(payload), capture_output=True,
                          text=True, cwd=str(tmp_path), env=env, timeout=60)
    assert not PROJECT.parent.exists(), "the gate must not create the project"
    return proc


def _edit(path: str) -> dict:
    return {"file_path": str(PROJECT / path), "old_string": '"issues": [', "new_string": '"issues": [ '}


def _denial(proc) -> dict:
    assert proc.returncode == 2, proc.stdout + proc.stderr
    line = next(ln for ln in proc.stderr.splitlines() if ln.startswith(BLOCK))
    return json.loads(line[len(BLOCK):])


@pytest.mark.parametrize("role", SPECIALISTS)
def test_a_specialist_edits_its_own_declared_report(tmp_path, night, role):
    proc = _gate(night, tmp_path, "Edit", _edit(_report(role)), role)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert '"deny"' not in proc.stdout, proc.stdout


@pytest.mark.parametrize("role", SPECIALISTS)
def test_the_specialist_edits_nothing_else(tmp_path, night, role):
    for path in (f"{OVERNIGHT}/notes.md", "docs/codex/notes.md"):
        assert _denial(_gate(night, tmp_path, "Edit", _edit(path), role))["deny_reason"] == \
            "tool Edit not in allowed_tools", path
    other = next(r for r in SPECIALISTS if r != role)
    assert _denial(_gate(night, tmp_path, "Edit", _edit(_report(other)), role))["deny_reason"].endswith(
        f"; only {other} writes this artifact (D8)")
    multi = {"file_path": str(PROJECT / _report(role)), "edits": [{"old_string": "a", "new_string": "b"}]}
    assert _denial(_gate(night, tmp_path, "MultiEdit", multi, role))["deny_reason"] == \
        "tool MultiEdit not in allowed_tools"


@pytest.mark.parametrize("caller", [None, "dev", "ui-specialist", "product-owner"])
@pytest.mark.parametrize("tool", ["Edit", "Write"])
def test_no_other_caller_changes_the_report(tmp_path, night, caller, tool):
    target = _report("architect")
    tool_input = _edit(target) if tool == "Edit" else {"file_path": str(PROJECT / target), "content": "{}"}
    denial = _denial(_gate(night, tmp_path, tool, tool_input, caller))
    assert denial["deny_reason"].endswith("; only architect writes this artifact (D8)"), denial


@pytest.mark.parametrize("role", SPECIALISTS)
def test_the_overwrite_guard_still_refuses_a_second_write_of_the_report(tmp_path, role):
    proj = tmp_path / "proj"
    subprocess.run(["git", "init", "-q", str(proj)], check=True)
    report = proj / _report(role)
    report.parent.mkdir(parents=True)
    report.write_text('{"issues": []}\n')
    payload = {"tool_name": "Write", "session_id": "sess-night", "hook_event_name": "PreToolUse",
               "agent_id": "a-" + role, "agent_type": role,
               "tool_input": {"file_path": str(report), "content": '{"issues": [], "task_id": "x"}\n'}}
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_"))}
    env.update(HOME=str(tmp_path / "home"), CLAUDE_STATE_DIR=str(tmp_path / "state"),
               CLAUDE_PROJECT_DIR=str(proj), PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run([sys.executable, str(OVERWRITE)], input=json.dumps(payload), capture_output=True,
                          text=True, env=env, cwd=str(proj), timeout=60)
    assert proc.returncode == 2 and "[Write Guard] BLOCKED: File already exists" in proc.stderr, proc.stderr
