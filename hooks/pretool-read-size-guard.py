#!/usr/bin/env python3
"""
PreToolUse Hook: Read Size Guard

Blocks the main agent from reading files larger than 600 lines when the Read
would return more than 600 lines: min(limit or 2000, total - offset + 1).
Subagents (agent_id present) are exempt.
Binary files (images, PDFs) are exempt.
"""
import os, sys  # noqa: E401 -- the harness switch (hooks/lib/harness_switch.py): no harness hook runs while /harness off holds
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))
try:  # a hook copied without its lib/ (an old install) is on
    import harness_switch  # noqa: E402
    harness_switch.exit_if_off()
except ImportError:
    pass
finally:
    sys.path.pop(0)

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.allowlist import has_do_consent, match_sentinel_grant_for_tool  # noqa: E402

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp", ".pdf",
}
LINE_LIMIT = 600
CHUNK_LIMIT = 600
READ_DEFAULT_LIMIT = 2000  # the Read tool returns this many lines when limit is absent


def is_exempt(data, file_path):
    if data.get("tool_name") != "Read":
        return True
    if data.get("agent_id"):
        return True
    if not file_path or not os.path.exists(file_path):
        return True
    _, ext = os.path.splitext(file_path)
    return ext.lower() in BINARY_EXTENSIONS


def count_lines(file_path):
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except Exception:
        return -1


def returned_line_count(tool_input, total_lines):
    """Lines a Read returns: min(limit or 2000, total - offset + 1).

    The Read tool's offset is the 1-based line it starts from and its limit
    defaults to READ_DEFAULT_LIMIT lines. A missing or malformed offset (0,
    negative, bool, string, float, anything not a positive int) counts as
    line 1, and a missing or malformed limit as the default, so a malformed
    value can only raise the count, never shrink it into an allow.
    """
    limit = tool_input.get("limit")
    if not (isinstance(limit, int) and limit > 0):
        limit = READ_DEFAULT_LIMIT
    offset = tool_input.get("offset")
    if isinstance(offset, bool) or not (isinstance(offset, int) and offset > 1):
        offset = 1
    return max(0, min(limit, total_lines - offset + 1))


def is_bounded_chunk(tool_input, total_lines):
    """Allow a Read whose returned chunk is at most CHUNK_LIMIT lines."""
    return returned_line_count(tool_input, total_lines) <= CHUNK_LIMIT


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if is_exempt(data, file_path):
        sys.exit(0)

    if data.get("tool_name") == "Read" and not data.get("agent_id"):
        sid = data.get("session_id") or os.environ.get("CLAUDE_SESSION_ID", "default")
        try:
            if has_do_consent(data) or match_sentinel_grant_for_tool(sid, "Read") is not None:
                sys.exit(0)
        except Exception:
            pass

    line_count = count_lines(file_path)
    if line_count < 0 or line_count <= LINE_LIMIT:
        sys.exit(0)
    if is_bounded_chunk(tool_input, line_count):
        sys.exit(0)

    sys.stderr.write(
        f"[Read Size Guard] File too large: {file_path} "
        f"({line_count} lines, limit {LINE_LIMIT}).\n"
        f"To slice it, retry with offset+limit so the Read returns at most {CHUNK_LIMIT} lines "
        f"(limit <= {CHUNK_LIMIT}, or an offset within the last {CHUNK_LIMIT} lines). Otherwise:\n"
        f"  1. Use Grep to locate the specific section you need, then Read that narrow range.\n"
        f"  2. Delegate to an Agent subagent asking it to SUMMARIZE the file (not return raw content).\n"
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
