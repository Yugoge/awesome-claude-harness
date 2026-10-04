#!/usr/bin/env python3
"""Regression: a corroborated, drift-free late-repair run is NOT State C.

scripts/late-repair-controller.py's ``resolve_effective_report_state`` is the
tri-state guard /commit consults before preferring an effective dev-report
over the canonical one.  It used to collapse two entirely different situations
into the same "invalid" answer:

  * corroboration genuinely failed (State C -- callers must fail closed), and
  * corroboration was ADMITTED but ``finalize`` recorded no effective report,
    which happens exactly when finalize found no drift at all.

The second is the BEST outcome a repair run can reach: the canonical
dev-report is already current, so there is simply nothing to prefer over it.
Reporting it as State C made every clean late-repair run permanently
un-committable while /commit printed the opposite of what had happened ("an
effective report exists but is not corroborated" -- when none existed and
corroboration had succeeded).

No test covered that shape: tests/test_late_repair_route.py's drift-free case
(AC-8) stops at verify-disclosure and never calls the guard, and its two guard
cases both fail corroboration before this branch is reached.  This file closes
that gap with a run built through the controller's OWN phases (init ->
record-stage ba/dev/qa -> finalize -> verify-disclosure), never a hand-written
run record, so the drift-free state it asserts on is one finalize actually
produced.

Deliberately self-contained (its own fixture builders, no import of the other
suite's helpers) so the two files can never break each other.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTROLLER_PATH = REPO_ROOT / "scripts" / "late-repair-controller.py"

_spec = importlib.util.spec_from_file_location(
    "_late_repair_controller_driftfree_state", CONTROLLER_PATH
)
CONTROLLER = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CONTROLLER)

TASK_ID = "20260927-000700"


def _run_controller(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CONTROLLER_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _last_json(proc: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, dict):
        value = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    path.write_text(value, encoding="utf-8")


def _build_beyond_qa_chain_with_one_current_file(
    root: Path, task_id: str, *, with_cycle_date: bool = True
) -> dict[str, Path]:
    """Late-repair-eligible chain (ticket/context/qa-report absent) whose
    dev-report declares one real, on-disk source file whose recorded final
    hash matches its live bytes.

    Declaring a file that genuinely matches makes the drift-free outcome a
    real comparison result rather than a vacuous "nothing declared" one:
    check-late-repair-provenance.detect_drift hashes the live bytes and finds
    them identical, so finalize takes its no-drift branch for a substantive
    reason.

    with_cycle_date=False drops the dev-report's ``timestamp``, which is the
    only field ``_derive_original_cycle_at`` can read here (no context exists
    at init time), leaving original_cycle_at None -- the precondition for
    finalize's fail_closed branch.
    """
    dev_dir = root / "docs" / "dev"
    source_rel = "src/current_thing.py"
    source_body = "def current():\n    return 'unchanged since the original cycle'\n"
    _write(root / source_rel, source_body)

    dev_report: dict = {
        "request_id": task_id,
        "task_id": task_id,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "baseline_head_sha": "0" * 40,
        "baseline_dirty_snapshot": "",
        "dev": {
            "status": "completed",
            "tasks_completed": [f"completed {task_id}"],
            "scripts_created": [],
            "permissions_to_add": [],
            "files_modified": [source_rel],
            "files_created": [],
            "observed_preexisting": [],
        },
        "final_source_hashes": {
            source_rel: hashlib.sha256(source_body.encode("utf-8")).hexdigest(),
        },
        "blocking_issues": [],
        "recommendations": [],
    }
    if not with_cycle_date:
        del dev_report["timestamp"]
    paths = {
        "ticket": dev_dir / f"ticket-{task_id}.md",
        "context": dev_dir / f"context-{task_id}.json",
        "dev_report": dev_dir / f"dev-report-{task_id}.json",
        "qa_report": dev_dir / f"qa-report-{task_id}.json",
        "completion": dev_dir / f"completion-{task_id}.md",
        "source": root / source_rel,
    }
    # ticket / context / qa_report are intentionally absent: that triple is the
    # beyond_qa stage gap the late-repair route exists to close.
    _write(paths["dev_report"], dev_report)
    references = [
        paths[key].relative_to(root).as_posix()
        for key in ("ticket", "context", "dev_report", "qa_report")
    ]
    completion = [f"# Completion\n\n**Request ID**: `{task_id}`\n"]
    completion.extend(f"- `{reference}`\n" for reference in references)
    _write(paths["completion"], "".join(completion))
    return paths


def _repair_run_through_controller_phases(root: Path, task_id: str, paths: dict[str, Path]) -> str:
    """init -> BA/Dev/QA stage recording -> finalize, all via the real CLI."""
    init = _run_controller("init", "--task-id", task_id, "--project-dir", str(root))
    assert init.returncode == 0, (init.stdout, init.stderr)
    run_id = _last_json(init)["repair_run_id"]

    # The stage artifacts BA and QA produce during the repair run itself.
    _write(paths["ticket"], f"# Ticket\n\n**TASK-ID**: `{task_id}`\n")
    _write(paths["context"], {"request_id": task_id, "task_id": task_id})
    _write(paths["qa_report"], {"request_id": task_id, "task_id": task_id, "qa": {"status": "pass"}})

    for stage, path in (
        ("ba", paths["ticket"]),
        ("dev", paths["dev_report"]),
        ("qa", paths["qa_report"]),
    ):
        proc = _run_controller(
            "record-stage", "--task-id", task_id, "--project-dir", str(root),
            "--stage", stage, "--report-path", str(path), "--repair-run-id", run_id,
        )
        assert proc.returncode == 0, (stage, proc.stdout, proc.stderr)
    return run_id


def test_corroborated_drift_free_run_is_state_none_not_invalid(tmp_path: Path) -> None:
    root = tmp_path
    paths = _build_beyond_qa_chain_with_one_current_file(root, TASK_ID)
    run_id = _repair_run_through_controller_phases(root, TASK_ID, paths)

    finalize = _run_controller(
        "finalize", "--task-id", TASK_ID, "--project-dir", str(root), "--repair-run-id", run_id,
    )
    assert finalize.returncode == 0, (finalize.stdout, finalize.stderr)
    finalize_payload = _last_json(finalize)
    assert finalize_payload["outcome"] == "finalized_pending_verification"
    # Genuinely drift-free: finalize compared and found nothing to reconcile.
    assert finalize_payload["drift_detected"] == {}

    # Therefore finalize legitimately recorded NO effective report, and wrote
    # no .effective.json at all -- this is the field emptiness the guard used
    # to misread as a corroboration failure.
    record = json.loads(
        (root / "docs" / "dev" / f"late-repair-run-{TASK_ID}.json").read_text(encoding="utf-8")
    )
    assert record["effective_report"] is None
    assert not (root / "docs" / "dev" / f"dev-report-{TASK_ID}.effective.json").exists()

    # Corroboration is ADMITTED: nothing about this run failed verification.
    verify = _run_controller("verify-disclosure", "--task-id", TASK_ID, "--project-dir", str(root))
    assert verify.returncode == 0, (verify.stdout, verify.stderr)
    assert _last_json(verify)["outcome"] == "admitted"

    # The guard must therefore NOT report State C.  With corroboration
    # admitted and no effective report recorded, there is nothing to prefer
    # over the canonical dev-report, which is exactly State A ("none", None) --
    # the same answer given when no repair run exists at all.
    state, path = CONTROLLER.resolve_effective_report_state(root, TASK_ID)
    assert state != "invalid", (
        "a corroborated, drift-free repair run was misclassified as "
        "uncorroborated, making every clean repair run un-committable"
    )
    assert state == "none"
    assert path is None

    # The CLI wrapper /commit actually shells out to reports the same state.
    resolved = _run_controller(
        "resolve-effective-report", "--task-id", TASK_ID, "--project-dir", str(root),
    )
    assert resolved.returncode == 0, (resolved.stdout, resolved.stderr)
    payload = _last_json(resolved)
    assert payload["state"] == "none"
    assert payload["path"] is None


def _record(root: Path) -> dict:
    return json.loads(
        (root / "docs" / "dev" / f"late-repair-run-{TASK_ID}.json").read_text(encoding="utf-8")
    )


def _assert_corroboration_admitted(root: Path) -> None:
    """The three shapes below all pass verify-disclosure.

    That is the whole difficulty: corroboration cannot distinguish them from
    the drift-free run, because every artifact they recorded is present and
    still hashes to what was recorded.  Only the run record's own outcome
    can, which is why the guard must read it.
    """
    verify = _run_controller("verify-disclosure", "--task-id", TASK_ID, "--project-dir", str(root))
    assert verify.returncode == 0, (verify.stdout, verify.stderr)
    assert _last_json(verify)["outcome"] == "admitted"


def test_unroutable_drift_run_is_state_invalid(tmp_path: Path) -> None:
    """finalize's honest_refuse shape must stay State C.

    finalize reports the drift it found in its EMITTED payload but never
    writes drift_detected onto the record, so this record carries a null
    effective_report indistinguishable from the drift-free one by emptiness
    alone.  Misreading it as "nothing to prefer" makes /commit fall back to
    canonical provenance that finalize has just declared stale and
    unroutable -- the exact fallback /commit's contract forbids.
    """
    root = tmp_path
    paths = _build_beyond_qa_chain_with_one_current_file(root, TASK_ID)
    run_id = _repair_run_through_controller_phases(root, TASK_ID, paths)

    # The declared source moves on after its final hash was recorded.  It
    # declares no provenance mechanism, so the drift has no route.
    _write(paths["source"], "def current():\n    return 'changed after the original cycle'\n")

    finalize = _run_controller(
        "finalize", "--task-id", TASK_ID, "--project-dir", str(root), "--repair-run-id", run_id,
    )
    assert finalize.returncode == 5, (finalize.stdout, finalize.stderr)
    finalize_payload = _last_json(finalize)
    assert finalize_payload["outcome"] == "honest_refuse"
    assert finalize_payload["drift_detected"], "finalize must have found drift to refuse over"
    assert finalize_payload["unroutable_files"] == ["src/current_thing.py"]

    record = _record(root)
    assert record["outcome"] == "honest_refuse"
    assert record["effective_report"] is None       # identical emptiness to drift-free
    assert record.get("drift_detected") is None     # ...but the drift itself was NOT recorded
    _assert_corroboration_admitted(root)

    state, path = CONTROLLER.resolve_effective_report_state(root, TASK_ID)
    assert state == "invalid", (
        "a run whose finalize refused itself over unroutable drift was reported as "
        "'nothing to prefer', so /commit would fall back to canonical provenance "
        "that same finalize had just found stale"
    )
    assert path is None

    resolved = _run_controller(
        "resolve-effective-report", "--task-id", TASK_ID, "--project-dir", str(root),
    )
    assert _last_json(resolved)["state"] == "invalid"


def test_not_yet_finalized_run_is_state_invalid(tmp_path: Path) -> None:
    """A record that exists but has never been finalized must stay State C.

    This is the shape every ordinary in-flight repair run passes through
    between its last record-stage call and finalize: outcome still the null
    cmd_init wrote, effective_report still that same null.  No drift
    comparison has been performed at all, so there is no basis whatsoever
    for telling a caller the canonical dev-report is current.
    """
    root = tmp_path
    paths = _build_beyond_qa_chain_with_one_current_file(root, TASK_ID)
    _repair_run_through_controller_phases(root, TASK_ID, paths)  # deliberately no finalize

    record = _record(root)
    assert record["outcome"] is None
    assert record["effective_report"] is None
    assert "drift_detected" not in record
    _assert_corroboration_admitted(root)

    state, path = CONTROLLER.resolve_effective_report_state(root, TASK_ID)
    assert state == "invalid", (
        "a repair run that had not yet run drift detection was reported as having "
        "found nothing to reconcile"
    )
    assert path is None


def test_fail_closed_run_is_state_invalid(tmp_path: Path) -> None:
    """finalize's fail_closed shape must stay State C.

    Reached when the dev-report is absent at finalize time and no
    independently corroborable original_cycle_at exists; finalize then
    persists outcome 'fail_closed' with the same null effective_report.
    Restoring the recorded dev-report bytes afterwards is what lets
    corroboration re-admit the run -- and that is exactly the condition
    under which a field-emptiness test calls a terminal failure benign.
    """
    root = tmp_path
    paths = _build_beyond_qa_chain_with_one_current_file(root, TASK_ID, with_cycle_date=False)
    run_id = _repair_run_through_controller_phases(root, TASK_ID, paths)
    assert _record(root)["original_cycle_at"] is None, "precondition for the fail_closed branch"

    recorded_bytes = paths["dev_report"].read_bytes()  # post-disclosure, as the record hashed it
    paths["dev_report"].unlink()
    finalize = _run_controller(
        "finalize", "--task-id", TASK_ID, "--project-dir", str(root), "--repair-run-id", run_id,
    )
    assert finalize.returncode == 6, (finalize.stdout, finalize.stderr)
    assert _last_json(finalize)["outcome"] == "fail_closed"
    paths["dev_report"].write_bytes(recorded_bytes)

    record = _record(root)
    assert record["outcome"] == "fail_closed"
    assert record["effective_report"] is None
    assert "drift_detected" not in record
    _assert_corroboration_admitted(root)

    state, path = CONTROLLER.resolve_effective_report_state(root, TASK_ID)
    assert state == "invalid", (
        "a run that failed closed was reported as a clean, drift-free run"
    )
    assert path is None
