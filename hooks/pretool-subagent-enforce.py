#!/usr/bin/env python3
"""
PreToolUse:Agent Hook — Contract-driven role/pipeline enforcement.

Replaces the legacy 'any Agent call satisfies the current step' behavior
with a strict cycle-contract.json lookup. For overnight sessions:

  1. Resolve the active cycle-contract.json (via lib.contract_runtime).
  2. Derive the current step from the workflow bookmark's todo state.
  3. Look up the required_calls entry whose ``step`` matches.
  4. Validate the about-to-fire Agent's role / pipeline_id / mode against
     that entry. On mismatch, exit 2 with a structured stderr message.
  5. On match, write a bookmark file
     ``/tmp/contract-bookmark-<sid>-<cycle>.json`` so
     ``posttool-subagent-track.py`` can reconcile what it sees against
     what was authorized.

HARD CUTOVER: when ``cycle-contract.json`` is absent for the session,
exit 0 silently (legacy /spec, /dev single-cycle sessions are not
overnight workflows and produce no contract).

Exit codes:
  0 — Allow (no contract present, or call matches contract).
  2 — Reject (role/pipeline_id mismatch against contract).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib import contract_runtime  # noqa: E402
from lib.subagent import is_subagent_context  # noqa: E402
from lib.allowlist import read_grant          # noqa: E402


def _parse_stdin() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def _has_consent(session_id: str) -> bool:
    try:
        flag = Path(f'/tmp/claude-orchestrator-consent-{session_id}.flag')
        return flag.exists() and flag.read_text().strip() == 'true'
    except Exception:
        return False


def _load_bookmark(session_id: str) -> dict | None:
    project_dir = Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))
    path = project_dir / '.claude' / f'workflow-{session_id}.json'
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None


def _content_to_step(content: str) -> str:
    """Map a todo content string ('Step 2a: ...') to a bare label ('2a')."""
    if content.startswith('Step '):
        head = content.split(':', 1)[0]
        return head.replace('Step ', '').strip()
    return content


def _current_step_label(state: dict) -> str | None:
    """Extract the current in-progress step label from the bookmark."""
    last_todos = state.get('last_todos') or []
    for item in last_todos:
        if item.get('status') == 'in_progress':
            return _content_to_step(item.get('content', ''))
    return None


def _cycle_id_from_state(state: dict) -> int:
    """Best-effort cycle id resolution. Defaults to 1 for cold sessions."""
    val = state.get('cycle_id') or state.get('cycle_count')
    try:
        return int(val) if val else 1
    except (TypeError, ValueError):
        return 1


def _resolve_session_and_cycle(stdin_data: dict) -> tuple[str, int, dict | None]:
    session_id = stdin_data.get('session_id', 'default')
    state = _load_bookmark(session_id)
    cycle_id = _cycle_id_from_state(state) if state else 1
    return session_id, cycle_id, state


def _detect_mode(prompt: str) -> str:
    """Identify a mode keyword embedded in the Agent prompt, if any."""
    for keyword in ('PLAN', 'TRIAGE', 'RETRO', 'DESIGN_MODE', 'AUDIT_MODE', 'UI_MODE'):
        if keyword in prompt:
            return keyword
    return ''


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


def _extract_agent_fields(stdin_data: dict) -> tuple[str, str, str, str]:
    """Return (role, mode, pipeline_id, prompt_preview) extracted from Agent call."""
    ti = stdin_data.get('tool_input', {}) or {}
    role = (ti.get('subagent_type') or '').strip().lower()
    prompt = ti.get('prompt', '') if isinstance(ti, dict) else ''
    mode = _detect_mode(prompt)
    pipeline_id = _resolve_pipeline_id(ti, prompt)
    preview = prompt[:200].replace('\n', ' ')
    return role, mode, pipeline_id, preview


def _bookmark_path(session_id: str, cycle_id: int) -> Path:
    return Path(f'/tmp/contract-bookmark-{session_id}-{cycle_id}.json')


def _write_bookmark(session_id: str, cycle_id: int, step: str, payload: dict) -> None:
    """Persist authorization context for posttool-subagent-track to read."""
    path = _bookmark_path(session_id, cycle_id)
    try:
        existing = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    except Exception:
        existing = {}
    existing[step] = payload
    try:
        path.write_text(json.dumps(existing, indent=2), encoding='utf-8')
    except OSError:
        pass


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


def _valid_contracted_step_ids(contract) -> str:
    """Render the contract's valid step ids (display wrapper over the data helper).

    Joins the deduped, order-preserved id list with ', ', rendering '<none>'
    when none remain. Presentation only — control flow uses the list helper.
    """
    ordered = _contracted_step_id_list(contract)
    return ', '.join(ordered) if ordered else '<none>'


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
    named '<none>' is Case A (stale bookmark), not Case C (incomplete).
    """
    if not isinstance(contract, dict):
        return (
            "Case M (contract malformed/non-dict): the loaded cycle-contract is "
            "not a JSON object, so it has no usable required_calls.",
            "do not retry by re-bookmarking; re-publish the contract / request "
            "orchestrator escalation.",
        )
    if not has_step_ids and entry is None:
        return (
            "Case C (incomplete contract): the contract is present but has no "
            "usable contracted steps.",
            "do not retry by re-bookmarking; re-publish the contract / request "
            "orchestrator escalation.",
        )
    if entry is None:
        return (
            f"Case A (stale bookmark): the resolved step '{step}' has no "
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
    valid_ids = _valid_contracted_step_ids(contract)
    diagnosis, action = _diagnose_block(contract, valid_ids, entry, step)
    sys.stderr.write(
        '\nCONTRACT BLOCK (pretool-subagent-enforce):\n'
        f'  step={step} source=current in-progress Todo bookmark\n'
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


def _entry_identity(entry: dict | None) -> dict:
    """T2.3: distill matched required_call entry to identity fields for bookmarking."""
    if not isinstance(entry, dict):
        return {}
    return {
        'step': entry.get('step'),
        'role': entry.get('role'),
        'pipeline_id': entry.get('pipeline_id'),
        'mode': entry.get('mode'),
        'expected_output_path': entry.get('expected_output_path'),
        'schema_name': entry.get('schema_name') or entry.get('expected_schema'),
    }


def _enforce(stdin_data: dict, contract: dict, step: str) -> None:
    session_id, cycle_id, _state = _resolve_session_and_cycle(stdin_data)
    role, mode, pipeline_id, preview = _extract_agent_fields(stdin_data)
    result = contract_runtime.validate_required_call(
        contract, role, pipeline_id or None, mode or None, step,
    )
    if not result['ok'] and result['severity'] == 'fail':
        _emit_block(step, role, pipeline_id, result['errors'],
                    mode=mode, entry=result.get('entry'), contract=contract)
        sys.exit(2)
    _write_bookmark(session_id, cycle_id, step, {
        'role': role,
        'mode': mode,
        'pipeline_id': pipeline_id,
        'agent_id': stdin_data.get('agent_id', ''),
        'ts': time.time(),
        'prompt_preview': preview,
        'severity': result['severity'],
        # T2.3: persist matched required_call identity so posttool-subagent-track
        # can validate the produced artifact against the authorized contract entry.
        'matched_entry': _entry_identity(result.get('entry')),
    })


def _main() -> None:
    stdin_data = _parse_stdin()
    if not stdin_data or stdin_data.get('tool_name') != 'Agent':
        sys.exit(0)
    session_id, cycle_id, state = _resolve_session_and_cycle(stdin_data)

    # /do bypass: main-agent-only
    if not is_subagent_context(stdin_data) and _has_consent(session_id):
        sys.exit(0)

    # /allow bypass: main-agent-only
    if not is_subagent_context(stdin_data) and read_grant("Agent", session_id):
        sys.exit(0)

    contract = contract_runtime.load_contract(session_id, cycle_id)
    if contract is None:
        # Hard cutover: legacy session — silent passthrough.
        sys.exit(0)
    step = _current_step_label(state) if state else None
    if not step:
        # No bookmark / no in-progress step — cannot enforce; fail open
        # rather than block all Agent calls.
        sys.exit(0)
    _enforce(stdin_data, contract, step)
    sys.exit(0)


if __name__ == '__main__':
    _main()
