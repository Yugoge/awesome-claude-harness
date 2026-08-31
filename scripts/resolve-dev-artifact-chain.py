#!/usr/bin/env python3
"""Read-only resolver/preflight for declared dev artifact chains.

Shape, relationships, paths, lineage and phase are read only from the validated
embedded declaration.  Normal resolution and parent preflight never write.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

RESULT_VERSION = "artifact_chain_result.v2"
PREFLIGHT_VERSION = "artifact_chain_preflight.v1"
IDENTITY_RE = re.compile(r"^(?:[-*+]\s*)?(?:task[- ]id|request[- ]id)\s*:\s*(\S+)\s*$", re.IGNORECASE)


class StableArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def _load_aggregate_module() -> ModuleType:
    path = Path(__file__).with_name("aggregate-dev-report.py")
    module = ModuleType("_artifact_chain_provider")
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module


AGG = _load_aggregate_module()


def _error(code: str, path: str, message: str, parent_task_id: str | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"code": code, "path": path, "message": message}
    if parent_task_id is not None:
        value["parent_task_id"] = parent_task_id
    return value


def _empty_parent() -> dict[str, Any]:
    return {"task_id": None, "ticket": None, "context": None, "canonical_dev_report": None, "qa_report": None, "completion": None}


def _base_result(project_root: str, input_task_id: str) -> dict[str, Any]:
    return {
        "schema_version": RESULT_VERSION, "status": "fail",
        "project_root": project_root, "input_task_id": input_task_id,
        "parent_task_id": None, "task_id": None, "shape": None, "mode": None,
        "execution": None, "origin": None, "lineage_digest": None,
        "phase_version": None, "phase_digest": None, "parent": _empty_parent(),
        "canonical_dev_report": None, "completion": None, "lanes": [],
        "excluded_lanes": [], "active_roster": [], "excluded_roster": [],
        "parallel_workers": [], "report_paths": [], "artifact_paths": [],
        "commit_whitelist_artifacts": [], "qa_inputs": [],
        "baseline_evidence": None,
        "checks": {
            "declaration_valid": False, "canonical_fresh": False,
            "file_unions_exact": False, "declared_paths_exist": False,
            "baselines_valid": False, "phase_final": False,
        },
        "errors": [],
    }


def _base_preflight(project_root: str, input_task_id: str) -> dict[str, Any]:
    return {
        "schema_version": PREFLIGHT_VERSION, "status": "fail",
        "project_root": project_root, "input_task_id": input_task_id,
        "parent_task_id": None, "shape": None, "canonical_state": "unknown",
        "canonical_path": None, "canonical_sha256": None,
        "declaration_digest": None, "lineage_digest": None,
        "phase_digest": None, "errors": [],
    }


class ChainValidator:
    """Frozen nested-status validator used by SCHEMA compatibility tests."""
    def __init__(self, project_root: Path, task_id: str) -> None:
        self.root = Path(project_root)
        self.task_id = task_id
        self.errors: list[dict[str, str]] = []

    def validate_dev(self, value: dict[str, Any], expected: str, path: Path) -> None:
        relative = path.as_posix()
        for key in ("request_id", "task_id"):
            if value.get(key) != expected:
                self.errors.append(_error("INVALID_IDENTITY", relative, f"{key} mismatch"))
        dev = value.get("dev")
        if not isinstance(dev, dict) or dev.get("status") != "completed":
            self.errors.append(_error("INVALID_STATUS", relative, "dev.status must be completed"))
        elif (not isinstance(dev.get("files_modified"), list)
              or not isinstance(dev.get("files_created"), list)):
            self.errors.append(_error("INVALID_STATUS", relative, "nested file lists must be arrays"))
        blockers = value.get("blocking_issues", [])
        if not isinstance(blockers, list) or blockers:
            self.errors.append(_error("UNRESOLVED_BLOCKERS", relative, "blocking_issues must be an empty array"))


def _canonical_path(root: Path, task_id: str) -> tuple[str, Path]:
    relative = f"docs/dev/dev-report-{task_id}.json"
    return relative, root / relative


def _read_json(root: Path, relative: str, errors: list[dict[str, Any]], *, required: bool = True) -> tuple[dict[str, Any] | None, bytes | None]:
    try:
        raw = AGG._read_regular_file_bytes(root, relative)
        return AGG.load_json_bytes(raw, relative), raw
    except AGG.ContractFailure as exc:
        for item in exc.errors:
            if not required and item["code"] == "MISSING_ARTIFACT":
                continue
            code = "INVALID_DECLARATION" if item["code"] == "INVALID_DECLARATION" else item["code"]
            errors.append(_error(code, item["path"], item["message"]))
    return None, None


def _read_text(root: Path, relative: str, errors: list[dict[str, Any]], *, required: bool = True) -> str | None:
    try:
        raw = AGG._read_regular_file_bytes(root, relative)
        text = raw.decode("utf-8", errors="strict")
    except AGG.ContractFailure as exc:
        for item in exc.errors:
            if required or item["code"] != "MISSING_ARTIFACT":
                errors.append(_error(item["code"], item["path"], item["message"]))
        return None
    except UnicodeDecodeError as exc:
        errors.append(_error("IO_ERROR", relative, str(exc)))
        return None
    if not text.strip():
        errors.append(_error("INVALID_STATUS", relative, "Markdown artifact is empty"))
        return None
    return text


def _json_identity(value: dict[str, Any], expected: str, path: str, errors: list[dict[str, Any]]) -> None:
    for field in ("request_id", "task_id"):
        if value.get(field) != expected:
            errors.append(_error("INVALID_IDENTITY", path, f"{field} is {value.get(field)!r}; expected {expected!r}"))


def _markdown_identity(text: str, expected: str, path: str, errors: list[dict[str, Any]]) -> None:
    found: list[str] = []
    for line in text.splitlines():
        match = IDENTITY_RE.fullmatch(line.strip().replace("**", "").replace("`", ""))
        if match:
            found.append(match.group(1))
    if not found:
        errors.append(_error("INVALID_IDENTITY", path, "no exact Task ID / Request ID metadata found"))
    for value in found:
        if value != expected:
            errors.append(_error("INVALID_IDENTITY", path, f"metadata identity is {value!r}; expected {expected!r}"))


def _preflight_candidate(root: Path, input_task_id: str) -> tuple[dict[str, Any] | None, bytes | None, list[dict[str, Any]]]:
    relative, _ = _canonical_path(root, input_task_id)
    errors: list[dict[str, Any]] = []
    report, raw = _read_json(root, relative, errors, required=False)
    if report is None:
        return None, raw, errors
    declaration = report.get("artifact_chain_declaration")
    if not isinstance(declaration, dict):
        role = report.get("artifact_chain_role")
        code = "NON_LIFECYCLE_REPORT" if role == "overnight_pipeline_intermediate" else "MISSING_DECLARATION"
        errors.append(_error(code, relative, "report is not a lifecycle parent canonical with an embedded declaration"))
        return None, raw, errors
    normalized, declaration_errors = AGG.validate_declaration(declaration, input_task_id)
    errors.extend(_error(item["code"], item["path"], item["message"]) for item in declaration_errors)
    if normalized is None:
        return None, raw, errors
    if report.get("artifact_chain_role") == "overnight_pipeline_intermediate":
        errors.append(_error("NON_LIFECYCLE_REPORT", relative, "overnight pipeline intermediates are not lifecycle parent canonicals"))
        return None, raw, errors
    return normalized, raw, errors


def _reverse_parent_matches(root: Path, input_task_id: str) -> list[tuple[str, str, dict[str, Any], bytes]]:
    """Bounded exact reverse lookup over digest-valid embedded parent canonicals."""
    dev_dir = root / "docs" / "dev"
    matches: list[tuple[str, str, dict[str, Any], bytes]] = []
    try:
        children = list(dev_dir.iterdir())
    except OSError:
        return matches
    for path in children:
        if not path.is_file() or path.is_symlink() or not path.name.startswith("dev-report-") or not path.name.endswith(".json"):
            continue
        relative = f"docs/dev/{path.name}"
        try:
            raw = AGG._read_regular_file_bytes(root, relative)
            report = AGG.load_json_bytes(raw, relative)
        except AGG.ContractFailure:
            continue
        declaration = report.get("artifact_chain_declaration")
        parent = declaration.get("parent_task_id") if isinstance(declaration, dict) else None
        if not isinstance(parent, str) or parent == input_task_id:
            continue
        normalized, errors = AGG.validate_declaration(declaration, parent)
        if errors or normalized is None:
            continue
        canonical_entry = next((entry for entry in normalized["inventory"] if entry["kind"] == "canonical_dev_report" and entry["member_id"] is None), None)
        if canonical_entry is None or canonical_entry["path"] != relative:
            continue
        if any(member["member_id"] == input_task_id for member in normalized["member_lineage"]):
            matches.append((parent, relative, normalized, raw))
    matches.sort(key=lambda row: row[0].encode("utf-8"))
    return matches


def preflight_parent(project_root: Path | str, input_task_id: str) -> dict[str, Any]:
    root, root_errors = AGG._valid_root(project_root)
    root_text = str(root) if root is not None else str(Path(project_root).resolve(strict=False))
    result = _base_preflight(root_text, input_task_id)
    if root is None:
        result["canonical_state"] = "unknown"
        result["errors"] = [_error(item["code"], item["path"], item["message"]) for item in root_errors]
        return result
    if not AGG._safe_task_id(input_task_id):
        result["errors"] = [_error("INVALID_ARGUMENT", "task_id", "task id must be an exact safe non-empty component")]
        return result
    direct, raw, direct_errors = _preflight_candidate(root, input_task_id)
    if direct is not None and raw is not None:
        relative, _ = _canonical_path(root, input_task_id)
        result.update(
            status="ready", parent_task_id=input_task_id, shape=direct["shape"],
            canonical_state="present", canonical_path=relative,
            canonical_sha256=hashlib.sha256(raw).hexdigest(),
            declaration_digest=direct["declaration_digest"],
            lineage_digest=direct["lineage_digest"],
            phase_digest=direct["phase_projection"]["phase_digest"], errors=[],
        )
        return result
    matches = _reverse_parent_matches(root, input_task_id)
    if len(matches) == 1:
        parent, relative, declaration, parent_raw = matches[0]
        result.update(
            status="redirect", parent_task_id=parent, shape=declaration["shape"],
            canonical_state="present", canonical_path=relative,
            canonical_sha256=hashlib.sha256(parent_raw).hexdigest(),
            declaration_digest=declaration["declaration_digest"],
            lineage_digest=declaration["lineage_digest"],
            phase_digest=declaration["phase_projection"]["phase_digest"],
            errors=[_error("PARENT_TASK_ID_REQUIRED", relative, f"{input_task_id!r} is a declared member; close the exact parent {parent!r}", parent)],
        )
        return result
    if len(matches) > 1:
        result.update(
            status="fail", canonical_state="invalid",
            errors=[_error("AMBIGUOUS_PARENT_MEMBERSHIP", "docs/dev", f"input member has multiple digest-valid parents: {[m[0] for m in matches]}")],
        )
        return result
    direct_rel, direct_path = _canonical_path(root, input_task_id)
    exists = direct_path.is_file()
    result.update(
        status="repair_required", parent_task_id=input_task_id,
        canonical_state="invalid" if exists else "absent",
        canonical_path=direct_rel,
        canonical_sha256=hashlib.sha256(raw).hexdigest() if raw is not None else None,
        errors=direct_errors or [_error("CANONICAL_NOT_FOUND", direct_rel, "no declared lifecycle parent canonical exists; audited LANE-F repair is required")],
    )
    return result


def _inventory_maps(declaration: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    parent: dict[str, dict[str, Any]] = {}
    members: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in declaration["inventory"]:
        if entry["member_id"] is None:
            parent[entry["kind"]] = entry
        else:
            members[(entry["member_id"], entry["kind"])] = entry
    return parent, members


def _present(root: Path, relative: str) -> bool:
    try:
        AGG._inspect_regular_file_beneath(root, relative)
        return True
    except AGG.ContractFailure:
        return False


def _phase_member_map(declaration: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["member_id"]: item for item in declaration["phase_projection"]["members"]}


def _row_for_member(root: Path, declaration: dict[str, Any], member: dict[str, Any], phase: dict[str, Any], excluded: bool) -> dict[str, Any]:
    paths = member["artifact_paths"]
    current = AGG._member_current_row(phase)
    dev_path = current["artifact_path"] if current is not None else paths["dev_report"]
    row: dict[str, Any] = {
        "lineage_ordinal": member["lineage_ordinal"], "member_kind": member["member_kind"],
        "member_id": member["member_id"], "task_id": member["member_id"],
        "phase_state": phase["state"], "attempt": phase["attempt"],
        "lineage_digest": declaration["lineage_digest"],
        "ticket": paths["ticket"], "context": paths["context"],
        "dev_report": dev_path, "qa_report": paths["qa_report"],
        "present_artifact_paths": [path for path in (paths["ticket"], paths["context"], dev_path, paths["qa_report"]) if path is not None and _present(root, path)],
        "attempt_history": copy.deepcopy(phase["attempt_ledger"]),
    }
    if excluded:
        row["superseded_evidence_digest"] = phase["evidence_digest"]
        row["superseded_by"] = phase["superseded_by"]
    return row


def _populate_relationships(result: dict[str, Any], root: Path, declaration: dict[str, Any]) -> None:
    shape = declaration["shape"]
    parent_inventory, _ = _inventory_maps(declaration)
    kind_field = {
        "parent_ticket": "ticket", "parent_context": "context",
        "canonical_dev_report": "canonical_dev_report", "parent_qa_report": "qa_report",
        "parent_completion": "completion",
    }
    parent = {"task_id": declaration["parent_task_id"], "ticket": None, "context": None, "canonical_dev_report": None, "qa_report": None, "completion": None}
    for kind, field in kind_field.items():
        entry = parent_inventory.get(kind)
        if entry is not None:
            parent[field] = entry["path"]
    phase_by_id = _phase_member_map(declaration)
    active_rows: list[dict[str, Any]] = []
    excluded_rows: list[dict[str, Any]] = []
    if shape != "singular":
        for member in declaration["member_lineage"]:
            phase = phase_by_id[member["member_id"]]
            row = _row_for_member(root, declaration, member, phase, phase["state"] == "superseded")
            (excluded_rows if phase["state"] == "superseded" else active_rows).append(row)
    qa_inputs: list[dict[str, Any]] = []
    if shape in {"singular", "parallel_dev"} and parent["qa_report"] is not None:
        qa_inputs.append({"scope": "parent", "member_id": None, "task_id": declaration["parent_task_id"], "qa_report": parent["qa_report"]})
    elif shape == "requirement_fanout":
        qa_inputs = [{"scope": "member", "member_id": row["member_id"], "task_id": row["task_id"], "qa_report": row["qa_report"]} for row in active_rows]
    report_paths = [parent["canonical_dev_report"]]
    if shape == "parallel_dev":
        report_paths.extend(row["dev_report"] for row in active_rows)
    elif shape == "requirement_fanout":
        for row in active_rows:
            report_paths.extend((row["dev_report"], row["qa_report"]))
    if parent["qa_report"] is not None and (shape != "requirement_fanout" or _present(root, parent["qa_report"])):
        report_paths.append(parent["qa_report"])
    artifact_paths = [entry["path"] for entry in declaration["inventory"] if _present(root, entry["path"])]
    # Promoted immutable retry paths extend the union without rewriting base inventory.
    inventory_set = set(artifact_paths)
    for phase in declaration["phase_projection"]["members"]:
        for ledger in phase["attempt_ledger"]:
            path = ledger["artifact_path"]
            if _present(root, path) and path not in inventory_set:
                artifact_paths.append(path)
                inventory_set.add(path)
    result.update(
        parent_task_id=declaration["parent_task_id"], task_id=declaration["parent_task_id"],
        shape=shape, mode=AGG.MODE_BY_SHAPE[shape], execution=declaration["execution"],
        origin=declaration["origin"], lineage_digest=declaration["lineage_digest"],
        phase_version=declaration["phase_projection"]["phase_version"],
        phase_digest=declaration["phase_projection"]["phase_digest"], parent=parent,
        canonical_dev_report=parent["canonical_dev_report"], completion=parent["completion"],
        lanes=active_rows, excluded_lanes=excluded_rows,
        active_roster=copy.deepcopy(declaration["active_roster"]),
        excluded_roster=copy.deepcopy(declaration["excluded_roster"]),
        parallel_workers=[row["member_id"] for row in active_rows],
        report_paths=report_paths, artifact_paths=artifact_paths,
        commit_whitelist_artifacts=copy.deepcopy(artifact_paths), qa_inputs=qa_inputs,
        baseline_evidence={"policy": declaration["baseline_policy"], **copy.deepcopy(declaration["baseline_bindings"])},
    )


def _validate_dev_document(root: Path, report: dict[str, Any], expected: str, path: str, errors: list[dict[str, Any]]) -> bool:
    _json_identity(report, expected, path, errors)
    AGG._dev_status(report, path, errors)
    return AGG._validate_declared_repo_paths(root, report, path, errors) is not None


def _validate_qa_document(report: dict[str, Any], expected: str, path: str, errors: list[dict[str, Any]], *, require_pass: bool = True) -> None:
    _json_identity(report, expected, path, errors)
    qa = report.get("qa")
    status = qa.get("status") if isinstance(qa, dict) else None
    if require_pass and status != "pass":
        errors.append(_error("INVALID_STATUS", path, f"qa.status is {status!r}; expected 'pass'"))


def _event_evidence_checks(root: Path, declaration: dict[str, Any], errors: list[dict[str, Any]]) -> None:
    events = declaration["phase_projection"]["events"]
    phase_by_id = _phase_member_map(declaration)
    for member in declaration["member_lineage"]:
        phase = phase_by_id[member["member_id"]]
        for ledger in phase["attempt_ledger"]:
            evidence = ledger.get("artifact_sha256", ledger["stable_projection_sha256"])
            historical_superseded_adoption = (
                declaration["origin"] == "historical_recovery"
                and phase["state"] == "superseded"
                and ledger["attempt"] == 1
                and ledger["completed_at_phase_version"] == 0
            )
            completed = [e for e in events if e["member_id"] == member["member_id"] and e["attempt"] == ledger["attempt"] and e["to_state"] == "dev_completed"]
            if not historical_superseded_adoption and (len(completed) != 1 or completed[0]["phase_version"] != ledger["completed_at_phase_version"] or completed[0]["evidence_digest"] != evidence):
                errors.append(_error("INVALID_PHASE_TRANSITION", ledger["artifact_path"], "ledger promotion does not have one exact dev_completed evidence event"))
            awaiting = [e for e in events if e["member_id"] == member["member_id"] and e["attempt"] == ledger["attempt"] and e["to_state"] == "awaiting_qa"]
            if awaiting and any(e["evidence_digest"] != evidence for e in awaiting):
                errors.append(_error("INVALID_PHASE_TRANSITION", ledger["artifact_path"], "awaiting_qa evidence does not equal the attempt ledger digest"))
        for reservation in phase["attempt_reservations"][1:]:
            retry = [e for e in events if e["member_id"] == member["member_id"] and e["attempt"] == reservation["attempt"] and e["to_state"] == "retry_dispatched"]
            if len(retry) != 1 or retry[0]["phase_version"] != reservation["reserved_at_phase_version"]:
                errors.append(_error("INVALID_PHASE_TRANSITION", reservation["artifact_path"], "retry reservation must be atomic with its exact retry_dispatched event"))


def _validate_required_inventory(root: Path, declaration: dict[str, Any], errors: list[dict[str, Any]]) -> None:
    excluded = {m["member_id"] for m in declaration["phase_projection"]["members"] if m["state"] == "superseded"}
    for entry in declaration["inventory"]:
        required = entry["required"] and entry["member_id"] not in excluded
        try:
            AGG._inspect_regular_file_beneath(root, entry["path"])
        except AGG.ContractFailure as exc:
            for item in exc.errors:
                if required or item["code"] != "MISSING_ARTIFACT":
                    errors.append(_error(item["code"], item["path"], item["message"]))


def _validate_report_baseline(report: dict[str, Any], declaration: dict[str, Any], member_id: str, path: str, errors: list[dict[str, Any]]) -> None:
    expected = AGG._baseline_for(declaration, member_id)
    dirty = report.get("baseline_dirty_snapshot")
    if report.get("baseline_head_sha") != expected["head_sha"] or not isinstance(dirty, str) or dirty.encode("utf-8") != expected["dirty_snapshot"].encode("utf-8"):
        errors.append(_error("BASELINE_MISMATCH", path, "head/dirty baseline evidence does not byte-match the immutable declaration binding"))


def _prior_parallel_qa_declaration(declaration: dict[str, Any]) -> dict[str, Any] | None:
    events = declaration["phase_projection"]["events"]
    qa_events = [e for e in events if e["to_state"] in {"qa_pass", "needs_review"}]
    if not qa_events:
        return None
    version = max(e["phase_version"] for e in qa_events)
    prefix = [copy.deepcopy(e) for e in events if e["phase_version"] < version]
    states: dict[str, dict[str, Any]] = {}
    for event in prefix:
        states[event["member_id"]] = {
            "member_id": event["member_id"], "state": event["to_state"],
            "attempt": event["attempt"], "evidence_digest": event["evidence_digest"],
            "superseded_by": event["superseded_by"],
        }
    prior = copy.deepcopy(declaration)
    current_attempts = {m["member_id"]: m for m in declaration["phase_projection"]["members"]}
    members = []
    for lineage in declaration["member_lineage"]:
        member_id = lineage["member_id"]
        if member_id not in states:
            return None
        attempt_data = current_attempts[member_id]
        members.append({**states[member_id], **{key: copy.deepcopy(attempt_data[key]) for key in ("attempt_storage", "attempt_reservations", "attempt_ledger", "current_attempt")}})
    phase_version = version - 1
    prior["phase_projection"] = {"phase_version": phase_version, "members": members, "events": prefix, "phase_digest": ""}
    prior["phase_projection"]["phase_digest"] = AGG._digest({"lineage_digest": prior["lineage_digest"], "phase_version": phase_version, "members": members, "events": prefix})
    return prior


def _validate_shape_artifacts(root: Path, result: dict[str, Any], declaration: dict[str, Any], canonical: dict[str, Any], canonical_raw: bytes, errors: list[dict[str, Any]]) -> bool:
    shape = declaration["shape"]
    parent = result["parent"]
    declared_paths_valid = _validate_dev_document(root, canonical, declaration["parent_task_id"], parent["canonical_dev_report"], errors)
    if canonical.get("artifact_chain_declaration") != declaration:
        errors.append(_error("DECLARATION_CONFLICT", parent["canonical_dev_report"], "canonical embedded declaration changed after validation"))
    if canonical.get("artifact_chain_role") == "overnight_pipeline_intermediate":
        errors.append(_error("NON_LIFECYCLE_REPORT", parent["canonical_dev_report"], "overnight intermediate cannot resolve as a lifecycle parent"))
    if (shape == "singular" and declaration["origin"] == "active_lifecycle"
            and canonical.get("artifact_chain_role") != "lifecycle_singular_parent"):
        errors.append(_error("INVALID_IDENTITY", parent["canonical_dev_report"], "active singular canonical requires artifact_chain_role=lifecycle_singular_parent"))
    phase_by_id = _phase_member_map(declaration)
    if shape == "singular":
        AGG._validate_mutable_singular_current(canonical, declaration, errors)
        _validate_report_baseline(canonical, declaration, declaration["parent_task_id"], parent["canonical_dev_report"], errors)
    sources: list[tuple[str, dict[str, Any], bytes]] = []
    row_by_id = {row["member_id"]: row for row in result["lanes"] + result["excluded_lanes"]}
    for member in declaration["member_lineage"]:
        phase = phase_by_id[member["member_id"]]
        if member["member_kind"] == "singular_parent":
            continue
        row = row_by_id[member["member_id"]]
        required = phase["state"] != "superseded"
        report, raw = _read_json(root, row["dev_report"], errors, required=required)
        if report is None or raw is None:
            if required:
                declared_paths_valid = False
            continue
        if not _validate_dev_document(root, report, member["member_id"], row["dev_report"], errors):
            declared_paths_valid = False
        _validate_report_baseline(report, declaration, member["member_id"], row["dev_report"], errors)
        binding = report.get("artifact_chain_binding")
        expected_binding = {"parent_task_id": declaration["parent_task_id"], "member_id": member["member_id"], "lineage_digest": declaration["lineage_digest"], "attempt": phase["current_attempt"]}
        reservation = phase["attempt_reservations"][phase["current_attempt"] - 1] if phase["current_attempt"] is not None else None
        historical_adoption = declaration["origin"] == "historical_recovery" and phase["current_attempt"] == 1 and reservation is not None and reservation["expected_absent"] is False
        if historical_adoption:
            if binding is not None and (report.get("artifact_chain_role") != "lifecycle_declared_member" or binding != expected_binding):
                errors.append(_error("INVALID_IDENTITY", row["dev_report"], "present historical member binding mismatch"))
        elif report.get("artifact_chain_role") != "lifecycle_declared_member" or binding != expected_binding:
            errors.append(_error("INVALID_IDENTITY", row["dev_report"], "member role/binding is not the exact current immutable lineage binding"))
        if required:
            sources.append((member["member_id"], report, raw))
    if shape in {"parallel_dev", "requirement_fanout"} and len(sources) == len(result["lanes"]):
        expected = AGG._build_aggregate(sources, declaration["parent_task_id"], declaration, timestamp=canonical.get("timestamp"))
        result["checks"]["canonical_fresh"] = AGG._canonical_projection(canonical) == AGG._canonical_projection(expected)
        result["checks"]["file_unions_exact"] = canonical.get("dev", {}).get("files_modified") == expected["dev"]["files_modified"] and canonical.get("dev", {}).get("files_created") == expected["dev"]["files_created"]
        if not result["checks"]["file_unions_exact"]:
            errors.append(_error("STALE_FILE_UNION", parent["canonical_dev_report"], "canonical file union differs from current declared source reports"))
        if not result["checks"]["canonical_fresh"]:
            errors.append(_error("STALE_CANONICAL", parent["canonical_dev_report"], "canonical deterministic projection differs from declaration-bound sources"))
    elif shape == "singular":
        result["checks"]["canonical_fresh"] = True
        result["checks"]["file_unions_exact"] = True
    # Parent ticket/context (required for singular/parallel, optional-present for fanout).
    for field in ("ticket", "context"):
        path = parent[field]
        if path is None:
            continue
        required = shape != "requirement_fanout"
        if field == "ticket":
            text = _read_text(root, path, errors, required=required)
            if text is not None:
                _markdown_identity(text, declaration["parent_task_id"], path, errors)
        else:
            value, _ = _read_json(root, path, errors, required=required)
            if value is not None:
                _json_identity(value, declaration["parent_task_id"], path, errors)
    # Lane ticket/context/QA.
    qa_documents: dict[str, tuple[dict[str, Any], bytes]] = {}
    for row in result["lanes"] + result["excluded_lanes"]:
        required = row["phase_state"] != "superseded"
        for field in ("ticket", "context"):
            path = row[field]
            if path is None:
                continue
            if field == "ticket":
                text = _read_text(root, path, errors, required=required)
                if text is not None:
                    _markdown_identity(text, row["member_id"], path, errors)
            else:
                value, _ = _read_json(root, path, errors, required=required)
                if value is not None:
                    _json_identity(value, row["member_id"], path, errors)
        qa_path = row["qa_report"]
        if qa_path is not None:
            qa, qa_raw = _read_json(root, qa_path, errors, required=required)
            if qa is not None and qa_raw is not None:
                if "parallel_dev_worker_outcomes" in qa:
                    errors.append(_error("INVALID_STATUS", qa_path, "parallel worker outcome object is forbidden outside parallel-dev parent QA"))
                _validate_qa_document(qa, row["member_id"], qa_path, errors, require_pass=required)
                qa_documents[row["member_id"]] = (qa, qa_raw)
    parent_qa: tuple[dict[str, Any], bytes] | None = None
    if parent["qa_report"] is not None:
        qa, qa_raw = _read_json(
            root, parent["qa_report"], errors,
            required=shape != "requirement_fanout",
        )
        if qa is not None and qa_raw is not None:
            _validate_qa_document(qa, declaration["parent_task_id"], parent["qa_report"], errors)
            parent_qa = (qa, qa_raw)
            if shape == "parallel_dev":
                before = _prior_parallel_qa_declaration(declaration)
                if before is None:
                    errors.append(_error("INVALID_PHASE_TRANSITION", parent["qa_report"], "cannot derive parent-QA pre-transition phase"))
                else:
                    expanded, outcome_errors = AGG.validate_parallel_worker_outcomes(qa, before)
                    errors.extend(_error(item["code"], parent["qa_report"], item["message"]) for item in outcome_errors)
                    if expanded is not None and any(value != "pass" for value in expanded.values()):
                        errors.append(_error("INVALID_STATUS", parent["qa_report"], "final parent QA outcomes must agree with all active qa_pass states"))
            elif "parallel_dev_worker_outcomes" in qa:
                errors.append(_error("INVALID_STATUS", parent["qa_report"], "parallel worker outcome object is forbidden for this shape"))
    # QA phase event byte evidence. For parallel-dev, the mutable current
    # parent QA can retain already-passed siblings without re-transitioning
    # their absorbing states; only the latest required transition batch binds
    # the current bytes.
    parallel_before = _prior_parallel_qa_declaration(declaration) if shape == "parallel_dev" else None
    prior_states = ({m["member_id"]: m["state"] for m in parallel_before["phase_projection"]["members"]}
                    if parallel_before is not None else {})
    for member in declaration["member_lineage"]:
        phase = phase_by_id[member["member_id"]]
        qa_pair = parent_qa if shape in {"singular", "parallel_dev"} else qa_documents.get(member["member_id"])
        binds_current = shape != "parallel_dev" or prior_states.get(member["member_id"]) != "qa_pass"
        if phase["state"] == "qa_pass" and qa_pair is not None and binds_current:
            qa_digest = AGG._bytes_digest(qa_pair[1])
            events = [e for e in declaration["phase_projection"]["events"] if e["member_id"] == member["member_id"] and e["attempt"] == phase["attempt"] and e["to_state"] == "qa_pass"]
            latest = events[-1:]
            if len(latest) != 1 or latest[0]["evidence_digest"] != qa_digest:
                errors.append(_error("INVALID_PHASE_TRANSITION", (parent["qa_report"] if shape in {"singular", "parallel_dev"} else member["artifact_paths"]["qa_report"]), "qa_pass event does not bind the exact current QA-report bytes"))
    # One parent completion indexes every present declared artifact except itself.
    if parent["completion"] is not None:
        completion = _read_text(root, parent["completion"], errors)
        if completion is not None:
            _markdown_identity(completion, declaration["parent_task_id"], parent["completion"], errors)
            for reference in result["artifact_paths"]:
                if reference == parent["completion"]:
                    continue
                pattern = re.compile(rf"(?<![A-Za-z0-9._/-]){re.escape(reference)}(?![A-Za-z0-9._/-])")
                if pattern.search(completion) is None:
                    errors.append(_error("INVALID_STATUS", parent["completion"], f"completion does not index declared artifact {reference}"))
    return declared_paths_valid


def _validate_declared_file_paths(root: Path, reports: list[tuple[str, dict[str, Any]]], errors: list[dict[str, Any]]) -> bool:
    valid = True
    for report_path, report in reports:
        if AGG._validate_declared_repo_paths(root, report, report_path, errors) is None:
            valid = False
    return valid


def _reject_bound_undeclared_reports(root: Path, declaration: dict[str, Any], allowed: set[str], errors: list[dict[str, Any]]) -> None:
    aggregate_errors: list[dict[str, str]] = []
    AGG._reject_undeclared_retries(root, declaration, allowed, aggregate_errors)
    errors.extend(
        _error(item["code"], item["path"], item["message"])
        for item in aggregate_errors
    )


def resolve_chain(project_root: Path | str, input_task_id: str) -> dict[str, Any]:
    root, root_errors = AGG._valid_root(project_root)
    root_text = str(root) if root is not None else str(Path(project_root).resolve(strict=False))
    result = _base_result(root_text, input_task_id)
    if root is None:
        result["errors"] = [_error(item["code"], item["path"], item["message"]) for item in root_errors]
        return result
    preflight = preflight_parent(root, input_task_id)
    if preflight["status"] != "ready":
        result["parent_task_id"] = preflight["parent_task_id"]
        result["task_id"] = preflight["parent_task_id"]
        result["shape"] = preflight["shape"]
        result["mode"] = AGG.MODE_BY_SHAPE.get(preflight["shape"])
        result["errors"] = preflight["errors"]
        return result
    parent_id = preflight["parent_task_id"]
    canonical_rel, canonical_path = _canonical_path(root, parent_id)
    errors: list[dict[str, Any]] = []
    canonical, canonical_raw = _read_json(root, canonical_rel, errors)
    if canonical is None or canonical_raw is None:
        result["errors"] = errors
        return result
    declaration, declaration_errors = AGG.validate_declaration(canonical.get("artifact_chain_declaration"), parent_id, root=root, validate_artifacts=True)
    errors.extend(_error(item["code"], item["path"], item["message"]) for item in declaration_errors)
    if declaration is None:
        result["errors"] = errors
        return result
    result["checks"]["declaration_valid"] = True
    _populate_relationships(result, root, declaration)
    _validate_required_inventory(root, declaration, errors)
    _event_evidence_checks(root, declaration, errors)
    result["checks"]["declared_paths_exist"] = _validate_shape_artifacts(
        root, result, declaration, canonical, canonical_raw, errors,
    )
    result["checks"]["baselines_valid"] = not any(error["code"] in {"MISSING_BASELINE_BINDING", "BASELINE_MISMATCH", "EXECUTION_POLICY_MISMATCH"} for error in errors)
    active_states = [member["state"] for member in declaration["phase_projection"]["members"] if member["state"] != "superseded"]
    result["checks"]["phase_final"] = bool(active_states) and all(state == "qa_pass" for state in active_states)
    if not result["checks"]["phase_final"]:
        errors.append(_error("INVALID_STATUS", canonical_rel, f"parent finalization requires every active member qa_pass; observed {active_states}"))
    allowed = set(result["artifact_paths"])
    for phase in declaration["phase_projection"]["members"]:
        allowed.update(row["artifact_path"] for row in phase["attempt_reservations"])
    _reject_bound_undeclared_reports(root, declaration, allowed, errors)
    result["errors"] = errors
    result["status"] = "pass" if not errors else "fail"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = StableArgumentParser(prog="resolve-dev-artifact-chain.py")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--preflight-parent", action="store_true")
    try:
        args = parser.parse_args(argv)
        result = preflight_parent(args.project_dir, args.task_id) if args.preflight_parent else resolve_chain(args.project_dir, args.task_id)
        success = result["status"] == ("ready" if args.preflight_parent else "pass")
    except ValueError as exc:
        result = _base_result("", "")
        result["errors"] = [_error("INVALID_ARGUMENT", "cli", str(exc))]
        success = False
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0 if success else 2


if __name__ == "__main__":
    sys.exit(main())
