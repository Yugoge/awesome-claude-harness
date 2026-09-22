#!/usr/bin/env python3
"""Notice tests for skipped INDEX, README and CLAUDE.md-section regeneration.

Backlog #85: the INDEX regeneration path and the CLAUDE.md section patcher now report what
they skipped through the same one-JSON-object channel the README notice (#83) uses, with the
same per-audience, per-state dedupe. Three groups:

  hook_chain  posttool-doc-sync.py run exactly as the harness runs it (a subprocess fed a JSON
              payload on stdin), for every skip shape, the dedupe and state-failure cases and
              the length cap.
  notice_unit hooks.doc_sync.notice called in-process: kinds x statuses x shapes, legacy
              tuples, hostile records, the cap policy.
  relay_line  hooks/userprompt-doc-sync-check.py and the line it prints per resynced directory.

Isolation: every run gets a temporary HOME and TMPDIR, CLAUDE_PROJECT_DIR points at a synthetic
project under tmp_path, and the parent CLAUDE_PROJECT_DIR, CLAUDE_DOC_SYNC_ROOTS and
CLAUDE_DOC_SYNC_STATE_ROOT are scrubbed. Nothing here regenerates anything inside the
repository tree. Unwritable state is simulated with conditions that hold for every user (uid 0
included): a directory where the state file should be, invalid JSON, a missing session
directory, and regular-file writes that fail with EFBIG through RLIMIT_FSIZE, with the state
root resolved through the documented CLAUDE_DOC_SYNC_STATE_ROOT seam.

New symbols are reached through load() inside the test bodies, never through a module-level
from-import.
"""

import importlib
import importlib.util
import json
import os
import re
import resource
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / 'hooks' / 'posttool-doc-sync.py'
RELAY_HOOK = REPO_ROOT / 'hooks' / 'userprompt-doc-sync-check.py'
DOC_SYNC_PACKAGE = REPO_ROOT / 'hooks' / 'doc_sync'
sys.path.insert(0, str(REPO_ROOT))

SCRUBBED_ENV = ('CLAUDE_PROJECT_DIR', 'CLAUDE_DOC_SYNC_ROOTS', 'CLAUDE_DOC_SYNC_STATE_ROOT')
STATE_ROOT_SEAM = 'CLAUDE_DOC_SYNC_STATE_ROOT'
NOTICE_CAP = 2000

IO = '<!-- AUTO:index-stats -->'
IC = '<!-- /AUTO:index-stats -->'
RO = '<!-- AUTO:readme-stats -->'
RC = '<!-- /AUTO:readme-stats -->'
# A section pair the patcher regenerates to the very same bytes (no .claude/commands directory):
# it satisfies the top-level candidate guard (`<!-- AUTO:` anywhere) without changing the file.
CLAUDE_GUARD = '<!-- AUTO:command-list -->\n\n<!-- /AUTO:command-list -->\n\n'
CLAUDE_HEAD = '# CLAUDE.md\n\n> Project-specific settings for demo\n\n'


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    """HOME and TMPDIR of the in-process cases; the subprocess cases get their own through World."""
    home = tmp_path / 'inproc-home'
    scratch_tmp = tmp_path / 'inproc-tmp'
    home.mkdir()
    scratch_tmp.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('TMPDIR', str(scratch_tmp))
    for name in SCRUBBED_ENV:
        monkeypatch.delenv(name, raising=False)


def load(name):
    """hooks.doc_sync.<name>; a module that cannot be imported fails the calling test."""
    try:
        return importlib.import_module(f'hooks.doc_sync.{name}')
    except ImportError as error:
        pytest.fail(f'hooks.doc_sync.{name} cannot be imported: {error}')


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
        self.index = self.folder / 'INDEX.md'
        self.claude_md = self.project / 'CLAUDE.md'
        # No AUTO region in CLAUDE.md, no README and no INDEX: the hook writes only what a
        # test asks for, and prints nothing until a test plants a skip shape.
        self.claude_md.write_text('# CLAUDE.md\n\nproject notes\n')

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

    def payload(self, session_id=None, agent_id=None):
        payload = {
            'hook_event_name': 'PostToolUse',
            'tool_name': 'Write',
            'tool_input': {'file_path': str(self.target)},
        }
        if session_id is not None:
            payload['session_id'] = session_id
        if agent_id is not None:
            payload['agent_id'] = agent_id
        return payload


def run_hook(world, session_id=None, agent_id=None, extra_env=None, preexec_fn=None):
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(world.payload(session_id, agent_id)),
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


INDEX_SHAPE_ROWS = [
    ('hc_index_no_marker', '# sub\n\nhand written\n', 'SKIPPED_NO_OPENING_MARKER', None),
    ('hc_index_only_open', f'# sub\n\n{IO}\nstale\n', 'SKIPPED_NO_CLOSING_MARKER', None),
    ('hc_index_only_close', f'# sub\n\n{IC}\n', 'SKIPPED_NO_OPENING_MARKER', None),
    ('hc_index_reversed', f'{IC}\nmiddle\n{IO}\nstale\n', 'SKIPPED_NO_CLOSING_MARKER', None),
    ('hc_index_duplicate_open', f'{IO}\nx\n{IO}\ny\n{IC}\n', 'SKIPPED_MALFORMED_MARKERS', 'DUPLICATE_OPENING'),
    ('hc_index_duplicate_close', f'{IO}\nx\n{IC}\n{IC}\n', 'SKIPPED_MALFORMED_MARKERS', 'DUPLICATE_CLOSING'),
    ('hc_index_multiple_regions', f'{IO}\na\n{IC}\nm\n{IO}\nb\n{IC}\n', 'SKIPPED_MALFORMED_MARKERS', 'MULTIPLE_REGIONS'),
    ('hc_index_nested', f'{IO}\n{IO}\nn\n{IC}\n{IC}\n', 'SKIPPED_MALFORMED_MARKERS', 'NESTED_REGIONS'),
    ('hc_index_near_miss', '# sub\n<!--AUTO:index-stats-->\nstale\n', 'SKIPPED_MALFORMED_MARKERS', 'NEAR_MISS_MARKER'),
    ('hc_index_foreign_inside', f'{IO}\n<!-- AUTO:other -->\nx\n<!-- /AUTO:other -->\n{IC}\n',
     'SKIPPED_MALFORMED_MARKERS', 'FOREIGN_MARKER_INSIDE'),
    ('hc_index_unclosed_fence', f'# sub\n```\n{IO}\nstale\n{IC}\n', 'SKIPPED_MALFORMED_MARKERS', 'UNCLOSED_FENCE'),
]


@pytest.mark.parametrize('text,status,shape', [
    pytest.param(text, status, shape, id=token) for token, text, status, shape in INDEX_SHAPE_ROWS])
def test_hook_chain_index_skip_prints_one_json_object(tmp_path, text, status, shape):
    """Every INDEX skip shape prints one JSON object naming the INDEX, the status, the shape and an action."""
    world = World(tmp_path)
    world.index.write_text(text)
    before = world.index.read_bytes()

    notice = parse_single_notice(run_hook(world))

    assert notice.startswith('doc-sync: INDEX not regenerated (' + status + ')')
    assert f'INDEX: {os.path.realpath(world.index)}' in notice
    assert 'Reason:' in notice and 'Action:' in notice
    if shape is not None:
        assert shape in notice
    if shape == 'UNCLOSED_FENCE':
        assert 'close the code fence that starts at line 2' in notice
    assert 'README' not in notice
    assert world.index.read_bytes() == before


def test_hook_chain_hc_silent_wellformed_index(tmp_path):
    """A well-formed INDEX is regenerated without a word."""
    world = World(tmp_path)
    world.index.write_text(f'# sub\n\n{IO}\nstale\n{IC}\n')

    assert_silent(run_hook(world))

    assert 'stale' not in world.index.read_text() and 'tool.py' in world.index.read_text()


def test_hook_chain_hc_silent_github_reserved(tmp_path):
    """The reserved .github tree is never regenerated and never reported."""
    world = World(tmp_path, folder_parts=('.github',))
    world.index.write_text('# hand written\n')

    assert_silent(run_hook(world))

    assert world.index.read_text() == '# hand written\n'
    assert not world.readme.exists()


def test_hook_chain_hc_silent_new_index(tmp_path):
    """A directory without INDEX (or README) gets both, first generation, silently."""
    world = World(tmp_path)

    assert_silent(run_hook(world))

    assert IO in world.index.read_text() and IC in world.index.read_text()
    assert RO in world.readme.read_text()


def test_hook_chain_hc_readme_and_index_one_object(tmp_path):
    """A README skip and an INDEX skip of one invocation share one JSON object, README first."""
    world = World(tmp_path)
    world.readme.write_text(f'# sub\n\n{RO}\nstale without a terminator\n')
    world.index.write_text('# sub\n\nhand written\n')

    notice = parse_single_notice(run_hook(world))

    lines = notice.split('\n')
    assert len(lines) == 2
    assert lines[0].startswith('doc-sync: README not regenerated (SKIPPED_NO_CLOSING_MARKER)')
    assert lines[1].startswith('doc-sync: INDEX not regenerated (SKIPPED_NO_OPENING_MARKER)')
    assert os.path.realpath(world.readme) in lines[0] and os.path.realpath(world.index) in lines[1]


def test_hook_chain_hc_claude_section_notice(tmp_path):
    """A CLAUDE.md section the classifier refuses is reported (the fallback shape: a near miss)."""
    world = World(tmp_path)
    text = CLAUDE_HEAD + CLAUDE_GUARD + '<!--AUTO:last-updated-->\nold\n<!-- /AUTO:last-updated -->\n'
    world.claude_md.write_text(text)

    notice = parse_single_notice(run_hook(world))

    assert notice.startswith('doc-sync: CLAUDE.md section not regenerated (SKIPPED_MALFORMED_MARKERS)')
    assert 'NEAR_MISS_MARKER' in notice and 'Action:' in notice
    assert f'CLAUDE.md: {os.path.realpath(world.claude_md)} section: last-updated' in notice
    assert world.claude_md.read_text() == text


def test_hook_chain_hc_single_json_object_exit_zero(tmp_path):
    """README, INDEX and section skips together still print exactly one object and exit 0."""
    world = World(tmp_path)
    world.readme.write_text(f'# sub\n\n{RO}\nstale\n')
    world.index.write_text(f'{IO}\nx\n{IO}\ny\n{IC}\n')
    world.claude_md.write_text(CLAUDE_HEAD + CLAUDE_GUARD + f'<!-- /AUTO:agent-list -->\n')

    completed = run_hook(world)
    notice = parse_single_notice(completed)

    assert completed.returncode == 0
    assert [line.split(' not regenerated')[0] for line in notice.split('\n')] == [
        'doc-sync: README', 'doc-sync: INDEX', 'doc-sync: CLAUDE.md section']


def test_hook_chain_hc_dedupe_second_call_silent(tmp_path):
    """The same INDEX state is reported once per session for the main audience, and once per agent."""
    world = World(tmp_path)
    world.index.write_text('# sub\n\nhand written\n')
    world.register_session('sess-a')

    parse_single_notice(run_hook(world, session_id='sess-a'))
    assert_silent(run_hook(world, session_id='sess-a'))
    # A subagent never saw the notice its parent received.
    parse_single_notice(run_hook(world, session_id='sess-a', agent_id='agent-one'))
    assert_silent(run_hook(world, session_id='sess-a', agent_id='agent-one'))


def test_hook_chain_hc_dedupe_changed_bytes_notifies(tmp_path):
    """An INDEX whose bytes changed since the last notice is reported again."""
    world = World(tmp_path)
    world.index.write_text('# sub\n\nhand written\n')
    world.register_session('sess-a')

    parse_single_notice(run_hook(world, session_id='sess-a'))
    assert_silent(run_hook(world, session_id='sess-a'))
    world.index.write_text('# sub\n\nhand written, then edited\n')
    parse_single_notice(run_hook(world, session_id='sess-a'))
    assert_silent(run_hook(world, session_id='sess-a'))


def test_hook_chain_hc_state_file_corrupt_notifies(tmp_path):
    """Corrupt state counts as empty: the notice is printed and the state heals."""
    world = World(tmp_path)
    world.index.write_text('# sub\n\nhand written\n')
    session_dir = world.register_session('sess-a')
    state_file = session_dir / 'doc-sync-notices-main.json'
    state_file.write_text('{not json')

    parse_single_notice(run_hook(world, session_id='sess-a'))

    key = f'{os.path.realpath(world.index)}|SKIPPED_NO_OPENING_MARKER'
    assert list(json.loads(state_file.read_text())) == [key]
    assert_silent(run_hook(world, session_id='sess-a'))


def test_hook_chain_hc_state_path_is_directory_notifies(tmp_path):
    """A directory where the state file should be: every run notifies, exit 0."""
    world = World(tmp_path)
    world.index.write_text('# sub\n\nhand written\n')
    session_dir = world.register_session('sess-a')
    (session_dir / 'doc-sync-notices-main.json').mkdir()

    parse_single_notice(run_hook(world, session_id='sess-a'))
    parse_single_notice(run_hook(world, session_id='sess-a'))

    assert (session_dir / 'doc-sync-notices-main.json').is_dir()


def test_hook_chain_hc_no_session_id_notifies(tmp_path):
    """Without a session id there is nowhere to keep state: every run notifies."""
    world = World(tmp_path)
    world.index.write_text('# sub\n\nhand written\n')

    parse_single_notice(run_hook(world))
    parse_single_notice(run_hook(world))

    assert list(world.tmp_root.iterdir()) == []


def test_hook_chain_hc_no_session_dir_notifies(tmp_path):
    """A session id whose directory does not exist notifies every time."""
    world = World(tmp_path)
    world.index.write_text('# sub\n\nhand written\n')

    parse_single_notice(run_hook(world, session_id='sess-missing'))
    parse_single_notice(run_hook(world, session_id='sess-missing'))

    assert list(world.tmp_root.iterdir()) == []


def test_hook_chain_hc_fsize_index_write_fails_readme_notice_survives(tmp_path):
    """An INDEX write that fails (EFBIG) after a README skip was recorded must not lose that notice."""
    seam = lambda world: {STATE_ROOT_SEAM: str(world.tmp_root)}  # noqa: E731
    outcomes = {}
    for name, preexec in (('control', None), ('limited', limit_file_size)):
        world = World(tmp_path / name)
        world.readme.write_text(f'# sub\n\n{RO}\nstale without a terminator\n')
        world.index.write_text(f'# sub\n\n{IO}\nstale\n{IC}\n')
        world.register_session('sess-a')
        outcomes[name] = parse_single_notice(
            run_hook(world, session_id='sess-a', extra_env=seam(world), preexec_fn=preexec))
    for notice in outcomes.values():
        assert notice.startswith('doc-sync: README not regenerated (SKIPPED_NO_CLOSING_MARKER)')
    assert outcomes['control'] == outcomes['limited'].replace(str(tmp_path / 'limited'), str(tmp_path / 'control'))


def long_world(tmp_path):
    """A world whose paths are long enough that five entries cannot fit the notice cap."""
    world = World(tmp_path / ('r' * 90), folder_parts=('f' * 60,))
    world.readme.write_text(f'# sub\n\n{RO}\nstale\n')
    world.index.write_text('# sub\n\nhand written\n')
    sections = ''.join(f'<!-- AUTO:{name} -->\nx\n<!-- AUTO:{name} -->\n<!-- /AUTO:{name} -->\n\n'
                       for name in ('claude-inventory', 'agent-list', 'skill-list', 'last-updated'))
    world.claude_md.write_text(CLAUDE_HEAD + CLAUDE_GUARD + sections)
    world.register_session('sess-a')
    return world


def entry_id(line):
    if line.startswith('doc-sync: README'):
        return 'README'
    if line.startswith('doc-sync: INDEX'):
        return 'INDEX'
    if line.startswith('doc-sync: CLAUDE.md section'):
        return 'section:' + re.search(r'section: (\S+)$', line).group(1)
    return None


def state_entry_ids(world):
    keys = json.loads((world.tmp_root / 'sess-a' / 'doc-sync-notices-main.json').read_text())
    ids = set()
    for key in keys:
        path, status, *marker = key.split('|')
        ids.add('README' if path.endswith('README.md') else 'INDEX' if path.endswith('INDEX.md')
                else 'section:' + marker[0])
    return ids


ALL_ENTRIES = {'README', 'INDEX', 'section:claude-inventory', 'section:agent-list', 'section:skill-list',
               'section:last-updated'}


def test_hook_chain_hc_cap_printed_equals_recorded(tmp_path):
    """The set of entries printed equals the set recorded as seen in the state file."""
    world = long_world(tmp_path)

    notice = parse_single_notice(run_hook(world, session_id='sess-a'))

    printed = {entry_id(line) for line in notice.split('\n')} - {None}
    assert len(notice) <= NOTICE_CAP
    assert 0 < len(printed) < len(ALL_ENTRIES)
    assert printed == state_entry_ids(world)
    assert 'more notice(s) not shown' in notice.split('\n')[-1]


def test_hook_chain_hc_cap_unprinted_appear_next_call(tmp_path):
    """Every entry the cap held back is printed by a later call, and none is printed twice."""
    world = long_world(tmp_path)
    seen = []

    for _ in range(len(ALL_ENTRIES) + 1):
        completed = run_hook(world, session_id='sess-a')
        if completed.stdout == '':
            break
        notice = parse_single_notice(completed)
        seen.extend(entry for entry in (entry_id(line) for line in notice.split('\n')) if entry)
    else:
        pytest.fail('the notice never became silent')

    assert sorted(seen) == sorted(ALL_ENTRIES)
    assert state_entry_ids(world) == ALL_ENTRIES


def test_hook_chain_hc_cap_never_recorded_unshown(tmp_path):
    """After the first call no state key exists for an entry that was not shown."""
    world = long_world(tmp_path)

    notice = parse_single_notice(run_hook(world, session_id='sess-a'))

    printed = {entry_id(line) for line in notice.split('\n')} - {None}
    recorded = state_entry_ids(world)
    assert recorded <= printed
    assert not (ALL_ENTRIES - printed) & recorded
    # The held-back entries are still unseen: the next call prints (only) them.
    second = parse_single_notice(run_hook(world, session_id='sess-a'))
    second_printed = {entry_id(line) for line in second.split('\n')} - {None}
    assert second_printed and second_printed.isdisjoint(printed)


def record(kind, path, status, marker_id=None, shape=None, detail=None):
    regions = load('regions')
    return regions.RegenRecord(regions.ArtifactKind[kind], path, regions.RegenStatus[status],
                               marker_id, None if shape is None else regions.RegionShape[shape], detail)


MALFORMED_SHAPES = ['DUPLICATE_OPENING', 'DUPLICATE_CLOSING', 'MULTIPLE_REGIONS', 'NESTED_REGIONS',
                    'FOREIGN_MARKER_INSIDE', 'NEAR_MISS_MARKER', 'UNCLOSED_FENCE', 'BODY_CONTAINS_MARKER',
                    'BODY_BREAKS_REGION']
NOTIFYING = ['SKIPPED_NO_OPENING_MARKER', 'SKIPPED_NO_CLOSING_MARKER', 'SKIPPED_MALFORMED_MARKERS']


def test_notice_unit_nu_exhaustive_kind_status_shape():
    """Every artifact kind x notifying status x shape yields a text, without raising."""
    regions = load('regions')
    notice = load('notice')
    count = 0
    for kind in ('README', 'INDEX', 'CLAUDE_MD_SECTION'):
        marker_id = 'last-updated' if kind == 'CLAUDE_MD_SECTION' else None
        for status in NOTIFYING:
            shapes = MALFORMED_SHAPES if status == 'SKIPPED_MALFORMED_MARKERS' else [None, 'REVERSED', 'ONLY_OPENING']
            for shape in shapes:
                entry = record(kind, '/x/artifact.md', status, marker_id, shape, '4')
                text = notice.build_notice_text(notice.notifiable([entry]))
                count += 1
                assert f'({status})' in text and '/x/artifact.md' in text, (kind, status, shape)
                assert 'Reason:' in text and 'Action:' in text
                if shape in MALFORMED_SHAPES:
                    assert shape in text
                if kind == 'CLAUDE_MD_SECTION':
                    assert text.endswith('section: last-updated')
                assert regions.ArtifactKind[kind].name  # kind stays a member
    assert count == 3 * (3 + 9 + 3)


def test_notice_unit_nu_legacy_two_tuple_accepted(capsys):
    """A legacy (path, status) pair is a README record and prints the README notice."""
    regions = load('regions')
    notice = load('notice')

    notice.emit_post_tool_notice([('/legacy/README.md', regions.RegenStatus.SKIPPED_NO_CLOSING_MARKER)], {})

    output = json.loads(capsys.readouterr().out)
    assert output['systemMessage'].startswith('doc-sync: README not regenerated (SKIPPED_NO_CLOSING_MARKER)')
    assert output['systemMessage'].endswith('README: /legacy/README.md')


def test_notice_unit_nu_bad_record_does_not_silence_rest(capsys):
    """Hostile or half-built records are dropped one by one; a good record still prints."""
    regions = load('regions')
    notice = load('notice')
    good = record('INDEX', '/good/INDEX.md', 'SKIPPED_NO_OPENING_MARKER')
    hostile = [
        None, 42, 'text', ('only-one',), ('a', 'b', 'c'), object(),
        regions.RegenRecord(regions.ArtifactKind.README, None, regions.RegenStatus.SKIPPED_NO_OPENING_MARKER),
        regions.RegenRecord('bogus', '/x', regions.RegenStatus.SKIPPED_NO_OPENING_MARKER),
        regions.RegenRecord(regions.ArtifactKind.README, '/x/README.md', 'not-a-status'),
        record('CLAUDE_MD_SECTION', '/x/CLAUDE.md', 'SKIPPED_NO_OPENING_MARKER'),
        record('README', '/x/README.md', 'SKIPPED_MALFORMED_MARKERS'),
        ('/x/README.md', None),
    ]

    notice.emit_post_tool_notice(hostile + [good], {})

    output = json.loads(capsys.readouterr().out)
    assert output['systemMessage'].startswith('doc-sync: INDEX not regenerated (SKIPPED_NO_OPENING_MARKER)')
    assert output['systemMessage'].count('doc-sync:') == 1


def test_notice_unit_nu_readme_text_byte_identical_to_baseline():
    """A README entry keeps the exact text the #83 template produced."""
    notice = load('notice')
    opening = ('doc-sync: README not regenerated (SKIPPED_NO_OPENING_MARKER). Reason: opening marker '
               '<!-- AUTO:readme-stats --> not found, so the README is treated as hand-written and left '
               'untouched. Action: add <!-- AUTO:readme-stats --> and <!-- /AUTO:readme-stats --> to let '
               'doc-sync manage its stats section, or ignore this notice if the README is meant to stay '
               'hand-written. README: /x/README.md')
    closing = ('doc-sync: README not regenerated (SKIPPED_NO_CLOSING_MARKER). Reason: closing marker missing '
               'or placed before the opening marker, so the README was left untouched. Action: place '
               '<!-- /AUTO:readme-stats --> after <!-- AUTO:readme-stats --> so the stats section can be '
               'regenerated. README: /x/README.md')

    assert notice.build_notice_text(notice.notifiable([('/x/README.md', load('regions').RegenStatus.SKIPPED_NO_OPENING_MARKER)])) == opening
    assert notice.build_notice_text(notice.notifiable([('/x/README.md', load('regions').RegenStatus.SKIPPED_NO_CLOSING_MARKER)])) == closing


def test_notice_unit_nu_index_text_prefix_pinned():
    """An INDEX entry opens with the pinned prefix, which is also the relay hook's constant."""
    notice = load('notice')
    assert notice.INDEX_NOTICE_PREFIX == 'doc-sync: INDEX not regenerated'
    for status in NOTIFYING:
        text = notice.build_notice_text(notice.notifiable(
            [record('INDEX', '/x/INDEX.md', status, None, 'DUPLICATE_OPENING')]))
        assert text.startswith(f'{notice.INDEX_NOTICE_PREFIX} ({status}). Reason: ')
        assert text.endswith('. INDEX: /x/INDEX.md')


def register_state(tmp_path, monkeypatch):
    """A registered session directory reachable through the documented state-root seam."""
    root = tmp_path / 'state-root'
    session_dir = root / 'sess-u'
    session_dir.mkdir(parents=True)
    (session_dir / '.owner').write_text('{}')
    monkeypatch.setenv(STATE_ROOT_SEAM, str(root))
    return session_dir / 'doc-sync-notices-main.json', {'session_id': 'sess-u'}


def test_notice_unit_nu_claude_section_key_includes_marker_id(tmp_path, monkeypatch, capsys):
    """The CLAUDE.md state key appends the marker id: one file, one key per section."""
    notice = load('notice')
    state_file, payload = register_state(tmp_path, monkeypatch)
    claude_md = tmp_path / 'CLAUDE.md'
    claude_md.write_text('# c\n')
    entries = [record('CLAUDE_MD_SECTION', str(claude_md), 'SKIPPED_MALFORMED_MARKERS', name, 'NEAR_MISS_MARKER')
               for name in ('agent-list', 'skill-list')]

    notice.emit_post_tool_notice(entries, payload)
    capsys.readouterr()

    real = os.path.realpath(claude_md)
    assert sorted(json.loads(state_file.read_text())) == [
        f'{real}|SKIPPED_MALFORMED_MARKERS|agent-list', f'{real}|SKIPPED_MALFORMED_MARKERS|skill-list']


def test_notice_unit_nu_state_key_readme_unchanged(tmp_path, monkeypatch, capsys):
    """README and INDEX keys keep the `<realpath>|<STATUS>` format the #83 state files use."""
    notice = load('notice')
    state_file, payload = register_state(tmp_path, monkeypatch)
    readme, index = tmp_path / 'README.md', tmp_path / 'INDEX.md'
    readme.write_text('r\n')
    index.write_text('i\n')

    notice.emit_post_tool_notice([
        record('README', str(readme), 'SKIPPED_NO_CLOSING_MARKER'),
        record('INDEX', str(index), 'SKIPPED_NO_OPENING_MARKER')], payload)
    capsys.readouterr()

    state = json.loads(state_file.read_text())
    assert sorted(state) == [f'{os.path.realpath(index)}|SKIPPED_NO_OPENING_MARKER',
                             f'{os.path.realpath(readme)}|SKIPPED_NO_CLOSING_MARKER']
    assert notice._state_key('/p', load('regions').RegenStatus.SKIPPED_NO_CLOSING_MARKER) == '/p|SKIPPED_NO_CLOSING_MARKER'
    assert all(len(value) == 64 for value in state.values())


def test_notice_unit_nu_dedupe_same_realpath_marker_once(tmp_path):
    """The same file reached twice (a symlink) is one entry; two sections of one file are two."""
    notice = load('notice')
    real = tmp_path / 'README.md'
    real.write_text('x\n')
    link = tmp_path / 'link.md'
    link.symlink_to(real)
    duplicate = notice.notifiable([record('README', str(real), 'SKIPPED_NO_CLOSING_MARKER'),
                                   record('README', str(link), 'SKIPPED_NO_CLOSING_MARKER')])
    assert len(duplicate) == 1
    claude = tmp_path / 'CLAUDE.md'
    claude.write_text('c\n')
    sections = notice.notifiable([
        record('CLAUDE_MD_SECTION', str(claude), 'SKIPPED_NO_OPENING_MARKER', 'agent-list'),
        record('CLAUDE_MD_SECTION', str(claude), 'SKIPPED_NO_OPENING_MARKER', 'agent-list'),
        record('CLAUDE_MD_SECTION', str(claude), 'SKIPPED_NO_OPENING_MARKER', 'skill-list')])
    assert [entry.marker_id for entry in sections] == ['agent-list', 'skill-list']


def long_entries(count, path_length):
    return [record('INDEX', f'/{index}' + 'p' * path_length + '/INDEX.md', 'SKIPPED_NO_OPENING_MARKER')
            for index in range(count)]


def test_notice_unit_nu_cap_greedy_whole_entries():
    """Whole entries are packed in order until the next one no longer fits; none is cut."""
    notice = load('notice')
    entries = notice.notifiable(long_entries(8, 150))

    printed, text = notice.render_notices(entries)

    assert len(text) <= NOTICE_CAP
    assert 0 < len(printed) < len(entries)
    assert printed == entries[:len(printed)]
    lines = text.split('\n')
    assert len(lines) == len(printed) + 1
    for entry, line in zip(printed, lines):
        assert line == notice.build_notice_text([entry])
    assert f'{len(entries) - len(printed)} more notice(s) not shown' in lines[-1]
    # Everything that fits is printed without a tail.
    few = notice.notifiable(long_entries(2, 150))
    assert notice.render_notices(few)[0] == few and 'not shown' not in notice.render_notices(few)[1]


def test_notice_unit_nu_cap_first_entry_truncated_when_alone_exceeds():
    """A first entry that alone exceeds the cap is still printed, cut with the existing suffix."""
    notice = load('notice')
    entries = notice.notifiable(long_entries(3, 2600))

    printed, text = notice.render_notices(entries)

    assert printed == entries[:1]
    assert len(text) == NOTICE_CAP and text.endswith(notice.TRUNCATION_SUFFIX)
    assert text.startswith('doc-sync: INDEX not regenerated')


def test_notice_unit_nu_cap_overflow_tail_inside_cap():
    """The line that counts the held-back entries is inside the cap, for every entry length."""
    notice = load('notice')
    for path_length in range(100, 700, 37):
        entries = notice.notifiable(long_entries(9, path_length))
        printed, text = notice.render_notices(entries)
        assert len(text) <= NOTICE_CAP, path_length
        assert printed and (len(printed) == len(entries) or 'more notice(s) not shown' in text.split('\n')[-1]
                            or len(printed) == 1), path_length


def test_notice_unit_nu_cap_records_only_printed(tmp_path, monkeypatch, capsys):
    """Only the entries that were printed become seen; the rest print on the next call."""
    notice = load('notice')
    state_file, payload = register_state(tmp_path, monkeypatch)
    entries = []
    for index in range(8):
        path = tmp_path / (f'{index}' + 'd' * 150) / 'INDEX.md'
        path.parent.mkdir()
        path.write_text(f'{index}\n')
        entries.append(record('INDEX', str(path), 'SKIPPED_NO_OPENING_MARKER'))

    notice.emit_post_tool_notice(entries, payload)
    first = json.loads(capsys.readouterr().out)['systemMessage']
    recorded_first = set(json.loads(state_file.read_text()))
    notice.emit_post_tool_notice(entries, payload)
    second = json.loads(capsys.readouterr().out)['systemMessage']
    recorded_second = set(json.loads(state_file.read_text()))

    shown_first = {os.path.realpath(entry.path) for entry in entries if os.path.realpath(entry.path) in first}
    assert {key.split('|')[0] for key in recorded_first} == shown_first
    assert 0 < len(recorded_first) < len(entries)
    assert recorded_first < recorded_second
    shown_second = {os.path.realpath(entry.path) for entry in entries if os.path.realpath(entry.path) in second}
    assert shown_first.isdisjoint(shown_second) and shown_second


def test_notice_unit_nu_never_raises_on_malformed_results(capsys):
    """Nothing a caller passes can raise out of emit_post_tool_notice or change the exit path."""
    notice = load('notice')

    def exploding():
        yield record('README', '/x/README.md', 'SKIPPED_NO_CLOSING_MARKER')
        raise RuntimeError('boom')

    for results in (None, 5, object(), [], [[]], [{}], ['x'], [(1, 2, 3, 4, 5, 6, 7)], exploding(), {'a': 1},
                    [(None, None)], [record('README', b'bytes', 'SKIPPED_NO_CLOSING_MARKER')]):
        notice.emit_post_tool_notice(results, {})
        notice.emit_post_tool_notice(results, {'session_id': 5, 'agent_id': object()})
    capsys.readouterr()
    assert notice.notifiable(None) == [] and notice.build_notice_text([]) == ''


def test_notice_unit_nu_regenstatus_identity():
    """The status class is the one from regions, whichever module handed the member over."""
    regions = load('regions')
    notice = load('notice')
    assert notice.RegenStatus is regions.RegenStatus is load('regen_readme').RegenStatus
    assert set(notice.NOTIFY_STATUSES) == {
        regions.RegenStatus.SKIPPED_NO_OPENING_MARKER, regions.RegenStatus.SKIPPED_NO_CLOSING_MARKER,
        regions.RegenStatus.SKIPPED_MALFORMED_MARKERS}
    spec = importlib.util.spec_from_file_location('regen_readme_bare_notice_test', DOC_SYNC_PACKAGE / 'regen_readme.py')
    bare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bare)
    status = bare.RegenStatus.SKIPPED_NO_CLOSING_MARKER
    assert status is regions.RegenStatus.SKIPPED_NO_CLOSING_MARKER
    assert len(notice.notifiable([('/x/README.md', status)])) == 1


def test_notice_unit_nu_malformed_notice_carries_shape_and_hint():
    """A malformed notice names the shape and gives one concrete action for it."""
    notice = load('notice')
    hints = {
        'DUPLICATE_OPENING': 'keep exactly one <!-- AUTO:index-stats -->',
        'DUPLICATE_CLOSING': 'keep exactly one <!-- AUTO:index-stats -->',
        'MULTIPLE_REGIONS': 'keep exactly one <!-- AUTO:index-stats -->',
        'NESTED_REGIONS': 'remove the inner opening marker <!-- AUTO:index-stats -->',
        'FOREIGN_MARKER_INSIDE': 'move the other section',
        'NEAR_MISS_MARKER': 'write the marker exactly as <!-- AUTO:index-stats -->',
        'UNCLOSED_FENCE': 'close the code fence',
        'BODY_CONTAINS_MARKER': 'nothing was written',
        'BODY_BREAKS_REGION': 'nothing was written',
    }
    for shape, hint in hints.items():
        text = notice.build_notice_text(notice.notifiable([record('INDEX', '/x/INDEX.md', 'SKIPPED_MALFORMED_MARKERS', None, shape)]))
        assert f'shape {shape}' in text and hint in text, shape
        assert text.count('Action:') == 1


def test_notice_unit_nu_unclosed_fence_hint_line_number():
    """The unclosed-fence notice names the line the fence starts on, or degrades without one."""
    notice = load('notice')
    with_line = notice.build_notice_text(notice.notifiable(
        [record('README', '/x/README.md', 'SKIPPED_MALFORMED_MARKERS', None, 'UNCLOSED_FENCE', '12')]))
    without = notice.build_notice_text(notice.notifiable(
        [record('README', '/x/README.md', 'SKIPPED_MALFORMED_MARKERS', None, 'UNCLOSED_FENCE', None)]))
    assert 'close the code fence that starts at line 12' in with_line
    assert 'close the code fence that hides the marker' in without and 'line None' not in without


def load_relay_module(home, monkeypatch):
    """Import the relay hook with HOME redirected first: CACHE_FILE and the roots derive from it."""
    monkeypatch.setenv('HOME', str(home))
    for name in SCRUBBED_ENV:
        monkeypatch.delenv(name, raising=False)
    spec = importlib.util.spec_from_file_location('userprompt_doc_sync_index_test', RELAY_HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_home(root, readme_text=None, index_text=None):
    """A temp HOME whose .claude/commands lost a file since the cached snapshot (copies, not symlinks)."""
    home = Path(root) / 'home'
    hooks_dir = home / '.claude' / 'hooks'
    commands = home / '.claude' / 'commands'
    hooks_dir.mkdir(parents=True)
    commands.mkdir()
    shutil.copy(HOOK, hooks_dir / 'posttool-doc-sync.py')
    shutil.copytree(DOC_SYNC_PACKAGE, hooks_dir / 'doc_sync',
                    ignore=shutil.ignore_patterns('__pycache__', 'README.md', 'INDEX.md'))
    (commands / 'keep.py').write_text('"""Keep."""\n')
    if readme_text is not None:
        (commands / 'README.md').write_text(readme_text)
    if index_text is not None:
        (commands / 'INDEX.md').write_text(index_text)
    cache = {'last_check': 0, 'snapshots': {str(commands): ['gone.md', 'keep.py']}}
    (home / '.claude' / '.doc-sync-cache.json').write_text(json.dumps(cache))
    return home


def run_relay(home, tmp_root):
    environment = {key: value for key, value in os.environ.items() if key not in SCRUBBED_ENV}
    environment.update(HOME=str(home), TMPDIR=str(tmp_root),
                       PATH=os.path.dirname(sys.executable) + os.pathsep + os.environ.get('PATH', ''),
                       PYTHONDONTWRITEBYTECODE='1')
    return subprocess.run([sys.executable, str(RELAY_HOOK)], capture_output=True, text=True, env=environment,
                          cwd=str(home), timeout=120)


def resync_line(home):
    return f'doc-sync: detected deletion in {home / ".claude" / "commands"}, resynced INDEX.md'


def test_relay_line_rl_no_notice_bytes_identical(tmp_path):
    """Without any notice the stdout is the plain resync line it always was, byte for byte."""
    home = build_home(tmp_path)

    completed = run_relay(home, tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == resync_line(home) + '\n'


def test_relay_line_rl_readme_only_notice_line_unchanged(tmp_path):
    """A README-only skip leaves the resync line byte-identical to the pre-change text."""
    home = build_home(tmp_path, readme_text=f'# Legacy\n\n{RO}\nstale without a terminator\n')

    completed = run_relay(home, tmp_path)

    output = json.loads(completed.stdout)
    assert resync_line(home) in output['hookSpecificOutput']['additionalContext'].split('\n')
    assert 'README not regenerated' in output['systemMessage'] and 'INDEX not regenerated' not in output['systemMessage']


def test_relay_line_rl_index_notice_line_not_resynced_claim(tmp_path):
    """An INDEX skip makes the line stop claiming the INDEX was resynced (README skip too)."""
    for name, readme in (('index_only', None), ('with_readme', f'# Legacy\n\n{RO}\nstale\n')):
        home = build_home(tmp_path / name, readme_text=readme, index_text='# hand written\n')

        completed = run_relay(home, tmp_path / name)

        output = json.loads(completed.stdout)
        context = output['hookSpecificOutput']['additionalContext'].split('\n')
        line = f'doc-sync: detected deletion in {home / ".claude" / "commands"}, doc-sync re-run, a notice follows'
        assert line in context and resync_line(home) not in context, name
        assert 'resynced INDEX.md' not in '\n'.join(context)
        assert output['systemMessage'].startswith(('doc-sync: INDEX not regenerated', 'doc-sync: README not regenerated'))
        assert 'INDEX not regenerated (SKIPPED_NO_OPENING_MARKER)' in output['systemMessage']
        assert (home / '.claude' / 'commands' / 'INDEX.md').read_text() == '# hand written\n'


def test_relay_line_rl_index_notice_single_json_object(tmp_path):
    """With an INDEX notice the whole stdout is exactly one JSON object; notices alone in systemMessage."""
    home = build_home(tmp_path, index_text='# hand written\n')

    completed = run_relay(home, tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.count('\n') == 1 and completed.stdout.endswith('\n')
    output = json.loads(completed.stdout)
    assert set(output) == {'systemMessage', 'hookSpecificOutput'}
    assert output['hookSpecificOutput']['hookEventName'] == 'UserPromptSubmit'
    assert 'detected deletion' not in output['systemMessage']
    assert output['systemMessage'] in output['hookSpecificOutput']['additionalContext']


def test_relay_line_rl_prefix_agrees_with_notice_module(tmp_path, monkeypatch):
    """The relay hook's copy of the INDEX prefix equals the notice module's, and matches a real notice."""
    notice = load('notice')
    relay = load_relay_module(tmp_path / 'relay-home', monkeypatch)
    text = notice.build_notice_text(notice.notifiable([record('INDEX', '/x/INDEX.md', 'SKIPPED_NO_CLOSING_MARKER')]))

    assert relay.INDEX_NOTICE_PREFIX == notice.INDEX_NOTICE_PREFIX
    assert relay.notice_reports_index_skip(text) is True
    readme_text = notice.build_notice_text(notice.notifiable(
        [record('README', '/x/README.md', 'SKIPPED_NO_CLOSING_MARKER')]))
    assert relay.notice_reports_index_skip(readme_text) is False
    assert relay.notice_reports_index_skip(readme_text + '\n' + text) is True


def test_relay_line_rl_earlier_output_survives_later_timeout(tmp_path, monkeypatch, capsys):
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
    module = load_relay_module(home, monkeypatch)
    index_text = 'doc-sync: INDEX not regenerated (SKIPPED_NO_OPENING_MARKER). INDEX: /somewhere/INDEX.md'
    child_json = json.dumps({'systemMessage': index_text, 'hookSpecificOutput': {
        'hookEventName': 'PostToolUse', 'additionalContext': index_text}})
    calls = []

    def fake_run(command, **kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            raise subprocess.TimeoutExpired(command, kwargs.get('timeout'))
        return subprocess.CompletedProcess(command, 0, stdout=child_json, stderr='')

    monkeypatch.setattr(module.subprocess, 'run', fake_run)

    with pytest.raises(SystemExit) as exit_info:
        module.main()

    assert exit_info.value.code == 0
    assert len(calls) == 2
    output = json.loads(capsys.readouterr().out)
    assert output['systemMessage'] == index_text
    context = output['hookSpecificOutput']['additionalContext']
    assert context.count('detected deletion') == 1 and 'resynced INDEX.md' not in context
    assert json.loads(cache_file.read_text())['last_check'] == 0
