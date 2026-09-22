#!/usr/bin/env python3
"""Main entry point for doc-sync hook."""

import json
import os
import sys
from pathlib import Path
from .regen_index import regen_index
from .regen_readme import regen_readme
from .patch import patch_claude_md
from .notice import emit_post_tool_notice
from .regions import (
    INDEX_MARKER_ID, README_MARKER_ID, ArtifactKind, RegenRecord, RegenStatus, RegionShape,
    classify_region,
)

WATCHED_DIRS = {
    '.claude/commands',
    '.claude/agents',
    '.claude/hooks',
    '.claude/skills',
    '.claude/scripts',
}
WATCHED_EXTS = {
    '.py', '.sh', '.bash', '.ts', '.js', '.tsx', '.jsx',
    '.md', '.json', '.yaml', '.yml', '.toml',
    '.go', '.rs', '.sql',
}
IGNORE_DIRS = {
    'node_modules', '.git', '__pycache__', '.venv', 'venv',
    'dist', 'build', '.next', '.cache', 'coverage',
}
SKIP_FILES = {'INDEX.md', 'README.md', '__init__.py', '.DS_Store'}
EXCLUDED_PATTERNS = (
    '.claude/commands/scripts/',
    '.claude/worktrees/',
    '.claude/specs/',
    '.claude/dev-registry/',
    'tests/generated/',  # keep test snapshots out of auto-indexing
)


def _is_excluded(rel: str) -> bool:
    rel_norm = rel.replace(os.sep, '/')
    return any(pat in rel_norm for pat in EXCLUDED_PATTERNS)


def should_sync(file_path: Path, rel: str) -> bool:
    rel_parts = Path(rel).parts
    if any(part in IGNORE_DIRS for part in rel_parts):
        return False
    if _is_excluded(rel):
        return False
    in_watched = any(rel.startswith(wd + '/') or rel.startswith(wd + os.sep) for wd in WATCHED_DIRS)
    has_watched_ext = file_path.suffix.lower() in WATCHED_EXTS
    return in_watched or has_watched_ext


def _get_relative_path(fp: Path, project_dir: Path) -> str | None:
    """Get relative path or None if not in claude dir."""
    try:
        return str(fp.relative_to(project_dir))
    except ValueError:
        pass
    global_claude = Path.home() / '.claude'
    try:
        return '.claude/' + str(fp.relative_to(global_claude))
    except ValueError:
        pass
    return None


def _match_watch_dir(rel: str):
    """Find matching watched dir prefix, or None."""
    for wd in WATCHED_DIRS:
        if rel.startswith(wd + '/') or rel.startswith(wd + os.sep):
            return wd
    return None


def _refusal_shape(path: Path):
    """(shape, detail) of a MALFORMED skip, by re-classifying the file the skip left untouched.

    regen_* return the bare status (that identity contract is what keeps their callers simple),
    so the shape is recovered here. A file that is itself well-formed, or absent, was refused
    because of the content that would have been generated.
    """
    marker_id = INDEX_MARKER_ID if path.name == 'INDEX.md' else README_MARKER_ID
    try:
        region = classify_region(path.read_text(), marker_id)
    except Exception:
        return RegionShape.BODY_BREAKS_REGION, None
    if region.shape is RegionShape.WELL_FORMED:
        return RegionShape.BODY_BREAKS_REGION, None
    detail = str(region.fence_line) if region.fence_line is not None else None
    return region.shape, detail


def _regen_and_record(regen, kind: ArtifactKind, d: Path, project_dir: Path, results):
    """Run one regeneration and append its record at once: a failure in the next call of the
    same directory (an unwritable INDEX after a README skip) must not lose what was reported."""
    status = regen(d, project_dir)
    if results is not None and status is not None:
        path = d / ('README.md' if kind is ArtifactKind.README else 'INDEX.md')
        shape, detail = (None, None)
        if status is RegenStatus.SKIPPED_MALFORMED_MARKERS:
            shape, detail = _refusal_shape(path)
        results.append(RegenRecord(kind, path, status, None, shape, detail))
    return status


def _regen_if_dir(d: Path, project_dir: Path, results: list | None = None):
    """Regenerate README.md, then INDEX.md; the README status, or None when d is no directory."""
    if not d.is_dir():
        return None
    status = _regen_and_record(regen_readme, ArtifactKind.README, d, project_dir, results)
    _regen_and_record(regen_index, ArtifactKind.INDEX, d, project_dir, results)
    return status


def _maybe_regen_global(parent_dir: Path, rel: str, results: list | None = None):
    """Same for the matching global directory; the README status, or None when not applicable."""
    wd = _match_watch_dir(rel)
    if wd is None:
        return None
    global_dir = Path.home() / wd
    if global_dir.is_dir() and global_dir.resolve() != parent_dir.resolve():
        # Global dirs live under ~/.claude; anchor the reserved-subtree check to
        # $HOME so it is framed the same way global rel paths are (.claude/...).
        status = _regen_and_record(regen_readme, ArtifactKind.README, global_dir, Path.home(), results)
        _regen_and_record(regen_index, ArtifactKind.INDEX, global_dir, Path.home(), results)
        return status
    return None


def process_parent_dirs(parent_dir: Path, project_dir: Path, results: list | None = None):
    """Regenerate the parent (and matching global) directory; returns the `results` list.

    Records (README first, then INDEX, per directory) are appended to the caller's `results`
    as each call finishes, so a failure in a later call does not lose what an earlier one
    already reported.
    """
    if results is None:
        results = []
    _regen_if_dir(parent_dir, project_dir, results)
    rel = str(parent_dir.relative_to(project_dir))
    _maybe_regen_global(parent_dir, rel, results)
    return results


def main():
    results: list = []
    payload = {}
    try:
        data = json.load(sys.stdin)
        payload = data
        file_path = data.get('tool_input', {}).get('file_path', '')
        if not file_path:
            sys.exit(0)
        fp = Path(file_path)
        if fp.name in SKIP_FILES:
            sys.exit(0)
        project_dir = Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))
        rel = _get_relative_path(fp, project_dir)
        if rel is None:
            sys.exit(0)
        if not should_sync(fp, rel):
            sys.exit(0)
        process_parent_dirs(fp.parent, project_dir, results)
        section_skips = patch_claude_md(project_dir)
        if isinstance(section_skips, list):
            results.extend(section_skips)
    except Exception:
        pass
    # Outside the try: skips collected before a later failure still reach the caller.
    emit_post_tool_notice(results, payload)
    sys.exit(0)


if __name__ == '__main__':
    main()
