"""The write targets of a Bash command, read by the shared parser (lib/shell_parse.py).

An import shim for the hooks that read paths rather than parse trees. Every reading is
``shell_parse.write_targets``; this module only renders each target as the path text its
callers match: a static path as written, with ``~``, ``$HOME`` and ``$CLAUDE_PROJECT_DIR``
expanded, and any other expansion kept as written so a caller sees it is unresolved.
"""

from __future__ import annotations

import os
import re
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


# A command whose name is computed counts as a copy only when an operand is spelled after cp or mv
# (`"$CP" cp-01 dest`); otherwise its last operand (`"$PY" script.py`) is no write.
_COPY_MOVE_WORD = _sp._COPY_MOVE_WORD_RE


def _targets(command: str) -> list:
    if not isinstance(command, str) or not command.strip():
        return []
    script = _sp.parse(command)
    found = _sp.write_targets(script, env=_known())
    if not any(t.mechanism == "computed-command" for t in found):
        return found
    copies = set()
    for site in _sp.walk(script):
        words = site.cmd.words
        if any(_COPY_MOVE_WORD.match(w.value() or "") for w in words[1:]):
            copies.update(id(w) for w in words)
    return [t for t in found if t.mechanism != "computed-command" or id(t.word) in copies]


def _render(t, command: str) -> str:
    if t.path is not None:
        text = t.path
    elif t.word is None or t.word.value() is not None:
        return ""  # a target with no word of its own (an operand xargs appends)
    else:
        w = t.word
        text = "".join(p.text if p.kind == "lit" else w.raw.text[p.span[0] - w.start:p.span[1] - w.start]
                       for p in w.parts)
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
    may remove its destination too. A command whose name is computed may do anything to each of its
    static path operands (`"$RM" f`), so each is touched and may be removed.
    """
    found = _targets(command)
    out: List[Tuple[str, bool]] = _computed_command_operands(command)
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


def _computed_command_operands(command: str) -> List[Tuple[str, bool]]:
    if not isinstance(command, str) or not command.strip():
        return []
    out = []
    for site in _sp.walk(_sp.parse(command)):
        res = _sp.resolve(site.cmd)
        if res.head is None or res.name is not None:
            continue
        for w in res.args:
            v = w.value()
            if v and not v.startswith("-"):
                out.append((os.path.expanduser(v) if v.startswith("~") else v, True))
    return out


command_without_heredoc_bodies = _sp.without_heredoc_bodies
