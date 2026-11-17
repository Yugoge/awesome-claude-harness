#!/usr/bin/env python3
"""Proves a Bash command read-only, for the orchestrator gate's Bash cap (OB-L03).

``is_read_only(command)`` is True only when every simple command in ``command``
is a program of PROGRAMS whose arguments pass that program's check, so the
command can neither run code of its choosing nor write a file. Everything else
is False: a text the parser cannot read, a compound (subshell, group, if,
loop, function), a background ``&``, an assignment prefix (``PAGER=``,
``GIT_*=``, ``PATH=``), any substitution, process substitution, parameter or
arithmetic expansion, a word that still spells one after quote removal
(bash's ``test -v 'a[$(cmd)]'`` runs cmd), a heredoc or here-string, any redirection but output
thrown into /dev/null or one standard stream duplicated onto the other, a
command named by a path, and a pipeline with any stage outside PROGRAMS. Silence
never proves: a program, option or form not listed here is not read-only. A
check reads options as GNU getopt does (an option after an operand still
parses, a long option may be abbreviated or take ``=``), and one that admits no
operand refuses ``--``, after which a dash-named word is an operand (GNU
``uniq -- -in -out`` writes ``-out``). A mini-language is admitted only in a
small grammar matched over the whole text, never split on a separator first:
a sed script (each -e word on its own) is commands p d = q Q and s/// with the
default / delimiter, line-number, $ or /RE/ addresses, and regex text without
``[`` ``{`` ``}`` ``#``, a newline or an escape other than a few literal ones
(GNU sed reads ``/[]/p;s/]/e cmd #/`` as one address and an ``e`` command); an
awk program may not spell system, a pipe, a redirection, getline, close,
fflush, ``@``, ``/inet``, ARGV or ARGC anywhere in its text.

The verdict reads the shell_parse tree (``parse``, ``walk``, ``resolve``,
``write_targets``) and is cross-checked against the independent byte scan of
bash_active_syntax_census: a command either reader finds active syntax in is
not read-only. Nothing here executes, expands or evaluates the text it reads,
and no function raises.

What the command text cannot show stays outside the proof: the user's own shell
aliases and PATH, a tool's own configuration file (RIPGREP_CONFIG_PATH), and
repository configuration git reads (diff.external, textconv drivers,
core.fsmonitor). The text cannot set any of them for itself:
an assignment prefix, ``git -c``, ``--exec-path``, ``--ext-diff`` and
``--textconv`` are refused, and planting such configuration takes a write that
is itself a counted call.
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bash_active_syntax_census as census_mod  # noqa: E402
from shell_parse import (  # noqa: E402
    SimpleCommand, active_parts, parse, resolve, walk, write_targets)
sys.path.pop(0)

MAX_COMMAND_LEN = 8192

# The census kinds that mean code or data the text does not show.
_ACTIVE_KINDS = frozenset({"substitution", "procsub", "heredoc", "param_reexpand"})

_SEPARATORS = frozenset({";", "&&", "||", "\n", ""})

DEV_NULL = "/dev/null"


# ---------------------------------------------------------------------------
# Option helpers
# ---------------------------------------------------------------------------

def _long_name(word: str) -> str:
    return word.split("=", 1)[0]


def _long_hits(word: str, forbidden) -> bool:
    """True when ``word`` is a long option naming, or abbreviating, one of
    ``forbidden`` (git's parse-options and GNU getopt accept any unambiguous
    prefix: ``--outp=x`` is ``--output=x``)."""
    if not word.startswith("--") or word == "--":
        return False
    name = _long_name(word)
    return any(f == name or f.startswith(name) for f in forbidden)


def _short_cluster(word: str) -> bool:
    return word.startswith("-") and not word.startswith("--") and len(word) > 1


def _cluster_has(word: str, letters: str) -> bool:
    return _short_cluster(word) and any(ch in word[1:] for ch in letters)


# ---------------------------------------------------------------------------
# Per-program checks: each takes the argument values (never None) and says
# whether they keep the program read-only.
# ---------------------------------------------------------------------------

def _any_args(_args) -> bool:
    return True


def _printf(args) -> bool:
    # printf -v NAME assigns a shell variable (PATH, say) a later command reads.
    return not any(a.startswith("-v") for a in args)


def _test(args) -> bool:
    # bash's test -v / -R read their operand as a variable name whose subscript
    # is evaluated arithmetically, running a $(...) inside it even when the
    # word was single-quoted: test -v 'a[$(cmd)]' runs cmd.
    return not any(a in ("-v", "-R") for a in args)


def _cd(args) -> bool:
    operands = [a for a in args if a not in ("-L", "-P")]
    return len(operands) <= 1 and all(not a.startswith("-") or a == "-" for a in operands)


_FIND_FORBIDDEN = ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf",
                   "-fls")


def _find(args) -> bool:
    return not any(a.startswith(f) for a in args for f in _FIND_FORBIDDEN)


_RG_FORBIDDEN = ("--pre", "--pre-glob", "--hostname-bin", "--search-zip")


def _rg(args) -> bool:
    return not any(_long_hits(a, _RG_FORBIDDEN) or _cluster_has(a, "z") for a in args)


_SORT_FORBIDDEN = ("--output", "--compress-program")


def _sort(args) -> bool:
    return not any(_long_hits(a, _SORT_FORBIDDEN) or _cluster_has(a, "o") for a in args)


def _uniq(args) -> bool:
    # uniq IN OUT writes OUT: no operand at all, so only stdin to stdout. A bare
    # `--` ends option parsing and makes every later word an operand, dash-named
    # ones included (uniq -- -in -out writes -out), so it is refused too.
    return all(a.startswith("-") and a not in ("-", "--") for a in args)


# A sed script is admitted only when this small grammar matches the WHOLE of
# it: commands p d = q Q and s///, each with an optional address (a line
# number, $, or /RE/ with the I or M modifier), an optional range and !, and
# separated by ;. The s command takes the flags g p i I m M and a count, never
# e w W. A regex or replacement may hold only letters, digits, space and
# _ . , : = + * ? ^ $ ( ) | & % @ -, and a backslash only before one of
# . / \ * ^ $ ( ) & + ? | or a digit 1-9. Everything else is refused because
# GNU sed reads it differently from a naive split: [ (a / or ; inside a
# bracket expression is literal, so /[]/p;s/]/e cmd #/ is one address and an e
# command), { } (blocks), # (comments, #n), a newline, other delimiters
# (s|a|b|, \cREc), the escapes \n \c \d \o \x \w \L \U and a trailing \
# (which joins the next -e word, as GNU sed joins -e words with newlines).
_SED_TEXT = r"(?:[A-Za-z0-9 _.,:=+*?^$()|&%@-]|\\[./\\*^$()&+?|1-9])*"
_SED_ADDR = r"(?:[0-9]+|\$|/%s/[IM]{0,2})" % _SED_TEXT
_SED_COMMAND = (r" *(?:%s(?:,%s)?)? *!? *(?:[pd=]|[qQ][0-9]*|s/%s/%s/[gpiImM0-9]*) *"
                % (_SED_ADDR, _SED_ADDR, _SED_TEXT, _SED_TEXT))
_SED_SCRIPT_RE = re.compile(r"%s(?:;%s)*;? *" % (_SED_COMMAND, _SED_COMMAND))


def _sed_script_ok(script: str) -> bool:
    """True only when the grammar above matches the whole script (one -e
    word, --expression= value or script operand)."""
    return bool(script) and _SED_SCRIPT_RE.fullmatch(script) is not None


_SED_LONG_FLAGS = frozenset({"--quiet", "--silent", "--regexp-extended", "--separate", "--unbuffered",
                             "--null-data", "--posix", "--sandbox", "--debug"})


def _sed(args) -> bool:
    scripts, operands = [], []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            operands.extend(args[i + 1:])
            break
        if a.startswith("--"):
            if a.startswith("--expression="):
                scripts.append(a.split("=", 1)[1])
            elif a not in _SED_LONG_FLAGS:
                return False  # --in-place, --file, an abbreviation of either, ...
        elif _short_cluster(a):
            body = a[1:]
            for k, ch in enumerate(body):
                if ch == "e":
                    rest = body[k + 1:]
                    if rest:
                        scripts.append(rest)
                    elif i + 1 < len(args):
                        i += 1
                        scripts.append(args[i])
                    else:
                        return False
                    break
                if ch not in "nErsuz":
                    return False  # -i, -f, -l, -s with a value, ...
        else:
            operands.append(a)
        i += 1
    if not scripts:
        if not operands:
            return False
        scripts.append(operands.pop(0))
    return all(_sed_script_ok(s) for s in scripts)


# Words an awk program may not hold: running a command, writing a file or a
# pipe, reading one by name, loading code. The match is on the raw program
# text, so a word inside a string, regex literal or comment counts too (awk's
# tokenizer can only see less than this scan does: a backslash-newline splits
# an identifier, it never joins one). ARGV and ARGC are refused because
# assigning them names input files the text need not spell: an element built
# as "/in" "et/tcp/0/host/80" is a main-input operand, and gawk io.c opens it
# through nextfile() -> devopen() -> inetfile() -> socketopen(), a TCP
# connection; devopen() checks neither the mode nor |& (only --traditional
# skips it), so getline < "/inet/..." connects the same way, through
# redirect_string(). Read in the gawk 5.2.2, 5.3.0, 5.3.2 and 5.4.2 sources,
# not run; the manual names |& as the use of these files, not the only one.
_AWK_FORBIDDEN_TEXT = ("system", "|", ">", "getline", "@", "close", "fflush", "/inet", "ARGV", "ARGC")


def _awk(args) -> bool:
    program = None
    i = 0
    while i < len(args):
        a = args[i]
        if program is None:
            if a == "--":
                i += 1
                if i < len(args):
                    program = args[i]
                i += 1
                continue
            if a in ("-F", "-v"):
                i += 2
                continue
            if a.startswith("-F") or a.startswith("-v"):
                i += 1
                continue
            if a.startswith("-"):
                return False  # -f progfile, -i/-l (load code), -E, --exec, ...
            program = a
        elif a.startswith("/inet") or a.startswith("-"):
            return False
        i += 1
    if program is None or i > len(args):
        return False
    return not any(t in program for t in _AWK_FORBIDDEN_TEXT)


# --- git -------------------------------------------------------------------

_GIT_GLOBAL_FLAGS = frozenset({
    "-P", "--no-pager", "--no-optional-locks", "--literal-pathspecs", "--no-literal-pathspecs",
    "--glob-pathspecs", "--noglob-pathspecs", "--icase-pathspecs", "--no-replace-objects", "--no-advice",
})

# Long options that write a file, run a program, or start a pager, refused (or
# any abbreviation of them) on every git subcommand.
_GIT_FORBIDDEN = ("--output", "--output-directory", "--ext-diff", "--textconv", "--open-files-in-pager",
                  "--filters", "--exec", "--upload-pack", "--receive-pack", "--edit", "--paginate")

# Builtin subcommands that only read (git never lets an alias shadow a builtin).
_GIT_READ = frozenset({
    "status", "log", "show", "diff", "rev-parse", "ls-files", "ls-tree", "blame", "describe", "shortlog",
    "rev-list", "grep", "merge-base", "diff-tree", "diff-index", "diff-files", "show-ref", "for-each-ref",
    "cat-file", "count-objects", "check-ignore", "name-rev", "whatchanged",
    "branch", "tag", "remote", "config", "stash", "worktree", "reflog",
})

_BRANCH_FLAGS = frozenset({"-a", "-r", "-v", "-vv", "--all", "--remotes", "--verbose", "--show-current",
                           "--no-color", "--color", "--no-column"})
_BRANCH_VALUED = ("--format=", "--sort=", "--contains=", "--no-contains=", "--merged=", "--no-merged=",
                  "--points-at=")
_TAG_FLAGS = frozenset({"--no-color", "--color", "--no-column"})
_TAG_VALUED = ("--format=", "--sort=", "--contains=", "--no-contains=", "--merged=", "--no-merged=",
               "--points-at=")
_CONFIG_FLAGS = frozenset({"--list", "-l", "--get", "--get-all", "--get-regexp", "--show-origin",
                           "--show-scope", "--global", "--local", "--system", "--worktree", "--null", "-z",
                           "--name-only", "--includes", "--no-includes", "--bool", "--int", "--path"})
_CONFIG_READ = frozenset({"--list", "-l", "--get", "--get-all", "--get-regexp"})


def _listing(args, flags, valued, list_flags, count_flag=False) -> bool:
    """branch / tag in their listing form: known flags only, a pattern operand
    only after a listing flag (an operand alone creates the branch or tag)."""
    listing = False
    operands = 0
    for a in args:
        if a in list_flags:
            listing = True
        elif a in flags or any(a.startswith(v) for v in valued):
            continue
        elif count_flag and re.fullmatch(r"-n\d*", a):
            continue
        elif a.startswith("-"):
            return False
        else:
            operands += 1
    return operands == 0 or listing


def _git_sub(sub: str, args) -> bool:
    if any(_long_hits(a, _GIT_FORBIDDEN) for a in args):
        return False
    if sub == "grep" and any(_cluster_has(a, "O") for a in args):
        return False  # -O[<pager>] opens the matching files in a pager
    positional = [a for a in args if not a.startswith("-")]
    if sub == "branch":
        # Only --list: before git 2.23 `git branch -l NAME` created NAME.
        return _listing(args, _BRANCH_FLAGS, _BRANCH_VALUED, ("--list",))
    if sub == "tag":
        return _listing(args, _TAG_FLAGS, _TAG_VALUED, ("--list", "-l"), count_flag=True)
    if sub == "remote":
        if positional and positional[0] == "get-url":
            return all(a in ("--all", "--push") for a in args if a.startswith("-")) and len(positional) == 2
        return not positional and all(a in ("-v", "--verbose") for a in args)
    if sub == "config":
        flags = [a for a in args if a.startswith("-")]
        if not all(a in _CONFIG_FLAGS or a.startswith("--type=") for a in flags):
            return False  # --file, --blob, --add, --unset, --edit, ...
        if positional and positional[0] in ("get", "list"):
            return len(positional) <= 3
        return any(a in _CONFIG_READ for a in flags) and len(positional) <= 2
    if sub == "stash":
        return bool(positional) and args[0] in ("list", "show")
    if sub == "worktree":
        return bool(args) and args[0] == "list"
    if sub == "reflog":
        return not positional or positional[0] == "show"
    return True


def _git(args) -> bool:
    i = 0
    while i < len(args):
        a = args[i]
        if a == "-C":
            if i + 1 >= len(args):
                return False
            i += 2
            continue
        if a in _GIT_GLOBAL_FLAGS:
            i += 1
            continue
        if a.startswith("-"):
            return False  # -c, --exec-path, --git-dir, --work-tree, -p, --help, ...
        break
    if i >= len(args) or args[i] not in _GIT_READ:
        return False
    return _git_sub(args[i], args[i + 1:])


# Programs whose every option only reads and prints: their arguments are not
# checked, and a glob or brace expansion among them is fine (whatever file
# names it expands to, no option of theirs runs or writes anything).
_ANY_ARGS = frozenset({
    "ls", "cat", "head", "tail", "wc", "grep", "egrep", "fgrep", "nl", "tac", "stat", "du", "df", "pwd",
    "echo", "true", "false", "basename", "dirname", "realpath", "readlink", "cut", "tr", "comm",
    "paste", "column", "rev", "fold", "expand", "unexpand", "diff", "cmp", "md5sum", "sha1sum",
    "sha256sum", "sha512sum", "cksum", "uname", "whoami", "id", "which",
})

# Programs with a per-argument check; their arguments must be static words.
_CHECKED = {
    "printf": _printf,
    "test": _test,
    "[": _test,
    "cd": _cd,
    "find": _find,
    "rg": _rg,
    "sort": _sort,
    "uniq": _uniq,
    "sed": _sed,
    "awk": _awk,
    "gawk": _awk,
    "mawk": _awk,
    "git": _git,
}

PROGRAMS = _ANY_ARGS | frozenset(_CHECKED)


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------

def _redirect_ok(r) -> bool:
    """Output thrown into /dev/null, or stdout and stderr duplicated onto each other."""
    if r.fd_var is not None or r.hd is not None or r.target is None:
        return False
    if r.op == ">&":
        return r.fd in (1, 2) and r.dup in (1, 2) and not r.close
    if r.op in (">", ">>", ">|", "&>", "&>>"):
        if r.fd not in (None, 1, 2):
            return False
        return all(p.kind == "lit" for p in r.target.parts) and r.target.value() == DEV_NULL
    return False


# Text bash expands when it meets it again inside an arithmetic context (an
# array subscript, an integer operand), quoted or not.
_CODE_MARKS = ("$(", "`", "${", "$[")


def _holds_code(word) -> bool:
    """True when a word, after quote removal, still spells a substitution or an
    expansion: a later arithmetic reading of it (test -v 'a[$(cmd)]', an
    integer operand, a printf %d argument) would run or expand it. Such text is
    never needed to read the tree, so every program counts it."""
    text = word.value()
    if text is None:
        text = word.raw.text
    return any(m in text for m in _CODE_MARKS)


def _command_ok(cmd) -> bool:
    if not isinstance(cmd, SimpleCommand) or cmd.assignments or not cmd.words:
        return False
    if not all(_redirect_ok(r) for r in cmd.redirects):
        return False
    head = cmd.words[0]
    name = head.value()
    if name is None or any(p.kind != "lit" for p in head.parts) or "/" in name or name not in PROGRAMS:
        return False
    res = resolve(cmd)
    if res.name != name or res.payload is not None or res.unresolved is not None or res.wrappers:
        return False
    if any(_holds_code(w) for w in cmd.words):
        return False
    rest = cmd.words[1:]
    if name in _ANY_ARGS:
        return all(p.kind in ("lit", "glob", "brace") for w in rest for p in active_parts(w.parts))
    if any(p.kind != "lit" for w in rest for p in active_parts(w.parts)):
        return False
    args = [w.value() for w in rest]
    if any(a is None for a in args):
        return False
    return _CHECKED[name](args)


def is_read_only(command) -> bool:
    """True only when ``command`` provably neither runs code of its choosing
    nor writes a file (see the module docstring). Never raises."""
    try:
        return _is_read_only(command)
    except Exception:
        return False


def _is_read_only(command) -> bool:
    if not isinstance(command, str) or not command.strip() or len(command) > MAX_COMMAND_LEN:
        return False
    scan = census_mod.census(command)
    if scan.get("fatal") or any(o.get("kind") in _ACTIVE_KINDS for o in scan.get("obligations", ())):
        return False
    script = parse(command)
    if script.errors() or not script.items:
        return False
    stages = 0
    for pipeline, sep in script.items:
        if sep not in _SEPARATORS:
            return False  # a background `&`
        for stage in pipeline.stages:
            if not _command_ok(stage):
                return False
            stages += 1
    sites = list(walk(script))
    if len(sites) != stages or any(s.context != ("top",) or s.dynamic or s.templated for s in sites):
        return False
    return all(t.path == DEV_NULL and t.mechanism.startswith("redirect") for t in write_targets(script))
