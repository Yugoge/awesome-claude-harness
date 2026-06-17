#!/usr/bin/env bash
# Description: SessionStart hook that promotes a cold session back to ramdisk.
# Reads hook JSON on stdin (fields: session_id, cwd, hook_event_name, ...).
# Invokes the session-promote helper in the background so the hook does NOT
# block session startup. Always exits 0.
#
# WS1: this is an OPTIONAL author-environment capability (RAM-disk promotion).
# The on-ramdisk project root is derived from the resolved harness home, and the
# external helper is resolved via $SESSION_PROMOTE_BIN — absent => degrade
# silently (the hook already always exits 0), NEVER the author literal /root.
#
# Input example:
#   {"session_id":"abc-...","cwd":"/some/home",...}

# Do NOT use `set -e` here: the hook must never fail Claude Code startup.

LOG="/var/log/claude-tier.log"

# WS1: resolve the harness home from this script's own location (optional — this
# hook degrades gracefully if unresolved).
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/claude_home.sh" 2>/dev/null || true
CLAUDE_HOME="$(claude_home_resolve 2>/dev/null || true)"

log_hook() {
  local ts
  ts="$(date -Iseconds 2>/dev/null || echo now)"
  printf '%s [hook] %s\n' "$ts" "$1" >> "$LOG" 2>/dev/null || true
}

# Read stdin into a variable (small JSON; cap at ~1MB for safety).
payload=""
if [[ ! -t 0 ]]; then
  # Non-empty stdin
  payload="$(head -c 1048576 2>/dev/null || true)"
fi

if [[ -z "$payload" ]]; then
  # Some SessionStart invocations may not pass stdin. Nothing to do.
  exit 0
fi

# Extract session_id and cwd using python (robust across JSON formatting).
# If either is missing, exit silently.
parsed="$(
  printf '%s' "$payload" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
sid = d.get("session_id") or d.get("sessionId") or ""
cwd = d.get("cwd") or d.get("workingDirectory") or ""
# Basic sanitation: no newlines/tabs
sid = sid.strip().replace("\n", "").replace("\t", "")
cwd = cwd.strip().replace("\n", "").replace("\t", "")
print(sid)
print(cwd)
' 2>/dev/null || true
)"

SESSION_ID="$(printf '%s\n' "$parsed" | sed -n '1p')"
CWD="$(printf '%s\n' "$parsed" | sed -n '2p')"

if [[ -z "$SESSION_ID" || -z "$CWD" ]]; then
  exit 0
fi

# UUID sanity: require the canonical 8-4-4-4-12 shape. If the shape does not
# match, this is almost certainly a new session (Claude Code generates a UUID
# either way), and promote.sh itself will also validate -- but we bail early
# to avoid forking a no-op child.
if [[ ! "$SESSION_ID" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
  exit 0
fi

# Claude Code maps CWD to project dir by replacing '/' with '-'.
# e.g. /root -> -root; /dev/shm/dev-workspace/applio -> -dev-shm-dev-workspace-applio
# Strategy: replace every '/' with '-'. A leading '/' becomes a leading '-'.
PROJECT_NAME="$(printf '%s' "$CWD" | sed 's|/|-|g')"

if [[ -z "$PROJECT_NAME" || "$PROJECT_NAME" == "-" ]]; then
  exit 0
fi

# WS1: the on-ramdisk project root lives under the resolved harness home's
# realpath (the author's /dev/shm tmpfs root that ~/.claude symlinks to). If the
# home is unresolved there is nothing to promote — degrade silently.
if [[ -z "$CLAUDE_HOME" ]]; then
  exit 0
fi
RAM_ROOT="$(_claude_home_realpath "$CLAUDE_HOME" 2>/dev/null || echo "$CLAUDE_HOME")"

# Only act if the on-ramdisk .jsonl is a symlink (archived). Saves a subshell
# fork on every single session start.
RAM_JSONL="${RAM_ROOT}/projects/$PROJECT_NAME/$SESSION_ID.jsonl"
if [[ ! -L "$RAM_JSONL" ]]; then
  # Either the session is already hot, or it's brand new (file not yet created).
  # Either way, nothing to promote.
  exit 0
fi

# WS1 (AC-WS3-6): resolve the OPTIONAL external promote helper via
# $SESSION_PROMOTE_BIN. Absent => this author-environment capability is simply
# unavailable on this machine; log one line and degrade (never a bare fallback).
PROMOTE_BIN="${SESSION_PROMOTE_BIN:-}"
if [[ -z "$PROMOTE_BIN" || ! -x "$PROMOTE_BIN" ]]; then
  log_hook "session-promote: unavailable (set SESSION_PROMOTE_BIN to enable RAM-disk promotion); skipping (optional)"
  exit 0
fi

log_hook "queue promote $PROJECT_NAME/$SESSION_ID"

# Fire and forget. Disown to fully detach from the hook's process group so
# Claude Code's hook pipeline doesn't wait on it.
( "$PROMOTE_BIN" "$SESSION_ID" "$PROJECT_NAME" \
    >> "$LOG" 2>&1 & disown ) 2>/dev/null

exit 0
