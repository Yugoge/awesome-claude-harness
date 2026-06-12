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

# Functional throwaway-repo keystone-abort test of a HEAD branch-switch.
# Returns: "structural_head_switch" | "branch_ref_only" | "hook_not_firing".
_functional_probe() {
  local tmp keystone_src rc selftest
  keystone_src="${KEYSTONE_DIR:-$(cd "$(dirname "$0")/.." && pwd)/hooks/git-keystone}/reference-transaction"
  [[ -x "$keystone_src" ]] || { echo "hook_not_firing"; return; }
  tmp="$(mktemp -d 2>/dev/null)" || { echo "hook_not_firing"; return; }
  trap 'rm -rf "$tmp" 2>/dev/null' RETURN
  (
    cd "$tmp" || exit 0
    "$GIT_BIN" init -q . 2>/dev/null
    "$GIT_BIN" config user.email t@t >/dev/null 2>&1
    "$GIT_BIN" config user.name t >/dev/null 2>&1
    mkdir -p hooks
    cp "$keystone_src" hooks/reference-transaction
    chmod +x hooks/reference-transaction
    "$GIT_BIN" config core.hooksPath "$tmp/hooks" >/dev/null 2>&1
    # Default branch is master here for the test.
    "$GIT_BIN" symbolic-ref HEAD refs/heads/master >/dev/null 2>&1
    echo x > f; "$GIT_BIN" add f >/dev/null 2>&1
    # First commit must succeed with NO overnight marker (commit creates master ref).
    CLAUDE_OVERNIGHT_ACTOR="" "$GIT_BIN" commit -qm init >/dev/null 2>&1
    "$GIT_BIN" branch other >/dev/null 2>&1
    # As an overnight actor (no token), attempt a HEAD branch-switch.
    if CLAUDE_OVERNIGHT_ACTOR=1 "$GIT_BIN" checkout other >/dev/null 2>&1; then
      # The switch SUCCEEDED -> keystone did not abort the symref move.
      # Distinguish branch_ref_only (master ref protected) vs hook_not_firing.
      "$GIT_BIN" checkout master >/dev/null 2>&1
      if CLAUDE_OVERNIGHT_ACTOR=1 "$GIT_BIN" commit -q --allow-empty -m x >/dev/null 2>&1; then
        exit 11  # keystone never fired at all
      else
        exit 12  # master-ref protected, symref switch not -> branch_ref_only
      fi
    else
      exit 13  # branch-switch aborted -> structural
    fi
  )
  rc=$?
  case "$rc" in
    13) echo "structural_head_switch" ;;
    12) echo "branch_ref_only" ;;
    *)  echo "hook_not_firing" ;;
  esac
}

SELFTEST_RESULT="$(_functional_probe)"

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
  jq -n '{
    git_version: env.GIT_VERSION,
    git_effective_path: env.GIT_EFFECTIVE_PATH,
    git_exec_path: env.GIT_EXEC_PATH,
    reference_transaction_selftest_result: env.SELFTEST_RESULT,
    guarantee_level: env.GUARANTEE_LEVEL,
    structural_claim_allowed: (env.STRUCTURAL_ALLOWED == "true")
  }')"

echo "$JSON"
echo "SELFTEST_JSON=$(printf '%s' "$JSON" | jq -c .)"
exit 0
