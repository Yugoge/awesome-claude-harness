#!/usr/bin/env python3
"""PostToolUse(AskUserQuestion): the one writer of the owner's answers. It routes by metadata.source prefix to one
handle(payload) per library and prints what the handler returns (hook JSON, or nothing):
- close-rating:<task-id> (D9): a row only for the main agent's (no agent_id) one close-rating question answered with
  one of the four exact labels in the CLI's tool_response (the CLI drops answers the model writes in its input);
- requirement-round:<task>:r<n> and producer-question:<task>:<role> (D28): requirement_round.handle writes the
  answer file or the producer answer.
Skip, free text, a decline, an error, an AFK auto-continue or any other payload: nothing. Never blocks, exit 0 (D9b)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))


def _close_rating(payload: dict):
    import close_rating
    if hasattr(close_rating, "handle"):
        return close_rating.handle(payload)
    tool_input, response = payload["tool_input"], payload["tool_response"]
    [question] = tool_input["questions"]
    task_id = close_rating.source_task(tool_input)
    rating = close_rating.LABEL_TO_RATING.get(response["answers"].get(question["question"]))
    if task_id and rating and payload.get("tool_name") == "AskUserQuestion" and not payload.get("agent_id") \
            and not any(response.get(k) for k in ("afkTimeoutMs", "response", "followUp")):
        close_rating.append_rating(task_id, rating, payload.get("tool_use_id"))
    return None


def _requirement_round(payload: dict):
    import requirement_round
    return requirement_round.handle(payload)


ROUTES = {"close-rating": _close_rating, "requirement-round": _requirement_round,
          "producer-question": _requirement_round}


def main() -> None:
    try:  # a payload of another shape raises here and writes nothing
        payload = json.load(sys.stdin)
        meta = payload["tool_input"].get("metadata") or {}
        route = ROUTES.get(str(meta.get("source", "")).partition(":")[0])
        output = route(payload) if route else None
        if output:
            print(json.dumps(output))
    except Exception:
        pass


if __name__ == "__main__":
    main()
