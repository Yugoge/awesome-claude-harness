#!/usr/bin/env python3
"""
PostToolUse Hook (and PostToolUseFailure, Bash): the commit-event finalization
and the merge-analyst grant check.

It once also spent /allow grants; a grant is now spent where it releases a
refusal, in the pre-tool launcher (lib/hook_launch.release_refused), and this
hook reads none.
  - Bash `git commit`: the commit journal entry from the pointer the privilege
    guard wrote for this tool_use_id (_finalize_commit_event).
  - Write of a merge-analyst grant that hooks/lib/merge_grant.py rejects: the
    file is removed and the hook exits 2, which returns the fault to the
    merge-analyst.
Exit 0 (fail-open) otherwise.
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

def _classify_terminal_result(data: dict) -> str:
    """Classify the posttool terminal-result for the commit-event finalization.

    "unknown_terminal" is the one NONTERMINAL label
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

    Returns one of: "success", "failure", "non_zero", "unknown_terminal".
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
        sys.exit(0)
    tool_name = data.get("tool_name", "")
    session_id = data.get("session_id") or os.environ.get("CLAUDE_SESSION_ID", "default")
    command = (data.get("tool_input") or {}).get("command", "") if tool_name == "Bash" else ""
    # Commit-event finalization: the guard spent the grant at PreToolUse and left
    # this event's pointer; the journal entry is appended from it here.
    if tool_name == "Bash" and command and _GIT_COMMIT_CMD_RE.search(command):
        _finalize_commit_event(commit_journal.event_key(data),
                               commit_journal.raw_tool_use_id(data),
                               session_id, _classify_terminal_result(data))
    elif tool_name == "Write":
        file_path = (data.get("tool_input") or {}).get("file_path", "")
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
