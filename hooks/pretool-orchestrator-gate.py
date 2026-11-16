#!/usr/bin/env python3
"""
PreToolUse Hook: Orchestrator Gate (Unified)

Three-tier policy for the main agent:
  1. ALWAYS_ALLOWED whitelist tools pass, but Bash is capped at 5 calls
     (6th blocked) until an Agent dispatch or the next prompt resets the
     count; other tools between the Bash calls do not.
  2. Non-whitelist tools are allowed once TOTAL per tool name per turn
     (2nd same-name call blocked regardless of intervening tool calls).
     Inside the session's open /dev-overnight window (lib/overnight
     window_open) an Agent dispatch also resets these counts: the unattended
     session is one turn, so there the turn's budget is the one between two
     dispatches.
  3. PERMANENTLY_BLOCKED (EnterPlanMode, ExitPlanMode) are blocked even
     with /do consent; an /allow grant naming the tool is the one way
     through.

bash_consecutive is a Bash-ONLY accumulator: only a Bash tool call
increments it. An Agent (subagent) dispatch resets it to
{"last_tool": "Agent", "count": 0} (and, inside an open overnight window,
empties per_tool_counts), and hooks/prompt-workflow.py removes the whole
state file (per_tool_counts too) at each prompt. Every other tool
(Read, TodoWrite, Glob, Grep, and any non-whitelist tool) leaves
bash_consecutive byte-unchanged — interleaving a non-Agent tool between
Bash calls does NOT launder the streak. The Agent-clear lives in main()
and fires on the PreToolUse Agent attempt BEFORE the /allow and /do
short-circuits, so a subagent dispatch resets the streak even under
consent/grant.

Subagents (lib.subagent.is_subagent_context) are fully exempt and do NOT
update the streak state.

/do consent (lib.allowlist.has_do_consent) bypasses the limits AND does not
update the streak state.

A session whose open command span runs on an older command text than
commands/<command>.md (in flight across an update, D15; detected as
pretool-todo-validate.py's _in_flight detects it) reads each refusal in
origin/master's (2acc29b's) wording; the rule and the counts are the same.

State file: <state dir>/claude-tool-streak-<sid>.json --
  {"schema_version": 2, "per_tool_counts": {"Edit": 1},
   "bash_consecutive": {"last_tool": "Bash", "count": 2}}
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
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.subagent import is_subagent_context  # noqa: E402
from lib.allowlist import (  # noqa: E402
    has_do_consent, match_sentinel_grant_for_tool, tool_streak_path, write_tool_streak)

ALWAYS_ALLOWED = {
    "Agent",
    "TodoWrite",
    "AskUserQuestion",
    "Skill",
    "CronCreate",
    "CronDelete",
    "CronList",
    "ScheduleWakeup",
    "Bash",
    "Read",
    "Glob",
    "Grep",
}

PERMANENTLY_BLOCKED = {
    "EnterPlanMode",
    "ExitPlanMode",
}

BASH_MAX_CONSECUTIVE = 5
NON_WHITELIST_MAX_CONSECUTIVE = 1


def get_session_id(data: dict) -> str:
    sid = data.get("session_id") or os.environ.get("CLAUDE_SESSION_ID", "")
    if sid:
        return sid
    sys.stderr.write("[Orchestrator Gate] WARNING: session_id unavailable, using shared default\n")
    return "default"


def _fresh_state() -> dict:
    return {"schema_version": 2, "per_tool_counts": {}, "bash_consecutive": {"last_tool": "", "count": 0}}


def _parse_streak_state(data) -> dict:
    if not isinstance(data, dict) or data.get("schema_version") != 2:
        return _fresh_state()
    per_tool = data.get("per_tool_counts")
    bash_con = data.get("bash_consecutive")
    if not isinstance(per_tool, dict) or not isinstance(bash_con, dict):
        return _fresh_state()
    if not isinstance(bash_con.get("last_tool"), str) or not isinstance(bash_con.get("count"), int):
        return _fresh_state()
    # Validate per_tool_counts VALUES are ints (bool excluded) so a corrupt
    # on-disk value can never crash the non-whitelist increment downstream
    # (counts.get(tool, 0) + 1) — fail-open: drop non-int entries rather than
    # wedge the gate.
    per_tool = {k: v for k, v in per_tool.items() if isinstance(v, int) and not isinstance(v, bool)}
    return {"schema_version": 2, "per_tool_counts": per_tool, "bash_consecutive": bash_con}


def read_streak_state(state_file: Path) -> dict:
    try:
        if state_file.exists():
            return _parse_streak_state(json.loads(state_file.read_text()))
    except (ValueError, OSError, json.JSONDecodeError):
        pass
    return _fresh_state()


def update_streak(session_id: str, tool_name: str) -> int:
    state = read_streak_state(tool_streak_path(session_id))

    if tool_name in ALWAYS_ALLOWED:
        if tool_name == "Bash":
            bash = state["bash_consecutive"]
            if bash["last_tool"] == "Bash":
                bash["count"] += 1
            else:
                bash["last_tool"] = "Bash"
                bash["count"] = 1
            write_tool_streak(session_id, state)
            return bash["count"]
        else:
            # Non-Bash whitelist (incl. Agent, Read, TodoWrite, Glob, Grep,
            # Skill, Cron*, ScheduleWakeup, AskUserQuestion): NEVER blocked, and
            # MUST leave bash_consecutive byte-identical. bash_consecutive is a
            # Bash-only accumulator cleared ONLY by an Agent dispatch in main()
            # (before the /allow and /do short-circuits), never here. NB2
            # no-clobber: perform NO state write at all — re-assigning or
            # rebuilding bash_consecutive (even to the "same" value) could
            # clobber last_tool and re-introduce the launder bug where a single
            # interleaved non-Bash tool resets the consecutive-Bash streak.
            # Whitelisted non-Bash tools also do NOT increment per_tool_counts.
            return 1
    else:
        # Non-whitelist: increment the per-turn total for this tool (the
        # NON_WHITELIST_MAX_CONSECUTIVE=1 once-per-turn limit). NB2 no-clobber:
        # leave bash_consecutive byte-identical (the unchanged value read from
        # disk) — do NOT reset or rebuild it. Persist ONLY the per_tool_counts
        # increment.
        counts = state["per_tool_counts"]
        counts[tool_name] = counts.get(tool_name, 0) + 1
        write_tool_streak(session_id, state)
        return counts[tool_name]


def overnight_window_open(data: dict) -> bool:
    """The payload's session has its own /dev-overnight record with end_time
    ahead and no human-typed /stop after its /dev-overnight (lib/overnight
    window_open, the time-lock's one reading). Fails closed: any error keeps
    the ordinary per-turn budget."""
    try:
        from lib import overnight
        return bool(overnight.window_open(data))
    except Exception:
        return False


def in_flight(data: dict) -> bool:
    """The payload's active command span runs on a command text the session
    loaded before an update (D15): the text is not commands/<command>.md now.
    The test is pretool-todo-validate.py's _in_flight (c8225f48), loaded from
    that file. No span, no recorded text, or any error: not in flight."""
    try:
        import importlib.util
        from types import SimpleNamespace
        from lib import command_span
        transcript = data.get("transcript_path")
        span = command_span.active_span(transcript) if transcript else None
        if span is None:
            return False
        spec = importlib.util.spec_from_file_location(
            "_todo_validate_in_flight", Path(__file__).parent / "pretool-todo-validate.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return bool(module._in_flight(SimpleNamespace(span=span, command=span.command)))
    except Exception:
        return False


def block_permanent(tool_name: str, data: dict) -> None:
    allowed = ", ".join(sorted(ALWAYS_ALLOWED))
    if in_flight(data):  # origin/master's (2acc29b's) wording, which the session's text was written against
        sys.stderr.write(
            f"[Orchestrator Gate] Permanently blocked: {tool_name}\n"
            f"Delegate to subagents (Agent tool) or run /do to unlock.\n"
            f"Allowed without /do: {allowed}\n"
        )
        sys.exit(2)
    sys.stderr.write(
        f"[Orchestrator Gate] Permanently blocked: {tool_name} (/do does not unlock it).\n"
        f"Delegate to a subagent (Agent tool), or the user grants it once with /allow {tool_name}.\n"
        f"Whitelisted tools: {allowed}\n"
    )
    sys.exit(2)


def block_streak(tool_name: str, count: int, limit: int, data: dict) -> None:
    if in_flight(data):  # origin/master's (2acc29b's) wording
        sys.stderr.write(
            f"[Orchestrator Gate] BLOCKED: {tool_name} used consecutively beyond limit ({count}/{limit}).\n"
            f"Delegate to a subagent (Agent tool) or ask the user to run /do to unlock.\n"
        )
        sys.exit(2)
    sys.stderr.write(
        f"[Orchestrator Gate] BLOCKED: {tool_name} used consecutively beyond limit ({count}/{limit}): Bash "
        f"counts its calls since the last Agent dispatch or prompt, any other non-whitelisted tool its calls "
        f"this turn, whatever ran between them.\n"
        f"Delegate to a subagent (Agent tool) or ask the user to run /do to unlock.\n"
    )
    sys.exit(2)


def enforce_streak_limit(tool_name: str, count: int, data: dict) -> None:
    if tool_name in ALWAYS_ALLOWED:
        if tool_name == "Bash" and count > BASH_MAX_CONSECUTIVE:
            block_streak(tool_name, count, BASH_MAX_CONSECUTIVE, data)
        return
    if count > NON_WHITELIST_MAX_CONSECUTIVE:
        block_streak(tool_name, count, NON_WHITELIST_MAX_CONSECUTIVE, data)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    # Fail-open on non-dict payloads (e.g. a bare JSON list/scalar): never wedge
    # the harness on a malformed PreToolUse payload.
    if not isinstance(data, dict):
        sys.exit(0)

    tool_name = data.get("tool_name", "")

    if is_subagent_context(data):
        sys.exit(0)

    sid = get_session_id(data)

    # /restart exception: multiple SendMessage calls are required to resume ALL
    # interrupted children, so the normal once-per-tool-per-turn budget cannot be
    # used. The shared verifier binds the session capability, parent
    # transcript, target agent id, prepared state, and exact fixed message. Any
    # failure falls through to the ordinary non-whitelist budget; the independent
    # background-task hook then denies the unauthorized send.
    if tool_name == "SendMessage":
        try:
            from lib.subagent_restart import authorize_send_message

            restart_ok, _restart_reason = authorize_send_message(data)
            if restart_ok:
                sys.exit(0)
        except Exception:
            pass

    # Agent-clear: dispatching a subagent (Agent) is the ONLY action that
    # clears the consecutive-Bash streak (the user's literal intent — the count
    # is reset only when a subagent is used). Placed here, after the subagent
    # check + sid resolution and BEFORE the /allow and /do short-circuits, so an
    # Agent dispatch resets the streak even during a /do or /allow session
    # (those exit early below, so an update_streak-based clear would never fire
    # under them). The clear keeps the key with {last_tool:'Agent',count:0}
    # (never deletes it — deleting would trip _parse_streak_state's type-guard
    # and wipe per_tool_counts). It is a pure state write that never blocks, so
    # placing it ahead of the bypasses changes no allow/deny outcome.
    # Inside the session's open overnight window the dispatch also empties
    # per_tool_counts: no prompt arrives there all night (one turn), so without
    # it every Write/Edit after the first was refused until the session ended.
    # Between two dispatches the budget stays one call per tool name, as one
    # interactive turn's is; outside the window nothing but a prompt resets it.
    if tool_name == "Agent":
        try:
            state = read_streak_state(tool_streak_path(sid))
            state["bash_consecutive"] = {"last_tool": "Agent", "count": 0}
            if overnight_window_open(data):
                state["per_tool_counts"] = {}
            write_tool_streak(sid, state)
        except Exception:
            pass
        sys.exit(0)

    # /allow bypass: explicit user grant for a specific tool (checked BEFORE
    # PERMANENTLY_BLOCKED — intentional asymmetry: /allow is a true break-glass
    # that the local user explicitly granted; /do bypasses only streak limits
    # and fires AFTER perm-blocked, so /do cannot rescue perm-blocked tools).
    # Note: /allow CAN rescue even perm-blocked tools (e.g., EnterPlanMode) if
    # the user explicitly /allow-ed that tool name. This is by design.
    try:
        if match_sentinel_grant_for_tool(sid, tool_name) is not None:
            sys.exit(0)
    except Exception:
        pass

    if tool_name in PERMANENTLY_BLOCKED:
        block_permanent(tool_name, data)

    if has_do_consent(data):
        sys.exit(0)

    # A Write that pretool-write-guard.sh will reject (overwrite of an EXISTING
    # file — the guard forces Edit instead) must NOT consume the orchestrator's
    # one-Write-per-turn budget. One event's hooks run in parallel, so this gate
    # cannot see write-guard's verdict; without this skip a blocked
    # overwrite-attempt would still increment the count and exhaust the budget
    # for a later legitimate new-file Write. Replicate write-guard's "Write only
    # creates new files" predicate and skip counting such a call — it cannot
    # succeed via Write anyway, so it is not a real direct action. A Write that
    # another guard blocks still counts (fail-strict).
    if tool_name == "Write":
        target = (data.get("tool_input") or {}).get("file_path") or ""
        try:
            # Match write-guard's predicate EXACTLY: it blocks only regular files
            # (`[ -f "$FILE_PATH" ]` in pretool-write-guard.sh). Using is_file()
            # (not exists()) avoids skipping the count for an existing directory /
            # FIFO / symlink-to-dir, which write-guard would NOT reject — those must
            # still count so the once-per-turn limit is not silently loosened.
            if target and Path(target).is_file():
                sys.exit(0)
        except OSError:
            pass

    count = update_streak(sid, tool_name)
    enforce_streak_limit(tool_name, count, data)
    sys.exit(0)


if __name__ == "__main__":
    main()
