"""A SendMessage to one of the session's own subagents counts, for the orchestrator's call limits, as a
dispatch does (hooks/pretool-orchestrator-gate.py; the owner's ruling that such a send IS a dispatch).

- It is not counted against the one-call-per-tool-name-per-turn budget: rework to three subagents in
  one turn passes.
- The resumed subagent runs in the background, and a background launch resets nothing (the owner's
  decision of 2026-11-21): the sends leave Bash's count and every other tool's count as they were.
- A send to anything that is not an own subagent (another session's agent id) keeps the budget of one.

"Own" is lib/send_policy.children (subagent_restart.own_children): an Agent call of the transcript
that ran, its child named by the CLI's result. Each hook runs as a subprocess with throwaway HOME,
state and temp directories.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "hooks" / "pretool-orchestrator-gate.py"
KIDS = ("a1111111111111111", "a2222222222222222", "a3333333333333333")
FOREIGN = "a9999999999999999"
LIMITED = "used consecutively beyond limit"


def _dispatch(tool_id: str, name: str) -> dict:
    return {"type": "assistant", "isSidechain": False, "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": tool_id, "name": "Agent", "caller": {"type": "direct"},
         "input": {"subagent_type": "general-purpose", "description": name, "name": name,
                   "run_in_background": False, "prompt": f"Do lane {name}."}}]}}


def _returned(tool_id: str, agent: str) -> dict:
    return {"type": "user", "isSidechain": False,
            "toolUseResult": {"status": "completed", "agentId": agent, "agentType": "general-purpose"},
            "message": {"role": "user", "content": [{"tool_use_id": tool_id, "type": "tool_result", "is_error": False,
                                                     "content": [{"type": "text", "text": f"done\nagentId: {agent}"}]}]}}


@pytest.fixture()
def session(tmp_path: Path):
    sid = str(uuid.uuid4())
    transcript = tmp_path / f"{sid}.jsonl"
    records = [{"type": "user", "isSidechain": False, "origin": {"kind": "human"},
                "message": {"role": "user", "content": "run the three lanes"}}]
    for n, agent in enumerate(KIDS):
        records += [_dispatch(f"toolu_{n}", f"lane{n}"), _returned(f"toolu_{n}", agent)]
    transcript.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    (tmp_path / "state").mkdir()
    (tmp_path / "project").mkdir()
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path / "home"), "CLAUDE_STATE_DIR": str(tmp_path / "state"),
           "CLAUDE_RESTART_GRANT_DIR": str(tmp_path / "grants"), "CLAUDE_RESTART_STATE_DIR": str(tmp_path / "restart"),
           "TMPDIR": str(tmp_path), "CLAUDE_PROJECT_DIR": str(tmp_path / "project"), "PYTHONDONTWRITEBYTECODE": "1"}

    def run(tool: str, tool_input: dict) -> subprocess.CompletedProcess:
        payload = {"tool_name": tool, "tool_input": tool_input, "session_id": sid, "transcript_path": str(transcript),
                   "cwd": str(tmp_path / "project"), "tool_use_id": f"toolu_{uuid.uuid4().hex[:12]}"}
        return subprocess.run([sys.executable, str(GATE)], input=json.dumps(payload), text=True,
                              capture_output=True, env=env, cwd=str(ROOT), check=False)
    return run


def _send(to: str) -> dict:
    return {"to": to, "summary": "rework", "message": "QA rejected: fix the failing case."}


def test_three_sends_to_three_own_subagents_in_one_turn_pass(session):
    for to in KIDS[:2] + ("lane2",):  # by agent id and by name
        p = session("SendMessage", _send(to))
        assert p.returncode == 0, p.stderr
    again = session("SendMessage", _send(KIDS[0]))  # rework a second time, same turn
    assert again.returncode == 0, again.stderr


def test_a_send_to_a_foreign_agent_id_keeps_the_budget_of_one(session):
    assert session("SendMessage", _send(KIDS[0])).returncode == 0
    assert session("SendMessage", _send(FOREIGN)).returncode == 0
    second = session("SendMessage", _send(FOREIGN))
    assert second.returncode == 2 and LIMITED in second.stderr, second.stderr


def test_sends_reset_nothing_other_limited_tools_stay_limited(session, tmp_path):
    for n in range(5):
        assert session("Bash", {"command": f"python3 -c 'print({n})'"}).returncode == 0
    target = tmp_path / "project" / "notes.txt"
    assert session("Edit", {"file_path": str(target), "old_string": "a", "new_string": "b"}).returncode == 0
    for to in KIDS:
        assert session("SendMessage", _send(to)).returncode == 0
    edit = session("Edit", {"file_path": str(target), "old_string": "b", "new_string": "c"})
    assert edit.returncode == 2 and LIMITED in edit.stderr, edit.stderr
    bash = session("Bash", {"command": "python3 -c 'print(6)'"})
    assert bash.returncode == 2 and LIMITED in bash.stderr, bash.stderr
