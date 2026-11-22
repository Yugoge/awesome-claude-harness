#!/usr/bin/env python3
"""PostToolUse (Agent): one process for what a returned dispatch records and checks.

The rules run in this order, each as its own hook would run alone
(hooks/lib/gate_runner.py):

1. posttool-subagent-track.py: on the PM TRIAGE return, the cycle contract's one
   writer;
2. posttool-overnight-file-check.py: the returned producer's artifacts against the
   cycle contract (exit 2 returns the finding to the agent);
3. posttool-overnight-trace.py: a specialist report's yield;
4. lib/dev_loop_checks.py advice(), advice only: for a returned dev dispatch, the
   layer match, guard integrity and minimum diff checks of the task its obligation
   names, as additionalContext; it never refuses.

The contract is written before the two rules that read it, so neither reads it half
way through a write or before it exists on the same return, as they did when the
three ran side by side.

A background launch (its result's status is async_launched) has not returned: at
the launch only the dispatch-temp rule runs. The rules run at the agent's end
instead, for every role and in every command, /dev-overnight included (AT_RETURN): the producer stop gate (hooks/subagentstop-producer-gate.py) runs this file
as its last rule, a witness, so only on the stop its rules let stand; with that
SubagentStop payload this file finds the agent's background launch in the main
transcript and runs the four rules on the Agent call's PostToolUse as it would have
been at a foreground return (its response: the agent's last reply). An agent whose
launch was not a background one of the main session runs nothing here.
"""
from __future__ import annotations
import os, sys  # noqa: E401 -- the harness switch (hooks/lib/harness_switch.py): no harness hook runs while /harness off holds
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))
try:  # a hook copied without its lib/ (an old install) is on
    import harness_switch  # noqa: E402
    harness_switch.exit_if_off()
except ImportError:
    pass
finally:
    sys.path.pop(0)

import io
import json
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parent
sys.path.insert(0, str(HOOKS))

from lib.gate_runner import ADVISE, OBSERVE, REFUSE, Rule, evaluate, main  # noqa: E402

RULES = [
    Rule("cycle-contract-writer", str(HOOKS / "posttool-subagent-track.py"), OBSERVE),
    Rule("overnight-file-check", str(HOOKS / "posttool-overnight-file-check.py"), REFUSE),
    Rule("overnight-trace", str(HOOKS / "posttool-overnight-trace.py"), OBSERVE),
    Rule("dev-loop-after", call="lib.dev_loop_checks:advice", kind=ADVISE),
    Rule("dispatch-temp", call="lib.dispatch_temp:returned", kind=OBSERVE),  # its temp directory goes
]
# at the agent's end: all five, dispatch-temp's end of the background run included, and the score log's sweep,
# which hooks/posttool-close-rating.py runs at a foreground return
AT_RETURN = [*RULES, Rule("score-events", call="lib.score_events:observe", kind=OBSERVE)]


def _launch(transcript, agent: str):
    """(tool_use_id, input, tool name) of the main session's dispatch whose result launched ``agent``
    in the background (the CLI's own toolUseResult: isAsync, agentId), or None."""
    ident = None
    try:
        with open(transcript, encoding="utf-8") as handle:
            lines = handle.readlines()
        records = [json.loads(line) for line in lines if agent in line]
    except (OSError, TypeError, ValueError):
        return None
    for rec in records:
        use = None if rec.get("isSidechain") else rec.get("toolUseResult")
        content = (rec.get("message") or {}).get("content")
        if isinstance(use, dict) and use.get("isAsync") is True and use.get("agentId") == agent and isinstance(content, list):
            ident = next((b.get("tool_use_id") for b in content if isinstance(b, dict) and b.get("type") == "tool_result"), None)
    for rec in (json.loads(line) for line in lines if ident and f'"{ident}"' in line):
        content = (rec.get("message") or {}).get("content")
        for block in content if isinstance(content, list) else ():
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id") == ident:
                return ident, block.get("input") or {}, block.get("name") or "Agent"
    return None


def at_end(stop: dict) -> bytes | None:
    """The PostToolUse payload of the background launch of the agent whose SubagentStop ``stop`` is, as
    its return; None when the main session did not launch that agent in the background."""
    agent, transcript = str(stop.get("agent_id") or ""), stop.get("transcript_path")
    found = _launch(transcript, agent) if agent and transcript else None
    if not found:
        return None
    ident, tool_input, name = found
    reply = str(stop.get("last_assistant_message") or "")
    return json.dumps({
        "session_id": stop.get("session_id"), "transcript_path": transcript, "cwd": stop.get("cwd"),
        "hook_event_name": "PostToolUse", "tool_name": name, "tool_use_id": ident, "tool_input": tool_input,
        "tool_response": {"status": "completed", "agentId": agent, "content": [{"type": "text", "text": reply}]},
    }).encode()


def rules_for(raw: bytes) -> tuple:
    """(the rules this event runs, the payload they read)."""
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = None
    if isinstance(payload, dict) and payload.get("hook_event_name") == "SubagentStop":
        ended = at_end(payload)
        return (AT_RETURN, ended) if ended else ([], raw)
    response = payload.get("tool_response") if isinstance(payload, dict) else None
    if isinstance(response, dict) and response.get("status") == "async_launched":
        return RULES[4:], raw  # not returned yet: only its temp directory's record
    return RULES, raw


if __name__ == "__main__":
    event = sys.stdin.buffer.read()
    rules, raw = rules_for(event)
    if raw is not event:  # at an agent's end: the checks run; what reaches the orchestrator is not this stop's
        evaluate(rules, raw)
        sys.exit(0)
    sys.stdin = io.TextIOWrapper(io.BytesIO(raw))
    sys.exit(main(rules))
