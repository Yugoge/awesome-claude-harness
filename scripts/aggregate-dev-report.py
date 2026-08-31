#!/usr/bin/env python3
"""Declaration-driven, linearizable dev artifact-chain provider.

The embedded ``artifact_chain_declaration.v1`` in the parent canonical is the
only durable chain declaration.  This module deliberately does not discover a
chain from filenames.  It validates caller-supplied topology, derives parallel
canonicals from those exact paths, and serializes every writer through one
root/task lock.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import copy
import errno
import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import stat
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

DECLARATION_VERSION = "artifact_chain_declaration.v1"
PROVIDER_VERSION = "artifact_chain_declaration_provider.v1"
STABLE_PROJECTION_VERSION = "stable_dev_projection.v1"
OUTCOMES_VERSION = "parallel_dev_worker_outcomes.v1"
SHAPES = {"singular", "parallel_dev", "requirement_fanout"}
MODE_BY_SHAPE = {"singular": "singular", "parallel_dev": "parallel_dev", "requirement_fanout": "fanout"}
MEMBER_KINDS = {"singular_parent", "parallel_worker", "requirement_lane"}
PHASE_STATES = {"dispatched", "dev_completed", "awaiting_qa", "needs_review", "retry_dispatched", "qa_pass", "superseded"}
TERMINAL_STATES = {"qa_pass", "superseded"}
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
HEX_RE = re.compile(r"^[0-9a-f]{64}$")
HEAD_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
BLOCKER_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
BASE64_RE = re.compile(r"^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$")
INT_MAX = 2_147_483_647
STABLE_EVIDENCE_FIELDS = frozenset({
    "artifact_sha256", "stable_projection_sha256",
    "stable_projection_utf8_base64", "phase_digest", "declaration_digest",
})
_WRITE_BOUNDARY: ContextVar[dict[str, Any] | None] = ContextVar("artifact_chain_write_boundary", default=None)
DECLARATION_FIELDS = {
    "schema_version", "parent_task_id", "shape", "execution", "origin",
    "member_lineage", "lineage_digest", "inventory", "inventory_digest",
    "baseline_policy", "baseline_bindings", "phase_projection",
    "active_roster", "excluded_roster", "declaration_digest",
}
INVENTORY_KINDS = {
    "parent_ticket", "parent_context", "canonical_dev_report",
    "parent_qa_report", "parent_completion", "worker_dev_report",
    "lane_ticket", "lane_context", "lane_dev_report", "lane_qa_report",
}
ATTEMPT_MEMBER_FIELDS = {
    "member_id", "state", "attempt", "evidence_digest", "superseded_by",
    "attempt_storage", "attempt_reservations", "attempt_ledger", "current_attempt",
}
EVENT_FIELDS = {
    "phase_version", "event_ordinal", "member_id", "from_state", "to_state",
    "attempt", "evidence_digest", "superseded_by", "coverage_disposition",
}
RESERVATION_FIELDS = {
    "schema_version", "attempt", "artifact_path", "expected_absent",
    "reserved_at_phase_version",
}
IMMUTABLE_LEDGER_FIELDS = {
    "schema_version", "record_kind", "attempt", "artifact_path",
    "artifact_sha256", "stable_projection_sha256", "completed_at_phase_version",
}
MUTABLE_LEDGER_FIELDS = {
    "schema_version", "record_kind", "attempt", "artifact_path",
    "stable_projection_sha256", "stable_projection_utf8_base64",
    "completed_at_phase_version",
}


class DuplicateKeyError(ValueError):
    pass


class ContractFailure(Exception):
    def __init__(self, errors: list[dict[str, str]]) -> None:
        super().__init__(errors[0]["message"] if errors else "contract failure")
        self.errors = errors


def _err(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise DuplicateKeyError(f"duplicate JSON key {key!r}")
        out[key] = value
    return out


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value}")


def load_json_bytes(raw: bytes, path: str = "") -> dict[str, Any]:
    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, DuplicateKeyError, ValueError) as exc:
        raise ContractFailure([_err("INVALID_DECLARATION", path, f"invalid strict JSON: {exc}")]) from exc
    if not isinstance(value, dict):
        raise ContractFailure([_err("INVALID_DECLARATION", path, "top-level JSON value must be an object")])
    return value


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ContractFailure([_err("INVALID_DECLARATION", "", f"value is not canonical JSON: {exc}")]) from exc


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _bytes_digest(raw: bytes, *, prefixed: bool = True) -> str:
    value = hashlib.sha256(raw).hexdigest()
    return f"sha256:{value}" if prefixed else value


def _evidence_leak_paths(value: Any, path: str) -> list[str]:
    leaks: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}/{str(key).replace('~', '~0').replace('/', '~1')}"
            if key == "artifact_chain_evidence" or key in STABLE_EVIDENCE_FIELDS:
                leaks.append(child_path)
            else:
                leaks.extend(_evidence_leak_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            leaks.extend(_evidence_leak_paths(child, f"{path}/{index}"))
    return leaks


def _validate_report_evidence_containment(document: Any) -> None:
    if not isinstance(document, dict):
        raise ContractFailure([_err("INVALID_STATUS", "", "Dev report must be a JSON object")])
    evidence = document.get("artifact_chain_evidence")
    if "artifact_chain_evidence" in document and type(evidence) is not dict:
        raise ContractFailure([_err(
            "INVALID_DECLARATION", "artifact_chain_evidence",
            "artifact_chain_evidence must be one exact top-level object when present",
        )])
    leaks: list[str] = []
    for key, value in document.items():
        if key in {"artifact_chain_declaration", "artifact_chain_evidence"}:
            continue
        path = f"/{str(key).replace('~', '~0').replace('/', '~1')}"
        if key in STABLE_EVIDENCE_FIELDS:
            leaks.append(path)
        else:
            leaks.extend(_evidence_leak_paths(value, path))
    if leaks:
        raise ContractFailure([_err(
            "INVALID_DECLARATION", leaks[0],
            "artifact-chain evidence fields are valid only inside the top-level artifact_chain_evidence object; leaks="
            + ",".join(leaks),
        )])


def stable_dev_projection(document: dict[str, Any]) -> tuple[bytes, str]:
    """Return exact non-self-referential stable_dev_projection.v1 bytes/hash."""
    _validate_report_evidence_containment(document)
    projection = {
        key: copy.deepcopy(value)
        for key, value in document.items()
        if key not in {"artifact_chain_declaration", "artifact_chain_evidence"}
    }
    raw = _canonical_bytes(projection)
    return raw, _bytes_digest(raw)


def _is_int(value: Any, minimum: int = 0, maximum: int = INT_MAX) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _safe_task_id(value: Any) -> bool:
    return isinstance(value, str) and value not in {".", ".."} and TASK_ID_RE.fullmatch(value) is not None


def _safe_rel_path(value: Any, *, beneath_docs_dev: bool = False) -> bool:
    if not isinstance(value, str) or not value or "\x00" in value or "//" in value or "\\" in value:
        return False
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return False
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        return False
    if pure.as_posix() != value:
        return False
    return (not beneath_docs_dev) or (len(pure.parts) >= 3 and pure.parts[:2] == ("docs", "dev"))


def _path_on_disk(root: Path, relative: str) -> Path:
    if not _safe_rel_path(relative):
        raise ContractFailure([_err("INVENTORY_MISMATCH", relative, "unsafe project-relative path")])
    target = root.joinpath(*PurePosixPath(relative).parts)
    try:
        resolved_parent = target.parent.resolve(strict=True)
        resolved_root = root.resolve(strict=True)
        resolved_parent.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise ContractFailure([_err("IO_ERROR", relative, f"path escapes or has an unreadable parent: {exc}")]) from exc
    try:
        if target.is_symlink():
            raise ContractFailure([_err("INVENTORY_MISMATCH", relative, "artifact path may not be a symlink")])
    except OSError as exc:
        raise ContractFailure([_err("IO_ERROR", relative, str(exc))]) from exc
    return target


def _file_fingerprint(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_size,
        metadata.st_mtime_ns, metadata.st_ctime_ns,
    )


def _filesystem_path_failure(relative: Any, exc: OSError) -> ContractFailure:
    if exc.errno == errno.ENOENT:
        return ContractFailure([_err("MISSING_ARTIFACT", str(relative), "declared path or an intermediate component is absent")])
    if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
        return ContractFailure([_err("INVENTORY_MISMATCH", str(relative), "declared path contains a symlink or non-directory intermediate component")])
    return ContractFailure([_err("IO_ERROR", str(relative), f"cannot inspect declared path: {exc}")])


def _open_regular_file_beneath(root: Path, relative: Any) -> tuple[int, tuple[int, int, int, int, int, int]]:
    """Open one exact regular file without following any path-component symlink."""
    if type(relative) is not str or not _safe_rel_path(relative):
        raise ContractFailure([_err("INVENTORY_MISMATCH", str(relative), "unsafe or non-string project-relative path")])
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise ContractFailure([_err("IO_ERROR", relative, "platform lacks required no-follow directory traversal support")])
    parts = PurePosixPath(relative).parts
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    file_flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    file_flags |= os.O_NOFOLLOW
    directory_fds: list[int] = []
    file_fd: int | None = None
    try:
        current_fd = os.open(root, directory_flags)
        directory_fds.append(current_fd)
        for part in parts[:-1]:
            current_fd = os.open(part, directory_flags, dir_fd=current_fd)
            directory_fds.append(current_fd)
        file_fd = os.open(parts[-1], file_flags, dir_fd=current_fd)
        metadata = os.fstat(file_fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise ContractFailure([_err("INVENTORY_MISMATCH", relative, "declared path must be a real regular file")])
        return file_fd, _file_fingerprint(metadata)
    except ContractFailure:
        if file_fd is not None:
            os.close(file_fd)
        raise
    except OSError as exc:
        if file_fd is not None:
            os.close(file_fd)
        raise _filesystem_path_failure(relative, exc) from exc
    finally:
        for directory_fd in reversed(directory_fds):
            os.close(directory_fd)


def _inspect_regular_file_beneath(root: Path, relative: Any) -> tuple[int, int, int, int, int, int]:
    fd, before = _open_regular_file_beneath(root, relative)
    os.close(fd)
    verify_fd, after = _open_regular_file_beneath(root, relative)
    os.close(verify_fd)
    if after != before:
        raise ContractFailure([_err("STALE_CANONICAL", str(relative), "declared path changed during containment validation")])
    return after


def _read_regular_file_snapshot(root: Path, relative: Any) -> tuple[bytes, tuple[int, int, int, int, int, int]]:
    """Read stable bytes/fingerprint from an exact no-symlink in-root file."""
    fd, before = _open_regular_file_beneath(root, relative)
    chunks: list[bytes] = []
    try:
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after_read = _file_fingerprint(os.fstat(fd))
    except OSError as exc:
        raise ContractFailure([_err("IO_ERROR", str(relative), f"cannot read declared path: {exc}")]) from exc
    finally:
        os.close(fd)
    if after_read != before:
        raise ContractFailure([_err("STALE_CANONICAL", str(relative), "declared file changed while its evidence was read")])
    verify_fd, after_reopen = _open_regular_file_beneath(root, relative)
    os.close(verify_fd)
    if after_reopen != after_read:
        raise ContractFailure([_err("STALE_CANONICAL", str(relative), "declared file was replaced while its evidence was read")])
    return b"".join(chunks), after_reopen


def _read_regular_file_bytes(root: Path, relative: Any) -> bytes:
    return _read_regular_file_snapshot(root, relative)[0]


def _validate_declared_repo_paths(
    root: Path, report: dict[str, Any], report_path: str,
    errors: list[dict[str, str]],
) -> dict[str, tuple[int, int, int, int, int, int]] | None:
    """Validate exact flat/nested Dev file aliases and bind real in-root files."""
    starting_error_count = len(errors)
    dev = report.get("dev")
    if type(dev) is not dict:
        errors.append(_err("INVALID_STATUS", report_path, "dev must be an exact object before declared paths are consumed"))
        return None
    seen_paths: set[str] = set()
    seen_objects: dict[tuple[int, int], str] = {}
    bindings: dict[str, tuple[int, int, int, int, int, int]] = {}
    for field in ("files_modified", "files_created"):
        values = dev.get(field)
        flat = report.get(field)
        if type(values) is not list or type(flat) is not list:
            errors.append(_err("INVALID_STATUS", report_path, f"dev.{field} and its flat alias must be exact arrays"))
            continue
        if len(flat) != len(values) or any(type(left) is not type(right) or left != right for left, right in zip(flat, values)):
            errors.append(_err("INVALID_STATUS", report_path, f"flat {field} must type-strictly equal dev.{field}"))
            continue
        for index, relative in enumerate(values):
            value_path = f"{report_path}#dev.{field}[{index}]"
            if type(relative) is not str or not _safe_rel_path(relative):
                errors.append(_err("INVENTORY_MISMATCH", value_path, f"unsafe or non-string declared repository path {relative!r}"))
                continue
            if relative in seen_paths:
                errors.append(_err("INVENTORY_MISMATCH", value_path, f"ambiguous duplicate declared repository path {relative!r}"))
                continue
            seen_paths.add(relative)
            try:
                fingerprint = _inspect_regular_file_beneath(root, relative)
            except ContractFailure as exc:
                errors.extend(_err(item["code"], value_path, item["message"]) for item in exc.errors)
                continue
            object_key = fingerprint[:2]
            if object_key in seen_objects:
                errors.append(_err(
                    "INVENTORY_MISMATCH", value_path,
                    f"declared repository paths {seen_objects[object_key]!r} and {relative!r} alias the same file",
                ))
                continue
            seen_objects[object_key] = relative
            bindings[relative] = fingerprint
    return bindings if len(errors) == starting_error_count else None


def _validate_digest(value: Any) -> bool:
    return isinstance(value, str) and DIGEST_RE.fullmatch(value) is not None


def _validate_baseline(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"head_sha", "dirty_snapshot"}
        and isinstance(value["head_sha"], str)
        and HEAD_RE.fullmatch(value["head_sha"]) is not None
        and isinstance(value["dirty_snapshot"], str)
    )


def _inventory_sort_key(entry: dict[str, Any]) -> tuple[bytes, bytes, bytes, bool]:
    return (
        entry["path"].encode("utf-8"), entry["kind"].encode("ascii"),
        (entry["member_id"] or "").encode("utf-8"), entry["required"],
    )


def _validate_inventory(
    declaration: dict[str, Any], errors: list[dict[str, str]]
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    inventory = declaration.get("inventory")
    by_kind: dict[str, dict[str, Any]] = {}
    by_member_kind: dict[tuple[str, str], dict[str, Any]] = {}
    if not isinstance(inventory, list):
        errors.append(_err("INVALID_DECLARATION", "artifact_chain_declaration.inventory", "inventory must be an array"))
        return by_kind, by_member_kind
    seen_paths: set[str] = set()
    previous_key: tuple[bytes, bytes, bytes, bool] | None = None
    for index, item in enumerate(inventory):
        path = f"artifact_chain_declaration.inventory[{index}]"
        if not isinstance(item, dict) or set(item) != {"kind", "path", "member_id", "required"}:
            errors.append(_err("INVALID_DECLARATION", path, "inventory row is a closed kind/path/member_id/required object"))
            continue
        kind, rel, member, required = item["kind"], item["path"], item["member_id"], item["required"]
        if not isinstance(kind, str) or kind not in INVENTORY_KINDS or not _safe_rel_path(rel) or not isinstance(required, bool):
            errors.append(_err("INVALID_DECLARATION", path, "invalid inventory kind/path/required"))
            continue
        if member is not None and not _safe_task_id(member):
            errors.append(_err("INVALID_DECLARATION", path, "member_id must be null or an exact safe id"))
            continue
        if rel in seen_paths:
            errors.append(_err("INVENTORY_MISMATCH", rel, "inventory paths must be globally unique"))
        seen_paths.add(rel)
        key = _inventory_sort_key(item)
        if previous_key is not None and key <= previous_key:
            errors.append(_err("INVALID_DECLARATION", path, "inventory must be strictly sorted by exact UTF-8 path topology"))
        previous_key = key
        if member is None:
            if kind in by_kind:
                errors.append(_err("INVENTORY_MISMATCH", rel, f"duplicate parent inventory kind {kind}"))
            by_kind[kind] = item
        else:
            mk = (member, kind)
            if mk in by_member_kind:
                errors.append(_err("INVENTORY_MISMATCH", rel, f"duplicate member inventory kind {kind}"))
            by_member_kind[mk] = item
    return by_kind, by_member_kind


def _expected_attempt_path(shape: str, parent: str, member: dict[str, Any], attempt: int) -> str:
    base = member["artifact_paths"]["dev_report"]
    if member["member_kind"] == "singular_parent" or attempt == 1:
        return base
    return f"docs/dev/dev-report-iter{attempt}-{parent}-{member['member_id']}.json"


def _decode_projection_snapshot(value: Any, path: str, errors: list[dict[str, str]]) -> tuple[bytes | None, str | None]:
    if not isinstance(value, str) or len(value) < 4 or BASE64_RE.fullmatch(value) is None:
        errors.append(_err("INVALID_DECLARATION", path, "stable projection snapshot must be canonical padded RFC 4648 base64"))
        return None, None
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        errors.append(_err("INVALID_DECLARATION", path, f"invalid base64: {exc}"))
        return None, None
    if base64.b64encode(raw).decode("ascii") != value:
        errors.append(_err("INVALID_DECLARATION", path, "base64 encoding is not canonical"))
        return None, None
    try:
        snapshot = load_json_bytes(raw, path)
    except ContractFailure as exc:
        errors.extend(exc.errors)
        return None, None
    if "artifact_chain_declaration" in snapshot or "artifact_chain_evidence" in snapshot:
        errors.append(_err("INVALID_DECLARATION", path, "stable projection snapshot contains an excluded top-level field"))
        return None, None
    try:
        projected, projection_digest = stable_dev_projection(snapshot)
    except ContractFailure as exc:
        errors.extend(exc.errors)
        return None, None
    if projected != raw:
        errors.append(_err("INVALID_DECLARATION", path, "snapshot bytes are not canonical stable_dev_projection.v1 JSON"))
        return None, None
    return raw, projection_digest


def _validate_attempts(
    declaration: dict[str, Any], lineage: list[dict[str, Any]], phase_members: list[dict[str, Any]],
    errors: list[dict[str, str]], root: Path | None, validate_artifacts: bool,
) -> None:
    shape = declaration["shape"]
    parent = declaration["parent_task_id"]
    origin = declaration["origin"]
    phase_version = declaration["phase_projection"]["phase_version"]
    lineage_by_id = {item["member_id"]: item for item in lineage}
    globally_reserved: set[str] = set()
    for ordinal, phase_member in enumerate(phase_members):
        base = f"artifact_chain_declaration.phase_projection.members[{ordinal}]"
        member = lineage_by_id.get(phase_member.get("member_id"))
        if member is None:
            continue
        if set(phase_member) != ATTEMPT_MEMBER_FIELDS:
            errors.append(_err("INVALID_DECLARATION", base, "phase member is closed and must contain the exact state and attempt-ledger fields"))
            continue
        storage = phase_member.get("attempt_storage")
        expected_storage = "mutable_singular" if member["member_kind"] == "singular_parent" else "immutable_member"
        if storage != expected_storage:
            errors.append(_err("INVALID_DECLARATION", base + ".attempt_storage", f"expected {expected_storage!r}"))
        reservations = phase_member.get("attempt_reservations")
        ledger = phase_member.get("attempt_ledger")
        alias = phase_member.get("current_attempt")
        if not isinstance(reservations, list) or not isinstance(ledger, list):
            errors.append(_err("INVALID_DECLARATION", base, "attempt_reservations and attempt_ledger must be arrays"))
            continue
        if len(reservations) not in {len(ledger), len(ledger) + 1}:
            errors.append(_err("INVALID_DECLARATION", base, "at most one final reservation may be pending"))
        expected_alias = ledger[-1].get("attempt") if ledger and isinstance(ledger[-1], dict) else None
        if alias is not None and not _is_int(alias, 1):
            errors.append(_err("INVALID_DECLARATION", base + ".current_attempt", "current_attempt must be null or an integer in range"))
        if alias != expected_alias:
            errors.append(_err("INVALID_DECLARATION", base + ".current_attempt", "current_attempt must be null iff the ledger is empty, otherwise the last ledger attempt"))
        previous_reservation: dict[str, Any] | None = None
        for index, reservation in enumerate(reservations):
            rpath = f"{base}.attempt_reservations[{index}]"
            if not isinstance(reservation, dict) or set(reservation) != RESERVATION_FIELDS:
                errors.append(_err("INVALID_DECLARATION", rpath, "attempt reservation has a closed schema"))
                continue
            attempt = reservation.get("attempt")
            if reservation.get("schema_version") != "attempt_reservation.v1" or not _is_int(attempt, 1):
                errors.append(_err("INVALID_DECLARATION", rpath, "invalid reservation schema_version or attempt"))
                continue
            if attempt != index + 1:
                errors.append(_err("INVALID_DECLARATION", rpath, "reservation attempts must be contiguous from 1"))
            artifact_path = reservation.get("artifact_path")
            if not _safe_rel_path(artifact_path, beneath_docs_dev=True):
                errors.append(_err("INVALID_DECLARATION", rpath + ".artifact_path", "unsafe reservation path"))
            elif artifact_path != _expected_attempt_path(shape, parent, member, attempt):
                errors.append(_err("INVENTORY_MISMATCH", artifact_path, "reservation path is not the exact declared attempt path"))
            elif artifact_path in globally_reserved and storage == "immutable_member":
                errors.append(_err("INVENTORY_MISMATCH", artifact_path, "immutable attempt paths must be globally unique"))
            globally_reserved.add(artifact_path) if isinstance(artifact_path, str) else None
            expected_absent = not (origin == "historical_recovery" and attempt == 1)
            if storage == "mutable_singular" and attempt > 1:
                expected_absent = False
            if not isinstance(reservation.get("expected_absent"), bool) or reservation.get("expected_absent") != expected_absent:
                errors.append(_err("INVALID_DECLARATION", rpath + ".expected_absent", f"expected_absent must be {expected_absent}"))
            reserved_version = reservation.get("reserved_at_phase_version")
            if not _is_int(reserved_version):
                errors.append(_err("INVALID_DECLARATION", rpath + ".reserved_at_phase_version", "invalid phase version"))
            elif attempt == 1 and reserved_version != 0:
                errors.append(_err("INVALID_DECLARATION", rpath, "attempt 1 must be reserved at phase version 0"))
            previous_reservation = reservation
        for index, row in enumerate(ledger):
            lpath = f"{base}.attempt_ledger[{index}]"
            if not isinstance(row, dict):
                errors.append(_err("INVALID_DECLARATION", lpath, "ledger row must be an object"))
                continue
            expected_fields = IMMUTABLE_LEDGER_FIELDS if storage == "immutable_member" else MUTABLE_LEDGER_FIELDS
            if set(row) != expected_fields:
                errors.append(_err("INVALID_DECLARATION", lpath, "ledger row fields do not match its discriminated storage branch"))
                continue
            attempt = row.get("attempt")
            if row.get("schema_version") != "attempt_ledger_record.v1" or row.get("record_kind") != storage or not _is_int(attempt, 1):
                errors.append(_err("INVALID_DECLARATION", lpath, "invalid ledger schema_version, record_kind, or attempt"))
                continue
            if attempt != index + 1:
                errors.append(_err("INVALID_DECLARATION", lpath, "ledger attempts must be contiguous from 1"))
            matching_reservation = reservations[index] if index < len(reservations) and isinstance(reservations[index], dict) else {}
            if not matching_reservation or row.get("artifact_path") != matching_reservation.get("artifact_path"):
                errors.append(_err("INVENTORY_MISMATCH", lpath, "ledger row must match its reservation path"))
            if not _validate_digest(row.get("stable_projection_sha256")):
                errors.append(_err("INVALID_DECLARATION", lpath + ".stable_projection_sha256", "invalid lowercase prefixed SHA-256"))
            completed_version = row.get("completed_at_phase_version")
            if not _is_int(completed_version):
                errors.append(_err("INVALID_DECLARATION", lpath + ".completed_at_phase_version", "invalid completed phase version"))
            elif completed_version == 0 and origin != "historical_recovery":
                errors.append(_err("INVALID_DECLARATION", lpath, "phase-0 adoption is historical-recovery only"))
            if storage == "immutable_member":
                if not _validate_digest(row.get("artifact_sha256")):
                    errors.append(_err("INVALID_DECLARATION", lpath + ".artifact_sha256", "invalid lowercase prefixed SHA-256"))
                if validate_artifacts and root is not None and isinstance(row.get("artifact_path"), str):
                    _validate_immutable_report(root, declaration, member, row, errors)
            else:
                raw, snapshot_digest = _decode_projection_snapshot(row.get("stable_projection_utf8_base64"), lpath + ".stable_projection_utf8_base64", errors)
                if raw is not None and row.get("stable_projection_sha256") != snapshot_digest:
                    errors.append(_err("DECLARATION_DIGEST_MISMATCH", lpath, "snapshot SHA does not match stable_projection_sha256"))
        state = phase_member.get("state")
        attempt_value = phase_member.get("attempt")
        if not _is_int(attempt_value, 1) or attempt_value != len(reservations) and not (state == "superseded" and not reservations and attempt_value == 1):
            errors.append(_err("INVALID_DECLARATION", base + ".attempt", "phase attempt must equal the latest contiguous reservation"))
        if state == "dispatched" and not (len(reservations) == 1 and not ledger and alias is None):
            errors.append(_err("INVALID_DECLARATION", base, "initial dispatched requires reservation 1, empty ledger, and null alias"))
        if state in {"dev_completed", "awaiting_qa", "needs_review", "qa_pass"} and (not ledger or alias is None or len(reservations) != len(ledger)):
            errors.append(_err("INVALID_DECLARATION", base, "active post-dev state requires a completed current attempt and no pending reservation"))
        if state == "retry_dispatched" and not (len(reservations) == len(ledger) + 1 and alias == len(ledger)):
            errors.append(_err("INVALID_DECLARATION", base, "retry_dispatched requires one pending reservation and retains the prior alias"))
        if state == "superseded" and not reservations and (origin != "historical_recovery" or phase_version != 0 or ledger or alias is not None):
            errors.append(_err("INVALID_DECLARATION", base, "only an audited phase-0 historical superseded member may have no attempt evidence"))
    if validate_artifacts and root is not None:
        declared_union = globally_reserved | {
            item["path"] for item in declaration.get("inventory", [])
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
        _reject_undeclared_retries(root, declaration, declared_union, errors)


def _validate_immutable_report(
    root: Path, declaration: dict[str, Any], member: dict[str, Any], row: dict[str, Any], errors: list[dict[str, str]]
) -> None:
    relative = row["artifact_path"]
    try:
        raw = _read_regular_file_bytes(root, relative)
        report = load_json_bytes(raw, relative)
    except ContractFailure as exc:
        errors.extend(exc.errors)
        return
    if _validate_declared_repo_paths(root, report, relative, errors) is None:
        return
    if _bytes_digest(raw) != row["artifact_sha256"]:
        errors.append(_err("STALE_CANONICAL", relative, "immutable attempt bytes changed after ledger promotion"))
    try:
        _, projection_digest = stable_dev_projection(report)
    except ContractFailure as exc:
        errors.extend(exc.errors)
        return
    if projection_digest != row["stable_projection_sha256"]:
        errors.append(_err("STALE_CANONICAL", relative, "immutable attempt stable projection changed"))
    expected_baseline = _baseline_for(declaration, member["member_id"])
    dirty = report.get("baseline_dirty_snapshot")
    if (report.get("baseline_head_sha") != expected_baseline["head_sha"]
            or not isinstance(dirty, str)
            or dirty.encode("utf-8") != expected_baseline["dirty_snapshot"].encode("utf-8")):
        errors.append(_err("BASELINE_MISMATCH", relative, "immutable attempt baseline does not byte-match dispatch evidence"))
    for identity_key in ("request_id", "task_id"):
        if report.get(identity_key) != member["member_id"]:
            errors.append(_err("INVALID_IDENTITY", relative, f"{identity_key} does not equal the exact member id"))
    dev = report.get("dev")
    if not isinstance(dev, dict) or dev.get("status") != "completed":
        errors.append(_err("INVALID_STATUS", relative, "immutable promoted report requires dev.status=completed"))
    binding = report.get("artifact_chain_binding")
    expected = {
        "parent_task_id": declaration["parent_task_id"],
        "member_id": member["member_id"],
        "lineage_digest": declaration["lineage_digest"],
        "attempt": row["attempt"],
    }
    phase_member = next(item for item in declaration["phase_projection"]["members"] if item["member_id"] == member["member_id"])
    reservation = phase_member["attempt_reservations"][row["attempt"] - 1]
    historical_adoption = declaration["origin"] == "historical_recovery" and row["attempt"] == 1 and reservation["expected_absent"] is False
    if historical_adoption:
        if binding is not None and (report.get("artifact_chain_role") != "lifecycle_declared_member" or binding != expected):
            errors.append(_err("INVALID_IDENTITY", relative, "present historical binding must exactly match the adopted lineage"))
    elif report.get("artifact_chain_role") != "lifecycle_declared_member" or binding != expected:
        errors.append(_err("INVALID_IDENTITY", relative, "member report role/binding does not exactly match immutable lineage and attempt"))


def _classify_undeclared_report(report: dict[str, Any], declaration: dict[str, Any]) -> tuple[str, str] | None:
    """Classify exact chain authority without using filename similarity."""
    parent = declaration["parent_task_id"]
    binding = report.get("artifact_chain_binding")
    exact_binding = (
        isinstance(binding, dict)
        and binding.get("parent_task_id") == parent
        and binding.get("lineage_digest") == declaration["lineage_digest"]
    )
    if exact_binding:
        return "exact_member_binding", "lineage-bound artifact is outside the immutable inventory/attempt union"
    embedded = report.get("artifact_chain_declaration")
    duplicate_authority = (
        isinstance(embedded, dict)
        and embedded.get("parent_task_id") == parent
        and embedded.get("lineage_digest") == declaration["lineage_digest"]
    )
    if duplicate_authority:
        return "duplicate_embedded_authority", "duplicate declaration authority is outside the immutable inventory/attempt union"
    exact_singular_sidecar = (
        declaration["shape"] == "singular"
        and report.get("request_id") == parent
        and report.get("task_id") == parent
        and report.get("artifact_chain_role") == "lifecycle_singular_parent"
    )
    if exact_singular_sidecar:
        return "exact_mutable_singular_identity", "exact-task mutable-singular report is outside its sole canonical reservation/ledger union"
    return None


def _scan_undeclared_json_reports(
    root: Path, allowed: set[str], declaration: dict[str, Any],
) -> list[dict[str, str]]:
    """Classify a stable no-follow snapshot of out-of-union real JSON files."""
    scan_errors: list[dict[str, str]] = []
    directory_fd: int | None = None
    try:
        directory_fd, directory_identity = _open_directory_beneath(root, "docs/dev")
        namespace_before = _file_fingerprint(os.fstat(directory_fd))
        names = sorted(os.listdir(directory_fd))
    except ContractFailure as exc:
        return exc.errors
    except OSError as exc:
        if directory_fd is not None:
            os.close(directory_fd)
        return [_err("IO_ERROR", "docs/dev", f"cannot enumerate report namespace: {exc}")]
    observed_files: dict[str, tuple[int, int, int, int, int, int]] = {}
    try:
        for name in names:
            relative = f"docs/dev/{name}"
            if relative in allowed or not name.endswith(".json"):
                continue
            try:
                metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                scan_errors.append(_err("INVENTORY_MISMATCH", relative, "out-of-union JSON changed during report discovery"))
                continue
            except OSError as exc:
                scan_errors.append(_err("IO_ERROR", relative, f"cannot inspect out-of-union JSON: {exc}"))
                continue
            if not stat.S_ISREG(metadata.st_mode):
                continue
            try:
                raw, observed = _read_regular_file_at(directory_fd, name, relative)
            except ContractFailure:
                scan_errors.append(_err("INVENTORY_MISMATCH", relative, "out-of-union JSON changed or became unsafe during report discovery"))
                continue
            if observed != _file_fingerprint(metadata):
                scan_errors.append(_err("INVENTORY_MISMATCH", relative, "out-of-union JSON was replaced during report discovery"))
                continue
            observed_files[name] = observed
            try:
                report = load_json_bytes(raw, relative)
            except ContractFailure:
                continue
            if type(report) is dict:
                classification = _classify_undeclared_report(report, declaration)
                if classification is not None:
                    kind, message = classification
                    scan_errors.append(_err("INVENTORY_MISMATCH", relative, f"{kind}: {message}"))
        for name, observed in observed_files.items():
            relative = f"docs/dev/{name}"
            try:
                current = _file_fingerprint(os.stat(name, dir_fd=directory_fd, follow_symlinks=False))
            except OSError:
                scan_errors.append(_err("INVENTORY_MISMATCH", relative, "out-of-union JSON changed after report discovery"))
                continue
            if current != observed:
                scan_errors.append(_err("INVENTORY_MISMATCH", relative, "out-of-union JSON changed after report discovery"))
        if _file_fingerprint(os.fstat(directory_fd)) != namespace_before:
            scan_errors.append(_err("INVENTORY_MISMATCH", "docs/dev", "report namespace changed during undeclared-artifact discovery"))
    finally:
        os.close(directory_fd)
    try:
        verify_fd, verify_identity = _open_directory_beneath(root, "docs/dev")
        os.close(verify_fd)
    except ContractFailure as exc:
        scan_errors.extend(exc.errors)
    else:
        if verify_identity != directory_identity:
            scan_errors.append(_err("INVENTORY_MISMATCH", "docs/dev", "report namespace changed during undeclared-artifact discovery"))
    return scan_errors


def _reject_undeclared_retries(root: Path, declaration: dict[str, Any], allowed: set[str], errors: list[dict[str, str]]) -> None:
    """Reject exact chain reports outside the declared union without filename authority."""
    errors.extend(_scan_undeclared_json_reports(root, allowed, declaration))


def _declared_artifact_union(declaration: dict[str, Any]) -> set[str]:
    """Return only explicit inventory and attempt-reservation authority."""
    allowed = {
        item["path"] for item in declaration["inventory"]
        if type(item) is dict and type(item.get("path")) is str
    }
    for member in declaration["phase_projection"]["members"]:
        if type(member) is not dict:
            continue
        for reservation in member.get("attempt_reservations", []):
            if type(reservation) is dict and type(reservation.get("artifact_path")) is str:
                allowed.add(reservation["artifact_path"])
    return allowed


def _validate_lineage_and_shape(
    declaration: dict[str, Any], by_kind: dict[str, dict[str, Any]],
    by_member_kind: dict[tuple[str, str], dict[str, Any]], errors: list[dict[str, str]],
) -> list[dict[str, Any]]:
    lineage = declaration.get("member_lineage")
    if not isinstance(lineage, list) or not lineage:
        errors.append(_err("INVALID_DECLARATION", "artifact_chain_declaration.member_lineage", "member_lineage must be non-empty"))
        return []
    starting_error_count = len(errors)
    seen: set[str] = set()
    shape = declaration["shape"]
    expected_kind = {"singular": "singular_parent", "parallel_dev": "parallel_worker", "requirement_fanout": "requirement_lane"}[shape]
    for index, member in enumerate(lineage):
        path = f"artifact_chain_declaration.member_lineage[{index}]"
        if not isinstance(member, dict) or set(member) != {"lineage_ordinal", "member_id", "member_kind", "artifact_paths", "baseline_binding_key"}:
            errors.append(_err("INVALID_DECLARATION", path, "member_lineage row has a closed schema"))
            continue
        member_id = member.get("member_id")
        lineage_ordinal = member.get("lineage_ordinal")
        if not _is_int(lineage_ordinal) or lineage_ordinal != index:
            errors.append(_err("INVALID_DECLARATION", path + ".lineage_ordinal", "lineage_ordinal must be the exact integer lineage index"))
            continue
        if not _safe_task_id(member_id) or member_id in seen or member.get("member_kind") != expected_kind:
            errors.append(_err("INVALID_DECLARATION", path, "invalid identity, uniqueness, or member_kind"))
            continue
        seen.add(member_id)
        paths = member.get("artifact_paths")
        if not isinstance(paths, dict) or set(paths) != {"ticket", "context", "dev_report", "qa_report"}:
            errors.append(_err("INVALID_DECLARATION", path + ".artifact_paths", "artifact_paths is a closed four-field object"))
            continue
        required_nonnull = {"dev_report"}
        if shape in {"singular", "requirement_fanout"}:
            required_nonnull = {"ticket", "context", "dev_report", "qa_report"}
        for name, value in paths.items():
            if value is not None and not _safe_rel_path(value):
                errors.append(_err("INVALID_DECLARATION", path + f".artifact_paths.{name}", "unsafe project-relative path"))
            if name in required_nonnull and not isinstance(value, str):
                errors.append(_err("SHAPE_ARTIFACT_MISMATCH", path, f"{name} must be non-null for {shape}"))
            if name not in required_nonnull and value is not None:
                errors.append(_err("SHAPE_ARTIFACT_MISMATCH", path, f"{name} must be null for {shape}"))
        kind_map = {
            "ticket": "lane_ticket", "context": "lane_context", "dev_report": "lane_dev_report", "qa_report": "lane_qa_report",
        } if shape == "requirement_fanout" else {"dev_report": "worker_dev_report"}
        if shape == "singular":
            parent_map = {"ticket": "parent_ticket", "context": "parent_context", "dev_report": "canonical_dev_report", "qa_report": "parent_qa_report"}
            for name, kind in parent_map.items():
                entry = by_kind.get(kind)
                if entry is None or entry["path"] != paths[name]:
                    errors.append(_err("INVENTORY_MISMATCH", path, f"{name} does not equal parent {kind} inventory"))
        else:
            for name, kind in kind_map.items():
                entry = by_member_kind.get((member_id, kind))
                if entry is None or entry["path"] != paths[name]:
                    errors.append(_err("INVENTORY_MISMATCH", path, f"{name} does not equal member {kind} inventory"))
    if len(errors) != starting_error_count:
        return []
    parent = declaration["parent_task_id"]
    parent_required = {"parent_ticket", "parent_context", "canonical_dev_report", "parent_qa_report", "parent_completion"}
    if shape == "singular":
        if len(lineage) != 1 or lineage[0].get("member_id") != parent or set(by_kind) != parent_required or by_member_kind:
            errors.append(_err("SHAPE_ARTIFACT_MISMATCH", "artifact_chain_declaration.inventory", "singular requires exactly its parent member and five parent artifacts"))
        if any(not entry["required"] for entry in by_kind.values()):
            errors.append(_err("SHAPE_ARTIFACT_MISMATCH", "artifact_chain_declaration.inventory", "singular parent artifacts are required"))
    elif shape == "parallel_dev":
        if len(lineage) < 2 or set(by_kind) != parent_required or len(by_member_kind) != len(lineage):
            errors.append(_err("SHAPE_ARTIFACT_MISMATCH", "artifact_chain_declaration.inventory", "parallel_dev requires parent five-pack plus one worker report per lineage member"))
        if any(not entry["required"] for entry in by_kind.values()) or any(kind != "worker_dev_report" or not entry["required"] for (_, kind), entry in by_member_kind.items()):
            errors.append(_err("SHAPE_ARTIFACT_MISMATCH", "artifact_chain_declaration.inventory", "parallel_dev topology entries are required"))
    else:
        required_parent = {"canonical_dev_report", "parent_completion"}
        optional_parent = {"parent_ticket", "parent_context", "parent_qa_report"}
        if len(lineage) < 2 or not required_parent.issubset(by_kind) or not set(by_kind).issubset(required_parent | optional_parent) or len(by_member_kind) != 4 * len(lineage):
            errors.append(_err("SHAPE_ARTIFACT_MISMATCH", "artifact_chain_declaration.inventory", "requirement_fanout requires lane four-packs and canonical/completion parent entries"))
        for kind, entry in by_kind.items():
            if entry["required"] != (kind in required_parent):
                errors.append(_err("SHAPE_ARTIFACT_MISMATCH", entry["path"], "optional fanout parent entries must be required=false"))
        if any(kind not in {"lane_ticket", "lane_context", "lane_dev_report", "lane_qa_report"} or not entry["required"] for (_, kind), entry in by_member_kind.items()):
            errors.append(_err("SHAPE_ARTIFACT_MISMATCH", "artifact_chain_declaration.inventory", "fanout lane four-pack entries are required"))
    canonical = by_kind.get("canonical_dev_report")
    completion = by_kind.get("parent_completion")
    expected_canonical = f"docs/dev/dev-report-{parent}.json"
    if canonical is None or canonical["path"] != expected_canonical:
        errors.append(_err("INVENTORY_MISMATCH", "artifact_chain_declaration.inventory", f"canonical path must be {expected_canonical}"))
    if completion is None:
        errors.append(_err("INVENTORY_MISMATCH", "artifact_chain_declaration.inventory", "parent completion entry is required in topology"))
    return lineage


def _fold_events(
    declaration: dict[str, Any], lineage: list[dict[str, Any]], errors: list[dict[str, str]]
) -> list[dict[str, Any]]:
    projection = declaration.get("phase_projection")
    if not isinstance(projection, dict) or set(projection) != {"phase_version", "members", "events", "phase_digest"}:
        errors.append(_err("INVALID_DECLARATION", "artifact_chain_declaration.phase_projection", "phase_projection has a closed four-field schema"))
        return []
    phase_version = projection.get("phase_version")
    members = projection.get("members")
    events = projection.get("events")
    if not _is_int(phase_version) or not isinstance(members, list) or not isinstance(events, list):
        errors.append(_err("INVALID_DECLARATION", "artifact_chain_declaration.phase_projection", "invalid phase_version/members/events types"))
        return members if isinstance(members, list) else []
    order = {member["member_id"]: member["lineage_ordinal"] for member in lineage if isinstance(member, dict) and "member_id" in member}
    states: dict[str, dict[str, Any]] = {}
    previous_key: tuple[int, int] | None = None
    seen_versions: set[int] = set()
    allowed_edges = {
        (None, "dispatched"), ("dispatched", "dev_completed"),
        ("dev_completed", "awaiting_qa"), ("awaiting_qa", "qa_pass"),
        ("awaiting_qa", "needs_review"), ("needs_review", "retry_dispatched"),
        ("retry_dispatched", "dev_completed"), ("needs_review", "superseded"),
    }
    for index, event in enumerate(events):
        path = f"artifact_chain_declaration.phase_projection.events[{index}]"
        if not isinstance(event, dict) or set(event) != EVENT_FIELDS:
            errors.append(_err("INVALID_PHASE_TRANSITION", path, "phase event has a closed schema"))
            continue
        version, ordinal = event.get("phase_version"), event.get("event_ordinal")
        member_id = event.get("member_id")
        from_state = event.get("from_state")
        to_state = event.get("to_state")
        if (not _is_int(version) or not _is_int(ordinal) or member_id not in order
                or from_state is not None and (not isinstance(from_state, str) or from_state not in PHASE_STATES)
                or not isinstance(to_state, str) or to_state not in PHASE_STATES
                or not _is_int(event.get("attempt"), 1)
                or not _validate_digest(event.get("evidence_digest"))):
            errors.append(_err("INVALID_PHASE_TRANSITION", path, "invalid event scalar type or identity"))
            continue
        key = (version, ordinal)
        if previous_key is not None and key <= previous_key:
            errors.append(_err("INVALID_PHASE_TRANSITION", path, "events must be strictly sorted by phase version and ordinal"))
        previous_key = key
        seen_versions.add(version)
        current = states.get(member_id)
        current_state = current["state"] if current else None
        current_attempt = current["attempt"] if current else 1
        edge = (event.get("from_state"), event.get("to_state"))
        historical_bootstrap = (
            declaration["origin"] == "historical_recovery" and version == 0
            and event.get("from_state") is None and event.get("to_state") == "superseded"
        )
        if edge not in allowed_edges and not historical_bootstrap:
            errors.append(_err("INVALID_PHASE_TRANSITION", path, f"forbidden edge {edge!r}"))
        if event.get("from_state") != current_state:
            errors.append(_err("INVALID_PHASE_TRANSITION", path, "from_state does not equal the deterministic prior fold"))
        expected_attempt = current_attempt + 1 if edge == ("needs_review", "retry_dispatched") else current_attempt
        if current is None:
            expected_attempt = 1
        if event.get("attempt") != expected_attempt:
            errors.append(_err("INVALID_PHASE_TRANSITION", path, "event attempt does not follow the exact retry rule"))
        if event.get("to_state") in TERMINAL_STATES and current_state in TERMINAL_STATES:
            errors.append(_err("INVALID_PHASE_TRANSITION", path, "terminal state is absorbing"))
        superseded = event.get("to_state") == "superseded"
        disposition = event.get("coverage_disposition")
        superseded_by = event.get("superseded_by")
        if superseded:
            if member_id == declaration["parent_task_id"] and declaration["shape"] == "singular":
                errors.append(_err("INVALID_PHASE_TRANSITION", path, "singular parent can never be superseded"))
            if superseded_by is None and (not isinstance(disposition, str) or not disposition.strip()):
                errors.append(_err("INVALID_PHASE_TRANSITION", path, "supersede requires superseded_by or non-empty coverage disposition"))
            if superseded_by is not None and (not _safe_task_id(superseded_by) or superseded_by not in order):
                errors.append(_err("INVALID_PHASE_TRANSITION", path, "superseded_by must be null or an exact member of the immutable lineage"))
            if disposition is not None and (not isinstance(disposition, str) or not disposition.strip()):
                errors.append(_err("INVALID_PHASE_TRANSITION", path, "coverage disposition must be null or a non-empty string"))
        elif superseded_by is not None or disposition is not None:
            errors.append(_err("INVALID_PHASE_TRANSITION", path, "non-supersede event forbids superseded fields"))
        states[member_id] = {
            "member_id": member_id, "state": event.get("to_state"),
            "attempt": event.get("attempt"), "evidence_digest": event.get("evidence_digest"),
            "superseded_by": superseded_by,
        }
    if set(states) != set(order):
        errors.append(_err("INVALID_PHASE_TRANSITION", "artifact_chain_declaration.phase_projection.events", "events must initialize every immutable lineage member"))
    if events and (max(seen_versions) != phase_version or min(seen_versions) != 0 or seen_versions != set(range(phase_version + 1))):
        errors.append(_err("INVALID_PHASE_TRANSITION", "artifact_chain_declaration.phase_projection", "event versions must be contiguous 0..phase_version"))
    if len(members) != len(lineage):
        errors.append(_err("INVALID_PHASE_TRANSITION", "artifact_chain_declaration.phase_projection.members", "one phase member is required per lineage row"))
    else:
        for index, member in enumerate(members):
            if not isinstance(member, dict) or member.get("member_id") != lineage[index]["member_id"]:
                errors.append(_err("INVALID_PHASE_TRANSITION", f"artifact_chain_declaration.phase_projection.members[{index}]", "phase members must be in immutable lineage order"))
                continue
            folded = states.get(member.get("member_id"))
            if folded is not None:
                for key in ("member_id", "state", "attempt", "evidence_digest", "superseded_by"):
                    if member.get(key) != folded[key]:
                        errors.append(_err("INVALID_PHASE_TRANSITION", f"artifact_chain_declaration.phase_projection.members[{index}].{key}", "phase member does not equal event fold"))
    return members


def _validate_attempt_event_links(declaration: dict[str, Any], errors: list[dict[str, str]]) -> None:
    events = declaration["phase_projection"]["events"]
    for member in declaration["phase_projection"]["members"]:
        for row in member["attempt_ledger"]:
            evidence = row.get("artifact_sha256", row.get("stable_projection_sha256"))
            historical_superseded_adoption = (
                declaration["origin"] == "historical_recovery"
                and member["state"] == "superseded"
                and row["attempt"] == 1
                and row["completed_at_phase_version"] == 0
            )
            completed = [event for event in events if event["member_id"] == member["member_id"] and event["attempt"] == row["attempt"] and event["to_state"] == "dev_completed"]
            if not historical_superseded_adoption and (len(completed) != 1
                    or completed[0]["phase_version"] != row["completed_at_phase_version"]
                    or completed[0]["evidence_digest"] != evidence):
                errors.append(_err("INVALID_PHASE_TRANSITION", row["artifact_path"], "ledger row must bind one exact dev_completed event/version/evidence digest"))
            awaiting = [event for event in events if event["member_id"] == member["member_id"] and event["attempt"] == row["attempt"] and event["to_state"] == "awaiting_qa"]
            if any(event["evidence_digest"] != evidence for event in awaiting):
                errors.append(_err("INVALID_PHASE_TRANSITION", row["artifact_path"], "awaiting_qa evidence must equal the discriminated ledger evidence digest"))
        for reservation in member["attempt_reservations"][1:]:
            retry = [event for event in events if event["member_id"] == member["member_id"] and event["attempt"] == reservation["attempt"] and event["to_state"] == "retry_dispatched"]
            if len(retry) != 1 or retry[0]["phase_version"] != reservation["reserved_at_phase_version"]:
                errors.append(_err("INVALID_PHASE_TRANSITION", reservation["artifact_path"], "retry reservation must be atomic with its retry_dispatched event"))


def _validate_rosters(declaration: dict[str, Any], members: list[dict[str, Any]], lineage: list[dict[str, Any]], errors: list[dict[str, str]]) -> None:
    roster_error_count = len(errors)
    roster_schemas = {
        "active_roster": {"ordinal", "member_id", "state", "attempt"},
        "excluded_roster": {"ordinal", "member_id", "state", "attempt", "evidence_digest", "superseded_by"},
    }
    for roster_name, fields in roster_schemas.items():
        roster = declaration.get(roster_name)
        roster_path = f"artifact_chain_declaration.{roster_name}"
        if not isinstance(roster, list):
            errors.append(_err("INVALID_DECLARATION", roster_path, f"{roster_name} must be an array"))
            continue
        for index, row in enumerate(roster):
            row_path = f"{roster_path}[{index}]"
            if not isinstance(row, dict) or set(row) != fields:
                errors.append(_err("INVALID_DECLARATION", row_path, f"{roster_name} row has a closed schema"))
                continue
            if not _is_int(row.get("ordinal")):
                errors.append(_err("INVALID_DECLARATION", row_path + ".ordinal", "roster ordinal must be an integer in range"))
            if not _is_int(row.get("attempt"), 1):
                errors.append(_err("INVALID_DECLARATION", row_path + ".attempt", "roster attempt must be an integer in range"))
    if len(errors) != roster_error_count:
        return

    active_expected: list[dict[str, Any]] = []
    excluded_expected: list[dict[str, Any]] = []
    for ordinal, member in enumerate(members):
        if not isinstance(member, dict):
            continue
        base = {"ordinal": ordinal, "member_id": member.get("member_id"), "state": member.get("state"), "attempt": member.get("attempt")}
        if member.get("state") == "superseded":
            excluded_expected.append({**base, "evidence_digest": member.get("evidence_digest"), "superseded_by": member.get("superseded_by")})
        else:
            active_expected.append(base)
    if declaration.get("active_roster") != active_expected:
        errors.append(_err("LANE_SET_MISMATCH", "artifact_chain_declaration.active_roster", "active_roster must be the exact deterministic phase projection"))
    if declaration.get("excluded_roster") != excluded_expected:
        errors.append(_err("LANE_SET_MISMATCH", "artifact_chain_declaration.excluded_roster", "excluded_roster must be the exact deterministic phase projection"))


def _validate_baselines(declaration: dict[str, Any], lineage: list[dict[str, Any]], errors: list[dict[str, str]]) -> None:
    policy = declaration.get("baseline_policy")
    bindings = declaration.get("baseline_bindings")
    if not isinstance(policy, str) or policy not in {"shared_dispatch", "per_member_dispatch"} or not isinstance(bindings, dict) or set(bindings) != {"shared", "by_member"}:
        errors.append(_err("MISSING_BASELINE_BINDING", "artifact_chain_declaration.baseline_bindings", "invalid baseline policy/bindings schema"))
        return
    shared, by_member = bindings["shared"], bindings["by_member"]
    if policy == "shared_dispatch":
        if not _validate_baseline(shared) or by_member != {}:
            errors.append(_err("MISSING_BASELINE_BINDING", "artifact_chain_declaration.baseline_bindings", "shared_dispatch requires one exact shared binding and an empty member map"))
        expected_key = "shared"
    else:
        if shared is not None or not isinstance(by_member, dict) or list(by_member) != [m["member_id"] for m in lineage] or any(not _validate_baseline(v) for v in by_member.values()):
            errors.append(_err("MISSING_BASELINE_BINDING", "artifact_chain_declaration.baseline_bindings", "per_member_dispatch requires the exact immutable-lineage ordered member map"))
        expected_key = None
    for member in lineage:
        wanted = expected_key if expected_key is not None else member["member_id"]
        if member.get("baseline_binding_key") != wanted:
            errors.append(_err("MISSING_BASELINE_BINDING", "artifact_chain_declaration.member_lineage", "baseline_binding_key does not select the declared policy binding"))
    shape, execution, origin = declaration["shape"], declaration["execution"], declaration["origin"]
    if shape == "singular":
        if execution != "sequential" or policy != "shared_dispatch":
            errors.append(_err("EXECUTION_POLICY_MISMATCH", "artifact_chain_declaration", "singular is a sequential singleton with shared dispatch evidence"))
    elif execution == "parallel":
        if policy != "shared_dispatch":
            errors.append(_err("EXECUTION_POLICY_MISMATCH", "artifact_chain_declaration", "parallel execution requires one shared immutable dispatch binding"))
    elif origin != "historical_recovery" or shape != "requirement_fanout" or policy != "per_member_dispatch":
        errors.append(_err("EXECUTION_POLICY_MISMATCH", "artifact_chain_declaration", "multi-member sequential is per-member audited historical requirement_fanout only"))
    if origin == "active_lifecycle" and shape != "singular" and execution != "parallel":
        errors.append(_err("EXECUTION_POLICY_MISMATCH", "artifact_chain_declaration", "active multi-member lifecycle execution must be parallel"))
    if shape == "parallel_dev" and origin != "active_lifecycle":
        errors.append(_err("EXECUTION_POLICY_MISMATCH", "artifact_chain_declaration", "parallel_dev is active_lifecycle only"))


def _validate_declaration_impl(
    candidate: Any, task_id: str, *, root: Path | None = None, validate_artifacts: bool = False,
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    errors: list[dict[str, str]] = []
    if not isinstance(candidate, dict):
        return None, [_err("INVALID_DECLARATION", "artifact_chain_declaration", "declaration must be an object")]
    declaration = copy.deepcopy(candidate)
    if set(declaration) != DECLARATION_FIELDS:
        missing = sorted(DECLARATION_FIELDS - set(declaration))
        unknown = sorted(set(declaration) - DECLARATION_FIELDS)
        errors.append(_err("INVALID_DECLARATION", "artifact_chain_declaration", f"closed schema mismatch; missing={missing}, unknown={unknown}"))
        return None, errors
    if declaration.get("schema_version") != DECLARATION_VERSION:
        errors.append(_err("UNSUPPORTED_DECLARATION_VERSION", "artifact_chain_declaration.schema_version", f"expected {DECLARATION_VERSION}"))
    if not _safe_task_id(task_id) or declaration.get("parent_task_id") != task_id:
        errors.append(_err("INVALID_IDENTITY", "artifact_chain_declaration.parent_task_id", "declaration parent must exactly equal the requested safe task id"))
    if (not isinstance(declaration.get("shape"), str) or declaration.get("shape") not in SHAPES
            or not isinstance(declaration.get("execution"), str) or declaration.get("execution") not in {"parallel", "sequential"}
            or not isinstance(declaration.get("origin"), str) or declaration.get("origin") not in {"active_lifecycle", "historical_recovery"}):
        errors.append(_err("INVALID_DECLARATION", "artifact_chain_declaration", "invalid shape, execution, or origin enum"))
        return None, errors
    by_kind, by_member_kind = _validate_inventory(declaration, errors)
    if errors:
        return None, errors
    lineage = _validate_lineage_and_shape(declaration, by_kind, by_member_kind, errors)
    if errors:
        return None, errors
    _validate_baselines(declaration, lineage, errors)
    if errors:
        return None, errors
    members = _fold_events(declaration, lineage, errors)
    if errors:
        return None, errors
    _validate_attempts(declaration, lineage, members, errors, root, validate_artifacts)
    if errors:
        return None, errors
    _validate_attempt_event_links(declaration, errors)
    if errors:
        return None, errors
    _validate_rosters(declaration, members, lineage, errors)
    if errors:
        return None, errors
    inventory_digest = _digest(declaration["inventory"])
    if declaration.get("inventory_digest") != inventory_digest:
        errors.append(_err("INVENTORY_DIGEST_MISMATCH", "artifact_chain_declaration.inventory_digest", f"expected {inventory_digest}"))
    lineage_payload = {
        key: declaration[key]
        for key in ("schema_version", "parent_task_id", "shape", "execution", "origin", "member_lineage", "inventory", "inventory_digest", "baseline_policy", "baseline_bindings")
    }
    lineage_digest = _digest(lineage_payload)
    if declaration.get("lineage_digest") != lineage_digest:
        errors.append(_err("LINEAGE_DIGEST_MISMATCH", "artifact_chain_declaration.lineage_digest", f"expected {lineage_digest}"))
    projection = declaration.get("phase_projection")
    if isinstance(projection, dict) and {"phase_version", "members", "events"}.issubset(projection):
        phase_digest = _digest({
            "lineage_digest": lineage_digest,
            "phase_version": projection["phase_version"],
            "members": projection["members"],
            "events": projection["events"],
        })
        if projection.get("phase_digest") != phase_digest:
            errors.append(_err("PHASE_DIGEST_MISMATCH", "artifact_chain_declaration.phase_projection.phase_digest", f"expected {phase_digest}"))
    else:
        phase_digest = None
    without_digest = {key: value for key, value in declaration.items() if key != "declaration_digest"}
    declaration_digest = _digest(without_digest)
    if declaration.get("declaration_digest") != declaration_digest:
        errors.append(_err("DECLARATION_DIGEST_MISMATCH", "artifact_chain_declaration.declaration_digest", f"expected {declaration_digest}"))
    return (declaration if not errors else None), errors


def validate_declaration(
    candidate: Any, task_id: str, *, root: Path | None = None, validate_artifacts: bool = False,
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    """Fail-closed public declaration validator for arbitrary JSON values."""
    try:
        return _validate_declaration_impl(
            candidate, task_id, root=root, validate_artifacts=validate_artifacts,
        )
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        return None, [_err("INVALID_DECLARATION", "artifact_chain_declaration", f"malformed declaration value: {exc}")]


def finalize_declaration(candidate: dict[str, Any]) -> dict[str, Any]:
    """Compute digest fields for a structurally complete draft.

    This is a producer convenience used by tests/documented callers.  Validation
    still rejects missing digest fields at the public provider boundary.
    """
    value = copy.deepcopy(candidate)
    value["inventory_digest"] = _digest(value["inventory"])
    value["lineage_digest"] = _digest({
        key: value[key]
        for key in ("schema_version", "parent_task_id", "shape", "execution", "origin", "member_lineage", "inventory", "inventory_digest", "baseline_policy", "baseline_bindings")
    })
    projection = value["phase_projection"]
    projection["phase_digest"] = _digest({
        "lineage_digest": value["lineage_digest"], "phase_version": projection["phase_version"],
        "members": projection["members"], "events": projection["events"],
    })
    value["declaration_digest"] = _digest({key: val for key, val in value.items() if key != "declaration_digest"})
    return value


def _read_report_snapshot(
    root: Path, relative: str, errors: list[dict[str, str]], *, required: bool = True,
) -> tuple[dict[str, Any] | None, bytes | None, dict[str, Any] | None]:
    try:
        raw, fingerprint = _read_regular_file_snapshot(root, relative)
    except ContractFailure as exc:
        if required or any(item["code"] != "MISSING_ARTIFACT" for item in exc.errors):
            errors.extend(exc.errors)
        return None, None, None
    try:
        binding = {
            "fingerprint": fingerprint,
            "sha256": _bytes_digest(raw, prefixed=False),
        }
        return load_json_bytes(raw, relative), raw, binding
    except ContractFailure as exc:
        errors.extend(exc.errors)
    return None, None, None


def _read_report(
    root: Path, relative: str, errors: list[dict[str, str]], *, required: bool = True,
) -> tuple[dict[str, Any] | None, bytes | None]:
    report, raw, _ = _read_report_snapshot(root, relative, errors, required=required)
    return report, raw


def _dev_status(report: dict[str, Any], path: str, errors: list[dict[str, str]]) -> None:
    dev = report.get("dev")
    nested = dev.get("status") if isinstance(dev, dict) else None
    if nested != "completed":
        errors.append(_err("INVALID_STATUS", path, f"dev.status is {nested!r}; expected 'completed'"))
    if "status" in report and report.get("status") != "completed":
        errors.append(_err("INVALID_STATUS", path, "flat status must project completed"))
    if isinstance(dev, dict):
        for key in ("files_modified", "files_created"):
            if not isinstance(dev.get(key), list) or any(not isinstance(v, str) or not v for v in dev.get(key, [])):
                errors.append(_err("INVALID_STATUS", path, f"dev.{key} must be a list of non-empty strings"))
    _validate_blockers(report.get("blocking_issues", []), path, errors)


def _validate_blockers(value: Any, path: str, errors: list[dict[str, str]]) -> None:
    if not isinstance(value, list):
        errors.append(_err("INVALID_BLOCKING_ISSUES", path, "blocking_issues must be an array"))
        return
    seen: set[str] = set()
    for index, item in enumerate(value):
        ipath = f"{path}#blocking_issues[{index}]"
        fields = {"issue_id", "code", "state", "message", "evidence_digest"}
        if not isinstance(item, dict) or set(item) != fields:
            errors.append(_err("INVALID_BLOCKING_ISSUES", ipath, "blocking issue has a closed schema"))
            continue
        if (not isinstance(item["issue_id"], str) or not item["issue_id"] or item["issue_id"] in seen
                or not isinstance(item["code"], str) or BLOCKER_CODE_RE.fullmatch(item["code"]) is None
                or not isinstance(item["state"], str) or item["state"] not in {"open", "resolved"}
                or not isinstance(item["message"], str) or not item["message"]
                or not _validate_digest(item["evidence_digest"])):
            errors.append(_err("INVALID_BLOCKING_ISSUES", ipath, "invalid or duplicate structured blocker"))
            continue
        seen.add(item["issue_id"])
        if item["state"] == "open":
            errors.append(_err("UNRESOLVED_BLOCKERS", path, f"open blocker {item['issue_id']}"))


def _identity(report: dict[str, Any], expected: str, path: str, errors: list[dict[str, str]]) -> None:
    for key in ("request_id", "task_id"):
        if report.get(key) != expected:
            errors.append(_err("INVALID_IDENTITY", path, f"{key} is {report.get(key)!r}; expected {expected!r}"))


def _member_current_row(phase_member: dict[str, Any]) -> dict[str, Any] | None:
    ledger = phase_member.get("attempt_ledger")
    alias = phase_member.get("current_attempt")
    if not isinstance(ledger, list) or not ledger or alias is None:
        return None
    row = ledger[-1]
    return row if isinstance(row, dict) and row.get("attempt") == alias else None


def _baseline_for(declaration: dict[str, Any], member_id: str) -> dict[str, str]:
    bindings = declaration["baseline_bindings"]
    return bindings["shared"] if declaration["baseline_policy"] == "shared_dispatch" else bindings["by_member"][member_id]


def _load_active_sources(
    root: Path, declaration: dict[str, Any], errors: list[dict[str, str]],
    *, with_bindings: bool = False,
) -> Any:
    phase_by_id = {m["member_id"]: m for m in declaration["phase_projection"]["members"]}
    sources: list[tuple[str, dict[str, Any], bytes]] = []
    bindings: dict[str, dict[str, Any]] = {}
    for member in declaration["member_lineage"]:
        phase = phase_by_id[member["member_id"]]
        if phase["state"] == "superseded":
            continue
        current = _member_current_row(phase)
        relative = current["artifact_path"] if current else member["artifact_paths"]["dev_report"]
        report, raw, source_binding = _read_report_snapshot(root, relative, errors)
        if report is None or raw is None or source_binding is None:
            continue
        if _validate_declared_repo_paths(root, report, relative, errors) is None:
            continue
        _identity(report, member["member_id"], relative, errors)
        _dev_status(report, relative, errors)
        baseline = _baseline_for(declaration, member["member_id"])
        if report.get("baseline_head_sha") != baseline["head_sha"] or not isinstance(report.get("baseline_dirty_snapshot"), str) or report.get("baseline_dirty_snapshot").encode("utf-8") != baseline["dirty_snapshot"].encode("utf-8"):
            errors.append(_err("BASELINE_MISMATCH", relative, "report baseline does not byte-match immutable dispatch evidence"))
        if member["member_kind"] != "singular_parent":
            artifact_binding = report.get("artifact_chain_binding")
            expected = {"parent_task_id": declaration["parent_task_id"], "member_id": member["member_id"], "lineage_digest": declaration["lineage_digest"], "attempt": phase["current_attempt"]}
            reservation = phase["attempt_reservations"][phase["current_attempt"] - 1] if phase["current_attempt"] is not None else None
            historical_adoption = declaration["origin"] == "historical_recovery" and phase["current_attempt"] == 1 and reservation is not None and reservation["expected_absent"] is False
            if historical_adoption:
                if artifact_binding is not None and (report.get("artifact_chain_role") != "lifecycle_declared_member" or artifact_binding != expected):
                    errors.append(_err("INVALID_IDENTITY", relative, "present historical member binding mismatch"))
            elif report.get("artifact_chain_role") != "lifecycle_declared_member" or artifact_binding != expected:
                errors.append(_err("INVALID_IDENTITY", relative, "member artifact-chain role/binding mismatch"))
        sources.append((member["member_id"], report, raw))
        bindings[relative] = source_binding
    return (sources, bindings) if with_bindings else sources


def _validate_shards(shards: list[tuple[str, dict[str, Any]]], task_id: str) -> list[str]:
    """Frozen SCHEMA compatibility boundary for already-loaded legacy shards.

    New R1 mutation paths never call this classifier; declarations are their
    sole authority. The function remains for projection consumers that verify
    nested dev semantics without performing a write.
    """
    errors: list[str] = []
    head: Any = None
    dirty: Any = None
    labels: set[str] = set()
    for label, report in shards:
        if label in labels:
            errors.append(f"duplicate worker label {label!r}")
        labels.add(label)
        identity = report.get("task_id") or report.get("request_id")
        if identity != task_id:
            errors.append(f"shard {label!r}: identity {identity!r} != {task_id!r}")
        dev = report.get("dev")
        if not isinstance(dev, dict) or dev.get("status") != "completed":
            errors.append(f"shard {label!r}: dev.status must be completed")
        if "baseline_head_sha" not in report or not report.get("baseline_head_sha"):
            errors.append(f"shard {label!r}: baseline_head_sha is missing or empty")
        elif head is None:
            head = report["baseline_head_sha"]
        elif report["baseline_head_sha"] != head:
            errors.append(f"shard {label!r}: baseline_head_sha mismatch")
        if "baseline_dirty_snapshot" not in report or not isinstance(report.get("baseline_dirty_snapshot"), str):
            errors.append(f"shard {label!r}: baseline_dirty_snapshot is missing or invalid")
        elif dirty is None:
            dirty = report["baseline_dirty_snapshot"]
        elif report["baseline_dirty_snapshot"].encode("utf-8") != dirty.encode("utf-8"):
            errors.append(f"shard {label!r}: baseline_dirty_snapshot mismatch")
    return errors


def _legacy_build_aggregate(shards: list[tuple[str, dict[str, Any]]], task_id: str) -> dict[str, Any]:
    files_modified: list[Any] = []
    files_created: list[Any] = []
    def legacy_union(keys: tuple[str, ...]) -> list[Any]:
        out: list[Any] = []
        seen: set[bytes] = set()
        for _, report in shards:
            value: Any = report
            for key in keys:
                value = value.get(key) if isinstance(value, dict) else None
            if not isinstance(value, list):
                continue
            for item in value:
                marker = _canonical_bytes(item)
                if marker not in seen:
                    seen.add(marker); out.append(copy.deepcopy(item))
        return out
    files_modified = legacy_union(("dev", "files_modified"))
    files_created = legacy_union(("dev", "files_created"))
    first = shards[0][1]
    root_text = first.get("dev", {}).get("git_rationale", {}).get("how_fix_addresses_root") or "Declaration-bound aggregate compatibility projection."
    ac_status: dict[str, Any] = {}
    for _, report in shards:
        value = report.get("dev", {}).get("ac_status")
        if isinstance(value, dict):
            ac_status.update(copy.deepcopy(value))
    return {
        "report_version": 1, "request_id": task_id, "task_id": task_id,
        "status": "completed", "files_modified": copy.deepcopy(files_modified),
        "files_created": copy.deepcopy(files_created), "root_cause_addressed": root_text,
        "ac_status": copy.deepcopy(ac_status), "timestamp": datetime.now(timezone.utc).isoformat(),
        "baseline_head_sha": first.get("baseline_head_sha"),
        "baseline_dirty_snapshot": first.get("baseline_dirty_snapshot"),
        "dev_report_path": f"docs/dev/dev-report-{task_id}.json",
        "parallel_workers": [label for label, _ in shards],
        "dev": {"status": "completed", "files_modified": files_modified, "files_created": files_created,
                "ac_status": ac_status, "tasks_completed": legacy_union(("dev", "tasks_completed")),
                "scripts_created": legacy_union(("dev", "scripts_created")),
                "permissions_to_add": legacy_union(("dev", "permissions_to_add")),
                "observed_preexisting": legacy_union(("dev", "observed_preexisting")),
                "git_rationale": {"how_fix_addresses_root": root_text}},
        "blocking_issues": legacy_union(("blocking_issues",)),
        "recommendations": legacy_union(("recommendations",)),
    }


def _union(sources: list[tuple[str, dict[str, Any], bytes]], keys: tuple[str, ...]) -> list[Any]:
    out: list[Any] = []
    seen: set[bytes] = set()
    for _, report, _ in sources:
        value: Any = report
        for key in keys:
            value = value.get(key) if isinstance(value, dict) else None
        if not isinstance(value, list):
            continue
        for item in value:
            marker = _canonical_bytes(item)
            if marker not in seen:
                seen.add(marker)
                out.append(copy.deepcopy(item))
    return out


def _build_aggregate(
    sources: list[tuple[str, dict[str, Any], bytes]] | list[tuple[str, dict[str, Any]]], task_id: str,
    declaration: dict[str, Any] | None = None, *, timestamp: str | None = None,
) -> dict[str, Any]:
    if declaration is None:
        return _legacy_build_aggregate(sources, task_id)  # frozen SCHEMA compatibility projection
    baseline = declaration["baseline_bindings"]["shared"] if declaration["baseline_policy"] == "shared_dispatch" else None
    files_modified = _union(sources, ("dev", "files_modified"))
    files_created = _union(sources, ("dev", "files_created"))
    ac_status: dict[str, Any] = {}
    rationales: list[str] = []
    for _, report, _ in sources:
        dev = report.get("dev") if isinstance(report.get("dev"), dict) else {}
        if isinstance(dev.get("ac_status"), dict):
            ac_status.update(copy.deepcopy(dev["ac_status"]))
        rationale = dev.get("git_rationale", {}).get("how_fix_addresses_root") if isinstance(dev.get("git_rationale"), dict) else None
        if isinstance(rationale, str) and rationale and rationale not in rationales:
            rationales.append(rationale)
    root_cause = " ".join(rationales) or "Parallel members completed the declaration-bound implementation."
    evidence_sources = []
    phase_by_id = {m["member_id"]: m for m in declaration["phase_projection"]["members"]}
    for member_id, report, raw in sources:
        _, stable_hash = stable_dev_projection(report)
        current = _member_current_row(phase_by_id[member_id])
        evidence_sources.append({
            "member_id": member_id,
            "path": current["artifact_path"] if current else next(m["artifact_paths"]["dev_report"] for m in declaration["member_lineage"] if m["member_id"] == member_id),
            "artifact_sha256": _bytes_digest(raw), "stable_projection_sha256": stable_hash,
        })
    document = {
        "report_version": 1,
        "request_id": task_id,
        "task_id": task_id,
        "status": "completed",
        "files_modified": copy.deepcopy(files_modified),
        "files_created": copy.deepcopy(files_created),
        "root_cause_addressed": root_cause,
        "ac_status": copy.deepcopy(ac_status),
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "baseline_head_sha": baseline["head_sha"] if baseline else None,
        "baseline_dirty_snapshot": baseline["dirty_snapshot"] if baseline else None,
        "dev_report_path": f"docs/dev/dev-report-{task_id}.json",
        "parallel_workers": [member_id for member_id, _, _ in sources],
        "artifact_chain_evidence": {
            "schema_version": "artifact_chain_evidence.v1",
            "lineage_digest": declaration["lineage_digest"],
            "phase_digest": declaration["phase_projection"]["phase_digest"],
            "baseline_evidence": copy.deepcopy(declaration["baseline_bindings"]),
            "source_reports": evidence_sources,
        },
        "artifact_chain_declaration": copy.deepcopy(declaration),
        "dev": {
            "status": "completed", "tasks_completed": _union(sources, ("dev", "tasks_completed")),
            "scripts_created": _union(sources, ("dev", "scripts_created")),
            "permissions_to_add": _union(sources, ("dev", "permissions_to_add")),
            "files_modified": copy.deepcopy(files_modified), "files_created": copy.deepcopy(files_created),
            "observed_preexisting": _union(sources, ("dev", "observed_preexisting")),
            "ac_status": copy.deepcopy(ac_status),
            "git_rationale": {"how_fix_addresses_root": root_cause},
        },
        "blocking_issues": _union(sources, ("blocking_issues",)),
        "recommendations": _union(sources, ("recommendations",)),
    }
    return document


def _canonical_projection(document: dict[str, Any]) -> dict[str, Any]:
    return {key: copy.deepcopy(value) for key, value in document.items() if key != "timestamp"}


def _validate_transition(old: dict[str, Any], new: dict[str, Any], errors: list[dict[str, str]]) -> None:
    immutable_keys = {"schema_version", "parent_task_id", "shape", "execution", "origin", "member_lineage", "lineage_digest", "inventory", "inventory_digest", "baseline_policy", "baseline_bindings"}
    if any(old.get(key) != new.get(key) for key in immutable_keys):
        errors.append(_err("DECLARATION_CONFLICT", "artifact_chain_declaration", "lawful update may not alter immutable lineage/topology/baselines"))
        return
    op, np = old["phase_projection"], new["phase_projection"]
    if np == op:
        if new != old:
            errors.append(_err("DECLARATION_CONFLICT", "artifact_chain_declaration", "phase-preserving refresh must preserve the entire declaration"))
        return
    if np["phase_version"] != op["phase_version"] + 1 or np["events"][:len(op["events"])] != op["events"] or not np["events"][len(op["events"]):]:
        errors.append(_err("INVALID_PHASE_TRANSITION", "artifact_chain_declaration.phase_projection", "update requires current+1 and an exact prior-event prefix"))
    old_members = {m["member_id"]: m for m in op["members"]}
    for member in np["members"]:
        prior = old_members.get(member["member_id"])
        if prior is None:
            continue
        for field in ("attempt_reservations", "attempt_ledger"):
            previous = prior[field]
            current = member[field]
            if current[:len(previous)] != previous:
                errors.append(_err("INVALID_PHASE_TRANSITION", f"artifact_chain_declaration.phase_projection.members.{field}", "attempt evidence is append-only"))
    _validate_qa_evidence_for_transition(old, new, errors)


def _validate_parallel_outcomes_for_transition(old: dict[str, Any], new: dict[str, Any], errors: list[dict[str, str]]) -> None:
    if new["shape"] != "parallel_dev":
        return
    qa_events = [e for e in new["phase_projection"]["events"][len(old["phase_projection"]["events"]):] if e["to_state"] in {"qa_pass", "needs_review"}]
    if not qa_events:
        return
    qa_entry = next((i for i in new["inventory"] if i["kind"] == "parent_qa_report" and i["member_id"] is None), None)
    root = new.get("__validation_root")
    if qa_entry is None or not isinstance(root, Path):
        return
    report_errors: list[dict[str, str]] = []
    report, raw = _read_report(root, qa_entry["path"], report_errors)
    errors.extend(report_errors)
    if report is None or raw is None:
        return
    _identity(report, new["parent_task_id"], qa_entry["path"], errors)
    outcomes, outcome_errors = validate_parallel_worker_outcomes(report, old)
    errors.extend(outcome_errors)
    if outcomes is None:
        return
    event_map = {e["member_id"]: "pass" if e["to_state"] == "qa_pass" else "needs_review" for e in qa_events}
    old_states = {member["member_id"]: member["state"] for member in old["phase_projection"]["members"] if member["state"] != "superseded"}
    expected_events = {member_id: outcome for member_id, outcome in outcomes.items() if old_states.get(member_id) != ("qa_pass" if outcome == "pass" else "needs_review")}
    if event_map != expected_events:
        errors.append(_err("INVALID_PHASE_TRANSITION", qa_entry["path"], "parent QA outcomes do not equal the required appended member QA transitions"))
    for member_id, outcome in outcomes.items():
        if old_states.get(member_id) in TERMINAL_STATES and not (old_states[member_id] == "qa_pass" and outcome == "pass"):
            errors.append(_err("INVALID_PHASE_TRANSITION", qa_entry["path"], "parent QA outcome contradicts an absorbing member state"))
    digest = _bytes_digest(raw)
    for event in qa_events:
        if event["evidence_digest"] != digest:
            errors.append(_err("INVALID_PHASE_TRANSITION", qa_entry["path"], "QA event evidence digest does not equal exact QA-report bytes"))


def _validate_qa_evidence_for_transition(old: dict[str, Any], new: dict[str, Any], errors: list[dict[str, str]]) -> None:
    """Bind every appended QA transition to its exact declared QA artifact."""
    if new["shape"] == "parallel_dev":
        _validate_parallel_outcomes_for_transition(old, new, errors)
        return
    appended = new["phase_projection"]["events"][len(old["phase_projection"]["events"]):]
    qa_events = [event for event in appended if event["to_state"] in {"qa_pass", "needs_review"}]
    if not qa_events:
        return
    root = new.get("__validation_root")
    if not isinstance(root, Path):
        return
    lineage = {member["member_id"]: member for member in new["member_lineage"]}
    cache: dict[str, tuple[dict[str, Any], bytes] | None] = {}
    for event in qa_events:
        if new["shape"] == "singular":
            entry = next((item for item in new["inventory"] if item["kind"] == "parent_qa_report" and item["member_id"] is None), None)
            expected_identity = new["parent_task_id"]
            relative = entry["path"] if entry is not None else ""
        else:
            member = lineage[event["member_id"]]
            expected_identity = event["member_id"]
            relative = member["artifact_paths"]["qa_report"]
        if not relative:
            errors.append(_err("MISSING_ARTIFACT", "artifact_chain_declaration.inventory", "QA transition has no exact declared QA path"))
            continue
        if relative not in cache:
            local_errors: list[dict[str, str]] = []
            report, raw = _read_report(root, relative, local_errors)
            errors.extend(local_errors)
            cache[relative] = (report, raw) if report is not None and raw is not None else None
        pair = cache[relative]
        if pair is None:
            continue
        report, raw = pair
        _identity(report, expected_identity, relative, errors)
        if "parallel_dev_worker_outcomes" in report:
            errors.append(_err("INVALID_STATUS", relative, "parallel worker outcomes are forbidden outside parallel-dev parent QA"))
        qa = report.get("qa")
        expected_status = "pass" if event["to_state"] == "qa_pass" else "needs_review"
        if not isinstance(qa, dict) or qa.get("status") != expected_status:
            errors.append(_err("INVALID_STATUS", relative, f"QA status must be {expected_status!r} for {event['to_state']}"))
        if event["evidence_digest"] != _bytes_digest(raw):
            errors.append(_err("INVALID_PHASE_TRANSITION", relative, "QA transition does not bind the exact declared QA-report bytes"))


def validate_parallel_worker_outcomes(report: dict[str, Any], declaration_before: dict[str, Any]) -> tuple[dict[str, str] | None, list[dict[str, str]]]:
    errors: list[dict[str, str]] = []
    value = report.get("parallel_dev_worker_outcomes")
    path = "parallel_dev_worker_outcomes"
    required = {"schema_version", "parent_task_id", "lineage_digest", "phase_digest_before", "coverage", "default_outcome", "worker_outcomes"}
    if not isinstance(value, dict) or set(value) != required:
        return None, [_err("INVALID_STATUS", path, "parallel-dev parent QA requires the closed parallel_dev_worker_outcomes.v1 object")]
    if value["schema_version"] != OUTCOMES_VERSION or value["parent_task_id"] != declaration_before["parent_task_id"] or value["lineage_digest"] != declaration_before["lineage_digest"] or value["phase_digest_before"] != declaration_before["phase_projection"]["phase_digest"]:
        errors.append(_err("INVALID_IDENTITY", path, "parent/lineage/phase identity is stale or mismatched"))
    active = [m["member_id"] for m in declaration_before["phase_projection"]["members"] if m["state"] != "superseded"]
    rows = value.get("worker_outcomes")
    if not isinstance(rows, list):
        errors.append(_err("INVALID_STATUS", path, "worker_outcomes must be an array"))
        return None, errors
    observed: list[str] = []
    expanded: dict[str, str] = {}
    for index, row in enumerate(rows):
        if (not isinstance(row, dict) or set(row) != {"member_id", "outcome"}
                or not isinstance(row.get("member_id"), str)
                or not isinstance(row.get("outcome"), str)
                or row.get("outcome") not in {"pass", "needs_review"}):
            errors.append(_err("INVALID_STATUS", f"{path}.worker_outcomes[{index}]", "outcome row is a closed exact member/outcome object"))
            continue
        member = row["member_id"]
        if member not in active or member in observed:
            errors.append(_err("INVALID_IDENTITY", path, "outcome member is unknown, excluded, or duplicated"))
        observed.append(member)
        expanded[member] = row["outcome"]
    if observed != [member for member in active if member in observed]:
        errors.append(_err("INVALID_STATUS", path, "outcome rows must preserve immutable lineage order"))
    coverage = value.get("coverage")
    default = value.get("default_outcome")
    if coverage == "all":
        if default is not None or observed != active:
            errors.append(_err("INVALID_STATUS", path, "coverage=all requires every active member exactly once and null default"))
    elif coverage == "subset":
        if not observed or len(observed) >= len(active) or not isinstance(default, str) or default not in {"pass", "needs_review"}:
            errors.append(_err("INVALID_STATUS", path, "coverage=subset requires a proper non-empty subset and explicit default"))
        for member in active:
            expanded.setdefault(member, default)
    else:
        errors.append(_err("INVALID_STATUS", path, "coverage must be all or subset"))
    if errors:
        return None, errors
    ordered = {member: expanded[member] for member in active}
    expected_status = "pass" if all(outcome == "pass" for outcome in ordered.values()) else "needs_review"
    qa = report.get("qa")
    if not isinstance(qa, dict) or qa.get("status") != expected_status:
        return None, [_err("INVALID_STATUS", "qa.status", f"parallel parent QA status must be {expected_status!r} for the expanded worker outcomes")]
    return ordered, []


def _validate_existing_injection(
    root: Path, existing: dict[str, Any], declaration: dict[str, Any], errors: list[dict[str, str]],
) -> dict[str, dict[str, Any]]:
    """Validate a declarationless canonical before an inject-only mutation."""
    relative = f"docs/dev/dev-report-{declaration['parent_task_id']}.json"
    _identity(existing, declaration["parent_task_id"], relative, errors)
    _dev_status(existing, relative, errors)
    if existing.get("artifact_chain_role") == "overnight_pipeline_intermediate":
        errors.append(_err("NON_LIFECYCLE_REPORT", relative, "overnight intermediate cannot be adopted as a lifecycle canonical"))
    if declaration["shape"] == "singular":
        baseline = _baseline_for(declaration, declaration["parent_task_id"])
        dirty = existing.get("baseline_dirty_snapshot")
        if (existing.get("baseline_head_sha") != baseline["head_sha"]
                or not isinstance(dirty, str)
                or dirty.encode("utf-8") != baseline["dirty_snapshot"].encode("utf-8")):
            errors.append(_err("BASELINE_MISMATCH", relative, "singular canonical baseline does not byte-match declaration evidence"))
        return {}
    sources, bindings = _load_active_sources(root, declaration, errors, with_bindings=True)
    if len(sources) != len(declaration["active_roster"]):
        if not errors:
            errors.append(_err("INSUFFICIENT_SOURCE_ARTIFACTS", relative, "not every active declared source is available for injection validation"))
        return bindings
    expected = _build_aggregate(sources, declaration["parent_task_id"], declaration, timestamp=existing.get("timestamp"))
    ignored = {"artifact_chain_declaration", "artifact_chain_evidence", "timestamp"}
    core_keys = set(expected) - ignored
    if any(existing.get(key) != expected.get(key) for key in core_keys):
        errors.append(_err("STALE_CANONICAL", relative, "declarationless aggregate core does not equal the deterministic declared source projection"))
    return bindings


def _provider_result(root: Path | str, task_id: str) -> dict[str, Any]:
    root_text = str(root)
    return {
        "schema_version": PROVIDER_VERSION, "status": "fail", "action": "none",
        "project_root": root_text, "task_id": task_id,
        "canonical_path": f"docs/dev/dev-report-{task_id}.json" if _safe_task_id(task_id) else None,
        "declaration": None, "lineage_digest": None, "phase_version": None,
        "phase_digest": None, "declaration_digest": None, "changed": False,
        "mutation_state": "none", "linearization_point": None,
        "previous_canonical_sha256": None, "observed_canonical_sha256": None,
        "errors": [],
    }


def _valid_root(project_root: Path | str) -> tuple[Path | None, list[dict[str, str]]]:
    try:
        supplied = Path(project_root)
        if not supplied.exists() or not supplied.is_dir():
            return None, [_err("INVALID_PROJECT_ROOT", str(project_root), "project root must exist and be a directory")]
        root = supplied.resolve(strict=True)
        docs_dir = root / "docs"
        dev_dir = docs_dir / "dev"
        if (not docs_dir.is_dir() or docs_dir.is_symlink()
                or not dev_dir.is_dir() or dev_dir.is_symlink()):
            return None, [_err("INVALID_PROJECT_ROOT", str(root), "project root must contain real in-root docs and docs/dev directories")]
        try:
            dev_dir.resolve(strict=True).relative_to(root)
        except (OSError, ValueError):
            return None, [_err("INVALID_PROJECT_ROOT", str(root), "docs/dev resolves outside the explicit real project root")]
        return root, []
    except OSError as exc:
        return None, [_err("INVALID_PROJECT_ROOT", str(project_root), str(exc))]


def _directory_identity(metadata: os.stat_result) -> tuple[int, int, int]:
    return metadata.st_dev, metadata.st_ino, stat.S_IFMT(metadata.st_mode)


def _open_directory_beneath(root: Path, relative: str) -> tuple[int, tuple[int, int, int]]:
    """Hold one exact in-root directory without following component symlinks."""
    if type(relative) is not str or not _safe_rel_path(relative, beneath_docs_dev=False):
        raise ContractFailure([_err("INVALID_PROJECT_ROOT", str(relative), "unsafe directory anchor path")])
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise ContractFailure([_err("IO_ERROR", relative, "platform lacks required no-follow directory traversal support")])
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    held: list[int] = []
    try:
        current = os.open(root, flags)
        held.append(current)
        for part in PurePosixPath(relative).parts:
            current = os.open(part, flags, dir_fd=current)
            held.append(current)
        result = held.pop()
        metadata = os.fstat(result)
        if not stat.S_ISDIR(metadata.st_mode):
            os.close(result)
            raise ContractFailure([_err("INVALID_PROJECT_ROOT", relative, "directory anchor is not a real directory")])
        return result, _directory_identity(metadata)
    except ContractFailure:
        raise
    except OSError as exc:
        raise ContractFailure([_err("INVALID_PROJECT_ROOT", relative, f"cannot open real directory anchor: {exc}")]) from exc
    finally:
        for directory_fd in reversed(held):
            os.close(directory_fd)


def _read_regular_file_at(
    directory_fd: int, name: str, display_path: str,
) -> tuple[bytes, tuple[int, int, int, int, int, int]]:
    """Read stable regular-file bytes relative to an already-held directory."""
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd: int | None = None
    try:
        fd = os.open(name, flags, dir_fd=directory_fd)
        before = _file_fingerprint(os.fstat(fd))
        if not stat.S_ISREG(before[2]):
            raise ContractFailure([_err("INVENTORY_MISMATCH", display_path, "canonical path must be a real regular file")])
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = _file_fingerprint(os.fstat(fd))
        if before != after:
            raise ContractFailure([_err("STALE_CANONICAL", display_path, "canonical changed while its evidence was read")])
    except ContractFailure:
        raise
    except OSError as exc:
        raise _filesystem_path_failure(display_path, exc) from exc
    finally:
        if fd is not None:
            os.close(fd)
    verify_fd: int | None = None
    try:
        verify_fd = os.open(name, flags, dir_fd=directory_fd)
        reopened = _file_fingerprint(os.fstat(verify_fd))
        if not stat.S_ISREG(reopened[2]):
            raise ContractFailure([_err("INVENTORY_MISMATCH", display_path, "canonical path must be a real regular file")])
    except ContractFailure:
        raise
    except OSError as exc:
        raise _filesystem_path_failure(display_path, exc) from exc
    finally:
        if verify_fd is not None:
            os.close(verify_fd)
    if reopened != after:
        raise ContractFailure([_err("STALE_CANONICAL", display_path, "canonical was replaced while its evidence was read")])
    return b"".join(chunks), reopened


def _validate_directory_anchor(boundary: dict[str, Any]) -> None:
    verify_fd, identity = _open_directory_beneath(boundary["root"], "docs/dev")
    os.close(verify_fd)
    if identity != boundary["directory_identity"]:
        raise ContractFailure([_err(
            "STALE_CANONICAL", "docs/dev",
            "canonical directory identity changed before the linearization point",
        )])


def _validate_write_boundary(boundary: dict[str, Any]) -> None:
    """Rebind every consumed source and target immediately before replacement."""
    _validate_directory_anchor(boundary)
    canonical_path = boundary["canonical_path"]
    expected = boundary["canonical_binding"]
    try:
        canonical_raw, canonical_fingerprint = _read_regular_file_at(
            boundary["directory_fd"], boundary["canonical_name"], canonical_path,
        )
    except ContractFailure as exc:
        if expected is None and all(item["code"] == "MISSING_ARTIFACT" for item in exc.errors):
            canonical_raw = None
            canonical_fingerprint = None
        else:
            if expected is not None and all(item["code"] == "MISSING_ARTIFACT" for item in exc.errors):
                raise ContractFailure([_err("CANONICAL_CHANGED", canonical_path, "canonical disappeared before replacement")]) from exc
            raise
    if expected is None:
        if canonical_raw is not None:
            raise ContractFailure([_err("CANONICAL_CHANGED", canonical_path, "expected canonical absence was lost before replacement")])
    elif (canonical_fingerprint != expected["fingerprint"]
          or _bytes_digest(canonical_raw, prefixed=False) != expected["sha256"]):
        raise ContractFailure([_err("CANONICAL_CHANGED", canonical_path, "canonical identity or bytes changed before replacement")])
    for relative, binding in boundary["source_bindings"].items():
        try:
            raw, fingerprint = _read_regular_file_snapshot(boundary["root"], relative)
        except ContractFailure as exc:
            raise ContractFailure([_err(
                item["code"], relative,
                f"declaration-bound source changed before replacement: {item['message']}",
            ) for item in exc.errors]) from exc
        if fingerprint != binding["fingerprint"] or _bytes_digest(raw, prefixed=False) != binding["sha256"]:
            raise ContractFailure([_err(
                "STALE_CANONICAL", relative,
                "declaration-bound source identity or bytes changed before replacement",
            )])
    for relative, fingerprint in boundary["repo_bindings"].items():
        try:
            observed = _inspect_regular_file_beneath(boundary["root"], relative)
        except ContractFailure as exc:
            raise ContractFailure([_err(
                item["code"], relative,
                f"declared repository evidence changed before replacement: {item['message']}",
            ) for item in exc.errors]) from exc
        if observed != fingerprint:
            raise ContractFailure([_err(
                "STALE_CANONICAL", relative,
                "declared repository evidence identity changed before replacement",
            )])
    inventory_errors: list[dict[str, str]] = []
    _reject_undeclared_retries(
        boundary["root"], boundary["declaration"],
        boundary["allowed_artifacts"], inventory_errors,
    )
    if inventory_errors:
        raise ContractFailure(inventory_errors)
    _validate_directory_anchor(boundary)


@contextmanager
def _task_lock(root: Path, task_id: str) -> Iterator[dict[str, Any]]:
    lock_path = "docs/dev/.artifact-chain-locks"
    dev_fd: int | None = None
    lock_dir_fd: int | None = None
    lock_fd: int | None = None
    locked = False
    try:
        dev_fd, dev_identity = _open_directory_beneath(root, "docs/dev")
        try:
            os.mkdir(".artifact-chain-locks", mode=0o700, dir_fd=dev_fd)
        except FileExistsError:
            pass
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        lock_dir_fd = os.open(".artifact-chain-locks", directory_flags, dir_fd=dev_fd)
        os.fchmod(lock_dir_fd, 0o700)
        lock_name = hashlib.sha256(task_id.encode("utf-8")).hexdigest() + ".lock"
        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        lock_fd = os.open(lock_name, flags, 0o600, dir_fd=lock_dir_fd)
        os.fchmod(lock_fd, 0o600)
        if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
            raise OSError("lock is not a regular file")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        locked = True
    except ContractFailure:
        if locked and lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        if lock_fd is not None:
            os.close(lock_fd)
        if lock_dir_fd is not None:
            os.close(lock_dir_fd)
        if dev_fd is not None:
            os.close(dev_fd)
        raise
    except OSError as exc:
        if locked and lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        if lock_fd is not None:
            os.close(lock_fd)
        if lock_dir_fd is not None:
            os.close(lock_dir_fd)
        if dev_fd is not None:
            os.close(dev_fd)
        raise ContractFailure([_err("LOCK_ACQUISITION_FAILED", lock_path, str(exc))]) from exc
    try:
        yield {"dir_fd": dev_fd, "identity": dev_identity}
    finally:
        if locked and lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        if lock_fd is not None:
            os.close(lock_fd)
        if lock_dir_fd is not None:
            os.close(lock_dir_fd)
        if dev_fd is not None:
            os.close(dev_fd)


def _replace_bytes(path: Path, raw: bytes) -> tuple[bool, Exception | None]:
    boundary = _WRITE_BOUNDARY.get()
    if boundary is None or path.name != boundary.get("canonical_name"):
        return False, ContractFailure([_err("ATOMIC_WRITE_FAILED", str(path), "missing exact descriptor-bound write context")])
    directory_fd = boundary["directory_fd"]
    temp_name: str | None = None
    temp_fd: int | None = None
    replaced = False
    try:
        _validate_write_boundary(boundary)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        for _ in range(128):
            candidate = f".{path.name}.{secrets.token_hex(12)}.tmp"
            try:
                temp_fd = os.open(candidate, flags, 0o600, dir_fd=directory_fd)
                temp_name = candidate
                break
            except FileExistsError:
                continue
        if temp_fd is None or temp_name is None:
            raise OSError("could not allocate a unique canonical temporary file")
        with os.fdopen(temp_fd, "wb") as handle:
            temp_fd = None
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        _validate_write_boundary(boundary)
        os.replace(temp_name, boundary["canonical_name"], src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        replaced = True
        os.fsync(directory_fd)
        return True, None
    except BaseException as exc:
        if temp_fd is not None:
            os.close(temp_fd)
        if not replaced and temp_name is not None:
            try:
                os.unlink(temp_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            except OSError as cleanup_exc:
                if not isinstance(exc, Exception):
                    raise
                return False, ContractFailure([_err(
                    "ATOMIC_WRITE_FAILED", str(path),
                    f"write failed ({exc}); temporary cleanup also failed ({cleanup_exc})",
                )])
        if not isinstance(exc, Exception):
            raise
        return replaced, exc


def apply_artifact_chain_declaration(
    project_root: Path | str, task_id: str, candidate: dict[str, Any] | None = None, *,
    candidate_from_canonical: bool = False, operation: str,
    expected_canonical_sha256: str | None = None, expect_canonical_absent: bool = False,
    expected_phase_digest: str | None = None, dry_run: bool = False,
    report_candidate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate/apply a declaration and return artifact_chain_declaration_provider.v1."""
    result = _provider_result(project_root, task_id)
    root, root_errors = _valid_root(project_root)
    if root is None:
        result["errors"] = root_errors
        return result
    result["project_root"] = str(root)
    if not _safe_task_id(task_id):
        result["errors"] = [_err("INVALID_ARGUMENT", "task_id", "task id must be an exact safe non-empty component")]
        return result
    canonical_rel = f"docs/dev/dev-report-{task_id}.json"
    canonical_path = root / canonical_rel
    result["canonical_path"] = canonical_rel
    operations = {"validate_only", "default_aggregate", "inject_only", "update_declaration_only"}
    if not isinstance(operation, str) or operation not in operations:
        result["errors"] = [_err("INVALID_ARGUMENT", "operation", f"unsupported operation {operation!r}")]
        return result
    if (candidate is None) == (not candidate_from_canonical):
        result["errors"] = [_err("INVALID_ARGUMENT", "candidate", "exactly one candidate source is required")]
        return result
    expected_count = int(expected_canonical_sha256 is not None) + int(expect_canonical_absent)
    if operation == "validate_only":
        if candidate_from_canonical or expected_count or expected_phase_digest is not None or report_candidate is not None:
            result["errors"] = [_err("INVALID_ARGUMENT", "validate_only", "validate-only requires an explicit candidate and no expected state/report input")]
            return result
        normalized, errors = validate_declaration(candidate, task_id)
        if errors:
            result["errors"] = errors
            return result
        _fill_success_declaration(result, normalized)
        result.update(status="ok", action="validated")
        return result
    if expected_count != 1 or (expected_canonical_sha256 is not None and HEX_RE.fullmatch(expected_canonical_sha256) is None):
        result["errors"] = [_err("INVALID_ARGUMENT", "expected_state", "every writer requires exactly one valid expected canonical SHA or expect-absent")]
        return result
    if candidate_from_canonical and (operation != "default_aggregate" or expect_canonical_absent):
        result["errors"] = [_err("INVALID_ARGUMENT", "candidate", "declaration-from-canonical is existing parallel default-refresh only")]
        return result
    if report_candidate is not None and operation != "update_declaration_only":
        result["errors"] = [_err("INVALID_ARGUMENT", "report_candidate", "transient report input is singular update-declaration-only input")]
        return result
    try:
        with _task_lock(root, task_id) as anchor:
            existing_raw: bytes | None = None
            existing: dict[str, Any] | None = None
            existing_binding: dict[str, Any] | None = None
            try:
                existing_raw, existing_fingerprint = _read_regular_file_at(
                    anchor["dir_fd"], canonical_path.name, canonical_rel,
                )
            except ContractFailure as exc:
                if not all(item["code"] == "MISSING_ARTIFACT" for item in exc.errors):
                    result["errors"] = exc.errors
                    return result
            if existing_raw is not None:
                try:
                    existing = load_json_bytes(existing_raw, canonical_rel)
                except ContractFailure as exc:
                    result["errors"] = exc.errors
                    return result
                result["previous_canonical_sha256"] = _bytes_digest(existing_raw, prefixed=False)
                existing_binding = {
                    "fingerprint": existing_fingerprint,
                    "sha256": result["previous_canonical_sha256"],
                }
            if expect_canonical_absent and existing is not None:
                result["errors"] = [_err("CANONICAL_ALREADY_EXISTS", canonical_rel, "expected canonical absence was lost under lock")]
                result["observed_canonical_sha256"] = result["previous_canonical_sha256"]
                return result
            if expected_canonical_sha256 is not None and (existing is None or result["previous_canonical_sha256"] != expected_canonical_sha256):
                result["errors"] = [_err("CANONICAL_CHANGED", canonical_rel, "canonical SHA did not match under the shared lock")]
                result["observed_canonical_sha256"] = result["previous_canonical_sha256"]
                return result
            if existing is not None:
                existing_path_errors: list[dict[str, str]] = []
                if _validate_declared_repo_paths(root, existing, canonical_rel, existing_path_errors) is None:
                    result["errors"] = existing_path_errors
                    return result
            existing_decl = existing.get("artifact_chain_declaration") if isinstance(existing, dict) else None
            old_normalized: dict[str, Any] | None = None
            if candidate_from_canonical:
                if not isinstance(existing_decl, dict):
                    result["errors"] = [_err("MISSING_DECLARATION", canonical_rel, "existing canonical has no embedded declaration")]
                    return result
                candidate = copy.deepcopy(existing_decl)
            normalized, errors = validate_declaration(candidate, task_id, root=root, validate_artifacts=True)
            if errors or normalized is None:
                result["errors"] = errors
                return result
            normalized["__validation_root"] = root
            if existing_decl is not None:
                old_normalized, old_errors = validate_declaration(existing_decl, task_id, root=root, validate_artifacts=True)
                if old_errors or old_normalized is None:
                    result["errors"] = old_errors
                    return result
                if expected_phase_digest is None or old_normalized["phase_projection"]["phase_digest"] != expected_phase_digest:
                    result["errors"] = [_err("PHASE_DIGEST_MISMATCH", canonical_rel, "current embedded phase digest does not match expected phase CAS")]
                    return result
                old_normalized["__validation_root"] = root
                _validate_transition(old_normalized, normalized, errors)
                old_normalized.pop("__validation_root", None)
            elif expected_phase_digest is not None:
                result["errors"] = [_err("PHASE_DIGEST_MISMATCH", canonical_rel, "no embedded phase exists for the expected digest")]
                return result
            elif operation == "update_declaration_only" or candidate_from_canonical:
                result["errors"] = [_err("MISSING_DECLARATION", canonical_rel, "operation requires an existing embedded declaration")]
                return result
            source_bindings: dict[str, dict[str, Any]] = {}
            if operation == "inject_only" and existing_decl is not None:
                errors.append(_err("DECLARATION_CONFLICT", canonical_rel, "inject-only requires a declarationless existing canonical"))
            if operation == "inject_only" and existing is None:
                errors.append(_err("CANONICAL_NOT_FOUND", canonical_rel, "inject-only cannot fabricate a missing canonical"))
            if operation == "default_aggregate" and existing is not None and existing_decl is None:
                errors.append(_err("DECLARATION_CONFLICT", canonical_rel, "an existing declarationless canonical requires inject-only; default aggregate may not overwrite it"))
            if operation == "update_declaration_only" and normalized["shape"] != "singular":
                errors.append(_err("INVALID_ARGUMENT", "operation", "declaration-only updates are singular-only"))
            if operation == "default_aggregate" and normalized["shape"] == "singular":
                errors.append(_err("INSUFFICIENT_SOURCE_ARTIFACTS", canonical_rel, "missing/aggregate singular canonical cannot be reconstructed"))
            normalized.pop("__validation_root", None)
            if operation == "inject_only" and existing is not None:
                source_bindings = _validate_existing_injection(root, existing, normalized, errors)
            if normalized["shape"] == "singular" and existing is not None:
                if report_candidate is None:
                    _validate_mutable_singular_current(existing, normalized, errors)
                elif old_normalized is not None and _member_current_row(old_normalized["phase_projection"]["members"][0]) is not None:
                    _validate_mutable_singular_current(existing, old_normalized, errors)
                elif old_normalized is not None:
                    # Initial publication: the declaration has no ledger alias yet,
                    # so bind the already-visible report body to the transient body
                    # that the first promotion will snapshot.
                    try:
                        old_projection, _ = stable_dev_projection(existing)
                        new_projection, _ = stable_dev_projection(report_candidate)
                        if old_projection != new_projection:
                            errors.append(_err("STALE_CANONICAL", canonical_rel, "initial singular promotion changed the report stable projection"))
                    except ContractFailure as exc:
                        errors.extend(exc.errors)
            if errors:
                result["errors"] = errors
                return result
            if operation == "inject_only":
                new_document = copy.deepcopy(existing)
                new_document["artifact_chain_declaration"] = normalized
                action = "injected"
            elif operation == "update_declaration_only":
                if report_candidate is None:
                    new_document = copy.deepcopy(existing)
                    new_document["artifact_chain_declaration"] = normalized
                else:
                    new_document = copy.deepcopy(report_candidate)
                    if not isinstance(new_document, dict):
                        result["errors"] = [_err("INVALID_ARGUMENT", "report_candidate", "transient singular report input must be an object")]
                        return result
                    if _validate_declared_repo_paths(root, new_document, canonical_rel, errors) is None:
                        result["errors"] = errors
                        return result
                    _identity(new_document, task_id, canonical_rel, errors)
                    _dev_status(new_document, canonical_rel, errors)
                    new_document["artifact_chain_declaration"] = normalized
                    _validate_mutable_singular_current(new_document, normalized, errors)
                    if errors:
                        result["errors"] = errors
                        return result
                action = "updated_declaration"
            else:
                sources, source_bindings = _load_active_sources(root, normalized, errors, with_bindings=True)
                if errors or len(sources) != len(normalized["active_roster"]):
                    if not errors:
                        errors.append(_err("INSUFFICIENT_SOURCE_ARTIFACTS", canonical_rel, "not every active declared source is available"))
                    result["errors"] = errors
                    return result
                new_document = _build_aggregate(sources, task_id, normalized, timestamp=existing.get("timestamp") if existing else None)
                action = "aggregated" if existing is None else "refreshed"
            final_path_errors: list[dict[str, str]] = []
            repo_bindings = _validate_declared_repo_paths(root, new_document, canonical_rel, final_path_errors)
            if repo_bindings is None:
                result["errors"] = final_path_errors
                return result
            new_raw = _canonical_bytes(new_document)
            _fill_success_declaration(result, normalized)
            boundary = {
                "root": root,
                "directory_fd": anchor["dir_fd"],
                "directory_identity": anchor["identity"],
                "canonical_name": canonical_path.name,
                "canonical_path": canonical_rel,
                "canonical_binding": existing_binding,
                "source_bindings": source_bindings,
                "repo_bindings": repo_bindings,
                "declaration": normalized,
                "allowed_artifacts": _declared_artifact_union(normalized),
            }
            try:
                _validate_write_boundary(boundary)
            except ContractFailure as exc:
                result["errors"] = exc.errors
                return result
            if existing_raw == new_raw:
                result.update(status="ok", action="unchanged", observed_canonical_sha256=_bytes_digest(new_raw, prefixed=False))
                return result
            if dry_run:
                result.update(status="ok", action="would_write", observed_canonical_sha256=result["previous_canonical_sha256"])
                return result
            token = _WRITE_BOUNDARY.set(boundary)
            try:
                replaced, failure = _replace_bytes(canonical_path, new_raw)
            finally:
                _WRITE_BOUNDARY.reset(token)
            if failure is not None:
                if replaced:
                    result.update(action="replaced_durability_uncertain", changed=True, mutation_state="committed_durability_uncertain", linearization_point="os.replace", observed_canonical_sha256=_bytes_digest(new_raw, prefixed=False))
                    result["errors"] = [_err("POST_REPLACE_DURABILITY_UNCERTAIN", canonical_rel, str(failure))]
                elif isinstance(failure, ContractFailure):
                    result["errors"] = failure.errors
                else:
                    result["errors"] = [_err("ATOMIC_WRITE_FAILED", canonical_rel, str(failure))]
                return result
            result.update(status="ok", action=action, changed=True, mutation_state="committed_durable", linearization_point="os.replace", observed_canonical_sha256=_bytes_digest(new_raw, prefixed=False))
            return result
    except ContractFailure as exc:
        result["errors"] = exc.errors
        return result


def _validate_mutable_singular_current(document: dict[str, Any], declaration: dict[str, Any], errors: list[dict[str, str]]) -> None:
    phase = declaration["phase_projection"]["members"][0]
    row = _member_current_row(phase)
    if row is None:
        errors.append(_err("INVALID_DECLARATION", "artifact_chain_declaration.phase_projection.members[0]", "published singular report requires a current ledger row"))
        return
    try:
        raw, digest = stable_dev_projection(document)
    except ContractFailure as exc:
        errors.extend(exc.errors)
        return
    snapshot, snapshot_digest = _decode_projection_snapshot(row.get("stable_projection_utf8_base64"), "attempt_ledger", errors)
    if snapshot != raw or digest != row.get("stable_projection_sha256") or snapshot_digest != digest:
        errors.append(_err("STALE_CANONICAL", "artifact_chain_declaration.phase_projection.members[0]", "current singular projection does not equal its aliased ledger snapshot"))


def _fill_success_declaration(result: dict[str, Any], declaration: dict[str, Any] | None) -> None:
    if declaration is None:
        return
    result["declaration"] = declaration
    result["lineage_digest"] = declaration["lineage_digest"]
    result["phase_version"] = declaration["phase_projection"]["phase_version"]
    result["phase_digest"] = declaration["phase_projection"]["phase_digest"]
    result["declaration_digest"] = declaration["declaration_digest"]


def recover_artifact_chain_durability(project_root: Path | str, task_id: str, intended_canonical_sha256: str) -> dict[str, Any]:
    """Re-fsync a post-replace result without ever overwriting canonical bytes."""
    result = _provider_result(project_root, task_id)
    root, root_errors = _valid_root(project_root)
    if root is None:
        result["errors"] = root_errors
        return result
    result["project_root"] = str(root)
    if not _safe_task_id(task_id) or HEX_RE.fullmatch(intended_canonical_sha256 or "") is None:
        result["errors"] = [_err("INVALID_ARGUMENT", "durability_recovery", "exact task id and intended lowercase canonical SHA are required")]
        return result
    relative = f"docs/dev/dev-report-{task_id}.json"
    path = root / relative
    result["canonical_path"] = relative
    try:
        with _task_lock(root, task_id) as anchor:
            try:
                raw, _ = _read_regular_file_at(anchor["dir_fd"], path.name, relative)
            except ContractFailure as exc:
                result["errors"] = exc.errors
                return result
            observed = _bytes_digest(raw, prefixed=False)
            result["previous_canonical_sha256"] = observed
            result["observed_canonical_sha256"] = observed
            if observed != intended_canonical_sha256:
                result["errors"] = [_err("CANONICAL_CHANGED", relative, "durability recovery refuses to fsync a different canonical SHA")]
                return result
            report = load_json_bytes(raw, relative)
            path_errors: list[dict[str, str]] = []
            if _validate_declared_repo_paths(root, report, relative, path_errors) is None:
                result["errors"] = path_errors
                return result
            declaration = report.get("artifact_chain_declaration")
            normalized, errors = validate_declaration(declaration, task_id, root=root, validate_artifacts=True)
            if errors or normalized is None:
                result["errors"] = errors
                return result
            try:
                _validate_directory_anchor({
                    "root": root,
                    "directory_identity": anchor["identity"],
                })
                os.fsync(anchor["dir_fd"])
            except OSError as exc:
                result["errors"] = [_err("POST_REPLACE_DURABILITY_UNCERTAIN", relative, str(exc))]
                return result
            _fill_success_declaration(result, normalized)
            result.update(status="ok", action="unchanged")
            return result
    except ContractFailure as exc:
        result["errors"] = exc.errors
        return result


def _load_candidate(path: str) -> dict[str, Any]:
    try:
        raw = sys.stdin.buffer.read() if path == "-" else Path(path).read_bytes()
        value = load_json_bytes(raw, path)
    except OSError as exc:
        raise ContractFailure([_err("IO_ERROR", path, str(exc))]) from exc
    if "artifact_chain_declaration" in value and set(value) != DECLARATION_FIELDS:
        nested = value.get("artifact_chain_declaration")
        if isinstance(nested, dict):
            return nested
    return value


def _exit_for(result: dict[str, Any]) -> int:
    if result["status"] == "ok":
        return 0
    io_codes = {"ATOMIC_WRITE_FAILED", "LOCK_ACQUISITION_FAILED", "POST_REPLACE_DURABILITY_UNCERTAIN", "IO_ERROR"}
    return 1 if any(error["code"] in io_codes for error in result["errors"]) else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aggregate-dev-report.py")
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--task-id", required=True)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--declaration-file")
    sources.add_argument("--declaration-from-canonical", action="store_true")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--validate-declaration-only", action="store_true")
    modes.add_argument("--inject-declaration-only", action="store_true")
    modes.add_argument("--update-declaration-only", action="store_true")
    expected = parser.add_mutually_exclusive_group()
    expected.add_argument("--expected-canonical-sha256")
    expected.add_argument("--expect-canonical-absent", action="store_true")
    parser.add_argument("--expected-phase-digest")
    parser.add_argument("--report-file", help="transient singular retry report input; never persisted separately")
    parser.add_argument("--dry-run", action="store_true")
    try:
        args = parser.parse_args(argv)
        candidate = None if args.declaration_from_canonical else _load_candidate(args.declaration_file)
        report_candidate = _load_candidate(args.report_file) if args.report_file else None
        operation = "validate_only" if args.validate_declaration_only else "inject_only" if args.inject_declaration_only else "update_declaration_only" if args.update_declaration_only else "default_aggregate"
        result = apply_artifact_chain_declaration(
            args.project_dir, args.task_id, candidate,
            candidate_from_canonical=args.declaration_from_canonical,
            operation=operation,
            expected_canonical_sha256=args.expected_canonical_sha256,
            expect_canonical_absent=args.expect_canonical_absent,
            expected_phase_digest=args.expected_phase_digest,
            dry_run=args.dry_run,
            report_candidate=report_candidate,
        )
    except (ContractFailure, SystemExit) as exc:
        if isinstance(exc, SystemExit):
            raise
        result = _provider_result("", "")
        result["errors"] = exc.errors
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return _exit_for(result)


if __name__ == "__main__":
    sys.exit(main())
