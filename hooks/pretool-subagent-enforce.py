#!/usr/bin/env python3
"""
PreToolUse:Agent Hook — Contract-driven role/pipeline enforcement (G1).

For a /dev-overnight session (the session owns an overnight state record):

  1. Derive the calls the cycle allows: its exploration (PM PLAN through PM
     TRIAGE, steps 2-4) from scripts/todo/dev-overnight.py ``_STEPS``, plus
     the cycle's contract once PM TRIAGE returned (written by the PM TRIAGE
     handler in posttool-subagent-track.py). The cycle is
     ``lib.overnight.cycle_index``.
  2. Derive the current step from the checklist the transcript records
     (lib.todo_canonical.checklist): the in-progress step of the last list the
     step rules accepted, in every cycle.
  3. Validate the about-to-fire Agent's role / pipeline_id / mode against
     the entries for that step. On mismatch, exit 2 with a structured stderr
     message.

A session with no overnight state is not an overnight workflow and is not
contracted: exit 0 silently.

Exit codes:
  0 — Allow (not an overnight session, or call matches an allowed entry).
  2 — Reject (role/pipeline_id/mode mismatch against the allowed calls).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib import contract_runtime  # noqa: E402
from lib import overnight  # noqa: E402
from lib.todo_canonical import checklist  # noqa: E402
from lib.subagent import is_subagent_context  # noqa: E402
from lib.allowlist import has_do_consent, match_sentinel_grant_for_tool  # noqa: E402


def _parse_stdin() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def _content_to_step(content: str) -> str:
    """Map a todo content string ('Step 2a: ...') to a bare label ('2a')."""
    if content.startswith('Step '):
        head = content.split(':', 1)[0]
        return head.replace('Step ', '').strip()
    return content


def _current_step_label(stdin_data: dict) -> str | None:
    """The in-progress step label of the session's checklist, read from the
    transcript."""
    state = checklist(stdin_data.get('transcript_path'))
    for item in (state.accepted if state else None) or []:
        if item.get('status') == 'in_progress':
            return _content_to_step(item.get('content', ''))
    return None


def _resolve_session(stdin_data: dict) -> tuple[str, dict | None]:
    """(session_id, the session's overnight state record)."""
    session_id = stdin_data.get('session_id', 'default')
    return session_id, overnight.session_state(session_id)


def _allowed_calls(overnight_state: dict):
    """The calls this cycle allows, as a contract-shaped dict, or None when the
    canonical steps cannot be read (nothing to derive, so nothing to enforce).

    A cycle contract that is not a JSON object is returned as is, so the block
    names it (Case M) instead of falling back to the exploration steps.
    """
    steps = contract_runtime.overnight_steps()
    if not steps:
        return None
    cycle_id = overnight.cycle_index(overnight_state)
    calls = contract_runtime.exploration_calls(steps)
    contract = contract_runtime.load_contract(
        overnight_state.get('session_id', ''), cycle_id, overnight_state)
    if contract is not None and not isinstance(contract, dict):
        return contract
    calls += contract_runtime._iter_required_calls(contract)
    return {'cycle_id': cycle_id, 'required_calls': calls}


def _detect_pipeline_id_from_prompt(prompt: str) -> str:
    """Heuristically identify a pipeline_id token (e.g. 'pipeline-3')."""
    match = re.search(r'pipeline[-_](\w+)', prompt, re.IGNORECASE)
    return f'pipeline-{match.group(1)}' if match else ''


def _resolve_pipeline_id(ti: dict, prompt: str) -> str:
    """T2.3: explicit tool_input.pipeline_id wins; prompt regex is fallback."""
    if not isinstance(ti, dict):
        return _detect_pipeline_id_from_prompt(prompt)
    explicit = ti.get('pipeline_id') or ti.get('pipelineId')
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    return _detect_pipeline_id_from_prompt(prompt)


def _extract_agent_fields(stdin_data: dict) -> tuple[str, str, str]:
    """Return (role, mode, pipeline_id) extracted from Agent call."""
    ti = stdin_data.get('tool_input', {}) or {}
    role = (ti.get('subagent_type') or '').strip().lower()
    prompt = ti.get('prompt', '') if isinstance(ti, dict) else ''
    mode = contract_runtime.detect_mode(prompt)
    pipeline_id = _resolve_pipeline_id(ti, prompt)
    return role, mode, pipeline_id


def _contracted_step_id_list(contract) -> list:
    """Return the contract's valid step ids as a list, order-preserved + deduped.

    Uses the isinstance-guarded accessor contract_runtime._iter_required_calls
    (NEVER a direct required_calls subscript on the contract — that raises
    TypeError on a non-dict contract). Keeps only dict entries with a
    non-empty str 'step', dedupes via a seen-set in CONTRACT ORDER (no sort).

    This is the DATA helper: case discrimination keys off the EMPTINESS of
    this list, not off the rendered string, so a contract whose only step is
    literally named '<none>' is correctly treated as a non-empty contract
    (Case A) rather than colliding with the empty-render sentinel (Case C).
    """
    seen: set[str] = set()
    ordered: list = []
    for entry in contract_runtime._iter_required_calls(contract):
        if not isinstance(entry, dict):
            continue
        step = entry.get('step')
        if not isinstance(step, str) or not step:
            continue
        if step not in seen:
            seen.add(step)
            ordered.append(step)
    return ordered


def _expected_signatures(contract, step: str) -> str:
    """Render the expected role/mode/pipeline_id signature(s) for a step.

    Enumerates ALL required_calls entries whose 'step' equals the resolved
    step, not just the single best-matched entry, so a Case B banner shows
    every contracted shape the agent could satisfy. '<any>' marks an
    unconstrained (wildcard) dimension.
    """
    sigs: list[str] = []
    for entry in contract_runtime._iter_required_calls(contract):
        if not isinstance(entry, dict) or entry.get('step') != step:
            continue
        role = entry.get('role') or '<any>'
        mode = entry.get('mode') or '<any>'
        pipeline = entry.get('pipeline_id') or '<any>'
        sigs.append(f'(role={role} mode={mode} pipeline_id={pipeline})')
    return ' | '.join(sigs) if sigs else '<none>'


def _diagnose_block(contract, valid_ids: str, has_step_ids: bool, entry, step: str) -> tuple[str, str]:
    """Four-way diagnosis (QA OBJ1 + codex). Returns (diagnosis, action).

    Discrimination order (structural, NEVER off result['errors'] content):
      1. not isinstance(contract, dict)             -> Case M
      2. not has_step_ids and entry is None         -> Case C
      3. entry is None                              -> Case A
      4. else (entry present)                       -> Case B

    ``has_step_ids`` is the EMPTINESS of the data step-id list (not the
    rendered '<none>' string), so a contract whose only step is literally
    named '<none>' is Case A (stale step), not Case C (incomplete).
    """
    if not isinstance(contract, dict):
        return (
            "Case M (contract malformed/non-dict): the loaded cycle-contract is "
            "not a JSON object, so it has no usable required_calls.",
            "do not retry by re-marking the step; re-publish the contract / request "
            "orchestrator escalation.",
        )
    if not has_step_ids and entry is None:
        return (
            "Case C (incomplete contract): the contract is present but has no "
            "usable contracted steps.",
            "do not retry by re-marking the step; re-publish the contract / request "
            "orchestrator escalation.",
        )
    if entry is None:
        return (
            f"Case A (stale step): the resolved step '{step}' has no "
            "required_calls entry. The in-progress todo is most likely not on "
            "an agent-dispatching step that owns an entry.",
            f"advance the in-progress todo to one of the valid_contracted_step_ids "
            f"({valid_ids}) and mark it in_progress before re-dispatching, OR "
            "request orchestrator escalation.",
        )
    return (
        f"Case B (dimension mismatch): step '{step}' has an entry, but the Agent "
        "call does not satisfy the required role/mode/pipeline dimensions.",
        "fix the Agent's role/mode/pipeline_id to match an expected signature for "
        "the resolved step, OR request orchestrator escalation.",
    )


def _emit_block(step: str, role: str, pipeline_id: str, errors: list,
                mode: str = '', entry=None, contract=None) -> None:
    step_ids = _contracted_step_id_list(contract)
    valid_ids = ', '.join(step_ids) if step_ids else '<none>'
    diagnosis, action = _diagnose_block(
        contract, valid_ids, bool(step_ids), entry, step)
    sys.stderr.write(
        '\nCONTRACT BLOCK (pretool-subagent-enforce):\n'
        f'  step={step} source=current in-progress Todo\n'
        f'  attempted_role={role or "<none>"} attempted_mode={mode or "<none>"} '
        f'attempted_pipeline_id={pipeline_id or "<none>"}\n'
        f'  valid_contracted_step_ids={valid_ids}\n'
        f'  diagnosis: {diagnosis}\n'
        f'  expected_for_resolved_step: {_expected_signatures(contract, step)}\n'
        f'  action: {action}\n'
        '  errors:\n'
    )
    for err in errors:
        sys.stderr.write(f'    - {err}\n')
    sys.stderr.write('\n')


def _enforce(stdin_data: dict, contract: dict, step: str) -> None:
    role, mode, pipeline_id = _extract_agent_fields(stdin_data)
    result = contract_runtime.validate_required_call(
        contract, role, pipeline_id or None, mode or None, step,
    )
    if not result['ok'] and result['severity'] == 'fail':
        _emit_block(step, role, pipeline_id, result['errors'],
                    mode=mode, entry=result.get('entry'), contract=contract)
        sys.exit(2)


def _main() -> None:
    stdin_data = _parse_stdin()
    if not stdin_data or stdin_data.get('tool_name') != 'Agent':
        sys.exit(0)
    session_id, overnight_state = _resolve_session(stdin_data)

    if has_do_consent(stdin_data):
        sys.exit(0)

    # /allow bypass: main-agent-only
    if (not is_subagent_context(stdin_data)
            and match_sentinel_grant_for_tool(session_id, "Agent") is not None):
        sys.exit(0)

    if overnight_state is None:
        # Not an overnight session: no cycle contract governs it.
        sys.exit(0)
    contract = _allowed_calls(overnight_state)
    if contract is None:
        sys.exit(0)
    step = _current_step_label(stdin_data)
    if not step:
        # No checklist / no in-progress step — cannot enforce; fail open
        # rather than block all Agent calls.
        sys.exit(0)
    _enforce(stdin_data, contract, step)
    sys.exit(0)


if __name__ == '__main__':
    _main()
