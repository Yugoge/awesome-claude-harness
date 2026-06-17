#!/usr/bin/env python3
"""Load doc-sync project-local config and the git-tracked-file set.

The git-tracked helpers (WS5, AC-WS5-1) let the INDEX/README generators list
ONLY published (git-tracked) files instead of walking the live filesystem and
advertising gitignored / untracked runtime junk. They degrade gracefully:
outside a git work-tree (git missing or dir not in a repo) they return None,
and callers fall back to their existing hand-denylist behaviour.
"""

import json
import subprocess
from pathlib import Path


def load_config(project_dir: Path) -> dict:
    """Load <project_dir>/.claude/doc-sync.json. Return {} when missing or malformed."""
    config_path = project_dir / '.claude' / 'doc-sync.json'
    if not config_path.is_file():
        return {}
    try:
        return json.loads(config_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def tracked_names(dir_path: Path) -> set[str] | None:
    """Return the set of basenames published (git-tracked) directly inside dir_path.

    A name is included if it is the first path segment of any tracked entry under
    dir_path -- i.e. a tracked file's own name, OR a directory that contains at
    least one tracked file. `git ls-files` lists tracked files only, so gitignored
    and untracked files are naturally absent.

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
    names: set[str] = set()
    for entry in out.split('\0'):
        if not entry:
            continue
        # entry is a path relative to dir_path; take its first segment.
        names.add(entry.replace('\\', '/').split('/', 1)[0])
    return names
