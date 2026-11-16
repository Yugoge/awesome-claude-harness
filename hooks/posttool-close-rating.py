#!/usr/bin/env python3
"""PostToolUse(AskUserQuestion|Agent): the one writer of the owner's answers and the score log's dispatcher.
A question goes by its source prefix to one handler, an Agent call to the observer; no logic here.
close-rating:<task-id> (D9) to close_rating.handle (a row for one of the four exact labels in the CLI's tool_response; the owner summary it returns is printed as one JSON line);
requirement-round:<task>:r<n> and producer-question:<task>:<role> (D28) to requirement_round.handle (the answer file, nothing printed); Agent and Task to score_events.observe (nothing printed).
Any other source, Skip, free text, a decline, an error and an AFK auto-continue write nothing (D9b). Quick, silent on any error, exit 0; never prints decision, continue or updatedToolOutput."""
import os, sys  # noqa: E401 -- the harness switch (hooks/lib/harness_switch.py): no harness hook runs while /harness off holds
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))
try:  # a hook copied without its lib/ (an old install) is on
    import harness_switch  # noqa: E402
    harness_switch.exit_if_off()
except ImportError:
    pass
finally:
    sys.path.pop(0)
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))


def _close_rating(payload: dict):
    import close_rating
    return close_rating.handle(payload)


def _requirement_round(payload: dict):
    import requirement_round
    requirement_round.handle(payload)  # its answer is a file, never a message: nothing to print


ROUTES = {"close-rating": _close_rating, "requirement-round": _requirement_round,
          "producer-question": _requirement_round}


def main() -> None:
    try:  # a payload of another shape, a missing module or a failing handler raises here and prints nothing
        payload = json.load(sys.stdin)
        name, out = payload.get("tool_name"), None
        if name == "AskUserQuestion":
            meta = payload["tool_input"].get("metadata") or {}
            route = ROUTES.get(str(meta.get("source", "")).partition(":")[0])
            out = route(payload) if route else None
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
