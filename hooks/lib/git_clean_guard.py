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
(`echo git clean -fd`, `git commit -m 'add git clean guard'`), because the same
text executes under `git rebase -x`; a `cd`/`pushd`/`popd` word anywhere in a
command that also holds a destructive clean denies; and a command nested more
than `_MAX_EMBED_DEPTH` payloads deep denies even when it holds no clean.

Exit codes (CLI): 0 = NONE, 10 = SNAPSHOT, 11 = DENY. Reason text on stdout.
"""

from __future__ import annotations

import os
import re
import sys

try:
    from lib.shell_parse import GIT_GLOBAL_VALUE_OPTS, LexError, Src, ansi_decode, lex
except ImportError:  # run as a script: hooks/lib is on sys.path
    from shell_parse import GIT_GLOBAL_VALUE_OPTS, LexError, Src, ansi_decode, lex

# git globals that point the invocation at a DIFFERENT repository / work tree.
_REDIRECT_FLAGS = frozenset({"-C", "--git-dir", "--work-tree"})
# Environment assignments that redirect the target.
_REDIRECT_ENV = frozenset({"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"})
# `-c key=value` config keys that redirect the work tree. `-c` is config, not
# the `-C` chdir: `-c clean.requireForce=false` is not a redirect.
_REDIRECT_CONFIG_KEYS = frozenset({"core.worktree", "core.gitdir"})

# Shell builtins that move the effective working directory.
_CWD_MUTATORS = frozenset({"cd", "pushd", "popd"})
_SUBST_MARKERS = ("$(", "<(", ">(", "`")

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
_DYNAMIC_PARTS = frozenset({"param", "sub", "arith", "procsub"})
# Parts that run a command (substitutions), whose bodies are commands too.
_BODY_PARTS = frozenset({"sub", "procsub", "arith"})


class _Word:
    """One static shell word plus the provenance the predicates need."""

    __slots__ = ("text", "dynamic")

    def __init__(self, text, dynamic=False):
        self.text = text
        self.dynamic = dynamic

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"_Word({self.text!r}, dynamic={self.dynamic})"


def _tokens(text):
    """lex() of text; text it cannot read is read with its quoting, then its syntax, removed."""
    for form in (text, _QUOTING_RE.sub("", text), _SYNTAX_RE.sub(" ", text)):
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


def _read(text, info):
    """The command segments of text: lists of _Word, one per simple command.

    Substitution bodies and here-document bodies are segments of their own, and
    so is a here-string's operand: `bash <<< '<payload>'` runs the payload as
    `bash -c '<payload>'` does. Stdin content is a command string, never an
    argument, so it never joins the words of the command it feeds (`git clean
    -fd <<< '-n'` really deletes). Other redirection targets are file paths
    and are dropped. info collects "substitution" and "subshell".
    """
    segments, current, extra = [], [], []
    at_start = True
    for tok in _tokens(text):
        if tok[0] == "OP":
            if tok[1] == "(" and at_start:
                info["subshell"] = True
            segments.append(current)
            current, at_start = [], True
            continue
        at_start = False
        if tok[0] == "R":
            redir = tok[1]
            if redir.heredoc is not None:
                extra.append(redir.heredoc[2].text)
            elif redir.target is not None:
                word, bodies = _static_word(redir.target)
                if bodies:
                    info["substitution"] = True
                extra.extend(bodies)
                if redir.op == "<<<":
                    segments.append([word])
            continue
        word, bodies = _static_word(tok[1])
        current.append(word)
        if bodies or any(kind in _BODY_PARTS for kind, _s, _o in tok[1].segs):
            info["substitution"] = True
        extra.extend(bodies)
    segments.append(current)
    for body in extra:
        segments.extend(_read(body, info))
    return [seg for seg in segments if seg]


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
        if os.path.basename(word.text) in _CWD_MUTATORS:
            return True
    return False


def decide(command_text: str):
    """Return (verdict, reason) for one Bash command.

    A destructive clean is allowed only when every reducible occurrence sits at
    a provably inert command position, no git global or environment variable
    redirects the target, and the effective working directory is provably the
    hook's own. Every other reducible clean denies."""
    info = {"substitution": False, "subshell": False}
    segments = _read(command_text, info)
    words = _all_words(segments)

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
