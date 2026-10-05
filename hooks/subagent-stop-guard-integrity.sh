#!/usr/bin/env bash
# subagent-stop-guard-integrity.sh
# Triggers: SubagentStop.
# Purpose: If BA's context lists pre_existing_guards with removal_authorized=false,
#          check whether recent diff (HEAD~5..HEAD + uncommitted) removes that guard.
# Non-blocking: always exit 0. Degrades gracefully.

set -euo pipefail

# Prevent stacking: concurrent SubagentStop hooks skip instead of piling up CPU.
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)/lib/harness_state_dir.sh" 2>/dev/null \
  || harness_state_dir() { printf '%s\n' /tmp; }
exec 9>"$(harness_state_dir)/.subagent-stop-guard-integrity.lock"
flock -n 9 || exit 0

cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

ctx=$(ls -t docs/dev/context-*.json 2>/dev/null | head -1 || true)
[ -z "$ctx" ] && exit 0

# Extract guards that must not be removed
guards=$(jq -c '.pre_existing_guards // [] | map(select(.removal_authorized == false))' \
  "$ctx" 2>/dev/null || echo "[]")

if [ "$guards" = "[]" ] || [ -z "$guards" ] || [ "$guards" = "null" ]; then
  exit 0
fi

# Collect recent + uncommitted diffs. Each branch may fail; tolerate.
diff_recent=$(git diff HEAD~5..HEAD 2>/dev/null || true)
diff_uncommitted=$(git diff 2>/dev/null || true)
diff="${diff_recent}
${diff_uncommitted}"

if ! printf '%s' "$diff" | grep -q '[^[:space:]]'; then
  exit 0
fi

# Iterate guards; for each, look for snippet appearing on a removed (-) line.
echo "$guards" | jq -c '.[]' 2>/dev/null | while IFS= read -r guard; do
  [ -z "$guard" ] && continue
  snippet=$(echo "$guard" | jq -r '.code_snippet // empty' 2>/dev/null || true)
  purpose=$(echo "$guard" | jq -r '.purpose // "unspecified"' 2>/dev/null || true)
  file=$(echo "$guard"   | jq -r '.file    // "unknown"'     2>/dev/null || true)

  [ -z "$snippet" ] && continue

  # Escape regex metacharacters in the snippet
  escaped=$(printf '%s' "$snippet" | sed 's/[][\.*^$/+?(){}|]/\\&/g')

  if printf '%s\n' "$diff" | grep -qE "^-.*${escaped}"; then
    cat >&2 <<EOF
UNAUTHORIZED GUARD REMOVAL
File: $file
Guard: $snippet
Purpose: $purpose
This guard has removal_authorized=false. Removing it requires BA authorization.
Context: $ctx
EOF
  fi
done

exit 0
