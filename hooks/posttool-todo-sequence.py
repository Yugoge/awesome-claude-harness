#!/usr/bin/env python3
"""
PostToolUse Hook: Enforce one-step-at-a-time progression in workflow checklists.

Compares the new TodoWrite input against the list the step rules last
accepted, read from the transcript (lib.todo_canonical.checklist, P1b E7).
Blocks if agent completed multiple steps at once, skipped in_progress, set
multiple steps to in_progress simultaneously, or modified step
content/activeForm (only status changes are allowed). The block is the whole
effect: the workflow gate reads the same record, so nothing is written.

Exit codes:
  0: Valid transition, allow
  2: Sequence violation, block
"""

import json
import sys
from pathlib import Path

# Import shared canonical validation
sys.path.insert(0, str(Path(__file__).parent))
from lib.todo_canonical import checklist, initial_status_violations, validate_against_canonical


def check_content_field(old, new, idx, field, violations):
    """Check a single field for immutability."""
    old_val = old.get(field, '')
    new_val = new.get(field, '')
    if old_val != new_val:
        violations.append(f'Step {idx} {field} modified: "{old_val}" -> "{new_val}"')


def check_content_immutability(last_todos, new_todos, violations):
    """Rule 5: content and activeForm are immutable after initialization."""
    for i, (old, new) in enumerate(zip(last_todos, new_todos)):
        check_content_field(old, new, i, 'content', violations)
        check_content_field(old, new, i, 'activeForm', violations)


def find_newly_completed(last_todos, new_todos):
    """Find step indices that transitioned to completed."""
    prev = {i for i, t in enumerate(last_todos) if t.get('status') == 'completed'}
    cur = {i for i, t in enumerate(new_todos) if t.get('status') == 'completed'}
    return cur - prev


def check_max_one_completion(newly_completed, new_todos, violations):
    """Rule 1: max 1 newly completed per call."""
    if len(newly_completed) <= 1:
        return
    names = [f'Step {i}: "{new_todos[i]["content"]}"' for i in sorted(newly_completed)]
    violations.append(
        f'Completed {len(newly_completed)} steps in one call (max 1):\n'
        + '\n'.join(f'  - {n}' for n in names)
    )


def _was_pending(last_todos, idx):
    """Check if a step was pending in the previous state."""
    return last_todos[idx].get('status') == 'pending'


def check_no_skip_in_progress(newly_completed, last_todos, new_todos, violations):
    """Rule 2: no pending -> completed (must pass through in_progress)."""
    for idx in newly_completed:
        if not _was_pending(last_todos, idx):
            continue
        msg = f'Step {idx} ("{new_todos[idx]["content"]}"): '
        violations.append(msg + 'pending -> completed without in_progress')


def check_single_in_progress(new_todos, violations):
    """Rule 3: max 1 in_progress at a time."""
    in_progress = [t for t in new_todos if t.get('status') == 'in_progress']
    if len(in_progress) > 1:
        names = ', '.join(f'"{t["content"]}"' for t in in_progress)
        violations.append(f'Multiple in_progress simultaneously ({len(in_progress)}): {names}')


def _find_incomplete_predecessor(new_todos, idx):
    """Return first predecessor index that is not completed, or None."""
    for prev_idx in range(idx):
        if new_todos[prev_idx].get('status') != 'completed':
            return prev_idx
    return None


def _format_ordering_violation(new_todos, step_idx, blocker_idx):
    """Format an ordering violation message."""
    step_name = new_todos[step_idx].get('content', '?')
    blocker_name = new_todos[blocker_idx].get('content', '?')
    return f'Step {step_idx} ("{step_name}"): cannot start before Step {blocker_idx} ("{blocker_name}") is completed'


def check_ordering(last_todos, new_todos, violations):
    """Rule 4: can't start step N if any earlier step is pending."""
    for i, (prev, cur) in enumerate(zip(last_todos, new_todos)):
        if prev.get('status') != 'pending' or cur.get('status') != 'in_progress':
            continue
        incomplete = _find_incomplete_predecessor(new_todos, i)
        if incomplete is not None:
            violations.append(_format_ordering_violation(new_todos, i, incomplete))


def check_completion_rules(last_todos, new_todos, violations):
    """Rules 1-4: sequence, status transitions, ordering."""
    newly_completed = find_newly_completed(last_todos, new_todos)
    check_max_one_completion(newly_completed, new_todos, violations)
    check_no_skip_in_progress(newly_completed, last_todos, new_todos, violations)
    check_single_in_progress(new_todos, violations)
    check_ordering(last_todos, new_todos, violations)


def build_hint(last_todos):
    """Build a hint for the required next action."""
    for i, t in enumerate(last_todos):
        if t.get('status') == 'in_progress':
            return f'\nREQUIRED: Complete Step {i} ("{t["content"]}"), then start Step {i+1}.'
    return ''


def emit_error(cmd_name, violations, last_todos):
    """Write the violation error and block."""
    numbered = '\n'.join(f'  [{j+1}] {v}' for j, v in enumerate(violations))
    next_hint = build_hint(last_todos) if last_todos else ''
    sys.stderr.write(
        f'\nBLOCKED STEP SEQUENCE VIOLATION in /{cmd_name}:\n'
        + numbered
        + '\n\nRULES: (1) One completion per call (2) Must pass through '
        'in_progress (3) One in_progress at a time (4) In order '
        '(5) Content immutable\n'
        + next_hint + '\n'
    )
    sys.exit(2)


def emit_canonical_error(violations):
    """Emit canonical validation error."""
    numbered = '\n'.join(f'  [{j+1}] {v}' for j, v in enumerate(violations))
    sys.stderr.write(
        f'\nBLOCKED TodoWrite (canonical validation):\n' + numbered
        + '\n\nContent/activeForm must match canonical in ~/.claude/scripts/todo/\n\n'
    )
    sys.exit(2)


def handle_first_call(arguments, cmd_name, new_todos):
    """First call: validate canonical + initial status."""
    canonical_violations = validate_against_canonical(cmd_name, new_todos, arguments)
    if canonical_violations:
        emit_canonical_error(canonical_violations)
    status_violations = initial_status_violations(new_todos)
    if status_violations:
        emit_error(cmd_name, status_violations, None)
    sys.exit(0)


def handle_length_mismatch(arguments, cmd_name, new_todos):
    """Length mismatch: validate canonical."""
    canonical_violations = validate_against_canonical(cmd_name, new_todos, arguments)
    if canonical_violations:
        emit_canonical_error(canonical_violations)
    sys.exit(0)


def handle_normal(cmd_name, last_todos, new_todos):
    """Normal case: full sequence validation."""
    violations = []
    check_content_immutability(last_todos, new_todos, violations)
    check_completion_rules(last_todos, new_todos, violations)
    if violations:
        emit_error(cmd_name, violations, last_todos)
    sys.exit(0)


def parse_stdin():
    """Parse stdin JSON. Returns (new_todos, transcript_path, tool_use_id) or exits.

    F1: subagent bypass — when agent_id is present in stdin, exit 0
    immediately. Subagents have their own todo schemas per role and
    shouldn't be force-fitted to main agent's canonical-21 schema.
    """
    try:
        data = json.load(sys.stdin)
        if data.get('agent_id'):
            sys.exit(0)
        todos = data.get('tool_input', {}).get('todos', [])
        return todos, data.get('transcript_path'), data.get('tool_use_id')
    except Exception:
        sys.exit(0)


def main():
    new_todos, transcript_path, tool_use_id = parse_stdin()
    if not new_todos:
        sys.exit(0)
    # This call is already in the record; the list it is checked against is
    # the one accepted before it.
    state = checklist(transcript_path, before=tool_use_id)
    if state is None:
        sys.exit(0)
    cmd_name = state.command
    last_todos = state.accepted
    if last_todos is None:
        handle_first_call(state.arguments, cmd_name, new_todos)
    elif len(last_todos) != len(new_todos):
        handle_length_mismatch(state.arguments, cmd_name, new_todos)
    else:
        handle_normal(cmd_name, last_todos, new_todos)


if __name__ == '__main__':
    main()
