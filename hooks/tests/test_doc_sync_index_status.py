#!/usr/bin/env python3
"""Status, zero-write and stability tests for INDEX, README and CLAUDE.md-section regeneration.

Backlog #85: regen_index() returned None on every path, so nobody could tell a skipped INDEX
from a regenerated one, and the marker predicates disagreed with each other. It now returns a
RegenStatus on every path, every skip is a zero-write, and README, INDEX and the CLAUDE.md
section patcher classify their markers with the one shared classifier.

The shape ids M-01..M-22 are the rows of the ticket's shape table. Every scenario runs on a
synthetic directory under tmp_path; nothing touches the repository tree. HOME and TMPDIR are
redirected and the doc-sync environment variables scrubbed, so a stray regeneration of a
global directory cannot write into the real ~/.claude.

New symbols (RegenStatus, classify_region, ...) are reached through load() inside the test
bodies, never through a module-level from-import: against the pre-change modules the tests
fail one by one instead of failing at collection.
"""

import builtins
import importlib
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

SCRUBBED_ENV = ('CLAUDE_PROJECT_DIR', 'CLAUDE_DOC_SYNC_ROOTS', 'CLAUDE_DOC_SYNC_STATE_ROOT')
# 2001-09-09: clearly earlier than any real mtime, so a rewrite cannot hide behind an equal one.
EARLIER_NS = 1_000_000_000 * 10**9
FIXED_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
FF = chr(0x0C)
NEL = chr(0x85)
LS = chr(0x2028)

IO = '<!-- AUTO:index-stats -->'
IC = '<!-- /AUTO:index-stats -->'
RO = '<!-- AUTO:readme-stats -->'
RC = '<!-- /AUTO:readme-stats -->'


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    scratch_tmp = tmp_path / 'tmp'
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


class FixedClock:
    """Stand-in for the module-level `datetime` name of regen_index and patch."""

    @classmethod
    def now(cls, tz=None):
        return FIXED_NOW


class WriteSpy:
    """Counts every write-mode access to one path through the APIs a rewrite could use."""

    def __init__(self, monkeypatch, target):
        self.calls = []
        self.target = Path(target)
        spy = self
        original_write_text = Path.write_text
        original_write_bytes = Path.write_bytes
        original_path_open = Path.open
        original_open = builtins.open

        def write_text(path, *args, **kwargs):
            spy.record(path, 'write_text')
            return original_write_text(path, *args, **kwargs)

        def write_bytes(path, *args, **kwargs):
            spy.record(path, 'write_bytes')
            return original_write_bytes(path, *args, **kwargs)

        def path_open(path, mode='r', *args, **kwargs):
            if any(flag in mode for flag in 'wax+'):
                spy.record(path, 'Path.open')
            return original_path_open(path, mode, *args, **kwargs)

        def builtin_open(file, mode='r', *args, **kwargs):
            if any(flag in str(mode) for flag in 'wax+'):
                spy.record(file, 'open')
            return original_open(file, mode, *args, **kwargs)

        monkeypatch.setattr(Path, 'write_text', write_text)
        monkeypatch.setattr(Path, 'write_bytes', write_bytes)
        monkeypatch.setattr(Path, 'open', path_open)
        monkeypatch.setattr(builtins, 'open', builtin_open)

    def record(self, path, api):
        try:
            if Path(path) == self.target:
                self.calls.append(api)
        except TypeError:
            pass


def shape_body(case, marker_id):
    """The text of one shape-table row for one marker id (the same rows serve INDEX, README, CLAUDE.md)."""
    o = f'<!-- AUTO:{marker_id} -->'
    c = f'<!-- /AUTO:{marker_id} -->'
    foreign_o = '<!-- AUTO:other-section -->'
    foreign_c = '<!-- /AUTO:other-section -->'
    table = {
        'M01': f'{o}\nstale\n{c}\n\nhand text\n',
        'M02': f'{o}\n{c}\n',
        'M03': 'hand written, no marker at all\n',
        'M04': f'hand\n{c}\n',
        'M05': f'hand\n\n{o}\nstale without a terminator\n',
        'M06': f'{c}\nmiddle\n{o}\nstale\n',
        'M07': f'{o}\nstale\n{o}\nmore\n{c}\n',
        'M08': f'{o}\nstale\n{c}\nmiddle\n{c}\n',
        'M09': f'{o}\na\n{c}\nmiddle\n{o}\nb\n{c}\n',
        'M10': f'{o}\n{o}\nnested\n{c}\n{c}\n',
        'M11': f'{o}\n{foreign_o}\nx\n{foreign_c}\n{c}\n',
        'M12': f'hand\n<!--AUTO:{marker_id}-->\nstale\n',
        'M13': f'hand\n{o} {c}\n',
        'M14': f'hand\n\n```\n{o}\nstale\n{c}\n```\n',
        'M15': f'```\n{o}\nexample body\n{c}\n```\n\n{o}\nstale\n{c}\n\nhand text\n',
        'M16': f'  {o}\nstale\n\t{c}\n\nhand text\n',
        'M21': '',
    }
    if case == 'M22':
        return table['M01'].replace('\n', '\r\n')
    return table[case]


EXPECTED_STATUS = {
    'M01': 'WRITTEN', 'M02': 'WRITTEN', 'M03': 'SKIPPED_NO_OPENING_MARKER', 'M04': 'SKIPPED_NO_OPENING_MARKER',
    'M05': 'SKIPPED_NO_CLOSING_MARKER', 'M06': 'SKIPPED_NO_CLOSING_MARKER',
    'M07': 'SKIPPED_MALFORMED_MARKERS', 'M08': 'SKIPPED_MALFORMED_MARKERS', 'M09': 'SKIPPED_MALFORMED_MARKERS',
    'M10': 'SKIPPED_MALFORMED_MARKERS', 'M11': 'SKIPPED_MALFORMED_MARKERS', 'M12': 'SKIPPED_MALFORMED_MARKERS',
    'M13': 'SKIPPED_MALFORMED_MARKERS', 'M14': 'SKIPPED_NO_OPENING_MARKER', 'M15': 'WRITTEN', 'M16': 'WRITTEN',
    'M17': 'SKIPPED_MALFORMED_MARKERS', 'M18': 'WRITTEN', 'M19': 'SKIPPED_GITHUB_RESERVED', 'M20': 'WRITTEN',
    'M21': 'SKIPPED_NO_OPENING_MARKER', 'M22': 'WRITTEN',
}
SKIP_CASES = ['M03', 'M04', 'M05', 'M06', 'M07', 'M08', 'M09', 'M10', 'M11', 'M12', 'M13', 'M14', 'M21']


def write_description_marker(directory, marker_lines):
    """A JSON file whose description holds a newline followed by whole-line marker text."""
    (directory / 'meta.json').write_text(json.dumps({'description': 'first line\n' + '\n'.join(marker_lines)}))


def build_index_case(tmp_path, case):
    """(project, directory, INDEX path) for one shape id; the INDEX exists except for M20."""
    project = tmp_path / 'project'
    directory = project / ('.github' if case == 'M19' else 'folder')
    directory.mkdir(parents=True)
    (directory / 'alpha.py').write_text('"""Alpha helper."""\n')
    index = directory / 'INDEX.md'
    if case == 'M17':
        write_description_marker(directory, [IC])
        index.write_text(f'# folder\n\n{IO}\nstale\n{IC}\n')
    elif case == 'M18':
        index.write_text(f'# folder\n\n{IO}\nstale\n{IC}\n\n<!-- AUTO:index-stats-extra -->\nhand\n<!-- /AUTO:index-stats-extra -->\n')
    elif case == 'M19':
        index.write_text(shape_body('M01', 'index-stats'))
    elif case != 'M20':
        index.write_bytes(shape_body(case, 'index-stats').encode())
    return project, directory, index


def build_readme_case(tmp_path, case):
    project = tmp_path / 'project'
    directory = project / 'folder'
    directory.mkdir(parents=True)
    (directory / 'alpha.py').write_text('"""Alpha helper."""\n')
    readme = directory / 'README.md'
    if case == 'M17':
        write_description_marker(directory, [RC])
        readme.write_text(f'# folder\n\n{RO}\nstale\n{RC}\n')
    else:
        readme.write_bytes(shape_body(case, 'readme-stats').encode())
    return project, directory, readme


def pin_mtime(path):
    os.utime(path, ns=(EARLIER_NS, EARLIER_NS))
    return path.read_bytes(), path.stat().st_mtime_ns


@pytest.mark.parametrize('case', [pytest.param(case, id=f'idxs_{case}') for case in EXPECTED_STATUS])
def test_idx_status_returns_the_status_for_each_shape(tmp_path, case):
    """regen_index returns (by identity) the status the ticket's table fixes for the shape."""
    regions = load('regions')
    project, directory, index = build_index_case(tmp_path, case)

    result = load('regen_index').regen_index(directory, project)

    assert result is regions.RegenStatus[EXPECTED_STATUS[case]], (case, result)
    if case == 'M20':
        assert IO in index.read_text() and IC in index.read_text()


def test_idx_status_idxs_never_none_all_shapes(tmp_path):
    """No path of regen_index returns None: every shape yields a RegenStatus member."""
    regions = load('regions')
    module = load('regen_index')
    for case in EXPECTED_STATUS:
        project, directory, _ = build_index_case(tmp_path / case, case)
        result = module.regen_index(directory, project)
        assert result is not None and any(result is member for member in regions.RegenStatus), case


@pytest.mark.parametrize('case', [pytest.param(case, id=f'idxz_{case}') for case in SKIP_CASES + ['M19']])
def test_idx_zero_write_skip_shapes_leave_bytes_and_mtime_alone(tmp_path, monkeypatch, case):
    """A skip performs no write: bytes, mtime and every write-mode access counter stay untouched."""
    regions = load('regions')
    module = load('regen_index')
    project, directory, index = build_index_case(tmp_path, case)
    before_bytes, before_mtime = pin_mtime(index)
    with monkeypatch.context() as patched:
        spy = WriteSpy(patched, index)
        result = module.regen_index(directory, project)

    assert spy.calls == []
    assert index.read_bytes() == before_bytes
    assert index.stat().st_mtime_ns == before_mtime == EARLIER_NS
    assert result is regions.RegenStatus[EXPECTED_STATUS[case]]


def test_idx_zero_write_idxz_selfcheck_description_marker(tmp_path, monkeypatch):
    """Generated content that would carry marker text is refused with zero writes.

    The marker lines sit inside the generated tree fence, where the fence-aware classifier
    alone would accept the result: only the body-level scan of the content about to be written
    (any marker of any id, fenced or not) refuses it.
    """
    regions = load('regions')
    module = load('regen_index')
    for variant, lines in {'own_closing': [IC], 'own_opening': [IO], 'foreign_id': ['<!-- AUTO:other -->'],
                           'inline_pair': [IO, IC]}.items():
        project, directory, index = build_index_case(tmp_path / variant, 'M01')
        write_description_marker(directory, lines)
        if variant == 'foreign_id':
            # Discriminator: the fence-aware classifier alone calls the would-be file
            # well-formed, so the refusal below can only come from the body-level scan.
            would_be = module._build_index_content(directory, 'kebab', '')
            assert regions.classify_region(would_be, 'index-stats').shape is regions.RegionShape.WELL_FORMED
        before_bytes, before_mtime = pin_mtime(index)
        with monkeypatch.context() as patched:
            spy = WriteSpy(patched, index)
            result = module.regen_index(directory, project)

        assert result is regions.RegenStatus.SKIPPED_MALFORMED_MARKERS, variant
        assert spy.calls == [], variant
        assert index.read_bytes() == before_bytes and index.stat().st_mtime_ns == before_mtime, variant
    # A directory without an INDEX yet is refused the same way and gets no file.
    project, directory, index = build_index_case(tmp_path / 'fresh', 'M20')
    write_description_marker(directory, [IC])
    assert module.regen_index(directory, project) is regions.RegenStatus.SKIPPED_MALFORMED_MARKERS
    assert not index.exists()


def run_rounds(module, directory, project, index, monkeypatch, rounds=3):
    monkeypatch.setattr(module, 'datetime', FixedClock)
    outputs = []
    for _ in range(rounds):
        module.regen_index(directory, project)
        outputs.append(index.read_bytes())
    return outputs


def assert_single_generated_block(text):
    assert text.count('*Last updated:') == 1
    assert text.count('**Total entries**') == 1
    assert text.count('## Tree') == 1


@pytest.mark.parametrize('case', [pytest.param(case, id=f'idxt_{case}') for case in
                                  ['M01', 'M02', 'M15', 'M16', 'M20', 'M22']])
def test_idx_stable_rounds_are_byte_stable(tmp_path, monkeypatch, case):
    """Three consecutive rounds give identical bytes and never duplicate the generated block."""
    project, directory, index = build_index_case(tmp_path, case)
    module = load('regen_index')

    first, second, third = run_rounds(module, directory, project, index, monkeypatch)

    # Without an INDEX the first round sees a directory that does not hold INDEX.md yet, and the
    # existing convention guess counts that file: round one may differ, unchanged by this ticket.
    assert second == third and (case == 'M20' or first == second)
    text = third.decode()
    assert_single_generated_block(text)
    assert text.count(IO) == (2 if case == 'M15' else 1)
    assert text.endswith('---\n*Auto-generated by doc-sync hook.*')
    if case == 'M15':
        # The fenced example is verbatim hand text and the real block is the only one outside it.
        assert f'```\n{IO}\nexample body\n{IC}\n```' in text
    if case in ('M01', 'M15', 'M16', 'M22'):
        assert text.count('hand text') == 1


def test_idx_stable_idxt_hand_before_after_moves_once(tmp_path, monkeypatch):
    """Hand text before and after the block ends up exactly once, after the block, and stays there."""
    project, directory, index = build_index_case(tmp_path, 'M20')
    index.write_text(f'# folder\n\nhand BEFORE\n\n{IO}\nstale\n{IC}\n\nhand AFTER\n\n---\n*Auto-generated by doc-sync hook.*\n')
    module = load('regen_index')

    first, second, third = run_rounds(module, directory, project, index, monkeypatch)

    text = third.decode()
    assert first == second == third
    assert text.count('hand BEFORE') == 1 and text.count('hand AFTER') == 1
    assert text.index(IC) < text.index('hand BEFORE') < text.index('hand AFTER')
    assert text.count('*Auto-generated by doc-sync hook.*') == 1
    assert text.startswith('# folder\n')


def test_idx_stable_idxt_hand_text_formfeed_u2028_byte_exact(tmp_path, monkeypatch):
    """Form feed, U+2028 and U+0085 inside hand text survive byte for byte (no generic line split)."""
    project, directory, index = build_index_case(tmp_path, 'M20')
    hand = f'first{FF}second\nthird{LS}fourth\nfifth{NEL}sixth\n{FF}\nlast line'
    index.write_bytes(f'# folder\n\n{IO}\nstale\n{IC}\n\n{hand}\n'.encode())
    module = load('regen_index')

    first, second, third = run_rounds(module, directory, project, index, monkeypatch)

    assert hand.encode() in third
    assert first == second == third


def test_idx_stable_idxt_open_only_is_skip_not_rewrite(tmp_path, monkeypatch):
    """An INDEX with only an opening marker is skipped now: its bytes never change (it used to duplicate once)."""
    regions = load('regions')
    project, directory, index = build_index_case(tmp_path, 'M05')
    module = load('regen_index')
    before = index.read_bytes()

    results = []
    monkeypatch.setattr(module, 'datetime', FixedClock)
    for _ in range(3):
        results.append(module.regen_index(directory, project))

    assert results == [regions.RegenStatus.SKIPPED_NO_CLOSING_MARKER] * 3
    assert index.read_bytes() == before


def test_idx_stable_idxt_no_duplicate_blocks(tmp_path, monkeypatch):
    """A legacy INDEX with an old generated block and an opening marker only is left alone, not doubled."""
    project, directory, index = build_index_case(tmp_path, 'M20')
    legacy = f'# folder\n\n{IO}\n*Last updated: 2001-01-01T00:00:00Z*\n**Total entries**: 1\n## Tree\n```\nfolder/\n```\n'
    index.write_text(legacy)
    module = load('regen_index')
    monkeypatch.setattr(module, 'datetime', FixedClock)

    for _ in range(3):
        module.regen_index(directory, project)

    assert index.read_text() == legacy
    assert_single_generated_block(index.read_text())


def test_idx_stable_idxt_needs_update_agrees_with_classifier(tmp_path):
    """_index_needs_update is True exactly when the INDEX is absent or its region is well-formed."""
    regions = load('regions')
    module = load('regen_index')
    absent = tmp_path / 'absent' / 'INDEX.md'
    absent.parent.mkdir()
    assert module._index_needs_update(absent) is True
    for case in ['M01', 'M02', 'M03', 'M04', 'M05', 'M06', 'M07', 'M08', 'M09', 'M10', 'M11', 'M12', 'M13',
                 'M14', 'M15', 'M16', 'M21', 'M22']:
        path = tmp_path / case / 'INDEX.md'
        path.parent.mkdir()
        path.write_bytes(shape_body(case, 'index-stats').encode())
        expected = regions.classify_region(path.read_text(), 'index-stats').shape is regions.RegionShape.WELL_FORMED
        assert module._index_needs_update(path) is expected, case


@pytest.mark.parametrize('case', [pytest.param(case, id=f'rdm_{case}') for case in
                                  ['M03', 'M04', 'M05', 'M06', 'M07', 'M08', 'M09', 'M10', 'M11', 'M12', 'M13',
                                   'M14', 'M15', 'M21']])
def test_readme_shapes_status_for_each_shape(tmp_path, case):
    """regen_readme keeps the #83 statuses, reports the new shapes, and preserves a fenced example."""
    regions = load('regions')
    project, directory, readme = build_readme_case(tmp_path, case)
    before = readme.read_bytes()

    result = load('regen_readme').regen_readme(directory, project)

    assert result is regions.RegenStatus[EXPECTED_STATUS[case]], (case, result)
    if case == 'M15':
        text = readme.read_text()
        assert f'```\n{RO}\nexample body\n{RC}\n```' in text
        assert 'stale' not in text and '**Total files**' in text and text.count('hand text') == 1
    else:
        assert readme.read_bytes() == before


def test_readme_shapes_rdm_M17_description_newline_marker(tmp_path):
    """A description with a newline and a whole-line marker is refused: zero writes, MALFORMED."""
    regions = load('regions')
    module = load('regen_readme')
    for variant, lines in {'own_closing': [RC], 'own_opening': [RO], 'foreign': ['<!-- AUTO:index-stats -->']}.items():
        project, directory, readme = build_readme_case(tmp_path / variant, 'M17')
        write_description_marker(directory, lines)
        before_bytes, before_mtime = pin_mtime(readme)
        assert module.regen_readme(directory, project) is regions.RegenStatus.SKIPPED_MALFORMED_MARKERS, variant
        assert readme.read_bytes() == before_bytes and readme.stat().st_mtime_ns == before_mtime, variant
    # No README yet: the same refusal, and no file is created.
    project = tmp_path / 'fresh' / 'project'
    directory = project / 'folder'
    directory.mkdir(parents=True)
    write_description_marker(directory, [RC])
    assert module.regen_readme(directory, project) is regions.RegenStatus.SKIPPED_MALFORMED_MARKERS
    assert not (directory / 'README.md').exists()


def test_readme_shapes_rdm_zero_write_all_skip_shapes(tmp_path, monkeypatch):
    """Every README skip (the #83 ones and the new ones) is a zero-write: bytes, mtime, write counters."""
    regions = load('regions')
    module = load('regen_readme')
    for case in SKIP_CASES + ['M17']:
        project, directory, readme = build_readme_case(tmp_path / case, case)
        before_bytes, before_mtime = pin_mtime(readme)
        with monkeypatch.context() as patched:
            spy = WriteSpy(patched, readme)
            result = module.regen_readme(directory, project)

        assert spy.calls == [], case
        assert readme.read_bytes() == before_bytes and readme.stat().st_mtime_ns == before_mtime == EARLIER_NS, case
        assert result is regions.RegenStatus[EXPECTED_STATUS[case]], case


def test_readme_shapes_rdm_bare_standalone_skip_and_written(tmp_path):
    """A bare-loaded regen_readme returns the very same RegenStatus objects as the package one."""
    regions = load('regions')
    spec = importlib.util.spec_from_file_location(
        'regen_readme_bare_status_test', REPO_ROOT / 'hooks' / 'doc_sync' / 'regen_readme.py')
    bare = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bare)
    assert not bare.__package__ and bare.RegenStatus is regions.RegenStatus
    for case in ('M01', 'M03', 'M05', 'M07', 'M12'):
        project, directory, _ = build_readme_case(tmp_path / case, case)
        expected = regions.RegenStatus[EXPECTED_STATUS[case]]
        assert bare.regen_readme(directory, project) is expected, case
        assert load('regen_readme').regen_readme(directory, project) is expected, case


def test_readme_shapes_rdm_status_identity_five_members(tmp_path):
    """The status class is one object with five members across regen_readme, regen_index and regions."""
    regions = load('regions')
    assert load('regen_readme').RegenStatus is regions.RegenStatus is load('regen_index').RegenStatus
    assert [member.name for member in regions.RegenStatus] == [
        'WRITTEN', 'SKIPPED_GITHUB_RESERVED', 'SKIPPED_NO_OPENING_MARKER', 'SKIPPED_NO_CLOSING_MARKER',
        'SKIPPED_MALFORMED_MARKERS']
    project, directory, _ = build_readme_case(tmp_path, 'M01')
    assert load('regen_readme').regen_readme(directory, project) is regions.RegenStatus.WRITTEN


CLAUDE_HEAD = '# CLAUDE.md\n\n> Project-specific settings for demo\n\n'
# One exact marker of another section id: the top-level candidate guard (`<!-- AUTO:` anywhere)
# silences a file whose only marker text is a near miss, so every fixture carries this pair.
# Its body is what patching regenerates (no .claude/commands directory), so it never changes.
CLAUDE_GUARD = '<!-- AUTO:command-list -->\n\n<!-- /AUTO:command-list -->\n\n'
CLAUDE_STATUS = {
    'M04': ('SKIPPED_NO_OPENING_MARKER', 'ONLY_CLOSING'), 'M05': ('SKIPPED_NO_CLOSING_MARKER', 'ONLY_OPENING'),
    'M06': ('SKIPPED_NO_CLOSING_MARKER', 'REVERSED'), 'M07': ('SKIPPED_MALFORMED_MARKERS', 'DUPLICATE_OPENING'),
    'M08': ('SKIPPED_MALFORMED_MARKERS', 'DUPLICATE_CLOSING'), 'M09': ('SKIPPED_MALFORMED_MARKERS', 'MULTIPLE_REGIONS'),
    'M10': ('SKIPPED_MALFORMED_MARKERS', 'NESTED_REGIONS'), 'M11': ('SKIPPED_MALFORMED_MARKERS', 'FOREIGN_MARKER_INSIDE'),
    'M12': ('SKIPPED_MALFORMED_MARKERS', 'NEAR_MISS_MARKER'), 'M13': ('SKIPPED_MALFORMED_MARKERS', 'NEAR_MISS_MARKER'),
    'M17': ('SKIPPED_MALFORMED_MARKERS', 'BODY_CONTAINS_MARKER'),
}
SILENT_CASES = ['M03', 'M14']
PATCHED_CASES = ['M01', 'M02', 'M15', 'M16']


def build_claude_case(tmp_path, monkeypatch, case, text=None):
    project = tmp_path / 'project'
    project.mkdir(parents=True)
    claude_md = project / 'CLAUDE.md'
    if text is None:
        if case == 'M17':
            # The skill-list body would carry the opening marker of its own section: a directory
            # name is the only free text a CLAUDE.md section body is built from (a closing
            # marker holds a slash, which no directory name can).
            skill = project / '.claude' / 'skills' / 'a\n<!-- AUTO:skill-list -->\nb'
            skill.mkdir(parents=True)
            text = CLAUDE_HEAD + CLAUDE_GUARD + shape_body('M01', 'skill-list')
        else:
            text = CLAUDE_HEAD + CLAUDE_GUARD + shape_body(case, 'last-updated')
    claude_md.write_bytes(text.encode())
    monkeypatch.setattr(load('patch'), 'datetime', FixedClock)
    return project, claude_md, text


@pytest.mark.parametrize('case', [pytest.param(case, id=f'cmd_{case}') for case in
                                  ['M01', 'M02', 'M03', 'M04', 'M05', 'M06', 'M07', 'M08', 'M09', 'M10', 'M11',
                                   'M12', 'M13', 'M14', 'M15', 'M17']])
def test_claudemd_shapes_section_records_and_bytes(tmp_path, monkeypatch, case):
    """A shape the classifier refuses never corrupts CLAUDE.md and yields exactly one record."""
    regions = load('regions')
    project, claude_md, text = build_claude_case(tmp_path, monkeypatch, case)

    records = load('patch').patch_claude_md(project)

    assert isinstance(records, list)
    if case in PATCHED_CASES:
        assert records == []
        assert claude_md.read_text() != text and '> Last updated: 2026-01-02' in claude_md.read_text()
        assert claude_md.read_text().count('<!-- AUTO:last-updated -->') == (2 if case == 'M15' else 1)
        assert claude_md.read_text().startswith(CLAUDE_HEAD + CLAUDE_GUARD)
        if case == 'M15':
            assert '```\n<!-- AUTO:last-updated -->\nexample body\n<!-- /AUTO:last-updated -->\n```' in claude_md.read_text()
        return
    assert claude_md.read_bytes() == text.encode()
    if case in SILENT_CASES:
        assert records == []
        return
    status, shape = CLAUDE_STATUS[case]
    marker_id = 'skill-list' if case == 'M17' else 'last-updated'
    assert len(records) == 1
    record = records[0]
    assert record.kind is regions.ArtifactKind.CLAUDE_MD_SECTION
    assert Path(record.path).resolve() == claude_md.resolve()
    assert record.status is regions.RegenStatus[status] and record.shape is regions.RegionShape[shape]
    assert record.marker_id == marker_id


def test_claudemd_shapes_cmd_single_last_updated_bytes_identical(tmp_path, monkeypatch):
    """A single well-formed last-updated pair is patched to the same bytes the old code produced."""
    project, claude_md, text = build_claude_case(
        tmp_path, monkeypatch, 'M01',
        text=CLAUDE_HEAD + '<!-- AUTO:last-updated -->\n> Last updated: 2001-01-01\n<!-- /AUTO:last-updated -->\n\nhand notes\n')
    start, end = '<!-- AUTO:last-updated -->', '<!-- /AUTO:last-updated -->'
    s, e = text.find(start), text.find(end)
    legacy = text[:s + len(start)] + '\n' + '> Last updated: 2026-01-02' + '\n' + text[e:]

    records = load('patch').patch_claude_md(project)

    assert records == []
    assert claude_md.read_bytes() == legacy.encode()


def test_claudemd_shapes_cmd_records_per_section(tmp_path, monkeypatch):
    """One record per opted-in section that was refused, in patch order; healthy sections get none."""
    text = (CLAUDE_HEAD
            + '<!-- AUTO:claude-inventory -->\n<!-- AUTO:claude-inventory -->\nx\n<!-- /AUTO:claude-inventory -->\n\n'
            + CLAUDE_GUARD
            + '<!-- /AUTO:agent-list -->\n\n'
            + '<!--AUTO:skill-list-->\n\n'
            + '<!-- AUTO:last-updated -->\nold\n<!-- /AUTO:last-updated -->\n')
    project, claude_md, _ = build_claude_case(tmp_path, monkeypatch, 'M01', text=text)

    records = load('patch').patch_claude_md(project)

    assert [(record.marker_id, record.shape.name) for record in records] == [
        ('claude-inventory', 'DUPLICATE_OPENING'), ('agent-list', 'ONLY_CLOSING'), ('skill-list', 'NEAR_MISS_MARKER')]
    updated = claude_md.read_text()
    assert '> Last updated: 2026-01-02' in updated
    assert '<!--AUTO:skill-list-->' in updated and '<!-- /AUTO:agent-list -->' in updated


def test_claudemd_shapes_cmd_unopted_section_silent(tmp_path, monkeypatch):
    """A section without any marker is not opted in: no record, no change, whatever else is present."""
    text = CLAUDE_HEAD + CLAUDE_GUARD + 'plain notes\n'
    project, claude_md, _ = build_claude_case(tmp_path, monkeypatch, 'M01', text=text)

    assert load('patch').patch_claude_md(project) == []
    assert claude_md.read_text() == text
    # A prose mention of a marker is not an opt-in either.
    prose = CLAUDE_HEAD + CLAUDE_GUARD + 'see `<!-- AUTO:last-updated -->` for the date\n'
    claude_md.write_text(prose)
    assert load('patch').patch_claude_md(project) == []
    assert claude_md.read_text() == prose


def test_claudemd_shapes_cmd_returns_list_of_records(tmp_path, monkeypatch):
    """patch_claude_md returns a list, empty or of six-field RegenRecords, on every path."""
    regions = load('regions')
    project, _, _ = build_claude_case(tmp_path / 'a', monkeypatch, 'M07')
    records = load('patch').patch_claude_md(project)
    assert isinstance(records, list) and all(isinstance(record, regions.RegenRecord) for record in records)
    assert records[0]._fields == ('kind', 'path', 'status', 'marker_id', 'shape', 'detail')
    # A project without any CLAUDE.md gets the template and an empty list.
    empty = tmp_path / 'empty'
    empty.mkdir()
    assert load('patch').patch_claude_md(empty) == []
    # A detail is carried for an unclosed fence: the line the fence starts on.
    fenced_text = CLAUDE_HEAD + CLAUDE_GUARD + '```\n<!-- AUTO:last-updated -->\nx\n<!-- /AUTO:last-updated -->\n'
    project, _, _ = build_claude_case(tmp_path / 'b', monkeypatch, 'M01', text=fenced_text)
    fenced = load('patch').patch_claude_md(project)
    assert [(record.shape.name, record.detail) for record in fenced] == [
        ('UNCLOSED_FENCE', str(fenced_text.split('\n').index('```') + 1))]


def test_claudemd_shapes_cmd_toplevel_candidate_guard_unchanged(tmp_path, monkeypatch):
    """Pinned boundary: a file is a candidate only when it contains the substring `<!-- AUTO:`."""
    # Only a near miss: the substring is absent, the file is not a candidate, nothing is reported.
    near_only = CLAUDE_HEAD + '<!--AUTO:last-updated-->\nold\n<!-- /AUTO:last-updated -->\n'
    project, claude_md, _ = build_claude_case(tmp_path / 'near', monkeypatch, 'M01', text=near_only)
    assert load('patch').patch_claude_md(project) == []
    assert claude_md.read_text() == near_only
    # The project file has no marker text: the second candidate .claude/CLAUDE.md is used instead.
    project, claude_md, _ = build_claude_case(tmp_path / 'second', monkeypatch, 'M01', text=CLAUDE_HEAD + 'notes\n')
    inner = project / '.claude' / 'CLAUDE.md'
    inner.parent.mkdir()
    inner.write_text(CLAUDE_HEAD + '<!-- AUTO:last-updated -->\nold\n<!-- /AUTO:last-updated -->\n')
    assert load('patch').patch_claude_md(project) == []
    assert '> Last updated: 2026-01-02' in inner.read_text() and claude_md.read_text() == CLAUDE_HEAD + 'notes\n'
