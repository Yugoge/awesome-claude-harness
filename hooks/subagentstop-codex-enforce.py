#!/usr/bin/env python3
"""SubagentStop Hook: Block a subagent asked to consult codex that did not call the codex skill.

Activation logic:
  1. Read agent_id from stdin. If absent, exit 0 (non-subagent stop).
  2. Resolve agent entry via resolve_dev_registry_entry(agent_id, project_dir).
     If None (agent not in agent-index.json — skipped FIRST ACTION sentinel):
       exit 0 (fail-open). Rationale: other hooks enforce FIRST ACTION; a
       false-positive block here is more harmful than a miss.
  3. If dev_session_id is None (legacy flat-string entry): exit 0 (fail-open).
  4. Check .claude/dev-registry/<dev_session_id>/codex-enforce.json.
     If absent or enabled != true: exit 0 (no enforcement for this session).
  5. Check .claude/dev-registry/<dev_session_id>/codex-ledger/<agent_id>.json.
     If present: exit 0.
  6. Read the agent's own dispatch prompt (hooks/lib/obligation.py's reader
     of its transcript). It is bound when it carries the line
     `codex_required: true`, or when the dispatch template it was made from
     (hooks/lib/dispatch_template.py: the command its obligation names, else
     the command whose span holds the dispatch) carries that line: the session
     runs --codex, so a dispatch of that template without the line is the
     orchestrator's omission. The command text puts the line in exactly the
     dispatches that must consult codex (every BA / QA / dev dispatch under
     --codex, and any other whose template adds it); the agent's own file
     activates codex on it. No role list here says which agents are bound.
     Unbound: exit 0. Bound: exit 2 with "CODEX_ENFORCE_BLOCKED" message.

Exit codes:
  0: Allow stop (pass-through).
  2: Block stop (CODEX_ENFORCE_BLOCKED — agent must call codex before stopping).
"""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib import dispatch_template, obligation
from lib.agent_resolver import resolve_dev_registry_entry

CODEX_REQUIRED_LINE = re.compile(r"^\s*codex_required:\s*true\s*$", re.M)


def _load_stdin() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _template_asks(resolution, agent_type: str, transcript) -> bool:
    """Whether the dispatch template this agent was dispatched from carries
    the line `codex_required: true`."""
    prompt = getattr(resolution, "prompt", "") or ""
    transcript = getattr(resolution, "transcript_path", None) or transcript
    found = dispatch_template.dispatch_of(transcript) if transcript else None
    own = getattr(resolution, "obligation", None) or {}
    command = own.get("pipeline") or (found[0] if found else None)
    template = dispatch_template.template_of(command, found[1] if found else agent_type, prompt) if command else None
    return bool(template and CODEX_REQUIRED_LINE.search(template))


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
        # Agent not in index: fail-open
        sys.exit(0)

    dev_session_id = entry.get("dev_session_id")
    if not dev_session_id:
        # Legacy flat-string entry: no session correlation, skip enforcement
        sys.exit(0)

    agent_type = entry.get("agent_type", "")

    # Check enforcement flag
    enforce_path = Path(project_dir) / ".claude" / "dev-registry" / dev_session_id / "codex-enforce.json"
    if not enforce_path.exists():
        # No enforcement flag for this session
        sys.exit(0)

    enforce_data = _read_json(enforce_path)
    if not enforce_data.get("enabled"):
        # Enforcement explicitly disabled
        sys.exit(0)

    # Check codex ledger
    ledger_path = Path(project_dir) / ".claude" / "dev-registry" / dev_session_id / "codex-ledger" / f"{agent_id}.json"
    if ledger_path.exists():
        # Agent called codex: allow stop
        sys.exit(0)

    # Bound only when its own dispatch, or the template it was made from, asks
    # for codex (read last: only an agent about to be blocked has its
    # transcript read).
    resolution = obligation.resolve_own_obligation(
        session_id=data.get("session_id") or data.get("sessionId"),
        agent_id=agent_id,
        project_dir=project_dir,
        payload_agent_transcript_path=data.get("agent_transcript_path"),
    )
    if (not CODEX_REQUIRED_LINE.search(getattr(resolution, "prompt", "") or "")
            and not _template_asks(resolution, agent_type, data.get("agent_transcript_path"))):
        sys.exit(0)

    # No ledger entry: block stop
    sys.stderr.write(
        f"CODEX_ENFORCE_BLOCKED: agent {agent_id} (type={agent_type}) has not called "
        f"codex skill in session {dev_session_id}.\n"
        f"Call Skill(skill='codex') before stopping, or ask the orchestrator to "
        f"disable enforcement if codex is genuinely unavailable.\n"
    )
    sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
