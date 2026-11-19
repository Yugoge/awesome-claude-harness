#!/usr/bin/env python3
"""Pre-clean WIP-snapshot decision for pretool-bash-safety.sh grant exits.

Classifies ONE Bash command for the fail-closed pre-clean guard woven into the
human-grant/consent `exit 0` escapes of pretool-bash-safety.sh:

  NONE     - no statically reducible destructive `git clean` in the command
  SNAPSHOT - a destructive clean whose target is PROVABLY the hook's own cwd
  DENY     - anything else that still reduces to a destructive clean

The terminal default is DENY, not NONE. The module asks "can a destructive
clean be statically reduced out of this command?" and, if so, demands positive
proof that its target is the hook's own working directory before allowing it:
an unmodelled prefix (`timeout 60 git clean -fd`, `bash -c '...'`) is an
unprovable region, and a clean reducible inside one denies. Target resolution
is deliberately not attempted: an allowed clean whose snapshot covered a
different tree is worse than an honest denial. Redirect presence is decidable;
redirect resolution is not.

One parse feeds every predicate. The command is read by the shared parser's lexer,
so adjacent quoted/escaped fragments are one word (`--no-""dry-run`, `g''it`),
`$'...'` is decoded, and substitution and here-document bodies are commands of
their own. The clean detector, the dry-run predicate, the git-global scan and
the cwd-mutation scan all consume that one word list, so a splice cannot hide a
negation, a `--work-tree` or a `cd` from one predicate while another sees it.

Not protected (each reaches this module on a granted path and reads NONE):
  - ignored-file (`-x`/`-X`) content; the snapshot still fires for `-x` cleans;
  - a command word whose value comes from the environment (`$GITX clean -fd`);
  - a git alias whose value is the clean (`-c alias.x=clean`, or stored config);
  - git's dashed standalone program (`git-clean -fd`);
  - a command word assembled from assignments in the same text
    (`g=git; c=clean; $g $c -fd`).

Protected, by carrier family: direct and behind an unknown wrapper; a fused
option carrying the command word (`env -S'git clean -fd'`); env's `-S`
separator escapes (`env -S 'git\\_clean\\_-fd'`); argument text behind any
command word including git (`git rebase -x '<clean>'`); an interpreter payload
at any depth, where analysis truncated at `_MAX_EMBED_DEPTH` denies; and a
payload delivered on stdin by here-string or here-document.

Accepted over-blocks (cost usability under an active grant, never data):
argument text that reduces to a destructive clean denies wherever it sits
behind a git command (`git commit -m 'add git clean guard'`,
`git log --grep='git clean -fd'`) or any command not PROVEN to execute
nothing, because the same text executes under `git rebase -x`. Since OB-L30
the one exception is a command proven inert by _inert_data_commands (echo,
grep, rg, cat ... at the top level, with no substitution, no rebinding of the
name, no pipe into anything else and no file written beside another command):
its arguments and its heredoc / here-string content are data, so
`grep -rn "git clean -fd" docs/` and `cat > notes.md <<'EOF'` with a body
naming a clean are NONE. Anything that proof cannot establish is scanned
exactly as before, so `echo '<clean>' | sh` and `$(echo <clean>)` still deny.
A heredoc fed to a git command (`git commit -F - <<EOF`) or to a substitution
(`"$(cat <<'EOF' ...)"`) stays in the argument-text class. A
`cd`/`pushd`/`popd` word anywhere in a command that also holds a destructive
clean denies; and a command nested more than `_MAX_EMBED_DEPTH` payloads deep
denies even when it holds no clean.

Exit codes (CLI): 0 = NONE, 10 = SNAPSHOT, 11 = DENY. Reason text on stdout.
"""

from __future__ import annotations

import os
import re
import sys

try:
    from lib.shell_parse import BODY_PART_KINDS, DYNAMIC_PART_KINDS, GIT_REDIRECT_ENV_VARS
    from lib.shell_parse import CWD_BUILTINS, GIT_GLOBAL_VALUE_OPTS, GIT_LOCATION_OPTS, PIPE_OPS, SUBST_OPENERS, LexError, Src, _lex_into, ansi_decode, lex
except ImportError:  # run as a script: hooks/lib is on sys.path
    from shell_parse import BODY_PART_KINDS, DYNAMIC_PART_KINDS, GIT_REDIRECT_ENV_VARS
    from shell_parse import CWD_BUILTINS, GIT_GLOBAL_VALUE_OPTS, GIT_LOCATION_OPTS, PIPE_OPS, SUBST_OPENERS, LexError, Src, _lex_into, ansi_decode, lex
try:
    from . import locations
except ImportError:  # loaded outside its package (by path, or from hooks/lib): its own directory holds it
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import locations

# git globals that point the invocation at a DIFFERENT repository / work tree.
_REDIRECT_FLAGS = GIT_LOCATION_OPTS
# Environment assignments that redirect the target.
_REDIRECT_ENV = frozenset(GIT_REDIRECT_ENV_VARS)
# `-c key=value` config keys that redirect the work tree. `-c` is config, not
# the `-C` chdir: `-c clean.requireForce=false` is not a redirect.
_REDIRECT_CONFIG_KEYS = frozenset({"core.worktree", "core.gitdir"})

# Shell builtins that move the effective working directory.
_SUBST_MARKERS = SUBST_OPENERS + ("`",)

# Reserved words / decorators that never move the target and take no operand.
_RESERVED_DECORATORS = frozenset({
    "!", "{", "}", "then", "else", "elif", "do", "done", "fi", "esac",
})
# Wrapper names whose option-free form is target-transparent. An unlisted name
# means "not provably inert", which denies rather than disappearing.
_INERT_WRAPPERS = frozenset({
    "sudo", "doas", "env", "xargs", "time", "nohup", "setsid", "stdbuf",
    "ionice", "command", "builtin", "nice", "exec",
})

_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# `env -S` / `--split-string` split their value on these escapes (env(1): `\_`
# is a space; `\t`, `\n`, `\f`, `\r`, `\v` the other whitespace). They are not
# shell syntax, so bash hands the payload over as one word. Which characters a
# given env build splits on is a property of that build, so all are modelled.
_ENV_S_SEPARATOR_RE = re.compile(r"\\[_tnfrv]")

_VERDICT_EXIT = {"NONE": 0, "SNAPSHOT": 10, "DENY": 11}
# Embedded-payload recursion budget; exhausting it denies (_analyze_segment).
# The work is O(3^depth): each level re-reads every candidate of every word,
# and a word yields up to three. Measured on a 250 KB crafted payload:
# d=3 0.64s, d=4 1.3s, d=5 2.7s, d=6 5.4s, past the hook's 5s watchdog. Beyond
# the budget the verdict is DENY either way, so a deeper budget only changes
# the reason for denying.
_MAX_EMBED_DEPTH = 3

# Text the lexer cannot read is read again with its quoting, and then all its
# shell syntax, removed: words survive, so a clean in it is still found.
_QUOTING_RE = re.compile(r"['\"`\\]")
_SYNTAX_RE = re.compile(r"['\"`\\$()<>]")
# Word parts with no static text: an expansion the shell computes at run time.
_DYNAMIC_PARTS = DYNAMIC_PART_KINDS
# Parts that run a command (substitutions), whose bodies are commands too.
_BODY_PARTS = BODY_PART_KINDS


class _Word:
    """One static shell word plus the provenance the predicates need."""

    __slots__ = ("text", "dynamic")

    def __init__(self, text, dynamic=False):
        self.text = text
        self.dynamic = dynamic

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"_Word({self.text!r}, dynamic={self.dynamic})"


def _tokens(text):
    """lex() of text; text it cannot read is read with its quoting, then its syntax, removed.

    A here-document with no terminating line is not unreadable: bash reads its
    body to the end of the text ("here-document delimited by end-of-file") and
    feeds it to the command that owns the `<<`, so no line of it is a command.
    The lexer raises unterminated_heredoc only after that body has consumed the
    rest of the text, so the tokens it read are the whole text read as bash
    reads it, the body held on its Redir (`hd`). Stripping the syntax instead
    would turn the `<<` into a word and every body line into a command. As
    OB-L30 read it, a body whose delimiter carries `$` or a backquote is not
    read so: that text goes on to the forms below, its lines read as commands.
    """
    toks = []
    try:
        _lex_into(Src.from_raw(text), toks)
        return toks
    except LexError as exc:
        if exc.code == "unterminated_heredoc" and not any(
                tok[0] == "R" and tok[1].hd is not None and not tok[1].hd.terminated
                and ("$" in tok[1].hd.delim or "`" in tok[1].hd.delim)
                for tok in toks):
            return toks
    for form in (_QUOTING_RE.sub("", text), _SYNTAX_RE.sub(" ", text)):
        try:
            return lex(Src.from_raw(form))
        except LexError:
            continue
    return []


def _static_word(word):
    """(_Word, bodies): the word's static text, and the substitution bodies inside it."""
    out, bodies, dynamic = [], [], False
    for kind, src, _off in word.segs:
        if kind == "ansi":
            out.append(ansi_decode(src.text))
        elif kind in _DYNAMIC_PARTS:
            dynamic = True
            if kind in _BODY_PARTS:
                bodies.append(src.text)
        else:
            out.append(src.text)
    return _Word("".join(out), dynamic), bodies


def _commands(text, info):
    """The simple commands of text, in order, each keeping what is attached to it.

    Each command is a dict: words (its _Word list, command word included),
    stdin (here-string operand words), bodies (here-document and substitution
    body texts, its redirection targets' included), redirs ((Redir, target
    _Word or None) pairs) and next_op (the operator that ended it, None for the
    last). info collects "substitution", "subshell" and "function" (a `name()`
    definition: an OP `(` directly followed by an OP `)`).
    """
    def fresh():
        return {"words": [], "stdin": [], "bodies": [], "redirs": [], "next_op": None}

    commands, current, at_start, prev = [], fresh(), True, None
    for tok in _tokens(text):
        if tok[0] == "OP":
            if tok[1] == "(" and at_start:
                info["subshell"] = True
            if tok[1] == ")" and prev == "(":
                info["function"] = True
            current["next_op"] = tok[1]
            commands.append(current)
            current, at_start, prev = fresh(), True, tok[1]
            continue
        at_start, prev = False, None
        if tok[0] == "R":
            redir = tok[1]
            if redir.op in ("<<", "<<-"):
                # hd holds the body, terminated or (read to the end of the
                # text) not; a `<<` that ends the text has none: empty stdin.
                if redir.hd is not None:
                    current["bodies"].append(redir.hd.body)
                current["redirs"].append((redir, None))
            elif redir.target is not None:
                word, bodies = _static_word(redir.target)
                if bodies:
                    info["substitution"] = True
                current["bodies"].extend(bodies)
                current["redirs"].append((redir, word))
                if redir.op == "<<<":
                    current["stdin"].append(word)
            continue
        word, bodies = _static_word(tok[1])
        current["words"].append(word)
        if bodies or any(kind in _BODY_PARTS for kind, _s, _o in tok[1].segs):
            info["substitution"] = True
        current["bodies"].extend(bodies)
    commands.append(current)
    return commands


def _segments(commands, info, exempt=frozenset()):
    """The command segments of commands: lists of _Word, one per simple command.

    Substitution bodies and here-document bodies are segments of their own, and
    so is a here-string's operand: `bash <<< '<payload>'` runs the payload as
    `bash -c '<payload>'` does. Stdin content is a command string, never an
    argument, so it never joins the words of the command it feeds (`git clean
    -fd <<< '-n'` really deletes). Other redirection targets are file paths
    and are dropped. A command whose index is in ``exempt`` (decide() alone
    passes the ones _inert_data_commands proved inert) contributes nothing: its
    arguments and its stdin content are data that nothing executes.
    """
    segments, extra = [], []
    for k, command in enumerate(commands):
        if k in exempt:
            continue
        segments.extend([word] for word in command["stdin"])
        segments.append(command["words"])
        extra.extend(command["bodies"])
    for body in extra:
        segments.extend(_read(body, info))
    return [seg for seg in segments if seg]


def _read(text, info):
    """The command segments of text (_segments of its _commands, none exempt)."""
    return _segments(_commands(text, info), info)


def _all_words(segments):
    return [word for seg in segments for word in seg]


def _is_redirect_config(kv: str) -> bool:
    return kv.split("=", 1)[0].strip().lower() in _REDIRECT_CONFIG_KEYS


def _abbrev_of(tok: str, full: str, min_len: int) -> bool:
    """True when git parse-options would accept `tok` as an abbreviation of the
    long option `full`. Used only in the fail-closed direction (to clear a
    dry-run exemption and to consume an exclude's operand), so a prefix git
    would reject can at worst cause a superfluous snapshot."""
    return min_len <= len(tok) <= len(full) and full.startswith(tok)


def _is_dry_run(rest: list) -> bool:
    """True only for a proven dry run.

    A force flag is not the destructiveness test (`git -c
    clean.requireForce=false clean -d` deletes without `-f`). git applies `-n`
    and its `--no-dry-run` negation last-wins, so the scan is stateful: `git
    clean -n --no-dry-run -fd` deletes. The negation and the exclude match as
    abbreviations too; the positive `-n` / `--dry-run` stays exact, so an
    unrecognised spelling reads as destructive. A separate-value exclude
    consumes the next word as its pattern (`git clean -fd -e -n` deletes), and
    inside a short cluster only an `n` before the first `e` counts. The scan
    stops at `--`.
    """
    dry = False
    i, n = 0, len(rest)
    while i < n:
        tok = rest[i]
        if tok == "--":
            break
        if tok in ("-n", "--dry-run"):
            dry = True
        elif _abbrev_of(tok, "--no-dry-run", 6):
            dry = False
        elif "=" in tok and _abbrev_of(tok.split("=", 1)[0], "--exclude", 3):
            i += 1
            continue
        elif tok == "-e" or _abbrev_of(tok, "--exclude", 3):
            i += 2
            continue
        elif tok.startswith("-") and not tok.startswith("--"):
            cluster = tok[1:]
            e_pos = cluster.find("e")
            n_pos = cluster.find("n")
            if n_pos >= 0 and (e_pos < 0 or n_pos < e_pos):
                dry = True
            if e_pos == len(cluster) - 1 and e_pos >= 0:
                i += 2
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
        if tok.startswith("-C") and len(tok) > 2:
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
        if tok.startswith("-c") and len(tok) > 2:
            if _is_redirect_config(tok[2:]):
                redirect = True
            i += 1
            continue
        if tok.startswith("--config-env="):
            if _is_redirect_config(tok[len("--config-env="):]):
                redirect = True
            i += 1
            continue
        if tok in GIT_GLOBAL_VALUE_OPTS:
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
    assignment that cannot redirect git, a reserved decorator, an option-free
    wrapper name, or `--`. The first option in the prefix ends the proof. An
    unknown name is returned as the command with inert=True; the caller's
    region scan then denies any clean reducible behind it.
    """
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
            return (i, False)
        return (i, inert)
    return (None, inert)


def _region_candidates(word):
    """Texts inside one region word that could themselves be a command: the word
    itself, any post-`=` value (`env --split-string='git clean -fd'`), and the
    payload of a fused short option (`env -S'git clean -fd'`), from the first
    offset whose basename is `git`. Later words of a payload are scanned on
    their own by the caller, so only the first token can hide a command word.

    `env -S` splits on its own escapes (`env -S'git\\_clean\\_-fd'` holds no
    shell whitespace), so any word in an unprovable region is also read with
    those escapes turned back into spaces.
    """
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

    A provably inert prefix in front of a literal git word is decided by the
    git invocation alone. Any other shape (an unknown wrapper, a wrapper option,
    an embedded payload, argument text) is an unprovable region, and a
    destructive clean reducible anywhere inside it denies. A non-clean git
    subcommand falls through to the same scan: `rebase -x`, `bisect run`,
    `submodule foreach` and `filter-branch` run a string argument in this tree.
    """
    if not words:
        return (False, False)
    idx, inert = _resolve_command(words)
    if idx is None:
        return (False, False)

    if inert and os.path.basename(words[idx].text) == "git":
        destructive, redirect = _git_invocation(words, idx, ignore_dry_run)
        if destructive:
            return (True, not redirect)

    for j in range(idx, len(words)):
        for candidate in _region_candidates(words[j]):
            if len(candidate.split()) > 1:
                # An embedded command string: read it as a command. Truncation
                # is not knowing, and not knowing denies.
                if depth >= _MAX_EMBED_DEPTH:
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
    segments = _read(text, {"substitution": False, "subshell": False})
    if len(segments) == 1 and len(segments[0]) == 1 and segments[0][0].text == text:
        return False  # the lexer reads it as the one word it already is
    for seg in segments:
        if _analyze_segment(seg, depth, ignore_dry_run)[0]:
            return True
    return False


def _has_env_redirect(words) -> bool:
    """True when any word assigns a work-tree-redirecting git environment
    variable, anywhere in the command (`export GIT_DIR=<other> && git clean`)."""
    for word in words:
        text = word.text
        if _ENV_ASSIGN_RE.match(text) and text.split("=", 1)[0] in _REDIRECT_ENV:
            return True
    return False


def _cwd_indeterminate(words, info, raw: str) -> bool:
    """True when the effective cwd at the clean cannot be proven to be the hook
    cwd: a `cd`/`pushd`/`popd` word anywhere, a subshell, or any command or
    process substitution. Substitution markers are re-checked on the raw text so
    a lexer miss still fails closed. Consulted only once a destructive clean has
    been found."""
    if info["substitution"] or info["subshell"]:
        return True
    if any(marker in raw for marker in _SUBST_MARKERS):
        return True
    for word in words:
        if os.path.basename(word.text) in CWD_BUILTINS:
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
#   - Every pipe consumer anywhere in the text (`|` and `|&`) is itself such a
#     command, so `echo '<clean>' | sh` and `{ echo '<clean>'; } | bash` keep
#     the scan.
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
    for redir, target in command["redirs"]:
        if not redir.writes():
            continue  # input, here-document, fd duplication or close
        if target is None or target.dynamic:
            return True
        if target.text == locations.NULL_DEVICE:
            continue
        return True
    words = command["words"]
    i = _data_head(words)
    if i < len(words) and words[i].text in _FILE_WRITING_DATA_COMMANDS:
        operands = [w for w in words[i + 1:] if not w.text.startswith("-")]
        if any(w.text != locations.NULL_DEVICE for w in operands):
            return True
    return False


def _is_shadowing(info, commands, inert) -> bool:
    """True when anything in the text could rebind a command name: a function
    definition anywhere, or - in any command NOT itself proven inert, whose
    words are therefore not known to be mere data - a rebinding builtin word or
    a PATH / BASH_ENV / ENV name or assignment. `.` counts only as a command
    word, so `grep -rn '<text>' .` keeps its search root."""
    if info.get("function"):
        return True     # `name() { ... }` - a function definition
    for k, command in enumerate(commands):
        if k in inert:
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


def _inert_data_commands(commands, info, raw: str):
    """Return the indices of the commands whose arguments and stdin content are
    data, under the conditions set out above; an empty set whenever any of the
    whole-text conditions cannot be established."""
    if info["substitution"] or any(marker in raw for marker in _SUBST_MARKERS):
        return frozenset()
    inert = {k for k, c in enumerate(commands) if _is_inert_data_command(c)}
    if not inert:
        return frozenset()
    if _is_shadowing(info, commands, inert):
        return frozenset()
    for k, command in enumerate(commands):
        if command["next_op"] in PIPE_OPS and k + 1 not in inert:
            return frozenset()
    if any(_writes_a_file(c) for c in commands):
        for k, command in enumerate(commands):
            if k in inert:
                continue
            if all(w.text in _RESERVED_DECORATORS for w in command["words"]):
                continue
            return frozenset()
    return frozenset(inert)


def decide(command_text: str):
    """Return (verdict, reason) for one Bash command.

    A destructive clean is allowed only when every reducible occurrence sits at
    a provably inert command position, no git global or environment variable
    redirects the target, and the effective working directory is provably the
    hook's own. Every other reducible clean denies."""
    info = {"substitution": False, "subshell": False}
    commands = _commands(command_text, info)
    # The cwd and environment-redirect predicates below keep reading EVERY word,
    # data included: they only run once a clean was found, and an inert command
    # never moving the cwd is not something this module needs to prove.
    words = _all_words(_segments(commands, info))
    segments = _segments(commands, info, _inert_data_commands(commands, info, command_text))

    destructive = False
    provable = True
    for seg in segments:
        seg_destructive, seg_provable = _analyze_segment(seg)
        if seg_destructive:
            destructive = True
            provable = provable and seg_provable

    if not destructive:
        # A clean whose flag region is built by substitution is not a proven
        # dry run: the flags the substitution contributes never reach _is_dry_run.
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
    except Exception as exc:  # unclassifiable -> DENY, never NONE
        print("pre-clean guard could not classify the command "
              f"({exc.__class__.__name__}); denying fail-closed")
        sys.exit(_VERDICT_EXIT["DENY"])
    if reason:
        print(reason)
    sys.exit(_VERDICT_EXIT[verdict])
