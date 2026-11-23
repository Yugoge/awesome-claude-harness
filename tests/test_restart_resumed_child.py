"""/restart judges a child by its LATEST run: the run started by the latest dispatch or message to it.

Constructed sessions: a child finishes its first run, is given new work by a message, and that second
run is cut (by a usage limit in the child's own record, or by the host's teardown). Its record still
holds the first run's end_turn and the first run's completed notification; neither may make it look
finished. A child whose latest run finished is not listed; a send a hook refused starts no run; a child
whose task was dispatched again afterwards stays unlisted.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hooks"))

from lib import subagent_restart as restart  # noqa: E402

SID = "0d0d0d0d-1111-4222-8333-555555555555"
AGENT = "agent-resumed"


def _ts(minute: int) -> str:
    return f"2026-01-05T10:{minute:02d}:00.000Z"


def _call(tool_id: str, prompt: str, minute: int, *, background: bool = False, name: str | None = None) -> dict:
    tool_input = {"subagent_type": "general-purpose", "description": prompt[:20], "prompt": prompt,
                  "run_in_background": background}
    if name:
        tool_input["name"] = name
    return {"type": "assistant", "timestamp": _ts(minute), "message": {"role": "assistant", "content": [{
        "type": "tool_use", "id": tool_id, "name": "Agent", "input": tool_input}]}}


def _result(tool_id: str, text: str, minute: int, *, cli: object = None, error: bool = False) -> dict:
    block = {"type": "tool_result", "tool_use_id": tool_id, "content": [{"type": "text", "text": text}]}
    if error:
        block["is_error"] = True
    return {"type": "user", "timestamp": _ts(minute), "toolUseResult": cli,
            "message": {"role": "user", "content": [block]}}


def _report(tool_id: str, agent: str, minute: int) -> dict:
    return _result(tool_id, f"Done.\nagentId: {agent} (use SendMessage with to: '{agent}' to continue)", minute,
                   cli={"status": "completed", "agentId": agent})


def _send(tool_id: str, to: str, minute: int) -> dict:
    return {"type": "assistant", "timestamp": _ts(minute), "message": {"role": "assistant", "content": [{
        "type": "tool_use", "id": tool_id, "name": "SendMessage",
        "input": {"to": to, "summary": "more work", "message": "Next: also do part two."}}]}}


def _sent(tool_id: str, minute: int) -> dict:
    return _result(tool_id, "Message sent; the agent resumes in the background.", minute,
                   cli={"success": True})


def _refused(tool_id: str, minute: int) -> dict:
    return _result(tool_id, "PreToolUse:SendMessage hook error: blocked", minute, error=True)


def _note(agent: str, status: str, minute: int) -> dict:
    return {"type": "user", "timestamp": _ts(minute), "message": {"role": "user", "content":
            f"<task-notification><task-id>{agent}</task-id><status>{status}</status><summary>x</summary>"
            "</task-notification>"}}


def _child_end(minute: int) -> dict:
    return {"type": "assistant", "timestamp": _ts(minute), "agentId": AGENT, "sessionId": SID,
            "message": {"role": "assistant", "content": [{"type": "text", "text": "report"}],
                        "stop_reason": "end_turn"}}


def _child_message(minute: int) -> dict:
    return {"type": "user", "timestamp": _ts(minute), "agentId": AGENT, "sessionId": SID, "origin": "message",
            "message": {"role": "user", "content": "The coordinator sent a message: Next: also do part two."}}


def _child_work(minute: int) -> dict:
    return {"type": "assistant", "timestamp": _ts(minute), "agentId": AGENT, "sessionId": SID,
            "message": {"role": "assistant", "content": [{"type": "text", "text": "working"}],
                        "stop_reason": "tool_use"}}


def _child_limit(minute: int) -> dict:
    return {"type": "assistant", "timestamp": _ts(minute), "agentId": AGENT, "sessionId": SID,
            "isApiErrorMessage": True, "error": "rate_limit", "apiErrorStatus": 429,
            "message": {"role": "assistant", "content": [{"type": "text", "text": "limit"}],
                        "stop_reason": "stop_sequence"}}


def _session(tmp_path: Path, parent: list[dict], child: list[dict], tool_id: str = "toolu_d") -> Path:
    transcript = tmp_path / "proj" / f"{SID}.jsonl"
    sub = transcript.with_suffix("") / "subagents"
    sub.mkdir(parents=True)
    transcript.write_text("".join(json.dumps(r) + "\n" for r in parent), encoding="utf-8")
    (sub / f"agent-{AGENT}.meta.json").write_text(json.dumps(
        {"agentType": "general-purpose", "description": "lane", "toolUseId": tool_id}), encoding="utf-8")
    (sub / f"agent-{AGENT}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in child), encoding="utf-8")
    return transcript


def _listed(transcript: Path) -> dict[str, list[str]]:
    return {c["agent_id"]: c["evidence"] for c in restart.discover_candidates(transcript)}


FINISHED_FIRST_RUN = [_call("toolu_d", "Lane D.", 1), _report("toolu_d", AGENT, 5)]


# 1. Established: finished, given new work by a message, the second run cut.
def test_a_finished_child_whose_resumed_run_hit_a_limit_is_listed(tmp_path: Path) -> None:
    t = _session(tmp_path, FINISHED_FIRST_RUN + [_send("toolu_s", AGENT, 6), _sent("toolu_s", 6)],
                 [_child_work(2), _child_end(4), _child_message(7), _child_work(8), _child_limit(9)])
    assert _listed(t) == {AGENT: ["quota_or_usage_limit_structural"]}


def test_a_background_child_whose_resumed_run_was_torn_down_is_listed(tmp_path: Path) -> None:
    parent = [_call("toolu_d", "Lane D.", 1, background=True),
              _result("toolu_d", f"Async agent launched successfully.\nagentId: {AGENT}", 1,
                      cli={"status": "async_launched", "agentId": AGENT}),
              _note(AGENT, "completed", 5),  # the first run came to rest
              _send("toolu_s", AGENT, 6), _sent("toolu_s", 6),
              _note(AGENT, "stopped", 9)]  # the host exited during the second run
    t = _session(tmp_path, parent, [_child_end(4), _child_message(7), _child_work(8)])
    assert _listed(t) == {AGENT: ["session_teardown_stop"]}


def test_a_message_by_the_childs_name_starts_its_latest_run(tmp_path: Path) -> None:
    parent = [_call("toolu_d", "Lane D.", 1, name="lane-d"), _report("toolu_d", AGENT, 5),
              _send("toolu_s", "lane-d", 6), _sent("toolu_s", 6)]
    t = _session(tmp_path, parent, [_child_end(4), _child_message(7), _child_limit(9)])
    assert AGENT in _listed(t)


def test_the_resume_of_a_listed_resumed_child_is_authorized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_RESTART_GRANT_DIR", str(tmp_path / "grants"))
    monkeypatch.setenv("CLAUDE_RESTART_STATE_DIR", str(tmp_path / "states"))
    t = _session(tmp_path, FINISHED_FIRST_RUN + [_send("toolu_s", AGENT, 6), _sent("toolu_s", 6)],
                 [_child_end(4), _child_message(7), _child_limit(9)])
    restart.mint_grant(SID, str(t), ttl_seconds=600)
    item = next(c for c in restart.prepare_state(SID)["candidates"] if c["agent_id"] == AGENT)
    assert restart.authorize_send_message({"session_id": SID, "tool_input": {
        "to": AGENT, "message": item["resume_message"]}}) == (True, "validated /restart recovery")


# 2. A latest run that finished is not listed; a send a hook refused starts no run.
def test_a_child_whose_resumed_run_finished_is_not_listed(tmp_path: Path) -> None:
    cut_first = [_call("toolu_d", "Lane D.", 1),
                 _result("toolu_d", f"You've hit your session limit · resets 3pm\nagentId: {AGENT}", 3,
                         cli={"status": "completed", "agentId": AGENT}),
                 _send("toolu_s", AGENT, 6), _sent("toolu_s", 6)]
    t = _session(tmp_path, cut_first, [_child_limit(2), _child_message(7), _child_work(8), _child_end(9)])
    assert _listed(t) == {}


def test_a_send_a_hook_refused_starts_no_run(tmp_path: Path) -> None:
    # the stopped notification after the refused send belongs to no new run: the first run's end_turn stands
    t = _session(tmp_path, FINISHED_FIRST_RUN + [_send("toolu_s", AGENT, 6), _refused("toolu_s", 6),
                                                 _note(AGENT, "stopped", 9)],
                 [_child_end(4)])
    assert _listed(t) == {}


def test_a_finished_child_given_no_message_is_not_listed(tmp_path: Path) -> None:
    t = _session(tmp_path, FINISHED_FIRST_RUN, [_child_limit(2), _child_end(4)])
    assert _listed(t) == {}


# 3. A child whose task was dispatched again after its resumed run was cut stays unlisted.
def test_a_resumed_child_whose_task_was_dispatched_again_is_not_listed(tmp_path: Path) -> None:
    parent = FINISHED_FIRST_RUN + [_send("toolu_s", AGENT, 6), _sent("toolu_s", 6),
                                   _call("toolu_e", "Lane D.", 12), _report("toolu_e", "agent-again", 15)]
    t = _session(tmp_path, parent, [_child_end(4), _child_message(7), _child_limit(9)])
    assert _listed(t) == {}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
