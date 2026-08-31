"""Focused executable tests for artifact_chain_declaration_provider.v1."""
from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
AGG_PATH = ROOT / "scripts" / "aggregate-dev-report.py"
TASK = "20260810-120000-r1"
HEAD = "a" * 40
DIRTY = " M café.txt\n?? e\u0301.txt"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


AGG = load_module(AGG_PATH, "r1_aggregate")


def write_json(path: Path, value: dict) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = AGG._canonical_bytes(value)
    path.write_bytes(raw)
    return raw


def dev_report(identity: str, *, binding: dict | None = None, baseline: dict | None = None) -> dict:
    baseline = baseline or {"head_sha": HEAD, "dirty_snapshot": DIRTY}
    value = {
        "report_version": 1, "request_id": identity, "task_id": identity,
        "status": "completed", "files_modified": [], "files_created": [],
        "root_cause_addressed": "The declared artifact chain is enforced at its shared boundary.",
        "ac_status": {"AC-01": "met"},
        "baseline_head_sha": baseline["head_sha"],
        "baseline_dirty_snapshot": baseline["dirty_snapshot"],
        "artifact_chain_role": "lifecycle_declared_member" if binding else "lifecycle_singular_parent",
        "dev": {
            "status": "completed", "files_modified": [], "files_created": [],
            "tasks_completed": [], "scripts_created": [], "permissions_to_add": [],
            "observed_preexisting": [], "ac_status": {"AC-01": "met"},
            "git_rationale": {"how_fix_addresses_root": "The declared artifact chain is enforced at its shared boundary."},
        },
        "blocking_issues": [], "recommendations": [],
    }
    if binding is not None:
        value["artifact_chain_binding"] = binding
    return value


def qa_report(identity: str, *, outcomes: dict | None = None, status: str = "pass") -> dict:
    value = {"request_id": identity, "task_id": identity, "qa": {"status": status}}
    if outcomes is not None:
        value["parallel_dev_worker_outcomes"] = outcomes
    return value


def ticket(identity: str) -> str:
    return f"# Ticket\n\n**Task ID**: {identity}\n"


def completion(identity: str, paths: list[str]) -> str:
    return f"# Completion\n\n**Task ID**: {identity}\n\n" + "\n".join(f"- `{path}`" for path in paths) + "\n"


def _inventory_entry(kind: str, path: str, member_id: str | None, required: bool) -> dict:
    return {"kind": kind, "path": path, "member_id": member_id, "required": required}


def _base_topology(shape: str, parent: str, members: list[str]) -> tuple[list[dict], list[dict]]:
    inventory: list[dict] = []
    lineage: list[dict] = []
    parent_entries = {
        "canonical_dev_report": f"docs/dev/dev-report-{parent}.json",
        "parent_completion": f"docs/dev/completion-{parent}.md",
    }
    if shape in {"singular", "parallel_dev"}:
        parent_entries.update({
            "parent_ticket": f"docs/dev/ticket-{parent}.md",
            "parent_context": f"docs/dev/context-{parent}.json",
            "parent_qa_report": f"docs/dev/qa-report-{parent}.json",
        })
    for kind, path in parent_entries.items():
        inventory.append(_inventory_entry(kind, path, None, True))
    for ordinal, member in enumerate(members):
        if shape == "singular":
            paths = {
                "ticket": parent_entries["parent_ticket"], "context": parent_entries["parent_context"],
                "dev_report": parent_entries["canonical_dev_report"], "qa_report": parent_entries["parent_qa_report"],
            }
            kind = "singular_parent"
        elif shape == "parallel_dev":
            paths = {"ticket": None, "context": None, "dev_report": f"docs/dev/dev-report-{member}.json", "qa_report": None}
            inventory.append(_inventory_entry("worker_dev_report", paths["dev_report"], member, True))
            kind = "parallel_worker"
        else:
            paths = {
                "ticket": f"docs/dev/ticket-{member}.md", "context": f"docs/dev/context-{member}.json",
                "dev_report": f"docs/dev/dev-report-{member}.json", "qa_report": f"docs/dev/qa-report-{member}.json",
            }
            for name, ikind in (("ticket", "lane_ticket"), ("context", "lane_context"), ("dev_report", "lane_dev_report"), ("qa_report", "lane_qa_report")):
                inventory.append(_inventory_entry(ikind, paths[name], member, True))
            kind = "requirement_lane"
        lineage.append({
            "lineage_ordinal": ordinal, "member_id": member, "member_kind": kind,
            "artifact_paths": paths, "baseline_binding_key": "shared",
        })
    inventory.sort(key=AGG._inventory_sort_key)
    return inventory, lineage


def make_final_chain(root: Path, shape: str, *, parent: str = TASK, member_ids: list[str] | None = None) -> tuple[dict, dict[str, Path]]:
    members = member_ids or ([parent] if shape == "singular" else [f"{parent}-w1", f"{parent}-w2"])
    inventory, lineage = _base_topology(shape, parent, members)
    draft = {
        "schema_version": AGG.DECLARATION_VERSION, "parent_task_id": parent,
        "shape": shape, "execution": "sequential" if shape == "singular" else "parallel",
        "origin": "active_lifecycle", "member_lineage": lineage,
        "lineage_digest": "", "inventory": inventory, "inventory_digest": "",
        "baseline_policy": "shared_dispatch",
        "baseline_bindings": {"shared": {"head_sha": HEAD, "dirty_snapshot": DIRTY}, "by_member": {}},
        "phase_projection": {"phase_version": 0, "members": [], "events": [], "phase_digest": ""},
        "active_roster": [], "excluded_roster": [], "declaration_digest": "",
    }
    draft["inventory_digest"] = AGG._digest(inventory)
    draft["lineage_digest"] = AGG._digest({key: draft[key] for key in ("schema_version", "parent_task_id", "shape", "execution", "origin", "member_lineage", "inventory", "inventory_digest", "baseline_policy", "baseline_bindings")})
    docs = root / "docs" / "dev"
    docs.mkdir(parents=True)
    # Parent non-report artifacts.
    parent_paths = {entry["kind"]: entry["path"] for entry in inventory if entry["member_id"] is None}
    if "parent_ticket" in parent_paths:
        (root / parent_paths["parent_ticket"]).write_text(ticket(parent), encoding="utf-8")
        write_json(root / parent_paths["parent_context"], {"request_id": parent, "task_id": parent})
    # Member reports and their immutable ledger rows/snapshots.
    ledger_by_member: dict[str, dict] = {}
    for member in lineage:
        member_id = member["member_id"]
        binding = None if shape == "singular" else {"parent_task_id": parent, "member_id": member_id, "lineage_digest": draft["lineage_digest"], "attempt": 1}
        report = dev_report(member_id, binding=binding)
        stable_raw, stable_hash = AGG.stable_dev_projection(report)
        report_path = member["artifact_paths"]["dev_report"]
        if shape == "singular":
            ledger = {
                "schema_version": "attempt_ledger_record.v1", "record_kind": "mutable_singular", "attempt": 1,
                "artifact_path": report_path, "stable_projection_sha256": stable_hash,
                "stable_projection_utf8_base64": base64.b64encode(stable_raw).decode("ascii"), "completed_at_phase_version": 1,
            }
        else:
            report_raw = write_json(root / report_path, report)
            ledger = {
                "schema_version": "attempt_ledger_record.v1", "record_kind": "immutable_member", "attempt": 1,
                "artifact_path": report_path, "artifact_sha256": AGG._bytes_digest(report_raw),
                "stable_projection_sha256": stable_hash, "completed_at_phase_version": 1,
            }
        ledger_by_member[member_id] = ledger
        if shape == "requirement_fanout":
            paths = member["artifact_paths"]
            (root / paths["ticket"]).write_text(ticket(member_id), encoding="utf-8")
            write_json(root / paths["context"], {"request_id": member_id, "task_id": member_id})
    # v0 dispatched, v1 dev_completed, v2 awaiting_qa.
    events: list[dict] = []
    for version, transition in ((0, (None, "dispatched")), (1, ("dispatched", "dev_completed")), (2, ("dev_completed", "awaiting_qa"))):
        for ordinal, member in enumerate(lineage):
            evidence = "sha256:" + ("d" * 64) if version == 0 else ledger_by_member[member["member_id"]].get("artifact_sha256", ledger_by_member[member["member_id"]]["stable_projection_sha256"])
            events.append({
                "phase_version": version, "event_ordinal": ordinal, "member_id": member["member_id"],
                "from_state": transition[0], "to_state": transition[1], "attempt": 1,
                "evidence_digest": evidence, "superseded_by": None, "coverage_disposition": None,
            })
    pre_members = []
    for member in lineage:
        mid = member["member_id"]
        pre_members.append({
            "member_id": mid, "state": "awaiting_qa", "attempt": 1,
            "evidence_digest": ledger_by_member[mid].get("artifact_sha256", ledger_by_member[mid]["stable_projection_sha256"]),
            "superseded_by": None,
            "attempt_storage": "mutable_singular" if shape == "singular" else "immutable_member",
            "attempt_reservations": [{
                "schema_version": "attempt_reservation.v1", "attempt": 1,
                "artifact_path": member["artifact_paths"]["dev_report"], "expected_absent": True,
                "reserved_at_phase_version": 0,
            }],
            "attempt_ledger": [ledger_by_member[mid]], "current_attempt": 1,
        })
    pre_digest = AGG._digest({"lineage_digest": draft["lineage_digest"], "phase_version": 2, "members": pre_members, "events": events})
    # QA artifact, then v3 qa_pass evidence.
    if shape == "parallel_dev":
        outcomes = {
            "schema_version": AGG.OUTCOMES_VERSION, "parent_task_id": parent,
            "lineage_digest": draft["lineage_digest"], "phase_digest_before": pre_digest,
            "coverage": "all", "default_outcome": None,
            "worker_outcomes": [{"member_id": member, "outcome": "pass"} for member in members],
        }
        qa_raw = write_json(root / parent_paths["parent_qa_report"], qa_report(parent, outcomes=outcomes))
        qa_digests = {member: AGG._bytes_digest(qa_raw) for member in members}
    elif shape == "singular":
        qa_raw = write_json(root / parent_paths["parent_qa_report"], qa_report(parent))
        qa_digests = {parent: AGG._bytes_digest(qa_raw)}
    else:
        qa_digests = {}
        for member in lineage:
            qa_raw = write_json(root / member["artifact_paths"]["qa_report"], qa_report(member["member_id"]))
            qa_digests[member["member_id"]] = AGG._bytes_digest(qa_raw)
    for ordinal, member in enumerate(lineage):
        events.append({
            "phase_version": 3, "event_ordinal": ordinal, "member_id": member["member_id"],
            "from_state": "awaiting_qa", "to_state": "qa_pass", "attempt": 1,
            "evidence_digest": qa_digests[member["member_id"]], "superseded_by": None, "coverage_disposition": None,
        })
    final_members = []
    for member, prior in zip(lineage, pre_members):
        final_members.append({**prior, "state": "qa_pass", "evidence_digest": qa_digests[member["member_id"]]})
    draft["phase_projection"] = {"phase_version": 3, "members": final_members, "events": events, "phase_digest": ""}
    draft["active_roster"] = [{"ordinal": i, "member_id": m["member_id"], "state": "qa_pass", "attempt": 1} for i, m in enumerate(lineage)]
    declaration = AGG.finalize_declaration(draft)
    canonical_path = root / parent_paths["canonical_dev_report"]
    if shape == "singular":
        report = dev_report(parent)
        report["artifact_chain_declaration"] = declaration
        write_json(canonical_path, report)
    else:
        outcome = AGG.apply_artifact_chain_declaration(root, parent, declaration, operation="default_aggregate", expect_canonical_absent=True)
        assert outcome["status"] == "ok", outcome
    present_inventory = [entry["path"] for entry in inventory]
    (root / parent_paths["parent_completion"]).write_text(completion(parent, present_inventory), encoding="utf-8")
    return declaration, {"canonical": canonical_path, "completion": root / parent_paths["parent_completion"]}


def rebind_singular_declared_paths(
    declaration: dict, canonical_path: Path, *,
    files_modified: list, files_created: list | None = None,
    flat_files_modified: list | None = None, flat_files_created: list | None = None,
) -> tuple[dict, dict]:
    """Rebind a singular stable snapshot after changing its declared file lists."""
    candidate = copy.deepcopy(declaration)
    document = json.loads(canonical_path.read_text(encoding="utf-8"))
    created = [] if files_created is None else copy.deepcopy(files_created)
    document["dev"]["files_modified"] = copy.deepcopy(files_modified)
    document["dev"]["files_created"] = created
    document["files_modified"] = copy.deepcopy(files_modified if flat_files_modified is None else flat_files_modified)
    document["files_created"] = copy.deepcopy(created if flat_files_created is None else flat_files_created)
    stable_raw, stable_hash = AGG.stable_dev_projection(document)
    member = candidate["phase_projection"]["members"][0]
    ledger = member["attempt_ledger"][0]
    ledger["stable_projection_sha256"] = stable_hash
    ledger["stable_projection_utf8_base64"] = base64.b64encode(stable_raw).decode("ascii")
    for event in candidate["phase_projection"]["events"]:
        if event["to_state"] in {"dev_completed", "awaiting_qa"}:
            event["evidence_digest"] = stable_hash
    candidate = AGG.finalize_declaration(candidate)
    document["artifact_chain_declaration"] = candidate
    write_json(canonical_path, document)
    return candidate, document


def test_validate_only_returns_exact_provider_schema(tmp_path: Path) -> None:
    declaration, paths = make_final_chain(tmp_path, "singular")
    result = AGG.apply_artifact_chain_declaration(tmp_path, TASK, declaration, operation="validate_only")
    assert result["status"] == "ok"
    assert result["action"] == "validated"
    assert result["schema_version"] == AGG.PROVIDER_VERSION
    assert result["lineage_digest"] == declaration["lineage_digest"]
    assert result["changed"] is False


@pytest.mark.parametrize("shape", ["parallel_dev", "requirement_fanout"])
def test_absent_parallel_creation_is_declared_and_no_parent_fabrication(tmp_path: Path, shape: str) -> None:
    declaration, paths = make_final_chain(tmp_path, shape)
    canonical = json.loads(paths["canonical"].read_text())
    assert canonical["artifact_chain_declaration"] == declaration
    if shape == "requirement_fanout":
        assert not (tmp_path / f"docs/dev/ticket-{TASK}.md").exists()
        assert not (tmp_path / f"docs/dev/context-{TASK}.json").exists()
        assert not (tmp_path / f"docs/dev/qa-report-{TASK}.json").exists()


def test_mutating_provider_requires_exact_expected_state(tmp_path: Path) -> None:
    declaration, paths = make_final_chain(tmp_path, "singular")
    before = paths["canonical"].read_bytes()
    result = AGG.apply_artifact_chain_declaration(tmp_path, TASK, declaration, operation="update_declaration_only")
    assert result["status"] == "fail"
    assert result["changed"] is False
    assert paths["canonical"].read_bytes() == before


def test_stale_cas_loses_without_overwrite(tmp_path: Path) -> None:
    declaration, paths = make_final_chain(tmp_path, "singular")
    before = paths["canonical"].read_bytes()
    result = AGG.apply_artifact_chain_declaration(
        tmp_path, TASK, declaration, operation="update_declaration_only",
        expected_canonical_sha256="0" * 64,
        expected_phase_digest=declaration["phase_projection"]["phase_digest"],
    )
    assert result["errors"][0]["code"] == "CANONICAL_CHANGED"
    assert paths["canonical"].read_bytes() == before


@pytest.mark.parametrize("replacement_kind", ["regular", "symlink"])
def test_declared_artifact_read_rejects_replacement_before_return(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement_kind: str,
) -> None:
    target = tmp_path / "tracked.txt"
    target.write_text("before", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("outside", encoding="utf-8")
    original_open = AGG._open_regular_file_beneath
    calls = 0

    def replace_after_open(root: Path, relative):
        nonlocal calls
        opened = original_open(root, relative)
        calls += 1
        if calls == 1:
            target.unlink()
            if replacement_kind == "regular":
                target.write_text("replacement", encoding="utf-8")
            else:
                target.symlink_to(outside)
        return opened

    monkeypatch.setattr(AGG, "_open_regular_file_beneath", replace_after_open)
    with pytest.raises(AGG.ContractFailure) as failure:
        AGG._read_regular_file_bytes(tmp_path, "tracked.txt")
    assert failure.value.errors[0]["code"] in {"STALE_CANONICAL", "INVENTORY_MISMATCH"}


def test_inject_rejects_external_symlink_declared_path_without_canonical_mutation(tmp_path: Path) -> None:
    declaration, paths = make_final_chain(tmp_path, "singular")
    outside = tmp_path.parent / f"{tmp_path.name}-external"
    outside.mkdir()
    (outside / "outside.txt").write_text("outside", encoding="utf-8")
    (tmp_path / "escape").symlink_to(outside, target_is_directory=True)
    candidate, document = rebind_singular_declared_paths(
        declaration, paths["canonical"], files_modified=["escape/outside.txt"],
    )
    document.pop("artifact_chain_declaration")
    before = write_json(paths["canonical"], document)
    result = AGG.apply_artifact_chain_declaration(
        tmp_path, TASK, candidate, operation="inject_only",
        expected_canonical_sha256=hashlib.sha256(before).hexdigest(),
    )
    assert result["status"] == "fail"
    assert result["changed"] is False
    assert result["errors"][0]["code"] == "INVENTORY_MISMATCH"
    assert paths["canonical"].read_bytes() == before


def test_declared_path_replacement_race_fails_before_canonical_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    declaration, paths = make_final_chain(tmp_path, "singular")
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("inside", encoding="utf-8")
    outside = tmp_path.parent / f"{tmp_path.name}-external.txt"
    outside.write_text("outside", encoding="utf-8")
    candidate, document = rebind_singular_declared_paths(
        declaration, paths["canonical"], files_modified=["tracked.txt"],
    )
    document.pop("artifact_chain_declaration")
    before = write_json(paths["canonical"], document)
    original_validate = AGG._validate_declared_repo_paths
    calls = 0

    def replace_after_validation(root: Path, report: dict, report_path: str, errors: list[dict[str, str]]):
        nonlocal calls
        result = original_validate(root, report, report_path, errors)
        calls += 1
        if calls == 1 and result is not None:
            tracked.unlink()
            tracked.symlink_to(outside)
        return result

    monkeypatch.setattr(AGG, "_validate_declared_repo_paths", replace_after_validation)
    result = AGG.apply_artifact_chain_declaration(
        tmp_path, TASK, candidate, operation="inject_only",
        expected_canonical_sha256=hashlib.sha256(before).hexdigest(),
    )
    assert calls >= 2
    assert result["status"] == "fail"
    assert result["changed"] is False
    assert result["errors"][0]["code"] == "INVENTORY_MISMATCH"
    assert paths["canonical"].read_bytes() == before


@pytest.mark.parametrize("bad", [None, True, 1.0, "1", 0, -1, 2_147_483_648])
def test_current_attempt_is_strict_integer_alias(tmp_path: Path, bad) -> None:
    declaration, _ = make_final_chain(tmp_path, "singular")
    broken = copy.deepcopy(declaration)
    broken["phase_projection"]["members"][0]["current_attempt"] = bad
    broken = AGG.finalize_declaration(broken)
    _, errors = AGG.validate_declaration(broken, TASK)
    assert any(error["code"] == "INVALID_DECLARATION" for error in errors)


def _replace_nested(value: dict, path: tuple, replacement) -> None:
    target = value
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = replacement


def test_every_declaration_phase_integer_field_rejects_boolean_aliases(tmp_path: Path) -> None:
    declaration, _ = make_final_chain(tmp_path, "parallel_dev")
    cases = [
        ("lineage ordinal zero", ("member_lineage", 0, "lineage_ordinal"), False, "INVALID_DECLARATION", "artifact_chain_declaration.member_lineage[0].lineage_ordinal"),
        ("lineage ordinal one", ("member_lineage", 1, "lineage_ordinal"), True, "INVALID_DECLARATION", "artifact_chain_declaration.member_lineage[1].lineage_ordinal"),
        ("phase version", ("phase_projection", "phase_version"), False, "INVALID_DECLARATION", "artifact_chain_declaration.phase_projection"),
        ("event phase version zero", ("phase_projection", "events", 0, "phase_version"), False, "INVALID_PHASE_TRANSITION", "artifact_chain_declaration.phase_projection.events[0]"),
        ("event phase version one", ("phase_projection", "events", 2, "phase_version"), True, "INVALID_PHASE_TRANSITION", "artifact_chain_declaration.phase_projection.events[2]"),
        ("event ordinal zero", ("phase_projection", "events", 0, "event_ordinal"), False, "INVALID_PHASE_TRANSITION", "artifact_chain_declaration.phase_projection.events[0]"),
        ("event ordinal one", ("phase_projection", "events", 1, "event_ordinal"), True, "INVALID_PHASE_TRANSITION", "artifact_chain_declaration.phase_projection.events[1]"),
        ("event attempt", ("phase_projection", "events", 0, "attempt"), True, "INVALID_PHASE_TRANSITION", "artifact_chain_declaration.phase_projection.events[0]"),
        ("phase member attempt", ("phase_projection", "members", 0, "attempt"), True, "INVALID_DECLARATION", "artifact_chain_declaration.phase_projection.members[0].attempt"),
        ("reservation attempt", ("phase_projection", "members", 0, "attempt_reservations", 0, "attempt"), True, "INVALID_DECLARATION", "artifact_chain_declaration.phase_projection.members[0].attempt_reservations[0]"),
        ("reservation phase version", ("phase_projection", "members", 0, "attempt_reservations", 0, "reserved_at_phase_version"), False, "INVALID_DECLARATION", "artifact_chain_declaration.phase_projection.members[0].attempt_reservations[0].reserved_at_phase_version"),
        ("ledger attempt", ("phase_projection", "members", 0, "attempt_ledger", 0, "attempt"), True, "INVALID_DECLARATION", "artifact_chain_declaration.phase_projection.members[0].attempt_ledger[0]"),
        ("ledger phase version", ("phase_projection", "members", 0, "attempt_ledger", 0, "completed_at_phase_version"), True, "INVALID_DECLARATION", "artifact_chain_declaration.phase_projection.members[0].attempt_ledger[0].completed_at_phase_version"),
        ("current attempt", ("phase_projection", "members", 0, "current_attempt"), True, "INVALID_DECLARATION", "artifact_chain_declaration.phase_projection.members[0].current_attempt"),
        ("active roster ordinal zero", ("active_roster", 0, "ordinal"), False, "INVALID_DECLARATION", "artifact_chain_declaration.active_roster[0].ordinal"),
        ("active roster ordinal one", ("active_roster", 1, "ordinal"), True, "INVALID_DECLARATION", "artifact_chain_declaration.active_roster[1].ordinal"),
        ("active roster attempt", ("active_roster", 0, "attempt"), True, "INVALID_DECLARATION", "artifact_chain_declaration.active_roster[0].attempt"),
    ]
    for name, path, bad, code, error_path in cases:
        candidate = copy.deepcopy(declaration)
        _replace_nested(candidate, path, bad)
        candidate = AGG.finalize_declaration(candidate)
        normalized, errors = AGG.validate_declaration(candidate, TASK)
        assert normalized is None, name
        assert any(error["code"] == code and error["path"] == error_path for error in errors), (name, errors)


@pytest.mark.parametrize(
    ("container", "index", "bad"),
    [
        pytest.param("member_lineage", 0, False, id="lineage-false"),
        pytest.param("member_lineage", 1, True, id="lineage-true"),
        pytest.param("member_lineage", 0, 0.0, id="lineage-float"),
        pytest.param("member_lineage", 0, "0", id="lineage-string"),
        pytest.param("member_lineage", 0, None, id="lineage-null"),
        pytest.param("member_lineage", 0, [], id="lineage-array"),
        pytest.param("member_lineage", 0, {}, id="lineage-object"),
        pytest.param("active_roster", 0, False, id="roster-false"),
        pytest.param("active_roster", 1, True, id="roster-true"),
        pytest.param("active_roster", 0, 0.0, id="roster-float"),
        pytest.param("active_roster", 0, "0", id="roster-string"),
        pytest.param("active_roster", 0, None, id="roster-null"),
        pytest.param("active_roster", 0, [], id="roster-array"),
        pytest.param("active_roster", 0, {}, id="roster-object"),
    ],
)
def test_lineage_and_roster_ordinal_types_fail_closed_without_canonical_mutation(
    tmp_path: Path, container: str, index: int, bad,
) -> None:
    declaration, paths = make_final_chain(tmp_path, "parallel_dev")
    before = paths["canonical"].read_bytes()
    candidate = copy.deepcopy(declaration)
    candidate[container][index]["lineage_ordinal" if container == "member_lineage" else "ordinal"] = bad
    candidate = AGG.finalize_declaration(candidate)
    field = "lineage_ordinal" if container == "member_lineage" else "ordinal"
    result = AGG.apply_artifact_chain_declaration(
        tmp_path, TASK, candidate, operation="default_aggregate",
        expected_canonical_sha256=hashlib.sha256(before).hexdigest(),
        expected_phase_digest=declaration["phase_projection"]["phase_digest"],
    )
    assert result["status"] == "fail"
    assert result["changed"] is False
    assert result["errors"][0]["code"] == "INVALID_DECLARATION"
    assert result["errors"][0]["path"] == f"artifact_chain_declaration.{container}[{index}].{field}"
    assert paths["canonical"].read_bytes() == before


def test_excluded_roster_integer_fields_are_type_exact() -> None:
    member = {
        "member_id": "lane-1", "state": "superseded", "attempt": 1,
        "evidence_digest": "sha256:" + "a" * 64, "superseded_by": "lane-2",
    }
    valid_row = {"ordinal": 0, **member}
    declaration = {"active_roster": [], "excluded_roster": [valid_row]}
    errors: list[dict[str, str]] = []
    AGG._validate_rosters(declaration, [member], [], errors)
    assert errors == []
    for field, bad in (
        ("ordinal", False), ("ordinal", True), ("ordinal", 0.0),
        ("ordinal", "0"), ("ordinal", None), ("ordinal", []),
        ("ordinal", {}), ("attempt", True),
    ):
        candidate = copy.deepcopy(declaration)
        candidate["excluded_roster"][0][field] = bad
        errors = []
        AGG._validate_rosters(candidate, [member], [], errors)
        assert errors[0] == {
            "code": "INVALID_DECLARATION",
            "path": f"artifact_chain_declaration.excluded_roster[0].{field}",
            "message": f"roster {field} must be an integer in range",
        }


def test_valid_integer_boundaries_and_roster_indices_pass(tmp_path: Path) -> None:
    assert AGG._is_int(0)
    assert AGG._is_int(AGG.INT_MAX)
    assert not AGG._is_int(False)
    assert not AGG._is_int(True)
    declaration, _ = make_final_chain(tmp_path, "parallel_dev")
    candidate = copy.deepcopy(declaration)
    candidate["phase_projection"]["events"][-1]["event_ordinal"] = AGG.INT_MAX
    candidate = AGG.finalize_declaration(candidate)
    normalized, errors = AGG.validate_declaration(candidate, TASK)
    assert errors == []
    assert normalized == candidate
    assert [row["lineage_ordinal"] for row in normalized["member_lineage"]] == [0, 1]
    assert [row["ordinal"] for row in normalized["active_roster"]] == [0, 1]


def test_mutable_singular_forbids_full_artifact_hash(tmp_path: Path) -> None:
    declaration, _ = make_final_chain(tmp_path, "singular")
    broken = copy.deepcopy(declaration)
    broken["phase_projection"]["members"][0]["attempt_ledger"][0]["artifact_sha256"] = "sha256:" + "f" * 64
    broken = AGG.finalize_declaration(broken)
    _, errors = AGG.validate_declaration(broken, TASK)
    assert errors


def test_stable_projection_excludes_only_chain_containers() -> None:
    report = dev_report(TASK)
    before, digest = AGG.stable_dev_projection(report)
    changed = copy.deepcopy(report)
    changed["artifact_chain_declaration"] = {"phase": 4}
    changed["artifact_chain_evidence"] = {
        "schema_version": "artifact_chain_evidence.v1",
        "lineage_digest": "sha256:" + "a" * 64,
        "phase_digest": "sha256:" + "b" * 64,
        "baseline_evidence": {"shared": None, "by_member": {}},
        "source_reports": [{
            "path": f"docs/dev/dev-report-{TASK}.json",
            "artifact_sha256": "sha256:" + "c" * 64,
            "stable_projection_sha256": "sha256:" + "d" * 64,
        }],
    }
    after, digest2 = AGG.stable_dev_projection(changed)
    assert before == after
    assert digest == digest2


@pytest.mark.parametrize("bad", [None, False, True, 0, 1.0, "evidence", []])
def test_stable_projection_requires_exact_top_level_evidence_object(bad) -> None:
    report = dev_report(TASK)
    report["artifact_chain_evidence"] = bad
    with pytest.raises(AGG.ContractFailure) as failure:
        AGG.stable_dev_projection(report)
    assert failure.value.errors == [{
        "code": "INVALID_DECLARATION",
        "path": "artifact_chain_evidence",
        "message": "artifact_chain_evidence must be one exact top-level object when present",
    }]


@pytest.mark.parametrize("field", sorted(AGG.STABLE_EVIDENCE_FIELDS))
@pytest.mark.parametrize("placement", ["top_level", "nested_dev"])
def test_stable_projection_rejects_every_evidence_field_outside_container(
    field: str, placement: str,
) -> None:
    report = dev_report(TASK)
    if placement == "top_level":
        report[field] = "sha256:" + "e" * 64
        expected_path = f"/{field}"
    else:
        report["dev"][field] = "sha256:" + "e" * 64
        expected_path = f"/dev/{field}"
    with pytest.raises(AGG.ContractFailure) as failure:
        AGG.stable_dev_projection(report)
    assert failure.value.errors[0]["code"] == "INVALID_DECLARATION"
    assert failure.value.errors[0]["path"] == expected_path
    assert "valid only inside the top-level artifact_chain_evidence object" in failure.value.errors[0]["message"]


@pytest.mark.parametrize(
    ("container", "expected_path"),
    [
        ({"tasks_completed": [{"phase_digest": "sha256:" + "f" * 64}]}, "/dev/tasks_completed/0/phase_digest"),
        ({"tasks_completed": [{"artifact_chain_evidence": {}}]}, "/dev/tasks_completed/0/artifact_chain_evidence"),
    ],
)
def test_stable_projection_rejects_evidence_leaks_through_arrays_and_nested_containers(
    container: dict, expected_path: str,
) -> None:
    report = dev_report(TASK)
    report["dev"].update(copy.deepcopy(container))
    with pytest.raises(AGG.ContractFailure) as failure:
        AGG.stable_dev_projection(report)
    assert failure.value.errors[0]["code"] == "INVALID_DECLARATION"
    assert failure.value.errors[0]["path"] == expected_path


def test_stable_projection_allows_adjacent_non_evidence_names_without_normalization() -> None:
    report = dev_report(TASK)
    report["dev"]["phase_digest_note"] = "e\u0301"
    report["dev"]["artifact_sha256_note"] = "é"
    raw, digest = AGG.stable_dev_projection(report)
    assert json.loads(raw)["dev"]["phase_digest_note"] == "e\u0301"
    assert b"e\\u0301" not in raw
    assert digest == AGG._bytes_digest(raw)


def test_valid_stable_evidence_container_replays_without_projection_or_canonical_drift(tmp_path: Path) -> None:
    declaration, paths = make_final_chain(tmp_path, "singular")
    canonical = json.loads(paths["canonical"].read_text(encoding="utf-8"))
    projection_before, digest_before = AGG.stable_dev_projection(canonical)
    canonical["artifact_chain_evidence"] = {
        "schema_version": "artifact_chain_evidence.v1",
        "lineage_digest": declaration["lineage_digest"],
        "phase_digest": declaration["phase_projection"]["phase_digest"],
        "baseline_evidence": copy.deepcopy(declaration["baseline_bindings"]),
        "source_reports": [],
    }
    projection_after, digest_after = AGG.stable_dev_projection(canonical)
    assert (projection_after, digest_after) == (projection_before, digest_before)
    before = write_json(paths["canonical"], canonical)
    replay = AGG.apply_artifact_chain_declaration(
        tmp_path, TASK, declaration, operation="update_declaration_only",
        expected_canonical_sha256=hashlib.sha256(before).hexdigest(),
        expected_phase_digest=declaration["phase_projection"]["phase_digest"],
    )
    assert replay["status"] == "ok", replay
    assert replay["action"] == "unchanged"
    assert replay["changed"] is False
    assert paths["canonical"].read_bytes() == before


def test_invalid_evidence_source_replacement_race_rejects_before_canonical_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    declaration, paths = make_final_chain(tmp_path, "parallel_dev")
    paths["canonical"].unlink()
    source = tmp_path / declaration["member_lineage"][0]["artifact_paths"]["dev_report"]
    backup = source.with_suffix(".valid-before-race")
    source_before = source.read_bytes()
    invalid = json.loads(source_before)
    invalid["dev"]["phase_digest"] = "sha256:" + "f" * 64
    original_replace = AGG._replace_bytes

    def replace_source_after_projection_validation(path: Path, raw: bytes):
        source.rename(backup)
        write_json(source, invalid)
        return original_replace(path, raw)

    monkeypatch.setattr(AGG, "_replace_bytes", replace_source_after_projection_validation)
    result = AGG.apply_artifact_chain_declaration(
        tmp_path, TASK, declaration, operation="default_aggregate",
        expect_canonical_absent=True,
    )
    assert result["status"] == "fail"
    assert result["changed"] is False
    assert result["errors"][0]["code"] == "STALE_CANONICAL"
    assert not paths["canonical"].exists()
    assert backup.read_bytes() == source_before
    with pytest.raises(AGG.ContractFailure):
        AGG.stable_dev_projection(json.loads(source.read_bytes()))
    assert not list(paths["canonical"].parent.glob(f".{paths['canonical'].name}.*.tmp"))


def test_unicode_baseline_is_not_normalized(tmp_path: Path) -> None:
    declaration, _ = make_final_chain(tmp_path, "singular")
    broken = copy.deepcopy(declaration)
    broken["baseline_bindings"]["shared"]["dirty_snapshot"] = DIRTY.replace("e\u0301", "é")
    broken = AGG.finalize_declaration(broken)
    _, errors = AGG.validate_declaration(broken, TASK)
    assert not errors  # each exact form is valid evidence
    assert declaration["baseline_bindings"]["shared"]["dirty_snapshot"].encode() != broken["baseline_bindings"]["shared"]["dirty_snapshot"].encode()


def test_cli_always_emits_structured_failure(tmp_path: Path) -> None:
    (tmp_path / "docs/dev").mkdir(parents=True)
    proc = subprocess.run(
        [sys.executable, str(AGG_PATH), "--project-dir", str(tmp_path), "--task-id", TASK,
         "--declaration-file", "-", "--validate-declaration-only"],
        input="{}", text=True, capture_output=True,
    )
    payload = json.loads(proc.stdout)
    assert proc.returncode == 2
    assert payload["schema_version"] == AGG.PROVIDER_VERSION
    assert payload["status"] == "fail"


def test_exact_task_mutable_singular_sidecar_is_rejected_without_canonical_mutation(
    tmp_path: Path,
) -> None:
    declaration, paths = make_final_chain(tmp_path, "singular")
    sidecar = tmp_path / "docs/dev/opaque-durable-retry.json"
    sidecar_raw = write_json(sidecar, dev_report(TASK))
    canonical_before = paths["canonical"].read_bytes()

    normalized, errors = AGG.validate_declaration(
        declaration, TASK, root=tmp_path, validate_artifacts=True,
    )
    assert normalized is None
    matching = [error for error in errors if error["path"] == "docs/dev/opaque-durable-retry.json"]
    assert matching == [{
        "code": "INVENTORY_MISMATCH",
        "path": "docs/dev/opaque-durable-retry.json",
        "message": (
            "exact_mutable_singular_identity: exact-task mutable-singular report "
            "is outside its sole canonical reservation/ledger union"
        ),
    }]
    assert paths["canonical"].read_bytes() == canonical_before
    assert sidecar.read_bytes() == sidecar_raw

    declarationless = json.loads(canonical_before)
    declarationless.pop("artifact_chain_declaration")
    writer_before = write_json(paths["canonical"], declarationless)
    result = AGG.apply_artifact_chain_declaration(
        tmp_path, TASK, declaration, operation="inject_only",
        expected_canonical_sha256=hashlib.sha256(writer_before).hexdigest(),
    )
    assert result["status"] == "fail"
    assert result["changed"] is False
    assert result["mutation_state"] == "none"
    assert any(error == matching[0] for error in result["errors"])
    assert paths["canonical"].read_bytes() == writer_before
    assert sidecar.read_bytes() == sidecar_raw


@pytest.mark.parametrize(
    ("request_id", "task_id", "role"),
    [
        (TASK + "-other", TASK + "-other", "lifecycle_singular_parent"),
        (TASK, TASK + "-other", "lifecycle_singular_parent"),
        (TASK + "-other", TASK, "lifecycle_singular_parent"),
        (TASK, TASK, "lifecycle_singular_parent-suffix"),
        (True, TASK, "lifecycle_singular_parent"),
        (TASK, [], "lifecycle_singular_parent"),
    ],
)
def test_singular_sidecar_discovery_does_not_infer_identity_from_filename_or_types(
    tmp_path: Path, request_id, task_id, role,
) -> None:
    declaration, paths = make_final_chain(tmp_path, "singular")
    report = dev_report(TASK)
    report.update(request_id=request_id, task_id=task_id, artifact_chain_role=role)
    sidecar = tmp_path / f"docs/dev/dev-report-iter2-{TASK}-suffix-collision.json"
    sidecar_raw = write_json(sidecar, report)
    before = paths["canonical"].read_bytes()

    normalized, errors = AGG.validate_declaration(
        declaration, TASK, root=tmp_path, validate_artifacts=True,
    )
    assert normalized == declaration
    assert errors == []
    assert paths["canonical"].read_bytes() == before
    assert sidecar.read_bytes() == sidecar_raw


def test_hardlink_alias_of_exact_singular_sidecar_is_classified_by_bytes_not_name(
    tmp_path: Path,
) -> None:
    declaration, paths = make_final_chain(tmp_path, "singular")
    origin = tmp_path / "unscanned-retry-source.bin"
    origin_raw = write_json(origin, dev_report(TASK))
    alias = tmp_path / "docs/dev/not-a-retry-name.json"
    alias.hardlink_to(origin)
    canonical_before = paths["canonical"].read_bytes()

    normalized, errors = AGG.validate_declaration(
        declaration, TASK, root=tmp_path, validate_artifacts=True,
    )
    assert normalized is None
    assert any(
        error["code"] == "INVENTORY_MISMATCH"
        and error["path"] == "docs/dev/not-a-retry-name.json"
        and "exact_mutable_singular_identity" in error["message"]
        for error in errors
    )
    assert paths["canonical"].read_bytes() == canonical_before
    assert origin.read_bytes() == alias.read_bytes() == origin_raw


@pytest.mark.parametrize("race_point", ["replace_entry", "pre_replace"])
def test_singular_sidecar_write_boundary_race_fails_then_clean_replay_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, race_point: str,
) -> None:
    declaration, paths = make_final_chain(tmp_path, "singular")
    canonical = paths["canonical"]
    document = json.loads(canonical.read_text(encoding="utf-8"))
    document.pop("artifact_chain_declaration")
    canonical_before = write_json(canonical, document)
    evidence_before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in (paths["completion"], tmp_path / f"docs/dev/qa-report-{TASK}.json")
    }
    sidecar = tmp_path / "docs/dev/raced-durable-retry.json"
    sidecar_raw = AGG._canonical_bytes(dev_report(TASK))
    injected = False

    def inject_sidecar() -> None:
        nonlocal injected
        assert not injected
        injected = True
        sidecar.write_bytes(sidecar_raw)

    original_replace = AGG._replace_bytes
    original_validate = AGG._validate_write_boundary
    if race_point == "replace_entry":
        def replace_after_initial_validation(path: Path, raw: bytes):
            inject_sidecar()
            return original_replace(path, raw)

        monkeypatch.setattr(AGG, "_replace_bytes", replace_after_initial_validation)
    else:
        calls = 0

        def validate_before_atomic_replace(boundary: dict) -> None:
            nonlocal calls
            calls += 1
            if calls == 3:
                inject_sidecar()
            original_validate(boundary)

        monkeypatch.setattr(AGG, "_validate_write_boundary", validate_before_atomic_replace)

    failed = AGG.apply_artifact_chain_declaration(
        tmp_path, TASK, declaration, operation="inject_only",
        expected_canonical_sha256=hashlib.sha256(canonical_before).hexdigest(),
    )
    assert injected
    assert failed["status"] == "fail"
    assert failed["changed"] is False
    assert failed["mutation_state"] == "none"
    assert any(
        error["code"] == "INVENTORY_MISMATCH"
        and error["path"] == "docs/dev/raced-durable-retry.json"
        for error in failed["errors"]
    )
    assert canonical.read_bytes() == canonical_before
    assert sidecar.read_bytes() == sidecar_raw
    assert evidence_before == {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in (paths["completion"], tmp_path / f"docs/dev/qa-report-{TASK}.json")
    }
    assert not list(canonical.parent.glob(f".{canonical.name}.*.tmp"))

    monkeypatch.setattr(AGG, "_replace_bytes", original_replace)
    monkeypatch.setattr(AGG, "_validate_write_boundary", original_validate)
    sidecar.unlink()
    repaired = AGG.apply_artifact_chain_declaration(
        tmp_path, TASK, declaration, operation="inject_only",
        expected_canonical_sha256=hashlib.sha256(canonical_before).hexdigest(),
    )
    assert repaired["status"] == "ok"
    assert repaired["changed"] is True
    written = canonical.read_bytes()
    replay = AGG.apply_artifact_chain_declaration(
        tmp_path, TASK, declaration, operation="update_declaration_only",
        expected_canonical_sha256=hashlib.sha256(written).hexdigest(),
        expected_phase_digest=declaration["phase_projection"]["phase_digest"],
    )
    assert replay["status"] == "ok", replay
    assert replay["action"] == "unchanged"
    assert replay["changed"] is False
    assert canonical.read_bytes() == written
    assert not list(canonical.parent.glob(f".{canonical.name}.*.tmp"))


def test_post_replace_fsync_failure_is_truthful_and_recoverable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    declaration, paths = make_final_chain(tmp_path, "singular")
    canonical = json.loads(paths["canonical"].read_text())
    canonical.pop("artifact_chain_declaration")
    before = write_json(paths["canonical"], canonical)
    real_fsync = AGG.os.fsync
    calls = {"count": 0}

    def fail_directory_fsync(fd: int) -> None:
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("injected directory fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(AGG.os, "fsync", fail_directory_fsync)
    result = AGG.apply_artifact_chain_declaration(
        tmp_path, TASK, declaration, operation="inject_only",
        expected_canonical_sha256=hashlib.sha256(before).hexdigest(),
    )
    assert result["status"] == "fail"
    assert result["action"] == "replaced_durability_uncertain"
    assert result["changed"] is True
    assert result["mutation_state"] == "committed_durability_uncertain"
    assert result["linearization_point"] == "os.replace"
    assert result["errors"][0]["code"] == "POST_REPLACE_DURABILITY_UNCERTAIN"
    assert json.loads(paths["canonical"].read_text())["artifact_chain_declaration"] == declaration
    assert not list(paths["canonical"].parent.glob(f".{paths['canonical'].name}.*.tmp"))

    monkeypatch.setattr(AGG.os, "fsync", real_fsync)
    recovered = AGG.recover_artifact_chain_durability(tmp_path, TASK, result["observed_canonical_sha256"])
    assert recovered["status"] == "ok"
    assert recovered["action"] == "unchanged"
    refused = AGG.recover_artifact_chain_durability(tmp_path, TASK, "0" * 64)
    assert refused["errors"][0]["code"] == "CANONICAL_CHANGED"


def _prepare_absent_parallel_write(root: Path) -> tuple[dict, dict[str, Path], Path]:
    declaration, paths = make_final_chain(root, "parallel_dev")
    paths["canonical"].unlink()
    source = root / declaration["member_lineage"][0]["artifact_paths"]["dev_report"]
    return declaration, paths, source


@pytest.mark.parametrize("race_point", ["replace_entry", "pre_replace"])
@pytest.mark.parametrize("race_target", ["source", "canonical_directory"])
def test_write_boundary_replacement_races_fail_without_canonical_or_temp_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, race_point: str, race_target: str,
) -> None:
    declaration, paths, source = _prepare_absent_parallel_write(tmp_path)
    canonical = paths["canonical"]
    real_dev = canonical.parent
    held_dev = tmp_path / "docs" / "dev-held-by-test"
    outside = tmp_path.parent / f"{tmp_path.name}-{race_point}-{race_target}-outside"
    outside.mkdir()
    outside_marker = outside / "marker.txt"
    outside_marker.write_bytes(b"external bytes remain exact")
    source_before = source.read_bytes()
    injected = False

    def inject_race() -> None:
        nonlocal injected
        assert not injected
        injected = True
        if race_target == "source":
            source.unlink()
            source.symlink_to(outside_marker)
        else:
            real_dev.rename(held_dev)
            real_dev.symlink_to(outside, target_is_directory=True)

    if race_point == "replace_entry":
        original_replace = AGG._replace_bytes

        def replace_after_evidence_validation(path: Path, raw: bytes):
            inject_race()
            return original_replace(path, raw)

        monkeypatch.setattr(AGG, "_replace_bytes", replace_after_evidence_validation)
    else:
        original_validate = AGG._validate_write_boundary
        validation_calls = 0

        def race_immediately_before_replace(boundary: dict) -> None:
            nonlocal validation_calls
            validation_calls += 1
            if validation_calls == 3:
                inject_race()
            original_validate(boundary)

        monkeypatch.setattr(AGG, "_validate_write_boundary", race_immediately_before_replace)

    result = AGG.apply_artifact_chain_declaration(
        tmp_path, TASK, declaration, operation="default_aggregate",
        expect_canonical_absent=True,
    )

    assert injected
    assert result["status"] == "fail"
    assert result["changed"] is False
    assert result["mutation_state"] == "none"
    assert result["linearization_point"] is None
    assert result["errors"][0]["code"] in {"INVALID_PROJECT_ROOT", "INVENTORY_MISMATCH", "STALE_CANONICAL"}
    assert outside_marker.read_bytes() == b"external bytes remain exact"
    if race_target == "source":
        assert source.is_symlink()
        assert source.read_bytes() == b"external bytes remain exact"
        assert not canonical.exists()
        assert not list(real_dev.glob(f".{canonical.name}.*.tmp"))
    else:
        assert real_dev.is_symlink()
        assert not (outside / canonical.name).exists()
        assert not (held_dev / canonical.name).exists()
        assert not list(outside.glob(f".{canonical.name}.*.tmp"))
        assert not list(held_dev.glob(f".{canonical.name}.*.tmp"))
        real_dev.unlink()
        held_dev.rename(real_dev)
        assert source.read_bytes() == source_before


def test_descriptor_anchored_write_success_replay_and_no_temp_leak(tmp_path: Path) -> None:
    declaration, paths, _ = _prepare_absent_parallel_write(tmp_path)
    canonical = paths["canonical"]
    written = AGG.apply_artifact_chain_declaration(
        tmp_path, TASK, declaration, operation="default_aggregate",
        expect_canonical_absent=True,
    )
    assert written["status"] == "ok"
    assert written["changed"] is True
    assert written["mutation_state"] == "committed_durable"
    assert not list(canonical.parent.glob(f".{canonical.name}.*.tmp"))
    raw = canonical.read_bytes()
    replay = AGG.apply_artifact_chain_declaration(
        tmp_path, TASK, candidate_from_canonical=True, operation="default_aggregate",
        expected_canonical_sha256=hashlib.sha256(raw).hexdigest(),
        expected_phase_digest=declaration["phase_projection"]["phase_digest"],
    )
    assert replay["status"] == "ok"
    assert replay["action"] == "unchanged"
    assert replay["changed"] is False
    assert canonical.read_bytes() == raw
    assert not list(canonical.parent.glob(f".{canonical.name}.*.tmp"))


def test_existing_canonical_is_unchanged_when_bound_source_is_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    declaration, paths = make_final_chain(tmp_path, "parallel_dev")
    canonical = paths["canonical"]
    document = json.loads(canonical.read_text(encoding="utf-8"))
    document.pop("artifact_chain_declaration")
    canonical_before = write_json(canonical, document)
    source = tmp_path / declaration["member_lineage"][0]["artifact_paths"]["dev_report"]
    source_backup = source.with_suffix(".original")
    source_before = source.read_bytes()
    outside = tmp_path.parent / f"{tmp_path.name}-existing-source-race.json"
    outside.write_bytes(b"external bytes remain exact")
    original_replace = AGG._replace_bytes

    def replace_bound_source(path: Path, raw: bytes):
        source.rename(source_backup)
        source.symlink_to(outside)
        return original_replace(path, raw)

    monkeypatch.setattr(AGG, "_replace_bytes", replace_bound_source)
    result = AGG.apply_artifact_chain_declaration(
        tmp_path, TASK, declaration, operation="inject_only",
        expected_canonical_sha256=hashlib.sha256(canonical_before).hexdigest(),
    )
    assert result["status"] == "fail"
    assert result["changed"] is False
    assert canonical.read_bytes() == canonical_before
    assert source_backup.read_bytes() == source_before
    assert outside.read_bytes() == b"external bytes remain exact"
    assert not list(canonical.parent.glob(f".{canonical.name}.*.tmp"))


@pytest.mark.parametrize("failure_point", ["file_fsync", "atomic_replace"])
def test_descriptor_anchored_pre_replace_failure_leaves_no_canonical_or_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_point: str,
) -> None:
    declaration, paths, source = _prepare_absent_parallel_write(tmp_path)
    canonical = paths["canonical"]
    source_before = source.read_bytes()
    if failure_point == "file_fsync":
        monkeypatch.setattr(AGG.os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("injected file fsync failure")))
    else:
        def fail_replace(_src, _dst, **_kwargs):
            raise OSError("injected anchored replace failure")

        monkeypatch.setattr(AGG.os, "replace", fail_replace)
    result = AGG.apply_artifact_chain_declaration(
        tmp_path, TASK, declaration, operation="default_aggregate",
        expect_canonical_absent=True,
    )
    assert result["status"] == "fail"
    assert result["changed"] is False
    assert result["errors"][0]["code"] == "ATOMIC_WRITE_FAILED"
    assert not canonical.exists()
    assert source.read_bytes() == source_before
    assert not list(canonical.parent.glob(f".{canonical.name}.*.tmp"))


def test_descriptor_anchored_pre_replace_cancellation_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    declaration, paths, source = _prepare_absent_parallel_write(tmp_path)
    canonical = paths["canonical"]
    source_before = source.read_bytes()
    original_validate = AGG._validate_write_boundary
    validation_calls = 0

    def cancel_after_temp_creation(boundary: dict) -> None:
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls == 3:
            raise KeyboardInterrupt("injected pre-replace cancellation")
        original_validate(boundary)

    monkeypatch.setattr(AGG, "_validate_write_boundary", cancel_after_temp_creation)
    with pytest.raises(KeyboardInterrupt, match="injected pre-replace cancellation"):
        AGG.apply_artifact_chain_declaration(
            tmp_path, TASK, declaration, operation="default_aggregate",
            expect_canonical_absent=True,
        )
    assert validation_calls == 3
    assert not canonical.exists()
    assert source.read_bytes() == source_before
    assert not list(canonical.parent.glob(f".{canonical.name}.*.tmp"))


def test_immutable_retry_reservation_promotion_and_parent_outcome_are_end_to_end(tmp_path: Path) -> None:
    declaration, paths = make_final_chain(tmp_path, "parallel_dev")
    canonical_path = paths["canonical"]
    members = declaration["member_lineage"]
    first_id, sibling_id = members[0]["member_id"], members[1]["member_id"]
    first_path = tmp_path / members[0]["artifact_paths"]["dev_report"]
    sibling_path = tmp_path / members[1]["artifact_paths"]["dev_report"]
    first_initial = first_path.read_bytes()
    sibling_initial = sibling_path.read_bytes()

    # Replace the initial all-pass QA phase with one needs-review worker and one
    # already-passed sibling, retaining the exact v0-v2 phase prefix.
    needs = copy.deepcopy(declaration)
    prefix = [event for event in needs["phase_projection"]["events"] if event["phase_version"] < 3]
    pre_members = []
    for member in needs["phase_projection"]["members"]:
        ledger = member["attempt_ledger"][-1]
        pre_members.append({**member, "state": "awaiting_qa", "evidence_digest": ledger["artifact_sha256"]})
    pre_digest = AGG._digest({"lineage_digest": needs["lineage_digest"], "phase_version": 2, "members": pre_members, "events": prefix})
    mixed_outcomes = {
        "schema_version": AGG.OUTCOMES_VERSION, "parent_task_id": TASK,
        "lineage_digest": needs["lineage_digest"], "phase_digest_before": pre_digest,
        "coverage": "all", "default_outcome": None,
        "worker_outcomes": [
            {"member_id": first_id, "outcome": "needs_review"},
            {"member_id": sibling_id, "outcome": "pass"},
        ],
    }
    qa_path = tmp_path / f"docs/dev/qa-report-{TASK}.json"
    mixed_raw = write_json(qa_path, qa_report(TASK, outcomes=mixed_outcomes, status="needs_review"))
    mixed_digest = AGG._bytes_digest(mixed_raw)
    mixed_events = prefix + [
        {"phase_version": 3, "event_ordinal": 0, "member_id": first_id, "from_state": "awaiting_qa", "to_state": "needs_review", "attempt": 1, "evidence_digest": mixed_digest, "superseded_by": None, "coverage_disposition": None},
        {"phase_version": 3, "event_ordinal": 1, "member_id": sibling_id, "from_state": "awaiting_qa", "to_state": "qa_pass", "attempt": 1, "evidence_digest": mixed_digest, "superseded_by": None, "coverage_disposition": None},
    ]
    mixed_members = [
        {**pre_members[0], "state": "needs_review", "evidence_digest": mixed_digest},
        {**pre_members[1], "state": "qa_pass", "evidence_digest": mixed_digest},
    ]
    needs["phase_projection"] = {"phase_version": 3, "members": mixed_members, "events": mixed_events, "phase_digest": ""}
    needs["active_roster"] = [
        {"ordinal": 0, "member_id": first_id, "state": "needs_review", "attempt": 1},
        {"ordinal": 1, "member_id": sibling_id, "state": "qa_pass", "attempt": 1},
    ]
    needs = AGG.finalize_declaration(needs)
    source_rows = []
    for member in members:
        raw = (tmp_path / member["artifact_paths"]["dev_report"]).read_bytes()
        source_rows.append((member["member_id"], json.loads(raw), raw))
    timestamp = json.loads(canonical_path.read_text())["timestamp"]
    write_json(canonical_path, AGG._build_aggregate(source_rows, TASK, needs, timestamp=timestamp))

    def mutate(candidate: dict, current: dict) -> dict:
        before = canonical_path.read_bytes()
        outcome = AGG.apply_artifact_chain_declaration(
            tmp_path, TASK, candidate, operation="default_aggregate",
            expected_canonical_sha256=hashlib.sha256(before).hexdigest(),
            expected_phase_digest=current["phase_projection"]["phase_digest"],
        )
        assert outcome["status"] == "ok", outcome
        return candidate

    # Reserve attempt 2 under CAS. Alias remains attempt 1.
    reserved = copy.deepcopy(needs)
    retry_path = f"docs/dev/dev-report-iter2-{TASK}-{first_id}.json"
    reservation = {"schema_version": "attempt_reservation.v1", "attempt": 2, "artifact_path": retry_path, "expected_absent": True, "reserved_at_phase_version": 4}
    reserved_member = reserved["phase_projection"]["members"][0]
    reserved_member["attempt_reservations"].append(reservation)
    reserved_member.update(state="retry_dispatched", attempt=2, evidence_digest="sha256:" + "e" * 64)
    reserved["phase_projection"]["events"].append({
        "phase_version": 4, "event_ordinal": 0, "member_id": first_id,
        "from_state": "needs_review", "to_state": "retry_dispatched", "attempt": 2,
        "evidence_digest": "sha256:" + "e" * 64, "superseded_by": None, "coverage_disposition": None,
    })
    reserved["phase_projection"]["phase_version"] = 4
    reserved["active_roster"][0].update(state="retry_dispatched", attempt=2)
    reserved = AGG.finalize_declaration(reserved)
    mutate(reserved, needs)
    assert first_path.read_bytes() == first_initial
    assert sibling_path.read_bytes() == sibling_initial

    # Create-only immutable retry, then promote its discriminated hashes.
    retry_report = dev_report(first_id, binding={
        "parent_task_id": TASK, "member_id": first_id,
        "lineage_digest": reserved["lineage_digest"], "attempt": 2,
    })
    retry_raw = write_json(tmp_path / retry_path, retry_report)
    _, retry_stable = AGG.stable_dev_projection(retry_report)
    promoted = copy.deepcopy(reserved)
    ledger2 = {
        "schema_version": "attempt_ledger_record.v1", "record_kind": "immutable_member",
        "attempt": 2, "artifact_path": retry_path,
        "artifact_sha256": AGG._bytes_digest(retry_raw),
        "stable_projection_sha256": retry_stable, "completed_at_phase_version": 5,
    }
    promoted_member = promoted["phase_projection"]["members"][0]
    promoted_member["attempt_ledger"].append(ledger2)
    promoted_member.update(state="dev_completed", current_attempt=2, evidence_digest=ledger2["artifact_sha256"])
    promoted["phase_projection"]["events"].append({
        "phase_version": 5, "event_ordinal": 0, "member_id": first_id,
        "from_state": "retry_dispatched", "to_state": "dev_completed", "attempt": 2,
        "evidence_digest": ledger2["artifact_sha256"], "superseded_by": None, "coverage_disposition": None,
    })
    promoted["phase_projection"]["phase_version"] = 5
    promoted["active_roster"][0].update(state="dev_completed")
    promoted = AGG.finalize_declaration(promoted)
    mutate(promoted, reserved)

    awaiting = copy.deepcopy(promoted)
    awaiting["phase_projection"]["members"][0].update(state="awaiting_qa")
    awaiting["phase_projection"]["events"].append({
        "phase_version": 6, "event_ordinal": 0, "member_id": first_id,
        "from_state": "dev_completed", "to_state": "awaiting_qa", "attempt": 2,
        "evidence_digest": ledger2["artifact_sha256"], "superseded_by": None, "coverage_disposition": None,
    })
    awaiting["phase_projection"]["phase_version"] = 6
    awaiting["active_roster"][0].update(state="awaiting_qa")
    awaiting = AGG.finalize_declaration(awaiting)
    mutate(awaiting, promoted)

    final_outcomes = {
        "schema_version": AGG.OUTCOMES_VERSION, "parent_task_id": TASK,
        "lineage_digest": awaiting["lineage_digest"],
        "phase_digest_before": awaiting["phase_projection"]["phase_digest"],
        "coverage": "subset", "default_outcome": "pass",
        "worker_outcomes": [{"member_id": first_id, "outcome": "pass"}],
    }
    final_qa_raw = write_json(qa_path, qa_report(TASK, outcomes=final_outcomes))
    final_qa_digest = AGG._bytes_digest(final_qa_raw)
    passed = copy.deepcopy(awaiting)
    passed["phase_projection"]["members"][0].update(state="qa_pass", evidence_digest=final_qa_digest)
    passed["phase_projection"]["events"].append({
        "phase_version": 7, "event_ordinal": 0, "member_id": first_id,
        "from_state": "awaiting_qa", "to_state": "qa_pass", "attempt": 2,
        "evidence_digest": final_qa_digest, "superseded_by": None, "coverage_disposition": None,
    })
    passed["phase_projection"]["phase_version"] = 7
    passed["active_roster"][0].update(state="qa_pass")
    passed = AGG.finalize_declaration(passed)
    mutate(passed, awaiting)

    inventory_paths = [entry["path"] for entry in passed["inventory"]] + [retry_path]
    paths["completion"].write_text(completion(TASK, inventory_paths), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/resolve-dev-artifact-chain.py"),
         "--project-dir", str(tmp_path), "--task-id", TASK],
        text=True, capture_output=True,
    )
    assert proc.returncode == 0, proc.stdout
    result = json.loads(proc.stdout)
    assert result["lanes"][0]["dev_report"] == retry_path
    assert [row["attempt"] for row in result["lanes"][0]["attempt_history"]] == [1, 2]
    assert first_path.read_bytes() == first_initial
    assert sibling_path.read_bytes() == sibling_initial


def test_mutable_singular_retry_keeps_projection_snapshots_without_full_hash(tmp_path: Path) -> None:
    declaration, paths = make_final_chain(tmp_path, "singular")
    canonical_path = paths["canonical"]
    original_document = json.loads(canonical_path.read_text())
    original_projection, _ = AGG.stable_dev_projection(original_document)

    # Establish a lawful needs_review state at v3.
    needs = copy.deepcopy(declaration)
    prefix = [event for event in needs["phase_projection"]["events"] if event["phase_version"] < 3]
    prior = copy.deepcopy(needs["phase_projection"]["members"][0])
    ledger1 = prior["attempt_ledger"][0]
    prior.update(state="awaiting_qa", evidence_digest=ledger1["stable_projection_sha256"])
    pre_digest = AGG._digest({"lineage_digest": needs["lineage_digest"], "phase_version": 2, "members": [prior], "events": prefix})
    needs_qa_raw = write_json(tmp_path / f"docs/dev/qa-report-{TASK}.json", qa_report(TASK, status="needs_review"))
    needs_qa_digest = AGG._bytes_digest(needs_qa_raw)
    needs_member = {**prior, "state": "needs_review", "evidence_digest": needs_qa_digest}
    needs_event = {"phase_version": 3, "event_ordinal": 0, "member_id": TASK, "from_state": "awaiting_qa", "to_state": "needs_review", "attempt": 1, "evidence_digest": needs_qa_digest, "superseded_by": None, "coverage_disposition": None}
    needs["phase_projection"] = {"phase_version": 3, "members": [needs_member], "events": prefix + [needs_event], "phase_digest": ""}
    needs["active_roster"] = [{"ordinal": 0, "member_id": TASK, "state": "needs_review", "attempt": 1}]
    needs = AGG.finalize_declaration(needs)
    original_document["artifact_chain_declaration"] = needs
    write_json(canonical_path, original_document)

    def singular_update(candidate: dict, current: dict, report_candidate: dict | None = None) -> dict:
        before = canonical_path.read_bytes()
        outcome = AGG.apply_artifact_chain_declaration(
            tmp_path, TASK, candidate, operation="update_declaration_only",
            expected_canonical_sha256=hashlib.sha256(before).hexdigest(),
            expected_phase_digest=current["phase_projection"]["phase_digest"],
            report_candidate=report_candidate,
        )
        assert outcome["status"] == "ok", outcome
        return outcome

    # Reservation and retry_dispatched are one declaration-only CAS; alias stays 1.
    reserved = copy.deepcopy(needs)
    reservation2 = {"schema_version": "attempt_reservation.v1", "attempt": 2, "artifact_path": f"docs/dev/dev-report-{TASK}.json", "expected_absent": False, "reserved_at_phase_version": 4}
    member = reserved["phase_projection"]["members"][0]
    member["attempt_reservations"].append(reservation2)
    member.update(state="retry_dispatched", attempt=2, evidence_digest="sha256:" + "e" * 64)
    reserved["phase_projection"]["events"].append({"phase_version": 4, "event_ordinal": 0, "member_id": TASK, "from_state": "needs_review", "to_state": "retry_dispatched", "attempt": 2, "evidence_digest": "sha256:" + "e" * 64, "superseded_by": None, "coverage_disposition": None})
    reserved["phase_projection"]["phase_version"] = 4
    reserved["active_roster"][0].update(state="retry_dispatched", attempt=2)
    reserved = AGG.finalize_declaration(reserved)
    singular_update(reserved, needs)

    # New report body and its snapshot/ledger promotion replace the one canonical atomically.
    retry_document = dev_report(TASK)
    retry_document["implementation_notes"] = "attempt two changed the stable implementation payload"
    retry_projection, retry_hash = AGG.stable_dev_projection(retry_document)
    promoted = copy.deepcopy(reserved)
    ledger2 = {
        "schema_version": "attempt_ledger_record.v1", "record_kind": "mutable_singular",
        "attempt": 2, "artifact_path": f"docs/dev/dev-report-{TASK}.json",
        "stable_projection_sha256": retry_hash,
        "stable_projection_utf8_base64": base64.b64encode(retry_projection).decode("ascii"),
        "completed_at_phase_version": 5,
    }
    member = promoted["phase_projection"]["members"][0]
    member["attempt_ledger"].append(ledger2)
    member.update(state="dev_completed", current_attempt=2, evidence_digest=retry_hash)
    promoted["phase_projection"]["events"].append({"phase_version": 5, "event_ordinal": 0, "member_id": TASK, "from_state": "retry_dispatched", "to_state": "dev_completed", "attempt": 2, "evidence_digest": retry_hash, "superseded_by": None, "coverage_disposition": None})
    promoted["phase_projection"]["phase_version"] = 5
    promoted["active_roster"][0].update(state="dev_completed")
    promoted = AGG.finalize_declaration(promoted)
    promotion_result = singular_update(promoted, reserved, retry_document)
    assert promotion_result["changed"] is True
    promoted_document = json.loads(canonical_path.read_text())
    assert promoted_document["implementation_notes"].startswith("attempt two")
    assert "artifact_sha256" not in promoted["phase_projection"]["members"][0]["attempt_ledger"][0]
    assert "artifact_sha256" not in ledger2
    assert base64.b64decode(promoted["phase_projection"]["members"][0]["attempt_ledger"][0]["stable_projection_utf8_base64"]) == original_projection

    awaiting = copy.deepcopy(promoted)
    awaiting["phase_projection"]["members"][0].update(state="awaiting_qa")
    awaiting["phase_projection"]["events"].append({"phase_version": 6, "event_ordinal": 0, "member_id": TASK, "from_state": "dev_completed", "to_state": "awaiting_qa", "attempt": 2, "evidence_digest": retry_hash, "superseded_by": None, "coverage_disposition": None})
    awaiting["phase_projection"]["phase_version"] = 6
    awaiting["active_roster"][0].update(state="awaiting_qa")
    awaiting = AGG.finalize_declaration(awaiting)
    singular_update(awaiting, promoted)

    passed_qa_raw = write_json(tmp_path / f"docs/dev/qa-report-{TASK}.json", qa_report(TASK))
    passed_digest = AGG._bytes_digest(passed_qa_raw)
    passed = copy.deepcopy(awaiting)
    passed["phase_projection"]["members"][0].update(state="qa_pass", evidence_digest=passed_digest)
    passed["phase_projection"]["events"].append({"phase_version": 7, "event_ordinal": 0, "member_id": TASK, "from_state": "awaiting_qa", "to_state": "qa_pass", "attempt": 2, "evidence_digest": passed_digest, "superseded_by": None, "coverage_disposition": None})
    passed["phase_projection"]["phase_version"] = 7
    passed["active_roster"][0].update(state="qa_pass")
    passed = AGG.finalize_declaration(passed)
    singular_update(passed, awaiting)

    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/resolve-dev-artifact-chain.py"), "--project-dir", str(tmp_path), "--task-id", TASK],
        text=True, capture_output=True,
    )
    assert proc.returncode == 0, proc.stdout
    result = json.loads(proc.stdout)
    assert result["status"] == "pass"
    # Full canonical hashes lawfully changed across declaration-only replacements,
    # while both retained exact stable projections remain independently rehashable.
    ledger = json.loads(canonical_path.read_text())["artifact_chain_declaration"]["phase_projection"]["members"][0]["attempt_ledger"]
    assert [row["attempt"] for row in ledger] == [1, 2]
    assert all(row["record_kind"] == "mutable_singular" and "artifact_sha256" not in row for row in ledger)
    assert not [path for path in canonical_path.parent.glob("*.json") if "iter2" in path.name]


def test_historical_sequential_fanout_preserves_distinct_member_baselines(tmp_path: Path) -> None:
    declaration, paths = make_final_chain(tmp_path, "requirement_fanout")
    paths["canonical"].unlink()
    historical = copy.deepcopy(declaration)
    historical["origin"] = "historical_recovery"
    historical["execution"] = "sequential"
    historical["baseline_policy"] = "per_member_dispatch"
    bindings: dict[str, dict] = {}
    raw_by_member: dict[str, bytes] = {}
    stable_by_member: dict[str, str] = {}
    for index, member in enumerate(historical["member_lineage"]):
        mid = member["member_id"]
        member["baseline_binding_key"] = mid
        baseline = {"head_sha": str(index + 1) * 40, "dirty_snapshot": "" if index == 0 else " M distinct.txt\n"}
        bindings[mid] = baseline
        report_path = tmp_path / member["artifact_paths"]["dev_report"]
        report = json.loads(report_path.read_text())
        report.pop("artifact_chain_binding")
        report.pop("artifact_chain_role")
        report["baseline_head_sha"] = baseline["head_sha"]
        report["baseline_dirty_snapshot"] = baseline["dirty_snapshot"]
        raw = write_json(report_path, report)
        raw_by_member[mid] = raw
        stable_by_member[mid] = AGG.stable_dev_projection(report)[1]
    historical["baseline_bindings"] = {"shared": None, "by_member": bindings}
    historical["inventory_digest"] = AGG._digest(historical["inventory"])
    historical["lineage_digest"] = AGG._digest({key: historical[key] for key in ("schema_version", "parent_task_id", "shape", "execution", "origin", "member_lineage", "inventory", "inventory_digest", "baseline_policy", "baseline_bindings")})
    phase_members = historical["phase_projection"]["members"]
    for member in phase_members:
        mid = member["member_id"]
        member["attempt_reservations"][0]["expected_absent"] = False
        row = member["attempt_ledger"][0]
        row["artifact_sha256"] = AGG._bytes_digest(raw_by_member[mid])
        row["stable_projection_sha256"] = stable_by_member[mid]
    for event in historical["phase_projection"]["events"]:
        if event["to_state"] in {"dev_completed", "awaiting_qa"}:
            row = next(member["attempt_ledger"][0] for member in phase_members if member["member_id"] == event["member_id"])
            event["evidence_digest"] = row["artifact_sha256"]
        if event["to_state"] == "awaiting_qa":
            member = next(member for member in phase_members if member["member_id"] == event["member_id"])
            # This is the evidence folded into the pre-QA member state only.
            member.setdefault("_unused", None)
    for member in phase_members:
        # Final members retain QA evidence from their qa_pass events.
        member.pop("_unused", None)
    # Adopt the second immutable report while bootstrapping that historical
    # member as phase-0 superseded. Its ledger remains audit-visible without a
    # fabricated dev_completed event.
    superseded_id = historical["member_lineage"][1]["member_id"]
    replacement_id = historical["member_lineage"][0]["member_id"]
    audit_digest = AGG._digest({
        "member_id": superseded_id, "superseded_by": replacement_id,
        "coverage_disposition": None,
    })
    initial_event = next(
        event for event in historical["phase_projection"]["events"]
        if event["member_id"] == superseded_id and event["phase_version"] == 0
    )
    initial_event.update(
        to_state="superseded", evidence_digest=audit_digest,
        superseded_by=replacement_id,
    )
    historical["phase_projection"]["events"] = [
        event for event in historical["phase_projection"]["events"]
        if event["member_id"] != superseded_id or event["phase_version"] == 0
    ]
    superseded_member = next(member for member in phase_members if member["member_id"] == superseded_id)
    superseded_member.update(
        state="superseded", evidence_digest=audit_digest,
        superseded_by=replacement_id,
    )
    superseded_member["attempt_ledger"][0]["completed_at_phase_version"] = 0
    historical["active_roster"] = [
        row for row in historical["active_roster"] if row["member_id"] != superseded_id
    ]
    historical["excluded_roster"] = [{
        "ordinal": 1, "member_id": superseded_id, "state": "superseded",
        "attempt": 1, "evidence_digest": audit_digest,
        "superseded_by": replacement_id,
    }]
    historical = AGG.finalize_declaration(historical)
    outcome = AGG.apply_artifact_chain_declaration(
        tmp_path, TASK, historical, operation="default_aggregate", expect_canonical_absent=True,
    )
    assert outcome["status"] == "ok", outcome
    canonical = json.loads(paths["canonical"].read_text())
    assert canonical["baseline_head_sha"] is None
    assert canonical["baseline_dirty_snapshot"] is None
    assert canonical["artifact_chain_evidence"]["baseline_evidence"]["by_member"] == bindings
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/resolve-dev-artifact-chain.py"), "--project-dir", str(tmp_path), "--task-id", TASK],
        text=True, capture_output=True,
    )
    assert proc.returncode == 0, proc.stdout
    result = json.loads(proc.stdout)
    assert result["execution"] == "sequential"
    assert result["baseline_evidence"]["by_member"] == bindings
    assert result["excluded_lanes"][0]["member_id"] == superseded_id
    assert result["excluded_lanes"][0]["attempt_history"][0]["completed_at_phase_version"] == 0


def test_malformed_attempt_schema_matrix_fails_closed_without_exception(tmp_path: Path) -> None:
    declaration, _ = make_final_chain(tmp_path, "singular")
    member_path = ("phase_projection", "members", 0)

    def mutate(path: tuple, *, missing: bool = False, value=None) -> dict:
        candidate = copy.deepcopy(declaration)
        target = candidate
        for part in path[:-1]:
            target = target[part]
        if missing:
            target.pop(path[-1])
        else:
            target[path[-1]] = value
        return candidate

    cases: list[dict] = []
    for field in ("attempt_storage", "attempt_reservations", "attempt_ledger", "current_attempt"):
        cases.append(mutate(member_path + (field,), missing=True))
        cases.append(mutate(member_path + (field,), value=None))
    for field in ("schema_version", "attempt", "artifact_path", "expected_absent", "reserved_at_phase_version"):
        cases.append(mutate(member_path + ("attempt_reservations", 0, field), missing=True))
        cases.append(mutate(member_path + ("attempt_reservations", 0, field), value=None))
    for field in AGG.MUTABLE_LEDGER_FIELDS:
        cases.append(mutate(member_path + ("attempt_ledger", 0, field), missing=True))
        cases.append(mutate(member_path + ("attempt_ledger", 0, field), value=None))
    for bad in (True, 1.0, "1", 0, -1, AGG.INT_MAX + 1):
        cases.append(mutate(member_path + ("current_attempt",), value=bad))
    cases.extend([
        mutate(("shape",), value=[]),
        mutate(("baseline_policy",), value={}),
        mutate(member_path + ("attempt_ledger", 0, "stable_projection_utf8_base64"), value="!!!!"),
    ])
    for candidate in cases:
        normalized, errors = AGG.validate_declaration(candidate, TASK)
        assert normalized is None
        assert errors and errors[0]["code"] in {
            "INVALID_DECLARATION", "INVALID_PHASE_TRANSITION",
            "INVENTORY_MISMATCH", "MISSING_BASELINE_BINDING",
        }


def test_parallel_outcomes_require_qa_status_to_agree_with_expansion(tmp_path: Path) -> None:
    declaration, _ = make_final_chain(tmp_path, "parallel_dev")
    events = declaration["phase_projection"]["events"]
    prefix = [event for event in events if event["phase_version"] < 3]
    members = []
    for member in declaration["phase_projection"]["members"]:
        ledger = member["attempt_ledger"][-1]
        members.append({**member, "state": "awaiting_qa", "evidence_digest": ledger["artifact_sha256"]})
    before = copy.deepcopy(declaration)
    before["phase_projection"] = {
        "phase_version": 2, "members": members, "events": prefix, "phase_digest": "",
    }
    before = AGG.finalize_declaration(before)
    outcomes = {
        "schema_version": AGG.OUTCOMES_VERSION, "parent_task_id": TASK,
        "lineage_digest": before["lineage_digest"],
        "phase_digest_before": before["phase_projection"]["phase_digest"],
        "coverage": "all", "default_outcome": None,
        "worker_outcomes": [
            {"member_id": member["member_id"], "outcome": "needs_review"}
            for member in before["member_lineage"]
        ],
    }
    expanded, errors = AGG.validate_parallel_worker_outcomes(
        qa_report(TASK, outcomes=outcomes, status="pass"), before,
    )
    assert expanded is None
    assert errors == [{
        "code": "INVALID_STATUS", "path": "qa.status",
        "message": "parallel parent QA status must be 'needs_review' for the expanded worker outcomes",
    }]


def test_existing_declarationless_parallel_requires_inject_not_default_overwrite(tmp_path: Path) -> None:
    declaration, paths = make_final_chain(tmp_path, "parallel_dev")
    canonical = json.loads(paths["canonical"].read_text())
    canonical.pop("artifact_chain_declaration")
    before = write_json(paths["canonical"], canonical)
    sha = hashlib.sha256(before).hexdigest()
    rejected = AGG.apply_artifact_chain_declaration(
        tmp_path, TASK, declaration, operation="default_aggregate",
        expected_canonical_sha256=sha,
    )
    assert rejected["status"] == "fail"
    assert rejected["errors"][0]["code"] == "DECLARATION_CONFLICT"
    assert paths["canonical"].read_bytes() == before
    injected = AGG.apply_artifact_chain_declaration(
        tmp_path, TASK, declaration, operation="inject_only",
        expected_canonical_sha256=sha,
    )
    assert injected["status"] == "ok", injected
    assert json.loads(paths["canonical"].read_text())["artifact_chain_declaration"] == declaration


def test_competing_absent_aggregate_writers_have_exactly_one_winner(tmp_path: Path) -> None:
    declaration, paths = make_final_chain(tmp_path, "parallel_dev")
    paths["canonical"].unlink()
    candidate = tmp_path / "candidate.json"
    candidate.write_bytes(AGG._canonical_bytes(declaration))
    command = [
        sys.executable, str(AGG_PATH), "--project-dir", str(tmp_path),
        "--task-id", TASK, "--declaration-file", str(candidate),
        "--expect-canonical-absent",
    ]
    processes = [subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
    results = []
    try:
        for process in processes:
            stdout, stderr = process.communicate(timeout=15)
            results.append((process.returncode, json.loads(stdout), stderr))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()
    assert sorted(returncode for returncode, _, _ in results) == [0, 2]
    assert sum(result["changed"] is True for _, result, _ in results) == 1
    loser = next(result for code, result, _ in results if code == 2)
    assert loser["errors"][0]["code"] == "CANONICAL_ALREADY_EXISTS"
    resolved = subprocess.run(
        [sys.executable, str(ROOT / "scripts/resolve-dev-artifact-chain.py"), "--project-dir", str(tmp_path), "--task-id", TASK],
        text=True, capture_output=True,
    )
    assert resolved.returncode == 0, resolved.stdout
