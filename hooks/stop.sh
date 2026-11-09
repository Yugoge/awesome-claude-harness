#!/usr/bin/env bash
# stop.sh - wrapper for /stop slash command
#
# The human-typed /stop record in the session's transcript is what releases the
# /dev-overnight time-lock (the Stop gate's step 4, hooks/stop-command-gate.py,
# through lib/command_span.py timelock_released) and opens the span no Stop gate
# holds; this wrapper releases nothing. It runs break-overnight-lock.py, which
# records current_phase=completed in the stopping session's own overnight state
# and, with the /stop helper-auth token, releases its isolation fields. It never
# writes end_time, and the session's todo list is the CLI's own record, which
# nothing here writes.
#
# Sentinel guard: pretool-wrapper-userintent.py
# enforces that this script is only invocable via /stop slash command.
# Model agents using Bash to invoke stop.sh directly will be blocked.
set -euo pipefail

# WS1: resolve the helper under the harness home (from this script's own
# location), instead of the author literal /root. The loud-fail guard is
# PRESERVED (exit 1 when absent) per the pre-existing-guard contract.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/claude_home.sh"
# Degrade to $HOME/.claude on a resolver miss instead of hard-aborting under
# `set -e`; the loud helper-missing guard below still fires (baseline behavior).
CLAUDE_HOME="$(claude_home_resolve || echo "${HOME}/.claude")"
HELPER="${CLAUDE_HOME}/scripts/break-overnight-lock.py"
if [ ! -f "$HELPER" ]; then
  echo "stop.sh: helper $HELPER missing" >&2
  exit 1
fi

python3 "$HELPER"
