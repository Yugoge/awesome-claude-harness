#!/usr/bin/env python3
"""locations.py -- the one place that answers where things are.

A decision about a location asks here. No other file of hooks/ or scripts/ compares a path
with an absolute system directory or lists one (tests/test_location_literals.py holds that):
the literals below are the only copy.

  devices      is_device(): a device node or a name the device directory keeps. A file of a
               filesystem that is only mounted there (a project on a tmpfs) is none.
  temp         system_temp_roots(), temp_roots(), session_temp_roots(): resolved, so a
               symlinked temp directory answers alike; in_system_temp(), temp_root_of().
  roots        harness_home(), project_root(), state_root(), temp_root(): one resolution
               each, the same for a writer and a reader.
  containment  below() and is_inside(): the directory resolved, the path in both of its
               resolved views (resolved_views).
  config       config_homes(): the directories this session's Claude configuration really is
               in, whatever they are named; config_folder(): the hooks/ or commands/ folder
               of one a path lies in; spec_rest(): a path below a spec root.
  data         data_parts(): a written file below the project, its scratch or a temp root.
  broad roots  is_broad_root(): the filesystem root, a system directory, the user's home
               and what lies above it.

Pure: reads os.environ and the filesystem, writes nothing.
"""

from __future__ import annotations

import os
import re
import stat
from typing import Optional, Tuple

try:
    from . import claude_home
    from .harness_state_dir import harness_state_dir
except ImportError:  # hooks/lib itself is on sys.path
    import claude_home
    from harness_state_dir import harness_state_dir

# -- the literals --------------------------------------------------------------------------
DEVICE_DIR = "/dev"
NULL_DEVICE = "/dev/null"
STD_SINKS = frozenset({NULL_DEVICE, "/dev/stdout", "/dev/stderr"})
TERMINAL_SINKS = STD_SINKS | {"/dev/tty"}
FD_DIR = "/dev/fd/"                               # /dev/fd/N: a descriptor of the process
FD_PATH = re.compile(r"/dev/fd/[0-9]+")
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
SPEC_DIRS = (("docs", "dev", "specs"), (CONFIG_DIR_NAME, "specs"))  # below a project


# -- paths ---------------------------------------------------------------------------------
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
    """``path`` as an absolute normal path (`~` expanded, from ``cwd`` or the process cwd,
    symlinks left as written); None when it names no file."""
    if not isinstance(path, str) or not path or "\x00" in path:
        return None
    try:
        norm = os.path.normpath(os.path.join(cwd or os.getcwd(), os.path.expanduser(path)))
    except OSError:
        return None
    return os.sep + norm.lstrip(os.sep) if norm.startswith(os.sep) else None


def resolved_views(path, cwd: Optional[str] = None) -> Tuple[str, ...]:
    """The resolved views a path is judged in: its full realpath (where a write through it
    lands), and its parent's realpath joined with its final component as written (the entry
    itself; skipped when that component is "." or ".."). A relative path is taken from
    ``cwd`` (default: the process cwd). str, bytes and os.PathLike are accepted; any other
    type raises TypeError. Empty for "" and for a path holding NUL."""
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
    """Components of ``path`` below ``directory`` when it is that directory or lies in it,
    else None: the directory resolved, the path in each resolved view, so a symlink or
    another spelling on either side answers alike."""
    root = _real(absolute(str(directory), cwd))
    for view in resolved_views(path, cwd) if root else ():
        rel = below(view, root)
        if rel is not None:
            return rel
    return None


def is_inside(path, directory, cwd: Optional[str] = None) -> bool:
    return inside(path, directory, cwd) is not None


# -- devices -------------------------------------------------------------------------------
def device_name(path: str) -> Optional[str]:
    """The name of absolute normal ``path`` below the device directory ("" for the directory
    itself), else None."""
    rel = below(path, DEVICE_DIR)
    return None if rel is None else "/".join(rel)


def is_device(path, cwd: Optional[str] = None) -> bool:
    """Whether ``path`` is a device: the device directory, a node in it, or a name the
    kernel or a shell keeps there (stdout, fd/N, tcp/...). Inside a real directory of it,
    only an existing character or block device is one: a file of a filesystem that is only
    mounted there (a project on the /dev/shm tmpfs), made or not yet, is an ordinary file."""
    full = absolute(path, cwd)
    name = device_name(full) if full else None
    if not name:
        return name == ""
    try:
        mode = os.lstat(os.path.join(DEVICE_DIR, name.split("/", 1)[0])).st_mode
    except OSError:
        return True
    if not stat.S_ISDIR(mode):
        return not stat.S_ISREG(mode)
    try:
        mode = os.stat(full).st_mode
    except OSError:
        return False
    return stat.S_ISCHR(mode) or stat.S_ISBLK(mode)


def is_system_path(path: str) -> bool:
    """Whether absolute normal ``path`` is in a directory the system keeps (UNSAFE_DIRS); a
    file of a filesystem only mounted in the device directory is not."""
    return (path + "/").startswith(UNSAFE_DIRS) and (device_name(path) is None or is_device(path))


# -- temp ----------------------------------------------------------------------------------
def system_temp_roots() -> Tuple[str, ...]:
    """The system temp directories, resolved and deduplicated (/tmp and an alias such as
    /private/tmp are one root)."""
    return _dedupe(SYSTEM_TEMP_DIRS)


def temp_roots() -> Tuple[str, ...]:
    """Every temp root, resolved and deduplicated: the system's, then each absolute
    TEMP_ROOT_VARS value. Unset, empty or relative values add nothing, and neither does one
    resolving to "/" (it would make every path temp)."""
    roots = _dedupe(list(SYSTEM_TEMP_DIRS) + [_abs_var(v) for v in TEMP_ROOT_VARS])
    return tuple(root for root in roots if root != os.sep)


def temp_root() -> str:
    """The session's temp directory as its environment names it: an absolute $TMPDIR, else
    the system default."""
    return os.path.normpath(_abs_var("TMPDIR") or DEFAULT_TEMP_DIR)


def session_temp_roots() -> Tuple[str, ...]:
    """The temp directories a session's own files go to, resolved: the system default and
    temp_root(); never "/"."""
    return tuple(root for root in _dedupe([DEFAULT_TEMP_DIR, temp_root()]) if root != os.sep)


def temp_root_of(path, cwd: Optional[str] = None, roots: Optional[Tuple[str, ...]] = None) -> Optional[str]:
    """The root of ``roots`` (default temp_roots()) that ``path`` lies strictly below in
    either resolved view (the deepest when roots nest), else None."""
    best = None
    for view in resolved_views(path, cwd):
        for root in temp_roots() if roots is None else roots:
            if below(view, root) and (best is None or len(root) > len(best)):
                best = root
    return best


def in_system_temp(path, cwd: Optional[str] = None) -> bool:
    """Whether ``path`` lies strictly below a system temp directory, both sides resolved."""
    return temp_root_of(path, cwd, system_temp_roots()) is not None


def is_system_temp_root(directory: str) -> bool:
    return _real(directory) in system_temp_roots()


def in_arbitrary_temp(path, project, cwd: Optional[str] = None) -> bool:
    """Whether ``path`` lies in a system temp directory and outside ``project``: a project
    checked out there is a project, and the ban on system temp writes is not about it."""
    return in_system_temp(path, cwd) and not is_inside(path, project, cwd)


# -- the harness's roots -------------------------------------------------------------------
def harness_home():
    """The harness home (lib/claude_home.resolve), or None."""
    return claude_home.resolve()


def project_root():
    """The project root (lib/claude_home.project_dir)."""
    return claude_home.project_dir()


def state_root() -> str:
    """The hook state root (lib/harness_state_dir)."""
    return harness_state_dir()


# -- Claude configuration directories ------------------------------------------------------
_HOMES: dict = {}


def config_homes() -> Tuple[str, ...]:
    """The directories this session's Claude configuration is in, each as named and resolved:
    the harness home, $CLAUDE_HOME, $CLAUDE_CONFIG_DIR and ~/.claude. On one machine these
    may be one directory under any name, reached through links."""
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
    """Which folder of ``names`` (hooks, commands) of a Claude configuration directory
    ``path`` is or lies in, by where it is and not by a piece of its spelling: below a
    config home, or below a directory named .claude (a project's), as written or in either
    resolved view. '' when none."""
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
    """The text of ``path`` below the spec root it names ("<id>/..."), casefolded: a
    project's docs/dev/specs or .claude/specs anywhere in it, or (an absolute path) the
    specs/ of a config home, wherever that home is and whatever it is named. None outside
    every spec root."""
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


# -- where a written file is data ----------------------------------------------------------
def data_parts(path: str) -> Optional[Tuple[str, ...]]:
    """The components of ``path`` below the place a written file may land in as data: a
    relative path as written; an absolute one (`~` expanded) below the project, the
    directory the call runs in (the same file a relative spelling names) or a temp root.
    Either way from below the managed scratch when it lies there. None anywhere else."""
    path = os.path.expanduser(path)
    if path.startswith("~"):
        return None
    if os.path.isabs(path):
        root = temp_root_of(path)
        for place in (str(project_root()), os.curdir, root):
            rel = inside(path, place) if place else None
            if rel is not None:
                break
        else:
            return None
    else:
        rel = tuple(c for c in path.split("/") if c and c != os.curdir)
    return rel[len(SCRATCH_PARTS):] if rel[:len(SCRATCH_PARTS)] == SCRATCH_PARTS else rel


# -- broad roots ---------------------------------------------------------------------------
def is_broad_root(directory: str) -> bool:
    """Whether ``directory`` is too broad to guard as one file's ancestor: the filesystem
    root, a system directory, the user's home or a directory above it."""
    norm = os.path.normpath(directory)
    home = os.path.normpath(os.environ.get("HOME") or os.path.expanduser("~"))
    return norm in SYSTEM_ROOTS or below(home, norm) is not None
