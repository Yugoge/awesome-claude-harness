#!/usr/bin/env python3
"""
PostToolUse Hook: the first-call rule of a workflow checklist.

The first TodoWrite of a command's checklist completes no step and starts at
most Step 0 (lib.todo_canonical.initial_status_violations). A first list that
breaks it has run, so the CLI holds it, but the step rules do not accept it
(lib.todo_canonical.checklist, P1b E7): the next TodoWrite is a first call
again, and the workflow gate holds other tools until one passes. The block is
the whole effect: nothing is written.

Every other step rule (canonical content and count, one completion per call,
in_progress before completed, one in_progress at a time, order, immutable
content) is pretool-todo-validate.py's, which refuses the TodoWrite before it
runs, against the same accepted list read the same way. P1c X6 deleted this
hook's copies of those rules: no call they would block reaches PostToolUse
(class U).

Exit codes:
  0: allow
  2: the first-call rule is broken, block
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.todo_canonical import checklist, initial_status_violations


def main():
    try:
        data = json.load(sys.stdin)
        # Subagents keep their own todo lists (one per role), not the command's.
        if data.get('agent_id'):
            sys.exit(0)
        new_todos = data.get('tool_input', {}).get('todos', [])
    except Exception:
        sys.exit(0)
    if not new_todos:
        sys.exit(0)
    # This call is already in the record; the list it is checked against is
    # the one accepted before it.
    state = checklist(data.get('transcript_path'), before=data.get('tool_use_id'))
    if state is None or state.accepted is not None:
        sys.exit(0)
    violations = initial_status_violations(new_todos)
    if violations:
        numbered = '\n'.join(f'  [{j+1}] {v}' for j, v in enumerate(violations))
        sys.stderr.write(
            f'\nBLOCKED STEP SEQUENCE VIOLATION in /{state.command}:\n' + numbered
            + '\n\nThe first TodoWrite of the checklist completes no step and starts at most '
            'Step 0, so this list is not accepted. Call TodoWrite again with the same steps, '
            'Step 0 in_progress and every other step pending.\n'
        )
        sys.exit(2)
    sys.exit(0)


if __name__ == '__main__':
    main()
