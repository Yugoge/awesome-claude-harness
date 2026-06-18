#!/usr/bin/env python3
"""Shared helper: parse Bash commands to extract write targets.

Provides two public functions used by tool-policy and overnight-hook-guard:

  command_without_heredoc_bodies(command) -> str
      Strip heredoc PAYLOAD lines from a shell command, keeping the
      heredoc OPENER line intact. Supports <<EOF, <<-EOF (tab-stripped),
      and <<'QUOTED' / <<"QUOTED" variants. Unclosed heredocs (no closing
      delimiter) fall back to dropping all lines after the opener.

  extract_bash_write_paths(command) -> list[str]
      Parse the heredoc-stripped command and extract every write target
      from common shell write idioms:
        - '> FILE' / '>> FILE' (redirect / append redirect)
        - 'tee FILE' / 'tee -a FILE' (tee / append-tee)
        - 'cp X DEST' / 'mv X DEST'
        - 'sed -i [PATTERN] FILE' (in-place editor)
        - 'install [-m MODE] X DEST'
        - here-string '<<<' followed by a redirect on the same line
      Resolves $HOME, ~, and $CLAUDE_PROJECT_DIR. Leaves other
      $UNRESOLVED_VAR tokens as-is. Returns absolute or workspace-
      relative path strings.

These helpers are intentionally regex-based (NOT a full shell parser).
They prioritize correctness on the patterns documented above and fail
soft on exotic syntax (compound substitutions, dynamic eval, etc.).

Doctest examples (run via `python3 -m doctest bash_write_targets.py`):

>>> command_without_heredoc_bodies('cat > /tmp/a << EOF\\nhello\\nEOF')
'cat > /tmp/a << EOF'

>>> extract_bash_write_paths('cat > /root/foo.txt << EOF\\nhello\\nEOF')
['/root/foo.txt']

>>> extract_bash_write_paths('cat > /root/a.txt << EOF\\necho > /root/b.txt\\nEOF')
['/root/a.txt']

>>> extract_bash_write_paths('tee /root/x.txt')
['/root/x.txt']

>>> extract_bash_write_paths('tee -a /root/x.txt')
['/root/x.txt']

>>> extract_bash_write_paths('cp src dest')
['dest']

>>> extract_bash_write_paths('mv src dest')
['dest']

>>> extract_bash_write_paths('sed -i s/a/b/ /root/file')
['/root/file']

>>> extract_bash_write_paths('install -m 755 src /usr/local/bin/x')
['/usr/local/bin/x']

>>> extract_bash_write_paths('echo X')
[]

>>> extract_bash_write_paths('cmd <<<"hello world" > /root/out')
['/root/out']

>>> extract_bash_write_paths('echo hello >> /var/log/app.log')
['/var/log/app.log']

>>> extract_bash_write_paths("cat <<-'END'\\n\\techo > /tmp/inside\\n\\tEND") == []
True

>>> extract_bash_write_paths("echo 'need >=10/3 items'")
[]

>>> extract_bash_write_paths("codex 'this is a Design gap >design fix this'")
[]

>>> extract_bash_write_paths("echo 'foo > bar'")
[]
"""

from __future__ import annotations

import os
import re
from typing import List, Tuple

# Heredoc opener pattern. Captures three groups:
#   1: dash flag (- means tab-stripped form)
#   2: optional quote (' or ")
#   3: delimiter token
# Examples matched: '<< EOF', '<<EOF', '<<-EOF', "<<'QUOTED'", '<<"QUOTED"'
_HEREDOC_OPENER_RE = re.compile(r"<<(-?)\s*([\"'])?([A-Za-z_][A-Za-z0-9_]*)\2?")


def _detect_heredoc_opener(line: str) -> Tuple[bool, str, bool]:
    """Return (found, delimiter, dash_form) for the right-most heredoc opener."""
    matches = list(_HEREDOC_OPENER_RE.finditer(line))
    if not matches:
        return (False, "", False)
    m = matches[-1]
    return (True, m.group(3), m.group(1) == "-")


def _is_heredoc_closer(payload_line: str, delim: str, dash: bool) -> bool:
    """True if payload_line is the matching delimiter line."""
    stripped = payload_line.lstrip("\t") if dash else payload_line
    return stripped.strip() == delim


def _skip_heredoc_payload(lines: List[str], start: int, delim: str, dash: bool) -> int:
    """Advance past heredoc payload lines and the closing delimiter.

    Returns the index of the line AFTER the closing delimiter, or
    len(lines) if the heredoc is unclosed.
    """
    i = start
    while i < len(lines):
        if _is_heredoc_closer(lines[i], delim, dash):
            return i + 1
        i += 1
    return i


def command_without_heredoc_bodies(command: str) -> str:
    """Return command with heredoc payload lines stripped.

    The opener line (e.g. 'cat > FILE << EOF') is preserved so that
    write-target extraction still sees the redirect; payload lines and
    the closing delimiter line are removed.

    Multiple heredocs in a single command are handled sequentially.
    Unclosed heredocs (no matching delimiter found) drop all
    subsequent lines.
    """
    if not isinstance(command, str):
        return ""
    if "<<" not in command:
        return command
    lines = command.split("\n")
    out_lines: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out_lines.append(line)
        found, delim, dash = _detect_heredoc_opener(line)
        if not found:
            i += 1
            continue
        i = _skip_heredoc_payload(lines, i + 1, delim, dash)
    return "\n".join(out_lines)


def _resolve_path(token: str) -> str:
    """Resolve $HOME, ~, and $CLAUDE_PROJECT_DIR. Leave others as-is."""
    if not token:
        return token
    # Strip surrounding quotes if present
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
        token = token[1:-1]
    # Tilde expansion
    if token.startswith("~"):
        token = os.path.expanduser(token)
    # $HOME / ${HOME} — WS1: fall back to the real user home, never the literal
    # /root, when HOME is unset (a fresh non-root clone).
    home = os.environ.get("HOME") or os.path.expanduser("~")
    token = token.replace("${HOME}", home).replace("$HOME", home)
    # $CLAUDE_PROJECT_DIR / ${CLAUDE_PROJECT_DIR}
    cpd = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if cpd:
        token = token.replace("${CLAUDE_PROJECT_DIR}", cpd)
        token = token.replace("$CLAUDE_PROJECT_DIR", cpd)
    return token


# Regex for redirect targets. Matches '>' or '>>' followed by optional
# whitespace and a token (path). Excludes '>&' (fd duplication like '2>&1')
# and process substitution '>(...)'. The '(?<![<>])' lookbehind prevents
# matching the '>' inside '<<'.
_REDIRECT_RE = re.compile(r"(?<![<>&\'\"])(?:>>?)\s*(?![&\(])([^\s;|&<>]+)")

# tee FILE / tee -a FILE  (also -ai, --append, etc — keep simple: -a flag form)
_TEE_RE = re.compile(r"(?:^|[\s;|&])tee\b((?:\s+-[aAip]+)*)\s+([^\s;|&<>]+)")

# cp/mv: capture rest-of-segment after 'cp '/'mv '. Caller takes last
# non-flag token as DEST.
_CP_MV_RE = re.compile(r"(?:^|[\s;|&])(cp|mv)\b([^;|&\n]+)")

# sed -i [PATTERN] FILE  — '-i' may be combined with other flags. Capture
# all tokens after 'sed -i' so caller can take the last one as FILE.
_SED_I_RE = re.compile(r"(?:^|[\s;|&])sed\b([^;|&\n]*?-i[^\s;|&\n]*)([^;|&\n]+)")

# install -m MODE SRC DEST  (DEST is last positional)
_INSTALL_RE = re.compile(r"(?:^|[\s;|&])install\b([^;|&\n]+)")


def _read_path_token_from_original(original: str, start: int) -> str:
    """Read the next path token from `original` starting at offset `start`.

    Skips leading whitespace. If the next char is `'` or `"`, consumes to
    the matching close-quote and strips the surrounding quotes (so a
    quoted PATH like `"/tmp/y"` yields `/tmp/y`). Otherwise reads to the
    next whitespace or shell separator (`;|&<>`).
    """
    i, n = start, len(original)
    while i < n and original[i].isspace():
        i += 1
    if i >= n:
        return ""
    if original[i] in ("'", '"'):
        quote = original[i]
        j = i + 1
        while j < n and original[j] != quote:
            j += 1
        return original[i + 1:j]
    j = i
    while j < n and original[j] not in " \t\n;|&<>":
        j += 1
    return original[i:j]


# Operator-only patterns for masked-text scanning (no path capture; path
# is read from the ORIGINAL text via _read_path_token_from_original).
# Preserves the lookbehind from fae388e for adjacent-quote edge cases.
_REDIRECT_OP_RE = re.compile(r"(?<![<>&\'\"])(?:>>?)(?![&\(])")
_TEE_OP_RE = re.compile(r"(?:^|[\s;|&])tee\b((?:\s+-[aAip]+)*)")


def _extract_redirect_targets(command_no_heredoc: str) -> List[str]:
    """F3/F4: scan masked text for operator positions; read path from ORIGINAL.

    Quoted CONTENT (e.g. `'need >=10/3 items'`) is neutralized in the masked
    copy so the operator scan skips it. Quoted PATH (e.g. `> "/tmp/y"`) is
    preserved because path extraction reads from the ORIGINAL byte-aligned text.
    """
    masked = _strip_quoted_regions(command_no_heredoc)
    targets: List[str] = []
    for m in _REDIRECT_OP_RE.finditer(masked):
        token = _read_path_token_from_original(command_no_heredoc, m.end()).strip()
        if not token or token.isdigit():
            continue
        targets.append(_resolve_path(token))
    return targets


def _extract_tee_targets(command: str) -> List[str]:
    """F3/F4: scan masked text for tee tokens; read path from ORIGINAL."""
    masked = _strip_quoted_regions(command)
    targets: List[str] = []
    for m in _TEE_OP_RE.finditer(masked):
        path = _read_path_token_from_original(command, m.end()).strip()
        if path:
            targets.append(_resolve_path(path))
    return targets


def _last_non_flag_token(tokens: List[str]) -> str:
    """Return the last token that does not start with '-'."""
    for t in reversed(tokens):
        if not t.startswith("-"):
            return t
    return ""


def _split_at_redirect(rest: str) -> str:
    """Truncate the segment at the first redirect operator."""
    return re.split(r"(?:>>?|<<?)", rest, maxsplit=1)[0]


def _strip_quoted_regions(s: str) -> str:
    """Replace single- and double-quoted spans with same-length whitespace.

    Preserves byte offsets so other regex consumers continue to align.
    Used to prevent _CP_MV_RE from matching cp/mv tokens inside quoted
    strings (C3) and to neutralize quoted argument payloads in general.
    """
    out = list(s)
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch in ("'", '"'):
            j = i + 1
            while j < n and s[j] != ch:
                j += 1
            for k in range(i, min(j + 1, n)):
                out[k] = ' '
            i = j + 1
        else:
            i += 1
    return ''.join(out)


def _strip_reason_payload(s: str) -> str:
    """Replace the token following '--reason' with whitespace placeholder.

    Preserves byte offsets. C25: prevents `--reason "scope reduction"`
    payloads (quoted or bare) from being treated as write targets.
    """
    out = list(s)
    for m in re.finditer(r"--reason\b", s):
        i = m.end()
        # Skip leading whitespace
        while i < len(s) and s[i].isspace():
            i += 1
        if i >= len(s):
            continue
        # Quoted form: erase from opening quote through matching close quote
        if s[i] in ("'", '"'):
            quote = s[i]
            j = i + 1
            while j < len(s) and s[j] != quote:
                j += 1
            for k in range(i, min(j + 1, len(s))):
                out[k] = ' '
            continue
        # Bare-word form: erase non-whitespace token
        while i < len(s) and not s[i].isspace():
            out[i] = ' '
            i += 1
    return ''.join(out)


def _extract_cp_mv_targets(command: str) -> List[str]:
    targets: List[str] = []
    scan = _strip_quoted_regions(command)
    for m in _CP_MV_RE.finditer(scan):
        rest = _split_at_redirect(m.group(2).strip())
        dest = _last_non_flag_token(rest.split())
        if dest:
            targets.append(_resolve_path(dest))
    return targets


def _extract_sed_i_targets(command: str) -> List[str]:
    targets: List[str] = []
    for m in _SED_I_RE.finditer(command):
        rest = _split_at_redirect(m.group(2).strip())
        file_arg = _last_non_flag_token(rest.split())
        if file_arg:
            targets.append(_resolve_path(file_arg))
    return targets


# Flag tokens that take a separate value argument (skip next token).
_INSTALL_VALUE_FLAGS = {"-m", "--mode", "-o", "--owner", "-g", "--group"}


def _filter_install_positionals(tokens: List[str]) -> List[str]:
    """Return install command positional arguments (drop flags + flag values)."""
    cleaned: List[str] = []
    skip_next = False
    for t in tokens:
        if skip_next:
            skip_next = False
            continue
        if t in _INSTALL_VALUE_FLAGS:
            skip_next = True
            continue
        if t.startswith("-"):
            continue
        cleaned.append(t)
    return cleaned


def _extract_install_targets(command: str) -> List[str]:
    targets: List[str] = []
    for m in _INSTALL_RE.finditer(command):
        rest = _split_at_redirect(m.group(1).strip())
        positionals = _filter_install_positionals(rest.split())
        if not positionals:
            continue
        # DEST is last positional; if only one positional, install creates
        # that path (directory or file).
        targets.append(_resolve_path(positionals[-1]))
    return targets


def extract_bash_write_paths(command: str) -> List[str]:
    """Extract write-target paths from a bash command string.

    Strips heredoc bodies first, then scans for redirect targets, tee,
    cp/mv DEST, sed -i FILE, and install DEST. Returns a deduplicated
    list preserving first-seen order.
    """
    if not isinstance(command, str) or not command.strip():
        return []
    stripped = command_without_heredoc_bodies(command)
    stripped = _strip_reason_payload(stripped)
    targets: List[str] = []
    targets.extend(_extract_redirect_targets(stripped))
    targets.extend(_extract_tee_targets(stripped))
    targets.extend(_extract_cp_mv_targets(stripped))
    targets.extend(_extract_sed_i_targets(stripped))
    targets.extend(_extract_install_targets(stripped))
    # Dedupe while preserving order
    seen = set()
    deduped: List[str] = []
    for t in targets:
        if t and t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped


if __name__ == "__main__":
    # Self-test entrypoint: run doctests when invoked directly.
    import doctest

    failures, _ = doctest.testmod(verbose=True)
    raise SystemExit(0 if failures == 0 else 1)
