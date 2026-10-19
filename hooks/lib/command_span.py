"""Read-only span reader for a main-session transcript (TC-4).

The span is the records after the latest human-typed harness command outside
stop_contract.CONTROL_COMMANDS. Every plain prompt continues it; built-in and
plugin commands, CONTROL commands and every record not typed by the human
(Skill-tool expansions, subagent records, tool results, queue-operation and
attachment records) never change it. The opener rule lives in stop_contract.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

try:  # imported as hooks.lib.command_span (tests) or lib.command_span (hooks)
    from . import stop_contract
except ImportError:  # hooks/lib placed directly on sys.path
    import stop_contract  # type: ignore[no-redef]


@dataclass
class ToolUse:
    line: int
    id: str
    name: str
    input: dict
    result: dict | None = None

    @property
    def ok(self) -> bool:
        """A result arrived and it is not an error."""
        return self.result is not None and not self.result.get("is_error")


@dataclass
class Span:
    command: str
    args: str
    start_line: int
    uses: list[ToolUse] = field(default_factory=list)
    last_text: str = ""

    def calls(self, *names: str) -> list[ToolUse]:
        """The span's tool uses named ``names``, each with its tool_result."""
        return [use for use in self.uses if use.name in names]

    def last_todos(self) -> list | None:
        """The input todos of the span's last ok TodoWrite."""
        done = [use for use in self.calls("TodoWrite") if use.ok]
        return done[-1].input.get("todos") if done else None

    def final_text(self, payload: dict) -> str:
        """The payload's last_assistant_message, else the span's last
        assistant text."""
        value = payload.get("last_assistant_message") if isinstance(payload, dict) else None
        return value if isinstance(value, str) and value.strip() else self.last_text


def _records(transcript_path: str | Path) -> list[tuple[int, dict]]:
    records = []
    with open(transcript_path, encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle, 1):
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                records.append((number, record))
    return records


def active_span(transcript_path: str | Path, commands: frozenset | None = None) -> Span | None:
    """The active span, or None when no human-typed harness command opened one
    or the transcript cannot be read. ``commands`` defaults to this harness's
    commands/*.md stems."""
    commands = stop_contract.harness_commands() if commands is None else commands
    try:
        records = _records(transcript_path)
    except (OSError, TypeError, ValueError):
        return None
    span = None
    for number, record in records:
        opener = stop_contract.span_opener(record, commands)
        if opener:
            span = Span(command=opener[0], args=opener[1], start_line=number)
    if span is None:
        return None
    by_id: dict[str, ToolUse] = {}
    for number, record in records:
        message = record.get("message") if number > span.start_line else None
        content = message.get("content") if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else ():
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "tool_use" and record.get("type") == "assistant":
                use = ToolUse(number, str(block.get("id", "")), str(block.get("name", "")), block.get("input") or {})
                span.uses.append(use)
                by_id[use.id] = use
            elif kind == "tool_result" and block.get("tool_use_id") in by_id:
                by_id[block["tool_use_id"]].result = block
            elif kind == "text" and record.get("type") == "assistant":
                span.last_text = block.get("text", "")
    return span
