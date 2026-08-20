#!/usr/bin/env python3
"""Regression tests for hooks/prompt-workflow.py overnight liveness + session binding.

Two defects, both reproduced before this suite was written:

1. ``_is_active_state`` compared an AWARE ``fromisoformat`` parse against a NAIVE
   ``datetime.now()``. On CPython 3.11+ that raises ``TypeError``, which the
   ``except (ValueError, TypeError)`` guard absorbed into the fail-closed value
   ``False``. Every ``end_time`` the launcher writes carries a zone designator,
   so the predicate reported not-live for 100% of real sessions -- silently, with
   no log and no degraded-mode signal. Same defect class as the sibling fix
   recorded at ``hooks/posttool-overnight-file-check.py:28-32``.

2. ``find_any_overnight_state`` globbed ``.claude/overnight-state-*.json``
   project-wide and returned the first live match, while ``handle_phase_b``
   discarded the submitting session id. Consequence: one live session was served
   another's state, and a session that submitted an unrelated prompt received the
   full continuation block instructing it to run an unattended development loop.

Structured after ``tests/test_overnight_loop_tz.py``.

``PW_HOOK_PATH`` overrides the module under test so an off-live release candidate
can be validated before it is published onto the live hook path (the working-tree
hook and the registered ``$HOME/.claude/hooks`` path are the same inode).
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK_PATH = Path(os.environ.get('PW_HOOK_PATH') or (REPO / 'hooks' / 'prompt-workflow.py'))
COMMAND_DOC = REPO / 'commands' / 'dev-overnight.md'
TODO_SCRIPT = REPO / 'scripts' / 'todo' / 'dev-overnight.py'

# AC1 mandates the zone be pinned per row group, and mandates a mechanism that
# actually moves datetime.now(). Assigning os.environ['TZ'] alone does NOT --
# CPython caches the zone until time.tzset() is called, so an unpinned run leaves
# rows 13/14/15 non-discriminating while the suite still reports green.
TZ_PINNING_MECHANISM = "os.environ['TZ'] + time.tzset() + restore"


@contextmanager
def pinned_tz(zone: str):
    """Pin the process zone so datetime.now() actually moves, then restore."""
    previous = os.environ.get('TZ')
    os.environ['TZ'] = zone
    time.tzset()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop('TZ', None)
        else:
            os.environ['TZ'] = previous
        time.tzset()


def load_hook_module():
    """Load the hook under test as a real module (fresh globals each call)."""
    loader = SourceFileLoader('pw_under_test', str(HOOK_PATH))
    spec = spec_from_loader(loader.name, loader)
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


def build_state(session_id: str, end_time: str | None, cycle_count: int = 3,
                phase: str = 'implementing', worktree: str = '/tmp/wt',
                omit_end_time: bool = False, omit_session_id: bool = False) -> dict:
    state = {
        'session_id': session_id,
        'end_time': end_time,
        'cycle_count': cycle_count,
        'current_phase': phase,
        'issues_fixed': 0,
        'worktree_path': worktree,
        'focus': 'none',
        'cycle_log': [],
        'current_issues': [],
    }
    if omit_end_time:
        del state['end_time']
    if omit_session_id:
        del state['session_id']
    return state


def write_state(claude_dir: Path, file_key: str, state: dict) -> Path:
    claude_dir.mkdir(parents=True, exist_ok=True)
    path = claude_dir / f'overnight-state-{file_key}.json'
    path.write_text(json.dumps(state, indent=2))
    return path


def future_z(hours: int = 1) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%SZ')


PAST_Z = '2000-01-01T00:00:00Z'
FAR_FUTURE_Z = '2099-01-01T00:00:00Z'


@contextmanager
def temp_project(fixture_command_doc: bool = False):
    """A hermetic project root with HOME redirected.

    HOME must be redirected: $HOME/.claude is a symlink to the repo root, so a
    fixture writing through HOME would mutate the working tree and could corrupt
    concurrent sibling-lane work (BA dev constraint C6).
    """
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        project = root / 'project'
        home = root / 'home'
        (project / '.claude').mkdir(parents=True)
        (home / '.claude').mkdir(parents=True)
        if fixture_command_doc:
            commands = project / '.claude' / 'commands'
            commands.mkdir(parents=True)
            (commands / 'dev-overnight.md').write_text(COMMAND_DOC.read_text())
        yield project, home


def run_hook(project: Path, home: Path, payload: dict, extra_env: dict | None = None):
    """Drive the hook across the real main() process boundary."""
    env = dict(os.environ)
    env['CLAUDE_PROJECT_DIR'] = str(project)
    env['HOME'] = str(home)
    env['CLAUDE_DEV_OVERNIGHT_TODO'] = str(TODO_SCRIPT)
    env.pop('CLAUDE_COMPAT_RUNTIME', None)
    env.pop('TZ', None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload), capture_output=True, text=True,
        env=env, cwd=str(project), timeout=180,
    )


def prompt_payload(session_id: str | None, prompt: str = 'continue') -> dict:
    payload: dict = {'prompt': prompt, 'cwd': None}
    payload.pop('cwd')
    if session_id is not None:
        payload['session_id'] = session_id
    return payload


class TestAC1Truthtable(unittest.TestCase):
    """AC1 -- 21-row truth table, zone pinned per row group."""

    def _assert_rows(self, module, rows):
        for n, state, expected in rows:
            with self.subTest(row=n, state=state):
                try:
                    actual = module._is_active_state(state)
                except BaseException as exc:  # noqa: BLE001 - AC1 forbids escape
                    self.fail(f'row {n}: exception escaped _is_active_state: {exc!r}')
                self.assertEqual(
                    expected, actual,
                    f'row {n}: end_time={state.get("end_time", "__KEY_ABSENT__")!r} '
                    f'expected {expected}, got {actual}',
                )

    def test_group_a_utc(self):
        """Rows 1-13 under TZ=UTC. Row 13 discriminates tzinfo-stripping."""
        with pinned_tz('UTC'):
            module = load_hook_module()
            now_utc = datetime.now(timezone.utc)
            digits_plus_4h = (now_utc + timedelta(hours=4)).strftime('%Y-%m-%dT%H:%M:%S')
            rows = [
                (1, {'end_time': FAR_FUTURE_Z}, True),
                (2, {'end_time': '2099-01-01T00:00:00+00:00'}, True),
                (3, {'end_time': '2099-01-01T00:00:00+08:00'}, True),
                (4, {'end_time': '2099-01-01T00:00:00'}, True),
                (5, {'end_time': PAST_Z}, False),
                (6, {'end_time': '2000-01-01T00:00:00+00:00'}, False),
                (7, {'end_time': '2000-01-01T00:00:00'}, False),
                (8, {}, False),
                (9, {'end_time': ''}, False),
                (10, {'end_time': 'not-a-date'}, False),
                (11, {'end_time': None}, False),
                (12, {'end_time': (now_utc + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')}, True),
                # Digits read 4h in the future; the +08:00 offset puts the true
                # instant 4h in the PAST. A stripping implementation says True.
                (13, {'end_time': digits_plus_4h + '+08:00'}, False),
            ]
            self._assert_rows(module, rows)

    def test_group_b_asia_shanghai(self):
        """Rows 14-16 under TZ=Asia/Shanghai. 14/15 pin naive-as-local; 16 kills stripping."""
        with pinned_tz('Asia/Shanghai'):
            module = load_hook_module()
            naive_local = datetime.now()
            rows = [
                (14, {'end_time': (naive_local + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%S')}, True),
                (15, {'end_time': (naive_local - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%S')}, False),
                (16, {'end_time': future_z(1)}, True),
            ]
            self._assert_rows(module, rows)

    def test_group_c_non_string_types(self):
        """Rows 17-21 under TZ=UTC: non-string end_time must be rejected, never raise."""
        with pinned_tz('UTC'):
            module = load_hook_module()
            rows = [
                (17, {'end_time': 1}, False),
                (18, {'end_time': {'a': 1}}, False),
                (19, {'end_time': ['x']}, False),
                (20, {'end_time': 3.5}, False),
                (21, {'end_time': True}, False),
            ]
            self._assert_rows(module, rows)

    def test_tz_pinning_actually_moves_the_clock(self):
        """The pinning mechanism itself must take effect, or 13/14/15 stop discriminating."""
        with pinned_tz('UTC'):
            utc_hour = datetime.now().hour
        with pinned_tz('Asia/Shanghai'):
            shanghai_hour = datetime.now().hour
        self.assertNotEqual(
            utc_hour, shanghai_hour,
            'time.tzset() did not move datetime.now(); AC1 group pinning is inert',
        )


class TestAC2Continuation(unittest.TestCase):
    """AC2 -- the owning session's live record yields a block with the four markers."""

    def test_owning_session_gets_block(self):
        # fixture_command_doc: the heavy half is only emitted when a command
        # document actually resolves. Without it the builder now correctly
        # refuses to certify an empty payload, so this test would be asserting
        # against the degenerate emission rather than a real block.
        with temp_project(fixture_command_doc=True) as (project, home):
            module = load_hook_module()
            module.PROJECT_DIR = project
            sid = 'AAAA-owner'
            write_state(project / '.claude', sid,
                        build_state(sid, future_z(1), cycle_count=3))
            os.environ['HOME'] = str(home)
            try:
                block = module.check_overnight_continuation(sid)
            finally:
                os.environ['HOME'] = str(Path.home())
            self.assertIsNotNone(block, 'live owned record must yield a block')
            for marker in ('OVERNIGHT CONTINUATION - Cycle 4',
                           '--- COMMAND SPECIFICATION ---',
                           '--- CURRENT STATE ---',
                           'Phase mapping:'):
                self.assertIn(marker, block)


class TestAC3BlockComposition(unittest.TestCase):
    """AC3 -- hermetic: the spec is embedded verbatim exactly once and the phase routes."""

    def test_block_embeds_spec_once_and_routes_phase(self):
        with temp_project(fixture_command_doc=True) as (project, home):
            previous_home = os.environ.get('HOME')
            previous_todo = os.environ.get('CLAUDE_DEV_OVERNIGHT_TODO')
            os.environ['HOME'] = str(home)
            os.environ['CLAUDE_DEV_OVERNIGHT_TODO'] = str(TODO_SCRIPT)
            try:
                module = load_hook_module()
                module.PROJECT_DIR = project
                sid = 'AAAA-owner'
                write_state(project / '.claude', sid,
                            build_state(sid, future_z(1), cycle_count=3,
                                        worktree=str(project / 'wt')))
                spec = module.read_command_spec('dev-overnight')
                todos = module._load_overnight_todos()
                block = module.check_overnight_continuation(sid)
            finally:
                if previous_home is not None:
                    os.environ['HOME'] = previous_home
                if previous_todo is None:
                    os.environ.pop('CLAUDE_DEV_OVERNIGHT_TODO', None)
                else:
                    os.environ['CLAUDE_DEV_OVERNIGHT_TODO'] = previous_todo
            self.assertTrue(spec, 'fixtured command spec must resolve non-empty')
            self.assertTrue(todos, '_load_overnight_todos must be non-empty')
            self.assertIsNotNone(block)
            self.assertEqual(1, block.count(spec), 'spec must be embedded exactly once')
            self.assertIn('implementing->Step 12', block)
            self.assertIn('CRITICAL: The validated isolated worktree is', block)
            self.assertNotIn('HARD ABORT. The overnight state has no validated worktree.', block)
            self.assertIn(f'when all {len(todos)} steps complete', block)


class TestAC4FailClosed(unittest.TestCase):
    """AC4 -- every rejected end_time yields None, with no exception escaping."""

    def test_rejected_end_times_yield_none(self):
        string_cases = [PAST_Z, 'not-a-date']
        non_string_cases = [1, {'a': 1}, ['x'], 3.5, True]
        with temp_project() as (project, home):
            module = load_hook_module()
            module.PROJECT_DIR = project
            sid = 'AAAA-owner'
            previous_home = os.environ.get('HOME')
            os.environ['HOME'] = str(home)
            try:
                for case in string_cases + non_string_cases + ['__KEY_ABSENT__']:
                    with self.subTest(case=case):
                        omit = case == '__KEY_ABSENT__'
                        state = build_state(sid, None if omit else case,
                                            omit_end_time=omit)
                        write_state(project / '.claude', sid, state)
                        # Direct call: a subprocess exit code cannot distinguish a
                        # clean rejection from an escaping AttributeError, because
                        # main() swallows generic exceptions and exits 0.
                        try:
                            live = module._is_active_state(state)
                        except BaseException as exc:  # noqa: BLE001
                            self.fail(f'{case!r}: exception escaped _is_active_state: {exc!r}')
                        self.assertFalse(live)
                        self.assertIsNone(module.check_overnight_continuation(sid))
            finally:
                if previous_home is not None:
                    os.environ['HOME'] = previous_home


AC5_ZERO_CHAR_ROWS = ['5.2', '5.5', '5.6', '5.7', '5.10', '5.11', '5.12']
AC5_ROW_COUNT = 12
DISCRIMINATING_ROWS = {
    '5.11': 'the only row separating strict identity binding from a weak '
            'filename-keyed predicate (a weak predicate passes 5.1-5.10 byte-identically)',
    '5.12': 'the only row catching a correct rejection followed by a fallback '
            'scan onto a competing valid record',
}


class TestAC5SessionBinding(unittest.TestCase):
    """AC5 -- 12-row session-binding matrix driven through the real process boundary."""

    def _run_row(self, records, submitting, prompt='continue'):
        """records: list of (file_key, state dict). Returns CompletedProcess."""
        with temp_project() as (project, home):
            for file_key, state in records:
                write_state(project / '.claude', file_key, state)
            payload = prompt_payload(submitting, prompt)
            return run_hook(project, home, payload)

    def _assert_block(self, result, owner_sid, cycle_count):
        self.assertEqual(0, result.returncode)
        self.assertIn('OVERNIGHT CONTINUATION', result.stdout)
        self.assertIn(f'OVERNIGHT CONTINUATION - Cycle {cycle_count + 1}', result.stdout)
        self.assertIn(f'overnight-state-{owner_sid}.json', result.stdout)

    def _assert_zero(self, result):
        self.assertEqual(0, result.returncode)
        self.assertNotIn('OVERNIGHT CONTINUATION', result.stdout)
        self.assertEqual('', result.stdout.strip(),
                         'a non-owning session must receive zero injected characters')

    def test_row_5_1_owner_receives_own_block(self):
        state = build_state('AAAA', future_z(1), cycle_count=1)
        self._assert_block(self._run_row([('AAAA', state)], 'AAAA'), 'AAAA', 1)

    def test_row_5_2_stranger_receives_nothing(self):
        state = build_state('AAAA', future_z(1), cycle_count=1)
        self._assert_zero(self._run_row([('AAAA', state)], 'ZZZZ-stranger'))

    def test_row_5_3_and_5_4_two_live_records_each_gets_its_own(self):
        a = build_state('AAAA', future_z(1), cycle_count=3)
        b = build_state('BBBB', future_z(1), cycle_count=9)
        records = [('AAAA', a), ('BBBB', b)]
        self._assert_block(self._run_row(records, 'AAAA'), 'AAAA', 3)
        result_b = self._run_row(records, 'BBBB')
        self._assert_block(result_b, 'BBBB', 9)
        self.assertNotIn('OVERNIGHT CONTINUATION - Cycle 4', result_b.stdout,
                         'BBBB must not be served AAAA state')

    def test_row_5_5_payload_omits_session_id(self):
        state = build_state('AAAA', future_z(1), cycle_count=1)
        self._assert_zero(self._run_row([('AAAA', state)], None))

    def test_row_5_6_submitter_is_default(self):
        state = build_state('AAAA', future_z(1), cycle_count=1)
        self._assert_zero(self._run_row([('AAAA', state)], 'default'))

    def test_row_5_7_record_has_no_session_id_field(self):
        """A blank/absent record id must NOT broadcast.

        hooks/posttool-overnight-loop.py:156-159 guards with
        `if state_session_id and ...`, so mirroring it literally would still
        deliver this record to every session. Strict binding delivers nothing.
        """
        state = build_state('CCCC', future_z(1), cycle_count=1, omit_session_id=True)
        self._assert_zero(self._run_row([('CCCC', state)], 'CCCC'))
        self._assert_zero(self._run_row([('CCCC', state)], 'ZZZZ-stranger'))
        blank = build_state('', future_z(1), cycle_count=1)
        blank['session_id'] = ''
        self._assert_zero(self._run_row([('DDDD', blank)], 'DDDD'))

    def test_row_5_8_expired_sorts_first_live_owner_still_served(self):
        expired = build_state('AAAA', PAST_Z, cycle_count=1)
        live = build_state('ZZZZ', future_z(1), cycle_count=5)
        self._assert_block(self._run_row([('AAAA', expired), ('ZZZZ', live)], 'ZZZZ'),
                           'ZZZZ', 5)

    def test_row_5_9_only_expired_record(self):
        expired = build_state('AAAA', PAST_Z, cycle_count=1)
        self._assert_zero(self._run_row([('AAAA', expired)], 'AAAA'))

    def test_row_5_10_abandoned_far_future_record(self):
        abandoned = build_state('AAAA', FAR_FUTURE_Z, cycle_count=1)
        self._assert_zero(self._run_row([('AAAA', abandoned)], 'ZZZZ-stranger'))

    def test_row_5_11_file_key_versus_record_identity_mismatch(self):
        """DISCRIMINATING: a filename-keyed weak predicate passes every other row."""
        mismatched = build_state('AAAA', future_z(1), cycle_count=7)
        self._assert_zero(self._run_row([('BBBB', mismatched)], 'BBBB'))

    def test_row_5_11b_identity_comparison_is_case_sensitive(self):
        """Mutation lock: a case-insensitive identity comparison would accept
        'aaaa' as the owner of 'AAAA' and pass every other row unchanged."""
        variant = build_state('aaaa', future_z(1), cycle_count=7)
        self._assert_zero(self._run_row([('AAAA', variant)], 'AAAA'))
        owned = build_state('AAAA', future_z(1), cycle_count=7)
        self._assert_zero(self._run_row([('AAAA', owned)], 'aaaa'))

    def test_row_5_12_rejected_record_must_not_trigger_fallback_scan(self):
        """DISCRIMINATING: rejection must not be followed by a scan onto another record."""
        mismatched = build_state('AAAA', future_z(1), cycle_count=7)
        competing = build_state('AAAA', future_z(1), cycle_count=42)
        result = self._run_row([('BBBB', mismatched), ('AAAA', competing)], 'BBBB')
        self._assert_zero(result)
        self.assertNotIn('Cycle 43', result.stdout)
        self.assertNotIn('Cycle 8', result.stdout)

    def test_matrix_declares_all_twelve_rows(self):
        """AC9.check.ac5_row_count reads 10; AC5.check.row_count, AC9's THEN text and
        AC9.check.coverage all read 12. 12 is authoritative -- building to 10 drops
        both discriminating rows."""
        self.assertEqual(12, AC5_ROW_COUNT)
        self.assertEqual({'5.11', '5.12'}, set(DISCRIMINATING_ROWS))
        self.assertEqual(7, len(AC5_ZERO_CHAR_ROWS))


class TestAC6ProcessBoundary(unittest.TestCase):
    """AC6 -- the block reaches a user prompt through the real main() boundary."""

    def test_live_session_injects_once(self):
        with temp_project() as (project, home):
            sid = 'AAAA-owner'
            write_state(project / '.claude', sid, build_state(sid, future_z(1)))
            result = run_hook(project, home, prompt_payload(sid))
        self.assertEqual(0, result.returncode)
        self.assertEqual(1, result.stdout.count('OVERNIGHT CONTINUATION'))
        for marker in ('--- COMMAND SPECIFICATION ---', '--- CURRENT STATE ---',
                       'Phase mapping:'):
            self.assertIn(marker, result.stdout)

    def test_expired_state_injects_nothing(self):
        with temp_project() as (project, home):
            sid = 'AAAA-owner'
            write_state(project / '.claude', sid, build_state(sid, PAST_Z))
            result = run_hook(project, home, prompt_payload(sid))
        self.assertEqual(0, result.returncode)
        self.assertNotIn('OVERNIGHT CONTINUATION', result.stdout)

    def test_codex_runtime_injects_nothing(self):
        with temp_project() as (project, home):
            sid = 'AAAA-owner'
            write_state(project / '.claude', sid, build_state(sid, future_z(1)))
            result = run_hook(project, home, prompt_payload(sid),
                              extra_env={'CLAUDE_COMPAT_RUNTIME': 'codex'})
        self.assertEqual(0, result.returncode)
        self.assertNotIn('OVERNIGHT CONTINUATION', result.stdout)

    def test_slash_command_prompt_is_not_phase_b(self):
        with temp_project() as (project, home):
            sid = 'AAAA-owner'
            write_state(project / '.claude', sid, build_state(sid, future_z(1)))
            result = run_hook(project, home, prompt_payload(sid, prompt='/status'))
        self.assertEqual(0, result.returncode)
        self.assertNotIn('OVERNIGHT CONTINUATION', result.stdout)


class TestAC7ExceptSetEquality(unittest.TestCase):
    """AC7 -- the caught set must EQUAL {ValueError, TypeError}, not merely subset it."""

    def _caught_names(self):
        tree = ast.parse(HOOK_PATH.read_text())
        target = None
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == '_is_active_state':
                target = node
        self.assertIsNotNone(target, '_is_active_state not found at module top level')
        names: set[str] = set()
        for handler in [n for n in ast.walk(target) if isinstance(n, ast.ExceptHandler)]:
            self.assertIsNotNone(handler.type, 'bare except is forbidden')
            captured = handler.type
            parts = captured.elts if isinstance(captured, ast.Tuple) else [captured]
            for part in parts:
                self.assertIsInstance(part, ast.Name, 'only plain exception names permitted')
                names.add(part.id)
        return names

    def test_caught_set_equals_value_error_and_type_error(self):
        names = self._caught_names()
        self.assertEqual({'ValueError', 'TypeError'}, names,
                         'the caught set must be EQUAL to the pre-fix set, not a superset')
        self.assertNotIn('Exception', names)
        self.assertNotIn('BaseException', names)


class TestAC8PatchScope(unittest.TestCase):
    """AC8 -- only the four permitted symbols may differ inside the hook."""

    PERMITTED = ['_is_active_state', 'find_any_overnight_state',
                 'check_overnight_continuation', 'handle_phase_b']

    def test_each_permitted_symbol_defined_exactly_once(self):
        tree = ast.parse(HOOK_PATH.read_text())
        counts: dict[str, int] = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in self.PERMITTED:
                    counts[node.name] = counts.get(node.name, 0) + 1
        for name in self.PERMITTED:
            self.assertEqual(1, counts.get(name, 0),
                             f'{name} must have exactly one top-level definition')

    def test_handle_phase_b_only_threads_the_session_id(self):
        source = HOOK_PATH.read_text()
        tree = ast.parse(source)
        lines = source.splitlines()
        body = None
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == 'handle_phase_b':
                body = '\n'.join(lines[node.lineno - 1:node.end_lineno])
        self.assertIsNotNone(body)
        self.assertIn('check_overnight_continuation(session_id)', body,
                      'handle_phase_b must thread the submitting session id through')


if __name__ == '__main__':
    unittest.main()
