#!/usr/bin/env python3
"""R4 late-repair route: monotonicity, negative controls, and hash-independence.

Covers AC-7..AC-11, AC-13, AC-14 (spec-20260907-115508-lawful-commit-channel.md,
docs/dev/acceptance-criteria-20260910-091226.json). AC-6/AC-15 (resolver gap
classification) live in tests/test_resolve_dev_artifact_chain.py. AC-12 (the
cross-repo spec-text insertion) is a data check against the other repository;
it is included below (see test_ac12_cross_repo_spec_text_insertion_is_pure_addition)
rather than left only in the test-writer scaffold under tests/generated/, since
that directory is gitignored by default (see .gitignore's `tests/generated/*`
rule) and would otherwise leave the pinned golden fixture
(tests/fixtures/late_repair_golden/spec-20260907-115508-lawful-commit-channel.pre-r4.md)
unreferenced by any committed test.

Evidence-seam disclosure (QA round-2 objection 4, option (b)): the BA/Dev/QA
"stages" recorded below via record-stage are genuine on-disk artifacts this
test constructs itself, hashed for real -- but the ACT of BA/Dev/QA reasoning
is not something pytest can prove. This suite proves the sequencing, gating,
and hash-independence contract only; genuine agent execution is verified by a
live, non-pytest /close --late-repair run reviewed by the orchestrator/QA.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _late_repair_fixtures as fx  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTROLLER_PATH = REPO_ROOT / "scripts" / "late-repair-controller.py"
CHECKER_PATH = REPO_ROOT / "scripts" / "check-late-repair-provenance.py"
ROUTE_SELECT_PATH = REPO_ROOT / "scripts" / "close-route-select.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CONTROLLER = _load(CONTROLLER_PATH, "_late_repair_controller_under_test")
ROUTE_SELECT = _load(ROUTE_SELECT_PATH, "_close_route_select_under_test")


def _run_controller(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CONTROLLER_PATH), *args],
        capture_output=True, text=True, check=False,
    )


def _last_json(proc: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")


def _run_record_path(root: Path, task_id: str) -> Path:
    return root / "docs" / "dev" / f"late-repair-run-{task_id}.json"


def _effective_path(root: Path, task_id: str) -> Path:
    return root / "docs" / "dev" / f"dev-report-{task_id}.effective.json"


# ---------------------------------------------------------------------------
# AC-7: init refuses immediately for every ineligible fixture shape.
# ---------------------------------------------------------------------------

def test_ac7_ineligible_fixtures_refuse_with_zero_run_records_and_zero_dispatch(tmp_path: Path) -> None:
    fixtures = {
        "qa_only": fx.build_qa_only,
        "complete": fx.build_complete,
        "mixed_integrity": fx.build_mixed_integrity,
    }
    for name, builder in fixtures.items():
        root = tmp_path / name
        task_id = f"20260101-0001{list(fixtures).index(name):02d}"
        builder(root, task_id)
        proc = _run_controller("init", "--task-id", task_id, "--project-dir", str(root))
        assert proc.returncode == 1, (name, proc.stdout, proc.stderr)
        payload = _last_json(proc)
        assert payload["outcome"] == "refuse"
        assert "not a beyond-QA gap; use R1's route" in payload["reason"]
        assert not _run_record_path(root, task_id).is_file()


def test_ac7_force_combined_with_late_repair_is_a_usage_error_before_eligibility(tmp_path: Path) -> None:
    task_id = "20260101-000110"
    root = tmp_path / "eligible"
    fx.build_beyond_qa_clean(root, task_id)
    proc = _run_controller("init", "--task-id", task_id, "--project-dir", str(root), "--force")
    assert proc.returncode not in (0, 1)
    payload = _last_json(proc)
    assert payload["outcome"] == "refuse"
    assert "--force" in payload["reason"]
    assert not _run_record_path(root, task_id).is_file()
    # A bare /close --force fixture's pre-cycle behavior is unaffected: close-route-select's
    # own --late-repair + --force usage-error check does not touch the resolver at all
    # for a bare bash-level --force invocation, and --force alone (no --late-repair)
    # never reaches late-repair code at all.
    rc, payload2 = ROUTE_SELECT.run(task_id, str(root), False, True)
    assert payload2["outcome"] == "not_selected"


# ---------------------------------------------------------------------------
# AC-8: eligible + no drift -> two-step admission (finalize is provisional).
# ---------------------------------------------------------------------------

def test_ac8_eligible_chain_no_drift_requires_separate_verify_disclosure_step(tmp_path: Path) -> None:
    task_id = "20260101-000200"
    root = tmp_path
    fx.build_beyond_qa_clean(root, task_id)

    init = _run_controller("init", "--task-id", task_id, "--project-dir", str(root))
    assert init.returncode == 0
    run_id = _last_json(init)["repair_run_id"]

    dev_dir = root / "docs" / "dev"
    ticket = dev_dir / f"ticket-{task_id}.md"
    ticket.write_text(fx._ticket(task_id), encoding="utf-8")

    # Out-of-order: dev before ba.
    out_of_order = _run_controller(
        "record-stage", "--task-id", task_id, "--project-dir", str(root),
        "--stage", "dev", "--report-path", str(dev_dir / f"dev-report-{task_id}.json"),
        "--repair-run-id", run_id,
    )
    assert out_of_order.returncode == 4

    ba = _run_controller(
        "record-stage", "--task-id", task_id, "--project-dir", str(root),
        "--stage", "ba", "--report-path", str(ticket), "--repair-run-id", run_id,
    )
    assert ba.returncode == 0
    ba_sha = _last_json(ba)["sha256"]
    assert ba_sha == __import__("hashlib").sha256(ticket.read_bytes()).hexdigest()

    context = dev_dir / f"context-{task_id}.json"
    context.write_text(json.dumps({"request_id": task_id, "task_id": task_id}), encoding="utf-8")
    qa_report = dev_dir / f"qa-report-{task_id}.json"
    qa_report.write_text(json.dumps(fx._qa_document(task_id)), encoding="utf-8")

    dev_stage = _run_controller(
        "record-stage", "--task-id", task_id, "--project-dir", str(root),
        "--stage", "dev", "--report-path", str(dev_dir / f"dev-report-{task_id}.json"),
        "--repair-run-id", run_id,
    )
    assert dev_stage.returncode == 0

    duplicate = _run_controller(
        "record-stage", "--task-id", task_id, "--project-dir", str(root),
        "--stage", "dev", "--report-path", str(dev_dir / f"dev-report-{task_id}.json"),
        "--repair-run-id", run_id,
    )
    assert duplicate.returncode == 3

    qa_stage = _run_controller(
        "record-stage", "--task-id", task_id, "--project-dir", str(root),
        "--stage", "qa", "--report-path", str(qa_report), "--repair-run-id", run_id,
    )
    assert qa_stage.returncode == 0

    finalize = _run_controller(
        "finalize", "--task-id", task_id, "--project-dir", str(root), "--repair-run-id", run_id,
    )
    assert finalize.returncode == 0
    finalize_payload = _last_json(finalize)
    assert finalize_payload["outcome"] == "finalized_pending_verification"

    # finalize alone is NOT sufficient for commit eligibility.
    record = json.loads(_run_record_path(root, task_id).read_text(encoding="utf-8"))
    assert record["outcome"] == "finalized_pending_verification"
    assert record["outcome"] != "admitted"

    verify = _run_controller("verify-disclosure", "--task-id", task_id, "--project-dir", str(root))
    assert verify.returncode == 0
    assert _last_json(verify)["outcome"] == "admitted"

    # A corrupted-after-the-fact artifact causes a mismatch.
    ticket.write_text(ticket.read_text(encoding="utf-8") + "\ntampered\n", encoding="utf-8")
    verify_after_tamper = _run_controller("verify-disclosure", "--task-id", task_id, "--project-dir", str(root))
    assert verify_after_tamper.returncode != 0
    assert "not independently corroborated" in _last_json(verify_after_tamper)["reason"]


def test_ac8_wrong_role_report_path_is_refused(tmp_path: Path) -> None:
    task_id = "20260101-000210"
    root = tmp_path
    fx.build_beyond_qa_clean(root, task_id)
    init = _run_controller("init", "--task-id", task_id, "--project-dir", str(root))
    run_id = _last_json(init)["repair_run_id"]
    dev_dir = root / "docs" / "dev"
    qa_report = dev_dir / f"qa-report-{task_id}.json"
    qa_report.write_text(json.dumps(fx._qa_document(task_id)), encoding="utf-8")
    wrong_role = _run_controller(
        "record-stage", "--task-id", task_id, "--project-dir", str(root),
        "--stage", "ba", "--report-path", str(qa_report), "--repair-run-id", run_id,
    )
    assert wrong_role.returncode == 3
    assert "not valid for stage" in _last_json(wrong_role)["reason"]


# ---------------------------------------------------------------------------
# AC-9: drift detection + per-file routing across all three provenance classes.
# ---------------------------------------------------------------------------

def _init_and_record_all_stages(root: Path, task_id: str) -> str:
    init = _run_controller("init", "--task-id", task_id, "--project-dir", str(root))
    assert init.returncode == 0, init.stdout
    run_id = _last_json(init)["repair_run_id"]
    dev_dir = root / "docs" / "dev"
    ticket_path = dev_dir / f"ticket-{task_id}.md"
    if not ticket_path.is_file():
        ticket_path.write_text(fx._ticket(task_id), encoding="utf-8")
    context_path = dev_dir / f"context-{task_id}.json"
    if not context_path.is_file():
        context_path.write_text(json.dumps({"request_id": task_id, "task_id": task_id}), encoding="utf-8")
    qa_path = dev_dir / f"qa-report-{task_id}.json"
    if not qa_path.is_file():
        qa_path.write_text(json.dumps(fx._qa_document(task_id)), encoding="utf-8")
    for stage, path in (
        ("ba", dev_dir / f"ticket-{task_id}.md"),
        ("dev", dev_dir / f"dev-report-{task_id}.json"),
        ("qa", dev_dir / f"qa-report-{task_id}.json"),
    ):
        proc = _run_controller(
            "record-stage", "--task-id", task_id, "--project-dir", str(root),
            "--stage", stage, "--report-path", str(path), "--repair-run-id", run_id,
        )
        assert proc.returncode == 0, (stage, proc.stdout, proc.stderr)
    return run_id


def test_ac9a_unreconcilable_drift_honestly_refuses(tmp_path: Path) -> None:
    task_id = "20260101-000300"
    root = tmp_path
    fx.build_beyond_qa_clean(root, task_id)
    _init_repo(root)

    tracked_rel = "src/tracked.py"
    tracked_path = root / tracked_rel
    tracked_path.parent.mkdir(parents=True, exist_ok=True)
    baseline = "alpha\nbeta\ngamma\n"
    tracked_path.write_text(baseline, encoding="utf-8")
    _git(root, "add", tracked_rel)
    _git(root, "commit", "-q", "-m", "baseline")

    dev_final = "alpha\nBETA-DEV\ngamma\n"
    # Peer edit OVERLAPS the exact line dev owns -- unreconcilable.
    peer_final = "alpha\nBETA-PEER\ngamma\n"
    tracked_path.write_text(peer_final, encoding="utf-8")

    dev_report_path = root / "docs" / "dev" / f"dev-report-{task_id}.json"
    dev_doc = json.loads(dev_report_path.read_text(encoding="utf-8"))
    dev_doc["dev"]["files_modified"] = [tracked_rel]
    dev_doc["owned_edits"] = {tracked_rel: [{"old": "beta\n", "new": "BETA-DEV\n"}]}
    dev_doc["pre_edit_snapshots"] = {tracked_rel: baseline}
    dev_doc["final_source_hashes"] = {
        tracked_rel: __import__("hashlib").sha256(dev_final.encode("utf-8")).hexdigest()
    }
    dev_report_path.write_text(json.dumps(dev_doc, indent=2), encoding="utf-8")

    run_id = _init_and_record_all_stages(root, task_id)
    finalize = _run_controller("finalize", "--task-id", task_id, "--project-dir", str(root), "--repair-run-id", run_id)
    assert finalize.returncode == 5
    payload = _last_json(finalize)
    assert payload["outcome"] == "honest_refuse"
    assert tracked_rel in payload["drift_detected"]
    assert tracked_rel in payload["unroutable_files"]
    assert not _effective_path(root, task_id).is_file()


def test_ac9b_reconcilable_drift_across_all_three_routing_classes(tmp_path: Path) -> None:
    """Reconcilable interleaving spanning tracked_composed and whole_created
    with GENUINE byte-level drift, plus untracked_modified exercised at its
    OWN, narrower guarantee (see the dedicated untracked_modified tests below
    for why -- disclosed finding, not a shortcut): stage-owned-hunks.py's
    ``--untracked-modified-report`` mode (read directly, lines 724-726) hard-
    requires ``final_source_hashes[claim] == contract["final"]["sha256"]`` to
    succeed at all -- there is no partial-hunk mechanism for an untracked
    file (no git-tracked history to diff against), so a GENUINE byte-level
    drift on this class is, by that existing, protected mechanism's own
    design, always unroutable. This fixture therefore includes the untracked
    file in a self-consistent (non-drifted) state to prove it correctly
    contributes NO drift entry and is left alone by the refresh; its routing
    function is exercised directly (success + genuine-drift-refusal) in the
    two tests below this one.
    """
    task_id = "20260101-000310"
    root = tmp_path
    fx.build_beyond_qa_clean(root, task_id)
    _init_repo(root)
    import hashlib

    # --- Class 1: tracked hunk-owned, real non-overlapping peer interleave. ---
    tracked_rel = "src/tracked.py"
    tracked_path = root / tracked_rel
    tracked_path.parent.mkdir(parents=True, exist_ok=True)
    baseline = "line1\nline2\nline3\n"
    tracked_path.write_text(baseline, encoding="utf-8")
    _git(root, "add", tracked_rel)
    _git(root, "commit", "-q", "-m", "baseline")
    dev_final_tracked = "line1\nCHANGED\nline3\n"
    worktree_tracked = "line1\nCHANGED\nline3\nPEER\n"  # non-overlapping peer append
    tracked_path.write_text(worktree_tracked, encoding="utf-8")

    # --- Class 2 control: authenticated pre-existing untracked, self-consistent. ---
    untracked_mod_rel = "notes/untracked-mod.txt"
    untracked_mod_path = root / untracked_mod_rel
    untracked_mod_path.parent.mkdir(parents=True, exist_ok=True)
    pre_bytes = b"before\n"
    final_bytes = b"after\n"
    untracked_mod_path.write_bytes(final_bytes)
    pre_sha = hashlib.sha256(pre_bytes).hexdigest()
    final_sha = hashlib.sha256(final_bytes).hexdigest()

    # --- Class 3: whole newly-created, currently untracked, GENUINE drift. ---
    created_rel = "src/new_thing.py"
    created_path = root / created_rel
    created_path.parent.mkdir(parents=True, exist_ok=True)
    created_pre = "# placeholder\n"
    created_final = "# placeholder\nprint('done')\n"
    created_path.write_text(created_final, encoding="utf-8")

    dev_report_path = root / "docs" / "dev" / f"dev-report-{task_id}.json"
    dev_doc = json.loads(dev_report_path.read_text(encoding="utf-8"))
    dev_doc["dev"]["files_modified"] = [tracked_rel, untracked_mod_rel]
    dev_doc["dev"]["files_created"] = [created_rel]
    dev_doc["owned_edits"] = {
        tracked_rel: [{"old": "line2\n", "new": "CHANGED\n"}],
        created_rel: [{"old": created_pre, "new": created_final}],
    }
    dev_doc["pre_edit_snapshots"] = {
        tracked_rel: baseline,
        created_rel: created_pre,
    }
    dev_doc["pre_edit_provenance"] = {
        "verified_before_edit": True,
        "source": "test fixture",
        "files": {untracked_mod_rel: pre_sha},
        "statuses": {untracked_mod_rel: "??"},
    }
    dev_doc["untracked_modified_provenance"] = {
        untracked_mod_rel: {
            "path": untracked_mod_rel,
            "admission": "authenticated_preexisting_untracked_whole_file",
            "pre_edit": {"git_status": "??", "sha256": pre_sha},
            "final": {"git_status": "??", "sha256": final_sha},
            "evidence_source": "test fixture",
        }
    }
    dev_doc["final_source_hashes"] = {
        tracked_rel: hashlib.sha256(dev_final_tracked.encode("utf-8")).hexdigest(),
        # Self-consistent (matches the contract + current bytes): no drift.
        untracked_mod_rel: final_sha,
        # Deliberately STALE: drift-detection fires; reconciliation
        # cross-validates against the ledger replay, a stronger, independent
        # authority than this summary map.
        created_rel: hashlib.sha256(b"stale-wrong-value-2").hexdigest(),
    }
    dev_report_path.write_text(json.dumps(dev_doc, indent=2), encoding="utf-8")

    run_id = _init_and_record_all_stages(root, task_id)
    finalize = _run_controller("finalize", "--task-id", task_id, "--project-dir", str(root), "--repair-run-id", run_id)
    assert finalize.returncode == 0, finalize.stdout
    payload = _last_json(finalize)
    assert payload["outcome"] == "finalized_pending_verification"
    drift = payload["drift_detected"]
    assert set(drift) == {tracked_rel, created_rel}
    assert untracked_mod_rel not in drift

    checker = _load(CHECKER_PATH, "_checker_under_test")
    routing = checker.check(str(root), task_id, dev_report_path)["routing"]
    assert routing[tracked_rel]["route"] == "tracked_composed"
    assert routing[created_rel]["route"] == "whole_created"

    effective_path = _effective_path(root, task_id)
    assert effective_path.is_file()
    original_bytes_before = dev_report_path.read_bytes()

    effective_doc = json.loads(effective_path.read_text(encoding="utf-8"))
    assert effective_doc["final_source_hashes"][tracked_rel] == hashlib.sha256(worktree_tracked.encode("utf-8")).hexdigest()
    assert effective_doc["final_source_hashes"][created_rel] == hashlib.sha256(created_final.encode("utf-8")).hexdigest()
    # Untracked file was never drifted: its recorded hash is carried through unchanged.
    assert effective_doc["final_source_hashes"][untracked_mod_rel] == final_sha

    # Original dev-report is byte-for-byte unchanged.
    assert dev_report_path.read_bytes() == original_bytes_before

    verify = _run_controller("verify-disclosure", "--task-id", task_id, "--project-dir", str(root))
    assert verify.returncode == 0
    assert _last_json(verify)["outcome"] == "admitted"

    # commit-resolution tri-state guard: verified -> "verified" state, returns
    # the effective path.
    state, resolved_path = CONTROLLER.resolve_effective_report_state(root, task_id)
    assert state == "verified"
    assert resolved_path == effective_path


def test_ac9_untracked_modified_routing_succeeds_when_self_consistent(tmp_path: Path) -> None:
    """Direct unit coverage of the untracked_modified routing mechanism.

    Exercised directly (not via the full drift pipeline -- see the class
    docstring above for why a genuinely-drifted untracked file can never
    reach this call in practice): confirms the routing function itself
    correctly re-authenticates a self-consistent adopted file.
    """
    task_id = "20260101-000311"
    root = tmp_path
    fx.build_beyond_qa_clean(root, task_id)
    _init_repo(root)
    import hashlib

    rel = "notes/untracked-mod.txt"
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    pre_bytes, final_bytes = b"before\n", b"after\n"
    path.write_bytes(final_bytes)
    pre_sha, final_sha = hashlib.sha256(pre_bytes).hexdigest(), hashlib.sha256(final_bytes).hexdigest()

    dev_report_path = root / "docs" / "dev" / f"dev-report-{task_id}.json"
    doc = json.loads(dev_report_path.read_text(encoding="utf-8"))
    doc["dev"]["files_modified"] = [rel]
    doc["pre_edit_provenance"] = {
        "verified_before_edit": True, "source": "test",
        "files": {rel: pre_sha}, "statuses": {rel: "??"},
    }
    doc["untracked_modified_provenance"] = {
        rel: {
            "path": rel, "admission": "authenticated_preexisting_untracked_whole_file",
            "pre_edit": {"git_status": "??", "sha256": pre_sha},
            "final": {"git_status": "??", "sha256": final_sha},
            "evidence_source": "test",
        }
    }
    doc["final_source_hashes"] = {rel: final_sha}
    dev_report_path.write_text(json.dumps(doc), encoding="utf-8")

    checker = _load(CHECKER_PATH, "_checker_under_test")
    route_kind, detail = checker.route_file(root, task_id, rel, doc, dev_report_path)
    assert route_kind == "untracked_modified", detail


def test_ac9_clean_committed_tracked_file_routes_through_tracked_composed_not_skipped(tmp_path: Path) -> None:
    """Self-review regression (codex unavailable this cycle, HTTP 401 against
    api.openai.com -- see docs/codex/20260910-091226/dev-adversarial-review.txt):
    a tracked file whose drift is invisible to `git status --porcelain`
    (worktree == index exactly, e.g. a peer's change was fully committed
    rather than left dirty) MUST still be routed through the tracked_composed
    mechanism -- not spuriously classified 'unroutable: no provenance
    mechanism declared for this file' via an absent-status-line proxy for
    'untracked'. The original implementation used `_git_status_code(...) not
    in ('??', None)` to decide tracked_composed eligibility; a clean tracked
    file produces NO porcelain line at all (status is None), which is
    indistinguishable from 'does not exist'. The fix (`_is_tracked()`, a
    direct `git ls-files --error-unmatch` check) routes this shape through
    the real mechanism, which then correctly fail-closes for its OWN
    git-apply reason (the index has already moved past dev's pre-edit
    baseline, so the hunk cannot compose) -- proving the diagnostic path
    changed without any fail-closed guarantee being weakened.
    """
    task_id = "20260101-999001"
    root = tmp_path
    fx.build_beyond_qa_clean(root, task_id)
    _init_repo(root)
    import hashlib

    rel = "src/committed_peer.py"
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    baseline = "x\ny\nz\n"
    path.write_text(baseline, encoding="utf-8")
    _git(root, "add", rel)
    _git(root, "commit", "-q", "-m", "baseline")

    dev_final = "x\nY-DEV\nz\n"
    peer_committed_final = "x\nY-DEV\nz\nPEER-COMMITTED\n"
    path.write_text(peer_committed_final, encoding="utf-8")
    _git(root, "add", rel)
    _git(root, "commit", "-q", "-m", "peer change, fully committed (not left dirty)")

    dev_report_path = root / "docs" / "dev" / f"dev-report-{task_id}.json"
    doc = json.loads(dev_report_path.read_text(encoding="utf-8"))
    doc["dev"]["files_modified"] = [rel]
    doc["owned_edits"] = {rel: [{"old": "y\n", "new": "Y-DEV\n"}]}
    doc["pre_edit_snapshots"] = {rel: baseline}
    doc["final_source_hashes"] = {rel: hashlib.sha256(dev_final.encode("utf-8")).hexdigest()}
    dev_report_path.write_text(json.dumps(doc), encoding="utf-8")

    checker = _load(CHECKER_PATH, "_checker_committed_peer_test")
    assert checker._git_status_code(root, rel) is None  # clean: no porcelain line at all
    assert checker._is_tracked(root, rel) is True

    route_kind, detail = checker.route_file(root, task_id, rel, doc, dev_report_path)
    # Correctly ATTEMPTED via the real mechanism (not skipped) -- the reason
    # is git-apply's own, not the generic "no provenance mechanism declared".
    assert route_kind == "unroutable"
    assert "no provenance mechanism declared" not in detail
    assert "index-composable" in detail or "reversible" in detail


def test_ac9_untracked_modified_genuine_drift_is_unroutable_by_design(tmp_path: Path) -> None:
    """A genuine byte-level change to an already-adopted untracked file is,
    by stage-owned-hunks.py's own protected --untracked-modified-report
    contract (no partial-hunk mechanism exists for untracked files), always
    unroutable -- proving the negative control for this class."""
    task_id = "20260101-000312"
    root = tmp_path
    fx.build_beyond_qa_clean(root, task_id)
    _init_repo(root)
    import hashlib

    rel = "notes/untracked-mod.txt"
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    pre_bytes, adopted_final = b"before\n", b"after\n"
    path.write_bytes(b"a-further-unattributed-change\n")  # genuine post-adoption drift
    pre_sha, adopted_sha = hashlib.sha256(pre_bytes).hexdigest(), hashlib.sha256(adopted_final).hexdigest()

    dev_report_path = root / "docs" / "dev" / f"dev-report-{task_id}.json"
    doc = json.loads(dev_report_path.read_text(encoding="utf-8"))
    doc["dev"]["files_modified"] = [rel]
    doc["pre_edit_provenance"] = {
        "verified_before_edit": True, "source": "test",
        "files": {rel: pre_sha}, "statuses": {rel: "??"},
    }
    doc["untracked_modified_provenance"] = {
        rel: {
            "path": rel, "admission": "authenticated_preexisting_untracked_whole_file",
            "pre_edit": {"git_status": "??", "sha256": pre_sha},
            "final": {"git_status": "??", "sha256": adopted_sha},
            "evidence_source": "test",
        }
    }
    doc["final_source_hashes"] = {rel: adopted_sha}
    dev_report_path.write_text(json.dumps(doc), encoding="utf-8")

    checker = _load(CHECKER_PATH, "_checker_under_test")
    drift = checker.detect_drift(root, doc)
    assert rel in drift
    route_kind, detail = checker.route_file(root, task_id, rel, doc, dev_report_path)
    assert route_kind == "unroutable", detail


def test_ac9_regression_no_run_record_leaves_resolution_untouched(tmp_path: Path) -> None:
    task_id = "20260101-000320"
    root = tmp_path
    fx.build_complete(root, task_id)
    state, path = CONTROLLER.resolve_effective_report_state(root, task_id)
    assert state == "none"
    assert path is None


def test_ac9_tri_state_fail_closed_on_uncorroborated_effective_state(tmp_path: Path) -> None:
    task_id = "20260101-000330"
    root = tmp_path
    fx.build_beyond_qa_clean(root, task_id)
    run_id = _init_and_record_all_stages(root, task_id)
    finalize = _run_controller("finalize", "--task-id", task_id, "--project-dir", str(root), "--repair-run-id", run_id)
    assert finalize.returncode == 0
    # Tamper with the run record's stored dev-stage hash to simulate a later
    # corroboration failure (drift/corruption discovered after finalize).
    run_record_path = _run_record_path(root, task_id)
    record = json.loads(run_record_path.read_text(encoding="utf-8"))
    record["stages"]["ba"]["sha256"] = "0" * 64
    run_record_path.write_text(json.dumps(record), encoding="utf-8")

    state, path = CONTROLLER.resolve_effective_report_state(root, task_id)
    assert state == "invalid"
    assert path is None


# ---------------------------------------------------------------------------
# AC-10: disclosure corroboration negative controls + positive control.
# ---------------------------------------------------------------------------

def test_ac10_disclosure_negative_controls_and_positive_control(tmp_path: Path) -> None:
    task_id = "20260101-000400"
    root = tmp_path
    fx.build_beyond_qa_clean(root, task_id)
    run_id = _init_and_record_all_stages(root, task_id)
    finalize = _run_controller("finalize", "--task-id", task_id, "--project-dir", str(root), "--repair-run-id", run_id)
    assert finalize.returncode == 0

    # Positive control first (establishes the baseline is genuinely admitted).
    positive = _run_controller("verify-disclosure", "--task-id", task_id, "--project-dir", str(root))
    assert positive.returncode == 0
    assert _last_json(positive)["outcome"] == "admitted"

    dev_dir = root / "docs" / "dev"
    ticket_path = dev_dir / f"ticket-{task_id}.md"
    original_ticket = ticket_path.read_text(encoding="utf-8")

    # (i) run record entirely absent.
    other_task = "20260101-000401"
    other_root = tmp_path / "other"
    fx.build_beyond_qa_clean(other_root, other_task)
    case_i = _run_controller("verify-disclosure", "--task-id", other_task, "--project-dir", str(other_root))
    assert case_i.returncode != 0
    reason_i = _last_json(case_i)["reason"]
    assert "not independently corroborated" in reason_i
    assert "no matching run record" in reason_i

    # (ii) repair_run_id matches, but hash mismatches (corrupt after the fact).
    ticket_path.write_text(original_ticket + "\ncorrupted\n", encoding="utf-8")
    case_ii = _run_controller("verify-disclosure", "--task-id", task_id, "--project-dir", str(root))
    assert case_ii.returncode != 0
    assert "hash mismatch" in _last_json(case_ii)["reason"]
    ticket_path.write_text(original_ticket, encoding="utf-8")  # restore

    # (iii) disclosure block missing entirely.
    stripped = json.loads((dev_dir / f"dev-report-{task_id}.json").read_text(encoding="utf-8"))
    stripped.pop("retrospective_disclosure", None)
    dev_report_backup = (dev_dir / f"dev-report-{task_id}.json").read_text(encoding="utf-8")
    (dev_dir / f"dev-report-{task_id}.json").write_text(json.dumps(stripped), encoding="utf-8")
    case_iii = _run_controller("verify-disclosure", "--task-id", task_id, "--project-dir", str(root))
    assert case_iii.returncode != 0
    assert "missing on an expected artifact" in _last_json(case_iii)["reason"]
    (dev_dir / f"dev-report-{task_id}.json").write_text(dev_report_backup, encoding="utf-8")

    # (iv) disclosure present but malformed -- one field missing per sub-case.
    for field in ("route", "repair_run_id", "original_cycle_at", "produced_at", "artifact"):
        doc = json.loads((dev_dir / f"dev-report-{task_id}.json").read_text(encoding="utf-8"))
        del doc["retrospective_disclosure"][field]
        (dev_dir / f"dev-report-{task_id}.json").write_text(json.dumps(doc), encoding="utf-8")
        case_iv = _run_controller("verify-disclosure", "--task-id", task_id, "--project-dir", str(root))
        assert case_iv.returncode != 0, field
        assert field in _last_json(case_iv)["reason"], field
        (dev_dir / f"dev-report-{task_id}.json").write_text(dev_report_backup, encoding="utf-8")

    # (v) route field wrong.
    doc = json.loads((dev_dir / f"dev-report-{task_id}.json").read_text(encoding="utf-8"))
    doc["retrospective_disclosure"]["route"] = "not-a-real-route"
    (dev_dir / f"dev-report-{task_id}.json").write_text(json.dumps(doc), encoding="utf-8")
    case_v = _run_controller("verify-disclosure", "--task-id", task_id, "--project-dir", str(root))
    assert case_v.returncode != 0
    assert "route mismatch" in _last_json(case_v)["reason"]
    (dev_dir / f"dev-report-{task_id}.json").write_text(dev_report_backup, encoding="utf-8")

    # (vi) artifact identity mismatch.
    doc = json.loads((dev_dir / f"dev-report-{task_id}.json").read_text(encoding="utf-8"))
    doc["retrospective_disclosure"]["artifact"] = "some-other-file.json"
    (dev_dir / f"dev-report-{task_id}.json").write_text(json.dumps(doc), encoding="utf-8")
    case_vi = _run_controller("verify-disclosure", "--task-id", task_id, "--project-dir", str(root))
    assert case_vi.returncode != 0
    assert "identity mismatch" in _last_json(case_vi)["reason"]
    (dev_dir / f"dev-report-{task_id}.json").write_text(dev_report_backup, encoding="utf-8")

    # Confirm the fixture is still admitted after every restore (sanity that
    # the negative controls did not leave permanent damage).
    final_check = _run_controller("verify-disclosure", "--task-id", task_id, "--project-dir", str(root))
    assert final_check.returncode == 0
    assert _last_json(final_check)["outcome"] == "admitted"


# ---------------------------------------------------------------------------
# AC-11: bare /close never invokes the controller; --late-repair does.
# ---------------------------------------------------------------------------

def test_ac11_bare_close_route_select_never_calls_controller(tmp_path: Path) -> None:
    task_id = "20260101-000500"
    root = tmp_path
    fx.build_qa_only(root, task_id)  # AC-4's shape: missing QA (and here, singular qa_only).
    before = {p: p.read_bytes() for p in (root / "docs" / "dev").rglob("*") if p.is_file()}

    calls = {"count": 0}
    original = ROUTE_SELECT._controller_module

    def _counting_controller():
        calls["count"] += 1
        return original()

    ROUTE_SELECT._controller_module = _counting_controller
    try:
        rc, payload = ROUTE_SELECT.run(task_id, str(root), False, False)
    finally:
        ROUTE_SELECT._controller_module = original

    assert payload["outcome"] == "not_selected"
    assert calls["count"] == 0
    assert not _run_record_path(root, task_id).is_file()
    after = {p: p.read_bytes() for p in (root / "docs" / "dev").rglob("*") if p.is_file()}
    assert before == after


def test_ac11_late_repair_flag_is_the_only_behavior_switch(tmp_path: Path) -> None:
    task_id = "20260101-000510"
    root = tmp_path
    fx.build_beyond_qa_clean(root, task_id)

    calls = {"count": 0}
    original = ROUTE_SELECT._controller_module

    def _counting_controller():
        calls["count"] += 1
        return original()

    ROUTE_SELECT._controller_module = _counting_controller
    try:
        rc0, payload0 = ROUTE_SELECT.run(task_id, str(root), False, False)
        assert calls["count"] == 0
        rc1, payload1 = ROUTE_SELECT.run(task_id, str(root), True, False)
        assert calls["count"] == 1
    finally:
        ROUTE_SELECT._controller_module = original

    assert payload0["outcome"] == "not_selected"
    assert payload1["outcome"] == "initialized"
    assert rc1 == 0


def test_ac11_static_grep_confirms_close_md_uses_close_route_select(tmp_path: Path) -> None:
    close_md = (REPO_ROOT / "commands" / "close.md").read_text(encoding="utf-8")
    late_repair_occurrences = [
        idx for idx in range(len(close_md)) if close_md.startswith("--late-repair", idx)
    ]
    assert late_repair_occurrences, "commands/close.md must mention --late-repair"
    section_start = close_md.index("### Late-repair route")
    section_end = close_md.index("\n### ", section_start + 1) if "\n### " in close_md[section_start + 1:] else len(close_md)
    for idx in late_repair_occurrences:
        assert section_start <= idx < section_end, "‑-late-repair token must occur only in the R4 section"
    assert "scripts/close-route-select.py" in close_md
    assert "late-repair-controller.py" not in close_md.split("### Late-repair route")[0]


# ---------------------------------------------------------------------------
# AC-13: absent dev-report, with and without independently corroborable evidence.
# ---------------------------------------------------------------------------

def test_ac13_no_dev_report_with_evidence_completes_via_fresh_dev_report(tmp_path: Path) -> None:
    task_id = "20260101-000600"
    root = tmp_path
    _init_repo(root)
    dev_dir = root / "docs" / "dev"
    dev_dir.mkdir(parents=True)
    ticket_path = dev_dir / f"ticket-{task_id}.md"
    ticket_path.write_text(fx._ticket(task_id), encoding="utf-8")
    target = root / "src" / "corroborated.py"
    target.parent.mkdir(parents=True)
    target.write_text("# original\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "earliest touch of corroborated.py")
    context_path = dev_dir / f"context-{task_id}.json"
    context_path.write_text(json.dumps({
        "request_id": task_id, "task_id": task_id,
        "requirement": {"where": ["src/corroborated.py"]},
    }), encoding="utf-8")
    # dev-report and completion intentionally absent.

    init = _run_controller("init", "--task-id", task_id, "--project-dir", str(root))
    assert init.returncode == 0, init.stdout
    payload = _last_json(init)
    run_id = payload["repair_run_id"]
    record = json.loads(_run_record_path(root, task_id).read_text(encoding="utf-8"))
    assert record["original_cycle_at"] is not None
    assert record["original_cycle_at_source"] == "earliest_git_commit"

    ba = _run_controller(
        "record-stage", "--task-id", task_id, "--project-dir", str(root),
        "--stage", "ba", "--report-path", str(ticket_path), "--repair-run-id", run_id,
    )
    assert ba.returncode == 0

    dev_report_path = dev_dir / f"dev-report-{task_id}.json"
    assert not dev_report_path.is_file()
    # Genuine Dev rerun produces a NEW dev-report BEFORE record-stage --stage dev.
    dev_report_path.write_text(json.dumps(fx._dev_document(task_id)), encoding="utf-8")

    dev_stage = _run_controller(
        "record-stage", "--task-id", task_id, "--project-dir", str(root),
        "--stage", "dev", "--report-path", str(dev_report_path), "--repair-run-id", run_id,
    )
    assert dev_stage.returncode == 0

    qa_path = dev_dir / f"qa-report-{task_id}.json"
    qa_path.write_text(json.dumps(fx._qa_document(task_id)), encoding="utf-8")
    qa_stage = _run_controller(
        "record-stage", "--task-id", task_id, "--project-dir", str(root),
        "--stage", "qa", "--report-path", str(qa_path), "--repair-run-id", run_id,
    )
    assert qa_stage.returncode == 0

    finalize = _run_controller("finalize", "--task-id", task_id, "--project-dir", str(root), "--repair-run-id", run_id)
    assert finalize.returncode == 0
    assert _last_json(finalize)["outcome"] == "finalized_pending_verification"
    assert _last_json(finalize)["drift_detected"] == {}

    verify = _run_controller("verify-disclosure", "--task-id", task_id, "--project-dir", str(root))
    assert verify.returncode == 0
    assert _last_json(verify)["outcome"] == "admitted"

    dev_doc = json.loads(dev_report_path.read_text(encoding="utf-8"))
    assert dev_doc["retrospective_disclosure"]["original_cycle_at"] == record["original_cycle_at"]


def test_ac13_no_dev_report_no_evidence_fails_closed(tmp_path: Path) -> None:
    """Reproduces QA's exact live finding and proves the fix closes it.

    QA's reported sequence: init (no context, no git repo -> original_cycle_at
    None) -> record-stage --stage ba succeeds -> a fabricated dev-report is
    written -> record-stage --stage dev ACCEPTS it with zero check of
    original_cycle_at -> finalize/verify-disclosure both succeed. The shipped
    fix gates EVERY stage (ba/dev/qa) -- QA's "more conservative" reading --
    whenever original_cycle_at is None AND the dev-report was itself absent
    (a stage gap) at init time, so this test drives the identical sequence
    and asserts outcome=='fail_closed' specifically (not a generic non-zero
    exit code) at every stage attempt, that the controller never certifies
    (embeds a disclosure into, or records in the run record's stages) any
    fabricated report, and that no dev-report of any name is ever produced
    BY THE CONTROLLER, so the overall sequence can never reach admission.
    """
    task_id = "20260101-000610"
    root = tmp_path
    dev_dir = root / "docs" / "dev"
    dev_dir.mkdir(parents=True)
    ticket_path = dev_dir / f"ticket-{task_id}.md"
    ticket_path.write_text(fx._ticket(task_id), encoding="utf-8")
    # No context (so no `where` list), no git repo at all -> no corroborable evidence.

    init = _run_controller("init", "--task-id", task_id, "--project-dir", str(root))
    assert init.returncode == 0
    run_id = _last_json(init)["repair_run_id"]
    record = json.loads(_run_record_path(root, task_id).read_text(encoding="utf-8"))
    assert record["original_cycle_at"] is None
    assert record["original_cycle_at_source"] == "none"
    dev_report_rel = f"docs/dev/dev-report-{task_id}.json"
    assert dev_report_rel in record["live_snapshot"]["stage_gaps"]

    # 'ba' is gated identically: with no dev-report at all AND no
    # corroborable evidence, the whole route refuses at the very first
    # stage rather than letting 'ba' succeed pointlessly.
    ba = _run_controller(
        "record-stage", "--task-id", task_id, "--project-dir", str(root),
        "--stage", "ba", "--report-path", str(ticket_path), "--repair-run-id", run_id,
    )
    assert ba.returncode == 6, ba.stdout
    assert _last_json(ba)["outcome"] == "fail_closed"
    assert "retrospective_disclosure" not in ticket_path.read_text(encoding="utf-8")

    # Reproduce the exact attack: a fabricated dev-report appears on disk at
    # the canonical path record-stage/finalize both consult, and record-stage
    # --stage dev is pointed at it directly.
    dev_report_path = dev_dir / f"dev-report-{task_id}.json"
    dev_report_path.write_text(json.dumps(fx._dev_document(task_id)), encoding="utf-8")
    pre_bytes = dev_report_path.read_bytes()

    dev_stage = _run_controller(
        "record-stage", "--task-id", task_id, "--project-dir", str(root),
        "--stage", "dev", "--report-path", str(dev_report_path), "--repair-run-id", run_id,
    )
    assert dev_stage.returncode == 6, dev_stage.stdout
    assert _last_json(dev_stage)["outcome"] == "fail_closed"

    # The controller must never certify the fabricated report: no bytes
    # changed (no retrospective_disclosure embedded), and the run record's
    # stages dict has no 'dev' entry.
    assert dev_report_path.read_bytes() == pre_bytes
    assert "retrospective_disclosure" not in json.loads(dev_report_path.read_text(encoding="utf-8"))
    updated_record = json.loads(_run_record_path(root, task_id).read_text(encoding="utf-8"))
    assert updated_record["stages"] == {}
    assert updated_record["outcome"] == "fail_closed"

    # 'qa' is refused identically (the gate fires before the out-of-order
    # check, so it is not merely relying on stage-order enforcement).
    qa_path = dev_dir / f"qa-report-{task_id}.json"
    qa_path.write_text(json.dumps(fx._qa_document(task_id)), encoding="utf-8")
    qa_stage = _run_controller(
        "record-stage", "--task-id", task_id, "--project-dir", str(root),
        "--stage", "qa", "--report-path", str(qa_path), "--repair-run-id", run_id,
    )
    assert qa_stage.returncode == 6
    assert _last_json(qa_stage)["outcome"] == "fail_closed"

    finalize = _run_controller("finalize", "--task-id", task_id, "--project-dir", str(root), "--repair-run-id", run_id)
    assert finalize.returncode != 0
    assert _last_json(finalize)["outcome"] != "finalized_pending_verification"

    # No dev-report of any name was ever produced BY THE CONTROLLER: the only
    # dev-report bytes on disk are the fabricated ones this test itself
    # planted (untouched); no .effective.json (a controller-only artifact)
    # exists at all. Since finalize never set effective_report on the run
    # record (it refused before reaching that point), the tri-state guard
    # /commit's own resolution chain relies on can never treat this run as
    # commit-eligible, regardless of verify-disclosure's own per-stage
    # (not whole-run-completeness) admission check.
    assert not (dev_dir / f"dev-report-{task_id}.effective.json").exists()
    state, _ = CONTROLLER.resolve_effective_report_state(root, task_id)
    assert state != "verified"


def test_ac13_no_dev_report_no_evidence_fails_closed_at_finalize_when_stages_complete(tmp_path: Path) -> None:
    """Retries every stage twice to prove the fail-closed gate is not a fluke.

    Even when a fresh, correctly-named fabricated report is presented for
    each of ba/dev/qa and each stage is retried, record-stage refuses with
    outcome=='fail_closed' every single time, the run record's stages dict
    never gains a single entry, and finalize can never reach
    'finalized_pending_verification' -- matching the AC's literal 'no
    dev-report of any name is written at any point in the sequence'
    guarantee even under repeated operator retries.
    """
    task_id = "20260101-000620"
    root = tmp_path
    dev_dir = root / "docs" / "dev"
    dev_dir.mkdir(parents=True)
    ticket_path = dev_dir / f"ticket-{task_id}.md"
    ticket_path.write_text(fx._ticket(task_id), encoding="utf-8")

    init = _run_controller("init", "--task-id", task_id, "--project-dir", str(root))
    run_id = _last_json(init)["repair_run_id"]
    record = json.loads(_run_record_path(root, task_id).read_text(encoding="utf-8"))
    assert record["original_cycle_at"] is None

    dev_report_path = dev_dir / f"dev-report-{task_id}.json"
    dev_report_path.write_text(json.dumps(fx._dev_document(task_id)), encoding="utf-8")
    qa_report_path = dev_dir / f"qa-report-{task_id}.json"
    qa_report_path.write_text(json.dumps(fx._qa_document(task_id)), encoding="utf-8")

    for attempt_number in (1, 2):
        for stage, path in (("ba", ticket_path), ("dev", dev_report_path), ("qa", qa_report_path)):
            attempt = _run_controller(
                "record-stage", "--task-id", task_id, "--project-dir", str(root),
                "--stage", stage, "--report-path", str(path), "--repair-run-id", run_id,
            )
            assert attempt.returncode == 6, (attempt_number, stage, attempt.stdout)
            assert _last_json(attempt)["outcome"] == "fail_closed"

    updated_record = json.loads(_run_record_path(root, task_id).read_text(encoding="utf-8"))
    assert updated_record["stages"] == {}
    assert updated_record["outcome"] == "fail_closed"

    finalize = _run_controller("finalize", "--task-id", task_id, "--project-dir", str(root), "--repair-run-id", run_id)
    assert finalize.returncode != 0
    assert _last_json(finalize)["outcome"] != "finalized_pending_verification"
    assert not (dev_dir / f"dev-report-{task_id}.effective.json").exists()
    for path in (ticket_path, dev_report_path, qa_report_path):
        assert "retrospective_disclosure" not in path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# AC-14: R4 does not grandfather pre-R4 backfills, including lane 20260906-085036's shape.
# ---------------------------------------------------------------------------

def test_ac14_pre_r4_backfill_with_well_formed_disclosure_is_refused(tmp_path: Path) -> None:
    task_id = "20260101-000700"
    root = tmp_path
    fx.build_complete(root, task_id)  # complete chain, exactly like a finished backfill.
    dev_dir = root / "docs" / "dev"
    ticket_path = dev_dir / f"ticket-{task_id}.md"
    # Hand-add an otherwise well-formed disclosure block -- no run record was
    # ever created via init while this chain was beyond_qa (it is complete
    # right now, and always was, in this fixture).
    hand_added = CONTROLLER._embed_disclosure  # reuse the exact embedding format
    hand_added(ticket_path, {
        "route": "R4-late-repair",
        "repair_run_id": "hand-crafted-repair-run-id",
        "original_cycle_at": "2026-01-01T00:00:00+00:00",
        "produced_at": "2026-01-01T00:00:00+00:00",
        "artifact": ticket_path.name,
    })
    assert not _run_record_path(root, task_id).is_file()

    verify = _run_controller("verify-disclosure", "--task-id", task_id, "--project-dir", str(root))
    assert verify.returncode != 0
    payload = _last_json(verify)
    assert payload["outcome"] == "refused"
    assert "no matching run record" in payload["reason"]


# ---------------------------------------------------------------------------
# AC-9(b) companion tests: the guarded, corroboration-gated resolution chain
# (resolve-commit-repos.py, resolve-dev-report.py, stage-owned-hunks.py) --
# regression (State A unaffected), verified selection (State B), and
# fail-closed (State C, never a silent fallback to stale canonical).
# ---------------------------------------------------------------------------

def _produce_verified_effective_report(root: Path, task_id: str) -> Path:
    """Minimal reconcilable-drift setup producing a verified .effective.json."""
    fx.build_beyond_qa_clean(root, task_id)
    _init_repo(root)
    tracked_rel = "src/companion.py"
    tracked_path = root / tracked_rel
    tracked_path.parent.mkdir(parents=True, exist_ok=True)
    baseline = "a\nb\nc\n"
    tracked_path.write_text(baseline, encoding="utf-8")
    _git(root, "add", tracked_rel)
    _git(root, "commit", "-q", "-m", "baseline")
    dev_final = "a\nB\nc\n"
    worktree = "a\nB\nc\nPEER\n"
    tracked_path.write_text(worktree, encoding="utf-8")

    dev_report_path = root / "docs" / "dev" / f"dev-report-{task_id}.json"
    doc = json.loads(dev_report_path.read_text(encoding="utf-8"))
    doc["dev"]["files_modified"] = [tracked_rel]
    doc["owned_edits"] = {tracked_rel: [{"old": "b\n", "new": "B\n"}]}
    doc["pre_edit_snapshots"] = {tracked_rel: baseline}
    import hashlib
    doc["final_source_hashes"] = {tracked_rel: hashlib.sha256(dev_final.encode()).hexdigest()}
    dev_report_path.write_text(json.dumps(doc), encoding="utf-8")

    run_id = _init_and_record_all_stages(root, task_id)
    finalize = _run_controller("finalize", "--task-id", task_id, "--project-dir", str(root), "--repair-run-id", run_id)
    assert finalize.returncode == 0, finalize.stdout
    verify = _run_controller("verify-disclosure", "--task-id", task_id, "--project-dir", str(root))
    assert verify.returncode == 0, verify.stdout
    return _effective_path(root, task_id)


def test_ac9_companion_resolve_commit_repos_selects_effective_report_when_verified(tmp_path: Path) -> None:
    task_id = "20260101-000800"
    root = tmp_path
    effective_path = _produce_verified_effective_report(root, task_id)

    repos_module = _load(REPO_ROOT / "scripts" / "resolve-commit-repos.py", "_resolve_commit_repos_under_test")
    plan = repos_module.build_plan(
        task_id=task_id,
        control_root_arg=str(root),
        supported_repo_args=[],
        report_arg=None,
    )
    assert Path(plan["report_path"]).resolve() == effective_path.resolve()


def test_ac9_companion_resolve_commit_repos_regression_no_run_record(tmp_path: Path) -> None:
    task_id = "20260101-000810"
    root = tmp_path
    fx.build_complete(root, task_id)
    _init_repo(root)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "fixture baseline")
    repos_module = _load(REPO_ROOT / "scripts" / "resolve-commit-repos.py", "_resolve_commit_repos_under_test_b")
    plan = repos_module.build_plan(
        task_id=task_id,
        control_root_arg=str(root),
        supported_repo_args=[],
        report_arg=None,
    )
    expected = (root / "docs" / "dev" / f"dev-report-{task_id}.json").resolve()
    assert Path(plan["report_path"]).resolve() == expected


def test_ac9_companion_resolve_commit_repos_fails_closed_when_uncorroborated(tmp_path: Path) -> None:
    task_id = "20260101-000820"
    root = tmp_path
    effective_path = _produce_verified_effective_report(root, task_id)
    run_record_path = _run_record_path(root, task_id)
    record = json.loads(run_record_path.read_text(encoding="utf-8"))
    record["stages"]["ba"]["sha256"] = "0" * 64
    run_record_path.write_text(json.dumps(record), encoding="utf-8")

    repos_module = _load(REPO_ROOT / "scripts" / "resolve-commit-repos.py", "_resolve_commit_repos_under_test_c")
    try:
        repos_module.build_plan(
            task_id=task_id,
            control_root_arg=str(root),
            supported_repo_args=[],
            report_arg=str(effective_path),
        )
        raised = False
    except repos_module.PlanError:
        raised = True
    assert raised, "expected State C to fail closed via PlanError, not silently resolve"


def test_ac9_companion_resolve_dev_report_selects_effective_when_verified(tmp_path: Path) -> None:
    task_id = "20260101-000830"
    root = tmp_path
    effective_path = _produce_verified_effective_report(root, task_id)
    proc = subprocess.run(
        [
            sys.executable, str(REPO_ROOT / "scripts" / "resolve-dev-report.py"),
            "--task-id", task_id, "--git-root", str(root), "--control-root", str(root),
        ],
        input=f"M docs/dev/dev-report-{task_id}.json\n",
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0
    assert Path(proc.stdout.strip()).resolve() == effective_path.resolve()


def test_ac9_companion_stage_owned_hunks_requires_flag_for_effective_basename(tmp_path: Path) -> None:
    task_id = "20260101-000840"
    root = tmp_path
    _init_repo(root)
    import hashlib

    rel = "notes/flagged.txt"
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    pre_bytes, final_bytes = b"before\n", b"after\n"
    path.write_bytes(final_bytes)
    pre_sha, final_sha = hashlib.sha256(pre_bytes).hexdigest(), hashlib.sha256(final_bytes).hexdigest()

    doc = {
        "request_id": task_id, "task_id": task_id,
        "dev": {"status": "completed", "files_modified": [rel], "files_created": []},
        "pre_edit_provenance": {
            "verified_before_edit": True, "source": "test",
            "files": {rel: pre_sha}, "statuses": {rel: "??"},
        },
        "untracked_modified_provenance": {
            rel: {
                "path": rel, "admission": "authenticated_preexisting_untracked_whole_file",
                "pre_edit": {"git_status": "??", "sha256": pre_sha},
                "final": {"git_status": "??", "sha256": final_sha},
                "evidence_source": "test",
            }
        },
        "final_source_hashes": {rel: final_sha},
    }
    effective_path = root / "docs" / "dev" / f"dev-report-{task_id}.effective.json"
    effective_path.parent.mkdir(parents=True, exist_ok=True)
    effective_path.write_text(json.dumps(doc), encoding="utf-8")
    digest = hashlib.sha256(effective_path.read_bytes()).hexdigest()

    stage_script = REPO_ROOT / "scripts" / "stage-owned-hunks.py"

    without_flag = subprocess.run(
        [sys.executable, str(stage_script), "--git-root", str(root), "--file", rel,
         "--untracked-modified-report", str(effective_path), "--report-sha256", digest,
         "--task-id", task_id, "--plan-only"],
        capture_output=True, text=True,
    )
    assert without_flag.returncode == 10
    assert "filename does not match task" in without_flag.stderr

    with_flag = subprocess.run(
        [sys.executable, str(stage_script), "--git-root", str(root), "--file", rel,
         "--untracked-modified-report", str(effective_path), "--report-sha256", digest,
         "--task-id", task_id, "--plan-only", "--effective-report-verified"],
        capture_output=True, text=True,
    )
    assert with_flag.returncode == 0, with_flag.stderr


def test_ac14_lane_20260906_085036_shape_is_refused_by_the_same_mechanism(tmp_path: Path) -> None:
    # Modeled directly on the motivating lane's own live-measured shape: a
    # structurally-complete chain (resolver status: pass) with no late-repair
    # run record, per BA's measurement this session.
    task_id = "20260906-085036"
    root = tmp_path
    fx.build_complete(root, task_id)
    dev_dir = root / "docs" / "dev"
    ticket_path = dev_dir / f"ticket-{task_id}.md"
    CONTROLLER._embed_disclosure(ticket_path, {
        "route": "R4-late-repair",
        "repair_run_id": "backfilled-before-r4-existed",
        "original_cycle_at": "2026-09-06T00:00:00+00:00",
        "produced_at": "2026-09-10T00:00:00+00:00",
        "artifact": ticket_path.name,
    })
    resolver = CONTROLLER._load_sibling_module("resolve-dev-artifact-chain.py")
    result = resolver.resolve_chain(root, task_id)
    assert result["status"] == "pass"
    assert result["gap_classification"] == "complete"

    verify = _run_controller("verify-disclosure", "--task-id", task_id, "--project-dir", str(root))
    assert verify.returncode != 0
    assert "no matching run record" in _last_json(verify)["reason"]


# ---------------------------------------------------------------------------
# AC-12: the cross-repo spec-text insertion (spec-20260907-115508-lawful-
# commit-channel.md, in the OTHER repository) is a pure addition against the
# pinned pre-R4 golden image. Ported from the test-writer scaffold at
# tests/generated/20260910-091226/test_AC_12_e6075609532ca13b.py -- that
# directory is gitignored by design (.gitignore's `tests/generated/*` rule),
# so the scaffold alone left the pinned golden fixture
# (tests/fixtures/late_repair_golden/spec-20260907-115508-lawful-commit-
# channel.pre-r4.md) unreferenced by any committed test. This is the
# fixture's one committed, load-bearing consumer.
# ---------------------------------------------------------------------------

AC12_PINNED_PRE_IMAGE_PATH = (
    REPO_ROOT / "tests" / "fixtures" / "late_repair_golden"
    / "spec-20260907-115508-lawful-commit-channel.pre-r4.md"
)
AC12_SPEC_PATH = Path.home() / "docs" / "dev" / "specs" / "spec-20260907-115508-lawful-commit-channel.md"
AC12_PINNED_SHA256 = "9b38e77b80ceb0b8b09ebd2dee919229a8889b60783f3738d1f30d6eb4d4d19b"
AC12_PINNED_LINE_COUNT = 300


def test_ac12_cross_repo_spec_text_insertion_is_pure_addition() -> None:
    """
    GIVEN: spec-20260907-115508-lawful-commit-channel.md's current R1/R2/R3
           text and AC-1..AC-5, pinned this session (the file is gitignored
           in its own /root repository per the spec's own Section 5 -- git
           diff is unavailable; a byte/line pin is the only mechanism)
    WHEN:  the orchestrator applies this ticket's supplied R4 requirement
           text and AC-6..AC-15 text
    THEN:  a byte/line diff (difflib.unified_diff) against the pinned
           pre-image shows only additions at the two identified insertion
           points, with zero bytes changed within the pinned R1/R2/R3 text
           or AC-1..AC-5 text
    """
    import difflib
    import hashlib

    pre_image_bytes = AC12_PINNED_PRE_IMAGE_PATH.read_bytes()
    assert hashlib.sha256(pre_image_bytes).hexdigest() == AC12_PINNED_SHA256
    pre_lines = pre_image_bytes.decode("utf-8").splitlines(keepends=True)
    assert len(pre_lines) == AC12_PINNED_LINE_COUNT
    # Pinned insertion-point anchors (1-indexed per the ticket's AC-12 pin).
    assert pre_lines[97].rstrip("\n").endswith("prohibited.")  # line 98
    assert pre_lines[99].strip() == "## 3. Acceptance criteria"  # line 100
    assert pre_lines[101].lstrip().startswith("- **AC-1**")  # line 102
    assert pre_lines[110].lstrip().startswith("- **AC-5**")  # line 111
    assert pre_lines[112].strip() == "## 4. Explicitly out of scope"  # line 113

    post_lines = AC12_SPEC_PATH.read_text(encoding="utf-8").splitlines(keepends=True)

    # Lines 1-98 (index 0..97) byte-identical.
    assert post_lines[:98] == pre_lines[:98]

    # An R4 block is inserted strictly between pinned line 98 and 100.
    ac_header_idx = next(
        i for i, line in enumerate(post_lines) if line.strip() == "## 3. Acceptance criteria"
    )
    assert ac_header_idx >= 98
    inserted_r4_block = post_lines[98:ac_header_idx]
    assert inserted_r4_block, "expected a non-empty inserted R4 block"
    assert any("### R4" in line for line in inserted_r4_block)

    # The pinned AC-1..AC-5 region must appear byte-identical, immediately
    # after the acceptance-criteria header.
    pinned_ac1_5 = pre_lines[101:111]
    post_ac1_5_start = ac_header_idx + 2  # header line + the blank line that follows it
    post_ac1_5 = post_lines[post_ac1_5_start:post_ac1_5_start + len(pinned_ac1_5)]
    assert post_ac1_5 == pinned_ac1_5

    # An AC-6..AC-15 block is inserted strictly between pinned line 111 and 113.
    scope_header_idx = next(
        i for i, line in enumerate(post_lines) if line.strip() == "## 4. Explicitly out of scope"
    )
    inserted_ac_block = post_lines[post_ac1_5_start + len(pinned_ac1_5):scope_header_idx]
    assert inserted_ac_block, "expected a non-empty inserted AC-6..AC-15 block"
    assert any("**AC-6**" in line for line in inserted_ac_block)
    assert any("**AC-15**" in line for line in inserted_ac_block)

    # A byte/line diff confirms every non-equal opcode against the pinned
    # pre-image is a pure INSERTION (i1 == i2: nothing from the pre-image
    # consumed/replaced/deleted).
    matcher = difflib.SequenceMatcher(a=pre_lines, b=post_lines, autojunk=False)
    opcodes = [op for op in matcher.get_opcodes() if op[0] != "equal"]
    assert opcodes, "expected at least the two insertions"
    for tag, i1, i2, j1, j2 in opcodes:
        assert tag == "insert", f"non-insert opcode found: {tag} pre[{i1}:{i2}] post[{j1}:{j2}]"
        assert i1 == i2, f"insertion unexpectedly consumed pinned content at pre[{i1}:{i2}]"
