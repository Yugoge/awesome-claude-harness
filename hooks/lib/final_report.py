"""The final report a stopping subagent delivered, for the SubagentStop rules that read it.

final_report() is the SubagentHandback message of the agent's latest run, else last_assistant_message;
handback_message() reads that message from the agent's own transcript.

A subagent reports in one of two ways. Most write it as their last reply, which the
SubagentStop payload carries as ``last_assistant_message``. In auto mode a subagent
instead calls the SubagentHandback tool: the report is that call's ``input.message``,
the call is the agent's last assistant record, and the payload has no
``last_assistant_message`` at all (measured on Claude Code 2.1.326, also when the
model wrote text before the call: that text is a record of its own, not the last
one). The call and its tool_result are in the agent's own transcript
(``agent_transcript_path``) when SubagentStop runs.

:func:`final_report` returns the handback message when this run of the agent
delivered one, else the payload's ``last_assistant_message`` unchanged (absent stays
None), so a reader that refused a missing reply before refuses it still.
Stdlib-only; never raises.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Optional

HANDBACK_TOOL = "SubagentHandback"

_USER = re.compile(rb'"type":\s*"user"')


def _blocks(record: Mapping[str, Any]) -> list:
    message = record.get("message")
    content = message.get("content") if isinstance(message, Mapping) else None
    return [b for b in content if isinstance(b, Mapping)] if isinstance(content, list) else []


def _starts_run(record: Mapping[str, Any]) -> bool:
    """A prompt to the agent (its dispatch, or a message that resumed it), not a tool result
    or a harness reminder: the records after it are this run's."""
    if record.get("type") != "user" or record.get("isMeta") is True:
        return False
    message = record.get("message")
    content = message.get("content") if isinstance(message, Mapping) else None
    if isinstance(content, str):
        return True
    return isinstance(content, list) and not any(b.get("type") == "tool_result" for b in _blocks(record))


def _accepted(block: Mapping[str, Any]) -> bool:
    """The CLI's tool_result for a handback that delivered: not an error, and not a JSON
    answer saying ``"success": false``."""
    if block.get("is_error") is True:
        return False
    content = block.get("content")
    if isinstance(content, list):
        content = "".join(b.get("text", "") for b in content if isinstance(b, Mapping) and isinstance(b.get("text"), str))
    try:
        answer = json.loads(content) if isinstance(content, str) else None
    except ValueError:
        answer = None
    return not (isinstance(answer, dict) and "success" in answer and not answer["success"])


def handback_message(transcript_path: Any) -> Optional[str]:
    """The message of the report the agent's latest run delivered through SubagentHandback:
    the first handback call of that run whose tool_result accepted it (the CLI delivers one
    report per run and leaves a later call unanswered or refused). None when the run has no
    such call or the transcript cannot be read."""
    if not isinstance(transcript_path, (str, Path)) or not str(transcript_path):
        return None
    calls: dict[str, str] = {}
    delivered: Optional[str] = None
    try:
        with open(transcript_path, "rb") as handle:
            for line in handle:
                if HANDBACK_TOOL.encode() not in line and not _USER.search(line):
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(record, dict):
                    continue
                if _starts_run(record):
                    calls, delivered = {}, None
                    continue
                for block in _blocks(record):
                    if (block.get("type") == "tool_use" and block.get("name") == HANDBACK_TOOL
                            and isinstance(block.get("id"), str)):
                        tool_input = block.get("input")
                        text = tool_input.get("message") if isinstance(tool_input, Mapping) else None
                        if isinstance(text, str):
                            calls[block["id"]] = text
                    elif (block.get("type") == "tool_result" and block.get("tool_use_id") in calls
                            and delivered is None and _accepted(block)):
                        delivered = calls[block["tool_use_id"]]
    except (OSError, ValueError):
        return None
    return delivered


def final_report(payload: Mapping[str, Any], transcript_path: Any = None) -> Any:
    """The stopping agent's final report: its handback message when its latest run delivered
    one (read from ``transcript_path``, else the payload's ``agent_transcript_path``), else
    the payload's ``last_assistant_message`` as given."""
    path = transcript_path or payload.get("agent_transcript_path")
    message = handback_message(path)
    return message if message is not None else payload.get("last_assistant_message")
