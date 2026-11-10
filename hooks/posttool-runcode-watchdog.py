#!/usr/bin/env python3
"""
PostToolUse Hook: Cancel timeout watchdog after browser_run_code completes.

Matcher: mcp__playwright__browser_run_code | mcp__paseo__browser_run_code

Sends SIGTERM to the watchdog process started by the PreToolUse hook,
preventing it from terminating JavaScript execution. If a timeout already
fired, it tells the model (PostToolUse additionalContext JSON on stdout), which
otherwise reads a cut-off result as the script's own.

Exit codes:
  0: Always (post hooks should not block)
"""
import os, sys  # noqa: E401 -- the harness switch (hooks/lib/harness_switch.py): no harness hook runs while /harness off holds
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib")); import harness_switch; sys.path.pop(0)  # noqa: E402,E702
harness_switch.exit_if_off()

import json
import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.harness_state_dir import harness_state_dir  # noqa: E402

RUN_CODE_TOOLS = frozenset(
    {"mcp__playwright__browser_run_code", "mcp__paseo__browser_run_code"}
)


def _cancel_watchdog(pid_file: str):
    """Send SIGTERM to watchdog and clean up PID file."""
    try:
        pid = int(Path(pid_file).read_text().strip())
        os.kill(pid, signal.SIGTERM)
        time.sleep(0.1)
    except (OSError, ValueError):
        pass
    try:
        os.unlink(pid_file)
    except OSError:
        pass


def _check_timeout_marker(pid_file: str):
    """Report and clean up if timeout already fired."""
    marker_file = f"{pid_file}.timeout"
    if not os.path.exists(marker_file):
        return
    timeout = os.environ.get("PLAYWRIGHT_RUNCODE_TIMEOUT", "30")
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": f"browser_run_code was terminated after {timeout}s timeout"}}))
    try:
        os.unlink(marker_file)
    except OSError:
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        data = {}

    if data.get("tool_name") not in RUN_CODE_TOOLS:
        sys.exit(0)

    session_id = os.environ.get("CLAUDE_SESSION_ID", "default")
    pid_file = f"{harness_state_dir()}/.runcode-watchdog-{session_id}.pid"

    if os.path.exists(pid_file):
        _cancel_watchdog(pid_file)

    _check_timeout_marker(pid_file)
    sys.exit(0)


if __name__ == "__main__":
    main()
