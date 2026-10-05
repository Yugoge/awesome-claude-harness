#!/usr/bin/env python3
"""
PreToolUse Hook: Start timeout watchdog for browser_run_code.

Matcher: mcp__playwright__browser_run_code | mcp__paseo__browser_run_code

Spawns a detached watchdog process that will terminate JavaScript execution
via CDP if the tool call exceeds the configured timeout.

Environment variables:
  PLAYWRIGHT_RUNCODE_TIMEOUT: timeout in seconds (default: 30)
  PLAYWRIGHT_CDP_ENDPOINT: CDP endpoint URL (default: http://127.0.0.1:8080)
  CLAUDE_SESSION_ID: session identifier (default: "default")

Exit codes:
  0: Allow tool call (always)
"""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.harness_state_dir import harness_state_dir  # noqa: E402

WATCHDOG_SCRIPT = str(Path.home() / ".claude" / "scripts" / "runcode-watchdog.py")
RUN_CODE_TOOLS = frozenset(
    {"mcp__playwright__browser_run_code", "mcp__paseo__browser_run_code"}
)


def _kill_stale_watchdog(pid_file: str):
    """Kill any existing watchdog from a previous call."""
    try:
        pid = int(Path(pid_file).read_text().strip())
        os.kill(pid, signal.SIGTERM)
    except (OSError, ValueError, FileNotFoundError):
        pass
    # Clean up stale files
    for f in [pid_file, f"{pid_file}.timeout"]:
        try:
            os.unlink(f)
        except OSError:
            pass


def main():
    # Read stdin (required by hook protocol)
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        data = {}

    tool_name = data.get("tool_name", "")
    if tool_name not in RUN_CODE_TOOLS:
        sys.exit(0)

    timeout = int(os.environ.get("PLAYWRIGHT_RUNCODE_TIMEOUT", "30"))
    cdp_endpoint = os.environ.get("PLAYWRIGHT_CDP_ENDPOINT", "http://127.0.0.1:8080")
    session_id = os.environ.get("CLAUDE_SESSION_ID", "default")
    pid_file = f"{harness_state_dir()}/.runcode-watchdog-{session_id}.pid"

    # Kill stale watchdog if any
    _kill_stale_watchdog(pid_file)

    # Start watchdog as detached background process
    subprocess.Popen(
        ["python3", WATCHDOG_SCRIPT, str(timeout), pid_file, cdp_endpoint],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    sys.exit(0)


if __name__ == "__main__":
    main()
