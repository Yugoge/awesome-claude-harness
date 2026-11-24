#!/bin/bash
# session-tmpfs-banner.sh — SessionStart hook: the space notice of hooks/userprompt-tmpfs-pressure.sh, at
# session start (its stdout is added to the model's context, as a prompt hook's is).
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib/harness_switch.sh" 2>/dev/null && harness_switch_exit_if_off  # the harness switch: no harness hook runs while /harness off holds
exec bash "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/userprompt-tmpfs-pressure.sh"
