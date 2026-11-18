"""The main agent's SendMessage policy (CLAUDE.md lesson 16, Orchestrator-Only Rule).

decide() is pretool-block-background-tasks.py's answer for a main-agent SendMessage;
record() is posttool-restart-sendmessage.py's journal of a send that was not a /restart one.

1. A /restart candidate (lib/subagent_restart state) gets subagent_restart.authorize_send_message's
   answer and nothing else: the exact recovery message, pending, under a live grant.
2. Any other target must be an agent id, or the `name` input, of an Agent call of this session's
   transcript whose result the CLI recorded. CLI 2.1.325 records it as the tool_result's
   toolUseResult {"status": "completed", "agentId": "<id>", ...} (an async launch:
   {"status": "async_launched", "agentId": ...}, completed by a later <task-notification> whose
   <task-id> is that id); the result text ends "agentId: <id> (use SendMessage with to: '<id>' ...".
   `main`, another session and the `name [ref]` form are no such target.
3. That child must have finished (a completed result or notification, no quota or interruption
   text: a cut child resumes only through /restart), carry no obligation block in its dispatch
   prompt (an obligation is the pipeline's to close, which this module does not read), and have
   been dispatched outside every span a gated command opened (lib/stop-commands.json).
   Steering a lane is refused rather than routed through the dispatch gate.
   A send resumes its child in the background (CLI 2.1.325: "Resuming agent ..."; the resumed run's end
   is a later <task-notification> carrying that send's tool use id), so a child an earlier send resumed
   counts as running again until a completion notification arrives after that send. Which sends ran and
   which child each resumed is the journal's: record() writes it, sends() is its one reader.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

try:  # package import (hooks.lib.send_policy) or lib/ on sys.path
    from . import command_span, subagent_restart as restart
    from .interruption_signals import is_interrupt_text, is_quota_text
except ImportError:  # pragma: no cover - direct sys.path import
    import command_span  # type: ignore[no-redef]
    import subagent_restart as restart  # type: ignore[no-redef]
    from interruption_signals import is_interrupt_text, is_quota_text  # type: ignore[no-redef]

OBLIGATION_TOKEN = "<obligation"
AGENT_TOOLS = ("Agent", "Task")


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text") or "" for b in content if isinstance(b, dict) and b.get("type") == "text") \
        if isinstance(content, list) else ""


def _cut(text: str) -> bool:
    return is_quota_text(text) or is_interrupt_text(text)


def children(transcript_path: Any, session_id: str = "") -> tuple[dict[str, dict], dict[str, str]]:
    """({agent id: child}, {name: agent id}) of the session's Agent calls whose result named an
    agent. A child: tool_use_id, name, command (the span its dispatch was issued in, or None),
    obligation (its prompt carries a block), finished (bool) and state (why). With the session id, a
    SendMessage the session's journal shows resumed a child marks it running from that call on, until
    a later task-notification for it says how the resumed run ended."""
    commands = command_span.harness_commands()
    resumed = {str(e["tool_use_id"]): e for e in (sends(session_id) if session_id else [])
               if isinstance(e.get("tool_use_id"), str) and e.get("success") is not False}
    calls: dict[str, dict] = {}
    kids: dict[str, dict] = {}
    names: dict[str, str] = {}
    current = None
    try:
        handle = open(transcript_path, encoding="utf-8", errors="replace")
    except (OSError, TypeError, ValueError):
        return kids, names
    with handle:
        for line in handle:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict) or record.get("isSidechain"):
                continue
            opener = command_span.span_opener(record, commands)
            if opener:
                current = opener[0]
                continue
            message = record.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            blocks = content if isinstance(content, list) else []
            if record.get("type") == "assistant":
                for b in blocks:
                    if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in AGENT_TOOLS \
                            and isinstance(b.get("input"), dict):
                        calls[str(b.get("id") or "")] = {"input": b["input"], "command": current}
                    elif isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "SendMessage" \
                            and str(b.get("id") or "") in resumed:
                        sent = resumed[str(b["id"])]
                        to, own = (x if isinstance(x, str) else "" for x in (sent.get("to"), sent.get("agent_id")))
                        agent = own if own in kids else names.get(to, to)
                        if agent in kids:
                            kids[agent].update(finished=False, state=f"resumed by SendMessage {b['id']}, "
                                               "no completion notification since")
                continue
            if record.get("type") != "user":
                continue
            for body in restart._iter_notification_blocks(_text(content)):
                found = restart.TASK_NOTIFICATION_RE.search(body)
                if found and found.group(1).strip() in kids:
                    done = found.group(2).lower() == "completed" and not _cut(found.group(3))
                    kids[found.group(1).strip()].update(
                        finished=done, state=f"notification status {found.group(2).lower()}"
                        + ("" if done or found.group(2).lower() != "completed" else " with a cut banner"))
            for b in blocks:
                call = calls.get(str(b.get("tool_use_id") or "")) if isinstance(b, dict) \
                    and b.get("type") == "tool_result" else None
                if call is None:
                    continue
                own = record.get("toolUseResult") if isinstance(record.get("toolUseResult"), dict) else {}
                text = _text(b.get("content"))
                found = restart.AGENT_ID_TEXT_RE.search(text)
                agent = own.get("agentId") if isinstance(own.get("agentId"), str) else (found.group(1) if found else None)
                if not agent:
                    continue
                status = own.get("status")
                done = not b.get("is_error") and status == "completed" and not _cut(text)
                state = "completed" if done else ("an error result" if b.get("is_error") else
                                                  f"result status {status or 'unrecorded'}"
                                                  + (" with a cut banner" if status == "completed" else ""))
                inp = call["input"]
                kids[agent] = {"agent_id": agent, "tool_use_id": b.get("tool_use_id"),
                               "name": inp.get("name") if isinstance(inp.get("name"), str) else None,
                               "command": call["command"], "finished": done, "state": state,
                               "obligation": OBLIGATION_TOKEN in str(inp.get("prompt") or "")}
                if kids[agent]["name"]:
                    names[kids[agent]["name"]] = agent
    return kids, names


def _target(payload: dict) -> Any:
    params = payload.get("tool_input") if "tool_input" in payload else payload.get("params")
    return params.get("to") if isinstance(params, dict) else None


def _session(payload: dict) -> str:
    return str(payload.get("session_id") or payload.get("sessionId") or os.environ.get("CLAUDE_SESSION_ID") or "")


def _candidate(session_id: str, agent_id: str) -> bool:
    try:
        state = restart._read_state(restart._safe_session_id(session_id))
    except restart.RestartError:
        return False
    return bool(state) and any(isinstance(c, dict) and c.get("agent_id") == agent_id
                               for c in state.get("candidates") or [])


def decide(payload: dict) -> tuple[bool, str]:
    """(allowed, why) for a main-agent SendMessage."""
    restart_ok, restart_reason = restart.authorize_send_message(payload)
    if restart_ok:
        return True, restart_reason
    to = _target(payload)
    sid = _session(payload)
    restart_note = f"\nRestart authorization: {restart_reason}"
    if isinstance(to, str) and _candidate(sid, to):
        return False, "the target is a /restart candidate, so only the exact recovery message reaches it" + restart_note
    if not isinstance(to, str) or not to or to == "main" or not restart.AGENT_RE.fullmatch(to):
        return False, (f"to={to!r} is not one of this session's own subagents (main, other sessions and the "
                       "'name [ref]' form are refused)" + restart_note)
    kids, names = children(payload.get("transcript_path"), sid)
    agent = to if to in kids else names.get(to)
    if agent is None:
        return False, (f"to={to!r} is no agent id or name an Agent result in this session's transcript returned"
                       + restart_note)
    if agent != to and _candidate(sid, agent):
        return False, "the target is a /restart candidate, so only the exact recovery message reaches it" + restart_note
    child = kids[agent]
    if child["obligation"]:
        return False, (f"{agent}'s dispatch carries an obligation block: work reaches a lane only through Agent "
                       "and the dispatch gate" + restart_note)
    if child["command"] in command_span.GATED_COMMANDS:
        return False, (f"{agent} was dispatched inside /{child['command']}: steering a gated command's lane is "
                       "refused" + restart_note)
    if not child["finished"]:
        return False, (f"{agent} has not finished ({child['state']}): a cut or running child resumes only "
                       "through /restart" + restart_note)
    return True, f"own finished subagent {agent}"


def journal_path(session_id: str) -> Path:
    return restart.state_dir() / "sends" / f"{restart._safe_session_id(session_id)}.jsonl"


def sends(session_id: str) -> list[dict]:
    """The session's journal, oldest first: the lines record() wrote, [] when it has none (or the
    session id is not a valid one). The journal's one reader; a torn or foreign line is skipped."""
    try:
        path = journal_path(session_id)
    except restart.RestartError:
        return []
    try:
        handle = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return []
    entries = []
    with handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
    return entries


def record(payload: dict) -> dict | None:
    """Append one journal line for a SendMessage that was not a /restart send; the line, or None
    when the payload names no valid session (nothing written)."""
    params = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    response = payload.get("tool_response") if isinstance(payload.get("tool_response"), dict) else {}
    message = params.get("message")
    raw = message if isinstance(message, str) else json.dumps(message, sort_keys=True)
    try:
        path = journal_path(_session(payload))
    except restart.RestartError:
        return None
    pin = response.get("pin") if isinstance(response.get("pin"), dict) else {}
    entry = {
        "at": restart._iso(),
        "session_id": _session(payload),
        "sender": payload.get("agent_id") or payload.get("agentId") or "main",
        "to": params.get("to"),
        "agent_id": response.get("resumedAgentId") or pin.get("id"),
        "tool_use_id": payload.get("tool_use_id"),
        "summary": params.get("summary"),
        "message_sha256": hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest(),
        "message_chars": len(raw),
        "success": response.get("success"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry

