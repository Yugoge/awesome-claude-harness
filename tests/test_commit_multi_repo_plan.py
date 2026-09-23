from __future__ import annotations

import base64
import hashlib
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
    baseline_dirty_snapshot: str | None = None,
) -> Path:
    """Write a dev/do-report fixture.

    ``owned_edits`` defaults to one ledger entry per ``modified`` path (the
    exact raw string, so it canonicalizes to the same identity as its
    files_modified entry) -- this keeps every pre-existing caller of this
    helper passing under the new ownership gate (task 20260922-215750)
    without per-test edits. Pass ``owned_edits={}`` explicitly to test the
    missing/empty-ledger boundary, or a custom dict to test a real gap.

    ``baseline_dirty_snapshot`` defaults to ``None``, which omits the field
    entirely from the payload (the "missing" boundary, task 20260923-024043
    AC-3) -- existing callers that never pass it keep testing the
    owned_edits-only path unaffected. Pass ``""`` explicitly to test the
    "present but empty" boundary, or a real ``git status --porcelain``
    string to test the baseline-dirty exemption.
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
    if baseline_dirty_snapshot is not None:
        payload["baseline_dirty_snapshot"] = baseline_dirty_snapshot
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


# --------------------------------------------------------------------------
# baseline_dirty_snapshot exemption (task 20260923-024043, backlog #110
# follow-up): a files_modified path absent from owned_edits is exempt from
# the ownership gate when it is a pre-existing dirty tracked file from
# another session, per agents/dev.md:521/533 -- but only then.
# --------------------------------------------------------------------------


# Real-artifact fixture bytes for the primary regression test below (base64,
# embedded verbatim -- NOT synthesized/paraphrased): docs/dev/ is globally
# gitignored (.gitignore:173), so this exact historical report would not
# exist in a fresh clone/checkout. Source: the untouched, never-hand-edited
# docs/dev/dev-report-dev-20260923-005810.json, 16601 bytes,
# sha256 da4277c1aba849ddbd38a581f6d687d916884d545dde23c4b5f4b8d891a446c5
# (task 20260923-024043 commit-gate correction: the original version of this
# test read that gitignored path directly and would deterministically fail
# in any checkout where it is absent).
_DEV_REPORT_DEV_20260923_005810_B64 = (
    "ewogICJyZXF1ZXN0X2lkIjogImRldi0yMDI2MDkyMy0wMDU4MTAiLAogICJ0YXNrX2lkIjogImRl"
    "di0yMDI2MDkyMy0wMDU4MTAiLAogICJ0aW1lc3RhbXAiOiAiMjAyNi0wOS0yM1QwMToyOTo1OVoi"
    "LAogICJyYW5rX2Fja25vd2xlZGdlZCI6ICJEaXNncmFjZWQiLAogICJyYW5nZV9hY2tub3dsZWRn"
    "ZWQiOiAiPDAiLAogICJyZWNlbnRfZXZlbnRzX2RpZ2VzdF9hY2tub3dsZWRnZWQiOiAiZmFlMTEx"
    "YTEiLAogICJzY29yZV9pbmplY3Rpb25fYWN0aW9uIjogIlJhbmsgRGlzZ3JhY2VkL3JhbmdlIDww"
    "IGRyb3ZlIGluZGVwZW5kZW50IHZlcmlmaWNhdGlvbiBvdmVyIHRydXN0OiByZS1yYW4gdGhlIGZ1"
    "bGwgdGFyZ2V0IHRlc3Qgc3VpdGUgdHdpY2UgKGJlZm9yZS9hZnRlcikgYW5kIGRpZmZlZCBzaGEy"
    "NTYgb2YgaG9va3MvbGliL2Jhc2hfd3JpdGVfdGFyZ2V0cy5weSBieXRlLWZvci1ieXRlIHJhdGhl"
    "ciB0aGFuIGFzc3VtaW5nIHRoZSBvbmUtZmlsZSBlZGl0IGxlZnQgaXQgdW50b3VjaGVkLCBhbmQg"
    "Y29uZmlybWVkIHZpYSBweXRlc3QuaW5pIHRoYXQgdGVzdHMvZ2VuZXJhdGVkLyBpcyBtYXJrZXIt"
    "Z2F0ZWQgb3V0IG9mIHRoZSBkZWZhdWx0IHJ1biBiZWZvcmUgbGVhdmluZyB0aGUgdGVzdC13cml0"
    "ZXIgc2tlbGV0b24gc2VudGluZWxzIHVudG91Y2hlZCwgaW5zdGVhZCBvZiBndWVzc2luZy4iLAog"
    "ICJkZXZfcmVwb3J0X3BhdGgiOiAiZG9jcy9kZXYvZGV2LXJlcG9ydC1kZXYtMjAyNjA5MjMtMDA1"
    "ODEwLmpzb24iLAogICJiYXNlbGluZV9oZWFkX3NoYSI6ICIwZjQ3NDljZWY5ZjRmZTQ4YzBlZDVm"
    "MzQ3MjAxZTQ4NGUxYTcyNmE0IiwKICAiYmFzZWxpbmVfZGlydHlfc25hcHNob3QiOiAiIE0gQ0xB"
    "VURFLm1kXG4gTSBhZ2VudHMvY2hhbmdlbG9nLWFuYWx5c3QubWRcbiBNIGFnZW50cy9kZXYubWRc"
    "biBNIGFnZW50cy9xYS5tZFxuIE0gY29tbWFuZHMvY2xvc2UubWRcbiBNIGNvbW1hbmRzL2NvbW1p"
    "dC5tZFxuIE0gY29tbWFuZHMvcmVzdGFydC5tZFxuIE0gZG9jcy9yZWZlcmVuY2UvSU5ERVgubWRc"
    "biBNIGRvY3MvcmVmZXJlbmNlL2hhcm5lc3MtaXNzdWVzLWJhY2tsb2cubWRcbiBNIGhvb2tzL0lO"
    "REVYLm1kXG4gTSBob29rcy9saWIvSU5ERVgubWRcbiBNIGhvb2tzL2xpYi9zdWJhZ2VudF9yZXN0"
    "YXJ0LnB5XG4gTSBob29rcy9wcmV0b29sLXdvcmtmbG93LWdhdGUucHlcbiBNIHNjcmlwdHMvcmVz"
    "dGFydC1zdWJhZ2VudHMucHlcbiBNIHNldHRpbmdzLmpzb25cbiBNIHRlc3RzL0lOREVYLm1kXG4g"
    "TSB0ZXN0cy9nZW5lcmF0ZWQvbWFuaWZlc3QuanNvblxuIE0gdGVzdHMvdGVzdF9yZXNvbHZlX2Rl"
    "dl9hcnRpZmFjdF9jaGFpbi5weVxuIE0gdGVzdHMvdGVzdF9yZXN0YXJ0X2NvbW1hbmQucHlcbiBN"
    "IHRlc3RzL3Rlc3Rfc3RhZ2Vfb3duZWRfaHVua3NfYm91bmRhcnkucHlcbj8/IHRlc3RzL19sYXRl"
    "X3JlcGFpcl9maXh0dXJlcy5weVxuPz8gdGVzdHMvdGVzdF9sYXRlX3JlcGFpcl9yb3V0ZS5weSIs"
    "CiAgIm93bmVkX2VkaXRzIjogewogICAgInRlc3RzL3Rlc3RfYmFzaF93cml0ZV90YXJnZXRzX3Zl"
    "cmJfbmFycm93aW5nLnB5IjogWwogICAgICB7CiAgICAgICAgIm9sZCI6ICJAcHl0ZXN0Lm1hcmsu"
    "cGFyYW1ldHJpemUoXCJyb2xlXCIsIFJPTEVTKVxuQHB5dGVzdC5tYXJrLnBhcmFtZXRyaXplKFwi"
    "Y29tbWFuZFwiLCBSRUFMX0NBU0VfQVJNKVxuZGVmIHRlc3RfdG9vbF9wb2xpY3lfc3RpbGxfZGV0"
    "ZWN0ZWRfY2FzZV9hcm1fdmVyYihyb2xlLCBjb21tYW5kKTpcbiAgICByYywgZXJyID0gX3J1bl9w"
    "b2xpY3kocm9sZSwgY29tbWFuZClcbiAgICBhc3NlcnQgKHJjLCBfcG9saWN5X3RhcmdldChlcnIp"
    "KSA9PSAoMiwgREVTVCksIFwicmVhbCBjb3B5IGluIGEgY2FzZSBhcm0gbm90IHJlZnVzZWQgZm9y"
    "ICVzOiAlclwiICUgKHJvbGUsIGNvbW1hbmQpXG5cblxuIyAtLS0tIGNvbnN1bWVyIDI6IHRoZSBv"
    "dmVybmlnaHQgZ3VhcmQsIHNpeCBkZWNpc2lvbiBmdW5jdGlvbnMgLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tIiwKICAgICAgICAibmV3IjogIkBweXRlc3QubWFyay5wYXJhbWV0"
    "cml6ZShcInJvbGVcIiwgUk9MRVMpXG5AcHl0ZXN0Lm1hcmsucGFyYW1ldHJpemUoXCJjb21tYW5k"
    "XCIsIFJFQUxfQ0FTRV9BUk0pXG5kZWYgdGVzdF90b29sX3BvbGljeV9zdGlsbF9kZXRlY3RlZF9j"
    "YXNlX2FybV92ZXJiKHJvbGUsIGNvbW1hbmQpOlxuICAgIHJjLCBlcnIgPSBfcnVuX3BvbGljeShy"
    "b2xlLCBjb21tYW5kKVxuICAgIGFzc2VydCAocmMsIF9wb2xpY3lfdGFyZ2V0KGVycikpID09ICgy"
    "LCBERVNUKSwgXCJyZWFsIGNvcHkgaW4gYSBjYXNlIGFybSBub3QgcmVmdXNlZCBmb3IgJXM6ICVy"
    "XCIgJSAocm9sZSwgY29tbWFuZClcblxuXG4jIC0tLS0gS05PV04gTE9TUyBwaW5zOiBiYWNrbG9n"
    "ICMxMDAgY2FzZS1hcm0gcGFyZW4gcmVzaWR1YWwgKGNvbnRyb2xsZXIgY29uZGl0aW9uIDIpIC0t"
    "LS0tLS0tLS0tLS0tXG4jIGhvb2tzL2xpYi9iYXNoX3dyaXRlX3RhcmdldHMucHkncyBzaGFyZWQg"
    "X3NlZ21lbnRfZW5kIChsaW5lIH43MDEtNzA2KSBjdXRzIGEgY29tbWFuZCBzZWdtZW50IGF0XG4j"
    "IGV2ZXJ5IGB8YCBhbmQgbmV3bGluZSwgaW5jbHVkaW5nIGluc2lkZSBhIGNhc2UgYXJtJ3Mgb3du"
    "IHBhdHRlcm4uIFRoYXQgY3V0IGxhbmRzIGJlZm9yZSB0aGUgd2Fsa2VyXG4jIHJlYWNoZXMgdGhl"
    "IHZlcmIgd29yZCB3aGVuZXZlciB0aGUgYXJtJ3MgcGF0dGVybiBpcyBwYXJlbnRoZXNpemVkIEFO"
    "RCBlaXRoZXIgY2FycmllcyBhIGB8YFxuIyBhbHRlcm5hdGl2ZSBvbiB0aGUgc2FtZSBsaW5lLCBv"
    "ciBzaXRzIG9uIHRoZSBsaW5lIGFmdGVyIGBjYXNlIFggaW5gLiBUaGUgdGhyZWUgY29tbWFuZHMg"
    "YmVsb3cgYWxsXG4jIGV4ZWN1dGUgYSByZWFsIGBjcGAvYG12YCB1bmRlciByZWFsIGJhc2ggKEJB"
    "IGluZGVwZW5kZW50bHkgY29uZmlybWVkIHdpdGggYSBQQVRILXNoaW1tZWQgJENQLFxuIyAyMDI2"
    "LTA5LTIzKSB5ZXQgYm90aCBsaWJyYXJ5IG91dHB1dHMgKGV4dHJhY3RfYmFzaF93cml0ZV9wYXRo"
    "cywgZXh0cmFjdF9iYXNoX3dyaXRlX3RhcmdldHNfd2l0aF9cbiMgbW9kZXMpIHJldHVybiBlbXB0"
    "eSBmb3IgYWxsIHRocmVlIHRvZGF5LiBBY2NlcHRlZCBhcyBhIGRlZmVycmVkIGZpeCAoY29udHJv"
    "bGxlciBydWxpbmcgMjAyNi0wOS0yMixcbiMgYmFja2xvZyAjMTAwKSBiZWNhdXNlIHJlYWNoYWJp"
    "bGl0eSBpcyAwLzE0NTA2NCBpbiB0aGlzIHByb2plY3QncyBvd24gcmVhbCBjb21tYW5kIGhpc3Rv"
    "cnkgKGFcbiMgNzQ1OTItY29tbWFuZCBzeW50aGV0aWMgZ3JpZCBmb3VuZCAzMDgvNzQ1OTIgbWlz"
    "c2VkIG9mIHRoaXMgZXhhY3QgY2xhc3MpIC0tIE5PVCBiZWNhdXNlIHRoZSBsb3NzIGlzXG4jIGJl"
    "bmlnbi4gVGhlc2UgdGhyZWUgdGVzdHMgcGluIHRoZSBDVVJSRU5UICh3cm9uZykgYmVoYXZpb3Ig"
    "dGhyb3VnaCB0aGUgdG9vbF9wb2xpY3kgY29uc3VtZXIgZW50cnlcbiMgcG9pbnQgc28gYSBmdXR1"
    "cmUgZml4IHRvIHRoZSBzaGFyZWQgc2VnbWVudC1jdXR0aW5nIG1lY2hhbmlzbSBpcyBmb3JjZWQg"
    "dG8gdHVybiB0aGVtIHJlZCBpbnN0ZWFkIG9mXG4jIHNpbGVudGx5IGxhbmRpbmcgdW5ub3RpY2Vk"
    "LlxuS05PV05fTE9TU19TSEFQRV8xX1NBTUVfTElORV9BTFRFUk5BVElPTiA9ICdjYXNlIHggaW4g"
    "KHl8eCkgXCIkQ1BcIiBjcC0wMSAnICsgREVTVCArICcgOzsgZXNhYydcbktOT1dOX0xPU1NfU0hB"
    "UEVfMl9ORVhUX0xJTkUgPSAnY2FzZSB4IGluXFxuKHgpIFwiJENQXCIgY3AtMDEgJyArIERFU1Qg"
    "KyAnXFxuOzsgZXNhYydcbiMgc3ViamVjdCBgYmAgZ2VudWluZWx5IG1hdGNoZXMgb25lIGFsdGVy"
    "bmF0aXZlIG9mIChhfGJ8YykgdW5kZXIgcmVhbCBiYXNoOyB0aGUgcWEtcmVwb3J0J3Mgb3duXG4j"
    "IGBjYXNlIHggaW4gKGF8YnxjKSAuLi5gIHRyYW5zY3JpcHRpb24gZG9lcyBOT1QgKHN1YmplY3Qg"
    "eCBtYXRjaGVzIG5vbmUgb2YgYS9iL2MpIGFuZCBtdXN0IG5vdCBiZVxuIyBjb3BpZWQgaGVyZSAt"
    "LSBCQSByZXByb2R1Y2VkIHRoaXMgbGl2ZSwgMjAyNi0wOS0yMy5cbktOT1dOX0xPU1NfU0hBUEVf"
    "M19NVUxUSV9BTFRFUk5BVElPTiA9ICdjYXNlIGIgaW4gKGF8YnxjKSBcIiRDUFwiIGNwLTAxICcg"
    "KyBERVNUICsgJyA7OyBlc2FjJ1xuIyBDT05UUk9MLCBub3QgYSBsb3NzOiBgKHgpYCB3aXRoIG5v"
    "IGB8YCBhbHRlcm5hdGl2ZSBvbiB0aGUgc2FtZSBsaW5lIGFzIGBjYXNlIC4uLiBpbmAgaXMgc3Rp"
    "bGxcbiMgY29ycmVjdGx5IGRldGVjdGVkIHRvZGF5ICh0aGlzIGV4YWN0IHJvdyBhbHJlYWR5IGxp"
    "dmVzIGluc2lkZSBDQVNFX0FSTV9ST1dTIGF0IG1vZHVsZSBzY29wZSwgbGluZVxuIyAxMDYgYWJv"
    "dmUsIHZpYSB0aGUgdW5kaWZmZXJlbnRpYXRlZCBSRUFMX0NBU0VfQVJNIHN3ZWVwKS4gQXNzZXJ0"
    "ZWQgYWdhaW4gaGVyZSBvbiBpdHMgb3duLCBkaXN0aW5jdGx5XG4jIGxhYmVsZWQsIHBlciBBQzQn"
    "cyByZXF1aXJlbWVudCBub3QgdG8gZm9sZCB0aGUgY29udHJvbCBhbm9ueW1vdXNseSBpbnRvIHRo"
    "YXQgbWFjaGluZXJ5LlxuQ09OVFJPTF9QQVJFTl9OT19BTFRFUk5BVElWRSA9ICdjYXNlIHggaW4g"
    "KHgpIFwiJENQXCIgY3AtMDEgJyArIERFU1QgKyAnIDs7IGVzYWMnXG5cblxuQHB5dGVzdC5tYXJr"
    "LnBhcmFtZXRyaXplKFwicm9sZVwiLCBST0xFUylcbmRlZiB0ZXN0X3Rvb2xfcG9saWN5X2tub3du"
    "X2xvc3NfYmFja2xvZ18xMDBfc2hhcGUxX3NhbWVfbGluZV9hbHRlcm5hdGlvbihyb2xlKTpcbiAg"
    "ICBcIlwiXCJLTk9XTiBMT1NTIChiYWNrbG9nICMxMDApLCBOT1QgZXhwZWN0ZWQgYmVoYXZpb3Iu"
    "IFJlYWwgYmFzaCBleGVjdXRlcyB0aGlzIGNvcHkgKEJBLWNvbmZpcm1lZFxuICAgIHdpdGggYSBQ"
    "QVRILXNoaW1tZWQgJENQKSwgYnV0IHRoZSBzaGFyZWQgc2VnbWVudC1jdXR0aW5nIG1lY2hhbmlz"
    "bSBkcm9wcyB0aGUgdmVyYiBiZWZvcmUgdGhlXG4gICAgd2Fsa2VyIHJlYWNoZXMgaXQuIFBpbnMg"
    "dGhlIENVUlJFTlQgKHdyb25nKSByYyA9PSAwIC8gbm8tcmVmdXNhbCBvdXRjb21lOiBvbmNlIHRo"
    "ZSBzZWdtZW50LWN1dHRpbmdcbiAgICBtZWNoYW5pc20gaXMgZml4ZWQsIHRvb2xfcG9saWN5IHdp"
    "bGwgcmVmdXNlIHRoaXMgY29tbWFuZCBhbmQgdGhpcyBhc3NlcnRpb24gdHVybnMgcmVkIC0tIHRo"
    "YXQgaXNcbiAgICB0aGUgaW50ZW5kZWQgc2lnbmFsIHRvIHVwZGF0ZSB0aGUgcGluLCBub3QgYSBi"
    "dWcgaW4gdGhlIHRlc3QuXCJcIlwiXG4gICAgcmMsIGVyciA9IF9ydW5fcG9saWN5KHJvbGUsIEtO"
    "T1dOX0xPU1NfU0hBUEVfMV9TQU1FX0xJTkVfQUxURVJOQVRJT04pXG4gICAgYXNzZXJ0IHJjID09"
    "IDAsIChcbiAgICAgICAgXCJLTk9XTiBMT1NTIHBpbiAoYmFja2xvZyAjMTAwKSBpcyBzdGFsZTog"
    "c2hhcGUgMSAoeXx4KSBpcyBub3cgcmVmdXNlZCAodGFyZ2V0ICVyKSAtLSBcIlxuICAgICAgICBc"
    "InRoZSBzZWdtZW50LWN1dHRpbmcgbWVjaGFuaXNtIGFwcGVhcnMgZml4ZWQ7IHVwZGF0ZS9yZW1v"
    "dmUgdGhpcyBwaW5cIiAlIF9wb2xpY3lfdGFyZ2V0KGVycikpXG5cblxuQHB5dGVzdC5tYXJrLnBh"
    "cmFtZXRyaXplKFwicm9sZVwiLCBST0xFUylcbmRlZiB0ZXN0X3Rvb2xfcG9saWN5X2tub3duX2xv"
    "c3NfYmFja2xvZ18xMDBfc2hhcGUyX25leHRfbGluZShyb2xlKTpcbiAgICBcIlwiXCJLTk9XTiBM"
    "T1NTIChiYWNrbG9nICMxMDApLCBOT1QgZXhwZWN0ZWQgYmVoYXZpb3IuIFNhbWUgbWVjaGFuaXNt"
    "IGFzIHNoYXBlIDEsIHRyaWdnZXJlZCBieSB0aGVcbiAgICBwYXJlbnRoZXNpemVkIHBhdHRlcm4g"
    "c2l0dGluZyBvbiB0aGUgbGluZSBhZnRlciBgY2FzZSBYIGluYCBpbnN0ZWFkIG9mIGEgYHxgIGFs"
    "dGVybmF0aXZlLiBSZWFsXG4gICAgYmFzaCBleGVjdXRlcyB0aGlzIGNvcHk7IHBpbnMgdGhlIENV"
    "UlJFTlQgKHdyb25nKSByYyA9PSAwIG91dGNvbWUgZm9yIHRoZSBzYW1lIGZhaWwtcmVkIHJlYXNv"
    "bi5cIlwiXCJcbiAgICByYywgZXJyID0gX3J1bl9wb2xpY3kocm9sZSwgS05PV05fTE9TU19TSEFQ"
    "RV8yX05FWFRfTElORSlcbiAgICBhc3NlcnQgcmMgPT0gMCwgKFxuICAgICAgICBcIktOT1dOIExP"
    "U1MgcGluIChiYWNrbG9nICMxMDApIGlzIHN0YWxlOiBzaGFwZSAyIChuZXh0LWxpbmUpIGlzIG5v"
    "dyByZWZ1c2VkICh0YXJnZXQgJXIpIC0tIFwiXG4gICAgICAgIFwidGhlIHNlZ21lbnQtY3V0dGlu"
    "ZyBtZWNoYW5pc20gYXBwZWFycyBmaXhlZDsgdXBkYXRlL3JlbW92ZSB0aGlzIHBpblwiICUgX3Bv"
    "bGljeV90YXJnZXQoZXJyKSlcblxuXG5AcHl0ZXN0Lm1hcmsucGFyYW1ldHJpemUoXCJyb2xlXCIs"
    "IFJPTEVTKVxuZGVmIHRlc3RfdG9vbF9wb2xpY3lfa25vd25fbG9zc19iYWNrbG9nXzEwMF9zaGFw"
    "ZTNfbXVsdGlfYWx0ZXJuYXRpb24ocm9sZSk6XG4gICAgXCJcIlwiS05PV04gTE9TUyAoYmFja2xv"
    "ZyAjMTAwKSwgTk9UIGV4cGVjdGVkIGJlaGF2aW9yLiBRQSdzIG93biBuZXdseS1mb3VuZCBnZW5l"
    "cmFsaXphdGlvbiBvZlxuICAgIHNoYXBlcyAxLTIgdG8gYSAzLXdheSBgKGF8YnxjKWAgYWx0ZXJu"
    "YXRpb24uIFN1YmplY3QgYGJgIGdlbnVpbmVseSBtYXRjaGVzIG9uZSBhbHRlcm5hdGl2ZSB1bmRl"
    "clxuICAgIHJlYWwgYmFzaCAodW5saWtlIHRoZSBxYS1yZXBvcnQncyBvd24gbm9uLW1hdGNoaW5n"
    "IGBjYXNlIHggaW4gKGF8YnxjKSAuLi5gIHByb3NlIHRyYW5zY3JpcHRpb24gLS1cbiAgICBCQSBj"
    "b3JyZWN0ZWQgdGhpcyBsaXZlLCAyMDI2LTA5LTIzKS4gUGlucyB0aGUgQ1VSUkVOVCAod3Jvbmcp"
    "IHJjID09IDAgb3V0Y29tZSBmb3IgdGhlIHNhbWVcbiAgICBmYWlsLXJlZCByZWFzb24gYXMgc2hh"
    "cGVzIDEtMi5cIlwiXCJcbiAgICByYywgZXJyID0gX3J1bl9wb2xpY3kocm9sZSwgS05PV05fTE9T"
    "U19TSEFQRV8zX01VTFRJX0FMVEVSTkFUSU9OKVxuICAgIGFzc2VydCByYyA9PSAwLCAoXG4gICAg"
    "ICAgIFwiS05PV04gTE9TUyBwaW4gKGJhY2tsb2cgIzEwMCkgaXMgc3RhbGU6IHNoYXBlIDMgKGF8"
    "YnxjKSBpcyBub3cgcmVmdXNlZCAodGFyZ2V0ICVyKSAtLSBcIlxuICAgICAgICBcInRoZSBzZWdt"
    "ZW50LWN1dHRpbmcgbWVjaGFuaXNtIGFwcGVhcnMgZml4ZWQ7IHVwZGF0ZS9yZW1vdmUgdGhpcyBw"
    "aW5cIiAlIF9wb2xpY3lfdGFyZ2V0KGVycikpXG5cblxuQHB5dGVzdC5tYXJrLnBhcmFtZXRyaXpl"
    "KFwicm9sZVwiLCBST0xFUylcbmRlZiB0ZXN0X3Rvb2xfcG9saWN5X2NvbnRyb2xfY2FzZV9hcm1f"
    "cGFyZW5fbm9fYWx0ZXJuYXRpdmVfc3RpbGxfZGV0ZWN0ZWQocm9sZSk6XG4gICAgXCJcIlwiQ09O"
    "VFJPTCwgbm90IGEgbG9zcyBwaW4uIGAoeClgIHdpdGggbm8gYHxgIGFsdGVybmF0aXZlLCBzYW1l"
    "IGxpbmUgYXMgYGNhc2UgLi4uIGluYCwgaXMgb3V0c2lkZVxuICAgIHRoZSBiYWNrbG9nICMxMDAg"
    "cmVzaWR1YWwgY2xhc3MgYW5kIHJlbWFpbnMgY29ycmVjdGx5IGRldGVjdGVkIHRvZGF5LiBEaXN0"
    "aW5jdCBmcm9tIHRoZSB0aHJlZVxuICAgIEtOT1dOIExPU1MgdGVzdHMgYWJvdmU6IHRoaXMgYXNz"
    "ZXJ0aW9uIGlzIGV4cGVjdGVkIHRvIHN0YXkgZ3JlZW4gYm90aCBiZWZvcmUgYW5kIGFmdGVyIGFu"
    "eSBmdXR1cmVcbiAgICBmaXggdG8gdGhlIHNoYXJlZCBzZWdtZW50LWN1dHRpbmcgbWVjaGFuaXNt"
    "IChBQzQpLlwiXCJcIlxuICAgIHJjLCBlcnIgPSBfcnVuX3BvbGljeShyb2xlLCBDT05UUk9MX1BB"
    "UkVOX05PX0FMVEVSTkFUSVZFKVxuICAgIGFzc2VydCAocmMsIF9wb2xpY3lfdGFyZ2V0KGVycikp"
    "ID09ICgyLCBERVNUKSwgKFxuICAgICAgICBcIkNPTlRST0wgcmVncmVzc2VkOiAoeCkgd2l0aCBu"
    "byBhbHRlcm5hdGl2ZSBtdXN0IHN0aWxsIGJlIGRldGVjdGVkIGFuZCByZWZ1c2VkOiAlclwiXG4g"
    "ICAgICAgICUgQ09OVFJPTF9QQVJFTl9OT19BTFRFUk5BVElWRSlcblxuXG4jIC0tLS0gY29uc3Vt"
    "ZXIgMjogdGhlIG92ZXJuaWdodCBndWFyZCwgc2l4IGRlY2lzaW9uIGZ1bmN0aW9ucyAtLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0iCiAgICAgIH0KICAgIF0KICB9LAogICJwcmVf"
    "ZWRpdF9zbmFwc2hvdHMiOiB7CiAgICAidGVzdHMvdGVzdF9iYXNoX3dyaXRlX3RhcmdldHNfdmVy"
    "Yl9uYXJyb3dpbmcucHkiOiAiNmQzMjBlNzAwNjdhZjcyM2YwYTAxMDkzYjgxMmZmNzRiYzBlY2E1"
    "MyIKICB9LAogICJkZXYiOiB7CiAgICAic3RhdHVzIjogImNvbXBsZXRlZCIsCiAgICAiZmlsZXNf"
    "bW9kaWZpZWQiOiBbCiAgICAgICJDTEFVREUubWQiLAogICAgICAiYWdlbnRzL2NoYW5nZWxvZy1h"
    "bmFseXN0Lm1kIiwKICAgICAgImFnZW50cy9kZXYubWQiLAogICAgICAiYWdlbnRzL3FhLm1kIiwK"
    "ICAgICAgImNvbW1hbmRzL2Nsb3NlLm1kIiwKICAgICAgImNvbW1hbmRzL2NvbW1pdC5tZCIsCiAg"
    "ICAgICJjb21tYW5kcy9yZXN0YXJ0Lm1kIiwKICAgICAgImRvY3MvcmVmZXJlbmNlL0lOREVYLm1k"
    "IiwKICAgICAgImRvY3MvcmVmZXJlbmNlL2hhcm5lc3MtaXNzdWVzLWJhY2tsb2cubWQiLAogICAg"
    "ICAiaG9va3MvSU5ERVgubWQiLAogICAgICAiaG9va3MvbGliL0lOREVYLm1kIiwKICAgICAgImhv"
    "b2tzL2xpYi9zdWJhZ2VudF9yZXN0YXJ0LnB5IiwKICAgICAgImhvb2tzL3ByZXRvb2wtd29ya2Zs"
    "b3ctZ2F0ZS5weSIsCiAgICAgICJzY3JpcHRzL3Jlc3RhcnQtc3ViYWdlbnRzLnB5IiwKICAgICAg"
    "InNldHRpbmdzLmpzb24iLAogICAgICAidGVzdHMvSU5ERVgubWQiLAogICAgICAidGVzdHMvZ2Vu"
    "ZXJhdGVkL21hbmlmZXN0Lmpzb24iLAogICAgICAidGVzdHMvdGVzdF9iYXNoX3dyaXRlX3Rhcmdl"
    "dHNfdmVyYl9uYXJyb3dpbmcucHkiLAogICAgICAidGVzdHMvdGVzdF9yZXNvbHZlX2Rldl9hcnRp"
    "ZmFjdF9jaGFpbi5weSIsCiAgICAgICJ0ZXN0cy90ZXN0X3Jlc3RhcnRfY29tbWFuZC5weSIsCiAg"
    "ICAgICJ0ZXN0cy90ZXN0X3N0YWdlX293bmVkX2h1bmtzX2JvdW5kYXJ5LnB5IgogICAgXSwKICAg"
    "ICJmaWxlc19tb2RpZmllZF9ub3RlIjogIlRoaXMgbGlzdCBpcyB0aGUgcmF3IGBnaXQgZGlmZiAt"
    "LW5hbWUtb25seSA8YmFzZWxpbmVfaGVhZF9zaGE+YCBvdXRwdXQgcGVyIHRoZSBtYW5kYXRvcnkg"
    "Z2l0LWRpZmYgZGVyaXZhdGlvbiBydWxlLiBPbmx5IHRlc3RzL3Rlc3RfYmFzaF93cml0ZV90YXJn"
    "ZXRzX3ZlcmJfbmFycm93aW5nLnB5IGlzIHRoaXMgY3ljbGUncyBvd24gZWRpdCAoc2VlIG93bmVk"
    "X2VkaXRzKTsgdGhlIG90aGVyIDIwIGVudHJpZXMgYXJlIHRoZSBwcmUtZXhpc3RpbmcgZGlydHkg"
    "dHJlZSBuYW1lZCBpbiB0aGUgZGlzcGF0Y2gncyBiYXNlbGluZV9kaXJ0eV9zbmFwc2hvdCBhbmQg"
    "d2VyZSBub3QgdG91Y2hlZCB0aGlzIGN5Y2xlIC0tIGRvIG5vdCBhdHRyaWJ1dGUgdGhlbSB0byB0"
    "aGlzIHRhc2suIiwKICAgICJmaWxlc19jcmVhdGVkIjogW10sCiAgICAib2JzZXJ2ZWRfcHJlZXhp"
    "c3RpbmciOiBbXSwKICAgICJ0YXNrc19jb21wbGV0ZWQiOiBbCiAgICAgIHsKICAgICAgICAiaWQi"
    "OiAxLAogICAgICAgICJkZXNjcmlwdGlvbiI6ICJBZGRlZCA0IG5ldyBweXRlc3QgdGVzdHMgKDMg"
    "S05PV04gTE9TUyBwaW5zIGZvciBiYWNrbG9nICMxMDAgY2FzZS1hcm0gcGFyZW4gc2hhcGVzICsg"
    "MSBkaXN0aW5jdGx5LWxhYmVsZWQgQ09OVFJPTCkgdG8gdGVzdHMvdGVzdF9iYXNoX3dyaXRlX3Rh"
    "cmdldHNfdmVyYl9uYXJyb3dpbmcucHksIGluc2VydGVkIGltbWVkaWF0ZWx5IGFmdGVyIHRlc3Rf"
    "dG9vbF9wb2xpY3lfc3RpbGxfZGV0ZWN0ZWRfY2FzZV9hcm1fdmVyYiAocHJldmlvdXNseSBlbmRp"
    "bmcgYXQgbGluZSAyMjApIGFuZCBiZWZvcmUgdGhlICcjIC0tLS0gY29uc3VtZXIgMicgYmFubmVy"
    "LiBQdXJlIGluc2VydGlvbiwgbm8gZXhpc3RpbmcgbGluZSBhbHRlcmVkLiIsCiAgICAgICAgInR5"
    "cGUiOiAidGVzdCIsCiAgICAgICAgImZpbGVzX21vZGlmaWVkIjogWyJ0ZXN0cy90ZXN0X2Jhc2hf"
    "d3JpdGVfdGFyZ2V0c192ZXJiX25hcnJvd2luZy5weSJdLAogICAgICAgICJjaGFuZ2VzIjogIkFk"
    "ZGVkIEtOT1dOX0xPU1NfU0hBUEVfMV9TQU1FX0xJTkVfQUxURVJOQVRJT04sIEtOT1dOX0xPU1Nf"
    "U0hBUEVfMl9ORVhUX0xJTkUsIEtOT1dOX0xPU1NfU0hBUEVfM19NVUxUSV9BTFRFUk5BVElPTiwg"
    "Q09OVFJPTF9QQVJFTl9OT19BTFRFUk5BVElWRSBjb21tYW5kIGNvbnN0YW50cyAoYWxsIGJ1aWx0"
    "IGZyb20gdGhlIGV4aXN0aW5nIERFU1QgY29uc3RhbnQsIG1hdGNoaW5nIGhvdXNlIHN0eWxlIG9m"
    "IG5vIGhhcmRjb2RlZCBkZXN0aW5hdGlvbiBzdHJpbmcpIHBsdXMgNCBuZXcgdGVzdCBmdW5jdGlv"
    "bnMsIGVhY2ggcGFyYW1ldHJpemVkIG92ZXIgUk9MRVMgKGJhL3FhKSBhbmQgZXhlcmNpc2VkIGV4"
    "Y2x1c2l2ZWx5IHRocm91Z2ggX3J1bl9wb2xpY3kgKHRoZSB0b29sX3BvbGljeSBjb25zdW1lciBl"
    "bnRyeSBwb2ludCksIHBlciB0aGUgY29ycmVjdGVkIEFDMS1BQzQgV0hFTiBjbGF1c2UuIiwKICAg"
    "ICAgICAicmF0aW9uYWxlIjogIkZ1bGZpbGxzIGNvbmRpdGlvbiAyIG9mIHRoZSAyMDI2LTA5LTIy"
    "IGNvbnRyb2xsZXIgcnVsaW5nIG9uIGJhY2tsb2cgIzEwMDogbWFrZXMgdGhlIHRocmVlIGNvbmZp"
    "cm1lZC1MT1NUIGNhc2UtYXJtIHBhcmVudGhlc2lzIHNoYXBlcyB2aXNpYmxlIGFzIGZhaWxpbmct"
    "cmVkLW9uLWZpeCByZWdyZXNzaW9uIHBpbnMsIHdpdGhvdXQgdG91Y2hpbmcgdGhlIGV4dHJhY3Rv"
    "ciAocm9vdF9jYXVzZV9jb21taXQgMjY3OTVjM2UncyByZXNpZHVhbCwgcm9vdCBjYXVzZSBhdCBo"
    "b29rcy9saWIvYmFzaF93cml0ZV90YXJnZXRzLnB5OjcwMS03MDYgX3NlZ21lbnRfZW5kLCBsZWZ0"
    "IHVudG91Y2hlZCkuIgogICAgICB9CiAgICBdLAogICAgInNjcmlwdHNfY3JlYXRlZCI6IFtdLAog"
    "ICAgImdpdF9yYXRpb25hbGUiOiB7CiAgICAgICJyb290X2NhdXNlX2NvbW1pdCI6ICIyNjc5NWMz"
    "ZSAtIGZpeChob29rcyk6IGZhbi1vdXQgbGFuZSBhL2UvYyBmaXhlcyBmb3IgYmFja2xvZyAjOTcg"
    "KGJhc2gtd3JpdGUtdGFyZ2V0IGV4dHJhY3RvciwgcmVmdXNhbCBub3RlLCBhdG9taWMgY3AtY2hl"
    "Y2tpbikgLSAyMDI2LTA5LTIyIiwKICAgICAgIndoeV9pc3N1ZV9vY2N1cnJlZCI6ICJUaGUgY29t"
    "bWl0J3MgbmFycm93aW5nIHNjaGVtZSBmb3IgYSBkaWZmZXJlbnQgcGhhbnRvbS1tYXRjaCBkZWZl"
    "Y3Qgc2hhcmVzIGl0cyB8IC8gbmV3bGluZSBzZWdtZW50LWN1dHRpbmcgbG9naWMgYWNyb3NzIGV2"
    "ZXJ5IHZlcmIgY2xhc3MgdGhlIGxpYnJhcnkgc3VwcG9ydHMsIGluY2x1ZGluZyBpbnNpZGUgY2Fz"
    "ZS1hcm0gcGF0dGVybnMsIHNvIGEgcGFyZW50aGVzaXplZCBwYXR0ZXJuIHdpdGggYSBzYW1lLWxp"
    "bmUgfCBhbHRlcm5hdGl2ZSBvciBvbiB0aGUgbGluZSBhZnRlciBgY2FzZSBYIGluYCBnZXRzIGl0"
    "cyBzZWdtZW50IGN1dCBiZWZvcmUgdGhlIHdhbGtlciByZWFjaGVzIHRoZSB2ZXJiIHdvcmQuIiwK"
    "ICAgICAgImhvd19maXhfYWRkcmVzc2VzX3Jvb3QiOiAiVGhpcyBjeWNsZSBkb2VzIG5vdCB0b3Vj"
    "aCB0aGUgcm9vdCBjYXVzZSAoZXhwbGljaXRseSBvdXQgb2Ygc2NvcGUsIHJlc2VydmVkIGZvciBj"
    "b250cm9sbGVyIGNvbmRpdGlvbiAzKS4gSXQgYWRkcyByZWdyZXNzaW9uIHRlc3RzIHRoYXQgcGlu"
    "IHRoZSBjdXJyZW50IHdyb25nIG91dHB1dCBhcyBLTk9XTiBMT1NTIHNvIGEgZnV0dXJlIGZpeCB0"
    "byB0aGUgc2hhcmVkIHNlZ21lbnQtY3V0dGluZyBtZWNoYW5pc20gaXMgZm9yY2VkIHRvIGZsaXAg"
    "dGhlc2UgdGVzdHMgcmVkIGluc3RlYWQgb2YgbGFuZGluZyBzaWxlbnRseSB1bm5vdGljZWQuIgog"
    "ICAgfSwKICAgICJkaWZmX3N0YXRzIjogewogICAgICAiZmlsZXNfY2hhbmdlZCI6IDEsCiAgICAg"
    "ICJsaW5lc19hZGRlZCI6IDc1LAogICAgICAibGluZXNfcmVtb3ZlZCI6IDAsCiAgICAgICJuZXdf"
    "c3ltYm9sc19pbnRyb2R1Y2VkIjogWwogICAgICAgICJLTk9XTl9MT1NTX1NIQVBFXzFfU0FNRV9M"
    "SU5FX0FMVEVSTkFUSU9OIiwKICAgICAgICAiS05PV05fTE9TU19TSEFQRV8yX05FWFRfTElORSIs"
    "CiAgICAgICAgIktOT1dOX0xPU1NfU0hBUEVfM19NVUxUSV9BTFRFUk5BVElPTiIsCiAgICAgICAg"
    "IkNPTlRST0xfUEFSRU5fTk9fQUxURVJOQVRJVkUiLAogICAgICAgICJ0ZXN0X3Rvb2xfcG9saWN5"
    "X2tub3duX2xvc3NfYmFja2xvZ18xMDBfc2hhcGUxX3NhbWVfbGluZV9hbHRlcm5hdGlvbiIsCiAg"
    "ICAgICAgInRlc3RfdG9vbF9wb2xpY3lfa25vd25fbG9zc19iYWNrbG9nXzEwMF9zaGFwZTJfbmV4"
    "dF9saW5lIiwKICAgICAgICAidGVzdF90b29sX3BvbGljeV9rbm93bl9sb3NzX2JhY2tsb2dfMTAw"
    "X3NoYXBlM19tdWx0aV9hbHRlcm5hdGlvbiIsCiAgICAgICAgInRlc3RfdG9vbF9wb2xpY3lfY29u"
    "dHJvbF9jYXNlX2FybV9wYXJlbl9ub19hbHRlcm5hdGl2ZV9zdGlsbF9kZXRlY3RlZCIKICAgICAg"
    "XSwKICAgICAgIm1pbmltdW1fcG9zc2libGVfbGluZXNfZXN0aW1hdGUiOiA3NSwKICAgICAgImp1"
    "c3RpZmljYXRpb25fZm9yX292ZXJhZ2UiOiAiQkEncyBkZXZlbG9wbWVudF9hcHByb2FjaCBleHBs"
    "aWNpdGx5IG1hbmRhdGVzIDQgZGlzdGluY3QsIHByb21pbmVudGx5LWxhYmVsZWQgdGVzdCBmdW5j"
    "dGlvbnMgKE0xLU00L0FDMS1BQzQpIHBsdXMgYSBiYWNrbG9nICMxMDAvcmVhY2hhYmlsaXR5LWRh"
    "dGEgYnJlYWRjcnVtYiBjb21tZW50IChTMS9TMiwgTTgpIGFuZCBhIHN1YmplY3QtY29ycmVjdGlv"
    "biBub3RlIChBQzMpLiBGb3VyIHNlcGFyYXRlIHRlc3QgZnVuY3Rpb25zIHdpdGggcmVxdWlyZWQg"
    "ZG9jc3RyaW5nIGxhYmVsaW5nIChLTk9XTiBMT1NTIHZzIENPTlRST0wgbXVzdCBub3QgYmUgZm9s"
    "ZGVkIHRvZ2V0aGVyIHBlciB0aGUgcmlzayBzZWN0aW9uKSBpcyB0aGUgc3RydWN0dXJhbCBtaW5p"
    "bXVtIGZvciA0IGluZGVwZW5kZW50bHktZ3JhZGFibGUgQUNzOyB0aGVyZSBpcyBubyBzbWFsbGVy"
    "IGRpZmYgdGhhdCBzYXRpc2ZpZXMgQUMxLUFDNCdzIGluZGl2aWR1YWwtbGFiZWxpbmcgcmVxdWly"
    "ZW1lbnQuIE5vIHJlZmFjdG9yLCByZW5hbWUsIG9yIGNvZGUgb3V0c2lkZSB0aGUgbWFuZGF0ZWQg"
    "YWRkaXRpb25zIGlzIGluY2x1ZGVkLiIKICAgIH0sCiAgICAiZml4X2xheWVyIjogIkwzIiwKICAg"
    "ICJzY29wZV9yZXZpZXdfcmVxdWVzdGVkIjogZmFsc2UsCiAgICAicWFfcmVhZHkiOiB0cnVlLAog"
    "ICAgInFhX25vdGVzIjogIlZlcmlmaWNhdGlvbiBwZXJmb3JtZWQ6ICgxKSBzaGEyNTZzdW0gaG9v"
    "a3MvbGliL2Jhc2hfd3JpdGVfdGFyZ2V0cy5weSBiZWZvcmUgYW5kIGFmdGVyID09IGQyYjU2YjUw"
    "NWVkOThjYWEyOTRkNWYwNjQ4OWFhNDlmZDc3NWVhYThlZGEwNzRhZGM0YTZjN2NjZjVhNTUxNWYg"
    "KHVuY2hhbmdlZCkuICgyKSBgcHl0ZXN0IHRlc3RzL3Rlc3RfYmFzaF93cml0ZV90YXJnZXRzX3Zl"
    "cmJfbmFycm93aW5nLnB5IC1xYCA9PiAyOTAgcGFzc2VkICgyODIgcHJlLWV4aXN0aW5nICsgOCBu"
    "ZXc6IDQgdGVzdHMgeCAyIHJvbGVzKSwgbm8gZmFpbHVyZXMsIG5vIHNraXBzLiAoMykgYHB5dGVz"
    "dCAuLi4gLWsgJ2tub3duX2xvc3Mgb3IgY29udHJvbF9jYXNlX2FybV9wYXJlbicgLXZgID0+IDgg"
    "cGFzc2VkLCAyODIgZGVzZWxlY3RlZCwgY29uZmlybWluZyB0aGUgbmV3IHRlc3RzIGlzb2xhdGUg"
    "Y2xlYW5seS4gKDQpIGBnaXQgZGlmZiAtLXN0YXQgLS0gdGVzdHMvdGVzdF9iYXNoX3dyaXRlX3Rh"
    "cmdldHNfdmVyYl9uYXJyb3dpbmcucHlgID0+IDEgZmlsZSBjaGFuZ2VkLCA3NSBpbnNlcnRpb25z"
    "KCspLCAwIGRlbGV0aW9ucygtKSAtLSBwdXJlIGFkZGl0aXZlIGVkaXQsIG5vIGV4aXN0aW5nIGxp"
    "bmUgdG91Y2hlZC4gKDUpIGBweXRob24zIC1tIHB5X2NvbXBpbGVgIG9uIHRoZSBmaWxlIHN1Y2Nl"
    "ZWRzLiBGYWlsLXJlZCBtZWNoYW5pc20gY2hvc2VuOiBwbGFpbiBhc3NlcnQgb2YgQ1VSUkVOVCAo"
    "d3JvbmcpIHJjPT0wIGZvciBhbGwgdGhyZWUgS05PV04gTE9TUyB0ZXN0cyAoTTcgbWVjaGFuaXNt"
    "IGkpIC0tIGRldGVybWluaXN0aWMgUHl0aG9uIHNlbWFudGljcyBndWFyYW50ZWUgQXNzZXJ0aW9u"
    "RXJyb3Igb25jZSB0aGUgZXh0cmFjdG9yIHN0YXJ0cyByZXR1cm5pbmcgcmM9PTIgZm9yIHRoZXNl"
    "IGNvbW1hbmRzLCBzbyBubyBmdXJ0aGVyIHNhbmRib3hlZCBwcm9vZiB3YXMgcGVyZm9ybWVkIGJ5"
    "IGRldiAoQkEncyB2YWxpZGF0aW9uX2FwcHJvYWNoIGFzc2lnbnMgdGhhdCBjb25maXJtYXRpb24g"
    "c3RlcCB0byBRQSkuIFFBIG1heSBpbmRlcGVuZGVudGx5IHZlcmlmeSBmYWlsLXJlZCBieSBwb2lu"
    "dGluZyBIQVJORVNTX1JPT1RfVU5ERVJfVEVTVCBhdCBhIHRocm93YXdheSBjb3B5IG9mIGhvb2tz"
    "LyB3aXRoIGEgbW9ua2V5cGF0Y2hlZCBiYXNoX3dyaXRlX3RhcmdldHMucHksIHBlciB0aGUgZmls"
    "ZSdzIG93biBlbnYtdmFyIG92ZXJyaWRlIHN1cHBvcnQgKGxpbmUgNDApLiIsCiAgICAicGVybWlz"
    "c2lvbnNfdG9fYWRkIjogW10KICB9LAogICJ0ZXN0X3dyaXRlcl9za2VsZXRvbnNfbm90ZSI6ICJ0"
    "ZXN0cy9nZW5lcmF0ZWQvZGV2LTIwMjYwOTIzLTAwNTgxMC8gY29udGFpbnMgNiB0ZXN0LXdyaXRl"
    "ci1nZW5lcmF0ZWQgc2tlbGV0b24gZmlsZXMgKHRlc3RfQUMxLi5BQzYpLCBlYWNoIHdpdGggYSBs"
    "aXZlIHB5dGVzdC5mYWlsKCdURVNUX0lOQ09NUExFVEU6IC4uLicpIHNlbnRpbmVsIGFuZCBtYW5p"
    "ZmVzdCBzdGF0dXMgJ2RlZmVycmVkX2ludmFsaWRfc2NoZW1hJy4gUGVyIHRoZSBkaXNwYXRjaCdz"
    "IGV4cGxpY2l0LCByZXBlYXRlZCBoYXJkLWZsb29yIGNvbnN0cmFpbnQgKCdUaGUgT05MWSBmaWxl"
    "IHlvdSBtYXkgbW9kaWZ5IGlzIHRlc3RzL3Rlc3RfYmFzaF93cml0ZV90YXJnZXRzX3ZlcmJfbmFy"
    "cm93aW5nLnB5JyAtLSBzdGF0ZWQgaW5kZXBlbmRlbnRseSBpbiB0aGUgQkEgdGlja2V0LCB0aGUg"
    "dXNlcidzIG9yaWdpbmFsIENoaW5lc2UgcmVxdWlyZW1lbnQsIGFuZCB0aGUgZGlzcGF0Y2ggcHJv"
    "bXB0KSwgdGhlc2Ugc2tlbGV0b24gZmlsZXMgd2VyZSBOT1QgZWRpdGVkIG9yIHJlcGxhY2VkLiBD"
    "b25maXJtZWQgdGhpcyBpcyBzYWZlIGZvciB0aGUgZGVmYXVsdCB0ZXN0IHJ1bjogcHl0ZXN0Lmlu"
    "aSBnYXRlcyB0ZXN0cy9nZW5lcmF0ZWQvIGJlaGluZCBhbiBvcHQtaW4gJ2dlbmVyYXRlZCcgbWFy"
    "a2VyICgndGhlIGRlZmF1bHQgcnVuIG5ldmVyIGRlc2NlbmRzIGludG8gdGVzdHMvZ2VuZXJhdGVk"
    "JyksIHNvIHRoZSB1bnRvdWNoZWQgVEVTVF9JTkNPTVBMRVRFIHNlbnRpbmVscyBkbyBub3QgYWZm"
    "ZWN0IGBweXRlc3RgIC8gYHB5dGVzdCB0ZXN0cy9gIGFuZCBkaWQgbm90IGFwcGVhciBpbiB0aGUg"
    "MjkwLXBhc3NlZCBydW4gYWJvdmUuIEZsYWdnaW5nIGZvciBvcmNoZXN0cmF0b3IvUUEgYXdhcmVu"
    "ZXNzIHJhdGhlciB0aGFuIHNpbGVudGx5IHJlc29sdmluZyB0aGUgdGVuc2lvbiBiZXR3ZWVuIHRo"
    "ZSBnZW5lcmljIHRlc3Qtd3JpdGVyLXNrZWxldG9uLXJlcGxhY2VtZW50IGluc3RydWN0aW9uIGFu"
    "ZCB0aGlzIGN5Y2xlJ3MgZXhwbGljaXQgb25lLWZpbGUgY29uc3RyYWludC4iLAogICJibG9ja2lu"
    "Z19pc3N1ZXMiOiBbXSwKICAicmVjb21tZW5kYXRpb25zIjogWwogICAgIkEgZnV0dXJlIGN5Y2xl"
    "IGFkZHJlc3NpbmcgY29udHJvbGxlciBjb25kaXRpb24gMyAodGhlIHJlYWwgZml4IHRvIHRoZSBz"
    "aGFyZWQgX3NlZ21lbnRfZW5kIC8gc2VnbWVudC1jdXR0aW5nIG1lY2hhbmlzbSwgaG9va3MvbGli"
    "L2Jhc2hfd3JpdGVfdGFyZ2V0cy5weTo3MDEtNzA2KSB3aWxsIG5lZWQgdG8gdXBkYXRlIG9yIHJl"
    "bW92ZSB0aGUgdGhyZWUgS05PV04gTE9TUyBwaW5zIGFkZGVkIHRoaXMgY3ljbGUgb25jZSB0aGV5"
    "IGZsaXAgcmVkIC0tIHRoYXQgaXMgdGhlIGludGVuZGVkIHNpZ25hbCwgbm90IGEgYnVnLiIsCiAg"
    "ICAiVGhlIDYgdGVzdC13cml0ZXIgc2tlbGV0b24gZmlsZXMgdW5kZXIgdGVzdHMvZ2VuZXJhdGVk"
    "L2Rldi0yMDI2MDkyMy0wMDU4MTAvIHJlbWFpbiBpbiB0aGVpciBnZW5lcmF0ZWQgVEVTVF9JTkNP"
    "TVBMRVRFIHN0YXRlOyBpZiB0aGlzIHByb2plY3QncyB3b3JrZmxvdyBleHBlY3RzIHRob3NlIHRv"
    "IGJlIHJlY29uY2lsZWQgb3IgYXJjaGl2ZWQgb25jZSB0aGUgY29ycmVzcG9uZGluZyBBQ3MgYXJl"
    "IGZ1bGZpbGxlZCBieSBoYW5kLXdyaXR0ZW4gdGVzdHMgZWxzZXdoZXJlIChhcyB0aGV5IHdlcmUg"
    "aGVyZSwgaW4gdGhlIHRhcmdldCBmaWxlKSwgYSBmb2xsb3ctdXAgaG91c2VrZWVwaW5nIHN0ZXAg"
    "b3V0c2lkZSB0aGlzIGN5Y2xlJ3Mgb25lLWZpbGUgY29uc3RyYWludCBtYXkgYmUgd2FycmFudGVk"
    "LiIKICBdLAogICJzZWxmX3ZlcmlmaWNhdGlvbiI6IHsKICAgICJidWlsZCI6ICJwYXNzIiwKICAg"
    "ICJzbW9rZV9jaGVjayI6ICJwYXNzIiwKICAgICJub3RlcyI6ICJzaGEyNTYgb2YgaG9va3MvbGli"
    "L2Jhc2hfd3JpdGVfdGFyZ2V0cy5weSB1bmNoYW5nZWQ7IGZ1bGwgdGFyZ2V0IHRlc3QgZmlsZSBy"
    "dW46IDI5MCBwYXNzZWQgKDI4MiBwcmUtZXhpc3RpbmcgKyA4IG5ldyksIDAgZmFpbGVkLCAwIHNr"
    "aXBwZWQ7IHB5X2NvbXBpbGUgY2xlYW47IGdpdCBkaWZmIHNob3dzIGV4YWN0bHkgMSBmaWxlIGNo"
    "YW5nZWQsIDc1IGluc2VydGlvbnMsIDAgZGVsZXRpb25zLiIKICB9LAogICJjb2RleF9jb25zdWx0"
    "IjogewogICAgImludm9rZWQiOiBmYWxzZSwKICAgICJzdGF0dXMiOiAibm90X3JlcXVlc3RlZCIs"
    "CiAgICAiZmVlZGJhY2tfc3VtbWFyeSI6IG51bGwsCiAgICAiZmVlZGJhY2tfaW5jb3Jwb3JhdGVk"
    "IjogbnVsbAogIH0KfQo="
)
_DEV_REPORT_DEV_20260923_005810_SHA256 = (
    "da4277c1aba849ddbd38a581f6d687d916884d545dde23c4b5f4b8d891a446c5"
)


def test_dev_20260923_005810_real_artifact_baseline_dirty_exempts_20_of_21_paths(
    tmp_path: Path,
) -> None:
    """Primary real-artifact regression fixture (never hand-edited, per the
    controller's explicit instruction). Pre-fix, build_plan() rejected 20 of
    this report's 21 files_modified paths: none of them are in owned_edits
    (only tests/test_bash_write_targets_verb_narrowing.py is), because they
    are this tree's pre-existing dirty tracked files from other sessions --
    named verbatim in the report's own baseline_dirty_snapshot field. Live
    BLOCKED/exit-2 reproduced this cycle (ticket Evidence section); must
    succeed post-fix (AC-1).

    Reads the report's exact verbatim bytes from the embedded base64
    constant above (task 20260923-024043 commit-gate correction) instead of
    docs/dev/dev-report-dev-20260923-005810.json directly: that path is
    globally gitignored (.gitignore:173) and would not exist in a fresh
    clone/checkout, which made the original direct-read version of this test
    deterministically fail there. The embedded bytes are written to a
    throwaway repo built by _repo() so build_plan() has a real git
    root/branch/HEAD to resolve against; none of the report's own
    files_modified paths need to exist on disk -- build_plan() only requires
    an EXISTING ANCESTOR directory to canonicalize each one, which the
    throwaway repo's own root always satisfies."""
    payload_bytes = base64.b64decode(_DEV_REPORT_DEV_20260923_005810_B64)
    assert hashlib.sha256(payload_bytes).hexdigest() == _DEV_REPORT_DEV_20260923_005810_SHA256

    control = _repo(tmp_path / "control")
    report = control / "docs" / "dev" / "dev-report-dev-20260923-005810.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_bytes(payload_bytes)

    plan = MODULE.build_plan(
        task_id="dev-20260923-005810",
        control_root_arg=str(control),
        supported_repo_args=[],
        report_arg=str(report),
    )

    assert plan["schema_version"] == 1
    owned = set(plan["repositories"][0]["owned_paths"])
    assert "tests/test_bash_write_targets_verb_narrowing.py" in owned
    assert "CLAUDE.md" in owned
    assert len(owned) == 21


def test_ac1_baseline_dirty_snapshot_exempts_files_modified_path_missing_from_ledger(
    tmp_path: Path,
) -> None:
    control = _repo(tmp_path / "control")
    (control / "owned.txt").write_text("owned\n", encoding="utf-8")
    (control / "baseline_dirty.txt").write_text("preexisting\n", encoding="utf-8")
    task = "task-ac1-baseline-dirty-exempt"
    report = _report(
        control,
        task,
        ["owned.txt", "baseline_dirty.txt"],
        owned_edits={"owned.txt": [{"old": "a", "new": "b"}]},
        baseline_dirty_snapshot=" M baseline_dirty.txt\n",
    )

    plan = MODULE.build_plan(
        task_id=task,
        control_root_arg=str(control),
        supported_repo_args=[],
        report_arg=str(report),
    )

    assert plan["repositories"][0]["owned_paths"] == sorted(["owned.txt", "baseline_dirty.txt"])


def test_ac2_post_baseline_foreign_path_still_rejected(tmp_path: Path) -> None:
    """Existential test: the baseline-dirty exemption must NOT weaken
    rejection of a path written by another seat AFTER the baseline snapshot
    was captured -- i.e. absent from BOTH owned_edits and
    baseline_dirty_snapshot. This is the gate's core protection."""
    control = _repo(tmp_path / "control")
    (control / "owned.txt").write_text("owned\n", encoding="utf-8")
    (control / "post_baseline_foreign.txt").write_text("foreign\n", encoding="utf-8")
    task = "task-ac2-post-baseline-foreign"
    report = _report(
        control,
        task,
        ["owned.txt", "post_baseline_foreign.txt"],
        owned_edits={"owned.txt": [{"old": "a", "new": "b"}]},
        baseline_dirty_snapshot=" M owned.txt\n",
    )

    with pytest.raises(MODULE.PlanError, match="post_baseline_foreign.txt"):
        MODULE.build_plan(
            task_id=task,
            control_root_arg=str(control),
            supported_repo_args=[],
            report_arg=str(report),
        )


def test_ac3a_missing_baseline_dirty_snapshot_degrades_to_strict(tmp_path: Path) -> None:
    control = _repo(tmp_path / "control")
    (control / "owned.txt").write_text("owned\n", encoding="utf-8")
    task = "task-ac3a-missing-baseline-dirty"
    report = _report(control, task, ["owned.txt"], owned_edits={})
    assert "baseline_dirty_snapshot" not in json.loads(report.read_text(encoding="utf-8"))

    with pytest.raises(MODULE.PlanError, match="owned.txt"):
        MODULE.build_plan(
            task_id=task,
            control_root_arg=str(control),
            supported_repo_args=[],
            report_arg=str(report),
        )


def test_ac3b_empty_string_baseline_dirty_snapshot_degrades_to_strict(tmp_path: Path) -> None:
    control = _repo(tmp_path / "control")
    (control / "owned.txt").write_text("owned\n", encoding="utf-8")
    task = "task-ac3b-empty-baseline-dirty"
    report = _report(control, task, ["owned.txt"], owned_edits={}, baseline_dirty_snapshot="")

    with pytest.raises(MODULE.PlanError, match="owned.txt"):
        MODULE.build_plan(
            task_id=task,
            control_root_arg=str(control),
            supported_repo_args=[],
            report_arg=str(report),
        )


def test_ac5_rename_line_in_baseline_dirty_exempts_both_endpoints(tmp_path: Path) -> None:
    control = _repo(tmp_path / "control")
    (control / "old.txt").write_text("old\n", encoding="utf-8")
    (control / "new.txt").write_text("new\n", encoding="utf-8")
    task = "task-ac5-rename-both-endpoints"
    report = _report(
        control,
        task,
        ["old.txt", "new.txt"],
        owned_edits={},
        baseline_dirty_snapshot="R  old.txt -> new.txt\n",
    )

    plan = MODULE.build_plan(
        task_id=task,
        control_root_arg=str(control),
        supported_repo_args=[],
        report_arg=str(report),
    )

    assert plan["repositories"][0]["owned_paths"] == sorted(["old.txt", "new.txt"])


def test_ac6_baseline_dirty_parser_handles_space_untracked_and_quoted_paths() -> None:
    """Porcelain edge cases (AC-6). Quoting/escaping behavior is NOT taken
    from documentation alone -- empirically confirmed this session via a
    real ``git status --porcelain`` subprocess fixture (git 2.54.0): a path
    containing nothing but a plain space is already C-style quoted by git
    (the fixed "XY " prefix already uses a single space as its own parse
    delimiter, so an embedded space would otherwise be ambiguous); a literal
    backslash, an embedded double quote, and non-ASCII bytes are each
    C-escaped (octal per byte for non-ASCII), never left as raw unescaped
    bytes. The parser must also accept the unquoted form (this AC's own
    literal ``' M with space.txt'`` check text), since not every consumer
    of this field is guaranteed to have core.quotePath enabled."""
    assert MODULE._parse_porcelain_snapshot_paths(" M with space.txt\n") == ["with space.txt"]
    assert MODULE._parse_porcelain_snapshot_paths("?? new_file.txt\n") == ["new_file.txt"]
    assert MODULE._parse_porcelain_snapshot_paths('?? "with space.txt"\n') == ["with space.txt"]
    assert MODULE._parse_porcelain_snapshot_paths('?? "quo\\"te.txt"\n') == ['quo"te.txt']
    assert MODULE._parse_porcelain_snapshot_paths('?? "back\\\\slash.txt"\n') == ["back\\slash.txt"]
    assert MODULE._parse_porcelain_snapshot_paths('?? "unicode_\\303\\274.txt"\n') == [
        "unicode_ü.txt"
    ]


def test_ac6b_baseline_dirty_snapshot_with_quoted_path_exempts_real_file(tmp_path: Path) -> None:
    control = _repo(tmp_path / "control")
    (control / "owned.txt").write_text("owned\n", encoding="utf-8")
    (control / "with space.txt").write_text("space\n", encoding="utf-8")
    task = "task-ac6b-quoted-baseline-dirty"
    report = _report(
        control,
        task,
        ["owned.txt", "with space.txt"],
        owned_edits={"owned.txt": [{"old": "a", "new": "b"}]},
        baseline_dirty_snapshot=' M "with space.txt"\n',
    )

    plan = MODULE.build_plan(
        task_id=task,
        control_root_arg=str(control),
        supported_repo_args=[],
        report_arg=str(report),
    )

    assert plan["repositories"][0]["owned_paths"] == sorted(["owned.txt", "with space.txt"])
