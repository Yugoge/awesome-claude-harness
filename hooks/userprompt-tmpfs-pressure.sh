#!/bin/bash
# userprompt-tmpfs-pressure.sh — UserPromptSubmit hook (4th block, appended).
#
# Layer 1.5 of the tmpfs-pressure prevention plan (dev-20260519-161035).
# On each user prompt, when /tmp and/or /dev/shm exceed 75% utilization, emit
# a non-blocking warning showing df -h plus the top-5 largest directories under
# EACH pressured mount (one block per pressured mount). Rate-limit to AT MOST
# 3 emissions per session.
#
# Non-blocking: exits 0 unconditionally; never blocks the user prompt.
# `df` and `du` are invoked via PATH lookup (bare commands) per OBJ-5 so the
# QA test driver's PATH-shim layer can substitute synthetic >75% scenarios
# without risking real tmpfs fill.
#
# Token derivation priority (session identity for the rate-limit counter):
#   1. stdin JSON `session_id` field (preferred; guaranteed unique per session)
#   2. CLAUDE_SESSION_ID env var
#   3. hashed PPID+process-start-time fallback (last resort)
#
# Counter file: /tmp/claude-pressure-warn-<sanitized_token>
# Lock file:    /tmp/claude-pressure-warn-<sanitized_token>.lock
# Both are regular files (flock primitive is the SOLE acceptable lock per OBJ-3;
# atomic-mkdir is FORBIDDEN — lock directories would never match the M3
# `-type f` hook-state sweep predicate and would leak indefinitely). Both
# are swept by /usr/local/sbin/tmp-cleanup.sh via the `claude-pressure-warn-*`
# wildcard at the >7d hook-state tier.

set -u

THRESHOLD=75
RATE_LIMIT=3

# ── Token derivation ─────────────────────────────────────────────────
# UserPromptSubmit hook receives a JSON envelope on stdin (same as prompt-workflow.py).
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

. "$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)/lib/harness_state_dir.sh" 2>/dev/null \
  || harness_state_dir() { printf '%s\n' /tmp; }
COUNTER_FILE="$(harness_state_dir)/claude-pressure-warn-${SANITIZED}"
LOCK_FILE="${COUNTER_FILE}.lock"

# ── Pressure detection ───────────────────────────────────────────────
# df --output=pcent emits a 2-line header + per-mount lines on most GNU coreutils;
# we strip the header with `tail -n +2`. The `Use%` column comes with a trailing
# percent sign that we strip. PATH-resolved bare `df` per OBJ-5. Wrapped in
# `timeout 2s` so a hung df cannot block the hook (codex review F2).
pressured=()
mapfile -t df_pct < <(timeout 2s df --output=pcent /tmp /dev/shm 2>/dev/null | tail -n +2 | tr -d '% ' || true)
mounts=(/tmp /dev/shm)

for i in 0 1; do
  pct="${df_pct[$i]:-0}"
  case "$pct" in
    ''|*[!0-9]*) pct=0 ;;
  esac
  if [ "$pct" -gt "$THRESHOLD" ]; then
    pressured+=("${mounts[$i]}")
  fi
done

# Neither mount over threshold → silent exit (do NOT consume a rate-limit slot).
if [ "${#pressured[@]}" -eq 0 ]; then
  exit 0
fi

# ── Atomic rate-limit decision via flock ─────────────────────────────
# fd 9 MUST be opened INSIDE the command substitution via a redirected
# brace-group (codex F1). The trailing-redirection form
# `decision=$(...) 9>"$LOCK_FILE"` is REJECTED because fd 9 is not reliably
# visible to commands running inside the command substitution in that shape.
#
# The lock-protected critical section returns either `emit` or `skip` to the
# parent shell via stdout. The parent shell short-circuits on `skip` — a bare
# `exit 0` inside the subshell only exits the subshell, not the parent hook.
decision=$(
  {
    # Bounded flock (-w 1) so contention with a long-running concurrent hook
    # invocation or with the daily cleanup script's xargs rm on this lock file
    # cannot block the user prompt (codex review F1). On contention we skip
    # the warning rather than waiting — the next prompt re-tries.
    flock -x -w 1 9 || { printf 'skip'; exit 0; }
    n=$(cat "$COUNTER_FILE" 2>/dev/null || echo 0)
    case "$n" in
      ''|*[!0-9]*) n=0 ;;
    esac
    if [ "$n" -ge "$RATE_LIMIT" ]; then
      # F7: refresh saturated counter's mtime so the >7d hook-state sweep
      # cannot delete an actively-saturated counter mid-session and reset
      # the ≤3/session guarantee for long-lived sessions. This is NOT slot
      # consumption — only mtime refresh.
      # arch-3 (spec R5a): ENOSPC/EISDIR guard — if write fails, skip rather
      # than crashing the subshell. 2>/dev/null placed before > so EISDIR stderr
      # is suppressed before the output redirect is evaluated (Bash left-to-right).
      printf '%s\n' "$n" 2>/dev/null > "$COUNTER_FILE" || { printf 'skip'; exit 0; }
      printf 'skip'
    else
      # arch-3 (spec R5a): ENOSPC/EISDIR guard — if counter write fails, emit
      # 'skip' so the warning is suppressed rather than misfiring on every prompt.
      if ! printf '%s\n' "$((n + 1))" 2>/dev/null > "$COUNTER_FILE"; then
        printf 'skip'
        exit 0
      fi
      printf 'emit'
    fi
  } 2>/dev/null 9> "$LOCK_FILE"
)

[ "$decision" = "emit" ] || exit 0

# ── Emit the warning ─────────────────────────────────────────────────
echo
echo "[tmpfs-pressure] WARN: one or more tmpfs mounts above ${THRESHOLD}% — non-blocking notice"
# df -h wrapped in `timeout 2s` so a hung df cannot block the hook (codex F2).
timeout 2s df -h /tmp /dev/shm 2>/dev/null || true
for mount in "${pressured[@]}"; do
  echo "--- top-5 dirs under ${mount} ---"
  # GNU du -sh --max-depth=1 is broken — -s conflicts with --max-depth=1.
  # Use -xh --max-depth=1, filter the root row by awk on the path column,
  # sort by size descending, head -5. The outer `timeout 5s` covers the
  # ENTIRE pipeline (du + awk + sort + head) per codex review F2 so a
  # hung sort or stalled head also cannot exceed the time bound.
  # PATH-resolved bare `du` per OBJ-5.
  timeout 5s bash -c "du -xh --max-depth=1 '$mount' 2>/dev/null \
    | awk -v m='$mount' '\$2 != m' \
    | sort -hr \
    | head -5" \
    || true
done
echo

exit 0
