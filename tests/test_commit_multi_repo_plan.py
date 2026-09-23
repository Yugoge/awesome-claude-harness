from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any

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


def _report(
    control: Path,
    task: str,
    modified: list[str],
    *,
    created: list[str] | None = None,
    owned_edits: dict[str, list[dict[str, str]]] | None = None,
    section_name: str = "dev",
    source: str | None = None,
) -> Path:
    """Write a dev/do-report fixture.

    ``owned_edits`` defaults to one ledger entry per ``modified`` path (the
    exact raw string, so it canonicalizes to the same identity as its
    files_modified entry) -- this keeps every pre-existing caller of this
    helper passing under the new ownership gate (task 20260922-215750)
    without per-test edits. Pass ``owned_edits={}`` explicitly to test the
    missing/empty-ledger boundary, or a custom dict to test a real gap.
    """
    created = created if created is not None else []
    if owned_edits is None:
        owned_edits = {path: [{"old": "placeholder-old", "new": "placeholder-new"}] for path in modified}
    filename = f"{section_name}-report-{task}.json" if section_name != "dev" else f"dev-report-{task}.json"
    path = control / "docs" / "dev" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "task_id": task,
        "request_id": task,
        section_name: {"files_modified": modified, "files_created": created},
    }
    if owned_edits:
        payload["owned_edits"] = owned_edits
    if source is not None:
        payload["source"] = source
    path.write_text(json.dumps(payload), encoding="utf-8")
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


# --------------------------------------------------------------------------
# Ownership gate (task 20260922-215750, backlog #110): files_modified must be
# backed by the report's owned_edits ledger for source=="dev" reports.
# --------------------------------------------------------------------------


def test_ac1_rejects_files_modified_path_missing_from_owned_edits_ledger(tmp_path: Path) -> None:
    control = _repo(tmp_path / "control")
    (control / "owned.txt").write_text("owned\n", encoding="utf-8")
    (control / "foreign.txt").write_text("foreign\n", encoding="utf-8")
    task = "task-ac1-missing-ledger-entry"
    report = _report(
        control,
        task,
        ["owned.txt", "foreign.txt"],
        owned_edits={"owned.txt": [{"old": "a", "new": "b"}]},
    )

    with pytest.raises(MODULE.PlanError, match="foreign.txt"):
        MODULE.build_plan(
            task_id=task,
            control_root_arg=str(control),
            supported_repo_args=[],
            report_arg=str(report),
        )


def test_ac2_passes_when_files_modified_fully_covered_by_owned_edits(tmp_path: Path) -> None:
    control = _repo(tmp_path / "control")
    (control / "owned.txt").write_text("owned\n", encoding="utf-8")
    (control / "other.txt").write_text("other\n", encoding="utf-8")
    task = "task-ac2-fully-covered"
    # _report()'s default owned_edits auto-populates one entry per `modified`
    # path -- exercises the common case with no explicit ledger override.
    report = _report(control, task, ["owned.txt", "other.txt"])

    plan = MODULE.build_plan(
        task_id=task,
        control_root_arg=str(control),
        supported_repo_args=[],
        report_arg=str(report),
    )

    assert plan["schema_version"] == 1
    assert plan["repositories"][0]["owned_paths"] == sorted(["owned.txt", "other.txt"])


def test_ac3a_rejects_when_owned_edits_missing_and_files_modified_nonempty(tmp_path: Path) -> None:
    control = _repo(tmp_path / "control")
    (control / "owned.txt").write_text("owned\n", encoding="utf-8")
    task = "task-ac3a-empty-ledger-nonempty-fm"
    report = _report(control, task, ["owned.txt"], owned_edits={})

    with pytest.raises(MODULE.PlanError, match="owned.txt"):
        MODULE.build_plan(
            task_id=task,
            control_root_arg=str(control),
            supported_repo_args=[],
            report_arg=str(report),
        )


def test_ac3b_passes_when_owned_edits_missing_and_files_modified_empty(tmp_path: Path) -> None:
    control = _repo(tmp_path / "control")
    task = "task-ac3b-empty-ledger-empty-fm"
    report = _report(control, task, [], owned_edits={})

    plan = MODULE.build_plan(
        task_id=task,
        control_root_arg=str(control),
        supported_repo_args=[],
        report_arg=str(report),
    )

    assert plan["repositories"][0]["owned_paths"] == []


def test_ac4a_files_created_only_path_exempt_from_ownership_ledger(tmp_path: Path) -> None:
    control = _repo(tmp_path / "control")
    (control / "owned.txt").write_text("owned\n", encoding="utf-8")
    (control / "new_file.txt").write_text("new\n", encoding="utf-8")
    task = "task-ac4a-created-only-exempt"
    report = _report(
        control,
        task,
        ["owned.txt"],
        created=["new_file.txt"],
        owned_edits={"owned.txt": [{"old": "a", "new": "b"}]},
    )

    plan = MODULE.build_plan(
        task_id=task,
        control_root_arg=str(control),
        supported_repo_args=[],
        report_arg=str(report),
    )

    assert plan["repositories"][0]["owned_paths"] == sorted(["owned.txt", "new_file.txt"])


def test_ac4b_dual_listed_path_not_exempt_from_ownership_ledger(tmp_path: Path) -> None:
    control = _repo(tmp_path / "control")
    (control / "dual.txt").write_text("dual\n", encoding="utf-8")
    task = "task-ac4b-dual-listed-not-exempt"
    report = _report(control, task, ["dual.txt"], created=["dual.txt"], owned_edits={})

    with pytest.raises(MODULE.PlanError, match="dual.txt"):
        MODULE.build_plan(
            task_id=task,
            control_root_arg=str(control),
            supported_repo_args=[],
            report_arg=str(report),
        )


def test_ac5_do_report_exempt_from_ownership_gate(tmp_path: Path) -> None:
    control = _repo(tmp_path / "control")
    (control / "foreign.txt").write_text("foreign\n", encoding="utf-8")
    task = "task-ac5-do-report-exempt"
    report = _report(
        control,
        task,
        ["foreign.txt"],
        owned_edits={},
        section_name="do",
        source="do",
    )

    plan = MODULE.build_plan(
        task_id=task,
        control_root_arg=str(control),
        supported_repo_args=[],
        report_arg=str(report),
    )

    assert plan["repositories"][0]["owned_paths"] == ["foreign.txt"]


def test_ac6_dev_lifecycle_call_site_passes_verify_ownership_false(tmp_path: Path) -> None:
    """scripts/dev-lifecycle.py's one build_plan() call site must pass
    verify_ownership=False -- confirmed here by reading the call site's
    source, plus a functional check that the same gap MODULE.build_plan()
    rejects by default is admitted when verify_ownership=False is passed
    explicitly (the parameter this ticket adds)."""
    dev_lifecycle_src = (
        Path(__file__).parents[1] / "scripts" / "dev-lifecycle.py"
    ).read_text(encoding="utf-8")
    assert "verify_ownership=False" in dev_lifecycle_src

    control = _repo(tmp_path / "control")
    (control / "gap.txt").write_text("gap\n", encoding="utf-8")
    task = "task-ac6-verify-ownership-false"
    report = _report(control, task, ["gap.txt"], owned_edits={})

    with pytest.raises(MODULE.PlanError, match="gap.txt"):
        MODULE.build_plan(
            task_id=task,
            control_root_arg=str(control),
            supported_repo_args=[],
            report_arg=str(report),
        )

    plan = MODULE.build_plan(
        task_id=task,
        control_root_arg=str(control),
        supported_repo_args=[],
        report_arg=str(report),
        verify_ownership=False,
    )
    assert plan["repositories"][0]["owned_paths"] == ["gap.txt"]


def test_ac7_canonicalization_path_form_parity_between_fm_and_ledger(tmp_path: Path) -> None:
    control = _repo(tmp_path / "control")
    (control / "owned.txt").write_text("owned\n", encoding="utf-8")
    task = "task-ac7-path-form-parity"
    report = _report(
        control,
        task,
        ["./owned.txt"],
        owned_edits={"owned.txt": [{"old": "a", "new": "b"}]},
    )

    plan = MODULE.build_plan(
        task_id=task,
        control_root_arg=str(control),
        supported_repo_args=[],
        report_arg=str(report),
    )

    assert plan["repositories"][0]["owned_paths"] == ["owned.txt"]
