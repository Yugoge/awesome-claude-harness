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
    SendMessage passes only lib/send_policy.decide: the exact, validated /restart
    recovery message to a pending candidate, or a send to this session's own
    finished subagent dispatched with no obligation outside every gated span.
    Workflow is blocked, except one call an `/allow Workflow` grant names.
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
from lib.allowlist import has_do_consent, match_sentinel_grant_for_tool  # noqa: E402
from lib.subagent import DISPATCH_TOOLS  # noqa: E402


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
# The active-interview detection is pretool-spec-block-foreground-agent.py's own
# (lib.todo_canonical.live_spec_checklist: the transcript's active span is /spec,
# its checklist has an incomplete step, and the span was not abandoned by a human
# prompt that followed it while Steps 1-3a were open), so the two hooks agree on
# the /spec FSM window.


def _spec_interview_active(payload: dict) -> bool:
    """True iff the active span is a live /spec interview: its checklist (the
    last ok TodoWrite, or the canonical list before the first) has an
    incomplete step and the span was not abandoned, read from the transcript
    (lib.todo_canonical.live_spec_checklist). Any exception -> False:
    fail-safe (the hole stays SHUT) AND never-wedge (the hook must never exit
    1 on this matcher=None path)."""
    try:
        from lib.todo_canonical import live_spec_checklist  # only this exemption pays the import
        return live_spec_checklist(payload.get("transcript_path")) is not None
    except Exception:  # noqa: BLE001 — never raise: fail-safe (shut) + never-wedge
        return False


def _is_spec_explore_exempt(tool_name, params, payload: dict) -> bool:
    """Narrow exemption: an EXPLICIT background Explore agent during a live /spec
    interview. Everything else (other subagent types, other tools, non-/spec
    sessions, absent run_in_background) is NOT exempt and stays blocked."""
    if tool_name not in DISPATCH_TOOLS:
        return False
    if params.get("run_in_background") is not True:
        return False
    if params.get("subagent_type") != "Explore":
        return False
    return _spec_interview_active(payload)


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

    # SendMessage resumes a child asynchronously, so the main agent's send passes only
    # lib/send_policy.decide: a /restart candidate gets the exact recovery message and
    # nothing else (lesson 16); any other target must be this session's own finished
    # subagent, dispatched with no obligation and outside every gated command's span.
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
        print(
            f"[BLOCK] SendMessage refused for the orchestrator: {send_reason}\n"
            "Dispatch new work with Agent(run_in_background=false), or use /do.",
            file=sys.stderr,
        )
        sys.exit(2)

    # Workflow spawns a whole background fleet and has no synchronous mode: blocked,
    # except the one call an `/allow Workflow` grant names (posttool-allowlist-consume.py
    # spends the grant after that call, so the next one is refused again).
    if tool_name == "Workflow":
        sid = payload.get("session_id") or os.environ.get("CLAUDE_SESSION_ID", "default")
        try:
            if match_sentinel_grant_for_tool(sid, "Workflow") is not None:
                sys.exit(0)
        except Exception:  # noqa: BLE001 — an unreadable grant is no grant
            pass
        print(
            "[BLOCK] Workflow runs agents in the background and is forbidden for "
            "the orchestrator.\n"
            "There is no synchronous mode; dispatch work with "
            "Agent(run_in_background=false), or use /do; an owner's /allow Workflow grant admits exactly one.",
            file=sys.stderr,
        )
        sys.exit(2)

    # Non-dict params (malformed) → treat as empty so Agent/Task still block and
    # the hook never crashes into an exit-1 fail-open.
    if not isinstance(params, dict):
        params = {}

    rib = params.get("run_in_background")

    # Narrow /spec Explore hole: allow an EXPLICIT background Explore agent while a
    # /spec interview is active (restores the legitimate non-blocking Step-3 codebase
    # exploration that pretool-spec-block-foreground-agent.py already exempts). Bounded
    # to Agent/Task + subagent_type=="Explore" + run_in_background is True + live /spec
    # FSM window — arbitrary orchestrator background work remains blocked.
    if _is_spec_explore_exempt(tool_name, params, payload):
        sys.exit(0)

    # Agent and Task default to BACKGROUND when the field is absent, so anything
    # other than an explicit False (i.e. True or None/absent) is a background
    # dispatch and is blocked.
    if tool_name in DISPATCH_TOOLS and rib is not False:
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
