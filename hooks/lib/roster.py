#!/usr/bin/env python3
"""roster.py -- the agent roster: the roles the harness's agent files declare.

A role exists because ``agents/<role>.md`` exists and opens with YAML front
matter; the folder documents (INDEX.md, README.md) carry none. The roster is
read from those files whenever it is asked for, so no list of role names is
written down anywhere: adding or removing an agent file is the whole change.
"""

from __future__ import annotations

import os
from pathlib import Path

AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / "agents"

# A hook that validates every dispatch of a long session asks for the same
# directory's roster once per obligation: it is read again only when the
# directory changed since (its mtime, or the names and inodes of its *.md
# entries, which a coarse mtime can miss). An agent file rewritten in place
# keeps its entry, so a process that has read the roster does not see that
# edit; every hook process reads it afresh.
_SEEN: dict[str, tuple[tuple, frozenset[str]]] = {}
# Within held(): each directory's roster as it was first asked for there.
_HELD: dict | None = None


class held:
    """``with held():`` -- within the block each directory's roster is listed
    and read once. A caller that decides at one moment over many obligations
    (tool-policy reading every started dispatch of a long session) takes one
    roster for all of them, as it would if the directory did not change while
    it ran: listing the directory again for each obligation was most of what
    validating one cost there. Nested blocks share the outermost one's."""

    def __enter__(self):
        global _HELD
        self._outer = _HELD
        if _HELD is None:
            _HELD = {}
        return self

    def __exit__(self, *exc):
        global _HELD
        _HELD = self._outer
        return False


def _md_entries(directory: Path) -> tuple | None:
    """What says the roster of ``directory`` may have changed, or None when it
    cannot be listed (then the roster is read without remembering it)."""
    try:
        mtime = os.stat(directory).st_mtime_ns
        with os.scandir(directory) as entries:
            names = sorted((e.name, e.inode()) for e in entries if e.name.endswith(".md"))
    except OSError:
        return None
    return (mtime, tuple(names))


def roles(agents_dir: str | Path | None = None) -> frozenset[str]:
    """The stems of the ``*.md`` files in ``agents_dir`` (default: the
    harness's agents/) whose first line opens front matter. A file that cannot
    be read contributes nothing; a missing directory gives the empty set."""
    if _HELD is not None:
        # Held by the directory as it is named: one read per name, not one
        # spelling of a path per obligation.
        if agents_dir not in _HELD:
            _HELD[agents_dir] = _read(agents_dir)
        return _HELD[agents_dir]
    return _read(agents_dir)


def _read(agents_dir: str | Path | None) -> frozenset[str]:
    """roles(), remembered in _SEEN until the directory changes."""
    directory = Path(agents_dir) if agents_dir is not None else AGENTS_DIR
    key = os.path.abspath(directory)
    listed = _md_entries(directory)
    seen = _SEEN.get(key)
    if listed is not None and seen is not None and seen[0] == listed:
        return seen[1]
    found = set()
    for path in directory.glob("*.md"):
        try:
            with path.open(encoding="utf-8") as handle:
                first = handle.readline()
        except (OSError, UnicodeDecodeError):
            continue
        if first.rstrip("\r\n") == "---":
            found.add(path.stem)
    result = frozenset(found)
    if listed is not None:
        _SEEN[key] = (listed, result)
    return result
