#!/usr/bin/env python3
"""
PreToolUse Hook: Block foreground Agent during an active /spec Interview.

Activation conditions (ALL must be true to block):
  1. tool_name == "Agent"
  2. tool_input.get("run_in_background") is not True
     (background Explore agents are explicitly allowed by spec.md
      Interview Rule 5)
  3. data.get("agent_id") is falsy
     (nested subagent calls are exempt -- field name "agent_id" matches
      pretool-orchestrator-gate.py:71 and pretool-read-size-guard.py:23)
  4. The transcript's active span was opened by /spec
  5. Its checklist (the last ok TodoWrite, or the canonical list before the
     first) has at least one step where status != "completed"
  (4 and 5 are read from the transcript, lib.todo_canonical.checklist.)

Exit 0 = allow. Exit 2 = block (stderr message shown to user).

Fail-open: any unexpected exception -> sys.exit(0). Never block on
malformed input, missing env vars, or corrupt state files.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.todo_canonical import checklist  # noqa: E402


def _spec_todo_progress(data: dict):
    """(done, total) of the active /spec span's checklist, or None when the
    active span is not /spec."""
    state = checklist(data.get("transcript_path"))
    if state is None or state.command != "spec":
        return None
    todos = state.todos if state.todos is not None else state.canonical
    done = sum(1 for t in todos if t.get("status") == "completed")
    return done, len(todos)


def _tool_is_exempt(data: dict) -> bool:
    """Exemptions that short-circuit the block decision (arch-10 + background)."""
    tool_input = data.get("tool_input") or {}
    if tool_input.get("run_in_background") is True:
        return True
    # arch-10: the spec subagent itself must be allowed as /spec Step 8
    if tool_input.get("subagent_type") == "spec":
        return True
    # M1 (harness-fixes 20260428): /spec Step 6 sub-step 3 mandates a
    # foreground qa Agent for split-validation. Exempt qa alongside spec.
    # Activation gate (the active span is /spec) is unchanged, so the
    # exemption is bounded to the /spec interview FSM window.
    if tool_input.get("subagent_type") == "qa":
        return True
    if data.get("agent_id"):
        return True
    return False


def _should_block(data: dict) -> tuple[bool, int, int]:
    """Evaluate activation conditions. Returns (block, done_count, total_count)."""
    if data.get("tool_name") != "Agent":
        return False, 0, 0
    if _tool_is_exempt(data):
        return False, 0, 0
    progress = _spec_todo_progress(data)
    if progress is None:
        return False, 0, 0
    done, total = progress
    if done >= total:
        return False, 0, 0
    return True, done, total


def _emit_block_message(done: int, total: int) -> None:
    """Write the multi-line block explanation to stderr."""
    sys.stderr.write(
        "SPEC INTERVIEW IN PROGRESS\n"
        f"A /spec interview is currently active ({done}/{total} steps complete).\n"
        "Foreground Agent calls are blocked until the interview finishes.\n"
        "To unblock:\n"
        f"  - Continue the interview and complete all {total} steps\n"
        "  - OR mark all todos completed via TodoWrite\n"
        "Background agents (run_in_background: true) are always allowed "
        "during the interview.\n"
    )


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        # Fail-open on malformed stdin
        sys.exit(0)

    try:
        block, done, total = _should_block(data)
    except Exception:
        # Fail-open on any unexpected error inside the evaluator
        sys.exit(0)

    if block:
        _emit_block_message(done, total)
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
