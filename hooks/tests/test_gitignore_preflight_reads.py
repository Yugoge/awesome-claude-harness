#!/usr/bin/env python3
"""The gitignore preflight refuses a dispatch over the files a dev report lists only where the
dispatch ships them (E8, E9 in hooks/pretool-gitignore-preflight.py's header).

Shapes of the live hour of 2026-11-19 (a 16-lane /dev): lane devs citing a sibling lane's report as
reading material; the lane dev the collection check names as its remedy, citing its fan-out's
canonical aggregate; reports written before agents/dev.md stopped listing generated tests. And the
case the rule is for: the QA of a dev report listing an ignored work product is still refused.

Each case runs the hook in a subprocess against a throwaway git project (CLAUDE_PROJECT_DIR) with
HOME and the CLI configuration directory in the test's own folder, so no account transcript is read.
"""

import json
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO_ROOT, 'hooks', 'pretool-gitignore-preflight.py')
TASK = '20261117-090000'
PRODUCT = 'build/app.js'                               # a work product the project ignores
OLD_TESTS = ['tests/generated/20260701-101010/test_AC_01_0a1b2c3d4e5f6a7b.py',
             'tests/generated/%s-l3/test_AC01_1b2c3d4e5f6a7b8c.py' % TASK]
BLOCKED = 'BLOCKED: gitignored deliverables detected: '


def report_rel(task):
    return 'docs/dev/dev-report-%s.json' % task


@pytest.fixture
def project(tmp_path):
    root = tmp_path / 'project'
    (root / 'docs' / 'dev').mkdir(parents=True)
    (root / '.gitignore').write_text('/tests/generated/\n/build/\n')
    subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
    return root


def write_report(root, task, created):
    (root / report_rel(task)).write_text(json.dumps({'dev': {'files_modified': ['src/app.py'],
                                                             'files_created': created}}))


def obligation(task, role, artifact, schema, lane=None):
    doc = {'task_id': task, 'role': role, 'pipeline': 'dev',
           'profile': 'fanout-lane' if lane else 'singular', 'dispatched_at': '2026-11-19T17:35:00Z',
           'artifacts': [{'kind': 'json', 'path': artifact, 'schema': schema, 'identity': {'task_id': task}}]}
    if lane:
        doc.update(lane=lane, lane_set=['l1', 'l2', 'l3'])
    return '<obligation v="1">\n%s\n</obligation>\n' % json.dumps(doc, indent=2)


def lane_dev(lane):
    task = '%s-%s' % (TASK, lane)
    return obligation(task, 'dev', report_rel(task), 'dev-report.v2', lane=lane)


def run_gate(root, prompt, subagent_type):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), HOME=str(root.parent / 'home'),
               CLAUDE_CONFIG_DIR=str(root.parent / 'home' / '.claude'))
    env.pop('CLAUDE_HOME', None)
    payload = {'tool_name': 'Agent', 'tool_input': {'subagent_type': subagent_type, 'description': 'd',
                                                    'prompt': prompt}}
    proc = subprocess.run([sys.executable, HOOK], input=json.dumps(payload), capture_output=True, text=True,
                          env=env, cwd=str(root), timeout=60)
    return proc.returncode, (proc.stderr.strip().split('\n') or [''])[0]


def test_lane_dev_citing_a_sibling_lanes_report_is_admitted(project):
    """E8: the integration-fix shape. Lane l1's dev reads lane l3's report; l3's files are l3's."""
    write_report(project, TASK + '-l3', [PRODUCT])
    prompt = ('Write your report to %s.\nRead the upstream lane report %s for the interface it built.\n%s'
              % (report_rel(TASK + '-l1'), report_rel(TASK + '-l3'), lane_dev('l1')))
    assert run_gate(project, prompt, 'dev') == (0, '')


def test_remedy_dev_citing_its_canonical_aggregate_is_admitted(project):
    """E8: the dev dispatched again for its own lane report (the remedy the collection check names)
    reads its fan-out's canonical aggregate, whatever that aggregate lists."""
    write_report(project, TASK + '-l3', [PRODUCT])
    write_report(project, TASK, [PRODUCT] + OLD_TESTS)
    prompt = ('Rewrite your report %s.\nThe canonical aggregate is %s.\n%s'
              % (report_rel(TASK + '-l3'), report_rel(TASK), lane_dev('l3')))
    assert run_gate(project, prompt, 'dev') == (0, '')


def test_qa_of_a_report_listing_only_generated_tests_is_admitted(project):
    """E9: a report written before agents/dev.md stopped listing generated tests does not block its
    QA: the policy keeps tests/generated/ out of git, so they are no deliverable."""
    write_report(project, TASK, ['src/new.py'] + OLD_TESTS)
    prompt = 'Dev report file: %s\n%s' % (report_rel(TASK), obligation(
        TASK, 'qa', 'docs/dev/qa-report-%s.json' % TASK, 'qa-report.v2'))
    assert run_gate(project, prompt, 'qa') == (0, '')


def test_qa_of_a_report_listing_an_ignored_work_product_is_refused(project):
    """What the rule is for: QA would pass a cycle whose declared work product git never ships.
    The generated tests beside it are not named."""
    write_report(project, TASK, [PRODUCT] + OLD_TESTS)
    prompt = 'Dev report file: %s\n%s' % (report_rel(TASK), obligation(
        TASK, 'qa', 'docs/dev/qa-report-%s.json' % TASK, 'qa-report.v2'))
    assert run_gate(project, prompt, 'qa') == (2, BLOCKED + PRODUCT)


def test_dev_dispatch_with_no_obligation_keeps_the_refusal(project):
    """E8 reads the dispatch's own obligation; a dispatch carrying none is refused as before."""
    write_report(project, TASK + '-l3', [PRODUCT])
    prompt = 'Read the upstream lane report %s and build lane l1.\n' % report_rel(TASK + '-l3')
    assert run_gate(project, prompt, 'dev') == (2, BLOCKED + PRODUCT)


def test_dev_dispatch_citing_its_own_tasks_other_report_keeps_the_refusal(project):
    """E8 admits only another task's report: a dev's own task's report it does not declare is
    judged as before."""
    write_report(project, TASK, [PRODUCT])
    prompt = 'Dev report file: %s\n%s' % (report_rel(TASK), obligation(
        TASK, 'dev', 'docs/dev/dev-notes-%s.json' % TASK, 'dev-report.v2'))
    assert run_gate(project, prompt, 'dev') == (2, BLOCKED + PRODUCT)


# E10: the /codex step's consultation transcript (hooks/lib/codex_transcript) of the report's own task
# family is provenance; any other file under docs/codex/ is judged as before. The project ignores docs/codex/.

def qa_of(project, task, created):
    (project / '.gitignore').write_text('/tests/generated/\n/build/\ndocs/codex/**\n')
    write_report(project, task, created)
    return 'Dev report file: %s\n%s' % (report_rel(task), obligation(
        task, 'qa', 'docs/dev/qa-report-%s.json' % task, 'qa-report.v2'))


@pytest.mark.parametrize('transcript', ['docs/codex/%s/dev.txt' % TASK, 'docs/codex/%s-l3/dev-iter2.txt' % TASK])
def test_qa_of_a_report_listing_its_own_tasks_transcript_is_admitted(project, transcript):
    """The canonical report of TASK lists its own and its lane l3's transcript."""
    assert run_gate(project, qa_of(project, TASK, ['src/new.py', transcript]), 'qa') == (0, '')


def test_lane_report_listing_its_parents_transcript_is_admitted(project):
    write_report(project, TASK, [])  # the parent's canonical: parent_task_id settles on it
    prompt = qa_of(project, TASK + '-l3', ['docs/codex/%s/qa.txt' % TASK])
    assert run_gate(project, prompt, 'qa') == (0, '')


@pytest.mark.parametrize('path', ['docs/codex/20260101-000000/dev.txt',        # another task's transcript
                                  'docs/codex/%s/router-spec.md' % TASK,       # not the transcript shape
                                  'docs/codex/%s/sub/dev.txt' % TASK,          # nor this
                                  'build/app.js'])
def test_qa_of_a_report_listing_another_file_is_refused(project, path):
    assert run_gate(project, qa_of(project, TASK, ['src/new.py', path]), 'qa') == (2, BLOCKED + path)
