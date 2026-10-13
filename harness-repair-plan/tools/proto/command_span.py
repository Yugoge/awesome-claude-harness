"""PROTOTYPE of hooks/lib/command_span.py: the active slash-command span of a
main-session transcript, derived from CLI-written records only (no state file).

Span = records after the latest human slash-command prompt whose command is not
a CONTROL command. Plain-text human prompts (answers to a question pause)
continue the span; a different slash command replaces it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

CONTROL_COMMANDS = frozenset({"allow", "restart", "checkpoint", "tickets"})  # orthogonal; never open a span
_CMD_RE = re.compile(r"<command-name>/?([A-Za-z0-9:_-]+)</command-name>")
_ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)
PAUSE_RE = re.compile(
    r"^AWAITING_INPUT: need=(?P<need>[^;\n]+); why=(?P<why>[^;\n]+); "
    r"addressee=(?P<who>human|user|operator)\s*$")


def _human_text(rec: dict) -> str | None:
    """Text of a human-typed prompt record, else None (meta, tool_result, hooks)."""
    if rec.get("type") != "user" or rec.get("isMeta"):
        return None
    msg = rec.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        return "".join(b.get("text", "") for b in content
                       if isinstance(b, dict) and b.get("type") == "text") or None
    return None


def _slash(text: str) -> tuple[str, str] | None:
    m = _CMD_RE.search(text)
    if m:
        a = _ARGS_RE.search(text)
        return m.group(1), (a.group(1).strip() if a else "")
    t = text.strip()
    if t.startswith("/") and len(t) > 1 and not t.startswith("//"):
        head, _, rest = t[1:].partition(" ")
        return head, rest.strip()
    return None


@dataclass
class ToolUse:
    line: int
    id: str
    name: str
    input: dict
    result: dict | None = None

    @property
    def ok(self) -> bool:
        return self.result is not None and not self.result.get("is_error")

    @property
    def result_text(self) -> str:
        c = (self.result or {}).get("content")
        if isinstance(c, list):
            return "".join(b.get("text", "") for b in c if isinstance(b, dict))
        return c if isinstance(c, str) else ""


@dataclass
class Span:
    command: str
    args: str
    start_line: int
    uses: list[ToolUse] = field(default_factory=list)
    last_text: str = ""
    last_assistant: dict | None = None

    def calls(self, *names: str) -> list[ToolUse]:
        return [u for u in self.uses if u.name in names]

    def last_todos(self) -> list[dict] | None:
        ok = [u for u in self.calls("TodoWrite") if u.ok]
        return ok[-1].input.get("todos") if ok else None


def active_span(transcript_path: str | Path, openers: frozenset | None = None) -> Span | None:
    """openers: harness command names (commands/*.md stems); built-ins and plugin commands never open a span."""
    records = []
    with open(transcript_path, encoding="utf-8", errors="replace") as fh:
        for n, line in enumerate(fh, 1):
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict):
                records.append((n, rec))
    start = None
    for n, rec in records:
        text = _human_text(rec)
        if text is None:
            continue
        sl = _slash(text)
        if sl and sl[0] not in CONTROL_COMMANDS and (openers is None or sl[0] in openers):
            start = (sl[0], sl[1], n)
    if start is None:
        return None
    span = Span(command=start[0], args=start[1], start_line=start[2])
    by_id: dict[str, ToolUse] = {}
    for n, rec in records:
        if n <= span.start_line:
            continue
        msg = rec.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use" and rec.get("type") == "assistant":
                u = ToolUse(n, b.get("id", ""), b.get("name", ""), b.get("input") or {})
                span.uses.append(u)
                by_id[u.id] = u
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in by_id:
                by_id[b["tool_use_id"]].result = b
            elif b.get("type") == "text" and rec.get("type") == "assistant":
                span.last_text = b.get("text", "")
    span.last_assistant = next((r for _, r in reversed(records) if r.get("type") == "assistant"), None)
    return span


def final_text(payload: dict, span: Span | None) -> str:
    v = payload.get("last_assistant_message")
    if isinstance(v, str) and v.strip():
        return v
    return span.last_text if span else ""


def is_pause(text: str) -> bool:
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return bool(lines) and PAUSE_RE.match(lines[-1].strip()) is not None
