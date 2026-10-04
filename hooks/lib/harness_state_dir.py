#!/usr/bin/env python3
"""harness_state_dir.py -- single resolver for the hook runtime-state root.

Hook runtime state (consent flags, grants, sentinels, bookmarks, stamps) lives
under one root so a full or unwritable default location can be redirected.

Contract:
  * ``CLAUDE_STATE_DIR`` set to an ABSOLUTE path -> that path (normalized).
  * unset, empty, or relative -> the default root (identical to the historical
    hardcoded location, so behaviour is unchanged unless the variable is set).

Deliberately NOT keyed on TMPDIR/CLAUDE_TMPDIR: those are per-session or
per-dispatch scratch roots, so a writer hook and its reader hook would
disagree. This is also NOT hooks/pretool-overnight-hook-guard.py
``_harness_state_dirs()`` (protected-path roots) nor the restart
``state_dir()`` in subagent_restart.py.

Shell twin: hooks/lib/harness_state_dir.sh.
"""

from __future__ import annotations

import os

_ENV = "CLAUDE_STATE_DIR"
_DEFAULT_ROOT = "/tmp"


def harness_state_dir() -> str:
    """Return the absolute state root; never raises."""
    value = os.environ.get(_ENV, "")
    if value and os.path.isabs(value):
        norm = os.path.normpath(value)
        if norm.startswith("//"):
            norm = "/" + norm.lstrip("/")
        return norm
    return _DEFAULT_ROOT
