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
4. No target: allow (a parse problem never blocks).
5. The target is an existing file: refused, Edit it in place instead, unless
   overwrite_exempt() says the file is a scratch, temp or untracked generated output
   (OB-L46, owner decision).
An /allow grant releases any refusal of this rule where the pre-tool verdicts meet
(lib/hook_launch.release_refused); the rule reads none.

The OB-L46 exemption, its protected set (harness state, another session's scratch,
gate-read artifacts, configuration, hard-linked and tracked files) and the line between
an untracked own output and a gate-read artifact are in lib/write_gate/overwrite_scope.py.
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


def overwrite_exempt(file_path: str, session_id: str) -> bool:
    """OB-L46: lib/write_gate/overwrite_scope.py decides; any failure to load it refuses."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import overwrite_scope
        return overwrite_scope.overwrite_exempt(file_path, session_id)
    except BaseException:
        return False


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

    if _consent(data):
        return 0
    if not file_path:
        return 0
    session_id = _shell_str(data.get("session_id", "") or os.environ.get("CLAUDE_SESSION_ID", ""))
    if os.path.isfile(file_path) and not overwrite_exempt(file_path, session_id):
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
