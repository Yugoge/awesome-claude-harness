#!/usr/bin/env python3
"""
PreToolUse Hook: Require TodoWrite/TodoRead acknowledgment before other tools.

If an active workflow exists (bookmark present) and the agent has NOT yet
called TodoWrite or TodoRead (todo_acknowledged == false in bookmark), block
any other tool.

This prevents agents from ignoring the workflow checklist while still using
other tools freely.

Logic:
  1. If tool is TodoWrite or TodoRead → set todo_acknowledged=true → allow
  2. No bookmark → allow (no active workflow)
  3. todo_acknowledged == true → allow
  4. Otherwise → block

Exit codes:
  0: Allow tool use
  2: Block tool use (must call TodoWrite/TodoRead first)
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

CODEX_PLAN_TOOLS = {'update_plan', 'UpdatePlan', 'functions.update_plan'}
CODEX_RUNTIME_ENV = 'CLAUDE_COMPAT_RUNTIME'


def official_todos_path(session_id: str) -> Path:
    return Path.home() / '.claude' / 'todos' / f'{session_id}-agent-{session_id}.json'


def run_canonical_todos(cmd_name: str, project_dir: Path, prompt: str = '') -> list:
    """Run the canonical todo script and return the full step list.

    prompt is forwarded as CLAUDE_TODO_PROMPT so argument-aware scripts
    (e.g. close.py --force path) return the correct step-count variant.
    """
    todo_script = project_dir / 'scripts' / 'todo' / f'{cmd_name}.py'
    if not todo_script.exists():
        global_todo = Path.home() / '.claude' / 'scripts' / 'todo' / f'{cmd_name}.py'
        if global_todo.exists():
            todo_script = global_todo
        else:
            return []
    env = {**os.environ}
    if prompt:
        env['CLAUDE_TODO_PROMPT'] = prompt
    result = subprocess.run(
        ['python3', str(todo_script)],
        capture_output=True, text=True, cwd=str(project_dir),
        env=env,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        return json.loads(result.stdout)
    except Exception:
        return []


def build_next_todowrite_call(session_id: str, cmd_name: str = '', project_dir: Path = None) -> str:
    """Return ready-to-use JSON for the next TodoWrite call.

    Primary source: todos file (always clean — tracker guards against bad-count writes).
    Fallback: canonical script (when file doesn't exist, e.g. first-time count_mismatch).
    """
    try:
        todos_file = official_todos_path(session_id)
        if todos_file.exists():
            todos = json.loads(todos_file.read_text())
        elif cmd_name and project_dir:
            # File missing (e.g. first TodoWrite had wrong count, tracker skipped write)
            # Fall back to canonical so agent still gets a usable hint.
            # Forward stored --force/etc. arguments so the hint matches the
            # argument-aware canonical variant (e.g. close.py 2-step forced list).
            _args = ''
            try:
                _bm = project_dir / '.claude' / f'workflow-{session_id}.json'
                _args = json.loads(_bm.read_text()).get('arguments', '')
            except Exception:
                _args = ''
            todos = run_canonical_todos(cmd_name, project_dir, _args)
            if not todos:
                return ''
        else:
            return ''

        result = [t.copy() for t in todos]
        has_inprogress = any(t.get('status') == 'in_progress' for t in result)
        if not has_inprogress:
            for t in result:
                if t.get('status') == 'pending':
                    t['status'] = 'in_progress'
                    break
        return json.dumps(result, ensure_ascii=False, separators=(',', ': '))
    except Exception:
        return ''


def build_sequence_fix_call(last_todos: list) -> str:
    """For sequence violations: compute the correct next state from last_todos.

    Finds the in_progress step in last_todos (the pre-violation state), marks it
    completed, and marks the next pending step as in_progress. This gives the agent
    a valid, non-violating TodoWrite to submit.
    """
    if not last_todos:
        return ''
    try:
        result = [t.copy() for t in last_todos]
        in_progress_idx = next(
            (i for i, t in enumerate(result) if t.get('status') == 'in_progress'), None
        )
        if in_progress_idx is not None:
            result[in_progress_idx]['status'] = 'completed'
            for t in result[in_progress_idx + 1:]:
                if t.get('status') == 'pending':
                    t['status'] = 'in_progress'
                    break
        else:
            for t in result:
                if t.get('status') == 'pending':
                    t['status'] = 'in_progress'
                    break
        return json.dumps(result, ensure_ascii=False, separators=(',', ': '))
    except Exception:
        return ''


def is_codex_runtime(data: dict) -> bool:
    """Return true only for hooks invoked through the Codex compatibility shim."""
    if os.environ.get(CODEX_RUNTIME_ENV, '').lower() == 'codex':
        return True
    runtime = str(data.get('runtime') or data.get('client') or '').lower()
    return runtime == 'codex'


def normalize_step_text(value: str) -> str:
    value = re.sub(r'\s+', ' ', value or '').strip().lower()
    value = re.sub(r'^(?:[-*]\s*)?(?:\[[ x-]\]\s*)?', '', value)
    value = re.sub(r'^(?:step\s*)?\d+[a-z]?\s*[:.)-]\s*', '', value)
    return value


def codex_plan_matches_canonical(plan: list, canonical: list) -> bool:
    if not canonical or len(plan) != len(canonical):
        return False
    for item, expected in zip(plan, canonical):
        if not isinstance(item, dict):
            return False
        status = item.get('status', 'pending')
        if status not in {'pending', 'in_progress', 'completed'}:
            return False
        step_text = item.get('step') or item.get('content') or item.get('title') or ''
        actual = normalize_step_text(str(step_text))
        expected_texts = {
            normalize_step_text(str(expected.get('content', ''))),
            normalize_step_text(str(expected.get('activeForm', ''))),
        }
        if actual not in expected_texts:
            return False
    completed = sum(1 for item in plan if item.get('status') == 'completed')
    in_progress = [idx for idx, item in enumerate(plan) if item.get('status') == 'in_progress']
    return completed == 0 and (not in_progress or in_progress == [0])


def codex_plan_to_todos(plan: list, canonical: list) -> tuple[list, list]:
    """Convert a Codex update_plan payload to canonical TodoWrite-shaped todos."""
    violations = []
    todos = []
    if not canonical:
        return [], ['Canonical workflow definition is unavailable']
    if not isinstance(plan, list):
        return [], ['Codex plan payload is not a list']
    if len(plan) != len(canonical):
        return [], [f'Expected {len(canonical)} steps, got {len(plan)}']
    for idx, (item, expected) in enumerate(zip(plan, canonical)):
        if not isinstance(item, dict):
            violations.append(f'Step {idx}: plan item is not an object')
            continue
        status = item.get('status', 'pending')
        if status not in {'pending', 'in_progress', 'completed'}:
            violations.append(f'Step {idx}: invalid status "{status}"')
        step_text = item.get('step') or item.get('content') or item.get('title') or ''
        actual = normalize_step_text(str(step_text))
        expected_texts = {
            normalize_step_text(str(expected.get('content', ''))),
            normalize_step_text(str(expected.get('activeForm', ''))),
        }
        if actual not in expected_texts:
            violations.append(
                f'Step {idx}: content does not match canonical '
                f'("{step_text}" != "{expected.get("content", "")}")'
            )
        todo_item = expected.copy()
        todo_item['status'] = status
        todos.append(todo_item)
    return todos, violations


def _completed_indices(todos: list) -> set:
    return {i for i, todo in enumerate(todos) if todo.get('status') == 'completed'}


def _in_progress_indices(todos: list) -> list:
    return [i for i, todo in enumerate(todos) if todo.get('status') == 'in_progress']


def validate_initial_codex_todos(new_todos: list) -> list:
    """First Codex plan call must initialize, not skip into later workflow steps."""
    violations = []
    completed = sorted(_completed_indices(new_todos))
    in_progress = _in_progress_indices(new_todos)
    if completed:
        violations.append(
            'Initial Codex update_plan cannot contain completed steps: '
            + ', '.join(str(i) for i in completed)
        )
    if len(in_progress) > 1:
        violations.append(f'Initial Codex update_plan has {len(in_progress)} in_progress steps')
    if in_progress and in_progress != [0]:
        violations.append(f'Initial in_progress must be Step 0, not Step {in_progress[0]}')
    return violations


def validate_codex_transition(state: dict, old_todos: list, new_todos: list) -> list:
    """Mirror TodoWrite sequence rules for Codex update_plan payloads."""
    violations = []
    if len(old_todos) != len(new_todos):
        violations.append(f'Step count changed from {len(old_todos)} to {len(new_todos)}')
        return violations

    old_completed = _completed_indices(old_todos)
    new_completed = _completed_indices(new_todos)
    newly_completed = new_completed - old_completed
    if len(newly_completed) > 1:
        violations.append(
            'Completed more than one step in one update: '
            + ', '.join(str(i) for i in sorted(newly_completed))
        )
    for idx in sorted(newly_completed):
        if old_todos[idx].get('status') == 'pending':
            violations.append(f'Step {idx}: pending -> completed without in_progress')

    in_progress = _in_progress_indices(new_todos)
    if len(in_progress) > 1:
        violations.append(
            'Multiple in_progress steps: ' + ', '.join(str(i) for i in in_progress)
        )

    for idx, (old, new) in enumerate(zip(old_todos, new_todos)):
        if old.get('status') != 'pending' or new.get('status') != 'in_progress':
            continue
        for prev_idx in range(idx):
            if new_todos[prev_idx].get('status') != 'completed':
                violations.append(
                    f'Step {idx}: cannot start before Step {prev_idx} is completed'
                )
                break

    for idx, (old, new) in enumerate(zip(old_todos, new_todos)):
        if old.get('status') != 'in_progress' or new.get('status') != 'completed':
            continue
        subagent_call = new.get('subagent_call')
        if subagent_call and not state.get('subagent_calls', {}).get(str(idx), False):
            violations.append(f'Step {idx}: subagent step completed before required subagent call')
    return violations


def emit_codex_plan_block(cmd_name: str, violations: list, last_todos: list) -> None:
    numbered = '\n'.join(f'  [{idx + 1}] {value}' for idx, value in enumerate(violations))
    next_json = build_sequence_fix_call(last_todos) if last_todos else ''
    plan_hint = codex_plan_hint(next_json) if next_json else ''
    hint = (
        '\nNext valid Codex update_plan payload:\n' + plan_hint + '\n'
        if plan_hint else ''
    )
    sys.stderr.write(
        f'\nBLOCKED Codex update_plan for /{cmd_name}:\n'
        + numbered
        + '\n\nRULES: (1) one completion per update '
        '(2) must pass through in_progress '
        '(3) one in_progress at a time '
        '(4) no step skipping '
        '(5) required subagent steps need matching subagent evidence.\n'
        + hint
    )
    sys.exit(2)


def persist_codex_initialization(
    session_id: str,
    bookmark_path: Path,
    state: dict,
    todos: list,
    implicit: bool,
) -> bool:
    try:
        todos_file = official_todos_path(session_id)
        todos_file.parent.mkdir(parents=True, exist_ok=True)
        todos_file.write_text(json.dumps(todos, ensure_ascii=False))
        state['todo_acknowledged'] = True
        state['last_todos'] = todos
        state['codex_plan_acknowledged'] = True
        if implicit:
            state['codex_plan_acknowledged_implicit'] = True
        state.pop('lock_reason', None)
        bookmark_path.write_text(json.dumps(state, ensure_ascii=False))
    except Exception:
        return False
    return True


def canonical_initial_todos(canonical: list) -> list:
    """Return the canonical first-call todo state for Codex plan bootstrap.

    Codex update_plan is not consistently exposed to legacy PreToolUse hooks.
    When the compatibility runtime is Codex and the workflow is still in the
    initial not-started state, the next hook-visible tool may be the first chance
    to persist checklist state. Store the canonical list with Step 0 in progress
    so downstream native hooks see the same shape as a valid first TodoWrite.
    """
    todos = []
    for idx, expected in enumerate(canonical):
        todo_item = expected.copy()
        todo_item['status'] = 'in_progress' if idx == 0 else 'pending'
        todos.append(todo_item)
    return todos


def codex_plan_hint(todo_json: str) -> str:
    try:
        todos = json.loads(todo_json)
        plan = [
            {
                'step': item.get('content', ''),
                'status': item.get('status', 'pending'),
            }
            for item in todos
        ]
        return json.dumps(plan, ensure_ascii=False, separators=(',', ': '))
    except Exception:
        return ''


def acknowledge_codex_plan(data: dict, session_id: str, bookmark_path: Path, project_dir: Path) -> bool:
    """Accept a Codex-native plan as the TodoWrite equivalent.

    This path is gated behind CLAUDE_COMPAT_RUNTIME=codex, which is set only by
    the Codex legacy-hook wrapper. Claude Code still requires TodoWrite.

    Earlier compatibility only accepted update_plan as an initial bootstrap. That
    left a hole: once initialized, a Codex agent could visually skip workflow
    steps with update_plan while the legacy TodoWrite validators never saw the
    transition. Treat update_plan as the full TodoWrite-equivalent here: validate
    canonical shape, enforce one-step-at-a-time progression, persist last_todos,
    and block invalid transitions before the plan UI is updated.
    """
    if not is_codex_runtime(data):
        return False

    tool_input = data.get('tool_input') if isinstance(data.get('tool_input'), dict) else {}
    plan = tool_input.get('plan')
    if plan is None:
        plan = data.get('plan')
    if not isinstance(plan, list):
        return False

    if not bookmark_path.exists():
        return True

    try:
        state = json.loads(bookmark_path.read_text())
    except Exception:
        return False

    cmd_name = state.get('command', '')
    canonical = run_canonical_todos(cmd_name, project_dir, state.get('arguments', ''))
    todos, violations = codex_plan_to_todos(plan, canonical)
    if violations:
        emit_codex_plan_block(cmd_name, violations, state.get('last_todos') or [])

    last_todos = state.get('last_todos')
    if last_todos is None:
        violations = validate_initial_codex_todos(todos)
    else:
        violations = validate_codex_transition(state, last_todos, todos)
    if violations:
        try:
            state['todo_acknowledged'] = False
            state['lock_reason'] = 'sequence_violation'
            bookmark_path.write_text(json.dumps(state, ensure_ascii=False))
        except Exception:
            pass
        emit_codex_plan_block(cmd_name, violations, last_todos or todos)

    if not persist_codex_initialization(session_id, bookmark_path, state, todos, implicit=False):
        return False
    return True


def acknowledge_codex_canonical_bootstrap(
    data: dict,
    session_id: str,
    bookmark_path: Path,
    project_dir: Path,
    state: dict,
    lock_reason: str,
) -> bool:
    """Initialize Codex checklist state when update_plan is not hook-visible.

    Some Codex runtimes represent update_plan as plan UI state rather than a
    PreToolUse tool event. In that case the explicit update_plan branch above
    cannot run, and the next ordinary tool would otherwise deadlock behind
    CHECKLIST NOT STARTED forever. This compatibility-only fallback persists the
    command's canonical first-call checklist state, but only for the initial
    not-started gate. Claude Code native TodoWrite and existing violation locks
    are untouched.
    """
    if not is_codex_runtime(data):
        return False
    if data.get('tool_name') in CODEX_PLAN_TOOLS:
        return False
    if state.get('todo_acknowledged', False):
        return False
    if lock_reason and lock_reason != 'not_started':
        return False
    cmd_name = state.get('command', '')
    canonical = run_canonical_todos(cmd_name, project_dir, state.get('arguments', ''))
    if not canonical:
        return False
    todos = canonical_initial_todos(canonical)
    return persist_codex_initialization(
        session_id,
        bookmark_path,
        state,
        todos,
        implicit=True,
    )


def main():
    try:
        data = json.load(sys.stdin)
        tool_name = data.get('tool_name', '')
        session_id = data.get('session_id', 'default')
    except Exception:
        sys.exit(0)

    project_dir = Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))
    bookmark_path = project_dir / '.claude' / f'workflow-{session_id}.json'

    if tool_name in CODEX_PLAN_TOOLS and acknowledge_codex_plan(
        data, session_id, bookmark_path, project_dir
    ):
        sys.exit(0)

    # TodoWrite → acknowledge and allow
    # (Stop hook enforces todo count >= blocking_count, so reducing todos is caught at session end)
    # Note: type errors (todos as string instead of array) are caught by Claude Code's schema
    # validation BEFORE PreToolUse hooks run — no need to duplicate that check here.
    # Tools that should always be allowed regardless of workflow state
    ALWAYS_ALLOWED = {'TodoWrite', 'TodoRead', 'mcp__happy__change_title'}

    if tool_name in ALWAYS_ALLOWED and tool_name != 'TodoWrite':
        sys.exit(0)

    if tool_name == 'TodoWrite':
        if bookmark_path.exists():
            try:
                state = json.loads(bookmark_path.read_text())
                changed = False
                if not state.get('todo_acknowledged', False):
                    state['todo_acknowledged'] = True
                    changed = True
                # Always clear lock_reason on TodoWrite — PostToolUse hooks (count/sequence)
                # will re-set it if the new call is still violating.
                # This handles race condition where tracker overwrites todo_acknowledged=False.
                if state.get('lock_reason'):
                    state.pop('lock_reason', None)
                    changed = True
                if changed:
                    bookmark_path.write_text(json.dumps(state))
            except Exception:
                pass
        sys.exit(0)

    # No bookmark → no active workflow → allow
    if not bookmark_path.exists():
        sys.exit(0)

    try:
        state = json.loads(bookmark_path.read_text())
    except Exception:
        sys.exit(0)

    lock_reason = state.get('lock_reason', '')

    # Already acknowledged AND no active lock → allow
    # Note: lock_reason checked independently because todo_acknowledged may stay True
    # due to a race condition between PostToolUse tracker and sequence/count hooks.
    if state.get('todo_acknowledged', False) and not lock_reason:
        sys.exit(0)

    # Not acknowledged or locked → block with reason-specific message
    cmd_name = state.get('command', '?')
    if not lock_reason:
        lock_reason = 'not_started'

    if acknowledge_codex_canonical_bootstrap(
        data, session_id, bookmark_path, project_dir, state, lock_reason
    ):
        sys.exit(0)

    if lock_reason == 'sequence_violation':
        # Hint uses last_todos (pre-violation state) to show the CORRECT next call,
        # not the violating todos-file state.
        last_todos = state.get('last_todos', [])
        next_json = build_sequence_fix_call(last_todos) if last_todos else ''
    else:
        next_json = build_next_todowrite_call(session_id, cmd_name, project_dir)

    codex_runtime = is_codex_runtime(data)
    if codex_runtime:
        plan_hint = codex_plan_hint(next_json)
        json_hint = (
            f'\nCall Codex update_plan with this exact plan array '
            f'(TodoWrite equivalent in Codex):\n{plan_hint}\n'
            if plan_hint else ''
        )
        action = 'Call Codex update_plan'
    else:
        json_hint = (
            f'\nCall TodoWrite with this exact todos array:\n{next_json}\n'
            if next_json else ''
        )
        action = 'Call TodoWrite'

    if lock_reason == 'sequence_violation':
        sys.stderr.write(
            f'\n🚫 STEP SKIPPING DETECTED: /{cmd_name} workflow is locked.\n'
            f'You attempted to skip or reorder steps.\n'
            f'{action} to fix the sequence — complete steps one at a time, in order.\n'
            + json_hint
        )
    elif lock_reason == 'count_mismatch':
        sys.stderr.write(
            f'\n🚫 STEP COUNT VIOLATION: /{cmd_name} workflow is locked.\n'
            f'TodoWrite was called with the wrong number of steps.\n'
            f'{action} with the complete canonical step list.\n'
            + json_hint
        )
    else:
        sys.stderr.write(
            f'\n⚠️  CHECKLIST NOT STARTED: /{cmd_name} workflow is active.\n'
            f'{action} to initialize the checklist before using other tools.\n'
            + json_hint
        )
    sys.exit(2)


if __name__ == '__main__':
    main()
