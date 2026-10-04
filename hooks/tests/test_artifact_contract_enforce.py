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
    }


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


# ---------------------------------------------------------------------------
# Obligation mode (rollout S4, ticket-20260930-132644-l2)
# ---------------------------------------------------------------------------


def test_ac1_legacy_path_byte_identical_without_obligation(tmp_path):
    """AC1: whether resolve_own_obligation lands on Unresolvable (no
    session_id supplied) or NoObligationInPrompt (a resolvable transcript
    with no '<obligation' substring), the legacy path's exit code is
    identical -- the obligation branch never changes outcomes it doesn't
    own."""
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
    assert no_session.returncode == 2, no_session.stderr
    assert with_session.returncode == no_session.returncode == 2
    assert "ARTIFACT_CONTRACT_BLOCKED" in with_session.stderr


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
    correlation path ever running. Proof fixture: a DIFFERENT,
    session-ts-correlated report that IS schema-invalid; if the legacy path
    ran, it would independently block on it."""
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
        project / "docs" / "dev" / f"dev-report-{SESSION_TS}.json",
        _invalid_dev_report(SESSION_TS),
    )
    proc = _run_hook(
        project, home, agent_id, session_id=harness_session, stopgate_mode="block"
    )
    assert proc.returncode == 0, proc.stderr
    assert "ARTIFACT_CONTRACT_BLOCKED" not in proc.stderr


def test_ac4_advisory_mode_never_blocks_logs_verify_fail(tmp_path):
    """AC4: the AC2 setup under advisory mode (the default) exits 0 and
    appends an obligation_verify_fail advisory record naming the missing
    artifact's path."""
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
    records = _advisory_records(home)
    fails = [r for r in records if r["kind"] == "obligation_verify_fail"]
    assert fails, records
    assert any(
        f.get("path") == artifact_path for r in fails for f in r.get("failures", [])
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
    """AC6: a forced exception inside validate_artifact_for_obligation logs
    obligation_gate_error and falls through; the legacy path's OWN
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
    _write(
        project / "docs" / "dev" / f"dev-report-{SESSION_TS}.json",
        _invalid_dev_report(SESSION_TS),
    )

    def _raise(*_args, **_kwargs):
        raise RuntimeError("forced obligation-mode failure")

    monkeypatch.setattr(HOOK.contract_runtime, "validate_artifact_for_obligation", _raise)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("HOME", str(home))
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
    records = _advisory_records(home)
    assert any(r["kind"] == "obligation_gate_error" for r in records)


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
    ever running, in block mode. Proof fixture: a DIFFERENT,
    session-ts-correlated report that IS schema-invalid; if the legacy path
    ran, it would independently block on it (same technique as AC3 above)."""
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
        project / "docs" / "dev" / f"dev-report-{SESSION_TS}.json",
        _invalid_dev_report(SESSION_TS),
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


def test_markdown_ac5_advisory_mode_never_blocks_logs_verify_fail(tmp_path):
    """This ticket's AC5: the AC3 setup (identity_anchor missing) under
    advisory mode (default/unset) -> exit 0, and an obligation_verify_fail
    advisory record naming the markdown artifact's path is appended."""
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
    records = _advisory_records(home)
    fails = [r for r in records if r["kind"] == "obligation_verify_fail"]
    assert fails, records
    assert any(
        f.get("path") == md_path for r in fails for f in r.get("failures", [])
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
    records = _advisory_records(home)
    assert not any(r["kind"] == "obligation_artifact_kind_unsupported" for r in records)
    assert not any(r["kind"] == "obligation_verify_fail" for r in records)


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
    and an obligation_markdown_waived advisory record names the path."""
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
    records = _advisory_records(home)
    waived = [r for r in records if r["kind"] == "obligation_markdown_waived"]
    assert waived, records
    assert waived[0]["path"] == md_path
    assert not any(r["kind"] == "obligation_verify_fail" for r in records)


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
    """Parity with every other obligation kind: advisory mode logs the
    obligation_verify_fail record but never exits non-zero."""
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
    records = _advisory_records(home)
    assert any(r.get("kind") == "obligation_verify_fail" for r in records)


def test_ac9_tests_land_in_existing_files_not_new_ones():
    """AC9: this lane's new tests augment the two EXISTING suites; no third
    test file is created for either hook's deliverable. Scoped to this
    lane's own markers only -- the shared working tree carries many
    unrelated dirty files under hooks/tests/ and tests/ from concurrent
    fan-out lanes, so this check must not assume exclusive ownership of
    either directory."""
    proc = subprocess.run(
        ["git", "status", "--porcelain", "hooks/tests/", "tests/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    touched = {line[3:].strip() for line in proc.stdout.splitlines() if line.strip()}
    assert "hooks/tests/test_artifact_contract_enforce.py" in touched
    assert "tests/test_subagentstop_e2e_enforce.py" in touched

    canonical = {
        "hooks/tests/test_artifact_contract_enforce.py",
        "tests/test_subagentstop_e2e_enforce.py",
    }
    for marker in ("OBLIGATION_STOPGATE_BLOCKED", "_qa_report_expected_absent"):
        grep = subprocess.run(
            [
                "grep", "-rl", "--include=*.py", marker,
                str(REPO_ROOT / "hooks" / "tests"), str(REPO_ROOT / "tests"),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        found = {
            str(Path(p).resolve().relative_to(REPO_ROOT))
            for p in grep.stdout.splitlines()
            if p.strip()
        }
        found = {p for p in found if not p.startswith("tests/generated/")}
        assert found <= canonical, (
            f"{marker!r} referenced outside the two canonical test files: "
            f"{found - canonical}"
        )


def test_dev_report_obligation_blocks_even_when_agent_index_entry_missing(
    monkeypatch, tmp_path
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
    records = _advisory_records(home)
    fails = [r for r in records if r["kind"] == "obligation_verify_fail"]
    assert fails, records
    assert any(
        f.get("path") == artifact_path for r in fails for f in r.get("failures", [])
    )


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
            "root_cause_analysis": {},
            "waves": [
                {"wave_id": 1, "tasks": [{"task_id": task_id, "title": "x"}]}
            ],
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
# state, four downstream wires, progress-bounded blocking, nonce hand-off.
# Every scenario is a function taking the pytest fixtures it needs, so the
# generated per-AC tests under tests/generated/ can call the SAME scenario.
# Fixtures are built under tmp_path only; the gate runs as a subprocess with
# HOME / project redirected, so no real registry or session state is touched.
# ---------------------------------------------------------------------------

import re as _re
import shutil as _shutil

L2_TASK = "dev-command-20261002-170011"
_NONCE_RE = _re.compile(r"ESCALATION_ACK ([0-9a-f]{32})")
_FINDING_KEY_RE = _re.compile(r"^[^|\s]+\|[^|\s][^|]*$")


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


def _l2_setup(tmp_path, *, role="dev", lane=None, lane_set=None, base_task=L2_TASK,
              required=True, git=True, agent_id="agent-l2-producer", home_name="home",
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
    if required and role == "dev":
        art["required_values"] = {"dev.status": ["completed"]}
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


def _l2_records(s, sub="escalations", cycle=None):
    d = s.project / ".claude" / "dev-registry" / (cycle or s.cycle) / sub
    if not d.is_dir():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))]


def _l2_nonce(proc) -> str:
    found = _NONCE_RE.findall(proc.stderr)
    assert found, proc.stderr
    return found[-1]


def _l2_hook_tree(tmp_path, script_overrides=None, drop_lib=()):
    """Copy of the hook with its lib/, a symlinked schemas/ and a scripts/ tree
    whose named entries are replaced by test stubs (HOOK scripts dir is derived
    from the hook's own location)."""
    root = tmp_path / "hooktree"
    (root / "hooks").mkdir(parents=True)
    _shutil.copy(HOOK_PATH, root / "hooks" / HOOK_PATH.name)
    _shutil.copytree(REPO_ROOT / "hooks" / "lib", root / "hooks" / "lib",
                     ignore=_shutil.ignore_patterns("__pycache__", *drop_lib))
    os.symlink(REPO_ROOT / "schemas", root / "schemas")
    scripts = root / "scripts"
    scripts.mkdir()
    overrides = script_overrides or {}
    for entry in (REPO_ROOT / "scripts").iterdir():
        if entry.name not in overrides:
            os.symlink(entry, scripts / entry.name)
    for name, text in overrides.items():
        (scripts / name).write_text(text, encoding="utf-8")
    return root / "hooks" / HOOK_PATH.name


def _l2_assert_record_fields(rec, s, kind=None):
    assert {"record_id", "nonce", "agent_id", "task_id", "finding_keys", "created_at"} <= set(rec)
    assert "resolved" not in rec
    assert rec["agent_id"] == s.agent_id and rec["task_id"] == s.task
    assert rec["finding_keys"] and all(_FINDING_KEY_RE.match(k) for k in rec["finding_keys"]), rec
    if kind:
        assert rec["kind"] == kind


def _l2_snapshot(project: Path) -> tuple:
    def git(*a):
        return subprocess.run(["git", "-C", str(project), *a], capture_output=True,
                              text=True, check=True).stdout
    return (git("status", "--porcelain"), git("ls-files", "-s"),
            (project / "src.txt").read_bytes())


# AC1 / AC2 -----------------------------------------------------------------


def test_l2_ac1_terminal_state_wrong_blocks(tmp_path):
    s = _l2_setup(tmp_path)
    _l2_write(s, _l2_dev_report(s.task, status="needs_review"))
    proc = _l2_stop(s)
    assert proc.returncode == 2, proc.stderr
    assert s.art_path in proc.stderr
    assert "terminal_value_violation" in proc.stderr
    assert "needs_review" in proc.stderr and "completed" in proc.stderr


def test_l2_ac2_terminal_state_right_passes(tmp_path):
    s = _l2_setup(tmp_path)
    _l2_write(s, _l2_dev_report(s.task))
    proc = _l2_stop(s)
    assert proc.returncode == 0, proc.stderr
    assert not [r for r in _advisory_records(s.home) if r["kind"] == "obligation_verify_fail"]
    assert _l2_records(s) == []


# AC3 -----------------------------------------------------------------------


def test_l2_ac3_ledger_wrong_blocks_right_passes_and_infra_fault_escalates(tmp_path):
    """Attribution-journal consumer cutover (docs/reference/attribution-
    journal-cutover-flip-plan-20261003.md, superseded by the zero-blocking
    constraint of the follow-up consumer-cutover task): this hook no longer
    calls check-owned-edits-ledger.py at all (see _wire_ledger_judgment).
    A malformed self-reported ledger (empty `old` needle) no longer blocks
    the producer's stop -- it has no write-time journal evidence either (a
    plain-filesystem test write), so src.txt is deferred, not rejected.

    The sibling scenario this test used to carry -- a stubbed
    check-owned-edits-ledger.py forced to exit 2, proving an infra fault
    escalates rather than silently passing or being misread as a finding --
    is removed rather than adapted: that script is no longer on this hook's
    blocking path, so stubbing it exercises nothing. _wire_ledger_judgment's
    own infra-fault handling (an unloadable/raising attribution_adjudicator)
    is exercised by this file's existing gate_infrastructure_fault coverage
    for the hook's OTHER wires (see AC6 below); duplicating that pattern
    for this one is not a new property, just a new call site accordion.
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


def test_l2_ac6_qa_chain_attribution(tmp_path):
    s, hook, env = _l2_qa(tmp_path, "own", {"status": "fail", "errors": [
        {"code": "QA_BAD", "path": f"docs/dev/qa-report-{L2_TASK}.json", "detail": "x"}]})
    proc = _l2_stop(s, hook_path=hook, extra_env=env)
    assert proc.returncode == 2 and "QA_BAD" in proc.stderr, proc.stderr

    s, hook, env = _l2_qa(tmp_path, "valid", {"status": "pass", "errors": []})
    assert _l2_stop(s, hook_path=hook, extra_env=env).returncode == 0
    assert _l2_records(s) == []

    s, hook, env = _l2_qa(tmp_path, "upstream", {"status": "fail", "errors": [
        {"code": "DEV_GAP", "path": f"docs/dev/dev-report-{L2_TASK}.json", "detail": "missing"}]})
    proc = _l2_stop(s, hook_path=hook, extra_env=env)
    assert proc.returncode == 0, proc.stderr
    recs = _l2_records(s)
    assert len(recs) == 1 and recs[0]["kind"] == "upstream_defect_notice"
    _l2_assert_record_fields(recs[0], s, kind="upstream_defect_notice")
    assert recs[0]["finding_keys"] == [f"DEV_GAP|docs/dev/dev-report-{L2_TASK}.json"]

    s, hook, env = _l2_qa(tmp_path, "pathless", {"status": "fail", "errors": [
        {"code": "NO_PATH", "path": "", "detail": "x"}]})
    proc = _l2_stop(s, hook_path=hook, extra_env=env)
    assert proc.returncode == 2, proc.stderr
    recs = _l2_records(s)
    assert len(recs) == 1 and recs[0]["reason"] == "gate_infrastructure_fault"


# AC7 / AC10 ----------------------------------------------------------------


def test_l2_ac7_progress_bounded_and_nonce_handoff(tmp_path):
    s = _l2_setup(tmp_path)
    for i in range(6):  # bytes change each stop, still failing: always exit 2, no record
        _l2_write(s, _l2_dev_report(s.task, status="needs_review", note=f"attempt-{i}"))
        proc = _l2_stop(s)
        assert proc.returncode == 2, proc.stderr
        assert _l2_records(s) == []
    first = _l2_stop(s)  # identical bytes -> no progress -> record + nonce quoted
    assert first.returncode == 2
    recs = _l2_records(s)
    assert len(recs) == 1
    _l2_assert_record_fields(recs[0], s)
    path = s.project / ".claude" / "dev-registry" / s.cycle / "escalations" / f"{recs[0]['record_id']}.json"
    assert path.is_file() and recs[0]["nonce"] == _l2_nonce(first)
    raw_first = path.read_bytes()

    nonce_a = recs[0]["nonce"]
    # Nonce only inside a longer line / stale / other payload field / fixed literal: all exit 2.
    longer = _l2_stop(s, msg=f"please see ESCALATION_ACK {nonce_a} now")
    assert longer.returncode == 2
    stale = _l2_stop(s, msg=f"ESCALATION_ACK {nonce_a}")  # nonce_a is no longer the latest record
    assert stale.returncode == 2
    latest = _l2_nonce(stale)
    other_field = _l2_stop(s, extra_payload={"transcript_tail": f"ESCALATION_ACK {latest}"})
    assert other_field.returncode == 2
    latest = _l2_nonce(other_field)
    literal = _l2_stop(s, msg="ESCALATION_ACK\nESCALATION_ACK 00000000000000000000000000000000")
    assert literal.returncode == 2
    latest = _l2_nonce(literal)
    assert path.read_bytes() == raw_first  # earlier record untouched

    done = _l2_stop(s, msg=f"could not repair.\n  ESCALATION_ACK {latest}  \n")
    assert done.returncode == 0, done.stderr
    recs = _l2_records(s)
    assert len({r["nonce"] for r in recs}) == len(recs) == len({r["record_id"] for r in recs})
    assert latest in {r["nonce"] for r in recs}
    assert path.read_bytes() == raw_first
    assert any(a["nonce"] == latest for a in _l2_records(s, "escalation-admissions"))


def test_l2_ac10_rejected_repair_is_no_progress_not_an_escape(tmp_path):
    s = _l2_setup(tmp_path)
    _l2_write(s, _l2_dev_report(s.task, status="needs_review"))
    assert _l2_stop(s).returncode == 2           # round 1
    # Repair attempt rejected by a hook: bytes unchanged -> no progress -> nonce hand-off only.
    second = _l2_stop(s)
    assert second.returncode == 2 and _NONCE_RE.search(second.stderr)
    # Reverting to previously seen bytes after a change is also no progress.
    _l2_write(s, _l2_dev_report(s.task, status="needs_review", note="other"))
    assert _l2_stop(s).returncode == 2
    _l2_write(s, _l2_dev_report(s.task, status="needs_review"))
    third = _l2_stop(s)
    assert third.returncode == 2 and _NONCE_RE.search(third.stderr)
    # No pause text of any kind admits the stop.
    paused = _l2_stop(s, msg="PAUSED: hook rejected my repair; releasing myself\nPAUSE_RELEASE")
    assert paused.returncode == 2


# AC8 -----------------------------------------------------------------------

_RAISING_PLAN_STUB = (
    "class PlanError(RuntimeError):\n"
    "    code = None\n"
    "def build_plan(**kwargs):\n"
    "    raise RuntimeError('unexpected checker crash')\n"
)


def test_l2_ac8_no_residual_fail_open(tmp_path):
    s = _l2_setup(tmp_path)
    _l2_write(s, _l2_dev_report(s.task))
    hook = _l2_hook_tree(tmp_path, {"resolve-commit-repos.py": _RAISING_PLAN_STUB})
    first = _l2_stop(s, hook_path=hook)
    assert first.returncode == 2, first.stderr
    recs = _l2_records(s)
    assert len(recs) == 1 and recs[0]["reason"] == "gate_exception"
    assert _l2_stop(s, hook_path=hook).returncode == 2
    nonce = _l2_nonce(_l2_stop(s, hook_path=hook))
    ok = _l2_stop(s, hook_path=hook, msg=f"ESCALATION_ACK {nonce}")
    assert ok.returncode == 0, ok.stderr
    assert any(r["nonce"] == nonce for r in _l2_records(s))

    # No counter-threshold release: identical bytes, never an ack line.
    s2 = _l2_setup(tmp_path / "loop")
    _l2_write(s2, _l2_dev_report(s2.task, status="needs_review"))
    assert all(_l2_stop(s2).returncode == 2 for _ in range(6))

    # Escalation record cannot be written: a FILE occupies the escalations path.
    s3 = _l2_setup(tmp_path / "unwritable")
    _l2_write(s3, _l2_dev_report(s3.task))
    reg = s3.project / ".claude" / "dev-registry" / s3.cycle
    reg.mkdir(parents=True, exist_ok=True)
    (reg / "escalations").write_text("not a directory", encoding="utf-8")
    hook3 = _l2_hook_tree(tmp_path / "unwritable", {"resolve-commit-repos.py": _RAISING_PLAN_STUB})
    for _ in range(3):
        proc = _l2_stop(s3, hook_path=hook3, msg="ESCALATION_ACK " + "0" * 32)
        assert proc.returncode == 2, proc.stderr
    assert (reg / "escalations").is_file()


# AC9 -----------------------------------------------------------------------


def test_l2_ac9_forced_close_flag_locations(tmp_path):
    def build(name):
        project, home = _standard_setup(tmp_path / name, "dev", f"agent-{name}")
        _write(project / "docs" / "dev" / f"dev-report-{SESSION_TS}.json",
               _invalid_dev_report(f"dev-{SESSION_TS}"))
        return project, home, f"agent-{name}"

    flag_name = f"claude-close-force-{SESSION}.flag"
    # (1) flag only in TMPDIR scratch -> bypass honoured.
    project, home, agent = build("tmpdir")
    scratch = tmp_path / "tmpdir" / "scratch"
    scratch.mkdir(parents=True)
    (scratch / flag_name).write_text("1", encoding="utf-8")
    proc = _run_hook(project, home, agent, extra_env={"TMPDIR": str(scratch)})
    assert proc.returncode == 0, proc.stderr
    # (2) flag nowhere -> blocked, and no gate scratch outside the registry / tmp default.
    project, home, agent = build("none")
    empty = tmp_path / "none" / "scratch"
    empty.mkdir(parents=True)
    proc = _run_hook(project, home, agent, extra_env={"TMPDIR": str(empty)})
    assert proc.returncode == 2, proc.stderr
    assert not any(empty.iterdir())
    # (3) flag redirected through the harness state dir -> bypass honoured.
    project, home, agent = build("state")
    state = tmp_path / "state" / "statedir"
    state.mkdir(parents=True)
    (state / flag_name).write_text("1", encoding="utf-8")
    proc = _run_hook(project, home, agent, extra_env={"CLAUDE_STATE_DIR": str(state),
                                                      "TMPDIR": str(empty)})
    assert proc.returncode == 0, proc.stderr
    # (4) the legacy fixed location remains honoured (see test_force_close_sentinel_allows).
    assert HOOK.LEGACY_FLAG_DIR == "/tmp"
    assert HOOK._forced_close_flag_present("l2-never-created-session") is False


# AC11 ----------------------------------------------------------------------


def test_l2_ac11_scope_only_owned_files_claimed():
    owned = {"hooks/subagentstop-artifact-contract-enforce.py",
             "hooks/tests/test_artifact_contract_enforce.py"}
    report_path = REPO_ROOT / "docs" / "dev" / f"dev-report-{L2_TASK}-l2.json"
    if not report_path.is_file():
        pytest.skip("dev report not written yet")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    claimed = set(report["dev"]["files_modified"]) | set(report["dev"]["files_created"])
    assert claimed == owned, claimed
    assert set(report["owned_edits"]) <= owned


# AC12 ----------------------------------------------------------------------


def test_l2_ac12_shard_defers_plan_and_replay_single_lane_blocks(tmp_path):
    """Attribution-journal consumer cutover (see test_l2_ac3's docstring for
    the full citation): _wire_ledger_judgment replaces stage-owned-hunks.py
    --dry-run's per-file replay entirely, and it does not need the full
    trial plan (unlike build_plan/_wire_trial_plan), so it is no longer
    deferred for a sharded lane -- it already ran, unconditionally, before
    the shard check below (see _run_downstream_wires). Only "trial_plan"
    remains deferred to full-cycle time. Neither the sharded nor the
    single-lane peer-dirty scenario blocks any more: src.txt is a plain-
    filesystem test write with no journal evidence, so both are deferred."""
    def peer_dirty(s):
        _l2_write(s, _l2_dev_report(s.task, lane=s.lane, lane_set=s.lane_set))
        (s.project / "src.txt").write_text("gamma\n", encoding="utf-8")

    shard = _l2_setup(tmp_path / "shard", lane="l2", lane_set=["l1", "l2"])
    shard.lane, shard.lane_set = "l2", ["l1", "l2"]
    peer_dirty(shard)
    proc = _l2_stop(shard)
    assert proc.returncode == 0, proc.stderr
    deferrals = _l2_records(shard, "deferred-checks")
    assert len(deferrals) == 1 and deferrals[0]["kind"] == "not_evaluable_at_lane_granularity"
    assert set(deferrals[0]["checks"]) == {"trial_plan"}
    assert any(r["kind"] == "obligation_check_deferred" for r in _advisory_records(shard.home))

    single = _l2_setup(tmp_path / "single")
    single.lane = None
    single.lane_set = None
    peer_dirty(single)
    proc = _l2_stop(single)
    assert proc.returncode == 0, proc.stderr

    # Shared progress helper unimportable: fail closed, never an inlined measure.
    s = _l2_setup(tmp_path / "nohelper")
    _l2_write(s, _l2_dev_report(s.task, status="needs_review"))
    hook = _l2_hook_tree(tmp_path / "nohelper", drop_lib=("progress_measure.py",))
    proc = _l2_stop(s, hook_path=hook)
    assert proc.returncode == 2, proc.stderr
    recs = _l2_records(s)
    assert len(recs) == 1 and recs[0]["reason"] == "gate_infrastructure_fault"


# AC13 ----------------------------------------------------------------------


def _l13_scan(registry_dir: Path):
    gate = REPO_ROOT / "hooks" / "stop-completion-gate.py"
    if not gate.is_file():
        return None
    spec = importlib.util.spec_from_file_location("l13_completion_gate_under_test", gate)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO_ROOT / "hooks"))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.pop(0)
    return getattr(mod, "_scan_escalations", None)


def test_l2_ac13_record_lands_where_the_consumer_scans(tmp_path):
    s = _l2_setup(tmp_path / "lane", lane="l2", lane_set=["l1", "l2"], required=True)
    s.lane = "l2"
    _l2_write(s, _l2_dev_report(s.task, status="needs_review", lane="l2", lane_set=["l1", "l2"]))
    _l2_stop(s)
    proc = _l2_stop(s)
    assert proc.returncode == 2 and _NONCE_RE.search(proc.stderr)
    registry = s.project / ".claude" / "dev-registry"
    assert s.cycle == L2_TASK and s.task == L2_TASK + "-l2"
    cycle_dir = registry / L2_TASK
    recs = _l2_records(s)
    assert len(recs) == 1
    _l2_assert_record_fields(recs[0], s)
    assert (cycle_dir / "escalations" / f"{recs[0]['record_id']}.json").is_file()
    assert not (registry / s.task / "escalations").exists()
    scan = _l13_scan(cycle_dir)
    if scan is not None:
        assert [r["record_id"] for r in scan(cycle_dir)] == [recs[0]["record_id"]]
    state = json.loads((cycle_dir / "progress" /
                        f"producer-stop-{HOOK._record_safe(s.agent_id)}.json").read_text("utf-8"))
    assert state["loop_key"] == f"producer-stop|{s.task}|{s.agent_id}"

    # lane null: cycle_id is the task id itself.
    n = _l2_setup(tmp_path / "nolane")
    _l2_write(n, _l2_dev_report(n.task, status="needs_review"))
    _l2_stop(n)
    assert _l2_stop(n).returncode == 2
    assert len(_l2_records(n)) == 1
    assert (n.project / ".claude" / "dev-registry" / n.task / "escalations").is_dir()

    # upstream_defect_notice carries the same fields (AC6 third case).
    q, hook, env = _l2_qa(tmp_path, "ud", {"status": "fail", "errors": [
        {"code": "DEV_GAP", "path": f"docs/dev/dev-report-{L2_TASK}.json", "detail": "m"}]})
    assert _l2_stop(q, hook_path=hook, extra_env=env).returncode == 0
    _l2_assert_record_fields(_l2_records(q)[0], q, kind="upstream_defect_notice")


if __name__ == "__main__":
    sys.exit(subprocess.run([sys.executable, "-m", "pytest", __file__, "-v"]).returncode)
