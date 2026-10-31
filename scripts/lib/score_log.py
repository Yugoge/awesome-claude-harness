#!/usr/bin/env python3
"""The one reader of the score log (logs/lifecycle.jsonl).

``scripts/score-update.sh`` (the log's writer) and ``scripts/score-inject.sh`` read
the whole log before they act. Both call ``read_lines``, so one rule decides which
lines count and when the log is refused; each script keeps its own exit code for a
refusal.

A final line that does not parse is skipped, not refused: the writer appends one
line at a time, so a crash mid-append leaves at most the last line partial.
"""

from __future__ import annotations

import json


class ScoreLogError(Exception):
    """The log cannot be read, or a line before the last is malformed."""


def read_lines(path: str) -> list[tuple[int, dict]]:
    """Every entry of the log with its 1-based line number, in file order."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw_lines = handle.readlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ScoreLogError(f"cannot read {path}: {exc}") from exc
    entries = []
    for index, raw_line in enumerate(raw_lines):
        stripped = raw_line.rstrip("\n")
        if not stripped:
            continue
        try:
            entry = json.loads(stripped)
        except json.JSONDecodeError:
            entry = None
        if isinstance(entry, dict):
            entries.append((index + 1, entry))
        elif index != len(raw_lines) - 1:
            raise ScoreLogError(
                f"malformed JSONL at line {index + 1} of {path} (not final line)"
            )
    return entries
