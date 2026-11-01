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
# Readable, not regular: /dev/stdin takes the list from a pipe (/dev and /dev-command).
[ -r "$PERMS" ]    || { echo "perms file not found: $PERMS" >&2; exit 1; }
# The file is read through the one load of a settings file (hooks/lib/claude_home.py): an
# unusable one refuses the merge with its reason and stays as it is; a missing one is an empty
# object to the merge, so the file is created when the merge adds an entry; a merge that adds
# nothing writes nothing.
CURRENT="$(python3 "$(dirname "${BASH_SOURCE[0]}")/../hooks/lib/claude_home.py" settings "$SETTINGS")" \
  || { echo "apply-permissions: nothing merged; $SETTINGS stays as it is" >&2; exit 1; }
TMP="$(mktemp)"
jq -n --slurpfile p "$PERMS" --argjson in "${CURRENT:-"{}"}" '
  $in |
  reduce $p[0][] as $entry (.;
    if (.permissions[$entry.section] // [] | index($entry.pattern)) then .
    else .permissions //= {allow:[], ask:[], deny:[]} |
      .permissions[$entry.section] += [$entry.pattern] end) |
  if . == $in then empty else . end
' > "$TMP"
if [ -s "$TMP" ]; then mkdir -p "$(dirname "$SETTINGS")"; mv "$TMP" "$SETTINGS"; else rm -f "$TMP"; fi
