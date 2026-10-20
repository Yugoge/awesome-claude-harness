"""Read-only span reader for a main-session transcript (TC-4).

The span is the records after the latest human-typed harness command outside
stop_contract.CONTROL_COMMANDS. Every plain prompt continues it; built-in and
plugin commands, CONTROL commands and every record not typed by the human
(Skill-tool expansions, subagent records, tool results, queue-operation and
attachment records) never change it. The opener rule lives in stop_contract.
P1 ships the span itself, whose command G1 reads; accessors over the span's
tool uses wait for the phases that consume them (P4, P5).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

try:  # imported as hooks.lib.command_span (tests) or lib.command_span (hooks)
    from . import stop_contract
except ImportError:  # hooks/lib placed directly on sys.path
    import stop_contract  # type: ignore[no-redef]


@dataclass
class Span:
    command: str
    args: str
    start_line: int


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
    return span
