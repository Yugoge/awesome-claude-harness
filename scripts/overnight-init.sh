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
# WHAT IT DOES
#   1. renders the verbatim user-requirement document from the record and hands
#      it, with the session id and the flags the record asks for (e2e always,
#      codex when codex_required), to the registry's one producer:
#      hooks/prompt-workflow.py's `arm-registry`, the same function that arms a
#      /dev registry (one sentinel per agent role, the requirement document,
#      the flags through write-enforce-flag.sh)
#   2. resolves the spec artifacts (spec id / cp dir / views dir)
#   3. prints the values the actor binds
#
# WHO RUNS IT, AND IN WHICH MODE
# The MUTATING form is run HARNESS-SIDE by scripts/create-overnight-state.sh
# against its TEMPORARY record, BEFORE the atomic publish and therefore BEFORE
# the isolation boundary is armed. The ACTOR runs --verify-only, which writes
# nothing and only prints the values it binds: under `/dev-overnight --worktree`
# the guard RO-binds the whole main root for every Bash command the actor
# issues, and the registry lives under that root.
#
# Usage: overnight-init.sh --state-file <path-to-overnight-state.json>
#        overnight-init.sh --session-id <sid> [--project-dir <dir>]
#        overnight-init.sh --verify-only --state-file <path>   # writes nothing
# Output: KEY=VALUE lines on stdout, then OVERNIGHT_INIT_OK / OVERNIGHT_INIT_FAIL.
# Exit: 0 = success, 1 = error (caller must abort).
set -euo pipefail

STATE_FILE=""
SESSION_ID=""
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-}"
VERIFY_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --state-file)  STATE_FILE="$2"; shift 2 ;;
    --session-id)  SESSION_ID="$2"; shift 2 ;;
    --project-dir) PROJECT_DIR="$2"; shift 2 ;;
    --verify-only) VERIFY_ONLY=1; shift ;;
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

# The session id becomes a path component of every path below, so it is
# validated before any path is built from it — same shape check write-qa-mode.sh
# and write-enforce-flag.sh apply.
[[ "$SESSION_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] \
  || _die "session id contains unsafe characters: $SESSION_ID"

PROJECT_ROOT="$(cd "$PROJECT_DIR" && pwd -P)"
REGISTRY_DIR="$PROJECT_ROOT/.claude/dev-registry/$SESSION_ID"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"

CODEX_REQUIRED=false
if [[ -n "$STATE_FILE" ]]; then
  CODEX_REQUIRED="$(jq -r '.codex_required // false' "$STATE_FILE")"
fi

# --- spec-artifact resolution -------------------------------------------------
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

# --- verbatim user-requirement document and the registry ----------------------
# Source-of-truth anchor every subagent reads before any derived context. Written
# from the record's own `focus` field, never from a re-typed paraphrase.
# PLACEMENT IS DELIBERATE (main root, not the isolated working root). Dispatched
# subagents run confined to worktree_path, so writing this under the main
# checkout looks like a containment conflict. It is not: the boundary is
# --ro-bind / / (guard _build_bwrap_argv), so the ENTIRE host stays READABLE and
# only writes are refused, and every dispatch template substitutes the resolved
# ABSOLUTE $REQUIREMENT_DOC rather than a working-root-relative path. Nothing
# rewrites the document after initialization, so the write side never binds.
REQUIREMENT_DOC="$PROJECT_ROOT/docs/dev/user-requirement-$SESSION_ID.md"
FOCUS=""
[[ -n "$STATE_FILE" ]] && FOCUS="$(jq -r '.focus // empty' "$STATE_FILE")"
_render_requirement_doc() {
  printf '%s\n' "$FOCUS"
  if [[ -n "$USER_SPEC_PATH" ]]; then
    printf '\nUser spec path: %s\n' "$USER_SPEC_PATH"
    SPEC_ABS="$USER_SPEC_PATH"
    [[ "$SPEC_ABS" != /* ]] && SPEC_ABS="$PROJECT_ROOT/$USER_SPEC_PATH"
    if [[ -f "$SPEC_ABS" ]]; then
      printf '\nSection 5 (User Acceptance Criterion):\n'
      # Verbatim byte-slice from the Section-5 level-2 heading up to the NEXT
      # level-2 heading, so the `### 5.x` subsections stay included. Both
      # heading dialects in use are accepted: "## Section 5: ..." and "## 5. ...".
      # Emits nothing when the spec has no Section 5 — an empty slice is honest,
      # a guessed substitute is not. LC_ALL=C pins [[:space:]] to the ASCII set,
      # so the slice does not depend on the host's locale.
      LC_ALL=C awk '
        /^##[[:space:]]/ && !/^###/ {
          if (inside) exit
          if ($0 ~ /^##[[:space:]]+(Section[[:space:]]+)?5([:.[:space:]]|$)/) { inside = 1 }
        }
        inside { print }
      ' "$SPEC_ABS"
    fi
  fi
}
if [[ "$VERIFY_ONLY" != "1" ]]; then
  INIT_PYTHON="${CLAUDE_HOME:-$SCRIPT_DIR/..}/venv/bin/python3"
  [[ -x "$INIT_PYTHON" ]] || INIT_PYTHON="$(command -v python3 || true)"
  [[ -n "$INIT_PYTHON" ]] || _die "no python3 interpreter available to arm the registry"
  ARM_ARGS=(arm-registry --name "$SESSION_ID" --source-command dev-overnight
            --project-dir "$PROJECT_ROOT" --flag e2e)
  [[ "$CODEX_REQUIRED" == "true" ]] && ARM_ARGS+=(--flag codex)
  _render_requirement_doc | "$INIT_PYTHON" "$SCRIPT_DIR/../hooks/prompt-workflow.py" "${ARM_ARGS[@]}" \
    || _die "the registry could not be armed: $REGISTRY_DIR"
fi

# --- summary ------------------------------------------------------------------
echo "SESSION_ID=$SESSION_ID"
echo "PROJECT_ROOT=$PROJECT_ROOT"
echo "REGISTRY_DIR=$REGISTRY_DIR"
echo "CODEX_REQUIRED=$CODEX_REQUIRED"
echo "SPEC_MODE=$SPEC_MODE"
echo "USER_SPEC_PATH=$USER_SPEC_PATH"
echo "SPEC_ID=$SPEC_ID"
echo "CP_DIR=$CP_DIR"
echo "VIEWS_DIR=$VIEWS_DIR"
echo "REQUIREMENT_DOC=$REQUIREMENT_DOC"
echo "OVERNIGHT_INIT_OK"
