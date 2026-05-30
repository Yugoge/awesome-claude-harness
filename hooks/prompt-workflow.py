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
import subprocess
import sys
import importlib.util
from datetime import datetime
from pathlib import Path

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
    git rev-parse --show-toplevel -> /root literal (final safety net).
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
    return Path('/root')


# Module-level binding for backward compat (env+cwd+git+literal tiers;
# stdin-cwd tier is added inside main() after JSON parse).
PROJECT_DIR = resolve_project_dir()


def overnight_state_path(session_id: str = 'default') -> Path:
    """Path to the overnight state file (keyed by session_id for multi-session)."""
    return PROJECT_DIR / '.claude' / f'overnight-state-{session_id}.json'


def _is_active_state(state: dict) -> bool:
    """Return True if state has a future end_time."""
    et = state.get('end_time')
    if not et:
        return False
    try:
        return datetime.fromisoformat(et) > datetime.now()
    except (ValueError, TypeError):
        return False


def find_any_overnight_state() -> tuple:
    """Find any active overnight state file for continuation."""
    claude_dir = PROJECT_DIR / '.claude'
    for p in sorted(claude_dir.glob('overnight-state-*.json')):
        try:
            state = json.loads(p.read_text())
        except Exception:
            continue
        if _is_active_state(state):
            return state, p
    return None, None


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


def parse_overnight_args(prompt_text: str) -> tuple[str, str, str, bool]:
    """Extract end-time, focus, spec path, and codex flag from /dev-overnight args.

    Returns (end_time_raw, focus_string, spec_path, codex_required). M4 (harness-fixes
    20260428): now also recognizes +Nh / +N.Mh / +Nm relative-time
    tokens; an unknown +token returns INVALID:<token> so the bash layer
    can surface an explicit error rather than silently defaulting to +8h.
    Spec dash-form tolerance unchanged (-- / — / –).
    M5 (2026-05-15): extracts --codex boolean flag and returns it as 4th element.
    """
    match = re.search(r'/dev-overnight\s+(.*)', prompt_text.strip())
    args = match.group(1).strip() if match else ''
    # Extract --codex flag (boolean toggle, no value)
    codex_required = '--codex' in args.split()
    args = re.sub(r'\s*--codex\b', '', args).strip()
    args, spec_path = _strip_spec_arg(args)
    if not args:
        return '', '', spec_path, codex_required
    end_time, focus = _match_end_time_token(args)
    return end_time, focus, spec_path, codex_required


def create_overnight_state(end_time: str, focus: str = '', spec_path: str = '', session_id: str = 'default', codex_required: bool = False) -> bool:
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
    cmd += ['--session-id', session_id]
    cmd += ['--project-dir', str(PROJECT_DIR)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
            return False
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)
        return True
    except Exception:
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
    """Build worktree guard instruction based on state."""
    wt = state.get('worktree_path')
    if wt is not None and wt != '':
        return (
            f'CRITICAL: Worktree already exists at {wt}. '
            'DO NOT call EnterWorktree under any circumstances.'
        )
    return 'Worktree was not created yet. Call EnterWorktree in Step 1.'


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


def build_overnight_continuation(state: dict) -> str:
    """Build continuation context for overnight loop prompts."""
    cc = state.get('cycle_count', 0)
    phase = state.get('current_phase', 'unknown')
    log = state.get('cycle_log', [])
    last_entry = log[-1] if log else None
    last = f"Cycle {last_entry.get('cycle')}: {last_entry.get('status')}" if last_entry else 'N/A'
    cmd_spec = read_command_spec('dev-overnight')
    wt_instruction = _build_worktree_instruction(state)
    overnight_todos = _load_overnight_todos()
    step_count = len(overnight_todos) or 21
    step_labels = '; '.join(str(item.get('content', '')) for item in overnight_todos)
    return '\n'.join([
        f'OVERNIGHT CONTINUATION - Cycle {cc + 1}', '',
        '--- COMMAND SPECIFICATION ---', '', cmd_spec, '',
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
        'Phase mapping: initializing/exploring->Step 2, selecting->Step 3,',
        'analyzing->Step 4, implementing->Step 6, verifying->Step 8, logging->Step 12',
    ])


def check_overnight_continuation() -> str | None:
    """Check if any overnight session needs continuation."""
    state, state_path = find_any_overnight_state()
    if state is None:
        return None
    return build_overnight_continuation(state)


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
        r['canonical'] = run_todo_script(r['command'])
    if r['lock_reason'] == 'sequence_violation':
        r['last_todos'] = st.get('last_todos', [])
    return r


def handle_phase_b(session_id: str) -> None:
    """Phase B: inject overnight continuation and/or workflow progress."""
    overnight_ctx = check_overnight_continuation()
    if overnight_ctx:
        print(overnight_ctx)
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


def emit_checklist_message(cmd_name: str, todos: list) -> None:
    """Print the checklist initialization message with command spec."""
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
    print('\n'.join(lines))


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


def handle_do_consent(sid: str) -> None:
    """Handle /do command: write consent flag and print confirmation."""
    flag = Path(f"/tmp/claude-orchestrator-consent-{sid}.flag")
    try:
        flag.write_text("true")
        print(f"[/do] Consent granted. Main agent may now perform direct operations this session.")
    except Exception as e:
        sys.stderr.write(f"[/do] Failed to write consent flag: {e}\n")


def _write_userintent_sentinel(cmd_name: str, sid: str) -> None:
    """Write sid-keyed user-intent sentinel. Mirrors /allow pattern: both
    writer (this hook) and reader (pretool-wrapper-userintent.py PreToolUse
    hook) resolve sid from stdin JSON, so sid-keying round-trips correctly.
    Single-use; consumed by the PreToolUse hook before the wrapper runs."""
    try:
        Path(f"/tmp/claude-{cmd_name}-userintent-{sid}.flag").write_text("true")
    except OSError:
        pass


def _init_dev_registry(cmd_name: str, user_input: str, claude_session_id: str, project_dir: Path) -> str:
    """Initialize dev registry directory and sentinel files for a /dev or /dev-command invocation.

    Creates .claude/dev-registry/<dev_session_id>/ with per-agent sentinel JSON files,
    writes docs/dev/user-requirement-<dev_session_id>.md with the cleaned requirement,
    and calls write-e2e-enforce.sh (and optionally write-codex-enforce.sh) as subprocesses.
    Returns the generated dev_session_id string.
    """
    import datetime as _dt
    prefix = 'dev-command' if cmd_name == 'dev-command' else 'dev'
    dev_session_id = f"{prefix}-{_dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"

    # Create registry directory and write per-agent sentinel files
    registry_dir = project_dir / '.claude' / 'dev-registry' / dev_session_id
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
    _write_graphify_sentinel = _graphify_enabled and bool(_graphify_bin)

    try:
        registry_dir.mkdir(parents=True, exist_ok=True)
        for agent in agent_types:
            # No-op guard: skip graphify sentinel when binary absent or disabled
            if agent == 'graphify' and not _write_graphify_sentinel:
                continue
            sentinel = registry_dir / f'{agent}.json'
            sentinel.write_text(
                json.dumps({'agent_type': agent, 'session_id': dev_session_id}) + '\n'
            )
    except Exception as e:
        print(f'_init_dev_registry: registry write error: {e}', file=sys.stderr)

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
    try:
        req_path = project_dir / 'docs' / 'dev' / f'user-requirement-{dev_session_id}.md'
        req_path.parent.mkdir(parents=True, exist_ok=True)
        req_path.write_text(clean_requirement)
    except Exception as e:
        print(f'_init_dev_registry: requirement write error: {e}', file=sys.stderr)

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


def handle_phase_a(cmd_name: str, user_input: str, sid: str) -> None:
    """Phase A: slash command detected -- setup todos, state, inject spec."""
    if cmd_name in ("commit", "push", "merge", "stop"):
        _write_userintent_sentinel(cmd_name, sid)
    if cmd_name == "do":
        handle_do_consent(sid)
        return
    todos = run_todo_script(cmd_name, user_input)
    if not todos:
        return
    _check_workflow_conflict(cmd_name, sid)
    tf = official_todos_path(sid)
    tf.parent.mkdir(parents=True, exist_ok=True)
    tf.write_text(json.dumps(todos, ensure_ascii=False))
    _write_bookmark(cmd_name, sid, _extract_arguments(user_input, cmd_name))
    if cmd_name == 'dev-overnight':
        end_time, focus, spec_path, codex_required = parse_overnight_args(user_input)
        create_overnight_state(end_time, focus, spec_path=spec_path, session_id=sid, codex_required=codex_required)
    if cmd_name in ('dev', 'dev-command', 'redev'):
        dev_session_id = _init_dev_registry(cmd_name, user_input, sid, PROJECT_DIR)
        codex_active = '--codex' in user_input.split()
        req_doc = f'docs/dev/user-requirement-{dev_session_id}.md'
        print(f'DEV_SESSION_ID pre-initialized by hook: {dev_session_id}')
        print(f'User requirement document: {req_doc}')
        print(f'E2E enforcement: ACTIVE')
        print(f'Codex enforcement: {"ACTIVE (--codex)" if codex_active else "inactive"}')
    emit_checklist_message(cmd_name, todos)


def _write_bookmark(cmd_name: str, sid: str, arguments: str = '') -> None:
    """Write the workflow bookmark file."""
    bm = workflow_bookmark_path(sid)
    try:
        bm.parent.mkdir(parents=True, exist_ok=True)
        data = {'command': cmd_name, 'todo_acknowledged': False}
        if arguments:
            data['arguments'] = arguments
        bm.write_text(json.dumps(data))
    except Exception:
        pass


def main():
    try:
        data = json.load(sys.stdin)
        global PROJECT_DIR
        PROJECT_DIR = resolve_project_dir(data)
        user_input = data.get('prompt', '')
        session_id = data.get('session_id', 'default')
        cmd_name = extract_command_name(user_input)
        if not cmd_name:
            handle_phase_b(session_id)
        else:
            handle_phase_a(cmd_name, user_input, session_id)
    except Exception:
        pass
    sys.exit(0)


if __name__ == '__main__':
    main()
