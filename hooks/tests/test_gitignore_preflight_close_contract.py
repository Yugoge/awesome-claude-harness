#!/usr/bin/env python3
"""Regression coverage for pretool-gitignore-preflight.py — spec-20260904-harness-fixes.md R1.

The gate previously harvested any docs/dev/dev-report-*.json cited anywhere in an
Agent prompt and treated that report's recorded file lists as deliverables of the
dispatch being gated. /close Step 1 hands its auditors a `--changed-files` list
(an audit INPUT) that itself contains lane dev-report paths, so the close of any
fan-out cycle was refused over paths the auditor would only ever READ.

Three obligations are pinned here:
  * E2 — the close contract's own mandated output paths are admitted.
  * E1 — a declared audit input is no longer mistaken for a deliverable.
  * The negative control — an unauthorised work product aimed at an ignored path
    is still refused, with the original message and exit code.

The SECOND narrow step (same spec R1) covers /close Step 2, which hands the QA
gatekeeper the cycle's whole lane matrix as READ material and writes only
`docs/dev/close-report-<P>.md`. E1 does not fire there (no `--changed-files`),
so the gate opened the cited lane reports and refused over 16 distinct paths.
Its obligations are pinned in the E3 section of this file.

The THIRD narrow step (same spec R1) covers the one Step 2 input artifact left
uncovered: the cycle's CANONICAL PARENT dev-report, which close.md:393-395
mandates be handed to the QA gatekeeper. Rendered as its own input-artifact line
it sits in no E3 span, so the gate opened it and refused over the 16 gitignored
paths recorded inside it — a set exactly equal to the canonical's own recorded
file lists filtered to gitignored non-contract paths. Its obligations are pinned
in the E4 section at the bottom of this file.

The FIFTH step (2026-09-17) covers /commit Step 7's changelog-analyst dispatch —
a legitimate read of a task's dev-report to build its own staging classification,
with no lane-matrix span and no close-report deliverable to anchor E3 or E4 on.
Discriminator E5 exempts it only when the prompt cites a live, unexpired
/tmp/claude-commit-grant-*.json whose own task_id (read off disk, never off the
prompt) matches the report being opened — an artifact only /commit's own Step 5
can mint, after a prior CLOSE: YES verdict for that exact task-id. Its
obligations are pinned in the E5 section at the bottom of this file.

Synthetic cases run against a throwaway git repo containing a copy of the gate, so
the gate's repo-root derivation (dirname(dirname(__file__))) lands inside the
fixture. Two cases run against the real repository and the real artifacts of the
live fan-out cycle 20260809-013317 that produced the original refusal.
"""

import contextlib
import datetime
import glob
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import uuid

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO_ROOT, 'hooks', 'pretool-gitignore-preflight.py')
LIVE_TASK_ID = '20260809-013317'


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def run_gate(hook_path, prompt):
    """Invoke the gate with a production-shaped PreToolUse Agent payload."""
    payload = json.dumps({
        'tool_name': 'Agent',
        'tool_input': {'subagent_type': 'style-inspector', 'prompt': prompt},
    })
    proc = subprocess.run(
        [sys.executable, hook_path],
        input=payload, capture_output=True, text=True,
    )
    return proc.returncode, proc.stderr.strip()


@pytest.fixture
def sandbox(tmp_path):
    """Throwaway git repo with the gate installed at <root>/hooks/."""
    root = tmp_path / 'repo'
    (root / 'hooks').mkdir(parents=True)
    (root / 'docs' / 'dev').mkdir(parents=True)
    (root / 'tests' / 'generated').mkdir(parents=True)
    shutil.copy2(HOOK, root / 'hooks' / 'pretool-gitignore-preflight.py')
    # Mirrors the real .gitignore:142 rule under test. Not a modification of the
    # repository's own ignore rules — this is a fixture.
    (root / '.gitignore').write_text('docs/dev/\ntests/generated/\n')
    subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
    return root


def write_report(root, task_id, modified=None, created=None, waiver=None):
    """Write docs/dev/dev-report-<task_id>.json and return its repo-relative path."""
    rel = 'docs/dev/dev-report-%s.json' % task_id
    body = {'dev': {'files_modified': modified or [], 'files_created': created or []}}
    if waiver is not None:
        body['gitignore_waiver'] = waiver
    (root / rel).write_text(json.dumps(body))
    return rel


def sandbox_hook(root):
    return str(root / 'hooks' / 'pretool-gitignore-preflight.py')


def close_step1_prompt(changed_files, task_id):
    """The /close Step 1 inspector dispatch shape (commands/close.md:348-356)."""
    return (
        'You are the style-inspector auditor for /close Step 1.\n'
        '--changed-files %s\n'
        'Write your report to docs/dev/style-inspector-report-%s.json\n'
        % (' '.join(changed_files), task_id)
    )


def load_gate_module():
    spec = importlib.util.spec_from_file_location('gate_under_test', HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# E1 — a declared audit input is not a deliverable
# --------------------------------------------------------------------------

def test_declared_audit_input_is_not_harvested(sandbox):
    """A lane dev-report cited inside --changed-files must not be opened."""
    lane = write_report(sandbox, 'T1-lane', created=['docs/dev/lane-scratch.json'])
    rc, err = run_gate(sandbox_hook(sandbox), close_step1_prompt([lane], 'T1'))
    assert rc == 0, 'declared audit input still refused: %s' % err
    assert err == ''


def test_audit_span_stops_before_the_deliverable_declaration():
    """The span must not swallow the 'Write your report to <path>' line."""
    gate = load_gate_module()
    prompt = close_step1_prompt(['CLAUDE.md', 'docs/dev/dev-report-T1-lane.json'], 'T1')
    spans = gate.declared_audit_input_spans(prompt)
    assert len(spans) == 1
    deliverable = prompt.index('docs/dev/style-inspector-report-T1.json')
    assert not gate._in_any_span(deliverable, spans), \
        'deliverable declaration was absorbed into the audit-input span'
    audit_input = prompt.index('docs/dev/dev-report-T1-lane.json')
    assert gate._in_any_span(audit_input, spans)


def test_live_instance_close_step1_now_admitted():
    """The original refusal, same live task-id, reproduced against the real repo."""
    canonical = os.path.join(REPO_ROOT, 'docs/dev/dev-report-%s.json' % LIVE_TASK_ID)
    if not os.path.isfile(canonical):
        pytest.skip('live artifacts for %s not present in this tree' % LIVE_TASK_ID)
    with open(canonical) as fh:
        changed = json.load(fh)['dev']['files_modified']
    assert any('dev-report-' in p for p in changed), \
        'fixture precondition lost: cycle-diff no longer contains a lane dev-report'
    rc, err = run_gate(HOOK, close_step1_prompt(changed, LIVE_TASK_ID))
    assert rc == 0, 'live fan-out close Step 1 still refused: %s' % err


# --------------------------------------------------------------------------
# E2 — the close contract's own mandated paths are admitted
# --------------------------------------------------------------------------

@pytest.mark.parametrize('name', [
    'style-inspector-report-T1.json',
    'cleanliness-inspector-report-T1.json',
    'prompt-inspector-report-T1.json',
    'close-report-T1.md',
])
def test_contract_mandated_deliverables_admitted(sandbox, name):
    rel = write_report(sandbox, 'T1', created=['docs/dev/%s' % name])
    prompt = 'Dev report file: %s\n' % rel
    rc, err = run_gate(sandbox_hook(sandbox), prompt)
    assert rc == 0, 'contract path %s still refused: %s' % (name, err)


def test_lane_report_may_carry_parent_close_artifacts(sandbox):
    """Close artifacts are written under the parent TASK_ID; lanes may record them."""
    rel = write_report(sandbox, 'T1-lane', created=['docs/dev/close-report-T1.md'])
    rc, err = run_gate(sandbox_hook(sandbox), 'Dev report file: %s\n' % rel)
    assert rc == 0, err


# --------------------------------------------------------------------------
# Negative controls — the protection must survive intact
# --------------------------------------------------------------------------

def test_negative_control_unauthorised_work_product_still_refused(sandbox):
    """A caller-chosen work product aimed at an ignored path is still blocked."""
    rel = write_report(sandbox, 'T1', created=['docs/dev/my-analysis.json'])
    rc, err = run_gate(sandbox_hook(sandbox), 'Dev report file: %s\n' % rel)
    assert rc == 2
    assert err == 'BLOCKED: gitignored deliverables detected: docs/dev/my-analysis.json'


def test_negative_control_generated_tests_still_refused(sandbox):
    rel = write_report(sandbox, 'T1', created=['tests/generated/T1/test_ac_1.py'])
    rc, err = run_gate(sandbox_hook(sandbox), 'Dev report file: %s\n' % rel)
    assert rc == 2
    assert 'tests/generated/T1/test_ac_1.py' in err


def test_contract_shaped_name_with_foreign_task_id_still_refused(sandbox):
    """E2 is cross-bound to the harvesting report's task-id, not to the name."""
    rel = write_report(sandbox, 'T1', created=['docs/dev/close-report-SOMEONE-ELSE.md'])
    rc, err = run_gate(sandbox_hook(sandbox), 'Dev report file: %s\n' % rel)
    assert rc == 2
    assert 'docs/dev/close-report-SOMEONE-ELSE.md' in err


def test_contract_shaped_name_outside_mandated_dir_still_refused(sandbox):
    """The mandated directory is part of the shape; elsewhere it is a work product."""
    rel = write_report(sandbox, 'T1', created=['tests/generated/close-report-T1.md'])
    rc, err = run_gate(sandbox_hook(sandbox), 'Dev report file: %s\n' % rel)
    assert rc == 2
    assert 'tests/generated/close-report-T1.md' in err


def test_audit_span_cannot_launder_a_real_deliverable(sandbox):
    """E1 is positional: citing a report in BOTH positions still gets it checked."""
    rel = write_report(sandbox, 'T1', created=['docs/dev/my-analysis.json'])
    prompt = close_step1_prompt([rel], 'T1') + '\nDev report file: %s\n' % rel
    rc, err = run_gate(sandbox_hook(sandbox), prompt)
    assert rc == 2, 'audit-input span laundered a deliverable citation'
    assert 'docs/dev/my-analysis.json' in err


def test_live_instance_still_refused_when_not_declared_as_audit_input():
    """The original 5 paths are still refused when the lane report is not a declared input."""
    lane = 'docs/dev/dev-report-%s-inject.json' % LIVE_TASK_ID
    if not os.path.isfile(os.path.join(REPO_ROOT, lane)):
        pytest.skip('live artifacts for %s not present in this tree' % LIVE_TASK_ID)
    rc, err = run_gate(HOOK, 'Dev report file: %s\n' % lane)
    assert rc == 2, 'protection lost for a non-declared dev-report citation'
    assert err.startswith('BLOCKED: gitignored deliverables detected: ')
    assert 'docs/codex/%s-inject/dev-iter2.txt' % LIVE_TASK_ID in err


# --------------------------------------------------------------------------
# Untouched dispatch shapes
# --------------------------------------------------------------------------

def test_dev_qa_dispatch_shape_unchanged(sandbox):
    """The /dev QA dispatch carries no --changed-files; behaviour must be identical."""
    rel = write_report(sandbox, 'T1', modified=['docs/dev/leaked.json'], created=[])
    prompt = (
        'Verify the implementation against the success criteria.\n'
        'Dev report file: %s\n'
        'Context file: docs/dev/context-T1.json\n' % rel
    )
    rc, err = run_gate(sandbox_hook(sandbox), prompt)
    assert rc == 2
    assert err == 'BLOCKED: gitignored deliverables detected: docs/dev/leaked.json'


def test_clean_report_passes(sandbox):
    rel = write_report(sandbox, 'T1', modified=['hooks/merge.sh'], created=['scripts/x.sh'])
    assert run_gate(sandbox_hook(sandbox), 'Dev report file: %s\n' % rel)[0] == 0


def test_waiver_still_honoured(sandbox):
    rel = write_report(sandbox, 'T1', created=['docs/dev/my-analysis.json'],
                       waiver='approved by user')
    assert run_gate(sandbox_hook(sandbox), 'Dev report file: %s\n' % rel)[0] == 0


def test_no_dev_report_reference_is_noop(sandbox):
    assert run_gate(sandbox_hook(sandbox), 'Do something unrelated.\n')[0] == 0


def test_missing_report_file_is_noop(sandbox):
    prompt = 'Dev report file: docs/dev/dev-report-does-not-exist.json\n'
    assert run_gate(sandbox_hook(sandbox), prompt)[0] == 0


# ==========================================================================
# E3 — /close Step 2 lane matrix (SECOND narrow step, spec R1)
# ==========================================================================

RESOLVER = os.path.join(REPO_ROOT, 'scripts', 'resolve-dev-artifact-chain.py')


def close_step2_prompt(lanes, close_task_id, canonical=None, report_paths=None):
    """The /close Step 2 QA gatekeeper dispatch shape (commands/close.md:391-397, 518).

    `lanes` is the resolver's lanes[] array. Every projection below is a
    rendering the close contract mandates: the chain object, the lane matrix,
    the report-paths list, the keyed fan-out block, and the sole deliverable.
    """
    if report_paths is None:
        report_paths = [lane['dev_report'] for lane in lanes]
    chain = {
        'schema_version': 1, 'status': 'pass', 'mode': 'fanout',
        'task_id': close_task_id, 'lanes': lanes,
        'canonical_dev_report': canonical or 'docs/dev/dev-report-%s.json' % close_task_id,
        'completion': 'docs/dev/completion-%s.md' % close_task_id,
        'report_paths': report_paths, 'artifact_paths': report_paths,
        'commit_whitelist_artifacts': report_paths,
    }
    fanout = '\n'.join(
        '    task_id=%s ticket=%s context=%s dev_report=%s qa_report=%s'
        % (l['task_id'], l['ticket'], l['context'], l['dev_report'], l['qa_report'])
        for l in lanes)
    return (
        'You are the QA gatekeeper evaluating whether a development can be closed.\n'
        'Input artifacts (read them first):\n'
        '- Artifact-chain result: %s\n'
        '- Mode: fanout\n'
        '- Lane matrix: %s\n'
        '- Report paths: %s\n'
        '- Fan-out inputs:\n%s\n'
        '    canonical_dev_report=%s\n'
        'Treat the lanes[] array as a lane matrix for one parent close decision.\n'
        'Transcript file: write the full debate to docs/dev/close-report-%s.md\n'
        % (json.dumps(chain, sort_keys=True), json.dumps(lanes, sort_keys=True),
           json.dumps(report_paths), fanout, chain['canonical_dev_report'],
           close_task_id)
    )


def blocked_paths(err):
    """Distinct paths named in a refusal.

    The gate lists one entry per CITATION, so a report cited by several
    projections of the same resolver object repeats. That listing behaviour
    predates both narrow steps (the live refusal named 208 occurrences of 16
    distinct paths) and is deliberately left unchanged.
    """
    assert err.startswith('BLOCKED: gitignored deliverables detected: '), err
    return set(err.split('detected: ', 1)[1].split(', '))


def lane_row(task_id, dev_report=None):
    return {
        'task_id': task_id, 'worker': task_id.rsplit('-', 1)[-1],
        'ticket': 'docs/dev/ticket-%s.md' % task_id,
        'context': 'docs/dev/context-%s.json' % task_id,
        'dev_report': dev_report or 'docs/dev/dev-report-%s.json' % task_id,
        'qa_report': 'docs/dev/qa-report-%s.json' % task_id,
    }


# --- the newly admitted shape --------------------------------------------

def test_step2_lane_matrix_is_not_harvested(sandbox):
    """A lane report cited only as Step 2 read material must not be opened."""
    write_report(sandbox, 'T1-adj', created=['docs/dev/lane-scratch.json'])
    write_report(sandbox, 'T1', created=['tests/generated/T1/test_ac.py'])
    prompt = close_step2_prompt([lane_row('T1-adj')], 'T1')
    rc, err = run_gate(sandbox_hook(sandbox), prompt)
    assert rc == 0, 'Step 2 lane matrix still refused: %s' % err
    assert err == ''


def test_step2_admits_every_contract_projection(sandbox):
    """Each mandated projection of the same resolver object must be covered."""
    write_report(sandbox, 'T1-adj', created=['docs/dev/lane-scratch.json'])
    write_report(sandbox, 'T1-doc', created=['docs/codex/T1-doc/dev.txt'])
    write_report(sandbox, 'T1', created=['tests/generated/T1/conftest.py'])
    lanes = [lane_row('T1-adj'), lane_row('T1-doc')]
    rc, err = run_gate(sandbox_hook(sandbox), close_step2_prompt(lanes, 'T1'))
    assert rc == 0, err


def test_step2_admits_the_close_report_deliverable(sandbox):
    """The dispatch's own deliverable, recorded by a lane report, is admitted (E2)."""
    write_report(sandbox, 'T1-adj', created=['docs/dev/close-report-T1.md'])
    rc, err = run_gate(sandbox_hook(sandbox),
                       'Dev report file: docs/dev/dev-report-T1-adj.json\n')
    assert rc == 0, err


def test_live_instance_close_step2_now_admitted():
    """The 16-path refusal, same live fan-out cycle, reproduced against the real repo."""
    if not os.path.isfile(RESOLVER):
        pytest.skip('resolver not present in this tree')
    proc = subprocess.run(
        [sys.executable, RESOLVER, '--task-id', LIVE_TASK_ID,
         '--project-dir', REPO_ROOT],
        capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip('resolver could not resolve %s here' % LIVE_TASK_ID)
    chain = json.loads(proc.stdout)
    if chain.get('mode') != 'fanout' or not chain.get('lanes'):
        pytest.skip('live cycle %s is no longer a fan-out chain' % LIVE_TASK_ID)
    prompt = close_step2_prompt(
        chain['lanes'], LIVE_TASK_ID,
        canonical=chain['canonical_dev_report'],
        report_paths=chain['report_paths'])
    rc, err = run_gate(HOOK, prompt)
    assert rc == 0, 'live fan-out close Step 2 still refused: %s' % err


# --- negative controls: the protection must survive intact ----------------

def test_step2_foreign_task_id_lane_matrix_still_refused(sandbox):
    """A lane matrix whose rows belong to another cycle is NOT read material here."""
    write_report(sandbox, 'OTHER-adj', created=['docs/dev/lane-scratch.json'])
    prompt = close_step2_prompt([lane_row('OTHER-adj')], 'T1')
    rc, err = run_gate(sandbox_hook(sandbox), prompt)
    assert rc == 2, 'foreign-task-id lane matrix was swept in'
    assert blocked_paths(err) == {'docs/dev/lane-scratch.json'}


def test_step2_cannot_launder_a_declared_deliverable(sandbox):
    """E3 is per-occurrence: citing a report in BOTH positions still gets it checked."""
    rel = write_report(sandbox, 'T1-adj', created=['docs/dev/my-analysis.json'])
    prompt = close_step2_prompt([lane_row('T1-adj')], 'T1') + \
        '\nDev report file: %s\n' % rel
    rc, err = run_gate(sandbox_hook(sandbox), prompt)
    assert rc == 2, 'lane-matrix span laundered a deliverable citation'
    assert err == 'BLOCKED: gitignored deliverables detected: docs/dev/my-analysis.json'


def test_prose_mention_beside_a_close_report_is_not_a_lane_matrix(sandbox):
    """A path merely mentioned in prose gets no span, so the gate still refuses."""
    rel = write_report(sandbox, 'T1-adj', created=['docs/dev/my-analysis.json'])
    prompt = ('Please review the findings recorded in %s before you begin.\n'
              'Transcript file: write the full debate to docs/dev/close-report-T1.md\n'
              % rel)
    rc, err = run_gate(sandbox_hook(sandbox), prompt)
    assert rc == 2
    assert err == 'BLOCKED: gitignored deliverables detected: docs/dev/my-analysis.json'


def test_unauthorised_work_product_still_refused_with_close_report_in_scope(sandbox):
    """The /dev deliverable-manifest shape is unchanged even beside a close-report."""
    rel = write_report(sandbox, 'T1', created=['docs/dev/my-analysis.json'])
    prompt = ('Dev report file: %s\n'
              'Prior closure: docs/dev/close-report-T1.md\n' % rel)
    rc, err = run_gate(sandbox_hook(sandbox), prompt)
    assert rc == 2
    assert err == 'BLOCKED: gitignored deliverables detected: docs/dev/my-analysis.json'


def test_two_distinct_close_report_task_ids_disable_e3(sandbox):
    """Ambiguity about which cycle is being closed fails CLOSED."""
    write_report(sandbox, 'T1-adj', created=['docs/dev/lane-scratch.json'])
    prompt = close_step2_prompt([lane_row('T1-adj')], 'T1') + \
        'Also see docs/dev/close-report-T2.md\n'
    rc, err = run_gate(sandbox_hook(sandbox), prompt)
    assert rc == 2
    assert 'docs/dev/lane-scratch.json' in err


def test_no_close_report_declaration_disables_e3(sandbox):
    """Without the deliverable anchor a lane matrix exempts nothing."""
    write_report(sandbox, 'T1-adj', created=['docs/dev/lane-scratch.json'])
    prompt = close_step2_prompt([lane_row('T1-adj')], 'T1').replace(
        'docs/dev/close-report-T1.md', 'the close transcript')
    rc, err = run_gate(sandbox_hook(sandbox), prompt)
    assert rc == 2
    assert 'docs/dev/lane-scratch.json' in err


def test_undecodable_chain_value_fails_closed(sandbox):
    """A schema key followed by non-JSON yields no span, so checking continues."""
    rel = write_report(sandbox, 'T1-adj', created=['docs/dev/lane-scratch.json'])
    prompt = ('- Artifact-chain result: {"report_paths": <redacted %s>}\n'
              'Transcript file: write the full debate to docs/dev/close-report-T1.md\n'
              % rel)
    rc, err = run_gate(sandbox_hook(sandbox), prompt)
    assert rc == 2
    assert 'docs/dev/lane-scratch.json' in err


# --- structural properties of the discriminator ---------------------------

def test_label_run_stops_before_the_deliverable_declaration():
    """The Fan-out inputs run must not swallow the close-report deliverable line."""
    gate = load_gate_module()
    prompt = close_step2_prompt([lane_row('T1-adj')], 'T1')
    spans = gate.lane_matrix_spans(prompt)
    deliverable = prompt.index('docs/dev/close-report-T1.md')
    assert not gate._in_any_span(deliverable, spans), \
        'the deliverable declaration was absorbed into a lane-matrix span'
    assert gate.close_cycle_task_id(prompt, spans) == 'T1'


def test_task_id_family_binding_is_the_resolver_naming_contract():
    gate = load_gate_module()
    assert gate.is_lane_of_cycle('T1', 'T1')
    assert gate.is_lane_of_cycle('T1-adj', 'T1')
    assert not gate.is_lane_of_cycle('T10', 'T1')
    assert not gate.is_lane_of_cycle('OTHER-adj', 'T1')


# --- corpus invariance ----------------------------------------------------

def test_corpus_verdicts_match_the_recorded_file_lists():
    """Replay every real dev-report in the /dev manifest shape.

    E3 must not fire for ANY of them (no close-report deliverable is declared),
    so each verdict must still be exactly 'blocked iff a recorded path is
    gitignored' — the gate's original meaning, measured rather than asserted.
    """
    gate = load_gate_module()
    reports = sorted(glob.glob(os.path.join(REPO_ROOT, 'docs/dev/dev-report-*.json')))
    if len(reports) < 20:
        pytest.skip('no meaningful dev-report corpus in this tree')
    checked = 0
    for abs_path in reports:
        rel = os.path.relpath(abs_path, REPO_ROOT)
        try:
            with open(abs_path) as fh:
                body = json.load(fh)
        except Exception:
            continue
        if not isinstance(body, dict):
            continue
        waiver = body.get('gitignore_waiver')
        dev = body.get('dev') or {}
        paths = [p for key in ('files_modified', 'files_created')
                 for p in (dev.get(key) or [])
                 if isinstance(p, str) and p]
        expect_block = bool(
            not (isinstance(waiver, str) and waiver.strip())
            and any(not gate.is_contract_deliverable(p, gate.source_task_id(rel))
                    and gate.is_gitignored(p, REPO_ROOT) for p in paths))
        rc, _ = run_gate(HOOK, 'Dev report file: %s\n' % rel)
        assert rc == (2 if expect_block else 0), \
            'verdict drifted for %s (expected block=%s)' % (rel, expect_block)
        checked += 1
    assert checked >= 20


# ==========================================================================
# E4 — /close Step 2 canonical parent dev-report (THIRD narrow step, spec R1)
# ==========================================================================
#
# commands/close.md:393-395 mandates that the Step 2 QA gatekeeper be handed
# `canonical_dev_report` as an input artifact. When the orchestrator renders
# that mandate as its own input-artifact line rather than inside a resolver
# JSON value or a CHAIN_LABELS token run, no E3 span covers it, so the gate
# opened the canonical report and refused over the ignored paths inside it.
#
# E4 is deliberately NOT position-anchored (close.md prescribes no label, so a
# label anchor would be caller-chosen text). It is anchored on:
#   (1) E3's deliverable anchor <P>, unchanged;
#   (2) the cited path being exactly the resolver's canonical name for <P>;
#   (3) every otherwise-blocking path having on-disk lane-shard provenance.


def close_step2_canonical_prompt(canonical_rel, close_task_id, lanes_by_pattern=True):
    """Step 2 with the canonical cited as its own input-artifact line.

    `lanes_by_pattern=True` names no lane path at all, which isolates the
    canonical citation as the sole trigger — the two renderings produced
    byte-identical refusals before the fix.
    """
    if lanes_by_pattern:
        lane_block = (
            '- Lane matrix: the lanes of %s; every lane artifact follows the\n'
            '  resolver naming contract docs/dev/<kind>-%s-<worker>.<ext>.\n'
            % (close_task_id, close_task_id))
    else:
        lane_block = '- Lane matrix: []\n'
    return (
        'You are the QA gatekeeper evaluating whether a completed development '
        'can be closed. codex_required: false\n'
        '\n'
        'Input artifacts (read them first):\n'
        '- Mode: fanout\n'
        + lane_block +
        '- Canonical dev report: %s\n'
        '- Completion: docs/dev/completion-%s.md\n'
        '\n'
        'Transcript file: write the full debate to docs/dev/close-report-%s.md\n'
        % (canonical_rel, close_task_id, close_task_id)
    )


# --- the newly admitted shape --------------------------------------------

def test_step2_canonical_parent_report_is_not_harvested(sandbox):
    """The canonical, cited outside every span, is read material — not a manifest."""
    write_report(sandbox, 'T1-init', created=['tests/generated/T1-init/test_ac.py'])
    write_report(sandbox, 'T1-inject', created=['docs/dev/pre-edit-T1-inject/x.py'])
    write_report(sandbox, 'T1',
                 modified=['tests/generated/T1-init/test_ac.py'],
                 created=['docs/dev/pre-edit-T1-inject/x.py'])
    prompt = close_step2_canonical_prompt('docs/dev/dev-report-T1.json', 'T1')
    rc, err = run_gate(sandbox_hook(sandbox), prompt)
    assert rc == 0, 'Step 2 canonical parent report still refused: %s' % err
    assert err == ''


def test_step2_canonical_admitted_with_lane_paths_enumerated_too(sandbox):
    """The same admission holds when the lane matrix is also spelled out (E3 + E4)."""
    write_report(sandbox, 'T1-init', created=['tests/generated/T1-init/test_ac.py'])
    write_report(sandbox, 'T1', created=['tests/generated/T1-init/test_ac.py'])
    prompt = close_step2_prompt([lane_row('T1-init')], 'T1') + \
        '- Canonical dev report: docs/dev/dev-report-T1.json\n'
    rc, err = run_gate(sandbox_hook(sandbox), prompt)
    assert rc == 0, err


def test_live_instance_close_step2_canonical_now_admitted():
    """The original refusing dispatch, re-observed against the real repo.

    Runs BOTH lane-naming renderings. A precondition assertion pins that the
    canonical really does record gitignored paths, so a pass here cannot be
    vacuous, and a control run with the deliverable anchor removed proves the
    trigger is still live rather than the fixture having gone stale.
    """
    canonical = 'docs/dev/dev-report-%s.json' % LIVE_TASK_ID
    if not os.path.isfile(os.path.join(REPO_ROOT, canonical)):
        pytest.skip('live artifacts for %s not present in this tree' % LIVE_TASK_ID)
    gate = load_gate_module()
    with open(os.path.join(REPO_ROOT, canonical)) as fh:
        body = json.load(fh)
    dev = body['dev']
    recorded = (dev.get('files_modified') or []) + (dev.get('files_created') or [])
    ignored = {p for p in recorded if isinstance(p, str) and p
               and not gate.is_contract_deliverable(p, LIVE_TASK_ID)
               and gate.is_gitignored(p, REPO_ROOT)}
    assert ignored, 'fixture precondition lost: canonical records no ignored path'

    # Control: strip the deliverable anchor -> E4 must not fire, and the refusal
    # must name exactly the canonical's own ignored path set.
    control = close_step2_canonical_prompt(canonical, LIVE_TASK_ID).replace(
        'docs/dev/close-report-%s.md' % LIVE_TASK_ID, 'the close transcript')
    rc_c, err_c = run_gate(HOOK, control)
    assert rc_c == 2, 'trigger no longer live; this test would pass vacuously'
    assert blocked_paths(err_c) == ignored

    for by_pattern in (True, False):
        prompt = close_step2_canonical_prompt(canonical, LIVE_TASK_ID,
                                              lanes_by_pattern=by_pattern)
        rc, err = run_gate(HOOK, prompt)
        assert rc == 0, 'live Step 2 canonical still refused (pattern=%s): %s' % (
            by_pattern, err)


# --- negative controls: the protection must survive intact ----------------

def test_e4_canonical_without_shard_provenance_still_refused(sandbox):
    """An unauthorised work product in the canonical has no shard provenance."""
    write_report(sandbox, 'T1-init', created=['tests/generated/T1-init/test_ac.py'])
    write_report(sandbox, 'T1', created=['docs/dev/my-analysis.json'])
    prompt = close_step2_canonical_prompt('docs/dev/dev-report-T1.json', 'T1')
    rc, err = run_gate(sandbox_hook(sandbox), prompt)
    assert rc == 2, 'a work product with no lane-shard provenance was admitted'
    assert err == 'BLOCKED: gitignored deliverables detected: docs/dev/my-analysis.json'


def test_e4_is_all_or_nothing_per_report(sandbox):
    """One uncovered path refuses the whole canonical, message unchanged."""
    write_report(sandbox, 'T1-init', created=['tests/generated/T1-init/test_ac.py'])
    write_report(sandbox, 'T1', modified=['tests/generated/T1-init/test_ac.py'],
                 created=['docs/dev/my-analysis.json'])
    prompt = close_step2_canonical_prompt('docs/dev/dev-report-T1.json', 'T1')
    rc, err = run_gate(sandbox_hook(sandbox), prompt)
    assert rc == 2
    assert blocked_paths(err) == {'tests/generated/T1-init/test_ac.py',
                                  'docs/dev/my-analysis.json'}


def test_e4_foreign_task_id_canonical_still_refused(sandbox):
    """A canonical report of an unrelated task is not swept in by this close."""
    write_report(sandbox, 'OTHER-init', created=['docs/dev/lane-scratch.json'])
    write_report(sandbox, 'OTHER', created=['docs/dev/lane-scratch.json'])
    prompt = close_step2_canonical_prompt('docs/dev/dev-report-OTHER.json', 'T1')
    rc, err = run_gate(sandbox_hook(sandbox), prompt)
    assert rc == 2, 'a foreign canonical report was swept in'
    assert err == 'BLOCKED: gitignored deliverables detected: docs/dev/lane-scratch.json'


def test_e4_lane_shard_cited_outside_a_span_is_not_the_canonical(sandbox):
    """E4 suppresses exactly one path per dispatch; a lane shard is not it."""
    write_report(sandbox, 'T1-init', created=['tests/generated/T1-init/test_ac.py'])
    write_report(sandbox, 'T1', created=['tests/generated/T1-init/test_ac.py'])
    prompt = close_step2_canonical_prompt('docs/dev/dev-report-T1-init.json', 'T1')
    rc, err = run_gate(sandbox_hook(sandbox), prompt)
    assert rc == 2, 'a lane shard was admitted by the canonical exemption'
    assert 'tests/generated/T1-init/test_ac.py' in err


def test_e4_without_deliverable_anchor_still_refused(sandbox):
    """No declared close-report means no <P>, so E4 cannot fire."""
    write_report(sandbox, 'T1-init', created=['tests/generated/T1-init/test_ac.py'])
    write_report(sandbox, 'T1', created=['tests/generated/T1-init/test_ac.py'])
    prompt = close_step2_canonical_prompt('docs/dev/dev-report-T1.json', 'T1').replace(
        'docs/dev/close-report-T1.md', 'the close transcript')
    rc, err = run_gate(sandbox_hook(sandbox), prompt)
    assert rc == 2
    assert 'tests/generated/T1-init/test_ac.py' in err


def test_e4_ambiguous_deliverable_anchor_fails_closed(sandbox):
    """Two distinct close-report task-ids disable E4 exactly as they disable E3."""
    write_report(sandbox, 'T1-init', created=['tests/generated/T1-init/test_ac.py'])
    write_report(sandbox, 'T1', created=['tests/generated/T1-init/test_ac.py'])
    prompt = close_step2_canonical_prompt('docs/dev/dev-report-T1.json', 'T1') + \
        'Also see docs/dev/close-report-T2.md\n'
    rc, err = run_gate(sandbox_hook(sandbox), prompt)
    assert rc == 2
    assert 'tests/generated/T1-init/test_ac.py' in err


def test_e4_does_not_launder_other_citations(sandbox):
    """Citing the canonical never admits some OTHER report's work product."""
    write_report(sandbox, 'T1-init', created=['tests/generated/T1-init/test_ac.py'])
    write_report(sandbox, 'T1', created=['tests/generated/T1-init/test_ac.py'])
    rel = write_report(sandbox, 'T9', created=['docs/dev/my-analysis.json'])
    prompt = close_step2_canonical_prompt('docs/dev/dev-report-T1.json', 'T1') + \
        'Dev report file: %s\n' % rel
    rc, err = run_gate(sandbox_hook(sandbox), prompt)
    assert rc == 2, 'the canonical citation laundered a neighbouring deliverable'
    assert err == 'BLOCKED: gitignored deliverables detected: docs/dev/my-analysis.json'


# --- structural properties of the discriminator ---------------------------

def test_canonical_name_is_not_caller_chosen():
    gate = load_gate_module()
    assert gate.canonical_report_rel('T1') == 'docs/dev/dev-report-T1.json'
    assert gate.canonical_report_rel('T1-init') == 'docs/dev/dev-report-T1-init.json'


def test_shard_provenance_is_read_off_disk_not_off_the_prompt(sandbox):
    gate = load_gate_module()
    write_report(sandbox, 'T1-init', created=['tests/generated/T1-init/test_ac.py'])
    root = str(sandbox)
    assert gate.shard_recorded_paths('T1', root) == {
        'tests/generated/T1-init/test_ac.py'}
    assert gate.has_lane_shard_provenance(
        ['tests/generated/T1-init/test_ac.py'], 'T1', root)
    assert not gate.has_lane_shard_provenance(['docs/dev/my-analysis.json'], 'T1', root)
    assert not gate.has_lane_shard_provenance([], 'T1', root)
    assert not gate.has_lane_shard_provenance(['x'], 'NOSUCH', root)


def test_malformed_shard_contributes_no_provenance(sandbox):
    """A shard that will not decode fails CLOSED rather than widening the set."""
    gate = load_gate_module()
    (sandbox / 'docs/dev/dev-report-T1-broken.json').write_text('{not json')
    assert gate.shard_recorded_paths('T1', str(sandbox)) == set()


# --- verdict invariance for the dispatch shapes NOT being fixed -----------
#
# The prior-step gate cannot be recovered from git: BOTH earlier narrow steps
# are still uncommitted, so `git show HEAD:` yields the gate as it stood before
# ALL THREE steps and would attribute E1/E2/E3's admissions to this one.
# The baseline used instead is exact by construction: E4 is a single guarded
# `continue` whose conjunct (3) is `has_lane_shard_provenance`, so forcing that
# predicate False reduces the gate to E1/E2/E3 alone, byte-for-byte.


def run_gate_baseline(prompt, e4_enabled):
    """Run the gate in-process, optionally with E4's conjunct (3) forced off."""
    gate = load_gate_module()
    if not e4_enabled:
        gate.has_lane_shard_provenance = lambda paths, tid, root: False
    payload = json.dumps({'tool_name': 'Agent',
                          'tool_input': {'subagent_type': 'qa', 'prompt': prompt}})
    err = io.StringIO()
    saved = sys.stdin
    sys.stdin = io.StringIO(payload)
    try:
        with contextlib.redirect_stderr(err):
            gate.main()
        rc = 0
    except SystemExit as exc:
        rc = exc.code or 0
    finally:
        sys.stdin = saved
    return rc, err.getvalue().strip()


def test_e4_moves_no_verdict_outside_the_canonical_citation_shape():
    """Only dispatches that satisfy all three E4 conjuncts may change verdict."""
    canonical = 'docs/dev/dev-report-%s.json' % LIVE_TASK_ID
    if not os.path.isfile(os.path.join(REPO_ROOT, canonical)):
        pytest.skip('live artifacts for %s not present in this tree' % LIVE_TASK_ID)
    with open(os.path.join(REPO_ROOT, canonical)) as fh:
        changed = json.load(fh)['dev']['files_modified']

    must_not_move = {
        'plain': 'Do something unrelated.\n',
        'step1_audit_input': close_step1_prompt(changed, LIVE_TASK_ID),
        'step2_lane_matrix': close_step2_prompt(
            [lane_row('%s-init' % LIVE_TASK_ID)], LIVE_TASK_ID, canonical=canonical),
    }
    for rel in sorted(glob.glob(os.path.join(REPO_ROOT,
                                             'docs/dev/dev-report-%s*.json'
                                             % LIVE_TASK_ID))):
        name = os.path.relpath(rel, REPO_ROOT)
        must_not_move['manifest:' + name] = 'Dev report file: %s\n' % name

    drifted, verdicts = [], []
    for name, prompt in must_not_move.items():
        base = run_gate_baseline(prompt, e4_enabled=False)
        now = run_gate_baseline(prompt, e4_enabled=True)
        verdicts.append(base[0])
        if base != now:
            drifted.append((name, base[0], now[0]))
    # Non-vacuity: if every baseline verdict were 0 the equality would prove
    # nothing. The manifest shapes must supply real refusals.
    assert 2 in verdicts and 0 in verdicts, \
        'corpus is not discriminating: baseline verdicts were all %r' % set(verdicts)
    assert not drifted, 'verdict drifted for untouched shapes: %r' % drifted

    # The shapes that MUST move, in exactly one direction.
    for by_pattern in (True, False):
        prompt = close_step2_canonical_prompt(canonical, LIVE_TASK_ID,
                                              lanes_by_pattern=by_pattern)
        assert run_gate_baseline(prompt, e4_enabled=False)[0] == 2
        assert run_gate_baseline(prompt, e4_enabled=True)[0] == 0


def test_e4_is_report_scoped_not_occurrence_scoped():
    """A recorded consequence of anchoring on provenance instead of position.

    E1 and E3 suppress by prompt POSITION, so they must be per-occurrence or a
    deliverable manifest could be laundered by a span. E4 suppresses by on-disk
    PROVENANCE, so position is irrelevant: whatever line the canonical is cited
    on, the only paths it can carry are ones a lane shard of the same cycle
    already recorded. That makes the canonical exempt even in the /dev
    deliverable-manifest position — a deliberate consequence, pinned here so a
    future reader sees a decision rather than drift. The laundering that
    actually matters is still refused: see
    test_unauthorised_work_product_still_refused_with_close_report_in_scope and
    test_e4_canonical_without_shard_provenance_still_refused, where the product
    has no shard provenance.
    """
    canonical = 'docs/dev/dev-report-%s.json' % LIVE_TASK_ID
    if not os.path.isfile(os.path.join(REPO_ROOT, canonical)):
        pytest.skip('live artifacts for %s not present in this tree' % LIVE_TASK_ID)
    prompt = ('Dev report file: %s\n'
              'Prior closure: docs/dev/close-report-%s.md\n'
              % (canonical, LIVE_TASK_ID))
    assert run_gate_baseline(prompt, e4_enabled=False)[0] == 2
    assert run_gate_baseline(prompt, e4_enabled=True)[0] == 0


# ==========================================================================
# E2 narrowing (FOURTH step, 2026-09-07) — the trail's claim made true
# ==========================================================================
#
# The first step's trail claimed E2 admits "exactly four shapes mandated by
# commands/close.md". Two measured ways that was false, neither pinned by any
# test, and both invisible to the corpus because E2 fires for ZERO of the 313
# real dev-report-*.json:
#   (a) the task-id was taken with `rsplit('.', 1)[0]`, discarding the
#       extension, so close-report-<TID>.py / .sh / no-extension were admitted
#       exactly as close-report-<TID>.md was;
#   (b) `src_task_id.startswith(tid + '-')` admitted every dash-delimited
#       ANCESTOR, not the parent, so a report for 20260809-013317-init admitted
#       docs/dev/close-report-20260809.md — a different task's close-report,
#       whose last line /commit reads as that task's closure verdict.
#
# Every test below fails against the predicate as it stood before this step.

COLLIDING_LANE = '20260809-013317-init'


@pytest.mark.parametrize('name', [
    'close-report-T1.py',
    'close-report-T1.sh',
    'close-report-T1',
    'close-report-T1.json',
    'style-inspector-report-T1.md',
    'style-inspector-report-T1.py',
    'cleanliness-inspector-report-T1.md',
    'prompt-inspector-report-T1.txt',
])
def test_e2_mandated_basename_with_foreign_extension_is_refused(sandbox, name):
    """(a) The extension is part of the mandated shape, not decoration.

    close.md mandates the three inspector reports as `.json` (:348-350,
    :364-366, :427-429) and the close-report as `.md` (:78, :518, :540, :543).
    A name differing only in extension is a different file the contract does not
    mandate — and the extension is the one part of a mandated name the caller is
    free to choose, so admitting it handed the caller the whole shape.
    """
    rel = write_report(sandbox, 'T1', created=['docs/dev/%s' % name])
    rc, err = run_gate(sandbox_hook(sandbox), 'Dev report file: %s\n' % rel)
    assert rc == 2, 'foreign-extension name %s was admitted by E2' % name
    assert err == 'BLOCKED: gitignored deliverables detected: docs/dev/%s' % name


def test_e2_dash_prefix_collision_is_refused(sandbox):
    """(b) An ancestor task-id is not this report's parent.

    docs/dev/close-report-20260809.md names a DIFFERENT task's close-report;
    admitting it let a report for one cycle claim another cycle's closure file.
    """
    rel = write_report(sandbox, COLLIDING_LANE,
                       created=['docs/dev/close-report-20260809.md'])
    rc, err = run_gate(sandbox_hook(sandbox), 'Dev report file: %s\n' % rel)
    assert rc == 2, 'a dash-prefix ancestor was admitted as the parent'
    assert err == ('BLOCKED: gitignored deliverables detected: '
                   'docs/dev/close-report-20260809.md')


def test_e2_collision_is_refused_even_when_the_real_parent_is_on_disk(sandbox):
    """The genuine parent's presence must not vouch for a shorter ancestor."""
    write_report(sandbox, '20260809-013317', created=[])
    rel = write_report(sandbox, COLLIDING_LANE,
                       created=['docs/dev/close-report-20260809.md'])
    rc, _ = run_gate(sandbox_hook(sandbox), 'Dev report file: %s\n' % rel)
    assert rc == 2


def test_e2_still_admits_the_parent_and_the_four_mandated_shapes(sandbox):
    """Not-too-narrow control: the shapes close.md really mandates still pass.

    Over-narrowing here would restore the failure this exemption exists to fix —
    a fan-out cycle's close dying at Step 1 on this gate.
    """
    write_report(sandbox, '20260809-013317', created=[])
    rel = write_report(sandbox, COLLIDING_LANE, created=[
        'docs/dev/close-report-20260809-013317.md',
        'docs/dev/style-inspector-report-20260809-013317.json',
        'docs/dev/cleanliness-inspector-report-20260809-013317.json',
        'docs/dev/prompt-inspector-report-20260809-013317.json',
    ])
    rc, err = run_gate(sandbox_hook(sandbox), 'Dev report file: %s\n' % rel)
    assert rc == 0, 'the mandated shapes were over-narrowed away: %s' % err


def test_e2_dashed_worker_label_still_resolves_to_its_parent(sandbox):
    """Not-too-narrow control: worker labels really do contain dashes.

    Measured 2026-09-07 over docs/dev: 21 of 131 lane ids have a dashed worker
    (`application-assistant`, `subtask-ab`, `fill-tests`). A lexical
    last-dash split would refuse every one of them, so the parent is resolved
    from on-disk evidence instead.
    """
    write_report(sandbox, 'T1', created=[])
    rel = write_report(sandbox, 'T1-application-assistant',
                       created=['docs/dev/close-report-T1.md'])
    rc, err = run_gate(sandbox_hook(sandbox), 'Dev report file: %s\n' % rel)
    assert rc == 0, 'a real dashed worker label was over-narrowed away: %s' % err


def test_e2_parent_is_exactly_one_task_id_not_a_family(sandbox):
    """The structural property the string prefix failed to express."""
    gate = load_gate_module()
    root = str(sandbox)
    # No canonical anywhere: the immediate lexical parent, and only that.
    assert gate.parent_task_id('T1-lane', root) == 'T1'
    assert gate.parent_task_id('A-B-C', root) == 'A-B'
    assert gate.parent_task_id('T1', root) is None
    # With evidence on disk the nearest real ancestor wins, not every ancestor.
    write_report(sandbox, 'A-B', created=[])
    assert gate.parent_task_id('A-B-C-D', root) == 'A-B'
    write_report(sandbox, 'A-B-C', created=[])
    assert gate.parent_task_id('A-B-C-D', root) == 'A-B-C'


def test_e2_extension_binding_is_the_close_md_mandate():
    """Each mandated prefix carries the extension close.md mandates for it."""
    gate = load_gate_module()
    assert gate.CONTRACT_DELIVERABLE_PREFIXES == {
        'style-inspector-report-': '.json',
        'cleanliness-inspector-report-': '.json',
        'prompt-inspector-report-': '.json',
        'close-report-': '.md',
    }


def test_e2_narrowing_admits_nothing_new(sandbox):
    """This step may only REFUSE more; it must never admit more.

    Anything E2 admitted before and still admits is fine; anything it admits now
    but did not before would be a widening, which is out of scope for a
    narrowing step.
    """
    gate = load_gate_module()
    root = str(sandbox)
    write_report(sandbox, 'T1', created=[])
    write_report(sandbox, 'T1-a', created=[])
    for src in ('T1', 'T1-a', 'T1-a-b', 'OTHER'):
        for prefix in gate.CONTRACT_DELIVERABLE_PREFIXES:
            for ext in ('.md', '.json', '.py', '.sh', ''):
                for tid in ('T1', 'T1-a', 'T1-a-b', 'OTHER', ''):
                    path = 'docs/dev/%s%s%s' % (prefix, tid, ext)
                    now = gate.is_contract_deliverable(path, src, root)
                    if not now:
                        continue
                    # the pre-fix predicate, inlined verbatim
                    base = os.path.basename(path)
                    before = False
                    for pre in gate.CONTRACT_DELIVERABLE_PREFIXES:
                        if not base.startswith(pre):
                            continue
                        old = base[len(pre):].rsplit('.', 1)[0]
                        before = bool(old) and (
                            old == src or src.startswith(old + '-'))
                        break
                    assert before, 'E2 now admits %s for %s but did not before' \
                        % (path, src)


# ==========================================================================
# E5 — /commit Step 7 changelog-analyst dispatch (FIFTH step, 2026-09-17)
# ==========================================================================
#
# E1/E3/E4 are all anchored on /close Step 1/Step 2 dispatch shapes (an
# auditor's --changed-files list, a QA gatekeeper's lane matrix, its
# canonical-parent citation). /commit Step 7's changelog-analyst dispatch
# legitimately reads a task's dev-report to build its OWN staging
# classification, but declares no close-report deliverable, so none of E1/E3/
# E4 can anchor an exemption for it. The measured live refusal (2026-09-17,
# re-close of 20260808-035658, exit 2, 8 distinct paths) is reproduced here in
# miniature: a synthetic dev-report declaring a gitignored deliverable, opened
# by a changelog-analyst-shaped prompt with no lane-matrix span and no
# close-report deliverable.
#
# Discriminator E5 exempts this shape ONLY when the prompt cites a live,
# unexpired /tmp/claude-commit-grant-*.json whose own task_id (read off disk,
# never off the prompt) equals the report's src_task_id, and whose expires_at
# has not passed. A commit-grant file can only be minted by /commit's own
# Step 5, itself gated on a prior CLOSE: YES verdict for that exact task-id,
# so E5 cannot be satisfied by prompt text alone.


def commit_step7_prompt(dev_report_rel, grant_path=None):
    """The /commit Step 7 changelog-analyst dispatch shape.

    A legitimate READ of the report to build a staging classification — no
    --changed-files span (E1), no lane matrix (E3), no close-report deliverable
    (E3/E4 anchor) anywhere in the prompt.
    """
    prompt = (
        'You are the changelog-analyst subagent for /commit Step 7.\n'
        'DRYRUN=true\n'
        'Read the dev report yourself and classify files for staging: %s\n'
        % dev_report_rel
    )
    if grant_path:
        prompt += 'Commit grant: %s\n' % grant_path
    return prompt


def _iso_offset(seconds):
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(seconds=seconds)).isoformat()


@pytest.fixture
def commit_grant():
    """Create a real /tmp/claude-commit-grant-<unique>.json file; clean up after.

    The gate's COMMIT_GRANT_PATTERN is anchored on the literal /tmp/claude-
    commit-grant-*.json prefix, so this cannot be redirected under tmp_path —
    it must be a real file at that exact location, same as production.
    """
    created = []

    def _make(task_id, expires_at, extra=None):
        path = '/tmp/claude-commit-grant-%s.json' % uuid.uuid4().hex
        body = {'task_id': task_id, 'expires_at': expires_at}
        if extra:
            body.update(extra)
        with open(path, 'w') as f:
            json.dump(body, f)
        created.append(path)
        return path

    yield _make

    for path in created:
        with contextlib.suppress(FileNotFoundError):
            os.remove(path)


# --- AC2.1 — E5 positive: live, unexpired, task-id-matched grant -----------

def test_e5_live_matched_grant_admits_dispatch(sandbox, commit_grant):
    rel = write_report(sandbox, 'T1', created=['docs/dev/my-analysis.json'])
    grant = commit_grant('T1', _iso_offset(1800))
    prompt = commit_step7_prompt(rel, grant)
    rc, err = run_gate(sandbox_hook(sandbox), prompt)
    assert rc == 0, 'live unexpired task-id-matched grant still refused: %s' % err
    assert err == ''


# --- AC2.2 — E5 negative: no grant reference -> identical pre-E5 refusal ---

def test_e5_no_grant_reference_refused_identically_to_pre_e5(sandbox):
    rel = write_report(sandbox, 'T1', created=['docs/dev/my-analysis.json'])
    prompt = commit_step7_prompt(rel)
    rc, err = run_gate(sandbox_hook(sandbox), prompt)
    assert rc == 2
    assert err == 'BLOCKED: gitignored deliverables detected: docs/dev/my-analysis.json'


# --- AC2.3 — E5 negative: grant referenced but expired ---------------------

def test_e5_expired_grant_still_refused(sandbox, commit_grant):
    rel = write_report(sandbox, 'T1', created=['docs/dev/my-analysis.json'])
    grant = commit_grant('T1', _iso_offset(-1800))
    prompt = commit_step7_prompt(rel, grant)
    rc, err = run_gate(sandbox_hook(sandbox), prompt)
    assert rc == 2
    assert err == 'BLOCKED: gitignored deliverables detected: docs/dev/my-analysis.json'


# --- AC2.4 — E5 negative: grant referenced but task_id mismatched ----------

def test_e5_task_id_mismatched_grant_still_refused(sandbox, commit_grant):
    rel = write_report(sandbox, 'T1', created=['docs/dev/my-analysis.json'])
    grant = commit_grant('T1-SOMEONE-ELSE', _iso_offset(1800))
    prompt = commit_step7_prompt(rel, grant)
    rc, err = run_gate(sandbox_hook(sandbox), prompt)
    assert rc == 2
    assert err == 'BLOCKED: gitignored deliverables detected: docs/dev/my-analysis.json'


# --- structural properties of the discriminator ---------------------------

def test_has_live_commit_grant_reads_task_id_and_ttl_off_disk(commit_grant):
    """Direct unit coverage of has_live_commit_grant's own conjuncts."""
    gate = load_gate_module()

    live = commit_grant('T1', _iso_offset(1800))
    prompt = 'Commit grant: %s\n' % live
    assert gate.has_live_commit_grant(prompt, 'T1')
    # A prompt cannot claim a grant for a task-id it does not hold one for.
    assert not gate.has_live_commit_grant(prompt, 'T1-OTHER')

    expired = commit_grant('T1', _iso_offset(-1800))
    prompt_expired = 'Commit grant: %s\n' % expired
    assert not gate.has_live_commit_grant(prompt_expired, 'T1')


def test_has_live_commit_grant_missing_file_fails_closed():
    gate = load_gate_module()
    prompt = 'Commit grant: /tmp/claude-commit-grant-does-not-exist-e5test.json\n'
    assert not gate.has_live_commit_grant(prompt, 'T1')


def test_has_live_commit_grant_malformed_json_fails_closed(commit_grant):
    gate = load_gate_module()
    path = commit_grant('T1', _iso_offset(1800))
    with open(path, 'w') as f:
        f.write('{not json')
    prompt = 'Commit grant: %s\n' % path
    assert not gate.has_live_commit_grant(prompt, 'T1')


def test_e5_never_widens_the_admissible_path_set(sandbox, commit_grant):
    """E5 conjunct (1): it can only re-permit the report's OWN declared paths.

    A live grant for src_task_id must not admit an UNRELATED report's citation
    in the same prompt — E5 fires per-report, not per-prompt.
    """
    rel_a = write_report(sandbox, 'T1', created=['docs/dev/my-analysis.json'])
    rel_b = write_report(sandbox, 'T2', created=['docs/dev/other-analysis.json'])
    grant = commit_grant('T1', _iso_offset(1800))
    prompt = commit_step7_prompt(rel_a, grant) + 'Also read: %s\n' % rel_b
    rc, err = run_gate(sandbox_hook(sandbox), prompt)
    assert rc == 2, 'a T1 grant exempted an unrelated T2 report'
    assert err == 'BLOCKED: gitignored deliverables detected: docs/dev/other-analysis.json'


def test_e1_e4_predicates_unchanged_when_e5_does_not_apply(sandbox):
    """E5 addition must not alter E1-E4 behaviour for dispatch shapes with no grant."""
    rel = write_report(sandbox, 'T1-adj', created=['docs/dev/close-report-T1.md'])
    rc, err = run_gate(sandbox_hook(sandbox),
                       'Dev report file: docs/dev/dev-report-T1-adj.json\n')
    assert rc == 0, err
