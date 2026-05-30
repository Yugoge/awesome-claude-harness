#!/usr/bin/env bash
# Description: Recovery path helpers for nothing_to_commit_precommitted detection.
# Usage: precommitted-recovery.sh <operation> <git_root> [additional args]
#   Operations:
#     scan-shas <git_root> <baseline_head_sha> <task_cycle_files_space_separated>
#     build-commit-msg <git_root> <scope> <task_id> <tmpfile> <precommitted_shas_space_separated> <attributed_files_space_separated>
#     execute-commit <git_root> <tmpfile>
#     capture-sha <git_root>
# Exit codes: 0=success, 1=failure

set -euo pipefail

OPERATION="${1:?Missing operation (scan-shas|build-commit-msg|execute-commit|capture-sha)}"
GIT_ROOT="${2:?Missing git_root}"
VENV_DIR="${VENV_DIR:-venv}"

source "${VENV_DIR}/bin/activate" 2>/dev/null || true

case "${OPERATION}" in

  scan-shas)
    # Scan baseline_head_sha..HEAD for auto-bulk commits touching task_cycle_files.
    # Args: scan-shas <git_root> <baseline_head_sha> <task_cycle_files...>
    BASELINE_HEAD_SHA="${3:?Missing baseline_head_sha}"
    shift 3
    task_cycle_files=("$@")

    precommitted_shas=()
    while IFS=' ' read -r sha subject; do
        commit_files=$(git -C "${GIT_ROOT}" show --name-only --format= "$sha" | grep -v '^$')
        for f in "${task_cycle_files[@]}"; do
            if echo "$commit_files" | grep -qF "$f"; then
                precommitted_shas+=("$sha")
                break
            fi
        done
    done < <(git -C "${GIT_ROOT}" log --format="%H %s" "${BASELINE_HEAD_SHA}..HEAD" | awk '{sha=$1; $1=""; sub(/^ /, ""); if (/^auto-bulk:/) print sha}')

    printf '%s\n' "${precommitted_shas[@]}"
    ;;

  build-commit-msg)
    # Build recovery commit message into a tmpfile.
    # Args: build-commit-msg <git_root> <scope> <task_id> <tmpfile> <shas...> -- <files...>
    SCOPE="${3:?Missing scope}"
    TASK_ID="${4:?Missing task_id}"
    TMPFILE="${5:?Missing tmpfile}"
    shift 5

    precommitted_shas=()
    attributed_files=()
    in_files=false
    for arg in "$@"; do
        if [[ "$arg" == "--" ]]; then
            in_files=true
            continue
        fi
        if $in_files; then
            attributed_files+=("$arg")
        else
            precommitted_shas+=("$arg")
        fi
    done

    umask 077
    {
        echo "chore(${SCOPE}): recovery commit — task ${TASK_ID} pre-empted by bulk session"
        echo ""
        echo "Task-id: ${TASK_ID}"
        for sha in "${precommitted_shas[@]}"; do
            echo "Precommitted-by: ${sha}"
        done
        echo "Attributed-files:"
        for f in "${attributed_files[@]}"; do
            echo "  ${f}"
        done
    } > "${TMPFILE}"
    ;;

  execute-commit)
    # Execute recovery commit using tmpfile.
    # Args: execute-commit <git_root> <tmpfile>
    TMPFILE="${3:?Missing tmpfile}"
    trap "rm -f ${TMPFILE}" EXIT
    git -C "${GIT_ROOT}" commit --allow-empty -F "${TMPFILE}"
    ;;

  capture-sha)
    # Capture recovery commit SHA and branch, print as: <sha> <branch>
    # Args: capture-sha <git_root>
    COMMIT_SHA=$(git -C "${GIT_ROOT}" rev-parse HEAD)
    BRANCH=$(git -C "${GIT_ROOT}" rev-parse --abbrev-ref HEAD)
    echo "${COMMIT_SHA} ${BRANCH}"
    ;;

  *)
    echo "Error: Unknown operation '${OPERATION}'" >&2
    echo "Valid operations: scan-shas, build-commit-msg, execute-commit, capture-sha" >&2
    exit 1
    ;;

esac
