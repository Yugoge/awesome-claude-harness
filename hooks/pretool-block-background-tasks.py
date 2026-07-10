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

    # Use correct field names with fallbacks
    tool_name = payload.get("tool_name") or payload.get("tool") or payload.get("toolName") or ""
    params = payload.get("tool_input") or payload.get("params") or payload.get("toolInput") or {}
    agent_id = payload.get("agent_id") or payload.get("agentId")
    session_id = (
        payload.get("session_id")
        or payload.get("sessionId")
        or os.environ.get("CLAUDE_SESSION_ID")
        or "default"
    )

    # Subagents exempt
    if agent_id:
        sys.exit(0)

    # /do consent bypass - use correct sentinel path
    do_sentinel = Path(f"/tmp/claude-orchestrator-consent-{session_id}.flag")
    if do_sentinel.exists():
        sys.exit(0)

    # Check if run_in_background is true - cover Agent, Bash, and Task
    if tool_name in {"Agent", "Bash", "Task"} and params.get("run_in_background") is True:
        print(
            f"[BLOCK] {tool_name}(run_in_background=true) is forbidden for orchestrator.\n"
            "All work must run synchronously. Remove run_in_background or use /do.",
            file=sys.stderr,
        )
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
