#!/bin/bash
# posttool-git-checkpoint.sh - PostToolUse checkpoint trigger
# Writes snapshots to refs/checkpoints/<branch> via the shared lib,
# so HEAD and branch refs are NEVER moved by auto-saves.
#
# Worktree awareness: detects when the edited file is inside a
# .claude/worktrees/ directory and targets that worktree instead of the
# main repo.
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib/harness_switch.sh" && harness_switch_exit_if_off  # the harness switch: no harness hook runs while /harness off holds

# Configuration
CHECKPOINT_THRESHOLD=${GIT_CHECKPOINT_THRESHOLD:-10}  # Default: 10 files accumulated
SILENT_MODE=${GIT_CHECKPOINT_SILENT:-0}

# Worktree detection: the payload on stdin names the file the tool wrote (the CLI passes
# hook input on stdin only); a file inside .claude/worktrees/<name>/ is checkpointed in
# that worktree instead of the main repo.
GIT_DIR=""
INPUT=$(cat 2>/dev/null || true)
FILE_PATH=$(printf '%s' "$INPUT" | grep -o '"file_path"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"file_path"[[:space:]]*:[[:space:]]*"//;s/"$//')
if [ -n "$FILE_PATH" ]; then
  if echo "$FILE_PATH" | grep -q '/.claude/worktrees/[^/]\+/'; then
    WORKTREE_ROOT=$(echo "$FILE_PATH" | sed 's|\(.*/.claude/worktrees/[^/]*/\).*|\1|')
    if [ -d "$WORKTREE_ROOT" ]; then
      GIT_DIR="$WORKTREE_ROOT"
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
  # Source lib and delegate. Lib writes to refs/checkpoints/<branch>, never HEAD.
  # shellcheck source=lib/checkpoint-core.sh
  . "$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)/lib/checkpoint-core.sh"

  write_checkpoint "$GIT_DIR" "posttool threshold (${TOTAL} files, threshold=${CHECKPOINT_THRESHOLD})" >&2
  RC=$?
  # A snapshot that was refused or failed is told to the user (systemMessage) and to the
  # model (additionalContext), as one JSON object that is the hook's whole stdout; plain
  # PostToolUse stdout reaches neither (code.claude.com/docs/en/hooks). A snapshot that
  # was written says nothing.
  NOTICE=""
  if [ "$RC" -eq 3 ]; then
    NOTICE="Checkpoint snapshot refused by $checkpoint_refused_by: nothing written, see logs/checkpoint.log"
  elif [ "$RC" -ne 0 ] && [ "$SILENT_MODE" != "1" ]; then
    NOTICE="Checkpoint failed (${TOTAL} files pending); see ~/.claude/logs/checkpoint.log"
  fi
  if [ -n "$NOTICE" ]; then
    printf '{"systemMessage": "%s", "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "%s"}}\n' \
      "$NOTICE" "$NOTICE"
  fi
fi

exit 0
