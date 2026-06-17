#!/usr/bin/env bash
# apply-permissions.sh — merge aggregated permissions JSON list into settings.json
# Usage: apply-permissions.sh <permissions.json> [settings.json]
set -euo pipefail

# WS1: resolve the harness home via the shared claude_home resolver (this script
# lives at <harness home>/scripts/, so the resolver is at ../hooks/lib). The
# fallback is the resolved home (then $HOME), NEVER the author literal /root.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../hooks/lib" && pwd)/claude_home.sh"
_CLAUDE_HOME_FALLBACK="$(claude_home_resolve || echo "$HOME")"

resolve_project_dir() {
  for v in "${CLAUDE_PROJECT_DIR:-}" "$(pwd)"; do
    [ -n "$v" ] && [ -d "$v" ] && { echo "$v"; return; }
  done
  git rev-parse --show-toplevel 2>/dev/null || echo "$_CLAUDE_HOME_FALLBACK"
}

PERMS="${1:?Missing permissions JSON path}"
PROJECT_DIR="$(resolve_project_dir)"
SETTINGS="${2:-$PROJECT_DIR/.claude/settings.json}"
[ -f "$SETTINGS" ] || { echo "settings.json not found: $SETTINGS" >&2; exit 1; }
[ -f "$PERMS" ]    || { echo "perms file not found: $PERMS" >&2; exit 1; }
TMP="$(mktemp)"
jq --slurpfile p "$PERMS" '
  .permissions //= {allow:[], ask:[], deny:[]} |
  reduce $p[0][] as $entry (.;
    .permissions[$entry.section] //= [] |
    if (.permissions[$entry.section] | index($entry.pattern)) then .
    else .permissions[$entry.section] += [$entry.pattern] end)
' "$SETTINGS" > "$TMP"
mv "$TMP" "$SETTINGS"
