#!/usr/bin/env python3
"""find/fd destructive-command argument parsing for the guard.

The find/fd command-family parsing leaves split out of _core.py in the phase-5
monolith decomposition (2026-07-15). This module sits above the phase-1/2/3
leaves: it imports shell_lex (`_strip_quotes`) and pathmatch
(`_glob_to_segment_regex`, `_has_shell_glob`) plus the stdlib and references
nothing from _core, so _core imports these names back at load time without a
circular dependency. Relocating them here leaves _core's public surface
identical (every `from ..._core import _find_path_operands` and every internal
call still resolves) -- see docs/reference/monolith-split-plan.md.

Scope: the pure argv PARSERS for a find/fd invocation -- path-operand and fd
search-dir collection (`_find_path_operands`, `_fd_positional_roots`), PATH/NAME
predicate-value extraction (`_find_predicate_values`), and the protected-basename
predicate matcher (`_glob_basenames`, `_name_value_matches_protected`) -- plus the
generic find/fd option/predicate lookup tables they key on.

The two forward-referencing orchestrators deliberately STAY in _core:
`_find_destructive_target_hits` and `_find_filter_exonerates_reverse` both call
`_resolve_rel` (a general path helper resident in _core) and the former also
forward-references `_destructive_root_contains_protected` (defined later in the
decision engine), so lifting either would invert the dependency into an import
cycle -- the same pattern that keeps `_mutation_cand_hits` in _core. Their moved
callees are re-imported into _core, so every reference still resolves.
`_find_is_destructive` also stays: its `_FIND_EXEC_MUTATION_VERBS` table derives
from `_STEP0_MUTATION_HEADS`, a shared STEP0/anchor constant resident in _core.
ZERO project identifiers.
"""

from __future__ import annotations

import os
import re

# find/fd argv parsers key on the phase-1 quote stripper and the phase-3
# basename-glob matchers. Dual-context import (INV-3): find_cmds loads BOTH
# inside the lib.runtime_guard package (relative) AND as a sibling of the
# directly-executed _core.py script (absolute, where sys.path[0] is this dir).
try:
    from .shell_lex import _strip_quotes
    from .pathmatch import _glob_to_segment_regex, _has_shell_glob
except ImportError:  # executed under the top-level-script shim (no package)
    from shell_lex import _strip_quotes  # type: ignore[no-redef]
    from pathmatch import _glob_to_segment_regex, _has_shell_glob  # type: ignore[no-redef]


# find GLOBAL options that PRECEDE the path operands: the no-arg position/symlink
# options (`-H`/`-L`/`-P`), the `-D <debugopts>` and `-O<level>` forms. These come
# BEFORE the paths, so the path scan must skip them (not stop at them). Generic
# find grammar, no project names.
_FIND_GLOBAL_NOARG_OPTS = frozenset({"-H", "-L", "-P"})
_FIND_GLOBAL_ARG_OPTS = frozenset({"-D"})
# pre-path POSITION options that take ONE numeric/string arg and may appear before
# the path on some `find` builds / fd (`-maxdepth N` / `-mindepth N`). Skipped with
# their argument so a path AFTER them is still recognized.
_FIND_PREPATH_ARG_OPTS = frozenset({"-maxdepth", "-mindepth", "--max-depth", "--min-depth"})


# fd options that consume ONE following VALUE (so the value is not mistaken for a
# search-dir positional). fd's search DIRECTORIES are positionals AFTER the pattern,
# unlike find where roots come first — so the root-intersection scope must collect
# fd positionals that follow the glob/option args. Generic fd grammar.
_FD_OPTS_WITH_ARG = frozenset({
    "-g", "--glob", "-e", "--extension", "-t", "--type", "-d", "--max-depth",
    "--min-depth", "-E", "--exclude", "-S", "--size", "--changed-within",
    "--changed-before", "--owner", "-c", "--color", "-j", "--threads",
    "-x", "--exec", "-X", "--exec-batch", "--max-results", "-p", "--full-path",
})


def _fd_positional_roots(tokens: list, fd_idx: int) -> list:
    """Collect fd SEARCH-DIRECTORY positionals — the bareword operands that are NOT a
    value of a value-consuming fd option and NOT the (first) pattern. fd's search dirs
    come AFTER the pattern (`fd -g <glob> <dir1> <dir2> -X rm`), so they are missed by
    `_find_path_operands` (which stops at the first option). Used ONLY to scope the
    basename-predicate root-intersection for fd. Conservative: a bareword that looks
    PATH-like (absolute, or contains '/', or '.'/'..') is treated as a search dir; a
    bare pattern stem without a slash is left out (it's the search pattern, already
    handled as the predicate value). The `-x`/`-X` exec COMMAND and its args are
    excluded (everything after `-x`/`-X` is the executed command, not a search dir)."""
    rest = tokens[fd_idx + 1:]
    out = []
    i = 0
    n = len(rest)
    while i < n:
        st = _strip_quotes(rest[i])
        if st in ("-x", "--exec", "-X", "--exec-batch"):
            break  # everything after is the executed command, not a search dir
        if st in _FD_OPTS_WITH_ARG:
            i += 2
            continue
        if st.startswith("-") and "=" in st:
            i += 1
            continue
        if st.startswith("-"):
            i += 1
            continue
        # a path-like bareword positional is a search directory.
        if "/" in st or st in (".", "..") or st.startswith("./") or st.startswith("../") or os.path.isabs(st):
            out.append(st)
        i += 1
    return out


def _find_path_operands(tokens: list, find_idx: int) -> list:
    """Return find/fd PATH operands. The path operands come after the head and any
    GLOBAL options (`-H`/`-L`/`-P`, `-D arg`, `-O*`) and certain pre-path position
    options (`-maxdepth N`), and BEFORE the first real predicate/expression. Honors
    `--` (everything after is a path until a predicate). Returns the explicit path
    operands; an empty list means the find has NO explicit path (the caller treats
    that as the implicit `.` = cwd via `_find_implicit_cwd_target`).

    Examples: `find -L <p> -delete` -> [<p>]; `find -maxdepth 1 <p> -delete` ->
    [<p>]; `find -- <p> -delete` -> [<p>]; `find <p1> <p2> -delete` -> [p1,p2];
    `find -delete` (path-less) -> []."""
    rest = tokens[find_idx + 1:]
    out = []
    i = 0
    n = len(rest)
    saw_dashdash = False
    while i < n:
        st = _strip_quotes(rest[i])
        if st == "--":
            saw_dashdash = True
            i += 1
            continue
        if not saw_dashdash:
            # skip leading GLOBAL / pre-path options (with their args) so the path
            # AFTER them is still seen.
            if st in _FIND_GLOBAL_NOARG_OPTS or st.startswith("-O"):
                i += 1
                continue
            if st in _FIND_GLOBAL_ARG_OPTS:
                i += 2  # `-D <debugopts>`
                continue
            if st in _FIND_PREPATH_ARG_OPTS:
                i += 2  # `-maxdepth N`
                continue
            if st.startswith("-") or st in ("(", ")", "!"):
                # a real predicate / expression begins -> path operands done.
                break
        else:
            # after `--`: a predicate still terminates the path list.
            if st.startswith("-") or st in ("(", ")", "!"):
                break
        if st:
            out.append(st)
        i += 1
    return out


# find/fd PREDICATE options whose VALUE is a full-PATH selector (matched against
# the whole path): GNU find `-path`/`-wholename`/`-ipath`/`-iwholename`, fd
# `-p`/`--full-path`. A destructive find selecting a protected path by one of these
# (`find /root -path <protectedfile> -delete`) must BLOCK even though the positional
# root is a generic ancestor (`/root`). Generic find/fd grammar, no project names.
_FIND_PATH_PREDICATES = frozenset({
    "-path", "-wholename", "-ipath", "-iwholename", "-p", "--full-path",
})
# find/fd PREDICATE options whose VALUE is a BASENAME selector (matched against the
# entry's filename only): `-name`/`-iname`, fd `-g`/`--glob` (fd globs basenames by
# default). A destructive find selecting a protected file BY NAME
# (`find /root -name <basename> -delete`) must BLOCK.
_FIND_NAME_PREDICATES = frozenset({"-name", "-iname", "-g", "--glob"})


# case-INSENSITIVE find predicate spellings (`-iname`/`-ipath`/`-iwholename`). A
# value matched by one of these must compare case-folded, else `find -iname
# INDEX.MJS -delete` under-blocks. Generic find grammar.
_FIND_CASE_INSENSITIVE_PREDS = frozenset({"-iname", "-ipath", "-iwholename"})


def _find_predicate_values(tokens: list, find_idx: int):
    """Yield (kind, value, ignore_case) for every find/fd PATH/NAME predicate value
    after the head: kind is 'path' (`-path`/`-wholename`/`-ipath`/`-iwholename`/fd
    `-p`) or 'name' (`-name`/`-iname`/fd `-g`). `ignore_case` is True for the `-i*`
    spellings (case-folded comparison). Honors both the separated (`-path <v>`) and
    fused (`-path=<v>`) forms. Used so a destructive find that selects its victim by a
    predicate — not a positional root — is still seen
    (`find /root -path <protected> -delete`, `find . -iname INDEX.MJS -delete`)."""
    rest = tokens[find_idx + 1:]
    i = 0
    n = len(rest)
    while i < n:
        st = _strip_quotes(rest[i])
        flag = st
        val = None
        if "=" in st and st.startswith("-"):
            flag, val = st.split("=", 1)
        ic = flag in _FIND_CASE_INSENSITIVE_PREDS
        if flag in _FIND_PATH_PREDICATES:
            if val is None and i + 1 < n:
                val = _strip_quotes(rest[i + 1]); i += 1
            if val:
                yield ("path", val, ic)
        elif flag in _FIND_NAME_PREDICATES:
            if val is None and i + 1 < n:
                val = _strip_quotes(rest[i + 1]); i += 1
            if val:
                yield ("name", val, ic)
        i += 1


def _glob_basenames(globs: list) -> set:
    """The set of BASENAME components of protected globs (the last `/`-segment),
    dropping pure-wildcard basenames. Lets a `-name <basename>` predicate match a
    protected file selected by filename (`-name protected-runtime.json`,
    `-name index.mjs`)."""
    out = set()
    for g in globs:
        base = g.rsplit("/", 1)[-1]
        if base and set(base) - set("*?[]{}"):  # has a literal component
            out.add(base)
    return out


def _name_value_matches_protected(name_glob: str, globs: list, ignore_case: bool = False) -> bool:
    """True if a `-name`/`-iname`/fd `-g` BASENAME glob selects a protected file's
    basename. Matches in EITHER direction (the predicate is a glob; the protected
    basename is a glob): the predicate's literal stem equals a protected basename, or
    the predicate glob would expand to a protected basename. `ignore_case` folds both
    sides (for `-iname`). Conservative — a pure-wildcard predicate (`-name '*'`)
    matches nothing here (it would over-block every destructive find; the positional-
    root scan already covers the dir case)."""
    nv = _strip_quotes(name_glob)
    if not nv or set(nv) <= set("*?[]{}."):
        return False
    flags = re.IGNORECASE if ignore_case else 0
    rx = re.compile(_glob_to_segment_regex(nv).pattern, flags)
    nv_cmp = nv.casefold() if ignore_case else nv
    for base in _glob_basenames(globs):
        base_cmp = base.casefold() if ignore_case else base
        # the protected basename matches the predicate glob, OR the predicate glob's
        # literal stem IS the protected basename.
        if rx.search(base) or nv_cmp == base_cmp:
            return True
        # the protected basename is itself a glob (`<cmd>*`) — does the predicate's
        # literal value fall under it?
        if _has_shell_glob(base) and re.compile(_glob_to_segment_regex(base).pattern, flags).search(nv):
            return True
    return False
