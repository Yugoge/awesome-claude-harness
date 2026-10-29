#!/usr/bin/env python3
"""Tests for hooks/stop-do-report-gate.py (the /do do-report runtime binder).

Covers the contract from commands/do.md Step 5: a /do session may stop only
when its do-report reached a terminal, shape-valid state. Block mode is the
shipped default (DO_REPORT_GATE_MODE unset); advisory mode (opt-in) is
asserted to never block and to write nothing. Deadlock guard:
after MAX_BLOCKS blocks the gate force-allows and leaves the report as the
agent wrote it (the agent is its only writer). do.status is decided by
lib/obligation.terminal_status on the do-report schema's vocabulary.

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

sys.path.insert(0, str(HOOK.parent))
from lib.harness_state_dir import harness_state_dir  # noqa: E402


def _state_path(name):
    # Resolved per call with the hook's own resolver: the spawned gate inherits
    # os.environ, so CLAUDE_STATE_DIR as it is at call time decides where it looks.
    return Path(harness_state_dir()) / name


def _sidecar_path(sid):
    return _state_path(f"claude-do-task-{sid}.json")


def _counter_path(sid):
    return _state_path(f"claude-do-report-gate-{sid}.json")


def _cleanup(sid):
    for p in (_sidecar_path(sid), _counter_path(sid)):
        try:
            p.unlink()
        except OSError:
            pass


def _sid():
    return "gate-test-" + next(tempfile._get_candidate_names())


def _write_sidecar(sid, task_id):
    _sidecar_path(sid).write_text(
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
           "HOME": str(home),
           "CLAUDE_CONFIG_DIR": str(Path(home) / ".claude")}
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
            assert not _counter_path(sid).exists(), \
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


def test_pending_status_blocks():
    """E8: the do-report schema declares no "pending" (nothing writes a
    skeleton any more), so a report that still carries it is not terminal."""
    sid, tid = _sid(), "20260101-000006"
    with tempfile.TemporaryDirectory() as tmp:
        _write_sidecar(sid, tid)
        try:
            _report(tmp, tid, do_status="pending", do_summary="")
            r = _run_gate(sid, tmp, tmp, task_id=tid)
            assert r.returncode == 2, "a pending do.status is not terminal and must block"
            assert "'pending'" in r.stderr and "blocked/completed" in r.stderr, r.stderr
        finally:
            _cleanup(sid)


def test_arbitrary_non_terminal_status_blocks():
    """Pins the generic terminal_status decision at the level it actually
    operates: an arbitrary non-"pending" non-terminal
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


def test_default_mode_blocks_and_forced_allow_writes_nothing():
    """AC-L5-06/07/08: with DO_REPORT_GATE_MODE unset the gate blocks by
    default; when the deadlock guard force-allows, the do-report keeps the
    agent's bytes (D8/D24: the gate is no second writer of it), whatever the
    violation (a non-terminal status, or a task_id mismatch)."""
    sid, tid = _sid(), "20260101-000012"
    with tempfile.TemporaryDirectory() as tmp:
        _write_sidecar(sid, tid)
        try:
            _report(tmp, tid, do_status="pending", do_summary="")
            report = Path(tmp) / "docs" / "dev" / f"do-report-{tid}.json"
            before = report.read_bytes()
            rcs = [_run_gate(sid, tmp, tmp, mode=None, task_id=tid)
                   for _ in range(MAX_BLOCKS + 1)]
            assert [r.returncode for r in rcs[:MAX_BLOCKS]] == [2] * MAX_BLOCKS, \
                f"DO_REPORT_GATE_MODE unset must block by default now: {[r.returncode for r in rcs]}"
            assert rcs[MAX_BLOCKS].returncode == 0, "deadlock guard must still force-allow"
            assert "FORCED ALLOW" in rcs[MAX_BLOCKS].stderr
            assert "rewritten" not in rcs[MAX_BLOCKS].stderr
            assert report.read_bytes() == before, "the forced allow must not write the report"
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
            assert final == rec, "the forced allow must not write the report"
        finally:
            _cleanup(sid2)


def test_advisory_mode_never_blocks_and_writes_nothing():
    sid, tid = _sid(), "20260101-000010"
    with tempfile.TemporaryDirectory() as tmp:
        _write_sidecar(sid, tid)
        try:
            r = _run_gate(sid, tmp, tmp, mode="advisory", task_id=tid)
            assert r.returncode == 0, f"advisory mode must never block: rc={r.returncode}"
            assert not (Path(tmp) / ".claude" / "logs").exists(), "advisory mode writes nothing"
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
        _sidecar_path(sid).write_text(
            json.dumps({"task_id": "../../etc/passwd", "session_id": sid}))
        try:
            r = _run_gate(sid, tmp, tmp)
            assert r.returncode == 0, "path-shaped task_id must degrade to no-enforcement, not escape docs/dev"
        finally:
            _cleanup(sid)


def _do_md_template(task_id):
    """The JSON block of commands/do.md's Step 5, placeholders as the agent fills them."""
    text = (HOOK.parent.parent / "commands" / "do.md").read_text(encoding="utf-8")
    step5 = text[text.index("### Step 5"):]
    block = step5[step5.index("```json") + len("```json"):]
    return json.loads(block[:block.index("```")].replace("<TASK_ID>", task_id))


def test_do_md_step5_template_passes_the_gate():
    """E8 (a): the /do main agent writes the whole report from commands/do.md's
    Step 5 template. Filled in, it passes this gate and keeps the
    expected_absent the close QA's e2e gate reads (subagentstop-e2e-enforce.py
    blocks the close QA's stop when a /do report does not declare its
    qa-report absent)."""
    sid, tid = _sid(), "20260101-000016"
    with tempfile.TemporaryDirectory() as tmp:
        _write_sidecar(sid, tid)
        try:
            rec = _do_md_template(tid)
            assert "qa-report" in rec["expected_absent"]
            d = Path(tmp) / "docs" / "dev"
            d.mkdir(parents=True)
            (d / f"do-report-{tid}.json").write_text(json.dumps(rec))
            r = _run_gate(sid, tmp, tmp, task_id=tid)
            assert r.returncode == 0, r.stderr
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
