#!/usr/bin/env python3
"""The gitignore preflight refuses only a dispatch whose agent type can write (E7, OB-L29).

pretool-gitignore-preflight.py scopes its refusal by the dispatched agent's
write capability (discriminator E7, GIT-10). A dispatch that cites a dev report whose dev.files_created holds a path
.gitignore matches was refused whatever agent type it dispatched, so an Explore
agent asked only to read and summarize that report was blocked. The capability
is read from policies/tool-policy.v1.json: an agent type the policy declares
with no write tool is admitted; every other dispatch keeps the refusal.

The gate runs from the harness's own hooks/ (so it reads the harness's own
policy, as in production) against a throwaway project named by
CLAUDE_PROJECT_DIR. One case runs a copy of the gate with no policy beside it,
to pin the fail-closed reading.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO_ROOT, 'hooks', 'pretool-gitignore-preflight.py')
POLICY = os.path.join(REPO_ROOT, 'policies', 'tool-policy.v1.json')
TASK = '20261117-090000'
IGNORED = '.pytest_cache/v/cache/lastfailed'
BLOCKED = 'BLOCKED: gitignored deliverables detected: ' + IGNORED


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A git project whose .gitignore matches .pytest_cache/, holding one dev
    report that records a file under it."""
    root = tmp_path / 'project'
    (root / 'docs' / 'dev').mkdir(parents=True)
    (root / '.gitignore').write_text('.pytest_cache/\n')
    subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
    (root / 'docs' / 'dev' / ('dev-report-%s.json' % TASK)).write_text(json.dumps(
        {'dev': {'files_modified': ['src/app.py'], 'files_created': [IGNORED]}}))
    monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(root))
    return root


REPORT = 'docs/dev/dev-report-%s.json' % TASK
READ_PROMPT = ('Read %s and summarize what the cycle changed: the files it lists and why. '
               'Report back in your reply; write no file.\n' % REPORT)
DEV_PROMPT = 'Dev report file: %s\nFix the failing acceptance criterion and update the report.\n' % REPORT
QA_PROMPT = 'Dev report file: %s\nVerify every acceptance criterion and write your QA report.\n' % REPORT


def run_gate(prompt, subagent_type=None, hook=HOOK):
    tool_input = {'prompt': prompt, 'description': 'dispatch'}
    if subagent_type is not None:
        tool_input['subagent_type'] = subagent_type
    proc = subprocess.run([sys.executable, hook], capture_output=True, text=True,
                          input=json.dumps({'tool_name': 'Agent', 'tool_input': tool_input}))
    return proc.returncode, proc.stderr.strip().split('\n')[0]


def load_gate():
    spec = importlib.util.spec_from_file_location('gitignore_preflight_e7', HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# The over-block lifted
# --------------------------------------------------------------------------

def test_explore_reading_a_cited_report_is_admitted(project):
    """OB-L29 must-pass: Explore has no write tool, so the report it is asked to
    read is no manifest of anything it ships. Refused (exit 2) before E7."""
    rc, err = run_gate(READ_PROMPT, 'Explore')
    assert rc == 0, 'read-only Explore dispatch still refused: %s' % err
    assert err == ''


def test_the_policy_declares_explore_without_a_write_tool():
    """The admission is read from the policy, not from a list in the hook."""
    with open(POLICY) as fh:
        row = json.load(fh)['built_in_agents']['Explore']
    for tool in ('Write', 'Edit', 'MultiEdit', 'NotebookEdit'):
        assert tool not in row['allowed_tools']
        assert tool in row['denied_tools']
    assert load_gate().agent_can_write('Explore') is False


# --------------------------------------------------------------------------
# Must still refuse
# --------------------------------------------------------------------------

@pytest.mark.parametrize('subagent_type,prompt', [
    ('dev', DEV_PROMPT),
    ('qa', QA_PROMPT),
    ('general-purpose', READ_PROMPT),
])
def test_a_dispatch_that_can_write_is_still_refused(project, subagent_type, prompt):
    """OB-L29 must-refuse: the cycle's dev and qa dispatches, and a
    general-purpose dispatch citing the same report (it has Write)."""
    rc, err = run_gate(prompt, subagent_type)
    assert rc == 2
    assert err == BLOCKED


def test_a_dispatch_naming_no_agent_type_is_still_refused(project):
    """No subagent_type runs general-purpose, which can write."""
    rc, err = run_gate(READ_PROMPT)
    assert rc == 2
    assert err == BLOCKED


def test_an_agent_type_the_policy_does_not_name_is_still_refused(project):
    """A plugin agent the policy declares nowhere counts as able to write."""
    rc, err = run_gate(READ_PROMPT, 'someplugin:reader')
    assert rc == 2
    assert err == BLOCKED


def test_every_policy_role_carrying_a_write_tool_keeps_the_refusal(project):
    """E7 admits by the policy's tool lists: each role row with a write tool
    is refused exactly as before."""
    with open(POLICY) as fh:
        roles = json.load(fh)['roles']
    writers = [name for name, row in roles.items()
               if {'Write', 'Edit', 'MultiEdit', 'NotebookEdit'} & set(row.get('allowed_tools') or [])]
    assert {'dev', 'qa'} <= set(writers)
    gate = load_gate()
    for name in writers:
        assert gate.agent_can_write(name) is True, name


def test_an_unreadable_policy_fails_closed(project, tmp_path):
    """A gate with no policy it can read refuses Explore as before."""
    harness = tmp_path / 'harness'
    (harness / 'hooks').mkdir(parents=True)
    shutil.copy2(HOOK, harness / 'hooks' / 'pretool-gitignore-preflight.py')
    shutil.copytree(os.path.join(REPO_ROOT, 'hooks', 'lib'), harness / 'hooks' / 'lib',
                    ignore=shutil.ignore_patterns('__pycache__'))
    for name in ('schemas', 'scripts'):
        os.symlink(os.path.join(REPO_ROOT, name), harness / name)
    rc, err = run_gate(READ_PROMPT, 'Explore',
                       hook=str(harness / 'hooks' / 'pretool-gitignore-preflight.py'))
    assert rc == 2
    assert err == BLOCKED
