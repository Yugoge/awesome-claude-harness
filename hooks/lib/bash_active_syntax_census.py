#!/usr/bin/env python3
"""Over-approximating census of ACTIVE shell syntax in a raw command string.

WHY THIS MODULE EXISTS (spec-20260808-035658 LANE-POL, Must-2 "completeness
obligation").  Six prior iterations of the removal policy failed because the
authorization algebra treated *analyzer silence* as *permission*: if no adapter
recognised a construct, no finding was produced, and no finding meant allow.
Adding more adapters can lower a sample mismatch count but can never prove that
the analyzer looked everywhere.

This module is the independent half of the proof.  It scans the RAW command
bytes with its own minimal quote/escape state machine and emits one OBLIGATION
per active-syntax event it sees, keyed by absolute byte offset.  The semantic
analyzer (``bash_execution_boundary.py``) must independently report that it
consumed every one of those offsets.  Any obligation the analyzer did not
discharge makes the command UNRESOLVED (deny).

CONTRACT (do not weaken):
  * This module MUST NOT import, call, or otherwise consume the semantic
    analyzer's conclusions.  It is a second opinion, not a summary of the first.
  * It over-approximates on purpose.  Extra obligations cost a denial; missing
    obligations cost a bypass.  When the two scanners disagree the command is
    denied.
  * It never executes, expands, or evaluates the text it scans.
"""

from __future__ import annotations

import json
import os
import sys

# Obligation kinds. The analyzer must discharge every emitted offset.
KIND_SUBSTITUTION = "substitution"   # $(...) or `...` or $((...)) or $[...]
KIND_PROCSUB = "procsub"             # <(...) or >(...)
KIND_HEREDOC = "heredoc"             # << / <<- / <<<
KIND_PARAM_REEXPAND = "param_reexpand"  # ${x@P} / ${x@E} / ${x@A} / ${!x}
KIND_REMOVAL_REFERENCE = "removal_reference"  # a token naming a removal binary

# Filesystem-removal front ends, duplicated here ON PURPOSE. This module is the
# INDEPENDENT completeness backstop: it must not import its trigger set from
# the analyzer it is checking, or a hole in the analyzer's model would silently
# become a hole in the census too.
REMOVAL_BINARIES = ("rm", "unlink", "shred", "srm")

# Word delimiters for the removal-reference scan. Quotes are delimiters, so a
# removal binary named inside a quoted payload (`script -qc 'rm x'`) is seen.
_TOKEN_DELIMS = frozenset(" \t\n\r\f\v;&|()<>'\"")

# Fatal lexical states: these are never dischargeable, they force UNRESOLVED.
FATAL_UNBALANCED = "unbalanced"
FATAL_UNTERMINATED_HEREDOC = "unterminated_heredoc"

_NAME_START = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")


def _skip_matching(text: str, i: int, opener: str, closer: str) -> int:
    """Return index just past the balanced closer, or -1 when unterminated.

    Quote-aware: a closer inside '...' or "..." does not close the construct.
    """
    depth = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "'":
            j = text.find("'", i + 1)
            if j < 0:
                return -1
            i = j + 1
            continue
        if c == '"':
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == '"':
                    break
                i += 1
            if i >= n:
                return -1
            i += 1
            continue
        if c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def _join_continuations(text: str, base: int):
    """Strip backslash-newline line continuations, keeping an offset map.

    Bash joins ``\\\\\\n`` BEFORE any other processing, so ``$\\\\\\n(`` is a real
    command substitution and ``/bi\\\\\\nn/rm`` is a real ``/bin/rm``.  A scanner
    that does not join here is blind to that whole obfuscation family.
    """
    out = []
    offs = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "\\" and i + 1 < n and text[i + 1] == "\n":
            i += 2
            continue
        out.append(text[i])
        offs.append(base + i)
        i += 1
    return "".join(out), offs


def _scan_removal_references(text: str, emit) -> None:
    """Raise one obligation per token that names a filesystem-removal binary.

    Wherever it sits: argument position, wrapper payload, quoted `-c` string,
    heredoc body, git alias body. The analyzer discharges an obligation only by
    positively consuming the text that raised it on a route whose every
    boundary was terminal-safe. Analyzer SILENCE therefore no longer authorizes
    anything — a payload nothing ever looked at leaves its obligation standing
    and the command resolves UNRESOLVED.

    This is the Must-2 half of the contract and it is deliberately independent
    of the analyzer's wrapper/handler tables: it needs no model of `taskset`,
    `chrt`, `numactl` or any other exec wrapper to notice that a removal binary
    was named and never accounted for.
    """
    n = len(text)
    i = 0
    while i < n:
        if text[i] in _TOKEN_DELIMS:
            i += 1
            continue
        j = i
        while j < n and text[j] not in _TOKEN_DELIMS:
            j += 1
        if text[i:j].rsplit("/", 1)[-1] in REMOVAL_BINARIES:
            emit(KIND_REMOVAL_REFERENCE, i)
        i = j


def census(raw: str) -> dict:
    """Scan ``raw`` and return the obligation set.

    Returns {"obligations": [{"kind","offset"}...], "fatal": [str...]}.
    """
    text, offs = _join_continuations(raw, 0)
    obligations = []
    fatal = []
    seen = set()

    def emit(kind: str, idx: int) -> None:
        off = offs[idx] if 0 <= idx < len(offs) else -1
        key = (kind, off)
        if key not in seen:
            seen.add(key)
            obligations.append({"kind": kind, "offset": off})

    # Completeness backstop: independent of every analyzer table.
    _scan_removal_references(text, emit)

    # Heredoc bodies are scanned in a second pass; collect (delimiter, quoted)
    # in first-seen order so bodies can be located after each newline.
    pending_heredocs = []
    heredoc_bodies = []  # (body_text, base_index) for unquoted delimiters only
    nested_bodies = []   # (body_text, [index...]) for backtick substitutions

    in_dq = False
    i = 0
    n = len(text)
    while i < n:
        c = text[i]

        if c == "\\":
            i += 2
            continue

        if c == "'" and not in_dq:
            j = text.find("'", i + 1)
            if j < 0:
                fatal.append(FATAL_UNBALANCED + ":single_quote")
                return {"obligations": obligations, "fatal": fatal}
            i = j + 1
            continue

        if c == '"':
            # Double quotes suppress word splitting and globbing but NOT
            # substitutions, so the body keeps being scanned actively; only the
            # quote STATE flips (single quotes and redirect operators are
            # literal inside them).
            in_dq = not in_dq
            i += 1
            continue

        if c == "`":
            end = i + 1
            found = -1
            while end < n:
                if text[end] == "\\":
                    end += 2
                    continue
                if text[end] == "`":
                    found = end
                    break
                end += 1
            if found < 0:
                fatal.append(FATAL_UNBALANCED + ":backtick")
                return {"obligations": obligations, "fatal": fatal}
            emit(KIND_SUBSTITUTION, i)
            # Backticks share their opener and closer, so descending inline
            # would read the closer as a fresh opener. Recurse on the body,
            # undoing the one level of backslash-escaping bash removes there.
            body_chars = []
            body_idx = []
            k = i + 1
            while k < found:
                if text[k] == "\\" and k + 1 < found and text[k + 1] in "`$\\":
                    body_chars.append(text[k + 1])
                    body_idx.append(k + 1)
                    k += 2
                    continue
                body_chars.append(text[k])
                body_idx.append(k)
                k += 1
            nested_bodies.append(("".join(body_chars), body_idx))
            i = found + 1
            continue

        if c == "$" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "(":
                if i + 2 < n and text[i + 2] == "(":
                    end = _skip_matching(text, i + 1, "(", ")")
                    if end < 0:
                        fatal.append(FATAL_UNBALANCED + ":arith")
                        return {"obligations": obligations, "fatal": fatal}
                else:
                    end = _skip_matching(text, i + 1, "(", ")")
                    if end < 0:
                        fatal.append(FATAL_UNBALANCED + ":cmdsub")
                        return {"obligations": obligations, "fatal": fatal}
                emit(KIND_SUBSTITUTION, i)
                i += 2
                continue
            if nxt == "[":
                end = _skip_matching(text, i + 1, "[", "]")
                if end < 0:
                    fatal.append(FATAL_UNBALANCED + ":arith_bracket")
                    return {"obligations": obligations, "fatal": fatal}
                emit(KIND_SUBSTITUTION, i)
                i += 2
                continue
            if nxt == "{":
                end = _skip_matching(text, i + 1, "{", "}")
                if end < 0:
                    fatal.append(FATAL_UNBALANCED + ":param")
                    return {"obligations": obligations, "fatal": fatal}
                body = text[i + 2:end - 1]
                # ${x@P} re-expands the value as a prompt string: the payload is
                # re-parsed and executed. ${!x} is an indirect reference.
                # @P/@E/@A re-parse the VALUE as shell input; ${!x} resolves the
                # name indirectly. Both defeat static reading of the word.
                if body.startswith("!"):
                    emit(KIND_PARAM_REEXPAND, i)
                elif "@" in body and body.rsplit("@", 1)[1][:1] in ("P", "E", "A"):
                    emit(KIND_PARAM_REEXPAND, i)
                i += 2  # descend so ${x:-$(...)} is censused
                continue
            i += 1
            continue

        if not in_dq and c in "<>" and i + 1 < n and text[i + 1] == "(":
            end = _skip_matching(text, i + 1, "(", ")")
            if end < 0:
                fatal.append(FATAL_UNBALANCED + ":procsub")
                return {"obligations": obligations, "fatal": fatal}
            emit(KIND_PROCSUB, i)
            i += 2
            continue

        if not in_dq and text.startswith("<<", i):
            if text.startswith("<<<", i):
                emit(KIND_HEREDOC, i)
                i += 3
                continue
            emit(KIND_HEREDOC, i)
            j = i + 2
            if j < n and text[j] == "-":
                j += 1
            while j < n and text[j] in " \t":
                j += 1
            # Delimiter word: quoted delimiter -> literal body, else expandable.
            quoted = False
            delim_chars = []
            while j < n and text[j] not in " \t\n;&|<>()":
                ch = text[j]
                if ch == "'":
                    quoted = True
                    k = text.find("'", j + 1)
                    if k < 0:
                        fatal.append(FATAL_UNBALANCED + ":heredoc_delim")
                        return {"obligations": obligations, "fatal": fatal}
                    delim_chars.append(text[j + 1:k])
                    j = k + 1
                    continue
                if ch == '"':
                    quoted = True
                    k = text.find('"', j + 1)
                    if k < 0:
                        fatal.append(FATAL_UNBALANCED + ":heredoc_delim")
                        return {"obligations": obligations, "fatal": fatal}
                    delim_chars.append(text[j + 1:k])
                    j = k + 1
                    continue
                if ch == "\\":
                    quoted = True
                    delim_chars.append(text[j + 1:j + 2])
                    j += 2
                    continue
                delim_chars.append(ch)
                j += 1
            pending_heredocs.append(("".join(delim_chars), quoted))
            i = j
            continue

        if not in_dq and c == "\n" and pending_heredocs:
            pos = i + 1
            for delim, quoted in pending_heredocs:
                body_start = pos
                terminated = False
                while pos <= n:
                    line_end = text.find("\n", pos)
                    if line_end < 0:
                        line_end = n
                    line = text[pos:line_end]
                    if line.strip() == delim:
                        if not quoted:
                            heredoc_bodies.append((text[body_start:pos], body_start))
                        pos = line_end + 1
                        terminated = True
                        break
                    if line_end >= n:
                        pos = n
                        break
                    pos = line_end + 1
                if not terminated:
                    fatal.append(FATAL_UNTERMINATED_HEREDOC)
                    return {"obligations": obligations, "fatal": fatal}
            pending_heredocs = []
            i = pos
            continue

        i += 1

    if in_dq:
        fatal.append(FATAL_UNBALANCED + ":double_quote")
        return {"obligations": obligations, "fatal": fatal}
    if pending_heredocs:
        fatal.append(FATAL_UNTERMINATED_HEREDOC)
        return {"obligations": obligations, "fatal": fatal}

    # Second pass: unquoted heredoc bodies undergo expansion, so any
    # substitution inside them is ACTIVE.  Offsets are mapped back to the
    # original raw string via the joined-offset table.
    nested = [(b, list(range(s, s + len(b))), "heredoc_body:") for b, s in heredoc_bodies]
    nested += [(b, idx, "backtick_body:") for b, idx in nested_bodies]
    for body, idx_map, label in nested:
        sub = census(body)
        for f in sub["fatal"]:
            fatal.append(label + f)
        for ob in sub["obligations"]:
            local = ob["offset"]
            idx = idx_map[local] if 0 <= local < len(idx_map) else -1
            off = offs[idx] if 0 <= idx < len(offs) else -1
            key = (ob["kind"], off)
            if key not in seen:
                seen.add(key)
                obligations.append({"kind": ob["kind"], "offset": off})

    return {"obligations": obligations, "fatal": fatal}


def main() -> int:
    raw = os.environ.get("CMD_INPUT")
    if raw is None:
        raw = sys.stdin.read()
    json.dump(census(raw), sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
