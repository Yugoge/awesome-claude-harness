"""Unit tests for scripts/aggregate-dev-report.py"""

import importlib.util
import json
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

def _good_shard(task_id: str = BARE_TID, sha: str = "abc123def456") -> dict:
    return {
        "task_id": task_id,
        "baseline_head_sha": sha,
        "baseline_dirty_snapshot": "",
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


def _write(dev_dir: Path, filename: str, data: dict) -> Path:
    p = dev_dir / filename
    p.write_text(json.dumps(data))
    return p


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "docs" / "dev").mkdir(parents=True)
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
            [("a", _good_shard()), ("a", _good_shard())], BARE_TID
        )
        assert any("duplicate worker labels" in error for error in errors)


class TestCanonicalContentFreshness:
    def test_legacy_canonical_without_content_provenance_is_regenerated(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard())
        _write(
            dev_dir,
            f"dev-report-{BARE_TID}.json",
            {
                "task_id": BARE_TID,
                "parallel_workers": ["A", "B"],
                "baseline_head_sha": "abc123def456",
            },
        )

        assert main(["--task-id", BARE_TID]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["action"] == "aggregated"
        canonical = json.loads((dev_dir / f"dev-report-{BARE_TID}.json").read_text())
        assert canonical["shard_provenance"]["algorithm"] == "sha256-canonical-json-v1"

    def test_same_workers_and_baseline_refresh_when_owned_content_changes(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        shard_a = _good_shard()
        shard_a["owned_files"] = [{"path": "alpha.py", "sha256": "before"}]
        path_a = _write(dev_dir, f"dev-report-A-{BARE_TID}.json", shard_a)
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard())

        assert main(["--task-id", BARE_TID]) == 0
        assert json.loads(capsys.readouterr().out)["action"] == "aggregated"
        canonical_path = dev_dir / f"dev-report-{BARE_TID}.json"
        before = json.loads(canonical_path.read_text())

        shard_a["owned_files"] = [{"path": "alpha.py", "sha256": "after"}]
        path_a.write_text(json.dumps(shard_a))
        assert main(["--task-id", BARE_TID]) == 0
        refreshed = json.loads(capsys.readouterr().out)
        assert refreshed["action"] == "aggregated"
        assert "Refreshed stale canonical" in refreshed["reason"]

        after = json.loads(canonical_path.read_text())
        assert after["parallel_workers"] == before["parallel_workers"] == ["A", "B"]
        assert after["baseline_head_sha"] == before["baseline_head_sha"]
        assert after["shard_provenance"] != before["shard_provenance"]
        assert main(["--task-id", BARE_TID]) == 0
        assert json.loads(capsys.readouterr().out)["action"] == "validated"

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
        errors = _validate_shards(shards, BARE_TID)
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
        errors = _validate_shards(shards, BARE_TID)
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
