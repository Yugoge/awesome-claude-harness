#!/bin/bash
# Resolve the close-report path for a given TASK_ID using subproject path-walk.
#
# Mirrors the Step 6 changelog-analyst fallback strategy (commit.md): probe the
# most-specific subproject docs/dev/ first, fall back to /root/docs/dev/.
# Handles nested-repo cycles where the close-report lives at
# /root/.claude/docs/dev/... (symlinked to the actual nested working tree)
# rather than /root/docs/dev/.
#
# Usage: resolve-close-report.sh <TASK_ID>
# Output: prints resolved path to stdout
#   - existing file's path when a candidate exists (exit 0)
#   - fallback CONTROL_ROOT path when no candidate exists (exit 1, path still
#     printed so caller can use it in error messages)

set -u
TASK_ID="${1:?usage: resolve-close-report.sh <TASK_ID>}"
CONTROL_ROOT="${CONTROL_ROOT:-/root}"

# git-toplevel-of-cwd candidate: when /close runs with cwd inside a (possibly
# nested) repo, probe that repo's docs/dev/ before the control-root fallback.
# Empty/failed git lookup yields an empty candidate, which the -n guard skips.
GIT_TOPLEVEL="$(git rev-parse --show-toplevel 2>/dev/null || true)"

for candidate in \
    "${CLAUDE_PROJECT_DIR:-}/docs/dev/close-report-${TASK_ID}.md" \
    "${GIT_TOPLEVEL:+${GIT_TOPLEVEL}/docs/dev/close-report-${TASK_ID}.md}" \
    "/root/.claude/docs/dev/close-report-${TASK_ID}.md" \
    "${CONTROL_ROOT}/docs/dev/close-report-${TASK_ID}.md"; do
    if [ -n "$candidate" ] && [ -f "$candidate" ]; then
        echo "$candidate"
        exit 0
    fi
done

# No candidate found — emit fallback path for error message, exit 1.
echo "${CONTROL_ROOT}/docs/dev/close-report-${TASK_ID}.md"
exit 1
