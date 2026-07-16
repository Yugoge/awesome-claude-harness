#!/usr/bin/env python3
"""Config-file loading and STEP0 self-protection for the protected-runtime guard.

Depends on shell_lex (`_strip_quotes`, `_has_redirect_to`) + pathmatch
(`_normalize_path`) + stdlib; references nothing from _core. See
docs/reference/monolith-split-plan.md for the decomposition rationale (incl. the
`_ANCESTOR_STOP_ROOTS` cluster-completion move and the DATA_FILE_PATH import-time
reload contract) and the INV-3 dual-context import contract.

Scope: the single generic `DATA_FILE_PATH` (env-overridable, read at MODULE-IMPORT
time so a test that sets the env then reloads the guard sees the fresh path),
`REQUIRED_KEYS`, `_load_config` (schema-validated fail-closed load), and the STEP0
self-protection helpers (`_home_tilde_variant`, `_config_path_variants`,
`_config_ancestor_dirs`, `_config_or_ancestor_variants`, `_targets_config_file`)
that key on the hardcoded path — NOT on data loaded from the file they protect.
ZERO project identifiers beyond the generic POSIX system/home roots the matcher needs.
"""

from __future__ import annotations

import json
import os
from typing import Optional

# _targets_config_file matches a candidate token / redirect against the protected
# config-path variants, so it needs the phase-1 quote stripper + redirect scanner
# and the phase-3 path normalizer. Dual-context import (INV-3): config loads BOTH
# inside the lib.runtime_guard package (relative) AND as a sibling of the
# directly-executed _core.py script (absolute, where sys.path[0] is this dir).
try:
    from .shell_lex import _has_redirect_to, _strip_quotes
    from .pathmatch import _normalize_path
except ImportError:  # executed under the top-level-script shim (no package)
    from shell_lex import _has_redirect_to, _strip_quotes  # type: ignore[no-redef]
    from pathmatch import _normalize_path  # type: ignore[no-redef]


# ── The single generic data-file path ────────────────────────────────────────
# Overridable for tests via env so the live machine file is never mutated by a
# test run. The path is generic; it carries no project identity. WS1: the
# default is now $HOME-relative (~/.config/claude/...) rather than the author
# literal /root, so a fresh non-root home resolves its own config path.
DATA_FILE_PATH = os.environ.get(
    "CLAUDE_PROTECTED_RUNTIME_FILE",
    os.path.join(
        os.environ.get("HOME") or os.path.expanduser("~"),
        ".config", "claude", "protected-runtime.json",
    ),
)


# ── Config loading ───────────────────────────────────────────────────────────

REQUIRED_KEYS = (
    "protected_cmds", "protected_launch_paths", "protected_services",
    "protected_hotfiles", "protected_statefiles", "protected_endpoint_paths",
    "protected_proc_idents", "protected_global_bins",
    "protected_build_workspaces", "protected_build_paths",
)


def _load_config():
    """Return (config_dict | None). None means indeterminate (fail-closed)."""
    try:
        with open(DATA_FILE_PATH, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(cfg, dict):
        return None
    if cfg.get("schema_version") != 1:
        return None
    for k in REQUIRED_KEYS:
        if k not in cfg or not isinstance(cfg[k], list):
            return None
    return cfg


# ── STEP 0: config self-protection (hardcoded, generic path) ─────────────────

def _home_tilde_variant(path: str) -> Optional[str]:
    """Return the ``~/``-prefixed form of ``path`` iff it lives under the real
    user home (``$HOME`` / ``Path.home()``), else None.

    Generic (WS1 codex #4 — no ``/root``-specific branch): on a non-root home
    (``/home/alice/...``) the ``~/relative`` variant is generated exactly as it
    was for ``/root/...``, so the guard protects the same path written either
    way regardless of which user runs it.
    """
    home = os.environ.get("HOME")
    if not home:
        try:
            home = os.path.expanduser("~")
        except Exception:
            return None
    if not home or home == "~":
        return None
    home_prefix = home.rstrip("/") + "/"
    if path.startswith(home_prefix):
        return "~/" + path[len(home_prefix):]
    return None


def _config_path_variants() -> set:
    p = DATA_FILE_PATH
    variants = {p, os.path.normpath(p)}
    tilde = _home_tilde_variant(p)
    if tilde:
        variants.add(tilde)
    return variants


# Generic, too-broad ancestor roots whose mutation must NOT be treated as a config
# self-protection hit — protecting them would over-block routine filesystem ops on
# the home/system roots (`mv /root /backup`, `rm -rf /tmp`). The data file's OWN
# parent dir(s) BELOW these roots ARE protected. NO project names — generic POSIX
# system/home roots derived structurally.
_ANCESTOR_STOP_ROOTS = frozenset({
    "/", "/root", "/home", "/etc", "/usr", "/var", "/tmp", "/opt", "/bin",
    "/lib", "/lib64", "/sbin", "/srv", "/mnt", "/media", "/dev", "/proc",
    "/sys", "/run", "/boot",
})


def _config_ancestor_dirs() -> set:
    """Proper ancestor DIRECTORIES of the data file that are protected against
    mutation/move/delete — moving or removing any of them neuters the guard's
    config. Yields each ancestor directory up to (but EXCLUDING) the generic
    too-broad system/home roots in `_ANCESTOR_STOP_ROOTS`, so `/root/.config/claude`
    and `/root/.config` are protected while `/root` and `/` are not (a routine
    `mv /root /backup` must still ALLOW). Includes the `~/`-prefixed variant for a
    `/root/`-rooted path. Generic — no project identity (the path itself is the only
    hardcoded constant, already generic)."""
    out = set()
    norm = os.path.normpath(DATA_FILE_PATH)
    d = os.path.dirname(norm)
    while d and d not in _ANCESTOR_STOP_ROOTS:
        out.add(d)
        # Generic (WS1 codex #4): add the ~/-prefixed variant for ANY ancestor
        # under the real user home, not only /root/.
        tilde = _home_tilde_variant(d + "/")
        if tilde:
            out.add(tilde.rstrip("/"))
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return out


def _config_or_ancestor_variants() -> set:
    """The data-file path variants UNION its protected ancestor directories — the
    full self-protection target set for a mutation/move/delete."""
    return _config_path_variants() | _config_ancestor_dirs()


def _targets_config_file(simple_cmd: str, tokens: list) -> bool:
    cfg_variants = {_normalize_path(v) for v in _config_path_variants()}
    cfg_dir = os.path.dirname(DATA_FILE_PATH)
    # redirect to the config path
    rt = _has_redirect_to(simple_cmd)
    if rt and _normalize_path(rt) in cfg_variants:
        return True
    # any bareword token equal to the config path (cp/mv/rm/tee/sed -i/chmod/chown/truncate/ln)
    for tok in tokens:
        st = _strip_quotes(tok)
        if not st:
            continue
        norm = _normalize_path(st)
        if norm in cfg_variants:
            return True
        # mutation of the containing directory entry
        if norm == os.path.normpath(cfg_dir) and tokens and os.path.basename(_strip_quotes(tokens[0])) in (
            "rm", "rmdir", "mv", "chmod", "chown"
        ):
            return True
    return False
