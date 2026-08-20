#!/usr/bin/env python3
"""
UserPromptSubmit Hook: Checklist Injection for Slash Commands

Phase A (slash command detected):
  - Runs scripts/todo/<command>.py to get the step list
  - Writes todos to Claude Code's official todos file
  - Writes {session_id, command} to .claude/workflow-{session_id}.json (bookmark only)
  - If /dev-overnight: creates overnight-state-<session_id>.json with parsed end-time
  - Prints checklist-ready message + exact first TodoWrite call to use

Phase B (subsequent prompts, no slash command):
  - If any overnight-state-*.json exists with future end_time: inject continuation
  - Reads official todos file for current session
  - Injects current progress + exact next TodoWrite call template

State: todos/{sid}.json + workflow-{sid}.json + overnight-state-{sid}.json
"""

import json
import os
import re
import secrets
import subprocess
import sys
import importlib.util
import time
import contextlib
import fcntl
import hashlib
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

# WS1: the shared claude_home resolver (this hook lives at <harness home>/hooks).
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
try:
    import claude_home  # noqa: E402
except Exception:  # pragma: no cover - fail-soft if lib missing
    claude_home = None  # type: ignore[assignment]


def _try_git_toplevel() -> Path | None:
    """Tier 4: git rev-parse --show-toplevel; None on failure."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            capture_output=True, text=True, timeout=2, check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass
    return None


def resolve_project_dir(stdin_payload: dict | None = None) -> Path:
    """Resolve project root via 5-tier fallback chain.

    Tiers: env CLAUDE_PROJECT_DIR -> stdin payload cwd -> os.getcwd ->
    git rev-parse --show-toplevel -> resolved harness home (WS1 final safety
    net, never the author literal /root).
    Tier 4 returns the worktree path when invoked from inside a worktree;
    this is intentional -- worktrees ARE per-project roots in /dev-overnight.
    """
    env_dir = os.environ.get('CLAUDE_PROJECT_DIR')
    if env_dir:
        return Path(env_dir)
    if stdin_payload and isinstance(stdin_payload, dict):
        payload_cwd = stdin_payload.get('cwd')
        if payload_cwd:
            return Path(payload_cwd)
    try:
        cwd = os.getcwd()
        if cwd:
            return Path(cwd)
    except (OSError, FileNotFoundError):
        pass
    git_top = _try_git_toplevel()
    if git_top is not None:
        return git_top
    # WS1: resolved harness home as the final safety net, not the literal /root.
    if claude_home is not None:
        home = claude_home.resolve()
        if home is not None:
            return home
    return Path.home()


# Module-level binding for backward compat (env+cwd+git+literal tiers;
# stdin-cwd tier is added inside main() after JSON parse).
PROJECT_DIR = resolve_project_dir()


def overnight_state_path(session_id: str = 'default') -> Path:
    """Path to the overnight state file (keyed by session_id for multi-session)."""
    return PROJECT_DIR / '.claude' / f'overnight-state-{session_id}.json'


def _is_active_state(state: dict) -> bool:
    """Return True if state has a future end_time.

    Fail closed: a missing, empty, non-string or unparseable end_time returns
    False, so a half-written state file never counts as a live session.

    'Z' is normalized to '+00:00' so a launcher-produced zoned end_time parses
    AWARE and is compared against an AWARE now(); a zone-less end_time stays
    naive-as-local. Previously the aware parse was compared against a naive
    datetime.now(), which raises TypeError on Python 3.11+, and the except
    clause below absorbed that TypeError into False -- so this predicate
    reported not-live for every real session, silently, since
    scripts/create-overnight-state.sh emits every end_time as
    %Y-%m-%dT%H:%M:%SZ. Same defect class as the sibling fix recorded at
    posttool-overnight-file-check.py:28-32.

    The caught set stays exactly {ValueError, TypeError}. Widening it -- which a
    str()-less copy of hooks/lib/overnight.py would need, to catch the
    AttributeError a non-string end_time raises -- would re-swallow a different
    class of fault; the isinstance guard rejects non-strings before parsing
    instead.
    """
    et = state.get('end_time')
    if not isinstance(et, str) or not et:
        return False
    try:
        end = datetime.fromisoformat(et.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return False
    if end.tzinfo is None:
        return end > datetime.now()
    return end > datetime.now(timezone.utc)


def find_any_overnight_state(session_id: str = '') -> tuple:
    """Return the live overnight state OWNED BY session_id, else (None, None).

    Strict identity binding: the record is resolved from the submitting
    session_id alone -- no project-wide glob and no fallback scan -- and the
    record's own session_id must equal that id before liveness is considered.
    A foreign, blank or absent id on either side injects nothing.

    Deliberately stricter than the posttool-overnight-loop.py:156-159 mirror,
    whose `if state_session_id and ...` guard still broadcasts a record carrying
    a blank/absent session_id to every session. The previous project-wide glob
    returned the first live match, so a second live session was served the first
    one's state, and any session -- including one with no overnight of its own --
    received the full continuation block.
    """
    if not isinstance(session_id, str) or not session_id:
        return None, None
    p = overnight_state_path(session_id)
    try:
        state = json.loads(p.read_text())
    except Exception:
        return None, None
    if not isinstance(state, dict) or state.get('session_id') != session_id:
        return None, None
    if not _is_active_state(state):
        return None, None
    return state, p


def extract_command_name(user_input: str) -> str:
    text = user_input.strip()
    if not text.startswith('/'):
        return ''
    parts = text.split()
    return parts[0][1:] if parts else ''


def official_todos_path(session_id: str) -> Path:
    return Path.home() / '.claude' / 'todos' / f'{session_id}-agent-{session_id}.json'


def workflow_bookmark_path(session_id: str) -> Path:
    return PROJECT_DIR / '.claude' / f'workflow-{session_id}.json'


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Publish complete bytes at ``path`` without exposing a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f'.{path.name}.tmp-{os.getpid()}-{hashlib.sha256(payload).hexdigest()[:16]}'
    )
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, 'wb', closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _atomic_write_json(path: Path, value: object) -> None:
    _atomic_write_bytes(
        path,
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8'),
    )


@contextlib.contextmanager
def _exclusive_lock(path: Path):
    """Serialize one Claude session only; independent sessions remain parallel."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _strip_yaml_frontmatter(content: str) -> str:
    """Strip YAML frontmatter from markdown content."""
    if not content.startswith('---'):
        return content
    end = content.find('\n---', 3)
    if end == -1:
        return content
    return content[end + 4:].lstrip('\n')


def _try_read_spec(path: Path) -> str | None:
    """Try to read a command spec file. Returns None on failure."""
    try:
        content = path.read_text()
        return _strip_yaml_frontmatter(content).strip()
    except Exception:
        return None


def _command_spec_candidates(cmd_name: str) -> list[Path]:
    """The paths read_command_spec searches, in its order.

    Extracted so the self-heal pointer can still name them when NONE of them
    resolves. A continuation block that carries neither the document nor a
    route to it is FM-1 with no mitigation left, so the pointer must degrade to
    "look in these places" rather than disappear.

    read_command_spec deliberately keeps its own copy of this list: it belongs
    to no single lane and rewriting it is outside this lane's permitted scope.
    test_candidate_list_matches_read_command_spec guards the two against drift.
    """
    return [
        PROJECT_DIR / '.claude' / 'commands' / f'{cmd_name}.md',
        Path.home() / '.claude' / 'commands' / f'{cmd_name}.md',
    ]


def read_command_spec(cmd_name: str) -> str:
    """Read the command .md file, stripping YAML frontmatter."""
    for search_path in [
        PROJECT_DIR / '.claude' / 'commands' / f'{cmd_name}.md',
        Path.home() / '.claude' / 'commands' / f'{cmd_name}.md',
    ]:
        if not search_path.exists():
            continue
        result = _try_read_spec(search_path)
        if result is not None:
            return result
    return ''


def resolve_command_spec_path(cmd_name: str) -> Path | None:
    """The file read_command_spec would read, resolved WITHOUT reading it.

    Same search order as read_command_spec above. Needed for two things that
    must not cost a 128 KB read on every prompt: the self-heal pointer printed
    in the light continuation payload, and the spec fingerprint. It diverges
    from read_command_spec only when the first candidate exists but cannot be
    read, where that function falls through to the second candidate.
    """
    for search_path in [
        PROJECT_DIR / '.claude' / 'commands' / f'{cmd_name}.md',
        Path.home() / '.claude' / 'commands' / f'{cmd_name}.md',
    ]:
        if search_path.exists():
            return search_path
    return None


def run_todo_script(cmd_name: str, user_input: str = "") -> list:
    todo_script = PROJECT_DIR / 'scripts' / 'todo' / f'{cmd_name}.py'
    if not todo_script.exists():
        global_todo = Path.home() / '.claude' / 'scripts' / 'todo' / f'{cmd_name}.py'
        if global_todo.exists():
            todo_script = global_todo
        else:
            return []
    # Forward the raw user prompt to the todo script via env var so
    # argument-aware scripts (e.g. spec.py) can distinguish modes.
    # Other todo scripts don't read this var; setting it is harmless.
    result = subprocess.run(
        ['python3', str(todo_script)],
        capture_output=True, text=True, cwd=str(PROJECT_DIR),
        env={**os.environ, "CLAUDE_TODO_PROMPT": user_input}
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        return json.loads(result.stdout)
    except Exception:
        return []


def _set_first_pending_ip(todos: list) -> None:
    """Set the first pending todo to in_progress."""
    for t in todos:
        if t.get('status') == 'pending':
            t['status'] = 'in_progress'
            break


def build_next_todowrite_call(todos: list, mark_first: bool = False) -> str:
    """Generate the JSON array to pass to TodoWrite."""
    if not todos:
        return ''
    result = [t.copy() for t in todos]
    if mark_first:
        result[0]['status'] = 'in_progress'
    elif not any(t.get('status') == 'in_progress' for t in result):
        _set_first_pending_ip(result)
    return json.dumps(result, ensure_ascii=False, separators=(",", ": "))


def build_completion_template(todos: list) -> str:
    """When a step is in_progress, generate template for after."""
    result = [t.copy() for t in todos]
    idx = next(
        (i for i, t in enumerate(result) if t.get('status') == 'in_progress'),
        None,
    )
    if idx is None:
        return json.dumps(result, ensure_ascii=False, separators=(",", ": "))
    result[idx]['status'] = 'completed'
    _set_first_pending_ip(result[idx + 1:])
    return json.dumps(result, ensure_ascii=False, separators=(",", ": "))


def build_sequence_fix_call(last_todos: list) -> str:
    """For sequence violations: compute correct next state."""
    if not last_todos:
        return ''
    try:
        result = [t.copy() for t in last_todos]
        idx = next(
            (i for i, t in enumerate(result) if t.get('status') == 'in_progress'),
            None,
        )
        if idx is not None:
            result[idx]['status'] = 'completed'
            _set_first_pending_ip(result[idx + 1:])
        else:
            _set_first_pending_ip(result)
        return json.dumps(result, ensure_ascii=False, separators=(",", ": "))
    except Exception:
        return ''


def format_count_mismatch(canonical: list) -> str:
    """Format locked message for count mismatch violations."""
    return '\n'.join([
        'WORKFLOW LOCKED (count_mismatch): TodoWrite called with wrong step count.',
        f'You MUST re-call TodoWrite with ALL {len(canonical)} canonical steps.',
        'Call TodoWrite with this exact todos array:', '',
        build_next_todowrite_call(canonical, mark_first=False),
    ])


def _find_current_step(todos: list) -> str:
    """Find the content of the current in_progress step."""
    ip = next((t for t in todos if t.get('status') == 'in_progress'), None)
    return ip["content"] if ip else "current step"


def format_sequence_violation(todos: list, last_todos: list) -> str:
    """Format locked message for sequence violations."""
    if last_todos:
        current = _find_current_step(last_todos)
        fix_json = build_sequence_fix_call(last_todos)
    else:
        current = _find_current_step(todos)
        fix_json = ''
    lines = [
        'WORKFLOW LOCKED (sequence_violation): Steps skipped or out of order.',
        f'REQUIRED: complete "{current}" first, then advance ONE step.',
        'Call TodoWrite to fix the sequence.',
    ]
    if fix_json:
        lines += ['', 'Call TodoWrite with this exact todos array:', '', fix_json]
    return '\n'.join(lines)


def format_active_progress(todos: list, ack: bool) -> str:
    """Format progress message for active (non-locked) workflow."""
    total = len(todos)
    done = sum(1 for t in todos if t.get('status') == 'completed')
    ip = next((t for t in todos if t.get('status') == 'in_progress'), None)
    lines = [f'ACTIVE WORKFLOW: {done}/{total} steps completed.']
    if ip:
        lines.append(f'Currently in_progress: {ip["content"]}')
    else:
        nxt = next((t for t in todos if t.get('status') == 'pending'), None)
        if nxt:
            lines.append(f'Next step: {nxt["content"]}')
    if ack:
        return '\n'.join(lines)
    lines.append('')
    if ip:
        lines.append('Complete the work, THEN call TodoWrite with this array:')
        lines.append('')
        lines.append(build_completion_template(todos))
    else:
        lines.append('Call TodoWrite NOW with this array (pass as array, NOT string):')
        lines.append(build_next_todowrite_call(todos, mark_first=False))
    return '\n'.join(lines)


def format_progress(
    todos: list, lock_reason: str = '', canonical: list = None,
    todo_acknowledged: bool = False, last_todos: list = None,
) -> str:
    """Phase B: show current progress. Dispatches to formatters."""
    if lock_reason == 'count_mismatch' and canonical:
        return format_count_mismatch(canonical)
    if lock_reason == 'sequence_violation':
        return format_sequence_violation(todos, last_todos or [])
    return format_active_progress(todos, todo_acknowledged)


# --- Overnight helpers ---

def _strip_spec_arg(args: str) -> tuple[str, str]:
    """Pull --spec/—spec/–spec from args; return (remaining_args, spec_path)."""
    spec_match = re.search(r'(?:--|[–—])spec\s+(\S+)', args)
    if not spec_match:
        return args, ''
    spec_path = spec_match.group(1)
    remaining = args[:spec_match.start()].rstrip() + ' ' + args[spec_match.end():].lstrip()
    return remaining.strip(), spec_path


def _match_end_time_token(args: str) -> tuple[str, str]:
    """Match leading end-time token (Nh / N.Mh / Nm / +Nh / HH:MM[ AM|PM])."""
    bare_match = re.match(r'^(\d+(?:\.\d+)?[hm])\s*(.*)', args)
    if bare_match:
        return f'+{bare_match.group(1).strip()}', bare_match.group(2).strip()
    rel_match = re.match(r'^(\+\d+(?:\.\d+)?[hm])\s*(.*)', args)
    if rel_match:
        return rel_match.group(1).strip(), rel_match.group(2).strip()
    if args.startswith('+'):
        bad = args.split(None, 1)[0]
        rest = args[len(bad):].lstrip()
        return f'INVALID:{bad}', rest
    time_match = re.match(r'^(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)\s*(.*)', args)
    if time_match:
        return time_match.group(1).strip(), time_match.group(2).strip()
    return '', args


def parse_overnight_args(prompt_text: str) -> tuple[str, str, str, bool, str]:
    """Extract end-time, focus, spec path, codex flag, and isolation choice.

    Returns (end_time_raw, focus_string, spec_path, codex_required,
    worktree_choice). M4 (harness-fixes 20260428): now also recognizes
    +Nh / +N.Mh / +Nm relative-time tokens; an unknown +token returns
    INVALID:<token> so the bash layer can surface an explicit error rather than
    silently defaulting to +8h. Spec dash-form tolerance unchanged (-- / — / –).
    M5 (2026-05-15): extracts --codex boolean flag and returns it as 4th element.

    2026-08-08: extracts the isolation choice as the 5th element. Both flags are
    passed through verbatim rather than resolved here — 'both given' is a user
    error the launcher refuses, and collapsing it to one value in this layer
    would hide the conflict instead of surfacing it. '' means neither flag was
    given, which the launcher resolves to in-place.
    """
    match = re.search(r'/dev-overnight\s+(.*)', prompt_text.strip())
    args = match.group(1).strip() if match else ''
    # Extract --codex flag (boolean toggle, no value)
    codex_required = '--codex' in args.split()
    args = re.sub(r'\s*--codex\b', '', args).strip()
    # Extract the isolation flags. --no-worktree is matched FIRST: '--worktree'
    # is a proper substring of '--no-worktree', so a \b-anchored --worktree scan
    # over the raw string would also fire on --no-worktree and report both.
    tokens = args.split()
    want_worktree = '--worktree' in tokens
    want_no_worktree = '--no-worktree' in tokens
    if want_worktree and want_no_worktree:
        worktree_choice = 'conflict'
    elif want_worktree:
        worktree_choice = 'worktree'
    elif want_no_worktree:
        worktree_choice = 'no-worktree'
    else:
        worktree_choice = ''
    args = re.sub(r'\s*--no-worktree\b', '', args)
    args = re.sub(r'\s*--worktree\b', '', args).strip()
    args, spec_path = _strip_spec_arg(args)
    if not args:
        return '', '', spec_path, codex_required, worktree_choice
    end_time, focus = _match_end_time_token(args)
    return end_time, focus, spec_path, codex_required, worktree_choice


def create_overnight_state(end_time: str, focus: str = '', spec_path: str = '', session_id: str = 'default', codex_required: bool = False, worktree_choice: str = '') -> bool:
    """Create overnight state file by calling the bash script."""
    script = Path.home() / '.claude' / 'scripts' / 'create-overnight-state.sh'
    cmd = [str(script)]
    if end_time:
        cmd += ['--end-time', end_time]
    if focus:
        cmd += ['--focus', focus]
    if spec_path:
        cmd += ['--spec', spec_path]
    if codex_required:
        cmd += ['--codex']
    # Forward the isolation choice verbatim, including the conflict case: the
    # launcher owns the refusal so the error text lives in exactly one place.
    # '' forwards nothing, and the launcher defaults to in-place.
    if worktree_choice == 'conflict':
        cmd += ['--worktree', '--no-worktree']
    elif worktree_choice == 'worktree':
        cmd += ['--worktree']
    elif worktree_choice == 'no-worktree':
        cmd += ['--no-worktree']
    cmd += ['--session-id', session_id]
    cmd += ['--project-dir', str(PROJECT_DIR)]
    try:
        # M5/AC4: raise the timeout from 10s to >=60s — worktree creation +
        # validation + launch self-test legitimately take longer than 10s.
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
            return False
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)
        return True
    except Exception as exc:
        print(f'overnight state creation failed: {exc}', file=sys.stderr)
        return False


def load_overnight_state(session_id: str = '') -> dict | None:
    """Load overnight state file. Returns None if missing or corrupt."""
    sp = overnight_state_path(session_id)
    if not sp.exists():
        return None
    try:
        return json.loads(sp.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _build_worktree_instruction(state: dict) -> str:
    """Build worktree guard instruction based on state.

    M5/round-3: a validated worktree is a launch PRECONDITION. The instruction
    NEVER tells the agent to call EnterWorktree, and a missing/invalid worktree
    is a HARD ABORT (the launcher refuses to write such a state, so this branch
    should be unreachable for a properly-launched session).
    """
    wt = state.get('worktree_path')
    # In-place mode (the user did not pass --worktree): there is no worktree to
    # enter and nothing to cd into. The actor still carries the overnight marker
    # so the keystone stays armed on the protected branch, but the policy shim is
    # deliberately absent — wiring it would deny every git op, since in-place
    # work IS main-targeting by definition (git-policy-shim:179-182).
    if state.get('isolation_kind') == 'in_place':
        branch = state.get('worktree_branch', '') or '<current branch>'
        actor_env = state.get('actor_git_env') or {}
        helper = actor_env.get('env_helper') if isinstance(actor_env, dict) else None
        main_root = state.get('main_root', '')
        base = (
            f'IN-PLACE MODE: no worktree was created. Work directly in {wt} on '
            f'branch "{branch}". Do NOT call EnterWorktree and do NOT create a '
            'worktree. '
        )
        if helper:
            # Sourced per command, not once: a fresh shell per Bash call means a
            # one-time export lapses and the keystone stops applying.
            base += (
                f'At the START OF EVERY command that runs git, source the '
                f'marker-only actor env: `source "{helper}" --main-root '
                f'"{main_root}"`. It exports CLAUDE_OVERNIGHT_ACTOR=1 and '
                'deliberately does NOT set CLAUDE_OVERNIGHT_MAIN_ROOT — setting '
                'that would arm the policy shim, which denies every git command '
                'in this mode. '
            )
        else:
            base += (
                'Export CLAUDE_OVERNIGHT_ACTOR=1 in every shell that runs git '
                '(do NOT set CLAUDE_OVERNIGHT_MAIN_ROOT — that would arm the '
                'policy shim and deny every git command in this mode). '
            )
        base += f'Never commit to the protected branch "{state.get("protected_branch", "")}".'
        return base
    if wt is not None and wt != '':
        # fix-1 (Cycle-2): also mandate sourcing + verifying the actor git-env so
        # the harness-owned policy shim is the actor's `git` and
        # CLAUDE_OVERNIGHT_ACTOR=1 is set in the actor runtime (defense in depth;
        # the PreTool hook-guard is the authoritative live-state-derived block).
        actor_env = state.get('actor_git_env') or {}
        env_helper = actor_env.get('env_helper') if isinstance(actor_env, dict) else None
        shim_git = actor_env.get('shim_git') if isinstance(actor_env, dict) else None
        main_root = state.get('main_root', '')
        base = (
            f'CRITICAL: The validated isolated worktree is {wt}. '
            'cd into it. DO NOT call EnterWorktree under any circumstances.'
        )
        if env_helper:
            base += (
                f' Then source the actor git-env: `source "{env_helper}" '
                f'--main-root "{main_root}" --worktree "{wt}"` and VERIFY '
                f'`command -v git` == "{shim_git}" and `git rev-parse '
                f'--show-toplevel` == "{wt}". Never run git against the main '
                'working directory; never strip CLAUDE_OVERNIGHT_ACTOR.'
            )
        return base
    return (
        'HARD ABORT. The overnight state has no validated worktree. '
        'Do not create state manually. Do not call EnterWorktree. '
        'Do not continue on the current branch or main project path.'
    )


def _load_overnight_todos() -> list[dict]:
    todo_path = Path(
        os.environ.get(
            'CLAUDE_DEV_OVERNIGHT_TODO',
            str(Path.home() / '.claude' / 'scripts' / 'todo' / 'dev-overnight.py'),
        )
    )
    try:
        spec = importlib.util.spec_from_file_location('dev_overnight_todo', todo_path)
        if spec is None or spec.loader is None:
            return []
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        todos = module.get_todos()
    except Exception:
        return []
    return [item for item in todos if isinstance(item, dict)]


# --- Overnight continuation delivery cadence ---
#
# The continuation block carries two content classes whose natural cadences
# differ by orders of magnitude:
#
#   heavy  commands/dev-overnight.md -- 128,288 of 130,785 chars (98.09%,
#          measured 2026-08-09). Changes only when that file is edited on
#          disk, i.e. essentially never inside a running session.
#   light  state summary + continuation instructions + phase->step map --
#          2,497 chars. Changes WITHIN every cycle: current_phase advances
#          through 8 values, and issues_fixed/current_issues/cycle_log mutate.
#
# Emitting both on every non-slash prompt applied the MOST frequent cadence to
# the LEAST frequently changing content. That inversion is the defect. The
# light half stays unconditional -- withholding it would make a resuming
# orchestrator route from the phase that was current at the last cycle
# boundary and re-run the pipeline on an already-implemented issue -- and the
# heavy half is gated on a delivery marker.
#
# Reading R-b is in force: a context reset, observed as a compaction record
# appended to the session transcript, RE-DELIVERS the heavy half. The marker
# is durable *storage* that survives a context reset as a file (a marker held
# in context would be destroyed by the very event it must remember across),
# but its validity key deliberately does not survive the reset itself: the
# marker models "the orchestrator still holds this document in context", and
# compaction is precisely the event that falsifies that model. R-a is the
# strict subset -- set this constant to 'R-a' and the transcript_offset term
# drops out of the validity key with no other change. The reading is recorded
# in every marker written, so it is readable from the artifact rather than
# inferred from behaviour.
OVERNIGHT_EPOCH_READING = 'R-b'

# The one string that proves the heavy half reached stdout (see
# commit_overnight_delivery).
OVERNIGHT_SPEC_HEADER = '--- COMMAND SPECIFICATION ---'

# transcript_path as delivered on the UserPromptSubmit payload; threaded by
# main(). Empty when this module is driven by a caller that has no payload.
CURRENT_TRANSCRIPT_PATH = ''


def overnight_delivery_marker_path(state_path: Path, session_id: str) -> Path:
    """Marker location: BESIDE the overnight state record it describes.

    Deliberately derived from the state file's own directory rather than
    recomputed from PROJECT_DIR. The marker is only ever consulted for a
    session whose state record was just read out of that directory, and
    posttool-overnight-loop.py must write cycle_count back into that same file
    for the loop to advance at all. Any deployment in which this marker cannot
    be written is therefore one in which the overnight session is already
    broken for an unrelated reason -- which is the strongest writability
    guarantee available on this path. Where it does not hold, _marker_writable
    makes the failure visible instead of silently costing the whole saving.
    """
    return state_path.with_name(f'overnight-delivery-{session_id}.json')


def _marker_writable(path: Path) -> bool:
    """Non-mutating probe: can the marker actually be persisted here?

    Creates nothing. A read-only bind mount -- the isolation mode that broke a
    sibling lane's launch-time writes under exactly this project layout --
    fails access(W_OK) with EROFS, so this catches the one failure that would
    otherwise make the entire cadence saving silently zero: every prompt
    re-delivers the heavy payload, the hook still exits 0, and every hermetic
    test still passes because each builds its own writable fixture.

    An existing NON-FILE at the marker path counts as unwritable: os.replace
    onto a directory always fails, so the cadence really is inactive and the
    condition must be announced rather than merely retried forever.
    """
    try:
        if path.exists():
            return path.is_file() and os.access(path, os.W_OK)
        return os.access(path.parent, os.W_OK)
    except Exception:
        return False


def _resolve_transcript_path(session_id: str) -> str:
    """Locate the session transcript, or '' when it cannot be resolved.

    The UserPromptSubmit payload's transcript_path is AUTHORITATIVE and is
    threaded by main() into CURRENT_TRANSCRIPT_PATH; it is already consumed in
    production at hooks/userprompt-restart-authorize.py:27.

    The store scan below is only a fallback for direct callers that have no
    payload. It is deliberately NOT the primary: transcript files are keyed by
    session id ($HOME/.claude/projects/<mangled-cwd>/<session_id>.jsonl, which
    was verified -- file stem == the record's sessionId), but $HOME/.claude is
    a symlink to the repository root in this harness, so the scan reads a
    SECONDARY store while the account's live store is elsewhere. Measured: the
    live overnight session's own transcript is absent from the scanned tree.
    Relying on the scan would therefore have degraded reading R-b to R-a
    silently, which is the one outcome this lane must not produce.

    Returning '' degrades THIS SESSION to reading R-a rather than failing, and
    the empty value is written into the marker so the degradation is visible
    in the artifact instead of having to be inferred from behaviour.
    """
    if CURRENT_TRANSCRIPT_PATH:
        return CURRENT_TRANSCRIPT_PATH
    if not isinstance(session_id, str) or not session_id:
        return ''
    try:
        for project_dir in (Path.home() / '.claude' / 'projects').iterdir():
            candidate = project_dir / f'{session_id}.jsonl'
            if candidate.exists():
                return str(candidate)
    except Exception:
        return ''
    return ''


def _transcript_size(transcript_path: str) -> int:
    """Byte offset to resume the compaction scan from. 0 when unknown."""
    if not transcript_path:
        return 0
    try:
        return Path(transcript_path).stat().st_size
    except Exception:
        return 0


def _transcript_inode(transcript_path: str) -> int:
    """Identity of the transcript FILE, not merely its path.

    A context reset that replaces the transcript with a fresh file at the same
    path leaves transcript_path equal and can leave the size >= the recorded
    offset, so neither of those two terms would notice. The inode changes.
    Stable across appends, so it does not churn. 0 when unknown.
    """
    if not transcript_path:
        return 0
    try:
        return Path(transcript_path).stat().st_ino
    except Exception:
        return 0


def _compaction_since(transcript_path: str, offset: object) -> bool:
    """True if a compaction record was appended since ``offset``.

    Compaction APPENDS an isCompactSummary record to the same transcript and
    preserves session_id, so only [offset, EOF) needs inspecting: the cost is
    proportional to bytes written since the last delivery, not to the
    multi-megabyte transcript. Fail-safe: every doubt (missing file, shrunken
    file, unusable offset, read error) returns True, which RE-DELIVERS.

    The substring gate is only an optimization. A record is confirmed by
    parsing it, so an ordinary prompt that merely grew the transcript -- even
    one quoting the token -- does not count as an epoch change.
    """
    if not transcript_path:
        return False
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        return True
    try:
        path = Path(transcript_path)
        size = path.stat().st_size
        if size < offset:
            return True
        if size == offset:
            return False
        with path.open('rb') as handle:
            handle.seek(offset)
            appended = handle.read()
    except Exception:
        return True
    if b'isCompactSummary' not in appended:
        return False
    for line in appended.splitlines():
        try:
            record = json.loads(line)
        except Exception:
            continue
        if isinstance(record, dict) and record.get('isCompactSummary'):
            return True
    return False


def _spec_fingerprint(cmd_name: str = 'dev-overnight') -> str:
    """Cheap identity for the spec file: size + mtime, never a 128 KB re-read.

    A touch with no content change re-delivers once. That is the fail-safe
    direction and is preferred to paying a full content hash on every prompt.
    """
    path = resolve_command_spec_path(cmd_name)
    if path is None:
        return ''
    try:
        stat_result = path.stat()
    except Exception:
        return ''
    return f'{stat_result.st_size}:{stat_result.st_mtime_ns}'


def _read_delivery_marker(path: Path) -> dict | None:
    """Read the marker, or None for absent/unreadable/malformed/non-object."""
    try:
        record = json.loads(path.read_text())
    except Exception:
        return None
    return record if isinstance(record, dict) else None


def _marker_suppresses_spec(marker: object, session_id: str, state: dict,
                            transcript_path: str, fingerprint: str) -> bool:
    """Exact match on all four validity fields, or deliver.

    Fail-safe polarity is the load-bearing property of this whole lane:
    absent, unreadable, malformed, non-object, field-missing,
    session-mismatched, cycle-mismatched, epoch-changed and
    fingerprint-changed markers ALL fall through to False, i.e. deliver.
    There is no code path in which an anomaly suppresses. Guarded here rather
    than by main()'s outer handler, which drops the block entirely -- that is
    the failure this lane exists to remove, not a fallback.

    Session binding is two-factor: the filename is keyed by session_id AND the
    record's own session_id must equal the submitting id, so a marker cannot
    be consumed by a session it was not written for.

    bool is rejected explicitly because bool is an int subclass in Python and
    True == 1 would otherwise satisfy a cycle_count comparison.
    """
    if not isinstance(marker, dict) or not session_id:
        return False
    if marker.get('session_id') != session_id:
        return False
    recorded = marker.get('cycle_count')
    current = state.get('cycle_count', 0)
    for value in (recorded, current):
        if not isinstance(value, int) or isinstance(value, bool):
            return False
    if recorded != current:
        return False
    if marker.get('spec_fingerprint') != fingerprint:
        return False
    if marker.get('transcript_path') != transcript_path:
        return False
    # A marker written under a DIFFERENT epoch reading must not be honoured
    # under this one: flipping the constant to descope R-b -> R-a (or back)
    # changes what the marker means, and an absent field means the marker was
    # not written by this implementation at all.
    if marker.get('epoch_reading') != OVERNIGHT_EPOCH_READING:
        return False
    if OVERNIGHT_EPOCH_READING == 'R-b':
        if marker.get('transcript_inode') != _transcript_inode(transcript_path):
            return False
        if _compaction_since(transcript_path, marker.get('transcript_offset')):
            return False
    return True


def commit_overnight_delivery(session_id: str, emitted: str) -> bool:
    """Record that the heavy payload was delivered -- AFTER it was emitted.

    Write-after-emit is the single ordering constraint in this design. A
    marker written first would claim a delivery that never happened, and
    unlike a stale marker that failure does NOT self-heal within the cycle:
    the marker stays valid, so every later prompt suppresses and the session
    stalls until the next cycle advance. The emitted text is therefore the
    evidence -- no spec header in it, no marker -- and the cycle number is
    re-read from that same text so a state file that moved between the
    decision and the write cannot cause a marker to be recorded against a
    cycle whose spec was never sent.

    Returns True only when a marker was written. Every failure is swallowed
    deliberately: an unwritten marker merely re-delivers on the next prompt,
    which is the fail-safe direction.
    """
    if OVERNIGHT_SPEC_HEADER not in emitted:
        return False
    state, state_path = find_any_overnight_state(session_id)
    if state is None:
        return False
    cycle = state.get('cycle_count', 0)
    if not isinstance(cycle, int) or isinstance(cycle, bool):
        return False
    if f'OVERNIGHT CONTINUATION - Cycle {cycle + 1}' not in emitted:
        return False
    transcript_path = _resolve_transcript_path(session_id)
    try:
        _atomic_write_json(
            overnight_delivery_marker_path(state_path, session_id),
            {
                'session_id': session_id,
                'cycle_count': cycle,
                'spec_fingerprint': _spec_fingerprint(),
                'transcript_path': transcript_path,
                'transcript_offset': _transcript_size(transcript_path),
                'transcript_inode': _transcript_inode(transcript_path),
                'epoch_reading': OVERNIGHT_EPOCH_READING,
                'delivered_at': datetime.now(timezone.utc).strftime(
                    '%Y-%m-%dT%H:%M:%SZ'
                ),
            },
        )
    except Exception:
        return False
    return True


def build_overnight_continuation(state: dict, include_spec: bool = True,
                                 notice: str = '') -> str:
    """Build continuation context for overnight loop prompts.

    include_spec=False emits the light half only: identical text minus the
    command specification and its header. The light half's own content is
    unchanged apart from the self-heal pointer, which names the resolved spec
    path so an orchestrator that has lost the document can recover it with one
    read instead of stalling.
    """
    cc = state.get('cycle_count', 0)
    phase = state.get('current_phase', 'unknown')
    log = state.get('cycle_log', [])
    last_entry = log[-1] if log else None
    last = f"Cycle {last_entry.get('cycle')}: {last_entry.get('status')}" if last_entry else 'N/A'
    spec_path = resolve_command_spec_path('dev-overnight')
    # Read the 128 KB document only when it is actually going to be emitted.
    cmd_spec = read_command_spec('dev-overnight') if include_spec else ''
    wt_instruction = _build_worktree_instruction(state)
    overnight_todos = _load_overnight_todos()
    step_count = len(overnight_todos) or 22
    step_labels = '; '.join(str(item.get('content', '')) for item in overnight_todos)
    parts = [f'OVERNIGHT CONTINUATION - Cycle {cc + 1}', '']
    if include_spec:
        parts += [OVERNIGHT_SPEC_HEADER, '', cmd_spec, '']
    parts += [
        '--- CURRENT STATE ---', '',
        f'Phase: {phase} | Cycles: {cc} | Fixed: {state.get("issues_fixed", 0)}',
        f'End time: {state.get("end_time")} | Active issues: {len(state.get("current_issues", []))}',
        f'Focus: {state.get("focus", "none")}',
        f'Last cycle: {last}', '',
        '--- CONTINUATION INSTRUCTIONS ---', '',
        'You are continuing an overnight session with FRESH context.',
        wt_instruction,
        f'Loop is driven by todo completion detection -- when all {step_count} steps complete,',
        'the system automatically resets for a new cycle.',
        f'Canonical steps: {step_labels}',
        'Do NOT create state file.',
        f'Read .claude/overnight-state-{state.get("session_id", "default")}.json and resume from phase="{phase}".',
        # Phase->step map MUST match the markdown Continuation-Mode map in
        # commands/dev-overnight.md (### Continuation Mode), the single source of
        # truth. implementing->Step 12 lands on the shared Step 11g Dev-dispatch
        # precondition, which enriches before Dev on resume.
        'Phase mapping: initializing/exploring->Step 2, pipeline_creation->Step 6,',
        'analyzing->Step 8, implementing->Step 12, verifying->Step 14,',
        'iterating->Step 17, logging->Step 19, retrospective->Step 20',
    ]
    # Self-heal pointer: the resolved path, never a hard-coded literal -- a
    # wrong path makes this mitigation worse than absent. It is the entire
    # recovery route for a context reset that the epoch check does not catch
    # (a rebuilt-from-truncated-transcript resume), so it rides on EVERY
    # prompt, not only the light ones.
    if spec_path is not None:
        parts.append(
            f'Command specification: {spec_path} -- READ that file now if the '
            '/dev-overnight specification is not already in your context.'
        )
    if notice:
        parts += ['', notice]
    return '\n'.join(parts)


def check_overnight_continuation(session_id: str = '') -> str | None:
    """Check whether the submitting session's OWN overnight record needs continuation.

    The heavy half is emitted only when the delivery marker does not exactly
    match this (session, cycle, context epoch, spec fingerprint). The light
    half is unconditional: current_phase drives the phase->step routing map
    and advances several times inside a single cycle, so withholding it would
    strand a resuming orchestrator on stale routing -- worse than paying for a
    fresh block.
    """
    state, state_path = find_any_overnight_state(session_id)
    if state is None:
        return None
    registry_notice = _repair_overnight_registry(session_id)
    marker_path = overnight_delivery_marker_path(state_path, session_id)
    suppress = _marker_suppresses_spec(
        _read_delivery_marker(marker_path), session_id, state,
        _resolve_transcript_path(session_id), _spec_fingerprint(),
    )
    notice = registry_notice
    if not suppress and not _marker_writable(marker_path):
        # Degraded: without a persistable marker the heavy half is re-sent on
        # every prompt and the saving is exactly zero. Say so, on every prompt,
        # rather than let a read-only path silently cost the whole benefit.
        # Appended, never assigned: notice already carries any registry
        # finding, and a marker problem must not erase an enforcement one.
        notice = '\n\n'.join(filter(None, (notice, (
            f'NOTE: the delivery marker cannot be written at {marker_path} '
            '(path unwritable). The command specification above will be '
            're-sent on EVERY prompt until that path is writable -- '
            'continuation-block cadence bounding is INACTIVE for this session.'
        ))))
    return build_overnight_continuation(
        state, include_spec=not suppress, notice=notice
    )


# --- Main entry points ---

def read_bookmark_state(session_id: str) -> dict:
    """Read lock state and todo_acknowledged from bookmark file."""
    bookmark = workflow_bookmark_path(session_id)
    r = {
        'lock_reason': '', 'todo_acknowledged': False,
        'canonical': [], 'last_todos': [], 'command': '',
    }
    if not bookmark.exists():
        return r
    try:
        st = json.loads(bookmark.read_text())
    except Exception:
        return r
    r['lock_reason'] = st.get('lock_reason', '')
    r['todo_acknowledged'] = st.get('todo_acknowledged', False)
    r['command'] = st.get('command', '')
    if r['lock_reason'] == 'count_mismatch' and r['command']:
        # Forward stored arguments so the count-mismatch recovery hint
        # reflects the correct (e.g. --force 2-step) canonical list.
        r['canonical'] = run_todo_script(r['command'], st.get('arguments', ''))
    if r['lock_reason'] == 'sequence_violation':
        r['last_todos'] = st.get('last_todos', [])
    return r


def handle_phase_b(session_id: str) -> None:
    """Phase B: inject overnight continuation and/or workflow progress."""
    overnight_ctx = check_overnight_continuation(session_id)
    if overnight_ctx:
        print(overnight_ctx)
        # M6a: the marker records that a delivery HAPPENED, so it is written
        # only once the emission has actually completed. Flush first -- a
        # buffered write that fails at interpreter shutdown would otherwise
        # leave a marker claiming a delivery that never reached the agent.
        sys.stdout.flush()
        recorded = commit_overnight_delivery(session_id, overnight_ctx)
        if OVERNIGHT_SPEC_HEADER in overnight_ctx and not recorded:
            # The pre-emission probe can pass while the write still fails (an
            # immutable attribute, a full filesystem, a state file that moved).
            # Without this line that case is indistinguishable from a normal
            # first delivery and the saving silently never materializes.
            print('NOTE: the overnight delivery marker was not recorded; the '
                  'command specification will be re-sent on the next prompt.')
    todos_file = official_todos_path(session_id)
    if not todos_file.exists():
        return
    try:
        todos = json.loads(todos_file.read_text())
    except Exception:
        return
    if not todos:
        return
    if all(t.get('status') == 'completed' for t in todos):
        return
    bm = read_bookmark_state(session_id)
    print(format_progress(
        todos, lock_reason=bm['lock_reason'], canonical=bm['canonical'],
        todo_acknowledged=bm['todo_acknowledged'], last_todos=bm['last_todos'],
    ))


def checklist_message(cmd_name: str, todos: list) -> str:
    """Build the checklist initialization message with command spec."""
    first_call = build_next_todowrite_call(todos, mark_first=True)
    lines = [
        f'CHECKLIST PRE-INITIALIZED for /{cmd_name.upper()}:',
        f'Your workflow checklist ({len(todos)} steps) has been created.',
        '',
        'Each item: {"content": "...", "activeForm": "...", "status": "..."}',
        f'FIRST ACTION: call TodoWrite with the todos array below:',
        f'(you MUST pass ALL {len(todos)} items every TodoWrite call)',
        '',
        first_call,
    ]
    spec = read_command_spec(cmd_name)
    if spec:
        lines += ['', f'--- /{cmd_name} COMMAND SPECIFICATION ---', '', spec]
    return '\n'.join(lines)


def emit_checklist_message(cmd_name: str, todos: list) -> None:
    print(checklist_message(cmd_name, todos))


def _warn_workflow_conflict(old_cmd: str, new_cmd: str, old_todos: list) -> None:
    """Emit warning to stderr when active workflow is being replaced (E17)."""
    incomplete = sum(1 for t in old_todos if t.get('status') != 'completed')
    sys.stderr.write(
        f'\nWARNING: Replacing active /{old_cmd} workflow ({incomplete} '
        f'incomplete steps) with /{new_cmd}.\n'
        f'The previous workflow state will be lost.\n\n'
    )


def _check_workflow_conflict(cmd_name: str, sid: str) -> None:
    """Check if an active workflow exists and warn before replacement (E17)."""
    bm_path = workflow_bookmark_path(sid)
    if not bm_path.exists():
        return
    try:
        bm = json.loads(bm_path.read_text())
    except Exception:
        return
    old_cmd = bm.get('command', '')
    if not old_cmd or old_cmd == cmd_name:
        return
    tf = official_todos_path(sid)
    if not tf.exists():
        return
    try:
        old_todos = json.loads(tf.read_text())
    except Exception:
        return
    if not old_todos or all(t.get('status') == 'completed' for t in old_todos):
        return
    _warn_workflow_conflict(old_cmd, cmd_name, old_todos)


def _mint_unique_do_taskid() -> str:
    """Mint a globally-unique pure-timestamp task-id (YYYYMMDD-HHMMSS) for a /do
    invocation, reserved ATOMICALLY across ALL sessions via a flat O_EXCL marker
    `/tmp/claude-do-resv-<ts>` so two concurrent /do invocations — even in the same
    wall-clock second — can never mint the same id. Pure-timestamp form keeps
    /close + /commit task-id resolution compatible (no nonce suffix that /close's
    timestamp-pattern branch might reject). The flat /tmp marker is reachable by the
    maxdepth-1 /tmp sweep AND self-pruned here. The ONLY non-reserved return path is
    an unwritable /tmp (OSError) — but there the sidecar AND do-report writes fail
    too, so no artifact is produced and a collision on the id is moot."""
    base = datetime.now()
    # Opportunistic prune — a marker only matters for the ~1s it guards (mint
    # always scans forward from `now`), so markers older than 5 min are pure debris.
    # Pruning markers strictly older than the cutoff cannot race a concurrent mint
    # (which reserves at-or-after its own `now`). Best-effort.
    try:
        cutoff = base.timestamp() - 300
        for _m in Path("/tmp").glob("claude-do-resv-*"):
            try:
                if _m.is_file() and _m.stat().st_mtime < cutoff:
                    _m.unlink()
            except OSError:
                pass
    except OSError:
        pass
    for i in range(300):  # forward-bump on contention; 300 distinct seconds
        ts = (base + timedelta(seconds=i)).strftime("%Y%m%d-%H%M%S")
        try:
            fd = os.open(f"/tmp/claude-do-resv-{ts}", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            return ts
        except FileExistsError:
            continue  # this second already reserved by another mint -> bump forward
        except OSError:
            # /tmp unwritable: sidecar + do-report writes will also fail, so an
            # unreserved id here is moot (no artifact is produced). Return it.
            return ts
    # 300 consecutive seconds all reserved — unreachable in practice. FAIL CLOSED
    # rather than return an already-reserved (colliding) id: handle_do_consent's
    # try/except then skips the sidecar, and the agent's own atomic fallback mints one.
    raise RuntimeError("unable to reserve a unique /do task-id after 300 probes")


def handle_do_consent(sid: str) -> None:
    """Handle /do command: write the consent flag, mint a unique per-invocation
    task-id, and write a session-keyed task sidecar so the agent can resolve ITS
    OWN task-id deterministically. Fixes the silent cross-task collision where the
    agent guessed its id via `ls -t /tmp/...consent-*.flag | head -1` (globally
    newest) — which aliased parallel /do sessions onto one id and overwrote each
    other's do-reports."""
    flag = Path(f"/tmp/claude-orchestrator-consent-{sid}.flag")
    try:
        flag.write_text("true")
        print(f"[/do] Consent granted. Main agent may now perform direct operations this session.")
    except Exception as e:
        sys.stderr.write(f"[/do] Failed to write consent flag: {e}\n")
    # Mint a unique task-id and expose it via a session-keyed sidecar. Kept
    # SEPARATE from the consent flag (the orchestrator-gate trust root, whose
    # content stays "true" so every existence-checking reader is unaffected).
    try:
        task_id = _mint_unique_do_taskid()
        sidecar = Path(f"/tmp/claude-do-task-{sid}.json")
        sidecar.write_text(json.dumps({
            "task_id": task_id,
            "session_id": sid,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }))
        print(f"[/do] task-id minted: {task_id} — resolve via $CLAUDE_CODE_SESSION_ID → /tmp/claude-do-task-<sid>.json (NOT `ls -t | head -1`).")
    except Exception as e:
        sys.stderr.write(f"[/do] Failed to write task sidecar: {e}\n")


def _write_userintent_sentinel(cmd_name: str, sid: str) -> None:
    """Write sid-keyed user-intent sentinel. Mirrors /allow pattern: both
    writer (this hook) and reader (pretool-wrapper-userintent.py PreToolUse
    hook) resolve sid from stdin JSON, so sid-keying round-trips correctly.
    Single-use; consumed by the PreToolUse hook before the wrapper runs."""
    try:
        Path(f"/tmp/claude-{cmd_name}-userintent-{sid}.flag").write_text("true")
    except OSError:
        pass


def _dev_clock() -> datetime:
    """Return the allocator clock, optionally fixed by an isolated test fixture."""
    injected = os.environ.get('CLAUDE_DEV_CLOCK_ISO', '').strip()
    if injected:
        parsed = datetime.fromisoformat(injected.replace('Z', '+00:00'))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    return datetime.now()


def _reserve_dev_registry(cmd_name: str, project_dir: Path) -> tuple[str, Path]:
    """Atomically reserve a pure-timestamp task family without a global lock."""
    prefix = 'dev-command' if cmd_name == 'dev-command' else 'dev'
    parent = project_dir / '.claude' / 'dev-registry'
    parent.mkdir(parents=True, exist_ok=True)
    base = _dev_clock().replace(microsecond=0)
    for offset in range(86400):
        task_id = f"{prefix}-{(base + timedelta(seconds=offset)).strftime('%Y%m%d-%H%M%S')}"
        requirement = project_dir / 'docs' / 'dev' / f'user-requirement-{task_id}.md'
        if requirement.exists():
            continue
        directory = parent / task_id
        try:
            directory.mkdir()
        except FileExistsError:
            continue
        _fsync_directory(parent)
        return task_id, directory
    raise RuntimeError('no collision-safe Dev task id available in allocator window')


def _write_new_file(path: Path, payload: bytes) -> None:
    """Create an immutable task-scoped artifact; never replace prior bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, 'wb', closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory(path.parent)
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _init_dev_registry(cmd_name: str, user_input: str, claude_session_id: str, project_dir: Path) -> str:
    """Initialize dev registry directory and sentinel files for a /dev or /dev-command invocation.

    Creates .claude/dev-registry/<dev_session_id>/ with per-agent sentinel JSON files,
    writes docs/dev/user-requirement-<dev_session_id>.md with the cleaned requirement,
    and calls write-e2e-enforce.sh (and optionally write-codex-enforce.sh) as subprocesses.
    Returns the generated dev_session_id string.
    """
    # Reserving the directory with mkdir(exist_ok=False) is the allocation
    # linearization point shared by concurrent sessions.  No existing family is
    # opened for replacement, even when the wall clock has only second precision.
    dev_session_id, registry_dir = _reserve_dev_registry(cmd_name, project_dir)
    agent_types = [
        'architect', 'ba', 'cleaner', 'cleanliness-inspector', 'dev',
        'git-edge-case-analyst', 'pm', 'product-owner', 'prompt-inspector',
        'qa', 'rule-inspector', 'style-inspector', 'test-executor',
        'test-validator', 'test-writer', 'ui-specialist', 'user',
        # graphify enrichment subagent (spec-20260527-061433): registered here
        # symmetrically with CP_AGENTS and ALLOWED_AGENTS per arch-2 precedent.
        # No-op guard: graphify.json sentinel is only written when
        # CLAUDE_GRAPHIFY_ENABLED != '0' AND GRAPHIFY_BIN is resolvable, OR
        # we write it unconditionally (sentinel is cheap) because the subagent
        # checks feature flags at runtime.  The guard below is advisory only.
        'graphify',
    ]
    # Graphify no-op guard (arch-7): when GRAPHIFY_BIN is absent or
    # CLAUDE_GRAPHIFY_ENABLED=0, skip writing the graphify sentinel entirely
    # (no file write, no subprocess spawn).  Existing UserPromptSubmit
    # behaviour is unaffected — all other agent sentinels are written normally.
    _graphify_enabled = os.environ.get('CLAUDE_GRAPHIFY_ENABLED', 'auto').strip().lower() != '0'
    import shutil as _shutil
    _graphify_bin = os.environ.get('GRAPHIFY_BIN', '').strip() or _shutil.which('graphify')
    # Fallback to the global tool install (~/.claude/venv) so the sentinel is
    # written whenever graphify is installed on disk — independent of whether the
    # GRAPHIFY_BIN env var has been injected into this process yet (settings.json
    # env changes only take effect on session restart). This keeps /dev
    # graphify-aware in ANY repo from one global install, with no per-repo setup.
    if not _graphify_bin:
        _global_gfx = Path.home() / '.claude' / 'venv' / 'bin' / 'graphify'
        if _global_gfx.exists():
            _graphify_bin = str(_global_gfx)
    _write_graphify_sentinel = _graphify_enabled and bool(_graphify_bin)

    for agent in agent_types:
        # No-op guard: skip graphify sentinel when binary absent or disabled
        if agent == 'graphify' and not _write_graphify_sentinel:
            continue
        sentinel = registry_dir / f'{agent}.json'
        _write_new_file(
            sentinel,
            (json.dumps({'agent_type': agent, 'session_id': dev_session_id}) + '\n').encode('utf-8'),
        )

    # Strip --codex and --spec <path> tokens to get clean requirement
    tokens = user_input.split()
    clean_tokens = []
    skip_next = False
    for tok in tokens:
        if skip_next:
            skip_next = False
            continue
        if tok == '--codex':
            continue
        if tok in ('--spec', '-spec', '—spec', '–spec'):
            skip_next = True
            continue
        clean_tokens.append(tok)
    # Also strip inline --spec=<path> form
    clean_requirement = re.sub(r'(?:--|[–—])spec\s+\S+', '', ' '.join(clean_tokens)).strip()

    # Write user requirement document
    req_path = project_dir / 'docs' / 'dev' / f'user-requirement-{dev_session_id}.md'
    _write_new_file(req_path, clean_requirement.encode('utf-8'))

    scripts_dir = Path(__file__).parent.parent / 'scripts'
    base_env = {**os.environ, 'CLAUDE_PROJECT_DIR': str(project_dir), 'CLAUDE_SESSION_ID': claude_session_id}

    # Call write-e2e-enforce.sh (fail-open)
    try:
        e2e_script = scripts_dir / 'write-e2e-enforce.sh'
        result = subprocess.run(
            [str(e2e_script), '--source-command', cmd_name, '--session-id', dev_session_id],
            capture_output=True, text=True, timeout=15, env=base_env,
        )
        if result.returncode != 0:
            print(f'_init_dev_registry: write-e2e-enforce.sh error: {result.stderr}', file=sys.stderr)
    except Exception as e:
        print(f'_init_dev_registry: write-e2e-enforce.sh exception: {e}', file=sys.stderr)

    # Call write-codex-enforce.sh if --codex flag present (fail-open)
    if '--codex' in user_input.split():
        try:
            codex_script = scripts_dir / 'write-codex-enforce.sh'
            result = subprocess.run(
                [str(codex_script), '--source-command', cmd_name, '--session-id', dev_session_id],
                capture_output=True, text=True, timeout=15, env=base_env,
            )
            if result.returncode != 0:
                print(f'_init_dev_registry: write-codex-enforce.sh error: {result.stderr}', file=sys.stderr)
        except Exception as e:
            print(f'_init_dev_registry: write-codex-enforce.sh exception: {e}', file=sys.stderr)

    return dev_session_id


def _extract_arguments(user_input: str, cmd_name: str) -> str:
    """Strip the /cmd_name prefix and return the remaining argument string."""
    text = user_input.strip()
    prefix = f'/{cmd_name}'
    if text.lower().startswith(prefix.lower()):
        return text[len(prefix):].strip()
    return ''


def verify_overnight_state(session_id: str) -> tuple[bool, str]:
    """Read-only verification of an ALREADY-PUBLISHED overnight record.

    The launcher now initializes before it publishes, so a published record is
    supposed to imply an initialized registry. This re-checks that claim from
    the outside rather than trusting it: --verify-only performs zero writes and
    re-derives every artifact (sentinel count against CP_AGENTS parsed at run
    time, both enforcement flags against ENFORCEMENT_FLAG_VALID, and the
    requirement document against a freshly recomputed render).

    A zero exit alone is NOT success: the contract is a final line of exactly
    OVERNIGHT_INIT_OK, so a truncated run that exits 0 without the token cannot
    pass. Returns (ok, diagnostic).
    """
    sp = overnight_state_path(session_id)
    if not sp.exists():
        return False, f'no published state record at {sp}'
    script = Path.home() / '.claude' / 'scripts' / 'overnight-init.sh'
    if not os.access(script, os.X_OK):
        return False, f'initializer missing or not executable: {script}'
    try:
        result = subprocess.run(
            [str(script), '--verify-only', '--state-file', str(sp)],
            capture_output=True, text=True, timeout=60)
    except Exception as exc:
        return False, f'verification could not run: {exc}'
    out = (result.stdout or '').strip()
    last = out.splitlines()[-1] if out else ''
    if result.returncode != 0 or last != 'OVERNIGHT_INIT_OK':
        detail = (result.stderr or '').strip() or out
        return False, (f'verification failed (exit {result.returncode}, '
                       f'final line {last!r}): {detail}')
    return True, ''


def _repair_overnight_registry(session_id: str) -> str:
    """Re-verify a LIVE session's enforcement artifacts; restore only what is gone.

    Verification used to run exactly ONCE, at launch (handle_phase_a). Nothing
    re-checked the registry afterwards, so a live session that lost a sentinel
    mid-flight kept receiving continuation blocks while
    pretool-subagent-code-block.py fell OPEN for that agent: enforcement off,
    reported nowhere. A check that stops enforcing without saying it stopped is
    the failure mode this closes -- the same class the user's own report names.

    Returns a notice to be carried INSIDE the continuation block, '' when the
    registry is healthy. What the block contains and how often it is sent are
    deliberately untouched: the block is never withheld and never re-sent
    because of this check. Withholding it would strand a resuming orchestrator
    on stale routing while repairing nothing -- trading a silent enforcement gap
    for a silent liveness one.

    Cost is one --verify-only run (~0.2s) per prompt, and only while an
    overnight record is live: find_any_overnight_state has already returned a
    session-owned live state before this is reached, so ordinary sessions pay
    nothing.
    """
    ok, why = verify_overnight_state(session_id)
    if ok:
        return ''
    sp = overnight_state_path(session_id)
    script = Path.home() / '.claude' / 'scripts' / 'overnight-init.sh'
    repaired: list[str] = []
    detail = ''
    if not sp.exists() or not os.access(script, os.X_OK):
        detail = f'repair unavailable (state {sp}, initializer {script})'
    else:
        try:
            # Bounded well below verify's 60s. This whole helper sits on the
            # prompt path, and verify->repair->verify is three subprocesses: at
            # the inherited 120s a single hung repair would freeze a prompt for
            # minutes. A repair that has not finished in 20s is not going to
            # finish usefully, and the WARNING path below is the correct answer.
            r = subprocess.run(
                [str(script), '--repair-only', '--state-file', str(sp)],
                capture_output=True, text=True, timeout=20)
            repaired = [ln.split('=', 1)[1]
                        for ln in (r.stdout or '').splitlines()
                        if ln.startswith('REPAIRED=')]
            if r.returncode != 0:
                detail = (r.stderr or r.stdout or '').strip()
        except Exception as exc:
            detail = f'repair could not run: {exc}'
    # Re-verified from the outside, never inferred from the repair's own exit
    # code -- the repair is the thing being checked.
    ok, why_after = verify_overnight_state(session_id)
    if not ok:
        return (
            'WARNING: this session\'s enforcement registry is INVALID and could '
            f'not be repaired ({why_after}'
            f'{"; " + detail if detail else ""}). An artifact that is PRESENT '
            'but wrong is deliberately not overwritten -- it is either a '
            'legitimate mutation or evidence -- so this needs a human. While it '
            'stands, code-write and e2e/codex enforcement may be silently OFF '
            'for this session: do NOT treat subagent output as gated. Re-launch '
            'from a clean state, or end the session with /stop.'
        )
    if not repaired:
        return (
            'NOTE: this session\'s enforcement registry failed verification '
            f'({why}) and then passed on re-check without any artifact being '
            'restored. Treat the first reading as a transient fault worth '
            'investigating, not as a healthy registry.'
        )
    return (
        'NOTE: this session\'s enforcement registry was INCOMPLETE and has been '
        'repaired. Restored: ' + ', '.join(repaired) + f'. Original finding: '
        f'{why}. A missing dev-registry sentinel makes '
        'pretool-subagent-code-block.py fall OPEN for that agent, so code-write '
        'enforcement was OFF for any dispatch between the loss and this prompt. '
        'Re-check subagent work done in that window.'
    )


def _cleanup_overnight_partials(sid: str) -> None:
    """M5/AC4: remove any partial todo/bookmark/state written for a failed
    /dev-overnight launch so a failed launch leaves no actionable artifacts.

    The STATE FILE is included. A record that was published and then failed
    verification is the one artifact a consumer would actually act on: the
    overnight guard keys the isolation boundary on its liveness window, so
    leaving it behind arms the boundary over a registry that never validated.
    """
    for p in (official_todos_path(sid), workflow_bookmark_path(sid)):
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass
    # The state record is removed only when it actually belongs to THIS session.
    # The path is derived from sid, so an unconditional unlink would also delete a
    # record some other launch left at the same path — and that record may be the
    # one a currently-armed boundary is keyed on. Reading session_id back is the
    # cheap way to keep the cleanup attributable rather than positional.
    sp = overnight_state_path(sid)
    try:
        if sp.exists() and json.loads(sp.read_text()).get('session_id') == sid:
            sp.unlink()
    except Exception:
        pass


def _dev_start_lock_path(sid: str) -> Path:
    return PROJECT_DIR / '.claude' / 'workflow-locks' / f'{sid}.lock'


def _dev_replay_path(sid: str, envelope_digest: str) -> Path:
    return PROJECT_DIR / '.claude' / 'dev-start-replays' / sid / f'{envelope_digest}.json'


def _archive_current_generation(sid: str) -> None:
    """Copy current pointer/checklist bytes to immutable, addressable history."""
    bookmark = workflow_bookmark_path(sid)
    todos = official_todos_path(sid)
    if not bookmark.exists():
        return
    bookmark_bytes = bookmark.read_bytes()
    try:
        state = json.loads(bookmark_bytes)
    except Exception:
        state = {}
    identity = str(state.get('task_id') or state.get('workflow_instance_id') or 'unknown')
    generation = int(state.get('workflow_generation', 1) or 1)
    history = PROJECT_DIR / '.claude' / 'workflow-history' / sid / f'{generation:06d}-{identity}'
    try:
        history.mkdir(parents=True, exist_ok=False)
        _write_new_file(history / 'bookmark.json', bookmark_bytes)
        if todos.exists():
            _write_new_file(history / 'todos.json', todos.read_bytes())
        _fsync_directory(history.parent)
    except FileExistsError:
        # A previously archived generation is immutable.  Its exact bytes must
        # match before the current pointer can move again.
        if (history / 'bookmark.json').read_bytes() != bookmark_bytes:
            raise RuntimeError('prior workflow history collision')
        if todos.exists() and (history / 'todos.json').read_bytes() != todos.read_bytes():
            raise RuntimeError('prior checklist history collision')


def _ordinary_dev_start(cmd_name: str, user_input: str, sid: str, envelope_digest: str) -> None:
    """Commit one distinct Dev family or replay an exact envelope verbatim."""
    if not envelope_digest:
        envelope_digest = hashlib.sha256(
            f'{sid}\0{user_input}'.encode('utf-8')
        ).hexdigest()
    replay_path = _dev_replay_path(sid, envelope_digest)
    with _exclusive_lock(_dev_start_lock_path(sid)):
        if replay_path.exists():
            replay = json.loads(replay_path.read_text(encoding='utf-8'))
            output = replay.get('stdout')
            error_output = replay.get('stderr', '')
            if not isinstance(output, str) or not isinstance(error_output, str):
                raise RuntimeError('malformed Dev start replay record')
            sys.stdout.write(output)
            sys.stderr.write(error_output)
            return

        todos = run_todo_script(cmd_name, user_input)
        if not todos:
            return
        current = {}
        bookmark = workflow_bookmark_path(sid)
        if bookmark.exists():
            try:
                current = json.loads(bookmark.read_text(encoding='utf-8'))
            except Exception:
                current = {}

        # Task family publication happens before either mutable current file.
        # Capture any fail-open enforcement diagnostics so exact replay returns
        # the byte-identical original handler output.
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        with contextlib.redirect_stdout(captured_stdout), contextlib.redirect_stderr(captured_stderr):
            _check_workflow_conflict(cmd_name, sid)
            task_id = _init_dev_registry(cmd_name, user_input, sid, PROJECT_DIR)
        diagnostics = captured_stdout.getvalue()
        error_output = captured_stderr.getvalue()

        generation = int(current.get('workflow_generation', 0) or 0) + 1
        data = {
            'command': cmd_name,
            'todo_acknowledged': False,
            'workflow_instance_id': secrets.token_hex(32),
            'workflow_generation': generation,
            'workflow_started_at_ms': time.time_ns() // 1_000_000,
            'task_id': task_id,
            'preservation_policy': 'immutable_prior_family_atomic_current_pointer/v1',
            'start_envelope_sha256': envelope_digest,
        }
        arguments = _extract_arguments(user_input, cmd_name)
        if arguments:
            data['arguments'] = arguments
        _archive_current_generation(sid)
        # The checklist is fully durable before the bookmark/current-pointer
        # replace.  The bookmark is the authoritative generation selector.
        _atomic_write_json(official_todos_path(sid), todos)
        _atomic_write_json(bookmark, data)

        codex_active = '--codex' in user_input.split()
        output = ''.join([
            diagnostics,
            f'DEV_SESSION_ID pre-initialized by hook: {task_id}\n',
            f'User requirement document: docs/dev/user-requirement-{task_id}.md\n',
            'E2E enforcement: ACTIVE\n',
            f'Codex enforcement: {"ACTIVE (--codex)" if codex_active else "inactive"}\n',
            checklist_message(cmd_name, todos),
            '\n',
        ])
        _atomic_write_json(replay_path, {
            'schema': 'claude.ordinary-dev-start-replay/v1',
            'session_id': sid,
            'envelope_sha256': envelope_digest,
            'task_id': task_id,
            'workflow_generation': generation,
            'stdout': output,
            'stderr': error_output,
        })
        sys.stdout.write(output)
        sys.stderr.write(error_output)


def handle_phase_a(cmd_name: str, user_input: str, sid: str, envelope_digest: str = '') -> None:
    """Phase A: slash command detected -- setup todos, state, inject spec."""
    if cmd_name in ("commit", "push", "merge", "stop"):
        _write_userintent_sentinel(cmd_name, sid)
    if cmd_name == "do":
        handle_do_consent(sid)
    if cmd_name in ('dev', 'dev-command', 'redev'):
        _ordinary_dev_start(cmd_name, user_input, sid, envelope_digest)
        return
    todos = run_todo_script(cmd_name, user_input)
    if not todos:
        return
    _check_workflow_conflict(cmd_name, sid)
    # M5/AC4: for /dev-overnight, create + validate the isolated overnight state
    # BEFORE writing todos/bookmark/checklist. On failure: print stderr, clean
    # any partials, and FAIL CLOSED (no checklist, no command-spec, no
    # EnterWorktree prompt, no silent exit(0)).
    if cmd_name == 'dev-overnight':
        end_time, focus, spec_path, codex_required, worktree_choice = parse_overnight_args(user_input)
        ok = create_overnight_state(
            end_time, focus, spec_path=spec_path, session_id=sid,
            codex_required=codex_required, worktree_choice=worktree_choice)
        if not ok:
            print('OVERNIGHT LAUNCH ABORTED: the launcher refused to write a '
                  'session-state record (see the error above). No checklist or '
                  'command spec injected.', file=sys.stderr)
            _cleanup_overnight_partials(sid)
            raise SystemExit(2)
        # The launcher claims a published record implies an initialized
        # registry. Verify it here, read-only, BEFORE any todos/bookmark/
        # checklist exist — a post-publication corruption is the one failure the
        # publish gate structurally cannot see. Failing closed removes the
        # record too, so no consumer can arm the boundary over it.
        verified, why = verify_overnight_state(sid)
        if not verified:
            print('OVERNIGHT LAUNCH ABORTED: the published session record did '
                  f'not verify ({why}). The record has been removed. No '
                  'checklist or command spec injected.', file=sys.stderr)
            _cleanup_overnight_partials(sid)
            raise SystemExit(2)
    tf = official_todos_path(sid)
    tf.parent.mkdir(parents=True, exist_ok=True)
    tf.write_text(json.dumps(todos, ensure_ascii=False))
    _write_bookmark(cmd_name, sid, _extract_arguments(user_input, cmd_name))
    emit_checklist_message(cmd_name, todos)


def _write_bookmark(cmd_name: str, sid: str, arguments: str = '') -> None:
    """Write the workflow bookmark file."""
    bm = workflow_bookmark_path(sid)
    try:
        bm.parent.mkdir(parents=True, exist_ok=True)
        data = {
            'command': cmd_name,
            'todo_acknowledged': False,
            'workflow_instance_id': secrets.token_hex(32),
            'workflow_generation': 1,
            'workflow_started_at_ms': time.time_ns() // 1_000_000,
        }
        if arguments:
            data['arguments'] = arguments
        bm.write_text(json.dumps(data))
    except Exception:
        pass


def main():
    # In a Codex root the native harness owns task identity, artifacts, workflow
    # generation, projection, and Stop. This Claude hook remains authoritative
    # only for Claude roots and must never become a second writer through the
    # compatibility wrapper.
    if os.environ.get('CLAUDE_COMPAT_RUNTIME') == 'codex':
        sys.exit(0)
    try:
        raw = sys.stdin.buffer.read()
        data = json.loads(raw)
        global PROJECT_DIR, CURRENT_TRANSCRIPT_PATH
        PROJECT_DIR = resolve_project_dir(data)
        # Authoritative context-epoch signal for the continuation cadence. It
        # must come from the payload: the session-id-keyed store scan resolves
        # against $HOME/.claude, a symlink to the repo root, and misses the
        # account's live transcript store.
        CURRENT_TRANSCRIPT_PATH = str(data.get('transcript_path') or '')
        user_input = data.get('prompt', '')
        session_id = data.get('session_id', 'default')
        cmd_name = extract_command_name(user_input)
        if not cmd_name:
            handle_phase_b(session_id)
        else:
            handle_phase_a(cmd_name, user_input, session_id, hashlib.sha256(raw).hexdigest())
    except SystemExit:
        # M5/AC4: a /dev-overnight launch failure raises SystemExit(2) to fail
        # CLOSED. Do NOT swallow it into exit(0); propagate the failure code.
        raise
    except Exception:
        pass
    sys.exit(0)


if __name__ == '__main__':
    main()
