#!/usr/bin/env python3
"""Tests for hooks/subagentstop-e2e-enforce.py: which QA report a stopping QA
is judged on.

- A QA whose dispatch carries an obligation (ticket 20261001-161041-r06, P1b
  E7, P1c R10) is judged on exactly the qa-report.v2 it declares, at the path
  declared, whatever the registry holds (no agent-index entry) and whatever
  form the session id takes; a stale report beside it is never read (F3b).
- A QA whose dispatch carries none, bound to a cycle's registry (its
  agent-index entry), is judged on the qa-reports its own transcript shows it
  wrote (command_span.write_set), never the newest file of the session or a
  sibling's (R10); the gate has no flag to read.
- Every other stop (no session_id, no obligation and no cycle registry entry,
  a role other than qa, a qa obligation declaring no qa-report.v2) exits 0.

Models hooks/tests/test_artifact_contract_enforce.py's fixture and
invocation patterns (importlib for the hyphenated module under test,
subprocess with CLAUDE_PROJECT_DIR/HOME, the obligation-transcript fixture
helpers).
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
    # Transcripts live in the configuration directory; pin it to this HOME.
    env["CLAUDE_CONFIG_DIR"] = str(Path(home_dir) / ".claude")
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


def test_ac4_own_dispatch_invokes_resolve_own_obligation_with_expected_shape(
    monkeypatch,
):
    """AC4 (exercised as a spy): the QA's own dispatch is read through
    obligation.resolve_own_obligation, called exactly once with the
    keyword-arg shape subagentstop-artifact-contract-enforce.py uses; no
    expected_role (the stopping agent's type decides that, R10), and the
    transcript the resolver found is the one handed back."""
    calls = []

    def _spy(**kwargs):
        calls.append(kwargs)
        return HOOK.obligation.NoObligationInPrompt(
            prompt="", rung="L1", transcript_path="x", cross_check="ok"
        )

    monkeypatch.setattr(HOOK.obligation, "resolve_own_obligation", _spy)

    declared, transcript = HOOK._own_dispatch(
        {"agent_id": "agent-qa-r06-ac4", "session_id": "harness-r06-ac4"},
        "agent-qa-r06-ac4",
        "/tmp/claude-test-r06-ac4-project",
    )

    assert (declared, transcript) == ({}, "x")
    assert len(calls) == 1
    kwargs = calls[0]
    assert set(kwargs) == {
        "session_id",
        "agent_id",
        "project_dir",
        "payload_agent_transcript_path",
    }
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
        # P1b row 8: the one cp-state running rule subagentstop-cp-enforce.py shares.
        "cp_state_running",
    }
    assert top_level_funcs == baseline_funcs


# ---------------------------------------------------------------------------
# R10 (P1c): a dispatch without an obligation, of a QA a cycle's registry
# holds, is judged on the QA reports its own transcript shows it wrote, never on the
# newest file of the session or a sibling's; every message names the report's
# path and the field.
# ---------------------------------------------------------------------------


def _write_qa_transcript(home, project, session, agent_id, prompt, paths):
    """The QA's transcript: its dispatch prompt, then one Write per path with
    an ok tool_result (the record the CLI keeps of the agent's own calls)."""
    _write_obligation_transcript(home, project, session, agent_id, prompt)
    slug = _project_slug(project)
    tpath = home / ".claude" / "projects" / slug / session / "subagents" / f"agent-{agent_id}.jsonl"
    with tpath.open("a", encoding="utf-8") as fh:
        for k, rel in enumerate(paths):
            use = f"toolu_r10_{agent_id}_{k}"
            fh.write(json.dumps({"type": "assistant", "cwd": str(project), "message": {"content": [
                {"type": "tool_use", "id": use, "name": "Write",
                 "input": {"file_path": str(project / rel), "content": "{}"}}]}}) + "\n")
            fh.write(json.dumps({"type": "user", "cwd": str(project), "message": {"content": [
                {"type": "tool_result", "tool_use_id": use, "content": "ok"}]}}) + "\n")


def _registered_qa(tmp_path, dev_session_id, agent_id, session, writes=()):
    project, home = _project_home(tmp_path)
    _register_agent(project, agent_id, dev_session_id, "qa")
    _write_qa_transcript(home, project, session, agent_id, "Verify this cycle. No obligation block.", writes)
    return project, home


def test_r10_registered_qa_that_wrote_no_report_blocks(tmp_path):
    """A QA that wrote no qa-report is blocked, even with another agent's
    report of the session on disk (the newest-filename correlation is gone)."""
    dev_session_id = "dev-20260101-000000"
    agent_id = "agent-qa-r10-none"
    project, home = _registered_qa(tmp_path, dev_session_id, agent_id, "harness-r10-none")
    _write(project / "docs" / "dev" / "qa-report-20260101-000000.json",
           _qa_report("20260101-000000", status="performed"))

    proc = _run_hook(project, home, agent_id, session_id="harness-r10-none")

    assert proc.returncode == 2
    assert proc.stderr == (
        f"E2E_ENFORCE_BLOCKED: agent {agent_id} (type=qa) wrote no "
        f"docs/dev/qa-report-*.json (in session {dev_session_id}).\n"
        f"QA must produce a report with e2e_enforcement.status before stopping.\n"
    )


def test_r10_registered_qa_judged_on_the_report_it_wrote_not_a_siblings(tmp_path):
    """Its own report passes: a sibling's unjustified skip beside it is not
    this QA's; its own unjustified skip blocks, naming its path and field."""
    dev_session_id = "dev-20260202-000000"
    agent_id = "agent-qa-r10-own"
    own = "docs/dev/qa-report-20260202-000000-l1.json"
    sibling = "docs/dev/qa-report-20260202-000000-l2.json"
    project, home = _registered_qa(tmp_path, dev_session_id, agent_id, "harness-r10-own", [own])
    _write(project / own, _qa_report("20260202-000000-l1", status="performed"))
    _write(project / sibling, _qa_report("20260202-000000-l2", status="skipped_without_justification"))

    proc = _run_hook(project, home, agent_id, session_id="harness-r10-own")
    assert proc.returncode == 0, proc.stderr

    _write(project / own, _qa_report("20260202-000000-l1", status="skipped_without_justification"))
    proc = _run_hook(project, home, agent_id, session_id="harness-r10-own")
    assert proc.returncode == 2
    assert str(project / own) in proc.stderr and sibling not in proc.stderr
    assert "e2e_enforcement.status='skipped_without_justification'" in proc.stderr


def test_r10_declared_path_beside_a_stale_unsuffixed_report(tmp_path):
    """F3b: a fan-out lane QA's obligation declares its lane report; a stale
    v1 qa-report at the parent's unsuffixed path is nobody's here. The lane
    passes on its own report; missing, it is blocked naming the declared path,
    never the stale one; at any registry state (no agent-index entry)."""
    session = "harness-r10-f3b"
    agent_id = "agent-qa-r10-f3b"
    task = "20260303-000000"
    declared = f"docs/dev/qa-report-{task}-l1.json"
    stale = f"docs/dev/qa-report-{task}.json"
    project, home = _project_home(tmp_path)
    _write_obligation_transcript(home, project, session, agent_id,
                                 _obligation_block(f"{task}-l1", declared, "qa-report.v2"))
    _write(project / stale, {"schema_version": "1.0", "task_id": task, "status": "fail"})

    proc = _run_hook(project, home, agent_id, session_id=session)
    assert proc.returncode == 2
    assert declared in proc.stderr and stale not in proc.stderr
    assert "no such file exists" in proc.stderr

    _write(project / declared, _qa_report(f"{task}-l1", status="performed"))
    proc = _run_hook(project, home, agent_id, session_id=session)
    assert proc.returncode == 0, proc.stderr


def test_r10_obligation_decides_alone_in_a_registered_session(tmp_path):
    """An obligation-bearing QA registered under a session id of an overnight
    id's form is still judged on its declared report."""
    session = "harness-r10-noflag"
    agent_id = "agent-qa-r10-noflag"
    task = "20260404-000000"
    declared = f"docs/dev/qa-report-{task}.json"
    project, home = _project_home(tmp_path)
    _register_agent(project, agent_id, "overnight-20260404-000000", "qa")
    _write_obligation_transcript(home, project, session, agent_id,
                                 _obligation_block(task, declared, "qa-report.v2"))
    _write(project / declared, {"task_id": task, "qa": {"status": "pass"}})

    proc = _run_hook(project, home, agent_id, session_id=session)

    assert proc.returncode == 2
    assert str(project / declared) in proc.stderr
    assert "has no e2e_enforcement field" in proc.stderr


def test_r10_a_non_qa_stop_is_never_judged(tmp_path):
    """The stopping agent's type decides: a dev whose transcript wrote a QA
    report is not judged here."""
    project, home = _project_home(tmp_path)
    _register_agent(project, "agent-dev-r10", "dev-20260505-000000", "dev")
    _write_qa_transcript(home, project, "harness-r10-dev", "agent-dev-r10", "dev work",
                         ["docs/dev/qa-report-20260505-000000.json"])
    _write(project / "docs" / "dev" / "qa-report-20260505-000000.json",
           _qa_report("20260505-000000", status="skipped_without_justification"))

    proc = _run_hook(project, home, "agent-dev-r10", session_id="harness-r10-dev")

    assert proc.returncode == 0, proc.stderr


def test_p4_r8_force_sentinel_changes_nothing(tmp_path, monkeypatch):
    """P4 R8 (A12): a /close --force sentinel (claude-close-force-<session>.flag,
    where the earlier hook looked for it) skips nothing: a registered QA's
    declared report with an unjustified skip still blocks."""
    session, agent_id, task = "harness-p4-force", "agent-qa-p4-force", "20260606-000000"
    declared = f"docs/dev/qa-report-{task}.json"
    project, home = _project_home(tmp_path)
    _register_agent(project, agent_id, f"dev-{task}", "qa")
    _write_obligation_transcript(home, project, session, agent_id,
                                 _obligation_block(task, declared, "qa-report.v2"))
    _write(project / declared, _qa_report(task, status="skipped_without_justification"))
    for name, root in (("CLAUDE_STATE_DIR", tmp_path / "state"), ("TMPDIR", tmp_path / "tmp")):
        _write(root / f"claude-close-force-dev-{task}.flag", "")
        monkeypatch.setenv(name, str(root))

    proc = _run_hook(project, home, agent_id, session_id=session)

    assert proc.returncode == 2
    assert "E2E_ENFORCE_BLOCKED" in proc.stderr


def test_write_e2e_enforce_is_an_exit_0_stub_that_writes_nothing(tmp_path):
    """scripts/write-e2e-enforce.sh (P1c): the gate has no flag, so the call earlier /dev, /dev-command
    and /dev-overnight text makes (`write-e2e-enforce.sh <session-id>`) exits 0 and writes no
    e2e-enforce.json; with no argument too."""
    stub = Path(__file__).resolve().parents[2] / "scripts" / "write-e2e-enforce.sh"
    assert sum(line.startswith("# STUB:") for line in stub.read_text().splitlines()) == 1
    assert stub.stat().st_mode & 0o100, "the earlier text executes it by path"
    project = tmp_path / "project"
    project.mkdir()
    env = {"PATH": "/usr/bin:/bin", "CLAUDE_PROJECT_DIR": str(project), "HOME": str(tmp_path)}
    for args in (["dev-20260101-000000"], []):
        done = subprocess.run([str(stub), *args], capture_output=True, text=True, env=env)
        assert (done.returncode, done.stdout, done.stderr) == (0, "", "")
    assert list(project.rglob("*")) == []


if __name__ == "__main__":
    sys.exit(subprocess.run([sys.executable, "-m", "pytest", __file__, "-v"]).returncode)
