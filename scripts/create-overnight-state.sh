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

# --- Spec mode detection ---
SPEC_MODE="autonomous"
USER_SPEC_PATH="null"

ensure_detected_spec_matches_focus() {
    local detected="$1"
    if [[ -z "$FOCUS" ]]; then
        echo "Error: Auto-detected spec requires explicit --spec when focus is empty." >&2
        echo "  detected: $detected" >&2
        return 1
    fi
    if grep -Fq -- "$FOCUS" "$detected"; then
        return 0
    fi
    echo "Error: Auto-detected spec does not match focus; pass explicit --spec to bind it." >&2
    echo "  focus: $FOCUS" >&2
    echo "  detected: $detected" >&2
    return 1
}

if [[ -n "$SPEC_PATH" ]]; then
    # Explicit --spec provided
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
        ensure_detected_spec_matches_focus "$DETECTED"
        SPEC_MODE="user-provided"
        USER_SPEC_PATH="$DETECTED"
        echo "Auto-detected spec: $USER_SPEC_PATH" >&2
    fi
fi

# --- Create worktree ---
WORKTREE_PATH=""
WORKTREE_BRANCH=""
WORKTREE_SCRIPT="$(dirname "$0")/create-worktree.sh"
WORKTREE_NAME="overnight-$(date +%Y%m%d)-${SESSION_ID:0:8}"
if [[ -x "$WORKTREE_SCRIPT" ]] && WORKTREE_RESULT=$(bash "$WORKTREE_SCRIPT" "$WORKTREE_NAME" 2>/dev/null); then
    WORKTREE_PATH=$(echo "$WORKTREE_RESULT" | grep -oP 'WORKTREE_PATH=\K\S+')
    WORKTREE_BRANCH=$(echo "$WORKTREE_RESULT" | grep -oP 'WORKTREE_BRANCH=\K\S+')
    echo "Created worktree: $WORKTREE_PATH (branch: $WORKTREE_BRANCH)" >&2
else
    echo "Warning: worktree creation failed, continuing without worktree" >&2
fi

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
        # loud-fail guard: a present-but-invalid / mismatched split must not be silently ignored.
        echo "Error: spec-artifact resolution FAILED for '$USER_SPEC_PATH' (path mismatch / present-but-invalid split). Re-finalize /spec before scheduling overnight." >&2
        exit 1
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

# --- Build JSON with jq ---
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
    --argjson view_paths "$VIEW_PATHS" \
    --argjson codex_required "$CODEX_REQUIRED" \
    '{
        session_id: $session_id,
        end_time: $end_time,
        start_time: $start_time,
        focus: $focus,
        spec_mode: $spec_mode,
        user_spec_path: (if $user_spec_path == "null" then null else $user_spec_path end),
        cycle_id: 1,
        cycle_contract_path: $cycle_contract_path,
        cycle_count: 0,
        issues_found: 0,
        issues_fixed: 0,
        issues_skipped: 0,
        current_phase: (if $worktree_path == "" then "initializing" else "exploring" end),
        current_issues: [],
        failed_attempts: {},
        addressed_issues: [],
        cycle_log: [],
        consecutive_clean_sweeps: 0,
        worktree_path: (if $worktree_path == "" then null else $worktree_path end),
        worktree_branch: (if $worktree_branch == "" then null else $worktree_branch end),
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

echo "Created overnight state v7: $STATE_FILE" >&2
echo "Created minimal cycle contract: $CONTRACT_FILE" >&2
echo "  Session: $SESSION_ID" >&2
echo "  End time: $END_TIME" >&2
echo "  Spec mode: $SPEC_MODE" >&2
if [[ -n "$WORKTREE_PATH" ]]; then
    echo "  Worktree: $WORKTREE_PATH" >&2
fi
echo "STATE_PATH=$STATE_FILE"
