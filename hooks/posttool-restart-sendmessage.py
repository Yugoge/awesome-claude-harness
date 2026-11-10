#!/usr/bin/env python3
"""PostToolUse: record successful validated restart SendMessage calls."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import subagent_restart as restart  # noqa: E402


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    ok, _ = restart.authorize_send_message(payload)
    if not ok:
        return 0
    params = payload.get("tool_input") or {}
    session_id = payload.get("session_id")
    agent_id = params.get("to") if isinstance(params, dict) else None
    try:
        view = restart.mark_dispatched(str(session_id or ""), str(agent_id or ""))
    except restart.RestartError:
        return 0
    # The orchestrator's next step depends on what is still incomplete (CLAUDE.md lesson 16):
    # PostToolUse additionalContext reaches it, plain stdout does not.
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": f"RESTART DISPATCH RECORDED: {agent_id}; "
                             f"incomplete={len(view['incomplete_agent_ids'])}"}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
