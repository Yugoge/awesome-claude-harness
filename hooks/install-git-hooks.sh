#!/bin/bash
# ============================================================================
# LEGACY / DO NOT USE — describes an obsolete git-tracking model.
# ============================================================================
# install-git-hooks.sh reflects an OLD git-tracking design the current harness
# does NOT use. Git protection today is the grant-gated kernel plus the
# git-native reference-transaction keystone, installed via
# scripts/install-git-keystone.sh (README.md / ARCHITECTURE.md §6). This script
# is kept only for historical reference and is disabled below.
# ============================================================================
echo "[LEGACY] hooks/install-git-hooks.sh is obsolete and disabled. See the root README." >&2
exit 0

# install-git-hooks.sh - Install pre-commit hooks into git repositories (legacy, unreachable)
# Part of Claude Code git tracking solution
# Location: ~/.claude/hooks/install-git-hooks.sh
#
# Usage:
#   ~/.claude/hooks/install-git-hooks.sh              # Install in current directory
#   ~/.claude/hooks/install-git-hooks.sh /path/to/repo  # Install in specific repo

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Determine target directory
if [ -z "$1" ]; then
  TARGET_DIR="$(pwd)"
else
  TARGET_DIR="$1"
fi

echo -e "${BLUE}Installing git hooks in: $TARGET_DIR${NC}"
echo ""

# Check if target directory exists
if [ ! -d "$TARGET_DIR" ]; then
  echo -e "${RED}❌ Error: Directory does not exist: $TARGET_DIR${NC}"
  exit 1
fi

# Check if it's a git repository
if [ ! -d "$TARGET_DIR/.git" ]; then
  echo -e "${RED}❌ Error: Not a git repository: $TARGET_DIR${NC}"
  echo "Run 'git init' first or specify a valid git repository."
  exit 1
fi

# Hooks directory
HOOKS_DIR="$TARGET_DIR/.git/hooks"

# Source template location
TEMPLATE_FILE="$HOME/.claude/hooks/git-hooks/pre-commit"

# Check if template exists
if [ ! -f "$TEMPLATE_FILE" ]; then
  echo -e "${RED}❌ Error: Hook template not found: $TEMPLATE_FILE${NC}"
  exit 1
fi

# Target hook file
HOOK_FILE="$HOOKS_DIR/pre-commit"

# Backup existing hook if it exists
if [ -f "$HOOK_FILE" ]; then
  BACKUP_FILE="$HOOK_FILE.backup.$(date +%Y%m%d_%H%M%S)"
  echo -e "${YELLOW}⚠️  Existing pre-commit hook found${NC}"
  echo "Creating backup: $BACKUP_FILE"
  cp "$HOOK_FILE" "$BACKUP_FILE"
  echo ""
fi

# Copy template to hooks directory
echo "Installing pre-commit hook..."
cp "$TEMPLATE_FILE" "$HOOK_FILE"

# Make executable
chmod +x "$HOOK_FILE"

# Verify installation
if [ -x "$HOOK_FILE" ]; then
  echo -e "${GREEN}✅ Successfully installed pre-commit hook${NC}"
  echo ""
  echo "Hook location: $HOOK_FILE"
  echo ""
  echo "Configuration (environment variables in settings.json):"
  echo "  • GIT_AUTO_STAGE_ALL=0      - Auto-stage all files (default: off)"
  echo "  • GIT_BLOCK_ON_UNTRACKED=0  - Block commits with untracked files (default: off)"
  echo "  • GIT_WARN_UNTRACKED=1      - Show warnings (default: on)"
  echo ""
  echo "To bypass the hook: git commit --no-verify"
else
  echo -e "${RED}❌ Error: Failed to install hook${NC}"
  exit 1
fi
