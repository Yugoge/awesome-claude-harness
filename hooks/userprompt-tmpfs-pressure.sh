#!/bin/bash
# userprompt-tmpfs-pressure.sh — UserPromptSubmit hook; hooks/session-tmpfs-banner.sh runs it at SessionStart.
#
# The space notice. scripts/install/tmp-cleanup-install.sh --pressure watches the volumes a session needs and,
# while one is short of space, removes what the harness owns and is provably dead (the rule is in its header),
# then prints the notice: on stdout, which both events add to the model's context. One notice per change of
# the set of short volumes: the last set is kept in <state dir>/claude-pressure-warn-<session token>. When that
# file cannot be written the notice still prints, says so, and comes again at the next prompt.
# Non-blocking: exits 0 on every path.
#
# Session token: the payload's `session_id`, else CLAUDE_SESSION_ID, else a hash of PPID and its start time.
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib/harness_switch.sh" 2>/dev/null && harness_switch_exit_if_off  # the harness switch: no harness hook runs while /harness off holds

set -u

# Bounded read so a never-closing stdin cannot hang the hook (codex review F2).
INPUT=""
IFS= read -r -t 1 -d '' INPUT 2>/dev/null || true

SID=$(printf '%s' "$INPUT" | python3 -c "
import json, os, sys
try:
    d = json.load(sys.stdin)
except Exception:
    d = {}
sid = d.get('session_id') or os.environ.get('CLAUDE_SESSION_ID') or ''
print(sid)
" 2>/dev/null)

if [ -z "${SID:-}" ]; then
  # Fallback: hashed PPID-rooted token. /proc/$PPID start-time anchors the
  # token to the parent shell's invocation, so it stays stable across the
  # lifetime of one process but differs between distinct parents.
  proc_start=$(stat -c %Y "/proc/$PPID" 2>/dev/null || echo 0)
  SID=$(printf '%s-%s' "$PPID" "$proc_start" | sha256sum | cut -c1-16)
fi

# Sanitize token: keep [A-Za-z0-9_-], length-cap 64. Anything else is hashed.
SANITIZED=$(printf '%s' "$SID" | tr -cd 'A-Za-z0-9_-' | cut -c1-64)
if [ -z "$SANITIZED" ]; then
  SANITIZED=$(printf '%s' "$SID" | sha256sum | cut -c1-32)
fi

HOOKS="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
. "$HOOKS/lib/harness_state_dir.sh" 2>/dev/null
COUNTER_FILE="$(harness_state_dir 2>/dev/null)/claude-pressure-warn-${SANITIZED}"

# The file: the set of short volumes last told, then the time of the last reaction.
PREV="" LAST=0
{ IFS= read -r PREV; IFS= read -r LAST; } 2>/dev/null < "$COUNTER_FILE"
case "$PREV" in "short:"*) ;; *) PREV="short:" ;; esac  # none recorded (or an older counter): nothing was short
# 4.5 s: the program's own bounds (df 2 s, removals, du 1 s) inside the SessionStart hook's 5 s.
OUT=$(timeout 4.5s bash "$HOOKS/../scripts/install/tmp-cleanup-install.sh" --pressure "$PREV" "$LAST" 2>/dev/null)
case "$OUT" in
  "short:"*$'\n'*) ;;
  *) echo "[space] The check of free space did not finish (scripts/install/tmp-cleanup-install.sh); run df -h."; exit 0 ;;
esac
SIG="${OUT%%$'\n'*}" REST="${OUT#*$'\n'}"
REACTED="${REST%%$'\n'*}" BODY="${REST#"${REST%%$'\n'*}"}"
[ "$SIG" = "$PREV" ] && [ "$REACTED" = "$LAST" ] && exit 0
[ -z "$BODY" ] || printf '%s\n' "${BODY#$'\n'}"
printf '%s\n%s\n' "$SIG" "$REACTED" 2>/dev/null > "$COUNTER_FILE" || [ -z "$BODY" ] \
  || echo "[space] This notice could not record itself in $COUNTER_FILE, so it comes again at the next prompt."

exit 0
