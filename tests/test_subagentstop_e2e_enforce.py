#!/usr/bin/env python3
"""Tests for hooks/subagentstop-e2e-enforce.py's QA-report correlation.

Backlog: dev-20260923-083731 -- widen _find_latest_qa_report's correlation
predicate with an additive, exact-match, orchestrator-anchored task_id
dimension, without ever relaxing the pre-existing "no correlation found ->
reject" terminal behavior. Pins AC1 (cross-session pass), AC2a/AC2b (the two
fail-closed exit-2 branches this hook exists for), AC3 (unchanged
same-timestamp behavior, with branch-identity proof via M9's stderr tag), and
AC5 (unsafe task_id degrades safely, no crash, no path escape).

Models tests/test_resolve_dev_artifact_chain.py's
importlib.util.spec_from_file_location pattern for loading a
hyphenated-filename module under test.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_PATH = REPO_ROOT / "hooks" / "subagentstop-e2e-enforce.py"


def _load_hook():
    spec = importlib.util.spec_from_file_location(
        "subagentstop_e2e_enforce_under_test", HOOK_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HOOK = _load_hook()


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, dict):
        value = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    path.write_text(value, encoding="utf-8")


def _qa_report(task_id: str, status: str = "performed") -> dict:
    return {
        "task_id": task_id,
        "request_id": task_id,
        "e2e_enforcement": {"status": status},
    }


def _register_agent(
    project_dir: Path, agent_id: str, dev_session_id: str, agent_type: str = "qa"
) -> None:
    index_path = project_dir / ".claude" / "dev-registry" / "agent-index.json"
    existing: dict = {}
    if index_path.exists():
        existing = json.loads(index_path.read_text(encoding="utf-8"))
    existing[agent_id] = {"agent_type": agent_type, "dev_session_id": dev_session_id}
    _write(index_path, existing)


def _enable_e2e_enforcement(project_dir: Path, dev_session_id: str) -> None:
    _write(
        project_dir / ".claude" / "dev-registry" / dev_session_id / "e2e-enforce.json",
        {"enabled": True},
    )


def _write_qa_sentinel(
    project_dir: Path,
    dev_session_id: str,
    *,
    task_id: str | None = None,
    qa_mode: str = "final_verification",
) -> None:
    data = {"agent_type": "qa", "session_id": dev_session_id, "qa_mode": qa_mode}
    if task_id is not None:
        data["task_id"] = task_id
    _write(project_dir / ".claude" / "dev-registry" / dev_session_id / "qa.json", data)


def _run_hook(project_dir: Path, agent_id: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps({"agent_id": agent_id}),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


WRITE_QA_MODE_SH = REPO_ROOT / "scripts" / "write-qa-mode.sh"


def _run_write_qa_mode(project_dir: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    return subprocess.run(
        ["bash", str(WRITE_QA_MODE_SH), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# M5: scripts/write-qa-mode.sh --task-id (blast-radius coverage_gap closure)
# ---------------------------------------------------------------------------


def test_write_qa_mode_sh_task_id_is_written_and_backward_compatible(tmp_path):
    """M5: --task-id writes a task_id field into qa.json alongside qa_mode,
    and omitting --task-id leaves the field absent (backward compatible with
    every pre-fix caller)."""
    dev_session_id = "dev-20260101-000000"
    session_dir = tmp_path / ".claude" / "dev-registry" / dev_session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "qa.json").write_text(
        json.dumps({"agent_type": "qa", "session_id": dev_session_id}), encoding="utf-8"
    )

    # Without --task-id: backward-compatible, field stays absent.
    proc1 = _run_write_qa_mode(
        tmp_path, "--session-id", dev_session_id, "--mode", "final_verification"
    )
    assert proc1.returncode == 0, proc1.stderr
    data1 = json.loads((session_dir / "qa.json").read_text(encoding="utf-8"))
    assert data1["qa_mode"] == "final_verification"
    assert "task_id" not in data1

    # With --task-id: field is written verbatim.
    task_id = "20260202-111111"
    proc2 = _run_write_qa_mode(
        tmp_path,
        "--session-id", dev_session_id,
        "--mode", "final_verification",
        "--task-id", task_id,
    )
    assert proc2.returncode == 0, proc2.stderr
    data2 = json.loads((session_dir / "qa.json").read_text(encoding="utf-8"))
    assert data2["task_id"] == task_id
    assert data2["qa_mode"] == "final_verification"


def test_write_qa_mode_sh_rejects_unsafe_task_id(tmp_path):
    """AC5-adjacent: write-qa-mode.sh's own --task-id validator rejects an
    unsafe value before it ever reaches the qa.json sentinel or the hook."""
    dev_session_id = "dev-20260101-000000"
    session_dir = tmp_path / ".claude" / "dev-registry" / dev_session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "qa.json").write_text(
        json.dumps({"agent_type": "qa", "session_id": dev_session_id}), encoding="utf-8"
    )

    proc = _run_write_qa_mode(
        tmp_path,
        "--session-id", dev_session_id,
        "--mode", "final_verification",
        "--task-id", "../../etc/passwd",
    )
    assert proc.returncode == 1
    assert "unsafe characters" in proc.stderr


# ---------------------------------------------------------------------------
# AC1: cross-session correlation via anchored task_id succeeds
# ---------------------------------------------------------------------------


def test_ac1_direct_call_resolves_task_id_anchor(tmp_path, capsys):
    """AC1 unit leg: _find_latest_qa_report(project_dir, dev_session_id,
    task_id=T) returns qa-report-<T>.json's Path when T's timestamp differs
    from dev_session_id's, and tags the resolution branch via M9."""
    dev_session_id = "dev-20260101-000000"
    task_id = "20260202-111111"
    _write(tmp_path / "docs" / "dev" / f"qa-report-{task_id}.json", _qa_report(task_id))

    result = HOOK._find_latest_qa_report(str(tmp_path), dev_session_id, task_id=task_id)

    assert result is not None
    assert result.name == f"qa-report-{task_id}.json"
    captured = capsys.readouterr()
    assert "branch=task_id_anchor_match" in captured.err


def test_ac1_hook_exits_zero_cross_session(tmp_path):
    """AC1 integration leg: the full hook exits 0 for a cross-session close
    whose qa.json sentinel carries the orchestrator-anchored task_id, even
    though dev_session_id's own timestamp cannot correlate to the report."""
    dev_session_id = "dev-20260101-000000"
    task_id = "20260202-111111"
    agent_id = "agent-close-cross-session"

    _register_agent(tmp_path, agent_id, dev_session_id)
    _enable_e2e_enforcement(tmp_path, dev_session_id)
    _write_qa_sentinel(tmp_path, dev_session_id, task_id=task_id)
    _write(tmp_path / "docs" / "dev" / f"qa-report-{task_id}.json", _qa_report(task_id))

    proc = _run_hook(tmp_path, agent_id)

    assert proc.returncode == 0, proc.stderr


# ---------------------------------------------------------------------------
# AC2a: fail-closed -- no correlation possible
# ---------------------------------------------------------------------------


def test_ac2a_no_anchor_no_session_correlation_exits_2(tmp_path):
    """AC2a: no session_ts filename/content match, no task_id anchor, and no
    qa-report-<task_id>.json for any candidate -> exit 2, E2E_ENFORCE_BLOCKED.
    This is one of the two branches this hook exists for -- it must never be
    weakened, so it gets its own dedicated assertion (not incidental
    coverage from a pass-path test)."""
    dev_session_id = "dev-20260101-000000"
    agent_id = "agent-no-correlation"

    _register_agent(tmp_path, agent_id, dev_session_id)
    _enable_e2e_enforcement(tmp_path, dev_session_id)
    _write_qa_sentinel(tmp_path, dev_session_id)  # no task_id field
    # An unrelated report exists so the empty-glob short-circuit (AC2b) is
    # NOT what is being exercised here -- this is genuinely "no correlation".
    _write(
        tmp_path / "docs" / "dev" / "qa-report-20269999-999999.json",
        _qa_report("20269999-999999"),
    )

    proc = _run_hook(tmp_path, agent_id)

    assert proc.returncode == 2
    assert "E2E_ENFORCE_BLOCKED" in proc.stderr
    assert "qa-report-*.json" in proc.stderr


def test_ac2a_unit_no_match_returns_none_untagged(tmp_path, capsys):
    """AC2a unit leg: _find_latest_qa_report itself returns None (not just
    the wrapping hook's exit code) when neither dimension matches, and emits
    no resolution-branch tag at all (M9 only tags successful returns)."""
    dev_session_id = "dev-20260101-000000"
    _write(
        tmp_path / "docs" / "dev" / "qa-report-20269999-999999.json",
        _qa_report("20269999-999999"),
    )

    result = HOOK._find_latest_qa_report(str(tmp_path), dev_session_id, task_id=None)

    assert result is None
    captured = capsys.readouterr()
    assert "branch=" not in captured.err


# ---------------------------------------------------------------------------
# AC2b: fail-closed -- report missing
# ---------------------------------------------------------------------------


def test_ac2b_report_genuinely_missing_exits_2(tmp_path):
    """AC2b: zero qa-report-*.json files exist at all -> exit 2 (unchanged
    pre-fix behavior), regardless of whether a task_id anchor is present.
    This is the second of the two branches this hook exists for -- dedicated
    assertion, not incidental coverage."""
    dev_session_id = "dev-20260101-000000"
    task_id = "20260202-111111"
    agent_id = "agent-report-missing"

    _register_agent(tmp_path, agent_id, dev_session_id)
    _enable_e2e_enforcement(tmp_path, dev_session_id)
    _write_qa_sentinel(tmp_path, dev_session_id, task_id=task_id)
    (tmp_path / "docs" / "dev").mkdir(parents=True, exist_ok=True)
    # deliberately write NO qa-report-*.json anywhere

    proc = _run_hook(tmp_path, agent_id)

    assert proc.returncode == 2


def test_ac2b_unit_empty_glob_short_circuits_to_none(tmp_path):
    """AC2b unit leg: an empty docs/dev/ (glob() returns zero matches)
    short-circuits to None before either correlation dimension runs, even
    with a well-formed task_id anchor present."""
    (tmp_path / "docs" / "dev").mkdir(parents=True, exist_ok=True)

    result = HOOK._find_latest_qa_report(
        str(tmp_path), "dev-20260101-000000", task_id="20260202-111111"
    )

    assert result is None


# ---------------------------------------------------------------------------
# AC3: unchanged behavior when session timestamp equals task timestamp
# ---------------------------------------------------------------------------


def test_ac3_session_ts_branch_wins_without_task_id(tmp_path, capsys):
    """AC3 sub-case 1: no task_id field at all -- the pre-existing branch
    resolves, tagged session_ts_filename_match (byte-identical outcome to
    pre-fix behavior)."""
    ts = "20260303-222222"
    dev_session_id = f"dev-{ts}"
    _write(tmp_path / "docs" / "dev" / f"qa-report-{ts}.json", _qa_report(ts))

    result = HOOK._find_latest_qa_report(str(tmp_path), dev_session_id, task_id=None)

    assert result is not None
    assert result.name == f"qa-report-{ts}.json"
    captured = capsys.readouterr()
    assert "branch=session_ts_filename_match" in captured.err
    assert "branch=task_id_anchor_match" not in captured.err


def test_ac3_session_ts_branch_wins_with_matching_task_id(tmp_path, capsys):
    """AC3 sub-case 2 (the ambiguous overlap case): task_id=<T> IS present
    and T's timestamp equals the session timestamp, so BOTH the pre-existing
    session_ts branch and the new task_id-anchor branch could independently
    resolve to the identical file. M2 requires the pre-existing branch to
    run FIRST and win; M9's stderr tag makes that externally observable."""
    ts = "20260303-222222"
    dev_session_id = f"dev-{ts}"
    _write(tmp_path / "docs" / "dev" / f"qa-report-{ts}.json", _qa_report(ts))

    result = HOOK._find_latest_qa_report(str(tmp_path), dev_session_id, task_id=ts)

    assert result is not None
    assert result.name == f"qa-report-{ts}.json"
    captured = capsys.readouterr()
    assert "branch=session_ts_filename_match" in captured.err
    assert "branch=task_id_anchor_match" not in captured.err


def test_ac3_hook_exits_zero_both_subcases(tmp_path):
    """AC3 integration leg: both sub-cases exit 0 end-to-end via main()."""
    ts = "20260303-222222"
    dev_session_id = f"dev-{ts}"
    agent_id = "agent-same-timestamp"

    _register_agent(tmp_path, agent_id, dev_session_id)
    _enable_e2e_enforcement(tmp_path, dev_session_id)
    _write(tmp_path / "docs" / "dev" / f"qa-report-{ts}.json", _qa_report(ts))

    # Sub-case 1: no task_id field in the sentinel.
    _write_qa_sentinel(tmp_path, dev_session_id)
    proc1 = _run_hook(tmp_path, agent_id)
    assert proc1.returncode == 0, proc1.stderr

    # Sub-case 2: task_id present, its timestamp equal to the session's.
    _write_qa_sentinel(tmp_path, dev_session_id, task_id=ts)
    proc2 = _run_hook(tmp_path, agent_id)
    assert proc2.returncode == 0, proc2.stderr


# ---------------------------------------------------------------------------
# AC5: unsafe task_id degrades to no-anchor, not a crash
# ---------------------------------------------------------------------------


def test_ac5_path_traversal_task_id_does_not_escape_or_crash(tmp_path, capsys):
    """AC5: a path-traversal-shaped task_id is rejected outright (treated as
    absent) -- no exception, no path escaping docs/dev/, falls through to
    the pre-existing session_ts branches / eventual None."""
    dev_session_id = "dev-20260101-000000"
    unsafe = "../../etc/passwd"

    result = HOOK._find_latest_qa_report(str(tmp_path), dev_session_id, task_id=unsafe)

    assert result is None
    captured = capsys.readouterr()
    assert "branch=task_id_anchor_match" not in captured.err


def test_ac5_empty_task_id_is_treated_as_absent(tmp_path):
    """AC5: an empty-string task_id is treated as absent, not a truthy
    anchor value that would otherwise glob docs/dev/qa-report-*.json."""
    result = HOOK._find_latest_qa_report(str(tmp_path), "dev-20260101-000000", task_id="")
    assert result is None


def _write_do_report_skeleton(
    project_dir: Path, task_id: str, expected_absent: list[str]
) -> None:
    _write(
        project_dir / "docs" / "dev" / f"do-report-{task_id}.json",
        {
            "report_version": 1,
            "task_id": task_id,
            "request_id": task_id,
            "source": "do",
            "expected_absent": expected_absent,
        },
    )


# ---------------------------------------------------------------------------
# AC7/AC8: /do-profile expected_absent skip of the missing-qa-report block
# (ticket-20260930-132644-l2)
# ---------------------------------------------------------------------------


def test_ac7_do_profile_expected_absent_qa_report_skips_block(tmp_path):
    """AC7: a do-report-<TID>.json sibling declaring 'qa-report' in its
    top-level expected_absent array suppresses the qa_report_path is None
    branch's sys.exit(2) -- the hook exits 0 instead."""
    dev_session_id = "dev-20260101-000000"
    task_id = "20260202-111111"
    agent_id = "agent-do-profile"

    _register_agent(tmp_path, agent_id, dev_session_id)
    _enable_e2e_enforcement(tmp_path, dev_session_id)
    _write_qa_sentinel(tmp_path, dev_session_id, task_id=task_id)
    (tmp_path / "docs" / "dev").mkdir(parents=True, exist_ok=True)
    # Deliberately no qa-report-*.json anywhere.
    _write_do_report_skeleton(
        tmp_path,
        task_id,
        ["qa-report", "dev-report", "ticket", "context", "completion"],
    )

    proc = _run_hook(tmp_path, agent_id)

    assert proc.returncode == 0, proc.stderr


def test_ac7_unit_qa_report_expected_absent_true(tmp_path):
    """AC7 unit leg: _qa_report_expected_absent itself returns True when the
    sibling do-report skeleton declares 'qa-report' expected-absent."""
    task_id = "20260202-111111"
    _write_do_report_skeleton(tmp_path, task_id, ["qa-report"])
    qa_sentinel = {"agent_type": "qa", "task_id": task_id}

    result = HOOK._qa_report_expected_absent(str(tmp_path), "dev-20260101-000000", qa_sentinel)

    assert result is True


def test_ac8_non_do_session_still_blocks_on_genuinely_missing_report(tmp_path):
    """AC8 regression guard: the AC7 setup MINUS the do-report skeleton (an
    ordinary /dev session) still exits 2 with the exact pre-existing
    E2E_ENFORCE_BLOCKED message -- the fix must not weaken the common,
    non-/do baseline."""
    dev_session_id = "dev-20260101-000000"
    task_id = "20260202-111111"
    agent_id = "agent-ordinary-dev"

    _register_agent(tmp_path, agent_id, dev_session_id)
    _enable_e2e_enforcement(tmp_path, dev_session_id)
    _write_qa_sentinel(tmp_path, dev_session_id, task_id=task_id)
    (tmp_path / "docs" / "dev").mkdir(parents=True, exist_ok=True)
    # No do-report-<TID>.json exists at all.

    proc = _run_hook(tmp_path, agent_id)

    assert proc.returncode == 2
    assert "E2E_ENFORCE_BLOCKED" in proc.stderr


def test_ac8_unit_qa_report_expected_absent_false_without_do_report(tmp_path):
    """AC8 unit leg: with no do-report skeleton and no expected_absent field
    on qa.json either, _qa_report_expected_absent returns False."""
    qa_sentinel = {"agent_type": "qa", "task_id": "20260202-111111"}

    result = HOOK._qa_report_expected_absent(
        str(tmp_path), "dev-20260101-000000", qa_sentinel
    )

    assert result is False


def test_ac5_unsafe_task_id_falls_through_to_session_ts_match(tmp_path, capsys):
    """AC5: an unsafe task_id never blocks the pre-existing session_ts
    branch from still matching when it otherwise would -- fail-closed
    degradation, not fail-open."""
    ts = "20260404-333333"
    dev_session_id = f"dev-{ts}"
    _write(tmp_path / "docs" / "dev" / f"qa-report-{ts}.json", _qa_report(ts))

    result = HOOK._find_latest_qa_report(
        str(tmp_path), dev_session_id, task_id="../../etc/passwd"
    )

    assert result is not None
    assert result.name == f"qa-report-{ts}.json"
    captured = capsys.readouterr()
    assert "branch=session_ts_filename_match" in captured.err
