#!/usr/bin/env python3
"""Focused tests for the read-only /dev artifact-chain resolver."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESOLVER_PATH = REPO_ROOT / "scripts" / "resolve-dev-artifact-chain.py"
TASK_ID = "dev-20260724-120000"
WORKERS = ["lane-a", "lane-b"]


def _load_resolver():
    spec = importlib.util.spec_from_file_location("dev_chain_resolver", RESOLVER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RESOLVER = _load_resolver()


def _write(path: Path, value: str | dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, dict):
        value = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    path.write_text(value, encoding="utf-8")


def _dev_document(
    identity: str,
    *,
    modified: list[str] | None = None,
    created: list[str] | None = None,
) -> dict:
    return {
        "request_id": identity,
        "task_id": identity,
        "baseline_head_sha": "0123456789abcdef",
        "baseline_dirty_snapshot": "",
        "dev": {
            "status": "completed",
            "tasks_completed": [f"completed {identity}"],
            "scripts_created": [],
            "permissions_to_add": [],
            "files_modified": modified or [],
            "files_created": created or [],
            "observed_preexisting": [],
        },
        "blocking_issues": [],
        "recommendations": [],
    }


def _qa_document(identity: str, status: str = "pass") -> dict:
    return {
        "request_id": identity,
        "task_id": identity,
        "qa": {"status": status},
    }


def _ticket(identity: str) -> str:
    return f"# Ticket\n\n**TASK-ID**: `{identity}`\n"


def _completion(identity: str, references: list[str]) -> str:
    lines = [f"# Completion\n\n**Request ID**: `{identity}`\n"]
    lines.extend(f"- `{reference}`\n" for reference in references)
    return "".join(lines)


def _dev_dir(root: Path) -> Path:
    path = root / "docs" / "dev"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _parent_paths(root: Path) -> dict[str, Path]:
    dev_dir = _dev_dir(root)
    return {
        "ticket": dev_dir / f"ticket-{TASK_ID}.md",
        "context": dev_dir / f"context-{TASK_ID}.json",
        "dev": dev_dir / f"dev-report-{TASK_ID}.json",
        "qa": dev_dir / f"qa-report-{TASK_ID}.json",
        "completion": dev_dir / f"completion-{TASK_ID}.md",
    }


def _lane_paths(root: Path, worker: str) -> dict[str, Path]:
    dev_dir = _dev_dir(root)
    identity = f"{TASK_ID}-{worker}"
    return {
        "ticket": dev_dir / f"ticket-{identity}.md",
        "context": dev_dir / f"context-{identity}.json",
        "dev": dev_dir / f"dev-report-{identity}.json",
        "qa": dev_dir / f"qa-report-{identity}.json",
    }


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _make_singular(root: Path) -> dict[str, Path]:
    paths = _parent_paths(root)
    _write(paths["ticket"], _ticket(TASK_ID))
    _write(paths["context"], {"request_id": TASK_ID, "task_id": TASK_ID})
    _write(paths["dev"], _dev_document(TASK_ID, modified=["scripts/one.py"]))
    _write(paths["qa"], _qa_document(TASK_ID))
    references = [_relative(root, paths[key]) for key in ("ticket", "context", "dev", "qa")]
    _write(paths["completion"], _completion(TASK_ID, references))
    return paths


def _make_fanout(
    root: Path,
    *,
    workers: list[str] | None = None,
    optional_parent: bool = False,
) -> tuple[dict[str, Path], dict[str, dict[str, Path]]]:
    workers = workers or list(WORKERS)
    parents = _parent_paths(root)
    lanes: dict[str, dict[str, Path]] = {}
    loaded = []
    references = [_relative(root, parents["dev"])]
    for index, worker in enumerate(workers):
        identity = f"{TASK_ID}-{worker}"
        paths = _lane_paths(root, worker)
        lanes[worker] = paths
        dev = _dev_document(
            identity,
            modified=[f"scripts/lane-{index}.py"],
            created=[f"tests/lane-{index}.py"],
        )
        _write(paths["ticket"], _ticket(identity))
        _write(paths["context"], {"request_id": identity, "task_id": identity})
        _write(paths["dev"], dev)
        _write(paths["qa"], _qa_document(identity))
        loaded.append((worker, dev))
        references.extend(
            _relative(root, paths[key]) for key in ("ticket", "context", "dev", "qa")
        )
    aggregate = RESOLVER._load_aggregate_module()._build_aggregate(loaded, TASK_ID)
    _write(parents["dev"], aggregate)
    _write(parents["completion"], _completion(TASK_ID, references))
    if optional_parent:
        _write(parents["ticket"], _ticket(TASK_ID))
        _write(parents["context"], {"request_id": TASK_ID, "task_id": TASK_ID})
        _write(parents["qa"], _qa_document(TASK_ID))
    return parents, lanes


def _snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _error_codes(result: dict) -> set[str]:
    return {error["code"] for error in result["errors"]}


def _run_cli(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(RESOLVER_PATH),
            "--task-id",
            TASK_ID,
            "--project-dir",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_singular_chain_passes_with_stable_consumer_fields(tmp_path: Path) -> None:
    parents = _make_singular(tmp_path)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "pass"
    assert result["mode"] == "singular"
    assert result["canonical_dev_report"] == _relative(tmp_path, parents["dev"])
    assert result["completion"] == _relative(tmp_path, parents["completion"])
    assert result["lanes"] == []
    assert result["report_paths"] == [
        _relative(tmp_path, parents["dev"]),
        _relative(tmp_path, parents["qa"]),
    ]
    assert result["optional_parent_artifacts"] == {}


def test_markdown_identity_accepts_generated_bullet_style(tmp_path: Path) -> None:
    parents = _make_singular(tmp_path)
    _write(parents["ticket"], f"# Ticket\n\n- **REQUEST-ID:** `{TASK_ID}`\n")
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "pass"


def test_fanout_without_parent_optional_artifacts_is_read_only_and_stable(
    tmp_path: Path,
) -> None:
    parents, lanes = _make_fanout(tmp_path)
    before = _snapshot(tmp_path)
    first = _run_cli(tmp_path)
    middle = _snapshot(tmp_path)
    second = _run_cli(tmp_path)
    after = _snapshot(tmp_path)
    assert first.returncode == second.returncode == 0
    assert first.stderr == second.stderr == ""
    assert first.stdout == second.stdout
    result = json.loads(first.stdout)
    assert result["status"] == "pass"
    assert result["mode"] == "fanout"
    assert result["parallel_workers"] == WORKERS
    assert result["report_paths"] == [
        _relative(tmp_path, parents["dev"]),
        *[
            _relative(tmp_path, lanes[worker][kind])
            for worker in WORKERS
            for kind in ("dev", "qa")
        ],
    ]
    assert all(
        not item["present"] for item in result["optional_parent_artifacts"].values()
    )
    assert before == middle == after
    assert not parents["ticket"].exists()
    assert not parents["context"].exists()
    assert not parents["qa"].exists()


def test_missing_canonical_is_aggregated_before_read_only_resolution(
    tmp_path: Path,
) -> None:
    parents = _parent_paths(tmp_path)
    references = [_relative(tmp_path, parents["dev"])]
    for index, worker in enumerate(WORKERS):
        identity = f"{TASK_ID}-{worker}"
        paths = _lane_paths(tmp_path, worker)
        _write(paths["ticket"], _ticket(identity))
        _write(paths["context"], {"request_id": identity, "task_id": identity})
        _write(
            paths["dev"],
            _dev_document(identity, modified=[f"scripts/lane-{index}.py"]),
        )
        _write(paths["qa"], _qa_document(identity))
        references.extend(
            _relative(tmp_path, paths[key])
            for key in ("ticket", "context", "dev", "qa")
        )
    _write(parents["completion"], _completion(TASK_ID, references))
    assert not parents["dev"].exists()

    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    aggregate = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "aggregate-dev-report.py"),
            "--task-id",
            TASK_ID,
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert aggregate.returncode == 0, aggregate.stderr
    assert json.loads(aggregate.stdout)["action"] == "aggregated"
    assert parents["dev"].is_file()

    resolved = _run_cli(tmp_path)
    assert resolved.returncode == 0, resolved.stderr
    result = json.loads(resolved.stdout)
    assert result["status"] == "pass"
    assert result["mode"] == "fanout"
    assert [lane["worker"] for lane in result["lanes"]] == WORKERS


def test_fanout_accepts_valid_optional_parent_artifacts(tmp_path: Path) -> None:
    parents, _ = _make_fanout(tmp_path, optional_parent=True)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "pass"
    assert all(
        item["present"] for item in result["optional_parent_artifacts"].values()
    )
    assert result["report_paths"][-1] == _relative(tmp_path, parents["qa"])


def test_current_three_lane_shape_with_r01_identity_and_full_index_passes(
    tmp_path: Path,
) -> None:
    workers = ["r01", "r02", "r03"]
    parents, lanes = _make_fanout(tmp_path, workers=workers)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "pass"
    assert result["parallel_workers"] == workers
    r01 = result["lanes"][0]
    assert r01["task_id"] == f"{TASK_ID}-r01"
    completion = parents["completion"].read_text(encoding="utf-8")
    for worker in workers:
        for path in lanes[worker].values():
            assert _relative(tmp_path, path) in completion


def test_missing_lane_context_fails_closed(tmp_path: Path) -> None:
    _, lanes = _make_fanout(tmp_path)
    lanes[WORKERS[0]]["context"].unlink()
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "fail"
    assert "MISSING_ARTIFACT" in _error_codes(result)


def test_lane_identity_mismatch_fails_closed(tmp_path: Path) -> None:
    _, lanes = _make_fanout(tmp_path)
    _write(
        lanes[WORKERS[0]]["context"],
        {"request_id": TASK_ID, "task_id": TASK_ID},
    )
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert "IDENTITY_MISMATCH" in _error_codes(result)


def test_lane_qa_must_pass(tmp_path: Path) -> None:
    _, lanes = _make_fanout(tmp_path)
    identity = f"{TASK_ID}-{WORKERS[0]}"
    _write(lanes[WORKERS[0]]["qa"], _qa_document(identity, "fail"))
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert "INVALID_QA_STATUS" in _error_codes(result)


def test_completion_must_index_every_lane_artifact(tmp_path: Path) -> None:
    parents, lanes = _make_fanout(tmp_path)
    missing = _relative(tmp_path, lanes[WORKERS[1]]["qa"])
    text = parents["completion"].read_text(encoding="utf-8").replace(missing, "")
    _write(parents["completion"], text)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert "MISSING_COMPLETION_REFERENCE" in _error_codes(result)


def test_changed_shard_makes_canonical_stale_without_rewriting_it(
    tmp_path: Path,
) -> None:
    parents, lanes = _make_fanout(tmp_path)
    canonical_before = parents["dev"].read_bytes()
    identity = f"{TASK_ID}-{WORKERS[0]}"
    changed = _dev_document(identity, modified=["scripts/changed.py"])
    _write(lanes[WORKERS[0]]["dev"], changed)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "fail"
    assert {
        "STALE_SHARD_PROVENANCE",
        "STALE_FILE_UNION",
        "STALE_CANONICAL",
    }.issubset(_error_codes(result))
    assert parents["dev"].read_bytes() == canonical_before


def test_extra_shard_is_an_ambiguous_lane_set(tmp_path: Path) -> None:
    _make_fanout(tmp_path)
    extra = _lane_paths(tmp_path, "lane-c")["dev"]
    _write(extra, _dev_document(f"{TASK_ID}-lane-c"))
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert "LANE_SET_MISMATCH" in _error_codes(result)


def test_malformed_json_fails_with_stable_error(tmp_path: Path) -> None:
    _, lanes = _make_fanout(tmp_path)
    _write(lanes[WORKERS[0]]["context"], "{not json\n")
    first = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    second = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert first == second
    assert "MALFORMED_JSON" in _error_codes(first)


def test_singular_with_worker_shard_is_ambiguous(tmp_path: Path) -> None:
    _make_singular(tmp_path)
    lane = _lane_paths(tmp_path, "lane-a")["dev"]
    _write(lane, _dev_document(f"{TASK_ID}-lane-a"))
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert "AMBIGUOUS_SINGULAR_CHAIN" in _error_codes(result)


def test_invalid_optional_parent_artifact_is_not_ignored(tmp_path: Path) -> None:
    parents, _ = _make_fanout(tmp_path)
    _write(parents["qa"], _qa_document("wrong-parent"))
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert "IDENTITY_MISMATCH" in _error_codes(result)


def test_cli_validation_failure_is_json_and_exit_two(tmp_path: Path) -> None:
    _make_fanout(tmp_path)
    (_parent_paths(tmp_path)["completion"]).unlink()
    first = _run_cli(tmp_path)
    second = _run_cli(tmp_path)
    assert first.returncode == second.returncode == 2
    assert first.stderr == second.stderr == ""
    assert first.stdout == second.stdout
    assert json.loads(first.stdout)["status"] == "fail"


def test_invalid_task_id_is_json_and_exit_two(tmp_path: Path) -> None:
    process = subprocess.run(
        [
            sys.executable,
            str(RESOLVER_PATH),
            "--task-id",
            "../escape",
            "--project-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 2
    assert process.stderr == ""
    assert "INVALID_TASK_ID" in _error_codes(json.loads(process.stdout))
