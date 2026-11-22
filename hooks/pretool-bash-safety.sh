#!/bin/bash
# PreToolUse safety hook for Bash: the rules live in lib/bash_safety_rules.py, run in one interpreter per call.
# This entry keeps the harness switch, the fail-closed interpreter check, and the pre-clean snapshot taken before a
# /do release lets a destructive `git clean` through. It runs inside hooks/pretool-launch.py, where the pre-tool
# verdicts meet and an /allow grant releases a refusal (lib/hook_launch.release_refused).
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib/harness_switch.sh" 2>/dev/null && harness_switch_exit_if_off  # no harness hook runs while /harness off holds

INPUT=$(cat)
. "$(dirname "${BASH_SOURCE[0]}")/lib/refusal_record.sh" 2>/dev/null && trap refusal_record_on_exit EXIT  # one refusal record when this hook refuses

# A Claude Code process started before its settings carried the overlay lacks CLAUDE_HOME; the guard keys it lacks
# come from the harness home's current settings.json.
[ -n "${CLAUDE_HOME:-}" ] || [ -z "${CLAUDECODE:-}${CLAUDE_PROJECT_DIR:-}" ] \
  || ! grep -qs '"CLAUDE_HOME"' "$(dirname "${BASH_SOURCE[0]}")/../settings.json" || eval "$(python3 \
  "$(dirname "${BASH_SOURCE[0]}")/lib/claude_home.py" env CLAUDE_DEV_SYSTEMD \
  CLAUDE_DAEMON_RESTART_GRANT_HELPER CLAUDE_PROTECTED_DAEMON_PREFIX CLAUDE_PROTECTED_DAEMON_TARGETS \
  CLAUDE_HARD_BANNED_SCRIPTS 2>/dev/null)"
export CLAUDE_DEV_SYSTEMD CLAUDE_DAEMON_RESTART_GRANT_HELPER CLAUDE_PROTECTED_DAEMON_PREFIX \
  CLAUDE_PROTECTED_DAEMON_TARGETS CLAUDE_HARD_BANNED_SCRIPTS
HOOKS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
CLAUDE_HOME="$(cd "$HOOKS_DIR/.." 2>/dev/null && pwd)"
PYTHON_BIN="${CLAUDE_PYTHON_BIN:-${CLAUDE_HOME}/venv/bin/python}"
[ -x "$PYTHON_BIN" ] || PYTHON_BIN="${CLAUDE_PYTHON_FALLBACK:-python3}"

VERDICT=$(printf '%s' "$INPUT" | "$PYTHON_BIN" "$HOOKS_DIR/lib/bash_safety_rules.py" "$HOOKS_DIR")
[ $? -eq 2 ] && [ -z "$VERDICT" ] && { _REFUSED_BY=hooks/lib/bash_safety_rules.py; exit 2; }  # a rule refused; its message is on stderr

# A granted destructive `git clean` proceeds only after its untracked work is snapshotted; a target that is not
# provably this working directory, or a failed snapshot, is refused.
_preclean_snapshot_guard() {
  local _guard_py="$HOOKS_DIR/lib/git_clean_guard.py" _guard_reason _guard_rc _guard_timeout
  COMMAND=$(printf '%s' "$INPUT" | "$PYTHON_BIN" -c "import json,sys; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('command',''))" 2>/dev/null)
  if [ ! -r "$_guard_py" ]; then
    _SAID="BLOCKED: granted 'git clean' denied — pre-clean WIP snapshot guard is unavailable (fail-closed)"; echo "$_SAID" >&2
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
  # The command goes on stdin: an exec'd environment string over the kernel's per-string limit (~128 KiB) fails
  # with E2BIG. CMD_INPUT is emptied so an inherited value cannot stand in for the command.
  _guard_reason=$(printf '%s' "$COMMAND" | CMD_INPUT= timeout -- "$_guard_timeout" "$PYTHON_BIN" "$_guard_py" 2>/dev/null)
  _guard_rc=$?
  case "$_guard_rc" in
    0)  return 0 ;;   # no destructive-or-uncertain `git clean`
    10) : ;;          # a destructive clean of this working directory: snapshot below
    126|127)          # the guard process could not be started: a deployment fault, not a verdict on the command
      _SAID="BLOCKED: /do or /allow release denied — the pre-clean guard could not run (rc=$_guard_rc), so the command cannot be checked for a destructive 'git clean' (fail-closed)"; echo "$_SAID" >&2
      echo "Command: $COMMAND" >&2
      echo "REASON: $PYTHON_BIN could not execute $_guard_py; repair the interpreter deployment, then re-issue the command." >&2
      exit 2
      ;;
    *)                # 11 = redirected or indeterminate target; any other rc = detector failure
      _SAID="BLOCKED: granted 'git clean' denied — no protective pre-clean WIP snapshot is possible (fail-closed)"; echo "$_SAID" >&2
      echo "Command: $COMMAND" >&2
      echo "REASON: ${_guard_reason:-the pre-clean guard could not classify this command}" >&2
      echo "Hint: re-issue the clean from this working directory without -C/--git-dir/--work-tree" >&2
      echo "      and without a leading cd/subshell, or snapshot the work yourself first." >&2
      exit 2
      ;;
  esac
  local _ckpt_lib="$HOOKS_DIR/lib/checkpoint-core.sh"
  if [ ! -r "$_ckpt_lib" ]; then
    _SAID="BLOCKED: granted 'git clean' denied — the pre-clean WIP snapshot library is unavailable (fail-closed)"; echo "$_SAID" >&2
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
  [ -z "$checkpoint_left_out" ] || _ckpt_rc="3 (written, but it left out $checkpoint_left_out)"  # lost to a clean
  trap - EXIT INT TERM HUP  # write_checkpoint's early returns leave its temp-index trap installed
  trap refusal_record_on_exit EXIT
  if [ "$_ckpt_rc" != 0 ]; then
    _SAID="BLOCKED: granted 'git clean' denied — the protective pre-clean WIP snapshot FAILED (fail-closed)"; echo "$_SAID" >&2
    echo "Command: $COMMAND" >&2
    if [ "$_ckpt_rc" = "2" ]; then
      echo "REASON: write_checkpoint rc=2 — this working directory is not a git repository, so untracked work cannot be snapshotted." >&2
    else
      echo "REASON: write_checkpoint rc=$_ckpt_rc — the snapshot is not complete, so untracked work would be unrecoverable." >&2
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
esac
_SAID="BLOCKED: safety-hook FAIL-CLOSED — the Python interpreter this hook depends on ($PYTHON_BIN) is unavailable or lib/bash_safety_rules.py gave no verdict, so no safety rule could be evaluated."; echo "$_SAID" >&2
echo "REASON: repair the interpreter deployment; a call no rule could read is never allowed." >&2
exit 2
