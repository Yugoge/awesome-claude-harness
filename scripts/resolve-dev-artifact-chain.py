#!/usr/bin/env python3
"""Read-only resolver for singular and fan-out /dev artifact chains.

The resolver never creates, refreshes, or rewrites artifacts.  It validates the
chain rooted at ``docs/dev/dev-report-<task-id>.json`` and emits one stable JSON
document suitable for /dev completion, /close, Close QA, and /commit.

Exit codes:
    0  the complete artifact chain is valid
    2  invalid arguments, or a missing/stale/mismatched/ambiguous chain
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


SCHEMA_VERSION = 1
IDENTITY_RE = re.compile(
    r"^(?:[-*+]\s*)?(?:task[- ]id|request[- ]id)\s*:\s*(\S+)\s*$",
    re.IGNORECASE,
)
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
WORKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*$")


class StableArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def _load_aggregate_module() -> ModuleType:
    path = Path(__file__).with_name("aggregate-dev-report.py")
    module = ModuleType("_dev_aggregate")
    module.__file__ = str(path)
    source = path.read_bytes()
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


class ChainValidator:
    def __init__(self, project_root: Path, task_id: str) -> None:
        self.root = project_root
        self.dev_dir = project_root / "docs" / "dev"
        self.task_id = task_id
        self.errors: list[dict[str, str]] = []

    def error(self, code: str, path: str, detail: str) -> None:
        self.errors.append({"code": code, "path": path, "detail": detail})

    def read_json(self, path: Path, *, required: bool = True) -> dict[str, Any] | None:
        relative = _rel(path, self.root)
        if not path.is_file():
            if required:
                self.error("MISSING_ARTIFACT", relative, "required JSON artifact is absent")
            return None
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            self.error("UNREADABLE_ARTIFACT", relative, str(exc))
            return None
        if not raw.strip():
            self.error("EMPTY_ARTIFACT", relative, "JSON artifact is empty")
            return None
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            self.error(
                "MALFORMED_JSON",
                relative,
                f"line {exc.lineno}, column {exc.colno}: {exc.msg}",
            )
            return None
        if not isinstance(value, dict):
            self.error("INVALID_JSON_TYPE", relative, "top-level value must be an object")
            return None
        return value

    def read_text(self, path: Path, *, required: bool = True) -> str | None:
        relative = _rel(path, self.root)
        if not path.is_file():
            if required:
                self.error("MISSING_ARTIFACT", relative, "required Markdown artifact is absent")
            return None
        try:
            value = path.read_text(encoding="utf-8")
        except OSError as exc:
            self.error("UNREADABLE_ARTIFACT", relative, str(exc))
            return None
        if not value.strip():
            self.error("EMPTY_ARTIFACT", relative, "Markdown artifact is empty")
            return None
        return value

    def validate_json_identity(
        self, value: dict[str, Any], expected: str, path: Path
    ) -> None:
        relative = _rel(path, self.root)
        for key in ("request_id", "task_id"):
            actual = value.get(key)
            if actual != expected:
                self.error(
                    "IDENTITY_MISMATCH",
                    relative,
                    f"{key} is {actual!r}; expected {expected!r}",
                )

    def validate_markdown_identity(self, text: str, expected: str, path: Path) -> None:
        values: list[str] = []
        for line in text.splitlines():
            cleaned = line.strip().replace("**", "").replace("`", "")
            match = IDENTITY_RE.fullmatch(cleaned)
            if match:
                values.append(match.group(1))
        relative = _rel(path, self.root)
        if not values:
            self.error(
                "MISSING_IDENTITY",
                relative,
                "no TASK-ID, Task ID, or Request ID metadata was found",
            )
            return
        for actual in values:
            if actual != expected:
                self.error(
                    "IDENTITY_MISMATCH",
                    relative,
                    f"metadata identity is {actual!r}; expected {expected!r}",
                )

    def validate_dev(self, value: dict[str, Any], expected: str, path: Path) -> None:
        self.validate_json_identity(value, expected, path)
        relative = _rel(path, self.root)
        dev = value.get("dev")
        if not isinstance(dev, dict):
            self.error("INVALID_DEV_STATUS", relative, "dev must be an object")
            return
        if dev.get("status") != "completed":
            self.error(
                "INVALID_DEV_STATUS",
                relative,
                f"dev.status is {dev.get('status')!r}; expected 'completed'",
            )
        for key in ("files_modified", "files_created"):
            paths = dev.get(key)
            if not isinstance(paths, list) or any(
                not isinstance(item, str) or not item or "\x00" in item for item in paths
            ):
                self.error(
                    "INVALID_FILE_LIST",
                    relative,
                    f"dev.{key} must be an array of non-empty path strings",
                )
        blockers = value.get("blocking_issues", [])
        if not isinstance(blockers, list):
            self.error(
                "INVALID_BLOCKING_ISSUES",
                relative,
                "blocking_issues must be an array when present",
            )
        elif blockers:
            self.error(
                "UNRESOLVED_BLOCKERS",
                relative,
                "blocking_issues is not empty",
            )

    def validate_qa(self, value: dict[str, Any], expected: str, path: Path) -> None:
        self.validate_json_identity(value, expected, path)
        relative = _rel(path, self.root)
        qa = value.get("qa")
        if not isinstance(qa, dict) or qa.get("status") != "pass":
            actual = qa.get("status") if isinstance(qa, dict) else None
            self.error(
                "INVALID_QA_STATUS",
                relative,
                f"qa.status is {actual!r}; expected 'pass'",
            )

    def validate_completion(
        self, text: str, expected: str, path: Path, references: list[str]
    ) -> None:
        self.validate_markdown_identity(text, expected, path)
        relative = _rel(path, self.root)
        for reference in references:
            reference_pattern = re.compile(
                rf"(?<![A-Za-z0-9._/-]){re.escape(reference)}(?![A-Za-z0-9._/-])"
            )
            if reference_pattern.search(text) is None:
                self.error(
                    "MISSING_COMPLETION_REFERENCE",
                    relative,
                    f"completion does not reference {reference}",
                )


def _safe_task_id(task_id: str) -> bool:
    return bool(task_id not in {".", ".."} and TASK_ID_RE.fullmatch(task_id))


def _lane_paths(dev_dir: Path, task_id: str, worker: str) -> dict[str, Path]:
    lane_id = f"{task_id}-{worker}"
    return {
        "ticket": dev_dir / f"ticket-{lane_id}.md",
        "context": dev_dir / f"context-{lane_id}.json",
        "dev_report": dev_dir / f"dev-report-{lane_id}.json",
        "qa_report": dev_dir / f"qa-report-{lane_id}.json",
    }


def _parent_paths(dev_dir: Path, task_id: str) -> dict[str, Path]:
    return {
        "ticket": dev_dir / f"ticket-{task_id}.md",
        "context": dev_dir / f"context-{task_id}.json",
        "dev_report": dev_dir / f"dev-report-{task_id}.json",
        "qa_report": dev_dir / f"qa-report-{task_id}.json",
        "completion": dev_dir / f"completion-{task_id}.md",
    }


def _optional_parent_result(
    validator: ChainValidator,
    paths: dict[str, Path],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for kind in ("ticket", "context", "qa_report"):
        path = paths[kind]
        result[kind] = {
            "path": _rel(path, validator.root),
            "present": path.is_file(),
        }
        if not path.is_file():
            continue
        if kind == "ticket":
            text = validator.read_text(path)
            if text is not None:
                validator.validate_markdown_identity(text, validator.task_id, path)
        else:
            value = validator.read_json(path)
            if value is not None:
                if kind == "qa_report":
                    validator.validate_qa(value, validator.task_id, path)
                else:
                    validator.validate_json_identity(value, validator.task_id, path)
    return result


def _find_undeclared_lane_artifacts(
    validator: ChainValidator, workers: list[str]
) -> None:
    declared = set(workers)
    families = (
        ("ticket-", ".md"),
        ("context-", ".json"),
        ("qa-report-", ".json"),
    )
    for prefix, suffix in families:
        start = f"{prefix}{validator.task_id}-"
        for path in sorted(validator.dev_dir.glob(f"{start}*{suffix}")):
            worker = path.name[len(start) : -len(suffix)]
            if worker not in declared:
                validator.error(
                    "UNDECLARED_LANE_ARTIFACT",
                    _rel(path, validator.root),
                    f"worker {worker!r} is not in canonical parallel_workers",
                )


def _base_result(task_id: str, canonical: str, completion: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "fail",
        "mode": "unknown",
        "task_id": task_id,
        "canonical_dev_report": canonical,
        "completion": completion,
        "parallel_workers": [],
        "lanes": [],
        "optional_parent_artifacts": {},
        "report_paths": [],
        "artifact_paths": [],
        "commit_whitelist_artifacts": [],
        "qa_inputs": [],
        "checks": {
            "canonical_fresh": False,
            "file_unions_exact": False,
        },
        "errors": [],
    }


def resolve_chain(project_root: Path | str, task_id: str) -> dict[str, Any]:
    """Resolve and validate one artifact chain without mutating the filesystem."""
    root = Path(project_root).resolve()
    task_id = task_id.strip()
    dev_dir = root / "docs" / "dev"
    parents = _parent_paths(dev_dir, task_id)
    result = _base_result(
        task_id,
        _rel(parents["dev_report"], root),
        _rel(parents["completion"], root),
    )
    validator = ChainValidator(root, task_id)

    if not _safe_task_id(task_id):
        validator.error(
            "INVALID_TASK_ID",
            "",
            "task-id must be a safe, non-empty filename component",
        )
        result["errors"] = validator.errors
        return result
    if not dev_dir.is_dir():
        validator.error(
            "MISSING_DEV_DIRECTORY",
            _rel(dev_dir, root),
            "docs/dev directory is absent",
        )
        result["errors"] = validator.errors
        return result

    canonical = validator.read_json(parents["dev_report"])
    completion = validator.read_text(parents["completion"])
    if canonical is None:
        result["errors"] = validator.errors
        return result

    validator.validate_dev(canonical, task_id, parents["dev_report"])
    workers_value = canonical.get("parallel_workers", [])
    workers: list[str] = []
    if not isinstance(workers_value, list) or any(
        not isinstance(worker, str) or not WORKER_RE.fullmatch(worker)
        for worker in workers_value
    ):
        validator.error(
            "INVALID_WORKER_SET",
            result["canonical_dev_report"],
            "parallel_workers must be an array of valid worker labels",
        )
    else:
        workers = list(workers_value)
        if len(set(workers)) != len(workers):
            validator.error(
                "AMBIGUOUS_WORKER_SET",
                result["canonical_dev_report"],
                "parallel_workers contains duplicates",
            )

    try:
        aggregate = _load_aggregate_module()
        bare_task_id = aggregate._bare_task_id(task_id)
        scanned = []
        try:
            children = sorted(dev_dir.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            validator.error(
                "UNREADABLE_DEV_DIRECTORY", _rel(dev_dir, root), str(exc)
            )
            children = []
        for child in children:
            if not child.is_file():
                continue
            is_worker, label = aggregate._is_worker_for_task(
                child.name, bare_task_id, task_id
            )
            if is_worker and label is not None:
                scanned.append((label, child))
        scanned.sort(key=lambda item: item[0])
    except Exception as exc:
        validator.error(
            "AGGREGATE_IMPLEMENTATION_ERROR",
            "scripts/aggregate-dev-report.py",
            str(exc),
        )
        scanned = []
        aggregate = None

    if workers:
        result["mode"] = "fanout"
        if len(workers) < 2:
            validator.error(
                "AMBIGUOUS_WORKER_SET",
                result["canonical_dev_report"],
                "fan-out requires at least two workers",
            )
        scanned_labels = [worker for worker, _ in scanned]
        if scanned_labels != workers:
            validator.error(
                "LANE_SET_MISMATCH",
                result["canonical_dev_report"],
                f"parallel_workers {workers!r} do not exactly match shards {scanned_labels!r}",
            )
        _find_undeclared_lane_artifacts(validator, workers)

        loaded_shards: list[tuple[str, dict[str, Any]]] = []
        completion_refs = [result["canonical_dev_report"]]
        artifact_paths = [result["canonical_dev_report"], result["completion"]]
        result["report_paths"] = [result["canonical_dev_report"]]
        for worker in workers:
            lane_id = f"{task_id}-{worker}"
            paths = _lane_paths(dev_dir, task_id, worker)
            lane = {
                "worker": worker,
                "task_id": lane_id,
                **{key: _rel(path, root) for key, path in paths.items()},
            }
            result["lanes"].append(lane)
            result["report_paths"].extend((lane["dev_report"], lane["qa_report"]))
            lane_refs = [lane[key] for key in ("ticket", "context", "dev_report", "qa_report")]
            completion_refs.extend(lane_refs)
            artifact_paths.extend(lane_refs)

            ticket = validator.read_text(paths["ticket"])
            if ticket is not None:
                validator.validate_markdown_identity(ticket, lane_id, paths["ticket"])
            context = validator.read_json(paths["context"])
            if context is not None:
                validator.validate_json_identity(context, lane_id, paths["context"])
            dev = validator.read_json(paths["dev_report"])
            if dev is not None:
                validator.validate_dev(dev, lane_id, paths["dev_report"])
                loaded_shards.append((worker, dev))
            qa = validator.read_json(paths["qa_report"])
            if qa is not None:
                validator.validate_qa(qa, lane_id, paths["qa_report"])

        if completion is not None:
            validator.validate_completion(
                completion, task_id, parents["completion"], completion_refs
            )
        optional = _optional_parent_result(validator, parents)
        result["optional_parent_artifacts"] = optional
        artifact_paths.extend(
            value["path"] for value in optional.values() if value["present"]
        )
        if optional["qa_report"]["present"]:
            result["report_paths"].append(optional["qa_report"]["path"])
        result["artifact_paths"] = artifact_paths
        result["commit_whitelist_artifacts"] = artifact_paths
        result["qa_inputs"] = [
            {"task_id": lane["task_id"], "qa_report": lane["qa_report"]}
            for lane in result["lanes"]
        ]

        if aggregate is not None and len(loaded_shards) == len(workers):
            shard_errors = aggregate._validate_shards(loaded_shards, task_id)
            for detail in shard_errors:
                validator.error(
                    "INVALID_SHARD_SET", result["canonical_dev_report"], detail
                )
            if not shard_errors:
                expected = aggregate._build_aggregate(loaded_shards, task_id)
                result["checks"]["shard_provenance_exact"] = (
                    canonical.get("shard_provenance")
                    == expected.get("shard_provenance")
                )
                canonical_dev = canonical.get("dev")
                if not isinstance(canonical_dev, dict):
                    canonical_dev = {}
                result["checks"]["file_unions_exact"] = (
                    canonical_dev.get("files_modified")
                    == expected.get("dev", {}).get("files_modified")
                    and canonical_dev.get("files_created")
                    == expected.get("dev", {}).get("files_created")
                )
                result["checks"]["canonical_fresh"] = (
                    aggregate._canonical_projection(canonical)
                    == aggregate._canonical_projection(expected)
                )
                if not result["checks"]["shard_provenance_exact"]:
                    validator.error(
                        "STALE_SHARD_PROVENANCE",
                        result["canonical_dev_report"],
                        "canonical shard_provenance does not match current lane reports",
                    )
                if not result["checks"]["file_unions_exact"]:
                    validator.error(
                        "STALE_FILE_UNION",
                        result["canonical_dev_report"],
                        "canonical file unions do not match current lane reports",
                    )
                if not result["checks"]["canonical_fresh"]:
                    validator.error(
                        "STALE_CANONICAL",
                        result["canonical_dev_report"],
                        "canonical aggregate projection does not match current lane reports",
                    )
    else:
        result["mode"] = "singular"
        result["checks"] = {
            "canonical_fresh": True,
            "shard_provenance_exact": True,
            "file_unions_exact": True,
        }
        if scanned:
            validator.error(
                "AMBIGUOUS_SINGULAR_CHAIN",
                result["canonical_dev_report"],
                f"singular canonical coexists with worker shards {[label for label, _ in scanned]!r}",
            )
        completion_refs = [
            _rel(parents[key], root)
            for key in ("ticket", "context", "dev_report", "qa_report")
        ]
        ticket = validator.read_text(parents["ticket"])
        if ticket is not None:
            validator.validate_markdown_identity(ticket, task_id, parents["ticket"])
        context = validator.read_json(parents["context"])
        if context is not None:
            validator.validate_json_identity(context, task_id, parents["context"])
        qa = validator.read_json(parents["qa_report"])
        if qa is not None:
            validator.validate_qa(qa, task_id, parents["qa_report"])
        if completion is not None:
            validator.validate_completion(
                completion, task_id, parents["completion"], completion_refs
            )
        result["report_paths"] = [
            result["canonical_dev_report"],
            _rel(parents["qa_report"], root),
        ]
        result["artifact_paths"] = completion_refs + [result["completion"]]
        result["commit_whitelist_artifacts"] = list(result["artifact_paths"])
        result["qa_inputs"] = [
            {"task_id": task_id, "qa_report": _rel(parents["qa_report"], root)}
        ]

    result["parallel_workers"] = workers
    result["errors"] = validator.errors
    result["status"] = "pass" if not validator.errors else "fail"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = StableArgumentParser(prog="resolve-dev-artifact-chain.py")
    parser.add_argument("--task-id", required=True)
    parser.add_argument(
        "--project-dir",
        default=str(Path(__file__).resolve().parent.parent),
    )
    try:
        args = parser.parse_args(argv)
    except ValueError as exc:
        result = _base_result("", "", "")
        result["errors"] = [
            {"code": "CLI_ARGUMENT_ERROR", "path": "", "detail": str(exc)}
        ]
        print(
            json.dumps(
                result, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
        )
        return 2
    result = resolve_chain(args.project_dir, args.task_id)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    sys.exit(main())
