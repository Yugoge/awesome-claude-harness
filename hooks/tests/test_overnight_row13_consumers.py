#!/usr/bin/env python3
"""/dev-overnight consumers trust one conclusion (P1b row 13, consumer side).

- The PM test plan, triage and retro reports and the specialists' reports are
  declared by their dispatch obligations (commands/dev-overnight.md) with a
  registered schema each; G2 checks them at the producer's stop, so the prose
  validations, the Step 6 legacy fallback and check-overnight-reports.py go.
  Each schema admits the report its producer's agent file declares and
  refuses what the deleted prose check refused.
- scripts/overnight-status.sh reads the record through lib/overnight.py and
  exits non-zero once the window has closed (the TIME CHECK routes on that).
- scripts/check-overnight-reports.sh stays at its path as an exit-0 stub.
- The trace hook files a dispatch under the cycle lib/overnight.py's
  cycle_index reads, not under a counter the record no longer holds.
"""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
REPO = HOOKS.parent
sys.path.insert(0, str(HOOKS))
from lib import contract_runtime, schema_registry  # noqa: E402

COMMAND = REPO / "commands" / "dev-overnight.md"
STATUS = REPO / "scripts" / "overnight-status.sh"
SID = "sess-row13"
TASK = "20261028-120000"


def _iso(delta_minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=delta_minutes)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


TEST_PLAN = {
    "plan_id": "tp-20261028-120000", "task_id": TASK, "version": 1, "session_id": SID,
    "cycle_number": 1,
    "app_context": {"url": "http://localhost:3000", "credentials_available": False},
    "pm_experience": {"app_not_running": False, "urls_visited": ["/"],
                      "actions_taken": [{"url": "/", "action": "opened", "result": "rendered"}]},
    "agent_assignments": {"user": {"mandatory": ["core_flow_execution"]}, "product-owner": {},
                          "architect": {}, "ui-specialist": {}},
    "core_flow_gate": {"owner": "user", "required": True, "failure_is_cycle_failure": True},
    "priority_tiers": {"tier_1_blockers": [], "tier_2_major": [], "tier_3_minor": []},
    "recommended_specialists": [
        {"specialist_type": "user", "decision": "call", "reason": "core flow",
         "degradation_check": {"pre_check_state": "active", "action_taken": "active"}}],
}
TRIAGE = {
    "triage_id": "tr-20261028-121000", "task_id": TASK, "session_id": SID, "cycle_number": 1,
    "mode": "normal", "mode_reason": "no focus",
    "issues": [{"triage_index": 0, "tier": 1, "description": "add() accepts strings",
                "location": "toy/__init__.py", "severity": "major", "category": "correctness",
                "pipeline_recommendation": "fix"}],
    "pipeline_order": [0], "pipeline_blocked": False, "block_reasons": [],
}
RETRO = {
    "retro_id": "rr-20261028-130000", "task_id": TASK, "session_id": SID, "cycle_number": 1,
    "is_final_cycle": False, "plan_vs_outcome": [], "cycle_stats": {"issues_fixed": 1},
    "unresolved_issues": [], "final_summary": None,
}
ARCHITECT = {
    "role": "architect", "task_id": TASK, "timestamp": "2026-10-28T12:05:00Z",
    "issues": [{"id": "arch-1", "description": "add() accepts strings",
                "location": {"file": "toy/__init__.py", "line": 1, "url": None},
                "severity": "major", "category": "runtime-error", "estimated_effort": "small"}],
    "summary": {"issues_found": 1},
}
UI_SPECIALIST = {
    "agent": "ui-specialist", "request_id": TASK, "task_id": TASK,
    "automated_findings": [], "contextual_findings": [], "aesthetic_findings": [],
    "summary": "no findings",
}


def _validate(record, schema_id: str, tmp_path: Path) -> dict:
    path = tmp_path / "report.json"
    path.write_text(json.dumps(record))
    return contract_runtime.validate_artifact_for_obligation(path, schema_id)


def _without(record: dict, dotted: str) -> dict:
    out = copy.deepcopy(record)
    node = out
    *parents, leaf = dotted.split(".")
    for key in parents:
        node = node[int(key)] if isinstance(node, list) else node[key]
    del node[int(leaf) if isinstance(node, list) else leaf]
    return out


def _with(record: dict, dotted: str, value) -> dict:
    out = copy.deepcopy(record)
    node = out
    *parents, leaf = dotted.split(".")
    for key in parents:
        node = node[int(key)] if isinstance(node, list) else node[key]
    node[int(leaf) if isinstance(node, list) else leaf] = value
    return out


# --------------------------------------------------------------------------
# The schemas: registered, admit the producer's declared report, refuse what
# the deleted prose checks refused.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("schema_id", [
    "test-plan.v1", "triage-report.v1", "retro-report.v1", "specialist-report.v1"])
def test_schema_is_registered(schema_id):
    assert schema_registry.get_schema(schema_id) is not None


@pytest.mark.parametrize("record, schema_id", [
    (TEST_PLAN, "test-plan.v1"),
    (_with(_without(TEST_PLAN, "pm_experience.urls_visited"), "pm_experience.app_not_running", True),
     "test-plan.v1"),
    (TRIAGE, "triage-report.v1"),
    (_with(TRIAGE, "issues", []), "triage-report.v1"),
    (RETRO, "retro-report.v1"),
    (_with(_with(RETRO, "is_final_cycle", True), "final_summary", {"total_cycles": 1}),
     "retro-report.v1"),
    (ARCHITECT, "specialist-report.v1"),
    (_with(ARCHITECT, "issues", []), "specialist-report.v1"),
    (UI_SPECIALIST, "specialist-report.v1"),
])
def test_compliant_report_passes(record, schema_id, tmp_path):
    result = _validate(record, schema_id, tmp_path)
    assert result["status"] == "pass", result


@pytest.mark.parametrize("record, schema_id", [
    # Validate test plan (dev-overnight.md Step 2, deleted).
    (_without(TEST_PLAN, "app_context.url"), "test-plan.v1"),
    (_without(TEST_PLAN, "agent_assignments.ui-specialist"), "test-plan.v1"),
    (_with(TEST_PLAN, "core_flow_gate.owner", "architect"), "test-plan.v1"),
    (_with(TEST_PLAN, "core_flow_gate.failure_is_cycle_failure", False), "test-plan.v1"),
    (_with(TEST_PLAN, "pm_experience.urls_visited", []), "test-plan.v1"),
    (_without(TEST_PLAN, "pm_experience.actions_taken"), "test-plan.v1"),
    (_without(TEST_PLAN, "recommended_specialists.0.degradation_check"), "test-plan.v1"),
    # Validate triage report (Step 4, deleted).
    (_without(TRIAGE, "mode"), "triage-report.v1"),
    (_with(TRIAGE, "mode", "panic"), "triage-report.v1"),
    (_without(TRIAGE, "issues"), "triage-report.v1"),
    (_without(TRIAGE, "pipeline_order"), "triage-report.v1"),
    (_without(TRIAGE, "issues.0.tier"), "triage-report.v1"),
    (_without(TRIAGE, "issues.0.pipeline_recommendation"), "triage-report.v1"),
    (_without(TRIAGE, "issues.0.triage_index"), "triage-report.v1"),
    # Validate retro report (Step 20, deleted).
    (_without(RETRO, "plan_vs_outcome"), "retro-report.v1"),
    (_without(RETRO, "unresolved_issues"), "retro-report.v1"),
    (_with(RETRO, "cycle_stats", []), "retro-report.v1"),
    (_with(RETRO, "is_final_cycle", True), "retro-report.v1"),
    # Sanity checks on each report (Step 3, deleted).
    (_without(ARCHITECT, "issues"), "specialist-report.v1"),
    (_without(ARCHITECT, "issues.0.estimated_effort"), "specialist-report.v1"),
    (_with(ARCHITECT, "issues", ARCHITECT["issues"] * 2), "specialist-report.v1"),
    (_without(UI_SPECIALIST, "aesthetic_findings"), "specialist-report.v1"),
    # Every report carries the identity its obligation names.
    (_without(TEST_PLAN, "task_id"), "test-plan.v1"),
    (_without(TRIAGE, "task_id"), "triage-report.v1"),
    (_without(RETRO, "task_id"), "retro-report.v1"),
    (_without(ARCHITECT, "task_id"), "specialist-report.v1"),
])
def test_report_failing_a_moved_check_fails(record, schema_id, tmp_path):
    result = _validate(record, schema_id, tmp_path)
    assert result["status"] == "fail", result


def test_missing_report_fails(tmp_path):
    result = contract_runtime.validate_artifact_for_obligation(tmp_path / "absent.json", "test-plan.v1")
    assert result["status"] == "fail"


# --------------------------------------------------------------------------
# The dispatch templates declare those reports; the prose checks are gone.
# --------------------------------------------------------------------------

def test_pm_and_specialist_dispatches_declare_their_reports():
    text = COMMAND.read_text(encoding="utf-8")
    for path, schema in (
        ("docs/dev/overnight/<session_id>/test-plan.json", "test-plan.v1"),
        ("docs/dev/overnight/<session_id>/<specialist.type>-report.json", "specialist-report.v1"),
        ("docs/dev/overnight/<session_id>/triage-report-cycle<N>.json", "triage-report.v1"),
        ("docs/dev/overnight/<session_id>/retro-report-cycle<N>.json", "retro-report.v1"),
    ):
        declared = re.search(r'"path":\s*"%s",\s*"schema":\s*"%s"' % (re.escape(path), re.escape(schema)),
                             text)
        assert declared, (path, schema)


def test_prose_rechecks_and_the_legacy_fallback_are_gone():
    text = COMMAND.read_text(encoding="utf-8")
    for gone in ("**Validate test plan**", "**Validate triage report**", "**Validate retro report**",
                 "**Sanity checks on each report**", "check-overnight-reports",
                 "**If triage report is missing or invalid**", "**If triage report exists and is valid**",
                 "Issues do not overlap with `addressed_issues`",
                 "Check JSON syntax after modification", "settings.json has syntax error"):
        assert gone not in text, gone


# --------------------------------------------------------------------------
# overnight-status.sh: the window verdict of lib/overnight.py, as its exit.
# --------------------------------------------------------------------------

def _project(tmp_path: Path, end_time: str, cycles_done: int = 0) -> Path:
    claude = tmp_path / ".claude"
    claude.mkdir()
    session_dir = tmp_path / "docs" / "dev" / "overnight" / SID
    session_dir.mkdir(parents=True)
    for cycle in range(1, cycles_done + 1):
        (session_dir / f"retro-report-cycle{cycle}.json").write_text("{}")
    state = claude / f"overnight-state-{SID}.json"
    state.write_text(json.dumps({"session_id": SID, "end_time": end_time, "current_phase": "exploring",
                                 "worktree_path": str(tmp_path), "issues_found": 0}))
    return state


def _status(*args, project: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    env.pop("OVERNIGHT_STATE_DIR", None)
    return subprocess.run(["bash", str(STATUS), *args], capture_output=True, text=True, env=env,
                          timeout=30)


def test_status_open_window_exits_zero_with_cycle_index(tmp_path):
    state = _project(tmp_path, _iso(90), cycles_done=2)
    for args in ((SID,), (str(state),), ()):
        run = _status(*args, project=tmp_path)
        assert run.returncode == 0, (args, run.stderr)
        assert "Cycle:    3" in run.stdout
        assert "Window:   open," in run.stdout


def test_status_closed_window_exits_nonzero(tmp_path):
    state = _project(tmp_path, _iso(-5))
    run = _status(str(state), project=tmp_path)
    assert run.returncode == 1, run.stderr
    assert "Window:   closed" in run.stdout


def test_status_without_a_record_exits_nonzero(tmp_path):
    run = _status("no-such-session", project=tmp_path)
    assert run.returncode == 1
    assert "No overnight session found." in run.stdout


# --------------------------------------------------------------------------
# The stubbed shell entry and the trace's cycle.
# --------------------------------------------------------------------------

def test_check_overnight_reports_is_an_exit_zero_stub(tmp_path):
    script = REPO / "scripts" / "check-overnight-reports.sh"
    assert os.access(script, os.X_OK)
    assert any(line.startswith("# STUB:") for line in script.read_text().splitlines())
    for args in ((f"docs/dev/overnight/{SID}",), ("--session-id", SID), ()):
        assert subprocess.run(["bash", str(script), *args], cwd=tmp_path,
                              capture_output=True).returncode == 0
    assert not (REPO / "scripts" / "check-overnight-reports.py").exists()


def test_trace_is_filed_under_the_cycle_index(tmp_path):
    _project(tmp_path, _iso(90), cycles_done=1)
    contract = tmp_path / "docs" / "dev" / "overnight" / SID / "cycle-2" / "cycle-contract.json"
    contract.parent.mkdir(parents=True)
    contract.write_text(json.dumps({"cycle_id": 2, "required_calls": []}))
    payload = {"session_id": SID, "tool_name": "Agent",
               "tool_input": {"subagent_type": "ba", "prompt": "analyse"},
               "tool_response": {"content": [{"type": "text", "text": "done"}]}}
    run = subprocess.run([sys.executable, str(HOOKS / "posttool-overnight-trace.py")],
                         input=json.dumps(payload), capture_output=True, text=True, timeout=30,
                         env={**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path)})
    assert run.returncode == 0, run.stderr
    trace = contract.parent / "trace.jsonl"
    records = [json.loads(line) for line in trace.read_text().splitlines()]
    assert [r["cycle_id"] for r in records] == [2]
    assert not (tmp_path / "docs" / "dev" / "overnight" / SID / "cycle-0").exists()
