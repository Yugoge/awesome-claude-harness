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
_build_aggregate = _mod._build_aggregate

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

    # -----------------------------------------------------------------------
    # REVISED IN PLACE — task 20260904-161820 (lane R21).
    #
    # This test was `test_stale_workers_list_in_canonical_exits_1` and asserted
    # `rc == 1` on the growth fixture below. It was GREEN. It is now inverted to
    # `rc == 0`, and the direction of that flip must be stated honestly rather
    # than described as a narrowing:
    #
    # (i)   THE AMENDED PREDICATE ACCEPTS STRICTLY MORE, so this test was
    #       flipped in the LOOSENING direction. The refusal condition went from
    #       `sorted(existing) != sorted(expected)` to
    #       `not set(existing) <= set(expected)`. Equal sorted lists imply equal
    #       sets, so new-refuse implies old-refuse and the accepted set can only
    #       grow. It grows by exactly three shapes: worker-set GROWTH (this
    #       test), a canonical with no `parallel_workers` key, and a canonical
    #       with duplicate entries. Nothing that was accepted is now refused.
    #       (A narrower FIRING condition is a WIDER acceptance set; calling this
    #       change "narrowing" would conceal which way it runs.)
    #
    # (ii)  THE INVARIANT THAT NONETHELESS SURVIVES, EXACTLY AND NOT
    #       APPROXIMATELY: no worker named by the canonical is ever dropped or
    #       retargeted. The accepted set grows, but the subset of accepted
    #       inputs that violate that invariant stays EMPTY — a canonical naming
    #       a worker with no shard on disk is still refused. Its standing
    #       negative controls are the sibling tests added directly below:
    #       `test_shrink_workers_list_in_canonical_exits_1` (canonical names a
    #       worker 'Z' that has no shard) and
    #       `test_disjoint_workers_list_in_canonical_exits_1` (canonical names
    #       only workers that have no shard). Deleting the guard outright —
    #       the naive alternative — would admit both of those and additionally
    #       discard the baseline-sha protection; that is what a genuinely
    #       weakened guard would look like, and it is not what this is.
    #
    # (iii) THE DEFINITIONAL CHANGE IS AUTHORISED, not inferred: the user
    #       required that a stale canonical be refreshable when the shard set is
    #       complete. The old assertion encoded a STRICTER definition of "stale"
    #       than that requirement; revising it moves the definition to the
    #       authorised one. `commands/close.md:186-188` independently documents
    #       refresh from current lane reports as writer behaviour. Completeness
    #       is still enforced upstream by _validate_shards (>=2 shards, no
    #       duplicate labels, matching task-id, dev.status == completed,
    #       agreeing baseline_head_sha and dirty snapshot), which this change
    #       does not touch.
    # -----------------------------------------------------------------------
    def test_growth_workers_list_in_canonical_is_refreshed(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard())
        _write(dev_dir, f"dev-report-C-{BARE_TID}.json", _good_shard())
        stale_canonical = {
            "task_id": BARE_TID,
            "parallel_workers": ["A", "B"],  # missing C — a strict SUBSET
            "baseline_head_sha": "abc123def456",
        }
        canonical_path = _write(dev_dir, f"dev-report-{BARE_TID}.json", stale_canonical)

        rc = main(["--task-id", BARE_TID])
        assert rc == 0
        assert json.loads(capsys.readouterr().out)["action"] == "aggregated"
        assert json.loads(canonical_path.read_text())["parallel_workers"] == [
            "A",
            "B",
            "C",
        ]

    def test_shrink_workers_list_in_canonical_exits_1(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        """Negative control for the flip above: a canonical naming a worker with
        no shard on disk must stay refused, so a refresh can never silently
        shrink the lane set and report the loss as success."""
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard())
        canonical = {
            "task_id": BARE_TID,
            "parallel_workers": ["A", "B", "Z"],  # Z has no shard
            "baseline_head_sha": "abc123def456",
        }
        canonical_path = _write(dev_dir, f"dev-report-{BARE_TID}.json", canonical)
        before = canonical_path.read_bytes()

        assert main(["--task-id", BARE_TID]) == 1
        assert canonical_path.read_bytes() == before

    def test_disjoint_workers_list_in_canonical_exits_1(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        """Neither declared worker has a shard: refreshing would retarget both."""
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard())
        canonical = {
            "task_id": BARE_TID,
            "parallel_workers": ["X", "Y"],
            "baseline_head_sha": "abc123def456",
        }
        canonical_path = _write(dev_dir, f"dev-report-{BARE_TID}.json", canonical)
        before = canonical_path.read_bytes()

        assert main(["--task-id", BARE_TID]) == 1
        assert canonical_path.read_bytes() == before

    def test_message_names_only_worker_clause_when_only_worker_set_differs(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        """The refusal message must name only the comparison that actually
        failed. The clause is isolated from the surrounding path text so the
        assertion cannot be satisfied by the tmp-dir name."""
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard())
        canonical = {
            "task_id": BARE_TID,
            "parallel_workers": ["A", "B", "Z"],
            "baseline_head_sha": "abc123def456",  # equal — must NOT be reported
        }
        _write(dev_dir, f"dev-report-{BARE_TID}.json", canonical)

        assert main(["--task-id", BARE_TID]) == 1
        clause = capsys.readouterr().err.split("is stale: ", 1)[1]
        assert "workers" in clause
        assert "baseline_sha" not in clause

    def test_message_names_only_digest_clause_when_only_digest_differs(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard(sha="newsha"))
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard(sha="newsha"))
        canonical = {
            "task_id": BARE_TID,
            "parallel_workers": ["A", "B"],  # equal — must NOT be reported
            "baseline_head_sha": "oldsha",
        }
        _write(dev_dir, f"dev-report-{BARE_TID}.json", canonical)

        assert main(["--task-id", BARE_TID]) == 1
        clause = capsys.readouterr().err.split("is stale: ", 1)[1]
        assert "baseline_sha" in clause
        assert "workers" not in clause

    def test_growth_dry_run_reports_would_be_refreshed_without_writing(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard())
        _write(dev_dir, f"dev-report-C-{BARE_TID}.json", _good_shard())
        canonical = {
            "task_id": BARE_TID,
            "parallel_workers": ["A", "B"],
            "baseline_head_sha": "abc123def456",
        }
        canonical_path = _write(dev_dir, f"dev-report-{BARE_TID}.json", canonical)
        before = canonical_path.read_bytes()

        assert main(["--task-id", BARE_TID, "--dry-run"]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["action"] == "skipped"
        assert "would be refreshed" in result["reason"]
        assert canonical_path.read_bytes() == before

    def test_lane_losing_negatives_still_exit_1_under_dry_run(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        """Validating a genuinely inconsistent set means reporting it, so
        --dry-run must not soften the shrink or digest-divergence refusals."""
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard())
        canonical_path = dev_dir / f"dev-report-{BARE_TID}.json"

        _write(
            dev_dir,
            f"dev-report-{BARE_TID}.json",
            {
                "task_id": BARE_TID,
                "parallel_workers": ["A", "B", "Z"],
                "baseline_head_sha": "abc123def456",
            },
        )
        before = canonical_path.read_bytes()
        assert main(["--task-id", BARE_TID, "--dry-run"]) == 1
        assert canonical_path.read_bytes() == before

        _write(
            dev_dir,
            f"dev-report-{BARE_TID}.json",
            {
                "task_id": BARE_TID,
                "parallel_workers": ["A", "B"],
                "baseline_head_sha": "oldsha",
            },
        )
        before = canonical_path.read_bytes()
        assert main(["--task-id", BARE_TID, "--dry-run"]) == 1
        assert canonical_path.read_bytes() == before

    def test_upstream_shard_validation_negatives_exit_1_under_dry_run(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        """_validate_shards runs strictly before the narrowed block, so the
        shards-disagree and not-completed refusals are unaffected by it."""
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard(sha="shaA"))
        path_b = _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard(sha="shaB"))
        assert main(["--task-id", BARE_TID, "--dry-run"]) == 1

        not_completed = _good_shard(sha="shaA")  # digests now agree; only status is bad
        not_completed["dev"]["status"] = "in_progress"
        path_b.write_text(json.dumps(not_completed))
        assert main(["--task-id", BARE_TID, "--dry-run"]) == 1

    def test_canonical_missing_parallel_workers_key_is_repaired(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        """An absent key normalises to [], which is a subset of anything, so
        nothing can be lost by rewriting it. Pinned so the repair is deliberate
        rather than incidental."""
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard())
        canonical_path = _write(
            dev_dir,
            f"dev-report-{BARE_TID}.json",
            {"task_id": BARE_TID, "baseline_head_sha": "abc123def456"},
        )

        assert main(["--task-id", BARE_TID]) == 0
        assert json.loads(capsys.readouterr().out)["action"] == "aggregated"
        assert json.loads(canonical_path.read_text())["parallel_workers"] == ["A", "B"]

    def test_duplicate_workers_in_canonical_is_repaired(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        """REVISED IN PLACE -- task dev-20260914-035503 (R29, Layer-Escalation
        Review item H / AC-09). This test used to assert {"A","A"} is
        silently repaired to {"A","B"} on the theory that a duplicate entry
        in a hand-crafted canonical's parallel_workers is noise, never real
        evidence. Item H replaces the plain set() containment check here
        with the SAME Counter-based multiset containment the sibling
        `if existing_is_blocked:` branch already used for a 'blocked'
        predecessor, applied unconditionally to every predecessor status --
        so this check can no longer distinguish "duplicate as noise" from
        "duplicate as genuine evidence of two real shard files, one later
        deleted", exactly the ambiguity AC-09's own required test
        (test_recovery_read_workers_subset_check_is_multiset_correct_for_completed_predecessor)
        exists to close. A canonical recording an "A" occurrence twice while
        only one "A" shard currently exists is therefore now REFUSED, not
        silently repaired -- the same directional choice already made for a
        'blocked' predecessor, extended here for symmetry (item H)."""
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard())
        canonical_path = _write(
            dev_dir,
            f"dev-report-{BARE_TID}.json",
            {
                "task_id": BARE_TID,
                "parallel_workers": ["A", "A"],
                "baseline_head_sha": "abc123def456",
            },
        )
        before = canonical_path.read_bytes()

        assert main(["--task-id", BARE_TID]) == 1
        assert canonical_path.read_bytes() == before


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


# ---------------------------------------------------------------------------
# Disclosed-exception vocabulary (ticket 20260911-011232 M5): a shard's
# dev.status=='needs_review' is a disclosed, narrower sibling of 'completed'
# -- accepted by _validate_shards, and propagated into a synthesized
# dev.status_rationale on the canonical by _build_aggregate.  'blocked' (and
# any other status) must keep failing exactly as before (AC-6 mirrored here).
# ---------------------------------------------------------------------------

def _needs_review_shard(
    task_id: str = BARE_TID,
    *,
    classification: str = "pending_commit_handoff",
    blocked_by: str = "commit verb forbidden to dev subagent",
    forbidden_action: str = "agents/dev.md No Band-Aid Rule item 7",
) -> dict:
    shard = _good_shard(task_id=task_id)
    shard["dev"]["status"] = "needs_review"
    shard["dev"]["status_rationale"] = {
        "classification": classification,
        "blocked_by": blocked_by,
        "forbidden_action": forbidden_action,
    }
    shard["blocking_issues"] = ["awaiting /commit hand-off"]
    return shard


class TestNeedsReviewShard:
    def test_unit_validate_shards_accepts_needs_review(self):
        shards = [("A", _good_shard()), ("B", _needs_review_shard())]
        errors = _validate_shards(shards, BARE_TID)
        assert errors == []

    def test_unit_validate_shards_still_rejects_blocked(self):
        shards = [
            ("A", _good_shard()),
            ("B", {**_good_shard(), "dev": {"status": "blocked"}}),
        ]
        errors = _validate_shards(shards, BARE_TID)
        assert any("status" in e and "'blocked'" in e for e in errors)

    def test_needs_review_shard_no_longer_blocks_aggregation_exit_code(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        # AC-P3 / M5: this is the exact wall the ticket's motivating example
        # was stuck against -- aggregate-dev-report.py used to exit 1 here.
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _needs_review_shard())

        rc = main(["--task-id", BARE_TID])
        captured = capsys.readouterr()
        assert rc == 0, captured.err
        out = json.loads(captured.out)
        assert out["action"] == "aggregated"
        canonical = json.loads((dev_dir / f"dev-report-{BARE_TID}.json").read_text())
        assert canonical["dev"]["status"] == "needs_review"
        assert canonical["dev"]["status_rationale"]["classification"] == "pending_commit_handoff"
        assert "B" in canonical["dev"]["status_rationale"]["blocked_by"]

    def test_build_aggregate_stays_completed_with_no_status_rationale_when_no_shard_needs_review(self):
        shards = [("A", _good_shard()), ("B", _good_shard(task_id=BARE_TID))]
        aggregate = _build_aggregate(shards, BARE_TID)
        assert aggregate["dev"]["status"] == "completed"
        assert "status_rationale" not in aggregate["dev"]

    def test_build_aggregate_synthesizes_needs_review_status_rationale(self):
        shards = [("A", _good_shard()), ("B", _needs_review_shard())]
        aggregate = _build_aggregate(shards, BARE_TID)
        assert aggregate["dev"]["status"] == "needs_review"
        rationale = aggregate["dev"]["status_rationale"]
        assert rationale["classification"] == "pending_commit_handoff"
        assert "B: commit verb forbidden to dev subagent" in rationale["blocked_by"]
        assert rationale["forbidden_action"] == (
            "see per-lane status_rationale in the referenced lane dev-report(s)"
        )

    def test_build_aggregate_diverging_classifications_fall_back_to_other_disclosed_handoff(self):
        shards = [
            ("A", _needs_review_shard(classification="pending_commit_handoff")),
            ("B", _needs_review_shard(classification="pending_external_authorization")),
        ]
        aggregate = _build_aggregate(shards, BARE_TID)
        assert aggregate["dev"]["status"] == "needs_review"
        assert aggregate["dev"]["status_rationale"]["classification"] == "other_disclosed_handoff"
        assert "A:" in aggregate["dev"]["status_rationale"]["blocked_by"]
        assert "B:" in aggregate["dev"]["status_rationale"]["blocked_by"]


# ---------------------------------------------------------------------------
# R29 (spec-20260904-harness-fixes.md, task dev-20260914-035503):
# shard-load / shard-validation mismatch must write a 'blocked' canonical
# aggregate instead of zero artifact, per commands/dev.md Step 11's
# construction rule. AC-01 (load failure), AC-02 (validation failure),
# AC-03 (dry-run never writes), AC-06 (existing-canonical overwrite/preserve),
# AC-08 (a previously-written blocked doc does not permanently wedge
# recovery).
# ---------------------------------------------------------------------------

class TestBlockedAggregateOnMismatch:
    # -- AC-01: shard-load failure -----------------------------------------

    def test_load_failure_writes_blocked_aggregate_with_full_roster(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())
        (dev_dir / f"dev-report-B-{BARE_TID}.json").write_text("{broken: json")

        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        canonical_path = dev_dir / f"dev-report-{BARE_TID}.json"
        assert canonical_path.exists()
        doc = json.loads(canonical_path.read_text())
        assert doc["dev"]["status"] == "blocked"
        assert sorted(doc["parallel_workers"]) == ["A", "B"]

    def test_load_failure_blocking_issues_surfaces_real_parse_error(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())
        (dev_dir / f"dev-report-B-{BARE_TID}.json").write_text("{broken: json")

        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        doc = json.loads((dev_dir / f"dev-report-{BARE_TID}.json").read_text())
        matching = [issue for issue in doc["blocking_issues"] if "'B'" in issue]
        assert matching
        assert any("Expecting" in issue for issue in matching)
        assert not any(issue == "Failed to load shard 'B'" for issue in doc["blocking_issues"])

    def test_load_failure_skips_cross_shard_validation_of_partial_set(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())
        shard_c = _good_shard()
        shard_c["baseline_provenance"] = {
            "mode": "sequential",
            "derived_from": "B",
            "predecessor_files_created": [],
        }
        _write(dev_dir, f"dev-report-C-{BARE_TID}.json", shard_c)
        (dev_dir / f"dev-report-B-{BARE_TID}.json").write_text("{broken: json")

        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        doc = json.loads((dev_dir / f"dev-report-{BARE_TID}.json").read_text())
        assert any("'B'" in issue and "Expecting" in issue for issue in doc["blocking_issues"])
        assert not any("is not among the shards" in issue for issue in doc["blocking_issues"])

    def test_load_failure_preserves_loaded_shards_own_blocking_issues(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        shard_a = _good_shard()
        shard_a["blocking_issues"] = ["pre-existing shard-A issue"]
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", shard_a)
        (dev_dir / f"dev-report-B-{BARE_TID}.json").write_text("{broken: json")

        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        doc = json.loads((dev_dir / f"dev-report-{BARE_TID}.json").read_text())
        assert "pre-existing shard-A issue" in doc["blocking_issues"]
        assert any("'B'" in issue for issue in doc["blocking_issues"])

    def test_load_failure_collects_all_failures_not_just_first(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        (dev_dir / f"dev-report-A-{BARE_TID}.json").write_text("{broken: json")
        (dev_dir / f"dev-report-B-{BARE_TID}.json").write_text("not json at all")

        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        doc = json.loads((dev_dir / f"dev-report-{BARE_TID}.json").read_text())
        assert any("'A'" in issue for issue in doc["blocking_issues"])
        assert any("'B'" in issue for issue in doc["blocking_issues"])
        assert sorted(doc["parallel_workers"]) == ["A", "B"]
        assert doc["baseline_head_sha"] == ""
        assert doc["baseline_dirty_snapshot"] == ""

    def test_load_failure_unions_sibling_dev_fields_from_loaded_shards(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        shard_a = _good_shard()
        shard_a["dev"]["files_modified"] = ["unique/loaded/file.py"]
        shard_a["dev"]["tasks_completed"] = [{"id": 1, "description": "did the thing"}]
        shard_a["recommendations"] = ["do the other thing"]
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", shard_a)
        (dev_dir / f"dev-report-B-{BARE_TID}.json").write_text("{broken: json")

        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        doc = json.loads((dev_dir / f"dev-report-{BARE_TID}.json").read_text())
        assert "unique/loaded/file.py" in doc["dev"]["files_modified"]
        assert {"id": 1, "description": "did the thing"} in doc["dev"]["tasks_completed"]
        assert "do the other thing" in doc["recommendations"]

    def test_load_failure_treats_non_object_json_root_as_failure(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())
        (dev_dir / f"dev-report-B-{BARE_TID}.json").write_text("[]")

        rc = main(["--task-id", BARE_TID])
        captured = capsys.readouterr()
        assert rc == 1
        assert "Traceback" not in captured.err
        doc = json.loads((dev_dir / f"dev-report-{BARE_TID}.json").read_text())
        assert doc["dev"]["status"] == "blocked"
        assert any(
            "'B'" in issue and ("not an object" in issue or "list" in issue)
            for issue in doc["blocking_issues"]
        )

    # -- AC-02: shard-validation failure ------------------------------------

    def test_validation_failure_writes_blocked_aggregate(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard(sha="sha1111"))
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard(sha="sha9999"))

        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        canonical_path = dev_dir / f"dev-report-{BARE_TID}.json"
        assert canonical_path.exists()
        doc = json.loads(canonical_path.read_text())
        assert doc["dev"]["status"] == "blocked"
        assert any("baseline_head_sha" in issue for issue in doc["blocking_issues"])
        assert sorted(doc["parallel_workers"]) == ["A", "B"]

    def test_validation_failure_blocking_issues_itemized_per_lane(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard(sha="shaAAA"))
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard(sha="shaDIFFERENT"))
        _write(dev_dir, f"dev-report-C-{BARE_TID}.json", _good_shard(sha="shaAAA"))
        _write(dev_dir, f"dev-report-{BARE_TID}-C.json", _good_shard(sha="shaAAA"))

        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        doc = json.loads((dev_dir / f"dev-report-{BARE_TID}.json").read_text())
        assert any(
            "baseline_head_sha" in issue and "'B'" in issue for issue in doc["blocking_issues"]
        )
        assert any("duplicate worker labels" in issue for issue in doc["blocking_issues"])

    def test_validation_failure_no_status_rationale_populated(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard(sha="shaAAA"))
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard(sha="shaBBB"))

        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        doc = json.loads((dev_dir / f"dev-report-{BARE_TID}.json").read_text())
        assert doc["dev"].get("status_rationale") is None

    def test_validation_failure_preserves_shards_own_blocking_issues(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        shard_a = _good_shard(sha="shaAAA")
        shard_a["blocking_issues"] = ["pre-existing shard-A issue"]
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", shard_a)
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard(sha="shaBBB"))

        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        doc = json.loads((dev_dir / f"dev-report-{BARE_TID}.json").read_text())
        assert "pre-existing shard-A issue" in doc["blocking_issues"]
        assert any("baseline_head_sha" in issue for issue in doc["blocking_issues"])

    def test_validation_failure_needs_review_shard_does_not_leak_status_rationale(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        needs_review = _needs_review_shard(task_id=BARE_TID)
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", needs_review)
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard(sha="a-different-sha"))

        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        doc = json.loads((dev_dir / f"dev-report-{BARE_TID}.json").read_text())
        assert doc["dev"]["status"] == "blocked"
        assert "status_rationale" not in doc["dev"]
        assert "awaiting /commit hand-off" in doc["blocking_issues"]

    def test_validation_failure_unions_sibling_dev_fields_from_loaded_shards(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        shard_a = _good_shard(sha="shaAAA")
        shard_a["dev"]["files_created"] = ["new/file/created.py"]
        shard_a["dev"]["scripts_created"] = [{"path": "scripts/new-script.sh", "purpose": "x"}]
        shard_a["recommendations"] = ["consider doing X"]
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", shard_a)
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard(sha="shaBBB"))

        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        doc = json.loads((dev_dir / f"dev-report-{BARE_TID}.json").read_text())
        assert "new/file/created.py" in doc["dev"]["files_created"]
        assert {"path": "scripts/new-script.sh", "purpose": "x"} in doc["dev"]["scripts_created"]
        assert "consider doing X" in doc["recommendations"]

    def test_validation_failure_duplicate_label_needs_review_before_malformed_dev_does_not_crash(
        self, project_dir: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
    ):
        dev_dir = project_dir / "docs" / "dev"
        needs_review = _needs_review_shard()
        needs_review["blocking_issues"] = ["needs-review own issue"]
        needs_review["dev"]["files_modified"] = ["needs-review-unique.py"]
        path_needs_review = _write(dev_dir, f"dev-report-A-{BARE_TID}.json", needs_review)

        malformed = _good_shard()
        malformed["dev"] = ["not", "a", "dict"]
        path_malformed = _write(dev_dir, f"dev-report-{BARE_TID}-A.json", malformed)

        # Force the discovery order: needs_review shard first, malformed
        # second. Duplicate-label correlation must not depend on this order
        # (codex round-4 finding 3) -- see the sibling test below for the
        # reversed order.
        monkeypatch.setattr(
            _mod,
            "_scan_shards",
            lambda dev_dir_arg, bare_tid, original_task_id: [
                ("A", path_needs_review),
                ("A", path_malformed),
            ],
        )

        rc = main(["--task-id", BARE_TID])
        captured = capsys.readouterr()
        assert rc == 1
        assert "Traceback" not in captured.err

        canonical_path = dev_dir / f"dev-report-{BARE_TID}.json"
        assert canonical_path.exists()
        doc = json.loads(canonical_path.read_text())
        assert doc["dev"]["status"] == "blocked"
        assert "status_rationale" not in doc["dev"]
        assert any("duplicate worker labels" in issue for issue in doc["blocking_issues"])
        assert any("dev.status is" in issue for issue in doc["blocking_issues"])
        assert "needs-review own issue" in doc["blocking_issues"]
        assert "needs-review-unique.py" in doc["dev"]["files_modified"]
        assert doc["parallel_workers"] == ["A", "A"]

    def test_validation_failure_duplicate_label_malformed_dev_before_needs_review_does_not_crash(
        self, project_dir: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
    ):
        dev_dir = project_dir / "docs" / "dev"
        needs_review = _needs_review_shard()
        needs_review["blocking_issues"] = ["needs-review own issue"]
        needs_review["dev"]["files_modified"] = ["needs-review-unique.py"]
        path_needs_review = _write(dev_dir, f"dev-report-A-{BARE_TID}.json", needs_review)

        malformed = _good_shard()
        malformed["dev"] = ["not", "a", "dict"]
        path_malformed = _write(dev_dir, f"dev-report-{BARE_TID}-A.json", malformed)

        # Reversed order from the sibling test above: malformed shard first.
        monkeypatch.setattr(
            _mod,
            "_scan_shards",
            lambda dev_dir_arg, bare_tid, original_task_id: [
                ("A", path_malformed),
                ("A", path_needs_review),
            ],
        )

        rc = main(["--task-id", BARE_TID])
        captured = capsys.readouterr()
        assert rc == 1
        assert "Traceback" not in captured.err

        canonical_path = dev_dir / f"dev-report-{BARE_TID}.json"
        assert canonical_path.exists()
        doc = json.loads(canonical_path.read_text())
        assert doc["dev"]["status"] == "blocked"
        assert "status_rationale" not in doc["dev"]
        assert any("duplicate worker labels" in issue for issue in doc["blocking_issues"])
        assert any("dev.status is" in issue for issue in doc["blocking_issues"])
        assert "needs-review own issue" in doc["blocking_issues"]
        assert "needs-review-unique.py" in doc["dev"]["files_modified"]
        assert doc["parallel_workers"] == ["A", "A"]

    # -- AC-03: --dry-run never writes on either mismatch path --------------

    def test_dry_run_load_failure_does_not_write(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())
        (dev_dir / f"dev-report-B-{BARE_TID}.json").write_text("{broken: json")
        canonical_path = dev_dir / f"dev-report-{BARE_TID}.json"
        assert not canonical_path.exists()

        rc = main(["--task-id", BARE_TID, "--dry-run"])
        assert rc == 1
        assert not canonical_path.exists()

    def test_dry_run_validation_failure_does_not_write(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard(sha="shaAAA"))
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard(sha="shaBBB"))
        canonical_path = dev_dir / f"dev-report-{BARE_TID}.json"
        assert not canonical_path.exists()

        rc = main(["--task-id", BARE_TID, "--dry-run"])
        assert rc == 1
        assert not canonical_path.exists()

    # -- AC-06: an existing canonical is overwritten/preserved --------------

    def test_existing_canonical_overwritten_blocked_on_load_failure(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard())
        assert main(["--task-id", BARE_TID]) == 0
        capsys.readouterr()
        canonical_path = dev_dir / f"dev-report-{BARE_TID}.json"
        assert json.loads(canonical_path.read_text())["dev"]["status"] == "completed"

        (dev_dir / f"dev-report-B-{BARE_TID}.json").write_text("{broken: json")
        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        doc = json.loads(canonical_path.read_text())
        assert doc["dev"]["status"] == "blocked"

    def test_existing_canonical_overwritten_blocked_on_validation_failure(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard(sha="shaAAA"))
        path_b = _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard(sha="shaAAA"))
        assert main(["--task-id", BARE_TID]) == 0
        capsys.readouterr()
        canonical_path = dev_dir / f"dev-report-{BARE_TID}.json"
        assert json.loads(canonical_path.read_text())["dev"]["status"] == "completed"

        bad_b = _good_shard(sha="shaZZZDIFFERENT")
        path_b.write_text(json.dumps(bad_b))
        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        doc = json.loads(canonical_path.read_text())
        assert doc["dev"]["status"] == "blocked"

    def test_existing_canonical_dry_run_leaves_it_unchanged(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard())
        assert main(["--task-id", BARE_TID]) == 0
        capsys.readouterr()
        canonical_path = dev_dir / f"dev-report-{BARE_TID}.json"
        before = canonical_path.read_bytes()

        (dev_dir / f"dev-report-B-{BARE_TID}.json").write_text("{broken: json")
        rc = main(["--task-id", BARE_TID, "--dry-run"])
        assert rc == 1
        assert canonical_path.read_bytes() == before

    # -- AC-08: no sha bypass survives for ANY predecessor status (rewritten,
    # Layer-Escalation Review revision 8: the sha-provenance-marker mechanism
    # this class used to test -- _classify_sha_provenance/_sha_provenance --
    # is deleted entirely; recovery from a genuine sha conflict is now
    # uniformly manual, for every predecessor dev.status) --------------------

    @pytest.mark.parametrize("existing_status", ["blocked", "completed", "needs_review"])
    def test_blocked_canonical_recovery_same_sha_refreshes_regardless_of_predecessor_status(
        self, project_dir: Path, capsys: pytest.CaptureFixture, existing_status: str
    ):
        dev_dir = project_dir / "docs" / "dev"
        existing_canonical = {
            "task_id": BARE_TID,
            "request_id": BARE_TID,
            "baseline_head_sha": "shaV",
            "baseline_dirty_snapshot": "",
            "parallel_workers": ["A", "B"],
            "dev": {
                "status": existing_status, "tasks_completed": [], "scripts_created": [],
                "permissions_to_add": [], "files_modified": [], "files_created": [],
                "observed_preexisting": [],
            },
            "blocking_issues": [],
            "recommendations": [],
        }
        canonical_path = _write(dev_dir, f"dev-report-{BARE_TID}.json", existing_canonical)

        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard(sha="shaV"))
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard(sha="shaV"))

        rc = main(["--task-id", BARE_TID])
        assert rc == 0
        doc = json.loads(canonical_path.read_text())
        assert doc["dev"]["status"] == "completed"
        assert doc["baseline_head_sha"] == "shaV"

    @pytest.mark.parametrize("existing_status", ["blocked", "completed", "needs_review"])
    def test_blocked_canonical_recovery_differing_sha_refused_regardless_of_predecessor_status(
        self, project_dir: Path, capsys: pytest.CaptureFixture, existing_status: str
    ):
        dev_dir = project_dir / "docs" / "dev"
        existing_canonical = {
            "task_id": BARE_TID,
            "request_id": BARE_TID,
            "baseline_head_sha": "shaV",
            "baseline_dirty_snapshot": "",
            "parallel_workers": ["A", "B"],
            "dev": {
                "status": existing_status, "tasks_completed": [], "scripts_created": [],
                "permissions_to_add": [], "files_modified": [], "files_created": [],
                "observed_preexisting": [],
            },
            "blocking_issues": [],
            "recommendations": [],
        }
        canonical_path = _write(dev_dir, f"dev-report-{BARE_TID}.json", existing_canonical)
        before = canonical_path.read_bytes()

        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard(sha="shaW"))
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard(sha="shaW"))

        rc = main(["--task-id", BARE_TID])
        captured = capsys.readouterr()
        assert rc == 1
        assert "is stale" in captured.err
        assert canonical_path.read_bytes() == before

    def test_blocked_canonical_recovery_dry_run_leaves_it_unchanged(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        blocked_canonical = {
            "task_id": BARE_TID,
            "request_id": BARE_TID,
            "baseline_head_sha": "shaV",
            "baseline_dirty_snapshot": "",
            "parallel_workers": ["A", "B"],
            "dev": {
                "status": "blocked", "tasks_completed": [], "scripts_created": [],
                "permissions_to_add": [], "files_modified": [], "files_created": [],
                "observed_preexisting": [],
            },
            "blocking_issues": ["shard 'A': failed to load: boom"],
            "recommendations": [],
        }
        canonical_path = _write(dev_dir, f"dev-report-{BARE_TID}.json", blocked_canonical)
        before = canonical_path.read_bytes()

        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard(sha="shaV"))
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard(sha="shaV"))

        rc = main(["--task-id", BARE_TID, "--dry-run"])
        assert rc == 0
        assert canonical_path.read_bytes() == before

    def test_written_aggregate_never_contains_sha_provenance_key(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        """Direct regression guard against reintroducing the removed
        _classify_sha_provenance/_sha_provenance heuristic -- neither the
        blocked-write path nor the ordinary refresh/fresh-build path may
        ever write a `_sha_provenance` key (AC-08). Both shards agree on
        sha throughout (the mismatch is B's dev.status), so the CANDIDATE
        sha stays "shaA" -- unanimous -- across both runs; recovery is not
        a sha-conflict case here, keeping this test's concern narrowly
        scoped to the presence/absence of the removed key."""
        dev_dir = project_dir / "docs" / "dev"
        shard_a = _good_shard(sha="shaA")
        shard_b = _good_shard(sha="shaA")
        shard_b["dev"]["status"] = "in_progress"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", shard_a)
        path_b = _write(dev_dir, f"dev-report-B-{BARE_TID}.json", shard_b)
        assert main(["--task-id", BARE_TID]) == 1
        canonical_path = dev_dir / f"dev-report-{BARE_TID}.json"
        doc = json.loads(canonical_path.read_text())
        assert doc["dev"]["status"] == "blocked"
        assert "_sha_provenance" not in doc

        shard_b["dev"]["status"] = "completed"
        path_b.write_text(json.dumps(shard_b))
        assert main(["--task-id", BARE_TID]) == 0
        doc = json.loads(canonical_path.read_text())
        assert "_sha_provenance" not in doc

    # -- dev-level codex consultation hardening (post-QA, pre-delivery) -----
    # Three additional findings from an adversarial codex pass on this same
    # implementation, each independently live-reproduced against the code
    # BEFORE these tests/fixes existed, then verified fixed:

    def test_load_failure_non_utf8_shard_does_not_crash(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        """A non-UTF-8 shard file raises UnicodeDecodeError (a ValueError
        subclass, NOT an OSError) from Path.read_text() -- uncaught, this
        crashed with zero artifact written, exactly the zero-artifact-on-crash
        regression R29 exists to close (codex finding 1)."""
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())
        (dev_dir / f"dev-report-B-{BARE_TID}.json").write_bytes(b"\xff\xfe not valid utf8 \x00\x01")

        rc = main(["--task-id", BARE_TID])
        captured = capsys.readouterr()
        assert rc == 1
        assert "Traceback" not in captured.err
        doc = json.loads((dev_dir / f"dev-report-{BARE_TID}.json").read_text())
        assert doc["dev"]["status"] == "blocked"
        assert any("'B'" in issue for issue in doc["blocking_issues"])

    def test_blocked_canonical_recovery_duplicate_worker_shrink_still_refused(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        """A blocked doc's parallel_workers can legitimately contain a
        duplicated label (>=2 real shard files sharing it) -- the duplicate
        COUNT is meaningful evidence. A plain set-containment check would
        silently tolerate ONE of those files later disappearing while the
        label itself survives via its sibling; multiset containment must
        catch this (codex finding 3)."""
        dev_dir = project_dir / "docs" / "dev"
        blocked_canonical = {
            "task_id": BARE_TID,
            "request_id": BARE_TID,
            "baseline_head_sha": "",
            "baseline_dirty_snapshot": "",
            "parallel_workers": ["A", "A", "B"],
            "dev": {
                "status": "blocked", "tasks_completed": [], "scripts_created": [],
                "permissions_to_add": [], "files_modified": [], "files_created": [],
                "observed_preexisting": [],
            },
            "blocking_issues": ["shard 'A': failed to load: boom"],
            "recommendations": [],
        }
        canonical_path = _write(dev_dir, f"dev-report-{BARE_TID}.json", blocked_canonical)
        before = canonical_path.read_bytes()

        # Only ONE "A"-labeled shard file exists now (its sibling was deleted,
        # not repaired), plus "B" -- the label set {"A","B"} is unchanged, but
        # the A count shrank from 2 to 1.
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard(sha="shaREAL"))
        _write(dev_dir, f"dev-report-{BARE_TID}-B.json", _good_shard(sha="shaREAL"))

        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        assert canonical_path.read_bytes() == before


# ---------------------------------------------------------------------------
# AC-09 (Layer-Escalation Review, revision 8/9): write-time reconciliation
# preserves a pre-existing canonical's own recorded baseline_head_sha and/or
# parallel_workers across ANY mismatch write or the len(shards_info)<2
# skip-branch extension, never silently discarding it.
# ---------------------------------------------------------------------------

class TestWriteTimeReconciliation:
    def _existing_canonical(self, **overrides) -> dict:
        base = {
            "task_id": BARE_TID,
            "request_id": BARE_TID,
            "baseline_head_sha": "",
            "baseline_dirty_snapshot": "",
            "parallel_workers": ["A", "B"],
            "dev": {
                "status": "completed", "tasks_completed": [], "scripts_created": [],
                "permissions_to_add": [], "files_modified": [], "files_created": [],
                "observed_preexisting": [],
            },
            "blocking_issues": [],
            "recommendations": [],
        }
        base.update(overrides)
        return base

    def test_write_time_reconciliation_preserves_existing_nonempty_sha_over_unrelated_validation_failure(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        canonical_path = _write(
            dev_dir,
            f"dev-report-{BARE_TID}.json",
            self._existing_canonical(baseline_head_sha="shaY"),
        )

        shard_a = _good_shard(sha="shaX")
        shard_b = _good_shard(sha="shaX")
        shard_b["dev"]["status"] = "in_progress"  # unrelated to sha
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", shard_a)
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", shard_b)

        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        doc = json.loads(canonical_path.read_text())
        assert doc["dev"]["status"] == "blocked"
        assert doc["baseline_head_sha"] == "shaY"
        assert any("shaY" in issue and "shaX" in issue for issue in doc["blocking_issues"])

    def test_write_time_reconciliation_preserves_existing_empty_sha_across_intervening_failure(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        canonical_path = _write(
            dev_dir,
            f"dev-report-{BARE_TID}.json",
            self._existing_canonical(baseline_head_sha="", dev={
                "status": "blocked", "tasks_completed": [], "scripts_created": [],
                "permissions_to_add": [], "files_modified": [], "files_created": [],
                "observed_preexisting": [],
            }),
        )

        shard_a = _good_shard(sha="shaX")
        shard_b = _good_shard(sha="shaX")
        shard_b["dev"]["status"] = "in_progress"
        path_a = _write(dev_dir, f"dev-report-A-{BARE_TID}.json", shard_a)
        path_b = _write(dev_dir, f"dev-report-B-{BARE_TID}.json", shard_b)

        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        doc = json.loads(canonical_path.read_text())
        assert doc["baseline_head_sha"] == ""  # NOT overwritten with shaX

        # Third run: both now agree on shaX and both are otherwise valid.
        shard_b["dev"]["status"] = "completed"
        path_b.write_text(json.dumps(shard_b))
        rc = main(["--task-id", BARE_TID])
        assert rc == 1  # refused: existing "" != candidate "shaX"
        assert json.loads(canonical_path.read_text())["baseline_head_sha"] == ""

    def test_write_time_reconciliation_candidate_sha_is_empty_when_current_shards_disagree(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        canonical_path = dev_dir / f"dev-report-{BARE_TID}.json"
        assert not canonical_path.exists()

        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard(sha="shaX"))
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard(sha="shaY"))
        _write(dev_dir, f"dev-report-C-{BARE_TID}.json", _good_shard(sha="shaY"))

        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        doc = json.loads(canonical_path.read_text())
        assert doc["baseline_head_sha"] == ""

        # A later run where all 3 agree on shaX is REFUSED, not silently
        # accepted, because the written candidate was correctly "".
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard(sha="shaX"))
        _write(dev_dir, f"dev-report-C-{BARE_TID}.json", _good_shard(sha="shaX"))
        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        assert json.loads(canonical_path.read_text())["baseline_head_sha"] == ""

    def test_write_time_reconciliation_roster_union_preserves_duplicate_label_occurrence(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        canonical_path = _write(
            dev_dir,
            f"dev-report-{BARE_TID}.json",
            self._existing_canonical(parallel_workers=["A", "A", "B"], dev={
                "status": "blocked", "tasks_completed": [], "scripts_created": [],
                "permissions_to_add": [], "files_modified": [], "files_created": [],
                "observed_preexisting": [],
            }),
        )

        # Only one "A" shard + one "B" shard now; disagree on sha to trigger
        # a validation-failure mismatch write.
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard(sha="shaA"))
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard(sha="shaB"))

        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        doc = json.loads(canonical_path.read_text())
        assert sorted(doc["parallel_workers"]) == ["A", "A", "B"]
        assert any("'A'" in issue and "occurrence" in issue for issue in doc["blocking_issues"])

    def test_write_time_reconciliation_unreadable_existing_canonical_falls_back_to_fail_closed_sha(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        canonical_path = dev_dir / f"dev-report-{BARE_TID}.json"
        canonical_path.write_text("{not valid json")

        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard(sha="shaA"))
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard(sha="shaB"))

        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        doc = json.loads(canonical_path.read_text())
        assert doc["dev"]["status"] == "blocked"
        assert doc["baseline_head_sha"] == ""
        assert any("reconciliation" in issue.lower() for issue in doc["blocking_issues"])

    def test_len_below_2_writes_blocked_aggregate_when_existing_canonical_establishes_larger_roster(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        canonical_path = _write(
            dev_dir,
            f"dev-report-{BARE_TID}.json",
            self._existing_canonical(parallel_workers=["A", "B"], baseline_head_sha="shaAB"),
        )

        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard(sha="shaAB"))
        # B's shard file is absent entirely.

        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        doc = json.loads(canonical_path.read_text())
        assert doc["dev"]["status"] == "blocked"
        assert any("'B'" in issue for issue in doc["blocking_issues"])

    def test_len_below_2_singular_dev_report_with_no_parallel_workers_key_is_skipped_untouched(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        """Regression test for the R29 item-F self-harm defect: a genuine
        SINGULAR dev-report -- written directly by a dev subagent per
        agents/dev.md's own Output Format schema, which has no
        parallel_workers concept at all -- must never be treated as
        "ambiguous, assume parallel" just because the key is absent. This is
        the exact /close Step 0 integration scenario (aggregate-dev-report.py
        invoked against a plain, non-fan-out task-id whose ONLY existing
        artifact is a singular dev-report) that previously overwrote the
        canonical in place with a generic blocked-aggregate document."""
        dev_dir = project_dir / "docs" / "dev"
        singular_report = {
            "request_id": BARE_TID,
            "task_id": BARE_TID,
            "timestamp": "2026-09-14T04:20:00Z",
            "baseline_head_sha": "4b90034884e1ffd7c84b55bf69e7c6b2d74c404a",
            "baseline_dirty_snapshot": "",
            "dev_report_path": f"docs/dev/dev-report-{BARE_TID}.json",
            "dev": {
                "status": "completed",
                "tasks_completed": [{"id": 1, "description": "did the thing"}],
                "scripts_created": [],
                "permissions_to_add": [],
                "files_modified": ["scripts/aggregate-dev-report.py"],
                "files_created": [],
                "observed_preexisting": [],
            },
            "blocking_issues": [],
            "recommendations": [],
            # Deliberately NO "parallel_workers" key: a singular dev-report
            # was never built via _build_aggregate and has no such concept.
        }
        canonical_path = _write(dev_dir, f"dev-report-{BARE_TID}.json", singular_report)
        before = canonical_path.read_bytes()

        # No shard files exist at all -- a singular /dev cycle never writes
        # per-lane shard files, so the scan finds zero.

        rc = main(["--task-id", BARE_TID])

        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["action"] == "skipped"
        assert canonical_path.read_bytes() == before, (
            "a genuine singular dev-report (no parallel_workers key) must be "
            "left completely byte-for-byte untouched, never overwritten with "
            "a blocked aggregate"
        )

    def test_len_below_2_existing_roster_usable_blocking_issues_has_no_duplicate_entries(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        """QA round-4 finding: in the existing_roster_usable sub-case, the
        skip-branch's own pre-computed roster-diff message and
        _reconcile_write_time's independently-recomputed roster-diff message
        must not both land in blocking_issues -- the same fact about the same
        missing shard must appear exactly once, not twice."""
        dev_dir = project_dir / "docs" / "dev"
        canonical_path = _write(
            dev_dir,
            f"dev-report-{BARE_TID}.json",
            self._existing_canonical(parallel_workers=["A", "B"], baseline_head_sha="shaAB"),
        )

        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard(sha="shaAB"))
        # B's shard file is absent entirely -- identical fixture shape to the
        # sibling `any(...)` test above, which does not notice duplication.

        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        doc = json.loads(canonical_path.read_text())
        assert doc["dev"]["status"] == "blocked"
        b_missing_issues = [
            issue
            for issue in doc["blocking_issues"]
            if "'B'" in issue and "occurrence" in issue
        ]
        assert len(b_missing_issues) == 1, (
            "expected exactly one 'B' roster-diff disclosure, got "
            f"{len(b_missing_issues)}: {b_missing_issues!r}"
        )
        assert len(doc["blocking_issues"]) == len(set(doc["blocking_issues"])), (
            f"blocking_issues contains exact-duplicate entries: {doc['blocking_issues']!r}"
        )

    def test_len_below_2_still_skips_when_no_existing_canonical(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard())

        rc = main(["--task-id", BARE_TID])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["action"] == "skipped"
        assert not (dev_dir / f"dev-report-{BARE_TID}.json").exists()

    def test_recovery_read_workers_subset_check_is_multiset_correct_for_completed_predecessor(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        canonical_path = _write(
            dev_dir,
            f"dev-report-{BARE_TID}.json",
            self._existing_canonical(parallel_workers=["A", "A", "B"], baseline_head_sha="shaAB"),
        )
        before = canonical_path.read_bytes()

        # Only ONE "A" shard exists now (its duplicate sibling is gone), plus "B".
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard(sha="shaAB"))
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard(sha="shaAB"))

        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        assert canonical_path.read_bytes() == before

    def test_len_below_2_unreadable_existing_canonical_still_writes_blocked_aggregate_fail_closed(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        canonical_path = dev_dir / f"dev-report-{BARE_TID}.json"
        canonical_path.write_text("{not valid json")

        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard(sha="shaA"))
        # No B shard at all.

        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        doc = json.loads(canonical_path.read_text())
        assert doc["dev"]["status"] == "blocked"
        assert doc["baseline_head_sha"] == ""
        assert sorted(doc["parallel_workers"]) == ["A"]

    def test_write_time_reconciliation_sha_field_malformed_does_not_block_roster_reconciliation(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        canonical_path = _write(
            dev_dir,
            f"dev-report-{BARE_TID}.json",
            self._existing_canonical(baseline_head_sha=12345, parallel_workers=["A", "A", "B"]),
        )

        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard(sha="shaX"))
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", _good_shard(sha="shaY"))

        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        doc = json.loads(canonical_path.read_text())
        assert doc["baseline_head_sha"] == ""
        assert sorted(doc["parallel_workers"]) == ["A", "A", "B"]

    def test_write_time_reconciliation_roster_field_malformed_does_not_block_sha_reconciliation(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        canonical_path = _write(
            dev_dir,
            f"dev-report-{BARE_TID}.json",
            self._existing_canonical(baseline_head_sha="shaY", parallel_workers="not-a-list"),
        )

        shard_a = _good_shard(sha="shaX")
        shard_b = _good_shard(sha="shaX")
        shard_b["dev"]["status"] = "in_progress"
        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", shard_a)
        _write(dev_dir, f"dev-report-B-{BARE_TID}.json", shard_b)

        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        doc = json.loads(canonical_path.read_text())
        assert doc["baseline_head_sha"] == "shaY"
        assert sorted(doc["parallel_workers"]) == ["A", "B"]

    def test_write_time_reconciliation_preserves_existing_sha_via_load_failure_call_site(
        self, project_dir: Path, capsys: pytest.CaptureFixture
    ):
        dev_dir = project_dir / "docs" / "dev"
        canonical_path = _write(
            dev_dir,
            f"dev-report-{BARE_TID}.json",
            self._existing_canonical(baseline_head_sha="shaY"),
        )

        _write(dev_dir, f"dev-report-A-{BARE_TID}.json", _good_shard(sha="shaX"))
        (dev_dir / f"dev-report-B-{BARE_TID}.json").write_text("{broken: json")

        rc = main(["--task-id", BARE_TID])
        assert rc == 1
        doc = json.loads(canonical_path.read_text())
        assert doc["dev"]["status"] == "blocked"
        assert doc["baseline_head_sha"] == "shaY"