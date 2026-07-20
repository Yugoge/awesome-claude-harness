"""Regression tests for Codex-native workflow-plan compatibility."""

from __future__ import annotations

import importlib.util
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


def test_codex_transition_defers_delegated_call_evidence_to_stop() -> None:
    old = [_todo("in_progress", delegated=True), _todo("pending")]
    new = [_todo("completed", delegated=True), _todo("in_progress")]

    assert MODULE.validate_codex_transition({}, old, new) == []


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
