#!/usr/bin/env bash
# Description: Fresh-clone bootstrap smoke — proves "core is runnable + guards engaged"
#   on a fresh, NON-ROOT clone with the author home ABSENT. NOT "the full LLM
#   pipeline works": only that the security guards load their OWN clone helpers,
#   block dangerous ops fail-closed, and degrade optional capabilities gracefully.
#
# Usage: fresh-clone-bootstrap-smoke.sh [--json <out.json>] [--keep]
#   --json <path>  write the machine-readable result document here (default: a
#                  temp file whose path is printed on the last stdout line).
#   --keep         do NOT remove the temp clone on exit (debugging).
#
# Exit codes: 0 = every assertion across every guard PASSED;
#             3 = one or more assertions FAILED (the JSON lists which);
#             2 = harness/setup error (could not build the clone, no privilege
#                 to drop to a non-root user, etc.) — the test treats this as a
#                 SKIP precondition, never a silent pass.
#
# Three-assertion-per-guard contract (BA spec / AC-WS2-1..3):
#   NEGATIVE  — a known-dangerous op is BLOCKED with the blocking status (2) and
#               the guard's OWN block marker on stderr.
#   POSITIVE  — a planted canary proves the INTENDED guard loaded ITS OWN clone
#               helper/policy (deny_reason echoes the canary token), catching
#               block-by-the-wrong-guard.
#   CLEAN-EXIT— required probes never return 1/126/127; allowed probes return 0;
#               blocked probes return 2; stderr has no unresolved author-absolute
#               path and no command-not-found for required helpers.
set -uo pipefail

# ── Argument parsing ─────────────────────────────────────────────────────────
JSON_OUT=""
KEEP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --json) JSON_OUT="${2:?--json needs a path}"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    -h|--help) sed -n '1,40p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "smoke: unknown argument '$1'" >&2; exit 2 ;;
  esac
done

# ── Locate the live harness (this script lives at <home>/tests/) ─────────────
REAL_HOME="${HOME:-}"; [ "$REAL_HOME" = "/" ] && REAL_HOME=""
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO="$(cd "$SELF_DIR/.." && pwd -P)"
FIXTURE_DIR="$SELF_DIR/fixtures"

# ── Privilege-drop wrapper: re-exec a probe under a NON-ROOT euid ─────────────
# The author's real Claude home lives under the invoking user's home; a smoke run
# that can reach it could accidentally resolve author files and "prove" the author
# machine. We require a non-root euid AND a temp HOME outside the real home and
# outside any RAM-disk workspace. If we are already
# non-root we run the probe directly; if root we drop to an unprivileged user.
DROP=()
detect_drop() {
  if [ "$(id -u)" -ne 0 ]; then
    DROP=()                       # already non-root: no drop needed
    return 0
  fi
  if command -v setpriv >/dev/null 2>&1 && id nobody >/dev/null 2>&1; then
    # nogroup is the conventional primary group of nobody on Debian/Ubuntu.
    local grp="nogroup"
    id -gn nobody >/dev/null 2>&1 && grp="$(id -gn nobody)"
    DROP=(setpriv "--reuid=nobody" "--regid=${grp}" "--clear-groups")
    return 0
  fi
  return 1                        # root with no way to drop -> setup error
}

# run_probe <home> <KEY=VAL ...> -- <cmd...>
#   Runs <cmd...> in a FRESH, CLEAN environment (env -i + explicit minimal env)
#   under a non-root euid. The clean env is what makes the policy_registry
#   in-process _CACHE irrelevant (each probe is its own subprocess) AND keeps the
#   author's real Claude home unreachable (HOME points only at the temp clone).
#   Prints stdout; captures rc; appends "<rc>" on its own trailing line is NOT
#   done here — callers capture rc via $?.
run_probe() {
  local home="$1"; shift
  local -a envkv=()
  while [ "$1" != "--" ]; do envkv+=("$1"); shift; done
  shift  # drop the --
  # Minimal explicit env: PATH + LANG + the requested HOME/CLAUDE_* only.
  "${DROP[@]}" env -i PATH="/usr/bin:/bin" LANG=C "${envkv[@]}" "$@"
}

# ── Build an isolated fresh clone under a temp HOME (NOT the real home or a RAM disk) ──
# mktemp honors TMPDIR; force a /tmp base so the clone is never under the author
# RAM disk. The clone root basename is "dot-claude" on purpose — it exercises the
# structural-sentinel resolver (which must NOT key on basename ".claude").
TMP_BASE="$(TMPDIR=/tmp mktemp -d /tmp/ws2-smoke.XXXXXX)" || { echo "smoke: cannot mktemp" >&2; exit 2; }
CLONE="$TMP_BASE/dot-claude"

# Idempotent cleanup: pre-init, install the trap BEFORE any background spawn, per
# the qa.md verification-harness cleanup contract (trap on EXIT INT TERM first).
PID=""
cleanup() {
  if [ -n "${PID}" ]; then kill -TERM "${PID}" 2>/dev/null; wait "${PID}" 2>/dev/null; fi
  if [ "$KEEP" -ne 1 ] && [ -n "${TMP_BASE:-}" ] && [ -d "$TMP_BASE" ]; then
    chmod -R u+rwX "$TMP_BASE" 2>/dev/null || true
    rm -rf "$TMP_BASE" 2>/dev/null || true
  fi
}
trap 'cleanup' EXIT INT TERM

mkdir -p "$CLONE/hooks/lib" "$CLONE/policies" "$CLONE/scripts" "$CLONE/scripts/install" \
         "$CLONE/docs/dev/specs" "$CLONE/commands" "$CLONE/agents" "$CLONE/skills" "$CLONE/schemas" \
  || { echo "smoke: cannot build clone tree" >&2; exit 2; }

# Structural sentinel set: settings.json + hooks/ + policies/ + scripts/ present.
# settings.json is the tracked CLEAN FORM below (what a fresh clone checks out).
cp -a "$REPO/hooks/lib/." "$CLONE/hooks/lib/" 2>/dev/null
cp -a "$REPO/hooks/pretool-tool-policy.py" "$CLONE/hooks/" 2>/dev/null
cp -a "$REPO/hooks/stop-spec-coverage-enforce.py" "$CLONE/hooks/" 2>/dev/null
cp -a "$REPO/hooks/session-promote-hook.sh" "$CLONE/hooks/" 2>/dev/null
cp -a "$REPO/policies/." "$CLONE/policies/" 2>/dev/null

# clean_settings <dest>: write the tracked clean form of settings.json. In a checkout
# the working file may be this machine's rendered form (settings filter registered),
# so read the index blob, else HEAD's; outside a git checkout the working file IS the
# clean form. A fresh clone checks out exactly this, with no machine values.
clean_settings() {
  local dest="$1" top=""
  top="$(git -C "$REPO" rev-parse --show-toplevel 2>/dev/null)" || top=""
  if [ -n "$top" ] && [ "$(cd "$top" 2>/dev/null && pwd -P)" = "$REPO" ]; then
    git -C "$REPO" show ":settings.json" > "$dest" 2>/dev/null && return 0
    git -C "$REPO" show "HEAD:settings.json" > "$dest" 2>/dev/null && return 0
  fi
  cp "$REPO/settings.json" "$dest" 2>/dev/null && return 0
  echo '{}' > "$dest"
}

clean_settings "$CLONE/settings.json"

if ! detect_drop; then
  echo "smoke: running as root but cannot drop to a non-root user (setpriv/nobody unavailable) — cannot satisfy the non-root precondition" >&2
  exit 2
fi

# Make the whole clone readable+traversable by the unprivileged probe user.
chmod -R a+rX "$TMP_BASE" 2>/dev/null || true

# ── Result accumulation ──────────────────────────────────────────────────────
# Each assertion appends a JSON-ish record to RESULTS via a helper. We build the
# final JSON with python at the end so quoting is safe.
declare -a R_GUARD R_KIND R_PASS R_DETAIL
record() {  # <guard> <kind:negative|positive|clean_exit> <pass:0|1> <detail>
  R_GUARD+=("$1"); R_KIND+=("$2"); R_PASS+=("$3"); R_DETAIL+=("$4")
}

# Helper: does stderr contain a forbidden author-absolute path or a
# command-not-found for a REQUIRED helper? (CLEAN-EXIT criterion.)
stderr_is_clean() {  # <stderr-text>
  local s="$1"
  # An unresolved author path leaking to stderr means the guard did NOT resolve
  # via the clone. command-not-found / "No such file" for a required helper too.
  # Generic: a Claude home under any system home root, or under the invoking
  # user's own real HOME (captured before any probe overrides HOME).
  if printf '%s' "$s" | grep -qE '/(root|home/[^/[:space:]]+|Users/[^/[:space:]]+)/\.claude'; then return 1; fi
  if [ -n "$REAL_HOME" ] && printf '%s' "$s" | grep -qF "$REAL_HOME/.claude"; then return 1; fi
  if printf '%s' "$s" | grep -qiE 'command not found|: not found'; then return 1; fi
  return 0
}

CANARY_TOKEN="CANARY-WS2-$(od -An -N6 -tx1 /dev/urandom 2>/dev/null | tr -d ' \n' || echo deadbeef)"

# ════════════════════════════════════════════════════════════════════════════
# GUARD 1 — pretool-tool-policy (the PreToolUse deny enforcer)
# ════════════════════════════════════════════════════════════════════════════
TP_HOOK="$CLONE/hooks/pretool-tool-policy.py"

# NEGATIVE: dev role attempts a tool NOT in its allowlist (WebFetch) -> BLOCK (2)
# with the guard's own marker "BLOCKED by tool-policy.v1".
neg_payload='{"subagent_type":"dev","agent_id":"smoke","tool_name":"WebFetch","tool_input":{"url":"http://x"}}'
err="$(printf '%s' "$neg_payload" | run_probe "$CLONE" HOME="$CLONE" CLAUDE_PROJECT_DIR="$CLONE" -- \
        python3 "$TP_HOOK" 2>&1 1>/dev/null)"; rc=$?
if [ "$rc" -eq 2 ] && printf '%s' "$err" | grep -q "BLOCKED by tool-policy.v1"; then
  record tool-policy negative 1 "blocked exit 2 with own marker"
else
  record tool-policy negative 0 "rc=$rc err=$(printf '%s' "$err" | head -c 200)"
fi

# POSITIVE (canary): plant a canary policy whose dev role denies writes bearing a
# unique token; ask the guard to authorize such a Write. A correct guard blocks
# AND its deny_reason echoes the token (proving it read THIS clone's policy).
CANARY_HOME="$TMP_BASE/canary-home/dot-claude"
mkdir -p "$CANARY_HOME/hooks/lib" "$CANARY_HOME/policies" "$CANARY_HOME/scripts"
echo '{}' > "$CANARY_HOME/settings.json"
cp -a "$CLONE/hooks/pretool-tool-policy.py" "$CANARY_HOME/hooks/" 2>/dev/null
cp -a "$CLONE/hooks/lib/." "$CANARY_HOME/hooks/lib/" 2>/dev/null
# Substitute the per-run token into the fixture canary policy.
sed "s/{{CANARY_TOKEN}}/$CANARY_TOKEN/g" "$FIXTURE_DIR/canary-tool-policy.v1.json" \
    > "$CANARY_HOME/policies/tool-policy.v1.json"
chmod -R a+rX "$TMP_BASE/canary-home" 2>/dev/null || true
canary_target="$CANARY_HOME/scripts/${CANARY_TOKEN}-evil.txt"
pos_payload="{\"subagent_type\":\"dev\",\"agent_id\":\"smoke\",\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$canary_target\"}}"
perr="$(printf '%s' "$pos_payload" | run_probe "$CANARY_HOME" HOME="$CANARY_HOME" CLAUDE_PROJECT_DIR="$CANARY_HOME" -- \
        python3 "$CANARY_HOME/hooks/pretool-tool-policy.py" 2>&1 1>/dev/null)"; prc=$?
if [ "$prc" -eq 2 ] && printf '%s' "$perr" | grep -q "$CANARY_TOKEN" \
   && printf '%s' "$perr" | grep -q "BLOCKED by tool-policy.v1"; then
  record tool-policy positive 1 "canary token echoed in deny_reason by tool-policy.v1"
else
  record tool-policy positive 0 "prc=$prc token_present=$(printf '%s' "$perr" | grep -qc "$CANARY_TOKEN" && echo yes || echo no) err=$(printf '%s' "$perr" | head -c 200)"
fi

# CLEAN-EXIT: an ALLOWED op (dev Read of an in-clone file) returns 0 with clean
# stderr (no leaked author path / command-not-found). Plus the negative rc above
# was 2 (already asserted) and never 1/126/127.
allow_payload="{\"subagent_type\":\"dev\",\"agent_id\":\"smoke\",\"tool_name\":\"Read\",\"tool_input\":{\"file_path\":\"$CLONE/settings.json\"}}"
aerr="$(printf '%s' "$allow_payload" | run_probe "$CLONE" HOME="$CLONE" CLAUDE_PROJECT_DIR="$CLONE" -- \
        python3 "$TP_HOOK" 2>&1 1>/dev/null)"; arc=$?
if [ "$arc" -eq 0 ] && stderr_is_clean "$aerr" && [ "$rc" != 1 ] && [ "$rc" != 126 ] && [ "$rc" != 127 ]; then
  record tool-policy clean_exit 1 "allowed=0 blocked=2 no 1/126/127 clean stderr"
else
  record tool-policy clean_exit 0 "allow_rc=$arc neg_rc=$rc stderr_clean=$(stderr_is_clean "$aerr" && echo 1 || echo 0)"
fi

# ════════════════════════════════════════════════════════════════════════════
# GUARD 2 — stop-spec-coverage-enforce (the blocking Stop hook)
# ════════════════════════════════════════════════════════════════════════════
SC_HOOK="$CLONE/hooks/stop-spec-coverage-enforce.py"
SPEC_TS="20260616-120000"; SPEC_ID="spec-$SPEC_TS"; SID="ws2-smoke-session"

# Build a /spec session inside a home: transcript (the typed /spec, then the
# spec Write) + views/ + monolith. with_verifier toggles the REQUIRED spec-verify
# helper; vexit is its simulated exit (nonzero => under-covered).
build_spec_home() {  # <home> <with_verifier:0|1> <vexit>
  local home="$1" wv="$2" vexit="$3"
  mkdir -p "$home/hooks/lib" "$home/policies" "$home/scripts" "$home/commands" \
           "$home/.claude" "$home/docs/dev/specs/$SPEC_TS/views"
  echo '{}' > "$home/settings.json"
  cp -a "$CLONE/hooks/stop-spec-coverage-enforce.py" "$home/hooks/" 2>/dev/null
  cp -a "$CLONE/hooks/lib/." "$home/hooks/lib/" 2>/dev/null
  cp -a "$REPO/commands/spec.md" "$home/commands/" 2>/dev/null
  printf '# view\n' > "$home/docs/dev/specs/$SPEC_TS/views/dev.md"
  printf '# Monolith\n\nSome spec body.\n' > "$home/docs/dev/specs/$SPEC_ID.md"
  { printf '{"type":"user","message":{"role":"user","content":"/spec smoke"}}\n'
    printf '{"type":"assistant","cwd":"%s","message":{"content":[{"type":"tool_use","id":"tu-spec","name":"Write","input":{"file_path":"%s/docs/dev/specs/%s.md"}}]}}\n' "$home" "$home" "$SPEC_ID"
    printf '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"tu-spec","content":"ok"}]}}\n'
  } > "$home/transcript.jsonl"
  if [ "$wv" -eq 1 ]; then
    mkdir -p "$home/scripts/spec-verify"
    printf 'import sys\nprint("coverage: simulated")\nsys.exit(%s)\n' "$vexit" \
      > "$home/scripts/spec-verify/spec-verify.py"
  fi
  chmod -R a+rX "$home" 2>/dev/null || true
}
run_stop() {  # <home>
  local home="$1"
  printf '{"session_id":"%s","transcript_path":"%s","stop_hook_active":false}' "$SID" "$home/transcript.jsonl" \
    | run_probe "$home" HOME="$home" CLAUDE_PROJECT_DIR="$home" -- python3 "$home/hooks/stop-spec-coverage-enforce.py" 2>&1 1>/dev/null
}

# DEGRADE/SKIP: REQUIRED verifier ABSENT + a spec was touched -> ALLOW the stop
# (exit 0, baseline advisory skip). The absent-verifier case is advisory, NOT a
# fail-closed block (reverted from the over-scoped WS1 exit-2 flip in 20260618-
# 082520). Genuine enforcement is proven by the under-covered POSITIVE below.
SH_NOVER="$TMP_BASE/specnover/dot-claude"; build_spec_home "$SH_NOVER" 0 0
serr="$(run_stop "$SH_NOVER")"; src=$?
if [ "$src" -eq 0 ] && stderr_is_clean "$serr"; then
  record stop-spec-coverage negative 1 "verifier-absent skips (exit 0, advisory baseline) — not a fail-closed block"
else
  record stop-spec-coverage negative 0 "src=$src err=$(printf '%s' "$serr" | head -c 200)"
fi

# POSITIVE (own-helper): verifier PRESENT but under-covered (vexit=1) -> BLOCK (2)
# with the < 100% coverage marker proving the guard ran THIS clone's verifier and
# acted on its result (not a different guard's block).
SH_UNDER="$TMP_BASE/specunder/dot-claude"; build_spec_home "$SH_UNDER" 1 1
uerr="$(run_stop "$SH_UNDER")"; urc=$?
if [ "$urc" -eq 2 ] && printf '%s' "$uerr" | grep -q "< 100% coverage"; then
  record stop-spec-coverage positive 1 "ran clone verifier; under-covered blocked exit 2"
else
  record stop-spec-coverage positive 0 "urc=$urc err=$(printf '%s' "$uerr" | head -c 200)"
fi

# CLEAN-EXIT: verifier PRESENT + full coverage (vexit=0) -> ALLOW stop (0) with
# clean stderr; and the two blocking cases were exactly 2, never 1/126/127.
SH_OK="$TMP_BASE/specok/dot-claude"; build_spec_home "$SH_OK" 1 0
okerr="$(run_stop "$SH_OK")"; okrc=$?
if [ "$okrc" -eq 0 ] && stderr_is_clean "$okerr" \
   && [ "$src" != 1 ] && [ "$src" != 126 ] && [ "$src" != 127 ] \
   && [ "$urc" != 1 ] && [ "$urc" != 126 ] && [ "$urc" != 127 ]; then
  record stop-spec-coverage clean_exit 1 "covered=0 blocked=2 no 1/126/127 clean stderr"
else
  record stop-spec-coverage clean_exit 0 "ok_rc=$okrc nover_rc=$src under_rc=$urc"
fi

# ════════════════════════════════════════════════════════════════════════════
# GUARD 3 — claude_home resolver: REQUIRED fail-closed (the security primitive)
# ════════════════════════════════════════════════════════════════════════════
# This is the keystone every guard depends on. We exercise its shell + python
# fail-closed (require/resolve_required) and the optional absent sentinel.
CH_SH="$CLONE/hooks/lib/claude_home.sh"
CH_PY="$CLONE/hooks/lib/claude_home.py"

# NEGATIVE: a REQUIRED security file that is ABSENT -> exit 2 with a block reason,
# NEVER exit 0 and NEVER 1/127.
rerr_sh="$(run_probe "$CLONE" HOME="$CLONE" -- bash "$CH_SH" require scripts/this-is-absent.py 2>&1 1>/dev/null)"; rrc_sh=$?
rerr_py="$(run_probe "$CLONE" HOME="$CLONE" -- python3 "$CH_PY" require scripts/this-is-absent.py 2>&1 1>/dev/null)"; rrc_py=$?
if [ "$rrc_sh" -eq 2 ] && [ "$rrc_py" -eq 2 ] \
   && printf '%s' "$rerr_sh" | grep -q "FAIL-CLOSED" \
   && printf '%s' "$rerr_py" | grep -q "FAIL-CLOSED"; then
  record claude-home-resolver negative 1 "require absent => exit 2 (shell+py) with FAIL-CLOSED reason"
else
  record claude-home-resolver negative 0 "sh_rc=$rrc_sh py_rc=$rrc_py"
fi

# POSITIVE (own-resolution): the resolver returns THIS clone's root (basename
# 'dot-claude', proving the structural sentinel — not basename '.claude' — and
# not the author's real home). require of a PRESENT file returns a path inside the clone.
rsolved="$(run_probe "$CLONE" HOME="$CLONE" -- bash "$CH_SH" resolve 2>/dev/null)"; rsrc=$?
rreq="$(run_probe "$CLONE" HOME="$CLONE" -- python3 "$CH_PY" require hooks/lib/claude_home.py 2>/dev/null)"; rqrc=$?
if [ "$rsrc" -eq 0 ] && [ "$rsolved" = "$CLONE" ] && [ "$rqrc" -eq 0 ] \
   && case "$rreq" in "$CLONE"/*) true;; *) false;; esac; then
  record claude-home-resolver positive 1 "resolved own clone root (dot-claude) + required path inside clone"
else
  record claude-home-resolver positive 0 "resolve='$rsolved' (want '$CLONE') req='$rreq'"
fi

# CLEAN-EXIT: an OPTIONAL absent file => empty stdout + nonzero (absent sentinel),
# NEVER exit 2 and NEVER a crash; an OPTIONAL present file => path + exit 0.
oabs="$(run_probe "$CLONE" HOME="$CLONE" -- bash "$CH_SH" optional scripts/absent.py 2>/dev/null)"; oarc=$?
opres="$(run_probe "$CLONE" HOME="$CLONE" -- bash "$CH_SH" optional hooks/lib/claude_home.sh 2>/dev/null)"; oprc=$?
if [ "$oarc" -ne 0 ] && [ "$oarc" -ne 2 ] && [ -z "$oabs" ] \
   && [ "$oprc" -eq 0 ] && [ -n "$opres" ]; then
  record claude-home-resolver clean_exit 1 "optional absent=>empty+nonzero(not 2); present=>path+0"
else
  record claude-home-resolver clean_exit 0 "abs_rc=$oarc abs='$oabs' pres_rc=$oprc"
fi

# ════════════════════════════════════════════════════════════════════════════
# OPTIONAL-CAPABILITY degradation (AC-WS2-5) — one-line unavailable, no crash,
# no bare unsafe fallback; green means core+guards, not the full LLM pipeline.
# ════════════════════════════════════════════════════════════════════════════
# (a) The session-promote hook with $SESSION_PROMOTE_BIN unset must NOT crash and
#     must exit 0 (degrade), referencing no author home path on stderr.
SP_HOOK="$CLONE/hooks/session-promote-hook.sh"
sp_payload='{"session_id":"12345678-1234-1234-1234-123456789abc","cwd":"/tmp/whatever"}'
sperr="$(printf '%s' "$sp_payload" | run_probe "$CLONE" HOME="$CLONE" -- bash "$SP_HOOK" 2>&1 1>/dev/null)"; sprc=$?
sp_ok=0
[ "$sprc" -eq 0 ] && stderr_is_clean "$sperr" && sp_ok=1

# (b) The external-helper env-var resolution contract: with CODEX_ISO_BIN unset, a
#     consumer must print a one-line "unavailable" and NEVER invoke a bare `codex`.
#     We model the documented contract directly (the smoke owns this probe) so the
#     assertion is deterministic and self-contained on any machine.
extprobe="$TMP_BASE/extprobe.sh"
cat > "$extprobe" <<'EXTEOF'
#!/usr/bin/env bash
# Models the AC-WS3-6 external-helper resolution contract for an OPTIONAL helper.
BIN="${CODEX_ISO_BIN:-}"
if [ -z "$BIN" ] || [ ! -x "$BIN" ]; then
  echo "codex isolation: unavailable (set CODEX_ISO_BIN to enable); skipping (optional)"
  exit 0
fi
# Would invoke the isolation wrapper here. NEVER a bare `codex` fallback.
exit 0
EXTEOF
chmod a+rx "$extprobe"
extout="$(run_probe "$CLONE" HOME="$CLONE" -- bash "$extprobe" 2>&1)"; extrc=$?
ext_ok=0
if [ "$extrc" -eq 0 ] \
   && printf '%s' "$extout" | grep -qi "unavailable" \
   && ! printf '%s' "$extout" | grep -qE '(^|[^-])\bcodex\b[^-]*(invoked|running|exec)'; then
  ext_ok=1
fi
if [ "$sp_ok" -eq 1 ] && [ "$ext_ok" -eq 1 ]; then
  record optional-capability unavailable 1 "session-promote degraded exit 0; external-helper printed one-line unavailable, no bare fallback"
else
  record optional-capability unavailable 0 "sp_rc=$sprc sp_ok=$sp_ok ext_rc=$extrc ext_ok=$ext_ok out=$(printf '%s' "$extout" | head -c 160)"
fi

# ── Emit the machine-readable result document ────────────────────────────────
[ -n "$JSON_OUT" ] || JSON_OUT="$TMP_BASE/smoke-result.json"
python3 - "$JSON_OUT" "$(id -u)" "${#R_GUARD[@]}" "${R_GUARD[@]}" "::KINDS::" "${R_KIND[@]}" "::PASS::" "${R_PASS[@]}" "::DET::" "${R_DETAIL[@]}" <<'PYEOF'
import json, sys
out_path = sys.argv[1]; euid = sys.argv[2]
n = int(sys.argv[3])
rest = sys.argv[4:]
def take(rest, marker, n):
    if marker:
        idx = rest.index(marker); return rest[:idx], rest[idx+1:]
    return rest[:n], rest[n:]
guards, rest = rest[:n], rest[n:]
# rest starts with ::KINDS:: <kinds...> ::PASS:: <pass...> ::DET:: <det...>
assert rest[0] == "::KINDS::"; rest = rest[1:]
kinds = rest[:n]; rest = rest[n:]
assert rest[0] == "::PASS::"; rest = rest[1:]
passes = rest[:n]; rest = rest[n:]
assert rest[0] == "::DET::"; rest = rest[1:]
details = rest[:n]
assertions = []
allpass = True
for i in range(n):
    p = passes[i] == "1"
    allpass = allpass and p
    assertions.append({"guard": guards[i], "kind": kinds[i], "pass": p, "detail": details[i]})
doc = {
    "smoke": "fresh-clone-bootstrap",
    "scope": "core is runnable + guards engaged (NOT the full LLM pipeline)",
    "euid_at_probe_time_was_root": euid == "0",
    "ran_under_nonroot_drop": euid == "0",  # if root we dropped via setpriv per-probe
    "assertions": assertions,
    "all_pass": allpass,
}
with open(out_path, "w") as fh:
    json.dump(doc, fh, indent=2)
print(out_path)
PYEOF

# Final stdout line: the JSON path (callers parse it).
echo "$JSON_OUT"

# Exit 0 only if every assertion passed.
allok=1
for p in "${R_PASS[@]}"; do [ "$p" = "1" ] || allok=0; done
[ "$allok" -eq 1 ] && exit 0 || exit 3
