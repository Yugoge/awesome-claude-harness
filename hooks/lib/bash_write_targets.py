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
from typing import List, NamedTuple, Tuple

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


def _next_token_from_original(original: str, start: int) -> Tuple[str, int]:
    """Read the next token from `original` and return (token, next_offset).

    Sole implementation of the quoted-PATH-vs-quoted-CONTENT rule; both
    `_read_path_token_from_original` (frozen public behaviour) and the
    write-mode segment tokenizer delegate here so the rule exists once.

    Skips leading whitespace. If the next char is `'` or `"`, consumes to
    the matching close-quote and strips the surrounding quotes (so a
    quoted PATH like `"/tmp/y"` yields `/tmp/y`). Otherwise reads to the
    next whitespace or shell separator (`;|&<>`).
    """
    i, n = start, len(original)
    while i < n and original[i].isspace():
        i += 1
    if i >= n:
        return ("", n)
    if original[i] in ("'", '"'):
        quote = original[i]
        j = i + 1
        while j < n and original[j] != quote:
            j += 1
        return (original[i + 1:j], min(j + 1, n))
    j = i
    while j < n and original[j] not in " \t\n;|&<>":
        j += 1
    return (original[i:j], j)


def _read_path_token_from_original(original: str, start: int) -> str:
    """Read the next path token from `original` starting at offset `start`.

    Thin projection of `_next_token_from_original`; behaviour unchanged.
    """
    return _next_token_from_original(original, start)[0]


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


# ---------------------------------------------------------------------------
# Write-MODE classification (ADDITIVE — task dev-20260804-010515-overwrite, M3)
#
# Everything above this banner is FROZEN. `extract_bash_write_paths()` keeps its
# name, signature and return shape because THREE hooks consume it
# (pretool-tool-policy.py, pretool-overnight-hook-guard.py and
# pretool-cp-state-write-guard.py — the last is itself a security guard).
#
# The functions below answer a question the frozen extractor never asked: not
# "which paths does this command write?" but "in what MODE does it write them?"
# — because replacing an existing file and appending to one are the same path
# and opposite acts.
# ---------------------------------------------------------------------------

MODE_TRUNCATING = "truncating"
MODE_APPENDING = "appending"
MODE_RENAME_INTO_PLACE = "rename_into_place"
MODE_DESTROYING = "destroying"
MODE_IN_PLACE_EDIT = "in_place_edit"

#: Modes that destroy the previous contents of an EXISTING target wholesale.
#: Appending and in-place editing derive their output from the original, so
#: neither is a replacement and neither is ever gated.
REPLACING_MODES = frozenset({MODE_TRUNCATING, MODE_RENAME_INTO_PLACE, MODE_DESTROYING})


class WriteTarget(NamedTuple):
    """One write target with its mode.

    Fields 0 and 1 are exactly the ``(path, write_mode)`` pair the requirement
    asks for; ``source`` is carried because the move-into-a-directory rule has
    to re-resolve a directory destination to ``<dir>/<basename(source)>`` and
    cannot do so from the destination alone.
    """

    path: str
    mode: str
    mechanism: str
    source: str = ""


def _segment_end(masked: str, start: int) -> int:
    """Offset of the first shell separator at/after `start` in masked text."""
    for k in range(start, len(masked)):
        if masked[k] in ";|&\n":
            return k
    return len(masked)


def _segment_tokens(original: str, masked: str, start: int) -> List[str]:
    """Tokenize one command segment, reading tokens from the ORIGINAL text.

    `masked` (quoted spans blanked, byte offsets preserved) supplies the
    segment boundary so a separator inside a quoted argument does not cut the
    segment short; `original` supplies the token bytes so a quoted PATH
    survives intact. Stops at a redirect operator, mirroring _split_at_redirect.
    """
    end = _segment_end(masked, start)
    tokens: List[str] = []
    i = start
    while i < end:
        tok, nxt = _next_token_from_original(original, i)
        if nxt <= i:
            break
        if tok:
            tokens.append(tok)
        i = nxt
    return tokens


# Redirect operators, mode-aware. Adds the clobber form '>|' that the frozen
# extractor cannot name (its path reader stops on the '|'). '>&' (fd
# duplication, e.g. 2>&1) and '>(' (process substitution) stay excluded, and
# '&>' stays OUT — it is a declared uncovered route, not a silent omission.
_REDIRECT_MODE_OP_RE = re.compile(r"(?<![<>&\'\"])(>>|>\||>)(?![&\(])")
_REDIRECT_MECHANISM = {">>": "redirect-append", ">|": "redirect-clobber", ">": "redirect-truncate"}

_TEE_WORD_RE = re.compile(r"(?:^|[\s;|&])tee\b")
_CP_MV_WORD_RE = re.compile(r"(?:^|[\s;|&])(cp|mv)\b")
_INSTALL_WORD_RE = re.compile(r"(?:^|[\s;|&])install\b")
_TRUNCATE_WORD_RE = re.compile(r"(?:^|[\s;|&])truncate\b")
_DD_WORD_RE = re.compile(r"(?:^|[\s;|&])dd\b")
_CURL_WORD_RE = re.compile(r"(?:^|[\s;|&])curl\b")
_WGET_WORD_RE = re.compile(r"(?:^|[\s;|&])wget\b")
_UNLINK_WORD_RE = re.compile(r"(?:^|[\s;|&])unlink\b")

# Occurrences carrying any of these are NOT attributed a target: the write
# destination is not decidable from command text, so naming one would be a
# guess. Each is a declared uncovered route rather than a silent miss.
_CP_UNDECIDABLE = {"-r", "-R", "--recursive", "-a", "--archive", "-t", "--target-directory"}
_MV_UNDECIDABLE = {"-t", "--target-directory"}
_INSTALL_UNDECIDABLE = {"-d", "--directory", "-t", "--target-directory"}
# Flags whose VALUE is a separate following token (skip that token).
_TRUNCATE_VALUE_FLAGS = {"-s", "--size", "-r", "--reference"}


def _positionals(tokens: List[str], value_flags: frozenset | set = frozenset()) -> List[str]:
    """Non-flag tokens, dropping flags and the values they consume."""
    out: List[str] = []
    skip = False
    for t in tokens:
        if skip:
            skip = False
            continue
        if t in value_flags:
            skip = True
            continue
        if t.startswith("-") and t != "-":
            continue
        out.append(t)
    return out


def _extract_redirect_mode_targets(command: str) -> List[WriteTarget]:
    masked = _strip_quoted_regions(command)
    out: List[WriteTarget] = []
    for m in _REDIRECT_MODE_OP_RE.finditer(masked):
        op = m.group(1)
        token = _read_path_token_from_original(command, m.end()).strip()
        if not token or token.isdigit():
            continue
        mode = MODE_APPENDING if op == ">>" else MODE_TRUNCATING
        out.append(WriteTarget(_resolve_path(token), mode, _REDIRECT_MECHANISM[op]))
    return out


def _extract_tee_mode_targets(command: str) -> List[WriteTarget]:
    masked = _strip_quoted_regions(command)
    out: List[WriteTarget] = []
    for m in _TEE_WORD_RE.finditer(masked):
        tokens = _segment_tokens(command, masked, m.end())
        append = any(
            t == "--append" or (t.startswith("-") and not t.startswith("--") and "a" in t[1:])
            for t in tokens
        )
        mode = MODE_APPENDING if append else MODE_TRUNCATING
        mech = "tee-append" if append else "tee-truncate"
        for path in _positionals(tokens):
            out.append(WriteTarget(_resolve_path(path), mode, mech))
    return out


def _extract_cp_mv_mode_targets(command: str) -> List[WriteTarget]:
    masked = _strip_quoted_regions(command)
    out: List[WriteTarget] = []
    for m in _CP_MV_WORD_RE.finditer(masked):
        verb = m.group(1)
        tokens = _segment_tokens(command, masked, m.end())
        undecidable = _CP_UNDECIDABLE if verb == "cp" else _MV_UNDECIDABLE
        if any(t in undecidable for t in tokens):
            continue
        if verb == "cp" and any(
            t.startswith("-") and not t.startswith("--") and ("r" in t[1:] or "R" in t[1:] or "a" in t[1:])
            for t in tokens
        ):
            continue
        positionals = _positionals(tokens)
        if not positionals:
            continue
        dest = positionals[-1]
        source = positionals[-2] if len(positionals) >= 2 else ""
        mode = MODE_RENAME_INTO_PLACE if verb == "mv" else MODE_TRUNCATING
        out.append(WriteTarget(_resolve_path(dest), mode, f"{verb}-dest",
                               _resolve_path(source) if source else ""))
    return out


#: `install` as a package-manager SUBCOMMAND names packages, not paths. Naming a
#: package as a write target is the cries-wolf failure the requirement forbids:
#: `pip install requests` in a directory holding a file called `requests` would
#: otherwise be refused as a replacement.
_PKG_MANAGERS = frozenset({
    "pip", "pip3", "npm", "pnpm", "yarn", "apt", "apt-get", "aptitude", "yum",
    "dnf", "apk", "zypper", "pacman", "brew", "cargo", "gem", "go", "poetry",
    "uv", "conda", "bundle", "composer", "nix-env", "opkg", "stack", "mix",
})


def _preceding_word(masked: str, end_of_word: int, word: str) -> str:
    """The bare word immediately preceding `word`, which ends at `end_of_word`."""
    head = masked[:end_of_word].rstrip()
    if head.endswith(word):
        head = head[: -len(word)]
    parts = head.rstrip().split()
    return parts[-1] if parts else ""


def _extract_install_mode_targets(command: str) -> List[WriteTarget]:
    masked = _strip_quoted_regions(command)
    out: List[WriteTarget] = []
    for m in _INSTALL_WORD_RE.finditer(masked):
        if _preceding_word(masked, m.end(), "install") in _PKG_MANAGERS:
            continue
        tokens = _segment_tokens(command, masked, m.end())
        if any(t in _INSTALL_UNDECIDABLE for t in tokens):
            continue
        positionals = _filter_install_positionals(tokens)
        if not positionals:
            continue
        source = positionals[-2] if len(positionals) >= 2 else ""
        out.append(WriteTarget(_resolve_path(positionals[-1]), MODE_TRUNCATING, "install-dest",
                               _resolve_path(source) if source else ""))
    return out


def _extract_truncate_mode_targets(command: str) -> List[WriteTarget]:
    masked = _strip_quoted_regions(command)
    out: List[WriteTarget] = []
    for m in _TRUNCATE_WORD_RE.finditer(masked):
        tokens = _segment_tokens(command, masked, m.end())
        for path in _positionals(tokens, _TRUNCATE_VALUE_FLAGS):
            out.append(WriteTarget(_resolve_path(path), MODE_TRUNCATING, "truncate-cmd"))
    return out


def _extract_dd_mode_targets(command: str) -> List[WriteTarget]:
    masked = _strip_quoted_regions(command)
    out: List[WriteTarget] = []
    for m in _DD_WORD_RE.finditer(masked):
        tokens = _segment_tokens(command, masked, m.end())
        source = ""
        for t in tokens:
            if t.startswith("if="):
                source = _resolve_path(t[3:])
        for t in tokens:
            if t.startswith("of=") and t[3:]:
                out.append(WriteTarget(_resolve_path(t[3:]), MODE_TRUNCATING, "dd-of", source))
    return out


def _flag_value_targets(tokens: List[str], short: str, long_opt: str) -> List[str]:
    """Values of `-x VALUE`, `--long VALUE`, `--long=VALUE` and `-abx VALUE`."""
    out: List[str] = []
    take_next = False
    for t in tokens:
        if take_next:
            take_next = False
            if t and not t.startswith("-"):
                out.append(t)
            continue
        if t == short or t == long_opt:
            take_next = True
        elif t.startswith(long_opt + "="):
            value = t[len(long_opt) + 1:]
            if value:
                out.append(value)
        elif t.startswith("-") and not t.startswith("--") and t.endswith(short[1:]) and len(t) > 1:
            take_next = True
    return out


def _extract_curl_wget_mode_targets(command: str) -> List[WriteTarget]:
    masked = _strip_quoted_regions(command)
    out: List[WriteTarget] = []
    for word_re, short, long_opt, mech in (
        (_CURL_WORD_RE, "-o", "--output", "curl-output"),
        (_WGET_WORD_RE, "-O", "--output-document", "wget-output"),
    ):
        for m in word_re.finditer(masked):
            tokens = _segment_tokens(command, masked, m.end())
            for path in _flag_value_targets(tokens, short, long_opt):
                out.append(WriteTarget(_resolve_path(path), MODE_TRUNCATING, mech))
    return out


def _extract_unlink_mode_targets(command: str) -> List[WriteTarget]:
    masked = _strip_quoted_regions(command)
    out: List[WriteTarget] = []
    for m in _UNLINK_WORD_RE.finditer(masked):
        positionals = _positionals(_segment_tokens(command, masked, m.end()))
        if positionals:
            out.append(WriteTarget(_resolve_path(positionals[0]), MODE_DESTROYING, "unlink-cmd"))
    return out


def extract_bash_write_targets_with_modes(command: str) -> List[WriteTarget]:
    """Extract (path, write_mode, mechanism, source) for every named write target.

    ADDITIVE sibling of `extract_bash_write_paths`, which is unchanged. A target
    this function cannot name is NOT an implicit denial — the caller's contract
    is affirmative-denial, so an unnamed target is allowed and its syntax is
    declared uncovered.

    >>> [(t.path, t.mode) for t in extract_bash_write_targets_with_modes('echo x > /tmp/a')]
    [('/tmp/a', 'truncating')]

    >>> [(t.path, t.mode) for t in extract_bash_write_targets_with_modes('echo x >> /tmp/a')]
    [('/tmp/a', 'appending')]

    >>> [(t.path, t.mode) for t in extract_bash_write_targets_with_modes('echo x >| /tmp/a')]
    [('/tmp/a', 'truncating')]

    >>> [(t.path, t.mode) for t in extract_bash_write_targets_with_modes('echo x | tee -a /tmp/a')]
    [('/tmp/a', 'appending')]

    >>> [(t.path, t.mode) for t in extract_bash_write_targets_with_modes('truncate -s 0 /tmp/a')]
    [('/tmp/a', 'truncating')]

    >>> [(t.path, t.mode) for t in extract_bash_write_targets_with_modes('dd if=/tmp/s of=/tmp/a')]
    [('/tmp/a', 'truncating')]

    >>> [(t.path, t.mode) for t in extract_bash_write_targets_with_modes('curl -sS -o /tmp/a http://h/f')]
    [('/tmp/a', 'truncating')]

    >>> [(t.path, t.mode) for t in extract_bash_write_targets_with_modes('wget -q -O /tmp/a http://h/f')]
    [('/tmp/a', 'truncating')]

    >>> [(t.path, t.mode) for t in extract_bash_write_targets_with_modes('unlink /tmp/a')]
    [('/tmp/a', 'destroying')]

    >>> [(t.path, t.mode, t.source) for t in extract_bash_write_targets_with_modes('mv /tmp/s /tmp/a')]
    [('/tmp/a', 'rename_into_place', '/tmp/s')]

    >>> [(t.path, t.mode) for t in extract_bash_write_targets_with_modes('sed -i s/a/b/ /tmp/a')]
    [('/tmp/a', 'in_place_edit')]

    Recursive copy carries no decidable single destination, so nothing is named:

    >>> extract_bash_write_targets_with_modes('cp -r /tmp/s /tmp/d')
    []

    Quoted CONTENT is never mistaken for a target, and '&>' is deliberately
    not named (declared uncovered):

    >>> extract_bash_write_targets_with_modes("echo 'foo > bar'")
    []
    >>> extract_bash_write_targets_with_modes('echo x &> /tmp/a')
    []
    """
    if not isinstance(command, str) or not command.strip():
        return []
    stripped = command_without_heredoc_bodies(command)
    stripped = _strip_reason_payload(stripped)
    found: List[WriteTarget] = []
    found.extend(_extract_redirect_mode_targets(stripped))
    found.extend(_extract_tee_mode_targets(stripped))
    found.extend(_extract_cp_mv_mode_targets(stripped))
    found.extend(_extract_install_mode_targets(stripped))
    found.extend(_extract_truncate_mode_targets(stripped))
    found.extend(_extract_dd_mode_targets(stripped))
    found.extend(_extract_curl_wget_mode_targets(stripped))
    found.extend(_extract_unlink_mode_targets(stripped))
    for path in _extract_sed_i_targets(stripped):
        found.append(WriteTarget(path, MODE_IN_PLACE_EDIT, "sed-in-place"))
    seen = set()
    deduped: List[WriteTarget] = []
    for t in found:
        if not t.path:
            continue
        key = (t.path, t.mode, t.mechanism)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(t)
    return deduped


if __name__ == "__main__":
    # Self-test entrypoint: run doctests when invoked directly.
    import doctest

    failures, _ = doctest.testmod(verbose=True)
    raise SystemExit(0 if failures == 0 else 1)
