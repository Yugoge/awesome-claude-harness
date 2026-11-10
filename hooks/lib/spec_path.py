#!/usr/bin/env python3
"""The spec a session last wrote, read from its transcript (E14, PLAN-v2 P9 row 1).

One rule, two callers: prompt-workflow.py decides a /dev, /dev-command, /redev or
/dev-overnight run's spec at UserPromptSubmit (an explicit --spec first, else this),
and stop-spec-coverage-enforce.py finds the spec a /spec session wrote. A write is an
ok Write, Edit or MultiEdit of a .md file directly under docs/dev/specs/ (INDEX.md and
README.md excluded), or an ok Bash call of scripts/spec-write.py, the one writer of
those files, through the `spec-write: <op> <path>` line it prints. Nothing else (an
mtime, a listing) chooses a spec.

The transcript is read through command_span, the one transcript reader (T2-9): its
calls are the session's own tool calls and how they came back, the same reading the
Stop gate decides on, so this module has no transcript parser of its own. A relative
target resolves against the cwd its tool_use record carries, as the CLI resolved it.
"""

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


def _reader():
    try:
        from . import command_span
    except ImportError:  # hooks/lib on sys.path, as prompt-workflow.py loads this module
        import command_span
    return command_span


def _record_cwds(reader, transcript_path) -> dict:
    """{line: the cwd its record carries}, read only for a relative target (a Call
    carries no record cwd); {} when the transcript cannot be read."""
    try:
        return {number: record.get("cwd") for number, record in reader._records(transcript_path)}
    except (OSError, TypeError, ValueError):
        return {}


def last_spec_write(transcript_path, cwd=""):
    """Absolute path of the spec the transcript's own tool calls last wrote, or None
    (no such write, or the transcript cannot be read). The calls are read newest
    first, so the read stops at the last spec write."""
    if not isinstance(transcript_path, (str, os.PathLike)):
        return None
    reader = _reader()
    span, cwds = reader.transcript_span(transcript_path), None
    for call in span.iter_calls(*EDIT_TOOLS, "Bash", newest_first=True):
        if not call.ok:
            continue
        if call.name in EDIT_TOOLS:
            target = call.input.get("file_path")
            if not (isinstance(target, str) and target):
                continue
            target = os.path.expanduser(target)
            if not os.path.isabs(target):
                cwds = _record_cwds(reader, transcript_path) if cwds is None else cwds
                target = os.path.join(cwds.get(call.line) or cwd or os.sep, target)
            target = os.path.normpath(target)
            if is_spec_file(target):
                return target
        elif WRITER in str(call.input.get("command", "")):
            for target in reversed(_WRITER_LINE.findall(span.result_text(call.id))):
                if is_spec_file(target):
                    return target
    return None
