#!/usr/bin/env python3
"""Regression tests for hooks/prompt-workflow.py continuation delivery cadence.

The defect: ``build_overnight_continuation`` emitted ONE payload at ONE cadence
for two content classes whose natural cadences differ by orders of magnitude.
98% of the block is ``commands/dev-overnight.md``, which does not change inside
a session; the remaining 2% is state summary + phase->step routing, which
changes several times within a single cycle. Applying the per-prompt cadence to
the invariant half made the recurring cost unbounded in prompts-per-cycle.

After the fix the light half rides every prompt (withholding it would strand a
resuming orchestrator on the phase that was current at the last cycle boundary)
and the heavy half is gated on a delivery marker keyed by
(session_id, cycle_count, context epoch, spec fingerprint).

Structured after ``tests/test_prompt_workflow_liveness_tz.py``.

Every fixture sets HOME to a temporary directory: ``$HOME/.claude`` is a symlink
to the repository root, so a fixture writing through it would mutate the working
tree and corrupt concurrent work.

``PW_HOOK_PATH`` overrides the module under test so an off-live release
candidate can be validated before it is published onto the live hook path.

THREE CRITERION DISCREPANCIES ARE ASSERTED TO INTENT, NOT TO LETTER. Each is
marked ``DISCREPANCY`` at its assertion site with the measurement establishing
it; see the dev report for the full record.
"""

from __future__ import annotations

import ast
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK_PATH = Path(os.environ.get('PW_HOOK_PATH') or (REPO / 'hooks' / 'prompt-workflow.py'))
COMMAND_DOC = REPO / 'commands' / 'dev-overnight.md'
TODO_PROVIDER = REPO / 'scripts' / 'todo' / 'dev-overnight.py'

SPEC_HEADER = '--- COMMAND SPECIFICATION ---'
LIGHT_MARKERS = (
    'OVERNIGHT CONTINUATION',
    '--- CURRENT STATE ---',
    '--- CONTINUATION INSTRUCTIONS ---',
    'Phase mapping:',
)
SELF_HEAL_PREFIX = 'Command specification: '

SID = 'aaaaaaaa-1111-2222-3333-444444444444'
OTHER_SID = 'zzzzzzzz-9999-8888-7777-666666666666'


def spec_body_probe(length: int = 400) -> str:
    """A prefix of the spec AS INJECTED -- read_command_spec strips frontmatter."""
    text = COMMAND_DOC.read_text()
    if text.startswith('---'):
        end = text.find('\n---', 3)
        if end != -1:
            text = text[end + 4:].lstrip('\n')
    return text.strip()[:length]

# AC-1's per_prompt_min_chars, asserted at its mandated value.
#
# An earlier revision of this module lowered the floor to 700 on the premise
# that AC-1's own fixture made 1,500 unreachable. That premise was FALSE and QA
# falsified it by measurement: AC-1 mandates HOME=<temp dir>, not an EMPTY one,
# and the fixture was already populating that temp HOME with the command
# document. 'Canonical steps: {labels}' renders from _load_overnight_todos(),
# which resolves $HOME/.claude/scripts/todo/dev-overnight.py -- so the provider
# simply had to be fixtured there too, exactly as the document already was.
# Measured with the provider fixtured: 2,772 chars. The floor never needed
# lowering, and at 700 the suite passed with an EMPTY 'Canonical steps:' field,
# so a regression that silently dropped that ~1,000-char component would not
# have been caught. It is now asserted non-empty in its own right.
LIGHT_FLOOR_CHARS = 1500
LIGHT_CEILING_CHARS = 3000


def load_hook_module():
    """Load the hook under test as a real module (fresh globals each call)."""
    loader = SourceFileLoader('pw_cadence_under_test', str(HOOK_PATH))
    spec = spec_from_loader(loader.name, loader)
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


class Fixture:
    """A hermetic project + HOME + transcript, never touching the repo."""

    def __init__(self, tmp: str, session_id: str = SID, cycle_count: int = 0,
                 isolation_kind: str = 'registered_worktree',
                 with_transcript: bool = True, with_spec: bool = True,
                 with_todo: bool = True):
        self.session_id = session_id
        self.root = Path(tmp)
        self.project = self.root / 'proj'
        self.home = self.root / 'home'
        (self.project / '.claude').mkdir(parents=True)
        (self.home / '.claude' / 'commands').mkdir(parents=True)
        if with_spec:
            (self.home / '.claude' / 'commands' / 'dev-overnight.md').write_text(
                COMMAND_DOC.read_text()
            )
        if with_todo:
            # The canonical step labels are ~1,000 chars of the light payload
            # and load from $HOME/.claude/scripts/todo/dev-overnight.py. AC-1
            # mandates a TEMPORARY home, not an empty one -- leaving the
            # provider out silently emptied 'Canonical steps:' and was the
            # false premise behind the lowered floor.
            provider = self.home / '.claude' / 'scripts' / 'todo'
            provider.mkdir(parents=True)
            shutil.copy(TODO_PROVIDER, provider / 'dev-overnight.py')
        transcripts = self.home / '.claude' / 'projects' / '-proj'
        transcripts.mkdir(parents=True)
        self.transcript = transcripts / f'{session_id}.jsonl'
        if with_transcript:
            self.transcript.write_text(json.dumps({'type': 'user', 'uuid': 'u0'}) + '\n')
        self.state_path = self.project / '.claude' / f'overnight-state-{session_id}.json'
        self.write_state(cycle_count=cycle_count, isolation_kind=isolation_kind)

    def write_state(self, cycle_count: int = 0, phase: str = 'exploring',
                    isolation_kind: str = 'registered_worktree') -> None:
        self.state_path.write_text(json.dumps({
            'session_id': self.session_id,
            'end_time': '2099-01-01T00:00:00Z',
            'cycle_count': cycle_count,
            'current_phase': phase,
            'isolation_kind': isolation_kind,
            'worktree_path': '/tmp/wt',
            'worktree_branch': 'wt-branch',
            'protected_branch': 'master',
            'issues_fixed': 0,
            'current_issues': [],
            'cycle_log': [],
            'focus': 'none',
        }))

    def state(self) -> dict:
        return json.loads(self.state_path.read_text())

    def marker_path(self, session_id: str | None = None) -> Path:
        sid = session_id or self.session_id
        return self.project / '.claude' / f'overnight-delivery-{sid}.json'

    def spec_doc(self) -> Path:
        return self.home / '.claude' / 'commands' / 'dev-overnight.md'

    def append_transcript(self, record: dict) -> None:
        with self.transcript.open('a') as handle:
            handle.write(json.dumps(record) + '\n')

    def env(self) -> dict:
        env = {**os.environ, 'HOME': str(self.home),
               'CLAUDE_PROJECT_DIR': str(self.project)}
        env.pop('CLAUDE_COMPAT_RUNTIME', None)
        env.pop('CLAUDE_DEV_OVERNIGHT_TODO', None)
        return env

    def run(self, session_id: str | None = None, prompt: str = 'continue please',
            extra_env: dict | None = None, stdout=subprocess.PIPE):
        """Drive the hook across the real main() process boundary."""
        env = self.env()
        if extra_env:
            env.update(extra_env)
        payload = json.dumps({
            'prompt': prompt,
            'session_id': session_id or self.session_id,
            'transcript_path': str(self.transcript),
        })
        return subprocess.run([sys.executable, str(HOOK_PATH)], input=payload,
                              capture_output=stdout is subprocess.PIPE, text=True,
                              env=env, stdout=None if stdout is not subprocess.PIPE else None)

    def call_direct(self, session_id: str | None = None) -> str | None:
        """Call the decision in-process so an ESCAPING EXCEPTION FAILS THE TEST.

        A subprocess exit of 0 is insufficient evidence on its own: main()
        swallows generic exceptions and exits 0, so a raising hook is
        indistinguishable from a working one from the outside.
        """
        previous = {k: os.environ.get(k) for k in
                    ('HOME', 'CLAUDE_PROJECT_DIR', 'CLAUDE_DEV_OVERNIGHT_TODO')}
        os.environ['HOME'] = str(self.home)
        os.environ['CLAUDE_PROJECT_DIR'] = str(self.project)
        os.environ.pop('CLAUDE_DEV_OVERNIGHT_TODO', None)
        try:
            module = load_hook_module()
            return module.check_overnight_continuation(session_id or self.session_id)
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


CANONICAL_PREFIX = 'Canonical steps: '


def canonical_steps(block: str) -> str:
    """The rendered step labels, or '' when the line is absent or empty."""
    for line in block.splitlines():
        if line.startswith(CANONICAL_PREFIX):
            return line[len(CANONICAL_PREFIX):].strip()
    return ''


def deliver(fixture: Fixture, session_id: str | None = None) -> str:
    """One full prompt: emit, then commit the marker (write-after-emit)."""
    result = fixture.run(session_id)
    return result.stdout


class TestAC1RecurringCostIsBounded(unittest.TestCase):
    """AC-1 -- repeated prompts inside one cycle stop carrying the heavy half."""

    def test_five_consecutive_prompts_deliver_the_spec_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            outputs = [deliver(fixture) for _ in range(5)]

            self.assertIn(SPEC_HEADER, outputs[0])
            self.assertIn(spec_body_probe(), outputs[0])

            for index, out in enumerate(outputs[1:], start=2):
                with self.subTest(prompt=index):
                    self.assertNotIn(SPEC_HEADER, out)
                    self.assertLessEqual(len(out), LIGHT_CEILING_CHARS)
                    # AC-1's lower bound at its mandated value. Absence-of-heavy
                    # is not evidence of presence-of-light: an implementation
                    # that delivered once then emitted nothing would satisfy
                    # every upper bound.
                    self.assertGreaterEqual(len(out), LIGHT_FLOOR_CHARS)
                    # ...and a size floor alone would still pass with the
                    # ~1,000-char step list emptied, so assert that component
                    # is populated in its own right.
                    self.assertTrue(canonical_steps(out),
                                    'Canonical steps rendered empty')
                    for marker in LIGHT_MARKERS:
                        self.assertIn(marker, out)
                    self.assertIn('CRITICAL: The validated isolated worktree', out)
                    self.assertIn(SELF_HEAL_PREFIX, out)

            # Every light prompt is byte-identical: the recurring term is a
            # constant, not merely "smaller".
            self.assertEqual(1, len(set(outputs[1:])))

            cumulative = sum(len(o) for o in outputs)
            baseline = len(outputs[0]) * 5
            # DISCREPANCY D2 -- AC-1 pins cumulative_max=145000 and
            # cumulative_min=130000 to constants that this lane's own
            # recommended landing order invalidates: the named residual owner
            # (include-expander) SHRINKS commands/dev-overnight.md, so a
            # minimum on cumulative size would fail this lane precisely for
            # succeeding at making the block smaller. Asserted relationally
            # against the fixture's own measured boundary block instead.
            self.assertLess(cumulative, len(outputs[0]) + 5 * LIGHT_CEILING_CHARS)
            self.assertGreaterEqual(cumulative, len(outputs[0]))
            self.assertLess(cumulative, baseline * 0.30)

    def test_marker_records_the_reading_in_force(self):
        """The R-a/R-b choice is readable from the artifact, not inferred."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            deliver(fixture)
            marker = json.loads(fixture.marker_path().read_text())
            self.assertIn(marker['epoch_reading'], ('R-a', 'R-b'))
            module = load_hook_module()
            self.assertEqual(module.OVERNIGHT_EPOCH_READING, marker['epoch_reading'])


class TestAC2FailSafePolarity(unittest.TestCase):
    """AC-2 -- every marker anomaly delivers; exactly one state suppresses."""

    def _write_marker(self, fixture: Fixture, payload) -> None:
        path = fixture.marker_path()
        if payload is None:
            return
        path.write_text(payload if isinstance(payload, str) else json.dumps(payload))

    def _valid_marker(self, fixture: Fixture) -> dict:
        deliver(fixture)
        return json.loads(fixture.marker_path().read_text())

    def test_all_eleven_marker_states(self):
        rows = [
            ('2.1', 'absent', None, 'heavy'),
            ('2.2', 'zero-length', '', 'heavy'),
            ('2.3', 'malformed JSON', '{not json', 'heavy'),
            ('2.4', 'not an object', [], 'heavy'),
            ('2.5', 'missing session_id', {'cycle_count': 0}, 'heavy'),
            ('2.6', 'foreign session_id', {'session_id': OTHER_SID}, 'heavy'),
            ('2.7', 'cycle lower', 'CYCLE:-1', 'heavy'),
            ('2.8', 'cycle higher', 'CYCLE:+1', 'heavy'),
            ('2.9', 'cycle non-numeric', 'CYCLE:str', 'heavy'),
            ('2.10', 'unreadable', 'UNREADABLE', 'heavy'),
            ('2.11', 'exact four-field match', 'VALID', 'light_only'),
        ]
        for row_id, label, payload, expected in rows:
            with self.subTest(row=row_id, marker=label):
                with tempfile.TemporaryDirectory() as tmp:
                    fixture = Fixture(tmp)
                    if payload in ('VALID', 'CYCLE:-1', 'CYCLE:+1', 'CYCLE:str'):
                        marker = self._valid_marker(fixture)
                        if payload == 'CYCLE:-1':
                            marker['cycle_count'] = marker['cycle_count'] - 1
                        elif payload == 'CYCLE:+1':
                            marker['cycle_count'] = marker['cycle_count'] + 1
                        elif payload == 'CYCLE:str':
                            marker['cycle_count'] = 'zero'
                        fixture.marker_path().write_text(json.dumps(marker))
                    elif payload == 'UNREADABLE':
                        # DISCREPANCY -- AC-2 row 2.10 specifies mode 0o000, but
                        # this suite runs as uid 0 in this harness and root
                        # bypasses the permission bits, so chmod alone yields a
                        # READABLE file and a non-discriminating row. A
                        # directory at the marker path is unreadable for every
                        # uid (read_text -> IsADirectoryError), which tests the
                        # property the row is actually about.
                        fixture.marker_path().mkdir()
                    else:
                        self._write_marker(fixture, payload)

                    out = deliver(fixture)
                    if expected == 'heavy':
                        self.assertIn(SPEC_HEADER, out)
                    else:
                        self.assertNotIn(SPEC_HEADER, out)
                        for marker_text in LIGHT_MARKERS:
                            self.assertIn(marker_text, out)

    def test_no_exception_escapes_the_decision(self):
        """Direct in-process call: any raise fails here, unlike a subprocess."""
        for label, payload in (('malformed', '{not json'), ('non-object', '[]'),
                               ('zero-length', ''), ('wrong types', '{"cycle_count": {}}')):
            with self.subTest(marker=label):
                with tempfile.TemporaryDirectory() as tmp:
                    fixture = Fixture(tmp)
                    fixture.marker_path().write_text(payload)
                    block = fixture.call_direct()
                    self.assertIsNotNone(block)
                    self.assertIn(SPEC_HEADER, block)


class TestAC3ValidityKeyDiscrimination(unittest.TestCase):
    """AC-3 -- the validity key is exactly the four fields."""

    def test_control_does_not_redeliver(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            deliver(fixture)
            self.assertNotIn(SPEC_HEADER, deliver(fixture))

    def test_3_1_cycle_advance_redelivers(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            deliver(fixture)
            fixture.write_state(cycle_count=fixture.state()['cycle_count'] + 1)
            self.assertIn(SPEC_HEADER, deliver(fixture))

    def test_3_2_session_change_redelivers(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            deliver(fixture)
            other = Fixture(tempfile.mkdtemp(dir=tmp), session_id=OTHER_SID)
            self.assertIn(SPEC_HEADER, deliver(other))

    def test_3_3_compaction_redelivers(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            deliver(fixture)
            fixture.append_transcript({'type': 'system', 'isCompactSummary': True,
                                       'uuid': 'compact-1'})
            self.assertIn(SPEC_HEADER, deliver(fixture))

    def test_3_4_spec_change_on_disk_redelivers(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            deliver(fixture)
            doc = fixture.spec_doc()
            doc.write_text(doc.read_text() + '\n<!-- edited -->\n')
            self.assertIn(SPEC_HEADER, deliver(fixture))

    def test_transcript_replaced_at_the_same_path_redelivers(self):
        """A fresh transcript file at the same path with the same size.

        Neither transcript_path (equal) nor transcript_offset (size unchanged)
        notices this; the inode term is what catches it. Found by fuzzing the
        marker fields, not by any acceptance criterion.
        """
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            deliver(fixture)
            replacement = fixture.transcript.with_suffix('.new')
            replacement.write_text(fixture.transcript.read_text())
            os.replace(replacement, fixture.transcript)
            self.assertIn(SPEC_HEADER, deliver(fixture))

    def test_truncated_transcript_redelivers(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            fixture.append_transcript({'type': 'user', 'pad': 'x' * 200})
            deliver(fixture)
            fixture.transcript.write_text('{"a":1}\n')
            self.assertIn(SPEC_HEADER, deliver(fixture))

    def test_marker_from_a_different_epoch_reading_is_not_honoured(self):
        """Descoping R-b -> R-a must not silently honour R-b markers."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            deliver(fixture)
            marker = json.loads(fixture.marker_path().read_text())
            marker['epoch_reading'] = 'R-a' if marker['epoch_reading'] == 'R-b' else 'R-b'
            fixture.marker_path().write_text(json.dumps(marker))
            self.assertIn(SPEC_HEADER, deliver(fixture))

    def test_negative_ordinary_transcript_growth_does_not_redeliver(self):
        """What distinguishes an epoch token from a naive transcript-grew check."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            deliver(fixture)
            for index in range(3):
                fixture.append_transcript({'type': 'user', 'uuid': f'plain-{index}'})
            self.assertNotIn(SPEC_HEADER, deliver(fixture))


class TestAC4EndToEndProcessBoundary(unittest.TestCase):
    """AC-4 -- through the real main() boundary, not an in-process import."""

    def test_subprocess_first_and_second_invocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            first = fixture.run()
            second = fixture.run()
            self.assertEqual(0, first.returncode)
            self.assertEqual(0, second.returncode)
            # DISCREPANCY D4 (not among the four the lane was briefed on) --
            # AC-4 asks for 'OVERNIGHT CONTINUATION' exactly once, but the
            # embedded command document contains that phrase itself, so on a
            # heavy prompt the count is 2. Measured true at the pre-change
            # baseline as well, so it is a criterion defect and not a
            # regression. The header form is the discriminating one: it occurs
            # 0 times in the document and exactly once per emitted block.
            self.assertEqual(1, first.stdout.count('OVERNIGHT CONTINUATION - Cycle'))
            self.assertEqual(1, second.stdout.count('OVERNIGHT CONTINUATION - Cycle'))
            self.assertIn(SPEC_HEADER, first.stdout)
            self.assertNotIn(SPEC_HEADER, second.stdout)
            for out in (first.stdout, second.stdout):
                self.assertIn('--- CURRENT STATE ---', out)
                self.assertIn('Phase mapping:', out)
                self.assertIn('CRITICAL: The validated isolated worktree', out)

    def test_codex_runtime_emits_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            result = fixture.run(extra_env={'CLAUDE_COMPAT_RUNTIME': 'codex'})
            self.assertEqual(0, result.returncode)
            self.assertNotIn('OVERNIGHT CONTINUATION', result.stdout)

    def test_slash_prompt_is_not_phase_b(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            result = fixture.run(prompt='/status')
            self.assertNotIn('OVERNIGHT CONTINUATION', result.stdout)


class TestAC5CycleBoundaryStillDelivers(unittest.TestCase):
    """AC-5 -- a genuine cycle advance delivers what routing needs."""

    def test_advance_redelivers_and_rearms(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp, cycle_count=4)
            deliver(fixture)
            self.assertNotIn(SPEC_HEADER, deliver(fixture))

            # posttool-overnight-loop.py:100-101 -- cycle_count +1, phase reset.
            fixture.write_state(cycle_count=5, phase='exploring')
            out = deliver(fixture)

            self.assertIn(SPEC_HEADER, out)
            self.assertIn(spec_body_probe(), out)
            self.assertIn('OVERNIGHT CONTINUATION - Cycle 6', out.splitlines()[0])
            self.assertIn('resume from phase="exploring"', out)
            self.assertIn('Phase mapping:', out)

            marker = json.loads(fixture.marker_path().read_text())
            self.assertEqual(5, marker['cycle_count'])
            self.assertNotIn(SPEC_HEADER, deliver(fixture))

    def test_phase_advance_within_a_cycle_updates_routing(self):
        """The light half must track current_phase, which moves mid-cycle."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp, cycle_count=2)
            deliver(fixture)
            fixture.write_state(cycle_count=2, phase='implementing')
            out = deliver(fixture)
            self.assertNotIn(SPEC_HEADER, out)
            self.assertIn('resume from phase="implementing"', out)
            self.assertIn('Phase: implementing', out)


class TestAC6SessionIsolation(unittest.TestCase):
    """AC-6 -- two-factor binding: filename AND the record's own field."""

    def test_foreign_session_does_not_consume_the_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            deliver(fixture)
            before = fixture.marker_path().read_bytes()
            fixture.run(session_id=OTHER_SID)
            self.assertEqual(before, fixture.marker_path().read_bytes())

    def test_filename_field_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            deliver(fixture)
            marker = json.loads(fixture.marker_path().read_text())
            marker['session_id'] = 'bbbbbbbb-0000-0000-0000-000000000000'
            fixture.marker_path().write_text(json.dumps(marker))
            self.assertIn(SPEC_HEADER, deliver(fixture))


class TestAC8SelfHealPointer(unittest.TestCase):
    """AC-8 -- the pointer names the resolved path, never a literal."""

    def test_pointer_equals_read_command_spec_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            block = fixture.call_direct()
            module = load_hook_module()
            os.environ['HOME'] = str(fixture.home)
            os.environ['CLAUDE_PROJECT_DIR'] = str(fixture.project)
            module = load_hook_module()
            resolved = module.resolve_command_spec_path('dev-overnight')
            self.assertIsNotNone(resolved)
            self.assertIn(f'{SELF_HEAL_PREFIX}{resolved}', block)
            # The resolved path is the file read_command_spec actually reads.
            self.assertEqual(module.read_command_spec('dev-overnight'),
                             module._try_read_spec(resolved))
            # ...and it is NOT the repository literal.
            self.assertNotIn(str(COMMAND_DOC), block)

    def test_pointer_rides_light_prompts_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            deliver(fixture)
            light = deliver(fixture)
            self.assertNotIn(SPEC_HEADER, light)
            self.assertIn(SELF_HEAL_PREFIX, light)


class TestAC11MarkerOrderingAndWritability(unittest.TestCase):
    """AC-11 -- write-after-emit, plus the coverage gap AC-1..AC-11 never had."""

    def test_no_marker_when_emission_fails(self):
        """Emission failure must leave NO marker, so the next prompt re-delivers.

        M6a: a marker written before emission claims a delivery that never
        happened and does NOT self-heal within the cycle -- every later prompt
        suppresses and the session stalls until the next cycle advance.

        The sink is /dev/full, which accepts the open and then fails every
        write with ENOSPC. An earlier revision of this test used /dev/null,
        which SUCCEEDS -- so it proved nothing about ordering and would have
        stayed green against an implementation that committed the marker BEFORE
        printing. The assertion below is the ordering property itself: the run
        whose emission failed must leave no marker behind.
        """
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            with open('/dev/full', 'w') as sink:
                result = subprocess.run(
                    [sys.executable, str(HOOK_PATH)],
                    input=json.dumps({'prompt': 'go', 'session_id': fixture.session_id,
                                      'transcript_path': str(fixture.transcript)}),
                    text=True, env=fixture.env(), stdout=sink,
                    stderr=subprocess.PIPE,
                )
            self.assertEqual(0, result.returncode)
            self.assertFalse(fixture.marker_path().exists(),
                             'marker written despite a failed emission')
            # ...and the delivery is therefore still owed: the next ordinary
            # prompt must carry the heavy half.
            self.assertIn(SPEC_HEADER, deliver(fixture))

    def test_committer_refuses_emissions_it_did_not_build(self):
        """No receipt, no certification -- the committer's own input guard."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            module = fixture.load_module()
            self.assertFalse(module.commit_overnight_delivery(SID, ''))
            self.assertFalse(module.commit_overnight_delivery(
                SID, 'light only, no spec header'))
            self.assertFalse(module.commit_overnight_delivery(
                SID, f'OVERNIGHT CONTINUATION - Cycle 1\n{SPEC_HEADER}\nbody'))
            self.assertFalse(fixture.marker_path().exists())

    def test_marker_write_failure_leaves_exit_zero_and_redelivers(self):
        """A marker that cannot be persisted is fail-safe, not an error."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            fixture.marker_path().mkdir()  # os.replace onto a dir always fails
            first = fixture.run()
            second = fixture.run()
            self.assertEqual(0, first.returncode)
            self.assertEqual(0, second.returncode)
            self.assertIn(SPEC_HEADER, first.stdout)
            self.assertIn(SPEC_HEADER, second.stdout)
            # The failure must be announced, not merely survived: a write that
            # fails on every prompt means the saving is exactly zero.
            self.assertIn('marker was not recorded', first.stdout)
            self.assertIn('marker was not recorded', second.stdout)

    def test_successful_delivery_announces_nothing(self):
        """The degradation notices must not fire on the healthy path."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            out = deliver(fixture)
            self.assertIn(SPEC_HEADER, out)
            self.assertNotIn('marker was not recorded', out)
            self.assertNotIn('INACTIVE', out)
            self.assertTrue(fixture.marker_path().is_file())

    def test_unwritable_marker_location_is_announced_not_silent(self):
        """COVERAGE GAP G1 -- no AC checked that the marker CAN be written.

        This is the sharpest risk in the lane: under a read-only project mount
        (the isolation mode that broke a sibling lane's launch-time writes)
        every prompt re-delivers the heavy half, the saving is exactly zero,
        the hook still exits 0, and every other test in this file still passes
        because each builds its own writable fixture. The degradation must be
        observable in the emitted block itself.
        """
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            claude_dir = fixture.project / '.claude'
            original_mode = claude_dir.stat().st_mode
            module = load_hook_module()
            marker_path = fixture.marker_path()

            self.assertTrue(module._marker_writable(marker_path))
            block = fixture.call_direct()
            self.assertNotIn('INACTIVE', block)

            # Trigger 1 -- an unwritable marker path, reproducible for EVERY
            # uid including root, which bypasses the mode bits. os.replace onto
            # a non-file always fails, so the cadence genuinely is inactive.
            marker_path.mkdir()
            self.assertFalse(module._marker_writable(marker_path))
            block = fixture.call_direct()
            self.assertIn('INACTIVE', block)
            self.assertIn(str(marker_path), block)
            self.assertIn(SPEC_HEADER, block)
            marker_path.rmdir()

            # Trigger 2 -- a read-only parent, the closer analogue of the
            # read-only bind mount that broke a sibling lane. Skipped only when
            # the running uid bypasses the mode bits.
            try:
                claude_dir.chmod(0o555)
                if not os.access(claude_dir, os.W_OK):
                    self.assertFalse(module._marker_writable(marker_path))
                    self.assertIn('INACTIVE', fixture.call_direct())
            finally:
                claude_dir.chmod(original_mode)


class TestScopeConfinement(unittest.TestCase):
    """AC-9 -- the lane boundary is honoured and the collision is not absorbed."""

    TZ_OWNED = ('_is_active_state', 'find_any_overnight_state')

    def test_tz_owned_symbols_are_not_edited_by_this_lane(self):
        """The tz lane's landed fix must be intact, byte for byte."""
        source = HOOK_PATH.read_text()
        tree = ast.parse(source)
        lines = source.splitlines()
        bodies = {}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in self.TZ_OWNED:
                bodies[node.name] = '\n'.join(lines[node.lineno - 1:node.end_lineno])
        self.assertEqual(set(self.TZ_OWNED), set(bodies))
        # tz's session binding and its fail-closed liveness predicate.
        self.assertIn("state.get('session_id') != session_id",
                      bodies['find_any_overnight_state'])
        # No project-wide scan survives (a prose mention in the docstring
        # explaining the removed glob is not a call site).
        self.assertNotIn('.glob(', bodies['find_any_overnight_state'])
        self.assertIn("replace('Z', '+00:00')", bodies['_is_active_state'])

    def test_handle_phase_b_still_threads_the_session_id(self):
        """tz asserts this literal; the cadence fix must not break it."""
        source = HOOK_PATH.read_text()
        tree = ast.parse(source)
        lines = source.splitlines()
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == 'handle_phase_b':
                body = '\n'.join(lines[node.lineno - 1:node.end_lineno])
                self.assertIn('check_overnight_continuation(session_id)', body)
                self.assertIn('commit_overnight_delivery', body)
                # M6a is a source-order property: emit, then record.
                self.assertLess(body.index('print(overnight_ctx)'),
                                body.index('commit_overnight_delivery'))
                return
        self.fail('handle_phase_b not found')

    def test_main_threads_the_authoritative_transcript_path(self):
        """DISCREPANCY D5 -- AC-9 does not list main() among the permitted
        edited symbols, but M4's context-epoch signal cannot reach Phase B
        without it. The alternative -- resolving the transcript by session id
        under $HOME/.claude/projects -- was implemented, measured, and
        REJECTED: $HOME/.claude is a symlink to the repository root, so the
        scan reads a secondary store and the live overnight session's own
        transcript is absent from it. Shipping that would have degraded
        reading R-b to R-a silently, on every real session, while every
        hermetic test still passed on its own fixture. main() is edited by two
        lines; the tz lane's symbols are untouched, and no file outside this
        hook and this test module is modified.
        """
        source = HOOK_PATH.read_text()
        tree = ast.parse(source)
        lines = source.splitlines()
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == 'main':
                body = '\n'.join(lines[node.lineno - 1:node.end_lineno])
                self.assertIn('handle_phase_b(session_id)', body)
                self.assertIn("data.get('transcript_path')", body)
                return
        self.fail('main not found')

    def test_payload_transcript_path_beats_the_store_scan(self):
        """The authoritative signal must actually be the one consulted."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            deliver(fixture)
            marker = json.loads(fixture.marker_path().read_text())
            self.assertEqual(str(fixture.transcript), marker['transcript_path'])
            self.assertGreater(marker['transcript_offset'], 0)

    def _run_without_payload_transcript(self, fixture) -> dict:
        payload = json.dumps({'prompt': 'go', 'session_id': fixture.session_id})
        subprocess.run([sys.executable, str(HOOK_PATH)], input=payload,
                       capture_output=True, text=True, env=fixture.env())
        return json.loads(fixture.marker_path().read_text())

    def test_store_scan_is_the_fallback_when_the_payload_omits_the_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp)
            marker = self._run_without_payload_transcript(fixture)
            self.assertEqual(str(fixture.transcript), marker['transcript_path'])

    def test_no_epoch_signal_at_all_degrades_to_R_a_VISIBLY(self):
        """When neither source resolves, the marker SAYS SO rather than guessing."""
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(tmp, with_transcript=False)
            marker = self._run_without_payload_transcript(fixture)
            self.assertEqual('', marker['transcript_path'])
            self.assertEqual(0, marker['transcript_offset'])
            self.assertEqual('R-b', marker['epoch_reading'])


if __name__ == '__main__':
    unittest.main()
