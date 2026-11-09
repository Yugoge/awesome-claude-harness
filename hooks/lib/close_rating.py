"""The owner's close rating (D9, D9b), for posttool-close-rating.py and P5's Stop gate.
handle() writes the owner's one rating row and returns the owner summary (a systemMessage).
The Stop gate imports source_task, rating_required and rating_asked. The /close question is required
asked, never answered: nothing here blocks."""
from __future__ import annotations

import importlib
import os
import re
import runpy
import time
from pathlib import Path

SOURCE_RE = re.compile(r"^close-rating:[A-Za-z0-9][A-Za-z0-9_-]{2,80}$")
LABEL_TO_RATING = {"5 - Fully met": 5, "4 - Minor gaps": 4, "3 - Major gaps": 3, "1-2 - Not met": 1}


def _lib(name: str):
    return importlib.import_module(f".{name}" if __package__ else name, __package__ or None)


def source_task(tool_input) -> str | None:
    """The task id of an AskUserQuestion input whose metadata.source is a close-rating source."""
    meta = tool_input.get("metadata") if isinstance(tool_input, dict) else None
    source = meta.get("source") if isinstance(meta, dict) else None
    return source.split(":", 1)[1] if isinstance(source, str) and SOURCE_RE.fullmatch(source) else None


def _landed(span, task_id: str) -> int:
    """Line of a /close span's latest ok close-QA result for the task (qa, pipeline close, the same
    canonical task id) whose final line classify_line maps to yes; 0 when there is none."""
    canonical, line = _lib("obligation").canonical_task_id, 0
    want = canonical(task_id) if span is not None and span.command == "close" else None
    verdict = runpy.run_path(str(Path(__file__).with_name("close-verdict.py"))) if want else {}
    for call, doc in span.obligations() if want else ():
        if (doc.get("role"), doc.get("pipeline"), canonical(doc.get("task_id"))) == ("qa", "close", want) \
                and verdict["classify_line"](verdict["last_nonempty"](span.result_text(call.id))) == "yes":
            line = call.result_line
    return line


def rating_required(span, task_id: str) -> bool:
    """A /close span (--auto too) holding a landed close-QA result for the task. No CLI-written
    fact marks a session that cannot offer AskUserQuestion, so headless is not read (P5 decides)."""
    return _landed(span, task_id) > 0


def rating_asked(transcript_path, task_id: str) -> bool:
    """The /close span holds the main agent's close-rating question for the task, asked after its
    latest landed close-QA result, with its tool_result of any content (Skip, AFK, a denial)."""
    span, canonical = _lib("command_span").active_span(transcript_path), _lib("obligation").canonical_task_id
    landed = _landed(span, task_id)
    return landed > 0 and any(call.line > landed and call.result_line and canonical(source_task(call.input))
                              == canonical(task_id) for call in span.calls("AskUserQuestion"))


def append_row(log, row: dict) -> None:
    """score-update.sh's legacy rows (no kind, no key) reach the log through score_log's writer, under the caller's lock."""
    _lib("score_log").append(log, row)


def _answered(question, response) -> int | None:
    """The rating of the owner's answer: one of the four exact labels, with none of the CLI's marks of a non-answer
    (afkTimeoutMs, free text, followUp, an annotation marked unanswered); None otherwise (Skip, free text, AFK, decline, error)."""
    response = response if isinstance(response, dict) else {}
    answers, notes = response.get("answers"), response.get("annotations")
    if any(response.get(k) for k in ("afkTimeoutMs", "response", "followUp")) or any(
            isinstance(n, dict) and n.get("unanswered") for n in (notes.values() if isinstance(notes, dict) else ())):
        return None
    answer = answers.get(question.get("question")) if isinstance(answers, dict) else None
    return LABEL_TO_RATING.get(answer) if isinstance(answer, str) else None


def _utc(seconds: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))


def handle(payload) -> dict | None:
    """The main agent's close-rating question (one question, metadata.source close-rating:<task>): at most one rating row
    through score_log, and {"systemMessage": owner summary}, returned even when no row was written (AFK, Skip, free text).
    The row's roles are the scored identities of the task's dispatches in every session of the project, read now. None
    for any other call or a log that cannot be read; never raises (a failure means no row, no output)."""
    try:
        tool_input = payload["tool_input"]
        task_id, questions = source_task(tool_input), tool_input.get("questions")
        if payload.get("tool_name") != "AskUserQuestion" or payload.get("agent_id") or not task_id \
                or not isinstance(questions, list) or len(questions) != 1 or not os.path.isabs(payload["cwd"]):
            return None
        score_log, now = _lib("score_log"), time.time()
        log, project = score_log.log_path(), score_log.project_key(payload["cwd"])
        rating = _answered(questions[0], payload.get("tool_response"))
        if rating:
            store = os.environ.get("CLAUDE_PROJECT_DIR") or payload["cwd"]
            dispatches = _lib("obligation")._task_records(task_id, store, None)  # obligation's cross-session reader
            roles = sorted({score_log.identity(d["obligation"].get("role"), d["obligation"].get("pipeline")) for d in dispatches})
            with score_log.locked(log):
                score_log.append(log, {"kind": "rating", "ts": _utc(now), "project": project, "task_id": task_id,
                                       "rating": rating, "roles": roles, "tool_use_id": payload.get("tool_use_id")})
        rows = [row for _, row in score_log.read_lines(str(log))]
        # as_of one second on: the row just written (ts truncated to the second) is before it
        return {"systemMessage": score_log.render_owner_summary(rows, project, _utc(now + 1), task_id)}
    except Exception:
        return None
