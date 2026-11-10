#!/bin/bash
# sessionend-scratch-sweep.sh — SessionEnd hook (Scratch Lifecycle Contract
# Layer B, task 20260907-015935).
#
# Removes ONLY this session's own files: its runtime files in the project, and
# its scratch directory (<root>/<own-sid>/) after confirming its .owner record
# names this exact session id — the common-case
# cleanup: session-owned scratch dies with its session. Runs in the hook
# channel, outside the agent tool-call gate — the same legitimate deletion
# channel already used by hooks/stop-cleanup-allowlist.sh; the agent-side rm
# ban (hooks/pretool-bash-safety.sh) is untouched and never bypassed by this
# script, because this script IS the hook process, not a Bash tool call.
#
# Escapes this hook never fires for (crash, kill -9, missing SessionEnd
# support) are NOT this hook's job: scripts/install/tmpfiles-claude-scratch.conf
# bounds them declaratively with an age floor (host channel), never here.
#
# Never touches a sibling session's files — only ever resolves and acts on
# paths named by its own sid. Non-blocking: best-effort, exits 0 unconditionally.

set -u
# Silent: the CLI discards what a SessionEnd hook prints (code.claude.com/docs/en/hooks,
# "SessionEnd"), so each skip below is named in a comment instead of a message nobody reads.
exec >/dev/null 2>&1

ROOT="${TMPDIR:-/var/tmp/claude-scratch}"
INPUT=$(cat 2>/dev/null || true)
# The payload's id keys the project files, as their producer (prompt-workflow.py) keys them.
PSID=$(printf '%s' "$INPUT" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print(d.get('session_id','') or '')" \
  2>/dev/null || true)
SID="${CLAUDE_CODE_SESSION_ID:-$PSID}"
if [ -z "$SID" ]; then
  # no session id available — skipping
  exit 0
fi

# Charset guard: SID becomes a literal path component below and must never
# carry a path separator or traversal sequence — this is the ONLY thing that
# stands between "remove our own dir" and "remove something else."
case "$SID $PSID" in
  */*|*..*)
    # unsafe session id '$SID $PSID' — skipping
    exit 0
    ;;
esac

# This session's own runtime files in the project (prompt-workflow.py's, keyed by
# session id) go with it: the workflow bookmark, its start lock, its start replays.
OWN="${CLAUDE_PROJECT_DIR:-$PWD}/.claude"
[ -n "$PSID" ] && rm -rf -- "$OWN/workflow-$PSID.json" "$OWN/workflow-locks/$PSID.lock" \
  "$OWN/dev-start-replays/$PSID" 2>/dev/null

if [ ! -d "$ROOT" ]; then
  # root $ROOT absent — nothing to sweep
  exit 0
fi

TARGET="$ROOT/$SID"

# Must be a real directory, never a symlink (a symlink here could redirect
# the subsequent rm -rf to an arbitrary path).
if [ -L "$TARGET" ] || [ ! -d "$TARGET" ]; then
  # $TARGET is not an own directory — skipping
  exit 0
fi

# Containment guard: the canonicalized target's parent must be the
# canonicalized root — closes any residual traversal the charset guard above
# did not already catch.
ROOT_REAL=$(cd "$ROOT" 2>/dev/null && pwd -P) || exit 0                  # cannot resolve root
TARGET_PARENT_REAL=$(cd "$TARGET/.." 2>/dev/null && pwd -P) || exit 0    # cannot resolve target parent
if [ "$TARGET_PARENT_REAL" != "$ROOT_REAL" ]; then
  # $TARGET escapes $ROOT — skipping
  exit 0
fi

# Ownership guard: the directory must belong to our own session (its .owner
# record names this exact session id) before we ever remove anything — the
# one rule hooks/lib/scratch_owner.py holds, which doc-sync's notice applies
# too; an undecidable directory is left alone.
if ! python3 "$(dirname "${BASH_SOURCE[0]}")/lib/scratch_owner.py" "$TARGET" "$SID" 2>/dev/null; then
  # $TARGET does not belong to session $SID — skipping
  exit 0
fi

rm -rf -- "$TARGET" 2>/dev/null   # this session's own dir; a failure leaves it to the orphan floor

exit 0
