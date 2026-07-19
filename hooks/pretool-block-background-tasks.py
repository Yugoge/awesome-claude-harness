#!/usr/bin/env python3
"""
PreToolUse hook: block background execution on Agent/Task/Bash/SendMessage/Workflow
for the orchestrator.

ENFORCEMENT (default disposition matters):
  - Agent / Task → background is the DEFAULT, so the field is usually ABSENT.
    Block unless run_in_background is explicitly False (True or absent → exit 2).
  - Bash → foreground is the default, so only an explicit True is a background
    task (exit 2); absent/False is fine.
  - SendMessage / Workflow → inherently background with NO synchronous mode.
    SendMessage drives/resumes a teammate async (regardless of how it was spawned);
    Workflow spawns a background agent fleet. Both are blocked outright (exit 2) —
    for the orchestrator they ARE background-agent execution.
  - Subagents (agent_id truthy) → exit 0 (no restriction)
  - /do consent active → exit 0 (bypass)

FAIL-OPEN, never-wedge:
  This hook has matcher=None and runs on EVERY tool call, so a hard failure on a
  malformed payload would wedge the whole session. Matching pretool-orchestrator-gate,
  an unparseable or non-object payload fails OPEN (exit 0). The real harness always
  sends a well-formed object, so this path costs nothing in practice.

RATIONALE:
  Orchestrator background tasks bypass harness monitoring and create
  unmanageable execution state. All work must be synchronous and observable.
  Because Agent/Task run in the background *by default*, guarding only against an
  explicit run_in_background=true lets every default-dispatch slip through — the
  orchestrator must be forced to opt into synchronous execution.
"""
import json
import os
import sys
from pathlib import Path


def first_present(mapping, names, default=None):
    """Return the value of the first key that is PRESENT (even if falsy).

    An empty canonical ``tool_input: {}`` must win over a stray ``params`` alias,
    so presence — not truthiness — selects the field.
    """
    for name in names:
        if name in mapping:
            return mapping[name]
    return default


# --- Narrow /spec Explore exemption --------------------------------------
# /spec Step 3 legitimately dispatches a NON-BLOCKING background Explore agent
# for codebase exploration, and pretool-spec-block-foreground-agent.py exempts
# exactly that (run_in_background is True). This blanket background block would
# otherwise kill that one legitimate /spec background use. The exemption below is
# deliberately narrow — ONLY a background Explore agent, ONLY while a /spec
# interview is active — so arbitrary orchestrator background work stays blocked
# and the observability policy holds for everything else.
#
# The active-interview detection MIRRORS pretool-spec-block-foreground-agent.py
# (bookmark command == "spec" AND at least one incomplete todo step) so the two
# hooks agree on the /spec FSM window.


def _load_json(path):
    """Read and json-parse a file. Return None on any failure (never wedge)."""
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _spec_interview_active(session_id: str) -> bool:
    """True iff a /spec interview bookmark is active AND has an incomplete step.

    Mirrors pretool-spec-block-foreground-agent.py exactly (same bookmark path,
    same command check, same todos-incomplete check) so the two hooks share one
    /spec-active definition. Any failure returns False (fail-safe: the block
    stands rather than opening the hole on corrupt state)."""
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    bookmark = _load_json(project_dir / ".claude" / f"workflow-{session_id}.json")
    if not isinstance(bookmark, dict) or bookmark.get("command") != "spec":
        return False
    todos = _load_json(
        Path.home() / ".claude" / "todos" / f"{session_id}-agent-{session_id}.json"
    )
    if not isinstance(todos, list) or not todos:
        return False
    incomplete = any(
        isinstance(t, dict) and t.get("status") != "completed" for t in todos
    )
    return incomplete


def _is_spec_explore_exempt(tool_name, params, session_id: str) -> bool:
    """Narrow exemption: an EXPLICIT background Explore agent during a live /spec
    interview. Everything else (other subagent types, other tools, non-/spec
    sessions, absent run_in_background) is NOT exempt and stays blocked."""
    if tool_name not in {"Agent", "Task"}:
        return False
    if params.get("run_in_background") is not True:
        return False
    if params.get("subagent_type") != "Explore":
        return False
    return _spec_interview_active(session_id)


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)  # never wedge: malformed payload fails open (matches pretool-orchestrator-gate)

    if not isinstance(payload, dict):
        sys.exit(0)  # bare JSON list/scalar → fail open; never wedge the session

    # Use correct field names with fallbacks
    tool_name = payload.get("tool_name") or payload.get("tool") or payload.get("toolName") or ""
    # A non-string tool_name (e.g. a JSON list) is unhashable; feeding it to the
    # `in {...}` set test below would raise TypeError → exit 1. Coerce to "" so it
    # simply fails to match and falls through to the fail-open exit (never-wedge).
    if not isinstance(tool_name, str):
        tool_name = ""
    params = first_present(payload, ("tool_input", "params", "toolInput"), {})
    agent_id = payload.get("agent_id") or payload.get("agentId")
    session_id = (
        payload.get("session_id")
        or payload.get("sessionId")
        or os.environ.get("CLAUDE_SESSION_ID")
        or "default"
    )

    # Subagents exempt. Truthiness (not presence) matches every other gate hook —
    # the main agent may carry agent_id=null, which must NOT count as a subagent.
    if agent_id:
        sys.exit(0)

    # /do consent bypass - use correct sentinel path
    do_sentinel = Path(f"/tmp/claude-orchestrator-consent-{session_id}.flag")
    if do_sentinel.exists():
        sys.exit(0)

    # SendMessage drives/resumes a background teammate (even one that was spawned
    # synchronously — a send resumes it from its transcript and runs it async);
    # Workflow spawns a whole background agent fleet and returns immediately. Neither
    # has a synchronous mode, so for the orchestrator they ARE background-agent
    # execution — block outright. (Subagent + /do bypasses already applied above.)
    # No run_in_background field is consulted; these tools have none.
    if tool_name in {"SendMessage", "Workflow"}:
        print(
            f"[BLOCK] {tool_name} runs agents in the background and is forbidden for "
            "the orchestrator.\n"
            "There is no synchronous mode; dispatch work with "
            "Agent(run_in_background=false), or use /do.",
            file=sys.stderr,
        )
        sys.exit(2)

    # Non-dict params (malformed) → treat as empty so Agent/Task still block and
    # the hook never crashes into an exit-1 fail-open.
    if not isinstance(params, dict):
        params = {}

    rib = params.get("run_in_background")

    # Agent and Task default to BACKGROUND when the field is absent, so anything
    # other than an explicit False (i.e. True or None/absent) is a background
    # dispatch and is blocked.
    if tool_name in {"Agent", "Task"} and rib is not False:
        print(
            f"[BLOCK] {tool_name} runs in the background by default and is forbidden "
            "for the orchestrator.\n"
            "Pass run_in_background=false for synchronous execution, or use /do.",
            file=sys.stderr,
        )
        sys.exit(2)

    # Bash defaults to FOREGROUND, so only an explicit True is a background task.
    if tool_name == "Bash" and rib is True:
        print(
            "[BLOCK] Bash(run_in_background=true) is forbidden for orchestrator.\n"
            "All work must run synchronously. Remove run_in_background or use /do.",
            file=sys.stderr,
        )
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
