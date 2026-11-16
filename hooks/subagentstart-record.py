#!/usr/bin/env python3
"""SubagentStart: shows the starting subagent its own record (D29, D32): score, rank and trend, its newest good event and newest miss as facts, and the
rank's reminder (hooks/lib/score_log.py), as additionalContext of at most 3 lines and 400 bytes; one line for a role with no rows. Nothing in a /close, /commit,
/merge or /push span, or for an agent outside agents/. Reads the score log, writes nothing, never blocks, exits 0 on every path, prints nothing on an error."""
import os, sys  # noqa: E401 -- the harness switch (hooks/lib/harness_switch.py): no harness hook runs while /harness off holds
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))
try:  # a hook copied without its lib/ (an old install) is on
    import harness_switch  # noqa: E402
    harness_switch.exit_if_off()
except ImportError:
    pass
finally:
    sys.path.pop(0)

import json  # noqa: E402
from pathlib import Path  # noqa: E402

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
