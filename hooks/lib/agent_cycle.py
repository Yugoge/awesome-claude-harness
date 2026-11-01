"""The cycle registry a subagent works in: one rule for the codex ledger's
producer (posttool-codex-skill-ledger.py) and the hooks that read a cycle's
flags and ledger (subagentstop-codex-enforce.py, subagentstop-e2e-enforce.py).

The agent's own dispatch obligation names it: the registry of its task id
(obligation.registry_dir_for; /close and /commit dispatches share the task's),
else that of the session that dispatched it (/dev-overnight arms its registry
under its session id). Only an agent whose dispatch carries no obligation is
looked up in agent-index.json. A registry that does not exist names no cycle.
"""

from __future__ import annotations

from pathlib import Path

from . import obligation  # imported as lib.agent_cycle (hooks) or hooks.lib.agent_cycle
from .agent_resolver import resolve_dev_registry_entry


def own_resolution(payload: dict, project_dir: str):
    """(obligation.resolve_own_obligation's reading of the agent's own dispatch
    from the hook payload, its obligation when Resolved else {})."""
    resolution = obligation.resolve_own_obligation(
        session_id=payload.get("session_id") or payload.get("sessionId"), agent_id=payload.get("agent_id"),
        project_dir=project_dir, payload_agent_transcript_path=payload.get("agent_transcript_path"))
    return resolution, resolution.obligation if isinstance(resolution, obligation.Resolved) else {}


def registry_dir(payload: dict, own: dict, project_dir: str) -> Path | None:
    """The existing registry of the cycle `own` (the agent's own obligation,
    {} when its dispatch carries none) belongs to, or None."""
    root = Path(project_dir) / ".claude" / "dev-registry"
    if own:
        session = payload.get("session_id") or payload.get("sessionId")
        names = [obligation.registry_dir_for(project_dir, own.get("task_id")), session]
    else:
        names = [(resolve_dev_registry_entry(payload.get("agent_id"), project_dir) or {}).get("dev_session_id")]
    return next((root / n for n in names if isinstance(n, (str, Path)) and n and (root / n).is_dir()), None)
