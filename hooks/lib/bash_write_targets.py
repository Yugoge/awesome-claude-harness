"""The write targets of a Bash command, read by the shared parser (lib/shell_parse.py).

An import shim for the hooks that read paths rather than parse trees. Every reading is
``shell_parse.write_targets``; this module only renders each target as the path text its
callers match: a static path as written, with ``~``, ``$HOME`` and ``$CLAUDE_PROJECT_DIR``
expanded, and any other expansion kept as written so a caller sees it is unresolved.
"""

from __future__ import annotations

import os
from typing import List, Tuple

try:
    from lib import shell_parse as _sp
except ImportError:  # imported with hooks/lib itself on sys.path
    import shell_parse as _sp


def _known() -> dict:
    """The variables whose value the hook shares with the shell it guards."""
    known = {"HOME": os.environ.get("HOME") or os.path.expanduser("~")}
    if os.environ.get("CLAUDE_PROJECT_DIR"):
        known["CLAUDE_PROJECT_DIR"] = os.environ["CLAUDE_PROJECT_DIR"]
    return known


def _targets(command: str) -> list:
    if not isinstance(command, str) or not command.strip():
        return []
    return _sp.write_targets(command, env=_known())


def _render(t, command: str) -> str:
    if t.path is not None:
        text = t.path
    else:
        text = "".join(p.text if p.kind == "lit" else command[p.span[0]:p.span[1]] for p in t.word.parts)
    for name, value in _known().items():
        text = text.replace("${%s}" % name, value).replace("$" + name, value)
    return os.path.expanduser(text) if text.startswith("~") else text


def extract_bash_write_targets_with_modes(command: str) -> list:
    """The parser's WriteTargets that leave a path holding new content (every mode but delete)."""
    return [t for t in _targets(command) if t.mode != _sp.DELETE]


def extract_bash_write_paths(command: str) -> List[str]:
    """The path text of every target a command writes, first-seen order, without duplicates."""
    found = (_render(t, command) for t in extract_bash_write_targets_with_modes(command))
    return list(dict.fromkeys(p for p in found if p))


def extract_bash_touched_paths(command: str) -> List[Tuple[str, bool]]:
    """(path, removed) for each path a command writes, deletes or renames away.

    A move whose words are all plain and whose destination is decidable writes the destination and
    removes ``<dest>/<basename(source)>``, the entry a directory destination loses; any other move
    may remove its destination too.
    """
    found = _targets(command)
    out: List[Tuple[str, bool]] = []
    for k, t in enumerate(found):
        path = _render(t, command)
        if not path:
            continue
        if t.mechanism not in ("mv", "git-mv"):
            out.append((path, t.mode == _sp.DELETE))
            continue
        sources = []
        for s in found[k + 1:]:
            if s.mechanism != t.mechanism + "-source":
                break
            sources.append(s)
        plain = t.decidable and all(w.word.value() is not None and not w.word.quoted() for w in [t] + sources)
        out.append((path, not plain))
        if plain:
            out.extend((os.path.join(path, os.path.basename(_render(s, command).rstrip("/"))), True)
                       for s in sources)
    return out


command_without_heredoc_bodies = _sp.without_heredoc_bodies
