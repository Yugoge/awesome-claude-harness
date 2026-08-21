#!/usr/bin/env python3
"""
PostToolUse:TodoWrite Hook: Overnight Loop Detection

Fires after every TodoWrite call. Checks if:
1. This is a dev-overnight workflow (overnight-state.json exists)
2. ALL todos have status "completed"
3. end_time is still in the future
4. session_id matches the overnight state file

If all conditions met: increments cycle_count in state, prints
continuation instructions telling the agent to reset its own todos
and resume from Step 2.

Does NOT directly modify the todos file -- prints instructions
for the agent to act on, avoiding race conditions with other hooks.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _all_completed(data: dict) -> bool:
    """Check if all todos in the tool_input are completed."""
    todos = data.get('tool_input', {}).get('todos', [])
    if not todos:
        return False
    return all(t.get('status') == 'completed' for t in todos)


def _try_load_json(path: Path) -> dict | None:
    """Attempt to load JSON from a file path. Returns None on failure."""
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _load_overnight_state(session_id: str) -> tuple[dict | None, Path]:
    """Load overnight state, preferring exact session_id match."""
    project_dir = Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))
    claude_dir = project_dir / '.claude'
    # Prefer exact match for this session
    if session_id:
        exact = claude_dir / f'overnight-state-{session_id}.json'
        state = _try_load_json(exact)
        if state:
            return state, exact
    # Fallback: scan all state files (backward compat)
    for p in sorted(claude_dir.glob('overnight-state-*.json')):
        state = _try_load_json(p)
        if state:
            return state, p
    return None, claude_dir / 'overnight-state-unknown.json'


def _check_end_time(state: dict) -> datetime | None:
    """Parse end_time from state. Returns None if expired or invalid.

    Always normalizes end_time to a timezone-aware UTC datetime, so all
    comparisons against datetime.now(timezone.utc) are aware-aware. Naive
    end_time strings (no offset, no Z) are auto-promoted to UTC.
    """
    et = state.get('end_time')
    if not et:
        return None
    try:
        end_time = datetime.fromisoformat(et.replace('Z', '+00:00'))
    except (ValueError, TypeError, AttributeError):
        return None
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) >= end_time:
        return None
    return end_time


def _mark_session_complete(state: dict, state_path: Path) -> None:
    """Mark session as complete when end_time has expired."""
    state['current_phase'] = 'complete'
    tmp = state_path.with_suffix('.tmp')
    try:
        tmp.write_text(json.dumps(state, indent=2))
        os.rename(str(tmp), str(state_path))
    except Exception:
        pass
    print(f'OVERNIGHT SESSION COMPLETE: end_time reached. Cycles: {state.get("cycle_count", 0)}, Fixed: {state.get("issues_fixed", 0)}')
    print('Generate your summary and finish up.')


def _update_state_cycle(state: dict, state_path: Path) -> None:
    """Increment cycle_count, reset phase and pipeline tracking in state file.

    Preserves session-level data (pm_triage_reports, pm_retro_reports) across cycles.
    Resets per-cycle data (current_issues, unresolved_issues).
    """
    state['cycle_count'] = state.get('cycle_count', 0) + 1
    state['current_phase'] = 'exploring'
    state['current_issues'] = []  # Clear pipeline array for next cycle
    state['unresolved_issues'] = []  # Reset for next cycle
    # Ensure session-level report arrays exist (preserve across cycles)
    state.setdefault('pm_triage_reports', [])
    state.setdefault('pm_retro_reports', [])
    # Backward compat: remove legacy v5 fields if present
    state.pop('current_issue', None)
    state.pop('current_issue_iteration', None)
    tmp = state_path.with_suffix('.tmp')
    try:
        tmp.write_text(json.dumps(state, indent=2))
        os.rename(str(tmp), str(state_path))
    except Exception:
        pass


def _print_loop_instructions(state: dict, end_time: datetime, state_path: Path) -> None:
    """Print continuation instructions for the agent."""
    remaining = end_time - datetime.now(timezone.utc)
    hours = int(remaining.total_seconds() // 3600)
    minutes = int((remaining.total_seconds() % 3600) // 60)
    cc = state.get('cycle_count', 0)
    fixed = state.get('issues_fixed', 0)
    wt = state.get('worktree_path', 'unknown')

    print(f'OVERNIGHT LOOP: Cycle {cc} complete (PM retro filed). Starting cycle {cc + 1}.')
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

    session_id = data.get('session_id', '')
    state, state_path = _load_overnight_state(session_id)
    if state is None:
        sys.exit(0)

    # Only inject loop instructions for the matching overnight session
    state_session_id = state.get('session_id', '')
    if state_session_id and state_session_id != session_id:
        sys.exit(0)

    end_time = _check_end_time(state)
    if end_time is None:
        _mark_session_complete(state, state_path)
        sys.exit(0)

    _update_state_cycle(state, state_path)
    _print_loop_instructions(state, end_time, state_path)
    sys.exit(0)


if __name__ == '__main__':
    main()
