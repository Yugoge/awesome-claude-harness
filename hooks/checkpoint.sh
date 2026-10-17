#!/bin/bash
# checkpoint.sh - Manual /checkpoint command
# Immediately snapshot all current changes to refs/checkpoints/<branch>.
# Location: ~/.claude/hooks/checkpoint.sh
# Usage: bash ~/.claude/hooks/checkpoint.sh [<message>]
#
# The working branch HEAD is never moved. The checkpoint ref stays local unless
# GIT_AUTO_PUSH=1, in which case the lib pushes it in the background (rate-limited, no -f).

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}💾 Creating checkpoint...${NC}"
echo ""

# Check for changes
STAGED=$(git diff --cached --name-only 2>/dev/null | wc -l)
MODIFIED=$(git diff --name-only 2>/dev/null | wc -l)
UNTRACKED=$(git ls-files --others --exclude-standard 2>/dev/null | wc -l)
TOTAL=$((STAGED + MODIFIED + UNTRACKED))

if [ "$TOTAL" -eq 0 ]; then
  echo -e "${GREEN}✓ No changes to checkpoint${NC}"
  exit 0
fi

echo "Found $TOTAL file(s) with changes"
echo ""

# Determine branch for display
BRANCH=$(git branch --show-current 2>/dev/null)
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")
MESSAGE_PREFIX=${GIT_CHECKPOINT_MESSAGE:-"checkpoint"}

# Assemble user-facing summary line (custom_message for lib)
USER_MESSAGE="$*"
if [ -n "$USER_MESSAGE" ]; then
  SUMMARY="${MESSAGE_PREFIX}: Manual save at ${TIMESTAMP} — ${USER_MESSAGE}"
else
  SUMMARY="${MESSAGE_PREFIX}: Manual save at ${TIMESTAMP}"
fi

echo "📝 Writing checkpoint to refs/checkpoints/<branch>..."

# Source and delegate
# shellcheck source=lib/checkpoint-core.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)/lib/checkpoint-core.sh"

if ! write_checkpoint "" "manual: /checkpoint" "$SUMMARY"; then
  echo -e "${RED}❌ Failed to create checkpoint. See ~/.claude/logs/checkpoint.log${NC}"
  exit 1
fi

# Display the new tip of the checkpoint ref
if [ -n "$BRANCH" ]; then
  SANITIZED=$(printf '%s' "$BRANCH" | tr '/' '-')
else
  SHORT=$(git rev-parse --short HEAD 2>/dev/null)
  SANITIZED="detached-${SHORT:-empty}"
fi
REF="refs/checkpoints/${SANITIZED}"
TIP=$(git rev-parse --short "$REF" 2>/dev/null)

echo -e "${GREEN}✅ Checkpoint created: ${TIP:-?} on ${REF}${NC}"
echo ""
echo "Summary:"
echo "  • Branch: ${BRANCH:-(detached)}"
echo "  • Ref:    ${REF}"
echo "  • Tip:    ${TIP:-?}"
echo "  • Files:  $TOTAL"
echo ""
echo "Recover a file:"
echo "  git checkout ${REF} -- <path>"
echo ""
if [ "${GIT_AUTO_PUSH:-}" = "1" ]; then
  echo -e "${YELLOW}ℹ${NC}  Background push of ${REF} is rate-limited (1/30s)."
  echo "   See ~/.claude/logs/checkpoint-push.log for push errors."
else
  echo -e "${YELLOW}ℹ${NC}  ${REF} is local only: automatic push is off (enable with export GIT_AUTO_PUSH=1)."
fi
