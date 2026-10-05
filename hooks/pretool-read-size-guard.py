#!/usr/bin/env python3
"""
PreToolUse Hook: Read Size Guard

Blocks the main agent from reading files larger than 600 lines.
Subagents (agent_id present) are exempt.
Binary files (images, PDFs) are exempt.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.allowlist import read_grant  # noqa: E402
from lib.harness_state_dir import harness_state_dir  # noqa: E402

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp", ".pdf",
}
LINE_LIMIT = 600
CHUNK_LIMIT = 600


def has_consent(session_id: str) -> bool:
    flag = Path(f"{harness_state_dir()}/claude-orchestrator-consent-{session_id}.flag")
    try:
        return flag.exists() and flag.read_text().strip() == "true"
    except Exception:
        return False


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


def is_bounded_chunk(tool_input):
    """Allow offset+limit Reads when chunk size <= CHUNK_LIMIT."""
    requested_limit = tool_input.get("limit")
    return isinstance(requested_limit, int) and 0 < requested_limit <= CHUNK_LIMIT


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
            if has_consent(sid) or read_grant("Read", sid):
                sys.exit(0)
        except Exception:
            pass

    line_count = count_lines(file_path)
    if line_count < 0 or line_count <= LINE_LIMIT:
        sys.exit(0)
    if is_bounded_chunk(tool_input):
        sys.exit(0)

    sys.stderr.write(
        f"[Read Size Guard] File too large: {file_path} "
        f"({line_count} lines, limit {LINE_LIMIT}).\n"
        f"To slice it, retry with offset+limit where limit <= {CHUNK_LIMIT}. Otherwise:\n"
        f"  1. Use Grep to locate the specific section you need, then Read that narrow range.\n"
        f"  2. Delegate to an Agent subagent asking it to SUMMARIZE the file (not return raw content).\n"
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
