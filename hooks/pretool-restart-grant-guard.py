#!/usr/bin/env python3
"""Block model-side creation or execution of /restart authorization grants."""

from __future__ import annotations

import json
import sys


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    tool = payload.get("tool_name") or ""
    params = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    if tool == "Bash":
        command = params.get("command") if isinstance(params.get("command"), str) else ""
        if "claude-restart-grant-" in command or "userprompt-restart-authorize.py" in command:
            print(
                "BLOCKED: restart authorization is minted only by the UserPromptSubmit hook "
                "for a human's exact /restart command.",
                file=sys.stderr,
            )
            return 2
    if tool in {"Write", "Edit", "MultiEdit", "NotebookEdit"}:
        path = params.get("file_path") if isinstance(params.get("file_path"), str) else ""
        if "claude-restart-grant-" in path:
            print("BLOCKED: restart grant files are hook-owned.", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

