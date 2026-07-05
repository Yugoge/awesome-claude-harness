#!/usr/bin/env python3
"""Main entry point for doc-sync hook."""

import json
import os
import sys
from pathlib import Path
from .regen_index import regen_index
from .regen_readme import regen_readme
from .patch import patch_claude_md

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


def _regen_if_dir(d: Path, project_dir: Path):
    if d.is_dir():
        regen_index(d, project_dir)
        regen_readme(d, project_dir)


def _maybe_regen_global(parent_dir: Path, rel: str):
    wd = _match_watch_dir(rel)
    if wd is None:
        return
    global_dir = Path.home() / wd
    if global_dir.is_dir() and global_dir.resolve() != parent_dir.resolve():
        # Global dirs live under ~/.claude; anchor the reserved-subtree check to
        # $HOME so it is framed the same way global rel paths are (.claude/...).
        regen_index(global_dir, Path.home())
        regen_readme(global_dir, Path.home())


def process_parent_dirs(parent_dir: Path, project_dir: Path):
    _regen_if_dir(parent_dir, project_dir)
    rel = str(parent_dir.relative_to(project_dir))
    _maybe_regen_global(parent_dir, rel)


def main():
    try:
        data = json.load(sys.stdin)
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
        process_parent_dirs(fp.parent, project_dir)
        patch_claude_md(project_dir)
    except Exception:
        pass
    sys.exit(0)


if __name__ == '__main__':
    main()
