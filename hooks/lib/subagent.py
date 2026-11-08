"""Subagent detection for Claude Code hooks.

is_subagent_context() and supporting helpers, for the hooks that import it
(the orchestrator gate and lib.allowlist's /do consent decision among them).
Many hooks test the payload's `agent_id` themselves instead, so a payload that
carries only an alias below is a subagent here and the main agent there.
Stdlib-only; Python 3.10+.
"""

import json
import os
from pathlib import Path

SUBAGENT_ID_KEYS: tuple[str, ...] = (
    "agent_id",
    "subagent_id",
    "agent_path",
    "parent_agent_id",
)

SUBAGENT_ENV_KEYS: tuple[str, ...] = (
    "CLAUDE_AGENT_ID",
    "CODEX_AGENT_ID",
    "CODEX_AGENT_PATH",
    "OPENAI_AGENT_ID",
    # presence signals a non-conventional-development compat runtime child environment
    "CLAUDE_COMPAT_RUNTIME",
)


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
        with path.open(errors="ignore") as fh:
            for _ in range(20):
                line = fh.readline()
                if not line:
                    break
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") != "session_meta":
                    continue
                payload = event.get("payload", {})
                source = payload.get("source")
                return isinstance(source, dict) and isinstance(source.get("subagent"), dict)
    except OSError:
        return False
    return False


def is_subagent_context(data: dict) -> bool:
    """Return True when this hook is running inside a subagent.

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

    if _transcript_meta_says_subagent(str(data.get("transcript_path") or "").strip()):
        return True

    return False
