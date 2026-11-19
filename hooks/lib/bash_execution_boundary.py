#!/usr/bin/env python3
"""Fail-closed execution-boundary analyzer for the filesystem-removal policy.

THE ALGEBRA.  Every execution-bearing
boundary in a command ends in exactly one of:

    PROVEN_INERT         nothing executes here, or what executes is a named
                         program that is not a filesystem-removal front end
    PROVEN_SAFE_REMOVAL  a removal that is provably NOT a filesystem removal
                         (git rm --cached, docker container/image/compose rm),
                         or a recoverable non-forced git rm (prove_git_rm)
    FORBIDDEN_REMOVAL    a filesystem removal front end executes
    UNRESOLVED           the analyzer could not PROVE which of the above holds

Precedence: FORBIDDEN_REMOVAL > UNRESOLVED > PROVEN_SAFE_REMOVAL > PROVEN_INERT.
The command is authorized by the removal policy only when every boundary is
terminal-safe.  There is deliberately NO code path from "no adapter matched",
"parser gave up", "unsupported syntax", or "analyzer crashed" to *allow* — that
inversion is the whole point.  The analyzer enumerates what is PROVABLY SAFE
and denies on silence; it never enumerates what is FORBIDDEN and allows on
silence.  Consequently every lookup table below may only ever move a
boundary toward SAFE: absence from a table falls to UNRESOLVED, never to allow.

Two failure classes are distinguished so the deny surface stays proportionate:

  * STRUCTURAL failures (lex/parse error, undischarged census obligation,
    redirect with no target, an option whose required value is missing, a
    command head that cannot be resolved to a literal name) are UNRESOLVED
    unconditionally.  You cannot authorize what you cannot even identify.
    The one reading they do not bind is the DATA READING of a value word
    (``payload_is_not_provably_inert``), which asks a narrower question: could
    any shell reading of this argument put a removal front end in command
    position?  There a static glob or brace head PROVEN unable to produce a
    removal front end's name (`https://h/a?x=1&y=2`, `count(*)`) is an
    unmodelled program whose argv is still read, and text the lexer cannot
    read counts only when it names, patterns or (above the failing line)
    assembles a removal.  A parse failure alone is not a removal reference.
  * REMOVAL-SCOPED failures (an unknown option inside a known dispatcher, an
    unknown git subcommand, interpreter code whose removal token cannot be
    proven inert) are UNRESOLVED only when the command carries removal
    evidence.  Without such evidence there is nothing for the removal policy
    to authorize, so the boundary is inert for THIS policy's purposes.

Completeness obligation: ``bash_active_syntax_census`` independently
scans the raw bytes and lists every active-syntax site it can see.  This module
must report that it consumed each one.  Any obligation left undischarged is a
structural UNRESOLVED.  The census is never imported into the semantic
decision; it is only compared against it.

ZERO EXECUTION: nothing in this module executes, expands, evals, or otherwise
runs the text it analyzes.  Command text is data (prove_git_rm runs git itself).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bash_active_syntax_census as census_mod  # noqa: E402  (path set above)
from shell_parse import (  # noqa: E402,F401  (the lexer and option reader)
    AWK_NAMES, AWK_SOURCE_OPTS, GREP_CORE_VALUE_OPTS, GREP_VALUE_OPTS, AWK_VALUE_OPTS, FIND_EXEC_ENDS, WRAPPERS, LexError, Redir, Src, Word, _find_ansi_end, _lex_backtick, _lex_dollar,
    CD_TARGET_BUILTINS, COMMAND_OPTS, COMMAND_PREFIX_WORDS, ENV_SPLIT_OPTS, EXEC_ASSIGNMENT_VARS,
    OPTION_SIGNS, PARALLEL_SEPARATORS, PEEL, PIPE_OPS, REEXPAND_OPS, SU_COMMAND_OPTS, XARGS_SPEC,
    _SSH_SPEC, _SU_SPEC, _match_pair, _resolve_long, _spec, ansi_decode, lex, split_opts, src_concat)
from shell_parse import GIT_GLOBAL_FLAGS, GIT_GLOBAL_VALUE_OPTS, GIT_LOCATION_OPTS, GIT_PATHSPEC_FLAGS  # noqa: E402
from shell_parse import GIT_LONG_OPTIONS  # noqa: E402
from git_facts import GIT_SHELL_PAYLOAD_SUBCOMMANDS  # noqa: E402

SCHEMA = "bash-execution-boundary.v1"

PROVEN_INERT = "PROVEN_INERT"
PROVEN_SAFE_REMOVAL = "PROVEN_SAFE_REMOVAL"
FORBIDDEN_REMOVAL = "FORBIDDEN_REMOVAL"
UNRESOLVED = "UNRESOLVED"

_RANK = {PROVEN_INERT: 0, PROVEN_SAFE_REMOVAL: 1, UNRESOLVED: 2, FORBIDDEN_REMOVAL: 3}
_TERMINAL_SAFE = (PROVEN_INERT, PROVEN_SAFE_REMOVAL)

MAX_DEPTH = 24
MAX_BOUNDARIES = 400

# Filesystem-removal front ends. This set defines the POLICY SCOPE (what is
# forbidden), not the authorization mechanism. Widening it widens the deny
# surface. The one definition of "removal binary" is the census's
# REMOVAL_BINARIES (the census, an independent backstop, imports nothing from
# here; this analyzer reads its set): the degraded fallback in
# hooks/pretool-bash-safety.sh names the same four, so the primary path can
# never be laxer than the fallback.
REMOVAL_EXES = frozenset(census_mod.REMOVAL_BINARIES)

# Removal evidence gates the REMOVAL-SCOPED failure class only.
_REMOVAL_EVIDENCE_RE = re.compile(
    r"(?:^|[^A-Za-z0-9_])(%s)(?![A-Za-z0-9_])" % "|".join(map(re.escape, sorted(REMOVAL_EXES))))

# Library-level removal in interpreter payloads. These carry NO rm/unlink/
# shred/srm token, so _REMOVAL_EVIDENCE_RE is structurally blind to them; this
# set keeps `python3 -c 'shutil.rmtree(p)'` from reading as "no removal token
# -> inert".
_API_REMOVAL_RE = re.compile(
    r"(?:^|[^A-Za-z0-9_])"
    r"(rmtree|removedirs|rimraf|unlinkSync|rmSync|rmdirSync|remove_tree"
    r"|rm_rf|rm_r|rmdir|removeSync|remove)"
    r"(?![A-Za-z0-9_])")
_API_DELETE_RE = re.compile(
    r"(?:^|[^A-Za-z0-9_])"
    r"(?:File|Files|Dir|FileUtils|Path|os|fs|shutil|pathlib|fse|fsp)"
    r"\s*\.\s*(delete|deleteIfExists|unlink|remove|removeSync|rm)"
    r"(?![A-Za-z0-9_])")

# Runtime name resolution inside interpreter inline code. These constructs
# choose their target while running, so no amount of NAME reading can prove the
# payload inert (`getattr(os,"remove")(p)`).
_DYNAMIC_ACCESS_RE = re.compile(
    r"(?:^|[^A-Za-z0-9_.])"
    r"(getattr|setattr|__getattribute__|__dict__|__import__|globals|locals"
    r"|vars|importlib|instance_eval|const_get|public_send|method_missing"
    r"|Function|eval|exec)"
    r"(?![A-Za-z0-9_])"
    r"|\[\s*[\"'](?:rm|remove|unlink|rmdir|rmtree|removedirs|rm_rf|rm_r"
    r"|unlinkSync|rmSync|rmdirSync|delete|deleteIfExists|removeSync|rimraf)"
    r"[\"']\s*\]")

# Library-removal names that are UNAMBIGUOUSLY api identifiers. `remove` and
# `rmdir` are deliberately absent: they are also ordinary subcommands and file
# names (`apt remove pkg`, `git remote remove origin`), and a prefixed use such
# as `os.remove` is already covered by _API_DELETE_RE.
_API_REMOVAL_UNAMBIGUOUS_RE = re.compile(
    r"(?:^|[^A-Za-z0-9_])"
    r"(rmtree|rimraf|unlinkSync|rmSync|rmdirSync|removedirs|remove_tree"
    r"|rm_rf|rm_r|removeSync)"
    r"(?![A-Za-z0-9_])")

# An API removal is an EXPRESSION, never a bare word. Requiring call or
# attribute syntax is what keeps `apt-get remove pkg` and a file named
# `rmtree.txt` out of the scan while `require("fs").rmSync(p)` stays in.
_EXPRESSION_SYNTAX_RE = re.compile(r"[.(\[]")


def _expression_names_removal_api(text):
    """The library-removal name in ``text``, when ``text`` is an expression.

    One shared reading of "this word performs a removal through a library",
    used both by the named-interpreter payload classifier and by the leaf that
    handles an UNNAMED head, so an interpreter this module has not enumerated
    cannot be laxer than one it has.
    """
    if not text or _EXPRESSION_SYNTAX_RE.search(text) is None:
        return None
    for rx in (_API_REMOVAL_UNAMBIGUOUS_RE, _API_DELETE_RE):
        m = rx.search(text)
        if m is not None and _enclosing_call(text, m.start(1)) not in OUTPUT_SINKS:
            return m.group(1)
    return None


_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?\+?=")
_ENVVAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Nesting level of ``Analyzer.payload_is_not_provably_inert``. It shares
# MAX_DEPTH with the walk so a payload chain and a substitution chain draw on
# ONE work budget, and exhausting it denies. Module scope because the predicate
# is reached from static call sites; the analyzer is a single-shot CLI.
_PAYLOAD_NESTING = [0]



def _static_prefix(w):
    """The leading statically-known characters of a word, or "" if it has none."""
    out = []
    for kind, s, _ in w.segs:
        if kind == "lit":
            out.append(s.text)
        elif kind == "ansi":
            out.append(ansi_decode(s.text))
        else:
            break
    return "".join(out)


def _strip_outer_quotes(text):
    t = text.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "'\"":
        return t[1:-1]
    if len(t) >= 3 and t[:2] == "$'" and t[-1] == "'":
        return ansi_decode(t[2:-1])
    return t


class Env:
    """Name bindings introduced by the command itself (hash -p, alias)."""

    __slots__ = ("hashed", "aliases")

    def __init__(self, hashed=None, aliases=None):
        self.hashed = dict(hashed or {})
        self.aliases = dict(aliases or {})


# ---------------------------------------------------------------------------
# Option-table machinery
#
# EVERY table below may only move a boundary toward PROVEN_SAFE. An option that
# is absent from a table yields UNRESOLVED, never allow. That one-directional
# property keeps an unenumerated option from ever meaning allow.
# ---------------------------------------------------------------------------

def _resolve_ic_long(name, model):
    """Resolve a long option against a declared-inert consumer's option model.

    Unambiguous GNU-style abbreviations resolve (`--compress-prog` is
    `--compress-program`, and must keep its exec classification). Anything that
    does not resolve returns None and is handled as an UNDECLARED option, whose
    value position denies a removal reference.
    """
    known = model["bool"] | model["exec"] | model["val"]
    if name in known:
        return name
    cands = [o for o in known if o.startswith("--") and o.startswith(name)]
    if len(cands) == 1:
        return cands[0]
    return None


# ---------------------------------------------------------------------------
# Affirmative-inertness proof set.
#
# READ THE DIRECTION OF THIS TABLE BEFORE EDITING IT. Every one of these
# programs is proven NOT to be an execution boundary: it consumes its argv as
# text, path, or name-lookup DATA and never execs an argv-derived program.
# Membership can therefore only ever move a boundary toward SAFE.
#
# ABSENCE FROM THIS TABLE DOES NOT ALLOW. An unlisted command head whose argv
# can name a removal front end resolves to UNRESOLVED (Analyzer._terminal_inert)
# — which denies. A table that enumerated the DANGEROUS heads would let an
# unenumerated head mean allow, so every unmodelled exec wrapper (chrt,
# numactl, setpriv, capsh, choom, runcon, cgexec, proxychains, torsocks,
# systemd-inhibit, lxc-execute, ...) would pass a literal `rm <path>` through.
#
# Anything with a documented facility for executing an argv-derived program is
# EXCLUDED on purpose: sed (GNU `e` flag), awk (system()), find/xargs/parallel/
# watch (own handlers), and every shell and interpreter.
#
# POSITION, NOT MEMBERSHIP. Authorizing on membership alone (the head's name
# matched, PROVEN_INERT emitted without looking at the argv) would allow a
# removal front end in option-VALUE position, including the real execution
# facilities `man -P`, `sort --compress-program=`, `split --filter=`, `sdiff
# --diff-program=`, `rg --pre` and `compgen -C`.
#
# Each member is therefore a DECLARED OPTION MODEL, not a bare name:
#   bool  -- options that consume NO value, so the next word is an OPERAND
#   exec  -- options whose value NAMES A PROGRAM; the value is analyzed as
#            shell code, so `man -P less ls` stays safe and `man -P '/bin/rm
#            -rf T' ls` denies
#   val   -- options that consume a DATA value
#   why   -- the written justification of the member's inertness
# Any option NOT declared is INDETERMINATE: its attached remainder and the
# following word are treated as option-value position, which denies a removal
# reference. Only an operand may carry one, which is what keeps `man rm`,
# `which rm` and `grep -F /bin/rm README.md` flowing.
#
def _ic(why, bool_=(), exec_=(), val=()):
    return {"why": why, "bool": set(bool_) | {"--help", "--version"},
            "exec": set(exec_), "val": set(val), "kind": _kind_for_why(why)}


# The PROOF KIND a member's operand position yields. It is carried into the
# boundary reason code so the laxity ledger can be keyed on an
# admissible proof kind instead of on a blanket "the head was in a table".
_KIND_LOOKUP = "operand_of_documentation_or_query_consumer"
_KIND_SEARCH = "search_pattern_operand"
_KIND_OUTPUT = "literal_output_text"
_KIND_RELOCATE = "path_operand_of_non_executing_relocator"


def _kind_for_why(why):
    if why.startswith(_SEARCH_WHY):
        return _KIND_SEARCH
    if why.startswith(_EMIT_WHY):
        return _KIND_OUTPUT
    if why.startswith(_RELOCATE_WHY):
        return _KIND_RELOCATE
    return _KIND_LOOKUP


_LOOKUP_WHY = "name/documentation lookup: argv words are names or paths looked up in a database or PATH; no argv-derived program is executed"
_EMIT_WHY = "text emission: argv words are rendered to stdout as text; no argv-derived program is executed"
_SEARCH_WHY = "text search: argv words are patterns and paths read as data; GNU/BSD search tools expose no argv-derived exec facility"
_READ_WHY = "file read/transform: argv words are paths and format strings; the program never execs an argv-derived command"
_META_WHY = "path/metadata inspection: argv words are paths; results are printed, never executed"
_DIGEST_WHY = "digest computation: argv words are paths hashed as bytes"
_PRED_WHY = "predicate/arithmetic builtin: argv words are operands of a comparison or expression, never a command name"
_RELOCATE_WHY = "file relocation/copy: argv words are source and destination paths renamed or copied as bytes; GNU mv/cp document no argv-derived exec facility"

# DECLARED DATA VALUES (`val`). The ONE option-value position with an
# affirmative proof of data-ness: the program reads this option's value as a
# regex, a pattern file, a count, a glob or a label, and never as a program
# name. A removal-naming token there keeps flowing, because `grep -e rm f.txt`
# is a developer searching for the string "rm"; denying it is a false positive
# on ordinary work.
#
# Every option below is a documented,
# REQUIRED-value data option of the tool that declares it. Nothing that can
# name a program may appear here — those belong in `exec`, and they DENY.
# Optional-value options (`--color[=WHEN]`) are deliberately excluded: their
# arity is ambiguous, and an ambiguous arity is not a proof.
_DATA_VAL_WHY = ("declared data value: read as a regex, a pattern file, a "
                 "count, a glob or a label; never as a program name")

_GREP_CORE_DATA = GREP_CORE_VALUE_OPTS  # shell_parse's grep value options
_GREP_DATA = GREP_VALUE_OPTS

# Long options of a non-removal git subcommand whose value git reads as DATA:
# a regex, an author name, a message, a date. None of them names a program.
# Declaring them is what makes `git log --grep=rm` and `git log --grep rm`
# reach the SAME verdict regardless of attachment.
# TEST/BUILD-RUNNER SELECTOR OPTIONS. A selector is an EXPRESSION matched
# against test names — never a program name — so a developer filtering on "rm"
# (`pytest -k rm`, `go test -run rm`) must keep flowing. These heads remain
# UNMODELLED as execution boundaries: the runner still executes the test code
# its path operands name, and this declaration narrows nothing but the
# selector's own value position.
SELECTOR_DATA_OPTIONS = {
    "pytest": ("-k", "-m", "--deselect", "--ignore", "--ignore-glob"),
    "py.test": ("-k", "-m", "--deselect", "--ignore", "--ignore-glob"),
    "go": ("-run", "-bench", "-skip"),
    "cargo": ("--test", "--bench", "--example"),
    "ctest": ("-R", "-E", "--tests-regex", "--exclude-regex"),
    "tox": ("-e",),
    "nox": ("-s",),
}

GIT_DATA_OPTIONS = frozenset((
    # `-m` is git's own short spelling of `--message`; both spellings must
    # reach the same verdict on the SAME string in the SAME position (`git
    # commit -m 'drop rm usage from the helper'`). Removing that
    # spelling-dependent split is what this table exists for (see the
    # `--grep=rm` / `--grep rm` rationale above).
    "-m",
    "--grep", "--author", "--committer", "--message", "--since", "--until",
    "--before", "--after", "--pretty", "--format", "--date", "--grep-reflog",
    "--exclude", "--glob", "--branches", "--tags", "--remotes",
))

# Subcommands that HAND A COMMAND LINE ONWARD (`git bisect run <cmd>`,
# `git submodule foreach <cmd>`, `git rebase -x <cmd>`, `git difftool -x <cmd>`). For these, NO option may declare its value
# data: otherwise `git bisect run -m '/bin/rm -rf T'` and `git submodule
# foreach --message '/bin/rm -rf T'` would read as PROVEN_INERT. Scoping the
# table by subcommand can only ever remove allows.
GIT_PAYLOAD_FORWARDING_SUBCOMMANDS = GIT_SHELL_PAYLOAD_SUBCOMMANDS

INERT_ARGV_CONSUMERS = {
    # ---- name / documentation lookup -------------------------------------
    "man": _ic(_LOOKUP_WHY + "; EXCEPT the pager/browser options, which name a program",
               bool_=("-a", "-f", "-k", "-w", "-W", "-l", "-c", "-d", "-D", "-u",
                      "-t", "-Z", "-7", "-h", "-V", "-i", "-I", "-g", "--all",
                      "--whatis", "--apropos", "--where", "--where-cat", "--local-file",
                      "--catman", "--debug", "--update", "--troff", "--ditroff",
                      "--ascii", "--global-apropos", "--no-hyphenation",
                      "--no-justification", "--names-only", "--regex", "--wildcard",
                      "--ignore-case", "--match-case", "--no-subpages"),
               exec_=("-P", "--pager", "-H", "--html", "-B", "--browser")),
    "whatis": _ic(_LOOKUP_WHY, bool_=("-d", "-v", "-a", "-l", "-w", "-r", "-e"),
                  exec_=("-P", "--pager")),
    "apropos": _ic(_LOOKUP_WHY, bool_=("-d", "-v", "-a", "-l", "-w", "-r", "-e"),
                   exec_=("-P", "--pager")),
    "info": _ic(_LOOKUP_WHY, bool_=("-a", "--all", "-s", "--subnodes", "-R",
                                    "--raw-escapes", "--vi-keys", "-w", "--where",
                                    "--location", "-x", "--debug")),
    "which": _ic(_LOOKUP_WHY, bool_=("-a", "--all", "-i", "--read-alias",
                                     "--skip-alias", "--read-functions",
                                     "--skip-functions", "--skip-dot", "--skip-tilde",
                                     "--show-dot", "--show-tilde", "--tty-only",
                                     "-v", "-V")),
    "whereis": _ic(_LOOKUP_WHY, bool_=("-b", "-m", "-s", "-u", "-l", "-h", "-V")),
    "type": _ic(_LOOKUP_WHY, bool_=("-a", "-f", "-P", "-p", "-t")),
    "whence": _ic(_LOOKUP_WHY, bool_=("-v", "-p", "-f", "-a")),
    "help": _ic(_LOOKUP_WHY, bool_=("-d", "-m", "-s")),
    "compgen": _ic(_LOOKUP_WHY + "; EXCEPT -C/-F, which name a command or function "
                                 "run to produce completions",
                   bool_=("-a", "-b", "-c", "-d", "-e", "-f", "-g", "-j", "-k",
                          "-s", "-u", "-v"),
                   exec_=("-C", "-F")),
    "pinfo": _ic(_LOOKUP_WHY, bool_=("-r", "-t", "-h", "-v")),
    # ---- text emission -----------------------------------------------------
    "echo": _ic(_EMIT_WHY, bool_=("-n", "-e", "-E")),
    "printf": _ic(_EMIT_WHY, bool_=("-v",)),
    # `print` IS ABSENT ON PURPOSE. The ksh/zsh builtin's option model and
    # text-emission proof do not hold for it: on a Debian host /usr/bin/print
    # is run-mailcap — "execute programs via entries in the mailcap file",
    # with system() on an argv-derived command string. A head that resolves to a PATH binary must
    # not inherit a builtin's proof: the proof was about a different program
    # from the one that would run. Per this table's own exclusion policy,
    # anything with a documented argv-derived execution facility is excluded.
    "yes": _ic(_EMIT_WHY),
    "seq": _ic(_EMIT_WHY, bool_=("-w", "--equal-width")),
    "true": _ic(_PRED_WHY),
    "false": _ic(_PRED_WHY),
    "pwd": _ic(_META_WHY, bool_=("-L", "-P")),
    "date": _ic(_EMIT_WHY, bool_=("-u", "--utc", "--universal", "-R", "--rfc-email",
                                  "-I", "--debug")),
    "sleep": _ic(_EMIT_WHY),
    "id": _ic(_META_WHY, bool_=("-a", "-g", "-G", "-n", "-r", "-u", "-z",
                                "--group", "--groups", "--name", "--real",
                                "--user", "--zero")),
    "whoami": _ic(_META_WHY),
    "hostname": _ic(_META_WHY, bool_=("-a", "-A", "-d", "-f", "-i", "-I", "-s", "-y")),
    "uname": _ic(_META_WHY, bool_=("-a", "-s", "-n", "-r", "-v", "-m", "-p", "-i",
                                   "-o", "--all", "--kernel-name", "--nodename",
                                   "--kernel-release", "--kernel-version",
                                   "--machine", "--processor", "--hardware-platform",
                                   "--operating-system")),
    "tty": _ic(_META_WHY, bool_=("-s", "--silent", "--quiet")),
    "logname": _ic(_META_WHY),
    "arch": _ic(_META_WHY),
    # ---- text search / filter ---------------------------------------------
    "grep": _ic(_SEARCH_WHY, bool_=("-E", "-F", "-G", "-P", "-i", "-v", "-w", "-x",
                                    "-c", "-l", "-L", "-o", "-q", "-s", "-b", "-H",
                                    "-h", "-n", "-r", "-R", "-a", "-I", "-z", "-U",
                                    "-V", "-y", "--extended-regexp", "--fixed-strings",
                                    "--basic-regexp", "--perl-regexp", "--ignore-case",
                                    "--invert-match", "--word-regexp", "--line-regexp",
                                    "--count", "--files-with-matches",
                                    "--files-without-match", "--only-matching",
                                    "--quiet", "--silent", "--no-messages",
                                    "--byte-offset", "--with-filename",
                                    "--no-filename", "--line-number", "--recursive",
                                    "--dereference-recursive", "--text", "--binary",
                                    "--null", "--null-data", "--line-buffered",
                                    "--initial-tab", "-T"),
                    val=_GREP_DATA),
    "egrep": _ic(_SEARCH_WHY, bool_=("-i", "-v", "-w", "-x", "-c", "-l", "-L", "-o",
                                     "-q", "-s", "-b", "-H", "-h", "-n", "-r", "-R",
                                     "-a", "-I", "-z", "-F", "-E", "-P"),
                     val=_GREP_DATA),
    "fgrep": _ic(_SEARCH_WHY, bool_=("-i", "-v", "-w", "-x", "-c", "-l", "-L", "-o",
                                     "-q", "-s", "-b", "-H", "-h", "-n", "-r", "-R",
                                     "-a", "-I", "-z", "-F", "-E", "-P"),
                     val=_GREP_DATA),
    "rgrep": _ic(_SEARCH_WHY, bool_=("-i", "-v", "-w", "-x", "-c", "-l", "-L", "-o",
                                     "-q", "-s", "-b", "-H", "-h", "-n", "-a", "-I",
                                     "-z", "-F", "-E", "-P"),
                     val=_GREP_DATA),
    # `zgrep` IS ABSENT ON PURPOSE — same rule as `print`. It is a
    # /bin/sh script that builds and `eval`s command strings from its own argv
    # (`eval "cat --$optarg"`, `eval "$grep$args"`). The shell-quoting applied
    # before each eval blocks an exploit, but the search-tool proof says the
    # program "expose[s] no argv-derived exec facility", which is false for
    # zgrep. A mitigated facility is still a facility.
    "rg": _ic(_SEARCH_WHY + "; EXCEPT --pre/--hostname-bin, which name a program",
              bool_=("-i", "-v", "-w", "-x", "-c", "-l", "-L", "-o", "-q", "-n", "-N",
                     "-s", "-S", "-F", "-P", "-z", "-a", "-u", "-uu", "-uuu", "-p",
                     "-H", "-I", "-0", "--json", "--files", "--hidden", "--no-ignore",
                     "--vimgrep", "--column", "--line-number", "--no-heading",
                     "--heading", "--smart-case", "--case-sensitive",
                     "--ignore-case", "--fixed-strings", "--multiline",
                     "--word-regexp", "--count", "--count-matches",
                     "--files-with-matches", "--files-without-match",
                     "--only-matching", "--invert-match", "--no-filename",
                     "--with-filename", "--null", "--stats", "--trim",
                     "--debug", "--pcre2", "--text", "--search-zip"),
              exec_=("--pre", "--hostname-bin"),
              val=_GREP_CORE_DATA + ("-g", "--glob", "--iglob", "-t", "--type",
                                     "-T", "--type-not", "--max-depth",
                                     "--max-filesize", "-r", "--replace")),
    "ag": _ic(_SEARCH_WHY + "; EXCEPT --pager, which names a program",
              bool_=("-i", "-v", "-w", "-c", "-l", "-L", "-o", "-Q", "-s", "-S",
                     "-u", "-U", "-a", "-z", "-n", "--nogroup", "--group",
                     "--hidden", "--literal", "--case-sensitive", "--smart-case"),
              exec_=("--pager",),
              val=("-m", "--max-count", "-A", "--after", "-B", "--before",
                   "-C", "--context", "-G", "--file-search-regex", "--ignore")),
    "ack": _ic(_SEARCH_WHY + "; EXCEPT --pager, which names a program",
               bool_=("-i", "-v", "-w", "-c", "-l", "-L", "-o", "-Q", "-a", "-n",
                      "-h", "-H", "--nogroup", "--group", "--literal",
                      "--smart-case", "--nopager"),
               exec_=("--pager",),
               val=("-m", "--max-count", "-A", "--after-context",
                    "-B", "--before-context", "-C", "--context",
                    "--match", "--type", "--ignore-dir", "--ignore-file")),
    "ugrep": _ic(_SEARCH_WHY + "; EXCEPT --filter/--pager, which name a program",
                 bool_=("-i", "-v", "-w", "-x", "-c", "-l", "-L", "-o", "-q", "-n",
                        "-r", "-R", "-a", "-z", "-F", "-E", "-P", "-H", "-h", "-U",
                        "--hidden", "--json", "--line-number", "--no-filename"),
                 exec_=("--filter", "--pager"),
                 val=_GREP_CORE_DATA + ("--include", "--exclude",
                                        "--include-dir", "--exclude-dir")),
    "look": _ic(_SEARCH_WHY, bool_=("-a", "-d", "-f")),
    "strings": _ic(_READ_WHY, bool_=("-a", "-f", "-o", "-p", "-U", "-z", "--all",
                                     "--print-file-name", "--include-all-whitespace")),
    # ---- file relocation / copy -------------------------------------------
    # GNU mv and cp rename or copy the bytes their operands NAME; neither
    # documents any argv-derived execution facility (no --to-command, no -e,
    # no exec hook), so an operand can never become a command head. Membership
    # answers ONLY the removal-policy question — protected-path writes and
    # moves stay under the runtime guard's path-aware model, which denies them
    # independently of this table (the live-hook pins: protected-glob mv/cp
    # BLOCK, unprotected mv/cp ALLOW). Optional-value options
    # (--backup[=CONTROL], --update[=UPDATE], --preserve[=LIST],
    # --reflink[=WHEN], --sparse[=WHEN], --debug) are deliberately undeclared
    # per the val doctrine above: ambiguous arity is not a proof, so their
    # values fall to the opaque-value scan.
    "mv": _ic(_RELOCATE_WHY,
              bool_=("-b", "-f", "-i", "-n", "-T", "-u", "-v", "-Z", "--force",
                     "--interactive", "--no-clobber", "--no-target-directory",
                     "--strip-trailing-slashes", "--verbose"),
              val=("-t", "--target-directory", "-S", "--suffix")),
    "cp": _ic(_RELOCATE_WHY,
              bool_=("-a", "-b", "-d", "-f", "-H", "-i", "-l", "-L", "-n", "-p",
                     "-P", "-r", "-R", "-s", "-T", "-u", "-v", "-x", "-Z",
                     "--archive", "--copy-contents", "--dereference", "--force",
                     "--interactive", "--link", "--no-clobber",
                     "--no-dereference", "--no-target-directory",
                     "--one-file-system", "--parents", "--recursive",
                     "--remove-destination", "--strip-trailing-slashes",
                     "--symbolic-link", "--verbose"),
              val=("-t", "--target-directory", "-S", "--suffix")),
    # ---- file content read / transform ------------------------------------
    "cat": _ic(_READ_WHY, bool_=("-A", "-b", "-e", "-E", "-n", "-s", "-t", "-T",
                                 "-u", "-v", "--number", "--squeeze-blank",
                                 "--show-all", "--show-ends", "--show-tabs",
                                 "--show-nonprinting", "--number-nonblank")),
    "tac": _ic(_READ_WHY, bool_=("-b", "-r", "--before", "--regex")),
    "zcat": _ic(_READ_WHY, bool_=("-f", "-q", "-v", "-r", "-t")),
    "bzcat": _ic(_READ_WHY, bool_=("-f", "-q", "-v", "-s")),
    "xzcat": _ic(_READ_WHY, bool_=("-f", "-q", "-v", "-k")),
    "head": _ic(_READ_WHY, bool_=("-q", "-v", "-z", "--quiet", "--silent",
                                  "--verbose", "--zero-terminated")),
    "tail": _ic(_READ_WHY, bool_=("-f", "-F", "-q", "-v", "-z", "--follow",
                                  "--retry", "--quiet", "--silent", "--verbose",
                                  "--zero-terminated")),
    "nl": _ic(_READ_WHY, bool_=("-p", "--no-renumber")),
    "wc": _ic(_READ_WHY, bool_=("-c", "-l", "-m", "-w", "-L", "--bytes", "--chars",
                                "--lines", "--words", "--max-line-length")),
    "cut": _ic(_READ_WHY, bool_=("-s", "-n", "-z", "--complement", "--only-delimited",
                                 "--zero-terminated")),
    "paste": _ic(_READ_WHY, bool_=("-s", "-z", "--serial", "--zero-terminated")),
    "join": _ic(_READ_WHY, bool_=("-i", "-z", "--ignore-case",
                                  "--zero-terminated", "--check-order",
                                  "--nocheck-order")),
    "sort": _ic(_READ_WHY + "; EXCEPT --compress-program, which names a program run "
                            "on temporary files",
                bool_=("-b", "-c", "-C", "-d", "-f", "-g", "-h", "-i", "-M", "-n",
                       "-r", "-R", "-u", "-z", "-s", "--check", "--dictionary-order",
                       "--ignore-case", "--general-numeric-sort", "--human-numeric-sort",
                       "--month-sort", "--numeric-sort", "--random-sort", "--reverse",
                       "--unique", "--stable", "--zero-terminated",
                       "--ignore-leading-blanks", "--ignore-nonprinting",
                       "--merge", "-m", "--debug", "--parallel"),
                exec_=("--compress-program",)),
    "uniq": _ic(_READ_WHY, bool_=("-c", "-d", "-D", "-i", "-u", "-z", "--count",
                                  "--repeated", "--all-repeated", "--ignore-case",
                                  "--unique", "--zero-terminated")),
    "comm": _ic(_READ_WHY, bool_=("-1", "-2", "-3", "-z", "--check-order",
                                  "--nocheck-order", "--total")),
    "tr": _ic(_READ_WHY, bool_=("-c", "-C", "-d", "-s", "-t", "--complement",
                                "--delete", "--squeeze-repeats", "--truncate-set1")),
    "rev": _ic(_READ_WHY),
    "fold": _ic(_READ_WHY, bool_=("-b", "-s", "--bytes", "--spaces")),
    "fmt": _ic(_READ_WHY, bool_=("-c", "-s", "-t", "-u", "--crown-margin",
                                 "--split-only", "--tagged-paragraph",
                                 "--uniform-spacing")),
    "expand": _ic(_READ_WHY, bool_=("-i", "--initial")),
    "unexpand": _ic(_READ_WHY, bool_=("-a", "--all", "--first-only")),
    "column": _ic(_READ_WHY, bool_=("-t", "-x", "-e", "-J", "-d", "-n", "-L", "-r")),
    "tee": _ic(_READ_WHY, bool_=("-a", "-i", "-p", "--append", "--ignore-interrupts")),
    "split": _ic(_READ_WHY + "; EXCEPT --filter, which is a shell command each output "
                             "chunk is piped into",
                 bool_=("-d", "-u", "-e", "-x", "--numeric-suffixes",
                        "--hex-suffixes", "--elide-empty-files", "--unbuffered",
                        "--verbose"),
                 exec_=("--filter",)),
    "csplit": _ic(_READ_WHY, bool_=("-k", "-s", "-z", "--keep-files", "--quiet",
                                    "--silent", "--elide-empty-files",
                                    "--suppress-matched")),
    "shuf": _ic(_READ_WHY, bool_=("-e", "-r", "-z", "--echo", "--repeat",
                                  "--zero-terminated")),
    "od": _ic(_READ_WHY, bool_=("-a", "-b", "-c", "-d", "-f", "-i", "-l", "-o",
                                "-s", "-x", "-v", "-C", "--canonical")),
    "xxd": _ic(_READ_WHY, bool_=("-b", "-e", "-i", "-p", "-r", "-u", "-C", "-d")),
    "hexdump": _ic(_READ_WHY, bool_=("-b", "-c", "-C", "-d", "-o", "-v", "-x")),
    "base64": _ic(_READ_WHY, bool_=("-d", "-i", "--decode", "--ignore-garbage")),
    "base32": _ic(_READ_WHY, bool_=("-d", "-i", "--decode", "--ignore-garbage")),
    "iconv": _ic(_READ_WHY, bool_=("-c", "-s", "-l", "--list", "--silent")),
    "jq": _ic(_READ_WHY, bool_=("-c", "-n", "-e", "-r", "-j", "-a", "-s", "-S",
                                "-M", "-C", "-R", "-t", "--compact-output",
                                "--null-input", "--exit-status", "--raw-output",
                                "--join-output", "--ascii-output", "--slurp",
                                "--sort-keys", "--monochrome-output",
                                "--color-output", "--raw-input", "--tab")),
    "yq": _ic(_READ_WHY, bool_=("-n", "-e", "-r", "-j", "-y", "-P", "-o", "-i",
                                "--null-input", "--exit-status", "--raw-output",
                                "--tojson", "--yaml-output", "--prettyPrint",
                                "--inplace")),
    "diff": _ic(_READ_WHY, bool_=("-q", "-r", "-u", "-c", "-i", "-w", "-b", "-B",
                                  "-a", "-N", "-p", "-s", "-t", "-T", "-y", "-e",
                                  "-n", "-E", "-Z", "--brief", "--recursive",
                                  "--unified", "--context", "--ignore-case",
                                  "--ignore-all-space", "--ignore-space-change",
                                  "--ignore-blank-lines", "--text", "--new-file",
                                  "--report-identical-files", "--expand-tabs",
                                  "--side-by-side", "--color", "--no-dereference")),
    "diff3": _ic(_READ_WHY + "; EXCEPT --diff-program, which names the diff binary "
                             "diff3 execs",
                 bool_=("-e", "-E", "-x", "-X", "-3", "-A", "-m", "-a", "-T", "-i",
                        "--ed", "--merge", "--text", "--show-all", "--easy-only",
                        "--overlap-only", "--show-overlap", "--initial-tab"),
                 exec_=("--diff-program",)),
    "cmp": _ic(_READ_WHY, bool_=("-b", "-l", "-s", "--print-bytes", "--verbose",
                                 "--quiet", "--silent")),
    "sdiff": _ic(_READ_WHY + "; EXCEPT --diff-program, which names the diff binary "
                             "sdiff execs",
                 bool_=("-l", "-s", "-t", "-a", "-b", "-B", "-E", "-i", "-W", "-d",
                        "--left-column", "--suppress-common-lines", "--expand-tabs",
                        "--text", "--minimal", "--ignore-case",
                        "--ignore-all-space", "--ignore-blank-lines"),
                 exec_=("--diff-program",)),
    "patch": _ic(_READ_WHY, bool_=("-b", "-c", "-e", "-f", "-l", "-n", "-N", "-R",
                                   "-s", "-t", "-T", "-u", "-v", "-E", "-Z", "-g",
                                   "--backup", "--context", "--force", "--batch",
                                   "--normal", "--unified", "--reverse", "--silent",
                                   "--quiet", "--verbose", "--dry-run",
                                   "--ignore-whitespace", "--posix")),
    "less": _ic(_READ_WHY + "; less has no argv option that names a program (its "
                            "input filter is the LESSOPEN environment hook, which "
                            "this analyzer denies as an assignment-prefix vector)",
                bool_=("-N", "-S", "-R", "-r", "-i", "-I", "-F", "-X", "-M", "-m",
                       "-n", "-q", "-Q", "-s", "-u", "-U", "-w", "-G", "-J", "-c",
                       "-C", "-e", "-E", "-f", "-g", "-a", "-B", "-d", "-L", "-+")),
    "more": _ic(_READ_WHY, bool_=("-d", "-f", "-l", "-c", "-p", "-s", "-u")),
    "pr": _ic(_READ_WHY, bool_=("-d", "-f", "-F", "-m", "-r", "-t", "-T", "-v",
                                "-a", "-c", "-j", "-J", "-l", "-s", "-x")),
    # ---- path / metadata inspection ---------------------------------------
    "ls": _ic(_META_WHY, bool_=("-a", "-A", "-b", "-c", "-C", "-d", "-D", "-f", "-F",
                                "-g", "-G", "-h", "-H", "-i", "-k", "-l", "-L", "-m",
                                "-n", "-N", "-o", "-p", "-q", "-Q", "-r", "-R", "-s",
                                "-S", "-t", "-u", "-U", "-v", "-x", "-X", "-1",
                                "--all", "--almost-all", "--human-readable",
                                "--recursive", "--reverse", "--size",
                                "--dereference", "--classify", "--inode",
                                "--numeric-uid-gid", "--no-group",
                                "--directory", "--literal")),
    "dir": _ic(_META_WHY, bool_=("-a", "-A", "-l", "-h", "-R", "-r", "-t", "-S",
                                 "-1", "-d", "-F", "-i")),
    "vdir": _ic(_META_WHY, bool_=("-a", "-A", "-l", "-h", "-R", "-r", "-t", "-S",
                                  "-1", "-d", "-F", "-i")),
    "file": _ic(_META_WHY, bool_=("-b", "-c", "-h", "-i", "-k", "-L", "-N", "-n",
                                  "-p", "-r", "-s", "-v", "-z", "-0", "--brief",
                                  "--mime", "--mime-type", "--mime-encoding",
                                  "--dereference", "--no-pad")),
    "stat": _ic(_META_WHY, bool_=("-L", "-f", "-t", "--dereference",
                                  "--file-system", "--terse")),
    "basename": _ic(_META_WHY, bool_=("-a", "-z", "--multiple", "--zero")),
    "dirname": _ic(_META_WHY, bool_=("-z", "--zero")),
    "readlink": _ic(_META_WHY, bool_=("-f", "-e", "-m", "-n", "-q", "-s", "-v", "-z",
                                      "--canonicalize", "--canonicalize-existing",
                                      "--canonicalize-missing", "--no-newline",
                                      "--silent", "--quiet", "--verbose", "--zero")),
    "realpath": _ic(_META_WHY, bool_=("-e", "-m", "-L", "-P", "-q", "-s", "-z",
                                      "--canonicalize-existing",
                                      "--canonicalize-missing", "--logical",
                                      "--physical", "--quiet", "--strip",
                                      "--no-symlinks", "--zero")),
    "dircolors": _ic(_META_WHY, bool_=("-b", "-c", "-p", "--sh", "--bourne-shell",
                                       "--csh", "--c-shell", "--print-database")),
    "namei": _ic(_META_WHY, bool_=("-l", "-m", "-n", "-o", "-v", "-x", "-Z")),
    "df": _ic(_META_WHY, bool_=("-a", "-h", "-H", "-i", "-k", "-l", "-P", "-T", "-m",
                                "--all", "--human-readable", "--si", "--inodes",
                                "--local", "--portability", "--print-type",
                                "--total", "--sync", "--no-sync")),
    "du": _ic(_META_WHY, bool_=("-a", "-b", "-c", "-D", "-h", "-H", "-k", "-L", "-l",
                                "-m", "-P", "-s", "-S", "-x", "-0", "--all",
                                "--bytes", "--total", "--human-readable",
                                "--summarize", "--separate-dirs",
                                "--one-file-system", "--si", "--apparent-size",
                                "--dereference", "--null")),
    "tree": _ic(_META_WHY, bool_=("-a", "-d", "-f", "-F", "-i", "-l", "-n", "-p",
                                  "-q", "-Q", "-r", "-s", "-t", "-u", "-g", "-D",
                                  "-x", "-C", "-J", "-h", "-v", "--noreport",
                                  "--dirsfirst", "--du")),
    # ---- digests -----------------------------------------------------------
    "md5sum": _ic(_DIGEST_WHY, bool_=("-b", "-c", "-t", "-w", "-z", "--binary",
                                      "--check", "--text", "--warn", "--zero",
                                      "--quiet", "--status", "--strict",
                                      "--ignore-missing", "--tag")),
    "sha1sum": _ic(_DIGEST_WHY, bool_=("-b", "-c", "-t", "-w", "-z", "--binary",
                                       "--check", "--text", "--warn", "--zero",
                                       "--quiet", "--status", "--strict", "--tag")),
    "sha224sum": _ic(_DIGEST_WHY, bool_=("-b", "-c", "-t", "-w", "-z", "--check",
                                         "--tag", "--quiet", "--status")),
    "sha256sum": _ic(_DIGEST_WHY, bool_=("-b", "-c", "-t", "-w", "-z", "--binary",
                                         "--check", "--text", "--warn", "--zero",
                                         "--quiet", "--status", "--strict", "--tag")),
    "sha384sum": _ic(_DIGEST_WHY, bool_=("-b", "-c", "-t", "-w", "-z", "--check",
                                         "--tag", "--quiet", "--status")),
    "sha512sum": _ic(_DIGEST_WHY, bool_=("-b", "-c", "-t", "-w", "-z", "--binary",
                                         "--check", "--text", "--warn", "--zero",
                                         "--quiet", "--status", "--strict", "--tag")),
    "cksum": _ic(_DIGEST_WHY, bool_=("-a", "--raw", "--untagged", "--tag")),
    "sum": _ic(_DIGEST_WHY, bool_=("-r", "-s", "--sysv")),
    "b2sum": _ic(_DIGEST_WHY, bool_=("-b", "-c", "-t", "-w", "-z", "--check",
                                     "--tag", "--quiet", "--status")),
    "shasum": _ic(_DIGEST_WHY, bool_=("-b", "-c", "-t", "-p", "-q", "-s", "-U",
                                      "--binary", "--check", "--text",
                                      "--portable", "--quiet", "--status")),
    # ---- arithmetic / predicate builtins ----------------------------------
    "test": _ic(_PRED_WHY, bool_=("-a", "-b", "-c", "-d", "-e", "-f", "-g", "-h",
                                  "-k", "-L", "-n", "-N", "-o", "-p", "-r", "-s",
                                  "-S", "-t", "-u", "-w", "-x", "-z", "-G", "-O",
                                  "-ef", "-nt", "-ot", "-eq", "-ne", "-lt", "-le",
                                  "-gt", "-ge")),
    "[": _ic(_PRED_WHY, bool_=("-a", "-b", "-c", "-d", "-e", "-f", "-g", "-h",
                               "-k", "-L", "-n", "-N", "-o", "-p", "-r", "-s",
                               "-S", "-t", "-u", "-w", "-x", "-z", "-G", "-O",
                               "-ef", "-nt", "-ot", "-eq", "-ne", "-lt", "-le",
                               "-gt", "-ge")),
    "expr": _ic(_PRED_WHY),
    "let": _ic(_PRED_WHY),
}

SHELLS = {"bash", "sh", "dash", "zsh", "ksh", "ksh93", "mksh", "ash", "rbash", "bash5"}
# The shells whose grammar has the `[[ ... ]]` conditional compound command.
# sh, dash and ash have none: there `[[` is an ordinary command name, so a
# `&&` or `||` after it IS a command boundary and is read as one.
COND_SHELLS = {"bash", "zsh", "ksh", "ksh93", "mksh", "rbash", "bash5"}
# The unquoted reserved words that may precede `[[` while it is still the first
# word of a command (`if [[`, `! [[`, `while ! [[`, `{ [[` ...). Any other word,
# an assignment or a redirection before it makes `[[` an argument or a command
# name, and then nothing inside it is a conditional expression.
COND_OPENER_PREFIX = COMMAND_PREFIX_WORDS
# Builtins that can stop `[[` from being read as the reserved word on a later
# line: an alias named `[[` (or `if`, `while` ...) turns it into a simple
# command, and zsh's `disable -r` switches the reserved word off.
COND_DISABLING_BUILTINS = frozenset(("alias", "disable"))
# A shell's script operand in the quoted CLAUDE_HOME channel, each component plain: a named file.
CLAUDE_HOME_FILE = re.compile(r'"\$\{CLAUDE_HOME:-\$HOME/\.claude\}(?:/[A-Za-z0-9_-][A-Za-z0-9_.-]*)+"')

SHELL_SHORT_BOOL = set("abBCefhHiklmnpPrstTuvxD")
SHELL_LONG_BOOL = {"--posix", "--norc", "--noprofile", "--login", "--restricted",
                   "--verbose", "--debugger", "--dump-strings", "--dump-po-strings",
                   "--help", "--version", "--noediting", "--protected", "--pretty-print"}
SHELL_LONG_VAL = {"--rcfile", "--init-file"}

INTERPRETERS = {
    "python": ("-c",), "python2": ("-c",), "python3": ("-c",),
    "perl": ("-e", "-E"), "ruby": ("-e",), "node": ("-e", "--eval", "-p", "--print"),
    "nodejs": ("-e", "--eval", "-p"), "php": ("-r",), "lua": ("-e",),
    "lua5.1": ("-e",), "lua5.3": ("-e",), "deno": ("eval",),
}
AWKS = set(AWK_NAMES) | {"busybox-awk"}  # and busybox's applet, as this reader names it

# Calls that only render text. A removal token reaching one of these and
# nothing else is PROVEN inert; anything else is not proven and denies.
OUTPUT_SINKS = {
    "print", "println", "printf", "puts", "p", "say", "echo", "write", "warn",
    "console.log", "console.error", "console.info", "console.warn", "console.debug",
    "sys.stdout.write", "sys.stderr.write", "io.write", "print_r", "var_dump",
    "STDOUT.puts", "STDERR.puts", "process.stdout.write",
}

GIT_GLOBAL = _spec(GIT_GLOBAL_FLAGS, GIT_GLOBAL_VALUE_OPTS)

# git rm's options: its long ones as shell_parse lists them, and the short ones.
GIT_RM = _spec(
    ("-n", "-r", "-f", "-q") + tuple(o for o in GIT_LONG_OPTIONS["rm"] if o != "--pathspec-from-file"),
    ("--pathspec-from-file",))
# A non-forced `git rm` is recoverable: git refuses a file that differs from HEAD or the index, and a
# removed clean file comes back with `git checkout <sha>^ -- <path>`. It is allowed only when the walk
# can hand prove_git_rm the repository it runs in: written at the top level as its command's own head
# (no wrapper, nested shell or assignment), only these git options before `rm`, literal pathspecs, and
# no shell state a later command inherits other than `cd`/`pushd` to a literal absolute directory.
_GIT_RM_LOCATION_OPTS = GIT_LOCATION_OPTS
_GIT_RM_PATHSPEC_OPTS = GIT_PATHSPEC_FLAGS
_SHELL_STATE_BUILTINS = {"export", "declare", "typeset", "local", "readonly", "unset", "source",
                         ".", "enable", "read", "readarray", "mapfile", "getopts", "trap", "for",
                         "select"}

# Non-removal git subcommands: known names, so the head is RESOLVED even though
# this policy has nothing to say about them.
GIT_SUBCOMMANDS = {
    "add", "am", "annotate", "apply", "archive", "bisect", "blame", "branch",
    "bundle", "cat-file", "check-attr", "check-ignore", "checkout", "cherry",
    "cherry-pick", "clean", "clone", "commit", "config", "count-objects",
    "describe", "diff", "difftool", "fetch", "fsck", "gc", "grep", "help", "init",
    "log", "ls-files", "ls-remote", "ls-tree", "merge", "merge-base", "mergetool",
    "mv", "notes", "pull", "push", "range-diff", "rebase", "reflog", "remote",
    "repack", "replace", "request-pull", "reset", "restore", "revert", "rev-list",
    "rev-parse", "shortlog", "show", "show-ref", "sparse-checkout", "stash",
    "status", "submodule", "switch", "symbolic-ref", "tag", "update-index",
    "update-ref", "verify-commit", "whatchanged", "worktree", "write-tree",
}

DOCKER_GLOBAL = _spec(
    ("-D", "--debug", "--tls", "--tlsverify", "-v", "--version", "--help"),
    ("-H", "--host", "--context", "-c", "--config", "-l", "--log-level",
     "--tlscacert", "--tlscert", "--tlskey"))
DOCKER_EXEC = _spec(("-d", "--detach", "-i", "--interactive", "-t", "--tty",
                     "--privileged"),
                    ("-e", "--env", "--env-file", "-u", "--user", "-w", "--workdir",
                     "--detach-keys"))
DOCKER_RUN = _spec(("-d", "--detach", "-i", "--interactive", "-t", "--tty", "--rm",
                    "--privileged", "--init", "-P", "--publish-all", "--read-only",
                    "--no-healthcheck", "--sig-proxy", "-q", "--quiet"),
                   ("-e", "--env", "--env-file", "-v", "--volume", "-p", "--publish",
                    "--name", "-u", "--user", "-w", "--workdir", "--network", "--net",
                    "--entrypoint", "--mount", "--label", "-l", "--restart", "--memory",
                    "-m", "--cpus", "--add-host", "--hostname", "-h", "--platform",
                    "--pull", "--user-ns", "--tmpfs", "--device", "--cap-add",
                    "--cap-drop", "--security-opt", "--log-driver", "--workdir"))
DOCKER_RESOURCE_RM = {"rm", "rmi", "prune"}
DOCKER_RESOURCE_NOUNS = {"container", "image", "volume", "network", "system",
                         "builder", "buildx", "config", "secret", "service",
                         "stack", "node", "plugin", "context", "compose"}


PARALLEL = _spec(
    ("--gnu", "--bar", "--eta", "--progress", "-k", "--keep-order", "--will-cite",
     "--dry-run", "--tag", "-u", "--ungroup", "--line-buffer", "--lb", "--pipe",
     "--verbose", "-v", "--quote", "-q", "--null", "-0", "--halt-on-error",
     "--no-notice", "--bibtex", "--citation", "--group", "--keep-order",
     "--round-robin", "--compress", "--files", "-X", "-m", "--xargs", "--tmux",
     "--shuf", "--resume", "--resume-failed", "--plus", "--dry-run"),
    ("-j", "--jobs", "--delay", "--sshlogin", "-S", "--sshdelay", "--env",
     "--colsep", "-C", "--tagstring", "--block", "--rpl", "--return", "--header",
     "--timeout", "--retries", "--results", "--joblog", "--tmpdir", "--basefile",
     "--workdir", "--wd", "--halt", "--load", "--memfree", "--nice", "--slf",
     "--trc", "-a", "--arg-file", "-N", "-L", "-l", "-I", "--recstart", "--recend",
     "--transfer", "--cleanup", "--sshloginfile", "--interactive", "--limit"))

WATCH = PEEL["watch"][0]

SSH_SPEC = _SSH_SPEC

FIND_EXEC_OPS = {"-exec", "-execdir", "-ok", "-okdir"}
FIND_DELETE_OPS = {"-delete"}

BWRAP_NARGS = {
    "--bind": 2, "--dev-bind": 2, "--ro-bind": 2, "--bind-try": 2,
    "--ro-bind-try": 2, "--dev-bind-try": 2, "--symlink": 2, "--setenv": 2,
    "--file": 2, "--bind-data": 2, "--ro-bind-data": 2, "--perms": 1,
    "--chdir": 1, "--proc": 1, "--dev": 1, "--tmpfs": 1, "--dir": 1,
    "--unsetenv": 1, "--hostname": 1, "--uid": 1, "--gid": 1, "--chmod": 2,
}
BWRAP_BOOL = {"--unshare-all", "--unshare-user", "--unshare-ipc", "--unshare-pid",
              "--unshare-net", "--unshare-uts", "--unshare-cgroup", "--share-net",
              "--die-with-parent", "--new-session", "--as-pid-1", "--clearenv"}


def basename(path):
    return path.rsplit("/", 1)[-1]


# ---------------------------------------------------------------------------
# Static removal-reference recognition
#
# A word does not have to be a plain literal to NAME a removal front end. The
# forms below all resolve to /bin/rm at execution time while `Word.literal()`
# returns either None or a string whose basename is not in REMOVAL_EXES:
#
#     /bin/r?      /bin/rm*     /bin/r[mp]     /bin/{r,}m
#     $'rm'        $'\x72m'     ${EMPTY}rm     /bin/$X
#
# Recognition therefore runs over the word's SEGMENTS, not over its literal:
# literal and ANSI-C chunks contribute their decoded characters (escaped, so a
# quoted `{rm,echo}` stays data), glob and brace chunks contribute their own
# pattern text, and any dynamic chunk contributes `*`. The composed pattern is
# then tested for whether it COULD name a removal front end.
#
# A pattern whose basename is pure wildcard (`*`, `$X`) is deliberately NOT a
# removal reference unless a literal directory anchors it: `chmod +x *` and
# `cp $SRC $DST` must keep flowing, while `taskset 0x1 /bin/*` must not.
# ---------------------------------------------------------------------------

_EXPANSION_RE = re.compile(
    r"\$\{[^{}]*\}|\$\([^()]*\)|`[^`]*`|\$[A-Za-z_][A-Za-z0-9_]*|\$[0-9@*#?$!-]")
_GLOB_META = "*?["


def _glob_escape(text):
    out = []
    for ch in text:
        out.append("[%s]" % ch if ch in _GLOB_META else ch)
    return "".join(out)


def _brace_expand(chunks, limit=48):
    """Expand `{a,b}` alternatives found in PATTERN chunks only.

    ``chunks`` is a list of (is_pattern, text). Literal chunks are already
    glob-escaped and their braces stay data — that is what keeps the fixture's
    quoted `printf '%s' '{rm,echo}'` a safe operand rather than a brace form.
    """
    results = [""]
    for is_pat, text in chunks:
        if not is_pat or "{" not in text:
            results = [r + text for r in results]
            if len(results) > limit:
                return results[:limit]
            continue
        alts = _brace_alternatives(text, limit)
        results = [r + a for r in results for a in alts]
        if len(results) > limit:
            return results[:limit]
    return results


def _brace_alternatives(text, limit):
    """All strings `text` (which may contain one or more {a,b} groups) yields."""
    i = text.find("{")
    if i < 0:
        return [text]
    depth = 0
    j = i
    while j < len(text):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    if j >= len(text) or depth != 0:
        return [text]
    body = text[i + 1:j]
    if "," not in body:
        return [text]
    parts = []
    depth = 0
    cur = []
    for ch in body:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    parts.append("".join(cur))
    out = []
    for p in parts:
        for tail in _brace_alternatives(text[j + 1:], limit):
            out.extend(_brace_alternatives(text[:i] + p + tail, limit))
            if len(out) > limit:
                return out[:limit]
    return out


def _fnmatch_names(pattern, names):
    """Could the glob `pattern` select any of `names`? Pure text, no filesystem."""
    try:
        rx = re.compile(_glob_to_regex(pattern))
    except re.error:
        return False
    return any(rx.match(nm) for nm in names)


def _glob_to_regex(pattern):
    out = ["(?s)"]
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            out.append(".*")
        elif c == "?":
            out.append(".")
        elif c == "[":
            j = i + 1
            if j < n and pattern[j] in "!^":
                j += 1
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                j += 1
            if j >= n:
                out.append(re.escape(c))
            else:
                body = pattern[i + 1:j]
                if body[:1] in ("!", "^"):
                    body = "^" + body[1:]
                out.append("[" + body.replace("\\", "\\\\") + "]")
                i = j + 1
                continue
        else:
            out.append(re.escape(c))
        i += 1
    out.append(r"\Z")
    return "".join(out)


def chunks_name_removal(chunks):
    """True when the composed pattern could name a member of REMOVAL_EXES."""
    for cand in _brace_expand(chunks):
        head, _, base = cand.rpartition("/")
        anchored = bool(head) or "/" in cand
        if not any(ch in base for ch in _GLOB_META):
            if base in REMOVAL_EXES:
                return True
            continue
        bare = re.sub(r"\[[^]]*\]|[*?]", "", base)
        if not bare:
            # Pure wildcard basename: only a removal reference when a literal
            # directory anchors it (`/bin/*` yes, `*` and `$X` no).
            if anchored:
                return True
            continue
        if _fnmatch_names(base, REMOVAL_EXES):
            return True
    return False


def word_chunks(w):
    """(chunks, has_dynamic) for a lexed Word, ready for chunks_name_removal."""
    chunks = []
    dynamic = False
    for kind, s, _ in w.segs:
        if kind == "lit":
            chunks.append((False, _glob_escape(s.text)))
        elif kind == "ansi":
            chunks.append((False, _glob_escape(ansi_decode(s.text))))
        elif kind in ("glob", "brace"):
            chunks.append((True, s.text))
        else:
            dynamic = True
            chunks.append((True, "*"))
    return chunks, dynamic


# ---------------------------------------------------------------------------
# Can a static PATTERN be proven unable to name a removal front end?
#
# ``chunks_name_removal`` answers "does this argv word NAME a removal front
# end?" and is lenient by design in ways that are right for an argument and
# wrong for a word about to be EXCUSED from command position: a basename made
# only of wildcards (`??`, `[r][m]`) is "not a reference", and glob syntax its
# translator does not model reads as "cannot match" (extglob `@(rm|ls)`, a
# POSIX class `r[[:alpha:]]`, a sequence `{r..s}m`, a brace list past the
# expansion cap). The predicate below asks the converse question, so each of
# those answers "it could".
# ---------------------------------------------------------------------------

_PATTERN_SEGS = ("lit", "glob", "brace")
# Glob or brace text whose meaning ``_glob_to_regex`` / ``_brace_alternatives``
# do not model: an extglob group, a POSIX bracket class / equivalence class /
# collating symbol, a sequence expression, and any expansion, substitution or
# escape carried inside the pattern text itself.
_UNMODELLED_PATTERN_RE = re.compile(r"^[?*+@!]\(|\[[:=.]|[$`\\]|\.\.")
_PATTERN_BRACE_CAP = 48


def pattern_word_could_name_removal(w):
    """Could the word ``w``, read as a COMMAND HEAD, expand to a removal name?

    ``w`` is a head whose ``literal()`` is None. This says "no" only when it is
    PROVEN: every segment is a literal, a glob or a brace whose syntax is
    modelled, and no candidate the expansion can yield names a member of
    REMOVAL_EXES. It says "it could" for:

      * any other segment — an expansion, substitution, arithmetic, process
        substitution or ANSI-C string is an ASSEMBLY CHANNEL and can build any
        name (`${R}${M}`, `$(printf rm)`, `$'\\x72m'`);
      * glob or brace syntax this module does not model (see above);
      * a brace expansion that reaches the cap, whose remaining alternatives
        were never examined;
      * a candidate whose basename is a removal front end or a glob matching
        one, compared without case (nocaseglob and a case-insensitive file
        system are both readings a shell can have);
      * a basename made only of `?` and bracket classes (`??`, `[r][m]`), and
        any wildcard anchored by a directory (`/bin/*`, `/bin/r?`).

    The ONE wildcard it excuses is a basename made only of `*` with no
    directory: the standing rule ``chunks_name_removal`` applies to `du -sh *`,
    and the shape `count(*)` puts in the walk's command position.
    """
    for kind, s, _ in w.segs:
        if kind not in _PATTERN_SEGS:
            return True
        if kind != "lit" and _UNMODELLED_PATTERN_RE.search(s.text):
            return True
    return _chunks_could_name_removal(word_chunks(w)[0])


def _chunks_could_name_removal(chunks):
    """The candidate test of ``pattern_word_could_name_removal``, on chunks."""
    cands = _brace_expand(chunks, limit=_PATTERN_BRACE_CAP)
    if len(cands) >= _PATTERN_BRACE_CAP:
        return True
    for cand in cands:
        _dir, sep, base = cand.rpartition("/")
        if not any(ch in base for ch in _GLOB_META):
            if base.lower() in REMOVAL_EXES:
                return True
            continue
        if not sep and not base.strip("*"):
            continue
        try:
            rx = re.compile(_glob_to_regex(base), re.IGNORECASE)
        except re.error:
            return True
        if any(rx.match(name) for name in REMOVAL_EXES):
            return True
    return False


# Pattern text taken from RAW text that the chunk test above does not model.
# `(` and `)` already split such text into separate tokens, so an extglob group
# arrives here only in pieces; a POSIX class and a sequence brace do not.
_UNMODELLED_TEXT_PATTERN_RE = re.compile(r"\[[:=.]|\{[^{}]*\.\.[^{}]*\}")
_QUOTE_ESCAPE_RE = re.compile(r"[\"'\\]")
_LENIENT_WORD_SPLIT_RE = re.compile(r"[\s;&|()<>]+")


def unparsed_text_could_reach_removal(text, offset=-1):
    """THE DATA READING of value text this module's lexer cannot read.

    A parse failure alone is not a removal reference. bash reads a whole line
    before it runs any of it, so the line holding the syntax error runs
    nothing, and a non-interactive shell stops there. The COMPLETE LINES
    BEFORE IT do run: those are re-entered as the command lines they are
    (``offset`` is where the lexer failed; the cut is the last newline before
    it), so `ok; $X` or `x; find . -delete` above an unbalanced quote is judged
    by the walk, not excused by the error below it.

    The rest of the text is judged by what survives any re-tokenization, both
    as written and with every quote and backslash removed (`r''m`, `r\\m`):
      * a removal front end's name that no word character joins to its
        neighbours (``_REMOVAL_EVIDENCE_RE``: `rm`, `/bin/rm`, `rm.txt`);
      * a library removal written as an expression (`shutil.rmtree(p)`);
      * a pattern that could expand to a removal front end's name (`/bin/r?`,
        `{r,}m`, `??`), by the test ``pattern_word_could_name_removal`` uses.

    A bare mention of some OTHER removal-related word — `don't delete it` — is
    not one of these, and no longer refuses a comment that merely holds an
    apostrophe.
    """
    if not text or not text.strip():
        return False
    plain = _QUOTE_ESCAPE_RE.sub("", text)
    for variant in (text, plain):
        if _REMOVAL_EVIDENCE_RE.search(variant):
            return True
        if _expression_names_removal_api(variant) is not None:
            return True
        for tok in _LENIENT_WORD_SPLIT_RE.split(variant):
            if not tok:
                continue
            if _UNMODELLED_TEXT_PATTERN_RE.search(tok):
                return True
            if _chunks_could_name_removal(_text_token_chunks(tok)):
                return True
    cut = text.rfind("\n", 0, offset if offset >= 0 else len(text))
    if cut > 0 and text[:cut].strip():
        return Analyzer.payload_is_not_provably_inert(text[:cut])
    return False


def text_token_names_removal(tok):
    """Same question for a token taken from RAW TEXT (a quoted payload word)."""
    if not tok:
        return False
    return chunks_name_removal(_text_token_chunks(tok))


def _text_token_chunks(tok):
    """A RAW-TEXT token reduced to the (is_pattern, text) chunks recognition reads."""
    chunks = []
    i = 0
    n = len(tok)
    plain = []

    def flush_plain():
        if plain:
            chunks.append((True, _EXPANSION_RE.sub("*", "".join(plain))))
            del plain[:]

    while i < n:
        c = tok[i]
        if c == "$" and tok[i + 1:i + 2] == "'":
            j = _find_ansi_end(tok, i + 2)
            if j < 0:
                j = n
            flush_plain()
            chunks.append((False, _glob_escape(ansi_decode(tok[i + 2:j]))))
            i = j + 1
            continue
        if c == "'":
            j = tok.find("'", i + 1)
            if j < 0:
                j = n
            flush_plain()
            chunks.append((False, _glob_escape(tok[i + 1:j])))
            i = j + 1
            continue
        if c == '"':
            j = tok.find('"', i + 1)
            if j < 0:
                j = n
            flush_plain()
            # Inside double quotes expansions still run; globs and braces do not.
            body = tok[i + 1:j]
            last = 0
            for m in _EXPANSION_RE.finditer(body):
                chunks.append((False, _glob_escape(body[last:m.start()])))
                chunks.append((True, "*"))
                last = m.end()
            chunks.append((False, _glob_escape(body[last:])))
            i = j + 1
            continue
        if c == "\\" and i + 1 < n:
            flush_plain()
            chunks.append((False, _glob_escape(tok[i + 1])))
            i += 2
            continue
        plain.append(c)
        i += 1
    flush_plain()
    return chunks


# ---------------------------------------------------------------------------
# ARGV CANONICALIZATION — one normalized shape, one predicate
# ---------------------------------------------------------------------------
#
# WHY THIS EXISTS. When TWO code paths answer the same question, they can
# answer it differently and the laxer one wins: an attached branch testing a
# TOKEN predicate and a separated branch testing a PAYLOAD predicate on the
# identical string would deny `cat --opt=/bin/rm f` yet allow the strictly
# more dangerous `cat --opt='/bin/rm -rf T' f`.
#
# The remedy is structural. Every value position —
# attached `-XV`, long-joined `--opt=V`, clustered `-abXV`, separated `-X V` /
# `--opt V`, and a bare payload — is first reduced to a NormalValue. Only then
# may a removal-recognition predicate run, and there is exactly ONE:
# ``Analyzer.value_names_removal``. The checkable property this buys:
#
#     the same string in the same position produces the same verdict
#     regardless of the syntactic form it arrived in.

class NormalValue:
    """A value position reduced to the canonical shape recognition runs on.

    ``text`` is the statically-known value (quotes already removed) or None
    when any part of it is computed; ``word`` is the source Word when the value
    arrived as a whole word, so a computed value can still be recognised over
    its segments. Constructing one of these is the ONLY way to ask the removal
    question about an option value.
    """

    __slots__ = ("text", "word", "ambiguous_split")

    def __init__(self, text, word=None, ambiguous_split=False):
        self.text = text
        self.word = word
        # True when WHERE the value begins is not knowable from the syntax —
        # a short cluster remainder (`-abXrm`) can start at any of its
        # characters. `--opt=V` is attached but exactly split, so it is False.
        self.ambiguous_split = ambiguous_split

    @staticmethod
    def from_word(w):
        """A value that arrived as its own argv word (separated forms)."""
        return NormalValue(w.literal(), w)

    @staticmethod
    def from_text(s, ambiguous_split=False):
        """A value that arrived attached to its option (`-XV`, `--opt=V`).

        The text is a slice of an enclosing word whose ``literal()`` was not
        None, so it is static by construction; it is still judged by the one
        payload predicate, never by a separate token predicate.
        """
        return NormalValue(s, None, ambiguous_split)

    def describe(self):
        return (self.text if self.text is not None
                else (self.word.raw.text if self.word is not None else ""))


# Canonical slot kinds produced by ``Analyzer._ic_canonicalize``. Identity, not
# equality, is used at the decision site so a typo cannot silently match.
_IC_OPERAND = "operand"
_IC_POST_DASH_OPERAND = "post_double_dash_operand"
_IC_BOOL = "bool_option"
_IC_EXEC_VALUE = "declared_exec_value"
_IC_DATA_VALUE = "declared_data_value"
_IC_OPAQUE_VALUE = "opaque_option_value"
_IC_UNRESOLVABLE = "unresolvable_option_word"
_IC_MISSING_VALUE = "missing_option_value"

# The CLOSED positional-shape vocabulary. Each token names WHERE the parse
# placed the word carrying a removal name. The ledger is keyed on
# (reason_code, positional_shape) because a reason code alone would let an
# element inherit a justification reading "it sits in OPERAND position" when
# it was not in operand position.
#
# `unclassified` is the reserved TOTALITY fallback and is inadmissible as a
# ledger key: a parse that cannot place the word must fail the criterion rather
# than borrow a neighbouring entry's proof.
SHAPE_OPERAND = "operand"
SHAPE_POST_DOUBLE_DASH = "post_double_dash_operand"
SHAPE_BOOL_OPTION_WORD = "declared_bool_option_word"
SHAPE_DATA_OPTION_VALUE = "declared_data_option_value"
SHAPE_EXEC_OPTION_VALUE = "declared_exec_option_value"
SHAPE_UNDECLARED_SEPARATED = "undeclared_option_value_separated"
SHAPE_UNDECLARED_ATTACHED = "undeclared_option_value_attached"
SHAPE_SUBCOMMAND_RESOURCE = "subcommand_resource_operand"
SHAPE_OUTPUT_SINK_LITERAL = "interpreter_string_literal_in_output_sink"
SHAPE_PARSE_ONLY_PAYLOAD = "parse_only_payload"
SHAPE_SCRIPT_FILE_OPERAND = "script_file_data_operand"
SHAPE_BUILTIN_LOOKUP = "builtin_lookup_operand"
# Heredoc bodies and assignment prefixes are positions the walk reaches and
# covers; naming them keeps such a boundary from reporting the inadmissible
# `unclassified` with an empty shape list.
SHAPE_HEREDOC_BODY = "heredoc_or_herestring_body"
SHAPE_ASSIGNMENT_PREFIX = "assignment_prefix_binding"
SHAPE_UNCLASSIFIED = "unclassified"

POSITIONAL_SHAPES = (
    SHAPE_OPERAND, SHAPE_POST_DOUBLE_DASH, SHAPE_BOOL_OPTION_WORD,
    SHAPE_DATA_OPTION_VALUE, SHAPE_EXEC_OPTION_VALUE,
    SHAPE_UNDECLARED_SEPARATED, SHAPE_UNDECLARED_ATTACHED,
    SHAPE_SUBCOMMAND_RESOURCE, SHAPE_OUTPUT_SINK_LITERAL,
    SHAPE_PARSE_ONLY_PAYLOAD, SHAPE_SCRIPT_FILE_OPERAND,
    SHAPE_BUILTIN_LOOKUP, SHAPE_HEREDOC_BODY, SHAPE_ASSIGNMENT_PREFIX,
    SHAPE_UNCLASSIFIED,
)

_IC_SHAPES = {
    _IC_OPERAND: SHAPE_OPERAND,
    _IC_POST_DASH_OPERAND: SHAPE_POST_DOUBLE_DASH,
    _IC_BOOL: SHAPE_BOOL_OPTION_WORD,
    _IC_EXEC_VALUE: SHAPE_EXEC_OPTION_VALUE,
    _IC_DATA_VALUE: SHAPE_DATA_OPTION_VALUE,
    _IC_OPAQUE_VALUE: SHAPE_UNDECLARED_SEPARATED,
    _IC_UNRESOLVABLE: SHAPE_UNDECLARED_ATTACHED,
    _IC_MISSING_VALUE: SHAPE_UNDECLARED_SEPARATED,
}

_REMOVAL_MENTION_SPLIT = re.compile(r"[^A-Za-z0-9_]+")

# Names the SHAPE ATTRIBUTION must recognise. Deliberately WIDER than
# REMOVAL_EXES and matching the degraded predicate's vocabulary, because the
# shape function has to be TOTAL over the DEGRADED-restricted domain: `man
# rmdir` and `man remove-shell` are in that domain, and the parse must still be
# able to say that `rmdir` sat in operand position. This list decides NO
# verdict — widening it can only move an element from `unclassified` to a named
# position, never from deny to allow.
REMOVAL_NAME_MENTIONS = frozenset(REMOVAL_EXES) | frozenset((
    "rmdir", "rmtree", "rimraf", "unlinkSync", "rmSync", "rmdirSync",
    "removeSync", "remove", "removedirs", "remove_tree", "rm_rf", "rm_r",
    "delete", "deleteIfExists"))


def text_mentions_removal_name(text):
    """Does this text CONTAIN a removal front end's name anywhere?

    Deliberately weaker than recognition, and it decides NO verdict. Its only
    job is to pick WHICH covered word the element's positional shape describes,
    so the shape function is TOTAL over the restricted domain: `cat -- rm.txt`
    is in that domain because the degraded predicate is a character regex, and
    the shape must still say where `rm.txt` sat.
    """
    if not text:
        return False
    for token in _REMOVAL_MENTION_SPLIT.split(text):
        if not token:
            continue
        if token in REMOVAL_NAME_MENTIONS:
            return True
        for piece in token.split("."):
            if piece in REMOVAL_NAME_MENTIONS or basename(piece) in REMOVAL_EXES:
                return True
    return False


def _text_is_nested_command_line(text):
    """Would this text have to be RE-PARSED as a command line to be judged?

    Answered by the module's OWN lexer, never by ``str.split``, which is a
    tokenizer COARSER THAN A SHELL'S: `x;/bin/rm${IFS}-rf${IFS}T` contains no
    whitespace, so a whitespace split would judge it as one program reference
    named `x;/bin/rm${IFS}…`, while a shell reads it as two commands and runs
    the second.

    A text the lexer reads as exactly ONE bare word carries no nested command
    line: the program-reference reading already answers it completely, and
    re-entering the evaluation procedure on it would ask the same question of
    the same bytes forever.

    A text the lexer CANNOT read is not proven to be a lone word, so it is
    treated as a nested command line exactly when its data reading could still
    reach a removal front end (``unparsed_text_could_reach_removal``): the
    complete lines above the failure are re-entered, and the rest counts only
    when it names a removal front end, writes a library removal, or carries a
    pattern that could expand to one. The parse failure alone is no evidence;
    a nested reading the walk then cannot finish still fails closed.
    """
    if not text or not text.strip():
        return False
    try:
        toks = lex(Src.from_raw(text))
    except LexError as exc:
        return unparsed_text_could_reach_removal(text, exc.offset)
    return not (len(toks) == 1 and toks[0][0] == "W")


def text_names_removal(text):
    """THE removal-recognition decision for canonical value TEXT.

    Two readings of the SAME text, both always applied, neither able to
    authorize what the other denies:

      * as a PROGRAM REFERENCE — the text names one program, judged on its own
        representation, so `/bin/r?`, `/bin/{r,}m` and `$'\\x72m'` are seen even
        though the shell's own tokenizer would collapse them to something the
        walk cannot re-derive;
      * as SHELL CODE — the text is handed back to the one evaluation
        procedure, which re-lexes it and walks it as a command line in its
        DATA READING: the same walk, except that a static pattern head proven
        unable to name a removal front end is judged as an unmodelled program
        rather than taken for evidence, and text the lexer cannot read counts
        only when ``unparsed_text_could_reach_removal`` says it could still
        reach a removal front end.

    Nothing decides which reading applies: a value that is dangerous under
    EITHER reading is not proven inert.
    """
    if not text or not text.strip():
        return False
    if text_token_names_removal(text):
        return True
    if not _text_is_nested_command_line(text):
        return False
    return Analyzer.payload_is_not_provably_inert(text)


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class Analyzer:
    def __init__(self, raw):
        self.raw = raw
        self.boundaries = []
        self.discharged = set()
        self.removal_shape = None
        self.removal_shapes = []
        # Shapes noted since the last boundary was recorded. They belong to the
        # boundary about to be recorded, which is how a shape stays bound to
        # the walk that produced the verdict instead of to whatever word
        # happened to mention a removal name first.
        self._pending_shapes = []
        self.removal_evidence = bool(_REMOVAL_EVIDENCE_RE.search(raw))
        self.depth = 0
        self.overflow = False
        # A non-forced git rm's run-time obligations (git options, pathspecs), the
        # directories a `cd` may leave a later one in, and why they cannot be known.
        self.git_rm, self.git_rm_cwds, self.git_rm_unresolved = [], [], ""
        self._head, self.direct = None, False
        # Whether the code being walked is read by a shell that has `[[ ]]`
        # (see walk). Set per analyze_code call; a call that does not say so
        # gets False. Any alias text in the command, or a run
        # of a COND_DISABLING_BUILTINS builtin, switches it off for the rest.
        self._cond = False
        self._cond_disabled = "alias" in raw.lower()
        # True for the walk ``payload_is_not_provably_inert`` runs: the DATA
        # READING of a value, which asks whether any shell reading of the text
        # could put a removal front end in command position. Only that walk
        # sets it, so the walk of a command line itself never changes.
        self.data_reading = False

    def note_removal_position(self, shape, text):
        """Record EVERY parse-derived position a removal NAME was placed in.

        Called BY THE WALK, at the moment the walk places a word — never
        re-derived afterwards from the reason-code string, which would just be
        the reason code wearing a second name.

        FIRST PLACEMENT DOES NOT WIN. Recording only the first word that
        merely MENTIONS a removal name would let one benign leading operand
        capture the shape of the whole command: `cat rm.txt --opt='<payload>'
        f` would report `operand` and borrow that entry's written proof, while
        the same command without `rm.txt` reports
        `undeclared_option_value_attached`.

        Recording the SET means an element is covered only when every position
        that carries a removal name is ledgered, so no position can borrow a
        neighbour's justification.

        Keying the laxity ledger on the boundary reason code alone would make
        new laxity invisible: any command the analyzer maps onto a ledgered
        code would inherit that entry's written positional justification even
        when the justification does not describe it.
        """
        if text and text_mentions_removal_name(text):
            if shape not in self._pending_shapes:
                self._pending_shapes.append(shape)
            if shape not in self.removal_shapes:
                self.removal_shapes.append(shape)
            if self.removal_shape is None:
                self.removal_shape = shape

    def note_removal_word(self, shape, w):
        if w is not None:
            self.note_removal_position(shape, w.raw.text)

    # -- verdict recording ---------------------------------------------------

    def add(self, verdict, reason, detail=""):
        if len(self.boundaries) >= MAX_BOUNDARIES:
            self.overflow = True
            return
        # EVERY position this boundary's own walk placed a removal name in.
        # Attaching the set here is what binds the positional shape to the walk
        # that produced the verdict: `echo "$(command -v rm)"` has an operand
        # AND a builtin-lookup operand, but they belong to two DIFFERENT
        # boundaries, and only the deciding one's shapes may key the ledger.
        shapes, self._pending_shapes = self._pending_shapes, []
        self.boundaries.append({"verdict": verdict, "reason": reason,
                                "detail": detail[:160],
                                "positional_shapes": shapes})

    def add_terminal(self, verdict, reason, detail=""):
        """Record a WHOLE-ANALYSIS finding, exempt from the boundary budget.

        ``add`` refuses to append once the budget is spent — which is exactly
        the moment the exhaustion finding needs recording, so routing it
        through ``add`` drops it. This recorder is uncapped by construction and
        is called at most twice per analysis, so it still functions at the
        bound. It is an OBSERVABILITY channel only: ``analyze`` seeds the
        verdict from the flags themselves, never from what lands here.
        """
        shapes, self._pending_shapes = self._pending_shapes, []
        self.boundaries.append({"verdict": verdict, "reason": reason,
                                "detail": detail[:160],
                                "positional_shapes": shapes})

    def structural(self, reason, detail=""):
        """Unconditionally UNRESOLVED: the boundary could not be identified."""
        self.add(UNRESOLVED, reason, detail)

    def scoped(self, reason, detail=""):
        """UNRESOLVED when the command carries removal evidence, else inert.

        Without removal evidence there is no removal for this policy to
        authorize, so an unmodelled option or subcommand is not a removal risk.
        """
        if self.removal_evidence:
            self.add(UNRESOLVED, reason, detail)
        else:
            self.add(PROVEN_INERT, "no_removal_evidence:" + reason, detail)

    def note(self, kind, off):
        if off is not None and off >= 0:
            self.discharged.add((kind, off))

    # -- census discharge (completeness backstop) -----------------------------

    def cover_src(self, src):
        """Discharge every removal-reference obligation inside ``src``.

        DISCHARGE IS AN EXPLANATION, NOT AN OUTCOME. It is called only from
        sites that can say WHY this particular text is accounted for: the token
        was the head of a boundary that got a real verdict, or it was consumed
        as data by an affirmatively proven inert consumer, or it sat in an
        assignment prefix that never executes, or it was inside a payload
        proven to be an output sink.

        It must NEVER be driven by "the enclosing command came out safe" —
        that is circular, and it would let a census raise zero effective
        obligations while a wrapper payload walks through. If no site can
        explain a removal reference, the obligation stands and the command
        resolves UNRESOLVED.
        """
        if src is None:
            return
        for o in src.idx:
            if o >= 0:
                self.discharged.add((census_mod.KIND_REMOVAL_REFERENCE, o))

    def cover(self, w):
        if w is not None:
            self.cover_src(w.raw)

    def cover_redir(self, r):
        """Discharge a redirection, and REPORT the position it discharged.

        The stdin payload of a `<<`/`<<-` heredoc and the target of a `<<<`
        here-string are delivered to the receiving command's STDIN; they are
        not words of its argv. The walk already reached both — the body as the
        redirection's own (delim, quoted, body) triple, the here-string as its
        target word — and this records SHAPE_HEREDOC_BODY for both, so neither
        reports `unclassified` from an empty shape list. An ordinary `>`/`<`
        target is NOT this position and stays unreported.
        """
        if r is None:
            return
        if r.target is not None:
            self.cover(r.target)
            if r.op == "<<<":
                self.note_removal_word(SHAPE_HEREDOC_BODY, r.target)
        if r.heredoc is not None and len(r.heredoc) > 2:
            self.cover_src(r.heredoc[2])
            self.note_removal_position(SHAPE_HEREDOC_BODY, r.heredoc[2].text)

    # -- affirmative inertness ------------------------------------------------

    @staticmethod
    def value_names_removal(v):
        """THE removal-recognition predicate. Nothing else may answer this.

        Its argument is always a NormalValue, so attached, long-joined,
        clustered and separated values have already been reduced to one shape
        before recognition begins. Three representations matter, because a
        wrapper payload arrives in all of them:
          (a) a bare program reference  -- rm, /bin/rm, ../bin/unlink
          (b) a command-line-shaped value -- 'rm -rf x', the quoted payload of
              an attached/clustered code option such as `script -qc`. A token
              predicate cannot judge this shape.
          (c) an UNEXPANDED reference -- /bin/r?, /bin/{r,}m, $'\\x72m',
              ${EMPTY}rm. These have no literal whose basename is in
              REMOVAL_EXES, so a literal-based reading sees them as clean;
              recognition therefore runs over the representation.
        """
        if v.text is not None:
            if v.ambiguous_split:
                # Same predicate, asked of every plausible start of the value.
                return Analyzer.attached_value_names_removal(v.text)
            return text_names_removal(v.text)
        w = v.word
        if w is None:
            return False
        chunks, _dynamic = word_chunks(w)
        if chunks_name_removal(chunks):
            return True
        # A whole-word value can equally be a QUOTED PAYLOAD — `setsid -c
        # '<removal>'`, `flock f -c '> log rm -rf T'`. Same text, same one
        # procedure, and no whitespace test gates it, for the same reason
        # ``text_names_removal`` has none.
        inner = _strip_outer_quotes(w.raw.text)
        if not _text_is_nested_command_line(inner):
            return False
        return Analyzer.payload_is_not_provably_inert(inner)

    @staticmethod
    def word_is_removal_reference(w):
        """Whole-word value positions. Canonicalize, then ask the one predicate."""
        return Analyzer.value_names_removal(NormalValue.from_word(w))

    @staticmethod
    def word_names_removal_program(w):
        """The PROGRAM-REFERENCE reading of a whole word, and ONLY that.

        Reachable from exactly one site: the data operands of a named
        interpreter running a script FILE with no inline-code flag. There the
        parse has already PROVEN what re-parses the word — the script does, as
        data — so the nested-command-line reading has nothing to resolve. This
        is the script-file data-operand proof kind: `python3 checker.py 'git rm
        x'` must stay allowed.

        It is not a second model of what executes. It is the FIRST of the two
        readings ``value_names_removal`` always applies, called where the other
        one has been discharged by proof rather than skipped by convenience —
        the same discipline that lets a DECLARED DATA option value through.
        """
        chunks, _dynamic = word_chunks(w)
        return chunks_name_removal(chunks)

    @staticmethod
    def text_is_removal_reference(s):
        """Attached / sliced value positions. Same canonicalization, same predicate."""
        return Analyzer.value_names_removal(NormalValue.from_text(s))

    @staticmethod
    def attached_value_names_removal(text):
        """THE predicate, asked about every plausible split of an ATTACHED value.

        Where an attached value BEGINS is exactly what an undeclared option
        leaves unknown: in `-abXrm` the value may be `bXrm`, `Xrm` or `rm`, and
        every one of those is tested.

        THERE IS NO CUT CAP. A fixed split count would flip the verdict once
        exceeded (`cat -a<pad>rm T` allowed past the cap), the same defect
        class as a depth cutoff that turns into an allow, so the search runs
        to the end of the text. What bounds it is STRUCTURAL, not
        numeric: a cut is only plausible while everything skipped so far still
        looks like clustered option characters, which is what keeps
        `-e$PATTERN` and `-k1,1` from fanning out. Running out of TEXT is
        completion, not exhaustion — every candidate split was examined.

        Cut 0 hands the whole remainder to the one evaluation procedure, so a
        remainder carrying shell metacharacters (`-aX;rm`) is read as the shell
        would read it rather than as one opaque token.
        """
        if not text:
            return False
        for cut in range(len(text)):
            # The only STRUCTURAL stop: whitespace ends the attached remainder,
            # and everything past it is a separate argv word the walk sees on
            # its own. Stopping at punctuation would make every in-value
            # separator a bypass (`-X'X,rm'`, `X:rm`, `X%rm`, `X@rm`, `X=rm`),
            # yet a comma- or colon-separated option value is exactly the shape
            # whose consumption an UNDECLARED option leaves unproven.
            if cut and text[cut - 1].isspace():
                break
            if Analyzer.text_is_removal_reference(text[cut:]):
                return True
        return False

    @staticmethod
    def unreadable_option_word_names_removal(w):
        """The same question for an option word that is not fully literal.

        `cat -X/bin/r? T` is judged by the one predicate, not by whether the
        raw text carries removal evidence. The word's own option marker is
        stripped by the split search, so the value is what gets recognised.
        """
        raw = _strip_outer_quotes(w.raw.text)
        if not raw[:1] in OPTION_SIGNS:
            return False
        return Analyzer.attached_value_names_removal(raw[1:])

    @staticmethod
    def payload_is_not_provably_inert(text):
        """RE-ENTER THE EVALUATION PROCEDURE on a nested payload.

        There is ONE procedure that decides what can execute, and this is how
        every nested position asks it. A command at top level, a command in an
        option value, a command in a `-c` argument and a command after an exec
        wrapper are the SAME QUESTION, so they are answered by the same lexer,
        the same walk, the same wrapper/shell/interpreter/consumer tables and
        the same census — recursively, at every depth, with no level at which
        the knowledge thins out.

        A SECOND, private model of this question would be laxer than the walk:
        a head scan that knows only shells and interpreters, or looks one level
        deep, or tokenizes on whitespace, would allow `xargs /bin/rm -rf T`,
        `timeout 5 …` or `sudo -u root …` as an option value, `sh -c 'sh -c
        /bin/rm'` one level down, and `x;/bin/rm${IFS}-rf${IFS}T` as one token.
        Re-entering the procedure leaves no second model to fall behind.

        FAIL-CLOSED, ALWAYS. Anything that stops the procedure short of a
        terminal-safe verdict — a lex failure, a census fatal, an unnamed head
        that could name a removal front end, a boundary overflow, an exhausted
        work budget — resolves the payload as NOT PROVABLY INERT. A bound that
        denies on exhaustion is a work bound; a bound that returns "inert" on
        exhaustion is a bypass.

        THE DATA READING. The text is a VALUE, so the walk below runs with
        ``data_reading`` set and asks only whether some reading of it could
        put a removal front end in command position. A head that is a static
        glob or brace (`a?x=1`, the `*` of `count(*)`) and is proven by
        ``pattern_word_could_name_removal`` unable to expand to one is an
        unmodelled program, so its argv is still read; any head that could, or
        that carries an expansion, substitution or ANSI-C string, stays
        UNRESOLVED. Whether a text the lexer cannot read reaches this point at
        all is decided by ``unparsed_text_could_reach_removal``.
        """
        if not text or not text.strip():
            return False
        # ONE shared work budget with the enclosing walk. Exhausting it is the
        # `recursion_limit` case, and it denies.
        if _PAYLOAD_NESTING[0] >= MAX_DEPTH:
            return True
        _PAYLOAD_NESTING[0] += 1
        try:
            try:
                cen = census_mod.census(text)
            except Exception:
                return True
            if cen["fatal"]:
                return True
            sub = Analyzer(text)
            sub.depth = _PAYLOAD_NESTING[0]
            sub.data_reading = True
            try:
                sub.analyze_code(Src.from_raw(text), Env())
            except Exception:
                return True
            if sub.overflow:
                return True
            for ob in cen["obligations"]:
                if (ob["kind"], ob["offset"]) not in sub.discharged:
                    return True
            for b in sub.boundaries:
                if b["verdict"] not in _TERMINAL_SAFE:
                    return True
            return False
        finally:
            _PAYLOAD_NESTING[0] -= 1

    def _swallowed_removal(self, base, consumed):
        """Did option/operand parsing eat a removal front end as DATA?

        Everything in ``consumed`` was classified as an option, an option
        VALUE, or a fixed operand. A removal front end sitting there means this
        spec's arity does not match the real program's, so the payload slice
        about to be trusted is the wrong one. `nsenter -t 1 -m rm <path>` is
        the live example: -m takes an OPTIONAL file, the spec ate `rm` as its
        value and handed on a bare path. An unresolvable argument vector is
        UNRESOLVED, never an allow.
        """
        for w in consumed:
            if self.word_is_removal_reference(w):
                self.structural("wrapper_arity_mismatch",
                                "%s:%s" % (base, (w.literal() or "")[:40]))
                return True
        return False

    def _terminal_inert(self, reason, detail, residual, data_opts=()):
        """Terminal-safe only when inertness is affirmatively provable.

        The boundary that would execute ``residual`` is NOT resolved by this
        analyzer. If nothing in ``residual`` can name a removal front end, the
        command lies outside the declared policy scope and is terminal-safe.
        If a removal reference IS present, the absence of a proof is
        UNRESOLVED — never an allow: `taskset 0x1 rm <path>` and `script -qc
        '<removal>'` reach this leaf and deny even though no table names their
        head.

        ``data_opts`` names options the CALLER has proven consume a DATA value.
        Without it this scan would be attachment-dependent: `git log --grep=rm`
        and `git log --grep rm` would get two verdicts for the same string in
        the same position. Declaring the option makes both ALLOW through one
        canonical value.
        """
        skip = -1
        for idx, w in enumerate(residual):
            if idx == skip:
                continue
            lit = w.literal()
            if lit is not None and data_opts and lit[:1] == "-":
                # Long `--opt[=V]` and short `-o[V]` are resolved to the SAME
                # value position before anything is judged, so attachment
                # cannot decide the verdict here either.
                if lit[:2] == "--":
                    optname, eq, attached = lit.partition("=")
                elif lit in data_opts:
                    # Go-style multi-character single-dash option (`-run`).
                    optname, eq, attached = lit, "", ""
                elif "=" in lit:
                    optname, eq, attached = lit.partition("=")
                else:
                    optname, attached = lit[:2], lit[2:]
                    eq = bool(attached)
                if optname in data_opts:
                    if eq or attached:
                        self.note_removal_position(SHAPE_DATA_OPTION_VALUE,
                                                   attached)
                    elif idx + 1 < len(residual):
                        skip = idx + 1
                        self.note_removal_word(SHAPE_DATA_OPTION_VALUE,
                                               residual[idx + 1])
                    continue
            if self.word_is_removal_reference(w):
                self.structural(
                    "unproven_boundary_with_removal_reference",
                    "%s:%s" % (detail, (w.literal() or "")[:60]))
                return
            api = _expression_names_removal_api(w.raw.text)
            if api is not None:
                # The SAME library-removal knowledge ``_classify_inline_code``
                # applies to a NAMED interpreter's payload, applied here to an
                # UNNAMED head's argv, so `bun -e 'require("fs").rmSync(p)'`
                # denies even though `bun` is not in INTERPRETERS: no position
                # may know less than another.
                self.structural(
                    "unproven_boundary_with_removal_api_reference",
                    "%s:%s" % (detail, api[:40]))
                return
        # Proving the residual clean IS the explanation the census wants: these
        # words were examined and none of them can put a removal front end in
        # command position. `git commit -m 'drop rm usage'` mentions rm; it
        # cannot run it.
        for w in residual:
            self.cover(w)
        self.add(PROVEN_INERT, reason, detail)

    # -- word traversal ------------------------------------------------------

    def visit_word(self, w, env):
        """Discharge and recurse into every active expansion inside ``w``."""
        for kind, s, off in w.segs:
            if kind == "sub":
                self.note("substitution", off)
                self.analyze_code(s, Env(env.hashed, env.aliases), cond=self._cond)
            elif kind == "arith":
                self.note("substitution", off)
                self.scan_expansions(s, env)
            elif kind == "procsub":
                self.note("procsub", off)
                self.analyze_code(s, Env(env.hashed, env.aliases), cond=self._cond)
            elif kind == "param":
                body = s.text
                if body.startswith("!") or (
                        "@" in body and body.rsplit("@", 1)[1][:1] in REEXPAND_OPS):
                    self.note("param_reexpand", off)
                    self.structural("param_reexpansion", body)
                self.scan_expansions(s, env)
            elif kind == "arraylit":
                self.scan_expansions(s, env)

    def scan_expansions(self, src, env, heredoc_body=False):
        """Find expansions inside a non-command context (arith / ${...} body).

        ``heredoc_body``: the body of an unquoted heredoc, where a quote is text.
        """
        t = src.text
        n = len(t)
        i = 0
        while i < n:
            c = t[i]
            if c == "\\":
                i += 2
                continue
            if c == "'" and not heredoc_body:
                j = t.find("'", i + 1)
                if j < 0:
                    self.structural("lex:single_quote", t[:80])
                    return
                i = j + 1
                continue
            if c == "`":
                segs = []
                try:
                    i = _lex_backtick(src, i, segs)
                except LexError as exc:
                    self.structural("lex:" + str(exc), t[:80])
                    return
                for kind, s, off in segs:
                    self.note("substitution", off)
                    self.analyze_code(s, Env(env.hashed, env.aliases), cond=self._cond)
                continue
            if c == "$" and i + 1 < n and t[i + 1] in "({[":
                segs = []
                try:
                    i = _lex_dollar(src, i, segs)
                except LexError as exc:
                    self.structural("lex:" + str(exc), t[:80])
                    return
                for kind, s, off in segs:
                    if kind == "sub":
                        self.note("substitution", off)
                        self.analyze_code(s, Env(env.hashed, env.aliases),
                                          cond=self._cond)
                    elif kind == "arith":
                        self.note("substitution", off)
                        self.scan_expansions(s, env)
                    elif kind == "param":
                        body = s.text
                        if body.startswith("!") or (
                                "@" in body
                                and body.rsplit("@", 1)[1][:1] in REEXPAND_OPS):
                            self.note("param_reexpand", off)
                            self.structural("param_reexpansion", body)
                        self.scan_expansions(s, env)
                continue
            i += 1

    # -- command-level walk --------------------------------------------------

    def analyze_code(self, src, env, cond=False):
        """Walk ``src`` as shell code.

        ``cond`` says the shell reading this code has the `[[ ]]` conditional
        (COND_SHELLS). Only a caller that knows the shell says so: the command
        itself, its substitutions, `eval` and alias bodies (the same shell), and
        a COND_SHELLS -c or stdin program. Every other caller (ssh, at, git
        aliases, exec option values ...) hands the code to a shell this file
        cannot name, so it keeps the default False.
        """
        self.depth += 1
        outer = self._cond
        self._cond = cond
        try:
            if self.depth > MAX_DEPTH:
                self.structural("recursion_limit")
                return
            try:
                toks = lex(src)
            except LexError as exc:
                self.structural("lex:" + str(exc), src.text[:80])
                return
            self.walk(toks, env)
        finally:
            self._cond = outer
            self.depth -= 1

    def _opens_conditional(self, cur, tok):
        """True when word ``tok`` is the reserved word `[[` of a new command.

        `[[` is reserved only unquoted and only as a command's first word, after
        nothing but the reserved words of COND_OPENER_PREFIX: `"[[" a || b`,
        `A=1 [[ a || b ]]` and `>f [[ a || b ]]` run a command named `[[`, and
        their `||` is a real boundary. The test is on the raw text, so every
        quoted or escaped spelling stays an ordinary word.
        """
        if not self._cond or self._cond_disabled or tok[1].raw.text != "[[":
            return False
        return all(t[0] == "W" and t[1].raw.text in COND_OPENER_PREFIX for t in cur)

    def walk(self, toks, env):
        cur = []
        piped = False
        next_piped = False
        # Inside `[[ ... ]]` (cond_depth is not None) the shell reads a
        # conditional expression, not commands: `&&`, `||`, `!`, `(` and `)` are
        # its operators and a line break between its terms is blank, so none of
        # them ends the command, and every operand is a word of the one `[[`
        # command, never a command head. Its expansions are still visited by
        # flush like any other word's, so `[[ -n $(cmd) ]]` is analysed as code.
        # Anything else (`;`, `&`, `|`, `;;`, a `)` that closes no `(` of the
        # conditional, as in a case pattern `[[)`) cannot occur inside a
        # conditional; there the walk reads it as it would outside one and
        # treats it as a boundary. The conditional ends at the first word whose value
        # is `]]`, however quoted: ending it early only splits more.
        cond_depth = None
        for tok in toks:
            if tok[0] == "OP":
                op = tok[1]
                if cond_depth is not None:
                    if op in ("&&", "||", "\n"):
                        continue
                    if op == "(":
                        cond_depth += 1
                        continue
                    if op == ")" and cond_depth > 0:
                        cond_depth -= 1
                        continue
                    cond_depth = None
                self.flush(cur, env, piped)
                cur = []
                piped = next_piped = (op in PIPE_OPS)
                continue
            if tok[0] == "W":
                if cond_depth is None:
                    if self._opens_conditional(cur, tok):
                        cond_depth = 0
                elif tok[1].literal() == "]]":
                    cond_depth = None
            cur.append(tok)
        self.flush(cur, env, piped)

    def flush(self, toks, env, piped):
        words = [t[1] for t in toks if t[0] == "W"]
        redirs = [t[1] for t in toks if t[0] == "R"]
        if not words and not redirs:
            return
        for r in redirs:
            if r.op in ("<<", "<<-"):
                self.note("heredoc", r.off)
                # An UNQUOTED delimiter leaves the body subject to expansion, so
                # any substitution inside it runs even when the body is mere
                # data for the receiving command.
                if r.heredoc is not None and not r.heredoc[1]:
                    self.scan_expansions(r.heredoc[2], env, heredoc_body=True)
            elif r.op == "<<<":
                self.note("heredoc", r.off)
                if r.target is not None:
                    self.visit_word(r.target, env)
            elif r.target is not None:
                self.visit_word(r.target, env)
        for w in words:
            self.visit_word(w, env)
        if not words:
            return

        # Leading assignments are not the command head, but their values are
        # live expansion sites (already visited above).
        k = 0
        while k < len(words):
            first = words[k].segs[0] if words[k].segs else None
            if first and first[0] == "lit" and _ASSIGN_RE.match(first[1].text):
                k += 1
                continue
            break
        # An assignment prefix normally never executes: its value is data, and
        # `A=(/bin/rm) echo x` stays SAFE. But a NAMED set
        # of variables is a documented command hook that the very next command
        # runs — GIT_EXTERNAL_DIFF, GIT_PAGER, GIT_SSH_COMMAND, PAGER, LESSOPEN,
        # EDITOR — so `GIT_EXTERNAL_DIFF=/bin/rm git diff` is an execution
        # boundary wearing an assignment's clothes. Scope the rule to those
        # names so ordinary prefixes keep flowing.
        if k < len(words):
            for w in words[:k]:
                if self._assignment_is_exec_vector(w):
                    return
                # The prefix is a BINDING the following command does not run.
                # The walk already computed this exact slice and already
                # covered it; reporting the position keeps `A=rm echo x` from
                # resolving to `unclassified`.
                # Guarded by `k < len(words)` so a prefix with no following
                # command records nothing — there is no boundary to attach to
                # and the note would drain into an unrelated later one.
                self.note_removal_word(SHAPE_ASSIGNMENT_PREFIX, w)
        if k:  # a variable (GIT_DIR, HOME, PATH, ...) a later git may run with
            self.git_rm_unresolved = self.git_rm_unresolved or "variable assignment"
        for w in words[:k]:
            self.cover(w)
        rest = words[k:]
        if not rest:
            for r in redirs:
                self.cover_redir(r)
            return
        self.eval_command(rest, redirs, env, piped)

    def _assignment_is_exec_vector(self, w):
        """True (and a verdict already recorded) when this prefix names a hook.

        Only the declared EXEC_ASSIGNMENT_VARS matter. Their value is a command
        line the following program runs, so it is read exactly like any other
        command text: a removal front end in its command position denies, a
        dynamic value denies, everything else stays data.
        """
        segs = w.segs
        if not segs or segs[0][0] != "lit":
            return False
        head = segs[0][1].text
        eq = head.find("=")
        if eq < 0:
            return False
        var = head[:eq].rstrip("+")
        if var not in EXEC_ASSIGNMENT_VARS:
            return False
        value = w.literal()
        if value is None:
            self.structural("exec_assignment_dynamic_value", var)
            return True
        body = value[value.find("=") + 1:]
        if not body.strip():
            return False
        # ONE predicate here too: two predicates must never answer one question
        # about one string.
        if Analyzer.text_is_removal_reference(body):
            self.add(FORBIDDEN_REMOVAL, "exec_assignment_vector",
                     "%s=%s" % (var, body[:60]))
            return True
        return False

    # -- keyword stripping ---------------------------------------------------

    DROP = {"if", "then", "else", "elif", "fi", "while", "until", "do", "done",
            "esac", "!", "{", "}", "in", ";;"}
    HEADER = {"for", "case", "select", "function"}

    def eval_command(self, words, redirs, env, piped):
        while words:
            lit = words[0].literal()
            if lit in self.DROP:
                words = words[1:]
                continue
            if lit in self.HEADER:
                self._shell_state(lit, words[1:])  # `for`/`select` assign their variable
                return  # loop/case header: its words are patterns, not commands
            if lit == "coproc":
                words = words[1:]
                if len(words) >= 2 and words[0].literal() and \
                        _NAME_RE.match(words[0].literal() or ""):
                    words = words[1:]
                continue
            break
        if not words:
            return
        self._head = words[0]  # a simple command's own head, not one a wrapper runs
        self.eval_argv(words, redirs, env, piped)

    def _shell_state(self, base, args):
        """Record what a later command inherits from shell builtin `base` (see _GIT_RM_LOCATION_OPTS)."""
        lits = [a.literal() for a in args]
        if base in CD_TARGET_BUILTINS:  # popd only returns to a directory already listed
            ops = [x for x in lits if x is None or x == "-" or not x.startswith("-")]
            if len(ops) == 1 and ops[0] and ops[0].startswith("/"):
                self.git_rm_cwds.append(ops[0])
                return
        elif base == "set":  # allexport, keyword and posix let an assignment reach git
            if None not in lits and not any(x in ("allexport", "keyword", "posix") or x[:1] in OPTION_SIGNS and x != "--" and ("a" in x or "k" in x) for x in lits):
                return
        elif base == "printf":
            if None not in lits and not any(x.startswith("-v") for x in lits):
                return
        elif base not in _SHELL_STATE_BUILTINS:
            return
        self.git_rm_unresolved = self.git_rm_unresolved or base

    # -- the boundary verdict ------------------------------------------------

    def eval_argv(self, words, redirs, env, piped=False):
        if not words:
            return
        head = words[0]
        args = words[1:]
        name = head.literal()
        if name is None:
            # THE DATA READING of a value: the head is a static glob or brace
            # PROVEN unable to produce a removal front end's name — the `a?x=1`
            # of `https://h/a?x=1&y=2`, the `*` of `count(*)`. That reading
            # cannot put a removal front end here, so the head is an unmodelled
            # program like any other: the leaf below still asks whether its
            # argv names one, so `x&a?b rm T` does not pass.
            if self.data_reading and not pattern_word_could_name_removal(head):
                self._terminal_inert("data_reading_pattern_head",
                                     head.raw.text[:80], words)
                return
            # The program that will execute cannot be named. Nothing about it
            # can be proven, so it is UNRESOLVED regardless of removal tokens.
            self.structural("dynamic_command_head", head.raw.text[:80])
            return
        if name in env.aliases:
            body = env.aliases[name]
            parts = [body] + [a.raw for a in args]
            self.analyze_code(src_concat(parts), Env(env.hashed, {}), cond=self._cond)
            return
        if name in env.hashed:
            name = env.hashed[name]
        base = basename(name)
        self.direct, self._head = head is self._head and self.depth == 1, None
        if base in COND_DISABLING_BUILTINS:
            self._cond_disabled = True
        if base in ("cd", "pushd", "set", "printf") or base in _SHELL_STATE_BUILTINS:
            self._shell_state(base, args)

        if base in REMOVAL_EXES:
            self.cover(head)  # accounted for: it IS the removal we denied
            self.add(FORBIDDEN_REMOVAL, "filesystem_removal", name)
            return

        if base == ".":
            self._h_source(name, args, redirs, env, piped)
            return
        handler = getattr(self, "_h_" + base.replace("-", "_").replace(".", "_"), None)
        if handler is not None:
            handler(name, args, redirs, env, piped)
            return
        if base in SHELLS:
            self._shell(name, args, redirs, env, piped)
            return
        if base in INTERPRETERS or base in AWKS:
            self._interpreter(base, args, env)
            return
        if base in WRAPPERS and WRAPPERS[base] is not None:
            spec, nops = WRAPPERS[base]
            self._prefix_wrapper(base, args, spec, nops, env)
            return
        if base in INERT_ARGV_CONSUMERS:
            self._inert_consumer(base, name, args, redirs, env)
            return
        # A literal, named program this analyzer has NOT proven to be a
        # non-boundary. Absence from every table above is NOT a proof of
        # inertness — it is the absence of a proof, and the absence of a proof
        # may not authorize. The only inertness this leaf can establish for an
        # unmodelled head is that its argv cannot name a removal front end at
        # all; then no reachable execution is in policy scope, whether or not
        # the head turns out to be an exec wrapper.
        #
        # The HEAD is tested alongside the arguments on purpose. A wrapper whose
        # spec reads `-c` as a boolean hands on its quoted operand as the whole
        # argv, so the removal arrives AS the command head — `setsid -c 'rm
        # <path>'`, `strace -c '<removal>'`, `exec -c '<removal>'`. Testing
        # arguments alone leaves that entire shape authorized.
        self._terminal_inert("named_program_no_removal_reference", name, words,
                             data_opts=SELECTOR_DATA_OPTIONS.get(basename(name), ()))

    # -- declared-inert argv consumers: POSITION, not membership -------------

    def _inert_consumer(self, base, name, args, redirs, env):
        """PHASE 2 — resolve a declared-inert consumer by INSPECTING ITS ARGV.

        Membership in INERT_ARGV_CONSUMERS alone does not decide the boundary:
        `man rm` (a documentation lookup) and `man -P '/bin/rm -rf T' ls` (a
        pager invocation) share a head but not a verdict.

        The question asked here is WHERE a removal reference sits. It is asked
        ONCE, of an already-canonical value, so no two syntactic forms of the
        same string can receive different verdicts:
          * OPERAND position is data — `man rm`, `which /bin/rm`,
            `grep -F /bin/rm README.md` keep flowing, which is why deleting
            members is no substitute for reading the argv;
          * DECLARED-EXEC option value is a program — its text is analyzed as
            shell code, so `man -P less ls` stays safe while `man -P
            '/bin/rm -rf T' ls` reaches the removal head and denies, in every
            one of the five option forms;
          * DECLARED-DATA option value is a pattern, a count, a delimiter or a
            data path the program reads and never runs, so `grep -e rm f.txt`
            keeps flowing — the one position where a proof of data-ness exists;
          * every OTHER option-value position — attached value, long
            `--opt=value`, clustered short option, or an option this model does
            not declare at all — is not proven to be data, so a removal
            reference there is UNRESOLVED whatever form it arrived in.
        """
        model = INERT_ARGV_CONSUMERS[base]
        for kind, opt, value, words in self._ic_canonicalize(args, model):
            post_dash = kind is _IC_POST_DASH_OPERAND
            if kind is _IC_UNRESOLVABLE:
                # This word's option/value split is unreadable, but that is a
                # reason to ask the ONE predicate about every split — not a
                # reason to ask a different question such as raw-text removal
                # evidence, which would allow `cat -X/bin/r? T`.
                if self.unreadable_option_word_names_removal(words[0]):
                    self.structural("option_value_removal_reference",
                                    "%s:%s" % (name, words[0].raw.text[:60]))
                    return
                self.scoped("inert_consumer_unresolvable_option",
                            "%s:%s" % (name, words[0].raw.text[:40]))
                return
            if kind is _IC_MISSING_VALUE:
                self.structural("missing_option_value", name + " " + opt)
                return
            if kind is _IC_EXEC_VALUE:
                if not self._ic_exec_value(name, opt, words[0], value, env):
                    return
            elif kind is _IC_OPAQUE_VALUE:
                # NOT PROVEN DATA. Whether this value is executed is exactly
                # what an undeclared option leaves unknown, so the absence of a
                # proof may not authorize it (the governing rule this file
                # states above the table).
                if value is not None and self.value_names_removal(value):
                    self.structural(
                        "option_value_removal_reference",
                        "%s:%s" % (name, (opt + "=" + value.describe())[:60]))
                    return
            shape = _IC_SHAPES[kind]
            if kind is _IC_OPAQUE_VALUE and value is not None:
                shape = (SHAPE_UNDECLARED_ATTACHED if value.text is not None
                         else SHAPE_UNDECLARED_SEPARATED)
            if value is not None:
                self.note_removal_position(shape, value.describe())
            for w in words:
                self.cover(w)
                self.note_removal_word(
                    SHAPE_POST_DOUBLE_DASH if post_dash else shape, w)
        for r in (redirs or ()):
            self.cover_redir(r)
        self.add(PROVEN_INERT,
                 "inert_consumer_operand_position_only:" + model["kind"], name)

    def _ic_canonicalize(self, args, model):
        """PHASE 1 — reduce argv to canonical slots. NO predicate runs here.

        This function deliberately contains not one removal-recognition call.
        Deciding the removal question inline at each syntactic branch lets the
        branches drift onto different predicates, so `--opt=/bin/rm` and the
        strictly more dangerous `--opt='/bin/rm -rf T'` could disagree. Here
        every value position — attached ``-XV``, long-joined ``--opt=V``,
        clustered ``-abXV``, separated ``-X V`` / ``--opt V`` — is reduced to a
        NormalValue first, so phase 2 sees one shape and asks one question.

        A slot is ``(kind, option, NormalValue|None, words_consumed)``.
        ``words_consumed`` is what phase 2 covers; a word examined in
        option-value position WITHOUT being consumed — an undeclared short or
        long option's follower, which may equally be the next option — carries
        an empty list and is re-walked on its own.
        """
        bools, execs, vals = model["bool"], model["exec"], model["val"]
        slots = []
        i = 0
        n = len(args)
        while i < n:
            w = args[i]
            lit = w.literal()
            if lit is None:
                # Not a plain literal. Its POSITION still decides: only a word
                # whose static prefix is an option marker can reach an
                # option-value position, and only then is it unresolvable.
                # `echo /bin/r?` and `du -sh *` are operands — data — and must
                # keep flowing.
                slots.append(((_IC_UNRESOLVABLE
                               if _static_prefix(w).startswith("-")
                               else _IC_OPERAND), "", None, [w]))
                i += 1
                continue
            if lit == "--":
                for w2 in args[i:]:
                    slots.append((_IC_POST_DASH_OPERAND, "", None, [w2]))
                break
            if len(lit) > 1 and lit[:2] == "--":
                optname, eq, attached = lit.partition("=")
                res = _resolve_ic_long(optname, model)
                declared = res is not None
                if res in execs:
                    if eq:
                        slots.append((_IC_EXEC_VALUE, res,
                                      NormalValue.from_text(attached), [w]))
                        i += 1
                    elif i + 1 >= n:
                        slots.append((_IC_MISSING_VALUE, res, None, [w]))
                        i += 1
                    else:
                        slots.append((_IC_EXEC_VALUE, res,
                                      NormalValue.from_word(args[i + 1]),
                                      [w, args[i + 1]]))
                        i += 2
                    continue
                if declared and res in bools and not eq:
                    slots.append((_IC_BOOL, res, None, [w]))
                    i += 1
                    continue
                if eq:
                    slots.append(((_IC_DATA_VALUE if declared and res in vals
                                   else _IC_OPAQUE_VALUE), optname,
                                  NormalValue.from_text(attached), [w]))
                    i += 1
                    continue
                if declared and res in vals:
                    if i + 1 >= n:
                        slots.append((_IC_MISSING_VALUE, res, None, [w]))
                        i += 1
                        continue
                    slots.append((_IC_DATA_VALUE, res,
                                  NormalValue.from_word(args[i + 1]),
                                  [w, args[i + 1]]))
                    i += 2
                    continue
                slots.append((_IC_OPAQUE_VALUE, optname, None, [w]))
                if i + 1 < n:
                    slots.append((_IC_OPAQUE_VALUE, optname,
                                  NormalValue.from_word(args[i + 1]), []))
                i += 1
                continue
            if len(lit) > 1 and lit[0] in "-+":
                kind, opt, value = _IC_BOOL, lit, None
                consumed_next = False
                j = 1
                while j < len(lit):
                    ch = lit[0] + lit[j]
                    rest = lit[j + 1:]
                    if ch in bools:
                        j += 1
                        continue
                    opt = ch
                    kind = (_IC_EXEC_VALUE if ch in execs else
                            _IC_DATA_VALUE if ch in vals else _IC_OPAQUE_VALUE)
                    if rest:
                        # A DECLARED option's attached value is exactly split;
                        # an UNDECLARED one's is not, because `rest` may still
                        # hold further cluster members before the value.
                        value = NormalValue.from_text(
                            rest, ambiguous_split=(kind is _IC_OPAQUE_VALUE))
                    elif kind is _IC_OPAQUE_VALUE:
                        value = None
                    elif i + 1 >= n:
                        kind = _IC_MISSING_VALUE
                    else:
                        value = NormalValue.from_word(args[i + 1])
                        consumed_next = True
                    break
                slots.append((kind, opt, value,
                              [w, args[i + 1]] if consumed_next else [w]))
                # An UNDECLARED short option may take a SEPARATED value, and
                # nothing here can tell whether the attached remainder was that
                # value or a further cluster member. Reading only the remainder
                # would let `cat -abX /bin/rm` through, so BOTH are examined,
                # and neither consumes the following word.
                if kind is _IC_OPAQUE_VALUE and i + 1 < n:
                    slots.append((_IC_OPAQUE_VALUE, opt,
                                  NormalValue.from_word(args[i + 1]), []))
                i += 2 if consumed_next else 1
                continue
            # Pure OPERAND position: data for a program proven not to exec it.
            slots.append((_IC_OPERAND, "", None, [w]))
            i += 1
        return slots

    def _ic_exec_value(self, name, opt, optword, value, env):
        """A declared exec option's value NAMES A PROGRAM: analyze it as code.

        Attached and separated forms arrive here through the SAME NormalValue,
        so `man -P'/bin/rm -rf T' ls`, `man -P '/bin/rm -rf T' ls` and
        `man --pager='/bin/rm -rf T' ls` cannot reach three different verdicts.
        """
        if value is None:
            self.structural("missing_option_value", name + " " + opt)
            return False
        if value.word is not None:
            if value.word.literal() is None:
                self.structural("exec_option_dynamic_value",
                                "%s %s %s" % (name, opt, value.word.raw.text[:40]))
                return False
            self.cover(value.word)
            self.analyze_code(value.word.content(), Env(env.hashed, env.aliases))
            return True
        if not value.text:
            self.structural("missing_option_value", name + " " + opt)
            return False
        self.cover(optword)
        self.analyze_code(self._alias_body_src(optword, value.text),
                          Env(env.hashed, env.aliases))
        return True

    # -- generic prefix wrapper ---------------------------------------------

    def _prefix_wrapper(self, base, args, spec, nops, env, allow_assignments=False):
        i, err = split_opts(args, spec)
        if err == "missing_option_value":
            self.structural("missing_option_value", base)
            return
        if err:
            self.scoped(err, base)
            return
        if base == "env" or allow_assignments:
            while i < len(args):
                lit = args[i].literal()
                if lit is not None and _ENVVAR_RE.match(lit):
                    i += 1
                    continue
                break
        i += nops
        if self._swallowed_removal(base, args[:i]):
            return
        payload = args[i:]
        if not payload:
            self._terminal_inert("wrapper_without_payload", base, args)
            return
        self.eval_argv(payload, [], env)

    # -- specific handlers ---------------------------------------------------

    def _h_command(self, name, args, redirs, env, piped):
        i = 0
        lookup = False
        while i < len(args):
            lit = args[i].literal()
            if lit is None or not lit.startswith("-") or lit == "-":
                break
            if lit == "--":
                i += 1
                break
            for ch in lit[1:]:
                if ch in "vV":
                    lookup = True
                elif ch != "p":
                    self.scoped("unknown_option:-" + ch, "command")
                    return
            i += 1
        if lookup:
            # -v/-V resolve a NAME and print it; they never run it.
            for w in args:
                self.cover(w)
            self.note_removal_position(SHAPE_BUILTIN_LOOKUP, self.raw)
            self.add(PROVEN_INERT, "command_lookup_only", "command -v")
            return
        payload = args[i:]
        if not payload:
            self._terminal_inert("wrapper_without_payload", "command", args)
            return
        self.eval_argv(payload, [], env)

    def _h_env(self, name, args, redirs, env, piped):
        # `env -S 'cmd args'` splits the string into argv itself. It performs
        # word splitting and $VAR substitution but NOT command substitution, so
        # the split words are argv literals, never shell code.
        for idx, a in enumerate(args):
            lit = a.literal()
            if lit is None:
                break
            if lit in ENV_SPLIT_OPTS:
                if idx + 1 >= len(args):
                    self.structural("missing_option_value", "env -S")
                    return
                self._env_split_string(args[idx + 1], env)
                return
            if lit.startswith("--split-string=") or (
                    lit.startswith("-S") and len(lit) > 2):
                content = a.content()
                start = len(content.text) - (
                    len(lit.split("=", 1)[1]) if "=" in lit else len(lit) - 2)
                self._env_split_words(content.slice(start, len(content.text)),
                                      args[idx + 1:], env)
                return
        spec, nops = WRAPPERS["env"]
        self._prefix_wrapper("env", args, spec, nops, env)

    def _env_split_string(self, word, env):
        if word.literal() is None:
            self.scoped("dynamic_env_split_string", word.raw.text[:60])
            return
        self._env_split_words(word.content(), [], env)

    def _env_split_words(self, src, tail, env):
        """Split a -S/--split-string payload into words, KEEPING raw offsets.

        Offsets matter: the words produced here are the real argv, and whatever
        resolves them has to be able to discharge the census obligations their
        text raised. Words rebuilt at offset -1 would leave `env -S 'echo
        /bin/rm'` unable to explain its own removal name.
        """
        words = []
        text = src.text
        i, n = 0, len(text)
        while i < n:
            if text[i].isspace():
                i += 1
                continue
            j = i
            while j < n and not text[j].isspace():
                j += 1
            piece = src.slice(i, j)
            words.append(Word([("lit", piece, piece.off(0))], piece.off(0), piece))
            i = j
        if not words:
            self._terminal_inert("env_split_string_empty", "env -S", list(tail))
            return
        self.eval_argv(words + list(tail), [], env)

    def _h_eval(self, name, args, redirs, env, piped):
        if args and args[0].literal() == "--":
            args = args[1:]
        if not args:
            self._terminal_inert("eval_without_payload", "eval", args)
            return
        parts = []
        for a in args:
            if a.literal() is None:
                self.scoped("dynamic_eval_argument", a.raw.text[:60])
                return
            parts.append(a.content())
        self.analyze_code(src_concat(parts), Env(env.hashed, env.aliases), cond=self._cond)

    def _h_source(self, name, args, redirs, env, piped):
        # The sourced file's contents are not in the command text. Nothing about
        # what it executes can be proven, so it is unresolved for the removal
        # policy whenever the command carries removal evidence.
        self.scoped("sourced_file_contents_unknown", " ".join(
            (a.literal() or a.raw.text) for a in args[:2]))

    _h_ = _h_source  # `.` — bash's POSIX synonym for `source`

    def _h_hash(self, name, args, redirs, env, piped):
        if args and args[0].literal() == "-p" and len(args) >= 3:
            target = args[1].literal()
            alias = args[2].literal()
            if target is not None and alias is not None:
                env.hashed[alias] = target
        for w in args:  # hash records a NAME in the lookup table; it runs nothing
            self.cover(w)
        self.note_removal_position(SHAPE_BUILTIN_LOOKUP, self.raw)
        self.add(PROVEN_INERT, "hash_builtin", "hash")

    def _h_alias(self, name, args, redirs, env, piped):
        for a in args:
            lit = a.literal()
            if lit and "=" in lit:
                key, _, _val = lit.partition("=")
                content = a.content()
                pos = content.text.find("=")
                if _NAME_RE.match(key) and pos >= 0:
                    env.aliases[key] = content.slice(pos + 1, len(content.text))
        self.add(PROVEN_INERT, "alias_builtin", "alias")

    def _h_busybox(self, name, args, redirs, env, piped):
        if not args:
            self._terminal_inert("applet_dispatcher_without_payload", name, args)
            return
        self.eval_argv(args, [], env)

    _h_toybox = _h_busybox
    _h_builtin = _h_busybox

    def _h_flock(self, name, args, redirs, env, piped):
        i, err = split_opts(args, PEEL["flock"][0])
        if err == "missing_option_value":
            self.structural("missing_option_value", "flock")
            return
        if err:
            self.scoped(err, "flock")
            return
        i += 1  # the lock file / directory / fd operand
        if self._swallowed_removal("flock", args[:i]):
            return
        if i < len(args) and args[i].literal() in COMMAND_OPTS:
            self._shell_code_operand(args, i + 1, env, "flock")
            return
        payload = args[i:]
        if not payload:
            self._terminal_inert("wrapper_without_payload", "flock", args)
            return
        self.eval_argv(payload, [], env)

    def _h_su(self, name, args, redirs, env, piped):
        if self._command_option(args, env, "su", SU_COMMAND_OPTS):
            return
        i, err = split_opts(args, _SU_SPEC)
        if err:
            self.scoped(err, "su")
            return
        self._terminal_inert("su_without_command", "su", args)

    def _h_runuser(self, name, args, redirs, env, piped):
        if self._command_option(args, env, "runuser", SU_COMMAND_OPTS):
            return
        i, err = split_opts(args, PEEL["runuser"][0])
        if err == "missing_option_value":
            self.structural("missing_option_value", "runuser")
            return
        if err:
            self.scoped(err, "runuser")
            return
        payload = args[i:]
        if not payload:
            self._terminal_inert("wrapper_without_payload", "runuser", args)
            return
        self.eval_argv(payload, [], env)

    def _h_sg(self, name, args, redirs, env, piped):
        for idx, a in enumerate(args):
            if a.literal() == "-c":
                self._shell_code_operand(args, idx + 1, env, "sg")
                return
        self._terminal_inert("sg_without_command", "sg", args)

    def _h_script(self, name, args, redirs, env, piped):
        if self._command_option(args, env, "script"):
            return
        # `-c` is matched EXACTLY above, so `script -qc '<code>'` (a clustered
        # short option, the canonical documented form) misses it. Falling to a
        # residual-proof terminal is what makes the miss deny instead of allow.
        self._terminal_inert("script_without_command", "script", args)

    def _h_start_stop_daemon(self, name, args, redirs, env, piped):
        for idx, a in enumerate(args):
            lit = a.literal()
            if lit in ("--exec", "-x", "--startas", "-a") and idx + 1 < len(args):
                prog = args[idx + 1]
                tail = []
                for j in range(idx + 2, len(args)):
                    if args[j].literal() == "--":
                        tail = args[j + 1:]
                        break
                self.eval_argv([prog] + tail, [], env)
                return
        self._terminal_inert("start_stop_daemon_without_exec", name, args)

    def _h_machinectl(self, name, args, redirs, env, piped):
        i, err = split_opts(args, _spec(("-q", "--quiet", "--no-pager", "--no-legend"),
                                        ("-M", "--machine", "-H", "--host",
                                         "--uid", "-E", "--setenv")))
        if err:
            self.scoped(err, "machinectl")
            return
        if i < len(args) and args[i].literal() in ("shell", "login"):
            payload = args[i + 2:]
            if payload:
                self.eval_argv(payload, [], env)
                return
        self._terminal_inert("machinectl_non_exec", name, args)

    def _h_bwrap(self, name, args, redirs, env, piped):
        i = 0
        while i < len(args):
            lit = args[i].literal()
            if lit is None or not lit.startswith("--"):
                break
            if lit in BWRAP_BOOL:
                i += 1
                continue
            if lit in BWRAP_NARGS:
                i += 1 + BWRAP_NARGS[lit]
                continue
            self.scoped("unknown_option:" + lit, "bwrap")
            return
        if i > len(args):
            self.structural("missing_option_value", "bwrap")
            return
        payload = args[i:]
        if not payload:
            self._terminal_inert("wrapper_without_payload", "bwrap", args)
            return
        self.eval_argv(payload, [], env)

    def _h_ssh(self, name, args, redirs, env, piped):
        i, err = split_opts(args, SSH_SPEC)
        if err == "missing_option_value":
            self.structural("missing_option_value", "ssh")
            return
        if err:
            self.scoped(err, "ssh")
            return
        i += 1  # destination
        if self._swallowed_removal("ssh", args[:i]):
            return
        payload = args[i:]
        if not payload:
            self._terminal_inert("ssh_login_only", "ssh", args)
            return
        # ssh concatenates its remaining operands and hands them to a remote shell.
        parts = []
        for a in payload:
            if a.literal() is None:
                self.scoped("dynamic_ssh_payload", a.raw.text[:60])
                return
            parts.append(a.content())
        self.analyze_code(src_concat(parts), Env())

    def _h_kubectl(self, name, args, redirs, env, piped):
        for idx, a in enumerate(args):
            if a.literal() == "--":
                payload = args[idx + 1:]
                if payload:
                    self.eval_argv(payload, [], env)
                    return
                break
        if any((a.literal() or "") in ("exec", "run", "debug") for a in args):
            self.scoped("kubectl_exec_payload_unresolved", name)
            return
        self._terminal_inert("kubectl_non_exec", name, args)

    def _h_at(self, name, args, redirs, env, piped):
        body = self._stdin_code(redirs)
        if body is not None:
            self.analyze_code(body, Env())
            return
        self.scoped("at_stdin_payload_unknown", name)

    _h_batch = _h_at

    def _h_watch(self, name, args, redirs, env, piped):
        i, err = split_opts(args, WATCH)
        if err == "missing_option_value":
            self.structural("missing_option_value", "watch")
            return
        if err:
            self.scoped(err, "watch")
            return
        payload = args[i:]
        if not payload:
            self._terminal_inert("wrapper_without_payload", "watch", args)
            return
        self.eval_argv(payload, [], env)

    def _h_xargs(self, name, args, redirs, env, piped):
        i, err = split_opts(args, XARGS_SPEC)
        if err == "missing_option_value":
            self.structural("missing_option_value", "xargs")
            return
        if err:
            self.scoped(err, "xargs")
            return
        payload = args[i:]
        if not payload:
            # xargs with no utility operand runs `echo`.
            self._terminal_inert("xargs_default_echo", "xargs", args)
            return
        self.eval_argv(payload, [], env)

    def _h_parallel(self, name, args, redirs, env, piped):
        cut = len(args)
        for idx, a in enumerate(args):
            if (a.literal() or "") in PARALLEL_SEPARATORS:
                cut = idx
                break
        head_args = args[:cut]
        i, err = split_opts(head_args, PARALLEL)
        if err == "missing_option_value":
            self.structural("missing_option_value", "parallel")
            return
        if err:
            self.scoped(err, "parallel")
            return
        payload = head_args[i:]
        if not payload:
            # With no template the command itself comes from the input stream.
            self.scoped("parallel_command_from_input", "parallel")
            return
        if "{" in (payload[0].literal() or "{"):
            # A placeholder in command position: the head comes from the input
            # items, which this analyzer cannot enumerate.
            self.scoped("parallel_command_from_input", "parallel")
            return
        # Input items are substituted as ARGUMENTS of the template, so they
        # belong to the same argv. Passing them through is both more faithful
        # and what lets `parallel echo ::: /bin/rm` explain its removal name.
        items = [a for a in args[cut:]
                 if (a.literal() or "") not in PARALLEL_SEPARATORS]
        self.eval_argv(payload + items, [], env)

    def _h_find(self, name, args, redirs, env, piped):
        i = 0
        saw_exec = False
        while i < len(args):
            lit = args[i].literal()
            if lit in FIND_DELETE_OPS:
                # find's own removal action needs no child process, so it never
                # reaches a command-head boundary. It is a filesystem removal
                # all the same and belongs to the same policy scope as `rm`.
                self.add(FORBIDDEN_REMOVAL, "find_delete_action",
                         "%s %s" % (name, lit))
                return
            if lit in FIND_EXEC_OPS:
                saw_exec = True
                j = i + 1
                payload = []
                while j < len(args):
                    jl = args[j].literal()
                    if jl in FIND_EXEC_ENDS:
                        break
                    payload.append(args[j])
                    j += 1
                if payload:
                    self.eval_argv(payload, [], env)
                i = j + 1
                continue
            i += 1
        if not saw_exec:
            # find's ONLY ways to remove are -exec/-execdir/-ok/-okdir (walked
            # above) and -delete (denied above). Every other operand is a
            # predicate pattern or a path, so `find . -name rm` searches for a
            # file called rm and is affirmatively inert — which is also the
            # explanation the census needs for that `rm`.
            #
            # POSITIONALLY, though: `find` DOES own an argv-derived execution
            # facility, so it cannot be authorized as an argv-blind consumer.
            # A removal reference in PREDICATE-VALUE position (`-name rm`) is
            # a search pattern; the same reference in PATH-OPERAND position
            # (`find /bin/rm -rf T`) is not proven to be anything.
            prev_is_predicate = False
            for w in args:
                lit = w.literal()
                if not prev_is_predicate and self.word_is_removal_reference(w):
                    self.structural("find_operand_removal_reference",
                                    "%s:%s" % (name, (lit or w.raw.text)[:60]))
                    return
                prev_is_predicate = bool(
                    lit and len(lit) > 1 and lit[0] == "-" and lit not in ("--",))
            for w in args:
                self.cover(w)
            self.add(PROVEN_INERT, "find_without_exec", name)

    def _h_perf(self, name, args, redirs, env, piped):
        if not args:
            self._terminal_inert("perf_without_payload", name, args)
            return
        if self._swallowed_removal(name, args[:1]):
            return
        payload = args[1:]
        if not payload:
            self._terminal_inert("perf_without_payload", name, args)
            return
        self.eval_argv(payload, [], env)

    # -- shells --------------------------------------------------------------

    def _command_option(self, args, env, who, names=COMMAND_OPTS):
        """Analyze the code of a `-c CODE`, `--command CODE` or `--command=CODE` among args."""
        for idx, a in enumerate(args):
            lit = a.literal()
            if lit in names:
                self._shell_code_operand(args, idx + 1, env, who)
                return True
            long = next((n for n in names if n.startswith("--") and (lit or "").startswith(n + "=")), None)
            if long is not None:
                content = a.content()
                start = len(content.text) - (len(lit) - len(long) - 1)
                self.analyze_code(content.slice(start, len(content.text)), Env(env.hashed, env.aliases))
                return True
        return False

    def _shell_code_operand(self, args, idx, env, who):
        if idx >= len(args):
            self.structural("missing_option_value", who)
            return
        w = args[idx]
        if w.literal() is None:
            self.scoped("dynamic_shell_code", w.raw.text[:60])
            return
        self.analyze_code(w.content(), Env(env.hashed, env.aliases))

    def _stdin_code(self, redirs):
        """Return the Src of code arriving on stdin, or None when not provable."""
        for r in redirs:
            if r.op in ("<<", "<<-") and (r.io in (None, "0")):
                if r.heredoc is None:
                    return None
                delim, quoted, body = r.heredoc
                if not quoted and ("\\$" in body.text or "\\`" in body.text):
                    return None  # heredoc expansion would rewrite the code
                return body
            if r.op == "<<<" and (r.io in (None, "0")):
                if r.target is None or r.target.literal() is None:
                    return None
                return r.target.content()
        return None

    def _shell(self, name, args, redirs, env, piped):
        i = 0
        code_word = None
        parse_only = False
        read_stdin = False
        n = len(args)
        while i < n:
            lit = args[i].literal()
            if lit is None or not lit or lit[0] not in "-+" or lit in OPTION_SIGNS:
                break
            if lit == "--":
                i += 1
                break
            if lit[:2] == "--":
                base_opt = lit.split("=", 1)[0]
                if base_opt in SHELL_LONG_BOOL:
                    i += 1
                    continue
                if base_opt in SHELL_LONG_VAL:
                    i += 1 if "=" in lit else 2
                    continue
                self.scoped("unknown_option:" + base_opt, name)
                return
            j = 1
            extra = 0
            bad = None
            while j < len(lit):
                ch = lit[j]
                if ch == "c":
                    if i + 1 >= n:
                        self.structural("missing_option_value", name + " -c")
                        return
                    code_word = args[i + 1]
                    extra = 1
                    j = len(lit)
                    break
                if ch == "n":
                    parse_only = True
                    j += 1
                    continue
                if ch == "s":
                    read_stdin = True
                    j += 1
                    continue
                if ch in "Oo":
                    if j + 1 < len(lit):
                        j = len(lit)
                    else:
                        extra = 1
                        j = len(lit)
                    break
                if ch in SHELL_SHORT_BOOL:
                    j += 1
                    continue
                bad = lit[0] + ch
                break
            if bad:
                self.scoped("unknown_option:" + bad, name)
                return
            i += 1 + extra
        if i > n:
            self.structural("missing_option_value", name)
            return

        if parse_only:
            # `-n` reads and parses without executing: active, but not executing.
            # Nothing in the payload or on stdin can run, so every removal
            # reference in them is explained.
            for w in args:
                self.cover(w)
            for r in (redirs or ()):
                self.cover_redir(r)
            self.note_removal_position(SHAPE_PARSE_ONLY_PAYLOAD, self.raw)
            self.add(PROVEN_INERT, "shell_parse_only", name)
            return
        if code_word is not None:
            if code_word.literal() is None:
                self.scoped("dynamic_shell_code", code_word.raw.text[:60])
                return
            self.analyze_code(code_word.content(), Env(env.hashed, env.aliases),
                              cond=basename(name) in COND_SHELLS)
            return
        operands = args[i:]
        if operands and not read_stdin:
            script = operands[0]
            path = script.literal()
            if path is None and CLAUDE_HOME_FILE.fullmatch(script.raw.text):
                path = script.raw.text
            if path is None:
                self.scoped("dynamic_script_operand", script.raw.text[:60])
                return
            # A named script file is the boundary; its operands are data handed
            # to that script. Opaque script contents are the policy's declared
            # trust boundary.
            #
            # EXCEPT when the script operand IS a removal front end. `bash
            # /bin/rm -rf T` names a removal binary in the position the shell
            # will open and run; nothing here proves that inert, for any
            # shell.
            if self.word_is_removal_reference(script):
                self.structural("shell_script_operand_removal_reference",
                                "%s:%s" % (name, path[:60]))
                return
            for w in operands:
                self.cover(w)
            self.add(PROVEN_INERT, "shell_script_file", path)
            return
        body = self._stdin_code(redirs)
        if body is not None:
            self.analyze_code(body, Env(env.hashed, env.aliases),
                              cond=basename(name) in COND_SHELLS)
            return
        self.scoped("shell_code_source_unknown", name)

    # -- inline interpreter code --------------------------------------------

    def _interpreter(self, base, args, env):
        code = None
        if base in AWKS:
            i = 0
            while i < len(args):
                lit = args[i].literal()
                if lit is None or not lit.startswith("-") or lit == "-":
                    break
                if lit in AWK_SOURCE_OPTS or lit.startswith(tuple(o + "=" for o in AWK_SOURCE_OPTS if o[1] == "-")):
                    # the program text: the next word, or the value attached with `=`
                    i += 0 if "=" in lit else 1
                    break
                if lit in AWK_VALUE_OPTS:
                    i += 2
                    continue
                if lit == "--":
                    i += 1
                    break
                i += 1
            if i < len(args):
                code = args[i]
        else:
            flags = INTERPRETERS[base]
            for idx, a in enumerate(args):
                lit = a.literal()
                if lit in flags and idx + 1 < len(args):
                    code = args[idx + 1]
                    break
                # The attached form reads the word's STATIC PREFIX: `-c"..$HOME.."`
                # has no literal, yet the flag it starts with is fixed text.
                head = lit if lit is not None else _static_prefix(a)
                if any(
                        head.startswith(f) and (len(head) > len(f) or lit is None)
                        for f in flags
                        if f.startswith("-") and len(f) == 2):
                    code = a
                    break
        if code is None:
            # Same rule as for shells: a script-file operand naming a removal
            # front end is not a proven-inert data path. The reading is the
            # PROGRAM-REFERENCE one, because this branch has proven there is no
            # inline-code flag and therefore no nested command line for the
            # interpreter to run (the script-file data-operand proof kind).
            for w in args:
                if self.word_names_removal_program(w):
                    self.structural("interpreter_script_operand_removal_reference",
                                    "%s:%s" % (base, (w.literal() or w.raw.text)[:60]))
                    return
            for w in args:  # script file + its data operands
                self.cover(w)
            self.note_removal_position(SHAPE_SCRIPT_FILE_OPERAND, self.raw)
            self.add(PROVEN_INERT, "interpreter_script_file", base)
            return
        if code.literal() is None:
            self._dynamic_interpreter_code(base, code)
            return
        text = code.literal()
        mark = len(self.boundaries)
        self._classify_inline_code(base, text)
        # Only an OUTPUT-SINK proof explains a removal name inside generated
        # code (`print("/bin/rm")`). Any other outcome leaves it unexplained.
        if all(b["reason"].startswith("interpreter_removal_token_in_output_sink")
               or b["reason"].startswith("interpreter_code_without_removal_token")
               for b in self.boundaries[mark:]) and self.boundaries[mark:]:
            self.cover(code)

    def _dynamic_interpreter_code(self, base, code):
        """An inline program whose word holds an expansion.

        The scoped check alone refuses only when the raw command carries an
        rm/unlink/shred/srm word, so it would judge `python3 -c
        "shutil.rmtree('$HOME/x')"` inert while refusing its literal-path form.
        The fixed text is therefore classified by the SAME classifier as the
        literal form, with each expansion replaced by a neutral placeholder: a
        refusal it finds is kept with the literal form's reason. An expansion
        that can change the program itself, not only a value inside one of its
        string literals, fails closed. Otherwise the scoped check runs as it
        does for a literal program, so no refusal weakens and no inert verdict
        changes its reason.
        """
        text, why = _program_with_placeholders(code, base, self.raw)
        mark = len(self.boundaries)
        saved = (list(self._pending_shapes), list(self.removal_shapes),
                 self.removal_shape)
        self._classify_inline_code(base, text)
        if any(b["verdict"] != PROVEN_INERT for b in self.boundaries[mark:]):
            return
        del self.boundaries[mark:]
        self._pending_shapes, self.removal_shapes, self.removal_shape = (
            saved[0], saved[1], saved[2])
        if why:
            self.structural("interpreter_expansion_changes_program",
                            "%s:%s" % (base, why))
            return
        self.scoped("dynamic_interpreter_code", code.raw.text[:60])

    def _classify_inline_code(self, base, text):
        # DYNAMIC ATTRIBUTE ACCESS FIRST. `getattr(os,"remove")(p)`,
        # `os.__dict__["unlink"](p)`, `globals()["shutil"].rmtree(p)` and
        # `__import__("os").remove(p)` reach the same syscalls while the name
        # never appears in a form the scans below can attribute to a call. A
        # construct that resolves its target at runtime cannot be proven inert
        # by reading names, so it is UNRESOLVED by construction.
        m = _DYNAMIC_ACCESS_RE.search(text)
        if m is not None:
            self.structural("interpreter_dynamic_attribute_access",
                            "%s:%s" % (base, m.group(0)[:40]))
            return
        # Library-level removal first. shutil.rmtree / fs.unlinkSync /
        # File.delete / fs.rmSync carry NO rm|unlink|shred|srm TOKEN, so the
        # token scan below cannot see them and would read them as "no removal
        # token -> inert". An interpreter payload that removes through an API is
        # exactly as unprovable as one that shells out.
        for rx in (_API_REMOVAL_RE, _API_DELETE_RE):
            m = rx.search(text)
            if m is None:
                continue
            sink = _enclosing_call(text, m.start(1))
            if sink not in OUTPUT_SINKS:
                self.structural("interpreter_api_removal_not_proven_inert",
                                "%s:%s" % (base, m.group(1)[:40]))
                return
        hits = list(_REMOVAL_EVIDENCE_RE.finditer(text))
        if not hits:
            self.add(PROVEN_INERT, "interpreter_code_without_removal_token", base)
            return
        for m in hits:
            sink = _enclosing_call(text, m.start(1))
            if sink not in OUTPUT_SINKS:
                self.scoped("interpreter_removal_token_not_proven_inert",
                            "%s:%s" % (base, sink or "<none>"))
                return
        self.note_removal_position(SHAPE_OUTPUT_SINK_LITERAL, self.raw)
        self.add(PROVEN_INERT, "interpreter_removal_token_in_output_sink", base)

    # -- git -----------------------------------------------------------------

    @staticmethod
    def _alias_body_src(word, body):
        """Offset-preserving Src for the body of a `-c alias.X=<body>` value.

        The body is always the TAIL of the option word's literal, so slicing
        the word's content keeps every raw offset. A body rebuilt from a plain
        str (offset -1 everywhere) could not discharge the census obligation
        its own `rm` raised.
        """
        if word is not None:
            content = word.content()
            start = len(content.text) - len(body)
            if 0 <= start <= len(content.text) and content.text[start:] == body:
                return content.slice(start, len(content.text))
        return Src(body, [-1] * len(body))

    def _h_git(self, name, args, redirs, env, piped):
        direct = self.direct
        aliases = {}
        alias_words = {}
        i = 0
        n = len(args)
        while i < n:
            lit = args[i].literal()
            if lit is None:
                # A computed word in git's option/subcommand region: the
                # subcommand that will run cannot be named.
                self.structural("dynamic_git_subcommand", args[i].raw.text[:60])
                return
            if lit == "--":
                i += 1
                break
            if not lit.startswith("-"):
                break
            if lit in ("-c", "--config-env") or lit.startswith("-c="):
                val = None
                val_word = None
                if "=" in lit and lit.startswith("--config-env="):
                    val = lit.split("=", 1)[1]
                    val_word = args[i]
                    i += 1
                elif i + 1 < n:
                    val = args[i + 1].literal()
                    val_word = args[i + 1]
                    i += 2
                else:
                    self.structural("missing_option_value", "git -c")
                    return
                if val and val.startswith("alias."):
                    key, _, body = val.partition("=")
                    aliases[key[len("alias."):]] = body
                    alias_words[key[len("alias."):]] = val_word
                continue
            res = _resolve_long(lit.split("=", 1)[0], GIT_GLOBAL) \
                if lit.startswith("--") else (lit if lit in GIT_GLOBAL["bool"] or
                                              lit in GIT_GLOBAL["val"] else None)
            if res is None:
                self.scoped("unknown_option:" + lit, "git")
                return
            if res in GIT_GLOBAL["val"] and "=" not in lit:
                i += 2
                if i > n:
                    self.structural("missing_option_value", "git " + lit)
                    return
                continue
            i += 1
        if i >= n:
            self._terminal_inert("git_without_subcommand", name, args)
            return
        sub = args[i].literal()
        if sub is None:
            self.structural("dynamic_git_subcommand", args[i].raw.text[:60])
            return
        rest = args[i + 1:]
        if sub == "rm":
            mark = len(self.boundaries)
            self._git_rm(rest, args[:i], direct)
            if any(b["verdict"] in _TERMINAL_SAFE
                   for b in self.boundaries[mark:]):
                self.cover(args[i])  # this `rm` was resolved as an index-only op
            return
        if sub in aliases:
            body = aliases[sub]
            body_src = self._alias_body_src(alias_words.get(sub), body)
            if body.startswith("!"):
                parts = [body_src.slice(1, len(body_src.text))]
            else:
                parts = [Src("git", [-1, -1, -1]), body_src]
            parts += [a.raw for a in rest]
            self.analyze_code(src_concat(parts), Env())
            return
        if sub in GIT_SUBCOMMANDS:
            # Operands of a known non-removal subcommand are data (paths, refs,
            # messages) — but `git submodule foreach '<removal>'` and
            # `git bisect run '<removal>'` hand a command line onward, so the
            # residual is proved rather than assumed.
            self.note_removal_position(SHAPE_SUBCOMMAND_RESOURCE, self.raw)
            self._terminal_inert(
                "git_non_removal_subcommand", "git " + sub, rest,
                data_opts=() if sub in GIT_PAYLOAD_FORWARDING_SUBCOMMANDS
                else GIT_DATA_OPTIONS)
            return
        # Unknown subcommand: it may be a user alias resolved from config or the
        # environment, whose body is not in the command text.
        self.scoped("git_unresolved_subcommand", "git " + sub)

    def _git_rm(self, rest, git_opts=(), direct=False):
        cached = unproven = False
        paths = []
        i = 0
        n = len(rest)
        while i < n:
            lit = rest[i].literal()
            if lit is None:
                self.scoped("dynamic_git_rm_argument", rest[i].raw.text[:60])
                return
            if lit == "--":
                paths += [w.literal() for w in rest[i + 1:]]
                break  # everything after is a pathspec, never an option
            if not lit.startswith("-") or lit == "-":
                paths.append(lit)
                i += 1
                continue
            if lit.startswith("--"):
                res = _resolve_long(lit.split("=", 1)[0], GIT_RM)
                if res is None:
                    self.scoped("unknown_option:" + lit, "git rm")
                    return
                if res == "--cached":
                    cached = True
                # forced, or pathspecs git reads from a file: nothing to prove at run time
                unproven = unproven or res in ("--force", "--pathspec-from-file")
                if res in GIT_RM["val"] and "=" not in lit:
                    i += 2
                    continue
                i += 1
                continue
            for ch in lit[1:]:
                if "-" + ch not in GIT_RM["bool"]:
                    self.scoped("unknown_option:-" + ch, "git rm")
                    return
            unproven = unproven or "f" in lit
            i += 1
        loc = [w.literal() for w in git_opts]  # kept only if they just locate the repository
        if None in loc or not all(x in _GIT_RM_LOCATION_OPTS | _GIT_RM_PATHSPEC_OPTS or "=" in x and x.split(
                "=", 1)[0] in _GIT_RM_LOCATION_OPTS - {"-C"} or loc[j - 1:j] and loc[j - 1] in _GIT_RM_LOCATION_OPTS
                for j, x in enumerate(loc)):
            loc = None
        if cached:
            # --cached removes from the index only; the working tree is untouched.
            self.note_removal_position(SHAPE_SUBCOMMAND_RESOURCE, self.raw)
            self.add(PROVEN_SAFE_REMOVAL, "git_rm_cached_index_only", "git rm --cached")
        elif unproven or not direct or loc is None or any(x is None or "~" in x for x in loc + paths):
            self.add(FORBIDDEN_REMOVAL, "git_rm_worktree", "git rm")
        else:
            # Recoverable; prove_git_rm checks the repository at run time.
            self.note_removal_position(SHAPE_SUBCOMMAND_RESOURCE, self.raw)
            self.git_rm.append({"git": loc, "paths": paths})
            self.add(PROVEN_SAFE_REMOVAL, "git_rm_recoverable", "git rm")

    # -- docker --------------------------------------------------------------

    def _h_docker(self, name, args, redirs, env, piped):
        i, err = split_opts(args, DOCKER_GLOBAL)
        if err == "missing_option_value":
            self.structural("missing_option_value", "docker")
            return
        if err:
            self.scoped(err, "docker")
            return
        self._docker_sub(name, args, i, env)

    _h_podman = _h_docker

    def _docker_sub(self, name, args, i, env):
        if i >= len(args):
            self._terminal_inert("docker_without_subcommand", name, args)
            return
        sub = args[i].literal()
        if sub is None:
            self.structural("dynamic_docker_subcommand", args[i].raw.text[:60])
            return
        if sub == "compose":
            j, err = split_opts(args[i + 1:], _spec(
                ("--ansi", "--dry-run", "--parallel", "--compatibility"),
                ("-f", "--file", "-p", "--project-name", "--project-directory",
                 "--profile", "--env-file")))
            if err:
                self.scoped(err, "docker compose")
                return
            self._docker_sub(name, args, i + 1 + j, env)
            return
        if sub in DOCKER_RESOURCE_NOUNS:
            self._docker_sub(name, args, i + 1, env)
            return
        if sub in DOCKER_RESOURCE_RM:
            # Removing a container / image / volume / network is a Docker
            # resource operation; it does not delete host filesystem paths.
            self.cover(args[i])  # this `rm` was resolved as a Docker resource op
            self.note_removal_position(SHAPE_SUBCOMMAND_RESOURCE, self.raw)
            self.add(PROVEN_SAFE_REMOVAL, "docker_resource_removal",
                     "%s %s" % (name, sub))
            return
        if sub in ("exec", "run", "create"):
            spec = DOCKER_EXEC if sub == "exec" else DOCKER_RUN
            j, err = split_opts(args[i + 1:], spec)
            if err == "missing_option_value":
                self.structural("missing_option_value", "docker " + sub)
                return
            if err:
                self.scoped(err, "docker " + sub)
                return
            payload = args[i + 1 + j + 1:]   # skip the container / image operand
            if not payload:
                self.add(PROVEN_INERT, "docker_exec_default_entrypoint", name)
                return
            self.eval_argv(payload, [], Env())
            return
        self.add(PROVEN_INERT, "docker_non_removal_subcommand", "%s %s" % (name, sub))


_IDENT_TAIL_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)$")
_QUOTE_OP_RE = re.compile(r"(%?q[qwrx]?)$")


# A placeholder for one expansion inside an inline program. A space keeps the
# characters on either side from joining into a name the scans would miss.
_PLACEHOLDER = " "
_MARK = "\x00"
_PLAIN_PARAM_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]|[*#?$!0-]")
_PLAIN_VALUE_RE = r"[A-Za-z0-9_./:%+,~-]*"


def _expansion_quoting(raw):
    """Shell double-quote state at each `$`/backtick expansion of a word, in order."""
    out = []
    t = raw
    n = len(t)
    i = 0
    dq = False
    while i < n:
        c = t[i]
        if c == "\\":
            i += 2
            continue
        if c == "'" and not dq:
            j = t.find("'", i + 1)
            i = n if j < 0 else j + 1
            continue
        if c == '"':
            dq = not dq
            i += 1
            continue
        if c == "$" and i + 1 < n:
            nxt = t[i + 1]
            if nxt == "'" and not dq:
                j = _find_ansi_end(t, i + 2)
                i = n if j < 0 else j + 1
                continue
            if nxt in "({[":
                out.append(dq)
                end = _match_pair(t, i + 1, nxt, {"(": ")", "{": "}", "[": "]"}[nxt])
                i = n if end < 0 else end
                continue
            if nxt.isalnum() or nxt in "_@*#?-$!":
                out.append(dq)
                i += 2
                if nxt.isalpha() or nxt == "_":
                    while i < n and (t[i].isalnum() or t[i] == "_"):
                        i += 1
                continue
            i += 1
            continue
        if c == "`":
            out.append(dq)
            j = i + 1
            while j < n and t[j] != "`":
                j += 2 if t[j] == "\\" else 1
            i = j + 1
            continue
        i += 1
    return out


def _marks_inside_string_literals(text):
    """True when every _MARK sits inside a program string literal.

    A literal here is '...', "..." or `...`, with backslash escapes. A mark
    after an unclosed `{` in the same literal is code (f-strings, `${}`,
    `#{}`), and a mark in a backtick literal is treated as code too.
    """
    quote = None
    brace = 0
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if quote is None:
            if c == _MARK:
                return False
            if c in "'\"`":
                quote, brace = c, 0
            i += 1
            continue
        if c == "\\":
            i += 2
            continue
        if c == _MARK:
            if quote == "`" or brace > 0:
                return False
        elif c == "{":
            brace += 1
        elif c == "}" and brace:
            brace -= 1
        elif c == quote:
            quote = None
        i += 1
    return quote is None


def _variable_set_unplainly(name, raw):
    """True when the command binds ``name`` to anything but one plain value."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return False
    esc = re.escape(name)
    for m in re.finditer(r"(?:^|[^A-Za-z0-9_])%s\+?=" % esc, raw):
        if not re.match(_PLAIN_VALUE_RE + r"(?:[\s;&|)]|$)", raw[m.end():]):
            return True
    binders = (r"(?:^|[\s;&|(])(?:read|mapfile|readarray|for|select|getopts"
               r"|printf\s+-v|declare|typeset|local|export|readonly|let)"
               r"\b[^;&|\n]*?(?:^|[^A-Za-z0-9_$])%s(?![A-Za-z0-9_=])" % esc)
    return re.search(binders, raw) is not None


def _program_with_placeholders(word, base, raw):
    """(program text with each expansion as a placeholder, fail-closed reason).

    The reason is empty when every expansion only supplies a value inside one
    of the program's string literals; otherwise it names the first expansion
    that could change the program itself.
    """
    quoting = _expansion_quoting(word.raw.text)
    k = 0
    why = ""
    chars = []
    for kind, s, _ in word.segs:
        if kind == "lit":
            chars.append(s.text)
            continue
        if kind == "ansi":
            chars.append(ansi_decode(s.text))
            continue
        chars.append(_MARK)
        if kind not in ("param", "sub", "arith"):
            why = why or "unquoted_" + kind
            continue
        quoted = quoting[k] if k < len(quoting) else False
        k += 1
        if not quoted:
            why = why or "unquoted_expansion"
        elif kind == "sub":
            why = why or "command_substitution"
        elif kind == "param":
            if not _PLAIN_PARAM_RE.fullmatch(s.text):
                why = why or "parameter_operator"
            elif _variable_set_unplainly(s.text, raw or ""):
                why = why or "variable_set_in_command"
    if len(quoting) != k:
        why = why or "expansion_count_mismatch"
    text = "".join(chars)
    if not why and not _marks_inside_string_literals(text):
        why = "expansion_outside_string_literal"
    return text.replace(_MARK, _PLACEHOLDER), why


def _enclosing_call(text, pos):
    """Name of the call that receives the string literal containing ``pos``.

    Used to decide whether a removal token inside inline interpreter code is
    PROVABLY inert. Only an affirmative match against OUTPUT_SINKS allows;
    an unrecognised or absent call name denies.
    """
    # Walk back out of the string literal the token sits in: path components
    # ("/bin/rm") and preceding words are part of the literal, not the call.
    k = pos
    while k > 0 and text[k - 1] not in "'\"`{[(,":
        k -= 1
    prefix = text[:k].rstrip()
    while prefix and prefix[-1] in "'\"`{[(<,+ \t":
        prefix = prefix[:-1].rstrip()
    m = _QUOTE_OP_RE.search(prefix)
    if m:
        # Perl/Ruby quote-like operators: print q{...}, puts %q{...}
        prefix = prefix[:m.start()].rstrip()
        while prefix and prefix[-1] in "'\"`{[(<,+ \t":
            prefix = prefix[:-1].rstrip()
    m = _IDENT_TAIL_RE.search(prefix)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def declared_authorizing_table():
    """The inertness declaration, in machine-readable form.

    Every program that may ALLOW a command whose argv names a removal front end
    appears here with a written justification, its proof kind, and its option
    model — including the argv-derived execution facilities it DOES own, which
    are the positions that deny.
    """
    out = {}
    for name, m in sorted(INERT_ARGV_CONSUMERS.items()):
        out[name] = {
            "justification": m["why"],
            "proof_kind": m["kind"],
            "argv_derived_execution_facility": sorted(m["exec"]),
            "option_model": {
                "bool": sorted(m["bool"]),
                "exec": sorted(m["exec"]),
                "val": sorted(m["val"]),
                "declared_data_value_justification": (_DATA_VAL_WHY if m["val"]
                                                      else ""),
                "undeclared_option_policy": (
                    "an option this model does not declare puts BOTH its "
                    "attached remainder and the following word in option-value "
                    "position, where a removal reference is UNRESOLVED, in "
                    "every one of the five option forms"),
            },
        }
    return out


def analyze(raw):
    result = {
        "schema": SCHEMA,
        "verdict": UNRESOLVED,
        "allowed": False,
        "reason": "",
        "boundaries": [],
        "census": {"obligations": 0, "discharged": 0, "undischarged": []},
    }
    if raw is None:
        result["reason"] = "no_input"
        return result

    az = Analyzer(raw)
    cen = census_mod.census(raw)

    if cen["fatal"]:
        result["verdict"] = UNRESOLVED
        result["reason"] = "census_fatal:" + ",".join(sorted(set(cen["fatal"])))[:120]
        result["census"]["obligations"] = len(cen["obligations"])
        return result

    az.analyze_code(Src.from_raw(raw), Env(), cond=True)

    undischarged = [ob for ob in cen["obligations"]
                    if (ob["kind"], ob["offset"]) not in az.discharged]
    result["census"] = {
        "obligations": len(cen["obligations"]),
        "discharged": len(cen["obligations"]) - len(undischarged),
        "undischarged": undischarged[:10],
    }
    if undischarged:
        az.add_terminal(UNRESOLVED, "census_obligation_undischarged",
                        ",".join("%s@%d" % (o["kind"], o["offset"])
                                 for o in undischarged[:5]))
    if az.overflow:
        az.add_terminal(UNRESOLVED, "boundary_limit_exceeded", str(MAX_BOUNDARIES))
    for b in az.boundaries if az.git_rm_unresolved else ():  # git rm's directory unknown
        if b["reason"] == "git_rm_recoverable":
            b.update(verdict=FORBIDDEN_REMOVAL, reason="git_rm_worktree",
                     detail="git rm after " + az.git_rm_unresolved)

    # OVERFLOW DENIES ITSELF: THE EXHAUSTION PATH IS DECIDED BY THE FLAG,
    # NOT BY A RECORDER.
    #
    # Both findings above go through ``add_terminal``, not ``Analyzer.add``,
    # which returns WITHOUT appending once ``len(self.boundaries) >=
    # MAX_BOUNDARIES``: at overflow, the one moment the marker decides the
    # outcome, ``add`` would drop it (the ``census_obligation_undischarged``
    # marker too), and the ranking loop would see only the first
    # MAX_BOUNDARIES boundaries. Inert padding followed by a filesystem removal
    # would then come back PROVEN_INERT — a fail-open cliff at the cap.
    #
    # Raising MAX_BOUNDARIES would only relocate the cliff. Any
    # bound on analysis work must have its exhaustion path decided by something
    # that still functions once the bound is hit, and only a flag read outside
    # the bounded structure qualifies — which is why the seed below reads
    # ``az.overflow`` and not the boundary list.
    #
    # The seed is monotone in _RANK, so it takes nothing away: a genuine
    # FORBIDDEN_REMOVAL inside the recorded prefix still outranks UNRESOLVED
    # and keeps its own reason, and no PROVEN_INERT boundary can lower the
    # seed. When ``az.overflow`` is False this block is inert, and
    # ``add_terminal`` behaves as ``add`` on a list that is not full.
    verdict = PROVEN_INERT
    reason = "no_execution_boundary_requires_removal_authorization"
    if az.overflow:
        verdict = UNRESOLVED
        reason = "boundary_limit_exceeded:%d" % MAX_BOUNDARIES
    for b in az.boundaries:
        if _RANK[b["verdict"]] > _RANK[verdict]:
            verdict = b["verdict"]
            reason = b["reason"] + (":" + b["detail"] if b["detail"] else "")
    result["verdict"] = verdict
    result["reason"] = reason
    result["allowed"] = verdict in _TERMINAL_SAFE
    result["boundaries"] = az.boundaries[:40]
    # The parse-derived positional shape(s) in which a removal reference was
    # COVERED. The ledger is keyed on (reason_code, positional_shape);
    # "none" means no inert-consumer argv walk authorized a removal reference,
    # so the proof rests entirely on the reason code's own site.
    # EVERY position placed by EVERY boundary that CARRIES THE FINAL VERDICT —
    # not just the first mention, and not the first co-winning boundary.
    #
    # Picking the first MENTION would let a benign leading operand supply the
    # proof for laxity sitting in an option value (`cat rm.txt --opt='<payload>'
    # f` would report `operand`, while the same command without `rm.txt`
    # reports `undeclared_option_value_attached`).
    #
    # Picking the first co-winning BOUNDARY is the same defect one level up:
    # `ack rm.txt --pager rm.txt T` would report ['operand'] while a second
    # PROVEN_INERT boundary recorded `declared_exec_option_value`. The union
    # can only ever report MORE positions, so it can only ever make coverage
    # harder, and it keeps such commands from reporting `unclassified`.
    #
    # Boundaries that do NOT carry the final verdict are still excluded: a
    # position belonging to a losing boundary is not a position the winning
    # proof is responsible for. Walk order is preserved so the ledger's
    # "counted once, under the shape the walk reached first" stays well defined.
    shapes = []
    for b in az.boundaries:
        if b["verdict"] != verdict:
            continue
        for shape in b["positional_shapes"]:
            if shape not in shapes:
                shapes.append(shape)
    result["removal_positional_shapes"] = shapes or [SHAPE_UNCLASSIFIED]
    result["removal_positional_shape"] = result["removal_positional_shapes"][0]
    if result["allowed"] and az.git_rm:
        result["git_rm_proof"] = {"cwds": az.git_rm_cwds, "removals": az.git_rm}
    return result


def prove_git_rm(result, cwd, home):
    """The run-time half of a non-forced git rm's proof. From each directory the command can run
    it in, git must resolve the repository and the pathspecs must match no gitlink (git removes a
    clean submodule's work tree with its ignored files, which no history holds); the repository
    must not be the harness home, whose running sessions run its current files (a registered hook
    also runs files no registration names, so no set derived from settings.json covers it). Git
    runs on the command's location options and pathspecs only, never on the command text."""
    proof = result.get("git_rm_proof")
    if not proof:
        return result
    home = {os.path.realpath(home), os.path.realpath(os.path.join(home, ".git"))}
    run = dict(capture_output=True, text=True, timeout=2, env=dict(os.environ, LC_ALL="C"))
    # `cd` resolves `..` lexically (-L) or after symlinks (-P): both directories are checked
    for d in dict.fromkeys([cwd] + proof["cwds"] + [os.path.normpath(x) for x in proof["cwds"]]):
        for rm in proof["removals"] if os.path.isdir(d) else ():
            git = ["git", "-c", "core.fsmonitor=false"] + rm["git"]
            try:
                where = subprocess.run(git + ["rev-parse", "--path-format=absolute", "--show-toplevel",
                                              "--git-common-dir"], cwd=d, **run)
                ls = subprocess.run(git + ["ls-files", "-s", "-z", "--full-name", "--"] + rm["paths"],
                                    cwd=d, **run)
            except (OSError, subprocess.SubprocessError):
                where = ls = None
            if where and where.returncode and "not a git repository" in where.stderr:
                continue  # no repository here: git rm removes nothing
            if where is None or where.returncode or ls.returncode:
                why = "git_rm_location_unresolved"
            elif home & {os.path.realpath(os.path.join(d, x)) for x in where.stdout.splitlines()}:
                why = "git_rm_in_harness_home"
            elif any(e.startswith("160000 ") for e in ls.stdout.split("\0")):
                why = "git_rm_gitlink"
            else:
                continue
            result.update(verdict=FORBIDDEN_REMOVAL, allowed=False, reason=why + ":" + d[:120])
            return result
    return result


def main():
    raw = os.environ.get("CMD_INPUT")
    if raw is None:
        raw = sys.stdin.read()
    try:
        payload = json.loads(sys.stdin.read() or "{}") if os.environ.get("CMD_PAYLOAD") == "stdin" else {}
        out = prove_git_rm(analyze(raw), payload.get("cwd") or os.getcwd(),
                           os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    except Exception as exc:  # analyzer failure is a DENY, never an allow
        out = {
            "schema": SCHEMA,
            "verdict": UNRESOLVED,
            "allowed": False,
            "reason": "analyzer_exception:" + type(exc).__name__,
            "boundaries": [],
            "census": {"obligations": 0, "discharged": 0, "undischarged": []},
        }
    json.dump(out, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
