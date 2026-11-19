#!/usr/bin/env python3
"""Regenerate INDEX.md for a directory."""

import re
from datetime import datetime, timezone
from pathlib import Path
from .regions import (
    INDEX_MARKER_ID, RegenStatus, RegionShape, classify_region, marker_close,
    marker_line_numbers, marker_open,
)
from .tree import build_tree

# Dual-mode import: relative in production, package-context fallback when this
# module is loaded standalone via importlib spec_from_file_location (mirrors the
# regen_readme/tree.py pattern so the git-tracked filter resolves either way).
try:
    from .config import SKIP_FILES, tracked_names, tracked_relpaths, is_github_reserved_subtree, work_tree_root
    from .folder_doc import write_folder_doc
except ImportError:
    import importlib as _importlib
    import os as _os
    import sys as _sys
    _pkg_root = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    if _pkg_root not in _sys.path:
        _sys.path.insert(0, _pkg_root)
    _cfg = _importlib.import_module("hooks.doc_sync.config")
    SKIP_FILES = _cfg.SKIP_FILES  # type: ignore[no-redef]
    tracked_names = _cfg.tracked_names  # type: ignore[no-redef]
    tracked_relpaths = _cfg.tracked_relpaths  # type: ignore[no-redef]
    is_github_reserved_subtree = _cfg.is_github_reserved_subtree  # type: ignore[no-redef]
    work_tree_root = _cfg.work_tree_root  # type: ignore[no-redef]
    write_folder_doc = _importlib.import_module("hooks.doc_sync.folder_doc").write_folder_doc  # type: ignore[no-redef]


def _detect_convention(dir_path: Path) -> str:
    """Detect naming convention from existing published files (untracked ones, such as a
    __pycache__, would make the text differ between a working tree and a clean checkout)."""
    published = tracked_names(dir_path)
    files = [f for f in dir_path.iterdir() if published is None or f.name in published]
    if not files:
        return 'kebab'
    lower_count = sum(1 for f in files if f.name.islower())
    kebab_count = sum(1 for f in files if '-' in f.name)
    if kebab_count > len(files) // 2:
        return 'kebab'
    if lower_count == len(files):
        return 'lower'
    return 'kebab'


def _build_stats(dir_path: Path) -> dict:
    published = tracked_names(dir_path)
    total = 0
    dirs = 0
    for item in dir_path.iterdir():
        if item.name in SKIP_FILES:
            continue
        if item.name.startswith('.'):
            continue
        # AC-WS5-1: when git is consulted, list only published (tracked) entries.
        if published is not None and item.name not in published:
            continue
        total += 1
        if item.is_dir():
            dirs += 1
    return {'total': total, 'dirs': dirs}


# A build_tree line is "<indent><connector> <body>", where <indent> is N
# repetitions of a 4-char unit ("│   " or "    "), <connector> is "├── "/"└── ",
# and <body> is either "`name` - desc" (a file) or "name/" (a directory). Parsing
# the indent gives the entry's depth; a name stack reconstructs each entry's full
# relative path so it can be checked against the git-tracked relpath set — pruning
# nested untracked/gitignored entries WITHOUT editing tree.py (out of WS5 scope).
_TREE_LINE_RE = re.compile(r'^((?:(?:│   )|(?:    ))*)([├└]── )(.*)$')


def _parse_tree_entry(line: str):
    """Return (depth, name, is_dir) for a build_tree line, or None if unparseable."""
    m = _TREE_LINE_RE.match(line)
    if not m:
        return None
    depth = len(m.group(1)) // 4
    body = m.group(3)
    if body.endswith('/'):
        return depth, body[:-1], True
    fm = re.match(r'^`([^`]+)`', body)
    if fm:
        return depth, fm.group(1), False
    return None


def _filter_tree_published(tree: list[str], dir_path: Path) -> list[str]:
    """Drop tree lines (at any depth) for entries that are not git-published, so
    the INDEX tree lists only tracked files (AC-WS5-1). A directory is kept iff it
    contains at least one tracked file. Degrades to a no-op when git was not
    consulted (tracked_relpaths -> None)."""
    relpaths = tracked_relpaths(dir_path)
    if relpaths is None:
        return tree
    tracked_dirs = {rp.rsplit('/', 1)[0] for rp in relpaths if '/' in rp}
    kept: list[str] = []
    stack: list[str] = []      # name stack: stack[d] is the ancestor name at depth d
    keep_at: list[bool] = []   # keep_at[d] mirrors whether that ancestor was kept
    for line in tree:
        parsed = _parse_tree_entry(line)
        if parsed is None:
            kept.append(line)
            continue
        depth, name, is_dir = parsed
        del stack[depth:]
        del keep_at[depth:]
        rel = '/'.join(stack + [name])
        if is_dir:
            published = rel in tracked_dirs or any(
                rp == rel or rp.startswith(rel + '/') for rp in relpaths)
        else:
            published = rel in relpaths
        parent_kept = all(keep_at) if keep_at else True
        stack.append(name)
        keep_at.append(published)
        if parent_kept and published:
            kept.append(line)
    return kept


AUTO_START = marker_open(INDEX_MARKER_ID)
AUTO_END = marker_close(INDEX_MARKER_ID)
_FOOTER = '*Auto-generated by doc-sync hook.*'


def _extract_preserved(old: str, dir_name: str) -> str:
    """Hand-written prose from a MARKED INDEX.md: everything outside the generated region.
    The generated region is the classifier's opening..closing marker lines, so fenced example
    markers in the hand text are never mistaken for it. Strips: the leading title line, that
    region, and the trailing `---`+footer pair at the very end. Human `---`, `**Convention**:`,
    or `## Tree` prose OUTSIDE the region is preserved verbatim. Idempotent. Lines are split on
    newline only: a form feed or U+2028 inside hand text is not a line break."""
    lines = old.split('\n')
    n = len(lines)
    remove = [False] * n
    title = f'# {dir_name}'
    first = 0
    while first < n and not lines[first].strip():
        first += 1
    if first < n and lines[first].rstrip() == title:
        remove[first] = True
    region = classify_region(old, INDEX_MARKER_ID)
    if region.shape is RegionShape.WELL_FORMED:
        for idx in range(region.open_line - 1, region.close_line):
            remove[idx] = True
    last = n - 1
    while last >= 0 and not lines[last].strip():
        last -= 1
    if last >= 0 and lines[last].strip() == _FOOTER:
        p = last - 1
        while p >= 0 and not lines[p].strip():
            p -= 1
        if p >= 0 and lines[p].strip() == '---':
            remove[last] = True
            remove[p] = True
    preserved = [lines[idx] for idx in range(n) if not remove[idx]]
    while preserved and not preserved[0].strip():
        preserved.pop(0)
    while preserved and not preserved[-1].strip():
        preserved.pop()
    return '\n'.join(preserved)


def _folder_name(dir_path: Path, old: str) -> str:
    """The name the INDEX gives its folder: the directory's own name, except at the top level
    of its git work tree, whose directory is named by wherever it was cloned (~/.claude for a
    harness home, a CI work path, a public copy under another name); there the title the file
    already carries is kept, so the text does not depend on the clone's location. The root is
    the repository's own, never the session's project directory, so a clone nested in that
    directory keeps its title too."""
    root = work_tree_root(dir_path)
    try:
        at_root = root is not None and dir_path.resolve() == root
    except OSError:
        at_root = False
    if at_root:
        for line in old.split('\n'):
            if line.strip():
                if line.startswith('# ') and line[2:].strip():
                    return line[2:].strip()
                break
    return dir_path.name


def _build_index_block(dir_path: Path, convention: str, name: str | None = None) -> list[str]:
    """The generated lines between the markers."""
    tree = _filter_tree_published(build_tree(dir_path, max_depth=3), dir_path)
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    lines = [
        f'*Last updated: {ts}*',
        f'**Total entries**: {len(tree)}',
        f'**Convention**: {convention}',
        '',
        '## Tree',
        '```',
        f'{name or dir_path.name}/',
    ]
    lines.extend(tree)
    lines.append('```')
    return lines


def _compose_index(dir_path: Path, block: list[str], preserved: str = '',
                   name: str | None = None) -> str:
    lines = [f'# {name or dir_path.name}', '', AUTO_START, *block, AUTO_END]
    if preserved.strip():
        lines.extend(['', preserved])
    lines.extend(['', f'---\n{_FOOTER}'])
    return '\n'.join(lines)


_TIMESTAMP_RE = re.compile(r'^\*Last updated: [^*\n]*\*$', re.MULTILINE)


def _keep_timestamp(old: str, new: str) -> str:
    """`new` with the old file's Last-updated line when that line is all that differs, so a
    regeneration of an unchanged folder rewrites the same bytes and the INDEX dates the
    last change of its listing, not the last run of the generator."""
    old_ts = _TIMESTAMP_RE.findall(old)
    new_ts = _TIMESTAMP_RE.findall(new)
    if len(old_ts) == 1 and len(new_ts) == 1 and \
            _TIMESTAMP_RE.sub('', old) == _TIMESTAMP_RE.sub('', new):
        return old
    return new


def render_index(dir_path: Path, project_dir: Path | None = None) -> tuple[RegenStatus, str | None]:
    """(status, the INDEX text regeneration would write); the text is None on every skip.

    Writes nothing: regen_index writes this text, and the tree-wide --check of
    scripts/regen-folder-docs.py compares it with the file, so both read one rendering.
    """
    # Never generate an INDEX under the GitHub-reserved subtree: a stub there is
    # repo-noise (nested) or a landing-page hijack risk. Skip when the folder IS
    # .github or lies beneath it (tested relative to project_dir), robust to
    # non-canonical '..' inputs.
    if is_github_reserved_subtree(dir_path, project_dir):
        return RegenStatus.SKIPPED_GITHUB_RESERVED, None
    index_path = dir_path / 'INDEX.md'
    if not index_path.exists():
        return RegenStatus.SKIPPED_ABSENT, None
    old = index_path.read_text()
    skip = classify_region(old, INDEX_MARKER_ID).status
    if skip is not None:
        return skip, None
    name = _folder_name(dir_path, old)
    preserved = _extract_preserved(old, name)
    block = _build_index_block(dir_path, _detect_convention(dir_path), name)
    if marker_line_numbers('\n'.join(block)):
        return RegenStatus.SKIPPED_MALFORMED_MARKERS, None
    content = _compose_index(dir_path, block, preserved, name)
    if classify_region(content, INDEX_MARKER_ID).shape is not RegionShape.WELL_FORMED:
        return RegenStatus.SKIPPED_MALFORMED_MARKERS, None
    return RegenStatus.WRITTEN, _keep_timestamp(old, content)


def regen_index(dir_path: Path, project_dir: Path | None = None) -> RegenStatus:
    """Regenerate INDEX.md, preserving hand-written annotations, and report what happened.

    Only an existing file that carries a well-formed AUTO region is managed. An absent INDEX
    is SKIPPED_ABSENT and none is created: nothing in a pipeline reads a generated index, and
    a created one stayed in the product repository as a file no dev declared. Every other
    existing INDEX is left untouched (no bytes, no mtime) and its status returned, mirroring
    regen_readme so annotation-wiping is structurally impossible. Content that would put
    marker text of its own into the file (a multi-line description in the tree) is refused
    the same way: a file the classifier rejects on the next run must never be produced here.

    project_dir (the repository root) anchors the GitHub-reserved-subtree check to
    the repo, making it CWD-independent; see config.is_github_reserved_subtree."""
    status, text = render_index(dir_path, project_dir)
    if text is None:
        return status
    return write_folder_doc(dir_path / 'INDEX.md', text, project_dir)
