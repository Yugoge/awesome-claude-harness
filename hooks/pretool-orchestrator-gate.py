#!/usr/bin/env python3
"""
PreToolUse Hook: Orchestrator Gate (Unified)

Three-tier policy for the main agent:
  1. ALWAYS_ALLOWED whitelist tools pass, but Bash is capped at 5 calls
     (6th blocked) until an Agent dispatch or the next prompt resets the
     count; other tools between the Bash calls do not. A Bash command that
     lib/bash_read_only proves read-only (OB-L03) passes uncounted. The built-in
     read-only tools of READ_ONLY_ALLOWED (LSP, TaskOutput/BashOutput,
     ReadMcpResourceTool, ListMcpResourcesTool) pass too and are not
     counted.
  2. Non-whitelist tools are allowed once TOTAL per tool name per turn
     (2nd same-name call blocked regardless of intervening tool calls).
     Inside the session's open /dev-overnight window (lib/overnight
     window_open) an Agent dispatch also resets these counts: the unattended
     session is one turn, so there the turn's budget is the one between two
     dispatches. The retrieval tools of RETRIEVAL_TOOLS (WebSearch,
     WebFetch and the Context7 tools named there, each by its exact name)
     get RETRIEVAL_MAX_PER_TURN = 3 calls per tool name per turn instead,
     and an Agent dispatch never resets their count, overnight window
     included: the calls of one message pass PreToolUse together, so a
     dispatch in the same message would otherwise refill the budget.
  3. PERMANENTLY_BLOCKED (EnterPlanMode, ExitPlanMode) are blocked even
     with /do consent; an /allow grant naming the tool is the one way
     through.

bash_consecutive is a Bash-ONLY accumulator: only a Bash tool call
increments it. An Agent (subagent) dispatch resets it to
{"last_tool": "Agent", "count": 0} (and, inside an open overnight window,
empties per_tool_counts but the retrieval tools' entries), and
hooks/prompt-workflow.py removes the whole
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

A counted call that did not run gives its slot back (OB-L02). The gate
counts at PreToolUse, before the verdicts of the other hooks (the launcher's
other rules, pretool-bash-safety.sh in its own process) are known, so each
counted call is kept in "reserved" by the tool_use_id the CLI sets, and every
later counted call first settles them: a call that ran is in the log
hooks/posttool-orchestrator-ran.py appends on the CLI's PostToolUse or
PostToolUseFailure event (fired for every call the CLI ran, a non-zero exit
included, never for a call a PreToolUse hook refused) and stays counted; a
call the transcript holds an is_error tool_result for (the CLI's record of a
refused call) and that is not in the log is given back; any other call (still
running, its result not written yet, no transcript) stays counted until a
later settlement. No text of a result, an input or a command decides it. The
prompt reset removes the log with the state file.

State file: <state dir>/claude-tool-streak-<sid>.json --
  {"schema_version": 2, "per_tool_counts": {"Edit": 1},
   "bash_consecutive": {"last_tool": "Bash", "count": 2},
   "reserved": [{"id": "toolu_...", "tool": "Bash"}]}
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
    has_do_consent, match_sentinel_grant_for_tool, read_tool_ran, tool_streak_path, write_tool_streak)

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

# Built-in tools that only read (code intelligence, a background task's
# output, MCP resources): no state change for a subagent to own, so they
# pass uncounted. Kept apart from ALWAYS_ALLOWED because the in-flight
# refusal prints ALWAYS_ALLOWED in origin/master's wording, byte for byte.
READ_ONLY_ALLOWED = frozenset({
    "LSP",
    "TaskOutput",
    "BashOutput",
    "ReadMcpResourceTool",
    "ListMcpResourcesTool",
})

# Retrieval tools with their own per-turn budget. MCP tools are listed by
# their exact name, never by a name pattern (get_*, *search*): a third-party
# MCP server can give a side-effecting tool such a name.
RETRIEVAL_TOOLS = frozenset({
    "WebSearch",
    "WebFetch",
    "mcp__context7__resolve-library-id",
    "mcp__context7__get-library-docs",
    "mcp__context7__query-docs",
    "mcp__plugin_context7_context7__resolve-library-id",
    "mcp__plugin_context7_context7__get-library-docs",
    "mcp__plugin_context7_context7__query-docs",
})

PERMANENTLY_BLOCKED = {
    "EnterPlanMode",
    "ExitPlanMode",
}

BASH_MAX_CONSECUTIVE = 5
NON_WHITELIST_MAX_CONSECUTIVE = 1
RETRIEVAL_MAX_PER_TURN = 3


def turn_limit(tool_name: str) -> int:
    """The per-turn budget of a non-whitelisted tool name."""
    return RETRIEVAL_MAX_PER_TURN if tool_name in RETRIEVAL_TOOLS else NON_WHITELIST_MAX_CONSECUTIVE


def get_session_id(data: dict) -> str:
    sid = data.get("session_id") or os.environ.get("CLAUDE_SESSION_ID", "")
    if sid:
        return sid
    sys.stderr.write("[Orchestrator Gate] WARNING: session_id unavailable, using shared default\n")
    return "default"


def _fresh_state() -> dict:
    return {"schema_version": 2, "per_tool_counts": {}, "bash_consecutive": {"last_tool": "", "count": 0},
            "reserved": []}


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
    reserved = data.get("reserved")
    reserved = [r for r in reserved if isinstance(r, dict) and isinstance(r.get("id"), str) and r["id"]
                and isinstance(r.get("tool"), str)] if isinstance(reserved, list) else []
    return {"schema_version": 2, "per_tool_counts": per_tool, "bash_consecutive": bash_con,
            "reserved": reserved}


def read_streak_state(state_file: Path) -> dict:
    try:
        if state_file.exists():
            return _parse_streak_state(json.loads(state_file.read_text()))
    except (ValueError, OSError, json.JSONDecodeError):
        pass
    return _fresh_state()


# How much of the transcript's end settle() reads: a reserved call is of this
# turn, so its result is near the end; one not found there stays counted.
TRANSCRIPT_TAIL_BYTES = 8 * 1024 * 1024


def refused_results(transcript_path, ids) -> dict:
    """{tool_use_id: is_error} for the ids whose tool_result the CLI recorded
    in the main transcript: a top-level user record (not a sidechain) whose
    message content holds a tool_result block with that tool_use_id. Only the
    record's structure is read, never a result's text; text a command printed
    sits inside a block's content and is never a block of its own. Empty on
    any error."""
    found: dict = {}
    if not ids or not isinstance(transcript_path, str) or not transcript_path:
        return found
    try:
        with open(transcript_path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - TRANSCRIPT_TAIL_BYTES))
            if size > TRANSCRIPT_TAIL_BYTES:
                handle.readline()  # a partial first line
            for raw in handle:
                if not any(i.encode() in raw for i in ids):
                    continue
                try:
                    record = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(record, dict) or record.get("type") != "user" or record.get("isSidechain"):
                    continue
                message = record.get("message")
                content = message.get("content") if isinstance(message, dict) else None
                if not isinstance(content, list):
                    continue
                for block in content:
                    if (isinstance(block, dict) and block.get("type") == "tool_result"
                            and block.get("tool_use_id") in ids):
                        found[block["tool_use_id"]] = block.get("is_error") is True
    except (OSError, ValueError):
        return {}
    return found


def settle(state: dict, session_id: str, transcript_path) -> None:
    """Give back the slot of each reserved call that is over and did not run.

    A reserved call in the ran log (hooks/posttool-orchestrator-ran.py) ran and
    stays counted. One with an is_error tool_result in the transcript and not
    in the log was refused before it ran (by another hook, or by this gate)
    and is given back: its Bash streak or per-tool count goes down by one.
    One whose result has no error but is not in the log stays counted. Any
    other stays reserved and counted. An unreadable log gives nothing back."""
    reserved = state.get("reserved") or []
    if not reserved:
        return
    ran = read_tool_ran(session_id)
    if ran is None:
        return
    ended = refused_results(transcript_path, {r["id"] for r in reserved if r["id"] not in ran})
    keep = []
    for r in reserved:
        if r["id"] in ran:
            continue
        if r["id"] not in ended:
            keep.append(r)
            continue
        if not ended[r["id"]]:
            continue
        if r["tool"] == "Bash":
            bash = state["bash_consecutive"]
            if bash["last_tool"] == "Bash" and bash["count"] > 0:
                bash["count"] -= 1
        else:
            counts = state["per_tool_counts"]
            if counts.get(r["tool"], 0) > 0:
                counts[r["tool"]] -= 1
    state["reserved"] = keep


def _write_state(session_id: str, state: dict) -> None:
    """Persist the state; "reserved" is written only while it holds a call, so
    a state with nothing reserved is the schema-2 record it always was."""
    if not state.get("reserved"):
        state = {k: v for k, v in state.items() if k != "reserved"}
    write_tool_streak(session_id, state)


def _reserve(state: dict, tool_name: str, tool_use_id) -> None:
    """Keep the counted call for settle(); a payload without a tool_use_id
    (an older CLI) leaves its call counted for good."""
    if isinstance(tool_use_id, str) and tool_use_id:
        state["reserved"].append({"id": tool_use_id, "tool": tool_name})


def update_streak(session_id: str, tool_name: str, data: dict | None = None) -> int:
    if tool_name in READ_ONLY_ALLOWED:
        return 1  # never blocked, never counted; no state write (NB2 no-clobber)

    data = data if isinstance(data, dict) else {}
    state = read_streak_state(tool_streak_path(session_id))

    if tool_name in ALWAYS_ALLOWED:
        if tool_name == "Bash":
            settle(state, session_id, data.get("transcript_path"))
            bash = state["bash_consecutive"]
            if bash["last_tool"] == "Bash":
                bash["count"] += 1
            else:
                bash["last_tool"] = "Bash"
                bash["count"] = 1
            _reserve(state, tool_name, data.get("tool_use_id"))
            _write_state(session_id, state)
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
        # NON_WHITELIST_MAX_CONSECUTIVE=1 once-per-turn limit, or
        # RETRIEVAL_MAX_PER_TURN for a retrieval tool). NB2 no-clobber:
        # leave bash_consecutive byte-identical (the unchanged value read from
        # disk) — do NOT reset or rebuild it. Persist ONLY the per_tool_counts
        # increment.
        settle(state, session_id, data.get("transcript_path"))
        counts = state["per_tool_counts"]
        counts[tool_name] = counts.get(tool_name, 0) + 1
        _reserve(state, tool_name, data.get("tool_use_id"))
        _write_state(session_id, state)
        return counts[tool_name]


def read_only_bash(data: dict) -> bool:
    """The payload's Bash command is proven read-only (lib/bash_read_only), in
    the foreground. Fails closed: any error, or a background run, counts."""
    try:
        tool_input = data.get("tool_input")
        if not isinstance(tool_input, dict) or tool_input.get("run_in_background"):
            return False
        from lib.bash_read_only import is_read_only
        return is_read_only(tool_input.get("command"))
    except Exception:
        return False


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
    if in_flight(data):  # origin/master's (2acc29b's) wording, which the session's text was written against
        allowed = ", ".join(sorted(ALWAYS_ALLOWED))
        sys.stderr.write(
            f"[Orchestrator Gate] Permanently blocked: {tool_name}\n"
            f"Delegate to subagents (Agent tool) or run /do to unlock.\n"
            f"Allowed without /do: {allowed}\n"
        )
        sys.exit(2)
    allowed = ", ".join(sorted(ALWAYS_ALLOWED | READ_ONLY_ALLOWED))
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
        + (f"{tool_name} is a retrieval tool: {RETRIEVAL_MAX_PER_TURN} calls per turn, which an Agent dispatch "
           f"does not refill.\n" if tool_name in RETRIEVAL_TOOLS else "")
        + "Delegate to a subagent (Agent tool) or ask the user to run /do to unlock.\n"
    )
    sys.exit(2)


def enforce_streak_limit(tool_name: str, count: int, data: dict) -> None:
    if tool_name in ALWAYS_ALLOWED:
        if tool_name == "Bash" and count > BASH_MAX_CONSECUTIVE:
            block_streak(tool_name, count, BASH_MAX_CONSECUTIVE, data)
        return
    limit = turn_limit(tool_name)
    if count > limit:
        block_streak(tool_name, count, limit, data)


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
    # The retrieval tools' counts are kept even there: the calls of one
    # message all pass PreToolUse together, so a dispatch in the same message
    # would refill their budget before any of them ran.
    if tool_name == "Agent":
        try:
            state = read_streak_state(tool_streak_path(sid))
            state["bash_consecutive"] = {"last_tool": "Agent", "count": 0}
            # A reserved call whose count the reset cleared is no longer in a
            # count settle() could give it back to.
            state["reserved"] = [r for r in state["reserved"] if r["tool"] != "Bash"]
            if overnight_window_open(data):
                state["per_tool_counts"] = {
                    name: n for name, n in state["per_tool_counts"].items() if name in RETRIEVAL_TOOLS}
                state["reserved"] = [r for r in state["reserved"] if r["tool"] in RETRIEVAL_TOOLS]
            _write_state(sid, state)
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
    # another guard blocks counts until settle() sees it was refused (OB-L02).
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

    # A Bash command lib/bash_read_only proves read-only (it can neither run
    # code of its choosing nor write a file, read from the shell_parse tree)
    # passes without a slot and without a state write (OB-L03). The other
    # hooks still judge it; anything not proven read-only counts.
    if tool_name == "Bash" and read_only_bash(data):
        sys.exit(0)

    count = update_streak(sid, tool_name, data)
    enforce_streak_limit(tool_name, count, data)
    sys.exit(0)


if __name__ == "__main__":
    main()
