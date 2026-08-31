#!/usr/bin/env python3
"""Executable C10 accounting proof for the ordinary ``/dev`` checklist."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

BEFORE = {
    "items": 17,
    "source_bytes": 3418,
    "source_sha256": "1148d94f6d7b144547e0d1e2a5dd7bb829af511ca5dcc06e1af60cb82c640bad",
    "stdout_bytes": 3052,
    "stdout_sha256": "e630d7b7c0c7ad150c5420d3be56d2b94317c47d9b1d88b33d85c8ae849fc544",
    "canonical_compact_sort_keys_sha256": "2515d41497da0f03a6890916e73356c8685f73f53b7ecae7036659f4da0501b7",
}
CONTROLS = {
    "dev_command": {
        "path": "scripts/todo/dev-command.py",
        "mode": "0755",
        "items": 16,
        "source_bytes": 2778,
        "source_sha256": "8e0fb9df1e6b40bfcf67a0cca61ca8fced04e5563ea653dfb0e48dd83ba10300",
        "stdout_bytes": 2818,
        "stdout_sha256": "8e308ca4f997e1cc5b1c5706a93ac15a776f5c021c3e3b1323db1062035fc8c6",
        "canonical_compact_sort_keys_sha256": "2cd3eb2064e51717036e8777526501d3756a63b52b43a6b4f29dbd36d6f3e748",
    },
    "dev_overnight": {
        "path": "scripts/todo/dev-overnight.py",
        "mode": "0644",
        "items": 22,
        "source_bytes": 4189,
        "source_sha256": "414ce617a3010b52d8d0d1434083ba30ab3bb6edc1b239dd7a736d52df50fdd8",
        "stdout_bytes": 4168,
        "stdout_sha256": "9e22b88b2839b682456b85eda1f0801f3d146cf06f8f544bd40c4cc4f9591105",
        "canonical_compact_sort_keys_sha256": "132f9b0b1e149a984498321b2870572f9373fbab562e38c026877ef028084bb0",
    },
}
READ_ONLY = {
    "hooks/lib/todo_canonical.py": "a6725b02fe6bd255308df8a9bcf59153bdb90c89d3962ea22d529ba6f347a5ec",
    "hooks/pretool-todo-validate.py": "57a0319cf259b5e5d716388b091e4f2895e1cbf155849543faf821ec93da9d80",
    "hooks/posttool-todo-sequence.py": "d25d9326ae317eccda6c3514531fe00483467a4b66a189b96e4b5d7a76d3fb41",
    "hooks/posttool-todo-count.py": "7f8ec8a794c36c26fcce13577728e3c77a08a1bca8b8c9154b3c6f28e4f6c918",
    "hooks/prompt-workflow.py": "c27c35e457b93455d0e52cea09f1f9b5593ab1df681b2e14826305eed6830f65",
    "hooks/posttool-todo-tracker.py": "ceb22264bbf3216d630b67676c282bb8818f40469a549b8932690a35546c8511",
    "hooks/pretool-workflow-gate.py": "a5b1cd36da1311dd08c590619417d5c0e773ce872125f5218ad0e77adbbac781",
    "hooks/posttool-subagent-track.py": "746916ac148fd09346e06bf15b8c2b3eba9c9936058f553b5077be2327942c68",
    "commands/dev.md": "a5dd14cd9c57e1e444c81dbd41f7153db73b19e245119cf9531ee52a9926e7f0",
    "commands/dev-command.md": "46a0ba2c4f8fff73aee6e16ed7c3a7d8b0bd611340a7dc04a9d47b40a0d5ff7f",
    "commands/dev-overnight.md": "413703685d76cb5620e5a00d852aa7a9d6c48c43a845519a5b959fed11566898",
}
EXPECTED_ROLES = ["ba", "qa", "graphify", "dev", "qa"]


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _compact(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _measure_script(root: Path, relative: str) -> tuple[dict[str, Any], list[dict]]:
    path = root / relative
    source = path.read_bytes()
    result = subprocess.run(
        [sys.executable, str(path)],
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    todos = json.loads(result.stdout) if result.returncode == 0 else []
    measured = {
        "path": relative,
        "mode": f"{path.stat().st_mode & 0o777:04o}",
        "items": len(todos),
        "source_bytes": len(source),
        "source_sha256": _sha(source),
        "stdout_bytes": len(result.stdout),
        "stdout_sha256": _sha(result.stdout),
        "stderr_bytes": len(result.stderr),
        "exit_code": result.returncode,
        "canonical_compact_sort_keys_sha256": _sha(_compact(todos)),
    }
    return measured, todos


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


def _validator_accounting(root: Path, todos: list[dict]) -> dict[str, Any]:
    hooks = root / "hooks"
    sys.path.insert(0, str(hooks))
    pre = _load_module(hooks / "pretool-todo-validate.py", "lguards_pre_todo")
    post = _load_module(hooks / "posttool-todo-sequence.py", "lguards_post_todo")
    gate = _load_module(hooks / "pretool-workflow-gate.py", "lguards_workflow_gate")
    canonical = _load_module(hooks / "lib/todo_canonical.py", "lguards_todo_canonical")

    valid_errors: list[str] = []
    initial = _frontier(todos, 0)
    initial_violations: list[str] = []
    post.check_initial_status(initial, initial_violations)
    valid_errors.extend(initial_violations)
    last = initial
    call_count = 1
    for index in range(1, len(todos)):
        new = _frontier(todos, index)
        valid_errors.extend(pre.validate(last, new))
        post_violations: list[str] = []
        post.check_content_immutability(last, new, post_violations)
        post.check_completion_rules(last, new, post_violations)
        valid_errors.extend(post_violations)
        role_state = {"subagent_calls": {str(index - 1): True}}
        valid_errors.extend(gate.validate_codex_transition(role_state, last, new))
        canonical_violations: list[str] = []
        canonical.check_immutability_against_canonical(todos, new, canonical_violations)
        valid_errors.extend(canonical_violations)
        last = new
        call_count += 1
    final = _frontier(todos, len(todos) - 1, completed=True)
    valid_errors.extend(pre.validate(last, final))
    state = {"subagent_calls": {str(len(todos) - 1): True}}
    valid_errors.extend(gate.validate_codex_transition(state, last, final))
    call_count += 1

    old = _frontier(todos, 0)
    invalid_cases: dict[str, bool] = {}
    invalid_details: dict[str, list[str]] = {}

    two_complete = copy.deepcopy(old)
    two_complete[0]["status"] = "completed"
    two_complete[1]["status"] = "completed"
    violations = pre.validate(old, two_complete)
    invalid_cases["max_one_completion"] = bool(violations)
    invalid_details["max_one_completion"] = violations

    all_pending = copy.deepcopy(todos)
    skipped = copy.deepcopy(all_pending)
    skipped[0]["status"] = "completed"
    violations = pre.validate(all_pending, skipped)
    invalid_cases["pending_to_completed"] = bool(violations)
    invalid_details["pending_to_completed"] = violations

    multiple = copy.deepcopy(old)
    multiple[1]["status"] = "in_progress"
    violations = pre.validate(old, multiple)
    invalid_cases["multiple_in_progress"] = bool(violations)
    invalid_details["multiple_in_progress"] = violations

    out_of_order = copy.deepcopy(all_pending)
    out_of_order[1]["status"] = "in_progress"
    violations = pre.validate(all_pending, out_of_order)
    invalid_cases["out_of_order"] = bool(violations)
    invalid_details["out_of_order"] = violations

    changed = copy.deepcopy(old)
    changed[0]["content"] += " tampered"
    violations = pre.validate(old, changed)
    invalid_cases["content_immutable"] = bool(violations)
    invalid_details["content_immutable"] = violations

    short_violations: list[str] = []
    canonical.check_immutability_against_canonical(todos, todos[:-1], short_violations)
    invalid_cases["full_list"] = bool(short_violations)
    invalid_details["full_list"] = short_violations

    guard_results = []
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
        guard_results.append(
            {
                "index": index,
                "role": call.get("subagent_type"),
                "missing_call_rejected": any(
                    "before required subagent call" in value for value in missing
                ),
                "recorded_call_accepted": not present,
            }
        )

    return {
        "accepted_call_count": call_count,
        "valid_transition_errors": valid_errors,
        "invalid_cases": invalid_cases,
        "invalid_details": invalid_details,
        "subagent_guards": guard_results,
    }


def run(project_root: Path) -> dict[str, Any]:
    root = project_root.resolve()
    violations: list[str] = []
    fixture_path = root / "tests/fixtures/dev-todo-canonical-before.v1.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    before_todos = fixture["todos"]
    before_summary = {
        "items": fixture["item_count"],
        "source_bytes": fixture["source_bytes"],
        "source_sha256": fixture["source_sha256"],
        "stdout_bytes": fixture["stdout_bytes"],
        "stdout_sha256": fixture["stdout_sha256"],
        "canonical_compact_sort_keys_sha256": fixture[
            "canonical_compact_sort_keys_sha256"
        ],
    }
    if before_summary != BEFORE:
        violations.append(
            "before fixture identity differs from the bound 17-item source"
        )
    if (
        len(before_todos) != 17
        or _sha(_compact(before_todos)) != BEFORE["canonical_compact_sort_keys_sha256"]
    ):
        violations.append(
            "before fixture todo list is not the exact 17-item canonical list"
        )

    after_measure, after_todos = _measure_script(root, "scripts/todo/dev.py")
    if after_measure["items"] != 9:
        violations.append("ordinary /dev must emit exactly nine macro phases")
    # Coverage metadata lives module-level, not inside the TodoWrite items: the
    # codex-native harness rejects any item key outside its whitelist and would
    # degrade to an empty step table (see scripts/todo/dev.py docstring).
    coverage_map = _load_module(
        root / "scripts/todo/dev.py", "dev_todo_coverage"
    ).PHASE_COVERS_OLD_STEPS
    if sorted(coverage_map) != list(range(1, 10)):
        violations.append("phase coverage metadata is not keyed by phases 1..9")
    coverage = [old for phase in sorted(coverage_map) for old in coverage_map[phase]]
    if sorted(coverage) != list(range(1, 18)) or len(coverage) != 17:
        violations.append("macro phases do not cover old steps 1..17 exactly once")
    roles = [
        item["subagent_call"].get("subagent_type")
        for item in after_todos
        if item.get("subagent_call")
    ]
    if roles != EXPECTED_ROLES:
        violations.append(f"subagent guard sequence drift: {roles!r}")

    before_validation = _validator_accounting(root, before_todos)
    after_validation = _validator_accounting(root, after_todos)
    if before_validation["accepted_call_count"] != 18:
        violations.append("17-item before list did not require exactly 18 calls")
    if after_validation["accepted_call_count"] != 10:
        violations.append("nine-phase list did not require exactly 10 calls")
    for label, result in (
        ("before", before_validation),
        ("after", after_validation),
    ):
        if result["valid_transition_errors"]:
            violations.append(f"{label} valid transition rejected by real validators")
        if not all(result["invalid_cases"].values()):
            violations.append(f"{label} generic invalid transition escaped")
    guards = after_validation["subagent_guards"]
    if len(guards) != 5 or not all(
        item["missing_call_rejected"] and item["recorded_call_accepted"]
        for item in guards
    ):
        violations.append("one or more of five real subagent guards is not preserved")

    controls: dict[str, Any] = {}
    for name, expected in CONTROLS.items():
        measured, _todos = _measure_script(root, expected["path"])
        controls[name] = measured
        if any(measured.get(key) != value for key, value in expected.items()):
            violations.append(f"{name} source/stdout/item/compact control drift")
        if measured["stderr_bytes"] != 0 or measured["exit_code"] != 0:
            violations.append(f"{name} execution is not clean")

    read_only = {}
    for relative, expected_sha in READ_ONLY.items():
        raw = (root / relative).read_bytes()
        actual = _sha(raw)
        read_only[relative] = actual
        if actual != expected_sha:
            violations.append(f"read-only generic/command control drift: {relative}")

    formulas = {
        "before": {
            "items": 17,
            "initial": 1,
            "combined_boundaries": 16,
            "final": 1,
            "fanout_multiplier": 1,
            "one_lane_total": 18,
            "ten_lane_total": 18,
        },
        "after": {
            "items": 9,
            "initial": 1,
            "combined_boundaries": 8,
            "final": 1,
            "fanout_multiplier": 1,
            "one_lane_total": 10,
            "ten_lane_total": 10,
        },
    }
    return {
        "validator": "dev-todo-accounting.v1",
        "status": "pass" if not violations else "fail",
        "violations": violations,
        "historical_nonclaims": [
            "no exact-eight sequence",
            "no per-lane Todo multiplier",
            "no subagent Todo calls",
        ],
        "formulas": formulas,
        "before": before_summary,
        "after": after_measure,
        "old_step_coverage": coverage,
        "old_step_coverage_once": sorted(coverage) == list(range(1, 18))
        and len(coverage) == 17,
        "subagent_guard_sequence": roles,
        "before_validator": before_validation,
        "after_validator": after_validation,
        "controls": controls,
        "read_only_sha256": read_only,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parent.parent
    )
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run(args.project_root)
    except Exception as exc:
        result = {
            "validator": "dev-todo-accounting.v1",
            "status": "fail",
            "violations": [f"accounting execution failed: {exc}"],
        }
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            indent=2 if args.pretty else None,
            separators=None if args.pretty else (",", ":"),
        )
    )
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
