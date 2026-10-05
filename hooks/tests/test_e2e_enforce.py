#!/usr/bin/env python3
"""Tests for hooks/subagentstop-e2e-enforce.py's registry-independent
obligation fallback (ticket 20261001-161041-r06, M1).

Pre-fix, this hook called resolve_dev_registry_entry(agent_id, project_dir)
and exited 0 unconditionally when it returned None (agent_id absent from
.claude/dev-registry/agent-index.json -- e.g. a skipped/failed FIRST ACTION
registration), with no fallback at all. That made QA's e2e_enforcement.status
obligation silently unenforceable for exactly the unregistered-agent
population it exists to catch.

This file covers the new fallback: when resolve_dev_registry_entry() returns
None, the hook now calls obligation.resolve_own_obligation() (registry-
independent; reads the agent's own dispatch transcript) and, only when that
resolves to a qa-role obligation declaring a qa-report.v2 artifact, applies
the SAME e2e_enforcement.status check the registered path applies -- against
that artifact's exact declared path. Every other outcome (no session_id, no
obligation block, role mismatch, no qa-report.v2 artifact declared) still
exits 0 (LOW-10 preserved, AC3).

AC1 and AC6 (the shared hooks/subagentstop-artifact-contract-enforce.py
L0/L1-before-L2 reorder) are sibling lanes r02/r04's deliverable, not this
file's -- this lane's dispatch scopes it exclusively to
subagentstop-e2e-enforce.py.

Models hooks/tests/test_artifact_contract_enforce.py's fixture and
invocation patterns (importlib for the hyphenated module under test,
subprocess with CLAUDE_PROJECT_DIR/HOME, the obligation-transcript fixture
helpers, and the "assert the fallback was actually invoked" spy pattern from
that file's own AC5/AC6 tests).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK_PATH = REPO_ROOT / "hooks" / "subagentstop-e2e-enforce.py"


def _load_hook_module():
    spec = importlib.util.spec_from_file_location(
        "subagentstop_e2e_enforce_under_test_r06", HOOK_PATH
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


def _qa_report(task_id: str, status: str = "performed") -> dict:
    return {
        "task_id": task_id,
        "request_id": task_id,
        "e2e_enforcement": {"status": status},
    }


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
    L1 rung (same shape as
    hooks/tests/test_artifact_contract_enforce.py's helper of the same
    name): a subagent transcript whose first record is the dispatch prompt,
    plus a meta.json carrying a toolUseId. The parent transcript is
    deliberately NOT written, so the meta cross-check degrades to "parent
    unreadable" (accepted, not a cross-check failure)."""
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
        json.dumps({"toolUseId": "tooluse-test-r06"}), encoding="utf-8"
    )


def _obligation_block(
    task_id: str, artifact_path: str, schema: str, role: str = "qa"
) -> str:
    doc = {
        "task_id": task_id,
        "role": role,
        "pipeline": "dev",
        "profile": "fanout-lane",
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


def _run_hook(
    project_dir: Path, home_dir: Path, agent_id: str, session_id: str | None = None
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    env["HOME"] = str(home_dir)
    payload: dict = {"agent_id": agent_id}
    if session_id is not None:
        payload["session_id"] = session_id
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _project_home(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "project"
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    return project, home


# ---------------------------------------------------------------------------
# AC2: registry-independent fallback blocks on a missing/unjustified
# obligated report, and passes when the report is valid.
# ---------------------------------------------------------------------------


def test_ac2_unregistered_obligated_missing_report_blocks(tmp_path):
    """AC2: a qa agent_id absent from agent-index.json, whose own transcript
    carries a resolvable obligation (role=qa) naming a qa-report.v2
    artifact that was never written, exits 2 with E2E_ENFORCE_BLOCKED --
    not the pre-fix silent exit 0."""
    harness_session = "harness-r06-ac2"
    agent_id = "agent-qa-r06-ac2"
    task_id = "20261001-161041-r06-ac2"
    artifact_path = f"docs/dev/qa-report-{task_id}.json"
    project, home = _project_home(tmp_path)
    _write_obligation_transcript(
        home,
        project,
        harness_session,
        agent_id,
        _obligation_block(task_id, artifact_path, "qa-report.v2"),
    )
    # Deliberately NOT registered in agent-index.json; the declared
    # qa-report.v2 artifact is deliberately never written.

    proc = _run_hook(project, home, agent_id, session_id=harness_session)

    assert proc.returncode == 2, proc.stderr
    assert "E2E_ENFORCE_BLOCKED" in proc.stderr
    assert task_id in proc.stderr


def test_ac2_unregistered_obligated_valid_report_passes(tmp_path):
    """M3 companion case: the same unregistered+obligated setup, but the
    declared artifact exists with e2e_enforcement.status=performed ->
    exit 0."""
    harness_session = "harness-r06-ac2b"
    agent_id = "agent-qa-r06-ac2b"
    task_id = "20261001-161041-r06-ac2b"
    artifact_path = f"docs/dev/qa-report-{task_id}.json"
    project, home = _project_home(tmp_path)
    _write_obligation_transcript(
        home,
        project,
        harness_session,
        agent_id,
        _obligation_block(task_id, artifact_path, "qa-report.v2"),
    )
    _write(project / artifact_path, _qa_report(task_id, status="performed"))

    proc = _run_hook(project, home, agent_id, session_id=harness_session)

    assert proc.returncode == 0, proc.stderr


def test_ac2_unregistered_obligated_unjustified_skip_blocks(tmp_path):
    """The declared artifact exists but e2e_enforcement.status is the
    unjustified-skip value -> exit 2, same blocking outcome as the
    registered path's equivalent check."""
    harness_session = "harness-r06-ac2c"
    agent_id = "agent-qa-r06-ac2c"
    task_id = "20261001-161041-r06-ac2c"
    artifact_path = f"docs/dev/qa-report-{task_id}.json"
    project, home = _project_home(tmp_path)
    _write_obligation_transcript(
        home,
        project,
        harness_session,
        agent_id,
        _obligation_block(task_id, artifact_path, "qa-report.v2"),
    )
    _write(
        project / artifact_path,
        _qa_report(task_id, status="skipped_without_justification"),
    )

    proc = _run_hook(project, home, agent_id, session_id=harness_session)

    assert proc.returncode == 2, proc.stderr
    assert "E2E_ENFORCE_BLOCKED" in proc.stderr


# ---------------------------------------------------------------------------
# AC3: LOW-10 preserved for genuinely unresolvable/non-qa agents
# ---------------------------------------------------------------------------


def test_ac3_no_session_id_fails_open(tmp_path):
    """AC3: an unregistered agent whose stdin payload carries no session_id
    at all (resolve_own_obligation cannot even attempt L1) still exits 0."""
    project, home = _project_home(tmp_path)

    proc = _run_hook(project, home, "agent-qa-r06-ac3-nosession")

    assert proc.returncode == 0, proc.stderr


def test_ac3_no_obligation_block_in_prompt_fails_open(tmp_path):
    """AC3: a resolvable transcript exists but carries no '<obligation'
    block at all (NoObligationInPrompt) -- exits 0."""
    harness_session = "harness-r06-ac3b"
    agent_id = "agent-qa-r06-ac3b"
    project, home = _project_home(tmp_path)
    _write_obligation_transcript(
        home,
        project,
        harness_session,
        agent_id,
        "Please verify this cycle's changes. No obligation block here.",
    )

    proc = _run_hook(project, home, agent_id, session_id=harness_session)

    assert proc.returncode == 0, proc.stderr


def test_ac3_role_mismatch_fails_open(tmp_path):
    """AC3: a resolvable obligation exists but declares role='dev', not
    'qa' -- resolve_own_obligation(expected_role='qa') returns
    Unresolvable(role_mismatch), and the hook still exits 0 (this agent's
    obligation is not a QA e2e obligation at all)."""
    harness_session = "harness-r06-ac3c"
    agent_id = "agent-dev-r06-ac3c"
    task_id = "20261001-161041-r06-ac3c"
    artifact_path = f"docs/dev/dev-report-{task_id}.json"
    project, home = _project_home(tmp_path)
    _write_obligation_transcript(
        home,
        project,
        harness_session,
        agent_id,
        _obligation_block(task_id, artifact_path, "dev-report.v2", role="dev"),
    )

    proc = _run_hook(project, home, agent_id, session_id=harness_session)

    assert proc.returncode == 0, proc.stderr


def test_ac3_qa_obligation_without_qa_report_artifact_fails_open(tmp_path):
    """AC3 edge case: a resolvable qa-role obligation that declares no
    qa-report.v2 artifact at all (e.g. a ba_validation-mode QA with a
    different declared schema) -- nothing to check, exits 0."""
    harness_session = "harness-r06-ac3d"
    agent_id = "agent-qa-r06-ac3d"
    task_id = "20261001-161041-r06-ac3d"
    project, home = _project_home(tmp_path)
    _write_obligation_transcript(
        home,
        project,
        harness_session,
        agent_id,
        _obligation_block(
            task_id, f"docs/dev/some-other-{task_id}.json", "some-other.v1", role="qa"
        ),
    )

    proc = _run_hook(project, home, agent_id, session_id=harness_session)

    assert proc.returncode == 0, proc.stderr


# ---------------------------------------------------------------------------
# AC4: the fallback reuses the EXISTING obligation.resolve_own_obligation,
# with the same parameter shape already used by
# subagentstop-artifact-contract-enforce.py's obligation-mode block -- no
# new resolver/fallback function invented anywhere.
# ---------------------------------------------------------------------------


def test_ac4_fallback_invokes_resolve_own_obligation_with_expected_shape(
    monkeypatch,
):
    """AC4 (code-review, exercised as a spy): the fallback calls
    obligation.resolve_own_obligation exactly once, with the keyword-arg
    shape (session_id, agent_id, project_dir, payload_agent_transcript_path,
    expected_role) already used by subagentstop-artifact-contract-enforce.py
    -- proving the fallback was actually invoked with the right shape, not
    just asserting a final exit code (right-exit-code-wrong-reason guard,
    per this ticket's Technical Hints)."""
    calls = []

    def _spy(**kwargs):
        calls.append(kwargs)
        return HOOK.obligation.NoObligationInPrompt(
            prompt="", rung="L1", transcript_path="x", cross_check="ok"
        )

    monkeypatch.setattr(HOOK.obligation, "resolve_own_obligation", _spy)

    HOOK._enforce_e2e_via_obligation(
        {"agent_id": "agent-qa-r06-ac4", "session_id": "harness-r06-ac4"},
        "agent-qa-r06-ac4",
        "/tmp/claude-test-r06-ac4-project",
    )

    assert len(calls) == 1
    kwargs = calls[0]
    assert set(kwargs) == {
        "session_id",
        "agent_id",
        "project_dir",
        "payload_agent_transcript_path",
        "expected_role",
    }
    assert kwargs["expected_role"] == "qa"
    assert kwargs["agent_id"] == "agent-qa-r06-ac4"
    assert kwargs["session_id"] == "harness-r06-ac4"
    assert kwargs["project_dir"] == "/tmp/claude-test-r06-ac4-project"


def test_ac4_agent_resolver_unmodified_by_this_fix():
    """AC4: hooks/lib/agent_resolver.py gained no new resolver/fallback
    function as part of this fix -- resolve_dev_registry_entry and its
    pre-existing private cp-state-scan helpers are exactly the function set
    that existed before this ticket touched anything. The fallback logic
    lives entirely in subagentstop-e2e-enforce.py and calls
    obligation.resolve_own_obligation directly (see the AC4 spy test
    above) rather than adding a new wrapper anywhere."""
    resolver_src = (REPO_ROOT / "hooks" / "lib" / "agent_resolver.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(resolver_src)
    top_level_funcs = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    baseline_funcs = {
        "_checked_in_age_seconds",
        "_is_stale",
        "_read_json",
        "_match_cp_state",
        "_read_match",
        "_pick_active",
        "_lookup_dev_registry_index",
        "resolve_dev_registry_entry",
        "_glob_cp_state",
        "_scan_cp_state_files",
        "_resolve_by_id",
        "resolve_agent_type",
    }
    assert top_level_funcs == baseline_funcs


# ---------------------------------------------------------------------------
# AC5: the pre-existing registered-agent path stays byte-identical -- the
# fallback is additive only and never alters the registered path's exit
# codes or stderr text.
# ---------------------------------------------------------------------------


def test_ac5_registered_missing_report_message_unchanged(tmp_path):
    """AC5: a REGISTERED qa agent with a missing qa-report still produces
    the exact pre-fix E2E_ENFORCE_BLOCKED/no-report message and exit 2."""
    dev_session_id = "dev-20260101-000000"
    agent_id = "agent-qa-r06-ac5-missing"
    project, home = _project_home(tmp_path)
    _register_agent(project, agent_id, dev_session_id, "qa")
    _enable_e2e_enforcement(project, dev_session_id)
    _write(
        project / ".claude" / "dev-registry" / dev_session_id / "qa.json",
        {"agent_type": "qa", "session_id": dev_session_id},
    )

    proc = _run_hook(project, home, agent_id)

    assert proc.returncode == 2
    assert proc.stderr == (
        f"E2E_ENFORCE_BLOCKED: agent {agent_id} (type=qa) has no "
        f"qa-report-*.json in {project}/docs/dev/ under session {dev_session_id}.\n"
        f"QA must produce a report with e2e_enforcement.status before stopping.\n"
    )


def test_ac5_registered_unjustified_skip_message_unchanged(tmp_path):
    """AC5: a REGISTERED qa agent with a report whose e2e_enforcement.status
    is the unjustified-skip value still produces the exact pre-fix
    'in session <sid>' message text and exit 2."""
    dev_session_id = "dev-20260202-000000"
    agent_id = "agent-qa-r06-ac5-skip"
    task_id = "20260202-000000"
    project, home = _project_home(tmp_path)
    _register_agent(project, agent_id, dev_session_id, "qa")
    _enable_e2e_enforcement(project, dev_session_id)
    _write(
        project / ".claude" / "dev-registry" / dev_session_id / "qa.json",
        {"agent_type": "qa", "session_id": dev_session_id},
    )
    _write(
        project / "docs" / "dev" / f"qa-report-{task_id}.json",
        _qa_report(task_id, status="skipped_without_justification"),
    )

    proc = _run_hook(project, home, agent_id)

    assert proc.returncode == 2
    report_path = project / "docs" / "dev" / f"qa-report-{task_id}.json"
    assert proc.stderr == (
        f"QA_REPORT_RESOLUTION: path={report_path} branch=session_ts_filename_match\n"
        f"E2E_ENFORCE_BLOCKED: agent {agent_id} (type=qa) in session "
        f"{dev_session_id} has e2e_enforcement.status='skipped_without_justification'.\n"
        f"blocking_reason: (none provided)\n"
        f"E2E verification is required. Perform E2E testing and update "
        f"e2e_enforcement.status to 'performed', 'legitimately_skipped', "
        f"'blocked_app_unavailable', or 'ran' before stopping.\n"
    )


def test_ac5_registered_passing_status_exit0_unchanged(tmp_path):
    """AC5: a REGISTERED qa agent with a passing status still exits 0."""
    dev_session_id = "dev-20260303-000000"
    agent_id = "agent-qa-r06-ac5-pass"
    task_id = "20260303-000000"
    project, home = _project_home(tmp_path)
    _register_agent(project, agent_id, dev_session_id, "qa")
    _enable_e2e_enforcement(project, dev_session_id)
    _write(
        project / ".claude" / "dev-registry" / dev_session_id / "qa.json",
        {"agent_type": "qa", "session_id": dev_session_id},
    )
    _write(
        project / "docs" / "dev" / f"qa-report-{task_id}.json",
        _qa_report(task_id, status="performed"),
    )

    proc = _run_hook(project, home, agent_id)

    assert proc.returncode == 0, proc.stderr


def test_ac5_registered_path_never_consults_obligation_module(tmp_path, monkeypatch):
    """AC5 (spy direction): _enforce_e2e_via_obligation (the fallback entry
    point) is only ever reached from main() when resolve_dev_registry_entry()
    returns None -- it is never called on the registered-agent path. Direct
    unit check of that control-flow invariant, independent of subprocess
    message assertions above."""
    calls = []
    monkeypatch.setattr(
        HOOK, "_enforce_e2e_via_obligation", lambda *a, **k: calls.append((a, k))
    )
    monkeypatch.setattr(
        HOOK,
        "resolve_dev_registry_entry",
        lambda *_a, **_k: {"agent_type": "qa", "dev_session_id": "dev-20260505-000000"},
    )
    dev_session_id = "dev-20260505-000000"
    task_id = "20260505-000000"
    project, home = _project_home(tmp_path)
    _enable_e2e_enforcement(project, dev_session_id)
    _write(
        project / ".claude" / "dev-registry" / dev_session_id / "qa.json",
        {"agent_type": "qa", "session_id": dev_session_id},
    )
    _write(
        project / "docs" / "dev" / f"qa-report-{task_id}.json",
        _qa_report(task_id, status="performed"),
    )
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setattr(HOOK, "_load_stdin", lambda: {"agent_id": "agent-qa-r06-ac5-spy"})

    with pytest.raises(SystemExit) as excinfo:
        HOOK.main()

    assert excinfo.value.code == 0
    assert calls == []
