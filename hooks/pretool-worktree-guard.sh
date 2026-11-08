#!/bin/bash
# PreToolUse hook: Detect stale agent worktrees before ANY tool call
# Fires on all tools. Uses 60s cache to avoid git overhead on every call.
# Advisory: always exit 0. While an agent worktree is behind the main branch it
# prints PreToolUse JSON: additionalContext carries the lesson to Claude,
# systemMessage tells the user.
#
# It never blocks (2026-11-08). It used to exit 2 on every tool while a stale
# worktree existed, so it blocked the `git worktree remove` it asked for, the
# status/Read calls that check a worktree for unsaved work, and AskUserQuestion:
# only the human could end that state. The other half of its old advice,
# `git branch -D`, is an agent-forbidden ref deletion (pretool-bash-safety.sh,
# pretool-git-privilege-guard.py), so branch deletion is now left to the user.

set -euo pipefail
# Exit 2 is Claude Code's block code. Every way out of this hook, an unexpected
# failure under set -e included, leaves with 0, so no repository state can turn
# the warning into a lock.
trap 'exit 0' EXIT

. "$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)/lib/harness_state_dir.sh" 2>/dev/null \
  || harness_state_dir() { printf '%s\n' /tmp; }
CACHE_FILE="$(harness_state_dir)/worktree-guard-cache"
CACHE_TTL=60

# Check cache: skip expensive git ops if checked recently
if [ -f "$CACHE_FILE" ]; then
  CACHE_AGE=$(( $(date +%s) - $(stat -c %Y "$CACHE_FILE" 2>/dev/null || echo 0) ))
  if [ "$CACHE_AGE" -lt "$CACHE_TTL" ]; then
    CACHED=$(cat "$CACHE_FILE" 2>/dev/null || true)
    if [ "$CACHED" = "0" ]; then
      exit 0
    fi
    # Otherwise re-check: stale worktrees may have been cleaned up
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

WARNINGS=""
STALE_COUNT=0
WT_PATH="" WT_HEAD="" WT_BRANCH="" WT_FLAGS=""

# One `git worktree list --porcelain` record has been read: count it if it is an
# agent worktree behind the main branch.
check_worktree() {
  [ -n "$WT_PATH" ] && [ -n "$WT_HEAD" ] || return 0
  # Skip main worktree
  [ "$WT_PATH" = "$GIT_ROOT" ] && return 0
  # Skip if not an agent worktree
  case "$WT_PATH" in *worktrees/agent-*) ;; *) return 0 ;; esac

  # Count how many commits behind
  local behind
  behind=$(git rev-list --count "$WT_HEAD".."$MAIN_HEAD" 2>/dev/null) || return 0
  [ "$behind" -gt 0 ] 2>/dev/null || return 0

  STALE_COUNT=$((STALE_COUNT + 1))
  WARNINGS="${WARNINGS}
  - ${WT_PATH##*/}: ${behind} commits behind ${MAIN_BRANCH} (HEAD: ${WT_HEAD:0:7}, ${WT_BRANCH:-detached HEAD})${WT_FLAGS}
      git worktree remove $(printf '%q' "$WT_PATH")"
}

# Whole lines, so a path with spaces stays whole; the trailing echo closes the
# last record.
while IFS= read -r line; do
  case "$line" in
    "worktree "*) WT_PATH=${line#worktree } ;;
    "HEAD "*) WT_HEAD=${line#HEAD } ;;
    "branch "*) WT_BRANCH="branch ${line#branch refs/heads/}" ;;
    locked) WT_FLAGS="${WT_FLAGS} [locked]" ;;
    "locked "*) WT_FLAGS="${WT_FLAGS} [locked: ${line#locked }]" ;;
    prunable*) WT_FLAGS="${WT_FLAGS} [directory missing]" ;;
    "")
      check_worktree
      WT_PATH="" WT_HEAD="" WT_BRANCH="" WT_FLAGS=""
      ;;
  esac
done < <(git worktree list --porcelain 2>/dev/null; echo)

# Update cache (best effort: an unwritable state dir must not hide the warning)
{ echo "$STALE_COUNT" > "$CACHE_FILE"; } 2>/dev/null || true

# A JSON string body: escape \ " and the usual whitespace, drop other control
# characters.
json_escape() {
  local s=$1
  s=${s//\\/\\\\}
  s=${s//\"/\\\"}
  s=${s//$'\t'/\\t}
  s=${s//$'\r'/\\r}
  s=${s//$'\n'/\\n}
  printf '%s' "$s" | LC_ALL=C tr -d '\000-\037'
}

if [ "$STALE_COUNT" -gt 0 ]; then
  CONTEXT="STALE WORKTREE ALERT: ${STALE_COUNT} agent worktree(s) behind ${MAIN_BRANCH}:${WARNINGS}

A stale worktree causes merge conflicts: work done in it starts from an old ${MAIN_BRANCH}.
Action required: remove stale worktrees before they cause merge conflicts. This hook never blocks the removal.
  - git worktree remove <path> refuses while the worktree holds uncommitted or untracked files: check them first (git -C <path> status); --force discards them.
  - A locked worktree may belong to a running agent: leave it, or run git worktree unlock <path> first.
  - The branch stays after its worktree is removed. Branch deletion (git branch -D) is closed to agents: ask the user.

NEVER use isolation:worktree for dev subagents. Work directly on ${MAIN_BRANCH}."
  SUMMARY="Stale worktree alert: ${STALE_COUNT} agent worktree(s) behind ${MAIN_BRANCH}. A stale worktree causes merge conflicts; Claude has been told how to remove it."
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"%s"},"systemMessage":"%s"}\n' \
    "$(json_escape "$CONTEXT")" "$(json_escape "$SUMMARY")"
fi

exit 0
