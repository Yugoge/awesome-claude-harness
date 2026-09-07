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


def _materialise(root: Path, *declared: str) -> None:
    """Create every path a fixture's dev-report declares.

    The resolver requires a declared file union to exist on disk, so a fixture
    that declares paths must produce them.  The correct remedy is to make the
    fixture honest, never to weaken the check.
    """
    for relative in declared:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()


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
    _materialise(root, "scripts/one.py")
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
        _materialise(root, f"scripts/lane-{index}.py", f"tests/lane-{index}.py")
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
        _materialise(tmp_path, f"scripts/lane-{index}.py")
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


# ---------------------------------------------------------------------------
# Shard scoping across the three task-id shapes.  Shards belong to the FULL
# task-id; the bare YYYYMMDD-HHMMSS timestamp is a truncation of a prefixed or
# suffixed id and must not be used as the scan key for it.
# ---------------------------------------------------------------------------

BARE_ID = "20260727-080801"
SUFFIXED_ID = "20260727-080801-11"
PREFIXED_ID = TASK_ID


def _make_singular_for(root: Path, identity: str) -> dict[str, Path]:
    dev_dir = _dev_dir(root)
    paths = {
        "ticket": dev_dir / f"ticket-{identity}.md",
        "context": dev_dir / f"context-{identity}.json",
        "dev": dev_dir / f"dev-report-{identity}.json",
        "qa": dev_dir / f"qa-report-{identity}.json",
        "completion": dev_dir / f"completion-{identity}.md",
    }
    _write(paths["ticket"], _ticket(identity))
    _write(paths["context"], {"request_id": identity, "task_id": identity})
    _materialise(root, "scripts/one.py")
    _write(paths["dev"], _dev_document(identity, modified=["scripts/one.py"]))
    _write(paths["qa"], _qa_document(identity))
    references = [
        _relative(root, paths[key]) for key in ("ticket", "context", "dev", "qa")
    ]
    _write(paths["completion"], _completion(identity, references))
    return paths


def _ambiguity_detail(result: dict) -> str:
    return next(
        error["detail"]
        for error in result["errors"]
        if error["code"] == "AMBIGUOUS_SINGULAR_CHAIN"
    )


def test_suffixed_task_id_canonical_is_not_a_shard_of_itself(tmp_path: Path) -> None:
    # A pristine suffixed-id chain, alone in docs/dev, must resolve.  Matching
    # against the truncated timestamp classifies dev-report-<ts>-11.json as
    # worker '11' of itself.
    _make_singular_for(tmp_path, SUFFIXED_ID)
    result = RESOLVER.resolve_chain(tmp_path, SUFFIXED_ID)
    assert result["status"] == "pass", result["errors"]
    assert "AMBIGUOUS_SINGULAR_CHAIN" not in _error_codes(result)


def test_suffixed_task_id_ignores_siblings_sharing_the_bare_timestamp(
    tmp_path: Path,
) -> None:
    _make_singular_for(tmp_path, SUFFIXED_ID)
    sibling = _dev_dir(tmp_path) / f"dev-report-{BARE_ID}-12.json"
    _write(sibling, _dev_document(f"{BARE_ID}-12"))
    result = RESOLVER.resolve_chain(tmp_path, SUFFIXED_ID)
    assert result["status"] == "pass", result["errors"]
    assert sibling.is_file()


def test_suffixed_task_id_still_detects_its_own_undeclared_sub_shards(
    tmp_path: Path,
) -> None:
    # The check must keep firing for a real undeclared fan-out parent, and must
    # name the sub-worker rather than a label carved out of the timestamp.
    _make_singular_for(tmp_path, SUFFIXED_ID)
    _write(
        _dev_dir(tmp_path) / f"dev-report-{SUFFIXED_ID}-S1.json",
        _dev_document(f"{SUFFIXED_ID}-S1"),
    )
    result = RESOLVER.resolve_chain(tmp_path, SUFFIXED_ID)
    assert "AMBIGUOUS_SINGULAR_CHAIN" in _error_codes(result)
    assert "'S1'" in _ambiguity_detail(result)


def test_prefixed_task_id_ignores_bare_timestamp_sibling_shards(
    tmp_path: Path,
) -> None:
    _make_singular_for(tmp_path, PREFIXED_ID)
    bare_sibling = _dev_dir(tmp_path) / "dev-report-20260724-120000-lane-x.json"
    _write(bare_sibling, _dev_document("20260724-120000-lane-x"))
    result = RESOLVER.resolve_chain(tmp_path, PREFIXED_ID)
    assert result["status"] == "pass", result["errors"]
    assert bare_sibling.is_file()


def test_bare_task_id_chain_resolves_and_keeps_collecting_its_shards(
    tmp_path: Path,
) -> None:
    # Control for the third shape: a bare id is its own scan key, so nothing is
    # truncated and its shard discovery is unchanged.
    _make_singular_for(tmp_path, BARE_ID)
    assert RESOLVER.resolve_chain(tmp_path, BARE_ID)["status"] == "pass"
    _write(
        _dev_dir(tmp_path) / f"dev-report-{BARE_ID}-11.json",
        _dev_document(f"{BARE_ID}-11"),
    )
    result = RESOLVER.resolve_chain(tmp_path, BARE_ID)
    assert "AMBIGUOUS_SINGULAR_CHAIN" in _error_codes(result)
    assert "'11'" in _ambiguity_detail(result)


# ---------------------------------------------------------------------------
# The checks object must never claim a check it did not perform.  The two
# relational checks are computed only on the fan-out branch; on the singular
# branch they have no analogue and say so.  The declared-path check IS
# meaningful for a single lane and is enforced on both branches.
# ---------------------------------------------------------------------------


def _absent_path_details(result: dict) -> list[str]:
    return [
        error["detail"]
        for error in result["errors"]
        if error["code"] == "ABSENT_DECLARED_PATH"
    ]


def test_singular_relational_checks_are_not_applicable_with_a_reason(
    tmp_path: Path,
) -> None:
    # Neither True nor False: a singular chain has no second artifact to compare
    # against, so reporting either boolean would assert a comparison that never ran.
    _make_singular(tmp_path)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "pass", result["errors"]
    for check in ("canonical_fresh", "file_unions_exact"):
        value = result["checks"][check]
        assert value is not True and value is not False
        assert value == RESOLVER.NOT_APPLICABLE
        reason = result["checks_not_applicable"][check]
        assert "two or more independent shard artifacts" in reason
        assert "no singular analogue" in reason


def test_base_result_initialises_every_check_fail_closed() -> None:
    checks = RESOLVER._base_result("t", "c", "d")["checks"]
    assert checks["canonical_fresh"] is False
    assert checks["file_unions_exact"] is False
    assert checks["declared_paths_exist"] is False


def test_singular_absent_declared_path_fails_under_its_own_error_code(
    tmp_path: Path,
) -> None:
    parents = _make_singular(tmp_path)
    _write(
        parents["dev"],
        _dev_document(TASK_ID, modified=["scripts/one.py"], created=["scripts/gone.py"]),
    )
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "fail"
    assert result["checks"]["declared_paths_exist"] is False
    codes = _error_codes(result)
    assert "ABSENT_DECLARED_PATH" in codes
    # A different failure from staleness, so it must not borrow either code.
    assert "STALE_FILE_UNION" not in codes
    assert "STALE_CANONICAL" not in codes
    assert any("scripts/gone.py" in detail for detail in _absent_path_details(result))
    assert _run_cli(tmp_path).returncode == 2


def test_fanout_absent_declared_path_fires_the_same_error_code(tmp_path: Path) -> None:
    # Models the real corpus case: the canonical is fresh and exactly matches its
    # shards, but a declared file has since left the tree.  Only the new check
    # may fire -- the relational checks stay computed and True.
    _make_fanout(tmp_path)
    (tmp_path / "tests" / "lane-1.py").unlink()
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["mode"] == "fanout"
    assert result["status"] == "fail"
    assert result["checks"]["declared_paths_exist"] is False
    assert result["checks"]["canonical_fresh"] is True
    assert result["checks"]["file_unions_exact"] is True
    codes = _error_codes(result)
    assert "ABSENT_DECLARED_PATH" in codes
    assert not codes & {"STALE_FILE_UNION", "STALE_CANONICAL"}
    assert any("tests/lane-1.py" in detail for detail in _absent_path_details(result))


def test_every_absent_path_is_reported_individually(tmp_path: Path) -> None:
    parents = _make_singular(tmp_path)
    _write(
        parents["dev"],
        _dev_document(
            TASK_ID,
            modified=["scripts/one.py", "scripts/missing-a.py"],
            created=["scripts/missing-b.py"],
        ),
    )
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    details = _absent_path_details(result)
    assert len(details) == 2
    assert any("scripts/missing-a.py" in detail for detail in details)
    assert any("scripts/missing-b.py" in detail for detail in details)


def test_declared_directory_and_symlink_count_as_present(tmp_path: Path) -> None:
    # Weakest defensible existence semantics: the claim under test is "a path is
    # there", not "a regular file is there".  A broken symlink is still an entry.
    parents = _make_singular(tmp_path)
    (tmp_path / "scripts" / "a-directory").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "dangling").symlink_to(tmp_path / "scripts" / "nowhere.py")
    _write(
        parents["dev"],
        _dev_document(
            TASK_ID,
            modified=["scripts/one.py", "scripts/a-directory"],
            created=["scripts/dangling"],
        ),
    )
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "pass", result["errors"]
    assert result["checks"]["declared_paths_exist"] is True


def test_absent_and_explicitly_empty_parallel_workers_are_distinguishable(
    tmp_path: Path,
) -> None:
    parents = _make_singular(tmp_path)
    absent = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    canonical = json.loads(parents["dev"].read_text(encoding="utf-8"))
    assert "parallel_workers" not in canonical
    canonical["parallel_workers"] = []
    _write(parents["dev"], canonical)
    empty = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert absent != empty
    assert absent["parallel_workers_declaration"] == "absent"
    assert empty["parallel_workers_declaration"] == "empty"
    # Both remain singular and passing; the distinction is diagnostic, not a
    # new failure for the ordinary case.
    assert absent["status"] == empty["status"] == "pass"
    assert absent["mode"] == empty["mode"] == "singular"


def test_declared_parallel_workers_are_reported_as_declared(tmp_path: Path) -> None:
    _make_fanout(tmp_path)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["parallel_workers_declaration"] == "declared"


def test_lost_worker_declaration_fires_alongside_ambiguous_singular_chain(
    tmp_path: Path,
) -> None:
    # An aggregate stripped of parallel_workers is structurally identical to a
    # singular chain; only surviving shard evidence reveals it.
    _make_singular(tmp_path)
    _write(
        _lane_paths(tmp_path, "lane-a")["dev"],
        _dev_document(f"{TASK_ID}-lane-a"),
    )
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    codes = _error_codes(result)
    assert "LOST_WORKER_DECLARATION" in codes
    # Additive only: the pre-existing error still fires unchanged beside it.
    assert "AMBIGUOUS_SINGULAR_CHAIN" in codes
    assert result["parallel_workers_declaration"] == "absent"


def test_explicitly_empty_worker_list_with_shards_is_only_ambiguous(
    tmp_path: Path,
) -> None:
    # The empty key is a deliberate declaration, not a loss, so the new error
    # must not fire -- that is the whole point of distinguishing the two.
    parents = _make_singular(tmp_path)
    canonical = json.loads(parents["dev"].read_text(encoding="utf-8"))
    canonical["parallel_workers"] = []
    _write(parents["dev"], canonical)
    _write(
        _lane_paths(tmp_path, "lane-a")["dev"],
        _dev_document(f"{TASK_ID}-lane-a"),
    )
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    codes = _error_codes(result)
    assert "AMBIGUOUS_SINGULAR_CHAIN" in codes
    assert "LOST_WORKER_DECLARATION" not in codes


def test_malformed_canonical_dev_block_does_not_raise_in_the_new_check(
    tmp_path: Path,
) -> None:
    parents = _make_singular(tmp_path)
    canonical = json.loads(parents["dev"].read_text(encoding="utf-8"))
    canonical["dev"] = "not-an-object"
    _write(parents["dev"], canonical)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert "INVALID_DEV_STATUS" in _error_codes(result)
    assert "ABSENT_DECLARED_PATH" not in _error_codes(result)


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
# Lane attribution for non-canonical artifacts.  Which lane an artifact belongs
# to is settled by the identity the artifact declares about itself, not by the
# label its writer happened to put in the filename.  The pairing that matters is
# the first two tests below: the check must stop flagging a declared lane's
# round-one report AND keep flagging a lane that really was never declared.
# ---------------------------------------------------------------------------

UNDECLARED_WORKER = "lane-c"


def _undeclared_lane_paths(result: dict) -> list[str]:
    return sorted(
        error["path"]
        for error in result["errors"]
        if error["code"] == "UNDECLARED_LANE_ARTIFACT"
    )


def _undeclared_lane_details(result: dict) -> list[str]:
    return sorted(
        error["detail"]
        for error in result["errors"]
        if error["code"] == "UNDECLARED_LANE_ARTIFACT"
    )


def _variant(root: Path, name: str) -> Path:
    """A non-canonical artifact whose filename suffix is not a lane name."""
    return _dev_dir(root) / name


def test_round_one_report_of_a_declared_lane_is_not_an_undeclared_lane(
    tmp_path: Path,
) -> None:
    # The regression under repair: a declared lane's earlier-round QA report
    # carries a distinguishing filename suffix while declaring, in both identity
    # fields, the lane it belongs to.  Attributing it to a worker carved out of
    # the whole suffix invents a lane that never ran.
    _make_fanout(tmp_path)
    variant = _variant(tmp_path, f"qa-report-{TASK_ID}-{WORKERS[0]}-round1.json")
    _write(variant, _qa_document(f"{TASK_ID}-{WORKERS[0]}", status="warning"))
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert _undeclared_lane_paths(result) == []
    assert result["status"] == "pass", result["errors"]


def test_genuinely_undeclared_lane_is_still_flagged(tmp_path: Path) -> None:
    # The finding that must survive: a lane that really ran without being
    # declared, whose artifacts carry its own distinct identity.  Consulting the
    # identity fields must sharpen this detection, never suppress it.
    _make_fanout(tmp_path)
    identity = f"{TASK_ID}-{UNDECLARED_WORKER}"
    lane = _lane_paths(tmp_path, UNDECLARED_WORKER)
    _write(lane["ticket"], _ticket(identity))
    _write(lane["context"], {"request_id": identity, "task_id": identity})
    _write(lane["qa"], _qa_document(identity))
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert _undeclared_lane_paths(result) == [
        _relative(tmp_path, lane[key]) for key in ("context", "qa", "ticket")
    ]
    assert all(
        f"{UNDECLARED_WORKER!r} (from declared identity)" in detail
        for detail in _undeclared_lane_details(result)
    )
    assert result["status"] == "fail"


def test_declared_identity_outranks_a_filename_naming_a_declared_lane(
    tmp_path: Path,
) -> None:
    # A file cannot buy an exemption by being named after a lane that was
    # declared; what it says it is decides.
    _make_fanout(tmp_path)
    variant = _variant(tmp_path, f"qa-report-{TASK_ID}-{WORKERS[0]}-r2.json")
    _write(variant, _qa_document(f"{TASK_ID}-{UNDECLARED_WORKER}"))
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert _undeclared_lane_paths(result) == [_relative(tmp_path, variant)]


# --- Degenerate identities.  Every one falls back to the filename, so none of
# --- them is a way to slip past the check.

def _assert_falls_back_to_filename(root: Path, path: Path) -> None:
    result = RESOLVER.resolve_chain(root, TASK_ID)
    assert _undeclared_lane_paths(result) == [_relative(root, path)]
    assert all(
        "(from filename, no usable declared identity)" in detail
        for detail in _undeclared_lane_details(result)
    )


def test_absent_identity_keys_fall_back_to_the_filename(tmp_path: Path) -> None:
    _make_fanout(tmp_path)
    path = _variant(tmp_path, f"qa-report-{TASK_ID}-{UNDECLARED_WORKER}.json")
    _write(path, {"qa": {"status": "pass"}})
    _assert_falls_back_to_filename(tmp_path, path)


def test_blank_and_non_string_identity_values_fall_back(tmp_path: Path) -> None:
    for value in ("", "   ", 17, None, ["a"]):
        root = tmp_path / f"case-{abs(hash(repr(value)))}"
        _make_fanout(root)
        path = _variant(root, f"qa-report-{TASK_ID}-{UNDECLARED_WORKER}.json")
        _write(
            path,
            {
                "request_id": value,
                "task_id": f"{TASK_ID}-{WORKERS[0]}",
                "qa": {"status": "pass"},
            },
        )
        _assert_falls_back_to_filename(root, path)


def test_contradictory_identity_keys_fall_back(tmp_path: Path) -> None:
    _make_fanout(tmp_path)
    path = _variant(tmp_path, f"qa-report-{TASK_ID}-{UNDECLARED_WORKER}.json")
    _write(
        path,
        {
            "request_id": f"{TASK_ID}-{WORKERS[0]}",
            "task_id": f"{TASK_ID}-{WORKERS[1]}",
            "qa": {"status": "pass"},
        },
    )
    _assert_falls_back_to_filename(tmp_path, path)


def test_malformed_and_non_object_json_fall_back(tmp_path: Path) -> None:
    for body in ("{not json\n", '["lane-a"]\n', ""):
        root = tmp_path / f"body-{abs(hash(body))}"
        _make_fanout(root)
        path = _variant(root, f"qa-report-{TASK_ID}-{UNDECLARED_WORKER}.json")
        _write(path, body)
        _assert_falls_back_to_filename(root, path)


def test_markdown_without_identity_metadata_falls_back(tmp_path: Path) -> None:
    _make_fanout(tmp_path)
    path = _variant(tmp_path, f"ticket-{TASK_ID}-{UNDECLARED_WORKER}.md")
    _write(path, "# Ticket\n\nNo identity metadata here.\n")
    _assert_falls_back_to_filename(tmp_path, path)


def test_markdown_with_contradictory_identity_lines_falls_back(
    tmp_path: Path,
) -> None:
    _make_fanout(tmp_path)
    path = _variant(tmp_path, f"ticket-{TASK_ID}-{UNDECLARED_WORKER}.md")
    _write(
        path,
        f"# Ticket\n\n**TASK-ID**: `{TASK_ID}-{WORKERS[0]}`\n"
        f"**Request ID**: `{TASK_ID}-{WORKERS[1]}`\n",
    )
    _assert_falls_back_to_filename(tmp_path, path)


def test_identity_naming_another_task_cannot_vouch(tmp_path: Path) -> None:
    # Outside this task's lane namespace, so it says nothing about which lane of
    # THIS task the file belongs to.
    _make_fanout(tmp_path)
    path = _variant(tmp_path, f"qa-report-{TASK_ID}-{UNDECLARED_WORKER}.json")
    _write(path, _qa_document(f"dev-20260101-000000-{WORKERS[0]}"))
    _assert_falls_back_to_filename(tmp_path, path)


def test_identity_equal_to_the_parent_task_id_cannot_vouch(tmp_path: Path) -> None:
    # A parent-scoped identity names no worker at all.
    _make_fanout(tmp_path)
    path = _variant(tmp_path, f"qa-report-{TASK_ID}-{UNDECLARED_WORKER}.json")
    _write(path, _qa_document(TASK_ID))
    _assert_falls_back_to_filename(tmp_path, path)


def test_identity_with_an_invalid_worker_label_cannot_vouch(tmp_path: Path) -> None:
    _make_fanout(tmp_path)
    path = _variant(tmp_path, f"qa-report-{TASK_ID}-{UNDECLARED_WORKER}.json")
    _write(path, _qa_document(f"{TASK_ID}-not a worker"))
    _assert_falls_back_to_filename(tmp_path, path)


# --- Symmetry with the shard classifier: a revision label is not a lane name.

def test_revision_labelled_filename_without_identity_is_not_a_lane(
    tmp_path: Path,
) -> None:
    # The sibling shard classifier already treats draft/final/iterN as non-lane
    # labels; this path must classify the same filename the same way.
    for label in ("draft", "final", "iter2", "RETRY"):
        root = tmp_path / f"label-{label}"
        _make_fanout(root)
        _write(_variant(root, f"qa-report-{TASK_ID}-{label}.json"), {"qa": {}})
        result = RESOLVER.resolve_chain(root, TASK_ID)
        assert _undeclared_lane_paths(result) == [], label


def test_revision_labelled_filename_declaring_an_undeclared_lane_is_flagged(
    tmp_path: Path,
) -> None:
    # The filename heuristic must not become an exemption a lane can claim by
    # naming its artifacts after a revision label.
    _make_fanout(tmp_path)
    path = _variant(tmp_path, f"qa-report-{TASK_ID}-final.json")
    _write(path, _qa_document(f"{TASK_ID}-{UNDECLARED_WORKER}"))
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert _undeclared_lane_paths(result) == [_relative(tmp_path, path)]
