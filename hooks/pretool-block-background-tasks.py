#!/usr/bin/env python3
"""
PreToolUse hook: block run_in_background=true on Agent and Bash tools.

ENFORCEMENT:
  - Agent(run_in_background=true) → exit 2
  - Bash(run_in_background=true) → exit 2
  - Subagents (agent_id present) → exit 0 (no restriction)
  - /do consent active → exit 0 (bypass)

RATIONALE:
  Orchestrator background tasks bypass harness monitoring and create
  unmanageable execution state. All work must be synchronous and observable.
"""
import json
import os
import sys
from pathlib import Path


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = payload.get("tool", "")
    params = payload.get("params", {})
    agent_id = payload.get("agentId")
    session_id = payload.get("sessionId", "unknown")

    # Subagents exempt
    if agent_id:
        sys.exit(0)

    # /do consent bypass
    do_sentinel = Path(f"/tmp/claude-do-{session_id}")
    if do_sentinel.exists():
        sys.exit(0)

    # Check if run_in_background is true
    if tool_name == "Agent" and params.get("run_in_background") is True:
        print(
            "[BLOCK] Agent(run_in_background=true) is forbidden for orchestrator.\n"
            "All subagents must run synchronously. Remove run_in_background or use /do.",
            file=sys.stderr,
        )
        sys.exit(2)

    if tool_name == "Bash" and params.get("run_in_background") is True:
        print(
            "[BLOCK] Bash(run_in_background=true) is forbidden for orchestrator.\n"
            "All commands must run synchronously. Remove run_in_background or use /do.",
            file=sys.stderr,
        )
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
