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

# G4 overnight-loop-reset anchor (ticket 20260930-132644-l4 item 7). Shares
# the SAME env var and advisory-log file as hooks/stop-obligation-gate.py --
# one switch, one log stream, for both halves of gate G4.
ADVISORY_LOG = Path.home() / '.claude' / 'logs' / 'obligation-terminal-gate-advisory.jsonl'

# Mirrors hooks/stop-do-report-gate.py's TERMINAL_STATUSES constant: "blocked"
# is a legitimate terminal dev status, never "incomplete" (R9).
TERMINAL_DEV_STATUSES = {"completed", "blocked"}


def _log_event(record: dict) -> None:
    """Best-effort append to the shared G4 advisory log. Never raises."""
    try:
        ADVISORY_LOG.parent.mkdir(parents=True, exist_ok=True)
        record['ts'] = datetime.now(timezone.utc).isoformat()
        with open(ADVISORY_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
    except Exception:
        pass


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
    # A successful reset supersedes any reason recorded by a PRIOR blocked
    # attempt for the cycle that just ended -- stale reasons must not persist
    # into the next cycle's state (ticket 20260930-132644-l4 item 7).
    state.pop('terminal_gate_blocked_reason', None)
    tmp = state_path.with_suffix('.tmp')
    try:
        tmp.write_text(json.dumps(state, indent=2))
        os.rename(str(tmp), str(state_path))
    except Exception:
        pass


def _write_terminal_gate_reason(state: dict, state_path: Path, reason: str) -> None:
    """Record why the G4 terminal gate blocked this cycle's reset (new
    overnight-state field, ticket 20260930-132644-l4 item 7). Atomic
    tmp-then-rename, matching the file's existing write pattern
    (_mark_session_complete / _update_state_cycle)."""
    state['terminal_gate_blocked_reason'] = reason
    tmp = state_path.with_suffix('.tmp')
    try:
        tmp.write_text(json.dumps(state, indent=2))
        os.rename(str(tmp), str(state_path))
    except Exception:
        pass


def _lane_dev_status(project_dir: Path, pipeline: dict) -> str | None:
    """Read dev.status from this pipeline's dev-report, or None if the
    report/field is absent or unreadable (treated as non-terminal by the
    caller -- a lane with no recorded status is not proven terminal)."""
    suffix = pipeline.get('timestamp_suffix')
    if not isinstance(suffix, str) or not suffix:
        return None
    report_path = project_dir / 'docs' / 'dev' / f'dev-report-{suffix}.json'
    try:
        record = json.loads(report_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(record, dict):
        return None
    dev = record.get('dev')
    status = dev.get('status') if isinstance(dev, dict) else None
    return status if isinstance(status, str) else None


def _lane_label(pipeline: dict, index: int) -> str:
    """Human-readable identifier for a current_issues[] entry, used in the
    state-reason text so the reason names the SPECIFIC non-terminal lane."""
    suffix = pipeline.get('timestamp_suffix')
    description = pipeline.get('description')
    label = f'pipeline[{index}] ({suffix})' if isinstance(suffix, str) and suffix else f'pipeline[{index}]'
    if isinstance(description, str) and description:
        label += f': {description[:60]}'
    return label


def _first_non_terminal_lane(state: dict, project_dir: Path) -> str | None:
    """Condition (b): return a label for the first lane whose dev status
    this cycle is NOT in TERMINAL_DEV_STATUSES, or None if every lane is
    terminal. "blocked" IS terminal -- never treated as "incomplete" (R9)."""
    current_issues = state.get('current_issues')
    if not isinstance(current_issues, list):
        return None
    for index, pipeline in enumerate(current_issues):
        if not isinstance(pipeline, dict):
            return f'pipeline[{index}] (malformed entry)'
        status = _lane_dev_status(project_dir, pipeline)
        if status not in TERMINAL_DEV_STATUSES:
            return _lane_label(pipeline, index)
    return None


def _terminal_gate_block_reason(data: dict, state: dict, project_dir: Path) -> str | None:
    """Conditions (a) and (b) for the G4 overnight-loop-reset anchor (ticket
    20260930-132644-l4 item 7). Returns a human-readable reason naming which
    condition failed, or None when both pass (safe to reset as today)."""
    transcript_path = data.get('transcript_path') or ''
    if transcript_path:
        hooks_dir = str(Path(__file__).resolve().parent)
        if hooks_dir not in sys.path:
            sys.path.insert(0, hooks_dir)
        from lib import obligation  # type: ignore
        unresolved = obligation.find_unresolved_dispatch_obligations(
            str(transcript_path), str(project_dir))
        if unresolved:
            names = sorted({str(item.get('artifact_path')) for item in unresolved})
            return 'condition (a) unresolved obligation(s): ' + ', '.join(names)

    non_terminal = _first_non_terminal_lane(state, project_dir)
    if non_terminal is not None:
        return f'condition (b) non-terminal lane dev status: {non_terminal}'

    return None


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

    # G4 terminal-gate anchor (ticket 20260930-132644-l4 item 7): two new
    # required conditions, inserted AFTER the expiry check above (which keeps
    # precedence, unconditionally, per the pre-existing guard) and BEFORE the
    # pre-existing reset call below. "off" mode skips both conditions
    # entirely -- not even a log write. Any unexpected exception fails open
    # to the ORIGINAL unconditional reset (never raises past main()).
    mode = (os.environ.get('CLAUDE_OBLIGATION_TERMINAL', 'advisory') or 'advisory').strip().lower()
    if mode != 'off':
        session_id_for_log = data.get('session_id', '')
        project_dir = Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))
        try:
            reason = _terminal_gate_block_reason(data, state, project_dir)
        except Exception as exc:
            reason = None
            _log_event({'event': 'gate_error', 'session_id': session_id_for_log, 'error': repr(exc)})
        if reason is not None:
            if mode == 'block':
                _write_terminal_gate_reason(state, state_path, reason)
                print(f'OVERNIGHT LOOP: cycle reset BLOCKED -- {reason}')
                sys.exit(0)
            # advisory (default, or any value other than "block"/"off"): the
            # ORIGINAL reset still happens below, unchanged; only log it.
            _log_event({'event': 'would_block_reset', 'mode': mode,
                        'session_id': session_id_for_log, 'reason': reason})

    _update_state_cycle(state, state_path)
    _print_loop_instructions(state, end_time, state_path)
    sys.exit(0)


if __name__ == '__main__':
    main()
