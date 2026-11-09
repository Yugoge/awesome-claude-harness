#!/usr/bin/env python3
# Description: Wave-1 skeleton harness for /dev-overnight regression eval cases.
# Usage: runner.py [--smoke | --extended | --regression | --case <id> | --category <name>] [--json]
# Exit codes: 0 = all pass, 1 = any case validation fails, 2 = no cases found in selected scope
#
# Wave-1 scope: schema-validate each case dir's spec.md + expected.json. Does NOT yet
# drive actual /dev-overnight invocations (that comes after Wave 4 lands the 100+ cases).

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EVAL_ROOT = Path("/root/.claude/eval")
CASES_ROOT = EVAL_ROOT / "cases"

CATEGORIES = {
    "bug-fix",
    "ui-target",
    "ui-audit",
    "backend-api",
    "infra-hook",
    "docs-research",
}

EXPECTED_KEYS = {
    "pipelines_count",
    "tier_distribution",
    "verdict_pattern",
    "evidence_kind_required",
    "ui_evidence_required",
    "pages_visited_minimum",
    "screenshots_minimum",
    "both_viewports_required",
    "ui_pipeline",
    "dev_only_modify",
    "primary_artifact",
}

REQUIRED_CORE_KEYS = {
    "pipelines_count",
    "tier_distribution",
    "verdict_pattern",
    "evidence_kind_required",
    "ui_evidence_required",
}


def case_id_to_category(case_id: str) -> str | None:
    for cat in sorted(CATEGORIES, key=len, reverse=True):
        if case_id == cat or case_id.startswith(cat + "-"):
            return cat
    return None


def discover_cases() -> list[Path]:
    if not CASES_ROOT.is_dir():
        return []
    return sorted(p for p in CASES_ROOT.iterdir() if p.is_dir())


def filter_cases(all_cases, *, smoke, extended, regression, case, category):
    if case is not None:
        return [p for p in all_cases if p.name == case]
    if category is not None:
        return [p for p in all_cases if case_id_to_category(p.name) == category]
    if smoke:
        return [p for p in all_cases if "-smoke-" in p.name]
    if extended:
        return all_cases[:30]
    if regression:
        return all_cases
    return []


def _check_spec(spec_path: Path) -> list[str]:
    errors: list[str] = []
    if not spec_path.is_file():
        return ["missing spec.md"]
    try:
        spec_text = spec_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"unreadable spec.md: {exc}"]
    non_empty = [ln for ln in spec_text.splitlines() if ln.strip()]
    if len(non_empty) < 1:
        errors.append("spec.md is empty (need >= 1 non-empty line)")
    return errors


def _check_expected_json(exp_path: Path) -> list[str]:
    if not exp_path.is_file():
        return ["missing expected.json"]
    try:
        data = json.loads(exp_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"expected.json invalid JSON: {exc}"]
    if not isinstance(data, dict):
        return ["expected.json must be a JSON object at top level"]
    if not (set(data.keys()) & REQUIRED_CORE_KEYS):
        return [
            "expected.json must declare at least one of: "
            + ", ".join(sorted(REQUIRED_CORE_KEYS))
        ]
    return []


def _check_category(case_name: str) -> list[str]:
    if case_id_to_category(case_name) is None:
        return [f"case id '{case_name}' does not match any known category prefix"]
    return []


def validate_case(case_dir: Path) -> tuple[str, list[str]]:
    errors: list[str] = []
    errors.extend(_check_spec(case_dir / "spec.md"))
    errors.extend(_check_expected_json(case_dir / "expected.json"))
    errors.extend(_check_category(case_dir.name))
    return ("pass" if not errors else "fail", errors)


def emit_human(results: list[dict], total_selected: int) -> None:
    passes = sum(1 for r in results if r["status"] == "pass")
    fails = sum(1 for r in results if r["status"] == "fail")
    for r in results:
        marker = "PASS" if r["status"] == "pass" else "FAIL"
        print(f"[{marker}] {r['case_id']} ({r['category'] or '?'})")
        for err in r["errors"]:
            print(f"       - {err}")
    print(f"\nTotal selected: {total_selected}  pass: {passes}  fail: {fails}")


def emit_json(results: list[dict], total_selected: int) -> None:
    summary = {
        "total_selected": total_selected,
        "pass_count": sum(1 for r in results if r["status"] == "pass"),
        "fail_count": sum(1 for r in results if r["status"] == "fail"),
        "results": results,
    }
    print(json.dumps(summary, indent=2))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Wave-1 skeleton harness for /dev-overnight regression eval cases."
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--smoke", action="store_true", help="Validate smoke cases (one per category).")
    scope.add_argument("--extended", action="store_true", help="Validate first 30 cases across categories.")
    scope.add_argument("--regression", action="store_true", help="Validate ALL cases.")
    scope.add_argument("--case", type=str, default=None, help="Validate a single case by id.")
    scope.add_argument("--category", type=str, default=None, help="Validate all cases in a category.")
    parser.add_argument("--json", action="store_true", help="Emit JSON results to stdout instead of human text.")
    return parser


def _validate_args(args) -> int | None:
    if args.category is not None and args.category not in CATEGORIES:
        print(
            f"error: unknown category '{args.category}'. Known: {', '.join(sorted(CATEGORIES))}",
            file=sys.stderr,
        )
        return 2
    return None


def _run_validations(selected: list[Path]) -> list[dict]:
    results: list[dict] = []
    for case_dir in selected:
        status, errors = validate_case(case_dir)
        results.append(
            {
                "case_id": case_dir.name,
                "category": case_id_to_category(case_dir.name),
                "status": status,
                "errors": errors,
            }
        )
    return results


def main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    err_code = _validate_args(args)
    if err_code is not None:
        return err_code
    selected = filter_cases(
        discover_cases(),
        smoke=args.smoke,
        extended=args.extended,
        regression=args.regression,
        case=args.case,
        category=args.category,
    )
    if not selected:
        print("no cases found in selected scope", file=sys.stderr)
        return 2
    results = _run_validations(selected)
    (emit_json if args.json else emit_human)(results, total_selected=len(selected))
    return 1 if any(r["status"] == "fail" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
