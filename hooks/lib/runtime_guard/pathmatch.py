#!/usr/bin/env python3
"""Path-normalization and segment-boundary glob matching for the guard.

Depends only on shell_lex (`_strip_quotes`) + stdlib; references nothing from
_core. See docs/reference/monolith-split-plan.md for the decomposition rationale
(incl. why `_mutation_cand_hits` stays in _core) and the INV-3 dual-context
import contract.

Scope: `$HOME`/`~` expansion, logical path normalization, glob->segment-boundary
regex translation, shell-glob detection / parent extraction, and the
protected-glob intersection predicates (`_path_matches_any`, `_path_under_any`,
the `_any_token_*` token scanners) -- the shared matching layer every downstream
destructive-command analyzer calls.
ZERO project identifiers.
"""

from __future__ import annotations

import os
import re
from typing import Optional

# Only the phase-1 quote stripper is needed here. Dual-context import (INV-3) --
# see docs/reference/monolith-split-plan.md.
try:
    from .shell_lex import _strip_quotes
except ImportError:  # executed under the top-level-script shim (no package)
    from shell_lex import _strip_quotes  # type: ignore[no-redef]


# ── Path normalization + segment-boundary suffix matching ──────────────────

def _expand_leading_home(raw: str) -> str:
    """Expand a LEADING deterministic `$HOME`/`${HOME}`/`~` to the absolute home dir,
    leaving the rest untouched. Used at cwd-resolution sites (cd / wrapper -C /
    git -C) so a `cd "$HOME/.config/<app>"` / `env -C ~/.config/<app>` chdir resolves
    to the protected path instead of being treated as dynamic-indeterminate. A value
    with NO leading home prefix (or a non-HOME var like `$HOMEDIR`) is returned
    unchanged. Generic — `$HOME`/`~` are well-defined shell constructs, no project
    names."""
    p = _strip_quotes(raw)
    home = os.environ.get("HOME")
    if home:
        if p.startswith("${HOME}"):
            return home + p[len("${HOME}"):]
        if p.startswith("$HOME") and (len(p) == 5 or not (p[5].isalnum() or p[5] == "_")):
            return home + p[len("$HOME"):]
    # leading `~` / `~user`: expanduser resolves `~` (HOME) and `~root`/`~user` (the
    # named user's home) deterministically. If the user is unknown it returns the
    # string unchanged (no spurious expansion).
    if p.startswith("~"):
        exp = os.path.expanduser(p)
        if exp != p:
            return exp
    return p


def _normalize_path(raw: str) -> str:
    p = _strip_quotes(raw)
    # expand a LEADING deterministic $HOME / ${HOME} (the only shell variable whose
    # value the engine can resolve without running the shell) so a mutation written
    # as `$HOME/.config/<app>/…` resolves to the same protected path as `~/…` and the
    # absolute form (`mv "$HOME/.config/<app>" /tmp` → the protected config dir). Only
    # a LEADING $HOME/${HOME} is expanded (a mid-path var is non-deterministic). Other
    # variables/command-subst are left intact (the dynamic-token paths fail closed for
    # protected verb families elsewhere). NO project names.
    home = os.environ.get("HOME")
    if home:
        if p.startswith("${HOME}"):
            p = home + p[len("${HOME}"):]
        elif p.startswith("$HOME") and (len(p) == 5 or not (p[5].isalnum() or p[5] == "_")):
            p = home + p[len("$HOME"):]
    if p.startswith("~"):
        p = os.path.expanduser(p)
    # collapse ./ and ../ logically without touching the filesystem
    p = os.path.normpath(p)
    return p


def _glob_to_segment_regex(glob: str) -> re.Pattern:
    """Translate a data-file glob into a segment-boundary SUFFIX regex.

    `**/a/b` matches any path ending in segments .../a/b (absolute or relative).
    `*` matches within a single segment (no /). `**` matches across segments.
    A leading absolute glob (/usr/bin/x*) anchors at string start.
    """
    g = glob
    anchored = g.startswith("/")
    # Tokenize the glob into literal/star chunks.
    out = []
    i = 0
    n = len(g)
    while i < n:
        if g[i:i + 2] == "**":
            # ** -> match anything including /
            out.append(".*")
            i += 2
            # swallow a following slash so **/x doesn't force a leading /
            if i < n and g[i] == "/":
                out.append("/?")
                i += 1
        elif g[i] == "*":
            out.append("[^/]*")
            i += 1
        else:
            out.append(re.escape(g[i]))
            i += 1
    body = "".join(out)
    if anchored:
        pattern = "^" + body + "$"
    else:
        # suffix match at a segment boundary: start of string OR after a '/'
        pattern = "(^|/)" + body + "$"
    return re.compile(pattern)


# Shell-glob metacharacters that make a COMMAND-SIDE token a wildcard the shell
# expands before the program sees it (`<dir>/*`, `<dir>/index.*`, `<dir>/[ab]*`,
# `<dir>/{a,b}`). A token carrying any of these is NOT a literal path — it SELECTS
# a set of entries under its glob-parent directory. Generic POSIX glob syntax.
_SHELL_GLOB_METACHARS = ("*", "?", "[", "{")


def _has_shell_glob(tok: str) -> bool:
    return any(ch in tok for ch in _SHELL_GLOB_METACHARS)


def _glob_parent(tok: str) -> Optional[str]:
    """The directory portion of a command-side glob token UP TO the last `/` before
    the FIRST path segment that carries a shell-glob metachar. For `<dir>/*` the
    glob-parent is `<dir>`; for `<dir>/sub/index.*` it is `<dir>/sub`; for
    `<dir>/a*/b` it is `<dir>` (the wildcard is in the `a*` segment). A token with a
    metachar in its FIRST segment (`*`, `a*/b`) has no determinate parent → None.
    Returns the normalized directory (no trailing slash) or None."""
    st = _strip_quotes(tok)
    if not _has_shell_glob(st):
        return None
    segs = st.split("/")
    parent_segs = []
    for i, seg in enumerate(segs):
        if _has_shell_glob(seg):
            break
        parent_segs.append(seg)
    if i == 0:  # first segment already carries a metachar -> no determinate parent
        return None
    parent = "/".join(parent_segs)
    if not parent:
        return None
    return _normalize_path(parent)


def _glob_token_selects_protected(tok: str, globs: list) -> bool:
    """HEAD-AGNOSTIC: True if a command-side token that carries shell-glob metachars
    (`<dir>/*`, `<dir>/index.*`, `<protectedfile-or-dir>/*`) would EXPAND to select a
    path matching one of `globs` — the protected file itself, a protected ancestor /
    container directory, OR a protected file located under the glob's parent dir.

    The shell expands `<dir>/*` to every entry of `<dir>`; if `<dir>` is (or is under)
    a protected directory glob, or a protected FILE glob lives directly under `<dir>`,
    the expansion mutates a protected path. Computed by taking the token's GLOB-PARENT
    (the dir portion before the first metachar segment) and BLOCKING when:
      (a) the glob-parent equals / is under a protected dir glob (ancestor/container),
      (b) a protected glob (file or dir) names a path AT or UNDER the glob-parent
          (so `<cfgdir>/*` selects `<cfgdir>/<datafile>` and `<distdir>/*` selects the
          bundle), OR
      (c) the glob token, treated as a literal-ish path, already segment-matches a
          protected glob (the `**`-suffix matcher tolerates a trailing `/*`).
    A glob whose parent matches NOTHING protected (`/tmp/scratch/*`) selects nothing
    protected → no match (the over-block boundary the controls require). Generic — the
    protected set is entirely data-file driven."""
    parent = _glob_parent(tok)
    if parent is None:
        return False
    # (a)+(b): does any protected glob name a path AT or UNDER the glob-parent dir?
    # `_path_under_any(parent, globs)` covers the glob-parent being (or under) a
    # protected dir glob; the reverse — a protected glob under the glob-parent —
    # is checked by asking whether the protected glob, stripped to its literal
    # prefix, lives under `parent`.
    if _path_under_any(parent, globs):
        return True
    for g in globs:
        gp = _glob_literal_prefix(g)
        if gp is None:
            continue
        # the protected target's literal directory prefix is AT or UNDER the
        # glob-parent → the `<parent>/*` expansion selects it.
        if _dir_equal_or_under(gp, parent):
            return True
    return False


def _glob_literal_prefix(glob: str) -> Optional[str]:
    """The leading LITERAL directory of a protected glob — the segments before the
    first `*`/`?`/`[`/`{` segment, with a trailing filename segment dropped only when
    it itself is literal (so `**/packages/<pkg>/dist/index.mjs` → the protected file's
    parent `…/dist` is derivable via the caller; here we return the literal DIR prefix
    `''` for a leading-`**` glob, or the absolute literal head for an anchored glob).
    Returns None when the glob has no usable literal directory prefix (leading
    wildcard)."""
    segs = glob.split("/")
    lit = []
    for seg in segs:
        if _has_shell_glob(seg) or seg == "**":
            break
        lit.append(seg)
    # drop a trailing literal FILENAME segment (has a dot, no following wildcard) so
    # the prefix is a directory: `/usr/bin/<cmd>` keeps `/usr/bin`; but an anchored
    # dir glob `/root/.config/app` keeps all segments. We cannot tell file vs dir
    # syntactically, so keep the full literal prefix AND its parent as candidates by
    # returning the full literal prefix; `_dir_equal_or_under` tests dir containment.
    prefix = "/".join(lit)
    return prefix or None


def _dir_equal_or_under(child: str, ancestor: str) -> bool:
    """True if directory `child` equals or is located under directory `ancestor`
    (both already normalized, comparing on segment boundaries — `/a/bc` is NOT under
    `/a/b`). The filesystem ROOT `/` is the ancestor of every absolute path
    (`find / -delete` wipes everything), so it is special-cased (rstrip would
    otherwise reduce it to '' and miss)."""
    cn = _normalize_path(child)
    an = _normalize_path(ancestor)
    # the filesystem root contains every absolute child.
    if an == "/":
        return os.path.isabs(cn)
    c = cn.rstrip("/")
    a = an.rstrip("/")
    if not a or not c:
        return False
    if c == a:
        return True
    return c.startswith(a + "/")


def _path_matches_any(path: str, globs: list) -> bool:
    norm = _normalize_path(path)
    candidates = {norm, path, _strip_quotes(path)}
    real = None
    try:
        if os.path.exists(norm):
            real = os.path.realpath(norm)
            candidates.add(real)
    except OSError:
        pass
    for glob in globs:
        rx = _glob_to_segment_regex(glob)
        for cand in candidates:
            if rx.search(cand):
                return True
    # COMMAND-SIDE shell-glob token (`<dir>/*`, `<protectedfile-or-dir>/*`): a literal
    # match above fails (the `*` is normalized literally), but the shell would expand
    # the token to select entries under its glob-parent. Intersect the glob-parent
    # against the protected globs so a glob mutation of a protected dir's contents is
    # caught (`mv <cfgdir>/* …`, `cp <distdir>/* …`). A glob selecting nothing
    # protected (`/tmp/scratch/*`) does not match.
    if _has_shell_glob(_strip_quotes(path)) and _glob_token_selects_protected(path, globs):
        return True
    return False


def _any_token_path_matches(tokens: list, globs: list) -> bool:
    for tok in tokens:
        st = _strip_quotes(tok)
        if not st or st.startswith("-"):
            continue
        if _path_matches_any(st, globs):
            return True
    return False


def _path_under_any(path: str, dir_globs: list) -> bool:
    """True if `path` equals OR is located under a directory matching a dir glob.

    A build-path glob like `**/packages/<pkg>` is a DIRECTORY; a token such as
    `packages/<pkg>/tsconfig.json` lives under it and must match.
    """
    norm = _normalize_path(path)
    parts = norm.split("/")
    # test the path itself and each ancestor against the dir globs as a suffix
    for i in range(len(parts), 0, -1):
        prefix = "/".join(parts[:i])
        if not prefix:
            continue
        if _path_matches_any(prefix, dir_globs):
            return True
    return False


def _any_token_under(tokens: list, dir_globs: list) -> bool:
    for tok in tokens:
        st = _strip_quotes(tok)
        if not st or st.startswith("-"):
            continue
        if _path_under_any(st, dir_globs):
            return True
    return False
