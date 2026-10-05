#!/bin/bash
# PreToolUse hook: Detect stale agent worktrees before ANY tool call
# Fires on all tools. Uses 60s cache to avoid git overhead on every call.
# Exit 0 = allow, Exit 2 = block (stderr shown to Claude)

set -euo pipefail

. "$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)/lib/harness_state_dir.sh" 2>/dev/null \
  || harness_state_dir() { printf '%s\n' /tmp; }
CACHE_FILE="$(harness_state_dir)/worktree-guard-cache"
CACHE_TTL=60

# Check cache: skip expensive git ops if checked recently
if [ -f "$CACHE_FILE" ]; then
  CACHE_AGE=$(( $(date +%s) - $(stat -c %Y "$CACHE_FILE" 2>/dev/null || echo 0) ))
  if [ "$CACHE_AGE" -lt "$CACHE_TTL" ]; then
    CACHED=$(cat "$CACHE_FILE")
    if [ "$CACHED" = "0" ]; then
      exit 0
    else
      # Re-check: stale worktrees may have been cleaned up
      :
    fi
  fi
fi

# Find git root
GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
MAIN_BRANCH=""

# Detect main branch name
for branch in master main; do
  if git rev-parse --verify "$branch" &>/dev/null; then
    MAIN_BRANCH="$branch"
    break
  fi
done
[ -z "$MAIN_BRANCH" ] && exit 0

MAIN_HEAD=$(git rev-parse "$MAIN_BRANCH" 2>/dev/null) || exit 0

# List all worktrees
WARNINGS=""
STALE_COUNT=0

while IFS= read -r line; do
  WT_PATH=$(echo "$line" | awk '{print $1}')
  WT_HEAD=$(echo "$line" | awk '{print $2}')

  # Skip main worktree
  [ "$WT_PATH" = "$GIT_ROOT" ] && continue
  # Skip if not an agent worktree
  echo "$WT_PATH" | grep -q "worktrees/agent-" || continue

  # Count how many commits behind
  BEHIND=$(git rev-list --count "$WT_HEAD".."$MAIN_HEAD" 2>/dev/null) || continue

  if [ "$BEHIND" -gt 0 ]; then
    STALE_COUNT=$((STALE_COUNT + 1))
    WT_NAME=$(basename "$WT_PATH")
    WARNINGS="${WARNINGS}
  - ${WT_NAME}: ${BEHIND} commits behind ${MAIN_BRANCH} (HEAD: ${WT_HEAD:0:7})"
  fi
done < <(git worktree list --porcelain 2>/dev/null | awk '
  /^worktree / { wt=$2 }
  /^HEAD / { head=$2; print wt, head }
')

# Update cache
echo "$STALE_COUNT" > "$CACHE_FILE"

if [ "$STALE_COUNT" -gt 0 ]; then
  echo "⚠️ STALE WORKTREE ALERT: ${STALE_COUNT} agent worktree(s) behind ${MAIN_BRANCH}:${WARNINGS}" >&2
  echo "" >&2
  echo "Action required: Remove stale worktrees before they cause merge conflicts:" >&2
  echo "  git worktree remove <path> --force && git branch -D <branch>" >&2
  echo "" >&2
  echo "NEVER use isolation:worktree for dev subagents. Work directly on ${MAIN_BRANCH}." >&2
  exit 2
fi

exit 0
