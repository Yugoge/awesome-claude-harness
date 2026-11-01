#!/usr/bin/env python3
"""SubagentStop Hook: Block a subagent asked to consult codex that did not call the codex skill.

Activation logic:
  1. Read agent_id from stdin. If absent, exit 0 (non-subagent stop).
  2. Read the agent's own dispatch obligation (hooks/lib/obligation.py's
     reader of its transcript). It names the cycle (lib/agent_cycle.py): the
     registry of its task, else of the session that dispatched it; a dispatch
     without one, by its agent-index.json entry. No cycle: exit 0 (fail-open).
  3. The role is Claude Code's record of the agent
     (lib.agent_resolver.resolve_agent_type).
  4. Check the cycle's codex-enforce.json.
     If absent or enabled != true: exit 0 (no enforcement for this cycle).
  5. Check the cycle's codex-ledger/<agent_id>.json.
     If present: exit 0.
  6. Its own dispatch prompt is bound when it carries the line
     `codex_required: true`, or when the dispatch template it was made from
     (hooks/lib/dispatch_template.py: the command its obligation names, else
     the command whose span holds the dispatch) carries that line: the session
     runs --codex, so a dispatch of that template without the line is the
     orchestrator's omission. The command text puts the line in exactly the
     dispatches that must consult codex (every BA / QA / dev dispatch under
     --codex, and any other whose template adds it); the agent's own file
     activates codex on it. No role list here says which agents are bound.
     A dispatch whose own obligation names pipeline close or commit is not
     bound by the flag. Unbound: exit 0. Bound: exit 2 ("CODEX_ENFORCE_BLOCKED").

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
from lib import agent_cycle, dispatch_template, obligation
from lib.agent_resolver import resolve_agent_type

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

    # The agent's own obligation names its cycle (P6 R4); the role is Claude
    # Code's record of the agent.
    resolution = agent_cycle.own_resolution(data, project_dir)
    own = resolution.obligation if isinstance(resolution, obligation.Resolved) else {}
    registry = agent_cycle.registry_dir(data, own, project_dir)
    if registry is None or not _read_json(registry / "codex-enforce.json").get("enabled"):
        # No cycle, or no (or a disabled) enforcement flag in it
        sys.exit(0)
    dev_session_id = registry.name
    agent_type = resolve_agent_type(data) or ""

    if (registry / "codex-ledger" / f"{agent_id}.json").exists():
        # Agent called codex: allow stop
        sys.exit(0)

    # Bound only when its own dispatch, or the template it was made from, asks
    # for codex. /close and /commit dispatches share the task's registry, whose
    # codex flag /dev --codex armed for /dev's own; the role is bound as G2 binds it.
    if own.get("pipeline") in ("close", "commit") and (not agent_type or own.get("role") == agent_type):
        sys.exit(0)
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
