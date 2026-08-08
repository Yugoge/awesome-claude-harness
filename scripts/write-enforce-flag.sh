#!/usr/bin/env bash
# Write one or more enforcement-flag sentinels into a dev-registry session dir.
#
# Merges the bodies of write-codex-enforce.sh and write-e2e-enforce.sh, which
# were byte-for-byte identical apart from the output filename and the
# enforced_agent_types list. Both remain as thin wrappers around this script
# (commands/dev.md and commands/dev-command.md call them by name), so this is a
# consolidation, not a rename.
#
# --flag is repeatable, and that is the point: /dev-overnight needs BOTH flags
# and used to pay two script invocations for them. One invocation writing N
# sentinels is what actually reduces the call count; a single generic script
# called twice would not.
#
# Usage: write-enforce-flag.sh --source-command <dev|dev-overnight> \
#                              --session-id <DEV_SESSION_ID> \
#                              --flag <codex|e2e> [--flag <...>]
# Exits 1 on failure; callers must abort if this script fails.
set -euo pipefail

SOURCE_CMD=""
SESSION_ID=""
FLAGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-command) SOURCE_CMD="$2"; shift 2 ;;
    --session-id)     SESSION_ID="$2"; shift 2 ;;
    --flag)           FLAGS+=("$2"); shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

[[ -n "$SOURCE_CMD" ]] || { echo "ERROR: --source-command required" >&2; exit 1; }
[[ -n "$SESSION_ID" ]] || { echo "ERROR: --session-id required" >&2; exit 1; }
[[ ${#FLAGS[@]} -gt 0 ]] || { echo "ERROR: at least one --flag required" >&2; exit 1; }
# Same session-id shape check write-qa-mode.sh applies: the value becomes a path
# component, so a traversal or separator in it must never reach the filesystem.
[[ "$SESSION_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || {
  echo "ERROR: --session-id contains unsafe characters: $SESSION_ID" >&2; exit 1; }

REGISTRY_DIR="${CLAUDE_PROJECT_DIR:?CLAUDE_PROJECT_DIR not set}/.claude/dev-registry/$SESSION_ID"
CREATED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Per-flag definitions: output filename + the agent types the gate applies to.
flag_filename() {
  case "$1" in
    codex) echo "codex-enforce.json" ;;
    e2e)   echo "e2e-enforce.json" ;;
    *)     return 1 ;;
  esac
}
flag_agent_types() {
  case "$1" in
    codex) echo '["ba", "dev", "qa"]' ;;
    e2e)   echo '["qa"]' ;;
    *)     return 1 ;;
  esac
}

mkdir -p "$REGISTRY_DIR" \
  || { echo "ERROR: Failed to create registry dir $REGISTRY_DIR — aborting." >&2; exit 1; }

for flag in "${FLAGS[@]}"; do
  filename="$(flag_filename "$flag")" || {
    echo "ERROR: unknown --flag '$flag' (expected: codex, e2e)" >&2; exit 1; }
  agent_types="$(flag_agent_types "$flag")"
  target="$REGISTRY_DIR/$filename"

  printf '{
  "schema_version": 1,
  "enabled": true,
  "source_command": "%s",
  "dev_session_id": "%s",
  "claude_session_id": "%s",
  "enforced_agent_types": %s,
  "created_at": "%s"
}\n' "$SOURCE_CMD" "$SESSION_ID" "${CLAUDE_SESSION_ID:-unknown}" "$agent_types" "$CREATED_AT" \
    > "$target" \
    || { echo "ERROR: Failed to write $filename at $target — aborting." >&2; exit 1; }

  echo "${flag} enforcement active: $target"
done
