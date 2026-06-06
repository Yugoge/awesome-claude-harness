"""
Shared canonical todo validation utilities.

Used by both pretool-todo-validate.py and posttool-todo-sequence.py
to avoid code duplication.

AF1 fix: Uses subprocess.run() instead of exec() for process isolation.
AF2 fix: Checks project dir first, then home dir (matches other hooks).
"""

import json
import os
import subprocess
from pathlib import Path


def _find_todo_script(cmd_name):
    """Locate the canonical todo script (project dir first, home fallback)."""
    project_dir = Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))
    candidates = [
        project_dir / 'scripts' / 'todo' / f'{cmd_name}.py',
        Path.home() / '.claude' / 'scripts' / 'todo' / f'{cmd_name}.py',
    ]
    for path in candidates:
        if path.exists():
            return path, project_dir
    return None, project_dir


def _parse_script_output(result):
    """Parse subprocess result into validated canonical list or None."""
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        canonical = json.loads(result.stdout)
    except Exception:
        return None
    if not isinstance(canonical, list):
        return None
    if any(not isinstance(item, dict) for item in canonical):
        return None
    return canonical


def run_todo_script(cmd_name, prompt=''):
    """Load canonical todos from todo script via subprocess.

    Search order (AF2 fix -- matches posttool-todo-count.py):
      1. {CLAUDE_PROJECT_DIR}/scripts/todo/{cmd_name}.py
      2. ~/.claude/scripts/todo/{cmd_name}.py

    prompt is forwarded as CLAUDE_TODO_PROMPT so argument-aware scripts
    (e.g. close.py --force path) can vary their step list.

    Returns list of todo dicts or None.
    """
    script_path, project_dir = _find_todo_script(cmd_name)
    if script_path is None:
        return None
    try:
        env = {**os.environ}
        env['CLAUDE_TODO_PROMPT'] = prompt or ''
        result = subprocess.run(
            ['python3', str(script_path)],
            capture_output=True, text=True, cwd=str(project_dir),
            env=env,
        )
        return _parse_script_output(result)
    except Exception:
        return None


def _check_field(canonical, new_todos, field, index, violations):
    """Check a single field match between canonical and submitted todo."""
    c_val = canonical[index].get(field, '')
    n_val = new_todos[index].get(field, '')
    if c_val != n_val:
        violations.append(
            f'Step {index} {field} modified from canonical: '
            f'"{c_val}" -> "{n_val}"'
        )


def check_immutability_against_canonical(canonical, new_todos, violations):
    """Check new todos against canonical source of truth.

    Validates that content and activeForm fields match the canonical
    definition. Checks length mismatch before comparing items.
    """
    if len(canonical) != len(new_todos):
        violations.append(
            f'Todo count mismatch: canonical has {len(canonical)}, '
            f'submitted has {len(new_todos)}'
        )
        return
    for i in range(len(canonical)):
        _check_field(canonical, new_todos, 'content', i, violations)
        _check_field(canonical, new_todos, 'activeForm', i, violations)


def validate_against_canonical(cmd_name, new_todos, prompt=''):
    """Validate new_todos against canonical script if available.

    prompt is forwarded to run_todo_script so argument-aware todo scripts
    (e.g. close.py for --force) can return the correct variant.

    Returns list of violations (empty if valid or no canonical exists).
    """
    canonical = run_todo_script(cmd_name, prompt) if cmd_name else None
    if not canonical:
        return []
    violations = []
    check_immutability_against_canonical(canonical, new_todos, violations)
    return violations
