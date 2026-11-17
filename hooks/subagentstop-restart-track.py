#!/usr/bin/env python3
"""SubagentStop: persist response evidence for a /restart-resumed agent."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import final_report  # noqa: E402
from lib import subagent_restart as restart  # noqa: E402


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    # An observer: the evidence it records is what /restart reads (lib/subagent_restart). It
    # prints nothing, because at SubagentStop any output that reaches the model keeps the
    # stopping subagent running, and plain stdout reaches no one.
    # A resumed agent in auto mode answers through SubagentHandback: its report is that
    # call's message, and the payload then carries no last_assistant_message.
    if isinstance(payload, dict):
        report = final_report.handback_message(payload.get("agent_transcript_path"))
        if report is not None:
            payload = {**payload, "last_assistant_message": report}
    restart.observe_subagent_stop(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
