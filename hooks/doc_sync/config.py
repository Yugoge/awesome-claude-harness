#!/usr/bin/env python3
"""Load doc-sync project-local config and the git-tracked-file set.

The git-tracked helpers (WS5, AC-WS5-1) let the INDEX/README generators list
ONLY published (git-tracked) files instead of walking the live filesystem and
advertising gitignored / untracked runtime junk. They degrade gracefully:
outside a git work-tree (git missing or dir not in a repo) they return None,
and callers fall back to their existing hand-denylist behaviour.
"""

import json
import os
import subprocess
from pathlib import Path, PurePath

# GitHub-reserved directory name. A generated README.md anywhere under .github/
# can hijack the repo landing page (GitHub precedence: .github/README.md >
# README.md > docs/README.md); nested INDEX/README stubs are repo-noise. No
# folder-doc generator may write under this subtree.
GITHUB_RESERVED_DIR = '.github'


def is_github_reserved_subtree(dir_path: Path, project_dir: Path | None = None) -> bool:
    """True iff dir_path is (or lies beneath) the repository's ROOT-level
    reserved .github/ directory.

    Reference frame — anchored to the repository root, NEVER the process CWD:

    * When ``project_dir`` is given (all production callers pass it), a relative
      ``dir_path`` is joined onto ``project_dir`` and membership is tested on the
      path RELATIVE to that root. Two consequences, both intended:
        - The answer does not depend on the process CWD, so a bare relative input
          such as '.' is resolved against the repo root (it means the repo root,
          which is not .github) rather than being silently judged by whatever
          directory the process happens to sit in.
        - It is immune to a repository that itself lives under an unrelated
          ancestor directory literally named '.github' (e.g. ``/srv/.github/app``):
          the ancestor is stripped by the relative-path computation, so only the
          repo's OWN .github matches. A ``dir_path`` resolving OUTSIDE
          ``project_dir`` is not this repo's .github and returns False.
    * When ``project_dir`` is None (no repo anchor available), membership is judged
      LEXICALLY on the path as written: '..' segments are collapsed via
      os.path.normpath, then the components are tested. A bare relative input is
      judged by its written components ONLY and is not resolved against the CWD;
      this fallback therefore does not claim to catch a bare relative directory
      that is physically inside .github. Pass ``project_dir`` for the robust,
      CWD-independent answer.

    In both modes the check is purely lexical (os.path.normpath / os.path.relpath)
    and never follows symlinks: a symlink whose own name is not '.github' is judged
    by its written name, never silently redirected. '..' is always collapsed before
    the membership test.
    """
    normalized = os.path.normpath(os.fspath(dir_path))
    if project_dir is None:
        return GITHUB_RESERVED_DIR in PurePath(normalized).parts
    root = os.path.normpath(os.fspath(project_dir))
    abs_path = normalized if os.path.isabs(normalized) \
        else os.path.normpath(os.path.join(root, normalized))
    try:
        rel = os.path.relpath(abs_path, root)
    except ValueError:
        # Different mount/drive (Windows) — cannot be under this repo root.
        return False
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        return False  # resolves outside project_dir → not the repo's .github
    rel_parts = PurePath(rel).parts
    # Only the repository's ROOT-level .github is GitHub-reserved (the landing-page
    # hijack + repo-noise concern applies to the root .github). Because rel is
    # anchored at project_dir, that root .github is exactly rel_parts[0]; a nested
    # .github deeper in the tree (e.g. src/.github) is a normal folder, not reserved.
    return bool(rel_parts) and rel_parts[0] == GITHUB_RESERVED_DIR


def load_config(project_dir: Path) -> dict:
    """Load <project_dir>/.claude/doc-sync.json. Return {} when missing or malformed."""
    config_path = project_dir / '.claude' / 'doc-sync.json'
    if not config_path.is_file():
        return {}
    try:
        return json.loads(config_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _tracked_relpaths(dir_path: Path) -> set[str] | None:
    """Forward-slash relative paths of every git-tracked file under dir_path.

    Returns None (NOT an empty set) when the tracked set cannot be determined --
    git is unavailable or dir_path is not inside a work-tree -- so callers can
    distinguish "no tracked files here" ({}) from "git not consulted" (None) and
    fall back to the hand denylist for non-git consumers.
    """
    try:
        proc = subprocess.run(
            ['git', '-C', str(dir_path), 'ls-files', '-z', '--', '.'],
            capture_output=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    out = proc.stdout.decode('utf-8', errors='replace')
    return {entry.replace('\\', '/') for entry in out.split('\0') if entry}


def tracked_names(dir_path: Path) -> set[str] | None:
    """Return the set of basenames published (git-tracked) directly inside dir_path.

    A name is included if it is the first path segment of any tracked entry under
    dir_path -- i.e. a tracked file's own name, OR a directory that contains at
    least one tracked file. `git ls-files` lists tracked files only, so gitignored
    and untracked files are naturally absent. Returns None when git was not
    consulted (see _tracked_relpaths).
    """
    relpaths = _tracked_relpaths(dir_path)
    if relpaths is None:
        return None
    return {rel.split('/', 1)[0] for rel in relpaths}


def tracked_relpaths(dir_path: Path) -> set[str] | None:
    """Public alias for the full forward-slash tracked relative-path set under
    dir_path (a tracked-aware tree filter consumes this to prune nested untracked
    entries). Returns None when git was not consulted."""
    return _tracked_relpaths(dir_path)
