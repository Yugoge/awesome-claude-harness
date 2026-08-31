#!/usr/bin/env python3
"""Create or verify authority-bound bounded negative-evidence receipts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
sys.path.insert(0, str(HOOKS))

from lib import negative_evidence as evidence  # noqa: E402


def _external_authority(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--contract-context", required=True)
    parser.add_argument("--expected-context-sha256", required=True)
    parser.add_argument("--authority-file", required=True)
    parser.add_argument("--expected-authority-sha256", required=True)
    parser.add_argument("--expected-authority-projection-sha256", required=True)
    parser.add_argument("--scan-root", required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Produce/verify fail-closed find -L receipts bound to a parent-owned "
            "root and repository authority."
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="run a bounded authority-bound scan")
    _external_authority(scan)
    scan.add_argument("--scope", action="append", required=True)
    scan.add_argument("--prune", action="append", default=[])
    scan.add_argument(
        "--target-kind", choices=("exact-path", "basename"), required=True
    )
    scan.add_argument("--target", "--target-value", dest="target", required=True)
    scan.add_argument(
        "--positive-control", "--control", dest="positive_control", required=True
    )
    scan.add_argument("--timeout-ms", type=int, required=True)
    scan.add_argument("--max-output-bytes", type=int, required=True)
    scan.add_argument("--max-files", type=int, required=True)
    scan.add_argument(
        "--output",
        help="absolute, absent receipt destination; published O_EXCL mode 0444",
    )
    scan.add_argument("--pretty", action="store_true")

    verify = sub.add_parser("verify", help="schema-check and re-run a receipt")
    _external_authority(verify)
    verify.add_argument("--receipt", "--receipt-path", dest="receipt", required=True)
    verify.add_argument("--expected-receipt-sha256", required=True)
    verify.add_argument(
        "--target-kind", choices=("exact-path", "basename"), required=True
    )
    verify.add_argument("--target", "--target-value", dest="target", required=True)
    verify.add_argument(
        "--expected-conclusion", choices=("present", "absent", "unknown"), required=True
    )
    verify.add_argument("--pretty", action="store_true")
    return parser


def _emit(value: dict, pretty: bool) -> None:
    if pretty:
        print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        sys.stdout.buffer.write(evidence.canonical_json_bytes(value, newline=True))


def _scan(args: argparse.Namespace) -> int:
    receipt = evidence.scan_evidence(
        contract_context=args.contract_context,
        expected_context_sha256=args.expected_context_sha256,
        authority_file=args.authority_file,
        expected_authority_sha256=args.expected_authority_sha256,
        expected_authority_projection_sha256=args.expected_authority_projection_sha256,
        scan_root=args.scan_root,
        scopes=args.scope,
        prunes=args.prune,
        target_kind=args.target_kind,
        target=args.target,
        positive_control=args.positive_control,
        timeout_ms=args.timeout_ms,
        max_output_bytes=args.max_output_bytes,
        max_files=args.max_files,
    )
    if args.output:
        evidence.publish_receipt(args.output, receipt)
    _emit(receipt, args.pretty)
    return (
        evidence.CONCLUSIVE_EXIT
        if receipt["conclusion"] in {"present", "absent"}
        else evidence.INCONCLUSIVE_EXIT
    )


def _verify(args: argparse.Namespace) -> int:
    result = evidence.verify_receipt(
        receipt_path=args.receipt,
        expected_receipt_sha256=args.expected_receipt_sha256,
        contract_context=args.contract_context,
        expected_context_sha256=args.expected_context_sha256,
        authority_file=args.authority_file,
        expected_authority_sha256=args.expected_authority_sha256,
        expected_authority_projection_sha256=args.expected_authority_projection_sha256,
        scan_root=args.scan_root,
        target_kind=args.target_kind,
        target=args.target,
        expected_conclusion=args.expected_conclusion,
    )
    _emit(result, args.pretty)
    if result["ok"]:
        return evidence.CONCLUSIVE_EXIT
    if not result["errors"] and result["conclusion"] == "unknown":
        return evidence.INCONCLUSIVE_EXIT
    return evidence.VERIFY_FAILURE_EXIT


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _scan(args) if args.command == "scan" else _verify(args)
    except evidence.SchemaContractError as exc:
        print(
            json.dumps({"error": str(exc), "kind": "schema_contract"}), file=sys.stderr
        )
        return evidence.USAGE_OR_SCHEMA_EXIT
    except evidence.UsageContractError as exc:
        print(
            json.dumps({"error": str(exc), "kind": "usage_contract"}), file=sys.stderr
        )
        return evidence.USAGE_OR_SCHEMA_EXIT
    except evidence.EvidenceError as exc:
        print(
            json.dumps({"error": str(exc), "kind": "evidence_contract"}),
            file=sys.stderr,
        )
        return evidence.USAGE_OR_SCHEMA_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
