#!/usr/bin/env bash
# stop.sh - wrapper for /stop slash command
#
# Cancels every active overnight time-lock + workflow-enforce by:
#   1. Backdating end_time on each active overnight-state-*.json file
#   2. Marking every todo in the corresponding todos file as "completed"
#
# After this runs, both Stop hooks (stop-overnight-timelock.py + stop-
# workflow-enforce.py) release on the next stop attempt and the session
# can terminate normally.
#
# Sentinel guard mirrors commit/push/merge: pretool-wrapper-userintent.py
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
