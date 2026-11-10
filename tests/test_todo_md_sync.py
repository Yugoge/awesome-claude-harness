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
    for command in ("clean", "close", "dev-command", "dev-overnight"):
        command_doc = REPO_ROOT / "commands" / f"{command}.md"
        todo_script = REPO_ROOT / "scripts" / "todo" / f"{command}.py"
        md_steps = CHECKER.extract_md_steps(command_doc)
        py_steps = CHECKER.extract_py_steps(todo_script)

        assert md_steps, f"{command}: Markdown extraction unexpectedly empty"
        assert py_steps is not None, f"{command}: todo script execution failed"
        assert py_steps, f"{command}: Python extraction unexpectedly empty"
        assert md_steps == py_steps
        assert CHECKER.diff_steps(command, md_steps, py_steps) == []


def test_close_checklist_is_steps_0_to_3b_under_every_prompt(monkeypatch) -> None:
    """P4 R11: close.md's five "### Step N" headings, whatever /close was given; the
    rating step is "Step 3b", a label no command's dispatch template sits under."""
    todo_script = REPO_ROOT / "scripts" / "todo" / "close.py"
    md_steps = CHECKER.extract_md_steps(REPO_ROOT / "commands" / "close.md")
    assert md_steps == [f"Step {n}" for n in range(4)] + ["Step 3b"]
    for prompt in ("", "--auto", "--force", "/close --codex 20260101-000000", "/close --late-repair 20260101-000000"):
        monkeypatch.setenv("CLAUDE_TODO_PROMPT", prompt)
        assert CHECKER.extract_py_steps(todo_script) == md_steps, prompt


def test_every_command_with_a_todo_script_is_in_sync() -> None:
    """Every scripts/todo/<cmd>.py and its commands/<cmd>.md list the same steps (the hook's
    session-start check, run in CI over the whole tree)."""
    pairs = 0
    for todo_script in sorted((REPO_ROOT / "scripts" / "todo").glob("*.py")):
        command_doc = REPO_ROOT / "commands" / f"{todo_script.stem}.md"
        if not command_doc.is_file():
            continue
        md_steps = CHECKER.extract_md_steps(command_doc)
        py_steps = CHECKER.extract_py_steps(todo_script)
        if not md_steps or py_steps is None:
            continue
        assert CHECKER.diff_steps(todo_script.stem, md_steps, py_steps) == [], todo_script.stem
        pairs += 1
    assert pairs >= 5


def test_the_hook_reads_its_own_harness_and_tells_the_model(tmp_path) -> None:
    """It checks the harness it belongs to, whatever HOME is, and a drift line goes to stdout
    (a SessionStart hook's stdout reaches the model; its stderr reaches no one)."""
    import os
    import shutil
    import subprocess
    import sys

    home = tmp_path / "harness"
    for part in ("hooks", "scripts/todo", "commands"):
        (home / part).mkdir(parents=True)
    shutil.copy(CHECKER_PATH, home / "hooks" / CHECKER_PATH.name)
    (home / "commands" / "x.md").write_text("### Step 1: one\n### Step 2: two\n", encoding="utf-8")
    (home / "scripts" / "todo" / "x.py").write_text(
        "import json\nprint(json.dumps([{'content': 'Step 1: one'}]))\n", encoding="utf-8")
    env = dict(os.environ, HOME=str(tmp_path / "elsewhere"), PYTHONDONTWRITEBYTECODE="1")
    env.pop("CLAUDE_HOME", None)
    proc = subprocess.run([sys.executable, str(home / "hooks" / CHECKER_PATH.name)], input="{}",
                          capture_output=True, text=True, env=env, timeout=60)
    assert proc.returncode == 0 and proc.stderr == "", proc.stderr
    assert "[todo-md-sync]" in proc.stdout and "Step 2" in proc.stdout, proc.stdout
