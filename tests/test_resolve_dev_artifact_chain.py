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
        "STALE_FILE_UNION",
        "STALE_CANONICAL",
    }.issubset(_error_codes(result))
    assert parents["dev"].read_bytes() == canonical_before


def test_owned_files_only_change_stays_pass_without_provenance(
    tmp_path: Path,
) -> None:
    # Restored post-rollback narrower freshness (consumer side): a shard change
    # confined to the non-projected owned_files field leaves the canonical fresh
    # and file unions exact, so the chain stays pass with no STALE_SHARD_PROVENANCE.
    parents, lanes = _make_fanout(tmp_path)
    dev_path = lanes[WORKERS[0]]["dev"]
    shard = json.loads(dev_path.read_text(encoding="utf-8"))
    shard["owned_files"] = {"alpha.py": "after"}
    _write(dev_path, shard)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "pass"
    assert result["checks"]["canonical_fresh"] is True
    assert result["checks"]["file_unions_exact"] is True
    assert "STALE_SHARD_PROVENANCE" not in _error_codes(result)


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


# ---------------------------------------------------------------------------
# Explicit artifact-chain shape declaration (task 20260803-150741).
# ---------------------------------------------------------------------------

DECLARATION_KEY = RESOLVER.DECLARATION_KEY


def _make_parallel_dev(
    root: Path,
    *,
    workers: list[str] | None = None,
    declaration: dict | object = ...,
) -> dict[str, Path]:
    """Canonical + completion + per-worker dev-reports; no lane artifacts."""
    workers = list(WORKERS) if workers is None else list(workers)
    parents = _parent_paths(root)
    loaded = []
    references = [_relative(root, parents["dev"])]
    for index, worker in enumerate(workers):
        # Per-worker shards legitimately carry the PARENT task-id.
        document = _dev_document(TASK_ID, modified=[f"scripts/w-{index}.py"])
        path = _lane_paths(root, worker)["dev"]
        _write(path, document)
        loaded.append((worker, document))
        references.append(_relative(root, path))
    if declaration is ...:
        declaration = {
            "version": 1,
            "shape": RESOLVER.SHAPE_PARALLEL_DEV,
            "declared_lanes": [],
        }
    aggregate = RESOLVER._load_aggregate_module()._build_aggregate(
        loaded, TASK_ID, declaration
    )
    _write(parents["dev"], aggregate)
    _write(parents["completion"], _completion(TASK_ID, references))
    return parents


def test_parallel_dev_shape_needs_no_lane_artifacts(tmp_path: Path) -> None:
    _make_parallel_dev(tmp_path)
    before = _snapshot(tmp_path)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["mode"] == RESOLVER.MODE_PARALLEL_DEV
    assert result["status"] == "pass", result["errors"]
    assert result["errors"] == []
    assert result["lanes"] == []
    assert result["qa_inputs"] == []
    assert _snapshot(tmp_path) == before


def test_parallel_dev_whitelist_keeps_every_worker_report(tmp_path: Path) -> None:
    parents = _make_parallel_dev(tmp_path)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    expected = {
        _relative(tmp_path, parents["dev"]),
        _relative(tmp_path, parents["completion"]),
        *(_relative(tmp_path, _lane_paths(tmp_path, worker)["dev"]) for worker in WORKERS),
    }
    assert set(result["commit_whitelist_artifacts"]) == expected
    for relative in result["commit_whitelist_artifacts"]:
        assert (tmp_path / relative).is_file()


def test_parallel_dev_mode_is_independent_of_parallel_workers(tmp_path: Path) -> None:
    parents = _make_parallel_dev(tmp_path)
    canonical = json.loads(parents["dev"].read_text())
    canonical["parallel_workers"] = ["other-x", "other-y"]
    _write(parents["dev"], canonical)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["mode"] == RESOLVER.MODE_PARALLEL_DEV
    assert "LANE_SET_MISMATCH" in _error_codes(result)


def test_absent_declaration_is_never_lax(tmp_path: Path) -> None:
    _make_fanout(tmp_path)
    parents = _parent_paths(tmp_path)
    canonical = json.loads(parents["dev"].read_text())
    assert DECLARATION_KEY not in canonical
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["mode"] == "fanout"


def test_malformed_declaration_fails_closed(tmp_path: Path) -> None:
    parents = _parent_paths(tmp_path)
    cases = [
        ({"version": 1, "shape": "", "declared_lanes": []}, "INVALID_DECLARATION_SHAPE"),
        ({"version": 1, "shape": None, "declared_lanes": []}, "INVALID_DECLARATION_SHAPE"),
        ({"version": 1, "shape": "lax", "declared_lanes": []}, "INVALID_DECLARATION_SHAPE"),
        ({"shape": "parallel_dev", "declared_lanes": []}, "INVALID_DECLARATION_VERSION"),
        ({"version": 99, "shape": "parallel_dev", "declared_lanes": []},
         "INVALID_DECLARATION_VERSION"),
        ("parallel_dev", "INVALID_CHAIN_DECLARATION"),
        ({"version": 1, "shape": "requirement_fanout"}, "INVALID_DECLARED_LANES"),
        ({"version": 1, "shape": "requirement_fanout", "declared_lanes": None},
         "INVALID_DECLARED_LANES"),
        ({"version": 1, "shape": "requirement_fanout", "declared_lanes": []},
         "INVALID_DECLARED_LANES"),
        ({"version": 1, "shape": "requirement_fanout", "declared_lanes": ["a"]},
         "INVALID_DECLARED_LANES"),
        ({"version": 1, "shape": "requirement_fanout", "declared_lanes": ["a", "a"]},
         "INVALID_DECLARED_LANES"),
        ({"version": 1, "shape": "requirement_fanout", "declared_lanes": ["a", "-bad"]},
         "INVALID_DECLARED_LANES"),
        ({"version": 1, "shape": "parallel_dev", "declared_lanes": ["a"]},
         "INVALID_DECLARED_LANES"),
    ]
    for declaration, expected in cases:
        _make_parallel_dev(tmp_path, declaration=declaration)
        canonical = json.loads(parents["dev"].read_text())
        canonical[DECLARATION_KEY] = declaration
        _write(parents["dev"], canonical)
        result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
        assert expected in _error_codes(result), (declaration, result["errors"])
        assert result["status"] == "fail"
        assert result["mode"] != RESOLVER.MODE_PARALLEL_DEV
        assert result["lanes"] == []


def test_declared_fanout_keeps_an_unrun_lane_visible(tmp_path: Path) -> None:
    _make_fanout(tmp_path)
    parents = _parent_paths(tmp_path)
    canonical = json.loads(parents["dev"].read_text())
    canonical[DECLARATION_KEY] = {
        "version": 1,
        "shape": RESOLVER.SHAPE_REQUIREMENT_FANOUT,
        "declared_lanes": [*WORKERS, "lane-c"],
    }
    _write(parents["dev"], canonical)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "fail"
    assert "lane-c" in {lane["worker"] for lane in result["lanes"]}
    missing = {
        error["path"] for error in result["errors"]
        if error["code"] == "MISSING_ARTIFACT" and "lane-c" in error["path"]
    }
    assert len(missing) == 4, missing


def test_declared_fanout_reports_an_orphan_lane_shard(tmp_path: Path) -> None:
    _make_fanout(tmp_path)
    parents = _parent_paths(tmp_path)
    orphan = _lane_paths(tmp_path, "lane-c")["dev"]
    _write(orphan, _dev_document(f"{TASK_ID}-lane-c"))
    canonical = json.loads(parents["dev"].read_text())
    canonical["parallel_workers"] = [*WORKERS, "lane-c"]
    canonical[DECLARATION_KEY] = {
        "version": 1,
        "shape": RESOLVER.SHAPE_REQUIREMENT_FANOUT,
        "declared_lanes": list(WORKERS),
    }
    _write(parents["dev"], canonical)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    orphans = [e for e in result["errors"] if e["code"] == "ORPHAN_LANE_SHARD"]
    assert len(orphans) == 1, result["errors"]
    assert "'lane-c'" in orphans[0]["detail"]


def test_lane_artifacts_contradict_a_parallel_dev_declaration(tmp_path: Path) -> None:
    _make_parallel_dev(tmp_path)
    _write(_lane_paths(tmp_path, WORKERS[0])["ticket"], _ticket(f"{TASK_ID}-{WORKERS[0]}"))
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["mode"] == RESOLVER.MODE_PARALLEL_DEV
    assert "UNDECLARED_LANE_ARTIFACT" in _error_codes(result)
    assert "LANE_SET_MISMATCH" not in _error_codes(result)


def test_declaration_enters_the_canonical_projection(tmp_path: Path) -> None:
    aggregate = RESOLVER._load_aggregate_module()
    base = {"request_id": TASK_ID, "task_id": TASK_ID, "parallel_workers": list(WORKERS)}
    left = dict(base, **{DECLARATION_KEY: {
        "version": 1, "shape": "parallel_dev", "declared_lanes": []}})
    right = dict(base, **{DECLARATION_KEY: {
        "version": 1, "shape": "requirement_fanout", "declared_lanes": list(WORKERS)}})
    assert aggregate._canonical_projection(left) != aggregate._canonical_projection(right)
    assert aggregate._canonical_projection(left) == aggregate._canonical_projection(dict(left))


def test_fanout_guard_uses_the_declared_roster_not_parallel_workers(
    tmp_path: Path,
) -> None:
    """A declared lane that produced a ticket but no shard is NOT undeclared.

    Discriminating geometry: `parallel_workers` is pinned to the shard scan, so
    lane `lane-c` is absent from it while being a legitimate declared lane.
    Invoking the guard with `parallel_workers` would raise a spurious
    UNDECLARED_LANE_ARTIFACT on lane-c's ticket; invoking it with the declared
    roster does not.
    """
    _make_fanout(tmp_path)
    parents = _parent_paths(tmp_path)
    _write(_lane_paths(tmp_path, "lane-c")["ticket"], _ticket(f"{TASK_ID}-lane-c"))
    canonical = json.loads(parents["dev"].read_text())
    canonical[DECLARATION_KEY] = {
        "version": 1,
        "shape": RESOLVER.SHAPE_REQUIREMENT_FANOUT,
        "declared_lanes": [*WORKERS, "lane-c"],
    }
    _write(parents["dev"], canonical)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert canonical["parallel_workers"] == list(WORKERS)
    assert "UNDECLARED_LANE_ARTIFACT" not in _error_codes(result)
    # lane-c is still fully enforced: its three absent artifacts are demanded.
    missing = {
        error["path"] for error in result["errors"]
        if error["code"] == "MISSING_ARTIFACT" and "lane-c" in error["path"]
    }
    assert len(missing) == 3, missing


def test_parallel_dev_without_two_workers_is_not_a_free_pass(tmp_path: Path) -> None:
    _make_parallel_dev(tmp_path, workers=[])
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["mode"] == RESOLVER.MODE_PARALLEL_DEV
    assert result["status"] == "fail"
    assert "AMBIGUOUS_WORKER_SET" in _error_codes(result)


# ---------------------------------------------------------------------------
# Per-worker shard identity is an exact two-value membership test, never a
# substring of the parent's timestamp (QA finding F1, task 20260803-150741).
# ---------------------------------------------------------------------------


def _make_parallel_dev_identities(root: Path, identities: dict[str, str]) -> dict[str, Path]:
    """A parallel-dev chain whose shards carry chosen request_id/task_id values.

    The canonical is built by the REAL producer over those shard documents, so a
    foreign identity cannot be dismissed as a hand-written canonical artefact.
    """
    parents = _parent_paths(root)
    loaded = []
    references = [_relative(root, parents["dev"])]
    for index, worker in enumerate(WORKERS):
        document = _dev_document(identities[worker], modified=[f"scripts/w-{index}.py"])
        path = _lane_paths(root, worker)["dev"]
        _write(path, document)
        loaded.append((worker, document))
        references.append(_relative(root, path))
    declaration = {
        "version": 1,
        "shape": RESOLVER.SHAPE_PARALLEL_DEV,
        "declared_lanes": [],
    }
    aggregate = RESOLVER._load_aggregate_module()._build_aggregate(
        loaded, TASK_ID, declaration
    )
    _write(parents["dev"], aggregate)
    _write(parents["completion"], _completion(TASK_ID, references))
    return parents


def _assert_foreign_shard_identity_is_refused(root: Path, foreign: str) -> None:
    _make_parallel_dev_identities(root, {"lane-a": TASK_ID, "lane-b": foreign})
    result = RESOLVER.resolve_chain(root, TASK_ID)
    assert result["mode"] == RESOLVER.MODE_PARALLEL_DEV
    assert result["status"] == "fail", result
    assert "IDENTITY_MISMATCH" in _error_codes(result)
    offending = {
        error["path"] for error in result["errors"]
        if error["code"] == "IDENTITY_MISMATCH"
    }
    assert offending == {f"docs/dev/dev-report-{TASK_ID}-lane-b.json"}, offending


def test_parallel_dev_refuses_a_shard_copied_under_another_workers_filename(
    tmp_path: Path,
) -> None:
    _assert_foreign_shard_identity_is_refused(tmp_path, f"{TASK_ID}-lane-a")


def test_parallel_dev_refuses_a_shard_with_a_foreign_cycle_prefix(
    tmp_path: Path,
) -> None:
    _assert_foreign_shard_identity_is_refused(tmp_path, f"someothercycle-{TASK_ID}-gamma")


def test_parallel_dev_refuses_a_shard_naming_a_worker_that_does_not_exist(
    tmp_path: Path,
) -> None:
    _assert_foreign_shard_identity_is_refused(tmp_path, f"{TASK_ID}-nonexistent-worker")


def test_parallel_dev_refuses_a_timestamp_wrapped_in_arbitrary_characters(
    tmp_path: Path,
) -> None:
    _assert_foreign_shard_identity_is_refused(tmp_path, f"zzz{TASK_ID}zzz")


def test_parallel_dev_refuses_a_mixed_identity_pair(tmp_path: Path) -> None:
    """request_id and task_id must carry the SAME one of the two legitimate forms."""
    for index, (request_id, task_id) in enumerate(
        [(TASK_ID, f"{TASK_ID}-lane-b"), (f"{TASK_ID}-lane-b", TASK_ID)]
    ):
        root = tmp_path / f"mixed{index}"
        _make_parallel_dev_identities(root, {"lane-a": TASK_ID, "lane-b": TASK_ID})
        shard_path = _lane_paths(root, "lane-b")["dev"]
        shard = json.loads(shard_path.read_text())
        shard["request_id"] = request_id
        shard["task_id"] = task_id
        _write(shard_path, shard)
        result = RESOLVER.resolve_chain(root, TASK_ID)
        assert result["status"] == "fail", (request_id, task_id, result)
        assert "IDENTITY_MISMATCH" in _error_codes(result)


def test_parallel_dev_names_a_non_string_identity_instead_of_crashing(
    tmp_path: Path,
) -> None:
    """A list/object/null identity must produce a named error, never a traceback."""
    for index, foreign in enumerate([[], {}, None]):
        root = tmp_path / f"nonstring{index}"
        _make_parallel_dev_identities(root, {"lane-a": TASK_ID, "lane-b": TASK_ID})
        shard_path = _lane_paths(root, "lane-b")["dev"]
        shard = json.loads(shard_path.read_text())
        shard["task_id"] = foreign
        _write(shard_path, shard)
        result = RESOLVER.resolve_chain(root, TASK_ID)
        assert result["status"] == "fail", (foreign, result)
        assert "IDENTITY_MISMATCH" in _error_codes(result)


def test_parallel_dev_accepts_exactly_the_two_legitimate_identity_forms(
    tmp_path: Path,
) -> None:
    bare = tmp_path / "bare"
    _make_parallel_dev_identities(bare, {worker: TASK_ID for worker in WORKERS})
    result = RESOLVER.resolve_chain(bare, TASK_ID)
    assert result["status"] == "pass", result["errors"]
    lane = tmp_path / "lane"
    _make_parallel_dev_identities(
        lane, {worker: f"{TASK_ID}-{worker}" for worker in WORKERS}
    )
    result = RESOLVER.resolve_chain(lane, TASK_ID)
    assert result["status"] == "pass", result["errors"]
