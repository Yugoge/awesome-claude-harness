"""Contract, safety, CAS, consent, crash and recovery tests for Lane F."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(os.environ.get("LANE_F_REPO", Path(__file__).resolve().parents[1]))
SOURCE = Path(os.environ.get("LANE_F_SOURCE", REPO / "scripts/dev-fix.py"))
HOOK = Path(os.environ.get("LANE_F_HOOK", REPO / "hooks/userprompt-bulk-commit-capability.py"))
CYCLE = REPO / "docs/dev/overnight/019fe5c1-5b46-7dd1-8086-591a5b932bf3/cycle-1"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fix = _load(SOURCE, "lane_f_dev_fix")
hook = _load(HOOK, "lane_f_confirmation_hook")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def digest(value, exclude=None):
    if exclude:
        value = {k: v for k, v in value.items() if k != exclude}
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def raw_digest(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_result_contract(result):
    fields = {"schema_version", "operation", "status", "action", "project_root", "task_id",
              "entrypoint", "invocation_id", "origin_invocation_id", "gate_invocation_id",
              "origin_session_id", "identity_adoption_digest", "gate_preclaim_digest",
              "request_digest", "run_id", "audit_path", "audit_generation", "audit_sha256",
              "inventory_digest_before", "inventory_digest_after", "plan_digest", "decision",
              "plan", "mutations", "waivers", "gate_handoff", "next_action", "errors",
              "result_digest"}
    status_actions = {"prepared": {"preview_emitted", "plan_prepared"},
                      "awaiting_gate": {"actions_applied", "gate_claimed"},
                      "finalized": {"gate_recorded", "run_recovered"},
                      "no_action": {"none"}, "refused": {"none"},
                      "route_required": {"route_emitted"},
                      "recovery_required": {"none"}, "error": {"none"}}
    operation_statuses = {
        "prepare": {"prepared", "no_action", "refused", "route_required", "recovery_required", "error"},
        "apply": {"awaiting_gate", "no_action", "refused", "route_required", "recovery_required", "error"},
        "claim_gate": {"awaiting_gate", "refused", "recovery_required", "error"},
        "record_gate_result": {"finalized", "refused", "recovery_required", "error"},
        "recover": {"awaiting_gate", "finalized", "no_action", "recovery_required", "error"},
        "inspect": {"no_action", "recovery_required", "error"},
    }
    assert isinstance(result, dict) and set(result) == fields
    assert result["schema_version"] == fix.RESULT_SCHEMA
    assert result["status"] in status_actions and result["action"] in status_actions[result["status"]]
    if result["operation"] in operation_statuses and not (
            result["status"] == "refused" and result["plan"] is None):
        assert result["status"] in operation_statuses[result["operation"]]
    assert result["result_digest"] == digest(result, "result_digest")
    decision = result["decision"]
    assert set(decision) == {"root_decision_ids", "secondary_evidence_codes", "disposition", "protected"}
    assert decision["root_decision_ids"] == sorted(set(decision["root_decision_ids"]))
    assert decision["secondary_evidence_codes"] == sorted(set(decision["secondary_evidence_codes"]))
    assert decision["disposition"] in {"no_blocker", "mechanical_repair", "waiver_candidate",
                                       "route_required", "protected_refusal"}
    assert isinstance(decision["protected"], bool)
    handoff = result["gate_handoff"]
    assert set(handoff) == {"required", "state", "gate_kind", "gate_attempt_id",
                            "gate_invocation_id", "identity_adoption_digest", "handoff_digest",
                            "claim_token", "gate_preclaim_digest", "allowed_mutations_digest",
                            "allowed_mutations", "pre_gate_state_digest", "receipt_digest", "outcome"}
    assert handoff["state"] in {"not_required", "ready", "claimed", "recorded", "recovered", "unknown"}
    assert set(result["next_action"]) == {"kind", "human_command"}
    assert result["next_action"]["kind"] in {"none", "submit_confirmation", "call_apply",
                                               "call_claim_gate", "run_close_gate_once",
                                               "run_commit_gate_once", "call_record_gate_result",
                                               "invoke_close_fix", "manual_recovery"}
    if result["plan"] is not None:
        plan_fields = {"schema_version", "run_id", "entrypoint", "origin_invocation_id",
                       "origin_session_id", "request_digest", "r1_result_digest", "inventory_digest",
                       "actions", "waivers", "gate_required", "gate_kind", "allowed_mutations",
                       "plan_digest"}
        assert set(result["plan"]) == plan_fields
        assert result["plan"]["schema_version"] == fix.PLAN_SCHEMA
        assert result["plan"]["plan_digest"] == digest(result["plan"], "plan_digest")
    mutation_fields = {"action_id", "catalog_id", "kind", "path", "before_sha256",
                       "expected_after_sha256", "observed_after_sha256", "provider_schema",
                       "provider_result_digest", "status"}
    assert all(isinstance(row, dict) and set(row) == mutation_fields for row in result["mutations"])
    waiver_fields = {"catalog_id", "path", "reason_digest", "confirmation_grant_digest",
                     "projection_digest", "status"}
    assert all(isinstance(row, dict) and set(row) == waiver_fields for row in result["waivers"])
    error_fields = {"schema_version", "code", "category", "message", "retryable", "protected",
                    "field", "expected", "observed"}
    assert all(isinstance(row, dict) and set(row) == error_fields and
               row["schema_version"] == fix.ERROR_SCHEMA for row in result["errors"])


def init_repo(tmp_path: Path) -> Path:
    root = tmp_path.resolve()
    (root / "docs/dev").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "scripts/resolve-dev-artifact-chain.py").write_text("# fixture\n")
    (root / ".gitignore").write_text("docs/dev/\n")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)
    return root


def r1_result(root: Path, task="parent", *, errors=None, shape="singular", qa=None,
              artifacts=None, completion=None, lanes=None, whitelist=None, parent=None):
    errors = list(errors or [])
    if qa is None:
        if shape == "requirement_fanout":
            qa = [{"scope": "member", "member_id": "member-1", "task_id": "member-1",
                   "qa_report": "docs/dev/qa-report-member-1.json"}]
        else:
            qa = [{"scope": "parent", "member_id": None, "task_id": task,
                   "qa_report": f"docs/dev/qa-report-{task}.json"}]
    return {
        "schema_version": "artifact_chain_result.v2",
        "status": "fail" if errors else "pass",
        "project_root": str(root),
        "task_id": task,
        "input_task_id": task,
        "parent_task_id": task,
        "shape": shape,
        "errors": errors,
        "artifact_paths": list(artifacts or []),
        "qa_inputs": list(qa),
        "parent": dict(parent or {"task_id": task, "ticket": None, "context": None,
                                  "canonical_dev_report": None, "completion": None,
                                  "qa_report": None}),
        "canonical_dev_report": None,
        "completion": completion,
        "commit_whitelist_artifacts": list(whitelist or []),
        "lanes": list(lanes or []),
        "excluded_lanes": [],
        "report_paths": [],
    }


def request(operation: str, root: Path, task="parent", entrypoint="close",
            invocation="11111111-1111-4111-8111-111111111111", session="session-1", **fields):
    value = {"schema_version": fix.REQUEST_SCHEMA, "operation": operation,
             "project_root": str(root), "task_id": task, "entrypoint": entrypoint,
             "session_id": session, "invocation_id": invocation, "request_digest": None,
             **fields}
    value["request_digest"] = digest(value, "request_digest")
    return value


def prepare(root: Path, r1, *, intent="execute", entrypoint="close",
            invocation="11111111-1111-4111-8111-111111111111", session="session-1"):
    req = request("prepare", root, entrypoint=entrypoint, invocation=invocation, session=session,
                  intent=intent, command_flags={"fix": True, "auto": False, "force": False, "bulk": False},
                  expected_ownership_audit_digest=fix.OWNERSHIP_ADMISSION_DIGEST)
    with patch.object(fix, "_load_r1_result", return_value=r1):
        return req, fix.execute_dev_fix(req)


def close_preclaim(root: Path, result, invocation=None):
    inv = invocation or result["origin_invocation_id"]
    value = {"schema_version": fix.PRECLAIM_SCHEMA, "project_root": str(root),
             "task_id": result["task_id"], "entrypoint": "close",
             "current_invocation_id": inv, "run_id": result["run_id"],
             "plan_digest": result["plan_digest"],
             "artifact_chain_result_digest": result["plan"]["r1_result_digest"],
             "variant": "close", "evidence_digest": None, "resolved_spec_id": None,
             "resolved_cp_state_path": None, "checkpoint_applicable": False,
             "cycle_diff_digest": digest({"cycle": "fixture"}),
             "inspector_output_paths": [
                 str(root / f"docs/dev/style-inspector-report-{result['task_id']}.json"),
                 str(root / f"docs/dev/cleanliness-inspector-report-{result['task_id']}.json"),
                 str(root / f"docs/dev/prompt-inspector-report-{result['task_id']}.json"),
             ],
             "close_report_path": str(root / f"docs/dev/close-report-{result['task_id']}.md")}
    value["evidence_digest"] = digest(value, "evidence_digest")
    return value


def apply_request(root: Path, result, preclaim, invocation=None, grant=None):
    inv = invocation or result["origin_invocation_id"]
    return request("apply", root, entrypoint=result["entrypoint"], invocation=inv,
                   session=result["origin_session_id"],
                   run_id=result["run_id"], expected_origin_invocation_id=result["origin_invocation_id"],
                   expected_audit_generation=result["audit_generation"],
                   expected_audit_sha256=result["audit_sha256"],
                   expected_inventory_digest=result["inventory_digest_before"],
                   expected_plan_digest=result["plan_digest"], gate_preclaim_evidence=preclaim,
                   expected_gate_preclaim_digest=preclaim["evidence_digest"],
                   confirmation_grant_path=str(grant) if grant else None)


def rebind_apply_audit_cas(value, audit_path):
    rebound = dict(value)
    audit_bytes = Path(audit_path).read_bytes()
    audit = json.loads(audit_bytes)
    rebound["expected_audit_generation"] = audit["generation"]
    rebound["expected_audit_sha256"] = "sha256:" + hashlib.sha256(audit_bytes).hexdigest()
    rebound["request_digest"] = None
    rebound["request_digest"] = digest(rebound, "request_digest")
    return rebound


def claim_request(root: Path, result):
    return request("claim_gate", root, entrypoint=result["entrypoint"],
                   invocation=result["gate_invocation_id"],
                   session=result["origin_session_id"], run_id=result["run_id"],
                   expected_audit_generation=result["audit_generation"],
                   expected_audit_sha256=result["audit_sha256"],
                   handoff_digest=result["gate_handoff"]["handoff_digest"], consumer_lane="LANE-L")


def waiver_prompt(preview):
    nonce = json.loads(Path(preview["audit_path"]).read_text())["runs"][0]["confirmation_nonce"]
    specs = " ".join(f"--waive {x['catalog_id']}:{x['path']}" for x in preview["plan"]["waivers"])
    prompt = (f"/close {preview['task_id']} --fix --confirm {nonce} --digest {preview['plan_digest']} "
              f"{specs} --reason \"historical interruption confirmed\"")
    return nonce, prompt


def mint_waiver(root: Path, preview, invocation="22222222-2222-4222-8222-222222222222"):
    nonce, prompt = waiver_prompt(preview)
    assert hook._mint_fix_confirmation({"cwd": str(root), "session_id": preview["origin_session_id"],
                                        "prompt": prompt, "prompt_id": invocation},
                                       prompt, preview["origin_session_id"])
    path = Path("/tmp") / f"claude-fix-confirmation-{preview['origin_session_id']}-{nonce}.json"
    assert path.is_file()
    prompt_invocation = json.loads(path.read_text())["prompt_id_or_prompt_sha256"]
    assert re.fullmatch(r"[0-9a-f-]{36}", prompt_invocation)
    return path, prompt, prompt_invocation


def waiver_preview(tmp_path):
    root = init_repo(tmp_path)
    r1 = r1_result(root, errors=[{"code": "MISSING_ARTIFACT", "kind": "completion",
                                  "path": "docs/dev/completion-parent.json", "required": True}],
                    artifacts=[{"path": "docs/dev/completion-parent.json", "kind": "completion", "required": True}])
    _, preview = prepare(root, r1, intent="preview")
    assert preview["status"] == "prepared"
    return root, r1, preview


def adopted_ready(tmp_path):
    root, r1, preview = waiver_preview(tmp_path)
    grant, _, invocation = mint_waiver(root, preview)
    preclaim = close_preclaim(root, preview, invocation)
    req = apply_request(root, preview, preclaim, invocation, grant)
    with patch.object(fix, "_load_r1_result", return_value=r1):
        ready = fix.execute_dev_fix(req)
    assert ready["status"] == "awaiting_gate", ready
    return root, r1, preview, req, ready


def commit_claimed(tmp_path, *, invocation="44444444-4444-4444-8444-444444444444"):
    root = init_repo(tmp_path)
    (root / "owned.txt").write_text("base\n")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=root, check=True)
    (root / "owned.txt").write_text("approved change\n")
    close = root / "docs/dev/close-report-parent.md"
    close.write_text("CLOSE: YES\n")
    session = "commit-" + hashlib.sha256(str(root).encode()).hexdigest()[:16]
    r1 = r1_result(root, errors=[{"code": "GRANT_INVALID"}])
    _, prepared = prepare(root, r1, entrypoint="commit", invocation=invocation, session=session)
    assert prepared["status"] == "prepared", prepared
    branch = subprocess.check_output(["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
                                     cwd=root, text=True).strip()
    git_dir = subprocess.check_output(["git", "rev-parse", "--absolute-git-dir"],
                                      cwd=root, text=True).strip()
    before_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root,
                                          text=True).strip()
    repo_hash = hashlib.sha256(str(root).encode()).hexdigest()[:16]
    token = Path("/tmp/agentic-commit/push") / repo_hash / (branch.replace("/", "__") + ".json")
    token.unlink(missing_ok=True)
    Path(f"/tmp/claude-commit-manifest-{session}.json").unlink(missing_ok=True)
    Path(f"/tmp/claude-commit-grant-active-{session}.json").unlink(missing_ok=True)
    descriptor = {"repo_root": str(root), "git_dir": git_dir, "before_head": before_head,
                  "before_index_digest": "", "approved_paths": ["owned.txt"],
                  "approved_tree_digest": "", "allowed_ref": branch,
                  "expected_commit_count_max": 1, "grant_slot_id": "commit-grants-0",
                  "push_token_path": str(token), "transaction_digest": None}
    state = fix._git_state(descriptor)
    descriptor["before_index_digest"] = state["index_digest"]
    descriptor["approved_tree_digest"] = state["approved_worktree_digest"]
    descriptor["transaction_digest"] = digest(descriptor, "transaction_digest")
    preclaim = {"schema_version": fix.PRECLAIM_SCHEMA, "project_root": str(root),
                "task_id": "parent", "entrypoint": "commit", "current_invocation_id": invocation,
                "run_id": prepared["run_id"], "plan_digest": prepared["plan_digest"],
                "artifact_chain_result_digest": prepared["plan"]["r1_result_digest"],
                "variant": "commit", "close_report_digest": "sha256:" + raw_digest(close),
                "repository_plan": [descriptor], "repository_plan_digest": digest([descriptor]),
                "commit_qa_report_path": str(root / "docs/dev/commit-qa-report-parent.md"),
                "manifest_path": f"/tmp/claude-commit-manifest-{session}.json",
                "grant_slot_descriptors": [{
                    "canonical_directory": "/tmp",
                    "anchored_basename_regex": rf"^claude\-commit\-grant\-{re.escape(session)}\-[0-9a-f]{{16}}\.json(?:\.lck)?$",
                    "max_created": 2, "allowed_lifecycle": "create_then_rename_lck_then_delete"}],
                "push_token_paths": [str(token)], "evidence_digest": None}
    preclaim["evidence_digest"] = digest(preclaim, "evidence_digest")
    req = apply_request(root, prepared, preclaim, invocation)
    with patch.object(fix, "_load_r1_result", return_value=r1):
        ready = fix.execute_dev_fix(req)
    assert ready["status"] == "awaiting_gate", ready
    claimed = fix.execute_dev_fix(claim_request(root, ready))
    assert claimed["gate_handoff"]["state"] == "claimed", claimed
    return root, r1, descriptor, claimed


def write_commit_outputs(root, claimed, descriptor, *, commit: bool, artifact_chain=None):
    allowed = claimed["gate_handoff"]["allowed_mutations"]
    entries = {row["entry_id"]: row for row in allowed["path_entries"]}
    Path(entries["commit-qa-report"]["canonical_path"]).write_text("COMMIT: APPROVE\n")
    Path(entries["dispatch-manifest"]["canonical_path"]).write_bytes(canonical({
        "session_id": claimed["origin_session_id"], "task_id": claimed["task_id"],
        "dispatched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "repository_plan": [descriptor], "artifact_chain": artifact_chain or {"status": "fail"},
        "files_at_dispatch": {str(root): subprocess.check_output(
            ["git", "status", "--porcelain=v1"], cwd=root, text=True)},
    }) + b"\n")
    if commit:
        subprocess.run(["git", "add", "--", "owned.txt"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "feat: approved change"], cwd=root, check=True)
        commit_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root,
                                             text=True).strip()
        token_path = Path(descriptor["push_token_path"])
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_bytes(canonical({"commit_sha": commit_sha,
                                          "branch": descriptor["allowed_ref"],
                                          "repo_root": str(root),
                                          "session_id": claimed["origin_session_id"]}) + b"\n")
        return "committed", commit_sha, "sha256:" + raw_digest(token_path)
    return "nothing_to_commit", descriptor["before_head"], None


def commit_receipt(root, claimed, descriptor, *, commit):
    repo_status, after_head, token_digest = write_commit_outputs(root, claimed, descriptor,
                                                                 commit=commit)
    allowed = claimed["gate_handoff"]["allowed_mutations"]
    audit_run = json.loads(Path(claimed["audit_path"]).read_text())["runs"][0]
    pre = audit_run["pre_gate_state"]
    post, post_digest = fix._capture_gate_state(allowed, claimed["inventory_digest_after"])
    before_paths = {row["entry_id"]: row for row in pre["path_states"]}
    after_paths = {row["entry_id"]: row for row in post["path_states"]}
    before_slots = {row["slot_id"]: row for row in pre["dynamic_slot_states"]}
    after_slots = {row["slot_id"]: row for row in post["dynamic_slot_states"]}
    before_repos = {row["repo_root"]: row for row in pre["repository_states"]}
    after_repos = {row["repo_root"]: row for row in post["repository_states"]}
    targets = {}
    for row in allowed["path_entries"]:
        targets[row["entry_id"]] = (row["canonical_path"], before_paths[row["entry_id"]]["state_digest"],
                                    after_paths[row["entry_id"]]["state_digest"], row["producer"], "path")
    for row in allowed["dynamic_slots"]:
        targets[row["slot_id"]] = (row["canonical_directory"], before_slots[row["slot_id"]]["membership_digest"],
                                   after_slots[row["slot_id"]]["membership_digest"], "LANE-L", "slot")
    for row in allowed["repository_transactions"]:
        targets[row["repo_root"]] = (row["repo_root"], digest(before_repos[row["repo_root"]]),
                                     digest(after_repos[row["repo_root"]]), "changelog-analyst", "repository")
    events: list[dict] = []
    by_target: dict[str, list[dict]] = {}
    for target_id in sorted(targets):
        canonical_path, before, after, actor, kind = targets[target_id]
        rows: list[dict] = []
        if before != after:
            mutation = ("ref_update" if kind == "repository" else "create" if kind == "slot"
                        else "token_write" if target_id.startswith("push-token-")
                        else "create")
            event = {"sequence": len(events) + 1, "actor": actor, "mutation_class": mutation,
                     "target_id": target_id, "canonical_path_or_repo": canonical_path,
                     "before_state_digest": before, "after_state_digest": after,
                     "operation_result_digest": digest({"target": target_id, "after": after})}
            events.append(event); rows.append(event)
        by_target[target_id] = rows
    observations = []
    for target_id in sorted(targets):
        canonical_path, before, after, _actor, kind = targets[target_id]
        observations.append({"entry_id": target_id, "canonical_path": canonical_path,
                             "mutation_class": "git_transaction" if kind == "repository" and before != after
                             else "no_change" if before == after else "create",
                             "before_state_digest": before, "after_state_digest": after,
                             "status": "observed", "transition_digest": digest(by_target[target_id])})
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    receipt = {"schema_version": fix.RECEIPT_SCHEMA, "run_id": claimed["run_id"],
               "gate_attempt_id": claimed["gate_handoff"]["gate_attempt_id"],
               "gate_invocation_id": claimed["gate_invocation_id"], "entrypoint": "commit",
               "gate_kind": "commit_preflight_and_transaction", "producer": "LANE-L",
               "started_at": now, "finished_at": now, "ordinary_attempt_count": 1,
               "handoff_digest": claimed["gate_handoff"]["handoff_digest"],
               "pre_gate_state_digest": claimed["gate_handoff"]["pre_gate_state_digest"],
               "post_gate_state_digest": post_digest,
               "allowed_mutations_digest": claimed["gate_handoff"]["allowed_mutations_digest"],
               "outcome": "pass" if commit else "no_action", "authoritative_evidence": {
                   "evidence_kind": "commit_status", "commit_status": "committed" if commit else "nothing_to_commit",
                   "failure_code": None, "repository_results": [{
                       "repo_root": str(root), "before_head": descriptor["before_head"],
                       "after_head": after_head, "status": repo_status,
                       "commit_sha": after_head if commit else None,
                       "push_gate_token_sha256": token_digest}]},
               "envelope_observations": observations, "gate_events": events,
               "gate_event_ledger_digest": digest(events), "receipt_digest": None}
    receipt["receipt_digest"] = digest(receipt, "receipt_digest")
    return receipt


# AC-FRESH-F-01
def test_section5_quote_array_and_single_spec_scope():
    admission = json.loads((CYCLE / "lane-f-historical-recovery-ownership-and-preimage-admission.v1.json").read_text())
    quotes = admission["section_5_binding"]["quotes"]
    assert len(quotes) == 9
    assert hashlib.sha256(canonical(quotes)).hexdigest() == fix.SECTION5_QUOTE_ARRAY_SHA256
    assert admission["identity"]["lane_id"] == "LANE-F"


def test_other_lane_nonclaims_and_no_implementation_claim():
    ba = json.loads((CYCLE / "lane-f-historical-recovery-ba-contract-and-handoff.v1.json").read_text())
    assert ba["record_status"]["implementation_started_or_claimed"] is False
    assert ba["authority_boundary"]["no_claim_about_other_lanes"]


# AC-FRESH-F-02
@pytest.mark.parametrize("family", fix.ALL_FAMILIES)
def test_taxonomy_ids_are_exactly_f01_through_f22(family):
    assert family in {f"F{i:02d}" for i in range(1, 23)}


@pytest.mark.parametrize("events,expected", [
    ([{"code": "MISSING_ARTIFACT", "kind": "completion"}, {"code": "ABSENT_DECLARED_PATH", "kind": "completion"}], "F07"),
    ([{"code": "MISSING_ARTIFACT", "kind": "context"}, {"code": "ABSENT_DECLARED_PATH", "kind": "context"}], "F07"),
    ([{"code": "ABSENT_DECLARED_PATH", "kind": "artifact"}, {"code": "INVALID_QA_STATUS", "kind": "qa"}], "F10"),
    ([{"code": "COMMIT_REJECT"}, {"code": "COMMIT_VERDICT_UNPARSEABLE"}, {"code": "BULK_SENTINEL_MISSING"}], "F17"),
    ([{"code": "INVALID_QA_STATUS", "kind": "qa"}, {"code": "CLOSE_NO"}], "F10"),
])
def test_protected_precedence_collision_matrix(tmp_path, events, expected):
    root = init_repo(tmp_path)
    r1 = r1_result(root, errors=events)
    decision, rows = fix.classify_r1(r1, "close", root, "parent")
    ranked = min(decision["root_decision_ids"], key=lambda x: fix.DECISION_RANK.get(x, 1 if x.startswith("U_") else 99))
    assert ranked == expected
    assert decision["protected"]
    assert all(len([row["root_decision_id"]]) == 1 for row in rows)


def test_protected_precedence_matrix(tmp_path):
    test_protected_precedence_collision_matrix(tmp_path,
        [{"code": "MISSING_ARTIFACT", "kind": "completion"}, {"code": "CLOSE_NO"}], "F22")


def test_unknown_is_protected(tmp_path):
    root = init_repo(tmp_path)
    decision, _ = fix.classify_r1(r1_result(root, errors=[{"code": "NEW_UNMAPPED"}]), "close", root, "parent")
    assert decision == {"root_decision_ids": ["U_UNKNOWN"],
                        "secondary_evidence_codes": ["NEW_UNMAPPED"],
                        "disposition": "protected_refusal", "protected": True}


# AC-FRESH-F-03
def test_r1_shape_required_evidence_matrix(tmp_path):
    root = init_repo(tmp_path)
    for shape in ("singular", "parallel_dev", "requirement_fanout"):
        qa: list[dict[str, object]]
        if shape == "requirement_fanout":
            qa = [{"scope": "member", "member_id": "member-1", "task_id": "member-1",
                   "qa_report": "docs/dev/qa-member-1.json"}]
        else:
            qa = [{"scope": "parent", "member_id": None, "task_id": "parent",
                   "qa_report": "docs/dev/qa-parent.json"}]
        r1 = r1_result(root, shape=shape, qa=qa)
        decision, _ = fix.classify_r1(r1, "close", root, "parent")
        assert "F10" not in decision["root_decision_ids"]


def test_requirement_fanout_optional_parent_is_no_blocker(tmp_path):
    root = init_repo(tmp_path)
    parent = {"task_id": "parent", "ticket": "docs/dev/ticket-parent.md", "context": None,
              "canonical_dev_report": None, "completion": None, "qa_report": "docs/dev/qa-parent.json"}
    r1 = r1_result(root, shape="requirement_fanout", parent=parent,
                    errors=[{"code": "MISSING_ARTIFACT", "kind": "qa", "path": "docs/dev/qa-parent.json",
                             "required": False}])
    decision, _ = fix.classify_r1(r1, "close", root, "parent")
    assert decision["root_decision_ids"] == ["NO_BLOCKER"]


def test_required_qa_nonpass_is_f10(tmp_path):
    root = init_repo(tmp_path)
    r1 = r1_result(root, qa=[{"scope": "parent", "member_id": None, "task_id": "parent",
                              "qa_report": "docs/dev/qa.json", "status": "fail"}])
    decision, _ = fix.classify_r1(r1, "close", root, "parent")
    assert decision["root_decision_ids"] == ["F10"] and decision["protected"]


# AC-FRESH-F-04
@pytest.mark.parametrize("flags", [
    {"fix": True, "auto": True, "force": False, "bulk": False},
    {"fix": True, "auto": False, "force": True, "bulk": False},
    {"fix": True, "auto": False, "force": False, "bulk": True},
    {"fix": False, "auto": False, "force": False, "bulk": False},
])
def test_auto_fix_bulk_force_combinations_fail_before_plan(tmp_path, flags):
    root = init_repo(tmp_path)
    req = request("prepare", root, intent="execute", command_flags=flags,
                  expected_ownership_audit_digest=fix.OWNERSHIP_ADMISSION_DIGEST)
    with patch.object(fix, "_load_r1_result") as loader:
        result = fix.execute_dev_fix(req)
    assert result["status"] == "refused" and result["plan"] is None
    loader.assert_not_called()


def test_flag_and_status_closed_matrix(tmp_path):
    root = init_repo(tmp_path)
    statuses = [None, "blocked", "needs_review", "partial", "ready_for_qa", "qa_ready",
                "paused_for_user", "blocked_pending_user_apply", "partially_completed",
                "contract_violation_refused", "completed_with_followups", "completed_scoped_iteration_3"]
    for status in statuses:
        root_id, _ = fix.classify_event({"code": "INVALID_DEV_STATUS", "status": status}, r1_result(root))
        assert root_id == "F08"


def test_ready_for_qa_routes_without_status_rewrite(tmp_path):
    root = init_repo(tmp_path)
    r1 = r1_result(root, errors=[{"code": "INVALID_DEV_STATUS", "status": "ready_for_qa"}])
    _, result = prepare(root, r1)
    assert result["status"] == "route_required"
    assert result["decision"]["root_decision_ids"] == ["F08"]
    assert result["mutations"] == []


# AC-FRESH-F-05
def test_terminal_r1_plus_current_revalidation_binding():
    report = CYCLE / "r1-current-bytes-revalidation-for-lane-f.v1.json"
    assert raw_digest(report) == "619953635932c82339c77f5651706e015177e5ed0d5b02a22a2ef936bfd5a833"
    data = json.loads(report.read_text())
    assert data["baseline_terminal_report"]["sha256"] == "3e22af5be5013a53004f9fb159bfc0532eaaf9fb89578882ef423f72e8052500"
    assert data["verdict"]["active_blockers"] == []


def test_any_17_path_drift_invalidates_prepare():
    report = json.loads((CYCLE / "r1-current-bytes-revalidation-for-lane-f.v1.json").read_text())
    rows = [row for group in report["current_exact_envelope"]["groups"].values() for row in group["rows"]]
    envelope = {row["path"]: raw_digest(REPO / row["path"]) for row in rows}
    assert len(envelope) == 17
    assert hashlib.sha256(canonical(envelope)).hexdigest() == report["current_exact_envelope"]["current_envelope_digest"]
    changed = dict(envelope); changed[next(iter(changed))] = "0" * 64
    assert hashlib.sha256(canonical(changed)).hexdigest() != report["current_exact_envelope"]["current_envelope_digest"]


# AC-FRESH-F-06
def test_f_three_path_ownership_receipt_and_preimage_cas():
    admission = json.loads((CYCLE / "lane-f-historical-recovery-ownership-and-preimage-admission.v1.json").read_text())
    assert admission["decision"]["owner_count_each"] == [1, 1, 1]
    assert admission["decision"]["lane_f_intersection_count"] == 0
    assert admission["decision"]["invalid_claim_count"] == 0
    assert [x["preimage"]["state"] for x in admission["preimage_cas"]["rows"]] == ["absent", "file", "absent"]


def test_runtime_accepts_current_successor_and_rejects_superseded_v1(tmp_path):
    root = init_repo(tmp_path)
    current = request(
        "prepare", root, intent="execute",
        command_flags={"fix": True, "auto": False, "force": False, "bulk": False},
        expected_ownership_audit_digest=fix.OWNERSHIP_ADMISSION_DIGEST)
    with patch.object(fix, "_load_r1_result", return_value=r1_result(root)):
        accepted = fix.execute_dev_fix(current)
    assert fix.OWNERSHIP_ADMISSION_DIGEST == \
        "sha256:6a4b1bfbe7267b0683ccf4845731a3e893d3aa1fa44a69493476d6da551be71c"
    assert accepted["status"] == "no_action"

    stale = request(
        "prepare", root, invocation="77777777-7777-4777-8777-777777777777",
        intent="execute",
        command_flags={"fix": True, "auto": False, "force": False, "bulk": False},
        expected_ownership_audit_digest=next(iter(fix.SUPERSEDED_OWNERSHIP_ADMISSION_DIGESTS)))
    with patch.object(fix, "_load_r1_result") as loader:
        refused = fix.execute_dev_fix(stale)
    assert refused["status"] == "refused"
    assert refused["errors"][0]["code"] == "OWNERSHIP_ADMISSION_BLOCKED"
    loader.assert_not_called()


def test_stale_or_colliding_ownership_receipt_refuses_before_mutation(tmp_path):
    root = init_repo(tmp_path)
    req = request("prepare", root, intent="execute",
                  command_flags={"fix": True, "auto": False, "force": False, "bulk": False},
                  expected_ownership_audit_digest="sha256:" + "0" * 64)
    result = fix.execute_dev_fix(req)
    assert result["errors"][0]["code"] == "OWNERSHIP_ADMISSION_BLOCKED"
    assert not (root / "docs/dev/fix-audit-parent.json").exists()


# AC-FRESH-F-07
def test_close_f01_f02_two_prompt_single_adoption(tmp_path):
    root, _, preview, _, ready = adopted_ready(tmp_path)
    assert preview["plan"]["gate_required"] is False and preview["plan"]["gate_kind"] is None
    assert ready["gate_invocation_id"] != preview["origin_invocation_id"]
    assert ready["identity_adoption_digest"].startswith("sha256:")
    assert ready["waivers"][0]["status"] == "authorized"


def test_confirmation_same_origin_stale_replay_mismatch_and_third_invocation_refuse(tmp_path):
    root, r1, preview = waiver_preview(tmp_path)
    grant, _, invocation = mint_waiver(root, preview)
    preclaim = close_preclaim(root, preview, preview["origin_invocation_id"])
    same = apply_request(root, preview, preclaim, preview["origin_invocation_id"], grant)
    with patch.object(fix, "_load_r1_result", return_value=r1):
        refused = fix.execute_dev_fix(same)
    assert refused["status"] == "refused"
    assert grant.exists()  # rejected identities never consume another prompt's capability

    bound = apply_request(root, preview, close_preclaim(root, preview, invocation), invocation, grant)
    with patch.object(fix, "_load_r1_result", return_value=r1):
        ready = fix.execute_dev_fix(bound)
    assert ready["status"] == "awaiting_gate" and ready["gate_invocation_id"] == invocation
    assert not grant.exists()

    # A replay or third invocation cannot replace the durable adopter.
    third = "99999999-9999-4999-8999-999999999999"
    replay = apply_request(root, preview, close_preclaim(root, preview, third), third, grant)
    with patch.object(fix, "_load_r1_result", return_value=r1):
        again = fix.execute_dev_fix(replay)
    assert again["status"] in {"refused", "recovery_required"}
    assert again["gate_invocation_id"] in {None, invocation}


def test_prompt2_digest_and_apply_invocation_are_one_exact_binding(tmp_path):
    root, r1, preview = waiver_preview(tmp_path)
    grant, _, invocation = mint_waiver(root, preview)
    document = json.loads(grant.read_text())
    assert document["prompt_id_or_prompt_sha256"] == invocation
    assert fix._confirmation_invocation_id(document["confirmation_prompt_digest"]) == invocation

    unrelated = "99999999-9999-4999-8999-999999999999"
    wrong_actor = apply_request(
        root, preview, close_preclaim(root, preview, unrelated), unrelated, grant)
    with patch.object(fix, "_load_r1_result", return_value=r1):
        refused = fix.execute_dev_fix(wrong_actor)
    assert refused["status"] == "refused" and grant.exists()
    assert refused["errors"][0]["code"] == "CONFIRMATION_INVALID"

    document["confirmation_prompt_digest"] = digest({"wrong": "valid digest shape"})
    document["confirmation_grant_digest"] = digest(document, "confirmation_grant_digest")
    grant.write_bytes(canonical(document) + b"\n")
    wrong_digest = apply_request(
        root, preview, close_preclaim(root, preview, invocation), invocation, grant)
    with patch.object(fix, "_load_r1_result", return_value=r1):
        refused_digest = fix.execute_dev_fix(wrong_digest)
    assert refused_digest["status"] == "refused" and grant.exists()
    assert refused_digest["errors"][0]["code"] == "CONFIRMATION_INVALID"
    grant.unlink()


def test_confirmation_hook_binds_runtime_event_id_when_prompt_id_is_absent(tmp_path):
    root, _, preview = waiver_preview(tmp_path)
    nonce, prompt = waiver_prompt(preview)
    assert hook._mint_fix_confirmation(
        {"cwd": str(root), "session_id": preview["origin_session_id"],
         "prompt": prompt, "event_id": "event-prompt-2"},
        prompt, preview["origin_session_id"])
    grant = Path("/tmp") / \
        f"claude-fix-confirmation-{preview['origin_session_id']}-{nonce}.json"
    document = json.loads(grant.read_text())
    assert fix._confirmation_invocation_id(document["confirmation_prompt_digest"]) == \
        document["prompt_id_or_prompt_sha256"]
    grant.unlink()


def test_confirmation_persist_failure_preserves_grant_and_retry_is_idempotent(tmp_path):
    root, r1, preview = waiver_preview(tmp_path)
    grant, _, invocation = mint_waiver(root, preview)
    req = apply_request(
        root, preview, close_preclaim(root, preview, invocation), invocation, grant)
    original = fix._persist_audit
    calls = 0

    def fail_first(path, audit):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise fix.ContractError("DURABILITY_UNCERTAIN", "injected confirmation persist failure")
        return original(path, audit)

    with patch.object(fix, "_load_r1_result", return_value=r1), \
         patch.object(fix, "_persist_audit", side_effect=fail_first):
        failed = fix.execute_dev_fix(req)
    durable = json.loads(Path(preview["audit_path"]).read_text())["runs"][0]
    assert failed["status"] == "recovery_required"
    assert grant.exists() and durable["state"] == "PREVIEWED"
    assert durable["gate_invocation_id"] is None

    with patch.object(fix, "_load_r1_result", return_value=r1):
        retried = fix.execute_dev_fix(req)
    assert retried["status"] == "awaiting_gate"
    assert retried["gate_invocation_id"] == invocation and not grant.exists()
    states = [row["state"] for row in json.loads(
        Path(preview["audit_path"]).read_text())["runs"][0]["state_history"]]
    assert states.count("CONFIRMED") == 1 and states.count("GATE_READY") == 1


@pytest.mark.parametrize("grant_state_after_crash", ["present", "absent"])
def test_confirmed_cleanup_boundary_resumes_without_second_adopter(
        tmp_path, grant_state_after_crash):
    root, r1, preview = waiver_preview(tmp_path)
    grant, _, invocation = mint_waiver(root, preview)
    req = apply_request(
        root, preview, close_preclaim(root, preview, invocation), invocation, grant)
    injected = fix.ContractError("DURABILITY_UNCERTAIN", "injected confirmed cleanup boundary")
    with patch.object(fix, "_load_r1_result", return_value=r1), \
         patch.object(fix, "_consume_confirmation_grant", side_effect=injected):
        interrupted = fix.execute_dev_fix(req)
    durable = json.loads(Path(preview["audit_path"]).read_text())["runs"][0]
    assert interrupted["status"] == "recovery_required"
    assert durable["state"] == "CONFIRMED"
    assert durable["gate_invocation_id"] == invocation
    if grant_state_after_crash == "absent":
        grant.unlink()
    else:
        assert grant.exists()

    resumed_req = rebind_apply_audit_cas(req, preview["audit_path"])
    with patch.object(fix, "_load_r1_result", return_value=r1):
        resumed = fix.execute_dev_fix(resumed_req)
    assert resumed["status"] == "awaiting_gate"
    assert resumed["gate_invocation_id"] == invocation and not grant.exists()
    final_run = json.loads(Path(preview["audit_path"]).read_text())["runs"][0]
    assert [x["state"] for x in final_run["state_history"]].count("CONFIRMED") == 1


def test_unrelated_confirmation_path_does_not_consume_exact_grant(tmp_path):
    root, r1, preview = waiver_preview(tmp_path)
    grant, _, invocation = mint_waiver(root, preview)
    req = apply_request(root, preview, close_preclaim(root, preview, invocation), invocation, grant)
    req["confirmation_grant_path"] = "/tmp/unrelated-fix-confirmation.json"
    req["request_digest"] = digest(req, "request_digest")
    try:
        with patch.object(fix, "_load_r1_result", return_value=r1):
            result = fix.execute_dev_fix(req)
        assert result["status"] == "refused"
        assert grant.is_file()
    finally:
        grant.unlink(missing_ok=True)


def test_confirmation_hook_rejects_hardlinked_audit(tmp_path):
    root, _, preview = waiver_preview(tmp_path)
    audit = Path(preview["audit_path"])
    alias = audit.with_name("hardlinked-audit.json")
    os.link(audit, alias)
    nonce, prompt = waiver_prompt(preview)
    destination = Path("/tmp") / f"claude-fix-confirmation-{preview['origin_session_id']}-{nonce}.json"
    destination.unlink(missing_ok=True)
    try:
        assert not hook._mint_fix_confirmation(
            {"cwd": str(root), "session_id": preview["origin_session_id"],
             "prompt": prompt, "prompt_id": "human-prompt-hardlink"},
            prompt, preview["origin_session_id"])
        assert not destination.exists()
    finally:
        alias.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)


def test_confirmation_hook_rejects_digest_valid_but_non_authorizing_preview(tmp_path):
    root, _, preview = waiver_preview(tmp_path)
    audit_path = Path(preview["audit_path"])
    audit = json.loads(audit_path.read_text())
    audit["runs"][0]["decision"]["protected"] = True
    audit["audit_digest"] = digest(audit, "audit_digest")
    audit_path.write_bytes(canonical(audit) + b"\n")
    nonce, prompt = waiver_prompt(preview)
    destination = Path("/tmp") / f"claude-fix-confirmation-{preview['origin_session_id']}-{nonce}.json"
    destination.unlink(missing_ok=True)
    try:
        assert not hook._mint_fix_confirmation(
            {"cwd": str(root), "session_id": preview["origin_session_id"],
             "prompt": prompt, "prompt_id": "human-prompt-forged"},
            prompt, preview["origin_session_id"])
        assert not destination.exists()
    finally:
        destination.unlink(missing_ok=True)


def test_confirmation_hook_cleans_partial_destination_on_fsync_failure(tmp_path):
    root, _, preview = waiver_preview(tmp_path)
    nonce, prompt = waiver_prompt(preview)
    destination = Path("/tmp") / f"claude-fix-confirmation-{preview['origin_session_id']}-{nonce}.json"
    destination.unlink(missing_ok=True)
    with patch.object(hook.os, "fsync", side_effect=OSError("injected fsync failure")):
        assert not hook._mint_fix_confirmation(
            {"cwd": str(root), "session_id": preview["origin_session_id"],
             "prompt": prompt, "prompt_id": "human-prompt-fsync"},
            prompt, preview["origin_session_id"])
    assert not destination.exists()


def test_commit_waiver_is_impossible(tmp_path):
    root = init_repo(tmp_path)
    r1 = r1_result(root, errors=[{"code": "MISSING_ARTIFACT", "kind": "completion",
                                  "path": "docs/dev/completion-parent.json"}])
    _, result = prepare(root, r1, intent="preview", entrypoint="commit")
    assert result["status"] in {"route_required", "refused"}
    assert result["waivers"] == []


# AC-FRESH-F-08
@pytest.mark.parametrize("code,family", [
    ("MISSING_IDENTITY", "F03"), ("IDENTITY_MISMATCH", "F04"),
    ("INVALID_FILE_LIST", "F05"), ("MISSING_COMPLETION_REFERENCE", "F06"),
    ("CANONICAL_NOT_FOUND", "F11"), ("LOST_WORKER_DECLARATION", "F12"),
    ("MALFORMED_JSON", "F13"), ("CLOSE_VERDICT_UNPARSEABLE", "F14"),
    ("COMMIT_VERDICT_UNPARSEABLE", "F18"), ("GRANT_INVALID", "F19"),
])
def test_all_conditional_mechanical_families_positive_and_negative(tmp_path, code, family):
    root = init_repo(tmp_path)
    target_rel = "docs/dev/dev-report-parent.json"
    target = root / target_rel
    event = {"code": code, "path": target_rel}
    result = r1_result(root)
    if family == "F03":
        target.write_bytes(canonical({"status": "completed"}) + b"\n")
    elif family == "F04":
        event |= {"observed": "dev-parent", "expected": "parent"}
        target.write_bytes(canonical({"task_id": "dev-parent", "request_id": "dev-parent"}) + b"\n")
    elif family == "F05":
        projection = {"files_modified": ["a.py"], "files_created": ["b.py"]}
        event |= {"authoritative_files_modified": projection["files_modified"],
                  "authoritative_files_created": projection["files_created"],
                  "authoritative_file_list_digest": digest(projection)}
        target.write_bytes(canonical({"task_id": "parent", "request_id": "parent",
                                      "files_modified": None, "files_created": {}}) + b"\n")
    elif family == "F06":
        target_rel = "docs/dev/completion-parent.json"; target = root / target_rel
        event["path"] = target_rel
        target.write_bytes(canonical({"task_id": "parent", "request_id": "parent"}) + b"\n")
        result["parent"] = {"task_id": "parent", "ticket": "docs/dev/ticket-parent.md",
                            "context": "docs/dev/context-parent.json",
                            "canonical_dev_report": "docs/dev/dev-report-parent.json",
                            "qa_report": "docs/dev/qa-report-parent.json", "completion": target_rel}
    elif family == "F13":
        duplicate_rel = "docs/dev/dev-report-parent-authoritative.json"
        duplicate = root / duplicate_rel
        duplicate.write_bytes(canonical({"task_id": "parent", "request_id": "parent",
                                         "status": "completed"}) + b"\n")
        expected = "sha256:" + raw_digest(duplicate)
        target.write_bytes(b"{malformed")
        event |= {"authoritative_duplicate": duplicate_rel, "expected_sha256": expected}
        result["artifact_paths"] = [{"path": duplicate_rel, "kind": "dev_report",
                                     "required": True, "sha256": expected}]
    elif family == "F14":
        target_rel = "docs/dev/close-report-parent.md"; target = root / target_rel
        event["path"] = target_rel
        target.write_text("## Verdict\n**CLOSE: YES**\ntrailing prose\n")
    elif family == "F18":
        target_rel = "docs/dev/commit-qa-report-parent.md"; target = root / target_rel
        event["path"] = target_rel
        target.write_text("## Review\n**COMMIT: APPROVE**\ntrailing prose\n")
    elif family == "F19":
        root_id, _ = fix.classify_event(event, result)
        assert root_id == family
        actions, waivers, final = fix._derive_actions(
            root, "parent", result,
            [{"root_decision_id": family, "event": event, "secondary_evidence_codes": [code]}],
            {"root_decision_ids": [family], "secondary_evidence_codes": [code],
             "disposition": "mechanical_repair", "protected": False})
        assert len(actions) == 1 and not waivers and not final["protected"]
        assert actions[0]["kind"] == "authorize_single_pristine_retry"
        return
    elif family in {"F11", "F12"}:
        helper = _load(REPO / "tests/test_aggregate_dev_report.py", f"lane_f_r1_helper_{family}")
        resolver = _load(REPO / "scripts/resolve-dev-artifact-chain.py", f"lane_f_r1_resolver_{family}")
        (root / "docs/dev").rmdir(); (root / "docs").rmdir()
        declaration, paths = helper.make_final_chain(root, "parallel_dev", parent="parent")
        (root / "scripts/aggregate-dev-report.py").write_bytes(
            (REPO / "scripts/aggregate-dev-report.py").read_bytes())
        if family == "F11":
            result = resolver.resolve_chain(root, "parent")
            result["status"] = "fail"; result["errors"] = [event]
        else:
            paths["canonical"].unlink()
            result = r1_result(root, shape="parallel_dev", lanes=[{"member_id": "member"}])
            result |= {"phase_digest": declaration["phase_projection"]["phase_digest"],
                       "declaration_candidate": declaration,
                       "declaration_candidate_digest": digest(declaration)}
        root_id, _ = fix.classify_event(event, result)
        assert root_id == family
        actions, waivers, final = fix._derive_actions(
            root, "parent", result,
            [{"root_decision_id": family, "event": event, "secondary_evidence_codes": [code]}],
            {"root_decision_ids": [family], "secondary_evidence_codes": [code],
             "disposition": "mechanical_repair", "protected": False})
        assert len(actions) == 1 and not waivers and not final["protected"]
        observed, provider_digest = fix._invoke_r1_provider(root, "parent", actions[0])
        assert observed.startswith("sha256:") and provider_digest.startswith("sha256:")
        collision = paths["canonical"]
        collision.write_bytes(collision.read_bytes() + b"\n")
        raced = collision.read_bytes()
        with pytest.raises(fix.ContractError):
            fix._invoke_r1_provider(root, "parent", actions[0])
        assert collision.read_bytes() == raced
        return
    result["artifact_paths"] = [*result.get("artifact_paths", []),
                                {"path": target_rel, "kind": "artifact", "required": True}]
    root_id, _ = fix.classify_event(event, result)
    assert root_id == family
    result["errors"] = [event]; result["status"] = "fail"
    full_decision, classified = fix.classify_r1(result, "close", root, "parent")
    assert not full_decision["protected"] and family in full_decision["root_decision_ids"]
    actions, waivers, derived_decision = fix._derive_actions(root, "parent", result,
        classified, full_decision)
    assert len(actions) == 1 and not waivers and not derived_decision["protected"]
    action = actions[0]
    data = json.loads(json.dumps(action["expected_state"]))["bytes_b64"]
    import base64
    expected_bytes = base64.b64decode(data)
    observed = fix._atomic_exact_write(root, target, expected_bytes, action["before_sha256"])
    assert observed == action["expected_after_sha256"] and target.read_bytes() == expected_bytes
    target.write_bytes(b"concurrent-writer\n")
    with pytest.raises(fix.ContractError) as exc:
        fix._atomic_exact_write(root, target, expected_bytes, action["before_sha256"])
    assert exc.value.code == "INVENTORY_DRIFT" and target.read_bytes() == b"concurrent-writer\n"


def test_cas_conflict_never_overwrites(tmp_path):
    root = init_repo(tmp_path)
    target = root / "docs/dev/value.json"; target.write_text("old\n")
    before = "sha256:" + hashlib.sha256(b"different\n").hexdigest()
    with pytest.raises(fix.ContractError) as exc:
        fix._atomic_exact_write(root, target, b"new\n", before)
    assert exc.value.code == "INVENTORY_DRIFT"
    assert target.read_text() == "old\n"


def test_atomic_write_preserves_mode_and_detects_last_moment_race(tmp_path):
    root = init_repo(tmp_path)
    target = root / "docs/dev/value.json"
    target.write_bytes(b"old\n")
    target.chmod(0o640)
    before = "sha256:" + raw_digest(target)
    observed = fix._atomic_exact_write(root, target, b"new\n", before)
    assert observed == "sha256:" + raw_digest(target)
    assert stat.S_IMODE(target.stat().st_mode) == 0o640

    target.write_bytes(b"old-again\n")
    before = "sha256:" + raw_digest(target)
    real_fsync = os.fsync
    calls = 0
    def race_then_fsync(fd):
        nonlocal calls
        calls += 1
        if calls == 1:
            target.write_bytes(b"concurrent-writer\n")
        return real_fsync(fd)
    with patch.object(fix.os, "fsync", side_effect=race_then_fsync), \
         pytest.raises(fix.ContractError) as captured:
        fix._atomic_exact_write(root, target, b"newer\n", before)
    assert captured.value.code == "INVENTORY_DRIFT"
    assert target.read_bytes() == b"concurrent-writer\n"


def _f03_prepared(root):
    target = root / "docs/dev/dev-report-parent.json"
    target.write_bytes(canonical({"status": "completed"}) + b"\n")
    event = {"code": "MISSING_IDENTITY", "path": "docs/dev/dev-report-parent.json"}
    before = r1_result(root, errors=[event],
                       artifacts=[{"path": "docs/dev/dev-report-parent.json",
                                   "kind": "dev_report", "required": True}])
    after = r1_result(root, artifacts=before["artifact_paths"])
    _, prepared = prepare(root, before, intent="execute")
    assert prepared["status"] == "prepared", prepared
    preclaim = close_preclaim(root, prepared)
    return target, before, after, prepared, preclaim


def test_mechanical_apply_revalidates_r1_before_and_after(tmp_path):
    root = init_repo(tmp_path)
    target, before, after, prepared, preclaim = _f03_prepared(root)
    req = apply_request(root, prepared, preclaim)
    with patch.object(fix, "_load_r1_result", side_effect=[before, after]):
        result = fix.execute_dev_fix(req)
    assert result["status"] == "awaiting_gate", result
    assert json.loads(target.read_text())["task_id"] == "parent"
    audit_run = json.loads(Path(result["audit_path"]).read_text())["runs"][0]
    assert [row["state"] for row in audit_run["state_history"]].count("ACTION_INTENT") == 1
    assert [row["state"] for row in audit_run["state_history"]].count("ACTION_APPLIED") == 1


def test_post_action_r1_still_failing_is_recovery_required(tmp_path):
    root = init_repo(tmp_path)
    target, before, _, prepared, preclaim = _f03_prepared(root)
    req = apply_request(root, prepared, preclaim)
    with patch.object(fix, "_load_r1_result", side_effect=[before, before]):
        result = fix.execute_dev_fix(req)
    assert result["status"] == "recovery_required"
    assert json.loads(target.read_text())["task_id"] == "parent"  # exact action durable, no false gate
    assert result["gate_handoff"]["required"] is False


def test_pre_action_r1_inventory_drift_preserves_confirmation_grant(tmp_path):
    root, r1, preview = waiver_preview(tmp_path)
    grant, _, invocation = mint_waiver(root, preview)
    (root / "docs/dev/qa-report-parent.json").write_text('{"qa":{"status":"pass"}}\n')
    req = apply_request(root, preview, close_preclaim(root, preview, invocation), invocation, grant)
    with patch.object(fix, "_load_r1_result", return_value=r1):
        result = fix.execute_dev_fix(req)
    assert result["status"] == "recovery_required" and grant.exists()
    grant.unlink()


def test_ambiguous_candidate_is_recovery_required(tmp_path):
    root = init_repo(tmp_path)
    r1 = r1_result(root, errors=[{"code": "AMBIGUOUS_WORKER_SET"}])
    _, result = prepare(root, r1)
    assert result["status"] == "refused" and result["mutations"] == []


# AC-FRESH-F-09
@pytest.mark.parametrize("code", ["INVALID_QA_STATUS", "COMMIT_REJECT", "CLOSE_NO", "FORCE_PROVENANCE", "UNKNOWN_X"])
def test_permanent_integrity_floor_all_flags(tmp_path, code):
    root = init_repo(tmp_path)
    r1 = r1_result(root, errors=[{"code": code, "kind": "qa"}])
    _, result = prepare(root, r1)
    assert result["status"] == "refused"
    assert result["mutations"] == [] and result["waivers"] == []
    assert result["gate_handoff"]["required"] is False


def test_protected_result_has_zero_side_effects(tmp_path):
    root = init_repo(tmp_path)
    before = subprocess.check_output(["git", "status", "--porcelain=v1", "-z"], cwd=root)
    _, result = prepare(root, r1_result(root, errors=[{"code": "COMMIT_REJECT"}]))
    after = subprocess.check_output(["git", "status", "--porcelain=v1", "-z"], cwd=root)
    # The ignored audit is the only durable side effect and stays out of porcelain.
    assert before == after and result["status"] == "refused"


def test_permanent_integrity_boundary(tmp_path):
    test_protected_result_has_zero_side_effects(tmp_path)


# AC-FRESH-F-10
def test_commit_fix_missing_close_is_nonrecursive_route_required(tmp_path):
    root = init_repo(tmp_path)
    _, result = prepare(root, r1_result(root), entrypoint="commit")
    assert result["status"] == "route_required"
    assert result["next_action"] == {"kind": "invoke_close_fix", "human_command": "/close parent --fix"}
    assert result["mutations"] == [] and result["gate_handoff"]["required"] is False


def test_f16_exact_next_action_and_nonzero_exit(tmp_path):
    root = init_repo(tmp_path)
    _, result = prepare(root, r1_result(root), entrypoint="commit")
    assert fix._EXIT_BY_STATUS[result["status"]] == 3
    assert result["next_action"]["human_command"] == "/close parent --fix"


def test_f16_route_required_stop(tmp_path):
    test_commit_fix_missing_close_is_nonrecursive_route_required(tmp_path)


def test_f15_stale_close_routes_without_gate_and_future_mtime_protects(tmp_path):
    root = init_repo(tmp_path)
    close_report = root / "docs/dev/close-report-parent.md"
    close_report.write_text("CLOSE: YES\n")
    old = datetime.now(timezone.utc).timestamp() - 25 * 60 * 60
    os.utime(close_report, (old, old))
    _, stale = prepare(root, r1_result(root), entrypoint="commit")
    assert stale["status"] == "route_required"
    assert "F15" in stale["decision"]["root_decision_ids"]
    assert stale["next_action"] == {"kind": "invoke_close_fix",
                                     "human_command": "/close parent --fix"}
    assert stale["gate_handoff"]["required"] is False

    future_root = init_repo(tmp_path / "future")
    future_close = future_root / "docs/dev/close-report-parent.md"
    future_close.write_text("CLOSE: YES\n")
    future = datetime.now(timezone.utc).timestamp() + 60
    os.utime(future_close, (future, future))
    _, protected = prepare(future_root, r1_result(future_root), entrypoint="commit")
    assert protected["status"] == "refused"
    assert protected["decision"]["root_decision_ids"] == ["U_UNKNOWN"]
    assert "U_FUTURE_CLOSE_MTIME" in protected["decision"]["secondary_evidence_codes"]
    assert protected["gate_handoff"]["required"] is False


# AC-FRESH-F-11
def test_crash_boundary_matrix_and_exact_recovery(tmp_path):
    root, _, _, _, ready = adopted_ready(tmp_path)
    recover = request("recover", root, invocation="33333333-3333-4333-8333-333333333333",
                      session="recovery-session", run_id=ready["run_id"],
                      expected_audit_generation=ready["audit_generation"],
                      expected_audit_sha256=ready["audit_sha256"])
    result = fix.execute_dev_fix(recover)
    assert result["status"] == "awaiting_gate"
    assert result["gate_handoff"]["state"] == "ready"


@pytest.mark.parametrize("crash_point", ["ACTION_INTENT", "ACTION_APPLIED"])
def test_action_journal_crash_boundaries_never_issue_gate(tmp_path, crash_point):
    root = init_repo(tmp_path)
    _, before, after, prepared, preclaim = _f03_prepared(root)
    req = apply_request(root, prepared, preclaim)
    if crash_point == "ACTION_INTENT":
        with patch.object(fix, "_load_r1_result", return_value=before), \
             patch.object(fix, "_atomic_exact_write", side_effect=KeyboardInterrupt), \
             pytest.raises(KeyboardInterrupt):
            fix.execute_dev_fix(req)
    else:
        with patch.object(fix, "_load_r1_result", side_effect=[before, KeyboardInterrupt]), \
             pytest.raises(KeyboardInterrupt):
            fix.execute_dev_fix(req)
    audit_path = root / "docs/dev/fix-audit-parent.json"
    audit = json.loads(audit_path.read_text())
    run = audit["runs"][0]
    assert run["state"] == crash_point and run["gate_attempt_count"] == 0
    recovery = request("recover", root, invocation="33333333-3333-4333-8333-333333333333",
                       session="recovery", run_id=run["run_id"],
                       expected_audit_generation=audit["generation"],
                       expected_audit_sha256="sha256:" + raw_digest(audit_path))
    result = fix.execute_dev_fix(recovery)
    assert result["status"] == "recovery_required" and result["gate_handoff"]["required"] is False


def test_gate_result_crash_finalizes_only_stored_identical_receipt(tmp_path):
    root, _, _, _, ready = adopted_ready(tmp_path)
    claimed = fix.execute_dev_fix(claim_request(root, ready))
    receipt = _complete_close_receipt(root, claimed)
    record = request("record_gate_result", root, invocation=claimed["gate_invocation_id"],
                     session=claimed["origin_session_id"], run_id=claimed["run_id"],
                     expected_audit_generation=claimed["audit_generation"],
                     expected_audit_sha256=claimed["audit_sha256"],
                     gate_claim_token=claimed["gate_handoff"]["claim_token"], gate_receipt=receipt)
    persist = fix._persist_audit
    def crash_after_gate_result(path, audit):
        persisted = persist(path, audit)
        if audit["runs"][0]["state"] == "GATE_RESULT":
            raise KeyboardInterrupt
        return persisted
    with patch.object(fix, "_persist_audit", side_effect=crash_after_gate_result), \
         pytest.raises(KeyboardInterrupt):
        fix.execute_dev_fix(record)
    audit_path = Path(claimed["audit_path"])
    audit = json.loads(audit_path.read_text())
    assert audit["runs"][0]["state"] == "GATE_RESULT"
    recovery = request("recover", root, invocation="33333333-3333-4333-8333-333333333333",
                       session="recovery", run_id=claimed["run_id"],
                       expected_audit_generation=audit["generation"],
                       expected_audit_sha256="sha256:" + raw_digest(audit_path))
    result = fix.execute_dev_fix(recovery)
    assert result["status"] == "finalized" and result["gate_handoff"]["outcome"] == "pass", result


def test_concurrent_callers_one_writer_one_adopter_one_gate(tmp_path):
    root, _, _, _, ready = adopted_ready(tmp_path)
    claim = claim_request(root, ready)
    first = fix.execute_dev_fix(claim)
    second = fix.execute_dev_fix(claim)
    assert first["gate_handoff"]["claim_token"] == second["gate_handoff"]["claim_token"]
    assert first["gate_handoff"]["gate_attempt_id"] == second["gate_handoff"]["gate_attempt_id"]
    audit = json.loads(Path(first["audit_path"]).read_text())
    assert audit["runs"][0]["gate_attempt_count"] == 1


def test_inspect_serializes_on_exact_cross_process_task_lock(tmp_path):
    root = init_repo(tmp_path)
    _audit, lock = fix._audit_paths(root, "parent")
    lock.parent.mkdir(mode=0o700)
    lock.touch(mode=0o600)
    lock.chmod(0o600)
    holder_code = (
        "import fcntl,sys,time; "
        "f=open(sys.argv[1],'r+'); fcntl.flock(f,fcntl.LOCK_EX); "
        "print('LOCKED',flush=True); time.sleep(3)"
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_code, str(lock)], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True)
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "LOCKED"
        req = request("inspect", root)
        started = time.monotonic()
        inspected = fix.execute_dev_fix(req)
        elapsed = time.monotonic() - started
    finally:
        holder.terminate()
        holder.wait(timeout=3)
    assert elapsed >= 0.45
    assert inspected["status"] == "refused"
    assert inspected["errors"][0]["code"] == "LOCK_BUSY"


def test_claimed_gate_is_never_reissued(tmp_path):
    root, _, _, _, ready = adopted_ready(tmp_path)
    claimed = fix.execute_dev_fix(claim_request(root, ready))
    recover = request("recover", root, invocation="33333333-3333-4333-8333-333333333333",
                      session="recovery-session", run_id=claimed["run_id"],
                      expected_audit_generation=claimed["audit_generation"],
                      expected_audit_sha256=claimed["audit_sha256"])
    result = fix.execute_dev_fix(recover)
    assert result["status"] == "recovery_required"
    assert result["gate_handoff"]["gate_attempt_id"] == claimed["gate_handoff"]["gate_attempt_id"]


# AC-FRESH-F-12
def test_split_phase_same_entrypoint_handoff(tmp_path):
    root, _, _, _, ready = adopted_ready(tmp_path)
    assert ready["entrypoint"] == "close"
    assert ready["gate_handoff"]["gate_kind"] == "close_artifact_chain_and_verdict"
    assert ready["gate_handoff"]["state"] == "ready"


def _complete_close_receipt(root, claimed):
    allowed = claimed["gate_handoff"]["allowed_mutations"]
    projection = {
        "schema_version": "dev_fix_close_projection.v1",
        "run_id": claimed["run_id"],
        "gate_attempt_id": claimed["gate_handoff"]["gate_attempt_id"],
        "gate_invocation_id": claimed["gate_invocation_id"],
        "handoff_digest": claimed["gate_handoff"]["handoff_digest"],
        "allowed_mutations_digest": claimed["gate_handoff"]["allowed_mutations_digest"],
        "artifact_chain_result_digest": claimed["plan"]["r1_result_digest"],
        "waiver_authorizations": [
            {key: waiver[key] for key in ("catalog_id", "path", "reason_digest",
                                           "confirmation_grant_digest")}
            for waiver in claimed["waivers"]
        ],
    }
    for entry in allowed["path_entries"]:
        p = Path(entry["canonical_path"]); p.parent.mkdir(parents=True, exist_ok=True)
        if entry["entry_id"] == "close-report":
            p.write_bytes(b"FIX-GATE: " + canonical(projection) + b"\nCLOSE: YES\n")
        else:
            p.write_text('{"status":"pass"}\n')
    _, post_digest = fix._capture_gate_state(allowed, claimed["inventory_digest_after"])
    events = []
    observations = []
    for seq, entry in enumerate(allowed["path_entries"], 1):
        after = fix._typed_path_state(Path(entry["canonical_path"]))["state_digest"]
        event = {"sequence": seq, "actor": entry["producer"], "mutation_class": "create",
                 "target_id": entry["entry_id"], "canonical_path_or_repo": entry["canonical_path"],
                 "before_state_digest": entry["before_state_digest"], "after_state_digest": after,
                 "operation_result_digest": digest({"entry": entry["entry_id"], "after": after})}
        events.append(event)
        observations.append({"entry_id": entry["entry_id"], "canonical_path": entry["canonical_path"],
                             "mutation_class": "create", "before_state_digest": entry["before_state_digest"],
                             "after_state_digest": after, "status": "observed",
                             "transition_digest": digest([event])})
    close = root / "docs/dev/close-report-parent.md"
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    receipt = {"schema_version": fix.RECEIPT_SCHEMA, "run_id": claimed["run_id"],
               "gate_attempt_id": claimed["gate_handoff"]["gate_attempt_id"],
               "gate_invocation_id": claimed["gate_invocation_id"], "entrypoint": "close",
               "gate_kind": "close_artifact_chain_and_verdict", "producer": "LANE-L",
               "started_at": now, "finished_at": now, "ordinary_attempt_count": 1,
               "handoff_digest": claimed["gate_handoff"]["handoff_digest"],
               "pre_gate_state_digest": claimed["gate_handoff"]["pre_gate_state_digest"],
               "post_gate_state_digest": post_digest,
               "allowed_mutations_digest": claimed["gate_handoff"]["allowed_mutations_digest"],
               "outcome": "pass", "authoritative_evidence": {
                   "evidence_kind": "close_report", "close_report_path": "docs/dev/close-report-parent.md",
                   "close_report_sha256": "sha256:" + raw_digest(close), "verdict": "YES",
                   "fix_gate_projection_digest": digest(projection),
                   "artifact_chain_result_digest": claimed["plan"]["r1_result_digest"]},
               "envelope_observations": observations, "gate_events": events,
               "gate_event_ledger_digest": digest(events), "receipt_digest": None}
    receipt["receipt_digest"] = digest(receipt, "receipt_digest")
    return receipt


def test_complete_close_and_commit_receipt_envelopes(tmp_path):
    root, _, _, _, ready = adopted_ready(tmp_path)
    claimed = fix.execute_dev_fix(claim_request(root, ready))
    receipt = _complete_close_receipt(root, claimed)
    record = request("record_gate_result", root, invocation=claimed["gate_invocation_id"],
                     session=claimed["origin_session_id"], run_id=claimed["run_id"],
                     expected_audit_generation=claimed["audit_generation"],
                     expected_audit_sha256=claimed["audit_sha256"],
                     gate_claim_token=claimed["gate_handoff"]["claim_token"], gate_receipt=receipt)
    result = fix.execute_dev_fix(record)
    assert result["status"] == "finalized" and result["gate_handoff"]["outcome"] == "pass"
    replay = fix.execute_dev_fix(record)
    assert replay["result_digest"] == result["result_digest"] or replay["status"] == "finalized"


def test_commit_no_action_receipt_roundtrip(tmp_path):
    root, _, descriptor, claimed = commit_claimed(tmp_path)
    receipt = commit_receipt(root, claimed, descriptor, commit=False)
    record = request("record_gate_result", root, entrypoint="commit",
                     invocation=claimed["gate_invocation_id"], session=claimed["origin_session_id"],
                     run_id=claimed["run_id"], expected_audit_generation=claimed["audit_generation"],
                     expected_audit_sha256=claimed["audit_sha256"],
                     gate_claim_token=claimed["gate_handoff"]["claim_token"], gate_receipt=receipt)
    result = fix.execute_dev_fix(record)
    assert result["status"] == "finalized" and result["gate_handoff"]["outcome"] == "no_action", result


def test_commit_one_child_approved_tree_and_push_token_roundtrip(tmp_path):
    root, _, descriptor, claimed = commit_claimed(tmp_path)
    receipt = commit_receipt(root, claimed, descriptor, commit=True)
    record = request("record_gate_result", root, entrypoint="commit",
                     invocation=claimed["gate_invocation_id"], session=claimed["origin_session_id"],
                     run_id=claimed["run_id"], expected_audit_generation=claimed["audit_generation"],
                     expected_audit_sha256=claimed["audit_sha256"],
                     gate_claim_token=claimed["gate_handoff"]["claim_token"], gate_receipt=receipt)
    result = fix.execute_dev_fix(record)
    assert result["status"] == "finalized" and result["gate_handoff"]["outcome"] == "pass", result


def test_no_per_lane_or_cross_entrypoint_gate(tmp_path):
    root, _, _, _, ready = adopted_ready(tmp_path)
    text = SOURCE.read_text()
    assert "subprocess.run([\"/close\"" not in text and "subprocess.run([\"/commit\"" not in text
    assert ready["task_id"] == "parent" and ready["gate_handoff"]["gate_kind"].startswith("close_")


# AC-FRESH-F-13
def test_all_operations_canonical_roundtrip_and_exit_codes(tmp_path):
    for operation in sorted(fix._OPERATIONS):
        assert operation in fix.REQUEST_OPERATION_FIELDS
    for status, code in fix._EXIT_BY_STATUS.items():
        assert code in {0, 1, 2, 3, 4}
        assert (status in fix._SUCCESS_STATUSES) == (code == 0)
    value = {"b": "é", "a": 1}
    assert fix.strict_json_loads(fix.canonical_bytes(value)) == value

    root, _, preview, _, applied = adopted_ready(tmp_path / "sequence")
    claimed = fix.execute_dev_fix(claim_request(root, applied))
    receipt = _complete_close_receipt(root, claimed)
    record = request("record_gate_result", root, invocation=claimed["gate_invocation_id"],
                     session=claimed["origin_session_id"], run_id=claimed["run_id"],
                     expected_audit_generation=claimed["audit_generation"],
                     expected_audit_sha256=claimed["audit_sha256"],
                     gate_claim_token=claimed["gate_handoff"]["claim_token"], gate_receipt=receipt)
    recorded = fix.execute_dev_fix(record)
    recover = request("recover", root, invocation="33333333-3333-4333-8333-333333333333",
                      session="recover", run_id=recorded["run_id"],
                      expected_audit_generation=recorded["audit_generation"],
                      expected_audit_sha256=recorded["audit_sha256"],
                      observed_close_report_path="docs/dev/close-report-parent.md")
    recovered = fix.execute_dev_fix(recover)
    inspected = fix.execute_dev_fix(request("inspect", root,
                                            invocation="44444444-4444-4444-8444-444444444444",
                                            session="inspect"))
    by_operation = {row["operation"] for row in (preview, applied, claimed, recorded, recovered, inspected)}
    assert by_operation == fix._OPERATIONS
    for row in (preview, applied, claimed, recorded, recovered, inspected):
        assert_result_contract(row)

    no_action_root = init_repo(tmp_path / "no-action")
    _, no_action = prepare(no_action_root, r1_result(no_action_root))
    route_root = init_repo(tmp_path / "route")
    _, route = prepare(route_root, r1_result(route_root), entrypoint="commit")
    refused_request = request("prepare", no_action_root, intent="execute",
                              command_flags={"fix": True, "auto": False, "force": False, "bulk": False},
                              expected_ownership_audit_digest="sha256:" + "0" * 64)
    refused = fix.execute_dev_fix(refused_request)
    error_request = request("inspect", no_action_root,
                            invocation="55555555-5555-4555-8555-555555555555", session="error")
    with patch.object(fix, "_canonical_root", side_effect=RuntimeError("injected internal failure")):
        error = fix.execute_dev_fix(error_request)
    assert error["operation"] == "unknown"
    assert error["decision"]["root_decision_ids"] == ["U_PROTOCOL"]
    assert error["gate_handoff"]["state"] == "not_required"
    assert error["next_action"]["kind"] == "manual_recovery"
    recovery_root, _, _, _, recovery_ready = adopted_ready(tmp_path / "recovery")
    recovery_claimed = fix.execute_dev_fix(claim_request(recovery_root, recovery_ready))
    recovery_request = request("recover", recovery_root,
                               invocation="66666666-6666-4666-8666-666666666666", session="recover",
                               run_id=recovery_claimed["run_id"],
                               expected_audit_generation=recovery_claimed["audit_generation"],
                               expected_audit_sha256=recovery_claimed["audit_sha256"])
    recovery_required = fix.execute_dev_fix(recovery_request)
    status_rows = [preview, applied, recorded, no_action, route, refused, recovery_required, error]
    assert {row["status"] for row in status_rows} == set(fix._EXIT_BY_STATUS)
    for row in status_rows:
        assert_result_contract(row)
        assert fix._EXIT_BY_STATUS[row["status"]] in {0, 1, 2, 3, 4}


@pytest.mark.parametrize("payload", [b"{", b"[]", b'{"x":1,"x":2}', b'{"x":NaN}', b'"x"'])
def test_malformed_oversize_duplicate_unknown_and_nonfinite_json_refuse(payload):
    if payload == b"[]" or payload == b'"x"':
        result = fix.execute_dev_fix(fix.strict_json_loads(payload))
        assert result["status"] == "refused"
    else:
        with pytest.raises(Exception):
            fix.strict_json_loads(payload)


def test_digest_dag_recomputes_without_cycles(tmp_path):
    root = init_repo(tmp_path)
    _, result = prepare(root, r1_result(root))
    identity = {"schema_version": fix.RUN_SCHEMA, "canonical_project_root": str(root), "task_id": "parent",
                "entrypoint": "close", "origin_session_id": result["origin_session_id"],
                "origin_invocation_id": result["origin_invocation_id"], "request_digest": result["plan"]["request_digest"],
                "inventory_digest_before": result["inventory_digest_before"],
                "r1_result_digest": result["plan"]["r1_result_digest"], "run_id": result["run_id"]}
    assert "plan_digest" not in identity
    assert digest(identity, "run_id") == result["run_id"]
    assert digest(result["plan"], "plan_digest") == result["plan_digest"]
    assert digest(result, "result_digest") == result["result_digest"]


def test_constructible_digest_chain_without_fixed_point(tmp_path):
    test_digest_dag_recomputes_without_cycles(tmp_path)


def test_cli_parse_failure_is_one_canonical_result_line():
    proc = subprocess.run([sys.executable, str(SOURCE), "--request-stdin"], input=b'{"x":NaN}',
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    lines = proc.stdout.splitlines()
    assert proc.returncode == 2 and len(lines) == 1
    result = json.loads(lines[0])
    assert result["schema_version"] == fix.RESULT_SCHEMA
    assert canonical(result) == lines[0]


def test_cli_oversize_and_unknown_field_fail_closed(tmp_path):
    oversized = b"{" + b" " * fix.MAX_STDIN_BYTES + b"}"
    proc = subprocess.run([sys.executable, str(SOURCE), "--request-stdin"], input=oversized,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    result = json.loads(proc.stdout)
    assert proc.returncode == 2 and result["status"] == "refused"
    assert result["errors"][0]["code"] == "INVALID_REQUEST"


def test_recover_observation_paths_are_normalized_and_typed(tmp_path):
    root = init_repo(tmp_path)
    base = {"run_id": digest({"run": 1}), "expected_audit_generation": 0,
            "expected_audit_sha256": digest({"audit": 1})}
    for observed in (None, "", "/tmp/close.md", "docs/../close.md", "../close.md"):
        req = request("recover", root, observed_close_report_path=observed, **base)
        result = fix.execute_dev_fix(req)
        assert result["status"] == "refused"
        assert result["errors"][0]["field"] == "observed_close_report_path"

    for roots in ([str(root), str(root)], [str(root / "z"), str(root / "a")], ["relative"]):
        req = request("recover", root, entrypoint="commit", observed_repository_roots=roots, **base)
        result = fix.execute_dev_fix(req)
        assert result["status"] == "refused"
        assert result["errors"][0]["field"] == "observed_repository_roots"

    wrong_variant = request("recover", root, entrypoint="close",
                            observed_repository_roots=[str(root)], **base)
    result = fix.execute_dev_fix(wrong_variant)
    assert result["status"] == "refused" and result["errors"][0]["field"] == "entrypoint"


def test_apply_confirmation_path_schema_is_absolute_tmp_or_null(tmp_path):
    root = init_repo(tmp_path)
    base = {"run_id": digest({"run": 1}),
            "expected_origin_invocation_id": "11111111-1111-4111-8111-111111111111",
            "expected_audit_generation": 0, "expected_audit_sha256": digest({"audit": 1}),
            "expected_inventory_digest": digest({"inventory": 1}),
            "expected_plan_digest": digest({"plan": 1}),
            "gate_preclaim_evidence": {}, "expected_gate_preclaim_digest": digest({"preclaim": 1})}
    for path in ("relative.json", "/var/tmp/grant.json", "/tmp/../tmp/grant.json"):
        req = request("apply", root, confirmation_grant_path=path, **base)
        result = fix.execute_dev_fix(req)
        assert result["status"] == "refused"
        assert result["errors"][0]["field"] == "confirmation_grant_path"


def test_r1_status_and_provider_exit_must_agree(tmp_path):
    root = init_repo(tmp_path)
    provider = root / "scripts/resolve-dev-artifact-chain.py"
    for status, exit_code in (("pass", 2), ("fail", 0)):
        value = r1_result(root, errors=[] if status == "pass" else [{"code": "INVALID_STATUS"}])
        value["status"] = status
        provider.write_text("import sys\nsys.stdout.write(" + repr(canonical(value).decode()) + ")\n"
                            + f"raise SystemExit({exit_code})\n")
        with pytest.raises(fix.ContractError) as captured:
            fix._load_r1_result(root, "parent")
        assert captured.value.code == "R1_CONTRACT_MISMATCH"

    for status, errors, shape, exit_code in (("pass", [{"code": "INVALID_STATUS"}], "singular", 0),
                                              ("fail", [], None, 2),
                                              ("pass", [], None, 0)):
        value = r1_result(root, errors=errors)
        value.update({"status": status, "errors": errors, "shape": shape})
        provider.write_text("import sys\nsys.stdout.write(" + repr(canonical(value).decode()) + ")\n"
                            + f"raise SystemExit({exit_code})\n")
        with pytest.raises(fix.ContractError) as captured:
            fix._load_r1_result(root, "parent")
        assert captured.value.code == "R1_CONTRACT_MISMATCH"


def test_recover_result_status_action_matrix(tmp_path):
    root = init_repo(tmp_path / "ordinary")
    _, final = prepare(root, r1_result(root))
    req = request("recover", root, invocation="33333333-3333-4333-8333-333333333333",
                  session="recover", run_id=final["run_id"],
                  expected_audit_generation=final["audit_generation"],
                  expected_audit_sha256=final["audit_sha256"])
    recovered = fix.execute_dev_fix(req)
    assert (recovered["status"], recovered["action"]) == ("no_action", "none")

    close_root, _, _, _, ready = adopted_ready(tmp_path / "gate")
    req = request("recover", close_root, invocation="33333333-3333-4333-8333-333333333333",
                  session="recover", run_id=ready["run_id"],
                  expected_audit_generation=ready["audit_generation"],
                  expected_audit_sha256=ready["audit_sha256"])
    recovered = fix.execute_dev_fix(req)
    assert (recovered["status"], recovered["action"]) == ("awaiting_gate", "actions_applied")

    root = init_repo(tmp_path)
    req = request("inspect", root)
    req["untrusted"] = "authority"
    req["request_digest"] = digest(req, "request_digest")
    proc = subprocess.run([sys.executable, str(SOURCE), "--request-stdin"], input=canonical(req),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    result = json.loads(proc.stdout)
    assert proc.returncode == 2 and result["status"] == "refused"
    assert result["errors"][0]["code"] == "INVALID_REQUEST"


# AC-FRESH-F-14
def test_fix_and_bulk_capability_cross_substitution_matrix():
    assert hook._is_bulk_commit("/commit parent --bulk")
    assert not hook._is_bulk_commit("/close parent --fix --confirm " + "a" * 32)
    assert hook._parse_fix_confirmation("/commit parent --bulk") is None
    assert hook._parse_fix_confirmation("/close parent --fix --confirm bad --digest sha256:" + "0" * 64 +
                                        " --waive F01:a --reason x") is None


def test_no_registration_or_settings_diff():
    admission = json.loads((CYCLE / "lane-f-historical-recovery-ownership-and-preimage-admission.v1.json").read_text())
    paths = {x["path"] for x in admission["authorized_dev_contract"]["allowed_source_test_paths"]}
    assert paths == {"scripts/dev-fix.py", "hooks/userprompt-bulk-commit-capability.py", "tests/test_dev_fix.py"}
    assert "settings.json" not in paths and "settings.template.json" not in paths


# Existing hooks/tests/test_bulk_commit_sentinel.py is run as a separate unchanged regression node.

# AC-FRESH-F-15
def test_exact_authored_scope_and_preimage_postimage_manifest():
    admission = json.loads((CYCLE / "lane-f-historical-recovery-ownership-and-preimage-admission.v1.json").read_text())
    hook_row = admission["preimage_cas"]["rows"][1]["preimage"]
    assert hook_row["sha256"] == "d2302de99836ec149c9eb2659514c04fa79fc9e5853ecec29b60384ba8935801"
    assert hook_row["bytes"] == 4660 and hook_row["mode"] == "0644"


def test_audit_is_local_durable_and_never_claimed_committed(tmp_path):
    root = init_repo(tmp_path)
    _, result = prepare(root, r1_result(root))
    audit = Path(result["audit_path"])
    assert audit.is_file() and stat.S_IMODE(audit.stat().st_mode) == 0o600
    status = subprocess.check_output(["git", "status", "--porcelain=v1", "--ignored", str(audit)], cwd=root,
                                     text=True)
    assert status.startswith("!! ")
    assert "committed" not in json.dumps(json.loads(audit.read_text())).lower()


def test_audit_tracking_policy(tmp_path):
    test_audit_is_local_durable_and_never_claimed_committed(tmp_path)


# AC-FRESH-F-16
def test_append_only_lineage_and_gate_order():
    ba = CYCLE / "lane-f-historical-recovery-ba-contract-and-handoff.v1.json"
    qa = CYCLE / "lane-f-historical-recovery-independent-ba-qa.v1.json"
    admission = CYCLE / "lane-f-historical-recovery-ownership-and-preimage-admission.v1.json"
    assert raw_digest(ba) == "090e57fe31678abdcfad5220d79e87e4aa108a330719d404de629c03e2bed10b"
    assert raw_digest(qa) == "eb9a9ffcaf323d3325dac047c8693f90925e79ddccaeff2702af8e3c6cf2987c"
    assert raw_digest(admission) == "bd3cf91fe43b78217740e6dc42c28122715518a4a85bc9cd7c02a54a1c0ab7c7"
    q = json.loads(qa.read_text()); a = json.loads(admission.read_text())
    assert q["verdict"]["status"] == "pass"
    assert datetime.fromisoformat(a["issued_at"].replace("Z", "+00:00")) > datetime.fromisoformat(q["created_at"].replace("Z", "+00:00"))


def test_no_early_f_qa_l_parent_close_commit_or_spec_complete_authority():
    admission = json.loads((CYCLE / "lane-f-historical-recovery-ownership-and-preimage-admission.v1.json").read_text())
    authority = admission["authority"]
    assert authority["qa_allowed"] is False and authority["close_allowed"] is False
    assert authority["commit_allowed"] is False and authority["spec_complete"] is False


# Named protocol fixtures from the normative same-entrypoint contract.
def test_protocol_schema_and_exit_contract():
    assert set(fix.REQUEST_OPERATION_FIELDS) == fix._OPERATIONS
    assert set(fix._EXIT_BY_STATUS) == {"prepared", "awaiting_gate", "finalized", "no_action",
                                               "error", "refused", "route_required", "recovery_required"}


def test_prepare_apply_gate_ready(tmp_path):
    _, _, _, _, ready = adopted_ready(tmp_path)
    assert ready["gate_handoff"]["state"] == "ready"


def test_gate_claim_record_finalize(tmp_path):
    test_complete_close_and_commit_receipt_envelopes(tmp_path)


def test_gate_claim_single_attempt_cas(tmp_path):
    test_concurrent_callers_one_writer_one_adopter_one_gate(tmp_path)


def test_claimed_gate_crash_reconciliation(tmp_path):
    test_claimed_gate_is_never_reissued(tmp_path)


def test_close_projection_recovery(tmp_path):
    root, _, _, _, ready = adopted_ready(tmp_path)
    claimed = fix.execute_dev_fix(claim_request(root, ready))
    _complete_close_receipt(root, claimed)  # persist the exact ordinary close outputs only
    recovery = request("recover", root, invocation="33333333-3333-4333-8333-333333333333",
                       session="recover", run_id=claimed["run_id"],
                       expected_audit_generation=claimed["audit_generation"],
                       expected_audit_sha256=claimed["audit_sha256"],
                       observed_close_report_path="docs/dev/close-report-parent.md")
    result = fix.execute_dev_fix(recovery)
    assert result["status"] == "finalized" and result["gate_handoff"]["state"] == "recovered", result


def test_close_projection_recovery_rejects_incomplete_outputs(tmp_path):
    root, _, _, _, ready = adopted_ready(tmp_path)
    claimed = fix.execute_dev_fix(claim_request(root, ready))
    (root / "docs/dev/close-report-parent.md").write_text("CLOSE: YES\n")
    recovery = request("recover", root, invocation="33333333-3333-4333-8333-333333333333",
                       session="recover", run_id=claimed["run_id"],
                       expected_audit_generation=claimed["audit_generation"],
                       expected_audit_sha256=claimed["audit_sha256"],
                       observed_close_report_path="docs/dev/close-report-parent.md")
    assert fix.execute_dev_fix(recovery)["status"] == "recovery_required"


def test_commit_topology_recovery(tmp_path):
    root, r1, descriptor, claimed = commit_claimed(tmp_path)
    write_commit_outputs(root, claimed, descriptor, commit=True, artifact_chain=r1)
    req = request("recover", root, entrypoint="commit",
                  invocation="55555555-5555-4555-8555-555555555555", session="recover",
                  run_id=claimed["run_id"], expected_audit_generation=claimed["audit_generation"],
                  expected_audit_sha256=claimed["audit_sha256"],
                  observed_repository_roots=[str(root)])
    result = fix.execute_dev_fix(req)
    assert result["status"] == "finalized" and result["gate_handoff"]["outcome"] == "pass", result


def test_gate_unknown_outcome_fail_closed(tmp_path):
    test_claimed_gate_is_never_reissued(tmp_path)


def test_gate_outcome_mapping_and_error_variant(tmp_path):
    root, _, _, _, ready = adopted_ready(tmp_path)
    claimed = fix.execute_dev_fix(claim_request(root, ready))
    receipt = _complete_close_receipt(root, claimed)
    receipt["outcome"] = "no_action"
    receipt["receipt_digest"] = digest(receipt, "receipt_digest")
    with pytest.raises(fix.ContractError):
        fix._validate_receipt_against_run(receipt, json.loads(Path(claimed["audit_path"]).read_text())["runs"][0])


def test_two_prompt_identity_adoption_and_replay_negatives(tmp_path):
    test_close_f01_f02_two_prompt_single_adoption(tmp_path)


def test_full_close_commit_mutation_envelopes_reject_extra(tmp_path):
    root, _, _, _, ready = adopted_ready(tmp_path)
    allowed = ready["gate_handoff"]["allowed_mutations"]
    assert len(allowed["path_entries"]) == 4
    assert not allowed["dynamic_slots"] and not allowed["repository_transactions"]


def test_preclaim_evidence_is_read_only_and_reused(tmp_path):
    root, _, preview = waiver_preview(tmp_path)
    before = subprocess.check_output(["git", "status", "--porcelain=v1", "-z"], cwd=root)
    evidence = close_preclaim(root, preview, "22222222-2222-4222-8222-222222222222")
    fix._validate_preclaim(evidence, evidence["evidence_digest"])
    after = subprocess.check_output(["git", "status", "--porcelain=v1", "-z"], cwd=root)
    assert before == after


def test_preclaim_drift_blocks_before_gate_write(tmp_path):
    root, r1, preview = waiver_preview(tmp_path)
    grant, _, invocation = mint_waiver(root, preview)
    evidence = close_preclaim(root, preview, invocation)
    evidence["cycle_diff_digest"] = digest({"drift": True})
    req = apply_request(root, preview, evidence, invocation, grant)
    result = fix.execute_dev_fix(req)
    assert result["status"] == "recovery_required" and grant.exists()  # request rejected before capability validation
    grant.unlink()


def test_intermediate_gate_event_ledger_complete(tmp_path):
    root, _, _, _, ready = adopted_ready(tmp_path)
    claimed = fix.execute_dev_fix(claim_request(root, ready))
    receipt = _complete_close_receipt(root, claimed)
    assert [x["sequence"] for x in receipt["gate_events"]] == list(range(1, len(receipt["gate_events"]) + 1))
    assert receipt["gate_event_ledger_digest"] == digest(receipt["gate_events"])


def test_unreported_index_or_checkpoint_event_rejected(tmp_path):
    root, _, _, _, ready = adopted_ready(tmp_path)
    claimed = fix.execute_dev_fix(claim_request(root, ready))
    receipt = _complete_close_receipt(root, claimed)
    receipt["gate_events"].append({"sequence": len(receipt["gate_events"]) + 1, "actor": "unknown",
                                   "mutation_class": "index_stage", "target_id": "undeclared",
                                   "canonical_path_or_repo": str(root),
                                   "before_state_digest": digest({}), "after_state_digest": digest({}),
                                   "operation_result_digest": digest({})})
    receipt["gate_event_ledger_digest"] = digest(receipt["gate_events"])
    receipt["receipt_digest"] = digest(receipt, "receipt_digest")
    run = json.loads(Path(claimed["audit_path"]).read_text())["runs"][0]
    with pytest.raises(fix.ContractError) as exc:
        fix._validate_receipt_against_run(receipt, run)
    assert exc.value.code == "GATE_STATE_DRIFT"
