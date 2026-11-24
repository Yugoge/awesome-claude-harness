#!/bin/bash
# PreToolUse hook: Block EnterWorktree tool
# EnterWorktree always bases worktree on origin/main (remote upstream), NOT local HEAD.
# For forked repos this silently replaces local code with upstream code.
# Use ~/.claude/scripts/create-worktree.sh instead.
# Exit 2 = block
#
# /do consent bypasses the block for the main agent only; an owner's /allow
# grant releases it for any actor, in the launcher that runs this hook.
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib/harness_switch.sh" 2>/dev/null && harness_switch_exit_if_off  # the harness switch: no harness hook runs while /harness off holds

# Read full JSON from stdin
INPUT=$(cat)
. "$(dirname "${BASH_SOURCE[0]}")/lib/refusal_record.sh" 2>/dev/null && trap refusal_record_on_exit EXIT  # one refusal record when this hook refuses

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
# An /allow grant releases this refusal in hooks/pretool-launch.py, which runs this hook
# (lib/hook_launch.release_refused).

_SAID=$(cat << 'EOF'
BLOCKED: EnterWorktree uses origin/main as start point, not local HEAD.
This causes worktrees to contain upstream code instead of local changes.

Use this instead:
  bash ~/.claude/scripts/create-worktree.sh <name>

It creates a worktree from HEAD and prints the path.
EOF
)
printf '%s\n' "$_SAID" >&2
exit 2
