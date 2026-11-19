"""Subagent detection for Claude Code hooks.

is_subagent(): whether the calling agent is a subagent, the one predicate of that fact (a
payload identity key, an environment name of a spawned agent, or a Codex child's transcript
meta). is_subagent_context(): that, or a compat runtime (CLAUDE_COMPAT_RUNTIME), for the hooks
that exempt both from the main agent's rules (the orchestrator gate and lib.allowlist's /do
consent decision among them). A hook that needs the subagent's own id (to find its transcript)
still reads the payload's `agent_id`. Stdlib-only; Python 3.10+.
"""

import json
import os
from pathlib import Path

# The tool names under which a subagent is dispatched: "Agent", and "Task", the name the CLI
# used before and still accepts (a transcript records the name the model called; hooks are
# handed "Agent", hooks/tests/test_agent_tool_name_pin.py). Every hook, transcript reader and
# launcher rule that asks "is this call a dispatch" reads this one tuple.
DISPATCH_TOOLS: tuple[str, ...] = ("Agent", "Task")

# Top-level payload keys that carry a subagent's identity: Claude Code's agent_id, and the
# aliases a Codex child's tool event carries.
SUBAGENT_ID_KEYS: tuple[str, ...] = (
    "agent_id",
    "subagent_id",
    "agent_path",
    "parent_agent_id",
    "parent_thread_id",
    "parent_session_id",
)

# Environment names that mark the process as a spawned agent's.
SUBAGENT_ENV_KEYS: tuple[str, ...] = (
    "CLAUDE_AGENT_ID",
    "CLAUDE_SUBAGENT_ID",
    "CODEX_AGENT_ID",
    "CODEX_AGENT_PATH",
    "OPENAI_AGENT_ID",
)

# Set for every call of a compat runtime ("codex": its main session and its children alike),
# so it marks the runtime, not a subagent; is_subagent_context exempts it as before.
COMPAT_RUNTIME_ENV = "CLAUDE_COMPAT_RUNTIME"


def _truthy(value) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip() not in {"", "0", "false", "False", "null", "None"}
    return bool(value)


def _transcript_meta_says_subagent(transcript_path: str) -> bool:
    """Detect Codex spawned-agent transcripts from their session metadata."""
    if not transcript_path:
        return False
    path = Path(transcript_path)
    try:
        with path.open(encoding="utf-8", errors="ignore") as fh:
            for _ in range(20):
                line = fh.readline()
                if not line:
                    break
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict) or event.get("type") != "session_meta":
                    continue
                payload = event.get("payload")
                source = payload.get("source") if isinstance(payload, dict) else None
                return isinstance(source, dict) and isinstance(source.get("subagent"), dict)
    except OSError:
        return False
    return False


def is_subagent(data: dict) -> bool:
    """Return True when the calling agent is a subagent.

    The canonical Claude hook payload contains top-level `agent_id`.  Codex
    compatibility can run the same hook without that exact field even though
    the call is inside a spawned agent.  This helper accepts equivalent
    top-level identity aliases and environment aliases, but deliberately does
    not inspect `tool_input.subagent_type`: that field belongs to main-agent
    Agent dispatch calls and would incorrectly exempt the orchestrator.
    """
    if any(_truthy(data.get(key)) for key in SUBAGENT_ID_KEYS):
        return True
    if any(_truthy(os.environ.get(key)) for key in SUBAGENT_ENV_KEYS):
        return True

    # A spawned agent's session_meta is a Codex transcript's record (a Claude Code transcript has
    # none), so the transcript is read only under a compat runtime: a Claude Code call never opens it.
    if (_truthy(os.environ.get(COMPAT_RUNTIME_ENV)) or data.get("runtime") or data.get("client")) \
            and _transcript_meta_says_subagent(str(data.get("transcript_path") or "").strip()):
        return True

    return False


def is_subagent_context(data: dict) -> bool:
    """Return True when this hook runs for a subagent (is_subagent) or under a compat runtime."""
    return is_subagent(data) or _truthy(os.environ.get(COMPAT_RUNTIME_ENV))
