#!/usr/bin/env python3
"""PostToolUse(AskUserQuestion|Agent): the dispatcher of the score log's observers (D9a, D28); it holds no logic.
AskUserQuestion goes to close_rating.handle (the owner's rating row and summary), Agent and Task to score_events.observe
(the dispatch's facts). The returned dict is printed as one JSON line. Quick, silent on any error, exit 0; it never
prints decision, continue or updatedToolOutput (D9b)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))


def main() -> None:
    try:  # a payload of another shape, a missing module or a failing handler raises here and prints nothing
        payload = json.load(sys.stdin)
        name, out = payload.get("tool_name"), None
        if name == "AskUserQuestion":
            import close_rating
            out = close_rating.handle(payload)
        elif name in ("Agent", "Task"):
            import score_events
            out = score_events.observe(payload)
        if isinstance(out, dict) and not {"decision", "continue"} & out.keys() \
                and "updatedToolOutput" not in (out.get("hookSpecificOutput") or {}):
            print(json.dumps(out))
    except Exception:
        pass


if __name__ == "__main__":
    main()
