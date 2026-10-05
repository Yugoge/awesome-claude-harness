#!/usr/bin/env python3
"""SubagentStop Hook: Block QA subagents that did not perform E2E verification.

Activation logic:
  1. Read agent_id from stdin. If absent, exit 0 (non-subagent stop).
  2. Resolve agent entry via resolve_dev_registry_entry(agent_id, project_dir).
     If None (agent not in agent-index.json -- skipped FIRST ACTION sentinel):
       fall back to obligation.resolve_own_obligation() (registry-independent;
       reads the agent's own dispatch transcript directly). On a Resolved
       obligation declaring a qa-report.v2 artifact, apply the SAME
       e2e_enforcement.status check described in steps 6-7 below against that
       artifact's exact path. Otherwise (no resolvable obligation, role != qa,
       or no qa-report.v2 artifact declared): exit 0, true fail-open (LOW-10
       preserved; ticket 20261001-161041-r06).
  3. If dev_session_id is None (legacy flat-string entry): exit 0 (fail-open).
  4. If agent_type != "qa": exit 0 (scoped to QA only).
  5. Check .claude/dev-registry/<dev_session_id>/e2e-enforce.json.
     If absent or enabled != true: exit 0 (no enforcement for this session).
  6. Find the most recent qa-report-*.json in docs/dev/ within project_dir.
     If none found: exit 2 (no QA report means no E2E evidence).
  7. Read e2e_enforcement.status from the QA report.
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
from lib.harness_state_dir import harness_state_dir

# Only enforce for QA agents
ENFORCED_AGENT_TYPE = "qa"

# Statuses that allow QA to stop
PASSING_STATUSES = {"performed", "ran", "blocked_app_unavailable", "legitimately_skipped"}


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


# Orchestrator-anchored task_id must match this shape before it is trusted as
# a correlation anchor — the exact identifier-safety pattern write-qa-mode.sh
# already enforces for --session-id, reused verbatim so an unsafe/path-shaped
# value degrades silently to "no anchor" (S1/AC5) rather than escaping
# docs/dev/ or raising.
_TASK_ID_ANCHOR_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')


def _task_id_anchor_match(project_dir: str, task_id: str | None) -> Path | None:
    """Additive, exact-match, orchestrator-anchored correlation dimension.

    Independent of session_ts. Only matches docs/dev/qa-report-<task_id>*.json
    candidates whose OWN self-declared task_id/request_id field equals
    task_id exactly (not substring) — reuses the exact-path + exact-equality
    convention already established by scripts/resolve-dev-artifact-chain.py.
    An unsafe/empty task_id is silently treated as absent: no exception, no
    path outside docs/dev/.
    """
    if not task_id or not _TASK_ID_ANCHOR_RE.match(task_id):
        return None
    anchor_pattern = os.path.join(project_dir, "docs", "dev", f"qa-report-{task_id}*.json")
    for p in sorted(glob.glob(anchor_pattern), reverse=True):
        data = _read_json(Path(p))
        report_id = data.get("task_id") or data.get("request_id") or ""
        if report_id == task_id:
            return Path(p)
    return None


def _find_latest_qa_report(
    project_dir: str,
    dev_session_id: str | None = None,
    task_id: str | None = None,
) -> Path | None:
    """Find the most relevant QA report for the current session.

    Two independent correlation dimensions are tried, in order:
      1. session_ts (pre-existing, unchanged): a timestamp extracted from
         dev_session_id, matched as a substring against candidate filenames,
         then against candidates' self-declared task_id/request_id content.
      2. task_id (additive): an orchestrator-anchored exact task identifier,
         matched by exact path + exact self-declared-identity equality. Only
         tried when dimension 1 produced no match — including when no
         timestamp is extractable from dev_session_id at all.

    Returns None if neither dimension produces a match ("no correlation
    found -> reject"). Never falls back to an unrelated/most-recent report
    when a session ID is present.
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
        _m = re.search(r'\d{8}-\d{6}', dev_session_id)
        if _m:
            session_ts = _m.group()
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
        # No session_ts match — either no timestamp was extractable from
        # dev_session_id, or one was extracted but no candidate matched it.
        # Fall through to the additive task_id anchor (M2) instead of
        # returning None immediately; this only ever ADDS a match
        # opportunity and never removes the terminal fail-closed return below.
        anchored = _task_id_anchor_match(project_dir, task_id)
        if anchored is not None:
            sys.stderr.write(
                f"QA_REPORT_RESOLUTION: path={anchored} branch=task_id_anchor_match\n"
            )
            return anchored
        # No correlated report found via either dimension; do not fall back
        # to unrelated sessions or guess.
        return None
    # dev_session_id is None — legacy/direct-call mode (dead code in enforcement path)
    return Path(matches[-1]) if matches else None


def _qa_report_expected_absent(
    project_dir: str, dev_session_id: str | None, qa_sentinel: dict
) -> bool:
    """True when this run's declared profile marks 'qa-report' expected-absent.

    Primary source: the sibling do-report-<task_id>.json skeleton
    (hooks/prompt-workflow.py:_write_do_report_skeleton), keyed by the SAME
    task_id this file already reads from qa_sentinel at the call site (M4:
    single source of truth). Secondary/defensive source: qa.json's own
    expected_absent field (Could-Have C1) -- a no-op today since no current
    writer populates it, kept for forward compatibility.

    Fails CLOSED on any internal error: returns False, never True, so an
    I/O hiccup degrades to the PRE-EXISTING blocking behavior rather than
    silently weakening E2E enforcement (Edge Case 2 -- the opposite polarity
    from this module's own outer fail-open wrapper at the bottom of the file).
    """
    try:
        task_id = qa_sentinel.get("task_id")
        candidates = []
        if isinstance(task_id, str) and _TASK_ID_ANCHOR_RE.match(task_id):
            candidates.append(
                os.path.join(project_dir, "docs", "dev", f"do-report-{task_id}.json")
            )
        ts_match = re.search(r"\d{8}-\d{6}", dev_session_id or "")
        if ts_match:
            for p in glob.glob(
                os.path.join(
                    project_dir, "docs", "dev", f"do-report-*{ts_match.group()}*.json"
                )
            ):
                if p not in candidates:
                    candidates.append(p)
        for p in candidates:
            data = _read_json(Path(p))
            absent = data.get("expected_absent")
            if isinstance(absent, list) and "qa-report" in absent:
                return True
        absent = qa_sentinel.get("expected_absent")
        if isinstance(absent, list) and "qa-report" in absent:
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

    if status in PASSING_STATUSES:
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

    qa_artifact = next(
        (
            a
            for a in resolution.obligation.get("artifacts", [])
            if a.get("kind") == "json" and a.get("schema") == "qa-report.v2"
        ),
        None,
    )
    if qa_artifact is None:
        # Obligated dispatch, but it declares no qa-report.v2 artifact (e.g.
        # a ba_validation-mode QA with no e2e obligation): nothing to check.
        return

    task_id = resolution.obligation.get("task_id")
    qa_report_path = Path(project_dir) / qa_artifact["path"]
    if not qa_report_path.is_file():
        sys.stderr.write(
            f"E2E_ENFORCE_BLOCKED: agent {agent_id} (type={ENFORCED_AGENT_TYPE}) "
            f"declared a qa-report.v2 obligation (task_id={task_id}) at "
            f"{qa_artifact['path']} but no such file exists.\n"
            f"QA must produce a report with e2e_enforcement.status before stopping.\n"
        )
        sys.exit(2)

    _enforce_e2e_status(
        qa_report_path,
        agent_id,
        ENFORCED_AGENT_TYPE,
        session_context=f"via obligation fallback (task_id={task_id})",
    )


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

    # Check for force-mode sentinel: /close --force writes this before any QA dispatch.
    # If present, skip E2E enforcement — forced closes dispatch zero QA subagents by design.
    # This is defense-in-depth; the primary fix is the 2-step force-path todo in close.md.
    force_sentinel_pattern = f"{harness_state_dir()}/claude-close-force-{dev_session_id}.flag"
    if glob.glob(force_sentinel_pattern):
        sys.stderr.write(
            f"subagentstop-e2e-enforce: force-mode sentinel found at "
            f"{force_sentinel_pattern}; skipping E2E enforcement.\n"
        )
        sys.exit(0)

    # Read qa_mode from authoritative sentinel (set by orchestrator before dispatch)
    qa_sentinel_path = (
        Path(project_dir) / ".claude" / "dev-registry" / dev_session_id / "qa.json"
    )
    qa_sentinel = _read_json(qa_sentinel_path)
    if qa_sentinel.get("qa_mode") == "ba_validation":
        sys.exit(0)  # BA-validation QA: no E2E obligation; role confirmed by sentinel

    # Find QA report to check e2e_enforcement field (prefer session-correlated,
    # falling back to the orchestrator-anchored task_id from this SAME
    # sentinel -- M4: single source of truth, no second/duplicate task_id source)
    qa_report_path = _find_latest_qa_report(
        project_dir, dev_session_id, task_id=qa_sentinel.get("task_id")
    )
    if qa_report_path is None:
        if _qa_report_expected_absent(project_dir, dev_session_id, qa_sentinel):
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
