#!/usr/bin/env python3
"""
PostToolUse Hook: Output checklist progress after every TodoWrite call.

Fires after every TodoWrite call:
1. Reads command name from .claude/workflow-{session_id}.json bookmark
2. Runs todo script to get canonical blocking_count (fresh, no cache)
3. Prints current checklist progress to stdout (injected into Claude's context)

Hook type: PostToolUse (TodoWrite matcher)
Exit codes: 0 always (never blocks)
"""

import json
import os
import subprocess
import sys
from pathlib import Path

STATUS_SYMBOL = {'completed': '[x]', 'in_progress': '[~]', 'pending': '[ ]'}


def run_todo_script(cmd_name: str, project_dir: Path, prompt: str = '') -> list:
    todo_script = project_dir / 'scripts' / 'todo' / f'{cmd_name}.py'
    if not todo_script.exists():
        global_todo = Path.home() / '.claude' / 'scripts' / 'todo' / f'{cmd_name}.py'
        if global_todo.exists():
            todo_script = global_todo
        else:
            return []
    env = {**os.environ}
    env['CLAUDE_TODO_PROMPT'] = prompt or ''
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


def format_checklist(command: str, todos: list, blocking_count: int) -> str:
    completed_count = sum(1 for t in todos if t.get('status') == 'completed')
    lines = [f"WORKFLOW PROGRESS ({command}): {completed_count}/{blocking_count} steps completed"]
    for todo in todos:
        symbol = STATUS_SYMBOL.get(todo.get('status', 'pending'), '[ ]')
        lines.append(f"  {symbol} {todo['content']}")
    if completed_count < blocking_count:
        lines.append("Continue with the next required step.")
    return '\n'.join(lines)


def official_todos_path(session_id: str) -> Path:
    return Path.home() / '.claude' / 'todos' / f'{session_id}-agent-{session_id}.json'


def main():
    try:
        data = json.load(sys.stdin)
        todos = data.get('tool_input', {}).get('todos', [])
        if data.get('agent_id') or not todos:  # F1 bypass + empty-payload guard (pretool-todo-validate.py:284-287)
            sys.exit(0)

        session_id = data.get('session_id', 'default')
        project_dir = Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))
        bookmark_path = project_dir / '.claude' / f'workflow-{session_id}.json'

        cmd_name = '?'
        arguments = ''
        bookmark_state = {}
        if bookmark_path.exists():
            try:
                bookmark_state = json.loads(bookmark_path.read_text())
                cmd_name = bookmark_state.get('command', '?')
                arguments = bookmark_state.get('arguments', '')
            except Exception:
                pass

        all_completed = all(t.get('status') == 'completed' for t in todos)
        todos_file = official_todos_path(session_id)

        if all_completed:
            # Clean up workflow state so future conversations aren't locked
            try:
                todos_file.unlink(missing_ok=True)
            except Exception:
                pass
            try:
                bookmark_path.unlink(missing_ok=True)
            except Exception:
                pass
        else:
            # Write updated todos back so Phase B reads current state
            # BUT only if count matches canonical — prevents corrupting file with bad data
            # when agent submits wrong number of steps (count hook will handle the error)
            canonical = run_todo_script(cmd_name, project_dir, arguments) if cmd_name != '?' else []
            blocking_count = len(canonical) if canonical else 0
            count_ok = blocking_count == 0 or len(todos) >= blocking_count
            if count_ok:
                try:
                    todos_file.parent.mkdir(parents=True, exist_ok=True)
                    todos_file.write_text(json.dumps(todos, ensure_ascii=False))
                except Exception:
                    pass
                # Only mark todo_acknowledged=True when count is correct
                # If count is wrong, count hook will set todo_acknowledged=False + lock_reason
                # Re-read bookmark to avoid clobbering updates from other PostToolUse hooks
                # (e.g. posttool-todo-sequence.py may have updated last_todos concurrently)
                try:
                    fresh_state = json.loads(bookmark_path.read_text())
                    fresh_state['todo_acknowledged'] = True
                    bookmark_path.write_text(json.dumps(fresh_state, ensure_ascii=False))
                except Exception:
                    pass

        # Get blocking_count fresh from todo script — never from cache
        canonical = run_todo_script(cmd_name, project_dir, arguments) if cmd_name != '?' else []
        blocking_count = len(canonical) if canonical else len(todos)

        print(format_checklist('/' + cmd_name, todos, blocking_count))

    except Exception:
        pass
    sys.exit(0)


if __name__ == '__main__':
    main()
