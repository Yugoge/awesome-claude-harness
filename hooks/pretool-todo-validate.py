#!/usr/bin/env python3
"""
PreToolUse Hook: Validate TodoWrite input BEFORE execution.

Prevents sequence violations by checking the proposed todos array against
the last known state. This is the enforcement counterpart to
posttool-todo-sequence.py (which can only warn after the fact).

State: the transcript records every TodoWrite and Agent call (P1b E7); the
last accepted list and the dispatches come from lib.todo_canonical.checklist.

Rules enforced:
  1. Max 1 step completed per call
  2. Steps must pass through in_progress before completed
  3. Only 1 step can be in_progress at a time
  4. Content and activeForm are immutable (only status changes allowed)
  5. Steps must be completed in order (no skipping ahead)
  6. Subagent completion guard (Gate 4): cannot complete a subagent step
     without an Agent call of its role that came back or that /restart resumed
  7. The wake (/dev-overnight Step 0) completes only after a recurring
     CronCreate of the wake's prompt in the span (P1c X8)
Past a command's first list, lists of one length pair by content, never index.

Exit codes:
  0: Valid, allow TodoWrite
  2: Violation detected, block TodoWrite (calls sys.exit(2))
"""

import json
import re
import sys
from pathlib import Path

# Import shared canonical validation
sys.path.insert(0, str(Path(__file__).parent))
from lib.todo_canonical import by_content, checklist, validate_against_canonical, run_todo_script


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


def _build_canonical_hint(cmd, prompt=''):
    """Build canonical todos hint string for error messages."""
    canonical = run_todo_script(cmd, prompt) if cmd else None
    if not canonical:
        return ''
    return ('\nCorrect canonical todos:\n'
            + json.dumps(canonical, ensure_ascii=False, indent=2) + '\n')


def emit_block_canonical(cmd, violations, prompt=''):
    """Print block message for canonical validation failures."""
    numbered = '\n'.join(f'  [{j+1}] {v}' for j, v in enumerate(violations))
    hint = _build_canonical_hint(cmd, prompt)
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
        emit_block_canonical(cmd, violations, prompt)
        return False
    return True


def _subagent_types(step):
    """The subagent types a canonical step's subagent_call names, lower-cased."""
    call = step.get('subagent_call') if isinstance(step, dict) else None
    entries = call if isinstance(call, list) else [call]
    return {str(e.get('subagent_type') or '').strip().lower() for e in entries if isinstance(e, dict)}


def _in_progress(todos):
    """The one in_progress step's index, or None (none, or several)."""
    found = [i for i, t in enumerate(todos) if t.get('status') == 'in_progress']
    return found[0] if len(found) == 1 else None


def _resumed(state, sid):
    """(offset, 1, call) of each Agent call of the span that never came back
    but whose agent the /restart recovery resumed (the span's SendMessage to
    it, placed there), saw come back (its journal record) and finalized (an ok
    finalize call of restart.md's helper after it in the span): that call is its
    step's dispatch, with no replacement call (commands/restart.md, Lesson 16)."""
    from lib.subagent_restart import completed_resumes, is_helper_invocation
    journal = completed_resumes(sid)
    cut = {c.id: c for c in state.span.uses('Agent', 'Task') if not c.ok} if journal else {}
    done = [b.result_at for b in state.span.uses('Bash') if b.ok and str(b.input.get('command')).split()[2:3]
            == ['finalize'] and is_helper_invocation({'tool_name': 'Bash', 'tool_input': b.input})] if cut else []
    return [(m.result_at, 1, cut[journal[str(m.input.get('to'))]]) for m in state.span.uses('SendMessage')
            if cut and m.ok and journal.get(str(m.input.get('to'))) in cut and any(t > m.result_at for t in done)]


def _dispatched_steps(state, canonical, sid=''):
    """The subagent steps a dispatch has been made for, read from the record:
    each Agent call that came back, or that a recovery resumed (_resumed),
    pairs with a step. With step ip in progress,
    a typed call counts for the first step of ip..ip+2 that names its type and
    has no call yet (the window covers a TodoWrite and its Agent sent
    together), an untyped call for ip itself. A step set back to pending (a new
    overnight cycle) needs a new call."""
    # Ordered by where each result is recorded (the offset of its line, which
    # orders as its line number does), so no line before the span is counted.
    events = sorted([(w.result_at, 0, w) for w in state.write_uses]
                    + [(c.result_at, 1, c) for c in state.span.uses('Agent', 'Task') if c.ok]
                    + _resumed(state, sid), key=lambda e: (e[0], e[1]))
    current, steps, counted = [], [], set()
    for _, is_dispatch, call in events:
        if not is_dispatch:
            current = call.input['todos']
            steps = by_content(canonical, current)
            counted -= {i for i, t in enumerate(current) if t.get('status') == 'pending'}
            continue
        ip = _in_progress(current)
        if ip is None:
            continue
        kind = str(call.input.get('subagent_type') or '').strip().lower()
        window = range(ip, min(len(current), ip + 3)) if kind else [ip]
        for i in window:
            types = _subagent_types(steps[i])
            if types and i not in counted and (not kind or kind in types):
                counted.add(i)
                break
    return counted


def _find_completing_subagent_step(state, last, new_todos, canonical, sid=''):
    """Find a step transitioning to completed that needs subagent guard."""
    dispatched = None
    for i, (old, new, step) in enumerate(zip(last, new_todos, by_content(canonical, new_todos))):
        needs_guard = (
            old.get('status') == 'in_progress'
            and new.get('status') == 'completed'
            and step.get('subagent_call')
        )
        if not needs_guard:
            continue
        if dispatched is None:
            dispatched = _dispatched_steps(state, canonical, sid)
        if i not in dispatched:
            return i, new, step
    return None, None, None


def _format_subagent_names(subagent_call):
    """Format subagent type names from subagent_call metadata."""
    if isinstance(subagent_call, list):
        return ', '.join(s.get('subagent_type', '?') for s in subagent_call)
    return subagent_call.get('subagent_type', '?')


def _unreturned(state, types):
    """'call <id>, declared artifacts: ...' of each Agent call of one of
    ``types`` in the span that has not come back (its obligation's paths)."""
    from lib.obligation import extract_obligation_block
    return [f'call {c.id}, declared artifacts: ' + (', '.join(re.findall(r'"path":\s*"([^"]+)"', getattr(
        extract_obligation_block(str(c.input.get('prompt') or '')), 'body', ''))) or 'none')
        for c in state.span.uses('Agent', 'Task')
        if not c.ok and str(c.input.get('subagent_type') or '').strip().lower() in types]


def check_subagent_completion_guard(state, last, new_todos, cmd, sid=''):
    """Gate 4: block completing a subagent step without calling Agent."""
    if not last or not cmd:
        return
    idx, step_todo, step = _find_completing_subagent_step(
        state, last, new_todos, state.canonical, sid
    )
    if idx is not None:
        agents = _format_subagent_names(step.get('subagent_call'))
        cut = _unreturned(state, _subagent_types(step))
        why = (f'Its {agents} call has not come back ({"; ".join(cut)}). A subagent cut by an '
               'interrupted session or a usage limit is resumed and finalized by the owner\'s /restart '
               '(commands/restart.md), never replaced by a new call.\n\n' if cut else
               f'This step requires a subagent call ({agents}) that has not been made.\n'
               'Call the Agent tool first, then mark completed.\n\n')
        sys.stderr.write(f'\nBLOCKED: Cannot complete "{step_todo.get("content", "?")}" '
                         f'(subagent role {agents}).\n' + why)
        sys.exit(2)


def check_wake_step(state, last, new_todos):
    """Rule 7: the wake step completes only after an ok recurring CronCreate of
    the wake's prompt in the span, the job the session's CronDelete ends."""
    from lib import overnight
    for old, new, step in zip(last, new_todos, by_content(state.canonical, new_todos)):
        if (step.get('wake_call') and old.get('status') == 'in_progress' and new.get('status') == 'completed'
                and not any(overnight.is_wake(u) for u in state.span.uses('CronCreate'))):
            sys.stderr.write(f'\nBLOCKED: Cannot complete "{new.get("content")}": this /{state.command} span holds '
                             "no ok recurring CronCreate of the wake's prompt. Call CronCreate as the command's "
                             'text gives it (recurring, its prompt verbatim), then mark the step completed.\n')
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
    state = checklist(data.get('transcript_path'))
    if not state:
        sys.exit(0)
    last = state.accepted
    cmd = state.command
    if last is None or len(last) != len(new_todos):
        validate_against_canonical_if_needed(cmd, new_todos, state.arguments)
        sys.exit(0)
    paired = by_content(last, new_todos)
    violations = validate(paired, new_todos)
    if violations:
        emit_block(cmd, violations, last)
    check_wake_step(state, paired, new_todos)
    check_subagent_completion_guard(state, paired, new_todos, cmd, str(data.get('session_id') or ''))
    sys.exit(0)


if __name__ == '__main__':
    main()
