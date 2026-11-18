#!/usr/bin/env python3
"""
PostToolUse:TodoWrite Hook: Overnight Loop Detection

Fires after every TodoWrite call. Checks if:
0. The payload is the orchestrator's own (lib.subagent.is_subagent_context: a
   subagent's list is a no-op)
1. This session owns an overnight state record (lib.overnight.locate)
2. ALL todos have status "completed", and the list is the span's checklist:
   a list foreign to the command (OB-L40, lib.todo_canonical.checklist_lists)
   ends no cycle
3. The time-lock's window is open (lib.overnight.window_open)

If all conditions met: tells the agent to reset its own todos and resume from
Step 2; once the window has closed (end_time or the human's /stop), no
continuation, only that the session is complete. The cycle number is
lib.overnight.cycle_index, read from the session's cycle directories under the
record's worktree_path; this hook writes no state and no contract. The text goes
as the hooks reference documents for PostToolUse, whose plain stdout reaches only
the debug log: hookSpecificOutput.additionalContext in one JSON object, exit 0.

Does NOT directly modify the todos file -- the agent acts on the instructions,
avoiding race conditions with other hooks.
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
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import overnight  # noqa: E402
from lib.subagent import is_subagent_context  # noqa: E402


def _all_completed(data: dict) -> bool:
    """Check if all todos in the tool_input are completed."""
    todos = data.get('tool_input', {}).get('todos', [])
    if not todos:
        return False
    return all(t.get('status') == 'completed' for t in todos)


def _foreign(data: dict) -> bool:
    """True when the span holds a checklist and the TodoWrite's list shares no
    step's text with the span's canonical list or its first list: not the
    checklist (OB-L40; the validator admits such a list only past a checklist
    all completed)."""
    from lib.todo_canonical import checklist, is_foreign
    state = checklist(data.get('transcript_path'))
    if state is None or state.todos is None:
        return False
    return is_foreign(data.get('tool_input', {}).get('todos', []), state.canonical,
                      next((t for _c, t in state.lists()), None))


def _session_complete(state: dict) -> str:
    """The window has closed: tell the agent to summarise and finish."""
    return (f'OVERNIGHT SESSION COMPLETE: the time-lock window has closed. '
            f'Cycles: {overnight.cycle_index(state) - 1}, Fixed: {state.get("issues_fixed", 0)}\n'
            'Generate your summary and finish up.')


def _loop_instructions(state: dict, end_time: datetime, state_path: Path) -> str:
    """The continuation instructions for the agent."""
    remaining = end_time - datetime.now(timezone.utc)
    hours = int(remaining.total_seconds() // 3600)
    minutes = int((remaining.total_seconds() % 3600) // 60)
    cycle = overnight.cycle_index(state)
    fixed = state.get('issues_fixed', 0)
    wt = state.get('worktree_path', 'unknown')

    return '\n'.join([
        f'OVERNIGHT LOOP: Cycle {cycle - 1} complete (PM retro filed). Starting cycle {cycle}.',
        f'Time remaining: {hours}h {minutes}m',
        f'Issues fixed this session: {fixed}',
        '',
        'INSTRUCTIONS: Reset your todo list to all-pending, then mark Step 0 and Step 1 completed.',
        f'State file: {state_path} (read it for current state)',
        f'Worktree: {wt} (already exists, DO NOT create another)',
        '',
        'Resume from Step 2 (exploration) -- Step 1 setup is already done, and the wake Step 0'
        ' scheduled still runs (no second CronCreate).'])


def _tell_agent(text: str) -> None:
    """PostToolUse's documented channel to the agent: additionalContext, exit 0."""
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PostToolUse', 'additionalContext': text}}))


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    # Only the orchestrator's own list: a subagent's payload carries the
    # parent's session_id (lib/overnight.py), so locate() would find the
    # orchestrator's record from it.
    if is_subagent_context(data) or not _all_completed(data):
        sys.exit(0)

    # Only the overnight session's own record: its file name and its own
    # session_id both name the session that wrote the todos.
    state_path, state = overnight.locate(data.get('session_id', ''), data)
    if state is None or _foreign(data):
        sys.exit(0)

    end_time = overnight.state_verdicts(state).end_time
    if end_time is None or not overnight.window_open(data):
        _tell_agent(_session_complete(state))
        sys.exit(0)

    _tell_agent(_loop_instructions(state, end_time, state_path))
    sys.exit(0)


if __name__ == '__main__':
    main()
