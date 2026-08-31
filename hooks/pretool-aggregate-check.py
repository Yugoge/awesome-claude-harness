#!/usr/bin/env python3
"""Phase-aware R1 guard for QA dispatches.

Only exact artifact paths explicitly present in the dispatch prompt select QA
targets.  An exact validated member binding additionally selects its one
normative parent canonical as validation context, whether or not the prompt
names it.  The hook never performs a global historical scan, truncates an id, or
guesses a parent from a filename.  A declared member may reach lane QA before
its parent canonical exists; an existing canonical is always authoritative.
"""
from __future__ import annotations

import json
import os
import re
import stat
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from lib.allowlist import read_grant  # noqa: E402

DEV_REPORT_REF_RE = re.compile(r"(?<![A-Za-z0-9._/-])(docs/dev/dev-report-[A-Za-z0-9][A-Za-z0-9._-]*\.json)(?![A-Za-z0-9._/-])")


def _load_aggregate() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "scripts" / "aggregate-dev-report.py"
    module = ModuleType("_r1_aggregate_hook")
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module


def _load_stdin() -> dict[str, Any] | None:
    try:
        value = json.load(sys.stdin)
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _is_qa_dispatch(data: dict[str, Any] | None) -> bool:
    if not isinstance(data, dict) or data.get("tool_name") not in {"Agent", "Task"}:
        return False
    tool_input = data.get("tool_input")
    return isinstance(tool_input, dict) and tool_input.get("subagent_type") == "qa"


def _prompt(data: dict[str, Any]) -> str:
    tool_input = data.get("tool_input")
    value = tool_input.get("prompt") if isinstance(tool_input, dict) else ""
    return value if isinstance(value, str) else ""


def _project_root() -> Path | None:
    raw = os.environ.get("CLAUDE_PROJECT_DIR")
    if not raw:
        raw = os.getcwd()
    try:
        root = Path(raw).resolve(strict=True)
    except OSError:
        return None
    return root if (root / "docs" / "dev").is_dir() else None


def _explicit_report_paths(prompt: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for match in DEV_REPORT_REF_RE.finditer(prompt):
        path = match.group(1)
        if path not in seen:
            seen.add(path)
            result.append(path)
    return result


def _read_report_snapshot(
    root: Path, relative: str, aggregate: ModuleType,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, str]]]:
    """Read one stable, real, in-root report and retain its exact binding."""
    try:
        raw, fingerprint = aggregate._read_regular_file_snapshot(root, relative)
        report = aggregate.load_json_bytes(raw, relative)
    except aggregate.ContractFailure as exc:
        return None, None, [
            _error(item["code"], relative, item["message"])
            for item in exc.errors
        ]
    if type(report) is not dict:
        return None, None, [_error("INVALID_DECLARATION", relative, "Dev report must be an exact JSON object")]
    return report, {
        "fingerprint": fingerprint,
        "sha256": aggregate._bytes_digest(raw, prefixed=False),
    }, []


def _read_exact_parent_snapshot(
    root: Path, parent_task_id: str, aggregate: ModuleType,
) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None, bool, list[dict[str, str]]]:
    """Resolve exactly one normative parent, distinguishing stable absence."""
    relative = f"docs/dev/dev-report-{parent_task_id}.json"
    directory_fd: int | None = None
    try:
        directory_fd, directory_identity = aggregate._open_directory_beneath(root, "docs/dev")
        namespace_before = aggregate._file_fingerprint(os.fstat(directory_fd))
        try:
            metadata = os.stat(relative.removeprefix("docs/dev/"), dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            if aggregate._file_fingerprint(os.fstat(directory_fd)) != namespace_before:
                return relative, None, None, False, [_error(
                    "STALE_CANONICAL", relative,
                    "exact parent namespace changed while canonical absence was inspected",
                )]
            verify_fd, verify_identity = aggregate._open_directory_beneath(root, "docs/dev")
            os.close(verify_fd)
            if verify_identity != directory_identity:
                return relative, None, None, False, [_error(
                    "STALE_CANONICAL", relative,
                    "exact parent directory changed while canonical absence was inspected",
                )]
            return relative, None, None, True, []
        except OSError as exc:
            return relative, None, None, False, [_error(
                "IO_ERROR", relative, f"cannot inspect exact parent canonical: {exc}",
            )]
        if not stat.S_ISREG(metadata.st_mode):
            return relative, None, None, False, [_error(
                "INVENTORY_MISMATCH", relative,
                "existing exact parent canonical must be a real regular file",
            )]
        try:
            raw, fingerprint = aggregate._read_regular_file_at(
                directory_fd, relative.removeprefix("docs/dev/"), relative,
            )
        except aggregate.ContractFailure as exc:
            return relative, None, None, False, [_error(
                "STALE_CANONICAL", relative,
                f"existing exact parent canonical changed during inspection: {item['message']}",
            ) for item in exc.errors]
        if fingerprint != aggregate._file_fingerprint(metadata):
            return relative, None, None, False, [_error(
                "STALE_CANONICAL", relative,
                "existing exact parent canonical was replaced after discovery",
            )]
        if aggregate._file_fingerprint(os.fstat(directory_fd)) != namespace_before:
            return relative, None, None, False, [_error(
                "STALE_CANONICAL", relative,
                "exact parent namespace changed during canonical inspection",
            )]
    except aggregate.ContractFailure as exc:
        return relative, None, None, False, [
            _error(item["code"], relative, item["message"])
            for item in exc.errors
        ]
    finally:
        if directory_fd is not None:
            os.close(directory_fd)
    try:
        report = aggregate.load_json_bytes(raw, relative)
    except aggregate.ContractFailure as exc:
        return relative, None, None, False, [
            _error(item["code"], relative, item["message"])
            for item in exc.errors
        ]
    if type(report) is not dict:
        return relative, None, None, False, [_error(
            "INVALID_DECLARATION", relative,
            "existing exact parent canonical must be an exact JSON object",
        )]
    return relative, report, {
        "fingerprint": fingerprint,
        "sha256": aggregate._bytes_digest(raw, prefixed=False),
    }, False, []


def _error(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _valid_member_binding(report: dict[str, Any], aggregate: ModuleType) -> bool:
    binding = report.get("artifact_chain_binding")
    return (
        type(binding) is dict
        and set(binding) == {"parent_task_id", "member_id", "lineage_digest", "attempt"}
        and report.get("artifact_chain_role") == "lifecycle_declared_member"
        and aggregate._safe_task_id(binding.get("parent_task_id"))
        and aggregate._safe_task_id(binding.get("member_id"))
        and aggregate._is_int(binding.get("attempt"), 1)
        and aggregate._validate_digest(binding.get("lineage_digest"))
    )


def _validate_parent_report(
    root: Path, relative: str, report: dict[str, Any], expected_parent: str,
    aggregate: ModuleType, violations: list[dict[str, str]],
) -> dict[str, Any] | None:
    declaration = report.get("artifact_chain_declaration")
    if type(declaration) is not dict:
        violations.append(_error(
            "MISSING_DECLARATION", relative,
            "existing exact parent canonical lacks an embedded declaration",
        ))
        return None
    normalized, errors = aggregate.validate_declaration(
        declaration, expected_parent, root=root, validate_artifacts=True,
    )
    if errors or normalized is None:
        violations.extend(_error(
            item["code"],
            item["path"] if isinstance(item.get("path"), str) and item["path"].startswith("docs/dev/") else relative,
            item["message"],
        ) for item in errors)
        return None
    aggregate._identity(report, expected_parent, relative, violations)
    aggregate._dev_status(report, relative, violations)
    if normalized["shape"] == "singular":
        aggregate._validate_mutable_singular_current(report, normalized, violations)
    else:
        source_errors: list[dict[str, str]] = []
        sources = aggregate._load_active_sources(root, normalized, source_errors)
        violations.extend(source_errors)
        if not source_errors and len(sources) == len(normalized["active_roster"]):
            expected = aggregate._build_aggregate(
                sources, expected_parent, normalized, timestamp=report.get("timestamp"),
            )
            if aggregate._canonical_projection(report) != aggregate._canonical_projection(expected):
                violations.append(_error(
                    "STALE_CANONICAL", relative,
                    "parent canonical is not fresh for its exact declared sources and phase",
                ))
    return normalized


def _revalidate_snapshots(
    root: Path, snapshots: dict[str, dict[str, Any]], aggregate: ModuleType,
    violations: list[dict[str, str]],
) -> None:
    """Close replacement/removal races after declaration/artifact validation."""
    for relative, expected in snapshots.items():
        try:
            raw, fingerprint = aggregate._read_regular_file_snapshot(root, relative)
        except aggregate.ContractFailure as exc:
            violations.append(_error(
                "STALE_CANONICAL", relative,
                "R1 QA input changed after discovery: " + "; ".join(item["message"] for item in exc.errors),
            ))
            continue
        if (fingerprint != expected["fingerprint"]
                or aggregate._bytes_digest(raw, prefixed=False) != expected["sha256"]):
            violations.append(_error(
                "STALE_CANONICAL", relative,
                "R1 QA input identity or bytes changed during dispatch inspection",
            ))


def _revalidate_parent_absence(
    root: Path, absent_parents: set[str], aggregate: ModuleType,
    violations: list[dict[str, str]],
) -> None:
    """Do not let a parent appear after the pre-parent allowance was chosen."""
    for parent in sorted(absent_parents):
        relative, report, _snapshot, absent, errors = _read_exact_parent_snapshot(
            root, parent, aggregate,
        )
        if errors:
            violations.extend(errors)
        elif not absent or report is not None:
            violations.append(_error(
                "STALE_CANONICAL", relative,
                "exact parent canonical appeared during pre-parent dispatch inspection",
            ))


def _inspect_dispatch(root: Path, prompt: str) -> list[dict[str, str]]:
    aggregate = _load_aggregate()
    paths = _explicit_report_paths(prompt)
    if not paths:
        return []
    explicit_parent_candidates: dict[str, tuple[str, dict[str, Any]]] = {}
    validation_parent_candidates: dict[str, tuple[str, dict[str, Any]]] = {}
    members: list[tuple[str, dict[str, Any]]] = []
    snapshots: dict[str, dict[str, Any]] = {}
    absent_parents: set[str] = set()
    recognized = False
    violations: list[dict[str, str]] = []
    for relative in paths:
        report, snapshot, _read_errors = _read_report_snapshot(root, relative, aggregate)
        if report is None:
            # Explicitly named but not yet written reports (especially QA outputs)
            # are not R1 inputs. A named Dev report that is absent is actionable.
            if "/dev-report-" in relative:
                recognized = True
                violations.append(_error("MISSING_ARTIFACT", relative, "explicit QA input Dev report is absent or invalid"))
            continue
        snapshots[relative] = snapshot
        role = report.get("artifact_chain_role")
        declaration = report.get("artifact_chain_declaration")
        binding = report.get("artifact_chain_binding")
        if role == "overnight_pipeline_intermediate":
            recognized = True
            if declaration is not None:
                violations.append(_error("NON_LIFECYCLE_REPORT", relative, "overnight intermediate declaration must be null"))
            # Overnight has its own per-pipeline QA and is outside R1 lifecycle.
            continue
        if isinstance(declaration, dict):
            recognized = True
            parent = declaration.get("parent_task_id")
            expected_parent = parent if isinstance(parent, str) else ""
            normalized = _validate_parent_report(
                root, relative, report, expected_parent, aggregate, violations,
            )
            if normalized is not None:
                if parent in explicit_parent_candidates and explicit_parent_candidates[parent][0] != relative:
                    violations.append(_error(
                        "AMBIGUOUS_PARENT_MEMBERSHIP", "docs/dev",
                        "QA prompt names multiple declaration authorities for one parent",
                    ))
                explicit_parent_candidates[parent] = (relative, normalized)
                validation_parent_candidates[parent] = (relative, normalized)
        elif isinstance(binding, dict):
            recognized = True
            members.append((relative, report))
    if not recognized:
        # Legacy/non-R1 QA remains outside this focused hook contract.
        return []
    valid_members: list[tuple[str, dict[str, Any]]] = []
    for relative, report in members:
        if not _valid_member_binding(report, aggregate):
            violations.append(_error("INVALID_IDENTITY", relative, "member report has a malformed exact artifact_chain_binding"))
            continue
        valid_members.append((relative, report))
        dev = report.get("dev")
        if not isinstance(dev, dict) or dev.get("status") != "completed":
            violations.append(_error("INVALID_STATUS", relative, "member QA requires dev.status=completed"))

    bound_parent_ids = {
        report["artifact_chain_binding"]["parent_task_id"]
        for _, report in valid_members
    }
    combined_parent_ids = set(explicit_parent_candidates) | bound_parent_ids
    if len(combined_parent_ids) > 1:
        violations.append(_error(
            "AMBIGUOUS_PARENT_MEMBERSHIP", "docs/dev",
            "QA prompt selects members or declarations from multiple exact parents",
        ))

    for parent in sorted(bound_parent_ids):
        normative = f"docs/dev/dev-report-{parent}.json"
        explicit = validation_parent_candidates.get(parent)
        if explicit is not None and explicit[0] == normative:
            continue
        relative, report, snapshot, absent, parent_errors = _read_exact_parent_snapshot(
            root, parent, aggregate,
        )
        violations.extend(parent_errors)
        if absent:
            absent_parents.add(parent)
            continue
        if report is None:
            continue
        snapshots[relative] = snapshot
        normalized = _validate_parent_report(
            root, relative, report, parent, aggregate, violations,
        )
        if normalized is not None:
            if explicit is not None and explicit[0] != relative:
                violations.append(_error(
                    "AMBIGUOUS_PARENT_MEMBERSHIP", "docs/dev",
                    "prompt declaration and exact binding resolve different parent artifacts",
                ))
            validation_parent_candidates[parent] = (relative, normalized)

    sole_parent = (
        next(iter(explicit_parent_candidates.values()))[1]
        if len(explicit_parent_candidates) == 1 else None
    )
    active_parent_members = (
        {member["member_id"] for member in sole_parent["phase_projection"]["members"] if member["state"] != "superseded"}
        if sole_parent is not None else set()
    )
    prompt_member_ids = {
        report.get("artifact_chain_binding", {}).get("member_id")
        for _, report in valid_members
    }
    fanout_parent_scope = (
        sole_parent is not None and sole_parent["shape"] == "requirement_fanout"
        and bool(active_parent_members) and prompt_member_ids == active_parent_members
    )
    member_scope = bool(members) and (
        sole_parent is None
        or sole_parent["shape"] == "requirement_fanout" and not fanout_parent_scope
    )
    # Member/lane QA is exact and may precede a parent canonical.
    if member_scope:
        for relative, report in valid_members:
            binding = report["artifact_chain_binding"]
            parent_tuple = validation_parent_candidates.get(binding["parent_task_id"])
            if parent_tuple is None:
                # Explicitly allowed: lane QA must be able to produce evidence
                # needed by a later audited parent canonical.
                continue
            _, declaration = parent_tuple
            if declaration["lineage_digest"] != binding["lineage_digest"]:
                violations.append(_error("INVALID_IDENTITY", relative, "member lineage digest differs from the parent declaration"))
                continue
            member = next((m for m in declaration["phase_projection"]["members"] if m["member_id"] == binding["member_id"]), None)
            if member is None or member["attempt"] != binding["attempt"]:
                violations.append(_error("INVALID_IDENTITY", relative, "member/attempt is not active in the exact parent phase"))
            elif member["state"] not in {"dev_completed", "awaiting_qa"}:
                violations.append(_error("INVALID_PHASE_TRANSITION", relative, f"lane QA requires dev_completed/awaiting_qa; observed {member['state']}"))
        _revalidate_snapshots(root, snapshots, aggregate, violations)
        _revalidate_parent_absence(root, absent_parents, aggregate, violations)
        return violations
    # Parent-scoped QA or Close QA: one exact declaration only.
    if len(explicit_parent_candidates) != 1:
        if len(explicit_parent_candidates) > 1:
            violations.append(_error("AMBIGUOUS_PARENT_MEMBERSHIP", "docs/dev", "QA prompt names multiple declared parents"))
        _revalidate_snapshots(root, snapshots, aggregate, violations)
        _revalidate_parent_absence(root, absent_parents, aggregate, violations)
        return violations
    relative, declaration = next(iter(explicit_parent_candidates.values()))
    active = [member for member in declaration["phase_projection"]["members"] if member["state"] != "superseded"]
    states = [member["state"] for member in active]
    if declaration["shape"] == "requirement_fanout" and not all(state == "qa_pass" for state in states):
        violations.append(_error("INVALID_PHASE_TRANSITION", relative, "requirement_fanout implementation QA is member-scoped; parent final QA requires every active lane qa_pass"))
    elif declaration["shape"] != "requirement_fanout" and not states or any(state not in {"awaiting_qa", "qa_pass"} for state in states):
        violations.append(_error("INVALID_PHASE_TRANSITION", relative, f"parent QA/final QA requires awaiting_qa or already-passed active members; observed {states}"))
    _revalidate_snapshots(root, snapshots, aggregate, violations)
    _revalidate_parent_absence(root, absent_parents, aggregate, violations)
    return violations


def _bypassed(data: dict[str, Any]) -> bool:
    if data.get("agent_id"):
        return False
    sid = data.get("session_id") or os.environ.get("CLAUDE_SESSION_ID", "") or "default"
    try:
        flag = Path(f"/tmp/claude-orchestrator-consent-{sid}.flag")
        if flag.exists() and flag.read_text().strip() == "true":
            return True
    except Exception:
        pass
    try:
        return bool(read_grant("Agent", sid))
    except Exception:
        return False


def _emit_block(root: Path, violations: list[dict[str, str]]) -> None:
    payload = {
        "schema_version": "artifact_chain_qa_gate.v1", "status": "blocked",
        "project_root": str(root), "errors": violations,
    }
    sys.stderr.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    raise SystemExit(2)


def main() -> None:
    data = _load_stdin()
    if data is None or not _is_qa_dispatch(data) or _bypassed(data):
        raise SystemExit(0)
    root = _project_root()
    if root is None:
        # The hook cannot safely choose another tree; do not scan globally.
        raise SystemExit(0)
    violations = _inspect_dispatch(root, _prompt(data))
    if violations:
        _emit_block(root, violations)
    raise SystemExit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # Hook self-failure remains non-terminal for unrelated Agent dispatches.
        raise SystemExit(0)
