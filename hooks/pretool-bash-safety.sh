#!/bin/bash
# PreToolUse Safety Hook - Warn or block before dangerous operations
# Reads tool input from stdin as JSON (Claude Code hook protocol)

# Read full JSON from stdin
INPUT=$(cat)

CLAUDE_HOME="${CLAUDE_HOME:-${HOME}/.claude}"
CLAUDE_TMPDIR="${CLAUDE_TMPDIR:-${TMPDIR:-/tmp}}"
PYTHON_BIN="${CLAUDE_PYTHON_BIN:-${CLAUDE_HOME}/venv/bin/python}"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="${CLAUDE_PYTHON_FALLBACK:-python3}"
fi
DAEMON_RESTART_GRANT_DIR="${CLAUDE_DAEMON_RESTART_GRANT_DIR:-${CLAUDE_TMPDIR}}"
DAEMON_RESTART_SENTINEL_RE="$(printf '%s' "${DAEMON_RESTART_GRANT_DIR%/}/claude-allow-daemon-restart-" | sed 's/[][\\.^$*+?{}|()]/\\&/g')"

# IS_SUBAGENT: set once here at the top of the script (after PYTHON_BIN resolution).
# $INPUT is assigned once at line 6 and never reassigned, so this read is safe regardless of position.
# Used by check_and_consume_allowlist (subagent firewall) and the /do bypass block below.
IS_SUBAGENT=$(echo "$INPUT" | "$PYTHON_BIN" -c "import json,sys; d=json.load(sys.stdin); print('1' if d.get('agent_id') else '0')" 2>/dev/null)

# Codex compatibility: hook payloads may pass a multi-line shell snippet with
# strict-mode preludes such as `set -euo pipefail` before the actual command.
# Docker compose service detection must examine compose invocations, not the
# first shell token in the whole snippet; otherwise dev-only operations like
# `set -euo pipefail; cd /root/deploy; docker compose up -d happy-web-dev`
# are misclassified as service `set`.
strip_shell_prelude_for_compose() {
  local command="$1"
  command="$(printf '%s\n' "$command" | sed -E \
    -e '/^[[:space:]]*set([[:space:]]+[^;&|]+)*[[:space:]]*$/d' \
    -e '/^[[:space:]]*cd[[:space:]]+[^;&|]+[[:space:]]*$/d')"
  printf '%s\n' "$command"
}

# Extract tool name and command
TOOL_NAME=$(echo "$INPUT" | "$PYTHON_BIN" -c "import json,sys; d=json.load(sys.stdin); print(d.get('tool_name',''))" 2>/dev/null)
COMMAND=$(echo "$INPUT" | "$PYTHON_BIN" -c "import json,sys; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('command',''))" 2>/dev/null)
COMPOSE_COMMAND=$(strip_shell_prelude_for_compose "$COMMAND")

# Only act on Bash tool
if [ "$TOOL_NAME" != "Bash" ]; then
  exit 0
fi

# ── Dev whitelist (exact names only) ──────────────────────────────
# These are the ONLY dev resources that can be freely managed.
DEV_CONTAINERS="happy-web-dev"
# Per c3-20260504-223115 R1: happy-daemon-dev is REMOVED from the systemctl whitelist.
# All happy-daemon-* targets are gated by Layer 1.A (daemon-restart-prohibition) which
# requires an explicit user grant via /root/bin/claude-allow-restart. The systemctl block
# at line ~700 skips happy-daemon commands entirely (Layer 1.A already adjudicated).
DEV_SYSTEMD=""

# ── Helper: split compound command into subcommands ───────────────
# Splits on && || ; and checks each subcommand independently.
# Returns 0 (true) if ANY subcommand matches the pattern.
any_subcmd_matches() {
  local cmd="$1"
  local pattern="$2"
  # Replace && || ; with newlines, then check each line
  echo "$cmd" | sed 's/&&/\n/g; s/||/\n/g; s/;/\n/g' | while IFS= read -r subcmd; do
    if echo "$subcmd" | grep -qE "$pattern"; then
      return 0
    fi
  done
}

# Returns 0 if ALL container/service args in a docker/systemctl subcommand
# are in the whitelist. Returns 1 if any non-whitelisted target is found.
check_docker_targets_all_dev() {
  local cmd="$1"
  local whitelist="$2"
  # Split on && || ;
  echo "$cmd" | sed 's/&&/\n/g; s/||/\n/g; s/;/\n/g' | while IFS= read -r subcmd; do
    # Check if this subcommand is a docker stop/restart/rm/kill
    if echo "$subcmd" | grep -qE 'docker\s+(stop|restart|rm|kill)\s'; then
      # Extract all args after the docker action word
      local args
      args=$(echo "$subcmd" | sed -E 's/.*docker\s+(stop|restart|rm|kill)\s+//')
      # Check each arg that looks like a container name (skip flags like -f)
      for arg in $args; do
        [[ "$arg" == -* ]] && continue
        local found=0
        for dev in $whitelist; do
          if [ "$arg" = "$dev" ]; then
            found=1
            break
          fi
        done
        if [ "$found" = "0" ]; then
          return 1  # Non-dev target found
        fi
      done
    fi
  done
}

check_systemctl_targets_all_dev() {
  local cmd="$1"
  local whitelist="$2"
  echo "$cmd" | sed 's/&&/\n/g; s/||/\n/g; s/;/\n/g' | while IFS= read -r subcmd; do
    if echo "$subcmd" | grep -qE 'systemctl\s+(stop|restart)\s'; then
      local args
      args=$(echo "$subcmd" | sed -E 's/.*systemctl\s+(stop|restart)\s+//')
      for arg in $args; do
        [[ "$arg" == -* ]] && continue
        # Strip .service suffix for comparison
        local bare="${arg%.service}"
        local found=0
        for dev in $whitelist; do
          if [ "$bare" = "$dev" ]; then
            found=1
            break
          fi
        done
        if [ "$found" = "0" ]; then
          return 1
        fi
      done
    fi
  done
}

# ── One-shot allowlist bypass (single-shot /allow consume) ────────────────────
# Reads /tmp/claude-bash-allowlist-<sid>.json (written by userprompt-consent-allowlist.sh).
# On match: atomically deletes the flag (single-use), audit-logs, emits canonical
# Claude Code PreToolUse approval JSON to stdout, returns 0.
# Per task-id 20260509-113838 (R11 relaxation): this helper is invoked from the
# global /allow short-circuit at line 555, which runs BEFORE all four absolute-ban
# categories (Layer 1.A daemon-restart prohibition + session_dirs/happy-recovery/
# happy-restart). The user-binding directive (verbatim text preserved in
# docs/dev/ticket-20260509-113838.md) authorizes /allow to bypass any command
# including dangerous ones when the user explicitly grants the pattern; consume
# covers ANY safety block when the user-granted pattern matches.
# NEVER bypasses subagent calls (checked via IS_SUBAGENT script-global set at top of script).
CONSENT_LOG="$HOME/.claude/logs/bash-consent.log"

check_and_consume_allowlist() {
  local cmd="$1"

  # IS_SUBAGENT check: references the script-global IS_SUBAGENT variable set at the top
  # of the script (after PYTHON_BIN resolution). $INPUT is assigned once at line 6 and
  # never reassigned, so IS_SUBAGENT is valid for the entire script lifetime.
  if [ "$IS_SUBAGENT" = "1" ]; then
    return 1
  fi

  local sid
  sid=$(echo "$INPUT" | "$PYTHON_BIN" -c \
    "import json,sys,os; d=json.load(sys.stdin); print(d.get('session_id','') or os.environ.get('CLAUDE_SESSION_ID','default'))" \
    2>/dev/null)
  [ -z "$sid" ] && sid="default"

  local flag_file="/tmp/claude-bash-allowlist-${sid}.json"
  [ ! -f "$flag_file" ] && return 1

  # Consolidated consume path: V1 (SIGALRM regex timeout) + V2 (flock atomic read-match-unlink) +
  # V3 (compound-command split on && || ; | with per-subcommand match + block-rule cross-check).
  # Pattern and command passed via environment variables — never shell-interpolated into Python.
  local lock_file="${flag_file}.lock"
  local consume_result
  # Compute hooks directory in bash context (BASH_SOURCE is valid here; NOT exported to Python).
  HOOKS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  export HOOKS_DIR
  consume_result=$(CMD_INPUT="$cmd" SID_VAL="$sid" "$PYTHON_BIN" - <<'PYEOF'
# Shim: delegate grant-read/match to lib/allowlist.py (allow-6, task 20260518-155948).
# All grant-file I/O, lock strategy, SIGALRM regex timeout, and subcommand splitting
# now live in hooks/lib/allowlist.py:match_grant_for_bash_command.
import os, sys
sys.path.insert(0, os.environ["HOOKS_DIR"])
from lib.allowlist import match_grant_for_bash_command

cmd = os.environ["CMD_INPUT"]
sid = os.environ["SID_VAL"]
result = match_grant_for_bash_command(cmd, sid)
if result is not None:
    print("CONSUMED\t{}\t{}\t{}".format(
        result.pattern,
        "1" if result.is_regex else "0",
        result.matched_sub,
    ))
PYEOF
)

  # Parse structured result.
  case "$consume_result" in
    CONSUMED$'\t'*)
      local rest pattern is_regex matched_sub
      rest="${consume_result#CONSUMED$'\t'}"
      pattern="${rest%%$'\t'*}"
      rest="${rest#*$'\t'}"
      is_regex="${rest%%$'\t'*}"
      matched_sub="${rest#*$'\t'}"
      mkdir -p "$(dirname "$CONSENT_LOG")"
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) sid=$sid CONSUMED pattern='$pattern' is_regex=$is_regex matched_subcmd='$matched_sub' full_cmd='$cmd'" >> "$CONSENT_LOG"
      echo "[allow] Grant matched for pattern='$pattern' (matched subcommand: '$matched_sub'). consume deferred to PostToolUse. Command will proceed." >&2
      # DEFECT 3a fix iter-2 (task-id 20260509-113838): emit the canonical Claude
      # Code PreToolUse approval JSON to stdout. Field shape verified locally at
      # /root/.claude-cold.backup/2026-05-06/projects/-dev-shm-dev-workspace-dot-claude/
      # 314848b6-214f-4302-845f-dc5d3d5975be/tool-results/b7goje9q2.txt:18702,19028
      # (Anthropic Claude Code release notes); cross-verified by codex consultation
      # of https://code.claude.com/docs/en/hooks. This produces a valid permissions-
      # ledger entry for every consumed /allow. NOTE per D3b refutation: this
      # canonical "allow" does NOT cross-block-short-circuit a sibling project-local
      # deny — the docs specify "All matching hooks run in parallel" and PreToolUse
      # precedence is "deny > defer > ask > allow". Cross-block override of
      # /root/<repo>/.claude/settings.json deny rules requires a separate cycle
      # (Plan B/C/D/E per dev-report plan_a_blocker_d3b).
      #
      # iter-2 fix per qa-report finding 1: pass pattern + matched_sub via env vars
      # so the Python source itself is static. Shell-interpolating user-supplied
      # patterns (which may contain literal single quotes, backslashes, or newlines)
      # into a Python source string causes SyntaxError. json.dumps escapes any
      # internal quote/backslash/newline correctly. This mirrors the env-var passing
      # idiom used at userprompt-consent-allowlist.sh:140-148 for the same class of
      # user-supplied strings.
      PATTERN_VAL="$pattern" SUBCMD_VAL="$matched_sub" "$PYTHON_BIN" -c '
import json, os
reason = "/allow consumed for pattern=" + repr(os.environ["PATTERN_VAL"]) + " matched_subcmd=" + repr(os.environ["SUBCMD_VAL"])
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow", "permissionDecisionReason": reason}}))
'
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

# ── C3: daemon-restart prohibition helper (consume_daemon_restart_grant) ───
# TASK-ID: c3-20260504-223115 (introduced) + 20260509-113838 (R11 relaxed)
# Per BA spec docs/dev/ticket-c3-20260504-223115.md (original) +
# docs/dev/ticket-20260509-113838.md (R11 supersession).
#
# Note: as of task-id 20260509-113838 the global /allow short-circuit at
# line 555 runs BEFORE Layer 1.A daemon-restart prohibition. R11's narrower
# invariant ("daemon-restart NOT bypassable by generic /allow") is RELAXED
# per the user-binding directive (verbatim text preserved in
# docs/dev/ticket-20260509-113838.md) authorizing /allow to bypass any command
# including dangerous ones. The dedicated
# ${DAEMON_RESTART_GRANT_DIR}/claude-allow-daemon-restart-<target>.flag sentinel created by
# /root/bin/claude-allow-restart is preserved per W6 as the precise-grant
# alternative for users who prefer not to type generic /allow. The function
# below is still invoked from Layer 1.A; it remains the consume mechanism
# for the dedicated channel and is unaffected by the /allow short-circuit
# relocation.

DAEMON_RESTART_AUDIT_LOG="${CLAUDE_DAEMON_RESTART_AUDIT_LOG:-$HOME/.claude/logs/claude-daemon-restart-grants.log}"

# Atomic consume of ${DAEMON_RESTART_GRANT_DIR}/claude-allow-daemon-restart-<target>.flag.
# Reuses the same flock+SIGALRM atomic-consume design as check_and_consume_allowlist.
# Args: $1 = bare unit name (e.g. "happy-daemon-dev"), $2 = the verb being attempted.
# Returns 0 if a valid grant existed and was consumed (caller may proceed);
# returns 1 otherwise (caller must block).
check_and_consume_daemon_restart_grant() {
  local unit="$1"
  local verb="$2"

  # Derive target suffix: strip "happy-daemon-" or "happy-daemon" prefix.
  # happy-daemon-dev → dev; happy-daemon → default; happy-daemon-jade → jade
  local target
  case "$unit" in
    happy-daemon-dev) target="dev" ;;
    happy-daemon-jade) target="jade" ;;
    happy-daemon-qijie) target="qijie" ;;
    happy-daemon) target="default" ;;
    *) target="" ;;
  esac
  [ -z "$target" ] && return 1

  local sid
  sid=$(echo "$INPUT" | "$PYTHON_BIN" -c \
    "import json,sys,os; d=json.load(sys.stdin); print(d.get('session_id','') or os.environ.get('CLAUDE_SESSION_ID','default'))" \
    2>/dev/null)
  [ -z "$sid" ] && sid="default"

  mkdir -p "$(dirname "$DAEMON_RESTART_AUDIT_LOG")" 2>/dev/null || true

  local flag_file="${DAEMON_RESTART_GRANT_DIR%/}/claude-allow-daemon-restart-${target}.flag"
  local flag_all="${DAEMON_RESTART_GRANT_DIR%/}/claude-allow-daemon-restart-all.flag"
  local lock_file="${flag_file}.lock"

  # Try target-specific flag first; if absent, try the "all" flag.
  if [ ! -f "$flag_file" ] && [ -f "$flag_all" ]; then
    flag_file="$flag_all"
    lock_file="${flag_all}.lock"
  fi
  [ ! -f "$flag_file" ] && return 1

  local consume_result
  consume_result=$(FLAG_FILE="$flag_file" LOCK_FILE="$lock_file" UNIT_VAL="$unit" SID_VAL="$sid" TARGET_VAL="$target" "$PYTHON_BIN" - <<'PYEOF'
# Atomic flock+SIGALRM consume for daemon-restart grant.
# Reuses the design from check_and_consume_allowlist (lines 114-298).
import fcntl, json, os, signal, sys, time
from datetime import datetime, timezone

flag_file = os.environ['FLAG_FILE']
lock_file = os.environ['LOCK_FILE']
unit_val  = os.environ['UNIT_VAL']
sid_val   = os.environ['SID_VAL']
target    = os.environ['TARGET_VAL']

def _alarm(signum, frame):
    raise TimeoutError('parse timeout')

lock_fd = None
try:
    lock_fd = os.open(lock_file, os.O_CREAT | os.O_RDWR, 0o600)
    attempts = 0
    while True:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            attempts += 1
            if attempts >= 3:
                print('BLOCKED_LOCK')
                sys.exit(0)
            time.sleep(0.1)

    if not os.path.exists(flag_file):
        print('NO_FLAG')
        sys.exit(0)

    old = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(1)
    try:
        with open(flag_file) as fh:
            data = json.load(fh)
    except Exception:
        signal.alarm(0); signal.signal(signal.SIGALRM, old)
        print('NO_FLAG')
        sys.exit(0)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)

    grant_target = data.get('target', '')
    expires_at   = data.get('expires_at', '')
    grant_sid    = data.get('session_id', '')
    single_shot  = bool(data.get('single_shot', True))

    # Target match: either exact, or grant target is "all"
    if grant_target != target and grant_target != 'all':
        print('TARGET_MISMATCH\t{}\t{}'.format(grant_target, target))
        sys.exit(0)

    # Expiry check
    try:
        # Accept both "Z" and "+00:00" suffixes
        norm = expires_at.replace('Z', '+00:00')
        exp = datetime.fromisoformat(norm)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if exp <= now:
            print('EXPIRED\t{}'.format(expires_at))
            sys.exit(0)
    except Exception:
        print('EXPIRED\t{}'.format(expires_at))
        sys.exit(0)

    # Session match: grant_sid must equal sid_val (no-active-session never matches a real sid).
    if grant_sid and grant_sid != 'no-active-session' and grant_sid != sid_val:
        print('SESSION_MISMATCH\t{}\t{}'.format(grant_sid, sid_val))
        sys.exit(0)

    # All checks pass. Single-shot consume: unlink atomically while holding lock.
    try:
        os.unlink(flag_file)
    except FileNotFoundError:
        pass
    print('CONSUMED\t{}\t{}\t{}'.format(grant_target, expires_at, grant_sid))
except Exception as e:
    print('ERROR\t{}'.format(e))
    sys.exit(0)
finally:
    if lock_fd is not None:
        try: fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except Exception: pass
        try: os.close(lock_fd)
        except Exception: pass
PYEOF
)

  case "$consume_result" in
    CONSUMED$'\t'*)
      local rest grant_target expires grant_sid
      rest="${consume_result#CONSUMED$'\t'}"
      grant_target="${rest%%$'\t'*}"
      rest="${rest#*$'\t'}"
      expires="${rest%%$'\t'*}"
      grant_sid="${rest#*$'\t'}"
      "$PYTHON_BIN" - "$DAEMON_RESTART_AUDIT_LOG" "$sid" "$target" "$unit" "$verb" "$grant_target" "$expires" "$grant_sid" <<'PYAUDIT' >> "$DAEMON_RESTART_AUDIT_LOG"
import json, sys
from datetime import datetime, timezone
log_path, sid, target, unit, verb, grant_target, expires, grant_sid = sys.argv[1:9]
print(json.dumps({
    "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "sid": sid,
    "target": target,
    "unit": unit,
    "verb": verb,
    "outcome": "consumed",
    "grant_target": grant_target,
    "grant_session_id": grant_sid,
    "grant_expires_at": expires,
    "source": "pretool-bash-safety",
}, separators=(",", ":")))
PYAUDIT
      echo "[daemon-restart-grant] consumed grant for target=$target unit=$unit verb=$verb" >&2
      return 0
      ;;
    EXPIRED$'\t'*|TARGET_MISMATCH$'\t'*|SESSION_MISMATCH$'\t'*|NO_FLAG|BLOCKED_LOCK|ERROR$'\t'*)
      local outcome="${consume_result%%$'\t'*}"
      "$PYTHON_BIN" - "$DAEMON_RESTART_AUDIT_LOG" "$sid" "$target" "$unit" "$verb" "$outcome" <<'PYAUDIT2' >> "$DAEMON_RESTART_AUDIT_LOG"
import json, sys
from datetime import datetime, timezone
log_path, sid, target, unit, verb, outcome = sys.argv[1:7]
print(json.dumps({
    "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "sid": sid,
    "target": target,
    "unit": unit,
    "verb": verb,
    "outcome": outcome.lower(),
    "source": "pretool-bash-safety",
}, separators=(",", ":")))
PYAUDIT2
      return 1
      ;;
    *)
      return 1
      ;;
  esac
}

# ── Global /allow short-circuit ─────────────────────────────────────────────
# RELOCATED 2026-05-09 (task-id 20260509-113838) to run BEFORE all four
# absolute-ban categories (Layer 1.A-E daemon-restart prohibition + the three
# session/recovery/restart blocks below). The user-binding directive (verbatim
# text preserved in docs/dev/ticket-20260509-113838.md) authorizing /allow to
# bypass any command including dangerous ones when the user explicitly grants
# the pattern supersedes c3-20260504-223115 R11.
# R11's narrower invariant ("daemon-restart NOT bypassable by generic /allow")
# is RELAXED for users who type generic /allow. The dedicated
# /root/bin/claude-allow-restart channel and its check_and_consume_daemon_restart_grant
# function are UNTOUCHED (W6) and remain the precise-grant alternative for
# users who prefer R11's tighter band.
# Single-shot consume semantics, V1 SIGALRM regex timeout, V1b structural
# rejection, flock atomic-unlink, and the IS_SUBAGENT firewall (inside
# check_and_consume_allowlist) are all preserved unchanged.
# On consume-match: emits canonical Claude Code PreToolUse approval JSON to
# stdout (DEFECT 3a) for permissions-ledger value; sibling project-local
# settings.json hooks still run in parallel and a project-local deny still
# wins per documented "deny > defer > ask > allow" precedence (D3b is a
# Plan-A-blocker; see dev-report plan_a_blocker_d3b for alternatives).
# ── Main-agent /do bypass ────────────────────────────────────────────────────
# IS_SUBAGENT is set at the top of the script — no inline parse needed here.
if [ "$IS_SUBAGENT" != "1" ]; then
  _DO_SID=$(echo "$INPUT" | "$PYTHON_BIN" -c \
    "import json,sys,os; d=json.load(sys.stdin); \
print(d.get('session_id','') or os.environ.get('CLAUDE_SESSION_ID','default'))" \
    2>/dev/null)
  [ -z "$_DO_SID" ] && _DO_SID="default"
  _DO_FLAG="/tmp/claude-orchestrator-consent-${_DO_SID}.flag"
  if [ -f "$_DO_FLAG" ] && [ "$(cat "$_DO_FLAG" 2>/dev/null)" = "true" ]; then
    exit 0
  fi
fi
# ────────────────────────────────────────────────────────────────────────────
# Sentinel-grant short-circuit (task 20260519-211515 R2 / AC2).
# Reads /tmp/claude-grants/<task_id>.json via hooks/lib/allowlist.py
# match_sentinel_grant_for_bash_command(). The predicate is STRUCTURED:
# allowed_operations[] entries must EQUAL the bash sub-command's op/target
# tokens — the in-hook command-text grep is REPLACED by this structured
# match. Substring matching against the raw command line is forbidden.
# This is the consume-on-any-terminal-result entry point; PostToolUse
# performs the unlink for all four terminal cases (success, non_zero,
# malformed, comment_only).
SENTINEL_EXISTS_FOR_TASK=0
# M2 (task 20260521-090200): sentinel check extended to IS_SUBAGENT=1 so user-created
# structured grants are honored in subagent context. The IS_SUBAGENT guard at line 145
# (legacy pattern-string grants) REMAINS UNCHANGED — only structured sentinel grants
# (user-created via /allow, written by userprompt-consent-allowlist.sh) are extended here.
TASK_ID_FOR_SENTINEL="${CLAUDE_TASK_ID:-}"
if [ -z "$TASK_ID_FOR_SENTINEL" ]; then
  # M3 (task 20260521-090200): align reader fallback to session_id (same as writer).
  # Writer (userprompt-consent-allowlist.sh:176) uses CLAUDE_TASK_ID:-SID where SID=session_id.
  # Previously reader fell back to task_id field first, causing mismatch when task_id != session_id.
  TASK_ID_FOR_SENTINEL=$(echo "$INPUT" | "$PYTHON_BIN" -c \
    "import json,sys,os; d=json.load(sys.stdin); print(d.get('session_id','') or os.environ.get('CLAUDE_SESSION_ID','default'))" \
    2>/dev/null)
fi
if [ -n "$TASK_ID_FOR_SENTINEL" ]; then
  HOOKS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  SENTINEL_QUERY=$(HOOKS_DIR="$HOOKS_DIR" CMD_INPUT="$COMMAND" TASK_ID="$TASK_ID_FOR_SENTINEL" "$PYTHON_BIN" - <<'PYEOF' 2>/dev/null
import os, sys
sys.path.insert(0, os.environ['HOOKS_DIR'])
from lib.allowlist import load_sentinel_grant_for_task, match_sentinel_grant_for_bash_command
task_id = os.environ['TASK_ID']
cmd = os.environ['CMD_INPUT']
grant = load_sentinel_grant_for_task(task_id)
if grant is None:
    print('SENTINEL_NONE')
else:
    m = match_sentinel_grant_for_bash_command(task_id, cmd)
    if m is not None:
        print('SENTINEL_OK')
    else:
        print('SENTINEL_EXISTS_NO_MATCH')
PYEOF
)
  case "$SENTINEL_QUERY" in
    SENTINEL_OK)
      mkdir -p "$(dirname "$CONSENT_LOG")"
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) task=$TASK_ID_FOR_SENTINEL SENTINEL_GRANT_MATCHED command='$COMMAND'" >> "$CONSENT_LOG"
      echo "[allow-sentinel] structured grant matched for task=$TASK_ID_FOR_SENTINEL. consume-on-any-terminal-result deferred to PostToolUse." >&2
      "$PYTHON_BIN" -c 'import json; print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow", "permissionDecisionReason": "/allow sentinel grant consumed (structured allowed_operations[] match)"}}))'
      exit 0
      ;;
    SENTINEL_EXISTS_NO_MATCH)
      # AC2 invariant (CF-1, codex iter-1 adversarial review): when a
      # structured sentinel exists for this task but does NOT match the
      # current bash command structurally, the legacy /allow short-circuit
      # MUST NOT be consulted. Substring-matching the comment-only attack
      # (e.g. `echo hi # rm -rf /` against a legacy `rm` pattern) would
      # otherwise succeed via the legacy path. We mark this and skip the
      # legacy short-circuit below.
      SENTINEL_EXISTS_FOR_TASK=1
      echo "[allow-sentinel] sentinel exists for task=$TASK_ID_FOR_SENTINEL but command did not match allowed_operations[] — legacy /allow path suppressed for this Bash call (AC2 invariant)." >&2
      ;;
    SENTINEL_NONE|*)
      # No sentinel: legacy /allow short-circuit may proceed.
      :
      ;;
  esac
fi

# ────────────────────────────────────────────────────────────────────────────
# Global /allow short-circuit — sole PreToolUse allowlist match/approval call site in
# pretool-bash-safety.sh. Fires unconditionally after the /do bypass and before all
# block rules. Actual grant deletion is deferred to posttool-allowlist-consume.py
# (PostToolUse). Per-rule secondary calls were removed in task 20260518-094616 because
# the global short-circuit at this location covers all paths unconditionally.
#
# CF-1 gating (task 20260519-211515 codex iter-1 BLOCKER): when a structured
# sentinel exists for the current task but did NOT match the bash command's
# allowed_operations[] structurally, the legacy substring-match short-circuit
# is SUPPRESSED — otherwise the comment-only bypass attack (e.g. `echo hi
# # rm -rf /` against a legacy `rm` pattern) defeats AC2's "predicate never
# substring-matches against the command line" invariant. If no sentinel exists
# (SENTINEL_EXISTS_FOR_TASK=0) we still run the legacy short-circuit for
# back-compat with pre-migration grants.
if [ "$SENTINEL_EXISTS_FOR_TASK" != "1" ]; then
  check_and_consume_allowlist "$COMMAND" && exit 0
fi

# Layer 1.A — daemon-restart prohibition: systemctl verb gate against happy-daemon-*.
# Verb set: stop|restart|disable|enable|reload|kill|try-restart|reload-or-restart.
# Anchor `(\s+|\b)` so `systemctl kill -s SIGTERM happy-daemon-dev` matches (verb
# followed by `-s` flag, not whitespace-then-target). Stable label: daemon-restart-prohibition.
if echo "$COMMAND" | grep -qE 'systemctl\s+(stop|restart|disable|enable|reload|kill|try-restart|reload-or-restart)(\s+|\b)' \
   && echo "$COMMAND" | grep -qE 'happy-daemon'; then
  # Identify the bare unit name in the command. We look for happy-daemon[suffix]
  # tokens; if multiple targets, the consume rejects unless grant covers all.
  HAPPY_UNIT=$(echo "$COMMAND" | grep -oE 'happy-daemon(-(dev|jade|qijie))?' | head -1 | sed 's/\.service$//')
  HAPPY_VERB=$(echo "$COMMAND" | grep -oE 'systemctl\s+(stop|restart|disable|enable|reload|kill|try-restart|reload-or-restart)' | head -1 | awk '{print $2}')
  if [ -n "$HAPPY_UNIT" ] && check_and_consume_daemon_restart_grant "$HAPPY_UNIT" "$HAPPY_VERB"; then
    : # grant consumed — fall through to allow the command
  else
    echo "BLOCKED: daemon-restart-prohibition — systemctl ${HAPPY_VERB:-<verb>} on ${HAPPY_UNIT:-happy-daemon-*} is FORBIDDEN" >&2
    echo "Command: $COMMAND" >&2
    echo "REASON: per c3-20260504-223115, Claude must NEVER restart any happy-daemon-* by any path." >&2
    echo "Hint: user must run /root/bin/claude-allow-restart <target> from a real TTY first." >&2
    exit 2
  fi
fi

# Layer 1.B — wrapper-class block: any wrapper invocation co-occurring with
# happy-daemon vocabulary AND daemon-state-disrupting verb. Stable label:
# daemon-restart-wrapper.
if echo "$COMMAND" | grep -qE 'happy-daemon' \
   && echo "$COMMAND" | grep -qE '(restart|stop|disable|enable|reload|kill|try-restart|reload-or-restart|kick|cycle|bounce|hup|HUP)' \
   && echo "$COMMAND" | grep -qE '(systemd-run|^|[[:space:]])((at|batch)\s|crontab\s|nohup\s|disown\s|watch\s|timeout\s|dbus-send|busctl|nc\s|ncat\s|eval\s|bash\s+-c|sh\s+-c|zsh\s+-c|python3?\s+-c|node\s+-[ce]|perl\s+-e|ruby\s+-e)'; then
  echo "BLOCKED: daemon-restart-wrapper — wrapper invocation co-occurring with daemon-restart vocabulary is FORBIDDEN" >&2
  echo "Command: $COMMAND" >&2
  echo "REASON: per c3-20260504-223115, indirect daemon-restart paths (systemd-run/at/crontab/nohup/" >&2
  echo "        timeout/dbus-send/nc/eval/bash -c/python -c) are all forbidden. Use the user-only" >&2
  echo "        /root/bin/claude-allow-restart grant channel instead." >&2
  exit 2
fi

# Layer 1.C — wrapper script on disk: bash /tmp/*.sh, /var/tmp/*.sh, /dev/shm/*.sh
# are blocked outright regardless of body content (orchestrator AND subagents).
# Stable label: daemon-restart-wrapper.
if echo "$COMMAND" | grep -qE '(^|[;&|]\s*)(bash|sh|zsh)\s+(/tmp/|/var/tmp/|/dev/shm/)[^[:space:];&|]+\.sh'; then
  echo "BLOCKED: daemon-restart-wrapper — bash invocation of disposable wrapper script is FORBIDDEN" >&2
  echo "Command: $COMMAND" >&2
  echo "REASON: per c3-20260504-223115, wrapper scripts under /tmp/, /var/tmp/, /dev/shm/ can be a" >&2
  echo "        durable bypass surface for daemon-restart. Run commands inline or via tracked scripts." >&2
  exit 2
fi

# Layer 1.D — daemon HTTP /stop UNCONDITIONAL block. Trigger: any
# (curl|wget|nc|ncat|http.client|aiohttp|requests) invocation referencing
# (localhost|127.0.0.1):PORT/stop, regardless of surrounding text. Stable
# label: daemon-restart-http-stop. Per BA AC4 / OBJ-3-F: there is no
# legitimate Claude reason to POST/GET to `/stop` on a localhost service.
if echo "$COMMAND" | grep -qE '(curl|wget|nc[[:space:]]|ncat|http\.client|aiohttp|requests)' \
   && echo "$COMMAND" | grep -qE '(localhost|127\.0\.0\.1):[0-9]+/stop'; then
  echo "BLOCKED: daemon-restart-http-stop — HTTP /stop on a localhost port is FORBIDDEN" >&2
  echo "Command: $COMMAND" >&2
  echo "REASON: per c3-20260504-223115, the daemon HTTP /stop endpoint is the only documented" >&2
  echo "        use of /stop on a localhost port; Claude must never trigger it. False-positive risk" >&2
  echo "        on other localhost services is accepted by design." >&2
  exit 2
fi

# Layer 1.E — sentinel-write block: any Bash that creates/edits the grant
# sentinel is forbidden (only /root/bin/claude-allow-restart may write it).
# Stable label: daemon-restart-sentinel-write.
if echo "$COMMAND" | grep -qE "${DAEMON_RESTART_SENTINEL_RE}[A-Za-z0-9_-]+\.flag" \
   && echo "$COMMAND" | grep -qE '(>|>>|tee|cp|mv|ln|touch|cat\s)'; then
  echo "BLOCKED: daemon-restart-sentinel-write — writing to grant sentinel is FORBIDDEN" >&2
  echo "Command: $COMMAND" >&2
  echo "REASON: per c3-20260504-223115, only /root/bin/claude-allow-restart (run by user from TTY)" >&2
  echo "        may create the grant sentinel." >&2
  exit 2
fi

# Layer 1.F — bulk-commit sentinel write block (M4.3 / AC-04,
# task 20260524-205206 + 20260525-095242 iter-3 compound-bypass hardening).
# Deny ANY model tool call (regardless of agent_id; main agent NOT exempt —
# codex iter-2 finding #7 fix) that even MENTIONS the protected glob
# /tmp/claude-bulk-commit-sentinel-*.json
# in a Bash command, UNLESS the WHOLE command is a single pure-read
# invocation OR a BARE official-writer invocation.
#
# This cycle (20260525-095242) tightens the allowlist semantics from
# PREFIX-read to WHOLE-COMMAND-read. The prior allowlist matched the
# read-only verb at the start of the command and only vetoed redirect
# tokens (> / >> / tee), allowing compound bypasses such as
# `ls <sentinel> ; python3 -c '...write...'` to slip through (the suffix
# write segment was never evaluated). The new predicate asserts the
# entire command shape:
#   (a) Bare official-writer: `python3 scripts/write-bulk-commit-sentinel.py [args]`
#       — /commit --bulk Step 5 invocation. STARTS-WITH
#       match (not substring) to defeat comment-spoof attacks.
#   (b) Single pure-read: command begins with one of
#       ls|stat|cat|file|wc|head|tail|grep|jq|find|test|[
#       AND contains NO shell control structure (`;`, `&&`, `||`, `|`,
#       bare `&`, `|&`, newline, `$(`, backtick, `<(`, `>(`, `<<`, `<<<`,
#       shell keywords if/then/else/fi/for/while/do/done/case/esac/function)
#       AND NO redirect (`>`, `>>`, `<>`, `tee`) AND NO recursive shell
#       (`bash|sh|zsh|dash|python|node|perl|ruby` with `-c`/`-e`;
#       `eval`; `source`) AND NO leading variable assignment (`VAR=...`)
#       AND NO `xargs`/`-exec`/`-delete`/`-execdir`/`-ok`/`-okdir` write
#       surface targeting the protected path.
# Anything else → DENY with stable stderr token `bulk-commit-sentinel-write`.
# Context-strip: remove string-content false positives for Layer 1.F entry gate.
# Moved here (dev-20260529-210759) so COMMAND_CONTEXT_STRIPPED is available to the
# Layer 1.F entry gate below. This is intentionally a bounded classifier, NOT a
# full shell parser.  It runs from a file path (not `python -`) and is wrapped by
# timeout + virtual-memory limits; on any failure the raw command is used, so the
# hook fails closed and never drops potentially executable text.
COMMAND_CONTEXT_STRIPPED="$COMMAND"
HOOKS_DIR_CTX="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -r "$HOOKS_DIR_CTX/lib/bash_context_strip.py" ]; then
  _ctx_out=$(
    ulimit -v "${CLAUDE_HOOK_CONTEXT_MEM_KB:-262144}" 2>/dev/null || true
    CMD_INPUT="$COMMAND" timeout "${CLAUDE_HOOK_CONTEXT_TIMEOUT:-2s}" \
      "$PYTHON_BIN" "$HOOKS_DIR_CTX/lib/bash_context_strip.py" 2>/dev/null
  )
  _ctx_status=$?
  if [ "$_ctx_status" -eq 0 ]; then
    COMMAND_CONTEXT_STRIPPED="$_ctx_out"
  fi
  unset _ctx_out _ctx_status
fi

# Entry gate: protected path mention. Uses TWO grep -F substring matches
# (item 5 fix, task 20260526-053746 AC-05/AC-05b) to match BOTH literal session-id
# paths AND glob forms (*, ?, [abc], [!abc]) — POSIX shell-glob bracket syntax.
# Prior regex `[A-Za-z0-9_\-]*` excluded glob metachars, so `cat /tmp/claude-bulk-commit-sentinel-*.json`
# entirely skipped Layer 1.F protection. The substring approach is wider but the
# Layer 1.F entry gate is intentionally permissive — actual write/compound detection
# happens inside the block via shlex tokenization (items 3+4).
# Note: raw $COMMAND is used for the entry gate (not COMMAND_CONTEXT_STRIPPED) to
# preserve coverage for compound commands where the context stripper removes the
# script path from python3 segment tokens. False positives from quoted string
# arguments are resolved inside the block by _bulk_decision (dev-20260529-210759).
if echo "$COMMAND" | grep -qF '/tmp/claude-bulk-commit-sentinel-' \
   || echo "$COMMAND" | grep -qF 'write-bulk-commit-sentinel.py'; then
  # M5 (task 20260526-052559): canonical /commit --bulk Step 5 venv-activate form.
  # Must be checked in bash BEFORE the Python compound-detection helper because the
  # canonical form contains && (compound) and source (shell keyword) — the Python
  # helper correctly DENYs those. [[ =~ ]] is used (NOT echo|grep -qE) to prevent
  # newline-injection bypass: bash [[ =~ ]] matches the WHOLE string; grep -qE is
  # line-oriented and would match a second line after an injected newline.
  _BULK_CANONICAL_RE='^source[[:space:]]+venv/bin/activate[[:space:]]*&&[[:space:]]*python3?[[:space:]]+/root/\.claude/scripts/write-bulk-commit-sentinel\.py$'
  if [[ $COMMAND =~ $_BULK_CANONICAL_RE ]]; then
    exit 0
  fi
  # Items 3+4 (task 20260526-053746): replace raw-text grep compound/write
  # detectors with a Python helper using shlex.shlex(posix=True, punctuation_chars=True)
  # tokenizer. The helper:
  #   (a) tokenizes the command with shlex.shlex(posix=True, punctuation_chars=True);
  #       lex.commenters='', lex.whitespace_split=True set via attribute assignment
  #       (NOT constructor kwarg — codex iter-2 C1).
  #   (b) exhausts the lexer via list(lex) inside try/except ValueError to fail-closed
  #       on unterminated-quote inputs (AC-08 / codex iter-2 C11).
  #   (c) inspects tokens for compound separators (;, &&, ||, |, &, |&, $(, `, <(, >(, <<, <<<, newline)
  #       — punctuation_chars=True correctly splits unspaced separators (AC-07).
  #   (d) detects write-action tokens (-exec, -execdir, -delete, -ok, -okdir,
  #       -fprint, -fprint0, -fprintf, -fls) AND their $-prefixed ANSI-C reassembled
  #       forms ($-delete, $-fprint, etc.) per codex iter-2 C9 / AC-03.
  #   (e) for cmd-sub/process-sub distinction (AC-04): runs a raw-text inspection
  #       pass that finds unquoted or double-quoted $( <( >( forms — these survive
  #       shlex with retained leading $/</> on token OR appear outside single-quotes
  #       in the raw text. Single-quoted bodies tokenize WITH the metachar but the
  #       raw text shows the metachar inside '...' — these are ALLOWED for pure-read.
  #   (f) returns the decision via stdout: BARE_WRITER | PURE_READ | DENY | TOKENIZER_ERROR.
  HOOKS_DIR_BULK="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  _bulk_decision=$(CMD_INPUT="$COMMAND" "$PYTHON_BIN" - <<'PYEOF' 2>/dev/null
import os, sys, shlex, re

cmd = os.environ.get('CMD_INPUT', '')

# Whitespace-trim for STARTS-WITH predicates on the raw text.
trimmed = cmd.lstrip()

# Canonical tokenizer recipe per ticket Reference Source / context constraints.
# MUST exhaust the lexer via list(lex) — construction alone does not raise
# (iter-2 C11). On ValueError (e.g. unterminated quote), fail-closed (AC-08).
def tokenize_or_deny(text):
    lex = shlex.shlex(text, posix=True, punctuation_chars=True)
    lex.commenters = ''        # attribute assignment, NOT constructor kwarg (C1)
    lex.whitespace_split = True
    try:
        return list(lex)       # MUST exhaust; construction alone will not raise
    except ValueError:
        return None            # signal fail-closed DENY (AC-08)

# Raw-text quote-state walk: detect unquoted OR double-quoted $( <( >( ` substrings.
# Single-quoted bodies are NOT active subshells (single quotes inhibit expansion).
# Double-quoted bodies ARE active subshells (double quotes do NOT inhibit $() or
# backticks — codex iter-2 C6 + iter-3 F4). Single quotes inside double quotes
# are LITERAL — they do NOT toggle single-quote state (iter-3 F4 closure).
# State machine: 4 states tracked explicitly:
#   - UNQUOTED (default): $( / <( / >( / ` are ACTIVE
#   - SINGLE: nothing is active; only ' exits to UNQUOTED
#   - DOUBLE: $( and ` are ACTIVE; <( / >( are inert (treated as literal inside "...")
#             only " exits to UNQUOTED. \ escapes the next char (mostly for \" and \\).
#   - ANSI_C: $'...' bash extension. Backslash escapes the next char. Only ' exits.
#             Body is literal; no expansion. Treat like SINGLE for active-form purposes.
def has_active_cmdsub_or_procsub(text):
    UNQUOTED, SINGLE, DOUBLE, ANSI_C = 0, 1, 2, 3
    state = UNQUOTED
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if state == UNQUOTED:
            # ANSI-C quoting start: $'...'
            if c == '$' and i + 1 < n and text[i+1] == "'":
                state = ANSI_C
                i += 2
                continue
            # Active forms in UNQUOTED state:
            if c == '$' and i + 1 < n and text[i+1] == '(':
                return True
            if c == '<' and i + 1 < n and text[i+1] == '(':
                return True
            if c == '>' and i + 1 < n and text[i+1] == '(':
                return True
            if c == '`':
                return True
            # State transitions.
            if c == "'":
                state = SINGLE
                i += 1
                continue
            if c == '"':
                state = DOUBLE
                i += 1
                continue
            # Backslash in UNQUOTED state escapes the next char.
            if c == '\\' and i + 1 < n:
                i += 2
                continue
            i += 1
            continue
        if state == SINGLE:
            # Inside single quotes nothing is active and nothing escapes.
            if c == "'":
                state = UNQUOTED
            i += 1
            continue
        if state == DOUBLE:
            # Inside double quotes: $( and backticks ARE active; <( and >( are
            # NOT active (literal). Single quotes are LITERAL (do not toggle).
            # Backslash escapes \, $, `, " and newline (per bash); for our scan
            # treating \X as a 2-char skip is safe.
            if c == '\\' and i + 1 < n:
                i += 2
                continue
            if c == '$' and i + 1 < n and text[i+1] == '(':
                return True
            if c == '`':
                return True
            if c == '"':
                state = UNQUOTED
            i += 1
            continue
        if state == ANSI_C:
            # Inside $'...': backslash escapes the next char (\', \\, \n, etc.).
            # Only an unescaped ' exits.
            if c == '\\' and i + 1 < n:
                i += 2
                continue
            if c == "'":
                state = UNQUOTED
            i += 1
            continue
    return False

# Tokenize FIRST so all subsequent checks (including bare-writer + pure-read)
# operate on the parsed token list. Bare-writer regression iter-3 F3: the prior
# anchored regex `^(python3?\s+)?scripts/write-bulk-commit-sentinel\.py(\s|$)`
# matched `script.py ; touch <flag>` because `(\s|$)` accepted the space before
# `;`. Tokenizing first lets us run all compound/redirect/write checks before
# the bare-writer decision is made.
tokens = tokenize_or_deny(cmd)
if tokens is None:
    print('TOKENIZER_ERROR')
    sys.exit(0)

# Newline check via raw text (shlex collapses newlines as whitespace).
if '\n' in cmd:
    print('DENY')
    sys.exit(0)

# Active cmd-sub / process-sub raw-text scan with 4-state quote machine.
# Runs BEFORE shlex token analysis because shlex strips quotes uniformly and
# cannot distinguish single-quoted '$(cmd)' (inactive — AC-04 d) from
# unquoted/double-quoted $(cmd)/"$(cmd)" (active — AC-04 g/h/i/j).
if has_active_cmdsub_or_procsub(cmd):
    print('DENY')
    sys.exit(0)

# Compound separator tokens as standalone tokens after punctuation_chars=True.
COMPOUND_TOKENS = {';', '&&', '||', '|', '&', '|&', ';;'}
for t in tokens:
    if t in COMPOUND_TOKENS:
        print('DENY')
        sys.exit(0)

# Recursive shell: <interpreter> -c|-e or combined flags like -lc, -ec, -lce
RECURSIVE_SHELLS = {'bash', 'sh', 'zsh', 'dash', 'python', 'python3', 'node', 'perl', 'ruby'}
import re as _re_rs
for i, t in enumerate(tokens):
    if t in RECURSIVE_SHELLS and i + 1 < len(tokens):
        _next = tokens[i+1]
        if _next in ('-c', '-e') or (_next.startswith('-') and _re_rs.match(r'^-[a-zA-Z]*[ce][a-zA-Z]*$', _next)):
            print('DENY')
            sys.exit(0)

# eval / source / dot-source as standalone command tokens.
for i, t in enumerate(tokens):
    if t in ('eval', 'source', '.'):
        if i == 0 or tokens[i-1] in COMPOUND_TOKENS:
            print('DENY')
            sys.exit(0)

# Leading variable assignment (VAR=value).
if tokens and re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', tokens[0]):
    print('DENY')
    sys.exit(0)

# Shell keywords as standalone tokens.
SHELL_KEYWORDS = {'if', 'then', 'else', 'elif', 'fi', 'for', 'while',
                  'until', 'do', 'done', 'case', 'esac', 'function', 'select'}
for t in tokens:
    if t in SHELL_KEYWORDS:
        print('DENY')
        sys.exit(0)

# xargs anywhere.
if 'xargs' in tokens:
    print('DENY')
    sys.exit(0)

# Redirect tokens — extended set per codex iter-3 F6. Bash redirections that
# tokenize as standalone tokens under punctuation_chars=True include the full
# set below. tee is a separate verb. Any of these on the protected path is a
# write surface.
REDIRECT_TOKENS = {
    '>', '>>', '<', '<>', '>|',
    '&>', '&>>', '>&', '<&',
    '<<', '<<-', '<<<',
}
for t in tokens:
    if t in REDIRECT_TOKENS:
        print('DENY')
        sys.exit(0)
if 'tee' in tokens:
    print('DENY')
    sys.exit(0)

# Write-action veto for find. Codex iter-2 C9 + iter-1 F2 + iter-3 F5: shlex
# does NOT expand ANSI-C `$'...'`, and bash accepts many equivalent concatenated
# forms like `-de$'lete'` (tokenizes to `-de$lete`) and `$'-de'$'lete'` (tokenizes
# to `$-de$lete`). The previous { -delete, $-delete } match is too narrow.
# General rule per F5: normalize the candidate token by stripping all '$' bytes
# and compare against the bare set.
WRITE_ACTION_FLAGS = {
    '-exec', '-execdir', '-delete', '-ok', '-okdir',
    '-fprint', '-fprint0', '-fprintf', '-fls',
}

def normalize_ansic_token(s):
    """Decode ANSI-C escape sequences that shlex does not expand.
    Fail-closed: return original token on any decode error."""
    try:
        import re as _re
        C_ESCAPES = {'n':'\n','t':'\t','r':'\r','a':'\a','b':'\b',
                     'f':'\f','v':'\v','\\':'\\','\'':'\'','"':'"'}
        def _repl(m):
            g = m.group(0)
            if g[1] == 'x':
                return chr(int(g[2:], 16))
            if g[1] == 'U':
                return chr(int(g[2:], 16))
            if g[1] == 'u':
                return chr(int(g[2:], 16))
            if g[1] == '0':
                return chr(int(g[2:], 8))
            if g[1] in '1234567':
                return chr(int(g[1:], 8))
            if g[1] in C_ESCAPES:
                return C_ESCAPES[g[1]]
            return g
        pat = r'\\(?:x[0-9a-fA-F]{2}|U[0-9a-fA-F]{8}|u[0-9a-fA-F]{4}|0[0-7]{1,3}|[0-7]{1,3}|[ntrabfv\\\'"])'
        return _re.sub(pat, _repl, s)
    except Exception:
        return None  # fail-closed: caller treats None as suspicious

for t in tokens:
    if t in WRITE_ACTION_FLAGS:
        print('DENY')
        sys.exit(0)
    # Strip all $ bytes for ANSI-C concatenated forms.
    if '$' in t:
        normalized = t.replace('$', '')
        if normalized in WRITE_ACTION_FLAGS:
            print('DENY')
            sys.exit(0)
    # Decode ANSI-C hex/octal/unicode escapes that shlex leaves unexpanded.
    # Combine $-strip + escape decode for concatenated forms like -de$'\x6c'ete.
    stripped = t.replace('$', '')
    decoded = normalize_ansic_token(stripped)
    if decoded is None:  # decode error: fail-closed
        print('DENY')
        sys.exit(0)
    if decoded in WRITE_ACTION_FLAGS:
        print('DENY')
        sys.exit(0)

# Now that all compound/write/dangerous shapes have been ruled out, decide the
# allowlist branch. Bare-writer (a) and pure-read (b) decisions happen LAST,
# AFTER the deny gauntlet above (codex iter-3 F3 fix).

# False-positive guard (dev-20260529-210759): if the protected name appears ONLY
# as a substring of a longer argument token (not as a standalone path token),
# the command is passing the name as string argument text, not executing it.
# Examples: codex exec --prompt "...write-bulk-commit-sentinel.py..."
#           python3 graphify-query.py --requirement "...write-bulk-commit-sentinel.py..."
# These reach here because they have no compound separators, no recursive shell,
# and no write-action tokens. The shlex tokenizer (posix=True) unquotes the
# string arg, so the protected name appears as a substring of the arg token.
_SENTINEL_SCRIPT = 'write-bulk-commit-sentinel.py'
_SENTINEL_PATH = '/tmp/claude-bulk-commit-sentinel-'
_sentinel_in_arg_only = False
for _t in tokens:
    # If any token IS the standalone path (or a path ending with it), it is a
    # real executable reference — no false-positive guard applies.
    if _t == _SENTINEL_SCRIPT or _t.endswith('/' + _SENTINEL_SCRIPT):
        _sentinel_in_arg_only = False
        break
    if _t.startswith(_SENTINEL_PATH) and not any(c in _t[len(_SENTINEL_PATH):] for c in ' \t'):
        _sentinel_in_arg_only = False
        break
    # Protected name appears embedded in a longer token (argument text).
    if _SENTINEL_SCRIPT in _t or _SENTINEL_PATH in _t:
        _sentinel_in_arg_only = True
if _sentinel_in_arg_only:
    print('PURE_READ')
    sys.exit(0)

# Allowlist (a): BARE official-writer — first token (or first 2 tokens for
# `python3 scripts/...`) must match the official writer path EXACTLY. The
# regex form is preserved on the trimmed text but ONLY reaches here when the
# command has no compound/write/dangerous shape.
BARE_WRITER_RE = re.compile(r'^(python3?\s+)?scripts/write-bulk-commit-sentinel\.py(\s|$)')
if BARE_WRITER_RE.match(trimmed):
    print('BARE_WRITER')
    sys.exit(0)

# Allowlist (b): single pure-read invocation. First token must be a pure-read verb.
PURE_READ_VERBS = {'ls', 'stat', 'cat', 'file', 'wc', 'head', 'tail',
                   'grep', 'jq', 'find', 'test', '['}
if tokens and tokens[0] in PURE_READ_VERBS:
    print('PURE_READ')
    sys.exit(0)

# Default: anything that is not BARE_WRITER or PURE_READ is DENY.
print('DENY')
PYEOF
)

  case "$_bulk_decision" in
    BARE_WRITER)
      : # bare official-writer — /commit --bulk Step 5 invocation
      ;;
    PURE_READ)
      : # single pure-read inspection allowed
      ;;
    TOKENIZER_ERROR)
      echo "BLOCKED: bulk-commit-sentinel-write — Bash command failed tokenization (likely unterminated quote) — FORBIDDEN (fail-closed)" >&2
      echo "Command: $COMMAND" >&2
      echo "REASON: per task 20260526-053746 AC-08, the shlex tokenizer raised ValueError" >&2
      echo "        while parsing this command. Per codex iter-2 C11, the helper exhausts" >&2
      echo "        list(lex) inside try/except ValueError and fails CLOSED (deny, not allow)." >&2
      exit 2
      ;;
    DENY|*)
      echo "BLOCKED: bulk-commit-sentinel-write — Bash command references protected bulk sentinel path OR sentinel-writer script (write-bulk-commit-sentinel.py) in a compound or write context — FORBIDDEN" >&2
      echo "Command: $COMMAND" >&2
      echo "REASON: per task 20260526-053746 (fix for prior cycle 20260525-095242 ANSI-C bypass +" >&2
      echo "        over-blocking regressions), the compound/write detector now uses Python" >&2
      echo "        shlex.shlex(posix=True, punctuation_chars=True) tokenization. Any" >&2
      echo "        shell control structure (; && || | & |& \$() backtick <(...) >(...) <<HEREDOC" >&2
      echo "        newline shell-keyword), recursive shell (-c/-e/eval/source), variable assignment," >&2
      echo "        or write-surface operator (xargs, find -exec/-delete/-execdir/-ok/-okdir/-fprint*/-fls" >&2
      echo "        — including ANSI-C-quoted forms like \$'-fpr''int' which shlex reassembles," >&2
      echo "        > >> tee) causes the command to be denied. Only a single bare 'ls|stat|cat|file|wc|" >&2
      echo "        head|tail|grep|jq|find|test|[' invocation of the protected path (with NO compound" >&2
      echo "        shape) is allowed for inspection. The official sentinel-writer scripts/write-bulk-" >&2
      echo "        commit-sentinel.py is allowed ONLY as a bare invocation (STARTS-WITH match —" >&2
      echo "        comment-spoof and compound-with-script forms are denied)." >&2
      exit 2
      ;;
  esac
fi

# ── ABSOLUTE BAN: session_dirs.txt, happy-session-recovery.sh, happy-restart.sh ──
# On 2026-04-09, editing session_dirs.txt triggered full restore and killed all sessions.
# These files must NEVER be touched by Claude under any circumstances.

if echo "$COMMAND" | grep -qE 'session_dirs\.txt'; then
  echo "BLOCKED: session_dirs.txt is PERMANENTLY FORBIDDEN — never read, write, or reference this file" >&2
  echo "Command: $COMMAND" >&2
  echo "REASON: On 2026-04-09, editing session_dirs.txt triggered session-watcher full restore and killed ALL production sessions." >&2
  exit 2
fi

if echo "$COMMAND" | grep -qE 'happy-session-recovery'; then
  echo "BLOCKED: happy-session-recovery.sh is PERMANENTLY FORBIDDEN" >&2
  echo "Command: $COMMAND" >&2
  echo "REASON: This script manages critical session state. Only the user may run it manually." >&2
  exit 2
fi

if echo "$COMMAND" | grep -qE 'happy-restart'; then
  echo "BLOCKED: happy-restart.sh is PERMANENTLY FORBIDDEN" >&2
  echo "Command: $COMMAND" >&2
  echo "REASON: This script restarts daemons and can kill all sessions. Only the user may run it manually." >&2
  exit 2
fi

# ── Rules ─────────────────────────────────────────────────────────

# Block: sensitive file write via Bash redirect or as target
if echo "$COMMAND" | grep -qE '(>|>>)\s*\S*(\.env|credentials|secret|password)'; then
  echo "BLOCKED: Attempting to write to sensitive file via Bash" >&2
  echo "Command: $COMMAND" >&2
  echo "Edit sensitive files manually — never via AI-driven Bash redirection." >&2
  exit 2
fi
if echo "$COMMAND" | grep -qE '(\.env|credentials|secret|password)\S*\s*(>|>>)'; then
  echo "BLOCKED: Attempting to redirect from/to sensitive file via Bash" >&2
  echo "Command: $COMMAND" >&2
  echo "Edit sensitive files manually — never via AI-driven Bash redirection." >&2
  exit 2
fi

# Block: destructive disk operations — see the context-stripped variant below
# (moved past the COMMAND_CONTEXT_STRIPPED setup so the dd|mkfs|fdisk|shred verb
# rule can read the stripped view; Item A, dev-20260529-092512).

# Block: Docker daemon operations
if echo "$COMMAND" | grep -qE 'systemctl\s+(restart|stop|disable)\s+docker'; then
  echo "BLOCKED: Docker daemon operations are forbidden" >&2
  echo "Command: $COMMAND" >&2
  exit 2
fi

# Block: modifying Docker daemon config
if echo "$COMMAND" | grep -qE '(>|>>|tee|cp|mv|sed|awk)\s.*/etc/docker/daemon\.json'; then
  echo "BLOCKED: Modifying Docker daemon config is forbidden" >&2
  echo "Command: $COMMAND" >&2
  exit 2
fi

# Block: docker stop/restart/rm/kill on happy containers (unless ALL targets are dev-whitelisted)
if echo "$COMMAND" | grep -qE 'docker\s+(stop|restart|rm|kill)\s+.*happy'; then
  if ! check_docker_targets_all_dev "$COMMAND" "$DEV_CONTAINERS"; then
    echo "BLOCKED: Stopping/restarting production happy containers is forbidden" >&2
    echo "Command: $COMMAND" >&2
    echo "Hint: only $DEV_CONTAINERS is allowed." >&2
    exit 2
  fi
fi

# Block: docker-compose down, stop, and restart (destructive)
if echo "$COMMAND" | grep -qE 'docker.compose\s+(down|restart|stop)'; then
  echo "BLOCKED: docker-compose down/stop/restart is forbidden" >&2
  echo "Command: $COMMAND" >&2
  exit 2
fi

# Block: docker system prune -a (removes everything)
if echo "$COMMAND" | grep -qE 'docker\s+system\s+prune\s+-a'; then
  echo "BLOCKED: docker system prune -a is forbidden" >&2
  echo "Command: $COMMAND" >&2
  exit 2
fi

# COMMAND_CONTEXT_STRIPPED is initialised earlier (before Layer 1.F, dev-20260529-210759).

# Block: destructive disk operations (command-word-anchored on the stripped view)
# The verb is preserved verbatim by the stripper, so echo "dd if=..." erases to a
# no-match while a real dd/mkfs/fdisk/shred command word still fires (Item A).
if echo "$COMMAND_CONTEXT_STRIPPED" | grep -qE '^\s*(dd|mkfs|fdisk|shred)\b'; then
  echo "BLOCKED: Destructive disk operation detected" >&2
  echo "Command: $COMMAND" >&2
  exit 2
fi

# Block: generic process killers targeting services
if echo "$COMMAND_CONTEXT_STRIPPED" | grep -qE '(killall|pkill)\s+.*(happy|claude|docker)'; then
  echo "BLOCKED: Killing happy/claude/docker processes is forbidden" >&2
  echo "Command: $COMMAND" >&2
  exit 2
fi

# Block: kill with ANY signal targeting PIDs (kill -9, kill -TERM, kill -15, kill -HUP, etc.)
# Word-boundary anchor ensures "kill" is a command word, not a substring.
# Note: \s inside bracket expressions is NOT whitespace in grep -E; use [ \t] instead.
if echo "$COMMAND_CONTEXT_STRIPPED" | grep -qE '(^|[ \t;|&])(kill)[ \t]+-'; then
  echo "BLOCKED: kill with signals is forbidden — use graceful shutdown methods" >&2
  echo "Command: $COMMAND" >&2
  exit 2
fi

# Block: systemctl stop/restart/disable/enable/reload/kill/try-restart/reload-or-restart
# Verb set extended per c3-20260504-223115 R1 (8 verbs covering all daemon-state-disrupting
# systemctl operations). Targets covering `happy-daemon` are handled by Layer 1.A above
# (with the dedicated grant channel); this block fires for non-happy systemctl targets.
if echo "$COMMAND" | grep -qE 'systemctl\s+(stop|restart|disable|enable|reload|kill|try-restart|reload-or-restart)(\s+|\b)' \
   && ! echo "$COMMAND" | grep -qE 'happy-daemon'; then
  if ! check_systemctl_targets_all_dev "$COMMAND" "$DEV_SYSTEMD"; then
    echo "BLOCKED: systemctl stop/restart/disable/enable/reload/kill/try-restart/reload-or-restart is forbidden for production services" >&2
    echo "Command: $COMMAND" >&2
    echo "Hint: only $DEV_SYSTEMD is allowed (and happy-daemon-* is gated by Layer 1.A)." >&2
    exit 2
  fi
fi

# Block: rm/mv targeting workflow enforcement files (AF3+AF4 security fix)
# CRITICAL: first grep uses COMMAND_CONTEXT_STRIPPED (danger-token check); second grep
# uses raw COMMAND so that quoted paths like rm ".claude/todos/x" still match (the path
# would be stripped by context stripping, losing the workflow-path signal).
if echo "$COMMAND_CONTEXT_STRIPPED" | grep -qE '(rm|mv)\s' && echo "$COMMAND" | grep -qE '(workflow-[^/]*\.json|\.claude/todos/)'; then
  echo "BLOCKED: Deleting/moving workflow state files is forbidden" >&2
  echo "Command: $COMMAND" >&2
  echo "These files are required by the workflow enforcement system." >&2
  exit 2
fi

# Block: filesystem rm (but NOT docker rm, which is handled above)
# Pattern uses [ \t;|&(] so that rm appearing after a space (e.g. inside a -c payload
# that was unwrapped by context stripping) or inside $( ) is still detected.
# Note: \s inside bracket expressions is NOT whitespace in grep -E; use [ \t] instead.
if echo "$COMMAND_CONTEXT_STRIPPED" | grep -qE '(^|[ \t;|&(])rm\s' && ! echo "$COMMAND" | grep -qE 'docker\s+rm\s'; then
  echo "BLOCKED: rm is forbidden — delete files manually or ask the user" >&2
  echo "Command: $COMMAND" >&2
  exit 2
fi

# Block: source contamination — rsync/cp from external paths into /root/happy/packages/
# Only git (merge/cherry-pick) should bring code into production source
if echo "$COMMAND" | grep -qE '(rsync|cp)\s' && echo "$COMMAND" | grep -q '/root/happy/packages/'; then
  # Allow operations WITHIN /root/happy (e.g. cp within the repo)
  # Block operations FROM external paths (happy-dev, worktrees, /dev/shm, /tmp)
  if echo "$COMMAND" | grep -qE '(/root/happy-dev/|/dev/shm/|/tmp/|worktree).*(/root/happy/packages/)'; then
    echo "BLOCKED: Writing external code into /root/happy/packages/ is forbidden" >&2
    echo "Command: $COMMAND" >&2
    echo "Hint: Use git merge/cherry-pick to bring code into production. NEVER rsync/cp from dev branches or worktrees." >&2
    echo "Bug #59: A dev-overnight agent rsynced worktree code into /root/happy, causing 6 days of broken sidechain rendering." >&2
    exit 2
  fi
fi

# Block: docker build of Dockerfile.webapp without HAPPY_SERVER_URL
if echo "$COMMAND" | grep -qE 'docker\s+build' && echo "$COMMAND" | grep -q "Dockerfile.webapp"; then
  if ! echo "$COMMAND" | grep -q "HAPPY_SERVER_URL"; then
    echo "BLOCKED: docker build for Dockerfile.webapp MUST include --build-arg HAPPY_SERVER_URL=https://api-dev.life-ai.app" >&2
    echo "Without this, the web app defaults to api.cluster-fluster.com (WRONG)." >&2
    echo "Command: $COMMAND" >&2
    exit 2
  fi
  if echo "$COMMAND" | grep -qE '\-\-build-arg.*cluster-fluster|HAPPY_SERVER_URL=.*cluster-fluster'; then
    echo "BLOCKED: HAPPY_SERVER_URL must NOT be api.cluster-fluster.com" >&2
    echo "Command: $COMMAND" >&2
    exit 2
  fi
  if echo "$COMMAND" | grep -qE 'HAPPY_SERVER_URL=https://api\.life-ai\.app([^-]|$)'; then
    echo "BLOCKED: HAPPY_SERVER_URL=https://api.life-ai.app is the PRODUCTION URL. Dev builds must use https://api-dev.life-ai.app" >&2
    echo "Only web-prod builds targeting happy-app:message-fixes may use the production URL." >&2
    echo "Command: $COMMAND" >&2
    exit 2
  fi
fi

# Block: wrong dev deployment patterns (2026-05-24 incident)
# Pattern A: docker build targeting happy-app:dev but using the production HAPPY_SERVER_URL.
#   This bakes api.life-ai.app into the dev image, breaking happy-dev by pointing it at production.
# Pattern B: /root/happy/scripts/deploy.sh web-dev — that script's web-dev case uses the
#   production URL and builds from /root/happy, both of which violate CLAUDE.md rules.
# Neither pattern has a legitimate use. No IS_SUBAGENT bypass.
_wrong_dev_deploy=0
# Pattern A: docker build command targeting happy-app:dev with production HAPPY_SERVER_URL.
#   All three must be true: (1) actual docker build invocation, (2) production URL, (3) dev image tag.
#   Commands that merely quote or reference the URL in variable text do NOT trigger this.
if echo "$COMMAND" | grep -q '\bdocker\b' && \
   echo "$COMMAND" | grep -q '\bbuild\b' && \
   echo "$COMMAND" | grep -q 'HAPPY_SERVER_URL=https://api\.life-ai\.app' && \
   echo "$COMMAND" | grep -q 'happy-app:dev'; then
  _wrong_dev_deploy=1
fi
# Pattern B: invokes /root/happy/scripts/deploy.sh with web-dev argument
if echo "$COMMAND" | sed 's/&&/\n/g; s/||/\n/g; s/;/\n/g' | grep -qE '/root/happy/scripts/deploy\.sh.*\bweb-dev\b'; then
  _wrong_dev_deploy=1
fi
if [ "$_wrong_dev_deploy" = "1" ]; then
  echo "BLOCKED: Wrong dev deployment method." >&2
  echo "  Pattern A: HAPPY_SERVER_URL=https://api.life-ai.app must NOT be used for happy-app:dev (that's the production URL)." >&2
  echo "  Pattern B: /root/happy/scripts/deploy.sh web-dev is a production script with a hardcoded wrong URL." >&2
  echo "Use instead: bash scripts/deploy-services.sh web-dev   (from /dev/shm/dev-workspace/happy-dev)" >&2
  echo "         or: bash scripts/dev-overnight-build-deploy.sh <worktree-path> frontend" >&2
  echo "Command: $COMMAND" >&2
  exit 2
fi

# Block: direct SQL writes to production happy DB (INSERT/UPDATE/DELETE on Session, Account, etc.)
if echo "$COMMAND" | grep -qE 'docker\s+exec\s+happy-postgres\b' && echo "$COMMAND" | grep -qiE '\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER)\b'; then
  echo "BLOCKED: Direct SQL writes to production happy-postgres are forbidden" >&2
  echo "Command: $COMMAND" >&2
  echo "Hint: Only SELECT queries allowed. Use the app/API to modify data." >&2
  exit 2
fi
if echo "$COMMAND" | grep -qE 'psql.*happydb' && echo "$COMMAND" | grep -qiE '\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER)\b'; then
  echo "BLOCKED: Direct SQL writes to production happydb are forbidden" >&2
  echo "Command: $COMMAND" >&2
  echo "Hint: Only SELECT queries allowed. Use the app/API to modify data." >&2
  exit 2
fi

# Block: docker compose up/build (recreates containers, causes downtime)
# Exception: applio-* and happy-*-dev services are allowed IF no prod services mixed in
# Whitelist approach: extract ALL service names, every one must be dev/applio
if echo "$COMPOSE_COMMAND" | grep -qE 'docker.compose\s+(up|build)\s'; then
  compose_lines=$(echo "$COMPOSE_COMMAND" | grep -E 'docker.compose\s+(up|build)\s')
  # Extract service names (everything after up/build and flags like -d --no-deps)
  services=$(echo "$compose_lines" | sed -E 's/.*docker.compose\s+(up|build)\s+//' | tr ' ' '\n' | grep -v '^-' | grep -v '^$')
  if [ -z "$services" ]; then
    # No specific services = ALL services = forbidden
    echo "BLOCKED: docker compose up/build without specific service names is forbidden" >&2
    echo "Command: $COMMAND" >&2
    echo "Hint: specify services explicitly: docker compose up -d happy-web-dev happy-server-dev" >&2
    exit 2
  fi
  # Check every service name is in the whitelist
  blocked_service=""
  while IFS= read -r svc; do
    case "$svc" in
      applio-*|happy-web-dev|happy-server-dev|happy-server-dev:*|postgres-dev|redis-dev) ;; # allowed
      *) blocked_service="$svc" ; break ;;
    esac
  done <<< "$services"
  if [ -n "$blocked_service" ]; then
    echo "BLOCKED: service '$blocked_service' is not a dev service — cannot compose up/build production services" >&2
    echo "Command: $COMMAND" >&2
    echo "Hint: only these services allowed: applio-*, happy-web-dev, happy-server-dev, postgres-dev, redis-dev" >&2
    exit 2
  fi
fi

# Block: curl/wget POST to happy-server API that creates/modifies sessions
if echo "$COMMAND" | grep -qE '(curl|wget).*(/v1/sessions|/v1/machines|/session-started|/spawn-session)' && echo "$COMMAND" | grep -qiE '(-X\s*POST|-X\s*PUT|-X\s*PATCH|-X\s*DELETE|-d\s|--data)'; then
  echo "BLOCKED: Session creation via API is forbidden. Use the UI flow instead." >&2
  echo "Command: $COMMAND" >&2
  echo "Hint: Open https://dev.life-ai.app -> click Start New Session -> type message -> send. NEVER use curl/API to create sessions." >&2
  exit 2
fi

# Block: curl/wget to production API (localhost:3000 or api.life-ai.app) — all methods
if echo "$COMMAND" | grep -qE '(curl|wget).*(localhost:3000|127\.0\.0\.1:3000|api\.life-ai\.app)' && \
   ! echo "$COMMAND" | grep -qE 'api-dev\.life-ai\.app'; then
  echo "BLOCKED: Accessing production API is FORBIDDEN from dev environment" >&2
  echo "Command: $COMMAND" >&2
  echo "Hint: Use localhost:3005 (dev API) or api-dev.life-ai.app instead." >&2
  exit 2
fi

# ── ABSOLUTE ISOLATION: happy-dev must NEVER touch production happy ──────────

# Block: npm install -g (strip comments first to avoid false positives)
CMD_NO_COMMENTS=$(echo "$COMMAND" | sed 's/#.*$//')
if echo "$CMD_NO_COMMENTS" | grep -qE 'npm\s+(install|i)\s+.*(-g|--global)' || echo "$CMD_NO_COMMENTS" | grep -qE 'npm\s+(install|i)\s+-g'; then
  echo "BLOCKED: npm install -g is FORBIDDEN from this environment" >&2
  echo "Command: $COMMAND" >&2
  echo "REASON: On 2026-04-04, npm install -g from a worktree replaced the global happy binary," >&2
  echo "triggered auto-upgrade, and killed ALL production sessions. NEVER do this again." >&2
  echo "The global CLI must only be installed from /root/happy by the user manually." >&2
  exit 2
fi

# Block: direct invocation of /usr/bin/happy or bare 'happy' CLI command
# (prevents triggering auto-upgrade version mismatch detection)
if echo "$COMMAND" | grep -qE '(^|[;&|]\s*)/usr/bin/happy([^-]|$)' || echo "$COMMAND" | grep -qE '(^|[;&|]\s*)happy\s+(daemon|--version|auth)\b'; then
  echo "BLOCKED: Direct invocation of the global happy CLI is FORBIDDEN" >&2
  echo "Command: $COMMAND" >&2
  echo "REASON: The global /usr/bin/happy is shared by ALL daemons. Invoking it can trigger" >&2
  echo "auto-upgrade and kill production sessions. Use node with full path to dist instead." >&2
  exit 2
fi

# Block: kill on PIDs that aren't verified dev processes
# (prevents accidentally killing production session processes)
# Uses COMMAND_CONTEXT_STRIPPED: kill is already in DANGER_COMMANDS, so its args are
# EXPOSED (unquoted) by the stripper — kill "1234" -> kill 1234 still matches, while
# echo "kill 1234" -> echo "" no longer false-positives (Item A, mirrors the kill -sig rule).
if echo "$COMMAND_CONTEXT_STRIPPED" | grep -qE '(^|[;&|]\s*)kill\s+[0-9]'; then
  echo "BLOCKED: kill with PIDs is FORBIDDEN — verify target is dev before killing" >&2
  echo "Command: $COMMAND" >&2
  echo "REASON: On 2026-04-04, killing dev session processes cascaded to production." >&2
  echo "Use systemctl restart happy-daemon-dev or daemon HTTP /stop instead." >&2
  exit 2
fi

# Block: WRITING to /usr/lib/node_modules/happy or /usr/bin/happy (reading is OK)
# Allow /usr/bin/happy-dev (dev binary) but block /usr/bin/happy (production binary)
if echo "$COMMAND" | grep -qE '(ln|cp|mv|unlink|tee)\s.*(/usr/lib/node_modules/happy|/usr/bin/happy)' && \
   ! echo "$COMMAND" | grep -qE '/usr/bin/happy-dev'; then
  echo "BLOCKED: Modifying global happy binary/modules is FORBIDDEN" >&2
  echo "Command: $COMMAND" >&2
  exit 2
fi

# Block: happy-daemon-dev service must NEVER use /usr/bin/happy (production binary)
# Allow /usr/bin/happy-dev but block /usr/bin/happy
if echo "$COMMAND" | grep -q 'happy-daemon-dev' && echo "$COMMAND" | grep -qE '/usr/bin/happy([^-]|$)'; then
  echo "BLOCKED: happy-daemon-dev must NEVER reference /usr/bin/happy (production binary)" >&2
  echo "Command: $COMMAND" >&2
  echo "REASON: Dev daemon must use /root/happy-dev/packages/happy-cli/dist/index.mjs directly." >&2
  echo "Using /usr/bin/happy causes dev daemon to run production code, ignoring all dev fixes." >&2
  exit 2
fi

# ── Dangerous git operations (2026-04-19 incident prevention) ──────────────
# On 2026-04-19 23:02:22, a dev subagent ran:
#     git stash && cd packages/happy-app && git checkout 925f5960 -- .
# The `-- .` wide-path checkout overwrote the entire happy-app directory with
# 3-27 baseline content, erasing 17 days of UI work. The stash was treated as
# a throwaway buffer but then failed to pop cleanly, leaving the worktree in a
# silently-regressed state. The subagent reported "something happened" as if
# it were an accident, concealing that it ran the destructive command itself.
# Block these three patterns globally — main agent AND subagents.

# Block: git stash (destructive forms only — list/show/pop/apply/drop/clear/branch are safe)
# V4: extended to also cover -u/--include-untracked/-a/--all variants (which include untracked/ignored files)
if echo "$COMMAND" | grep -qE 'git\s+stash\s+(push|save|create|store|-u|--include-untracked|-a|--all)\b' || \
   echo "$COMMAND" | grep -qE 'git\s+stash\s+-[ua]+\b'; then
  echo "BLOCKED: 'git stash push/save/create/store/-u/--all' requires explicit user approval" >&2
  echo "Command: $COMMAND" >&2
  echo "REASON: On 2026-04-19, a dev subagent used 'git stash' as a throwaway buffer" >&2
  echo "before running a destructive 'git checkout <hash> -- .', silently erasing 17 days" >&2
  echo "of UI work. Stash+checkout is a known-dangerous combo in subagent hands." >&2
  echo "-u/--include-untracked/-a/--all forms include untracked/ignored files — more destructive." >&2
  echo "Tell the user what you want to do and ask them to run it, or use commit/branch." >&2
  exit 2
fi
if echo "$COMMAND" | grep -qE 'git\s+stash\s*($|[;&|])'; then
  echo "BLOCKED: bare 'git stash' (implicit push) requires explicit user approval" >&2
  echo "Command: $COMMAND" >&2
  echo "REASON: See 2026-04-19 incident — stash is often paired with destructive checkout." >&2
  echo "Safe stash subcommands are exempt: list, show, pop, apply, drop, clear, branch." >&2
  exit 2
fi

# Block: git checkout <ref> -- . or -- * or -- <dir>/
# Wide-path checkout from a ref overwrites the entire subtree with historical content.
# Allowed: 'git checkout <ref> -- path/to/specific-file.ts' (single file), 'git checkout <branch>' (branch switch).
if echo "$COMMAND" | grep -qE 'git\s+checkout\s+\S+\s+--\s+(\.|\*|[^ ]+/)\s*($|[;&|])'; then
  echo "BLOCKED: 'git checkout <ref> -- .' / '-- *' / '-- dir/' requires explicit user approval" >&2
  echo "Command: $COMMAND" >&2
  echo "REASON: On 2026-04-19, a dev subagent ran 'git checkout 925f5960 -- .' inside" >&2
  echo "packages/happy-app/, overwriting 17 days of UI development with 3-27 baseline." >&2
  echo "Wide-path checkout from a commit is a blunt-force destructive operation." >&2
  echo "Allowed: 'git checkout <ref> -- path/to/specific-file.ts' (single file)." >&2
  echo "If you genuinely need a subtree restore, tell the user what you need and why." >&2
  exit 2
fi

# Block: git restore --source=<ref> -- . / -- */ -- <dir>/  (V6)
# Modern equivalent of 'git checkout <ref> -- .' (git 2.23+) — overwrites working tree with historical content.
# Two-condition approach (order-independent): command must contain BOTH a source flag AND a wide-path.
# Covers all four syntaxes: --source=X, --source X, -s=X, -s X.
# Allowed: 'git restore -- myfile.ts' (no --source, no overwrite), 'git restore --staged -- file' (index-only),
#          'git restore --source=HEAD -- specific-file.ts' (specific file, not wide-path).
if echo "$COMMAND" | grep -qE 'git\s+restore\b' && \
   echo "$COMMAND" | grep -qE -- '(--source\b|-s\b)' && \
   echo "$COMMAND" | grep -qE -- '--\s+(\.|\*|[^ /]+/)\s*($|[;&|])'; then
  echo "BLOCKED: 'git restore --source=<ref> -- .' / '-- *' / '-- dir/' requires explicit user approval" >&2
  echo "Command: $COMMAND" >&2
  echo "REASON: 'git restore --source=<ref> -- .' is the modern equivalent of" >&2
  echo "'git checkout <ref> -- .' (git 2.23+). It overwrites the working tree with historical" >&2
  echo "content — same blunt-force destructive operation that erased 17 days of UI work on 2026-04-19." >&2
  echo "Allowed: 'git restore -- path/to/specific-file.ts' (no --source, or specific file)." >&2
  echo "If you genuinely need a subtree restore, tell the user what you need and why." >&2
  exit 2
fi

# Block: every git reset --hard form. Shared-repo policy forbids reset-like cleanup in agent flow.
GIT_GLOBAL_OPT_RE='([[:space:]]+(-[Cc][[:space:]]+[^[:space:];|&]+|-[Cc][^[:space:];|&]+|--(git-dir|work-tree|namespace|exec-path|super-prefix|config-env)(=[^[:space:];|&]+|[[:space:]]+[^[:space:];|&]+)|--(bare|no-pager|paginate|no-replace-objects|literal-pathspecs|glob-pathspecs|noglob-pathspecs|icase-pathspecs|no-optional-locks)|-[pP]))*'
GIT_CMD_RE='(^|[[:space:];&|()`])git'"$GIT_GLOBAL_OPT_RE"'[[:space:]]+'
if echo "$COMMAND" | grep -qE "${GIT_CMD_RE}reset[[:space:]]+([^;|&]*[[:space:]]+)?--hard\b"; then
  echo "BLOCKED: 'git reset --hard' is forbidden in agent flow" >&2
  echo "Command: $COMMAND" >&2
  echo "REASON: shared-repo policy requires non-destructive recovery; hard reset can discard another session's work or index state." >&2
  echo "Use semantic commits, backup recovery refs, or ask the user for a human-run recovery operation." >&2
  exit 2
fi

# Block: force/delete branch publication and direct ref mutation surfaces.
if echo "$COMMAND" | grep -qE "${GIT_CMD_RE}push\b" && \
   echo "$COMMAND" | grep -qE '(^|[[:space:]])(--force|-f|--force-with-lease(=[^[:space:]]+)?|--delete|-d|--mirror)([[:space:]]|$)|[[:space:]]\+[^[:space:]]|[[:space:]]:[^[:space:]]'; then
  echo "BLOCKED: force/delete/ref-rewrite push is forbidden in agent flow" >&2
  echo "Command: $COMMAND" >&2
  echo "REASON: policy allows normal /push branch publication and backup-only recovery refs; force/delete/ref-rewrite pushes can lose remote work." >&2
  exit 2
fi
if echo "$COMMAND" | grep -qE "${GIT_CMD_RE}(update-ref\b|branch[[:space:]]+(-[fDdMm]+|--delete|--force|--move)\b|symbolic-ref([[:space:]]+-m([[:space:]]+[^[:space:];|&]+|[^[:space:];|&]*))*[[:space:]]+HEAD[[:space:]]+refs/)"; then
  echo "BLOCKED: direct git ref mutation is forbidden in agent flow" >&2
  echo "Command: $COMMAND" >&2
  echo "REASON: branch movement must go through the expected-parent CAS wrapper; branch delete/force/update-ref is not agent-accessible." >&2
  exit 2
fi

# Block: subagent-initiated git history mutation (2026-04-23 incident)
# Subagents have weak context and cannot reliably know whether the user has consented.
# All git history changes by subagents must be surfaced to the user instead.
# IS_SUBAGENT is set at the top of the script (after PYTHON_BIN resolution); no re-parse needed.
if [ "$IS_SUBAGENT" = "1" ]; then
  # /do bypass (2026-04-25): user has explicitly consented via /do — allow subagent history mutation
  SID=$(echo "$INPUT" | "$PYTHON_BIN" -c "import json,sys; d=json.load(sys.stdin); print(d.get('session_id',''))" 2>/dev/null)
  if [ -n "$SID" ] && [ -e "/tmp/claude-orchestrator-consent-${SID}.flag" ]; then
    exit 0
  fi
  # Narrowed (2026-05-14): commit|merge|push are fully covered by
  # pretool-git-privilege-guard.py (canonical layer). revert|cherry-pick|rebase
  # are NOT covered there, so they remain in this layer.
  if echo "$COMMAND" | grep -qE 'git[[:space:]]+(revert|cherry-pick|rebase)([[:space:]]|$)'; then
    echo "BLOCKED: Subagent-initiated git history mutation is FORBIDDEN (revert|cherry-pick|rebase)" >&2
    echo "Command: $COMMAND" >&2
    echo "Subagents must NEVER mutate git history. Tell the user what you want done" >&2
    echo "and ask them to run the command themselves." >&2
    echo "Allowed git verbs for subagents: status, log, show, diff, blame, ls-tree, ls-files, branch (read-only), worktree list." >&2
    echo "(commit|merge|push are blocked by pretool-git-privilege-guard.py)" >&2
    exit 2
  fi
  # Branch -D / -d deletion is covered by the canonical block at line ~1046
  # (regex -[fDdMm]+) AND by pretool-git-privilege-guard.py:287. The previous
  # 'git branch -D ' substring check here was a duplicate and has been removed.
fi

# Block: git revert <commit-hash> or git revert <ref>^ or git revert <ref>~N or git revert <ref>@{N}
# V5: broadened from HEAD-only anchor to \S+ so any ref (HEAD, master, main, branch, tag)
# with a modifier (caret, tilde, reflog, hash) is blocked.
# Reverting a non-bare-HEAD commit can undo deliberate user work.
# Safe: 'git revert HEAD' ONLY (bare — no caret, no tilde, no reflog, no branch-ref modifier).
# All other revert forms are blocked.
if echo "$COMMAND" | grep -qE 'git\s+revert\s+'; then
  # Block hex hashes (7+ chars)
  # Block caret form: <ref>^ or <ref>^^ (e.g., HEAD^, master^, HEAD^^)
  # Block tilde form: <ref>~ or <ref>~N (e.g., HEAD~, HEAD~1, master~2)
  # Block reflog form: <ref>@{N} (e.g., HEAD@{1})
  # Intermediate group (\S+\s+)* allows flags-before-ref (e.g., git revert --no-edit HEAD^)
  # Note: \b after ^/~/} is omitted because those characters are non-word — \b requires
  # a word-char transition and would fail to match at end-of-string or before whitespace.
  if echo "$COMMAND" | grep -qE 'git\s+revert\s+(\S+\s+)*[0-9a-f]{7,40}\b' || \
     echo "$COMMAND" | grep -qE 'git\s+revert\s+(\S+\s+)*\S+\^+' || \
     echo "$COMMAND" | grep -qE 'git\s+revert\s+(\S+\s+)*\S+~[0-9]*' || \
     echo "$COMMAND" | grep -qE 'git\s+revert\s+(\S+\s+)*\S+@\{[0-9]+\}'; then
    echo "BLOCKED: 'git revert' with any ref modifier (caret/tilde/reflog/hash) requires explicit user approval" >&2
    echo "Command: $COMMAND" >&2
    echo "REASON: On 2026-04-23, a dev subagent ran 'git revert 1204d62' which undid a user-approved" >&2
    echo "feature commit (the /spec simplification the user had explicitly endorsed), restoring an" >&2
    echo "unwanted 5-step interview state. The user had explicitly forbidden full revert in chat." >&2
    echo "Reverting historical commits without user authorization is destructive — it overrides" >&2
    echo "deliberate work that may have been thoroughly reviewed and accepted." >&2
    # V5 comment fix: Only bare 'git revert HEAD' (no suffix) is safe. All other forms blocked.
    echo "Safe: 'git revert HEAD' only (bare — no caret, no tilde, no reflog, no branch-ref)." >&2
    echo "All other revert forms (HEAD^, HEAD~N, HEAD@{N}, master^, <hash>) are blocked." >&2
    echo "If you genuinely need to revert a historical commit, tell the user the hash and the" >&2
    echo "rationale, and ask them to run it manually." >&2
    exit 2
  fi
fi

exit 0
