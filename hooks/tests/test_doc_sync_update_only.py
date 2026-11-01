#!/usr/bin/env python3
"""posttool-doc-sync.py updates doc files that exist and creates none.

A Write in a product repository leaves no CLAUDE.md, INDEX.md or README.md behind that was
not there before; an existing CLAUDE.md is neither prepended nor re-dated; a marked INDEX.md
is still regenerated; a Write under docs/dev/ does nothing; and nothing outside the written
file's own directory is touched (the harness home's copies included). Every run uses a
scratch HOME and scratch repositories.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / 'hooks' / 'posttool-doc-sync.py'
SCRUBBED_ENV = ('CLAUDE_PROJECT_DIR', 'CLAUDE_DOC_SYNC_ROOTS', 'CLAUDE_DOC_SYNC_STATE_ROOT')
GIT = ['git', '-c', 'user.name=sandbox', '-c', 'user.email=sandbox@example.invalid',
       '-c', 'core.hooksPath=/dev/null']
DOC_FILES = {'CLAUDE.md', 'INDEX.md', 'README.md'}
DATE_BLOCK = '<!-- AUTO:last-updated -->\n> Last updated: 2099-01-01\n<!-- /AUTO:last-updated -->\n'


def marked_index(name):
    return f'# {name}\n\n<!-- AUTO:index-stats -->\nstale\n<!-- /AUTO:index-stats -->\n'


def fresh_repository(path):
    """git init and one commit, with no CLAUDE.md, INDEX.md or README.md."""
    path.mkdir(parents=True)
    (path / 'app.txt').write_text('app\n')
    for args in (['init', '-q'], ['add', '-A'], ['commit', '-qm', 'one commit']):
        subprocess.run(GIT + args, cwd=path, check=True, capture_output=True)
    return path


def write_and_run(home, project, target, text='"""Foo."""\n'):
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    env = {key: value for key, value in os.environ.items() if key not in SCRUBBED_ENV}
    env.update(HOME=str(home), TMPDIR=str(home), CLAUDE_PROJECT_DIR=str(project),
               PYTHONDONTWRITEBYTECODE='1')
    payload = {'hook_event_name': 'PostToolUse', 'tool_name': 'Write',
               'tool_input': {'file_path': str(target)}}
    completed = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                               capture_output=True, text=True, env=env, cwd=str(project), timeout=60)
    assert completed.returncode == 0, completed.stderr
    return completed


def tree(path):
    """sha256 of every file under path, .git excluded."""
    return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in path.rglob('*') if p.is_file() and '.git' not in p.relative_to(path).parts}


def test_fresh_repository_write_creates_no_doc_file(tmp_path):
    home = tmp_path / 'home'
    fresh = fresh_repository(home / 'fresh')

    write_and_run(home, fresh, fresh / 'src' / 'foo.py')

    assert DOC_FILES.isdisjoint(os.listdir(fresh))
    assert sorted(os.listdir(fresh / 'src')) == ['foo.py']


def test_marked_index_is_still_regenerated(tmp_path):
    home = tmp_path / 'home'
    project = fresh_repository(home / 'project')
    (project / 'src').mkdir()
    index = project / 'src' / 'INDEX.md'
    index.write_text(marked_index('src'))

    write_and_run(home, project, project / 'src' / 'bar.py')

    text = index.read_text()
    assert 'stale' not in text and '`bar.py`' in text
    assert sorted(os.listdir(project / 'src')) == ['INDEX.md', 'bar.py']
    assert 'CLAUDE.md' not in os.listdir(project)


def test_existing_claude_md_is_neither_prepended_nor_redated(tmp_path):
    home = tmp_path / 'home'
    headerless = fresh_repository(home / 'headerless')
    (headerless / 'CLAUDE.md').write_text('plain notes\n')
    dated = fresh_repository(home / 'dated')
    dated_text = f'# Config\n\n{DATE_BLOCK}\nnotes\n'
    (dated / 'CLAUDE.md').write_text(dated_text)

    write_and_run(home, headerless, headerless / 'src' / 'foo.py')
    write_and_run(home, dated, dated / 'src' / 'foo.py')

    assert (headerless / 'CLAUDE.md').read_text() == 'plain notes\n'
    assert (dated / 'CLAUDE.md').read_text() == dated_text


def test_harness_claude_md_byte_identical_around_a_harness_write(tmp_path):
    home = tmp_path / 'home'
    harness = home / '.claude'
    (harness / 'commands').mkdir(parents=True)
    claude_md = harness / 'CLAUDE.md'
    claude_md.write_text(f'# Global configuration\n\n{DATE_BLOCK}\n---\n\nrules\n')
    (harness / 'commands' / 'INDEX.md').write_text(marked_index('commands'))
    product = fresh_repository(home / 'product')
    before = hashlib.sha256(claude_md.read_bytes()).hexdigest()

    # A session in the harness home, then one in a product repository.
    write_and_run(home, harness, harness / 'commands' / 'one.md', '# one\n')
    write_and_run(home, product, harness / 'commands' / 'two.md', '# two\n')

    assert hashlib.sha256(claude_md.read_bytes()).hexdigest() == before
    assert '`two.md`' in (harness / 'commands' / 'INDEX.md').read_text()


def test_docs_dev_write_does_nothing(tmp_path):
    home = tmp_path / 'home'
    project = fresh_repository(home / 'project')
    (project / 'docs' / 'dev').mkdir(parents=True)
    (project / 'docs' / 'dev' / 'INDEX.md').write_text(marked_index('dev'))
    before = tree(project)

    write_and_run(home, project, project / 'docs' / 'dev' / 'ticket-20990101-000001.md', '# t\n')
    write_and_run(home, project, project / 'docs' / 'dev' / 'specs' / 'spec-20990101-000001.md', '# s\n')

    after = tree(project)
    del after['docs/dev/ticket-20990101-000001.md'], after['docs/dev/specs/spec-20990101-000001.md']
    assert after == before


def test_product_write_leaves_the_harness_home_alone(tmp_path):
    home = tmp_path / 'home'
    harness = home / '.claude'
    (harness / 'commands').mkdir(parents=True)
    (harness / 'commands' / 'INDEX.md').write_text(marked_index('commands'))
    product = fresh_repository(home / 'product')
    before = tree(harness)

    write_and_run(home, product, product / '.claude' / 'commands' / 'sub' / 'x.md', '# x\n')

    assert tree(harness) == before
    assert sorted(os.listdir(product / '.claude' / 'commands' / 'sub')) == ['x.md']
    assert 'CLAUDE.md' not in os.listdir(product)
