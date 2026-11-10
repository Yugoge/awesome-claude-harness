#!/usr/bin/env python3
"""SubagentStop: persist response evidence for a /restart-resumed agent."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import subagent_restart as restart  # noqa: E402


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    # An observer: the evidence it records is what /restart reads (lib/subagent_restart). It
    # prints nothing, because at SubagentStop any output that reaches the model keeps the
    # stopping subagent running, and plain stdout reaches no one.
    restart.observe_subagent_stop(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
