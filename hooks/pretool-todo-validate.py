#!/usr/bin/env python3
"""
PreToolUse Hook: Validate TodoWrite input BEFORE execution.

Prevents sequence violations by checking the proposed todos array against
the last known state. This is the enforcement counterpart to
posttool-todo-sequence.py (which can only warn after the fact).

State: reads last_todos from .claude/workflow-{session_id}.json

Rules enforced:
  1. Max 1 step completed per call
  2. Steps must pass through in_progress before completed
  3. Only 1 step can be in_progress at a time
  4. Content and activeForm are immutable (only status changes allowed)
  5. Steps must be completed in order (no skipping ahead)
  6. Subagent completion guard (Gate 4): cannot complete a subagent step
     without having called the Agent tool first

Exit codes:
  0: Valid, allow TodoWrite
  2: Violation detected, block TodoWrite (calls sys.exit(2))
"""

import json
import os
import sys
from pathlib import Path

# Import shared canonical validation
sys.path.insert(0, str(Path(__file__).parent))
from lib.todo_canonical import validate_against_canonical, run_todo_script


def _check_field_changed(old_val, new_val):
    """Return True if a field value changed."""
    return old_val != new_val


def _format_step_hint(index, content):
    """Format a hint for a specific step."""
    return f'\nREQUIRED: Complete Step {index} ("{content}"), then start Step {index+1}.'


def check_immutability(last, new, violations):
    """Content and activeForm are immutable after init."""
    for i, (o, n) in enumerate(zip(last, new)):
        old_c, new_c = o.get('content', ''), n.get('content', '')
        if _check_field_changed(old_c, new_c):
            violations.append(f'Step {i} content modified: "{old_c}" -> "{new_c}"')
        old_a, new_a = o.get('activeForm', ''), n.get('activeForm', '')
        if _check_field_changed(old_a, new_a):
            violations.append(f'Step {i} activeForm modified: "{old_a}" -> "{new_a}"')


def check_max_one_completion(last, new, violations):
    """Rule 1: max 1 newly completed per call."""
    prev = {i for i, t in enumerate(last) if t.get('status') == 'completed'}
    cur = {i for i, t in enumerate(new) if t.get('status') == 'completed'}
    fresh = cur - prev
    if len(fresh) > 1:
        names = [f'Step {i}: "{new[i]["content"]}"' for i in sorted(fresh)]
        violations.append(
            f"Completed {len(fresh)} steps in one call (max 1):\n"
            + '\n'.join(f'  - {n}' for n in names)
        )
    return fresh


def _check_one_skip(idx, last, new, violations):
    """Check if a single step skipped in_progress."""
    if idx < len(last) and last[idx].get('status') == 'pending':
        msg = (f'Step {idx} ("{new[idx]["content"]}"): '
               f'pending -> completed without in_progress')
        violations.append(msg)


def check_skip_in_progress(last, new, fresh, violations):
    """Rule 2: no pending -> completed without in_progress."""
    for idx in fresh:
        _check_one_skip(idx, last, new, violations)


def check_single_in_progress(new, violations):
    """Rule 3: max 1 in_progress at a time."""
    ip = [t for t in new if t.get('status') == 'in_progress']
    if len(ip) > 1:
        violations.append(
            f"Multiple in_progress ({len(ip)}): "
            + ', '.join(f'"{t["content"]}"' for t in ip)
        )


def _find_incomplete_predecessor(new, idx):
    """Find first non-completed step before idx, or None."""
    for prev in range(idx):
        if new[prev].get('status') != 'completed':
            return prev
    return None


def _check_one_ordering(idx, new, violations):
    """Check ordering constraint for a single newly-started step."""
    prev = _find_incomplete_predecessor(new, idx)
    if prev is not None:
        violations.append(
            f'Step {idx} ("{new[idx]["content"]}"): '
            f'cannot start before Step {prev} '
            f'("{new[prev]["content"]}") is completed'
        )


def check_ordering(last, new, violations):
    """Rule 4: can't start step N before earlier steps complete."""
    started = [
        i for i, (p, c) in enumerate(zip(last, new))
        if p.get('status') == 'pending' and c.get('status') == 'in_progress'
    ]
    for idx in started:
        _check_one_ordering(idx, new, violations)


def _activate_next_pending(todos, start_idx=0):
    """Set the first pending step (from start_idx) to in_progress."""
    for t in todos[start_idx:]:
        if t.get('status') == 'pending':
            t['status'] = 'in_progress'
            return


def build_correct_call(last):
    """Compute the valid next TodoWrite from last state."""
    if not last:
        return ''
    result = [t.copy() for t in last]
    ip = next(
        (i for i, t in enumerate(result) if t.get('status') == 'in_progress'),
        None
    )
    if ip is not None:
        result[ip]['status'] = 'completed'
        _activate_next_pending(result, ip + 1)
    else:
        _activate_next_pending(result)
    return json.dumps(result, ensure_ascii=False, separators=(',', ': '))


def load_state(session_id):
    """Load workflow bookmark, return state dict or None."""
    project_dir = Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))
    path = project_dir / '.claude' / f'workflow-{session_id}.json'
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def validate(last, new):
    """Run all validation rules, return list of violations."""
    violations = []
    check_immutability(last, new, violations)
    fresh = check_max_one_completion(last, new, violations)
    check_skip_in_progress(last, new, fresh, violations)
    check_single_in_progress(new, violations)
    check_ordering(last, new, violations)
    return violations


def _find_in_progress_hint(last):
    """Build hint string for the current in_progress step."""
    for i, t in enumerate(last):
        if t.get('status') == 'in_progress':
            return _format_step_hint(i, t['content'])
    return ''


def emit_block(cmd, violations, last):
    """Print block message to stderr and exit 2."""
    hint = _find_in_progress_hint(last)
    correct = build_correct_call(last)
    json_hint = f'\nCall TodoWrite with:\n{correct}\n' if correct else ''
    numbered = '\n'.join(f'  [{j+1}] {v}' for j, v in enumerate(violations))
    sys.stderr.write(
        f'\nBLOCKED TodoWrite for /{cmd}:\n' + numbered
        + '\n\nRULES: (1) One completion per call '
        '(2) Must pass through in_progress '
        '(3) One in_progress at a time '
        '(4) In order (5) Content immutable\n'
        + hint + json_hint + '\n'
    )
    sys.exit(2)


def _build_canonical_hint(cmd):
    """Build canonical todos hint string for error messages."""
    canonical = run_todo_script(cmd) if cmd else None
    if not canonical:
        return ''
    return ('\nCorrect canonical todos:\n'
            + json.dumps(canonical, ensure_ascii=False, indent=2) + '\n')


def emit_block_canonical(cmd, violations):
    """Print block message for canonical validation failures."""
    numbered = '\n'.join(f'  [{j+1}] {v}' for j, v in enumerate(violations))
    hint = _build_canonical_hint(cmd)
    sys.stderr.write(
        f'\nBLOCKED TodoWrite (canonical validation):\n' + numbered
        + '\n\nContent/activeForm must match the canonical definition '
        'in ~/.claude/scripts/todo/\n'
        + hint + '\n'
    )
    sys.exit(2)


def validate_against_canonical_if_needed(cmd, new_todos, prompt=''):
    """Validate new_todos against canonical script if available."""
    violations = validate_against_canonical(cmd, new_todos, prompt)
    if violations:
        emit_block_canonical(cmd, violations)
        return False
    return True


def _find_completing_subagent_step(state, last, new_todos, canonical):
    """Find a step transitioning to completed that needs subagent guard."""
    for i, (old, new) in enumerate(zip(last, new_todos)):
        needs_guard = (
            old.get('status') == 'in_progress'
            and new.get('status') == 'completed'
            and i < len(canonical)
            and canonical[i].get('subagent_call')
        )
        if not needs_guard:
            continue
        called = state.get('subagent_calls', {}).get(str(i), False)
        if not called:
            return i, new, canonical[i].get('subagent_call')
    return None, None, None


def _format_subagent_names(subagent_call):
    """Format subagent type names from subagent_call metadata."""
    if isinstance(subagent_call, list):
        return ', '.join(s.get('subagent_type', '?') for s in subagent_call)
    return subagent_call.get('subagent_type', '?')


def check_subagent_completion_guard(state, last, new_todos, cmd):
    """Gate 4: block completing a subagent step without calling Agent."""
    if not last or not cmd:
        return
    canonical = run_todo_script(cmd, state.get('arguments', ''))
    if not canonical:
        return
    idx, step_todo, sa_call = _find_completing_subagent_step(
        state, last, new_todos, canonical
    )
    if idx is not None:
        agents = _format_subagent_names(sa_call)
        sys.stderr.write(
            f'\nBLOCKED: Cannot complete Step {idx} '
            f'("{step_todo.get("content", "?")}").\n'
            f'This step requires a subagent call ({agents}) '
            f'that has not been made.\n'
            f'Call the Agent tool first, then mark completed.\n\n'
        )
        sys.exit(2)


def parse_stdin():
    """Parse stdin JSON. Returns data dict or exits 0."""
    try:
        return json.load(sys.stdin)
    except Exception:
        sys.exit(0)


def main():
    """Entry point: parse stdin, load state, validate, block or allow."""
    data = parse_stdin()
    # F1: subagent bypass — subagents have their own todo schemas (one per
    # role) and shouldn't be force-fitted to main agent's canonical schema.
    if data.get('agent_id'):
        sys.exit(0)
    if data.get('tool_name') != 'TodoWrite':
        sys.exit(0)
    new_todos = data.get('tool_input', {}).get('todos', [])
    if not new_todos:
        sys.exit(0)
    state = load_state(data.get('session_id', 'default'))
    if not state:
        sys.exit(0)
    last = state.get('last_todos')
    cmd = state.get('command', '')
    if last is None or len(last) != len(new_todos):
        validate_against_canonical_if_needed(cmd, new_todos, state.get('arguments', '') if state else '')
        sys.exit(0)
    violations = validate(last, new_todos)
    if violations:
        emit_block(cmd, violations, last)
    check_subagent_completion_guard(state, last, new_todos, cmd)
    sys.exit(0)


if __name__ == '__main__':
    main()
