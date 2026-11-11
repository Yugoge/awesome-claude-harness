#!/usr/bin/env python3
"""SubagentStart: shows the starting subagent its own record (D29, D32): score, rank and trend, its newest good event and newest miss as facts, and the
rank's reminder (hooks/lib/score_log.py), as additionalContext of at most 3 lines and 400 bytes; one line for a role with no rows. Nothing in a /close, /commit,
/merge or /push span, or for an agent outside agents/. Reads the score log, writes nothing, never blocks, exits 0 on every path, prints nothing on an error."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))


def main() -> None:
    try:
        import score_view
        text = score_view.dispatch_context(json.load(sys.stdin))
        if text:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": text}}))
    except Exception:
        pass


if __name__ == "__main__":
    main()
