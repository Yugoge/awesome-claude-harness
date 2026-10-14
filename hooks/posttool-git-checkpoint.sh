#!/bin/bash
# posttool-git-checkpoint.sh - PostToolUse checkpoint trigger
# Writes snapshots to refs/checkpoints/<branch> via the shared lib,
# so HEAD and branch refs are NEVER moved by auto-saves.
#
# Worktree awareness: detects when the edited file is inside a
# .claude/worktrees/ directory and targets that worktree instead of the
# main repo.

# Configuration
CHECKPOINT_THRESHOLD=${GIT_CHECKPOINT_THRESHOLD:-10}  # Default: 10 files accumulated
SILENT_MODE=${GIT_CHECKPOINT_SILENT:-0}

# Worktree detection: parse TOOL_INPUT to find file_path, detect worktree context
GIT_DIR=""
if [ -n "$TOOL_INPUT" ]; then
  FILE_PATH=$(echo "$TOOL_INPUT" | grep -o '"file_path"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"file_path"[[:space:]]*:[[:space:]]*"//;s/"$//')

  if [ -n "$FILE_PATH" ]; then
    if echo "$FILE_PATH" | grep -q '/.claude/worktrees/[^/]\+/'; then
      WORKTREE_ROOT=$(echo "$FILE_PATH" | sed 's|\(.*/.claude/worktrees/[^/]*/\).*|\1|')
      if [ -d "$WORKTREE_ROOT" ]; then
        GIT_DIR="$WORKTREE_ROOT"
        if [ "$SILENT_MODE" != "1" ]; then
          echo "📂 Worktree detected: $GIT_DIR"
        fi
      fi
    fi
  fi
fi

# Allow explicit override via environment variable
GIT_DIR="${GIT_CHECKPOINT_DIR:-$GIT_DIR}"

# Build git command for counting only (no commit is issued here; the lib handles commits)
if [ -n "$GIT_DIR" ]; then
  GIT_CMD="git -C $GIT_DIR"
else
  GIT_CMD="git"
fi

# Count changes (threshold gating)
STAGED=$($GIT_CMD diff --cached --name-only 2>/dev/null | wc -l)
MODIFIED=$($GIT_CMD diff --name-only 2>/dev/null | wc -l)
UNTRACKED=$($GIT_CMD ls-files --others --exclude-standard 2>/dev/null | wc -l)
TOTAL=$((STAGED + MODIFIED + UNTRACKED))

# Exit if no changes
if [ "$TOTAL" -eq 0 ]; then
  exit 0
fi

# Threshold gate
if [ "$TOTAL" -ge "$CHECKPOINT_THRESHOLD" ]; then
  if [ "$SILENT_MODE" != "1" ]; then
    echo "💾 Auto-checkpoint triggered: $TOTAL files pending"
  fi

  # Source lib and delegate. Lib writes to refs/checkpoints/<branch>, never HEAD.
  # shellcheck source=lib/checkpoint-core.sh
  . "$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)/lib/checkpoint-core.sh"

  if write_checkpoint "$GIT_DIR" "posttool threshold (${TOTAL} files, threshold=${CHECKPOINT_THRESHOLD})"; then
    if [ "$SILENT_MODE" != "1" ]; then
      BRANCH=$($GIT_CMD branch --show-current 2>/dev/null)
      if [ -n "$BRANCH" ]; then
        SANITIZED=$(printf '%s' "$BRANCH" | tr '/' '-')
      else
        SHORT=$($GIT_CMD rev-parse --short HEAD 2>/dev/null)
        SANITIZED="detached-${SHORT:-empty}"
      fi
      REF="refs/checkpoints/${SANITIZED}"
      TIP=$($GIT_CMD rev-parse --short "$REF" 2>/dev/null)
      echo "✅ Checkpoint saved: ${TIP:-?} on ${REF} (${TOTAL} files)"
    fi
  else
    if [ "$SILENT_MODE" != "1" ]; then
      echo "⚠️  Checkpoint failed; see ~/.claude/logs/checkpoint.log"
    fi
  fi
fi

exit 0
