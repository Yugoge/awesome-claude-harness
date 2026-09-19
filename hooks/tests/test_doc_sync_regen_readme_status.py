#!/usr/bin/env python3
"""Regression tests for the status regen_readme() reports and the zero-write skip paths.

Backlog #83: regen_readme() returned None on every path, so nobody could tell a skipped
README from a regenerated one, and a README with an opening marker but no closing marker
was rewritten with identical bytes (mtime changed, looking like a regeneration).

Every scenario runs on a synthetic directory under tmp_path; nothing touches the
repository tree. HOME and TMPDIR are redirected as well, so a stray regeneration of a
global directory cannot write into the real ~/.claude.

The new symbols (RegenStatus, ...) are reached through module attributes inside the test
bodies, never through a module-level from-import: against the pre-change modules the tests
then fail one by one instead of failing at collection.
"""

import builtins
import importlib
import importlib.util
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

regen_readme_module = importlib.import_module('hooks.doc_sync.regen_readme')
patch_module = importlib.import_module('hooks.doc_sync.patch')

OPEN = '<!-- AUTO:readme-stats -->'
CLOSE = '<!-- /AUTO:readme-stats -->'
# 2001-09-09: clearly earlier than any real mtime, so a rewrite cannot hide behind a
# timestamp that happens to be equal.
EARLIER_NS = 1_000_000_000 * 10**9

README_TEXTS = {
    'S2': f'# Hand title\n\nhand text before\n\n{OPEN}\nstale stats\n{CLOSE}\n\nhand text after\n',
    'S3': f'# Legacy\n\nhand text\n\n{OPEN}\nstale stats without a terminator\n',
    'S4': '# Hand written\n\nno markers at all\n',
    'S5': f'# Reversed\n{CLOSE}\nmiddle\n{OPEN}\nstale\n',
    'S5b': f'{CLOSE}\nmiddle\n{OPEN}\nstale\n{CLOSE}\n',
    'S6': f'# Closing only\n\n{CLOSE}\n',
}
EXPECTED_STATUS = {
    'S1': 'WRITTEN',
    'S2': 'WRITTEN',
    'S3': 'SKIPPED_NO_CLOSING_MARKER',
    'S4': 'SKIPPED_NO_OPENING_MARKER',
    'S5': 'SKIPPED_NO_CLOSING_MARKER',
    'S5b': 'SKIPPED_NO_CLOSING_MARKER',
    'S6': 'SKIPPED_NO_OPENING_MARKER',
    'S7github': 'SKIPPED_GITHUB_RESERVED',
    'S7workflows': 'SKIPPED_GITHUB_RESERVED',
}
ALL_SCENARIOS = list(EXPECTED_STATUS)
SKIP_SCENARIOS = ['S3', 'S4', 'S5', 'S5b', 'S6']
RESERVED_SCENARIOS = ['S7github', 'S7workflows']


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    scratch_tmp = tmp_path / 'tmp'
    home.mkdir()
    scratch_tmp.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('TMPDIR', str(scratch_tmp))
    for name in ('CLAUDE_PROJECT_DIR', 'CLAUDE_DOC_SYNC_ROOTS', 'CLAUDE_DOC_SYNC_STATE_ROOT'):
        monkeypatch.delenv(name, raising=False)


def build_scenario(tmp_path, scenario):
    """(project root, directory to regenerate, its README path) for one scenario id."""
    project = tmp_path / 'project'
    if scenario == 'S7github':
        directory = project / '.github'
    elif scenario == 'S7workflows':
        directory = project / '.github' / 'workflows'
    else:
        directory = project / 'folder'
    directory.mkdir(parents=True)
    (directory / 'alpha.py').write_text('"""Alpha helper."""\n')
    readme = directory / 'README.md'
    if scenario in README_TEXTS:
        readme.write_text(README_TEXTS[scenario])
    return project, directory, readme


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


@pytest.mark.parametrize('scenario', ALL_SCENARIOS)
def test_status_contract_returns_a_status_member(tmp_path, scenario):
    """Every path returns one of the four RegenStatus members, never None."""
    project, directory, readme = build_scenario(tmp_path, scenario)
    status_enum = regen_readme_module.RegenStatus
    needs_update_before = regen_readme_module._readme_needs_update(readme)

    result = regen_readme_module.regen_readme(directory, project)

    assert result is not None
    assert any(result is member for member in status_enum), result
    assert result is status_enum[EXPECTED_STATUS[scenario]]
    # _readme_needs_update is True only for an absent or a well-formed README.
    assert needs_update_before is (scenario in ('S1', 'S2', 'S7github', 'S7workflows'))


@pytest.mark.parametrize('scenario', SKIP_SCENARIOS + RESERVED_SCENARIOS)
def test_skip_zero_write_leaves_bytes_and_mtime_alone(tmp_path, monkeypatch, scenario):
    """A skip path performs no write: bytes, mtime and the write counters stay untouched."""
    project, directory, readme = build_scenario(tmp_path, scenario)
    existed = readme.exists()
    if existed:
        os.utime(readme, ns=(EARLIER_NS, EARLIER_NS))
        before_bytes = readme.read_bytes()
        before_mtime = readme.stat().st_mtime_ns
    spy = WriteSpy(monkeypatch, readme)

    result = regen_readme_module.regen_readme(directory, project)

    # The write-side checks come first: they are what the fake write (S3) and the growing
    # rewrite (S5) violate, independent of whether a status is returned.
    assert spy.calls == []
    assert readme.exists() is existed
    if existed:
        assert readme.read_bytes() == before_bytes
        assert readme.stat().st_mtime_ns == before_mtime == EARLIER_NS
    assert result is regen_readme_module.RegenStatus[EXPECTED_STATUS[scenario]]


def test_matrix_S1_first_readme_of_a_fresh_folder(tmp_path):
    """A folder without README gets a first-generation README with both markers and the footer."""
    project, directory, readme = build_scenario(tmp_path, 'S1')

    result = regen_readme_module.regen_readme(directory, project)

    text = readme.read_text()
    assert result is regen_readme_module.RegenStatus.WRITTEN
    assert text.index(OPEN) < text.index(CLOSE)
    assert '**Total files**: 1' in text
    assert '`alpha.py`' in text
    assert text.rstrip().endswith('*Auto-generated by doc-sync hook.*')


def test_matrix_S1rerun_growth_is_reflected(tmp_path):
    """A second file added after the first generation shows up on the rerun."""
    project, directory, readme = build_scenario(tmp_path, 'S1')
    regen_readme_module.regen_readme(directory, project)
    (directory / 'beta.py').write_text('"""Beta helper."""\n')

    result = regen_readme_module.regen_readme(directory, project)

    text = readme.read_text()
    assert result is regen_readme_module.RegenStatus.WRITTEN
    assert '**Total files**: 2' in text
    assert '`beta.py`' in text
    assert text.count(OPEN) == 1 and text.count(CLOSE) == 1


def test_matrix_S2_wellformed_readme_keeps_hand_text(tmp_path):
    """Hand text outside the AUTO region is preserved byte for byte; the region is refreshed."""
    project, directory, readme = build_scenario(tmp_path, 'S2')

    result = regen_readme_module.regen_readme(directory, project)

    text = readme.read_text()
    original = README_TEXTS['S2']
    assert result is regen_readme_module.RegenStatus.WRITTEN
    assert text.startswith(original[:original.index(OPEN) + len(OPEN)])
    assert text.endswith(original[original.index(CLOSE):])
    assert 'stale stats' not in text
    assert '**Total files**: 1' in text


@pytest.mark.parametrize('scenario', SKIP_SCENARIOS + RESERVED_SCENARIOS)
def test_matrix_skip_states_report_the_reason_and_change_nothing(tmp_path, scenario):
    """Malformed and hand-written READMEs (S3-S6) and the reserved .github tree (S7) are skipped."""
    project, directory, readme = build_scenario(tmp_path, scenario)
    before = readme.read_bytes() if readme.exists() else None

    result = regen_readme_module.regen_readme(directory, project)

    assert result is regen_readme_module.RegenStatus[EXPECTED_STATUS[scenario]]
    assert (readme.read_bytes() if readme.exists() else None) == before


@pytest.mark.parametrize('scenario', ['S5', 'S5b'])
def test_matrix_reversed_markers_do_not_grow_the_file(tmp_path, scenario):
    """Repeated runs on a README whose closing marker comes first change nothing (it used to grow)."""
    project, directory, readme = build_scenario(tmp_path, scenario)

    for _ in range(3):
        regen_readme_module.regen_readme(directory, project)

    assert readme.read_text() == README_TEXTS[scenario]


REPLACE_SECTION_CASES = {
    'wellformed': (f'head\n{OPEN}\nold\n{CLOSE}\ntail\n', True),
    'missing_open': (f'head\nold\n{CLOSE}\ntail\n', False),
    'missing_close': (f'head\n{OPEN}\nold\ntail\n', False),
    'close_before_open': (f'head\n{CLOSE}\nmiddle\n{OPEN}\nold\ntail\n', False),
}


@pytest.mark.parametrize('case', list(REPLACE_SECTION_CASES))
def test_replace_section_only_wellformed_input_is_replaced(case):
    """_replace_section returns anything without an ordered marker pair unchanged."""
    text, replaced = REPLACE_SECTION_CASES[case]

    result = patch_module._replace_section(text, 'readme-stats', 'NEW BODY')

    if replaced:
        assert result == f'head\n{OPEN}\nNEW BODY\n{CLOSE}\ntail\n'
    else:
        assert result == text


@pytest.mark.parametrize('scenario', ['S2', 'S3', 'S4', 'S5', 'S5b', 'S6'])
def test_replace_section_agrees_with_the_readme_classifier(tmp_path, scenario):
    """A README is regenerated exactly when _replace_section would actually replace its region."""
    _, _, readme = build_scenario(tmp_path, scenario)
    text = README_TEXTS[scenario]

    replaceable = patch_module._replace_section(text, 'readme-stats', 'NEW BODY') != text

    assert regen_readme_module._readme_needs_update(readme) is replaceable


CLAUDE_MD_HEAD = '# CLAUDE.md\n\n> Project-specific settings for demo\n\n'


@pytest.mark.parametrize('case', ['single_pair', 'reversed_pair'])
def test_patch_claude_md_touches_only_a_wellformed_last_updated_pair(tmp_path, case):
    """patch_claude_md refreshes a single last-updated pair and leaves a reversed pair alone."""
    project = tmp_path / 'project'
    project.mkdir()
    open_marker = '<!-- AUTO:last-updated -->'
    close_marker = '<!-- /AUTO:last-updated -->'
    if case == 'single_pair':
        text = f'{CLAUDE_MD_HEAD}{open_marker}\n> Last updated: 2001-01-01\n{close_marker}\n\nhand notes\n'
    else:
        text = f'{CLAUDE_MD_HEAD}{close_marker}\nmiddle\n{open_marker}\n> Last updated: 2001-01-01\n\nhand notes\n'
    claude_md = project / 'CLAUDE.md'
    claude_md.write_text(text)
    date_before = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    patch_module.patch_claude_md(project)

    date_after = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if case == 'single_pair':
        expected = {
            f'{CLAUDE_MD_HEAD}{open_marker}\n> Last updated: {date}\n{close_marker}\n\nhand notes\n'
            for date in (date_before, date_after)
        }
        assert claude_md.read_text() in expected
    else:
        assert claude_md.read_text() == text


def load_regen_readme(mode):
    if mode == 'package_import':
        return importlib.import_module('hooks.doc_sync.regen_readme')
    path = REPO_ROOT / 'hooks' / 'doc_sync' / 'regen_readme.py'
    spec = importlib.util.spec_from_file_location('regen_readme_standalone_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('mode', ['package_import', 'standalone_shim_import'])
def test_import_mode_exposes_status_and_reports_the_same_results(tmp_path, mode):
    """Both load paths (relative import, standalone spec_from_file_location shim) expose RegenStatus."""
    module = load_regen_readme(mode)
    if mode == 'standalone_shim_import':
        # No parent package means the relative imports failed and the shim branch ran.
        assert not module.__package__

    seen = {}
    for scenario in ('S3', 'S4'):
        project, directory, _ = build_scenario(tmp_path / mode / scenario, scenario)
        seen[scenario] = module.regen_readme(directory, project)

    assert hasattr(module, 'RegenStatus')
    assert seen['S3'].name == 'SKIPPED_NO_CLOSING_MARKER'
    assert seen['S4'].name == 'SKIPPED_NO_OPENING_MARKER'
