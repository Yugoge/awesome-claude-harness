#!/usr/bin/env python3
"""
PostToolUse Hook: /allow grant consumption.

Atomically deletes the /allow grant file after a tool executes successfully.
PreToolUse hooks are now read-only grant checkers; this hook is the sole
consume point. Applies to any matching PostToolUse event (subagent or
main-agent). Subagent write-grant firewall remains in
`hooks/userprompt-consent-allowlist.sh` Step 0.

PostToolUse fires only when all PreToolUse hooks exit 0 (tool was allowed).
If any PreToolUse hook exits 2, PostToolUse never fires — grant persists
for retry. This is correct UX: user can retry with the same grant.

PostToolUse additionally fires only for tool calls that RETURNED. A Bash
command whose non-benign exit code makes the tool throw fires the separate
PostToolUseFailure event (payload: tool_name/tool_input/tool_use_id/error/
is_interrupt — no tool_response), so this hook is registered under BOTH
events in settings.json (audit R2-1): the failure event is what removes a
failed commit's event pointer and consumes sentinels on failed commands.

Sentinel-grant consume-on-any-terminal-result semantic (task 20260519-211515
R2 / AC2): this hook unlinks the sentinel grant at
<state dir>/claude-grants/<task_id>.json, the one /allow grant file, when ANY
terminal result is observed for the wrapped tool. The four mandated
terminal-consumption cases are: success (exit 0), failure / non_zero exit
(1..255), malformed grant JSON, and comment_only attack (the magic phrase
appears in the command but no sentinel JSON exists). All four unlink the
sentinel grant unconditionally — this is the consume-on-any-terminal-result
contract documented verbatim below.

Exit 0 (fail-open), silently when no grant matches. One exception: a Write of
a merge-analyst grant that hooks/lib/merge_grant.py rejects is removed and exits
2, which returns the fault to the merge-analyst.
"""

import json
import os
import re as _re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib import commit_journal  # noqa: E402

# Pattern to detect git commit commands (used by the commit-event finalization).
_GIT_COMMIT_CMD_RE = _re.compile(r'\bgit\b.*\bcommit\b', _re.DOTALL)


def _finalize_commit_event(event_key: str, raw_event_id: str,
                           session_id: str, terminal_result: str) -> None:
    """Journal THIS tool event's commit from the pointer the guard wrote for it.

    The privilege guard spent the commit grant (deleted it) at PreToolUse and
    wrote a pointer named for the `tool_use_id` of the very invocation this
    PostToolUse call completes, holding the grant's journal fields
    (hooks/lib/commit_journal.py `write_event_pointer`). This acts on THAT
    pointer and no other:
      - terminal_result='success'          → append the commit-event journal
        entry, then remove the pointer
      - terminal_result='unknown_terminal' → NOTHING (audit F2). That label is a
        NONTERMINAL background-launch receipt: the command is still running, so
        no outcome exists to act on. No later PostToolUse ever fires for a
        backgrounded tool_use_id, so the pointer ages out through the stale
        reaper below (a later commit event or the Stop cleanup).
      - any other terminal result          → remove the pointer; the failed
        commit's next attempt takes a fresh grant from /commit
    This hook is the journal's one writer.

    AN EVENT WITH NO POINTER OF ITS OWN ACTS ON NOTHING. A session id proves only
    that two things share a session; an auto-bulk commit (which spends no grant)
    or an event whose pointer could not be written must not reach another
    event's pointer and journal a record mixing that event's grant fields with
    this event's session id. The recorded `event_key` is checked against the
    name, and the recorded RAW `tool_use_id` against `raw_event_id` (audit R2-2):
    the derived name is lossy, so ownership is proven raw-for-raw.

    Fail-open: never raises, and never disturbs a commit that has already landed.
    """
    if terminal_result == 'unknown_terminal':
        return
    pointer_path = commit_journal.pointer_path(event_key) if event_key else ''
    commit_journal.reap_stale_pointers(pointer_path)
    if not pointer_path:
        return
    # The identity of the pointer inode this event's decisions are made ABOUT
    # (audit F8): the unlink below acts on that instance only, so a pointer a
    # colliding live event re-created under the same lossy name is left alone.
    pointer, pointer_ident = commit_journal.read_untrusted_json_ident(pointer_path)
    if not isinstance(pointer, dict) or not all(
            isinstance(pointer.get(field), str) and pointer.get(field)
            for field in ('event_key', 'repo_root', 'task_id')):
        # Absent is the ordinary case for every commit that spent no grant. A
        # corrupt, non-regular, oversized or field-incomplete one names nothing
        # any event could journal; it is removed so it cannot sit under a dead key.
        commit_journal.unlink_verified(pointer_path, pointer_ident)
        return
    if pointer.get('event_key') != event_key:
        return
    if not raw_event_id or str(pointer.get('tool_use_id') or '') != raw_event_id:
        return
    if terminal_result == 'success':
        try:
            commit_journal.append_commit_event(pointer, session_id)
        except Exception:
            pass
    commit_journal.unlink_verified(pointer_path, pointer_ident)

sys.path.insert(0, str(Path(__file__).parent))
from lib.allowlist import (  # noqa: E402
    consume_sentinel_grant_on_terminal_result,
    match_sentinel_grant_for_tool,
    match_sentinel_grant_for_write,
)


def _classify_terminal_result(data: dict) -> str:
    """Classify the posttool terminal-result for sentinel consumption.

    Implements consume-on-any-terminal-result: every TERMINAL outcome
    (success, failure, non_zero exit, malformed grant, comment_only attack)
    unlinks the sentinel. "unknown_terminal" is the one NONTERMINAL label
    (audit F2): a background-launch receipt means the command is still
    running, so nothing is consumed, restored, or deleted for it — the state
    survives for the terminal event or the age-bounded sweeps.

    Precedence (audit F3): nonterminal and interrupted signals DOMINATE any
    exit code. The shipped binary's explicit-background and timeout-
    background paths both return {stdout:"", stderr:"", code:0,
    interrupted:false, backgroundTaskId} — a receipt CARRIES a zero exit
    code — and an SDK-style payload can carry exit_code alongside either
    signal, so an exit_code branch evaluated first would classify a
    still-running or interrupted command as a finished one.

    REAL PAYLOAD SHAPES (audit R2-1, settled against the shipped harness
    binary's BashOutput schema and live-session transcript records): a
    successful Bash call's tool_response is {stdout, stderr, interrupted,
    ...} with NO exit_code and NO is_error field — the harness only fires
    PostToolUse for tool calls that returned; a non-benign non-zero exit
    makes the Bash tool THROW, which fires PostToolUseFailure instead,
    whose payload carries an `error` string and no tool_response at all.
    Success is therefore derived from the shape that is actually present,
    and the failure event is recognized by its hook_event_name. The
    is_error / exit_code branches are kept for SDK-style payloads.

    Returns one of: "success", "failure", "non_zero", "malformed",
                    "comment_only", "unknown_terminal".
    """
    if data.get("hook_event_name") == "PostToolUseFailure":
        # The tool threw (Bash: non-benign non-zero exit or pre-spawn
        # error). Terminal failure; there is no tool_response to inspect.
        return "failure"
    response = data.get("tool_response") or {}
    if isinstance(response, dict):
        if response.get("backgroundTaskId"):
            # Background-launch receipt: the command is still running, so no
            # terminal result exists yet for this event. Checked FIRST (audit
            # F3): the receipt carries code 0, and combined with `interrupted`
            # it is ambiguous — nonterminal wins because leaving state alone
            # is the recoverable reading (fail-open toward the commit).
            return "unknown_terminal"
        if response.get("interrupted") is True:
            # Interrupted dominates any exit code (audit F3): an interrupted
            # command has no trustworthy outcome regardless of the code an
            # SDK-style payload reports next to it.
            return "failure"
        if response.get("is_error"):
            return "failure"
        exit_code = response.get("exit_code")
        if isinstance(exit_code, int):
            if exit_code == 0:
                return "success"
            if 1 <= exit_code <= 255:
                return "non_zero"
        if isinstance(response.get("stdout"), str) \
                and isinstance(response.get("stderr"), str):
            # The real harness success shape (BashOutput). Reaching
            # PostToolUse with this shape IS the success signal.
            return "success"
    return "unknown_terminal"


def main() -> None:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        # Malformed posttool input — still reap the sentinel for the
        # comment_only / malformed terminal case. Mirror writer priority:
        # CLAUDE_TASK_ID > CLAUDE_SESSION_ID (session_id fallback).
        _env_tid = os.environ.get("CLAUDE_TASK_ID", "")
        _env_sid = os.environ.get("CLAUDE_SESSION_ID", "default")
        task_id = _env_tid if _env_tid else _env_sid
        if task_id:
            consume_sentinel_grant_on_terminal_result(task_id, "malformed")
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    session_id = data.get("session_id") or os.environ.get("CLAUDE_SESSION_ID", "default")

    if tool_name == "Bash":
        command = (data.get("tool_input") or {}).get("command", "")
    else:
        command = ""

    # A grant that names the tool itself (`/allow Agent`, `/allow Bash`) is spent
    # by the call it let through, as the command and Write matchers below spend
    # theirs. A non-Bash PostToolUse fires only for a call that returned; a Bash
    # background receipt is not terminal yet (audit F2) and keeps the grant.
    if tool_name != "Write" and match_sentinel_grant_for_tool(session_id, tool_name) is not None:
        named_result = _classify_terminal_result(data) if tool_name == "Bash" else "success"
        if named_result != "unknown_terminal":
            consume_sentinel_grant_on_terminal_result(
                os.environ.get("CLAUDE_TASK_ID") or session_id, named_result)

    # Sentinel-grant consume-on-any-terminal-result (task 20260519-211515 R2 / AC2).
    #
    # CF-2 scoping (codex iter-1 BLOCKER): the sentinel grants bash-command
    # authorization. PostToolUse fires for EVERY tool (matcher "*"), so an
    # unrelated Read/Grep/Glob call after `/allow` could otherwise unlink the
    # sentinel before the intended Bash call. We restrict sentinel consumption
    # to Bash terminal results AND only when the sentinel actually matched
    # this command structurally (`match_sentinel_grant_for_bash_command`).
    # The four mandated terminal cases (success/failure/non_zero/malformed)
    # are all hit only when Bash itself fires; non-Bash tool events skip the
    # sentinel-consume path entirely.
    env_task_id = os.environ.get("CLAUDE_TASK_ID", "")
    task_id = env_task_id if env_task_id else session_id
    if task_id and tool_name == "Bash":
        try:
            from lib.allowlist import (  # noqa: E402
                match_sentinel_grant_for_bash_command,
                load_sentinel_grant_for_task,
                _enumerate_sentinel_grant_files,
            )
        except Exception:
            match_sentinel_grant_for_bash_command = None
            load_sentinel_grant_for_task = None
            _enumerate_sentinel_grant_files = None
        terminal_result = _classify_terminal_result(data)
        should_consume = False
        if match_sentinel_grant_for_bash_command is not None:
            try:
                m = match_sentinel_grant_for_bash_command(task_id, command)
                if m is not None:
                    should_consume = True
            except Exception:
                should_consume = True
                terminal_result = "malformed"
        # Malformed-grant terminal case: a sentinel file exists for this task
        # but load_sentinel_grant_for_task returned None (parse failure or
        # expired). The AC2 contract requires unlink on malformed.
        if (not should_consume) and load_sentinel_grant_for_task is not None \
                and _enumerate_sentinel_grant_files is not None:
            try:
                if _enumerate_sentinel_grant_files(task_id) and load_sentinel_grant_for_task(task_id) is None:
                    should_consume = True
                    terminal_result = "malformed"
            except Exception:
                pass
        # Nonterminal background receipt (audit F2): the command is still
        # running, so a structurally matched sentinel must SURVIVE for the
        # real terminal event — consume nothing, unlink nothing. The two
        # malformed overrides above are unaffected: "malformed" is itself a
        # terminal-consumption case and has already replaced the label.
        if terminal_result == "unknown_terminal":
            should_consume = False
        if should_consume:
            consume_sentinel_grant_on_terminal_result(task_id, terminal_result)
    # Commit-event finalization: the guard spent the grant at PreToolUse and left
    # this event's pointer; the journal entry is appended from it here.
    if tool_name == "Bash" and command and _GIT_COMMIT_CMD_RE.search(command):
        _finalize_commit_event(commit_journal.event_key(data),
                               commit_journal.raw_tool_use_id(data),
                               session_id, _classify_terminal_result(data))

    elif tool_name == "Write":
        # Sentinel-grant consume for Write-overwrite grants (task 20260522-080646-B).
        # Uses tool_input.file_path (not command — Write has no command field).
        #
        # 3-candidate task_id lookup (iter3 B1 fix): mirrors pretool write-guard.sh
        # candidate list so we find the sentinel regardless of whether userprompt-
        # consent-allowlist.sh keyed it by CLAUDE_TASK_ID or by session_id.
        # Candidate order must match writer: [CLAUDE_TASK_ID or session_id, data.task_id, session_id].
        env_task_id = os.environ.get("CLAUDE_TASK_ID", "")
        writer_primary = env_task_id if env_task_id else session_id
        data_task_id = data.get("task_id") or ""
        seen: set = set()
        candidates = []
        for c in [writer_primary, data_task_id, session_id]:
            if c and c not in seen:
                seen.add(c)
                candidates.append(c)
        file_path = (data.get("tool_input") or {}).get("file_path", "")
        terminal_result = _classify_terminal_result(data)
        should_consume = False
        consumed_task_id = ""
        for candidate in candidates:
            try:
                m = match_sentinel_grant_for_write(candidate, session_id, file_path)
                if m is not None:
                    should_consume = True
                    consumed_task_id = candidate
                    break
            except Exception:
                should_consume = True
                consumed_task_id = candidate
                terminal_result = "malformed"
                break
        # Malformed-grant fallback: sentinel exists for some candidate but
        # load/match failed (expired, parse error).
        if not should_consume:
            try:
                from lib.allowlist import (  # noqa: E402
                    load_sentinel_grant_for_task,
                    _enumerate_sentinel_grant_files,
                )
                for candidate in candidates:
                    if _enumerate_sentinel_grant_files(candidate) and load_sentinel_grant_for_task(candidate) is None:
                        should_consume = True
                        consumed_task_id = candidate
                        terminal_result = "malformed"
                        break
            except Exception:
                pass
        if should_consume:
            consume_sentinel_grant_on_terminal_result(consumed_task_id or session_id, terminal_result)
        # The merge-analyst grant is checked on its producer's own Write
        # (experiment E11); /merge reads it verbatim. A faulty grant is removed
        # here, as /merge Step 3 removed it before, so no faulty grant reaches
        # /merge and the merge-analyst can Write it again (pretool-write-guard
        # refuses a Write over an existing file; the role has no Edit).
        try:
            from lib import merge_grant  # noqa: E402
            grant_fault = (merge_grant.fault(file_path)
                           if merge_grant.is_grant_path(file_path) else "")
        except Exception:
            grant_fault = ""
        if grant_fault:
            try:
                os.unlink(file_path)
            except OSError:
                pass
            print(f"MERGE_GRANT_INVALID: {file_path}: {grant_fault}. The grant was removed; "
                  "Write it again from your own analysis (agents/merge-analyst.md Phase 8) "
                  "before you stop. /merge aborts on a missing grant and acts on a present "
                  "one as written.", file=sys.stderr)
            sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
