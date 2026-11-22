"""One definition of a session's own subagents, read by /restart's listing and the message rule.

Constructed sessions: a foreground dispatch cut by the owner's interrupt (its result names no child),
a finished child, a child cut by a usage limit, a child stopped by the orchestrator (TaskStop), a cut
child whose task was dispatched again (same prompt, or same lane of a gated command), and a foreign
agent id (named only in a report's prose or in nothing of this session).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hooks"))

from lib import send_policy, subagent_restart as restart  # noqa: E402

SID = "0c0c0c0c-1111-4222-8333-444444444444"
INTERRUPT = ("The user doesn't want to proceed with this tool use. The tool use was rejected. "
             "Correction to the text above: this call was stopped while running, not rejected.")
LIMIT = "You've hit your session limit · resets 3pm"


def _call(tool_id: str, prompt: str, *, background: bool = False) -> dict:
    return {"type": "assistant", "message": {"role": "assistant", "content": [{
        "type": "tool_use", "id": tool_id, "name": "Agent",
        "input": {"subagent_type": "general-purpose", "description": prompt[:20], "prompt": prompt,
                  "run_in_background": background}}]}}


def _result(tool_id: str, text: str, *, cli: object, error: bool = False) -> dict:
    return {"type": "user", "toolUseResult": cli, "message": {"role": "user", "content": [{
        "type": "tool_result", "tool_use_id": tool_id, "is_error": error,
        "content": [{"type": "text", "text": text}]}]}}


def _report(tool_id: str, agent: str, text: str = "Done.") -> dict:
    return _result(tool_id, f"{text}\nagentId: {agent} (use SendMessage with to: '{agent}' to continue)",
                   cli={"status": "completed", "agentId": agent})


def _note(agent: str, status: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content":
            f"<task-notification><task-id>{agent}</task-id><status>{status}</status><summary>x</summary>"
            "</task-notification>"}}


def _session(tmp_path: Path, records: list[dict], children: dict[str, tuple[str, bool]]) -> Path:
    """The parent record, plus for each child {agent: (tool_use_id, finished)} the CLI's meta.json
    and child record."""
    transcript = tmp_path / "proj" / f"{SID}.jsonl"
    sub = transcript.with_suffix("") / "subagents"
    sub.mkdir(parents=True)
    transcript.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    for agent, (tool_id, finished) in children.items():
        (sub / f"agent-{agent}.meta.json").write_text(json.dumps(
            {"agentType": "general-purpose", "description": "lane", "toolUseId": tool_id}), encoding="utf-8")
        last = {"role": "assistant", "content": [{"type": "text", "text": "report" if finished else "working"}],
                "stop_reason": "end_turn" if finished else "tool_use"}
        (sub / f"agent-{agent}.jsonl").write_text(json.dumps(
            {"type": "assistant", "agentId": agent, "sessionId": SID, "message": last}) + "\n", encoding="utf-8")
    return transcript


def _listed(transcript: Path) -> list[str]:
    return [c["agent_id"] for c in restart.discover_candidates(transcript)]


def _send(transcript: Path, to: str) -> tuple[bool, str]:
    return send_policy.decide({"session_id": SID, "transcript_path": str(transcript), "tool_name": "SendMessage",
                               "tool_use_id": "toolu_send", "hook_event_name": "PreToolUse",
                               "tool_input": {"to": to, "summary": "resume", "message": "Resume and finish."}})


def test_a_foreground_dispatch_cut_by_the_interrupt_is_listed_and_own(tmp_path: Path) -> None:
    t = _session(tmp_path, [_call("toolu_a", "Lane A."),
                            _result("toolu_a", INTERRUPT, cli="User rejected tool use", error=True)],
                 {"agent-cut": ("toolu_a", False)})
    assert _listed(t) == ["agent-cut"]
    assert restart.discover_candidates(t)[0]["evidence"] == ["dispatch_returned_no_report"]
    assert "agent-cut" in send_policy.children(t)[0]
    ok, why = _send(t, "agent-cut")
    assert ok and "own subagent agent-cut" in why


def test_a_finished_child_is_own_and_never_listed(tmp_path: Path) -> None:
    t = _session(tmp_path, [_call("toolu_f", "Lane F."), _report("toolu_f", "agent-done")],
                 {"agent-done": ("toolu_f", True)})
    assert _listed(t) == []
    assert "agent-done" in send_policy.children(t)[0]
    ok, why = _send(t, "agent-done")
    assert ok and "own subagent agent-done" in why


def test_a_child_cut_by_a_limit_is_listed(tmp_path: Path) -> None:
    t = _session(tmp_path, [_call("toolu_q", "Lane Q."),
                            _result("toolu_q", f"{LIMIT}\nagentId: agent-quota", cli={"status": "completed",
                                                                                      "agentId": "agent-quota"})],
                 {"agent-quota": ("toolu_q", False)})
    assert _listed(t) == ["agent-quota"]


def test_a_background_child_stopped_by_the_orchestrator_is_listed(tmp_path: Path) -> None:
    t = _session(tmp_path, [_call("toolu_k", "Lane K.", background=True),
                            _result("toolu_k", "Async agent launched successfully.\nagentId: agent-killed",
                                    cli={"status": "async_launched", "agentId": "agent-killed"}),
                            _note("agent-killed", "killed")],
                 {"agent-killed": ("toolu_k", False)})
    assert _listed(t) == ["agent-killed"]
    assert restart.discover_candidates(t)[0]["evidence"] == ["stopped_by_orchestrator"]


def test_a_cut_child_dispatched_again_with_the_same_prompt_is_not_listed(tmp_path: Path) -> None:
    cut = _result("toolu_1", INTERRUPT, cli="User rejected tool use", error=True)
    t = _session(tmp_path, [_call("toolu_1", "Lane R."), cut, _call("toolu_2", "Lane R."), _report("toolu_2", "agent-new")],
                 {"agent-old": ("toolu_1", False), "agent-new": ("toolu_2", True)})
    assert _listed(t) == []
    # the replacement cut as well: only the latest is listed
    t2 = _session(tmp_path / "b", [_call("toolu_1", "Lane R."), cut, _call("toolu_2", "Lane R."),
                                   _result("toolu_2", INTERRUPT, cli="User rejected tool use", error=True)],
                  {"agent-old": ("toolu_1", False), "agent-new": ("toolu_2", False)})
    assert _listed(t2) == ["agent-new"]


def test_a_cut_lane_of_a_gated_command_dispatched_again_is_not_listed(tmp_path: Path) -> None:
    def block(text: str) -> str:
        doc = {"task_id": "dev-1", "lane": "L1", "role": "dev"}
        return f'{text}\n<obligation v="1">\n{json.dumps(doc)}\n</obligation>'
    cut = _result("toolu_1", INTERRUPT, cli="User rejected tool use", error=True)
    t = _session(tmp_path, [_call("toolu_1", block("First wording.")), cut,
                            _call("toolu_2", block("Second wording.")), _report("toolu_2", "agent-new")],
                 {"agent-old": ("toolu_1", False), "agent-new": ("toolu_2", True)})
    assert _listed(t) == []


def test_a_foreign_agent_id_is_never_own(tmp_path: Path) -> None:
    # a finished child whose report quotes another agent's id; the CLI's own trailer comes last
    t = _session(tmp_path, [_call("toolu_f", "Lane F."),
                            _result("toolu_f", "I read agentId: agent-foreign in a log.\nagentId: agent-done",
                                    cli="text only"),
                            _call("toolu_x", "Lane X."),
                            _result("toolu_x", INTERRUPT, cli="User rejected tool use", error=True)],
                 {"agent-done": ("toolu_f", True)})
    # a meta.json naming no call of this session (toolu_other) makes nothing own
    sub = t.with_suffix("") / "subagents"
    (sub / "agent-agent-forged.meta.json").write_text(json.dumps({"toolUseId": "toolu_other"}), encoding="utf-8")
    kids, _names = send_policy.children(t)
    assert set(kids) == {"agent-done"}
    assert _listed(t) == []
    ok, why = _send(t, "agent-foreign")
    assert ok and "not one of this session's own subagents" in why


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
