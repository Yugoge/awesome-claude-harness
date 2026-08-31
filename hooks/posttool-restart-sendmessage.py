#!/usr/bin/env python3
"""PostToolUse: record the structured result of validated restart sends."""

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
    send_tool_use_id = payload.get("tool_use_id") or payload.get("toolUseId")
    try:
        view = restart.record_send_result(
            str(session_id or ""), str(agent_id or ""), str(send_tool_use_id or ""),
            payload.get("tool_response"),
        )
    except restart.RestartError:
        return 0
    row = next(item for item in view["candidates"] if item.get("agent_id") == agent_id)
    print(
        f"RESTART SEND RESULT RECORDED: {agent_id}; status={row['status']}; "
        f"incomplete={len(view['incomplete_agent_ids'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
