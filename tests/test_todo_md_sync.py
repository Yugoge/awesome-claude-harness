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
                "# Step 0: document title, not an executable step",
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


def test_step_only_in_todo_is_reported_as_stale() -> None:
    """An extra Python todo remains visible rather than being normalized away."""
    assert CHECKER.diff_steps(
        "extra",
        ["Step 1"],
        ["Step 1", "Step 2"],
    ) == ["extra: stale in .py — Step 2"]


def test_common_steps_in_different_order_are_reported() -> None:
    """Matching token sets do not hide ordering drift."""
    assert CHECKER.diff_steps(
        "reordered",
        ["Step 1", "Step 2"],
        ["Step 2", "Step 1"],
    ) == [
        "reordered: order drift at position 0 — "
        ".md has 'Step 1', .py has 'Step 2'"
    ]


def test_duplicate_token_count_drift_is_reported_without_false_order_drift() -> None:
    """A repeated label cannot pass merely because both sets are identical."""
    assert CHECKER.diff_steps(
        "duplicate",
        ["Step 1", "Step 2"],
        ["Step 1", "Step 1", "Step 2"],
    ) == [
        "duplicate: duplicate count drift — Step 1 appears "
        "1 time(s) in .md, 2 time(s) in .py"
    ]


def test_repository_workflows_fixed_by_this_change_are_in_sync() -> None:
    """Both repository sources are non-empty and exactly token-identical."""
    for command in ("clean", "dev-command", "dev-overnight"):
        command_doc = REPO_ROOT / "commands" / f"{command}.md"
        todo_script = REPO_ROOT / "scripts" / "todo" / f"{command}.py"
        md_steps = CHECKER.extract_md_steps(command_doc)
        py_steps = CHECKER.extract_py_steps(todo_script)

        assert md_steps, f"{command}: Markdown extraction unexpectedly empty"
        assert py_steps is not None, f"{command}: todo script execution failed"
        assert py_steps, f"{command}: Python extraction unexpectedly empty"
        assert md_steps == py_steps
        assert CHECKER.diff_steps(command, md_steps, py_steps) == []
