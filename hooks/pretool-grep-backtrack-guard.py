#!/usr/bin/env python3
"""PreToolUse hook (Bash matcher): block catastrophic-backtracking text searches.

Why
---
Claude Code shadows `grep` with a shell FUNCTION that routes every grep through
the embedded engine inside the compiled binary:

    exec -a ugrep "$CLAUDE_CODE_EXECPATH" -G --ignore-files --hidden -I \
         --exclude-dir=.git ... "$@"

The embedded engine BACKTRACKS. A regex whose ERE form has two or more ADJACENT
variable-length gaps (`.{0,N}`, `.{N,}`, `.*`, `.+`) combined with top-level
alternation explodes on keyword-dense input: one such search grew to ~24 GiB
RSS and took the host down with an out-of-memory kill.

The system grep at /usr/bin/grep uses a NON-backtracking (DFA/Thompson-NFA)
engine and handles the SAME pattern instantly with bounded memory. The embedded
engine lives inside the compiled binary and cannot be patched or disabled by
configuration, so the only available control point is a PreToolUse speed-bump
on the COMMAND.

Design (cheap static pre-filter, then a bounded empirical probe)
---------------------------------------------------------------
1. Read the Bash command with the shared parser (lib/shell_parse.py) and find
   every text search that reaches the embedded engine:
     - `grep` / `egrep` / `fgrep` by bare name (the shadowed FUNCTION form),
       anywhere the function is inherited: substitutions, compound commands,
       `eval`, a bare `bash -c` payload, a shell fed a heredoc;
     - a direct embedded-engine form: `exec -a ugrep <bin> ... PATTERN`,
       `ARGV0=ugrep <bin> ... PATTERN`, or `ugrep ... PATTERN`.
   For each, recover the SEARCH PATTERN(s) and the regex MODE flag (-E / -G /
   -P). `fgrep` / `-F` (fixed strings) can never backtrack and is never flagged.
   A command the parser cannot read is let through, as every other internal
   failure is.

2. CHEAP STATIC PRE-FILTER on the pattern. Flag it ONLY when it has the
   catastrophic shape: two-or-more variable-length gaps that are ADJACENT
   (separated only by a short literal / a small alternation). Everything else is
   ALLOWED immediately with no probe and no measurable latency.

3. BOUNDED EMPIRICAL PROBE (flagged patterns only). Run the SAME pattern through
   the SAME embedded engine in the SAME regex mode, against a worst-case
   adversarial input, inside a transient systemd scope with a hard per-process
   RSS ceiling (~1.5 GiB) AND a short wall-clock limit (~5 s):
     - probe killed by the memory ceiling OR the time limit  -> REJECT (exit 2).
     - probe completes within both bounds                    -> ALLOW (exit 0).
   The ceiling bounds ONLY the probe subprocess (its own transient scope).
   Inside the scope the probe first writes a start marker into its own fresh
   private directory, and runs the engine only once that write succeeded. When
   the guard's outer margin runs out, the marker tells the two cases apart:
     - no marker: the scope never came up (e.g. a delayed systemd-run launch)
       -> an infrastructure failure, FAIL OPEN;
     - marker present (whatever it holds): the probe started and then hung
       (e.g. throttled at MemoryHigh)                        -> REJECT.

4. FAIL OPEN. ANY internal error -> allow the command (exit 0).

Why a probe at all (vs. blocking on the static shape alone): catastrophic
backtracking is engine- and input-specific; many shape-matching patterns are in
fact safe. The probe asks the real engine, in a sandbox that cannot hurt the host.

Exit codes: 0 = allow, 2 = block (stderr shown to the agent). Fails OPEN.
"""
import os, sys  # noqa: E401 -- the harness switch (hooks/lib/harness_switch.py): no harness hook runs while /harness off holds
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))
try:  # a hook copied without its lib/ (an old install) is on
    import harness_switch  # noqa: E402
    harness_switch.exit_if_off()
except ImportError:
    pass
finally:
    sys.path.pop(0)

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))
try:
    import shell_parse  # noqa: E402
finally:
    sys.path.pop(0)

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
_SEARCH_NAMES = ("grep", "egrep", "fgrep")

# Wrappers that keep the shell function in play: a search behind them still
# reaches the embedded engine. Every other wrapper execs the named binary through
# PATH (or, as `command`/`builtin`, skips function lookup), so a bare grep behind
# it runs the SYSTEM grep; an explicit `ugrep` behind one is still guarded.
_FUNCTION_PRESERVING_WRAPPERS = {"time"}

# A shell started by bare name inherits the function shadow; one started by path
# does not, and the search inside it runs the system grep.
_SHELL_INTERP_NAMES = {"bash", "sh", "zsh", "dash", "ksh"}

# Only `command`/`builtin` may stand between `eval` or a shell and the payload it runs.
_PAYLOAD_WRAPPERS = {"command", "builtin"}

# Nested code walked as the same shell: substitution bodies.
_SUBSTITUTIONS = ("cmdsub", "backtick", "procsub")

# Word parts read as written: an unmatched glob or brace stays literal.
_LITERAL_PARTS = ("lit", "glob", "brace")

# Bound on descents into code a command hands to a shell (`eval`, `-c`, heredoc).
_MAX_DESCENT = 6

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
# more option letters — so `grep -Ee'PAT'` => -E then -e with value PAT. This is
# what GNU getopt does, and it recovers an -e pattern attached inside a cluster.
_SHORT_VALUE_LETTERS = set("efmABCDd")


def _mode_from_flags(tokens):
    """Return regex mode: 'E' (ERE), 'G' (BRE), 'P' (PCRE), or 'F' (fixed).

    Mirrors how the command would actually run. egrep => E, fgrep => F. The LAST
    of -E/-G/-P/-F among the tokens wins (matches grep/ugrep behaviour). The
    shadowed-grep function injects a default -G, but a user -E/-P on the command
    overrides it (empirically: -E triggers the embedded-engine explosion).

    CRITICAL: when a short cluster contains a value-consuming letter
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
    is catastrophic.

    Honours -e/--regexp / --regexp=... (explicit, repeatable), -f/--file
    (pattern from a file => cannot statically inspect => contributes nothing),
    value-consuming flags, the `--` that ends the options, and otherwise the
    first operand ONLY when no -e/--regexp/-f/--file pattern source was given.
    """
    explicit = []
    from_file = False
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
        if t == "--":  # ends the options: the next operand is the pattern
            saw_double_dash = True
            i += 1
            continue
        # attached long form: --regexp=PAT / --file=...
        if t.startswith("--regexp="):
            explicit.append(t.split("=", 1)[1])
            i += 1
            continue
        if t.startswith("--file=") or t == "-f" or t == "--file":
            # pattern read from a file: cannot statically inspect -> skip this one
            from_file = True
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
        # cluster like -Ee'BOMB'.
        if t.startswith("-") and not t.startswith("--") and len(t) > 1 and t != "-":
            consumed_next = False
            k = 1
            tk = t
            while k < len(tk):
                ch = tk[k]
                if ch in _SHORT_VALUE_LETTERS:
                    rest = tk[k + 1:]
                    if ch == "f":
                        from_file = True
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
    # If any -e/--regexp or -f/--file pattern source was given, grep IGNORES the
    # positional operand (it becomes a file argument), so the patterns are exactly
    # the explicit ones.
    if explicit or from_file:
        return explicit
    if positional is not None:
        return [positional]
    return []


def _text(word):
    """A word's value as the shell passes it when no file matches its globs, with
    each computed part kept as written in the command."""
    offs = [word.raw.off(i) for i in range(len(word.raw))]
    out = []
    for p in word.parts:
        if p.kind in _LITERAL_PARTS:
            out.append(p.text)
            continue
        a = offs.index(p.span[0]) if p.span[0] in offs else None
        b = offs.index(p.span[1]) if p.span[1] in offs else len(word.raw.text)
        out.append(word.raw.text[a:b] if a is not None else "$" + p.text)
    return "".join(out)


def _search_argv(cmd):
    """The argv of the search a simple command runs on the embedded engine, with
    argv[0] the search name, or None when it runs no such search."""
    r = shell_parse.resolve(cmd)
    if r.head is None or r.head.value() is None:
        return None
    head = r.head.value()
    name = shell_parse.basename(head)
    args = [_text(w) for w in r.args]
    wrappers = [w[0] for w in r.wrappers]
    if name in _SEARCH_NAMES and ("/" in head or any(w not in _FUNCTION_PRESERVING_WRAPPERS
                                                      for w in wrappers)):
        return None
    for wname, opts in r.wrappers:
        if wname == "exec" and any(o == "-a" and v is not None
                                   and shell_parse.basename(_text(v)) == _UGREP_ARGV0
                                   for o, v in opts):
            return [_UGREP_ARGV0] + args
    for a in r.assignments:
        name_val = _text(a.word).split("=", 1)
        if name_val[0] == "ARGV0" and len(name_val) == 2 \
                and shell_parse.basename(name_val[1]) == _UGREP_ARGV0:
            return [_UGREP_ARGV0] + args
    if name in _SEARCH_NAMES or name == _UGREP_ARGV0:
        return [name] + args
    return None


def _payloads(cmd):
    """The code an `eval` or a bare-named shell `-c` runs, as Scripts; [] when the
    command hands no code to a shell that inherits the function shadow. An `eval`
    is read as bash joins its arguments, and also with each argument kept whole,
    so a pattern the join would split is still seen."""
    r = shell_parse.resolve(cmd)
    if not set(w[0] for w in r.wrappers) <= _PAYLOAD_WRAPPERS:
        return []
    if r.payload_kind == "eval":
        args = [_text(w) for w in r.args]
        joins = [" ".join(args),
                 " ".join(t if t in shell_parse.RESERVED else shlex.quote(t) for t in args)]
        return [shell_parse.parse(t) for t in args + joins]
    if r.payload_kind == "shell_c" and r.name in _SHELL_INTERP_NAMES \
            and "/" not in r.head.value():
        if r.payload is not None:
            return [r.payload]
        return [shell_parse.parse(_text(w)) for w in r.args[_shell_c_index(r.args):][:1]]
    return []


def _shell_c_index(args):
    """Index in a shell's arguments of the `-c` script word."""
    for k, w in enumerate(args):
        v = _text(w)
        if not v.startswith("-") or v.startswith("--"):
            return k
    return len(args)


def _heredoc_scripts(cmd):
    """The heredoc bodies a shell reads as code (`bash <<EOF`), parsed."""
    if shell_parse.resolve(cmd).name not in _SHELL_INTERP_NAMES:
        return []
    return [shell_parse.parse_src(r.hd.body_src, 1) for r in cmd.redirects
            if r.op in ("<<", "<<-") and r.hd is not None]


def _searches_in(script, depth):
    found = []
    for site in shell_parse.walk(script, into=_SUBSTITUTIONS):
        nested = _payloads(site.cmd) + _heredoc_scripts(site.cmd)
        if nested:
            if depth < _MAX_DESCENT:
                for sub in nested:
                    if sub.error is None:
                        found.extend(_searches_in(sub, depth + 1))
            continue
        toks = _search_argv(site.cmd)
        if not toks:
            continue
        mode = _mode_from_flags(toks)
        if mode == "F":
            continue  # fixed strings never backtrack
        found.extend((pat, mode) for pat in _extract_patterns(toks) if pat)
    return found


def _find_searches(command):
    """Return a list of (pattern, mode) for every text search in the command
    that reaches the embedded engine. A command the parser cannot read gives
    no search: the guard lets it through, as it does on every internal error."""
    script = shell_parse.parse(command)
    if script.error is not None:
        return []
    return _searches_in(script, 0)


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
        # Per-user install location of the INVOKING user (not an author literal):
        # expands to the same path the previous hardcoded candidate named when
        # running as root, and resolves correctly for every other user.
        os.path.join(os.path.expanduser("~"), ".local", "bin", "claude"),
    ):
        if os.path.exists(cand):
            return cand
    # Last resort: ordinary PATH discovery, so a system/user install in any
    # location still enables the probe instead of silently disabling it.
    return shutil.which("claude")


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

    # A fresh private directory per probe run: no marker of an earlier run, and
    # none planted elsewhere, can be read as this run's.
    tmpdir = tempfile.mkdtemp(prefix="grepguard-probe-")
    infile = os.path.join(tmpdir, "dense.txt")
    marker = os.path.join(tmpdir, "started")
    try:
        _worst_case_input(infile)
        # Inner command runs inside the scope: it writes the start marker, and
        # stops with 125 (a launch failure) when it cannot, so the engine never
        # runs unmarked. It then drives the SAME embedded engine the agent's grep
        # would, via argv[0]=ugrep and the matching mode flag, on the dense input.
        inner = "printf 'started\\n' > {k} || exit 125; exec -a {a} {b} {m} {p} {f}".format(
            k=shlex.quote(marker),
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
            # Outer guard tripped. A probe that wrote its marker inside the
            # scope started and then ran past even the outer margin => treat as
            # catastrophic. Any file at the marker path counts, so spoiling the
            # marker can only refuse. No marker: the scope never came up (a
            # delayed systemd-run launch), so nothing was measured => fail open.
            if os.path.lexists(marker):
                return True
            raise RuntimeError("probe never started inside its scope")
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
        shutil.rmtree(tmpdir, ignore_errors=True)


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
        "A search of this class has grown to ~24 GiB and triggered a host-wide "
        "out-of-memory kill.",
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
