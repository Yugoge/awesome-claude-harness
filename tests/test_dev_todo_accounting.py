from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "hooks"
DEV_TODO_SCRIPT = ROOT / "scripts/todo/dev.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _frontier(todos: list[dict], index: int, *, completed: bool = False) -> list[dict]:
    value = copy.deepcopy(todos)
    for idx, item in enumerate(value):
        if idx < index or (completed and idx == index):
            item["status"] = "completed"
        elif idx == index:
            item["status"] = "in_progress"
        else:
            item["status"] = "pending"
    return value


@pytest.fixture(scope="module")
def todos() -> list[dict]:
    result = subprocess.run(
        [sys.executable, str(DEV_TODO_SCRIPT)],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    value = json.loads(result.stdout)
    assert value
    return value


@pytest.fixture(scope="module")
def guards():
    sys.path.insert(0, str(HOOKS))
    return {
        "pre": _load_module(HOOKS / "pretool-todo-validate.py", "lguards_pre_todo"),
        "post": _load_module(HOOKS / "posttool-todo-sequence.py", "lguards_post_todo"),
        "gate": _load_module(HOOKS / "pretool-workflow-gate.py", "lguards_workflow_gate"),
        "canonical": _load_module(HOOKS / "lib/todo_canonical.py", "lguards_todo_canonical"),
    }


def test_real_generic_validators_accept_every_projected_transition(todos, guards):
    pre, post, gate, canonical = (
        guards["pre"], guards["post"], guards["gate"], guards["canonical"]
    )
    errors: list[str] = []
    last = _frontier(todos, 0)
    post.check_initial_status(last, errors)
    for index in range(1, len(todos)):
        new = _frontier(todos, index)
        errors.extend(pre.validate(last, new))
        post.check_content_immutability(last, new, errors)
        post.check_completion_rules(last, new, errors)
        errors.extend(
            gate.validate_codex_transition(
                {"subagent_calls": {str(index - 1): True}}, last, new
            )
        )
        canonical.check_immutability_against_canonical(todos, new, errors)
        last = new
    final = _frontier(todos, len(todos) - 1, completed=True)
    errors.extend(pre.validate(last, final))
    errors.extend(
        gate.validate_codex_transition(
            {"subagent_calls": {str(len(todos) - 1): True}}, last, final
        )
    )
    assert errors == []


def _invalid_case(guard: str, todos: list[dict], guards) -> list[str]:
    pre, canonical = guards["pre"], guards["canonical"]
    old = _frontier(todos, 0)
    all_pending = copy.deepcopy(todos)
    if guard == "max_one_completion":
        new = copy.deepcopy(old)
        new[0]["status"] = "completed"
        new[1]["status"] = "completed"
        return pre.validate(old, new)
    if guard == "pending_to_completed":
        new = copy.deepcopy(all_pending)
        new[0]["status"] = "completed"
        return pre.validate(all_pending, new)
    if guard == "multiple_in_progress":
        new = copy.deepcopy(old)
        new[1]["status"] = "in_progress"
        return pre.validate(old, new)
    if guard == "out_of_order":
        new = copy.deepcopy(all_pending)
        new[1]["status"] = "in_progress"
        return pre.validate(all_pending, new)
    if guard == "content_immutable":
        new = copy.deepcopy(old)
        new[0]["content"] += " tampered"
        return pre.validate(old, new)
    if guard == "full_list":
        violations: list[str] = []
        canonical.check_immutability_against_canonical(todos, todos[:-1], violations)
        return violations
    raise AssertionError(guard)


@pytest.mark.parametrize(
    "guard",
    [
        "max_one_completion",
        "pending_to_completed",
        "multiple_in_progress",
        "out_of_order",
        "content_immutable",
        "full_list",
    ],
)
def test_generic_invalid_transitions_remain_rejected(todos, guards, guard: str):
    assert _invalid_case(guard, todos, guards)


def test_five_real_subagent_guards_remain(todos, guards):
    gate = guards["gate"]
    results = []
    for index, item in enumerate(todos):
        call = item.get("subagent_call")
        if not call:
            continue
        old_step = _frontier(todos, index)
        new_step = (
            _frontier(todos, index + 1)
            if index + 1 < len(todos)
            else _frontier(todos, index, completed=True)
        )
        missing = gate.validate_codex_transition({}, old_step, new_step)
        present = gate.validate_codex_transition(
            {"subagent_calls": {str(index): True}}, old_step, new_step
        )
        results.append(
            (
                call.get("subagent_type"),
                any("before required subagent call" in value for value in missing),
                not present,
            )
        )
    assert [role for role, _, _ in results] == ["ba", "qa", "graphify", "dev", "qa"]
    assert all(rejected for _, rejected, _ in results)
    assert all(accepted for _, _, accepted in results)
