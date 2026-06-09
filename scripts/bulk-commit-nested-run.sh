#!/usr/bin/env bash
# One-shot bulk commit script for the nested dot-claude repo.
# Called by changelog-analyst subagent. Safe to delete after run.
set -uo pipefail

GIT_ROOT=/dev/shm/dev-workspace/dot-claude
BRANCH=$(git -C "${GIT_ROOT}" rev-parse --abbrev-ref HEAD)
# Acquire lock — hold across all operations.
# Lock + temp files live under /tmp (deterministic sha256-of-toplevel name keeps the
# per-repo mutual-exclusion guarantee), NOT under the repo's protected bundle dir, which
# the runtime guard correctly blocks as a protected-bundle write. Matches the relocated /tmp scheme
# the live changelog-analyst flow uses (agents/changelog-analyst.md Phase 3): the
# redirect target MUST start with a literal /tmp prefix — a leading ${VAR} is re-joined
# to the protected cwd and re-triggers the brace-glob false positive.
mkdir -p /tmp/agentic-commit/locks
REPO_HASH="$(printf '%s' "$(git -C "${GIT_ROOT}" rev-parse --show-toplevel)" | sha256sum | cut -c1-16)"
exec 9>"/tmp/agentic-commit/locks/${REPO_HASH}.lock"
flock -w 30 -x 9 || {
    echo "ERROR: could not acquire /tmp/agentic-commit/locks/${REPO_HASH}.lock within 30s — another commit in progress?"
    exit 1
}
echo "Lock acquired."

FAILED_GROUPS=()

# ── Status ───────────────────────────────────────────────────────────────────
STATUS=$(git -C "${GIT_ROOT}" status --porcelain=v1)
echo "Current status:"
echo "${STATUS}"
echo "---"

if [ -z "${STATUS}" ]; then
    echo "No changes to commit."
    exit 0
fi

# ── Classify files ────────────────────────────────────────────────────────────
COMMANDS_FILES=()
DOCS_FILES=()
MISC_FILES=()

while IFS= read -r line; do
    SC1="${line:0:1}"
    SC2="${line:1:1}"
    FILE_PATH="${line:3}"
    if [[ "${SC1}" == "R" || "${SC2}" == "R" ]]; then
        FILE_PATH="${line##*-> }"
    fi
    FILE_PATH="${FILE_PATH# }"

    BASENAME=$(basename "${FILE_PATH}")
    BNAME_LC="${BASENAME,,}"
    if [[ "${BNAME_LC}" == ".env" || "${BNAME_LC}" == *".key" || "${BNAME_LC}" == *".pem" || \
          "${BNAME_LC}" == *"password"* || "${BNAME_LC}" == *"secret"* || "${BNAME_LC}" == *"credential"* ]]; then
        echo "SKIP (secret pattern): ${FILE_PATH}"
        continue
    fi

    if [[ "${FILE_PATH}" == commands/* ]]; then
        COMMANDS_FILES+=("${FILE_PATH}")
    elif [[ "${FILE_PATH}" == docs/* ]]; then
        DOCS_FILES+=("${FILE_PATH}")
    else
        MISC_FILES+=("${FILE_PATH}")
    fi
done <<< "${STATUS}"

echo "Commands files: ${COMMANDS_FILES[*]:-none}"
echo "Docs files: ${DOCS_FILES[*]:-none}"
echo "Misc files: ${MISC_FILES[*]:-none}"
echo "---"

# ── Pre-staged verification ───────────────────────────────────────────────────
CACHED=$(git -C "${GIT_ROOT}" diff --cached --name-only 2>/dev/null || true)
if [ -n "${CACHED}" ]; then
    while IFS= read -r cached_file; do
        FOUND=0
        for f in "${COMMANDS_FILES[@]:-}" "${DOCS_FILES[@]:-}" "${MISC_FILES[@]:-}"; do
            if [ "${f}" = "${cached_file}" ]; then FOUND=1; break; fi
        done
        if [ "${FOUND}" -eq 0 ]; then
            echo "Pre-staged verify: unstaging ${cached_file} (not in classified set)"
            git -C "${GIT_ROOT}" restore --staged -- "${cached_file}"
        fi
    done <<< "${CACHED}"
fi

# ── commit_group function ─────────────────────────────────────────────────────
commit_group() {
    local SCOPE="$1"
    shift
    local FILES=("$@")

    if [ "${#FILES[@]}" -eq 0 ]; then
        echo "Group ${SCOPE}: no files, skipping."
        return 0
    fi

    echo "Staging group ${SCOPE}: ${FILES[*]}"
    for f in "${FILES[@]}"; do
        SC=$(git -C "${GIT_ROOT}" status --porcelain=v1 -- "${f}" 2>/dev/null | head -1 | cut -c1-2 || true)
        if [[ "${SC}" == " D" || "${SC}" == "D " || "${SC}" == "DD" ]]; then
            git -C "${GIT_ROOT}" rm -- "${f}" || echo "WARN: rm failed for ${f}"
        else
            git -C "${GIT_ROOT}" add -- "${f}" || echo "WARN: add failed for ${f}"
        fi
    done

    if git -C "${GIT_ROOT}" rev-parse --verify HEAD >/dev/null 2>&1; then
        DIFFSTAT=$(git -C "${GIT_ROOT}" diff --stat HEAD 2>/dev/null || true)
    else
        DIFFSTAT=$(git -C "${GIT_ROOT}" diff --stat --cached 2>/dev/null || true)
    fi
    if [ -z "${DIFFSTAT}" ]; then
        DIFFSTAT=$(git -C "${GIT_ROOT}" diff --stat --cached 2>/dev/null || true)
    fi

    MSGFILE=$(mktemp "/tmp/agentic-commit/commit-msg-XXXXXX.txt")
    # shellcheck disable=SC2064
    trap "rm -f ${MSGFILE}" EXIT

    printf '%s\n' \
        "auto-bulk: end-of-cycle commit for ${BRANCH} — ${SCOPE} updates" \
        "" \
        "Task-id: bulk" \
        "${DIFFSTAT}" \
        "" \
        "Generated with [Claude Code](https://claude.ai/code)" \
        "via [Happy](https://happy.engineering)" \
        "" \
        "Co-Authored-By: Claude <noreply@anthropic.com>" \
        "Co-Authored-By: Happy <yesreply@happy.engineering>" \
        > "${MSGFILE}"

    echo "Commit message for ${SCOPE}:"
    cat "${MSGFILE}"
    echo "---"

    if ! git -C "${GIT_ROOT}" commit -F "${MSGFILE}"; then
        echo "WARNING: Failed to commit group ${SCOPE}. Skipping and continuing."
        git -C "${GIT_ROOT}" restore --staged -- "${FILES[@]}" 2>/dev/null || true
        FAILED_GROUPS+=("${SCOPE}")
        rm -f "${MSGFILE}"
        return 0
    fi

    rm -f "${MSGFILE}"
    COMMIT_SHA=$(git -C "${GIT_ROOT}" rev-parse HEAD)
    echo "Committed ${SCOPE}: ${COMMIT_SHA}"
}

# ── Execute groups ────────────────────────────────────────────────────────────
commit_group "commands" "${COMMANDS_FILES[@]:-}"
commit_group "docs" "${DOCS_FILES[@]:-}"
commit_group "misc" "${MISC_FILES[@]:-}"

# ── Final verification ────────────────────────────────────────────────────────
FINAL_STATUS=$(git -C "${GIT_ROOT}" status --porcelain=v1)
if [ -z "${FINAL_STATUS}" ]; then
    echo "All changes committed in nested repo."
else
    echo "WARNING: remaining changes after commit:"
    echo "${FINAL_STATUS}"
fi

COMMIT_SHA=$(git -C "${GIT_ROOT}" rev-parse HEAD)
echo "FINAL_SHA=${COMMIT_SHA}"
echo "FINAL_BRANCH=${BRANCH}"
echo "FINAL_GIT_ROOT=${GIT_ROOT}"

if [ "${#FAILED_GROUPS[@]}" -gt 0 ]; then
    echo "Bulk complete with failures: ${FAILED_GROUPS[*]}"
    exit 2
else
    echo "Bulk complete. All groups committed successfully."
fi
