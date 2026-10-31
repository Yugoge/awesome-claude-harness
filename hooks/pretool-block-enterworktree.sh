#!/bin/bash
# PreToolUse hook: Block EnterWorktree tool
# EnterWorktree always bases worktree on origin/main (remote upstream), NOT local HEAD.
# For forked repos this silently replaces local code with upstream code.
# Use ~/.claude/scripts/create-worktree.sh instead.
# Exit 2 = block
#
# /do consent flag and /allow EnterWorktree grant bypass the block for the
# main agent only (subagents remain unconditionally blocked — they should
# use the safety script directly). See CLAUDE.md permanent-block list
# (EnterPlanMode/ExitPlanMode only).

# Read full JSON from stdin
INPUT=$(cat)

# Extract tool name (fail-open on parse failure)
TOOL_NAME=$(echo "$INPUT" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print(d.get('tool_name',''))" \
  2>/dev/null)

# Only act on EnterWorktree
if [ "$TOOL_NAME" != "EnterWorktree" ]; then
    exit 0
fi

# dev-overnight exception: a live /dev-overnight session may create worktrees.
# Mirrors pretool-block-branch-pr-worktree.py — overnight is the always-on
# exception and applies to subagents too, so it precedes the subagent block.
_BEW_OV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_BEW_OV_CWD=$(echo "$INPUT" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print(d.get('cwd','') or '')" \
  2>/dev/null)
if HOOKS_DIR="$_BEW_OV_DIR" BEW_OV_CWD="$_BEW_OV_CWD" python3 - <<'OVEOF' 2>/dev/null
import os, sys
sys.path.insert(0, os.environ["HOOKS_DIR"])
try:
    from lib.overnight import is_overnight_active
    sys.exit(0 if is_overnight_active(os.environ.get("BEW_OV_CWD") or None) else 1)
except Exception:
    sys.exit(1)
OVEOF
then
  exit 0
fi

# /do bypass: hooks/lib/allowlist.py has_do_consent (main agent only).
if printf '%s' "$INPUT" | python3 "$_BEW_OV_DIR/lib/allowlist.py" consent 2>/dev/null; then
  exit 0
fi
# /allow bypass (main-agent only) — lib/allowlist.match_sentinel_grant_for_tool
_BEW_IS_SUB=$(echo "$INPUT" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print('1' if d.get('agent_id') else '0')" \
  2>/dev/null)
if [ "$_BEW_IS_SUB" != "1" ]; then
  _BEW_SID=$(echo "$INPUT" | python3 -c \
    "import json,sys,os; d=json.load(sys.stdin); \
print(d.get('session_id','') or os.environ.get('CLAUDE_SESSION_ID','default'))" \
    2>/dev/null)
  [ -z "$_BEW_SID" ] && _BEW_SID="default"
  _BEW_MATCHED=$(HOOKS_DIR="$_BEW_OV_DIR" BEW_SID="$_BEW_SID" python3 - <<'BEWEOF'
import os, sys
sys.path.insert(0, os.environ["HOOKS_DIR"])
from lib.allowlist import match_sentinel_grant_for_tool
if match_sentinel_grant_for_tool(os.environ["BEW_SID"], "EnterWorktree") is not None:
    print("1")
BEWEOF
)
  if [ "$_BEW_MATCHED" = "1" ]; then
    exit 0
  fi
fi

cat >&2 << 'EOF'
BLOCKED: EnterWorktree uses origin/main as start point, not local HEAD.
This causes worktrees to contain upstream code instead of local changes.

Use this instead:
  bash ~/.claude/scripts/create-worktree.sh <name>

It creates a worktree from HEAD and prints the path.
EOF
exit 2
