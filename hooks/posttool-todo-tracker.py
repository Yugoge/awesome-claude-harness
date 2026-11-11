#!/usr/bin/env python3
"""
PostToolUse Hook: Output checklist progress after every TodoWrite call.

Fires after every TodoWrite call:
1. Reads the command from the transcript's active span (lib.todo_canonical.checklist)
2. Counts the steps of the list it was given (the list's own length)
3. Gives the agent the checklist progress as additionalContext (PostToolUse's
   channel to the model; plain stdout at exit 0 reaches only the transcript view)

It writes nothing: the CLI records every TodoWrite in the transcript and in its
own todo file, and every reader of the checklist reads the transcript (P1b E7).

Hook type: PostToolUse (TodoWrite matcher)
Exit codes: 0 always (never blocks)
"""
import os, sys  # noqa: E401 -- the harness switch (hooks/lib/harness_switch.py): no harness hook runs while /harness off holds
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))
try:  # a hook copied without its lib/ (an old install) is on
    import harness_switch  # noqa: E402
    harness_switch.exit_if_off()
except ImportError:
    pass
finally:
    sys.path.pop(0)

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.todo_canonical import checklist  # noqa: E402

STATUS_SYMBOL = {'completed': '[x]', 'in_progress': '[~]', 'pending': '[ ]'}


def format_checklist(command: str, todos: list, blocking_count: int) -> str:
    completed_count = sum(1 for t in todos if t.get('status') == 'completed')
    lines = [f"WORKFLOW PROGRESS ({command}): {completed_count}/{blocking_count} steps completed"]
    for todo in todos:
        symbol = STATUS_SYMBOL.get(todo.get('status', 'pending'), '[ ]')
        lines.append(f"  {symbol} {todo['content']}")
    if completed_count < blocking_count:
        lines.append("Continue with the next required step.")
    return '\n'.join(lines)


def main():
    # Native save_state owns Codex progress. Avoid a second progress writer
    # when invoked by a compatibility wrapper.
    if os.environ.get('CLAUDE_COMPAT_RUNTIME') == 'codex':
        sys.exit(0)
    try:
        data = json.load(sys.stdin)
        todos = data.get('tool_input', {}).get('todos', [])
        if data.get('agent_id') or not todos:  # F1 bypass + empty-payload guard, as pretool-todo-validate.py
            sys.exit(0)

        state = checklist(data.get('transcript_path'))
        cmd_name = state.command if state else '?'
        # The list's own length, not the canonical one's: whether its length is right is
        # decided at a first list or a length change (pretool-todo-validate.py), and a list
        # the session started with stays valid when the canonical list changes (P1c row 17).
        blocking_count = len(todos)

        print(json.dumps({'hookSpecificOutput': {
            'hookEventName': 'PostToolUse',
            'additionalContext': format_checklist('/' + cmd_name, todos, blocking_count)}}))

    except Exception:
        pass
    sys.exit(0)


if __name__ == '__main__':
    main()
