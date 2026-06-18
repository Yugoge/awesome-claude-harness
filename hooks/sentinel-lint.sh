#!/bin/bash
# sentinel-lint.sh - Guards the dev-registry sentinel anchor in orchestrator files
#
# Purpose: Verifies that the canonical REGISTRY_DIR assignment line — the anchor
# for the /dev subagent code-write enforcement injection — remains present in
# each of the three orchestrator files. If any file has lost the anchor, the
# script exits 1 with a clear error identifying the affected file. Exits 0
# silently when all anchors are present.
#
# Modes (auto-detected via $GIT_INDEX_FILE):
#   - Pre-commit (staged content):  $GIT_INDEX_FILE is set -> read via `git show :<path>`
#   - Standalone (disk content):    $GIT_INDEX_FILE is unset -> read files from disk
#
# Usage:
#   sentinel-lint.sh                 # standalone mode (disk files)
#   GIT_INDEX_FILE=.git/index sentinel-lint.sh   # pre-commit mode (staged content)
#
# Exit codes:
#   0 = all three files contain the anchor
#   1 = one or more files are missing the anchor
#   2 = internal error (e.g. repo root not found in staged mode)
#
# Dependencies: bash, grep -F, git (only in staged mode).
# Must complete in <500ms on the current repo.

set -u

# Canonical anchor string — MUST match exactly in each orchestrator file.
# Using single quotes so $CLAUDE_PROJECT_DIR and $DEV_SESSION_ID are literal.
readonly ANCHOR='REGISTRY_DIR="$CLAUDE_PROJECT_DIR/.claude/dev-registry/$DEV_SESSION_ID"'

# Target files (relative to the .claude repo root / nested repo).
readonly TARGETS=(
  "commands/dev.md"
  "commands/dev-command.md"
  "commands/dev-overnight.md"
)

# Disk root for standalone mode. WS1: resolve the harness home from this
# script's own location (hooks/sentinel-lint.sh -> harness home) instead of the
# author literal /root/.claude; an explicit SENTINEL_LINT_ROOT still overrides.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/claude_home.sh"
readonly DISK_ROOT="${SENTINEL_LINT_ROOT:-$(claude_home_resolve)}"

failed=0
failed_files=()

if [[ -n "${GIT_INDEX_FILE:-}" ]]; then
  # Pre-commit mode: read staged content via `git show :<path>`.
  # git must run from inside the repo, and the paths are repo-relative.
  for rel in "${TARGETS[@]}"; do
    # `git show :<path>` prints the staged blob for <path> (index version).
    if ! git show ":$rel" 2>/dev/null | grep -Fq -- "$ANCHOR"; then
      failed=1
      failed_files+=("$rel (staged)")
    fi
  done
else
  # Standalone mode: read files from disk.
  for rel in "${TARGETS[@]}"; do
    abs="$DISK_ROOT/$rel"
    if [[ ! -f "$abs" ]]; then
      failed=1
      failed_files+=("$abs (not found)")
      continue
    fi
    if ! grep -Fq -- "$ANCHOR" "$abs"; then
      failed=1
      failed_files+=("$abs")
    fi
  done
fi

if [[ $failed -ne 0 ]]; then
  {
    echo "❌ sentinel-lint: canonical REGISTRY_DIR line missing — dev-registry injection has been broken"
    echo "   Expected anchor: $ANCHOR"
    echo "   Affected file(s):"
    for f in "${failed_files[@]}"; do
      echo "     - $f"
    done
    echo "   Restore the sentinel-injection block in the affected file(s) or bypass with 'git commit --no-verify' (not recommended)."
  } >&2
  exit 1
fi

# Silent success by default. Emit a short summary when SENTINEL_LINT_VERBOSE=1.
if [[ "${SENTINEL_LINT_VERBOSE:-0}" = "1" ]]; then
  echo "sentinel-lint: OK (${#TARGETS[@]} files checked)"
fi

exit 0
