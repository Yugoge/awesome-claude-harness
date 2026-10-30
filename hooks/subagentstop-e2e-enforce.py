#!/usr/bin/env python3
"""SubagentStop Hook: Block QA subagents that did not perform E2E verification.

Activation logic:
  1. Read agent_id from stdin. If absent, exit 0 (non-subagent stop).
  2. Resolve agent entry via resolve_dev_registry_entry(agent_id, project_dir).
     If None (agent not in agent-index.json -- skipped FIRST ACTION sentinel):
       fall back to obligation.resolve_own_obligation() (registry-independent;
       reads the agent's own dispatch transcript directly). On a Resolved
       obligation declaring a qa-report.v2 artifact, apply the SAME
       declared-report check as step 6 below against that artifact's exact
       path. Otherwise (no resolvable obligation, role != qa,
       or no qa-report.v2 artifact declared): exit 0, true fail-open (LOW-10
       preserved; ticket 20261001-161041-r06).
  3. If dev_session_id is None (legacy flat-string entry): exit 0 (fail-open).
  4. If agent_type != "qa": exit 0 (scoped to QA only).
  5. Check .claude/dev-registry/<dev_session_id>/e2e-enforce.json.
     If absent or enabled != true: exit 0 (no enforcement for this session).
  6. Read the QA's own dispatch obligation (P1b E7: the record of what it
     owes). When the dispatch carries one, it decides alone: the qa-report.v2
     artifact it declares is the report judged, at exactly the path declared
     (missing: exit 2); one that declares none (BA validation, close QA) owes
     no E2E evidence here: exit 0.
  7. A dispatch without an obligation: find the session-correlated
     qa-report-*.json in docs/dev/ within project_dir.
     If none found: exit 2 (no QA report means no E2E evidence).
  8. Read e2e_enforcement.status from the QA report.
     If status is "performed", "legitimately_skipped" (with blocking_reason),
     "ran", or "blocked_app_unavailable": exit 0.
     If status is "skipped_without_justification" or field is absent:
       exit 2 with "E2E_ENFORCE_BLOCKED" message.

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


def _find_latest_qa_report(
    project_dir: str,
    dev_session_id: str | None = None,
) -> Path | None:
    """Find the most relevant QA report for a QA dispatch that carries no
    obligation (one that carries one is judged on the report it declares).

    session_ts: a timestamp extracted from dev_session_id, matched as a
    substring against candidate filenames, then against candidates'
    self-declared task_id/request_id content.

    Returns None if nothing matches ("no correlation found -> reject"). Never
    falls back to an unrelated/most-recent report when a session ID is
    present.
    """
    pattern = os.path.join(project_dir, "docs", "dev", "qa-report-*.json")
    matches = glob.glob(pattern)
    if not matches:
        return None
    # Sort by filename (timestamp-based names sort chronologically)
    matches.sort()

    if dev_session_id:
        # dev_session_id format: "dev-YYYYMMDD-HHMMSS"
        # Extract YYYYMMDD-HHMMSS portion from any session ID format
        session_ts = obligation.task_stamp(dev_session_id)
        if session_ts:
            # Check by filename match first (fastest)
            for p in reversed(matches):
                fname = os.path.basename(p)
                if session_ts in fname:
                    sys.stderr.write(
                        f"QA_REPORT_RESOLUTION: path={p} branch=session_ts_filename_match\n"
                    )
                    return Path(p)
            # Check by task_id/request_id inside recent reports (last 5)
            for p in reversed(matches[-5:]):
                try:
                    data = json.loads(Path(p).read_text(encoding="utf-8"))
                    report_id = data.get("task_id") or data.get("request_id") or ""
                    if report_id and session_ts in report_id:
                        sys.stderr.write(
                            f"QA_REPORT_RESOLUTION: path={p} branch=session_ts_content_match\n"
                        )
                        return Path(p)
                except Exception:
                    continue
        # No correlated report found; do not fall back to unrelated sessions
        # or guess.
        return None
    # dev_session_id is None — legacy/direct-call mode (dead code in enforcement path)
    return Path(matches[-1]) if matches else None


def _qa_report_expected_absent(project_dir: str, dev_session_id: str | None) -> bool:
    """True when this run's declared profile marks 'qa-report' expected-absent.

    Source: the sibling do-report-*<session_ts>*.json of a QA dispatch that
    carries no obligation (one that carries one declares what it owes).

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
    """Check a resolved QA report's e2e_enforcement.status.

    Exits 2 on any blocking outcome; returns normally when the status
    passes. Shared by the registered resolution path and the obligation-
    based fallback (ticket 20261001-161041-r06, M1) so the blocking rules
    are defined exactly once. `session_context` is the only text that
    differs between callers, preserving byte-identical output for the
    pre-existing registered path (AC5).
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
        f"E2E_ENFORCE_BLOCKED: agent {agent_id} (type={agent_type}) {session_context} "
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
        )
    except Exception:
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
    """Registry-independent fallback (ticket 20261001-161041-r06, M1).

    Resolves THIS agent's own dispatch obligation directly from its
    transcript (hooks/lib/obligation.py::resolve_own_obligation) instead of
    agent-index.json, and -- only when that obligation declares a
    qa-report.v2 artifact -- applies the SAME e2e_enforcement.status check
    the registered path applies, against the obligation's own declared
    artifact path (no glob-guessing).

    Exits 2 on a block. Returns normally (never exits) when no resolvable
    qa obligation exists, the role does not match "qa", or the obligation
    declares no qa-report.v2 artifact -- in every such case the caller's
    own unconditional exit 0 is the true fail-open (LOW-10 preserved, AC3).
    """
    try:
        resolution = obligation.resolve_own_obligation(
            session_id=data.get("session_id") or data.get("sessionId"),
            agent_id=agent_id,
            project_dir=project_dir,
            payload_agent_transcript_path=data.get("agent_transcript_path"),
            expected_role=ENFORCED_AGENT_TYPE,
        )
    except Exception:
        # A resolver bug must degrade to the caller's fail-open, never
        # crash the hook and never block on an internal error.
        return

    if not isinstance(resolution, obligation.Resolved):
        # NoObligationInPrompt / Unresolvable (including role_mismatch):
        # true fail-open, LOW-10 preserved (AC3).
        return

    _enforce_declared_report(
        dict(resolution.obligation),
        agent_id,
        project_dir,
        session_context=f"via obligation fallback (task_id={resolution.obligation.get('task_id')})",
    )


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

    # Resolve agent entry (both agent_type and dev_session_id)
    entry = resolve_dev_registry_entry(agent_id, project_dir)
    if entry is None:
        # Agent not in index (e.g. a skipped/failed FIRST ACTION
        # registration): fall back to the registry-independent obligation
        # resolver (ticket 20261001-161041-r06, M1) before the true
        # fail-open below.
        _enforce_e2e_via_obligation(data, agent_id, project_dir)
        sys.exit(0)

    dev_session_id = entry.get("dev_session_id")
    if not dev_session_id:
        # Legacy flat-string entry: no session correlation, skip enforcement
        sys.exit(0)

    agent_type = entry.get("agent_type", "")
    if agent_type != ENFORCED_AGENT_TYPE:
        # Not a QA agent: bypass enforcement unconditionally
        sys.exit(0)

    # Check enforcement flag
    enforce_path = (
        Path(project_dir)
        / ".claude"
        / "dev-registry"
        / dev_session_id
        / "e2e-enforce.json"
    )
    if not enforce_path.exists():
        # No enforcement flag for this session: fail-open
        sys.exit(0)

    enforce_data = _read_json(enforce_path)
    if not enforce_data.get("enabled"):
        # Enforcement explicitly disabled
        sys.exit(0)

    # What this QA owes is in its own dispatch obligation (P1b E7, row 3): a
    # dispatch that carries one is judged on the report it declares alone.
    declared = _own_obligation(data, agent_id, project_dir)
    if declared:
        _enforce_declared_report(
            declared, agent_id, project_dir, session_context=f"in session {dev_session_id}"
        )
        sys.exit(0)

    # A dispatch without an obligation: the session-correlated report.
    qa_report_path = _find_latest_qa_report(project_dir, dev_session_id)
    if qa_report_path is None:
        if _qa_report_expected_absent(project_dir, dev_session_id):
            sys.stderr.write(
                f"subagentstop-e2e-enforce: qa-report expected absent for "
                f"dev_session_id={dev_session_id} (do-profile expected_absent "
                f"declares 'qa-report'); skipping missing-report block.\n"
            )
            sys.exit(0)
        sys.stderr.write(
            f"E2E_ENFORCE_BLOCKED: agent {agent_id} (type={agent_type}) has no "
            f"qa-report-*.json in {project_dir}/docs/dev/ under session {dev_session_id}.\n"
            f"QA must produce a report with e2e_enforcement.status before stopping.\n"
        )
        sys.exit(2)

    _enforce_e2e_status(
        qa_report_path,
        agent_id,
        agent_type,
        session_context=f"in session {dev_session_id}",
    )
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
