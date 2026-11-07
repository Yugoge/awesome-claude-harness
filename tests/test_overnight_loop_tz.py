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


def _said(result: subprocess.CompletedProcess) -> str:
    """The text the hook hands the agent: its PostToolUse JSON's additionalContext (the hooks
    reference; a PostToolUse hook's plain stdout reaches the debug log only)."""
    hso = json.loads(result.stdout)['hookSpecificOutput']
    assert hso['hookEventName'] == 'PostToolUse'
    return hso['additionalContext']


def _exec_case(end_time_iso: str, sid: str, cycle_count: int = 0):
    tmp = tempfile.TemporaryDirectory()
    tmpdir = Path(tmp.name)
    state_path = _write_state(tmpdir, sid, end_time_iso, cycle_count=cycle_count)
    before = state_path.read_bytes()
    result = _run_hook(tmpdir, _build_payload(sid))
    # The launcher's write path is the record's only writer: the loop reads it.
    assert state_path.read_bytes() == before
    return result, tmp


class OvernightLoopTimezoneTests(unittest.TestCase):
    """Aware/naive end_time comparison must not raise nor misclassify."""

    def test_aware_future_end_time_does_not_complete(self) -> None:
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        result, tmp = _exec_case(future, 'test-future-aware')
        try:
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertNotIn('OVERNIGHT SESSION COMPLETE', _said(result))
            self.assertIn('Starting cycle 1.', _said(result))
        finally:
            tmp.cleanup()

    def test_aware_past_end_time_completes_session(self) -> None:
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        result, tmp = _exec_case(past, 'test-past-aware', cycle_count=2)
        try:
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn('OVERNIGHT SESSION COMPLETE', _said(result))
        finally:
            tmp.cleanup()

    def test_z_suffixed_future_end_time_does_not_complete(self) -> None:
        future_dt = datetime.now(timezone.utc) + timedelta(hours=1)
        future_z = future_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        result, tmp = _exec_case(future_z, 'test-z-suffix')
        try:
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertNotIn('OVERNIGHT SESSION COMPLETE', _said(result))
        finally:
            tmp.cleanup()

    def test_naive_end_time_is_utc_in_any_timezone(self) -> None:
        """A zone-less end_time is UTC (lib/overnight.py parse_end_time), so
        UTC now+1h is ahead and UTC now-1h has passed under TZ=Asia/Shanghai
        (UTC+8) and TZ=America/Los_Angeles (UTC-7/-8) alike."""
        utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
        for tz in ('Asia/Shanghai', 'America/Los_Angeles'):
            for delta, complete in ((1, False), (-1, True)):
                naive = (utc_now + timedelta(hours=delta)).isoformat()
                self.assertNotIn('+', naive)
                with self.subTest(tz=tz, delta=delta):
                    tmp = tempfile.TemporaryDirectory()
                    try:
                        tmpdir = Path(tmp.name)
                        _write_state(tmpdir, 'test-naive', naive)
                        env = {**os.environ, 'CLAUDE_PROJECT_DIR': str(tmpdir), 'TZ': tz}
                        result = subprocess.run(
                            [sys.executable, str(HOOK_PATH)], input=json.dumps(_build_payload('test-naive')),
                            capture_output=True, text=True, env=env, timeout=10)
                        self.assertEqual(result.returncode, 0, msg=result.stderr)
                        self.assertEqual('OVERNIGHT SESSION COMPLETE' in _said(result), complete, result.stdout)
                        if not complete:
                            self.assertIn('Time remaining: 0h 59m', _said(result))
                    finally:
                        tmp.cleanup()

    def test_cycle_number_is_read_from_the_retrospectives(self) -> None:
        """The loop writes no state: the cycle that ended is the last one
        whose PM retrospective is on disk under the working root, whatever
        cycle_count the record carries. CLAUDE_OBLIGATION_TERMINAL=off
        isolates this from the unrelated G4 terminal-gate conditions (a)/(b)."""
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        sid = 'test-cycle-index'
        tmp = tempfile.TemporaryDirectory()
        tmpdir = Path(tmp.name)
        try:
            state_path = _write_state(tmpdir, sid, future, cycle_count=5)
            session_dir = tmpdir / 'worktree' / 'docs' / 'dev' / 'overnight' / sid
            session_dir.mkdir(parents=True)
            for n in (1, 2):
                (session_dir / f'retro-report-cycle{n}.json').write_text('{}')
            before = state_path.read_bytes()

            env = os.environ.copy()
            env['CLAUDE_PROJECT_DIR'] = str(tmpdir)
            env['CLAUDE_OBLIGATION_TERMINAL'] = 'off'
            result = subprocess.run(
                [sys.executable, str(HOOK_PATH)],
                input=json.dumps(_build_payload(sid)),
                capture_output=True,
                text=True,
                env=env,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn('OVERNIGHT LOOP: Cycle 2 complete (PM retro filed). '
                          'Starting cycle 3.', _said(result))
            self.assertEqual(state_path.read_bytes(), before)
        finally:
            tmp.cleanup()

    def test_a_replay_sees_the_continuation_and_never_plain_stdout(self) -> None:
        """tests/replay/hookrun.context, the text a replay's driver acts on, is
        the hook's additionalContext; the same text printed plain, as the hook
        did before, hands the agent nothing on PostToolUse."""
        from tests.replay import hookrun
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        result, tmp = _exec_case(future, 'test-replay-view')
        try:
            run = {'verdict': hookrun.interpret(result.returncode, result.stdout)[0], 'stdout': result.stdout}
            self.assertEqual(run['verdict'], 'ok')
            seen = hookrun.context('PostToolUse', run)
            self.assertEqual(seen, _said(result))
            self.assertIn('Reset your todo list', seen)
            self.assertEqual(hookrun.context('PostToolUse', {'verdict': 'ok', 'stdout': seen + '\n'}), '')
            self.assertEqual(hookrun.context('Stop', run), '')
        finally:
            tmp.cleanup()


if __name__ == '__main__':
    unittest.main()
