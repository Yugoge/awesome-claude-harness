"""The write targets of a Bash command, read by the shared parser (lib/shell_parse.py).

An import shim for the hooks that read paths rather than parse trees. Every reading is
``shell_parse.write_targets``; this module only renders each target as the path text its
callers match: a static path as written, with ``~``, ``$HOME`` and ``$CLAUDE_PROJECT_DIR``
expanded, a variable the parser tracked to a literal set earlier in the same command put in, and
any other expansion kept as written so a caller sees it is unresolved.
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


# A computed target's text with each variable the parser tracked to a literal in this command put in
# (`S=/own; cp f $S/$r` -> `/own/$r`), keyed by id(target); refilled by each _targets call.
_PARTIAL: dict = {}


def _partials(script, command: str, found: list, reached) -> None:
    """A second reading in which every other variable holds a marker that renders back as written."""
    _PARTIAL.clear()
    if not any(t.path is None and t.word is not None for t in found):
        return
    known = _known()
    seed = {n: "\0%s\0" % n for n in set(re.findall(r"\$\{?([A-Za-z_]\w*)", command)) - set(known)}
    by_word = {(id(t.word), t.mechanism): t for t in found if t.path is None and t.word is not None}
    for t in _sp.write_targets(script, env={**known, **seed}, raw=command, reached=reached):
        old = by_word.get((id(t.word), t.mechanism))
        # only where a tracked literal went in: a word of untracked variables alone stays as written (`${N}`)
        refs = [n for n in re.findall(r"\$\{?([A-Za-z_]\w*)", old.word.text) if n in seed] if old else []
        if old is not None and t.path is not None and t.path.count("\0") // 2 < len(refs):
            _PARTIAL[id(old)] = (old, re.sub("\0(\\w+)\0", r"$\1", t.path))


def _targets(command: str) -> list:
    if not isinstance(command, str) or not command.strip():
        return []
    script = _sp.parse(command)
    reached = lambda d: os.path.isdir(os.path.expanduser(d))  # noqa: E731
    found = _sp.write_targets(script, env=_known(), raw=command, reached=reached)
    _partials(script, command, found, reached)
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
    elif _PARTIAL.get(id(t), (None,))[0] is t:
        text = _PARTIAL[id(t)][1]
    else:
        w = t.word
        text = "".join(p.text if p.kind == "lit" else w.raw.text[p.span[0] - w.start:p.span[1] - w.start]
                       for p in w.parts)
    for name, value in _known().items():
        text = text.replace("${%s}" % name, value).replace("$" + name, value)
    return os.path.expanduser(text) if text.startswith("~") else text


def _placed(t, command: str) -> list:
    """_render's text where the write lands: at each directory its command may run in (WriteTarget.placed)."""
    return t.placed(_render(t, command))


def extract_bash_write_targets_with_modes(command: str) -> list:
    """The parser's WriteTargets that leave a path holding new content (every mode but delete)."""
    return [t for t in _targets(command) if t.mode != _sp.DELETE]


def extract_bash_write_paths(command: str) -> List[str]:
    """The path text of every target a command writes, first-seen order, without duplicates."""
    found = (p for t in extract_bash_write_targets_with_modes(command) for p in _placed(t, command))
    return list(dict.fromkeys(p for p in found if p))


def extract_bash_touched_paths(command: str) -> List[Tuple[str, bool]]:
    """(path, removed) for each path a command writes, deletes or renames away.

    A move whose words are all plain and whose destination is decidable writes the destination and
    removes ``<dest>/<basename(source)>``, the entry a directory destination loses; any other move
    may remove its destination too. A command whose name is computed is not read (`"$RM" f`,
    `"$PY" -m pytest hooks`): each of its static path operands is touched, not removed, so a
    protected file it names is refused and a directory above one is not; whether it removes is the
    removal policy's decision (lib/bash_safety_rules).
    """
    found = _targets(command)
    out: List[Tuple[str, bool]] = _computed_command_operands(command)
    for k, t in enumerate(found):
        sources = []
        for s in found[k + 1:] if t.mechanism in _sp.MOVE_MECHANISMS else ():
            if s.mechanism != t.mechanism + "-source":
                break
            sources.append(s)
        plain = t.decidable and all(w.word.value() is not None and not w.word.quoted() for w in [t] + sources)
        for path in _placed(t, command):
            if t.mechanism not in _sp.MOVE_MECHANISMS:
                out.append((path, t.mode == _sp.DELETE))
                continue
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
                out.append((os.path.expanduser(v) if v.startswith("~") else v, False))
    return out


command_without_heredoc_bodies = _sp.without_heredoc_bodies
