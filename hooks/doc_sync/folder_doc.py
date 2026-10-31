#!/usr/bin/env python3
"""The one writer of a folder's INDEX.md and README.md.

doc-sync's regeneration, /clean's scripts/generate-folder-index.sh and
scripts/generate-folder-readme.sh (which hand it their text on stdin), and the prompt-time
removal of an emptied watched directory's INDEX.md (hooks/userprompt-doc-sync-check.py) all
write through write_folder_doc, so one rule decides what may land in those files: nothing
under the repository's own .github subtree (config.is_github_reserved_subtree).

Run as a file it imports only its two leaf siblings, so the prompt hook (which must not
import doc_sync) and the shell scripts can call it without loading the package.
Usage: folder_doc.py <path>            (the new text on stdin)
       folder_doc.py --remove <path>
"""

import subprocess
import sys
from pathlib import Path

try:
    from .config import is_github_reserved_subtree
    from .regions import RegenStatus
except ImportError:  # run as a file: its own directory is sys.path[0]
    from config import is_github_reserved_subtree  # type: ignore[no-redef]
    from regions import RegenStatus  # type: ignore[no-redef]


def write_folder_doc(path: Path, text: str | None, project_dir: Path | None = None) -> RegenStatus:
    """Replace the file at `path` with `text`, or remove it when `text` is None."""
    path = Path(path)
    if is_github_reserved_subtree(path.parent, project_dir):
        return RegenStatus.SKIPPED_GITHUB_RESERVED
    if text is None:
        path.unlink(missing_ok=True)
    else:
        path.write_text(text)
    return RegenStatus.WRITTEN


def _repo_root(folder: Path) -> Path | None:
    """The work tree holding `folder`, which anchors the reserved-subtree rule as doc-sync's
    project directory does; None outside a repository (the rule then reads the path as written)."""
    try:
        proc = subprocess.run(['git', '-C', str(folder), 'rev-parse', '--show-toplevel'],
                              capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return Path(proc.stdout.strip()) if proc.returncode == 0 and proc.stdout.strip() else None


def main(argv: list[str]) -> int:
    remove = argv[:1] == ['--remove']
    args = argv[1:] if remove else argv
    if len(args) != 1:
        print('Usage: folder_doc.py [--remove] <path>', file=sys.stderr)
        return 1
    path = Path(args[0]).absolute()
    if not path.parent.is_dir():
        print(f'Error: Folder not found: {path.parent}', file=sys.stderr)
        return 1
    status = write_folder_doc(path, None if remove else sys.stdin.read(), _repo_root(path.parent))
    if status is RegenStatus.SKIPPED_GITHUB_RESERVED:
        print(f'Skipping GitHub-reserved subtree: {path}', file=sys.stderr)
    elif not remove:
        print(f'Generated: {path}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
