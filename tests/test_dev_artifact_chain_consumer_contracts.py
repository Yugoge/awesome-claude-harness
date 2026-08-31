"""Static consumer mappings for the admitted R1 provider/result contract."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CALLER_LITERAL = "You are the dev subagent. Follow agents/dev.md instructions precisely."
EXPECTED_CALLERS = {"commands/dev.md", "commands/dev-command.md", "commands/dev-overnight.md"}


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _block005_modules():
    hook = _load_module("r1_block005_hook", ROOT / "hooks/pretool-aggregate-check.py")
    helper = _load_module("r1_block005_helpers", ROOT / "tests/test_aggregate_dev_report.py")
    return hook, helper


def _write_parallel_or_fanout_phase(root: Path, helper, shape: str, state: str):
    """Create a digest-valid current parent at dev_completed or awaiting_qa."""
    declaration, paths = helper.make_final_chain(root, shape)
    if state == "qa_pass":
        return declaration, paths
    phase_version = {"dev_completed": 1, "awaiting_qa": 2}[state]
    candidate = copy.deepcopy(declaration)
    events = [
        event for event in candidate["phase_projection"]["events"]
        if event["phase_version"] <= phase_version
    ]
    members = []
    for member in candidate["phase_projection"]["members"]:
        evidence = member["attempt_ledger"][-1]["artifact_sha256"]
        members.append({**member, "state": state, "evidence_digest": evidence})
    candidate["phase_projection"] = {
        "phase_version": phase_version,
        "members": members,
        "events": events,
        "phase_digest": "",
    }
    candidate["active_roster"] = [
        {"ordinal": index, "member_id": member["member_id"], "state": state, "attempt": 1}
        for index, member in enumerate(candidate["member_lineage"])
    ]
    candidate = helper.AGG.finalize_declaration(candidate)
    current = json.loads(paths["canonical"].read_text(encoding="utf-8"))
    sources = []
    for member in candidate["member_lineage"]:
        relative = member["artifact_paths"]["dev_report"]
        raw = (root / relative).read_bytes()
        sources.append((member["member_id"], json.loads(raw), raw))
    helper.write_json(
        paths["canonical"],
        helper.AGG._build_aggregate(
            sources, helper.TASK, candidate, timestamp=current.get("timestamp"),
        ),
    )
    return candidate, paths


def _write_parallel_attempt2_awaiting(root: Path, helper):
    """Create a lawful immutable attempt-2 current parent and retain attempt 1."""
    declaration, paths = helper.make_final_chain(root, "parallel_dev")
    canonical = paths["canonical"]
    parent_document = json.loads(canonical.read_text(encoding="utf-8"))
    first, sibling = declaration["member_lineage"]
    first_id, sibling_id = first["member_id"], sibling["member_id"]

    needs = copy.deepcopy(declaration)
    prefix = [event for event in needs["phase_projection"]["events"] if event["phase_version"] < 3]
    pre_members = []
    for member in needs["phase_projection"]["members"]:
        evidence = member["attempt_ledger"][-1]["artifact_sha256"]
        pre_members.append({**member, "state": "awaiting_qa", "evidence_digest": evidence})
    pre_digest = helper.AGG._digest({
        "lineage_digest": needs["lineage_digest"], "phase_version": 2,
        "members": pre_members, "events": prefix,
    })
    outcomes = {
        "schema_version": helper.AGG.OUTCOMES_VERSION,
        "parent_task_id": helper.TASK,
        "lineage_digest": needs["lineage_digest"],
        "phase_digest_before": pre_digest,
        "coverage": "all", "default_outcome": None,
        "worker_outcomes": [
            {"member_id": first_id, "outcome": "needs_review"},
            {"member_id": sibling_id, "outcome": "pass"},
        ],
    }
    qa_path = root / f"docs/dev/qa-report-{helper.TASK}.json"
    qa_raw = helper.write_json(
        qa_path, helper.qa_report(helper.TASK, outcomes=outcomes, status="needs_review"),
    )
    qa_digest = helper.AGG._bytes_digest(qa_raw)
    needs["phase_projection"] = {
        "phase_version": 3,
        "members": [
            {**pre_members[0], "state": "needs_review", "evidence_digest": qa_digest},
            {**pre_members[1], "state": "qa_pass", "evidence_digest": qa_digest},
        ],
        "events": prefix + [
            {"phase_version": 3, "event_ordinal": 0, "member_id": first_id, "from_state": "awaiting_qa", "to_state": "needs_review", "attempt": 1, "evidence_digest": qa_digest, "superseded_by": None, "coverage_disposition": None},
            {"phase_version": 3, "event_ordinal": 1, "member_id": sibling_id, "from_state": "awaiting_qa", "to_state": "qa_pass", "attempt": 1, "evidence_digest": qa_digest, "superseded_by": None, "coverage_disposition": None},
        ],
        "phase_digest": "",
    }
    needs["active_roster"] = [
        {"ordinal": 0, "member_id": first_id, "state": "needs_review", "attempt": 1},
        {"ordinal": 1, "member_id": sibling_id, "state": "qa_pass", "attempt": 1},
    ]
    needs = helper.AGG.finalize_declaration(needs)

    retry_path = f"docs/dev/dev-report-iter2-{helper.TASK}-{first_id}.json"
    reserved = copy.deepcopy(needs)
    target = reserved["phase_projection"]["members"][0]
    target["attempt_reservations"].append({
        "schema_version": "attempt_reservation.v1", "attempt": 2,
        "artifact_path": retry_path, "expected_absent": True,
        "reserved_at_phase_version": 4,
    })
    target.update(state="retry_dispatched", attempt=2, evidence_digest="sha256:" + "e" * 64)
    reserved["phase_projection"]["events"].append({
        "phase_version": 4, "event_ordinal": 0, "member_id": first_id,
        "from_state": "needs_review", "to_state": "retry_dispatched", "attempt": 2,
        "evidence_digest": "sha256:" + "e" * 64,
        "superseded_by": None, "coverage_disposition": None,
    })
    reserved["phase_projection"]["phase_version"] = 4
    reserved["active_roster"][0].update(state="retry_dispatched", attempt=2)
    reserved = helper.AGG.finalize_declaration(reserved)

    retry_report = helper.dev_report(first_id, binding={
        "parent_task_id": helper.TASK, "member_id": first_id,
        "lineage_digest": reserved["lineage_digest"], "attempt": 2,
    })
    retry_raw = helper.write_json(root / retry_path, retry_report)
    _, retry_stable = helper.AGG.stable_dev_projection(retry_report)
    ledger2 = {
        "schema_version": "attempt_ledger_record.v1", "record_kind": "immutable_member",
        "attempt": 2, "artifact_path": retry_path,
        "artifact_sha256": helper.AGG._bytes_digest(retry_raw),
        "stable_projection_sha256": retry_stable,
        "completed_at_phase_version": 5,
    }
    promoted = copy.deepcopy(reserved)
    target = promoted["phase_projection"]["members"][0]
    target["attempt_ledger"].append(ledger2)
    target.update(state="dev_completed", current_attempt=2, evidence_digest=ledger2["artifact_sha256"])
    promoted["phase_projection"]["events"].append({
        "phase_version": 5, "event_ordinal": 0, "member_id": first_id,
        "from_state": "retry_dispatched", "to_state": "dev_completed", "attempt": 2,
        "evidence_digest": ledger2["artifact_sha256"],
        "superseded_by": None, "coverage_disposition": None,
    })
    promoted["phase_projection"]["phase_version"] = 5
    promoted["active_roster"][0].update(state="dev_completed")
    promoted = helper.AGG.finalize_declaration(promoted)

    awaiting = copy.deepcopy(promoted)
    awaiting["phase_projection"]["members"][0].update(state="awaiting_qa")
    awaiting["phase_projection"]["events"].append({
        "phase_version": 6, "event_ordinal": 0, "member_id": first_id,
        "from_state": "dev_completed", "to_state": "awaiting_qa", "attempt": 2,
        "evidence_digest": ledger2["artifact_sha256"],
        "superseded_by": None, "coverage_disposition": None,
    })
    awaiting["phase_projection"]["phase_version"] = 6
    awaiting["active_roster"][0].update(state="awaiting_qa")
    awaiting = helper.AGG.finalize_declaration(awaiting)

    sibling_path = sibling["artifact_paths"]["dev_report"]
    sibling_raw = (root / sibling_path).read_bytes()
    helper.write_json(
        canonical,
        helper.AGG._build_aggregate(
            [
                (first_id, retry_report, retry_raw),
                (sibling_id, json.loads(sibling_raw), sibling_raw),
            ],
            helper.TASK, awaiting, timestamp=parent_document.get("timestamp"),
        ),
    )
    return awaiting, paths, first["artifact_paths"]["dev_report"], retry_path


def _hook_process(project: Path, prompt: str) -> subprocess.CompletedProcess[str]:
    data = {
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "qa", "prompt": prompt},
        "session_id": f"r1-block005-{os.getpid()}-{project.name}",
    }
    env = dict(os.environ)
    env.update(
        CLAUDE_PROJECT_DIR=str(project),
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONPYCACHEPREFIX="/tmp/r1-block005-hook-process-pycache",
    )
    return subprocess.run(
        [sys.executable, str(ROOT / "hooks/pretool-aggregate-check.py")],
        input=json.dumps(data), text=True, capture_output=True, env=env,
    )


def test_shared_dev_agent_caller_inventory_is_closed_and_classified() -> None:
    callers = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "commands").glob("*.md")
        if CALLER_LITERAL in path.read_text(encoding="utf-8")
    }
    assert callers == EXPECTED_CALLERS
    dev = read("commands/dev.md")
    command = read("commands/dev-command.md")
    overnight = read("commands/dev-overnight.md")
    assert "artifact_chain_role: <lifecycle_singular_parent|lifecycle_declared_member" in dev
    assert "artifact_chain_role: lifecycle_singular_parent" in command
    assert "artifact_chain_role: overnight_pipeline_intermediate" in overnight
    assert "artifact_chain_declaration: null" in overnight


def test_agent_preserves_terminal_schema_projection_and_adds_conditional_r1_fields() -> None:
    text = read("agents/dev.md")
    assert "`report_version` is the literal integer `1`, never a string or boolean" in text
    assert '"report_version": 1' in text
    assert "lifecycle_singular_parent" in text
    assert "lifecycle_declared_member" in text
    assert "overnight_pipeline_intermediate" in text
    assert "stable_dev_projection.v1" in text
    assert "mutable-singular records forbid a full canonical hash" in text


def test_dev_declares_three_shapes_and_uses_v2_relationships() -> None:
    text = read("commands/dev.md")
    for value in ("`singular`", "`parallel_dev`", "`requirement_fanout`"):
        assert value in text
    assert "Shape is never derived from `parallel_workers`, filenames, globs" in text
    assert "--validate-declaration-only" in text
    assert "--expected-canonical-sha256" in text
    assert "--expected-phase-digest" in text
    assert "--report-file" in text
    assert "parallel_dev_worker_outcomes.v1" in text
    assert "`awaiting_qa` or already\n`qa_pass`" in text
    assert 'schema_version == "artifact_chain_result.v2"' in text
    for field in ("shape", "parent", "lanes", "excluded_lanes", "report_paths", "qa_inputs", "commit_whitelist_artifacts"):
        assert f"`{field}`" in text
    assert "Retries are never accepted from an optional filename convention" in text


def test_close_preflights_before_any_writer_and_refreshes_existing_parallel_only() -> None:
    text = read("commands/close.md")
    section = text[text.index("### Step 0:"):text.index("### do-report lite preflight")]
    assert section.index("--preflight-parent") < section.index("scripts/aggregate-dev-report.py")
    assert "PARENT_TASK_ID_REQUIRED" in section
    assert "before any aggregate call" in section
    assert "shape=singular` performs zero aggregate calls" in section
    assert "--declaration-from-canonical" in section
    assert "--expected-canonical-sha256" in section
    assert "--expected-phase-digest" in section
    assert "normal close never synthesizes a candidate or creates a missing canonical" in " ".join(section.split())
    assert section.index("scripts/aggregate-dev-report.py") < section.rindex("scripts/resolve-dev-artifact-chain.py")


def test_close_uses_exact_shape_parent_lane_and_qa_mappings() -> None:
    text = read("commands/close.md")
    for field in ("shape", "parent", "lanes", "excluded_lanes", "qa_inputs"):
        assert f"`{field}`" in text or f"ARTIFACT_CHAIN.{field}" in text
    assert '`shape == "parallel_dev"`' in text
    assert '`shape == "requirement_fanout"`' in text
    assert "Record the supplied `shape`, `parent`, `lanes`, `excluded_lanes`, and `qa_inputs` verbatim" in text
    assert "exactly one parent close decision" in text


def test_commit_is_validation_only_child_fail_closed_and_parent_resolver_consumer() -> None:
    text = read("commands/commit.md")
    assert hashlib.sha256((ROOT / "commands/commit.md").read_bytes()).hexdigest() == "695b82ef24dbf985b72c6207c11b8ae67bad0cb5bf6f451dc411baae19b27bb8"
    close_gate = text.index("### Step 3: Close-gate validation")
    resolver = text.index("scripts/resolve-dev-artifact-chain.py", close_gate)
    assert close_gate < resolver
    assert "Close-gate: no close-report" in text[close_gate:resolver]
    assert "ARTIFACT_CHAIN.commit_whitelist_artifacts" in text


def test_no_authorized_consumer_claims_per_member_close() -> None:
    combined = "\n".join(read(path) for path in EXPECTED_CALLERS | {"commands/close.md", "agents/dev.md"})
    assert "one parent close" in combined
    assert "one parent `/close`" in combined or "one parent close decision" in combined
    assert "close-report-<lane" not in combined
    assert "/close <lane" not in combined


def test_phase_aware_hook_uses_only_explicit_exact_reports(tmp_path: Path) -> None:
    import importlib.util
    import json
    import sys

    hook_path = ROOT / "hooks" / "pretool-aggregate-check.py"
    spec = importlib.util.spec_from_file_location("r1_aggregate_hook_test", hook_path)
    assert spec and spec.loader
    hook = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = hook
    spec.loader.exec_module(hook)

    docs = tmp_path / "docs/dev"
    docs.mkdir(parents=True)
    member = "20260810-120000-r1-worker.full"
    relative = f"docs/dev/dev-report-{member}.json"
    report = {
        "request_id": member, "task_id": member,
        "artifact_chain_role": "lifecycle_declared_member",
        "artifact_chain_binding": {
            "parent_task_id": "20260810-120000-r1-parent.full",
            "member_id": member, "lineage_digest": "sha256:" + "a" * 64,
            "attempt": 1,
        },
        "dev": {"status": "completed"},
    }
    (tmp_path / relative).write_text(json.dumps(report), encoding="utf-8")
    # Lane QA is allowed before the parent canonical exists; unrelated history
    # is never globally scanned and the full suffixed identity is not truncated.
    assert hook._inspect_dispatch(tmp_path, f"Read {relative}") == []
    violations = hook._inspect_dispatch(tmp_path, "Read docs/dev/dev-report-20260810-120000-r1-missing.full.json")
    assert violations[0]["code"] == "MISSING_ARTIFACT"

    # A parallel parent-QA prompt names both the parent canonical and worker
    # reports. It is parent-scoped (not mistaken for lane QA), and the hook
    # recomputes immutable evidence/canonical freshness before allowing it.
    helper_path = ROOT / "tests" / "test_aggregate_dev_report.py"
    helper_spec = importlib.util.spec_from_file_location("r1_hook_helpers", helper_path)
    assert helper_spec and helper_spec.loader
    helper = importlib.util.module_from_spec(helper_spec)
    sys.modules[helper_spec.name] = helper
    helper_spec.loader.exec_module(helper)
    project = tmp_path / "parallel-project"
    declaration, _ = helper.make_final_chain(project, "parallel_dev")
    canonical = f"docs/dev/dev-report-{helper.TASK}.json"
    worker_paths = [member["artifact_paths"]["dev_report"] for member in declaration["member_lineage"]]
    prompt = "Inspect " + " ".join([canonical, *worker_paths])
    assert hook._inspect_dispatch(project, prompt) == []
    worker = project / worker_paths[0]
    changed = json.loads(worker.read_text())
    changed["unexpected_mutation"] = True
    helper.write_json(worker, changed)
    violations = hook._inspect_dispatch(project, prompt)
    assert any(item["code"] == "STALE_CANONICAL" for item in violations)


def test_worker_only_prompt_recomputes_existing_parent_and_matches_explicit_scope(
    tmp_path: Path,
) -> None:
    hook, helper = _block005_modules()
    declaration, paths = helper.make_final_chain(tmp_path, "parallel_dev")
    canonical = f"docs/dev/dev-report-{helper.TASK}.json"
    workers = [member["artifact_paths"]["dev_report"] for member in declaration["member_lineage"]]
    target = tmp_path / workers[0]
    changed = json.loads(target.read_text(encoding="utf-8"))
    changed["tampered_after_qa_pass"] = True
    helper.write_json(target, changed)
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*") if path.is_file() and not path.is_symlink()
    }

    worker_only = hook._inspect_dispatch(tmp_path, f"Inspect {workers[0]}")
    explicit = hook._inspect_dispatch(tmp_path, "Inspect " + " ".join([canonical, *workers]))
    assert any(
        error["code"] == "STALE_CANONICAL" and error["path"] == workers[0]
        for error in worker_only
    )
    assert any(error["code"] == "STALE_CANONICAL" for error in explicit)
    assert {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*") if path.is_file() and not path.is_symlink()
    } == before
    assert paths["canonical"].read_bytes() == before[canonical]


@pytest.mark.parametrize("shape", ["parallel_dev", "requirement_fanout"])
def test_worker_only_prompt_with_intact_current_parent_is_allowed_after_revalidation(
    tmp_path: Path, shape: str,
) -> None:
    hook, helper = _block005_modules()
    declaration, paths = _write_parallel_or_fanout_phase(tmp_path, helper, shape, "awaiting_qa")
    worker = declaration["member_lineage"][0]["artifact_paths"]["dev_report"]
    before = paths["canonical"].read_bytes()
    assert hook._inspect_dispatch(tmp_path, f"Inspect {worker}") == []
    assert paths["canonical"].read_bytes() == before


@pytest.mark.parametrize("shape", ["parallel_dev", "requirement_fanout"])
def test_genuine_preparent_worker_only_qa_remains_allowed_without_global_lookup(
    tmp_path: Path, shape: str,
) -> None:
    hook, helper = _block005_modules()
    declaration, paths = helper.make_final_chain(tmp_path, shape)
    worker = declaration["member_lineage"][0]["artifact_paths"]["dev_report"]
    paths["canonical"].unlink()
    unrelated = tmp_path / f"docs/dev/dev-report-{helper.TASK}-suffix-collision.json"
    unrelated.write_text("{not-json", encoding="utf-8")
    foreign = tmp_path.parent / f"{tmp_path.name}-foreign-root"
    (foreign / "docs/dev").mkdir(parents=True)
    (foreign / f"docs/dev/dev-report-{helper.TASK}.json").write_text("{}", encoding="utf-8")
    before = (tmp_path / worker).read_bytes()
    assert hook._inspect_dispatch(tmp_path, f"Inspect {worker}") == []
    assert (tmp_path / worker).read_bytes() == before
    assert unrelated.read_text(encoding="utf-8") == "{not-json"


def test_singular_parent_scope_remains_valid_and_does_not_infer_members(tmp_path: Path) -> None:
    hook, helper = _block005_modules()
    _, paths = helper.make_final_chain(tmp_path, "singular")
    canonical = f"docs/dev/dev-report-{helper.TASK}.json"
    before = paths["canonical"].read_bytes()
    assert hook._inspect_dispatch(tmp_path, f"Inspect {canonical}") == []
    assert paths["canonical"].read_bytes() == before


def test_existing_invalid_exact_parent_never_downgrades_to_preparent_allowance(tmp_path: Path) -> None:
    hook, helper = _block005_modules()
    expected_codes = {
        "malformed": {"INVALID_DECLARATION"},
        "declarationless": {"MISSING_DECLARATION"},
        "wrong-parent": {"INVALID_IDENTITY"},
        "wrong-lineage": {"INVALID_IDENTITY", "LINEAGE_DIGEST_MISMATCH", "DECLARATION_DIGEST_MISMATCH"},
        "symlink": {"INVENTORY_MISMATCH"},
        "directory": {"INVENTORY_MISMATCH"},
    }
    for case, wanted in expected_codes.items():
        project = tmp_path / case
        declaration, paths = _write_parallel_or_fanout_phase(project, helper, "parallel_dev", "awaiting_qa")
        worker = declaration["member_lineage"][0]["artifact_paths"]["dev_report"]
        canonical = paths["canonical"]
        if case == "malformed":
            canonical.write_bytes(b'{"unterminated":')
        elif case == "declarationless":
            document = json.loads(canonical.read_text(encoding="utf-8"))
            document.pop("artifact_chain_declaration")
            helper.write_json(canonical, document)
        elif case == "wrong-parent":
            document = json.loads(canonical.read_text(encoding="utf-8"))
            document["artifact_chain_declaration"]["parent_task_id"] += "-other"
            helper.write_json(canonical, document)
        elif case == "wrong-lineage":
            document = json.loads(canonical.read_text(encoding="utf-8"))
            document["artifact_chain_declaration"]["lineage_digest"] = "sha256:" + "f" * 64
            helper.write_json(canonical, document)
        elif case == "symlink":
            outside = tmp_path / f"{case}-outside.json"
            outside.write_text("{}", encoding="utf-8")
            canonical.unlink()
            canonical.symlink_to(outside)
        else:
            canonical.unlink()
            canonical.mkdir()
        violations = hook._inspect_dispatch(project, f"Inspect {worker}")
        assert violations, case
        assert wanted & {error["code"] for error in violations}, (case, violations)


def test_current_attempt_and_phase_defeat_worker_only_replay(tmp_path: Path) -> None:
    hook, helper = _block005_modules()
    declaration, paths, attempt1, attempt2 = _write_parallel_attempt2_awaiting(tmp_path, helper)
    canonical_before = paths["canonical"].read_bytes()
    old = hook._inspect_dispatch(tmp_path, f"Inspect {attempt1}")
    assert any(
        error["code"] == "INVALID_IDENTITY" and "attempt" in error["message"]
        for error in old
    )
    assert hook._inspect_dispatch(tmp_path, f"Inspect {attempt2}") == []

    # An old lineage cannot use a differently named report or prompt omission
    # to override the current exact parent's lineage.
    stale_lineage_path = tmp_path / "docs/dev/dev-report-old-lineage-worker.json"
    stale = json.loads((tmp_path / attempt2).read_text(encoding="utf-8"))
    stale["artifact_chain_binding"]["lineage_digest"] = "sha256:" + "f" * 64
    helper.write_json(stale_lineage_path, stale)
    lineage_errors = hook._inspect_dispatch(tmp_path, "Inspect docs/dev/dev-report-old-lineage-worker.json")
    assert any(error["code"] == "INVALID_IDENTITY" for error in lineage_errors)
    assert paths["canonical"].read_bytes() == canonical_before


def test_already_passed_member_only_prompt_cannot_replay_lane_qa(tmp_path: Path) -> None:
    hook, helper = _block005_modules()
    declaration, _ = helper.make_final_chain(tmp_path, "requirement_fanout")
    worker = declaration["member_lineage"][0]["artifact_paths"]["dev_report"]
    violations = hook._inspect_dispatch(tmp_path, f"Inspect {worker}")
    assert any(
        error["code"] == "INVALID_PHASE_TRANSITION" and "qa_pass" in error["message"]
        for error in violations
    )


def test_multiple_bound_parent_identities_fail_closed_without_scanning_history(tmp_path: Path) -> None:
    hook, helper = _block005_modules()
    docs = tmp_path / "docs/dev"
    docs.mkdir(parents=True)
    paths = []
    for index, parent in enumerate(("20260810-parent.full", "20260810-parent.full-other")):
        member = f"{parent}-worker"
        relative = f"docs/dev/dev-report-member-{index}.json"
        helper.write_json(tmp_path / relative, helper.dev_report(member, binding={
            "parent_task_id": parent, "member_id": member,
            "lineage_digest": "sha256:" + str(index + 1) * 64, "attempt": 1,
        }))
        paths.append(relative)
    violations = hook._inspect_dispatch(tmp_path, "Inspect " + " ".join(paths))
    assert any(error["code"] == "AMBIGUOUS_PARENT_MEMBERSHIP" for error in violations)


@pytest.mark.parametrize("replacement", ["regular", "removed", "symlink"])
def test_exact_parent_discovery_replacement_races_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement: str,
) -> None:
    hook, helper = _block005_modules()
    declaration, paths = _write_parallel_or_fanout_phase(tmp_path, helper, "parallel_dev", "awaiting_qa")
    worker = declaration["member_lineage"][0]["artifact_paths"]["dev_report"]
    canonical = paths["canonical"]
    canonical_before = canonical.read_bytes()
    qa_path = tmp_path / f"docs/dev/qa-report-{helper.TASK}.json"
    qa_before = qa_path.read_bytes()
    original = helper.AGG._read_regular_file_at
    injected = False

    def race(directory_fd: int, name: str, display_path: str):
        nonlocal injected
        if display_path != f"docs/dev/dev-report-{helper.TASK}.json" or injected:
            return original(directory_fd, name, display_path)
        injected = True
        if replacement == "removed":
            canonical.unlink()
            return original(directory_fd, name, display_path)
        raw, fingerprint = original(directory_fd, name, display_path)
        canonical.unlink()
        if replacement == "regular":
            canonical.write_bytes(raw)
        else:
            outside = tmp_path.parent / f"{tmp_path.name}-canonical-race.json"
            outside.write_bytes(raw)
            canonical.symlink_to(outside)
        return raw, fingerprint

    monkeypatch.setattr(helper.AGG, "_read_regular_file_at", race)
    monkeypatch.setattr(hook, "_load_aggregate", lambda: helper.AGG)
    violations = hook._inspect_dispatch(tmp_path, f"Inspect {worker}")
    assert injected
    assert any(error["code"] == "STALE_CANONICAL" for error in violations)
    assert qa_path.read_bytes() == qa_before
    if replacement == "regular":
        assert canonical.read_bytes() == canonical_before


def test_worker_replacement_during_parent_artifact_validation_fails_without_parent_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    hook, helper = _block005_modules()
    declaration, paths = _write_parallel_or_fanout_phase(tmp_path, helper, "parallel_dev", "awaiting_qa")
    worker_relative = declaration["member_lineage"][0]["artifact_paths"]["dev_report"]
    worker = tmp_path / worker_relative
    canonical_before = paths["canonical"].read_bytes()
    original = helper.AGG._validate_immutable_report
    injected = False

    def replace_worker(root: Path, declared: dict, member: dict, row: dict, errors: list):
        nonlocal injected
        if row["artifact_path"] == worker_relative and not injected:
            injected = True
            report = json.loads(worker.read_text(encoding="utf-8"))
            report["raced_mutation"] = True
            helper.write_json(worker, report)
        return original(root, declared, member, row, errors)

    monkeypatch.setattr(helper.AGG, "_validate_immutable_report", replace_worker)
    monkeypatch.setattr(hook, "_load_aggregate", lambda: helper.AGG)
    violations = hook._inspect_dispatch(tmp_path, f"Inspect {worker_relative}")
    assert injected
    assert any(error["code"] == "STALE_CANONICAL" for error in violations)
    assert paths["canonical"].read_bytes() == canonical_before


def test_parent_appearing_after_stable_absence_is_rejected_before_preparent_allowance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    hook, helper = _block005_modules()
    declaration, paths = _write_parallel_or_fanout_phase(
        tmp_path, helper, "parallel_dev", "awaiting_qa",
    )
    worker = declaration["member_lineage"][0]["artifact_paths"]["dev_report"]
    canonical = paths["canonical"]
    canonical_bytes = canonical.read_bytes()
    canonical.unlink()
    original = hook._revalidate_snapshots
    appeared = False

    def create_parent_after_absence(root: Path, snapshots: dict, aggregate, violations: list) -> None:
        nonlocal appeared
        original(root, snapshots, aggregate, violations)
        canonical.write_bytes(canonical_bytes)
        appeared = True

    monkeypatch.setattr(hook, "_revalidate_snapshots", create_parent_after_absence)
    violations = hook._inspect_dispatch(tmp_path, f"Inspect {worker}")
    assert appeared
    assert any(
        error["code"] == "STALE_CANONICAL"
        and "appeared" in error["message"]
        for error in violations
    )
    assert canonical.read_bytes() == canonical_bytes


def test_hook_process_blocks_worker_only_stale_parent_and_allows_genuine_preparent(
    tmp_path: Path,
) -> None:
    _, helper = _block005_modules()
    stale_root = tmp_path / "stale"
    declaration, _ = helper.make_final_chain(stale_root, "parallel_dev")
    worker = declaration["member_lineage"][0]["artifact_paths"]["dev_report"]
    report = json.loads((stale_root / worker).read_text(encoding="utf-8"))
    report["tampered"] = True
    helper.write_json(stale_root / worker, report)
    blocked = _hook_process(stale_root, f"Inspect {worker}")
    assert blocked.returncode == 2
    payload = json.loads(blocked.stderr)
    assert payload["schema_version"] == "artifact_chain_qa_gate.v1"
    assert payload["status"] == "blocked"
    assert any(error["code"] == "STALE_CANONICAL" for error in payload["errors"])

    preparent = tmp_path / "preparent"
    declaration, paths = helper.make_final_chain(preparent, "parallel_dev")
    worker = declaration["member_lineage"][0]["artifact_paths"]["dev_report"]
    paths["canonical"].unlink()
    allowed = _hook_process(preparent, f"Inspect {worker}")
    assert allowed.returncode == 0
    assert allowed.stderr == ""
