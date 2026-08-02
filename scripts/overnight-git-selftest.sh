#!/usr/bin/env bash
# overnight-git-selftest.sh — launch git-version + symref self-test (M8, M16).
#
# Probes the EFFECTIVE git the overnight actor will use and emits a JSON object
# (last stdout line: SELFTEST_JSON=<json>) with the honest guarantee fields:
#   git_version, git_effective_path, git_exec_path,
#   reference_transaction_selftest_result (one of:
#       "structural_head_switch"      — >=2.46 AND functional keystone-abort of a
#                                        plain HEAD branch-switch passed,
#       "branch_ref_only"             — keystone fires for master-ref/HEAD-detach
#                                        but NOT for a symref branch-switch (2.43),
#       "hook_not_firing"             — keystone did not fire at all),
#   guarantee_level ("structural_head_switch" | "best_effort_head_switch"),
#   structural_claim_allowed (true|false).
#
# M16 gate: structural_claim_allowed=true ONLY when ALL hold:
#   (1) effective git --version >= 2.46 AND git --exec-path inside the slot,
#   (2) a FUNCTIONAL throwaway-repo test: a plain HEAD branch-switch fires the
#       keystone AND the keystone actually ABORTS it,
#   (3) a non-mutating TARGET-repo attestation: core.hooksPath == expected,
#       keystone hook hash matches, blessed token ABSENT from the env.
# Any failure => best_effort_head_switch + structural_claim_allowed=false.
#
# Isolation/worktree creation is NEVER gated on this — the caller proceeds
# regardless; only the CLAIM is downgraded.
#
# Usage: overnight-git-selftest.sh --project-dir <main_root> [--git-bin <path>]
#                                  [--keystone-dir <dir>]
# Exit: always 0 (self-test never blocks launch); JSON carries the verdict.

set -uo pipefail

PROJECT_DIR=""
GIT_BIN=""
KEYSTONE_DIR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-dir) PROJECT_DIR="$2"; shift 2 ;;
    --git-bin) GIT_BIN="$2"; shift 2 ;;
    --keystone-dir) KEYSTONE_DIR="$2"; shift 2 ;;
    *) shift ;;
  esac
done
[[ -n "$PROJECT_DIR" ]] || PROJECT_DIR="$(pwd)"

# Resolve the effective git (selector-aware). If a modern slot exists, use it.
SLOT="${CLAUDE_MODERN_GIT_SLOT:-$PROJECT_DIR/.claude/modern-git-slot}"
if [[ -z "$GIT_BIN" ]]; then
  if [[ -x "$SLOT/bin/git" ]]; then GIT_BIN="$SLOT/bin/git"; else GIT_BIN="$(command -v git || echo /usr/bin/git)"; fi
fi

GIT_VERSION="$("$GIT_BIN" --version 2>/dev/null | awk '{print $3}')"
GIT_EXEC_PATH="$("$GIT_BIN" --exec-path 2>/dev/null || echo '')"
GIT_EFFECTIVE_PATH="$GIT_BIN"

# Version comparison: is GIT_VERSION >= 2.46 ?
_ge_246() {
  local v="${1:-0.0.0}"; local maj min
  maj="$(printf '%s' "$v" | cut -d. -f1)"; min="$(printf '%s' "$v" | cut -d. -f2)"
  [[ "$maj" =~ ^[0-9]+$ ]] || return 1
  [[ "$min" =~ ^[0-9]+$ ]] || min=0
  if [[ "$maj" -gt 2 ]]; then return 0; fi
  if [[ "$maj" -eq 2 && "$min" -ge 46 ]]; then return 0; fi
  return 1
}

KEYSTONE_SRC="${KEYSTONE_DIR:-$(cd "$(dirname "$0")/.." && pwd)/hooks/git-keystone}/reference-transaction"
SHIM_SRC="$(cd "$(dirname "$0")" && pwd)/overnight-git/git-policy-shim"
LAUNCHER_SRC="$(cd "$(dirname "$0")" && pwd)/create-overnight-state.sh"

# One scratch root for every probe below; removed by the single trap.
PROBE_ROOT="$(mktemp -d 2>/dev/null || echo '')"
if [[ -n "$PROBE_ROOT" ]]; then
  trap 'rm -rf "$PROBE_ROOT" 2>/dev/null' EXIT INT TERM
fi

# ---------------------------------------------------------------------------
# Runtime entropy (M5-NO-ENUMERATION / QA OBJ-9).
# The decisive operands are generated HERE, at selftest runtime, from a real
# entropy source. They therefore cannot appear in any enumeration, allowlist,
# regex or fixture written before this run — which is what makes every ordinary
# name-keyed implementation fail rather than merely be unlikely to pass.
# ---------------------------------------------------------------------------
_rand_stem() {
  local s=""
  s="$(head -c 8 /dev/urandom 2>/dev/null | od -An -tx1 2>/dev/null | tr -d ' \n')"
  if [[ ${#s} -lt 8 ]]; then
    s="$(date +%s%N 2>/dev/null | sha256sum 2>/dev/null | cut -c1-16)"
  fi
  printf '%s' "${s:0:16}"
}
STEM="$(_rand_stem)"
OP_A="ovnprobe-${STEM}-a"
OP_B="ovnprobe-${STEM}-b"

# Write a resolver-valid, live, schema-v9, NON-RELEASED session-state record at
# the path a real consumer searches (M8b property 7). The D1-unresolved level is
# produced by NOT calling this at all — never by malforming the file, which
# would test parser tolerance instead of resolution.
_write_probe_state() {
  local dir="$1" branch="$2"
  mkdir -p "$dir/.claude"
  cat > "$dir/.claude/overnight-state-probe-${STEM}.json" <<PROBESTATE
{
  "schema_version": 9,
  "session_id": "probe-${STEM}",
  "isolation_released_at": null,
  "protected_branch": "${branch}"
}
PROBESTATE
}

# Build a throwaway probe repo. HEAD is parked on a THIRD idle branch, so
# neither operand is the current branch of ANY worktree (M8b property 6) — both
# because a "deny any non-checked-out branch" rule must not pass, and because
# git itself refuses a forced move of a checked-out branch with a `fatal` raised
# BEFORE any transaction opens, which would satisfy "exit!=0 + OID unchanged"
# for entirely the wrong reason.
# Operands are created at the SAME commit, in the SAME order, with IDENTICAL
# histories, so history / reachability / creation order carry no signal.
_build_probe_repo() {
  local dir="$1" op1="$2" op2="$3" install_keystone="${4:-1}"
  mkdir -p "$dir"
  (
    cd "$dir" || exit 1
    "$GIT_BIN" init -q -b probe-idle . 2>/dev/null || "$GIT_BIN" init -q . 2>/dev/null
    "$GIT_BIN" symbolic-ref HEAD refs/heads/probe-idle >/dev/null 2>&1
    "$GIT_BIN" config user.email t@t >/dev/null 2>&1
    "$GIT_BIN" config user.name t >/dev/null 2>&1
    echo x > f; "$GIT_BIN" add f >/dev/null 2>&1
    CLAUDE_OVERNIGHT_ACTOR="" "$GIT_BIN" commit -qm base >/dev/null 2>&1
    CLAUDE_OVERNIGHT_ACTOR="" "$GIT_BIN" commit -q --allow-empty -m next >/dev/null 2>&1
    # base = the operands' start point; next = the requested new oid (genuine change)
    "$GIT_BIN" branch "$op1" HEAD~1 >/dev/null 2>&1
    "$GIT_BIN" branch "$op2" HEAD~1 >/dev/null 2>&1
    if [[ "$install_keystone" == "1" ]]; then
      mkdir -p hooks
      cp "$KEYSTONE_SRC" hooks/reference-transaction
      chmod +x hooks/reference-transaction
      "$GIT_BIN" config core.hooksPath "$dir/hooks" >/dev/null 2>&1
    fi
  )
}

# Parse THE single dedicated machine-readable denial line (M4-REASON-TOKENS).
# Emits "<reason>|<ref>|<n_reason>|<n_ref>". Assertions read these FIELDS; they
# never substring-search the stream, so an embedded lookalike such as `notref=`
# or a second `reason=` cannot satisfy them.
_parse_deny_line() {
  local blob="$1" line
  line="$(printf '%s\n' "$blob" | grep -E '^OVERNIGHT-(KEYSTONE|SHIM)-DENY ' | head -n1)"
  if [[ -z "$line" ]]; then printf '||0|0'; return; fi
  local reason="" ref="" n_reason=0 n_ref=0 tok
  for tok in $line; do
    case "$tok" in
      reason=*) n_reason=$((n_reason+1)); [[ -z "$reason" ]] && reason="${tok#reason=}" ;;
      ref=*)    n_ref=$((n_ref+1));       [[ -z "$ref" ]]    && ref="${tok#ref=}" ;;
    esac
  done
  printf '%s|%s|%s|%s' "$reason" "$ref" "$n_reason" "$n_ref"
}

# Attempt one actor-marked DIRECT branch-ref move and report the observation.
# Form (i) of M8b property 1: a direct branch-ref move emits ONLY
# refs/heads/<N>; git emits no HEAD transaction line, so the HEAD arm cannot
# fire and the only arm that can deny is the branch arm.
# Emits: exit|reason|ref|n_reason|n_ref|oid_changed|precondition_ok
_move_branch() {
  local repo="$1" op="$2" cwdctx="$3"
  local before after target out rc pre_ok=1 wd
  before="$("$GIT_BIN" -C "$repo" rev-parse "refs/heads/$op" 2>/dev/null || echo '')"
  target="$("$GIT_BIN" -C "$repo" rev-parse refs/heads/probe-idle 2>/dev/null || echo '')"
  # property 6 preconditions, asserted BEFORE the move
  [[ -n "$before" && -n "$target" && "$before" != "$target" ]] || pre_ok=0
  "$GIT_BIN" -C "$repo" cat-file -e "$target" 2>/dev/null || pre_ok=0
  "$GIT_BIN" -C "$repo" cat-file -e "$before" 2>/dev/null || pre_ok=0
  # neither operand may be current in ANY worktree
  if "$GIT_BIN" -C "$repo" worktree list --porcelain 2>/dev/null \
       | grep -qE "^branch refs/heads/($OP_A|$OP_B)$"; then pre_ok=0; fi
  if [[ "$cwdctx" == "scratch" ]]; then
    wd="$PROBE_ROOT/scratch-$STEM"
    mkdir -p "$wd"
    # preflight the three equalities of M8b property 5
    local pwdp top common
    pwdp="$(cd "$wd" && pwd -P)"
    top="$(cd "$wd" && GIT_DIR="$repo/.git" GIT_WORK_TREE="$wd" "$GIT_BIN" rev-parse --path-format=absolute --show-toplevel 2>/dev/null || echo '')"
    common="$(cd "$wd" && GIT_DIR="$repo/.git" GIT_WORK_TREE="$wd" "$GIT_BIN" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || echo '')"
    [[ "$top" == "$pwdp" ]] || pre_ok=0
    [[ "$common" == "$repo/.git" ]] || pre_ok=0
    out="$(cd "$wd" && CLAUDE_OVERNIGHT_ACTOR=1 GIT_DIR="$repo/.git" GIT_WORK_TREE="$wd" \
             "$GIT_BIN" branch -f "$op" "$target" 2>&1)"; rc=$?
  else
    out="$(cd "$repo" && CLAUDE_OVERNIGHT_ACTOR=1 "$GIT_BIN" branch -f "$op" "$target" 2>&1)"; rc=$?
  fi
  after="$("$GIT_BIN" -C "$repo" rev-parse "refs/heads/$op" 2>/dev/null || echo '')"
  local changed=0; [[ "$before" != "$after" ]] && changed=1
  printf '%s|%s|%s|%s' "$rc" "$(_parse_deny_line "$out")" "$changed" "$pre_ok"
}

# One counterfactual CELL. D1 selects which operand the state declares
# (A | B | NONE); D2 is the attempt order; D3 is the working-directory context.
# Every cell is built from a FRESH equivalent repo snapshot, which is what
# falsifies a state-blind rule that denies the first move it sees per repo.
CELLS_JSON=""
KS_FAIL=""
_record_cell() { CELLS_JSON="${CELLS_JSON}${CELLS_JSON:+,}$1"; }
_ks_fail() { KS_FAIL="${KS_FAIL}${KS_FAIL:+; }$1"; }

_ks_cell() {
  local d1="$1" d2="$2" d3="$3" idx="$4"
  local repo="$PROBE_ROOT/ks-$idx"
  _build_probe_repo "$repo" "$OP_A" "$OP_B" 1
  local protected="" control=""
  case "$d1" in
    A) protected="$OP_A"; control="$OP_B"; _write_probe_state "$repo" "$OP_A" ;;
    B) protected="$OP_B"; control="$OP_A"; _write_probe_state "$repo" "$OP_B" ;;
    NONE) protected="$OP_A"; control="$OP_B" ;;   # no record written at all
  esac
  local first second
  if [[ "$d2" == "P" ]]; then first="$protected"; second="$control"
  else first="$control"; second="$protected"; fi
  local r1 r2 rp rc_
  r1="$(_move_branch "$repo" "$first" "$d3")"
  r2="$(_move_branch "$repo" "$second" "$d3")"
  if [[ "$d2" == "P" ]]; then rp="$r1"; rc_="$r2"; else rp="$r2"; rc_="$r1"; fi
  IFS='|' read -r p_exit p_reason p_ref p_nreason p_nref p_changed p_pre <<<"$rp"
  IFS='|' read -r c_exit c_reason c_ref c_nreason c_nref c_changed c_pre <<<"$rc_"

  local label="d1=$d1,d2=$d2,d3=$d3"
  # A0 — a precondition violation is a DISTINCT setup error, never a pass and
  # never an ordinary deny.
  if [[ "$p_pre" != "1" || "$c_pre" != "1" ]]; then
    _ks_fail "SETUP_ERROR($label)"
  elif [[ "$d1" == "NONE" ]]; then
    # D1-unresolved: BOTH operands denied with the fail-closed token, and NO
    # control succeeds. This is what proves the verdict tracks the state VALUE
    # rather than merely differing between two names.
    [[ "$p_exit" != "0" && "$c_exit" != "0" ]] || _ks_fail "unresolved_not_denied($label)"
    [[ "$p_reason" == "unresolved_protected_branch" ]] || _ks_fail "unresolved_token_p($label:$p_reason)"
    [[ "$c_reason" == "unresolved_protected_branch" ]] || _ks_fail "unresolved_token_c($label:$c_reason)"
    [[ "$p_changed" == "0" && "$c_changed" == "0" ]] || _ks_fail "unresolved_oid_moved($label)"
  else
    [[ "$p_exit" != "0" ]]                       || _ks_fail "protected_not_denied($label)"
    [[ "$p_changed" == "0" ]]                    || _ks_fail "protected_oid_moved($label)"
    [[ "$p_ref" == "refs/heads/$protected" ]]    || _ks_fail "ref_field($label:$p_ref)"
    [[ "$p_ref" != "HEAD" ]]                     || _ks_fail "ref_is_HEAD($label)"
    [[ "$p_reason" == "branch_protected" ]]      || _ks_fail "reason_field($label:$p_reason)"
    [[ "$p_nreason" == "1" ]]                    || _ks_fail "reason_count($label:$p_nreason)"
    [[ "$p_nref" -le 1 ]]                        || _ks_fail "ref_count($label:$p_nref)"
    [[ "$c_exit" == "0" ]]                       || _ks_fail "control_denied($label:$c_reason)"
    [[ "$c_changed" == "1" ]]                    || _ks_fail "control_oid_unchanged($label)"
  fi
  _record_cell "$(D1="$d1" D2="$d2" D3="$d3" STEM="$STEM" OPA="$OP_A" OPB="$OP_B" \
    PROT="$protected" CTRL="$control" PE="$p_exit" PR="$p_reason" PF="$p_ref" PC="$p_changed" \
    CE="$c_exit" CR="$c_reason" CC="$c_changed" PRE="$p_pre" \
    jq -n '{d1:env.D1,d2:env.D2,d3:env.D3,stem:env.STEM,operand_a:env.OPA,operand_b:env.OPB,
            protected:env.PROT,control:env.CTRL,preconditions_ok:(env.PRE=="1"),
            protected_outcome:{exit:(env.PE|tonumber),reason:env.PR,ref:env.PF,oid_changed:(env.PC=="1")},
            control_outcome:{exit:(env.CE|tonumber),reason:env.CR,oid_changed:(env.CC=="1")}}' | jq -c .)"
}

# D1 x D2 x D3 = 8 resolved cells on ONE operand pair, plus the additional
# D1-unresolved level (which is NOT a member of the cross).
_run_branch_ref_arm_probe() {
  [[ -n "$PROBE_ROOT" && -x "$KEYSTONE_SRC" ]] || { _ks_fail "keystone_source_missing"; return; }
  local i=0 d1 d2 d3
  for d1 in A B; do for d2 in P C; do for d3 in root scratch; do
    i=$((i+1)); _ks_cell "$d1" "$d2" "$d3" "$i"
  done; done; done
  i=$((i+1)); _ks_cell NONE P root "$i"
  # Fixed regression anchors: the literal names the user's reported defect is
  # actually about. Their role is REGRESSION ANCHORING, not falsification —
  # every falsification claim rests on the runtime-random cross above.
  local anchor arepo actrl
  for anchor in master main trunk; do
    i=$((i+1)); arepo="$PROBE_ROOT/anchor-$i"; actrl="ovnctl-$(_rand_stem)"
    _build_probe_repo "$arepo" "$anchor" "$actrl" 1
    _write_probe_state "$arepo" "$anchor"
    local ra rc2
    ra="$(_move_branch "$arepo" "$anchor" root)"
    rc2="$(_move_branch "$arepo" "$actrl" root)"
    IFS='|' read -r a_exit a_reason a_ref a_nr a_nf a_ch a_pre <<<"$ra"
    IFS='|' read -r k_exit k_reason k_ref k_nr k_nf k_ch k_pre <<<"$rc2"
    [[ "$a_pre" == "1" && "$k_pre" == "1" ]] || _ks_fail "SETUP_ERROR(anchor=$anchor)"
    [[ "$a_exit" != "0" && "$a_reason" == "branch_protected" ]] || _ks_fail "anchor_not_denied($anchor:$a_reason)"
    [[ "$k_exit" == "0" ]] || _ks_fail "anchor_control_denied($anchor:$k_reason)"
    _record_cell "$(AN="$anchor" CT="$actrl" AE="$a_exit" AR="$a_reason" AF="$a_ref" KE="$k_exit" \
      jq -n '{anchor:env.AN,role:"regression_anchor_not_falsification",control:env.CT,
              protected_outcome:{exit:(env.AE|tonumber),reason:env.AR,ref:env.AF},
              control_outcome:{exit:(env.KE|tonumber)}}' | jq -c .)"
  done
}

# M8b property 8 — the SHIM is exercised as a SEPARATE consumer with the
# keystone out of its path, so a corrected keystone cannot mask a still-literal
# shim. The shim needs D1 alone; the full cross is the keystone's job.
SHIM_CELLS_JSON=""
SHIM_FAIL=""
_shim_eval() {   # $1=repo $2=operand -> exit|reason|ref|n_reason|n_ref
  local repo="$1" op="$2" out rc
  out="$(cd "$repo" && CLAUDE_OVERNIGHT_ACTOR=1 \
          CLAUDE_OVERNIGHT_MAIN_ROOT="$PROBE_ROOT/shim-main" \
          CLAUDE_OVERNIGHT_REAL_GIT="$PROBE_ROOT/stub-git" \
          bash "$SHIM_SRC" update-ref "refs/heads/$op" HEAD 2>&1)"; rc=$?
  printf '%s|%s' "$rc" "$(_parse_deny_line "$out")"
}
_run_shim_probe() {
  [[ -n "$PROBE_ROOT" && -x "$SHIM_SRC" ]] || { SHIM_FAIL="shim_source_missing"; return; }
  mkdir -p "$PROBE_ROOT/shim-main"
  printf '#!/usr/bin/env bash\nexit 0\n' > "$PROBE_ROOT/stub-git"; chmod +x "$PROBE_ROOT/stub-git"
  local lvl repo protected control r_p r_c
  for lvl in A B NONE; do
    repo="$PROBE_ROOT/shim-$lvl"; mkdir -p "$repo"
    case "$lvl" in
      A) protected="$OP_A"; control="$OP_B"; _write_probe_state "$repo" "$OP_A" ;;
      B) protected="$OP_B"; control="$OP_A"; _write_probe_state "$repo" "$OP_B" ;;
      NONE) protected="$OP_A"; control="$OP_B" ;;
    esac
    r_p="$(_shim_eval "$repo" "$protected")"
    r_c="$(_shim_eval "$repo" "$control")"
    IFS='|' read -r sp_exit sp_reason sp_ref sp_nr sp_nf <<<"$r_p"
    IFS='|' read -r sc_exit sc_reason sc_ref sc_nr sc_nf <<<"$r_c"
    if [[ "$lvl" == "NONE" ]]; then
      [[ "$sp_reason" == "unresolved_protected_branch" ]] || SHIM_FAIL="${SHIM_FAIL}shim_unresolved_p($sp_reason);"
      [[ "$sc_reason" == "unresolved_protected_branch" ]] || SHIM_FAIL="${SHIM_FAIL}shim_unresolved_c($sc_reason);"
    else
      [[ "$sp_exit" != "0" && "$sp_reason" == "branch_protected" ]] || SHIM_FAIL="${SHIM_FAIL}shim_protected_not_blocked($lvl:$sp_reason);"
      [[ "$sp_ref" == "refs/heads/$protected" ]] || SHIM_FAIL="${SHIM_FAIL}shim_ref($lvl:$sp_ref);"
      [[ "$sc_reason" != "branch_protected" ]] || SHIM_FAIL="${SHIM_FAIL}shim_control_branch_denied($lvl);"
    fi
    SHIM_CELLS_JSON="${SHIM_CELLS_JSON}${SHIM_CELLS_JSON:+,}$(LV="$lvl" PT="$protected" CT="$control" \
      PE="$sp_exit" PR="$sp_reason" PF="$sp_ref" CE="$sc_exit" CR="$sc_reason" \
      jq -n '{d1:env.LV,protected:env.PT,control:env.CT,
              protected_outcome:{exit:(env.PE|tonumber),reason:env.PR,ref:env.PF},
              control_outcome:{exit:(env.CE|tonumber),reason:env.CR}}' | jq -c .)"
  done
}

# M5-OPERANDS / AC-14 — operand-form coverage in the shim, evaluated through the
# production branch-protection decision seam with unrelated predicates held
# permissive. Controls must produce NO BRANCH-PROTECTION denial (not "exit 0":
# the shim legitimately blocks some operations on path grounds regardless of
# branch name), plus one otherwise-permitted control op exiting 0 to rule out
# blanket blocking.
OPERAND_FORMS_JSON=""
OPERAND_FAIL=""
_run_operand_form_probe() {
  [[ -n "$PROBE_ROOT" && -x "$SHIM_SRC" ]] || { OPERAND_FAIL="shim_source_missing"; return; }
  local repo="$PROBE_ROOT/operands"; mkdir -p "$repo"
  _write_probe_state "$repo" "$OP_A"
  local form rc out reason entries="" ctrl_zero=0
  for form in "$OP_A" "refs/heads/$OP_A" "heads/$OP_A" "$OP_A@{0}" \
              "$OP_A:$OP_A" "+$OP_A:refs/heads/$OP_A" "refs/heads/$OP_A:refs/heads/$OP_A"; do
    out="$(cd "$repo" && CLAUDE_OVERNIGHT_ACTOR=1 CLAUDE_OVERNIGHT_MAIN_ROOT="$PROBE_ROOT/shim-main" \
            CLAUDE_OVERNIGHT_REAL_GIT="$PROBE_ROOT/stub-git" bash "$SHIM_SRC" update-ref "$form" HEAD 2>&1)"; rc=$?
    IFS='|' read -r reason _ _ _ <<<"$(_parse_deny_line "$out")"
    [[ "$reason" == "branch_protected" ]] || OPERAND_FAIL="${OPERAND_FAIL}form_not_blocked($form:$reason);"
    entries="${entries}${entries:+,}$(F="$form" R="$reason" jq -n '{form:env.F,reason:env.R,blocked:(env.R=="branch_protected")}' | jq -c .)"
  done
  for form in "$OP_B" "refs/heads/$OP_B" "heads/$OP_B" "$OP_B@{0}" "$OP_B:$OP_B"; do
    out="$(cd "$repo" && CLAUDE_OVERNIGHT_ACTOR=1 CLAUDE_OVERNIGHT_MAIN_ROOT="$PROBE_ROOT/shim-main" \
            CLAUDE_OVERNIGHT_REAL_GIT="$PROBE_ROOT/stub-git" bash "$SHIM_SRC" update-ref "$form" HEAD 2>&1)"; rc=$?
    IFS='|' read -r reason _ _ _ <<<"$(_parse_deny_line "$out")"
    [[ "$reason" != "branch_protected" ]] || OPERAND_FAIL="${OPERAND_FAIL}control_form_branch_denied($form);"
    [[ "$rc" == "0" ]] && ctrl_zero=1
    entries="${entries}${entries:+,}$(F="$form" R="$reason" jq -n '{control_form:env.F,reason:env.R,branch_protection_denial:(env.R=="branch_protected")}' | jq -c .)"
  done
  [[ "$ctrl_zero" == "1" ]] || OPERAND_FAIL="${OPERAND_FAIL}no_control_exited_0;"
  OPERAND_FORMS_JSON="$entries"
}

# M8c / AC-2 — dedicated DIAGNOSTIC probe. Its reference-transaction is a
# TRANSPARENT CAPTURE WRAPPER: it appends the phase and every stdin line
# verbatim (ref names included) to a log, feeds the identical lines to the real
# keystone, and exits with the keystone's exit code. Confined to this probe —
# the M8a and M8b probes run the UNWRAPPED keystone, so what they attest is
# unambiguous. The commit is made WITHOUT the actor marker, because the marker
# governs whether the keystone DENIES, not what git EMITS, and an aborted
# transaction would not show the complete prepared-phase line set.
# Diagnostic only: nothing here changes any allow/deny decision.
HEADLINE_CAPTURE=""
HEADLINE_HAS_HEAD="unknown"
_run_headline_capture_probe() {
  [[ -n "$PROBE_ROOT" && -x "$KEYSTONE_SRC" ]] || return
  local repo="$PROBE_ROOT/capture" log="$PROBE_ROOT/capture.log"
  mkdir -p "$repo/hooks"
  cp "$KEYSTONE_SRC" "$repo/hooks/real-reference-transaction"
  chmod +x "$repo/hooks/real-reference-transaction"
  cat > "$repo/hooks/reference-transaction" <<CAPWRAP
#!/usr/bin/env bash
# Transparent capture wrapper (M8c). Behaviour-neutral by construction: it
# forwards the IDENTICAL stdin to the real keystone and exits with its code.
LOG="$log"
IN="\$(cat)"
printf 'PHASE=%s\n' "\${1:-}" >> "\$LOG"
printf '%s\n' "\$IN" >> "\$LOG"
printf '%s\n' "\$IN" | "$repo/hooks/real-reference-transaction" "\$@"
exit \$?
CAPWRAP
  chmod +x "$repo/hooks/reference-transaction"
  (
    cd "$repo" || exit 0
    "$GIT_BIN" init -q -b probe-idle . 2>/dev/null || "$GIT_BIN" init -q . 2>/dev/null
    "$GIT_BIN" config user.email t@t >/dev/null 2>&1
    "$GIT_BIN" config user.name t >/dev/null 2>&1
    "$GIT_BIN" config core.hooksPath "$repo/hooks" >/dev/null 2>&1
    echo x > f; "$GIT_BIN" add f >/dev/null 2>&1
    CLAUDE_OVERNIGHT_ACTOR="" "$GIT_BIN" commit -qm diag >/dev/null 2>&1
  )
  if [[ -f "$log" ]]; then
    HEADLINE_CAPTURE="$(cat "$log")"
    if awk '/^PHASE=prepared$/{p=1;next} /^PHASE=/{p=0} p&&/(^| )HEAD$/{found=1} END{exit !found}' "$log"; then
      HEADLINE_HAS_HEAD="true"
    else
      HEADLINE_HAS_HEAD="false"
    fi
  fi
}

# Functional throwaway-repo keystone-abort test of a HEAD branch-switch (M8a).
# This probe exercises the HEAD ARM ONLY. On git >=2.46 its decisive operation
# is a HEAD symref switch that the keystone aborts at an arm containing NO
# branch name at all, so it carries NO information about the branch-ref arm.
# The branch-ref arm is measured separately by _run_branch_ref_arm_probe.
# The probe repository is built on the branch passed in — never on a literal.
# Returns: "structural_head_switch" | "branch_ref_denied_symref_switch_not_denied"
#        | "hook_not_firing".
_functional_probe() {
  local probe_branch="$1" tmp rc
  [[ -n "$probe_branch" ]] || { echo "hook_not_firing"; return; }
  [[ -x "$KEYSTONE_SRC" ]] || { echo "hook_not_firing"; return; }
  [[ -n "$PROBE_ROOT" ]] || { echo "hook_not_firing"; return; }
  tmp="$PROBE_ROOT/headarm"; mkdir -p "$tmp"
  (
    cd "$tmp" || exit 0
    "$GIT_BIN" init -q . 2>/dev/null
    "$GIT_BIN" config user.email t@t >/dev/null 2>&1
    "$GIT_BIN" config user.name t >/dev/null 2>&1
    mkdir -p hooks
    cp "$KEYSTONE_SRC" hooks/reference-transaction
    chmod +x hooks/reference-transaction
    "$GIT_BIN" config core.hooksPath "$tmp/hooks" >/dev/null 2>&1
    # The probe repo is built on the TARGET's resolved protected branch (AC-13);
    # no branch-name literal appears on this construction path.
    "$GIT_BIN" symbolic-ref HEAD "refs/heads/$probe_branch" >/dev/null 2>&1
    # The keystone resolves its protected set from a live record, so the probe
    # supplies one declaring exactly the branch under test.
    mkdir -p .claude
    printf '{\n  "schema_version": 9,\n  "session_id": "headarm",\n  "isolation_released_at": null,\n  "protected_branch": "%s"\n}\n' \
      "$probe_branch" > ".claude/overnight-state-headarm.json"
    echo x > f; "$GIT_BIN" add f >/dev/null 2>&1
    # First commit must succeed with NO overnight marker (it creates the ref).
    CLAUDE_OVERNIGHT_ACTOR="" "$GIT_BIN" commit -qm init >/dev/null 2>&1
    "$GIT_BIN" branch other >/dev/null 2>&1
    # As an overnight actor (no token), attempt a HEAD branch-switch.
    if CLAUDE_OVERNIGHT_ACTOR=1 "$GIT_BIN" checkout other >/dev/null 2>&1; then
      # The switch SUCCEEDED -> the keystone did not abort the symref move.
      "$GIT_BIN" checkout "$probe_branch" >/dev/null 2>&1
      if CLAUDE_OVERNIGHT_ACTOR=1 "$GIT_BIN" commit -q --allow-empty -m x >/dev/null 2>&1; then
        exit 11  # keystone never fired at all
      else
        # The branch-ref arm denied the commit AND the HEAD arm was simultaneously
        # live (it protects detach on this git); the old `branch_ref_only` label
        # attributed the denial SOLELY to the branch-ref arm, which is not what
        # was observed. The label now names the liveness of both arms.
        exit 12
      fi
    else
      exit 13  # branch-switch aborted -> structural
    fi
  )
  rc=$?
  case "$rc" in
    13) echo "structural_head_switch" ;;
    12) echo "branch_ref_denied_symref_switch_not_denied" ;;
    *)  echo "hook_not_firing" ;;
  esac
}

# ---------------------------------------------------------------------------
# AC-13 — the attestation target. A DISTINCT scratch repository, because the
# repository under analysis has its own default-branch name and cannot
# simultaneously have a runtime-random one. Its default branch is discoverable
# ONLY from local refs; HEAD is parked elsewhere; no local ref carries either of
# the two names the reported defect is about, so a literal fallback is
# observable rather than coincidentally correct; and origin's URL does not
# exist, so a network tier would fail rather than silently succeed.
# ---------------------------------------------------------------------------
ATTEST_TARGET=""
ATTEST_N=""
ATTEST_RESOLVED=""
_build_attest_target() {
  [[ -n "$PROBE_ROOT" ]] || return 1
  ATTEST_N="ovnlaunch-$(_rand_stem)"
  ATTEST_TARGET="$PROBE_ROOT/attest-target"
  mkdir -p "$ATTEST_TARGET"
  (
    cd "$ATTEST_TARGET" || exit 1
    "$GIT_BIN" init -q -b probe-idle . 2>/dev/null || "$GIT_BIN" init -q . 2>/dev/null
    "$GIT_BIN" symbolic-ref HEAD refs/heads/probe-idle >/dev/null 2>&1
    "$GIT_BIN" config user.email t@t >/dev/null 2>&1
    "$GIT_BIN" config user.name t >/dev/null 2>&1
    echo y > g; "$GIT_BIN" add g >/dev/null 2>&1
    CLAUDE_OVERNIGHT_ACTOR="" "$GIT_BIN" commit -qm base >/dev/null 2>&1
    CLAUDE_OVERNIGHT_ACTOR="" "$GIT_BIN" commit -q --allow-empty -m next >/dev/null 2>&1
    # the default branch is discoverable ONLY through the remote-tracking symref
    "$GIT_BIN" update-ref "refs/remotes/origin/$ATTEST_N" HEAD~1 >/dev/null 2>&1
    "$GIT_BIN" symbolic-ref refs/remotes/origin/HEAD "refs/remotes/origin/$ATTEST_N" >/dev/null 2>&1
    "$GIT_BIN" remote add origin "$PROBE_ROOT/no-such-origin-$STEM" >/dev/null 2>&1 || \
      "$GIT_BIN" config remote.origin.url "$PROBE_ROOT/no-such-origin-$STEM" >/dev/null 2>&1
    # a local branch carrying N so the behavioural enforcement check has a ref
    "$GIT_BIN" branch "$ATTEST_N" HEAD~1 >/dev/null 2>&1
    "$GIT_BIN" branch "control-$STEM" HEAD~1 >/dev/null 2>&1
  )
  # ANTI-CIRCULARITY: the expected value is RE-DERIVED by the PRODUCTION
  # resolver from the target's OWN origin/HEAD. It is never taken from the
  # governing session record and never passed in as an expected-value argument,
  # so the same variable cannot both configure enforcement and check it.
  if [[ -x "$LAUNCHER_SRC" ]]; then
    ATTEST_RESOLVED="$(bash "$LAUNCHER_SRC" --emit-record-only --project-dir "$ATTEST_TARGET" \
                        --session-id "attest-$STEM" 2>/dev/null | jq -r '.protected_branch // ""' 2>/dev/null || echo '')"
  fi
  [[ -n "$ATTEST_RESOLVED" ]]
}

# BEHAVIOURAL definition of "will enforce" (AC-13). String equality between
# record fields — or between a record field and a value the selftest computed —
# is explicitly NOT sufficient: an implementation could read protected_branch
# twice, label one copy "enforced", compare it with itself and pass while the
# installed keystone still protected something else. So the EXACT INSTALLED
# keystone is exercised through the SAME reference-write path git itself uses.
# Returns 0 iff refs/heads/<N> is denied with reason=branch_protected AND a
# distinct non-HEAD control ref is NOT denied for branch protection.
_enforces_branch() {
  local repo="$1" want="$2" ctrl="control-$STEM"
  local rp rc_ p_reason c_reason p_exit c_exit
  rp="$(_move_branch "$repo" "$want" root)"
  rc_="$(_move_branch "$repo" "$ctrl" root)"
  IFS='|' read -r p_exit p_reason _ _ _ _ _ <<<"$rp"
  IFS='|' read -r c_exit c_reason _ _ _ _ _ <<<"$rc_"
  [[ "$p_exit" != "0" && "$p_reason" == "branch_protected" ]] || return 1
  [[ "$c_reason" != "branch_protected" ]] || return 1
  return 0
}

# Install the exact source keystone into the attestation target so the
# behavioural check exercises the same bytes _attest_target hashes.
_install_keystone_into() {
  local repo="$1"
  mkdir -p "$repo/hooks"
  cp "$KEYSTONE_SRC" "$repo/hooks/reference-transaction"
  chmod +x "$repo/hooks/reference-transaction"
  "$GIT_BIN" -C "$repo" config core.hooksPath "$repo/hooks" >/dev/null 2>&1
}

ATTEST_CASES_JSON=""
ATTEST_FAIL=""
_run_attestation_cases() {
  [[ -n "$ATTEST_TARGET" && -n "$ATTEST_RESOLVED" ]] || { ATTEST_FAIL="attest_target_unbuildable"; return; }
  _install_keystone_into "$ATTEST_TARGET"
  local pos neg unres

  # POSITIVE — the record declares exactly the resolved value. Attestation is
  # PERMITTED to pass, so the criterion is not satisfiable by a blanket
  # downgrade that would make every session best-effort forever.
  _write_probe_state "$ATTEST_TARGET" "$ATTEST_RESOLVED"
  _enforces_branch "$ATTEST_TARGET" "$ATTEST_RESOLVED" && pos=pass || pos=fail
  [[ "$pos" == "pass" ]] || ATTEST_FAIL="${ATTEST_FAIL}positive_case_failed;"

  # NEGATIVE — a DELIBERATELY MISMATCHING ENFORCEMENT FIXTURE. The mismatch is
  # introduced in the governing STATE RECORD, never in the keystone file: the
  # hash check runs first and returns before any branch assertion, so a
  # keystone-mutating fixture would pass on the hash rather than on the branch —
  # the exact "passes for the wrong reason" class this case exists to close.
  _write_probe_state "$ATTEST_TARGET" "ovnmismatch-$(_rand_stem)"
  _enforces_branch "$ATTEST_TARGET" "$ATTEST_RESOLVED" && neg=pass || neg=fail
  [[ "$neg" == "fail" ]] || ATTEST_FAIL="${ATTEST_FAIL}negative_case_passed;"

  # UNRESOLVABLE — no record at all.
  mv "$ATTEST_TARGET/.claude/overnight-state-probe-${STEM}.json" \
     "$ATTEST_TARGET/state-record-parked.json" 2>/dev/null || true
  _enforces_branch "$ATTEST_TARGET" "$ATTEST_RESOLVED" && unres=pass || unres=fail
  [[ "$unres" == "fail" ]] || ATTEST_FAIL="${ATTEST_FAIL}unresolvable_case_passed;"

  # restore the positive fixture for the live attestation below
  _write_probe_state "$ATTEST_TARGET" "$ATTEST_RESOLVED"

  ATTEST_CASES_JSON="$(P="$pos" N="$neg" U="$unres" RN="$ATTEST_RESOLVED" \
    jq -n '{resolved_from_target_origin_head:env.RN,
            positive_case_enforced:(env.P=="pass"),
            negative_case_enforced:(env.N=="pass"),
            unresolvable_case_enforced:(env.U=="pass"),
            definition:"behavioural: the exact installed keystone must deny refs/heads/<N> with reason=branch_protected through git own reference-write path, and must not deny a distinct control ref for branch protection. String equality between record fields is NOT sufficient."}' | jq -c .)"
}

_build_attest_target || true
_run_headline_capture_probe
_run_branch_ref_arm_probe
_run_shim_probe
_run_operand_form_probe
_run_attestation_cases

BRANCH_REF_ARM_OK=false; [[ -z "$KS_FAIL" ]] && BRANCH_REF_ARM_OK=true
SHIM_ARM_OK=false;       [[ -z "$SHIM_FAIL" ]] && SHIM_ARM_OK=true
OPERAND_FORMS_OK=false;  [[ -z "$OPERAND_FAIL" ]] && OPERAND_FORMS_OK=true
ATTEST_EQUALITY_OK=false; [[ -z "$ATTEST_FAIL" ]] && ATTEST_EQUALITY_OK=true

SELFTEST_RESULT="$(_functional_probe "${ATTEST_RESOLVED:-probe-idle}")"

# Target-repo attestation (non-mutating): core.hooksPath points at a keystone
# dir whose reference-transaction matches, and the blessed token is absent.
_attest_target() {
  local hp expected_keystone hooks_hash src_hash
  hp="$(git -C "$PROJECT_DIR" config --local --get core.hooksPath 2>/dev/null || echo '')"
  [[ -n "$hp" ]] || return 1
  [[ -x "$hp/reference-transaction" ]] || return 1
  expected_keystone="${KEYSTONE_DIR:-$(cd "$(dirname "$0")/.." && pwd)/hooks/git-keystone}/reference-transaction"
  [[ -f "$expected_keystone" ]] || return 1
  hooks_hash="$(sha256sum "$hp/reference-transaction" 2>/dev/null | awk '{print $1}')"
  src_hash="$(sha256sum "$expected_keystone" 2>/dev/null | awk '{print $1}')"
  [[ "$hooks_hash" == "$src_hash" ]] || return 1
  [[ -z "${CLAUDE_GIT_BLESSED_TOKEN:-}" ]] || return 1
  # M8 / AC-13 — the value the keystone WILL ENFORCE must equal the target
  # repository's resolved protected branch. "Will enforce" is defined
  # BEHAVIOURALLY (see _enforces_branch): the exact installed keystone denies
  # refs/heads/<N> through git's own reference-write path and does not deny a
  # control ref. This assertion is placed AFTER the hash check on purpose — the
  # negative fixture mismatches the governing STATE RECORD, not the keystone
  # file, so the hash check passes and the branch assertion is what decides.
  [[ "$ATTEST_EQUALITY_OK" == "true" ]] || return 1
  return 0
}

STRUCTURAL_ALLOWED=false
GUARANTEE_LEVEL="best_effort_head_switch"
if _ge_246 "$GIT_VERSION" \
   && { [[ -z "$SLOT" ]] || [[ "$GIT_EXEC_PATH" == "$SLOT"* ]] || [[ ! -x "$SLOT/bin/git" ]]; } \
   && [[ "$SELFTEST_RESULT" == "structural_head_switch" ]] \
   && _attest_target; then
  # Require exec-path inside the slot when a modern slot is actually in use.
  if [[ -x "$SLOT/bin/git" && "$GIT_EXEC_PATH" != "$SLOT"* ]]; then
    STRUCTURAL_ALLOWED=false
  else
    STRUCTURAL_ALLOWED=true
    GUARANTEE_LEVEL="structural_head_switch"
  fi
fi

JSON="$(GIT_VERSION="$GIT_VERSION" GIT_EFFECTIVE_PATH="$GIT_EFFECTIVE_PATH" \
  GIT_EXEC_PATH="$GIT_EXEC_PATH" SELFTEST_RESULT="$SELFTEST_RESULT" \
  GUARANTEE_LEVEL="$GUARANTEE_LEVEL" STRUCTURAL_ALLOWED="$STRUCTURAL_ALLOWED" \
  STEM="$STEM" OP_A="$OP_A" OP_B="$OP_B" \
  KS_OK="$BRANCH_REF_ARM_OK" KS_FAIL="$KS_FAIL" \
  SHIM_OK="$SHIM_ARM_OK" SHIM_FAIL="$SHIM_FAIL" \
  OPF_OK="$OPERAND_FORMS_OK" OPF_FAIL="$OPERAND_FAIL" \
  ATT_OK="$ATTEST_EQUALITY_OK" ATT_FAIL="$ATTEST_FAIL" ATT_N="${ATTEST_RESOLVED:-}" \
  HDR_HAS_HEAD="$HEADLINE_HAS_HEAD" HDR_CAP="$HEADLINE_CAPTURE" \
  CELLS="[${CELLS_JSON}]" SHIM_CELLS="[${SHIM_CELLS_JSON}]" OPF="[${OPERAND_FORMS_JSON}]" \
  ATT_CASES="${ATTEST_CASES_JSON:-null}" \
  jq -n '{
    git_version: env.GIT_VERSION,
    git_effective_path: env.GIT_EFFECTIVE_PATH,
    git_exec_path: env.GIT_EXEC_PATH,
    reference_transaction_selftest_result: env.SELFTEST_RESULT,
    guarantee_level: env.GUARANTEE_LEVEL,
    structural_claim_allowed: (env.STRUCTURAL_ALLOWED == "true"),

    head_arm_probe: {
      result: env.SELFTEST_RESULT,
      arm_tested: "HEAD symref branch-switch — reference-transaction HEAD arm",
      covers_branch_ref_arm: false,
      note: "This probe carries NO information about the branch-ref arm. On git >= 2.46 its decisive operation is a HEAD symref switch denied by an arm that contains no branch name at all. Its result must never be cited as evidence that the protected branch is enforced by name; see branch_ref_arm_probe. It also does not cover the branch the probe repository is built on — that is attestation_probe1s job."
    },

    branch_ref_arm_probe: {
      ok: (env.KS_OK == "true"),
      failures: env.KS_FAIL,
      stem: env.STEM,
      operand_a: env.OP_A,
      operand_b: env.OP_B,
      design: "crossed counterfactual D1 x D2 x D3 on ONE runtime-random operand pair, plus an additional D1-unresolved level, plus three fixed regression anchors whose role is anchoring and not falsification",
      cells: (env.CELLS | fromjson)
    },

    policy_shim_probe: {
      ok: (env.SHIM_OK == "true"),
      failures: env.SHIM_FAIL,
      note: "the shim is exercised as a SEPARATE consumer with the keystone out of its path, so a corrected keystone cannot mask a still-literal shim",
      cells: (env.SHIM_CELLS | fromjson)
    },

    operand_forms_probe: {
      ok: (env.OPF_OK == "true"),
      failures: env.OPF_FAIL,
      forms: (env.OPF | fromjson)
    },

    attestation_probe: {
      ok: (env.ATT_OK == "true"),
      failures: env.ATT_FAIL,
      target_resolved_branch: env.ATT_N,
      cases: (if env.ATT_CASES == "null" then null else (env.ATT_CASES | fromjson) end)
    },

    head_line_capture: {
      head_present_in_prepared_phase: env.HDR_HAS_HEAD,
      captured_lines: env.HDR_CAP,
      note: "diagnostic only (M8c): a transparent capture wrapper confined to one dedicated probe, feeding identical stdin to the real keystone and exiting with its code. The M8a and M8b probes run the UNWRAPPED keystone. Nothing here changes any allow/deny decision."
    },

    guarantee_scope: "correct enforcement against drift and misconfiguration, plus honest attestation. The shared common-dir remains read-write, so this is NOT a claim about a malicious actor."
  }')"

echo "$JSON"
echo "SELFTEST_JSON=$(printf '%s' "$JSON" | jq -c .)"
exit 0
