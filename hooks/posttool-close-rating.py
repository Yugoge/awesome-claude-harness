#!/usr/bin/env python3
"""PostToolUse(AskUserQuestion): the one writer of the owner's close rating (D9a). A row only for the
main agent's (no agent_id) one close-rating question (metadata.source close-rating:<task-id>) answered with
one of the four exact labels in the CLI's tool_response (the CLI drops answers the model writes in its input).
Skip, free text, a decline, an error, an AFK auto-continue or any other payload: no row. Silent, exit 0 (D9b)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))


def main() -> None:
    try:  # a payload of another shape raises here and writes nothing
        import close_rating
        payload = json.load(sys.stdin)
        tool_input, response = payload["tool_input"], payload["tool_response"]
        [question] = tool_input["questions"]
        task_id = close_rating.source_task(tool_input)
        rating = close_rating.LABEL_TO_RATING.get(response["answers"].get(question["question"]))
        if task_id and rating and payload.get("tool_name") == "AskUserQuestion" and not payload.get("agent_id") \
                and not any(response.get(k) for k in ("afkTimeoutMs", "response", "followUp")):
            close_rating.append_rating(task_id, rating, payload.get("tool_use_id"))
    except Exception:
        pass


if __name__ == "__main__":
    main()
