#!/usr/bin/env python3
"""
PostToolUse Hook: Enforce canonical todo count immediately after TodoWrite.

Fires after every TodoWrite call.
If the number of todos written is less than blocking_count (from todo script),
block Claude and provide the full canonical todo list to re-submit. The command
is the one that opened the transcript's active span; the workflow gate reads the
same record, so the block writes nothing.

Exit codes:
  0: Count correct, allow
  2: Count mismatch, block and show canonical todos
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.todo_canonical import checklist  # noqa: E402


def _emit_count_mismatch(cmd_name, blocking_count, actual_count, canonical):
    """Emit the count-mismatch block."""
    sys.stderr.write(
        f'\n⛔ TODO COUNT MISMATCH: /{cmd_name} requires {blocking_count} steps '
        f'but TodoWrite was called with only {actual_count}.\n'
        f'You MUST use the recommended canonical todos below — do NOT create custom or abbreviated steps.\n'
        f'All other tools are now blocked until you re-call TodoWrite with ALL {blocking_count} canonical steps:\n\n'
        + json.dumps(canonical, ensure_ascii=False, indent=2) + '\n'
    )
    sys.exit(2)


def main():
    try:
        data = json.load(sys.stdin)
        todos = data.get('tool_input', {}).get('todos', [])
    except Exception:
        sys.exit(0)

    # F1: subagent bypass — subagents have their own todo schemas (one per role)
    # and shouldn't be force-fitted to main agent's canonical schema.
    if data.get('agent_id'):
        sys.exit(0)

    if not todos:
        sys.exit(0)

    state = checklist(data.get('transcript_path'))
    if state is None:
        sys.exit(0)

    canonical = state.canonical
    blocking_count = len(canonical)
    actual_count = len(todos)

    if actual_count < blocking_count:
        _emit_count_mismatch(state.command, blocking_count, actual_count, canonical)

    sys.exit(0)


if __name__ == '__main__':
    main()
