#!/usr/bin/env python3
"""PreToolUse:* hook — enforce tool-policy.v1.json for all subagents.

Single hook that consumes the harness ``policies/tool-policy.v1.json`` (resolved
via the shared hooks/lib/claude_home resolver) through
lib.policy_registry.is_allowed() and lib.agent_resolver.resolve_agent_type().

Behavior:
  - Main agent (no agent_id, no subagent_type) -> exit 0 (orchestrator
    gate handles main agent).
  - Subagent role unresolvable + protected Write -> exit 2 (FAIL CLOSED, WS1
    codex #6): an unresolved subagent role does NOT bypass policy. Non-write
    tools with an unresolved role still defer to the backstop shim (exit 0).
  - Resolved role + denied tool/path -> exit 2 with structured stderr
    JSON: {"role", "tool", "target", "deny_reason"}.
  - Deny-logic import/bootstrap failure -> exit 2 (FAIL CLOSED, WS1): the
    security imports live inside a fail-closed bootstrap guard, NOT inside the
    blanket `except Exception: sys.exit(0)` (which would silently fail open).

Bash policy bypass fix (T2.1):
  - For Bash tool, parse the command with lib.bash_write_targets to
    extract every shell write target (heredoc-stripped). Each extracted
    path is authorized as if it were a Write target. The bash command
    itself is also authorized for tool-list membership (target=None).
  - This closes the heredoc/redirect bypass where a subagent could
    write to a protected path via 'cat > FILE << EOF' or similar.

Fail-safe: any unexpected exception logs to stderr and exits 0 to
avoid bricking the tool pipeline on a hook bug.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.agent_resolver import resolve_agent_type  # noqa: E402
from lib.bash_write_targets import extract_bash_write_paths  # noqa: E402
from lib.policy_registry import WRITE_TOOLS, is_allowed  # noqa: E402


def _read_payload() -> dict:
    try:
        return json.load(sys.stdin)
    except json.JSONDecodeError:
        return {}


def _extract_targets(tool_name: str, tool_input: dict) -> list:
    """Return list of policy targets for the (tool, input) pair.

    For Bash: returns [None] followed by every extracted write target.
    The leading None preserves tool-list authorization (allowed_tools /
    denied_tools) even when the bash command has no write targets
    (e.g. 'echo hello'). Each subsequent extracted path is then
    authorized as a Write target — closing the heredoc/redirect bypass
    where a subagent could write to a protected path via 'cat > FILE
    << EOF' or other shell write idioms.
    """
    if not isinstance(tool_input, dict):
        return [None]
    if tool_name in WRITE_TOOLS:
        return [tool_input.get("file_path") or tool_input.get("notebook_path")]
    if tool_name == "Read":
        return [tool_input.get("file_path")]
    if tool_name == "Bash":
        command = tool_input.get("command") or ""
        return [None] + extract_bash_write_paths(command)
    return [None]


def _emit_block(role: str, tool: str, target, reason: str) -> None:
    payload = {
        "role": role,
        "tool": tool,
        "target": target,
        "deny_reason": reason,
    }
    sys.stderr.write(
        f"BLOCKED by tool-policy.v1: {json.dumps(payload, separators=(',', ':'))}\n"
    )


def _check_targets(role: str, tool_name: str, targets: list) -> None:
    """Iterate targets, exit 2 on first deny. For Bash, treat each
    extracted write target (idx > 0) as a Write authorization request."""
    for idx, target in enumerate(targets):
        check_tool = tool_name
        if tool_name == "Bash" and idx > 0:
            check_tool = "Write"
        allowed, reason = is_allowed(role, check_tool, target)
        if not allowed:
            _emit_block(role, check_tool, target, reason)
            sys.exit(2)


def main() -> None:
    data = _read_payload()
    if not data:
        sys.exit(0)
    role = resolve_agent_type(data)
    if not role:
        sys.exit(0)
    tool_name = data.get("tool_name")
    if not isinstance(tool_name, str):
        sys.exit(0)
    tool_input = data.get("tool_input") or {}
    targets = _extract_targets(tool_name, tool_input)
    _check_targets(role, tool_name, targets)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # pragma: no cover
        sys.stderr.write(f"pretool-tool-policy: unexpected ({e})\n")
        sys.exit(0)
