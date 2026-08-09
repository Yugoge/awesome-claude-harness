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
# WHO RUNS IT, AND IN WHICH MODE
# The MUTATING form is run HARNESS-SIDE by scripts/create-overnight-state.sh
# against its TEMPORARY record, BEFORE the atomic publish and therefore BEFORE
# the isolation boundary is armed. The ACTOR runs --verify-only, which performs
# ZERO writes: under `/dev-overnight --worktree` the guard RO-binds the whole
# main root for every Bash command the actor issues, and every target below
# lives under that root, so an actor-side mutating run cannot succeed. Ordering,
# not permissions, was the defect.
#
# Usage: overnight-init.sh --state-file <path-to-overnight-state.json>
#        overnight-init.sh --session-id <sid> [--project-dir <dir>]
#        overnight-init.sh --verify-only --state-file <path>   # read-only
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
#
# Order matters. Checking only AFTER `mkdir -p` is useless: mkdir follows a
# symlinked ancestor and creates the tree at the far end, so by the time the
# check runs the escape has already happened. The deepest EXISTING ancestor is
# therefore canonicalized FIRST, before anything is created, and the resolved
# parent is re-checked afterwards to catch a race. A target that is itself a
# symlink is refused outright rather than followed.
_assert_confined_dir() {
  # $1 = directory that must resolve under PROJECT_ROOT (need not exist yet)
  local dir="$1" probe resolved
  probe="$dir"
  while [[ -n "$probe" && ! -e "$probe" ]]; do
    local next="${probe%/*}"
    [[ "$next" == "$probe" ]] && next=""
    probe="$next"
  done
  [[ -n "$probe" ]] || _die "cannot resolve any existing ancestor of $dir"
  resolved="$(cd "$probe" 2>/dev/null && pwd -P)" \
    || _die "cannot canonicalize $probe"
  case "$resolved" in
    "$PROJECT_ROOT"|"$PROJECT_ROOT"/*) ;;
    *) _die "refusing to write outside the project root: $dir (nearest existing ancestor $probe resolves to $resolved, outside $PROJECT_ROOT)" ;;
  esac
}
_mkdir_confined() {
  local dir="$1" resolved
  _assert_confined_dir "$dir"
  # --verify-only performs ZERO writes: `mkdir -p` on an existing directory is a
  # silent no-op even on a read-only mount, so calling it here would look
  # harmless while still being a write ATTEMPT the actor must not make. The
  # directory is asserted to exist instead.
  if [[ "$VERIFY_ONLY" == "1" ]]; then
    [[ -d "$dir" ]] || _die "verify: directory does not exist: $dir"
  else
    mkdir -p "$dir" || _die "failed to create $dir"
  fi
  # Re-check the now-existing directory: the walk above validated the deepest
  # ancestor that existed at the time, which does not by itself prove the newly
  # created leaf resolves inside (a concurrent symlink swap would).
  resolved="$(cd "$dir" && pwd -P)" || _die "cannot canonicalize $dir"
  case "$resolved" in
    "$PROJECT_ROOT"|"$PROJECT_ROOT"/*) return 0 ;;
    *) _die "refusing to write outside the project root: $dir resolves to $resolved" ;;
  esac
}
_write_confined() {
  # $1 = target path, stdin = content.
  # In --verify-only this becomes an ASSERTION: the on-disk bytes must equal the
  # bytes this run would have written. Same producer, same expression — so the
  # oracle can never drift from the writer, and a verifier is never comparing
  # against a digest the initializer itself recorded.
  local target="$1"
  _mkdir_confined "$(dirname "$target")"
  # A pre-existing symlink at the target would redirect the write regardless of
  # how well the parent is confined. Refuse rather than follow it. In verify
  # mode a symlinked artifact is equally disqualifying: the bytes read are not
  # the bytes at the recorded path.
  [[ -L "$target" ]] && _die "refusing to write through a symlink: $target"
  if [[ "$VERIFY_ONLY" == "1" ]]; then
    [[ -f "$target" ]] || _die "verify: missing artifact: $target"
    diff -q - "$target" >/dev/null 2>&1 \
      || _die "verify: content mismatch against the recomputed oracle: $target"
  else
    cat > "$target" || _die "failed to write $target"
  fi
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
#
# INTERPRETER PREFERENCE (should-have, deliberately not a hard gate). The managed
# interpreter is tried FIRST, matching write-qa-mode.sh:31-33 and score-inject.sh.
# It is a FALLBACK CHAIN, not a provenance requirement: an ambient python3 that
# parses CP_AGENTS and yields fully validated artifacts is not an initialization
# failure, and refusing it would PREVENT Step 1 from succeeding on hosts without
# the managed venv. The fail-closed half — abort when NO interpreter can produce
# the list — is the guard below and is unconditional.
INIT_PYTHON="${CLAUDE_HOME:-$HOME/.claude}/venv/bin/python3"
[[ -x "$INIT_PYTHON" ]] || INIT_PYTHON="$(command -v python3 || true)"
[[ -n "$INIT_PYTHON" ]] || _die "no python3 interpreter available to read CP_AGENTS"
AGENT_LIST="$("$INIT_PYTHON" - "$SCRIPT_DIR/../hooks/pretool-cp-checkin.py" <<'PYEOF' || true
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

_mkdir_confined "$REGISTRY_DIR"
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
      # Verbatim byte-slice from the Section-5 level-2 heading up to the NEXT
      # level-2 heading, so the `### 5.x` subsections stay included. Both
      # heading dialects in use are accepted: "## Section 5: ..." and "## 5. ...".
      # Emits nothing when the spec has no Section 5 — an empty slice is honest,
      # a guessed substitute is not.
      awk '
        /^##[[:space:]]/ && !/^###/ {
          if (inside) exit
          if ($0 ~ /^##[[:space:]]+(Section[[:space:]]+)?5([:.[:space:]]|$)/) { inside = 1 }
        }
        inside { print }
      ' "$SPEC_ABS"
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
