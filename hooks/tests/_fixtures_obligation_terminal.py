#!/usr/bin/env python3
"""Shared fixture builders for the G4 terminal-gate test pair (ticket
20260930-132644-l4): hooks/tests/test_stop_obligation_gate.py and
hooks/tests/test_posttool_overnight_loop_terminal_gate.py.

NOT a test module itself (no test_* functions -- pytest will not collect
assertions from here). Builds fake top-level-session transcripts (JSONL)
carrying Agent/Task dispatch tool_use records with embedded
``<obligation v="1">`` blocks, plus overnight-state and dev-report
fixtures, so both test files share one construction path instead of
duplicating it -- the same "do not duplicate the scan logic" discipline the
ticket applies to the hooks themselves, extended here to their tests.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_HOOKS_DIR = Path(__file__).resolve().parent.parent
if str(_HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(_HOOKS_DIR))
from lib import obligation  # type: ignore  # noqa: E402


def user_record(text: str) -> dict:
    """A transcript JSONL record for a type=="user" turn (plain-string
    content, the shape read_first_record_prompt documents as observed live
    on this store)."""
    return {"type": "user", "message": {"role": "user", "content": text}}


def agent_dispatch_record(tool_use_id: str, prompt: str, name: str = "Agent") -> dict:
    """A transcript JSONL record for an assistant turn containing one
    Agent/Task tool_use dispatch block -- the exact shape
    subagent_restart._read_parent_calls scans for."""
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": tool_use_id, "name": name,
                 "input": {"prompt": prompt}},
            ],
        },
    }


def build_obligation_doc(
    task_id: str = "20260930-132644-l4",
    lane: str | None = "l4",
    role: str = "dev",
    pipeline: str = "dev",
    profile: str = "fanout-lane",
    artifact_path: str = "docs/dev/dev-report-20260930-132644-l4.json",
    schema: str = "dev-report.v2",
    dispatched_at: str | None = None,
) -> dict:
    """A grammar-valid obligation document (hooks/lib/obligation.py
    validate_obligation) declaring exactly one json-kind artifact."""
    return {
        "task_id": task_id,
        "lane": lane,
        "role": role,
        "pipeline": pipeline,
        "profile": profile,
        "dispatched_at": dispatched_at or datetime.now(timezone.utc).isoformat(),
        "artifacts": [
            {
                "kind": "json",
                "path": artifact_path,
                "schema": schema,
                "identity": {"task_id": task_id},
            }
        ],
    }


def write_transcript(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


def make_dev_family_transcript(
    transcript_dir: Path,
    project_dir: Path,
    dev_registry_token: str,
    obligation_doc: dict | None = None,
    first_user_message: str = "/dev fix the thing",
    tool_use_id: str = "toolu_001",
) -> Path:
    """A fake top-level transcript: first-record user message, then one
    Agent dispatch carrying the dev-registry token (+ optional obligation
    block). Also creates the dev-registry token directory under
    project_dir so the classification's filesystem confirmation succeeds."""
    (project_dir / ".claude" / "dev-registry" / dev_registry_token).mkdir(
        parents=True, exist_ok=True)
    prompt = (
        f"FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/"
        f"{dev_registry_token}/dev.json to register with the enforcement system."
    )
    if obligation_doc is not None:
        prompt += "\n\n" + obligation.serialize_obligation(obligation_doc)
    transcript_path = transcript_dir / "transcript.jsonl"
    write_transcript(transcript_path, [
        user_record(first_user_message),
        agent_dispatch_record(tool_use_id, prompt),
    ])
    return transcript_path


def make_non_dev_family_transcript(
    transcript_dir: Path, first_user_message: str = "hello"
) -> Path:
    """A transcript with an Agent dispatch that contains NO dev-registry
    reference anywhere -- not dev-family (AC9 / scenario e)."""
    transcript_path = transcript_dir / "transcript.jsonl"
    write_transcript(transcript_path, [
        user_record(first_user_message),
        agent_dispatch_record("toolu_001", "a plain dispatch with no dev-registry reference"),
    ])
    return transcript_path


def write_dev_report(
    project_dir: Path,
    timestamp_suffix: str,
    status: str | None,
    omit_status_field: bool = False,
) -> None:
    """Write a minimal dev-report fixture with the given dev.status (or an
    object missing the status field entirely, for the AC10 positive
    control's "no per-lane status field recorded at all" variant)."""
    d = project_dir / "docs" / "dev"
    d.mkdir(parents=True, exist_ok=True)
    dev_obj: dict = {} if omit_status_field else {"status": status}
    record = {
        "task_id": timestamp_suffix,
        "request_id": timestamp_suffix,
        "dev": dev_obj,
    }
    (d / f"dev-report-{timestamp_suffix}.json").write_text(json.dumps(record))


def write_overnight_state(
    state_path: Path,
    session_id: str,
    cycle_count: int = 0,
    current_issues: list[dict] | None = None,
    end_time_minutes_from_now: int = 60,
) -> dict:
    """Write an overnight-state-<session_id>.json fixture with all todos
    implicitly completed (the caller supplies tool_input separately) and a
    future end_time so the expiry-precedence guard does not short-circuit."""
    end_time = (
        datetime.now(timezone.utc) + timedelta(minutes=end_time_minutes_from_now)
    ).isoformat()
    state = {
        "session_id": session_id,
        "cycle_count": cycle_count,
        "end_time": end_time,
        "current_phase": "retro",
        "current_issues": current_issues or [],
        "unresolved_issues": [],
        "pm_triage_reports": [],
        "pm_retro_reports": [],
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2))
    return state


def all_completed_todo_payload(session_id: str, transcript_path: str = "") -> dict:
    """The PostToolUse:TodoWrite stdin payload with every todo completed."""
    return {
        "session_id": session_id,
        "transcript_path": transcript_path,
        "tool_input": {
            "todos": [
                {"content": "step one", "status": "completed"},
                {"content": "step two", "status": "completed"},
            ]
        },
    }
