#!/usr/bin/env python3
"""Tests for hooks/stop-do-report-gate.py (the /do do-report runtime binder).

Covers the contract from commands/do.md Step 5: a /do session may stop only
when its do-report reached a terminal, shape-valid state. Block mode is the
shipped default (DO_REPORT_GATE_MODE unset); advisory mode (opt-in) is
asserted to never block and to journal would-block events. Deadlock guard:
after MAX_BLOCKS blocks the gate force-allows, honestly rewriting a still-
"pending" do-report to "blocked" rather than leaving it silently pending.

Run: python3 hooks/tests/test_stop_do_report_gate.py
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "stop-do-report-gate.py"
MAX_BLOCKS = 2  # keep in sync with the hook


def _cleanup(sid):
    for p in (Path(f"/tmp/claude-do-task-{sid}.json"),
              Path(f"/tmp/claude-do-report-gate-{sid}.json")):
        try:
            p.unlink()
        except OSError:
            pass


def _sid():
    return "gate-test-" + next(tempfile._get_candidate_names())


def _write_sidecar(sid, task_id):
    Path(f"/tmp/claude-do-task-{sid}.json").write_text(
        json.dumps({"task_id": task_id, "session_id": sid}))


def _report(project_dir, task_id, **overrides):
    """Write a compliant completed do-report, then apply overrides."""
    rec = {
        "report_version": 1,
        "task_id": task_id,
        "request_id": task_id,
        "source": "do",
        "request": "test request",
        "do": {
            "status": "completed",
            "summary": "did the thing",
            "files_modified": ["a.py"],
            "files_created": [],
        },
    }
    for key, value in overrides.items():
        if key.startswith("do_"):
            rec["do"][key[3:]] = value
        elif value is None:
            rec.pop(key, None)
        else:
            rec[key] = value
    d = Path(project_dir) / "docs" / "dev"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"do-report-{task_id}.json").write_text(json.dumps(rec))


def _run_gate(sid, project_dir, home, mode="block", raw_report=None, task_id="20260101-000000"):
    env = {**os.environ,
           "CLAUDE_PROJECT_DIR": str(project_dir),
           "HOME": str(home)}
    if mode is None:
        env.pop("DO_REPORT_GATE_MODE", None)  # exercise the true unset-env-var default
    else:
        env["DO_REPORT_GATE_MODE"] = mode
    if raw_report is not None:
        d = Path(project_dir) / "docs" / "dev"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"do-report-{task_id}.json").write_text(raw_report)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"session_id": sid}),
        capture_output=True, text=True, env=env, timeout=30)


def test_no_sidecar_allows():
    sid = _sid()
    with tempfile.TemporaryDirectory() as tmp:
        r = _run_gate(sid, tmp, tmp)
        assert r.returncode == 0, f"no /do consent must pass through: rc={r.returncode} err={r.stderr}"


def test_missing_report_blocks_in_block_mode():
    sid, tid = _sid(), "20260101-000001"
    with tempfile.TemporaryDirectory() as tmp:
        _write_sidecar(sid, tid)
        try:
            r = _run_gate(sid, tmp, tmp, task_id=tid)
            assert r.returncode == 2, f"absent report must block: rc={r.returncode}"
            assert "DO_REPORT_GATE_BLOCKED" in r.stderr
            assert tid in r.stderr, "block message must name the report path/task"
        finally:
            _cleanup(sid)


def test_deadlock_guard_force_allows_after_max_blocks():
    sid, tid = _sid(), "20260101-000002"
    with tempfile.TemporaryDirectory() as tmp:
        _write_sidecar(sid, tid)
        try:
            rcs = [_run_gate(sid, tmp, tmp, task_id=tid).returncode for _ in range(MAX_BLOCKS + 1)]
            assert rcs[:MAX_BLOCKS] == [2] * MAX_BLOCKS, f"first {MAX_BLOCKS} stops must block: {rcs}"
            assert rcs[MAX_BLOCKS] == 0, f"stop #{MAX_BLOCKS + 1} must force-allow (deadlock guard): {rcs}"
        finally:
            _cleanup(sid)


def test_completed_report_allows_and_clears_counter():
    sid, tid = _sid(), "20260101-000003"
    with tempfile.TemporaryDirectory() as tmp:
        _write_sidecar(sid, tid)
        try:
            assert _run_gate(sid, tmp, tmp, task_id=tid).returncode == 2  # arm the counter
            _report(tmp, tid)
            r = _run_gate(sid, tmp, tmp, task_id=tid)
            assert r.returncode == 0, f"completed report must allow stop: {r.stderr}"
            assert not Path(f"/tmp/claude-do-report-gate-{sid}.json").exists(), \
                "compliance must clear the block counter"
        finally:
            _cleanup(sid)


def test_readonly_task_empty_files_modified_allows():
    sid, tid = _sid(), "20260101-000004"
    with tempfile.TemporaryDirectory() as tmp:
        _write_sidecar(sid, tid)
        try:
            _report(tmp, tid, do_files_modified=[])
            r = _run_gate(sid, tmp, tmp, task_id=tid)
            assert r.returncode == 0, f"read-only /do (empty files_modified) must NOT be rejected: {r.stderr}"
        finally:
            _cleanup(sid)


def test_blocked_status_with_summary_allows_stop():
    sid, tid = _sid(), "20260101-000005"
    with tempfile.TemporaryDirectory() as tmp:
        _write_sidecar(sid, tid)
        try:
            _report(tmp, tid, do_status="blocked", do_summary="user declined the required restart")
            r = _run_gate(sid, tmp, tmp, task_id=tid)
            assert r.returncode == 0, \
                f"honest 'blocked' terminal state must allow stop (no misreporting pressure): {r.stderr}"
        finally:
            _cleanup(sid)


def test_pending_skeleton_blocks():
    sid, tid = _sid(), "20260101-000006"
    with tempfile.TemporaryDirectory() as tmp:
        _write_sidecar(sid, tid)
        try:
            _report(tmp, tid, do_status="pending", do_summary="")
            r = _run_gate(sid, tmp, tmp, task_id=tid)
            assert r.returncode == 2, "never-completed skeleton must block"
            assert "pending" in r.stderr
        finally:
            _cleanup(sid)


def test_arbitrary_non_terminal_status_blocks():
    """Pins the generic `status not in TERMINAL_STATUSES` check (hook L97-98)
    at the level it actually operates: an arbitrary non-"pending" non-terminal
    value, and a do-report whose "do" object omits the status key entirely,
    must both still block. Guards against a future narrowing regression that
    collapses the check into a "status == 'pending'"-only comparison."""
    sid, tid = _sid(), "20260101-000014"
    with tempfile.TemporaryDirectory() as tmp:
        _write_sidecar(sid, tid)
        try:
            _report(tmp, tid, do_status="in_progress")
            r = _run_gate(sid, tmp, tmp, task_id=tid)
            assert r.returncode == 2, f"arbitrary non-terminal status must block: rc={r.returncode}"
        finally:
            _cleanup(sid)

    sid2, tid2 = _sid(), "20260101-000015"
    with tempfile.TemporaryDirectory() as tmp:
        _write_sidecar(sid2, tid2)
        try:
            _report(tmp, tid2)  # default do.status == "completed"
            p = Path(tmp) / "docs" / "dev" / f"do-report-{tid2}.json"
            rec = json.loads(p.read_text())
            del rec["do"]["status"]
            p.write_text(json.dumps(rec))
            r = _run_gate(sid2, tmp, tmp, task_id=tid2)
            assert r.returncode == 2, f"missing do.status key must block: rc={r.returncode}"
        finally:
            _cleanup(sid2)


def test_task_id_mismatch_blocks():
    sid, tid = _sid(), "20260101-000007"
    with tempfile.TemporaryDirectory() as tmp:
        _write_sidecar(sid, tid)
        try:
            _report(tmp, tid)
            p = Path(tmp) / "docs" / "dev" / f"do-report-{tid}.json"
            rec = json.loads(p.read_text())
            rec["task_id"] = "20991231-235959"
            p.write_text(json.dumps(rec))
            r = _run_gate(sid, tmp, tmp, task_id=tid)
            assert r.returncode == 2, "task_id mismatch must block (wrong session's report)"
        finally:
            _cleanup(sid)


def test_malformed_json_blocks():
    sid, tid = _sid(), "20260101-000008"
    with tempfile.TemporaryDirectory() as tmp:
        _write_sidecar(sid, tid)
        try:
            r = _run_gate(sid, tmp, tmp, task_id=tid, raw_report="{not json")
            assert r.returncode == 2, "unparseable report must block"
        finally:
            _cleanup(sid)


def test_versioned_schema_violation_blocks():
    """Structurally-plausible report that violates do-report.v1 (missing
    required 'request') — caught by the shared schema engine, not a hand-rolled
    duplicate check."""
    sid, tid = _sid(), "20260101-000009"
    with tempfile.TemporaryDirectory() as tmp:
        _write_sidecar(sid, tid)
        try:
            _report(tmp, tid, request=None)
            r = _run_gate(sid, tmp, tmp, task_id=tid)
            assert r.returncode == 2, "do-report.v1 violation on a versioned report must block"
            assert "schema" in r.stderr.lower()
        finally:
            _cleanup(sid)


def test_default_mode_blocks_and_honest_giveup_rewrite():
    """AC-L5-06/07/08: with DO_REPORT_GATE_MODE unset the gate now blocks by
    default (was advisory); when the deadlock guard force-allows and the
    do-report is still 'pending', it is rewritten to an honest 'blocked'
    terminal state -- but a give-up on an already-non-pending status (a
    different violation, e.g. task_id mismatch) must leave status untouched."""
    sid, tid = _sid(), "20260101-000012"
    with tempfile.TemporaryDirectory() as tmp:
        _write_sidecar(sid, tid)
        try:
            _report(tmp, tid, do_status="pending", do_summary="")
            rcs = [_run_gate(sid, tmp, tmp, mode=None, task_id=tid).returncode
                   for _ in range(MAX_BLOCKS + 1)]
            assert rcs[:MAX_BLOCKS] == [2] * MAX_BLOCKS, \
                f"DO_REPORT_GATE_MODE unset must block by default now: {rcs}"
            assert rcs[MAX_BLOCKS] == 0, f"deadlock guard must still force-allow: {rcs}"
            report = Path(tmp) / "docs" / "dev" / f"do-report-{tid}.json"
            rec = json.loads(report.read_text())
            assert rec["do"]["status"] == "blocked", \
                f"give-up must rewrite a still-pending status to 'blocked', got {rec['do']['status']!r}"
            assert rec["do"]["summary"] == "session ended without completing the do-report"
        finally:
            _cleanup(sid)

    sid2, tid2 = _sid(), "20260101-000013"
    with tempfile.TemporaryDirectory() as tmp:
        _write_sidecar(sid2, tid2)
        try:
            _report(tmp, tid2)  # default do.status == "completed"
            p = Path(tmp) / "docs" / "dev" / f"do-report-{tid2}.json"
            rec = json.loads(p.read_text())
            rec["task_id"] = "20991231-235959"  # mismatch: still non-compliant, status stays non-pending
            p.write_text(json.dumps(rec))
            rcs2 = [_run_gate(sid2, tmp, tmp, task_id=tid2).returncode for _ in range(MAX_BLOCKS + 1)]
            assert rcs2[MAX_BLOCKS] == 0, f"deadlock guard must force-allow: {rcs2}"
            final = json.loads(p.read_text())
            assert final["do"]["status"] == "completed", \
                f"give-up must NOT touch an already-non-pending status, got {final['do']['status']!r}"
        finally:
            _cleanup(sid2)


def test_advisory_mode_never_blocks_and_journals():
    sid, tid = _sid(), "20260101-000010"
    with tempfile.TemporaryDirectory() as tmp:
        _write_sidecar(sid, tid)
        try:
            r = _run_gate(sid, tmp, tmp, mode="advisory", task_id=tid)
            assert r.returncode == 0, f"advisory mode must never block: rc={r.returncode}"
            log = Path(tmp) / ".claude" / "logs" / "do-report-gate-advisory.jsonl"
            assert log.exists(), "advisory mode must journal the would-block event"
            rec = json.loads(log.read_text().strip().splitlines()[-1])
            assert rec["event"] == "would_block" and rec["task_id"] == tid
        finally:
            _cleanup(sid)


def test_off_mode_is_noop():
    sid, tid = _sid(), "20260101-000011"
    with tempfile.TemporaryDirectory() as tmp:
        _write_sidecar(sid, tid)
        try:
            r = _run_gate(sid, tmp, tmp, mode="off", task_id=tid)
            assert r.returncode == 0
        finally:
            _cleanup(sid)


def test_unsafe_sidecar_task_id_degrades_to_allow():
    sid = _sid()
    with tempfile.TemporaryDirectory() as tmp:
        Path(f"/tmp/claude-do-task-{sid}.json").write_text(
            json.dumps({"task_id": "../../etc/passwd", "session_id": sid}))
        try:
            r = _run_gate(sid, tmp, tmp)
            assert r.returncode == 0, "path-shaped task_id must degrade to no-enforcement, not escape docs/dev"
        finally:
            _cleanup(sid)


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run())
