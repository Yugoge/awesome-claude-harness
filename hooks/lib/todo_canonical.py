"""
Shared canonical todo validation utilities.

Used by both pretool-todo-validate.py and posttool-todo-sequence.py
to avoid code duplication.

AF1 fix: the todo script runs in a process of its own, never in the hook's: a
new interpreter (subprocess.run), or for the harness's own scripts a fork of
the hook that runs them as that interpreter would (_forkable).
AF2 fix: Checks project dir first, then home dir (matches other hooks).

checklist() is the one reading of a command's checklist state (P1b E7): the
transcript records every TodoWrite the CLI ran, so the hooks that gate on the
checklist read it there instead of a copy a hook kept in the workflow bookmark.
"""

import io
import json
import os
import subprocess
import sys
from pathlib import Path


def _find_todo_script(cmd_name):
    """Locate the canonical todo script (project dir first, home fallback)."""
    project_dir = Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))
    candidates = [
        project_dir / 'scripts' / 'todo' / f'{cmd_name}.py',
        Path(__file__).resolve().parents[2] / 'scripts' / 'todo' / f'{cmd_name}.py',
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


_HARNESS_TODO_DIR = Path(__file__).resolve().parents[2] / 'scripts' / 'todo'


def _forkable(script_path, env):
    """True when a fork of this process runs ``script_path`` as the new
    ``python3`` subprocess.run would: the script is one of the harness's own
    todo scripts (stdlib only; hooks/tests/test_todo_script_fork.py runs each
    both ways), this process is that same interpreter started with no options,
    and no other thread runs. A fork skips the interpreter start, the largest
    cost of a gate that reads the checklist at every tool call."""
    if not hasattr(os, 'fork') or getattr(sys, '__stdout__', None) is None:
        return False
    threading = sys.modules.get('threading')
    if threading is not None and threading.active_count() > 1:
        return False
    argv = getattr(sys, 'orig_argv', None) or []
    if len(argv) < 2 or argv[1].startswith('-'):
        return False
    try:
        if os.path.dirname(os.path.realpath(script_path)) != os.path.realpath(_HARNESS_TODO_DIR):
            return False
    except (OSError, ValueError):
        return False
    for directory in os.get_exec_path(env):  # the PATH search the subprocess would make
        if not os.path.isabs(directory):
            return False
        candidate = os.path.join(directory, 'python3')
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate == sys.executable
    return False


def _run_forked(script_path, project_dir, env):
    """``subprocess.run(['python3', script], capture_output=True, text=True,
    cwd=project_dir, env=env)`` run in a fork of this process: the child is
    another process (AF1), so the script reaches the hook only through its
    exit status and its stdout."""
    path = str(script_path)
    encoding, errors = sys.__stdout__.encoding, sys.__stdout__.errors
    read_fd, write_fd = os.pipe()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    try:
        pid = os.fork()
    except OSError:
        os.close(read_fd)
        os.close(write_fd)
        raise
    if pid == 0:  # the child: run the script as a new interpreter's __main__, never return
        status = 1
        try:
            os.close(read_fd)
            os.dup2(write_fd, 1)
            os.close(write_fd)
            null = os.open(os.devnull, os.O_WRONLY)
            os.dup2(null, 2)
            os.close(null)
            os.chdir(project_dir)
            os.environ.update(env)
            sys.stdout = io.TextIOWrapper(io.BufferedWriter(io.FileIO(1, 'w', closefd=False)),
                                          encoding=encoding, errors=errors, newline='\n')
            sys.stderr = io.TextIOWrapper(io.FileIO(2, 'w', closefd=False), encoding='utf-8',
                                          errors='backslashreplace', write_through=True)
            sys.argv = [path]
            sys.path.insert(0, os.path.dirname(os.path.realpath(path)))
            main = type(sys)('__main__')
            main.__file__, main.__cached__ = path, None
            sys.modules['__main__'] = main
            with open(path, 'rb') as handle:
                code = compile(handle.read(), path, 'exec', dont_inherit=True)
            try:
                exec(code, main.__dict__)
                status = 0
            except SystemExit as stop:
                status = 0 if stop.code is None else stop.code if isinstance(stop.code, int) else 1
            sys.stdout.flush()
        except BaseException:
            status = 1
        finally:
            os._exit(status & 0xFF)
    os.close(write_fd)
    with os.fdopen(read_fd, 'rb') as pipe:
        raw = pipe.read()
    _, wait_status = os.waitpid(pid, 0)
    # Decoded as subprocess.run(text=True) decodes: the locale's encoding
    # (UTF-8 in UTF-8 mode), strict, universal newlines.
    probe = io.TextIOWrapper(io.BytesIO())
    stdout = raw.decode(probe.encoding, probe.errors).replace('\r\n', '\n').replace('\r', '\n')
    return subprocess.CompletedProcess(['python3', path], os.waitstatus_to_exitcode(wait_status), stdout, '')


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
        result = None
        if _forkable(script_path, env):
            try:
                result = _run_forked(script_path, str(project_dir), env)
            except OSError:  # no fork (EAGAIN, ENOMEM): the subprocess below
                result = None
        if result is None:
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


def initial_status_violations(todos):
    """First-call rule: no completed step, at most 1 in_progress, at Step 0."""
    violations = []
    completed = [i for i, t in enumerate(todos) if t.get('status') == 'completed']
    in_progress = [i for i, t in enumerate(todos) if t.get('status') == 'in_progress']
    if completed:
        names = [f'Step {i}: "{todos[i]["content"]}"' for i in completed]
        violations.append(
            f'Initial TodoWrite cannot have completed steps ({len(completed)}):\n'
            + '\n'.join(f'  - {n}' for n in names)
        )
    if len(in_progress) > 1:
        violations.append(f'Initial TodoWrite: at most 1 in_progress (found {len(in_progress)})')
    if in_progress and in_progress[0] != 0:
        violations.append(f'Initial in_progress must be Step 0, not Step {in_progress[0]}')
    return violations


def _ok_lists(calls, before=None):
    """(call, todos) of each ok TodoWrite of ``calls`` whose todos is a list of
    steps, up to the call ``before``."""
    for call in calls:
        if before and call.id == before:
            break
        new = call.input.get('todos')
        if call.ok and isinstance(new, list) and all(isinstance(t, dict) for t in new):
            yield call, new


def _accepted_writes(lists):
    """(the last list, the calls the step rules accepted) of ``lists``, in
    order: from the first list initial_status_violations passes on."""
    todos, writes = None, []
    for call, new in lists:
        todos = new
        if writes or not initial_status_violations(new):
            writes.append(call)
    return todos, tuple(writes)


_UNREAD = object()


class Checklist:
    """The active command's checklist as the transcript records it. A plain
    class: importing dataclasses would cost the workflow gate, which reads the
    checklist at every tool call, more than the rest of its reading."""
    __slots__ = ('span', 'canonical', '_todos', '_accepted', '_writes', '_before')

    def __init__(self, span, canonical, todos, accepted, writes=None, before=None):
        self.span = span              # command_span.Span of the command
        self.canonical = canonical    # its canonical steps (scripts/todo/<command>.py)
        self._todos = todos           # todos, once read (_UNREAD before)
        self._accepted = accepted     # the step rules accepted an ok TodoWrite of the span
        self._writes = writes         # writes, once read
        self._before = before         # the tool use the checklist stops ahead of, if any

    @property
    def todos(self):
        """The last ok TodoWrite's list: the checklist the CLI holds; None
        before the first. Read from the end of the span when first asked: the
        readers that need only the command and its canonical steps (the count
        and progress hooks) leave it unread. No step rule runs on it, so
        reading it later raises nothing checklist() would have raised."""
        if self._todos is _UNREAD:
            self._todos = next((new for _call, new in _ok_lists(
                self.span.uses('TodoWrite', newest_first=True, before=self._before))), None)
        return self._todos

    @property
    def writes(self):
        """The ok TodoWrite calls the step rules accepted, in order (a tuple).
        Read when first asked: only the subagent completion guard needs every
        one, so the other readers leave a long span's lists undecoded."""
        if self._writes is None:
            self._writes = _accepted_writes(_ok_lists(self.span.calls('TodoWrite'), self._before))[1]
        return self._writes

    @property
    def write_uses(self):
        """writes as command_span.Use records (results by offset, no line
        numbers), for a reader that only orders them: a span read from the end
        of a long transcript then never counts the lines before it."""
        return _accepted_writes(_ok_lists(self.span.uses('TodoWrite'), self._before))[1]

    @property
    def command(self):
        return self.span.command

    @property
    def arguments(self):
        return self.span.args

    @property
    def accepted(self):
        """The list the next TodoWrite is checked against, or None."""
        return self.todos if self._accepted else None

    @property
    def lock(self):
        """Why the workflow gate holds other tools back, or '' when it does not."""
        if self.todos is None:
            return 'not_started'
        if len(self.todos) < len(self.canonical):
            return 'count_mismatch'
        if not self._accepted:
            return 'sequence_violation'
        return ''


def checklist(transcript_path, before=None):
    """The checklist of the command that opened the active span, or None when
    no harness command with a canonical checklist did. ``before`` (a tool use
    id) leaves out that call and every later one.

    Every ok TodoWrite already passed pretool-todo-validate.py against the
    accepted list before it, so the step rules accept it too, except the first
    rule only posttool-todo-sequence.py applies: a first list that breaks
    initial_status_violations is not accepted, and the next is a first call
    again.

    Only the lists that decide are decoded: from the start the lists up to
    the first the step rules accept, and, when a reader asks for it, the
    newest ok list from the end (with ``before``, back from the call that has
    that id). Every later ok list is accepted too, so the last accepted list
    is the newest and needs no reading of its own."""
    try:  # imported as hooks.lib.todo_canonical (tests) or lib.todo_canonical (hooks)
        from . import command_span
    except ImportError:  # loaded by path, with hooks/ or hooks/lib on sys.path
        try:
            from lib import command_span
        except ImportError:
            import command_span
    span = command_span.active_span(transcript_path) if transcript_path else None
    if span is None:
        return None
    canonical = run_todo_script(span.command, span.args)
    if not canonical:
        return None
    # Read here, not when asked: the step rules may raise on a list, and a
    # caller that guards checklist() must see that inside the call. With no ok
    # list the rules run on nothing, as when the newest list is None.
    accepted = any(
        not initial_status_violations(new) for _call, new in _ok_lists(span.uses('TodoWrite', before=before)))
    return Checklist(span, canonical, _UNREAD, accepted, before=before)
