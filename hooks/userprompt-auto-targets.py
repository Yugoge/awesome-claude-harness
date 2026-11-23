#!/usr/bin/env python3
"""UserPromptSubmit: fix an --auto run's task list when the owner's /close --auto or /commit --auto arrives.

commands/commit.md and close.md say the --auto snapshot is frozen for the batch; this rule makes it so: at the
typed prompt it runs dev-lifecycle's --auto target function (freeze_auto_targets, the one writer) with the
prompt's arrival as the cut-off and keeps the list as the session's state (`auto-targets/<sid>.json` under the
state root). The Stop gate reads it (read_frozen) and scans no ticket again for that run. It never blocks and
prints nothing; a listing that fails or runs past the rule's timeout leaves no list, and the gate then lists as
before (a fresh scan at each Stop).
"""
from __future__ import annotations

import importlib.util
import json
import os
import shlex
import sys
import time
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent
ACTIONS = {"/close": "close", "/commit": "commit"}


def action_of(prompt: str) -> str | None:
    """close or commit for a prompt that types /close or /commit with --auto among its words; else None."""
    first = (prompt or "").strip().splitlines()[:1]
    try:
        words = shlex.split(first[0]) if first else []
    except ValueError:
        words = first[0].split()
    return ACTIONS.get(words[0]) if words and "--auto" in words[1:] else None


def main() -> int:
    arrived = time.time()
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    action = action_of(payload.get("prompt") or "") if isinstance(payload, dict) else None
    if action is None:
        return 0
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    spec = importlib.util.spec_from_file_location("_auto_targets_lifecycle", HARNESS / "scripts" / "dev-lifecycle.py")
    lifecycle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lifecycle)
    lifecycle.freeze_auto_targets(Path(root), action, str(payload.get("session_id") or ""), arrived)
    return 0


if __name__ == "__main__":
    sys.exit(main())
