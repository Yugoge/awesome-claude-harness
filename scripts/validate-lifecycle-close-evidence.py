#!/usr/bin/env python3
"""Validate frozen lifecycle evidence without authenticating the human boundary."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

HEX64 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_EVENTS = {"UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "SubagentStop"}
REQUIRED_MANIFEST_FIELDS = {
    "schema_version",
    "continuation_task_id",
    "frozen_at",
    "authoritative_native_path",
    "authoritative_native_sha256",
    "hooks_json_sha256",
    "per_event_owner_counts",
    "config_toml_sha256",
    "trust_row",
    "canonical_hook_sha256",
    "byte_identical_projection_sha256_values",
    "standalone_runtime_hashes",
    "plugin_runtime_hashes",
    "provenance_hashes",
    "canonical_e2e_sha256",
    "installed_e2e_sha256",
    "canonical_e2e_test_count",
    "installed_e2e_test_count",
    "focused_test_and_report_hashes",
    "compatibility_counts",
    "known_unsupported_rows",
    "release_claim",
}
ALLOWED_NATIVE_TERMINALS = {"completed", "incomplete", "user_cancelled"}


class EvidenceError(ValueError):
    pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256_bytes(payload.encode())


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"{path}: unreadable JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"{path}: top-level JSON must be an object")
    return value


def require_fields(value: dict[str, Any], fields: set[str], label: str) -> None:
    missing = sorted(fields - value.keys())
    if missing:
        raise EvidenceError(f"{label}: missing fields: {', '.join(missing)}")


def require_hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        raise EvidenceError(f"{label}: expected 64 lowercase hexadecimal characters")
    return value


def verify_file_hash(path_value: Any, expected: Any, label: str) -> None:
    if not isinstance(path_value, str) or not path_value:
        raise EvidenceError(f"{label}: path must be non-empty")
    expected_hash = require_hash(expected, f"{label}.sha256")
    path = Path(path_value)
    if not path.is_file():
        raise EvidenceError(f"{label}: missing file: {path}")
    actual = sha256_file(path)
    if actual != expected_hash:
        raise EvidenceError(f"{label}: hash mismatch for {path}: {actual} != {expected_hash}")


def verify_hash_map(value: Any, label: str) -> None:
    if not isinstance(value, dict) or not value:
        raise EvidenceError(f"{label}: expected non-empty path/hash object")
    for path, digest in value.items():
        verify_file_hash(path, digest, f"{label}[{path}]")


@contextmanager
def lifecycle_family_read_lock(manifest: dict[str, Any]) -> Iterator[None]:
    projections = manifest.get("byte_identical_projection_sha256_values")
    if not isinstance(projections, dict) or len(projections) < 2:
        raise EvidenceError("freeze manifest lacks the lifecycle projection family")
    harness_root = Path(os.path.commonpath([str(Path(path).resolve()) for path in projections]))
    roots = (harness_root, harness_root / "plugin")
    if any(not root.is_dir() for root in roots):
        raise EvidenceError("freeze manifest lifecycle projection roots are invalid")
    descriptors = [
        os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)) for root in roots
    ]
    try:
        for descriptor in descriptors:
            fcntl.flock(descriptor, fcntl.LOCK_SH)
        yield
    finally:
        for descriptor in reversed(descriptors):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def validate_manifest(path: Path, task_id: str) -> tuple[dict[str, Any], str]:
    manifest = load_object(path)
    with lifecycle_family_read_lock(manifest):
        return _validate_manifest_locked(manifest, path, task_id)


def _validate_manifest_locked(
    manifest: dict[str, Any], path: Path, task_id: str
) -> tuple[dict[str, Any], str]:
    require_fields(manifest, REQUIRED_MANIFEST_FIELDS, "freeze manifest")
    if manifest["continuation_task_id"] != task_id:
        raise EvidenceError("freeze manifest continuation_task_id mismatch")
    verify_file_hash(
        manifest["authoritative_native_path"],
        manifest["authoritative_native_sha256"],
        "authoritative_native",
    )
    verify_file_hash(manifest["hooks_json_path"], manifest["hooks_json_sha256"], "hooks_json")
    verify_file_hash(manifest["config_toml_path"], manifest["config_toml_sha256"], "config_toml")
    verify_file_hash(manifest["canonical_hook_path"], manifest["canonical_hook_sha256"], "canonical_hook")
    verify_file_hash(manifest["canonical_e2e_path"], manifest["canonical_e2e_sha256"], "canonical_e2e")
    verify_file_hash(manifest["installed_e2e_path"], manifest["installed_e2e_sha256"], "installed_e2e")
    for field in (
        "byte_identical_projection_sha256_values",
        "standalone_runtime_hashes",
        "plugin_runtime_hashes",
        "provenance_hashes",
        "focused_test_and_report_hashes",
    ):
        verify_hash_map(manifest[field], field)

    projection_hashes = set(manifest["byte_identical_projection_sha256_values"].values())
    projection_hashes.add(manifest["canonical_hook_sha256"])
    if len(projection_hashes) != 1:
        raise EvidenceError("canonical hook and declared byte-identical projections diverge")
    if manifest["canonical_e2e_sha256"] == manifest["installed_e2e_sha256"]:
        raise EvidenceError("installed E2E must remain a separately hashed semantic extension")
    if not isinstance(manifest["canonical_e2e_test_count"], int) or not isinstance(
        manifest["installed_e2e_test_count"], int
    ):
        raise EvidenceError("E2E test counts must be integers")
    if manifest["installed_e2e_test_count"] <= manifest["canonical_e2e_test_count"]:
        raise EvidenceError("installed E2E must retain installed-only coverage")

    counts = manifest["per_event_owner_counts"]
    if not isinstance(counts, dict) or set(counts) != REQUIRED_EVENTS:
        raise EvidenceError("per_event_owner_counts must cover exactly the five lifecycle events")
    if any(counts[event] != 1 for event in REQUIRED_EVENTS):
        raise EvidenceError("each configured lifecycle event must have exactly one native owner")

    compatibility = manifest["compatibility_counts"]
    if compatibility.get("fail") != 0 or compatibility.get("sync_isomorphic") != "pass":
        raise EvidenceError("compatibility sync must have zero failures and sync_isomorphic=pass")
    if compatibility.get("full_runtime_isomorphic") != "fail":
        raise EvidenceError("full runtime isomorphism must remain fail while unsupported rows remain")
    unsupported = manifest["known_unsupported_rows"]
    if not isinstance(unsupported, list) or len(unsupported) != 13:
        raise EvidenceError("exactly 13 known unsupported/fallback rows must be retained")
    if manifest["release_claim"] != "live_activation_unproven":
        raise EvidenceError("pre-live manifest release_claim must be live_activation_unproven")
    return manifest, sha256_file(path)


def validate_human_reference(
    reference: Any,
    manifest_digest: str,
    native_digest: str,
    label: str,
) -> str:
    if not isinstance(reference, dict):
        raise EvidenceError(f"{label}: human_confirmation_reference must be an object")
    required = {
        "source_kind",
        "event_id",
        "confirmed_manifest_sha256",
        "confirmed_native_sha256",
        "reload_completed_at",
        "post_reload_session_id",
        "agent_authored",
    }
    require_fields(reference, required, label)
    if reference["source_kind"] != "external_human_event" or reference["agent_authored"] is not False:
        raise EvidenceError(f"{label}: only an external, non-agent-authored reference is admissible")
    if not isinstance(reference["event_id"], str) or not reference["event_id"].strip():
        raise EvidenceError(f"{label}: external event_id must be non-empty")
    if reference["confirmed_manifest_sha256"] != manifest_digest:
        raise EvidenceError(f"{label}: confirmed manifest digest mismatch")
    if reference["confirmed_native_sha256"] != native_digest:
        raise EvidenceError(f"{label}: confirmed native digest mismatch")
    if not isinstance(reference["post_reload_session_id"], str) or not reference[
        "post_reload_session_id"
    ].strip():
        raise EvidenceError(f"{label}: post_reload_session_id must be non-empty")
    return canonical_sha256(reference)


def validate_probe(
    path: Path,
    task_id: str,
    manifest_digest: str,
    native_digest: str,
    expected_terminal: str,
) -> tuple[dict[str, Any], str]:
    probe = load_object(path)
    required = {
        "continuation_task_id",
        "probe_task_id",
        "host_session_id",
        "runtime_root",
        "native_sha256",
        "freeze_manifest_sha256",
        "human_confirmation_reference",
        "started_at",
        "stopped_at",
        "identity_cardinality",
        "first_stop_attempt",
        "ordinary_time_lock_active",
        "terminal_host_return",
        "terminal_status",
    }
    require_fields(probe, required, f"probe {path}")
    if probe["continuation_task_id"] != task_id:
        raise EvidenceError(f"{path}: continuation_task_id mismatch")
    if probe["runtime_root"] != "codex":
        raise EvidenceError(f"{path}: configured live probe runtime_root must be codex")
    if probe["native_sha256"] != native_digest or probe["freeze_manifest_sha256"] != manifest_digest:
        raise EvidenceError(f"{path}: frozen digest mismatch")
    if probe["probe_task_id"] == task_id or not str(probe["probe_task_id"]).strip():
        raise EvidenceError(f"{path}: probe_task_id must be newly allocated")
    if not str(probe["host_session_id"]).strip():
        raise EvidenceError(f"{path}: host_session_id must be non-empty")
    if probe["identity_cardinality"] != 1 or probe["first_stop_attempt"] != 1:
        raise EvidenceError(f"{path}: identity cardinality and first Stop attempt must both be one")
    if probe["ordinary_time_lock_active"] is not False or probe["terminal_host_return"] is not True:
        raise EvidenceError(f"{path}: ordinary Stop did not prove an unlocked terminal host return")
    if probe["terminal_status"] != expected_terminal:
        raise EvidenceError(f"{path}: expected terminal_status={expected_terminal}")
    if expected_terminal == "incomplete" and probe.get("first_checklist_accepted") is not True:
        raise EvidenceError(f"{path}: early probe must prove first checklist acceptance")
    reference_digest = validate_human_reference(
        probe["human_confirmation_reference"],
        manifest_digest,
        native_digest,
        f"{path}.human_confirmation_reference",
    )
    return probe, reference_digest


def write_receipt(
    output: Path,
    task_id: str,
    stage: str,
    verdict: str,
    validated_inputs: dict[str, str],
    reference_hashes: dict[str, str],
) -> dict[str, Any]:
    receipt = {
        "schema_version": 1,
        "request_id": task_id,
        "task_id": task_id,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "stage": stage,
        "stage_scope": "C3_only" if stage == "pre_live" else "C7",
        "verdict": verdict,
        "accepted_for_close": stage == "post_live" and verdict == "pass",
        "release_claim": "live_activation_unproven" if stage == "pre_live" else "live_activation_observed",
        "allowed_native_terminal_states": sorted(ALLOWED_NATIVE_TERMINALS),
        "delivery_claim_is_native_enum": False,
        "validated_input_sha256_values": validated_inputs,
        "human_confirmation_reference_sha256_values": reference_hashes,
    }
    output.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n")
    return receipt


def validate_stage(args: argparse.Namespace) -> dict[str, Any]:
    manifest, manifest_digest = validate_manifest(args.manifest, args.task_id)
    native_digest = manifest["authoritative_native_sha256"]
    if args.stage == "pre_live":
        return write_receipt(
            args.output,
            args.task_id,
            "pre_live",
            "pass",
            {str(args.manifest): manifest_digest},
            {},
        )

    if not args.output.exists():
        raise EvidenceError("post_live validation requires the prior pre_live receipt at --output")
    prior = load_object(args.output)
    if prior.get("stage") != "pre_live":
        raise EvidenceError("post_live validation requires an existing pre_live receipt")
    prior_inputs = prior.get("validated_input_sha256_values", {})
    matching_digests = {
        digest
        for raw_path, digest in prior_inputs.items()
        if Path(raw_path).resolve() == args.manifest.resolve()
    } if isinstance(prior_inputs, dict) else set()
    if matching_digests != {manifest_digest}:
        raise EvidenceError("freeze manifest changed since pre_live validation")
    if args.early_probe is None or args.completed_probe is None:
        raise EvidenceError("post_live validation requires both probe records")
    early, early_ref = validate_probe(
        args.early_probe, args.task_id, manifest_digest, native_digest, "incomplete"
    )
    completed, completed_ref = validate_probe(
        args.completed_probe, args.task_id, manifest_digest, native_digest, "completed"
    )
    if early["probe_task_id"] == completed["probe_task_id"]:
        raise EvidenceError("probe task IDs must be distinct")
    if early["host_session_id"] == completed["host_session_id"]:
        raise EvidenceError("probe host session IDs must be distinct")
    return write_receipt(
        args.output,
        args.task_id,
        "post_live",
        "pass",
        {
            str(args.manifest): manifest_digest,
            str(args.early_probe): sha256_file(args.early_probe),
            str(args.completed_probe): sha256_file(args.completed_probe),
        },
        {
            str(args.early_probe): early_ref,
            str(args.completed_probe): completed_ref,
        },
    )


def check_close(args: argparse.Namespace) -> dict[str, Any]:
    _, manifest_digest = validate_manifest(args.manifest, args.task_id)
    receipt = load_object(args.receipt)
    if receipt.get("task_id") != args.task_id or receipt.get("stage") != "post_live":
        raise EvidenceError("close requires a same-task post_live receipt")
    if receipt.get("verdict") != "pass" or receipt.get("accepted_for_close") is not True:
        raise EvidenceError("close requires an accepted passing receipt")
    expected_inputs = receipt.get("validated_input_sha256_values")
    if not isinstance(expected_inputs, dict) or expected_inputs.get(str(args.manifest)) != manifest_digest:
        raise EvidenceError("receipt does not bind the unchanged freeze manifest")
    for path, digest in expected_inputs.items():
        verify_file_hash(path, digest, f"receipt input {path}")

    qa = load_object(args.qa_report)
    if qa.get("request_id") != args.task_id or qa.get("task_id") != args.task_id:
        raise EvidenceError("QA report task identity mismatch")
    if qa.get("qa", {}).get("status") != "pass":
        raise EvidenceError("QA report status is not pass")
    evidence = qa.get("qa", {}).get("lifecycle_evidence")
    if not isinstance(evidence, dict):
        raise EvidenceError("QA report lacks qa.lifecycle_evidence")
    receipt_digest = sha256_file(args.receipt)
    expected_echo = {
        "receipt_sha256": receipt_digest,
        "receipt_stage": receipt["stage"],
        "receipt_verdict": receipt["verdict"],
        "validated_input_sha256_values": expected_inputs,
        "human_confirmation_reference_sha256_values": receipt.get(
            "human_confirmation_reference_sha256_values", {}
        ),
    }
    for key, value in expected_echo.items():
        if evidence.get(key) != value:
            raise EvidenceError(f"QA lifecycle evidence echo mismatch: {key}")
    return {
        "task_id": args.task_id,
        "stage": "close",
        "verdict": "pass",
        "receipt_sha256": receipt_digest,
        "full_parity_claimed": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--stage", choices=("pre_live", "post_live"), required=True)
    validate.add_argument("--task-id", required=True)
    validate.add_argument("--manifest", type=Path, required=True)
    validate.add_argument("--early-probe", type=Path)
    validate.add_argument("--completed-probe", type=Path)
    validate.add_argument("--output", type=Path, required=True)

    close = subparsers.add_parser("check-close")
    close.add_argument("--task-id", required=True)
    close.add_argument("--manifest", type=Path, required=True)
    close.add_argument("--receipt", type=Path, required=True)
    close.add_argument("--qa-report", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = validate_stage(args) if args.command == "validate" else check_close(args)
    except EvidenceError as exc:
        print(json.dumps({"verdict": "fail", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
