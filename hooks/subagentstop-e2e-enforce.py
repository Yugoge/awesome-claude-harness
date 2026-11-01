#!/usr/bin/env python3
"""SubagentStop Hook: Block QA subagents that did not perform E2E verification.

What a QA owes is in its own dispatch obligation (P1b E7): the qa-report.v2
artifact it declares, read from a resolved obligation or, when the block
fails the grammar (an earlier template's), as declared. That report alone is
judged, at exactly the declared path, never another report of the session or
the task. Activation:
  1. Read agent_id from stdin. If absent, exit 0 (non-subagent stop).
  2. A registered agent (resolve_dev_registry_entry) is judged only while its
     session's .claude/dev-registry/<dev_session_id>/e2e-enforce.json is
     enabled; one with no dev_session_id (legacy flat entry) is not judged.
     An agent the registry does not resolve (a skipped FIRST ACTION read) is
     judged on its obligation alone.
  3. Both: an obligation whose role is "qa" and that declares a qa-report.v2
     is enforced (_enforce_e2e_via_obligation); every other dispatch (none
     declared, BA validation, close QA, another role) exits 0.
  4. The declared report missing: exit 2. Its e2e_enforcement.status (under
     qa.* or top level) passes when the schema's vocabulary lists it and it is
     not "skipped_without_justification"; that value, another or none exits 2
     (E2E_ENFORCE_BLOCKED).

Exit codes:
  0: Allow stop (pass-through).
  2: Block stop (E2E_ENFORCE_BLOCKED -- QA must perform E2E verification).
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.agent_resolver import resolve_dev_registry_entry
from lib import obligation

# Only enforce for QA agents
ENFORCED_AGENT_TYPE = "qa"

# The one status that does not let QA stop: a skip with no reason. Every other
# value of the qa-report.v2 vocabulary (the schema's e2e_enforcement.status
# enum, read through obligation's schema reader) lets it stop; a value outside
# that vocabulary, or none, does not.
UNJUSTIFIED_STATUS = "skipped_without_justification"


def _passing_statuses() -> frozenset[str]:
    return obligation._schema_enum("qa-report.v2", "qa.e2e_enforcement.status") - {UNJUSTIFIED_STATUS}


def _load_stdin() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _enforce_e2e_status(qa_report_path: Path, agent_id: str, task_id) -> None:
    """Check the declared QA report's e2e_enforcement.status. Exits 2 on any
    blocking outcome; returns normally when the status passes."""
    qa_report = _read_json(qa_report_path)

    # Navigate to e2e_enforcement field (may be nested under qa.*)
    e2e = None
    qa_section = qa_report.get("qa", {})
    if isinstance(qa_section, dict):
        e2e = qa_section.get("e2e_enforcement")
    if e2e is None:
        e2e = qa_report.get("e2e_enforcement")

    # Guard: e2e must be a dict; malformed value fails closed
    if e2e is not None and not isinstance(e2e, dict):
        sys.stderr.write(
            f"E2E_ENFORCE_BLOCKED: agent {agent_id} (type={ENFORCED_AGENT_TYPE}) QA report "
            f"at {qa_report_path} has malformed e2e_enforcement field (expected dict, "
            f"got {type(e2e).__name__}).\n"
        )
        sys.exit(2)

    if e2e is None:
        sys.stderr.write(
            f"E2E_ENFORCE_BLOCKED: agent {agent_id} (type={ENFORCED_AGENT_TYPE}) QA report "
            f"at {qa_report_path} has no e2e_enforcement field.\n"
            f"Add e2e_enforcement.status to the QA report before stopping.\n"
        )
        sys.exit(2)

    status = e2e.get("status", "")
    passing = _passing_statuses()

    if status in passing:
        # For legitimately_skipped, blocking_reason should be populated
        # but we do not hard-block on missing blocking_reason (advisory check only)
        return

    # status is skipped_without_justification, empty, or unrecognized
    blocking_reason = e2e.get("blocking_reason") or "(none provided)"
    sys.stderr.write(
        f"E2E_ENFORCE_BLOCKED: agent {agent_id} (type={ENFORCED_AGENT_TYPE}) (task_id={task_id}) "
        f"has e2e_enforcement.status={status!r}.\n"
        f"blocking_reason: {blocking_reason}\n"
        f"E2E verification is required. Perform E2E testing and update "
        f"e2e_enforcement.status to 'performed', 'legitimately_skipped', "
        f"'blocked_app_unavailable', or 'ran' before stopping.\n"
    )
    sys.exit(2)


def _own_obligation(data: dict, agent_id: str, project_dir: str) -> dict:
    """This QA's own dispatch obligation as declared, read also when the block
    fails the grammar (a pre-P1 template); {} when there is none or it cannot
    be read."""
    try:
        resolution = obligation.resolve_own_obligation(
            session_id=data.get("session_id") or data.get("sessionId"),
            agent_id=agent_id,
            project_dir=project_dir,
            payload_agent_transcript_path=data.get("agent_transcript_path"),
            expected_role=ENFORCED_AGENT_TYPE,
        )
    except Exception:
        # A resolver bug judges nothing: never a block on an internal error.
        return {}
    if isinstance(resolution, obligation.Resolved):
        return dict(resolution.obligation)
    block = obligation.extract_obligation_block(getattr(resolution, "prompt", "") or "")
    if not isinstance(block, obligation.ExtractedBlock):
        return {}
    try:
        doc = json.loads(block.body)
    except ValueError:
        return {}
    return doc if isinstance(doc, dict) else {}


def _enforce_e2e_via_obligation(data: dict, agent_id: str, project_dir: str) -> None:
    """Judge exactly the qa-report.v2 this QA's own dispatch obligation
    declares, at the path it declares (P1b row 3). Exits 2 on a block; returns
    when the obligation's role is not qa, it declares no such report (BA
    validation, close QA: no E2E evidence is owed here) or its status passes.
    A declared path the grammar's path rule refuses (only a block that fails
    the grammar carries one) is the dispatch's defect, G1's to decide, and is
    never read."""
    declared = _own_obligation(data, agent_id, project_dir)
    if declared.get("role") != ENFORCED_AGENT_TYPE:
        return
    qa_artifact = next(
        (
            a
            for a in declared.get("artifacts") or []
            if isinstance(a, dict) and a.get("kind") == "json"
            and a.get("schema") == "qa-report.v2"
            and obligation._legal_repo_relative_path(a.get("path"))
        ),
        None,
    )
    if qa_artifact is None:
        return

    task_id = declared.get("task_id")
    qa_report_path = Path(project_dir) / qa_artifact["path"]
    if not qa_report_path.is_file():
        sys.stderr.write(
            f"E2E_ENFORCE_BLOCKED: agent {agent_id} (type={ENFORCED_AGENT_TYPE}) "
            f"declared a qa-report.v2 obligation (task_id={task_id}) at "
            f"{qa_artifact['path']} but no such file exists.\n"
            f"QA must produce a report with e2e_enforcement.status before stopping.\n"
        )
        sys.exit(2)

    _enforce_e2e_status(qa_report_path, agent_id, task_id)


def main() -> None:
    data = _load_stdin()
    agent_id = data.get("agent_id")
    if not agent_id:
        sys.exit(0)

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())

    entry = resolve_dev_registry_entry(agent_id, project_dir)
    if entry is not None:
        # A registered agent is judged only while its session's flag arms the gate.
        sid = entry.get("dev_session_id")
        if not sid or not _read_json(
                Path(project_dir) / ".claude" / "dev-registry" / sid / "e2e-enforce.json").get("enabled"):
            sys.exit(0)
    _enforce_e2e_via_obligation(data, agent_id, project_dir)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
