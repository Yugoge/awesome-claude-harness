#!/usr/bin/env python3
"""Context-stripper for pretool-grep-backtrack-guard.py.

PURPOSE (narrow, guard-specific)
--------------------------------
The grep-backtrack guard must inspect the SEARCH PATTERN argument of a grep
invocation, so — unlike the generic pretool-bash-safety stripper — it must NOT
strip the quoted argument that carries a grep pattern. What it MUST remove is
text that is *data, not commands*, so that data which merely MENTIONS a grep
invocation is not mistaken for an executable grep:

  - heredoc / here-doc bodies  (`cat <<EOF ... grep ... EOF` is file content,
    not an executed grep) — UNLESS the heredoc feeds a shell interpreter
    (`bash <<EOF ... EOF`), in which case the body IS shell code and is kept.
  - standalone `#` shell comments.

Everything else — command structure, operators, AND quoted grep patterns — is
preserved verbatim so the guard's own parser can recover (pattern, mode) pairs.

This is deliberately NOT a full shell parser. It is a conservative,
bounded, fail-OPEN-to-raw transform: any error returns the command unchanged
(so the guard still sees the command and can guard it — never blocks legit work
by *losing* a command, never crashes the Bash tool).

Safety invariants (live hook use):
  - bounded input size; oversized input returns raw command.
  - no unbounded recursion; every scanner branch advances the index.
  - on ANY exception, return the raw command unchanged.
"""

from __future__ import annotations

import os
import re

MAX_COMMAND_CHARS = int(os.environ.get("GREPGUARD_CONTEXT_MAX_CHARS", "262144"))

# Interpreters whose heredoc body is executable shell code (keep the body).
_SHELL_INTERPS = {"bash", "sh", "zsh", "dash", "ksh"}


def _scan_heredoc_openers(line):
    """Quote/comment/escape-aware scan for heredoc openers on ONE logical line.

    Returns a list of (delimiter, strip_tabs, owner_fragment) in left-to-right
    order, recognising `<<` / `<<-` ONLY outside single/double quotes, backticks,
    and after an unescaped position — NOT a `<<EOF` that appears inside a quoted
    string or a `#` comment (codex#7). `owner_fragment` is the command text from
    the last command separator up to this operator, used to decide shell-context
    PER opener (codex#8). The delimiter word is parsed as a bash word with
    optional surrounding quotes, supporting arbitrary delimiters like EOF-JSON
    (codex#9). `<<<` here-strings are NOT heredocs and are skipped.
    """
    openers = []
    quote = None
    seg_start = 0  # start of the current command fragment (for owner detection)
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if quote:
            if c == quote:
                quote = None
            elif c == "\\" and quote == '"' and i + 1 < n:
                i += 2
                continue
            i += 1
            continue
        if c in ("'", '"', "`"):
            quote = c
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            i += 2
            continue
        if c == "#" and (i == 0 or line[i - 1].isspace()):
            break  # rest of line is a comment; no openers beyond here
        if c in (";", "|", "&"):
            seg_start = i + 1
        if c == "<" and i + 1 < n and line[i + 1] == "<":
            # Distinguish `<<<` (here-string, NOT a heredoc) from `<<` / `<<-`.
            if i + 2 < n and line[i + 2] == "<":
                i += 3
                continue
            k = i + 2
            strip_tabs = False
            if k < n and line[k] == "-":
                strip_tabs = True
                k += 1
            while k < n and line[k] in " \t":
                k += 1
            # Parse the delimiter word: optional surrounding quote, else a run of
            # word chars up to whitespace / redirection / separator.
            delim = None
            if k < n and line[k] in ("'", '"'):
                q = line[k]
                k2 = k + 1
                while k2 < n and line[k2] != q:
                    k2 += 1
                delim = line[k + 1:k2]
                k = k2 + 1 if k2 < n else k2
            else:
                k2 = k
                while k2 < n and line[k2] not in " \t\n;|&<>()":
                    k2 += 1
                delim = line[k:k2]
                k = k2
            if delim:
                owner = line[seg_start:i]
                openers.append((delim, strip_tabs, owner))
            i = k
            continue
        i += 1
    return openers


def _first_word(text: str) -> str:
    """Best-effort first command word of a fragment (basename), ignoring leading
    assignments and a couple of common wrappers. Used only to decide whether a
    heredoc feeds a shell interpreter."""
    for raw in text.strip().split():
        w = raw
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w):
            continue  # leading VAR=val assignment
        if w in ("env", "time", "sudo", "nice", "ionice", "nohup", "command", "builtin"):
            continue  # transparent wrappers
        return w.rsplit("/", 1)[-1]
    return ""


def _strip_line_comment(line: str) -> str:
    """Remove a trailing/standalone `#` comment from a single logical line,
    respecting single/double quotes and backticks so a `#` inside a quoted grep
    pattern (e.g. grep '#define') is preserved. A `#` is a comment only at the
    start of a word (preceded by start-of-line or whitespace)."""
    out = []
    quote = None
    i = 0
    n = len(line)
    prev = ""
    while i < n:
        c = line[i]
        if quote:
            out.append(c)
            if c == quote:
                quote = None
            elif c == "\\" and quote == '"' and i + 1 < n:
                out.append(line[i + 1])
                i += 2
                prev = ""
                continue
        elif c in ("'", '"', "`"):
            quote = c
            out.append(c)
        elif c == "\\" and i + 1 < n:
            out.append(c)
            out.append(line[i + 1])
            i += 2
            prev = ""
            continue
        elif c == "#" and (prev == "" or prev.isspace()):
            break  # rest of line is a comment
        else:
            out.append(c)
        prev = c
        i += 1
    return "".join(out)


def _terminates(body_line: str, delim: str, strip_tabs: bool) -> bool:
    """A heredoc body line terminates the doc when it equals the delimiter. For
    `<<` the match is EXACT (no surrounding whitespace stripped — codex#9); for
    `<<-` leading TABS only are stripped before comparison (bash semantics)."""
    candidate = body_line.lstrip("\t") if strip_tabs else body_line
    return candidate == delim


def _process_heredocs(cmd: str) -> str:
    """Blank out non-shell heredoc bodies; keep shell-interpreter heredoc bodies.

    Handles MULTIPLE heredocs on one opener line (`cat <<A <<B`) by consuming
    bodies in opener order, deciding shell-context PER opener from the command
    fragment that OWNS each operator (codex#8), and recognising openers only
    outside quotes/comments (codex#7) with bash-word delimiters (codex#9)."""
    if "<<" not in cmd:
        return cmd
    lines = cmd.split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        openers = _scan_heredoc_openers(line)
        out.append(line)
        i += 1
        for delim, strip_tabs, owner in openers:
            shell_ctx = _first_word(owner) in _SHELL_INTERPS
            body: list[str] = []
            while i < n and not _terminates(lines[i], delim, strip_tabs):
                body.append(lines[i])
                i += 1
            # Replace body with blanks unless it feeds a shell interpreter.
            out.extend(body if shell_ctx else ["" for _ in body])
            if i < n:  # the closing delimiter line
                out.append(lines[i])
                i += 1
    return "\n".join(out)


def strip_non_executable_contexts(cmd: str) -> str:
    """Return a guard-friendly view of *cmd*: heredoc data bodies and shell
    comments removed, command structure and quoted grep patterns preserved.

    Fail-OPEN-to-raw: any problem returns *cmd* unchanged so the guard still
    inspects the real command.
    """
    if not isinstance(cmd, str):
        return ""
    if len(cmd) > MAX_COMMAND_CHARS:
        return cmd
    try:
        stripped = _process_heredocs(cmd)
        # Strip standalone comments line-by-line (heredoc bodies are already
        # blanked, so a `#` left here is a real comment or inside a real command).
        return "\n".join(_strip_line_comment(ln) for ln in stripped.split("\n"))
    except Exception:
        return cmd


if __name__ == "__main__":
    print(strip_non_executable_contexts(os.environ.get("CMD_INPUT", "")))
