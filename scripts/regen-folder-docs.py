#!/usr/bin/env python3
"""Regenerates every doc-sync section of the tree, or checks that none has drifted.

doc-sync regenerates a folder's INDEX.md and README.md AUTO regions only when a live harness
session writes a file in that folder, so a folder no session touched (and every cloud session or
CI run) keeps whatever was generated last. This command runs the same rendering
(hooks/doc_sync regen_readme.render_readme and regen_index.render_index, written through
folder_doc.write_folder_doc, the one writer) over every git-tracked INDEX.md and README.md.

Usage: regen-folder-docs.py           regenerate every drifted section, naming each file written
       regen-folder-docs.py --check   write nothing; exit 1 naming each file that differs from
                                      what the writer would produce, or whose doc-sync region
                                      the writer refuses (so it can never be kept current)
Exit codes: 0 = nothing drifted (or everything regenerated), 1 = drift or refusal, 2 = usage.

Run it on a clean tree: the writer lists git-tracked files only, so a file to be listed must be
added to the index first.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from hooks.doc_sync.folder_doc import write_folder_doc  # noqa: E402
from hooks.doc_sync.main import _is_excluded  # noqa: E402
from hooks.doc_sync.regen_index import render_index  # noqa: E402
from hooks.doc_sync.regen_readme import render_readme  # noqa: E402
from hooks.doc_sync.regions import (  # noqa: E402
    INDEX_MARKER_ID, README_MARKER_ID, RegenStatus, marker_open,
)

RENDERERS = {
    'README.md': (render_readme, README_MARKER_ID),
    'INDEX.md': (render_index, INDEX_MARKER_ID),
}
# A file the writer does not manage at all: no such region, or a folder it never writes.
NOT_MANAGED = {
    RegenStatus.SKIPPED_ABSENT,
    RegenStatus.SKIPPED_GITHUB_RESERVED,
    RegenStatus.SKIPPED_NO_OPENING_MARKER,
}


def tracked_folder_docs(root: Path) -> list[Path]:
    """Every git-tracked INDEX.md and README.md under `root`, outside doc-sync's exclusions."""
    out = subprocess.run(
        ['git', '-C', str(root), 'ls-files', '-z', '--', '*INDEX.md', '*README.md'],
        capture_output=True, check=True,
    ).stdout.decode('utf-8', errors='replace')
    docs = []
    for rel in sorted(entry for entry in out.split('\0') if entry):
        if Path(rel).name in RENDERERS and not _is_excluded(rel):
            docs.append(root / rel)
    return docs


def run(root: Path, check: bool) -> int:
    drifted: list[str] = []
    refused: list[str] = []
    for path in tracked_folder_docs(root):
        render, marker_id = RENDERERS[path.name]
        status, text = render(path.parent, root)
        rel = path.relative_to(root).as_posix()
        if text is None:
            if status not in NOT_MANAGED and marker_open(marker_id) in path.read_text():
                refused.append(f'{rel} ({status.value})')
            continue
        if text == path.read_text():
            continue
        drifted.append(rel)
        if not check:
            write_folder_doc(path, text, root)
    verb = 'differs from the generator' if check else 'regenerated'
    for rel in drifted:
        print(f'{verb}: {rel}')
    for item in refused:
        print(f'refused by the writer, so never regenerated: {item}')
    if check and (drifted or refused):
        print(f'regen-folder-docs: {len(drifted)} drifted, {len(refused)} refused; '
              'run scripts/regen-folder-docs.py on a clean tree and commit the result',
              file=sys.stderr)
        return 1
    if refused:
        return 1
    if check:
        print('regen-folder-docs: every doc-sync section matches the generator')
    return 0


def main(argv: list[str]) -> int:
    if argv not in ([], ['--check']):
        print(__doc__.split('\n\n')[1], file=sys.stderr)
        return 2
    return run(REPO_ROOT, check=argv == ['--check'])


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
