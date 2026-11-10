#!/usr/bin/env python3
"""PostToolUse: record successful validated restart SendMessage calls."""

from __future__ import annotations
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
