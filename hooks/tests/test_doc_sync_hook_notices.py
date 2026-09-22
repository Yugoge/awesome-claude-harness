#!/usr/bin/env python3
"""Subprocess-level tests for the notices the PostToolUse doc-sync hook prints.

Backlog #83: a README that regen_readme() skips (no opening marker, or no closing marker)
must be reported to the caller of the hook chain instead of being skipped silently. The
hook is run exactly as the harness runs it: a subprocess fed a JSON payload on stdin.

Isolation: every run gets a temporary HOME and TMPDIR, CLAUDE_PROJECT_DIR points at a
synthetic project under tmp_path, and the parent environment's CLAUDE_PROJECT_DIR,
CLAUDE_DOC_SYNC_ROOTS and CLAUDE_DOC_SYNC_STATE_ROOT are scrubbed. Nothing here
regenerates anything inside the repository tree.

Unreadable or unwritable state cannot be simulated with permission bits on a host where
the tests run as uid 0, so the failure cases use conditions that hold for every user: a
directory where the state file should be, invalid or wrong-typed JSON, a session
directory that is a plain file, and regular-file writes that fail with EFBIG through
RLIMIT_FSIZE. tempfile.gettempdir() itself raises under that limit (it probes by
writing), so the write-failure cases resolve the state root through the documented
CLAUDE_DOC_SYNC_STATE_ROOT test seam and assert which step failed.
"""

import errno
import hashlib
import importlib
import io
import json
import os
import resource
import signal
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / 'hooks' / 'posttool-doc-sync.py'
sys.path.insert(0, str(REPO_ROOT))

main_module = importlib.import_module('hooks.doc_sync.main')

OPEN = '<!-- AUTO:readme-stats -->'
CLOSE = '<!-- /AUTO:readme-stats -->'
SCRUBBED_ENV = ('CLAUDE_PROJECT_DIR', 'CLAUDE_DOC_SYNC_ROOTS', 'CLAUDE_DOC_SYNC_STATE_ROOT')
STATE_ROOT_SEAM = 'CLAUDE_DOC_SYNC_STATE_ROOT'
NOTICE_CAP = 2000

README_TEXTS = {
    'S2': f'# Hand title\n\nhand text\n\n{OPEN}\nstale stats\n{CLOSE}\n\nmore hand text\n',
    'S3': f'# Legacy\n\nhand text\n\n{OPEN}\nstale stats without a terminator\n',
    'S4': '# Hand written\n\nno markers at all\n',
    'S5': f'# Reversed\n{CLOSE}\nmiddle\n{OPEN}\nstale\n',
    'S5b': f'{CLOSE}\nmiddle\n{OPEN}\nstale\n{CLOSE}\n',
    'S6': f'# Closing only\n\n{CLOSE}\n',
}


class World:
    """A synthetic project, HOME and TMPDIR for one hook run."""

    def __init__(self, root, folder_parts=('sub',)):
        self.root = Path(root)
        self.project = self.root / 'project'
        self.folder = self.project.joinpath(*folder_parts)
        self.home = self.root / 'home'
        self.tmp_root = self.root / 'tmp'
        for directory in (self.folder, self.home, self.tmp_root):
            directory.mkdir(parents=True)
        self.target = self.folder / 'tool.py'
        self.target.write_text('"""Tool."""\n')
        self.readme = self.folder / 'README.md'
        # A CLAUDE.md that already has a header and no AUTO region, and a well-formed INDEX.md
        # stub (regenerated silently; a markerless one would be skipped and reported, which is
        # a separate notice these README tests must not carry), so the only notice this world
        # can produce is the one for the README under test.
        (self.project / 'CLAUDE.md').write_text('# CLAUDE.md\n\nproject notes\n')
        (self.folder / 'INDEX.md').write_text(
            '# index\n\n<!-- AUTO:index-stats -->\nstale\n<!-- /AUTO:index-stats -->\n')

    def register_session(self, session_id):
        """Create <TMPDIR>/<session_id> with the .owner record session-scratch-init.sh writes."""
        session_dir = self.tmp_root / session_id
        session_dir.mkdir()
        (session_dir / '.owner').write_text(json.dumps({'sid': session_id}))
        return session_dir

    def env(self, extra=None):
        environment = {key: value for key, value in os.environ.items() if key not in SCRUBBED_ENV}
        environment.update(
            HOME=str(self.home),
            TMPDIR=str(self.tmp_root),
            CLAUDE_PROJECT_DIR=str(self.project),
            PYTHONDONTWRITEBYTECODE='1',
        )
        environment.update(extra or {})
        return environment

    def payload(self, session_id=None, agent_id=None, target=None):
        payload = {
            'hook_event_name': 'PostToolUse',
            'tool_name': 'Write',
            'tool_input': {'file_path': str(target or self.target)},
        }
        if session_id is not None:
            payload['session_id'] = session_id
        if agent_id is not None:
            payload['agent_id'] = agent_id
        return payload


def run_hook(world, session_id=None, agent_id=None, extra_env=None, preexec_fn=None, target=None):
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(world.payload(session_id, agent_id, target)),
        capture_output=True,
        text=True,
        env=world.env(extra_env),
        cwd=str(world.home),
        timeout=60,
        preexec_fn=preexec_fn,
    )


def limit_file_size():
    """Make regular-file writes fail with EFBIG (errno 27) even for uid 0."""
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    signal.signal(signal.SIGXFSZ, signal.SIG_IGN)


def parse_single_notice(completed):
    """The notice text of a run that printed exactly one PostToolUse JSON object."""
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.count('\n') == 1 and completed.stdout.endswith('\n'), completed.stdout
    output = json.loads(completed.stdout)
    assert set(output) == {'systemMessage', 'hookSpecificOutput'}
    assert set(output['hookSpecificOutput']) == {'hookEventName', 'additionalContext'}
    assert output['hookSpecificOutput']['hookEventName'] == 'PostToolUse'
    assert output['systemMessage'] == output['hookSpecificOutput']['additionalContext']
    return output['systemMessage']


def assert_silent(completed):
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ''


@pytest.mark.parametrize('scenario,status', [
    pytest.param('S3', 'SKIPPED_NO_CLOSING_MARKER', id='emits_S3'),
    pytest.param('S4', 'SKIPPED_NO_OPENING_MARKER', id='emits_S4'),
    pytest.param('S5', 'SKIPPED_NO_CLOSING_MARKER', id='emits_S5'),
    pytest.param('S5b', 'SKIPPED_NO_CLOSING_MARKER', id='emits_S5b'),
    pytest.param('S6', 'SKIPPED_NO_OPENING_MARKER', id='emits_S6'),
])
def test_hook_notice_skip_states_print_one_json_object(tmp_path, scenario, status):
    """Each skip state prints one JSON object naming the README, the status token and a remedy."""
    world = World(tmp_path)
    world.readme.write_text(README_TEXTS[scenario])
    before = world.readme.read_bytes()

    text = parse_single_notice(run_hook(world))

    assert f'({status})' in text
    assert os.path.realpath(world.readme) in text
    assert 'Reason:' in text and 'Action:' in text
    assert OPEN in text
    assert world.readme.read_bytes() == before


def test_hook_notice_closing_marker_reason_covers_a_reversed_pair(tmp_path):
    """A closing marker that precedes the opening marker is described as such, not as absent."""
    world = World(tmp_path)
    world.readme.write_text(README_TEXTS['S5'])

    text = parse_single_notice(run_hook(world))

    assert 'closing marker missing or placed before the opening marker' in text


@pytest.mark.parametrize('scenario', [
    pytest.param('S1', id='silent_S1'),
    pytest.param('S2', id='silent_S2'),
    pytest.param('S7github', id='silent_S7github'),
])
def test_hook_notice_regenerated_or_reserved_paths_stay_silent(tmp_path, scenario):
    """First generation, a well-formed README and the reserved .github tree print nothing."""
    parts = ('.github',) if scenario == 'S7github' else ('sub',)
    world = World(tmp_path, folder_parts=parts)
    if scenario == 'S2':
        world.readme.write_text(README_TEXTS['S2'])

    completed = run_hook(world)

    assert_silent(completed)
    if scenario == 'S1':
        assert OPEN in world.readme.read_text()
    if scenario == 'S7github':
        assert not world.readme.exists()


def test_hook_notice_single_notice_when_dirs_coincide(tmp_path):
    """The parent and the global directory reach the same README: it is reported once."""
    world = World(tmp_path, folder_parts=('.claude', 'commands', 'sub'))
    world.readme.write_text(README_TEXTS['S3'])
    global_commands = world.home / '.claude' / 'commands'
    global_commands.mkdir(parents=True)
    (global_commands / 'README.md').symlink_to(world.readme)

    text = parse_single_notice(run_hook(world))

    # The global branch really ran (it wrote its INDEX.md), yet both READMEs are one file.
    assert (global_commands / 'INDEX.md').exists()
    assert text.count('SKIPPED_NO_CLOSING_MARKER') == 1
    assert text.count(os.path.realpath(world.readme)) == 1


def test_hook_notice_dedupe_same_audience_repeat_silent(tmp_path):
    """The same README state is reported once per session for the main audience."""
    world = World(tmp_path)
    world.readme.write_text(README_TEXTS['S3'])
    world.register_session('sess-a')

    parse_single_notice(run_hook(world, session_id='sess-a'))
    assert_silent(run_hook(world, session_id='sess-a'))


def test_hook_notice_dedupe_same_agent_repeat_silent(tmp_path):
    """The same README state is reported once for the same subagent."""
    world = World(tmp_path)
    world.readme.write_text(README_TEXTS['S3'])
    session_dir = world.register_session('sess-a')

    parse_single_notice(run_hook(world, session_id='sess-a', agent_id='agent-one'))
    assert_silent(run_hook(world, session_id='sess-a', agent_id='agent-one'))

    digest = hashlib.sha256(b'agent-one').hexdigest()[:16]
    assert (session_dir / f'doc-sync-notices-agent-{digest}.json').is_file()


def test_hook_notice_dedupe_other_session_prints(tmp_path):
    """A notice seen in one session does not silence another session."""
    world = World(tmp_path)
    world.readme.write_text(README_TEXTS['S3'])
    world.register_session('sess-a')
    world.register_session('sess-b')

    parse_single_notice(run_hook(world, session_id='sess-a'))
    parse_single_notice(run_hook(world, session_id='sess-b'))


def test_hook_notice_dedupe_other_agent_prints(tmp_path):
    """The orchestrator's notice does not silence a subagent that never saw it."""
    world = World(tmp_path)
    world.readme.write_text(README_TEXTS['S3'])
    session_dir = world.register_session('sess-a')

    parse_single_notice(run_hook(world, session_id='sess-a'))
    parse_single_notice(run_hook(world, session_id='sess-a', agent_id='agent-one'))
    parse_single_notice(run_hook(world, session_id='sess-a', agent_id='agent-two'))

    state_files = sorted(path.name for path in session_dir.glob('doc-sync-notices-*.json'))
    assert len(state_files) == 3
    assert 'doc-sync-notices-main.json' in state_files


def test_hook_notice_dedupe_changed_readme_prints(tmp_path):
    """A README whose bytes changed since the last notice is reported again."""
    world = World(tmp_path)
    world.readme.write_text(README_TEXTS['S3'])
    world.register_session('sess-a')

    parse_single_notice(run_hook(world, session_id='sess-a'))
    assert_silent(run_hook(world, session_id='sess-a'))
    world.readme.write_text(README_TEXTS['S3'] + '\nanother hand-written line\n')
    parse_single_notice(run_hook(world, session_id='sess-a'))
    assert_silent(run_hook(world, session_id='sess-a'))


def test_hook_notice_dedupe_payload_without_session_id_prints(tmp_path):
    """Without a session_id there is nowhere to keep state: every run notifies."""
    world = World(tmp_path)
    world.readme.write_text(README_TEXTS['S3'])

    parse_single_notice(run_hook(world))
    parse_single_notice(run_hook(world))

    assert list(world.tmp_root.iterdir()) == []


def test_hook_notice_dedupe_no_session_dir_prints(tmp_path):
    """A session id whose directory does not exist notifies every time."""
    world = World(tmp_path)
    world.readme.write_text(README_TEXTS['S3'])

    parse_single_notice(run_hook(world, session_id='sess-missing'))
    parse_single_notice(run_hook(world, session_id='sess-missing'))


def test_hook_notice_dedupe_session_dir_without_owner_prints(tmp_path):
    """A directory that lacks the .owner record is not a registered session directory."""
    world = World(tmp_path)
    world.readme.write_text(README_TEXTS['S3'])
    unowned = world.tmp_root / 'sess-unowned'
    unowned.mkdir()

    parse_single_notice(run_hook(world, session_id='sess-unowned'))
    parse_single_notice(run_hook(world, session_id='sess-unowned'))

    assert list(unowned.iterdir()) == []


def test_hook_notice_state_file_lives_in_session_dir(tmp_path):
    """State is one owner-only JSON file inside the registered session directory, nothing else."""
    world = World(tmp_path)
    world.readme.write_text(README_TEXTS['S3'])
    session_dir = world.register_session('sess-a')

    parse_single_notice(run_hook(world, session_id='sess-a'))

    state_file = session_dir / 'doc-sync-notices-main.json'
    key = f'{os.path.realpath(world.readme)}|SKIPPED_NO_CLOSING_MARKER'
    assert json.loads(state_file.read_text()) == {key: hashlib.sha256(world.readme.read_bytes()).hexdigest()}
    assert state_file.stat().st_mode & 0o777 == 0o600
    assert sorted(path.name for path in session_dir.iterdir()) == ['.owner', 'doc-sync-notices-main.json']
    assert [path.name for path in world.tmp_root.iterdir()] == ['sess-a']


def test_hook_notice_state_dir_never_created(tmp_path):
    """The hook never creates a session directory, not even for a hostile session id."""
    world = World(tmp_path)
    world.readme.write_text(README_TEXTS['S3'])

    for session_id in ('sess-new', '../escape', '..', '.'):
        parse_single_notice(run_hook(world, session_id=session_id))

    assert list(world.tmp_root.iterdir()) == []
    assert not (world.root / 'escape').exists()


def test_hook_notice_state_path_session_id_traversal_prints(tmp_path):
    """A session id that climbs to an existing registered directory gets no state file there."""
    world = World(tmp_path)
    world.readme.write_text(README_TEXTS['S3'])
    sibling = world.root / 'sibling'
    sibling.mkdir()
    (sibling / '.owner').write_text(json.dumps({'sid': 'sibling'}))
    # Path arithmetic alone reaches a valid registered directory, so only the id guard stops it.
    assert (world.tmp_root / '..' / 'sibling' / '.owner').is_file()

    parse_single_notice(run_hook(world, session_id='../sibling'))
    parse_single_notice(run_hook(world, session_id='../sibling'))

    assert [path.name for path in sibling.iterdir()] == ['.owner']


def test_hook_notice_state_path_symlinked_session_dir_prints(tmp_path):
    """A session directory that is a symlink to a registered one gets no state file."""
    world = World(tmp_path)
    world.readme.write_text(README_TEXTS['S3'])
    target = world.register_session('sess-real')
    (world.tmp_root / 'sess-link').symlink_to(target, target_is_directory=True)
    assert (world.tmp_root / 'sess-link' / '.owner').is_file()

    parse_single_notice(run_hook(world, session_id='sess-link'))
    parse_single_notice(run_hook(world, session_id='sess-link'))

    assert [path.name for path in target.iterdir()] == ['.owner']


@pytest.mark.parametrize('content', [
    pytest.param('{not json', id='invalid_json'),
    pytest.param('[1, 2, 3]', id='wrong_type'),
])
def test_hook_notice_state_file_corrupt_prints(tmp_path, content):
    """Corrupt or wrong-typed state counts as empty: the notice is printed and the state heals."""
    world = World(tmp_path)
    world.readme.write_text(README_TEXTS['S3'])
    session_dir = world.register_session('sess-a')
    state_file = session_dir / 'doc-sync-notices-main.json'
    state_file.write_text(content)

    parse_single_notice(run_hook(world, session_id='sess-a'))

    assert isinstance(json.loads(state_file.read_text()), dict)
    assert_silent(run_hook(world, session_id='sess-a'))


def test_hook_notice_state_file_deeply_nested_prints(tmp_path):
    """A state file that makes the JSON parser raise RecursionError still notifies and heals."""
    world = World(tmp_path)
    world.readme.write_text(README_TEXTS['S3'])
    session_dir = world.register_session('sess-a')
    state_file = session_dir / 'doc-sync-notices-main.json'
    depth = 20000
    state_file.write_text('[' * depth + ']' * depth)

    parse_single_notice(run_hook(world, session_id='sess-a'))

    key = f'{os.path.realpath(world.readme)}|SKIPPED_NO_CLOSING_MARKER'
    assert json.loads(state_file.read_text()) == {key: hashlib.sha256(world.readme.read_bytes()).hexdigest()}
    assert_silent(run_hook(world, session_id='sess-a'))


def test_hook_notice_readme_digest_failure_means_notify(tmp_path):
    """Any failure to hash a README, not only an OSError, gives no digest, and no digest always notifies."""
    notice_module = importlib.import_module('hooks.doc_sync.notice')
    readme = tmp_path / 'README.md'
    readme.write_text(README_TEXTS['S3'])

    assert notice_module._readme_digest(str(readme)) == hashlib.sha256(readme.read_bytes()).hexdigest()
    assert notice_module._readme_digest(str(tmp_path / 'missing.md')) is None
    assert notice_module._readme_digest('embedded\0nul') is None


def test_hook_notice_state_path_is_directory_prints(tmp_path):
    """Reading and replacing a state path that is a directory both fail: notify, exit 0."""
    world = World(tmp_path)
    world.readme.write_text(README_TEXTS['S3'])
    session_dir = world.register_session('sess-a')
    (session_dir / 'doc-sync-notices-main.json').mkdir()

    parse_single_notice(run_hook(world, session_id='sess-a'))
    parse_single_notice(run_hook(world, session_id='sess-a'))

    assert (session_dir / 'doc-sync-notices-main.json').is_dir()
    assert sorted(path.name for path in session_dir.iterdir()) == ['.owner', 'doc-sync-notices-main.json']


def test_hook_notice_state_write_failure_fsize_limit_prints(tmp_path):
    """A state write that fails with EFBIG still prints the notice (state root through the seam)."""
    seam = lambda world: {STATE_ROOT_SEAM: str(world.tmp_root)}  # noqa: E731
    control = World(tmp_path / 'control')
    control.readme.write_text(README_TEXTS['S3'])
    control_session = control.register_session('sess-a')
    limited = World(tmp_path / 'limited')
    limited.readme.write_text(README_TEXTS['S3'])
    limited_session = limited.register_session('sess-a')

    # Control: same fixture, no limit. Resolution, the .owner check and the write all succeed.
    parse_single_notice(run_hook(control, session_id='sess-a', extra_env=seam(control)))
    assert (control_session / 'doc-sync-notices-main.json').is_file()

    # Limited: the write step fails, the notice is still printed, and nothing was recorded.
    text = parse_single_notice(
        run_hook(limited, session_id='sess-a', extra_env=seam(limited), preexec_fn=limit_file_size))
    assert 'SKIPPED_NO_CLOSING_MARKER' in text
    assert [path.name for path in limited_session.iterdir()] == ['.owner']


def test_hook_notice_state_write_step_raises_efbig(tmp_path):
    """The state-write function itself raises OSError(EFBIG) under the limit and succeeds without."""
    snippet = (
        'import errno, sys\n'
        'sys.path.insert(0, sys.argv[1])\n'
        'from hooks.doc_sync import notice\n'
        'try:\n'
        '    notice.write_state(sys.argv[2], {"key": "value"})\n'
        'except OSError as error:\n'
        '    print(error.errno)\n'
        'else:\n'
        '    print("written")\n'
    )
    environment = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
    limited_dir = tmp_path / 'limited'
    control_dir = tmp_path / 'control'
    limited_dir.mkdir()
    control_dir.mkdir()

    def run(directory, preexec_fn):
        return subprocess.run(
            [sys.executable, '-c', snippet, str(REPO_ROOT), str(directory / 'state.json')],
            capture_output=True, text=True, env=environment, cwd=str(tmp_path), timeout=60,
            preexec_fn=preexec_fn)

    control = run(control_dir, None)
    limited = run(limited_dir, limit_file_size)

    assert control.stdout.strip() == 'written', control.stderr
    assert (control_dir / 'state.json').is_file()
    assert limited.stdout.strip() == str(errno.EFBIG), limited.stderr
    assert list(limited_dir.iterdir()) == []


def test_hook_notice_tempdir_resolution_raises_prints(tmp_path):
    """tempfile.gettempdir() raises under the limit; with the seam unset the notice still prints."""
    world = World(tmp_path)
    world.readme.write_text(README_TEXTS['S3'])
    session_dir = world.register_session('sess-a')
    probe = subprocess.run(
        [sys.executable, '-c',
         'import tempfile\n'
         'try:\n'
         '    tempfile.gettempdir()\n'
         'except Exception as error:\n'
         '    print(type(error).__name__)\n'],
        capture_output=True, text=True, env=world.env(), cwd=str(world.home), timeout=60,
        preexec_fn=limit_file_size)
    assert probe.stdout.strip() == 'FileNotFoundError', probe.stderr

    text = parse_single_notice(run_hook(world, session_id='sess-a', preexec_fn=limit_file_size))

    assert 'SKIPPED_NO_CLOSING_MARKER' in text
    assert [path.name for path in session_dir.iterdir()] == ['.owner']


def test_hook_notice_tmpdir_missing_prints(tmp_path):
    """TMPDIR pointing at a missing path falls back to /tmp: no session directory, notify."""
    world = World(tmp_path)
    world.readme.write_text(README_TEXTS['S3'])
    session_id = f'sess-{uuid.uuid4().hex}'
    missing = tmp_path / 'does-not-exist'

    parse_single_notice(run_hook(world, session_id=session_id, extra_env={'TMPDIR': str(missing)}))
    parse_single_notice(run_hook(world, session_id=session_id, extra_env={'TMPDIR': str(missing)}))

    assert not missing.exists()
    assert not (Path('/tmp') / session_id).exists()


def test_hook_notice_notice_length_under_cap(tmp_path):
    """A very long README path cannot push the notice past the length cap."""
    world = World(tmp_path, folder_parts=tuple(f'{index}' + 'd' * 199 for index in range(9)))
    world.readme.write_text(README_TEXTS['S3'])
    assert len(os.path.realpath(world.readme)) > NOTICE_CAP - 400

    text = parse_single_notice(run_hook(world))

    assert len(text) <= NOTICE_CAP
    assert text.startswith('doc-sync: README not regenerated (SKIPPED_NO_CLOSING_MARKER)')


class FailingStream:
    """A stdout stand-in whose writes fail the way a closed pipe or a bad encoding would."""

    def __init__(self, error):
        self.error = error
        self.write_attempts = 0

    def write(self, text):
        self.write_attempts += 1
        raise self.error

    def flush(self):
        raise self.error


def run_main_in_process(monkeypatch, world, stdout=None):
    monkeypatch.setenv('HOME', str(world.home))
    monkeypatch.setenv('TMPDIR', str(world.tmp_root))
    monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(world.project))
    for name in ('CLAUDE_DOC_SYNC_ROOTS', STATE_ROOT_SEAM):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(world.payload())))
    if stdout is not None:
        monkeypatch.setattr(sys, 'stdout', stdout)
    with pytest.raises(SystemExit) as exit_info:
        main_module.main()
    return exit_info.value.code


def raise_runtime_error(*args, **kwargs):
    raise RuntimeError('simulated failure after the README was reported')


@pytest.mark.parametrize('failing_step', [
    pytest.param('patch_claude_md', id='patch_claude_md_raises'),
    pytest.param('_maybe_regen_global', id='global_regen_raises'),
])
def test_emission_robust_notices_survive_later_exception(tmp_path, monkeypatch, capsys, failing_step):
    """A skip collected before a later step raises is still printed, and the exit code stays 0."""
    world = World(tmp_path, folder_parts=('.claude', 'commands', 'sub'))
    world.readme.write_text(README_TEXTS['S3'])
    monkeypatch.setattr(main_module, failing_step, raise_runtime_error)

    code = run_main_in_process(monkeypatch, world)

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert os.path.realpath(world.readme) in output['systemMessage']


@pytest.mark.parametrize('variant', ['fake_stream', 'closed_pipe'])
def test_emission_robust_broken_pipe_exit_zero(tmp_path, monkeypatch, variant):
    """A broken stdout must not turn into a non-zero exit code of the hook."""
    world = World(tmp_path)
    world.readme.write_text(README_TEXTS['S3'])
    if variant == 'fake_stream':
        stream = FailingStream(BrokenPipeError(errno.EPIPE, 'Broken pipe'))
        assert run_main_in_process(monkeypatch, world, stdout=stream) == 0
        assert stream.write_attempts >= 1
        return
    read_end, write_end = os.pipe()
    os.close(read_end)
    try:
        completed = subprocess.run(
            [sys.executable, str(HOOK)],
            input=json.dumps(world.payload()),
            stdout=write_end,
            stderr=subprocess.PIPE,
            text=True,
            env=world.env(),
            cwd=str(world.home),
            timeout=60,
        )
    finally:
        os.close(write_end)
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize('variant', ['fake_stream_raises', 'ascii_only_output'])
def test_emission_robust_encoding_error_exit_zero(tmp_path, monkeypatch, variant):
    """An encoding problem on stdout cannot fail the hook; non-ASCII paths are escaped up front."""
    if variant == 'fake_stream_raises':
        world = World(tmp_path)
        world.readme.write_text(README_TEXTS['S3'])
        stream = FailingStream(UnicodeEncodeError('ascii', 'é', 0, 1, 'ordinal not in range(128)'))
        assert run_main_in_process(monkeypatch, world, stdout=stream) == 0
        assert stream.write_attempts >= 1
        return
    world = World(tmp_path, folder_parts=('dossier-é',))
    world.readme.write_text(README_TEXTS['S3'])

    completed = run_hook(world, extra_env={'PYTHONIOENCODING': 'ascii:strict'})

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.isascii()
    assert 'dossier-é' in json.loads(completed.stdout)['systemMessage']
