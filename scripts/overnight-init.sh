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

# A SYMLINKED registry leaf passes the confinement walk whenever its target is
# also under the project root — so `dev-registry/<sidA>` pointing at
# `dev-registry/<sidB>` would redirect this session's sentinels into another
# session's registry, overwriting B's records with A's session_id and silently
# invalidating B's enforcement. Confinement answers "inside the project", not
# "the directory it claims to be".
[[ -L "$REGISTRY_DIR" ]] && _die "refusing to use a symlinked registry directory: $REGISTRY_DIR"
_mkdir_confined "$REGISTRY_DIR"
[[ -d "$REGISTRY_DIR" && ! -L "$REGISTRY_DIR" ]] \
  || _die "registry path is not a real directory: $REGISTRY_DIR"
SENTINEL_COUNT=0
while IFS= read -r agent; do
  [[ -n "$agent" ]] || continue
  # Sentinels are verified SEMANTICALLY, never byte-wise. scripts/write-qa-mode.sh
  # legitimately rewrites qa.json with json.dump to add `qa_mode`, and
  # commands/dev-overnight.md invokes it before every QA dispatch. A byte
  # comparison would therefore abort every continuation cycle after the first QA
  # run — stranding a long-running session mid-flight, which is the opposite of
  # what this change exists to achieve. The fields consumers actually read
  # (agent_type, session_id) are asserted in the validation pass below, in both
  # modes; additive keys from a legitimate mutator are tolerated.
  if [[ "$VERIFY_ONLY" != "1" ]]; then
    printf '{"agent_type": "%s", "session_id": "%s"}\n' "$agent" "$SESSION_ID" \
      | _write_confined "$REGISTRY_DIR/$agent.json"
  fi
  SENTINEL_COUNT=$((SENTINEL_COUNT + 1))
done <<< "$AGENT_LIST"

# Direct artifact validation, in BOTH modes, before any success is claimed. In
# verify mode _write_confined already compared bytes; in mutating mode `cat >`
# can still leave a short write behind. Re-reading each sentinel with jq is the
# only check that proves what is ON DISK — never what was intended. The count is
# asserted against len(CP_AGENTS) parsed at run time, never a literal.
EXPECTED_SENTINELS="$(grep -c . <<< "$AGENT_LIST")"
[[ "$SENTINEL_COUNT" == "$EXPECTED_SENTINELS" ]] \
  || _die "sentinel count $SENTINEL_COUNT != CP_AGENTS length $EXPECTED_SENTINELS"
while IFS= read -r agent; do
  [[ -n "$agent" ]] || continue
  _s="$REGISTRY_DIR/$agent.json"
  [[ -f "$_s" && ! -L "$_s" ]] || _die "sentinel missing or not a regular file: $_s"
  jq -e --arg a "$agent" --arg s "$SESSION_ID" \
     '.agent_type == $a and .session_id == $s' "$_s" >/dev/null 2>&1 \
    || _die "sentinel failed validation (malformed, wrong agent_type, or wrong session_id): $_s"
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
if [[ "$VERIFY_ONLY" != "1" ]]; then
  CLAUDE_PROJECT_DIR="$PROJECT_ROOT" bash "$SCRIPT_DIR/write-enforce-flag.sh" "${ENFORCE_ARGS[@]}" >/dev/null \
    || _die "enforcement flag write failed"
fi

# ENFORCEMENT_FLAG_VALID — validity, never mere existence.
# Both consumers fail open TWICE: on absence (subagentstop-e2e-enforce.py:136-138,
# subagentstop-codex-enforce.py:77) AND on a falsy `enabled`
# (e2e:140-143, codex:82), where their _read_json degrades ANY malformed or
# non-dict file to {} so `{}.get("enabled")` is None. A flag that EXISTS but is
# truncated, non-dict, or disabled is therefore INDISTINGUISHABLE from no flag at
# all, and enforcement is silently off for the whole session. Group 1 below is
# what closes that fail-open; group 2 are writer-conformance/integrity clauses
# that exceed what the consumers read (a wrong dev_session_id does NOT disable
# enforcement) and are asserted as corruption signals, not as security closure.
_flag_agent_types() {
  case "$1" in
    e2e)   printf '["qa"]' ;;
    codex) printf '["ba","dev","qa"]' ;;
    *)     return 1 ;;
  esac
}
_assert_flag_valid() {
  local flag="$1" target="$REGISTRY_DIR/$2" want
  want="$(_flag_agent_types "$flag")" || _die "unknown flag: $flag"
  # group 1 — fail-open closing
  [[ -e "$target" ]] || _die "enforcement flag missing: $target (consumer would silently skip enforcement)"
  [[ -L "$target" ]] && _die "enforcement flag is a symlink: $target"
  [[ -f "$target" ]] || _die "enforcement flag is not a regular file: $target"
  jq -e 'type == "object"' "$target" >/dev/null 2>&1 \
    || _die "enforcement flag is not a JSON object: $target (consumer degrades it to {} and fails OPEN)"
  jq -e '.enabled == true' "$target" >/dev/null 2>&1 \
    || _die "enforcement flag is not enabled: $target (consumer exits 0 on a falsy 'enabled')"
  # group 2 — writer conformance / integrity
  jq -e --arg s "$SESSION_ID" --argjson t "$want" \
     '.schema_version == 1 and .source_command == "dev-overnight"
      and .dev_session_id == $s and .enforced_agent_types == $t' "$target" >/dev/null 2>&1 \
    || _die "enforcement flag failed writer-conformance: $target"
}
_assert_flag_valid e2e e2e-enforce.json
if [[ "$CODEX_REQUIRED" == "true" ]]; then
  _assert_flag_valid codex codex-enforce.json
else
  [[ -e "$REGISTRY_DIR/codex-enforce.json" ]] \
    && _die "codex-enforce.json present but the record does not set codex_required"
fi

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
# PLACEMENT IS DELIBERATE (main root, not the isolated working root). Dispatched
# subagents run confined to worktree_path, so writing this under the main
# checkout looks like a containment conflict. It is not: the boundary is
# --ro-bind / / (guard _build_bwrap_argv), so the ENTIRE host stays READABLE and
# only writes are refused, and every dispatch template substitutes the resolved
# ABSOLUTE $REQUIREMENT_DOC rather than a working-root-relative path. Nothing
# rewrites the document after initialization, so the write side never binds.
# Mirroring a copy into the working root was considered and rejected: a
# fresh_clone_checkout root is relocatable outside the main root via
# OVERNIGHT_FRESH_CLONE_ROOT, where _assert_confined_dir would refuse it and
# fail an otherwise-healthy launch, and the alternative silent skip would be a
# fall-open in the one mode the mirror exists to serve.
REQUIREMENT_DOC="$PROJECT_ROOT/docs/dev/user-requirement-$SESSION_ID.md"
FOCUS=""
[[ -n "$STATE_FILE" ]] && FOCUS="$(jq -r '.focus // empty' "$STATE_FILE")"
# Rendered by a FUNCTION so the writer and the oracle are the same expression.
# Comparing against a digest the initializer itself recorded would pass a bad
# renderer trivially — it would write wrong bytes and record their matching hash.
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
}
_render_requirement_doc | _write_confined "$REQUIREMENT_DOC"
# Re-read what is ON DISK and compare it to a freshly recomputed render. In
# mutating mode this catches a short or redirected write; in verify mode it is
# the oracle AC-1 requires. Recomputed, never trusted.
_render_requirement_doc | diff -q - "$REQUIREMENT_DOC" >/dev/null 2>&1 \
  || _die "requirement document does not match the recomputed oracle: $REQUIREMENT_DOC"

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
