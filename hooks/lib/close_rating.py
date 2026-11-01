"""The owner's close rating (D9, D9a, D9b): the one writer hooks/posttool-close-rating.py
calls and the two predicates P5's Stop gate imports. The question (/close Step 4, source
``close-rating:<task-id>``) is required asked, never answered: nothing here blocks the session.
Rows share the score scripts' log and lock and carry no ``agent`` field, which their readers skip.
"""
from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import re
import time
from pathlib import Path

SOURCE_RE = re.compile(r"^close-rating:[A-Za-z0-9][A-Za-z0-9_-]{2,80}$")
LABEL_TO_RATING = {"5 - Fully met": 5, "4 - Minor gaps": 4, "3 - Major gaps": 3, "1-2 - Not met": 1}


def _lib(name: str):
    return importlib.import_module(f".{name}" if __package__ else name, __package__ or None)


def _verdict():
    spec = importlib.util.spec_from_file_location("close_verdict", Path(__file__).with_name("close-verdict.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_task(tool_input) -> str | None:
    """The task id of an AskUserQuestion input whose metadata.source is a close-rating source."""
    meta = tool_input.get("metadata") if isinstance(tool_input, dict) else None
    source = meta.get("source") if isinstance(meta, dict) else None
    return source.split(":", 1)[1] if isinstance(source, str) and SOURCE_RE.fullmatch(source) else None


def _landed(span, task_id: str) -> int:
    """Line of the span's latest ok close-QA result for the task (qa, pipeline close, the same
    canonical task id) whose final line classify_line maps to yes; 0 when there is none."""
    canonical, verdict, line = _lib("obligation").canonical_task_id, _verdict(), 0
    want = canonical(task_id)
    for call, doc in span.obligations() if want else ():
        if (doc.get("role"), doc.get("pipeline")) == ("qa", "close") and canonical(doc.get("task_id")) == want \
                and verdict.classify_line(verdict.last_nonempty(span.result_text(call.id))) == "yes":
            line = call.result_line
    return line


def rating_required(span, task_id: str) -> bool:
    """A /close span (--auto too) holding a landed close-QA result for the task. No CLI-written
    fact marks a session that cannot offer AskUserQuestion, so headless is not read (P5 decides)."""
    return span is not None and span.command == "close" and _landed(span, task_id) > 0


def rating_asked(transcript_path, task_id: str) -> bool:
    """The /close span holds the main agent's close-rating question for the task, asked after its
    latest landed close-QA result, with its tool_result of any content (Skip, AFK, a denial)."""
    span, canonical = _lib("command_span").active_span(transcript_path), _lib("obligation").canonical_task_id
    landed = _landed(span, task_id) if span is not None and span.command == "close" else 0
    return landed > 0 and any(call.line > landed and call.result_line and canonical(source_task(call.input))
                              == canonical(task_id) for call in span.calls("AskUserQuestion"))


def append_rating(task_id: str, rating: int, tool_use_id) -> bool:
    """Append {ts, task_id, rating, tool_use_id} to the lifecycle log under an exclusive lock on
    the score scripts' <log>.lock; the task's first rating wins, read under the lock."""
    log = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "logs" / "lifecycle.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(f"{log}.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with open(log, "a+", encoding="utf-8", errors="replace") as handle:
            handle.seek(0)
            if any(re.search(rf'"task_id":\s*"{re.escape(task_id)}"', line) for line in handle):
                return False
            handle.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "task_id": task_id,
                                     "rating": rating, "tool_use_id": tool_use_id}) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    return True
