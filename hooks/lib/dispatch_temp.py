#!/usr/bin/env python3
"""Temp files follow the foreground dispatch during which they were made.

<session root>/.dispatch-tmp is this module's state and _write its one writer. Line 1 names the
temp directory of the open dispatches; the line hooks/session-scratch-init.sh puts in the
session's env file reads it before every shell command and makes it TMPDIR (else the session
root). Line 2 is {"open": tool_use_ids, "kept": retired directories still to remove, "held":
directories whose agent went on in the background}. The dispatch gate's witness opens a
foreground dispatch (opened); its return, PostToolUse or PostToolUseFailure, closes it (returned).
Nested and parallel dispatches share the open directory; when the last returns it is retired and
removed, unless a live process works or holds a file inside it: then it is tried again at each
later return, at the owner's next prompt and at the next start. An end never seen (a cancelled
turn fires no hook) is closed at the owner's next prompt (prompted, userprompt-launch.py) and at
a session start (started): no foreground dispatch outlives its turn, so both empty the open set and
remove every dispatch directory left that nothing uses. An agent moved to the background (status
async_launched) keeps its directory until a start whose previous process died.
A background child reads the same line 1, so while one runs ("running": the launches whose end
was not seen; the end is its dispatch-end return, hooks/posttool-dispatch-record.py) no dispatch
directory is current: a launch clears line 1 and holds the open directory, a foreground dispatch
opens none, and the held directories go once no background child runs.
Only a directory made by mkdtemp right under a root whose .owner names the session.
"""
import contextlib
import fcntl
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import locations, scratch_owner  # noqa: E402
from lib.subagent import DISPATCH_TOOLS  # noqa: E402

POINTER = ".dispatch-tmp"
PREFIX = locations.DISPATCH_PREFIX


def _owned(root, sid):
    return bool(root) and scratch_owner.is_safe_session_dir_name(sid) and scratch_owner.owns_scratch_dir(root, sid)


def _read(root):
    try:
        with open(os.path.join(root, POINTER), encoding="utf-8") as handle:
            current, state = handle.readline().rstrip("\n"), json.loads(handle.readline() or "{}")
    except (OSError, ValueError):
        return "", {}
    return current, (state if isinstance(state, dict) else {})


def _write(root, current, state):
    path = os.path.join(root, POINTER)
    if not (current or state.get("kept") or state.get("held") or state.get("running")):
        with contextlib.suppress(FileNotFoundError):
            os.unlink(path)
        return
    with open(f"{path}.{os.getpid()}", "w", encoding="utf-8") as handle:
        handle.write(f"{current}\n{json.dumps(state)}\n")
    os.replace(f"{path}.{os.getpid()}", path)


@contextlib.contextmanager
def _locked(root):
    fd = os.open(root, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _targets(pid):
    """What a process's working directory and open files resolve to (none once it is gone)."""
    try:
        links = [f"/proc/{pid}/cwd"] + [f"/proc/{pid}/fd/{fd}" for fd in os.listdir(f"/proc/{pid}/fd")]
    except OSError:
        links = [f"/proc/{pid}/cwd"]
    for link in links:
        with contextlib.suppress(OSError):
            yield os.readlink(link)


def _all_targets():
    """Every working directory and open file /proc shows; None when it cannot tell (no /proc mounted)."""
    if not os.path.exists("/proc/self/stat"):
        return None
    return [t for pid in os.listdir("/proc") if pid.isdigit() for t in _targets(pid)]


def _in_use(directory, targets=False):
    """A process's working directory or an open file lies inside; cannot tell (no /proc) counts."""
    targets = _all_targets() if targets is False else targets
    return targets is None or any(t == directory or t.startswith(directory + os.sep) for t in targets)


def _remove(root, directories):
    """The directories still there after removing each of ours that nothing uses."""
    left = []
    for d in directories:
        if (os.path.dirname(d) != root or not os.path.basename(d).startswith(PREFIX)
                or os.path.islink(d) or not os.path.isdir(d)):
            continue
        if not _in_use(d):
            shutil.rmtree(d, ignore_errors=True)
        if os.path.lexists(d):
            left.append(d)
    return left


def _session_root(payload):
    sid = payload.get("session_id")
    root = locations.session_scratch_dir(sid) if payload.get("tool_name") in DISPATCH_TOOLS else None
    return root if payload.get("tool_use_id") and _owned(root, sid) else None


def opened(payload):
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    root = _session_root(payload)
    if not root or tool_input.get("run_in_background") in (True, "true"):
        return []
    with _locked(root):
        current, state = _read(root)
        if not (current and os.path.isdir(current)) and not state.get("running"):
            current = tempfile.mkdtemp(prefix=PREFIX, dir=root)
        state["open"] = sorted(set(state.get("open", [])) | {payload["tool_use_id"]})
        _write(root, current, state)
    return []


def returned(payload):
    root = _session_root(payload)
    if not root:
        return []
    response = payload.get("tool_response")
    moved = isinstance(response, dict) and response.get("status") == "async_launched"
    with _locked(root):
        current, state = _read(root)
        open_ids, running = state.get("open", []), set(state.get("running", []))
        if moved and current:  # an agent in the background reads line 1 too: it names no dispatch's directory
            state["held"], current = sorted(set(state.get("held", [])) | {current}), ""
        if moved:
            running.add(payload["tool_use_id"])
        elif payload["tool_use_id"] in running:  # a background agent's end: once none runs, the held go
            running.discard(payload["tool_use_id"])
            if not running:
                state["kept"], state["held"] = state.get("kept", []) + state.get("held", []), []
        state["running"] = sorted(running)
        state["open"] = [i for i in open_ids if i != payload["tool_use_id"]]
        if not state["open"] and current:
            if current not in state.get("held", []):
                state["kept"] = state.get("kept", []) + [current]
            current = ""
        state["kept"] = _remove(root, state.get("kept", []))
        _write(root, current, state)
    return []


ALIVE, GONE, UNKNOWN = "alive", "gone", "unknown"


def owner_state(owner):
    """The one definition of "the process that owned this is gone" (scripts/install/tmp-cleanup-install.sh asks
    it through judge): GONE only on proof (another boot, no process with that pid, or one with another start
    time); UNKNOWN without /proc, without a recorded pid, or for a running pid with no recorded start time."""
    try:
        pid, start = int(owner.get("pid")), str(owner.get("pid_start_time") or "")
        with open("/proc/sys/kernel/random/boot_id", encoding="utf-8") as handle:
            boot = handle.read().strip()
    except (OSError, ValueError, TypeError, AttributeError):
        return UNKNOWN
    if pid <= 0:
        return UNKNOWN
    if owner.get("boot_id") and owner.get("boot_id") != boot:
        return GONE
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
            now = handle.read().rsplit(")", 1)[1].split()[19]
    except FileNotFoundError:
        return GONE
    except (OSError, IndexError):
        return UNKNOWN
    return UNKNOWN if not start else ALIVE if now == start else GONE


def judge(paths):
    """For the cleanup program, one line "<verdict> <path>\\0" per path: of an .owner, owner_state of its
    record; of anything else used|unused|unknown (_in_use), and also "control <path>" when the inventory
    (lib/harness_temp_state.py) names it a session's control state."""
    from lib import harness_temp_state as inventory
    targets = _all_targets()
    for path in paths:
        if os.path.basename(path) == scratch_owner.OWNER_FILE:
            sys.stdout.write(f"{owner_state(_owner_record(path) or {})} {path}\0")
            continue
        rel = tuple(os.path.normpath(path).split(os.sep)[-2:])
        if any(loc.kind == inventory.CONTROL and inventory._matches(rel, loc) for loc in inventory.LOCATIONS):
            sys.stdout.write(f"control {path}\0")
        verdict = UNKNOWN if targets is None else ("used" if _in_use(os.path.realpath(path), targets) else "unused")
        sys.stdout.write(f"{verdict} {path}\0")


def _owner_record(path):
    """The record of an .owner file at ``path`` (scratch_owner.owner_record, the one reader), else None."""
    return scratch_owner.owner_record(os.path.dirname(path))


def _close(root, held_too):
    """No dispatch is open: every dispatch directory left goes unless in use; held ones only with held_too."""
    with _locked(root):
        current, state = _read(root)
        held = [] if held_too else state.get("held", [])
        left = [os.path.join(root, n) for n in os.listdir(root) if n.startswith(PREFIX)]
        _write(root, "", {"kept": _remove(root, [d for d in dict.fromkeys(left + [current]) if d not in held]), "held": held,
                          "running": [] if held_too else state.get("running", [])})


def prompted(payload):
    """At the owner's prompt (UserPromptSubmit): a dispatch whose end was never seen is closed."""
    sid = payload.get("session_id")
    root = locations.session_scratch_dir(sid)
    if _owned(root, sid):
        _close(root, False)


def started(session_dir, sid):
    """At a session start, before the new .owner: closes what is left; held ones too if that process died."""
    root = os.path.realpath(session_dir)
    owner = _owner_record(os.path.join(root, scratch_owner.OWNER_FILE))
    if owner is not None and _owned(root, sid):
        _close(root, owner_state(owner) == GONE)


if __name__ == "__main__":
    with contextlib.suppress(Exception):
        if sys.argv[1:2] == ["--start"]:
            started(sys.argv[2], sys.argv[3])
        elif sys.argv[1:2] == ["--judge"]:
            judge(sys.argv[2:])  # scripts/install/tmp-cleanup-install.sh
        elif (payload := json.load(sys.stdin)).get("hook_event_name") == "UserPromptSubmit":
            prompted(payload)  # userprompt-launch.py
        else:  # PostToolUseFailure (posttool-failure-launch.py)
            returned(payload)
    sys.exit(0)
