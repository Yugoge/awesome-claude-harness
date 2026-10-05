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
# Degrade to $HOME/.claude on a resolver miss instead of hard-aborting under
# `set -e` (matches push.sh / apply-permissions.sh / resolve-close-report.sh).
CLAUDE_HOME="$(claude_home_resolve || echo "${HOME}/.claude")"

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

# In-place vs linked worktree detection (commands/dev-overnight.md's own
# isolation_kind vocabulary: "in_place" == worktree_path equals main_root).
# A linked (registered_worktree) worktree is always distinct from the main
# one (scripts/create-worktree.sh::validate_worktree enforces rp_wt != rp_main
# at creation time), so nothing else uses that directory while /merge runs.
# cwd being the main root carries no such exclusivity guarantee -- other
# sessions may hold uncommitted edits here right now -- so the checks below
# give that shape the equivalent safety the linked shape gets for free.
MAIN_WORKTREE_PATH="$(git worktree list --porcelain 2>/dev/null | awk '/^worktree /{print $2; exit}')"
CURRENT_TOPLEVEL="$(git rev-parse --show-toplevel)"
IS_IN_PLACE=false
if [ -n "$MAIN_WORKTREE_PATH" ] && [ "$(realpath "$MAIN_WORKTREE_PATH" 2>/dev/null)" = "$(realpath "$CURRENT_TOPLEVEL" 2>/dev/null)" ]; then
  IS_IN_PLACE=true
fi

if [ "$IS_IN_PLACE" = true ]; then
  DIRTY="$(git status --porcelain)"
  if [ -n "$DIRTY" ]; then
    echo "merge.sh: refusing to merge in_place with uncommitted changes present (equivalent of the linked worktree's exclusivity guarantee -- this directory may be shared with other sessions):" >&2
    echo "$DIRTY" >&2
    exit 2
  fi
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

  # Delete branch (worktree gone, so -d is safe; -d refuses unmerged but we just merged).
  # Skipped in_place: that branch is not a disposable linked-worktree branch,
  # so merging it does not imply deleting it too -- it stays on disk.
  if [ "$IS_IN_PLACE" = true ]; then
    echo "  ~ skipped branch deletion: $BRANCH_NAME (in_place merge keeps the source branch)"
  elif git branch -d "$BRANCH_NAME" 2>/dev/null; then
    echo "  ✓ deleted branch: $BRANCH_NAME"
  else
    echo "  ! branch $BRANCH_NAME not deleted (may be unmerged or detached)"
  fi

  # Cleanup overnight-state files referencing this branch
  # WS1: default to the resolved harness home, never the author literal /root.
  PROJ="${CLAUDE_PROJECT_DIR:-${CLAUDE_HOME}}"
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
