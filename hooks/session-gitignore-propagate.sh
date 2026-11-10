#!/usr/bin/env bash
# SessionStart hook: keep the harness's runtime directories out of a product repo's git status.
# Appends each harness-owned .claude/ subdirectory below, and each per-session record the harness
# keeps directly in .claude/, that the clone's own exclude file
# (`git rev-parse --git-path info/exclude`; a worktree resolves its own) does not list yet.
# Never writes a tracked file or the tracked .gitignore, never lists a docs/dev artifact
# /commit stages; a project that is not a git repository is left alone. Exits 0.
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib/harness_switch.sh" 2>/dev/null && harness_switch_exit_if_off  # the harness switch: no harness hook runs while /harness off holds

set -u

RUNTIME_DIRS=(
  ".claude/dev-registry/"
  ".claude/dev-start-replays/"
  ".claude/overnight-fresh-clones/"
  ".claude/overnight-git-bin/"
  ".claude/overnight-git-policy-bin/"
  ".claude/specs/"
  ".claude/workflow-locks/"
  ".claude/worktrees/"
)
# The two per-session records stay directly in .claude/ (the overnight guards and the bash safety
# layer glob them there), so each gets one exact name pattern instead of a directory line. Neither
# matches a file Claude Code or a user keeps in .claude/ (settings*.json, CLAUDE.md, commands/...).
RUNTIME_FILES=(
  ".claude/overnight-state-*.json"
  ".claude/workflow-*.json"
)

ROOT=$(git -C "${CLAUDE_PROJECT_DIR:-$PWD}" rev-parse --show-toplevel 2>/dev/null) || exit 0
[ -n "$ROOT" ] && cd "$ROOT" 2>/dev/null || exit 0
EXCLUDE=$(git rev-parse --git-path info/exclude 2>/dev/null) || exit 0
mkdir -p "$(dirname "$EXCLUDE")" 2>/dev/null || exit 0
for line in "${RUNTIME_DIRS[@]}" "${RUNTIME_FILES[@]}"; do
  grep -qxF "$line" "$EXCLUDE" 2>/dev/null && continue
  # A last line without its newline must not swallow the appended one.
  [ -s "$EXCLUDE" ] && [ -n "$(tail -c1 "$EXCLUDE")" ] && printf '\n' >> "$EXCLUDE"
  printf '%s\n' "$line" >> "$EXCLUDE" 2>/dev/null || exit 0
done
exit 0
