"""Unit tests for scripts/aggregate-dev-report.py"""

import importlib.util
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Load module (filename has hyphens — cannot use normal import)
# ---------------------------------------------------------------------------

_SCRIPT = Path(__file__).parent.parent / "scripts" / "aggregate-dev-report.py"

_spec = importlib.util.spec_from_file_location("aggregate_dev_report", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

main = _mod.main
_is_worker_for_task = _mod._is_worker_for_task
_validate_shards = _mod._validate_shards
_load_baseline_authority = _mod._load_baseline_authority
_migrate_baseline_reports = _mod._migrate_baseline_reports

_HOOK = Path(__file__).parent.parent / "hooks" / "pretool-aggregate-check.py"
_hook_spec = importlib.util.spec_from_file_location("pretool_aggregate_check", _HOOK)
_hook_mod = importlib.util.module_from_spec(_hook_spec)
_hook_spec.loader.exec_module(_hook_mod)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

BARE_TID = "20260101-120000"
OTHER_TID = "20260202-090000"
PREFIXED_TID = f"dev-{BARE_TID}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _authority_contract(
    task_id: str = BARE_TID,
    sha: str = "abc123def456",
    snapshot: str = "",
    *,
    origin: str = "pre_dispatch_native",
    creator: str | None = None,
) -> dict:
    cycle_id = _mod._bare_task_id(task_id)
    raw = snapshot.encode("utf-8")
    return {
        "version": 1,
        "cycle_id": cycle_id,
        "capture_phase": "pre_dev_fanout",
        "descriptor_origin": origin,
        "descriptor_created_by_task": creator or cycle_id,
        "head_sha": sha,
        "dirty_snapshot": {
            "path": f".claude/dev-registry/{cycle_id}/baseline-dirty.txt",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
            "line_count": len(raw.splitlines()),
            "encoding": "utf-8",
            "trailing_lf": raw.endswith(b"\n"),
            "state": "clean" if not raw else "dirty",
            "serialization": "git_status_porcelain_v1_raw_text",
        },
    }


def _install_authority(
    project_root: Path,
    task_id: str = BARE_TID,
    sha: str = "abc123def456",
    snapshot: str = "",
    *,
    origin: str = "pre_dispatch_native",
    creator: str | None = None,
) -> dict:
    contract = _authority_contract(
        task_id, sha, snapshot, origin=origin, creator=creator
    )
    registry = project_root / ".claude" / "dev-registry" / _mod._bare_task_id(task_id)
    registry.mkdir(parents=True, exist_ok=True)
    (registry / "baseline-dirty.txt").write_bytes(snapshot.encode("utf-8"))
    (registry / "baseline-authority.json").write_text(
        json.dumps(contract, indent=2) + "\n", encoding="utf-8"
    )
    return contract


def _good_shard(
    task_id: str = BARE_TID,
    sha: str = "abc123def456",
    snapshot: str = "",
) -> dict:
    contract = _authority_contract(task_id, sha, snapshot)
    return {
        "task_id": task_id,
        "baseline_contract": contract,
        "baseline_head_sha": sha,
        "baseline_dirty_snapshot": snapshot,
        "baseline_dirty_snapshot_sha256": contract["dirty_snapshot"]["sha256"],
        "dev": {
            "status": "completed",
            "tasks_completed": [],
            "scripts_created": [],
            "permissions_to_add": [],
            "files_modified": [f"src/{task_id}.py"],
            "files_created": [],
            "observed_preexisting": [],
        },
        "blocking_issues": [],
        "recommendations": [],
    }


def _verified_authority(
    task_id: str = BARE_TID, sha: str = "abc123def456", snapshot: str = ""
) -> dict:
    contract = _authority_contract(task_id, sha, snapshot)
    return {
        "cycle_id": _mod._bare_task_id(task_id),
        "snapshot_text": snapshot,
        "snapshot_raw": snapshot.encode("utf-8"),
        "contract": contract,
    }


def _write(dev_dir: Path, filename: str, data: dict) -> Path:
    p = dev_dir / filename
    p.write_text(json.dumps(data))
    return p


def _fanout_declaration(lanes: list[str]) -> dict:
    return {
        "version": 1,
        "shape": "requirement_fanout",
        "declared_lanes": lanes,
    }


def _good_lane(task_id: str, lane: str, *, history_paths: list[str] | None = None) -> dict:
    value = _good_shard(f"{task_id}-{lane}")
    value.update(
        {
            "request_id": f"{task_id}-{lane}",
            "task_id": f"{task_id}-{lane}",
            "parent_task_id": task_id,
            "lane": lane,
            "requirement_id": lane,
            "dev_report_path": f"docs/dev/dev-report-{task_id}-{lane}.json",
        }
    )
    if history_paths:
        value["iteration_reports"] = list(history_paths)
    return value


def _error_codes(discovery: dict) -> set[str]:
    return {item["code"] for item in discovery["errors"]}


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "docs" / "dev").mkdir(parents=True)
    _install_authority(tmp_path)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    return tmp_path


# ---------------------------------------------------------------------------
# AC1: 0 shards → exit 0, action=skipped
# ---------------------------------------------------------------------------

class TestZeroShards:
    def test_no_shards_returns_skipped(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        rc = main(["--task-id", BARE_TID])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["status"] == "ok"
        assert out["action"] == "skipped"

    def test_one_shard_also_skipped(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())

        rc = main(["--task-id", BARE_TID])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["action"] == "skipped"


# ---------------------------------------------------------------------------
# AC2: 2 shards (role-first) → exit 0, action=aggregated, canonical written
# ---------------------------------------------------------------------------

class TestRoleFirstNaming:
    def test_two_role_first_shards_aggregated(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard())

        rc = main(["--task-id", BARE_TID])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["action"] == "aggregated"

        canonical = dev_dir / f"dev-report-{BARE_TID}.json"
        assert canonical.exists()
        data = json.loads(canonical.read_text())
        assert "shard_provenance" not in data
        assert sorted(data["parallel_workers"]) == ["A", "B"]
        assert data["dev"]["status"] == "completed"

    def test_files_modified_union_across_role_first_shards(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        shard_a = _good_shard()
        shard_a["dev"]["files_modified"] = ["alpha.py"]
        shard_b = _good_shard()
        shard_b["dev"]["files_modified"] = ["beta.py"]
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", shard_a)
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", shard_b)

        main(["--task-id", BARE_TID])
        capsys.readouterr()

        canonical = dev_dir / f"dev-report-{BARE_TID}.json"
        data = json.loads(canonical.read_text())
        assert "alpha.py" in data["dev"]["files_modified"]
        assert "beta.py" in data["dev"]["files_modified"]


# ---------------------------------------------------------------------------
# AC3: 2 shards (task-first) → exit 0, action=aggregated
# ---------------------------------------------------------------------------

class TestTaskFirstNaming:
    def test_two_task_first_shards_aggregated(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-{BARE_TID}-worker1.json", _good_shard())
        _write(dev_dir, f"dev-report-{BARE_TID}-worker2.json", _good_shard())

        rc = main(["--task-id", BARE_TID])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["action"] == "aggregated"

    def test_non_worker_label_draft_not_counted(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())
        # "draft" is a NON_WORKER_LABEL — must not count as a second shard
        _write(dev_dir, f"dev-report-{BARE_TID}-draft.json", _good_shard())

        rc = main(["--task-id", BARE_TID])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["action"] == "skipped"


class TestPrefixedTaskIdNaming:
    def test_real_dev_lane_shards_aggregate_and_canonical_rerun_validates(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        for worker in ("a", "b", "c"):
            _write(
                dev_dir,
                f"dev-report-{PREFIXED_TID}-{worker}.json",
                _good_shard(f"{PREFIXED_TID}-{worker}"),
            )

        assert main(["--task-id", PREFIXED_TID]) == 0
        first = json.loads(capsys.readouterr().out)
        assert first["action"] == "aggregated"
        canonical = dev_dir / f"dev-report-{PREFIXED_TID}.json"
        assert canonical.exists()
        assert sorted(json.loads(canonical.read_text())["parallel_workers"]) == ["a", "b", "c"]

        assert main(["--task-id", PREFIXED_TID]) == 0
        rerun = json.loads(capsys.readouterr().out)
        assert rerun["action"] == "validated"

    def test_prefixed_shards_do_not_bleed_into_bare_task(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        for worker in ("a", "b", "c"):
            _write(dev_dir, f"dev-report-{PREFIXED_TID}-{worker}.json", _good_shard(PREFIXED_TID))
        assert main(["--task-id", BARE_TID]) == 0
        assert json.loads(capsys.readouterr().out)["action"] == "skipped"

    def test_script_and_hook_prefixed_classifiers_are_identical(self):
        assert _mod.PREFIXED_WORKER_RE.pattern == _hook_mod.PREFIXED_WORKER_RE.pattern
        assert _mod.PREFIXED_CANONICAL_RE.pattern == _hook_mod.PREFIXED_CANONICAL_RE.pattern
        assert _hook_mod._classify_filename(
            f"dev-report-{PREFIXED_TID}-a.json"
        ) == ("worker", PREFIXED_TID, "a")
        assert _hook_mod._classify_filename(
            f"dev-report-{PREFIXED_TID}.json"
        ) == ("canonical", PREFIXED_TID)

    def test_hook_scopes_real_lane_artifact_to_prefixed_cycle(self, project_dir: Path):
        dev_dir = project_dir / "docs" / "dev"
        for worker in ("a", "b", "c"):
            _write(dev_dir, f"dev-report-{PREFIXED_TID}-{worker}.json", _good_shard())
        workers, canonical = _hook_mod._scan_dev_dir(dev_dir)
        scope = _hook_mod._resolve_scope_task_ids(
            _hook_mod._collect_anchored_task_ids(
                f"Read context-{PREFIXED_TID}-a.json before QA"
            )
        )
        assert scope == [PREFIXED_TID]
        assert sorted(workers[PREFIXED_TID]) == ["a", "b", "c"]
        assert _hook_mod._collect_violations(workers, canonical, scope)

        _write(dev_dir, f"dev-report-{PREFIXED_TID}.json", _good_shard(PREFIXED_TID))
        workers, canonical = _hook_mod._scan_dev_dir(dev_dir)
        assert not _hook_mod._collect_violations(workers, canonical, scope)


# ---------------------------------------------------------------------------
# AC4: canonical present + 2 matching shards → action=validated
# ---------------------------------------------------------------------------

class TestCanonicalPresent:
    def test_matching_canonical_returns_validated(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard())

        assert main(["--task-id", BARE_TID]) == 0
        assert json.loads(capsys.readouterr().out)["action"] == "aggregated"

        rc = main(["--task-id", BARE_TID])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["action"] == "validated"

    def test_duplicate_worker_labels_are_rejected(self):
        errors = _validate_shards(
            [("a", _good_shard()), ("a", _good_shard())],
            BARE_TID,
            _verified_authority(),
        )
        assert any("duplicate worker labels" in error for error in errors)


class TestCanonicalContentFreshness:
    def test_legacy_canonical_without_baseline_contract_is_not_rewritten(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard())
        canonical_path = _write(
            dev_dir,
            f"dev-report-{BARE_TID}.json",
            {
                "task_id": BARE_TID,
                "parallel_workers": ["A", "B"],
                "baseline_head_sha": "abc123def456",
            },
        )
        before = canonical_path.read_bytes()

        assert main(["--task-id", BARE_TID]) == 1
        captured = capsys.readouterr()
        assert "BASELINE_SHARD_SCHEMA_INVALID" in captured.err
        assert canonical_path.read_bytes() == before

    def test_owned_files_only_change_keeps_canonical_validated(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        # Restored post-rollback narrower freshness: owned_files is NOT an
        # aggregate-output field, so a shard change confined to it must not
        # force a canonical rewrite (was provenance-driven before removal).
        dev_dir = project_dir / "docs" / "dev"
        shard_a = _good_shard()
        shard_a["owned_files"] = [{"path": "alpha.py", "sha256": "before"}]
        path_a = _write(dev_dir, f"dev-report-A-{BARE_TID}.json", shard_a)
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard())

        assert main(["--task-id", BARE_TID]) == 0
        assert json.loads(capsys.readouterr().out)["action"] == "aggregated"
        canonical_path = dev_dir / f"dev-report-{BARE_TID}.json"
        before = canonical_path.read_bytes()

        shard_a["owned_files"] = [{"path": "alpha.py", "sha256": "after"}]
        path_a.write_text(json.dumps(shard_a))
        assert main(["--task-id", BARE_TID]) == 0
        assert json.loads(capsys.readouterr().out)["action"] == "validated"
        assert canonical_path.read_bytes() == before

    def test_changed_r01_declared_paths_are_unioned_after_regeneration(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        r01 = _good_shard(f"{PREFIXED_TID}-r01")
        r01["dev"]["files_modified"] = ["hooks/pretool-workflow-gate.py"]
        r01_path = _write(dev_dir, f"dev-report-{PREFIXED_TID}-r01.json", r01)
        for worker in ("r02", "r03"):
            _write(
                dev_dir,
                f"dev-report-{PREFIXED_TID}-{worker}.json",
                _good_shard(f"{PREFIXED_TID}-{worker}"),
            )

        assert main(["--task-id", PREFIXED_TID]) == 0
        assert json.loads(capsys.readouterr().out)["action"] == "aggregated"

        current_r01_paths = [
            "tests/generated/dev-20260722-081544-r01/ac_harness.py",
            "docs/dev/dev-report-dev-20260722-081544-r01.json",
            "/root/.codex/claude-compat/isomorphism-report.json",
        ]
        r01["dev"]["files_modified"].extend(current_r01_paths)
        r01["owned_files"] = [{"path": path, "ownership": "current"} for path in current_r01_paths]
        r01_path.write_text(json.dumps(r01))

        assert main(["--task-id", PREFIXED_TID]) == 0
        refreshed = json.loads(capsys.readouterr().out)
        assert refreshed["action"] == "aggregated"
        canonical = json.loads(
            (dev_dir / f"dev-report-{PREFIXED_TID}.json").read_text()
        )
        assert set(current_r01_paths) <= set(canonical["dev"]["files_modified"])

    def test_dry_run_reports_stale_content_without_rewriting(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        shard_a = _good_shard()
        path_a = _write(dev_dir, f"dev-report-A-{BARE_TID}.json", shard_a)
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard())
        assert main(["--task-id", BARE_TID]) == 0
        capsys.readouterr()
        canonical_path = dev_dir / f"dev-report-{BARE_TID}.json"
        before = canonical_path.read_bytes()

        shard_a["dev"]["files_modified"].append("new-current-path.py")
        path_a.write_text(json.dumps(shard_a))
        assert main(["--task-id", BARE_TID, "--dry-run"]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["action"] == "skipped"
        assert "would be refreshed" in result["reason"]
        assert canonical_path.read_bytes() == before


# ---------------------------------------------------------------------------
# AC5: malformed shard JSON → exit 1
# ---------------------------------------------------------------------------

class TestMalformedShard:
    def test_malformed_json_shard_exits_1(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())
        (dev_dir / f"dev-report-B-{BARE_TID}.json").write_text("{broken: json")

        rc = main(["--task-id", BARE_TID])
        assert rc == 1


# ---------------------------------------------------------------------------
# AC6: task isolation — shards from OTHER_TID don't bleed into BARE_TID
# ---------------------------------------------------------------------------

class TestTaskIsolation:
    def test_shards_from_different_bare_tid_excluded(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        # Only one shard for BARE_TID
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())
        # Two shards for OTHER_TID — must not be picked up as shards for BARE_TID
        _write(dev_dir, f"dev-report-A-{OTHER_TID}.json", _good_shard(OTHER_TID))
        _write(dev_dir, f"dev-report-B-{OTHER_TID}.json", _good_shard(OTHER_TID))

        rc = main(["--task-id", BARE_TID])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["action"] == "skipped"

    def test_unit_is_worker_for_task_wrong_bare_tid(self):
        is_worker, _ = _is_worker_for_task(
            f"dev-report-A-{OTHER_TID}.json", BARE_TID, BARE_TID
        )
        assert not is_worker


# ---------------------------------------------------------------------------
# AC7: stale canonical (sha mismatch) → exit 1
# ---------------------------------------------------------------------------

class TestStaleCanonical:
    def test_stale_sha_in_canonical_exits_1(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard(sha="newsha"))
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard(sha="newsha"))
        stale_canonical = {
            "task_id": BARE_TID,
            "parallel_workers": ["A", "B"],
            "baseline_head_sha": "oldsha",
        }
        _write(dev_dir, f"dev-report-{BARE_TID}.json", stale_canonical)

        rc = main(["--task-id", BARE_TID])
        assert rc == 1

    def test_stale_workers_list_in_canonical_exits_1(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard())
        _write(dev_dir, f"dev-report-C-{BARE_TID}.json", _good_shard())
        stale_canonical = {
            "task_id": BARE_TID,
            "parallel_workers": ["A", "B"],  # missing C
            "baseline_head_sha": "abc123def456",
        }
        _write(dev_dir, f"dev-report-{BARE_TID}.json", stale_canonical)

        rc = main(["--task-id", BARE_TID])
        assert rc == 1


# ---------------------------------------------------------------------------
# AC8: shard with dev.status != "completed" → exit 1
# ---------------------------------------------------------------------------

class TestDevStatusNotCompleted:
    def test_failed_dev_status_exits_1(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        bad = _good_shard()
        bad["dev"]["status"] = "failed"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", bad)
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard())

        rc = main(["--task-id", BARE_TID])
        assert rc == 1

    def test_in_progress_dev_status_exits_1(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        bad = _good_shard()
        bad["dev"]["status"] = "in_progress"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", bad)
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard())

        rc = main(["--task-id", BARE_TID])
        assert rc == 1

    def test_unit_validate_shards_catches_non_completed(self):
        shards = [
            ("A", _good_shard()),
            ("B", {**_good_shard(), "dev": {"status": "failed"}}),
        ]
        errors = _validate_shards(shards, BARE_TID, _verified_authority())
        assert any("status" in e for e in errors)


# ---------------------------------------------------------------------------
# Bonus: baseline_head_sha mismatch across shards → exit 1
# ---------------------------------------------------------------------------

class TestShardSHAMismatch:
    def test_mismatched_baseline_sha_across_shards_exits_1(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard(sha="sha1111"))
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard(sha="sha9999"))

        rc = main(["--task-id", BARE_TID])
        assert rc == 1

    def test_unit_validate_shards_catches_sha_mismatch(self):
        shards = [
            ("A", _good_shard(sha="sha1111")),
            ("B", _good_shard(sha="sha9999")),
        ]
        errors = _validate_shards(shards, BARE_TID, _verified_authority())
        assert any("baseline_head_sha" in e for e in errors)


# ---------------------------------------------------------------------------
# Bonus: dry-run skips write
# ---------------------------------------------------------------------------

class TestDryRun:
    def test_dry_run_does_not_write_canonical(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard())

        rc = main(["--task-id", BARE_TID, "--dry-run"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["action"] == "skipped"
        assert not (dev_dir / f"dev-report-{BARE_TID}.json").exists()


# ---------------------------------------------------------------------------
# Retry-report naming: pin the MEASURED classifier truth table
# ---------------------------------------------------------------------------

class TestRetryReportNaming:
    """commands/dev.md once claimed the `iter<N>-` PREFIX excluded a retry
    report from the worker-shard set. Measured (task 20260803-150741): it does
    not. `PER_WORKER_ROLE_FIRST_RE` matches `dev-report-<role>-<bare-tid>.json`
    and its branch applies neither NON_WORKER_LABELS nor NON_WORKER_LABEL_RE,
    so the flat lane-less form IS a worker shard. The exclusion actually comes
    from a trailing `-<lane>`, a `dev-`prefixed task-id, or the non-recursive
    `iterations/` subdirectory.

    These are CHANGE-DETECTORS pinning current behaviour, NOT an endorsement of
    it. The role-first branch contradicts its own sibling branches and the hook
    docstring, and that asymmetry is a recorded OPEN defect, not a settled
    design. It is pinned rather than fixed because relaxing it would flip 6
    legacy project cycles from fail to pass, which is this project's defined
    signal of a weakened check; closing it properly needs a separate cycle that
    first establishes those 6 cycles' actual provenance.
    """

    def test_flat_lane_less_retry_is_a_worker_shard_in_both_copies(self):
        name = f"dev-report-iter3-{BARE_TID}.json"
        assert _is_worker_for_task(name, BARE_TID, BARE_TID) == (True, "iter3")
        assert _hook_mod._classify_filename(name) == ("worker", BARE_TID, "iter3")

    def test_documented_safe_forms_are_excluded_in_both_copies(self):
        for name in (
            f"dev-report-iter3-{BARE_TID}-lane.json",  # trailing lane segment
            f"dev-report-iter3-{PREFIXED_TID}.json",   # dev-prefixed task-id
        ):
            assert _is_worker_for_task(name, BARE_TID, PREFIXED_TID) == (False, None)
            assert _hook_mod._classify_filename(name) is None

    def test_role_first_branch_ignores_the_exclusion_set_in_both_copies(self):
        """Every documented non-worker label is promoted in role-first position."""
        for label in sorted(_mod.NON_WORKER_LABELS) + ["iter", "iter9", "retry", "attempt2"]:
            name = f"dev-report-{label}-{BARE_TID}.json"
            assert _is_worker_for_task(name, BARE_TID, BARE_TID) == (True, label)
            assert _hook_mod._classify_filename(name) == ("worker", BARE_TID, label)

    def test_iterations_subdirectory_is_outside_both_non_recursive_scans(
        self, project_dir: Path
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-{BARE_TID}.json", _good_shard())
        (dev_dir / "iterations").mkdir(parents=True, exist_ok=True)
        _write(dev_dir / "iterations", f"dev-report-iter3-{BARE_TID}.json", _good_shard())

        assert _mod._scan_shards(dev_dir, BARE_TID, BARE_TID) == []
        workers, _canonical = _hook_mod._scan_dev_dir(dev_dir)
        assert BARE_TID not in workers


# ---------------------------------------------------------------------------
# Declared active roots versus append-only history (task 20260804-065447-g)
# ---------------------------------------------------------------------------

LIVE_TASK = "20260804-065447"
LIVE_LANES = ["a", "b", "c", "d", "e", "f"]
LIVE_HISTORY_HASHES = {
    "dev-report-20260804-065447-d-iteration-1.json":
        "a610c67ab5d084562337ee2fba80f8d1f24cb4ea1e82c985bab8f83b737a80ff",
    "dev-report-20260804-065447-d-iteration-2.json":
        "8bee28667c0fef962dd3d3e54f270185b271740cac6d12da2036bca19f40fe6b",
    "dev-report-20260804-065447-e-iteration-2.json":
        "76f7bbc4669833f9b6b19020caa439160a06a1b61ac1b9cff77857b4af8fca82",
}


def _live_project() -> Path:
    return Path(os.environ.get("CODEX_HOME", "/root/.codex"))


def _copy_frozen_cycle(destination: Path) -> Path:
    live = _live_project()
    source = live / "docs" / "dev"
    target = destination / "docs" / "dev"
    target.mkdir(parents=True)
    names = [f"dev-report-{LIVE_TASK}-{lane}.json" for lane in LIVE_LANES]
    names.extend(LIVE_HISTORY_HASHES)
    for name in names:
        shutil.copyfile(source / name, target / name)
    source_registry = live / ".claude" / "dev-registry" / LIVE_TASK
    target_registry = destination / ".claude" / "dev-registry" / LIVE_TASK
    target_registry.mkdir(parents=True)
    for name in ("baseline-authority.json", "baseline-dirty.txt"):
        shutil.copyfile(source_registry / name, target_registry / name)
    return target


def test_current_cycle_declared_lanes_exclude_legacy_iteration_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    source = _live_project() / "docs" / "dev"
    for name, expected in LIVE_HISTORY_HASHES.items():
        assert hashlib.sha256((source / name).read_bytes()).hexdigest() == expected

    dev_dir = _copy_frozen_cycle(tmp_path)
    declaration = _fanout_declaration(LIVE_LANES)
    discovery = _mod._discover_dev_reports(dev_dir, LIVE_TASK, declaration)
    assert [label for label, _path in discovery["active"]] == LIVE_LANES
    assert [item["path"] for item in discovery["history"]] == [
        f"docs/dev/{name}" for name in sorted(LIVE_HISTORY_HASHES)
    ]
    assert discovery["errors"] == []

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    rc = main(
        [
            "--task-id", LIVE_TASK, "--dry-run", "--shape", "requirement_fanout",
            "--declared-lanes", ",".join(LIVE_LANES),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    for compound in ("d-iteration-1", "d-iteration-2", "e-iteration-2"):
        assert f"shard '{compound}'" not in captured.err
    for lane in ("b", "c", "f"):
        assert f"shard '{lane}': dev.status is 'completed_with_runtime_blockers'" in captured.err
    assert "BASELINE_" not in captured.err
    assert not (dev_dir / f"dev-report-{LIVE_TASK}.json").exists()


def test_declaration_driven_active_shard_set(
    tmp_path: Path,
) -> None:
    task_id = BARE_TID
    lanes = ["a", "b"]
    declaration = _fanout_declaration(lanes)

    complete = tmp_path / "complete" / "docs" / "dev"
    complete.mkdir(parents=True)
    for lane in lanes:
        _write(complete, f"dev-report-{task_id}-{lane}.json", _good_lane(task_id, lane))
    discovery = _mod._discover_dev_reports(complete, task_id, declaration)
    assert [label for label, _path in discovery["active"]] == lanes
    assert discovery["errors"] == []

    missing = tmp_path / "missing" / "docs" / "dev"
    missing.mkdir(parents=True)
    _write(missing, f"dev-report-{task_id}-a.json", _good_lane(task_id, "a"))
    history_name = f"dev-report-iter1-{task_id}-b.json"
    history = _good_lane(task_id, "b")
    history["dev_report_path"] = f"docs/dev/{history_name}"
    history[_mod.DEV_REPORT_ROLE_KEY] = _mod._expected_role(
        kind=_mod.ROLE_ITERATION_HISTORY,
        parent_task_id=task_id,
        lane="b",
        iteration=1,
    )
    _write(missing, history_name, history)
    assert "MISSING_DECLARED_SHARD" in _error_codes(
        _mod._discover_dev_reports(missing, task_id, declaration)
    )

    undeclared = tmp_path / "undeclared" / "docs" / "dev"
    shutil.copytree(complete, undeclared)
    hidden = _good_lane(task_id, "z")
    hidden[_mod.DEV_REPORT_ROLE_KEY] = {
        **_mod._expected_role(
            kind=_mod.ROLE_ITERATION_HISTORY,
            parent_task_id=task_id,
            lane="z",
            iteration=1,
        ),
        "aggregation_eligible": False,
    }
    _write(undeclared, f"dev-report-{task_id}-z.json", hidden)
    assert "UNDECLARED_SHARD" in _error_codes(
        _mod._discover_dev_reports(undeclared, task_id, declaration)
    )

    unsafe = tmp_path / "unsafe" / "docs" / "dev"
    unsafe.mkdir(parents=True)
    _write(unsafe, f"dev-report-{task_id}-a.json", _good_lane(task_id, "a"))
    (unsafe / f"dev-report-{task_id}-b.json").symlink_to(
        unsafe / f"dev-report-{task_id}-a.json"
    )
    codes = _error_codes(_mod._discover_dev_reports(unsafe, task_id, declaration))
    assert {"DUPLICATE_ACTIVE_SHARD", "DUPLICATE_OR_UNSAFE_DEV_REPORT"} <= codes

    foreign = f"dev-report-{OTHER_TID}-z.json"
    _write(complete, foreign, _good_lane(OTHER_TID, "z"))
    discovery = _mod._discover_dev_reports(complete, task_id, declaration)
    assert discovery["errors"] == []
    assert [label for label, _path in discovery["active"]] == lanes


def test_iteration_history_role_contract(tmp_path: Path) -> None:
    task_id = BARE_TID
    lanes = ["a", "b"]
    dev_dir = tmp_path / "docs" / "dev"
    dev_dir.mkdir(parents=True)
    history_name = f"dev-report-iter3-{task_id}-a.json"
    history_relative = f"docs/dev/{history_name}"
    for lane in lanes:
        root = _good_lane(
            task_id, lane, history_paths=[history_relative] if lane == "a" else None
        )
        root[_mod.DEV_REPORT_ROLE_KEY] = _mod._expected_role(
            kind=_mod.ROLE_ACTIVE_LANE_SHARD,
            parent_task_id=task_id,
            lane=lane,
            iteration=0,
        )
        _write(dev_dir, f"dev-report-{task_id}-{lane}.json", root)
    history = _good_lane(task_id, "a")
    history["dev_report_path"] = history_relative
    history[_mod.DEV_REPORT_ROLE_KEY] = _mod._expected_role(
        kind=_mod.ROLE_ITERATION_HISTORY,
        parent_task_id=task_id,
        lane="a",
        iteration=3,
    )
    history_path = _write(dev_dir, history_name, history)

    discovery = _mod._discover_dev_reports(
        dev_dir, task_id, _fanout_declaration(lanes)
    )
    assert discovery["errors"] == []
    assert [label for label, _path in discovery["active"]] == lanes
    assert discovery["history"] == [
        {
            "path": history_relative,
            "lane": "a",
            "iteration": 3,
            "profile": "versioned_iteration_history",
        }
    ]
    assert type(history[_mod.DEV_REPORT_ROLE_KEY]["iteration"]) is int

    broken = json.loads(history_path.read_text())
    broken[_mod.DEV_REPORT_ROLE_KEY]["iteration"] = "3"
    history_path.write_text(json.dumps(broken))
    assert "INVALID_HISTORY_METADATA" in _error_codes(
        _mod._discover_dev_reports(dev_dir, task_id, _fanout_declaration(lanes))
    )


def test_legacy_d_e_history_profiles(tmp_path: Path) -> None:
    dev_dir = _copy_frozen_cycle(tmp_path)
    declaration = _fanout_declaration(LIVE_LANES)
    discovery = _mod._discover_dev_reports(dev_dir, LIVE_TASK, declaration)
    profiles = {item["path"]: item["profile"] for item in discovery["history"]}
    assert profiles[f"docs/dev/dev-report-{LIVE_TASK}-d-iteration-1.json"] == (
        "legacy_suffix_identity_profile"
    )
    assert profiles[f"docs/dev/dev-report-{LIVE_TASK}-d-iteration-2.json"] == (
        "legacy_suffix_identity_profile"
    )
    assert profiles[f"docs/dev/dev-report-{LIVE_TASK}-e-iteration-2.json"] == (
        "legacy_lane_identity_with_iteration_field_profile"
    )

    mutated = dev_dir / f"dev-report-{LIVE_TASK}-d-iteration-1.json"
    document = json.loads(mutated.read_text())
    document["parent_task_id"] = LIVE_TASK
    mutated.write_text(json.dumps(document))
    broken = _mod._discover_dev_reports(dev_dir, LIVE_TASK, declaration)
    assert "INVALID_HISTORY_METADATA" in _error_codes(broken)
    assert not any(item["path"].endswith("d-iteration-1.json") for item in broken["history"])

    invalid_iteration = dev_dir / f"dev-report-{LIVE_TASK}-d-iteration-0.json"
    invalid_iteration.write_text(json.dumps(document))
    assert "INVALID_HISTORY_METADATA" in _error_codes(
        _mod._discover_dev_reports(dev_dir, LIVE_TASK, declaration)
    )


def test_history_fail_closed_matrix(tmp_path: Path) -> None:
    task_id = BARE_TID
    lanes = ["d", "e"]
    declaration = _fanout_declaration(lanes)

    def fresh(name: str) -> Path:
        dev_dir = tmp_path / name / "docs" / "dev"
        dev_dir.mkdir(parents=True)
        for lane in lanes:
            _write(dev_dir, f"dev-report-{task_id}-{lane}.json", _good_lane(task_id, lane))
        return dev_dir

    undeclared = fresh("undeclared")
    forged = _good_lane(task_id, "z")
    forged["aggregation_eligible"] = False
    _write(undeclared, f"dev-report-{task_id}-z.json", forged)
    assert "UNDECLARED_SHARD" in _error_codes(
        _mod._discover_dev_reports(undeclared, task_id, declaration)
    )

    malformed = fresh("malformed")
    (malformed / f"dev-report-iter1-{task_id}-d.json").write_text("{broken")
    assert "INVALID_HISTORY_METADATA" in _error_codes(
        _mod._discover_dev_reports(malformed, task_id, declaration)
    )

    malformed_iteration = fresh("malformed-iteration")
    (malformed_iteration / f"dev-report-iter0-{task_id}-d.json").write_text("{}")
    assert "INVALID_HISTORY_METADATA" in _error_codes(
        _mod._discover_dev_reports(malformed_iteration, task_id, declaration)
    )

    collision_lanes = ["d", "d-iteration-1"]
    collision = tmp_path / "collision" / "docs" / "dev"
    collision.mkdir(parents=True)
    for lane in collision_lanes:
        _write(collision, f"dev-report-{task_id}-{lane}.json", _good_lane(task_id, lane))
    assert "AMBIGUOUS_DEV_REPORT_ROLE" in _error_codes(
        _mod._discover_dev_reports(collision, task_id, _fanout_declaration(collision_lanes))
    )

    orphan = fresh("orphan")
    root = orphan / f"dev-report-{task_id}-d.json"
    root.unlink()
    history_name = f"dev-report-iter1-{task_id}-d.json"
    history = _good_lane(task_id, "d")
    history["dev_report_path"] = f"docs/dev/{history_name}"
    history[_mod.DEV_REPORT_ROLE_KEY] = _mod._expected_role(
        kind=_mod.ROLE_ITERATION_HISTORY,
        parent_task_id=task_id,
        lane="d",
        iteration=1,
    )
    _write(orphan, history_name, history)
    codes = _error_codes(_mod._discover_dev_reports(orphan, task_id, declaration))
    assert {"MISSING_DECLARED_SHARD", "HISTORY_WITHOUT_ACTIVE_SHARD"} <= codes

    unsafe = fresh("unsafe")
    alias = unsafe / f"dev-report-{task_id}-z.json"
    alias.symlink_to(unsafe / f"dev-report-{task_id}-d.json")
    assert "DUPLICATE_OR_UNSAFE_DEV_REPORT" in _error_codes(
        _mod._discover_dev_reports(unsafe, task_id, declaration)
    )


def test_failure_reason_subjects_are_real_active_lanes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _copy_frozen_cycle(tmp_path)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    argv = [
        "--task-id", LIVE_TASK, "--dry-run", "--shape", "requirement_fanout",
        "--declared-lanes", ",".join(LIVE_LANES),
    ]
    assert main(argv) == 1
    first = capsys.readouterr().err
    assert main(argv) == 1
    second = capsys.readouterr().err
    assert first == second
    subjects = re.findall(r"shard '([^']+)'", first)
    assert subjects
    assert set(subjects) <= set(LIVE_LANES)
    assert len(first.splitlines()) == len(set(first.splitlines()))


def test_no_gate_downgrade_or_runtime_credit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    root = _live_project()
    dev_dir = root / "docs" / "dev"
    parent = dev_dir / f"dev-report-{LIVE_TASK}.json"
    before = parent.read_bytes() if parent.exists() else None
    for lane in ("b", "c", "f"):
        report = json.loads((dev_dir / f"dev-report-{LIVE_TASK}-{lane}.json").read_text())
        assert report["dev"]["status"] == "completed_with_runtime_blockers"
    native = json.loads((root / "claude-compat/native-harness-status.json").read_text())
    release = native["release_gate"]
    assert release["lifecycle_blocker_count"] == 13
    assert release["full_claude_parity"] == "blocked"
    assert release["full_parity_blocker_count"] >= 16

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    rc = main(
        [
            "--task-id", LIVE_TASK, "--dry-run", "--shape", "requirement_fanout",
            "--declared-lanes", ",".join(LIVE_LANES),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    for lane in ("b", "c", "f"):
        assert f"shard '{lane}': dev.status" in captured.err
    assert "BASELINE_" not in captured.err
    assert (parent.read_bytes() if parent.exists() else None) == before


# ---------------------------------------------------------------------------
# Frozen cycle authority and baseline-only migration (lane h)
# ---------------------------------------------------------------------------

def _write_two_valid_shards(root: Path, task_id: str, *, snapshot: str = "") -> Path:
    dev_dir = root / "docs" / "dev"
    dev_dir.mkdir(parents=True, exist_ok=True)
    for lane in ("a", "b"):
        _write(
            dev_dir,
            f"dev-report-{task_id}-{lane}.json",
            _good_lane(task_id, lane) if not snapshot else {
                **_good_lane(task_id, lane),
                **{
                    "baseline_contract": _authority_contract(task_id, snapshot=snapshot),
                    "baseline_dirty_snapshot": snapshot,
                    "baseline_dirty_snapshot_sha256": hashlib.sha256(snapshot.encode()).hexdigest(),
                },
            },
        )
    return dev_dir


def test_dirty_and_true_clean_authorities_publish_exact_projections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    for name, snapshot, state in (("clean", "", "clean"), ("dirty", " M file\n", "dirty")):
        root = tmp_path / name
        _install_authority(root, snapshot=snapshot)
        dev_dir = _write_two_valid_shards(root, BARE_TID, snapshot=snapshot)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
        assert main(["--task-id", BARE_TID]) == 0
        capsys.readouterr()
        canonical = json.loads((dev_dir / f"dev-report-{BARE_TID}.json").read_text())
        assert canonical["baseline_dirty_snapshot"] == snapshot
        assert canonical["baseline_contract"]["dirty_snapshot"]["state"] == state
        assert canonical["baseline_dirty_snapshot_sha256"] == hashlib.sha256(
            snapshot.encode()
        ).hexdigest()


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("missing_descriptor", "BASELINE_AUTHORITY_MISSING"),
        ("wrong_cycle", "BASELINE_CYCLE_MISMATCH"),
        ("path_escape", "BASELINE_PATH_INVALID"),
        ("digest", "BASELINE_SNAPSHOT_DIGEST_MISMATCH"),
        ("size", "BASELINE_SNAPSHOT_METADATA_MISMATCH"),
    ],
)
def test_authority_failure_matrix_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    mutation: str,
    code: str,
) -> None:
    root = tmp_path / mutation
    contract = _install_authority(root, snapshot=" M file\n")
    dev_dir = _write_two_valid_shards(root, BARE_TID, snapshot=" M file\n")
    descriptor = root / ".claude" / "dev-registry" / BARE_TID / "baseline-authority.json"
    if mutation == "missing_descriptor":
        descriptor.unlink()
    else:
        if mutation == "wrong_cycle":
            contract["cycle_id"] = OTHER_TID
        elif mutation == "path_escape":
            contract["dirty_snapshot"]["path"] = "../../outside"
        elif mutation == "digest":
            contract["dirty_snapshot"]["sha256"] = "0" * 64
        elif mutation == "size":
            contract["dirty_snapshot"]["size_bytes"] += 1
        descriptor.write_text(json.dumps(contract))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    assert main(["--task-id", BARE_TID]) == 1
    captured = capsys.readouterr()
    assert code in captured.err
    assert not (dev_dir / f"dev-report-{BARE_TID}.json").exists()


def test_symlink_nonregular_and_changed_during_read_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    symlink_root = tmp_path / "symlink"
    _install_authority(symlink_root)
    registry = symlink_root / ".claude" / "dev-registry" / BARE_TID
    snapshot = registry / "baseline-dirty.txt"
    target = registry / "target.txt"
    snapshot.rename(target)
    snapshot.symlink_to(target)
    _authority, errors = _load_baseline_authority(symlink_root, BARE_TID)
    assert any("BASELINE_FILE_TYPE_INVALID" in error for error in errors)

    race_root = tmp_path / "race"
    _install_authority(race_root)
    original = _mod._stable_regular_read

    def report_race(path: Path):
        if path.name == "baseline-dirty.txt":
            return None, "changed"
        return original(path)

    monkeypatch.setattr(_mod, "_stable_regular_read", report_race)
    _authority, errors = _load_baseline_authority(race_root, BARE_TID)
    assert any("BASELINE_CHANGED_DURING_READ" in error for error in errors)


@pytest.mark.parametrize("legacy_form", ["missing", "null", "path", "dirty_empty"])
def test_legacy_or_ambiguous_shard_forms_never_become_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    legacy_form: str,
) -> None:
    root = tmp_path / legacy_form
    snapshot = " M file\n"
    _install_authority(root, snapshot=snapshot)
    dev_dir = _write_two_valid_shards(root, BARE_TID, snapshot=snapshot)
    for lane in ("a", "b"):  # even unanimous wrong shards cannot forge authority
        path = dev_dir / f"dev-report-{BARE_TID}-{lane}.json"
        document = json.loads(path.read_text())
        if legacy_form == "missing":
            document.pop("baseline_contract")
        elif legacy_form == "null":
            document["baseline_contract"] = None
        elif legacy_form == "path":
            document["baseline_dirty_snapshot"] = document["baseline_contract"]["dirty_snapshot"]["path"]
        else:
            document["baseline_dirty_snapshot"] = ""
        path.write_text(json.dumps(document))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    assert main(["--task-id", BARE_TID]) == 1
    captured = capsys.readouterr()
    assert "BASELINE_SHARD_" in captured.err
    assert not (dev_dir / f"dev-report-{BARE_TID}.json").exists()


def test_existing_canonical_is_byte_identical_on_baseline_or_status_failure(
    project_dir: Path, capsys: pytest.CaptureFixture
) -> None:
    dev_dir = project_dir / "docs" / "dev"
    paths = []
    for lane in ("a", "b"):
        paths.append(_write(dev_dir, f"dev-report-{BARE_TID}-{lane}.json", _good_lane(BARE_TID, lane)))
    assert main(["--task-id", BARE_TID]) == 0
    capsys.readouterr()
    canonical = dev_dir / f"dev-report-{BARE_TID}.json"
    before = canonical.read_bytes()
    bad = json.loads(paths[0].read_text())
    bad["baseline_dirty_snapshot_sha256"] = "f" * 64
    bad["dev"]["status"] = "completed_with_runtime_blockers"
    paths[0].write_text(json.dumps(bad))
    assert main(["--task-id", BARE_TID]) == 1
    captured = capsys.readouterr()
    assert "BASELINE_SHARD_MISMATCH" in captured.err
    assert "SHARD_STATUS_NOT_COMPLETED" in captured.err
    assert canonical.read_bytes() == before


def test_current_tree_changes_do_not_participate_in_baseline_identity(
    tmp_path: Path
) -> None:
    _install_authority(tmp_path, snapshot=" M frozen\n")
    before, errors = _load_baseline_authority(tmp_path, BARE_TID)
    assert errors == []
    (tmp_path / "unrelated-post-development-file").write_text("changed")
    after, errors = _load_baseline_authority(tmp_path, BARE_TID)
    assert errors == []
    assert _mod._baseline_projections(before) == _mod._baseline_projections(after)


def test_exact_preimage_migration_preserves_nonbaseline_and_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = " M frozen\n"
    _install_authority(tmp_path, snapshot=snapshot)
    dev_dir = tmp_path / "docs" / "dev"
    dev_dir.mkdir(parents=True)
    plan = {}
    originals = {}
    forms = {
        "a": {"baseline_dirty_snapshot": snapshot},
        "b": {"baseline_dirty_snapshot": ""},
        "c": {"baseline_dirty_snapshot": ".claude/dev-registry/path"},
        "d": {},
    }
    for lane, baseline in forms.items():
        document = {
            "task_id": f"{BARE_TID}-{lane}",
            "dev": {"status": "completed", "failure_history": [lane]},
            "blocking_issues": [{"lane": lane}],
            "baseline_head_sha": "abc123def456",
            **baseline,
        }
        path = _write(dev_dir, f"dev-report-{BARE_TID}-{lane}.json", document)
        originals[lane] = path.read_bytes()
        plan[lane] = {
            "sha256": hashlib.sha256(originals[lane]).hexdigest(),
            "legacy": lane,
            "dev_status": "completed",
        }

    real_replace = _mod._replace_path
    calls = {"count": 0}

    def fail_second(source: Path, destination: Path) -> None:
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("injected migration failure")
        real_replace(source, destination)

    monkeypatch.setattr(_mod, "_replace_path", fail_second)
    with pytest.raises(OSError, match="injected migration failure"):
        _migrate_baseline_reports(tmp_path, BARE_TID, "rollback", plan)
    for lane in forms:
        assert (dev_dir / f"dev-report-{BARE_TID}-{lane}.json").read_bytes() == originals[lane]
    assert not (
        tmp_path
        / ".claude/dev-registry"
        / BARE_TID
        / "baseline-migrations/rollback/migration-ledger.jsonl"
    ).exists()

    monkeypatch.setattr(_mod, "_replace_path", real_replace)
    result = _migrate_baseline_reports(tmp_path, BARE_TID, "success", plan)
    assert result["current_tree_read"] is False
    rows = [
        json.loads(line)
        for line in (
            tmp_path / result["ledger_path"]
        ).read_text().splitlines()
    ]
    assert len(rows) == 4
    for row in rows:
        lane = row["lane"]
        original = json.loads(originals[lane])
        migrated = json.loads((dev_dir / f"dev-report-{BARE_TID}-{lane}.json").read_text())
        assert _mod._without_baseline_fields(original) == _mod._without_baseline_fields(migrated)
        assert migrated["baseline_dirty_snapshot"] == snapshot
        assert row["current_tree_read"] is False


def _single_active_root_plan(project_root: Path) -> tuple[Path, bytes, dict]:
    snapshot = " M frozen\n"
    _install_authority(project_root, snapshot=snapshot, creator=f"{BARE_TID}-h")
    dev_dir = project_root / "docs" / "dev"
    dev_dir.mkdir(parents=True)
    path = dev_dir / f"dev-report-{BARE_TID}-g.json"
    document = {
        "request_id": f"{BARE_TID}-g",
        "task_id": f"{BARE_TID}-g",
        "parent_task_id": BARE_TID,
        "lane": "g",
        "dev_report_role": {
            "version": 1,
            "kind": "active_lane_shard",
            "aggregation_eligible": True,
            "parent_task_id": BARE_TID,
            "lane": "g",
            "iteration": 0,
            "canonical_shard_path": f"docs/dev/dev-report-{BARE_TID}-g.json",
        },
        "baseline_head_sha": "abc123def456",
        "baseline_dirty_snapshot": snapshot,
        "dev": {"status": "completed", "failure_history": ["kept"]},
        "blocking_issues": [],
    }
    raw = json.dumps(document, indent=2).encode() + b"\n"
    path.write_bytes(raw)
    path.chmod(0o644)
    plan = {
        "g": {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
            "mode_octal": "0644",
            "trailing_lf": True,
            "legacy": "inline_exact_missing_structured_contract_and_digest",
            "dev_status": "completed",
            "require_active_lane_identity": True,
            "existing_baseline_values": {
                "baseline_head_sha": "abc123def456",
                "baseline_dirty_snapshot": snapshot,
            },
            "changed_json_pointers": [
                "/baseline_contract",
                "/baseline_dirty_snapshot_sha256",
            ],
        }
    }
    return path, raw, plan


def test_single_target_migration_enforces_two_pointer_delta_and_metadata(
    tmp_path: Path,
) -> None:
    path, raw, plan = _single_active_root_plan(tmp_path)
    original = json.loads(raw)

    result = _migrate_baseline_reports(tmp_path, BARE_TID, f"{BARE_TID}-i", plan)
    migrated = json.loads(path.read_text())
    rows = [
        json.loads(line)
        for line in (tmp_path / result["ledger_path"]).read_text().splitlines()
    ]

    assert len(rows) == 1
    assert rows[0]["changed_json_pointers"] == [
        "/baseline_contract",
        "/baseline_dirty_snapshot_sha256",
    ]
    assert _mod._without_baseline_fields(original) == _mod._without_baseline_fields(migrated)
    assert migrated["baseline_head_sha"] == original["baseline_head_sha"]
    assert migrated["baseline_dirty_snapshot"] == original["baseline_dirty_snapshot"]
    assert migrated["dev_report_role"] == original["dev_report_role"]
    assert migrated["dev"]["status"] == "completed"
    assert path.stat().st_mode & 0o777 == 0o644
    with pytest.raises(ValueError, match="ledger already exists"):
        _migrate_baseline_reports(tmp_path, BARE_TID, f"{BARE_TID}-i", plan)


def test_single_target_migration_rejects_stale_preimage_before_publication(
    tmp_path: Path,
) -> None:
    path, raw, plan = _single_active_root_plan(tmp_path)
    stale = raw + b" "
    path.write_bytes(stale)
    migration_root = (
        tmp_path / ".claude" / "dev-registry" / BARE_TID
        / "baseline-migrations" / f"{BARE_TID}-i"
    )

    with pytest.raises(ValueError, match="preimage sha256"):
        _migrate_baseline_reports(tmp_path, BARE_TID, f"{BARE_TID}-i", plan)

    assert path.read_bytes() == stale
    assert not (migration_root / "migration-ledger.jsonl").exists()
    assert not (migration_root / "preimages").exists()


@pytest.mark.parametrize("drift", ["mode", "active_role"])
def test_single_target_migration_rejects_bound_metadata_drift(
    tmp_path: Path, drift: str
) -> None:
    path, _raw, plan = _single_active_root_plan(tmp_path)
    if drift == "mode":
        path.chmod(0o600)
        expected = "preimage mode"
    else:
        document = json.loads(path.read_text())
        document["dev_report_role"]["kind"] = "iteration_history"
        rebound = json.dumps(document, indent=2).encode() + b"\n"
        path.write_bytes(rebound)
        plan["g"]["sha256"] = hashlib.sha256(rebound).hexdigest()
        plan["g"]["size_bytes"] = len(rebound)
        expected = "active-root identity or role drifted"

    with pytest.raises(ValueError, match=expected):
        _migrate_baseline_reports(tmp_path, BARE_TID, f"{BARE_TID}-i", plan)

    ledger = (
        tmp_path / ".claude" / "dev-registry" / BARE_TID
        / "baseline-migrations" / f"{BARE_TID}-i" / "migration-ledger.jsonl"
    )
    assert not ledger.exists()


@pytest.mark.parametrize(
    "failure_point",
    [
        "target_replace",
        "ledger_create",
        "ledger_write",
        "ledger_fsync",
        "target_postverify",
        "authority_postverify",
    ],
)
def test_single_target_migration_rolls_back_every_publication_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    path, raw, plan = _single_active_root_plan(tmp_path)
    original_open = _mod.os.open
    original_stable_read = _mod._stable_regular_read
    original_load_authority = _mod._load_baseline_authority
    target_reads = {"count": 0}
    authority_loads = {"count": 0}

    if failure_point == "target_replace":
        monkeypatch.setattr(
            _mod,
            "_replace_path",
            lambda _source, _destination: (_ for _ in ()).throw(OSError("target replace")),
        )
    elif failure_point == "ledger_create":
        def fail_ledger_open(name, flags, mode=0o777):
            if str(name).endswith("migration-ledger.jsonl"):
                raise OSError("ledger create")
            return original_open(name, flags, mode)
        monkeypatch.setattr(_mod.os, "open", fail_ledger_open)
    elif failure_point == "ledger_write":
        monkeypatch.setattr(
            _mod,
            "_write_migration_ledger",
            lambda _handle, _payload: (_ for _ in ()).throw(OSError("ledger write")),
        )
    elif failure_point == "ledger_fsync":
        monkeypatch.setattr(
            _mod,
            "_fsync_migration_ledger",
            lambda _handle: (_ for _ in ()).throw(OSError("ledger fsync")),
        )
    elif failure_point == "target_postverify":
        def fail_target_postverify(candidate: Path):
            if candidate == path:
                target_reads["count"] += 1
                if target_reads["count"] == 2:
                    return None, "changed"
            return original_stable_read(candidate)
        monkeypatch.setattr(_mod, "_stable_regular_read", fail_target_postverify)
    else:
        def fail_authority_postverify(project_root: Path, task_id: str):
            authority_loads["count"] += 1
            if authority_loads["count"] == 2:
                return None, ["injected authority postverify"]
            return original_load_authority(project_root, task_id)
        monkeypatch.setattr(_mod, "_load_baseline_authority", fail_authority_postverify)

    with pytest.raises((OSError, RuntimeError)):
        _migrate_baseline_reports(tmp_path, BARE_TID, f"{BARE_TID}-i", plan)

    ledger = (
        tmp_path / ".claude" / "dev-registry" / BARE_TID
        / "baseline-migrations" / f"{BARE_TID}-i" / "migration-ledger.jsonl"
    )
    assert path.read_bytes() == raw
    assert path.stat().st_mode & 0o777 == 0o644
    assert not ledger.exists()
