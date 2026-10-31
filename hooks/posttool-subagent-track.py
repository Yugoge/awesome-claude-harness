#!/usr/bin/env python3
"""
PostToolUse:Agent Hook: Track subagent invocations in workflow bookmark.

Bookkeeping (every workflow): locate the in_progress canonical todo via
array-index (not label) and set
    bookmark.subagent_calls[str(ip_index)] = True
in the workflow bookmark as lib.todo_canonical.write_bookmark, its one writer,
reads it at the write. This unblocks pretool-todo-validate.py at line 238 which
reads `state.get('subagent_calls', {}).get(str(i), False)` where `i` is the
canonical enumerate-index. Whether the dispatch produced its artifact is
decided by posttool-overnight-file-check.py at the same PostToolUse (G3) and
by the producer's own stop (G2), not here.

PM TRIAGE handler (/dev-overnight): when the returned Agent call is the PM
TRIAGE step's dispatch, write the cycle's contract,
`<working root>/docs/dev/overnight/<sid>/cycle-<N>/cycle-contract.json`
(lib.contract_runtime.contract_path, N = lib.overnight.cycle_index). It
renders the dispatching steps after PM TRIAGE from scripts/todo/dev-overnight.py
_STEPS: once per pipeline the triage report creates (counted by
scripts/build-pipelines-from-triage.py, the Step-6 builder), except a step
whose dispatch carries a mode (PM RETRO), which runs once per cycle. This hook
is the contract's only writer; nothing edits a contract after it is written.

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
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.todo_canonical import run_todo_script, write_bookmark
from lib import contract_runtime
from lib import overnight


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
# Bookmark update
# ---------------------------------------------------------------------------

def _record_subagent_call_legacy(bm_path: Path, key: str) -> None:
    """Set subagent_calls[key]=True in the bookmark as write_bookmark reads it.

    The bookkeeping update. `key` MUST be the validator-side
    string form, i.e. str(array_index). Iter1 fix replaced previous
    label-form key with index-form key.
    """
    def _mark(text):
        if text is None:
            return None  # no bookmark to record the call in
        fresh = json.loads(text)
        calls = fresh.get('subagent_calls', {})
        if not isinstance(calls, dict):
            calls = {}
        calls[str(key)] = True
        fresh['subagent_calls'] = calls
        return json.dumps(fresh)

    try:
        write_bookmark(bm_path, _mark)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# PM TRIAGE handler — the cycle contract's one writer (/dev-overnight)
# ---------------------------------------------------------------------------

_BUILD_PIPELINES = Path(__file__).resolve().parent.parent / 'scripts' / 'build-pipelines-from-triage.py'


def _is_triage_dispatch(stdin_data: dict, steps: list) -> bool:
    """True iff the returned Agent call is the PM TRIAGE step's dispatch."""
    triage = contract_runtime.triage_call(steps)
    ti = stdin_data.get('tool_input') if isinstance(stdin_data, dict) else None
    if not triage or not isinstance(ti, dict):
        return False
    role = ti.get('subagent_type')
    return (isinstance(role, str) and role.strip().lower() == triage.get('subagent_type')
            and contract_runtime.detect_mode(ti.get('prompt', '')) == triage.get('mode'))


def _pipeline_count(state: dict, cycle_id: int) -> int | None:
    """How many pipelines this cycle's triage report creates, counted by the
    Step-6 builder itself so the count and the pipelines cannot disagree."""
    triage = overnight.session_dir(state) / f'triage-report-cycle{cycle_id}.json'
    if not triage.is_file():
        return None
    try:
        result = subprocess.run(
            [sys.executable, str(_BUILD_PIPELINES), str(triage), '/dev/stdin',
             f'cycle{cycle_id}', str(state.get('session_id'))],
            input=json.dumps(state.get('addressed_issues') or []),
            capture_output=True, text=True, timeout=30,
        )
        pipelines = json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return len(pipelines) if isinstance(pipelines, list) else None


def _write_cycle_contract(stdin_data: dict, session_id: str) -> None:
    """Render the cycle contract when PM TRIAGE returns; otherwise do nothing."""
    state = overnight.session_state(session_id)
    if state is None:
        return
    steps = contract_runtime.overnight_steps()
    if not _is_triage_dispatch(stdin_data, steps):
        return
    cycle_id = overnight.cycle_index(state)
    count = _pipeline_count(state, cycle_id)
    if count is None:
        sys.stderr.write(
            f'CYCLE CONTRACT NOT WRITTEN: cycle {cycle_id} has no readable triage '
            'report; the next PM TRIAGE dispatch writes it.\n')
        return
    calls = []
    for label, call in contract_runtime.post_triage_steps(steps):
        copies = 1 if call.get('mode') else count
        calls += [contract_runtime.call_entry(label, call) for _ in range(copies)]
    contract = {
        'schema_version': 1,
        'session_id': session_id,
        'cycle_id': cycle_id,
        'created_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'required_calls': calls,
    }
    path = contract_runtime.contract_path(state, cycle_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
        tmp.write_text(json.dumps(contract, indent=2) + '\n', encoding='utf-8')
        os.replace(tmp, path)
    except OSError as exc:
        sys.stderr.write(f'CYCLE CONTRACT NOT WRITTEN: {path}: {exc}\n')
        return
    print(f'CYCLE CONTRACT: cycle {cycle_id}, {count} pipeline(s), '
          f'{len(calls)} required call(s): {path}')


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
    _write_cycle_contract(stdin_data, session_id)

    # Load base context once (state, canonical, ip_index, bm_path).
    base = _resolve_base_context(session_id)
    if base is None:
        sys.exit(0)
    state, last_todos, canonical, ip_index, bm_path = base

    # Case A (typed lookup via subagent_type) takes precedence over Case B
    # (legacy in_progress inference). The two are mutually exclusive; Case A MUST NOT fall
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
