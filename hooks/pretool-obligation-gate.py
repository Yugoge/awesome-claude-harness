#!/usr/bin/env python3
"""PreToolUse hook (G1): dispatch obligation gate for producer-role Agent calls.

WHY THIS HOOK EXISTS:
  User ruling (spec-20260930-092323 traceability rows 1-2): artifact-
  completeness detection must move from /close and /commit time -- where the
  producing agent's context is already gone -- to the dispatch moment. This
  is the FIRST of five enforcement doors (G1-G4 + repair engine) that make
  that possible. G1 runs on every Agent dispatch whose subagent_type is a
  producer role and evaluates whether the dispatch prompt carries a valid
  <obligation v="1"> block (hooks/lib/obligation.py grammar), logging
  (advisory mode) or rejecting (block mode) when it does not.

SEMANTICS (turn-1 blueprint L1, docs/dev/specs/20260930-092323/design/
turn-1-one-shot-blueprint.md:36-50,147-165), first match wins:
  1. CLAUDE_OBLIGATION_GATE == "off" (case/whitespace-insensitive) -> exit 0
     immediately -- the emergency kill switch, checked OUTSIDE the fail-open
     wrapper below so it can never be defeated by an internal bug.
  2. Everything else (stdin read, producer-role check, obligation evaluation)
     runs inside one try/except: tool_input.subagent_type not in the producer
     set {ba, dev, qa, test-writer, changelog-analyst, style-inspector,
     cleanliness-inspector, prompt-inspector} -> exit 0, no log (every other
     dispatch, including the main agent, passes through untouched).
  3. hooks.lib.obligation.parse_obligation(prompt) on a producer dispatch:
       - ParsedObligation (valid block) -> exit 0, no log.
       - NoBlock (no block at all): gated on whether
         .claude/dev-registry/<session_id>/ exists (an active dev-family
         session). Absent -> exit 0, nothing logged. Present -> advisory
         record (reason="missing_block"); advisory mode then exits 0, block
         mode additionally prints a three-element stderr message and exits 2.
       - Rejection (malformed block, OR tool_input.prompt absent/non-string --
         hooks/lib/obligation.py's own bad_prompt case): UNCONDITIONAL, never
         gated on dev-registry presence -- advisory record carries the
         validator's own .reason; advisory mode exits 0, block mode also
         prints the three-element stderr message (with that specific reason)
         and exits 2.
  4. Any exception raised anywhere in step 2/3 (malformed/empty stdin,
     unreadable dev-registry path, any unexpected internal failure) is caught
     by the single wrapping try/except: a best-effort advisory record with
     reason="gate_error" is written and the hook exits 0 -- it never raises
     past main() and never exits non-zero outside the deliberate block-mode
     rejection in step 3.

FAIL-OPEN, never-wedge: matches the unified gate template byte-for-byte in
spirit (turn-1-one-shot-blueprint.md:147-165) and
hooks/pretool-do-block-subagents.py's SystemExit-reraise / catch-all idiom.

Validation is delegated ENTIRELY to hooks/lib/obligation.py's
parse_obligation() -- this hook never re-implements obligation-block
grammar or field validation (ticket-20260930-132644-l1 constraint).

Exit codes:
  0 -- allow (pass-through, valid block, or advisory-logged-and-pass).
  2 -- reject (block mode only: missing block + active dev-family session,
       or any malformed/invalid block / bad prompt).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.obligation import NoBlock, ParsedObligation, parse_obligation  # noqa: E402

SWITCH_ENV = "CLAUDE_OBLIGATION_GATE"
PRODUCER_ROLES = frozenset({
    "ba", "dev", "qa", "test-writer", "changelog-analyst",
    # 20261001-161041-r11: the three /close-dispatched inspectors gain the
    # same producer-role enforcement already applied to the five roles
    # above (G1 dispatch gate coverage for their report obligations).
    "style-inspector", "cleanliness-inspector", "prompt-inspector",
})
ADVISORY_LOG = os.path.join("~", ".claude", "logs", "obligation-gate-advisory.jsonl")
GRAMMAR_DOC_REF = "docs/reference/close-commit-zero-failure-mechanism-20260928.md"


def _resolve_project_dir() -> str:
    """Mirrors hooks/pretool-aggregate-check.py:386."""
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def _dev_registry_dir_exists(session_id) -> bool:
    return (Path(_resolve_project_dir()) / ".claude" / "dev-registry" / session_id).is_dir()


def _emit_advisory(session_id, subagent_type, reason) -> None:
    """Best-effort JSONL append. A log-write failure must never affect the
    exit code (M4) -- kept LOCAL, not imported, per the documented rationale
    in hooks/subagentstop-artifact-contract-enforce.py (an unrelated refactor
    of a shared helper must never silently disable this gate)."""
    try:
        log_path = os.path.expanduser(ADVISORY_LOG)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "session_id": session_id,
            "subagent_type": subagent_type,
            "reason": reason,
        }
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
    except Exception:
        pass


def _emit_block(session_id, subagent_type, reason) -> None:
    sys.stderr.write(
        "\nOBLIGATION GATE BLOCK (pretool-obligation-gate):\n"
        f"  session={session_id} subagent_type={subagent_type}\n"
        f'  what-is-missing: this dispatch\'s prompt carries no valid '
        f'<obligation v="1"> block (reason={reason}).\n'
        "  whose-responsibility: the orchestrator that issued this Agent "
        "dispatch -- the obligation block belongs in the dispatch prompt it "
        "writes.\n"
        f'  fix: add a well-formed <obligation v="1">{{...}}</obligation> '
        f"block to the dispatch prompt; see {GRAMMAR_DOC_REF} section 1.2 "
        "for the grammar.\n\n"
    )


def _evaluate(data: dict, mode: str) -> None:
    """Producer-role check + obligation evaluation (turn-1 microsteps 3-4)."""
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    subagent_type = tool_input.get("subagent_type")
    if subagent_type not in PRODUCER_ROLES:
        return
    session_id = data.get("session_id")
    parsed = parse_obligation(tool_input.get("prompt"), known_schema_ids=None)
    if isinstance(parsed, ParsedObligation):
        return
    if isinstance(parsed, NoBlock):
        if not _dev_registry_dir_exists(session_id):
            return
        reason = "missing_block"
    else:  # Rejection -- unconditional, never gated on dev-registry presence
        reason = parsed.reason
    _emit_advisory(session_id, subagent_type, reason)
    if mode == "block":
        _emit_block(session_id, subagent_type, reason)
        sys.exit(2)


def main() -> None:
    if os.environ.get(SWITCH_ENV, "").strip().lower() == "off":
        sys.exit(0)
    data: dict = {}
    try:
        data = json.load(sys.stdin)
        mode = os.environ.get(SWITCH_ENV, "advisory").strip().lower()
        _evaluate(data, mode)
    except SystemExit:
        raise
    except Exception:
        session_id = data.get("session_id") if isinstance(data, dict) else None
        tool_input = data.get("tool_input") if isinstance(data, dict) else None
        subagent_type = tool_input.get("subagent_type") if isinstance(tool_input, dict) else None
        _emit_advisory(session_id, subagent_type, "gate_error")
    sys.exit(0)


if __name__ == "__main__":
    main()
