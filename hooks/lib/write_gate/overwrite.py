#!/usr/bin/env python3
"""Write-gate rule: Write never replaces an existing file; nothing writes the bulk-commit sentinel.

The Python form of hooks/pretool-write-guard.sh, decision for decision and message for
message (hooks/tests/test_write_gate_overwrite_parity.py runs both over one corpus).
It is a rule of hooks/pretool-write-gate.py, which runs it as ``__main__``; it can also
run alone. Exit 0 allows, exit 2 refuses with the reason on stderr.

1. Bulk-commit sentinel (every actor, the main agent included; no /do or /allow
   exemption): a Write or NotebookEdit whose target's name is
   ``claude-bulk-commit-sentinel-*.json`` is refused. Only the orchestrator's /commit
   --bulk route mints it. (The shell hook was registered on Write alone, so its
   NotebookEdit branch never ran; the gate gives this rule the same tool set.)
2. Every other check is for Write only.
3. /do consent (lib.allowlist.has_do_consent: the main agent, the flag holding true)
   allows the Write.
4. The main agent's /allow grant for Write: a grant that names this target allows it;
   a valid same-session grant that names another target refuses an overwrite of an
   existing file (CF-1) and leaves a new file's creation to step 6.
5. No target: allow (a parse problem never blocks).
6. The target is an existing file: refused, Edit it in place instead.
"""
from __future__ import annotations

import fnmatch
import json
import os
import sys

_HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _err(*lines: str) -> None:
    sys.stderr.write("".join(f"{line}\n" for line in lines))


def _shell_str(value) -> str:
    """What the shell hook's ``print(value)`` put into its variable (None prints "None")."""
    return "" if value == "" else str(value)


def _bulk_target(data: dict) -> str:
    try:
        ti = data.get("tool_input", {})
        return _shell_str(ti.get("file_path") or ti.get("notebook_path") or "")
    except Exception:
        return ""


def _field(data: dict, key: str) -> str:
    try:
        if key == "file_path":
            return _shell_str(data.get("tool_input", {}).get("file_path", ""))
        return _shell_str(data.get(key, ""))
    except Exception:
        return ""


def _consent(data) -> bool:
    try:
        sys.path.insert(0, os.path.join(_HOOKS_DIR, "lib"))
        from allowlist import has_do_consent
        return bool(has_do_consent(data))
    except BaseException:
        return False


def _sentinel(session_id: str, data_task_id: str, env_task_id: str, target: str) -> str:
    """'match', 'valid_no_match' or 'none' (and 'none' when the lookup fails)."""
    try:
        sys.path.insert(0, _HOOKS_DIR)
        from lib.allowlist import match_sentinel_grant_for_write, load_sentinel_grant_for_task
        writer_key = env_task_id if env_task_id else session_id
        seen, candidates = set(), []
        for k in (writer_key, data_task_id, session_id):
            if k and k not in seen:
                seen.add(k)
                candidates.append(k)
        any_valid = False
        for key in candidates:
            g = load_sentinel_grant_for_task(key)
            if g is None or g.get("session_id") != session_id:
                continue
            any_valid = True
            if match_sentinel_grant_for_write(key, session_id, target) is not None:
                return "match"
        return "valid_no_match" if any_valid else "none"
    except BaseException:
        return "none"


def main() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
        tool = _shell_str(data.get("tool_name", ""))
    except Exception:
        return 0

    if tool in ("Write", "NotebookEdit"):
        target = _bulk_target(data)
        if fnmatch.fnmatchcase(target, "*/claude-bulk-commit-sentinel-*.json"):
            _err(f"BLOCKED: bulk-commit-sentinel-write — writing to claude-bulk-commit-sentinel-*.json via {tool} is FORBIDDEN",
                 f"Target: {target}",
                 "REASON: per task 20260524-205206 M4.3, only the orchestrator via /commit --bulk may",
                 "        create the bulk-commit sentinel. ALL model tool calls are denied",
                 "        regardless of agent_id (main agent and subagent equally blocked).")
            return 2

    if tool != "Write":
        return 0

    file_path = _field(data, "file_path")
    task_id = _field(data, "task_id")
    env_task_id = os.environ.get("CLAUDE_TASK_ID", "")

    if _consent(data):
        return 0
    if not data.get("agent_id"):
        sid = _shell_str(data.get("session_id", "") or os.environ.get("CLAUDE_SESSION_ID", "default")) or "default"
        result = _sentinel(sid, task_id, env_task_id, file_path)
        if result == "match":
            return 0
        if result == "valid_no_match" and os.path.isfile(file_path):
            _err("[Write Guard] BLOCKED: sentinel grant does not cover this target.",
                 f"Target: {file_path}",
                 "A valid sentinel grant exists for this task, but it does NOT name this file,",
                 "so it confers no permission to overwrite it. The grant is scoped on purpose:",
                 "an approval for one path is not an approval for every path.",
                 "Two ways forward:",
                 "  1. Re-issue the grant naming this exact path, if overwriting it is genuinely intended.",
                 "  2. Modify the existing file in place (Edit) instead of replacing it wholesale.")
            return 2

    if not file_path:
        return 0
    if os.path.isfile(file_path):
        _err(f"[Write Guard] BLOCKED: File already exists: {file_path}",
             "Write would replace this file wholesale, so every byte of the new content has to be",
             "reproduced from memory. Any field you forgot to carry over, or mis-remembered, would be",
             "silently lost — there is no diff to reveal what went missing.",
             "Modify the existing file IN PLACE instead (Edit), changing only the fields that need to",
             "change. Reserve Write for files that genuinely do not exist yet.")
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
