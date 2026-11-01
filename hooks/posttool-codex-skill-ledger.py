#!/usr/bin/env python3
"""PostToolUse Hook (Skill): Stamp codex-ledger entry when codex skill is called.

Fires on every PostToolUse for the Skill tool. When tool_input.skill == "codex",
resolves the calling agent's cycle as its consumer, subagentstop-codex-enforce.py,
does (lib/agent_cycle.py: from the agent's own dispatch obligation, else its
agent-index.json entry) and writes a ledger entry to:
    .claude/dev-registry/<DEV_SESSION_ID>/codex-ledger/<agent_id>.json

Fail-open on all error paths: if agent_id is missing or the agent names no
existing cycle registry, exit 0 without blocking.

The quota/timeout semantics: PostToolUse fires on all Skill completions regardless
of whether the codex invocation succeeded. The ledger records the call with a
status field. The subagentstop-codex-enforce.py hook treats any ledger entry as
sufficient — the agent tried; infrastructure failure is not agent non-compliance.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib import agent_cycle, obligation
from lib.agent_resolver import resolve_agent_type


def _now_iso_z() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_stdin() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def _determine_status(data: dict) -> str:
    """Classify the codex call outcome from PostToolUse payload."""
    tool_response = data.get("tool_response") or {}
    if isinstance(tool_response, dict):
        output = tool_response.get("output") or ""
        if isinstance(output, str):
            if "quota" in output.lower() or "usage limit" in output.lower():
                return "quota_error"
            if "timeout" in output.lower():
                return "timeout"
            if "error" in output.lower():
                return "parse_error"
    return "called"


def main() -> None:
    data = _load_stdin()
    if not data:
        sys.exit(0)

    # Only act on Skill tool PostToolUse
    tool_name = data.get("tool_name")
    if tool_name != "Skill":
        sys.exit(0)

    # Only act when skill == "codex"
    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        sys.exit(0)
    if tool_input.get("skill") != "codex":
        sys.exit(0)

    agent_id = data.get("agent_id")
    if not agent_id:
        sys.exit(0)

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    resolution = agent_cycle.own_resolution(data, project_dir)
    own = resolution.obligation if isinstance(resolution, obligation.Resolved) else {}
    registry = agent_cycle.registry_dir(data, own, project_dir)
    if registry is None:
        sys.exit(0)
    dev_session_id = registry.name
    agent_type = resolve_agent_type(data) or ""

    # Determine source_command from any available context
    source_command = data.get("session_type") or data.get("source_command") or "unknown"
    tool_call_id = data.get("tool_use_id") or data.get("tool_call_id") or ""
    status = _determine_status(data)

    ledger_dir = registry / "codex-ledger"
    try:
        ledger_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        sys.exit(0)

    ledger_path = ledger_dir / f"{agent_id}.json"
    ledger_entry = {
        "schema_version": 1,
        "dev_session_id": dev_session_id,
        "agent_id": agent_id,
        "agent_type": agent_type,
        "source_command": source_command,
        "skill": "codex",
        "tool_call_id": tool_call_id,
        "status": status,
        "called_at": _now_iso_z(),
    }

    try:
        ledger_path.write_text(
            json.dumps(ledger_entry, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass  # fail-open: ledger write failure does not block

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
