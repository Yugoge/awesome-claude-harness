"""The owner's close rating: handle() writes its row and returns the owner summary; the predicates P5's Stop gate imports."""
from __future__ import annotations

import contextlib
import importlib
import os
import re
import runpy
import time
from pathlib import Path

try:  # as hooks.lib.close_rating (tests), or from hooks/lib on the path (the hook, score-update.sh): the writer's module, by name
    from . import score_log
except ImportError:
    import score_log

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
    span = _lib("command_span").active_span(transcript_path)
    landed = _landed(span, task_id)
    return landed > 0 and _lib("requirement_round").asked(span, f"close-rating:{task_id}", after=landed)


def append_row(log, row: dict) -> None:
    """score-update.sh's legacy rows go through score_log's writer, under the caller's lock."""
    score_log.append(log, row)


def _utc(seconds: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))


def handle(payload) -> dict | None:
    """A main-agent close-rating call: at most one rating row, and the owner summary as a systemMessage; else None; never raises."""
    try:
        tool_input = payload["tool_input"]
        task_id, questions, response = source_task(tool_input), tool_input.get("questions"), payload.get("tool_response")
        if payload.get("tool_name") != "AskUserQuestion" or payload.get("agent_id") or not task_id \
                or not isinstance(questions, list) or len(questions) != 1 or not os.path.isabs(payload["cwd"]):
            return None
        response = response if isinstance(response, dict) else {}
        answers, notes = response.get("answers"), response.get("annotations")
        answer = answers.get(questions[0]["question"]) if isinstance(answers, dict) else None
        unanswered = any(response.get(k) for k in ("afkTimeoutMs", "response", "followUp")) or any(
            isinstance(n, dict) and n.get("unanswered") for n in (notes.values() if isinstance(notes, dict) else ()))
        rating = LABEL_TO_RATING.get(answer) if isinstance(answer, str) and not unanswered else None
        log, project = score_log.log_path(), score_log.project_key(payload["cwd"])
        if rating:
            dispatches = _lib("obligation")._task_records(task_id, os.environ.get("CLAUDE_PROJECT_DIR") or payload["cwd"], None)
            roles = sorted({score_log.identity(d["obligation"].get("role"), d["obligation"].get("pipeline")) for d in dispatches})
            with score_log.locked(log):
                score_log.append(log, {"kind": "rating", "ts": _utc(time.time()), "project": project, "task_id": task_id,
                                       "rating": rating, "roles": roles, "tool_use_id": payload.get("tool_use_id")})
            with contextlib.suppress(Exception):
                _lib("score_events").sweep(payload["transcript_path"], payload["cwd"])
        rows =[row for _, row in score_log.read_lines(str(log))]
        return {"systemMessage": score_log.render_owner_summary(rows, project, _utc(time.time() + 1), task_id)}
    except Exception:
        return None
