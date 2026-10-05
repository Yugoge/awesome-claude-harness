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


# ---------------------------------------------------------------------------
# Disclosed-exception vocabulary fixtures (ticket 20260911-011232).  Small,
# focused builders layered on top of the existing _dev_document/_qa_document
# helpers above -- neither of those two functions is modified, matching the
# ticket's Contract D constraint that validate_dev()/validate_qa() (and, by
# extension, the fixtures exercising their happy path) stay untouched.
# ---------------------------------------------------------------------------

ROUTE_SELECT_PATH = REPO_ROOT / "scripts" / "close-route-select.py"


def _run_route_select(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROUTE_SELECT_PATH),
            "--task-id",
            TASK_ID,
            "--project-dir",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _run_aggregate(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "aggregate-dev-report.py"),
            "--task-id",
            TASK_ID,
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(root),
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)},
    )


def _qa_document_with_disclosed_exception(
    identity: str,
    *,
    classification: str = "shared_working_tree_concurrency",
    evidence: list[str] | None = None,
    attestation: str | None = None,
    iteration_needed: bool = False,
    findings: list[dict] | None = None,
) -> dict:
    """A qa.status=='fail' document declaring a complete M2 disclosure block."""
    doc = _qa_document(identity, status="fail")
    doc["iteration_needed"] = iteration_needed
    doc["qa"]["disclosed_exception"] = {
        "classification": classification,
        "evidence": ["docs/dev/evidence.log:1"] if evidence is None else evidence,
        "attestation": RESOLVER.DISCLOSED_EXCEPTION_ATTESTATION if attestation is None else attestation,
    }
    if findings is not None:
        doc["qa"]["all_findings"] = findings
    return doc


def _dev_document_needs_review(
    identity: str,
    *,
    modified: list[str] | None = None,
    created: list[str] | None = None,
    classification: str = "pending_commit_handoff",
    blocked_by: str = "commit verb forbidden to dev subagent",
    forbidden_action: str = "agents/dev.md No Band-Aid Rule item 7",
    blocking_issues: list[str] | None = None,
) -> dict:
    """A dev.status=='needs_review' document declaring a complete M3 rationale."""
    doc = _dev_document(identity, modified=modified, created=created)
    doc["dev"]["status"] = "needs_review"
    doc["dev"]["status_rationale"] = {
        "classification": classification,
        "blocked_by": blocked_by,
        "forbidden_action": forbidden_action,
    }
    doc["blocking_issues"] = ["awaiting /commit hand-off"] if blocking_issues is None else blocking_issues
    return doc


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


# ---------------------------------------------------------------------------
# Finding F-AGG-ASYMMETRY: the dev-report SHARD scan used to decide lane
# membership purely from the filename while the sibling scan above already read
# declared identity, so one lane's fix round was counted as a second lane.  The
# first test below fails if the filename-only rule is reintroduced; the rest
# pin the two limits that keep the identity rule from becoming an escape.
# ---------------------------------------------------------------------------

FIX_ROUND_SUFFIX = "fixround2"


def _lane_set_mismatch_details(result: dict) -> list[str]:
    return [
        error["detail"]
        for error in result["errors"]
        if error["code"] == "LANE_SET_MISMATCH"
    ]


def test_dev_report_fix_round_of_a_declared_lane_is_not_an_extra_lane(
    tmp_path: Path,
) -> None:
    # The regression under repair.  A declared lane's fix-round dev-report
    # carries a distinguishing filename suffix while declaring, in both identity
    # fields, the lane it belongs to.  Counting a worker carved out of the whole
    # suffix invents a lane that never ran and manufactures a mismatch no honest
    # declaration can satisfy.
    _make_fanout(tmp_path)
    variant = _variant(
        tmp_path, f"dev-report-{TASK_ID}-{WORKERS[0]}-{FIX_ROUND_SUFFIX}.json"
    )
    _write(variant, _dev_document(f"{TASK_ID}-{WORKERS[0]}"))
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert _lane_set_mismatch_details(result) == []
    assert result["status"] == "pass", result["errors"]


def test_dev_report_shard_without_usable_identity_still_uses_its_filename(
    tmp_path: Path,
) -> None:
    # The deliberate fallback must keep firing, so damaging or omitting one's own
    # identity can never buy a weaker verdict than declaring it honestly.  Each
    # body below is a degenerate identity that `_self_declared_identity` refuses.
    label = f"{UNDECLARED_WORKER}-{FIX_ROUND_SUFFIX}"
    bodies: list[str | dict] = [
        {"dev": {"status": "completed"}},
        {"request_id": "   ", "task_id": f"{TASK_ID}-{WORKERS[0]}"},
        {"request_id": f"{TASK_ID}-{WORKERS[0]}", "task_id": f"{TASK_ID}-{WORKERS[1]}"},
        "{not json\n",
        '["lane-a"]\n',
    ]
    for index, body in enumerate(bodies):
        root = tmp_path / f"degenerate-{index}"
        _make_fanout(root)
        _write(_variant(root, f"dev-report-{TASK_ID}-{label}.json"), body)
        result = RESOLVER.resolve_chain(root, TASK_ID)
        assert _lane_set_mismatch_details(result) == [
            f"parallel_workers {WORKERS!r} do not exactly match shards "
            f"{sorted([*WORKERS, label])!r}"
        ], index
        assert result["status"] == "fail", index


def test_dev_report_shard_declaring_an_undispatched_lane_cannot_smuggle_itself_in(
    tmp_path: Path,
) -> None:
    # A declaration is honoured only when it resolves to a lane the canonical
    # actually declared.  Claiming a lane nobody dispatched buys nothing: the
    # filename label is attributed instead and the mismatch still fires.
    _make_fanout(tmp_path)
    label = f"{WORKERS[0]}-{FIX_ROUND_SUFFIX}"
    _write(
        _variant(tmp_path, f"dev-report-{TASK_ID}-{label}.json"),
        _dev_document(f"{TASK_ID}-{UNDECLARED_WORKER}"),
    )
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert _lane_set_mismatch_details(result) == [
        f"parallel_workers {WORKERS!r} do not exactly match shards "
        f"{sorted([*WORKERS, label])!r}"
    ]
    assert result["status"] == "fail"


def test_a_genuinely_undeclared_dev_report_lane_is_still_a_mismatch(
    tmp_path: Path,
) -> None:
    # The finding that must survive: a lane that really ran without being
    # declared, declaring its own distinct identity.  Reading identity must
    # sharpen this detection, never suppress it.
    _make_fanout(tmp_path)
    _write(
        _lane_paths(tmp_path, UNDECLARED_WORKER)["dev"],
        _dev_document(f"{TASK_ID}-{UNDECLARED_WORKER}"),
    )
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert _lane_set_mismatch_details(result) == [
        f"parallel_workers {WORKERS!r} do not exactly match shards "
        f"{sorted([*WORKERS, UNDECLARED_WORKER])!r}"
    ]
    assert result["status"] == "fail"


# ---------------------------------------------------------------------------
# R4 (spec-20260907-115508-lawful-commit-channel.md) additive gap
# classification: stage_gaps / non_gap_errors / late_repair_eligible /
# gap_classification. AC-6 and AC-15
# (docs/dev/acceptance-criteria-20260910-091226.json).
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _late_repair_fixtures as _lrfx  # noqa: E402

GOLDEN_DIR = REPO_ROOT / "tests" / "fixtures" / "late_repair_golden"
NEW_GAP_FIELDS = {"stage_gaps", "non_gap_errors", "late_repair_eligible", "gap_classification"}
# ticket 20260911-011232 M1: disclosed_exceptions is a second purely-additive
# field, following the exact same golden-baseline exemption as the R4 fields
# above -- none of the golden fixtures exercise a disclosed exception, so the
# field is always [] for them and is excluded from the pinned-baseline diff
# the same way NEW_GAP_FIELDS already is.
NEW_GAP_FIELDS = NEW_GAP_FIELDS | {"disclosed_exceptions"}
# task dev-20260927-135305 (spec-20260914-052140 S5.3, same-cycle-only gate
# rescope): ownership_completeness_informational is a third purely-additive
# field, same exemption -- none of the golden fixtures exercise a fan-out
# chain with a real ownership-completeness gap, so the field is always []
# for them.
NEW_GAP_FIELDS = NEW_GAP_FIELDS | {"ownership_completeness_informational"}


def test_ac6_gap_fields_partition_stage_gaps_from_integrity_errors(tmp_path: Path) -> None:
    complete_root = tmp_path / "complete"
    _lrfx.build_complete(complete_root, _lrfx.TASK_ID)
    complete = RESOLVER.resolve_chain(complete_root, _lrfx.TASK_ID)
    assert complete["stage_gaps"] == []
    assert complete["non_gap_errors"] == []
    assert complete["late_repair_eligible"] is False
    assert complete["gap_classification"] == "complete"

    qa_only_root = tmp_path / "qa_only"
    _lrfx.build_qa_only(qa_only_root, _lrfx.TASK_ID)
    qa_only = RESOLVER.resolve_chain(qa_only_root, _lrfx.TASK_ID)
    assert qa_only["stage_gaps"] == []
    assert qa_only["non_gap_errors"] == []
    assert qa_only["late_repair_eligible"] is False
    assert qa_only["gap_classification"] == "qa_only"

    beyond_qa_root = tmp_path / "beyond_qa"
    paths = _lrfx.build_beyond_qa_clean(beyond_qa_root, _lrfx.TASK_ID)
    beyond_qa = RESOLVER.resolve_chain(beyond_qa_root, _lrfx.TASK_ID)
    assert beyond_qa["stage_gaps"] == sorted([
        _relative(beyond_qa_root, paths["ticket"]),
        _relative(beyond_qa_root, paths["context"]),
    ])
    assert beyond_qa["non_gap_errors"] == []
    assert beyond_qa["late_repair_eligible"] is True
    assert beyond_qa["gap_classification"] == "beyond_qa"

    mixed_root = tmp_path / "mixed_integrity"
    mixed_paths = _lrfx.build_mixed_integrity(mixed_root, _lrfx.TASK_ID)
    mixed = RESOLVER.resolve_chain(mixed_root, _lrfx.TASK_ID)
    assert mixed["stage_gaps"] == [_relative(mixed_root, mixed_paths["ticket"])]
    assert mixed["non_gap_errors"] == [_relative(mixed_root, mixed_paths["dev_report"])]
    # The mixed-integrity fixture proves late_repair_eligible==False EVEN
    # THOUGH stage_gaps is non-empty (codex finding #7) -- a real stage gap
    # co-occurring with an unrelated integrity error is not eligible.
    assert mixed["late_repair_eligible"] is False
    assert mixed["gap_classification"] == "beyond_qa"

    fanout_root = tmp_path / "fanout"
    _lrfx.build_fanout(fanout_root, _lrfx.TASK_ID)
    fanout = RESOLVER.resolve_chain(fanout_root, _lrfx.TASK_ID)
    assert fanout["mode"] == "fanout"
    assert fanout["stage_gaps"] == RESOLVER.NOT_APPLICABLE
    assert fanout["non_gap_errors"] == RESOLVER.NOT_APPLICABLE
    assert fanout["late_repair_eligible"] == RESOLVER.NOT_APPLICABLE
    assert fanout["gap_classification"] == RESOLVER.NOT_APPLICABLE


def test_ac6_gap_fields_computed_in_exactly_one_function(tmp_path: Path) -> None:
    source = RESOLVER_PATH.read_text(encoding="utf-8")
    # Every one of the four field names must be ASSIGNED (appear as a dict
    # key target) in exactly one function body: _compute_gap_fields. A
    # code-search over `result["<field>"] = ` call sites confirms both
    # resolve_chain() call sites merely ASSIGN the tuple _compute_gap_fields
    # returns -- neither recomputes the classification independently.
    assert source.count("def _compute_gap_fields(") == 1
    body_start = source.index("def _compute_gap_fields(")
    body_end = source.index("\n\n\ndef ", body_start)
    body = source[body_start:body_end]
    assert "STAGE_GAP_CODES" in body
    # Outside the function, STAGE_GAP_CODES must appear only in its own
    # module-level constant definition -- never a second partition site.
    outside = source[:body_start] + source[body_end:]
    assert outside.count("STAGE_GAP_CODES") == 1  # the constant's own definition


def test_ac15_new_fields_are_purely_additive_against_a_pinned_golden_baseline(
    tmp_path: Path,
) -> None:
    golden_files = sorted(GOLDEN_DIR.glob("*.json"))
    golden_names = {p.stem for p in golden_files}
    assert len(golden_files) >= 4, (
        "golden baseline directory must be non-empty (codex round-2 finding #15) -- "
        f"found {golden_files}"
    )
    assert golden_names == {"complete", "qa_only", "mixed_integrity", "fanout"}

    builders = {
        "complete": _lrfx.build_complete,
        "qa_only": _lrfx.build_qa_only,
        "mixed_integrity": _lrfx.build_mixed_integrity,
        "fanout": _lrfx.build_fanout,
    }
    for name, builder in builders.items():
        root = tmp_path / name
        builder(root, _lrfx.TASK_ID)
        current = RESOLVER.resolve_chain(root, _lrfx.TASK_ID)
        stripped = {k: v for k, v in current.items() if k not in NEW_GAP_FIELDS}
        golden = json.loads((GOLDEN_DIR / f"{name}.json").read_text(encoding="utf-8"))
        golden_stripped = {k: v for k, v in golden.items() if k not in NEW_GAP_FIELDS}
        assert stripped == golden_stripped, name


# ---------------------------------------------------------------------------
# Disclosed-exception vocabulary (ticket 20260911-011232).  Bidirectional:
# AC-P* prove the new intermediate state is REACHABLE for a genuine, complete
# disclosure; AC-N* prove every pre-existing hard-fail shape (incomplete,
# mislabeled, untrustworthy, or simply undeclared) keeps failing exactly as
# before -- disclosed_exceptions[] must stay empty on every AC-N case.
# ---------------------------------------------------------------------------


def test_ac_p1_qa_environmental_disclosed_exception_reaches_pass_with_exceptions(
    tmp_path: Path,
) -> None:
    parents = _make_singular(tmp_path)
    _write(parents["qa"], _qa_document_with_disclosed_exception(TASK_ID))
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "pass_with_exceptions", result["errors"]
    assert result["errors"] == []
    assert len(result["disclosed_exceptions"]) == 1
    entry = result["disclosed_exceptions"][0]
    assert entry["code"] == "INVALID_QA_STATUS"
    assert entry["path"] == _relative(tmp_path, parents["qa"])
    assert entry["lane_task_id"] == TASK_ID
    assert entry["kind"] == "qa_environmental"
    assert entry["classification"] == "shared_working_tree_concurrency"
    assert entry["evidence_ref_count"] == 1


def test_ac_p2_dev_side_handoff_reaches_pass_with_exceptions(tmp_path: Path) -> None:
    # Singular mode: the parent IS the lane, and its own qa-report is the
    # "same lane's own qa-report" M3(b) requires.
    parents = _make_singular(tmp_path)
    _write(parents["dev"], _dev_document_needs_review(TASK_ID, modified=["scripts/one.py"]))
    _write(parents["qa"], _qa_document(TASK_ID, status="pass"))
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "pass_with_exceptions", result["errors"]
    assert result["errors"] == []
    codes = {entry["code"] for entry in result["disclosed_exceptions"]}
    assert codes == {"INVALID_DEV_STATUS", "UNRESOLVED_BLOCKERS"}
    for entry in result["disclosed_exceptions"]:
        assert entry["path"] == _relative(tmp_path, parents["dev"])
        assert entry["lane_task_id"] == TASK_ID
        assert entry["kind"] == "dev_handoff"
        assert entry["classification"] == "pending_commit_handoff"


def test_ac_p3_fanout_dev_handoff_lane_propagates_through_aggregate_and_route_select(
    tmp_path: Path,
) -> None:
    # The full motivating shape (task 20260808-035658's lanesumatdoc10): one
    # lane whose dev.status is a disclosed needs_review handoff, its OWN
    # qa-report passes, and (per M5) the canonical inherits needs_review too
    # -- exercised end to end through aggregate-dev-report.py and
    # close-route-select.py, not just resolve_chain() directly.
    parents = _parent_paths(tmp_path)
    lanes: dict[str, dict[str, Path]] = {}
    loaded: list[tuple[str, dict]] = []
    references = [_relative(tmp_path, parents["dev"])]

    identity_a = f"{TASK_ID}-lane-a"
    paths_a = _lane_paths(tmp_path, "lane-a")
    lanes["lane-a"] = paths_a
    _materialise(tmp_path, "scripts/lane-a.py")
    dev_a = _dev_document(identity_a, modified=["scripts/lane-a.py"])
    _write(paths_a["ticket"], _ticket(identity_a))
    _write(paths_a["context"], {"request_id": identity_a, "task_id": identity_a})
    _write(paths_a["dev"], dev_a)
    _write(paths_a["qa"], _qa_document(identity_a))
    loaded.append(("lane-a", dev_a))
    references.extend(_relative(tmp_path, paths_a[k]) for k in ("ticket", "context", "dev", "qa"))

    identity_b = f"{TASK_ID}-lane-b"
    paths_b = _lane_paths(tmp_path, "lane-b")
    lanes["lane-b"] = paths_b
    _materialise(tmp_path, "scripts/lane-b.py")
    dev_b = _dev_document_needs_review(identity_b, modified=["scripts/lane-b.py"])
    _write(paths_b["ticket"], _ticket(identity_b))
    _write(paths_b["context"], {"request_id": identity_b, "task_id": identity_b})
    _write(paths_b["dev"], dev_b)
    _write(paths_b["qa"], _qa_document(identity_b, status="pass"))
    loaded.append(("lane-b", dev_b))
    references.extend(_relative(tmp_path, paths_b[k]) for k in ("ticket", "context", "dev", "qa"))

    aggregate_module = RESOLVER._load_aggregate_module()
    fresh_canonical = aggregate_module._build_aggregate(loaded, TASK_ID)
    _write(parents["dev"], fresh_canonical)
    _write(parents["qa"], _qa_document(TASK_ID, status="pass"))
    _write(parents["completion"], _completion(TASK_ID, references))

    # M5: the canonical itself declares needs_review with a synthesized
    # status_rationale aggregating the contributing lane.
    assert fresh_canonical["dev"]["status"] == "needs_review"
    assert fresh_canonical["dev"]["status_rationale"]["classification"] == "pending_commit_handoff"
    assert "lane-b" in fresh_canonical["dev"]["status_rationale"]["blocked_by"]

    # AC-P3 / M5: aggregate-dev-report.py no longer rejects the needs_review
    # shard before the resolver is even reached (was exit 1 pre-fix).
    aggregate_result = _run_aggregate(tmp_path)
    assert aggregate_result.returncode == 0, aggregate_result.stderr

    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "pass_with_exceptions", result["errors"]
    assert result["errors"] == []
    by_path: dict[str, set[str]] = {}
    for entry in result["disclosed_exceptions"]:
        by_path.setdefault(entry["path"], set()).add(entry["code"])
        assert entry["kind"] == "dev_handoff"
    assert by_path[_relative(tmp_path, paths_b["dev"])] == {"INVALID_DEV_STATUS", "UNRESOLVED_BLOCKERS"}
    assert by_path[_relative(tmp_path, parents["dev"])] == {"INVALID_DEV_STATUS", "UNRESOLVED_BLOCKERS"}

    # AC-P3 / M4: close-route-select.py (the fixed production entrypoint
    # /close's Step 0 shells out to) exits 0, not 2, on this chain.
    route_result = _run_route_select(tmp_path)
    assert route_result.returncode == 0, route_result.stdout
    route_payload = json.loads(route_result.stdout)
    assert route_payload["outcome"] == "not_selected"
    assert route_payload["artifact_chain"]["status"] == "pass_with_exceptions"


def _make_fanout_with_one_needs_review_lane(
    tmp_path: Path, *, contributing_lane_qa_status: str = "pass"
) -> tuple[dict[str, Path], Path, Path]:
    """Shared scaffold for the iteration-2 parent-reclassification tests.

    Builds the real-world fan-out shape (no parent ticket/context/qa-report
    ever written -- commands/close.md documents those as optional, and the
    live motivating task 20260808-035658 has no qa-report-<task-id>.json on
    disk at all) with one clean lane-a and one needs_review lane-b whose own
    qa-report status is the caller-supplied `contributing_lane_qa_status`.
    """
    parents = _parent_paths(tmp_path)
    loaded: list[tuple[str, dict]] = []
    references = [_relative(tmp_path, parents["dev"])]

    identity_a = f"{TASK_ID}-lane-a"
    paths_a = _lane_paths(tmp_path, "lane-a")
    _materialise(tmp_path, "scripts/lane-a.py")
    dev_a = _dev_document(identity_a, modified=["scripts/lane-a.py"])
    _write(paths_a["ticket"], _ticket(identity_a))
    _write(paths_a["context"], {"request_id": identity_a, "task_id": identity_a})
    _write(paths_a["dev"], dev_a)
    _write(paths_a["qa"], _qa_document(identity_a))
    loaded.append(("lane-a", dev_a))
    references.extend(_relative(tmp_path, paths_a[k]) for k in ("ticket", "context", "dev", "qa"))

    identity_b = f"{TASK_ID}-lane-b"
    paths_b = _lane_paths(tmp_path, "lane-b")
    _materialise(tmp_path, "scripts/lane-b.py")
    dev_b = _dev_document_needs_review(identity_b, modified=["scripts/lane-b.py"])
    _write(paths_b["ticket"], _ticket(identity_b))
    _write(paths_b["context"], {"request_id": identity_b, "task_id": identity_b})
    _write(paths_b["dev"], dev_b)
    _write(paths_b["qa"], _qa_document(identity_b, status=contributing_lane_qa_status))
    loaded.append(("lane-b", dev_b))
    references.extend(_relative(tmp_path, paths_b[k]) for k in ("ticket", "context", "dev", "qa"))

    aggregate_module = RESOLVER._load_aggregate_module()
    fresh_canonical = aggregate_module._build_aggregate(loaded, TASK_ID)
    _write(parents["dev"], fresh_canonical)
    _write(parents["completion"], _completion(TASK_ID, references))
    assert not parents["qa"].exists()
    assert not parents["ticket"].exists()
    assert not parents["context"].exists()
    return parents, paths_a["dev"], paths_b["dev"]


def test_ac_p3b_fanout_parent_reclassifies_via_contributing_lane_qa_with_no_parent_qa_report(
    tmp_path: Path,
) -> None:
    """Ticket 20260911-011232 iteration 2: the exact empirically-found gap.

    `test_ac_p3_...` above happens to write a parent-level qa-report showing
    qa.status == "pass", which coincidentally satisfied
    `_dev_handoff_eligible`'s sibling-qa-report lookup for the parent path
    too -- masking the real bug.  In real fan-out mode (and in the live
    motivating task 20260808-035658) NO parent-level qa-report file exists on
    disk at all.  The parent/canonical's own INVALID_DEV_STATUS /
    UNRESOLVED_BLOCKERS errors must still reclassify into
    disclosed_exceptions[] by cross-checking the CONTRIBUTING lane's (lane-b,
    the one whose dev.status == "needs_review" actually drove the parent's
    synthesized status_rationale) own qa-report -- not a nonexistent
    qa-report-<bare-task-id> sibling of the parent.
    """
    parents, dev_a_path, dev_b_path = _make_fanout_with_one_needs_review_lane(
        tmp_path, contributing_lane_qa_status="pass"
    )

    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "pass_with_exceptions", result["errors"]
    assert result["errors"] == []
    by_path: dict[str, set[str]] = {}
    for entry in result["disclosed_exceptions"]:
        by_path.setdefault(entry["path"], set()).add(entry["code"])
        assert entry["kind"] == "dev_handoff"
    assert by_path[_relative(tmp_path, dev_b_path)] == {"INVALID_DEV_STATUS", "UNRESOLVED_BLOCKERS"}
    assert by_path[_relative(tmp_path, parents["dev"])] == {"INVALID_DEV_STATUS", "UNRESOLVED_BLOCKERS"}


def test_ac_n5_fanout_parent_stays_hard_fail_when_contributing_lane_qa_does_not_pass(
    tmp_path: Path,
) -> None:
    """Rejection counterpart of the P3b case above.

    If the contributing needs_review lane's OWN qa-report does not show a
    genuine pass (undisclosed fail here), the parent's exception must NOT be
    granted and the parent's errors must stay hard exactly as before this
    iteration's fix -- proving the new cross-check does not relax anything,
    it only relocates where the same-lane-QA evidence is looked up from.
    """
    parents, dev_a_path, dev_b_path = _make_fanout_with_one_needs_review_lane(
        tmp_path, contributing_lane_qa_status="fail"
    )

    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "fail"
    codes_by_path: dict[str, set[str]] = {}
    for entry in result["errors"]:
        codes_by_path.setdefault(entry["path"], set()).add(entry["code"])
    assert codes_by_path[_relative(tmp_path, parents["dev"])] == {
        "INVALID_DEV_STATUS",
        "UNRESOLVED_BLOCKERS",
    }
    assert codes_by_path[_relative(tmp_path, dev_b_path)] == {
        "INVALID_DEV_STATUS",
        "UNRESOLVED_BLOCKERS",
    }
    assert result["disclosed_exceptions"] == []


def test_ac_5_exit_code_plumbing_is_consistent_end_to_end(tmp_path: Path) -> None:
    parents = _make_singular(tmp_path)
    _write(parents["qa"], _qa_document_with_disclosed_exception(TASK_ID))

    resolver_process = _run_cli(tmp_path)
    assert resolver_process.returncode == 0
    assert json.loads(resolver_process.stdout)["status"] == "pass_with_exceptions"

    route_process = _run_route_select(tmp_path)
    assert route_process.returncode == 0
    route_payload = json.loads(route_process.stdout)
    assert route_payload["artifact_chain"]["status"] == "pass_with_exceptions"


def test_ac_n1_incomplete_disclosure_stays_hard_fail(tmp_path: Path) -> None:
    parents = _make_singular(tmp_path)

    # Missing/empty evidence[].
    _write(parents["qa"], _qa_document_with_disclosed_exception(TASK_ID, evidence=[]))
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "fail"
    assert "INVALID_QA_STATUS" in _error_codes(result)
    assert result["disclosed_exceptions"] == []

    # Missing attestation entirely.
    doc = _qa_document_with_disclosed_exception(TASK_ID)
    del doc["qa"]["disclosed_exception"]["attestation"]
    _write(parents["qa"], doc)
    result2 = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result2["status"] == "fail"
    assert "INVALID_QA_STATUS" in _error_codes(result2)
    assert result2["disclosed_exceptions"] == []

    # Attestation present but not the exact literal (paraphrased).
    doc2 = _qa_document_with_disclosed_exception(
        TASK_ID, attestation="This is a disclosed exception, not a defect."
    )
    _write(parents["qa"], doc2)
    result3 = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result3["status"] == "fail"
    assert "INVALID_QA_STATUS" in _error_codes(result3)
    assert result3["disclosed_exceptions"] == []


def test_ac_n2_mislabeled_real_defect_stays_hard_fail(tmp_path: Path) -> None:
    parents = _make_singular(tmp_path)
    doc = _qa_document_with_disclosed_exception(
        TASK_ID,
        findings=[
            {"blocks_release": True, "severity": "critical", "primary_cause": "dev_implementation"},
        ],
    )
    _write(parents["qa"], doc)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "fail"
    assert "INVALID_QA_STATUS" in _error_codes(result)
    assert result["disclosed_exceptions"] == []

    # A non-blocking finding with a non-environment cause must NOT disqualify
    # -- only a finding that actually blocks release (or is severity=critical)
    # is examined.
    doc2 = _qa_document_with_disclosed_exception(
        TASK_ID,
        findings=[
            {"blocks_release": False, "severity": "minor", "primary_cause": "dev_implementation"},
        ],
    )
    _write(parents["qa"], doc2)
    result2 = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result2["status"] == "pass_with_exceptions", result2["errors"]


def test_qa_findings_malformed_dict_all_findings_stays_hard_fail(tmp_path: Path) -> None:
    """AC1 (dev-20260914-075954): a dict-shaped qa.all_findings must not be
    silently treated as zero findings -- a critical dev_implementation
    finding smuggled inside it must still hard-fail the chain, matching the
    already-correct list-shaped behavior in test_ac_n2 above."""
    parents = _make_singular(tmp_path)
    doc = _qa_document_with_disclosed_exception(TASK_ID)
    doc["qa"]["all_findings"] = {
        "smuggled": {
            "severity": "critical",
            "primary_cause": "dev_implementation",
            "blocks_release": True,
        }
    }
    _write(parents["qa"], doc)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "fail"
    assert "INVALID_QA_STATUS" in _error_codes(result)
    assert result["disclosed_exceptions"] == []


def test_qa_findings_malformed_dict_failures_stays_hard_fail(tmp_path: Path) -> None:
    """AC2 (dev-20260914-075954): same bypass via qa.failures instead of
    qa.all_findings -- both container keys share the vulnerable path."""
    parents = _make_singular(tmp_path)
    doc = _qa_document_with_disclosed_exception(TASK_ID)
    doc["qa"]["failures"] = {
        "smuggled": {
            "severity": "critical",
            "primary_cause": "dev_implementation",
            "blocks_release": True,
        }
    }
    _write(parents["qa"], doc)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "fail"
    assert "INVALID_QA_STATUS" in _error_codes(result)
    assert result["disclosed_exceptions"] == []


def test_qa_findings_malformed_explicit_null_stays_hard_fail(tmp_path: Path) -> None:
    """AC3 (dev-20260914-075954): an explicit JSON null for a present
    all_findings key is malformed, not "no findings" -- only a truly absent
    key means zero findings, so this must hard-fail exactly like the
    dict-shaped cases above."""
    parents = _make_singular(tmp_path)
    doc = _qa_document_with_disclosed_exception(TASK_ID)
    doc["qa"]["all_findings"] = None
    _write(parents["qa"], doc)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "fail"
    assert "INVALID_QA_STATUS" in _error_codes(result)
    assert result["disclosed_exceptions"] == []


def test_qa_findings_absent_key_guard_preserved_pass_with_exceptions(tmp_path: Path) -> None:
    """AC4 (dev-20260914-075954): guard preservation -- a truly absent
    all_findings key (the pre-existing, legitimate shape almost every
    fixture relies on) must still resolve to pass_with_exceptions; the fix
    must fail closed only on a present-but-malformed container, never on
    plain absence."""
    parents = _make_singular(tmp_path)
    doc = _qa_document_with_disclosed_exception(TASK_ID)
    assert "all_findings" not in doc["qa"]
    _write(parents["qa"], doc)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "pass_with_exceptions", result["errors"]
    assert result["errors"] == []


def test_qa_findings_malformed_scalar_shapes_stay_hard_fail(tmp_path: Path) -> None:
    """Codex round-1 finding #1 (dev-20260914-075954): the fix's isinstance
    check is a general "not a list" guard, not special-cased to dict/null --
    prove that generality holds for scalar JSON shapes too (string, number,
    boolean), for BOTH all_findings and failures."""
    parents = _make_singular(tmp_path)
    for container_key in ("all_findings", "failures"):
        for malformed_value in ("a string", 42, True):
            doc = _qa_document_with_disclosed_exception(TASK_ID)
            doc["qa"][container_key] = malformed_value
            _write(parents["qa"], doc)
            result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
            assert result["status"] == "fail", (container_key, malformed_value)
            assert "INVALID_QA_STATUS" in _error_codes(result)
            assert result["disclosed_exceptions"] == []


def test_qa_findings_malformed_explicit_null_via_failures_stays_hard_fail(tmp_path: Path) -> None:
    """Symmetric counterpart of AC3 via the failures key (Codex round-1
    finding #1)."""
    parents = _make_singular(tmp_path)
    doc = _qa_document_with_disclosed_exception(TASK_ID)
    doc["qa"]["failures"] = None
    _write(parents["qa"], doc)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "fail"
    assert "INVALID_QA_STATUS" in _error_codes(result)
    assert result["disclosed_exceptions"] == []


def test_qa_findings_absent_all_findings_with_valid_list_failures_still_pass_with_exceptions(
    tmp_path: Path,
) -> None:
    """Symmetric counterpart of AC4 (Codex round-1 finding #1): all_findings
    entirely absent while failures IS present and list-shaped with only a
    non-blocking finding must still resolve to pass_with_exceptions -- the
    fix must not regress this valid mixed-presence case either."""
    parents = _make_singular(tmp_path)
    doc = _qa_document_with_disclosed_exception(TASK_ID)
    assert "all_findings" not in doc["qa"]
    doc["qa"]["failures"] = [
        {"blocks_release": False, "severity": "minor", "primary_cause": "dev_implementation"},
    ]
    _write(parents["qa"], doc)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "pass_with_exceptions", result["errors"]
    assert result["errors"] == []


def test_ac_n3_needs_review_without_same_lane_qa_pass_stays_hard_fail(tmp_path: Path) -> None:
    parents = _make_singular(tmp_path)
    _write(parents["dev"], _dev_document_needs_review(TASK_ID, modified=["scripts/one.py"]))
    _write(parents["qa"], _qa_document(TASK_ID, status="fail"))
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "fail"
    codes = _error_codes(result)
    assert "INVALID_DEV_STATUS" in codes
    assert "UNRESOLVED_BLOCKERS" in codes
    # The undisclosed qa fail also stays hard -- no disclosure block supplied.
    assert "INVALID_QA_STATUS" in codes
    assert result["disclosed_exceptions"] == []


def test_ac_n4_reverted_2026_08_06_warning_shape_still_hard_fails(tmp_path: Path) -> None:
    # Today's exact reverted-attempt shape: qa.status=='warning' (or 'fail')
    # with NO qa.disclosed_exception block at all -- proves the base binary
    # check validate_qa() (the subject of the reverted attempt) is untouched.
    parents = _make_singular(tmp_path)
    for bad_status in ("warning", "fail"):
        _write(parents["qa"], _qa_document(TASK_ID, status=bad_status))
        result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
        assert result["status"] == "fail"
        assert "INVALID_QA_STATUS" in _error_codes(result)
        assert result["disclosed_exceptions"] == []


def test_ac_6_blocked_status_is_never_reclassification_eligible(tmp_path: Path) -> None:
    parents = _make_singular(tmp_path)
    doc = _dev_document(TASK_ID, modified=["scripts/one.py"])
    doc["dev"]["status"] = "blocked"
    # Even a fully-formed status_rationale block must not rescue 'blocked' --
    # it is unconditionally hard-fail regardless of any disclosure attempt.
    doc["dev"]["status_rationale"] = {
        "classification": "pending_commit_handoff",
        "blocked_by": "irrelevant",
        "forbidden_action": "irrelevant",
    }
    doc["blocking_issues"] = ["something"]
    _write(parents["dev"], doc)
    _write(parents["qa"], _qa_document(TASK_ID, status="pass"))
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "fail"
    codes = _error_codes(result)
    assert "INVALID_DEV_STATUS" in codes
    assert "UNRESOLVED_BLOCKERS" in codes
    assert result["disclosed_exceptions"] == []


def test_missing_disclosure_field_on_an_otherwise_needs_review_lane_stays_hard_fail(
    tmp_path: Path,
) -> None:
    # dev.status=='needs_review' but status_rationale is entirely absent.
    parents = _make_singular(tmp_path)
    doc = _dev_document(TASK_ID, modified=["scripts/one.py"])
    doc["dev"]["status"] = "needs_review"
    doc["blocking_issues"] = ["awaiting /commit hand-off"]
    _write(parents["dev"], doc)
    _write(parents["qa"], _qa_document(TASK_ID, status="pass"))
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert result["status"] == "fail"
    codes = _error_codes(result)
    assert "INVALID_DEV_STATUS" in codes
    assert "UNRESOLVED_BLOCKERS" in codes
    assert result["disclosed_exceptions"] == []


# --- Serialized-wave baseline route -----------------------------------------
#
# A fan-out whose lanes edit the same file must be dispatched serially, so its
# lanes see different dirty trees -- and a lane dispatched after a peer session
# committed sees a different head.  The shared-baseline requirement exists
# because the aggregate projects ONE baseline for the whole set and every
# downstream pre-edit/ownership cross-check resolves every lane's files against
# that single scalar; equality is what makes that projection lossless.  These
# tests pin the route that lets a serialized set declare its order truthfully,
# AND pin that every corruption the requirement caught is still caught.

SERIAL_DIRTY_A = " M scripts/alpha.py\n?? scripts/beta.py\n"
SERIAL_DIRTY_B = " M scripts/alpha.py\n?? scripts/beta.py\n?? tests/lane-0.py\n"


def _init_repo(root: Path) -> list[str]:
    """Make `root` a git repo with two commits; return [first_sha, second_sha]."""
    env_git = [
        "git",
        "-c",
        "user.name=wave-fixture",
        "-c",
        "user.email=wave@fixture.invalid",
        "-C",
        str(root),
    ]
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    shas: list[str] = []
    for index in range(2):
        marker = root / f"commit-{index}.txt"
        marker.write_text(f"commit {index}\n", encoding="utf-8")
        subprocess.run(env_git + ["add", "--", marker.name], check=True)
        subprocess.run(env_git + ["commit", "-q", "-m", f"c{index}"], check=True)
        shas.append(
            subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
    return shas


def _divergent_sha(root: Path) -> str:
    """A real commit object on an unrelated root -- reachable from nothing.

    Built with mktree/commit-tree rather than an orphan branch so the fixture
    creates no branch, no worktree and no checkout: it only writes a parentless
    commit object into the repo's object store.
    """
    tree = subprocess.run(
        ["git", "-C", str(root), "mktree"],
        input="",
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=wave-fixture",
            "-c",
            "user.email=wave@fixture.invalid",
            "-C",
            str(root),
            "commit-tree",
            tree,
            "-m",
            "unrelated root",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _make_wave_fanout(root: Path, overrides: dict[str, dict]) -> dict[str, Path]:
    """Fan-out of WORKERS where each lane's dev document is patched in place.

    The canonical is rebuilt from the patched shards, so these fixtures isolate
    the baseline dimensions under test instead of tripping the freshness checks.
    """
    parents = _parent_paths(root)
    loaded = []
    references = [_relative(root, parents["dev"])]
    for index, worker in enumerate(WORKERS):
        identity = f"{TASK_ID}-{worker}"
        paths = _lane_paths(root, worker)
        _materialise(root, f"scripts/lane-{index}.py", f"tests/lane-{index}.py")
        dev = _dev_document(
            identity,
            modified=[f"scripts/lane-{index}.py"],
            created=[f"tests/lane-{index}.py"],
        )
        dev.update(overrides.get(worker, {}))
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
    return parents


def _shard_details(result: dict) -> list[str]:
    return [e["detail"] for e in result["errors"] if e["code"] == "INVALID_SHARD_SET"]


def _wave_details(result: dict) -> list[str]:
    return [
        e["detail"] for e in result["errors"] if e["code"] == "INVALID_BASELINE_WAVE"
    ]


def _serialized_overrides(first: str, second: str) -> dict[str, dict]:
    """Lane-a at the older commit, lane-b at its descendant, chain declared.

    Both baseline dimensions diverge at once, exactly as a serialized wave's do:
    lane-b ran later, so it saw a commit lane-a had not and a dirty tree lane-a
    had not.  Neither lane's recorded baseline is altered to agree with the
    other's -- the chain explains the divergence instead.
    """
    return {
        "lane-a": {
            "baseline_head_sha": first,
            "baseline_dirty_snapshot": SERIAL_DIRTY_A,
        },
        "lane-b": {
            "baseline_head_sha": second,
            "baseline_dirty_snapshot": SERIAL_DIRTY_B,
            "baseline_wave": {
                "mode": "serialized_wave",
                "derived_from": "lane-a",
                "predecessor_head_sha": first,
                "explains": ["baseline_head_sha", "baseline_dirty_snapshot"],
                "dirty_predecessor": "lane-a",
                "dirty_growth": 1,
                "dirty_attribution": [
                    {
                        "source": "chain_files_created",
                        "paths": ["tests/lane-0.py"],
                    }
                ],
            },
        },
    }


def test_serialized_wave_with_per_lane_baselines_validates(tmp_path: Path) -> None:
    first, second = _init_repo(tmp_path)
    _make_wave_fanout(tmp_path, _serialized_overrides(first, second))
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert _wave_details(result) == []
    assert _shard_details(result) == []
    assert result["status"] == "pass"


def test_simultaneous_fanout_still_validates_unchanged(tmp_path: Path) -> None:
    """Regression control: one shared baseline, no declaration anywhere."""
    _init_repo(tmp_path)
    shared = {
        "baseline_head_sha": "0123456789abcdef",
        "baseline_dirty_snapshot": SERIAL_DIRTY_A,
    }
    _make_wave_fanout(tmp_path, {worker: dict(shared) for worker in WORKERS})
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert _wave_details(result) == []
    assert _shard_details(result) == []
    assert result["status"] == "pass"


def test_undeclared_divergent_baseline_is_still_rejected(tmp_path: Path) -> None:
    """Positive control for the corruption the shared-baseline check catches.

    The ONLY difference from test_serialized_wave_with_per_lane_baselines_
    validates is that nothing is declared.  Divergence without a declaration is
    indistinguishable from a lane dispatched against a stale or foreign tree, so
    it must still be rejected under the original code.
    """
    first, second = _init_repo(tmp_path)
    overrides = _serialized_overrides(first, second)
    overrides["lane-b"].pop("baseline_wave")
    _make_wave_fanout(tmp_path, overrides)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert _wave_details(result) == []
    details = _shard_details(result)
    assert any("baseline_head_sha" in detail for detail in details), details
    assert any("baseline_dirty_snapshot mismatch" in detail for detail in details), details
    assert result["status"] == "fail"


def test_serialized_wave_rejects_head_unrelated_to_its_predecessor(
    tmp_path: Path,
) -> None:
    first, _second = _init_repo(tmp_path)
    orphan = _divergent_sha(tmp_path)
    overrides = _serialized_overrides(first, orphan)
    overrides["lane-b"]["baseline_head_sha"] = orphan
    _make_wave_fanout(tmp_path, overrides)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert any("is not reachable from" in d for d in _wave_details(result)), result[
        "errors"
    ]
    # The divergence it failed to explain is still reported under its own code.
    assert any("baseline_head_sha" in d for d in _shard_details(result))
    assert result["status"] == "fail"


def test_serialized_wave_rejects_a_misstated_predecessor_head(tmp_path: Path) -> None:
    first, second = _init_repo(tmp_path)
    overrides = _serialized_overrides(first, second)
    overrides["lane-b"]["baseline_wave"]["predecessor_head_sha"] = second
    _make_wave_fanout(tmp_path, overrides)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert any(
        "does not match the baseline_head_sha" in d for d in _wave_details(result)
    ), result["errors"]
    assert result["status"] == "fail"


def test_serialized_wave_rejects_a_predecessor_outside_the_shard_set(
    tmp_path: Path,
) -> None:
    first, second = _init_repo(tmp_path)
    overrides = _serialized_overrides(first, second)
    overrides["lane-b"]["baseline_wave"]["derived_from"] = "lane-ghost"
    _make_wave_fanout(tmp_path, overrides)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert any("is not among the shards" in d for d in _wave_details(result)), result[
        "errors"
    ]
    assert result["status"] == "fail"


def test_serialized_wave_rejects_a_shrinking_working_tree(tmp_path: Path) -> None:
    first, second = _init_repo(tmp_path)
    overrides = _serialized_overrides(first, second)
    overrides["lane-a"]["baseline_dirty_snapshot"] = SERIAL_DIRTY_B
    overrides["lane-b"]["baseline_dirty_snapshot"] = SERIAL_DIRTY_A
    overrides["lane-b"]["baseline_wave"]["dirty_growth"] = -1
    _make_wave_fanout(tmp_path, overrides)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert any("may only grow along the chain" in d for d in _wave_details(result)), (
        result["errors"]
    )
    assert result["status"] == "fail"


def test_serialized_wave_rejects_growth_it_cannot_account_for(tmp_path: Path) -> None:
    first, second = _init_repo(tmp_path)
    overrides = _serialized_overrides(first, second)
    overrides["lane-b"]["baseline_wave"]["dirty_attribution"] = [
        {"source": "chain_files_created", "paths": ["tests/never-created.py"]}
    ]
    _make_wave_fanout(tmp_path, overrides)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert any(
        "but none of those shards recorded creating them" in d
        for d in _wave_details(result)
    ), result["errors"]
    assert result["status"] == "fail"


def test_serialized_wave_rejects_a_declared_growth_figure_that_is_invented(
    tmp_path: Path,
) -> None:
    first, second = _init_repo(tmp_path)
    overrides = _serialized_overrides(first, second)
    overrides["lane-b"]["baseline_wave"]["dirty_growth"] = 7
    _make_wave_fanout(tmp_path, overrides)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert any(
        "does not equal the 1 entry growth recomputed" in d
        for d in _wave_details(result)
    ), result["errors"]
    assert result["status"] == "fail"


def test_serialized_wave_forbids_an_unitemised_remainder_on_a_porcelain_snapshot(
    tmp_path: Path,
) -> None:
    """Porcelain names every entry, so exhaustive itemisation is required."""
    first, second = _init_repo(tmp_path)
    overrides = _serialized_overrides(first, second)
    overrides["lane-b"]["baseline_wave"]["dirty_attribution"] = [
        {"source": "peer_session", "paths": ["scripts/peer.py"]}
    ]
    overrides["lane-b"]["baseline_wave"]["dirty_growth_unitemised"] = 1
    overrides["lane-b"]["baseline_wave"]["dirty_growth_unitemised_reason"] = "narration"
    _make_wave_fanout(tmp_path, overrides)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    details = _wave_details(result)
    assert any("exhaustive itemisation is possible here" in d for d in details), details
    assert result["status"] == "fail"


def test_serialized_wave_permits_an_unitemised_remainder_on_a_narration(
    tmp_path: Path,
) -> None:
    """A count summary names examples, so a declared, reasoned remainder stands."""
    first, second = _init_repo(tmp_path)
    overrides = _serialized_overrides(first, second)
    overrides["lane-a"]["baseline_dirty_snapshot"] = "2 paths dirty at dispatch."
    overrides["lane-b"]["baseline_dirty_snapshot"] = "4 paths dirty at dispatch."
    wave = overrides["lane-b"]["baseline_wave"]
    wave["dirty_growth"] = 2
    wave["dirty_attribution"] = [
        {"source": "chain_files_created", "paths": ["tests/lane-0.py"]}
    ]
    wave["dirty_growth_unitemised"] = 1
    wave["dirty_growth_unitemised_reason"] = (
        "the recorded snapshot is a count summary naming examples, not porcelain"
    )
    _make_wave_fanout(tmp_path, overrides)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert _wave_details(result) == []
    assert _shard_details(result) == []
    assert result["status"] == "pass"


def test_serialized_wave_requires_a_reason_for_an_unitemised_remainder(
    tmp_path: Path,
) -> None:
    first, second = _init_repo(tmp_path)
    overrides = _serialized_overrides(first, second)
    overrides["lane-a"]["baseline_dirty_snapshot"] = "2 paths dirty at dispatch."
    overrides["lane-b"]["baseline_dirty_snapshot"] = "4 paths dirty at dispatch."
    wave = overrides["lane-b"]["baseline_wave"]
    wave["dirty_growth"] = 2
    wave["dirty_attribution"] = [
        {"source": "chain_files_created", "paths": ["tests/lane-0.py"]}
    ]
    wave["dirty_growth_unitemised"] = 1
    _make_wave_fanout(tmp_path, overrides)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert any(
        "must state why the recorded snapshot cannot support exhaustive itemisation" in d
        for d in _wave_details(result)
    ), result["errors"]
    assert result["status"] == "fail"


def test_serialized_wave_rejects_peer_attribution_that_double_counts_the_chain(
    tmp_path: Path,
) -> None:
    first, second = _init_repo(tmp_path)
    overrides = _serialized_overrides(first, second)
    overrides["lane-b"]["baseline_wave"]["dirty_attribution"] = [
        {"source": "peer_session", "paths": ["tests/lane-0.py"]}
    ]
    _make_wave_fanout(tmp_path, overrides)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert any(
        "cannot be counted twice" in d for d in _wave_details(result)
    ), result["errors"]
    assert result["status"] == "fail"


def test_serialized_wave_rejects_an_unsupported_mode(tmp_path: Path) -> None:
    first, second = _init_repo(tmp_path)
    overrides = _serialized_overrides(first, second)
    overrides["lane-b"]["baseline_wave"]["mode"] = "whatever"
    _make_wave_fanout(tmp_path, overrides)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert any("is not supported" in d for d in _wave_details(result)), result["errors"]
    assert result["status"] == "fail"


def test_serialized_wave_rejects_a_self_referential_chain(tmp_path: Path) -> None:
    first, second = _init_repo(tmp_path)
    overrides = _serialized_overrides(first, second)
    overrides["lane-b"]["baseline_wave"]["derived_from"] = "lane-b"
    _make_wave_fanout(tmp_path, overrides)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert any("names itself" in d for d in _wave_details(result)), result["errors"]
    assert result["status"] == "fail"


def test_serialized_wave_rejects_a_cycle_that_roots_nowhere(tmp_path: Path) -> None:
    first, second = _init_repo(tmp_path)
    overrides = _serialized_overrides(first, second)
    overrides["lane-a"]["baseline_wave"] = {
        "mode": "serialized_wave",
        "derived_from": "lane-b",
        "predecessor_head_sha": second,
        "explains": ["baseline_head_sha"],
    }
    _make_wave_fanout(tmp_path, overrides)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert any("never roots at an undeclared baseline" in d for d in _wave_details(result)), (
        result["errors"]
    )
    assert result["status"] == "fail"


def test_serialized_wave_retires_only_the_dimension_it_names(tmp_path: Path) -> None:
    """A chain that accounts only for the head leaves the dirty divergence standing."""
    first, second = _init_repo(tmp_path)
    overrides = _serialized_overrides(first, second)
    wave = overrides["lane-b"]["baseline_wave"]
    wave["explains"] = ["baseline_head_sha"]
    for key in ("dirty_predecessor", "dirty_growth", "dirty_attribution"):
        wave.pop(key, None)
    _make_wave_fanout(tmp_path, overrides)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert _wave_details(result) == []
    details = _shard_details(result)
    assert details == ["shard 'lane-b': baseline_dirty_snapshot mismatch"], details
    assert result["status"] == "fail"


def test_serialized_wave_fails_closed_when_a_head_does_not_resolve(
    tmp_path: Path,
) -> None:
    """An unverifiable claim must not buy a weaker verdict than declaring nothing."""
    first, second = _init_repo(tmp_path)
    overrides = _serialized_overrides(first, second)
    absent = "0" * 40
    overrides["lane-b"]["baseline_head_sha"] = absent
    _make_wave_fanout(tmp_path, overrides)
    result = RESOLVER.resolve_chain(tmp_path, TASK_ID)
    assert any("does not resolve to a commit" in d for d in _wave_details(result)), (
        result["errors"]
    )
    assert any("baseline_head_sha" in d for d in _shard_details(result))
    assert result["status"] == "fail"
