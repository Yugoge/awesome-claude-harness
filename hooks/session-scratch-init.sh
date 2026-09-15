#!/bin/bash
# session-scratch-init.sh — SessionStart hook (Scratch Lifecycle Contract
# Layer A, task 20260907-015935).
#
# Registers this session's per-session scratch directory under the managed,
# disk-backed root (settings.json env.TMPDIR / CLAUDE_CODE_TMPDIR). Ownership
# is captured BY LOCATION, not by name: any creator that honors $TMPDIR or
# calls mktemp is captured automatically, so newly-invented scratch family
# names need no reaper-pattern update (the failure mode this plan retires).
#
# Writes <root>/<sid>/.owner = {sid, pid, pid_start_time, boot_id, created_at}
# so hooks/sessionend-scratch-sweep.sh and the declarative orphan-floor
# backstop (scripts/install/tmpfiles-claude-scratch.conf) can tell a live
# session's dir from a crashed one — 3 accounts share this machine, all root,
# so uid cannot discriminate sessions; .owner is the only ownership signal.
#
# Non-blocking: best-effort, exits 0 unconditionally. SessionStart must never
# fail a session over scratch bookkeeping.

set -u
exec >&2   # SessionStart hooks must not pollute stdout (harness JSON channel)

ROOT="${TMPDIR:-/var/tmp/claude-scratch}"
SID="${CLAUDE_CODE_SESSION_ID:-}"
PID="${CLAUDE_PID:-$$}"

# Best-effort JSON-stdin fallback for SID when the env var is absent. Drains
# stdin either way so the harness never blocks on an unread pipe.
INPUT=$(cat 2>/dev/null || true)
if [ -z "$SID" ]; then
  SID=$(printf '%s' "$INPUT" | python3 -c \
    "import json,sys; d=json.load(sys.stdin); print(d.get('session_id','') or '')" \
    2>/dev/null || true)
fi
if [ -z "$SID" ]; then
  echo "session-scratch-init: no session id available — skipping"
  exit 0
fi

# Charset guard: SID becomes a literal path component below and must never
# carry a path separator or traversal sequence.
case "$SID" in
  */*|*..*)
    echo "session-scratch-init: unsafe session id '$SID' — skipping"
    exit 0
    ;;
esac

mkdir -p "$ROOT" 2>/dev/null || { echo "session-scratch-init: cannot create root $ROOT"; exit 0; }
chmod 1777 "$ROOT" 2>/dev/null || true

SESSION_DIR="$ROOT/$SID"
if ! mkdir -p "$SESSION_DIR" 2>/dev/null; then
  echo "session-scratch-init: cannot create $SESSION_DIR"
  exit 0
fi

# /proc/<pid>/stat field 22 (starttime): strip "pid (comm) " with a greedy
# match on "(.*)" so a comm containing its own parentheses is handled
# correctly (matches through the LAST ')'), then starttime is field 20 of
# what remains (state=1 ... starttime=20 in the post-comm field list).
PID_START=""
if [ -r "/proc/$PID/stat" ]; then
  PID_START=$(sed -E 's/^[0-9]+ \(.*\) //' "/proc/$PID/stat" 2>/dev/null | awk '{print $20}')
fi
BOOT_ID=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || true)
CREATED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)

OWNER_FILE="$SESSION_DIR/.owner"
TMP_OWNER="$SESSION_DIR/.owner.$$.tmp"
if python3 -c "
import json, sys
data = {
    'sid': sys.argv[1],
    'pid': sys.argv[2],
    'pid_start_time': sys.argv[3],
    'boot_id': sys.argv[4],
    'created_at': sys.argv[5],
}
with open(sys.argv[6], 'w') as fh:
    json.dump(data, fh)
" "$SID" "$PID" "$PID_START" "$BOOT_ID" "$CREATED_AT" "$TMP_OWNER" 2>/dev/null; then
  mv -f "$TMP_OWNER" "$OWNER_FILE" 2>/dev/null \
    || echo "session-scratch-init: failed to install .owner for $SID"
else
  echo "session-scratch-init: failed to write .owner for $SID"
  rm -f "$TMP_OWNER" 2>/dev/null || true
fi

exit 0
