#!/usr/bin/env python3
"""The spec a session last wrote, read from its transcript (E14, PLAN-v2 P9 row 1).

One rule, two callers: prompt-workflow.py decides a /dev, /dev-command, /redev or
/dev-overnight run's spec at UserPromptSubmit (an explicit --spec first, else this),
and stop-spec-coverage-enforce.py finds the spec a /spec session wrote. A write is an
ok Write, Edit or MultiEdit of a .md file directly under docs/dev/specs/ (INDEX.md and
README.md excluded), or an ok Bash call of scripts/spec-write.py, the one writer of
those files, through the `spec-write: <op> <path>` line it prints. Nothing else (an
mtime, a listing) chooses a spec.
"""

import json
import os
import re

EDIT_TOOLS = ("Write", "Edit", "MultiEdit")
WRITER = "spec-write.py"
_WRITER_LINE = re.compile(r"^spec-write: (?:create|append) (/\S+)$", re.M)
_NOT_SPECS = ("INDEX.md", "README.md")


def is_spec_file(path) -> bool:
    if not isinstance(path, str) or not path.endswith(".md"):
        return False
    parts = os.path.normpath(path).split(os.sep)
    return len(parts) >= 4 and parts[-4:-1] == ["docs", "dev", "specs"] and parts[-1] not in _NOT_SPECS


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""


def last_spec_write(transcript_path, cwd=""):
    """Absolute path of the spec the transcript's own tool calls last wrote, or None
    (no such write, or the transcript cannot be read)."""
    uses, results = [], {}
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                message = record.get("message") if isinstance(record, dict) else None
                content = message.get("content") if isinstance(message, dict) else None
                for block in content if isinstance(content, list) else ():
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use" and isinstance(block.get("input"), dict):
                        uses.append((block.get("id"), block.get("name"), block["input"],
                                     record.get("cwd") or cwd))
                    elif block.get("type") == "tool_result" and not block.get("is_error"):
                        results[block.get("tool_use_id")] = _text(block.get("content"))
    except (OSError, TypeError):
        return None
    found = None
    for use_id, name, tool_input, base in uses:
        if use_id not in results:
            continue
        if name in EDIT_TOOLS:
            target = tool_input.get("file_path")
            if isinstance(target, str) and target:
                target = os.path.normpath(os.path.join(base or os.sep, os.path.expanduser(target)))
                if is_spec_file(target):
                    found = target
        elif name == "Bash" and WRITER in str(tool_input.get("command", "")):
            for target in _WRITER_LINE.findall(results[use_id]):
                if is_spec_file(target):
                    found = target
    return found
