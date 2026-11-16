#!/bin/bash
# ============================================================================
# Ensure Git Repository Hook for Claude Code
# Ensure project has Git repository (auto-create if none exists)
# ============================================================================
# Purpose: Check and initialize Git repository when Claude Code session starts
# Trigger: SessionStart Hook
# ============================================================================
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib/harness_switch.sh" 2>/dev/null && harness_switch_exit_if_off  # the harness switch: no harness hook runs while /harness off holds

set -e

# Opt-in gate: truthy-only semantics — {1,true,TRUE,yes,YES} → enabled; everything else → skip
case "${CLAUDE_SESSION_GIT_INIT:-}" in
  1|true|TRUE|yes|YES) ;;
  *) exit 0 ;;  # off (the default): silent, since a SessionStart hook's stdout enters the context
esac

# Its own messages go to the hook's stdout (fd 3), which a SessionStart hook adds to the model's
# context (code.claude.com/docs/en/hooks); what the commands it runs print goes to stderr.
exec 3>&1 >&2

# No colour codes: the messages are read by the model, not a terminal.
GREEN=''
YELLOW=''
BLUE=''
RED=''
NC=

# Configurable Co-Authorship (Claude attribution only — no third-party watermark in default)
CO_AUTHOR=${CLAUDE_CO_AUTHOR:-"Co-Authored-By: Claude <noreply@anthropic.com>"}

# Check if already a git repository
if git rev-parse --git-dir > /dev/null 2>&1; then
  echo -e "${GREEN}✅ Git repository already exists.${NC}" >&3
  exit 0
fi

# Get current directory name as repository name
REPO_NAME=$(basename "$PWD")

echo -e "${BLUE}🚀 No Git repository found. Initializing...${NC}" >&3

# Initialize git
git init > /dev/null 2>&1

# Create .gitignore (if doesn't exist), through the one writer of a project's
# .gitignore, scripts/update-gitignore.sh.
HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ "$(bash "$HARNESS_DIR/scripts/update-gitignore.sh" "$PWD" --init)" = "created" ]; then
  echo -e "${GREEN}✅ Created .gitignore${NC}" >&3
fi

# Initial commit — ONLY on repos with zero commits (blame hygiene guard)
# ----------------------------------------------------------------------------
# If HEAD already resolves, this is an existing repo (even one we just
# re-init'd alongside history); DO NOT write a non-semantic commit to HEAD.
# This guard closes the HEAD-pollution leak identified by the 2026-04-16
# SaaS-grade blame audit (qa-final-blame-audit-20260416-063500.json).
if git rev-parse --verify -q HEAD >/dev/null 2>&1; then
  echo -e "${GREEN}✅ Git repository already has history; skipping Initial commit${NC}" >&3
  exit 0
fi

if git add . && git commit -m "chore: initialize repository with default .gitignore

🤖 Generated with [Claude Code](https://claude.ai/code)

${CO_AUTHOR}" > /dev/null 2>&1; then
  echo -e "${GREEN}✅ Git repository initialized with initial commit${NC}" >&3
else
  # Cleanup staged content — use git rm -r --cached . (not git reset HEAD, which fails on
  # unborn HEAD before the first commit)
  git rm -r --cached . > /dev/null 2>&1 || true
  exit 1
fi

# Check if GitHub CLI is installed
if ! command -v gh &> /dev/null; then
  echo -e "${YELLOW}⚠️  GitHub CLI (gh) not found.${NC}" >&3
  echo -e "${YELLOW}   Install it to auto-create remote repositories:${NC}" >&3
  echo -e "${YELLOW}   https://cli.github.com/${NC}" >&3
  exit 0
fi

# Check if authenticated with GitHub CLI
if ! gh auth status > /dev/null 2>&1; then
  echo -e "${YELLOW}⚠️  GitHub CLI not authenticated.${NC}" >&3
  echo -e "${YELLOW}   Run: gh auth login${NC}" >&3
  exit 0
fi

# Remote repository step (environment variables):
#   CLAUDE_AUTO_CREATE_REPO  unset or "ask": print the manual command and skip;
#                            {1,true,TRUE,yes,YES} (the gate set above): create it;
#                            {0,false,FALSE,no,NO}: skip; anything else: skip, saying so.
#   GIT_AUTO_PUSH            push the initial commit only when exactly "1", unless the new
#                            repository's harness.autoPush (from a git init template) says
#                            otherwise (lib/auto_push.sh); else create without pushing (/push later).
AUTO_CREATE=${CLAUDE_AUTO_CREATE_REPO:-ask}
CREATE_ARGS=(--private --source=. --remote=origin)
PUSH_NOTE="Initial commit not pushed: automatic push is off for this repository (enable with git config harness.autoPush true, or GIT_AUTO_PUSH=1). Push with /push or: git push -u origin HEAD"
. "$(dirname "${BASH_SOURCE[0]}")/lib/auto_push.sh" 2>/dev/null || harness_auto_push() { return 1; }  # no reader, no push
if harness_auto_push .; then
  CREATE_ARGS+=(--push)
  PUSH_NOTE=""
fi
MANUAL_CMD="gh repo create \"$REPO_NAME\" ${CREATE_ARGS[*]}"

case "$AUTO_CREATE" in
  1|true|TRUE|yes|YES) ;;
  ask)
    echo -e "${BLUE}❓ Create GitHub repository '$REPO_NAME'? (set CLAUDE_AUTO_CREATE_REPO env var to automate)${NC}" >&3
    echo -e "${YELLOW}   Skipping for now. Run manually: $MANUAL_CMD${NC}" >&3
    [ -z "$PUSH_NOTE" ] || echo -e "${YELLOW}   $PUSH_NOTE${NC}" >&3
    exit 0 ;;
  0|false|FALSE|no|NO)
    echo -e "${YELLOW}⚠️  Auto-create disabled. Skipping GitHub repository creation.${NC}" >&3
    exit 0 ;;
  *)
    echo -e "${YELLOW}⚠️  CLAUDE_AUTO_CREATE_REPO value not recognised (true/1/yes create, false skips). Skipping GitHub repository creation.${NC}" >&3
    exit 0 ;;
esac

# Auto-create GitHub repository
echo -e "${BLUE}🌐 Creating GitHub repository: $REPO_NAME${NC}" >&3

# Create private repository (pushed only when harness_auto_push added --push)
if gh repo create "$REPO_NAME" "${CREATE_ARGS[@]}" > /dev/null 2>&1; then
  USERNAME=$(gh api user -q .login)
  echo -e "${GREEN}✅ Repository created: https://github.com/$USERNAME/$REPO_NAME${NC}" >&3
  [ -z "$PUSH_NOTE" ] || echo -e "${YELLOW}   $PUSH_NOTE${NC}" >&3
else
  echo -e "${RED}❌ Failed to create GitHub repository.${NC}" >&3
  echo -e "${YELLOW}   You can create it manually: $MANUAL_CMD${NC}" >&3
  [ -z "$PUSH_NOTE" ] || echo -e "${YELLOW}   $PUSH_NOTE${NC}" >&3
  exit 1
fi

exit 0
