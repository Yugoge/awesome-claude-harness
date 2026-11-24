#!/usr/bin/env python3
"""harness_state_dir.py -- the one resolver of where the harness keeps its own files, on disk.

state_root(): <home>/.local/state/claude-harness/<harness home's name>-<crc32 of its real path> (HOME when
absolute, else the passwd entry's), the refusal record's own key (lib/refusal_record.py). In it: state/
(control state: harness_state_dir(), which CLAUDE_STATE_DIR, when absolute, replaces as it always has),
logs/ and restart-state/ (their owners join them), refusals/. Not keyed on TMPDIR (per-session scratch:
writer and reader hooks must agree). The default was /tmp until 2026-11-21. Nothing here, nor anywhere in the
harness, moves, copies or removes what an earlier version left in its old places: carrying it over is the
explicit install step scripts/install/carry_state.py. Shell twin: .sh beside it.
"""

from __future__ import annotations

import os
import zlib

_ENV = "CLAUDE_STATE_DIR"


def _user_home() -> str:
    home = os.path.expanduser("~")
    if not os.path.isabs(home):
        import pwd
        home = pwd.getpwuid(os.getuid()).pw_dir
    return home


def state_root(home: str | None = None, harness: str | None = None) -> str:
    """The per-install root on disk (of this file's harness home, for the user's home unless given)."""
    harness = harness or os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    key = f"{harness.rsplit(os.sep, 1)[-1].lstrip('.')}-{zlib.crc32(os.fsencode(harness)):08x}"
    return os.path.join(home or _user_home(), ".local", "state", "claude-harness", key)


def harness_state_dir() -> str:
    """Return the absolute control-state directory; never raises."""
    value = os.environ.get(_ENV, "")
    if value and os.path.isabs(value):
        norm = os.path.normpath(value)
        if norm.startswith("//"):
            norm = "/" + norm.lstrip("/")
        return norm
    state = os.path.join(state_root(), "state")
    try:
        os.makedirs(state, mode=0o700, exist_ok=True)
    except Exception:  # noqa: BLE001 - best effort: a writer reports its own failure
        pass
    return state


if __name__ == "__main__":
    print(harness_state_dir())
