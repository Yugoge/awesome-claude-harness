#!/bin/bash
# PreToolUse Hook - Block Write tool from overwriting existing files
# Forces agents to use Edit for modifying existing files.
# Reads tool input from stdin as JSON (Claude Code hook protocol)

# Read full JSON from stdin
INPUT=$(cat)

# Extract tool name
TOOL_NAME=$(echo "$INPUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('tool_name',''))" 2>/dev/null)

# Layer A — bulk-commit sentinel write block (M4.3 / AC-04,
# task 20260524-205206). Deny ANY Write or NotebookEdit tool call (regardless
# of agent_id; main agent NOT exempt) that targets
# /tmp/claude-bulk-commit-sentinel-*.json.
# The sentinel is written by the orchestrator via /commit --bulk;
# model-tool writes are forbidden.
if [ "$TOOL_NAME" = "Write" ] || [ "$TOOL_NAME" = "NotebookEdit" ]; then
  _BULK_TARGET=$(echo "$INPUT" | python3 -c "import json,sys; d=json.load(sys.stdin); ti=d.get('tool_input',{}); print(ti.get('file_path') or ti.get('notebook_path') or '')" 2>/dev/null)
  case "$_BULK_TARGET" in
    /tmp/claude-bulk-commit-sentinel-*.json)
      echo "BLOCKED: bulk-commit-sentinel-write — writing to /tmp/claude-bulk-commit-sentinel-*.json via $TOOL_NAME is FORBIDDEN" >&2
      echo "Target: $_BULK_TARGET" >&2
      echo "REASON: per task 20260524-205206 M4.3, only the orchestrator via /commit --bulk may" >&2
      echo "        create the bulk-commit sentinel. ALL model tool calls are denied" >&2
      echo "        regardless of agent_id (main agent and subagent equally blocked)." >&2
      exit 2
      ;;
  esac
fi

# Only act on Write tool
if [ "$TOOL_NAME" != "Write" ]; then
  exit 0
fi

# Extract file_path and task_id before any bypass checks (required by sentinel check)
FILE_PATH=$(echo "$INPUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" 2>/dev/null)
# _WG_TASK_ID is passed into the sentinel lookup for backward compat.
# The sentinel lookup uses a de-duped candidate list (see inline Python below).
_WG_TASK_ID=$(echo "$INPUT" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print(d.get('task_id',''))" \
  2>/dev/null)
_WG_ENV_TASK_ID="${CLAUDE_TASK_ID:-}"

# /do bypass (main-agent only)
_WG_IS_SUB=$(echo "$INPUT" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print('1' if d.get('agent_id') else '0')" \
  2>/dev/null)
if [ "$_WG_IS_SUB" != "1" ]; then
  _WG_SID=$(echo "$INPUT" | python3 -c \
    "import json,sys,os; d=json.load(sys.stdin); \
print(d.get('session_id','') or os.environ.get('CLAUDE_SESSION_ID','default'))" \
    2>/dev/null)
  [ -z "$_WG_SID" ] && _WG_SID="default"
  _WG_DO_FLAG="/tmp/claude-orchestrator-consent-${_WG_SID}.flag"
  if [ -f "$_WG_DO_FLAG" ] && [ "$(cat "$_WG_DO_FLAG" 2>/dev/null)" = "true" ]; then
    exit 0
  fi
  # Sentinel-grant bypass (main-agent only) — must check BEFORE legacy /allow grant.
  # CF-1 invariant: if a valid (unexpired, correct-session) sentinel exists for
  # this task but does NOT match the target file, suppress the legacy
  # read_grant("Write") fallback entirely. CF-1 only applies to overwrite
  # attempts (existing files); new-file creation bypasses CF-1 denial.
  _WG_HOOKS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  _WG_SENTINEL_RESULT=$(HOOKS_DIR="$_WG_HOOKS_DIR" WG_SID="$_WG_SID" WG_TASK_ID="$_WG_TASK_ID" WG_ENV_TASK_ID="$_WG_ENV_TASK_ID" WG_FILE_PATH="$FILE_PATH" python3 - <<'WGEOF'
import os, sys
sys.path.insert(0, os.environ["HOOKS_DIR"])
from lib.allowlist import match_sentinel_grant_for_write, load_sentinel_grant_for_task
data_task_id = os.environ.get("WG_TASK_ID", "")
env_task_id = os.environ.get("WG_ENV_TASK_ID", "")
session_id = os.environ["WG_SID"]
target = os.environ["WG_FILE_PATH"]
# Build a writer-aligned candidate list (de-duped, preserving priority).
# The sentinel writer (userprompt-consent-allowlist.sh) keys by CLAUDE_TASK_ID:-SID.
# Priority: (1) writer-preferred key (env CLAUDE_TASK_ID, else session_id),
#           (2) data.task_id (for grants written during subagent/task context),
#           (3) session_id (already covered by #1 when CLAUDE_TASK_ID unset).
writer_key = env_task_id if env_task_id else session_id
seen = set()
candidates = []
for k in [writer_key, data_task_id, session_id]:
    if k and k not in seen:
        seen.add(k)
        candidates.append(k)
# Attempt lookup against all candidates. Return match if any matches;
# valid_no_match if at least one valid same-session sentinel exists but
# none match; none if no valid sentinel found for any candidate.
match_result = None
any_valid_sentinel = False
for key in candidates:
    g = load_sentinel_grant_for_task(key)
    if g is None or g.get("session_id") != session_id:
        continue
    any_valid_sentinel = True
    m = match_sentinel_grant_for_write(key, session_id, target)
    if m is not None:
        match_result = "match"
        break
if match_result == "match":
    print("match")
elif any_valid_sentinel:
    print("valid_no_match")
else:
    print("none")
WGEOF
)
  if [ "$_WG_SENTINEL_RESULT" = "match" ]; then
    exit 0
  fi
  # CF-1: valid same-session sentinel exists but does not match this target.
  # Suppress legacy grant — but ONLY for overwrite attempts (existing files).
  # New-file creation (non-existing file) must not be blocked by an unrelated sentinel.
  if [ "$_WG_SENTINEL_RESULT" = "valid_no_match" ] && [ -f "$FILE_PATH" ]; then
    echo "[Write Guard] BLOCKED: sentinel grant does not cover this target." >&2
    echo "Target: $FILE_PATH" >&2
    echo "A valid sentinel grant exists for this task, but it does NOT name this file," >&2
    echo "so it confers no permission to overwrite it. The grant is scoped on purpose:" >&2
    echo "an approval for one path is not an approval for every path." >&2
    echo "Two ways forward:" >&2
    echo "  1. Re-issue the grant naming this exact path, if overwriting it is genuinely intended." >&2
    echo "  2. Modify the existing file in place (Edit) instead of replacing it wholesale." >&2
    exit 2
  fi
  # /allow bypass (main-agent only) — delegates to lib/allowlist.read_grant("Write", sid)
  _WG_HOOKS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  _WG_ALLOW_FILE="/tmp/claude-bash-allowlist-${_WG_SID}.json"
  if [ -f "$_WG_ALLOW_FILE" ]; then
    _WG_MATCHED=$(HOOKS_DIR="$_WG_HOOKS_DIR" WG_SID="$_WG_SID" python3 - <<'WGEOF'
import os, sys
sys.path.insert(0, os.environ["HOOKS_DIR"])
from lib.allowlist import read_grant
if read_grant("Write", os.environ["WG_SID"]):
    print("1")
WGEOF
)
    if [ "$_WG_MATCHED" = "1" ]; then
      exit 0
    fi
  fi
fi

# If we couldn't extract a file path, allow (don't block on parse errors)
if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Check if the file already exists
if [ -f "$FILE_PATH" ]; then
  echo "[Write Guard] BLOCKED: File already exists: $FILE_PATH" >&2
  echo "Write would replace this file wholesale, so every byte of the new content has to be" >&2
  echo "reproduced from memory. Any field you forgot to carry over, or mis-remembered, would be" >&2
  echo "silently lost — there is no diff to reveal what went missing." >&2
  echo "Modify the existing file IN PLACE instead (Edit), changing only the fields that need to" >&2
  echo "change. Reserve Write for files that genuinely do not exist yet." >&2
  exit 2
fi

# File does not exist — allow creation
exit 0
