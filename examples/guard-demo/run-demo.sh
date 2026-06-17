#!/usr/bin/env bash
# Description: Reproducible guard demo — a dangerous operation is BLOCKED by the
#   tool-policy guard (fail-closed exit 2), then a properly-authorized,
#   grant-gated fix COMPLETES (allow exit 0 + the write actually lands).
#
#   This is the substantive, executable WS6 deliverable (AC-WS6-1). It runs the
#   REAL guard (hooks/pretool-tool-policy.py) and the REAL shared harness-home
#   resolver (hooks/lib/claude_home.sh) against an isolated, ephemeral demo home,
#   so it is re-runnable on ANY machine under a non-root $HOME with the author's
#   /root/.claude absent. No author-absolute paths; no external binaries; the
#   demo home is built fresh each run, making the block-then-grant-then-complete
#   sequence deterministic regardless of install location.
#
#   A recorded terminal cast is OPTIONAL and is NOT required for the scenario to
#   be valid — the scenario IS the executable script below.
#
# Usage: run-demo.sh [--keep] [--quiet]
#   --keep   leave the ephemeral demo home in place (debugging); default removes
#            it via the script's own EXIT trap.
#   --quiet  suppress the narrated step output; exit code still reflects success.
#
# Exit codes:
#   0 = the full block-then-grant-then-complete sequence behaved as designed
#       (dangerous op blocked with exit 2 + the guard's own marker; authorized
#        fix allowed with exit 0; the fix write actually landed on disk).
#   1 = some step did not behave as designed (the narration names which).
#   2 = setup precondition unmet (could not locate the live harness from this
#       script's own location, or could not build the demo home).

set -uo pipefail

# ── Argument parsing ─────────────────────────────────────────────────────────
KEEP=0
QUIET=0
while [ $# -gt 0 ]; do
  case "$1" in
    --keep)  KEEP=1; shift ;;
    --quiet) QUIET=1; shift ;;
    -h|--help) sed -n '1,40p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "run-demo.sh: unknown argument '$1'" >&2; exit 2 ;;
  esac
done

say() { [ "$QUIET" -eq 1 ] || printf '%s\n' "$*"; }
step() { [ "$QUIET" -eq 1 ] || printf '\n=== %s ===\n' "$*"; }

# ── Locate the live harness from THIS script's own location ──────────────────
# This script lives at <harness-home>/examples/guard-demo/run-demo.sh, so the
# harness home is two directories up. We do NOT hardcode /root; we resolve from
# the running file, exactly like the shared resolver does — making the demo
# portable to any clone location.
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)" || {
  echo "run-demo: cannot determine own location" >&2; exit 2; }
HARNESS_HOME="$(cd "$SELF_DIR/../.." && pwd -P)" || {
  echo "run-demo: cannot locate harness home (expected two levels above $SELF_DIR)" >&2; exit 2; }

RESOLVER="$HARNESS_HOME/hooks/lib/claude_home.sh"
GUARD="$HARNESS_HOME/hooks/pretool-tool-policy.py"
for required in "$RESOLVER" "$GUARD"; do
  if [ ! -f "$required" ]; then
    echo "run-demo: required harness file absent: $required (is this a complete clone?)" >&2
    exit 2
  fi
done

# Resolve the Python interpreter ONCE, by absolute path, so the guard probes can
# invoke it under env -i (which clears PATH) on machines where python3 is not in
# /usr/bin:/bin. Absent python3 is a setup precondition, not a guard failure.
PYTHON_BIN="$(command -v python3 || true)"
if [ -z "$PYTHON_BIN" ] || [ ! -x "$PYTHON_BIN" ]; then
  echo "run-demo: python3 not found on PATH — cannot run the guard (precondition)" >&2
  exit 2
fi

# ── Build an isolated, ephemeral demo home (NOT under /root, NOT /dev/shm) ────
# mktemp honors TMPDIR; force a /tmp base so the demo home is never under the
# author RAM disk. The root basename is "dot-claude" on purpose — it exercises
# the STRUCTURAL-sentinel resolver, which must NOT key on the basename ".claude".
TMP_BASE="$(TMPDIR=/tmp mktemp -d /tmp/guard-demo.XXXXXX)" || {
  echo "run-demo: cannot mktemp a demo home" >&2; exit 2; }
DEMO_HOME="$TMP_BASE/dot-claude"

cleanup() {
  if [ "$KEEP" -ne 1 ] && [ -n "${TMP_BASE:-}" ] && [ -d "$TMP_BASE" ]; then
    chmod -R u+rwX "$TMP_BASE" 2>/dev/null || true
    find "$TMP_BASE" -mindepth 1 -delete 2>/dev/null || true
    rmdir "$TMP_BASE" 2>/dev/null || true
  fi
}
trap 'cleanup' EXIT INT TERM

# Structural sentinel set the resolver walks to: settings.json + hooks/ +
# policies/ + scripts/ present together. We copy in only the guard + its lib so
# the demo is a faithful slice of the real harness, not a mock.
mkdir -p "$DEMO_HOME/hooks/lib" "$DEMO_HOME/policies" "$DEMO_HOME/scripts" \
         "$DEMO_HOME/work" \
  || { echo "run-demo: cannot build demo home tree" >&2; exit 2; }
# Fail FAST on any setup error so a copy/write failure can never masquerade as
# guard behavior (a missing guard would otherwise look like a "block").
cp -a "$HARNESS_HOME/hooks/lib/." "$DEMO_HOME/hooks/lib/" \
  || { echo "run-demo: cannot copy hooks/lib into the demo home" >&2; exit 2; }
cp -a "$GUARD" "$DEMO_HOME/hooks/" \
  || { echo "run-demo: cannot copy the guard into the demo home" >&2; exit 2; }
echo '{}' > "$DEMO_HOME/settings.json" \
  || { echo "run-demo: cannot write the demo settings.json" >&2; exit 2; }
[ -f "$DEMO_HOME/hooks/pretool-tool-policy.py" ] \
  || { echo "run-demo: guard not present in the demo home after copy" >&2; exit 2; }

# The demo's own scoped policy. The `dev` role may write anywhere EXCEPT a path
# bearing the unique DEMO-FORBIDDEN token (a stand-in for any protected target).
# This makes the block deterministic and install-location-independent: the glob
# matches the canonical absolute target wherever the demo home lands.
cat > "$DEMO_HOME/policies/tool-policy.v1.json" <<'POLICY'
{
  "_demo": "examples/guard-demo — scoped policy for AC-WS6-1. The dev role is",
  "_demo2": "denied any write whose path contains DEMO-FORBIDDEN (the dangerous",
  "_demo3": "target), and is granted writes anywhere else (the authorized fix).",
  "policy_version": "guard-demo-v1",
  "default_action": "deny",
  "roles": {
    "dev": {
      "allowed_tools": ["Read", "Glob", "Grep", "Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "Skill"],
      "allowed_write_path_prefixes": ["*"],
      "denied_write_path_prefixes": ["*DEMO-FORBIDDEN*"]
    }
  }
}
POLICY
[ -s "$DEMO_HOME/policies/tool-policy.v1.json" ] \
  || { echo "run-demo: cannot write the demo policy" >&2; exit 2; }

# ── Sanity: the shared resolver finds the demo home structurally ─────────────
# This proves the demo consumes the WS1 resolver (not a hardcoded path) — the
# guard below relies on the SAME resolution to find its policy. We invoke the
# DEMO's own copy of the resolver so its PRIMARY script-walk (from the running
# file's location) lands on the demo home, exactly as the guard's in-clone
# import of claude_home.py does on a fresh clone.
DEMO_RESOLVER="$DEMO_HOME/hooks/lib/claude_home.sh"
RESOLVED="$(HOME="$DEMO_HOME" CLAUDE_PROJECT_DIR="$DEMO_HOME" bash "$DEMO_RESOLVER" resolve 2>/dev/null)"
if [ "$RESOLVED" != "$DEMO_HOME" ]; then
  say "FAIL: shared resolver did not resolve the demo home structurally"
  say "      (resolved '$RESOLVED', expected '$DEMO_HOME')"
  exit 1
fi
say "Harness home (live):  $HARNESS_HOME"
say "Demo home (ephemeral): $DEMO_HOME"
say "Shared resolver resolved the demo home by structural sentinel (basename 'dot-claude', not '.claude')."

# ── Helper: ask the REAL guard to authorize a dev-role Write ─────────────────
# Returns the guard exit code; captures stderr (the guard's block marker) into
# the named variable. Runs in a clean env so no author /root path can leak in.
ask_guard() {  # <out_stderr_var> <target_path>
  local __outvar="$1" target="$2" payload err rc
  payload="$(printf '{"subagent_type":"dev","agent_id":"guard-demo","tool_name":"Write","tool_input":{"file_path":"%s"}}' "$target")"
  err="$(printf '%s' "$payload" \
          | env -i PATH="/usr/bin:/bin" LANG=C HOME="$DEMO_HOME" CLAUDE_PROJECT_DIR="$DEMO_HOME" \
                python3 "$DEMO_HOME/hooks/pretool-tool-policy.py" 2>&1 1>/dev/null)"
  rc=$?
  printf -v "$__outvar" '%s' "$err"
  return "$rc"
}

OVERALL=0

# ── STEP 1 — the dangerous operation is BLOCKED (fail-closed) ────────────────
step "STEP 1 — attempt a DANGEROUS operation (must be BLOCKED)"
DANGEROUS_TARGET="$DEMO_HOME/work/DEMO-FORBIDDEN-overwrite-a-guard.txt"
say "An agent (role: dev) attempts to write to a protected target:"
say "  $DANGEROUS_TARGET"
ask_guard BLOCK_ERR "$DANGEROUS_TARGET"; BLOCK_RC=$?
if [ "$BLOCK_RC" -eq 2 ] && printf '%s' "$BLOCK_ERR" | grep -q "BLOCKED by tool-policy.v1"; then
  say "BLOCKED (exit 2) by the guard, fail-closed:"
  say "  $(printf '%s' "$BLOCK_ERR" | head -c 240)"
  # The dangerous write must NOT have landed (the guard runs BEFORE the tool).
  if [ -e "$DANGEROUS_TARGET" ]; then
    say "FAIL: the dangerous target exists despite the block."
    OVERALL=1
  fi
else
  say "FAIL: dangerous op was NOT blocked as designed (rc=$BLOCK_RC)."
  say "  stderr: $(printf '%s' "$BLOCK_ERR" | head -c 240)"
  OVERALL=1
fi

# ── STEP 2 — a properly-authorized, grant-gated fix is ALLOWED ───────────────
step "STEP 2 — apply a properly-AUTHORIZED fix (must be ALLOWED)"
FIX_TARGET="$DEMO_HOME/work/fix-applied.txt"
say "The same agent now performs the authorized, in-scope fix:"
say "  $FIX_TARGET"
ask_guard ALLOW_ERR "$FIX_TARGET"; ALLOW_RC=$?
if [ "$ALLOW_RC" -eq 0 ]; then
  say "ALLOWED (exit 0) by the guard — the operation is within policy."
else
  say "FAIL: authorized fix was NOT allowed (rc=$ALLOW_RC)."
  say "  stderr: $(printf '%s' "$ALLOW_ERR" | head -c 240)"
  OVERALL=1
fi

# ── STEP 3 — the authorized fix COMPLETES (the write actually lands) ─────────
step "STEP 3 — the authorized fix COMPLETES"
if [ "$ALLOW_RC" -eq 0 ]; then
  printf 'guard demo: fix applied after grant-gated authorization\n' > "$FIX_TARGET" 2>/dev/null
  if [ -s "$FIX_TARGET" ]; then
    say "Fix write landed on disk:"
    say "  $FIX_TARGET -> $(head -c 80 "$FIX_TARGET")"
  else
    say "FAIL: authorized fix write did not land."
    OVERALL=1
  fi
else
  say "SKIPPED: STEP 2 did not authorize the fix, so STEP 3 cannot complete."
  OVERALL=1
fi

# ── Summary ──────────────────────────────────────────────────────────────────
step "RESULT"
if [ "$OVERALL" -eq 0 ]; then
  say "PASS — dangerous op BLOCKED (exit 2), then grant-gated fix COMPLETED (exit 0 + write landed)."
  say "Re-run this script under any non-root \$HOME for the same deterministic result."
else
  say "FAIL — the block-then-grant-then-complete sequence did not behave as designed."
fi
exit "$OVERALL"
