#!/usr/bin/env python3
"""
PreToolUse hook: block background execution on Bash/SendMessage/Workflow for the
orchestrator; Agent/Task dispatches pass in either mode.

ENFORCEMENT (default disposition matters):
  - Agent / Task → pass, foreground or background (the owner's decision of 2026-11-21:
    every role, every command, /dev-overnight included); what a return runs, a background
    child's end runs (hooks/posttool-dispatch-record.py).
  - Bash → foreground is the default, so only an explicit True is a background
    task (exit 2); absent/False is fine.
  - SendMessage / Workflow → inherently background with NO synchronous mode.
    SendMessage passes lib/send_policy.decide: a send to another session is allowed;
    a send to this session's own subagent is a dispatch, judged by the dispatch gate;
    none in the overnight wake's turn after the owner's /stop.
    Workflow is blocked, except one call an `/allow Workflow` grant names.
  - Subagents (agent_id truthy) → exit 0 (no restriction)
  - /do consent active → exit 0 (bypass)

FAIL-OPEN, never-wedge:
  This hook has matcher=None and runs on EVERY tool call, so a hard failure on a
  malformed payload would wedge the whole session. Matching pretool-orchestrator-gate,
  an unparseable or non-object payload fails OPEN (exit 0). The real harness always
  sends a well-formed object, so this path costs nothing in practice.

RATIONALE:
  An orchestrator background shell or Workflow fleet has no end the harness sees;
  a background dispatch has one, its child's SubagentStop and task-notification.
"""
import os, sys  # noqa: E401 -- the harness switch (hooks/lib/harness_switch.py): no harness hook runs while /harness off holds
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))
try:  # a hook copied without its lib/ (an old install) is on
    import harness_switch  # noqa: E402
    harness_switch.exit_if_off()
except ImportError:
    pass
finally:
    sys.path.pop(0)
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.allowlist import has_do_consent  # noqa: E402


def first_present(mapping, names, default=None):
    """Return the value of the first key that is PRESENT (even if falsy).

    An empty canonical ``tool_input: {}`` must win over a stray ``params`` alias,
    so presence — not truthiness — selects the field.
    """
    for name in names:
        if name in mapping:
            return mapping[name]
    return default


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

    # Subagents exempt. Truthiness (not presence) matches every other gate hook —
    # the main agent may carry agent_id=null, which must NOT count as a subagent.
    if agent_id:
        sys.exit(0)

    if has_do_consent(payload):
        sys.exit(0)

    # The main agent's send passes lib/send_policy.decide (lesson 16): a send to an own
    # subagent is judged as the dispatch it is; any other target is another session's.
    # Import inside the branch so a missing helper cannot wedge unrelated tools;
    # SendMessage fails CLOSED on any helper error.
    if tool_name == "SendMessage":
        try:
            from lib.send_policy import decide

            send_ok, send_reason = decide(payload)
        except Exception as exc:  # noqa: BLE001 — the policy's default is deny
            send_ok, send_reason = False, f"SendMessage policy unavailable: {exc}"
        if send_ok:
            sys.exit(0)
        print(f"[BLOCK] SendMessage refused for the orchestrator: {send_reason}", file=sys.stderr)
        sys.exit(2)

    # Workflow spawns a whole background fleet and has no synchronous mode: blocked,
    # except the one call an owner's /allow grant releases where the pre-tool verdicts
    # meet (lib/hook_launch.release_refused).
    if tool_name == "Workflow":
        print(
            "[BLOCK] Workflow runs agents in the background and is forbidden for "
            "the orchestrator.\n"
            "There is no synchronous mode; dispatch work with "
            "Agent, or use /do; an owner's /allow Workflow grant admits exactly one.",
            file=sys.stderr,
        )
        sys.exit(2)

    # Non-dict params (malformed) → treat as empty so the hook never crashes into
    # an exit-1 fail-open.
    if not isinstance(params, dict):
        params = {}

    rib = params.get("run_in_background")

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
