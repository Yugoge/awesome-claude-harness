#!/bin/bash
# create-overnight-state.sh — Create overnight state file (v7 schema)
# Replaces inline JSON creation so the LLM agent never writes JSON itself.
#
# Usage: create-overnight-state.sh [OPTIONS]
#   --end-time <ISO-8601|HH:MM>   End time (default: now + 8h)
#   --focus <string>               Discovery focus hint (default: empty)
#   --spec <path>                  User-provided spec file path
#   --session-id <uuid>            Session ID (default: $CLAUDE_SESSION_ID or generated)
#   --project-dir <path>           Project directory (default: $CLAUDE_PROJECT_DIR or pwd)
#
# Output (last line): STATE_PATH=<path>
# Exit: 0=success, 1=error

set -euo pipefail

# --- Defaults ---
END_TIME=""
FOCUS=""
SPEC_PATH=""
SESSION_ID="${CLAUDE_SESSION_ID:-}"
resolve_project_dir() {
    # 4-tier fallback: env -> pwd -> git toplevel -> /root literal.
    # (No stdin tier; this is a CLI script, not a stdin-payload hook.)
    if [[ -n "${CLAUDE_PROJECT_DIR:-}" ]]; then
        printf '%s\n' "$CLAUDE_PROJECT_DIR"
        return 0
    fi
    local cwd
    cwd="$(pwd 2>/dev/null)" || cwd=""
    if [[ -n "$cwd" ]]; then
        printf '%s\n' "$cwd"
        return 0
    fi
    local toplevel
    toplevel="$(git rev-parse --show-toplevel 2>/dev/null)" || toplevel=""
    if [[ -n "$toplevel" ]]; then
        printf '%s\n' "$toplevel"
        return 0
    fi
    echo "Error: cannot determine project directory; set CLAUDE_PROJECT_DIR or run from within a git repo" >&2
    exit 1
}
PROJECT_DIR="$(resolve_project_dir)"

# --- Parse arguments ---
CODEX_REQUIRED=false
# Override state and cycle directories via env vars or CLI
STATE_SUBDIR="${OVERNIGHT_STATE_SUBDIR:-.claude}"
CYCLE_SUBDIR="${OVERNIGHT_CYCLE_SUBDIR:-docs/dev/overnight}"
SPECS_SUBDIR="${OVERNIGHT_SPECS_SUBDIR:-docs/dev/specs}"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --end-time)  END_TIME="$2"; shift 2 ;;
        --focus)     FOCUS="$2"; shift 2 ;;
        --spec)      SPEC_PATH="$2"; shift 2 ;;
        --session-id) SESSION_ID="$2"; shift 2 ;;
        --project-dir) PROJECT_DIR="$2"; shift 2 ;;
        --state-subdir) STATE_SUBDIR="$2"; shift 2 ;;
        --cycle-subdir) CYCLE_SUBDIR="$2"; shift 2 ;;
        --specs-subdir) SPECS_SUBDIR="$2"; shift 2 ;;
        --codex)     CODEX_REQUIRED=true; shift ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Usage: create-overnight-state.sh [--end-time <time>] [--focus <str>] [--spec <path>] [--session-id <uuid>] [--project-dir <path>] [--state-subdir <dir>] [--cycle-subdir <dir>] [--specs-subdir <dir>] [--codex]" >&2
            exit 1
            ;;
    esac
done

# --- Session ID ---
if [[ -z "$SESSION_ID" ]]; then
    SESSION_ID="$(uuidgen)"
    echo "Generated session ID: $SESSION_ID" >&2
fi

# --- Start time ---
START_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# --- End time parsing ---
parse_end_time() {
    local input="$1"

    # Empty → now + 8 hours
    if [[ -z "$input" ]]; then
        date -u -d "+8 hours" +%Y-%m-%dT%H:%M:%SZ
        return
    fi

    # M5 (harness-fixes 20260428): the Python layer (prompt-workflow.py)
    # forwards INVALID:<token> when it sees an unparseable +token. Surface
    # an explicit error here rather than silent fallback to +8h.
    if [[ "$input" == INVALID:* ]]; then
        echo "Cannot parse end-time: ${input#INVALID:}" >&2
        exit 1
    fi

    # T1.6 (redev-tier123): accept bare-form Nh / N.Mh / Nm by stripping
    # an optional leading '+' before the existing match below. Per user
    # directive (e), the '+' prefix is documented no-op compat; bare form
    # is the primary spelling.
    local stripped="${input#+}"

    # M5: relative-time forms Nh / N.Mh / Nm (with optional leading +
    # already stripped). GNU date does not accept fractional hours
    # ("+0.5 hours" errors), so we always normalize to whole-minute
    # offsets via integer arithmetic. Any token NOT matching this
    # pattern errors loudly (no silent fallback to +8h).
    if [[ "$stripped" =~ ^([0-9]+)(\.([0-9]+))?([hm])$ ]]; then
        local whole="${BASH_REMATCH[1]}"
        local frac="${BASH_REMATCH[3]}"
        local unit="${BASH_REMATCH[4]}"
        local minutes
        if [[ "$unit" == "h" ]]; then
            minutes=$((whole * 60))
            if [[ -n "$frac" ]]; then
                # Compute fractional-hours minutes: frac/10^len(frac) * 60
                local pad="${#frac}"
                local denom=$((10 ** pad))
                minutes=$((minutes + (10#$frac * 60) / denom))
            fi
        else
            if [[ -n "$frac" ]]; then
                echo "Cannot parse end-time: $input (fractional minutes not supported)" >&2
                exit 1
            fi
            minutes="$whole"
        fi
        date -u -d "+${minutes} minutes" +%Y-%m-%dT%H:%M:%SZ
        return
    fi
    if [[ "$input" == +* ]]; then
        echo "Cannot parse end-time: $input" >&2
        exit 1
    fi

    # Already ISO-8601 (contains T or full date pattern)
    if [[ "$input" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2} ]]; then
        date -u -d "$input" +%Y-%m-%dT%H:%M:%SZ
        return
    fi

    # HH:MM or HH:MM AM/PM → parse as clock time today, if past → tomorrow
    local target_epoch
    target_epoch=$(date -d "today $input" +%s 2>/dev/null) || {
        echo "Cannot parse end-time: $input" >&2
        exit 1
    }
    local now_epoch
    now_epoch=$(date +%s)

    if [[ "$target_epoch" -le "$now_epoch" ]]; then
        # Already past today → use tomorrow
        target_epoch=$(date -d "tomorrow $input" +%s)
    fi

    date -u -d "@$target_epoch" +%Y-%m-%dT%H:%M:%SZ
}

END_TIME="$(parse_end_time "$END_TIME")"

# C12 (redev-tier123): warn (do not error) when time budget is <60 min.
target_epoch=$(date -u -d "$END_TIME" +%s 2>/dev/null || echo 0)
now_epoch=$(date +%s)
if [[ "$target_epoch" -gt 0 ]]; then
    delta_min=$(( (target_epoch - now_epoch) / 60 ))
    if [[ "$delta_min" -lt 60 ]]; then
        echo "WARNING: time budget <1h (${delta_min}m). Recommended minimum: 1h for 1 pipeline; 2h for 2-3 pipelines; 6h+ for overnight." >&2
    fi
fi

# --- Repo identity + MAIN_HEAD capture (side-effect-free; may precede worktree) ---
# M1/round-3: only side-effect-free repo-identity discovery and MAIN_HEAD capture
# may run before worktree creation. Everything fallible (spec/focus/view) runs AFTER.
MAIN_ROOT="$(git -C "$PROJECT_DIR" rev-parse --show-toplevel 2>/dev/null || echo '')"
if [[ -z "$MAIN_ROOT" ]]; then
    echo "Error: --project-dir is not inside a git repo: $PROJECT_DIR" >&2
    exit 1
fi
MAIN_GIT_DIR="$(git -C "$MAIN_ROOT" rev-parse --absolute-git-dir 2>/dev/null || echo "$MAIN_ROOT/.git")"
MAIN_BRANCH_AT_START="$(git -C "$MAIN_ROOT" branch --show-current 2>/dev/null || echo '')"
# Fatal unless the main checkout is exactly on master (round-3 §2): we will never
# move it; launching from a non-master main dir is an unsafe precondition.
if [[ "$MAIN_BRANCH_AT_START" != "master" ]]; then
    echo "Error: overnight launch requires the main checkout on 'master' (found: '${MAIN_BRANCH_AT_START:-<detached>}'). Refusing to launch (no state written)." >&2
    exit 1
fi
MAIN_HEAD_AT_START="$(git -C "$MAIN_ROOT" rev-parse HEAD 2>/dev/null || echo '')"
# Dirty main tree is ALLOWED; we record it and NEVER stash/copy/commit it.
if [[ -n "$(git -C "$MAIN_ROOT" status --porcelain 2>/dev/null)" ]]; then
    MAIN_DIRTY_AT_START=true
else
    MAIN_DIRTY_AT_START=false
fi

# --- Create + validate the isolated worktree FIRST (M1, M2, M3) ---------------
# Recoverable failures here NEVER fall back to in-place work: a missing/invalid
# worktree means launch refuses (no state) — distinct from hard-abort-then-work.
WORKTREE_PATH=""
WORKTREE_BRANCH=""
WORKTREE_HEAD_AT_START=""
ISOLATION_KIND=""
WORKTREE_SCRIPT="$(dirname "$0")/create-worktree.sh"
WORKTREE_NAME="overnight-$(date +%Y%m%d)-${SESSION_ID:0:8}"
if [[ -x "$WORKTREE_SCRIPT" ]] && \
   WORKTREE_RESULT=$(bash "$WORKTREE_SCRIPT" --project-dir "$MAIN_ROOT" "$WORKTREE_NAME" 2>/dev/null); then
    WORKTREE_PATH=$(echo "$WORKTREE_RESULT" | grep -oP 'WORKTREE_PATH=\K\S+' || echo '')
    WORKTREE_BRANCH=$(echo "$WORKTREE_RESULT" | grep -oP 'WORKTREE_BRANCH=\K\S+' || echo '')
    if [[ -n "$WORKTREE_PATH" && -d "$WORKTREE_PATH" ]]; then
        ISOLATION_KIND="registered_worktree"
        WORKTREE_HEAD_AT_START="$(git -C "$WORKTREE_PATH" rev-parse HEAD 2>/dev/null || echo '')"
        echo "Created worktree: $WORKTREE_PATH (branch: $WORKTREE_BRANCH)" >&2
    fi
fi

# Recovery ladder + fresh-clone fallback (M2/AC3a) when the primary worktree
# could not be produced. NEVER work in-place; NEVER use tmpfs as a default.
if [[ -z "$ISOLATION_KIND" ]]; then
    echo "Primary worktree creation failed; attempting recovery ladder (repair -> prune -> fresh-clone)." >&2
    git -C "$MAIN_ROOT" worktree repair >/dev/null 2>&1 || true
    git -C "$MAIN_ROOT" worktree prune >/dev/null 2>&1 || true
    # one more registered-worktree attempt after repair/prune
    if WORKTREE_RESULT=$(bash "$WORKTREE_SCRIPT" --project-dir "$MAIN_ROOT" "$WORKTREE_NAME" 2>/dev/null); then
        WORKTREE_PATH=$(echo "$WORKTREE_RESULT" | grep -oP 'WORKTREE_PATH=\K\S+' || echo '')
        WORKTREE_BRANCH=$(echo "$WORKTREE_RESULT" | grep -oP 'WORKTREE_BRANCH=\K\S+' || echo '')
        if [[ -n "$WORKTREE_PATH" && -d "$WORKTREE_PATH" ]]; then
            ISOLATION_KIND="registered_worktree"
            WORKTREE_HEAD_AT_START="$(git -C "$WORKTREE_PATH" rev-parse HEAD 2>/dev/null || echo '')"
            echo "Recovered worktree after repair/prune: $WORKTREE_PATH" >&2
        fi
    fi
fi
if [[ -z "$ISOLATION_KIND" ]]; then
    # Durable fresh-clone fallback at captured MAIN_HEAD on its own branch.
    # Only on a durable (non-tmpfs, writable) root: default under main_root.
    FRESH_ROOT="${OVERNIGHT_FRESH_CLONE_ROOT:-$MAIN_ROOT/.claude/overnight-fresh-clones}"
    FRESH_FSTYPE="$(stat -f -c %T "$(dirname "$FRESH_ROOT")" 2>/dev/null || echo unknown)"
    if [[ "$FRESH_FSTYPE" == "tmpfs" && -z "${OVERNIGHT_ALLOW_TMPFS_FRESH_CLONE:-}" ]]; then
        echo "Fresh-clone root is tmpfs ($FRESH_ROOT); refusing (data-loss risk). Set OVERNIGHT_FRESH_CLONE_ROOT to a durable path." >&2
    elif mkdir -p "$FRESH_ROOT" 2>/dev/null && [[ -w "$FRESH_ROOT" ]]; then
        FRESH_WT="$FRESH_ROOT/${WORKTREE_NAME}"
        FRESH_BRANCH="worktree-${WORKTREE_NAME}"
        if git clone -q --local "$MAIN_GIT_DIR" "$FRESH_WT" 2>/dev/null \
           && git -C "$FRESH_WT" checkout -q -b "$FRESH_BRANCH" "$MAIN_HEAD_AT_START" 2>/dev/null; then
            WORKTREE_PATH="$FRESH_WT"
            WORKTREE_BRANCH="$FRESH_BRANCH"
            ISOLATION_KIND="fresh_clone_checkout"
            WORKTREE_HEAD_AT_START="$(git -C "$FRESH_WT" rev-parse HEAD 2>/dev/null || echo '')"
            echo "Durable fresh-clone fallback created at $FRESH_WT" >&2
        fi
    fi
fi

# AC3b: refusal-to-LAUNCH only when ALL durable isolation is impossible. NEVER
# write a null/main-root worktree; NEVER continue in-place.
if [[ -z "$ISOLATION_KIND" || -z "$WORKTREE_PATH" \
      || "$(realpath "$WORKTREE_PATH" 2>/dev/null || echo "$WORKTREE_PATH")" == "$(realpath "$MAIN_ROOT" 2>/dev/null || echo "$MAIN_ROOT")" ]]; then
    echo "FATAL: no durable isolated worktree could be produced; refusing to launch the overnight actor (no state, no checklist, no in-place work)." >&2
    exit 1
fi

# --- Spec mode detection (AFTER worktree exists; mismatch DEGRADES, never aborts) ---
SPEC_MODE="autonomous"
USER_SPEC_PATH="null"

spec_matches_focus() {
    local detected="$1"
    [[ -n "$FOCUS" ]] || return 1
    grep -Fq -- "$FOCUS" "$detected"
}

if [[ -n "$SPEC_PATH" ]]; then
    # Explicit --spec missing/invalid is fatal (round-3 §2) — but the worktree
    # already exists, so this is a clean refuse-to-launch, not in-place fallback.
    if [[ ! -f "$SPEC_PATH" ]]; then
        echo "Error: Spec file not found: $SPEC_PATH" >&2
        exit 1
    fi
    SPEC_MODE="user-provided"
    USER_SPEC_PATH="$SPEC_PATH"
elif [[ -d "$PROJECT_DIR/$SPECS_SUBDIR" ]]; then
    # Auto-detect: newest .md in the specs directory, excluding INDEX.md and README.md
    DETECTED=$(find "$PROJECT_DIR/$SPECS_SUBDIR" -maxdepth 1 -name '*.md' \
        ! -name 'INDEX.md' ! -name 'README.md' \
        -printf '%T@ %p\n' 2>/dev/null \
        | sort -rn | head -1 | cut -d' ' -f2-)
    if [[ -n "$DETECTED" && -f "$DETECTED" ]]; then
        if spec_matches_focus "$DETECTED"; then
            SPEC_MODE="user-provided"
            USER_SPEC_PATH="$DETECTED"
            echo "Auto-detected spec: $USER_SPEC_PATH" >&2
        else
            # M2/AC2: recoverable spec/focus mismatch DEGRADES to autonomous;
            # never abort, never work in-place. The worktree is already valid.
            echo "Auto-detected spec did not match focus; degrading to spec_mode=autonomous (worktree already created)." >&2
            SPEC_MODE="autonomous"
            USER_SPEC_PATH="null"
        fi
    fi
fi

# --- Install the git-native keystone (M7) into the main repo (idempotent) -----
# fix-5 (Cycle-2): the keystone install MUST run BEFORE the launch self-test so a
# properly-provisioned git >=2.46 host can legitimately record a structural claim
# (the self-test attests core.hooksPath == expected + keystone hash). Cycle-1 ran
# the self-test first, denying a legitimate structural claim on a >=2.46 host.
# Wires the reference-transaction hook via core.hooksPath relocation WITHOUT
# clobbering pre-commit/post-commit (the installer re-homes/chains them, AC6).
KEYSTONE_INSTALLER="$(dirname "$0")/install-git-keystone.sh"
if [[ -x "$KEYSTONE_INSTALLER" ]]; then
    bash "$KEYSTONE_INSTALLER" --project-dir "$MAIN_ROOT" >&2 || \
        echo "Warning: keystone installation reported a problem (layered defenses still active)." >&2
fi

# --- Prepare + CAPTURE the overnight actor's git PATH wrappers (fix-1) ---------
# fix-1 (Cycle-2): the env helper installs the policy-shim + selector bin dirs AND
# emits the export lines. Cycle-1 discarded that output in a child shell, so the
# actor never inherited CLAUDE_OVERNIGHT_ACTOR=1 / the shim-first PATH. We now
# CAPTURE the emitted markers and PERSIST the resolved actor git env into the
# state file so dev-overnight.md Step 1 can source it and verify it took effect,
# and so AC-1 can inspect the durable resolved shim-git path.
ACTOR_GIT_SHIM=""
ACTOR_GIT_BINDIR=""
ACTOR_GIT_SHIMDIR=""
ACTOR_ENV_HELPER_PATH=""
SCRIPT_DIR_ABS="$(cd "$(dirname "$0")" && pwd -P)"
GITENV_HELPER="$SCRIPT_DIR_ABS/overnight-git-env.sh"
if [[ -x "$GITENV_HELPER" ]]; then
    ACTOR_ENV_HELPER_PATH="$GITENV_HELPER"
    GITENV_OUT="$(bash "$GITENV_HELPER" --main-root "$MAIN_ROOT" --worktree "$WORKTREE_PATH" 2>/dev/null || true)"
    ACTOR_GIT_SHIM="$(printf '%s\n' "$GITENV_OUT" | grep -oP '^# OVERNIGHT_GIT_ENV_SHIM_GIT=\K.*' | head -1 || echo '')"
    ACTOR_GIT_BINDIR="$(printf '%s\n' "$GITENV_OUT" | grep -oP '^# OVERNIGHT_GIT_ENV_BINDIR=\K.*' | head -1 || echo '')"
    ACTOR_GIT_SHIMDIR="$(printf '%s\n' "$GITENV_OUT" | grep -oP '^# OVERNIGHT_GIT_ENV_SHIMDIR=\K.*' | head -1 || echo '')"
fi

# --- Launch git self-test: record honest guarantee fields (M8/M16) -----------
# Runs AFTER the keystone install (fix-5) so the self-test's target-repo
# attestation observes the already-installed keystone (core.hooksPath + hash).
GUARANTEE_LEVEL="best_effort_head_switch"
STRUCTURAL_CLAIM_ALLOWED=false
GIT_VERSION_FIELD=""
GIT_EFFECTIVE_PATH_FIELD=""
GIT_EXEC_PATH_FIELD=""
SELFTEST_RESULT_FIELD=""
SELFTEST_SCRIPT="$(dirname "$0")/overnight-git-selftest.sh"
if [[ -x "$SELFTEST_SCRIPT" ]]; then
    SELFTEST_JSON_LINE="$(bash "$SELFTEST_SCRIPT" --project-dir "$MAIN_ROOT" 2>/dev/null | grep '^SELFTEST_JSON=' | head -1 || echo '')"
    SELFTEST_JSON="${SELFTEST_JSON_LINE#SELFTEST_JSON=}"
    if [[ -n "$SELFTEST_JSON" ]] && echo "$SELFTEST_JSON" | jq empty >/dev/null 2>&1; then
        GUARANTEE_LEVEL="$(echo "$SELFTEST_JSON" | jq -r '.guarantee_level // "best_effort_head_switch"')"
        STRUCTURAL_CLAIM_ALLOWED="$(echo "$SELFTEST_JSON" | jq -r '.structural_claim_allowed // false')"
        GIT_VERSION_FIELD="$(echo "$SELFTEST_JSON" | jq -r '.git_version // ""')"
        GIT_EFFECTIVE_PATH_FIELD="$(echo "$SELFTEST_JSON" | jq -r '.git_effective_path // ""')"
        GIT_EXEC_PATH_FIELD="$(echo "$SELFTEST_JSON" | jq -r '.git_exec_path // ""')"
        SELFTEST_RESULT_FIELD="$(echo "$SELFTEST_JSON" | jq -r '.reference_transaction_selftest_result // ""')"
    fi
fi

# --- dev-registry sentinel dir for child-actor classification (round-3 §2) ---
DEV_REGISTRY_DIR="$MAIN_ROOT/.claude/dev-registry/$SESSION_ID"
mkdir -p "$DEV_REGISTRY_DIR" 2>/dev/null || true

# --- isolation_active_until == end_time (liveness key, M9/M10) ---------------
ISOLATION_ACTIVE_UNTIL="$END_TIME"

# --- Detect view_paths + canonical spec-id via the centralized resolver ---
# Do NOT derive SPEC_DIR / spec_id from the monolith basename inline: the producer
# (/spec) emits DE-prefixed split dirs (docs/dev/specs/<ts>/) while the monolith
# filename keeps the spec- prefix, so "${USER_SPEC_PATH%.md}" misses the manifest.  # spec-id-lint: allow
# resolve-spec-artifacts.py tolerates both conventions and fails loud on a
# present-but-invalid split. RESOLVED_SPEC_ID is reused for the contract's spec_id.
VIEW_PATHS="{}"
RESOLVED_SPEC_ID=""
RESOLVER="$(dirname "$0")/resolve-spec-artifacts.py"
if [[ "$USER_SPEC_PATH" != "null" && -n "$USER_SPEC_PATH" ]]; then
    if RESOLVED_JSON=$("$RESOLVER" --spec-path "$USER_SPEC_PATH" --project-dir "$PROJECT_DIR" 2>/dev/null); then
        RESOLVED_SPEC_ID=$(jq -r '.artifact_id // empty' <<<"$RESOLVED_JSON")
        VIEWS_AVAILABLE=$(jq -r '.views_available // false' <<<"$RESOLVED_JSON")
        MANIFEST=$(jq -r '.manifest_path // empty' <<<"$RESOLVED_JSON")
        if [[ "$VIEWS_AVAILABLE" == "true" && -n "$MANIFEST" && -f "$PROJECT_DIR/$MANIFEST" ]]; then
            VIEW_PATHS=$(jq -c '.views // {}' "$PROJECT_DIR/$MANIFEST" 2>/dev/null || echo '{}')
            echo "Loaded view_paths from manifest ($MANIFEST)" >&2
        fi
    else
        # M2/cp-05: a present-but-invalid / mismatched split is a RECOVERABLE
        # failure. The isolated worktree already exists and is validated, so we
        # MUST NOT hard-abort (that would orphan a valid worktree and is the
        # forbidden behavior). Degrade to spec_mode=autonomous and continue;
        # the launch never works in-place and never refuses on a recoverable
        # post-worktree failure.
        echo "Warning: spec-artifact resolution FAILED for '$USER_SPEC_PATH' (present-but-invalid split). Degrading to spec_mode=autonomous (worktree already validated; not aborting)." >&2
        SPEC_MODE="autonomous"
        USER_SPEC_PATH="null"
        VIEW_PATHS="{}"
        RESOLVED_SPEC_ID=""
    fi
fi

# --- Ensure output directory exists ---
STATE_DIR="$PROJECT_DIR/$STATE_SUBDIR"
mkdir -p "$STATE_DIR"

STATE_FILE="$STATE_DIR/overnight-state-${SESSION_ID}.json"
TMP_FILE="${STATE_FILE}.tmp"
CYCLE_ID=1
CYCLE_DIR="$PROJECT_DIR/$CYCLE_SUBDIR/$SESSION_ID/cycle-$CYCLE_ID"
CONTRACT_FILE="$CYCLE_DIR/cycle-contract.json"
TRACE_LOG_PATH="$CYCLE_DIR/trace.jsonl"
MONOLITH_SHA="null"
if [[ "$USER_SPEC_PATH" != "null" && -n "$USER_SPEC_PATH" && -f "$USER_SPEC_PATH" ]]; then
    MONOLITH_SHA="$(sha256sum "$USER_SPEC_PATH" | awk '{print $1}')"
fi

# --- Build JSON with jq (schema v8 + Option-A immutable guarantee fields) -----
jq -n \
    --arg session_id "$SESSION_ID" \
    --arg end_time "$END_TIME" \
    --arg start_time "$START_TIME" \
    --arg focus "$FOCUS" \
    --arg spec_mode "$SPEC_MODE" \
    --arg user_spec_path "$USER_SPEC_PATH" \
    --arg worktree_path "$WORKTREE_PATH" \
    --arg worktree_branch "$WORKTREE_BRANCH" \
    --arg cycle_contract_path "$CONTRACT_FILE" \
    --arg main_root "$MAIN_ROOT" \
    --arg main_git_dir "$MAIN_GIT_DIR" \
    --arg main_branch_at_start "$MAIN_BRANCH_AT_START" \
    --arg main_head_at_start "$MAIN_HEAD_AT_START" \
    --argjson main_dirty_at_start "$MAIN_DIRTY_AT_START" \
    --arg worktree_head_at_start "$WORKTREE_HEAD_AT_START" \
    --arg isolation_kind "$ISOLATION_KIND" \
    --arg isolation_active_until "$ISOLATION_ACTIVE_UNTIL" \
    --arg dev_registry_session_id "$SESSION_ID" \
    --arg dev_registry_dir "$DEV_REGISTRY_DIR" \
    --arg guarantee_level "$GUARANTEE_LEVEL" \
    --argjson structural_claim_allowed "$STRUCTURAL_CLAIM_ALLOWED" \
    --arg git_version "$GIT_VERSION_FIELD" \
    --arg git_effective_path "$GIT_EFFECTIVE_PATH_FIELD" \
    --arg git_exec_path "$GIT_EXEC_PATH_FIELD" \
    --arg reference_transaction_selftest_result "$SELFTEST_RESULT_FIELD" \
    --arg actor_git_shim "$ACTOR_GIT_SHIM" \
    --arg actor_git_bindir "$ACTOR_GIT_BINDIR" \
    --arg actor_git_shimdir "$ACTOR_GIT_SHIMDIR" \
    --arg actor_env_helper "$ACTOR_ENV_HELPER_PATH" \
    --argjson view_paths "$VIEW_PATHS" \
    --argjson codex_required "$CODEX_REQUIRED" \
    '{
        schema_version: 8,
        session_id: $session_id,
        end_time: $end_time,
        start_time: $start_time,
        isolation_active_until: $isolation_active_until,
        isolation_released_at: null,
        focus: $focus,
        spec_mode: $spec_mode,
        user_spec_path: (if $user_spec_path == "null" then null else $user_spec_path end),
        cycle_id: 1,
        cycle_contract_path: $cycle_contract_path,
        cycle_count: 0,
        issues_found: 0,
        issues_fixed: 0,
        issues_skipped: 0,
        current_phase: "exploring",
        current_issues: [],
        failed_attempts: {},
        addressed_issues: [],
        cycle_log: [],
        consecutive_clean_sweeps: 0,
        main_root: $main_root,
        main_git_dir: $main_git_dir,
        main_branch_at_start: $main_branch_at_start,
        main_head_at_start: $main_head_at_start,
        main_dirty_at_start: $main_dirty_at_start,
        worktree_path: $worktree_path,
        worktree_branch: $worktree_branch,
        worktree_head_at_start: (if $worktree_head_at_start == "" then null else $worktree_head_at_start end),
        isolation_kind: $isolation_kind,
        dev_registry_session_id: $dev_registry_session_id,
        dev_registry_dir: $dev_registry_dir,
        guarantee_level: $guarantee_level,
        structural_claim_allowed: $structural_claim_allowed,
        git_version: (if $git_version == "" then null else $git_version end),
        git_effective_path: (if $git_effective_path == "" then null else $git_effective_path end),
        git_exec_path: (if $git_exec_path == "" then null else $git_exec_path end),
        reference_transaction_selftest_result: (if $reference_transaction_selftest_result == "" then null else $reference_transaction_selftest_result end),
        actor_git_env: {
            shim_git: (if $actor_git_shim == "" then null else $actor_git_shim end),
            bindir: (if $actor_git_bindir == "" then null else $actor_git_bindir end),
            shimdir: (if $actor_git_shimdir == "" then null else $actor_git_shimdir end),
            env_helper: (if $actor_env_helper == "" then null else $actor_env_helper end)
        },
        view_paths: $view_paths,
        pm_triage_reports: [],
        pm_retro_reports: [],
        unresolved_issues: [],
        codex_required: $codex_required
    }' > "$TMP_FILE"

# Atomic move
mv "$TMP_FILE" "$STATE_FILE"

# --- Create minimal cycle contract at session creation ---
mkdir -p "$CYCLE_DIR"
CONTRACT_TMP="${CONTRACT_FILE}.tmp"
jq -n \
    --arg session_id "$SESSION_ID" \
    --arg spec_mode "$SPEC_MODE" \
    --arg spec_path "$USER_SPEC_PATH" \
    --arg created_at "$START_TIME" \
    --arg monolith_sha "$MONOLITH_SHA" \
    --arg trace_log_path "$TRACE_LOG_PATH" \
    --arg resolved_spec_id "$RESOLVED_SPEC_ID" \
    '{
        schema_version: 1,
        # spec_id is the resolver-canonical artifact id (de-prefixed/prefixed per disk),
        # NOT the raw monolith basename — keeps producer & consumers byte-for-byte in agreement.
        spec_id: (if $spec_path == "null" then "autonomous-" + $session_id
                  elif ($resolved_spec_id | length) > 0 then $resolved_spec_id
                  else ($spec_path | split("/")[-1] | sub("\\.md$"; "")) end),
        session_id: $session_id,
        cycle_id: 1,
        spec_mode: $spec_mode,
        spec_path: (if $spec_path == "null" then null else $spec_path end),
        created_at: $created_at,
        monolith_sha256: (if $monolith_sha == "null" then null else $monolith_sha end),
        trace_log_path: $trace_log_path,
        required_calls: [],
        pipelines: {},
        specialist_selection: {}
    }' > "$CONTRACT_TMP"
jq empty "$CONTRACT_TMP" >/dev/null
mv "$CONTRACT_TMP" "$CONTRACT_FILE"

echo "Created overnight state v8: $STATE_FILE" >&2
echo "Created minimal cycle contract: $CONTRACT_FILE" >&2
echo "  Session: $SESSION_ID" >&2
echo "  End time: $END_TIME" >&2
echo "  Spec mode: $SPEC_MODE" >&2
if [[ -n "$WORKTREE_PATH" ]]; then
    echo "  Worktree: $WORKTREE_PATH" >&2
fi
echo "STATE_PATH=$STATE_FILE"
