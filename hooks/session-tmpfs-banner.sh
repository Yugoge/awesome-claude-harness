#!/bin/bash
# session-tmpfs-banner.sh — SessionStart hook (6th in the SessionStart hooks block).
#
# Layer 1 of the tmpfs-pressure prevention plan (dev-20260519-161035).
# Emits exactly TWO compact lines (one per mount: /tmp and /dev/shm), derived from
# `df -h /tmp /dev/shm | tail -n +2` (column header stripped). Any mount whose
# Use% column exceeds 75% is prefixed with the literal `WARN ` (5 bytes including
# trailing space) on its own line so grep verification is unambiguous.
#
# Non-blocking: exits 0 unconditionally regardless of df failures.
# `df` is invoked via PATH lookup (bare `df`) per project convention.

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
    ''|*[!0-9]*) printf '%s\n' "$line" >&2; continue ;;
  esac
  if [ "$pct" -gt "$THRESHOLD" ]; then
    printf 'WARN %s\n' "$line" >&2
  else
    printf '%s\n' "$line" >&2
  fi
done

exit 0
