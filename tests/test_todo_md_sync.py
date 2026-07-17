"""Regression tests for the session-start todo/Markdown drift detector."""

from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = REPO_ROOT / "hooks" / "check-todo-md-sync.py"

SPEC = importlib.util.spec_from_file_location("check_todo_md_sync", CHECKER_PATH)
CHECKER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(CHECKER)


def test_extract_md_steps_includes_nested_workflow_headings(tmp_path: Path) -> None:
    """Executable nested steps remain part of the Markdown/todo contract."""
    command = tmp_path / "nested.md"
    command.write_text(
        "\n".join(
            [
                "## Step 0: section title, not an executable step",
                "### Step 1: top-level workflow step",
                "#### Step 2: nested workflow step",
                "##### Step 3a: deeper nested workflow step",
                "###### Step 4: deepest valid Markdown workflow step",
                "####### Step 5: invalid Markdown heading depth",
            ]
        ),
        encoding="utf-8",
    )

    assert CHECKER.extract_md_steps(command) == [
        "Step 1",
        "Step 2",
        "Step 3a",
        "Step 4",
    ]


def test_nested_step_missing_from_todo_is_still_reported(tmp_path: Path) -> None:
    """Accepting level-4 headings must strengthen, not silence, drift checks."""
    command = tmp_path / "nested.md"
    command.write_text(
        "### Step 1: parent\n#### Step 2: required nested child\n",
        encoding="utf-8",
    )

    warnings = CHECKER.diff_steps(
        "nested",
        CHECKER.extract_md_steps(command),
        ["Step 1"],
    )

    assert warnings == ["nested: missing in .py — Step 2"]


def test_repository_nested_workflows_are_in_sync() -> None:
    """The two workflows that use nested step headings have no token drift."""
    original_commands_dir = CHECKER.COMMANDS_DIR
    CHECKER.COMMANDS_DIR = REPO_ROOT / "commands"
    try:
        for command in ("clean", "dev-overnight"):
            todo_script = REPO_ROOT / "scripts" / "todo" / f"{command}.py"
            assert CHECKER.check_one(todo_script) == []
    finally:
        CHECKER.COMMANDS_DIR = original_commands_dir
