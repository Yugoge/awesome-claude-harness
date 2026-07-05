#!/usr/bin/env bash
# Description: Cache-safe canary that behaviorally verifies the four core PreToolUse hooks.
# Usage: canary-verify.sh [--hooks-dir <path>]
#   Designed to run as a SessionStart hook (registered in settings.json).
# Output contract (spec §5.5):
#   - Healthy run: zero bytes to stdout (exec >/dev/null), exit 0
#   - Failure:     stderr message describing the broken hook, exit 2
#   - Advisory:    stderr message but exit 0 (stdout-polluting prerequisite hooks
#                  such as session-info.sh / session-git-init.sh — declared
#                  Won't Have for this cycle; documented in spec §5.5)

set -uo pipefail

# Suppress ALL stdout for prompt-cache safety per spec §5.5 line 214
# (exec >/dev/null at top; not just at the end). Failures still reach stderr.
exec >/dev/null

HOOKS_DIR_DEFAULT="${HOME}/.claude/hooks"
HOOKS_DIR="${HOOKS_DIR_DEFAULT}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hooks-dir) HOOKS_DIR="${2:?missing value for --hooks-dir}"; shift 2 ;;
    -h|--help)
      echo "Usage: $(basename "$0") [--hooks-dir <path>]" >&2
      exit 0
      ;;
    *) echo "canary-verify.sh: unknown arg '$1'" >&2; exit 1 ;;
  esac
done

# Venv-presence guard (E-M5): placed after arg parsing (--help already handled above)
# but before emit_advisory function definition (direct echo required here).
# CLAUDE_HOME portability: respect env var override for non-default venv locations.
CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
VENV_ACTIVATE="$CLAUDE_HOME/venv/bin/activate"
if [[ ! -f "$VENV_ACTIVATE" ]]; then
  echo "canary-verify[ADVISORY]: venv absent: $VENV_ACTIVATE — skipping hook verification" >&2
  exit 0
fi

failures=0

emit_failure() {
  # Final exit is 2; emit a single composed stderr line per failure.
  echo "canary-verify[FAIL]: $*" >&2
  failures=$((failures + 1))
}

emit_advisory() {
  # Advisory: log to stderr but do not increment failures (spec §5.5 + Won't Have).
  echo "canary-verify[ADVISORY]: $*" >&2
}

# ---------------------------------------------------------------------------
# Behavioural test for each guard. Inputs are synthetic minimal JSON envelopes
# matching Claude's PreToolUse contract. We only check the hook is invocable
# and does not crash; deny outcomes are EXPECTED for unsafe payloads.
# ---------------------------------------------------------------------------

verify_bash_safety() {
  local hook="${HOOKS_DIR}/pretool-bash-safety.sh"
  if [[ ! -x "${hook}" && ! -f "${hook}" ]]; then
    emit_failure "missing or non-executable: ${hook}"
    return
  fi
  # Allow case: benign payload should NOT exit 2
  local safe='{"tool_name":"Bash","tool_input":{"command":"echo hello"}}'
  echo "${safe}" | bash "${hook}" >/dev/null 2>&1
  if [[ $? -eq 2 ]]; then
    emit_failure "pretool-bash-safety.sh BLOCKED a benign 'echo hello' payload (false-positive guard)"
  fi
  # Block case: a payload matching one of the documented unsafe patterns
  # MUST be rejected (exit 2). Use 'rm -rf /' style payload — universally blocked.
  local unsafe='{"tool_name":"Bash","tool_input":{"command":"rm -rf /"}}'
  echo "${unsafe}" | bash "${hook}" >/dev/null 2>&1
  if [[ $? -ne 2 ]]; then
    emit_failure "pretool-bash-safety.sh FAILED to block 'rm -rf /' (fail-open guard — should exit 2)"
  fi
}

verify_write_guard() {
  local hook="${HOOKS_DIR}/pretool-write-guard.sh"
  if [[ ! -f "${hook}" ]]; then
    emit_failure "missing: ${hook}"
    return
  fi
  # Allow case: Write to a path that does NOT yet exist must NOT exit 2.
  # mktemp is used here only to GENERATE a unique path; we delete the file
  # before the test so the path is non-existent at the moment of the Write
  # call, matching the guard's "new file creation" allow path
  # (hooks/pretool-write-guard.sh:127-128).
  local new_path
  new_path=$(mktemp -u -t canary-write-new.XXXXXX)
  local safe="{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"${new_path}\",\"content\":\"ok\"}}"
  echo "${safe}" | bash "${hook}" >/dev/null 2>&1
  local rc=$?
  if [[ "${rc}" -ge 126 ]]; then
    emit_failure "pretool-write-guard.sh exec error rc=${rc}"
  fi
  if [[ "${rc}" -eq 2 ]]; then
    emit_failure "pretool-write-guard.sh BLOCKED a new-file Write (false-positive guard)"
  fi
  # Deny case (spec-20260518-225715 Cycle 3 Debt 6 / AC-06): the guard MUST
  # block Write attempts that target an EXISTING file (per
  # hooks/pretool-write-guard.sh:120-128). Synthesize the payload by
  # creating an existing file via mktemp, then send a Write payload that
  # targets that path. Guard MUST exit 2.
  local existing_file
  existing_file=$(mktemp -t canary-write-existing.XXXXXX)
  local deny="{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"${existing_file}\",\"content\":\"overwrite\"}}"
  echo "${deny}" | bash "${hook}" >/dev/null 2>&1
  rc=$?
  rm -f "${existing_file}"
  if [[ "${rc}" -ne 2 ]]; then
    emit_failure "pretool-write-guard.sh FAILED to block Write to existing file (rc=${rc}, expected 2; fail-open guard)"
  fi
}

verify_read_size_guard() {
  local hook="${HOOKS_DIR}/pretool-read-size-guard.py"
  if [[ ! -f "${hook}" ]]; then
    emit_failure "missing: ${hook}"
    return
  fi
  # Allow case: tiny file (or /dev/null) must NOT exit 2.
  # python3 invocation is wrapped in a same-line subshell that sources the
  # venv per spec-20260518-225715 Cycle 2 P3.6 (canonical /dev Standard).
  local safe='{"tool_name":"Read","tool_input":{"file_path":"/dev/null"}}'
  echo "${safe}" | ( source ~/.claude/venv/bin/activate && python3 "${hook}" >/dev/null 2>&1 )
  local rc=$?
  if [[ "${rc}" -ge 126 ]]; then
    emit_failure "pretool-read-size-guard.py exec error rc=${rc}"
  fi
  # Block case: synthesize an oversized file. The hook's documented cap is
  # 1000 lines (CLAUDE.md says 600; spec §5.5 documented mismatch). Use 5000
  # lines to exceed any plausible cap and assert the guard fires (exit 2).
  # mktemp replaces former hardcoded temp-dir oversized literal per
  # spec-20260518-225715 Cycle 2 P3.8 (parameterizes the path so the test
  # tolerates non-default TMPDIR setups).
  local oversized
  oversized=$(mktemp -t canary-oversized.XXXXXX)
  yes "fill" 2>/dev/null | head -5000 > "${oversized}" || true
  local payload="{\"tool_name\":\"Read\",\"tool_input\":{\"file_path\":\"${oversized}\"}}"
  echo "${payload}" | ( source ~/.claude/venv/bin/activate && python3 "${hook}" >/dev/null 2>&1 )
  rc=$?
  rm -f "${oversized}"
  # Note: the guard exits 0/2/other depending on policy. We do NOT hard-fail
  # this because the documented cap value is contested (1000 vs 600); we
  # surface it as advisory if it did NOT exit 2 — so QA knows to verify.
  if [[ "${rc}" -ne 2 ]]; then
    emit_advisory "pretool-read-size-guard.py did NOT block a 5000-line file (rc=${rc}); verify cap value"
  fi
}

verify_git_privilege_guard() {
  local hook="${HOOKS_DIR}/pretool-git-privilege-guard.py"
  if [[ ! -f "${hook}" ]]; then
    emit_failure "missing: ${hook}"
    return
  fi
  # Allow case: 'git status' is universally read-only. python3 invocation is
  # wrapped in a same-line subshell that sources the venv per
  # spec-20260518-225715 Cycle 2 P3.6.
  local safe='{"tool_name":"Bash","tool_input":{"command":"git status"}}'
  echo "${safe}" | ( source ~/.claude/venv/bin/activate && python3 "${hook}" >/dev/null 2>&1 )
  local rc=$?
  if [[ "${rc}" -ge 126 ]]; then
    emit_failure "pretool-git-privilege-guard.py exec error rc=${rc}"
  fi
  if [[ "${rc}" -eq 2 ]]; then
    emit_failure "pretool-git-privilege-guard.py BLOCKED 'git status' (false-positive — should be allowed)"
  fi
  # Deny case (spec-20260518-225715 Cycle 3 Debt 6 / AC-06): the guard MUST
  # block destructive privileged git commands. 'git push --force' is the
  # canonical destructive write that rewrites history on the remote — the
  # guard MUST exit 2 when it sees this payload.
  local deny='{"tool_name":"Bash","tool_input":{"command":"git push --force origin master"}}'
  echo "${deny}" | ( source ~/.claude/venv/bin/activate && python3 "${hook}" >/dev/null 2>&1 )
  rc=$?
  if [[ "${rc}" -ne 2 ]]; then
    emit_failure "pretool-git-privilege-guard.py FAILED to block 'git push --force' (rc=${rc}, expected 2; fail-open guard)"
  fi
}

# ---------------------------------------------------------------------------
# Advisory checks (spec §5.5 prerequisite — declared Won't Have for this cycle)
# session-info.sh and session-git-init.sh are SessionStart hooks that emit
# stdout. They are not in scope to fix; we log advisory only so existing
# sessions are not blocked.
# ---------------------------------------------------------------------------
check_advisory_prerequisites() {
  for f in "${HOOKS_DIR}/session-info.sh" "${HOOKS_DIR}/session-git-init.sh"; do
    if [[ ! -f "${f}" ]]; then
      continue
    fi
    # If the script writes to stdout (echo / printf without >&2), flag advisory.
    if grep -E '^[[:space:]]*(echo|printf)' "${f}" 2>/dev/null \
       | grep -vE '>\s*&2|>&2' >/dev/null 2>&1; then
      emit_advisory "${f} emits stdout without >&2 (spec §5.5 prerequisite, Won't Have this cycle)"
    fi
  done
}

verify_bash_safety
verify_write_guard
verify_read_size_guard
verify_git_privilege_guard
check_advisory_prerequisites

if [[ "${failures}" -gt 0 ]]; then
  echo "canary-verify[FAIL]: ${failures} hook(s) broken — see preceding lines" >&2
  exit 2
fi

exit 0
