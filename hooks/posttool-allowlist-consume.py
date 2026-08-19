#!/usr/bin/env python3
"""
PostToolUse Hook: /allow grant consumption.

Atomically deletes the /allow grant file after a tool executes successfully.
PreToolUse hooks are now read-only grant checkers; this hook is the sole
consume point. Applies to any matching PostToolUse event (subagent or
main-agent); legacy grant cleanup is unconditional. Subagent write-grant
firewall remains in `hooks/userprompt-consent-allowlist.sh` Step 0.

PostToolUse fires only when all PreToolUse hooks exit 0 (tool was allowed).
If any PreToolUse hook exits 2, PostToolUse never fires — grant persists
for retry. This is correct UX: user can retry with the same grant.

Sentinel-grant consume-on-any-terminal-result semantic (task 20260519-211515
R2 / AC2): in addition to consuming the legacy pattern-string grant, this
hook also unlinks any sentinel grant at /tmp/claude-grants/<task_id>.json
when ANY terminal result is observed for the wrapped tool. The four mandated
terminal-consumption cases are: success (exit 0), failure / non_zero exit
(1..255), malformed grant JSON, and comment_only attack (the magic phrase
appears in the command but no sentinel JSON exists). All four unlink the
sentinel grant unconditionally — this is the consume-on-any-terminal-result
contract documented verbatim below.

Exit 0 always (fail-open). Silently exits if no grant or no match.
"""

import glob as _glob
import json
import os
import re as _re
import sys
from pathlib import Path

# Pattern to detect git commit commands (used by deferred-grant finalization).
_GIT_COMMIT_CMD_RE = _re.compile(r'\bgit\b.*\bcommit\b', _re.DOTALL)


def _finalize_deferred_commit_grant(session_id: str, terminal_result: str) -> None:
    """Consume or restore a deferred commit grant (Fix B).

    PreToolUse renames the grant to <path>.lck and writes a pointer at
    /tmp/claude-commit-grant-active-<sid>.json.  This function:
      - terminal_result='success' → unlinks the .lck file (grant consumed)
      - anything else            → renames .lck back to original (retry OK)
    Always removes the pointer file.
    """
    # Collect pointer candidates: session-specific first, then any-SID.
    candidates: list[str] = []
    if session_id:
        candidates.append(f'/tmp/claude-commit-grant-active-{session_id}.json')
    for p in _glob.glob('/tmp/claude-commit-grant-active-*.json'):
        if p not in candidates:
            candidates.append(p)

    for pointer_path in candidates:
        try:
            with open(pointer_path, 'r') as fp:
                pointer = json.load(fp)
        except (OSError, json.JSONDecodeError):
            try:
                os.unlink(pointer_path)
            except OSError:
                pass
            continue

        locked_path = pointer.get('locked_path', '')
        original_path = pointer.get('original_path', '')

        if terminal_result == 'success':
            # Commit-event journal (hooks/lib/commit_journal.py). This is the ONLY moment
            # in the whole lifecycle at which a non-agent observer holds both the identity
            # of the committing session and the sha the commit produced, so it is the only
            # place a durable, non-actor-authored attribution record can be created. Read
            # the grant BEFORE the unlink below destroys it. Wrapped and fail-open: a
            # journal defect must never disturb a commit that has already landed.
            try:
                from lib.commit_journal import append_commit_event
                with open(locked_path, 'r') as fp:
                    append_commit_event(json.load(fp), session_id)
            except Exception:
                pass
            try:
                os.unlink(locked_path)
            except OSError:
                pass
        elif locked_path and original_path and os.path.exists(locked_path):
            try:
                os.rename(locked_path, original_path)
            except OSError:
                # Restore failed — unlink to prevent stale .lck accumulation.
                try:
                    os.unlink(locked_path)
                except OSError:
                    pass

        try:
            os.unlink(pointer_path)
        except OSError:
            pass
        break

sys.path.insert(0, str(Path(__file__).parent))
from lib.allowlist import (  # noqa: E402
    consume_grant_for_posttool,
    consume_sentinel_grant_on_terminal_result,
    match_sentinel_grant_for_write,
)


def _classify_terminal_result(data: dict) -> str:
    """Classify the posttool terminal-result for sentinel consumption.

    Implements consume-on-any-terminal-result: every terminal outcome
    (success, failure, non_zero exit, malformed grant, comment_only attack)
    unlinks the sentinel. The returned label is logged but the unlink is
    unconditional.

    Returns one of: "success", "failure", "non_zero", "malformed",
                    "comment_only", "unknown_terminal".
    """
    response = data.get("tool_response") or {}
    if isinstance(response, dict):
        if response.get("is_error"):
            return "failure"
        exit_code = response.get("exit_code")
        if isinstance(exit_code, int):
            if exit_code == 0:
                return "success"
            if 1 <= exit_code <= 255:
                return "non_zero"
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

    # Legacy grant: always consume on any terminal result, regardless of context.
    # Both main-agent and subagent Bash executions unlink the legacy grant so
    # the main agent cannot reuse a stale grant after a subagent consumed the sentinel.
    consume_grant_for_posttool(session_id, tool_name, command)

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
        if should_consume:
            consume_sentinel_grant_on_terminal_result(task_id, terminal_result)
        # Sentinel consumed — also unlink legacy grant unconditionally.
        # Closes the whitespace-normalization divergence: sentinel uses tokenized
        # matching (handles "git   push") but legacy uses literal substring match.
        if should_consume:
            legacy_path = Path(f"/tmp/claude-bash-allowlist-{session_id}.json")
            try:
                legacy_path.unlink()
            except (FileNotFoundError, OSError):
                pass
            # Cross-SID: orchestrator SID may differ from subagent SID.
            # Unlink orchestrator's legacy grant too if the SIDs diverge.
            orch_sid = os.environ.get("CLAUDE_SESSION_ID", "")
            if orch_sid and orch_sid != session_id:
                orch_legacy = Path(f"/tmp/claude-bash-allowlist-{orch_sid}.json")
                try:
                    orch_legacy.unlink()
                except (FileNotFoundError, OSError):
                    pass
    # Deferred commit grant finalization (Fix B): PostToolUse is the sole
    # consume point for commit grants.  PreToolUse locked the grant (.lck);
    # here we either delete it (success) or restore it (failure, retry OK).
    if tool_name == "Bash" and command and _GIT_COMMIT_CMD_RE.search(command):
        _finalize_deferred_commit_grant(session_id, _classify_terminal_result(data))

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
    sys.exit(0)


if __name__ == "__main__":
    main()
