#!/usr/bin/env python3
"""PreToolUse hook (Bash matcher): block catastrophic-backtracking text searches.

ROOT-CAUSE BACKGROUND (verified ground truth, 2026-06-15 host OOM)
------------------------------------------------------------------
Claude Code shadows `grep` with a shell FUNCTION that routes every grep through
the embedded engine inside the compiled binary:

    exec -a ugrep "$CLAUDE_CODE_EXECPATH" -G --ignore-files --hidden -I \
         --exclude-dir=.git ... "$@"

The embedded engine BACKTRACKS. A regex whose ERE form has two or more ADJACENT
variable-length gaps (`.{0,N}`, `.{N,}`, `.*`, `.+`) combined with top-level
alternation explodes on keyword-dense input — one such search grew to ~24 GiB
RSS and triggered a machine-wide OOM that took down the primary happy daemon.

The system grep at /usr/bin/grep uses a NON-backtracking (DFA/Thompson-NFA)
engine and handles the SAME pattern instantly with bounded memory (empirically
verified: 4.3 MiB RSS, <0.01 s). The embedded engine lives inside Anthropic's
compiled binary and cannot be patched or disabled by configuration — so the only
available control point is a PreToolUse speed-bump on the COMMAND.

DESIGN (hybrid: cheap static pre-filter, then a bounded empirical probe)
-----------------------------------------------------------------------
1. Inspect the Bash command. Find any text-search invocation:
     - `grep` / `egrep` / `fgrep` (the shadowed-grep FUNCTION form the agent runs)
     - a direct embedded-engine form: `exec -a ugrep <bin> ... PATTERN`
       or `ARGV0=ugrep <bin> ... PATTERN` or a bare `ugrep ... PATTERN`.
   For each, recover the SEARCH PATTERN and the regex MODE flag (-E / -G / -P).
   `fgrep` / `-F` (fixed strings) can never backtrack -> never flagged.

2. CHEAP STATIC PRE-FILTER on the pattern. Flag it ONLY when it has the
   catastrophic shape: two-or-more variable-length gaps that are ADJACENT
   (separated only by a short literal / a small alternation), with extra weight
   when top-level alternation is present. Literal strings, simple patterns, a
   single gap, and every non-search command are ALLOWED immediately with no
   probe and no measurable latency. Normal everyday grep is untouched.

3. BOUNDED EMPIRICAL PROBE (flagged commands only). Run the SAME pattern through
   the SAME embedded engine in the SAME regex mode the command uses, against a
   worst-case adversarial input, inside a transient systemd scope with a hard
   per-process RSS ceiling (~1.5 GiB) AND a short wall-clock limit (~5 s):
     - probe killed by the memory ceiling OR the time limit  -> REJECT (exit 2).
     - probe completes within both bounds                    -> ALLOW (exit 0).
   The ceiling bounds ONLY the probe subprocess (its own transient scope). It
   never touches happy daemons, sessions, or any long-running process.

4. FAIL OPEN. ANY internal error -> allow the command (exit 0). The guard never
   blocks legitimate work and never crashes the session.

Why a probe at all (vs. blocking on the static shape alone): catastrophic
backtracking is engine- and input-specific. The same shape that explodes in the
embedded ERE engine is handled instantly by other engines, and many
shape-matching patterns are in fact safe. Blocking on shape alone would
over-block legitimate complex regexes. The probe is the ground-truth oracle: it
asks the real engine, in a sandbox that cannot hurt the host.

Exit codes: 0 = allow, 2 = block (stderr shown to the agent). Fails OPEN.
"""

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

# --- tunables (kept as named constants; not hardcoded magic in logic) --------
def _int_env(name, default):
    """Parse an int env override, falling back to default on ANY bad value.

    Import-time parsing must never raise: a malformed override (e.g.
    GREPGUARD_PROBE_WALL_SECS=abc) would otherwise crash the module before
    main()'s fail-open envelope runs, taking down the Bash tool entirely.
    """
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return int(default)


PROBE_MEM_MAX = os.environ.get("GREPGUARD_PROBE_MEM_MAX", "1500M")  # ~1.5 GiB RSS ceiling
PROBE_MEM_HIGH = os.environ.get("GREPGUARD_PROBE_MEM_HIGH", "1400M")
PROBE_WALL_SECS = _int_env("GREPGUARD_PROBE_WALL_SECS", 5)
# A small outer margin so the guard itself never hangs if systemd-run misbehaves.
PROBE_OUTER_SECS = PROBE_WALL_SECS + 5

# argv[0] the shadowed-grep function uses to reach the embedded engine.
_UGREP_ARGV0 = "ugrep"


# ---------------------------------------------------------------------------
# Step 1: recover (pattern, mode) pairs from the command's search invocations.
# ---------------------------------------------------------------------------
def _strip_contexts(command):
    """Best-effort removal of non-executable contexts; reuse repo lib if present."""
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from lib.grepguard_context_strip import strip_non_executable_contexts
        return strip_non_executable_contexts(command)
    except Exception:
        return command


_ANSI_C_ESCAPES = {
    "n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f",
    "v": "\v", "\\": "\\", "'": "'", '"': '"', "?": "?", "e": "\x1b", "E": "\x1b",
}


def _decode_ansi_c_quotes(command):
    """Decode bash ANSI-C `$'...'` quoting OUTSIDE single quotes into a plain
    single-quoted token, so the guard's shape analysis sees the ACTUAL regex
    characters rather than the literal escape text (codex#5). E.g.
    `grep -E $'a.\\x7b0,40\\x7db' f` -> `grep -E 'a.{0,40}b' f`.

    Bounded, advancing, fail-open: on any oddity the original text is preserved.
    """
    if "$'" not in command:
        return command
    try:
        out = []
        sq = False
        i = 0
        n = len(command)
        while i < n:
            c = command[i]
            if sq:
                out.append(c)
                if c == "'":
                    sq = False
                i += 1
                continue
            if c == "'":
                sq = True
                out.append(c)
                i += 1
                continue
            if c == "$" and i + 1 < n and command[i + 1] == "'":
                # decode the $'...' span
                j = i + 2
                buf = []
                while j < n and command[j] != "'":
                    if command[j] == "\\" and j + 1 < n:
                        e = command[j + 1]
                        if e in _ANSI_C_ESCAPES:
                            buf.append(_ANSI_C_ESCAPES[e])
                            j += 2
                            continue
                        if e == "x":  # \xHH
                            h = command[j + 2:j + 4]
                            hexs = ""
                            for ch in h:
                                if ch in "0123456789abcdefABCDEF":
                                    hexs += ch
                                else:
                                    break
                            if hexs:
                                buf.append(chr(int(hexs, 16)))
                                j += 2 + len(hexs)
                                continue
                        if e in "01234567":  # \ooo octal
                            o = ""
                            k = j + 1
                            while k < n and len(o) < 3 and command[k] in "01234567":
                                o += command[k]
                                k += 1
                            buf.append(chr(int(o, 8) & 0xFF))
                            j = k
                            continue
                        # unknown escape: keep the escaped char literally
                        buf.append(e)
                        j += 2
                        continue
                    buf.append(command[j])
                    j += 1
                decoded = "".join(buf)
                # re-emit as a normal single-quoted token (escape embedded quotes)
                out.append("'" + decoded.replace("'", "'\\''") + "'")
                i = j + 1 if j < n else j
                continue
            out.append(c)
            i += 1
        return "".join(out)
    except Exception:
        return command


_SEP_TOKENS = {";", "|", "||", "&", "&&", "\n", "(", ")", "{", "}", "&|", ";;"}

# Bash reserved words / structural tokens that can sit in COMMAND position in
# front of a real command (compound commands, pipelines negation, etc.). They are
# TRANSPARENT: a grep that follows one still routes to the embedded function
# shadow, so we strip them and keep inspecting the inner command (OBJ-1).
_RESERVED_TRANSPARENT = {
    "if", "then", "else", "elif", "fi",
    "for", "while", "until", "do", "done",
    "case", "esac", "in", "select", "function",
    "{", "}", "(", ")", "!", "time", "coproc",
}


def _tokenize_segments(command):
    """Quote-AWARE split of a command into pipeline/sequence segments.

    CRITICAL: a search regex legitimately contains unquoted-looking `|`
    alternation INSIDE quotes (e.g. `grep -E 'a|b' f`). A naive character split on
    `|` shreds the pattern. So we tokenize with shlex first (which keeps a quoted
    pattern as ONE token and only yields a bare `|`/`;`/`&&` when it is a real
    unquoted shell operator), then group tokens into segments at operator tokens.

    Returns a list of token-lists, one per segment. On a shlex parse error
    (unbalanced quotes), returns [] so the caller fails open.
    """
    # Use posix shlex but keep operator chars as their own tokens by pre-spacing
    # ONLY unquoted operators. shlex itself does not split on |/;/& by default, so
    # we run it in a mode that yields them: punctuation_chars groups shell
    # operators into separate tokens while respecting quotes.
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        toks = list(lex)
    except ValueError:
        return []
    segments = []
    cur = []
    for t in toks:
        if t in _SEP_TOKENS:
            if cur:
                segments.append(cur)
                cur = []
            continue
        cur.append(t)
    if cur:
        segments.append(cur)
    return segments


# Flags (for grep/egrep/ugrep) that CONSUME a following value token, so the value
# is not mistaken for the pattern.
_VALUE_FLAGS = {
    "-e", "--regexp", "-f", "--file", "-m", "--max-count", "-A", "--after-context",
    "-B", "--before-context", "-C", "--context", "--color", "--colour",
    "-d", "--directories", "--exclude", "--exclude-dir", "--exclude-from",
    "--include", "--label", "--binary-files", "-D", "--devices", "--group-separator",
    "--jobs", "-J",
}


# Short option letters that CONSUME the rest of their cluster (or the next token)
# as a value: -e PAT, -f FILE, -m N, -A/-B/-C N, -d ACTION, -D ACTION. Once one of
# these appears in a short cluster, the REMAINDER of the token is its value, not
# more option letters — so `grep -Ee'PAT'` => -E then -e with value "'PAT'" (the
# shell already stripped the quotes => PAT). This is what GNU getopt does and is
# the basis for OBJ codex#6 (attached -e inside a cluster must be recovered).
_SHORT_VALUE_LETTERS = set("efmABCDd")


def _mode_from_flags(tokens):
    """Return regex mode: 'E' (ERE), 'G' (BRE), 'P' (PCRE), or 'F' (fixed).

    Mirrors how the command would actually run. egrep => E, fgrep => F. The LAST
    of -E/-G/-P/-F among the tokens wins (matches grep/ugrep behaviour). The
    shadowed-grep function injects a default -G, but a user -E/-P on the command
    overrides it (empirically: -E triggers the embedded-engine explosion).

    CRITICAL (codex#6): when a short cluster contains a value-consuming letter
    (e/f/m/...), STOP scanning at that letter — the rest of the token is the
    value (e.g. a PATTERN), and a stray 'E'/'F' INSIDE the pattern must NOT be
    read as a mode flag.
    """
    mode = "G"  # grep default is BRE; the shadow function also passes -G
    base = tokens[0].rsplit("/", 1)[-1] if tokens else ""
    if base == "egrep":
        mode = "E"
    elif base == "fgrep":
        mode = "F"
    for t in tokens[1:]:
        if t in ("-E", "--extended-regexp"):
            mode = "E"
        elif t in ("-G", "--basic-regexp"):
            mode = "G"
        elif t in ("-P", "--perl-regexp"):
            mode = "P"
        elif t in ("-F", "--fixed-strings"):
            mode = "F"
        elif t.startswith("-") and not t.startswith("--") and len(t) > 1:
            # short cluster like -riE : take the last engine letter present, but
            # stop at the first value-consuming letter (its tail is a value).
            for ch in t[1:]:
                if ch in _SHORT_VALUE_LETTERS:
                    break
                if ch == "E":
                    mode = "E"
                elif ch == "G":
                    mode = "G"
                elif ch == "P":
                    mode = "P"
                elif ch == "F":
                    mode = "F"
    return mode


def _extract_patterns(tokens):
    """Given a tokenized search invocation, return ALL search PATTERN strings.

    grep runs EVERY -e/--regexp pattern, so a non-first pattern can be the bomb
    (`grep -e safe -e BOMB`). We therefore return the FULL list of patterns the
    command would feed the engine — the caller probes each one and blocks if ANY
    is catastrophic (OBJ-2).

    Honours -e/--regexp / --regexp=... (explicit, repeatable), -f/--file
    (pattern from a file => cannot statically inspect => contributes nothing),
    value-consuming flags, the `--` separator, and otherwise the first non-flag
    positional ONLY when no explicit -e/--regexp pattern was given.
    """
    explicit = []
    positional = None
    i = 1
    n = len(tokens)
    saw_double_dash = False
    while i < n:
        t = tokens[i]
        if saw_double_dash:
            # first positional after -- is the pattern (only if no explicit -e)
            if positional is None:
                positional = t
            i += 1
            continue
        # attached long form: --regexp=PAT / --file=...
        if t.startswith("--regexp="):
            explicit.append(t.split("=", 1)[1])
            i += 1
            continue
        if t.startswith("--file=") or t == "-f" or t == "--file":
            # pattern read from a file: cannot statically inspect -> skip this one
            if t == "-f" or t == "--file":
                i += 2
            else:
                i += 1
            continue
        if t in ("-e", "--regexp"):
            if i + 1 < n:
                explicit.append(tokens[i + 1])
            i += 2
            continue
        # value-consuming LONG flags (and =attached form): skip flag AND its value.
        base = t.split("=", 1)[0]
        if t.startswith("--") and (t in _VALUE_FLAGS or base in _VALUE_FLAGS):
            if "=" in t:
                i += 1
            else:
                i += 2
            continue
        # SHORT option cluster (e.g. -niE, -Ee'PAT', -inef FILE). Walk letters
        # left-to-right; the FIRST value-consuming letter (e/f/m/A/B/C/d/D) takes
        # the REST of the token as its value, or the NEXT token if the cluster
        # ends at that letter. This recovers attached -e patterns hidden inside a
        # cluster like -Ee'BOMB' (codex#6) that the old startswith("-e") missed.
        if t.startswith("-") and not t.startswith("--") and len(t) > 1 and t != "-":
            consumed_next = False
            k = 1
            tk = t
            while k < len(tk):
                ch = tk[k]
                if ch in _SHORT_VALUE_LETTERS:
                    rest = tk[k + 1:]
                    if rest:  # value attached in the same token
                        if ch == "e":
                            explicit.append(rest)
                        # ch == 'f' => pattern-from-file: cannot inspect, skip.
                        # other value letters (m/A/B/C/d/D): value is not a pattern.
                    else:  # value is the NEXT token
                        if i + 1 < n:
                            if ch == "e":
                                explicit.append(tokens[i + 1])
                            consumed_next = True
                    break  # rest of token is a value, stop scanning letters
                k += 1
            i += 2 if consumed_next else 1
            continue
        # first bare positional = the pattern (only consulted if no explicit -e)
        if positional is None:
            positional = t
        i += 1
    # If any explicit -e/--regexp pattern was given, grep IGNORES the positional
    # operand (it becomes a file argument), so the patterns are exactly explicit.
    if explicit:
        return explicit
    if positional is not None:
        return [positional]
    return []


# Bound recursion into nested executable contexts (cmd-subst / eval bodies).
_MAX_DESCENT = 6


def _extract_backtick_bodies(command):
    """Return the inner command text of every backtick span `...`, including
    those NESTED inside double quotes (where backticks STILL execute — codex#2).

    The shlex tokenizer with punctuation_chars does NOT split backticks, so a
    `x=`grep BOMB`` form (and `echo "`grep BOMB`"`) hides the inner grep. We
    recover each backtick body so it can be re-scanned as its own command.
    Backticks inside SINGLE quotes are inert and are skipped.
    """
    bodies = []
    quote = None  # None | "'" (inert) | '"' (backticks active inside)
    i = 0
    n = len(command)
    while i < n:
        c = command[i]
        if quote == "'":
            # single-quoted: everything inert until the closing quote.
            if c == "'":
                quote = None
            i += 1
            continue
        if quote == '"':
            # double-quoted: backticks STILL execute; only \ before `, ", $, \,
            # newline is an escape. Fall through to backtick handling below.
            if c == "\\" and i + 1 < n and command[i + 1] in ('`', '"', '$', '\\', '\n'):
                i += 2
                continue
            if c == '"':
                quote = None
                i += 1
                continue
            # NOT returning/continuing here: let backtick check run below.
        elif c == "'":
            quote = "'"
            i += 1
            continue
        elif c == '"':
            quote = '"'
            i += 1
            continue
        elif c == "\\" and i + 1 < n:
            i += 2
            continue
        if c == "`":
            j = i + 1
            while j < n and command[j] != "`":
                if command[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                j += 1
            bodies.append(command[i + 1:j])
            i = j + 1
            continue
        i += 1
    return bodies


def _extract_dollar_paren_bodies(command):
    """Return the inner command text of every `$( ... )` command-substitution,
    including those NESTED inside double quotes (where $() is still active) and
    those the shlex segment-splitter would not expose (e.g. `"$(grep ...)"`).

    Single-quoted regions are inert in bash, so a `$(` inside single quotes is
    NOT a substitution and is skipped. Nested parens are balanced. Bounded,
    advancing scan; on any oddity it simply stops (fail-open: fewer descents).
    """
    bodies = []
    sq = False  # inside single quotes (substitutions inert)
    i = 0
    n = len(command)
    while i < n:
        c = command[i]
        if sq:
            if c == "'":
                sq = False
            i += 1
            continue
        if c == "'":
            sq = True
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            i += 2
            continue
        if c == "$" and i + 1 < n and command[i + 1] == "(":
            # Skip arithmetic $(( ... )) — not a command substitution.
            if i + 2 < n and command[i + 2] == "(":
                i += 3
                continue
            depth = 1
            j = i + 2
            inner_sq = False
            inner_dq = False
            while j < n and depth > 0:
                cj = command[j]
                if inner_sq:
                    if cj == "'":
                        inner_sq = False
                    j += 1
                    continue
                if inner_dq:
                    if cj == '"':
                        inner_dq = False
                    elif cj == "\\" and j + 1 < n:
                        j += 2
                        continue
                    j += 1
                    continue
                if cj == "'":
                    inner_sq = True
                elif cj == '"':
                    inner_dq = True
                elif cj == "\\" and j + 1 < n:
                    j += 2
                    continue
                elif cj == "(":
                    depth += 1
                elif cj == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            bodies.append(command[i + 2:j])
            i = j + 1
            continue
        i += 1
    return bodies


def _eval_args(toks):
    """If a segment is an `eval` invocation (possibly behind transparent prefixes
    `time`/`!`/structural reserved words, or `command eval` / `builtin eval`),
    return the eval ARGUMENT tokens; otherwise None. (codex#3)
    """
    i = 0
    n = len(toks)
    while i < n:
        b = toks[i].rsplit("/", 1)[-1]
        if b in _RESERVED_TRANSPARENT or b in _FUNCTION_PRESERVING_WRAPPERS:
            i += 1
            continue
        if b in ("command", "builtin"):
            # `command eval ...` / `builtin eval ...` still re-parse their arg.
            i += 1
            continue
        if b == "eval":
            return toks[i + 1:] if i + 1 < n else []
        return None
    return None


_SHELL_INTERP_NAMES = {"bash", "sh", "zsh", "dash", "ksh"}


def _shell_c_script(toks):
    """If a segment invokes a function-inheriting shell interpreter with `-c`
    (`bash -c "<script>"`, possibly behind transparent prefixes/`command`), return
    the script string; otherwise None (codex#4). The interpreter re-parses the
    script and inherits the grep function shadow, so the inner grep must be
    re-scanned. Only the bare/`command`-form interpreter routes the shadow; a
    PATH-qualified `/bin/bash` is a fresh shell that does NOT inherit the
    (non-exported) function, so we do not descend into it (would be a false
    positive and the inner grep there hits system grep)."""
    i = 0
    n = len(toks)
    while i < n:
        b = toks[i].rsplit("/", 1)[-1]
        if b in _RESERVED_TRANSPARENT or b in _FUNCTION_PRESERVING_WRAPPERS \
                or b in ("command", "builtin"):
            i += 1
            continue
        # Only a BARE interpreter name (no '/') inherits the shell function shadow.
        if b in _SHELL_INTERP_NAMES and "/" not in toks[i]:
            j = i + 1
            while j < n:
                a = toks[j]
                if a == "-c":
                    return toks[j + 1] if j + 1 < n else None
                if a.startswith("-") and "c" in a[1:] and not a.startswith("--"):
                    # clustered like -xc : the -c arg is the next token
                    return toks[j + 1] if j + 1 < n else None
                if a.startswith("-"):
                    j += 1
                    continue
                break  # first non-option = script FILE, not a -c string
            return None
        return None
    return None


def _extract_process_substitution_bodies(command):
    """Return the inner command text of every `<( ... )` / `>( ... )` process
    substitution (codex#1). bash runs the inner command, so a grep there reaches
    the embedded engine. Single-quoted regions are inert; nested parens balanced.
    """
    bodies = []
    sq = False
    i = 0
    n = len(command)
    while i < n:
        c = command[i]
        if sq:
            if c == "'":
                sq = False
            i += 1
            continue
        if c == "'":
            sq = True
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            i += 2
            continue
        if c in ("<", ">") and i + 1 < n and command[i + 1] == "(":
            depth = 1
            j = i + 2
            inner_sq = False
            inner_dq = False
            while j < n and depth > 0:
                cj = command[j]
                if inner_sq:
                    if cj == "'":
                        inner_sq = False
                    j += 1
                    continue
                if inner_dq:
                    if cj == '"':
                        inner_dq = False
                    elif cj == "\\" and j + 1 < n:
                        j += 2
                        continue
                    j += 1
                    continue
                if cj == "'":
                    inner_sq = True
                elif cj == '"':
                    inner_dq = True
                elif cj == "\\" and j + 1 < n:
                    j += 2
                    continue
                elif cj == "(":
                    depth += 1
                elif cj == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            bodies.append(command[i + 2:j])
            i = j + 1
            continue
        i += 1
    return bodies


def _find_searches(command, _depth=0):
    """Return a list of (pattern, mode) for every text-search in the command.

    Recognises top-level AND nested forms (OBJ-1):
      - the shadowed-grep FUNCTION form: grep/egrep/fgrep ... PATTERN
      - the direct embedded-engine forms:
          exec -a ugrep <bin> ... PATTERN / ARGV0=ugrep <bin> ... / ugrep ...
      - grep nested inside command-substitution $( ), backticks ` `, eval STRING,
        subshell ( ), brace group { }, and compound commands (if/then, loops):
        the embedded function shadow is inherited into ALL of these, so a bomb in
        any of them reaches the embedded engine and MUST be guarded.

    `_depth` bounds recursion into nested command text so a pathological input
    cannot cause unbounded work (fail-open via bound, not via crash).
    """
    found = []
    # Decode ANSI-C $'...' quoting FIRST (codex#5) so shape analysis sees the real
    # regex metacharacters, then strip non-executable contexts (heredoc data).
    cmd = _strip_contexts(_decode_ansi_c_quotes(command))

    # Descend into BACKTICK, $( ) command-substitution, and <( )/>( ) process-
    # substitution bodies (incl. those nested inside double quotes, which shlex
    # would hide). Each body is itself a command list, re-scanned recursively
    # (OBJ-1 cmd-subst / backtick / process-subst forms — codex#1, codex#2).
    # NOTE (codex#10): the depth gate stops only FURTHER recursion; the CURRENT
    # command level is ALWAYS scanned below, so a direct grep is never skipped by
    # the bound — the bound only prevents unbounded descent into nested bodies.
    if _depth < _MAX_DESCENT:
        for body in _extract_backtick_bodies(cmd):
            if body.strip():
                found.extend(_find_searches(body, _depth + 1))
        for body in _extract_dollar_paren_bodies(cmd):
            if body.strip():
                found.extend(_find_searches(body, _depth + 1))
        for body in _extract_process_substitution_bodies(cmd):
            if body.strip():
                found.extend(_find_searches(body, _depth + 1))

    # An unquoted newline is a command separator in bash, but shlex with
    # whitespace_split=True swallows it as ordinary whitespace, fusing a later
    # `grep` into a preceding segment and HIDING it. Pre-split the raw command on
    # newlines (outside quotes) so each line is tokenized as its own command list.
    for line in _split_unquoted_newlines(cmd):
        for toks in _tokenize_segments(line):
            if not toks:
                continue
            # `eval STRING` (and `eval tok tok ...`): the argument(s) are a command
            # that bash re-parses and runs, so a grep inside reaches the embedded
            # engine. Re-scan the eval body recursively (OBJ-1 eval form). The eval
            # may sit behind transparent prefixes (`time`, `!`, reserved words) or
            # `command`/`builtin` (`command eval "..."`) — strip those first so the
            # eval is still recognised (codex#3).
            eval_args = _eval_args(toks)
            if eval_args and _depth < _MAX_DESCENT:
                # bash `eval` concatenates its arguments with spaces and re-parses
                # the result as a command. Two shapes occur:
                #   eval "grep -niE 'PAT' f"  -> ONE token that IS a command string
                #                                (single-quotes inside survived).
                #   eval grep -niE 'PAT' f    -> MANY tokens whose quotes the OUTER
                #                                shell already stripped.
                # We re-scan EACH argument token as its own command string (covers
                # the single-token quoted-string form), AND re-scan the tokens
                # re-quoted-and-joined (covers the multi-token form, preserving the
                # pattern's regex metacharacters through re-tokenization). Both are
                # cheap; over-scanning only ever adds detections, never removes one.
                for t in eval_args:
                    if t.strip():
                        found.extend(_find_searches(t, _depth + 1))
                eval_body = " ".join(shlex.quote(t) for t in eval_args)
                found.extend(_find_searches(eval_body, _depth + 1))
                # fall through: the eval token itself is not a grep, nothing else
                # in this segment to inspect.
                continue
            # `bash -c "<script>"` / `sh -c ...`: the script string is re-parsed by
            # an interpreter that INHERITS the grep function shadow, so a grep
            # inside reaches the embedded engine (codex#4). Re-scan the -c arg.
            sh_script = _shell_c_script(toks)
            if sh_script is not None and _depth < _MAX_DESCENT:
                if sh_script.strip():
                    found.extend(_find_searches(sh_script, _depth + 1))
                continue
            # Normalise leading env-assignments / wrappers / launchers / structural
            # reserved words. Returns [] for forms that BYPASS the embedded engine
            # (path-form grep, external exec wrappers, command/builtin grep).
            toks = _normalise_search_tokens(toks)
            if not toks:
                continue
            base = toks[0].rsplit("/", 1)[-1]
            if base in ("grep", "egrep", "fgrep", _UGREP_ARGV0):
                mode = _mode_from_flags(toks)
                if mode == "F":
                    continue  # fixed strings never backtrack
                for pat in _extract_patterns(toks):
                    if pat:
                        found.append((pat, mode))
    return found


def _split_unquoted_newlines(command):
    """Split a command on newlines that are NOT inside single/double quotes.

    A bare newline separates commands in bash exactly like `;`. shlex's
    whitespace_split mode treats it as plain whitespace, so without this split a
    `grep` after a newline-separated command would be fused into the prior segment
    and never seen. Quotes are respected so a newline inside a quoted pattern is
    preserved. On any error, returns [command] (single line) so we fail safe.
    """
    try:
        out = []
        cur = []
        quote = None
        i = 0
        n = len(command)
        while i < n:
            c = command[i]
            if quote:
                cur.append(c)
                if c == quote:
                    quote = None
                elif c == "\\" and quote == '"' and i + 1 < n:
                    cur.append(command[i + 1])
                    i += 2
                    continue
            elif c in ("'", '"'):
                quote = c
                cur.append(c)
            elif c == "\\" and i + 1 < n:
                # escaped char (incl. an escaped newline = line continuation):
                # keep both so shlex sees the original token.
                cur.append(c)
                cur.append(command[i + 1])
                i += 2
                continue
            elif c == "\n":
                out.append("".join(cur))
                cur = []
            else:
                cur.append(c)
            i += 1
        out.append("".join(cur))
        return out
    except Exception:
        return [command]


# Function-PRESERVING wrappers: these are shell keywords/builtins that run their
# argument through normal command resolution, so a following `grep` STILL hits the
# function shadow -> embedded engine -> must be GUARDED. We strip them and keep
# inspecting the inner command. (`time` is a bash keyword; verified empirically
# that `time grep ...` still invokes the grep FUNCTION.)
_FUNCTION_PRESERVING_WRAPPERS = {"time"}

# Function-BYPASSING wrappers: external exec wrappers (or builtins that skip
# function lookup). They exec the named binary directly via PATH, bypassing the
# shell `grep` function -> a following `grep` runs the SYSTEM grep (safe DFA
# engine) -> EXEMPT. Verified empirically (`env grep`, `nice grep`, `xargs grep`
# bypass the function; `command`/`builtin` skip function lookup by definition).
_FUNCTION_BYPASSING_WRAPPERS = {"sudo", "doas", "env", "nohup", "setsid", "stdbuf",
                                "ionice", "nice", "xargs", "command", "builtin"}


def _normalise_search_tokens(toks):
    """Strip leading env-assignments / wrappers and the embedded-engine launchers,
    returning a token list whose toks[0] is the search command name (grep/ugrep),
    or [] when the invocation does NOT reach the embedded engine (so the caller
    EXEMPTS it).

    CRITICAL — engine routing. Only forms that reach the EMBEDDED engine are
    returned for guarding:
      - a BARE `grep`/`egrep`/`fgrep` name (incl. a backslash-escaped `\\grep`,
        which posix shlex already reduced to the bare name): backslash suppresses
        ALIAS expansion but NOT function lookup, so `\\grep` STILL hits the shell
        function shadow -> embedded engine -> GUARDED. (verified empirically)
      - explicit `ugrep` / `\\ugrep`: directly names the embedded engine binary.
      - `time grep ...`: `time` is a shell keyword that preserves the function.
      - the ARGV0=ugrep / exec -a ugrep launchers.

    Forms that BYPASS the function shadow and reach the SYSTEM grep (safe,
    non-backtracking) return [] -> EXEMPT:
      - a PATH form (`/usr/bin/grep`, `./grep`): name contains '/', a real binary.
      - external exec wrappers (`env`/`nice`/`xargs`/`sudo`/... grep): exec the
        PATH binary directly, bypassing the function.
      - `command grep` / `builtin grep`: bash skips function lookup.
    """
    i = 0
    n = len(toks)
    saw_argv0_ugrep = False
    while i < n:
        t = toks[i]
        # Structural / reserved-word tokens in command position are TRANSPARENT:
        # the grep that follows them STILL hits the function shadow (OBJ-1). Strip
        # them and keep scanning. `time` stays in the preserving-wrapper set below
        # but is also listed here harmlessly.
        if t in _RESERVED_TRANSPARENT:
            i += 1
            continue
        # ARGV0=ugrep / ARGV0=/path/ugrep
        m = re.match(r"^[A-Za-z_][A-Za-z0-9_]*=(.*)$", t)
        if m:
            if t.split("=", 1)[0] == "ARGV0" and m.group(1).rsplit("/", 1)[-1] == _UGREP_ARGV0:
                saw_argv0_ugrep = True
            i += 1
            continue
        b = t.rsplit("/", 1)[-1]
        if b == "exec":
            # exec -a NAME <bin> ...   (NAME may be ugrep)
            j = i + 1
            execname = None
            while j < n and toks[j].startswith("-"):
                if toks[j] == "-a" and j + 1 < n:
                    execname = toks[j + 1]
                    j += 2
                    continue
                j += 1
            if execname and execname.rsplit("/", 1)[-1] == _UGREP_ARGV0:
                # the next token is the binary; synthesise a ugrep invocation
                if j < n:
                    return [_UGREP_ARGV0] + toks[j + 1:]
            # `exec` REPLACES the shell with the named binary via PATH, bypassing
            # the grep function shadow. So `exec grep ...` / `exec -a foo grep ...`
            # runs the SYSTEM grep (safe DFA engine) -> EXEMPT (codex#11). Only the
            # explicit `exec -a ugrep <bin>` form (handled above) reaches the
            # embedded engine.
            tgt = toks[j].rsplit("/", 1)[-1] if j < n else ""
            if tgt in ("grep", "egrep", "fgrep"):
                return []
            i = j
            continue
        # External exec wrappers (and command/builtin) bypass the function shadow:
        # a following bare grep runs the SYSTEM grep -> EXEMPT the whole segment.
        # (An inner explicit `ugrep` is still the embedded engine, so keep scanning
        #  for that rather than blanket-exempting.)
        if b in _FUNCTION_BYPASSING_WRAPPERS:
            # Find the wrapper's REAL command by skipping the wrapper's own
            # arguments. For `env` (and similar) that means skipping VAR=val
            # assignments and `-`/`-i`/`-u NAME`/`--`-style env options, so
            # `env FOO=1 grep ...` correctly resolves to the system grep (OBJ-4).
            j = i + 1
            while j < n:
                w = toks[j]
                # leading VAR=val assignment consumed by env/the shell wrapper
                if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w):
                    j += 1
                    continue
                if w == "--":
                    j += 1
                    break
                if w == "-" or w in ("-i", "--ignore-environment", "-0", "--null",
                                     "-v", "--debug"):
                    j += 1
                    continue
                if w in ("-u", "--unset", "-C", "--chdir", "-S", "--split-string"):
                    j += 2  # option takes a value
                    continue
                if w.startswith("-") and len(w) > 1:
                    j += 1  # unknown wrapper option, skip conservatively
                    continue
                break
            nxt = toks[j] if j < n else ""
            nxt_base = nxt.rsplit("/", 1)[-1]
            if nxt_base in ("grep", "egrep", "fgrep"):
                return []  # system grep -> not the embedded engine -> exempt
            i += 1
            continue
        # Function-preserving wrappers (`time`) keep the shell function in play, so
        # the inner grep STILL routes to the embedded engine -> keep scanning.
        if b in _FUNCTION_PRESERVING_WRAPPERS:
            i += 1
            continue
        # First real command token.
        if saw_argv0_ugrep:
            # ARGV0=ugrep <bin> ...  -> treat as ugrep invocation (drop the bin)
            return [_UGREP_ARGV0] + toks[i + 1:]
        # A PATH-qualified grep (name contains '/') is the real system binary, not
        # the function shadow -> safe DFA engine -> EXEMPT. The embedded engine is
        # only reached via a BARE `grep`/`egrep` name (or explicit `ugrep`).
        if "/" in t and b in ("grep", "egrep", "fgrep"):
            return []  # /usr/bin/grep, ./grep, etc. -> exempt
        return toks[i:]
    return []


# ---------------------------------------------------------------------------
# Step 2: cheap static pre-filter — catastrophic-backtracking SHAPE detection.
# ---------------------------------------------------------------------------
# A "variable-length gap" token in ERE/PCRE shape:
#   .*  .+  .{0,N}  .{N,}  .{N,M}  (and the lazy ?-suffixed forms)
# We also count generic `X*` / `X+` / `X{n,}` greedy quantifiers that can span.
_GAP_RE = re.compile(
    r"""
    (?:
        \. (?: \* | \+ | \{ \s*\d* \s*,\s*\d* \s*\} )   # .*  .+  .{n,m}
      | \[ [^\]]* \] (?: \* | \+ | \{ \s*\d* \s*,\s*\d* \s*\} )  # [..]* etc
      | \\w (?: \* | \+ | \{ \s*\d* \s*,\s*\d* \s*\} )  # \w* etc
    )
    \??                                                 # optional lazy modifier
    """,
    re.VERBOSE,
)


def _has_top_level_alternation(pattern):
    """True if an unescaped, top-level (depth-0) `|` exists in the pattern."""
    depth = 0
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "\\":
            i += 2
            continue
        if c == "[":
            # skip a character class
            j = i + 1
            if j < n and pattern[j] == "^":
                j += 1
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                if pattern[j] == "\\":
                    j += 1
                j += 1
            i = j + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth = max(0, depth - 1)
        elif c == "|" and depth == 0:
            return True
        i += 1
    return False


def is_catastrophic_shape(pattern, mode):
    """Cheap static pre-filter. Return True ONLY for the catastrophic shape:
    two or more variable-length gaps that are ADJACENT (the spans between them
    are short — a small literal / small group), i.e. the classic
    `X.{0,N}Y.{0,N}Z` adjacency that drives the embedded engine's backtracking.

    Single-gap patterns, fixed strings, and short simple patterns return False.
    Top-level alternation raises the catastrophic risk but is not required on its
    own.
    """
    if not pattern:
        return False
    # In BRE (-G) the {,},(,),| metacharacters are literals unless escaped, so the
    # ADJACENT-gap explosion (which needs interval/alternation operators) does not
    # arise from these tokens. We normalise BRE escaped operators to their ERE
    # meaning for shape analysis so an escaped-BRE catastrophic pattern is caught.
    pat = pattern
    if mode == "G":
        pat = (pat.replace(r"\{", "{").replace(r"\}", "}")
                  .replace(r"\(", "(").replace(r"\)", ")")
                  .replace(r"\|", "|").replace(r"\+", "+"))

    gaps = list(_GAP_RE.finditer(pat))
    if len(gaps) < 2:
        return False

    # Require ADJACENCY: at least one pair of gaps separated by a SHORT span.
    # "short" = the literal/group text between two gaps is small (<= 24 chars),
    # which is the dangerous `X.{0,N}Y.{0,N}Z` adjacency. Two gaps far apart in an
    # otherwise long pattern are far less explosive.
    ADJ_MAX = 24
    adjacent = False
    for a, b in zip(gaps, gaps[1:]):
        between = pat[a.end():b.start()]
        if len(between) <= ADJ_MAX:
            adjacent = True
            break
    if not adjacent:
        return False

    # Adjacency alone qualifies. Top-level alternation (multiple branches each
    # carrying adjacent gaps) is the worst case and definitely qualifies.
    return True


# ---------------------------------------------------------------------------
# Step 3: bounded empirical probe through the SAME embedded engine.
# ---------------------------------------------------------------------------
def _embedded_bin():
    """Path to the embedded-engine binary the shadowed-grep function uses."""
    p = os.environ.get("CLAUDE_CODE_EXECPATH", "")
    if p and os.path.exists(p):
        return p
    for cand in (
        "/usr/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe",
        "/root/.local/bin/claude",
    ):
        if os.path.exists(cand):
            return cand
    return None


def _worst_case_input(path):
    """Write a worst-case, keyword-dense adversarial input to `path`.

    The input is engineered to maximise partial-match start positions for an
    arbitrary catastrophic pattern: many repeats of common English connective and
    keyword tokens, so the gaps have lots of fillable text and the alternation
    branches keep partially matching and backtracking. This is independent of
    whatever file the agent intended to search — the probe asks "does THIS pattern
    explode in THIS engine on dense text", which is the property that caused the
    host OOM.
    """
    words = [
        "do", "not", "never", "cannot", "dont", "cant", "privilege", "kernel",
        "guard", "always-on", "even", "/do", "commit", "push", "the", "to",
        "with", "you", "and", "or", "a", "is", "are", "of", "in", "on",
    ]
    chunk = " ".join(words)
    line = (chunk + " ") * 12
    with open(path, "w") as f:
        for _ in range(500):
            f.write(line + "\n")


def _mode_flag(mode):
    return {"E": "-E", "G": "-G", "P": "-P"}.get(mode, "-G")


def probe_explodes(pattern, mode):
    """Run the pattern through the embedded engine inside a transient systemd
    scope with a hard RSS ceiling and a wall-clock limit.

    Returns True  if the probe was terminated by the memory ceiling or the time
                  limit (=> catastrophic; REJECT the original command).
    Returns False if the probe completed within both bounds (=> ALLOW).
    Raises on any infrastructure problem so the caller can FAIL OPEN.
    """
    binpath = _embedded_bin()
    if not binpath:
        raise RuntimeError("embedded engine binary not found")
    if not (os.path.exists("/usr/bin/systemd-run") or _which("systemd-run")):
        raise RuntimeError("systemd-run unavailable")

    tmpdir = tempfile.mkdtemp(prefix="grepguard-probe-")
    infile = os.path.join(tmpdir, "dense.txt")
    try:
        _worst_case_input(infile)
        # Inner command drives the SAME embedded engine the agent's grep would,
        # via argv[0]=ugrep and the matching mode flag, against the dense input.
        inner = "exec -a {a} {b} {m} {p} {f}".format(
            a=shlex.quote(_UGREP_ARGV0),
            b=shlex.quote(binpath),
            m=_mode_flag(mode),
            p=shlex.quote(pattern),
            f=shlex.quote(infile),
        )
        scope_unit = "grepguard-probe-{}".format(os.getpid())
        argv = [
            "systemd-run", "--scope", "-q",
            "-p", "MemoryMax={}".format(PROBE_MEM_MAX),
            "-p", "MemorySwapMax=0",
            "-p", "MemoryHigh={}".format(PROBE_MEM_HIGH),
            "--slice", "grepguard-probe.slice",
            "--unit", scope_unit,
            "timeout", str(PROBE_WALL_SECS),
            "env", "-", "bash", "-c", inner,
        ]
        try:
            cp = subprocess.run(
                argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=PROBE_OUTER_SECS,
            )
            rc = cp.returncode
        except subprocess.TimeoutExpired:
            # Outer guard tripped: the probe itself ran past even the outer
            # margin => treat as catastrophic (it could not finish in time).
            return True
        # rc semantics:
        #   0   -> a match was found, completed fast            => safe (ALLOW)
        #   1   -> no match, completed fast                     => safe (ALLOW)
        #   124 -> `timeout` killed it at the wall limit        => EXPLODED
        #   137 -> SIGKILL: OOM ceiling (or timeout -s KILL)    => EXPLODED
        #   125/126/127 -> systemd-run/launch failure           => infra error
        if rc in (124, 137):
            return True
        if rc in (0, 1):
            return False
        if rc in (125, 126, 127):
            raise RuntimeError("probe launch failure rc={}".format(rc))
        # Any other nonzero: be conservative but do not over-block — the engine
        # returned a real (non-kill) exit, so it did not explode.
        return False
    finally:
        try:
            os.remove(infile)
        except Exception:
            pass
        try:
            os.rmdir(tmpdir)
        except Exception:
            pass


def _which(name):
    for d in os.environ.get("PATH", "").split(os.pathsep):
        cand = os.path.join(d, name)
        if os.path.exists(cand) and os.access(cand, os.X_OK):
            return cand
    return None


# ---------------------------------------------------------------------------
# Blocking message.
# ---------------------------------------------------------------------------
def _block(pattern, data):
    lines = [
        "",
        "BLOCKED: this text-search regex catastrophically BACKTRACKS in Claude "
        "Code's embedded grep engine.",
        "A bounded sandbox probe (1.5 GiB ceiling, {}s wall) confirmed the SAME "
        "pattern in the SAME engine either ran out of memory or out of time."
        .format(PROBE_WALL_SECS),
        "On 2026-06-15 a search of this class grew to ~24 GiB and triggered a "
        "host-wide OOM that took down the happy daemon.",
        "",
        "Pattern (excerpt): {}".format((pattern or "")[:200]),
        "",
        "FIX — pick one:",
        "  1. Simplify the regex: avoid two-or-more adjacent variable-length "
        "gaps (.{0,N} / .* / .+) combined with alternation.",
        "  2. Use the system grep, which uses a non-backtracking engine and is "
        "immune to this:  /usr/bin/grep -E '<pattern>' <files>",
    ]
    if data.get("agent_id"):
        lines.append(
            "  You are a subagent: PAUSE and report this block to the user per "
            "Subagent Hook Discipline — do NOT attempt to work around it.")
    sys.stderr.write("\n".join(lines) + "\n")
    sys.exit(2)


# ---------------------------------------------------------------------------
# Main.
# ---------------------------------------------------------------------------
def main():
    # Outermost fail-open shell: ANY error => allow.
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        if data.get("tool_name", "") != "Bash":
            sys.exit(0)
        command = (data.get("tool_input", {}) or {}).get("command", "") or ""
        if not command.strip():
            sys.exit(0)

        # Test seam: allow self-test to force an internal error and prove fail-open.
        if os.environ.get("GREPGUARD_FORCE_ERROR") == "1":
            raise RuntimeError("forced internal error (fail-open self-test)")

        searches = _find_searches(command)
        if not searches:
            sys.exit(0)  # no text search -> nothing to do

        for pattern, mode in searches:
            # Step 2: cheap static pre-filter.
            if not is_catastrophic_shape(pattern, mode):
                continue  # safe shape -> no probe, negligible overhead
            # Step 3: bounded empirical probe (only for flagged patterns).
            try:
                exploded = probe_explodes(pattern, mode)
            except Exception:
                # Probe infrastructure error -> FAIL OPEN for this pattern.
                continue
            if exploded:
                _block(pattern, data)
        sys.exit(0)
    except SystemExit:
        raise
    except Exception:
        # FAIL OPEN on any unexpected error.
        sys.exit(0)


if __name__ == "__main__":
    main()
