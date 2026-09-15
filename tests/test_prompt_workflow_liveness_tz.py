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
        # fixture_command_doc: same reason as AC2 -- the builder now refuses to
        # certify an empty payload, so without a resolvable command document the
        # heavy half (and the COMMAND SPECIFICATION marker asserted below) is
        # legitimately absent.
        with temp_project(fixture_command_doc=True) as (project, home):
            sid = 'AAAA-owner'
            write_state(project / '.claude', sid,
                        build_state(sid, future_z(1), cycle_count=3))
            result = run_hook(project, home, prompt_payload(sid))
        self.assertEqual(0, result.returncode)
        # Collect whole banner LINES rather than counting the bare phrase: the
        # embedded command document mentions "OVERNIGHT CONTINUATION" in its own
        # prose, so the bare phrase occurs twice for one real emission. A bare
        # substring count of the cycle-designated form would be no better -- it
        # matches 'Cycle 40' inside 'Cycle 4', and a second banner bearing a
        # DIFFERENT cycle number would leave the count at 1. Comparing the full
        # line list catches an extra banner of any cycle number.
        banners = [line for line in result.stdout.splitlines()
                   if line.startswith('OVERNIGHT CONTINUATION - Cycle ')]
        self.assertEqual(['OVERNIGHT CONTINUATION - Cycle 4'], banners)
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


STUB_LAUNCHER = '''#!/usr/bin/env bash
set -euo pipefail
SESSION_ID=""; PROJECT_DIR=""
printf '%s\\n' "$@" > "${STUB_ARGV_LOG:?}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --session-id) SESSION_ID="$2"; shift 2;;
    --project-dir) PROJECT_DIR="$2"; shift 2;;
    --end-time|--focus|--spec|--state-subdir|--cycle-subdir|--specs-subdir) shift 2;;
    *) shift;;
  esac
done
if [[ -z "$SESSION_ID" ]]; then SESSION_ID="$(uuidgen)"; fi
mkdir -p "$PROJECT_DIR/.claude"
printf '{"session_id":"%s","end_time":"2099-01-01T00:00:00Z","cycle_count":0,"phase":"init"}\\n' \\
  "$SESSION_ID" > "$PROJECT_DIR/.claude/overnight-state-$SESSION_ID.json"
'''

STUB_INIT = '#!/usr/bin/env bash\necho OVERNIGHT_INIT_OK\n'


class TestF10IdentityLessFailClosed(unittest.TestCase):
    """A missing identity must not be synthesized into a usable one.

    ``main()`` resolved an absent payload ``session_id`` to the literal
    ``'default'``, and ``create_overnight_state`` defaulted the same parameter to
    the same literal and always forwarded it. One fallback therefore both MINTED
    ``overnight-state-default.json`` and later SERVED it: a payload omitting
    ``session_id`` was handed the whole continuation block (137,183 chars
    measured on the pre-fix tree). AC5 rows 5.5/5.6 missed it because they seed
    only an AAAA-owned record, exercising MISMATCH rather than fail-closed
    omission.

    The consumption half is a subtraction ('' is already rejected). The creation
    half is NOT: with '' forwarded, the launcher mints an id it does not return,
    so ``verify_overnight_state`` resolves ``overnight-state-.json``, aborts the
    launch, and ``_cleanup_overnight_partials`` -- keyed on the same '' -- leaves
    the freshly published record live. The boundary guard globs
    ``overnight-state-*.json`` project-wide, so that orphan would arm isolation
    for an aborted launch. Hence the id is minted in the hook.
    """

    SHARED_LITERALS = ('default', '', 'None', 'null')

    # The shared prompt_payload() helper spells an omitted key as None, so it
    # cannot express JSON null -- and the two are different inputs: an absent key
    # takes main()'s .get() default, an explicit null takes the null. Both must
    # be probed, so this class carries its own sentinel rather than widening the
    # helper other classes depend on.
    OMIT = object()

    def _payload(self, submitting, prompt='continue'):
        payload = {'prompt': prompt}
        if submitting is not self.OMIT:
            payload['session_id'] = submitting
        return payload

    def test_the_two_identity_less_shapes_are_actually_distinct(self):
        """Guards the fixture itself: without this, 'null' silently means 'absent'."""
        self.assertNotIn('session_id', self._payload(self.OMIT))
        self.assertIn('"session_id": null', json.dumps(self._payload(None)))

    # --- consumption half -----------------------------------------------------

    def _run_phase_b(self, records, submitting):
        with temp_project() as (project, home):
            for file_key, state in records:
                write_state(project / '.claude', file_key, state)
            return run_hook(project, home, self._payload(submitting))

    def test_absent_identity_with_live_default_record_receives_nothing(self):
        """The F-10 regression: the row AC5 never seeded."""
        state = build_state('default', future_z(1), cycle_count=3)
        result = self._run_phase_b([('default', state)], self.OMIT)
        self.assertEqual(0, result.returncode)
        self.assertNotIn('OVERNIGHT CONTINUATION', result.stdout)
        self.assertEqual('', result.stdout,
                         'a payload with no session_id must receive zero '
                         'characters even when a default-keyed record is live')

    def test_null_and_empty_identities_stay_closed_against_a_default_record(self):
        """The record AC5 never seeded, probed with every identity-less shape."""
        state = build_state('default', future_z(1), cycle_count=3)
        for label, submitting in (('json null', None), ('empty string', ''),
                                  ('stranger', 'ZZZZ-stranger')):
            with self.subTest(submitting=label):
                result = self._run_phase_b([('default', state)], submitting)
                self.assertEqual('', result.stdout)

    def test_owner_is_unaffected(self):
        state = build_state('AAAA', future_z(1), cycle_count=1)
        result = self._run_phase_b([('AAAA', state)], 'AAAA')
        self.assertIn('OVERNIGHT CONTINUATION - Cycle 2', result.stdout)
        self.assertIn('overnight-state-AAAA.json', result.stdout)

    # --- creation half --------------------------------------------------------

    @contextmanager
    def _stubbed_launch_root(self):
        """A project whose launcher and initializer are recording stubs.

        The real launcher demands a primary git checkout and creates worktrees,
        branches and a dev-registry; stubbing it keeps the assertion on the one
        thing this lane owns -- which identity the hook decides on and forwards.
        """
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project, home = root / 'project', root / 'home'
            (project / '.claude').mkdir(parents=True)
            scripts = home / '.claude' / 'scripts'
            (scripts / 'todo').mkdir(parents=True)
            for name, body in (('create-overnight-state.sh', STUB_LAUNCHER),
                               ('overnight-init.sh', STUB_INIT)):
                path = scripts / name
                path.write_text(body)
                path.chmod(0o755)
            (scripts / 'todo' / 'dev-overnight.py').write_text(TODO_SCRIPT.read_text())
            yield project, home, root / 'argv.txt'

    def _launch(self, submitting):
        """Drive a /dev-overnight launch. Returns (result, forwarded_id, keys)."""
        with self._stubbed_launch_root() as (project, home, argv_log):
            payload = self._payload(submitting, prompt='/dev-overnight 23:59')
            result = run_hook(project, home, payload,
                              {'STUB_ARGV_LOG': str(argv_log)})
            argv = argv_log.read_text().splitlines() if argv_log.exists() else []
            forwarded = (argv[argv.index('--session-id') + 1]
                         if '--session-id' in argv else None)
            keys = sorted(p.name[len('overnight-state-'):-len('.json')]
                          for p in (project / '.claude').glob('overnight-state-*.json'))
            return result, forwarded, keys

    def test_launch_without_an_identity_still_produces_a_usable_record(self):
        """Launch-succeeds is a DELIBERATE choice, not an oversight.

        Adversarial review argued the opposite -- that an identity-less launch
        should be refused outright, since a runtime that omits the key at launch
        omits it afterwards too, leaving a record its own session cannot resume.
        The dispatched acceptance criterion is explicit the other way ('a launch
        that supplies no identity still produces a usable record rather than
        failing ... confirm it is not a shared literal that another session
        could later be served'), so the requirement governs. Refusal is a
        one-line change here if that criterion is ever revised; this test is
        where the decision is recorded.
        """
        result, forwarded, keys = self._launch(self.OMIT)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([forwarded], keys,
                         'the published record must be keyed on the id the hook '
                         'forwarded, so verify/cleanup resolve the same path')
        self.assertNotIn(forwarded, self.SHARED_LITERALS)

    def test_minted_identity_is_unique_per_launch(self):
        """Uniqueness is the property that makes the record unservable to others."""
        minted = {self._launch(self.OMIT)[1] for _ in range(3)}
        self.assertEqual(3, len(minted), f'ids must not repeat: {minted}')

    def test_no_identity_less_payload_shape_can_mint_a_shared_literal_record(self):
        for label, submitting in (('absent key', self.OMIT), ('json null', None),
                                  ('empty string', '')):
            with self.subTest(submitting=label):
                result, forwarded, keys = self._launch(submitting)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual([forwarded], keys)
                self.assertNotIn('default', keys)

    def test_an_explicitly_declared_default_identity_is_still_its_own_owner(self):
        """The bound on the claim, pinned so the report cannot overstate it.

        Identity binding is by identity, not by denylist: a session that
        DECLARES its id as the literal 'default' mints and owns
        overnight-state-default.json exactly as any other id would, and is
        served its own record. What the fix removes is the identity-LESS route
        to that filename -- the one that made a single fallback both mint the
        record and serve it to unrelated prompts.
        """
        result, forwarded, keys = self._launch('default')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('default', forwarded)
        self.assertEqual(['default'], keys)

    def test_a_real_identity_is_forwarded_verbatim(self):
        result, forwarded, keys = self._launch('RRRR')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('RRRR', forwarded)
        self.assertEqual(['RRRR'], keys)

    def test_the_literal_survives_nowhere_in_the_identity_path(self):
        """Both fallbacks are gone from the two symbols that carried them."""
        source = HOOK_PATH.read_text()
        tree = ast.parse(source)
        lines = source.splitlines()
        for name in ('main', 'create_overnight_state'):
            node = next(n for n in tree.body
                        if isinstance(n, ast.FunctionDef) and n.name == name)
            body = '\n'.join(lines[node.lineno - 1:node.end_lineno])
            code = '\n'.join(ln for ln in body.splitlines()
                             if not ln.lstrip().startswith('#'))
            self.assertNotIn("'default'", code,
                             f'{name} must not resolve a missing identity to a literal')


class TestAC10G1BoundsUnderOptionR(unittest.TestCase):
    """AC10 G1 assertion[4] as amended under F-11 option R (human-authorized).

    WHAT THE RELATIONAL CEILING DOES NOT DO. It does not bound absolute
    magnitude, and no reading of it should suggest otherwise. ``boundary_block``
    appears on BOTH sides of the inequality, so it cancels and the margin is
    algebraically constant: (B + 3*MAX) - (B + 2*light) = 9000 - 5534 = 3466 for
    every value of B. Executed both ways: inflating the fixtured command
    document to 647,667 chars moved the cumulative to 655,823 -- 4.7x the
    retired 140,000 constant -- while every bound in this class still passed and
    the margin measured 3,466 at BOTH magnitudes. The spec-share floor below
    gets EASIER as the document grows (0.9801 -> 0.9957), so it certifies that
    the unbounded term dominates rather than constraining it. Unbounded absolute
    magnitude is the STATED and human-accepted consequence of option R; the two
    absolute ceilings here bound only the lane-owned share, measured at 1.99%
    of the total.

    The superseded literal read ``cumulative across the 3 prompts is < 140000``.
    It is an ABSOLUTE constant pinned against commands/dev-overnight.md, a
    document this lane neither owns nor can shrink, and which a concurrent lane
    keeps growing: 142,535 -> 144,283 -> 145,331 -> the figure this class
    measures. Two independent analyses put achievable document surgery at
    <= 0.79%, so no amount of trimming closes the gap; the constant, not the
    mechanism, is what drifted.

    Option R replaces the cumulative upper bound with the relational form the
    sibling lane already adopted (inject AC-1 ``cumulative_max_relational``),
    plus its ``cumulative_min_relational`` floor -- which is retained for
    form-parity with the sibling and is NOT a collapse guard; see the floor
    assertion below for the mutation that settles that.

    THE G3 HAZARD IS ACCEPTED FOR TOTAL MAGNITUDE, ANSWERED ONLY FOR THE
    LANE-OWNED SHARE. G3 was discharged via discharge_path_b (a recorded user
    decision), never via its absolute discharge_path_a bar, so converting this
    assertion to relational leaves NO absolute bound on total payload magnitude
    anywhere in the tz criteria. That outcome is not averted here -- it is the
    accepted consequence stated above. What this class does bound is the share
    the lane controls. The boundary block decomposes into a share this lane
    cannot control -- the command document, embedded verbatim -- and two terms
    it can. Both controllable terms keep ABSOLUTE ceilings, so absolute
    magnitude stays bounded for everything the lane can actually move:

      * the recurring per-prompt light payload  <= G1_PER_PROMPT_MAX_CHARS
      * the boundary block's NON-SPEC overhead  <= G1_BOUNDARY_OVERHEAD_MAX_CHARS

    Only the verbatim document share is left unbounded in absolute terms, and it
    is bounded by IDENTITY instead: emitted at most once per delivery key, which
    is what assertions 1 and 2 measure. Its magnitude residual stays recorded
    under G3 as discharged-not-met and is NOT closed by this class.
    """

    G1_RUNS = 3
    G1_PROMPTS = ('continue', 'what next?', 'ok go on')
    G1_PER_PROMPT_MIN_CHARS = 1500          # unchanged floor, carried over
    # FIXTURE-SHAPED ceiling, not a production one. Sibling inject AC-1 attaches
    # `per_prompt_max_chars_scope` to this very number: "AC-1's own fixture shape
    # as declared in 'given' (no main_root, no actor_git_env). NOT a production
    # figure and must not be quoted as one downstream." This class's base fixture
    # is that same shape (build_state populates neither field), so 3,000 is the
    # correct ceiling HERE and must not be cited as bounding production payload.
    G1_PER_PROMPT_MAX_CHARS = 3000
    # PRODUCTION-SHAPED ceiling: the sibling's own `production_shaped_per_prompt
    # _max_chars`, for the state create-overnight-state.sh actually writes.
    # Populating main_root + actor_git_env selects the long worktree branch and
    # the light payload measures 3,554 -- above the fixture ceiling by design.
    G1_PRODUCTION_PER_PROMPT_MAX_CHARS = 4000
    G1_PRODUCTION_MAX_RATIO_OF_BOUNDARY = 0.05
    G1_BOUNDARY_OVERHEAD_MAX_CHARS = 4000   # ABSOLUTE, the lane-owned block share
    G1_SPEC_SHARE_MIN_RATIO = 0.90          # anti-vacuity, see test below
    G1_MARKERS = ('OVERNIGHT CONTINUATION', '--- CURRENT STATE ---',
                  'Phase mapping:', 'CRITICAL: The validated isolated worktree is')

    @classmethod
    def setUpClass(cls):
        sid = 'AAAA-owner'
        with temp_project(fixture_command_doc=True) as (project, home):
            write_state(project / '.claude', sid,
                        build_state(sid, future_z(6), cycle_count=3,
                                    worktree=str(project / 'wt')))
            cls.outputs = [run_hook(project, home, prompt_payload(sid, p)).stdout
                           for p in cls.G1_PROMPTS]
            cls.stranger = run_hook(project, home,
                                    prompt_payload('ZZZZ-stranger', 'what is 2+2')).stdout
        cls.spec = load_hook_module()._strip_yaml_frontmatter(COMMAND_DOC.read_text()).strip()
        cls.heavy = [o for o in cls.outputs if cls.spec in o]
        cls.light = [o for o in cls.outputs if cls.spec not in o]
        cls.cumulative = sum(len(o) for o in cls.outputs)
        cls.boundary_block = max(len(o) for o in cls.outputs)
        cls.overhead = cls.boundary_block - len(cls.spec)

    def test_measurement_is_non_vacuous(self):
        """Guards the fixture: an empty spec would make every bound trivially true."""
        self.assertTrue(self.spec, 'fixtured command spec must resolve non-empty')
        self.assertEqual(self.G1_RUNS, len(self.outputs))
        self.assertEqual(0, len(self.stranger),
                         'a stranger session must be charged zero characters')

    def test_assertions_1_and_2_exactly_one_heavy_delivery(self):
        self.assertEqual(1, len(self.heavy), 'exactly ONE prompt carries the spec')
        self.assertEqual(self.G1_RUNS - 1, len(self.light),
                         'the other prompts carry NONE of it')

    def test_assertion_3_light_prompts_keep_every_routing_marker(self):
        for index, output in enumerate(self.light):
            for marker in self.G1_MARKERS:
                with self.subTest(prompt=index, marker=marker):
                    self.assertIn(marker, output)

    def test_assertion_4_light_prompts_stay_inside_both_absolute_bounds(self):
        """The floor is the carried-over one; the ceiling is what option R adds.

        Adopting the relational cumulative half WITHOUT this per-prompt half
        would weaken the criterion rather than recalibrate it: the cumulative
        bound is an aggregate, so it constrains the average and an uneven split
        could pass it while one prompt individually blew past the ceiling.
        """
        for index, output in enumerate(self.light):
            with self.subTest(prompt=index, chars=len(output)):
                self.assertGreaterEqual(len(output), self.G1_PER_PROMPT_MIN_CHARS)
                self.assertLessEqual(len(output), self.G1_PER_PROMPT_MAX_CHARS)

    def test_production_shaped_state_is_bounded_by_the_production_figure(self):
        """The recurring term, bounded in the shape that actually ships.

        The class fixture leaves main_root and actor_git_env unset, so
        _build_worktree_instruction renders its short branch and the light
        payload measures 2,767. That is the shape sibling inject AC-1 scopes its
        3,000 ceiling to, and the sibling explicitly forbids quoting that number
        as a production figure. The launcher-written state populates both fields,
        selects the long branch, and measures 3,554 -- which BREACHES 3,000. The
        production-facing bound is therefore the sibling's own production figure,
        asserted here against a production-shaped state rather than merely
        caveated, together with its ratio-of-boundary companion so an absolute
        cap alone cannot drift loose as the command document grows.
        """
        sid = 'AAAA-owner'
        with temp_project(fixture_command_doc=True) as (project, home):
            state = build_state(sid, future_z(6), cycle_count=3,
                                worktree=str(project / 'wt'))
            # The shape create-overnight-state.sh writes. Every path derives from
            # the fixture's own temp root; nothing here is a live-tree literal.
            claude = project / '.claude'
            state['isolation_kind'] = 'registered_worktree'
            state['worktree_branch'] = 'worktree-overnight-20260904-aaaaaaaa'
            state['protected_branch'] = 'master'
            state['main_root'] = str(project)
            state['actor_git_env'] = {
                'shim_git': str(claude / 'overnight-git-policy-bin' / 'git'),
                'bindir': str(claude / 'overnight-git-bin'),
                'shimdir': str(claude / 'overnight-git-policy-bin'),
                'env_helper': str(project / 'scripts' / 'overnight-git-env.sh'),
                'marker_only': False,
            }
            write_state(claude, sid, state)
            outputs = [run_hook(project, home, prompt_payload(sid, p)).stdout
                       for p in self.G1_PROMPTS]

        light = [o for o in outputs if self.spec not in o]
        boundary = max(len(o) for o in outputs)
        self.assertEqual(self.G1_RUNS - 1, len(light))
        # The long branch really is in force -- without this the case would
        # silently re-measure the fixture shape and prove nothing.
        self.assertIn('source the actor git-env', light[0])
        for index, output in enumerate(light):
            with self.subTest(prompt=index, chars=len(output)):
                self.assertGreater(
                    len(output), self.G1_PER_PROMPT_MAX_CHARS,
                    'production shape no longer exceeds the fixture ceiling; the '
                    'two shapes have converged and this case is now vacuous')
                self.assertLessEqual(len(output),
                                     self.G1_PRODUCTION_PER_PROMPT_MAX_CHARS)
                self.assertLessEqual(
                    len(output), boundary * self.G1_PRODUCTION_MAX_RATIO_OF_BOUNDARY)
        # The other lane-owned absolute ceiling, re-measured in the same shape:
        # the block overhead grows with the long branch too and must still hold.
        self.assertLessEqual(boundary - len(self.spec),
                             self.G1_BOUNDARY_OVERHEAD_MAX_CHARS)

    def test_amended_assertion_5_cumulative_is_relational_not_absolute(self):
        """Option R: bound the cumulative against the block it actually contains.

        THE FLOOR BELOW IS A TAUTOLOGY AND IS LABELLED AS ONE. ``cumulative`` is
        sum(len(o)) and ``boundary_block`` is max(len(o)) over the SAME output
        list, and sum >= max holds for any list of non-negative lengths: 0
        counterexamples in an exhaustive sweep of 64,000 configurations and 0 in
        2,000,000 randomised ones. Executed against a mutant hook that delivers
        once and then emits nothing -- the exact collapse this floor was
        previously credited with catching -- this method PASSED, on outputs
        [140694, 0, 0]. What actually caught that mutant was
        ``test_assertion_3_light_prompts_keep_every_routing_marker`` (8 subtest
        failures) and the >= G1_PER_PROMPT_MIN_CHARS half of
        ``test_assertion_4_light_prompts_stay_inside_both_absolute_bounds`` (2).
        Strengthening the floor to ``max + (runs-1)*MIN`` was measured and
        rejected: it is strictly implied by that per-prompt floor (0 discriminating
        configurations in 500,000), so it would add a second name for the same
        check rather than a new guarantee. The floor is kept because the sibling
        criterion declares ``cumulative_min_relational`` and the discharge
        linkage depends on both sides carrying the same form -- not because it
        can fail.
        """
        ceiling = self.boundary_block + self.G1_RUNS * self.G1_PER_PROMPT_MAX_CHARS
        self.assertLess(self.cumulative, ceiling,
                        f'cumulative {self.cumulative} must stay under '
                        f'{self.boundary_block} + {self.G1_RUNS} * '
                        f'{self.G1_PER_PROMPT_MAX_CHARS} = {ceiling}')
        self.assertGreaterEqual(self.cumulative, self.boundary_block,
                                'form-parity with the sibling cumulative_min_relational; '
                                'sum >= max is a tautology and catches no collapse')

    def test_g3_hazard_boundary_overhead_keeps_an_absolute_ceiling(self):
        """The absolute guard option R would otherwise have removed.

        This is the term the lane owns: everything the boundary block adds on
        top of the verbatim document. Bounding it absolutely means R does not
        leave absolute magnitude unguarded, while still not failing this lane
        for a document it cannot shrink.
        """
        self.assertGreater(self.overhead, 0, 'the block must exceed the document it embeds')
        self.assertLessEqual(self.overhead, self.G1_BOUNDARY_OVERHEAD_MAX_CHARS,
                             f'lane-owned boundary overhead {self.overhead} chars')

    def test_g3_hazard_the_unbounded_share_is_the_document_and_is_named(self):
        """Pins WHY the remaining term is left relational, so it cannot drift silently.

        If the document share ever stopped dominating, the residual would no
        longer be attributable to a document this lane cannot shrink, and the
        relational cumulative bound would need re-deriving rather than reusing.
        """
        share = len(self.spec) / self.boundary_block
        self.assertGreaterEqual(share, self.G1_SPEC_SHARE_MIN_RATIO,
                                f'document share of the boundary block is {share:.4f}; '
                                'below this the residual is no longer document drift')
        self.assertGreater(self.boundary_block, self.G1_PER_PROMPT_MAX_CHARS,
                           'the two payload shapes must not converge and make '
                           'the per-prompt ceiling vacuous')


if __name__ == '__main__':
    unittest.main()
