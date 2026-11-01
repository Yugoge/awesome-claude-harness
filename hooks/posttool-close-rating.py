#!/usr/bin/env python3
"""PostToolUse(AskUserQuestion): the one writer of the owner's close rating (D9a).

A row only for the main agent's (no agent_id) one close-rating question (metadata.source
close-rating:<task-id>) answered with exactly one of the four labels, read from the CLI's
tool_response: the CLI drops answers the model writes into its own input before the dialog.
Skip, free text, a decline, an error and an AFK auto-continue write nothing. Silent, exit 0.
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
            or not isinstance(response, dict) or any(response.get(k) for k in ("afkTimeoutMs", "response", "followUp")):
        return None
    questions, answers = tool_input.get("questions"), response.get("answers")
    if not isinstance(questions, list) or len(questions) != 1 or not isinstance(answers, dict):
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
