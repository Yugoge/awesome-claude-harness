#!/usr/bin/env python3
"""
Stop Hook: Block conversation termination until overnight end-time.

Logic:
  1. Read JSON from stdin (session_id)
  2. Scan for any .claude/overnight-state-*.json files
  3. If no state file: exit 0 (allow stop)
  4. If current time < end_time: exit 2 (block stop)
  5. If current time >= end_time: exit 0 (allow stop)

Exit codes:
  0: Allow stop
  2: Block stop (time-lock active)
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Make sibling lib importable for closeout integration.
_HOOKS_DIR = Path(__file__).resolve().parent
if str(_HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(_HOOKS_DIR))

try:
    from lib.closeout import has_pending_required_calls, run_cycle_closeout
except Exception:  # pragma: no cover - fail-soft if lib missing
    has_pending_required_calls = None  # type: ignore[assignment]
    run_cycle_closeout = None  # type: ignore[assignment]


def read_stdin_context() -> dict:
    """Read and parse JSON from stdin."""
    try:
        if not sys.stdin.isatty():
            return json.load(sys.stdin)
    except Exception:
        pass
    return {}


def _try_load_json(path: Path) -> dict | None:
    """Attempt to load JSON from a file path. Returns None on failure."""
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def load_state(project_dir: Path, session_id: str) -> dict | None:
    """Load overnight state file. Tries exact session_id match first, then scans."""
    claude_dir = project_dir / '.claude'
    # Prefer exact match for this session
    if session_id:
        exact = claude_dir / f'overnight-state-{session_id}.json'
        state = _try_load_json(exact)
        if state:
            return state
    # Fallback: scan all state files (backward compat / legacy "default" naming)
    for p in sorted(claude_dir.glob('overnight-state-*.json')):
        state = _try_load_json(p)
        if state:
            return state
    return None


def parse_end_time(state: dict) -> datetime | None:
    """Extract and parse end_time from state dict.

    Returns naive datetime for local-time comparison with datetime.now().
    """
    end_time_str = state.get('end_time')
    if not end_time_str:
        return None
    try:
        dt = datetime.fromisoformat(end_time_str)
        # Strip timezone if present — all comparisons use naive local time
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except (ValueError, TypeError):
        return None


def is_session_mismatch(current_id: str, state: dict) -> bool:
    """Return True if current session does NOT own this state file (fail-open)."""
    if not current_id:
        return False  # Fail-open: unknown session_id -> don't skip
    state_id = state.get('session_id', '')
    if not state_id:
        return False  # Fail-open: state has no session_id -> don't skip
    return current_id != state_id


def _coerce_cycle_id(state: dict) -> int | None:
    raw = state.get("cycle_count")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _invoke_closeout(session_id: str, state: dict) -> bool:
    """Run cycle closeout. Returns True if pending required_calls remain."""
    if run_cycle_closeout is None or has_pending_required_calls is None:
        return False
    cycle_id = _coerce_cycle_id(state)
    if not session_id or cycle_id is None:
        return False
    try:
        run_cycle_closeout(session_id, cycle_id)
        return bool(has_pending_required_calls(session_id, cycle_id))
    except Exception as exc:  # pragma: no cover - fail-soft
        sys.stderr.write(f"[stop-overnight-timelock] closeout error: {exc}\n")
        return False


def _block_pending(session_id: str, cycle_id_str: str) -> None:
    sys.stderr.write(
        "\n CLOSEOUT GATE: cycle still has unresolved required_calls.\n"
        f" session={session_id} cycle={cycle_id_str}\n"
        " Complete or waive the missing entries before terminating.\n"
    )
    sys.exit(2)


def _path_exists(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    return Path(value).expanduser().exists()


def _closeout_artifact_blockers(state: dict) -> list[str]:
    blockers: list[str] = []
    if state.get('unresolved_issues') or state.get('current_issues'):
        blockers.append('unresolved_backlog')
    if not _path_exists(state.get('final_summary_path') or state.get('summary_path')):
        blockers.append('final_summary')
    retro = state.get('pm_retro_reports')
    if not isinstance(retro, list) or not retro:
        blockers.append('retro_status')
    checkpoint_status = state.get('artifact_checkpoint_status') or state.get('checkpoint_status')
    if checkpoint_status not in {'checkpointed', 'intentionally_uncommitted'}:
        blockers.append('artifact_checkpoint_status')
    return blockers


def _block_closeout_artifacts(session_id: str, cycle_id_str: str, blockers: list[str]) -> None:
    sys.stderr.write(
        "\n CLOSEOUT GATE: final overnight artifacts are incomplete.\n"
        f" session={session_id} cycle={cycle_id_str}\n"
        f" missing={', '.join(blockers)}\n"
        " Record backlog, final summary, PM retro, and checkpoint/artifact status before terminating.\n"
    )
    sys.exit(2)


def _write_continuation_sentinel(
    state: dict, end_time: datetime, total_seconds: int
) -> None:
    """Drop /tmp/overnight-needs-continuation-<sid> on every block.

    Provides observable proof for downstream consumers (watchdog, QA) that
    the Stop hook fired and continuation is needed. Fail-soft: any I/O
    error is swallowed so a /tmp failure cannot escalate Stop into a hard
    error. Source: BA spec ba-spec-stop-hook-gap-20260426-2250.md (M4).
    """
    try:
        sid = state.get('session_id') or 'unknown'
        payload = {
            'ts': datetime.now().isoformat(timespec='seconds'),
            'session_id': sid,
            'reason': 'stop-overnight-timelock blocked stop',
            'end_time': end_time.isoformat(timespec='seconds'),
            'time_remaining_seconds': total_seconds,
            'current_phase': state.get('current_phase'),
            'cycle_count': state.get('cycle_count'),
        }
        sentinel = Path(f'/tmp/overnight-needs-continuation-{sid}')
        sentinel.write_text(json.dumps(payload, ensure_ascii=False))
    except Exception as exc:  # pragma: no cover - fail-soft
        sys.stderr.write(
            f'[stop-overnight-timelock] sentinel write error: {exc}\n'
        )


def block_with_message(end_time: datetime, state: dict) -> None:
    """Write time-lock message to stderr and exit 2."""
    remaining = end_time - datetime.now()
    total_seconds = int(remaining.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    phase = state.get('current_phase', 'unknown')
    cycle_count = state.get('cycle_count', 0)
    issues_fixed = state.get('issues_fixed', 0)

    sys.stderr.write(
        f'\n TIME-LOCK ACTIVE: Overnight session runs until '
        f'{end_time.strftime("%Y-%m-%d %H:%M")}.\n'
        f'Time remaining: {hours}h {minutes}m\n'
        f'Current phase: {phase} | Cycles: {cycle_count} | '
        f'Fixed: {issues_fixed}\n'
        f'The session cannot end until the end-time is reached.\n'
        f'Continue working on the current cycle.\n'
    )
    _write_continuation_sentinel(state, end_time, total_seconds)
    sys.exit(2)


def _enforce_timelock(session_id: str, state: dict) -> None:
    """Run closeout + apply blocking rules. Exits 0 or 2 directly."""
    end_time = parse_end_time(state)
    end_time_expired = end_time is not None and datetime.now() >= end_time
    # Always run closeout (produces harness-report). HARD CUTOVER: closeout
    # itself no-ops if no cycle-contract.json exists (legacy session).
    pending = _invoke_closeout(session_id, state)
    if pending and not end_time_expired:
        _block_pending(session_id, str(state.get('cycle_count', '?')))
    if end_time_expired:
        blockers = _closeout_artifact_blockers(state)
        if blockers:
            _block_closeout_artifacts(session_id, str(state.get('cycle_count', '?')), blockers)
    if end_time is None:
        sys.exit(0)
    if datetime.now() < end_time:
        block_with_message(end_time, state)
    sys.exit(0)


def main():
    """Entry point for the stop-overnight-timelock hook."""
    context = read_stdin_context()
    if context.get('stop_hook_active', False):
        # NEVER-STOP-UNTIL-END_TIME: honor the framework loop-guard only AFTER
        # end_time; while now < end_time, fall through so the lock re-blocks every stop.
        _sid = context.get('session_id', '')
        _pdir = Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))
        _st = load_state(_pdir, _sid)
        _et = parse_end_time(_st) if _st else None
        if _et is None or datetime.now() >= _et:
            sys.exit(0)

    session_id = context.get('session_id', '')
    project_dir = Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))
    state = load_state(project_dir, session_id)
    if state is None:
        sys.exit(0)

    # Only block the overnight session itself -- not other sessions.
    if is_session_mismatch(session_id, state):
        sys.exit(0)

    _enforce_timelock(session_id, state)


if __name__ == '__main__':
    main()
