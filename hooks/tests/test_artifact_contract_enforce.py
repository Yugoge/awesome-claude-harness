#!/usr/bin/env python3
"""Tests for hooks/subagentstop-artifact-contract-enforce.py.

The hook is the producer-side port of /close's Artifact schema gate
(contract_runtime.validate_report_artifact): a registered dev/qa subagent in a
session whose artifact-contract-enforce.json flag is enabled must not stop
while its correlated report declares report_version yet violates its schema
(exit 2). Everything else — unversioned legacy reports, missing reports,
unregistered agents, absent flag, non-enforced agent types, ba_validation QA,
forced closes — passes through (exit 0). Missing reports and would-block
events land in ~/.claude/logs/artifact-contract-advisory.jsonl.

Models tests/test_subagentstop_e2e_enforce.py's fixture and invocation
patterns (importlib for the hyphenated module, subprocess with
CLAUDE_PROJECT_DIR; HOME is redirected per-test so advisory log writes stay
inside tmp_path).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK_PATH = REPO_ROOT / "hooks" / "subagentstop-artifact-contract-enforce.py"
FLAG_WRITER = REPO_ROOT / "scripts" / "write-enforce-flag.sh"

SESSION = "dev-20260101-000000"
SESSION_TS = "20260101-000000"


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


def _enable_flag(
    project_dir: Path, dev_session_id: str, enforced_agent_types=("dev", "qa")
) -> None:
    _write(
        project_dir / ".claude" / "dev-registry" / dev_session_id
        / "artifact-contract-enforce.json",
        {"enabled": True, "enforced_agent_types": list(enforced_agent_types)},
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
    project_dir: Path, home_dir: Path, agent_id: str, mode: str | None = None
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    env["HOME"] = str(home_dir)
    env.pop("ARTIFACT_CONTRACT_ENFORCE_MODE", None)
    if mode is not None:
        env["ARTIFACT_CONTRACT_ENFORCE_MODE"] = mode
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps({"agent_id": agent_id}),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _advisory_records(home_dir: Path) -> list[dict]:
    log = home_dir / ".claude" / "logs" / "artifact-contract-advisory.jsonl"
    if not log.exists():
        return []
    return [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _standard_setup(tmp_path: Path, agent_type: str, agent_id: str, **sentinel_extra):
    project = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    _register_agent(project, agent_id, SESSION, agent_type)
    _enable_flag(project, SESSION)
    _write_sentinel(project, SESSION, agent_type, **sentinel_extra)
    return project, home


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
    assert data["enforced_agent_types"] == ["dev", "qa"]
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
    _write(
        project / "docs" / "dev" / f"qa-report-{SESSION_TS}.json",
        _invalid_qa_report(SESSION_TS),
    )
    proc = _run_hook(project, home, "agent-qa-1")
    assert proc.returncode == 0, proc.stderr


def test_agent_type_outside_flag_list_allows(tmp_path):
    project, home = _standard_setup(tmp_path, "dev", "agent-dev-1")
    # Flag narrowed to qa only: dev stops freely even with an invalid report.
    _enable_flag(project, SESSION, enforced_agent_types=("qa",))
    _write(
        project / "docs" / "dev" / f"dev-report-{SESSION_TS}.json",
        _invalid_dev_report(SESSION_TS),
    )
    proc = _run_hook(project, home, "agent-dev-1")
    assert proc.returncode == 0, proc.stderr


def test_ba_validation_qa_exempt(tmp_path):
    project, home = _standard_setup(
        tmp_path, "qa", "agent-qa-1", qa_mode="ba_validation"
    )
    _write(
        project / "docs" / "dev" / f"qa-report-{SESSION_TS}.json",
        _invalid_qa_report(SESSION_TS),
    )
    proc = _run_hook(project, home, "agent-qa-1")
    assert proc.returncode == 0, proc.stderr


def test_force_close_sentinel_allows(tmp_path):
    # Unique session id so the /tmp sentinel cannot collide across runs.
    session = "dev-19990101-000001"
    project = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir()
    _register_agent(project, "agent-qa-1", session, "qa")
    _write(
        project / ".claude" / "dev-registry" / session
        / "artifact-contract-enforce.json",
        {"enabled": True, "enforced_agent_types": ["dev", "qa"]},
    )
    _write_sentinel(project, session, "qa")
    _write(
        project / "docs" / "dev" / "qa-report-19990101-000001.json",
        _invalid_qa_report("19990101-000001"),
    )
    sentinel = Path(f"/tmp/claude-close-force-{session}.flag")
    sentinel.write_text("", encoding="utf-8")
    try:
        proc = _run_hook(project, home, "agent-qa-1")
        assert proc.returncode == 0, proc.stderr
    finally:
        sentinel.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Blocking surface: versioned-and-invalid only (same as /close's schema gate)
# ---------------------------------------------------------------------------


def test_qa_schema_invalid_blocks(tmp_path):
    project, home = _standard_setup(tmp_path, "qa", "agent-qa-1")
    _write(
        project / "docs" / "dev" / f"qa-report-{SESSION_TS}.json",
        _invalid_qa_report(SESSION_TS),
    )
    proc = _run_hook(project, home, "agent-qa-1")
    assert proc.returncode == 2, proc.stderr
    assert "ARTIFACT_CONTRACT_BLOCKED" in proc.stderr
    assert "qa-report.v1" in proc.stderr
    records = _advisory_records(home)
    assert any(r["kind"] == "schema_fail" for r in records)


def test_dev_schema_invalid_blocks(tmp_path):
    project, home = _standard_setup(tmp_path, "dev", "agent-dev-1")
    _write(
        project / "docs" / "dev" / f"dev-report-{SESSION_TS}.json",
        _invalid_dev_report(SESSION_TS),
    )
    proc = _run_hook(project, home, "agent-dev-1")
    assert proc.returncode == 2, proc.stderr
    assert "ARTIFACT_CONTRACT_BLOCKED" in proc.stderr
    assert "dev-report.v1" in proc.stderr


def test_qa_schema_valid_allows(tmp_path):
    project, home = _standard_setup(tmp_path, "qa", "agent-qa-1")
    _write(
        project / "docs" / "dev" / f"qa-report-{SESSION_TS}.json",
        _valid_qa_report(SESSION_TS),
    )
    proc = _run_hook(project, home, "agent-qa-1")
    assert proc.returncode == 0, proc.stderr


def test_qa_unversioned_legacy_allows(tmp_path):
    # 665 of 674 real reports on disk are unversioned; they must keep passing.
    project, home = _standard_setup(tmp_path, "qa", "agent-qa-1")
    _write(
        project / "docs" / "dev" / f"qa-report-{SESSION_TS}.json",
        {"task_id": SESSION_TS, "verdict": "pass"},
    )
    proc = _run_hook(project, home, "agent-qa-1")
    assert proc.returncode == 0, proc.stderr


def test_missing_report_allows_and_logs(tmp_path):
    project, home = _standard_setup(tmp_path, "qa", "agent-qa-1")
    (project / "docs" / "dev").mkdir(parents=True, exist_ok=True)
    proc = _run_hook(project, home, "agent-qa-1")
    assert proc.returncode == 0, proc.stderr
    records = _advisory_records(home)
    assert any(r["kind"] == "missing_report" for r in records)


def test_advisory_mode_logs_but_never_blocks(tmp_path):
    project, home = _standard_setup(tmp_path, "qa", "agent-qa-1")
    _write(
        project / "docs" / "dev" / f"qa-report-{SESSION_TS}.json",
        _invalid_qa_report(SESSION_TS),
    )
    proc = _run_hook(project, home, "agent-qa-1", mode="advisory")
    assert proc.returncode == 0, proc.stderr
    records = _advisory_records(home)
    assert any(
        r["kind"] == "schema_fail" and r["mode"] == "advisory" for r in records
    )


# ---------------------------------------------------------------------------
# Fan-out: ALL correlated reports are validated (union, not lexicographic pick)
# ---------------------------------------------------------------------------


def test_fanout_invalid_lane_not_shadowed_by_later_valid_sibling(tmp_path):
    # Codex audit finding (HIGH): lane-a invalid must block even though
    # lane-b sorts lexicographically later and is valid.
    project, home = _standard_setup(tmp_path, "dev", "agent-dev-1")
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
        },
    )
    proc = _run_hook(project, home, "agent-dev-1")
    assert proc.returncode == 2, proc.stderr
    assert "lane-a" in proc.stderr


def test_fanout_all_valid_lane_reports_allow(tmp_path):
    project, home = _standard_setup(tmp_path, "dev", "agent-dev-1")
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
            },
        )
    proc = _run_hook(project, home, "agent-dev-1")
    assert proc.returncode == 0, proc.stderr


def test_fanout_invalid_canonical_not_shadowed_by_valid_shards(tmp_path):
    # Aggregate canonical (no lane suffix) invalid, shards valid: still blocks.
    project, home = _standard_setup(tmp_path, "qa", "agent-qa-1")
    _write(
        project / "docs" / "dev" / f"qa-report-{SESSION_TS}.json",
        _invalid_qa_report(SESSION_TS),
    )
    _write(
        project / "docs" / "dev" / f"qa-report-{SESSION_TS}-lane-a.json",
        _valid_qa_report(SESSION_TS),
    )
    proc = _run_hook(project, home, "agent-qa-1")
    assert proc.returncode == 2, proc.stderr
    assert f"qa-report-{SESSION_TS}.json" in proc.stderr


def test_task_id_anchor_unions_with_session_ts_matches(tmp_path):
    # /close cross-session shape WITH a same-ts sibling present: the anchor
    # dimension must still contribute its exact-match report to the validated
    # set (union semantics — the old code returned early on any ts match).
    task_id = "20251231-235959"
    session = "dev-20260202-020202"
    project = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir()
    _register_agent(project, "agent-qa-1", session, "qa")
    _write(
        project / ".claude" / "dev-registry" / session
        / "artifact-contract-enforce.json",
        {"enabled": True, "enforced_agent_types": ["dev", "qa"]},
    )
    _write_sentinel(project, session, "qa", task_id=task_id)
    # Session-ts-correlated sibling (valid) + task_id-anchored target (invalid).
    _write(
        project / "docs" / "dev" / "qa-report-20260202-020202.json",
        _valid_qa_report("20260202-020202"),
    )
    _write(
        project / "docs" / "dev" / f"qa-report-{task_id}.json",
        _invalid_qa_report(task_id),
    )
    proc = _run_hook(project, home, "agent-qa-1")
    assert proc.returncode == 2, proc.stderr
    assert task_id in proc.stderr


# ---------------------------------------------------------------------------
# Correlation: the task_id anchor works across sessions (close.md Step 2 path)
# ---------------------------------------------------------------------------


def test_task_id_anchor_blocks_when_session_ts_never_matches(tmp_path):
    # /close in a fresh session binds SESSION_ID="dev-<TASK_ID>" and writes
    # task_id into qa.json; the report filename carries the task_id, not the
    # (different) session timestamp.
    task_id = "20251231-235959"
    session = "dev-20260202-020202"
    project = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir()
    _register_agent(project, "agent-qa-1", session, "qa")
    _write(
        project / ".claude" / "dev-registry" / session
        / "artifact-contract-enforce.json",
        {"enabled": True, "enforced_agent_types": ["dev", "qa"]},
    )
    _write_sentinel(project, session, "qa", task_id=task_id)
    _write(
        project / "docs" / "dev" / f"qa-report-{task_id}.json",
        _invalid_qa_report(task_id),
    )
    proc = _run_hook(project, home, "agent-qa-1")
    assert proc.returncode == 2, proc.stderr
    assert "ARTIFACT_CONTRACT_BLOCKED" in proc.stderr


def test_uncorrelated_report_is_not_grabbed(tmp_path):
    # A report from an unrelated task must not be validated against this
    # session: no correlation -> missing_report advisory, exit 0.
    project, home = _standard_setup(tmp_path, "qa", "agent-qa-1")
    _write(
        project / "docs" / "dev" / "qa-report-20200909-090909.json",
        _invalid_qa_report("20200909-090909"),
    )
    proc = _run_hook(project, home, "agent-qa-1")
    assert proc.returncode == 0, proc.stderr
    records = _advisory_records(home)
    assert any(r["kind"] == "missing_report" for r in records)


if __name__ == "__main__":
    sys.exit(subprocess.run([sys.executable, "-m", "pytest", __file__, "-v"]).returncode)
