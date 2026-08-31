#!/usr/bin/env python3
"""Fail-closed historical ``--fix`` provider for the dev lifecycle.

This module is intentionally a backend, not a command orchestrator.  It classifies
only R1-declared lifecycle evidence, journals every state transition durably, and
hands an exact mutation envelope to the later same-entrypoint Lane-L gate.  It
never invokes /close, /commit, Git commit/push, --force, --bulk, or --auto.
"""
from __future__ import annotations

import base64
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

MAX_STDIN_BYTES = 1_048_576
MAX_PROVIDER_BYTES = 2_097_152
MAX_AUDIT_BYTES = 8 * 1024 * 1024
REQUEST_SCHEMA = "dev_fix_request.v1"
RESULT_SCHEMA = "dev_fix_result.v1"
ERROR_SCHEMA = "dev_fix_error.v1"
PLAN_SCHEMA = "dev_fix_plan.v1"
RUN_SCHEMA = "dev_fix_run_identity.v1"
AUDIT_SCHEMA = "fix-audit.v2"
PRECLAIM_SCHEMA = "dev_fix_gate_preclaim_evidence.v1"
RECEIPT_SCHEMA = "dev_fix_gate_receipt.v1"
GRANT_SCHEMA = "human_fix_confirmation.v1"
TEMPLATE_SCHEMA = "dev_fix_mutation_envelope_template.v1"
ALLOWED_SCHEMA = "dev_fix_allowed_gate_mutations.v1"
STATE_SCHEMA = "dev_fix_gate_state.v1"
OWNERSHIP_ADMISSION_DIGEST = "sha256:6a4b1bfbe7267b0683ccf4845731a3e893d3aa1fa44a69493476d6da551be71c"
SUPERSEDED_OWNERSHIP_ADMISSION_DIGESTS = frozenset({
    "sha256:bd3cf91fe43b78217740e6dc42c28122715518a4a85bc9cd7c02a54a1c0ab7c7",
})
SECTION5_QUOTE_ARRAY_SHA256 = "d5b699ddb42a043c9ce35036e4fffc69eca6a6b4986b4c01a635b514b6f20714"

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_RAW_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_TASK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,191}$")
_SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_NONFINITE = {"NaN", "Infinity", "-Infinity"}
_OPERATIONS = {"prepare", "apply", "claim_gate", "record_gate_result", "recover", "inspect"}
_ENTRYPOINTS = {"close", "commit"}
_SUCCESS_STATUSES = {"prepared", "awaiting_gate", "finalized", "no_action"}
_EXIT_BY_STATUS = {
    "prepared": 0,
    "awaiting_gate": 0,
    "finalized": 0,
    "no_action": 0,
    "error": 1,
    "refused": 2,
    "route_required": 3,
    "recovery_required": 4,
}

ERROR_POLICY: dict[str, tuple[str, str, int, bool, bool]] = {
    "INVALID_REQUEST": ("request", "refused", 2, False, True),
    "UNSUPPORTED_SCHEMA": ("request", "refused", 2, False, True),
    "INVALID_OPERATION": ("request", "refused", 2, False, True),
    "INVALID_PROJECT_ROOT": ("request", "refused", 2, False, True),
    "TASK_ID_MISMATCH": ("request", "refused", 2, False, True),
    "ENTRYPOINT_MISMATCH": ("request", "refused", 2, False, True),
    "REQUEST_DIGEST_MISMATCH": ("request", "refused", 2, False, True),
    "R1_DEPENDENCY_UNAVAILABLE": ("dependency", "refused", 2, False, True),
    "R1_CONTRACT_MISMATCH": ("dependency", "refused", 2, False, True),
    "OWNERSHIP_ADMISSION_BLOCKED": ("ownership", "refused", 2, False, True),
    "LOCK_BUSY": ("cas", "refused", 2, True, False),
    "AUDIT_MALFORMED": ("recovery", "recovery_required", 4, False, True),
    "AUDIT_CAS_MISMATCH": ("cas", "recovery_required", 4, False, True),
    "INVENTORY_DRIFT": ("cas", "recovery_required", 4, False, True),
    "PLAN_DIGEST_MISMATCH": ("cas", "recovery_required", 4, False, True),
    "CONFIRMATION_REQUIRED": ("integrity", "refused", 2, False, True),
    "CONFIRMATION_INVALID": ("integrity", "refused", 2, False, True),
    "PROTECTED_INTEGRITY_REFUSAL": ("integrity", "refused", 2, False, True),
    "ROUTE_REQUIRED": ("integrity", "route_required", 3, False, False),
    "ACTION_FAILED": ("action", "recovery_required", 4, False, True),
    "DURABILITY_UNCERTAIN": ("action", "recovery_required", 4, False, True),
    "GATE_PRECLAIM_INVALID": ("gate", "recovery_required", 4, False, True),
    "GATE_NOT_EXPECTED": ("gate", "refused", 2, False, True),
    "GATE_ALREADY_CLAIMED": ("gate", "refused", 2, False, True),
    "GATE_CLAIM_INVALID": ("gate", "refused", 2, False, True),
    "GATE_RECEIPT_INVALID": ("gate", "recovery_required", 4, False, True),
    "GATE_OUTCOME_UNKNOWN": ("gate", "recovery_required", 4, False, True),
    "GATE_STATE_DRIFT": ("gate", "recovery_required", 4, False, True),
    "RECOVERY_REQUIRED": ("recovery", "recovery_required", 4, False, True),
    "INTERNAL_ERROR": ("internal", "error", 1, False, True),
}

# Lower rank dominates. NO_BLOCKER is intentionally outside the repair taxonomy.
DECISION_RANK = {
    "U_": 1,
    "F17": 2,
    "F10": 3,
    "F22": 4,
    "F07": 5,
    "F13": 6,
    "F08": 6,
    "F09": 6,
    "F21": 6,
    "F16": 7,
    "F15": 7,
    "F20": 7,
    "F03": 8,
    "F04": 8,
    "F05": 8,
    "F06": 8,
    "F11": 8,
    "F12": 8,
    "F14": 8,
    "F18": 8,
    "F19": 8,
    "F01": 9,
    "F02": 9,
    "NO_BLOCKER": 10,
}
PROTECTED_FAMILIES = {"F07", "F08", "F09", "F10", "F13", "F17", "F21", "F22"}
ROUTE_FAMILIES = {"F15", "F16", "F20"}
MECHANICAL_FAMILIES = {"F03", "F04", "F05", "F06", "F11", "F12", "F13", "F14", "F18", "F19"}
WAIVER_FAMILIES = {"F01", "F02"}
ALL_FAMILIES = tuple(f"F{i:02d}" for i in range(1, 23))

CURRENT_CODE_MAP = {
    "CLI_ARGUMENT_ERROR": "U_INVALID_ARGUMENT",
    "UNREADABLE_ARTIFACT": "F13",
    "EMPTY_ARTIFACT": "F13",
    "MALFORMED_JSON": "F13",
    "INVALID_JSON_TYPE": "F13",
    "MISSING_IDENTITY": "F03",
    "INVALID_DEV_STATUS": "F08",
    "INVALID_FILE_LIST": "F05",
    "INVALID_BLOCKING_ISSUES": "F09",
    "UNRESOLVED_BLOCKERS": "F09",
    "INVALID_QA_STATUS": "F10",
    "MISSING_COMPLETION_REFERENCE": "F06",
    "UNDECLARED_LANE_ARTIFACT": "F12",
    "MISSING_DEV_DIRECTORY": "U_INVALID_PROJECT_ROOT",
    "INVALID_WORKER_SET": "F12",
    "AMBIGUOUS_WORKER_SET": "U_AMBIGUOUS_WORKER_SET",
    "UNREADABLE_DEV_DIRECTORY": "U_INVALID_PROJECT_ROOT",
    "AGGREGATE_IMPLEMENTATION_ERROR": "U_PROVIDER_ERROR",
    "LANE_SET_MISMATCH": "F12",
    "INVALID_SHARD_SET": "F12",
    "STALE_FILE_UNION": "F05",
    "STALE_CANONICAL": "F11",
    "AMBIGUOUS_SINGULAR_CHAIN": "U_AMBIGUOUS_SINGULAR",
    "LOST_WORKER_DECLARATION": "F12",
}
R1_CODE_MAP = {
    "INVALID_ARGUMENT": "U_INVALID_ARGUMENT",
    "INVALID_PROJECT_ROOT": "U_INVALID_PROJECT_ROOT",
    "NON_LIFECYCLE_REPORT": "U_NON_LIFECYCLE",
    "MISSING_DECLARATION": "F12",
    "UNSUPPORTED_DECLARATION_VERSION": "U_UNSUPPORTED_DECLARATION",
    "INVALID_DECLARATION": "F13",
    "DECLARATION_DIGEST_MISMATCH": "U_DECLARATION_INTEGRITY",
    "LINEAGE_DIGEST_MISMATCH": "U_DECLARATION_INTEGRITY",
    "PHASE_DIGEST_MISMATCH": "U_DECLARATION_INTEGRITY",
    "INVALID_PHASE_TRANSITION": "F08",
    "INVENTORY_DIGEST_MISMATCH": "U_DECLARATION_INTEGRITY",
    "INVENTORY_MISMATCH": "U_INVENTORY_INTEGRITY",
    "SHAPE_ARTIFACT_MISMATCH": "U_SHAPE_INTEGRITY",
    "EXECUTION_POLICY_MISMATCH": "F12",
    "MISSING_BASELINE_BINDING": "U_BASELINE_INTEGRITY",
    "BASELINE_MISMATCH": "U_BASELINE_INTEGRITY",
    "PARENT_TASK_ID_REQUIRED": "NO_BLOCKER",
    "AMBIGUOUS_PARENT_MEMBERSHIP": "U_AMBIGUOUS_PARENT",
    "LANE_SET_MISMATCH": "F12",
    "INVALID_BLOCKING_ISSUES": "F09",
    "UNRESOLVED_BLOCKERS": "F09",
    "CANONICAL_NOT_FOUND": "F11",
    "CANONICAL_CHANGED": "U_STALE_PLAN",
    "INVALID_IDENTITY": "F03",
    "INVALID_STATUS": "F08",
    "STALE_FILE_UNION": "F05",
    "STALE_CANONICAL": "F11",
    "IO_ERROR": "U_IO_ERROR",
}
SPECIAL_CODE_MAP = {
    "COMMIT_REJECT": "F17",
    "COMMIT_VERDICT_UNPARSEABLE": "F18",
    "CLOSE_NO": "F22",
    "CLOSE_VERDICT_UNPARSEABLE": "F14",
    "CLOSE_STALE": "F15",
    "CLOSE_MISSING": "F16",
    "GRANT_INVALID": "F19",
    "PUSH_TOKEN_INVALID": "F19",
    "BULK_SENTINEL_MISSING": "F20",
    "FORCE_PROVENANCE": "F21",
}

REQUEST_COMMON = {
    "schema_version", "operation", "project_root", "task_id", "entrypoint",
    "session_id", "invocation_id", "request_digest",
}
REQUEST_OPERATION_FIELDS: dict[str, tuple[set[str], set[str]]] = {
    "prepare": ({"intent", "command_flags", "expected_ownership_audit_digest"}, set()),
    "apply": ({"run_id", "expected_origin_invocation_id", "expected_audit_generation",
               "expected_audit_sha256", "expected_inventory_digest", "expected_plan_digest",
               "gate_preclaim_evidence", "expected_gate_preclaim_digest",
               "confirmation_grant_path"}, set()),
    "claim_gate": ({"run_id", "expected_audit_generation", "expected_audit_sha256",
                    "handoff_digest", "consumer_lane"}, set()),
    "record_gate_result": ({"run_id", "expected_audit_generation", "expected_audit_sha256",
                            "gate_claim_token", "gate_receipt"}, set()),
    "recover": ({"run_id", "expected_audit_generation", "expected_audit_sha256"},
                {"observed_close_report_path", "observed_repository_roots"}),
    "inspect": (set(), set()),
}

class ContractError(Exception):
    def __init__(self, code: str, message: str, *, field: str | None = None,
                 expected: Any = None, observed: Any = None):
        super().__init__(message)
        self.code = code if code in ERROR_POLICY else "INTERNAL_ERROR"
        self.message = message
        self.field = field
        self.expected = expected
        self.observed = observed


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest_value(value: Any, exclude: str | None = None) -> str:
    if exclude is not None:
        if not isinstance(value, Mapping):
            raise ValueError("exclude requires a mapping")
        value = {k: v for k, v in value.items() if k != exclude}
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def raw_sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value}")


def strict_json_loads(data: bytes | str) -> Any:
    if isinstance(data, str):
        data = data.encode("utf-8")
    text = data.decode("utf-8", errors="strict")
    duplicates: list[str] = []
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in items:
            if key in out:
                duplicates.append(key)
            out[key] = value
        return out
    value = json.loads(text, object_pairs_hook=pairs, parse_constant=_reject_constant)
    if duplicates:
        raise ValueError("duplicate JSON key: " + duplicates[0])
    return value


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(_DIGEST_RE.fullmatch(value))


def _is_uuid(value: Any) -> bool:
    if not isinstance(value, str) or not _UUID_RE.fullmatch(value):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _confirmation_invocation_id(prompt_digest: Any) -> str:
    """Derive the one apply identity bound to the trusted Prompt-2 event."""
    if not _is_digest(prompt_digest):
        raise ContractError("CONFIRMATION_INVALID", "confirmation prompt digest invalid")
    raw = bytearray.fromhex(str(prompt_digest).removeprefix("sha256:"))[:16]
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(raw)))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("not RFC3339 UTC")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.tzinfo is None:
        raise ValueError("timezone missing")
    return parsed


def _error(code: str, message: str, *, field: str | None = None,
           expected: Any = None, observed: Any = None) -> dict[str, Any]:
    category, _status, _exit, retryable, protected = ERROR_POLICY.get(
        code, ERROR_POLICY["INTERNAL_ERROR"])
    return {
        "schema_version": ERROR_SCHEMA,
        "code": code if code in ERROR_POLICY else "INTERNAL_ERROR",
        "category": category,
        "message": message or code,
        "retryable": retryable,
        "protected": protected,
        "field": field,
        "expected": expected,
        "observed": observed,
    }


def _gate_handoff_empty(*, state: str = "not_required") -> dict[str, Any]:
    return {
        "required": False,
        "state": state,
        "gate_kind": None,
        "gate_attempt_id": None,
        "gate_invocation_id": None,
        "identity_adoption_digest": None,
        "handoff_digest": None,
        "claim_token": None,
        "gate_preclaim_digest": None,
        "allowed_mutations_digest": None,
        "allowed_mutations": None,
        "pre_gate_state_digest": None,
        "receipt_digest": None,
        "outcome": None,
    }


def _base_result(operation: str = "unknown") -> dict[str, Any]:
    return {
        "schema_version": RESULT_SCHEMA,
        "operation": operation,
        "status": "refused",
        "action": "none",
        "project_root": None,
        "task_id": None,
        "entrypoint": None,
        "invocation_id": None,
        "origin_invocation_id": None,
        "gate_invocation_id": None,
        "origin_session_id": None,
        "identity_adoption_digest": None,
        "gate_preclaim_digest": None,
        "request_digest": None,
        "run_id": None,
        "audit_path": None,
        "audit_generation": None,
        "audit_sha256": None,
        "inventory_digest_before": None,
        "inventory_digest_after": None,
        "plan_digest": None,
        "decision": {"root_decision_ids": [], "secondary_evidence_codes": [],
                     "disposition": "protected_refusal", "protected": True},
        "plan": None,
        "mutations": [],
        "waivers": [],
        "gate_handoff": _gate_handoff_empty(state="unknown"),
        "next_action": {"kind": "none", "human_command": None},
        "errors": [],
        "result_digest": None,
    }


def _finish_result(result: dict[str, Any]) -> dict[str, Any]:
    result["errors"] = sorted(result.get("errors", []),
                              key=lambda e: (str(e.get("code", "")), str(e.get("field") or "")))
    result["mutations"] = sorted(result.get("mutations", []), key=lambda x: x.get("action_id", ""))
    result["waivers"] = sorted(result.get("waivers", []),
                                key=lambda x: (x.get("catalog_id", ""), x.get("path", "")))
    decision = result.get("decision", {})
    decision["root_decision_ids"] = sorted(set(decision.get("root_decision_ids", [])))
    decision["secondary_evidence_codes"] = sorted(set(decision.get("secondary_evidence_codes", [])))
    result["result_digest"] = digest_value(result, "result_digest")
    return result


def _failure_result(exc: ContractError, request: Mapping[str, Any] | None = None) -> dict[str, Any]:
    op = request.get("operation") if isinstance(request, Mapping) else None
    operation = op if op in _OPERATIONS and exc.code != "INTERNAL_ERROR" else "unknown"
    result = _base_result(operation)
    if isinstance(request, Mapping):
        valid = {
            "project_root": lambda v: isinstance(v, str) and v.startswith("/"),
            "task_id": lambda v: isinstance(v, str) and bool(_TASK_RE.fullmatch(v)),
            "entrypoint": lambda v: v in _ENTRYPOINTS,
            "invocation_id": _is_uuid,
            "request_digest": _is_digest,
        }
        for key, predicate in valid.items():
            value = request.get(key)
            if predicate(value):
                result[key] = value
        sid = request.get("session_id")
        if isinstance(sid, str) and sid:
            result["origin_session_id"] = sid
    result["status"] = ERROR_POLICY[exc.code][1]
    result["errors"] = [_error(exc.code, exc.message, field=exc.field,
                               expected=exc.expected, observed=exc.observed)]
    if exc.code == "INTERNAL_ERROR":
        result["decision"] = {"root_decision_ids": ["U_PROTOCOL"],
                              "secondary_evidence_codes": [],
                              "disposition": "protected_refusal", "protected": True}
        result["gate_handoff"] = _gate_handoff_empty(state="not_required")
        result["next_action"] = {"kind": "manual_recovery", "human_command": None}
    return _finish_result(result)


def _validate_request(request: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(request, Mapping) or isinstance(request, (str, bytes)):
        raise ContractError("INVALID_REQUEST", "request must be one JSON object")
    req = dict(request)
    schema = req.get("schema_version")
    if schema != REQUEST_SCHEMA:
        raise ContractError("UNSUPPORTED_SCHEMA", "unsupported request schema",
                            field="schema_version", expected=REQUEST_SCHEMA, observed=schema)
    operation = req.get("operation")
    if operation not in _OPERATIONS:
        raise ContractError("INVALID_OPERATION", "unsupported operation", field="operation",
                            expected=sorted(_OPERATIONS), observed=operation)
    required, optional = REQUEST_OPERATION_FIELDS[operation]
    allowed = REQUEST_COMMON | required | optional
    missing = sorted((REQUEST_COMMON | required) - set(req))
    extra = sorted(set(req) - allowed)
    if missing or extra:
        raise ContractError("INVALID_REQUEST", "operation field set is not exact",
                            field="fields", expected={"required": sorted(REQUEST_COMMON | required),
                                                      "optional": sorted(optional)},
                            observed={"missing": missing, "extra": extra})
    if req["entrypoint"] not in _ENTRYPOINTS:
        raise ContractError("INVALID_REQUEST", "invalid entrypoint", field="entrypoint",
                            expected=sorted(_ENTRYPOINTS), observed=req["entrypoint"])
    if not isinstance(req["project_root"], str) or not os.path.isabs(req["project_root"]):
        raise ContractError("INVALID_PROJECT_ROOT", "project_root must be absolute",
                            field="project_root", observed=req["project_root"])
    if not isinstance(req["task_id"], str) or not _TASK_RE.fullmatch(req["task_id"]):
        raise ContractError("INVALID_REQUEST", "invalid canonical task id", field="task_id")
    if not isinstance(req["session_id"], str) or not _SESSION_RE.fullmatch(req["session_id"]):
        raise ContractError("INVALID_REQUEST", "invalid session id", field="session_id")
    if not _is_uuid(req["invocation_id"]):
        raise ContractError("INVALID_REQUEST", "invocation_id must be canonical lowercase UUID",
                            field="invocation_id")
    if not _is_digest(req["request_digest"]):
        raise ContractError("INVALID_REQUEST", "invalid request digest", field="request_digest")
    observed = digest_value(req, "request_digest")
    if observed != req["request_digest"]:
        raise ContractError("REQUEST_DIGEST_MISMATCH", "request digest mismatch",
                            field="request_digest", expected=observed, observed=req["request_digest"])
    if operation == "prepare":
        if req["intent"] not in {"preview", "execute"}:
            raise ContractError("INVALID_REQUEST", "invalid prepare intent", field="intent")
        flags = req["command_flags"]
        exact_flags = {"fix": True, "auto": False, "force": False, "bulk": False}
        if not isinstance(flags, dict) or flags != exact_flags:
            raise ContractError("INVALID_REQUEST", "--fix is opt-in and incompatible with auto/bulk/force",
                                field="command_flags", expected=exact_flags, observed=flags)
        if req["expected_ownership_audit_digest"] != OWNERSHIP_ADMISSION_DIGEST:
            raise ContractError("OWNERSHIP_ADMISSION_BLOCKED", "ownership admission digest is not exact",
                                field="expected_ownership_audit_digest",
                                expected=OWNERSHIP_ADMISSION_DIGEST,
                                observed=req["expected_ownership_audit_digest"])
    elif operation == "apply":
        for key in ("run_id", "expected_audit_sha256", "expected_inventory_digest",
                    "expected_plan_digest", "expected_gate_preclaim_digest"):
            if not _is_digest(req[key]):
                raise ContractError("INVALID_REQUEST", "invalid digest", field=key)
        if not _is_uuid(req["expected_origin_invocation_id"]):
            raise ContractError("INVALID_REQUEST", "invalid expected origin UUID",
                                field="expected_origin_invocation_id")
        if not isinstance(req["expected_audit_generation"], int) or req["expected_audit_generation"] < 0:
            raise ContractError("INVALID_REQUEST", "invalid audit generation",
                                field="expected_audit_generation")
        confirmation_path = req["confirmation_grant_path"]
        if confirmation_path is not None:
            if not isinstance(confirmation_path, str) or not os.path.isabs(confirmation_path) \
                    or os.path.normpath(confirmation_path) != confirmation_path \
                    or Path(confirmation_path).parent != Path("/tmp"):
                raise ContractError("INVALID_REQUEST", "confirmation path must be a normalized absolute /tmp path or null",
                                    field="confirmation_grant_path")
        _validate_preclaim(req["gate_preclaim_evidence"], req["expected_gate_preclaim_digest"])
    elif operation == "claim_gate":
        for key in ("run_id", "expected_audit_sha256", "handoff_digest"):
            if not _is_digest(req[key]):
                raise ContractError("INVALID_REQUEST", "invalid digest", field=key)
        if req["consumer_lane"] != "LANE-L":
            raise ContractError("INVALID_REQUEST", "only LANE-L can claim a gate", field="consumer_lane")
        if not isinstance(req["expected_audit_generation"], int) or req["expected_audit_generation"] < 0:
            raise ContractError("INVALID_REQUEST", "invalid audit generation", field="expected_audit_generation")
    elif operation == "record_gate_result":
        for key in ("run_id", "expected_audit_sha256", "gate_claim_token"):
            if not _is_digest(req[key]):
                raise ContractError("INVALID_REQUEST", "invalid digest", field=key)
        if not isinstance(req["expected_audit_generation"], int) or req["expected_audit_generation"] < 0:
            raise ContractError("INVALID_REQUEST", "invalid audit generation", field="expected_audit_generation")
        _validate_receipt_shape(req["gate_receipt"])
    elif operation == "recover":
        for key in ("run_id", "expected_audit_sha256"):
            if not _is_digest(req[key]):
                raise ContractError("INVALID_REQUEST", "invalid digest", field=key)
        if not isinstance(req["expected_audit_generation"], int) or req["expected_audit_generation"] < 0:
            raise ContractError("INVALID_REQUEST", "invalid audit generation", field="expected_audit_generation")
        if "observed_close_report_path" in req:
            close_path = req["observed_close_report_path"]
            if not isinstance(close_path, str) or not close_path or os.path.isabs(close_path):
                raise ContractError("INVALID_REQUEST", "close report path must be a non-empty relative path",
                                    field="observed_close_report_path")
            normalized = os.path.normpath(close_path)
            if normalized != close_path or normalized == ".." or normalized.startswith("../"):
                raise ContractError("INVALID_REQUEST", "close report path must be normalized beneath project root",
                                    field="observed_close_report_path")
        if req["entrypoint"] == "close" and "observed_repository_roots" in req \
                or req["entrypoint"] == "commit" and "observed_close_report_path" in req:
            raise ContractError("INVALID_REQUEST", "recovery observations must match the selected entrypoint",
                                field="entrypoint")
        if "observed_repository_roots" in req:
            roots = req["observed_repository_roots"]
            if not isinstance(roots, list) or roots != sorted(set(roots)) or not all(
                    isinstance(x, str) and os.path.isabs(x) and os.path.realpath(x) == x for x in roots):
                raise ContractError("INVALID_REQUEST", "repository roots must be sorted unique absolutes",
                                    field="observed_repository_roots")
    return req


def _canonical_root(value: str) -> Path:
    real = Path(os.path.realpath(value))
    if str(real) != value or not real.is_dir():
        raise ContractError("INVALID_PROJECT_ROOT", "project root must be an existing canonical path",
                            field="project_root", expected=str(real), observed=value)
    try:
        proc = subprocess.run(["git", "-C", str(real), "rev-parse", "--show-toplevel"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                              timeout=10, env={"PATH": os.environ.get("PATH", "")})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContractError("INVALID_PROJECT_ROOT", f"cannot resolve git root: {exc}") from exc
    if proc.returncode != 0:
        raise ContractError("INVALID_PROJECT_ROOT", "project root is not a Git worktree",
                            observed=proc.stderr.decode(errors="replace")[:300])
    top = Path(os.path.realpath(proc.stdout.decode("utf-8", errors="strict").strip()))
    if top != real:
        raise ContractError("INVALID_PROJECT_ROOT", "project root differs from git toplevel",
                            expected=str(top), observed=str(real))
    return real


def _safe_rel(root: Path, value: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or os.path.isabs(value):
        raise ContractError("R1_CONTRACT_MISMATCH", "artifact path is not normalized relative",
                            observed=value)
    posix = Path(value).as_posix()
    if posix != value or value.startswith("./") or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ContractError("R1_CONTRACT_MISMATCH", "artifact path escapes or is not normalized",
                            observed=value)
    resolved_parent = Path(os.path.realpath(root / Path(value).parent))
    try:
        resolved_parent.relative_to(root)
    except ValueError as exc:
        raise ContractError("R1_CONTRACT_MISMATCH", "artifact parent escapes project", observed=value) from exc
    return value


def _typed_path_state(path: Path) -> dict[str, Any]:
    try:
        st = path.lstat()
    except FileNotFoundError:
        value: dict[str, Any] = {"state": "absent"}
        return {**value, "state_digest": digest_value(value)}
    if stat.S_ISLNK(st.st_mode):
        value = {"state": "symlink", "mode": f"{stat.S_IMODE(st.st_mode):04o}"}
    elif not stat.S_ISREG(st.st_mode):
        value = {"state": "other", "mode": f"{stat.S_IMODE(st.st_mode):04o}"}
    else:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        except OSError as exc:
            raise ContractError("INVENTORY_DRIFT", f"cannot open regular evidence safely: {exc}",
                                field=str(path)) from exc
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (st.st_dev, st.st_ino):
                raise ContractError("INVENTORY_DRIFT", "evidence path changed during open",
                                    field=str(path))
            hasher = hashlib.sha256()
            size = 0
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                hasher.update(chunk)
                size += len(chunk)
            after = os.fstat(fd)
        finally:
            os.close(fd)
        try:
            final = path.lstat()
        except OSError as exc:
            raise ContractError("INVENTORY_DRIFT", "evidence path disappeared during read",
                                field=str(path)) from exc
        stable_fields = lambda row: (row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns,
                                     row.st_ctime_ns, stat.S_IMODE(row.st_mode))
        if stable_fields(opened) != stable_fields(after) or stable_fields(after) != stable_fields(final) \
                or size != after.st_size or not stat.S_ISREG(final.st_mode):
            raise ContractError("INVENTORY_DRIFT", "evidence path changed during read",
                                field=str(path))
        value = {"state": "file", "mode": f"{stat.S_IMODE(after.st_mode):04o}",
                 "size": size, "content_sha256": "sha256:" + hasher.hexdigest()}
    return {**value, "state_digest": digest_value(value)}


def _inventory_entry(root: Path, path: str, kind: str, member: str | None,
                     required: bool) -> dict[str, Any]:
    rel = _safe_rel(root, path)
    state = _typed_path_state(root / rel)
    return {
        "path": rel,
        "kind": kind,
        "member_id": member,
        "required": bool(required),
        "existence": state["state"] != "absent",
        "file_type": state["state"],
        "byte_length": state.get("size"),
        "sha256": state.get("content_sha256"),
    }


def _collect_inventory(root: Path, r1: Mapping[str, Any]) -> tuple[list[dict[str, Any]], str]:
    candidates: list[tuple[str, str, str | None, bool]] = []
    def add(path: Any, kind: str, member: str | None = None, required: bool = True) -> None:
        if isinstance(path, str) and path:
            candidates.append((path, kind, member, required))
    for value in r1.get("artifact_paths", []):
        if isinstance(value, str): add(value, "artifact")
        elif isinstance(value, Mapping): add(value.get("path"), str(value.get("kind", "artifact")),
                                             value.get("member_id"), value.get("required", True) is True)
    for value in r1.get("qa_inputs", []):
        if isinstance(value, str):
            add(value, "qa", None, True)
        elif isinstance(value, Mapping):
            # artifact_chain_result.v2 names this field qa_report (not path).
            add(value.get("qa_report"), "qa", value.get("member_id") or value.get("task_id"), True)
    parent = r1.get("parent")
    if isinstance(parent, Mapping):
        for key in ("ticket", "context", "canonical_dev_report", "completion", "qa_report"):
            value = parent.get(key)
            if isinstance(value, Mapping): add(value.get("path"), key, parent.get("task_id"),
                                               value.get("required", True) is True)
            else: add(value, key, parent.get("task_id"), True)
    for key in ("canonical_dev_report", "completion"):
        value = r1.get(key)
        if isinstance(value, Mapping): add(value.get("path"), key, r1.get("task_id"),
                                           value.get("required", True) is True)
        else: add(value, key, r1.get("task_id"), True)
    for value in r1.get("commit_whitelist_artifacts", []):
        if isinstance(value, str): add(value, "commit_whitelist", None, True)
        elif isinstance(value, Mapping): add(value.get("path"), "commit_whitelist",
                                             value.get("member_id"), value.get("required", True) is True)
    # Same path/kind/member may appear in more than one R1 projection; collapse exact duplicates.
    unique = sorted(set(candidates), key=lambda x: (x[0].encode("utf-8"), x[1], (x[2] or "").encode("utf-8"), not x[3]))
    rows = [_inventory_entry(root, *item) for item in unique]
    return rows, digest_value(rows)


def _load_r1_result(root: Path, task_id: str) -> dict[str, Any]:
    script = root / "scripts/resolve-dev-artifact-chain.py"
    state = _typed_path_state(script)
    if state["state"] != "file":
        raise ContractError("R1_DEPENDENCY_UNAVAILABLE", "R1 resolver is missing or non-regular",
                            field="scripts/resolve-dev-artifact-chain.py", observed=state["state"])
    try:
        proc = subprocess.run([sys.executable, str(script), "--project-dir", str(root),
                               "--task-id", task_id], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, check=False, timeout=60,
                              env={"PATH": os.environ.get("PATH", ""), "LANG": "C.UTF-8"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContractError("R1_DEPENDENCY_UNAVAILABLE", f"R1 resolver failed: {exc}") from exc
    if len(proc.stdout) > MAX_PROVIDER_BYTES:
        raise ContractError("R1_CONTRACT_MISMATCH", "R1 result exceeds bound")
    try:
        value = strict_json_loads(proc.stdout)
    except Exception as exc:
        raise ContractError("R1_CONTRACT_MISMATCH", f"R1 did not emit strict JSON: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != "artifact_chain_result.v2":
        raise ContractError("R1_CONTRACT_MISMATCH", "R1 schema mismatch")
    if value.get("project_root") != str(root):
        raise ContractError("R1_CONTRACT_MISMATCH", "R1 root mismatch", field="project_root",
                            expected=str(root), observed=value.get("project_root"))
    ids = {value.get("task_id"), value.get("parent_task_id"), value.get("input_task_id")}
    if task_id not in ids:
        raise ContractError("TASK_ID_MISMATCH", "R1 task identity mismatch",
                            expected=task_id, observed=sorted(str(x) for x in ids))
    if value.get("status") not in {"pass", "fail"} or not isinstance(value.get("errors"), list):
        raise ContractError("R1_CONTRACT_MISMATCH", "R1 status/errors are invalid")
    if (value["status"] == "pass") != (len(value["errors"]) == 0):
        raise ContractError("R1_CONTRACT_MISMATCH", "R1 status contradicts its error set",
                            field="status", observed={"status": value["status"],
                                                        "error_count": len(value["errors"])})
    if value["status"] == "pass" and value.get("shape") not in {
            "singular", "parallel_dev", "requirement_fanout"}:
        raise ContractError("R1_CONTRACT_MISMATCH", "R1 PASS lacks a supported artifact shape",
                            field="shape", observed=value.get("shape"))
    expected_exit = 0 if value["status"] == "pass" else 2
    if proc.returncode != expected_exit:
        raise ContractError("R1_CONTRACT_MISMATCH", "R1 status and provider exit disagree",
                            field="provider_exit", expected=expected_exit, observed=proc.returncode)
    value["_provider_exit"] = proc.returncode
    value["_provider_stderr_digest"] = digest_value({"stderr": proc.stderr.decode(errors="replace")[:4096]})
    return value


def _r1_snapshot(root: Path, task_id: str) -> tuple[dict[str, Any], str,
                                                     list[dict[str, Any]], str]:
    """Read one provider snapshot and derive its public digest and exact inventory."""
    result = _load_r1_result(root, task_id)
    public = {key: value for key, value in result.items() if not key.startswith("_")}
    inventory, inventory_digest = _collect_inventory(root, result)
    return result, digest_value(public), inventory, inventory_digest


def _path_kind(event: Mapping[str, Any], r1: Mapping[str, Any]) -> tuple[str, bool, bool]:
    kind = str(event.get("artifact_kind") or event.get("kind") or "").lower()
    path = str(event.get("path") or "").lower()
    if not kind:
        for token in ("qa", "completion", "ticket", "context", "canonical", "dev-report", "dev_report"):
            if token in path:
                kind = token
                break
    required = event.get("required", True) is not False
    claimed = event.get("authority_claimed_produced", event.get("claimed_produced", False)) is True
    shape = r1.get("shape")
    if shape == "requirement_fanout" and kind in {"ticket", "context", "qa", "qa_report"}:
        parent = r1.get("parent")
        parent_path = None
        if isinstance(parent, Mapping):
            pv = parent.get("qa_report" if kind.startswith("qa") else kind)
            parent_path = pv.get("path") if isinstance(pv, Mapping) else pv
        if parent_path and event.get("path") == parent_path:
            required = False
    return kind, required, claimed


def _declared_json(root: Path, event: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Read only the exact R1-declared event path; never discover by filename/glob."""
    path = event.get("path")
    if not isinstance(path, str):
        return None
    try:
        relative = _safe_rel(root, path)
        state = _typed_path_state(root / relative)
        if state["state"] != "file":
            return None
        value = strict_json_loads((root / relative).read_bytes())
    except (ContractError, OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def _dev_status(root: Path, event: Mapping[str, Any]) -> str | None:
    """Return a structured dev status, never a value parsed from diagnostic prose."""
    supplied = event.get("status")
    if isinstance(supplied, str):
        return supplied
    document = _declared_json(root, event)
    if document is None:
        return None
    dev = document.get("dev")
    if isinstance(dev, Mapping) and isinstance(dev.get("status"), str):
        return dev["status"]
    return document.get("status") if isinstance(document.get("status"), str) else None


def _f13_has_exact_duplicate(root: Path, event: Mapping[str, Any], r1: Mapping[str, Any]) -> bool:
    duplicate = event.get("authoritative_duplicate")
    expected = event.get("expected_sha256")
    declared = {
        row.get("path"): row
        for row in r1.get("artifact_paths", [])
        if isinstance(row, Mapping) and isinstance(row.get("path"), str)
    }
    if not isinstance(duplicate, str) or duplicate not in declared or not _is_digest(expected):
        return False
    if declared[duplicate].get("sha256") != expected:
        return False
    try:
        state = _typed_path_state(root / _safe_rel(root, duplicate))
    except ContractError:
        return False
    return state.get("content_sha256") == expected


def classify_event(event: Mapping[str, Any], r1: Mapping[str, Any]) -> tuple[str, list[str]]:
    """Return exactly one root decision and sorted secondary evidence codes."""
    if not isinstance(event, Mapping):
        return "U_UNKNOWN", []
    code = event.get("code")
    if not isinstance(code, str) or not code:
        return "U_UNKNOWN", []
    secondary = [code]
    if code in SPECIAL_CODE_MAP:
        return SPECIAL_CODE_MAP[code], secondary
    if code in {"MISSING_ARTIFACT", "ABSENT_DECLARED_PATH", "MISSING_ARTIFACT_PATH"}:
        kind, required, claimed = _path_kind(event, r1)
        if not required:
            return "NO_BLOCKER", secondary
        if kind in {"qa", "qa_report"}:
            return "F10", secondary
        if claimed or code == "ABSENT_DECLARED_PATH":
            return "F07", secondary
        if kind == "completion":
            return "F01", secondary
        if kind in {"ticket", "context"}:
            return "F02", secondary
        if kind in {"canonical", "dev-report", "dev_report"} and r1.get("shape") == "parallel_dev":
            return "F11", secondary
        return "F07", secondary
    if code in {"IDENTITY_MISMATCH", "INVALID_TASK_ID", "INVALID_IDENTITY"}:
        observed = str(event.get("observed") or event.get("actual") or "")
        expected = str(event.get("expected") or r1.get("task_id") or r1.get("parent_task_id") or "")
        if expected and observed == "dev-" + expected:
            return "F04", secondary
        return "F03" if expected else "U_IDENTITY_CONFLICT", secondary
    root = CURRENT_CODE_MAP.get(code, R1_CODE_MAP.get(code))
    if root is None:
        return "U_UNKNOWN", secondary
    if code == "INVALID_STATUS":
        kind, _, _ = _path_kind(event, r1)
        if kind.startswith("qa") or event.get("phase") == "qa":
            root = "F10"
    if code == "CANONICAL_NOT_FOUND" and r1.get("shape") not in {"parallel_dev", "requirement_fanout"}:
        root = "F07"
    return root, secondary


def classify_r1(r1: Mapping[str, Any], entrypoint: str, root: Path, task_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    events = [dict(x) if isinstance(x, Mapping) else {"code": "U_UNKNOWN", "raw": repr(x)}
              for x in r1.get("errors", [])]
    # Required QA authority is exactly R1 qa_inputs. artifact_chain_result.v2
    # rows name the declared artifact in qa_report; the resolver's own status and
    # errors are the PASS authority. Optional fanout parent QA is never injected.
    shape = r1.get("shape")
    qa_inputs = r1.get("qa_inputs")
    if shape in {"singular", "parallel_dev", "requirement_fanout"}:
        if not isinstance(qa_inputs, list) or not qa_inputs:
            events.append({"code": "INVALID_QA_STATUS", "kind": "qa", "required": True})
        else:
            expected_scope = "member" if shape == "requirement_fanout" else "parent"
            seen: set[tuple[Any, Any, Any]] = set()
            for qa in qa_inputs:
                if not isinstance(qa, Mapping):
                    events.append({"code": "INVALID_QA_STATUS", "kind": "qa", "required": True})
                    continue
                path = qa.get("qa_report")
                key = (qa.get("scope"), qa.get("member_id"), path)
                if key in seen or qa.get("scope") != expected_scope or not isinstance(path, str):
                    events.append({"code": "INVALID_QA_STATUS", "kind": "qa",
                                   "path": path, "required": True})
                    continue
                seen.add(key)
                # A structured status is accepted only as an additional negative
                # signal; its absence is normal in the v2 resolver projection.
                if "status" in qa and str(qa.get("status", "")).lower() not in {"pass", "passed"}:
                    events.append({"code": "INVALID_QA_STATUS", "kind": "qa",
                                   "path": path, "required": True, "status": qa.get("status")})
    if entrypoint == "commit":
        close_rel = f"docs/dev/close-report-{task_id}.md"
        close_path = root / close_rel
        state = _typed_path_state(close_path)
        if state["state"] == "absent":
            events.append({"code": "CLOSE_MISSING", "path": close_rel, "kind": "close"})
        elif state["state"] != "file":
            events.append({"code": "U_UNKNOWN", "path": close_rel, "kind": "close"})
        else:
            text = close_path.read_text("utf-8", errors="strict")
            nonempty = [line.strip() for line in text.splitlines() if line.strip()]
            verdicts = [line.split(":", 1)[1].strip().split()[0] for line in nonempty
                        if re.match(r"^CLOSE:\s+(?:YES|NO)(?:\s|$)", line)]
            if nonempty and nonempty[-1].startswith("CLOSE: YES"):
                pass
            elif nonempty and nonempty[-1].startswith("CLOSE: NO"):
                events.append({"code": "CLOSE_NO", "path": close_rel})
            elif len(set(verdicts)) == 1 and verdicts:
                events.append({"code": "CLOSE_VERDICT_UNPARSEABLE", "path": close_rel})
            else:
                events.append({"code": "U_UNKNOWN", "path": close_rel, "kind": "close"})
            close_mtime = close_path.lstat().st_mtime
            now_epoch = time.time()
            if close_mtime > now_epoch + 1:
                events.append({"code": "U_FUTURE_CLOSE_MTIME", "path": close_rel,
                               "observed_mtime": close_mtime})
            elif now_epoch - close_mtime > 24 * 60 * 60:
                events.append({"code": "CLOSE_STALE", "path": close_rel,
                               "observed_age_seconds": int(now_epoch - close_mtime)})
    classified: list[dict[str, Any]] = []
    for idx, event in enumerate(events):
        root_id, secondary = classify_event(event, r1)
        classified.append({"event_index": idx, "event": event, "root_decision_id": root_id,
                           "secondary_evidence_codes": secondary})
    roots = [x["root_decision_id"] for x in classified]
    f08_route = any(
        row["root_decision_id"] == "F08" and _dev_status(root, row["event"]) in {"ready_for_qa", "qa_ready"}
        for row in classified
    )
    f08_protected = any(
        row["root_decision_id"] == "F08" and _dev_status(root, row["event"]) not in {"ready_for_qa", "qa_ready"}
        for row in classified
    )
    f13_protected = any(
        row["root_decision_id"] == "F13" and not _f13_has_exact_duplicate(root, row["event"], r1)
        for row in classified
    )
    protected = any(
        x.startswith("U_") or x in (PROTECTED_FAMILIES - {"F08", "F13"})
        for x in roots
    ) or f08_protected or f13_protected
    if protected:
        disposition = "protected_refusal"
    elif f08_route or any(x in ROUTE_FAMILIES for x in roots):
        disposition = "route_required"
    elif any(x in WAIVER_FAMILIES for x in roots):
        disposition = "waiver_candidate"
    elif any(x in MECHANICAL_FAMILIES for x in roots):
        disposition = "mechanical_repair"
    else:
        disposition = "no_blocker"
    decision = {
        "root_decision_ids": sorted(set(roots)),
        "secondary_evidence_codes": sorted({c for x in classified for c in x["secondary_evidence_codes"]}),
        "disposition": disposition,
        "protected": protected,
    }
    return decision, classified


def _audit_paths(root: Path, task_id: str) -> tuple[Path, Path]:
    if not _TASK_RE.fullmatch(task_id):
        raise ContractError("INVALID_REQUEST", "unsafe task id")
    audit = root / "docs/dev" / f"fix-audit-{task_id}.json"
    lock = root / "docs/dev/.fix-locks" / (hashlib.sha256(task_id.encode()).hexdigest() + ".lock")
    return audit, lock


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    st = path.lstat()
    if path.is_symlink() or not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid() \
            or Path(os.path.realpath(path)) != path:
        raise ContractError("AUDIT_MALFORMED", "audit directory is unsafe", observed=str(path))


@contextmanager
def _task_lock(root: Path, task_id: str):
    audit, lock = _audit_paths(root, task_id)
    _ensure_private_directory(audit.parent)
    _ensure_private_directory(lock.parent)
    try:
        fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    except OSError as exc:
        raise ContractError("LOCK_BUSY", f"cannot open task lock: {exc}") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or st.st_nlink != 1:
            raise ContractError("LOCK_BUSY", "task lock is not an owned regular file")
        if stat.S_IMODE(st.st_mode) != 0o600:
            raise ContractError("LOCK_BUSY", "task lock mode is not 0600")
        acquired = False
        for _ in range(20):
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                time.sleep(0.025)
        if not acquired:
            raise ContractError("LOCK_BUSY", "task lock is busy")
        yield audit
    finally:
        try: fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError: pass
        os.close(fd)


def _new_audit(root: Path, task_id: str) -> dict[str, Any]:
    value = {
        "schema_version": AUDIT_SCHEMA,
        "project_root": str(root),
        "task_id": task_id,
        "generation": 0,
        "runs": [],
        "created_at": _now(),
        "updated_at": _now(),
        "audit_digest": None,
    }
    value["audit_digest"] = digest_value(value, "audit_digest")
    return value


def _validate_audit_runs(value: Mapping[str, Any]) -> None:
    run_ids: set[str] = set()
    request_digests: set[str] = set()
    identity_fields = {"schema_version", "canonical_project_root", "task_id", "entrypoint",
                       "origin_session_id", "origin_invocation_id", "request_digest",
                       "inventory_digest_before", "r1_result_digest", "run_id"}
    plan_fields = {"schema_version", "run_id", "entrypoint", "origin_invocation_id",
                   "origin_session_id", "request_digest", "r1_result_digest", "inventory_digest",
                   "actions", "waivers", "gate_required", "gate_kind", "allowed_mutations",
                   "plan_digest"}
    states = {"PREPARED", "PREVIEWED", "CONFIRMED", "ACTION_INTENT", "ACTION_APPLIED",
              "GATE_READY", "GATE_CLAIMED", "GATE_RESULT", "FINAL", "ROUTE_REQUIRED",
              "RECOVERY_REQUIRED", "REFUSED"}
    for run in value.get("runs", []):
        if not isinstance(run, Mapping):
            raise ContractError("AUDIT_MALFORMED", "audit run is not an object")
        identity, plan = run.get("identity"), run.get("plan")
        if not isinstance(identity, Mapping) or set(identity) != identity_fields \
                or not isinstance(plan, Mapping) or set(plan) != plan_fields:
            raise ContractError("AUDIT_MALFORMED", "run identity/plan field set is not exact")
        if identity.get("schema_version") != RUN_SCHEMA or plan.get("schema_version") != PLAN_SCHEMA:
            raise ContractError("AUDIT_MALFORMED", "run identity/plan schema mismatch")
        if identity.get("run_id") != digest_value(identity, "run_id") \
                or plan.get("plan_digest") != digest_value(plan, "plan_digest"):
            raise ContractError("AUDIT_MALFORMED", "run identity/plan digest mismatch")
        bindings = {
            "run_id": identity["run_id"], "entrypoint": identity["entrypoint"],
            "origin_invocation_id": identity["origin_invocation_id"],
            "origin_session_id": identity["origin_session_id"],
            "request_digest": identity["request_digest"],
            "r1_result_digest": identity["r1_result_digest"],
            "inventory_digest": identity["inventory_digest_before"],
        }
        if any(plan.get(key) != expected for key, expected in bindings.items()) \
                or run.get("run_id") != identity["run_id"] \
                or run.get("request_digest") != identity["request_digest"]:
            raise ContractError("AUDIT_MALFORMED", "run/identity/plan binding mismatch")
        if run.get("state") not in states or identity["run_id"] in run_ids \
                or identity["request_digest"] in request_digests:
            raise ContractError("AUDIT_MALFORMED", "run state or uniqueness invariant failed")
        run_ids.add(identity["run_id"])
        request_digests.add(identity["request_digest"])


def _read_private_audit_bytes(path: Path, *, allow_absent: bool) -> bytes | None:
    try:
        dfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise ContractError("AUDIT_MALFORMED", f"cannot open audit directory safely: {exc}") from exc
    try:
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dfd)
        except FileNotFoundError:
            if allow_absent:
                return None
            raise ContractError("AUDIT_MALFORMED", "required audit is absent")
        except OSError as exc:
            raise ContractError("AUDIT_MALFORMED", f"cannot open audit safely: {exc}") from exc
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or st.st_nlink != 1 \
                    or stat.S_IMODE(st.st_mode) != 0o600 or st.st_size <= 0 \
                    or st.st_size > MAX_AUDIT_BYTES:
                raise ContractError("AUDIT_MALFORMED", "audit must be one bounded owned mode-0600 regular file")
            chunks = []
            remaining = MAX_AUDIT_BYTES + 1
            while remaining:
                chunk = os.read(fd, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            after = os.fstat(fd)
        finally:
            os.close(fd)
        try:
            current = os.stat(path.name, dir_fd=dfd, follow_symlinks=False)
        except OSError as exc:
            raise ContractError("AUDIT_MALFORMED", "audit changed during read") from exc
        if len(raw) != st.st_size or len(raw) > MAX_AUDIT_BYTES \
                or (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns) \
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) \
                or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) \
                != (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns, current.st_ctime_ns):
            raise ContractError("AUDIT_MALFORMED", "audit changed during read")
        return raw
    finally:
        os.close(dfd)


def _read_audit(path: Path, root: Path, task_id: str, *, allow_absent: bool = True) -> tuple[dict[str, Any], str | None]:
    data = _read_private_audit_bytes(path, allow_absent=allow_absent)
    if data is None:
        return _new_audit(root, task_id), None
    try:
        value = strict_json_loads(data)
    except Exception as exc:
        raise ContractError("AUDIT_MALFORMED", f"audit is malformed: {exc}") from exc
    exact = {"schema_version", "project_root", "task_id", "generation", "runs",
             "created_at", "updated_at", "audit_digest"}
    if not isinstance(value, dict) or set(value) != exact:
        raise ContractError("AUDIT_MALFORMED", "audit field set is not exact")
    if value["schema_version"] != AUDIT_SCHEMA or value["project_root"] != str(root) or value["task_id"] != task_id:
        raise ContractError("AUDIT_MALFORMED", "audit identity mismatch")
    if not isinstance(value["generation"], int) or value["generation"] < 0 or not isinstance(value["runs"], list):
        raise ContractError("AUDIT_MALFORMED", "audit generation/runs invalid")
    if value["audit_digest"] != digest_value(value, "audit_digest"):
        raise ContractError("AUDIT_MALFORMED", "audit digest mismatch")
    _validate_audit_runs(value)
    return value, "sha256:" + raw_sha(data)


def _persist_audit(path: Path, audit: dict[str, Any]) -> tuple[int, str]:
    audit["generation"] = int(audit["generation"]) + 1
    audit["updated_at"] = _now()
    audit["audit_digest"] = None
    audit["audit_digest"] = digest_value(audit, "audit_digest")
    data = canonical_bytes(audit) + b"\n"
    _ensure_private_directory(path.parent)
    temp_path = path.parent / ("." + path.name + ".tmp-" + secrets.token_hex(16))
    fd = None
    try:
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            fd = None
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        os.chmod(path, 0o600, follow_symlinks=False)
        dfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try: os.fsync(dfd)
        finally: os.close(dfd)
    except OSError as exc:
        try:
            if fd is not None: os.close(fd)
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise ContractError("DURABILITY_UNCERTAIN", f"audit persistence failed: {exc}") from exc
    try:
        observed = _read_private_audit_bytes(path, allow_absent=False)
    except ContractError as exc:
        raise ContractError("DURABILITY_UNCERTAIN", f"audit post-write verification failed: {exc.message}") from exc
    assert observed is not None
    if observed != data:
        raise ContractError("DURABILITY_UNCERTAIN", "audit post-write bytes differ")
    return audit["generation"], "sha256:" + raw_sha(observed)


def _check_audit_cas(audit: Mapping[str, Any], observed_sha: str | None, request: Mapping[str, Any]) -> None:
    if audit.get("generation") != request.get("expected_audit_generation"):
        raise ContractError("AUDIT_CAS_MISMATCH", "audit generation changed",
                            expected=request.get("expected_audit_generation"), observed=audit.get("generation"))
    if observed_sha != request.get("expected_audit_sha256"):
        raise ContractError("AUDIT_CAS_MISMATCH", "audit bytes changed",
                            expected=request.get("expected_audit_sha256"), observed=observed_sha)


def _find_run(audit: Mapping[str, Any], run_id: str) -> dict[str, Any]:
    rows = [x for x in audit.get("runs", []) if isinstance(x, dict) and x.get("run_id") == run_id]
    if len(rows) != 1:
        raise ContractError("AUDIT_MALFORMED", "run identity is absent or duplicated",
                            field="run_id", observed=len(rows))
    return rows[0]


def _file_before(root: Path, rel: str) -> str | None:
    state = _typed_path_state(root / _safe_rel(root, rel))
    if state["state"] == "absent": return None
    if state["state"] != "file":
        raise ContractError("PROTECTED_INTEGRITY_REFUSAL", "repair target is not a regular file", observed=rel)
    return state["content_sha256"]


def _canonicalize_final_line(path: Path, prefix: str) -> bytes | None:
    try: text = path.read_text("utf-8", errors="strict")
    except (OSError, UnicodeError): return None
    matches: list[str] = []
    token = "YES|NO" if prefix == "CLOSE" else "APPROVE|REJECT"
    rx = re.compile(rf"^(?:\*\*)?{prefix}:\s*({token})(?:\*\*)?(?:\s.*)?$")
    for line in text.splitlines():
        match = rx.match(line.strip())
        if match: matches.append(match.group(1))
    if len(set(matches)) != 1 or not matches:
        return None
    lines = text.rstrip().splitlines()
    while lines and not lines[-1].strip(): lines.pop()
    lines.append(f"{prefix}: {matches[0]}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _json_repair_bytes(root: Path, path: Path, family: str, task_id: str,
                       r1: Mapping[str, Any], event: Mapping[str, Any]) -> bytes | None:
    try:
        value = strict_json_loads(path.read_bytes())
    except Exception:
        return None
    if not isinstance(value, dict): return None
    out = dict(value)
    if family == "F03":
        if any(key in out and out[key] != task_id for key in ("task_id", "request_id")):
            return None
        if all(key in out for key in ("task_id", "request_id")):
            return None
        out["task_id"] = task_id
        out["request_id"] = task_id
    elif family == "F04":
        changed = False
        for key in ("task_id", "request_id"):
            if out.get(key) == "dev-" + task_id:
                out[key] = task_id
                changed = True
            elif key in out and out[key] != task_id:
                return None
        if not changed:
            return None
    elif family == "F05":
        modified = event.get("authoritative_files_modified")
        created = event.get("authoritative_files_created")
        binding = event.get("authoritative_file_list_digest")
        if not isinstance(modified, list) or not isinstance(created, list):
            return None
        try:
            modified = sorted({_safe_rel(root, item) for item in modified})
            created = sorted({_safe_rel(root, item) for item in created})
        except (ContractError, TypeError):
            return None
        projection = {"files_modified": modified, "files_created": created}
        if binding != digest_value(projection):
            return None
        out.update(projection)
    elif family == "F06":
        parent = r1.get("parent")
        if not isinstance(parent, Mapping): return None
        changed = False
        for src, dst in (("ticket", "ticket_path"), ("context", "context_path"),
                         ("canonical_dev_report", "dev_report_path"), ("qa_report", "qa_report_path")):
            v = parent.get(src)
            p = v.get("path") if isinstance(v, Mapping) else v
            if isinstance(p, str) and dst not in out:
                out[dst] = p; changed = True
        if not changed: return None
    else:
        return None
    return canonical_bytes(out) + b"\n"


def _derive_actions(root: Path, task_id: str, r1: Mapping[str, Any],
                    classified: Sequence[Mapping[str, Any]], decision: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    waivers: list[dict[str, Any]] = []
    if decision["protected"] or decision["disposition"] == "route_required":
        return actions, waivers, decision
    unresolved: list[str] = []
    promoted_protected: list[str] = []
    for item in classified:
        family = item["root_decision_id"]
        event = item["event"]
        if family in WAIVER_FAMILIES:
            path = event.get("path")
            if not isinstance(path, str): unresolved.append(family); continue
            try: path = _safe_rel(root, path)
            except ContractError: unresolved.append(family); continue
            # F01 is mechanical only when R1 supplies a complete deterministic object.
            completion = r1.get("completion")
            if family == "F01" and isinstance(completion, Mapping) and completion.get("path") == path \
                    and isinstance(completion.get("document"), Mapping):
                data = canonical_bytes(completion["document"]) + b"\n"
                actions.append({"action_id": f"{family}:{path}", "catalog_id": family,
                                "kind": "write_exact_completion", "path": path,
                                "before_sha256": _file_before(root, path),
                                "expected_after_sha256": "sha256:" + raw_sha(data),
                                "provider": "R1", "provider_operation": "exact_completion_projection",
                                "expected_state": {"bytes_b64": base64.b64encode(data).decode("ascii")}})
            else:
                waivers.append({"catalog_id": family, "path": path})
        elif family in MECHANICAL_FAMILIES:
            path = event.get("path")
            if family in {"F11", "F12"}:
                if family == "F12" and not isinstance(r1.get("lanes"), list):
                    unresolved.append(family); continue
                rel = path if isinstance(path, str) else f"docs/dev/dev-report-{task_id}.json"
                try: rel = _safe_rel(root, rel)
                except ContractError: unresolved.append(family); continue
                before = _file_before(root, rel)
                candidate = r1.get("declaration_candidate")
                candidate_digest = r1.get("declaration_candidate_digest")
                candidate_valid = isinstance(candidate, Mapping) \
                    and candidate_digest == digest_value(candidate)
                if before is None and not candidate_valid:
                    unresolved.append(family)
                    continue
                candidate_value = dict(candidate) if isinstance(candidate, Mapping) and candidate_valid else None
                actions.append({"action_id": f"{family}:{rel}", "catalog_id": family,
                                "kind": "r1_declaration_provider", "path": rel,
                                "before_sha256": before, "expected_after_sha256": None,
                                "provider": "artifact_chain_declaration_provider.v1",
                                "provider_operation": "default_aggregate",
                                "expected_state": {
                                    "cas": "exact", "candidate_from_canonical": before is not None,
                                    "candidate": candidate_value,
                                    "candidate_digest": candidate_digest if candidate_valid else None,
                                    "expected_phase_digest": r1.get("phase_digest"),
                                }})
                continue
            if family == "F19":
                actions.append({"action_id": "F19:single-pristine-retry", "catalog_id": family,
                                "kind": "authorize_single_pristine_retry", "path": "docs/dev",
                                "before_sha256": None, "expected_after_sha256": None,
                                "provider": None, "provider_operation": None,
                                "expected_state": {"commit_count": 0}})
                continue
            if not isinstance(path, str): unresolved.append(family); continue
            try: rel = _safe_rel(root, path)
            except ContractError: unresolved.append(family); continue
            target = root / rel
            repair_data: bytes | None = None
            if family == "F14":
                repair_data = _canonicalize_final_line(target, "CLOSE")
                if repair_data is not None and repair_data.rstrip().endswith(b"CLOSE: NO"):
                    promoted_protected.append("F22")
                    continue
            elif family == "F18":
                repair_data = _canonicalize_final_line(target, "COMMIT")
                if repair_data is not None and repair_data.rstrip().endswith(b"COMMIT: REJECT"):
                    promoted_protected.append("F17")
                    continue
            elif family in {"F03", "F04", "F05", "F06"}:
                repair_data = _json_repair_bytes(root, target, family, task_id, r1, event)
            # F13 only admits an exact duplicate already declared by R1 with matching expected sha.
            elif family == "F13":
                duplicate = event.get("authoritative_duplicate")
                expected = event.get("expected_sha256")
                declared = {x["path"]: x for x in r1.get("artifact_paths", []) if isinstance(x, Mapping) and isinstance(x.get("path"), str)}
                if isinstance(duplicate, str) and duplicate in declared and declared[duplicate].get("sha256") == expected \
                        and _is_digest(expected):
                    dup = root / _safe_rel(root, duplicate)
                    if _typed_path_state(dup).get("content_sha256") == expected:
                        repair_data = dup.read_bytes()
            if repair_data is None:
                unresolved.append(family); continue
            actions.append({"action_id": f"{family}:{rel}", "catalog_id": family,
                            "kind": "write_exact_bytes", "path": rel,
                            "before_sha256": _file_before(root, rel),
                            "expected_after_sha256": "sha256:" + raw_sha(repair_data),
                            "provider": "LANE-F", "provider_operation": "expected_state_atomic_replace",
                            "expected_state": {"bytes_b64": base64.b64encode(repair_data).decode("ascii")}})
    if promoted_protected:
        decision = {"root_decision_ids": sorted(set([*decision["root_decision_ids"], *promoted_protected])),
                    "secondary_evidence_codes": decision["secondary_evidence_codes"],
                    "disposition": "protected_refusal", "protected": True}
        return [], [], decision
    if unresolved:
        decision = {"root_decision_ids": sorted(set([*decision["root_decision_ids"], "U_REPAIR_AMBIGUOUS"])),
                    "secondary_evidence_codes": decision["secondary_evidence_codes"],
                    "disposition": "protected_refusal", "protected": True}
        return [], [], decision
    return sorted(actions, key=lambda x: x["action_id"]), sorted(waivers, key=lambda x: (x["catalog_id"], x["path"])), decision


def _template(entrypoint: str, r1_digest: str) -> dict[str, Any]:
    if entrypoint == "close":
        kinds = ["cleanliness_inspector_report", "close_report", "prompt_inspector_report",
                 "qa_checkpoint_if_applicable", "style_inspector_report"]
        gate_kind = "close_artifact_chain_and_verdict"
        ceiling = None
    else:
        kinds = ["active_grant_pointer", "commit_grant_slot", "commit_qa_report",
                 "dispatch_manifest", "push_token", "repository_transaction"]
        gate_kind = "commit_preflight_and_transaction"
        ceiling = r1_digest
    value = {"schema_version": TEMPLATE_SCHEMA, "entrypoint": entrypoint,
             "gate_kind": gate_kind, "required_output_kinds": sorted(kinds),
             "repository_ceiling_source": ceiling, "template_digest": None}
    value["template_digest"] = digest_value(value, "template_digest")
    return value


def _make_plan(root: Path, task_id: str, req: Mapping[str, Any], r1: Mapping[str, Any],
               inventory_digest: str, r1_digest: str, decision: dict[str, Any],
               classified: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    identity = {"schema_version": RUN_SCHEMA, "canonical_project_root": str(root),
                "task_id": task_id, "entrypoint": req["entrypoint"],
                "origin_session_id": req["session_id"], "origin_invocation_id": req["invocation_id"],
                "request_digest": req["request_digest"], "inventory_digest_before": inventory_digest,
                "r1_result_digest": r1_digest, "run_id": None}
    identity["run_id"] = digest_value(identity, "run_id")
    actions, waiver_candidates, decision = _derive_actions(root, task_id, r1, classified, decision)
    # A waiver preview has no gate authority.  Its immutable plan can be
    # confirmed later, at which point apply resolves a required handoff from
    # the template.  Only an executable deterministic action plan advertises a
    # gate at prepare time.
    gate_required = bool(actions) and req["intent"] == "execute" and not decision["protected"] \
        and decision["disposition"] != "route_required"
    plan = {"schema_version": PLAN_SCHEMA, "run_id": identity["run_id"],
            "entrypoint": req["entrypoint"], "origin_invocation_id": req["invocation_id"],
            "origin_session_id": req["session_id"], "request_digest": req["request_digest"],
            "r1_result_digest": r1_digest, "inventory_digest": inventory_digest,
            "actions": actions, "waivers": waiver_candidates, "gate_required": gate_required,
            "gate_kind": _template(req["entrypoint"], r1_digest)["gate_kind"] if gate_required else None,
            "allowed_mutations": _template(req["entrypoint"], r1_digest), "plan_digest": None}
    plan["plan_digest"] = digest_value(plan, "plan_digest")
    return identity, plan | {"_decision": decision}


def _public_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in plan.items() if not k.startswith("_")}


def _planned_mutations(plan: Mapping[str, Any], status: str = "planned") -> list[dict[str, Any]]:
    return [{"action_id": x["action_id"], "catalog_id": x["catalog_id"], "kind": x["kind"],
             "path": x["path"], "before_sha256": x["before_sha256"],
             "expected_after_sha256": x["expected_after_sha256"], "observed_after_sha256": None,
             "provider_schema": x["provider"], "provider_result_digest": None, "status": status}
            for x in plan.get("actions", [])]


def _planned_waivers(plan: Mapping[str, Any], status: str = "planned",
                     grant: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    rows = []
    for x in plan.get("waivers", []):
        if grant:
            reason_digest = digest_value({"reason": grant["reason"]})
            grant_digest = grant["confirmation_grant_digest"]
        else:
            reason_digest = digest_value({"state": "pending_human_reason", "catalog_id": x["catalog_id"], "path": x["path"]})
            grant_digest = digest_value({"state": "pending_confirmation", "catalog_id": x["catalog_id"], "path": x["path"]})
        rows.append({"catalog_id": x["catalog_id"], "path": x["path"],
                     "reason_digest": reason_digest, "confirmation_grant_digest": grant_digest,
                     "projection_digest": None, "status": status})
    return rows


def _result_from_run(req: Mapping[str, Any], run: Mapping[str, Any], audit_path: Path,
                     audit_generation: int, audit_sha: str, *, status: str, action: str,
                     errors: Sequence[dict[str, Any]] = (), next_kind: str = "none",
                     human_command: str | None = None) -> dict[str, Any]:
    result = _base_result(req["operation"])
    plan = run["plan"]
    result.update({"status": status, "action": action, "project_root": run["identity"]["canonical_project_root"],
                   "task_id": run["identity"]["task_id"], "entrypoint": run["identity"]["entrypoint"],
                   "invocation_id": req["invocation_id"], "origin_invocation_id": run["identity"]["origin_invocation_id"],
                   "gate_invocation_id": run.get("gate_invocation_id"),
                   "origin_session_id": run["identity"]["origin_session_id"],
                   "identity_adoption_digest": run.get("identity_adoption_digest"),
                   "gate_preclaim_digest": run.get("gate_preclaim_digest"),
                   "request_digest": req["request_digest"], "run_id": run["run_id"],
                   "audit_path": str(audit_path), "audit_generation": audit_generation,
                   "audit_sha256": audit_sha, "inventory_digest_before": run["identity"]["inventory_digest_before"],
                   "inventory_digest_after": run.get("inventory_digest_after"),
                   "plan_digest": plan["plan_digest"], "decision": run["decision"],
                   "plan": _public_plan(plan), "mutations": run.get("mutations", _planned_mutations(plan)),
                   "waivers": run.get("waivers", _planned_waivers(plan)),
                   "gate_handoff": run.get("gate_handoff", _gate_handoff_empty()),
                   "next_action": {"kind": next_kind, "human_command": human_command},
                   "errors": list(errors)})
    return _finish_result(result)


def _prepare(req: Mapping[str, Any], root: Path) -> dict[str, Any]:
    r1, r1_digest, inventory, inventory_digest = _r1_snapshot(root, req["task_id"])
    decision, classified = classify_r1(r1, req["entrypoint"], root, req["task_id"])
    identity, plan_raw = _make_plan(root, req["task_id"], req, r1, inventory_digest,
                                    r1_digest, decision, classified)
    decision = plan_raw.pop("_decision")
    plan = plan_raw
    with _task_lock(root, req["task_id"]) as audit_path:
        audit, audit_sha = _read_audit(audit_path, root, req["task_id"])
        existing = [x for x in audit["runs"] if isinstance(x, dict) and x.get("request_digest") == req["request_digest"]]
        if existing:
            run = existing[0]
            if run["identity"]["r1_result_digest"] != r1_digest \
                    or run["identity"]["inventory_digest_before"] != inventory_digest:
                raise ContractError("INVENTORY_DRIFT", "prepare replay authority changed",
                                    expected={"r1": run["identity"]["r1_result_digest"],
                                              "inventory": run["identity"]["inventory_digest_before"]},
                                    observed={"r1": r1_digest, "inventory": inventory_digest})
            status, action, next_kind, human = _projection_for_state(run)
            return _result_from_run(req, run, audit_path, audit["generation"], audit_sha or "",
                                    status=status, action=action, next_kind=next_kind, human_command=human)
        nonce = secrets.token_hex(16) if plan["waivers"] else None
        state = "PREPARED"
        status = "prepared"
        action = "plan_prepared"
        next_kind = "call_apply"
        human = None
        errors: list[dict[str, Any]] = []
        if decision["protected"]:
            state, status, action, next_kind = "REFUSED", "refused", "none", "none"
            errors = [_error("PROTECTED_INTEGRITY_REFUSAL", "protected or ambiguous lifecycle evidence")]
        elif decision["disposition"] == "route_required":
            state, status, action = "ROUTE_REQUIRED", "route_required", "route_emitted"
            next_kind = "invoke_close_fix" if {"F15", "F16"} & set(decision["root_decision_ids"]) else "manual_recovery"
            if {"F15", "F16"} & set(decision["root_decision_ids"]):
                human = f"/close {req['task_id']} --fix"
            elif "F20" in decision["root_decision_ids"]:
                human = "Restart the session, then submit a fresh human /commit --bulk"
            elif "F08" in decision["root_decision_ids"]:
                human = f"Continue the ordinary QA phase for {req['task_id']}"
            else:
                human = f"/close {req['task_id']} --fix"
            errors = [_error("ROUTE_REQUIRED", "a separate later human invocation is required")]
        elif plan["waivers"]:
            if req["entrypoint"] != "close" or req["intent"] != "preview":
                state, status, action, next_kind = "REFUSED", "refused", "none", "none"
                errors = [_error("CONFIRMATION_REQUIRED", "F01/F02 require a /close --fix preview then later human confirmation")]
            else:
                state, action, next_kind = "PREVIEWED", "preview_emitted", "submit_confirmation"
                specs = " ".join(f"--waive {x['catalog_id']}:{x['path']}" for x in plan["waivers"])
                human = (f"/close {req['task_id']} --fix --confirm {nonce} --digest {plan['plan_digest']} "
                         f"{specs} --reason \"<non-empty human reason>\"")
        elif decision["disposition"] == "no_blocker":
            state, status, action, next_kind = "FINAL", "no_action", "none", "none"
        elif req["intent"] != "execute":
            state, status, action, next_kind = "REFUSED", "refused", "none", "none"
            errors = [_error("INVALID_REQUEST", "mechanical repairs require intent=execute", field="intent")]
        run = {"run_id": identity["run_id"], "request_digest": req["request_digest"],
               "identity": identity, "plan": plan, "decision": decision,
               "classified_events": classified, "inventory_before": inventory,
               "inventory_digest_after": inventory_digest if state == "FINAL" else None,
               "state": state, "state_history": [{"state": state, "at": _now()}],
               "confirmation_nonce": nonce, "gate_invocation_id": None,
               "identity_adoption_digest": None, "gate_preclaim_digest": None,
               "mutations": _planned_mutations(plan), "waivers": _planned_waivers(plan),
               "gate_handoff": _gate_handoff_empty(), "gate_attempt_count": 0,
               "gate_receipt_digest": None, "ownership_admission_digest": req["expected_ownership_audit_digest"]}
        if state == "ROUTE_REQUIRED":
            run["route_next_kind"] = next_kind
            run["route_human_command"] = human
        audit["runs"].append(run)
        generation, audit_sha = _persist_audit(audit_path, audit)
        return _result_from_run(req, run, audit_path, generation, audit_sha,
                                status=status, action=action, errors=errors,
                                next_kind=next_kind, human_command=human)


def _projection_for_state(run: Mapping[str, Any]) -> tuple[str, str, str, str | None]:
    state = run.get("state")
    if state == "PREVIEWED":
        nonce = run.get("confirmation_nonce")
        plan = run["plan"]
        specs = " ".join(f"--waive {x['catalog_id']}:{x['path']}" for x in plan["waivers"])
        cmd = (f"/close {run['identity']['task_id']} --fix --confirm {nonce} --digest {plan['plan_digest']} "
               f"{specs} --reason \"<non-empty human reason>\"")
        return "prepared", "preview_emitted", "submit_confirmation", cmd
    if state == "PREPARED": return "prepared", "plan_prepared", "call_apply", None
    if state == "GATE_READY": return "awaiting_gate", "actions_applied", "call_claim_gate", None
    if state == "GATE_CLAIMED":
        kind = "run_close_gate_once" if run["identity"]["entrypoint"] == "close" else "run_commit_gate_once"
        return "awaiting_gate", "gate_claimed", kind, None
    if state == "FINAL":
        return ("finalized", "gate_recorded", "none", None) if run.get("gate_handoff", {}).get("required") else ("no_action", "none", "none", None)
    if state == "ROUTE_REQUIRED":
        return ("route_required", "route_emitted", run.get("route_next_kind", "manual_recovery"),
                run.get("route_human_command"))
    if state == "RECOVERY_REQUIRED": return "recovery_required", "none", "manual_recovery", None
    if state == "REFUSED": return "refused", "none", "none", None
    return "recovery_required", "none", "manual_recovery", None


def _validate_preclaim(value: Any, expected_digest: str | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("GATE_PRECLAIM_INVALID", "preclaim must be an object")
    common = {"schema_version", "project_root", "task_id", "entrypoint", "current_invocation_id",
              "run_id", "plan_digest", "artifact_chain_result_digest", "variant", "evidence_digest"}
    close = {"resolved_spec_id", "resolved_cp_state_path", "checkpoint_applicable",
             "cycle_diff_digest", "inspector_output_paths", "close_report_path"}
    commit = {"close_report_digest", "repository_plan", "repository_plan_digest",
              "commit_qa_report_path", "manifest_path", "grant_slot_descriptors", "push_token_paths"}
    variant = value.get("variant")
    required = common | (close if variant == "close" else commit if variant == "commit" else set())
    if variant not in {"close", "commit"} or set(value) != required:
        raise ContractError("GATE_PRECLAIM_INVALID", "preclaim field set/variant is invalid")
    if value.get("schema_version") != PRECLAIM_SCHEMA or value.get("entrypoint") != variant:
        raise ContractError("GATE_PRECLAIM_INVALID", "preclaim schema/entrypoint mismatch")
    for key in ("run_id", "plan_digest", "artifact_chain_result_digest", "evidence_digest"):
        if not _is_digest(value.get(key)):
            raise ContractError("GATE_PRECLAIM_INVALID", "preclaim digest invalid", field=key)
    if not _is_uuid(value.get("current_invocation_id")):
        raise ContractError("GATE_PRECLAIM_INVALID", "preclaim invocation invalid")
    observed = digest_value(value, "evidence_digest")
    if value["evidence_digest"] != observed or (expected_digest and expected_digest != observed):
        raise ContractError("GATE_PRECLAIM_INVALID", "preclaim digest mismatch",
                            expected=observed, observed=value.get("evidence_digest"))
    if variant == "close":
        if not isinstance(value["checkpoint_applicable"], bool) or not isinstance(value["inspector_output_paths"], list) \
                or not _is_digest(value["cycle_diff_digest"]):
            raise ContractError("GATE_PRECLAIM_INVALID", "close preclaim types invalid")
        if len(value["inspector_output_paths"]) != 3 or len(set(value["inspector_output_paths"])) != 3:
            raise ContractError("GATE_PRECLAIM_INVALID", "exactly three inspector paths are required")
        if value["checkpoint_applicable"] != (value["resolved_cp_state_path"] is not None):
            raise ContractError("GATE_PRECLAIM_INVALID", "checkpoint applicability mismatch")
        if value["resolved_spec_id"] is not None and not isinstance(value["resolved_spec_id"], str):
            raise ContractError("GATE_PRECLAIM_INVALID", "resolved spec id is invalid")
        if not isinstance(value["close_report_path"], str) \
                or not all(isinstance(item, str) for item in value["inspector_output_paths"]):
            raise ContractError("GATE_PRECLAIM_INVALID", "close output paths are invalid")
    else:
        if not isinstance(value["repository_plan"], list) or not isinstance(value["grant_slot_descriptors"], list) \
                or not isinstance(value["push_token_paths"], list) or not _is_digest(value["close_report_digest"]) \
                or not isinstance(value["commit_qa_report_path"], str) \
                or not isinstance(value["manifest_path"], str):
            raise ContractError("GATE_PRECLAIM_INVALID", "commit preclaim types invalid")
        if value["repository_plan_digest"] != digest_value(value["repository_plan"]):
            raise ContractError("GATE_PRECLAIM_INVALID", "repository plan digest mismatch")
        if len(value["repository_plan"]) != len(value["push_token_paths"]) \
                or not all(isinstance(item, str) for item in value["push_token_paths"]):
            raise ContractError("GATE_PRECLAIM_INVALID", "repository/token cardinality mismatch")
    return value


def _state_for_descriptor(path: str) -> str:
    return _typed_path_state(Path(path))["state_digest"]


def _resolve_allowed_mutations(root: Path, task_id: str, run: Mapping[str, Any],
                               preclaim: Mapping[str, Any], gate_id: str) -> dict[str, Any]:
    template = run["plan"]["allowed_mutations"]
    template_fields = {"schema_version", "entrypoint", "gate_kind", "required_output_kinds",
                       "repository_ceiling_source", "template_digest"}
    if not isinstance(template, Mapping) or set(template) != template_fields \
            or template.get("schema_version") != TEMPLATE_SCHEMA \
            or template.get("template_digest") != digest_value(template, "template_digest"):
        raise ContractError("PLAN_DIGEST_MISMATCH", "mutation-envelope template is invalid")
    if preclaim["project_root"] != str(root) or preclaim["task_id"] != task_id \
            or preclaim["entrypoint"] != run["identity"]["entrypoint"] \
            or preclaim["run_id"] != run["run_id"] or preclaim["plan_digest"] != run["plan"]["plan_digest"] \
            or preclaim["artifact_chain_result_digest"] != run["identity"]["r1_result_digest"] \
            or preclaim["current_invocation_id"] != gate_id:
        raise ContractError("GATE_PRECLAIM_INVALID", "preclaim identity does not bind the run")
    paths: list[dict[str, Any]] = []
    slots: list[dict[str, Any]] = []
    repos: list[dict[str, Any]] = []
    def path_entry(entry_id: str, value: str, kind: str, mutation: str, producer: str, required: bool) -> None:
        p = Path(value)
        if not p.is_absolute(): p = root / _safe_rel(root, value)
        canonical_parent = Path(os.path.realpath(p.parent))
        if canonical_parent != p.parent or p.parent.is_symlink():
            raise ContractError("GATE_PRECLAIM_INVALID", "output parent is not a canonical directory")
        if kind == "project_artifact":
            try:
                (canonical_parent / p.name).relative_to(root)
            except ValueError as exc:
                raise ContractError("GATE_PRECLAIM_INVALID", "project output path escapes root") from exc
        elif kind == "tmp_control":
            try:
                canonical_parent.relative_to("/tmp")
            except ValueError as exc:
                raise ContractError("GATE_PRECLAIM_INVALID", "temporary control output is not under /tmp") from exc
        canonical = str(canonical_parent / p.name)
        before = _typed_path_state(Path(canonical))
        if before["state"] not in {"absent", "file"}:
            raise ContractError("GATE_PRECLAIM_INVALID", "output pre-state is not absent/regular",
                                field=canonical, observed=before["state"])
        paths.append({"entry_id": entry_id, "canonical_path": canonical, "path_kind": kind,
                      "mutation_class": mutation, "producer": producer, "required": required,
                      "before_state_digest": before["state_digest"],
                      "allowed_final_state": {"states": ["file"] if required else ["absent", "file"]}})
    if preclaim["variant"] == "close":
        expected = {
            str(root / f"docs/dev/style-inspector-report-{task_id}.json"),
            str(root / f"docs/dev/cleanliness-inspector-report-{task_id}.json"),
            str(root / f"docs/dev/prompt-inspector-report-{task_id}.json"),
        }
        observed = {str(Path(x) if os.path.isabs(x) else root / _safe_rel(root, x))
                    for x in preclaim["inspector_output_paths"]}
        if observed != expected:
            raise ContractError("GATE_PRECLAIM_INVALID", "inspector output paths are not exact",
                                expected=sorted(expected), observed=sorted(observed))
        for p in sorted(expected):
            name = Path(p).name.split("-inspector-report", 1)[0].split("/")[-1]
            path_entry(name + "-inspector-report", p, "project_artifact", "create_or_replace",
                       name + "-inspector", True)
        close_expected = str(root / f"docs/dev/close-report-{task_id}.md")
        close_observed = str(Path(preclaim["close_report_path"]) if os.path.isabs(preclaim["close_report_path"])
                             else root / _safe_rel(root, preclaim["close_report_path"]))
        if close_observed != close_expected:
            raise ContractError("GATE_PRECLAIM_INVALID", "close report path is not exact")
        path_entry("close-report", close_observed, "project_artifact", "create_or_replace", "LANE-L", True)
        if preclaim["checkpoint_applicable"]:
            cp = Path(preclaim["resolved_cp_state_path"])
            if not isinstance(preclaim["resolved_spec_id"], str) or not preclaim["resolved_spec_id"] \
                    or not cp.is_absolute() or cp.name != "cp-state-qa.json" \
                    or Path(os.path.realpath(cp.parent)) != cp.parent:
                raise ContractError("GATE_PRECLAIM_INVALID", "resolved checkpoint path is invalid")
            try:
                cp.relative_to(root)
            except ValueError as exc:
                raise ContractError("GATE_PRECLAIM_INVALID",
                                    "resolved checkpoint path is outside the project") from exc
            path_entry("qa-checkpoint", str(cp), "checkpoint_state", "modify", "close-QA", True)
        elif preclaim["resolved_spec_id"] not in {None, ""}:
            raise ContractError("GATE_PRECLAIM_INVALID", "spec id exists without checkpoint state")
    else:
        close_path = root / f"docs/dev/close-report-{task_id}.md"
        close_state = _typed_path_state(close_path)
        if close_state["state"] != "file" \
                or preclaim["close_report_digest"] != close_state["content_sha256"]:
            raise ContractError("GATE_PRECLAIM_INVALID", "commit preclaim close report is stale",
                                expected=close_state.get("content_sha256"),
                                observed=preclaim["close_report_digest"])
        qa_expected = str(root / f"docs/dev/commit-qa-report-{task_id}.md")
        qa_observed = str(Path(preclaim["commit_qa_report_path"]) if os.path.isabs(preclaim["commit_qa_report_path"])
                          else root / _safe_rel(root, preclaim["commit_qa_report_path"]))
        if qa_observed != qa_expected:
            raise ContractError("GATE_PRECLAIM_INVALID", "commit QA report path is not exact")
        path_entry("commit-qa-report", qa_observed, "project_artifact", "create_or_replace", "LANE-L", True)
        sid = run["identity"]["origin_session_id"]
        expected_manifest = f"/tmp/claude-commit-manifest-{sid}.json"
        if preclaim["manifest_path"] != expected_manifest:
            raise ContractError("GATE_PRECLAIM_INVALID", "dispatch manifest path is not session-bound")
        path_entry("dispatch-manifest", expected_manifest, "tmp_control", "create_or_replace", "LANE-L", True)
        path_entry("active-grant-pointer", f"/tmp/claude-commit-grant-active-{sid}.json",
                   "tmp_control", "create_consume_or_delete", "commit-guard", False)
        for idx, token in enumerate(sorted(preclaim["push_token_paths"])):
            path_entry(f"push-token-{idx}", token, "tmp_control", "create_or_replace", "commit-guard", False)
        if len(preclaim["grant_slot_descriptors"]) != 1:
            raise ContractError("GATE_PRECLAIM_INVALID", "exactly one bounded commit-grant slot is required")
        for idx, slot in enumerate(preclaim["grant_slot_descriptors"]):
            exact = {"canonical_directory", "anchored_basename_regex", "max_created", "allowed_lifecycle"}
            expected_pattern = rf"^claude\-commit\-grant\-{re.escape(sid)}\-[0-9a-f]{{16}}\.json(?:\.lck)?$"
            expected_max = 2 * len(preclaim["repository_plan"])
            if not isinstance(slot, dict) or set(slot) != exact \
                    or slot["anchored_basename_regex"] != expected_pattern \
                    or slot["max_created"] != expected_max \
                    or slot["allowed_lifecycle"] != "create_then_rename_lck_then_delete":
                raise ContractError("GATE_PRECLAIM_INVALID", "grant slot descriptor is invalid")
            directory = Path(slot["canonical_directory"])
            if str(directory) != "/tmp":
                raise ContractError("GATE_PRECLAIM_INVALID", "grant slots are limited to /tmp")
            members = _slot_members(directory, slot["anchored_basename_regex"])
            slots.append({"slot_id": f"commit-grants-{idx}", **slot,
                          "before_membership_digest": digest_value(members)})
        for idx, repo in enumerate(preclaim["repository_plan"]):
            required = {"repo_root", "git_dir", "before_head", "before_index_digest", "approved_paths",
                        "approved_tree_digest", "allowed_ref", "expected_commit_count_max", "grant_slot_id",
                        "push_token_path", "transaction_digest"}
            if not isinstance(repo, dict) or set(repo) != required or repo["transaction_digest"] != digest_value(repo, "transaction_digest"):
                raise ContractError("GATE_PRECLAIM_INVALID", "repository transaction is invalid")
            if repo["expected_commit_count_max"] != 1 or repo["approved_paths"] != sorted(set(repo["approved_paths"])) \
                    or not all(isinstance(item, str) for item in repo["approved_paths"]) \
                    or repo["grant_slot_id"] != "commit-grants-0":
                raise ContractError("GATE_PRECLAIM_INVALID", "repository transaction exceeds ceiling")
            repo_root = Path(repo["repo_root"])
            if not repo_root.is_absolute() or Path(os.path.realpath(repo_root)) != repo_root:
                raise ContractError("GATE_PRECLAIM_INVALID", "repository root is not canonical")
            try:
                approved_paths = [_safe_rel(repo_root, item) for item in repo["approved_paths"]]
            except ContractError as exc:
                raise ContractError("GATE_PRECLAIM_INVALID", "approved repository path is unsafe") from exc
            if approved_paths != repo["approved_paths"]:
                raise ContractError("GATE_PRECLAIM_INVALID", "approved repository paths are not canonical")
            current = _git_state(repo)
            if current["head"] != repo["before_head"] or current["index_digest"] != repo["before_index_digest"]:
                raise ContractError("INVENTORY_DRIFT", "repository HEAD/index changed before apply")
            if current["approved_worktree_digest"] != repo["approved_tree_digest"]:
                raise ContractError("GATE_PRECLAIM_INVALID",
                                    "approved tree digest does not bind the admitted worktree",
                                    expected=current["approved_worktree_digest"],
                                    observed=repo["approved_tree_digest"])
            branch = _git_output(repo_root, "symbolic-ref", "--quiet", "--short", "HEAD")
            if repo["allowed_ref"] not in {branch, "refs/heads/" + branch}:
                raise ContractError("GATE_PRECLAIM_INVALID", "repository ref binding is invalid")
            git_dir = Path(_git_output(repo_root, "rev-parse", "--absolute-git-dir"))
            if str(git_dir) != repo["git_dir"]:
                raise ContractError("GATE_PRECLAIM_INVALID", "repository git-dir binding is invalid")
            token_expected = Path("/tmp/agentic-commit/push") / hashlib.sha256(
                str(repo_root).encode("utf-8")
            ).hexdigest()[:16] / (branch.replace("/", "__") + ".json")
            if repo["push_token_path"] != str(token_expected) \
                    or repo["push_token_path"] not in preclaim["push_token_paths"]:
                raise ContractError("GATE_PRECLAIM_INVALID", "push token path is not repository-bound")
            repos.append(dict(repo))
        if len({item["repo_root"] for item in repos}) != len(repos):
            raise ContractError("GATE_PRECLAIM_INVALID", "repository plan has duplicate roots")
    value = {"schema_version": ALLOWED_SCHEMA, "project_root": str(root), "task_id": task_id,
             "entrypoint": run["identity"]["entrypoint"], "gate_kind": template["gate_kind"],
             "template_digest": template["template_digest"], "gate_invocation_id": gate_id,
             "path_entries": sorted(paths, key=lambda x: x["entry_id"]),
             "dynamic_slots": sorted(slots, key=lambda x: x["slot_id"]),
             "repository_transactions": sorted(repos, key=lambda x: x["repo_root"]),
             "descriptor_digest": None}
    value["descriptor_digest"] = digest_value(value, "descriptor_digest")
    return value


def _slot_members(directory: Path, pattern: str) -> list[dict[str, Any]]:
    try: rx = re.compile(pattern)
    except re.error as exc: raise ContractError("GATE_PRECLAIM_INVALID", f"invalid bounded slot regex: {exc}") from exc
    rows = []
    if directory.is_dir():
        for name in sorted(os.listdir(directory)):
            if not rx.fullmatch(name): continue
            p = directory / name; state = _typed_path_state(p)
            rows.append({"canonical_path": str(p), "file_type": state["state"],
                         "mode": state.get("mode"), "size": state.get("size"),
                         "content_sha256": state.get("content_sha256")})
    return rows


def _git_output(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(root), *args], stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=20, check=False,
                          env={"PATH": os.environ.get("PATH", "")})
    if proc.returncode != 0:
        raise ContractError("GATE_STATE_DRIFT", "cannot inspect admitted repository",
                            observed=proc.stderr.decode(errors="replace")[:300])
    return proc.stdout.decode("utf-8", errors="strict").strip()


def _git_state(repo: Mapping[str, Any]) -> dict[str, Any]:
    root = Path(repo["repo_root"])
    def run(*args: str) -> bytes:
        p = subprocess.run(["git", "-C", str(root), *args], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=20, check=False,
                           env={"PATH": os.environ.get("PATH", "")})
        if p.returncode != 0: raise ContractError("GATE_STATE_DRIFT", "cannot inspect admitted repository")
        return p.stdout
    def run_optional(*args: str) -> bytes:
        p = subprocess.run(["git", "-C", str(root), *args], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=20, check=False,
                           env={"PATH": os.environ.get("PATH", "")})
        return p.stdout if p.returncode == 0 else b""
    probe = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20,
                           check=False, env={"PATH": os.environ.get("PATH", "")})
    head = probe.stdout.decode().strip() if probe.returncode == 0 else None
    index_digest = digest_value({"index": base64.b64encode(run("ls-files", "--stage", "-z")).decode()})
    approved = []
    for rel in repo["approved_paths"]:
        state = _typed_path_state(root / rel)
        approved.append({"path": rel, "state_digest": state["state_digest"]})
    transactions: list[dict[str, Any]] = []
    if head is not None:
        before = repo.get("before_head")
        rev_args = ("rev-list", "--reverse", f"{before}..{head}") if before else (
            "rev-list", "--reverse", head)
        commits = run(*rev_args).decode("ascii", errors="strict").splitlines()
        for commit in commits:
            parents = run("show", "-s", "--format=%P", commit).decode("ascii").strip().split()
            tree = run("show", "-s", "--format=%T", commit).decode("ascii").strip()
            changed = run("diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "-z", commit)
            paths = sorted(x.decode("utf-8", errors="strict") for x in changed.split(b"\0") if x)
            transactions.append({"commit": commit, "parents": parents, "tree": tree,
                                 "changed_paths": paths})
    reflog = run_optional("reflog", "show", "--format=%H%x00%gD", "-n", "2",
                          repo["allowed_ref"])
    return {"repo_root": str(root), "head": head, "index_digest": index_digest,
            "approved_worktree_digest": digest_value(approved),
            "allowed_ref_digest": digest_value({"ref": repo["allowed_ref"], "head": head}),
            "grant_slot_membership_digest": None,
            "push_token_digest": _typed_path_state(Path(repo["push_token_path"]))["state_digest"],
            "reachable_transaction_digest": digest_value(transactions),
            "transaction_event_digest": digest_value({
                "ref": repo["allowed_ref"],
                "rows_b64": base64.b64encode(reflog).decode("ascii"),
            })}


def _capture_gate_state(allowed: Mapping[str, Any], inventory_digest: str) -> tuple[dict[str, Any], str]:
    path_states = []
    for entry in allowed["path_entries"]:
        p = Path(entry["canonical_path"]); st = _typed_path_state(p)
        path_states.append({"entry_id": entry["entry_id"], "canonical_path": str(p),
                            "exists": st["state"] != "absent", "file_type": st["state"],
                            "mode": st.get("mode"), "size": st.get("size"),
                            "content_sha256": st.get("content_sha256"), "state_digest": st["state_digest"]})
    slot_states = []
    for slot in allowed["dynamic_slots"]:
        members = _slot_members(Path(slot["canonical_directory"]), slot["anchored_basename_regex"])
        slot_states.append({"slot_id": slot["slot_id"], "members": members,
                            "membership_digest": digest_value(members)})
    slot_membership = {row["slot_id"]: row["membership_digest"] for row in slot_states}
    repo_states = []
    for descriptor in allowed["repository_transactions"]:
        repo_state = _git_state(descriptor)
        repo_state["grant_slot_membership_digest"] = slot_membership.get(descriptor["grant_slot_id"])
        repo_states.append(repo_state)
    value = {"schema_version": STATE_SCHEMA, "project_root": allowed["project_root"],
             "task_id": allowed["task_id"], "entrypoint": allowed["entrypoint"],
             "gate_kind": allowed["gate_kind"], "gate_invocation_id": allowed["gate_invocation_id"],
             "inventory_digest": inventory_digest, "allowed_mutations_digest": allowed["descriptor_digest"],
             "path_states": path_states, "dynamic_slot_states": slot_states,
             "repository_states": repo_states}
    return value, digest_value(value)


def _read_confirmation_grant(path_value: Any, run: Mapping[str, Any], req: Mapping[str, Any],
                             root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    expected_path = Path("/tmp") / (
        f"claude-fix-confirmation-{run['identity']['origin_session_id']}-"
        f"{run['confirmation_nonce']}.json"
    )
    if not isinstance(path_value, str) or path_value != str(expected_path):
        raise ContractError("CONFIRMATION_INVALID", "confirmation grant path is not trusted")
    dfd = os.open("/tmp", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        try:
            fd = os.open(expected_path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                         dir_fd=dfd)
        except OSError as exc:
            raise ContractError("CONFIRMATION_INVALID", f"confirmation grant is unavailable: {exc}") from exc
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() \
                    or stat.S_IMODE(st.st_mode) != 0o600 or st.st_nlink != 1 \
                    or st.st_size <= 0 or st.st_size > MAX_STDIN_BYTES:
                raise ContractError("CONFIRMATION_INVALID", "confirmation grant file attributes are invalid")
            chunks = []
            remaining = MAX_STDIN_BYTES + 1
            while remaining:
                chunk = os.read(fd, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            if len(raw) != st.st_size or len(raw) > MAX_STDIN_BYTES:
                raise ContractError("CONFIRMATION_INVALID", "confirmation grant size changed during read")
        finally:
            os.close(fd)
        try:
            current = os.stat(expected_path.name, dir_fd=dfd, follow_symlinks=False)
        except OSError as exc:
            raise ContractError("CONFIRMATION_INVALID", "confirmation grant changed before consumption") from exc
        if (current.st_dev, current.st_ino) != (st.st_dev, st.st_ino) \
                or not stat.S_ISREG(current.st_mode) or current.st_nlink != 1:
            raise ContractError("CONFIRMATION_INVALID", "confirmation grant changed before consumption")
        try:
            grant = strict_json_loads(raw)
        except Exception as exc:
            raise ContractError("CONFIRMATION_INVALID", "confirmation grant is malformed") from exc
        exact = {"schema_version", "origin", "session_id", "prompt_id_or_prompt_sha256",
                 "canonical_project_root", "task_id", "command", "nonce", "preview_run_id",
                 "preview_request_digest", "preview_plan_digest", "preview_invocation_id",
                 "preview_inventory_digest", "confirmation_prompt_digest", "waivers", "reason",
                 "created_at", "expires_at", "confirmation_grant_digest"}
        if not isinstance(grant, dict) or set(grant) != exact:
            raise ContractError("CONFIRMATION_INVALID", "confirmation grant fields are not exact")
        if grant["schema_version"] != GRANT_SCHEMA or grant["origin"] != "userpromptsubmit-hook" \
                or grant["command"] != "close" or grant["session_id"] != run["identity"]["origin_session_id"] \
                or grant["canonical_project_root"] != str(root) or grant["task_id"] != run["identity"]["task_id"] \
                or grant["nonce"] != run["confirmation_nonce"] or grant["preview_run_id"] != run["run_id"] \
                or grant["preview_request_digest"] != run["identity"]["request_digest"] \
                or grant["preview_plan_digest"] != run["plan"]["plan_digest"] \
                or grant["preview_invocation_id"] != run["identity"]["origin_invocation_id"] \
                or grant["preview_inventory_digest"] != run["identity"]["inventory_digest_before"]:
            raise ContractError("CONFIRMATION_INVALID", "confirmation grant binding mismatch")
        if req["invocation_id"] == run["identity"]["origin_invocation_id"]:
            raise ContractError("CONFIRMATION_INVALID", "same invocation cannot confirm its own preview")
        if not isinstance(grant["reason"], str) or not grant["reason"].strip():
            raise ContractError("CONFIRMATION_INVALID", "human reason is empty")
        if grant["waivers"] != run["plan"]["waivers"]:
            raise ContractError("CONFIRMATION_INVALID", "waiver set differs from preview")
        created, expires = _parse_time(grant["created_at"]), _parse_time(grant["expires_at"])
        now = datetime.now(timezone.utc)
        if not (created < expires and (expires - created).total_seconds() <= 600 and created <= now < expires):
            raise ContractError("CONFIRMATION_INVALID", "confirmation grant is stale")
        if grant["confirmation_grant_digest"] != digest_value(grant, "confirmation_grant_digest"):
            raise ContractError("CONFIRMATION_INVALID", "confirmation grant digest mismatch")
        expected_prompt_invocation = _confirmation_invocation_id(
            grant["confirmation_prompt_digest"])
        prompt_identity = grant["prompt_id_or_prompt_sha256"]
        if not _is_uuid(prompt_identity) or prompt_identity != expected_prompt_invocation \
                or req["invocation_id"] != expected_prompt_invocation:
            raise ContractError(
                "CONFIRMATION_INVALID",
                "apply invocation is not the trusted Prompt-2 invocation",
                field="invocation_id", expected=expected_prompt_invocation,
                observed=req["invocation_id"])
        token = {
            "path": str(expected_path), "st_dev": st.st_dev, "st_ino": st.st_ino,
            "st_size": st.st_size, "raw_sha256": raw_sha(raw),
        }
        return grant, token
    finally:
        os.close(dfd)


def _consume_confirmation_grant(path_value: Any, token: Mapping[str, Any]) -> str:
    """Consume only the exact grant already bound by a durable CONFIRMED audit.

    The durable audit is the authorization linearization point.  A crash before
    it leaves the capability untouched; a crash after it leaves either the exact
    inert grant or an absent grant, both of which are safe to resume.
    """
    if not isinstance(path_value, str) or path_value != token.get("path"):
        raise ContractError("CONFIRMATION_INVALID", "confirmation consumption path mismatch")
    path = Path(path_value)
    if path.parent != Path("/tmp"):
        raise ContractError("CONFIRMATION_INVALID", "confirmation consumption path is not trusted")
    dfd = os.open("/tmp", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dfd)
        except FileNotFoundError:
            return "already_absent"
        except OSError as exc:
            raise ContractError("DURABILITY_UNCERTAIN", "confirmation grant cannot be reopened") from exc
        try:
            st = os.fstat(fd)
            chunks = []
            remaining = MAX_STDIN_BYTES + 1
            while remaining:
                chunk = os.read(fd, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
        finally:
            os.close(fd)
        expected_stat = (token.get("st_dev"), token.get("st_ino"), token.get("st_size"))
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() \
                or stat.S_IMODE(st.st_mode) != 0o600 or st.st_nlink != 1 \
                or (st.st_dev, st.st_ino, st.st_size) != expected_stat \
                or raw_sha(raw) != token.get("raw_sha256"):
            raise ContractError("DURABILITY_UNCERTAIN", "confirmation grant changed before consumption")
        try:
            current = os.stat(path.name, dir_fd=dfd, follow_symlinks=False)
        except OSError as exc:
            raise ContractError("DURABILITY_UNCERTAIN", "confirmation grant changed before consumption") from exc
        if (current.st_dev, current.st_ino, current.st_size) != expected_stat \
                or not stat.S_ISREG(current.st_mode) or current.st_nlink != 1:
            raise ContractError("DURABILITY_UNCERTAIN", "confirmation grant changed before consumption")
        try:
            os.unlink(path.name, dir_fd=dfd)
            os.fsync(dfd)
        except OSError as exc:
            raise ContractError("DURABILITY_UNCERTAIN", "confirmed grant cleanup is not durable") from exc
        return "consumed"
    finally:
        os.close(dfd)


def _atomic_exact_write(root: Path, path: Path, data: bytes, expected_before: str | None) -> str:
    """CAS-replace one regular file through a verified, non-symlink directory fd."""
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ContractError("INVENTORY_DRIFT", "repair target escapes project root") from exc
    if not path.parent.is_dir() or path.parent.is_symlink() \
            or Path(os.path.realpath(path.parent)) != path.parent:
        raise ContractError("INVENTORY_DRIFT", "repair target parent is not canonical",
                            field=str(path.parent))
    dfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    temp_name = "." + path.name + ".fix-" + secrets.token_hex(16)
    try:
        current: str | None
        original_identity: tuple[int, int] | None = None
        target_mode = 0o644
        try:
            current_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dfd)
        except FileNotFoundError:
            current = None
        except OSError as exc:
            raise ContractError("INVENTORY_DRIFT", f"cannot inspect repair target: {exc}") from exc
        else:
            try:
                st = os.fstat(current_fd)
                if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or st.st_nlink != 1:
                    raise ContractError("INVENTORY_DRIFT", "repair target is not one regular file")
                original_identity = (st.st_dev, st.st_ino)
                target_mode = stat.S_IMODE(st.st_mode)
                chunks = []
                while True:
                    chunk = os.read(current_fd, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                current = "sha256:" + raw_sha(b"".join(chunks))
            finally:
                os.close(current_fd)
        if current != expected_before:
            raise ContractError("INVENTORY_DRIFT", "repair target changed before mutation",
                                field=str(path), expected=expected_before, observed=current)
        fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     target_mode, dir_fd=dfd)
        try:
            with os.fdopen(fd, "wb", closefd=True) as handle:
                os.fchmod(handle.fileno(), target_mode)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
                written = os.fstat(handle.fileno())
                if not stat.S_ISREG(written.st_mode) or written.st_nlink != 1 \
                        or stat.S_IMODE(written.st_mode) != target_mode or written.st_size != len(data):
                    raise ContractError("DURABILITY_UNCERTAIN", "repair temporary file attributes differ")
            # Revalidate the exact expected state immediately before replace.
            try:
                verify_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                    dir_fd=dfd)
            except FileNotFoundError:
                verify_current = None
                verify_identity = None
            except OSError as exc:
                raise ContractError("INVENTORY_DRIFT", f"cannot recheck repair target: {exc}") from exc
            else:
                try:
                    verify_stat = os.fstat(verify_fd)
                    if not stat.S_ISREG(verify_stat.st_mode) or verify_stat.st_uid != os.geteuid() \
                            or verify_stat.st_nlink != 1:
                        raise ContractError("INVENTORY_DRIFT", "repair target changed type before replace")
                    verify_hash = hashlib.sha256()
                    while True:
                        chunk = os.read(verify_fd, 1024 * 1024)
                        if not chunk:
                            break
                        verify_hash.update(chunk)
                    verify_current = "sha256:" + verify_hash.hexdigest()
                    verify_identity = (verify_stat.st_dev, verify_stat.st_ino)
                finally:
                    os.close(verify_fd)
            if verify_current != expected_before or verify_identity != original_identity:
                raise ContractError("INVENTORY_DRIFT", "repair target raced before replace",
                                    field=str(path), expected=expected_before,
                                    observed=verify_current)
            os.replace(temp_name, path.name, src_dir_fd=dfd, dst_dir_fd=dfd)
            os.fsync(dfd)
        except Exception:
            try:
                os.unlink(temp_name, dir_fd=dfd)
            except OSError:
                pass
            raise
        observed_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dfd)
        try:
            observed = b""
            while True:
                chunk = os.read(observed_fd, 1024 * 1024)
                if not chunk:
                    break
                observed += chunk
        finally:
            os.close(observed_fd)
        post = os.stat(path.name, dir_fd=dfd, follow_symlinks=False)
        if observed != data or not stat.S_ISREG(post.st_mode) or post.st_nlink != 1 \
                or stat.S_IMODE(post.st_mode) != target_mode:
            raise ContractError("DURABILITY_UNCERTAIN", "repair post-write bytes differ")
        return "sha256:" + raw_sha(observed)
    finally:
        os.close(dfd)


def _invoke_r1_provider(root: Path, task_id: str, action: Mapping[str, Any]) -> tuple[str, str]:
    script = root / "scripts/aggregate-dev-report.py"
    spec = importlib.util.spec_from_file_location("_lane_f_r1_provider", script)
    if spec is None or spec.loader is None:
        raise ContractError("ACTION_FAILED", "cannot load R1 declaration provider")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    before = action["before_sha256"]
    expected_state = action["expected_state"]
    candidate = expected_state.get("candidate")
    candidate_from_canonical = expected_state.get("candidate_from_canonical") is True
    result = mod.apply_artifact_chain_declaration(
        str(root), task_id, candidate,
        candidate_from_canonical=candidate_from_canonical,
        operation="default_aggregate",
        expected_canonical_sha256=before.removeprefix("sha256:") if before else None,
        expect_canonical_absent=before is None,
        expected_phase_digest=expected_state.get("expected_phase_digest") if before else None,
        dry_run=False)
    if not isinstance(result, dict) or result.get("schema_version") != "artifact_chain_declaration_provider.v1" \
            or result.get("status") != "ok" or result.get("mutation_state") not in {"committed_durable", "none"}:
        raise ContractError("ACTION_FAILED", "R1 provider did not return durable pass")
    digest = digest_value(result)
    try:
        path = root / _safe_rel(root, result["canonical_path"])
    except (KeyError, ContractError) as exc:
        raise ContractError("ACTION_FAILED", "R1 provider canonical path is invalid") from exc
    state = _typed_path_state(path)
    if state["state"] != "file":
        raise ContractError("DURABILITY_UNCERTAIN", "R1 provider canonical post-state absent")
    if result.get("observed_canonical_sha256") != state["content_sha256"].removeprefix("sha256:"):
        raise ContractError("DURABILITY_UNCERTAIN", "R1 provider result/post-state digest mismatch")
    return state["content_sha256"], digest


def _apply(req: Mapping[str, Any], root: Path) -> dict[str, Any]:
    with _task_lock(root, req["task_id"]) as audit_path:
        audit, audit_sha = _read_audit(audit_path, root, req["task_id"], allow_absent=False)
        run = _find_run(audit, req["run_id"])
        if run["identity"]["canonical_project_root"] != str(root) \
                or run["identity"]["task_id"] != req["task_id"] \
                or run["identity"]["entrypoint"] != req["entrypoint"]:
            raise ContractError("ENTRYPOINT_MISMATCH", "apply identity differs from prepared run")
        if run.get("apply_request_digest") == req["request_digest"] \
                and run["state"] in {"GATE_READY", "GATE_CLAIMED"}:
            status, action, next_kind, human = _projection_for_state(run)
            return _result_from_run(req, run, audit_path, audit["generation"], audit_sha or "",
                                    status=status, action=action, next_kind=next_kind,
                                    human_command=human)
        _check_audit_cas(audit, audit_sha, req)
        if run["identity"]["origin_invocation_id"] != req["expected_origin_invocation_id"] \
                or run["plan"]["plan_digest"] != req["expected_plan_digest"] \
                or run["identity"]["inventory_digest_before"] != req["expected_inventory_digest"]:
            raise ContractError("PLAN_DIGEST_MISMATCH", "run/plan/inventory CAS mismatch")
        if run["identity"]["origin_session_id"] != req["session_id"]:
            raise ContractError("CONFIRMATION_INVALID", "session differs from prepared run")
        preclaim = _validate_preclaim(req["gate_preclaim_evidence"], req["expected_gate_preclaim_digest"])
        if run["state"] not in {"PREPARED", "PREVIEWED", "CONFIRMED"}:
            raise ContractError("AUDIT_CAS_MISMATCH", "run is not applyable", observed=run["state"])
        # The retained preclaim is a binding, not a replacement for an immediate
        # provider/inventory CAS.  Re-read R1 under the task lock before consuming
        # consent or persisting any action intent.
        try:
            _pre_r1, pre_r1_digest, _pre_inventory, pre_inventory_digest = _r1_snapshot(
                root, req["task_id"])
        except ContractError as exc:
            run["state"] = "RECOVERY_REQUIRED"
            run["state_history"].append({"state": "RECOVERY_REQUIRED", "at": _now(),
                                         "error_code": exc.code})
            generation, new_sha = _persist_audit(audit_path, audit)
            return _result_from_run(
                req, run, audit_path, generation, new_sha, status="recovery_required",
                action="none", errors=[_error(exc.code, exc.message, field=exc.field,
                                               expected=exc.expected, observed=exc.observed)],
                next_kind="manual_recovery")
        if pre_r1_digest != run["identity"]["r1_result_digest"] \
                or pre_inventory_digest != run["identity"]["inventory_digest_before"]:
            run["state"] = "RECOVERY_REQUIRED"
            run["state_history"].append({"state": "RECOVERY_REQUIRED", "at": _now(),
                                         "error_code": "INVENTORY_DRIFT"})
            generation, new_sha = _persist_audit(audit_path, audit)
            return _result_from_run(
                req, run, audit_path, generation, new_sha, status="recovery_required",
                action="none", errors=[_error(
                    "INVENTORY_DRIFT", "R1/inventory changed after prepare",
                    expected={"r1": run["identity"]["r1_result_digest"],
                              "inventory": run["identity"]["inventory_digest_before"]},
                    observed={"r1": pre_r1_digest, "inventory": pre_inventory_digest})],
                next_kind="manual_recovery")
        grant = None
        if run["plan"]["waivers"]:
            if req["confirmation_grant_path"] is None:
                raise ContractError("CONFIRMATION_REQUIRED", "preview-bound confirmation grant is required")
            if run["state"] == "PREVIEWED":
                grant, consumption_token = _read_confirmation_grant(
                    req["confirmation_grant_path"], run, req, root)
                gate_id = req["invocation_id"]
                next_generation = audit["generation"] + 1
                adoption = digest_value({"run_id": run["run_id"],
                                         "origin_session_id": run["identity"]["origin_session_id"],
                                         "origin_invocation_id": run["identity"]["origin_invocation_id"],
                                         "gate_invocation_id": gate_id,
                                         "confirmation_grant_digest": grant["confirmation_grant_digest"],
                                         "audit_generation": next_generation})
                run["gate_invocation_id"] = gate_id
                run["identity_adoption_digest"] = adoption
                run["gate_preclaim_digest"] = preclaim["evidence_digest"]
                run["state"] = "CONFIRMED"
                run["state_history"].append({"state": "CONFIRMED", "at": _now()})
                run["waivers"] = _planned_waivers(run["plan"], "authorized", grant)
                generation, audit_sha = _persist_audit(audit_path, audit)
                try:
                    _consume_confirmation_grant(req["confirmation_grant_path"], consumption_token)
                except ContractError as exc:
                    return _result_from_run(
                        req, run, audit_path, generation, audit_sha,
                        status="recovery_required", action="none",
                        errors=[_error(exc.code, exc.message, field=exc.field,
                                       expected=exc.expected, observed=exc.observed)],
                        next_kind="manual_recovery")
            else:
                gate_id = req["invocation_id"]
                if run.get("gate_invocation_id") != gate_id \
                        or run.get("gate_preclaim_digest") != preclaim["evidence_digest"] \
                        or not _is_digest(run.get("identity_adoption_digest")):
                    raise ContractError(
                        "CONFIRMATION_INVALID",
                        "confirmed adoption cannot be resumed by a different apply binding")
                stored_grant_digests = {
                    row.get("confirmation_grant_digest") for row in run.get("waivers", [])
                    if isinstance(row, Mapping)
                }
                if len(stored_grant_digests) != 1 or not _is_digest(next(iter(stored_grant_digests), None)) \
                        or any(row.get("status") != "authorized" for row in run.get("waivers", [])):
                    raise ContractError("AUDIT_MALFORMED", "confirmed waiver authority is incomplete")
                if os.path.lexists(req["confirmation_grant_path"]):
                    grant, consumption_token = _read_confirmation_grant(
                        req["confirmation_grant_path"], run, req, root)
                    if grant["confirmation_grant_digest"] not in stored_grant_digests:
                        raise ContractError("CONFIRMATION_INVALID", "resumed grant digest differs")
                    try:
                        _consume_confirmation_grant(req["confirmation_grant_path"], consumption_token)
                    except ContractError as exc:
                        return _result_from_run(
                            req, run, audit_path, audit["generation"], audit_sha or "",
                            status="recovery_required", action="none",
                            errors=[_error(exc.code, exc.message, field=exc.field,
                                           expected=exc.expected, observed=exc.observed)],
                            next_kind="manual_recovery")
        else:
            if req["invocation_id"] != run["identity"]["origin_invocation_id"] or req["confirmation_grant_path"] is not None:
                raise ContractError("CONFIRMATION_INVALID", "deterministic apply must retain origin identity and no grant")
            gate_id = req["invocation_id"]
            next_generation = audit["generation"] + 1
            adoption = digest_value({"run_id": run["run_id"],
                                     "origin_session_id": run["identity"]["origin_session_id"],
                                     "origin_invocation_id": run["identity"]["origin_invocation_id"],
                                     "gate_invocation_id": gate_id,
                                     "confirmation_grant_digest": None,
                                     "audit_generation": next_generation})
            run["gate_invocation_id"] = gate_id; run["identity_adoption_digest"] = adoption
            run["state"] = "CONFIRMED"; run["state_history"].append({"state": "CONFIRMED", "at": _now()})
            _generation, audit_sha = _persist_audit(audit_path, audit)
        try:
            allowed = _resolve_allowed_mutations(root, req["task_id"], run, preclaim, gate_id)
        except ContractError as exc:
            run["state"] = "RECOVERY_REQUIRED"
            run["state_history"].append({"state": "RECOVERY_REQUIRED", "at": _now(),
                                         "error_code": exc.code})
            generation, new_sha = _persist_audit(audit_path, audit)
            return _result_from_run(
                req, run, audit_path, generation, new_sha, status="recovery_required",
                action="none", errors=[_error(exc.code, exc.message, field=exc.field,
                                               expected=exc.expected, observed=exc.observed)],
                next_kind="manual_recovery")
        # Apply each exact action with write-ahead intent and post-state verification.
        mutation_rows = _planned_mutations(run["plan"])
        for index, action in enumerate(run["plan"]["actions"]):
            row = mutation_rows[index]
            row["status"] = "intent"; run["mutations"] = mutation_rows
            run["state"] = "ACTION_INTENT"; run["state_history"].append({"state": "ACTION_INTENT", "at": _now(), "action_id": action["action_id"]})
            _generation, audit_sha = _persist_audit(audit_path, audit)
            try:
                if action["kind"] in {"write_exact_bytes", "write_exact_completion"}:
                    data = base64.b64decode(action["expected_state"]["bytes_b64"], validate=True)
                    observed_after = _atomic_exact_write(root, root / action["path"], data,
                                                         action["before_sha256"])
                    provider_digest = digest_value({"action": action["action_id"], "observed_after": observed_after})
                elif action["kind"] == "r1_declaration_provider":
                    observed_after, provider_digest = _invoke_r1_provider(root, req["task_id"], action)
                    row["expected_after_sha256"] = observed_after
                elif action["kind"] == "authorize_single_pristine_retry":
                    if preclaim["variant"] != "commit" or not preclaim["repository_plan"] \
                            or run.get("gate_attempt_count", 0) != 0:
                        raise ContractError("INVENTORY_DRIFT", "F19 pristine retry precondition failed")
                    observed_after = None; provider_digest = digest_value({"authorization": "one_gate_attempt", "run_id": run["run_id"]})
                else:
                    raise ContractError("ACTION_FAILED", "unknown repair action")
            except ContractError as exc:
                run["state"] = "RECOVERY_REQUIRED"; run["state_history"].append({"state": "RECOVERY_REQUIRED", "at": _now(), "action_id": action["action_id"]})
                row["status"] = "refused"
                generation, audit_sha = _persist_audit(audit_path, audit)
                return _result_from_run(
                    req, run, audit_path, generation, audit_sha, status="recovery_required",
                    action="none", errors=[_error(exc.code, exc.message, field=exc.field,
                                                   expected=exc.expected, observed=exc.observed)],
                    next_kind="manual_recovery")
            if action["expected_after_sha256"] is not None and observed_after != action["expected_after_sha256"]:
                run["state"] = "RECOVERY_REQUIRED"; row["status"] = "refused"
                generation, audit_sha = _persist_audit(audit_path, audit)
                return _result_from_run(
                    req, run, audit_path, generation, audit_sha, status="recovery_required",
                    action="none", errors=[_error("ACTION_FAILED", "repair post-state mismatch")],
                    next_kind="manual_recovery")
            row["observed_after_sha256"] = observed_after; row["provider_result_digest"] = provider_digest; row["status"] = "applied"
            run["state"] = "ACTION_APPLIED"; run["state_history"].append({"state": "ACTION_APPLIED", "at": _now(), "action_id": action["action_id"]})
            _generation, audit_sha = _persist_audit(audit_path, audit)
        # Waiver authorization is already durable; its projection remains Lane-L close output.
        try:
            current_r1, _current_r1_digest, inventory_after, inventory_digest_after = _r1_snapshot(
                root, req["task_id"])
            post_decision, _post_rows = classify_r1(
                current_r1, run["identity"]["entrypoint"], root, req["task_id"])
            action_families = {item["catalog_id"] for item in run["plan"]["actions"]}
            waiver_families = {item["catalog_id"] for item in run["plan"]["waivers"]}
            post_roots = set(post_decision["root_decision_ids"]) - {"NO_BLOCKER"}
            if run["plan"]["actions"] and action_families == {"F19"}:
                post_valid = not post_decision["protected"] and post_roots <= {"F19"}
            elif run["plan"]["actions"]:
                post_valid = current_r1.get("status") == "pass" \
                    and post_decision["disposition"] == "no_blocker" and not post_roots
            elif run["plan"]["waivers"]:
                post_valid = not post_decision["protected"] and post_roots == waiver_families
            else:
                post_valid = current_r1.get("status") == "pass" \
                    and post_decision["disposition"] == "no_blocker" and not post_roots
            if not post_valid:
                raise ContractError(
                    "ACTION_FAILED", "post-action R1 authority does not prove the planned repair",
                    expected={"actions": sorted(action_families), "waivers": sorted(waiver_families)},
                    observed={"status": current_r1.get("status"), "decision": post_decision})
        except ContractError as exc:
            run["state"] = "RECOVERY_REQUIRED"
            run["state_history"].append({"state": "RECOVERY_REQUIRED", "at": _now(),
                                         "error_code": exc.code})
            generation, new_sha = _persist_audit(audit_path, audit)
            return _result_from_run(
                req, run, audit_path, generation, new_sha, status="recovery_required",
                action="none", errors=[_error(exc.code, exc.message, field=exc.field,
                                               expected=exc.expected, observed=exc.observed)],
                next_kind="manual_recovery")
        run["inventory_after"] = inventory_after; run["inventory_digest_after"] = inventory_digest_after
        run["gate_preclaim_digest"] = preclaim["evidence_digest"]
        pre_state, pre_digest = _capture_gate_state(allowed, inventory_digest_after)
        handoff_preimage = {"run_id": run["run_id"], "gate_invocation_id": gate_id,
                            "identity_adoption_digest": run["identity_adoption_digest"],
                            "audit_generation": audit["generation"], "audit_sha256": audit_sha,
                            "inventory_digest_after": inventory_digest_after,
                            "plan_digest": run["plan"]["plan_digest"], "gate_attempt_id": None,
                            "gate_kind": allowed["gate_kind"], "pre_gate_state_digest": pre_digest,
                            "allowed_mutations_digest": allowed["descriptor_digest"]}
        handoff_digest = digest_value(handoff_preimage)
        run["gate_handoff"] = {"required": True, "state": "ready", "gate_kind": allowed["gate_kind"],
                               "gate_attempt_id": None, "gate_invocation_id": gate_id,
                               "identity_adoption_digest": run["identity_adoption_digest"],
                               "handoff_digest": handoff_digest, "claim_token": None,
                               "gate_preclaim_digest": preclaim["evidence_digest"],
                               "allowed_mutations_digest": allowed["descriptor_digest"],
                               "allowed_mutations": allowed, "pre_gate_state_digest": pre_digest,
                               "receipt_digest": None, "outcome": None}
        run["pre_gate_state"] = pre_state
        run["apply_request_digest"] = req["request_digest"]
        run["state"] = "GATE_READY"; run["state_history"].append({"state": "GATE_READY", "at": _now()})
        generation, new_sha = _persist_audit(audit_path, audit)
        return _result_from_run(req, run, audit_path, generation, new_sha,
                                status="awaiting_gate", action="actions_applied", next_kind="call_claim_gate")


def _claim(req: Mapping[str, Any], root: Path) -> dict[str, Any]:
    with _task_lock(root, req["task_id"]) as audit_path:
        audit, sha = _read_audit(audit_path, root, req["task_id"], allow_absent=False)
        run = _find_run(audit, req["run_id"])
        if run["identity"]["canonical_project_root"] != str(root) \
                or run["identity"]["task_id"] != req["task_id"] \
                or run["identity"]["entrypoint"] != req["entrypoint"]:
            raise ContractError("ENTRYPOINT_MISMATCH", "claim identity differs from prepared run")
        handoff = run.get("gate_handoff", {})
        if run["state"] == "GATE_CLAIMED" and run.get("claim_request_digest") == req["request_digest"]:
            return _result_from_run(req, run, audit_path, audit["generation"], sha or "",
                                    status="awaiting_gate", action="gate_claimed",
                                    next_kind="run_close_gate_once" if req["entrypoint"] == "close" else "run_commit_gate_once")
        _check_audit_cas(audit, sha, req)
        if run["identity"]["origin_session_id"] != req["session_id"] or run.get("gate_invocation_id") != req["invocation_id"] \
                or handoff.get("handoff_digest") != req["handoff_digest"]:
            raise ContractError("GATE_CLAIM_INVALID", "gate claim identity/handoff mismatch")
        if run["state"] != "GATE_READY" or run.get("gate_attempt_count", 0) != 0:
            raise ContractError("GATE_ALREADY_CLAIMED", "gate is not claimable", observed=run["state"])
        _current_state, current_digest = _capture_gate_state(
            handoff["allowed_mutations"], run["inventory_digest_after"])
        if current_digest != handoff["pre_gate_state_digest"]:
            run["state"] = "RECOVERY_REQUIRED"
            run["state_history"].append({"state": "RECOVERY_REQUIRED", "at": _now(),
                                         "error_code": "GATE_STATE_DRIFT"})
            generation, new_sha = _persist_audit(audit_path, audit)
            return _result_from_run(
                req, run, audit_path, generation, new_sha, status="recovery_required",
                action="none", errors=[_error("GATE_STATE_DRIFT", "pre-gate state changed before claim",
                                               expected=handoff["pre_gate_state_digest"],
                                               observed=current_digest)],
                next_kind="manual_recovery")
        attempt = digest_value({"domain": "dev-fix-gate.v1", "run_id": run["run_id"],
                                "gate_invocation_id": run["gate_invocation_id"], "attempt": 1})
        next_generation = audit["generation"] + 1
        token = digest_value({"handoff_digest": handoff["handoff_digest"],
                              "gate_invocation_id": run["gate_invocation_id"],
                              "consumer_lane": "LANE-L", "generation": next_generation})
        run["gate_attempt_count"] = 1; run["claim_request_digest"] = req["request_digest"]
        run["state"] = "GATE_CLAIMED"; run["state_history"].append({"state": "GATE_CLAIMED", "at": _now()})
        handoff.update({"state": "claimed", "gate_attempt_id": attempt, "claim_token": token})
        generation, new_sha = _persist_audit(audit_path, audit)
        return _result_from_run(req, run, audit_path, generation, new_sha,
                                status="awaiting_gate", action="gate_claimed",
                                next_kind="run_close_gate_once" if req["entrypoint"] == "close" else "run_commit_gate_once")


def _validate_receipt_shape(value: Any) -> dict[str, Any]:
    required = {"schema_version", "run_id", "gate_attempt_id", "gate_invocation_id", "entrypoint",
                "gate_kind", "producer", "started_at", "finished_at", "ordinary_attempt_count",
                "handoff_digest", "pre_gate_state_digest", "post_gate_state_digest",
                "allowed_mutations_digest", "outcome", "authoritative_evidence",
                "envelope_observations", "gate_events", "gate_event_ledger_digest", "receipt_digest"}
    if not isinstance(value, dict) or set(value) != required:
        raise ContractError("GATE_RECEIPT_INVALID", "gate receipt field set is not exact")
    if value["schema_version"] != RECEIPT_SCHEMA or value["producer"] != "LANE-L" \
            or value["ordinary_attempt_count"] != 1 or value["entrypoint"] not in _ENTRYPOINTS \
            or value["gate_kind"] not in {"close_artifact_chain_and_verdict", "commit_preflight_and_transaction"} \
            or value["outcome"] not in {"pass", "reject", "no_action", "partial", "error"}:
        raise ContractError("GATE_RECEIPT_INVALID", "gate receipt identity/count invalid")
    for key in ("run_id", "gate_attempt_id", "handoff_digest", "pre_gate_state_digest",
                "post_gate_state_digest", "allowed_mutations_digest", "gate_event_ledger_digest", "receipt_digest"):
        if not _is_digest(value[key]): raise ContractError("GATE_RECEIPT_INVALID", "invalid receipt digest", field=key)
    if not _is_uuid(value["gate_invocation_id"]): raise ContractError("GATE_RECEIPT_INVALID", "invalid gate UUID")
    try:
        if _parse_time(value["finished_at"]) < _parse_time(value["started_at"]): raise ValueError
    except ValueError as exc: raise ContractError("GATE_RECEIPT_INVALID", "invalid receipt time range") from exc
    if value["gate_event_ledger_digest"] != digest_value(value["gate_events"]):
        raise ContractError("GATE_RECEIPT_INVALID", "gate event ledger digest mismatch")
    if value["receipt_digest"] != digest_value(value, "receipt_digest"):
        raise ContractError("GATE_RECEIPT_INVALID", "receipt digest mismatch")
    if not isinstance(value["gate_events"], list) or not isinstance(value["envelope_observations"], list):
        raise ContractError("GATE_RECEIPT_INVALID", "receipt event/observation arrays invalid")
    event_fields = {"sequence", "actor", "mutation_class", "target_id", "canonical_path_or_repo",
                    "before_state_digest", "after_state_digest", "operation_result_digest"}
    event_classes = {"create", "replace", "modify", "delete", "rename_to_lck", "consume",
                     "index_stage", "index_unstage", "git_object_write", "ref_update",
                     "reflog_update", "token_write"}
    for index, event in enumerate(value["gate_events"], 1):
        if not isinstance(event, dict) or set(event) != event_fields or event["sequence"] != index \
                or event["mutation_class"] not in event_classes \
                or not all(isinstance(event[key], str) and event[key]
                           for key in ("actor", "target_id", "canonical_path_or_repo")):
            raise ContractError("GATE_RECEIPT_INVALID", "gate event ledger is not contiguous/exact")
        for key in ("before_state_digest", "after_state_digest", "operation_result_digest"):
            if not _is_digest(event[key]): raise ContractError("GATE_RECEIPT_INVALID", "invalid event digest")
    obs_fields = {"entry_id", "canonical_path", "mutation_class", "before_state_digest",
                  "after_state_digest", "status", "transition_digest"}
    observation_classes = {"create", "modify", "delete", "git_transaction", "consume", "no_change"}
    for obs in value["envelope_observations"]:
        if not isinstance(obs, dict) or set(obs) != obs_fields \
                or obs["status"] not in {"observed", "absent_optional", "invalid"} \
                or obs["mutation_class"] not in observation_classes \
                or not isinstance(obs["entry_id"], str) or not isinstance(obs["canonical_path"], str) \
                or not all(_is_digest(obs[key]) for key in ("before_state_digest", "after_state_digest",
                                                            "transition_digest")):
            raise ContractError("GATE_RECEIPT_INVALID", "envelope observation is invalid")
    return value


def _close_projection(close_text: str, run: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    lines = [line[len("FIX-GATE: "):] for line in close_text.splitlines()
             if line.startswith("FIX-GATE: ")]
    if len(lines) != 1:
        raise ContractError("GATE_RECEIPT_INVALID", "close report requires one FIX-GATE projection")
    try:
        projection = strict_json_loads(lines[0])
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError("GATE_RECEIPT_INVALID", "FIX-GATE projection is not strict JSON") from exc
    fields = {"schema_version", "run_id", "gate_attempt_id", "gate_invocation_id",
              "handoff_digest", "allowed_mutations_digest", "artifact_chain_result_digest",
              "waiver_authorizations"}
    if not isinstance(projection, dict) or set(projection) != fields \
            or projection["schema_version"] != "dev_fix_close_projection.v1" \
            or not isinstance(projection["waiver_authorizations"], list):
        raise ContractError("GATE_RECEIPT_INVALID", "FIX-GATE projection fields are not exact")
    expected = {
        "run_id": run["run_id"],
        "gate_attempt_id": run["gate_handoff"]["gate_attempt_id"],
        "gate_invocation_id": run["gate_invocation_id"],
        "handoff_digest": run["gate_handoff"]["handoff_digest"],
        "allowed_mutations_digest": run["gate_handoff"]["allowed_mutations_digest"],
        "artifact_chain_result_digest": run["identity"]["r1_result_digest"],
        "waiver_authorizations": [
            {key: waiver[key] for key in ("catalog_id", "path", "reason_digest",
                                           "confirmation_grant_digest")}
            for waiver in run.get("waivers", [])
        ],
    }
    if any(projection.get(key) != value for key, value in expected.items()):
        raise ContractError("GATE_RECEIPT_INVALID", "FIX-GATE projection does not bind the run")
    return projection, digest_value(projection)


def _validate_receipt_against_run(receipt: Mapping[str, Any], run: Mapping[str, Any]) -> None:
    handoff = run["gate_handoff"]; allowed = handoff["allowed_mutations"]
    known_unchanged_error = receipt.get("outcome") == "error"
    bindings = {"run_id": run["run_id"], "gate_attempt_id": handoff["gate_attempt_id"],
                "gate_invocation_id": run["gate_invocation_id"], "entrypoint": run["identity"]["entrypoint"],
                "gate_kind": handoff["gate_kind"], "handoff_digest": handoff["handoff_digest"],
                "pre_gate_state_digest": handoff["pre_gate_state_digest"],
                "allowed_mutations_digest": handoff["allowed_mutations_digest"]}
    for key, expected in bindings.items():
        if receipt.get(key) != expected:
            raise ContractError("GATE_RECEIPT_INVALID", "receipt binding mismatch", field=key,
                                expected=expected, observed=receipt.get(key))
    pre_state = run.get("pre_gate_state")
    if not isinstance(pre_state, Mapping) or digest_value(pre_state) != handoff["pre_gate_state_digest"]:
        raise ContractError("GATE_STATE_DRIFT", "persisted pre-gate state is invalid")
    post_state, post_digest = _capture_gate_state(allowed, run["inventory_digest_after"])
    if receipt["post_gate_state_digest"] != post_digest:
        raise ContractError("GATE_STATE_DRIFT", "actual post-gate state differs from receipt")
    path_before = {x["entry_id"]: x for x in pre_state["path_states"]}
    path_after = {x["entry_id"]: x for x in post_state["path_states"]}
    slot_before = {x["slot_id"]: x for x in pre_state["dynamic_slot_states"]}
    slot_after = {x["slot_id"]: x for x in post_state["dynamic_slot_states"]}
    repo_before = {x["repo_root"]: x for x in pre_state["repository_states"]}
    repo_after = {x["repo_root"]: x for x in post_state["repository_states"]}
    targets: dict[str, dict[str, Any]] = {}
    for item in allowed["path_entries"]:
        before, after = path_before.get(item["entry_id"]), path_after.get(item["entry_id"])
        if not before or not after or before["state_digest"] != item["before_state_digest"]:
            raise ContractError("GATE_STATE_DRIFT", "path descriptor/pre-state mismatch")
        if item["required"] and after["file_type"] != "file" and not known_unchanged_error:
            raise ContractError("GATE_STATE_DRIFT", "required gate output is not a regular file",
                                field=item["canonical_path"], observed=after["file_type"])
        if after["file_type"] not in item["allowed_final_state"]["states"] and not known_unchanged_error:
            raise ContractError("GATE_STATE_DRIFT", "gate output final state is not allowed")
        targets[item["entry_id"]] = {
            "canonical": item["canonical_path"], "before": before["state_digest"],
            "after": after["state_digest"], "kind": "path",
            "required": item["required"] and not known_unchanged_error,
            "actors": {item["producer"]},
        }
    for item in allowed["dynamic_slots"]:
        before, after = slot_before.get(item["slot_id"]), slot_after.get(item["slot_id"])
        if not before or not after or before["membership_digest"] != item["before_membership_digest"] \
                or len(after["members"]) > item["max_created"] \
                or any(member["file_type"] not in {"file", "absent"} for member in after["members"]):
            raise ContractError("GATE_STATE_DRIFT", "dynamic slot state is outside its bound")
        targets[item["slot_id"]] = {
            "canonical": item["canonical_directory"], "before": before["membership_digest"],
            "after": after["membership_digest"], "kind": "slot", "required": False,
            "actors": {"LANE-L", "changelog-analyst", "commit-guard"},
        }
    for item in allowed["repository_transactions"]:
        before, after = repo_before.get(item["repo_root"]), repo_after.get(item["repo_root"])
        if not before or not after or before["head"] != item["before_head"] \
                or before["index_digest"] != item["before_index_digest"]:
            raise ContractError("GATE_STATE_DRIFT", "repository descriptor/pre-state mismatch")
        targets[item["repo_root"]] = {
            "canonical": item["repo_root"], "before": digest_value(before),
            "after": digest_value(after), "kind": "repository", "required": False,
            "actors": {"LANE-L", "changelog-analyst", "commit-guard"},
        }
    target_ids = set(targets)
    observed_ids = [x["entry_id"] for x in receipt["envelope_observations"]]
    if len(observed_ids) != len(set(observed_ids)) or set(observed_ids) != target_ids \
            or observed_ids != sorted(observed_ids):
        raise ContractError("GATE_STATE_DRIFT", "receipt does not cover exact mutation envelope",
                            expected=sorted(target_ids), observed=sorted(observed_ids))
    for event in receipt["gate_events"]:
        if event["target_id"] not in target_ids:
            raise ContractError("GATE_STATE_DRIFT", "event targets undeclared output")
        target = targets[event["target_id"]]
        if event["canonical_path_or_repo"] != target["canonical"] or event["actor"] not in target["actors"]:
            raise ContractError("GATE_STATE_DRIFT", "gate event identity/producer is outside the envelope")
        allowed_event_classes = {
            "path": {"create", "replace", "modify", "delete", "consume", "token_write"},
            "slot": {"create", "delete", "rename_to_lck", "consume"},
            "repository": {"index_stage", "index_unstage", "git_object_write", "ref_update", "reflog_update"},
        }[target["kind"]]
        if event["mutation_class"] not in allowed_event_classes:
            raise ContractError("GATE_STATE_DRIFT", "gate event mutation class is outside target semantics")
    for obs in receipt["envelope_observations"]:
        target = targets[obs["entry_id"]]
        events = [x for x in receipt["gate_events"] if x["target_id"] == obs["entry_id"]]
        if obs["canonical_path"] != target["canonical"] \
                or obs["before_state_digest"] != target["before"] \
                or obs["after_state_digest"] != target["after"] \
                or obs["status"] == "invalid" \
                or obs["transition_digest"] != digest_value(events):
            raise ContractError("GATE_RECEIPT_INVALID", "observation transition digest mismatch")
        if events:
            if events[0]["before_state_digest"] != target["before"] \
                    or events[-1]["after_state_digest"] != target["after"] \
                    or any(left["after_state_digest"] != right["before_state_digest"]
                           for left, right in zip(events, events[1:])):
                raise ContractError("GATE_STATE_DRIFT", "gate event chain is incomplete")
        elif target["before"] != target["after"] or target["required"]:
            raise ContractError("GATE_STATE_DRIFT", "changed/required target has no durable event")
    evidence = receipt["authoritative_evidence"]
    outcome = receipt["outcome"]
    if known_unchanged_error and (receipt["pre_gate_state_digest"] != receipt["post_gate_state_digest"]
                                  or receipt["gate_events"]):
        raise ContractError("GATE_RECEIPT_INVALID", "known gate error must prove unchanged state")
    if receipt["entrypoint"] == "close":
        if not isinstance(evidence, dict) or evidence.get("evidence_kind") not in {"close_report", "gate_error"}:
            raise ContractError("GATE_RECEIPT_INVALID", "invalid close evidence variant")
        if evidence["evidence_kind"] == "close_report":
            fields = {"evidence_kind", "close_report_path", "close_report_sha256", "verdict",
                      "fix_gate_projection_digest", "artifact_chain_result_digest"}
            expected_close = f"docs/dev/close-report-{run['identity']['task_id']}.md"
            if set(evidence) != fields or evidence["verdict"] not in {"YES", "NO"} \
                    or evidence["close_report_path"] != expected_close \
                    or not all(_is_digest(evidence[key]) for key in (
                        "close_report_sha256", "fix_gate_projection_digest",
                        "artifact_chain_result_digest")) \
                    or evidence["artifact_chain_result_digest"] != run["identity"]["r1_result_digest"]:
                raise ContractError("GATE_RECEIPT_INVALID", "close report evidence invalid")
            close_path = Path(run["identity"]["canonical_project_root"]) / expected_close
            try:
                close_bytes = close_path.read_bytes()
                close_text = close_bytes.decode("utf-8", errors="strict")
            except (OSError, UnicodeError) as exc:
                raise ContractError("GATE_RECEIPT_INVALID", "close report is unreadable") from exc
            nonempty = [line.strip() for line in close_text.splitlines() if line.strip()]
            expected_final = "CLOSE: " + evidence["verdict"]
            _projection, projection_digest = _close_projection(close_text, run)
            if "sha256:" + raw_sha(close_bytes) != evidence["close_report_sha256"] \
                    or not nonempty or nonempty[-1] != expected_final \
                    or projection_digest != evidence["fix_gate_projection_digest"]:
                raise ContractError("GATE_RECEIPT_INVALID", "close report bytes/verdict/projection mismatch")
            expected_outcome = "pass" if evidence["verdict"] == "YES" else "reject"
        else:
            fields = {"evidence_kind", "error_code", "diagnostics_digest", "report_absent"}
            if set(evidence) != fields or evidence["report_absent"] is not True \
                    or not isinstance(evidence["error_code"], str) or not evidence["error_code"] \
                    or not _is_digest(evidence["diagnostics_digest"]) \
                    or receipt["pre_gate_state_digest"] != receipt["post_gate_state_digest"]:
                raise ContractError("GATE_RECEIPT_INVALID", "close error evidence is not unchanged")
            expected_outcome = "error"
        if outcome != expected_outcome or outcome in {"no_action", "partial"}:
            raise ContractError("GATE_RECEIPT_INVALID", "close outcome mapping invalid")
    else:
        fields = {"evidence_kind", "commit_status", "failure_code", "repository_results"}
        if not isinstance(evidence, dict) or set(evidence) != fields or evidence["evidence_kind"] != "commit_status" \
                or not isinstance(evidence["repository_results"], list):
            raise ContractError("GATE_RECEIPT_INVALID", "commit evidence invalid")
        result_fields = {"repo_root", "before_head", "after_head", "status", "commit_sha",
                         "push_gate_token_sha256"}
        expected_repos = [item["repo_root"] for item in allowed["repository_transactions"]]
        observed_repos = [item.get("repo_root") for item in evidence["repository_results"]
                          if isinstance(item, Mapping)]
        if observed_repos != expected_repos or len(observed_repos) != len(evidence["repository_results"]):
            raise ContractError("GATE_RECEIPT_INVALID", "commit repository result set/order mismatch")
        descriptor_by_root = {item["repo_root"]: item for item in allowed["repository_transactions"]}
        post_by_root = {item["repo_root"]: item for item in post_state["repository_states"]}
        for row in evidence["repository_results"]:
            if set(row) != result_fields or row["status"] not in {"committed", "nothing_to_commit", "failed", "partial"}:
                raise ContractError("GATE_RECEIPT_INVALID", "repository result row is not strict")
            descriptor = descriptor_by_root[row["repo_root"]]
            post = post_by_root[row["repo_root"]]
            if row["before_head"] != descriptor["before_head"] or row["after_head"] != post["head"]:
                raise ContractError("GATE_STATE_DRIFT", "repository result topology binding mismatch")
            if row["status"] == "committed":
                if not isinstance(row["commit_sha"], str) or not re.fullmatch(r"[0-9a-f]{40}", row["commit_sha"]) \
                        or row["after_head"] != row["commit_sha"] or row["after_head"] == row["before_head"]:
                    raise ContractError("GATE_RECEIPT_INVALID", "committed repository topology is invalid")
                repo_root = Path(row["repo_root"])
                parents = _git_output(repo_root, "show", "-s", "--format=%P", row["commit_sha"]).split()
                expected_parents = [] if row["before_head"] is None else [row["before_head"]]
                if parents != expected_parents:
                    raise ContractError("GATE_STATE_DRIFT", "commit is not exactly one child of before_head")
                changed_raw = subprocess.run(
                    ["git", "-C", str(repo_root), "diff-tree", "--root", "--no-commit-id",
                     "--name-only", "-r", "-z", row["commit_sha"]],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False,
                    env={"PATH": os.environ.get("PATH", "")})
                if changed_raw.returncode != 0:
                    raise ContractError("GATE_STATE_DRIFT", "cannot inspect committed tree scope")
                changed_paths = sorted(x.decode("utf-8", errors="strict")
                                       for x in changed_raw.stdout.split(b"\0") if x)
                if changed_paths != descriptor["approved_paths"]:
                    raise ContractError("GATE_STATE_DRIFT", "commit tree is outside approved paths",
                                        expected=descriptor["approved_paths"], observed=changed_paths)
                worktree_match = subprocess.run(
                    ["git", "-C", str(repo_root), "diff", "--quiet", row["commit_sha"], "--",
                     *descriptor["approved_paths"]], stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=20, check=False,
                    env={"PATH": os.environ.get("PATH", "")})
                if worktree_match.returncode != 0 \
                        or post["approved_worktree_digest"] != descriptor["approved_tree_digest"]:
                    raise ContractError("GATE_STATE_DRIFT", "committed approved tree is not the admitted bytes")
                token_state = _typed_path_state(Path(descriptor["push_token_path"]))
                if token_state["state"] != "file" or row["push_gate_token_sha256"] != token_state["content_sha256"]:
                    raise ContractError("GATE_RECEIPT_INVALID", "committed repository push token is unbound")
                try:
                    token = strict_json_loads(Path(descriptor["push_token_path"]).read_bytes())
                except Exception as exc:
                    raise ContractError("GATE_RECEIPT_INVALID", "push token is malformed") from exc
                token_fields = {"commit_sha", "branch", "repo_root", "session_id"}
                expected_branch = descriptor["allowed_ref"].removeprefix("refs/heads/")
                if not isinstance(token, dict) or set(token) != token_fields \
                        or token["commit_sha"] != row["commit_sha"] \
                        or token["branch"] != expected_branch \
                        or token["repo_root"] != row["repo_root"] \
                        or token["session_id"] != run["identity"]["origin_session_id"]:
                    raise ContractError("GATE_RECEIPT_INVALID", "push token identity is unbound")
            elif row["status"] in {"nothing_to_commit", "failed"}:
                if row["after_head"] != row["before_head"] or row["commit_sha"] is not None \
                        or row["push_gate_token_sha256"] is not None:
                    raise ContractError("GATE_RECEIPT_INVALID", "unchanged repository result has a transaction")
            elif row["status"] == "partial":
                if row["after_head"] == row["before_head"]:
                    raise ContractError("GATE_RECEIPT_INVALID", "partial repository result has no durable delta")
        status = evidence["commit_status"]
        rows_status = [row["status"] for row in evidence["repository_results"]]
        if status == "committed":
            if not rows_status or not any(item == "committed" for item in rows_status) \
                    or any(item not in {"committed", "nothing_to_commit"} for item in rows_status) \
                    or evidence["failure_code"] is not None:
                raise ContractError("GATE_RECEIPT_INVALID", "committed status contradicts repository results")
            expected_outcome = "pass"
        elif status in {"nothing_to_commit", "nothing_to_commit_precommitted"}:
            if any(item != "nothing_to_commit" for item in rows_status) or evidence["failure_code"] is not None:
                raise ContractError("GATE_RECEIPT_INVALID", "no-action status contradicts repository results")
            expected_outcome = "no_action"
        elif status == "partially_committed":
            if not any(item in {"committed", "partial"} for item in rows_status):
                raise ContractError("GATE_RECEIPT_INVALID", "partial status has no durable transaction")
            expected_outcome = "partial"
        elif status == "failed":
            if not isinstance(evidence["failure_code"], str) or not evidence["failure_code"]:
                raise ContractError("GATE_RECEIPT_INVALID", "failed status lacks a stable failure code")
            changed = any(x.get("status") in {"committed", "partial"} for x in evidence["repository_results"])
            expected_outcome = "partial" if changed else "error"
        else: raise ContractError("GATE_RECEIPT_INVALID", "unknown commit status")
        if outcome != expected_outcome or outcome == "reject":
            raise ContractError("GATE_RECEIPT_INVALID", "commit outcome mapping invalid")


def _record(req: Mapping[str, Any], root: Path) -> dict[str, Any]:
    receipt = req["gate_receipt"]
    with _task_lock(root, req["task_id"]) as audit_path:
        audit, sha = _read_audit(audit_path, root, req["task_id"], allow_absent=False)
        run = _find_run(audit, req["run_id"])
        if run["identity"]["canonical_project_root"] != str(root) \
                or run["identity"]["task_id"] != req["task_id"] \
                or run["identity"]["entrypoint"] != req["entrypoint"]:
            raise ContractError("ENTRYPOINT_MISMATCH", "record identity differs from prepared run")
        if run["state"] == "FINAL" and run.get("gate_receipt_digest") == receipt["receipt_digest"] \
                and run.get("record_request_digest") == req["request_digest"]:
            return _result_from_run(req, run, audit_path, audit["generation"], sha or "",
                                    status="finalized", action="gate_recorded")
        if run["state"] == "FINAL":
            raise ContractError("GATE_RECEIPT_INVALID", "divergent receipt cannot replace FINAL")
        _check_audit_cas(audit, sha, req)
        if run["state"] != "GATE_CLAIMED" or run["identity"]["origin_session_id"] != req["session_id"] \
                or run.get("gate_invocation_id") != req["invocation_id"] \
                or run["gate_handoff"].get("claim_token") != req["gate_claim_token"]:
            raise ContractError("GATE_CLAIM_INVALID", "record identity/claim mismatch")
        try:
            _validate_receipt_against_run(receipt, run)
        except ContractError as exc:
            run["state"] = "RECOVERY_REQUIRED"
            run["state_history"].append({"state": "RECOVERY_REQUIRED", "at": _now(),
                                         "error_code": exc.code})
            generation, new_sha = _persist_audit(audit_path, audit)
            return _result_from_run(
                req, run, audit_path, generation, new_sha, status="recovery_required",
                action="none", errors=[_error(exc.code, exc.message, field=exc.field,
                                               expected=exc.expected, observed=exc.observed)],
                next_kind="manual_recovery")
        run["gate_receipt_digest"] = receipt["receipt_digest"]
        run["gate_receipt"] = dict(receipt)
        run["record_request_digest"] = req["request_digest"]
        run["gate_handoff"]["receipt_digest"] = receipt["receipt_digest"]
        run["gate_handoff"]["outcome"] = receipt["outcome"]
        run["gate_handoff"]["state"] = "recorded"
        if receipt["entrypoint"] == "close" \
                and receipt["authoritative_evidence"].get("evidence_kind") == "close_report":
            projection_digest = receipt["authoritative_evidence"]["fix_gate_projection_digest"]
            for waiver in run.get("waivers", []):
                waiver["projection_digest"] = projection_digest
                waiver["status"] = "projected"
        run["state"] = "GATE_RESULT"; run["state_history"].append({"state": "GATE_RESULT", "at": _now()})
        _persist_audit(audit_path, audit)
        run["state"] = "FINAL"; run["state_history"].append({"state": "FINAL", "at": _now()})
        generation, new_sha = _persist_audit(audit_path, audit)
        return _result_from_run(req, run, audit_path, generation, new_sha,
                                status="finalized", action="gate_recorded")


def _recover_close_receipt(run: Mapping[str, Any], observed_path: Any) -> dict[str, Any]:
    expected_relative = f"docs/dev/close-report-{run['identity']['task_id']}.md"
    if observed_path != expected_relative:
        raise ContractError("GATE_OUTCOME_UNKNOWN", "recovery did not bind the exact close report")
    allowed = run["gate_handoff"]["allowed_mutations"]
    post_state, post_digest = _capture_gate_state(allowed, run["inventory_digest_after"])
    before_by_id = {row["entry_id"]: row for row in run["pre_gate_state"]["path_states"]}
    after_by_id = {row["entry_id"]: row for row in post_state["path_states"]}
    descriptors = {row["entry_id"]: row for row in allowed["path_entries"]}
    if allowed["dynamic_slots"] or allowed["repository_transactions"]:
        raise ContractError("GATE_OUTCOME_UNKNOWN", "close recovery envelope has non-close targets")
    events: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    for entry_id in sorted(descriptors):
        descriptor = descriptors[entry_id]
        before, after = before_by_id.get(entry_id), after_by_id.get(entry_id)
        if not before or not after or after["file_type"] != "file" \
                or before["state_digest"] == after["state_digest"]:
            raise ContractError("GATE_OUTCOME_UNKNOWN",
                                "recovery cannot prove every required close output transition",
                                field=descriptor["canonical_path"])
        mutation_class = "create" if before["file_type"] == "absent" else "modify"
        event = {
            "sequence": len(events) + 1, "actor": descriptor["producer"],
            "mutation_class": mutation_class, "target_id": entry_id,
            "canonical_path_or_repo": descriptor["canonical_path"],
            "before_state_digest": before["state_digest"],
            "after_state_digest": after["state_digest"],
            "operation_result_digest": digest_value({"recovered": True, "entry_id": entry_id,
                                                       "after": after["state_digest"]}),
        }
        events.append(event)
        observations.append({
            "entry_id": entry_id, "canonical_path": descriptor["canonical_path"],
            "mutation_class": mutation_class, "before_state_digest": before["state_digest"],
            "after_state_digest": after["state_digest"], "status": "observed",
            "transition_digest": digest_value([event]),
        })
    close_path = Path(run["identity"]["canonical_project_root"]) / expected_relative
    close_bytes = close_path.read_bytes()
    close_text = close_bytes.decode("utf-8", errors="strict")
    nonempty = [line.strip() for line in close_text.splitlines() if line.strip()]
    if not nonempty or nonempty[-1] not in {"CLOSE: YES", "CLOSE: NO"}:
        raise ContractError("GATE_OUTCOME_UNKNOWN", "recovered close verdict is not canonical")
    verdict = nonempty[-1].split(":", 1)[1].strip()
    _projection, projection_digest = _close_projection(close_text, run)
    now = _now()
    receipt = {
        "schema_version": RECEIPT_SCHEMA, "run_id": run["run_id"],
        "gate_attempt_id": run["gate_handoff"]["gate_attempt_id"],
        "gate_invocation_id": run["gate_invocation_id"], "entrypoint": "close",
        "gate_kind": run["gate_handoff"]["gate_kind"], "producer": "LANE-L",
        "started_at": now, "finished_at": now, "ordinary_attempt_count": 1,
        "handoff_digest": run["gate_handoff"]["handoff_digest"],
        "pre_gate_state_digest": run["gate_handoff"]["pre_gate_state_digest"],
        "post_gate_state_digest": post_digest,
        "allowed_mutations_digest": run["gate_handoff"]["allowed_mutations_digest"],
        "outcome": "pass" if verdict == "YES" else "reject",
        "authoritative_evidence": {
            "evidence_kind": "close_report", "close_report_path": expected_relative,
            "close_report_sha256": "sha256:" + raw_sha(close_bytes), "verdict": verdict,
            "fix_gate_projection_digest": projection_digest,
            "artifact_chain_result_digest": run["identity"]["r1_result_digest"],
        },
        "envelope_observations": observations, "gate_events": events,
        "gate_event_ledger_digest": digest_value(events), "receipt_digest": None,
    }
    receipt["receipt_digest"] = digest_value(receipt, "receipt_digest")
    return receipt


def _recover_commit_receipt(run: Mapping[str, Any], observed_roots: Any) -> dict[str, Any]:
    """Reconstruct one conclusive commit receipt from ordinary durable evidence.

    The dispatch manifest cannot embed the receipt itself: doing so would create a
    digest fixed point because the manifest is part of the receipt post-state.  A
    recovery therefore validates the pre-existing ordinary manifest, QA transcript,
    exact one-child topology, approved tree, consumed grant lifecycle, and push token,
    then synthesizes a receipt whose event ledger is derived from those durable facts.
    """
    allowed = run["gate_handoff"]["allowed_mutations"]
    expected_roots = [row["repo_root"] for row in allowed["repository_transactions"]]
    if observed_roots != expected_roots:
        raise ContractError("GATE_OUTCOME_UNKNOWN", "recovery repository roots differ from the envelope")
    descriptors = {row["repo_root"]: row for row in allowed["repository_transactions"]}
    entries = {row["entry_id"]: row for row in allowed["path_entries"]}
    manifest = entries.get("dispatch-manifest")
    qa_entry = entries.get("commit-qa-report")
    active_entry = entries.get("active-grant-pointer")
    if manifest is None or qa_entry is None or active_entry is None:
        raise ContractError("GATE_OUTCOME_UNKNOWN", "commit recovery control envelope is incomplete")
    try:
        document = strict_json_loads(Path(manifest["canonical_path"]).read_bytes())
        qa_text = Path(qa_entry["canonical_path"]).read_text("utf-8", errors="strict")
    except Exception as exc:
        raise ContractError("GATE_OUTCOME_UNKNOWN", "commit recovery control output is unreadable") from exc
    manifest_fields = {"session_id", "task_id", "dispatched_at", "repository_plan",
                       "artifact_chain", "files_at_dispatch"}
    nonempty_qa = [line.strip() for line in qa_text.splitlines() if line.strip()]
    try:
        dispatched_at = _parse_time(document.get("dispatched_at")) if isinstance(document, Mapping) else None
    except ValueError as exc:
        raise ContractError("GATE_OUTCOME_UNKNOWN", "commit manifest timestamp is invalid") from exc
    if not isinstance(document, dict) or set(document) != manifest_fields \
            or document["session_id"] != run["identity"]["origin_session_id"] \
            or document["task_id"] != run["identity"]["task_id"] \
            or dispatched_at is None or dispatched_at > datetime.now(timezone.utc) \
            or document["repository_plan"] != allowed["repository_transactions"] \
            or not isinstance(document["artifact_chain"], Mapping) \
            or digest_value(document["artifact_chain"]) != run["identity"]["r1_result_digest"] \
            or not isinstance(document["files_at_dispatch"], dict) \
            or sorted(document["files_at_dispatch"]) != expected_roots \
            or not all(isinstance(value, str) for value in document["files_at_dispatch"].values()) \
            or not nonempty_qa or nonempty_qa[-1] != "COMMIT: APPROVE":
        raise ContractError("GATE_OUTCOME_UNKNOWN", "commit manifest/QA does not bind the claimed gate")
    post_state, post_digest = _capture_gate_state(allowed, run["inventory_digest_after"])
    pre_state = run["pre_gate_state"]
    before_paths = {row["entry_id"]: row for row in pre_state["path_states"]}
    after_paths = {row["entry_id"]: row for row in post_state["path_states"]}
    before_slots = {row["slot_id"]: row for row in pre_state["dynamic_slot_states"]}
    after_slots = {row["slot_id"]: row for row in post_state["dynamic_slot_states"]}
    before_repos = {row["repo_root"]: row for row in pre_state["repository_states"]}
    after_repos = {row["repo_root"]: row for row in post_state["repository_states"]}
    if after_paths["active-grant-pointer"]["file_type"] != "absent" \
            or any(row["members"] for row in after_slots.values()):
        raise ContractError("GATE_OUTCOME_UNKNOWN", "commit grant lifecycle is not durably consumed")
    repository_results = []
    any_commit = False
    for repo_root in expected_roots:
        descriptor = descriptors[repo_root]
        before, after = before_repos[repo_root], after_repos[repo_root]
        if before["head"] != descriptor["before_head"] or before["index_digest"] != descriptor["before_index_digest"]:
            raise ContractError("GATE_OUTCOME_UNKNOWN", "commit recovery pre-state is unbound")
        if after["head"] == descriptor["before_head"]:
            token_state = _typed_path_state(Path(descriptor["push_token_path"]))
            if token_state["state"] != "absent":
                raise ContractError("GATE_OUTCOME_UNKNOWN", "unchanged repository has an unexplained push token")
            repository_results.append({"repo_root": repo_root, "before_head": descriptor["before_head"],
                                       "after_head": after["head"], "status": "nothing_to_commit",
                                       "commit_sha": None, "push_gate_token_sha256": None})
            continue
        any_commit = True
        commit_sha = after["head"]
        if not isinstance(commit_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
            raise ContractError("GATE_OUTCOME_UNKNOWN", "commit recovery HEAD is invalid")
        parents = _git_output(Path(repo_root), "show", "-s", "--format=%P", commit_sha).split()
        expected_parents = [] if descriptor["before_head"] is None else [descriptor["before_head"]]
        changed = subprocess.run(
            ["git", "-C", repo_root, "diff-tree", "--root", "--no-commit-id", "--name-only",
             "-r", "-z", commit_sha], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=20, check=False, env={"PATH": os.environ.get("PATH", "")})
        changed_paths = sorted(x.decode("utf-8", errors="strict")
                               for x in changed.stdout.split(b"\0") if x)
        token_state = _typed_path_state(Path(descriptor["push_token_path"]))
        try:
            token = strict_json_loads(Path(descriptor["push_token_path"]).read_bytes())
        except Exception as exc:
            raise ContractError("GATE_OUTCOME_UNKNOWN", "commit recovery push token is unreadable") from exc
        expected_token = {"commit_sha": commit_sha,
                          "branch": descriptor["allowed_ref"].removeprefix("refs/heads/"),
                          "repo_root": repo_root,
                          "session_id": run["identity"]["origin_session_id"]}
        if parents != expected_parents or changed.returncode != 0 \
                or changed_paths != descriptor["approved_paths"] \
                or after["approved_worktree_digest"] != descriptor["approved_tree_digest"] \
                or token != expected_token or token_state["state"] != "file":
            raise ContractError("GATE_OUTCOME_UNKNOWN", "commit recovery topology/tree/token is not exact")
        repository_results.append({"repo_root": repo_root, "before_head": descriptor["before_head"],
                                   "after_head": commit_sha, "status": "committed",
                                   "commit_sha": commit_sha,
                                   "push_gate_token_sha256": token_state["content_sha256"]})

    targets: dict[str, tuple[str, str, str, str, str]] = {}
    for entry_id, descriptor in entries.items():
        targets[entry_id] = (descriptor["canonical_path"], before_paths[entry_id]["state_digest"],
                             after_paths[entry_id]["state_digest"], descriptor["producer"], "path")
    for slot_id, before in before_slots.items():
        slot = next(row for row in allowed["dynamic_slots"] if row["slot_id"] == slot_id)
        targets[slot_id] = (slot["canonical_directory"], before["membership_digest"],
                            after_slots[slot_id]["membership_digest"], "commit-guard", "slot")
    for repo_root in expected_roots:
        targets[repo_root] = (repo_root, digest_value(before_repos[repo_root]),
                              digest_value(after_repos[repo_root]), "changelog-analyst", "repository")
    events: list[dict[str, Any]] = []
    events_by_target: dict[str, list[dict[str, Any]]] = {}
    for target_id in sorted(targets):
        canonical, before, after, actor, kind = targets[target_id]
        target_events: list[dict[str, Any]] = []
        classes: list[str]
        if kind == "repository" and before != after:
            classes = ["git_object_write", "ref_update", "reflog_update"]
        elif kind == "path" and before != after:
            classes = ["token_write" if target_id.startswith("push-token-") else "create"]
        elif target_id == "active-grant-pointer":
            classes = ["create", "consume"]
        elif kind == "slot":
            classes = ["create", "rename_to_lck", "delete"]
        else:
            classes = []
        cursor = before
        for index, mutation_class in enumerate(classes):
            final = index == len(classes) - 1
            next_state = after if final else digest_value({"recovered": True, "target": target_id,
                                                           "step": index + 1})
            event = {"sequence": len(events) + 1, "actor": actor,
                     "mutation_class": mutation_class, "target_id": target_id,
                     "canonical_path_or_repo": canonical, "before_state_digest": cursor,
                     "after_state_digest": next_state,
                     "operation_result_digest": digest_value({"recovered": True,
                                                                "target": target_id,
                                                                "class": mutation_class})}
            events.append(event); target_events.append(event); cursor = next_state
        events_by_target[target_id] = target_events
    observations = [{"entry_id": target_id, "canonical_path": targets[target_id][0],
                     "mutation_class": "git_transaction" if targets[target_id][4] == "repository"
                     and targets[target_id][1] != targets[target_id][2]
                     else "no_change" if targets[target_id][1] == targets[target_id][2] else "create",
                     "before_state_digest": targets[target_id][1],
                     "after_state_digest": targets[target_id][2], "status": "observed",
                     "transition_digest": digest_value(events_by_target[target_id])}
                    for target_id in sorted(targets)]
    now = _now()
    receipt = {"schema_version": RECEIPT_SCHEMA, "run_id": run["run_id"],
               "gate_attempt_id": run["gate_handoff"]["gate_attempt_id"],
               "gate_invocation_id": run["gate_invocation_id"], "entrypoint": "commit",
               "gate_kind": run["gate_handoff"]["gate_kind"], "producer": "LANE-L",
               "started_at": now, "finished_at": now, "ordinary_attempt_count": 1,
               "handoff_digest": run["gate_handoff"]["handoff_digest"],
               "pre_gate_state_digest": run["gate_handoff"]["pre_gate_state_digest"],
               "post_gate_state_digest": post_digest,
               "allowed_mutations_digest": run["gate_handoff"]["allowed_mutations_digest"],
               "outcome": "pass" if any_commit else "no_action",
               "authoritative_evidence": {"evidence_kind": "commit_status",
                   "commit_status": "committed" if any_commit else "nothing_to_commit",
                   "failure_code": None, "repository_results": repository_results},
               "envelope_observations": observations, "gate_events": events,
               "gate_event_ledger_digest": digest_value(events), "receipt_digest": None}
    receipt["receipt_digest"] = digest_value(receipt, "receipt_digest")
    return receipt


def _finalize_recovered_receipt(req: Mapping[str, Any], audit_path: Path,
                                audit: dict[str, Any], run: dict[str, Any],
                                receipt: dict[str, Any]) -> dict[str, Any]:
    _validate_receipt_against_run(receipt, run)
    run["gate_receipt"] = receipt
    run["gate_receipt_digest"] = receipt["receipt_digest"]
    run["gate_handoff"]["receipt_digest"] = receipt["receipt_digest"]
    run["gate_handoff"]["outcome"] = receipt["outcome"]
    run["gate_handoff"]["state"] = "recovered"
    if receipt["entrypoint"] == "close" \
            and receipt["authoritative_evidence"].get("evidence_kind") == "close_report":
        projection_digest = receipt["authoritative_evidence"]["fix_gate_projection_digest"]
        for waiver in run.get("waivers", []):
            waiver["projection_digest"] = projection_digest
            waiver["status"] = "projected"
    run["state"] = "GATE_RESULT"
    run["state_history"].append({"state": "GATE_RESULT", "at": _now(), "recovered": True})
    _persist_audit(audit_path, audit)
    run["state"] = "FINAL"
    run["state_history"].append({"state": "FINAL", "at": _now(), "recovered": True})
    generation, new_sha = _persist_audit(audit_path, audit)
    return _result_from_run(req, run, audit_path, generation, new_sha,
                            status="finalized", action="run_recovered")


def _recover(req: Mapping[str, Any], root: Path) -> dict[str, Any]:
    with _task_lock(root, req["task_id"]) as audit_path:
        audit, sha = _read_audit(audit_path, root, req["task_id"], allow_absent=False)
        run = _find_run(audit, req["run_id"])
        if run["identity"]["canonical_project_root"] != str(root) \
                or run["identity"]["task_id"] != req["task_id"] \
                or run["identity"]["entrypoint"] != req["entrypoint"]:
            raise ContractError("ENTRYPOINT_MISMATCH", "recovery identity differs from prepared run")
        _check_audit_cas(audit, sha, req)
        if run["state"] == "FINAL":
            gate_required = run.get("gate_handoff", {}).get("required") is True
            return _result_from_run(req, run, audit_path, audit["generation"], sha or "",
                                    status="finalized" if gate_required else "no_action",
                                    action="run_recovered" if gate_required else "none")
        if run["state"] == "GATE_READY":
            _state, state_digest = _capture_gate_state(run["gate_handoff"]["allowed_mutations"],
                                                       run["inventory_digest_after"])
            if state_digest != run["gate_handoff"]["pre_gate_state_digest"]:
                run["state"] = "RECOVERY_REQUIRED"
                run["state_history"].append({"state": "RECOVERY_REQUIRED", "at": _now(),
                                             "error_code": "GATE_STATE_DRIFT"})
                generation, new_sha = _persist_audit(audit_path, audit)
                return _result_from_run(
                    req, run, audit_path, generation, new_sha, status="recovery_required",
                    action="none", errors=[_error("GATE_STATE_DRIFT", "unclaimed gate pre-state drifted")],
                    next_kind="manual_recovery")
            return _result_from_run(req, run, audit_path, audit["generation"], sha or "",
                                    status="awaiting_gate", action="actions_applied", next_kind="call_claim_gate")
        if run["state"] == "GATE_RESULT" and isinstance(run.get("gate_receipt"), dict):
            try:
                return _finalize_recovered_receipt(req, audit_path, audit, run, run["gate_receipt"])
            except ContractError:
                pass
        if run["state"] == "GATE_CLAIMED":
            try:
                receipt = (_recover_close_receipt(run, req.get("observed_close_report_path"))
                           if run["identity"]["entrypoint"] == "close"
                           else _recover_commit_receipt(run, req.get("observed_repository_roots")))
                return _finalize_recovered_receipt(req, audit_path, audit, run, receipt)
            except (ContractError, OSError, UnicodeError, ValueError):
                pass
        # A claimed gate is never re-issued. Recovery without a complete receipt is protected.
        run["recovery_identity"] = {"session_id": req["session_id"], "invocation_id": req["invocation_id"], "at": _now()}
        run["state"] = "RECOVERY_REQUIRED"; run["state_history"].append({"state": "RECOVERY_REQUIRED", "at": _now()})
        generation, new_sha = _persist_audit(audit_path, audit)
        return _result_from_run(req, run, audit_path, generation, new_sha,
                                status="recovery_required", action="none",
                                errors=[_error("RECOVERY_REQUIRED", "claimed or incomplete gate requires complete manual evidence")],
                                next_kind="manual_recovery")


def _inspect(req: Mapping[str, Any], root: Path) -> dict[str, Any]:
    with _task_lock(root, req["task_id"]) as audit_path:
        audit, sha = _read_audit(audit_path, root, req["task_id"], allow_absent=True)
        if not audit["runs"]:
            result = _base_result("inspect")
            result.update({"status": "no_action", "action": "none", "project_root": str(root),
                           "task_id": req["task_id"], "entrypoint": req["entrypoint"],
                           "invocation_id": req["invocation_id"], "origin_session_id": req["session_id"],
                           "request_digest": req["request_digest"], "audit_path": str(audit_path),
                           "audit_generation": audit["generation"], "audit_sha256": sha,
                           "decision": {"root_decision_ids": [], "secondary_evidence_codes": [],
                                        "disposition": "no_blocker", "protected": False},
                           "gate_handoff": _gate_handoff_empty(),
                           "next_action": {"kind": "none", "human_command": None}})
            return _finish_result(result)
        run = audit["runs"][-1]
        status, _action, next_kind, human = _projection_for_state(run)
        if status not in {"recovery_required", "error"}:
            status = "no_action"
        return _result_from_run(req, run, audit_path, audit["generation"], sha or "",
                                status=status, action="none", next_kind=next_kind,
                                human_command=human)


def execute_dev_fix(request: Mapping[str, Any]) -> dict[str, Any]:
    """Execute one strict provider operation and always return dev_fix_result.v1."""
    req: dict[str, Any] | None = None
    try:
        req = _validate_request(request)
        root = _canonical_root(req["project_root"])
        operation = req["operation"]
        if operation == "prepare": return _prepare(req, root)
        if operation == "apply": return _apply(req, root)
        if operation == "claim_gate": return _claim(req, root)
        if operation == "record_gate_result": return _record(req, root)
        if operation == "recover": return _recover(req, root)
        if operation == "inspect": return _inspect(req, root)
        raise ContractError("INVALID_OPERATION", "unreachable invalid operation")
    except ContractError as exc:
        return _failure_result(exc, req or request if isinstance(request, Mapping) else None)
    except Exception as exc:  # fail closed without leaking a traceback as machine authority
        return _failure_result(ContractError("INTERNAL_ERROR", f"internal provider failure: {type(exc).__name__}: {exc}"),
                               req or request if isinstance(request, Mapping) else None)


def _cli_failure(code: str, message: str) -> dict[str, Any]:
    return _failure_result(ContractError(code, message), None)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args != ["--request-stdin"]:
        result = _cli_failure("INVALID_REQUEST", "argv must be exactly --request-stdin")
    else:
        try:
            data = sys.stdin.buffer.read(MAX_STDIN_BYTES + 1)
            if len(data) > MAX_STDIN_BYTES:
                raise ContractError("INVALID_REQUEST", "stdin exceeds 1048576 bytes")
            value = strict_json_loads(data)
            if not isinstance(value, dict):
                raise ContractError("INVALID_REQUEST", "stdin must contain one JSON object")
            result = execute_dev_fix(value)
        except ContractError as exc:
            result = _failure_result(exc, None)
        except Exception as exc:
            result = _cli_failure("INVALID_REQUEST", f"invalid UTF-8/JSON input: {exc}")
    sys.stdout.buffer.write(canonical_bytes(result) + b"\n")
    sys.stdout.buffer.flush()
    status = result.get("status")
    return _EXIT_BY_STATUS.get(status if isinstance(status, str) else "", 1)


if __name__ == "__main__":
    raise SystemExit(main())
