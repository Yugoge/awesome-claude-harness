#!/usr/bin/env bash
#
# push.sh - Global pre-push checks: git identity + fetch/pull/status
#
# Usage:
#   /root/.claude/push.sh [--quiet]
#
# Exit codes:
#   0 - Ready to push (or already pulled)
#   1 - Error occurred
#

set -euo pipefail

QUIET_MODE=false
if [[ "${1:-}" == "--quiet" ]]; then
    QUIET_MODE=true
fi

log() {
    if [[ "$QUIET_MODE" == false ]]; then
        echo "$@"
    fi
}

# Ensure git identity
EXPECTED_NAME="Yugoge"
EXPECTED_EMAIL="${CLAUDE_PUSH_EXPECTED_EMAIL:-$(git config user.email)}"
CURRENT_NAME=$(git config user.name 2>/dev/null || echo "")
CURRENT_EMAIL=$(git config user.email 2>/dev/null || echo "")
if [[ "$CURRENT_NAME" != "$EXPECTED_NAME" || "$CURRENT_EMAIL" != "$EXPECTED_EMAIL" ]]; then
    git config user.name "$EXPECTED_NAME"
    git config user.email "$EXPECTED_EMAIL"
    log "[INFO] Git identity corrected to: $EXPECTED_NAME <$EXPECTED_EMAIL>"
fi

# Fetch remote updates
log "[INFO] Checking git status..."
git fetch origin >/dev/null 2>&1 || true

# Get current and remote commit hashes
LOCAL_HEAD=$(git rev-parse HEAD)
REMOTE_HEAD=$(git rev-parse @{u} 2>/dev/null || echo "")

if [[ -z "$REMOTE_HEAD" ]]; then
    log "[INFO] Remote branch not found (first push?)"
    exit 0
fi

# Pull if behind
if [[ "$LOCAL_HEAD" != "$REMOTE_HEAD" ]]; then
    log "[INFO] Local branch is behind remote. Pulling with rebase..."
    BRANCH=$(git rev-parse --abbrev-ref HEAD)
    if git pull --rebase origin "$BRANCH"; then
        log "[SUCCESS] Pulled remote changes"
        exit 0
    else
        echo "[ERROR] Failed to pull remote changes" >&2
        exit 1
    fi
fi

# Check if ahead
AHEAD_COUNT=$(git rev-list @{u}..HEAD 2>/dev/null | wc -l)
if [[ "$AHEAD_COUNT" -gt 0 ]]; then
    log "[INFO] Ready to push (unpushed commits: $AHEAD_COUNT)"
else
    log "[INFO] Nothing to push (in sync with remote)"
fi

exit 0
