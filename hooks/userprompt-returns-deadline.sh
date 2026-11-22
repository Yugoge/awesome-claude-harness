#!/usr/bin/env bash
# UserPromptSubmit, asyncRewake: the deadline of a batch of held background returns (hooks/lib/returns_hold.py,
# its `deadline`). Off unless switched on (CLAUDE_RETURNS_HOLD=on): with the setting absent it does nothing.
# Runs in the background on every prompt; only an agent's task-notification arms it, so a typed prompt starts no
# interpreter. Exit 2 wakes the session with the held returns' deadline notice.
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib/harness_switch.sh" 2>/dev/null && harness_switch_exit_if_off  # the harness switch: no harness hook runs while /harness off holds
[ "${CLAUDE_RETURNS_HOLD:-}" = on ] || exit 0
in=$(cat)
case "$in" in *'<task-notification>\n<task-id>a'*) ;; *) exit 0 ;; esac
printf '%s' "$in" | exec python3 "$(dirname "$(realpath "$0")")/lib/returns_hold.py" --deadline
