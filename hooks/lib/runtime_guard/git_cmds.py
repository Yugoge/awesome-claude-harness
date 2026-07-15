#!/usr/bin/env python3
"""git destructive-subcommand argument parsing for the guard.

The git command-family parsing leaves split out of _core.py in the phase-5
monolith decomposition (2026-07-15). This module sits above the phase-1/3
leaves: it imports shell_lex (`_strip_quotes`) and pathmatch
(`_expand_leading_home`) plus the stdlib and references nothing from _core, so
_core imports these names back at load time without a circular dependency.
Relocating them here leaves _core's public surface identical (every
`from ..._core import _git_destructive_pathspecs` and every internal call --
including `_git_inspection_head`, which stays in _core and uses
`_GIT_GLOBAL_OPTS_WITH_ARG` -- still resolves) -- see
docs/reference/monolith-split-plan.md.

Scope: the pure argv PARSERS for a git invocation -- global-option-aware
subcommand location and `-C` chdir folding (`_git_subcommand_index`,
`_git_effective_cwd`), pathspec-magic stripping (`_strip_git_pathspec_magic`),
destructive-pathspec collection (`_git_destructive_pathspecs`), and the
destructive-mode predicate (`_git_is_destructive_invocation`) -- plus the generic
git verb/option lookup tables they key on.

The forward-referencing orchestrator `_git_destructive_pathspec_hits`
deliberately STAYS in _core: it calls `_resolve_rel` (a general path helper
resident in _core) and forward-references `_destructive_root_contains_protected`
(defined later in the decision engine), so lifting it would invert the dependency
into an import cycle -- the same pattern that keeps `_mutation_cand_hits` in
_core. Its moved callees are re-imported into _core, so every reference still
resolves. ZERO project identifiers.
"""

from __future__ import annotations

import os
from typing import Optional

# git argv parsers key on the phase-1 quote stripper and the phase-3 leading-home
# expander (for `git -C ~/dir`). Dual-context import (INV-3): git_cmds loads BOTH
# inside the lib.runtime_guard package (relative) AND as a sibling of the
# directly-executed _core.py script (absolute, where sys.path[0] is this dir).
try:
    from .shell_lex import _strip_quotes
    from .pathmatch import _expand_leading_home
except ImportError:  # executed under the top-level-script shim (no package)
    from shell_lex import _strip_quotes  # type: ignore[no-redef]
    from pathmatch import _expand_leading_home  # type: ignore[no-redef]


# git GLOBAL options (before the subcommand) that consume the FOLLOWING token as
# their argument (`git -C <dir> status`, `git -c k=v log`). Their operand must be
# skipped when locating the subcommand, else the operand (`<dir>`) is mistaken for
# the subcommand and a read-only `git -C <dir> status` is wrongly treated as a
# non-inspection command (which then mis-fires the anchor scan on the dir operand
# when the dir basename equals a protected command). Generic git CLI grammar, NOT
# project names.
_GIT_GLOBAL_OPTS_WITH_ARG = frozenset({
    "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path",
    "--super-prefix",
})


# Destructive git subcommands that DELETE / OVERWRITE / REVERT working-tree files
# under a pathspec (wiping or clobbering a protected bundle / build dir / statefile).
# `clean` removes untracked files; `restore`/`checkout`/`reset --hard` overwrite
# tracked files from the index/HEAD. Generic git verbs, NO project names.
_GIT_DESTRUCTIVE_SUBCMDS = frozenset({"clean", "restore", "checkout", "reset"})
# git global options (before the subcommand) consuming the next token as an operand
# (shared shape with `_GIT_GLOBAL_OPTS_WITH_ARG`, reused here).


def _git_subcommand_index(tokens: list, git_idx: int):
    """Return (subcmd, subcmd_token_index) for a git invocation whose head/exec
    token is at `git_idx`, skipping git GLOBAL options and their operands
    (`git -C <dir> clean …`). Returns (None, None) when no subcommand follows."""
    i = git_idx + 1
    n = len(tokens)
    skip_next = False
    while i < n:
        st = _strip_quotes(tokens[i])
        if skip_next:
            skip_next = False
            i += 1
            continue
        if not st:
            i += 1
            continue
        if st in _GIT_GLOBAL_OPTS_WITH_ARG:
            skip_next = True
            i += 1
            continue
        if st.startswith("-"):
            i += 1  # bare/fused global flag
            continue
        return (st, i)
    return (None, None)


def _git_effective_cwd(tokens: list, git_idx: int, cwd: Optional[str], cwd_det: bool):
    """Fold a git `-C <dir>` global option into the effective cwd (git runs as if
    started in <dir>). A dynamic `-C` operand ($/`/glob) yields cwd_det=False."""
    i = git_idx + 1
    n = len(tokens)
    while i < n:
        st = _strip_quotes(tokens[i])
        if st == "-C" and i + 1 < n:
            d = _expand_leading_home(_strip_quotes(tokens[i + 1]))
            if any(ch in d for ch in ("$", "`", "*", "?")):
                return (cwd, False)
            if os.path.isabs(d):
                return (os.path.normpath(d), True)
            if cwd:
                return (os.path.normpath(os.path.join(cwd, d)), cwd_det)
            return (os.path.normpath(d), cwd_det)
        if st.startswith("-C"):  # fused `-C<dir>`
            d = _expand_leading_home(_strip_quotes(st[2:]))
            if d and not any(ch in d for ch in ("$", "`", "*", "?")):
                if os.path.isabs(d):
                    return (os.path.normpath(d), True)
                if cwd:
                    return (os.path.normpath(os.path.join(cwd, d)), cwd_det)
                return (os.path.normpath(d), cwd_det)
        if st in _GIT_GLOBAL_OPTS_WITH_ARG:
            i += 2
            continue
        if st.startswith("-"):
            i += 1
            continue
        break
    return (cwd, cwd_det)


def _strip_git_pathspec_magic(spec: str):
    """Strip a leading git PATHSPEC-MAGIC prefix from a pathspec, returning
    (clean_path, repo_root_relative, ignore_case, is_exclude). Forms:
      • `:(top)<path>` / `:/<path>` — repo-root-relative (rel=True).
      • `:(icase)<path>` — case-insensitive match (ignore_case=True).
      • `:(exclude)<path>` / `:!<path>` / `:^<path>` — EXCLUDE pathspec (is_exclude=
        True): it REMOVES entries from the set, so it is NOT a positive destructive
        target.
      • `:(glob)<path>`, combined `:(top,glob,icase)<path>` — magic stripped, path kept.
    A pathspec with NO magic prefix is returned unchanged (rel/ic/exclude all False).
    Generic git pathspec grammar, no project names."""
    s = _strip_quotes(spec)
    repo_rel = ignore_case = is_exclude = False
    if s.startswith(":("):
        end = s.find(")")
        if end != -1:
            magic = s[2:end].split(",")
            if "top" in magic:
                repo_rel = True
            if "icase" in magic:
                ignore_case = True
            if "exclude" in magic:
                is_exclude = True
            s = s[end + 1:]
    elif s.startswith(":/"):
        repo_rel = True
        s = s[2:] or "."
    elif s.startswith(":!") or s.startswith(":^"):
        is_exclude = True
        s = s[2:]
    return (s, repo_rel, ignore_case, is_exclude)


def _git_destructive_pathspecs(tokens: list, sub_idx: int, subcmd: str) -> list:
    """Return (pathspec, repo_root_relative, ignore_case, is_exclude) for each
    PATHSPEC operand of a destructive git subcommand (the bare positional path
    arguments, honoring a `--` separator and parsing git pathspec-magic prefixes
    `:(glob)`/`:(top)`/`:(icase)`/`:(exclude)`/`:/`/`:!`). Subcommand options
    (`-f`/`-d`/`-x` for clean, `--hard`/`--soft` for reset, `--source=…`/`--staged`
    for restore, `-f`/`--force` for checkout) are skipped. A bare `git clean -fdx` /
    `git checkout -- .` with no POSITIVE path targets the WHOLE worktree; a single
    `(., …)` is returned so the cwd is resolved (a worktree-wide wipe at a protected
    cwd is in scope). An EXCLUDE pathspec (`:!`/`:(exclude)`) is returned with
    is_exclude=True; the caller must NOT treat it as a positive destructive target."""
    rest = tokens[sub_idx + 1:]
    out = []
    saw_dashdash = False
    for i, t in enumerate(rest):
        st = _strip_quotes(t)
        if st == "--":
            saw_dashdash = True
            continue
        if not saw_dashdash and st.startswith("-"):
            continue  # an option / option=value (fused) before the pathspec
        clean, repo_rel, ic, is_exclude = _strip_git_pathspec_magic(st)
        if not saw_dashdash:
            # `checkout <branch>` / `restore` without `--`: a bare token MIGHT be a
            # branch/ref, not a path. For checkout/restore we require a `--`
            # separator OR a token that looks path-like to treat it as a pathspec —
            # a plain branch name (`git checkout main`) is NOT a path op. An EXCLUDE
            # pathspec is always a pathspec (it has the `:!`/`:(exclude)` magic).
            if (subcmd in ("checkout", "restore") and not repo_rel and not is_exclude
                    and not ("/" in clean or clean in (".", "..") or clean.startswith("./") or clean.startswith("../"))):
                continue
        out.append((clean, repo_rel, ic, is_exclude))
    # a path-less destructive form (no POSITIVE pathspec — excludes don't count)
    # targets the worktree root (the effective cwd).
    if not any(not ex for (_p, _r, _i, ex) in out) and subcmd in ("clean", "checkout", "restore", "reset"):
        out.append((".", False, False, False))
    return out


def _git_is_destructive_invocation(tokens: list, sub_idx: int, subcmd: str) -> bool:
    """True if the git subcommand is in its DESTRUCTIVE mode:
      • clean   — requires `-f`/`--force` (git refuses to clean without it).
      • restore — always overwrites the worktree file from the index/source.
      • checkout— a pathspec checkout (`--` or a path operand) reverts the worktree
        file; a plain branch switch (`git checkout <branch>`) is NOT a path wipe.
      • reset   — requires `--hard` (only --hard touches the worktree)."""
    rest = [_strip_quotes(t) for t in tokens[sub_idx + 1:]]
    if subcmd == "clean":
        return any(t in ("-f", "--force") or (t.startswith("-") and not t.startswith("--") and "f" in t[1:]) for t in rest)
    if subcmd == "restore":
        return True
    if subcmd == "reset":
        return any(t == "--hard" for t in rest)
    if subcmd == "checkout":
        # destructive (worktree revert) only when a pathspec is present: a `--`
        # separator OR a path-like operand. A plain `git checkout <branch>` is a
        # branch switch (no worktree-file wipe) → not destructive here.
        if "--" in rest:
            return True
        return any(("/" in t or t in (".", "..") or t.startswith("./") or t.startswith("../"))
                   for t in rest if not t.startswith("-"))
    return False
