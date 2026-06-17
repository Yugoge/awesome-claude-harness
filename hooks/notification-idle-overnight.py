#!/usr/bin/env python3
"""
Notification hook: Observe overnight idle events.

Matcher: idle_prompt
Lifecycle: fires when Claude Code is about to go idle (waiting for user
input). Notification hooks are exit-0-only -- they cannot block idle,
only observe it.

Behavior:
  1. Read JSON stdin (session_id, transcript_path optional, message
     preview optional).
  2. If no active overnight-state-*.json with future end_time exists for
     this session, exit 0 silently.
  3. If active, append a JSONL record to
     /root/.claude/logs/overnight-idle.jsonl with fields:
       {ts, session_id, end_time, time_remaining_seconds,
        transcript_path, current_phase, cycle_count,
        last_message_preview}
  4. Exit 0 unconditionally. Any exception is logged to stderr and
     swallowed -- a misbehaving Notification hook would interrupt every
     idle event across all sessions, which is far worse than a missing
     log entry.

Source: BA spec ba-spec-stop-hook-gap-20260426-2250.md (M3, AC3).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

_HOOKS_DIR = Path(__file__).resolve().parent
if str(_HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(_HOOKS_DIR))

try:  # WS1 shared harness-home resolver (consume resolve_optional semantics).
    from lib import claude_home  # noqa: E402
except Exception:  # pragma: no cover - fail-soft when the resolver is absent
    claude_home = None  # type: ignore[assignment]

# Relative location of the idle log under the harness home. Routed through the
# WS1 resolver at runtime (see _log_path) instead of the author literal
# /root/.claude so a fresh non-root clone logs under its OWN home.
_LOG_RELPATH = "logs/overnight-idle.jsonl"


def _log_path() -> Path:
    """Resolve the idle-log path via the WS1 harness-home resolver.

    Order: resolved harness home -> CLAUDE_PROJECT_DIR/.claude -> cwd/.claude.
    Never the author literal /root. This is an OPTIONAL observability sink: a
    Notification hook is exit-0-only and must never crash, so an unresolved
    home degrades to the project dir rather than failing.
    """
    if claude_home is not None:
        home = claude_home.resolve()
        if home is not None:
            return home / _LOG_RELPATH
        return claude_home.project_dir() / ".claude" / _LOG_RELPATH
    base = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())) / ".claude"
    return base / _LOG_RELPATH


def _read_stdin() -> dict:
    try:
        if sys.stdin.isatty():
            return {}
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except Exception:
        return {}


def _try_load_state(state_path: Path) -> dict | None:
    try:
        return json.loads(state_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _parse_end_time(state: dict) -> datetime | None:
    end_time_str = state.get("end_time")
    if not end_time_str:
        return None
    try:
        dt = datetime.fromisoformat(end_time_str)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt


def _find_active_state(session_id: str) -> tuple[dict | None, datetime | None]:
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    claude_dir = project_dir / ".claude"
    if not claude_dir.is_dir():
        return None, None
    now = datetime.now()
    candidates = []
    if session_id:
        candidates.append(claude_dir / f"overnight-state-{session_id}.json")
    candidates.extend(sorted(claude_dir.glob("overnight-state-*.json")))
    for state_path in candidates:
        if not state_path.is_file():
            continue
        state = _try_load_state(state_path)
        if state is None:
            continue
        end_time = _parse_end_time(state)
        if end_time is None or end_time <= now:
            continue
        return state, end_time
    return None, None


def _build_record(payload: dict, state: dict, end_time: datetime) -> dict:
    now = datetime.now()
    remaining = int((end_time - now).total_seconds())
    return {
        "ts": now.isoformat(timespec="seconds"),
        "session_id": state.get("session_id") or payload.get("session_id"),
        "end_time": end_time.isoformat(timespec="seconds"),
        "time_remaining_seconds": remaining,
        "transcript_path": payload.get("transcript_path"),
        "current_phase": state.get("current_phase"),
        "cycle_count": state.get("cycle_count"),
        "last_message_preview": payload.get("message")
        or payload.get("last_message_preview"),
    }


def _append_record(record: dict) -> None:
    log_path = _log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass


def main() -> int:
    try:
        payload = _read_stdin()
        session_id = payload.get("session_id") or ""
        state, end_time = _find_active_state(session_id)
        if state is None or end_time is None:
            return 0
        record = _build_record(payload, state, end_time)
        _append_record(record)
    except Exception as exc:  # pragma: no cover - fail-soft
        sys.stderr.write(f"[notification-idle-overnight] error: {exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
