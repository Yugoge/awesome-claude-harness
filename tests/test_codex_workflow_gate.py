"""Regression tests for Codex-native workflow-plan compatibility."""

from __future__ import annotations

import importlib.util
import json
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


def _write_transcript(path: Path, *, include_final: bool = True) -> None:
    events = [
        {
            "timestamp": "2026-07-20T15:00:01.000Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "spawn_agent",
                "namespace": "collaboration",
                "call_id": "call-current",
            },
        },
        {
            "timestamp": "2026-07-20T15:00:01.100Z",
            "type": "event_msg",
            "payload": {
                "type": "sub_agent_activity",
                "event_id": "call-current",
                "kind": "started",
                "agent_path": "/root/qa_current",
                "agent_thread_id": "thread-current",
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
                    "author": "/root/qa_current",
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


def test_native_evidence_requires_spawn_start_and_final(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.jsonl"
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
    transcript = tmp_path / "transcript.jsonl"
    _write_transcript(transcript, include_final=False)
    old = [_todo("in_progress", delegated=True), _todo("pending")]
    new = [_todo("completed", delegated=True), _todo("in_progress")]
    state = {"codex_step_started_at_ms": {"0": 1784559600000}}

    assert MODULE.native_subagent_evidence_for_transition(
        {"transcript_path": str(transcript)}, "session", state, old, new
    ) == {}


def test_native_evidence_rejects_spawn_before_step_window(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.jsonl"
    _write_transcript(transcript)
    old = [_todo("in_progress", delegated=True), _todo("pending")]
    new = [_todo("completed", delegated=True), _todo("in_progress")]
    state = {"codex_step_started_at_ms": {"0": 1784559602001}}

    assert MODULE.native_subagent_evidence_for_transition(
        {"transcript_path": str(transcript)}, "session", state, old, new
    ) == {}
