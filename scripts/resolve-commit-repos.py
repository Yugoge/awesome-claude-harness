#!/usr/bin/env python3
"""Resolve a closed task's owned paths into an admitted repository plan.

The normal ``/commit`` workflow uses this helper before it writes any commit
grant.  A dev/do report is the ownership authority, but it is not repository
admission authority: every resolved owner must also be one of the explicitly
supported repositories supplied by the command orchestrator.

The emitted JSON binds each admitted repository to its current branch and HEAD
so the changelog analyst can apply the same CAS boundary before staging and
again before committing.  This helper never changes a repository or its index.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


class PlanError(RuntimeError):
    """A fail-closed repository-plan admission error."""


def _git_capture(repo_or_path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_or_path), *args],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git command failed").strip()
        raise PlanError(f"git -C {repo_or_path} {' '.join(args)}: {detail}")
    return result.stdout.strip()


def _repo_root(path: Path) -> Path:
    anchor = path if path.is_dir() else path.parent
    return Path(_git_capture(anchor, "rev-parse", "--show-toplevel")).resolve()


def _existing_ancestor(path: Path) -> Path:
    candidate = path
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            raise PlanError(f"owned path has no existing ancestor: {path}")
        candidate = parent
    return candidate


def _canonical_owned_path(raw: str, control_root: Path) -> Path:
    if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
        raise PlanError("owned paths must be non-empty NUL-free strings")
    candidate = Path(os.path.expanduser(raw))
    if not candidate.is_absolute():
        candidate = control_root / candidate

    # resolve(strict=False) normalizes '..' and resolves every existing symlink
    # prefix while still supporting a not-yet-created files_created entry.
    resolved = candidate.resolve(strict=False)
    _existing_ancestor(resolved)
    return resolved


def _contains(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _load_report(path: Path, task_id: str) -> tuple[dict[str, Any], str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanError(f"cannot read report {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PlanError(f"report is not a JSON object: {path}")
    identities = [
        payload.get(field)
        for field in ("task_id", "request_id")
        if payload.get(field) is not None
    ]
    if not identities or any(identity != task_id for identity in identities):
        raise PlanError(f"report task id does not match {task_id}: {path}")

    if path.name == f"dev-report-{task_id}.json":
        section_name = "dev"
    elif path.name == f"do-report-{task_id}.json" and payload.get("source") == "do":
        section_name = "do"
    else:
        raise PlanError(f"report is neither a canonical dev report nor a source=do report: {path}")
    section = payload.get(section_name)
    if not isinstance(section, dict):
        raise PlanError(f"report is missing object field {section_name}: {path}")
    return payload, section_name


def _resolve_report(control_root: Path, task_id: str, explicit: str | None) -> Path:
    if explicit:
        report = Path(explicit).expanduser().resolve()
        if not report.is_file():
            raise PlanError(f"explicit report does not exist: {report}")
        return report
    docs = control_root / "docs" / "dev"
    for name in (f"dev-report-{task_id}.json", f"do-report-{task_id}.json"):
        candidate = docs / name
        if candidate.is_file():
            return candidate.resolve()
    raise PlanError(f"no dev/do report found for task {task_id} under {docs}")


def build_plan(
    *,
    task_id: str,
    control_root_arg: str,
    supported_repo_args: list[str],
    report_arg: str | None = None,
) -> dict[str, Any]:
    if not task_id.strip():
        raise PlanError("task id must be non-empty")
    control_root = _repo_root(Path(control_root_arg).expanduser().resolve())
    report_path = _resolve_report(control_root, task_id, report_arg)
    if not _contains(control_root, report_path):
        raise PlanError(f"report must resolve under the control repository: {report_path}")
    payload, section_name = _load_report(report_path, task_id)
    section = payload[section_name]

    supported: list[Path] = []
    for raw in [str(control_root), *supported_repo_args]:
        repo = _repo_root(Path(raw).expanduser().resolve())
        if repo not in supported:
            supported.append(repo)

    owned_raw: list[str] = []
    for field in ("files_modified", "files_created"):
        values = section.get(field, [])
        if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
            raise PlanError(f"{section_name}.{field} must be an array of strings")
        owned_raw.extend(values)

    by_repo: dict[Path, list[str]] = {control_root: []}
    for raw in owned_raw:
        absolute = _canonical_owned_path(raw, control_root)
        actual_owner = _repo_root(_existing_ancestor(absolute))
        if actual_owner not in supported:
            raise PlanError(f"owned path is outside the supported repository set: {raw}")
        # Git, not pathname containment alone, determines ownership. This rejects
        # an unadmitted nested checkout instead of laundering it through an
        # admitted outer repository.
        owner = actual_owner
        relative = absolute.relative_to(owner).as_posix()
        if relative == "." or relative.startswith("../"):
            raise PlanError(f"owned path cannot name a repository root: {raw}")
        by_repo.setdefault(owner, [])
        if relative not in by_repo[owner]:
            by_repo[owner].append(relative)

    targets: list[dict[str, Any]] = []
    ordered_roots = [control_root] + sorted(
        (root for root in by_repo if root != control_root), key=lambda item: str(item)
    )
    for order, root in enumerate(ordered_roots):
        branch = _git_capture(root, "branch", "--show-current")
        head = _git_capture(root, "rev-parse", "HEAD")
        if not branch or not head:
            raise PlanError(f"repository must have an attached branch and HEAD: {root}")
        targets.append(
            {
                "order": order,
                "repo_root": str(root),
                "branch": branch,
                "expected_head": head,
                "owned_paths": sorted(by_repo.get(root, [])),
                "cycle_artifact_repo": root == control_root,
            }
        )

    report_bytes = report_path.read_bytes()
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "report_path": str(report_path),
        "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "control_root": str(control_root),
        "repository_count": len(targets),
        "repositories": targets,
        "transaction_semantics": "ordered_non_atomic_with_partial_failure_reporting",
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--control-root", required=True)
    parser.add_argument("--supported-repo", action="append", default=[])
    parser.add_argument("--report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        plan = build_plan(
            task_id=args.task_id,
            control_root_arg=args.control_root,
            supported_repo_args=args.supported_repo,
            report_arg=args.report,
        )
    except PlanError as exc:
        print(f"resolve-commit-repos: BLOCKED: {exc}", file=sys.stderr)
        return 2
    json.dump(plan, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
