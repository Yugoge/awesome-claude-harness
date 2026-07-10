#!/usr/bin/env python3
"""
PreToolUse hook: block background execution on Agent/Task/Bash for orchestrator.

ENFORCEMENT (default disposition matters):
  - Agent / Task → background is the DEFAULT, so the field is usually ABSENT.
    Block unless run_in_background is explicitly False (True or absent → exit 2).
  - Bash → foreground is the default, so only an explicit True is a background
    task (exit 2); absent/False is fine.
  - Subagents (agent_id present) → exit 0 (no restriction)
  - /do consent active → exit 0 (bypass)

RATIONALE:
  Orchestrator background tasks bypass harness monitoring and create
  unmanageable execution state. All work must be synchronous and observable.
  Because Agent/Task run in the background *by default*, guarding only against an
  explicit run_in_background=true lets every default-dispatch slip through — the
  orchestrator must be forced to opt into synchronous execution.
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

    rib = params.get("run_in_background")

    # Agent and Task default to BACKGROUND when the field is absent, so anything
    # other than an explicit False (i.e. True or None/absent) is a background
    # dispatch and is blocked.
    if tool_name in {"Agent", "Task"} and rib is not False:
        print(
            f"[BLOCK] {tool_name} runs in the background by default and is forbidden "
            "for the orchestrator.\n"
            "Pass run_in_background=false for synchronous execution, or use /do.",
            file=sys.stderr,
        )
        sys.exit(2)

    # Bash defaults to FOREGROUND, so only an explicit True is a background task.
    if tool_name == "Bash" and rib is True:
        print(
            "[BLOCK] Bash(run_in_background=true) is forbidden for orchestrator.\n"
            "All work must run synchronously. Remove run_in_background or use /do.",
            file=sys.stderr,
        )
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
