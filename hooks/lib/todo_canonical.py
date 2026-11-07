"""
Shared canonical todo validation utilities.

Used by pretool-todo-validate.py, the TodoWrite rules' one decider, and
by the readers of a command's checklist.

AF1 fix: the todo script runs in a process of its own, never in the hook's: a
new interpreter (subprocess.run), or for the harness's own scripts a fork of
the hook that runs them as that interpreter would (_forkable).
AF2 fix: Checks project dir first, then home dir (matches other hooks).

checklist() is the one reading of a command's checklist state (P1b E7): the
transcript records every TodoWrite the CLI ran, so the hooks that gate on the
checklist read it there instead of a copy a hook kept in the workflow bookmark.

write_bookmark() is the workflow bookmark's one writer (P1b D24): every hook
that starts or updates <project>/.claude/workflow-<sid>.json writes through it.
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

    Search order (AF2 fix):
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


def by_content(steps, todos):
    """Each of ``todos`` paired with the step of ``steps`` of the same content ({} when none): past
    a command's first list and with its length unchanged, a hook comparing todo lists pairs them
    so, never by index (P1c row 17: a session keeps the list it started with)."""
    found = {s.get('content'): s for s in steps if isinstance(s, dict)}
    return [found.get(t.get('content'), {}) for t in todos]


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


def _ok_lists(calls):
    """(call, todos) of each ok TodoWrite of ``calls`` whose todos is a list of steps."""
    for call in calls:
        new = call.input.get('todos')
        if call.ok and isinstance(new, list) and all(isinstance(t, dict) for t in new):
            yield call, new


_UNREAD = object()


class Checklist:
    """The active command's checklist as the transcript records it. A plain
    class: importing dataclasses would cost the workflow gate, which reads the
    checklist at every tool call, more than the rest of its reading."""
    __slots__ = ('span', 'canonical', '_todos')

    def __init__(self, span, canonical, todos=_UNREAD):
        self.span = span              # command_span.Span of the command
        self.canonical = canonical    # its canonical steps (scripts/todo/<command>.py)
        self._todos = todos           # todos, once read (_UNREAD before)

    @property
    def todos(self):
        """The last ok TodoWrite's list (command_span's last_todos, read from
        the end of the span): the checklist the CLI holds, and the list the
        next TodoWrite is checked against; None before the first. Read when
        first asked: the readers that need only the command and its canonical
        steps leave it unread."""
        if self._todos is _UNREAD:
            self._todos = next((new for _call, new in _ok_lists(
                self.span.uses('TodoWrite', newest_first=True))), None)
        return self._todos

    @property
    def command(self):
        return self.span.command

    @property
    def arguments(self):
        return self.span.args

    @property
    def lock(self):
        """'not_started' while the span holds no ok TodoWrite, the workflow
        gate's one hold on other tools; else ''. pretool-todo-validate.py
        refuses a list that breaks a step rule before it runs, so an ok list is
        an accepted one."""
        return 'not_started' if self.todos is None else ''


def checklist(transcript_path):
    """The checklist of the command that opened the active span, or None when
    no harness command with a canonical checklist did. A PreToolUse reader's
    own call has no tool_result yet, so its list is not among the ok ones."""
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
    return Checklist(span, canonical)


def _bookmark_text(path, encoding):
    try:
        return path.read_text(encoding=encoding)
    except (OSError, ValueError):
        return None


def write_bookmark(path, update, encoding=None):
    """Write the workflow bookmark at ``path`` (<project>/.claude/workflow-<sid>.json).

    ``update`` gets the bookmark's text as it is now (None when there is no
    file it can read) and returns the text to put in its place, or None to
    leave the file as it is; what it raises reaches the caller with the file
    untouched. ``encoding`` is the text's on both sides (None: the locale's,
    as Path.read_text and write_text use).

    The text goes to a new file beside the bookmark that then replaces it
    (synced, then renamed), so a hook that reads the bookmark while another
    writes it sees the old bookmark or the new one, never a part of one. The
    PreToolUse workflow gate and the PostToolUse subagent tracker can write it
    in the same tool call and nothing serializes them (C1: no lock file): when
    another hook replaced the bookmark while this one synced its text,
    ``update`` runs again on that bookmark, so the window in which a write can
    undo another's is the one between that last read and the rename."""
    path = Path(path)
    current = _bookmark_text(path, encoding)
    for attempt in range(3):
        text = update(current)
        if text is None:
            return
        temporary = path.with_name(f'.{path.name}.tmp-{os.getpid()}-{os.urandom(8).hex()}')
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, 'w', encoding=encoding) as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            latest = _bookmark_text(path, encoding)
            if latest != current and attempt < 2:
                current = latest
                continue
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            return
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
