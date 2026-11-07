#!/usr/bin/env python3
"""Tests for hooks/subagentstop-e2e-enforce.py's QA-report resolution.

A QA dispatch that carries an obligation is judged on exactly the qa-report
its obligation declares, at the declared path, never on another report of the
session or the task (P1b row 3): AC1 (cross-session pass), AC2b (the declared
report missing exits 2), the declared report not shadowed by a same-session
report either way, and a dispatch that declares no qa-report (BA validation,
close QA) owing no E2E evidence. A QA dispatch without an obligation keeps the
session_ts correlation (P1c row 10): AC2a (no correlation exits 2), AC3
(same-timestamp match, with branch-identity proof via M9's stderr tag) and the
/do-profile expected_absent skip (AC7/AC8). What a QA owes comes from its own
dispatch obligation (P1b E7), never from a switch in qa.json.

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
from datetime import datetime, timezone
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


def _dispatch_qa(
    project_dir: Path, agent_id: str, task_id: str, schema: str = "qa-report.v2",
    artifacts: list | None = None,
) -> Path:
    """The QA's dispatch transcript: its first record is the dispatch prompt,
    whose obligation declares the report the QA owes (the record E7 reads)."""
    report = "ba-qa-report" if schema.startswith("ba-qa-report") else "qa-report"
    doc = {
        "task_id": task_id, "role": "qa", "pipeline": "dev",
        "profile": "ba_validation" if report == "ba-qa-report" else "final_verification",
        "dispatched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "artifacts": artifacts or [{"kind": "json", "path": f"docs/dev/{report}-{task_id}.json",
                                    "schema": schema, "identity": {"task_id": task_id}}],
    }
    path = project_dir / "transcripts" / f"agent-{agent_id}.jsonl"
    prompt = f'<obligation v="1">\n{json.dumps(doc)}\n</obligation>\nYou are the QA subagent.'
    _write(path, json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n")
    return path


def _run_hook(project_dir: Path, agent_id: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    payload = {"agent_id": agent_id, "session_id": "session-e2e"}
    transcript = project_dir / "transcripts" / f"agent-{agent_id}.jsonl"
    if transcript.exists():
        payload["agent_transcript_path"] = str(transcript)
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# AC1: cross-session correlation via anchored task_id succeeds
# ---------------------------------------------------------------------------


def test_ac1_hook_exits_zero_cross_session(tmp_path):
    """AC1 integration leg: the full hook exits 0 for a cross-session close
    whose dispatch obligation names the task_id, even though
    dev_session_id's own timestamp cannot correlate to the report."""
    dev_session_id = "dev-20260101-000000"
    task_id = "20260202-111111"
    agent_id = "agent-close-cross-session"

    _register_agent(tmp_path, agent_id, dev_session_id)
    _enable_e2e_enforcement(tmp_path, dev_session_id)
    _dispatch_qa(tmp_path, agent_id, task_id)
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
    # No dispatch obligation: no task_id anchor.
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
    the wrapping hook's exit code) when the session timestamp matches
    nothing, and emits no resolution-branch tag at all (M9 only tags
    successful returns)."""
    dev_session_id = "dev-20260101-000000"
    _write(
        tmp_path / "docs" / "dev" / "qa-report-20269999-999999.json",
        _qa_report("20269999-999999"),
    )

    result = HOOK._find_latest_qa_report(str(tmp_path), dev_session_id)

    assert result is None
    captured = capsys.readouterr()
    assert "branch=" not in captured.err


# ---------------------------------------------------------------------------
# AC2b: fail-closed -- report missing
# ---------------------------------------------------------------------------


def test_ac2b_report_genuinely_missing_exits_2(tmp_path):
    """AC2b: the qa-report the QA's obligation declares does not exist -> exit
    2 naming that path. This is the second of the two branches this hook
    exists for -- dedicated assertion, not incidental coverage."""
    dev_session_id = "dev-20260101-000000"
    task_id = "20260202-111111"
    agent_id = "agent-report-missing"

    _register_agent(tmp_path, agent_id, dev_session_id)
    _enable_e2e_enforcement(tmp_path, dev_session_id)
    _dispatch_qa(tmp_path, agent_id, task_id)
    (tmp_path / "docs" / "dev").mkdir(parents=True, exist_ok=True)
    # deliberately write NO qa-report-*.json anywhere

    proc = _run_hook(tmp_path, agent_id)

    assert proc.returncode == 2
    assert f"docs/dev/qa-report-{task_id}.json but no such file exists" in proc.stderr


def test_ac2b_unit_empty_glob_short_circuits_to_none(tmp_path):
    """AC2b unit leg: an empty docs/dev/ (glob() returns zero matches)
    short-circuits to None before the session_ts correlation runs."""
    (tmp_path / "docs" / "dev").mkdir(parents=True, exist_ok=True)

    result = HOOK._find_latest_qa_report(str(tmp_path), "dev-20260101-000000")

    assert result is None


# ---------------------------------------------------------------------------
# AC3: unchanged behavior when session timestamp equals task timestamp
# ---------------------------------------------------------------------------


def test_ac3_session_ts_branch_resolves_without_obligation(tmp_path, capsys):
    """AC3: a QA dispatch without an obligation -- the session_ts branch
    resolves, tagged session_ts_filename_match."""
    ts = "20260303-222222"
    dev_session_id = f"dev-{ts}"
    _write(tmp_path / "docs" / "dev" / f"qa-report-{ts}.json", _qa_report(ts))

    result = HOOK._find_latest_qa_report(str(tmp_path), dev_session_id)

    assert result is not None
    assert result.name == f"qa-report-{ts}.json"
    captured = capsys.readouterr()
    assert "branch=session_ts_filename_match" in captured.err


def test_ac3_hook_exits_zero_both_subcases(tmp_path):
    """AC3 integration leg: both sub-cases exit 0 end-to-end via main()."""
    ts = "20260303-222222"
    dev_session_id = f"dev-{ts}"
    agent_id = "agent-same-timestamp"

    _register_agent(tmp_path, agent_id, dev_session_id)
    _enable_e2e_enforcement(tmp_path, dev_session_id)
    _write(tmp_path / "docs" / "dev" / f"qa-report-{ts}.json", _qa_report(ts))

    # Sub-case 1: no dispatch obligation, so no task_id anchor.
    proc1 = _run_hook(tmp_path, agent_id)
    assert proc1.returncode == 0, proc1.stderr

    # Sub-case 2: an obligation declaring the report, its task_id equal to
    # the session's timestamp.
    _dispatch_qa(tmp_path, agent_id, ts)
    proc2 = _run_hook(tmp_path, agent_id)
    assert proc2.returncode == 0, proc2.stderr


# ---------------------------------------------------------------------------
# P1b row 3: the declared report alone, never a same-session one
# ---------------------------------------------------------------------------


def test_declared_report_is_judged_not_a_same_session_report(tmp_path):
    """A same-timestamp report the dispatch does not declare is not
    correlated: a failing one beside the declared passing report does not
    block, and a passing one does not mask the declared report's absence
    (the fault pilot's newest-file case)."""
    ts = "20260303-222222"
    dev_session_id = f"dev-{ts}"
    agent_id = "agent-lane-qa"
    task_id = f"{ts}-l1"
    _register_agent(tmp_path, agent_id, dev_session_id)
    _enable_e2e_enforcement(tmp_path, dev_session_id)
    _dispatch_qa(tmp_path, agent_id, task_id)
    _write(tmp_path / "docs" / "dev" / f"qa-report-{ts}-l2.json",
           _qa_report(f"{ts}-l2", status="skipped_without_justification"))
    _write(tmp_path / "docs" / "dev" / f"qa-report-{task_id}.json", _qa_report(task_id))

    passing = _run_hook(tmp_path, agent_id)
    assert passing.returncode == 0, passing.stderr

    (tmp_path / "docs" / "dev" / f"qa-report-{task_id}.json").unlink()
    _write(tmp_path / "docs" / "dev" / f"qa-report-{ts}-l2.json", _qa_report(f"{ts}-l2"))
    missing = _run_hook(tmp_path, agent_id)
    assert missing.returncode == 2
    assert f"docs/dev/qa-report-{task_id}.json but no such file exists" in missing.stderr


def test_close_qa_declaring_no_qa_report_is_not_judged(tmp_path):
    """A close QA (its obligation declares the close report, no qa-report)
    owes no E2E evidence here: the cycle's session-correlated qa-report,
    failing or not, is not judged at its stop."""
    ts = "20260303-222222"
    dev_session_id = f"dev-{ts}"
    agent_id = "agent-close-qa"
    _register_agent(tmp_path, agent_id, dev_session_id)
    _enable_e2e_enforcement(tmp_path, dev_session_id)
    _dispatch_qa(tmp_path, agent_id, ts, artifacts=[{
        "kind": "markdown", "path": f"docs/dev/close-report-{ts}.md",
        "identity_anchor": ts, "terminal_line_regex": "^CLOSE: YES$"}])
    _write(tmp_path / "docs" / "dev" / f"qa-report-{ts}.json",
           _qa_report(ts, status="skipped_without_justification"))

    proc = _run_hook(tmp_path, agent_id)

    assert proc.returncode == 0, proc.stderr


def test_traversal_declared_path_is_not_read(tmp_path):
    """A declared qa-report path that is not repo-relative and traversal-free
    (possible only in a block that fails the grammar) is not read: no file
    outside the project is judged."""
    dev_session_id = "dev-20260101-000000"
    agent_id = "agent-traversal"
    project = tmp_path / "project"
    _register_agent(project, agent_id, dev_session_id)
    _enable_e2e_enforcement(project, dev_session_id)
    _write(tmp_path / "outside" / "qa-report.json",
           _qa_report("x", status="skipped_without_justification"))
    _dispatch_qa(project, agent_id, "20260101-000000", artifacts=[{
        "kind": "json", "path": "../outside/qa-report.json", "schema": "qa-report.v2",
        "identity": {"task_id": "20260101-000000"}}])

    proc = _run_hook(project, agent_id)

    assert proc.returncode == 0, proc.stderr


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
    """AC7: for a QA dispatch without an obligation, a session-correlated
    do-report sibling declaring 'qa-report' in its top-level expected_absent
    array suppresses the qa_report_path is None branch's sys.exit(2) -- the
    hook exits 0 instead."""
    task_id = "20260202-111111"
    dev_session_id = f"dev-{task_id}"
    agent_id = "agent-do-profile"

    _register_agent(tmp_path, agent_id, dev_session_id)
    _enable_e2e_enforcement(tmp_path, dev_session_id)
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
    session-correlated do-report skeleton declares 'qa-report' expected-absent."""
    task_id = "20260202-111111"
    _write_do_report_skeleton(tmp_path, task_id, ["qa-report"])

    result = HOOK._qa_report_expected_absent(str(tmp_path), f"dev-{task_id}")

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
    _dispatch_qa(tmp_path, agent_id, task_id)
    (tmp_path / "docs" / "dev").mkdir(parents=True, exist_ok=True)
    # No do-report-<TID>.json exists at all.

    proc = _run_hook(tmp_path, agent_id)

    assert proc.returncode == 2
    assert "E2E_ENFORCE_BLOCKED" in proc.stderr


def test_ac8_unit_qa_report_expected_absent_false_without_do_report(tmp_path):
    """AC8 unit leg: with no do-report skeleton, _qa_report_expected_absent
    returns False."""
    result = HOOK._qa_report_expected_absent(str(tmp_path), "dev-20260202-111111")

    assert result is False


# ---------------------------------------------------------------------------
# P1b E7: BA validation is read from the QA's own dispatch obligation
# ---------------------------------------------------------------------------


def test_ba_validation_qa_owes_no_e2e_evidence(tmp_path):
    """A QA whose obligation declares the BA-QA report stops without any
    qa-report, in an e2e-enforced session."""
    dev_session_id = "dev-20260101-000000"
    agent_id = "agent-ba-validation"
    _register_agent(tmp_path, agent_id, dev_session_id)
    _enable_e2e_enforcement(tmp_path, dev_session_id)
    _dispatch_qa(tmp_path, agent_id, "20260101-000000", schema="ba-qa-report.v1")
    (tmp_path / "docs" / "dev").mkdir(parents=True, exist_ok=True)

    proc = _run_hook(tmp_path, agent_id)

    assert proc.returncode == 0, proc.stderr


def test_qa_json_switch_is_not_read(tmp_path):
    """A qa_mode left in qa.json by the earlier text does not exempt a QA whose
    obligation declares a qa-report: the record decides."""
    dev_session_id = "dev-20260101-000000"
    agent_id = "agent-final-qa"
    _register_agent(tmp_path, agent_id, dev_session_id)
    _enable_e2e_enforcement(tmp_path, dev_session_id)
    _write(tmp_path / ".claude" / "dev-registry" / dev_session_id / "qa.json",
           {"agent_type": "qa", "session_id": dev_session_id, "qa_mode": "ba_validation"})
    _dispatch_qa(tmp_path, agent_id, "20260101-000000")
    (tmp_path / "docs" / "dev").mkdir(parents=True, exist_ok=True)

    proc = _run_hook(tmp_path, agent_id)

    assert proc.returncode == 2
    assert "E2E_ENFORCE_BLOCKED" in proc.stderr
