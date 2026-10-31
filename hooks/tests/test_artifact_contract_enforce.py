#!/usr/bin/env python3
"""Tests for hooks/subagentstop-artifact-contract-enforce.py.

The hook is the producer-side port of /close's Artifact schema gate
(contract_runtime.validate_report_artifact): a registered dev/qa subagent in a
session whose artifact-contract-enforce.json flag is enabled must not stop
while its correlated report declares report_version yet violates its schema
(exit 2). A report is the producer's own only when its own dispatch record
names its task; a same-timestamp report the dispatch does not declare is not
correlated. Everything else — unversioned legacy reports, missing reports,
unregistered agents, absent flag, ba_validation QA — passes through (exit 0).
The hook writes no log and no record.

Models tests/test_subagentstop_e2e_enforce.py's fixture and invocation
patterns (importlib for the hyphenated module, subprocess with
CLAUDE_PROJECT_DIR; HOME is redirected per-test so the hook never sees the
real one).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK_PATH = REPO_ROOT / "hooks" / "subagentstop-artifact-contract-enforce.py"
FLAG_WRITER = REPO_ROOT / "scripts" / "write-enforce-flag.sh"

SESSION = "dev-20260101-000000"
SESSION_TS = "20260101-000000"


def _load_hook_module():
    """In-process load of the hyphenated hook module (obligation-mode AC5/AC6
    need direct monkeypatch access to module globals; subprocess cannot be
    monkeypatched). Models tests/test_subagentstop_e2e_enforce.py's pattern."""
    spec = importlib.util.spec_from_file_location(
        "subagentstop_artifact_contract_enforce_under_test", HOOK_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HOOK = _load_hook_module()


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, dict):
        value = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    path.write_text(value, encoding="utf-8")


def _register_agent(
    project_dir: Path, agent_id: str, dev_session_id: str, agent_type: str
) -> None:
    index_path = project_dir / ".claude" / "dev-registry" / "agent-index.json"
    existing: dict = {}
    if index_path.exists():
        existing = json.loads(index_path.read_text(encoding="utf-8"))
    existing[agent_id] = {"agent_type": agent_type, "dev_session_id": dev_session_id}
    _write(index_path, existing)


def _enable_flag(project_dir: Path, dev_session_id: str) -> None:
    _write(
        project_dir / ".claude" / "dev-registry" / dev_session_id
        / "artifact-contract-enforce.json",
        {"enabled": True},
    )


def _write_sentinel(
    project_dir: Path, dev_session_id: str, agent_type: str, **extra
) -> None:
    _write(
        project_dir / ".claude" / "dev-registry" / dev_session_id
        / f"{agent_type}.json",
        {"agent_type": agent_type, "session_id": dev_session_id, **extra},
    )


def _valid_qa_report(task_id: str) -> dict:
    return {
        "report_version": 1,
        "task_id": task_id,
        "verdict": "pass",
        "evidence_summary": {},
        "ui_pipeline": False,
        "qa": {"status": "pass", "evidence_summary": {}, "ui_pipeline": False},
    }


def _invalid_qa_report(task_id: str) -> dict:
    # Declares report_version but omits required verdict/evidence_summary/
    # ui_pipeline — the exact class /close's Artifact schema gate rejects
    # with SCHEMA-GATE FAIL.
    return {"report_version": 1, "task_id": task_id}


def _invalid_dev_report(task_id: str) -> dict:
    return {
        "report_version": 1,
        "task_id": task_id,
        "status": "nonsense",
        "files_modified": [],
        "files_created": [],
        "root_cause_addressed": "x",
        "ac_status": {},
    }


def _run_hook(
    project_dir: Path,
    home_dir: Path,
    agent_id: str,
    mode: str | None = None,
    session_id: str | None = None,
    stopgate_mode: str | None = None,
    last_assistant_message: str | None = None,
    extra_env: dict | None = None,
    hook_path: Path | None = None,
    extra_payload: dict | None = None,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    env["HOME"] = str(home_dir)
    # Transcripts live in the configuration directory; pin it to this HOME.
    env["CLAUDE_CONFIG_DIR"] = str(Path(home_dir) / ".claude")
    env.update(extra_env or {})
    env.pop("ARTIFACT_CONTRACT_ENFORCE_MODE", None)
    if mode is not None:
        env["ARTIFACT_CONTRACT_ENFORCE_MODE"] = mode
    env.pop("CLAUDE_OBLIGATION_STOPGATE", None)
    if stopgate_mode is not None:
        env["CLAUDE_OBLIGATION_STOPGATE"] = stopgate_mode
    payload: dict = {"agent_id": agent_id}
    payload.update(extra_payload or {})
    if session_id is not None:
        payload["session_id"] = session_id
    # ticket 20261001-161041-r12: response_line/waived_by_response/
    # consistency all key off the producer's own final response text.
    if last_assistant_message is not None:
        payload["last_assistant_message"] = last_assistant_message
    return subprocess.run(
        [sys.executable, str(hook_path or HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _project_slug(project_dir: Path) -> str:
    return str(project_dir.resolve()).replace("/", "-")


def _write_obligation_transcript(
    home_dir: Path,
    project_dir: Path,
    harness_session_id: str,
    agent_id: str,
    prompt: str,
) -> None:
    """Minimal harness transcript-store fixture for resolve_own_obligation's
    L1 rung: a subagent transcript whose first record is the dispatch
    prompt, plus a meta.json carrying a toolUseId. The parent transcript is
    deliberately NOT written, so the meta cross-check degrades to "parent
    unreadable" (accepted, not a cross-check failure) -- this lane does not
    test the cross-check itself, only whether an obligation is resolved from
    the dispatch prompt."""
    slug = _project_slug(project_dir)
    subagents_dir = (
        home_dir / ".claude" / "projects" / slug / harness_session_id / "subagents"
    )
    subagents_dir.mkdir(parents=True, exist_ok=True)
    (subagents_dir / f"agent-{agent_id}.jsonl").write_text(
        json.dumps({"type": "user", "message": {"content": prompt}}) + "\n",
        encoding="utf-8",
    )
    (subagents_dir / f"agent-{agent_id}.meta.json").write_text(
        json.dumps({"toolUseId": "tooluse-test-1"}), encoding="utf-8"
    )


def _obligation_block(
    task_id: str, artifact_path: str, schema: str, role: str = "dev"
) -> str:
    doc = {
        "task_id": task_id,
        "role": role,
        "pipeline": "dev",
        "profile": "singular",
        "dispatched_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": [
            {
                "kind": "json",
                "path": artifact_path,
                "schema": schema,
                "identity": {"task_id": task_id},
            }
        ],
    }
    body = json.dumps(doc, indent=2, ensure_ascii=False)
    return f'<obligation v="1">\n{body}\n</obligation>'


def _obligation_block_multi(
    task_id: str, artifacts: list, role: str = "dev", consistency: str | None = None
) -> str:
    """Like :func:`_obligation_block` but takes an explicit artifacts[] list,
    so a single obligation can declare a mix of kinds (ticket
    20261001-161041-r01's markdown-kind coverage: one json + one markdown
    artifact, or a markdown + a response_block, etc.). ``consistency``
    (ticket 20261001-161041-r12) optionally declares the top-level
    ``consistency: "verdict_class"`` field close-QA's own obligation uses."""
    doc = {
        "task_id": task_id,
        "role": role,
        "pipeline": "dev",
        "profile": "singular",
        "dispatched_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": artifacts,
    }
    if consistency is not None:
        doc["consistency"] = consistency
    body = json.dumps(doc, indent=2, ensure_ascii=False)
    return f'<obligation v="1">\n{body}\n</obligation>'


def _valid_dev_report_v1(task_id: str) -> dict:
    return {
        "report_version": 1,
        "task_id": task_id,
        "status": "completed",
        "files_modified": [],
        "files_created": [],
        "root_cause_addressed": "x",
        "ac_status": {},
        "dev": {
            "status": "completed",
            "files_modified": [],
            "files_created": [],
            "git_rationale": {"how_fix_addresses_root": "x"},
            "ac_status": {},
        },
    }


def _written_logs(home_dir: Path) -> list[str]:
    """Files under the scratch home's logs/ directory: the hook writes none."""
    logs = home_dir / ".claude" / "logs"
    return sorted(p.name for p in logs.rglob("*")) if logs.is_dir() else []


def _resolution(home_dir: Path, project_dir: Path, session_id: str, agent_id: str, role: str):
    """What the hook's obligation branch resolves for this stop, read from the
    transcript store the hook reads (the scratch home's projects/)."""
    return HOOK.obligation.resolve_own_obligation(
        session_id=session_id, agent_id=agent_id, project_dir=str(project_dir),
        expected_role=role, roots=[home_dir / ".claude" / "projects"],
    )


def _standard_setup(tmp_path: Path, agent_type: str, agent_id: str, **sentinel_extra):
    project = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    _register_agent(project, agent_id, SESSION, agent_type)
    _enable_flag(project, SESSION)
    _write_sentinel(project, SESSION, agent_type, **sentinel_extra)
    return project, home


LEGACY_SESSION = "harness-legacy"


def _declare_own(project: Path, home: Path, agent_id: str, agent_type: str,
                 task_id: str = SESSION_TS, reports: list | None = None) -> str:
    """The stopping producer's dispatch record, naming task_id in an earlier
    template's obligation (its required_values fail the grammar, so the
    legacy check decides, reading the block as declared). Returns the harness
    session to stop under: the legacy check judges the reports that dispatch
    declares (``reports``, default the task's one report) and no other."""
    if agent_type == "qa" and reports is None:
        block = _pre_p1_qa_obligation(task_id, "qa-report.v1")
    else:
        doc = {
            "task_id": task_id, "role": agent_type, "pipeline": "dev", "profile": "singular",
            "dispatched_at": datetime.now(timezone.utc).isoformat(),
            "artifacts": [{
                "kind": "json", "path": f"docs/dev/{name}",
                "schema": f"{agent_type}-report.v1", "identity": {"task_id": task_id},
                "required_values": {"status": ["completed"]},
            } for name in (reports or [f"{agent_type}-report-{task_id}.json"])],
        }
        block = f'<obligation v="1">\n{json.dumps(doc, indent=2)}\n</obligation>'
    _write_obligation_transcript(home, project, LEGACY_SESSION, agent_id,
                                 f"You are the {agent_type} subagent.\n{block}")
    return LEGACY_SESSION


# ---------------------------------------------------------------------------
# Flag writer: the artifact-contract flag is a first-class write-enforce-flag
# ---------------------------------------------------------------------------


def test_flag_writer_supports_artifact_contract(tmp_path):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    proc = subprocess.run(
        [
            "bash",
            str(FLAG_WRITER),
            "--source-command",
            "dev",
            "--session-id",
            SESSION,
            "--flag",
            "artifact-contract",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Artifact-contract enforcement active:" in proc.stdout
    flag_path = (
        tmp_path / ".claude" / "dev-registry" / SESSION
        / "artifact-contract-enforce.json"
    )
    data = json.loads(flag_path.read_text(encoding="utf-8"))
    assert data["enabled"] is True
    # A flag names no agent types: which roles a gate covers is the gate's own
    # decision, never a list in the flag.
    assert "enforced_agent_types" not in data
    assert data["source_command"] == "dev"


def test_flag_writer_rejects_unknown_flag_naming_known_set(tmp_path):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    proc = subprocess.run(
        [
            "bash",
            str(FLAG_WRITER),
            "--source-command",
            "dev",
            "--session-id",
            SESSION,
            "--flag",
            "bogus",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 1
    assert "artifact-contract" in proc.stderr


# ---------------------------------------------------------------------------
# Fail-open activation chain
# ---------------------------------------------------------------------------


def test_unregistered_agent_allows(tmp_path):
    project = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir()
    (project / "docs" / "dev").mkdir(parents=True)
    proc = _run_hook(project, home, "agent-unknown")
    assert proc.returncode == 0, proc.stderr


def test_flag_absent_allows_even_with_invalid_report(tmp_path):
    project = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir()
    _register_agent(project, "agent-qa-1", SESSION, "qa")
    _write_sentinel(project, SESSION, "qa")
    session = _declare_own(project, home, "agent-qa-1", "qa")
    _write(
        project / "docs" / "dev" / f"qa-report-{SESSION_TS}.json",
        _invalid_qa_report(SESSION_TS),
    )
    proc = _run_hook(project, home, "agent-qa-1", session_id=session)
    assert proc.returncode == 0, proc.stderr


def _pre_p1_qa_obligation(task_id: str, schema: str) -> str:
    """A QA dispatch obligation from an earlier template: its required_values
    no longer parse (invalid_obligation), so the legacy check decides, reading
    the block as declared."""
    report = "ba-qa-report" if schema.startswith("ba-qa-report") else "qa-report"
    doc = {
        "task_id": task_id, "role": "qa", "pipeline": "dev",
        "profile": "ba_validation" if report == "ba-qa-report" else "final_verification",
        "dispatched_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": [{
            "kind": "json", "path": f"docs/dev/{report}-{task_id}.json", "schema": schema,
            "identity": {"task_id": task_id}, "required_values": {"verdict": ["pass"]},
        }],
    }
    return f'<obligation v="1">\n{json.dumps(doc, indent=2)}\n</obligation>'


@pytest.mark.parametrize("schema,expected", [("ba-qa-report.v1", 0), ("qa-report.v1", 2)],
                         ids=["owes_ba_qa_report", "owes_qa_report"])
def test_ba_validation_qa_exempt(tmp_path, schema, expected):
    """P1b E7: a QA whose dispatch declares the BA-QA report owes no
    qa-report, read from its obligation; a qa_mode left in qa.json by the
    earlier text decides nothing."""
    project, home = _standard_setup(
        tmp_path, "qa", "agent-qa-1", qa_mode="ba_validation"
    )
    _write_obligation_transcript(home, project, "harness-ba-qa", "agent-qa-1",
                                 "You are the QA subagent.\n" + _pre_p1_qa_obligation(SESSION_TS, schema))
    _write(
        project / "docs" / "dev" / f"qa-report-{SESSION_TS}.json",
        _invalid_qa_report(SESSION_TS),
    )
    proc = _run_hook(project, home, "agent-qa-1", session_id="harness-ba-qa")
    assert proc.returncode == expected, proc.stderr


# ---------------------------------------------------------------------------
# Blocking surface: versioned-and-invalid only (same as /close's schema gate)
# ---------------------------------------------------------------------------


def test_qa_schema_invalid_blocks(tmp_path):
    project, home = _standard_setup(tmp_path, "qa", "agent-qa-1")
    session = _declare_own(project, home, "agent-qa-1", "qa")
    _write(
        project / "docs" / "dev" / f"qa-report-{SESSION_TS}.json",
        _invalid_qa_report(SESSION_TS),
    )
    proc = _run_hook(project, home, "agent-qa-1", session_id=session)
    assert proc.returncode == 2, proc.stderr
    assert "ARTIFACT_CONTRACT_BLOCKED" in proc.stderr
    assert "qa-report.v1" in proc.stderr
    assert _written_logs(home) == []


def test_dev_schema_invalid_blocks(tmp_path):
    project, home = _standard_setup(tmp_path, "dev", "agent-dev-1")
    session = _declare_own(project, home, "agent-dev-1", "dev")
    _write(
        project / "docs" / "dev" / f"dev-report-{SESSION_TS}.json",
        _invalid_dev_report(SESSION_TS),
    )
    proc = _run_hook(project, home, "agent-dev-1", session_id=session)
    assert proc.returncode == 2, proc.stderr
    assert "ARTIFACT_CONTRACT_BLOCKED" in proc.stderr
    assert "dev-report.v1" in proc.stderr


def test_qa_schema_valid_allows(tmp_path):
    project, home = _standard_setup(tmp_path, "qa", "agent-qa-1")
    session = _declare_own(project, home, "agent-qa-1", "qa")
    _write(
        project / "docs" / "dev" / f"qa-report-{SESSION_TS}.json",
        _valid_qa_report(SESSION_TS),
    )
    proc = _run_hook(project, home, "agent-qa-1", session_id=session)
    assert proc.returncode == 0, proc.stderr


def test_qa_unversioned_legacy_allows(tmp_path):
    # 665 of 674 real reports on disk are unversioned; they must keep passing.
    project, home = _standard_setup(tmp_path, "qa", "agent-qa-1")
    session = _declare_own(project, home, "agent-qa-1", "qa")
    _write(
        project / "docs" / "dev" / f"qa-report-{SESSION_TS}.json",
        {"task_id": SESSION_TS, "verdict": "pass"},
    )
    proc = _run_hook(project, home, "agent-qa-1", session_id=session)
    assert proc.returncode == 0, proc.stderr


def test_missing_report_allows(tmp_path):
    project, home = _standard_setup(tmp_path, "qa", "agent-qa-1")
    session = _declare_own(project, home, "agent-qa-1", "qa")
    (project / "docs" / "dev").mkdir(parents=True, exist_ok=True)
    proc = _run_hook(project, home, "agent-qa-1", session_id=session)
    assert proc.returncode == 0, proc.stderr
    assert _written_logs(home) == []


def test_advisory_mode_never_blocks(tmp_path):
    project, home = _standard_setup(tmp_path, "qa", "agent-qa-1")
    session = _declare_own(project, home, "agent-qa-1", "qa")
    _write(
        project / "docs" / "dev" / f"qa-report-{SESSION_TS}.json",
        _invalid_qa_report(SESSION_TS),
    )
    proc = _run_hook(project, home, "agent-qa-1", mode="advisory", session_id=session)
    assert proc.returncode == 0, proc.stderr
    assert "ARTIFACT_CONTRACT_BLOCKED" not in proc.stderr
    assert _written_logs(home) == []


# ---------------------------------------------------------------------------
# Fan-out: ALL correlated reports are validated (union, not lexicographic pick)
# ---------------------------------------------------------------------------


def test_fanout_invalid_lane_not_shadowed_by_later_valid_sibling(tmp_path):
    # Codex audit finding (HIGH): lane-a invalid must block even though
    # lane-b sorts lexicographically later and is valid. The dev's own
    # dispatch record declares both.
    project, home = _standard_setup(tmp_path, "dev", "agent-dev-1")
    session = _declare_own(project, home, "agent-dev-1", "dev", reports=[
        f"dev-report-{SESSION_TS}-lane-a.json", f"dev-report-{SESSION_TS}-lane-b.json"])
    _write(
        project / "docs" / "dev" / f"dev-report-{SESSION_TS}-lane-a.json",
        _invalid_dev_report(SESSION_TS),
    )
    _write(
        project / "docs" / "dev" / f"dev-report-{SESSION_TS}-lane-b.json",
        {
            "report_version": 1,
            "task_id": SESSION_TS,
            "status": "completed",
            "files_modified": [],
            "files_created": [],
            "root_cause_addressed": "x",
            "ac_status": {},
            "dev": {
                "status": "completed",
                "files_modified": [],
                "files_created": [],
                "git_rationale": {"how_fix_addresses_root": "x"},
                "ac_status": {},
            },
        },
    )
    proc = _run_hook(project, home, "agent-dev-1", session_id=session)
    assert proc.returncode == 2, proc.stderr
    assert "lane-a" in proc.stderr


def test_fanout_all_valid_lane_reports_allow(tmp_path):
    project, home = _standard_setup(tmp_path, "dev", "agent-dev-1")
    session = _declare_own(project, home, "agent-dev-1", "dev", reports=[
        f"dev-report-{SESSION_TS}-lane-a.json", f"dev-report-{SESSION_TS}-lane-b.json"])
    for lane in ("lane-a", "lane-b"):
        _write(
            project / "docs" / "dev" / f"dev-report-{SESSION_TS}-{lane}.json",
            {
                "report_version": 1,
                "task_id": SESSION_TS,
                "status": "completed",
                "files_modified": [],
                "files_created": [],
                "root_cause_addressed": "x",
                "ac_status": {},
                "dev": {
                    "status": "completed",
                    "files_modified": [],
                    "files_created": [],
                    "git_rationale": {"how_fix_addresses_root": "x"},
                    "ac_status": {},
                },
            },
        )
    proc = _run_hook(project, home, "agent-dev-1", session_id=session)
    assert proc.returncode == 0, proc.stderr


def test_fanout_invalid_canonical_not_shadowed_by_valid_shards(tmp_path):
    # Aggregate canonical (no lane suffix) invalid, shards valid: still blocks.
    project, home = _standard_setup(tmp_path, "qa", "agent-qa-1")
    session = _declare_own(project, home, "agent-qa-1", "qa")
    _write(
        project / "docs" / "dev" / f"qa-report-{SESSION_TS}.json",
        _invalid_qa_report(SESSION_TS),
    )
    _write(
        project / "docs" / "dev" / f"qa-report-{SESSION_TS}-lane-a.json",
        _valid_qa_report(SESSION_TS),
    )
    proc = _run_hook(project, home, "agent-qa-1", session_id=session)
    assert proc.returncode == 2, proc.stderr
    assert f"qa-report-{SESSION_TS}.json" in proc.stderr


def test_task_id_anchor_not_shadowed_by_a_same_session_report(tmp_path):
    # /close cross-session shape WITH a valid report named by the session's
    # timestamp beside it: the anchored report (the task_id the QA's own
    # dispatch obligation names, P1b E7) is still validated and blocks.
    task_id = "20251231-235959"
    session = "dev-20260202-020202"
    project = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir()
    _register_agent(project, "agent-qa-1", session, "qa")
    _write(
        project / ".claude" / "dev-registry" / session
        / "artifact-contract-enforce.json",
        {"enabled": True},
    )
    _write_sentinel(project, session, "qa")
    _write_obligation_transcript(home, project, "harness-anchor", "agent-qa-1",
                                 "You are the QA subagent.\n" + _pre_p1_qa_obligation(task_id, "qa-report.v1"))
    # Same-session sibling (valid) + task_id-anchored target (invalid).
    _write(
        project / "docs" / "dev" / "qa-report-20260202-020202.json",
        _valid_qa_report("20260202-020202"),
    )
    _write(
        project / "docs" / "dev" / f"qa-report-{task_id}.json",
        _invalid_qa_report(task_id),
    )
    proc = _run_hook(project, home, "agent-qa-1", session_id="harness-anchor")
    assert proc.returncode == 2, proc.stderr
    assert task_id in proc.stderr


# ---------------------------------------------------------------------------
# Correlation: the task_id anchor works across sessions (close.md Step 2 path)
# ---------------------------------------------------------------------------


def test_task_id_anchor_blocks_when_session_ts_never_matches(tmp_path):
    # The anchor is the task_id the QA's own dispatch obligation names (P1b
    # E7; qa.json carries none): the report filename carries the task_id, not
    # the (different) session timestamp.
    task_id = "20251231-235959"
    session = "dev-20260202-020202"
    project = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir()
    _register_agent(project, "agent-qa-1", session, "qa")
    _write(
        project / ".claude" / "dev-registry" / session
        / "artifact-contract-enforce.json",
        {"enabled": True},
    )
    _write_sentinel(project, session, "qa")
    _write_obligation_transcript(home, project, "harness-anchor", "agent-qa-1",
                                 "You are the QA subagent.\n" + _pre_p1_qa_obligation(task_id, "qa-report.v1"))
    _write(
        project / "docs" / "dev" / f"qa-report-{task_id}.json",
        _invalid_qa_report(task_id),
    )
    proc = _run_hook(project, home, "agent-qa-1", session_id="harness-anchor")
    assert proc.returncode == 2, proc.stderr
    assert "ARTIFACT_CONTRACT_BLOCKED" in proc.stderr


def test_uncorrelated_report_is_not_grabbed(tmp_path):
    # A report from an unrelated task must not be validated against this
    # producer's task: no correlation -> exit 0.
    project, home = _standard_setup(tmp_path, "qa", "agent-qa-1")
    session = _declare_own(project, home, "agent-qa-1", "qa")
    _write(
        project / "docs" / "dev" / "qa-report-20200909-090909.json",
        _invalid_qa_report("20200909-090909"),
    )
    proc = _run_hook(project, home, "agent-qa-1", session_id=session)
    assert proc.returncode == 0, proc.stderr


def test_same_timestamp_report_no_dispatch_declares_is_not_correlated(tmp_path):
    # P1b row 3: the session's timestamp correlates nothing. A schema-invalid
    # report named by it, which no dispatch record of the stopping producer
    # declares, is not that producer's report.
    project, home = _standard_setup(tmp_path, "dev", "agent-dev-1")
    _write(
        project / "docs" / "dev" / f"dev-report-{SESSION_TS}.json",
        _invalid_dev_report(SESSION_TS),
    )
    session = _declare_own(project, home, "agent-dev-1", "dev", task_id="20260101-000001")
    for session_id in (None, session):
        proc = _run_hook(project, home, "agent-dev-1", session_id=session_id)
        assert proc.returncode == 0, proc.stderr
        assert "ARTIFACT_CONTRACT_BLOCKED" not in proc.stderr


# ---------------------------------------------------------------------------
# Obligation mode (rollout S4, ticket-20260930-132644-l2)
# ---------------------------------------------------------------------------


def test_ac1_legacy_path_byte_identical_without_obligation(tmp_path):
    """AC1: whether resolve_own_obligation lands on Unresolvable (no
    session_id supplied) or NoObligationInPrompt (a resolvable transcript
    with no '<obligation' substring), the legacy path's outcome is
    identical -- the obligation branch never changes outcomes it doesn't
    own. With no dispatch record naming a task, no report is the producer's
    own: a same-timestamp schema-invalid report is not correlated (P1b row 3)
    and the stop passes either way."""
    harness_session = "harness-ac1"
    project, home = _standard_setup(tmp_path, "qa", "agent-qa-ac1")
    _write_obligation_transcript(
        home,
        project,
        harness_session,
        "agent-qa-ac1",
        "Implement the QA report for this cycle. No obligation block here.",
    )
    _write(
        project / "docs" / "dev" / f"qa-report-{SESSION_TS}.json",
        _invalid_qa_report(SESSION_TS),
    )
    no_session = _run_hook(project, home, "agent-qa-ac1")
    with_session = _run_hook(project, home, "agent-qa-ac1", session_id=harness_session)
    assert no_session.returncode == 0, no_session.stderr
    assert with_session.returncode == no_session.returncode == 0
    assert (with_session.stdout, with_session.stderr) == (no_session.stdout, no_session.stderr) == ("", "")


def test_ac2_resolved_obligation_missing_artifact_blocks(tmp_path):
    """AC2: a resolvable obligation naming one json artifact that is never
    written to disk, in block mode, exits 2 naming that exact path and the
    fixed closing instruction."""
    harness_session = "harness-ac2"
    agent_id = "agent-dev-ac2"
    task_id = "20260101-000002"
    artifact_path = "docs/dev/dev-report-20260101-000002.json"
    project, home = _standard_setup(tmp_path, "dev", agent_id)
    _write_obligation_transcript(
        home,
        project,
        harness_session,
        agent_id,
        _obligation_block(task_id, artifact_path, "dev-report.v1"),
    )
    proc = _run_hook(
        project, home, agent_id, session_id=harness_session, stopgate_mode="block"
    )
    assert proc.returncode == 2, proc.stderr
    assert artifact_path in proc.stderr
    assert "Do NOT edit any other agent's artifact" in proc.stderr


def test_ac3_resolved_obligation_all_valid_bypasses_legacy_path(tmp_path):
    """AC3: all declared artifacts valid -> exit 0 WITHOUT the legacy
    correlation path ever running. Proof fixture: a DIFFERENT report of the
    same task that IS schema-invalid; if the legacy path ran, it would
    independently block on it."""
    harness_session = "harness-ac3"
    agent_id = "agent-dev-ac3"
    task_id = "20260101-000003"
    artifact_path = "docs/dev/dev-report-20260101-000003.json"
    project, home = _standard_setup(tmp_path, "dev", agent_id)
    _write_obligation_transcript(
        home,
        project,
        harness_session,
        agent_id,
        _obligation_block(task_id, artifact_path, "dev-report.v1"),
    )
    _write(project / artifact_path, _valid_dev_report_v1(task_id))
    _write(
        project / "docs" / "dev" / f"dev-report-{task_id}-stale.json",
        _invalid_dev_report(task_id),
    )
    proc = _run_hook(
        project, home, agent_id, session_id=harness_session, stopgate_mode="block"
    )
    assert proc.returncode == 0, proc.stderr
    assert "ARTIFACT_CONTRACT_BLOCKED" not in proc.stderr


def test_ac4_advisory_mode_never_blocks(tmp_path):
    """AC4: the AC2 setup under advisory mode (the default): the obligation
    resolves, yet the stop exits 0 with no block message and nothing
    written."""
    harness_session = "harness-ac4"
    agent_id = "agent-dev-ac4"
    task_id = "20260101-000004"
    artifact_path = "docs/dev/dev-report-20260101-000004.json"
    project, home = _standard_setup(tmp_path, "dev", agent_id)
    _write_obligation_transcript(
        home,
        project,
        harness_session,
        agent_id,
        _obligation_block(task_id, artifact_path, "dev-report.v1"),
    )
    proc = _run_hook(project, home, agent_id, session_id=harness_session)
    assert proc.returncode == 0, proc.stderr
    assert "OBLIGATION_STOPGATE_BLOCKED" not in proc.stderr
    assert _written_logs(home) == []
    assert isinstance(
        _resolution(home, project, harness_session, agent_id, "dev"), HOOK.obligation.Resolved
    )


def test_ac5_off_switch_never_calls_resolve_own_obligation(monkeypatch, tmp_path):
    """AC5: CLAUDE_OBLIGATION_STOPGATE=off never calls resolve_own_obligation
    at all (call-count spy, not just an outcome assertion) -- the legacy
    path alone determines the exit code."""
    calls = []

    def _spy(*args, **kwargs):
        calls.append((args, kwargs))
        return HOOK.obligation.Unresolvable(reason="should_not_be_called")

    monkeypatch.setattr(HOOK.obligation, "resolve_own_obligation", _spy)
    project, home = _standard_setup(tmp_path, "qa", "agent-qa-ac5")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude"))
    monkeypatch.setenv("CLAUDE_OBLIGATION_STOPGATE", "off")
    monkeypatch.setattr(
        HOOK,
        "_load_stdin",
        lambda: {"agent_id": "agent-qa-ac5", "session_id": "harness-ac5"},
    )
    with pytest.raises(SystemExit) as exc_info:
        HOOK.main()
    assert exc_info.value.code == 0
    assert calls == []


def test_ac6_internal_exception_falls_through_to_legacy_path(
    monkeypatch, tmp_path, capsys
):
    """AC6: a forced exception inside validate_artifact_for_obligation falls
    through; the legacy path's OWN
    schema-invalid correlated report alone determines the final exit code
    (proved by independently making the legacy path find one)."""
    harness_session = "harness-ac6"
    agent_id = "agent-dev-ac6"
    task_id = "20260101-000006"
    artifact_path = "docs/dev/dev-report-20260101-000006.json"
    project, home = _standard_setup(tmp_path, "dev", agent_id)
    _write_obligation_transcript(
        home,
        project,
        harness_session,
        agent_id,
        _obligation_block(task_id, artifact_path, "dev-report.v1"),
    )
    # The report the dispatch declares, at its declared path: the legacy
    # check judges only the stopping producer's own reports.
    _write(project / artifact_path, _invalid_dev_report(task_id))

    def _raise(*_args, **_kwargs):
        raise RuntimeError("forced obligation-mode failure")

    monkeypatch.setattr(HOOK.contract_runtime, "validate_artifact_for_obligation", _raise)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude"))
    monkeypatch.setenv("CLAUDE_OBLIGATION_STOPGATE", "block")
    monkeypatch.setattr(
        HOOK,
        "_load_stdin",
        lambda: {"agent_id": agent_id, "session_id": harness_session},
    )
    with pytest.raises(SystemExit) as exc_info:
        HOOK.main()
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "ARTIFACT_CONTRACT_BLOCKED" in captured.err


# ---------------------------------------------------------------------------
# Markdown-kind obligation verification (ticket 20261001-161041-r01):
# BA's own kind:"markdown" ticket.md now gets the same producer-side Stop
# check context.json (kind:"json") already has. Mirrors the json-kind AC2-
# AC6 tests above, reusing the same _obligation_block_multi/_standard_setup
# harness. Distinct test names (test_markdown_* prefix) avoid colliding with
# the pre-existing json-kind test_ac2..test_ac6 names above, which belong to
# ticket-20260930-132644-l2 and are left untouched.
# ---------------------------------------------------------------------------


def test_markdown_ac2_mixed_kinds_all_valid_bypasses_legacy_path(tmp_path):
    """This ticket's AC2: one valid kind:"json" artifact AND one valid
    kind:"markdown" artifact -> exit 0 WITHOUT the legacy correlation path
    ever running, in block mode. Proof fixture: a DIFFERENT report of the
    same task that IS schema-invalid; if the legacy path ran, it would
    independently block on it (same technique as AC3 above)."""
    harness_session = "harness-md-ac2"
    agent_id = "agent-dev-md-ac2"
    task_id = "20260101-000102"
    json_path = "docs/dev/dev-report-20260101-000102.json"
    md_path = "docs/dev/ticket-20260101-000102.md"
    anchor = f"Request ID: {task_id}"
    project, home = _standard_setup(tmp_path, "dev", agent_id)
    _write_obligation_transcript(
        home,
        project,
        harness_session,
        agent_id,
        _obligation_block_multi(
            task_id,
            [
                {
                    "kind": "json",
                    "path": json_path,
                    "schema": "dev-report.v1",
                    "identity": {"task_id": task_id},
                },
                {
                    "kind": "markdown",
                    "path": md_path,
                    "identity_anchor": anchor,
                    "terminal_line_regex": "^STATUS: ready$",
                },
            ],
        ),
    )
    _write(project / json_path, _valid_dev_report_v1(task_id))
    _write(project / md_path, f"# Ticket\n{anchor}\nSTATUS: ready\n")
    _write(
        project / "docs" / "dev" / f"dev-report-{task_id}-stale.json",
        _invalid_dev_report(task_id),
    )
    proc = _run_hook(
        project, home, agent_id, session_id=harness_session, stopgate_mode="block"
    )
    assert proc.returncode == 0, proc.stderr
    assert "ARTIFACT_CONTRACT_BLOCKED" not in proc.stderr


def test_markdown_ac3_identity_anchor_missing_blocks(tmp_path):
    """This ticket's AC3: the markdown artifact's declared identity_anchor
    substring is absent -> exit 2, stderr names the exact path with a
    reason distinguishable from terminal-line-mismatch wording."""
    harness_session = "harness-md-ac3"
    agent_id = "agent-dev-md-ac3"
    task_id = "20260101-000103"
    md_path = "docs/dev/ticket-20260101-000103.md"
    anchor = f"Request ID: {task_id}"
    project, home = _standard_setup(tmp_path, "dev", agent_id)
    _write_obligation_transcript(
        home,
        project,
        harness_session,
        agent_id,
        _obligation_block_multi(
            task_id,
            [
                {
                    "kind": "markdown",
                    "path": md_path,
                    "identity_anchor": anchor,
                    "terminal_line_regex": "^STATUS: ready$",
                },
            ],
        ),
    )
    _write(project / md_path, "# Ticket\nNo anchor here.\nSTATUS: ready\n")
    proc = _run_hook(
        project, home, agent_id, session_id=harness_session, stopgate_mode="block"
    )
    assert proc.returncode == 2, proc.stderr
    assert md_path in proc.stderr
    assert "identity_anchor" in proc.stderr
    assert "terminal_line_mismatch" not in proc.stderr


def test_markdown_ac4_terminal_line_mismatch_blocks_distinct_from_ac3(tmp_path):
    """This ticket's AC4: identity_anchor present but the last non-empty
    line does not match terminal_line_regex -> exit 2, stderr names the
    path with wording distinct from AC3's (no "identity_anchor" substring),
    matching the precedent already pinned by
    tests/test_aggregate_dev_report.py's
    TestObligationBarrierBlockMarkdownTerminalLineMismatch."""
    harness_session = "harness-md-ac4"
    agent_id = "agent-dev-md-ac4"
    task_id = "20260101-000104"
    md_path = "docs/dev/ticket-20260101-000104.md"
    anchor = f"Request ID: {task_id}"
    project, home = _standard_setup(tmp_path, "dev", agent_id)
    _write_obligation_transcript(
        home,
        project,
        harness_session,
        agent_id,
        _obligation_block_multi(
            task_id,
            [
                {
                    "kind": "markdown",
                    "path": md_path,
                    "identity_anchor": anchor,
                    "terminal_line_regex": "^STATUS: ready$",
                },
            ],
        ),
    )
    _write(project / md_path, f"# Ticket\n{anchor}\nNOT-THE-RIGHT-LAST-LINE\n")
    proc = _run_hook(
        project, home, agent_id, session_id=harness_session, stopgate_mode="block"
    )
    assert proc.returncode == 2, proc.stderr
    assert md_path in proc.stderr
    assert "terminal_line_regex" in proc.stderr
    assert "identity_anchor" not in proc.stderr


def test_markdown_ac5_advisory_mode_never_blocks(tmp_path):
    """This ticket's AC5: the AC3 setup (identity_anchor missing) under
    advisory mode (default/unset): the obligation resolves, yet the stop
    exits 0 with no block message and nothing written."""
    harness_session = "harness-md-ac5"
    agent_id = "agent-dev-md-ac5"
    task_id = "20260101-000105"
    md_path = "docs/dev/ticket-20260101-000105.md"
    anchor = f"Request ID: {task_id}"
    project, home = _standard_setup(tmp_path, "dev", agent_id)
    _write_obligation_transcript(
        home,
        project,
        harness_session,
        agent_id,
        _obligation_block_multi(
            task_id,
            [
                {
                    "kind": "markdown",
                    "path": md_path,
                    "identity_anchor": anchor,
                    "terminal_line_regex": "^STATUS: ready$",
                },
            ],
        ),
    )
    _write(project / md_path, "# Ticket\nNo anchor here.\nSTATUS: ready\n")
    proc = _run_hook(project, home, agent_id, session_id=harness_session)
    assert proc.returncode == 0, proc.stderr
    assert "OBLIGATION_STOPGATE_BLOCKED" not in proc.stderr
    assert _written_logs(home) == []
    assert isinstance(
        _resolution(home, project, harness_session, agent_id, "dev"), HOOK.obligation.Resolved
    )


def test_markdown_ac6_response_block_kind_now_verified_not_advisory_only(tmp_path):
    """SUPERSEDES this test's original r01-authored assertion (kind-filter
    widened to {"json","markdown"} only, response_block left
    advisory-logged as obligation_artifact_kind_unsupported): ticket
    20261001-161041-r21's M2 adds response_block verification to this SAME
    loop, so a response_block entry is no longer advisory-skipped -- it is
    verified against its declared schema exactly like the other three
    kinds (see the dedicated response_block test block below for the
    pass/fail/sentinel/json cases). A schema-valid block passes through
    cleanly under block mode, preserving this test's original "never
    crashing, never falsely blocked" intent -- now achieved via genuine
    verification rather than an unhandled-kind skip."""
    harness_session = "harness-md-ac6"
    agent_id = "agent-dev-md-ac6"
    task_id = "20260101-000106"
    project, home = _standard_setup(tmp_path, "dev", agent_id)
    _write_obligation_transcript(
        home,
        project,
        harness_session,
        agent_id,
        _obligation_block_multi(
            task_id,
            [
                {
                    "kind": "response_block",
                    "begin": "BEGIN",
                    "end": "END",
                    "format": "json",
                    "schema": "changelog-status.v1",
                },
            ],
        ),
    )
    body = json.dumps({"commit_status": "nothing_to_commit"})
    response = f"BEGIN\n{body}\nEND\n"
    proc = _run_hook(
        project, home, agent_id, session_id=harness_session, stopgate_mode="block",
        last_assistant_message=response,
    )
    assert proc.returncode == 0, proc.stderr


# ---------------------------------------------------------------------------
# response_line kind + waived_by_response + consistency:verdict_class
# (ticket 20261001-161041-r12): extends r01's markdown-kind wiring with the
# close-QA ("G5 door") shape -- a response_line channel independent of the
# markdown file channel (AC3), the waived_by_response sentinel escape
# (AC4), and the cross-channel verdict_class consistency check (AC5).
# ---------------------------------------------------------------------------

_CLOSE_REGEX = r"^CLOSE: (YES|NO)([ -].*)?$"


def test_response_line_ac3_independent_of_passing_markdown_channel(tmp_path):
    """AC3: a correct markdown close-report file but a WRONG final response
    line -> exit 2 naming the response_line channel distinctly, while the
    markdown artifact's own path is never reported as a failure (channel
    independence)."""
    harness_session = "harness-rl-ac3"
    agent_id = "agent-qa-rl-ac3"
    task_id = "20260101-000107"
    md_path = "docs/dev/close-report-20260101-000107.md"
    project, home = _standard_setup(tmp_path, "qa", agent_id)
    _write_obligation_transcript(
        home,
        project,
        harness_session,
        agent_id,
        _obligation_block_multi(
            task_id,
            [
                {
                    "kind": "markdown",
                    "path": md_path,
                    "identity_anchor": task_id,
                    "terminal_line_regex": _CLOSE_REGEX,
                },
                {"kind": "response_line", "terminal_line_regex": _CLOSE_REGEX},
            ],
            role="qa",
        ),
    )
    _write(project / md_path, f"# Close Debate Report\n{task_id}\nCLOSE: YES\n")
    proc = _run_hook(
        project, home, agent_id, session_id=harness_session, stopgate_mode="block",
        last_assistant_message="NOT-A-LEGAL-VERDICT-LINE",
    )
    assert proc.returncode == 2, proc.stderr
    assert "<response_line>" in proc.stderr
    assert "terminal_line_mismatch" in proc.stderr
    assert md_path not in proc.stderr


def test_response_line_ac4_waived_by_response_skips_file_check(tmp_path):
    """AC4: the markdown file's last line is wrong (would fail standalone),
    but the response matches the declared waived_by_response sentinel ->
    the file check is SKIPPED (not failed): exit 0 even under block mode,
    decided by the resolved obligation."""
    harness_session = "harness-rl-ac4"
    agent_id = "agent-qa-rl-ac4"
    task_id = "20260101-000108"
    md_path = "docs/dev/close-report-20260101-000108.md"
    project, home = _standard_setup(tmp_path, "qa", agent_id)
    _write_obligation_transcript(
        home,
        project,
        harness_session,
        agent_id,
        _obligation_block_multi(
            task_id,
            [
                {
                    "kind": "markdown",
                    "path": md_path,
                    "identity_anchor": task_id,
                    "terminal_line_regex": _CLOSE_REGEX,
                    "waived_by_response": "^CLOSE_REPORT_APPEND_(ERROR|CRITICAL): ",
                },
            ],
            role="qa",
        ),
    )
    _write(project / md_path, f"# Close Debate Report\n{task_id}\nSTALE-UNRELATED-LINE\n")
    proc = _run_hook(
        project, home, agent_id, session_id=harness_session, stopgate_mode="block",
        last_assistant_message="CLOSE_REPORT_APPEND_ERROR: append: disk full",
    )
    assert proc.returncode == 0, proc.stderr
    assert isinstance(
        _resolution(home, project, harness_session, agent_id, "qa"), HOOK.obligation.Resolved
    )


def test_response_line_ac5_verdict_class_inconsistency_blocks(tmp_path):
    """AC5: the markdown file classifies 'no' while the response classifies
    'yes' under a declared consistency:"verdict_class" obligation -> a
    dedicated verdict_class_inconsistent failure, distinct from either
    channel's own terminal_line_mismatch, exit 2 under block mode."""
    harness_session = "harness-rl-ac5"
    agent_id = "agent-qa-rl-ac5"
    task_id = "20260101-000109"
    md_path = "docs/dev/close-report-20260101-000109.md"
    project, home = _standard_setup(tmp_path, "qa", agent_id)
    _write_obligation_transcript(
        home,
        project,
        harness_session,
        agent_id,
        _obligation_block_multi(
            task_id,
            [
                {
                    "kind": "markdown",
                    "path": md_path,
                    "identity_anchor": task_id,
                    "terminal_line_regex": _CLOSE_REGEX,
                },
                {"kind": "response_line", "terminal_line_regex": _CLOSE_REGEX},
            ],
            role="qa",
            consistency="verdict_class",
        ),
    )
    _write(project / md_path, f"# Close Debate Report\n{task_id}\nCLOSE: NO - unresolved dissent\n")
    proc = _run_hook(
        project, home, agent_id, session_id=harness_session, stopgate_mode="block",
        last_assistant_message="CLOSE: YES",
    )
    assert proc.returncode == 2, proc.stderr
    assert "verdict_class_inconsistent" in proc.stderr
    assert "terminal_line_mismatch" not in proc.stderr


# ---------------------------------------------------------------------------
# response_block kind (ticket 20261001-161041-r21, M2): changelog-analyst's
# own BEGIN/END-delimited JSON status block (commands/commit.md:463-480),
# validated against changelog-status.v1 via the SubagentStop payload's own
# last_assistant_message -- the SAME field response_line already keys off,
# no transcript scan, no second jsonschema call path.
# ---------------------------------------------------------------------------

_CA_BEGIN = "--- CHANGELOG-ANALYST-STATUS-BEGIN ---"
_CA_END = "--- CHANGELOG-ANALYST-STATUS-END ---"


def _response_block_obligation(task_id: str) -> str:
    return _obligation_block_multi(
        task_id,
        [
            {
                "kind": "response_block",
                "begin": _CA_BEGIN,
                "end": _CA_END,
                "format": "json",
                "schema": "changelog-status.v1",
            },
        ],
        role="changelog-analyst",
    )


def test_response_block_well_formed_bypasses_legacy_path(tmp_path):
    """AC4: a schema-valid response_block (changelog-status.v1) -> exit 0
    via the all-pass short-circuit."""
    harness_session = "harness-rb-ac4"
    agent_id = "agent-ca-rb-ac4"
    task_id = "20260101-000201"
    project, home = _standard_setup(tmp_path, "changelog-analyst", agent_id)
    _write_obligation_transcript(
        home, project, harness_session, agent_id, _response_block_obligation(task_id)
    )
    body = json.dumps({"commit_status": "nothing_to_commit"})
    response = f"some narration\n{_CA_BEGIN}\n{body}\n{_CA_END}\nmore narration\n"
    proc = _run_hook(
        project, home, agent_id, session_id=harness_session, stopgate_mode="block",
        last_assistant_message=response,
    )
    assert proc.returncode == 0, proc.stderr


def test_response_block_schema_violation_blocks(tmp_path):
    """AC3: a response_block whose JSON violates changelog-status.v1
    (commit_status not in its declared enum) -> exit 2 naming the
    response_block artifact and the schema violation, distinct from a
    missing-sentinel or unparseable-JSON failure."""
    harness_session = "harness-rb-ac3"
    agent_id = "agent-ca-rb-ac3"
    task_id = "20260101-000202"
    project, home = _standard_setup(tmp_path, "changelog-analyst", agent_id)
    _write_obligation_transcript(
        home, project, harness_session, agent_id, _response_block_obligation(task_id)
    )
    body = json.dumps({"commit_status": "not-a-real-status"})
    response = f"{_CA_BEGIN}\n{body}\n{_CA_END}\n"
    proc = _run_hook(
        project, home, agent_id, session_id=harness_session, stopgate_mode="block",
        last_assistant_message=response,
    )
    assert proc.returncode == 2, proc.stderr
    assert "<response_block>" in proc.stderr
    assert "schema-invalid" in proc.stderr


def test_response_block_missing_sentinel_blocks(tmp_path):
    """AC3: the response text carries neither BEGIN nor END sentinel ->
    exit 2 with a reason distinguishing 'sentinel_missing' from a schema
    violation or unparseable JSON."""
    harness_session = "harness-rb-sentinel"
    agent_id = "agent-ca-rb-sentinel"
    task_id = "20260101-000203"
    project, home = _standard_setup(tmp_path, "changelog-analyst", agent_id)
    _write_obligation_transcript(
        home, project, harness_session, agent_id, _response_block_obligation(task_id)
    )
    proc = _run_hook(
        project, home, agent_id, session_id=harness_session, stopgate_mode="block",
        last_assistant_message="no sentinels anywhere in this response",
    )
    assert proc.returncode == 2, proc.stderr
    assert "<response_block>" in proc.stderr
    assert "sentinel_missing" in proc.stderr


def test_response_block_unparseable_json_blocks(tmp_path):
    """AC3: the sentinel-delimited substring is present but not valid JSON
    -> exit 2 with 'unparseable_json', distinct from sentinel_missing and
    schema-invalid."""
    harness_session = "harness-rb-badjson"
    agent_id = "agent-ca-rb-badjson"
    task_id = "20260101-000204"
    project, home = _standard_setup(tmp_path, "changelog-analyst", agent_id)
    _write_obligation_transcript(
        home, project, harness_session, agent_id, _response_block_obligation(task_id)
    )
    response = _CA_BEGIN + "\n" + "{not valid json at all" + "\n" + _CA_END + "\n"
    proc = _run_hook(
        project, home, agent_id, session_id=harness_session, stopgate_mode="block",
        last_assistant_message=response,
    )
    assert proc.returncode == 2, proc.stderr
    assert "<response_block>" in proc.stderr
    assert "unparseable_json" in proc.stderr


def test_response_block_advisory_mode_never_blocks(tmp_path):
    """Parity with every other obligation kind: advisory mode never exits
    non-zero and writes nothing."""
    harness_session = "harness-rb-advisory"
    agent_id = "agent-ca-rb-advisory"
    task_id = "20260101-000205"
    project, home = _standard_setup(tmp_path, "changelog-analyst", agent_id)
    _write_obligation_transcript(
        home, project, harness_session, agent_id, _response_block_obligation(task_id)
    )
    proc = _run_hook(
        project, home, agent_id, session_id=harness_session, stopgate_mode="advisory",
        last_assistant_message="no sentinels anywhere",
    )
    assert proc.returncode == 0, proc.stderr
    assert _written_logs(home) == []


def test_dev_report_obligation_blocks_even_when_agent_index_entry_missing(
    monkeypatch, tmp_path, capsys
):
    """Lane r04 (dev-report.v2 parity with r02's context.json finding): an
    UNREGISTERED dev agent_id (agent-index.json carries no entry -- the
    orchestrator-injected FIRST ACTION registry Read was skipped) must still
    reach and execute the obligation-mode block for its own
    dev-report-<task_id>.json / dev-report.v2 obligation, blocking exactly
    like the already-covered REGISTERED case (test_ac2_...). The spy wraps
    the REAL resolve_own_obligation (not a stub) so the assertion proves the
    call actually happened, not merely that the final exit code matches --
    an exit-code-only assertion could pass for the wrong reason (same
    pattern as test_ac5_off_switch_never_calls_resolve_own_obligation)."""
    harness_session = "harness-r04-unregistered"
    agent_id = "agent-dev-r04-unregistered"
    task_id = "20260101-000900"
    artifact_path = f"docs/dev/dev-report-{task_id}.json"

    project = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    # Deliberately NOT calling _register_agent: agent-index.json has no key
    # for agent_id, reproducing a skipped FIRST ACTION registry Read.
    _enable_flag(project, SESSION)
    _write_sentinel(project, SESSION, "dev")
    _write_obligation_transcript(
        home,
        project,
        harness_session,
        agent_id,
        _obligation_block(task_id, artifact_path, "dev-report.v2"),
    )
    # artifact_path is deliberately never written -- validate_artifact_for_
    # obligation treats a missing obligation-named artifact as 'fail'
    # (hooks/lib/contract_runtime.py), which is sufficient to prove the
    # obligation-mode block actually ran and reached a verdict.

    assert HOOK.resolve_dev_registry_entry(agent_id, str(project)) is None, (
        "premise: agent_id must have no agent-index.json entry"
    )

    real_resolve = HOOK.obligation.resolve_own_obligation
    calls = []

    def _spy(*args, **kwargs):
        calls.append((args, kwargs))
        return real_resolve(*args, **kwargs)

    monkeypatch.setattr(HOOK.obligation, "resolve_own_obligation", _spy)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude"))
    monkeypatch.setenv("CLAUDE_OBLIGATION_STOPGATE", "block")
    monkeypatch.setattr(
        HOOK,
        "_load_stdin",
        lambda: {"agent_id": agent_id, "session_id": harness_session},
    )

    with pytest.raises(SystemExit) as exc_info:
        HOOK.main()

    assert len(calls) == 1, (
        "resolve_own_obligation must be invoked even when agent-index.json "
        "has no entry for agent_id -- the obligation-mode block must not be "
        "short-circuited by the registry-entry guard"
    )
    assert exc_info.value.code == 2
    assert f"  - {artifact_path}:" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Lane 20261001-161041-r02: BA/context.v1 coverage for the entry-is-None +
# resolvable-obligation gap (Measured 7: no pre-existing test combined these
# two conditions). The structural reorder itself (moving the entry-is-None /
# dev_session_id guards past the obligation-mode block) landed via a sibling
# lane before this lane's edit -- confirmed by reading the live file: the
# CLAUDE_OBLIGATION_STOPGATE resolution now precedes `if entry is None:`.
# This lane adds only the role="ba" test coverage M4 calls for, per the
# ticket's own Shared-File Risk recommendation (verify, don't duplicate).
# ---------------------------------------------------------------------------


def test_ba_context_obligation_missing_artifact_blocks_when_entry_unresolved(
    tmp_path,
):
    """An agent_id absent from agent-index.json (skipped FIRST ACTION
    registry Read) with a resolvable obligation naming a role="ba"
    context.v1 json artifact that was never written must still exit 2 in
    block mode -- the obligation-mode ladder (L0/L1) must be reachable for
    BA's context.json specifically, not just for dev/qa report kinds."""
    harness_session = "harness-r02-missing"
    agent_id = "agent-ba-r02-missing"
    task_id = "20260101-000921"
    artifact_path = f"docs/dev/context-{task_id}.json"
    project = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    # Deliberately NOT calling _register_agent: reproduces a skipped FIRST
    # ACTION registry Read, so resolve_dev_registry_entry() returns None.
    _write_obligation_transcript(
        home,
        project,
        harness_session,
        agent_id,
        _obligation_block(task_id, artifact_path, "context.v1", role="ba"),
    )
    assert HOOK.resolve_dev_registry_entry(agent_id, str(project)) is None, (
        "premise: agent_id must have no agent-index.json entry"
    )
    proc = _run_hook(
        project, home, agent_id, session_id=harness_session, stopgate_mode="block"
    )
    assert proc.returncode == 2, proc.stderr
    assert artifact_path in proc.stderr


def test_ba_context_obligation_valid_artifact_allows_when_entry_unresolved(
    tmp_path,
):
    """Same unregistered-agent setup as above, but the role="ba" context.v1
    artifact exists and validates -- exit 0 via the obligation-mode bypass,
    proving the ladder actually ran (not merely that an unresolved agent's
    legacy path trivially allows)."""
    harness_session = "harness-r02-valid"
    agent_id = "agent-ba-r02-valid"
    task_id = "20260101-000922"
    artifact_path = f"docs/dev/context-{task_id}.json"
    project = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    _write_obligation_transcript(
        home,
        project,
        harness_session,
        agent_id,
        _obligation_block(task_id, artifact_path, "context.v1", role="ba"),
    )
    _write(
        project / artifact_path,
        {
            "task_id": task_id,
            "requirement": "x",
            "root_cause_analysis": {"affected_files": ["x.py"]},
            "development_approach": {"strategy": "x"},
            "complexity_tier": "SMALL",
            "risk_level": "low",
            "test_writer_expected": False,
        },
    )
    proc = _run_hook(
        project, home, agent_id, session_id=harness_session, stopgate_mode="block"
    )
    assert proc.returncode == 0, proc.stderr


def test_no_obligation_in_transcript_allows_when_entry_unresolved(tmp_path):
    """LOW-10 narrowed, not deleted: an agent_id absent from agent-index.json
    whose resolvable transcript carries no '<obligation' block at all still
    exits 0 -- the reorder must not turn NoObligationInPrompt into a block."""
    harness_session = "harness-r02-noobl"
    agent_id = "agent-ba-r02-noobl"
    project = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    _write_obligation_transcript(
        home,
        project,
        harness_session,
        agent_id,
        "Implement the thing. No obligation block here.",
    )
    proc = _run_hook(
        project, home, agent_id, session_id=harness_session, stopgate_mode="block"
    )
    assert proc.returncode == 0, proc.stderr


# ---------------------------------------------------------------------------
# Lane 20261001-161041-r06: QA/qa-report.v2 coverage for the entry-is-None +
# resolvable-obligation gap, AC1/AC6. The structural reorder itself (moving
# the entry-is-None / dev_session_id guards past the obligation-mode block)
# had already landed via a sibling lane (r02 and/or r04) by the time this
# lane's dev re-read the live file -- confirmed the same way r02's own tests
# above confirm it: CLAUDE_OBLIGATION_STOPGATE resolution now precedes
# `if entry is None:`. Per this lane's own ticket's Shared-File Coordination
# protocol (and r02's/r04's identical protocol), this lane contributes ONLY
# the qa-role regression test the reorder's AC1 calls for -- no second,
# independent reorder is applied here.
# ---------------------------------------------------------------------------


def _valid_qa_report_v2(task_id: str, e2e_status: str = "performed") -> dict:
    return {
        "report_version": 2,
        "request_id": task_id,
        "task_id": task_id,
        "timestamp": "2026-10-01T00:00:00Z",
        "qa": {"status": "pass", "e2e_enforcement": {"status": e2e_status}},
    }


def test_qa_report_v2_obligation_missing_artifact_blocks_when_entry_unresolved(
    tmp_path,
):
    """AC1 (qa leg): an agent_id absent from agent-index.json (skipped FIRST
    ACTION registry Read) with a resolvable obligation naming a role="qa"
    qa-report.v2 json artifact that was never written must still exit 2 in
    block mode -- the obligation-mode ladder (L0/L1) is reachable for QA's
    own report, with no QA-specific carve-out required beyond the generic
    reorder r02/r04 already landed."""
    harness_session = "harness-r06-ac1-missing"
    agent_id = "agent-qa-r06-ac1-missing"
    task_id = "20260101-000931"
    artifact_path = f"docs/dev/qa-report-{task_id}.json"
    project = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    # Deliberately NOT calling _register_agent: reproduces a skipped FIRST
    # ACTION registry Read, so resolve_dev_registry_entry() returns None.
    _write_obligation_transcript(
        home,
        project,
        harness_session,
        agent_id,
        _obligation_block(task_id, artifact_path, "qa-report.v2", role="qa"),
    )
    assert HOOK.resolve_dev_registry_entry(agent_id, str(project)) is None, (
        "premise: agent_id must have no agent-index.json entry"
    )
    proc = _run_hook(
        project, home, agent_id, session_id=harness_session, stopgate_mode="block"
    )
    assert proc.returncode == 2, proc.stderr
    assert artifact_path in proc.stderr


def test_qa_report_v2_obligation_valid_artifact_allows_when_entry_unresolved(
    tmp_path,
):
    """Same unregistered-agent setup as above, but the role="qa"
    qa-report.v2 artifact exists and validates -- exit 0 via the
    obligation-mode bypass, proving the ladder actually ran for QA's own
    report (not merely that an unresolved agent's legacy path trivially
    allows)."""
    harness_session = "harness-r06-ac1-valid"
    agent_id = "agent-qa-r06-ac1-valid"
    task_id = "20260101-000932"
    artifact_path = f"docs/dev/qa-report-{task_id}.json"
    project = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    _write_obligation_transcript(
        home,
        project,
        harness_session,
        agent_id,
        _obligation_block(task_id, artifact_path, "qa-report.v2", role="qa"),
    )
    _write(project / artifact_path, _valid_qa_report_v2(task_id))
    proc = _run_hook(
        project, home, agent_id, session_id=harness_session, stopgate_mode="block"
    )
    assert proc.returncode == 0, proc.stderr


# ---------------------------------------------------------------------------
# Lane L2 (dev-command-20261002-170011-l2): producer stop gate -- terminal
# state and the dev report's downstream wires. A failing stop is a plain exit
# 2 naming each failing artifact and check, in every round (corrections 2.27,
# P1b row 3): no hand-off nonce, no admission, no record store.
# Every scenario is a function taking the pytest fixtures it needs, so the
# generated per-AC tests under tests/generated/ can call the SAME scenario.
# Fixtures are built under tmp_path only; the gate runs as a subprocess with
# HOME / project redirected, so no real registry or session state is touched.
# ---------------------------------------------------------------------------

import re as _re
import shutil as _shutil

L2_TASK = "dev-command-20261002-170011"
_NONCE_RE = _re.compile(r"ESCALATION_ACK ([0-9a-f]{32})")
# The record stores the escalation path wrote; the gate writes none of them.
_RECORD_STORES = ("escalations", "escalation-admissions", "progress", "deferred-checks")


def _git_init_project(project: Path) -> None:
    project.mkdir(parents=True, exist_ok=True)
    for args in (
        ["init", "-q", "-b", "main"],
        ["config", "user.email", "t@example.invalid"],
        ["config", "user.name", "t"],
    ):
        subprocess.run(["git", "-C", str(project), *args], check=True, capture_output=True)
    (project / "src.txt").write_text("alpha\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", "src.txt"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(project), "commit", "-q", "-m", "seed"],
                   check=True, capture_output=True)
    (project / "src.txt").write_text("beta\n", encoding="utf-8")


def _l2_dev_report(task_id, status="completed", ledger_old="alpha", lane=None, lane_set=None,
                   note="x"):
    rep = {
        "report_version": 2, "request_id": task_id, "task_id": task_id,
        "timestamp": "2026-10-02T00:00:00Z", "baseline_head_sha": "",
        "baseline_dirty_snapshot": "",
        "owned_edits": {"src.txt": [{"old": ledger_old, "new": "beta"}]},
        "pre_edit_snapshots": {"src.txt": "alpha\n"},
        "dev": {"status": status, "files_modified": ["src.txt"], "files_created": [],
                "note": note},
    }
    if status == "needs_review":
        rep["dev"]["status_rationale"] = {
            "classification": "other_disclosed_handoff", "blocked_by": note,
            "forbidden_action": "commit"}
    if lane:
        rep["lane"] = lane
        rep["lane_set"] = lane_set
    return rep


def _l2_unattributed_report(s, note="x", lane=None, lane_set=None):
    """A schema-valid dev report naming another task: an identity_mismatch
    finding. The failing report of the escalation scenarios below, which
    used a needs_review report while required_values existed; P1 (D2)
    removed required_values, so a wrong dev.status is now a schema failure
    (test_l2_ac1), whose reason is a sentence rather than a finding code."""
    rep = _l2_dev_report(s.task, note=note, lane=lane, lane_set=lane_set)
    rep["task_id"] = rep["request_id"] = "20991231-235959"
    return rep


def _l2_setup(tmp_path, *, role="dev", lane=None, lane_set=None, base_task=L2_TASK,
              git=True, agent_id="agent-l2-producer", home_name="home",
              project_name="project"):
    s = type("S", (), {})()
    s.project = tmp_path / project_name
    s.home = tmp_path / home_name
    s.home.mkdir(parents=True, exist_ok=True)
    if git:
        _git_init_project(s.project)
    else:
        s.project.mkdir(parents=True, exist_ok=True)
    s.agent_id = agent_id
    s.harness = "harness-l2"
    s.role = role
    s.cycle = base_task
    s.task = f"{base_task}-{lane}" if lane else base_task
    s.art_path = f"docs/dev/{role}-report-{s.task}.json"
    art = {"kind": "json", "path": s.art_path,
           "schema": "dev-report.v2" if role == "dev" else "qa-report.v2",
           "identity": {"task_id": s.task}}
    # P1 (D2): a json artifact carries no required_values; the dev terminal
    # is the schema's own dev.status enum ({"completed"}).
    doc = {"task_id": s.task, "role": role, "pipeline": "dev",
           "profile": "fanout-lane" if lane else "singular",
           "dispatched_at": datetime.now(timezone.utc).isoformat(), "artifacts": [art]}
    if lane:
        doc["lane"] = lane
        doc["lane_set"] = lane_set or [lane]
    s.obligation = doc
    _register_agent(s.project, agent_id, SESSION, role)
    _write_obligation_transcript(
        s.home, s.project, s.harness, agent_id,
        f'<obligation v="1">\n{json.dumps(doc, indent=2)}\n</obligation>')
    return s


def _l2_write(s, report) -> None:
    _write(s.project / s.art_path, report)


def _l2_stop(s, msg=None, extra_env=None, hook_path=None, extra_payload=None):
    return _run_hook(s.project, s.home, s.agent_id, session_id=s.harness,
                     stopgate_mode="block", last_assistant_message=msg,
                     extra_env=extra_env, hook_path=hook_path, extra_payload=extra_payload)


def _l2_stores(s) -> list:
    """Every record-store directory under the project's dev registry."""
    registry = s.project / ".claude" / "dev-registry"
    if not registry.is_dir():
        return []
    return sorted(str(p.relative_to(registry)) for p in registry.rglob("*")
                  if p.is_dir() and p.name in _RECORD_STORES)


def _l2_hook_tree(tmp_path, script_overrides=None):
    """Copy of the hook with its lib/, symlinked schemas/, agents/ and
    commands/ (the roster and the command files an obligation's role and
    pipeline are checked against) and a scripts/ tree whose named entries are
    replaced by test stubs (HOOK scripts dir is derived from the hook's own
    location)."""
    root = tmp_path / "hooktree"
    (root / "hooks").mkdir(parents=True)
    _shutil.copy(HOOK_PATH, root / "hooks" / HOOK_PATH.name)
    _shutil.copytree(REPO_ROOT / "hooks" / "lib", root / "hooks" / "lib",
                     ignore=_shutil.ignore_patterns("__pycache__"))
    for name in ("schemas", "agents", "commands"):
        os.symlink(REPO_ROOT / name, root / name)
    scripts = root / "scripts"
    scripts.mkdir()
    overrides = script_overrides or {}
    for entry in (REPO_ROOT / "scripts").iterdir():
        if entry.name not in overrides:
            os.symlink(entry, scripts / entry.name)
    for name, text in overrides.items():
        (scripts / name).write_text(text, encoding="utf-8")
    return root / "hooks" / HOOK_PATH.name


def _l2_snapshot(project: Path) -> tuple:
    def git(*a):
        return subprocess.run(["git", "-C", str(project), *a], capture_output=True,
                              text=True, check=True).stdout
    return (git("status", "--porcelain"), git("ls-files", "-s"),
            (project / "src.txt").read_bytes())


# AC1 / AC2 -----------------------------------------------------------------


def test_l2_ac1_terminal_state_wrong_blocks(tmp_path):
    """P1 (D2): no required_values check any more; dev-report.v2's own
    dev.status enum is {"completed"}, so a needs_review report fails the
    schema."""
    s = _l2_setup(tmp_path)
    _l2_write(s, _l2_dev_report(s.task, status="needs_review"))
    proc = _l2_stop(s)
    assert proc.returncode == 2, proc.stderr
    assert s.art_path in proc.stderr
    assert "schema-invalid" in proc.stderr
    assert "terminal_value_violation" not in proc.stderr
    assert "needs_review" in proc.stderr and "completed" in proc.stderr


def test_l2_ac2_terminal_state_right_passes(tmp_path):
    s = _l2_setup(tmp_path)
    _l2_write(s, _l2_dev_report(s.task))
    proc = _l2_stop(s)
    assert proc.returncode == 0, proc.stderr
    assert _l2_stores(s) == []


# AC3 -----------------------------------------------------------------------


def test_l2_ac3_ledger_without_journal_evidence_passes_wrong_or_right(tmp_path):
    """Attribution-journal consumer cutover (docs/reference/attribution-
    journal-cutover-flip-plan-20261003.md, superseded by the zero-blocking
    constraint of the follow-up consumer-cutover task): this hook no longer
    calls check-owned-edits-ledger.py at all (see _wire_ledger_judgment).
    A malformed self-reported ledger (empty `old` needle) no longer blocks
    the producer's stop -- it has no write-time journal evidence either (a
    plain-filesystem test write), so src.txt is deferred, not rejected.

    The sibling scenario this test used to carry -- a stubbed
    check-owned-edits-ledger.py forced to exit 2 -- is removed rather than
    adapted: that script is no longer on this hook's blocking path, so
    stubbing it exercises nothing. A checker that will not load or crashes
    judges nothing, for this wire as for the trial plan (see AC8).
    """
    s = _l2_setup(tmp_path)
    _l2_write(s, _l2_dev_report(s.task, ledger_old=""))  # empty needle violates the ledger contract
    first = _l2_stop(s)
    assert first.returncode == 0, first.stderr
    _l2_write(s, _l2_dev_report(s.task))
    second = _l2_stop(s)
    assert second.returncode == 0, second.stderr


# AC4 -----------------------------------------------------------------------


def test_l2_ac4_unplannable_blocks_plannable_passes(tmp_path):
    """Attribution-journal consumer cutover (see test_l2_ac3's docstring for
    the full citation): build_plan()'s ownership gate no longer raises on
    self-report absence alone (scripts/resolve-commit-repos.py
    _ledger_entangled()) -- "ghost.txt" is a plain-filesystem test write with
    no journal evidence, so it is now plannable too, not unplannable."""
    s = _l2_setup(tmp_path)
    rep = _l2_dev_report(s.task)
    rep["dev"]["files_modified"] = ["src.txt", "ghost.txt"]
    _l2_write(s, rep)
    # The comparator: the module itself now succeeds for this report.
    mod = HOOK._load_script_module("resolve-commit-repos.py")
    plan = mod.build_plan(task_id=s.task, control_root_arg=str(s.project), supported_repo_args=[],
                          report_arg=str(s.project / s.art_path))
    assert "ghost.txt" in plan["repositories"][0]["owned_paths"]
    proc = _l2_stop(s)
    assert proc.returncode == 0, proc.stderr


# AC5 -----------------------------------------------------------------------


def test_l2_ac5_stager_replay_exclude_blocks_include_passes_index_untouched(tmp_path):
    """Attribution-journal consumer cutover (see test_l2_ac3's docstring for
    the full citation): this hook no longer calls stage-owned-hunks.py
    --dry-run at all (see _wire_ledger_judgment, which replaces it). The
    owned region no longer matching the ledger's declared snapshot no
    longer blocks on its own -- src.txt is a plain-filesystem test write
    with no journal evidence, so it is deferred, not excluded."""
    s = _l2_setup(tmp_path)
    _l2_write(s, _l2_dev_report(s.task))
    before = _l2_snapshot(s.project)
    ok = _l2_stop(s)
    assert ok.returncode == 0, ok.stderr
    assert _l2_snapshot(s.project) == before
    (s.project / "src.txt").write_text("gamma\n", encoding="utf-8")
    before = _l2_snapshot(s.project)
    now_ok = _l2_stop(s)
    assert now_ok.returncode == 0, now_ok.stderr
    assert _l2_snapshot(s.project) == before


# AC6 -----------------------------------------------------------------------

_CHAIN_STUB = (
    "import json, os, sys\n"
    "open(os.environ['L2_STUB_CHAIN'] + '.ran', 'w').close()\n"
    "doc = json.load(open(os.environ['L2_STUB_CHAIN']))\n"
    "print(json.dumps(doc))\n"
    "sys.exit(0 if doc.get('status') in ('pass', 'pass_with_exceptions') else 2)\n"
)


def _l2_qa(tmp_path, name, chain):
    s = _l2_setup(tmp_path / name, role="qa")
    _write(s.project / s.art_path, _valid_qa_report_v2(s.task))
    chain_file = tmp_path / name / "chain.json"
    _write(chain_file, chain)
    hook = _l2_hook_tree(tmp_path / name, {"resolve-dev-artifact-chain.py": _CHAIN_STUB})
    return s, hook, {"L2_STUB_CHAIN": str(chain_file)}


def test_l2_ac6_qa_stop_judges_only_qa_own_artifacts(tmp_path):
    """P1b row 7: QA's stop runs no artifact chain resolver. Other producers'
    artifacts are G3's, at the next dispatch; QA's own report is judged on
    its declared shape, schema and identity. A resolver that would reject
    QA's report and an upstream report alike is never run, and nothing is
    recorded."""
    s, hook, env = _l2_qa(tmp_path, "chain", {"status": "fail", "errors": [
        {"code": "QA_BAD", "path": f"docs/dev/qa-report-{L2_TASK}.json", "detail": "x"},
        {"code": "DEV_GAP", "path": f"docs/dev/dev-report-{L2_TASK}.json", "detail": "missing"}]})
    proc = _l2_stop(s, hook_path=hook, extra_env=env)
    assert proc.returncode == 0, proc.stderr
    assert not Path(env["L2_STUB_CHAIN"] + ".ran").exists()
    assert _l2_stores(s) == []


# AC7 / AC10 ----------------------------------------------------------------


def test_l2_ac7_every_failing_round_is_a_plain_block(tmp_path):
    """Corrections 2.27 / P1c row 7: a failing stop is a plain exit 2 naming
    the failing artifact and its check, in every round -- bytes changing or
    not -- with no hand-off nonce; no ESCALATION_ACK line admits it and
    nothing is recorded. The repair alone passes."""
    s = _l2_setup(tmp_path)
    for i in range(3):
        _l2_write(s, _l2_unattributed_report(s, note=f"attempt-{i}"))
        assert _l2_stop(s).returncode == 2
    for msg in (None, "ESCALATION_ACK " + "0" * 32, "could not repair.\n  ESCALATION_ACK " + "a" * 32):
        proc = _l2_stop(s, msg=msg)
        assert proc.returncode == 2, proc.stderr
        assert s.art_path in proc.stderr and "identity_mismatch" in proc.stderr
        assert "ESCALATION" not in proc.stderr and not _NONCE_RE.search(proc.stderr)
    assert _l2_stores(s) == []
    _l2_write(s, _l2_dev_report(s.task))
    proc = _l2_stop(s)
    assert proc.returncode == 0, proc.stderr


def test_l2_ac10_rejected_repair_is_no_progress_not_an_escape(tmp_path):
    s = _l2_setup(tmp_path)
    _l2_write(s, _l2_dev_report(s.task, status="needs_review"))
    assert _l2_stop(s).returncode == 2           # round 1
    # Repair attempt rejected by a hook: bytes unchanged -> the same plain block.
    second = _l2_stop(s)
    assert second.returncode == 2 and not _NONCE_RE.search(second.stderr)
    # Reverting to previously seen bytes after a change is no release either.
    _l2_write(s, _l2_dev_report(s.task, status="needs_review", note="other"))
    assert _l2_stop(s).returncode == 2
    _l2_write(s, _l2_dev_report(s.task, status="needs_review"))
    assert _l2_stop(s).returncode == 2
    # No pause text of any kind admits the stop.
    paused = _l2_stop(s, msg="PAUSED: hook rejected my repair; releasing myself\nPAUSE_RELEASE")
    assert paused.returncode == 2
    assert _l2_stores(s) == []


# AC8 -----------------------------------------------------------------------

_RAISING_PLAN_STUB = (
    "class PlanError(RuntimeError):\n"
    "    code = None\n"
    "def build_plan(**kwargs):\n"
    "    raise RuntimeError('unexpected checker crash')\n"
)


def test_l2_ac8_crashed_checker_judges_nothing_and_no_threshold_releases(tmp_path):
    """A wire that crashes (here /commit's planner raising instead of
    returning a PlanError) judges nothing: its fault is not the producer's
    artifact, no repair of the producer's could clear it, and blocking on it
    would leave the producer no route (D25). A failing report, though, is
    never released by repetition."""
    s = _l2_setup(tmp_path)
    _l2_write(s, _l2_dev_report(s.task))
    hook = _l2_hook_tree(tmp_path, {"resolve-commit-repos.py": _RAISING_PLAN_STUB})
    proc = _l2_stop(s, hook_path=hook)
    assert proc.returncode == 0, proc.stderr
    assert _l2_stores(s) == []

    # No counter-threshold release: identical bytes, never an ack line.
    s2 = _l2_setup(tmp_path / "loop")
    _l2_write(s2, _l2_dev_report(s2.task, status="needs_review"))
    assert all(_l2_stop(s2).returncode == 2 for _ in range(6))


# AC12 ----------------------------------------------------------------------


_REJECTING_PLAN_STUB = (
    "class PlanError(RuntimeError):\n"
    "    code = 'stub_rejects'\n"
    "def build_plan(**kwargs):\n"
    "    raise PlanError('the planner rejects every report')\n"
)


def test_l2_ac12_shard_skips_the_trial_plan_without_a_record(tmp_path):
    """A lane's report alone is not the cycle /commit plans: a fan-out lane's
    stop runs no trial plan (a planner that rejects every report passes it)
    and records no deferral; a singular report is planned and blocked by
    the same planner. The ledger judgment runs for both: src.txt is a
    plain-filesystem test write with no journal evidence, so it finds
    nothing. Without the former progress helper in the hook tree, a failing
    report still gets the plain block."""
    def peer_dirty(s, lane=None, lane_set=None):
        _l2_write(s, _l2_dev_report(s.task, lane=lane, lane_set=lane_set))
        (s.project / "src.txt").write_text("gamma\n", encoding="utf-8")

    shard = _l2_setup(tmp_path / "shard", lane="l2", lane_set=["l1", "l2"])
    peer_dirty(shard, "l2", ["l1", "l2"])
    hook = _l2_hook_tree(tmp_path / "shard", {"resolve-commit-repos.py": _REJECTING_PLAN_STUB})
    proc = _l2_stop(shard, hook_path=hook)
    assert proc.returncode == 0, proc.stderr
    assert _l2_stores(shard) == []

    single = _l2_setup(tmp_path / "single")
    peer_dirty(single)
    assert _l2_stop(single).returncode == 0
    hook = _l2_hook_tree(tmp_path / "single", {"resolve-commit-repos.py": _REJECTING_PLAN_STUB})
    proc = _l2_stop(single, hook_path=hook)
    assert proc.returncode == 2, proc.stderr
    assert single.art_path in proc.stderr and "repository_plan_error" in proc.stderr
    assert _l2_stores(single) == []


# ---------------------------------------------------------------------------
# Phase P1 G2 with CLAUDE_OBLIGATION_STOPGATE=block (acceptance test 5): no
# required_values (D2), so honest fail verdicts pass on shape, schema and
# identity alone and dev has the one terminal "completed"; the producer
# question artifact docs/dev/producer-question-<task_id>-<role>.json of a ba
# or dev obligation (TC-33); no reply text skips a check; close-QA's
# markdown waiver is read from the reply's final non-empty line.
# ---------------------------------------------------------------------------

G2_TASK = "20261018-120000"


def _g2_dev_report_v1(task_id: str, status: str = "completed") -> dict:
    """A dev-report.v1 that passes the projection pre-pass: the flat fields
    together with the nested dev sources they project."""
    return {
        "report_version": 1,
        "task_id": task_id,
        "status": status,
        "files_modified": [],
        "files_created": [],
        "root_cause_addressed": "x",
        "ac_status": {},
        "dev": {
            "status": status,
            "files_modified": [],
            "files_created": [],
            "git_rationale": {"how_fix_addresses_root": "x"},
            "ac_status": {},
        },
    }


def _g2_ba_qa_report(task_id: str, verdict: str) -> dict:
    return {
        "task_id": task_id,
        "verdict": verdict,
        "objections": [
            {
                "dimension": "scope_alignment",
                "claim": "the ticket covers the cache only",
                "problem": "the request also names the index",
                "required_evidence": "an AC for the index",
            }
        ],
        "summary": "scope does not match the request",
    }


def _g2_question(task_id: str, role: str, labels=("keep", "replace"), default=None) -> dict:
    """A producer-question.v1 record (schemas/producer-question.v1.json)."""
    return {
        "task_id": task_id,
        "role": role,
        "need": "whether the cache is kept or replaced",
        "options": [{"label": label, "description": f"{label} the cache"} for label in labels],
        "default": labels[0] if default is None else default,
        "why": "the request, the code and a sensible default do not settle it",
    }


def _g2_question_path(task_id: str, role: str) -> str:
    return f"docs/dev/producer-question-{task_id}-{role}.json"


def _g2_json(path: str, schema: str, task_id: str = G2_TASK) -> dict:
    return {"kind": "json", "path": path, "schema": schema, "identity": {"task_id": task_id}}


def _g2_dev_artifacts(schema: str = "dev-report.v1", task_id: str = G2_TASK) -> list:
    return [_g2_json(f"docs/dev/dev-report-{task_id}.json", schema, task_id)]


def _g2_ba_artifacts(task_id: str = G2_TASK) -> list:
    """BA's declared artifacts as commands/dev.md's BA obligation lists them."""
    return [
        _g2_json(f"docs/dev/context-{task_id}.json", "context.v1", task_id),
        {"kind": "markdown", "path": f"docs/dev/ticket-{task_id}.md", "identity_anchor": task_id},
        _g2_json(f"docs/dev/acceptance-criteria-{task_id}.json", "acceptance-criteria.v1", task_id),
    ]


def _g2_setup(tmp_path, role: str, artifacts: list, *, task_id: str = G2_TASK,
              pipeline: str = "dev", profile: str = "singular", consistency=None):
    """A registered producer whose dispatch prompt carries one obligation.
    The legacy correlation path is armed as well (_standard_setup), so a
    stop the obligation branch did not decide is told apart by
    _g2_assert_decided_by_obligation."""
    s = type("G2", (), {})()
    s.agent_id = f"agent-{role}-g2"
    s.harness = f"harness-g2-{role}"
    s.task = task_id
    s.project, s.home = _standard_setup(tmp_path, role, s.agent_id)
    s.dispatched_at = datetime.now(timezone.utc)
    doc = {
        "task_id": task_id,
        "role": role,
        "pipeline": pipeline,
        "profile": profile,
        "dispatched_at": s.dispatched_at.isoformat(),
        "artifacts": artifacts,
    }
    if consistency is not None:
        doc["consistency"] = consistency
    s.obligation = doc
    _write_obligation_transcript(
        s.home, s.project, s.harness, s.agent_id,
        f'<obligation v="1">\n{json.dumps(doc, indent=2)}\n</obligation>',
    )
    return s


def _g2_stop(s, msg=None) -> subprocess.CompletedProcess:
    return _run_hook(s.project, s.home, s.agent_id, session_id=s.harness,
                     stopgate_mode="block", last_assistant_message=msg)


def _g2_assert_decided_by_obligation(s) -> None:
    """The obligation resolves, so the obligation branch made the decision:
    no fallback to the legacy path."""
    resolution = _resolution(s.home, s.project, s.harness, s.agent_id, s.obligation["role"])
    assert isinstance(resolution, HOOK.obligation.Resolved), resolution


def _g2_assert_blocked_on(proc, path: str, reason: str) -> None:
    assert proc.returncode == 2, proc.stderr
    assert "OBLIGATION_STOPGATE_BLOCKED" in proc.stderr
    assert f"  - {path}: {reason}" in proc.stderr, proc.stderr


_G2_MISSING = "obligation-named artifact absent"


# (a) honest fail verdicts pass on shape, schema and identity -------------


def _g2_write_upstream_chain(project: Path, task_id: str = G2_TASK) -> None:
    """The artifacts upstream of QA in a /dev cycle (BA's context and ticket,
    dev's completed report), so the QA chain wire's resolver reaches the
    qa-report itself instead of stopping at a missing dev report."""
    _write(project / f"docs/dev/context-{task_id}.json", {
        "task_id": task_id, "request_id": task_id, "requirement": "x",
        "root_cause_analysis": {},
        "waves": [{"wave_id": 1, "tasks": [{"task_id": task_id, "title": "x"}]}],
    })
    _write(project / f"docs/dev/ticket-{task_id}.md", f"# Ticket\nRequest ID: {task_id}\n")
    _write(project / f"docs/dev/dev-report-{task_id}.json", _l2_dev_report(task_id))


@pytest.mark.parametrize("qa_status", ["pass", "fail"], ids=["qa_pass_control", "qa_fail"])
def test_g2_qa_status_fail_passes_on_shape_schema_and_identity(tmp_path, qa_status):
    """An honest QA fail is a legal terminal (D2): G2 passes the qa-report
    on shape, schema and identity alone. The pass case is the control: the
    same cycle, so the two differ only in qa.status."""
    report = f"docs/dev/qa-report-{G2_TASK}.json"
    s = _g2_setup(tmp_path, "qa", [_g2_json(report, "qa-report.v2")])
    _g2_write_upstream_chain(s.project)
    doc = _valid_qa_report_v2(G2_TASK)
    doc["qa"]["status"] = qa_status
    _write(s.project / report, doc)
    proc = _g2_stop(s)
    assert proc.returncode == 0, proc.stderr
    _g2_assert_decided_by_obligation(s)


def test_g2_ba_qa_verdict_fail_passes(tmp_path):
    report = f"docs/dev/ba-qa-report-{G2_TASK}.json"
    s = _g2_setup(tmp_path, "qa", [_g2_json(report, "ba-qa-report.v1")], profile="ba_validation")
    _write(s.project / report, _g2_ba_qa_report(G2_TASK, "fail"))
    proc = _g2_stop(s)
    assert proc.returncode == 0, proc.stderr
    _g2_assert_decided_by_obligation(s)


# (b) dev has one terminal: blocked fails the enum ------------------------


@pytest.mark.parametrize("schema", ["dev-report.v2", "dev-report.v1"])
def test_g2_dev_status_blocked_fails_the_enum(tmp_path, schema):
    report = f"docs/dev/dev-report-{G2_TASK}.json"
    s = _g2_setup(tmp_path, "dev", _g2_dev_artifacts(schema))
    if schema == "dev-report.v2":
        _write(s.project / report, _l2_dev_report(G2_TASK, status="blocked"))
    else:
        _write(s.project / report, _g2_dev_report_v1(G2_TASK, status="blocked"))
    proc = _g2_stop(s)
    _g2_assert_blocked_on(proc, report, "schema-invalid under obligation-supplied schema")
    assert "'blocked'" in proc.stderr


# (c) a valid, fresh question stands in for every declared artifact -------


@pytest.mark.parametrize("role", ["dev", "ba"])
def test_g2_valid_producer_question_stands_in_for_declared_artifacts(tmp_path, role):
    artifacts = _g2_dev_artifacts("dev-report.v2") if role == "dev" else _g2_ba_artifacts()
    s = _g2_setup(tmp_path, role, artifacts)
    _write(s.project / _g2_question_path(G2_TASK, role), _g2_question(G2_TASK, role))
    proc = _g2_stop(s, msg="One owner decision is needed; see the question artifact.")
    assert proc.returncode == 0, proc.stderr
    _g2_assert_decided_by_obligation(s)
    for art in artifacts:
        assert not (s.project / art["path"]).exists()


# (d) a fresh, invalid question blocks and names why ----------------------


@pytest.mark.parametrize(
    "question, why",
    [
        (_g2_question(G2_TASK, "dev", labels=("keep",)), "is too short"),
        (
            _g2_question(G2_TASK, "dev", default="maybe"),
            "default 'maybe' is not one of the option labels",
        ),
        (
            _g2_question("20261018-120001", "dev"),
            "task_id: obligation declares '20261018-120000', file has '20261018-120001'",
        ),
    ],
    ids=["one_option", "default_not_a_label", "other_task_id"],
)
def test_g2_fresh_invalid_producer_question_blocks_naming_why(tmp_path, question, why):
    report = f"docs/dev/dev-report-{G2_TASK}.json"
    s = _g2_setup(tmp_path, "dev", _g2_dev_artifacts())
    # The declared report is valid, so the question alone blocks the stop.
    _write(s.project / report, _g2_dev_report_v1(G2_TASK))
    question_path = _g2_question_path(G2_TASK, "dev")
    _write(s.project / question_path, question)
    proc = _g2_stop(s)
    _g2_assert_blocked_on(proc, question_path, "producer_question_invalid")
    assert why in proc.stderr, proc.stderr
    assert f"  - {report}:" not in proc.stderr


# (e) a question older than the dispatch is ignored -----------------------


def test_g2_stale_producer_question_is_ignored(tmp_path):
    report = f"docs/dev/dev-report-{G2_TASK}.json"
    s = _g2_setup(tmp_path, "dev", _g2_dev_artifacts())
    question = s.project / _g2_question_path(G2_TASK, "dev")
    _write(question, _g2_question(G2_TASK, "dev"))
    earlier = s.dispatched_at.timestamp() - 3600
    os.utime(question, (earlier, earlier))
    proc = _g2_stop(s)
    _g2_assert_blocked_on(proc, report, _G2_MISSING)
    assert "producer_question" not in proc.stderr
    # A re-dispatched producer that writes its report passes; the stale
    # question from the earlier round neither helps nor hurts.
    _write(s.project / report, _g2_dev_report_v1(G2_TASK))
    proc = _g2_stop(s)
    assert proc.returncode == 0, proc.stderr
    _g2_assert_decided_by_obligation(s)


# (f) no reply text stands in for an artifact -----------------------------


@pytest.mark.parametrize(
    "reply",
    [
        "I need an owner decision before I can write the report.\n"
        "AWAITING_INPUT: keep the cache or replace it?",
        "Should I keep the cache or replace it?",
    ],
    ids=["awaiting_input_line", "question_text"],
)
def test_g2_reply_text_without_artifact_is_a_missing_artifact(tmp_path, reply):
    report = f"docs/dev/dev-report-{G2_TASK}.json"
    s = _g2_setup(tmp_path, "dev", _g2_dev_artifacts())
    proc = _g2_stop(s, msg=reply)
    _g2_assert_blocked_on(proc, report, _G2_MISSING)


# (g) only ba and dev have the question path ------------------------------


def test_g2_qa_question_artifact_does_not_stand_in_for_qa_report(tmp_path):
    """Which producers may ask is producer-question.v1's role enum (ba, dev;
    D23), not a role list in the gate: a QA's question stands in for nothing,
    the stop blocks on the missing report and names the question invalid."""
    report = f"docs/dev/qa-report-{G2_TASK}.json"
    question = _g2_question_path(G2_TASK, "qa")
    s = _g2_setup(tmp_path, "qa", [_g2_json(report, "qa-report.v2")])
    _write(s.project / question, _g2_question(G2_TASK, "qa"))
    proc = _g2_stop(s)
    _g2_assert_blocked_on(proc, report, _G2_MISSING)
    _g2_assert_blocked_on(proc, question, "producer_question_invalid")
    assert "'qa' is not one of ['ba', 'dev']" in proc.stderr, proc.stderr


# (g') the expected role is the type the agent registered as ---------------


@pytest.mark.parametrize("role", ["pm", "architect", "test-writer"])
def test_g2_registered_role_outside_any_list_is_decided_by_its_obligation(tmp_path, role):
    """P1b row 18: no role list says whose obligation G2 resolves. A PM or a
    specialist registered as its type, dispatched with its own obligation,
    is judged on the artifact that obligation declares."""
    report = f"docs/dev/{role}-report-{G2_TASK}.json"
    s = _g2_setup(tmp_path, role, [_g2_json(report, "ba-qa-report.v1")],
                  pipeline="dev-overnight", profile="overnight")
    proc = _g2_stop(s)
    _g2_assert_blocked_on(proc, report, _G2_MISSING)
    _write(s.project / report, _g2_ba_qa_report(G2_TASK, "pass"))
    proc = _g2_stop(s)
    assert proc.returncode == 0, proc.stderr
    _g2_assert_decided_by_obligation(s)


def test_g2_obligation_of_another_role_than_registered_is_not_this_agents(tmp_path):
    """An agent registered as qa whose dispatch carries a dev obligation: the
    obligation is not the one its type declares (role_mismatch), so the
    obligation branch decides nothing for it."""
    report = f"docs/dev/dev-report-{G2_TASK}.json"
    s = _g2_setup(tmp_path, "qa", [])
    doc = dict(s.obligation, role="dev", artifacts=_g2_dev_artifacts())
    _write_obligation_transcript(s.home, s.project, s.harness, s.agent_id,
                                 f'<obligation v="1">\n{json.dumps(doc)}\n</obligation>')
    resolution = _resolution(s.home, s.project, s.harness, s.agent_id, "qa")
    assert isinstance(resolution, HOOK.obligation.Unresolvable)
    assert resolution.reason == "role_mismatch"
    proc = _g2_stop(s)
    assert f"  - {report}:" not in proc.stderr, proc.stderr


# (h) close-QA: the waiver reads the reply's final non-empty line ---------


def _g2_close_qa_obligation() -> dict:
    """commands/close.md's close-QA obligation (role qa, profile
    final_verification; the only one), read from the template itself with
    <TASK_ID> bound. Its response_line regex admits the
    CLOSE_REPORT_APPEND_(ERROR|CRITICAL) line family (P1 row 21)."""
    text = (REPO_ROOT / "commands" / "close.md").read_text(encoding="utf-8")
    found = []
    for body in _re.findall(r'<obligation v="1">\s*(\{.*?\})\s*</obligation>', text, _re.S):
        try:
            doc = json.loads(body.replace("<TASK_ID>", G2_TASK))
        except ValueError:
            continue
        if doc.get("role") == "qa" and doc.get("profile") == "final_verification":
            found.append(doc)
    assert len(found) == 1, found
    return found[0]


def _g2_close_qa_setup(tmp_path):
    doc = _g2_close_qa_obligation()
    [report] = [a["path"] for a in doc["artifacts"] if a["kind"] == "markdown"]
    assert report == f"docs/dev/close-report-{G2_TASK}.md"
    s = _g2_setup(tmp_path, "qa", doc["artifacts"], pipeline=doc["pipeline"],
                  profile=doc["profile"], consistency=doc.get("consistency"))
    # The on-disk last line is a prior attempt's: it fails unless waived.
    _write(s.project / report, f"# Close Debate Report\n{G2_TASK}\nSTALE-UNRELATED-LINE\n")
    return s, report


def test_g2_close_qa_append_error_final_line_waives_markdown(tmp_path):
    s, report = _g2_close_qa_setup(tmp_path)
    reply = (
        "Step 2 reached no verdict for this attempt.\n"
        "The append helper refused to touch the report.\n"
        "\n"
        "CLOSE_REPORT_APPEND_ERROR: append: disk full\n"
    )
    proc = _g2_stop(s, msg=reply)
    assert proc.returncode == 0, proc.stderr
    _g2_assert_decided_by_obligation(s)


def test_g2_close_qa_sentinel_quoted_on_earlier_line_does_not_waive(tmp_path):
    s, report = _g2_close_qa_setup(tmp_path)
    reply = (
        "CLOSE_REPORT_APPEND_ERROR: append: disk full\n"
        "That was the previous attempt; this one is done.\n"
        "DONE\n"
    )
    proc = _g2_stop(s, msg=reply)
    assert proc.returncode == 2, proc.stderr
    assert "OBLIGATION_STOPGATE_BLOCKED" in proc.stderr
    assert f"  - {report}: terminal_line_mismatch" in proc.stderr, proc.stderr
    assert "  - <response_line>: terminal_line_mismatch" in proc.stderr, proc.stderr


# (i) a missing declared artifact blocks ----------------------------------


def test_g2_missing_declared_artifact_blocks(tmp_path):
    report = f"docs/dev/ba-qa-report-{G2_TASK}.json"
    s = _g2_setup(tmp_path, "qa", [_g2_json(report, "ba-qa-report.v1")], profile="ba_validation")
    proc = _g2_stop(s)
    _g2_assert_blocked_on(proc, report, _G2_MISSING)
    assert "expected artifact missing" in proc.stderr


# ---------------------------------------------------------------------------
# Landing on an in-flight fan-out cycle: the legacy report-schema check judges
# the stopping producer's own lane report only. A dev lane dispatched from
# origin/master's template carries required_values, so its obligation no
# longer parses (invalid_obligation) and the legacy check decides, but the
# block still names the lane's task_id.
# ---------------------------------------------------------------------------

_FANOUT_LANES = ("l1", "l2")
_FANOUT_HARNESS = "harness-fanout-landing"


def _pre_p1_lane_obligation(task_id: str, lane: str) -> str:
    doc = {
        "task_id": task_id, "role": "dev", "pipeline": "dev", "profile": "fanout-lane",
        "dispatched_at": datetime.now(timezone.utc).isoformat(),
        "lane": lane, "lane_set": list(_FANOUT_LANES),
        "artifacts": [{
            "kind": "json", "path": f"docs/dev/dev-report-{task_id}.json",
            "schema": "dev-report.v2", "identity": {"task_id": task_id},
            "required_values": {"dev.status": ["completed"]},
        }],
    }
    return f'<obligation v="1">\n{json.dumps(doc, indent=2)}\n</obligation>'


def _fanout_landing_setup(tmp_path, l2_status: str):
    project = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir()
    _enable_flag(project, SESSION)
    _write_sentinel(project, SESSION, "dev")
    tasks = {lane: f"{SESSION}-{lane}" for lane in _FANOUT_LANES}
    for lane, task in tasks.items():
        _register_agent(project, f"agent-dev-{lane}", SESSION, "dev")
        _write_obligation_transcript(
            home, project, _FANOUT_HARNESS, f"agent-dev-{lane}",
            "You are the dev subagent.\n" + _pre_p1_lane_obligation(task, lane))
    # l1 reported needs_review under the pre-P1 schema, before the landing.
    statuses = {"l1": "needs_review", "l2": l2_status}
    for lane, task in tasks.items():
        _write(project / "docs" / "dev" / f"dev-report-{task}.json",
               _l2_dev_report(task, status=statuses[lane], lane=lane,
                              lane_set=list(_FANOUT_LANES)))
    return project, home, tasks


@pytest.mark.parametrize("stopgate", [None, "block"], ids=["switch_unset", "stopgate_block"])
@pytest.mark.parametrize("l2_status,expected", [("completed", 0), ("needs_review", 2)],
                         ids=["l2_valid", "l2_invalid"])
def test_fanout_legacy_check_judges_only_the_stopping_lanes_own_report(
    tmp_path, stopgate, l2_status, expected
):
    project, home, tasks = _fanout_landing_setup(tmp_path, l2_status)
    l1_report = f"dev-report-{tasks['l1']}.json"
    l2_report = f"dev-report-{tasks['l2']}.json"

    proc = _run_hook(project, home, "agent-dev-l2", session_id=_FANOUT_HARNESS,
                     stopgate_mode=stopgate)
    assert proc.returncode == expected, proc.stderr
    assert l1_report not in proc.stderr
    if expected == 2:
        assert "ARTIFACT_CONTRACT_BLOCKED" in proc.stderr
        assert l2_report in proc.stderr
    resolution = _resolution(home, project, _FANOUT_HARNESS, "agent-dev-l2", "dev")
    assert isinstance(resolution, HOOK.obligation.Unresolvable), resolution
    assert resolution.reason == "invalid_obligation"

    # l1 is still judged on its own report, at its own stop.
    proc_l1 = _run_hook(project, home, "agent-dev-l1", session_id=_FANOUT_HARNESS,
                        stopgate_mode=stopgate)
    assert proc_l1.returncode == 2, proc_l1.stderr
    assert l1_report in proc_l1.stderr and l2_report not in proc_l1.stderr


if __name__ == "__main__":
    sys.exit(subprocess.run([sys.executable, "-m", "pytest", __file__, "-v"]).returncode)
