#!/usr/bin/env python3
"""Tests for how hooks/userprompt-doc-sync-check.py relays the skip notices of its child hook.

Backlog #83: the UserPromptSubmit hook resyncs a directory by running
posttool-doc-sync.py as a subprocess and used to discard everything that child printed,
so a skipped README stayed invisible on that path too. It now relays the child's notice.

The output contract, from the official hooks reference: JSON is only read when stdout
starts with "{" and parses as a whole, so plain lines and JSON must never be mixed. With
a relayed notice the whole stdout is one JSON object (resynced lines plus notices in
additionalContext for the agent, the notices alone in systemMessage for the user);
without one the stdout is the plain resync text it always was.

Isolation: the hook is loaded or run with a temporary HOME (its cache file and project
root come from Path.home()), a temporary TMPDIR, and CLAUDE_PROJECT_DIR and
CLAUDE_DOC_SYNC_ROOTS scrubbed. The end-to-end cases give the child a real COPY of
posttool-doc-sync.py and the doc_sync package under that HOME; a symlink to the
repository hooks would let a resync of the watched hooks directory write the real repo.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / 'hooks' / 'userprompt-doc-sync-check.py'
CHILD_HOOK = REPO_ROOT / 'hooks' / 'posttool-doc-sync.py'
DOC_SYNC_PACKAGE = REPO_ROOT / 'hooks' / 'doc_sync'

OPEN = '<!-- AUTO:readme-stats -->'
SCRUBBED_ENV = ('CLAUDE_PROJECT_DIR', 'CLAUDE_DOC_SYNC_ROOTS', 'CLAUDE_DOC_SYNC_STATE_ROOT')
RELAYED_TEXT = 'doc-sync: README not regenerated (SKIPPED_NO_CLOSING_MARKER). README: /somewhere/README.md'
CHILD_JSON = json.dumps({
    'systemMessage': RELAYED_TEXT,
    'hookSpecificOutput': {'hookEventName': 'PostToolUse', 'additionalContext': RELAYED_TEXT},
})


def load_hook_module(home, monkeypatch):
    """Import the hook file with HOME redirected first: CACHE_FILE and the roots derive from it."""
    monkeypatch.setenv('HOME', str(home))
    for name in SCRUBBED_ENV:
        monkeypatch.delenv(name, raising=False)
    spec = importlib.util.spec_from_file_location('userprompt_doc_sync_under_test', HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def relay(tmp_path, monkeypatch):
    home = tmp_path / 'relay-home'
    home.mkdir()
    return load_hook_module(home, monkeypatch).relay_child_notice


def test_relay_empty_stdout(relay):
    """Nothing printed by the child means nothing to relay."""
    for output in ('', '  \n', None):
        assert relay(output) is None


def test_relay_non_json_stdout(relay):
    """Plain text or truncated JSON is not a notice."""
    for output in ('doc-sync: some plain line\n', '{"systemMessage": "cut off', 'not json at all'):
        assert relay(output) is None


def test_relay_wrong_shape_stdout(relay):
    """Valid JSON without a non-empty string systemMessage is not a notice."""
    for output in ('[]', '"a quoted string"', 'null', '{}', '{"systemMessage": 5}',
                   '{"systemMessage": "   "}', '{"hookSpecificOutput": {"additionalContext": "x"}}'):
        assert relay(output) is None


def test_relay_valid_stdout(relay):
    """The systemMessage of the child's JSON object is the notice text."""
    assert relay(CHILD_JSON) == RELAYED_TEXT
    assert relay(CHILD_JSON + '\n') == RELAYED_TEXT


def build_home(root, readme_text=None):
    """A temp HOME whose .claude/commands lost a file since the cached snapshot."""
    home = Path(root) / 'home'
    hooks_dir = home / '.claude' / 'hooks'
    commands = home / '.claude' / 'commands'
    hooks_dir.mkdir(parents=True)
    commands.mkdir()
    shutil.copy(CHILD_HOOK, hooks_dir / 'posttool-doc-sync.py')
    shutil.copytree(DOC_SYNC_PACKAGE, hooks_dir / 'doc_sync',
                    ignore=shutil.ignore_patterns('__pycache__', 'README.md', 'INDEX.md'))
    (commands / 'keep.py').write_text('"""Keep."""\n')
    if readme_text is not None:
        (commands / 'README.md').write_text(readme_text)
    cache = {'last_check': 0, 'snapshots': {str(commands): ['gone.md', 'keep.py']}}
    (home / '.claude' / '.doc-sync-cache.json').write_text(json.dumps(cache))
    return home


def run_hook(home, tmp_root):
    environment = {key: value for key, value in os.environ.items() if key not in SCRUBBED_ENV}
    # The hook starts its child as `python3`; put the interpreter running the tests first.
    environment.update(
        HOME=str(home),
        TMPDIR=str(tmp_root),
        PATH=os.path.dirname(sys.executable) + os.pathsep + os.environ.get('PATH', ''),
        PYTHONDONTWRITEBYTECODE='1',
    )
    return subprocess.run(
        [sys.executable, str(HOOK)], capture_output=True, text=True, env=environment,
        cwd=str(home), timeout=120)


def resync_line(home):
    return f'doc-sync: detected deletion in {home / ".claude" / "commands"}, resynced INDEX.md'


def test_e2e_notice_single_json_object(tmp_path):
    """With a relayed notice the whole stdout is exactly one UserPromptSubmit JSON object."""
    home = build_home(tmp_path, readme_text=f'# Legacy\n\n{OPEN}\nstale stats without a terminator\n')
    readme = home / '.claude' / 'commands' / 'README.md'

    completed = run_hook(home, tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.count('\n') == 1 and completed.stdout.endswith('\n')
    output = json.loads(completed.stdout)
    assert set(output) == {'systemMessage', 'hookSpecificOutput'}
    assert output['hookSpecificOutput']['hookEventName'] == 'UserPromptSubmit'
    additional_context = output['hookSpecificOutput']['additionalContext']
    assert 'SKIPPED_NO_CLOSING_MARKER' in output['systemMessage']
    assert os.path.realpath(readme) in output['systemMessage']
    # The agent still gets the resync line; the user-facing message carries the notice only.
    assert resync_line(home) in additional_context
    assert output['systemMessage'] in additional_context
    assert 'detected deletion' not in output['systemMessage']


def test_e2e_no_notice_plain_text_unchanged(tmp_path):
    """Without a notice the stdout is the existing plain resync line, byte for byte."""
    home = build_home(tmp_path)

    completed = run_hook(home, tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == resync_line(home) + '\n'


@pytest.mark.parametrize('with_notice', [True, False])
def test_e2e_stdout_never_mixed(tmp_path, with_notice):
    """Stdout is either one JSON object or plain lines only, never a mixture of both."""
    readme_text = f'# Legacy\n\n{OPEN}\nstale\n' if with_notice else None
    home = build_home(tmp_path, readme_text=readme_text)

    completed = run_hook(home, tmp_path)

    lines = completed.stdout.splitlines()
    assert lines
    if with_notice:
        assert len(lines) == 1 and json.loads(lines[0])['hookSpecificOutput']
    else:
        assert not any(line.startswith('{') for line in lines)
        assert 'systemMessage' not in completed.stdout


def test_e2e_second_run_within_throttle_silent(tmp_path):
    """A second run inside the 300 s throttle window prints nothing and exits 0."""
    home = build_home(tmp_path, readme_text=f'# Legacy\n\n{OPEN}\nstale\n')

    first = run_hook(home, tmp_path)
    second = run_hook(home, tmp_path)

    assert first.stdout != ''
    assert second.returncode == 0
    assert second.stdout == ''
    assert json.loads((home / '.claude' / '.doc-sync-cache.json').read_text())['last_check'] > 0


@pytest.mark.parametrize('first_child_output', [
    pytest.param(CHILD_JSON, id='with_notice'),
    pytest.param('', id='plain_only'),
])
def test_earlier_output_survives_later_timeout(tmp_path, monkeypatch, capsys, first_child_output):
    """Output collected for an earlier directory is printed even if a later directory times out."""
    home = tmp_path / 'home'
    commands = home / '.claude' / 'commands'
    agents = home / '.claude' / 'agents'
    for directory, kept in ((commands, 'keep.py'), (agents, 'keep.md')):
        directory.mkdir(parents=True)
        (directory / kept).write_text('kept\n')
    cache_file = home / '.claude' / '.doc-sync-cache.json'
    cache_file.write_text(json.dumps({'last_check': 0, 'snapshots': {
        str(commands): ['gone.md', 'keep.py'], str(agents): ['gone.md', 'keep.md']}}))
    module = load_hook_module(home, monkeypatch)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            raise subprocess.TimeoutExpired(command, kwargs.get('timeout'))
        return subprocess.CompletedProcess(command, 0, stdout=first_child_output, stderr='')

    monkeypatch.setattr(module.subprocess, 'run', fake_run)

    with pytest.raises(SystemExit) as exit_info:
        module.main()

    assert exit_info.value.code == 0
    assert len(calls) == 2 and all(call['timeout'] == 5 for call in calls)
    printed = capsys.readouterr().out
    if first_child_output:
        output = json.loads(printed)
        assert output['systemMessage'] == RELAYED_TEXT
        assert output['hookSpecificOutput']['additionalContext'].count('detected deletion') == 1
    else:
        assert printed.count('detected deletion') == 1 and not printed.startswith('{')
    # The failure still skips the cache update, exactly as before.
    assert json.loads(cache_file.read_text())['last_check'] == 0
