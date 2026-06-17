#!/usr/bin/env bash
# merge.sh - wrapper for /merge slash command
#
# Why this exists: pretool-git-privilege-guard.py raw-greps for the literal
# string "git" + space + "merge" in command text and rejects it unless the
# env var CLAUDE_MERGE_COMMAND_ACTIVE=1 is set in the hook's process env.
# main-agent shell never has that env set, so the inline checkout+merge
# pattern in merge.md was unrunnable from agent context. This wrapper runs
# the merge in its OWN subprocess (which does not go through main-agent
# PreToolUse), exporting the env var locally so the privilege-guard inside
# the subprocess admits the inner command.
#
# Sentinel check mirrors commit.sh/push.sh (2026-04-28 SlashCommand-bypass plug).
set -euo pipefail

# Sentinel enforcement is handled by pretool-wrapper-userintent.py (PreToolUse hook)
# before this script runs. The wrapper itself stays pure git work.

# WS1: resolve the harness home from this script's own location (hooks/merge.sh
# -> harness home) via the shared resolver, so helper paths + the project-dir
# default work on a fresh non-root clone instead of the author literal /root.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/claude_home.sh"
CLAUDE_HOME="$(claude_home_resolve)"

# Args
BRANCH_NAME="${1:-}"
if [ -z "$BRANCH_NAME" ]; then
  echo "merge.sh: branch name required (Usage: merge.sh <worktree-branch>)" >&2
  exit 2
fi

# Resolve default branch via existing helper (under the resolved harness home)
DEFAULT_BRANCH="$("${CLAUDE_HOME}/scripts/derive-default-branch.sh")"
if [ -z "$DEFAULT_BRANCH" ]; then
  echo "merge.sh: could not resolve default branch" >&2
  exit 1
fi

# Verify worktree branch exists
if ! git show-ref --verify --quiet "refs/heads/$BRANCH_NAME"; then
  echo "merge.sh: branch $BRANCH_NAME does not exist" >&2
  exit 1
fi

# Untracked-overlap preflight (spec 5.2.1.3 R3b)
OVERLAP="$(git ls-files --others --exclude-standard | sort -u)"
if [ -n "$OVERLAP" ]; then
  TOUCHED="$(git diff --name-only "$DEFAULT_BRANCH" "$BRANCH_NAME" | sort -u)"
  CONFLICTS="$(comm -12 <(echo "$OVERLAP") <(echo "$TOUCHED") || true)"
  if [ -n "$CONFLICTS" ]; then
    echo "untracked overlap detected:" >&2
    echo "$CONFLICTS" >&2
    exit 2
  fi
fi

echo "merge.sh: merging $BRANCH_NAME into $DEFAULT_BRANCH"

# Export env so the inner subprocess command passes privilege-guard
export CLAUDE_MERGE_COMMAND_ACTIVE=1

# Checkout default branch + perform the merge.
# Disable set -e around the merge so we can capture the exit code and emit
# clear conflict-resolution instructions instead of dying silently.
git checkout "$DEFAULT_BRANCH"
set +e
git merge "$BRANCH_NAME" --no-edit
MERGE_RC=$?
set -e

if [ $MERGE_RC -ne 0 ]; then
  cat >&2 <<EOF
merge.sh: git merge exited $MERGE_RC — likely conflicts. Cleanup SKIPPED.

Resolve manually, then re-invoke:
  1. git status                # inspect conflicting files
  2. <edit files to resolve conflicts>
  3. git add <files>
  4. git commit                # complete the merge commit
  5. /merge $BRANCH_NAME       # re-run via slash command to finish cleanup
                               # (worktree remove, branch delete, state file removal)

The wrapper is idempotent: re-running after a clean merge skips re-merging
("Already up to date") and executes only the cleanup section.
EOF
  exit $MERGE_RC
fi

# ─── Cleanup after successful merge ──────────────────────────────────────
# Only execute when:
#   1. The merge subprocess returned 0 (no conflicts; set -euo pipefail above
#      ensures we never reach here on failure)
#   2. The default branch HEAD now contains the worktree branch's tip
#      (sanity check via diff vs branch — should be clean post-merge)
if git diff --quiet "$BRANCH_NAME" 2>/dev/null; then
  echo "merge.sh: post-merge sanity OK; cleaning up worktree + branch + overnight state files"

  # Locate worktree path (if branch was checked out as a worktree)
  WORKTREE_PATH=$(git worktree list --porcelain 2>/dev/null | awk -v b="refs/heads/$BRANCH_NAME" 'BEGIN{p=""} /^worktree /{p=$2} $1=="branch" && $2==b{print p; exit}')

  if [ -n "$WORKTREE_PATH" ] && [ -d "$WORKTREE_PATH" ]; then
    git worktree remove "$WORKTREE_PATH" --force 2>/dev/null && \
      echo "  ✓ removed worktree: $WORKTREE_PATH" || \
      echo "  ! could not remove worktree: $WORKTREE_PATH"
  fi

  # Delete branch (worktree gone, so -d is safe; -d refuses unmerged but we just merged)
  if git branch -d "$BRANCH_NAME" 2>/dev/null; then
    echo "  ✓ deleted branch: $BRANCH_NAME"
  else
    echo "  ! branch $BRANCH_NAME not deleted (may be unmerged or detached)"
  fi

  # Cleanup overnight-state files referencing this branch
  PROJ="${CLAUDE_PROJECT_DIR:-/root}"
  for sf in "$PROJ/.claude"/overnight-state-*.json; do
    [ -f "$sf" ] || continue
    STATE_BRANCH=$(python3 -c "
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print(d.get('worktree_branch') or d.get('branch') or d.get('focus_branch') or '')
except Exception:
    pass
" "$sf" 2>/dev/null || echo "")
    if [ "$STATE_BRANCH" = "$BRANCH_NAME" ]; then
      rm -f "$sf"
      echo "  ✓ removed overnight-state: $sf"
    fi
  done
else
  echo "merge.sh: post-merge sanity check failed (diff vs $BRANCH_NAME non-empty); cleanup SKIPPED — manually inspect" >&2
fi

echo "merge.sh: merge complete on $DEFAULT_BRANCH"
