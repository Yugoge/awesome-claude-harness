#!/usr/bin/env python3
"""PreToolUse hook (G1): dispatch obligation gate for producer-role Agent calls.

WHY THIS HOOK EXISTS:
  User ruling (spec-20260930-092323 traceability rows 1-2): artifact-
  completeness detection must move from /close and /commit time -- where the
  producing agent's context is already gone -- to the dispatch moment. This
  is the FIRST of five enforcement doors (G1-G4 + repair engine) that make
  that possible. G1 runs on every Agent dispatch whose subagent_type is a
  producer role and evaluates whether the dispatch prompt carries a valid
  <obligation v="1"> block (hooks/lib/obligation.py grammar), allowing
  (advisory mode) or rejecting (block mode) when it does not.

SEMANTICS (turn-1 blueprint L1, docs/dev/specs/20260930-092323/design/
turn-1-one-shot-blueprint.md:36-50,147-165), first match wins:
  1. CLAUDE_OBLIGATION_GATE == "off" (case/whitespace-insensitive) -> exit 0
     immediately -- the emergency kill switch, checked OUTSIDE the fail-open
     wrapper below so it can never be defeated by an internal bug.
  2. Everything else (stdin read, dispatch selection, obligation evaluation)
     runs inside one try/except. A dispatch is evaluated when its prompt
     contains "<obligation" (any subagent_type) OR the human-typed span it
     lies in (lib/command_span.active_span) is a command whose dispatch
     templates declare an obligation for its subagent_type (_declared_roles,
     read from commands/<command>.md, TC-41); every other dispatch passes
     through untouched.
  3. hooks.lib.obligation.parse_obligation(prompt), with the schema ids of
     the harness's own schemas/registry.json (resolved from the hook's
     location, so a product repo without schemas/ works):
       - ParsedObligation -> its role must equal the dispatch's subagent_type
         (role_mismatch) and its dispatched_at must lie within
         DISPATCH_CLOCK_BOUND_SECONDS of now (dispatch_clock_out_of_bound; an
         uncomparable value fails closed). Otherwise exit 0.
       - NoBlock (a dispatch step 2 requires a block of): missing_block.
       - Rejection (malformed block, unregistered schema id, OR
         tool_input.prompt absent/non-string -- hooks/lib/obligation.py's own
         bad_prompt case): UNCONDITIONAL.
     On a violation advisory mode exits 0; block mode prints the
     three-element stderr message and exits 2.
  4. Any exception raised anywhere in step 2/3 (malformed/empty stdin,
     unreadable dev-registry path, any unexpected internal failure) is caught
     by the single wrapping try/except and the hook exits 0 -- it never
     raises past main() and never exits non-zero outside the deliberate
     block-mode rejection in step 3.

FAIL-OPEN, never-wedge: matches the unified gate template byte-for-byte in
spirit (turn-1-one-shot-blueprint.md:147-165) and
hooks/pretool-do-block-subagents.py's SystemExit-reraise / catch-all idiom.

Validation is delegated ENTIRELY to hooks/lib/obligation.py's
parse_obligation() -- this hook never re-implements obligation-block
grammar or field validation (ticket-20260930-132644-l1 constraint).

Exit codes:
  0 -- allow (pass-through, valid block, or a violation in advisory mode).
  2 -- reject (block mode only: missing block where step 2 requires one, or any
       malformed/invalid block, role mismatch, out-of-bound clock, bad prompt).
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib import command_span, schema_registry, stop_contract  # noqa: E402
from lib.obligation import (  # noqa: E402
    OBLIGATION_OPEN_TOKEN,
    NoBlock,
    ParsedObligation,
    dispatch_clock_within_bound,
    parse_obligation,
)

SWITCH_ENV = "CLAUDE_OBLIGATION_GATE"
# The role an obligation in a command template names: the role="<r>" of a
# template sentence or the "role":"<r>" of a worked example. A placeholder
# role (role="<specialist.type>") names none.
_DECLARED_ROLE_RE = re.compile(r'\brole="([a-z][a-z0-9-]*)"|"role"\s*:\s*"([a-z][a-z0-9-]*)"')
# A canonical todo that is another command's (scripts/todo/redev.py runs
# dev.py's): that command's span runs the other's dispatch templates.
_TODO_DELEGATE_RE = re.compile(r"^from ([a-z][a-z0-9-]*) import get_todos\b", re.M)
TODO_DIR = stop_contract.COMMANDS_DIR.parent / "scripts" / "todo"
GRAMMAR_DOC_REF = "docs/reference/close-commit-zero-failure-mechanism-20260928.md"


def _declared_roles(command) -> frozenset:
    """The roles the active command's dispatch templates declare an obligation
    for (P1b row 18), read from commands/<command>.md whenever asked: a
    dispatch of one of them inside that command's span must carry its block.
    A command whose canonical todo is another's (/redev runs /dev, D22) has
    that command's templates. No list of roles or of commands says which,
    and the roster is not this set: /dev dispatches graphify and its
    specialists without a block."""
    try:
        delegate = _TODO_DELEGATE_RE.search((TODO_DIR / f"{command}.py").read_text(encoding="utf-8"))
    except OSError:
        delegate = None
    if delegate and delegate.group(1) in stop_contract.harness_commands():
        command = delegate.group(1)
    try:
        text = (stop_contract.COMMANDS_DIR / f"{command}.md").read_text(encoding="utf-8")
    except OSError:
        return frozenset()
    return frozenset(sentence or example for sentence, example in _DECLARED_ROLE_RE.findall(text))


def _block_required(transcript_path, subagent_type) -> bool:
    span = command_span.active_span(transcript_path) if transcript_path else None
    return span is not None and subagent_type in _declared_roles(span.command)


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
    prompt = tool_input.get("prompt")
    carries_block = isinstance(prompt, str) and OBLIGATION_OPEN_TOKEN in prompt
    if not carries_block and not _block_required(data.get("transcript_path"), subagent_type):
        return
    session_id = data.get("session_id")
    parsed = parse_obligation(prompt, known_schema_ids=frozenset(schema_registry.load_registry()))
    if isinstance(parsed, ParsedObligation):
        obligation = parsed.obligation
        clock = dispatch_clock_within_bound(
            obligation.get("dispatched_at"), datetime.now(timezone.utc)
        )
        if obligation.get("role") != subagent_type:
            reason = "role_mismatch"
        elif clock is not True:
            reason = "dispatch_clock_out_of_bound" if clock is False else "dispatch_clock_unverifiable"
        else:
            return
    elif isinstance(parsed, NoBlock):  # reached only where a block is required
        reason = "missing_block"
    else:  # Rejection -- unconditional, whatever the span
        reason = parsed.reason
    if mode == "block":
        _emit_block(session_id, subagent_type, reason)
        sys.exit(2)


def main() -> None:
    if os.environ.get(SWITCH_ENV, "").strip().lower() == "off":
        sys.exit(0)
    try:
        data = json.load(sys.stdin)
        mode = os.environ.get(SWITCH_ENV, "advisory").strip().lower()
        _evaluate(data, mode)
    except SystemExit:
        raise
    except Exception:
        pass  # fail open: an internal error never blocks a dispatch
    sys.exit(0)


if __name__ == "__main__":
    main()
