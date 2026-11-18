#!/usr/bin/env python3
"""harness_temp_state.py -- one answer to "is this path harness state kept in a temp root?".

Is a resolved path harness temp state, and which temp root is it in: the one definition.

The harness keeps grants, consent flags, sentinels, counters, locks, stamps and
caches under the state dir (hooks/lib/harness_state_dir.py, default /tmp) and a
few more under $TMPDIR, /var/tmp or an override directory. LOCATIONS lists every
one (docs/reference/harness-temp-state.md has the inventory, each with the
path:line that writes or reads it). This module is the only definition a caller
needs of both questions:

  * temp_roots() / temp_root_of() / is_in_temp_root(): /tmp, /var/tmp, $TMPDIR,
    $CLAUDE_TMPDIR, $CLAUDE_CODE_TMPDIR (absolute values only), realpath'd and
    deduplicated, so /tmp and an alias such as /private/tmp are one root.
  * classify() / is_harness_state(): the LOCATIONS entry a path is, or None.

Matching is symlink-safe. A path is judged in two resolved views: its full
realpath (where a write through it lands) and its parent's realpath plus its
final component as written (the directory entry itself, so a symlink placed at
a state name is still that state entry). Either view matching is a match, so a
symlink pointing into harness state counts, and `..` is resolved, never trusted.
Names are matched under every name root (the state dir, every temp root, and the
override directories that hold state names), so a state name is state whatever
CLAUDE_STATE_DIR another process resolved. Whole-directory overrides
(CLAUDE_GIT_BLESSED_GRANT_DIR, CLAUDE_CAPABILITY_STATE_DIR, $XDG_RUNTIME_DIR/
claude-capability, CLAUDE_GRAPHIFY_CACHE_ROOT) count from the directory down.

Kinds: "control" is state a hook trusts (forging it changes a decision);
"scratch" is harness-managed scratch output (role scratch, codex outputs, the
graphify cache, ...). is_harness_state() answers for "control" unless
include_scratch=True; classify() returns either kind.

Pure: reads os.environ and the filesystem's symlinks and writes nothing. A
str, bytes or os.PathLike path is accepted; any other type raises TypeError.
Relative TMPDIR-style values count, against the cwd, for state detection
but never widen temp_roots(). Control names match case-insensitively. Known
limits (hard links, per-call variable redirects) are in the inventory doc.
No hook uses it yet.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Optional, Sequence, Tuple

_LIB = os.path.dirname(os.path.abspath(__file__))
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)
from harness_state_dir import harness_state_dir  # noqa: E402

CONTROL = "control"
SCRATCH = "scratch"

SYSTEM_TEMP_ROOTS: Tuple[str, ...] = ("/tmp", "/var/tmp")
# Variables naming a temp root (a scratch root mktemp and its callers honour).
TEMP_ROOT_VARS: Tuple[str, ...] = ("TMPDIR", "CLAUDE_TMPDIR", "CLAUDE_CODE_TMPDIR")
# Override variables naming a directory that holds state NAMES (matched like a temp root).
# A relative value is resolved against the cwd for state detection only; it never
# becomes a temp root.
NAME_ROOT_VARS: Tuple[str, ...] = (
    "TMP", "TEMP",                      # tempfile.gettempdir(): hooks/doc_sync/notice.py:241
    "CLAUDE_USERINTENT_SENTINEL_DIR",   # hooks/pretool-wrapper-userintent.py:82
    "CLAUDE_DAEMON_RESTART_GRANT_DIR",  # hooks/pretool-bash-safety.sh:25
    "CLAUDE_DOC_SYNC_STATE_ROOT",       # hooks/doc_sync/notice.py:238
)


@dataclass(frozen=True)
class Location:
    """One inventoried harness location.

    patterns: tuples of fnmatch globs, one per path component below a name root.
    tree: the matched entry and everything below it, else the exact entry only.
    tree_vars: override variables whose absolute value is this location's whole directory.
    """

    name: str
    kind: str
    patterns: Tuple[Tuple[str, ...], ...]
    tree: bool = False
    tree_vars: Tuple[str, ...] = ()


def _p(*components: str) -> Tuple[str, ...]:
    return tuple(components)


# Control state first: a path matching both kinds (a session dir's .owner) is control.
LOCATIONS: Tuple[Location, ...] = (
    Location("sentinel-grants", CONTROL, (_p("claude-grants"),), tree=True),
    # The /do consent flag (hooks/prompt-workflow.py:1210). Matched as the consent-flag
    # family, not by its full name: hooks/tests/test_do_consent_landing.py keeps that
    # name to its reader and writer only.
    Location("do-consent-flag", CONTROL, (_p("claude-*-consent-*.flag"),)),
    Location("tool-streak", CONTROL, (_p("claude-tool-streak-*.json"),)),
    Location("do-reservation", CONTROL, (_p("claude-do-resv-*"),)),
    Location("do-task-sidecar", CONTROL, (_p("claude-do-task-*.json"),)),
    Location("userintent-flag", CONTROL, (_p("claude-*-userintent-*.flag"),)),
    Location("helper-auth", CONTROL, (_p("claude-*-helper-auth-*.json"),)),
    Location("git-grant", CONTROL,
             (_p("claude-commit-grant-*.json"), _p("claude-push-grant-*.json"))),
    Location("commit-dispatch-attest", CONTROL, (_p("claude-commit-dispatch-*.json"),)),
    Location("commit-manifest", CONTROL, (_p("claude-commit-manifest-*.json"),)),
    Location("bulk-commit-sentinel", CONTROL, (_p("claude-bulk-commit-sentinel-*.json"),)),
    Location("commit-event-pointer", CONTROL, (_p("claude-commit-event-*.json"),)),
    Location("agentic-commit", CONTROL, (_p("agentic-commit"),), tree=True),
    Location("git-residual-override", CONTROL, (_p("claude-git-residual-override"),), tree=True),
    Location("runcode-watchdog-pid", CONTROL, (_p(".runcode-watchdog-*.pid"),)),
    Location("usage-snapshot-cache", CONTROL,
             (_p("claude-usage-snapshot-cache.json"), _p(".usage-cache-*"))),
    Location("worktree-guard-cache", CONTROL, (_p("worktree-guard-cache"),)),
    Location("git-fswatch-lock", CONTROL, (_p("git-fswatch-*.lock"),)),
    Location("tmpfs-pressure-counter", CONTROL, (_p("claude-pressure-warn-*"),)),
    Location("checkpoint-push-stamp", CONTROL, (_p(".checkpoint-push-*.ts"),)),
    Location("capability-state", CONTROL, (_p("claude-capability-*"),), tree=True,
             tree_vars=("CLAUDE_CAPABILITY_STATE_DIR",)),
    Location("git-blessed-grants", CONTROL, (_p("claude-git-blessed"),), tree=True,
             tree_vars=("CLAUDE_GIT_BLESSED_GRANT_DIR",)),
    Location("daemon-restart-grant", CONTROL, (_p("claude-allow-daemon-restart-*.flag"),)),
    Location("scratch-owner", CONTROL,
             (_p("*", ".owner"), _p("*", ".owner.*.tmp"),
              _p("claude-scratch", "*", ".owner"), _p("claude-scratch", "*", ".owner.*.tmp"))),
    Location("doc-sync-notices", CONTROL,
             (_p("*", "doc-sync-notices-*.json"), _p("*", ".doc-sync-notices-*.tmp"),
              _p("claude-scratch", "*", "doc-sync-notices-*.json"),
              _p("claude-scratch", "*", ".doc-sync-notices-*.tmp"))),
    # Harness-managed scratch.
    Location("claude-scratch", SCRATCH, (_p("claude-scratch", "*"),), tree=True),
    Location("codex-outputs", SCRATCH, (_p("codex-outputs"),), tree=True),
    Location("graphify-cache", SCRATCH, (_p("claude-graphify"),), tree=True,
             tree_vars=("CLAUDE_GRAPHIFY_CACHE_ROOT",)),
    Location("orchestrator-output", SCRATCH,
             tuple(_p(f"{stem}-*.json") for stem in (
                 "dev-output", "qa-output", "iteration-context", "cleanliness-output",
                 "style-output", "cleaner-output", "rule-output"))),
    Location("runtime-guard-err", SCRATCH, (_p("runtime-guard-*"),)),
    Location("grepguard-probe", SCRATCH, (_p("grepguard-probe-*"),), tree=True),
    Location("checkpoint-result", SCRATCH, (_p("checkpoint-result.*"),)),
    Location("hero-fixture", SCRATCH, (_p("claude-hero-fixture-*"),), tree=True),
    Location("tmp-cleanup-candidates", SCRATCH, (_p("tmp-cleanup-cands-*"),)),
)
_CAPABILITY = next(loc for loc in LOCATIONS if loc.name == "capability-state")


def _real(path: str) -> Optional[str]:
    try:
        return os.path.realpath(path)
    except (OSError, ValueError):
        return None


def _dedupe(paths) -> Tuple[str, ...]:
    out = []
    for path in paths:
        real = _real(path) if path else None
        if real and real not in out:
            out.append(real)
    return tuple(out)


def _abs_var(name: str) -> Optional[str]:
    """The variable's value when it is an absolute path, else None."""
    value = os.environ.get(name) or ""
    return value if os.path.isabs(value) else None


def _var_path(name: str, cwd: Optional[str]) -> Optional[str]:
    """The variable's value as a path a hook would use: absolute as is, relative
    joined to `cwd` (default: the process cwd); None when unset or empty."""
    value = os.environ.get(name) or ""
    if not value or "\x00" in value:
        return None
    if os.path.isabs(value):
        return value
    try:
        return os.path.join(cwd or os.getcwd(), value)
    except OSError:
        return None


def temp_roots() -> Tuple[str, ...]:
    """Every temp root, realpath'd and deduplicated: /tmp, /var/tmp, then each
    absolute TMPDIR / CLAUDE_TMPDIR / CLAUDE_CODE_TMPDIR. Fails closed: unset,
    empty or relative values add nothing, and neither does one resolving to "/"
    (it would make every path temp)."""
    roots = _dedupe(list(SYSTEM_TEMP_ROOTS) + [_abs_var(v) for v in TEMP_ROOT_VARS])
    return tuple(root for root in roots if root != os.sep)


def state_dir() -> str:
    """The realpath'd hook state dir (hooks/lib/harness_state_dir.py)."""
    root = harness_state_dir()
    return _real(root) or root


def name_roots(cwd: Optional[str] = None) -> Tuple[str, ...]:
    """Directories state names are matched under, realpath'd and deduplicated:
    the state dir, /tmp, /var/tmp, and every TEMP_ROOT_VARS / NAME_ROOT_VARS value
    (relative ones joined to `cwd`). Unlike temp_roots(), "/" is kept: a state
    name directly under it is still state."""
    return _dedupe([state_dir()] + list(SYSTEM_TEMP_ROOTS)
                   + [_var_path(v, cwd) for v in TEMP_ROOT_VARS + NAME_ROOT_VARS])


def tree_dirs(cwd: Optional[str] = None) -> Tuple[Tuple[str, Location], ...]:
    """(realpath'd directory, Location) for each whole-directory override set
    (relative values joined to `cwd`)."""
    out = []
    for loc in LOCATIONS:
        for var in loc.tree_vars:
            out.append((_var_path(var, cwd), loc))
    xdg = _var_path("XDG_RUNTIME_DIR", cwd)
    if xdg:
        out.append((os.path.join(xdg, "claude-capability"), _CAPABILITY))
    return tuple((_real(d), loc) for d, loc in out if d and _real(d))


def _as_str(path) -> str:
    """str of a str, bytes or os.PathLike path (bytes via os.fsdecode); raises
    TypeError for anything else, so a caller can never mistake it for "not state"."""
    raw = os.fspath(path)
    return os.fsdecode(raw) if isinstance(raw, bytes) else raw


def resolved_views(path, cwd: Optional[str] = None) -> Tuple[str, ...]:
    """The resolved views a path is judged in: its full realpath, and its
    parent's realpath joined with its final component as written (the entry
    itself; skipped when that component is "." or ".."). A relative path is
    taken from `cwd` (default: the process cwd). str, bytes and os.PathLike are
    accepted; any other type raises TypeError. Empty for "" and for a path
    holding NUL (no file can have that name)."""
    raw = _as_str(path)
    if not raw or "\x00" in raw:
        return ()
    try:
        if not os.path.isabs(raw):
            raw = os.path.join(cwd or os.getcwd(), raw)
        views = [os.path.realpath(raw)]
        head, tail = os.path.split(raw.rstrip(os.sep) or os.sep)
        if tail and tail not in (os.curdir, os.pardir):
            views.append(os.path.join(os.path.realpath(head), tail))
    except (OSError, ValueError):
        return ()
    return tuple(dict.fromkeys(views))


def _below(path: str, root: str, fold: bool = False) -> Optional[Tuple[str, ...]]:
    """Components of `path` below `root`; () when equal; None when outside.
    fold=True compares case-insensitively."""
    if fold:
        path, root = path.casefold(), root.casefold()
    if path == root:
        return ()
    prefix = root if root.endswith(os.sep) else root + os.sep
    if not path.startswith(prefix):
        return None
    return tuple(c for c in path[len(prefix):].split(os.sep) if c)


def _matches(rel: Sequence[str], loc: Location) -> bool:
    fold = loc.kind == CONTROL
    for pattern in loc.patterns:
        if len(rel) < len(pattern) or (not loc.tree and len(rel) != len(pattern)):
            continue
        if all(fnmatchcase(rel[i], glob.casefold() if fold else glob)
               for i, glob in enumerate(pattern)):
            return True
    return False


def classify(path, *, cwd: Optional[str] = None) -> Optional[Location]:
    """The LOCATIONS entry `path` is (control before scratch), else None.

    Control locations match case-insensitively (root and names), so a
    case-insensitive filesystem cannot hide state behind another spelling;
    on a case-sensitive one this errs toward "state"."""
    views = resolved_views(path, cwd)
    if not views:
        return None
    roots = name_roots(cwd)
    trees = tree_dirs(cwd)
    for loc in LOCATIONS:
        fold = loc.kind == CONTROL
        for view in views:
            for tree_dir, tree_loc in trees:
                if tree_loc is loc and _below(view, tree_dir, fold) is not None:
                    return loc
            for root in roots:
                rel = _below(view, root, fold)
                if rel and _matches(rel, loc):
                    return loc
    return None


def is_harness_state(path, *, include_scratch: bool = False,
                     cwd: Optional[str] = None) -> bool:
    """True when `path` resolves to (or names) harness control state, or with
    include_scratch=True any inventoried harness location."""
    loc = classify(path, cwd=cwd)
    return loc is not None and (include_scratch or loc.kind == CONTROL)


def temp_root_of(path, *, cwd: Optional[str] = None) -> Optional[str]:
    """The temp root `path` lies strictly below in either resolved view (the
    deepest when roots nest, e.g. TMPDIR under /var/tmp), else None. A temp
    root itself is not below one; "/" is never a temp root."""
    best = None
    for view in resolved_views(path, cwd):
        for root in temp_roots():
            if _below(view, root) and (best is None or len(root) > len(best)):
                best = root
    return best


def is_in_temp_root(path, *, cwd: Optional[str] = None) -> bool:
    """True when `path` lies strictly below a temp root in either resolved view."""
    return temp_root_of(path, cwd=cwd) is not None
