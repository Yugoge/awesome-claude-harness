"""The main agent's SendMessage policy (CLAUDE.md lesson 16, the owner's ruling of 2026-11-21).

decide() is pretool-block-background-tasks.py's answer for a main-agent SendMessage;
record() is posttool-restart-sendmessage.py's journal of a send that was not a /restart one.

1. A send to anything but one of this session's own subagents (another session, `main`) is allowed:
   the receiving session is a full session, and its own harness handles what arrives.
2. A send to an own subagent (its agent id or `name`, by subagent_restart.own_children, the one
   definition /restart's listing reads too) is a dispatch of that subagent's type with the message as its prompt: it passes the
   dispatch gate (pretool-dispatch-gate.py) exactly as that dispatch would, whatever the child's
   state (running, finished, cut). Its next stop is judged by the message's declaration
   (obligation.latest_send). One exception: the recovery's own resume message
   (subagent_restart.is_resume_message, text fixed by code) adds no work, so it passes on the
   child's original dispatch, which that gate already admitted.
3. What enforces the owner's /stop stays: in a turn the overnight wake opened after the owner's
   /stop (overnight.wake_fired is false for it), no send is allowed.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

try:  # package import (hooks.lib.send_policy) or lib/ on sys.path
    from . import command_span, overnight, subagent_restart as restart
except ImportError:  # pragma: no cover - direct sys.path import
    import command_span  # type: ignore[no-redef]
    import overnight  # type: ignore[no-redef]
    import subagent_restart as restart  # type: ignore[no-redef]

DISPATCH_GATE = Path(__file__).resolve().parents[1] / "pretool-dispatch-gate.py"
GATE_TIMEOUT = 55  # seconds; within the launcher's 60 s for this hook


def children(transcript_path: Any) -> tuple[dict[str, dict], dict[str, str]]:
    """({agent id: child}, {name: agent id}) of the session's own subagents, as
    subagent_restart.own_children defines them (one definition for every reader). A child:
    agent_id, tool_use_id, name, subagent_type, prompt (its dispatch's)."""
    kids: dict[str, dict] = {}
    names: dict[str, str] = {}
    try:
        own = restart.own_children(Path(transcript_path))
    except (restart.RestartError, OSError, TypeError, ValueError):
        return kids, names
    for child in own:
        kids[child["agent_id"]] = {key: child[key] for key in ("agent_id", "tool_use_id", "name", "subagent_type", "prompt")}
        if child["name"]:
            names[child["name"]] = child["agent_id"]
    return kids, names


def _target(payload: dict) -> Any:
    params = payload.get("tool_input") if "tool_input" in payload else payload.get("params")
    return params.get("to") if isinstance(params, dict) else None


def _session(payload: dict) -> str:
    return str(payload.get("session_id") or payload.get("sessionId") or os.environ.get("CLAUDE_SESSION_ID") or "")


def _stopped_wake(transcript_path: Any) -> bool:
    """The turn's prompt is the overnight wake's and the wake did not fire: the owner's /stop came first."""
    last = None
    try:
        handle = open(transcript_path, encoding="utf-8", errors="replace")
    except (OSError, TypeError, ValueError):
        return False
    with handle:
        for line in handle:
            if '"user"' not in line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            content = (record.get("message") or {}).get("content") if isinstance(record, dict) else None
            text = command_span.prompt_text(record)
            if text is not None:
                last = text
            elif isinstance(content, str) and content.strip() == overnight.WAKE_PROMPT and not record.get("isSidechain"):
                last = content
    return isinstance(last, str) and last.strip() == overnight.WAKE_PROMPT \
        and not overnight.wake_fired(last, transcript_path)


def as_dispatch(payload: dict, child: dict) -> dict:
    """The Agent payload a send to ``child`` is judged as: its type, the message as the prompt."""
    params = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    message = params.get("message")
    tool_input = {"subagent_type": child["subagent_type"], "description": params.get("summary") or "",
                  "prompt": message if isinstance(message, str) else json.dumps(message),
                  "run_in_background": False}
    if child["name"]:
        tool_input["name"] = child["name"]
    return {**payload, "tool_name": "Agent", "tool_input": tool_input}


def decide(payload: dict) -> tuple[bool, str]:
    """(allowed, why) for a main-agent SendMessage."""
    transcript = payload.get("transcript_path")
    if _stopped_wake(transcript):
        return False, "this turn is the overnight wake after the owner's /stop: no send resumes the run"
    to = _target(payload)
    kids, names = children(transcript)
    key = to.split(" [", 1)[0] if isinstance(to, str) else ""
    agent = key if key in kids else names.get(key)
    if agent is None:
        return True, f"to={to!r} is not one of this session's own subagents: the receiving session decides"
    child = kids[agent]
    params = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    if restart.is_resume_message(_session(payload), child, params.get("message")):
        return True, (f"own subagent {agent}: the recovery's resume message adds no work; the child goes on "
                      "under its original dispatch, which the dispatch gate admitted when it ran")
    try:
        run = subprocess.run([sys.executable, str(DISPATCH_GATE)], input=json.dumps(as_dispatch(payload, child)),
                             capture_output=True, text=True, timeout=GATE_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"the dispatch gate could not judge this send to {agent}: {exc}"
    if run.returncode == 2:
        return False, (f"a send to own subagent {agent} is a dispatch of {child['subagent_type']}, and the "
                       f"dispatch gate refuses that dispatch:\n{run.stderr.strip()}")
    return True, f"own subagent {agent}: admitted as a dispatch"


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

