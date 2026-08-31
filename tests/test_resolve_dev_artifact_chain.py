"""Focused read-only result/preflight contract tests for LANE-R1."""
from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RESOLVER_PATH = ROOT / "scripts" / "resolve-dev-artifact-chain.py"
HELPERS_PATH = ROOT / "tests" / "test_aggregate_dev_report.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


H = load(HELPERS_PATH, "r1_contract_helpers")
RESOLVER = load(RESOLVER_PATH, "r1_resolver")


def singular_with_declared_paths(
    root: Path, files_modified: list, *, files_created: list | None = None,
    flat_files_modified: list | None = None,
) -> tuple[dict, dict[str, Path]]:
    declaration, paths = H.make_final_chain(root, "singular")
    declaration, _ = H.rebind_singular_declared_paths(
        declaration, paths["canonical"], files_modified=files_modified,
        files_created=files_created, flat_files_modified=flat_files_modified,
    )
    return declaration, paths


@pytest.mark.parametrize(
    ("shape", "mode"),
    [("singular", "singular"), ("parallel_dev", "parallel_dev"), ("requirement_fanout", "fanout")],
)
def test_all_declared_shapes_resolve_with_compatibility_aliases(tmp_path: Path, shape: str, mode: str) -> None:
    declaration, _ = H.make_final_chain(tmp_path, shape)
    result = RESOLVER.resolve_chain(tmp_path, H.TASK)
    assert result["status"] == "pass", result["errors"]
    assert result["schema_version"] == RESOLVER.RESULT_VERSION
    assert result["shape"] == shape
    assert result["mode"] == mode
    assert result["task_id"] == result["parent_task_id"] == H.TASK
    assert result["canonical_dev_report"] == result["parent"]["canonical_dev_report"]
    assert result["completion"] == result["parent"]["completion"]
    assert result["commit_whitelist_artifacts"] == result["artifact_paths"]
    assert result["lineage_digest"] == declaration["lineage_digest"]


def test_exact_relationship_matrix_for_parallel_dev(tmp_path: Path) -> None:
    declaration, _ = H.make_final_chain(tmp_path, "parallel_dev")
    result = RESOLVER.resolve_chain(tmp_path, H.TASK)
    assert len(result["lanes"]) == 2
    for row in result["lanes"]:
        assert row["member_kind"] == "parallel_worker"
        assert row["ticket"] is row["context"] is row["qa_report"] is None
        assert row["task_id"] == row["member_id"]
        assert row["lineage_digest"] == result["lineage_digest"]
        assert row["attempt_history"][0]["record_kind"] == "immutable_member"
    assert result["qa_inputs"] == [{
        "scope": "parent", "member_id": None, "task_id": H.TASK,
        "qa_report": f"docs/dev/qa-report-{H.TASK}.json",
    }]
    expected_reports = [f"docs/dev/dev-report-{H.TASK}.json"] + [m["artifact_paths"]["dev_report"] for m in declaration["member_lineage"]] + [f"docs/dev/qa-report-{H.TASK}.json"]
    assert result["report_paths"] == expected_reports


def test_exact_relationship_matrix_for_requirement_fanout(tmp_path: Path) -> None:
    declaration, _ = H.make_final_chain(tmp_path, "requirement_fanout")
    result = RESOLVER.resolve_chain(tmp_path, H.TASK)
    assert result["parent"]["ticket"] is None
    assert result["parent"]["context"] is None
    assert result["parent"]["qa_report"] is None
    assert [item["scope"] for item in result["qa_inputs"]] == ["member", "member"]
    assert [item["member_id"] for item in result["qa_inputs"]] == [m["member_id"] for m in declaration["member_lineage"]]
    assert all(all(row[field] is not None for field in ("ticket", "context", "dev_report", "qa_report")) for row in result["lanes"])


def test_preflight_redirects_exact_child_before_any_mutation(tmp_path: Path) -> None:
    declaration, paths = H.make_final_chain(tmp_path, "parallel_dev")
    child = declaration["member_lineage"][0]["member_id"]
    before = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = RESOLVER.preflight_parent(tmp_path, child)
    after = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert result["status"] == "redirect"
    assert result["parent_task_id"] == H.TASK
    assert result["errors"][0]["code"] == "PARENT_TASK_ID_REQUIRED"
    assert before == after


def test_parent_preflight_is_ready_and_read_only(tmp_path: Path) -> None:
    declaration, paths = H.make_final_chain(tmp_path, "parallel_dev")
    before = paths["canonical"].read_bytes()
    result = RESOLVER.preflight_parent(tmp_path, H.TASK)
    assert result["status"] == "ready"
    assert result["canonical_state"] == "present"
    assert result["canonical_sha256"] == H.hashlib.sha256(before).hexdigest()
    assert result["phase_digest"] == declaration["phase_projection"]["phase_digest"]
    assert paths["canonical"].read_bytes() == before


def test_lawful_real_in_root_declared_file_resolves(tmp_path: Path) -> None:
    tracked = tmp_path / "src" / "tracked.txt"
    tracked.parent.mkdir()
    tracked.write_text("inside", encoding="utf-8")
    singular_with_declared_paths(tmp_path, ["src/tracked.txt"])
    result = RESOLVER.resolve_chain(tmp_path, H.TASK)
    assert result["status"] == "pass", result["errors"]
    assert result["checks"]["declared_paths_exist"] is True


@pytest.mark.parametrize(
    "layout",
    [
        "direct-external-file", "external-directory", "nested-external-directory",
        "broken-file", "broken-intermediate", "directory-target", "non-directory-intermediate",
    ],
)
def test_declared_paths_reject_symlink_escape_and_broken_components(tmp_path: Path, layout: str) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-external"
    outside.mkdir()
    (outside / "outside.txt").write_text("outside", encoding="utf-8")
    if layout == "direct-external-file":
        (tmp_path / "declared.txt").symlink_to(outside / "outside.txt")
        relative = "declared.txt"
    elif layout == "external-directory":
        (tmp_path / "escape").symlink_to(outside, target_is_directory=True)
        relative = "escape/outside.txt"
    elif layout == "nested-external-directory":
        (tmp_path / "real").mkdir()
        (tmp_path / "real" / "escape").symlink_to(outside, target_is_directory=True)
        relative = "real/escape/outside.txt"
    elif layout == "broken-file":
        (tmp_path / "declared.txt").symlink_to(tmp_path / "missing.txt")
        relative = "declared.txt"
    elif layout == "broken-intermediate":
        (tmp_path / "broken").symlink_to(tmp_path / "missing-directory", target_is_directory=True)
        relative = "broken/missing.txt"
    elif layout == "directory-target":
        (tmp_path / "declared-directory").mkdir()
        relative = "declared-directory"
    else:
        (tmp_path / "not-a-directory").write_text("file", encoding="utf-8")
        relative = "not-a-directory/missing.txt"
    singular_with_declared_paths(tmp_path, [relative])
    result = RESOLVER.resolve_chain(tmp_path, H.TASK)
    assert result["status"] == "fail"
    assert result["checks"]["declared_paths_exist"] is False
    assert any(error["code"] in {"INVENTORY_MISMATCH", "MISSING_ARTIFACT"} for error in result["errors"])


@pytest.mark.parametrize(
    "relative",
    ["../outside.txt", "./tracked.txt", "dir/../tracked.txt", "dir//tracked.txt", "dir\\tracked.txt", "/tracked.txt"],
)
def test_declared_paths_reject_lexical_traversal_and_aliases(tmp_path: Path, relative: str) -> None:
    (tmp_path / "tracked.txt").write_text("inside", encoding="utf-8")
    singular_with_declared_paths(tmp_path, [relative])
    result = RESOLVER.resolve_chain(tmp_path, H.TASK)
    assert result["status"] == "fail"
    assert result["checks"]["declared_paths_exist"] is False
    assert any(error["code"] == "INVENTORY_MISMATCH" for error in result["errors"])


@pytest.mark.parametrize("bad", [False, True, 1, 1.0, None, [], {}])
def test_declared_paths_reject_wrong_json_types(tmp_path: Path, bad) -> None:
    singular_with_declared_paths(tmp_path, [bad])
    result = RESOLVER.resolve_chain(tmp_path, H.TASK)
    assert result["status"] == "fail"
    assert result["checks"]["declared_paths_exist"] is False
    assert any(error["code"] in {"INVALID_STATUS", "INVENTORY_MISMATCH"} for error in result["errors"])


def test_declared_paths_reject_duplicate_cross_list_and_hardlink_aliases(tmp_path: Path) -> None:
    tracked = tmp_path / "tracked.txt"
    alias = tmp_path / "alias.txt"
    tracked.write_text("inside", encoding="utf-8")
    alias.hardlink_to(tracked)
    cases = [
        (["tracked.txt", "tracked.txt"], []),
        (["tracked.txt"], ["tracked.txt"]),
        (["tracked.txt", "alias.txt"], []),
    ]
    for index, (modified, created) in enumerate(cases):
        root = tmp_path / f"case-{index}"
        root.mkdir()
        (root / "tracked.txt").hardlink_to(tracked)
        (root / "alias.txt").hardlink_to(tracked)
        singular_with_declared_paths(root, modified, files_created=created)
        result = RESOLVER.resolve_chain(root, H.TASK)
        assert result["status"] == "fail"
        assert result["checks"]["declared_paths_exist"] is False
        assert any(error["code"] == "INVENTORY_MISMATCH" for error in result["errors"])


def test_declared_paths_reject_flat_nested_alias_ambiguity(tmp_path: Path) -> None:
    (tmp_path / "tracked.txt").write_text("inside", encoding="utf-8")
    singular_with_declared_paths(
        tmp_path, ["tracked.txt"], flat_files_modified=[],
    )
    result = RESOLVER.resolve_chain(tmp_path, H.TASK)
    assert result["status"] == "fail"
    assert result["checks"]["declared_paths_exist"] is False
    assert any(error["code"] == "INVALID_STATUS" and "type-strictly equal" in error["message"] for error in result["errors"])


def test_missing_canonical_requires_repair_and_is_not_created(tmp_path: Path) -> None:
    (tmp_path / "docs/dev").mkdir(parents=True)
    result = RESOLVER.preflight_parent(tmp_path, H.TASK)
    assert result["status"] == "repair_required"
    assert result["canonical_state"] == "absent"
    assert result["errors"][0]["code"] == "CANONICAL_NOT_FOUND"
    assert not (tmp_path / f"docs/dev/dev-report-{H.TASK}.json").exists()


def test_overnight_intermediate_is_non_lifecycle(tmp_path: Path) -> None:
    dev = tmp_path / "docs/dev"
    dev.mkdir(parents=True)
    H.write_json(dev / f"dev-report-{H.TASK}.json", {
        "request_id": H.TASK, "task_id": H.TASK,
        "artifact_chain_role": "overnight_pipeline_intermediate",
        "artifact_chain_declaration": None,
    })
    result = RESOLVER.preflight_parent(tmp_path, H.TASK)
    assert result["status"] == "repair_required"
    assert result["errors"][0]["code"] == "NON_LIFECYCLE_REPORT"


def test_changed_immutable_member_bytes_fail_freshness_and_hash(tmp_path: Path) -> None:
    declaration, _ = H.make_final_chain(tmp_path, "parallel_dev")
    member_path = tmp_path / declaration["member_lineage"][0]["artifact_paths"]["dev_report"]
    report = json.loads(member_path.read_text())
    report["dev"]["tasks_completed"] = [{"changed": True}]
    H.write_json(member_path, report)
    result = RESOLVER.resolve_chain(tmp_path, H.TASK)
    assert result["status"] == "fail"
    assert "STALE_CANONICAL" in {error["code"] for error in result["errors"]}


def test_undeclared_retry_is_rejected_without_path_inference_acceptance(tmp_path: Path) -> None:
    declaration, _ = H.make_final_chain(tmp_path, "parallel_dev")
    member = declaration["member_lineage"][0]
    report = H.dev_report(member["member_id"], binding={
        "parent_task_id": H.TASK, "member_id": member["member_id"],
        "lineage_digest": declaration["lineage_digest"], "attempt": 2,
    })
    rogue = tmp_path / f"docs/dev/dev-report-iter2-{H.TASK}-{member['member_id']}.json"
    H.write_json(rogue, report)
    result = RESOLVER.resolve_chain(tmp_path, H.TASK)
    assert result["status"] == "fail"
    assert any(error["code"] == "INVENTORY_MISMATCH" and error["path"].endswith(rogue.name) for error in result["errors"])


def test_exact_singular_sidecar_has_aggregate_resolver_parity_and_zero_mutation(
    tmp_path: Path,
) -> None:
    declaration, _ = H.make_final_chain(tmp_path, "singular")
    sidecar = tmp_path / "docs/dev/arbitrary-content-authority.json"
    H.write_json(sidecar, H.dev_report(H.TASK))
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*") if path.is_file() and not path.is_symlink()
    }

    normalized, aggregate_errors = H.AGG.validate_declaration(
        declaration, H.TASK, root=tmp_path, validate_artifacts=True,
    )
    result = RESOLVER.resolve_chain(tmp_path, H.TASK)
    aggregate_match = [
        error for error in aggregate_errors
        if error["path"] == "docs/dev/arbitrary-content-authority.json"
    ]
    resolver_match = [
        error for error in result["errors"]
        if error["path"] == "docs/dev/arbitrary-content-authority.json"
    ]
    assert normalized is None
    assert result["status"] == "fail"
    assert aggregate_match == resolver_match
    assert aggregate_match[0]["code"] == "INVENTORY_MISMATCH"
    assert "exact_mutable_singular_identity" in aggregate_match[0]["message"]
    after = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*") if path.is_file() and not path.is_symlink()
    }
    assert after == before


@pytest.mark.parametrize(
    ("request_id", "task_id", "role"),
    [
        (H.TASK + "-foreign", H.TASK + "-foreign", "lifecycle_singular_parent"),
        (H.TASK, H.TASK + "-foreign", "lifecycle_singular_parent"),
        (H.TASK + "-foreign", H.TASK, "lifecycle_singular_parent"),
        (H.TASK, H.TASK, "lifecycle_singular_parent-suffix"),
        (False, H.TASK, "lifecycle_singular_parent"),
        (H.TASK, {}, "lifecycle_singular_parent"),
    ],
)
def test_resolver_singular_sidecar_negative_identity_and_suffix_controls(
    tmp_path: Path, request_id, task_id, role,
) -> None:
    H.make_final_chain(tmp_path, "singular")
    report = H.dev_report(H.TASK)
    report.update(request_id=request_id, task_id=task_id, artifact_chain_role=role)
    sidecar = tmp_path / f"docs/dev/dev-report-iter2-{H.TASK}-suffix.json"
    sidecar_raw = H.write_json(sidecar, report)
    result = RESOLVER.resolve_chain(tmp_path, H.TASK)
    assert result["status"] == "pass", result["errors"]
    assert sidecar.read_bytes() == sidecar_raw


def test_resolver_rejects_hardlink_alias_of_exact_singular_sidecar(tmp_path: Path) -> None:
    H.make_final_chain(tmp_path, "singular")
    origin = tmp_path / "unscanned-retry-source.bin"
    origin_raw = H.write_json(origin, H.dev_report(H.TASK))
    alias = tmp_path / "docs/dev/content-addressed-alias.json"
    alias.hardlink_to(origin)
    result = RESOLVER.resolve_chain(tmp_path, H.TASK)
    assert result["status"] == "fail"
    assert any(
        error["code"] == "INVENTORY_MISMATCH"
        and error["path"] == "docs/dev/content-addressed-alias.json"
        for error in result["errors"]
    )
    assert origin.read_bytes() == alias.read_bytes() == origin_raw


def test_resolver_sidecar_replacement_during_discovery_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    H.make_final_chain(tmp_path, "singular")
    canonical = tmp_path / f"docs/dev/dev-report-{H.TASK}.json"
    canonical_before = canonical.read_bytes()
    sidecar = tmp_path / "docs/dev/raced-retry.json"
    H.write_json(sidecar, H.dev_report(H.TASK + "-foreign"))
    replacement = H.dev_report(H.TASK)
    original_read = RESOLVER.AGG._read_regular_file_at
    replaced = False

    def replace_after_snapshot(directory_fd: int, name: str, display_path: str):
        nonlocal replaced
        raw, fingerprint = original_read(directory_fd, name, display_path)
        if display_path == "docs/dev/raced-retry.json" and not replaced:
            replaced = True
            sidecar.unlink()
            H.write_json(sidecar, replacement)
        return raw, fingerprint

    monkeypatch.setattr(RESOLVER.AGG, "_read_regular_file_at", replace_after_snapshot)
    result = RESOLVER.resolve_chain(tmp_path, H.TASK)
    assert replaced
    assert result["status"] == "fail"
    assert any(
        error["code"] == "INVENTORY_MISMATCH"
        and error["path"] == "docs/dev/raced-retry.json"
        for error in result["errors"]
    )
    assert canonical.read_bytes() == canonical_before
    assert json.loads(sidecar.read_text(encoding="utf-8"))["task_id"] == H.TASK


def test_parallel_parent_outcomes_are_closed_and_complete(tmp_path: Path) -> None:
    declaration, _ = H.make_final_chain(tmp_path, "parallel_dev")
    qa_path = tmp_path / f"docs/dev/qa-report-{H.TASK}.json"
    qa = json.loads(qa_path.read_text())
    qa["parallel_dev_worker_outcomes"]["worker_outcomes"].pop()
    H.write_json(qa_path, qa)
    result = RESOLVER.resolve_chain(tmp_path, H.TASK)
    codes = {error["code"] for error in result["errors"]}
    assert result["status"] == "fail"
    assert "INVALID_STATUS" in codes or "INVALID_PHASE_TRANSITION" in codes


def test_decomposed_unicode_baseline_does_not_equal_precomposed(tmp_path: Path) -> None:
    declaration, _ = H.make_final_chain(tmp_path, "parallel_dev")
    path = tmp_path / declaration["member_lineage"][0]["artifact_paths"]["dev_report"]
    report = json.loads(path.read_text())
    report["baseline_dirty_snapshot"] = report["baseline_dirty_snapshot"].replace("e\u0301", "é")
    H.write_json(path, report)
    result = RESOLVER.resolve_chain(tmp_path, H.TASK)
    assert any(error["code"] == "BASELINE_MISMATCH" for error in result["errors"])


@pytest.mark.parametrize("invalid_layout", ["evidence_scalar", "nested_phase_digest"])
def test_singular_resolve_rejects_stable_evidence_outside_exact_top_level_object(
    tmp_path: Path, invalid_layout: str,
) -> None:
    declaration, paths = H.make_final_chain(tmp_path, "singular")
    canonical = json.loads(paths["canonical"].read_text(encoding="utf-8"))
    candidate = copy.deepcopy(declaration)
    if invalid_layout == "evidence_scalar":
        canonical["artifact_chain_evidence"] = True
    else:
        canonical["dev"]["phase_digest"] = "sha256:" + "f" * 64
        projection = {
            key: copy.deepcopy(value)
            for key, value in canonical.items()
            if key not in {"artifact_chain_declaration", "artifact_chain_evidence"}
        }
        projection_raw = H.AGG._canonical_bytes(projection)
        stable_digest = H.AGG._bytes_digest(projection_raw)
        ledger = candidate["phase_projection"]["members"][0]["attempt_ledger"][0]
        ledger["stable_projection_sha256"] = stable_digest
        ledger["stable_projection_utf8_base64"] = H.base64.b64encode(projection_raw).decode("ascii")
        for event in candidate["phase_projection"]["events"]:
            if event["to_state"] in {"dev_completed", "awaiting_qa"}:
                event["evidence_digest"] = stable_digest
        candidate = H.AGG.finalize_declaration(candidate)
        canonical["artifact_chain_declaration"] = candidate
    before = H.write_json(paths["canonical"], canonical)
    result = RESOLVER.resolve_chain(tmp_path, H.TASK)
    assert result["status"] == "fail"
    assert any(error["code"] == "INVALID_DECLARATION" for error in result["errors"])
    assert paths["canonical"].read_bytes() == before


def test_cli_failure_is_parseable_v2_and_exit_two(tmp_path: Path) -> None:
    (tmp_path / "docs/dev").mkdir(parents=True)
    proc = subprocess.run(
        [sys.executable, str(RESOLVER_PATH), "--project-dir", str(tmp_path), "--task-id", H.TASK],
        text=True, capture_output=True,
    )
    payload = json.loads(proc.stdout)
    assert proc.returncode == 2
    assert payload["schema_version"] == RESOLVER.RESULT_VERSION
    assert payload["status"] == "fail"
    assert set(("shape", "mode", "parent", "lanes", "qa_inputs", "artifact_paths")).issubset(payload)


def test_cli_preflight_exit_pairing(tmp_path: Path) -> None:
    H.make_final_chain(tmp_path, "singular")
    proc = subprocess.run(
        [sys.executable, str(RESOLVER_PATH), "--project-dir", str(tmp_path), "--task-id", H.TASK, "--preflight-parent"],
        text=True, capture_output=True,
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["status"] == "ready"


def test_parent_outcome_subset_expands_one_default_per_active_worker(tmp_path: Path) -> None:
    declaration, _ = H.make_final_chain(tmp_path, "parallel_dev")
    before = RESOLVER._prior_parallel_qa_declaration(declaration)
    assert before is not None
    active = [m["member_id"] for m in before["phase_projection"]["members"] if m["state"] != "superseded"]
    report = H.qa_report(H.TASK, outcomes={
        "schema_version": H.AGG.OUTCOMES_VERSION,
        "parent_task_id": H.TASK,
        "lineage_digest": before["lineage_digest"],
        "phase_digest_before": before["phase_projection"]["phase_digest"],
        "coverage": "subset",
        "default_outcome": "pass",
        "worker_outcomes": [{"member_id": active[0], "outcome": "needs_review"}],
    }, status="needs_review")
    expanded, errors = H.AGG.validate_parallel_worker_outcomes(report, before)
    assert errors == []
    assert expanded == {active[0]: "needs_review", active[1]: "pass"}


def test_fanout_optional_parent_entries_may_be_declared_but_absent(tmp_path: Path) -> None:
    declaration, paths = H.make_final_chain(tmp_path, "requirement_fanout")
    paths["canonical"].unlink()
    optional = {
        "parent_ticket": f"docs/dev/ticket-{H.TASK}.md",
        "parent_context": f"docs/dev/context-{H.TASK}.json",
        "parent_qa_report": f"docs/dev/qa-report-{H.TASK}.json",
    }
    for kind, path in optional.items():
        declaration["inventory"].append(H._inventory_entry(kind, path, None, False))
    declaration["inventory"].sort(key=H.AGG._inventory_sort_key)
    declaration["inventory_digest"] = H.AGG._digest(declaration["inventory"])
    declaration["lineage_digest"] = H.AGG._digest({
        key: declaration[key]
        for key in ("schema_version", "parent_task_id", "shape", "execution", "origin", "member_lineage", "inventory", "inventory_digest", "baseline_policy", "baseline_bindings")
    })
    phase_by_id = {member["member_id"]: member for member in declaration["phase_projection"]["members"]}
    for member in declaration["member_lineage"]:
        report_path = tmp_path / member["artifact_paths"]["dev_report"]
        report = json.loads(report_path.read_text())
        report["artifact_chain_binding"]["lineage_digest"] = declaration["lineage_digest"]
        raw = H.write_json(report_path, report)
        stable = H.AGG.stable_dev_projection(report)[1]
        ledger = phase_by_id[member["member_id"]]["attempt_ledger"][0]
        ledger["artifact_sha256"] = H.AGG._bytes_digest(raw)
        ledger["stable_projection_sha256"] = stable
    for event in declaration["phase_projection"]["events"]:
        if event["to_state"] in {"dev_completed", "awaiting_qa"}:
            event["evidence_digest"] = phase_by_id[event["member_id"]]["attempt_ledger"][0]["artifact_sha256"]
    declaration = H.AGG.finalize_declaration(declaration)
    created = H.AGG.apply_artifact_chain_declaration(
        tmp_path, H.TASK, declaration, operation="default_aggregate", expect_canonical_absent=True,
    )
    assert created["status"] == "ok", created
    result = RESOLVER.resolve_chain(tmp_path, H.TASK)
    assert result["status"] == "pass", result["errors"]
    assert result["parent"]["ticket"] == optional["parent_ticket"]
    assert result["parent"]["context"] == optional["parent_context"]
    assert result["parent"]["qa_report"] == optional["parent_qa_report"]
    assert optional["parent_qa_report"] not in result["report_paths"]
    assert set(optional.values()).isdisjoint(result["artifact_paths"])


def test_suffix_collision_report_is_not_claimed_by_filename_prefix(tmp_path: Path) -> None:
    H.make_final_chain(tmp_path, "parallel_dev")
    foreign_parent = H.TASK + "-other"
    foreign_member = foreign_parent + "-w1"
    rogue = H.dev_report(foreign_member, binding={
        "parent_task_id": foreign_parent, "member_id": foreign_member,
        "lineage_digest": "sha256:" + "f" * 64, "attempt": 2,
    })
    H.write_json(
        tmp_path / f"docs/dev/dev-report-iter2-{H.TASK}-other-w1.json", rogue,
    )
    result = RESOLVER.resolve_chain(tmp_path, H.TASK)
    assert result["status"] == "pass", result["errors"]


def test_duplicate_embedded_declaration_sidecar_is_rejected(tmp_path: Path) -> None:
    declaration, _ = H.make_final_chain(tmp_path, "parallel_dev")
    sidecar = tmp_path / "docs/dev/not-a-canonical-sidecar.json"
    H.write_json(sidecar, {
        "request_id": H.TASK, "task_id": H.TASK,
        "artifact_chain_declaration": declaration,
    })
    result = RESOLVER.resolve_chain(tmp_path, H.TASK)
    assert result["status"] == "fail"
    assert any(error["code"] == "INVENTORY_MISMATCH" and error["path"].endswith(sidecar.name) for error in result["errors"])
