#!/usr/bin/env bash
# SessionStart hook: append missing standard harness gitignore rules to project repo
# Usage: Invoked automatically at session start by the Claude Code harness
# Runs idempotently — only appends rules that are absent.
# Exit codes: 0=success (always), 2=internal error (treated as 0 by design)

set -euo pipefail

HARNESS_RULES=(
  "tests/generated/"
  ".claude/dev-registry/dev-*/"
  "docs/codex/"
  ".playwright-mcp/"
)

# Find git root of CWD (fall back to CLAUDE_PROJECT_DIR env var if set)
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"

GIT_ROOT=$(git -C "$PROJECT_DIR" rev-parse --show-toplevel 2>/dev/null) || exit 0

# Only run for harness repos identified by the .awesome-claude-harness marker file
[[ -f "$GIT_ROOT/.claude/.awesome-claude-harness" ]] || exit 0

GITIGNORE="$GIT_ROOT/.gitignore"

# If no .gitignore exists, exit without modifying anything
[[ -f "$GITIGNORE" ]] || exit 0

# The one writer of a project's .gitignore appends each rule it does not hold yet.
HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RULE_ARGS=()
for rule in "${HARNESS_RULES[@]}"; do
  RULE_ARGS+=(--rule "$rule")
done
bash "$HARNESS_DIR/scripts/update-gitignore.sh" "$GIT_ROOT" \
  --comment "harness-propagated by session-gitignore-propagate.sh" "${RULE_ARGS[@]}" >/dev/null || true

exit 0
