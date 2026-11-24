#!/usr/bin/env bash
# UserPromptSubmit Hook: the owner's /allow grant, and its end at the owner's next prompt.
#
# Every prompt the owner types ends the session's grant (hooks/lib/allowlist.py remove_grant): a
# grant lives until it is spent or until the next prompt, with no clock limit inside the turn.
# A typed `/allow [text]` then writes a new one (write_sentinel_grant) whose scope is what
# allowlist.recognise makes of the text: a tool name or a command restricts it to a refused call of
# that tool or command; anything else (nothing, free text) lets through the next refused call,
# whatever it is. The pre-tool launcher releases and spends it (lib/hook_launch.release_refused).
# A subagent's payload (agent_id) never makes, extends or removes a grant. The notice the owner sees
# says which of the two was recorded. The deny list is a pre-tool rule (hooks/pretool-deny-list.py),
# released like any other; the two switch rules settings.json permissions.deny keeps are the CLI's own,
# not a hook's: no grant releases what they deny.
#
# Exit 0 always.
. "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/lib/harness_switch.sh" 2>/dev/null && harness_switch_exit_if_off  # the harness switch: no harness hook runs while /harness off holds
set -u

# Hook runtime-state root (lib/harness_state_dir.sh: CLAUDE_STATE_DIR, else on disk).
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)/lib/harness_state_dir.sh" 2>/dev/null \
  || { echo "[allow] ERROR: hooks/lib/harness_state_dir.sh is missing; no grant was issued." >&2; exit 0; }

INPUT=$(cat)

# ── Step 0: subagent write firewall ─────────────────────────────────
IS_SUBAGENT=$(echo "$INPUT" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print('1' if d.get('agent_id') else '0')" \
  2>/dev/null)
if [ "$IS_SUBAGENT" = "1" ]; then
  exit 0
fi

# ── Step 1: extract prompt + session_id ────────────────────────────
PROMPT=$(echo "$INPUT" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print(d.get('prompt',''))" \
  2>/dev/null)
SID=$(echo "$INPUT" | python3 -c \
  "import json,sys,os; d=json.load(sys.stdin); print(d.get('session_id','') or os.environ.get('CLAUDE_SESSION_ID','default'))" \
  2>/dev/null)
[ -z "$SID" ] && SID="default"

# ── The grant ends at the owner's next prompt, and /allow writes a new one ──
case "$PROMPT" in
  "/allow"[[:space:]]*|"/allow") ALLOW_TEXT="${PROMPT#/allow}" ;;
  *) ALLOW_TEXT=""; PROMPT_IS_ALLOW=false ;;
esac
NOTICE=$(ALLOW_TEXT="$ALLOW_TEXT" ALLOW_WRITE="${PROMPT_IS_ALLOW:-true}" SID="$SID" \
  HOOKS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)" python3 -c "
import os, sys
sys.path.insert(0, os.environ['HOOKS_DIR'])
from lib import allowlist
key = allowlist.grant_key(os.environ['SID'])
allowlist.remove_grant(key)
if os.environ['ALLOW_WRITE'] == 'true':
    scope = allowlist.recognise(os.environ['ALLOW_TEXT'])
    allowlist.write_sentinel_grant(key, os.environ['SID'], scope)
    if scope['kind'] == allowlist.ANY:
        print('[allow] Grant recorded: it lets through ' + allowlist.describe(scope) + ', once, for this session '
              '(main agent or subagent, any tool, any harness rule). The text after /allow was not read as a tool '
              'name or a command, so it does not narrow the grant.')
    else:
        print('[allow] Grant recorded, restricted: it lets through ' + allowlist.describe(scope) + ', once, for '
              'this session; any other refused call stays refused.')
    print('[allow] It ends when it is spent or at your next prompt. It releases a refusal of the deny-list rule '
          'too; the two harness-switch rules kept in the deny list of settings.json belong to the CLI and are not '
          'released by it.')
" 2>&1) || { [ "${PROMPT_IS_ALLOW:-true}" = true ] && echo "[allow] ERROR: the grant could not be written; no grant was issued. ${NOTICE}" >&2; exit 0; }
[ -n "$NOTICE" ] && printf '%s\n' "$NOTICE"
exit 0
