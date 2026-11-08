#!/bin/bash
# posttool-git-warn.sh - Warn about untracked files after commit
# Part of Claude Code git tracking solution
# Location: ~/.claude/hooks/posttool-git-warn.sh

# Only run if warnings enabled
if [ "$GIT_WARN_UNTRACKED" != "1" ]; then
  exit 0
fi

# Check for untracked files (respecting .gitignore)
UNTRACKED=$(git ls-files --others --exclude-standard 2>/dev/null)

if [ -n "$UNTRACKED" ]; then
  # Count untracked files (more robust method)
  COUNT=$(echo "$UNTRACKED" | grep -c '^' || echo "1")

  echo ""
  echo "⚠️  Warning: $COUNT untracked file(s) detected after commit:"
  echo "$UNTRACKED" | sed 's/^/   - /'
  echo ""
  echo "💡 Suggestions:"
  echo "   • Run /push to stage and push all files"
  echo "   • Run: git add . && git commit --amend --no-edit"
  echo "   • Review files and add to .gitignore if needed"
  echo ""
fi

exit 0
