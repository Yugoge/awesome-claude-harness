#!/bin/bash
# update-overnight-state.sh — Atomically update overnight state file
# Companion to create-overnight-state.sh. Handles ALL mutations so the
# LLM agent never writes JSON itself.
#
# Usage: update-overnight-state.sh [--session-id <id>] [--project-dir <path>] <operations...>
#
# Operations (composable, applied left-to-right):
#   --set <key> <value>             Set scalar (auto-typed: null/bool/int/string)
#   --set-json <key> <json>         Set field to raw JSON value
#   --inc <key>                     Increment numeric field by 1
#   --append <key> <value>          Append string to array
#   --append-json <key> <json>      Append JSON object/value to array
#   --update-issue <idx> <key> <val>  Update current_issues[idx].key = value
#   --inc-issue <idx> <key>         Increment current_issues[idx].key by 1
#   --inc-fail <description>        Increment failed_attempts[description] by 1
#   --cycle-reset                   Reset for new cycle (bump cycle_count, clear issues)
#
# Output (last line to stdout): STATE_PATH=<path>
# Info messages go to stderr.
# Exit: 0=success, 1=error

set -euo pipefail

# --- Defaults ---
SESSION_ID="${CLAUDE_SESSION_ID:-}"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# --- Collect operations before processing ---
OPS=()

# --- Parse arguments ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --session-id)
            SESSION_ID="$2"; shift 2 ;;
        --project-dir)
            PROJECT_DIR="$2"; shift 2 ;;
        --set)
            OPS+=("set" "$2" "$3"); shift 3 ;;
        --set-json)
            OPS+=("set-json" "$2" "$3"); shift 3 ;;
        --inc)
            OPS+=("inc" "$2"); shift 2 ;;
        --append)
            OPS+=("append" "$2" "$3"); shift 3 ;;
        --append-json)
            OPS+=("append-json" "$2" "$3"); shift 3 ;;
        --update-issue)
            OPS+=("update-issue" "$2" "$3" "$4"); shift 4 ;;
        --inc-issue)
            OPS+=("inc-issue" "$2" "$3"); shift 3 ;;
        --inc-fail)
            OPS+=("inc-fail" "$2"); shift 2 ;;
        --cycle-reset)
            OPS+=("cycle-reset"); shift 1 ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Usage: update-overnight-state.sh [--session-id <id>] [--project-dir <path>] <operations...>" >&2
            exit 1
            ;;
    esac
done

if [[ ${#OPS[@]} -eq 0 ]]; then
    echo "Error: No operations specified" >&2
    exit 1
fi

# --- M10/AC8: reject mutation of immutable isolation + Option-A fields --------
# State integrity is non-negotiable: an actor must not be able to flip
# best_effort -> structural, repoint the worktree at main, or release isolation
# via a plain --set. `isolation_released_at` is settable ONLY via the dedicated
# /stop release path (scripts/break-overnight-lock.py), never via --set here.
IMMUTABLE_FIELDS=(
    session_id main_root main_git_dir main_branch_at_start main_head_at_start
    worktree_path worktree_branch worktree_head_at_start isolation_active_until
    dev_registry_session_id dev_registry_dir isolation_kind
    guarantee_level structural_claim_allowed git_effective_path git_version
    git_exec_path reference_transaction_selftest_result isolation_released_at
)
_is_immutable() {
    local k="$1" f
    for f in "${IMMUTABLE_FIELDS[@]}"; do
        [[ "$k" == "$f" ]] && return 0
    done
    return 1
}
i=0
while [[ $i -lt ${#OPS[@]} ]]; do
    case "${OPS[$i]}" in
        set|set-json)
            if _is_immutable "${OPS[$((i+1))]}"; then
                echo "Error: field '${OPS[$((i+1))]}' is immutable (isolation/guarantee integrity); mutation rejected." >&2
                echo "  Only the /stop release path may set isolation_released_at." >&2
                exit 1
            fi
            i=$((i+3)) ;;
        inc) i=$((i+2)) ;;
        append|append-json) i=$((i+3)) ;;
        update-issue) i=$((i+4)) ;;
        inc-issue) i=$((i+3)) ;;
        inc-fail) i=$((i+2)) ;;
        cycle-reset) i=$((i+1)) ;;
        *) i=$((i+1)) ;;
    esac
done

# --- Locate state file ---
STATE_DIR="$PROJECT_DIR/.claude"

find_state_file() {
    if [[ -n "$SESSION_ID" ]]; then
        local candidate="$STATE_DIR/overnight-state-${SESSION_ID}.json"
        if [[ -f "$candidate" ]]; then
            echo "$candidate"
            return
        fi
        echo "Error: State file not found: $candidate" >&2
        return 1
    fi

    # Auto-detect: newest overnight-state-*.json
    local newest
    newest=$(find "$STATE_DIR" -maxdepth 1 -name 'overnight-state-*.json' -printf '%T@ %p\n' 2>/dev/null \
        | sort -rn | head -1 | cut -d' ' -f2-)
    if [[ -n "$newest" && -f "$newest" ]]; then
        echo "$newest"
        return
    fi

    echo "Error: No overnight state file found in $STATE_DIR" >&2
    return 1
}

STATE_FILE="$(find_state_file)"
TMP_FILE="${STATE_FILE}.tmp"

# --- Auto-type a value for --set ---
# Returns a jq expression that produces the typed value
auto_type_value() {
    local val="$1"
    case "$val" in
        null)   echo "null" ;;
        true)   echo "true" ;;
        false)  echo "false" ;;
        *)
            if [[ "$val" =~ ^-?[0-9]+$ ]]; then
                echo "$val"
            else
                # String — use jq --arg for safe escaping (caller handles this)
                echo "__string__"
            fi
            ;;
    esac
}

# --- Build jq filter from operations ---
JQ_FILTER="."
JQ_ARGS=()
ARG_COUNTER=0

i=0
while [[ $i -lt ${#OPS[@]} ]]; do
    op="${OPS[$i]}"
    case "$op" in
        set)
            key="${OPS[$((i+1))]}"
            val="${OPS[$((i+2))]}"
            typed=$(auto_type_value "$val")
            if [[ "$typed" == "__string__" ]]; then
                arg_name="arg${ARG_COUNTER}"
                ARG_COUNTER=$((ARG_COUNTER + 1))
                JQ_ARGS+=(--arg "$arg_name" "$val")
                JQ_FILTER="${JQ_FILTER} | .${key} = \$${arg_name}"
            else
                JQ_FILTER="${JQ_FILTER} | .${key} = ${typed}"
            fi
            i=$((i + 3))
            ;;
        set-json)
            key="${OPS[$((i+1))]}"
            json_val="${OPS[$((i+2))]}"
            arg_name="arg${ARG_COUNTER}"
            ARG_COUNTER=$((ARG_COUNTER + 1))
            JQ_ARGS+=(--argjson "$arg_name" "$json_val")
            JQ_FILTER="${JQ_FILTER} | .${key} = \$${arg_name}"
            i=$((i + 3))
            ;;
        inc)
            key="${OPS[$((i+1))]}"
            JQ_FILTER="${JQ_FILTER} | .${key} = (.${key} + 1)"
            i=$((i + 2))
            ;;
        append)
            key="${OPS[$((i+1))]}"
            val="${OPS[$((i+2))]}"
            arg_name="arg${ARG_COUNTER}"
            ARG_COUNTER=$((ARG_COUNTER + 1))
            JQ_ARGS+=(--arg "$arg_name" "$val")
            JQ_FILTER="${JQ_FILTER} | .${key} = (.${key} + [\$${arg_name}])"
            i=$((i + 3))
            ;;
        append-json)
            key="${OPS[$((i+1))]}"
            json_val="${OPS[$((i+2))]}"
            arg_name="arg${ARG_COUNTER}"
            ARG_COUNTER=$((ARG_COUNTER + 1))
            JQ_ARGS+=(--argjson "$arg_name" "$json_val")
            JQ_FILTER="${JQ_FILTER} | .${key} = (.${key} + [\$${arg_name}])"
            i=$((i + 3))
            ;;
        update-issue)
            idx="${OPS[$((i+1))]}"
            key="${OPS[$((i+2))]}"
            val="${OPS[$((i+3))]}"
            typed=$(auto_type_value "$val")
            if [[ "$typed" == "__string__" ]]; then
                arg_name="arg${ARG_COUNTER}"
                ARG_COUNTER=$((ARG_COUNTER + 1))
                JQ_ARGS+=(--arg "$arg_name" "$val")
                JQ_FILTER="${JQ_FILTER} | .current_issues[${idx}].${key} = \$${arg_name}"
            else
                JQ_FILTER="${JQ_FILTER} | .current_issues[${idx}].${key} = ${typed}"
            fi
            i=$((i + 4))
            ;;
        inc-issue)
            idx="${OPS[$((i+1))]}"
            key="${OPS[$((i+2))]}"
            JQ_FILTER="${JQ_FILTER} | .current_issues[${idx}].${key} = (.current_issues[${idx}].${key} + 1)"
            i=$((i + 3))
            ;;
        inc-fail)
            desc="${OPS[$((i+1))]}"
            arg_name="arg${ARG_COUNTER}"
            ARG_COUNTER=$((ARG_COUNTER + 1))
            JQ_ARGS+=(--arg "$arg_name" "$desc")
            JQ_FILTER="${JQ_FILTER} | .failed_attempts[\$${arg_name}] = ((.failed_attempts[\$${arg_name}] // 0) + 1)"
            i=$((i + 2))
            ;;
        cycle-reset)
            JQ_FILTER="${JQ_FILTER} | .cycle_count = (.cycle_count + 1) | .current_phase = \"exploring\" | .current_issues = [] | .unresolved_issues = []"
            i=$((i + 1))
            ;;
        *)
            echo "Internal error: unknown op '$op'" >&2
            exit 1
            ;;
    esac
done

# --- Apply jq filter atomically ---
echo "Applying to: $STATE_FILE" >&2
echo "Filter: $JQ_FILTER" >&2

if ! jq "${JQ_ARGS[@]}" "$JQ_FILTER" "$STATE_FILE" > "$TMP_FILE"; then
    rm -f "$TMP_FILE"
    echo "Error: jq filter failed — state file not modified" >&2
    exit 1
fi

# Validate output is valid JSON
if ! jq empty "$TMP_FILE" 2>/dev/null; then
    rm -f "$TMP_FILE"
    echo "Error: jq produced invalid JSON — state file not modified" >&2
    exit 1
fi

mv "$TMP_FILE" "$STATE_FILE"

# --- Summary to stderr ---
echo "Updated overnight state: $STATE_FILE" >&2

echo "STATE_PATH=$STATE_FILE"
