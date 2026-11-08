#!/usr/bin/env python3
"""R4 late-repair route: monotonicity, negative controls, and hash-independence.

Covers AC-7..AC-11, AC-13, AC-14 (spec-20260907-115508-lawful-commit-channel.md,
docs/dev/acceptance-criteria-20260910-091226.json). AC-6/AC-15 (resolver gap
classification) live in tests/test_resolve_dev_artifact_chain.py. AC-12 (the
cross-repo spec-text insertion) is a data check against a file outside this
repository and is not covered by this suite.

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
    # record-stage records the stage and the report's path, and no hash of it
    # (P1b row 6: G2 checked the report at its producer's stop).
    assert _last_json(ba) == {"outcome": "recorded", "stage": "ba"}

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

    # A stage recorded again (its producer's next round) replaces its entry:
    # row 6 drops the duplicate refusal, which only kept a stored hash. The
    # record is kept once per dispatch (P1c review 1): the dispatch already
    # recorded is refused, and the next round's fresh dispatch is recorded.
    record_dev = (
        "record-stage", "--task-id", task_id, "--project-dir", str(root),
        "--stage", "dev", "--report-path", str(dev_dir / f"dev-report-{task_id}.json"),
        "--repair-run-id", run_id,
    )
    same = _run_controller(*record_dev)
    assert same.returncode == 3 and "already recorded" in _last_json(same)["reason"]
    _dispatch_again(root, task_id, "dev")
    again = _run_controller(*record_dev)
    assert again.returncode == 0, again.stdout
    entry = json.loads(_run_record_path(root, task_id).read_text(encoding="utf-8"))["stages"]["dev"]
    assert entry["tool_use_id"] == f"toolu_dev_again_{task_id}"

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

    # verify-disclosure compares no stage report (P1b row 6): it reads
    # finalize's recorded outcome. A record finalize has not carried to its
    # outcome is refused, naming the run record's path.
    record["outcome"] = None
    _run_record_path(root, task_id).write_text(json.dumps(record), encoding="utf-8")
    unfinalized = _run_controller("verify-disclosure", "--task-id", task_id, "--project-dir", str(root))
    assert unfinalized.returncode == 3
    refused = _last_json(unfinalized)
    assert "not independently corroborated" in refused["reason"]
    assert refused["path"] == f"docs/dev/late-repair-run-{task_id}.json"


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
    # A record that no longer holds finalize's outcome (finalize's refusal on
    # a later run, or a record rewritten since) fails closed.
    run_record_path = _run_record_path(root, task_id)
    record = json.loads(run_record_path.read_text(encoding="utf-8"))
    record["outcome"] = "honest_refuse"
    run_record_path.write_text(json.dumps(record), encoding="utf-8")

    state, path = CONTROLLER.resolve_effective_report_state(root, task_id)
    assert state == "invalid"
    # The path to route the finding on: the run record, whose outcome is not finalize's.
    assert path == run_record_path.resolve()


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

    # (i) run record entirely absent: the refusal names the run record's path.
    other_task = "20260101-000401"
    other_root = tmp_path / "other"
    fx.build_beyond_qa_clean(other_root, other_task)
    case_i = _run_controller("verify-disclosure", "--task-id", other_task, "--project-dir", str(other_root))
    assert case_i.returncode != 0
    payload_i = _last_json(case_i)
    assert "not independently corroborated" in payload_i["reason"]
    assert "no matching run record" in payload_i["reason"]
    assert payload_i["path"] == f"docs/dev/late-repair-run-{other_task}.json"

    # (ii) a stage report changed after the fact, and (iii) one removed: no
    # stage report is compared here (P1b row 6; G2 checked each at its
    # producer's stop), so the run stays admitted, and a removed report is the
    # gap the chain function names (/commit Step 5's call, row 7).
    ticket_path.write_text(original_ticket + "\ncorrupted\n", encoding="utf-8")
    case_ii = _run_controller("verify-disclosure", "--task-id", task_id, "--project-dir", str(root))
    assert case_ii.returncode == 0
    assert _last_json(case_ii)["outcome"] == "admitted"
    ticket_path.write_text(original_ticket, encoding="utf-8")  # restore

    qa_path = dev_dir / f"qa-report-{task_id}.json"
    qa_backup = qa_path.read_bytes()
    qa_path.unlink()
    case_iii = _run_controller("verify-disclosure", "--task-id", task_id, "--project-dir", str(root))
    assert case_iii.returncode == 0
    resolver = CONTROLLER._load_sibling_module("resolve-dev-artifact-chain.py")
    chain = resolver.resolve_chain(root, task_id)
    assert chain["status"] == "fail"
    assert f"docs/dev/qa-report-{task_id}.json" in [e.get("path") for e in chain["errors"]]
    qa_path.write_bytes(qa_backup)

    # (iv) a run record finalize has not carried to its outcome.
    run_record_path = _run_record_path(root, task_id)
    record_bytes = run_record_path.read_bytes()
    unfinalized = dict(json.loads(record_bytes), outcome=None)
    run_record_path.write_text(json.dumps(unfinalized), encoding="utf-8")
    case_iv = _run_controller("verify-disclosure", "--task-id", task_id, "--project-dir", str(root))
    assert case_iv.returncode != 0
    assert _last_json(case_iv)["path"] == f"docs/dev/late-repair-run-{task_id}.json"
    run_record_path.write_bytes(record_bytes)

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


def test_route_select_cli_passes_only_a_pass_chain_and_loads_a_legacy_needs_review_report(tmp_path: Path) -> None:
    # /close Step 0's arguments; a dev-report older code left as needs_review
    # with a status_rationale is a failing chain: exit 2 with the JSON.
    for task_id, legacy, expected_rc, expected_status in (
        ("20260101-000520", False, 0, "pass"),
        ("20260101-000521", True, 2, "fail"),
    ):
        root = tmp_path / task_id
        paths = fx.build_complete(root, task_id)
        if legacy:
            report = json.loads(paths["dev_report"].read_text(encoding="utf-8"))
            report["dev"]["status"] = "needs_review"
            report["dev"]["status_rationale"] = {
                "classification": "other_disclosed_handoff",
                "blocked_by": "a lane could not finish",
                "forbidden_action": "see the lane dev-report",
            }
            paths["dev_report"].write_text(json.dumps(report), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(ROUTE_SELECT_PATH), "--task-id", task_id, "--project-dir", str(root)],
            capture_output=True, text=True, check=False,
        )
        assert proc.returncode == expected_rc, proc.stderr
        assert "Traceback" not in proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["outcome"] == "not_selected"
        assert payload["artifact_chain"]["status"] == expected_status


def test_ac11_static_grep_confirms_close_md_reaches_init_only_in_the_r4_section(tmp_path: Path) -> None:
    # Routing invariant (P4): /close calls no route selector; its late-repair
    # section alone names the controller, whose init it calls once, and only
    # when --late-repair is passed. close-route-select.py stays, uncalled.
    close_md = (REPO_ROOT / "commands" / "close.md").read_text(encoding="utf-8")
    head, rest = close_md.split("### Late-repair route")
    r4 = rest.split("\n### ")[0]
    assert "close-route-select" not in close_md
    assert "late-repair-controller.py" not in head
    assert close_md.count("late-repair-controller.py") == r4.count("late-repair-controller.py")
    assert 'late-repair-controller.py" init --task-id "$TASK_ID"' in r4
    assert "without `--late-repair`, nothing in this section runs" in r4
    assert ROUTE_SELECT_PATH.is_file()


# ---------------------------------------------------------------------------
# AC-13: absent dev-report, with and without independently corroborable evidence.
# ---------------------------------------------------------------------------

def test_ac13_no_dev_report_with_evidence_completes_via_fresh_dev_report(tmp_path: Path) -> None:
    task_id = "20260101-000600"
    root = tmp_path
    _init_repo(root)
    dev_dir = root / "docs" / "dev"
    dev_dir.mkdir(parents=True)
    fx.declare_stage_dispatches(root, task_id)
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

    # record-stage writes nothing into the dev report: its one producer is dev.
    dev_doc = json.loads(dev_report_path.read_text(encoding="utf-8"))
    assert "retrospective_disclosure" not in dev_doc


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

def _hand_add_disclosure(path: Path, fields: dict[str, str]) -> None:
    """A backfill's hand-written block, in the markdown form the controller
    used to embed: verify-disclosure never reads such a block."""
    lines = ["<!-- retrospective_disclosure", *(f"{k}: {v}" for k, v in fields.items()), "-->"]
    text = path.read_text(encoding="utf-8").rstrip("\n")
    path.write_text(text + "\n\n" + "\n".join(lines) + "\n", encoding="utf-8")


def test_ac14_pre_r4_backfill_with_well_formed_disclosure_is_refused(tmp_path: Path) -> None:
    task_id = "20260101-000700"
    root = tmp_path
    fx.build_complete(root, task_id)  # complete chain, exactly like a finished backfill.
    dev_dir = root / "docs" / "dev"
    ticket_path = dev_dir / f"ticket-{task_id}.md"
    # Hand-add an otherwise well-formed disclosure block -- no run record was
    # ever created via init while this chain was beyond_qa (it is complete
    # right now, and always was, in this fixture).
    _hand_add_disclosure(ticket_path, {
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

def _reconcilable_drift_run(root: Path, task_id: str) -> str:
    """Minimal reconcilable-drift setup, every stage recorded; returns the run id."""
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

    return _init_and_record_all_stages(root, task_id)


def _produce_verified_effective_report(root: Path, task_id: str) -> Path:
    """Minimal reconcilable-drift setup producing a verified .effective.json."""
    run_id = _reconcilable_drift_run(root, task_id)
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


def _commit_step5_block() -> str:
    """commands/commit.md Step 5's repository-plan block, as the command spells it."""
    text = (REPO_ROOT / "commands" / "commit.md").read_text(encoding="utf-8")
    step5 = text[text.index("### Step 5:") : text.index("### Step 6:")]
    import re
    body = next(b for b in re.findall(r"```bash\n(.*?)```", step5, re.S) if "LATE_REPAIR_JSON" in b)
    assert "resolve-commit-repos.py" in body, body
    return "\n".join(line[2:] if line.startswith("  ") else line for line in body.splitlines())


def test_commit_step5_plans_from_the_verified_effective_report(tmp_path: Path) -> None:
    """P4 R5/R6 (late-repair entry as /commit uses it): with the controller's state verified,
    commit.md Step 5's own block plans from the effective report, which the changelog-analyst
    then admits into its whitelist because the plan names it (agents/changelog-analyst.md item 4)."""
    task_id = "20260101-000805"
    root = tmp_path / "project"
    effective_path = _produce_verified_effective_report(root, task_id)
    script = (_commit_step5_block() + '\nprintf "TASK_REPORT=%s\\n" "$TASK_REPORT"'
              + '\nprintf "PLAN=%s\\n" "$(jq -c . <<<"$REPOSITORY_PLAN")"\n')
    env = {**__import__("os").environ, "CLAUDE_HOME": str(REPO_ROOT), "TASK_ID": task_id,
           "CLOSE_REPORT": str(root / "docs" / "dev" / f"close-report-{task_id}.md")}
    proc = subprocess.run(["bash", "-c", script], cwd=root, env=env, capture_output=True, text=True)
    out = dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)
    assert json.loads(out["LATE_REPAIR"])["state"] == "verified", proc.stdout + proc.stderr
    assert Path(out["TASK_REPORT"]).resolve() == effective_path.resolve()
    assert Path(json.loads(out["PLAN"])["report_path"]).resolve() == effective_path.resolve()
    analyst = (REPO_ROOT / "agents" / "changelog-analyst.md").read_text(encoding="utf-8")
    assert "when `REPOSITORY_PLAN.report_path` is\n   `dev-report-<TASK_ID>.effective.json`" in analyst


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
    record["outcome"] = "honest_refuse"  # no longer finalize's outcome: State C
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
    _hand_add_disclosure(ticket_path, {
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
# P1b row 6: late repair writes only its own files, and finalize decides on
# the effective report it wrote.
# ---------------------------------------------------------------------------

def test_record_stage_writes_nothing_into_the_stage_reports(tmp_path: Path) -> None:
    task_id = "20260101-000900"
    root = tmp_path
    fx.build_beyond_qa_clean(root, task_id)
    dev_dir = root / "docs" / "dev"
    reports = {
        "ba": dev_dir / f"ticket-{task_id}.md",
        "dev": dev_dir / f"dev-report-{task_id}.json",
        "qa": dev_dir / f"qa-report-{task_id}.json",
    }
    reports["ba"].write_text(fx._ticket(task_id), encoding="utf-8")
    reports["qa"].write_text(json.dumps(fx._qa_document(task_id)), encoding="utf-8")
    before = {stage: path.read_bytes() for stage, path in reports.items()}

    run_id = _init_and_record_all_stages(root, task_id)

    record = json.loads(_run_record_path(root, task_id).read_text(encoding="utf-8"))
    assert record["repair_run_id"] == run_id
    for stage, path in reports.items():
        assert path.read_bytes() == before[stage], stage
        # the stage and its report's path; no hash of the report (P1b row 6)
        assert record["stages"][stage]["report_path"] == path.relative_to(root).as_posix()
        assert "sha256" not in record["stages"][stage]


def test_a_removed_stage_report_is_named_by_the_chain_call_at_commit(tmp_path: Path) -> None:
    """P1b row 6 and acceptance 7: a stage report removed after /close is no
    late-repair state (resolve-effective-report still prints none, comparing
    no stage report); /commit Step 5's chain call names it, and the dispatch
    that declared it runs again. A fresh report from that dispatch needs no
    re-record: nothing holds its old hash."""
    task_id = "20260101-000910"
    root = tmp_path
    fx.build_beyond_qa_clean(root, task_id)
    run_id = _init_and_record_all_stages(root, task_id)
    finalize = _run_controller("finalize", "--task-id", task_id, "--project-dir", str(root), "--repair-run-id", run_id)
    assert _last_json(finalize)["drift_detected"] == {}
    assert CONTROLLER.resolve_effective_report_state(root, task_id) == ("none", None)

    qa_path = root / "docs" / "dev" / f"qa-report-{task_id}.json"
    qa_bytes = qa_path.read_bytes()
    qa_path.unlink()
    assert CONTROLLER.resolve_effective_report_state(root, task_id) == ("none", None)
    printed = _last_json(_run_controller(
        "resolve-effective-report", "--task-id", task_id, "--project-dir", str(root),
    ))
    assert printed == {"state": "none", "path": None}
    resolver = CONTROLLER._load_sibling_module("resolve-dev-artifact-chain.py")
    chain = resolver.resolve_chain(root, task_id)
    assert [e.get("path") for e in chain["errors"]] == [f"docs/dev/qa-report-{task_id}.json"]

    # The QA dispatch's next round writes the report afresh, in other bytes.
    qa_path.write_text(json.dumps(json.loads(qa_bytes), indent=2), encoding="utf-8")
    assert qa_path.read_bytes() != qa_bytes
    assert resolver.resolve_chain(root, task_id)["errors"] == []
    assert CONTROLLER.resolve_effective_report_state(root, task_id) == ("none", None)


def _dispatch_again(root: Path, task_id: str, role: str) -> None:
    """The stage's dispatch run again: its record in the task's transcript, a fresh
    dispatched_at and its own tool_use id (toolu_<role>_again_<task>)."""
    import os
    store = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / str(root.resolve()).replace("/", "-")
    transcript = store / f"late-repair-{task_id}.jsonl"
    records = [json.loads(line) for line in transcript.read_text(encoding="utf-8").splitlines()]
    first = next(r for r in records if r["type"] == "assistant"
                 and r["message"]["content"][0]["input"]["subagent_type"] == role)
    again = json.loads(json.dumps(first).replace("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"))
    again["message"]["content"][0]["id"] = f"toolu_{role}_again_{task_id}"
    with transcript.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(again) + "\n")


def test_a_stage_dispatched_again_is_recorded_again_and_admitted(tmp_path: Path) -> None:
    """/commit's late-repair-qa case: the recorded QA report removed after CLOSE: YES, and the QA
    dispatch that declared it run again, which writes the report afresh (its own timestamp). The
    late-repair state compares no stage report (P1b row 6: Step 5's chain call names the removed
    one), so it stays none throughout; a second record of the dispatch already recorded is refused,
    and the fresh dispatch's report is recorded once, under its own tool_use id and with no hash,
    keeping finalize's outcome: the run stays admitted."""
    task_id = "20260101-000920"
    root = tmp_path
    fx.build_beyond_qa_clean(root, task_id)
    run_id = _init_and_record_all_stages(root, task_id)
    _run_controller("finalize", "--task-id", task_id, "--project-dir", str(root), "--repair-run-id", run_id)
    assert CONTROLLER.resolve_effective_report_state(root, task_id) == ("none", None)
    qa_path = root / "docs" / "dev" / f"qa-report-{task_id}.json"
    qa_path.unlink()
    qa_path.write_text(json.dumps(dict(fx._qa_document(task_id), timestamp="2026-01-02T00:00:00Z")), encoding="utf-8")
    assert CONTROLLER.resolve_effective_report_state(root, task_id) == ("none", None)
    record_qa = ("record-stage", "--task-id", task_id, "--project-dir", str(root), "--stage", "qa",
                 "--report-path", str(qa_path), "--repair-run-id", run_id)
    same = _run_controller(*record_qa)  # no dispatch ran since the record: the same dispatch's report
    assert same.returncode == 3 and "already recorded" in _last_json(same)["reason"]
    assert CONTROLLER.resolve_effective_report_state(root, task_id) == ("none", None)

    _dispatch_again(root, task_id, "qa")
    recorded = _run_controller(*record_qa)
    assert recorded.returncode == 0, recorded.stdout
    record = json.loads(_run_record_path(root, task_id).read_text(encoding="utf-8"))
    entry = record["stages"]["qa"]
    assert entry["report_path"] == f"docs/dev/qa-report-{task_id}.json" and "sha256" not in entry, entry
    assert entry["tool_use_id"] == f"toolu_qa_again_{task_id}"
    assert record["outcome"] == "finalized_pending_verification" and record["drift_detected"] == {}, record
    verify = _run_controller("verify-disclosure", "--task-id", task_id, "--project-dir", str(root))
    assert verify.returncode == 0 and _last_json(verify)["outcome"] == "admitted", verify.stdout
    assert CONTROLLER.resolve_effective_report_state(root, task_id) == ("none", None)
    assert _run_controller(*record_qa).returncode == 3


def test_a_dev_report_recorded_again_after_finalize_routes_to_finalize(tmp_path: Path) -> None:
    """finalize decides on the dev report. Its stage dispatched again after finalize ran and
    recorded again: the record clears finalize's outcome, so verify-disclosure (which reads that
    outcome, P1b row 6) refuses, naming the run record, and the effective-report resolution no
    longer takes finalize's earlier outcome. It names the effective report, whose owner is
    /close --late-repair's Step 0 (finalize, the main agent's own step); finalize run again under
    the run record's repair_run_id finalizes the chain, and verify-disclosure admits it."""
    sys.path.insert(0, str(REPO_ROOT))
    from hooks.lib.obligation import declaring_dispatch
    task_id = "20260101-000930"
    root = tmp_path
    fx.build_beyond_qa_clean(root, task_id)
    run_id = _init_and_record_all_stages(root, task_id)
    finalize = ("finalize", "--task-id", task_id, "--project-dir", str(root), "--repair-run-id", run_id)
    assert _last_json(_run_controller(*finalize))["outcome"] == "finalized_pending_verification"
    assert CONTROLLER.resolve_effective_report_state(root, task_id) == ("none", None)

    dev_path = root / "docs" / "dev" / f"dev-report-{task_id}.json"
    doc = json.loads(dev_path.read_text(encoding="utf-8"))
    doc["dev"]["tasks_completed"].append("dispatched again")
    dev_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    _dispatch_again(root, task_id, "dev")
    recorded = _run_controller("record-stage", "--task-id", task_id, "--project-dir", str(root), "--stage", "dev",
                               "--report-path", str(dev_path), "--repair-run-id", run_id)
    assert recorded.returncode == 0, recorded.stdout
    record = json.loads(_run_record_path(root, task_id).read_text(encoding="utf-8"))
    assert (record["outcome"], record["effective_report"], "drift_detected" in record) == (None, None, False), record
    verify = _run_controller("verify-disclosure", "--task-id", task_id, "--project-dir", str(root))
    assert verify.returncode == 3, verify.stdout
    assert _last_json(verify)["path"] == f"docs/dev/late-repair-run-{task_id}.json"

    state, path = CONTROLLER.resolve_effective_report_state(root, task_id)
    assert (state, path) == ("invalid", _effective_path(root, task_id))
    owner = declaring_dispatch(task_id, path, root)
    assert owner["source"] == "todo_step" and owner["step"].startswith("Step 0:"), owner
    assert (owner["command"], owner["subagent_call"], owner["template"]) == ("close", None, None), owner

    assert _last_json(_run_controller(*finalize))["outcome"] == "finalized_pending_verification"
    assert CONTROLLER.resolve_effective_report_state(root, task_id) == ("none", None)
    verify = _run_controller("verify-disclosure", "--task-id", task_id, "--project-dir", str(root))
    assert verify.returncode == 0 and _last_json(verify)["outcome"] == "admitted", verify.stdout


def test_verify_disclosure_takes_no_reading_of_the_effective_report(tmp_path: Path) -> None:
    """finalize's effective report is checked by finalize when it writes it;
    after that verify-disclosure, resolve_effective_report_state and its
    callers take it from the outcome and path finalize recorded, verbatim."""
    task_id = "20260101-000920"
    root = tmp_path
    effective_path = _produce_verified_effective_report(root, task_id)
    record = json.loads(_run_record_path(root, task_id).read_text(encoding="utf-8"))
    assert record["effective_report"] == f"docs/dev/dev-report-{task_id}.effective.json"
    assert "effective_report_disclosure_sha256" not in record

    effective_path.write_text("{}", encoding="utf-8")
    verify = _run_controller("verify-disclosure", "--task-id", task_id, "--project-dir", str(root))
    assert _last_json(verify)["outcome"] == "admitted"

    effective_path.unlink()
    assert CONTROLLER.resolve_effective_report_state(root, task_id) == ("verified", effective_path.resolve())
    proc = subprocess.run(
        [
            sys.executable, str(REPO_ROOT / "scripts" / "resolve-dev-report.py"),
            "--task-id", task_id, "--git-root", str(root), "--control-root", str(root),
        ],
        input=f"M docs/dev/dev-report-{task_id}.json\n",
        capture_output=True, text=True, check=False,
    )
    assert Path(proc.stdout.strip()) == effective_path.resolve()

    # The gap shows at the file's first use, the repository plan, which
    # names the path; finalize, run again, is that file's producer.
    repos_module = _load(REPO_ROOT / "scripts" / "resolve-commit-repos.py", "_resolve_commit_repos_gap")
    for report_arg in (None, str(effective_path)):
        try:
            repos_module.build_plan(
                task_id=task_id, control_root_arg=str(root), supported_repo_args=[], report_arg=report_arg,
            )
            raised = ""
        except repos_module.PlanError as exc:
            raised = str(exc)
        assert str(effective_path.resolve()) in raised, report_arg


def test_finalize_writes_the_effective_report_afresh_on_every_run(tmp_path: Path) -> None:
    task_id = "20260101-000930"
    root = tmp_path
    run_id = _reconcilable_drift_run(root, task_id)
    effective_path = _effective_path(root, task_id)
    for damage in (None, effective_path.unlink, lambda: effective_path.write_text("not json", encoding="utf-8")):
        if damage is not None:
            damage()
        finalize = _run_controller(
            "finalize", "--task-id", task_id, "--project-dir", str(root), "--repair-run-id", run_id,
        )
        assert finalize.returncode == 0, finalize.stdout
        payload = _last_json(finalize)
        assert payload["outcome"] == "finalized_pending_verification"
        assert payload["effective_report"] == f"docs/dev/dev-report-{task_id}.effective.json"
        written = json.loads(effective_path.read_text(encoding="utf-8"))
        assert written["retrospective_disclosure"]["repair_run_id"] == run_id
        assert written["retrospective_disclosure"]["artifact"] == effective_path.name
    assert CONTROLLER.resolve_effective_report_state(root, task_id) == ("verified", effective_path.resolve())


def test_finalize_refuses_naming_the_path_when_the_file_it_wrote_is_wrong(tmp_path: Path, monkeypatch, capsys) -> None:
    task_id = "20260101-000940"
    root = tmp_path
    run_id = _reconcilable_drift_run(root, task_id)
    effective_path = _effective_path(root, task_id)
    real_write = CONTROLLER._write_json

    def write_without_block(path: Path, doc: dict) -> None:
        if path.name == effective_path.name:
            doc = {key: value for key, value in doc.items() if key != "retrospective_disclosure"}
        real_write(path, doc)

    monkeypatch.setattr(CONTROLLER, "_write_json", write_without_block)
    ns = CONTROLLER.build_parser().parse_args([
        "finalize", "--task-id", task_id, "--project-dir", str(root), "--repair-run-id", run_id,
    ])
    rc = ns.func(ns)
    payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert rc == 3
    assert payload["outcome"] == "refuse"
    assert payload["path"] == f"docs/dev/dev-report-{task_id}.effective.json"
    assert payload["path"] in payload["reason"]
    record = json.loads(_run_record_path(root, task_id).read_text(encoding="utf-8"))
    assert record["outcome"] is None
    assert record["effective_report"] is None


def test_rule5_a_declined_init_hands_its_chain_call_to_the_ordinary_route(tmp_path: Path, monkeypatch) -> None:
    """Row 19 rule 5: a /close --late-repair whose init declines goes on with
    that call's chain result, used verbatim; the chain is resolved once."""
    calls: list[tuple] = []

    def counting(module):
        real = module.resolve_chain

        def resolve_chain(*args, **kwargs):
            calls.append(args)
            return real(*args, **kwargs)

        module.resolve_chain = resolve_chain
        return module

    original_controller = ROUTE_SELECT._controller_module
    original_resolver = ROUTE_SELECT._resolver_module

    def controller():
        module = original_controller()
        loader = module.load_sibling_module
        module.load_sibling_module = lambda name, caller: (
            counting(loader(name, caller)) if name == "resolve-dev-artifact-chain.py" else loader(name, caller)
        )
        return module

    monkeypatch.setattr(ROUTE_SELECT, "_controller_module", controller)
    monkeypatch.setattr(ROUTE_SELECT, "_resolver_module", lambda: counting(original_resolver()))

    for index, builder in enumerate((fx.build_complete, fx.build_qa_only, fx.build_mixed_integrity)):
        task_id = f"20260101-00095{index}"
        root = tmp_path / builder.__name__
        builder(root, task_id)
        calls.clear()
        rc, payload = ROUTE_SELECT.run(task_id, str(root), True, False)
        assert len(calls) == 1, builder.__name__
        assert payload["outcome"] == "not_selected"
        assert payload["late_repair"] == {"outcome": "refuse", "reason": "not a beyond-QA gap; use R1's route"}
        assert not _run_record_path(root, task_id).is_file()

        calls.clear()
        rc_ordinary, ordinary = ROUTE_SELECT.run(task_id, str(root), False, False)
        assert len(calls) == 1
        assert rc == rc_ordinary
        assert json.dumps(payload["artifact_chain"], sort_keys=True) == json.dumps(ordinary["artifact_chain"], sort_keys=True)
        assert {k: v for k, v in payload.items() if k != "late_repair"}.keys() == ordinary.keys()


def test_close_todo_declares_finalize_as_a_main_agent_step_under_late_repair(tmp_path: Path) -> None:
    def todos(prompt: str) -> list[dict]:
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "todo" / "close.py")],
            env={**__import__("os").environ, "CLAUDE_TODO_PROMPT": prompt},
            capture_output=True, text=True, check=True,
        )
        return json.loads(proc.stdout)

    plain = todos("/close")
    late = todos("/close --late-repair 20260101-000960")
    # P4 R11: the same five steps under every prompt; under --late-repair,
    # Step 0 (the main agent's own) also declares finalize's effective report.
    assert todos("/close --force") == plain
    assert todos("/close --auto") == plain
    assert late[1:] == plain[1:]
    finalize = late[0]
    assert finalize["content"] == plain[0]["content"] == "Step 0: Resolve the disposition; complete the cycle when incomplete"
    assert "subagent_call" not in finalize
    assert "artifacts" not in plain[0]
    [declared] = finalize["artifacts"]

    # The declared path is the one finalize writes and records.
    task_id = "20260101-000960"
    effective_path = _produce_verified_effective_report(tmp_path, task_id)
    record = json.loads(_run_record_path(tmp_path, task_id).read_text(encoding="utf-8"))
    assert declared["path"].replace("<task>", task_id) == record["effective_report"]
    assert effective_path == tmp_path / record["effective_report"]
