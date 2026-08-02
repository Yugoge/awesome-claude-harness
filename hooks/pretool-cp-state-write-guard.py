#!/usr/bin/env python3
"""PreToolUse hook: deny direct subagent writes to cp-state-*.json.

Cycle-3 slim form (2026-05-14): Bash-extractor removed — 22-form adversarial
scanner was over-engineering of cooperative-threat model. Only direct
Write/Edit/MultiEdit/NotebookEdit on cp-state paths exit 2.
Orchestrator (no agent_id) always exits 0.

Failsafe: any unexpected exception exits 0 (never brick the tool pipeline).
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Remediation paths are derived from THIS hook's own on-disk location
# (<harness-home>/hooks/<name>.py), so the message names the spec-check.py that
# actually exists for the invoking user instead of an author-absolute literal.
SPEC_CHECK = Path(__file__).resolve().parent.parent / "scripts" / "spec-check.py"

from lib.bash_write_targets import extract_bash_write_paths  # noqa: E402

WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

_CP_STATE_GLOBS = [
    "*/.claude/specs/*/cp-state-*.json",
    "*/docs/dev/specs/*/cp-state-*.json",
    "*/dot-claude/specs/*/cp-state-*.json",
]


def _read_payload() -> dict:
    try:
        return json.load(sys.stdin)
    except json.JSONDecodeError:
        return {}


def _path_candidates(path: str) -> list:
    abs_p = os.path.abspath(path)
    try:
        real = os.path.realpath(path)
    except OSError:
        return [abs_p]
    if real == abs_p:
        return [abs_p]
    return [abs_p, real]


def _matches_any_glob(candidate: str) -> bool:
    return any(fnmatch.fnmatchcase(candidate, p) for p in _CP_STATE_GLOBS)


def _is_cp_state_components(candidate: str) -> bool:
    if not candidate or not isinstance(candidate, str):
        return False
    parts = candidate.rstrip("/").split("/")
    if len(parts) < 3:
        return False
    basename = parts[-1]
    if not basename.startswith("cp-state-") or not basename.endswith(".json"):
        return False
    return parts[-3] == "specs"


def _is_cp_state_path(path: str) -> bool:
    if not path:
        return False
    for c in _path_candidates(path):
        if _is_cp_state_components(c) or _matches_any_glob(c):
            return True
    return False


def _extract_targets(tool_name: str, tool_input: dict) -> list:
    # Cycle-3 slim form: only direct Write/Edit/MultiEdit/NotebookEdit paths
    # are scanned. Cycle-2 Bash extractor removed (adversarial-threat-model
    # over-engineering; cooperative model only needs L1 direct-write check).
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


def _check_targets(tool_name: str, targets: list) -> None:
    for target in targets:
        if _is_cp_state_path(target):
            _emit_block(tool_name, target)
            sys.exit(2)


def _is_in_scope(tool_name: str) -> bool:
    # Cycle-3 slim form: drop Bash from scope; only direct write tools
    # are checked. See _extract_targets comment for rationale.
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
    _check_targets(tool_name, targets)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # pragma: no cover
        sys.stderr.write(f"pretool-cp-state-write-guard: unexpected ({e})\n")
        sys.exit(0)
