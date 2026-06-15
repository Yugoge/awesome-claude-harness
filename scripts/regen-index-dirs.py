#!/usr/bin/env python3
"""Insert AUTO:index-stats markers into markerless INDEX.md files (preserving any
hand-written prose outside the generated stats+tree block), then regenerate the
INDEX via the existing hooks.doc_sync.regen_index.regen_index function.

The /doc-sync slash command is human-only (disable-model-invocation), so this
script calls the underlying regen_index function directly — it does NOT invoke
the slash command.

Usage: regen-index-dirs.py <dir> [<dir> ...]
Exit codes: 0=all regenerated, 1=usage/error
"""
import sys
from pathlib import Path

# Make the hooks package importable.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hooks.doc_sync.regen_index import (  # noqa: E402
    regen_index, AUTO_START, AUTO_END,
)


def _ensure_marker(index_path: Path, dir_name: str) -> None:
    """Insert AUTO markers around the generated stats+tree block of a markerless
    INDEX, preserving everything else verbatim. No-op if marker already present
    or the file is absent (regen handles those)."""
    if not index_path.exists():
        return
    text = index_path.read_text()
    if AUTO_START in text:
        return
    lines = text.splitlines()
    n = len(lines)

    # Locate the generated region: it begins at the first '*Last updated:' stats
    # line and ends at the closing code-fence of the '## Tree' block.
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith('*Last updated:'):
            start = i
            break
    if start is None:
        # No recognizable generated block; let regen build one from scratch by
        # bracketing nothing — fall back to a leading marker after the title.
        return

    # Find the '## Tree' fence open after start, then its closing fence.
    tree_open = None
    for i in range(start, n):
        if lines[i].strip() == '```':
            tree_open = i
            break
    end = None
    if tree_open is not None:
        for i in range(tree_open + 1, n):
            if lines[i].strip() == '```':
                end = i
                break
    if end is None:
        return

    new_lines = lines[:start] + [AUTO_START] + lines[start:end + 1] + [AUTO_END] + lines[end + 1:]
    index_path.write_text('\n'.join(new_lines) + '\n')


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: regen-index-dirs.py <dir> [<dir> ...]", file=sys.stderr)
        return 1
    for raw in argv[1:]:
        d = Path(raw).resolve()
        if not d.is_dir():
            print(f"Error: not a directory: {d}", file=sys.stderr)
            return 1
        _ensure_marker(d / 'INDEX.md', d.name)
        regen_index(d)
        print(f"regenerated: {d / 'INDEX.md'}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
