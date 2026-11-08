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
     read from the command's text as the CLI recorded it when it was typed,
     else from commands/<command>.md, TC-41); every other dispatch passes
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
     On a violation advisory mode prints the reason on one stderr line
     (OBLIGATION GATE ADVISORY) and exits 0; block mode prints the
     three-element stderr message and exits 2.
     A valid block in block mode is then held to dispatch order (R17,
     _order_findings): ORDER_EXIT decides the exit of a finding.
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
  0 -- allow (pass-through, valid block, or a violation in advisory mode,
       its reason on stderr; nothing is written).
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
# R17's finding blocks, like every G1 finding in block mode.
ORDER_EXIT = 2
# The verdict a later consumer of the judged producer's artifacts waits for:
# "every BA invocation MUST be followed by QA validation" (commands/dev.md).
VERDICT_SCHEMA = "ba-qa-report.v1"


def _declared_roles(command, text=None) -> frozenset:
    """The roles the active command's dispatch templates declare an obligation
    for (P1b row 18): a dispatch of one of them inside that command's span
    must carry its block. They are read from ``text``, the command as the
    session loaded it (Span.body), else from commands/<command>.md: a session
    that started before an update follows the prose it loaded, and the
    templates it writes from are that prose's. A command whose canonical todo
    is another's (/redev runs /dev, D22) has that command's templates, read
    from its file. No list of roles or of commands says which, and the
    roster is not this set: /dev dispatches graphify and its specialists
    without a block."""
    try:
        delegate = _TODO_DELEGATE_RE.search((TODO_DIR / f"{command}.py").read_text(encoding="utf-8"))
    except OSError:
        delegate = None
    if delegate and delegate.group(1) in stop_contract.harness_commands():
        command, text = delegate.group(1), None
    if text is None:
        try:
            text = (stop_contract.COMMANDS_DIR / f"{command}.md").read_text(encoding="utf-8")
        except OSError:
            return frozenset()
    return frozenset(sentence or example for sentence, example in _DECLARED_ROLE_RE.findall(text))


def _block_required(transcript_path, subagent_type) -> bool:
    span = command_span.active_span(transcript_path) if transcript_path else None
    return span is not None and subagent_type in _declared_roles(span.command, span.body())


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


def _declared(obligation) -> dict:
    """path -> schema of each artifact an obligation declares."""
    return {a["path"]: a.get("schema") for a in obligation.get("artifacts") or []
            if isinstance(a, dict) and isinstance(a.get("path"), str)}


def _resumed_returns(span, session_id, before) -> dict:
    """{id of an Agent call that never came back: the line its agent's resume
    returned at} for the agents the /restart recovery resumed and saw come
    back (subagent_restart.completed_resumes, the journal Gate 4 reads; P1c
    R15): that call is its step's dispatch, with no replacement call
    (commands/restart.md, Lesson 16), and it returned when its resume did."""
    try:
        from lib.subagent_restart import completed_resumes
        journal = completed_resumes(session_id) if session_id else {}
    except Exception:
        return {}
    returns = {}
    for message in span.iter_calls("SendMessage", before=before) if journal else ():
        original = journal.get(str((message.input or {}).get("to")))
        if original and message.result_line and message.ok:
            returns[original] = message.result_line
    return returns


def _order_findings(data: dict, obligation: dict, prompt: str, known: frozenset) -> list:
    """R17, read from the active span's dispatch order (the CLI's record of
    each Agent call and its result, never a file's mtime or a clock): for
    each artifact this prompt names that an earlier dispatch declared, the
    latest such dispatch must have returned; and unless this dispatch is a
    verdict itself, the latest verdict naming that producer's artifacts must
    be issued after it returned and have returned too. A refused or errored
    dispatch (an is_error result) ran nothing, so it has not returned; a cut
    dispatch whose agent the /restart recovery resumed returned when its
    resume did (_resumed_returns)."""
    span = command_span.active_span(data["transcript_path"]) if data.get("transcript_path") else None
    if span is None:
        return []
    resumed = _resumed_returns(span, data.get("session_id") or data.get("sessionId"),
                               data.get("tool_use_id") or None)
    returned_at = lambda c: c.result_line if (c.result_line and c.ok) else resumed.get(c.id)
    earlier = []
    for call in span.iter_calls("Agent", "Task", before=data.get("tool_use_id") or None):
        parsed = parse_obligation(call.input.get("prompt"), known_schema_ids=known)
        if isinstance(parsed, ParsedObligation):
            earlier.append((call, parsed.obligation.get("role"), _declared(parsed.obligation)))
    own = _declared(obligation)
    upstream = {path: entry for entry in earlier for path in entry[2] if path not in own and path in prompt}
    findings, seen = [], set()
    for path, (call, role, paths) in upstream.items():
        if call.id in seen:
            continue
        seen.add(call.id)
        stopped = returned_at(call)
        if not stopped:
            findings.append(f"reason=producer_not_stopped artifact={path}: declared by dispatch "
                            f"{call.id} ({role}), which has not returned a result")
            continue
        verdicts = [(v, vpath) for v, _role, vpaths in earlier for vpath, schema in vpaths.items()
                    if schema == VERDICT_SCHEMA and not set(vpaths) & set(paths)
                    and any(p in v.input["prompt"] for p in paths)]
        if verdicts and VERDICT_SCHEMA not in own.values():
            verdict, vpath = verdicts[-1]
            returned = bool(returned_at(verdict))
            if verdict.line < stopped or not returned:
                findings.append(
                    f"reason=verdict_not_after_producer_stop artifact={vpath}: the latest verdict on "
                    f"{path}, dispatch {verdict.id} (line {verdict.line}, "
                    f"{'returned' if returned else 'not returned'}), does not follow the "
                    f"return of dispatch {call.id} ({role}) at line {stopped}")
    return findings


def _emit_order(session_id, subagent_type, findings) -> None:
    sys.stderr.write(
        "\nOBLIGATION GATE ORDER (pretool-obligation-gate, R17):\n"
        f"  session={session_id} subagent_type={subagent_type}\n"
        + "".join(f"  {finding}\n" for finding in findings)
        + "  fix: dispatch this once the dispatch named above has returned (for a verdict, once a\n"
        "  verdict dispatched after that return has returned).\n\n"
    )
    sys.exit(ORDER_EXIT)


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
    known = frozenset(schema_registry.load_registry())
    parsed = parse_obligation(prompt, known_schema_ids=known)
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
            findings = _order_findings(data, obligation, prompt, known) if mode == "block" else []
            if findings:
                _emit_order(session_id, subagent_type, findings)
            return
    elif isinstance(parsed, NoBlock):  # reached only where a block is required
        reason = "missing_block"
    else:  # Rejection -- unconditional, whatever the span; the field it failed named
        reason = parsed.reason + (f" at {parsed.field}" if getattr(parsed, "field", "") else "")
    if mode == "block":
        _emit_block(session_id, subagent_type, reason)
        sys.exit(2)
    sys.stderr.write(f"OBLIGATION GATE ADVISORY (pretool-obligation-gate): would block "
                     f"session={session_id} subagent_type={subagent_type} reason={reason}\n")


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
