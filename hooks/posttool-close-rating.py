#!/usr/bin/env python3
"""PostToolUse(AskUserQuestion|Agent): the one writer of the owner's answers and the score log's dispatcher.
A question goes by its source prefix to one handler, an Agent call to the observer; no logic here.
By tool_name:
- AskUserQuestion goes by the prefix of metadata.source to one handle(payload) per library: close-rating:<task-id>
  (D9) to close_rating.handle, a row only for the main agent's one question answered with one of the four exact
  labels in the CLI's tool_response (the CLI drops answers the model writes in its input), and it returns the owner
  summary; requirement-round:<task>:r<n> and producer-question:<task>:<role> (D28) to requirement_round.handle,
  which writes the answer file or the producer answer and prints nothing; any other source writes and prints nothing;
- Agent and Task go to score_events.observe (the dispatch's facts), which prints nothing.
The dict a route returns (the rating's summary) is printed as one JSON line. Skip, free text, a decline, an error, an
AFK auto-continue or any other payload writes nothing (D9b). Quick, silent on any error, exit 0; it never prints
decision, continue or updatedToolOutput."""
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
