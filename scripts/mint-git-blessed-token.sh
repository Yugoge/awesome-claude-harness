#!/usr/bin/env bash
# mint-git-blessed-token.sh — issuer of the keystone blessed token (M12).
#
# The reference-transaction keystone (hooks/git-keystone/reference-transaction)
# rejects master-ref / main-HEAD moves for an OVERNIGHT actor unless a blessed
# token is present. This script is the NAMED ISSUER: the sanctioned harness
# wrappers (/commit, /push, /merge execution paths) call it to mint a
# single-operation, short-lived token, then run the git op with the token in
# env. The overnight launch env NEVER calls this and NEVER sets the token.
#
# Token contract (AC10):
#   env var:   CLAUDE_GIT_BLESSED_TOKEN  (the token string)
#   issuer:    this script (scripts/mint-git-blessed-token.sh), invoked by the
#              /commit//push//merge execution wrappers ONLY.
#   scope:     single-operation / short-lived (default TTL 60s, NOT
#              session-global). Each mint writes a grant file whose first line
#              is an epoch expiry; the keystone checks it.
#   grant dir: ${CLAUDE_GIT_BLESSED_GRANT_DIR:-${TMPDIR:-/tmp}/claude-git-blessed}
#
# Usage:
#   eval "$(scripts/mint-git-blessed-token.sh [--ttl 60])"   # exports the var
#   git commit ...                                            # token honored
#
# Output (stdout): shell export lines (export CLAUDE_GIT_BLESSED_TOKEN=...;
#                  export CLAUDE_GIT_BLESSED_GRANT_DIR=...).
# Exit: 0 on success.

set -euo pipefail

TTL=60
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ttl) TTL="$2"; shift 2 ;;
    *) shift ;;
  esac
done
[[ "$TTL" =~ ^[0-9]+$ ]] || TTL=60

GRANT_DIR="${CLAUDE_GIT_BLESSED_GRANT_DIR:-${TMPDIR:-/tmp}/claude-git-blessed}"
mkdir -p "$GRANT_DIR"
chmod 700 "$GRANT_DIR" 2>/dev/null || true

TOKEN="$(head -c 18 /dev/urandom | od -An -tx1 | tr -d ' \n')"
EXPIRY=$(( $(date +%s) + TTL ))
GRANT="$GRANT_DIR/${TOKEN}.grant"
printf '%s\nissuer=mint-git-blessed-token.sh\nscope=single-operation\n' "$EXPIRY" > "$GRANT"
chmod 600 "$GRANT" 2>/dev/null || true

echo "export CLAUDE_GIT_BLESSED_TOKEN=${TOKEN};"
echo "export CLAUDE_GIT_BLESSED_GRANT_DIR=${GRANT_DIR};"
