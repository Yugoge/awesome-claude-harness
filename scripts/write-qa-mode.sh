#!/usr/bin/env bash
# Write or update qa_mode field in the QA sentinel file for a dev-registry session.
# Usage: write-qa-mode.sh --session-id <dev-SESSION_ID> --mode <ba_validation|final_verification> [--task-id <TASK_ID>] [--init-if-missing]
# --task-id is optional and additive: it anchors subagentstop-e2e-enforce.py's
# task_id-based correlation dimension. Omitting it leaves the sentinel's
# task_id field absent -- fully backward compatible with every pre-fix caller.
# --init-if-missing is optional and additive: pre-creates the sentinel with
# the minimal {"agent_type": "qa", "session_id": ...} shape when absent, then
# falls through to the normal write below. No-op when the sentinel already
# exists -- existing --mode/--task-id behavior is unchanged in that case.
# Exits 1 on failure; callers must abort if this script fails.
set -euo pipefail

SESSION_ID=""
MODE=""
TASK_ID=""
INIT_IF_MISSING=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --session-id) SESSION_ID="$2"; shift 2 ;;
    --mode)       MODE="$2"; shift 2 ;;
    --task-id)    TASK_ID="$2"; shift 2 ;;
    --init-if-missing) INIT_IF_MISSING=1; shift 1 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

[[ -n "$SESSION_ID" ]] || { echo "ERROR: --session-id required" >&2; exit 1; }
[[ -n "$MODE" ]] || { echo "ERROR: --mode required" >&2; exit 1; }
[[ "$SESSION_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || { echo "ERROR: --session-id contains unsafe characters: $SESSION_ID" >&2; exit 1; }
[[ "$MODE" == "ba_validation" || "$MODE" == "final_verification" ]] || { echo "ERROR: --mode must be ba_validation or final_verification, got: $MODE" >&2; exit 1; }
[[ -z "$TASK_ID" || "$TASK_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || { echo "ERROR: --task-id contains unsafe characters: $TASK_ID" >&2; exit 1; }

REGISTRY_DIR="${CLAUDE_PROJECT_DIR:?CLAUDE_PROJECT_DIR not set}/.claude/dev-registry/$SESSION_ID"
QA_PATH="$REGISTRY_DIR/qa.json"

# --init-if-missing: pre-create the sentinel with the minimal shape when
# absent, mirroring the inline block this flag replaces in commands/close.md.
# No-op when the sentinel already exists -- never overwrites, and the
# existing --mode/--task-id behavior below is completely unchanged for that
# case.
if [[ "$INIT_IF_MISSING" == "1" && ! -f "$QA_PATH" ]]; then
  mkdir -p "$REGISTRY_DIR"
  printf '{"agent_type": "qa", "session_id": "%s"}\n' "$SESSION_ID" > "$QA_PATH"
fi

# Activate venv so python3 runs in a managed environment. Prefer a per-project
# venv (.venv/ or venv/), else fall back to the global ~/.claude install (the
# single tool home). The inline python below is stdlib-only, so activation
# failure is non-fatal (|| true) and system python3 still works from any repo.
# shellcheck disable=SC1091
source "${CLAUDE_PROJECT_DIR}/.venv/bin/activate" 2>/dev/null \
  || source "${CLAUDE_PROJECT_DIR}/venv/bin/activate" 2>/dev/null \
  || source "$HOME/.claude/venv/bin/activate" 2>/dev/null \
  || true

python3 - "$QA_PATH" "$MODE" "$SESSION_ID" "$TASK_ID" <<'PYEOF'
import json, os, sys
path, mode, sid, tid = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

def die(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)

# The sentinel is PRE-CREATED by the launcher (overnight-init.sh, or the /dev
# Step-1 hook) and carries the agent_type/session_id fields the enforcement chain
# resolves subagents through. Creating or repairing it here would quietly destroy
# those fields and leave enforcement failing open, so an absent, unparseable, or
# foreign-session sentinel is a LOUD refusal that touches nothing -- never a
# silent rewrite. Writing stays IN PLACE (no temp+rename): under the overnight
# boundary this file is a bind mountpoint and rename() over it returns EBUSY.
if not os.path.exists(path):
    die(f"qa sentinel missing (initialization did not run): {path}")
try:
    with open(path) as f:
        data = json.load(f)
except Exception as exc:
    die(f"qa sentinel is not readable JSON ({exc}): {path}")
if not isinstance(data, dict):
    die(f"qa sentinel is not a JSON object: {path}")
if data.get('agent_type') != 'qa':
    die(f"qa sentinel agent_type={data.get('agent_type')!r}, expected 'qa': {path}")
if data.get('session_id') != sid:
    die(f"qa sentinel session_id={data.get('session_id')!r} != --session-id {sid!r}: {path}")
data['qa_mode'] = mode
if tid:
    data['task_id'] = tid
with open(path, 'w') as f:
    json.dump(data, f)
print(f"qa_mode={mode} written to {path}" + (f" (task_id={tid})" if tid else ""), file=sys.stderr)
PYEOF
