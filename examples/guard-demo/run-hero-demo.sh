#!/usr/bin/env bash
# Description: Five-beat guard demo — a real agent git push is refused pre-execution, a
#   narrowly-scoped single-use grant permits exactly one push, and the repeat is refused
#   because the real posttool consumer consumed the grant.
# Usage: run-hero-demo.sh <fixture-dir> <grant-path> <task-id>
# Exit codes: 0=all five beats ran, 1=precondition failure, 2=beat sequencing failure
#
# CONTRACT (M5b/M8 of ticket dev-20260719-193823-f):
#   This script prints NOTHING but the operator command lines. It never prints refusal,
#   rule, reason, remedy or consumption text, and -- since a codex review of the first
#   draft -- it no longer prints CAUSAL NARRATION either. Lines like
#   "[... exit 2 - nothing executed]" or "[... permitted by single-use grant]" were
#   authored conclusions dressed as transcript: a reader would attribute them to the
#   system, and re-running could never expose them because both the committed capture and
#   the fresh run receive the same narration. That is the authored-not-captured defect
#   this hero exists to kill, reappearing one level up. Every remaining non-command line
#   in the capture is emitted either by a real hook under hooks/, by git, or by the
#   verifier under an explicit [verifier] attribution.
#
# NOTE ON SCOPE: this is a DIRECT-HOOK fixture. It invokes the real hook programs with
#   synthesized PreToolUse/PostToolUse payloads (the pattern established by run-demo.sh);
#   it does not drive Claude Code's live tool dispatcher. The hook decisions are real; the
#   dispatch is simulated. The caption says so rather than implying an agent session.
#
# SAFETY: the push executes against a hermetic LOCAL BARE remote addressed by a RELATIVE
#   path (../hero-remote.git) inside a throwaway fixture. The project repository and its
#   configured remote are never the cwd and are never contacted.

set -uo pipefail

FIXTURE="${1:?Missing fixture dir}"
GRANT_PATH="${2:?Missing grant path}"
TASK_ID="${3:?Missing task id}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="$(command -v python3 || true)"
if [ -z "$PYTHON_BIN" ]; then
  echo "run-hero-demo: python3 not found on PATH (precondition)" >&2
  exit 1
fi
PYDIR="$(dirname "$PYTHON_BIN")"

# --- Named pacing table (M19) --------------------------------------------------------
# Deliberate operator-reading pauses. They execute INSIDE the recorded run, so the
# session really did last as long as the capture says, and changing these changes the
# real session length. NOTE: the SVG renderer (tools/demo/gen-svg.mjs) is content-
# agnostic and applies its OWN animation cadence -- it does not replay these captured
# intervals. The measured session duration therefore comes from the raw capture's
# timestamps, never from the SVG's dur attribute, and the caption says so.
PACE_BEFORE_ATTEMPT=1.2
PACE_READ_REFUSAL=3.6
PACE_AFTER_GRANT=2.6
PACE_AFTER_PUSH=2.4
PACE_AFTER_CONSUME=3.0
PACE_TAIL=1.0

# The exact command used for beats 1, 3 and 5 — byte-identical across all three.
PUSH_CMD='git push hero-remote main'

# --- Real-hook invocation -------------------------------------------------------------
# env -i gives the hook a clean environment: no CLAUDE_SESSION_ID, no CLAUDE_TASK_ID and
# no CLAUDE_PUSH_COMMAND_ACTIVE from the invoking session can leak into the capture.
# session_id is set to the reserved token so no foreign identifier can ever be recorded.
pretool_push() {
  printf '{"tool_name":"Bash","tool_input":{"command":%s},"session_id":"%s"}' \
    "$("$PYTHON_BIN" -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$PUSH_CMD")" \
    "$TASK_ID" \
    | env -i PATH="$PYDIR:/usr/bin:/bin" LANG=C HOME="$FIXTURE/home" \
        CLAUDE_TASK_ID="$TASK_ID" \
        "$PYTHON_BIN" "$REPO_ROOT/hooks/pretool-git-privilege-guard.py"
  return $?
}

posttool_consume() {
  printf '{"tool_name":"Bash","tool_input":{"command":%s},"tool_response":{"exit_code":0},"session_id":"%s"}' \
    "$("$PYTHON_BIN" -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$PUSH_CMD")" \
    "$TASK_ID" \
    | env -i PATH="$PYDIR:/usr/bin:/bin" LANG=C HOME="$FIXTURE/home" \
        CLAUDE_TASK_ID="$TASK_ID" \
        "$PYTHON_BIN" "$REPO_ROOT/hooks/posttool-allowlist-consume.py"
  return $?
}

cd "$FIXTURE/work" || exit 1

# ===== BEAT 1 — an agent attempts a dangerous operation ===============================
sleep "$PACE_BEFORE_ATTEMPT"
echo "\$ $PUSH_CMD"

# ===== BEAT 2 + 3 — the real hook refuses it BEFORE execution, showing rule, =========
# =====             reason and a safe remedy. All of that text is the hook's. =========
pretool_push
RC1=$?
sleep "$PACE_READ_REFUSAL"

# ===== BEAT 4 — a narrowly-scoped grant permits EXACTLY ONE operation ================
# The grant is installed by the VERIFIER, never by this script, and only now -- after the
# unaided refusal of beats 1-3 has already been captured. This script cannot write, move
# or delete a grant; it can only ask the verifier to install one and wait for the ack.
: > "$FIXTURE/work/.request-grant"
RDV_WAITED=0
while [ ! -e "$FIXTURE/work/.grant-installed" ]; do
  sleep 0.05
  RDV_WAITED=$((RDV_WAITED + 1))
  if [ "$RDV_WAITED" -gt 200 ]; then
    echo "run-hero-demo: verifier never installed the grant" >&2
    exit 2
  fi
done
echo "\$ $PUSH_CMD"
pretool_push
RC2=$?
if [ "$RC2" -ne 0 ]; then
  echo "run-hero-demo: expected the granted retry to be permitted" >&2
  exit 2
fi
sleep "$PACE_AFTER_GRANT"

# The push actually executes — against the hermetic local bare remote, by RELATIVE path.
git push hero-remote main 2>&1
PUSH_RC=$?
sleep "$PACE_AFTER_PUSH"

# ===== BEAT 5a — the REAL posttool consumer consumes that grant =======================
# The marker line below is emitted by hooks/lib/allowlist.py, not by this script.
posttool_consume
sleep "$PACE_AFTER_CONSUME"

# ===== BEAT 5b — repeating the operation fails because the grant was consumed =========
echo "\$ $PUSH_CMD"
pretool_push
RC3=$?
sleep "$PACE_TAIL"

if [ "$RC1" -ne 2 ] || [ "$RC3" -ne 2 ]; then
  echo "run-hero-demo: expected refusal (exit 2) on beats 1 and 5" >&2
  exit 2
fi
exit 0
