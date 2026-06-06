#!/usr/bin/env python3
"""
PostToolUse:Agent Hook: Track subagent invocations in workflow bookmark.

Two execution paths:

Path A (contract present — /dev-overnight cycles):
    A cycle-contract.json file exists for the active session/cycle. The hook
    delegates to lib.contract_runtime for cycle-aware progression and marks
    the step done so downstream validators see the same bookmark shape.

Path B (contract absent — /dev / /redev cycles):
    No cycle-contract.json. The hook falls through to legacy bookkeeping:
    locate the in_progress canonical todo via array-index (not label),
    fresh-read the workflow bookmark, set
        bookmark.subagent_calls[str(ip_index)] = True
    and write back atomically. This unblocks pretool-todo-validate.py at
    line 238 which reads `state.get('subagent_calls', {}).get(str(i), False)`
    where `i` is the canonical enumerate-index.

iter1 fix (AC-WID5): the fall-through writer was previously keyed on the
step LABEL (the literal after "Step ", e.g., '6', '5a', '8'). The validator
keys on the array INDEX, so labels like '5a' or labels-after-inserts (Step 6
at array index 7 once Step 5a/5b/6.5 are inserted) caused a key mismatch and
the cycle would deadlock. Helper `_current_in_progress_index` returns the
0-indexed array position; we write `str(ip_index)` to match the validator.

Exit codes:
  0: Always (tracking only, never blocks).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.todo_canonical import run_todo_script

try:
    from lib import contract_runtime  # noqa: F401  (Path A optional dep)
    HAS_CONTRACT_RUNTIME = True
except Exception:
    HAS_CONTRACT_RUNTIME = False


# ---------------------------------------------------------------------------
# Stdin parsing
# ---------------------------------------------------------------------------

def _parse_stdin() -> tuple:
    """Parse PostToolUse stdin JSON. Returns (data, session_id, prompt)."""
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    sid = data.get('session_id', 'default')
    ti = data.get('tool_input', {}) or {}
    prompt = ti.get('prompt', '') if isinstance(ti, dict) else ''
    return data, sid, prompt


# ---------------------------------------------------------------------------
# Workflow bookmark loading
# ---------------------------------------------------------------------------

def _load_workflow_bookmark(session_id: str) -> tuple:
    """Load workflow bookmark. Returns (state_dict, path) or (None, path)."""
    project_dir = Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))
    path = project_dir / '.claude' / f'workflow-{session_id}.json'
    if not path.exists():
        return None, path
    try:
        return json.loads(path.read_text()), path
    except Exception:
        return None, path


# ---------------------------------------------------------------------------
# Step / index resolution
# ---------------------------------------------------------------------------

def _split_step_label(rest: str) -> str:
    """Return the prefix of `rest` up to the first label-terminator char."""
    for sep in (':', ' ', '\t'):
        if sep in rest:
            return rest.split(sep, 1)[0].strip()
    return rest.strip()


def _content_to_step(content: str) -> str:
    """Extract the step label (text after 'Step ') from a todo content."""
    if not isinstance(content, str):
        return ''
    if not content.startswith('Step '):
        return ''
    return _split_step_label(content[len('Step '):])


def _current_step_label(state: dict) -> str:
    """Return the LABEL of the in_progress todo (e.g. '6', '5a').

    Used by the contract-driven path (Path A) which keys validation on
    label form. The fall-through path (Path B) uses array index instead.
    """
    for item in state.get('last_todos') or []:
        if isinstance(item, dict) and item.get('status') == 'in_progress':
            return _content_to_step(item.get('content', ''))
    return ''


def _current_in_progress_index(state: dict) -> int | None:
    """Return the 0-indexed array position of the in_progress todo in last_todos.

    The validator at pretool-todo-validate.py around line 238 keys
    `subagent_calls` on the canonical enumerate-index string form, so this
    writer must conform to the same indexing scheme (NOT the step label).

    Multi-in_progress guard (cycle 20260519-211515 Item H, OBJ-5 BLOCKER
    resolution): if MORE THAN ONE step has status='in_progress' the bookmark
    is inconsistent — return None so callers fall through to the no-write
    branch. This prevents the typed-lookup window in Case A from anchoring
    on an ambiguous bookmark state, and prevents Case B legacy from
    arbitrarily picking the first of several in_progress steps.
    """
    last_todos = state.get('last_todos') or []
    found: int | None = None
    for idx, item in enumerate(last_todos):
        if isinstance(item, dict) and item.get('status') == 'in_progress':
            if found is not None:
                # Multi-in_progress bookmark inconsistency — refuse to anchor.
                return None
            found = idx
    return found


# ---------------------------------------------------------------------------
# Canonical step inspection (legacy fall-through gating)
# ---------------------------------------------------------------------------

def _step_has_subagent_call(canonical: list, step_index: int) -> bool:
    """Check if a canonical step has subagent_call metadata."""
    if step_index < 0 or step_index >= len(canonical):
        return False
    item = canonical[step_index]
    if not isinstance(item, dict):
        return False
    return item.get('subagent_call') is not None


def _find_earliest_unflipped_matching_step(
    canonical: list,
    state: dict,
    subagent_type: str,
    ip_index: int | None,
) -> int | None:
    """Bounded-window K=3 first-unflipped-match keyed on subagent_type.

    Cycle 20260519-211515 Item H (AC-H1, AC-H3b). Used by Case A in _main
    when stdin.tool_input.subagent_type is NON-EMPTY (parallel
    TodoWrite+Agent dispatch closes the bookmark-stale race).

    Case A is gated on a single valid in_progress anchor (OBJ-5 BLOCKER
    resolution): if ip_index is None — either no in_progress step exists,
    OR multi-in_progress returned None from _current_in_progress_index —
    return None immediately. There is NO `else: start = 0` fallback. The
    caller exits 0 with no write per AC-H3b sub-cases (3) and (4).

    Within the K=3 window canonical[max(0, ip_index):ip_index+3], return
    the earliest index whose canonical step has
    subagent_call.subagent_type matching `subagent_type` (case-insensitive)
    AND is not yet flipped in state.subagent_calls.

    Returns int (target index) or None (no anchor / no unflipped match).
    """
    if ip_index is None:
        return None
    if not isinstance(subagent_type, str) or not subagent_type:
        return None
    start = max(0, ip_index)
    end = min(len(canonical), start + 3)  # K=3 bounded window
    needle = subagent_type.lower()
    calls = state.get('subagent_calls') or {}
    if not isinstance(calls, dict):
        calls = {}
    for i in range(start, end):
        step = canonical[i] if i < len(canonical) else None
        if not isinstance(step, dict):
            continue
        call_meta = step.get('subagent_call')
        if call_meta is None:
            continue
        # Normalize: subagent_call may be a dict (single subagent) or a list
        # of dicts (multiple alternative subagents — supported by the
        # validator's _format_subagent_names at pretool-todo-validate.py:244-248).
        if isinstance(call_meta, dict):
            entries = [call_meta]
        elif isinstance(call_meta, list):
            entries = [e for e in call_meta if isinstance(e, dict)]
        else:
            continue
        if calls.get(str(i)):
            continue  # already flipped
        for entry in entries:
            cand_type = entry.get('subagent_type', '')
            if not isinstance(cand_type, str):
                continue
            if cand_type.lower() == needle:
                return i
    return None  # window exhausted, no unflipped match


def _get_expected_type(canonical: list, step_index: int) -> str:
    """Extract expected subagent_type from canonical step metadata."""
    if step_index < 0 or step_index >= len(canonical):
        return ''
    item = canonical[step_index]
    if not isinstance(item, dict):
        return ''
    call = item.get('subagent_call', {})
    if not isinstance(call, dict):
        return ''
    return call.get('subagent_type', '')


def _check_role_match(expected: str, prompt: str, ip_index: int) -> None:
    """Emit warning when Agent prompt does not match expected subagent type."""
    if not expected:
        return
    if expected.lower() in (prompt or '').lower():
        return
    sys.stderr.write(
        f'WARNING: Agent call on step {ip_index} expected '
        f'subagent_type="{expected}" but prompt does not match. '
        f'Marking call anyway for backward compatibility.\n'
    )


# ---------------------------------------------------------------------------
# Bookmark writers
# ---------------------------------------------------------------------------

def _record_subagent_call_legacy(bm_path: Path, key: str) -> None:
    """Fresh-read the bookmark, set subagent_calls[key]=True, write back.

    Path B writer (no contract present). `key` MUST be the validator-side
    string form, i.e. str(array_index). Iter1 fix replaced previous
    label-form key with index-form key.
    """
    try:
        fresh = json.loads(bm_path.read_text())
        calls = fresh.get('subagent_calls', {})
        if not isinstance(calls, dict):
            calls = {}
        calls[str(key)] = True
        fresh['subagent_calls'] = calls
        bm_path.write_text(json.dumps(fresh))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Contract path (Path A) — /dev-overnight
# ---------------------------------------------------------------------------

def _cycle_id_from_state(state: dict) -> int:
    """Pull the active overnight cycle id from bookmark state, default 0."""
    for key in ('cycle', 'cycle_id', 'active_cycle'):
        v = state.get(key)
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)
    return 0


def _try_load_contract(session_id: str, state: dict):
    """Attempt to load the active overnight contract; return None on miss."""
    if not HAS_CONTRACT_RUNTIME:
        return None
    try:
        cycle_id = _cycle_id_from_state(state)
        return contract_runtime.load_contract(session_id, cycle_id)
    except Exception:
        return None


def _contract_bookmark_path(session_id: str, cycle_id: int) -> Path:
    """T2.3: pretool-subagent-enforce wrote /tmp/contract-bookmark-<sid>-<cycle>.json."""
    return Path(f'/tmp/contract-bookmark-{session_id}-{cycle_id}.json')


def _artifact_status_path(session_id: str, cycle_id: int) -> Path:
    """T2.3: posttool-overnight-file-check (T3.2) writes per-call sidecar."""
    return Path(f'/tmp/artifact-status-{session_id}-{cycle_id}.json')


def _read_json(path: Path) -> dict | None:
    """Best-effort JSON read; None on any failure."""
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None


def _matched_entry_for_step(session_id: str, cycle_id: int, step: str) -> dict | None:
    """T2.3: load the pretool-authored matched_entry for this step."""
    bm = _read_json(_contract_bookmark_path(session_id, cycle_id))
    if not isinstance(bm, dict):
        return None
    payload = bm.get(step)
    if not isinstance(payload, dict):
        return None
    matched = payload.get('matched_entry')
    return matched if isinstance(matched, dict) else None


def _emit_pending(step: str, ip_index: int, reasons: list) -> None:
    """T2.3: stderr structured contract-pending diagnostic; never blocks."""
    sys.stderr.write(
        f'CONTRACT PENDING (posttool-subagent-track): step={step} '
        f'index={ip_index} not marked done.\n  reasons:\n'
    )
    for r in reasons:
        sys.stderr.write(f'    - {r}\n')


def _validate_via_schema(record: dict, schema_name: str, path_str: str) -> tuple[bool, list]:
    """T2.3: run validate_artifact and translate Result into (ok, reasons)."""
    res = contract_runtime.validate_artifact(record, schema_name)
    if res.get('severity') == 'pass':
        return True, []
    errs = res.get('errors') or []
    msgs = [f"schema '{schema_name}' validation failed: {e}" for e in errs]
    return False, msgs or [f"schema '{schema_name}' validation failed (no detail)"]


def _validate_artifact_for_entry(matched: dict) -> tuple[bool, list]:
    """T2.3: confirm expected_output_path exists + schema validates."""
    path_str = matched.get('expected_output_path')
    if not path_str:
        return True, []  # entry has no artifact gating
    p = Path(path_str)
    if not p.exists():
        return False, [f"expected_output_path missing: {path_str}"]
    schema_name = matched.get('schema_name')
    if not schema_name:
        return True, []  # existence-only is sufficient
    record = _read_json(p)
    if record is None:
        return False, [f"expected_output_path unreadable as JSON: {path_str}"]
    return _validate_via_schema(record, schema_name, path_str)


def _consult_artifact_status_sidecar(session_id: str, cycle_id: int) -> tuple[bool, list]:
    """T2.3: if T3.2 sidecar present, honor its schema_status."""
    sidecar = _read_json(_artifact_status_path(session_id, cycle_id))
    if not isinstance(sidecar, dict):
        return True, []
    status = sidecar.get('schema_status')
    if status in ('pass', 'unchecked', None):
        return True, []
    errs = sidecar.get('errors') or []
    base = f"artifact-status sidecar reports schema_status='{status}'"
    return False, [f"{base}: {e}" for e in errs] or [base]


def _mark_or_pend(bm_path: Path, ip_index: int | None, step: str,
                  ok: bool, reasons: list, session_id: str = '',
                  cycle_id: int = 0, matched: dict | None = None) -> None:
    """Write the bookmark mark only through atomic contract reconciliation."""
    if ok and ip_index is not None:
        try:
            result = contract_runtime.reconcile_accepted_artifact(
                session_id, cycle_id, bm_path, ip_index, matched or {},
            )
        except Exception as exc:
            _emit_pending(step, ip_index, [f'atomic reconciliation failed: {exc}'])
            return
        if result.get('ok'):
            return
        _emit_pending(step, ip_index, [str(result.get('reason') or 'atomic reconciliation failed')])
        return
    if ip_index is not None:
        _emit_pending(step, ip_index, reasons)


def _enforce(stdin_data: dict, contract: dict, state: dict,
             bm_path: Path, step: str) -> None:
    """T2.3: contract-driven path. Marks step done IFF bookmark + artifact valid."""
    session_id = stdin_data.get('session_id', 'default')
    cycle_id = _cycle_id_from_state(state)
    ip_index = _current_in_progress_index(state)
    matched = _matched_entry_for_step(session_id, cycle_id, step)
    if not isinstance(matched, dict):
        _mark_or_pend(bm_path, ip_index, step, False,
                      ['pretool contract-bookmark missing matched_entry'])
        return
    a_ok, a_why = _validate_artifact_for_entry(matched)
    s_ok, s_why = _consult_artifact_status_sidecar(session_id, cycle_id)
    _mark_or_pend(
        bm_path, ip_index, step, a_ok and s_ok, a_why + s_why,
        session_id, cycle_id, matched,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _resolve_base_context(session_id: str):
    """Load state + canonical + ip_index without gating on subagent_call metadata.

    Cycle 20260519-211515 Item H: replaces the previous
    `_resolve_context` gate-and-bail pattern for the legacy path. Case A
    (subagent_type non-empty, typed lookup) MUST NOT bail when the current
    in_progress step lacks subagent_call metadata — that is exactly the
    parallel-dispatch race shape where the bookmark is stale by one step.

    Returns tuple(state, last_todos, canonical, ip_index, bm_path) on
    success (bm exists, last_todos non-empty). ip_index may be None when
    no in_progress step exists OR when multiple in_progress steps were
    detected by the guarded _current_in_progress_index. Returns None when
    bookmark is unreadable / shape is invalid.
    """
    state, bm_path = _load_workflow_bookmark(session_id)
    if state is None:
        return None
    cmd_name = state.get('command', '')
    last_todos = state.get('last_todos')
    if not cmd_name or not last_todos:
        return None
    canonical = run_todo_script(cmd_name, state.get('arguments', '')) or []
    ip_index = _current_in_progress_index(state)
    return state, last_todos, canonical, ip_index, bm_path


# NOTE: `_resolve_context` removed by cycle 20260519-211515 close cleanup
# (cleanliness-inspector finding: dead function — H restructure inlined the
# contract gate into `_main`, leaving this helper without callers).
def _emit_legacy_tracked(last_todos: list, ip_index: int) -> None:
    """Print the SUBAGENT TRACKED line for the legacy fall-through path."""
    item = last_todos[ip_index] if ip_index < len(last_todos) else {}
    content = item.get('content', '?') if isinstance(item, dict) else '?'
    print(f'SUBAGENT TRACKED: Step {ip_index} ("{content}") '
          f'subagent call recorded.')


def _extract_subagent_type(stdin_data: dict) -> str:
    """Extract and normalize stdin.tool_input.subagent_type.

    Returns lower-cased, stripped string; empty string if absent / wrong type.
    """
    ti = stdin_data.get('tool_input') if isinstance(stdin_data, dict) else None
    if not isinstance(ti, dict):
        return ''
    val = ti.get('subagent_type', '')
    if not isinstance(val, str):
        return ''
    return val.strip().lower()


def _main() -> None:
    stdin_data, session_id, agent_prompt = _parse_stdin()

    # Load base context once (state, canonical, ip_index, bm_path).
    base = _resolve_base_context(session_id)
    if base is None:
        sys.exit(0)
    state, last_todos, canonical, ip_index, bm_path = base

    # Contract-presence check FIRST (cycle 20260519-211515 codex Finding 1):
    # if a /dev-overnight cycle-contract is active, the legacy Case A/B paths
    # MUST NOT run — bookmark writes go strictly through the contract's
    # _enforce path (artifact validation + atomic reconciliation). Falling
    # through to a legacy write would bypass artifact validation.
    contract = _try_load_contract(session_id, state)
    if contract is not None:
        # Path A: strict gate (single in_progress + subagent_call metadata).
        if ip_index is None:
            sys.exit(0)
        if not _step_has_subagent_call(canonical, ip_index):
            sys.exit(0)
        _check_role_match(_get_expected_type(canonical, ip_index),
                          agent_prompt, ip_index)
        step = _current_step_label(state)
        _enforce(stdin_data, contract, state, bm_path, step)
        sys.exit(0)

    # Contract absent — Path B: legacy bookkeeping. Case A (typed lookup
    # via subagent_type) takes precedence over Case B (legacy in_progress
    # inference). The two are mutually exclusive; Case A MUST NOT fall
    # through to Case B on a typed miss (AC-H3b mandate).
    subagent_type = _extract_subagent_type(stdin_data)
    if subagent_type:
        # Case A: subagent_type non-empty. Gated on single valid in_progress
        # anchor. Helper returns None when ip_index is None (no anchor / multi)
        # OR when no unflipped matching step in K=3 window — all AC-H3b cases.
        target = _find_earliest_unflipped_matching_step(
            canonical, state, subagent_type, ip_index,
        )
        if target is not None and isinstance(target, int):
            _check_role_match(_get_expected_type(canonical, target),
                              agent_prompt, target)
            _record_subagent_call_legacy(bm_path, str(target))
            _emit_legacy_tracked(last_todos, target)
        # DO NOT fall through to Case B when subagent_type is non-empty
        # and typed lookup misses (AC-H3b sub-case 2 mandate).
        sys.exit(0)

    # Case B: subagent_type absent. Existing legacy chain: requires a
    # single valid in_progress anchor AND that step has subagent_call.
    if ip_index is None:
        sys.exit(0)  # AC-H3b sub-case 1: legacy None
    if not _step_has_subagent_call(canonical, ip_index):
        sys.exit(0)  # AC-H3b sub-case 1: in_progress lacks subagent_call
    _check_role_match(_get_expected_type(canonical, ip_index),
                      agent_prompt, ip_index)
    if isinstance(ip_index, int):
        _record_subagent_call_legacy(bm_path, str(ip_index))
        _emit_legacy_tracked(last_todos, ip_index)
    sys.exit(0)


if __name__ == '__main__':
    _main()
