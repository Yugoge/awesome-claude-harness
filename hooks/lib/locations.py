#!/usr/bin/env python3
"""locations.py -- the one place that answers where things are.

What is a device or system temp, where the harness's roots are, what lies in which directory.
A decision about a location asks here: where the harness home, the project, the state root and
the temp root are, whether a path lies in a directory, which Claude configuration folder or spec
root it is in. No other file of hooks/ or scripts/ compares a path with an absolute system
directory or lists one (tests/test_location_literals.py): the literals below are the only copy.
Pure: reads os.environ and the filesystem, writes nothing.
"""

from __future__ import annotations

import os
import re
from typing import Optional, Tuple
from pathlib import Path

try:
    from .harness_state_dir import harness_state_dir
except ImportError:  # loaded outside its package (by path, or from hooks/lib): its own directory holds it
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from harness_state_dir import harness_state_dir

# -- the literals --------------------------------------------------------------------------
DEVICE_DIR = "/dev"
SHM_DIR = "/dev/shm"                              # the shared-memory tmpfs mounted in it
NULL_DEVICE = "/dev/null"
STD_SINKS = frozenset({NULL_DEVICE, "/dev/stdout", "/dev/stderr"})
TERMINAL_SINKS = STD_SINKS | {"/dev/tty"}
FD_DIR = "/dev/fd/"                               # /dev/fd/N: a descriptor of the process
FD_PATH = re.compile(r"^/dev/fd/[0-9]+$")
PROC_DIR = "/proc"
PROC_FD = re.compile(r"/proc/[^/]+/fd(/|$)")      # a descriptor of some process
STDIN_DEVICE = "/dev/stdin"
STDIN_DEVICES = (STDIN_DEVICE, "/dev/fd/0", "/proc/self/fd/0")
SYSTEM_TEMP_DIRS = ("/tmp", "/var/tmp")
DEFAULT_TEMP_DIR = SYSTEM_TEMP_DIRS[0]
# A role row's grant of a whole system temp directory, as policies/tool-policy.v1.json spells one.
RAW_TEMP_GRANTS = frozenset(pre + d + end for d in SYSTEM_TEMP_DIRS for pre, end in (("", "/*"), ("*", "/*"), ("", "/")))
# Directories the system keeps: no ordinary file of a project is in one.
UNSAFE_DIRS = ("/dev/", "/proc/", "/sys/", "/etc/", "/boot/", "/run/", "/var/run/")
SYSTEM_ROOTS = frozenset({
    "/", "/root", "/home", "/etc", "/usr", "/var", "/tmp", "/opt", "/bin", "/lib", "/lib64",
    "/sbin", "/srv", "/mnt", "/media", "/dev", "/proc", "/sys", "/run", "/boot"})
SYSTEM_BIN_DIRS = ("/bin", "/usr/bin", "/usr/local/bin")
BIN_DIRS = SYSTEM_BIN_DIRS + ("/opt/homebrew/bin",)

TEMP_ROOT_VARS = ("TMPDIR", "CLAUDE_TMPDIR", "CLAUDE_CODE_TMPDIR")
CONFIG_DIR_NAME = ".claude"                       # a project's configuration directory
CONFIG_HOME_VARS = ("CLAUDE_HOME", "CLAUDE_CONFIG_DIR")
CONFIG_FOLDERS = ("hooks", "commands")
SCRATCH_PARTS = (CONFIG_DIR_NAME, "scratch")      # the managed scratch, below a project
SESSION_SCRATCH_ROOT = os.path.join(SYSTEM_TEMP_DIRS[1], "claude-scratch")  # hooks/session-scratch-init.sh's, TMPDIR unset
SPEC_DIRS = (("docs", "dev", "specs"), (CONFIG_DIR_NAME, "specs"))  # below a project


# -- paths and containment -----------------------------------------------------------------
def _real(path) -> Optional[str]:
    try:
        return os.path.realpath(path) if path else None
    except (OSError, ValueError):
        return None


def _dedupe(paths) -> Tuple[str, ...]:
    out = []
    for path in paths:
        real = _real(path)
        if real and real not in out:
            out.append(real)
    return tuple(out)


def _abs_var(name: str) -> Optional[str]:
    """The variable's value when it is an absolute path, else None."""
    value = os.environ.get(name) or ""
    return value if os.path.isabs(value) else None


def absolute(path, cwd: Optional[str] = None) -> Optional[str]:
    """``path`` as an absolute normal path (`~` expanded, from ``cwd`` or the process cwd, symlinks
    left as written); None when it names no file."""
    if not isinstance(path, str) or not path or "\x00" in path:
        return None
    try:
        norm = os.path.normpath(os.path.join(cwd or os.getcwd(), os.path.expanduser(path)))
    except OSError:
        return None
    return os.sep + norm.lstrip(os.sep) if norm.startswith(os.sep) else None


def resolved_views(path, cwd: Optional[str] = None) -> Tuple[str, ...]:
    """The resolved views a path is judged in: its full realpath (where a write through it lands),
    and its parent's realpath joined with its final component as written (the entry itself; not for
    "." or ".."). A relative path is taken from ``cwd`` (default: the process cwd). str, bytes and
    os.PathLike are accepted, any other type raises TypeError; empty for "" and a path holding NUL."""
    raw = os.fspath(path)
    raw = os.fsdecode(raw) if isinstance(raw, bytes) else raw
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


def below(path: str, root: str, fold: bool = False) -> Optional[Tuple[str, ...]]:
    """Components of ``path`` below ``root``, both as given; () when equal; None outside.
    fold=True compares case-insensitively."""
    if fold:
        path, root = path.casefold(), root.casefold()
    if path == root:
        return ()
    prefix = root if root.endswith(os.sep) else root + os.sep
    if not path.startswith(prefix):
        return None
    return tuple(c for c in path[len(prefix):].split(os.sep) if c)


def inside(path, directory, cwd: Optional[str] = None) -> Optional[Tuple[str, ...]]:
    """Components of ``path`` below ``directory`` when it is that directory or lies in it, else
    None. Both sides are resolved, so a symlink or another spelling on either side answers alike,
    and a write through ``path`` is judged where it lands."""
    real, root = _real(absolute(str(path), cwd)), _real(absolute(str(directory), cwd))
    return below(real, root) if real and root else None


def is_inside(path, directory, cwd: Optional[str] = None) -> bool:
    return inside(path, directory, cwd) is not None


# -- devices -------------------------------------------------------------------------------
def device_name(path: str) -> Optional[str]:
    """The name of absolute normal ``path`` below the device directory ("" for it), else None."""
    rel = below(path, DEVICE_DIR)
    return None if rel is None else "/".join(rel)


def is_device(path, cwd: Optional[str] = None) -> bool:
    """Whether ``path`` names a device: the device directory or anything in it (a node, stdout,
    fd/N, a shell's tcp/...), but nothing below the shared-memory tmpfs mounted there. Its files
    are ordinary files, made or not yet: a project can be checked out on it."""
    full = absolute(path, cwd)
    return bool(full) and below(full, DEVICE_DIR) is not None and not below(full, SHM_DIR)


def is_system_path(path: str) -> bool:
    """Whether absolute normal ``path`` is in a directory the system keeps (UNSAFE_DIRS); a file of
    the tmpfs mounted in the device directory is not."""
    return (path + "/").startswith(UNSAFE_DIRS) and (device_name(path) is None or is_device(path))


# -- temp ----------------------------------------------------------------------------------
def system_temp_roots() -> Tuple[str, ...]:
    """The system temp directories, resolved (/tmp and an alias such as /private/tmp are one)."""
    return _dedupe(SYSTEM_TEMP_DIRS)


def temp_roots(system: Optional[Tuple[str, ...]] = None) -> Tuple[str, ...]:
    """Every temp root, resolved and deduplicated: the system's, then each absolute TEMP_ROOT_VARS
    value; never "/" (it would make every path temp)."""
    named = list(SYSTEM_TEMP_DIRS if system is None else system) + [_abs_var(v) for v in TEMP_ROOT_VARS]
    return tuple(root for root in _dedupe(named) if root != os.sep)


def temp_root() -> str:
    """The session's temp directory as its environment names it: an absolute $TMPDIR, else the default."""
    return os.path.normpath(_abs_var("TMPDIR") or DEFAULT_TEMP_DIR)


def session_temp_roots() -> Tuple[str, ...]:
    """The temp directories a session's own files go to, resolved: the default and temp_root(); never "/"."""
    return tuple(root for root in _dedupe([DEFAULT_TEMP_DIR, temp_root()]) if root != os.sep)


def temp_root_of(path, cwd: Optional[str] = None, roots: Optional[Tuple[str, ...]] = None) -> Optional[str]:
    """The root of ``roots`` (default temp_roots()) that ``path`` lies strictly below in either
    resolved view (the deepest when roots nest), else None."""
    best = None
    for view in resolved_views(path, cwd):
        for root in temp_roots() if roots is None else roots:
            if below(view, root) and (best is None or len(root) > len(best)):
                best = root
    return best


def session_scratch_dir(session_id) -> Optional[str]:
    """The session's scratch directory, <TMPDIR or SESSION_SCRATCH_ROOT>/<session id>, which
    hooks/session-scratch-init.sh creates; None for an id that is no single name."""
    sid = session_id if isinstance(session_id, str) else ""
    if not sid.strip(".") or os.path.basename(sid) != sid:
        return None
    root = _abs_var("TMPDIR") or SESSION_SCRATCH_ROOT
    return os.path.join(_real(root) or root, sid)


def in_system_temp(path, cwd: Optional[str] = None) -> bool:
    """Whether ``path`` is a system temp directory or a write of it lands in one, both sides resolved."""
    return any(inside(path, root, cwd) is not None for root in system_temp_roots())


def is_system_temp_root(directory: str) -> bool:
    return _real(directory) in system_temp_roots()


def in_arbitrary_temp(path, project, cwd: Optional[str] = None) -> bool:
    """Whether ``path`` lies in a system temp directory and outside ``project``: a project checked
    out there is a project, and the ban on system temp writes is not about it."""
    return in_system_temp(path, cwd) and not is_inside(path, project, cwd)


# -- the harness's roots: one resolution each ----------------------------------------------
def state_root() -> str:
    """The hook state root (lib/harness_state_dir.py, which imports nothing; shell twin .sh)."""
    return harness_state_dir()


def _claude_home():
    try:  # loaded on first use: the shared parser imports this module on every Bash call
        from . import claude_home
    except ImportError:  # hooks/lib itself is on sys.path
        import claude_home
    return claude_home


def harness_home():
    """The harness home (lib/claude_home.resolve; shell twin lib/claude_home.sh), or None."""
    return _claude_home().resolve()


def config_home():
    """Where per-harness records live whichever configuration directory runs (lib/claude_home.config_home)."""
    return _claude_home().config_home()


def project_root(bash: bool = False):
    """The project root (lib/claude_home.project_dir). bash=True: for a program the Bash tool runs,
    whose environment carries no CLAUDE_PROJECT_DIR and whose cwd is the session's directory (the
    hooks' root): CLAUDE_PROJECT_DIR, else the cwd, never the harness home."""
    if bash:
        return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    return _claude_home().project_dir()


# -- Claude configuration directories ------------------------------------------------------
_HOMES: dict = {}


def config_homes() -> Tuple[str, ...]:
    """The directories this session's Claude configuration is in, each as named and resolved: the
    harness home, $CLAUDE_HOME, $CLAUDE_CONFIG_DIR and ~/.claude. On one machine these may be one
    directory under any name, reached through links."""
    key = tuple(os.environ.get(v) for v in ("HOME",) + CONFIG_HOME_VARS)
    if key not in _HOMES:
        named = [str(harness_home() or "")] + [os.environ.get(v) or "" for v in CONFIG_HOME_VARS]
        named.append(os.path.join(os.path.expanduser("~"), CONFIG_DIR_NAME))
        out = []
        for d in named:
            for form in (os.path.normpath(d), _real(d)) if os.path.isabs(d) else ():
                if form and form != os.sep and form not in out:
                    out.append(form)
        _HOMES.clear()
        _HOMES[key] = tuple(out)
    return _HOMES[key]


def config_folder(path, cwd: Optional[str] = None, names: Tuple[str, ...] = CONFIG_FOLDERS) -> str:
    """Which folder of ``names`` (hooks, commands) of a Claude configuration directory ``path`` is
    or lies in, by where it is and not by a piece of its spelling: below a config home, or below a
    directory named .claude (a project's), as written or in either resolved view. '' when none."""
    try:
        views = dict.fromkeys(filter(None, (absolute(path, cwd),) + resolved_views(path, cwd)))
    except TypeError:
        return ""
    homes = config_homes()
    for view in views:
        for home in homes:
            rel = below(view, home)
            if rel and rel[0] in names:
                return rel[0]
        parts = view.split(os.sep)
        for i, part in enumerate(parts[:-1]):
            if part == CONFIG_DIR_NAME and parts[i + 1] in names:
                return parts[i + 1]
    return ""


def spec_rest(path: str) -> Optional[str]:
    """The text of ``path`` below the spec root it names ("<id>/..."), casefolded: a project's
    docs/dev/specs or .claude/specs anywhere in it, or (an absolute path) the specs/ of a config
    home, wherever that home is and whatever it is named. None outside every spec root."""
    parts = [p.casefold() for p in path.replace("\\", "/").split("/") if p]
    for i in range(len(parts)):
        for root in SPEC_DIRS:
            if tuple(parts[i:i + len(root)]) == root and len(parts) > i + len(root):
                return "/".join(parts[i + len(root):])
    for home in config_homes() if path.startswith("/") else ():
        rel = below("/" + "/".join(parts), home, fold=True)
        if rel and rel[0] == SPEC_DIRS[1][1] and len(rel) > 1:
            return "/".join(rel[1:])
    return None


# -- where a written file is data, and what is too broad to guard --------------------------
def data_parts(path: str) -> Optional[Tuple[str, ...]]:
    """The components of ``path`` below the place a written file may land in as data: a relative
    path as written; an absolute one (`~` expanded) below the project, the directory the call runs
    in (the same file a relative spelling names) or a temp root. Either way from below the managed
    scratch when it lies there. None anywhere else."""
    path = os.path.expanduser(path)
    if path.startswith("~"):
        return None
    if os.path.isabs(path):
        if is_device(path) or below(os.path.normpath(path), PROC_DIR) is not None:
            return None  # a name the kernel keeps for a process (fd/N, self/fd/N), not where a file lies
        for place in (str(project_root()), os.curdir) + tuple(sorted(temp_roots(), key=len, reverse=True)):
            rel = inside(path, place)
            if rel is not None:
                break
        else:
            return None
    else:
        rel = tuple(c for c in path.split("/") if c and c != os.curdir)
    return rel[len(SCRATCH_PARTS):] if rel[:len(SCRATCH_PARTS)] == SCRATCH_PARTS else rel


def is_broad_root(directory: str) -> bool:
    """Whether ``directory`` is too broad to guard as one file's ancestor: the filesystem root, a
    system directory, the user's home or a directory above it."""
    norm = os.path.normpath(directory)
    home = os.path.normpath(os.environ.get("HOME") or os.path.expanduser("~"))
    return norm in SYSTEM_ROOTS or below(home, norm) is not None
