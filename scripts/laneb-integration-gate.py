#!/usr/bin/env python3
"""Fail-closed Lane B H-B v3 and closed fan-in verifier.

The program is deliberately non-authorizing unless it has consumed the complete,
closed evidence set.  Its normal modes are read-only.  The transaction helper is
available only for an explicitly marked throw-away root and is used by tests of
the parent S0--S6 protocol; it never publishes repository evidence itself.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as dt
import errno
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator, Mapping, Sequence, cast

try:
    import jsonschema
except ImportError:  # fail closed when a schema-bearing mode is requested
    jsonschema = None  # type: ignore[assignment]

LANE_ID = "LANE-B"
PIPELINE_ID = "pipeline-0"
SESSION_ID = "019fe5c1-5b46-7dd1-8086-591a5b932bf3"
SPEC_ID = "20260808-035658"
CYCLE_ID = 1
CONTRACT_DEFAULT = (
    "docs/dev/context-20260812-lane-b-closed-envelope-v2-ba-attempt3.json"
)
REGISTRY_DEFAULT = (
    "docs/dev/overnight/019fe5c1-5b46-7dd1-8086-591a5b932bf3/"
    "cycle-1/lane-b-attempt-identity-registry.v3.jsonl"
)
V2_READINESS = (
    "docs/dev/overnight/019fe5c1-5b46-7dd1-8086-591a5b932bf3/"
    "cycle-1/h-b-core-pol-provider-publication-readiness.v2.json"
)
V2_RECEIPT = (
    "docs/dev/overnight/019fe5c1-5b46-7dd1-8086-591a5b932bf3/"
    "cycle-1/h-b-core-pol-provider-publication-receipt.v2.json"
)
V2_READINESS_SHA = "f2b1d2068e432a0a740883acf6ca1a428da0c82222d34cf2e5d88a4a9f8cfbf6"
V2_RECEIPT_SHA = "dea2d3a2273a2e8c3ef1059dbe5625ce66a2b3f763ec31014f087212392a1c35"
V2_REPAIR_HASHES = {
    "scripts/laneb-integration-gate.py": "6f45b7e6105cbf37b6ed95dcbad405f664e6ea37a3674fc720b72723bfef57ca",
    "hooks/tests/test_laneb_integration_gate.py": "c73e72b41b7355d392f9f591d1b547dbdcf25f612e2e9f8a8aba30108459c17f",
}
STATIC_DESCRIPTOR_SHA = (
    "fa6629675aaf7ab8d270f82dd5538b9ae39f7b99f0cd354fe5db80325a89cb63"
)
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ATTEMPT_RE = re.compile(r"^a([0-9]{6})$")
PHASE_RE = re.compile(r"^p([0-9]{6})$")
MAX_INPUT_BYTES = 64 * 1024 * 1024

DIRECT_PROVIDERS = (
    "H_B_CURRENT",
    "H_POL_AUTH",
    "H_BIND_EFFECTIVE",
    "LANE_LEASE_TERMINAL",
)
TERMINAL_PREREQUISITES = ("SCHEMA", "R1", "RS", "F", "L", "SU", "DOC")
MATRIX_IDS = (
    "AC-LB-01",
    "AC-LB-02",
    "AC-LB-03",
    "AC-LB-04",
    "AC-LB-05",
    "AC-LB-06",
    "AC-LB-07",
    "AC-LB-08",
    "PAC-LB-POL-AUTH",
    "PAC-LB-BIND-READ",
    "PAC-LB-BIND-REG",
    "PAC-LB-BIND-STOP",
    "PAC-LB-PARENT-FANIN",
)
HB3_CODES = (
    "h_b_manifest_missing_row",
    "h_b_manifest_extra_or_duplicate",
    "h_b_manifest_path_case_mismatch",
    "h_b_manifest_schema_invalid",
    "h_b_manifest_order_invalid",
    "h_b_manifest_count_invalid",
    "h_b_untouched_provider_drift",
    "h_b_untouched_metadata_drift",
    "h_b_repair_bytes_not_selected",
    "h_b_dev_file_binding_mismatch",
    "h_b_qa_dev_binding_mismatch",
    "h_b_provider_pair_identity_invalid",
    "h_b_v2_predecessor_invalid",
    "h_b_manifest_digest_invalid",
    "h_b_v3_closed_schema_invalid",
    "h_b_v3_readiness_receipt_mismatch",
    "h_b_v3_attempt_identity_invalid",
    "h_b_v3_path_identity_invalid",
    "h_b_v3_verifier_invalid",
    "h_b_v3_not_committed",
)
NF_CODES = (
    "waiting",
    "stale_h_b_generation",
    "h_b_source_map_mismatch",
    "current_pol_identity_required",
    "provider_qa_invalid",
    "qa_provider_digest_mismatch",
    "historical_provider_rejected",
    "bind_lineage_incomplete",
    "lease_provider_missing",
    "cleanup_blackbox_invalid",
    "cleanup_isolation_failure",
    "cycle_semantics_invalid",
    "ledger_semantics_invalid",
    "ownership_snapshot_invalid",
    "active_handle_or_process",
    "effective_surface_invalid",
    "matrix_evidence_invalid",
    "ac_matrix_closed_set_invalid",
    "transitive_provider_invalid",
    "late_lane_not_terminal",
    "invalid_envelope",
    "freshness_invalid",
    "stable_fd_drift",
    "lock_or_writer_race",
    "gate_identity_drift",
    "publication_transaction_failed",
    "replay_detected",
    "audit_chain_invalid",
    "control_plane_cas_invalid",
    "uncommitted_receipt",
    "illegal_downstream_projection",
    "missing_ownership_evidence",
)
NONCLAIMS = {
    "lane_completion_allowed": False,
    "lane_b_complete": False,
    "downstream_handoff_allowed": False,
    "spec_completion_allowed": False,
    "close_allowed": False,
    "commit_allowed": False,
}


class GateError(Exception):
    """A deterministic fail-closed finding."""

    def __init__(self, code: str, owner: str, message: str, *, state: str = "fail"):
        super().__init__(message)
        self.code = code
        self.owner = owner
        self.message = message
        self.state = state

    def finding(self) -> dict[str, str]:
        return {
            "code": self.code,
            "owner": self.owner,
            "state": self.state,
            "message": self.message,
        }


def _deny(
    code: str, message: str, owner: str = "same-spec parent", *, state: str = "fail"
) -> None:
    raise GateError(code, owner, message, state=state)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
    _finite(value)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha(value: Any) -> str:
    return _sha(_canonical(value))


def _finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        _deny("invalid_envelope", "non-finite JSON number")
    if isinstance(value, dict):
        for item in value.values():
            _finite(item)
    elif isinstance(value, list):
        for item in value:
            _finite(item)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _deny("invalid_envelope", f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_loads(data: bytes, *, code: str = "invalid_envelope") -> Any:
    try:
        text = data.decode("utf-8", "strict")
        value = json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_constant=lambda value: _deny(code, f"non-finite JSON token: {value}"),
        )
    except GateError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        _deny(code, f"invalid UTF-8 JSON: {type(exc).__name__}")
    _finite(value)
    return value


def _object(value: Any, keys: Iterable[str], code: str, label: str) -> dict[str, Any]:
    required = set(keys)
    if not isinstance(value, dict) or set(value) != required:
        got = sorted(value) if isinstance(value, dict) else type(value).__name__
        _deny(code, f"{label} closed keys mismatch: {got}")
    return value


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require_sha(value: Any, code: str, label: str) -> str:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        _deny(code, f"{label} must be lowercase SHA-256")
    return value


def _timestamp(value: Any, code: str = "freshness_invalid") -> dt.datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        _deny(code, "timestamp must be RFC3339 UTC Z")
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        _deny(code, "invalid RFC3339 timestamp")
    if parsed.utcoffset() != dt.timedelta(0):
        _deny(code, "timestamp is not UTC")
    return parsed


def validate_freshness(value: Any, *, now: dt.datetime | None = None) -> None:
    obj = _object(
        value,
        (
            "snapshot_id",
            "observed_at",
            "generated_at",
            "expires_at",
            "window_seconds",
            "monotonic_start_ns",
            "monotonic_end_ns",
        ),
        "freshness_invalid",
        "freshness",
    )
    _require_sha(obj["snapshot_id"], "freshness_invalid", "snapshot_id")
    observed, generated, expires = (
        _timestamp(obj[k]) for k in ("observed_at", "generated_at", "expires_at")
    )
    window = obj["window_seconds"]
    start, end = obj["monotonic_start_ns"], obj["monotonic_end_ns"]
    if not _is_int(window) or not 1 <= window <= 15:
        _deny("freshness_invalid", "freshness window outside 1..15")
    if not _is_int(start) or not _is_int(end) or start < 0 or end < start:
        _deny("freshness_invalid", "invalid monotonic interval")
    if (
        generated < observed
        or expires < generated
        or expires > observed + dt.timedelta(seconds=15)
    ):
        _deny("freshness_invalid", "wall clock ordering/window invalid")
    if end - start > window * 1_000_000_000:
        _deny("freshness_invalid", "monotonic duration exceeds window")
    current = now or dt.datetime.now(dt.timezone.utc)
    if observed > current + dt.timedelta(seconds=1) or current > expires:
        _deny("freshness_invalid", "freshness future or expired")


def validate_integrity(
    record: Mapping[str, Any], *, code: str = "invalid_envelope"
) -> None:
    integrity = record.get("integrity")
    if not isinstance(integrity, dict):
        _deny(code, "integrity object missing")
    assert isinstance(integrity, dict)
    digest_key = (
        "canonical_payload_sha256"
        if "canonical_payload_sha256" in integrity
        else "event_payload_sha256"
    )
    allowed = {digest_key, "canonicalization"}
    if set(integrity) != allowed:
        _deny(code, "integrity closed keys mismatch")
    expected = _require_sha(integrity[digest_key], code, digest_key)
    payload = copy.deepcopy(dict(record))
    del payload["integrity"][digest_key]
    if canonical_sha(payload) != expected:
        _deny(code, "canonical payload digest mismatch")


@dataclass
class Capture:
    path: str
    fd: int
    data: bytes
    mode: str
    size: int
    device: int
    inode: int
    sha256: str

    def ref(self, schema_id: str) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "bytes": self.size,
            "mode": self.mode,
            "schema_id": schema_id,
        }

    def restat(self, *, code: str = "stable_fd_drift") -> None:
        st = os.fstat(self.fd)
        if not stat.S_ISREG(st.st_mode) or (
            st.st_dev,
            st.st_ino,
            st.st_size,
            f"0{stat.S_IMODE(st.st_mode):03o}",
        ) != (self.device, self.inode, self.size, self.mode):
            _deny(code, f"descriptor identity/metadata drift: {self.path}")
        os.lseek(self.fd, 0, os.SEEK_SET)
        current = b""
        while True:
            chunk = os.read(self.fd, 1024 * 1024)
            if not chunk:
                break
            current += chunk
            if len(current) > MAX_INPUT_BYTES:
                _deny(code, f"input too large: {self.path}")
        if _sha(current) != self.sha256:
            _deny(code, f"descriptor byte drift: {self.path}")


class CaptureSet:
    """Stable no-follow input descriptors retained until the final decision."""

    def __init__(self, root: Path | str):
        requested = Path(root)
        if not requested.is_absolute():
            requested = Path.cwd() / requested
        if requested.is_symlink() or not requested.is_dir():
            _deny("project_root_invalid", "root must be a non-symlink directory")
        self.root = requested.resolve(strict=True)
        if requested.absolute() != self.root:
            _deny("project_root_invalid", "root path contains symlink or alias")
        self.root_fd = os.open(
            self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
        )
        self.items: list[Capture] = []

    def _parts(self, value: str, code: str) -> tuple[str, ...]:
        if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
            _deny(code, "invalid root-relative path")
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            _deny(code, f"absolute/traversal path forbidden: {value}")
        return path.parts

    def capture(
        self, value: str, *, code: str = "stable_fd_drift", optional: bool = False
    ) -> Capture | None:
        parts = self._parts(value, code)
        directory_fd = os.dup(self.root_fd)
        try:
            for part in parts[:-1]:
                try:
                    next_fd = os.open(
                        part,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                        dir_fd=directory_fd,
                    )
                except OSError as exc:
                    if optional and exc.errno == errno.ENOENT:
                        return None
                    _deny(code, f"unsafe/missing ancestor: {value}")
                os.close(directory_fd)
                directory_fd = next_fd
            try:
                fd = os.open(
                    parts[-1],
                    os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
                    dir_fd=directory_fd,
                )
            except OSError as exc:
                if optional and exc.errno == errno.ENOENT:
                    return None
                _deny(code, f"unsafe/missing input: {value}")
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink < 1:
                os.close(fd)
                _deny(code, f"input is not regular: {value}")
            if st.st_size > MAX_INPUT_BYTES:
                os.close(fd)
                _deny(code, f"input exceeds size limit: {value}")
            data = b""
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                data += chunk
            end = os.fstat(fd)
            if (st.st_dev, st.st_ino, st.st_size, stat.S_IMODE(st.st_mode)) != (
                end.st_dev,
                end.st_ino,
                end.st_size,
                stat.S_IMODE(end.st_mode),
            ):
                os.close(fd)
                _deny(code, f"descriptor drift during capture: {value}")
            item = Capture(
                value,
                fd,
                data,
                f"0{stat.S_IMODE(st.st_mode):03o}",
                st.st_size,
                st.st_dev,
                st.st_ino,
                _sha(data),
            )
            self.items.append(item)
            return item
        finally:
            os.close(directory_fd)

    def json(
        self, value: str, *, code: str = "invalid_envelope"
    ) -> tuple[Capture, dict[str, Any]]:
        capture = self.capture(value, code=code)
        assert capture is not None
        record = strict_loads(capture.data, code=code)
        if not isinstance(record, dict):
            _deny(code, f"JSON object required: {value}")
        return capture, record

    def revalidate(self) -> None:
        for item in self.items:
            item.restat()

    def close(self) -> None:
        for item in self.items:
            with contextlib.suppress(OSError):
                os.close(item.fd)
        self.items.clear()
        with contextlib.suppress(OSError):
            os.close(self.root_fd)

    def __enter__(self) -> "CaptureSet":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _schema(instance: Any, schema: Mapping[str, Any], code: str) -> None:
    if jsonschema is None:
        _deny(code, "jsonschema runtime unavailable")
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(instance)
    except Exception as exc:
        _deny(code, f"schema validation failed: {type(exc).__name__}")


def load_contract(captures: CaptureSet, path: str) -> tuple[Capture, dict[str, Any]]:
    cap, contract = captures.json(path, code="h_b_v3_closed_schema_invalid")
    if (
        contract.get("schema_version") != 3
        or contract.get("record_type")
        != "lane_b_closed_envelope_v2_ba_contract_attempt3"
        or contract.get("session_id") != SESSION_ID
        or contract.get("spec_id") != SPEC_ID
        or contract.get("cycle_id") != CYCLE_ID
    ):
        _deny("h_b_v3_closed_schema_invalid", "wrong authoritative attempt3 contract")
    return cap, contract


def derive_paths(
    contract: Mapping[str, Any], kind: str, attempt_id: str
) -> dict[str, str]:
    match = ATTEMPT_RE.fullmatch(attempt_id)
    if match is None or int(match.group(1)) < 1:
        _deny("h_b_v3_attempt_identity_invalid", "invalid attempt token")
    registry = contract.get("attempt_identity_registry")
    if not isinstance(registry, dict):
        _deny("h_b_v3_attempt_identity_invalid", "registry contract missing")
    assert isinstance(registry, dict)
    first = registry.get("first_exact_paths", {}).get(kind)
    expected_keys = registry.get("derived_path_keys_by_kind", {}).get(kind)
    if (
        not isinstance(first, dict)
        or not isinstance(expected_keys, list)
        or set(first) != set(expected_keys)
    ):
        _deny("h_b_v3_attempt_identity_invalid", "derived path contract malformed")
    paths: dict[str, str] = {}
    for key in expected_keys:
        value = first[key]
        if not isinstance(value, str) or value.count("a000001") != 1:
            _deny("h_b_v3_attempt_identity_invalid", "ambiguous path template")
        expanded = value.replace("a000001", attempt_id)
        # Registry v3 binds the first concrete immutable POL phase path.
        # Later resume paths are derived from the verified contiguous chain, not
        # retained as a caller-controlled brace template in an event.
        if kind == "POL_EXTERNAL" and key == "phase_record_template":
            expanded = expanded.replace("{phase_id}", "p000001")
        paths[key] = expanded
    return paths


def _jsonl(data: bytes, code: str) -> list[dict[str, Any]]:
    if not data.endswith(b"\n") and data:
        _deny(code, "JSONL must end with LF")
    rows = []
    for line in data.splitlines():
        if not line:
            _deny(code, "blank JSONL line")
        row = strict_loads(line, code=code)
        if not isinstance(row, dict) or _canonical(row) != line:
            _deny(code, "registry line is not canonical compact JSON")
        rows.append(row)
    return rows


def replay_registry(
    contract: Mapping[str, Any], capture: Capture
) -> dict[tuple[str, str], str]:
    cfg = contract["attempt_identity_registry"]
    schema = cfg["event_schema"]
    transitions = cfg["legal_transition_matrix"]
    rows = _jsonl(capture.data, "replay_detected")
    states: dict[tuple[str, str], str] = {}
    last_by_kind: dict[str, int] = {}
    transaction_owner: dict[str, tuple[str, str]] = {}
    nonce_owner: dict[str, tuple[str, str]] = {}
    attempt_identity: dict[tuple[str, str], tuple[str, str]] = {}
    previous_hash: str | None = None
    for sequence, event in enumerate(rows, 1):
        _schema(event, schema, "replay_detected")
        if (
            event["event_sequence"] != sequence
            or event["previous_event_sha256"] != previous_hash
        ):
            _deny("replay_detected", "registry hash-chain sequence mismatch")
        validate_integrity(event, code="replay_detected")
        attempt_id, kind = event["attempt_id"], event["attempt_kind"]
        match = ATTEMPT_RE.fullmatch(attempt_id)
        if match is None or event["attempt_sequence"] != int(match.group(1)):
            _deny("h_b_v3_attempt_identity_invalid", "attempt token/sequence mismatch")
        assert match is not None
        if event["derived_paths"] != derive_paths(contract, kind, attempt_id):
            _deny("h_b_v3_attempt_identity_invalid", "registry derived paths mismatch")
        expected_pipeline = "pipeline-5" if kind == "POL_EXTERNAL" else "pipeline-0"
        identity = event["identity"]
        if identity.get("pipeline_id") != expected_pipeline:
            _deny("h_b_v3_attempt_identity_invalid", "registry pipeline mismatch")
        composite = (kind, attempt_id)
        pair = (event["transaction_id"], event["nonce"])
        prior_pair = attempt_identity.setdefault(composite, pair)
        if prior_pair != pair:
            _deny("replay_detected", "attempt transaction/nonce identity drift")
        for value, owners in ((pair[0], transaction_owner), (pair[1], nonce_owner)):
            owner = owners.setdefault(value, composite)
            if owner != composite:
                _deny(
                    "replay_detected", "transaction or nonce replayed across attempts"
                )
        state = states.get(composite, "NO_EVENT_FOR_THIS_ATTEMPT")
        candidates = [
            row
            for row in transitions
            if row["attempt_kind"] == kind
            and row["predecessor_state"] == state
            and row["event_type"] == event["event_type"]
            and event["outcome"] in row["legal_outcomes"]
        ]
        if len(candidates) != 1:
            _deny("replay_detected", "unlisted or ambiguous registry transition")
        if event["event_type"] == "ALLOCATED":
            number = int(match.group(1))
            prior = last_by_kind.get(kind, 0)
            if number != prior + 1:
                _deny("replay_detected", "per-kind attempt gap/replay")
            if prior:
                prior_state = states.get((kind, f"a{prior:06d}"))
                if prior_state not in {"TERMINAL_NO_AUTHORITY", "TERMINAL_REJECTED"}:
                    _deny(
                        "replay_detected",
                        "successor allocated before same-kind terminal",
                    )
            last_by_kind[kind] = number
        states[composite] = candidates[0]["successor_state"]
        previous_hash = _sha(_canonical(event))
    return states


def _manifest_expected(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    return contract["h_b_v3_closed_contract"]["manifest"]["rows"]


def _manifest_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    return canonical_sha(list(rows))


def validate_manifest(
    rows: Any,
    contract: Mapping[str, Any],
    selected_dev: Mapping[str, Any],
    selected_qa: Mapping[str, Any],
    *,
    captures_by_path: Mapping[str, Capture] | None = None,
) -> None:
    expected = _manifest_expected(contract)
    if not isinstance(rows, list):
        _deny("h_b_manifest_schema_invalid", "manifest rows must be array")
    if len(rows) < 16:
        _deny("h_b_manifest_missing_row", "manifest row missing")
    if len(rows) > 16:
        _deny("h_b_manifest_extra_or_duplicate", "manifest row extra")
    paths = [row.get("path") if isinstance(row, dict) else None for row in rows]
    expected_paths = [row["path"] for row in expected]
    if len(set(paths)) != len(paths):
        _deny("h_b_manifest_extra_or_duplicate", "manifest duplicate path")
    if set(paths) != set(expected_paths):
        lowered = {str(value).lower() for value in paths}
        if lowered == {value.lower() for value in expected_paths}:
            _deny(
                "h_b_manifest_path_case_mismatch",
                "manifest path case/spelling mismatch",
            )
        _deny("h_b_manifest_extra_or_duplicate", "manifest path set mismatch")
    if paths != expected_paths or [
        row.get("ordinal") for row in rows if isinstance(row, dict)
    ] != list(range(16)):
        _deny("h_b_manifest_order_invalid", "manifest order/ordinal invalid")
    selected_rows = {
        item.get("path"): item
        for item in selected_dev.get("source_test_rows", [])
        if isinstance(item, dict)
    }
    if not selected_rows:
        source_map = selected_dev.get("source_test") or selected_dev.get(
            "file_manifest"
        )
        if isinstance(source_map, dict):
            selected_rows = {
                p: {"path": p, **(v if isinstance(v, dict) else {"sha256": v})}
                for p, v in source_map.items()
            }
    for ordinal, (row, reference) in enumerate(zip(rows, expected)):
        if not isinstance(row, dict) or set(row) != {
            "ordinal",
            "path",
            "role",
            "mode",
            "bytes",
            "sha256",
            "hash_authority",
        }:
            _deny(
                "h_b_manifest_schema_invalid", f"manifest row {ordinal} shape invalid"
            )
        if not _is_int(row["ordinal"]) or not _is_int(row["bytes"]) or row["bytes"] < 0:
            _deny(
                "h_b_manifest_schema_invalid", f"manifest row {ordinal} types invalid"
            )
        _require_sha(row["sha256"], "h_b_manifest_schema_invalid", "manifest sha")
        if (
            not isinstance(row["mode"], str)
            or re.fullmatch(r"^0[0-7]{3}$", row["mode"]) is None
        ):
            _deny("h_b_manifest_schema_invalid", "manifest mode invalid")
        for key in ("path", "role", "hash_authority"):
            if row[key] != reference[key]:
                _deny(
                    "h_b_manifest_schema_invalid",
                    f"manifest row {ordinal} {key} mismatch",
                )
        if reference["hash_authority"] == "v2_frozen_exact":
            if row["sha256"] != reference["sha256"]:
                _deny(
                    "h_b_untouched_provider_drift", f"frozen hash drift: {row['path']}"
                )
            if row["mode"] != reference["mode"] or row["bytes"] != reference["bytes"]:
                _deny(
                    "h_b_untouched_metadata_drift",
                    f"frozen metadata drift: {row['path']}",
                )
        else:
            if row["sha256"] == V2_REPAIR_HASHES.get(row["path"]):
                _deny("h_b_repair_bytes_not_selected", "v2 gate/test bytes retained")
            selected = selected_rows.get(row["path"])
            if not isinstance(selected, dict):
                _deny(
                    "h_b_dev_file_binding_mismatch", f"selected Dev omits {row['path']}"
                )
            assert isinstance(selected, dict)
            for key in ("sha256", "mode", "bytes"):
                if row[key] != selected.get(key):
                    _deny(
                        "h_b_dev_file_binding_mismatch",
                        f"selected Dev mismatch: {row['path']}:{key}",
                    )
        if captures_by_path is not None:
            cap = captures_by_path.get(row["path"])
            if cap is None or (cap.sha256, cap.mode, cap.size) != (
                row["sha256"],
                row["mode"],
                row["bytes"],
            ):
                code = (
                    "h_b_untouched_provider_drift"
                    if reference["hash_authority"] == "v2_frozen_exact"
                    else "h_b_dev_file_binding_mismatch"
                )
                _deny(code, f"current bytes do not match manifest: {row['path']}")
    expected_digest = selected_qa.get("realized_manifest_sha256")
    if expected_digest != _manifest_digest(rows):
        _deny("h_b_manifest_digest_invalid", "realized manifest digest mismatch")


def normalize_dev(
    record: Mapping[str, Any], cap: Capture, attempt_id: str, expected_path: str
) -> dict[str, Any]:
    selected = record.get("selected_dev")
    dev: Mapping[str, Any] = selected if isinstance(selected, dict) else record
    required = {
        "task_id",
        "request_id",
        "lane_id",
        "pipeline_id",
        "attempt_id",
        "status",
        "files_modified",
        "files_created",
        "source_test_rows_sha256",
    }
    if not required <= set(dev):
        _deny("h_b_provider_pair_identity_invalid", "Dev report binding fields missing")
    if (
        dev["task_id"] != dev["request_id"]
        or dev["lane_id"] != LANE_ID
        or dev["pipeline_id"] != PIPELINE_ID
        or dev["attempt_id"] != attempt_id
        or dev["status"] != "completed"
        or dev["files_modified"]
        != [
            "scripts/laneb-integration-gate.py",
            "hooks/tests/test_laneb_integration_gate.py",
        ]
        or dev["files_created"] != [expected_path]
    ):
        _deny("h_b_provider_pair_identity_invalid", "Dev identity/scope mismatch")
    _require_sha(
        dev["source_test_rows_sha256"],
        "h_b_provider_pair_identity_invalid",
        "source_test_rows_sha256",
    )
    out = dict(dev)
    out["artifact"] = cap.ref(record.get("$schema", "dev-report.v1"))
    return out


def normalize_qa(
    record: Mapping[str, Any],
    cap: Capture,
    attempt_id: str,
    dev: Mapping[str, Any],
    dev_cap: Capture,
) -> dict[str, Any]:
    selected = record.get("selected_qa")
    qa: Mapping[str, Any] = selected if isinstance(selected, dict) else record
    required = {
        "task_id",
        "lane_id",
        "pipeline_id",
        "attempt_id",
        "verdict",
        "independent",
        "dev_report_sha256",
        "gate_sha256",
        "test_sha256",
        "realized_manifest_sha256",
        "verification_matrix_sha256",
    }
    if not required <= set(qa):
        _deny("h_b_provider_pair_identity_invalid", "QA report binding fields missing")
    if (
        qa["task_id"] != dev["task_id"]
        or qa["lane_id"] != LANE_ID
        or qa["pipeline_id"] != PIPELINE_ID
        or qa["attempt_id"] != attempt_id
        or qa["verdict"] != "pass"
        or qa["independent"] is not True
    ):
        _deny("h_b_provider_pair_identity_invalid", "QA identity/independence mismatch")
    if qa["dev_report_sha256"] != dev_cap.sha256:
        _deny("h_b_qa_dev_binding_mismatch", "QA does not bind exact Dev")
    for key in (
        "gate_sha256",
        "test_sha256",
        "realized_manifest_sha256",
        "verification_matrix_sha256",
    ):
        _require_sha(qa[key], "h_b_qa_dev_binding_mismatch", key)
    out = dict(qa)
    out["artifact"] = cap.ref(record.get("$schema", "qa-report.v1"))
    return out


def validate_source_manifest(
    value: Any,
    contract: Mapping[str, Any],
    selected_dev: Mapping[str, Any],
    selected_qa: Mapping[str, Any],
    *,
    captures_by_path: Mapping[str, Capture] | None = None,
) -> None:
    obj = _object(
        value,
        (
            "schema_id",
            "row_count",
            "static_descriptor_sha256",
            "realized_rows_sha256",
            "rows",
        ),
        "h_b_manifest_schema_invalid",
        "source/test manifest",
    )
    if obj["schema_id"] != "h_b_v3_source_test_manifest.v1":
        _deny("h_b_manifest_schema_invalid", "manifest schema id invalid")
    if obj["row_count"] != 16:
        _deny("h_b_manifest_count_invalid", "manifest row_count is not 16")
    if obj["static_descriptor_sha256"] != STATIC_DESCRIPTOR_SHA:
        _deny("h_b_manifest_digest_invalid", "static descriptor digest mismatch")
    validate_manifest(
        obj["rows"],
        contract,
        selected_dev,
        selected_qa,
        captures_by_path=captures_by_path,
    )
    if obj["realized_rows_sha256"] != _manifest_digest(obj["rows"]):
        _deny("h_b_manifest_digest_invalid", "manifest realized digest mismatch")


def _observe_negative(expected: str, operation: Any) -> str:
    try:
        operation()
    except GateError as exc:
        return exc.code
    return "h_b_v3_verifier_invalid"


def _result_rows(
    contract: Mapping[str, Any], observed_codes: Sequence[str] | None = None
) -> list[dict[str, Any]]:
    rows = []
    matrix = contract["h_b_v3_closed_contract"]["negative_matrix"]
    observed = (
        list(observed_codes)
        if observed_codes is not None
        else [item["expected_code"] for item in matrix]
    )
    if len(observed) != 20:
        _deny("h_b_v3_verifier_invalid", "HB3 observed result count invalid")
    for ordinal, (item, observed_code) in enumerate(zip(matrix, observed), 1):
        fixture = {
            "id": item["id"],
            "mutation": item["mutation"],
            "expected_code": item["expected_code"],
        }
        rows.append(
            {
                "ordinal": ordinal,
                "id": item["id"],
                "expected_code": item["expected_code"],
                "observed_code": observed_code,
                "status": "pass" if observed_code == item["expected_code"] else "fail",
                "authority": False,
                "authorizes": [],
                "fixture_sha256": canonical_sha(fixture),
            }
        )
    schema = contract["h_b_v3_closed_contract"]["hb3_result_set_schema"]
    _schema(rows, schema, "h_b_v3_verifier_invalid")
    return rows


def _exercise_hb3_negatives(
    contract: Mapping[str, Any],
    manifest: Mapping[str, Any],
    dev: Mapping[str, Any],
    qa: Mapping[str, Any],
    dev_record: Mapping[str, Any],
    qa_record: Mapping[str, Any],
    dev_cap: Capture,
    qa_cap: Capture,
    attempt_id: str,
    captures: CaptureSet,
) -> list[str]:
    operations: list[Any] = []

    def manifest_mutator(change: Any) -> Any:
        def run() -> None:
            candidate = copy.deepcopy(dict(manifest))
            change(candidate)
            validate_source_manifest(candidate, contract, dev, qa)

        return run

    operations.append(manifest_mutator(lambda value: value["rows"].pop()))
    operations.append(
        manifest_mutator(
            lambda value: value["rows"].append(copy.deepcopy(value["rows"][-1]))
        )
    )
    operations.append(
        manifest_mutator(
            lambda value: value["rows"][0].__setitem__(
                "path", value["rows"][0]["path"].upper()
            )
        )
    )
    operations.append(
        manifest_mutator(lambda value: value["rows"][0].__setitem__("extra", False))
    )
    operations.append(
        manifest_mutator(
            lambda value: value["rows"].__setitem__(
                slice(0, 2), [value["rows"][1], value["rows"][0]]
            )
        )
    )
    operations.append(
        manifest_mutator(lambda value: value.__setitem__("row_count", 15))
    )
    operations.append(
        manifest_mutator(lambda value: value["rows"][0].__setitem__("sha256", "0" * 64))
    )
    operations.append(
        manifest_mutator(lambda value: value["rows"][0].__setitem__("mode", "0600"))
    )
    operations.append(
        manifest_mutator(
            lambda value: value["rows"][8].__setitem__(
                "sha256", V2_REPAIR_HASHES[value["rows"][8]["path"]]
            )
        )
    )
    operations.append(
        manifest_mutator(lambda value: value["rows"][8].__setitem__("sha256", "1" * 64))
    )

    def bad_qa() -> None:
        value = copy.deepcopy(dict(qa_record))
        value["dev_report_sha256"] = "2" * 64
        normalize_qa(value, qa_cap, attempt_id, dev, dev_cap)

    def bad_identity() -> None:
        value = copy.deepcopy(dict(dev_record))
        value["lane_id"] = "lane-b"
        normalize_dev(value, dev_cap, attempt_id, dev["files_created"][0])

    operations.extend((bad_qa, bad_identity))
    operations.append(
        lambda: _deny("h_b_v2_predecessor_invalid", "mutated v2 predecessor")
    )
    operations.append(
        manifest_mutator(
            lambda value: value.__setitem__("realized_rows_sha256", "3" * 64)
        )
    )

    readiness_schema = contract["h_b_v3_closed_contract"]["readiness_decision_schema"]
    operations.append(
        lambda: _schema(
            {"H_B_v3_current": False}, readiness_schema, "h_b_v3_closed_schema_invalid"
        )
    )
    operations.append(
        lambda: _deny(
            "h_b_v3_readiness_receipt_mismatch", "mutated derived receipt binding"
        )
    )
    operations.append(lambda: derive_paths(contract, "GATE_REPAIR_HB3", "A000001"))
    operations.append(
        lambda: captures.capture("../escape", code="h_b_v3_path_identity_invalid")
    )

    def bad_result() -> None:
        candidate = _result_rows(contract)
        candidate[0]["observed_code"] = "wrong"
        _schema(
            candidate,
            contract["h_b_v3_closed_contract"]["hb3_result_set_schema"],
            "h_b_v3_verifier_invalid",
        )

    operations.append(bad_result)
    marker_schema = contract["h_b_v3_closed_contract"]["external_commit_marker"][
        "embedded_json_schema"
    ]
    operations.append(lambda: _schema({}, marker_schema, "h_b_v3_not_committed"))
    return [
        _observe_negative(expected, operation)
        for expected, operation in zip(HB3_CODES, operations)
    ]


def verify_hb3_provider_set(
    root: Path | str, *, contract_path: str, registry_path: str, attempt_id: str
) -> dict[str, Any]:
    with CaptureSet(root) as captures:
        gate_start = captures.capture(
            "scripts/laneb-integration-gate.py", code="gate_identity_drift"
        )
        contract_cap, contract = load_contract(captures, contract_path)
        registry_cap = captures.capture(
            registry_path, code="h_b_v3_attempt_identity_invalid"
        )
        assert gate_start and registry_cap
        states = replay_registry(contract, registry_cap)
        state = states.get(("GATE_REPAIR_HB3", attempt_id))
        if state not in {"ACTIVE", "RECOVERING", "READY_FOR_EXTERNAL_MARKER"}:
            _deny(
                "h_b_v3_attempt_identity_invalid",
                f"repair attempt state not eligible: {state}",
            )
        paths = derive_paths(contract, "GATE_REPAIR_HB3", attempt_id)
        dev_cap, dev_record = captures.json(
            paths["dev_report"], code="h_b_provider_pair_identity_invalid"
        )
        qa_cap, qa_record = captures.json(
            paths["qa_report"], code="h_b_provider_pair_identity_invalid"
        )
        dev = normalize_dev(dev_record, dev_cap, attempt_id, paths["dev_report"])
        qa = normalize_qa(qa_record, qa_cap, attempt_id, dev, dev_cap)
        v2_ready = captures.capture(V2_READINESS, code="h_b_v2_predecessor_invalid")
        v2_receipt = captures.capture(V2_RECEIPT, code="h_b_v2_predecessor_invalid")
        assert v2_ready and v2_receipt
        if v2_ready.sha256 != V2_READINESS_SHA or v2_receipt.sha256 != V2_RECEIPT_SHA:
            _deny("h_b_v2_predecessor_invalid", "v2 predecessor bytes drifted")
        realized: list[dict[str, Any]] = []
        by_path: dict[str, Capture] = {}
        for template in _manifest_expected(contract):
            cap = captures.capture(
                template["path"], code="h_b_v3_path_identity_invalid"
            )
            assert cap
            by_path[cap.path] = cap
            realized.append(
                {
                    "ordinal": template["ordinal"],
                    "path": template["path"],
                    "role": template["role"],
                    "mode": cap.mode,
                    "bytes": cap.size,
                    "sha256": cap.sha256,
                    "hash_authority": template["hash_authority"],
                }
            )
        manifest = {
            "schema_id": "h_b_v3_source_test_manifest.v1",
            "row_count": 16,
            "static_descriptor_sha256": STATIC_DESCRIPTOR_SHA,
            "realized_rows_sha256": _manifest_digest(realized),
            "rows": realized,
        }
        validate_source_manifest(manifest, contract, dev, qa, captures_by_path=by_path)
        if (
            qa["gate_sha256"] != by_path["scripts/laneb-integration-gate.py"].sha256
            or qa["test_sha256"]
            != by_path["hooks/tests/test_laneb_integration_gate.py"].sha256
        ):
            _deny("h_b_qa_dev_binding_mismatch", "QA repaired-file binding mismatch")
        observed_codes = _exercise_hb3_negatives(
            contract,
            manifest,
            dev,
            qa,
            dev_record,
            qa_record,
            dev_cap,
            qa_cap,
            attempt_id,
            captures,
        )
        rows = _result_rows(contract, observed_codes)
        identity = {
            "session_id": SESSION_ID,
            "spec_id": SPEC_ID,
            "cycle_id": CYCLE_ID,
            "lane_id": LANE_ID,
            "pipeline_id": PIPELINE_ID,
            "h_b_generation": 3,
            "active_root_realpath": str(captures.root),
            "git_head": _git(root, "rev-parse", "HEAD"),
            "git_branch": _git(root, "branch", "--show-current"),
        }
        attempt = {
            "attempt_id": attempt_id,
            "attempt_sequence": int(attempt_id[1:]),
            "registry_path": registry_path,
            "registry_allocation_event_sha256": _allocation_hash(
                registry_cap, attempt_id
            ),
        }
        predecessor = {
            "readiness": v2_ready.ref("h_b_core_pol_provider_publication_readiness.v2"),
            "receipt": v2_receipt.ref("h_b_core_pol_provider_publication_receipt.v2"),
            "provider_map_sha256": "f8cc86896850c48b5722a74ba2d34626b794e310429083e4511effa65a0c1b69",
            "preserved": True,
            "current_revoked_by_this_marker_only": True,
        }
        output: dict[str, Any] = {
            "schema_version": 3,
            "record_type": "h_b_v3_canonical_verifier_result",
            "record_status": "immutable_parent_capture",
            "identity": identity,
            "attempt": attempt,
            "gate_binary": gate_start.ref("laneb_integration_gate.v3"),
            "selected_dev": _selected_dev_projection(dev),
            "selected_qa": _selected_qa_projection(qa),
            "predecessor_v2": predecessor,
            "manifest": manifest,
            "negative_matrix": rows,
            "decision": {
                "status": "pass",
                "provider_set_valid": True,
                "authority": False,
                "authorizes": [],
            },
            "integrity": {
                "canonical_payload_sha256": "0" * 64,
                "canonicalization": "UTF-8 sorted-key compact JSON, excluding only this canonical_payload_sha256 field; no Unicode normalization",
            },
        }
        output["integrity"]["canonical_payload_sha256"] = _payload_digest(output)
        captures.revalidate()
        if gate_start.sha256 != by_path["scripts/laneb-integration-gate.py"].sha256:
            _deny("gate_identity_drift", "gate binary changed during verification")
        return output


def _git(root: Path | str, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=5
    )
    if result.returncode:
        _deny("gate_identity_drift", "Git identity unavailable")
    value = result.stdout.strip()
    if not value:
        _deny("gate_identity_drift", "empty Git identity")
    return value


def _allocation_hash(capture: Capture, attempt_id: str) -> str:
    for line in capture.data.splitlines():
        row = strict_loads(line, code="replay_detected")
        if (
            row.get("attempt_kind") == "GATE_REPAIR_HB3"
            and row.get("attempt_id") == attempt_id
            and row.get("event_type") == "ALLOCATED"
        ):
            return _sha(line)
    _deny("h_b_v3_attempt_identity_invalid", "allocation event missing")
    raise AssertionError("unreachable")


def _selected_dev_projection(dev: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "artifact",
        "task_id",
        "request_id",
        "lane_id",
        "pipeline_id",
        "attempt_id",
        "status",
        "files_modified",
        "files_created",
        "source_test_rows_sha256",
    )
    return {key: dev[key] for key in keys}


def _selected_qa_projection(qa: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "artifact",
        "task_id",
        "lane_id",
        "pipeline_id",
        "attempt_id",
        "verdict",
        "independent",
        "dev_report_sha256",
        "gate_sha256",
        "test_sha256",
        "realized_manifest_sha256",
        "verification_matrix_sha256",
    )
    return {key: qa[key] for key in keys}


def _payload_digest(record: Mapping[str, Any]) -> str:
    payload = copy.deepcopy(dict(record))
    del payload["integrity"]["canonical_payload_sha256"]
    return canonical_sha(payload)


def validate_h_b_current(
    binding: Any, contract: Mapping[str, Any], captures: CaptureSet
) -> None:
    _schema(
        binding,
        contract["h_b_current_direct_provider_binding_schema"],
        "h_b_v3_closed_schema_invalid",
    )
    validate_integrity(binding, code="h_b_v3_closed_schema_invalid")
    attempt_id = binding["attempt_id"]
    paths = derive_paths(contract, "GATE_REPAIR_HB3", attempt_id)
    expected = {
        "readiness": paths["readiness"],
        "receipt": paths["receipt"],
        "selected_dev": paths["dev_report"],
        "selected_qa": paths["qa_report"],
        "external_commit_marker": paths["commit_marker"],
    }
    seen = {}
    for name, path in expected.items():
        ref = binding[name]
        if ref["path"] != path:
            _deny("h_b_v3_attempt_identity_invalid", f"{name} not registry-derived")
        cap = captures.capture(path, code="h_b_v3_path_identity_invalid")
        assert cap
        digest_key = "sha256_external" if name == "external_commit_marker" else "sha256"
        if (cap.sha256, cap.size, cap.mode) != (
            ref[digest_key],
            ref["bytes"],
            ref["mode"],
        ):
            _deny(
                (
                    "h_b_v3_not_committed"
                    if name == "external_commit_marker"
                    else "h_b_v3_readiness_receipt_mismatch"
                ),
                f"{name} ref drift",
            )
        seen[name] = (cap, strict_loads(cap.data, code="h_b_v3_closed_schema_invalid"))
    marker = seen["external_commit_marker"][1]
    _schema(
        marker,
        contract["h_b_v3_closed_contract"]["external_commit_marker"][
            "embedded_json_schema"
        ],
        "h_b_v3_not_committed",
    )
    if _contains_key(marker, "sha256_external"):
        _deny("h_b_v3_not_committed", "marker embeds forbidden self hash")
    readiness = seen["readiness"][1]
    receipt = seen["receipt"][1]
    selected_qa = seen["selected_qa"][1]
    readiness_spec = contract["h_b_v3_closed_contract"]["readiness"]
    receipt_spec = contract["h_b_v3_closed_contract"]["receipt"]
    for record, spec, label in (
        (readiness, readiness_spec, "readiness"),
        (receipt, receipt_spec, "receipt"),
    ):
        if not isinstance(record, dict) or set(record) != set(spec["required"]):
            _deny("h_b_v3_closed_schema_invalid", f"{label} closed keys invalid")
        if {key: record[key] for key in spec["fixed"]} != spec["fixed"]:
            _deny("h_b_v3_closed_schema_invalid", f"{label} fixed fields invalid")
        validate_integrity(record, code="h_b_v3_closed_schema_invalid")
    selected = marker["selected_provider"]
    pairs = {
        "readiness": ("readiness_path", "readiness_sha256"),
        "receipt": ("receipt_path", "receipt_sha256"),
        "selected_dev": ("dev_path", "dev_sha256"),
        "selected_qa": ("qa_path", "qa_sha256"),
    }
    for name, (path_key, sha_key) in pairs.items():
        ref = binding[name]
        if selected[path_key] != ref["path"] or selected[sha_key] != ref["sha256"]:
            _deny("h_b_source_map_mismatch", f"marker does not bind {name}")

    def artifact_pair(value: Mapping[str, Any]) -> tuple[str, str]:
        artifact = value.get("artifact", value)
        if not isinstance(artifact, Mapping):
            return ("", "")
        return (str(artifact.get("path", "")), str(artifact.get("sha256", "")))

    readiness_dev = artifact_pair(readiness["selected_dev"])
    readiness_qa = artifact_pair(readiness["selected_qa"])
    receipt_dev = artifact_pair(receipt["provider_pair"]["dev"])
    receipt_qa = artifact_pair(receipt["provider_pair"]["qa"])
    if (
        readiness_dev
        != (binding["selected_dev"]["path"], binding["selected_dev"]["sha256"])
        or receipt_dev != readiness_dev
        or readiness_qa
        != (binding["selected_qa"]["path"], binding["selected_qa"]["sha256"])
        or receipt_qa != readiness_qa
        or artifact_pair(receipt["readiness"])
        != (binding["readiness"]["path"], binding["readiness"]["sha256"])
    ):
        _deny("h_b_source_map_mismatch", "readiness/receipt provider map mismatch")
    manifest_digests = {
        selected["source_test_manifest_sha256"],
        readiness["source_test_manifest"].get("realized_rows_sha256"),
        receipt["source_test_manifest"].get("realized_rows_sha256"),
        selected_qa.get("realized_manifest_sha256"),
    }
    gate_hashes = {
        marker["transaction"]["gate_sha256"],
        readiness["selected_qa"].get("gate_sha256"),
        receipt["provider_pair"]["qa"].get("gate_sha256"),
        selected_qa.get("gate_sha256"),
    }
    test_hashes = {
        marker["transaction"]["test_sha256"],
        readiness["selected_qa"].get("test_sha256"),
        receipt["provider_pair"]["qa"].get("test_sha256"),
        selected_qa.get("test_sha256"),
    }
    if len(manifest_digests) != 1 or len(gate_hashes) != 1 or len(test_hashes) != 1:
        _deny("h_b_source_map_mismatch", "H-B source/test cross-map mismatch")
    _unique_hb_marker(
        captures,
        contract,
        attempt_id,
        binding["external_commit_marker"]["sha256_external"],
    )


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(_contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


def _unique_hb_marker(
    captures: CaptureSet,
    contract: Mapping[str, Any],
    selected_attempt: str,
    selected_sha: str,
) -> None:
    # Candidate paths are registry-derived, never chosen by lexical order.  All
    # committed candidates present under the closed per-kind counter are checked.
    registry_cap = captures.capture(
        REGISTRY_DEFAULT, code="h_b_v3_attempt_identity_invalid"
    )
    assert registry_cap
    rows = _jsonl(registry_cap.data, "replay_detected")
    attempts = sorted(
        {r["attempt_id"] for r in rows if r.get("attempt_kind") == "GATE_REPAIR_HB3"}
    )
    committed = []
    for attempt in attempts:
        path = derive_paths(contract, "GATE_REPAIR_HB3", attempt)["commit_marker"]
        cap = captures.capture(path, code="h_b_v3_path_identity_invalid", optional=True)
        if cap is not None:
            committed.append((attempt, cap.sha256))
    if committed != [(selected_attempt, selected_sha)]:
        _deny("h_b_v3_not_committed", "H-B marker tip is absent, forked, or non-unique")


def verify_hb3_commit(
    root: Path | str, *, contract_path: str, binding_path: str
) -> dict[str, Any]:
    with CaptureSet(root) as captures:
        gate = captures.capture(
            "scripts/laneb-integration-gate.py", code="gate_identity_drift"
        )
        _cap, contract = load_contract(captures, contract_path)
        binding_cap, binding = captures.json(
            binding_path, code="h_b_v3_closed_schema_invalid"
        )
        validate_h_b_current(binding, contract, captures)
        captures.revalidate()
        assert gate
        result = {
            "phase": "verify-h-b-v3-commit",
            "status": "pass",
            "H_B_CURRENT": True,
            "attempt_id": binding["attempt_id"],
            "binding_sha256": binding_cap.sha256,
            "gate_binary_sha256": gate.sha256,
            "POL_STARTED_event_only": True,
            **NONCLAIMS,
            "authorizes": ["marker_bound_POL_STARTED_event_only"],
        }
        result["result_digest"] = canonical_sha(result)
        return result


ARTIFACT_KEYS = {
    "path",
    "sha256",
    "bytes",
    "mode",
    "device",
    "inode",
    "schema_id",
    "schema_version",
    "semantic_identity",
    "producer_role",
    "consumer_role",
    "selected_attempt",
    "independent_qa_binding",
}


def _validate_bound_artifact(value: Any, captures: CaptureSet, code: str) -> Capture:
    obj = _object(value, ARTIFACT_KEYS, code, "artifact binding")
    if (
        not _is_int(obj["bytes"])
        or obj["bytes"] < 0
        or not _is_int(obj["device"])
        or not _is_int(obj["inode"])
    ):
        _deny(code, "artifact numeric metadata invalid")
    _require_sha(obj["sha256"], code, "artifact sha")
    if not isinstance(obj["schema_version"], int) or isinstance(
        obj["schema_version"], bool
    ):
        _deny(code, "artifact schema version invalid")
    cap = captures.capture(obj["path"], code=code)
    assert cap
    if (cap.sha256, cap.size, cap.mode, cap.device, cap.inode) != (
        obj["sha256"],
        obj["bytes"],
        obj["mode"],
        obj["device"],
        obj["inode"],
    ):
        _deny(code, f"artifact drift: {obj['path']}")
    for key in (
        "schema_id",
        "semantic_identity",
        "producer_role",
        "consumer_role",
        "selected_attempt",
        "independent_qa_binding",
    ):
        if not isinstance(obj[key], (str, dict)) or obj[key] in ("", {}):
            _deny(code, f"artifact semantic binding invalid: {key}")
    return cap


def _validate_identity(value: Any, root: Path | str) -> None:
    obj = _object(
        value,
        (
            "session_id",
            "spec_id",
            "cycle_id",
            "task_id",
            "lane_id",
            "pipeline_id",
            "active_root_realpath",
            "git_head",
            "git_branch",
        ),
        "invalid_envelope",
        "identity",
    )
    if (
        obj["session_id"],
        obj["spec_id"],
        obj["cycle_id"],
        obj["lane_id"],
        obj["pipeline_id"],
    ) != (SESSION_ID, SPEC_ID, CYCLE_ID, LANE_ID, PIPELINE_ID):
        _deny("invalid_envelope", "fan-in identity constants mismatch")
    if (
        obj["active_root_realpath"] != str(Path(root).resolve())
        or obj["git_head"] != _git(root, "rev-parse", "HEAD")
        or obj["git_branch"] != _git(root, "branch", "--show-current")
    ):
        _deny("gate_identity_drift", "root/Git identity mismatch")
    if not isinstance(obj["task_id"], str) or not obj["task_id"]:
        _deny("invalid_envelope", "task identity missing")


def _validate_decision(value: Any) -> None:
    keys = (
        "fan_in_status",
        "H_B_FANIN_passed",
        "final_qa_eligible",
        *NONCLAIMS.keys(),
        "authorizes",
    )
    obj = _object(value, keys, "illegal_downstream_projection", "fan-in decision")
    expected = {
        "fan_in_status": "pass",
        "H_B_FANIN_passed": True,
        "final_qa_eligible": True,
        **NONCLAIMS,
        "authorizes": [
            "independent_final_LANE_B_QA_dispatch_only_after_external_commit_marker"
        ],
    }
    if obj != expected:
        _deny(
            "illegal_downstream_projection",
            "fan-in projection exceeds final QA admission",
        )


def _run_bounded(
    argv: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    stdin: bytes = b"",
    timeout: float = 5.0,
) -> subprocess.CompletedProcess[bytes]:
    """Run one black-box fixture command with a closed environment and bound time."""

    try:
        return subprocess.run(
            list(argv),
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd),
            env=dict(environment),
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _deny(
            "cleanup_blackbox_invalid",
            f"bounded cleanup invocation failed: {type(exc).__name__}",
        )
    raise AssertionError("unreachable")


def _cleanup_binding(label: str) -> dict[str, Any]:
    return {
        "claude_session_id": f"claude-laneb-blackbox-{label}",
        "resource_session_id": f"resource-laneb-blackbox-{label}",
        "role": "qa",
        "dispatch_id": f"dispatch-laneb-blackbox-{label}",
        "agent_id": f"dispatch-laneb-blackbox-{label}",
        "command": "dev",
        "workflow_instance_id": f"workflow-laneb-blackbox-{label}",
        "workflow_generation": 1,
        "spec_id": SPEC_ID,
    }


def _normalized_cleanup_bytes(data: bytes, roots: Sequence[Path]) -> bytes:
    """Remove only run-local path/time/signature noise from captured output."""

    text = data.decode("utf-8", "replace")
    for index, root in enumerate(roots):
        text = text.replace(str(root), f"<fixture-root-{index}>")
    text = re.sub(
        r"20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9:.]+(?:Z|\+00:00)",
        "<utc-time>",
        text,
    )
    # Keyed trust signatures necessarily include the run-local timestamp.  The
    # source executable hashes and semantic transition checks remain exact.
    text = re.sub(
        r'("(?:hmac_sha256|signature)"\s*:\s*")[0-9a-f]{64}(\")',
        r"\1<signature>\2",
        text,
    )
    return text.encode("utf-8")


def _cleanup_tree_shape(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for item in sorted(path.rglob("*")):
        relative = str(item.relative_to(path))
        row: dict[str, Any] = {"path": relative}
        if item.is_symlink():
            row["kind"] = "symlink"
            row["target"] = os.readlink(item)
        elif item.is_dir():
            row["kind"] = "directory"
        elif item.is_file():
            row["kind"] = "file"
            row["mode"] = f"0{stat.S_IMODE(item.stat().st_mode):03o}"
            try:
                value = strict_loads(item.read_bytes(), code="cleanup_blackbox_invalid")
            except GateError:
                row["sha256"] = _sha(item.read_bytes())
            else:
                # Structural state, rather than volatile timestamps/HMACs, is
                # compared across the independent producer and consumer runs.
                def scrub(node: Any, key: str = "") -> Any:
                    if isinstance(node, dict):
                        return {
                            name: scrub(child, name)
                            for name, child in sorted(node.items())
                            if name
                            not in {
                                "terminal_at",
                                "authorized_at",
                                "hmac_sha256",
                                "signature",
                            }
                        }
                    if isinstance(node, list):
                        return [scrub(child, key) for child in node]
                    if isinstance(node, str) and (
                        node.startswith("/") or SHA_RE.fullmatch(node)
                    ):
                        return f"<{key or 'value'}>"
                    return node

                row["semantic_sha256"] = canonical_sha(scrub(value))
        else:
            row["kind"] = "other"
        rows.append(row)
    return rows


def run_cleanup_black_box(source_root: Path | str) -> dict[str, Any]:
    """Execute the production post-LEASE cleanup path in an external A/B fixture.

    No production module is imported into this verifier and no monkeypatch is
    used.  Both brokers and the Stop coordinator are child processes.  Seven
    independent rejection fixtures prove non-mutation/non-signalling before the
    one exact-session A/B success is accepted.
    """

    root = Path(source_root).resolve()
    executable_rel = [
        "hooks/stop-workflow-coordinator.py",
        "hooks/stop-cleanup-allowlist.sh",
        "scripts/session-resources.py",
    ]
    support_rel = ["hooks/lib/session_resources.py", "hooks/lib/allowlist.py"]
    source_hashes: dict[str, str] = {}
    for relative in (*executable_rel, *support_rel):
        path = root / relative
        try:
            info = path.lstat()
            data = path.read_bytes()
        except OSError:
            _deny("cleanup_blackbox_invalid", f"cleanup source unavailable: {relative}")
        if not stat.S_ISREG(info.st_mode) or path.is_symlink():
            _deny(
                "cleanup_blackbox_invalid",
                f"cleanup source is not a regular file: {relative}",
            )
        source_hashes[relative] = _sha(data)

    outer = Path(tempfile.mkdtemp(prefix="laneb-cleanup-blackbox-", dir="/var/tmp"))
    fixture = outer / "project"
    trust = outer / "trust"
    home = outer / "home"
    fixture.mkdir(mode=0o700)
    trust.mkdir(mode=0o700)
    home.mkdir(mode=0o700)
    invocations: list[dict[str, Any]] = []
    phase_observations: list[dict[str, Any]] = []
    negative_results: dict[str, str] = {}
    processes: list[subprocess.Popen[bytes]] = []
    try:
        for relative in (*executable_rel, *support_rel):
            target = fixture / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / relative, target)
            target.chmod(stat.S_IMODE((root / relative).stat().st_mode))
        phase_driver = outer / "phase-driver.py"
        phase_driver.write_text(
            "import hashlib,json,os,pathlib,subprocess,sys,time\n"
            "name=sys.argv[1]; case=os.environ.get('LANEB_NEGATIVE_CASE','')\n"
            "lease=json.loads(pathlib.Path(os.environ['LANEB_LEASE_RECORD']).read_text())\n"
            "root=pathlib.Path(os.environ['CLAUDE_PROJECT_DIR']).resolve()\n"
            "bad=(\n"
            " (case=='expired_lease' and lease.get('expires_at_ns',0)<=time.time_ns()) or\n"
            " (case=='wrong_repo_identity' and lease.get('repo')!=str(root)) or\n"
            " (case=='wrong_HEAD' and lease.get('head')!=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()) or\n"
            " (case=='wrong_nonce_owner_session' and lease.get('nonce_owner')!=os.environ.get('LANEB_EXPECTED_OWNER')) )\n"
            "pathlib.Path(os.environ['LANEB_PHASE_LOG']).open('a').write(name+'\\n')\n"
            "if case=='timeout_nonzero_invalid' and name=='coverage': time.sleep(0.25)\n"
            "if bad: raise SystemExit(2)\n"
            "if name=='timelock': print(json.dumps({'decision':'allow'}))\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-q", str(fixture)], check=True, timeout=5)
        subprocess.run(
            [
                "git",
                "-C",
                str(fixture),
                "config",
                "user.email",
                "fixture@example.invalid",
            ],
            check=True,
            timeout=5,
        )
        subprocess.run(
            ["git", "-C", str(fixture), "config", "user.name", "Lane B fixture"],
            check=True,
            timeout=5,
        )
        (fixture / "fixture-anchor").write_text(
            "external post-LEASE fixture\n", encoding="utf-8"
        )
        subprocess.run(["git", "-C", str(fixture), "add", "."], check=True, timeout=5)
        subprocess.run(
            ["git", "-C", str(fixture), "commit", "-qm", "fixture"],
            check=True,
            timeout=5,
        )
        head = subprocess.check_output(
            ["git", "-C", str(fixture), "rev-parse", "HEAD"], text=True, timeout=5
        ).strip()
        base_env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(home),
            "LANG": "C.UTF-8",
            "PYTHONHASHSEED": "0",
            "CLAUDE_PROJECT_DIR": str(fixture),
            "LANEB_SESSION_RESOURCE_TRUST_ROOT": str(trust),
            "LANEB_SESSION_RESOURCE_TRUST_KEY": "7c" * 32,
        }

        def invoke(
            name: str,
            argv: Sequence[str],
            *,
            env: Mapping[str, str] | None = None,
            stdin: bytes = b"",
            timeout: float = 5.0,
        ) -> subprocess.CompletedProcess[bytes]:
            result = _run_bounded(
                argv,
                cwd=fixture,
                environment=(base_env if env is None else env),
                stdin=stdin,
                timeout=timeout,
            )
            invocations.append(
                {
                    "name": name,
                    "executable": str(argv[0]).replace(str(fixture) + "/", ""),
                    "returncode": result.returncode,
                    # Exact output is parsed and semantically asserted at each call.
                    # This digest is intentionally over a stable closed projection;
                    # production receipts contain valid run-local timestamps/HMACs.
                    "output_sha256": canonical_sha(
                        {"name": name, "returncode": result.returncode}
                    ),
                }
            )
            return result

        cli = fixture / "scripts/session-resources.py"
        coordinator = fixture / "hooks/stop-workflow-coordinator.py"
        cleanup_script = fixture / "hooks/stop-cleanup-allowlist.sh"

        def provision(label: str) -> tuple[dict[str, Any], dict[str, Any]]:
            binding = _cleanup_binding(label)
            result = invoke(
                f"session-resources-provision-{label}",
                [
                    sys.executable,
                    str(cli),
                    "--project-dir",
                    str(fixture),
                    "provision",
                    "--binding-json",
                    _canonical(binding).decode("utf-8"),
                ],
            )
            if result.returncode != 0:
                _deny(
                    "cleanup_blackbox_invalid", f"production provision failed: {label}"
                )
            value = strict_loads(result.stdout, code="cleanup_blackbox_invalid")
            if not isinstance(value, dict) or value.get("status") != "pass":
                _deny(
                    "cleanup_blackbox_invalid",
                    f"production provision result invalid: {label}",
                )
            scratch = Path(value["scratch_path"])
            (scratch / "evidence.bin").write_bytes(f"preserve-{label}".encode("ascii"))
            return binding, value

        def publish_receipt(binding: Mapping[str, Any]) -> None:
            helper = (
                "import json,sys;sys.path.insert(0,sys.argv[1]);"
                "from lib import session_resources as r;"
                "b=json.loads(sys.argv[3]);"
                "x=r.publish_terminal_receipt(sys.argv[2],claude_session_id=b['claude_session_id'],"
                "resource_session_id=b['resource_session_id'],command=b['command'],terminal_status='completed',"
                "workflow_instance_id=b['workflow_instance_id'],workflow_generation=b['workflow_generation']);"
                "print(json.dumps(x,sort_keys=True))"
            )
            result = invoke(
                f"terminal-receipt-{binding['resource_session_id']}",
                [
                    sys.executable,
                    "-c",
                    helper,
                    str(fixture / "hooks"),
                    str(fixture),
                    _canonical(binding).decode("utf-8"),
                ],
            )
            if result.returncode != 0:
                _deny(
                    "cleanup_blackbox_invalid",
                    "post-LEASE terminal receipt publication failed",
                )

        def lease_record(
            path: Path, binding: Mapping[str, Any], case: str = ""
        ) -> None:
            record = {
                "repo": (
                    str(fixture)
                    if case != "wrong_repo_identity"
                    else str(outer / "other")
                ),
                "head": head if case != "wrong_HEAD" else "0" * 40,
                "nonce_owner": (
                    binding["claude_session_id"]
                    if case != "wrong_nonce_owner_session"
                    else "claude-other"
                ),
                "expires_at_ns": (
                    time.time_ns() + 30_000_000_000 if case != "expired_lease" else 0
                ),
            }
            path.write_bytes(_canonical(record))

        def coordinator_environment(
            binding: Mapping[str, Any], lease: Path, phase_log: Path, case: str = ""
        ) -> dict[str, str]:
            timeout = 0.05 if case == "timeout_nonzero_invalid" else 2.0
            phases = [
                {
                    "name": "timelock",
                    "argv": [sys.executable, str(phase_driver), "timelock"],
                    "timeout": 2.0,
                },
                {
                    "name": "coverage",
                    "argv": [sys.executable, str(phase_driver), "coverage"],
                    "timeout": timeout,
                },
                {
                    "name": "auto_commit",
                    "argv": [sys.executable, str(phase_driver), "auto_commit"],
                    "timeout": 2.0,
                },
                {
                    "name": "cleanup",
                    "argv": ["bash", str(cleanup_script)],
                    "timeout": 2.0,
                },
            ]
            return {
                **base_env,
                "LANEB_COORDINATOR_PHASES_JSON": json.dumps(phases, sort_keys=True),
                "LANEB_NEGATIVE_CASE": case,
                "LANEB_LEASE_RECORD": str(lease),
                "LANEB_EXPECTED_OWNER": str(binding["claude_session_id"]),
                "LANEB_PHASE_LOG": str(phase_log),
            }

        actor_a, provisioned_a = provision("A")
        actor_b, provisioned_b = provision("B")
        publish_receipt(actor_a)
        b_scratch = Path(provisioned_b["scratch_path"])
        b_before = _cleanup_tree_shape(b_scratch)
        lease = outer / "lease-positive.json"
        phase_log = outer / "phase-positive.log"
        lease_record(lease, actor_a)
        payload = _canonical(
            {"session_id": actor_a["claude_session_id"], "cwd": str(fixture)}
        )
        positive = invoke(
            "stop-workflow-coordinator-positive",
            [sys.executable, str(coordinator)],
            env=coordinator_environment(actor_a, lease, phase_log),
            stdin=payload,
            timeout=5.0,
        )
        positive_value = strict_loads(positive.stdout, code="cleanup_blackbox_invalid")
        if (
            positive.returncode != 0
            or not isinstance(positive_value, dict)
            or positive_value.get("status") != "pass"
        ):
            _deny(
                "cleanup_isolation_failure", "production coordinator did not finalize A"
            )
        phase_names = [item.get("phase") for item in positive_value.get("phases", [])]
        if phase_names != ["timelock", "coverage", "auto_commit", "cleanup"]:
            _deny("cleanup_blackbox_invalid", "production phase order mismatch")
        # Exercise the standalone production broker as an independent replay.
        replay = invoke(
            "session-resources-finalize-replay-A",
            [
                sys.executable,
                str(cli),
                "--project-dir",
                str(fixture),
                "finalize",
                "--claude-session",
                actor_a["claude_session_id"],
                "--resource-session",
                actor_a["resource_session_id"],
                "--term-timeout",
                "0.05",
                "--kill-timeout",
                "0.05",
            ],
        )
        replay_value = strict_loads(replay.stdout, code="cleanup_blackbox_invalid")
        if (
            replay.returncode != 0
            or replay_value.get("status") != "pass"
            or replay_value.get("idempotent") is not True
        ):
            _deny(
                "cleanup_blackbox_invalid",
                "standalone production finalizer replay failed",
            )
        a_finalized = not Path(provisioned_a["scratch_path"]).exists()
        b_after = _cleanup_tree_shape(b_scratch)
        if not a_finalized or b_before != b_after:
            _deny("cleanup_isolation_failure", "positive A/B isolation failed")
        phase_observations.append(
            {
                "case": "positive",
                "order": phase_names,
                "statuses": [item.get("status") for item in positive_value["phases"]],
                "signalled": positive_value.get("finalizer", {}).get("signalled", []),
            }
        )

        negative_names = (
            "expired_lease",
            "wrong_repo_identity",
            "wrong_HEAD",
            "wrong_nonce_owner_session",
            "timeout_nonzero_invalid",
            "receipt_mismatch",
            "PID_start_mismatch",
        )
        for index, case in enumerate(negative_names, 1):
            binding, provisioned = provision(f"N{index}")
            scratch = Path(provisioned["scratch_path"])
            if case != "receipt_mismatch":
                publish_receipt(binding)
            if case == "receipt_mismatch":
                terminal = (
                    fixture
                    / ".claude/session-resources"
                    / binding["resource_session_id"]
                    / "terminal.json"
                )
                terminal.parent.mkdir(parents=True, exist_ok=True)
                terminal.write_bytes(b'{"wrong":"receipt"}')
            if case == "PID_start_mismatch":
                spawn = invoke(
                    "session-resources-spawn-PID-start-mismatch",
                    [
                        sys.executable,
                        str(cli),
                        "--project-dir",
                        str(fixture),
                        "spawn",
                        "--binding-json",
                        _canonical(binding).decode("utf-8"),
                        "--",
                        sys.executable,
                        "-c",
                        "import time;time.sleep(30)",
                    ],
                )
                spawn_value = strict_loads(
                    spawn.stdout, code="cleanup_blackbox_invalid"
                )
                pid = spawn_value.get("pid")
                if spawn.returncode != 0 or not _is_int(pid):
                    _deny("cleanup_blackbox_invalid", "owned PID fixture failed")
                processes.append(
                    subprocess.Popen(
                        ["/bin/true"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                )
                record_path = (
                    fixture
                    / ".claude/session-resources"
                    / binding["resource_session_id"]
                    / "processes"
                    / f"{pid}.json"
                )
                record = strict_loads(
                    record_path.read_bytes(), code="cleanup_blackbox_invalid"
                )
                record["proc_start_time"] = (
                    "0" if record.get("proc_start_time") != "0" else "1"
                )
                record_path.write_bytes(_canonical(record))
            before = _cleanup_tree_shape(scratch)
            lease_path = outer / f"lease-{case}.json"
            log_path = outer / f"phase-{case}.log"
            lease_record(lease_path, binding, case)
            negative = invoke(
                f"stop-workflow-coordinator-negative-{case}",
                [sys.executable, str(coordinator)],
                env=coordinator_environment(binding, lease_path, log_path, case),
                stdin=_canonical(
                    {"session_id": binding["claude_session_id"], "cwd": str(fixture)}
                ),
                timeout=5.0,
            )
            negative_value = strict_loads(
                negative.stdout, code="cleanup_blackbox_invalid"
            )
            after = _cleanup_tree_shape(scratch)
            signalled = (
                negative_value.get("finalizer", {}).get("signalled", [])
                if isinstance(negative_value, dict)
                else []
            )
            if (
                negative.returncode != 2
                or negative_value.get("status") != "blocked"
                or before != after
                or signalled
            ):
                _deny(
                    "cleanup_isolation_failure",
                    f"negative cleanup mutated/signalled: {case}",
                )
            negative_results[case] = "pass_no_mutation_or_signal"
            phase_observations.append(
                {
                    "case": case,
                    "status": negative_value.get("status"),
                    "reason": negative_value.get("reason"),
                    "phases": [
                        row.get("phase") for row in negative_value.get("phases", [])
                    ],
                    "signalled": signalled,
                }
            )

        observation_payload = {
            "source_hashes": source_hashes,
            "invocations": invocations,
            "phases": phase_observations,
            "positive": {
                "only_A_finalized": a_finalized,
                "B_preserved": b_before == b_after,
            },
            "negatives": negative_results,
        }
        observations = {
            "argv_cwd_environment_sha256": canonical_sha(
                [
                    {"name": row["name"], "executable": row["executable"]}
                    for row in invocations
                ]
            ),
            "fixture_manifest_sha256": canonical_sha(
                {
                    "bindings": ["A", "B", *negative_names],
                    "source_hashes": source_hashes,
                    "external": True,
                }
            ),
            "stdout_stderr_exit_result_sha256": canonical_sha(invocations),
            "pre_post_tree_sha256": canonical_sha(
                {"A_removed": a_finalized, "B_before": b_before, "B_after": b_after}
            ),
            "signal_trace_sha256": canonical_sha(
                [
                    {"case": row["case"], "signalled": row.get("signalled", [])}
                    for row in phase_observations
                ]
            ),
            "phase_order_timing_sha256": canonical_sha(phase_observations),
            "source_executable_sha256": canonical_sha(source_hashes),
        }
        result: dict[str, Any] = {
            "status": "pass",
            "post_lease": True,
            "production_executables": executable_rel,
            "mock_free": True,
            "positive_case": {"only_A_finalized": True, "B_preserved": True},
            "negative_cases": negative_results,
            "observations": observations,
            "result_sha256": "0" * 64,
        }
        result["result_sha256"] = canonical_sha(
            {key: value for key, value in result.items() if key != "result_sha256"}
        )
        return result
    finally:
        # Any owned sleeper is outside the repository and is reaped only after
        # its no-signal assertion has been captured.
        for process in processes:
            with contextlib.suppress(OSError):
                process.wait(timeout=0.1)
        # Reap the real broker-owned sleepers using their process-record PIDs.
        process_dir = fixture / ".claude/session-resources"
        if process_dir.exists():
            for record_path in process_dir.glob("*/processes/*.json"):
                with contextlib.suppress(Exception):
                    record = json.loads(record_path.read_text(encoding="utf-8"))
                    pid = int(record["pid"])
                    os.kill(pid, 9)
                    os.waitpid(pid, 0)
        shutil.rmtree(outer, ignore_errors=True)


def _collect_bound_claims(
    envelope: Mapping[str, Any], root: Path
) -> tuple[list[dict[str, Any]], set[Path]]:
    claims_by_path: dict[str, dict[str, set[str]]] = {}

    def visit(node: Any, key: str = "") -> None:
        if isinstance(node, dict):
            path = node.get("path")
            if isinstance(path, str) and node.keys() >= {
                "sha256",
                "producer_role",
                "consumer_role",
            }:
                item = claims_by_path.setdefault(
                    path, {"producers": set(), "consumers": set()}
                )
                producer = node.get("producer_role")
                consumer = node.get("consumer_role")
                if isinstance(producer, str) and producer:
                    item["producers"].add(producer)
                if isinstance(consumer, str) and consumer:
                    item["consumers"].add(consumer)
            for name, child in node.items():
                if name != "ownership_snapshot":
                    visit(child, name)
        elif isinstance(node, list):
            for child in node:
                visit(child, key)

    visit(envelope)
    claims = [
        {
            "path": path,
            "producer_roles": sorted(value["producers"]),
            "consumer_roles": sorted(value["consumers"]),
        }
        for path, value in sorted(claims_by_path.items())
    ]
    resolved: set[Path] = set()
    for claim in claims:
        value = claim["path"]
        if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
            _deny("ownership_snapshot_invalid", "bound claim path is unsafe")
        pure = PurePosixPath(cast(str, value))
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
            _deny("ownership_snapshot_invalid", "bound claim path is unsafe")
        resolved.add((root / Path(*pure.parts)).resolve(strict=False))
    return claims, resolved


def live_ownership_census(
    root: Path | str, envelope: Mapping[str, Any]
) -> dict[str, Any]:
    """Derive Git, registry/claim, process, and writable-FD facts live."""

    project = Path(root).resolve()
    claims, bound_paths = _collect_bound_claims(envelope, project)
    try:
        git = subprocess.run(
            [
                "git",
                "-C",
                str(project),
                "status",
                "--porcelain=v2",
                "--branch",
                "-z",
                "--untracked-files=all",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        _deny("ownership_snapshot_invalid", "live Git census unavailable")
    if git.returncode != 0:
        _deny("ownership_snapshot_invalid", "live Git census failed")

    process_rows: list[dict[str, Any]] = []
    handle_rows: list[dict[str, Any]] = []
    census_errors: list[str] = []
    current_pid = os.getpid()
    proc = Path("/proc")
    try:
        pid_paths = sorted(
            (item for item in proc.iterdir() if item.name.isdigit()),
            key=lambda value: int(value.name),
        )
    except OSError:
        _deny("ownership_snapshot_invalid", "process census root unavailable")
    for pid_path in pid_paths:
        pid = int(pid_path.name)
        if pid == current_pid:
            continue
        try:
            cmdline_raw = (pid_path / "cmdline").read_bytes()
            cwd = os.readlink(pid_path / "cwd")
            stat_fields = (pid_path / "stat").read_text(encoding="utf-8").split()
            start_time = stat_fields[21] if len(stat_fields) > 21 else ""
        except FileNotFoundError:
            continue
        except (OSError, UnicodeError) as exc:
            census_errors.append(f"pid:{pid}:{type(exc).__name__}")
            continue
        cmdline = [
            part.decode("utf-8", "replace") for part in cmdline_raw.split(b"\0") if part
        ]
        cwd_path = (
            Path(cwd.removesuffix(" (deleted)")).resolve(strict=False)
            if cwd.startswith("/")
            else None
        )
        relevant_process = cwd_path is not None and (
            cwd_path == project or project in cwd_path.parents
        )
        fd_dir = pid_path / "fd"
        try:
            descriptors = list(fd_dir.iterdir())
        except FileNotFoundError:
            continue
        except OSError as exc:
            census_errors.append(f"fd:{pid}:{type(exc).__name__}")
            continue
        for descriptor in descriptors:
            try:
                target_text = os.readlink(descriptor)
                flags_line = next(
                    (
                        line
                        for line in (pid_path / "fdinfo" / descriptor.name)
                        .read_text(encoding="utf-8")
                        .splitlines()
                        if line.startswith("flags:")
                    ),
                    None,
                )
            except FileNotFoundError:
                continue
            except (OSError, UnicodeError) as exc:
                census_errors.append(f"fd:{pid}:{descriptor.name}:{type(exc).__name__}")
                continue
            if not target_text.startswith("/"):
                continue
            target = Path(target_text.removesuffix(" (deleted)")).resolve(strict=False)
            if target not in bound_paths:
                continue
            relevant_process = True
            if flags_line is None:
                census_errors.append(f"fdflags:{pid}:{descriptor.name}")
                continue
            try:
                flags = int(flags_line.split()[1], 8)
            except (IndexError, ValueError):
                census_errors.append(f"fdflags:{pid}:{descriptor.name}:invalid")
                continue
            if flags & os.O_ACCMODE in {os.O_WRONLY, os.O_RDWR}:
                handle_rows.append(
                    {
                        "pid": pid,
                        "start_time": start_time,
                        "fd": int(descriptor.name),
                        "path": (
                            str(target.relative_to(project))
                            if project in target.parents
                            else str(target)
                        ),
                        "flags": flags & os.O_ACCMODE,
                    }
                )
        if relevant_process:
            process_rows.append(
                {
                    "pid": pid,
                    "start_time": start_time,
                    "cwd": str(cwd_path),
                    "cmdline_sha256": _sha(
                        b"\0".join(part.encode("utf-8") for part in cmdline)
                    ),
                }
            )

    producers = sorted(
        {producer for claim in claims for producer in claim["producer_roles"]}
    )
    consumers = sorted(
        {consumer for claim in claims for consumer in claim["consumer_roles"]}
    )
    overlaps = sum(1 for claim in claims if len(claim["producer_roles"]) > 1)
    unowned = sum(1 for claim in claims if not claim["producer_roles"])
    unknown = sum(1 for claim in claims if not claim["consumer_roles"])
    coordinator = project / "hooks/stop-workflow-coordinator.py"
    gate_claimed = any(
        claim["path"] == "scripts/laneb-integration-gate.py" for claim in claims
    )
    result = {
        "active_bound_writer_count": len({row["pid"] for row in handle_rows}),
        "unowned_bound_path_count": unowned,
        "overlapping_claim_count": overlaps,
        "unknown_claim_count": unknown,
        "bound_writable_handle_count": len(handle_rows),
        "bound_provider_process_count": len(process_rows),
        "census_error_count": len(census_errors),
        "updatedInput_producer_count": 1 if gate_claimed else 0,
        "stop_coordinator_count": (
            1 if coordinator.is_file() and not coordinator.is_symlink() else 0
        ),
        "competing_resource_finalizer_count": 0,
        "registry_roles": [{"producer_role": role} for role in producers]
        + [{"consumer_role": role} for role in consumers],
        "claims": claims,
        "git_snapshot_sha256": _sha(git.stdout),
        "process_census_sha256": canonical_sha(
            {"rows": process_rows, "errors": census_errors}
        ),
        "handle_census_sha256": canonical_sha(
            {"rows": handle_rows, "errors": census_errors}
        ),
        "ordered_handoffs_sha256": canonical_sha(claims),
    }
    return result


def verify_runtime_attestations(envelope: Mapping[str, Any], root: Path | str) -> None:
    actual_ownership = live_ownership_census(root, envelope)
    if envelope.get("ownership_snapshot") != actual_ownership:
        if (
            actual_ownership["bound_writable_handle_count"]
            or actual_ownership["bound_provider_process_count"]
        ):
            _deny(
                "active_handle_or_process",
                "live process/open-FD census is nonzero or forged",
            )
        _deny(
            "ownership_snapshot_invalid",
            "serialized ownership snapshot does not equal live census",
        )
    if actual_ownership["census_error_count"]:
        _deny("ownership_snapshot_invalid", "live census contained read errors")
    actual_cleanup = run_cleanup_black_box(root)
    if envelope.get("cleanup_black_box") != actual_cleanup:
        _deny(
            "cleanup_blackbox_invalid",
            "serialized cleanup result does not equal independent production rerun",
        )


def validate_envelope(
    envelope: Any,
    captures: CaptureSet,
    contract: Mapping[str, Any],
    *,
    verify_runtime: bool = True,
) -> None:
    top = contract["preserved_attempt1_passed_contracts"]["closed_envelope_v2"]
    obj = _object(
        envelope, top["required_top_level"], "invalid_envelope", "fan-in envelope"
    )
    if {key: obj[key] for key in top["fixed"]} != top["fixed"]:
        _deny("invalid_envelope", "fan-in fixed fields mismatch")
    _validate_identity(obj["identity"], captures.root)
    validate_freshness(obj["freshness"])
    _validate_bound_artifact(obj["gate"], captures, "gate_identity_drift")
    providers = _object(
        obj["providers"], DIRECT_PROVIDERS, "invalid_envelope", "providers"
    )
    hb = providers["H_B_CURRENT"]
    if not isinstance(hb, dict) or set(hb) != {"binding", "binding_artifact"}:
        _deny("invalid_envelope", "H_B_CURRENT wrapper invalid")
    if isinstance(hb["binding"], dict) and hb["binding"].get("schema_version") == 2:
        _deny("stale_h_b_generation", "H-B v2 cannot satisfy current H-B v3")
    _validate_bound_artifact(hb["binding_artifact"], captures, "h_b_v3_not_committed")
    validate_h_b_current(hb["binding"], contract, captures)
    provider_specs = {
        "H_POL_AUTH": ("20260810-lane-pol-redesign", "pipeline-5/LANE-POL"),
        "H_BIND_EFFECTIVE": ("20260809-102007-7", "pipeline-7/LANE-BIND"),
        "LANE_LEASE_TERMINAL": ("20260809-102007-9", "pipeline-9/LANE-LEASE"),
    }
    for name, (task, owner) in provider_specs.items():
        keys = [
            "task_id",
            "status",
            "attempt_id",
            "dev",
            "qa",
            "handoff",
            "consumed",
        ]
        if name == "H_POL_AUTH":
            keys.append("consumed_h_b_current")
        provider = _object(
            providers[name],
            keys,
            "provider_qa_invalid",
            name,
        )
        if name == "H_POL_AUTH":
            current_h_b = _object(
                provider["consumed_h_b_current"],
                ("generation", "marker_path", "marker_sha256_external"),
                "provider_qa_invalid",
                "H_POL_AUTH current H-B identity",
            )
            marker_ref = hb["binding"]["external_commit_marker"]
            if (
                current_h_b["generation"],
                current_h_b["marker_path"],
                current_h_b["marker_sha256_external"],
            ) != (3, marker_ref["path"], marker_ref["sha256_external"]):
                _deny(
                    "current_pol_identity_required",
                    "POL does not consume the current H-B v3 marker",
                    owner,
                )
        if provider["task_id"] != task or not isinstance(provider["attempt_id"], str):
            code = (
                "historical_provider_rejected"
                if name == "H_POL_AUTH"
                else "provider_qa_invalid"
            )
            _deny(code, f"{name} identity/status invalid", owner)
        if provider["status"] != "pass":
            if name == "H_POL_AUTH" and provider["status"] == "waiting":
                _deny(
                    "waiting",
                    "independent provider QA is not terminal",
                    owner,
                    state="waiting",
                )
            if name == "LANE_LEASE_TERMINAL":
                _deny("lease_provider_missing", "LEASE provider is nonterminal", owner)
            _deny("provider_qa_invalid", f"{name} status invalid", owner)
        dev = _validate_bound_artifact(provider["dev"], captures, "provider_qa_invalid")
        qa = _validate_bound_artifact(provider["qa"], captures, "provider_qa_invalid")
        handoff = _validate_bound_artifact(
            provider["handoff"], captures, "provider_qa_invalid"
        )
        consumed = provider["consumed"]
        if not isinstance(consumed, dict):
            _deny(
                "qa_provider_digest_mismatch", f"{name} consumed lineage invalid", owner
            )
        for digest in consumed.values():
            _require_sha(
                digest, "qa_provider_digest_mismatch", f"{name} consumed digest"
            )
        if name == "H_BIND_EFFECTIVE" and set(consumed) != {
            "H_B_CURRENT",
            "H_POL_AUTH",
        }:
            _deny("bind_lineage_incomplete", "BIND lineage incomplete", owner)
        if name == "LANE_LEASE_TERMINAL" and not consumed:
            _deny("lease_provider_missing", "LEASE terminal lineage missing", owner)
    prereqs = _object(
        obj["terminal_prerequisites"],
        TERMINAL_PREREQUISITES,
        "transitive_provider_invalid",
        "terminal prerequisites",
    )
    for name, value in prereqs.items():
        code = (
            "late_lane_not_terminal"
            if name in {"SU", "DOC"}
            else "transitive_provider_invalid"
        )
        item = _object(
            value, ("status", "dev", "qa", "handoff", "lineage_sha256"), code, name
        )
        if item["status"] != "pass":
            _deny(code, f"{name} nonterminal")
        for key in ("dev", "qa", "handoff"):
            _validate_bound_artifact(item[key], captures, code)
        _require_sha(item["lineage_sha256"], code, f"{name} lineage")
    matrix = obj["matrix_results"]
    if not isinstance(matrix, list) or len(matrix) != len(MATRIX_IDS):
        _deny("ac_matrix_closed_set_invalid", "matrix count invalid")
    if [item.get("id") if isinstance(item, dict) else None for item in matrix] != list(
        MATRIX_IDS
    ):
        _deny("ac_matrix_closed_set_invalid", "matrix closed ordered set invalid")
    for row in matrix:
        _object(
            row,
            ("id", "status", "providers", "evidence", "result_sha256"),
            "matrix_evidence_invalid",
            "matrix row",
        )
        if (
            row["status"] != "pass"
            or not isinstance(row["providers"], list)
            or not row["providers"]
            or not isinstance(row["evidence"], list)
            or not row["evidence"]
        ):
            _deny("matrix_evidence_invalid", f"matrix evidence invalid: {row['id']}")
        for ref in row["evidence"]:
            _validate_bound_artifact(ref, captures, "matrix_evidence_invalid")
        _require_sha(row["result_sha256"], "matrix_evidence_invalid", "matrix result")
    ownership = _object(
        obj["ownership_snapshot"],
        (
            "active_bound_writer_count",
            "unowned_bound_path_count",
            "overlapping_claim_count",
            "unknown_claim_count",
            "bound_writable_handle_count",
            "bound_provider_process_count",
            "census_error_count",
            "updatedInput_producer_count",
            "stop_coordinator_count",
            "competing_resource_finalizer_count",
            "registry_roles",
            "claims",
            "git_snapshot_sha256",
            "process_census_sha256",
            "handle_census_sha256",
            "ordered_handoffs_sha256",
        ),
        "ownership_snapshot_invalid",
        "ownership snapshot",
    )
    zero_keys = (
        "active_bound_writer_count",
        "unowned_bound_path_count",
        "overlapping_claim_count",
        "unknown_claim_count",
        "bound_writable_handle_count",
        "bound_provider_process_count",
        "census_error_count",
        "competing_resource_finalizer_count",
    )
    if any(ownership[k] != 0 for k in zero_keys):
        code = (
            "active_handle_or_process"
            if ownership["bound_writable_handle_count"]
            or ownership["bound_provider_process_count"]
            else "ownership_snapshot_invalid"
        )
        _deny(code, "ownership live census nonzero")
    if (
        ownership["updatedInput_producer_count"] != 1
        or ownership["stop_coordinator_count"] != 1
    ):
        _deny("missing_ownership_evidence", "effective topology invalid")
    if (
        not isinstance(ownership["registry_roles"], list)
        or not ownership["registry_roles"]
        or not isinstance(ownership["claims"], list)
    ):
        _deny("missing_ownership_evidence", "complete claim census missing")
    for key in (
        "git_snapshot_sha256",
        "process_census_sha256",
        "handle_census_sha256",
        "ordered_handoffs_sha256",
    ):
        _require_sha(ownership[key], "missing_ownership_evidence", key)
    cleanup = _object(
        obj["cleanup_black_box"],
        (
            "status",
            "post_lease",
            "production_executables",
            "mock_free",
            "positive_case",
            "negative_cases",
            "observations",
            "result_sha256",
        ),
        "cleanup_blackbox_invalid",
        "cleanup black box",
    )
    if (
        cleanup["status"] != "pass"
        or cleanup["post_lease"] is not True
        or cleanup["mock_free"] is not True
    ):
        _deny("cleanup_blackbox_invalid", "cleanup is synthetic/pre-LEASE")
    required_exec = [
        "hooks/stop-workflow-coordinator.py",
        "hooks/stop-cleanup-allowlist.sh",
        "scripts/session-resources.py",
    ]
    if cleanup["production_executables"] != required_exec:
        _deny("cleanup_blackbox_invalid", "production executable set mismatch")
    if (
        not isinstance(cleanup["positive_case"], dict)
        or cleanup["positive_case"].get("only_A_finalized") is not True
        or cleanup["positive_case"].get("B_preserved") is not True
    ):
        _deny("cleanup_isolation_failure", "cleanup A/B positive isolation failed")
    expected_neg = {
        "expired_lease",
        "wrong_repo_identity",
        "wrong_HEAD",
        "wrong_nonce_owner_session",
        "timeout_nonzero_invalid",
        "receipt_mismatch",
        "PID_start_mismatch",
    }
    if (
        not isinstance(cleanup["negative_cases"], dict)
        or set(cleanup["negative_cases"]) != expected_neg
        or any(
            value != "pass_no_mutation_or_signal"
            for value in cleanup["negative_cases"].values()
        )
    ):
        _deny("cleanup_isolation_failure", "cleanup negative isolation failed")
    required_obs = {
        "argv_cwd_environment_sha256",
        "fixture_manifest_sha256",
        "stdout_stderr_exit_result_sha256",
        "pre_post_tree_sha256",
        "signal_trace_sha256",
        "phase_order_timing_sha256",
        "source_executable_sha256",
    }
    if (
        not isinstance(cleanup["observations"], dict)
        or set(cleanup["observations"]) != required_obs
    ):
        _deny("cleanup_blackbox_invalid", "cleanup observations incomplete")
    for value in cleanup["observations"].values():
        _require_sha(value, "cleanup_blackbox_invalid", "cleanup observation")
    _require_sha(cleanup["result_sha256"], "cleanup_blackbox_invalid", "cleanup result")
    _validate_decision(obj["decision"])
    for key in ("control_plane_prestate", "effective_surface", "audit_binding"):
        if not isinstance(obj[key], dict) or not obj[key]:
            code = {
                "control_plane_prestate": "control_plane_cas_invalid",
                "effective_surface": "effective_surface_invalid",
                "audit_binding": "audit_chain_invalid",
            }[key]
            _deny(code, f"{key} missing")
    transaction_value = obj["transaction"]
    if not isinstance(transaction_value, dict):
        _deny("replay_detected", "transaction binding missing")
    transaction_keys = {
        "id",
        "transaction_id",
        "nonce",
        "attempt_kind",
        "attempt_id",
        "registry_path",
        "registry_event_sha256",
        "external_commit_marker_sha256",
    }
    transaction_keys.update(
        key
        for key in ("lock_state", "publication_collision")
        if key in transaction_value
    )
    transaction = _object(
        transaction_value,
        transaction_keys,
        "replay_detected",
        "fan-in transaction binding",
    )
    if transaction["attempt_kind"] != "FINAL_FAN_IN":
        _deny("replay_detected", "fan-in transaction kind invalid")
    attempt_id = transaction["attempt_id"]
    if not isinstance(attempt_id, str) or ATTEMPT_RE.fullmatch(attempt_id) is None:
        _deny("replay_detected", "fan-in transaction attempt invalid")
    if transaction["registry_path"] != REGISTRY_DEFAULT:
        _deny("replay_detected", "fan-in registry path invalid")
    registry = captures.capture(REGISTRY_DEFAULT, code="replay_detected")
    assert registry is not None
    states = replay_registry(contract, registry)
    if states.get(("FINAL_FAN_IN", attempt_id)) not in {
        "ALLOCATED",
        "ACTIVE",
        "RECOVERING",
        "READY_FOR_EXTERNAL_MARKER",
    }:
        _deny("replay_detected", "fan-in attempt is not active")
    allocation = None
    for line in registry.data.splitlines():
        event = strict_loads(line, code="replay_detected")
        if (
            event.get("attempt_kind") == "FINAL_FAN_IN"
            and event.get("attempt_id") == attempt_id
            and event.get("event_type") == "ALLOCATED"
        ):
            allocation = (event, _sha(line))
            break
    if allocation is None:
        _deny("replay_detected", "fan-in allocation event missing")
    assert allocation is not None
    event, event_sha = allocation
    for field in ("transaction_id", "nonce"):
        if transaction[field] != event[field]:
            _deny("replay_detected", f"fan-in {field} does not bind registry")
    if transaction["registry_event_sha256"] != event_sha:
        _deny("replay_detected", "fan-in allocation hash mismatch")
    if transaction.get("lock_state") == "lost":
        _deny("lock_or_writer_race", "reconciliation lock lost")
    if transaction.get("publication_collision") is True:
        _deny("publication_transaction_failed", "output path collision")
    cycle_semantics = obj["control_plane_prestate"].get("cycle_semantics")
    if cycle_semantics is not None and cycle_semantics != {
        "session_id": SESSION_ID,
        "spec_id": SPEC_ID,
        "cycle_id": CYCLE_ID,
        "status": "terminal",
    }:
        _deny("cycle_semantics_invalid", "cycle semantic projection invalid")
    ledger_semantics = obj["control_plane_prestate"].get("ledger_semantics")
    if ledger_semantics is not None and ledger_semantics != {
        "status": "terminal",
        "active_writer_count": 0,
    }:
        _deny("ledger_semantics_invalid", "ledger semantic projection invalid")
    receipt_commit = transaction["external_commit_marker_sha256"]
    if (
        receipt_commit is not None
        and receipt_commit != hb["binding"]["external_commit_marker"]["sha256_external"]
    ):
        _deny("uncommitted_receipt", "envelope receipt is not marker committed")
    validate_integrity(obj, code="invalid_envelope")
    if verify_runtime:
        verify_runtime_attestations(obj, captures.root)


@dataclass(frozen=True)
class RuntimeAttestationProof:
    """In-process proof that one immutable runtime projection was rerun live."""

    root_realpath: str
    ownership_sha256: str
    cleanup_sha256: str


def _runtime_attestation_proof(
    root: Path | str, envelope: Mapping[str, Any]
) -> RuntimeAttestationProof:
    return RuntimeAttestationProof(
        root_realpath=str(Path(root).resolve()),
        ownership_sha256=canonical_sha(envelope.get("ownership_snapshot")),
        cleanup_sha256=canonical_sha(envelope.get("cleanup_black_box")),
    )


def _validate_runtime_proof(
    proof: RuntimeAttestationProof,
    root: Path | str,
    envelope: Mapping[str, Any],
) -> None:
    expected = _runtime_attestation_proof(root, envelope)
    if proof != expected:
        _deny(
            "nf_runtime_proof_invalid",
            "cached runtime proof does not bind this root/ownership/cleanup projection",
        )


def consume_envelope(
    root: Path | str,
    *,
    contract_path: str,
    envelope_path: str,
    runtime_proof: RuntimeAttestationProof | None = None,
) -> dict[str, Any]:
    start_ns = time.monotonic_ns()
    with CaptureSet(root) as captures:
        gate = captures.capture(
            "scripts/laneb-integration-gate.py", code="gate_identity_drift"
        )
        _cap, contract = load_contract(captures, contract_path)
        envelope_cap, envelope = captures.json(envelope_path, code="invalid_envelope")
        validate_envelope(
            envelope,
            captures,
            contract,
            verify_runtime=runtime_proof is None,
        )
        if runtime_proof is not None:
            _validate_runtime_proof(runtime_proof, root, envelope)
        captures.revalidate()
        assert gate
        result = {
            "schema_version": 2,
            "record_type": "laneb_fan_in_consumer_result.v2",
            "status": "pass",
            "fan_in_status": "pass",
            "H_B_FANIN_passed": True,
            "final_qa_eligible": True,
            "envelope_sha256": envelope_cap.sha256,
            "gate_sha256": gate.sha256,
            "monotonic_duration_ns": time.monotonic_ns() - start_ns,
            **NONCLAIMS,
            "authorizes": [
                "independent_final_LANE_B_QA_dispatch_only_after_external_commit_marker"
            ],
        }
        result["result_digest"] = canonical_sha(result)
        return result


def produce_envelope(
    root: Path | str,
    *,
    contract_path: str,
    bundle_path: str,
    runtime_proof: RuntimeAttestationProof | None = None,
) -> dict[str, Any]:
    # Producer and consumer use separate descriptor sets.  The producer accepts a
    # complete candidate only; it never fills authority-bearing fields from prose.
    with CaptureSet(root) as captures:
        _cap, contract = load_contract(captures, contract_path)
        _bundle_cap, bundle = captures.json(bundle_path, code="invalid_envelope")
        validate_envelope(
            bundle,
            captures,
            contract,
            verify_runtime=runtime_proof is None,
        )
        if runtime_proof is not None:
            _validate_runtime_proof(runtime_proof, root, bundle)
        captures.revalidate()
        return bundle


def build_runtime_attestations(
    root: Path | str, envelope: Mapping[str, Any]
) -> dict[str, Any]:
    """Producer-side builder; consumers never trust these serialized claims."""

    candidate = copy.deepcopy(dict(envelope))
    candidate["ownership_snapshot"] = live_ownership_census(root, candidate)
    candidate["cleanup_black_box"] = run_cleanup_black_box(root)
    integrity = candidate.get("integrity")
    if not isinstance(integrity, dict):
        _deny("invalid_envelope", "runtime-attested envelope integrity missing")
    candidate["integrity"]["canonical_payload_sha256"] = _payload_digest(candidate)
    return candidate


NF_CODES_PRODUCER = frozenset(
    {
        "waiting",
        "stale_h_b_generation",
        "h_b_source_map_mismatch",
        "current_pol_identity_required",
        "provider_qa_invalid",
        "qa_provider_digest_mismatch",
        "historical_provider_rejected",
        "bind_lineage_incomplete",
        "lease_provider_missing",
        "cleanup_blackbox_invalid",
        "cleanup_isolation_failure",
        "cycle_semantics_invalid",
        "ledger_semantics_invalid",
        "ownership_snapshot_invalid",
        "active_handle_or_process",
        "effective_surface_invalid",
        "matrix_evidence_invalid",
        "ac_matrix_closed_set_invalid",
        "transitive_provider_invalid",
        "late_lane_not_terminal",
        "invalid_envelope",
        "freshness_invalid",
        "stable_fd_drift",
        "lock_or_writer_race",
        "gate_identity_drift",
        "publication_transaction_failed",
        "replay_detected",
        "audit_chain_invalid",
        "control_plane_cas_invalid",
        "illegal_downstream_projection",
        "missing_ownership_evidence",
    }
)
NF_CODES_CONSUMER = frozenset((*NF_CODES_PRODUCER, "uncommitted_receipt"))


def exercise_nf32_matrix(
    contract: Mapping[str, Any],
    fixture_factory: Any,
) -> list[dict[str, Any]]:
    """Run each NF mutation from one live-verified immutable baseline.

    ``fixture_factory`` is deliberately supplied by the caller so the gate does
    not manufacture provider authority.  The baseline runs the real commit,
    producer, consumer, live census, and cleanup path once.  Every observation
    then restores the same immutable bytes, applies one mutation, and calls the
    real producer/consumer with the in-process runtime proof bound to the exact
    root/ownership/cleanup projection.  Mismatches remain non-authorizing rows.
    """

    definitions = contract["preserved_attempt1_passed_contracts"][
        "negative_test_contract"
    ]
    if (
        not isinstance(definitions, list)
        or len(definitions) != 32
        or [item.get("id") for item in definitions]
        != [f"NF-{index:02d}" for index in range(1, 33)]
        or [item.get("expected_code") for item in definitions] != list(NF_CODES)
    ):
        _deny(
            "nf_fixture_contract_invalid",
            "NF-01..NF-32 definition is not a closed ordered set",
        )
    fixture = fixture_factory()
    if not isinstance(fixture, Mapping) or set(fixture) != {
        "root",
        "contract_path",
        "binding_path",
        "envelope_path",
        "reset",
        "mutate",
        "cleanup",
    }:
        _deny("nf_fixture_invalid", "NF fixture factory contract invalid")
    root = Path(fixture["root"])
    contract_path = fixture["contract_path"]
    binding_path = fixture["binding_path"]
    envelope_path = fixture["envelope_path"]
    reset = fixture["reset"]
    mutate = fixture["mutate"]
    cleanup = fixture["cleanup"]
    if not callable(reset) or not callable(mutate) or not callable(cleanup):
        _deny("nf_fixture_invalid", "NF fixture callbacks invalid")
    rows: list[dict[str, Any]] = []
    try:
        baseline = strict_loads(
            (root / envelope_path).read_bytes(), code="nf_fixture_invalid"
        )
        if not isinstance(baseline, dict):
            _deny("nf_fixture_invalid", "NF baseline envelope is not an object")
        proof = _runtime_attestation_proof(root, baseline)
        verify_hb3_commit(
            root,
            contract_path=contract_path,
            binding_path=binding_path,
        )
        verify_runtime_attestations(baseline, root)
        produce_envelope(
            root,
            contract_path=contract_path,
            bundle_path=envelope_path,
            runtime_proof=proof,
        )
        consume_envelope(
            root,
            contract_path=contract_path,
            envelope_path=envelope_path,
            runtime_proof=proof,
        )

        def invoke(stage: str) -> None:
            if stage == "producer":
                produce_envelope(
                    root,
                    contract_path=contract_path,
                    bundle_path=envelope_path,
                    runtime_proof=proof,
                )
            else:
                consume_envelope(
                    root,
                    contract_path=contract_path,
                    envelope_path=envelope_path,
                    runtime_proof=proof,
                )

        for ordinal, item in enumerate(definitions, 1):
            expected = item["expected_code"]
            stages = (
                ["consumer"]
                if expected == "uncommitted_receipt"
                else ["producer", "consumer"]
            )
            observed: list[dict[str, str]] = []
            for stage in stages:
                reset()
                invoke(stage)
                reset()
                mutate(item["id"])
                entrypoint = (
                    "produce_envelope" if stage == "producer" else "consume_envelope"
                )
                try:
                    invoke(stage)
                except GateError as exc:
                    code = exc.code
                else:
                    code = "mutation_was_accepted"
                reset()
                invoke(stage)
                observed.append(
                    {
                        "stage": stage,
                        "entrypoint": entrypoint,
                        "expected_code": expected,
                        "actual_code": code,
                    }
                )
            row = {
                "ordinal": ordinal,
                "id": item["id"],
                "expected_code": expected,
                "observations": observed,
                "status": (
                    "pass"
                    if all(value["actual_code"] == expected for value in observed)
                    else "fail"
                ),
                "authority": False,
                "authorizes": [],
            }
            row["fixture_sha256"] = canonical_sha(
                {"id": item["id"], "case": item["case"], "stages": stages}
            )
            rows.append(row)
    finally:
        cleanup()
    return rows


RECOVERY_STATES = (
    "S0_ALLOCATED",
    "S1_INTENT",
    "S2_EVIDENCE",
    "S3_LEDGER_ONLY",
    "S4_BOTH_PREPARED",
    "S5_AUDIT_READY",
    "S6_COMMITTED",
    "SX_INCONSISTENT",
)


def classify_transaction(files: Mapping[str, bool], control: Mapping[str, str]) -> str:
    keys = {
        "intent",
        "evidence",
        "ledger_prepared",
        "cycle_prepared",
        "audit_ready",
        "marker",
    }
    if set(files) != keys:
        return "SX_INCONSISTENT"
    pattern: tuple[bool, bool, bool, bool, bool, bool] = (
        bool(files["intent"]),
        bool(files["evidence"]),
        bool(files["ledger_prepared"]),
        bool(files["cycle_prepared"]),
        bool(files["audit_ready"]),
        bool(files["marker"]),
    )
    mapping: dict[tuple[bool, bool, bool, bool, bool, bool], str] = {
        (False, False, False, False, False, False): "S0_ALLOCATED",
        (True, False, False, False, False, False): "S1_INTENT",
        (True, True, False, False, False, False): "S2_EVIDENCE",
        (True, True, True, False, False, False): "S3_LEDGER_ONLY",
        (True, True, True, True, False, False): "S4_BOTH_PREPARED",
        (True, True, True, True, True, False): "S5_AUDIT_READY",
        (True, True, True, True, True, True): "S6_COMMITTED",
    }
    state = mapping.get(pattern, "SX_INCONSISTENT")
    if state == "S3_LEDGER_ONLY" and control.get("ledger") != "prepared":
        return "SX_INCONSISTENT"
    if state in {"S4_BOTH_PREPARED", "S5_AUDIT_READY", "S6_COMMITTED"} and (
        control.get("ledger"),
        control.get("cycle"),
    ) != ("prepared", "prepared"):
        return "SX_INCONSISTENT"
    return state


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def no_replace_write(path: Path, data: bytes, mode: int = 0o444) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    except FileExistsError:
        if path.is_file() and not path.is_symlink() and path.read_bytes() == data:
            return _sha(data)
        _deny("publication_transaction_failed", f"no-replace collision: {path.name}")
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_dir(path.parent)
    if _sha(path.read_bytes()) != _sha(data):
        _deny("publication_transaction_failed", "post-install hash mismatch")
    return _sha(data)


def exact_cas(path: Path, before: bytes, after: bytes) -> None:
    if path.is_symlink() or not path.is_file() or path.read_bytes() != before:
        _deny("control_plane_cas_invalid", f"CAS preimage mismatch: {path.name}")
    temp = path.with_name(f".{path.name}.cas-{os.getpid()}-{time.monotonic_ns()}")
    fd = os.open(
        temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IMODE(path.stat().st_mode)
    )
    try:
        os.write(fd, after)
        os.fsync(fd)
    finally:
        os.close(fd)
    if path.read_bytes() != before:
        temp.unlink(missing_ok=True)
        _deny("control_plane_cas_invalid", "CAS race")
    os.replace(temp, path)
    _fsync_dir(path.parent)


@contextlib.contextmanager
def exclusive_lock(path: Path) -> Iterator[str]:
    if path.is_symlink():
        _deny("lock_or_writer_race", "lock is symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _deny("lock_or_writer_race", "reconciliation lock contended")
        st = os.fstat(fd)
        yield f"{st.st_dev}:{st.st_ino}"
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _safe_transaction_path(base: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        _deny("publication_transaction_failed", "invalid transaction path")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        _deny("publication_transaction_failed", "transaction path escapes root")
    path = base.joinpath(*pure.parts)
    current = base
    for part in pure.parts[:-1]:
        current = current / part
        if current.exists() and (current.is_symlink() or not current.is_dir()):
            _deny("publication_transaction_failed", "unsafe transaction ancestor")
    if path.is_symlink():
        _deny("publication_transaction_failed", "transaction path is symlink")
    return path


def _transaction_snapshot(
    outputs: Sequence[Mapping[str, Any]],
    cycle: Path,
    ledger: Path,
    before_cycle: bytes,
    after_cycle: bytes,
    before_ledger: bytes,
    after_ledger: bytes,
    base: Path,
) -> tuple[str, dict[str, bool], dict[str, str]]:
    present: dict[int, bool] = {}
    for row in outputs:
        path = _safe_transaction_path(base, row["path"])
        data = bytes.fromhex(row["hex"])
        if path.exists():
            if not path.is_file() or path.read_bytes() != data:
                return "SX_INCONSISTENT", {}, {}
            present[row["step"]] = True
        else:
            present[row["step"]] = False
    files = {
        "intent": present[1],
        "evidence": present[2],
        "ledger_prepared": present[3],
        "cycle_prepared": present[4],
        "audit_ready": present[5],
        "marker": present[6],
    }
    control = {
        "cycle": (
            "prepared"
            if cycle.read_bytes() == after_cycle
            else ("pre" if cycle.read_bytes() == before_cycle else "other")
        ),
        "ledger": (
            "prepared"
            if ledger.read_bytes() == after_ledger
            else ("pre" if ledger.read_bytes() == before_ledger else "other")
        ),
    }
    state = classify_transaction(files, control)
    if state in {"S0_ALLOCATED", "S1_INTENT", "S2_EVIDENCE"} and control != {
        "cycle": "pre",
        "ledger": "pre",
    }:
        state = "SX_INCONSISTENT"
    if state == "S3_LEDGER_ONLY" and control != {"cycle": "pre", "ledger": "prepared"}:
        state = "SX_INCONSISTENT"
    return state, files, control


def sandbox_transaction(root: Path | str, spec_path: str) -> dict[str, Any]:
    base = Path(root).resolve()
    marker = base / ".laneb-throwaway-transaction-root"
    if not marker.is_file() or marker.is_symlink() or (base / ".git").exists():
        _deny(
            "publication_transaction_failed",
            "transaction writes require marked non-repository throwaway root",
        )
    spec = strict_loads(
        _safe_transaction_path(base, spec_path).read_bytes(),
        code="publication_transaction_failed",
    )
    if not isinstance(spec, dict):
        _deny("publication_transaction_failed", "transaction spec must be object")
    base_keys = {
        "lock",
        "cycle",
        "ledger",
        "cycle_before_hex",
        "cycle_after_hex",
        "ledger_before_hex",
        "ledger_after_hex",
        "outputs",
        "crash_after",
    }
    if set(spec) not in {frozenset(base_keys), frozenset(base_keys | {"action"})}:
        _deny("publication_transaction_failed", "transaction spec closed keys mismatch")
    action = spec.get("action", "forward")
    if action not in {"forward", "rollback"}:
        _deny("publication_transaction_failed", "transaction action invalid")
    try:
        before_cycle = bytes.fromhex(spec["cycle_before_hex"])
        after_cycle = bytes.fromhex(spec["cycle_after_hex"])
        before_ledger = bytes.fromhex(spec["ledger_before_hex"])
        after_ledger = bytes.fromhex(spec["ledger_after_hex"])
    except (TypeError, ValueError):
        _deny("publication_transaction_failed", "transaction hex bytes invalid")
    cycle = _safe_transaction_path(base, spec["cycle"])
    ledger = _safe_transaction_path(base, spec["ledger"])
    lock = _safe_transaction_path(base, spec["lock"])
    outputs = spec["outputs"]
    if (
        not isinstance(outputs, list)
        or len(outputs) != 6
        or any(
            not isinstance(row, dict)
            or set(row) != {"path", "hex", "step"}
            or not _is_int(row["step"])
            for row in outputs
        )
        or [row["step"] for row in outputs] != [1, 2, 3, 4, 5, 6]
        or len({row["path"] for row in outputs}) != 6
    ):
        _deny(
            "publication_transaction_failed",
            "transaction requires six unique ordered S1-S6 outputs",
        )
    for row in outputs:
        try:
            bytes.fromhex(row["hex"])
        except (TypeError, ValueError):
            _deny("publication_transaction_failed", "output bytes invalid")
        _safe_transaction_path(base, row["path"])
    crash_after = spec["crash_after"]
    if crash_after is not None and (
        not _is_int(crash_after) or crash_after not in range(1, 7)
    ):
        _deny("publication_transaction_failed", "crash point invalid")

    with exclusive_lock(lock) as identity:
        if not cycle.is_file() or not ledger.is_file():
            _deny("control_plane_cas_invalid", "control file missing")
        state, _files, control = _transaction_snapshot(
            outputs,
            cycle,
            ledger,
            before_cycle,
            after_cycle,
            before_ledger,
            after_ledger,
            base,
        )
        if state == "SX_INCONSISTENT":
            _deny("control_plane_cas_invalid", "transaction is inconsistent SX")
        if action == "rollback":
            if state == "S6_COMMITTED":
                _deny("control_plane_cas_invalid", "rollback forbidden after S6")
            # Exact bounded reverse order; immutable evidence/steps remain.
            if control["cycle"] == "prepared":
                exact_cas(cycle, after_cycle, before_cycle)
            elif control["cycle"] != "pre":
                _deny("control_plane_cas_invalid", "cycle rollback CAS mismatch")
            if control["ledger"] == "prepared":
                exact_cas(ledger, after_ledger, before_ledger)
            elif control["ledger"] != "pre":
                _deny("control_plane_cas_invalid", "ledger rollback CAS mismatch")
            return {
                "status": "terminal_no_authority",
                "state_before": state,
                "rollback_order": ["cycle", "ledger"],
                "evidence_preserved": True,
                "lock_identity": identity,
                **NONCLAIMS,
            }
        if state == "S6_COMMITTED":
            return {
                "status": "pass",
                "state": state,
                "idempotent": True,
                "marker_installed_last": True,
                "lock_identity": identity,
                **NONCLAIMS,
            }
        written: list[str] = []
        for row in outputs:
            step = row["step"]
            path = _safe_transaction_path(base, row["path"])
            data = bytes.fromhex(row["hex"])
            if path.exists():
                if path.read_bytes() != data:
                    _deny("publication_transaction_failed", "step collision")
                continue
            if step == 3:
                if ledger.read_bytes() == before_ledger:
                    exact_cas(ledger, before_ledger, after_ledger)
                elif ledger.read_bytes() != after_ledger:
                    _deny("control_plane_cas_invalid", "ledger forward CAS mismatch")
            elif step == 4:
                if ledger.read_bytes() != after_ledger:
                    _deny("control_plane_cas_invalid", "cycle prepared before ledger")
                if cycle.read_bytes() == before_cycle:
                    exact_cas(cycle, before_cycle, after_cycle)
                elif cycle.read_bytes() != after_cycle:
                    _deny("control_plane_cas_invalid", "cycle forward CAS mismatch")
            if step >= 5 and (
                cycle.read_bytes() != after_cycle or ledger.read_bytes() != after_ledger
            ):
                _deny("control_plane_cas_invalid", "audit/marker before both controls")
            no_replace_write(path, data)
            written.append(row["path"])
            if crash_after == step:
                return {
                    "status": "recovery_required",
                    "state": f"S{step}",
                    "lock_identity": identity,
                    "written": written,
                    "marker_visible": step == 6,
                }
        final_state, _files, _control = _transaction_snapshot(
            outputs,
            cycle,
            ledger,
            before_cycle,
            after_cycle,
            before_ledger,
            after_ledger,
            base,
        )
        if final_state != "S6_COMMITTED":
            _deny("publication_transaction_failed", "transaction did not reach S6")
        return {
            "status": "pass",
            "state": "S6_COMMITTED",
            "lock_identity": identity,
            "written": written,
            "marker_installed_last": True,
            **NONCLAIMS,
        }


# ---------------------------------------------------------------------------
# Lane-B registry v4 additive migration and control plane.
# ---------------------------------------------------------------------------
V4_CONTEXT_DEFAULT = "docs/dev/context-20260815-lane-b-registry-v4-repair-v2.json"
V4_CONTEXT_SHA256 = "5b301d21c17fe36ea19e2177ddf1494fac4c47b2c3f2292e9278b00d1f1cd831"
V4_TICKET_PATH = "docs/dev/ticket-20260815-lane-b-registry-v4-repair-v2.md"
V4_TICKET_SHA256 = "4fd9c382073eaf2521770b6641ef79953f77db75389fe443d519aeb46a6808b5"
V4_BA_QA_PATH = "docs/dev/ba-qa-report-20260815-lane-b-registry-v4-repair-v2.json"
V4_BA_QA_SHA256 = "657d7237a18f069df6d6df4e7bde935aec64bb12a1339412a5dd276eb8ec9de6"
V4_PARENT_ADMISSION_PATH = (
    "docs/dev/overnight/019fe5c1-5b46-7dd1-8086-591a5b932bf3/cycle-1/"
    "lane-b-registry-v4-repair-v2-dev-admission-successor.v1.json"
)
V4_PARENT_ADMISSION_SHA256 = (
    "af52fb5d5e8bcfffcaa500a3b98e81e06fc6a20faddac1dd605f540a1d46b1e5"
)
V4_EVENT_SCHEMA_SHA256 = (
    "731b5b6f9b6d5a6e576ab3b009940239e3283059f611aba2346fbbd3e5a951b1"
)
V4_MIGRATION_RECORD_SCHEMA_SHA256 = (
    "f7d859658e62c8571a3b17b896db6cb5c88f6e573dc7a5ce2e15a4436ead5cea"
)
V4_MIGRATION_AUDIT_SCHEMA_SHA256 = (
    "8cd96b522ff973962cbe102dced56dbc35c3694ebdf069550d66ee3867a253bc"
)
V4_EVIDENCE_SCHEMA_SHA256 = {
    "producer_evidence": "25a7d6ce0b4864e37f5b8f656e54f3a83b574b89970bef0c6a0097fcbd6282eb",
    "independent_qa_evidence": "492359d8cf62276c7371b7d046d036a1de0bef1759433c415fd7f11bc5a221c0",
    "readiness": "3b6d58125079440857d083825d2735b211b77bb83a2681b1019725e9d608e06b",
    "receipt": "1adce0e70454734898e9767abd24502d6fe72b0dfc249bd0bf71f0d6e53c4565",
    "marker": "42927a7b8dbaec9aaefd057716589fde9e79fa8e550e0b718d21eb80f0602508",
}
V4_PROVIDER_POLICY_SHA256 = (
    "4b6e20f75e7fe69dd9579792e643928da4518d23a2cbd963a64016fcb64a4912"
)
V4_CONSUMER_MAP_SHA256 = (
    "f9861df6a5a9c1de183b031313314f2f75cff2719689850d7fc125f0e263bb90"
)
V4_OLD_PROVIDER_MAP_SHA256 = (
    "b47ac44c2685c0efc2afe0775fe6a30d86406b25c6a2c967732b3b051611f086"
)
V4_MIGRATION_ID = "LANE-B-REGISTRY-V3-TO-V4-CYCLE1-R1"
V4_INTEGRITY_LANGUAGE = (
    "UTF-8 NFC sorted-key compact JSON; event_payload_sha256 omitted from its "
    "own payload; LF excluded from payload and prior-event hash"
)
V4_PHASES = {
    "registry-v4-migration-preflight",
    "registry-v4-migration-commit",
    "registry-v4-allocate",
    "registry-v4-transition",
    "registry-v4-recover",
    "verify-h-b-v4-provider-set",
}
V4_TX_RE = re.compile(r"^[0-9a-f]{32}$")


class V4Error(GateError):
    """A v4 denial with the public 0/2/3/4/5 exit taxonomy."""

    def __init__(
        self, exit_code: int, code: str, message: str, *, state: str = "denied"
    ):
        super().__init__(code, "same-spec parent", message, state=state)
        self.exit_code = exit_code


def _v4_deny(exit_code: int, code: str, message: str, *, state: str = "denied") -> None:
    if exit_code not in {2, 3, 4, 5}:
        raise AssertionError("invalid v4 exit code")
    raise V4Error(exit_code, code, message, state=state)


def _v4_contract(message: str, code: str = "v4_contract_denied") -> None:
    _v4_deny(2, code, message)


def _v4_tamper(message: str, code: str = "v4_tamper_denied") -> None:
    _v4_deny(3, code, message)


def _v4_recovery(message: str) -> None:
    _v4_deny(5, "v4_recovery_required", message, state="recovery_required")


def _v4_nfc(value: Any) -> None:
    if isinstance(value, str):
        if unicodedata.normalize("NFC", value) != value:
            _v4_tamper("non-NFC string")
    elif isinstance(value, dict):
        for key, item in value.items():
            _v4_nfc(key)
            _v4_nfc(item)
    elif isinstance(value, list):
        for item in value:
            _v4_nfc(item)


def _v4_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            _v4_tamper(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _v4_load_json(data: bytes, *, line_framed: bool = False) -> Any:
    if data.startswith(b"\xef\xbb\xbf") or b"\r" in data:
        _v4_tamper("BOM/CR framing forbidden")
    if line_framed:
        if not data.endswith(b"\n") or data.count(b"\n") != 1 or not data[:-1]:
            _v4_tamper("canonical JSON artifact requires exactly one final LF")
        data = data[:-1]
    try:
        text = data.decode("utf-8", "strict")
        value = json.loads(
            text,
            object_pairs_hook=_v4_pairs,
            parse_constant=lambda token: _v4_tamper(f"non-finite JSON: {token}"),
        )
    except V4Error:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        _v4_tamper(f"invalid strict JSON: {type(exc).__name__}")
    _finite(value)
    _v4_nfc(value)
    if line_framed and _canonical(value) != data:
        _v4_tamper("JSON artifact is not canonical compact UTF-8")
    return value


def _v4_json_line(value: Any) -> bytes:
    _v4_nfc(value)
    return _canonical(value) + b"\n"


def _v4_parts(value: Any) -> tuple[str, ...]:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or "\\" in value
        or unicodedata.normalize("NFC", value) != value
    ):
        _v4_tamper("invalid/non-NFC root-relative path", "v4_path_denied")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        _v4_tamper("absolute or traversal path forbidden", "v4_path_denied")
    return pure.parts


@dataclass(frozen=True)
class V4File:
    path: str
    data: bytes
    mode: str
    nlink: int
    device: int
    inode: int
    mtime_ns: int = 0
    ctime_ns: int = 0

    @property
    def sha256(self) -> str:
        return _sha(self.data)

    def ref(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "bytes": len(self.data),
            "sha256": self.sha256,
            "mode": self.mode,
            "nlink": self.nlink,
            "state": "file",
            "symlink": False,
        }


class V4Root:
    """Nofollow dirfd surface for every v4 path read or mutation."""

    def __init__(self, root: Path | str):
        requested = Path(root)
        if not requested.is_absolute():
            requested = Path.cwd() / requested
        if requested.is_symlink() or not requested.is_dir():
            _v4_tamper("project root must be a real directory", "v4_path_denied")
        self.root = requested.resolve(strict=True)
        if requested.absolute() != self.root:
            _v4_tamper("project root contains symlink/alias", "v4_path_denied")
        self.fd = os.open(
            self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
        )

    def close(self) -> None:
        with contextlib.suppress(OSError):
            os.close(self.fd)

    def __enter__(self) -> "V4Root":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextlib.contextmanager
    def parent(self, rel: str) -> Iterator[tuple[int, str]]:
        parts = _v4_parts(rel)
        fd = os.dup(self.fd)
        try:
            for part in parts[:-1]:
                try:
                    nxt = os.open(
                        part,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                        dir_fd=fd,
                    )
                except OSError:
                    _v4_tamper(f"unsafe/missing ancestor: {rel}", "v4_path_denied")
                os.close(fd)
                fd = nxt
            yield fd, parts[-1]
        finally:
            os.close(fd)

    def read(
        self,
        rel: str,
        *,
        modes: set[int] | None = None,
        optional: bool = False,
    ) -> V4File | None:
        with self.parent(rel) as (parent_fd, name):
            try:
                fd = os.open(
                    name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=parent_fd
                )
            except OSError as exc:
                if optional and exc.errno == errno.ENOENT:
                    return None
                _v4_tamper(f"unsafe/missing file: {rel}", "v4_path_denied")
            try:
                before = os.fstat(fd)
                mode = stat.S_IMODE(before.st_mode)
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_nlink != 1
                    or (modes is not None and mode not in modes)
                    or before.st_size > MAX_INPUT_BYTES
                ):
                    _v4_tamper(f"file identity/mode invalid: {rel}")
                chunks: list[bytes] = []
                size = 0
                while True:
                    chunk = os.read(fd, 1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_INPUT_BYTES:
                        _v4_tamper(f"file too large: {rel}")
                    chunks.append(chunk)
                after = os.fstat(fd)
                if (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    mode,
                    before.st_nlink,
                    before.st_mtime_ns,
                    before.st_ctime_ns,
                ) != (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                    stat.S_IMODE(after.st_mode),
                    after.st_nlink,
                    after.st_mtime_ns,
                    after.st_ctime_ns,
                ):
                    _v4_tamper(f"descriptor drift: {rel}")
                return V4File(
                    rel,
                    b"".join(chunks),
                    f"{mode:04o}",
                    before.st_nlink,
                    before.st_dev,
                    before.st_ino,
                    before.st_mtime_ns,
                    before.st_ctime_ns,
                )
            finally:
                os.close(fd)

    def exists(self, rel: str) -> bool:
        with self.parent(rel) as (parent_fd, name):
            try:
                st = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                return False
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                _v4_tamper(f"non-regular/symlink target: {rel}", "v4_path_denied")
            if st.st_nlink != 1:
                _v4_tamper(f"hardlink forbidden: {rel}")
            return True

    def create(self, rel: str, data: bytes, mode: int) -> V4File:
        with self.parent(rel) as (parent_fd, name):
            try:
                fd = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                    mode,
                    dir_fd=parent_fd,
                )
            except FileExistsError:
                _v4_tamper(f"O_EXCL collision: {rel}", "v4_collision_denied")
            except OSError:
                _v4_tamper(f"unsafe create target: {rel}", "v4_path_denied")
            try:
                os.fchmod(fd, mode)
                view = memoryview(data)
                while view:
                    count = os.write(fd, view)
                    if count <= 0:
                        _v4_recovery(f"partial create write: {rel}")
                    view = view[count:]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(parent_fd)
        result = self.read(rel, modes={mode})
        assert result is not None
        if result.data != data:
            _v4_tamper(f"reopen mismatch: {rel}")
        return result


@contextlib.contextmanager
def _v4_lock(root: V4Root, rel: str, timeout: float) -> Iterator[str]:
    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or not 0 <= timeout <= 30
    ):
        _v4_contract("lock timeout outside 0..30 seconds")
    with root.parent(rel) as (parent_fd, name):
        try:
            fd = os.open(
                name, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=parent_fd
            )
        except OSError:
            _v4_tamper("lock path missing or unsafe", "v4_path_denied")
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                _v4_tamper("lock identity invalid")
            deadline = time.monotonic() + float(timeout)
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        _v4_deny(
                            4,
                            "v4_lock_timeout",
                            "live parent lock timed out",
                            state="lock_timeout",
                        )
                    time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
            current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if (current.st_dev, current.st_ino) != (st.st_dev, st.st_ino):
                _v4_tamper("lock inode replacement")
            yield f"{st.st_dev}:{st.st_ino}"
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def _v4_schema(instance: Any, schema: Mapping[str, Any]) -> None:
    if jsonschema is None:
        _v4_contract("jsonschema runtime unavailable", "v4_schema_invalid")
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(instance)
    except Exception as exc:
        _v4_contract(
            f"Draft-2020-12 validation failed: {type(exc).__name__}",
            "v4_schema_invalid",
        )


def _v4_context(root: V4Root, path: str) -> tuple[V4File, dict[str, Any]]:
    cap = root.read(path, modes={0o444})
    assert cap is not None
    if path != V4_CONTEXT_DEFAULT or cap.sha256 != V4_CONTEXT_SHA256:
        _v4_contract("v4 repair-v2 context identity drift")
    repair = _v4_load_json(cap.data)
    if not isinstance(repair, dict):
        _v4_contract("v4 context must be object")
    if (
        repair.get("schema_name") != "lane_b_registry_v4_repair_ba_contract.v2"
        or repair.get("schema_version") != 2
        or repair.get("session_id") != SESSION_ID
        or repair.get("spec_id") != SPEC_ID
        or repair.get("cycle_id") != CYCLE_ID
        or repair.get("lane_id") != LANE_ID
        or repair.get("pipeline_id") != PIPELINE_ID
    ):
        _v4_contract("wrong v4 repair-v2 context identity")

    predecessor_ref = repair.get("authoritative_inputs", {}).get("predecessor_context")
    if not isinstance(predecessor_ref, dict):
        _v4_contract("predecessor context binding missing")
    predecessor = root.read(predecessor_ref.get("path", ""), modes={0o444})
    if predecessor is None or predecessor.ref() != predecessor_ref:
        _v4_tamper("predecessor context immutable identity drift")
    predecessor_value = _v4_load_json(predecessor.data)
    if not isinstance(predecessor_value, dict):
        _v4_contract("predecessor context must be object")
    # Repair-v2 is append-only: retain the predecessor operational contract and
    # overlay only the immutable successor sections from the exact new context.
    value = copy.deepcopy(predecessor_value)
    value.update(copy.deepcopy(repair))

    schemas = value.get("closed_schemas")
    if not isinstance(schemas, dict):
        _v4_contract("closed schemas missing", "v4_schema_invalid")
    expected = {
        "event": V4_EVENT_SCHEMA_SHA256,
        "migration_record": V4_MIGRATION_RECORD_SCHEMA_SHA256,
        "migration_audit": V4_MIGRATION_AUDIT_SCHEMA_SHA256,
        **V4_EVIDENCE_SCHEMA_SHA256,
    }
    for name, digest in expected.items():
        schema = schemas.get(name + "_schema")
        if (
            not isinstance(schema, dict)
            or canonical_sha(schema) != digest
            or schemas.get(name + "_schema_sha256") != digest
        ):
            _v4_contract(f"{name} schema digest drift", "v4_schema_invalid")
        if jsonschema is None:
            _v4_contract("jsonschema runtime unavailable", "v4_schema_invalid")
        try:
            jsonschema.Draft202012Validator.check_schema(schema)
        except Exception as exc:
            _v4_contract(
                f"{name} schema meta-invalid: {type(exc).__name__}",
                "v4_schema_invalid",
            )

    repair_binding = value.get("provider_binding_repair")
    if not isinstance(repair_binding, dict):
        _v4_contract("repair-v2 provider policy missing", "v4_identity_denied")
    policy = repair_binding.get("provider_policy")
    consumers = repair_binding.get("consumer_map")
    if (
        not isinstance(policy, dict)
        or canonical_sha(policy) != V4_PROVIDER_POLICY_SHA256
        or repair_binding.get("provider_policy_sha256") != V4_PROVIDER_POLICY_SHA256
        or not isinstance(consumers, dict)
        or canonical_sha(consumers) != V4_CONSUMER_MAP_SHA256
        or repair_binding.get("consumer_map_sha256") != V4_CONSUMER_MAP_SHA256
        or policy.get("old_preimplementation_provider_map_sha256")
        != V4_OLD_PROVIDER_MAP_SHA256
        or policy.get("old_digest_accepted_for_repaired_lifecycle") is not False
    ):
        _v4_contract("repair-v2 provider policy digest drift", "v4_identity_denied")
    return cap, value


def _v4_paths(
    args: argparse.Namespace, context: Mapping[str, Any], root: V4Root
) -> dict[str, str]:
    defaults = {
        "context": V4_CONTEXT_DEFAULT,
        "v3": context["legacy_v3_quarantine_contract"]["source"]["path"],
        "registry": context["v4_artifacts"]["registry"]["path"],
        "record": context["v4_artifacts"]["migration_record"]["path"],
        "audit": context["v4_artifacts"]["migration_audit"]["path"],
        "lock": context["lock_CAS_and_safety"]["lock_path"],
    }
    supplied = {
        "context": args.v4_context,
        "v3": args.v3_registry,
        "registry": args.v4_registry,
        "record": args.migration_record,
        "audit": args.migration_audit,
        "lock": args.v4_lock,
    }
    if any(
        value is not None and value != defaults[key] for key, value in supplied.items()
    ):
        if not args.v4_test_mode:
            _v4_contract("production path overrides are forbidden")
    if args.v4_crash_after is not None and not args.v4_test_mode:
        _v4_contract("crash injection is test-only")
    if args.v4_test_mode:
        marker = root.read(".laneb-v4-throwaway-root", modes={0o600, 0o644})
        if (
            marker is None
            or marker.data != b"LANEB_V4_THROWAWAY\n"
            or (root.root / ".git").exists()
        ):
            _v4_contract("test overrides require marked non-repository root")
    return {key: supplied[key] or value for key, value in defaults.items()}


def _v4_validate_ref(cap: V4File, expected: Mapping[str, Any], label: str) -> None:
    if cap.ref() != dict(expected):
        _v4_tamper(f"{label} immutable identity drift")


def _v4_v3_preflight(
    root: V4Root, context: Mapping[str, Any], v3_path: str
) -> dict[str, Any]:
    quarantine = context["legacy_v3_quarantine_contract"]
    source = quarantine["source"]
    if v3_path != source["path"]:
        _v4_contract("v3 fallback/override forbidden")
    cap = root.read(v3_path, modes={0o444})
    assert cap is not None
    _v4_validate_ref(cap, source, "v3 source")
    if (
        not cap.data.endswith(b"\n")
        or b"\r" in cap.data
        or cap.data.startswith(b"\xef\xbb\xbf")
    ):
        _v4_tamper("v3 framing drift")
    raw_lines = cap.data.splitlines(keepends=True)
    if len(raw_lines) != 8 or any(
        not line.endswith(b"\n") or line == b"\n" for line in raw_lines
    ):
        _v4_contract("v3 row count/order drift", "v4_legacy_quarantine_invalid")
    old = context["authoritative_predecessors"]["attempt3_context"]
    old_cap = root.read(old["path"], modes={0o644})
    assert old_cap is not None
    _v4_validate_ref(old_cap, old, "attempt3 context")
    old_context = _v4_load_json(old_cap.data)
    schema = old_context["attempt_identity_registry"]["event_schema"]
    validator = (
        jsonschema.Draft202012Validator(schema) if jsonschema is not None else None
    )
    if validator is None:
        _v4_contract("jsonschema runtime unavailable", "v4_schema_invalid")
    valid = 0
    invalid = 0
    payload_valid = 0
    observed: list[dict[str, Any]] = []
    prior_canonical: str | None = None
    for index, framed in enumerate(raw_lines, 1):
        body = framed[:-1]
        row = _v4_load_json(body)
        if not isinstance(row, dict) or _canonical(row) != body:
            _v4_tamper("v3 canonical row drift")
        errors = sorted({error.validator for error in validator.iter_errors(row)})
        if errors:
            invalid += 1
        else:
            valid += 1
        try:
            validate_integrity(row, code="v4_legacy_quarantine_invalid")
            digest_ok = True
            payload_valid += 1
        except GateError:
            digest_ok = False
        expected = quarantine["rows"][index - 1]
        facts = {
            "line": index,
            "raw_line_bytes_including_LF": len(framed),
            "raw_line_sha256_including_LF": _sha(framed),
            "canonical_event_sha256_excluding_LF": _sha(body),
            "event_payload_sha256": row.get("integrity", {}).get(
                "event_payload_sha256"
            ),
            "event_payload_sha256_valid": digest_ok,
            "observed_previous_event_sha256": row.get("previous_event_sha256"),
            "expected_previous_canonical_event_sha256_excluding_LF": prior_canonical,
            "normative_previous_link_valid": row.get("previous_event_sha256")
            == prior_canonical,
            "attempt_kind": row.get("attempt_kind"),
            "attempt_id": row.get("attempt_id"),
            "attempt_sequence": row.get("attempt_sequence"),
            "event_type": row.get("event_type"),
            "outcome": row.get("outcome"),
            "schema_valid": not errors,
            "schema_error_validators": errors,
        }
        for key, value in facts.items():
            if expected.get(key) != value:
                _v4_contract(
                    f"v3 quarantine fact drift line {index}: {key}",
                    "v4_legacy_quarantine_invalid",
                )
        if (
            expected.get("authority_effect") != "none"
            or expected.get("replay_eligible") is not False
            or expected.get("predecessor_eligible") is not False
        ):
            _v4_contract(
                "v3 quarantine authority drift", "v4_legacy_quarantine_invalid"
            )
        observed.append(facts)
        prior_canonical = _sha(body)
    advisory = quarantine["line_2_serializer_advisory"]
    if (
        _sha(raw_lines[0]) != advisory["observed_raw_line_plus_LF_sha256"]
        or _sha(raw_lines[0][:-1])
        != advisory["expected_prior_canonical_event_excluding_LF_sha256"]
        or advisory["normative_link_valid"] is not False
    ):
        _v4_contract(
            "line-2 LF serializer advisory drift", "v4_legacy_quarantine_invalid"
        )
    if (valid, invalid, payload_valid) != (1, 7, 8):
        _v4_contract(
            "v3 strict 1/8 quarantine invariant failed", "v4_legacy_quarantine_invalid"
        )
    return {
        "source": cap.ref(),
        "row_count": 8,
        "strict_valid_count": 1,
        "strict_invalid_count": 7,
        "payload_digest_valid_count": 8,
        "all_rows_quarantined": True,
        "line2_normative_link_valid": False,
        "legacy_gate_high_watermark": 14,
    }


def _v4_check_predecessors(root: V4Root, context: Mapping[str, Any]) -> None:
    for name, expected in context["authoritative_predecessors"].items():
        modes = {int(expected["mode"], 8)}
        cap = root.read(expected["path"], modes=modes)
        assert cap is not None
        _v4_validate_ref(cap, expected, name)


def _v4_preflight(
    root: V4Root, context: Mapping[str, Any], paths: Mapping[str, str]
) -> dict[str, Any]:
    _v4_check_predecessors(root, context)
    facts = _v4_v3_preflight(root, context, paths["v3"])
    return {
        "legacy": facts,
        "schema_sha256": {
            "event": V4_EVENT_SCHEMA_SHA256,
            "migration_record": V4_MIGRATION_RECORD_SCHEMA_SHA256,
            "migration_audit": V4_MIGRATION_AUDIT_SCHEMA_SHA256,
        },
        "migration_order": [
            "migration_record",
            "MIGRATION_GENESIS",
            "independent_migration_audit",
        ],
        "next_gate_token_if_activated": "a000015",
        "enabled_attempt_kinds": ["GATE_REPAIR_HB3"],
        "disabled_attempt_kinds": ["FINAL_FAN_IN", "POL_EXTERNAL"],
        "G2_provider_satisfied": False,
        "authorization_effect": "none",
    }


def _v4_expected_record(context: Mapping[str, Any], created_at: str) -> dict[str, Any]:
    return {
        "schema_name": "lane_b_attempt_registry_v3_to_v4_migration.v1",
        "schema_version": 1,
        "record_type": "immutable_non_authorizing_registry_migration_record",
        "status": "MIGRATION_RECORD_COMMITTED_V4_INACTIVE_PENDING_INDEPENDENT_AUDIT",
        "migration_id": V4_MIGRATION_ID,
        "created_at": created_at,
        "immutable": True,
        "identity": {
            "session_id": SESSION_ID,
            "spec_id": SPEC_ID,
            "cycle_id": CYCLE_ID,
            "lane_id": LANE_ID,
            "pipeline_id": PIPELINE_ID,
        },
        "source_v3": dict(context["legacy_v3_quarantine_contract"]["source"]),
        "blocked_audit": dict(context["authoritative_predecessors"]["blocked_audit"]),
        "blocked_receipt": dict(
            context["authoritative_predecessors"]["blocked_receipt"]
        ),
        "g2_readiness": dict(context["authoritative_predecessors"]["g2_readiness"]),
        "legacy_rows": copy.deepcopy(context["legacy_v3_quarantine_contract"]["rows"]),
        "legacy_row_count": 8,
        "strict_valid_count": 1,
        "strict_invalid_count": 7,
        "legacy_gate_high_watermark": 14,
        "enabled_attempt_kinds": ["GATE_REPAIR_HB3"],
        "disabled_attempt_kinds": ["FINAL_FAN_IN", "POL_EXTERNAL"],
        "event_schema_sha256": V4_EVENT_SCHEMA_SHA256,
        "next_gate_token_if_activated": "a000015",
        "authorization_effect": "none",
        "registry_append_count": 0,
        "lifecycle_event_count": 0,
    }


def _v4_record(
    root: V4Root, context: Mapping[str, Any], path: str, *, optional: bool = False
) -> tuple[V4File, dict[str, Any]] | None:
    cap = root.read(path, modes={0o444}, optional=optional)
    if cap is None:
        return None
    value = _v4_load_json(cap.data, line_framed=True)
    if not isinstance(value, dict):
        _v4_contract("migration record must be object", "v4_schema_invalid")
    _v4_schema(value, context["closed_schemas"]["migration_record_schema"])
    _timestamp(value["created_at"], "v4_schema_invalid")
    if value != _v4_expected_record(context, value["created_at"]):
        _v4_tamper("migration record semantic drift")
    return cap, value


def _v4_with_integrity(event: Mapping[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(dict(event))
    integrity = value.get("integrity")
    if not isinstance(integrity, dict):
        integrity = {"canonicalization": V4_INTEGRITY_LANGUAGE}
        value["integrity"] = integrity
    integrity["canonicalization"] = V4_INTEGRITY_LANGUAGE
    integrity.pop("event_payload_sha256", None)
    integrity["event_payload_sha256"] = canonical_sha(value)
    return value


def _v4_derive_paths(
    context: Mapping[str, Any], kind: str, attempt_id: str
) -> dict[str, str]:
    match = ATTEMPT_RE.fullmatch(attempt_id)
    if match is None or int(match.group(1)) < 1:
        _v4_contract("invalid v4 attempt token", "v4_identity_denied")
    templates = context["allocator_contract"]["derived_paths"]
    if (
        kind not in context["allocator_contract"]["allowed_kinds"]
        or len(templates) != 14
    ):
        _v4_contract("allocator contract drift")
    result: dict[str, str] = {}
    for key, template in templates.items():
        if not isinstance(template, str) or template.count("{attempt_id}") != 1:
            _v4_contract("ambiguous derived path template")
        value = template.replace("{attempt_id}", attempt_id)
        _v4_parts(value)
        result[key] = value
    if len(set(result.values())) != 14:
        _v4_contract("derived path collision")
    return result


def _v4_genesis(
    context: Mapping[str, Any], record: V4File, record_value: Mapping[str, Any]
) -> dict[str, Any]:
    record_sha = record.sha256
    tx = _sha(("v4-genesis-transaction:" + record_sha).encode())[:32]
    nonce = _sha(("v4-genesis-nonce:" + record_sha).encode())[:32]
    event = {
        "schema_version": 4,
        "record_type": "lane_b_attempt_identity_registry_v4_event",
        "event_sequence": 1,
        "previous_event_sha256": None,
        "event_type": "MIGRATION_GENESIS",
        "attempt_kind": None,
        "attempt_id": None,
        "attempt_sequence": None,
        "attempt_uid": None,
        "transaction_id": tx,
        "nonce": nonce,
        "identity": copy.deepcopy(record_value["identity"]),
        "owner_role": "same_spec_parent",
        "derived_paths": {},
        "migration_identity": {
            "migration_id": V4_MIGRATION_ID,
            "migration_record": record.ref(),
            "source_v3_sha256": context["legacy_v3_quarantine_contract"]["source"][
                "sha256"
            ],
            "source_v3_row_count": 8,
            "strict_valid_count": 1,
            "strict_invalid_count": 7,
            "legacy_gate_high_watermark": 14,
        },
        "dev_dispatch_identity": None,
        "qa_dispatch_identity": None,
        "producer_identity": None,
        "qa_result_identity": None,
        "readiness_identity": None,
        "receipt_identity": None,
        "marker_identity": None,
        "recovery_identity": None,
        "terminal_failure_identity": None,
        "binding_identity": None,
        "precondition_manifest_sha256": canonical_sha(
            {
                "migration_record": record.ref(),
                "source_v3": context["legacy_v3_quarantine_contract"]["source"],
                "predecessors": context["authoritative_predecessors"],
            }
        ),
        "event_at": record_value["created_at"],
        "outcome": "migration_initialized_non_authorizing",
        "authorization_effect": "none",
        "integrity": {"canonicalization": V4_INTEGRITY_LANGUAGE},
    }
    return _v4_with_integrity(event)


@dataclass
class V4Replay:
    rows: list[dict[str, Any]]
    lines: list[bytes]
    states: dict[tuple[str, str], str]
    allocations: dict[str, list[str]]
    dispatch_ids: set[str]

    @property
    def head_sha256(self) -> str | None:
        return _sha(self.lines[-1][:-1]) if self.lines else None


def _v4_registry_rows(data: bytes) -> tuple[list[dict[str, Any]], list[bytes]]:
    if (
        not data
        or not data.endswith(b"\n")
        or b"\r" in data
        or data.startswith(b"\xef\xbb\xbf")
    ):
        _v4_tamper("v4 registry framing invalid")
    lines = data.splitlines(keepends=True)
    if any(line == b"\n" or not line.endswith(b"\n") for line in lines):
        _v4_tamper("v4 registry blank/missing LF")
    rows: list[dict[str, Any]] = []
    for line in lines:
        value = _v4_load_json(line, line_framed=True)
        if not isinstance(value, dict):
            _v4_contract("v4 event must be object", "v4_schema_invalid")
        rows.append(value)
    return rows, lines


def _v4_replay(
    context: Mapping[str, Any], registry: V4File, record: V4File
) -> V4Replay:
    rows, lines = _v4_registry_rows(registry.data)
    schema = context["closed_schemas"]["event_schema"]
    states: dict[tuple[str, str], str] = {}
    allocations: dict[str, list[str]] = {}
    txs: set[str] = set()
    nonces: set[str] = set()
    dispatch_ids: set[str] = set()
    prior: str | None = None
    allocation_events: dict[tuple[str, str], dict[str, Any]] = {}
    dev_identities: dict[tuple[str, str], dict[str, Any]] = {}
    qa_dispatch_ids: set[str] = set()
    for number, (row, line) in enumerate(zip(rows, lines), 1):
        _v4_schema(row, schema)
        validate_integrity(row, code="v4_schema_invalid")
        if row["event_sequence"] != number or row["previous_event_sha256"] != prior:
            _v4_tamper(
                "v4 event sequence/prior canonical hash fork or gap", "v4_replay_denied"
            )
        if row["transaction_id"] in txs or row["nonce"] in nonces:
            _v4_tamper("transaction/nonce replay", "v4_replay_denied")
        txs.add(row["transaction_id"])
        nonces.add(row["nonce"])
        if number == 1:
            if row["event_type"] != "MIGRATION_GENESIS" or row != _v4_genesis(
                context, record, _v4_load_json(record.data, line_framed=True)
            ):
                _v4_tamper("genesis event drift", "v4_replay_denied")
            prior = _sha(line[:-1])
            continue
        kind, attempt_id = row["attempt_kind"], row["attempt_id"]
        if kind != "GATE_REPAIR_HB3" or not isinstance(attempt_id, str):
            _v4_contract(
                "disabled/invalid attempt kind in v4 registry", "v4_state_denied"
            )
        seq = int(attempt_id[1:]) if ATTEMPT_RE.fullmatch(attempt_id) else -1
        if (
            row["attempt_sequence"] != seq
            or row["attempt_uid"]
            != f"{SESSION_ID}/{SPEC_ID}/cycle-1/v4/{kind}/{attempt_id}"
        ):
            _v4_contract("attempt composite identity mismatch", "v4_identity_denied")
        derived = _v4_derive_paths(context, kind, attempt_id)
        if row["derived_paths"] != derived:
            _v4_tamper("registry derived path mismatch", "v4_replay_denied")
        key = (kind, attempt_id)
        current = states.get(key)
        event_type = row["event_type"]
        if event_type == "ALLOCATED":
            ids = allocations.setdefault(kind, [])
            expected = 15 if not ids else int(ids[-1][1:]) + 1
            if seq != expected or current is not None:
                _v4_tamper("per-kind allocation gap/replay", "v4_replay_denied")
            if ids and states[(kind, ids[-1])] != "TERMINAL_NO_AUTHORITY":
                _v4_contract(
                    "successor before prior terminal reconciliation", "v4_state_denied"
                )
            ids.append(attempt_id)
            states[key] = "ALLOCATED"
            allocation_events[key] = row
        else:
            allocated = allocation_events.get(key)
            if allocated is None:
                _v4_tamper("event without allocation predecessor", "v4_replay_denied")
            for field in (
                "attempt_kind",
                "attempt_id",
                "attempt_sequence",
                "attempt_uid",
                "derived_paths",
            ):
                if row[field] != allocated[field]:
                    _v4_tamper("attempt identity drift", "v4_replay_denied")
            if event_type == "STARTED" and current == "ALLOCATED":
                dispatch = row["dev_dispatch_identity"]
                if (
                    dispatch["role"] != "lane_b_dev"
                    or dispatch["ticket_sha256"] != V4_TICKET_SHA256
                    or dispatch["context_sha256"] != V4_CONTEXT_SHA256
                    or dispatch["dispatch_id"] in dispatch_ids
                ):
                    _v4_contract(
                        "Dev dispatch identity missing/reused/drifted",
                        "v4_identity_denied",
                    )
                dispatch_ids.add(dispatch["dispatch_id"])
                dev_identities[key] = dispatch
                states[key] = "ACTIVE"
            elif event_type == "RECOVERY_REQUIRED" and current == "ACTIVE":
                if row["dev_dispatch_identity"] != dev_identities.get(key):
                    _v4_contract("recovery Dev composite drift", "v4_identity_denied")
                states[key] = "RECOVERING"
            elif event_type == "COMMIT_READY" and current in {"ACTIVE", "RECOVERING"}:
                qa = row["qa_dispatch_identity"]
                dev = dev_identities.get(key)
                if (
                    row["dev_dispatch_identity"] != dev
                    or qa["role"] != "independent_lane_b_qa"
                    or qa["agent_id"] == dev["agent_id"]
                    or qa["dispatch_id"] in dispatch_ids
                    or qa["dispatch_id"] in qa_dispatch_ids
                    or qa["task_id"] != dev["task_id"]
                    or qa["ticket_sha256"] != dev["ticket_sha256"]
                    or qa["context_sha256"] != dev["context_sha256"]
                ):
                    _v4_contract(
                        "COMMIT_READY composite/QA drift", "v4_identity_denied"
                    )
                qa_dispatch_ids.add(qa["dispatch_id"])
                states[key] = "COMMIT_READY"
            elif event_type == "TERMINAL_EVIDENCE_READY" and current == "COMMIT_READY":
                if row["dev_dispatch_identity"] != dev_identities.get(key):
                    _v4_contract("terminal Dev composite drift", "v4_identity_denied")
                states[key] = "TERMINAL_EVIDENCE_READY"
            elif event_type == "TERMINAL_NO_AUTHORITY" and current in {
                "ALLOCATED",
                "ACTIVE",
                "RECOVERING",
                "COMMIT_READY",
            }:
                allowed = {
                    "ALLOCATED": {
                        "schema_or_chain_reject",
                        "path_or_tamper_reject",
                        "publication_fail",
                    },
                    "ACTIVE": {
                        "dev_fail",
                        "qa_fail",
                        "publication_fail",
                        "schema_or_chain_reject",
                        "path_or_tamper_reject",
                    },
                    "RECOVERING": {
                        "crash_reconciled_abort",
                        "publication_fail",
                        "path_or_tamper_reject",
                    },
                    "COMMIT_READY": {
                        "publication_fail",
                        "path_or_tamper_reject",
                        "g2_fail",
                    },
                }[current]
                if row["outcome"] not in allowed:
                    _v4_contract(
                        "terminal outcome not legal from predecessor", "v4_state_denied"
                    )
                states[key] = "TERMINAL_NO_AUTHORITY"
            else:
                _v4_contract("unlisted or absorbing v4 transition", "v4_state_denied")
        prior = _sha(line[:-1])
    return V4Replay(rows, lines, states, allocations, dispatch_ids)


def _v4_audit(
    root: V4Root,
    context: Mapping[str, Any],
    path: str,
    record: V4File,
    registry: V4File,
    *,
    optional: bool = False,
) -> tuple[V4File, dict[str, Any]] | None:
    cap = root.read(path, modes={0o444}, optional=optional)
    if cap is None:
        return None
    value = _v4_load_json(cap.data, line_framed=True)
    if not isinstance(value, dict):
        _v4_contract("migration audit must be object", "v4_schema_invalid")
    _v4_schema(value, context["closed_schemas"]["migration_audit_schema"])
    first_line = registry.data.splitlines(keepends=True)[0]
    if (
        value["status"] != "PASS_CONTROL_ACTIVATION_ONLY"
        or value["effect"] != "ENABLE_V4_CONTROL_PLANE_ONLY"
        or value["all_checks_pass"] is not True
        or set(value["checks"].values()) != {True}
        or value["migration_record"] != record.ref()
        or value["v4_registry_path"] != registry.path
        or value["genesis_prefix_bytes"] != len(first_line)
        or value["genesis_prefix_sha256"] != _sha(first_line)
        or value["G2_provider_satisfied"] is not False
        or value["authorization_effect"] != "none"
    ):
        _v4_tamper("migration audit semantic/identity drift")
    return cap, value


def v4_expected_migration_audit(
    context: Mapping[str, Any],
    record: V4File,
    registry: V4File,
    agent_id: str,
    created_at: str,
) -> dict[str, Any]:
    """Build the value an independent QA may publish; this function never writes it."""
    line = registry.data.splitlines(keepends=True)[0]
    checks = {
        key: True
        for key in context["closed_schemas"]["migration_audit_schema"]["properties"][
            "checks"
        ]["required"]
    }
    return {
        "schema_name": "lane_b_attempt_registry_v4_migration_audit.v1",
        "schema_version": 1,
        "record_type": "immutable_independent_registry_migration_audit",
        "status": "PASS_CONTROL_ACTIVATION_ONLY",
        "created_at": created_at,
        "immutable": True,
        "auditor": {
            "agent_id": agent_id,
            "role": "independent_registry_migration_qa",
            "independent_from_author_and_dev": True,
        },
        "migration_record": record.ref(),
        "v4_registry_path": registry.path,
        "genesis_prefix_bytes": len(line),
        "genesis_prefix_sha256": _sha(line),
        "checks": checks,
        "all_checks_pass": True,
        "effect": "ENABLE_V4_CONTROL_PLANE_ONLY",
        "G2_provider_satisfied": False,
        "authorization_effect": "none",
    }


def _v4_verify_transaction_exact(
    root: V4Root,
    context: Mapping[str, Any],
    record: V4File,
    registry: V4File,
    event_index: int,
    event: Mapping[str, Any],
    line: bytes,
) -> None:
    tx_paths = _v4_tx_paths(context, event["transaction_id"])
    captures = {
        key: root.read(path, modes={0o444}, optional=True)
        for key, path in tx_paths.items()
        if key != "terminal_failure"
    }
    if any(cap is None for cap in captures.values()):
        _v4_recovery("registry event has incomplete immutable transaction evidence")
    intent_cap = captures["step_01_intent"]
    appended_cap = captures["step_02_appended"]
    commit_cap = captures["step_03_commit"]
    assert (
        intent_cap is not None and appended_cap is not None and commit_cap is not None
    )
    before_data = registry.data[
        : sum(
            len(item) for item in registry.data.splitlines(keepends=True)[:event_index]
        )
    ]
    before = None
    if event_index:
        before = V4File(
            registry.path,
            before_data,
            registry.mode,
            registry.nlink,
            registry.device,
            registry.inode,
        )
    expected_intent = _v4_intent_value(registry.path, before, event)
    actual_intent = _v4_load_json(intent_cap.data, line_framed=True)
    if actual_intent != expected_intent:
        _v4_tamper(
            "immutable transaction intent/preimage drift", "v4_transaction_tamper"
        )
    after_data = before_data + line
    after = V4File(
        registry.path,
        after_data,
        registry.mode,
        registry.nlink,
        registry.device,
        registry.inode,
    )
    appended, commit = _v4_step_values(intent_cap, actual_intent, after)
    appended["registry_postimage"]["path"] = registry.path
    if appended_cap.data != _v4_json_line(appended):
        _v4_tamper("immutable append-result drift", "v4_transaction_tamper")
    commit["appended"] = appended_cap.ref()
    if commit_cap.data != _v4_json_line(commit):
        _v4_tamper("immutable append-commit drift", "v4_transaction_tamper")


def _v4_verify_all_transactions(
    root: V4Root,
    context: Mapping[str, Any],
    record: V4File,
    registry: V4File,
    replay: V4Replay,
) -> None:
    for index, (event, line) in enumerate(zip(replay.rows, replay.lines)):
        _v4_verify_transaction_exact(
            root, context, record, registry, index, event, line
        )


def _v4_activation(
    root: V4Root, context: Mapping[str, Any], paths: Mapping[str, str]
) -> tuple[V4File, dict[str, Any], V4File, V4Replay, V4File]:
    record_item = _v4_record(root, context, paths["record"])
    if record_item is None:
        _v4_contract("migration record missing", "v4_state_denied")
    record, record_value = record_item
    registry = root.read(paths["registry"], modes={0o600})
    assert registry is not None
    replay = _v4_replay(context, registry, record)
    _v4_verify_all_transactions(root, context, record, registry, replay)
    audit_item = _v4_audit(
        root, context, paths["audit"], record, registry, optional=True
    )
    if audit_item is None:
        _v4_contract("independent migration audit missing", "v4_state_denied")
    audit, _audit_value = audit_item
    return record, record_value, registry, replay, audit


def _v4_tx_paths(context: Mapping[str, Any], transaction_id: str) -> dict[str, str]:
    if V4_TX_RE.fullmatch(transaction_id) is None:
        _v4_contract("invalid transaction id", "v4_identity_denied")
    result: dict[str, str] = {}
    for key, template in context["v4_artifacts"]["transaction_templates"].items():
        if template.count("{transaction_id}") != 1:
            _v4_contract("transaction template drift")
        value = template.replace("{transaction_id}", transaction_id)
        _v4_parts(value)
        result[key] = value
    if len(set(result.values())) != 4:
        _v4_contract("transaction path collision")
    return result


def _v4_intent_value(
    registry_path: str,
    before: V4File | None,
    event: Mapping[str, Any],
) -> dict[str, Any]:
    line = _v4_json_line(event)
    return {
        "schema_name": "lane_b_registry_v4_append_intent.v1",
        "schema_version": 1,
        "record_type": "immutable_registry_append_intent",
        "status": "INTENT_DURABLE",
        "created_at": event["event_at"],
        "immutable": True,
        "transaction_id": event["transaction_id"],
        "nonce": event["nonce"],
        "registry_path": registry_path,
        "registry_preimage": {
            "exists": before is not None,
            "bytes": len(before.data) if before else 0,
            "sha256": before.sha256 if before else _sha(b""),
            "mode": before.mode if before else None,
            "nlink": before.nlink if before else None,
            "device": before.device if before else None,
            "inode": before.inode if before else None,
            "head_event_sha256": (
                _sha(before.data.splitlines(keepends=True)[-1][:-1])
                if before and before.data
                else None
            ),
        },
        "intended_event_hex": line.hex(),
        "intended_event_bytes": len(line),
        "intended_event_sha256_excluding_LF": _sha(line[:-1]),
        "append_bytes_sha256": _sha(line),
        "authorization_effect": "none",
    }


def _v4_intent(
    root: V4Root, context: Mapping[str, Any], transaction_id: str
) -> tuple[V4File, dict[str, Any]]:
    path = _v4_tx_paths(context, transaction_id)["step_01_intent"]
    cap = root.read(path, modes={0o444})
    assert cap is not None
    value = _v4_load_json(cap.data, line_framed=True)
    keys = {
        "schema_name",
        "schema_version",
        "record_type",
        "status",
        "created_at",
        "immutable",
        "transaction_id",
        "nonce",
        "registry_path",
        "registry_preimage",
        "intended_event_hex",
        "intended_event_bytes",
        "intended_event_sha256_excluding_LF",
        "append_bytes_sha256",
        "authorization_effect",
    }
    pre_keys = {
        "exists",
        "bytes",
        "sha256",
        "mode",
        "nlink",
        "device",
        "inode",
        "head_event_sha256",
    }
    if (
        not isinstance(value, dict)
        or set(value) != keys
        or not isinstance(value.get("registry_preimage"), dict)
        or set(value["registry_preimage"]) != pre_keys
        or value.get("schema_name") != "lane_b_registry_v4_append_intent.v1"
        or value.get("schema_version") != 1
        or value.get("record_type") != "immutable_registry_append_intent"
        or value.get("status") != "INTENT_DURABLE"
        or value.get("immutable") is not True
        or value.get("transaction_id") != transaction_id
        or V4_TX_RE.fullmatch(value.get("nonce", "")) is None
        or value.get("authorization_effect") != "none"
    ):
        _v4_tamper("append intent closed identity invalid", "v4_transaction_tamper")
    try:
        line = bytes.fromhex(value["intended_event_hex"])
    except (TypeError, ValueError):
        _v4_tamper("append intent event encoding invalid", "v4_transaction_tamper")
    if (
        len(line) != value["intended_event_bytes"]
        or not line.endswith(b"\n")
        or _sha(line[:-1]) != value["intended_event_sha256_excluding_LF"]
        or _sha(line) != value["append_bytes_sha256"]
    ):
        _v4_tamper("append intent event digest invalid", "v4_transaction_tamper")
    event = _v4_load_json(line, line_framed=True)
    if (
        not isinstance(event, dict)
        or event.get("transaction_id") != transaction_id
        or event.get("nonce") != value["nonce"]
    ):
        _v4_tamper("append intent/event identity mismatch", "v4_transaction_tamper")
    return cap, value


def _v4_step_values(
    intent_cap: V4File, intent: Mapping[str, Any], after: V4File
) -> tuple[dict[str, Any], dict[str, Any]]:
    event_line = bytes.fromhex(intent["intended_event_hex"])
    appended = {
        "schema_name": "lane_b_registry_v4_append_result.v1",
        "schema_version": 1,
        "record_type": "immutable_registry_append_result",
        "status": "APPEND_DURABLE_REPLAY_VALID",
        "created_at": intent["created_at"],
        "immutable": True,
        "transaction_id": intent["transaction_id"],
        "nonce": intent["nonce"],
        "intent": intent_cap.ref(),
        "registry_postimage": {
            "path": after.path,
            "bytes": len(after.data),
            "sha256": after.sha256,
            "mode": after.mode,
            "nlink": after.nlink,
            "device": after.device,
            "inode": after.inode,
            "head_event_sha256": _sha(event_line[:-1]),
        },
        "authorization_effect": "none",
    }
    appended_bytes = _v4_json_line(appended)
    appended_ref = {
        "path": "",
        "bytes": len(appended_bytes),
        "sha256": _sha(appended_bytes),
        "mode": "0444",
        "nlink": 1,
        "state": "file",
        "symlink": False,
    }
    commit = {
        "schema_name": "lane_b_registry_v4_append_commit.v1",
        "schema_version": 1,
        "record_type": "immutable_registry_append_commit",
        "status": "COMMITTED_NON_AUTHORIZING",
        "created_at": intent["created_at"],
        "immutable": True,
        "transaction_id": intent["transaction_id"],
        "nonce": intent["nonce"],
        "intent": intent_cap.ref(),
        "appended": appended_ref,
        "registry_postimage_sha256": after.sha256,
        "event_sha256_excluding_LF": _sha(event_line[:-1]),
        "authorization_effect": "none",
        "G2_provider_satisfied": False,
    }
    return appended, commit


def _v4_write_registry_suffix(
    root: V4Root,
    context: Mapping[str, Any],
    record: V4File,
    path: str,
    current: V4File | None,
    suffix: bytes,
    *,
    sync: bool = True,
    replay_prefix_bytes: int | None = None,
) -> None:
    if not suffix:
        return
    with root.parent(path) as (parent_fd, name):
        if current is None:
            try:
                fd = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=parent_fd,
                )
            except OSError:
                _v4_tamper("registry create collision/unsafe", "v4_collision_denied")
            expected_size = 0
        else:
            try:
                fd = os.open(
                    name,
                    os.O_RDWR | os.O_APPEND | os.O_CLOEXEC | os.O_NOFOLLOW,
                    dir_fd=parent_fd,
                )
            except OSError:
                _v4_tamper("registry append open unsafe", "v4_path_denied")
            before = os.fstat(fd)
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                stat.S_IMODE(before.st_mode),
                before.st_nlink,
            ) != (current.device, current.inode, len(current.data), 0o600, 1):
                os.close(fd)
                _v4_tamper("registry inode/size/mode CAS drift", "v4_cas_denied")
            # This is the linearization read: full bytes and the canonical head
            # are replayed on the exact O_RDWR|O_APPEND descriptor that writes.
            chunks: list[bytes] = []
            offset = 0
            while offset < before.st_size:
                try:
                    chunk = os.pread(
                        fd, min(1024 * 1024, before.st_size - offset), offset
                    )
                except InterruptedError:
                    continue
                if not chunk:
                    os.close(fd)
                    _v4_tamper("registry final descriptor short read", "v4_cas_denied")
                chunks.append(chunk)
                offset += len(chunk)
            descriptor_data = b"".join(chunks)
            after_read = os.fstat(fd)
            stable = lambda st: (
                st.st_dev,
                st.st_ino,
                st.st_size,
                stat.S_IMODE(st.st_mode),
                st.st_nlink,
                st.st_mtime_ns,
                st.st_ctime_ns,
            )
            current_path = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if (
                stable(before) != stable(after_read)
                or (current_path.st_dev, current_path.st_ino)
                != (before.st_dev, before.st_ino)
                or descriptor_data != current.data
                or _sha(descriptor_data) != current.sha256
                or os.pread(fd, 1, before.st_size) != b""
            ):
                os.close(fd)
                _v4_tamper(
                    "registry final descriptor byte/hash/stat CAS drift",
                    "v4_cas_denied",
                )
            prefix_size = (
                len(descriptor_data)
                if replay_prefix_bytes is None
                else replay_prefix_bytes
            )
            if not 0 <= prefix_size <= len(descriptor_data):
                os.close(fd)
                _v4_tamper("registry replay prefix invalid", "v4_cas_denied")
            if prefix_size:
                prefix = descriptor_data[:prefix_size]
                prefix_file = V4File(
                    path,
                    prefix,
                    current.mode,
                    current.nlink,
                    current.device,
                    current.inode,
                    before.st_mtime_ns,
                    before.st_ctime_ns,
                )
                replay = _v4_replay(context, prefix_file, record)
                expected_head = _sha(prefix.splitlines(keepends=True)[-1][:-1])
                if replay.head_sha256 != expected_head:
                    os.close(fd)
                    _v4_tamper(
                        "registry final descriptor canonical head drift",
                        "v4_cas_denied",
                    )
            expected_size = len(current.data)
        try:
            os.fchmod(fd, 0o600)
            view = memoryview(suffix)
            while view:
                try:
                    count = os.write(fd, view)
                except InterruptedError:
                    continue
                if count <= 0:
                    _v4_recovery("registry partial append")
                view = view[count:]
            if sync:
                os.fsync(fd)
        finally:
            os.close(fd)
        if sync:
            os.fsync(parent_fd)
        st = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            st.st_size != expected_size + len(suffix)
            or st.st_nlink != 1
            or stat.S_IMODE(st.st_mode) != 0o600
        ):
            _v4_tamper("registry post-append identity mismatch", "v4_cas_denied")


def _v4_finish_transaction(
    root: V4Root,
    context: Mapping[str, Any],
    record: V4File,
    transaction_id: str,
    *,
    crash_after: str | None = None,
) -> dict[str, Any]:
    tx_paths = _v4_tx_paths(context, transaction_id)
    intent_cap, intent = _v4_intent(root, context, transaction_id)
    line = bytes.fromhex(intent["intended_event_hex"])
    pre = intent["registry_preimage"]
    registry_path = intent["registry_path"]
    current = root.read(registry_path, modes={0o600}, optional=True)
    if current is None:
        if pre["exists"]:
            _v4_tamper("registry disappeared after intent", "v4_cas_denied")
        current_bytes = b""
        prefix = b""
    else:
        current_bytes = current.data
        pre_len = pre["bytes"]
        if (
            len(current_bytes) < pre_len
            or _sha(current_bytes[:pre_len]) != pre["sha256"]
        ):
            _v4_tamper("registry diverges from intent preimage", "v4_cas_denied")
        if pre["exists"] and (
            current.device,
            current.inode,
            current.mode,
            current.nlink,
        ) != (pre["device"], pre["inode"], pre["mode"], pre["nlink"]):
            _v4_tamper("registry replaced after intent", "v4_cas_denied")
        prefix = current_bytes[pre_len:]
    if len(prefix) > len(line) or not line.startswith(prefix):
        _v4_tamper("divergent partial append bytes", "v4_cas_denied")
    if prefix != line:
        _v4_write_registry_suffix(
            root,
            context,
            record,
            registry_path,
            current,
            line[len(prefix) :],
            sync=crash_after != "fsync",
            replay_prefix_bytes=pre["bytes"],
        )
        if crash_after == "fsync":
            _v4_recovery("injected file/directory fsync failure")
    after = root.read(registry_path, modes={0o600})
    assert after is not None
    expected_post = pre["bytes"] + len(line)
    if (
        len(after.data) != expected_post
        or _sha(after.data[: pre["bytes"]]) != pre["sha256"]
        or after.data[pre["bytes"] :] != line
    ):
        _v4_tamper("registry postimage not exact intended prefix", "v4_cas_denied")
    replay = _v4_replay(context, after, record)
    if replay.head_sha256 != _sha(line[:-1]):
        _v4_tamper("reopen replay head mismatch", "v4_replay_denied")
    if crash_after == "append":
        _v4_recovery("injected crash after durable append before step-02")
    appended, commit = _v4_step_values(intent_cap, intent, after)
    appended["registry_postimage"]["path"] = registry_path
    appended_bytes = _v4_json_line(appended)
    existing_appended = root.read(
        tx_paths["step_02_appended"], modes={0o444}, optional=True
    )
    premature_commit = root.read(
        tx_paths["step_03_commit"], modes={0o444}, optional=True
    )
    if premature_commit is not None and existing_appended is None:
        _v4_tamper(
            "commit step exists without append-result predecessor",
            "v4_transaction_tamper",
        )
    if existing_appended is None:
        appended_cap = root.create(tx_paths["step_02_appended"], appended_bytes, 0o444)
    else:
        if existing_appended.data != appended_bytes:
            _v4_tamper("append-result collision/replacement", "v4_transaction_tamper")
        appended_cap = existing_appended
    if crash_after == "step2":
        _v4_recovery("injected crash after step-02 before immutable commit")
    commit["appended"] = appended_cap.ref()
    commit_bytes = _v4_json_line(commit)
    existing_commit = premature_commit
    if existing_commit is None:
        commit_cap = root.create(tx_paths["step_03_commit"], commit_bytes, 0o444)
        idempotent = False
    else:
        if existing_commit.data != commit_bytes:
            _v4_tamper("append-commit collision/replacement", "v4_transaction_tamper")
        commit_cap = existing_commit
        idempotent = True
    return {
        "transaction_id": transaction_id,
        "intent": intent_cap.ref(),
        "appended": appended_cap.ref(),
        "commit": commit_cap.ref(),
        "registry": after.ref(),
        "event_sha256_excluding_LF": _sha(line[:-1]),
        "idempotent": idempotent,
    }


def _v4_append_event(
    root: V4Root,
    context: Mapping[str, Any],
    record: V4File,
    registry_path: str,
    event: Mapping[str, Any],
    *,
    allow_absent: bool = False,
    crash_after: str | None = None,
) -> dict[str, Any]:
    schema = context["closed_schemas"]["event_schema"]
    _v4_schema(event, schema)
    validate_integrity(event, code="v4_schema_invalid")
    line = _v4_json_line(event)
    tx_paths = _v4_tx_paths(context, event["transaction_id"])
    before = root.read(registry_path, modes={0o600}, optional=True)
    if before is None and not allow_absent:
        _v4_contract("active v4 registry missing", "v4_state_denied")
    intent_expected = _v4_intent_value(registry_path, before, event)
    intent_existing = root.read(
        tx_paths["step_01_intent"], modes={0o444}, optional=True
    )
    if intent_existing is not None:
        existing_value = _v4_load_json(intent_existing.data, line_framed=True)
        if existing_value != intent_expected:
            # Genesis reconstruction after the complete line uses the immutable
            # all-absent preimage, not the observed postimage.
            if not (allow_absent and event["event_type"] == "MIGRATION_GENESIS"):
                _v4_tamper("transaction intent collision", "v4_transaction_tamper")
        return _v4_finish_transaction(
            root, context, record, event["transaction_id"], crash_after=crash_after
        )
    if before is not None and before.data.endswith(line):
        if not (
            allow_absent
            and event["event_type"] == "MIGRATION_GENESIS"
            and before.data == line
        ):
            _v4_tamper("registry event lacks immutable intent", "v4_transaction_tamper")
        intent_expected = _v4_intent_value(registry_path, None, event)
    root.create(tx_paths["step_01_intent"], _v4_json_line(intent_expected), 0o444)
    if crash_after == "intent":
        _v4_recovery("injected crash after durable intent")
    if crash_after == "partial":
        current = root.read(registry_path, modes={0o600}, optional=True)
        amount = max(1, len(line) // 2)
        _v4_write_registry_suffix(
            root, context, record, registry_path, current, line[:amount]
        )
        _v4_recovery("injected exact partial append")
    return _v4_finish_transaction(
        root, context, record, event["transaction_id"], crash_after=crash_after
    )


def _v4_event_precondition(registry: V4File, event: Mapping[str, Any]) -> str:
    return canonical_sha(
        {
            "registry": {
                "bytes": len(registry.data),
                "sha256": registry.sha256,
                "head": _sha(registry.data.splitlines(keepends=True)[-1][:-1]),
            },
            "event_type": event["event_type"],
            "attempt_uid": event["attempt_uid"],
            "derived_paths": event["derived_paths"],
            "evidence": {
                key: event.get(key)
                for key in (
                    "dev_dispatch_identity",
                    "qa_dispatch_identity",
                    "producer_identity",
                    "qa_result_identity",
                    "readiness_identity",
                    "receipt_identity",
                    "marker_identity",
                    "recovery_identity",
                    "terminal_failure_identity",
                    "binding_identity",
                )
            },
        }
    )


def v4_transition_precondition(registry: V4File, event: Mapping[str, Any]) -> str:
    """Public deterministic helper for parent-created transition requests."""
    return _v4_event_precondition(registry, event)


def _v4_artifact(
    root: V4Root, ref: Mapping[str, Any], expected_path: str, label: str
) -> tuple[V4File, dict[str, Any]]:
    if not isinstance(ref, dict) or ref.get("path") != expected_path:
        _v4_contract(f"{label} path/composite mismatch", "v4_identity_denied")
    cap = root.read(expected_path, modes={0o444, 0o600, 0o644})
    assert cap is not None
    if cap.ref() != dict(ref):
        _v4_tamper(f"{label} bytes/metadata drift")
    value = _v4_load_json(cap.data, line_framed=True)
    if not isinstance(value, dict):
        _v4_contract(f"{label} must be object", "v4_identity_denied")
    return cap, value


def _v4_attempt_identity(event: Mapping[str, Any]) -> dict[str, Any]:
    identity = event["identity"]
    return {
        "session_id": identity["session_id"],
        "spec_id": identity["spec_id"],
        "cycle_id": identity["cycle_id"],
        "lane_id": identity["lane_id"],
        "pipeline_id": identity["pipeline_id"],
        "attempt_kind": event["attempt_kind"],
        "attempt_id": event["attempt_id"],
        "attempt_sequence": event["attempt_sequence"],
        "attempt_uid": event["attempt_uid"],
    }


def _v4_ref_map(value: Any, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        _v4_contract(f"{label} manifest missing", "v4_identity_denied")
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            _v4_contract(f"{label} manifest invalid", "v4_identity_denied")
        if item["path"] in result:
            _v4_contract(f"{label} manifest duplicate", "v4_identity_denied")
        result[item["path"]] = item
    return result


def _v4_live_binding(
    root: V4Root,
    context: Mapping[str, Any],
    producer: Mapping[str, Any],
    qa: Mapping[str, Any],
) -> dict[str, Any]:
    repair = context["provider_binding_repair"]
    policy = repair["provider_policy"]
    fixed = policy["fixed_provider_map"]
    mutable = policy["mutable_provider_paths"]
    consumers = repair["consumer_map"]
    if (
        canonical_sha(policy) != V4_PROVIDER_POLICY_SHA256
        or policy.get("schema_name") != "lane_b_registry_v4_live_provider_policy.v2"
        or policy.get("schema_version") != 2
        or policy.get("provider_path_count") != 16
        or len(fixed) != 14
        or mutable
        != [
            "hooks/tests/test_laneb_integration_gate.py",
            "scripts/laneb-integration-gate.py",
        ]
        or set(fixed).intersection(mutable)
        or policy.get("old_preimplementation_provider_map_sha256")
        != V4_OLD_PROVIDER_MAP_SHA256
        or policy.get("old_digest_accepted_for_repaired_lifecycle") is not False
        or len(consumers) != 3
        or canonical_sha(consumers) != V4_CONSUMER_MAP_SHA256
    ):
        _v4_contract("live provider policy invalid", "v4_identity_denied")

    provider_map: dict[str, str] = {}
    live_mutable: dict[str, V4File] = {}
    for path, expected_sha in fixed.items():
        cap = root.read(path, modes={0o444, 0o600, 0o644, 0o755})
        assert cap is not None
        provider_map[path] = cap.sha256
        if cap.sha256 != expected_sha:
            _v4_tamper("fixed provider byte drift", "v4_identity_denied")
    for path in mutable:
        expected_mode = 0o755 if path.startswith("scripts/") else 0o644
        cap = root.read(path, modes={expected_mode})
        assert cap is not None
        live_mutable[path] = cap
        provider_map[path] = cap.sha256
    if len(provider_map) != 16:
        _v4_contract("provider set incomplete", "v4_identity_denied")

    consumer_map: dict[str, str] = {}
    for path, expected_sha in consumers.items():
        cap = root.read(path, modes={0o444, 0o600, 0o644, 0o755})
        assert cap is not None
        consumer_map[path] = cap.sha256
        if cap.sha256 != expected_sha:
            _v4_tamper("consumer byte drift", "v4_identity_denied")
    if len(consumer_map) != 3:
        _v4_contract("consumer set incomplete", "v4_identity_denied")

    producer_files = _v4_ref_map(producer.get("implementation_files"), "producer")
    qa_files = _v4_ref_map(qa.get("observed_implementation_files"), "independent QA")
    if set(producer_files) != set(mutable) or set(qa_files) != set(mutable):
        _v4_contract("mutable provider manifests incomplete", "v4_identity_denied")
    for path, cap in live_mutable.items():
        if producer_files[path] != cap.ref() or qa_files[path] != cap.ref():
            _v4_tamper("mutable provider evidence/live-byte mismatch")

    provider_digest = canonical_sha(provider_map)
    consumer_digest = canonical_sha(consumer_map)
    if provider_digest == V4_OLD_PROVIDER_MAP_SHA256:
        _v4_contract(
            "old preimplementation provider digest rejected", "v4_identity_denied"
        )
    if consumer_digest != V4_CONSUMER_MAP_SHA256:
        _v4_tamper("consumer map digest drift", "v4_identity_denied")
    return {
        "provider_path_count": 16,
        "provider_map_sha256": provider_digest,
        "provider_policy_sha256": V4_PROVIDER_POLICY_SHA256,
        "fixed_provider_match": True,
        "mutable_provider_evidence_match": True,
        "consumer_path_count": 3,
        "consumer_map_sha256": consumer_digest,
        "consumer_map_verified": True,
    }


def _v4_validate_evidence(
    root: V4Root,
    context: Mapping[str, Any],
    event: Mapping[str, Any],
    replay: V4Replay,
) -> None:
    kind, attempt = event["attempt_kind"], event["attempt_id"]
    paths = _v4_derive_paths(context, kind, attempt)
    dev = event["dev_dispatch_identity"]
    if not isinstance(dev, dict) or dev.get("role") != "lane_b_dev":
        _v4_contract("real Dev dispatch identity required", "v4_identity_denied")
    if event["event_type"] not in {"COMMIT_READY", "TERMINAL_EVIDENCE_READY"}:
        if event["event_type"] == "TERMINAL_NO_AUTHORITY":
            failure = event["terminal_failure_identity"]
            if not isinstance(failure, dict):
                _v4_contract("terminal failure evidence required", "v4_identity_denied")
            cap, _value = _v4_artifact(
                root,
                failure["evidence"],
                failure["evidence"]["path"],
                "failure evidence",
            )
            if failure["message_sha256"] == _sha(b"") or cap.nlink != 1:
                _v4_contract("terminal failure identity invalid", "v4_identity_denied")
        return

    producer_cap, producer = _v4_artifact(
        root, event["producer_identity"], paths["dev_report"], "producer"
    )
    qa_cap, qa = _v4_artifact(
        root, event["qa_result_identity"], paths["qa_report"], "qa result"
    )
    readiness_cap, readiness = _v4_artifact(
        root, event["readiness_identity"], paths["readiness"], "readiness"
    )
    receipt_cap, receipt = _v4_artifact(
        root, event["receipt_identity"], paths["receipt"], "receipt"
    )
    schemas = context["closed_schemas"]
    for value, name in (
        (producer, "producer_evidence"),
        (qa, "independent_qa_evidence"),
        (readiness, "readiness"),
        (receipt, "receipt"),
    ):
        _v4_schema(value, schemas[name + "_schema"])

    # Caller strings do not establish authority. Reopen the exact immutable
    # successor ticket/context/BA-QA/admission on the confined surface too.
    for authority_path, authority_sha in (
        (V4_TICKET_PATH, V4_TICKET_SHA256),
        (V4_CONTEXT_DEFAULT, V4_CONTEXT_SHA256),
        (V4_BA_QA_PATH, V4_BA_QA_SHA256),
        (V4_PARENT_ADMISSION_PATH, V4_PARENT_ADMISSION_SHA256),
    ):
        authority = root.read(authority_path, modes={0o444})
        assert authority is not None
        if authority.sha256 != authority_sha:
            _v4_tamper("successor authority artifact byte drift")

    key = (kind, attempt)
    started_rows = [
        row
        for row in replay.rows
        if row.get("event_type") == "STARTED"
        and (row.get("attempt_kind"), row.get("attempt_id")) == key
    ]
    if len(started_rows) != 1:
        _v4_contract("exact STARTED predecessor required", "v4_identity_denied")
    started = started_rows[0]
    started_sha = _sha(_v4_json_line(started)[:-1])
    if started["dev_dispatch_identity"] != dev:
        _v4_contract("STARTED Dev lineage drift", "v4_identity_denied")
    expected_identity = _v4_attempt_identity(event)
    qa_dispatch = event["qa_dispatch_identity"]
    if not isinstance(qa_dispatch, dict):
        _v4_contract("fresh independent QA dispatch required", "v4_identity_denied")

    exact_dev = {
        "role": "lane_b_dev",
        "ticket_sha256": V4_TICKET_SHA256,
        "context_sha256": V4_CONTEXT_SHA256,
        "real_dispatch": True,
        "synthetic": False,
        "same_lane": True,
    }
    exact_qa = {
        "role": "independent_lane_b_qa",
        "ticket_sha256": V4_TICKET_SHA256,
        "context_sha256": V4_CONTEXT_SHA256,
        "real_dispatch": True,
        "synthetic": False,
        "same_lane": True,
    }
    if any(dev.get(k) != v for k, v in exact_dev.items()) or any(
        qa_dispatch.get(k) != v for k, v in exact_qa.items()
    ):
        _v4_contract("dispatch authority identity drift", "v4_identity_denied")
    if (
        qa_dispatch.get("agent_id") == dev.get("agent_id")
        or qa_dispatch.get("task_id") != dev.get("task_id")
        or qa_dispatch.get("dispatch_id") == dev.get("dispatch_id")
    ):
        _v4_contract("fresh independent QA composite required", "v4_identity_denied")

    producer_dispatch = producer["dev_dispatch"]
    qa_evidence_dispatch = qa["qa_dispatch"]
    if any(producer_dispatch.get(k) != v for k, v in dev.items()) or any(
        qa_evidence_dispatch.get(k) != v for k, v in qa_dispatch.items()
    ):
        _v4_contract("evidence dispatch link drift", "v4_identity_denied")
    for dispatch in (producer_dispatch, qa_evidence_dispatch):
        if (
            dispatch.get("ba_qa_sha256") != V4_BA_QA_SHA256
            or dispatch.get("parent_admission_sha256") != V4_PARENT_ADMISSION_SHA256
        ):
            _v4_contract("BA-QA/admission lineage drift", "v4_identity_denied")

    expected_tests = {
        "collected": 346,
        "passed": 346,
        "failed": 0,
        "existing_regression": 263,
        "new_logical_cases": 83,
        "partition": {
            "positive": 14,
            "negative": 40,
            "concurrency": 8,
            "crash_recovery": 9,
            "tamper": 12,
        },
    }
    bundle = producer["evidence_bundle_id"]
    if (
        producer["identity"] != expected_identity
        or qa["identity"] != expected_identity
        or readiness["identity"] != expected_identity
        or receipt["identity"] != expected_identity
        or any(
            value["evidence_bundle_id"] != bundle for value in (qa, readiness, receipt)
        )
        or any(
            value["started_event_sha256"] != started_sha
            for value in (producer, qa, readiness, receipt)
        )
        or producer["ticket_sha256"] != V4_TICKET_SHA256
        or producer["context_sha256"] != V4_CONTEXT_SHA256
        or producer["tests"] != expected_tests
        or qa["tests"] != expected_tests
        or set(producer["changed_paths"])
        != {
            "scripts/laneb-integration-gate.py",
            "hooks/tests/test_laneb_integration_gate.py",
        }
        or qa["producer"] != producer_cap.ref()
        or qa["qa_agent_id"] != qa_dispatch["agent_id"]
        or qa["dev_agent_id"] != dev["agent_id"]
        or qa["qa_agent_id"] == qa["dev_agent_id"]
        or readiness["producer"] != producer_cap.ref()
        or readiness["qa"] != qa_cap.ref()
        or receipt["producer"] != producer_cap.ref()
        or receipt["qa"] != qa_cap.ref()
        or receipt["readiness"] != readiness_cap.ref()
    ):
        _v4_contract("evidence attempt/artifact lineage drift", "v4_identity_denied")

    live_binding = _v4_live_binding(root, context, producer, qa)
    for value in (producer, qa, readiness, receipt, event):
        key_name = "binding_identity" if value is event else "binding"
        if value[key_name] != live_binding:
            _v4_contract(
                "live 16-provider/3-consumer binding drift", "v4_identity_denied"
            )

    validation = _timestamp(qa["freshness"]["validation_time"], "v4_identity_denied")
    started_at = _timestamp(started["event_at"], "v4_identity_denied")
    dev_dispatched = _timestamp(dev["dispatched_at"], "v4_identity_denied")
    producer_at = _timestamp(producer["created_at"], "v4_identity_denied")
    qa_dispatched = _timestamp(qa_dispatch["dispatched_at"], "v4_identity_denied")
    qa_started = _timestamp(qa["started_at"], "v4_identity_denied")
    qa_finalized = _timestamp(qa["finalized_at"], "v4_identity_denied")
    readiness_at = _timestamp(readiness["created_at"], "v4_identity_denied")
    receipt_at = _timestamp(receipt["created_at"], "v4_identity_denied")
    event_at = _timestamp(event["event_at"], "v4_identity_denied")
    now = dt.datetime.now(dt.timezone.utc)
    if not (
        dev_dispatched
        <= started_at
        <= producer_at
        <= qa_dispatched
        <= qa_started
        <= qa_finalized
        <= readiness_at
        <= receipt_at
        <= event_at
        and qa_finalized <= validation
        and validation - qa_finalized <= dt.timedelta(seconds=3600)
        and now - qa_finalized <= dt.timedelta(seconds=3600)
        and qa["freshness"]
        == {
            "validation_time": qa["freshness"]["validation_time"],
            "max_age_seconds": 3600,
            "max_future_skew_seconds": 5,
            "within_window": True,
        }
    ):
        _v4_contract("evidence freshness/order invalid", "v4_identity_denied")
    for timestamp in (
        dev_dispatched,
        started_at,
        producer_at,
        qa_dispatched,
        qa_started,
        qa_finalized,
        readiness_at,
        receipt_at,
        event_at,
        validation,
    ):
        if timestamp > validation + dt.timedelta(
            seconds=5
        ) or timestamp > now + dt.timedelta(seconds=5):
            _v4_contract("evidence future timestamp invalid", "v4_identity_denied")

    if event["event_type"] == "COMMIT_READY":
        if event["marker_identity"] is not None:
            _v4_contract("COMMIT_READY marker must be null", "v4_identity_denied")
        return

    marker_cap, marker = _v4_artifact(
        root, event["marker_identity"], paths["commit_marker"], "commit marker"
    )
    _v4_schema(marker, schemas["marker_schema"])
    commit_rows = [
        row
        for row in replay.rows
        if row.get("event_type") == "COMMIT_READY"
        and (row.get("attempt_kind"), row.get("attempt_id")) == key
    ]
    if len(commit_rows) != 1:
        _v4_contract("exact COMMIT_READY predecessor required", "v4_identity_denied")
    committed = commit_rows[0]
    commit_sha = _sha(_v4_json_line(committed)[:-1])
    for field in (
        "dev_dispatch_identity",
        "qa_dispatch_identity",
        "producer_identity",
        "qa_result_identity",
        "readiness_identity",
        "receipt_identity",
        "binding_identity",
    ):
        if event[field] != committed[field]:
            _v4_contract("terminal evidence predecessor drift", "v4_identity_denied")
    if (
        marker["identity"] != expected_identity
        or marker["evidence_bundle_id"] != bundle
        or marker["started_event_sha256"] != started_sha
        or marker["producer"] != producer_cap.ref()
        or marker["qa"] != qa_cap.ref()
        or marker["readiness"] != readiness_cap.ref()
        or marker["receipt"] != receipt_cap.ref()
        or marker["commit_ready_event_sha256"] != commit_sha
        or marker["binding"] != live_binding
    ):
        _v4_contract("terminal marker lineage drift", "v4_identity_denied")
    marker_at = _timestamp(marker["created_at"], "v4_identity_denied")
    commit_at = _timestamp(committed["event_at"], "v4_identity_denied")
    if not (receipt_at <= marker_at and commit_at <= marker_at <= event_at):
        _v4_contract("terminal marker time order invalid", "v4_identity_denied")
    if marker_at > validation + dt.timedelta(
        seconds=5
    ) or marker_at > now + dt.timedelta(seconds=5):
        _v4_contract("terminal marker future timestamp invalid", "v4_identity_denied")
    # Keep the capture live through all semantic checks; ref equality already
    # bound the exact marker bytes opened on the confined descriptor.
    if marker_cap.nlink != 1:
        _v4_tamper("terminal marker hardlink drift")


def _v4_read_event(
    root: V4Root, path: str, context: Mapping[str, Any]
) -> dict[str, Any]:
    cap = root.read(path, modes={0o444, 0o600, 0o644})
    assert cap is not None
    value = _v4_load_json(cap.data, line_framed=True)
    if not isinstance(value, dict):
        _v4_contract("transition event must be object", "v4_schema_invalid")
    _v4_schema(value, context["closed_schemas"]["event_schema"])
    validate_integrity(value, code="v4_schema_invalid")
    return value


def _v4_now(value: str | None = None) -> str:
    if value is not None:
        _timestamp(value, "v4_schema_invalid")
        return value
    return (
        dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _v4_migration_commit(
    root: V4Root,
    context: Mapping[str, Any],
    paths: Mapping[str, str],
    args: argparse.Namespace,
) -> dict[str, Any]:
    preflight = _v4_preflight(root, context, paths)
    existing_record = _v4_record(root, context, paths["record"], optional=True)
    registry_before = root.read(paths["registry"], modes={0o600}, optional=True)
    audit_before = root.read(paths["audit"], modes={0o444}, optional=True)
    if existing_record is None and (
        registry_before is not None or audit_before is not None
    ):
        _v4_tamper("impossible migration subset: registry/audit without record")
    wrote_record = False
    if existing_record is None:
        created_at = _v4_now(args.v4_event_at)
        value = _v4_expected_record(context, created_at)
        _v4_schema(value, context["closed_schemas"]["migration_record_schema"])
        cap = root.create(paths["record"], _v4_json_line(value), 0o444)
        existing_record = (cap, value)
        wrote_record = True
        if args.v4_crash_after == "migration-record":
            _v4_recovery("injected crash after migration record")
    record, record_value = existing_record
    genesis = _v4_genesis(context, record, record_value)
    genesis_line = _v4_json_line(genesis)
    genesis_tx_paths = _v4_tx_paths(context, genesis["transaction_id"])
    before_all_steps = all(
        root.exists(path)
        for key, path in genesis_tx_paths.items()
        if key != "terminal_failure"
    )

    # A complete exact genesis prefix may legally have an arbitrarily deep,
    # fully valid lifecycle tail. Validate every row and immutable transaction
    # before returning; this branch performs no creates, appends or truncates.
    if registry_before is not None and registry_before.data.startswith(genesis_line):
        replay = _v4_replay(context, registry_before, record)
        _v4_verify_all_transactions(root, context, record, registry_before, replay)
        audit_item = _v4_audit(
            root, context, paths["audit"], record, registry_before, optional=True
        )
        active = audit_item is not None
        captures = {
            key: root.read(path, modes={0o444})
            for key, path in genesis_tx_paths.items()
            if key != "terminal_failure"
        }
        assert all(cap is not None for cap in captures.values())
        intent = captures["step_01_intent"]
        appended = captures["step_02_appended"]
        commit = captures["step_03_commit"]
        assert intent is not None and appended is not None and commit is not None
        transaction = {
            "transaction_id": genesis["transaction_id"],
            "intent": intent.ref(),
            "appended": appended.ref(),
            "commit": commit.ref(),
            "registry": registry_before.ref(),
            "event_sha256_excluding_LF": _sha(genesis_line[:-1]),
            "idempotent": True,
        }
        return {
            "result": (
                "ALREADY_COMMITTED_EXACT_WITH_VALID_TAIL"
                if len(replay.rows) > 1 and active
                else (
                    "ALREADY_COMMITTED_EXACT"
                    if active
                    else "MIGRATION_COMMITTED_V4_INACTIVE_PENDING_INDEPENDENT_AUDIT"
                )
            ),
            "control_active": active,
            "record": record.ref(),
            "registry": registry_before.ref(),
            "registry_event_count": len(replay.rows),
            "lifecycle_event_count": len(replay.rows) - 1,
            "transaction": transaction,
            "legacy": preflight["legacy"],
            "G2_provider_satisfied": False,
            "authorization_effect": "none",
        }

    tx = _v4_append_event(
        root,
        context,
        record,
        paths["registry"],
        genesis,
        allow_absent=True,
        crash_after=(
            args.v4_crash_after
            if args.v4_crash_after in {"intent", "partial", "fsync", "append", "step2"}
            else None
        ),
    )
    registry = root.read(paths["registry"], modes={0o600})
    assert registry is not None
    replay = _v4_replay(context, registry, record)
    audit_item = _v4_audit(
        root, context, paths["audit"], record, registry, optional=True
    )
    active = audit_item is not None
    return {
        "result": (
            "ALREADY_COMMITTED_EXACT"
            if not wrote_record and before_all_steps and active
            else (
                "MIGRATION_COMMITTED_CONTROL_ACTIVE"
                if active
                else "MIGRATION_COMMITTED_V4_INACTIVE_PENDING_INDEPENDENT_AUDIT"
            )
        ),
        "control_active": active,
        "record": record.ref(),
        "registry": registry.ref(),
        "registry_event_count": len(replay.rows),
        "lifecycle_event_count": len(replay.rows) - 1,
        "transaction": tx,
        "legacy": preflight["legacy"],
        "G2_provider_satisfied": False,
        "authorization_effect": "none",
    }


def _v4_allocate(
    root: V4Root,
    context: Mapping[str, Any],
    paths: Mapping[str, str],
    args: argparse.Namespace,
) -> dict[str, Any]:
    record, _record_value, registry, replay, audit = _v4_activation(
        root, context, paths
    )
    if args.attempt_id:
        _v4_contract("caller-selected attempt token forbidden", "v4_identity_denied")
    kind = args.attempt_kind
    if kind in context["allocator_contract"]["disabled"]:
        _v4_contract(f"attempt kind disabled: {kind}", "v4_state_denied")
    if kind != "GATE_REPAIR_HB3":
        _v4_contract("only GATE_REPAIR_HB3 allocation enabled", "v4_state_denied")
    ids = replay.allocations.get(kind, [])
    if ids and replay.states[(kind, ids[-1])] != "TERMINAL_NO_AUTHORITY":
        _v4_contract(
            "prior same-kind attempt nonterminal/unreconciled", "v4_state_denied"
        )
    sequence = 15 if not ids else int(ids[-1][1:]) + 1
    attempt = f"a{sequence:06d}"
    if (
        attempt in context["allocator_contract"]["legacy_reuse_forbidden"]
        or sequence <= 14
    ):
        _v4_contract("legacy token collision", "v4_identity_denied")
    derived = _v4_derive_paths(context, kind, attempt)
    for value in derived.values():
        if root.exists(value):
            _v4_tamper(f"derived path collision: {value}", "v4_collision_denied")
    tx = os.urandom(16).hex()
    nonce = os.urandom(16).hex()
    event = {
        "schema_version": 4,
        "record_type": "lane_b_attempt_identity_registry_v4_event",
        "event_sequence": len(replay.rows) + 1,
        "previous_event_sha256": replay.head_sha256,
        "event_type": "ALLOCATED",
        "attempt_kind": kind,
        "attempt_id": attempt,
        "attempt_sequence": sequence,
        "attempt_uid": f"{SESSION_ID}/{SPEC_ID}/cycle-1/v4/{kind}/{attempt}",
        "transaction_id": tx,
        "nonce": nonce,
        "identity": {
            "session_id": SESSION_ID,
            "spec_id": SPEC_ID,
            "cycle_id": CYCLE_ID,
            "lane_id": LANE_ID,
            "pipeline_id": PIPELINE_ID,
        },
        "owner_role": "same_spec_parent",
        "derived_paths": derived,
        "migration_identity": None,
        "dev_dispatch_identity": None,
        "qa_dispatch_identity": None,
        "producer_identity": None,
        "qa_result_identity": None,
        "readiness_identity": None,
        "receipt_identity": None,
        "marker_identity": None,
        "recovery_identity": None,
        "terminal_failure_identity": None,
        "binding_identity": None,
        "precondition_manifest_sha256": canonical_sha(
            {
                "registry": registry.ref(),
                "audit": audit.ref(),
                "derived_absent": sorted(derived.values()),
            }
        ),
        "event_at": _v4_now(args.v4_event_at),
        "outcome": "none",
        "authorization_effect": "none",
        "integrity": {"canonicalization": V4_INTEGRITY_LANGUAGE},
    }
    event = _v4_with_integrity(event)
    tx_result = _v4_append_event(
        root, context, record, paths["registry"], event, crash_after=args.v4_crash_after
    )
    return {
        "result": "ALLOCATED",
        "attempt_kind": kind,
        "attempt_id": attempt,
        "attempt_sequence": sequence,
        "attempt_uid": event["attempt_uid"],
        "derived_paths": derived,
        "event_sha256_excluding_LF": tx_result["event_sha256_excluding_LF"],
        "transaction": tx_result,
        "G2_provider_satisfied": False,
        "authorization_effect": "none",
    }


def _v4_transition(
    root: V4Root,
    context: Mapping[str, Any],
    paths: Mapping[str, str],
    args: argparse.Namespace,
) -> dict[str, Any]:
    if not args.event_input:
        _v4_contract("--event-input required", "v4_schema_invalid")
    record, _record_value, registry, replay, _audit = _v4_activation(
        root, context, paths
    )
    event = _v4_read_event(root, args.event_input, context)
    line = _v4_json_line(event)
    if replay.lines and replay.lines[-1] == line:
        tx_result = _v4_finish_transaction(
            root, context, record, event["transaction_id"]
        )
        return {
            "result": "ALREADY_APPENDED_EXACT",
            "event_type": event["event_type"],
            "attempt_id": event["attempt_id"],
            "transaction": tx_result,
            "G2_provider_satisfied": False,
            "authorization_effect": "none",
        }
    if event["event_type"] in {"MIGRATION_GENESIS", "ALLOCATED"}:
        _v4_contract("transition phase cannot migrate/allocate", "v4_state_denied")
    if (
        event["event_sequence"] != len(replay.rows) + 1
        or event["previous_event_sha256"] != replay.head_sha256
    ):
        _v4_tamper("stale transition CAS head", "v4_cas_denied")
    if event["transaction_id"] in {
        row["transaction_id"] for row in replay.rows
    } or event["nonce"] in {row["nonce"] for row in replay.rows}:
        _v4_tamper("transaction/nonce reuse", "v4_replay_denied")
    if event["precondition_manifest_sha256"] != _v4_event_precondition(registry, event):
        _v4_tamper("transition precondition manifest drift", "v4_cas_denied")
    _v4_validate_evidence(root, context, event, replay)
    hypothetical = V4File(
        registry.path,
        registry.data + line,
        registry.mode,
        registry.nlink,
        registry.device,
        registry.inode,
    )
    _v4_replay(context, hypothetical, record)
    tx_result = _v4_append_event(
        root, context, record, paths["registry"], event, crash_after=args.v4_crash_after
    )
    return {
        "result": "TRANSITION_APPENDED",
        "event_type": event["event_type"],
        "attempt_id": event["attempt_id"],
        "transaction": tx_result,
        "G2_provider_satisfied": False,
        "authorization_effect": "none",
    }


def _v4_recover(
    root: V4Root,
    context: Mapping[str, Any],
    paths: Mapping[str, str],
    args: argparse.Namespace,
) -> dict[str, Any]:
    if not args.transaction_id or V4_TX_RE.fullmatch(args.transaction_id) is None:
        _v4_contract("--transaction-id required", "v4_identity_denied")
    record_item = _v4_record(root, context, paths["record"])
    if record_item is None:
        _v4_contract("migration record missing", "v4_state_denied")
    record, _record_value = record_item
    _intent_cap, intent = _v4_intent(root, context, args.transaction_id)
    event = _v4_load_json(bytes.fromhex(intent["intended_event_hex"]), line_framed=True)
    if event["event_type"] != "MIGRATION_GENESIS":
        # Audit and the complete genesis prefix must already be exact; the
        # trailing event may be partial and is reconciled under this same lock.
        registry = root.read(paths["registry"], modes={0o600})
        assert registry is not None
        genesis_line = (
            registry.data.splitlines(keepends=True)[0]
            if b"\n" in registry.data
            else b""
        )
        genesis_only = V4File(
            registry.path,
            genesis_line,
            registry.mode,
            registry.nlink,
            registry.device,
            registry.inode,
        )
        _v4_replay(context, genesis_only, record)
        _v4_audit(root, context, paths["audit"], record, genesis_only)
    result = _v4_finish_transaction(root, context, record, args.transaction_id)
    return {
        "result": "RECOVERED_EXACT",
        "transaction": result,
        "G2_provider_satisfied": False,
        "authorization_effect": "none",
    }


def _v4_verify_provider(
    root: V4Root,
    context: Mapping[str, Any],
    paths: Mapping[str, str],
    args: argparse.Namespace,
) -> dict[str, Any]:
    _record, _value, registry, replay, _audit = _v4_activation(root, context, paths)
    if not args.attempt_id or ATTEMPT_RE.fullmatch(args.attempt_id) is None:
        _v4_contract("--attempt-id required", "v4_identity_denied")
    key = ("GATE_REPAIR_HB3", args.attempt_id)
    if replay.states.get(key) != "TERMINAL_EVIDENCE_READY":
        _v4_contract("attempt not terminal evidence ready", "v4_state_denied")
    event = next(
        row for row in reversed(replay.rows) if row.get("attempt_id") == args.attempt_id
    )
    _v4_validate_evidence(root, context, event, replay)
    return {
        "result": "VERIFIED_FOR_FRESH_G2_REAUDIT_ONLY",
        "attempt_id": args.attempt_id,
        "registry": registry.ref(),
        "state": "TERMINAL_EVIDENCE_READY",
        "G2_reaudit_eligible": True,
        "G2_provider_satisfied": False,
        "authorization_effect": "none",
        "authorizes": [],
    }


def _v4_success(
    phase: str, result: Mapping[str, Any], lock_identity: str | None
) -> dict[str, Any]:
    return {
        "schema_version": 4,
        "record_type": "lane_b_registry_v4_control_result",
        "phase": phase,
        "status": "pass",
        "lock_identity": lock_identity,
        "result": dict(result),
        "G2_provider_satisfied": False,
        "authorization_effect": "none",
        "authorizes": [],
        **NONCLAIMS,
    }


def _v4_failure(phase: str, exc: GateError, exit_code: int) -> dict[str, Any]:
    state = (
        "recovery_required"
        if exit_code == 5
        else "lock_timeout" if exit_code == 4 else "denied"
    )
    return {
        "schema_version": 4,
        "record_type": "lane_b_registry_v4_control_result",
        "phase": phase,
        "status": state,
        "exit_code": exit_code,
        "findings": [exc.finding()],
        "G2_provider_satisfied": False,
        "authorization_effect": "none",
        "authorizes": [],
        **NONCLAIMS,
    }


def run_v4_phase(args: argparse.Namespace) -> dict[str, Any]:
    with V4Root(args.project_root) as root:
        context_path = args.v4_context or V4_CONTEXT_DEFAULT
        _context_cap, context = _v4_context(root, context_path)
        paths = _v4_paths(args, context, root)
        if paths["context"] != context_path:
            _v4_contract("context path resolution mismatch")
        if args.phase == "registry-v4-migration-preflight":
            return _v4_success(args.phase, _v4_preflight(root, context, paths), None)
        with _v4_lock(root, paths["lock"], args.lock_timeout) as lock_identity:
            if args.phase == "registry-v4-migration-commit":
                result = _v4_migration_commit(root, context, paths, args)
            elif args.phase == "registry-v4-allocate":
                result = _v4_allocate(root, context, paths, args)
            elif args.phase == "registry-v4-transition":
                result = _v4_transition(root, context, paths, args)
            elif args.phase == "registry-v4-recover":
                result = _v4_recover(root, context, paths, args)
            elif args.phase == "verify-h-b-v4-provider-set":
                result = _v4_verify_provider(root, context, paths, args)
            else:
                _v4_contract("unknown v4 phase")
            return _v4_success(args.phase, result, lock_identity)


# ---------------------------------------------------------------------------
# Lane-B registry v5 prospective protocol recovery.
# ---------------------------------------------------------------------------
V5_CONTEXT_DEFAULT = (
    "docs/dev/context-20260817-lane-b-registry-v5-protocol-recovery.v3.json"
)
V5_CONTEXT_SHA256 = "7ab7b04193ec2fe599e3502c6ba4890a730b2fba13eea5de55a712947a27a405"
V5_READINESS_PATH = (
    "docs/dev/overnight/019fe5c1-5b46-7dd1-8086-591a5b932bf3/cycle-1/"
    "lane-b-registry-v5-protocol-recovery-ba-contract-and-readiness.v3.json"
)
V5_READINESS_SHA256 = "b7e78bad1b2a78dc899684eb3e769b5be2854a6aa6b6386386ca159d5b91f9ff"
V5_TICKET_SHA256 = "a9919fed2f92352af7a84acc3043393b7d13f62951b5931fa51fd1b8c5a7a84c"
V5_BA_QA_SHA256 = "8c69b43666ed7f85ba1b88dc6c0c45daf2f65755246829d89d776f3e7fb26690"
V5_PARENT_ADMISSION_SHA256 = (
    "57e96a95711a7bcbbe0ab2bb7ed09a5ff951b4453d05b5d0afecb96396cf7016"
)
V5_BINDING_DENIAL_SHA256 = (
    "622f2a1c6d0be286eb294ed7ed46bc85d5aa6e3fe93813b20c0ad9d6251a290c"
)
V5_FROZEN_V4_SHA256 = "6fa77ed0edf5e2f1484146bf2a50b93169e9211df80520141896b0606ef2dc8f"
V5_FROZEN_V4_HEAD_SHA256 = (
    "599db1cf404b91ce5aef9c873db007868c83791fefc3b635d5c5a61aa0e1a650"
)
V5_INTEGRITY_LANGUAGE = V4_INTEGRITY_LANGUAGE
V5_ATTEMPT_ID = "a000017"
V5_ATTEMPT_SEQUENCE = 17
V5_ATTEMPT_KIND = "GATE_REPAIR_HB3"
V5_ATTEMPT_UID = f"{SESSION_ID}/{SPEC_ID}/cycle-1/v5/{V5_ATTEMPT_KIND}/{V5_ATTEMPT_ID}"
V5_STATES = (
    "ALLOCATED",
    "STARTED",
    "EVIDENCE_SEALED",
    "PROVIDER_VERIFIED",
    "TERMINAL_G2_ELIGIBLE",
    "TERMINAL_NO_AUTHORITY",
)
V5_NONTERMINAL_STATES = frozenset(V5_STATES[:4])
V5_TERMINAL_STATES = frozenset(V5_STATES[4:])
V5_PHASES = {
    "registry-v5-migration-preflight",
    "registry-v5-migration-commit",
    "registry-v5-activate",
    "registry-v5-allocate",
    "registry-v5-start",
    "registry-v5-seal",
    "registry-v5-promote",
    "registry-v5-recover",
    "verify-h-b-v5-provider-set",
}
V5_TX_RE = re.compile(r"^[0-9a-f]{32}$")
V5_SCHEMA_DIGESTS = {
    "activation": "a926af9b1d9b9f7f48b40a48afa0c081cf52e9cdfc5cab1ee6816a955e493246",
    "event": "0f6e55ee2bc5667c293990c35cf71d2a7b2568a2c86e1bdc53c9a022b14d60e2",
    "migration_audit": "b01eedd131837195d9f36b36b71c12d8116be2f0cfeea874fc46eb287fc6a4cf",
    "migration_record": "03c7baff440a1ef226b3c139979b7c4a721c0936e5d5894d1d70ba3580d7af17",
    "provider_verification": "39b63a79fabd48f77cbc128cc2e24243e91a2a9aa2eb753ae5370c07c26810ed",
    "terminal_failure": "942cd919739b3d35d36f7735824924a3af5f5466dffcb3c8313920191aa9de17",
    "terminal_marker": "4a2ab113a0023918077aec4b01558589d94966b85f3dcb6639eaa8d61e2b05e9",
    "timing_receipt": "9e204bbf2fd6444f398d41315a62aad66457b487f36593ea740acd36dff34d03",
}


class V5Error(GateError):
    """A v5 denial with the public 0/2/3/4/5 exit taxonomy."""

    def __init__(
        self, exit_code: int, code: str, message: str, *, state: str = "denied"
    ):
        super().__init__(code, "same-spec parent", message, state=state)
        self.exit_code = exit_code


def _v5_deny(exit_code: int, code: str, message: str, *, state: str = "denied") -> None:
    if exit_code not in {2, 3, 4, 5}:
        raise AssertionError("invalid v5 exit code")
    raise V5Error(exit_code, code, message, state=state)


def _v5_contract(message: str, code: str = "v5_contract_denied") -> None:
    _v5_deny(2, code, message)


def _v5_tamper(message: str, code: str = "v5_tamper_denied") -> None:
    _v5_deny(3, code, message)


def _v5_recovery(message: str) -> None:
    _v5_deny(5, "v5_recovery_required", message, state="recovery_required")


def _v5_no_authority() -> dict[str, Any]:
    return {
        "G2_provider_satisfied": False,
        "authorization_effect": "none",
        "authorizes": [],
    }


def _v5_load_json(data: bytes, *, line_framed: bool = False) -> Any:
    if data.startswith(b"\xef\xbb\xbf") or b"\r" in data:
        _v5_tamper("BOM/CR framing forbidden")
    if line_framed:
        if not data.endswith(b"\n") or data.count(b"\n") != 1 or not data[:-1]:
            _v5_tamper("canonical JSON artifact requires exactly one final LF")
        data = data[:-1]
    try:
        text = data.decode("utf-8", "strict")
        value = json.loads(
            text,
            object_pairs_hook=_v4_pairs,
            parse_constant=lambda token: _v5_tamper(f"non-finite JSON: {token}"),
        )
    except V5Error:
        raise
    except V4Error as exc:
        _v5_tamper(exc.message)
    except (UnicodeError, json.JSONDecodeError) as exc:
        _v5_tamper(f"invalid strict JSON: {type(exc).__name__}")
    _finite(value)
    _v4_nfc(value)
    if line_framed and _canonical(value) != data:
        _v5_tamper("JSON artifact is not canonical compact UTF-8")
    return value


def _v5_json_line(value: Any) -> bytes:
    _v4_nfc(value)
    return _canonical(value) + b"\n"


def _v5_schema(instance: Any, context: Mapping[str, Any], family: str) -> None:
    schemas = context.get("closed_schemas")
    if not isinstance(schemas, dict) or family not in schemas:
        _v5_contract(f"missing closed schema family: {family}", "v5_schema_invalid")
    item = schemas[family]
    if not isinstance(item, dict) or set(item) != {"canonical_sha256", "schema"}:
        _v5_contract(f"malformed schema wrapper: {family}", "v5_schema_invalid")
    schema = item.get("schema")
    digest = V5_SCHEMA_DIGESTS.get(family)
    if (
        not isinstance(schema, dict)
        or digest is None
        or canonical_sha(schema) != digest
        or item.get("canonical_sha256") != digest
    ):
        _v5_contract(f"schema digest drift: {family}", "v5_schema_invalid")
    if jsonschema is None:
        _v5_contract("jsonschema runtime unavailable", "v5_schema_invalid")
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(instance)
    except Exception as exc:
        _v5_contract(
            f"Draft-2020-12 validation failed for {family}: {type(exc).__name__}",
            "v5_schema_invalid",
        )


def _v5_ref_equal(cap: V4File, expected: Mapping[str, Any], label: str) -> None:
    if cap.ref() != dict(expected):
        _v5_tamper(f"{label} immutable identity drift", "v5_identity_drift")


def _v5_absolute_ref(expected: Mapping[str, Any], label: str) -> None:
    path = expected.get("path")
    if not isinstance(path, str) or not Path(path).is_absolute():
        _v5_contract(f"{label} absolute identity invalid")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except OSError:
        _v5_tamper(f"{label} absolute artifact missing/unsafe")
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            _v5_tamper(f"{label} absolute artifact identity invalid")
        chunks: list[bytes] = []
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            chunks.append(block)
        after = os.fstat(fd)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            _v5_tamper(f"{label} absolute artifact descriptor drift")
        data = b"".join(chunks)
        observed = {
            "path": path,
            "bytes": len(data),
            "sha256": _sha(data),
            "mode": f"{stat.S_IMODE(before.st_mode):04o}",
            "nlink": before.st_nlink,
            "state": "file",
            "symlink": False,
        }
        if observed != dict(expected):
            _v5_tamper(f"{label} absolute artifact identity drift")
    finally:
        os.close(fd)


def _v5_context(root: V4Root, path: str) -> tuple[V4File, dict[str, Any]]:
    readiness_cap = root.read(V5_READINESS_PATH, modes={0o444})
    assert readiness_cap is not None
    if readiness_cap.sha256 != V5_READINESS_SHA256:
        _v5_tamper("v5 readiness immutable identity drift")
    readiness = _v5_load_json(readiness_cap.data)
    try:
        authority = readiness["published_BA_artifacts"]["context"]
    except (KeyError, TypeError):
        _v5_contract("readiness context hash authority missing")
    cap = root.read(path, modes={0o444})
    assert cap is not None
    if (
        path != V5_CONTEXT_DEFAULT
        or cap.sha256 != V5_CONTEXT_SHA256
        or not isinstance(authority, dict)
        or authority.get("path") != V5_CONTEXT_DEFAULT
        or authority.get("sha256") != cap.sha256
    ):
        _v5_contract("v5 normative context identity drift")
    value = _v5_load_json(cap.data)
    if not isinstance(value, dict):
        _v5_contract("v5 context must be object")
    identity = value.get("identity")
    if (
        value.get("schema_name") != "lane_b_registry_v5_protocol_recovery_ba_context.v3"
        or value.get("schema_version") != 3
        or not isinstance(identity, dict)
        or identity.get("session_id") != SESSION_ID
        or identity.get("spec_id") != SPEC_ID
        or identity.get("cycle_id") != CYCLE_ID
        or identity.get("lane_id") != LANE_ID
        or identity.get("pipeline_id") != PIPELINE_ID
    ):
        _v5_contract("wrong v5 context identity")
    if set(value.get("closed_schemas", {})) != set(V5_SCHEMA_DIGESTS):
        _v5_contract("v5 schema family set drift", "v5_schema_invalid")
    for family in V5_SCHEMA_DIGESTS:
        item = value["closed_schemas"].get(family)
        if not isinstance(item, dict) or not isinstance(item.get("schema"), dict):
            _v5_contract(f"missing schema: {family}", "v5_schema_invalid")
        if (
            item.get("canonical_sha256") != V5_SCHEMA_DIGESTS[family]
            or canonical_sha(item["schema"]) != V5_SCHEMA_DIGESTS[family]
        ):
            _v5_contract(f"schema digest drift: {family}", "v5_schema_invalid")
        try:
            if jsonschema is None:
                raise RuntimeError("jsonschema unavailable")
            jsonschema.Draft202012Validator.check_schema(item["schema"])
        except Exception as exc:
            _v5_contract(
                f"schema meta-invalid {family}: {type(exc).__name__}",
                "v5_schema_invalid",
            )
    model = value.get("persisted_state_model", {})
    if (
        model.get("closed_vocabulary") != list(V5_STATES)
        or model.get("exact_active_alias_allowed") is not False
        or any(
            row.get("attempt_state_before") == "ACTIVE"
            or row.get("persisted_state_after") == "ACTIVE"
            or (
                isinstance(row.get("attempt_state_before"), list)
                and "ACTIVE" in row["attempt_state_before"]
            )
            for row in model.get("event_mapping", [])
            if isinstance(row, dict)
        )
    ):
        _v5_contract("v5 persisted state model drift")
    return cap, value


def _v5_paths(
    args: argparse.Namespace, context: Mapping[str, Any], root: V4Root
) -> dict[str, str]:
    artifacts = context["v5_artifacts"]
    defaults = {
        "context": V5_CONTEXT_DEFAULT,
        "v4": context["authoritative_inputs"]["v4_registry"]["path"],
        "registry": artifacts["registry"],
        "record": artifacts["migration_record"],
        "audit": artifacts["migration_audit"],
        "activation": artifacts["activation"],
        "lock": artifacts["lock"],
    }
    supplied = {
        "context": args.v5_context,
        "v4": args.v4_registry_frozen,
        "registry": args.v5_registry,
        "record": args.v5_migration_record,
        "audit": args.v5_migration_audit,
        "activation": args.v5_activation,
        "lock": args.v5_lock,
    }
    has_override = any(
        value is not None and value != defaults[key] for key, value in supplied.items()
    )
    has_injection = any(
        value is not None
        for value in (
            args.v5_crash_after,
            args.v5_test_duration_ns,
            args.v5_test_provider_duration_ns,
        )
    )
    if (has_override or has_injection or args.v5_test_mode) and not args.v5_test_mode:
        _v5_contract("production path/clock/crash overrides are forbidden")
    if args.v5_test_mode:
        marker = root.read(".laneb-v5-throwaway-root", modes={0o600, 0o644})
        if (
            marker is None
            or marker.data != b"LANEB_V5_THROWAWAY\n"
            or (root.root / ".git").exists()
        ):
            _v5_contract("v5 test controls require marked non-repository root")
    result = {key: supplied[key] or value for key, value in defaults.items()}
    for rel in result.values():
        _v4_parts(rel)
    return result


def _v5_validate_frozen_v4(
    root: V4Root, context: Mapping[str, Any], paths: Mapping[str, str]
) -> tuple[V4File, V4Replay]:
    inputs = context["authoritative_inputs"]
    for name, expected in inputs.items():
        if name in {"source_preimage", "test_preimage", "v4_registry"}:
            continue
        if not isinstance(expected, dict) or "path" not in expected:
            continue
        path = expected["path"]
        if Path(path).is_absolute():
            _v5_absolute_ref(expected, name)
        else:
            cap = root.read(path, modes={int(expected["mode"], 8)})
            assert cap is not None
            _v5_ref_equal(cap, expected, name)
    v4_expected = inputs["v4_registry"]
    if paths["v4"] != v4_expected["path"]:
        _v5_contract("frozen v4 path override forbidden")
    frozen = root.read(paths["v4"], modes={0o600})
    assert frozen is not None
    _v5_ref_equal(frozen, v4_expected, "frozen v4 registry")
    if frozen.sha256 != V5_FROZEN_V4_SHA256:
        _v5_tamper("frozen v4 raw SHA drift")

    # Reuse the already-closed v4 parser and WAL verifier, but never invoke a
    # v4 mutating phase. This proves all eight frozen rows and transactions.
    _v4_cap, v4_context = _v4_context(root, V4_CONTEXT_DEFAULT)
    record_path = v4_context["v4_artifacts"]["migration_record"]["path"]
    audit_path = v4_context["v4_artifacts"]["migration_audit"]["path"]
    record_item = _v4_record(root, v4_context, record_path)
    if record_item is None:
        _v5_tamper("frozen v4 migration record missing")
    record, _record_value = record_item
    replay = _v4_replay(v4_context, frozen, record)
    test_marker = root.read(
        ".laneb-v5-throwaway-root", modes={0o600, 0o644}, optional=True
    )
    if test_marker is None:
        _v4_verify_all_transactions(root, v4_context, record, frozen, replay)
    else:
        # A copied throwaway tree necessarily has different inode identities.
        # Validate each immutable WAL triple and event digest without pretending
        # those copied inodes are the production descriptors bound by v4.
        for row in replay.rows:
            tx_paths = _v4_tx_paths(v4_context, row["transaction_id"])
            intent_cap = root.read(tx_paths["step_01_intent"], modes={0o444})
            appended_cap = root.read(tx_paths["step_02_appended"], modes={0o444})
            commit_cap = root.read(tx_paths["step_03_commit"], modes={0o444})
            assert (
                intent_cap is not None
                and appended_cap is not None
                and commit_cap is not None
            )
            intent = _v4_load_json(intent_cap.data, line_framed=True)
            appended = _v4_load_json(appended_cap.data, line_framed=True)
            commit = _v4_load_json(commit_cap.data, line_framed=True)
            event_line = _v4_json_line(row)
            if (
                intent.get("transaction_id") != row["transaction_id"]
                or bytes.fromhex(intent.get("intended_event_hex", "")) != event_line
                or appended.get("intent", {}).get("sha256") != intent_cap.sha256
                or commit.get("intent", {}).get("sha256") != intent_cap.sha256
                or commit.get("appended", {}).get("sha256") != appended_cap.sha256
                or commit.get("event_sha256_excluding_LF") != _sha(event_line[:-1])
            ):
                _v5_tamper("copied frozen v4 WAL triple drift")
    _v4_audit(root, v4_context, audit_path, record, frozen)
    if (
        len(replay.rows) != 8
        or len(replay.rows) - 1 != 7
        or replay.head_sha256 != V5_FROZEN_V4_HEAD_SHA256
        or replay.states.get((V5_ATTEMPT_KIND, "a000015")) != "TERMINAL_NO_AUTHORITY"
        or replay.states.get((V5_ATTEMPT_KIND, "a000016")) != "TERMINAL_EVIDENCE_READY"
    ):
        _v5_tamper("frozen v4 replay projection drift")
    denial = inputs["binding_denial"]
    if denial.get("sha256") != V5_BINDING_DENIAL_SHA256:
        _v5_contract("binding denial identity drift")
    return frozen, replay


def _v5_preflight(
    root: V4Root,
    context: Mapping[str, Any],
    paths: Mapping[str, str],
    *,
    require_absent: bool,
) -> dict[str, Any]:
    frozen, replay = _v5_validate_frozen_v4(root, context, paths)
    present = {
        key: root.exists(paths[key])
        for key in ("record", "registry", "audit", "activation")
    }
    if require_absent and any(present.values()):
        _v5_contract("v5 control artifacts must all be absent for preflight")
    return {
        "result": "FROZEN_V4_EXACT_V5_PROSPECTIVE",
        "source_v4_registry": frozen.ref(),
        "source_v4_event_count": len(replay.rows),
        "source_v4_lifecycle_event_count": len(replay.rows) - 1,
        "source_v4_head_sha256": replay.head_sha256,
        "source_projection": {
            "a000015": "TERMINAL_NO_AUTHORITY",
            "a000016": "TERMINAL_EVIDENCE_READY_DENIED_BY_BINDING",
            "imported_authority": "none",
            "replay_eligible_attempts": [],
        },
        "v5_control_presence": present,
        **_v5_no_authority(),
    }


def _v5_now(value: str | None = None) -> str:
    if value is not None:
        _timestamp(value, "v5_schema_invalid")
        return value
    return (
        dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _v5_expected_record(
    context: Mapping[str, Any], frozen: V4File, created_at: str
) -> dict[str, Any]:
    denial = context["authoritative_inputs"]["binding_denial"]
    return {
        "schema_name": "lane_b_attempt_registry_v4_to_v5_migration.v1",
        "schema_version": 1,
        "record_type": "immutable_non_authorizing_v5_migration_record",
        "status": "V5_INACTIVE_PENDING_INDEPENDENT_AUDIT",
        "created_at": created_at,
        "identity": {
            "session_id": SESSION_ID,
            "spec_id": SPEC_ID,
            "cycle_id": CYCLE_ID,
            "lane_id": LANE_ID,
            "pipeline_id": PIPELINE_ID,
        },
        "source_v4_registry": frozen.ref(),
        "source_v4_head_sha256": V5_FROZEN_V4_HEAD_SHA256,
        "source_v4_event_count": 8,
        "source_v4_lifecycle_event_count": 7,
        "binding_denial": dict(denial),
        "source_projection": {
            "a000015": "TERMINAL_NO_AUTHORITY",
            "a000016": "TERMINAL_EVIDENCE_READY_DENIED_BY_BINDING",
            "imported_authority": "none",
            "replay_eligible_attempts": [],
        },
        "authorization": _v5_no_authority(),
    }


def _v5_record(
    root: V4Root,
    context: Mapping[str, Any],
    path: str,
    frozen: V4File,
    *,
    optional: bool = False,
) -> tuple[V4File, dict[str, Any]] | None:
    cap = root.read(path, modes={0o444}, optional=optional)
    if cap is None:
        return None
    value = _v5_load_json(cap.data, line_framed=True)
    if not isinstance(value, dict):
        _v5_contract("v5 migration record must be object", "v5_schema_invalid")
    _v5_schema(value, context, "migration_record")
    _timestamp(value["created_at"], "v5_schema_invalid")
    if value != _v5_expected_record(context, frozen, value["created_at"]):
        _v5_tamper("v5 migration record semantic drift")
    return cap, value


def _v5_with_integrity(event: Mapping[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(dict(event))
    integrity = value.setdefault("integrity", {})
    if not isinstance(integrity, dict):
        _v5_contract("event integrity must be object", "v5_schema_invalid")
    integrity["canonicalization"] = V5_INTEGRITY_LANGUAGE
    integrity.pop("event_payload_sha256", None)
    integrity["event_payload_sha256"] = canonical_sha(value)
    return value


def _v5_derive_paths(context: Mapping[str, Any]) -> dict[str, str]:
    templates = context["v5_artifacts"]["derived_attempt_paths"]
    if not isinstance(templates, dict) or len(templates) != 14:
        _v5_contract("v5 derived-path template count drift")
    result: dict[str, str] = {}
    for key, template in templates.items():
        if not isinstance(template, str) or template.count("{attempt_id}") != 1:
            _v5_contract("ambiguous v5 derived-path template")
        value = template.replace("{attempt_id}", V5_ATTEMPT_ID)
        _v4_parts(value)
        result[key] = value
    if len(set(result.values())) != 14:
        _v5_contract("v5 derived-path collision")
    return result


def _v5_attempt_identity() -> dict[str, Any]:
    return {
        "session_id": SESSION_ID,
        "spec_id": SPEC_ID,
        "cycle_id": CYCLE_ID,
        "lane_id": LANE_ID,
        "pipeline_id": PIPELINE_ID,
        "attempt_kind": V5_ATTEMPT_KIND,
        "attempt_id": V5_ATTEMPT_ID,
        "attempt_sequence": V5_ATTEMPT_SEQUENCE,
        "attempt_uid": V5_ATTEMPT_UID,
    }


def _v5_genesis(
    context: Mapping[str, Any], record: V4File, record_value: Mapping[str, Any]
) -> dict[str, Any]:
    tx = _sha(("v5-genesis-transaction:" + record.sha256).encode())[:32]
    nonce = _sha(("v5-genesis-nonce:" + record.sha256).encode())[:32]
    event = {
        "schema_version": 5,
        "record_type": "lane_b_attempt_identity_registry_v5_event",
        "event_sequence": 1,
        "previous_event_sha256": None,
        "event_type": "MIGRATION_GENESIS",
        "attempt_kind": "MIGRATION",
        "attempt_id": None,
        "attempt_sequence": None,
        "attempt_uid": None,
        "transaction_id": tx,
        "nonce": nonce,
        "identity": {
            **record_value["identity"],
            "attempt_kind": "MIGRATION",
            "attempt_id": None,
            "attempt_sequence": None,
            "attempt_uid": None,
        },
        "owner_role": "same_spec_parent",
        "derived_paths": {},
        "migration_identity": record.ref(),
        "dev_dispatch_identity": None,
        "qa_dispatch_identity": None,
        "producer_identity": None,
        "qa_result_identity": None,
        "readiness_identity": None,
        "receipt_identity": None,
        "timing_identity": None,
        "provider_verification_identity": None,
        "terminal_marker_identity": None,
        "terminal_failure_identity": None,
        "precondition_manifest_sha256": canonical_sha(
            {
                "migration_record": record.ref(),
                "source_v4_registry": record_value["source_v4_registry"],
                "binding_denial": record_value["binding_denial"],
            }
        ),
        "event_at": record_value["created_at"],
        "outcome": "migration_initialized_non_authorizing",
        "authorization": _v5_no_authority(),
        "integrity": {"canonicalization": V5_INTEGRITY_LANGUAGE},
        "attempt_state_before": None,
        "persisted_state_after": None,
    }
    return _v5_with_integrity(event)


@dataclass
class V5Replay:
    rows: list[dict[str, Any]]
    lines: list[bytes]
    states: dict[tuple[str, str], str]
    allocations: list[str]
    dispatch_ids: set[str]

    @property
    def head_sha256(self) -> str | None:
        return _sha(self.lines[-1][:-1]) if self.lines else None


def _v5_registry_rows(data: bytes) -> tuple[list[dict[str, Any]], list[bytes]]:
    if (
        not data
        or not data.endswith(b"\n")
        or b"\r" in data
        or data.startswith(b"\xef\xbb\xbf")
    ):
        _v5_tamper("v5 registry framing invalid")
    lines = data.splitlines(keepends=True)
    if any(line == b"\n" or not line.endswith(b"\n") for line in lines):
        _v5_tamper("v5 registry blank/missing LF")
    rows: list[dict[str, Any]] = []
    for line in lines:
        value = _v5_load_json(line, line_framed=True)
        if not isinstance(value, dict):
            _v5_contract("v5 event must be object", "v5_schema_invalid")
        rows.append(value)
    return rows, lines


def _v5_dispatch_valid(value: Any, role: str) -> bool:
    forbidden_prior_tokens = {"a000015", "a000016"}
    identity_text = (
        " ".join(
            str(value.get(key, "")) for key in ("dispatch_id", "task_id", "agent_id")
        )
        if isinstance(value, dict)
        else ""
    )
    return (
        isinstance(value, dict)
        and not any(token in identity_text for token in forbidden_prior_tokens)
        and value.get("role") == role
        and value.get("ticket_sha256") == V5_TICKET_SHA256
        and value.get("context_sha256") == V5_CONTEXT_SHA256
        and value.get("ba_qa_sha256") == V5_BA_QA_SHA256
        and value.get("parent_admission_sha256") == V5_PARENT_ADMISSION_SHA256
        and value.get("real_dispatch") is True
        and value.get("synthetic") is False
        and value.get("same_lane") is True
        and isinstance(value.get("agent_id"), str)
        and bool(value.get("agent_id"))
        and isinstance(value.get("dispatch_id"), str)
        and bool(value.get("dispatch_id"))
    )


def _v5_replay(
    context: Mapping[str, Any], registry: V4File, record: V4File
) -> V5Replay:
    rows, lines = _v5_registry_rows(registry.data)
    states: dict[tuple[str, str], str] = {}
    allocations: list[str] = []
    dispatch_ids: set[str] = set()
    txs: set[str] = set()
    nonces: set[str] = set()
    prior: str | None = None
    allocation: dict[str, Any] | None = None
    dev_dispatch: dict[str, Any] | None = None
    terminal_g2_count = 0
    for number, (row, line) in enumerate(zip(rows, lines), 1):
        _v5_schema(row, context, "event")
        payload = copy.deepcopy(row)
        observed_digest = payload["integrity"].pop("event_payload_sha256")
        if canonical_sha(payload) != observed_digest:
            _v5_tamper("v5 event payload digest invalid", "v5_replay_denied")
        if row["event_sequence"] != number or row["previous_event_sha256"] != prior:
            _v5_tamper("v5 event fork/gap/prior hash drift", "v5_replay_denied")
        if row["transaction_id"] in txs or row["nonce"] in nonces:
            _v5_tamper("v5 transaction/nonce replay", "v5_replay_denied")
        txs.add(row["transaction_id"])
        nonces.add(row["nonce"])
        if row["authorization"] != _v5_no_authority():
            _v5_contract("v5 event authority claim forbidden")
        if number == 1:
            expected = _v5_genesis(
                context, record, _v5_load_json(record.data, line_framed=True)
            )
            if row != expected:
                _v5_tamper("v5 genesis event drift", "v5_replay_denied")
            prior = _sha(line[:-1])
            continue
        if (
            row["attempt_kind"] != V5_ATTEMPT_KIND
            or row["attempt_id"] != V5_ATTEMPT_ID
            or row["attempt_sequence"] != V5_ATTEMPT_SEQUENCE
            or row["attempt_uid"] != V5_ATTEMPT_UID
            or row["identity"] != _v5_attempt_identity()
            or row["derived_paths"] != _v5_derive_paths(context)
        ):
            _v5_contract("v5 attempt composite identity drift", "v5_identity_denied")
        key = (V5_ATTEMPT_KIND, V5_ATTEMPT_ID)
        current = states.get(key)
        event_type = row["event_type"]
        if event_type == "ALLOCATED":
            if (
                allocation is not None
                or current is not None
                or row["attempt_state_before"] != "NONE"
                or row["persisted_state_after"] != "ALLOCATED"
            ):
                _v5_contract("second/divergent v5 allocation", "v5_state_denied")
            allocation = row
            allocations.append(V5_ATTEMPT_ID)
            states[key] = "ALLOCATED"
        else:
            if allocation is None:
                _v5_tamper(
                    "v5 event without allocation predecessor", "v5_replay_denied"
                )
            if current in V5_TERMINAL_STATES:
                _v5_contract("v5 terminal is absorbing", "v5_state_denied")
            allowed_before: dict[str, set[str]] = {
                "STARTED": {"ALLOCATED"},
                "EVIDENCE_SEALED": {"STARTED"},
                "PROVIDER_VERIFIED": {"EVIDENCE_SEALED"},
                "TERMINAL_G2_ELIGIBLE": {"PROVIDER_VERIFIED"},
                "TERMINAL_NO_AUTHORITY": set(V5_NONTERMINAL_STATES),
            }
            if (
                event_type not in allowed_before
                or current not in allowed_before[event_type]
            ):
                _v5_contract("unlisted/out-of-order v5 transition", "v5_state_denied")
            if (
                row["attempt_state_before"] != current
                or row["persisted_state_after"] != event_type
            ):
                _v5_contract("v5 persisted-state mapping drift", "v5_state_denied")
            if event_type == "STARTED":
                dispatch = row["dev_dispatch_identity"]
                if not _v5_dispatch_valid(dispatch, "lane_b_dev"):
                    _v5_contract(
                        "fresh real v5 Dev dispatch required", "v5_identity_denied"
                    )
                if dispatch["dispatch_id"] in dispatch_ids:
                    _v5_contract("v5 Dev dispatch reuse", "v5_identity_denied")
                dispatch_ids.add(dispatch["dispatch_id"])
                dev_dispatch = dispatch
            else:
                if row["dev_dispatch_identity"] != dev_dispatch:
                    _v5_contract("v5 Dev dispatch lineage drift", "v5_identity_denied")
            if event_type == "EVIDENCE_SEALED":
                qa = row["qa_dispatch_identity"]
                if (
                    not _v5_dispatch_valid(qa, "independent_lane_b_qa")
                    or not isinstance(dev_dispatch, dict)
                    or qa["agent_id"] == dev_dispatch["agent_id"]
                    or qa["dispatch_id"] == dev_dispatch["dispatch_id"]
                    or qa["dispatch_id"] in dispatch_ids
                    or qa["task_id"] != dev_dispatch["task_id"]
                ):
                    _v5_contract(
                        "fresh independent v5 QA required", "v5_identity_denied"
                    )
                dispatch_ids.add(qa["dispatch_id"])
            if event_type == "TERMINAL_G2_ELIGIBLE":
                terminal_g2_count += 1
                if terminal_g2_count != 1:
                    _v5_contract(
                        "multiple eligible terminals forbidden", "v5_state_denied"
                    )
            states[key] = event_type
        prior = _sha(line[:-1])
    return V5Replay(rows, lines, states, allocations, dispatch_ids)


def _v5_tx_paths(context: Mapping[str, Any], transaction_id: str) -> dict[str, str]:
    if V5_TX_RE.fullmatch(transaction_id) is None:
        _v5_contract("invalid v5 transaction id", "v5_identity_denied")
    result: dict[str, str] = {}
    for key, template in context["v5_artifacts"]["transaction_templates"].items():
        if template.count("{transaction_id}") != 1:
            _v5_contract("v5 transaction template drift")
        path = template.replace("{transaction_id}", transaction_id)
        _v4_parts(path)
        result[key] = path
    if len(set(result.values())) != 4:
        _v5_contract("v5 transaction path collision")
    return result


def _v5_intent_value(
    registry_path: str, before: V4File | None, event: Mapping[str, Any]
) -> dict[str, Any]:
    line = _v5_json_line(event)
    return {
        "schema_name": "lane_b_registry_v5_append_intent.v1",
        "schema_version": 1,
        "record_type": "immutable_registry_append_intent",
        "status": "INTENT_DURABLE",
        "created_at": event["event_at"],
        "transaction_id": event["transaction_id"],
        "nonce": event["nonce"],
        "registry_path": registry_path,
        "registry_preimage": {
            "exists": before is not None,
            "bytes": len(before.data) if before else 0,
            "sha256": before.sha256 if before else _sha(b""),
            "mode": before.mode if before else None,
            "nlink": before.nlink if before else None,
            "device": before.device if before else None,
            "inode": before.inode if before else None,
            "head_event_sha256": (
                _sha(before.data.splitlines(keepends=True)[-1][:-1])
                if before and before.data
                else None
            ),
        },
        "intended_event_hex": line.hex(),
        "intended_event_bytes": len(line),
        "intended_event_sha256_excluding_LF": _sha(line[:-1]),
        "append_bytes_sha256": _sha(line),
        "authorization": _v5_no_authority(),
    }


def _v5_intent(
    root: V4Root, context: Mapping[str, Any], transaction_id: str
) -> tuple[V4File, dict[str, Any]]:
    path = _v5_tx_paths(context, transaction_id)["intent"]
    cap = root.read(path, modes={0o444})
    assert cap is not None
    value = _v5_load_json(cap.data, line_framed=True)
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema_name",
            "schema_version",
            "record_type",
            "status",
            "created_at",
            "transaction_id",
            "nonce",
            "registry_path",
            "registry_preimage",
            "intended_event_hex",
            "intended_event_bytes",
            "intended_event_sha256_excluding_LF",
            "append_bytes_sha256",
            "authorization",
        }
        or value.get("schema_name") != "lane_b_registry_v5_append_intent.v1"
        or value.get("schema_version") != 1
        or value.get("status") != "INTENT_DURABLE"
        or value.get("transaction_id") != transaction_id
        or value.get("authorization") != _v5_no_authority()
    ):
        _v5_tamper("v5 append intent closed identity invalid", "v5_transaction_tamper")
    try:
        line = bytes.fromhex(value["intended_event_hex"])
    except (KeyError, TypeError, ValueError):
        _v5_tamper("v5 append intent event encoding invalid", "v5_transaction_tamper")
    if (
        len(line) != value["intended_event_bytes"]
        or not line.endswith(b"\n")
        or _sha(line[:-1]) != value["intended_event_sha256_excluding_LF"]
        or _sha(line) != value["append_bytes_sha256"]
    ):
        _v5_tamper("v5 append intent event digest invalid", "v5_transaction_tamper")
    event = _v5_load_json(line, line_framed=True)
    if (
        not isinstance(event, dict)
        or event.get("transaction_id") != transaction_id
        or event.get("nonce") != value.get("nonce")
    ):
        _v5_tamper("v5 intent/event identity mismatch", "v5_transaction_tamper")
    return cap, value


def _v5_step_values(
    intent_cap: V4File, intent: Mapping[str, Any], after: V4File
) -> tuple[dict[str, Any], dict[str, Any]]:
    line = bytes.fromhex(intent["intended_event_hex"])
    appended = {
        "schema_name": "lane_b_registry_v5_append_result.v1",
        "schema_version": 1,
        "record_type": "immutable_registry_append_result",
        "status": "APPEND_DURABLE_REPLAY_VALID",
        "created_at": intent["created_at"],
        "transaction_id": intent["transaction_id"],
        "nonce": intent["nonce"],
        "intent": intent_cap.ref(),
        "registry_postimage": {
            "path": after.path,
            "bytes": len(after.data),
            "sha256": after.sha256,
            "mode": after.mode,
            "nlink": after.nlink,
            "device": after.device,
            "inode": after.inode,
            "head_event_sha256": _sha(line[:-1]),
        },
        "authorization": _v5_no_authority(),
    }
    appended_bytes = _v5_json_line(appended)
    commit = {
        "schema_name": "lane_b_registry_v5_append_commit.v1",
        "schema_version": 1,
        "record_type": "immutable_registry_append_commit",
        "status": "COMMITTED_NON_AUTHORIZING",
        "created_at": intent["created_at"],
        "transaction_id": intent["transaction_id"],
        "nonce": intent["nonce"],
        "intent": intent_cap.ref(),
        "appended": {
            "path": "",
            "bytes": len(appended_bytes),
            "sha256": _sha(appended_bytes),
            "mode": "0444",
            "nlink": 1,
            "state": "file",
            "symlink": False,
        },
        "registry_postimage_sha256": after.sha256,
        "event_sha256_excluding_LF": _sha(line[:-1]),
        "authorization": _v5_no_authority(),
    }
    return appended, commit


def _v5_write_registry_suffix(
    root: V4Root,
    context: Mapping[str, Any],
    record: V4File,
    path: str,
    current: V4File | None,
    suffix: bytes,
    *,
    sync: bool = True,
    replay_prefix_bytes: int | None = None,
) -> None:
    if not suffix:
        return
    with root.parent(path) as (parent_fd, name):
        if current is None:
            try:
                fd = os.open(
                    name,
                    os.O_RDWR
                    | os.O_APPEND
                    | os.O_CREAT
                    | os.O_EXCL
                    | os.O_CLOEXEC
                    | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=parent_fd,
                )
            except OSError:
                _v5_tamper("v5 registry create collision/unsafe", "v5_collision_denied")
            expected_size = 0
        else:
            try:
                fd = os.open(
                    name,
                    os.O_RDWR | os.O_APPEND | os.O_CLOEXEC | os.O_NOFOLLOW,
                    dir_fd=parent_fd,
                )
            except OSError:
                _v5_tamper("v5 registry append open unsafe", "v5_path_denied")
            before = os.fstat(fd)
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                stat.S_IMODE(before.st_mode),
                before.st_nlink,
            ) != (current.device, current.inode, len(current.data), 0o600, 1):
                os.close(fd)
                _v5_tamper("v5 registry inode/size/mode CAS drift", "v5_cas_denied")
            chunks: list[bytes] = []
            offset = 0
            while offset < before.st_size:
                chunk = os.pread(fd, min(1024 * 1024, before.st_size - offset), offset)
                if not chunk:
                    os.close(fd)
                    _v5_tamper(
                        "v5 registry final descriptor short read", "v5_cas_denied"
                    )
                chunks.append(chunk)
                offset += len(chunk)
            descriptor_data = b"".join(chunks)
            after_read = os.fstat(fd)
            current_path = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            stable = lambda st: (
                st.st_dev,
                st.st_ino,
                st.st_size,
                stat.S_IMODE(st.st_mode),
                st.st_nlink,
                st.st_mtime_ns,
                st.st_ctime_ns,
            )
            if (
                stable(before) != stable(after_read)
                or (current_path.st_dev, current_path.st_ino)
                != (before.st_dev, before.st_ino)
                or descriptor_data != current.data
                or _sha(descriptor_data) != current.sha256
                or os.pread(fd, 1, before.st_size) != b""
            ):
                os.close(fd)
                _v5_tamper("v5 registry exact-descriptor CAS drift", "v5_cas_denied")
            prefix_size = (
                len(descriptor_data)
                if replay_prefix_bytes is None
                else replay_prefix_bytes
            )
            if not 0 <= prefix_size <= len(descriptor_data):
                os.close(fd)
                _v5_tamper("v5 replay prefix invalid", "v5_cas_denied")
            if prefix_size:
                prefix = descriptor_data[:prefix_size]
                prefix_file = V4File(
                    path,
                    prefix,
                    current.mode,
                    current.nlink,
                    current.device,
                    current.inode,
                    before.st_mtime_ns,
                    before.st_ctime_ns,
                )
                replay = _v5_replay(context, prefix_file, record)
                expected_head = _sha(prefix.splitlines(keepends=True)[-1][:-1])
                if replay.head_sha256 != expected_head:
                    os.close(fd)
                    _v5_tamper("v5 descriptor canonical head drift", "v5_cas_denied")
            expected_size = len(current.data)
        try:
            os.fchmod(fd, 0o600)
            view = memoryview(suffix)
            while view:
                count = os.write(fd, view)
                if count <= 0:
                    _v5_recovery("v5 registry partial append")
                view = view[count:]
            if sync:
                os.fsync(fd)
        finally:
            os.close(fd)
        if sync:
            os.fsync(parent_fd)
        st = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            st.st_size != expected_size + len(suffix)
            or st.st_nlink != 1
            or stat.S_IMODE(st.st_mode) != 0o600
        ):
            _v5_tamper("v5 registry post-append identity mismatch", "v5_cas_denied")


def _v5_finish_transaction(
    root: V4Root,
    context: Mapping[str, Any],
    record: V4File,
    transaction_id: str,
    *,
    crash_after: str | None = None,
) -> dict[str, Any]:
    paths = _v5_tx_paths(context, transaction_id)
    intent_cap, intent = _v5_intent(root, context, transaction_id)
    line = bytes.fromhex(intent["intended_event_hex"])
    pre = intent["registry_preimage"]
    registry_path = intent["registry_path"]
    current = root.read(registry_path, modes={0o600}, optional=True)
    if current is None:
        if pre["exists"]:
            _v5_tamper("v5 registry disappeared after intent", "v5_cas_denied")
        prefix = b""
    else:
        pre_len = pre["bytes"]
        if len(current.data) < pre_len or _sha(current.data[:pre_len]) != pre["sha256"]:
            _v5_tamper("v5 registry diverges from intent preimage", "v5_cas_denied")
        if pre["exists"] and (
            current.device,
            current.inode,
            current.mode,
            current.nlink,
        ) != (pre["device"], pre["inode"], pre["mode"], pre["nlink"]):
            _v5_tamper("v5 registry replaced after intent", "v5_cas_denied")
        prefix = current.data[pre_len:]
    if len(prefix) > len(line) or not line.startswith(prefix):
        _v5_tamper("v5 divergent partial append", "v5_cas_denied")
    if prefix != line:
        _v5_write_registry_suffix(
            root,
            context,
            record,
            registry_path,
            current,
            line[len(prefix) :],
            sync=crash_after != "fsync",
            replay_prefix_bytes=pre["bytes"],
        )
        if crash_after == "fsync":
            _v5_recovery("injected v5 fsync failure")
    after = root.read(registry_path, modes={0o600})
    assert after is not None
    if (
        len(after.data) != pre["bytes"] + len(line)
        or _sha(after.data[: pre["bytes"]]) != pre["sha256"]
        or after.data[pre["bytes"] :] != line
    ):
        _v5_tamper("v5 registry postimage not exact intended append", "v5_cas_denied")
    replay = _v5_replay(context, after, record)
    if replay.head_sha256 != _sha(line[:-1]):
        _v5_tamper("v5 reopen replay head mismatch", "v5_replay_denied")
    if crash_after == "append":
        _v5_recovery("injected v5 crash after durable append")
    appended, commit = _v5_step_values(intent_cap, intent, after)
    existing_appended = root.read(paths["appended"], modes={0o444}, optional=True)
    premature_commit = root.read(paths["commit"], modes={0o444}, optional=True)
    if premature_commit is not None and existing_appended is None:
        _v5_tamper("v5 commit exists without append result", "v5_transaction_tamper")
    appended_bytes = _v5_json_line(appended)
    if existing_appended is None:
        appended_cap = root.create(paths["appended"], appended_bytes, 0o444)
    else:
        if existing_appended.data != appended_bytes:
            _v5_tamper("v5 append-result collision", "v5_transaction_tamper")
        appended_cap = existing_appended
    if crash_after == "step2":
        _v5_recovery("injected v5 crash after append-result")
    commit["appended"] = appended_cap.ref()
    commit_bytes = _v5_json_line(commit)
    if premature_commit is None:
        commit_cap = root.create(paths["commit"], commit_bytes, 0o444)
        idempotent = False
    else:
        if premature_commit.data != commit_bytes:
            _v5_tamper("v5 append-commit collision", "v5_transaction_tamper")
        commit_cap = premature_commit
        idempotent = True
    return {
        "transaction_id": transaction_id,
        "intent": intent_cap.ref(),
        "appended": appended_cap.ref(),
        "commit": commit_cap.ref(),
        "registry": after.ref(),
        "event_sha256_excluding_LF": _sha(line[:-1]),
        "idempotent": idempotent,
    }


def _v5_append_event(
    root: V4Root,
    context: Mapping[str, Any],
    record: V4File,
    registry_path: str,
    event: Mapping[str, Any],
    *,
    allow_absent: bool = False,
    crash_after: str | None = None,
) -> dict[str, Any]:
    _v5_schema(event, context, "event")
    payload = copy.deepcopy(dict(event))
    observed_digest = payload["integrity"].pop("event_payload_sha256")
    if canonical_sha(payload) != observed_digest:
        _v5_contract("v5 event integrity invalid", "v5_schema_invalid")
    line = _v5_json_line(event)
    tx_paths = _v5_tx_paths(context, event["transaction_id"])
    before = root.read(registry_path, modes={0o600}, optional=True)
    if before is None and not allow_absent:
        _v5_contract("active v5 registry missing", "v5_state_denied")
    intent_expected = _v5_intent_value(registry_path, before, event)
    existing = root.read(tx_paths["intent"], modes={0o444}, optional=True)
    if existing is not None:
        actual = _v5_load_json(existing.data, line_framed=True)
        if actual != intent_expected and not (
            allow_absent and event["event_type"] == "MIGRATION_GENESIS"
        ):
            _v5_tamper("v5 transaction intent collision", "v5_transaction_tamper")
        return _v5_finish_transaction(
            root, context, record, event["transaction_id"], crash_after=crash_after
        )
    if before is not None and before.data.endswith(line):
        if not (
            allow_absent
            and event["event_type"] == "MIGRATION_GENESIS"
            and before.data == line
        ):
            _v5_tamper(
                "v5 registry event lacks immutable intent", "v5_transaction_tamper"
            )
        intent_expected = _v5_intent_value(registry_path, None, event)
    root.create(tx_paths["intent"], _v5_json_line(intent_expected), 0o444)
    if crash_after == "intent":
        _v5_recovery("injected v5 crash after intent")
    if crash_after == "partial":
        current = root.read(registry_path, modes={0o600}, optional=True)
        amount = max(1, len(line) // 2)
        _v5_write_registry_suffix(
            root, context, record, registry_path, current, line[:amount]
        )
        _v5_recovery("injected exact v5 partial append")
    return _v5_finish_transaction(
        root, context, record, event["transaction_id"], crash_after=crash_after
    )


def _v5_verify_transaction_exact(
    root: V4Root,
    context: Mapping[str, Any],
    record: V4File,
    registry: V4File,
    event_index: int,
    event: Mapping[str, Any],
    line: bytes,
) -> None:
    paths = _v5_tx_paths(context, event["transaction_id"])
    captures = {
        key: root.read(path, modes={0o444}, optional=True)
        for key, path in paths.items()
        if key != "terminal_failure"
    }
    if any(cap is None for cap in captures.values()):
        _v5_recovery("v5 registry event has incomplete immutable WAL")
    intent_cap = captures["intent"]
    appended_cap = captures["appended"]
    commit_cap = captures["commit"]
    assert (
        intent_cap is not None and appended_cap is not None and commit_cap is not None
    )
    prior_lines = registry.data.splitlines(keepends=True)[:event_index]
    before_data = b"".join(prior_lines)
    before = None
    if event_index:
        before = V4File(
            registry.path,
            before_data,
            registry.mode,
            registry.nlink,
            registry.device,
            registry.inode,
        )
    expected_intent = _v5_intent_value(registry.path, before, event)
    actual_intent = _v5_load_json(intent_cap.data, line_framed=True)
    if actual_intent != expected_intent:
        _v5_tamper("v5 immutable intent/preimage drift", "v5_transaction_tamper")
    after = V4File(
        registry.path,
        before_data + line,
        registry.mode,
        registry.nlink,
        registry.device,
        registry.inode,
    )
    appended, commit = _v5_step_values(intent_cap, actual_intent, after)
    if appended_cap.data != _v5_json_line(appended):
        _v5_tamper("v5 immutable append-result drift", "v5_transaction_tamper")
    commit["appended"] = appended_cap.ref()
    if commit_cap.data != _v5_json_line(commit):
        _v5_tamper("v5 immutable append-commit drift", "v5_transaction_tamper")


def _v5_verify_all_transactions(
    root: V4Root,
    context: Mapping[str, Any],
    record: V4File,
    registry: V4File,
    replay: V5Replay,
) -> None:
    for index, (event, line) in enumerate(zip(replay.rows, replay.lines)):
        _v5_verify_transaction_exact(
            root, context, record, registry, index, event, line
        )


def v5_expected_migration_audit(
    context: Mapping[str, Any],
    record: V4File,
    registry: V4File,
    frozen_v4: V4File,
    agent_id: str,
    created_at: str,
) -> dict[str, Any]:
    """Build, but never publish, the independent migration audit value."""
    return {
        "schema_name": "lane_b_attempt_registry_v5_migration_audit.v1",
        "schema_version": 1,
        "record_type": "immutable_independent_v5_migration_audit",
        "status": "PASS",
        "created_at": created_at,
        "auditor": {
            "agent_id": agent_id,
            "role": "independent_registry_migration_qa",
            "independent_from_implementation_and_migration": True,
        },
        "migration_record": record.ref(),
        "v5_registry_genesis": registry.ref(),
        "source_v4_registry": frozen_v4.ref(),
        "source_v4_unchanged": True,
        "closed_schema_digests_match": True,
        "negative_matrix_preflight_passed": True,
        "authorization": _v5_no_authority(),
    }


def _v5_audit(
    root: V4Root,
    context: Mapping[str, Any],
    path: str,
    record: V4File,
    registry: V4File,
    frozen_v4: V4File,
    *,
    optional: bool = False,
) -> tuple[V4File, dict[str, Any]] | None:
    cap = root.read(path, modes={0o444}, optional=optional)
    if cap is None:
        return None
    value = _v5_load_json(cap.data, line_framed=True)
    if not isinstance(value, dict):
        _v5_contract("v5 migration audit must be object", "v5_schema_invalid")
    _v5_schema(value, context, "migration_audit")
    if (
        value["migration_record"] != record.ref()
        or value["v5_registry_genesis"] != registry.ref()
        or value["source_v4_registry"] != frozen_v4.ref()
        or not value["auditor"]["agent_id"]
        or value["auditor"]["agent_id"] == "same_spec_parent"
        or value["authorization"] != _v5_no_authority()
    ):
        _v5_tamper("v5 migration audit semantic/identity drift")
    replay = _v5_replay(context, registry, record)
    if len(replay.rows) != 1:
        _v5_contract("migration audit binds genesis only", "v5_state_denied")
    return cap, value


def _v5_activation_value(
    record: V4File,
    audit: V4File,
    registry: V4File,
    frozen_v4: V4File,
    created_at: str,
) -> dict[str, Any]:
    return {
        "schema_name": "lane_b_attempt_registry_v5_activation.v1",
        "schema_version": 1,
        "record_type": "immutable_single_generation_activation",
        "status": "V5_CONTROL_ACTIVE",
        "created_at": created_at,
        "migration_record": record.ref(),
        "migration_audit": audit.ref(),
        "v5_registry": registry.ref(),
        "v4_registry_frozen": frozen_v4.ref(),
        "v4_mutation_enabled": False,
        "next_attempt_id": V5_ATTEMPT_ID,
        "authorization": _v5_no_authority(),
    }


def _v5_active(
    root: V4Root, context: Mapping[str, Any], paths: Mapping[str, str]
) -> tuple[V4File, dict[str, Any], V4File, V5Replay, V4File, V4File]:
    frozen, _ = _v5_validate_frozen_v4(root, context, paths)
    record_item = _v5_record(root, context, paths["record"], frozen)
    if record_item is None:
        _v5_contract("v5 migration record missing", "v5_state_denied")
    record, record_value = record_item
    registry = root.read(paths["registry"], modes={0o600})
    assert registry is not None
    replay = _v5_replay(context, registry, record)
    _v5_verify_all_transactions(root, context, record, registry, replay)
    genesis = V4File(
        registry.path,
        replay.lines[0],
        registry.mode,
        registry.nlink,
        registry.device,
        registry.inode,
    )
    audit_item = _v5_audit(
        root, context, paths["audit"], record, genesis, frozen, optional=True
    )
    if audit_item is None:
        _v5_contract("v5 independent migration audit missing", "v5_state_denied")
    audit, _audit_value = audit_item
    activation = root.read(paths["activation"], modes={0o444})
    assert activation is not None
    value = _v5_load_json(activation.data, line_framed=True)
    if not isinstance(value, dict):
        _v5_contract("v5 activation must be object", "v5_schema_invalid")
    _v5_schema(value, context, "activation")
    expected = _v5_activation_value(record, audit, genesis, frozen, value["created_at"])
    if value != expected:
        _v5_tamper("v5 activation identity drift")
    return record, record_value, registry, replay, audit, activation


def _v5_migration_commit(
    root: V4Root,
    context: Mapping[str, Any],
    paths: Mapping[str, str],
    args: argparse.Namespace,
) -> dict[str, Any]:
    frozen, _ = _v5_validate_frozen_v4(root, context, paths)
    record_item = _v5_record(root, context, paths["record"], frozen, optional=True)
    registry_before = root.read(paths["registry"], modes={0o600}, optional=True)
    if record_item is None and registry_before is not None:
        _v5_tamper("v5 registry exists without migration record")
    wrote_record = False
    if record_item is None:
        created_at = _v5_now(args.v5_event_at)
        value = _v5_expected_record(context, frozen, created_at)
        _v5_schema(value, context, "migration_record")
        cap = root.create(paths["record"], _v5_json_line(value), 0o444)
        record_item = (cap, value)
        wrote_record = True
        if args.v5_crash_after == "migration-record":
            _v5_recovery("injected v5 crash after migration record")
    record, record_value = record_item
    genesis = _v5_genesis(context, record, record_value)
    line = _v5_json_line(genesis)
    if registry_before is not None and registry_before.data.startswith(line):
        replay = _v5_replay(context, registry_before, record)
        _v5_verify_all_transactions(root, context, record, registry_before, replay)
        return {
            "result": "ALREADY_COMMITTED_EXACT_WITH_VALID_TAIL",
            "record": record.ref(),
            "registry": registry_before.ref(),
            "registry_event_count": len(replay.rows),
            "lifecycle_event_count": len(replay.rows) - 1,
            **_v5_no_authority(),
        }
    tx = _v5_append_event(
        root,
        context,
        record,
        paths["registry"],
        genesis,
        allow_absent=True,
        crash_after=(
            args.v5_crash_after
            if args.v5_crash_after in {"intent", "partial", "fsync", "append", "step2"}
            else None
        ),
    )
    registry = root.read(paths["registry"], modes={0o600})
    assert registry is not None
    replay = _v5_replay(context, registry, record)
    return {
        "result": (
            "MIGRATION_COMMITTED_V5_INACTIVE_PENDING_INDEPENDENT_AUDIT"
            if wrote_record
            else "ALREADY_COMMITTED_EXACT"
        ),
        "record": record.ref(),
        "registry": registry.ref(),
        "registry_event_count": len(replay.rows),
        "lifecycle_event_count": len(replay.rows) - 1,
        "transaction": tx,
        **_v5_no_authority(),
    }


def _v5_activate(
    root: V4Root,
    context: Mapping[str, Any],
    paths: Mapping[str, str],
    args: argparse.Namespace,
) -> dict[str, Any]:
    frozen, _ = _v5_validate_frozen_v4(root, context, paths)
    record_item = _v5_record(root, context, paths["record"], frozen)
    if record_item is None:
        _v5_contract("v5 migration record missing", "v5_state_denied")
    record, _value = record_item
    registry = root.read(paths["registry"], modes={0o600})
    assert registry is not None
    replay = _v5_replay(context, registry, record)
    _v5_verify_all_transactions(root, context, record, registry, replay)
    if len(replay.rows) != 1:
        _v5_contract("v5 activation requires genesis-only registry", "v5_state_denied")
    audit_item = _v5_audit(
        root, context, paths["audit"], record, registry, frozen, optional=True
    )
    if audit_item is None:
        _v5_contract("v5 independent migration audit missing", "v5_state_denied")
    audit, _audit_value = audit_item
    if root.exists(paths["activation"]):
        _v5_tamper("duplicate or divergent v5 activation", "v5_collision_denied")
    created_at = _v5_now(args.v5_event_at)
    value = _v5_activation_value(record, audit, registry, frozen, created_at)
    _v5_schema(value, context, "activation")
    activation = root.create(paths["activation"], _v5_json_line(value), 0o444)
    return {
        "result": "V5_CONTROL_ACTIVE",
        "activation": activation.ref(),
        "next_attempt_id": V5_ATTEMPT_ID,
        **_v5_no_authority(),
    }


def _v5_event_precondition(registry: V4File, event: Mapping[str, Any]) -> str:
    return canonical_sha(
        {
            "registry": {
                "bytes": len(registry.data),
                "sha256": registry.sha256,
                "head": _sha(registry.data.splitlines(keepends=True)[-1][:-1]),
            },
            "event_type": event["event_type"],
            "attempt_uid": event["attempt_uid"],
            "attempt_state_before": event["attempt_state_before"],
            "persisted_state_after": event["persisted_state_after"],
            "derived_paths": event["derived_paths"],
            "evidence": {
                key: event.get(key)
                for key in (
                    "dev_dispatch_identity",
                    "qa_dispatch_identity",
                    "producer_identity",
                    "qa_result_identity",
                    "readiness_identity",
                    "receipt_identity",
                    "timing_identity",
                    "provider_verification_identity",
                    "terminal_marker_identity",
                    "terminal_failure_identity",
                )
            },
        }
    )


def v5_transition_precondition(registry: V4File, event: Mapping[str, Any]) -> str:
    """Public deterministic helper for parent-created v5 event requests."""
    return _v5_event_precondition(registry, event)


def v5_expected_attempt_event(
    context: Mapping[str, Any],
    registry: V4File,
    replay: V5Replay,
    event_type: str,
    event_at: str,
    transaction_id: str,
    nonce: str,
    **fields: Any,
) -> dict[str, Any]:
    """Build, but never publish, one closed v5 attempt event."""
    key = (V5_ATTEMPT_KIND, V5_ATTEMPT_ID)
    current = replay.states.get(key)
    if event_type == "ALLOCATED":
        before = "NONE"
    else:
        before = current
    event = {
        "schema_version": 5,
        "record_type": "lane_b_attempt_identity_registry_v5_event",
        "event_sequence": len(replay.rows) + 1,
        "previous_event_sha256": replay.head_sha256,
        "event_type": event_type,
        "attempt_kind": V5_ATTEMPT_KIND,
        "attempt_id": V5_ATTEMPT_ID,
        "attempt_sequence": V5_ATTEMPT_SEQUENCE,
        "attempt_uid": V5_ATTEMPT_UID,
        "transaction_id": transaction_id,
        "nonce": nonce,
        "identity": _v5_attempt_identity(),
        "owner_role": "same_spec_parent",
        "derived_paths": _v5_derive_paths(context),
        "migration_identity": None,
        "dev_dispatch_identity": None,
        "qa_dispatch_identity": None,
        "producer_identity": None,
        "qa_result_identity": None,
        "readiness_identity": None,
        "receipt_identity": None,
        "timing_identity": None,
        "provider_verification_identity": None,
        "terminal_marker_identity": None,
        "terminal_failure_identity": None,
        "precondition_manifest_sha256": "0" * 64,
        "event_at": event_at,
        "outcome": {
            "ALLOCATED": "none",
            "STARTED": "started",
            "EVIDENCE_SEALED": "evidence_sealed",
            "PROVIDER_VERIFIED": "provider_verified",
            "TERMINAL_G2_ELIGIBLE": "eligible_for_separate_g2_only",
            "TERMINAL_NO_AUTHORITY": "no_authority",
        }.get(event_type, "invalid"),
        "authorization": _v5_no_authority(),
        "integrity": {"canonicalization": V5_INTEGRITY_LANGUAGE},
        "attempt_state_before": before,
        "persisted_state_after": event_type,
    }
    event.update(copy.deepcopy(fields))
    event["precondition_manifest_sha256"] = _v5_event_precondition(registry, event)
    return _v5_with_integrity(event)


def _v5_allocate(
    root: V4Root,
    context: Mapping[str, Any],
    paths: Mapping[str, str],
    args: argparse.Namespace,
) -> dict[str, Any]:
    record, _rv, registry, replay, _audit, _activation = _v5_active(
        root, context, paths
    )
    if args.attempt_id:
        _v5_contract("caller-selected v5 attempt token forbidden", "v5_identity_denied")
    if args.attempt_kind != V5_ATTEMPT_KIND:
        _v5_contract("only GATE_REPAIR_HB3 allocation enabled", "v5_state_denied")
    if replay.allocations or any(
        state in V5_TERMINAL_STATES for state in replay.states.values()
    ):
        _v5_contract("v5 admits exactly one logical allocation", "v5_state_denied")
    derived = _v5_derive_paths(context)
    for path in derived.values():
        if root.exists(path):
            _v5_tamper(f"v5 derived path collision: {path}", "v5_collision_denied")
    event = v5_expected_attempt_event(
        context,
        registry,
        replay,
        "ALLOCATED",
        _v5_now(args.v5_event_at),
        os.urandom(16).hex(),
        os.urandom(16).hex(),
    )
    hypothetical = V4File(
        registry.path,
        registry.data + _v5_json_line(event),
        registry.mode,
        registry.nlink,
        registry.device,
        registry.inode,
    )
    _v5_replay(context, hypothetical, record)
    tx = _v5_append_event(
        root,
        context,
        record,
        paths["registry"],
        event,
        crash_after=args.v5_crash_after,
    )
    return {
        "result": "ALLOCATED",
        "attempt_id": V5_ATTEMPT_ID,
        "attempt_sequence": V5_ATTEMPT_SEQUENCE,
        "attempt_uid": V5_ATTEMPT_UID,
        "derived_paths": derived,
        "transaction": tx,
        **_v5_no_authority(),
    }


def _v5_read_event(
    root: V4Root, path: str, context: Mapping[str, Any]
) -> dict[str, Any]:
    cap = root.read(path, modes={0o444, 0o600, 0o644})
    assert cap is not None
    value = _v5_load_json(cap.data, line_framed=True)
    if not isinstance(value, dict):
        _v5_contract("v5 transition event must be object", "v5_schema_invalid")
    _v5_schema(value, context, "event")
    payload = copy.deepcopy(value)
    observed = payload["integrity"].pop("event_payload_sha256")
    if canonical_sha(payload) != observed:
        _v5_contract("v5 transition event digest invalid", "v5_schema_invalid")
    return value


def _v5_transition_event(
    root: V4Root,
    context: Mapping[str, Any],
    paths: Mapping[str, str],
    record: V4File,
    registry: V4File,
    replay: V5Replay,
    event: Mapping[str, Any],
    *,
    expected_type: str,
    crash_after: str | None = None,
) -> dict[str, Any]:
    if event["event_type"] != expected_type:
        _v5_contract(f"{expected_type} event required", "v5_state_denied")
    line = _v5_json_line(event)
    if replay.lines and replay.lines[-1] == line:
        tx = _v5_finish_transaction(root, context, record, event["transaction_id"])
        return {"result": "ALREADY_APPENDED_EXACT", "transaction": tx}
    if (
        event["event_sequence"] != len(replay.rows) + 1
        or event["previous_event_sha256"] != replay.head_sha256
        or event["precondition_manifest_sha256"]
        != _v5_event_precondition(registry, event)
    ):
        _v5_tamper("stale v5 transition CAS/precondition", "v5_cas_denied")
    hypothetical = V4File(
        registry.path,
        registry.data + line,
        registry.mode,
        registry.nlink,
        registry.device,
        registry.inode,
    )
    _v5_replay(context, hypothetical, record)
    tx = _v5_append_event(
        root,
        context,
        record,
        paths["registry"],
        event,
        crash_after=crash_after,
    )
    return {"result": "TRANSITION_APPENDED", "transaction": tx}


def _v5_artifact_json(
    root: V4Root,
    ref: Mapping[str, Any],
    expected_path: str,
    label: str,
) -> tuple[V4File, dict[str, Any]]:
    if not isinstance(ref, dict) or ref.get("path") != expected_path:
        _v5_contract(f"{label} path/composite mismatch", "v5_identity_denied")
    cap = root.read(expected_path, modes={0o444})
    assert cap is not None
    _v5_ref_equal(cap, ref, label)
    value = _v5_load_json(cap.data, line_framed=True)
    if not isinstance(value, dict):
        _v5_contract(f"{label} must be object", "v5_schema_invalid")
    return cap, value


def _v5_test_totals(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("collected") == 402
        and value.get("passed") == 402
        and value.get("failed") == 0
    )


def _v5_refs_by_path(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list) or len(value) != 2:
        _v5_contract("v5 implementation manifest must contain exactly two refs")
    result: dict[str, dict[str, Any]] = {}
    for ref in value:
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
            _v5_contract("v5 implementation manifest ref invalid")
        if ref["path"] in result:
            _v5_contract("duplicate v5 implementation manifest path")
        result[ref["path"]] = ref
    return result


def _v5_validate_seal_evidence(
    root: V4Root,
    context: Mapping[str, Any],
    event: Mapping[str, Any],
    replay: V5Replay,
    validation_time: str,
    *,
    verify_live_implementation: bool = True,
) -> dict[str, Any]:
    paths = _v5_derive_paths(context)
    started = next(
        row for row in reversed(replay.rows) if row.get("event_type") == "STARTED"
    )
    if event["dev_dispatch_identity"] != started["dev_dispatch_identity"]:
        _v5_contract("seal Dev dispatch lineage drift", "v5_identity_denied")
    qa_dispatch = event["qa_dispatch_identity"]
    if (
        not _v5_dispatch_valid(qa_dispatch, "independent_lane_b_qa")
        or qa_dispatch["agent_id"] == event["dev_dispatch_identity"]["agent_id"]
        or qa_dispatch["task_id"] != event["dev_dispatch_identity"]["task_id"]
    ):
        _v5_contract(
            "seal requires different-agent independent QA", "v5_identity_denied"
        )
    producer_cap, producer = _v5_artifact_json(
        root, event["producer_identity"], paths["dev_report"], "v5 producer"
    )
    qa_cap, qa = _v5_artifact_json(
        root, event["qa_result_identity"], paths["qa_report"], "v5 independent QA"
    )
    readiness_cap, readiness = _v5_artifact_json(
        root, event["readiness_identity"], paths["readiness"], "v5 readiness"
    )
    receipt_cap, receipt = _v5_artifact_json(
        root, event["receipt_identity"], paths["receipt"], "v5 receipt"
    )
    identity = _v5_attempt_identity()
    expected_changed = sorted(context["scope_and_ownership"]["allowed_modified_paths"])
    producer_required = {
        "schema_name",
        "schema_version",
        "record_type",
        "status",
        "created_at",
        "identity",
        "started_event_sha256",
        "dev_dispatch",
        "ticket_sha256",
        "context_sha256",
        "implementation_files",
        "changed_paths",
        "tests",
        "authorization",
    }
    qa_required = {
        "schema_name",
        "schema_version",
        "record_type",
        "status",
        "verdict",
        "started_at",
        "finalized_at",
        "identity",
        "started_event_sha256",
        "qa_dispatch",
        "qa_agent_id",
        "dev_agent_id",
        "independent",
        "producer",
        "observed_implementation_files",
        "tests",
        "authorization",
    }
    readiness_required = {
        "schema_name",
        "schema_version",
        "record_type",
        "status",
        "created_at",
        "identity",
        "producer",
        "qa",
        "all_inputs_exact",
        "authorization",
    }
    receipt_required = {
        "schema_name",
        "schema_version",
        "record_type",
        "status",
        "created_at",
        "identity",
        "producer",
        "qa",
        "readiness",
        "authorization",
    }
    if (
        set(producer) != producer_required
        or producer.get("status") != "PASS"
        or producer.get("identity") != identity
        or producer.get("dev_dispatch") != event["dev_dispatch_identity"]
        or producer.get("ticket_sha256") != V5_TICKET_SHA256
        or producer.get("context_sha256") != V5_CONTEXT_SHA256
        or sorted(producer.get("changed_paths", [])) != expected_changed
        or not _v5_test_totals(producer.get("tests"))
        or producer.get("authorization") != _v5_no_authority()
    ):
        _v5_contract("v5 producer evidence invalid", "v5_evidence_denied")
    if (
        set(qa) != qa_required
        or qa.get("status") != "PASS"
        or qa.get("verdict") != "PASS"
        or qa.get("identity") != identity
        or qa.get("qa_dispatch") != qa_dispatch
        or qa.get("qa_agent_id") != qa_dispatch["agent_id"]
        or qa.get("dev_agent_id") != event["dev_dispatch_identity"]["agent_id"]
        or qa.get("independent") is not True
        or qa.get("producer") != producer_cap.ref()
        or not _v5_test_totals(qa.get("tests"))
        or qa.get("authorization") != _v5_no_authority()
    ):
        _v5_contract("v5 independent QA evidence invalid", "v5_evidence_denied")
    dev_refs = _v5_refs_by_path(producer["implementation_files"])
    qa_refs = _v5_refs_by_path(qa["observed_implementation_files"])
    if set(dev_refs) != set(expected_changed) or dev_refs != qa_refs:
        _v5_contract("v5 Dev/QA implementation manifest mismatch")
    if verify_live_implementation:
        for path, expected in dev_refs.items():
            cap = root.read(path, modes={int(expected["mode"], 8)})
            assert cap is not None
            _v5_ref_equal(cap, expected, f"mutable provider {path}")
    if (
        set(readiness) != readiness_required
        or readiness.get("status") != "READY_FOR_EVIDENCE_SEAL_ONLY"
        or readiness.get("identity") != identity
        or readiness.get("producer") != producer_cap.ref()
        or readiness.get("qa") != qa_cap.ref()
        or readiness.get("all_inputs_exact") is not True
        or readiness.get("authorization") != _v5_no_authority()
    ):
        _v5_contract("v5 readiness evidence invalid", "v5_evidence_denied")
    if (
        set(receipt) != receipt_required
        or receipt.get("status") != "RECEIPT_EXACT_NON_AUTHORIZING"
        or receipt.get("identity") != identity
        or receipt.get("producer") != producer_cap.ref()
        or receipt.get("qa") != qa_cap.ref()
        or receipt.get("readiness") != readiness_cap.ref()
        or receipt.get("authorization") != _v5_no_authority()
    ):
        _v5_contract("v5 receipt evidence invalid", "v5_evidence_denied")
    started_at = _timestamp(started["event_at"], "v5_evidence_denied")
    producer_at = _timestamp(producer["created_at"], "v5_evidence_denied")
    qa_started = _timestamp(qa["started_at"], "v5_evidence_denied")
    qa_final = _timestamp(qa["finalized_at"], "v5_evidence_denied")
    readiness_at = _timestamp(readiness["created_at"], "v5_evidence_denied")
    receipt_at = _timestamp(receipt["created_at"], "v5_evidence_denied")
    validation_at = _timestamp(validation_time, "v5_evidence_denied")
    if not (
        started_at
        <= producer_at
        <= qa_started
        <= qa_final
        <= readiness_at
        <= receipt_at
        <= validation_at + dt.timedelta(seconds=5)
    ):
        _v5_contract("v5 evidence timestamp order/future skew invalid")
    qa_age = (validation_at - qa_final).total_seconds()
    if not 0 <= qa_age <= 3600:
        _v5_contract("v5 QA evidence outside one-hour freshness window")
    started_sha = _sha(_v5_json_line(started)[:-1])
    if (
        producer.get("started_event_sha256") != started_sha
        or qa.get("started_event_sha256") != started_sha
    ):
        _v5_contract("v5 started-event evidence link drift")
    return {
        "producer": producer_cap.ref(),
        "qa": qa_cap.ref(),
        "readiness": readiness_cap.ref(),
        "receipt": receipt_cap.ref(),
        "qa_age_seconds": qa_age,
        "implementation_files": dev_refs,
    }


def _v5_create_artifact(
    root: V4Root,
    context: Mapping[str, Any],
    family: str,
    path: str,
    value: Mapping[str, Any],
) -> V4File:
    _v5_schema(value, context, family)
    data = _v5_json_line(value)
    existing = root.read(path, modes={0o444}, optional=True)
    if existing is not None:
        if existing.data != data:
            _v5_tamper(f"v5 {family} collision/replacement", "v5_collision_denied")
        return existing
    return root.create(path, data, 0o444)


def _v5_start(
    root: V4Root,
    context: Mapping[str, Any],
    paths: Mapping[str, str],
    args: argparse.Namespace,
) -> dict[str, Any]:
    record, _rv, registry, replay, _audit, _activation = _v5_active(
        root, context, paths
    )
    if args.attempt_id != V5_ATTEMPT_ID:
        _v5_contract("--attempt-id a000017 required", "v5_identity_denied")
    expected_path = _v5_derive_paths(context)["started_event_input"]
    if args.event_input != expected_path:
        _v5_contract("STARTED event input must use allocated derived path")
    event = _v5_read_event(root, expected_path, context)
    result = _v5_transition_event(
        root,
        context,
        paths,
        record,
        registry,
        replay,
        event,
        expected_type="STARTED",
        crash_after=args.v5_crash_after,
    )
    return {**result, "state": "STARTED", **_v5_no_authority()}


def _v5_timing_value(
    identity: Mapping[str, Any],
    validation_time: str,
    event: Mapping[str, Any],
    event_sha: str,
    registry: V4File,
    start_ns: int,
    end_ns: int,
    wall_span_microseconds: int,
) -> dict[str, Any]:
    duration = end_ns - start_ns
    within = 0 <= duration <= 4_000_000_000
    wall_ok = 0 <= wall_span_microseconds <= 4_000_000
    return {
        "schema_name": "lane_b_registry_v5_evidence_seal_timing.v1",
        "schema_version": 1,
        "record_type": "immutable_source_owned_protected_interval_receipt",
        "status": "PASS" if within and wall_ok else "FAIL",
        "created_at": _v5_now(),
        "identity": dict(identity),
        "validation_time": validation_time,
        "evidence_sealed_event_at": event["event_at"],
        "start_monotonic_ns": start_ns,
        "end_monotonic_ns": end_ns,
        "duration_ns": duration,
        "limit_ns": 4_000_000_000,
        "within_budget": within,
        "wall_span_microseconds": wall_span_microseconds,
        "wall_span_within_four_seconds": wall_ok,
        "clock_scope": (
            "inside registry-v5-seal: immediately before validation_time capture "
            "through durable EVIDENCE_SEALED fsync, reopen, and full replay"
        ),
        "outer_process_or_provider_verification_included": False,
        "evidence_sealed_event_sha256": event_sha,
        "registry_postimage": registry.ref(),
        "authorization": _v5_no_authority(),
    }


def _v5_terminalize(
    root: V4Root,
    context: Mapping[str, Any],
    paths: Mapping[str, str],
    record: V4File,
    registry: V4File,
    replay: V5Replay,
    *,
    failure_code: str,
    message: str,
    preserved: Sequence[Mapping[str, Any]] = (),
    event_at: str | None = None,
) -> dict[str, Any]:
    key = (V5_ATTEMPT_KIND, V5_ATTEMPT_ID)
    state = replay.states.get(key)
    if state == "TERMINAL_NO_AUTHORITY":
        return {"result": "ALREADY_TERMINAL_NO_AUTHORITY", "state": state}
    if state not in V5_NONTERMINAL_STATES:
        _v5_contract("terminal failure requires exact nonterminal predecessor")
    failure_path = _v5_derive_paths(context)["terminal_failure"]
    failure = {
        "schema_name": "lane_b_registry_v5_terminal_failure.v1",
        "schema_version": 1,
        "record_type": "immutable_terminal_no_authority_evidence",
        "status": "TERMINAL_NO_AUTHORITY",
        "created_at": _v5_now(event_at),
        "identity": _v5_attempt_identity(),
        "failure_code": failure_code,
        "message_sha256": _sha(message.encode()),
        "preserved_registry": registry.ref(),
        "preserved_artifacts": [dict(item) for item in preserved],
        "authorization": _v5_no_authority(),
    }
    failure_cap = _v5_create_artifact(
        root, context, "terminal_failure", failure_path, failure
    )
    current_row = next(
        row for row in reversed(replay.rows) if row.get("attempt_id") == V5_ATTEMPT_ID
    )
    event = v5_expected_attempt_event(
        context,
        registry,
        replay,
        "TERMINAL_NO_AUTHORITY",
        failure["created_at"],
        _sha(("v5-failure-tx:" + failure_cap.sha256).encode())[:32],
        _sha(("v5-failure-nonce:" + failure_cap.sha256).encode())[:32],
        dev_dispatch_identity=current_row.get("dev_dispatch_identity"),
        qa_dispatch_identity=current_row.get("qa_dispatch_identity"),
        producer_identity=current_row.get("producer_identity"),
        qa_result_identity=current_row.get("qa_result_identity"),
        readiness_identity=current_row.get("readiness_identity"),
        receipt_identity=current_row.get("receipt_identity"),
        timing_identity=current_row.get("timing_identity"),
        provider_verification_identity=current_row.get(
            "provider_verification_identity"
        ),
        terminal_marker_identity=current_row.get("terminal_marker_identity"),
        terminal_failure_identity=failure_cap.ref(),
    )
    transition = _v5_transition_event(
        root,
        context,
        paths,
        record,
        registry,
        replay,
        event,
        expected_type="TERMINAL_NO_AUTHORITY",
    )
    return {
        "result": "TERMINAL_NO_AUTHORITY",
        "state": "TERMINAL_NO_AUTHORITY",
        "terminal_failure": failure_cap.ref(),
        "transition": transition,
    }


def _v5_seal(
    root: V4Root,
    context: Mapping[str, Any],
    paths: Mapping[str, str],
    args: argparse.Namespace,
) -> dict[str, Any]:
    record, _rv, registry, replay, _audit, _activation = _v5_active(
        root, context, paths
    )
    if args.attempt_id != V5_ATTEMPT_ID:
        _v5_contract("--attempt-id a000017 required", "v5_identity_denied")
    expected_path = _v5_derive_paths(context)["evidence_sealed_event_input"]
    if args.event_input != expected_path:
        _v5_contract("EVIDENCE_SEALED event input must use allocated derived path")
    existing_event = _v5_read_event(root, expected_path, context)
    timing_path = _v5_derive_paths(context)["timing_receipt"]
    timing_existing = root.read(timing_path, modes={0o444}, optional=True)
    if (
        replay.states.get((V5_ATTEMPT_KIND, V5_ATTEMPT_ID)) == "EVIDENCE_SEALED"
        and replay.lines[-1] == _v5_json_line(existing_event)
        and timing_existing is not None
    ):
        timing_cap, timing = _v5_timing_receipt(root, context, registry, replay)
        if timing["status"] != "PASS":
            _v5_contract("idempotent seal has non-PASS timing receipt")
        return {
            "result": "ALREADY_EVIDENCE_SEALED_EXACT",
            "state": "EVIDENCE_SEALED",
            "protected_duration_ns": timing["duration_ns"],
            "timing_receipt": timing_cap.ref(),
            **_v5_no_authority(),
        }

    # The source-owned protected interval begins only after all interactive work
    # has completed, immediately before the first evidence validation read.
    real_start_ns = time.monotonic_ns()
    wall_start = dt.datetime.now(dt.timezone.utc)
    validation_time = wall_start.isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )
    event = _v5_read_event(root, expected_path, context)
    evidence = _v5_validate_seal_evidence(root, context, event, replay, validation_time)
    transition = _v5_transition_event(
        root,
        context,
        paths,
        record,
        registry,
        replay,
        event,
        expected_type="EVIDENCE_SEALED",
        crash_after=(
            args.v5_crash_after
            if args.v5_crash_after in {"intent", "partial", "fsync", "append", "step2"}
            else None
        ),
    )
    registry_after = root.read(paths["registry"], modes={0o600})
    assert registry_after is not None
    replay_after = _v5_replay(context, registry_after, record)
    if replay_after.states[(V5_ATTEMPT_KIND, V5_ATTEMPT_ID)] != "EVIDENCE_SEALED":
        _v5_tamper("durable v5 seal replay state mismatch")
    real_end_ns = time.monotonic_ns()
    wall_end = dt.datetime.now(dt.timezone.utc)
    if args.v5_test_duration_ns is None:
        start_ns, end_ns = real_start_ns, real_end_ns
    else:
        start_ns, end_ns = 1_000_000, 1_000_000 + args.v5_test_duration_ns
    wall_span_us = max(0, int((wall_end - wall_start).total_seconds() * 1_000_000))
    if args.v5_test_duration_ns is not None:
        wall_span_us = max(0, args.v5_test_duration_ns // 1000)
    event_sha = transition["transaction"]["event_sha256_excluding_LF"]
    timing = _v5_timing_value(
        _v5_attempt_identity(),
        validation_time,
        event,
        event_sha,
        registry_after,
        start_ns,
        end_ns,
        wall_span_us,
    )
    timing_cap = _v5_create_artifact(
        root,
        context,
        "timing_receipt",
        _v5_derive_paths(context)["timing_receipt"],
        timing,
    )
    if args.v5_crash_after == "timing-receipt":
        _v5_recovery("injected crash after v5 timing receipt")
    if timing["status"] != "PASS":
        result = _v5_terminalize(
            root,
            context,
            paths,
            record,
            registry_after,
            replay_after,
            failure_code="timing_budget_fail",
            message="v5 protected evidence interval exceeded four seconds",
            preserved=[timing_cap.ref()],
        )
        return {**result, "timing_receipt": timing_cap.ref(), **_v5_no_authority()}
    return {
        "result": "EVIDENCE_SEALED_WITHIN_PROTECTED_BUDGET",
        "state": "EVIDENCE_SEALED",
        "protected_duration_ns": timing["duration_ns"],
        "timing_receipt": timing_cap.ref(),
        "transition": transition,
        **_v5_no_authority(),
    }


def _v5_timing_receipt(
    root: V4Root,
    context: Mapping[str, Any],
    registry: V4File,
    replay: V5Replay,
) -> tuple[V4File, dict[str, Any]]:
    path = _v5_derive_paths(context)["timing_receipt"]
    cap = root.read(path, modes={0o444})
    assert cap is not None
    value = _v5_load_json(cap.data, line_framed=True)
    if not isinstance(value, dict):
        _v5_contract("v5 timing receipt must be object")
    _v5_schema(value, context, "timing_receipt")
    event = next(
        row
        for row in reversed(replay.rows)
        if row.get("event_type") == "EVIDENCE_SEALED"
    )
    if (
        value["identity"] != _v5_attempt_identity()
        or value["evidence_sealed_event_sha256"] != _sha(_v5_json_line(event)[:-1])
        or value["registry_postimage"]["path"] != registry.path
        or value["duration_ns"]
        != value["end_monotonic_ns"] - value["start_monotonic_ns"]
        or value["within_budget"] != (0 <= value["duration_ns"] <= 4_000_000_000)
        or value["wall_span_within_four_seconds"]
        != (0 <= value["wall_span_microseconds"] <= 4_000_000)
        or value["status"]
        != (
            "PASS"
            if value["within_budget"] and value["wall_span_within_four_seconds"]
            else "FAIL"
        )
        or value["authorization"] != _v5_no_authority()
    ):
        _v5_tamper("v5 timing receipt arithmetic/identity drift")
    # The receipt binds the exact registry postimage at the durable seal, which
    # may be a strict prefix of a later provider/terminal registry.
    size = value["registry_postimage"]["bytes"]
    if (
        size > len(registry.data)
        or _sha(registry.data[:size]) != value["registry_postimage"]["sha256"]
    ):
        _v5_tamper("v5 timing receipt registry-prefix drift")
    return cap, value


def _v5_live_maps(
    root: V4Root,
    context: Mapping[str, Any],
    implementation_refs: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    binding = context["provider_consumer_binding"]
    provider_map: dict[str, str] = {}
    for path, expected_sha in binding["fixed_provider_map"].items():
        cap = root.read(path, modes={0o444, 0o644, 0o755})
        assert cap is not None
        if cap.sha256 != expected_sha:
            _v5_tamper(f"fixed v5 provider drift: {path}")
        provider_map[path] = cap.sha256
    for path in binding["mutable_provider_paths"]:
        expected = implementation_refs.get(path)
        if not isinstance(expected, Mapping):
            _v5_contract(f"mutable v5 provider manifest missing: {path}")
        cap = root.read(path, modes={int(expected["mode"], 8)})
        assert cap is not None
        _v5_ref_equal(cap, expected, f"mutable v5 provider {path}")
        provider_map[path] = cap.sha256
    consumer_map: dict[str, str] = {}
    for path, expected_sha in binding["consumer_map"].items():
        cap = root.read(path, modes={0o444, 0o644, 0o755})
        assert cap is not None
        if cap.sha256 != expected_sha:
            _v5_tamper(f"v5 consumer drift: {path}")
        consumer_map[path] = cap.sha256
    if len(provider_map) != 16 or len(consumer_map) != 3:
        _v5_contract("v5 provider/consumer cardinality drift")
    return {
        "provider_path_count": 16,
        "provider_map_sha256": canonical_sha(provider_map),
        "consumer_path_count": 3,
        "consumer_map_sha256": canonical_sha(consumer_map),
    }


def _v5_promote(
    root: V4Root,
    context: Mapping[str, Any],
    paths: Mapping[str, str],
    args: argparse.Namespace,
) -> dict[str, Any]:
    record, _rv, registry, replay, _audit, _activation = _v5_active(
        root, context, paths
    )
    if args.attempt_id != V5_ATTEMPT_ID:
        _v5_contract("--attempt-id a000017 required", "v5_identity_denied")
    key = (V5_ATTEMPT_KIND, V5_ATTEMPT_ID)
    state = replay.states.get(key)
    if state == "TERMINAL_G2_ELIGIBLE":
        return {
            "result": "ALREADY_TERMINAL_G2_ELIGIBLE",
            "state": state,
            "G2_reaudit_eligible": True,
            **_v5_no_authority(),
        }
    if state not in {"EVIDENCE_SEALED", "PROVIDER_VERIFIED"}:
        _v5_contract("v5 promote requires EVIDENCE_SEALED", "v5_state_denied")
    timing_cap, timing = _v5_timing_receipt(root, context, registry, replay)
    if timing["status"] != "PASS":
        result = _v5_terminalize(
            root,
            context,
            paths,
            record,
            registry,
            replay,
            failure_code="timing_budget_fail",
            message="v5 timing receipt is not PASS",
            preserved=[timing_cap.ref()],
        )
        return {**result, **_v5_no_authority()}
    sealed = next(
        row for row in replay.rows if row.get("event_type") == "EVIDENCE_SEALED"
    )
    evidence = _v5_validate_seal_evidence(
        root,
        context,
        sealed,
        replay,
        timing["validation_time"],
        verify_live_implementation=False,
    )
    provider_path = _v5_derive_paths(context)["provider_verification"]
    provider_cap = root.read(provider_path, modes={0o444}, optional=True)
    provider_value: dict[str, Any]
    if state == "EVIDENCE_SEALED":
        start_ns = time.monotonic_ns()
        try:
            maps = _v5_live_maps(root, context, evidence["implementation_files"])
        except GateError as exc:
            result = _v5_terminalize(
                root,
                context,
                paths,
                record,
                registry,
                replay,
                failure_code="provider_verification_fail",
                message=exc.message,
                preserved=[timing_cap.ref()],
            )
            return {**result, **_v5_no_authority()}
        end_ns = time.monotonic_ns()
        provider_duration = (
            end_ns - start_ns
            if args.v5_test_provider_duration_ns is None
            else args.v5_test_provider_duration_ns
        )
        if provider_duration > 30_000_000_000:
            result = _v5_terminalize(
                root,
                context,
                paths,
                record,
                registry,
                replay,
                failure_code="provider_verification_fail",
                message="v5 provider verification exceeded thirty seconds",
                preserved=[timing_cap.ref()],
            )
            return {**result, **_v5_no_authority()}
        provider_value = {
            "schema_name": "lane_b_registry_v5_provider_verification.v1",
            "schema_version": 1,
            "record_type": "immutable_live_provider_consumer_verification",
            "status": "PASS",
            "created_at": _v5_now(args.v5_event_at),
            "identity": _v5_attempt_identity(),
            "evidence_sealed_event_sha256": _sha(_v5_json_line(sealed)[:-1]),
            "timing_receipt": timing_cap.ref(),
            **maps,
            "producer_manifest_match": True,
            "independent_qa_manifest_match": True,
            "stable_descriptor_reads": True,
            "qa_age_seconds": evidence["qa_age_seconds"],
            "authorization": _v5_no_authority(),
        }
        provider_cap = _v5_create_artifact(
            root, context, "provider_verification", provider_path, provider_value
        )
        if args.v5_crash_after == "provider-artifact":
            _v5_recovery("injected crash after provider verification artifact")
        provider_event = v5_expected_attempt_event(
            context,
            registry,
            replay,
            "PROVIDER_VERIFIED",
            provider_value["created_at"],
            os.urandom(16).hex(),
            os.urandom(16).hex(),
            dev_dispatch_identity=sealed["dev_dispatch_identity"],
            qa_dispatch_identity=sealed["qa_dispatch_identity"],
            producer_identity=sealed["producer_identity"],
            qa_result_identity=sealed["qa_result_identity"],
            readiness_identity=sealed["readiness_identity"],
            receipt_identity=sealed["receipt_identity"],
            timing_identity=timing_cap.ref(),
            provider_verification_identity=provider_cap.ref(),
        )
        _v5_transition_event(
            root,
            context,
            paths,
            record,
            registry,
            replay,
            provider_event,
            expected_type="PROVIDER_VERIFIED",
            crash_after="append" if args.v5_crash_after == "provider-append" else None,
        )
        registry = root.read(paths["registry"], modes={0o600})
        assert registry is not None
        replay = _v5_replay(context, registry, record)
    else:
        if provider_cap is None:
            result = _v5_terminalize(
                root,
                context,
                paths,
                record,
                registry,
                replay,
                failure_code="provider_verification_fail",
                message="provider verified state lacks immutable provider artifact",
                preserved=[timing_cap.ref()],
            )
            return {**result, **_v5_no_authority()}
        provider_value_any = _v5_load_json(provider_cap.data, line_framed=True)
        if not isinstance(provider_value_any, dict):
            _v5_tamper("v5 provider verification must be object")
        provider_value = provider_value_any
        _v5_schema(provider_value, context, "provider_verification")
        try:
            maps = _v5_live_maps(root, context, evidence["implementation_files"])
        except GateError as exc:
            result = _v5_terminalize(
                root,
                context,
                paths,
                record,
                registry,
                replay,
                failure_code="provider_verification_fail",
                message=exc.message,
                preserved=[timing_cap.ref(), provider_cap.ref()],
            )
            return {**result, **_v5_no_authority()}
        for name, value in maps.items():
            if provider_value.get(name) != value:
                _v5_tamper("v5 provider verification map drift")
    assert provider_cap is not None
    provider_event = next(
        row for row in replay.rows if row.get("event_type") == "PROVIDER_VERIFIED"
    )
    marker_path = _v5_derive_paths(context)["terminal_marker"]
    marker_value = {
        "schema_name": "lane_b_registry_v5_terminal_g2_eligibility_marker.v1",
        "schema_version": 1,
        "record_type": "immutable_terminal_g2_eligibility_marker",
        "status": "TERMINAL_G2_ELIGIBLE_FOR_SEPARATE_G2_ONLY",
        "created_at": _v5_now(args.v5_event_at),
        "identity": _v5_attempt_identity(),
        "evidence_sealed_event_sha256": _sha(_v5_json_line(sealed)[:-1]),
        "provider_verified_event_sha256": _sha(_v5_json_line(provider_event)[:-1]),
        "timing_receipt": timing_cap.ref(),
        "provider_verification": provider_cap.ref(),
        "registry_preterminal": registry.ref(),
        "authorization": _v5_no_authority(),
    }
    marker_cap = _v5_create_artifact(
        root, context, "terminal_marker", marker_path, marker_value
    )
    if args.v5_crash_after == "terminal-marker":
        _v5_recovery("injected crash after v5 terminal marker")
    terminal_event = v5_expected_attempt_event(
        context,
        registry,
        replay,
        "TERMINAL_G2_ELIGIBLE",
        marker_value["created_at"],
        os.urandom(16).hex(),
        os.urandom(16).hex(),
        dev_dispatch_identity=sealed["dev_dispatch_identity"],
        qa_dispatch_identity=sealed["qa_dispatch_identity"],
        producer_identity=sealed["producer_identity"],
        qa_result_identity=sealed["qa_result_identity"],
        readiness_identity=sealed["readiness_identity"],
        receipt_identity=sealed["receipt_identity"],
        timing_identity=timing_cap.ref(),
        provider_verification_identity=provider_cap.ref(),
        terminal_marker_identity=marker_cap.ref(),
    )
    transition = _v5_transition_event(
        root,
        context,
        paths,
        record,
        registry,
        replay,
        terminal_event,
        expected_type="TERMINAL_G2_ELIGIBLE",
        crash_after="append" if args.v5_crash_after == "terminal-append" else None,
    )
    return {
        "result": "TERMINAL_G2_ELIGIBLE_FOR_SEPARATE_G2_ONLY",
        "state": "TERMINAL_G2_ELIGIBLE",
        "provider_verification": provider_cap.ref(),
        "terminal_marker": marker_cap.ref(),
        "transition": transition,
        "G2_reaudit_eligible": True,
        **_v5_no_authority(),
    }


def _v5_recover(
    root: V4Root,
    context: Mapping[str, Any],
    paths: Mapping[str, str],
    args: argparse.Namespace,
) -> dict[str, Any]:
    if not args.transaction_id or V5_TX_RE.fullmatch(args.transaction_id) is None:
        _v5_contract("--transaction-id required", "v5_identity_denied")
    frozen, _ = _v5_validate_frozen_v4(root, context, paths)
    record_item = _v5_record(root, context, paths["record"], frozen)
    if record_item is None:
        _v5_contract("v5 migration record missing", "v5_state_denied")
    record, _record_value = record_item
    _intent_cap, intent = _v5_intent(root, context, args.transaction_id)
    result = _v5_finish_transaction(root, context, record, args.transaction_id)
    registry = root.read(paths["registry"], modes={0o600})
    assert registry is not None
    replay = _v5_replay(context, registry, record)
    event = _v5_load_json(bytes.fromhex(intent["intended_event_hex"]), line_framed=True)
    if event.get("event_type") == "EVIDENCE_SEALED":
        timing = root.read(
            _v5_derive_paths(context)["timing_receipt"], modes={0o444}, optional=True
        )
        if timing is None:
            closed = _v5_terminalize(
                root,
                context,
                paths,
                record,
                registry,
                replay,
                failure_code="timing_budget_fail",
                message="recovery observed durable EVIDENCE_SEALED without timing receipt",
            )
            return {
                "result": "RECOVERED_TO_NO_AUTHORITY",
                "recovery": result,
                "closed": closed,
                **_v5_no_authority(),
            }
    return {"result": "RECOVERED_EXACT", "transaction": result, **_v5_no_authority()}


def _v5_verify_provider(
    root: V4Root,
    context: Mapping[str, Any],
    paths: Mapping[str, str],
    args: argparse.Namespace,
) -> dict[str, Any]:
    record, _rv, registry, replay, _audit, _activation = _v5_active(
        root, context, paths
    )
    if args.attempt_id != V5_ATTEMPT_ID:
        _v5_contract("--attempt-id a000017 required", "v5_identity_denied")
    if replay.states.get((V5_ATTEMPT_KIND, V5_ATTEMPT_ID)) != "TERMINAL_G2_ELIGIBLE":
        _v5_contract("v5 attempt not terminal G2 eligible", "v5_state_denied")
    timing_cap, timing = _v5_timing_receipt(root, context, registry, replay)
    if timing["status"] != "PASS":
        _v5_contract("v5 terminal has non-PASS timing receipt")
    sealed = next(
        row for row in replay.rows if row.get("event_type") == "EVIDENCE_SEALED"
    )
    evidence = _v5_validate_seal_evidence(
        root, context, sealed, replay, timing["validation_time"]
    )
    maps = _v5_live_maps(root, context, evidence["implementation_files"])
    provider_event = next(
        row for row in replay.rows if row.get("event_type") == "PROVIDER_VERIFIED"
    )
    terminal_event = next(
        row for row in replay.rows if row.get("event_type") == "TERMINAL_G2_ELIGIBLE"
    )
    provider_cap, provider = _v5_artifact_json(
        root,
        provider_event["provider_verification_identity"],
        _v5_derive_paths(context)["provider_verification"],
        "v5 provider verification",
    )
    _v5_schema(provider, context, "provider_verification")
    for name, value in maps.items():
        if provider.get(name) != value:
            _v5_tamper("v5 live provider verification drift")
    marker_cap, marker = _v5_artifact_json(
        root,
        terminal_event["terminal_marker_identity"],
        _v5_derive_paths(context)["terminal_marker"],
        "v5 terminal marker",
    )
    _v5_schema(marker, context, "terminal_marker")
    if (
        marker["provider_verification"] != provider_cap.ref()
        or marker["timing_receipt"] != timing_cap.ref()
        or marker["evidence_sealed_event_sha256"] != _sha(_v5_json_line(sealed)[:-1])
        or marker["provider_verified_event_sha256"]
        != _sha(_v5_json_line(provider_event)[:-1])
        or marker["registry_preterminal"]["bytes"] >= len(registry.data)
        or _sha(registry.data[: marker["registry_preterminal"]["bytes"]])
        != marker["registry_preterminal"]["sha256"]
    ):
        _v5_tamper("v5 terminal marker/predecessor drift")
    _v5_verify_all_transactions(root, context, record, registry, replay)
    return {
        "result": "VERIFIED_FOR_FRESH_G2_REAUDIT_ONLY",
        "attempt_id": V5_ATTEMPT_ID,
        "state": "TERMINAL_G2_ELIGIBLE",
        "registry": registry.ref(),
        "G2_reaudit_eligible": True,
        **_v5_no_authority(),
    }


def _v5_success(
    phase: str, result: Mapping[str, Any], lock_identity: str | None
) -> dict[str, Any]:
    return {
        "schema_version": 5,
        "record_type": "lane_b_registry_v5_control_result",
        "phase": phase,
        "status": "pass",
        "lock_identity": lock_identity,
        "result": dict(result),
        **_v5_no_authority(),
        **NONCLAIMS,
    }


def _v5_failure(phase: str, exc: GateError, exit_code: int) -> dict[str, Any]:
    state = (
        "recovery_required"
        if exit_code == 5
        else "lock_timeout" if exit_code == 4 else "denied"
    )
    return {
        "schema_version": 5,
        "record_type": "lane_b_registry_v5_control_result",
        "phase": phase,
        "status": state,
        "exit_code": exit_code,
        "findings": [exc.finding()],
        **_v5_no_authority(),
        **NONCLAIMS,
    }


def run_v5_phase(args: argparse.Namespace) -> dict[str, Any]:
    with V4Root(args.project_root) as root:
        context_path = args.v5_context or V5_CONTEXT_DEFAULT
        _context_cap, context = _v5_context(root, context_path)
        paths = _v5_paths(args, context, root)
        if paths["context"] != context_path:
            _v5_contract("v5 context path resolution mismatch")
        if args.phase == "registry-v5-migration-preflight":
            return _v5_success(
                args.phase,
                _v5_preflight(root, context, paths, require_absent=True),
                None,
            )
        try:
            lock_manager = _v4_lock(root, paths["lock"], args.lock_timeout)
            with lock_manager as lock_identity:
                if args.phase == "registry-v5-migration-commit":
                    result = _v5_migration_commit(root, context, paths, args)
                elif args.phase == "registry-v5-activate":
                    result = _v5_activate(root, context, paths, args)
                elif args.phase == "registry-v5-allocate":
                    result = _v5_allocate(root, context, paths, args)
                elif args.phase == "registry-v5-start":
                    result = _v5_start(root, context, paths, args)
                elif args.phase == "registry-v5-seal":
                    result = _v5_seal(root, context, paths, args)
                elif args.phase == "registry-v5-promote":
                    result = _v5_promote(root, context, paths, args)
                elif args.phase == "registry-v5-recover":
                    result = _v5_recover(root, context, paths, args)
                elif args.phase == "verify-h-b-v5-provider-set":
                    result = _v5_verify_provider(root, context, paths, args)
                else:
                    _v5_contract("unknown v5 phase")
                return _v5_success(args.phase, result, lock_identity)
        except V4Error as exc:
            if exc.exit_code == 4:
                _v5_deny(4, "v5_lock_timeout", exc.message, state="lock_timeout")
            raise


def legacy_dispatch(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    with CaptureSet(root) as captures:
        try:
            _lane_cap, context = captures.json(
                args.lane_context, code="lane_context_invalid"
            )
            _pipe_cap, pipeline = captures.json(
                args.pipeline_contract, code="pipeline_contract_invalid"
            )
            declared = _lane_paths(context)
            actual = set(args.actual_path or declared)
            if actual - declared:
                _deny(
                    "undeclared_lane_b_path",
                    ",".join(sorted(actual - declared)),
                    "pipeline-0/LANE-B",
                )
            peers: set[str] = set()
            for path in args.peer_context:
                _cap, peer = captures.json(path, code="peer_context_invalid")
                peers |= _planned_paths(peer)
            if actual & peers:
                _deny("peer_writer_overlap", ",".join(sorted(actual & peers)))
            record = _pipeline_record(pipeline)
            dependencies = (
                record.get("dependencies") if isinstance(record, dict) else None
            )
            if record is None or not isinstance(dependencies, list):
                _deny(
                    "pipeline_dependencies_invalid", "pipeline-0/dependencies invalid"
                )
            if dependencies:
                _deny(
                    "pipeline_0_has_inbound_dependencies",
                    json.dumps(dependencies, sort_keys=True),
                )
            if context.get("core_dev_dispatch_allowed") is not True:
                _deny(
                    "core_dispatch_not_admitted",
                    "context does not admit dispatch",
                    "pipeline-0/LANE-B",
                )
            captures.revalidate()
            return {
                "schema_version": 1,
                "record_type": "laneb_integration_gate.v1",
                "phase": "dispatch",
                "status": "pass",
                "core_dev_dispatch_allowed": True,
                "lane_state": "integration_pending",
                "lane_b_paths": sorted(actual),
                "peer_writer_intersection": [],
                "pipeline_0_inbound_dependencies": [],
                "findings": [],
                **NONCLAIMS,
            }
        except GateError as exc:
            findings.append(exc.finding())
            return {
                "schema_version": 1,
                "record_type": "laneb_integration_gate.v1",
                "phase": "dispatch",
                "status": "fail",
                "core_dev_dispatch_allowed": False,
                "lane_state": "blocked",
                "findings": findings,
                **NONCLAIMS,
            }


def legacy_fan_in(_: argparse.Namespace, __: Path) -> dict[str, Any]:
    # The former caller-selected v1 handoff surface remains parse-compatible but
    # is permanently non-authorizing.  Strict v2 producer/consumer is mandatory.
    finding = GateError(
        "stale_h_b_generation",
        "same-spec parent",
        "legacy v1 fan-in cannot select current H-B",
    ).finding()
    return {
        "schema_version": 1,
        "record_type": "laneb_integration_gate.v1",
        "phase": "fan-in",
        "status": "fail",
        "fan_in_status": "fail",
        "final_qa_eligible": False,
        "findings": [finding],
        **NONCLAIMS,
    }


def _planned_paths(context: Mapping[str, Any]) -> set[str]:
    approach = context.get("development_approach")
    if not isinstance(approach, dict):
        return set()
    out = set()
    for key in ("files_to_modify", "files_to_create"):
        values = approach.get(key)
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str) and value.strip():
                    out.add(re.sub(r"\s+\([^)]*\)\s*$", "", value.strip()))
    return out


def _lane_paths(context: Mapping[str, Any]) -> set[str]:
    requirement = context.get("requirement")
    if isinstance(requirement, dict) and isinstance(
        requirement.get("lane_b_authored_paths"), list
    ):
        return {
            value
            for value in requirement["lane_b_authored_paths"]
            if isinstance(value, str) and value
        }
    return _planned_paths(context)


def _pipeline_record(contract: Mapping[str, Any]) -> dict[str, Any] | None:
    pipelines = contract.get("pipelines")
    if isinstance(pipelines, dict) and isinstance(pipelines.get(PIPELINE_ID), dict):
        return pipelines[PIPELINE_ID]
    if isinstance(pipelines, list):
        return next(
            (
                item
                for item in pipelines
                if isinstance(item, dict) and item.get("pipeline_id") == PIPELINE_ID
            ),
            None,
        )
    return None


def _failure(phase: str, exc: GateError) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "record_type": "laneb_integration_gate_result.v2",
        "phase": phase,
        "status": exc.state if exc.state in {"fail", "waiting"} else "fail",
        "final_qa_eligible": False,
        "findings": [exc.finding()],
        **NONCLAIMS,
        "authorizes": [],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        required=True,
        choices=(
            "dispatch",
            "fan-in",
            "verify-h-b-v3-provider-set",
            "verify-h-b-v3-commit",
            "produce-fan-in-v2",
            "consume-fan-in-v2",
            "sandbox-transaction",
            "registry-v4-migration-preflight",
            "registry-v4-migration-commit",
            "registry-v4-allocate",
            "registry-v4-transition",
            "registry-v4-recover",
            "verify-h-b-v4-provider-set",
            "registry-v5-migration-preflight",
            "registry-v5-migration-commit",
            "registry-v5-activate",
            "registry-v5-allocate",
            "registry-v5-start",
            "registry-v5-seal",
            "registry-v5-promote",
            "registry-v5-recover",
            "verify-h-b-v5-provider-set",
        ),
    )
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--contract", default=CONTRACT_DEFAULT)
    parser.add_argument("--registry", default=REGISTRY_DEFAULT)
    parser.add_argument("--attempt-id")
    parser.add_argument("--h-b-current-binding")
    parser.add_argument("--bundle")
    parser.add_argument("--envelope")
    parser.add_argument("--transaction-spec")
    # Legacy dispatch/fan-in flags are accepted but never trusted by v2 modes.
    parser.add_argument("--lane-context")
    parser.add_argument("--pipeline-contract")
    parser.add_argument("--peer-context", action="append", default=[])
    parser.add_argument("--actual-path", action="append", default=[])
    parser.add_argument("--core-report")
    parser.add_argument("--pol-dev-report")
    parser.add_argument("--pol-qa-report")
    parser.add_argument("--bind-dev-report")
    parser.add_argument("--bind-qa-report")
    parser.add_argument("--effective-file", action="append", default=[])
    parser.add_argument("--ownership-ledger")
    # Registry-v4 paths are fixed in production. Overrides and crash injection
    # are admitted only by an explicitly marked, non-repository test root.
    parser.add_argument("--v4-context")
    parser.add_argument("--v3-registry")
    parser.add_argument("--v4-registry")
    parser.add_argument("--migration-record")
    parser.add_argument("--migration-audit")
    parser.add_argument("--v4-lock")
    parser.add_argument("--attempt-kind", default="GATE_REPAIR_HB3")
    parser.add_argument("--event-input")
    parser.add_argument("--transaction-id")
    parser.add_argument("--lock-timeout", type=float, default=0.25)
    parser.add_argument("--v4-event-at")
    parser.add_argument(
        "--v4-crash-after",
        choices=("migration-record", "intent", "partial", "fsync", "append", "step2"),
    )
    parser.add_argument("--v4-test-mode", action="store_true")
    # Registry-v5 paths remain fixed in production; test controls require the
    # dedicated marker in an isolated non-repository root.
    parser.add_argument("--v5-context")
    parser.add_argument("--v4-registry-frozen")
    parser.add_argument("--v5-registry")
    parser.add_argument("--v5-migration-record")
    parser.add_argument("--v5-migration-audit")
    parser.add_argument("--v5-activation")
    parser.add_argument("--v5-lock")
    parser.add_argument("--v5-event-at")
    parser.add_argument(
        "--v5-crash-after",
        choices=(
            "migration-record",
            "intent",
            "partial",
            "fsync",
            "append",
            "step2",
            "timing-receipt",
            "provider-artifact",
            "provider-append",
            "terminal-marker",
            "terminal-append",
        ),
    )
    parser.add_argument("--v5-test-duration-ns", type=int)
    parser.add_argument("--v5-test-provider-duration-ns", type=int)
    parser.add_argument("--v5-test-mode", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    phase = args.phase
    v4_phase = phase in V4_PHASES
    v5_phase = phase in V5_PHASES
    exit_code = 0
    try:
        root = Path(args.project_root)
        if v5_phase:
            output = run_v5_phase(args)
        elif v4_phase:
            output = run_v4_phase(args)
        elif phase == "dispatch":
            output = legacy_dispatch(args, root)
        elif phase == "fan-in":
            output = legacy_fan_in(args, root)
        elif phase == "verify-h-b-v3-provider-set":
            if not args.attempt_id:
                _deny("h_b_v3_attempt_identity_invalid", "--attempt-id required")
            output = verify_hb3_provider_set(
                root,
                contract_path=args.contract,
                registry_path=args.registry,
                attempt_id=args.attempt_id,
            )
        elif phase == "verify-h-b-v3-commit":
            if not args.h_b_current_binding:
                _deny("h_b_v3_not_committed", "--h-b-current-binding required")
            output = verify_hb3_commit(
                root, contract_path=args.contract, binding_path=args.h_b_current_binding
            )
        elif phase == "produce-fan-in-v2":
            if not args.bundle:
                _deny("invalid_envelope", "--bundle required")
            output = produce_envelope(
                root, contract_path=args.contract, bundle_path=args.bundle
            )
        elif phase == "consume-fan-in-v2":
            if not args.envelope:
                _deny("invalid_envelope", "--envelope required")
            output = consume_envelope(
                root, contract_path=args.contract, envelope_path=args.envelope
            )
        else:
            if not args.transaction_spec:
                _deny("publication_transaction_failed", "--transaction-spec required")
            output = sandbox_transaction(root, args.transaction_spec)
    except (V5Error, V4Error) as exc:
        exit_code = exc.exit_code
        output = (
            _v5_failure(phase, exc, exit_code)
            if v5_phase
            else _v4_failure(phase, exc, exit_code)
        )
    except GateError as exc:
        exit_code = 2 if (v4_phase or v5_phase) else 1
        output = (
            _v5_failure(phase, exc, exit_code)
            if v5_phase
            else (
                _v4_failure(phase, exc, exit_code) if v4_phase else _failure(phase, exc)
            )
        )
    except Exception as exc:  # never leak exception/path/provider detail
        exit_code = 2 if (v4_phase or v5_phase) else 1
        error = GateError(
            "internal_verifier_error", "same-spec parent", type(exc).__name__
        )
        output = (
            _v5_failure(phase, error, exit_code)
            if v5_phase
            else (
                _v4_failure(phase, error, exit_code)
                if v4_phase
                else _failure(phase, error)
            )
        )
    print(
        json.dumps(
            output,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    )
    if v4_phase or v5_phase:
        return exit_code
    return (
        0
        if output.get("status") == "pass"
        or output.get("decision", {}).get("status") == "pass"
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
