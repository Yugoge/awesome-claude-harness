#!/usr/bin/env bash
# overnight-init.sh — perform the ENTIRE /dev-overnight Step 1 initialization in
# ONE invocation, and emit a single machine-readable summary block.
#
# WHY THIS EXISTS
# Step 1 used to cost ~25 separate tool calls: one mkdir, ~20 per-agent sentinel
# writes, two enforcement-flag scripts, a spec-artifact resolution, and a
# requirement-document heredoc. A session that hits its usage ceiling during
# initialization never reaches PM Plan and produces nothing — the exact failure
# that motivated this script (session ae7f1efe, 2026-08-08: hung with
# "Step 1: Create worktree" still in_progress, cycle_count 0). Collapsing the
# fan-out into one process removes the per-call overhead entirely.
#
# WHAT IT DOES (all idempotent — safe to re-run on every continuation cycle)
#   1. dev-registry dir + one sentinel JSON per agent type
#   2. e2e enforcement flag, plus codex when the record asks for it
#   3. spec-artifact resolution (spec id / cp dir / views dir)
#   4. the verbatim user-requirement document
#
# Usage: overnight-init.sh --state-file <path-to-overnight-state.json>
#        overnight-init.sh --session-id <sid> [--project-dir <dir>]
# Output: KEY=VALUE lines on stdout, then OVERNIGHT_INIT_OK / OVERNIGHT_INIT_FAIL.
# Exit: 0 = success, 1 = error (caller must abort).
set -euo pipefail

STATE_FILE=""
SESSION_ID=""
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --state-file)  STATE_FILE="$2"; shift 2 ;;
    --session-id)  SESSION_ID="$2"; shift 2 ;;
    --project-dir) PROJECT_DIR="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

_die() { echo "ERROR: $*" >&2; echo "OVERNIGHT_INIT_FAIL"; exit 1; }

# --- Locate the state file / session id --------------------------------------
if [[ -z "$STATE_FILE" && -z "$SESSION_ID" ]]; then
  _die "one of --state-file or --session-id is required"
fi
if [[ -n "$STATE_FILE" ]]; then
  [[ -f "$STATE_FILE" ]] || _die "state file not found: $STATE_FILE"
  SESSION_ID="$(jq -r '.session_id // empty' "$STATE_FILE")"
  [[ -n "$SESSION_ID" ]] || _die "state file has no session_id: $STATE_FILE"
  [[ -n "$PROJECT_DIR" ]] || PROJECT_DIR="$(jq -r '.main_root // empty' "$STATE_FILE")"
fi
[[ -n "$PROJECT_DIR" ]] || _die "cannot determine project dir; pass --project-dir or set CLAUDE_PROJECT_DIR"
[[ -d "$PROJECT_DIR" ]] || _die "project dir does not exist: $PROJECT_DIR"

# The session id becomes a path component in every target below, so it is
# validated before any path is built from it — same shape check write-qa-mode.sh
# and write-enforce-flag.sh apply.
[[ "$SESSION_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] \
  || _die "session id contains unsafe characters: $SESSION_ID"

PROJECT_ROOT="$(cd "$PROJECT_DIR" && pwd -P)"

# --- Write confinement (fail-closed) -----------------------------------------
# The PreToolUse worktree guard scans the Bash TOOL command line
# (hooks/pretool-overnight-hook-guard.py:586-596 via
# hooks/lib/bash_write_targets.py). Writes performed INSIDE this script are
# invisible to that scan, so batching them here would otherwise trade ~25 guarded
# writes for ~25 unguarded ones. This script therefore re-imposes the boundary
# itself: every target is canonicalized (with its symlinks resolved) and must
# land under PROJECT_ROOT, or the whole init fails. The check runs on the
# resolved PARENT directory, because the target file itself usually does not
# exist yet and a symlinked parent is the escape that matters.
_confined() {
  local target="$1" parent resolved
  parent="$(dirname "$target")"
  mkdir -p "$parent" 2>/dev/null || return 1
  resolved="$(cd "$parent" && pwd -P)" || return 1
  case "$resolved" in
    "$PROJECT_ROOT"|"$PROJECT_ROOT"/*) return 0 ;;
  esac
  return 1
}
_write_confined() {
  # $1 = target path, stdin = content
  local target="$1"
  _confined "$target" || _die "refusing to write outside the project root: $target (resolved parent escapes $PROJECT_ROOT)"
  cat > "$target" || _die "failed to write $target"
}

REGISTRY_DIR="$PROJECT_ROOT/.claude/dev-registry/$SESSION_ID"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"

# --- 1. dev-registry sentinels ------------------------------------------------
# The agent list is READ from hooks/pretool-cp-checkin.py CP_AGENTS rather than
# duplicated here. That file already declares itself the single source of truth
# ("Dev-registry sentinel agent names must match CP_AGENTS"), and a second copy
# would drift silently — a missing sentinel makes pretool-subagent-code-block.py
# fall open for that agent, which is a security regression that produces no
# error. Parsed with ast so the module is never imported (no side effects).
AGENT_LIST="$(python3 - "$SCRIPT_DIR/../hooks/pretool-cp-checkin.py" <<'PYEOF' || true
import ast, sys
src = open(sys.argv[1], encoding='utf-8').read()
tree = ast.parse(src)
for node in tree.body:
    if not isinstance(node, ast.Assign):
        continue
    for tgt in node.targets:
        if isinstance(tgt, ast.Name) and tgt.id == 'CP_AGENTS':
            try:
                names = ast.literal_eval(node.value)
            except ValueError:
                sys.exit(1)
            print('\n'.join(sorted(str(n) for n in names)))
            sys.exit(0)
sys.exit(1)
PYEOF
)"
[[ -n "$AGENT_LIST" ]] \
  || _die "could not read CP_AGENTS from hooks/pretool-cp-checkin.py; refusing to guess the agent list (a missing sentinel silently disables code-write enforcement for that agent)"

mkdir -p "$REGISTRY_DIR" || _die "failed to create $REGISTRY_DIR"
SENTINEL_COUNT=0
while IFS= read -r agent; do
  [[ -n "$agent" ]] || continue
  printf '{"agent_type": "%s", "session_id": "%s"}\n' "$agent" "$SESSION_ID" \
    | _write_confined "$REGISTRY_DIR/$agent.json"
  SENTINEL_COUNT=$((SENTINEL_COUNT + 1))
done <<< "$AGENT_LIST"

# --- 2. enforcement flags -----------------------------------------------------
# E2E is unconditional; codex is opt-in via the record. Both are written by a
# single write-enforce-flag.sh invocation.
CODEX_REQUIRED=false
if [[ -n "$STATE_FILE" ]]; then
  CODEX_REQUIRED="$(jq -r '.codex_required // false' "$STATE_FILE")"
fi
ENFORCE_ARGS=(--source-command dev-overnight --session-id "$SESSION_ID" --flag e2e)
[[ "$CODEX_REQUIRED" == "true" ]] && ENFORCE_ARGS+=(--flag codex)
CLAUDE_PROJECT_DIR="$PROJECT_ROOT" bash "$SCRIPT_DIR/write-enforce-flag.sh" "${ENFORCE_ARGS[@]}" >/dev/null \
  || _die "enforcement flag write failed"

# --- 3. spec-artifact resolution ---------------------------------------------
SPEC_MODE="autonomous"
USER_SPEC_PATH=""
SPEC_ID=""
CP_DIR=""
VIEWS_DIR=""
if [[ -n "$STATE_FILE" ]]; then
  SPEC_MODE="$(jq -r '.spec_mode // "autonomous"' "$STATE_FILE")"
  USER_SPEC_PATH="$(jq -r '.user_spec_path // empty' "$STATE_FILE")"
  [[ "$USER_SPEC_PATH" == "null" ]] && USER_SPEC_PATH=""
fi
if [[ -n "$USER_SPEC_PATH" ]]; then
  RESOLVER="$SCRIPT_DIR/resolve-spec-artifacts.py"
  if [[ -x "$RESOLVER" ]]; then
    # Resolution failure is FATAL, matching the previous inline behaviour: a
    # present-but-invalid split would otherwise drop the session to monolith
    # mode without saying so.
    RESOLVED_JSON="$("$RESOLVER" --spec-path "$USER_SPEC_PATH" --project-dir "$PROJECT_ROOT" 2>&1)" \
      || _die "spec-artifact resolution failed for $USER_SPEC_PATH: $RESOLVED_JSON"
    SPEC_ID="$(jq -r '.artifact_id // empty'  <<<"$RESOLVED_JSON")"
    CP_DIR="$(jq -r '.cp_dir // empty'        <<<"$RESOLVED_JSON")"
    VIEWS_DIR="$(jq -r '.views_dir // empty'  <<<"$RESOLVED_JSON")"
    # A cp_dir the resolver named but that is not on disk is not a usable
    # handoff; drop both so the caller emits no SECOND ACTION lines for it.
    if [[ -n "$CP_DIR" && ! -d "$PROJECT_ROOT/$CP_DIR" ]]; then
      SPEC_ID=""; CP_DIR=""
    fi
  fi
fi

# --- 4. verbatim user-requirement document -----------------------------------
# Source-of-truth anchor every subagent reads before any derived context. Written
# from the record's own `focus` field, never from a re-typed paraphrase.
REQUIREMENT_DOC="$PROJECT_ROOT/docs/dev/user-requirement-$SESSION_ID.md"
FOCUS=""
[[ -n "$STATE_FILE" ]] && FOCUS="$(jq -r '.focus // empty' "$STATE_FILE")"
{
  printf '%s\n' "$FOCUS"
  if [[ -n "$USER_SPEC_PATH" ]]; then
    printf '\nUser spec path: %s\n' "$USER_SPEC_PATH"
    SPEC_ABS="$USER_SPEC_PATH"
    [[ "$SPEC_ABS" != /* ]] && SPEC_ABS="$PROJECT_ROOT/$USER_SPEC_PATH"
    if [[ -f "$SPEC_ABS" ]]; then
      printf '\nSection 5 (User Acceptance Criterion):\n'
      # Verbatim byte-slice from the "## 5" heading to the next same-level
      # heading. Emits nothing when the spec has no Section 5 rather than
      # guessing at a substitute.
      awk '/^##[[:space:]]*5[.[:space:]]/{f=1} f&&/^##[[:space:]]*[^5]/&&!/^##[[:space:]]*5/{if(seen)exit} f{print;seen=1}' "$SPEC_ABS"
    fi
  fi
} | _write_confined "$REQUIREMENT_DOC"

# --- summary ------------------------------------------------------------------
echo "SESSION_ID=$SESSION_ID"
echo "PROJECT_ROOT=$PROJECT_ROOT"
echo "REGISTRY_DIR=$REGISTRY_DIR"
echo "SENTINELS_WRITTEN=$SENTINEL_COUNT"
echo "CODEX_REQUIRED=$CODEX_REQUIRED"
echo "SPEC_MODE=$SPEC_MODE"
echo "USER_SPEC_PATH=$USER_SPEC_PATH"
echo "SPEC_ID=$SPEC_ID"
echo "CP_DIR=$CP_DIR"
echo "VIEWS_DIR=$VIEWS_DIR"
echo "REQUIREMENT_DOC=$REQUIREMENT_DOC"
echo "OVERNIGHT_INIT_OK"
