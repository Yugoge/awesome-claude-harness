#!/usr/bin/env python3
"""Shell-command lexing primitives for the protected-runtime guard.

Pure text tokenizers split out of _core.py in the phase-1 monolith
decomposition (2026-07-15). This module is a dependency LEAF: it imports only
the stdlib and references nothing from _core, so _core imports these names back
at load time without a circular dependency. Relocating them here leaves _core's
public surface identical (every `from ..._core import _strip_quotes` and every
internal call still resolves) — see docs/reference/monolith-split-plan.md.

Scope: quote-aware pipeline / compound-group splitting, fd-redirect detection,
and write-redirect target extraction — the one layer that must agree
byte-for-byte across every downstream primitive, so it lives in one place.
ZERO project identifiers.
"""

from __future__ import annotations

import re
import shlex
from typing import Optional


# ── Tokenization that preserves redirections (> >> ) which shlex eats ────────

def _split_pipeline(command: str) -> list:
    """Split a bash command into simple commands across ; && || | and newlines.

    Conservative: operates on the raw text but only at unquoted top level by a
    cheap quote-aware scan. Returns a list of raw simple-command strings.
    """
    parts = []
    buf = []
    i = 0
    n = len(command)
    quote = None
    subst_depth = 0   # inside $(...) command substitution
    backtick = False  # inside `...` command substitution
    while i < n:
        c = command[i]
        if quote == "'":
            # single quotes: no escaping inside; only a matching ' ends it.
            buf.append(c)
            if c == "'":
                quote = None
            i += 1
            continue
        if quote == '"':
            # double quotes: backslash escapes ", \, $, `, newline — those do
            # NOT terminate the quote. Any other char (incl. an escaped ;/&/|)
            # stays inside the quote, so a quoted separator never splits.
            if c == "\\" and i + 1 < n and command[i + 1] in ('"', "\\", "$", "`", "\n"):
                buf.append(c); buf.append(command[i + 1]); i += 2; continue
            buf.append(c)
            if c == '"':
                quote = None
            i += 1
            continue
        # unquoted context
        if c in ("'", '"'):
            quote = c
            buf.append(c)
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            buf.append(c)
            buf.append(command[i + 1])
            i += 2
            continue
        # command-substitution tracking: separators inside $()/`` do NOT split
        # the OUTER simple command (the whole substitution belongs to it).
        if c == "`":
            backtick = not backtick
            buf.append(c); i += 1; continue
        if command[i:i + 2] in ("$(", "<(", ">("):
            subst_depth += 1
            buf.append(command[i:i + 2]); i += 2; continue
        if c == ")" and subst_depth > 0:
            subst_depth -= 1
            buf.append(c); i += 1; continue
        if subst_depth > 0 or backtick:
            buf.append(c); i += 1; continue
        # fd-redirection `&` (2>&1, >&, &>, &>>, >&2) is NOT a separator.
        if c == "&" and _is_redirect_amp(command, i):
            buf.append(c); i += 1; continue
        two = command[i:i + 2]
        if two in ("&&", "||", "|&"):
            parts.append("".join(buf)); buf = []; i += 2; continue
        if c in (";", "|", "\n", "&"):
            parts.append("".join(buf)); buf = []; i += 1; continue
        buf.append(c)
        i += 1
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _is_redirect_amp(command: str, i: int) -> bool:
    """True if the `&` at index i is part of an fd redirection, not a separator.

    Forms: `>&`, `<&`, `&>`, `&>>`, `2>&1`, `>&2`. Heuristic: preceded by a
    redirection operator (`>`/`<` possibly with a leading fd digit) OR followed
    by `>`/a digit/`-` (the `&>file` / `&>>file` form). `&&` is handled earlier.
    """
    n = len(command)
    nxt = command[i + 1] if i + 1 < n else ""
    if nxt == "&":
        return False  # `&&` control operator
    # &>file / &>>file / &- forms
    if nxt in (">", "-") or nxt.isdigit():
        return True
    # preceding char is a redirection operator (>& / <&), optionally fd-prefixed
    j = i - 1
    while j >= 0 and command[j] == " ":
        j -= 1
    if j >= 0 and command[j] in (">", "<"):
        return True
    return False


def _strip_compound_delims(command: str) -> str:
    """Neutralize shell compound-group delimiters `( ) { }` at the UNQUOTED top
    level by replacing them with a `;` separator, so a grouped launch/build
    (`(cd x && npx tsc)`, `{ cd x; node y; }`) decomposes into ordinary simple
    commands the splitters already handle. Conservative for a security guard:
    turning a group boundary into a separator can only split MORE (never hide a
    command word), so it cannot cause under-blocking. Quote/escape aware.
    """
    out = []
    i = 0
    n = len(command)
    quote = None
    subst_depth = 0  # `$(` depth — its `)` must be preserved, not neutralized
    brace_expr_depth = 0  # `${` depth — its `}` must be preserved
    while i < n:
        c = command[i]
        if quote == "'":
            out.append(c)
            if c == "'":
                quote = None
            i += 1
            continue
        if quote == '"':
            if c == "\\" and i + 1 < n and command[i + 1] in ('"', "\\", "$", "`", "\n"):
                out.append(c); out.append(command[i + 1]); i += 2; continue
            out.append(c)
            if c == '"':
                quote = None
            i += 1
            continue
        if c in ("'", '"'):
            quote = c
            out.append(c)
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            out.append(c); out.append(command[i + 1]); i += 2; continue
        # `$(` command substitution and `${` parameter expansion are preserved
        # intact (their closing `)`/`}` is NOT a compound-group delimiter).
        # Process substitutions `<(...)` / `>(...)` are likewise preserved so a
        # kill/xargs fed by `<(pgrep -f <ident>)` keeps the inner pipeline intact
        # for P6 connectivity analysis.
        if command[i:i + 2] in ("<(", ">("):
            subst_depth += 1
            out.append(command[i:i + 2]); i += 2; continue
        if command[i:i + 2] == "$(":
            subst_depth += 1
            out.append("$("); i += 2; continue
        if command[i:i + 2] == "${":
            brace_expr_depth += 1
            out.append("${"); i += 2; continue
        if c == ")" and subst_depth > 0:
            subst_depth -= 1
            out.append(c); i += 1; continue
        if c == "}" and brace_expr_depth > 0:
            brace_expr_depth -= 1
            out.append(c); i += 1; continue
        if subst_depth > 0 or brace_expr_depth > 0:
            out.append(c); i += 1; continue
        # Parentheses are always sub-shell group delimiters → `;`.
        if c in ("(", ")"):
            out.append(" ; "); i += 1; continue
        # Braces are a command GROUP only as standalone `{`/`}` words:
        # `{ cmd; }`. An adjacent `{}` (xargs replstr), `{a,b}` brace expansion,
        # or `-I{}` must be left intact (mangling them breaks legitimate parsing
        # and can hide an xargs placeholder). Treat `{` as a group open only when
        # followed by whitespace, and `}` as a group close only when preceded by
        # whitespace or `;`.
        if c == "{" and i + 1 < n and command[i + 1] in (" ", "\t"):
            out.append(" ; "); i += 1; continue
        if c == "}" and out and out[-1] in (" ", "\t", ";"):
            out.append(" ; "); i += 1; continue
        out.append(c)
        i += 1
    return "".join(out)


def _has_redirect_to(simple_cmd: str) -> Optional[str]:
    """Return the FIRST bare `>`/`>>` write-redirect target (legacy/back-compat).

    Prefer `_write_redirect_targets` (below) for completeness — it returns ALL
    write-redirect targets incl. the fd-prefixed / force forms. This narrower helper
    is retained only where a single first-target probe is sufficient.
    """
    m = re.search(r"(?<![0-9<>])>>?\s*([^\s;&|<>]+)", simple_cmd)
    if m:
        return _strip_quotes(m.group(1))
    return None


# ONE shared write-redirect-target scanner. A protected file is MUTATED when it is
# the target of ANY write redirect anywhere in the simple command, for every form:
#   `>`  `>>`  `>|`  (force-clobber)   `1>` `2>` `N>` `N>>` `N>|` (fd-prefixed)
#   `&>` `&>>` `&>|` (stdout+stderr).  Read redirects (`<`, `N<`) are NOT targets.
# Returns EVERY such target (not just the first), so a non-first redirect to a
# protected path (`echo x > /tmp/out 2><protected>`) is caught. Used by both the
# bundle/statefile path (`_mutation_targets`) and STEP0 config self-protection, so
# the redirect coverage cannot drift between families.
_WRITE_REDIRECT_RE = re.compile(
    r"(?:^|[\s;&|])"          # start or a shell separator before the operator
    r"(?:&|\d+)?"             # optional fd prefix: a digit run or `&` (stdout+stderr)
    r">>?\|?"                 # the write operator: > or >> with an optional force `|`
    r"\s*([^\s;&|<>]+)"       # the target token (next bareword)
)


def _write_redirect_targets(simple_cmd: str) -> list:
    """Return ALL write-redirect target paths in a simple command (every form)."""
    return [_strip_quotes(m) for m in _WRITE_REDIRECT_RE.findall(simple_cmd)]


def _strip_quotes(tok: str) -> str:
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in ("'", '"'):
        return tok[1:-1]
    return tok


def _safe_shlex(simple_cmd: str) -> list:
    try:
        return shlex.split(simple_cmd, comments=False)
    except ValueError:
        # Unbalanced quotes etc. — fall back to whitespace split.
        return [t for t in re.split(r"\s+", simple_cmd) if t]
