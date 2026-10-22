"""Stop contract: the commands a Stop gate guards, and which transcript record
is a prompt the human typed (TC-4).

Stdlib only, no harness imports: the Stop coordinator's fallback and
command_span import it, and an import-free launcher may copy its tuples.
Only human-typed records count; no CLI error or cancellation record is read
(D4c), and nothing an agent writes can open, replace or close a span.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

GATED_COMMANDS = ("do", "dev", "redev", "dev-command", "dev-overnight", "close", "commit", "merge", "push")
CONTROL_COMMANDS = ("allow", "restart", "checkpoint", "tickets")

COMMANDS_DIR = Path(__file__).resolve().parent.parent.parent / "commands"
# Markers a typed prompt never carries: a Skill-tool expansion (isMeta,
# sourceToolUseID), a subagent's own records (isSidechain), a tool result.
_NON_HUMAN_KEYS = ("isMeta", "isSidechain", "sourceToolUseID", "toolUseResult")
# The CLI records a typed command as <command-message>..</command-message>
# <command-name>/x</command-name><command-args>..</command-args> at the start.
_CMD_TAG_RE = re.compile(
    r"\s*(?:<command-message>.*?</command-message>\s*)?<command-name>/?([A-Za-z0-9:_-]+)</command-name>", re.S
)
_ARGS_TAG_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)
_SLASH_RE = re.compile(r"\s*/([A-Za-z0-9:_-]+)(?:\s+(.*))?\Z", re.S)


def harness_commands() -> frozenset:
    """commands/*.md stems of this harness, INDEX and README excluded."""
    try:
        return frozenset(p.stem for p in COMMANDS_DIR.glob("*.md") if p.stem not in ("INDEX", "README"))
    except OSError:
        return frozenset()


def prompt_text(record) -> str | None:
    """Text of a human-typed prompt record, else None (TC-4)."""
    if not isinstance(record, dict) or record.get("type") != "user":
        return None
    if any(record.get(key) for key in _NON_HUMAN_KEYS):
        return None
    for key in ("origin", "turnOrigin"):  # a typed prompt records origin kind "human"
        value = record.get(key)
        kind = value.get("kind") if isinstance(value, dict) else value
        if kind is not None and kind != "human":
            return None
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if not isinstance(content, list) or any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return None
    return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text") or None


def is_human_prompt(record) -> bool:
    return prompt_text(record) is not None


def slash_command(text: str) -> tuple[str, str] | None:
    """(name, args) of a slash command typed as ``/x`` or recorded as
    ``<command-name>/x</command-name>``, else None."""
    match = _CMD_TAG_RE.match(text)
    if match:
        args = _ARGS_TAG_RE.search(text)
        return match.group(1), (args.group(1).strip() if args else "")
    match = _SLASH_RE.match(text)
    return (match.group(1), (match.group(2) or "").strip()) if match else None


def span_opener(record, commands: frozenset) -> tuple[str, str] | None:
    """(command, args) when ``record`` is a human-typed harness command outside
    CONTROL_COMMANDS; built-in and plugin commands never qualify."""
    text = prompt_text(record)
    found = slash_command(text) if text is not None else None
    if found and found[0] in commands and found[0] not in CONTROL_COMMANDS:
        return found
    return None


def active_command(transcript_path) -> str | None:
    """The latest human-typed harness command outside CONTROL_COMMANDS in the
    whole transcript, or None (no such prompt, or the file is unreadable)."""
    commands, latest = harness_commands(), None
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    found = span_opener(json.loads(line), commands)
                except ValueError:
                    continue
                if found:
                    latest = found[0]
    except (OSError, TypeError, ValueError):
        return None
    return latest
