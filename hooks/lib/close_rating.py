"""The owner's close rating (D9, D9a, D9b): the writer posttool-close-rating.py calls and the predicates P5's
Stop gate imports. The /close Step 4 question (source ``close-rating:<task-id>``) is required asked, never
answered: nothing here blocks. Rows share the score scripts' log, lock and writer; they skip rows without ``agent``."""
from __future__ import annotations

import fcntl
import importlib
import json
import os
import re
import runpy
import time
from pathlib import Path

SOURCE_RE = re.compile(r"^close-rating:[A-Za-z0-9][A-Za-z0-9_-]{2,80}$")
LABEL_TO_RATING = {"5 - Fully met": 5, "4 - Minor gaps": 4, "3 - Major gaps": 3, "1-2 - Not met": 1}
TASK_ID_FIELD = re.compile(r'"task_id":\s*"([^"]*)"')


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
    """A /close span (--auto too) holding a landed close-QA result for the task. Neither the Stop payload
    nor the transcript lists the session's tools, so a session that offers no AskUserQuestion is asked too:
    its call comes back as the CLI's own `No such tool available` error (before any hook), which
    rating_asked counts as asked, as it counts a denial (close.md Step 4)."""
    return _landed(span, task_id) > 0


def rating_asked(transcript_path, task_id: str) -> bool:
    """The /close span holds the main agent's close-rating question for the task, asked after its
    latest landed close-QA result, with its tool_result of any content (Skip, AFK, a denial)."""
    span, canonical = _lib("command_span").active_span(transcript_path), _lib("obligation").canonical_task_id
    landed = _landed(span, task_id)
    return landed > 0 and any(call.line > landed and call.result_line and canonical(source_task(call.input))
                              == canonical(task_id) for call in span.calls("AskUserQuestion"))


def append_row(log, row: dict) -> None:
    """The lifecycle log's one writer: a row appended and fsynced under the caller's exclusive lock on
    <log>.lock (append_rating's rating; score-update.sh's rows, which its heredoc hands here)."""
    with open(log, "a", encoding="utf-8") as handle:
        print(json.dumps(row, ensure_ascii=False), file=handle, flush=True)
        os.fsync(handle.fileno())


def append_rating(task_id: str, rating: int, tool_use_id) -> None:
    """Append {ts, task_id, rating, tool_use_id} to the lifecycle log under an exclusive lock on
    the score scripts' <log>.lock; the task's first rating wins (canonical ids), read under the lock."""
    log = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "logs" / "lifecycle.jsonl"
    canonical = _lib("obligation").canonical_task_id
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(f"{log}.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows = log.read_text(encoding="utf-8", errors="replace").splitlines() if log.exists() else ()
        if canonical(task_id) not in {canonical(m[1]) for m in map(TASK_ID_FIELD.search, rows) if m}:
            append_row(log, {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "task_id": task_id,
                             "rating": rating, "tool_use_id": tool_use_id})
