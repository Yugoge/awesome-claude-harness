#!/bin/bash
# ============================================================================
# auto-commit.sh - Stop hook: snapshot on conversation end
# ----------------------------------------------------------------------------
# Writes a checkpoint to refs/checkpoints/<branch> via the shared library.
# The working branch HEAD is never moved.
#
# Trigger: Stop hook (sole checkpoint writer in the Stop chain since
# 2026-04-28; the redundant stop-git-commit.sh sibling was retired).
# Idempotent: if tree==parent, the shared library short-circuits to no-op.
# ============================================================================

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Check if this is a git repository
if ! git rev-parse --git-dir > /dev/null 2>&1; then
  echo -e "${YELLOW}⚠️  Not a git repository. Skipping checkpoint.${NC}"
  exit 0
fi

# Fast exit if nothing changed (keeps Stop hook chatter minimal)
if [[ -z "$(git status --porcelain)" ]]; then
  echo -e "${GREEN}✅ No changes to checkpoint.${NC}"
  exit 0
fi

# Source and delegate to the shared library
# shellcheck source=lib/checkpoint-core.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)/lib/checkpoint-core.sh"

if write_checkpoint "" "stop hook: auto-commit.sh"; then
  TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")
  BRANCH=$(git branch --show-current 2>/dev/null)
  if [ -n "$BRANCH" ]; then
    SANITIZED=$(printf '%s' "$BRANCH" | tr '/' '-')
  else
    SHORT=$(git rev-parse --short HEAD 2>/dev/null)
    SANITIZED="detached-${SHORT:-empty}"
  fi
  REF="refs/checkpoints/${SANITIZED}"
  TIP=$(git rev-parse --short "$REF" 2>/dev/null)
  echo -e "${GREEN}✅ Checkpoint saved at $TIMESTAMP${NC}"
  echo -e "${GREEN}   Ref: ${REF}${NC}"
  if [ -n "$TIP" ]; then
    echo -e "${GREEN}   Tip: ${TIP}${NC}"
  fi
else
  echo -e "${RED}❌ Checkpoint failed. See ~/.claude/logs/checkpoint.log${NC}"
  exit 1
fi

exit 0
