#!/usr/bin/env python3
"""Tests for hooks/doc_sync/hook_ledger.py, the write-side ledger for
hook-authored side-effect files (backlog #122, M1/M2).

AC1 (docs/dev/acceptance-criteria-20260923-175747.json, ac_uid
6a3ec21b82e88deb): a dev-role agent's PostToolUse doc_sync regeneration of a
directory's INDEX.md (a real WRITTEN RegenRecord, not a SKIPPED_* one)
produces a ledger entry at
.claude/dev-registry/<dev_session_id>/hook-landed-files/ whose diff_sha256
equals an independently-recomputed sha256(git diff HEAD -- <path>).

Every scenario runs against a REAL git repository under tmp_path and calls
the REAL production functions (process_parent_dirs, record_landed_files,
resolve_dev_registry_entry) -- nothing here is mocked. Isolation mirrors
hooks/tests/test_doc_sync_index_status.py: nothing touches the checked-out
repository tree.
"""

import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

SCRUBBED_ENV = ('CLAUDE_PROJECT_DIR', 'CLAUDE_DOC_SYNC_ROOTS', 'CLAUDE_DOC_SYNC_STATE_ROOT')
IO = '<!-- AUTO:index-stats -->'
IC = '<!-- /AUTO:index-stats -->'


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
    try:
        return importlib.import_module(f'hooks.doc_sync.{name}')
    except ImportError as error:
        pytest.fail(f'hooks.doc_sync.{name} cannot be imported: {error}')


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ['git', '-C', str(repo), *args], check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def _repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, 'init', '-q', '-b', 'main')
    _git(path, 'config', 'user.email', 'tests@example.invalid')
    _git(path, 'config', 'user.name', 'Tests')
    (path / 'seed.txt').write_text('seed\n', encoding='utf-8')
    _git(path, 'add', 'seed.txt')
    _git(path, 'commit', '-q', '-m', 'seed')
    return path


def _register_dev_agent(project_dir: Path, agent_id: str, dev_session_id: str, agent_type: str = 'dev') -> None:
    index_path = project_dir / '.claude' / 'dev-registry' / 'agent-index.json'
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps({agent_id: {'agent_type': agent_type, 'dev_session_id': dev_session_id}}),
        encoding='utf-8',
    )


def _real_diff_sha256(project_dir: Path, rel_path: str) -> str:
    proc = subprocess.run(
        ['git', 'diff', 'HEAD', '--', rel_path], cwd=str(project_dir), capture_output=True, check=True,
    )
    return hashlib.sha256(proc.stdout).hexdigest()


def _seed_watched_dir_with_tracked_index(project_dir: Path, rel_dir: str) -> Path:
    """A tracked, well-formed (but stale) INDEX.md so regeneration is a real
    content change against a real committed baseline -- not a brand-new
    untracked file (whose `git diff HEAD` would be empty)."""
    d = project_dir / rel_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / 'example.py').write_text('# example\n', encoding='utf-8')
    (d / 'INDEX.md').write_text(f'# {d.name}\n\n{IO}\nstale placeholder stats\n{IC}\n', encoding='utf-8')
    _git(project_dir, 'add', rel_dir)
    _git(project_dir, 'commit', '-q', '-m', f'seed {rel_dir}')
    return d


def test_ac1_written_regeneration_produces_ledger_entry_with_matching_diff_sha256(tmp_path):
    main_mod = load('main')
    hook_ledger_mod = load('hook_ledger')

    project = _repo(tmp_path / 'project')
    watched = _seed_watched_dir_with_tracked_index(project, 'hooks/tests')

    results: list = []
    main_mod.process_parent_dirs(watched, project, results)
    written_index = [
        r for r in results
        if r.status is hook_ledger_mod.RegenStatus.WRITTEN and r.path.name == 'INDEX.md'
    ]
    assert written_index, f'expected a WRITTEN INDEX RegenRecord, got: {results}'

    agent_id = 'agent-ac1-real-regen'
    dev_session_id = 'dev-ac1-session'
    _register_dev_agent(project, agent_id, dev_session_id)

    hook_ledger_mod.record_landed_files(results, {'agent_id': agent_id}, project)

    ledger_dir = project / '.claude' / 'dev-registry' / dev_session_id / 'hook-landed-files'
    assert ledger_dir.is_dir()
    entry_files = list(ledger_dir.glob('*.json'))
    assert entry_files, 'expected at least one ledger entry file'

    rel_path = 'hooks/tests/INDEX.md'
    entries = [json.loads(p.read_text(encoding='utf-8')) for p in entry_files]
    matching = [e for e in entries if e.get('path') == rel_path]
    assert len(matching) == 1, f'expected exactly one entry for {rel_path}, got: {entries}'
    entry = matching[0]

    for field in ('path', 'diff_sha256', 'reason', 'source_agent_id', 'ts'):
        assert field in entry and entry[field], f'missing/empty required field {field!r} in {entry}'

    assert entry['source_agent_id'] == agent_id
    assert entry['diff_sha256'] == _real_diff_sha256(project, rel_path)
    # M2: honesty-compliant reason -- names hook-authorship, never implies review.
    assert 'doc-sync' in entry['reason'].lower() or 'hook' in entry['reason'].lower()
    assert 'reviewed by dev' not in entry['reason'].lower() or 'not reviewed by dev' in entry['reason'].lower()


def test_fail_open_non_dev_agent_type_writes_no_entry(tmp_path):
    main_mod = load('main')
    hook_ledger_mod = load('hook_ledger')

    project = _repo(tmp_path / 'project')
    watched = _seed_watched_dir_with_tracked_index(project, 'hooks/tests')

    results: list = []
    main_mod.process_parent_dirs(watched, project, results)

    agent_id = 'agent-qa-not-dev'
    _register_dev_agent(project, agent_id, 'dev-should-not-be-used', agent_type='qa')

    hook_ledger_mod.record_landed_files(results, {'agent_id': agent_id}, project)

    assert not (project / '.claude' / 'dev-registry' / 'dev-should-not-be-used' / 'hook-landed-files').exists()


def test_fail_open_unresolvable_agent_id_writes_no_entry(tmp_path):
    main_mod = load('main')
    hook_ledger_mod = load('hook_ledger')

    project = _repo(tmp_path / 'project')
    watched = _seed_watched_dir_with_tracked_index(project, 'hooks/tests')

    results: list = []
    main_mod.process_parent_dirs(watched, project, results)

    # No agent-index.json written at all -- resolve_dev_registry_entry() must
    # return None, and record_landed_files() must no-op, not raise.
    hook_ledger_mod.record_landed_files(results, {'agent_id': 'ghost-agent'}, project)

    assert not (project / '.claude' / 'dev-registry').exists() or not list(
        (project / '.claude' / 'dev-registry').glob('*/hook-landed-files')
    )


def test_fail_open_empty_results_is_a_no_op(tmp_path):
    hook_ledger_mod = load('hook_ledger')
    project = _repo(tmp_path / 'project')
    agent_id = 'agent-empty-results'
    _register_dev_agent(project, agent_id, 'dev-empty-results')

    hook_ledger_mod.record_landed_files([], {'agent_id': agent_id}, project)

    assert not (project / '.claude' / 'dev-registry' / 'dev-empty-results' / 'hook-landed-files').exists()


def test_two_distinct_regenerated_paths_get_two_distinct_collision_safe_entries(tmp_path):
    main_mod = load('main')
    hook_ledger_mod = load('hook_ledger')

    project = _repo(tmp_path / 'project')
    watched_a = _seed_watched_dir_with_tracked_index(project, 'hooks/tests')
    watched_b = _seed_watched_dir_with_tracked_index(project, 'scripts')

    results: list = []
    main_mod.process_parent_dirs(watched_a, project, results)
    main_mod.process_parent_dirs(watched_b, project, results)

    agent_id = 'agent-two-paths'
    dev_session_id = 'dev-two-paths'
    _register_dev_agent(project, agent_id, dev_session_id)

    hook_ledger_mod.record_landed_files(results, {'agent_id': agent_id}, project)

    ledger_dir = project / '.claude' / 'dev-registry' / dev_session_id / 'hook-landed-files'
    entries = [json.loads(p.read_text(encoding='utf-8')) for p in ledger_dir.glob('*.json')]
    paths = {e['path'] for e in entries}
    assert {'hooks/tests/INDEX.md', 'scripts/INDEX.md'} <= paths


def test_same_path_regenerated_twice_overwrites_its_own_entry_not_duplicates(tmp_path):
    main_mod = load('main')
    hook_ledger_mod = load('hook_ledger')

    project = _repo(tmp_path / 'project')
    watched = _seed_watched_dir_with_tracked_index(project, 'hooks/tests')

    agent_id = 'agent-repeat'
    dev_session_id = 'dev-repeat'
    _register_dev_agent(project, agent_id, dev_session_id)

    results_1: list = []
    main_mod.process_parent_dirs(watched, project, results_1)
    hook_ledger_mod.record_landed_files(results_1, {'agent_id': agent_id}, project)

    # Regenerate again -- the INDEX region is still well-formed, so a second
    # real regeneration fires and (nondeterministic timestamp aside) is a
    # real second WRITTEN record for the same path.
    results_2: list = []
    main_mod.process_parent_dirs(watched, project, results_2)
    hook_ledger_mod.record_landed_files(results_2, {'agent_id': agent_id}, project)

    ledger_dir = project / '.claude' / 'dev-registry' / dev_session_id / 'hook-landed-files'
    entries = [json.loads(p.read_text(encoding='utf-8')) for p in ledger_dir.glob('*.json')]
    index_entries = [e for e in entries if e['path'] == 'hooks/tests/INDEX.md']
    assert len(index_entries) == 1, f'expected one content-addressed entry, got: {index_entries}'
