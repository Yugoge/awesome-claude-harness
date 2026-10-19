"""Contracts for the live ``/spec-update`` command policy and its history entry."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_command_policy_and_history_placement() -> None:
    command = (ROOT / "commands" / "spec-update.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "disable-model-invocation: true" in command
    assert all(flag in command for flag in ("--update", "--continue", "--temp"))
    assert "Migration note" not in command
    assert "/spec-continue" in changelog and "/spec-update" in changelog
