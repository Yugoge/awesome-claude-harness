#!/bin/bash
# Create a git worktree from local HEAD (not origin/main).
# Usage: bash ~/.claude/scripts/create-worktree.sh [--project-dir <dir>] <name>
# Output (last line, ONLY after validation): WORKTREE_PATH=<path> WORKTREE_BRANCH=<branch>
#
# M4 hardening (task 20260604-204954):
#   * Accept --project-dir; use `git -C "$PROJECT_DIR"` for all git ops.
#   * NON-resetting, nonce-unique branch creation (`worktree add -b`, never -B);
#     never reset/reuse an existing branch.
#   * An existing target dir is success ONLY if it is the registered worktree for
#     the expected branch AND validates; otherwise retry under a unique name
#     (never reuse a bogus dir).
#   * cleanup trap removes a partial worktree on validation failure.
#   * Emit WORKTREE_PATH/WORKTREE_BRANCH ONLY after full validation; fail closed.

set -euo pipefail

PROJECT_DIR=""
NAME=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --project-dir) PROJECT_DIR="$2"; shift 2 ;;
        *) NAME="$1"; shift ;;
    esac
done
[[ -n "$NAME" ]] || { echo "Usage: create-worktree.sh [--project-dir <dir>] <name>" >&2; exit 1; }

if [[ -n "$PROJECT_DIR" ]]; then
    GIT_ROOT="$(git -C "$PROJECT_DIR" rev-parse --show-toplevel)"
else
    GIT_ROOT="$(git rev-parse --show-toplevel)"
fi
GITC=(git -C "$GIT_ROOT")

WORKTREE_BASE_DIR="${GIT_ROOT}/.claude/worktrees"
mkdir -p "$WORKTREE_BASE_DIR"

CAPTURED_HEAD="$("${GITC[@]}" rev-parse HEAD)"

# --- validation helper: is <dir> a registered worktree on <branch> at HEAD? ---
validate_worktree() {
    local wt="$1" branch="$2"
    [[ -n "$wt" && -d "$wt" ]] || return 1
    local rp_wt rp_main
    rp_wt="$(realpath "$wt" 2>/dev/null || echo "$wt")"
    rp_main="$(realpath "$GIT_ROOT" 2>/dev/null || echo "$GIT_ROOT")"
    [[ "$rp_wt" != "$rp_main" ]] || return 1
    # present in worktree list
    "${GITC[@]}" worktree list --porcelain 2>/dev/null | grep -Fxq "worktree $rp_wt" || \
        "${GITC[@]}" worktree list --porcelain 2>/dev/null | grep -Fxq "worktree $wt" || return 1
    # toplevel resolves to the worktree
    local top
    top="$(git -C "$wt" rev-parse --show-toplevel 2>/dev/null || echo '')"
    [[ "$(realpath "$top" 2>/dev/null || echo "$top")" == "$rp_wt" ]] || return 1
    # branch matches and is not master
    local cur
    cur="$(git -C "$wt" branch --show-current 2>/dev/null || echo '')"
    [[ "$cur" == "$branch" && "$cur" != "master" ]] || return 1
    return 0
}

# --- pick a unique, non-reused (path,branch) pair ---
make_worktree() {
    local attempt suffix wt branch
    for attempt in 0 1 2 3 4; do
        if [[ "$attempt" -eq 0 ]]; then suffix=""; else suffix="-r${attempt}-$$"; fi
        wt="${WORKTREE_BASE_DIR}/${NAME}${suffix}"
        branch="worktree-${NAME}${suffix}"
        # If the target dir already exists, accept ONLY if it validates; else skip.
        if [[ -e "$wt" ]]; then
            if validate_worktree "$wt" "$branch"; then
                echo "Reusing valid registered worktree at ${wt}" >&2
                printf '%s\t%s' "$wt" "$branch"
                return 0
            fi
            echo "Existing dir ${wt} is not a valid registered worktree; trying a unique name" >&2
            continue
        fi
        # Branch must not already exist (non-resetting): skip name if it does.
        if "${GITC[@]}" show-ref --verify --quiet "refs/heads/${branch}"; then
            echo "Branch ${branch} already exists; trying a unique name" >&2
            continue
        fi
        # Create with a cleanup trap so a partial add does not leak.
        local created=0
        trap '[[ "$created" -eq 1 ]] && "${GITC[@]}" worktree remove --force "$wt" 2>/dev/null || rmdir "$wt" 2>/dev/null || true' RETURN
        if "${GITC[@]}" worktree add -b "$branch" "$wt" "$CAPTURED_HEAD" >&2; then
            created=1
            if validate_worktree "$wt" "$branch"; then
                trap - RETURN
                echo "Created worktree from $("${GITC[@]}" rev-parse --short "$CAPTURED_HEAD") at ${wt}" >&2
                printf '%s\t%s' "$wt" "$branch"
                return 0
            fi
        fi
        # validation failed -> RETURN trap cleans the partial worktree
        trap - RETURN
        "${GITC[@]}" worktree remove --force "$wt" 2>/dev/null || true
        echo "Worktree creation/validation failed for ${wt}; retrying" >&2
    done
    return 1
}

RESULT="$(make_worktree)" || { echo "Error: could not create a valid isolated worktree after retries" >&2; exit 1; }
WORKTREE_PATH="${RESULT%%$'\t'*}"
BRANCH_NAME="${RESULT##*$'\t'}"

# Auto-renew parent .claude/settings.local.json Write/Edit allow entries for the
# current overnight worktree. Safety boundary is enforced by the overnight hook
# (pretool-overnight-hook-guard.py); these allow entries only skip permission
# prompts inside the worktree. Without renewal, stale overnight-<oldhash> paths
# cause every Write/Edit in the new worktree to hit a prompt.
if [[ "$NAME" == overnight-* ]] && command -v jq >/dev/null 2>&1; then
    SETTINGS="${GIT_ROOT}/.claude/settings.local.json"
    if [ -f "$SETTINGS" ]; then
        WORKTREE_BASE="${GIT_ROOT}/.claude/worktrees/overnight-"
        NEW_WRITE="Write(${WORKTREE_PATH}/**)"
        NEW_EDIT="Edit(${WORKTREE_PATH}/**)"
        TMP="$(mktemp)"
        if jq \
            --arg base "$WORKTREE_BASE" \
            --arg newW "$NEW_WRITE" \
            --arg newE "$NEW_EDIT" '
            .permissions //= {} |
            .permissions.allow //= [] |
            .permissions.allow |= (
                map(select(
                    (startswith("Write(" + $base) | not) and
                    (startswith("Edit("  + $base) | not)
                )) + [$newW, $newE]
            )
        ' "$SETTINGS" > "$TMP" 2>/dev/null; then
            mv "$TMP" "$SETTINGS"
            echo "Refreshed ${SETTINGS} allow entries for ${WORKTREE_PATH}" >&2
        else
            rm -f "$TMP"
            echo "WARN: failed to refresh ${SETTINGS}; keeping existing entries" >&2
        fi
    fi
fi

echo "WORKTREE_PATH=${WORKTREE_PATH} WORKTREE_BRANCH=${BRANCH_NAME}"
