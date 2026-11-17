#!/usr/bin/env python3
"""Pre-clean WIP-snapshot decision for pretool-bash-safety.sh grant exits.

Classifies ONE Bash command for the fail-closed pre-clean guard woven into the
four human-grant/consent `exit 0` escapes of pretool-bash-safety.sh:

  NONE     - no statically reducible destructive `git clean` in the command
  SNAPSHOT - a destructive clean whose target is PROVABLY the hook's own cwd
  DENY     - anything else that still reduces to a destructive clean

THE TERMINAL DEFAULT IS DENY, NOT NONE. The previous revision asked "does the
command token resolve to git?" and answered NONE whenever it could not tell.
That inverted the burden of proof: an unmodelled prefix (`timeout 60 git clean
-fd`, `bash -c '...'`, `flock ... git clean -fd`) made the clean invisible and a
granted destructive clean proceeded with NO snapshot - the exact incident this
lane exists to prevent. Enumerating more wrapper names only moves that
boundary. This module instead asks "can a destructive clean be statically
reduced out of this command?" and, if so, demands POSITIVE proof that its
target is the hook's own working directory before allowing it.

Target resolution is still deliberately NOT attempted: an allowed clean whose
snapshot covered a DIFFERENT tree is worse than an honest denial, because the
operator is told their work is recoverable when it is not. Redirect PRESENCE is
decidable; redirect RESOLUTION is not.

ONE parse feeds every predicate. `_lex` is a small bash-aware static-word
extractor: it joins adjacent quoted/escaped fragments into a single word
(`--no-""dry-run` -> `--no-dry-run`, `g''it` -> `git`), decodes `$'...'`,
honours line continuations, comments and redirections, reads heredoc bodies as
stdin content of the command owning the `<<`, and marks command substitution. The clean detector, the dry-run predicate, the git-global scan
and the cwd-mutation scan all consume THAT word list, so a splice can no longer
hide a negation, a `--work-tree` or a `cd` from one predicate while another
sees it.

From git_command_classifier.py only the git global-option table is imported:
its `_WRAPPERS` set is a closed enumeration that this module must not treat as
exhaustive.

Coverage bounds. TWICE this section has asserted a universal fail-closed
posture and twice measurement has falsified it - three carriers the first time,
two more the second, each found by someone choosing inputs this module's author
had not imagined. The universal claim is RETIRED rather than re-hedged, because
the habit of stating a bound broader than the one measured is exactly what makes
a green suite read as coverage. An unlisted carrier below reads as UNKNOWN.

What holds without reference to any corpus is STRUCTURAL, and it is the only
thing offered as a guarantee: a region this module cannot prove inert is
scanned, and a destructive clean reducible anywhere inside it DENIES. Every
terminal path - an unresolved command word, an exhausted recursion budget, a
raised exception - ends in DENY. That is what covers the carrier nobody has
thought of yet; the measured list below is evidence, not the guarantee.

MEASURED NOT PROTECTED - declared residuals:
  - Ignored-file (`-x`/`-X`) CONTENT; the snapshot still fires for `-x` cleans
    so untracked-non-ignored WIP is preserved.
  - A command word whose value arrives from the ENVIRONMENT or from an earlier
    process (`$GITX clean -fd`) carries no static text at all. THAT bound is
    real undecidability and it survives.
  - THREE further carriers below are NOT undecidable. Each is statically
    present in the command text and reducible in principle, this module simply
    does not reduce it yet, and each reaches THIS module on the GRANTED path:
    measured NONE, exit 0 and no checkpoint on all four grant channels, with
    the planted incident-class file destroyed in situ. They are out of scope by
    REQUIREMENT-OWNER SCOPE AMENDMENT 2026-08-09 (AC16 check.excluded_carriers),
    a scope decision and not a statement about what is knowable, and they are
    routed to a dedicated follow-up cycle:
      X1 GIT ALIAS - the invoked word is an alias NAME and the clean is produced
         by git's own alias expansion, whether defined inline
         (`-c alias.NAME=...`), installed by a `git config` earlier in the same
         command text, or already stored in configuration. Two reducer causes: a
         bang GLUED to the command word defeats the exact basename test (which
         is why the standalone `! git clean -fd` correctly snapshots and the
         glued spelling does not), and a plain alias VALUE is a git argv with
         the git word implicit.
      X2 DASHED STANDALONE PROGRAM - the command word is git's dashed
         subcommand executable for clean, bare (`git-clean -fd`), path-qualified
         into git's exec-path, or behind an inert prefix, so no `git` word and
         no separate `clean` subcommand word occupies a command position.
      X3 EXPANSION-ASSEMBLED WORD, decidable half only - the assignment sits in
         the SAME command text (`g=git; c=clean; $g $c -fd`), so constant
         propagation would reduce it. The environment-sourced half is the
         genuine undecidability bound listed above.
    The exclusion is CONDITIONAL. All three stay in the corpus tagged
    EXCLUDED_BY_AC16 with that date, ground-truthed and reported on every run,
    recorded rather than scored; any spelling ever measured non-NONE is promoted
    straight back into AC16 part 1 and its exclusion entry deleted.

MEASURED PROTECTED, by carrier family, against the GENERATED cross-product in
tests/generated/dev-20260719-150041-c/test_AC21_*.py - whose rows survive only
when bash is observed to execute them, so a family absent from this list is a
generator gap that shows up as an untested axis rather than as silent coverage:
  - direct, and behind a wrapper name this module has never heard of;
  - a FUSED option carrying the command word (`env -S'git clean -fd'`);
  - env's own separator escapes, in the fused AND spaced spellings of both
    `-S` and `--split-string` (`env -S 'git\\_clean\\_-fd'`). Measured
    precisely: a real space and `\\_` are the separators env was OBSERVED to
    split on, and those cells are shell-proven. `\\t\\n\\f\\r\\v` are modelled
    by `_ENV_S_SEPARATOR_RE` and denied, but were measured NOT to execute on
    this build, so those denials are a disclosed COST and not a protection.
    The broad model is kept deliberately - which characters a given env build
    splits on is a property of that build, and guessing narrow fails OPEN;
  - argument text behind ANY command word INCLUDING a git one
    (`git rebase -x '<clean>'`, `bisect run`, `submodule foreach`);
  - an interpreter payload at any nesting depth, where analysis truncated at
    `_MAX_EMBED_DEPTH` DENIES instead of reading as "nothing here";
  - a payload delivered on STDIN by here-string or heredoc, to any command,
    in every quoting form - previously dropped with the redirection operand.

Accepted over-blocks (cost usability under an active grant, never data):
  - Argument text that reduces to a destructive clean denies wherever it sits
    behind a git command (`git commit -m 'add git clean guard'`,
    `git log --grep='git clean -fd'`) or any command not PROVEN to execute
    nothing: the same text executes under `git rebase -x`. Since OB-L30 the
    one exception is a command proven inert by _inert_data_commands (echo,
    grep, rg, cat ... at the top level, with no substitution, no rebinding of
    the name, no pipe into anything else and no file written beside another
    command): its arguments and its heredoc / here-string content are data, so
    `grep -rn "git clean -fd" docs/` and `cat > notes.md <<'EOF'` with a body
    naming a clean are NONE. Anything that proof cannot establish is scanned
    exactly as before, so `echo '<clean>' | sh` and `$(echo <clean>)` still
    deny. A heredoc fed to a git command (`git commit -F - <<EOF`) or to a
    substitution (`"$(cat <<'EOF' ...)"`) stays in the argument-text class.
  - A `cd`/`pushd`/`popd` word anywhere in a command that ALSO contains a
    destructive clean denies, even when the clean textually precedes it.
  - A command nested more than `_MAX_EMBED_DEPTH` embedded payloads deep denies
    even when it holds no clean at all, because at that point the analysis is
    truncated and "no clean found" is not something this module knows.

Exit codes (CLI): 0 = NONE, 10 = SNAPSHOT, 11 = DENY. Reason text on stdout.
"""

from __future__ import annotations

import os
import re
import sys

try:
    from lib.git_command_classifier import GIT_GLOBAL_VALUE_OPTS
except ImportError:  # run as a script: hooks/lib is on sys.path
    from git_command_classifier import GIT_GLOBAL_VALUE_OPTS

# git globals that point the invocation at a DIFFERENT repository / work tree.
_REDIRECT_FLAGS = frozenset({"-C", "--git-dir", "--work-tree"})
# Environment assignments that redirect the target (QA obs-1: these aim at
# ANOTHER tree, so mis-detection would be safe, but denying them keeps the
# "deny ANY redirect" invariant honest rather than merely safe-by-accident).
_REDIRECT_ENV = frozenset({"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"})
# `-c key=value` config keys that redirect the work tree. NOTE `-c` is config,
# NOT `-C` chdir: `-c clean.requireForce=false` is NOT a redirect.
_REDIRECT_CONFIG_KEYS = frozenset({"core.worktree", "core.gitdir"})

# Shell builtins that move the effective working directory.
_CWD_MUTATORS = frozenset({"cd", "pushd", "popd"})
_SUBST_MARKERS = ("$(", "<(", ">(", "`")

# Reserved words / decorators that never move the target and take no operand.
_RESERVED_DECORATORS = frozenset({
    "!", "{", "}", "then", "else", "elif", "do", "done", "fi", "esac",
})
# Wrapper NAMES whose OPTION-FREE form is target-transparent. Membership here is
# NO LONGER what makes a command visible: an unlisted name simply means "not
# provably inert", which now DENIES rather than disappearing.
_INERT_WRAPPERS = frozenset({
    "sudo", "doas", "env", "xargs", "time", "nohup", "setsid", "stdbuf",
    "ionice", "command", "builtin", "nice", "exec",
})

_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# `env -S` / `env --split-string=` perform their OWN word splitting on the value,
# using these escapes as separators (env(1): `\_` is a space; `\t`, `\n`, `\f`,
# `\r`, `\v` are the other whitespace forms). They are NOT shell syntax, so bash
# hands the whole payload over as one word and a shell-level lexer sees no
# separator at all. Modelled here because ignoring it left
# `env -S'git\_clean\_-fd'` classified NONE while really deleting.
_ENV_S_SEPARATOR_RE = re.compile(r"\\[_tnfrv]")

_VERDICT_EXIT = {"NONE": 0, "SNAPSHOT": 10, "DENY": 11}
# Embedded-payload recursion budget. Exhausting it DENIES (see _analyze_segment).
# KEEP THIS SMALL. Each level re-lexes every candidate of every word, and a word
# can yield up to three candidates (itself, its post-`=` value, its fused-option
# tail), so the work is O(3^depth) in the worst case rather than linear. Measured
# on a 250 KB crafted payload of the form `-x=sh -c '<...>'` nested d deep:
# d=3 0.64s, d=4 1.3s, d=5 2.7s, d=6 5.4s - i.e. raising this to 6 pushed the
# worst case past the hook's own 5s watchdog. That direction fails CLOSED (the
# watchdog's non-zero rc denies), so it costs availability rather than safety,
# but it is still a self-inflicted denial and the depth buys nothing: beyond the
# budget the verdict is DENY either way, so a deeper budget only changes the
# REASON for denying, never the answer.
_MAX_EMBED_DEPTH = 3


class _Word:
    """One static shell word plus the provenance the predicates need."""

    __slots__ = ("text", "dynamic", "redir_target", "stdin_script", "quoted")

    def __init__(self, text, dynamic=False, redir_target=False, quoted=False):
        self.text = text
        self.dynamic = dynamic
        self.redir_target = redir_target
        # True only for a here-string operand: stdin CONTENT, not a file.
        self.stdin_script = False
        # True when any quote or escape contributed to the word. Used only for
        # a heredoc delimiter, where it decides whether the body is expanded.
        self.quoted = quoted

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"_Word({self.text!r}, dynamic={self.dynamic})"


def _decode_ansi_c(inner: str) -> str:
    """Decode a `$'...'` body. Falls back to the raw body, which is fail-closed:
    an undecoded body can only look LESS like `git`/`clean`, and a residual that
    still reduces to a clean is caught by the terminal DENY default."""
    try:
        return inner.encode("utf-8", "surrogateescape").decode("unicode_escape")
    except Exception:
        return inner


def _static_heredoc_delimiter(text: str, j: int) -> bool:
    """True when the heredoc delimiter starting at text[j] is free of `$` and
    backquote. bash matches the terminator against the delimiter AFTER quote
    removal but WITHOUT expansion, so a delimiter carrying an expansion has a
    literal spelling this lexer would mis-compute; such a heredoc is not
    captured, and its body is then lexed inline as command text, exactly as
    before heredoc bodies were modelled."""
    n = len(text)
    while j < n and text[j] in " \t":
        j += 1
    k = j
    while k < n and not text[k].isspace() and text[k] not in ";|&<>()":
        k += 1
    raw = text[j:k]
    return bool(raw) and "$" not in raw and "`" not in raw


def _read_heredoc_bodies(text: str, i: int, tokens: list, pending: list, info: dict) -> int:
    """Consume the bodies of the heredocs opened on the line that just ended.

    Bodies are read in operator order, one per pending `<<`/`<<-`, each up to
    the line equal to its delimiter (leading tabs stripped for `<<-`); a body
    with no terminator runs to the end of the text, as bash reads it. Each body
    becomes a ("heredoc", (body, delimiter_quoted, body_tokens)) token placed
    right after its delimiter word, so it stays attached to the command that
    owns the redirection. The body is lexed here once; its substitution and
    subshell markers are merged into `info` so every later predicate sees them
    exactly as it did when bodies were lexed inline.

    Returns the index just past the last body consumed."""
    n = len(text)
    delimiters = []
    for idx in pending:
        nxt = tokens[idx + 1] if idx + 1 < len(tokens) else None
        if nxt is None or nxt[0] != "word" or nxt[1].dynamic or not nxt[1].text:
            # One unresolvable delimiter makes every body boundary on this line
            # unknown: capture nothing and let the lines lex inline as before.
            return i
        delimiters.append(nxt[1])
    captured = []
    for idx, delim_word in zip(pending, delimiters):
        delim = delim_word.text
        strip_tabs = tokens[idx][1] == "<<-"
        lines = []
        while i < n:
            end = text.find("\n", i)
            line = text[i:] if end < 0 else text[i:end]
            i = n if end < 0 else end + 1
            if (line.lstrip("\t") if strip_tabs else line) == delim:
                break
            lines.append(line)
        captured.append(("\n".join(lines), delim_word.quoted))
    for idx, body in reversed(list(zip(pending, captured))):
        body_tokens, body_info = _lex(body[0])
        info["substitution"] = info["substitution"] or body_info["substitution"]
        info["subshell"] = info["subshell"] or body_info["subshell"]
        tokens.insert(idx + 2, ("heredoc", (body[0], body[1], body_tokens)))
    return i


def _lex(text: str):
    """Return (tokens, info) for one command string.

    tokens: list of ("word", _Word) / ("op", str) / ("redir", str) /
            ("heredoc", (body, delimiter_quoted, body_tokens))
    info:   {"substitution": bool, "subshell": bool}

    A heredoc body is read as stdin CONTENT, not as command text: it is held in
    one ("heredoc", ...) token attached to the command owning the `<<`, with its
    own pre-lexed tokens. Whether that content is then analysed as a script is
    decided by the caller (see _inert_data_commands); by default it is.

    Adjacent quoted/escaped fragments join into ONE word, which is what defeats
    the whole splice class (`g''it`, `--no-""dry-run`, `--work-'tree'=<B>`).
    Never raises: an unterminated quote consumes the remainder of the input."""
    tokens = []
    info = {"substitution": False, "subshell": False}
    buf = []
    dynamic = False
    started = False
    quoted = False
    # Indices in `tokens` of `<<` / `<<-` operators whose body starts at the
    # next unquoted newline.
    pending_heredocs = []
    i, n = 0, len(text)

    def flush():
        nonlocal buf, dynamic, started, quoted
        if started or buf:
            tokens.append(("word", _Word("".join(buf), dynamic, quoted=quoted)))
        buf, dynamic, started, quoted = [], False, False, False

    def at_command_position():
        if started or buf:
            return False
        for kind, _payload in reversed(tokens):
            return kind == "op"
        return True

    while i < n:
        c = text[i]
        two = text[i:i + 2]

        # `#` starts a comment only at the beginning of a word.
        if c == "#" and not started and not buf:
            while i < n and text[i] != "\n":
                i += 1
            continue

        if c == "\\":
            if two == "\\\n":
                i += 2          # line continuation: joins adjacent fragments
                continue
            if i + 1 < n:
                buf.append(text[i + 1])
                started = quoted = True
                i += 2
                continue
            i += 1
            continue

        # ANSI-C quoting is STATIC: `git $'clean' -fd` really runs a clean.
        if two == "$'":
            j = i + 2
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == "'":
                    break
                j += 1
            buf.append(_decode_ansi_c(text[i + 2:j]))
            started = quoted = True
            i = min(j + 1, n)
            continue

        if two == '$"':         # locale-translated string behaves like "..."
            i += 1
            continue

        if two in ("$(", "<(", ">("):
            info["substitution"] = True
            flush()
            tokens.append(("op", two))
            i += 2
            continue
        if c == "`":
            info["substitution"] = True
            flush()
            tokens.append(("op", "`"))
            i += 1
            continue

        if c == "$":            # parameter expansion contributes no static text
            dynamic = True
            started = True
            j = i + 1
            if j < n and text[j] == "{":
                depth, j = 1, j + 1
                while j < n and depth:
                    if text[j] == "{":
                        depth += 1
                    elif text[j] == "}":
                        depth -= 1
                    j += 1
            else:
                while j < n and (text[j].isalnum() or text[j] == "_"):
                    j += 1
                if j == i + 1 and j < n:
                    j += 1      # $?, $$, $1 ...
            i = j
            continue

        if c == "'":
            j = text.find("'", i + 1)
            if j < 0:
                buf.append(text[i + 1:])
                started = quoted = True
                i = n
                continue
            buf.append(text[i + 1:j])
            started = quoted = True
            i = j + 1
            continue

        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    nxt = text[j + 1]
                    if nxt in '$`"\\':
                        buf.append(nxt)
                    elif nxt != "\n":
                        buf.append(text[j])
                        buf.append(nxt)
                    j += 2
                    continue
                if text[j] in "$`":
                    if text[j] == "`" or text[j:j + 2] == "$(":
                        info["substitution"] = True
                    dynamic = True
                    j += 1
                    continue
                buf.append(text[j])
                j += 1
            started = quoted = True
            i = j + 1
            continue

        if c in "<>":           # redirection, with an optional leading fd
            op = c
            j = i + 1
            while j < n and text[j] in "<>&" and len(op) < 3:
                op += text[j]
                j += 1
            if op == "<<" and j < n and text[j] == "-":
                op += "-"       # `<<-`: heredoc with leading tabs stripped
                j += 1
            if buf and all(ch.isdigit() for ch in buf):
                buf, started, quoted = [], False, False  # fd of the redirection
            else:
                flush()
            if op in ("<<", "<<-") and _static_heredoc_delimiter(text, j):
                pending_heredocs.append(len(tokens))
            tokens.append(("redir", op))
            i = j
            continue

        if two in ("&&", "||", ";;"):
            flush()
            tokens.append(("op", two))
            i += 2
            continue

        if c in ";\n|&":
            flush()
            tokens.append(("op", c))
            i += 1
            if c == "\n" and pending_heredocs:
                i = _read_heredoc_bodies(text, i, tokens, pending_heredocs, info)
                pending_heredocs = []
            continue

        if c == "(":
            if at_command_position():
                info["subshell"] = True
            flush()
            tokens.append(("op", "("))
            i += 1
            continue

        if c == ")":
            flush()
            tokens.append(("op", ")"))
            i += 1
            continue

        if c.isspace():
            flush()
            i += 1
            continue

        buf.append(c)
        started = True
        i += 1

    flush()

    # A redirection's operand is data, never a command word - but WHICH data
    # depends on the operator. For `>`/`<` it is a FILE PATH and dropping it is
    # right. For `<<<`/`<<` it is stdin CONTENT, which is a SCRIPT whenever the
    # command consumes stdin as one, so it is flagged for retention instead.
    for idx, (kind, payload) in enumerate(tokens):
        if kind != "redir":
            continue
        for nxt_kind, nxt in tokens[idx + 1:]:
            if nxt_kind == "word":
                nxt.redir_target = True
                nxt.stdin_script = payload.startswith("<<")
            break
    return tokens, info


def _split_segments(tokens):
    """Split the token stream into command segments on shell separators,
    dropping redirection operators and their FILE operands.

    A here-string / heredoc operand is NOT dropped. `bash <<< '<payload>'` runs
    the payload exactly as `bash -c '<payload>'` does, and discarding it made the
    command reduce to nothing at all: eleven spellings reached a grant exit with
    verdict NONE and no snapshot. The heredoc form of the same command already
    snapshotted correctly, because its newline split the body into its own
    segment - one spelling of a family handled and its sibling not, which marks
    this a lexer-coverage gap rather than a policy.

    The operand becomes its OWN segment rather than an extra word of the command
    it feeds, and that distinction is load-bearing in the fail-closed direction.
    Appending would hand its text to `_is_dry_run` as though it were an argument,
    so `git clean -fd <<< '-n'` - which really deletes, because git ignores its
    stdin - would read as a proven dry run and LOSE the snapshot it gets today.
    stdin content is a command string, never an argument.

    Deliberately NOT keyed on whether the command word is a shell: deciding which
    programs execute their stdin is the enumeration mistake in a new costume. The
    operand is scanned like any other unprovable region, so one that reduces to a
    destructive clean denies wherever it sits and an inert one costs nothing.

    A heredoc body is expanded back into the segments of its own pre-lexed
    tokens, which is what it produced when bodies were lexed inline. decide()
    alone calls _segments_of with the commands _inert_data_commands proved
    inert; those contribute no segment, since their arguments and stdin content
    are data that nothing executes."""
    return _segments_of(_split_commands(tokens))


def _split_commands(tokens):
    """Group the token stream into simple commands, keeping each command's
    redirections, here-string operands and heredoc bodies attached to it.

    Each command is a dict: words (argument words, command word included),
    stdin (here-string / heredoc-delimiter operand words), heredocs (body
    tuples), redirs ([operator, operand word or None]) and next_op (the
    separator that ended it, None for the last)."""
    commands = []

    def fresh():
        return {"words": [], "stdin": [], "heredocs": [], "redirs": [], "next_op": None}

    current = fresh()
    for kind, payload in tokens:
        if kind == "op":
            current["next_op"] = payload
            commands.append(current)
            current = fresh()
            continue
        if kind == "redir":
            current["redirs"].append([payload, None])
            continue
        if kind == "heredoc":
            current["heredocs"].append(payload)
            continue
        if payload.redir_target:
            if current["redirs"] and current["redirs"][-1][1] is None:
                current["redirs"][-1][1] = payload
            if payload.stdin_script:
                current["stdin"].append(payload)
            continue
        current["words"].append(payload)
    commands.append(current)
    return commands


def _segments_of(commands, exempt=()):
    segments, stdin_scripts, bodies = [], [], []
    for command in commands:
        if id(command) in exempt:
            continue
        segments.append(command["words"])
        stdin_scripts.extend([word] for word in command["stdin"])
        for _body, _quoted, body_tokens in command["heredocs"]:
            bodies.extend(_split_segments(body_tokens))
    segments.extend(stdin_scripts)
    segments.extend(bodies)
    return [seg for seg in segments if seg]


def _all_words(segments):
    return [word for seg in segments for word in seg]


def _is_redirect_config(kv: str) -> bool:
    return kv.split("=", 1)[0].strip().lower() in _REDIRECT_CONFIG_KEYS


def _abbrev_of(tok: str, full: str, min_len: int) -> bool:
    """True when git parse-options would accept `tok` as an abbreviation of the
    long option `full`. Unambiguous prefixes are accepted by git (verified:
    `git status --no-col` and `--unt=no` both parse), and `git clean`'s option
    set is small enough that `--no-dry` and `--e` are unambiguous. Used only in
    the fail-CLOSED direction — to CLEAR a dry-run exemption and to consume an
    exclude's operand — so a prefix git would actually reject can at worst cause
    a superfluous snapshot, never a skipped one."""
    return min_len <= len(tok) <= len(full) and full.startswith(tok)


def _is_dry_run(rest: list) -> bool:
    """True only for a PROVEN dry run. A force flag is NOT the destructiveness
    test (`git -c clean.requireForce=false clean -d` deletes without `-f`), so
    everything that is not `-n`/`--dry-run` counts as destructive-or-uncertain.

    git parse-options applies the dry-run flag and its generated `--no-dry-run`
    negation LAST-WINS, so the scan is STATEFUL rather than first-match: `git
    clean -n --no-dry-run -fd` DELETES, and an early `return True` on the first
    `-n` skipped the snapshot on it (CX-1). The negation and the exclude are
    matched as ABBREVIATIONS too (`--no-dry`, `--exc <pat>`), because git accepts
    any unambiguous prefix; both directions of that are fail-closed, so an
    abbreviation git would reject only costs a superfluous snapshot. The
    positive `-n` / `--dry-run` stays exact-match for the same reason: an
    unrecognised spelling must read as destructive, never as exempt.

    A separate-value exclude consumes the FOLLOWING token as its pattern, so a
    trailing `-n` there is an exclude pattern and NOT a dry run: `git clean -fd
    -e -n` DELETES. Treating it as exempt would skip the snapshot on a
    destructive clean, so `-e` / `--exclude` operands are skipped, and inside a
    short cluster only an `n` occurring BEFORE the first `e` counts (everything
    after an `e` is that exclude's argument). Scanning stops at `--` so a
    pathspec literally named `-n` cannot exempt either."""
    dry = False
    i, n = 0, len(rest)
    while i < n:
        tok = rest[i]
        if tok == "--":
            break  # everything after is a pathspec, not a flag
        if tok in ("-n", "--dry-run"):
            dry = True
        elif _abbrev_of(tok, "--no-dry-run", 6):
            dry = False  # last-wins negation, `--no-d` upwards
        elif "=" in tok and _abbrev_of(tok.split("=", 1)[0], "--exclude", 3):
            i += 1  # self-contained `--exclude=<pat>`, consumes nothing
            continue
        elif tok == "-e" or _abbrev_of(tok, "--exclude", 3):
            i += 2  # the next token is this exclude's pattern, not a flag
            continue
        elif tok.startswith("-") and not tok.startswith("--"):
            cluster = tok[1:]
            e_pos = cluster.find("e")
            n_pos = cluster.find("n")
            if n_pos >= 0 and (e_pos < 0 or n_pos < e_pos):
                dry = True
            if e_pos == len(cluster) - 1 and e_pos >= 0:
                i += 2  # cluster ends in `e` -> next token is its pattern
                continue
        i += 1
    return dry


def _git_invocation(words, start, ignore_dry_run=False):
    """words[start] basenames to `git`. Return (destructive_clean, redirect)."""
    redirect = False
    subcommand = None
    sub_idx = None
    i, n = start + 1, len(words)
    while i < n:
        tok = words[i].text
        if not tok:
            if words[i].dynamic:
                return (False, False)   # an expansion sits in global position
            i += 1
            continue
        if tok in _REDIRECT_FLAGS:
            redirect = True
            i += 2
            continue
        if tok.startswith("-C") and len(tok) > 2:  # fused -C<dir>
            redirect = True
            i += 1
            continue
        if tok.startswith("--git-dir=") or tok.startswith("--work-tree="):
            redirect = True
            i += 1
            continue
        if tok in ("-c", "--config-env"):
            if i + 1 < n and _is_redirect_config(words[i + 1].text):
                redirect = True
            i += 2
            continue
        if tok.startswith("-c") and len(tok) > 2:  # fused -c<key=value>
            if _is_redirect_config(tok[2:]):
                redirect = True
            i += 1
            continue
        if tok.startswith("--config-env="):
            if _is_redirect_config(tok[len("--config-env="):]):
                redirect = True
            i += 1
            continue
        if tok in GIT_GLOBAL_VALUE_OPTS:  # any other value-taking global
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        subcommand, sub_idx = tok, i
        break

    if subcommand != "clean":
        return (False, False)
    if not ignore_dry_run and _is_dry_run([w.text for w in words[sub_idx + 1:]]):
        return (False, False)
    return (True, redirect)


def _resolve_command(words):
    """Return (index_of_command_word, prefix_is_provably_inert).

    A prefix is inert only when every word before the command is an env
    assignment that cannot redirect git, a reserved decorator, an OPTION-FREE
    wrapper name, or a `--` option terminator. The FIRST option in the prefix
    region ends the proof: `-C`/`--chdir` move the child's cwd outright, and an
    option this module does not model cannot be proven not to. An UNKNOWN name
    is returned as the command with inert=True; it is the caller's region scan
    that then denies any clean reducible behind it."""
    i, n = 0, len(words)
    inert = True
    while i < n:
        tok = words[i].text
        if not tok and words[i].dynamic:
            return (i, False)
        if _ENV_ASSIGN_RE.match(tok):
            name = tok.split("=", 1)[0]
            if name in _REDIRECT_ENV or name.startswith("GIT_"):
                inert = False
            i += 1
            continue
        if tok in _RESERVED_DECORATORS or tok == "--":
            i += 1
            continue
        if os.path.basename(tok) in _INERT_WRAPPERS:
            i += 1
            continue
        if tok.startswith("-"):
            return (i, False)       # a wrapper's own option: unprovable region
        return (i, inert)
    return (None, inert)


def _region_candidates(word):
    """Texts inside one region word that could themselves be a command: the word
    itself, any post-`=` value (`env --split-string='git clean -fd'`), and the
    payload of a FUSED short option (`env -S'git clean -fd'`).

    The fused spelling is why this leaked. `-S` and its quoted argument are ONE
    shell word, so the sole candidate `-Sgit clean -fd` re-parsed to the command
    word `-Sgit`: `-`-prefixed, so not provably inert, and not a `git` basename,
    so the region scan skipped it and a granted clean ran unsnapshotted. The
    spaced (`env -S '...'`) and long (`--split-string=`) spellings denied
    correctly, which is what marks this a lexer-coverage gap rather than a
    policy.

    Only the FIRST token can hide a command word: every later word of the
    payload is scanned on its own by the caller, so a fused INTERPRETER
    (`env -S'sh -c "git clean -fd"'`) is already caught through its payload
    words, and a fused wrapper (`env -Ssudo git clean -fd`) through the bare
    `git` word that follows. What the caller cannot see is a command word glued
    to the option letters, so the first offset whose basename is `git` is
    emitted as a candidate too - one extra candidate, no extra recursion.

    THAT ARGUMENT IS ONLY TRUE ONCE THE WORD IS IN SHELL-WORD FORM, which is the
    correction adversarial review forced. `env -S` carries its own mini-language
    and uses `\\_` for a space, so `env -S'git\\_clean\\_-fd'` runs a destructive
    clean while containing NO shell whitespace at all: bash hands over a single
    word, `_lex` correctly sees one word, "is it multi-word?" answers no, and the
    payload was invisible. env splits on the escapes below, so a surface form
    with those translated back to spaces is analysed alongside the raw text.

    That unescape is gated on the REGION, not on the spelling. Gating it on the
    word starting with `-` was the same enumeration mistake once more: it holds
    for the fused word `-Sgit\\_clean\\_-fd` and NOT for the spaced payload word
    of `env -S 'git\\_clean\\_-fd'`, so two cells of the {fused, spaced} x {plain,
    escaped} grid were closed and the third stayed open and deleting. Any word in
    an unprovable region gets the surface; the cost is confined to words that
    literally contain one of `\\_ \\t \\n \\f \\r \\v` AND still reduce to a
    destructive clean once translated."""
    surfaces = [word.text]
    if "\\" in word.text:
        unescaped = _ENV_S_SEPARATOR_RE.sub(" ", word.text)
        if unescaped != word.text:
            surfaces.append(unescaped)
    out = []
    for text in surfaces:
        out.append(text)
        if "=" in text:
            out.append(text.split("=", 1)[1])
        if text.startswith("-"):
            head = text.split(None, 1)[0]
            for k in range(1, len(head)):
                if os.path.basename(head[k:]) == "git":
                    out.append(text[k:])
                    break
    return [t for t in out if t]


def _analyze_segment(words, depth=0, ignore_dry_run=False):
    """Return (destructive_clean_present, target_provably_hook_cwd).

    The inversion lives here. A provably-inert prefix in front of a literal git
    token is decided by the git invocation alone. ANY other shape - an
    unrecognised wrapper name, a wrapper option region, an embedded shell
    payload, bare argument text - is an unprovable region, and a destructive
    clean reducible anywhere inside it denies instead of vanishing."""
    if not words:
        return (False, False)
    idx, inert = _resolve_command(words)
    if idx is None:
        return (False, False)

    if inert and os.path.basename(words[idx].text) == "git":
        destructive, redirect = _git_invocation(words, idx, ignore_dry_run)
        if destructive:
            return (True, not redirect)
        # A NON-clean subcommand is not proof that the command is harmless. git
        # subcommands that EXECUTE a string argument - `rebase -x/--exec`,
        # `bisect run`, `submodule foreach`, `filter-branch` - run it in THIS
        # working tree, so returning early here meant `echo '<clean>'` denied
        # while the identical text behind `-x` was waved through and destroyed
        # the WIP unrecoverably. Fall through and scan the arguments the same
        # way every other command's arguments are scanned; the resulting
        # over-block (`git commit -m 'add git clean guard'`) is the disclosed
        # argument-text class, and consistency there is the point.

    for j in range(idx, len(words)):
        for candidate in _region_candidates(words[j]):
            if len(candidate.split()) > 1:
                # An embedded command string (`bash -c '<payload>'`,
                # `env -S '<payload>'`): re-parse it as a command.
                if depth >= _MAX_EMBED_DEPTH:
                    # Truncation is precisely the state of NOT KNOWING, and the
                    # doctrine above says unknown denies. `continue` here made a
                    # budget-exhausted payload indistinguishable from an empty
                    # one, so one extra `sh -c` wrapper bought a silent allow -
                    # and wrapping a target redirect in it re-opened that class
                    # too.
                    return (True, False)
                if _reduces_to_clean(candidate, depth + 1, ignore_dry_run):
                    return (True, False)
                continue
            if os.path.basename(candidate) != "git":
                continue
            tail = (words[j:] if candidate == words[j].text
                    else [_Word(candidate)] + list(words[j + 1:]))
            if _git_invocation(tail, 0, ignore_dry_run)[0]:
                return (True, False)
    return (False, False)


def _reduces_to_clean(text: str, depth=0, ignore_dry_run=False) -> bool:
    """True when an embedded command string statically reduces to a destructive
    clean in any of its segments."""
    tokens, _info = _lex(text)
    for seg in _split_segments(tokens):
        if _analyze_segment(seg, depth, ignore_dry_run)[0]:
            return True
    return False


def _has_env_redirect(words) -> bool:
    """True when ANY word assigns a work-tree-redirecting git environment
    variable. Scanned across the whole command, not just the git segment's own
    leading assignments, so `export GIT_DIR=<other> && git clean -fd` is caught
    as well as the inline `GIT_WORK_TREE=<other> git clean -fd` form."""
    for word in words:
        text = word.text
        if _ENV_ASSIGN_RE.match(text) and text.split("=", 1)[0] in _REDIRECT_ENV:
            return True
    return False


def _cwd_indeterminate(words, info, raw: str) -> bool:
    """True when the effective cwd at the clean cannot be proven to be the hook
    cwd: a `cd`/`pushd`/`popd` word ANYWHERE (a prefix such as `!`, `command --`
    or `time -p` must not be able to hide one), a subshell, or any command /
    process substitution. Substitution markers are re-checked on the RAW text so
    a lexer miss still fails closed. Consulted only once a destructive clean has
    been found, so a `cd` in an unrelated command costs nothing."""
    if info["substitution"] or info["subshell"]:
        return True
    if any(marker in raw for marker in _SUBST_MARKERS):
        return True
    for word in words:
        if os.path.basename(word.text) in _CWD_MUTATORS:
            return True
    return False


# ---------------------------------------------------------------------------
# Argument DATA versus executed command words (OB-L30).
#
# The region scan above treats every argument as possibly-executed text, and it
# must: `git rebase -x`, `timeout`, `flock` and any unknown name run their
# arguments. What it may not do is read the arguments of a command that is
# PROVEN to execute nothing, whose output provably reaches nothing that
# executes either. That proof is positive and narrow; every condition below
# that cannot be established leaves the command scanned exactly as before.
#
#   - The command word is a literal, unshadowed name from _ARG_INERT_COMMANDS:
#     programs whose operands are patterns, text or file names and that have no
#     option which runs a program (rg only without any `--pre*` option and
#     without an expansion that could supply one). Membership can only ever
#     REMOVE a scan; an unlisted name keeps the scan, so the list is not the
#     wrapper-enumeration mistake turned around.
#   - Only reserved words and the option-free `command`/`builtin`/`time` may
#     precede it: an assignment or a wrapper option ends the proof.
#   - The command text is analysed at the TOP level only. Inside an embedded
#     payload (`bash -c '...'`, `git rebase -x '...'`) the text is already being
#     executed by something whose output use is unknown, so nothing is exempt.
#   - No command or process substitution anywhere: `$(echo git clean -fd)` runs
#     the echoed text, and so does a substitution fed by a heredoc.
#   - Nothing in the text can rebind the name: no function definition, no
#     alias/unalias/enable/hash/shopt/source/./eval word, no PATH, BASH_ENV or
#     ENV assignment or operand.
#   - Every pipe consumer anywhere in the text is itself such a command, so
#     `echo '<clean>' | sh` and `{ echo '<clean>'; } | bash` keep the scan.
#   - If anything writes a file (an output redirection other than /dev/null or
#     an fd duplication, or a `tee` operand), EVERY command in the text must be
#     such a command, so `echo '<clean>' > x.sh && sh x.sh` keeps the scan.
#
# A command proven inert contributes nothing to the clean scan: neither its
# argument words nor its here-string / heredoc content. A heredoc fed to any
# other command (`bash <<EOF`, `git commit -F - <<EOF`) is still scanned.
# ---------------------------------------------------------------------------
_ARG_INERT_COMMANDS = frozenset({
    "echo", "cat", "grep", "egrep", "fgrep", "rg",
    "head", "tail", "wc", "cut", "tr", "nl", "tee",
})
_FILE_WRITING_DATA_COMMANDS = frozenset({"tee"})
_DATA_PREFIX = frozenset({
    "!", "{", "then", "else", "elif", "do", "if", "while", "until",
    "time", "command", "builtin",
})
_SHADOWING_WORDS = frozenset({
    "alias", "unalias", "enable", "hash", "function", "shopt",
    "source", "eval",
})
_SHADOWING_NAMES = ("PATH", "BASH_ENV", "ENV")


def _data_head(words):
    """Index of the first word after the reserved-word / option-free prefix."""
    i = 0
    while i < len(words) and not words[i].dynamic and words[i].text in _DATA_PREFIX:
        i += 1
    return i


def _is_inert_data_command(command) -> bool:
    words = command["words"]
    i = _data_head(words)
    if i >= len(words):
        return False
    head = words[i]
    if head.dynamic or head.text not in _ARG_INERT_COMMANDS:
        return False
    if head.text == "rg":
        for word in words[i + 1:]:
            if word.dynamic or word.text.startswith("--pre"):
                return False
    return True


def _writes_a_file(command) -> bool:
    for op, target in command["redirs"]:
        if ">" not in op:
            continue
        if target is None or target.dynamic:
            return True
        if target.text == "/dev/null":
            continue
        if op.endswith("&") and (target.text.isdigit() or target.text == "-"):
            continue
        return True
    words = command["words"]
    i = _data_head(words)
    if i < len(words) and words[i].text in _FILE_WRITING_DATA_COMMANDS:
        operands = [w for w in words[i + 1:] if not w.text.startswith("-")]
        if any(w.text != "/dev/null" for w in operands):
            return True
    return False


def _is_shadowing(tokens, commands, inert_ids) -> bool:
    """True when anything in the text could rebind a command name: a function
    definition anywhere, or - in any command NOT itself proven inert, whose
    words are therefore not known to be mere data - a rebinding builtin word or
    a PATH / BASH_ENV / ENV name or assignment. `.` counts only as a command
    word, so `grep -rn '<text>' .` keeps its search root."""
    prev = None
    for kind, payload in tokens:
        if kind == "op" and payload == ")" and prev == ("op", "("):
            return True     # `name() { ... }` - a function definition
        prev = (kind, payload if kind != "word" else None)
    for command in commands:
        if id(command) in inert_ids:
            continue
        words = command["words"]
        head = _data_head(words)
        if head < len(words) and words[head].text == ".":
            return True
        for word in words:
            text = word.text
            if text in _SHADOWING_WORDS:
                return True
            for name in _SHADOWING_NAMES:
                if text == name or text.startswith(name + "=") or text.startswith(name + "+="):
                    return True
    return False


def _inert_data_commands(commands, tokens, info, raw: str):
    """Return the ids of the commands whose arguments and stdin content are
    data, under the conditions set out above; an empty set whenever any of the
    whole-text conditions cannot be established."""
    if info["substitution"] or any(marker in raw for marker in _SUBST_MARKERS):
        return frozenset()
    inert = {id(c) for c in commands if _is_inert_data_command(c)}
    if not inert:
        return frozenset()
    if _is_shadowing(tokens, commands, inert):
        return frozenset()
    for idx, command in enumerate(commands):
        if command["next_op"] == "|":
            consumer = commands[idx + 1] if idx + 1 < len(commands) else None
            if consumer is None or id(consumer) not in inert:
                return frozenset()
    if any(_writes_a_file(c) for c in commands):
        for command in commands:
            if id(command) in inert:
                continue
            if all(w.text in _RESERVED_DECORATORS for w in command["words"]):
                continue
            return frozenset()
    return frozenset(inert)


def decide(command_text: str):
    """Return (verdict, reason) for one Bash command.

    Fail-closed by design: a destructive clean is allowed ONLY when every
    reducible occurrence sits at a provably-inert command position, no git
    global or environment variable redirects the target, and the effective
    working directory is provably the hook's own. Every other reducible clean
    - including one behind a prefix this guard does not model - denies."""
    tokens, info = _lex(command_text)
    commands = _split_commands(tokens)
    # The cwd and environment-redirect predicates below keep reading EVERY word,
    # data included: they only run once a clean was found, and an inert command
    # never moving the cwd is not something this module needs to prove.
    words = _all_words(_segments_of(commands))
    segments = _segments_of(
        commands, _inert_data_commands(commands, tokens, info, command_text))

    destructive = False
    provable = True
    for seg in segments:
        seg_destructive, seg_provable = _analyze_segment(seg)
        if seg_destructive:
            destructive = True
            provable = provable and seg_provable

    if not destructive:
        # A clean whose flag region is built by substitution is not a PROVEN dry
        # run: _split_segments carved the substitution into its own segment, so
        # the flags it contributes never reached _is_dry_run.
        if info["substitution"] or any(m in command_text for m in _SUBST_MARKERS):
            for seg in segments:
                if _analyze_segment(seg, ignore_dry_run=True)[0]:
                    return ("DENY", "a `git clean` carries command substitution "
                                    "in its flag region - the effective flags "
                                    "cannot be proven to be a dry run")
        return ("NONE", "")

    if not provable:
        return ("DENY", "a destructive `git clean` is reducible from this command, "
                        "but its target is not provably this working directory: it "
                        "sits behind a target-redirecting git global (-C / --git-dir "
                        "/ --work-tree / -c core.worktree), a wrapper option "
                        "(env -C / env --chdir / env -S), an unrecognised wrapper or "
                        "interpreter, an embedded shell payload (including one "
                        "nested deeper than this guard analyses), or plain argument "
                        "text this guard cannot prove inert - argument text behind a "
                        "git subcommand included, since `git rebase -x` runs it")
    if _has_env_redirect(words):
        return ("DENY", "a work-tree-redirecting git environment variable "
                        "(GIT_DIR / GIT_WORK_TREE / GIT_COMMON_DIR) is assigned - "
                        "the clean target is not provably the hook's own working "
                        "directory")
    if _cwd_indeterminate(words, info, command_text):
        return ("DENY", "effective working directory is indeterminate "
                        "(cd/pushd/popd, subshell, or command substitution) - "
                        "the clean target is not provably the hook's own working "
                        "directory")
    return ("SNAPSHOT", "")


if __name__ == "__main__":
    cmd_text = os.environ.get("CMD_INPUT", "")
    if not cmd_text:
        cmd_text = sys.stdin.read()
    try:
        verdict, reason = decide(cmd_text)
    except Exception as exc:  # unclassifiable -> DENY, never NONE. The former
        # `if "git" not in cmd_text: NONE` escape was a raw-substring test, and a
        # spliced or ANSI-C-quoted command word defeats exactly that test.
        print("pre-clean guard could not classify the command "
              f"({exc.__class__.__name__}); denying fail-closed")
        sys.exit(_VERDICT_EXIT["DENY"])
    if reason:
        print(reason)
    sys.exit(_VERDICT_EXIT[verdict])
