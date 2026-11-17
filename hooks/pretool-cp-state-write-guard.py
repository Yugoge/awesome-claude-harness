#!/usr/bin/env python3
"""PreToolUse hook: deny direct subagent writes to cp-state-*.json.

Only a direct Write/Edit/MultiEdit/NotebookEdit of a cp-state path exits 2: a
`cp-state-*.json` below a spec root (a `.claude/specs/`, `docs/dev/specs/` or
`dot-claude/specs/` directory). A relative path is read from the call's directory
(the payload's cwd); the path is matched normalised and by the real path of its unfolded
spelling (a symlink is resolved before a `..` after it, as the kernel does), so `./`, `../`,
absolute spellings, a symlink landing in a spec root and `link/../<id>/` are refused alike,
and a `cp-state-*.json` under any other `specs/` (a test fixture) passes;
a Bash command is out of scope (the cooperative threat model needs only the
direct-write check).
Orchestrator (no agent_id) always exits 0.

Failsafe: any unexpected exception exits 0 (never brick the tool pipeline).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Remediation paths are derived from THIS hook's own on-disk location
# (<harness-home>/hooks/<name>.py), so the message names the spec-check.py that
# actually exists for the invoking user instead of an author-absolute literal.
SPEC_CHECK = Path(__file__).resolve().parent.parent / "scripts" / "spec-check.py"

WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

# The spec roots, as path components (compared casefolded).
SPEC_ROOTS = ((".claude", "specs"), ("docs", "dev", "specs"), ("dot-claude", "specs"))


def _read_payload() -> dict:
    try:
        return json.load(sys.stdin)
    except json.JSONDecodeError:
        return {}


def _call_dir(data: dict) -> str:
    cwd = data.get("cwd")
    if isinstance(cwd, str) and os.path.isabs(cwd):
        return cwd
    return os.getcwd()


def _path_candidates(path: str, call_dir: str) -> list:
    # `..` is folded textually (the path as written) and also read as the kernel reads it: the
    # real path of the UNFOLDED spelling, so a symlink is resolved before the `..` that follows
    # it (`link/../s1/x` with `link -> .claude/specs/s1` is `.claude/specs/s1`, not `s1`).
    joined = os.path.join(call_dir, os.path.expanduser(path))
    out = [os.path.normpath(joined)]
    try:
        out.append(os.path.realpath(joined))
    except (OSError, ValueError):
        pass
    return list(dict.fromkeys(out))


def _is_cp_state_under_root(candidate: str) -> bool:
    parts = [p.casefold() for p in candidate.replace("\\", "/").split("/") if p]
    if not parts:
        return False
    name = parts[-1]
    if not (name.startswith("cp-state-") and name.endswith(".json")):
        return False
    for i in range(len(parts)):
        for root in SPEC_ROOTS:
            # the root, then at least a spec id, then the file
            if tuple(parts[i:i + len(root)]) == root and len(parts) >= i + len(root) + 2:
                return True
    return False


def _is_cp_state_path(path: str, call_dir: str) -> bool:
    if not path or not isinstance(path, str):
        return False
    return any(_is_cp_state_under_root(c) for c in _path_candidates(path, call_dir))


def _extract_targets(tool_name: str, tool_input: dict) -> list:
    # Only the direct write tools' paths are scanned.
    if not isinstance(tool_input, dict):
        return []
    if tool_name in WRITE_TOOLS:
        target = tool_input.get("file_path") or tool_input.get("notebook_path")
        return [target] if target else []
    return []


def _emit_block(tool_name: str, target: str) -> None:
    sys.stderr.write(
        "BLOCKED by cp-state write-guard: direct subagent writes to cp-state "
        "files are forbidden (AC-1, spec-20260507-142952; cycle-2 hardening "
        "spec-20260507-191743).\n"
        f"  tool: {tool_name}\n"
        f"  target: {target}\n"
        "spec-check.py is the only legal writer. Use one of:\n"
        f"  python3 {SPEC_CHECK} mark "
        "--spec-id <SPEC_ID> --agent <ROLE> --agent-id <AID> --cp-id <CP>\n"
        f"  python3 {SPEC_CHECK} waive "
        "--spec-id <SPEC_ID> --agent <ROLE> --agent-id <AID> --cp-id <CP>\n"
        f"  python3 {SPEC_CHECK} check-in "
        "--spec-id <SPEC_ID> --agent <ROLE> --agent-id <AID>\n"
        f"  python3 {SPEC_CHECK} check-out "
        "--spec-id <SPEC_ID> --agent <ROLE> --agent-id <AID>\n"
    )


def _check_targets(tool_name: str, targets: list, call_dir: str) -> None:
    for target in targets:
        if _is_cp_state_path(target, call_dir):
            _emit_block(tool_name, target)
            sys.exit(2)


def _is_in_scope(tool_name: str) -> bool:
    # Only the direct write tools are checked.
    return tool_name in WRITE_TOOLS


def _is_subagent(data: dict) -> bool:
    if data.get("agent_id"):
        return True
    if isinstance(data.get("subagent_type"), str) and data.get("subagent_type"):
        return True
    return False


def main() -> None:
    data = _read_payload()
    if not data:
        sys.exit(0)
    if not _is_subagent(data):
        sys.exit(0)
    tool_name = data.get("tool_name")
    if not isinstance(tool_name, str) or not _is_in_scope(tool_name):
        sys.exit(0)
    tool_input = data.get("tool_input") or {}
    targets = _extract_targets(tool_name, tool_input)
    _check_targets(tool_name, targets, _call_dir(data))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # pragma: no cover
        sys.stderr.write(f"pretool-cp-state-write-guard: unexpected ({e})\n")
        sys.exit(0)
