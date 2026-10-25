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

# P7b: land P7 on a harness home upgraded from pre-P7 code (scripts/install/land always exits 0 and
# prints at most one plain line). The Stop coordinator relays only a last stdout line, so notice()
# prints it last on every exit-0 path, joined with a refused-snapshot notice.
NOTICE="$(bash "$(dirname "${BASH_SOURCE[0]}")/../scripts/install/land" 2>/dev/null)" || NOTICE=""
notice() { [ -z "$NOTICE" ] || printf '{"systemMessage": "%s"}\n' "$NOTICE"; }

# Check if this is a git repository
if ! git rev-parse --git-dir > /dev/null 2>&1; then
  echo -e "${YELLOW}⚠️  Not a git repository. Skipping checkpoint.${NC}"
  notice; exit 0
fi

# Fast exit if nothing changed (keeps Stop hook chatter minimal)
if [[ -z "$(git status --porcelain)" ]]; then
  echo -e "${GREEN}✅ No changes to checkpoint.${NC}"
  notice; exit 0
fi

# Source and delegate to the shared library
# shellcheck source=lib/checkpoint-core.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)/lib/checkpoint-core.sh"

SANITIZED=$(git branch --show-current 2>/dev/null | tr '/' '-')  # the ref as write_checkpoint names it
REF="refs/checkpoints/${SANITIZED:-detached-$(git rev-parse --short HEAD 2>/dev/null || echo empty)}"
OLD=$(git rev-parse -q --verify "$REF") || true  # rc 0 is written or a no-op: the tip tells which
if write_checkpoint "" "stop hook: auto-commit.sh"; then
  TIP=$(git rev-parse -q --verify "$REF") || true  # none yet when the first snapshot was a no-op
  if [ -n "$TIP" ] && [ "$TIP" != "$OLD" ]; then
    echo -e "${GREEN}✅ Checkpoint saved at $(date +"%Y-%m-%d %H:%M:%S")${NC}"
  else
    echo -e "${GREEN}✅ No changes to checkpoint: nothing written.${NC}"
  fi
  if [ -n "$TIP" ]; then
    echo -e "${GREEN}   Ref: ${REF}${NC}"
    echo -e "${GREEN}   Tip: $(git rev-parse --short "$TIP")${NC}"
  fi
elif [ "$?" -eq 3 ]; then  # refused, nothing written: a one-line notice (systemMessage), never a Stop block
  NOTICE="Checkpoint snapshot refused by $checkpoint_refused_by: nothing written, see logs/checkpoint.log${NOTICE:+; $NOTICE}"
else
  echo -e "${RED}❌ Checkpoint failed. See ~/.claude/logs/checkpoint.log${NC}"
  exit 1
fi

notice; exit 0
