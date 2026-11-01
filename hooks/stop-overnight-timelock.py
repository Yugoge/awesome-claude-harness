#!/usr/bin/env python3
"""Stop hook: the /dev-overnight time-lock, a thin caller of lib/overnight.

For the stopping session's own record (overnight.locate; no record: exit 0):
  1. overnight.window_open: exit 2 with the time left. Only end_time or the
     human's typed /stop closes the window; stop_hook_active frees nothing.
  2. A human-typed /stop record (stop_contract.timelock_released): exit 0 and
     publish the cancelled_by_user receipt, with no closeout check.
  3. Otherwise end_time has passed: exit 2 naming overnight.closeout_gaps on
     stderr until none is left, then exit 0 and publish completed_by_deadline.
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

from lib import overnight, stop_contract  # noqa: E402

try:
    from lib import session_resources
except Exception:  # pragma: no cover - fail-soft if lib missing
    session_resources = None  # type: ignore[assignment]


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


def main():
    """Entry point for the stop-overnight-timelock hook."""
    # Codex-native Stop owns overnight isolation in Codex roots. A legacy
    # projection can never time-lock or contradict an ordinary native workflow.
    if os.environ.get('CLAUDE_COMPAT_RUNTIME') == 'codex':
        sys.exit(0)
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    payload = payload if isinstance(payload, dict) else {}
    session_id = payload.get('session_id', '')
    state_file, state = overnight.locate(session_id, payload)
    if state is None:
        sys.exit(0)
    if overnight.window_open(payload):
        end = overnight.state_verdicts(state).end_time or datetime.now(timezone.utc)
        left = max(0, int((end - datetime.now(timezone.utc)).total_seconds()) // 60)
        sys.stderr.write(
            f'\n TIME-LOCK ACTIVE: Overnight session runs until {end:%Y-%m-%d %H:%M} UTC.\n'
            f'Time remaining: {left // 60}h {left % 60}m\n'
            f'Cycle in progress: {overnight.cycle_index(state)}\n'
            'The session cannot end before end_time; only the human typing /stop ends it early.\n'
            'Continue working on the current cycle.\n'
        )
        sys.exit(2)
    main_root = state_file.parent.parent
    if stop_contract.timelock_released(payload.get('transcript_path')):
        _publish_terminal_receipt(main_root, session_id, state, 'cancelled_by_user')
        sys.exit(0)
    gaps = overnight.closeout_gaps(state, overnight.working_root(state))
    if gaps:
        sys.stderr.write(
            '\n CLOSEOUT GATE: end_time has passed; the session ends once its closeout is on disk.\n'
            + ''.join(f' missing: {gap}\n' for gap in gaps)
        )
        sys.exit(2)
    _publish_terminal_receipt(main_root, session_id, state, 'completed_by_deadline')
    sys.exit(0)


if __name__ == '__main__':
    main()
