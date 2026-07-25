from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "resolve-commit-repos.py"
SPEC = importlib.util.spec_from_file_location("resolve_commit_repos", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "tests@example.invalid")
    _git(path, "config", "user.name", "Tests")
    (path / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(path, "add", "seed.txt")
    _git(path, "commit", "-q", "-m", "seed")
    return path


def _report(control: Path, task: str, modified: list[str]) -> Path:
    path = control / "docs" / "dev" / f"dev-report-{task}.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "task_id": task,
                "request_id": task,
                "dev": {"files_modified": modified, "files_created": []},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_partitions_owned_paths_and_binds_each_repo_head(tmp_path: Path) -> None:
    control = _repo(tmp_path / "control")
    profile = _repo(tmp_path / "profile")
    (control / "owned.txt").write_text("control\n", encoding="utf-8")
    (profile / "native.txt").write_text("profile\n", encoding="utf-8")
    task = "20260720-211059-g2"
    report = _report(control, task, ["owned.txt", str(profile / "native.txt")])

    plan = MODULE.build_plan(
        task_id=task,
        control_root_arg=str(control),
        supported_repo_args=[str(control), str(profile)],
        report_arg=str(report),
    )

    assert plan["transaction_semantics"] == "ordered_non_atomic_with_partial_failure_reporting"
    assert plan["report_sha256"]
    assert [item["repo_root"] for item in plan["repositories"]] == [
        str(control.resolve()),
        str(profile.resolve()),
    ]
    assert plan["repositories"][0]["owned_paths"] == ["owned.txt"]
    assert plan["repositories"][1]["owned_paths"] == ["native.txt"]
    for target in plan["repositories"]:
        assert target["branch"] == "main"
        assert target["expected_head"] == _git(Path(target["repo_root"]), "rev-parse", "HEAD")


def test_rejects_owned_path_outside_explicit_supported_set(tmp_path: Path) -> None:
    control = _repo(tmp_path / "control")
    unadmitted = _repo(tmp_path / "unadmitted")
    task = "task-outside"
    report = _report(control, task, [str(unadmitted / "seed.txt")])

    with pytest.raises(MODULE.PlanError, match="outside the supported repository set"):
        MODULE.build_plan(
            task_id=task,
            control_root_arg=str(control),
            supported_repo_args=[str(control)],
            report_arg=str(report),
        )


def test_prefers_deepest_admitted_repo_for_nested_checkout(tmp_path: Path) -> None:
    control = _repo(tmp_path / "control")
    nested = _repo(control / "profile")
    task = "task-nested"
    report = _report(control, task, [str(nested / "seed.txt")])

    plan = MODULE.build_plan(
        task_id=task,
        control_root_arg=str(control),
        supported_repo_args=[str(nested)],
        report_arg=str(report),
    )

    assert plan["repository_count"] == 2
    assert plan["repositories"][0]["owned_paths"] == []
    assert plan["repositories"][1]["owned_paths"] == ["seed.txt"]


def test_rejects_unadmitted_nested_repo_instead_of_laundering_to_outer(tmp_path: Path) -> None:
    control = _repo(tmp_path / "control")
    nested = _repo(control / "nested")
    task = "task-unadmitted-nested"
    report = _report(control, task, [str(nested / "seed.txt")])

    with pytest.raises(MODULE.PlanError, match="outside the supported repository set"):
        MODULE.build_plan(
            task_id=task,
            control_root_arg=str(control),
            supported_repo_args=[],
            report_arg=str(report),
        )


def test_report_task_identity_mismatch_is_fail_closed(tmp_path: Path) -> None:
    control = _repo(tmp_path / "control")
    report = _report(control, "wrong-task", ["seed.txt"])

    with pytest.raises(MODULE.PlanError, match="task id does not match"):
        MODULE.build_plan(
            task_id="wanted-task",
            control_root_arg=str(control),
            supported_repo_args=[],
            report_arg=str(report),
        )

    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["task_id"] = "wanted-task"
    report.rename(report.with_name("dev-report-wanted-task.json"))
    renamed = report.with_name("dev-report-wanted-task.json")
    renamed.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MODULE.PlanError, match="task id does not match"):
        MODULE.build_plan(
            task_id="wanted-task",
            control_root_arg=str(control),
            supported_repo_args=[],
            report_arg=str(renamed),
        )


def test_explicit_report_outside_control_repo_is_rejected(tmp_path: Path) -> None:
    control = _repo(tmp_path / "control")
    outside = _repo(tmp_path / "outside")
    task = "outside-report"
    report = _report(outside, task, ["seed.txt"])

    with pytest.raises(MODULE.PlanError, match="report must resolve under"):
        MODULE.build_plan(
            task_id=task,
            control_root_arg=str(control),
            supported_repo_args=[str(outside)],
            report_arg=str(report),
        )


def test_command_and_analyst_contract_expose_partial_results() -> None:
    root = Path(__file__).parents[1]
    command = (root / "commands" / "commit.md").read_text(encoding="utf-8")
    analyst = (root / "agents" / "changelog-analyst.md").read_text(encoding="utf-8")
    for text in (command, analyst):
        assert "REPOSITORY_PLAN" in text
        assert "partially_committed" in text
        assert "repository_results" in text
        assert "cross-repository atomicity" in text
    assert "resolve-commit-repos.py" in command
    assert "one single-use commit grant per" in command
    assert "repository_plan_invalid" in analyst
    assert "report-digest" in analyst
    assert "not_attempted" in analyst


def test_real_task_shape_is_consumable_by_control_and_nested_repos(tmp_path: Path) -> None:
    control = _repo(tmp_path / "control")
    nested = _repo(tmp_path / "nested")
    (control / "hooks").mkdir()
    (control / "tests").mkdir()
    (nested / "hooks").mkdir()
    (nested / "tests").mkdir()
    task_paths = [
        "hooks/pretool-workflow-gate.py",
        "tests/test_workflow_gate.py",
        str(nested / "hooks" / "extra_hook.py"),
        str(nested / "tests" / "test_extra_hook.py"),
    ]
    for raw in task_paths:
        path = Path(raw) if Path(raw).is_absolute() else control / raw
        path.write_text("owned\n", encoding="utf-8")
    task = "20260720-211059-g2"
    report = _report(control, task, task_paths)

    plan = MODULE.build_plan(
        task_id=task,
        control_root_arg=str(control),
        supported_repo_args=[str(control), str(nested)],
        report_arg=str(report),
    )

    assert plan["repository_count"] == 2
    assert plan["repositories"][0]["owned_paths"] == [
        "hooks/pretool-workflow-gate.py",
        "tests/test_workflow_gate.py",
    ]
    assert plan["repositories"][1]["owned_paths"] == [
        "hooks/extra_hook.py",
        "tests/test_extra_hook.py",
    ]


def test_codex_profile_path_fails_closed(tmp_path: Path) -> None:
    """A report owning a Codex-profile path is fail-closed when only control+nested
    are admitted — the desired convergence behavior (Codex profile is no longer a
    supported repository)."""
    control = _repo(tmp_path / "control")
    nested = _repo(tmp_path / "nested")
    codex_profile = _repo(tmp_path / "codex-profile")
    task = "task-codex-fail-closed"
    report = _report(control, task, [str(codex_profile / "seed.txt")])

    with pytest.raises(MODULE.PlanError, match="outside the supported repository set"):
        MODULE.build_plan(
            task_id=task,
            control_root_arg=str(control),
            supported_repo_args=[str(control), str(nested)],
            report_arg=str(report),
        )
