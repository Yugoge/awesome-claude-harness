#!/usr/bin/env python3
"""
PostToolUse:TodoWrite Hook: Overnight Loop Detection

Fires after every TodoWrite call. Checks if:
1. This session owns an overnight state record
2. ALL todos have status "completed"
3. The record's window is live (lib.overnight.state_verdicts)

If all conditions met: prints continuation instructions telling the agent to
reset its own todos and resume from Step 2. The cycle number is
lib.overnight.cycle_index, read from the session's cycle directories; this
hook writes no state (the launcher's write path is the record's only writer).

Does NOT directly modify the todos file -- prints instructions
for the agent to act on, avoiding race conditions with other hooks.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import overnight  # noqa: E402


def _all_completed(data: dict) -> bool:
    """Check if all todos in the tool_input are completed."""
    todos = data.get('tool_input', {}).get('todos', [])
    if not todos:
        return False
    return all(t.get('status') == 'completed' for t in todos)


def _print_session_complete(state: dict) -> None:
    """The window has closed: tell the agent to summarise and finish."""
    print(f'OVERNIGHT SESSION COMPLETE: end_time reached. '
          f'Cycles: {overnight.cycle_index(state) - 1}, Fixed: {state.get("issues_fixed", 0)}')
    print('Generate your summary and finish up.')


def _print_loop_instructions(state: dict, end_time: datetime, state_path: Path) -> None:
    """Print continuation instructions for the agent."""
    now = datetime.now(timezone.utc) if end_time.tzinfo else datetime.now()
    remaining = end_time - now
    hours = int(remaining.total_seconds() // 3600)
    minutes = int((remaining.total_seconds() % 3600) // 60)
    cycle = overnight.cycle_index(state)
    fixed = state.get('issues_fixed', 0)
    wt = state.get('worktree_path', 'unknown')

    print(f'OVERNIGHT LOOP: Cycle {cycle - 1} complete (PM retro filed). Starting cycle {cycle}.')
    print(f'Time remaining: {hours}h {minutes}m')
    print(f'Issues fixed this session: {fixed}')
    print()
    print('INSTRUCTIONS: Reset your todo list to all-pending and begin Step 1 again.')
    print(f'State file: {state_path} (read it for current state)')
    print(f'Worktree: {wt} (already exists, DO NOT create another)')
    print()
    print('Resume from Step 2 (exploration) -- Step 1 setup is already done.')


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    if not _all_completed(data):
        sys.exit(0)

    # Only the overnight session's own record: its file name and its own
    # session_id both name the session that wrote the todos.
    session_id = data.get('session_id', '')
    state = overnight.session_state(session_id)
    if state is None:
        sys.exit(0)

    verdicts = overnight.state_verdicts(state)
    if not verdicts.window_live:
        _print_session_complete(state)
        sys.exit(0)

    _print_loop_instructions(state, verdicts.end_time, overnight.state_path(session_id))
    sys.exit(0)


if __name__ == '__main__':
    main()
