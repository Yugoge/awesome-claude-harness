#!/usr/bin/env python3
"""Config-file loading and STEP0 self-protection for the protected-runtime guard.

Depends on pathmatch (`_normalize_path`, `_strip_quotes`) + stdlib; references nothing from _core. The DATA_FILE_PATH
import-time reload contract is stated at _core's `_importlib.reload(_config)`.

Scope: the single generic `DATA_FILE_PATH` (env-overridable, read at MODULE-IMPORT
time so a test that sets the env then reloads the guard sees the fresh path),
`REQUIRED_KEYS`, `_read_config` / `_load_config` (schema-validated fail-closed load; a
schema-1 file missing list keys reads them as empty), `_config_problem` (the cause and
recovery a STEP1 refusal prints), and the STEP0
self-protection helpers (`_home_tilde_variant`, `_config_path_variants`,
`_config_ancestor_dirs`, `_config_or_ancestor_variants`, `_targets_config_file`)
that key on the hardcoded path — NOT on data loaded from the file they protect.
ZERO project identifiers beyond the generic POSIX system/home roots the matcher needs.
"""

from __future__ import annotations

import json
import os
from typing import Optional

# _targets_config_file needs the quote stripper and the path normalizer.
# Dual-context import (INV-3; the contract is stated at _core's first import block).
try:
    from .pathmatch import _normalize_path, _strip_quotes
except ImportError:  # executed under the top-level-script shim (no package)
    from pathmatch import _normalize_path, _strip_quotes  # type: ignore[no-redef]


# ── The single generic data-file path ────────────────────────────────────────
# Overridable for tests via env so the live machine file is never mutated by a
# test run. The path is generic; it carries no project identity. The
# default is $HOME-relative (~/.config/claude/...), so any home resolves its own
# config path.
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


SCHEMA_VERSION = 1

# What the guard's own messages call the file: the env key or the generic default, never
# the resolved path (an overriding path or the home directory can name the account).
FILE_LABEL = ("the protected-runtime file (CLAUDE_PROTECTED_RUNTIME_FILE, else "
              "~/.config/claude/protected-runtime.json)")

# The one repair, also what a fresh init writes: from the harness home, step 4 of init.
RECOVERY_COMMAND = "scripts/bootstrap --steps 4"


def _read_config():
    """Read and classify the data file: (cfg | None, problem | None, missing_keys).

    cfg is the file's object with every REQUIRED_KEYS list it lacks added as an empty
    list (exactly what `scripts/bootstrap` writes when it repairs the file), so a
    schema-1 file that predates a key, or lost one, keeps every declared entry and is
    read as declaring nothing more. Anything else that is not a valid schema-1 file
    (absent, unreadable, not JSON, not an object, another schema_version, a required
    key that is not a list) gives cfg None and a problem sentence naming the cause;
    the problem never repeats the file's path or its values beyond the schema_version
    number.
    """
    try:
        with open(DATA_FILE_PATH, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return None, "the file does not exist", []
    except OSError as exc:
        return None, "the file cannot be read (%s)" % (exc.strerror or "read error"), []
    except ValueError:
        return None, "the file is not valid JSON (or not UTF-8)", []
    if not isinstance(raw, dict):
        return None, "the file's top level is not a JSON object", []
    ver = raw.get("schema_version")
    if ver != SCHEMA_VERSION:  # as before: 1 (or 1.0 / true, which compare equal) is schema 1
        if "schema_version" not in raw:
            shown = "has no schema_version"
        elif isinstance(ver, int) and not isinstance(ver, bool):
            shown = "has schema_version %d" % ver
        else:
            shown = "has a schema_version that is not an integer"
        return None, "the file %s; this guard reads only schema_version %d" % (shown, SCHEMA_VERSION), []
    wrong = [k for k in REQUIRED_KEYS if k in raw and not isinstance(raw[k], list)]
    if wrong:
        return None, "key(s) %s are not JSON lists" % ", ".join(wrong), []
    missing = [k for k in REQUIRED_KEYS if k not in raw]
    cfg = dict(raw)
    for k in missing:
        cfg[k] = []
    return cfg, None, missing


def _load_config():
    """Return (config_dict | None). None means indeterminate (fail-closed).

    A schema-1 file missing some REQUIRED_KEYS is read with those keys as empty lists
    (see `_read_config`); every other defect stays indeterminate.
    """
    return _read_config()[0]


def _config_problem() -> str:
    """One sentence for an indeterminate policy: the cause and the exact recovery.

    Empty when the file loads. Names the file by FILE_LABEL only (no resolved path).
    """
    cfg, problem, _ = _read_config()
    if cfg is not None:
        return ""
    if problem == "the file does not exist":
        fix = "run `%s` from the harness home, which creates it with empty lists" % RECOVERY_COMMAND
    else:
        fix = ("fix it by hand to a JSON object with \"schema_version\": %d and each of %s as a list, keeping "
               "every entry it declares; or move it aside (keep it as the backup), run `%s` from the harness "
               "home to create an empty one, and copy the entries back. `%s` never rewrites such a file" % (
                   SCHEMA_VERSION, ", ".join(REQUIRED_KEYS), RECOVERY_COMMAND, RECOVERY_COMMAND))
    return "%s is unusable: %s. Recovery: %s." % (FILE_LABEL[0].upper() + FILE_LABEL[1:], problem, fix)


# ── STEP 0: config self-protection (hardcoded, generic path) ─────────────────

def _home_tilde_variant(path: str) -> Optional[str]:
    """Return the ``~/``-prefixed form of ``path`` iff it lives under the real
    user home (``$HOME`` / ``Path.home()``), else None.

    Generic (no ``/root``-specific branch): on a non-root home
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
        # Generic: add the ~/-prefixed variant for ANY ancestor
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
    # any token equal to the config path (a redirect target, cp/mv/rm/tee/sed -i/chmod/
    # chown/truncate/ln operands)
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
