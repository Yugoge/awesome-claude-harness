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
    view = restart.observe_subagent_stop(payload)
    if view is not None:
        print(
            f"RESTART RESPONSE OBSERVED: {payload.get('agent_id')}; "
            f"complete={str(view['complete']).lower()}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
