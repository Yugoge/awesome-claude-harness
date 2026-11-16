#!/bin/bash
# session-tmpfs-banner.sh — SessionStart hook (6th in the SessionStart hooks block).
#
# Layer 1 of the tmpfs-pressure prevention plan (dev-20260519-161035).
# Reads `df -h /tmp /dev/shm | tail -n +2` (column header stripped) and prints one
# `WARN tmpfs over 75%: <df line>` line on stdout for each mount whose Use% exceeds
# 75%, and nothing when none does.
#
# Non-blocking: exits 0 unconditionally regardless of df failures.
# `df` is invoked via PATH lookup (bare `df`) per project convention.
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib/harness_switch.sh" 2>/dev/null && harness_switch_exit_if_off  # the harness switch: no harness hook runs while /harness off holds

set -u

THRESHOLD=75

# `df -h /tmp /dev/shm | tail -n +2` yields exactly two lines on this server.
# We parse each line; column 5 is `Use%` (e.g., `45%`). We strip the `%` and
# compare numerically. Wrapped in `timeout 2s` so a hung df cannot block
# the SessionStart sequence (codex review F2).
timeout 2s df -h /tmp /dev/shm 2>/dev/null | tail -n +2 | while IFS= read -r line; do
  # Defensive: skip blank lines that can appear on unusual mount lists.
  [ -z "$line" ] && continue
  # Use% is the 5th whitespace-separated column.
  pct_raw=$(echo "$line" | awk '{print $5}')
  pct=${pct_raw%\%}
  # If parsing failed, emit the raw line without WARN prefix (best effort,
  # non-blocking by contract).
  case "$pct" in
    ''|*[!0-9]*) continue ;;
  esac
  # Only a mount over the threshold is worth the model's context: plain-text stdout of a
  # SessionStart hook is added to it (code.claude.com/docs/en/hooks), stderr reaches no one.
  if [ "$pct" -gt "$THRESHOLD" ]; then
    printf 'WARN tmpfs over %s%%: %s\n' "$THRESHOLD" "$line"
  fi
done

exit 0
