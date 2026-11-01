#!/usr/bin/env python3
"""PostToolUse(AskUserQuestion): the one writer of the owner's close rating (D9a).

A row (lib/close_rating.append_rating) only when the main agent (no agent_id)
asked the close-rating question (metadata.source close-rating:<task-id>, one
question) and the dialog's answer is exactly one of the four labels. The answer
is read from the CLI's tool_response, never from the model's tool_input: the
CLI drops answers the model writes into its input before the dialog runs.
Skip, free text, a decline, an error result and an AFK auto-continue write
nothing. It prints nothing and exits 0 on every path: the rating never blocks.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))


def _rating(payload: dict, close_rating):
    """(task id, rating) of an exact-label answer to the main agent's close-rating question, else None."""
    tool_input, response = payload.get("tool_input"), payload.get("tool_response")
    task_id = close_rating.source_task(tool_input)
    if payload.get("agent_id") or payload.get("tool_name") != "AskUserQuestion" or not task_id \
            or not isinstance(response, dict) or response.get("afkTimeoutMs") or response.get("response") \
            or response.get("followUp"):
        return None
    questions, answers = tool_input.get("questions"), response.get("answers")
    if not isinstance(questions, list) or len(questions) != 1 or not isinstance(questions[0], dict) \
            or not isinstance(answers, dict):
        return None
    answer = answers.get(questions[0].get("question"))
    rating = close_rating.LABEL_TO_RATING.get(answer) if isinstance(answer, str) else None
    return (task_id, rating) if rating else None


def main() -> int:
    try:
        import close_rating
        payload = json.load(sys.stdin)
        found = _rating(payload, close_rating) if isinstance(payload, dict) else None
        if found:
            close_rating.append_rating(*found, payload.get("tool_use_id"))
    except Exception:  # the rating never blocks and never speaks to the model (D9b)
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
