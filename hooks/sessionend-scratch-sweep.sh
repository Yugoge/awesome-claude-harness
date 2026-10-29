#!/bin/bash
# sessionend-scratch-sweep.sh — SessionEnd hook (Scratch Lifecycle Contract
# Layer B, task 20260907-015935).
#
# Removes ONLY this session's own scratch directory (<root>/<own-sid>/) after
# confirming its .owner record names this exact session id — the common-case
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
# Never touches a sibling session's directory — only ever resolves and acts
# on <root>/<own-sid>/. Non-blocking: best-effort, exits 0 unconditionally.

set -u
exec >&2   # SessionEnd hooks must not pollute stdout (harness JSON channel)

ROOT="${TMPDIR:-/var/tmp/claude-scratch}"
SID="${CLAUDE_CODE_SESSION_ID:-}"

INPUT=$(cat 2>/dev/null || true)
if [ -z "$SID" ]; then
  SID=$(printf '%s' "$INPUT" | python3 -c \
    "import json,sys; d=json.load(sys.stdin); print(d.get('session_id','') or '')" \
    2>/dev/null || true)
fi
if [ -z "$SID" ]; then
  echo "sessionend-scratch-sweep: no session id available — skipping"
  exit 0
fi

# Charset guard: SID becomes a literal path component below and must never
# carry a path separator or traversal sequence — this is the ONLY thing that
# stands between "remove our own dir" and "remove something else."
case "$SID" in
  */*|*..*)
    echo "sessionend-scratch-sweep: unsafe session id '$SID' — skipping"
    exit 0
    ;;
esac

if [ ! -d "$ROOT" ]; then
  echo "sessionend-scratch-sweep: root $ROOT absent — nothing to sweep"
  exit 0
fi

TARGET="$ROOT/$SID"

# Must be a real directory, never a symlink (a symlink here could redirect
# the subsequent rm -rf to an arbitrary path).
if [ -L "$TARGET" ] || [ ! -d "$TARGET" ]; then
  echo "sessionend-scratch-sweep: $TARGET is not an own directory — skipping"
  exit 0
fi

# Containment guard: the canonicalized target's parent must be the
# canonicalized root — closes any residual traversal the charset guard above
# did not already catch.
ROOT_REAL=$(cd "$ROOT" 2>/dev/null && pwd -P) || { echo "sessionend-scratch-sweep: cannot resolve root"; exit 0; }
TARGET_PARENT_REAL=$(cd "$TARGET/.." 2>/dev/null && pwd -P) || { echo "sessionend-scratch-sweep: cannot resolve target parent"; exit 0; }
if [ "$TARGET_PARENT_REAL" != "$ROOT_REAL" ]; then
  echo "sessionend-scratch-sweep: $TARGET escapes $ROOT — skipping"
  exit 0
fi

# Ownership guard: the directory must belong to our own session (its .owner
# record names this exact session id) before we ever remove anything — the
# one rule hooks/lib/scratch_owner.py holds, which doc-sync's notice applies
# too; an undecidable directory is left alone.
if ! python3 "$(dirname "${BASH_SOURCE[0]}")/lib/scratch_owner.py" "$TARGET" "$SID" 2>/dev/null; then
  echo "sessionend-scratch-sweep: $TARGET does not belong to session $SID — skipping"
  exit 0
fi

rm -rf -- "$TARGET" 2>/dev/null \
  && echo "sessionend-scratch-sweep: removed own session dir $TARGET" \
  || echo "sessionend-scratch-sweep: rm -rf $TARGET failed"

exit 0
