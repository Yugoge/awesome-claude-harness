#!/usr/bin/env python3
"""SubagentStop Hook: Block QA subagents that did not perform E2E verification.

Activation logic:
  1. Read agent_id from stdin. If absent, exit 0 (non-subagent stop).
  2. The stopping agent's type (the payload's agent_type, else its
     agent-index entry): any type other than "qa" exits 0.
  3. Its own dispatch obligation (P1b E7, R10), read also when the block
     fails the grammar: when the dispatch carries one, it decides alone,
     whatever the registry holds and whatever form the session id takes:
     the qa-report.v2 artifact it declares is the report judged, at exactly
     the path declared (missing: exit 2 naming that path); one that declares
     none (BA validation, close QA) owes no E2E evidence here: exit 0.
  4. A dispatch without an obligation, of a QA its agent-index entry binds to
     a cycle's registry (dev_session_id): the docs/dev/qa-report-*.json files
     this QA's own transcript shows it wrote (command_span.write_set), never
     another agent's. None written: exit 2, unless the session's do-report
     declares qa-report expected-absent.
  5. Each judged report's e2e_enforcement.status: "performed",
     "legitimately_skipped", "ran" or "blocked_app_unavailable" pass;
     "skipped_without_justification", another value or an absent field exit
     2 with an E2E_ENFORCE_BLOCKED message naming the report's path and the
     field.

Exit codes:
  0: Allow stop (pass-through).
  2: Block stop (E2E_ENFORCE_BLOCKED -- QA must perform E2E verification).
"""

import glob
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.agent_resolver import resolve_dev_registry_entry
from lib import command_span, obligation

# Only enforce for QA agents
ENFORCED_AGENT_TYPE = "qa"

# The one status that does not let QA stop: a skip with no reason. Every other
# value of the qa-report.v2 vocabulary (the schema's e2e_enforcement.status
# enum, read through obligation's schema reader) lets it stop; a value outside
# that vocabulary, or none, does not.
UNJUSTIFIED_STATUS = "skipped_without_justification"
QA_REPORT_RE = re.compile(r"docs/dev/qa-report-[^/]+\.json")


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


def _qa_report_expected_absent(project_dir: str, dev_session_id: str | None) -> bool:
    """True when this run's declared profile marks 'qa-report' expected-absent.

    Source: the sibling do-report-*<session_ts>*.json of a QA dispatch that
    carries no obligation and wrote no qa-report (one that carries one
    declares what it owes).

    Fails CLOSED on any internal error: returns False, never True, so an
    I/O hiccup degrades to the PRE-EXISTING blocking behavior rather than
    silently weakening E2E enforcement (Edge Case 2 -- the opposite polarity
    from this module's own outer fail-open wrapper at the bottom of the file).
    """
    try:
        stamp = obligation.task_stamp(dev_session_id)
        if not stamp:
            return False
        from lib import do_report  # the report's one reading (E8)
        for p in glob.glob(
            os.path.join(project_dir, "docs", "dev", f"do-report-*{stamp}*.json")
        ):
            if "qa-report" in do_report.expected_absent(p):
                return True
        return False
    except Exception:
        return False


def _enforce_e2e_status(
    qa_report_path: Path, agent_id: str, agent_type: str, session_context: str
) -> None:
    """Check a judged QA report's e2e_enforcement.status.

    Exits 2 on any blocking outcome, naming the report's path and the field;
    returns normally when the status passes. Shared by the declared-report
    path and the written-report path so the blocking rules are defined
    exactly once; `session_context` is the only text that differs.
    """
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
            f"E2E_ENFORCE_BLOCKED: agent {agent_id} (type={agent_type}) QA report "
            f"at {qa_report_path} has malformed e2e_enforcement field (expected dict, "
            f"got {type(e2e).__name__}).\n"
        )
        sys.exit(2)

    if e2e is None:
        sys.stderr.write(
            f"E2E_ENFORCE_BLOCKED: agent {agent_id} (type={agent_type}) QA report "
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
        f"E2E_ENFORCE_BLOCKED: agent {agent_id} (type={agent_type}) QA report at "
        f"{qa_report_path} ({session_context}) has e2e_enforcement.status={status!r}.\n"
        f"blocking_reason: {blocking_reason}\n"
        f"artifact: {qa_report_path} (failing check: e2e_enforcement.status not a passing status)\n"
        f"E2E verification is required. Perform E2E testing and update "
        f"e2e_enforcement.status to 'performed', 'legitimately_skipped', "
        f"'blocked_app_unavailable', or 'ran' before stopping.\n"
    )
    sys.exit(2)


def _own_dispatch(data: dict, agent_id: str, project_dir: str) -> tuple[dict, str | None]:
    """This QA's own dispatch obligation as declared, read also when the block
    fails the grammar (a pre-P1 template), {} when there is none or it cannot
    be read; and the agent's own transcript (the payload's, else the one the
    resolver found)."""
    transcript = data.get("agent_transcript_path")
    try:
        resolution = obligation.resolve_own_obligation(
            session_id=data.get("session_id") or data.get("sessionId"),
            agent_id=agent_id,
            project_dir=project_dir,
            payload_agent_transcript_path=transcript,
        )
    except Exception:
        return {}, transcript
    transcript = transcript or getattr(resolution, "transcript_path", None)
    if isinstance(resolution, obligation.Resolved):
        return dict(resolution.obligation), transcript
    block = obligation.extract_obligation_block(getattr(resolution, "prompt", "") or "")
    if not isinstance(block, obligation.ExtractedBlock):
        return {}, transcript
    try:
        doc = json.loads(block.body)
    except ValueError:
        return {}, transcript
    return (doc if isinstance(doc, dict) else {}), transcript


def _enforce_declared_report(
    declared: dict, agent_id: str, project_dir: str, session_context: str
) -> None:
    """Judge exactly the qa-report.v2 this QA's own dispatch obligation
    declares, at the path it declares, never another report of the session or
    the task (P1b row 3). Exits 2 on a block; returns when the dispatch
    declares no such report (BA validation, close QA: no E2E evidence is owed
    here) or its status passes. A declared path the grammar's path rule
    refuses (only a block that fails the grammar carries one) is the
    dispatch's defect, G1's to decide, and is never read."""
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

    _enforce_e2e_status(qa_report_path, agent_id, ENFORCED_AGENT_TYPE, session_context)


def main() -> None:
    data = _load_stdin()
    if not data:
        sys.exit(0)

    agent_id = data.get("agent_id")
    if not agent_id:
        sys.exit(0)

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())

    entry = resolve_dev_registry_entry(agent_id, project_dir) or {}
    agent_type = data.get("agent_type") or entry.get("agent_type") or ""
    if agent_type and agent_type != ENFORCED_AGENT_TYPE:
        # Not a QA agent: bypass enforcement unconditionally
        sys.exit(0)

    # What this QA owes is in its own dispatch obligation (P1b E7, R10): a
    # dispatch that carries one is judged on the report it declares alone,
    # whatever the registry holds and whatever form the session id takes.
    declared, transcript = _own_dispatch(data, agent_id, project_dir)
    if declared:
        if declared.get("role", ENFORCED_AGENT_TYPE) == ENFORCED_AGENT_TYPE:
            _enforce_declared_report(
                declared, agent_id, project_dir, session_context=f"task_id={declared.get('task_id')}"
            )
        sys.exit(0)

    # A dispatch without an obligation, of a QA a cycle's registry holds: the
    # QA report this QA's own transcript shows it wrote, never another agent's.
    dev_session_id = entry.get("dev_session_id")
    if agent_type != ENFORCED_AGENT_TYPE or not dev_session_id:
        sys.exit(0)

    written = command_span.write_set(transcript, project_dir, excluded=()) if transcript else None
    reports = sorted(p for p in (written.written if written else ()) if QA_REPORT_RE.fullmatch(p))
    if not reports:
        if _qa_report_expected_absent(project_dir, dev_session_id):
            sys.stderr.write(
                f"subagentstop-e2e-enforce: qa-report expected absent for "
                f"dev_session_id={dev_session_id} (do-profile expected_absent "
                f"declares 'qa-report'); skipping missing-report block.\n"
            )
            sys.exit(0)
        sys.stderr.write(
            f"E2E_ENFORCE_BLOCKED: agent {agent_id} (type={agent_type}) wrote no "
            f"docs/dev/qa-report-*.json (in session {dev_session_id}).\n"
            f"QA must produce a report with e2e_enforcement.status before stopping.\n"
        )
        sys.exit(2)

    for rel in reports:
        _enforce_e2e_status(
            Path(project_dir) / rel, agent_id, agent_type, session_context=f"in session {dev_session_id}"
        )
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
