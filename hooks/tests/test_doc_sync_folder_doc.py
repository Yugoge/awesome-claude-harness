#!/usr/bin/env python3
"""hooks/doc_sync/folder_doc.py is the one writer of a folder's INDEX.md and README.md.

doc-sync's regeneration, /clean's generate-folder-index.sh and generate-folder-readme.sh,
and the prompt-time INDEX removal (hooks/userprompt-doc-sync-check.py) all write through
it. The routing tests swap the writer for a stub that records its arguments and writes
nothing: if a caller still wrote the file itself, the file would appear.
"""

import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
WRITER = REPO_ROOT / 'hooks' / 'doc_sync' / 'folder_doc.py'
SCRIPTS = REPO_ROOT / 'scripts'
RELAY_HOOK = REPO_ROOT / 'hooks' / 'userprompt-doc-sync-check.py'
OPEN, CLOSE = '<!-- AUTO:index-stats -->', '<!-- /AUTO:index-stats -->'
STUB = '''import json, sys
with open(sys.argv[0] + '.log', 'a') as log:
    log.write(json.dumps(sys.argv[1:]) + '\\n')
sys.stdin.read() if '--remove' not in sys.argv else None
'''


def env(**extra):
    environment = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
    environment.update(extra)
    return environment


def git_repo(root):
    root.mkdir(parents=True)
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    return root


def run_writer(*args, stdin=''):
    return subprocess.run([sys.executable, str(WRITER), *map(str, args)], input=stdin, capture_output=True,
                          text=True, env=env(), timeout=60)


def stub_harness(tmp_path, *scripts):
    """A harness copy whose writer is the recording stub; returns (scripts dir, stub log)."""
    harness = tmp_path / 'harness'
    (harness / 'scripts').mkdir(parents=True)
    (harness / 'hooks' / 'doc_sync').mkdir(parents=True)
    for name in scripts:
        shutil.copy(SCRIPTS / name, harness / 'scripts' / name)
    stub = harness / 'hooks' / 'doc_sync' / 'folder_doc.py'
    stub.write_text(STUB)
    return harness, Path(str(stub) + '.log')


def test_writer_writes_removes_and_refuses_the_root_github_subtree(tmp_path):
    repo = git_repo(tmp_path / 'repo')
    for folder in ('sub', '.github/workflows', 'src/.github'):
        (repo / folder).mkdir(parents=True)

    assert run_writer(repo / 'sub' / 'INDEX.md', stdin='# sub\n').returncode == 0
    assert (repo / 'sub' / 'INDEX.md').read_text() == '# sub\n'
    assert run_writer('--remove', repo / 'sub' / 'INDEX.md').returncode == 0
    assert not (repo / 'sub' / 'INDEX.md').exists()

    refused = run_writer(repo / '.github' / 'workflows' / 'README.md', stdin='x')
    assert refused.returncode == 0 and 'Skipping GitHub-reserved subtree' in refused.stderr
    assert not (repo / '.github' / 'workflows' / 'README.md').exists()
    # The rule doc-sync applies: only the repository's own root-level .github is reserved.
    assert run_writer(repo / 'src' / '.github' / 'INDEX.md', stdin='y').returncode == 0
    assert (repo / 'src' / '.github' / 'INDEX.md').read_text() == 'y'
    assert run_writer(repo / 'missing' / 'INDEX.md', stdin='z').returncode == 1


def test_generate_folder_scripts_hand_their_text_to_the_writer(tmp_path):
    harness, log = stub_harness(tmp_path, 'generate-folder-index.sh', 'generate-folder-readme.sh')
    folder = git_repo(tmp_path / 'repo') / 'sub'
    folder.mkdir()
    (folder / 'a.py').write_text('x\n')

    for script, args in (('generate-folder-index.sh', []), ('generate-folder-readme.sh', ['Purpose', '.py', 'snake'])):
        completed = subprocess.run(['bash', str(harness / 'scripts' / script), str(folder), *args],
                                   capture_output=True, text=True, env=env(), timeout=60)
        assert completed.returncode == 0, completed.stderr

    assert [json.loads(line) for line in log.read_text().splitlines()] == [
        [str(folder / 'INDEX.md')], [str(folder / 'README.md')]]
    assert not (folder / 'INDEX.md').exists() and not (folder / 'README.md').exists()


def test_generate_folder_scripts_write_their_text_through_the_real_writer(tmp_path):
    repo = git_repo(tmp_path / 'repo')
    (repo / 'sub').mkdir()
    (repo / 'sub' / 'a.py').write_text('x\n')
    (repo / '.github').mkdir()

    for folder in ('sub', '.github'):
        for script, args in (('generate-folder-index.sh', []),
                             ('generate-folder-readme.sh', ['Purpose', '.py', 'snake'])):
            completed = subprocess.run(['bash', str(SCRIPTS / script), str(repo / folder), *args],
                                       capture_output=True, text=True, env=env(), timeout=60)
            assert completed.returncode == 0, completed.stderr

    assert '- `a.py`' in (repo / 'sub' / 'INDEX.md').read_text()
    assert '## Naming Convention\n\nsnake' in (repo / 'sub' / 'README.md').read_text()
    assert sorted(os.listdir(repo / '.github')) == []


def test_doc_sync_regeneration_writes_through_the_writer(tmp_path, monkeypatch):
    regen_index = importlib.import_module('hooks.doc_sync.regen_index')
    regen_readme = importlib.import_module('hooks.doc_sync.regen_readme')
    regions = importlib.import_module('hooks.doc_sync.regions')
    folder = tmp_path / 'folder'
    folder.mkdir()
    (folder / 'a.py').write_text('"""A."""\n')
    (folder / 'INDEX.md').write_text(f'# folder\n\n{OPEN}\n{CLOSE}\n')
    (folder / 'README.md').write_text('# folder\n\n<!-- AUTO:readme-stats -->\n<!-- /AUTO:readme-stats -->\n')
    calls = []

    def recorder(path, text, project_dir=None):
        calls.append(Path(path).name)
        return regions.RegenStatus.WRITTEN
    monkeypatch.setattr(regen_index, 'write_folder_doc', recorder)
    monkeypatch.setattr(regen_readme, 'write_folder_doc', recorder)

    assert regen_index.regen_index(folder, tmp_path) is regions.RegenStatus.WRITTEN
    assert regen_readme.regen_readme(folder, tmp_path) is regions.RegenStatus.WRITTEN
    assert calls == ['INDEX.md', 'README.md']
    assert (folder / 'INDEX.md').read_text() == f'# folder\n\n{OPEN}\n{CLOSE}\n'


def emptied_home(tmp_path, harness_writer=None):
    """A HOME whose watched .claude/commands lost its last file since the cached snapshot."""
    home = tmp_path / 'home'
    hooks_dir = home / '.claude' / 'hooks'
    commands = home / '.claude' / 'commands'
    hooks_dir.mkdir(parents=True)
    commands.mkdir()
    shutil.copytree(REPO_ROOT / 'hooks' / 'doc_sync', hooks_dir / 'doc_sync',
                    ignore=shutil.ignore_patterns('__pycache__', 'README.md', 'INDEX.md'))
    if harness_writer is not None:
        (hooks_dir / 'doc_sync' / 'folder_doc.py').write_text(harness_writer)
    (commands / 'INDEX.md').write_text('# commands\n')
    cache = {'last_check': 0, 'snapshots': {str(commands): ['gone.md']}}
    (home / '.claude' / '.doc-sync-cache.json').write_text(json.dumps(cache))
    return home, commands / 'INDEX.md', hooks_dir / 'doc_sync' / 'folder_doc.py.log'


def run_relay(home, tmp_path):
    environment = env(HOME=str(home), TMPDIR=str(tmp_path),
                      PATH=os.path.dirname(sys.executable) + os.pathsep + os.environ.get('PATH', ''))
    for name in ('CLAUDE_PROJECT_DIR', 'CLAUDE_DOC_SYNC_ROOTS', 'CLAUDE_DOC_SYNC_STATE_ROOT'):
        environment.pop(name, None)
    return subprocess.run([sys.executable, str(RELAY_HOOK)], capture_output=True, text=True, env=environment,
                          cwd=str(home), timeout=120)


def test_prompt_hook_removes_an_emptied_directorys_index_through_the_writer(tmp_path):
    home, index, _ = emptied_home(tmp_path / 'real')
    assert run_relay(home, tmp_path / 'real').returncode == 0
    assert not index.exists()

    home, index, log = emptied_home(tmp_path / 'stub', harness_writer=STUB)
    assert run_relay(home, tmp_path / 'stub').returncode == 0
    assert index.exists(), 'the hook removed the INDEX itself instead of handing it to the writer'
    assert json.loads(log.read_text()) == ['--remove', str(index)]
