#!/bin/bash
# PreToolUse safety hook for Bash: the rules live in lib/bash_safety_rules.py, run in one interpreter per call.
# This entry keeps the harness switch, the fail-closed interpreter check, and the pre-clean snapshot taken before a
# /do or /allow release lets a destructive `git clean` through.
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib/harness_switch.sh" 2>/dev/null && harness_switch_exit_if_off  # no harness hook runs while /harness off holds

INPUT=$(cat)

# A Claude Code process started before its settings carried the overlay lacks CLAUDE_HOME; the guard keys it lacks
# come from the harness home's current settings.json.
[ -n "${CLAUDE_HOME:-}" ] || [ -z "${CLAUDECODE:-}${CLAUDE_PROJECT_DIR:-}" ] \
  || ! grep -qs '"CLAUDE_HOME"' "$(dirname "${BASH_SOURCE[0]}")/../settings.json" || eval "$(python3 \
  "$(dirname "${BASH_SOURCE[0]}")/lib/claude_home.py" env CLAUDE_DEV_CONTAINERS CLAUDE_DEV_SYSTEMD \
  CLAUDE_DAEMON_RESTART_GRANT_HELPER CLAUDE_PROTECTED_DAEMON_PREFIX CLAUDE_PROTECTED_DAEMON_TARGETS \
  CLAUDE_PROTECTED_PROCESS_FAMILY CLAUDE_HARD_BANNED_SCRIPTS 2>/dev/null)"
export CLAUDE_DEV_CONTAINERS CLAUDE_DEV_SYSTEMD CLAUDE_DAEMON_RESTART_GRANT_HELPER CLAUDE_PROTECTED_DAEMON_PREFIX \
  CLAUDE_PROTECTED_DAEMON_TARGETS CLAUDE_PROTECTED_PROCESS_FAMILY CLAUDE_HARD_BANNED_SCRIPTS
HOOKS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
CLAUDE_HOME="$(cd "$HOOKS_DIR/.." 2>/dev/null && pwd)"
PYTHON_BIN="${CLAUDE_PYTHON_BIN:-${CLAUDE_HOME}/venv/bin/python}"
[ -x "$PYTHON_BIN" ] || PYTHON_BIN="${CLAUDE_PYTHON_FALLBACK:-python3}"

VERDICT=$(printf '%s' "$INPUT" | "$PYTHON_BIN" "$HOOKS_DIR/lib/bash_safety_rules.py" "$HOOKS_DIR")
[ $? -eq 2 ] && [ -z "$VERDICT" ] && exit 2  # a rule refused; its message is on stderr

# A granted destructive `git clean` proceeds only after its untracked work is snapshotted; a target that is not
# provably this working directory, or a failed snapshot, is refused.
_preclean_snapshot_guard() {
  local _guard_py="$HOOKS_DIR/lib/git_clean_guard.py" _guard_reason _guard_rc _guard_timeout
  COMMAND=$(printf '%s' "$INPUT" | "$PYTHON_BIN" -c "import json,sys; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('command',''))" 2>/dev/null)
  if [ ! -r "$_guard_py" ]; then
    echo "BLOCKED: granted 'git clean' denied — pre-clean WIP snapshot guard is unavailable (fail-closed)" >&2
    echo "Command: $COMMAND" >&2
    echo "REASON: $_guard_py is missing or unreadable, so the clean target cannot be classified." >&2
    exit 2
  fi
  # Validated: an unchecked value sits in timeout's option position, where --help would exit 0 as "no clean".
  _guard_timeout="${CLAUDE_HOOK_CONTEXT_TIMEOUT:-5s}"
  case "$_guard_timeout" in
    *[!0-9.smhd]*|''|*[!0-9smhd]) _guard_timeout="5s" ;;
    [!0-9]*) _guard_timeout="5s" ;;
  esac
  _guard_reason=$(CMD_INPUT="$COMMAND" timeout -- "$_guard_timeout" "$PYTHON_BIN" "$_guard_py" 2>/dev/null)
  _guard_rc=$?
  case "$_guard_rc" in
    0)  return 0 ;;   # no destructive-or-uncertain `git clean`
    10) : ;;          # a destructive clean of this working directory: snapshot below
    *)                # 11 = redirected or indeterminate target; any other rc = detector failure
      echo "BLOCKED: granted 'git clean' denied — no protective pre-clean WIP snapshot is possible (fail-closed)" >&2
      echo "Command: $COMMAND" >&2
      echo "REASON: ${_guard_reason:-the pre-clean guard could not classify this command}" >&2
      echo "Hint: re-issue the clean from this working directory without -C/--git-dir/--work-tree" >&2
      echo "      and without a leading cd/subshell, or snapshot the work yourself first." >&2
      exit 2
      ;;
  esac
  local _ckpt_lib="$HOOKS_DIR/lib/checkpoint-core.sh"
  if [ ! -r "$_ckpt_lib" ]; then
    echo "BLOCKED: granted 'git clean' denied — the pre-clean WIP snapshot library is unavailable (fail-closed)" >&2
    echo "Command: $COMMAND" >&2
    echo "REASON: $_ckpt_lib is missing or unreadable, so untracked work cannot be made recoverable." >&2
    exit 2
  fi
  # shellcheck source=lib/checkpoint-core.sh
  . "$_ckpt_lib"
  # write_checkpoint redirects into its log directory before creating it.
  mkdir -p "$CHECKPOINT_LOG_DIR" 2>/dev/null || true
  write_checkpoint "" "pre-clean WIP snapshot before granted: $COMMAND"
  local _ckpt_rc=$?
  trap - EXIT INT TERM HUP  # write_checkpoint's early returns leave its temp-index trap installed
  if [ "$_ckpt_rc" -ne 0 ]; then
    echo "BLOCKED: granted 'git clean' denied — the protective pre-clean WIP snapshot FAILED (fail-closed)" >&2
    echo "Command: $COMMAND" >&2
    if [ "$_ckpt_rc" = "2" ]; then
      echo "REASON: write_checkpoint rc=2 — this working directory is not a git repository, so untracked work cannot be snapshotted." >&2
    else
      echo "REASON: write_checkpoint rc=$_ckpt_rc — the snapshot could not be written, so untracked work would be unrecoverable." >&2
    fi
    echo "Hint: see ${CHECKPOINT_LOG_FILE}, fix the snapshot failure, then re-issue the clean." >&2
    exit 2
  fi
  local _ckpt_branch _ckpt_ref
  _ckpt_branch=$(git branch --show-current 2>/dev/null)
  if [ -n "$_ckpt_branch" ]; then
    _ckpt_ref="refs/checkpoints/$(printf '%s' "$_ckpt_branch" | tr '/' '-')"
  else
    _ckpt_ref="refs/checkpoints/*"
  fi
  echo "[pre-clean-snapshot] untracked WIP snapshotted to $_ckpt_ref before granted clean; recover with 'git show $_ckpt_ref:<path>'" >&2
  return 0
}

case "$VERDICT" in
  ALLOW) exit 0 ;;
  CONSENT) _preclean_snapshot_guard; exit 0 ;;
  "SENTINEL "*)
    _preclean_snapshot_guard
    echo "[allow-sentinel] structured grant matched for task=${VERDICT#SENTINEL }. consume-on-any-terminal-result deferred to PostToolUse." >&2
    printf '%s\n' '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow", "permissionDecisionReason": "/allow sentinel grant consumed (structured allowed_operations[] match)"}}'
    exit 0 ;;
esac
echo "BLOCKED: safety-hook FAIL-CLOSED — the Python interpreter this hook depends on ($PYTHON_BIN) is unavailable or lib/bash_safety_rules.py gave no verdict, so no safety rule could be evaluated." >&2
echo "REASON: repair the interpreter deployment; a call no rule could read is never allowed." >&2
exit 2
