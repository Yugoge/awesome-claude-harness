#!/usr/bin/env bash
# Description: statusLine command that renders the persistent host-capability marker.
# Usage: capability-status-line.sh            (reads the statusLine JSON envelope on stdin)
# Exit codes: 0 always — a status line must never be able to wedge a session.
#
# Emits a RED "UNPROTECTED HOST" marker on every non-PASS state and a plain
# "protected" marker only on a fresh, binding-matched PASS. This is a continuously
# re-rendered surface, not a log line that scrolls past.
#
# NOTE: emitting this string is NOT evidence the host RENDERS it. Verification
# asserts on the captured pane buffer (tmux capture-pane -p -e), never on this
# command's stdout — see scripts/capability-handshake.py::observe_status_surface.
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
HOME_DIR="$(cd "$SELF_DIR/.." && pwd -P)"

RED=$'\033[1;31m'
DIM=$'\033[2m'
RESET=$'\033[0m'

payload="$(cat 2>/dev/null || true)"

verdict="$(
  SL_PAYLOAD="$payload" python3 - "$HOME_DIR" <<'PY' 2>/dev/null || true
import json, os, sys
sys.path.insert(0, os.path.join(sys.argv[1], "hooks", "lib"))
import capability_state as cs
try:
    env = json.loads(os.environ.get("SL_PAYLOAD") or "{}")
except ValueError:
    env = {}
sid = (env.get("session_id") if isinstance(env, dict) else None) or os.environ.get("CLAUDE_SESSION_ID") or ""
state, err = cs.load_state(cs.state_path(sid), expected_session_id=sid or None)
if err:
    print("UNPROTECTED\t" + err)
else:
    overall, reason = cs.aggregate_verdict(state, sys.argv[1])
    print(("PASS\t" if overall == "PASS" else "UNPROTECTED\t") + (reason or "fresh PASS"))
PY
)"

status="${verdict%%$'\t'*}"
reason="${verdict#*$'\t'}"
[ -n "$status" ] || { status="UNPROTECTED"; reason="status probe unavailable"; }

if [ "$status" = "PASS" ]; then
  printf '%shost capability: protected%s\n' "$DIM" "$RESET"
else
  printf '%s UNPROTECTED HOST %s%s %s%s\n' "$RED" "$RESET" "$DIM" "$reason" "$RESET"
fi
exit 0
