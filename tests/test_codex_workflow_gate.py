"""Regression tests for Codex-native workflow-plan compatibility."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


HOOK_PATH = Path(__file__).parents[1] / "hooks" / "pretool-workflow-gate.py"
SPEC = importlib.util.spec_from_file_location("pretool_workflow_gate", HOOK_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _todo(status: str, *, delegated: bool = False) -> dict[str, object]:
    todo: dict[str, object] = {"content": "step", "status": status}
    if delegated:
        todo["subagent_call"] = {"agent": "qa", "subagent_type": "qa"}
    return todo


def test_codex_transition_requires_delegated_call_evidence() -> None:
    old = [_todo("in_progress", delegated=True), _todo("pending")]
    new = [_todo("completed", delegated=True), _todo("in_progress")]

    assert MODULE.validate_codex_transition({}, old, new) == [
        "Step 0: subagent step completed before required subagent call"
    ]
    assert MODULE.validate_codex_transition({}, old, new, {0}) == []


def test_codex_transition_rejects_truthy_non_boolean_legacy_markers() -> None:
    old = [_todo("in_progress", delegated=True), _todo("pending")]
    new = [_todo("completed", delegated=True), _todo("in_progress")]

    for marker in ("false", "true", 1, [True], {"value": True}):
        assert MODULE.validate_codex_transition(
            {"subagent_calls": {"0": marker}}, old, new
        ) == ["Step 0: subagent step completed before required subagent call"]
    assert MODULE.validate_codex_transition(
        {"subagent_calls": {"0": True}}, old, new
    ) == []


def test_codex_transition_still_rejects_step_skipping() -> None:
    old = [_todo("in_progress"), _todo("pending"), _todo("pending")]
    new = [_todo("completed"), _todo("pending"), _todo("in_progress")]

    violations = MODULE.validate_codex_transition({}, old, new)

    assert "Step 2: cannot start before Step 1 is completed" in violations


def test_codex_transition_still_rejects_pending_to_completed() -> None:
    old = [_todo("completed"), _todo("pending")]
    new = [_todo("completed"), _todo("completed")]

    violations = MODULE.validate_codex_transition({}, old, new)

    assert "Step 1: pending -> completed without in_progress" in violations


def test_projected_in_progress_step_initializes_and_preserves_lower_bound(
    tmp_path: Path, monkeypatch
) -> None:
    todos = [
        _todo("in_progress", delegated=True),
        _todo("pending"),
        _todo("completed"),
    ]
    state = {
        # Model the native state owner projecting the new plan before the legacy
        # compatibility hook observes it.
        "last_todos": [todo.copy() for todo in todos],
        "codex_step_started_at_ms": {},
    }
    bookmark = tmp_path / "workflow-session.json"
    monkeypatch.setattr(
        MODULE,
        "official_todos_path",
        lambda _session_id: tmp_path / "todos.json",
    )
    monkeypatch.setattr(MODULE.time, "time_ns", lambda: 1784559602500 * 1_000_000)

    assert MODULE.persist_codex_initialization(
        "session", bookmark, state, todos, implicit=False
    )
    assert state["codex_step_started_at_ms"] == {"0": 1784559602500}

    transcript = tmp_path / "rollout-session.jsonl"
    _write_transcript(transcript)
    completed = [
        _todo("completed", delegated=True),
        _todo("in_progress"),
        _todo("completed"),
    ]
    assert MODULE.native_subagent_evidence_for_transition(
        {"transcript_path": str(transcript)}, "session", state, todos, completed
    ) == {}

    monkeypatch.setattr(MODULE.time, "time_ns", lambda: 1784559610000 * 1_000_000)
    assert MODULE.persist_codex_initialization(
        "session", bookmark, state, todos, implicit=False
    )
    assert state["codex_step_started_at_ms"] == {"0": 1784559602500}


def test_child_local_plan_does_not_touch_parent_workflow_bookmark(tmp_path: Path) -> None:
    session_id = "parent-session"
    workflow_dir = tmp_path / ".claude"
    workflow_dir.mkdir()
    bookmark = workflow_dir / f"workflow-{session_id}.json"
    parent_state = {
        "command": "dev",
        "todo_acknowledged": True,
        "last_todos": [_todo("in_progress", delegated=True)],
        "codex_step_started_at_ms": {"0": 1234},
        "codex_subagent_evidence": {"prior": {"call_id": "parent-call"}},
    }
    bookmark.write_text(json.dumps(parent_state))
    before = bookmark.read_bytes()
    transcript = tmp_path / "child.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "session_meta",
                "payload": {
                    "session_id": session_id,
                    "id": "child-thread",
                    "source": {
                        "subagent": {
                            "thread_spawn": {"parent_thread_id": session_id}
                        }
                    },
                },
            }
        )
        + "\n"
    )
    payload = {
        "session_id": session_id,
        "transcript_path": str(transcript),
        "tool_name": "functions.update_plan",
        "tool_input": {
            "plan": [
                {"step": f"child step {index}", "status": "pending"}
                for index in range(4)
            ]
        },
    }
    env = {
        **os.environ,
        "CLAUDE_COMPAT_RUNTIME": "codex",
        "CLAUDE_PROJECT_DIR": str(tmp_path),
    }

    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert bookmark.read_bytes() == before


def _write_transcript(
    path: Path,
    *,
    session_id: str = "session",
    include_final: bool = True,
    task_name: str = "qa_current",
    agent_path: str | None = None,
    agent_thread_id: str | None = "thread-current",
) -> None:
    agent_path = agent_path or f"/root/{task_name}"
    events = [
        {
            "timestamp": "2026-07-20T15:00:00.000Z",
            "type": "session_meta",
            "payload": {"id": session_id, "session_id": session_id},
        },
        {
            "timestamp": "2026-07-20T15:00:01.000Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "spawn_agent",
                "namespace": "collaboration",
                "call_id": "call-current",
                "arguments": json.dumps({"task_name": task_name, "message": "opaque"}),
            },
        },
        {
            "timestamp": "2026-07-20T15:00:01.100Z",
            "type": "event_msg",
            "payload": {
                "type": "sub_agent_activity",
                "event_id": "call-current",
                "kind": "started",
                "agent_path": agent_path,
                "agent_thread_id": agent_thread_id,
                "occurred_at_ms": 1784559601100,
            },
        },
    ]
    if include_final:
        events.append(
            {
                "timestamp": "2026-07-20T15:00:02.000Z",
                "type": "response_item",
                "payload": {
                    "type": "agent_message",
                    "author": agent_path,
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Message Type: FINAL_ANSWER\nPayload:\nok",
                        }
                    ],
                },
            }
        )
    path.write_text("".join(json.dumps(event) + "\n" for event in events))


def _append_transcript_events(path: Path, *events: dict) -> None:
    with path.open("a") as handle:
        handle.write("".join(json.dumps(event) + "\n" for event in events))


def test_native_evidence_requires_spawn_start_and_final(tmp_path: Path) -> None:
    transcript = tmp_path / "rollout-session.jsonl"
    _write_transcript(transcript)
    old = [_todo("in_progress", delegated=True), _todo("pending")]
    new = [_todo("completed", delegated=True), _todo("in_progress")]
    state = {"codex_step_started_at_ms": {"0": 1784559600000}}

    evidence = MODULE.native_subagent_evidence_for_transition(
        {"transcript_path": str(transcript)}, "session", state, old, new
    )

    assert evidence[0]["call_id"] == "call-current"
    assert evidence[0]["agent_thread_id"] == "thread-current"


def test_native_evidence_rejects_missing_final(tmp_path: Path) -> None:
    transcript = tmp_path / "rollout-session.jsonl"
    _write_transcript(transcript, include_final=False)
    old = [_todo("in_progress", delegated=True), _todo("pending")]
    new = [_todo("completed", delegated=True), _todo("in_progress")]
    state = {"codex_step_started_at_ms": {"0": 1784559600000}}

    assert MODULE.native_subagent_evidence_for_transition(
        {"transcript_path": str(transcript)}, "session", state, old, new
    ) == {}


def test_native_evidence_rejects_spawn_before_step_window(tmp_path: Path) -> None:
    transcript = tmp_path / "rollout-session.jsonl"
    _write_transcript(transcript)
    old = [_todo("in_progress", delegated=True), _todo("pending")]
    new = [_todo("completed", delegated=True), _todo("in_progress")]
    state = {"codex_step_started_at_ms": {"0": 1784559602001}}

    assert MODULE.native_subagent_evidence_for_transition(
        {"transcript_path": str(transcript)}, "session", state, old, new
    ) == {}


def test_native_evidence_rejects_foreign_session_transcript(tmp_path: Path) -> None:
    transcript = tmp_path / "rollout-session.jsonl"
    _write_transcript(transcript, session_id="foreign-session")
    old = [_todo("in_progress", delegated=True), _todo("pending")]
    new = [_todo("completed", delegated=True), _todo("in_progress")]
    state = {"codex_step_started_at_ms": {"0": 1784559600000}}

    assert MODULE.native_subagent_evidence_for_transition(
        {"transcript_path": str(transcript)}, "session", state, old, new
    ) == {}


def test_native_evidence_rejects_conflicting_later_session_meta(tmp_path: Path) -> None:
    transcript = tmp_path / "rollout-session.jsonl"
    _write_transcript(transcript)
    _append_transcript_events(
        transcript,
        {
            "timestamp": "2026-07-20T15:00:03.000Z",
            "type": "session_meta",
            "payload": {"id": "foreign-session", "session_id": "foreign-session"},
        },
    )
    old = [_todo("in_progress", delegated=True), _todo("pending")]
    new = [_todo("completed", delegated=True), _todo("in_progress")]
    state = {"codex_step_started_at_ms": {"0": 1784559600000}}

    assert MODULE.native_subagent_evidence_for_transition(
        {"transcript_path": str(transcript)}, "session", state, old, new
    ) == {}


def test_auto_discovery_rejects_ambiguous_current_session_transcripts(
    tmp_path: Path, monkeypatch
) -> None:
    sessions = tmp_path / ".codex" / "sessions"
    for directory in (sessions / "a", sessions / "b"):
        directory.mkdir(parents=True)
        _write_transcript(directory / "rollout-session.jsonl")
    monkeypatch.setattr(MODULE.Path, "home", lambda: tmp_path)

    assert MODULE._transcript_path({}, "session") is None


def test_native_evidence_rejects_missing_child_thread(tmp_path: Path) -> None:
    transcript = tmp_path / "rollout-session.jsonl"
    _write_transcript(transcript, agent_thread_id=None)
    old = [_todo("in_progress", delegated=True), _todo("pending")]
    new = [_todo("completed", delegated=True), _todo("in_progress")]
    state = {"codex_step_started_at_ms": {"0": 1784559600000}}

    assert MODULE.native_subagent_evidence_for_transition(
        {"transcript_path": str(transcript)}, "session", state, old, new
    ) == {}


def test_native_evidence_rejects_spawn_path_disagreement(tmp_path: Path) -> None:
    transcript = tmp_path / "rollout-session.jsonl"
    _write_transcript(
        transcript,
        task_name="qa_current",
        agent_path="/root/graphify_enrich",
    )
    old = [_todo("in_progress", delegated=True), _todo("pending")]
    new = [_todo("completed", delegated=True), _todo("in_progress")]
    state = {"codex_step_started_at_ms": {"0": 1784559600000}}

    assert MODULE.native_subagent_evidence_for_transition(
        {"transcript_path": str(transcript)}, "session", state, old, new
    ) == {}


def test_native_evidence_rejects_wrong_canonical_role(tmp_path: Path) -> None:
    transcript = tmp_path / "rollout-session.jsonl"
    _write_transcript(transcript, task_name="graphify_enrich")
    old = [_todo("in_progress", delegated=True), _todo("pending")]
    new = [_todo("completed", delegated=True), _todo("in_progress")]
    state = {"codex_step_started_at_ms": {"0": 1784559600000}}

    assert MODULE.native_subagent_evidence_for_transition(
        {"transcript_path": str(transcript)}, "session", state, old, new
    ) == {}


def test_task_name_role_matching_accepts_real_codex_lane_names() -> None:
    assert MODULE._task_name_matches_role("qa", "qa")
    assert MODULE._task_name_matches_role("qa_current", "qa")
    assert MODULE._task_name_matches_role("close_qa", "qa")
    assert MODULE._task_name_matches_role("baqa_terminal", "qa")
    assert MODULE._task_name_matches_role("close_style_inspector", "style-inspector")


def test_task_name_role_matching_rejects_substrings_and_wrong_compound_role() -> None:
    assert not MODULE._task_name_matches_role("quality", "qa")
    assert not MODULE._task_name_matches_role("equalizer", "qa")
    assert not MODULE._task_name_matches_role("baqa_terminal", "ba")
    assert not MODULE._task_name_matches_role("graphify_enrich", "qa")


def test_native_evidence_accepts_real_qa_task_names(tmp_path: Path) -> None:
    old = [_todo("in_progress", delegated=True), _todo("pending")]
    new = [_todo("completed", delegated=True), _todo("in_progress")]
    state = {"codex_step_started_at_ms": {"0": 1784559600000}}

    for task_name in ("close_qa", "baqa_terminal"):
        transcript = tmp_path / f"rollout-{task_name}-session.jsonl"
        _write_transcript(transcript, task_name=task_name)

        evidence = MODULE.native_subagent_evidence_for_transition(
            {"transcript_path": str(transcript)}, "session", state, old, new
        )

        assert evidence[0]["task_name"] == task_name


def test_native_evidence_rejects_reused_child_thread(tmp_path: Path) -> None:
    transcript = tmp_path / "rollout-session.jsonl"
    _write_transcript(transcript)
    old = [_todo("in_progress", delegated=True), _todo("pending")]
    new = [_todo("completed", delegated=True), _todo("in_progress")]
    state = {
        "codex_step_started_at_ms": {"0": 1784559600000},
        "codex_subagent_evidence": {
            "previous": {
                "call_id": "different-call",
                "agent_thread_id": "thread-current",
            }
        },
    }

    assert MODULE.native_subagent_evidence_for_transition(
        {"transcript_path": str(transcript)}, "session", state, old, new
    ) == {}


def test_native_evidence_rejects_current_window_thread_reuse(tmp_path: Path) -> None:
    transcript = tmp_path / "rollout-session.jsonl"
    _write_transcript(transcript)
    _append_transcript_events(
        transcript,
        {
            "timestamp": "2026-07-20T15:00:03.000Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "spawn_agent",
                "namespace": "collaboration",
                "call_id": "call-other",
                "arguments": json.dumps(
                    {"task_name": "qa_other", "message": "opaque"}
                ),
            },
        },
        {
            "timestamp": "2026-07-20T15:00:03.100Z",
            "type": "event_msg",
            "payload": {
                "type": "sub_agent_activity",
                "event_id": "call-other",
                "kind": "started",
                "agent_path": "/root/qa_other",
                "agent_thread_id": "thread-current",
                "occurred_at_ms": 1784559603100,
            },
        },
    )
    old = [_todo("in_progress", delegated=True), _todo("pending")]
    new = [_todo("completed", delegated=True), _todo("in_progress")]
    state = {"codex_step_started_at_ms": {"0": 1784559600000}}

    assert MODULE.native_subagent_evidence_for_transition(
        {"transcript_path": str(transcript)}, "session", state, old, new
    ) == {}


def test_native_evidence_rejects_current_window_call_reuse(tmp_path: Path) -> None:
    transcript = tmp_path / "rollout-session.jsonl"
    _write_transcript(transcript)
    _append_transcript_events(
        transcript,
        {
            "timestamp": "2026-07-20T15:00:03.100Z",
            "type": "event_msg",
            "payload": {
                "type": "sub_agent_activity",
                "event_id": "call-current",
                "kind": "started",
                "agent_path": "/root/qa_current",
                "agent_thread_id": "thread-other",
                "occurred_at_ms": 1784559603100,
            },
        },
    )
    old = [_todo("in_progress", delegated=True), _todo("pending")]
    new = [_todo("completed", delegated=True), _todo("in_progress")]
    state = {"codex_step_started_at_ms": {"0": 1784559600000}}

    assert MODULE.native_subagent_evidence_for_transition(
        {"transcript_path": str(transcript)}, "session", state, old, new
    ) == {}


def test_native_evidence_deduplicates_exact_terminal_messages(tmp_path: Path) -> None:
    transcript = tmp_path / "rollout-session.jsonl"
    _write_transcript(transcript)
    _append_transcript_events(
        transcript,
        {
            "timestamp": "2026-07-20T15:00:03.000Z",
            "type": "response_item",
            "payload": {
                "type": "agent_message",
                "author": "/root/qa_current",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Message Type: FINAL_ANSWER\nPayload:\nrepeat",
                    }
                ],
            },
        },
    )

    completed = MODULE.completed_codex_subagents(
        {"transcript_path": str(transcript)}, "session", 1784559600000
    )

    assert len(completed) == 1
    assert completed[0]["call_id"] == "call-current"
    assert completed[0]["agent_thread_id"] == "thread-current"
    assert completed[0]["terminal_at_ms"] == 1784559603000
