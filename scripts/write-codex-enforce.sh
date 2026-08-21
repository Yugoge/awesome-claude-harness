#!/usr/bin/env bash
# Writes codex-enforce.json into the dev-registry for the given session.
# Usage: write-codex-enforce.sh --source-command <dev|dev-overnight> --session-id <DEV_SESSION_ID>
# Exits 1 on failure; callers must abort if this script fails.
set -euo pipefail

SOURCE_CMD=""
SESSION_ID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-command) SOURCE_CMD="$2"; shift 2 ;;
    --session-id)     SESSION_ID="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

[[ -n "$SOURCE_CMD" ]] || { echo "ERROR: --source-command required" >&2; exit 1; }
[[ -n "$SESSION_ID" ]] || { echo "ERROR: --session-id required" >&2; exit 1; }

ENFORCE_FLAG="${CLAUDE_PROJECT_DIR:?CLAUDE_PROJECT_DIR not set}/.claude/dev-registry/$SESSION_ID/codex-enforce.json"

printf '{
  "schema_version": 1,
  "enabled": true,
  "source_command": "%s",
  "dev_session_id": "%s",
  "claude_session_id": "%s",
  "enforced_agent_types": ["ba", "dev", "qa"],
  "created_at": "%s"
}\n' "$SOURCE_CMD" "$SESSION_ID" "${CLAUDE_SESSION_ID:-unknown}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  > "$ENFORCE_FLAG" \
  || { echo "ERROR: Failed to write codex-enforce.json at $ENFORCE_FLAG — aborting." >&2; exit 1; }

echo "Codex enforcement active: $ENFORCE_FLAG"
