#!/usr/bin/env python3
"""
PreToolUse Hook: Orchestrator Gate (Unified)

Three-tier policy for the main agent:
  1. ALWAYS_ALLOWED whitelist tools pass, but Bash is capped at 5
     consecutive same-name calls (6th blocked).
  2. Non-whitelist tools are allowed once TOTAL per tool name per turn
     (2nd same-name call blocked regardless of intervening tool calls).
  3. PERMANENTLY_BLOCKED (EnterPlanMode, ExitPlanMode) are always
     blocked, even with /do consent.

Subagents (agent_id present) are fully exempt and do NOT update
the streak state.

/do consent (Design A) bypasses streak checks AND does not update
the streak state, preserving clean exit semantics.

State file: /tmp/claude-tool-streak-<sid>.json --
  {"schema_version": 2, "per_tool_counts": {"Edit": 1},
   "bash_consecutive": {"last_tool": "Bash", "count": 2}}
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.subagent import is_subagent_context  # noqa: E402
from lib.allowlist import read_grant          # noqa: E402

ALWAYS_ALLOWED = {
    "Agent",
    "TodoWrite",
    "AskUserQuestion",
    "Skill",
    "CronCreate",
    "CronDelete",
    "CronList",
    "ScheduleWakeup",
    "mcp__happy__change_title",
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


def has_consent(session_id: str) -> bool:
    flag = Path(f"/tmp/claude-orchestrator-consent-{session_id}.flag")
    try:
        return flag.exists() and flag.read_text().strip() == "true"
    except Exception:
        return False


def get_streak_state_file(session_id: str) -> Path:
    return Path(f"/tmp/claude-tool-streak-{session_id}.json")


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
    return {"schema_version": 2, "per_tool_counts": per_tool, "bash_consecutive": bash_con}


def read_streak_state(state_file: Path) -> dict:
    try:
        if state_file.exists():
            return _parse_streak_state(json.loads(state_file.read_text()))
    except (ValueError, OSError, json.JSONDecodeError):
        pass
    return _fresh_state()


def write_streak_state(state_file: Path, state: dict) -> None:
    try:
        state_file.write_text(json.dumps(state))
    except OSError:
        pass


def update_streak(state_file: Path, tool_name: str) -> int:
    state = read_streak_state(state_file)

    if tool_name in ALWAYS_ALLOWED:
        if tool_name == "Bash":
            bash = state["bash_consecutive"]
            if bash["last_tool"] == "Bash":
                bash["count"] += 1
            else:
                bash["last_tool"] = "Bash"
                bash["count"] = 1
            write_streak_state(state_file, state)
            return bash["count"]
        else:
            # Non-Bash whitelist: reset bash consecutive counter, never blocked
            state["bash_consecutive"] = {"last_tool": tool_name, "count": 1}
            write_streak_state(state_file, state)
            return 1
    else:
        # Non-whitelist: increment total count for this tool; reset bash consecutive
        counts = state["per_tool_counts"]
        counts[tool_name] = counts.get(tool_name, 0) + 1
        state["bash_consecutive"] = {"last_tool": tool_name, "count": 1}
        write_streak_state(state_file, state)
        return counts[tool_name]


def block_permanent(tool_name: str) -> None:
    allowed = ", ".join(sorted(ALWAYS_ALLOWED))
    sys.stderr.write(
        f"[Orchestrator Gate] Permanently blocked: {tool_name}\n"
        f"Delegate to subagents (Agent tool) or run /do to unlock.\n"
        f"Allowed without /do: {allowed}\n"
    )
    sys.exit(2)


def block_streak(tool_name: str, count: int, limit: int) -> None:
    sys.stderr.write(
        f"[Orchestrator Gate] BLOCKED: {tool_name} used consecutively beyond limit ({count}/{limit}).\n"
        f"Delegate to a subagent (Agent tool) or ask the user to run /do to unlock.\n"
    )
    sys.exit(2)


def enforce_streak_limit(tool_name: str, count: int) -> None:
    if tool_name in ALWAYS_ALLOWED:
        if tool_name == "Bash" and count > BASH_MAX_CONSECUTIVE:
            block_streak(tool_name, count, BASH_MAX_CONSECUTIVE)
        return
    if count > NON_WHITELIST_MAX_CONSECUTIVE:
        block_streak(tool_name, count, NON_WHITELIST_MAX_CONSECUTIVE)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_name = data.get("tool_name", "")

    if is_subagent_context(data):
        sys.exit(0)

    sid = get_session_id(data)

    # /allow bypass: explicit user grant for a specific tool (checked BEFORE
    # PERMANENTLY_BLOCKED — intentional asymmetry: /allow is a true break-glass
    # that the local user explicitly granted; /do bypasses only streak limits
    # and fires AFTER perm-blocked, so /do cannot rescue perm-blocked tools).
    # Note: /allow CAN rescue even perm-blocked tools (e.g., EnterPlanMode) if
    # the user explicitly /allow-ed that tool name. This is by design.
    try:
        if read_grant(tool_name, sid):
            sys.exit(0)
    except Exception:
        pass

    if tool_name in PERMANENTLY_BLOCKED:
        block_permanent(tool_name)

    if has_consent(sid):
        sys.exit(0)

    # A Write that pretool-write-guard.sh will reject (overwrite of an EXISTING
    # file — the guard forces Edit instead) must NOT consume the orchestrator's
    # one-Write-per-turn budget. This gate runs FIRST, before write-guard, so
    # without this skip a blocked overwrite-attempt still increments the streak
    # and wrongly exhausts the budget for a later legitimate new-file Write
    # (observed: a blocked requirement-doc overwrite blocked a later completion
    # write). Replicate write-guard's "Write only creates new files" predicate and
    # skip counting such a call — it cannot succeed via Write anyway, so it is not
    # a real direct action. Writes blocked by OTHER downstream guards are out of
    # scope for this targeted fix (fail-strict is preserved; the general
    # PostToolUse-counting fix is deferred — see do-report).
    if tool_name == "Write":
        target = (data.get("tool_input") or {}).get("file_path") or ""
        try:
            # Match write-guard's predicate EXACTLY: it blocks only regular files
            # (`[ -f "$FILE_PATH" ]`, pretool-write-guard.sh:141). Using is_file()
            # (not exists()) avoids skipping the count for an existing directory /
            # FIFO / symlink-to-dir, which write-guard would NOT reject — those must
            # still count so the once-per-turn limit is not silently loosened.
            if target and Path(target).is_file():
                sys.exit(0)
        except OSError:
            pass

    count = update_streak(get_streak_state_file(sid), tool_name)
    enforce_streak_limit(tool_name, count)
    sys.exit(0)


if __name__ == "__main__":
    main()
