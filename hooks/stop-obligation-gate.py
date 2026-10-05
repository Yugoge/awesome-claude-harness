#!/usr/bin/env python3
"""Stop hook: session-terminal obligation gate (G4, ticket 20260930-132644-l4).

A dev-family session (/dev, /dev-command, /redev, or any /dev-overnight-
internal cycle) dispatches producer subagents carrying an ``<obligation
v="1">`` block declaring the artifact(s) they must deliver. Nothing
previously checked, at the ORCHESTRATING session's own stop time, whether
every obligation its OWN dispatches created was actually discharged -- a
session could appear to end normally while a dispatched producer never
delivered its declared artifact. This gate is that session-terminal
backstop (the per-artifact, producer-side check is a separate SubagentStop-
level concern -- hooks/subagentstop-artifact-contract-enforce.py -- out of
this lane's scope).

MODE (env CLAUDE_OBLIGATION_TERMINAL): "advisory" (default, unset) | "block"
| "off". Shared with the sibling conditions this ticket adds to
hooks/posttool-overnight-loop.py -- ONE switch governs both halves of this
gate (G4; turn-1-one-shot-blueprint.md's L4 section titles BOTH mechanisms
under the same gate). ADVISORY-FIRST for the same reason
stop-do-report-gate.py is: a buggy BLOCKING Stop hook on the MAIN session
traps every session exit project-wide -- worse blast radius than a scoped
SubagentStop hook.

No command-based exemption (removed, ticket 20261001-161041-r21 M1): a
session whose transcript's first user-turn message is "/close" or "/commit"
is classified and re-checked exactly like any other dev-family session --
those are precisely the sessions that dispatch close/commit's own producer
obligations (QA's reports, changelog-analyst's response_block), so
unconditionally exempting them defeated this gate for its intended
beneficiaries. LOW-10 (scenario (e): a session with no dev-family obligation
at all still exits 0, every mode) remains the correct fail-open path for
non-obligated sessions, /close/`/commit` included.

Dev-family classification + obligation re-check: delegated entirely to
hooks.lib.obligation.find_unresolved_dispatch_obligations -- the shared
scan-and-check algorithm this gate shares with
hooks/posttool-overnight-loop.py's new reset conditions. Do not duplicate
that scan here.

FAIL-SAFE: any unexpected error during classification -> exit 0 (allow stop)
plus one best-effort "gate_error" advisory record. No network, no
subprocess, read-only filesystem access only.

Exit codes: 0 = allow stop; 2 = block stop (block mode only; stderr names,
per unresolved artifact, what is unmet / whose responsibility it is / how to
satisfy it).
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path

ADVISORY_LOG = Path.home() / ".claude" / "logs" / "obligation-terminal-gate-advisory.jsonl"
_HOOKS_DIR = Path(__file__).resolve().parent


def _log_event(record: dict) -> None:
    """Best-effort append to the advisory log. Never affects exit."""
    try:
        ADVISORY_LOG.parent.mkdir(parents=True, exist_ok=True)
        record["ts"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with open(ADVISORY_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _import_obligation_lib():
    """Lazy import of hooks/lib/obligation.py (mirrors stop-do-report-gate.py's
    lazy ``from lib import contract_runtime`` pattern)."""
    if str(_HOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(_HOOKS_DIR))
    from lib import obligation  # type: ignore

    return obligation


def _find_unresolved(transcript_path: str, project_dir: str) -> list[dict]:
    """Dev-family classification + obligation re-check (shared algorithm)."""
    obligation = _import_obligation_lib()
    return obligation.find_unresolved_dispatch_obligations(transcript_path, project_dir)


def _format_block_message(item: dict) -> str:
    """Three-element line: what is unmet / whose responsibility / how to fix
    (ticket item 5 exact template: ``<artifact_path>: <what problem> |
    owner: <role>(<lane>) | fix: <one-sentence action>``)."""
    artifact_path = item.get("artifact_path") or "<unknown artifact>"
    role = item.get("role") or "unknown-role"
    lane = item.get("lane") or "unknown-lane"
    task_id = item.get("task_id") or "unknown-task"
    return (
        f"[obligation-terminal] {artifact_path}: obligation unmet -- artifact missing "
        f"or schema-invalid under task {task_id} | owner: {role}({lane}) | "
        f"fix: have the {role} producer for task {task_id} regenerate {artifact_path} "
        "per its obligation-declared schema, then stop again\n"
    )


def main() -> int:
    mode = (os.environ.get("CLAUDE_OBLIGATION_TERMINAL", "advisory") or "advisory").strip().lower()
    if mode == "off":
        return 0

    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    transcript_path = str(payload.get("transcript_path") or "")
    session_id = str(
        payload.get("session_id")
        or os.environ.get("CLAUDE_CODE_SESSION_ID")
        or os.environ.get("CLAUDE_SESSION_ID")
        or ""
    )

    project_dir = str(
        Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd())
    )

    try:
        if not transcript_path or not Path(transcript_path).is_file():
            return 0
        unresolved = _find_unresolved(transcript_path, project_dir)
    except Exception as exc:  # item 6: fail-open on ANY unexpected error
        _log_event({"event": "gate_error", "session_id": session_id, "error": repr(exc)})
        return 0

    if not unresolved:
        return 0

    if mode != "block":
        for item in unresolved:
            _log_event({"event": "would_block", "mode": mode, "session_id": session_id, **item})
        return 0

    for item in unresolved:
        sys.stderr.write(_format_block_message(item))
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # FAIL-SAFE: a gate bug must never trap the session
        try:
            _log_event({"event": "gate_error", "error": repr(exc)})
        except Exception:
            pass
        sys.exit(0)
