#!/usr/bin/env python3
"""Tests for posttool-overnight-loop.py timezone handling.

Verifies the overnight loop hook compares end_time correctly against the
current time when end_time may be aware or naive. Prior bug:
datetime.now() naive vs aware fromisoformat raised TypeError on Py3.11+.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOOK_PATH = Path(__file__).parent.parent / 'hooks' / 'posttool-overnight-loop.py'


def _make_todo(label: str) -> dict:
    return {'content': label, 'status': 'completed', 'activeForm': label}


def _build_payload(session_id: str) -> dict:
    todos = [_make_todo('a'), _make_todo('b')]
    tool_input = {'todos': todos}
    return {
        'session_id': session_id,
        'tool_name': 'TodoWrite',
        'tool_input': tool_input,
    }


def _build_state(session_id: str, end_time_iso: str, cycle_count: int,
                 worktree_path: str) -> dict:
    return {
        'session_id': session_id,
        'end_time': end_time_iso,
        'cycle_count': cycle_count,
        'current_phase': 'exploring',
        'issues_fixed': 0,
        'worktree_path': worktree_path,
        'pm_triage_reports': [],
        'pm_retro_reports': [],
    }


def _write_state(tmpdir: Path, session_id: str, end_time_iso: str,
                 cycle_count: int = 0) -> Path:
    claude_dir = tmpdir / '.claude'
    claude_dir.mkdir(parents=True, exist_ok=True)
    state_path = claude_dir / f'overnight-state-{session_id}.json'
    state = _build_state(session_id, end_time_iso, cycle_count,
                         str(tmpdir / 'worktree'))
    state_path.write_text(json.dumps(state, indent=2))
    return state_path


def _run_hook(tmpdir: Path, payload: dict) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env['CLAUDE_PROJECT_DIR'] = str(tmpdir)
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


def _exec_case(end_time_iso: str, sid: str, cycle_count: int = 0):
    tmp = tempfile.TemporaryDirectory()
    tmpdir = Path(tmp.name)
    state_path = _write_state(tmpdir, sid, end_time_iso, cycle_count=cycle_count)
    result = _run_hook(tmpdir, _build_payload(sid))
    state = json.loads(state_path.read_text())
    return result, state, tmp


class OvernightLoopTimezoneTests(unittest.TestCase):
    """Aware/naive end_time comparison must not raise nor misclassify."""

    def test_aware_future_end_time_does_not_complete(self) -> None:
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        result, state, tmp = _exec_case(future, 'test-future-aware')
        try:
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertNotEqual(state.get('current_phase'), 'complete')
            self.assertEqual(state.get('cycle_count'), 1)
        finally:
            tmp.cleanup()

    def test_aware_past_end_time_marks_complete(self) -> None:
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        result, state, tmp = _exec_case(past, 'test-past-aware', cycle_count=2)
        try:
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertEqual(state.get('current_phase'), 'complete')
        finally:
            tmp.cleanup()

    def test_z_suffixed_future_end_time_does_not_complete(self) -> None:
        future_dt = datetime.now(timezone.utc) + timedelta(hours=1)
        future_z = future_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        result, state, tmp = _exec_case(future_z, 'test-z-suffix')
        try:
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertNotEqual(state.get('current_phase'), 'complete')
        finally:
            tmp.cleanup()

    def test_naive_future_end_time_auto_promoted_to_utc(self) -> None:
        future_aware = datetime.now(timezone.utc) + timedelta(hours=1)
        future_naive = future_aware.replace(tzinfo=None).isoformat()
        self.assertNotIn('+', future_naive)
        self.assertFalse(future_naive.endswith('Z'))
        result, state, tmp = _exec_case(future_naive, 'test-naive-future')
        try:
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertNotEqual(state.get('current_phase'), 'complete')
        finally:
            tmp.cleanup()


if __name__ == '__main__':
    unittest.main()
