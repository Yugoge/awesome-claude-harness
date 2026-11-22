#!/usr/bin/env python3
"""PostToolUse: journal every SendMessage call that ran.

A validated /restart send is recorded as dispatched in the restart state, as before; any other
send gets one line in the session's send journal (lib/send_policy.record).
"""

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
from lib import send_policy  # noqa: E402
from lib import subagent_restart as restart  # noqa: E402


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    try:  # a send to an own subagent was opened as a dispatch (lib/send_policy); its run goes on in the background
        from lib import dispatch_temp
        dispatch_temp.returned({**payload, "tool_response": {"status": "async_launched"}})
    except Exception:  # noqa: BLE001 -- never fails the tool call
        pass
    ok, _ = restart.authorize_send_message(payload)
    if not ok:
        try:
            send_policy.record(payload)
        except Exception:  # noqa: BLE001 -- a journal write never fails the tool call
            pass
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
