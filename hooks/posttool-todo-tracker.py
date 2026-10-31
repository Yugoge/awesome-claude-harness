#!/usr/bin/env python3
"""
PostToolUse Hook: Output checklist progress after every TodoWrite call.

Fires after every TodoWrite call:
1. Reads the command from the transcript's active span (lib.todo_canonical.checklist)
2. Runs todo script to get canonical blocking_count (fresh, no cache)
3. Prints current checklist progress to stdout (injected into Claude's context)

It writes nothing: the CLI records every TodoWrite in the transcript and in its
own todo file, and every reader of the checklist reads the transcript (P1b E7).

Hook type: PostToolUse (TodoWrite matcher)
Exit codes: 0 always (never blocks)
"""

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
        if data.get('agent_id') or not todos:  # F1 bypass + empty-payload guard (pretool-todo-validate.py:284-287)
            sys.exit(0)

        state = checklist(data.get('transcript_path'))
        cmd_name = state.command if state else '?'
        # Get blocking_count fresh from todo script — never from cache
        blocking_count = len(state.canonical) if state else len(todos)

        print(format_checklist('/' + cmd_name, todos, blocking_count))

    except Exception:
        pass
    sys.exit(0)


if __name__ == '__main__':
    main()
