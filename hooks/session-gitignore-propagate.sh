#!/usr/bin/env bash
# SessionStart hook: keep the harness's runtime directories out of a product repo's git status.
# Appends each harness-owned .claude/ subdirectory below that the clone's own exclude file
# (`git rev-parse --git-path info/exclude`; a worktree resolves its own) does not list yet.
# Never writes a tracked file or the tracked .gitignore, never lists a docs/dev artifact
# /commit stages; a project that is not a git repository is left alone. Exits 0.

set -u

RUNTIME_DIRS=(
  ".claude/dev-registry/"
  ".claude/dev-start-replays/"
  ".claude/specs/"
  ".claude/workflow-locks/"
)

ROOT=$(git -C "${CLAUDE_PROJECT_DIR:-$PWD}" rev-parse --show-toplevel 2>/dev/null) || exit 0
[ -n "$ROOT" ] && cd "$ROOT" 2>/dev/null || exit 0
EXCLUDE=$(git rev-parse --git-path info/exclude 2>/dev/null) || exit 0
mkdir -p "$(dirname "$EXCLUDE")" 2>/dev/null || exit 0
for dir in "${RUNTIME_DIRS[@]}"; do
  grep -qxF "$dir" "$EXCLUDE" 2>/dev/null && continue
  # A last line without its newline must not swallow the appended one.
  [ -s "$EXCLUDE" ] && [ -n "$(tail -c1 "$EXCLUDE")" ] && printf '\n' >> "$EXCLUDE"
  printf '%s\n' "$dir" >> "$EXCLUDE" 2>/dev/null || exit 0
done
exit 0
