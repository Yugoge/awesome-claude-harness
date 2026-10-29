#!/usr/bin/env python3
"""
Stop Hook: Block conversation termination until overnight end-time.

Logic:
  1. Read JSON from stdin (session_id)
  2. Load only the session's own record (lib.overnight.session_state)
  3. If no state file: exit 0 (allow stop)
  4. If the record's window is live (lib.overnight.state_verdicts): exit 2
  5. Otherwise: exit 0 (allow stop)

Exit codes:
  0: Allow stop
  2: Block stop (time-lock active)
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make sibling lib importable.
_HOOKS_DIR = Path(__file__).resolve().parent
if str(_HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(_HOOKS_DIR))

from lib import overnight  # noqa: E402

try:
    from lib import session_resources
except Exception:  # pragma: no cover - fail-soft if lib missing
    session_resources = None  # type: ignore[assignment]


def read_stdin_context() -> dict:
    """Read and parse JSON from stdin."""
    try:
        if not sys.stdin.isatty():
            return json.load(sys.stdin)
    except Exception:
        pass
    return {}


def load_state(project_dir: Path, session_id: str) -> dict | None:
    """Load only the exact session state; global/newest scans are unauthorized."""
    return overnight.session_state(session_id, project_dir)


def is_session_mismatch(current_id: str, state: dict) -> bool:
    """Return True if current session does NOT own this state file (fail-open)."""
    if not current_id:
        return False  # Fail-open: unknown session_id -> don't skip
    state_id = state.get('session_id', '')
    if not state_id:
        return False  # Fail-open: state has no session_id -> don't skip
    return current_id != state_id


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


def block_with_message(end_time: datetime, state: dict) -> None:
    """Write time-lock message to stderr and exit 2."""
    now = datetime.now(timezone.utc) if end_time.tzinfo else datetime.now()
    remaining = end_time - now
    total_seconds = int(remaining.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    phase = state.get('current_phase', 'unknown')
    cycles_done = overnight.cycle_index(state) - 1
    issues_fixed = state.get('issues_fixed', 0)

    sys.stderr.write(
        f'\n TIME-LOCK ACTIVE: Overnight session runs until '
        f'{end_time.strftime("%Y-%m-%d %H:%M")}.\n'
        f'Time remaining: {hours}h {minutes}m\n'
        f'Current phase: {phase} | Cycles: {cycles_done} | '
        f'Fixed: {issues_fixed}\n'
        f'The session cannot end until the end-time is reached.\n'
        f'Continue working on the current cycle.\n'
    )
    sys.exit(2)




def _publish_terminal_receipt(
    project_dir: Path, session_id: str, state: dict, terminal_status: str
) -> bool:
    """Publish evidence only; this writer never finalizes or signals resources."""
    if session_resources is None:
        return False
    try:
        result = session_resources.publish_overnight_receipt(
            project_dir,
            claude_session_id=session_id,
            state=state,
            terminal_status=terminal_status,
        )
    except (OSError, ValueError) as exc:
        sys.stderr.write(
            f'[stop-overnight-timelock] terminal receipt not published: {exc}\n'
        )
        return False
    return result.get('status') == 'pass'

def _enforce_timelock(session_id: str, state: dict, project_dir: Path | None = None) -> None:
    """Apply the time-lock and the closeout-artifact rules. Exits 0 or 2 directly."""
    project_dir = project_dir or Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))
    terminal_hint = state.get('terminal_status') or state.get('status')
    if terminal_hint in {'cancelled_by_user', 'user_cancelled', 'cancelled'}:
        _publish_terminal_receipt(project_dir, session_id, state, 'cancelled_by_user')
        sys.exit(0)
    verdicts = overnight.state_verdicts(state)
    end_time = verdicts.end_time
    end_time_expired = end_time is not None and not verdicts.window_live
    # A subagent's report is checked at that subagent's own stop (G2) and at
    # its collection (posttool-overnight-file-check.py), never again here.
    if end_time_expired:
        blockers = _closeout_artifact_blockers(state)
        if blockers:
            # The completed cycles, as master's cycle_count was (cycle_index is the one in progress).
            _block_closeout_artifacts(session_id, str(overnight.cycle_index(state) - 1), blockers)
    if end_time is None:
        sys.exit(0)
    if verdicts.window_live:
        block_with_message(end_time, state)
    _publish_terminal_receipt(project_dir, session_id, state, 'completed_by_deadline')
    sys.exit(0)


def main():
    """Entry point for the stop-overnight-timelock hook."""
    # Codex-native Stop owns overnight isolation in Codex roots. A legacy
    # projection can never time-lock or contradict an ordinary native workflow.
    if os.environ.get('CLAUDE_COMPAT_RUNTIME') == 'codex':
        sys.exit(0)
    context = read_stdin_context()
    if context.get('stop_hook_active', False):
        # NEVER-STOP-UNTIL-END_TIME: honor the framework loop-guard only AFTER
        # end_time; while now < end_time, fall through so the lock re-blocks every stop.
        _sid = context.get('session_id', '')
        _pdir = Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))
        _st = load_state(_pdir, _sid)
        if _st is None or overnight.state_verdicts(_st).end_time is None:
            sys.exit(0)

    session_id = context.get('session_id', '')
    project_dir = Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))
    state = load_state(project_dir, session_id)
    if state is None:
        sys.exit(0)

    # Only block the overnight session itself -- not other sessions.
    if is_session_mismatch(session_id, state):
        sys.exit(0)

    _enforce_timelock(session_id, state, project_dir)


if __name__ == '__main__':
    main()
