#!/usr/bin/env python3
"""
PreToolUse Hook: Overnight session file modification guard.

Activation: Session-specific — only the session owning an overnight state file
is subject to worktree enforcement. The overnight-state protection applies to
every session while any overnight session is active.

Enforcement layers:
  1. Global: Block Write/Edit of .claude/hooks/ and .claude/commands/, and any
     write of an overnight-state file.
  2. Session: Block file writes outside the worktree realpath boundary.
  3. Actor: Block git ops that target the main checkout or the protected branch,
     Write/Edit of its checkout's git config (the keystone), any write onto a
     worktree's per-worktree config.worktree, and a `git config` write of the
     keystone key.
  AskUserQuestion: denied to the /dev-overnight session's main agent and
  subagents until a human-typed prompt follows its /dev-overnight.

A Bash command is read once by the shared parser (lib/shell_parse.py).

Exit codes:
  0: Allow tool use
  2: Block tool use
"""

import fnmatch
import functools
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.harness_state_dir import harness_state_dir  # noqa: E402
from lib import command_span, locations, overnight, shell_parse as sp, stop_contract  # noqa: E402
from lib.git_command_classifier import GIT_GLOBAL_VALUE_OPTS  # noqa: E402
from lib import git_facts  # noqa: E402
from lib.git_facts import GIT_COMMON_DIR_PROTECTED, GIT_DIR_CONFIG_FILES  # noqa: E402

try:  # optional contract runtime + agent resolver for the self_repair grant
    from lib import contract_runtime as _contract_runtime  # noqa: E402
    from lib.agent_resolver import resolve_agent_type as _resolve_agent_type  # noqa: E402
    from lib.agent_resolver import resolve_dev_registry_entry as _resolve_dev_registry_entry  # noqa: E402
except Exception:  # pragma: no cover - fail-soft when modules missing
    _contract_runtime = None  # type: ignore[assignment]
    _resolve_agent_type = None  # type: ignore[assignment]
    _resolve_dev_registry_entry = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Contract-driven self-repair grant
# ---------------------------------------------------------------------------


def _self_repair_block(contract: dict | None) -> dict | None:
    """Return cycle-contract.self_repair object iff enabled, else None."""
    if not isinstance(contract, dict):
        return None
    sr = contract.get('self_repair')
    if not isinstance(sr, dict):
        return None
    if not sr.get('enabled', False):
        return None
    return sr


def _expires_passed(expires_at: str) -> bool:
    """True when ISO-8601 expires_at has passed; True on parse failure (fail-closed)."""
    if not expires_at or not isinstance(expires_at, str):
        return True
    try:
        dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return True
    if dt.tzinfo is None:
        return datetime.now() > dt
    return datetime.now(timezone.utc) > dt


def _path_under_prefix(target: str, prefix: str) -> bool:
    """Boundary-aware prefix match using realpath comparison."""
    try:
        abs_target = os.path.realpath(os.path.abspath(target))
        abs_prefix = os.path.realpath(os.path.abspath(prefix))
    except (OSError, ValueError):
        return False
    if abs_target == abs_prefix:
        return True
    return abs_target.startswith(abs_prefix.rstrip('/') + os.sep)
_HARNESS_STATE_DIR_PREFIXES = (
    '.claude/dev-registry/',
    '.claude/specs/',
    '.claude/todos/',
)
_HARNESS_STATE_FILE_PFX_REL = ('.claude/overnight-state-',)


def _harness_state_dirs() -> list[str]:
    """The harness-state directories, under the project and under HOME, that the orchestrator
    may write outside the worktree boundary (an overnight-state file stays refused by
    is_state_file_path)."""
    proj = Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))
    home = Path.home()
    out = []
    for p in _HARNESS_STATE_DIR_PREFIXES:
        out.append(str(proj / p))
        out.append(str(home / p))
    return out


def _harness_state_file_pfx_resolved() -> list[str]:
    """Realpath-resolved filename prefixes (matched via startswith)."""
    proj = Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))
    return [os.path.realpath(str(proj / p)) for p in _HARNESS_STATE_FILE_PFX_REL]


def _harness_dir_match(target: str) -> bool:
    """True iff target falls under a harness-state directory prefix."""
    return any(_path_under_prefix(target, pfx) for pfx in _harness_state_dirs())


def _harness_file_match(target: str) -> bool:
    """True iff target's realpath starts with a harness-state filename prefix."""
    try:
        abs_target = os.path.realpath(os.path.abspath(target))
    except (OSError, ValueError):
        return False
    return any(abs_target.startswith(pfx) for pfx in _harness_state_file_pfx_resolved())


def _is_harness_state_path(target: str) -> bool:
    """True iff target matches any harness-state directory or file prefix."""
    return _harness_dir_match(target) or _harness_file_match(target)


def _is_orchestrator_actor() -> bool:
    """True iff the payload carries no agent_id (the orchestrator, the main agent)."""
    payload = _REQUEST_CTX.get('payload') or {}
    return not payload.get('agent_id')


def _is_harness_state_exempt(target: str) -> bool:
    """True iff target is a harness-state path and the actor is the orchestrator."""
    if not target:
        return False
    if not _is_orchestrator_actor():
        return False
    return _is_harness_state_path(target)


def _payload_pipeline_id(payload: dict) -> str:
    """Extract pipeline_id from payload (tool_input direct, then prompt regex)."""
    if not isinstance(payload, dict):
        return ''
    ti = payload.get('tool_input', {}) or {}
    pid = ti.get('pipeline_id') or ti.get('pipelineId')
    if isinstance(pid, str) and pid:
        return pid
    prompt = ti.get('prompt', '')
    if not isinstance(prompt, str):
        return ''
    m = re.search(r'pipeline[_-]?id[\s:=]+["\']?([A-Za-z0-9_.\-]+)', prompt)
    return m.group(1) if m else ''


def _resolve_role(payload: dict) -> str:
    """The acting subagent's role through lib.agent_resolver alone ('' for the
    main agent or on any failure): an environment variable is never a role."""
    if _resolve_agent_type is None or not isinstance(payload, dict):
        return ''
    try:
        role = _resolve_agent_type(payload)
    except Exception:
        return ''
    return role if isinstance(role, str) else ''


def _load_active_contract(state: dict) -> dict | None:
    """Load cycle-contract for the active overnight session, if available."""
    if _contract_runtime is None or not isinstance(state, dict):
        return None
    sid = state.get('session_id') or ''
    if not sid:
        return None
    try:
        return _contract_runtime.load_contract(sid, overnight.cycle_index(state), state)
    except Exception:
        return None


def _check_role(role: str, sr: dict) -> tuple[bool, str]:
    """Sub-check: role membership in allowed_roles."""
    allowed = sr.get('allowed_roles') or ['dev']
    return (role in allowed, f'role_not_allowed:{role}')


def _check_target_prefix(target: str, sr: dict) -> tuple[bool, str]:
    """Sub-check: target startswith one of allowed_path_prefixes."""
    prefixes = sr.get('allowed_path_prefixes') or []
    if not prefixes:
        return False, 'no_prefixes_declared'
    ok = any(_path_under_prefix(target, p) for p in prefixes)
    return ok, 'target_outside_prefixes'


def _check_pipeline(pipeline_id: str, sr: dict) -> tuple[bool, str]:
    """Sub-check: pipeline_id matches when declared."""
    declared = sr.get('pipeline_id')
    if not isinstance(declared, str) or not declared:
        return True, 'pipeline_unconstrained'
    return (pipeline_id == declared, f'pipeline_mismatch:{pipeline_id}!={declared}')


def _grant_decision_for(target: str, role: str, pipeline_id: str, sr: dict) -> tuple[bool, str]:
    """Pure decision: combine role/prefix/pipeline/expiry sub-checks."""
    ok, reason = _check_role(role, sr)
    if not ok:
        return False, reason
    ok, reason = _check_target_prefix(target, sr)
    if not ok:
        return False, reason
    ok, reason = _check_pipeline(pipeline_id, sr)
    if not ok:
        return False, reason
    if _expires_passed(sr.get('expires_at', '')):
        return False, 'expired'
    return True, 'granted'


def is_self_repair_allowed(target: str, state: dict, payload: dict) -> bool:
    """True iff cycle-contract grants self_repair for (target, role, pipeline).

    Fail-closed: missing contract / disabled grant / role mismatch /
    target outside prefixes / pipeline mismatch / expired all collapse
    to False.
    """
    contract = _load_active_contract(state)
    sr = _self_repair_block(contract)
    if sr is None:
        return False
    role = _resolve_role(payload)
    pipeline_id = _payload_pipeline_id(payload)
    granted, _reason = _grant_decision_for(target, role, pipeline_id, sr)
    return granted


# Module-level request context; populated by main() so existing helper
# call sites (security checks, worktree enforcement) can consult the
# self_repair grant without changing their signatures. Empty dict = no
# context (e.g. unit tests calling helpers directly).
_REQUEST_CTX: dict = {}


def _set_request_ctx(state: dict | None, payload: dict | None) -> None:
    """Populate the per-request context for grant-aware block sites."""
    _REQUEST_CTX['state'] = state or {}
    _REQUEST_CTX['payload'] = payload or {}


def _grant_skips_block(target: str) -> bool:
    """Helper used by block sites: True iff self_repair grants this target."""
    if not _REQUEST_CTX:
        return False
    state = _REQUEST_CTX.get('state') or {}
    payload = _REQUEST_CTX.get('payload') or {}
    if not state:
        return False
    return is_self_repair_allowed(target, state, payload)


def _is_session_live(state: dict) -> bool:
    """Check if the overnight session's isolation still binds.

    The verdict is lib/overnight.py's `isolation_held`: keyed on the isolation
    window (`isolation_active_until`, falling back to `end_time`) and an
    explicit `isolation_released_at` — NOT on `current_phase`, so a state write
    that marks the phase complete cannot release isolation prematurely; only
    the user `/stop` path sets `isolation_released_at`.
    """
    return overnight.state_verdicts(state).isolation_held


def _file_age_seconds(sf: Path) -> float:
    """Return seconds since sf was last modified, or 0.0 on OSError."""
    try:
        return time.time() - sf.stat().st_mtime
    except OSError:
        return 0.0


def _is_orphaned_state(sf: Path, state: dict) -> bool:
    """Detect orphaned state: appears live but has no backing session."""
    wt = state.get('worktree_path')
    if wt and not Path(wt).is_dir():
        return True
    if wt:
        return False
    return _file_age_seconds(sf) > 7200


def _load_state(sf: Path) -> dict | None:
    """The record in a state file, or None (lib/overnight.py `read_state`)."""
    return overnight.read_state(sf)


def _extract_live_worktree_path(sf: Path) -> str:
    """Return the ISOLATED worktree_path from a live state file; else empty.

    An `in_place` session (`/dev-overnight` without `--worktree`) is
    deliberately excluded. Its `worktree_path` is the main root, and this list
    is the set of roots that writes are confined TO — so including it would
    declare the main checkout an isolated worktree for *every* session, not just
    its own. A concurrent `--worktree` actor would then find the main root on
    its allow-list and be free to write into the very checkout its isolation
    exists to protect. An in-place session imposes no boundary, which is exactly
    what the user chose by not asking for one.
    """
    state = _load_state(sf)
    if state is None:
        return ""
    if not _is_session_live(state):
        return ""
    if state.get("isolation_kind") == "in_place":
        return ""
    return state.get("worktree_path", "") or ""


def _get_active_worktree_paths() -> list[str]:
    """Return worktree_paths from all live overnight sessions."""
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    state_files = list((project_dir / ".claude").glob("overnight-state-*.json"))
    paths = []
    for sf in state_files:
        wt = _extract_live_worktree_path(sf)
        if wt:
            paths.append(wt)
    return paths


def _get_protected_branches() -> list[str]:
    """Union of `protected_branch` over every NON-RELEASED overnight session record.

    The protected branch is read from the session-state records at decision time, never a literal;
    an unresolvable set carries no branch-name signal, and the main-targeting / not-in-worktree
    predicates still govern. A released record (lib/overnight.py's `released`, which is immutable)
    is the only one left out.
    """
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    names: list[str] = []
    try:
        state_files = list((project_dir / ".claude").glob("overnight-state-*.json"))
    except OSError:
        return names
    for sf in state_files:
        state = _load_state(sf)
        if state is None or overnight.state_verdicts(state).released:
            continue
        val = state.get("protected_branch")
        if isinstance(val, str) and val and val not in names:
            names.append(val)
    return names


def _operand_branch_names(token: str) -> list[str]:
    """Reduce one argv token to the branch name(s) it can denote.

    Covers bare <N>, refs/heads/<N>, heads/<N>, <N>@{0} and refspec forms.
    Every transformation is a STRUCTURAL ref-namespace normalisation; none
    inspects the branch NAME, so none is a name-shape gate.
    """
    out: list[str] = []
    for part in token.lstrip('+').split(':'):
        part = part.split('@{', 1)[0]
        for pfx in ('refs/heads/', 'heads/'):
            if part.startswith(pfx):
                part = part[len(pfx):]
                break
        if part:
            out.append(part)
    return out


def _mentions_protected_branch(tokens) -> bool:
    """True iff any token denotes a branch in the RESOLVED protected set.

    Membership is exact string equality against a value read from the record.
    """
    protected = _get_protected_branches()
    if not protected:
        return False
    for tok in tokens:
        for name in _operand_branch_names(tok.strip('\'"')):
            if name in protected:
                return True
    return False


def _body_mentions_protected_branch(body: str) -> bool:
    """True iff a script body names a resolved protected branch as a word."""
    for name in _get_protected_branches():
        if re.search(r'(?<![\w/-])' + re.escape(name) + r'(?![\w-])', body):
            return True
    return False


def _is_path_exempt(file_path: str) -> bool:
    """Check if path is exempt from overnight worktree restrictions: the null device, a sink no file
    lies behind (by name: /dev/stderr is a link to this process's own descriptor), a temp directory the
    session's own files go to, the hook state root (lib/locations: both sides resolved)."""
    named = os.path.abspath(file_path)
    if os.path.realpath(named) == locations.NULL_DEVICE or locations.is_sink(named):
        return True
    roots = locations.session_temp_roots() + (locations.state_root(),)
    return any(root != os.sep and locations.is_inside(file_path, root) for root in roots)


def _in_isolated_main_root(file_path: str) -> bool:
    """True iff file_path lies in the main root of a live ISOLATED record.

    The /tmp exemption must not reach the very checkout an isolated session
    exists to protect (a main root under /tmp would otherwise fail open). A
    harness state dir placed INSIDE the main root keeps its exemption; the
    default state dir (/tmp) does not. in_place records add nothing.
    """
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    state_root = harness_state_dir()
    for sf in (project_dir / ".claude").glob("overnight-state-*.json"):
        if not _extract_live_worktree_path(sf):
            continue
        main_root = (_load_state(sf) or {}).get("main_root") or str(project_dir)
        if not _path_under_prefix(file_path, main_root):
            continue
        if _path_under_prefix(state_root, main_root) and _path_under_prefix(file_path, state_root):
            continue
        return True
    return False


def _is_path_allowed_during_overnight(file_path: str, worktree_paths: list[str]) -> bool:
    """Check if a file path is allowed during overnight (inside worktree or /tmp)."""
    abs_path = os.path.realpath(os.path.abspath(file_path))
    for wt in worktree_paths:
        abs_wt = os.path.realpath(os.path.abspath(wt))
        if abs_path.startswith(abs_wt + os.sep) or abs_path == abs_wt:
            return True
    if _is_harness_state_exempt(file_path):
        return True
    return _is_path_exempt(file_path) and not _in_isolated_main_root(file_path)


def _block_global_worktree(tool_name: str, target: str, worktree_paths: list[str]) -> None:
    """Emit the shared OVERNIGHT WORKTREE ENFORCEMENT block message."""
    allowed = ", ".join(worktree_paths)
    _block(
        '\nOVERNIGHT WORKTREE ENFORCEMENT: All writes must target '
        'the overnight worktree during active sessions.\n'
        f'Allowed worktrees: {allowed}\n'
        f'Attempted: {tool_name} to {target}\n'
    )


def _edit_target(tool_name: str, tool_input: dict) -> str:
    """The file a file-writing tool names ('' for any other): command_span.EDIT_TOOLS holds each tool's path key."""
    key = command_span.EDIT_TOOLS.get(tool_name)
    return str(tool_input.get(key) or '') if key else ''


def _enforce_write_edit_all_sessions(tool_name: str, tool_input: dict, worktree_paths: list[str]) -> None:
    """Block Write/Edit outside active overnight worktrees for all sessions (self_repair-grant aware)."""
    fp = _edit_target(tool_name, tool_input)
    if not fp or _is_path_allowed_during_overnight(fp, worktree_paths) or _grant_skips_block(fp):
        return
    _block_global_worktree(tool_name, fp, worktree_paths)


def _enforce_bash_all_sessions(tool_name: str, tool_input: dict, worktree_paths: list[str]) -> None:
    """Block Bash writes outside active overnight worktrees for all sessions (self_repair-grant aware).
    A `docker compose build|up` command's own output redirection is QA's and passes."""
    if tool_name != 'Bash':
        return
    command = tool_input.get('command', '')
    for path in _bash_write_paths(command, _compose_up_redirects(command)):
        if _is_path_allowed_during_overnight(path, worktree_paths) or _grant_skips_block(path):
            continue
        _block_global_worktree('Bash', path, worktree_paths)


def apply_global_worktree_enforcement(tool_name: str, tool_input: dict, worktree_paths: list[str]) -> None:
    """Block writes outside every live overnight worktree; main() runs it for
    each enforced actor. A subagent's payload carries its parent's session_id
    and main transcript_path (plus agent_id), so it is governed as its session.
    """
    if not worktree_paths:
        return
    _enforce_write_edit_all_sessions(tool_name, tool_input, worktree_paths)
    _enforce_bash_all_sessions(tool_name, tool_input, worktree_paths)


def _any_live_state(sf: Path) -> bool:
    """Return True if sf describes a live, non-orphaned overnight session. An expired state file
    stays on disk as evidence."""
    state = _load_state(sf)
    return state is not None and _is_session_live(state) and not _is_orphaned_state(sf, state)


def is_overnight_active() -> bool:
    """Check if any overnight session is still live."""
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    state_files = list((project_dir / ".claude").glob("overnight-state-*.json"))
    if not state_files:
        return False
    return any(_any_live_state(sf) for sf in state_files)


def get_overnight_state_for_session(project_dir: Path, session_id: str) -> dict | None:
    """Load overnight state file for the specific session."""
    if not session_id:
        return None
    return _load_state(project_dir / '.claude' / f'overnight-state-{session_id}.json')


# ---------------------------------------------------------------------------
# A Bash command, read once by the shared parser (lib/shell_parse.py)
# ---------------------------------------------------------------------------


def _known_env() -> dict:
    """The variables whose value the hook shares with the shell it guards."""
    known = {'HOME': os.environ.get('HOME') or os.path.expanduser('~')}
    if os.environ.get('CLAUDE_PROJECT_DIR'):
        known['CLAUDE_PROJECT_DIR'] = os.environ['CLAUDE_PROJECT_DIR']
    return known


class _Read:
    """One Bash command as the shared parser reads it: each command it runs (also inside
    substitutions, `bash -c`, `eval` and fed shells) with what that command resolves to past its
    wrappers, and each path it writes."""

    def __init__(self, command: str, env: dict):
        self.command = command
        self.script = sp.parse(command)
        self.unreadable = bool(self.script.errors())
        self.resolved = [(site, sp.resolve(site.cmd)) for site in sp.walk(self.script)]
        self.targets = sp.write_targets(self.script, env=env)


@functools.lru_cache(maxsize=8)
def _read_with(command: str, env: tuple) -> _Read:
    return _Read(command, dict(env))


def _read(command: str) -> _Read:
    return _read_with(command or '', tuple(sorted(_known_env().items())))


def _word_text(word) -> str:
    """A word as the shell hands it on where it is static, each expansion kept as written."""
    raw, at = word.raw.text, word.start
    return ''.join(p.text if p.kind == 'lit' else raw[p.span[0] - at:p.span[1] - at] for p in word.parts)


def _harness_home() -> str:
    return os.environ.get('CLAUDE_HOME') or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _word_path(word) -> str:
    """A path word as the shell expands it where the value is known: `~`, $HOME,
    $CLAUDE_PROJECT_DIR and $CLAUDE_HOME (the home this hook runs from when unset), also as
    `${NAME:-default}`; any other expansion stays as written."""
    env = dict(_known_env(), CLAUDE_HOME=_harness_home())
    out = []
    for p in word.parts:
        m = re.fullmatch(r'([A-Za-z_]\w*)(?::?-(.*))?', p.text, re.S) if p.kind == 'param' else None
        if p.kind == 'lit':
            out.append(p.text)
        elif m and m.group(1) in env:
            out.append(env[m.group(1)])
        elif m and m.group(2) is not None:
            out.append(re.sub(r'\$\{?([A-Za-z_]\w*)\}?', lambda v: env.get(v.group(1), v.group(0)), m.group(2)))
        else:
            out.append(word.raw.text[p.span[0] - word.start:p.span[1] - word.start])
    text = ''.join(out)
    return os.path.expanduser(text) if text.startswith('~') else text


def _target_text(t) -> str:
    """A write target as the path text the checks match: the static path, else its word with each
    known variable expanded and any other expansion kept as written."""
    text = t.path if t.path is not None else _word_text(t.word)
    for name, value in _known_env().items():
        text = text.replace('${%s}' % name, value).replace('$' + name, value)
    return os.path.expanduser(text) if text.startswith('~') else text


def _bash_write_paths(command: str, skip=frozenset()) -> list[str]:
    """The path of each file the command writes or creates (a deletion is not one), first seen order.
    ``skip`` holds the ids of target words not to report."""
    found = (_target_text(t) for t in _read(command).targets
             if t.mode != sp.DELETE and id(t.word) not in skip)
    return list(dict.fromkeys(p for p in found if p))


def _interpreter(name) -> bool:
    """True iff the command named ``name`` runs code it reads: a shell or a script interpreter."""
    return bool(name) and (name in sp.SHELLS or bool(sp._SCRIPT_INTERP_RE.match(name)))


def _code_text(site, res) -> str:
    """What an interpreter command is handed as code: its arguments and the bodies of the heredocs
    and here-strings that feed it."""
    parts = [w.raw.text for w in res.args]
    for red in site.cmd.redirects:
        if red.hd is not None:
            parts.append(red.hd.body)
        elif red.op == '<<<' and red.target is not None:
            parts.append(red.target.raw.text)
    return ' '.join(parts)


def _harness_launch(res, worktree_path: str, main_root: str = '') -> bool:
    """True iff an interpreter command's first argument is a harness script (``_harness_script``)."""
    return bool(res.args) and _harness_script(_word_path(res.args[0]), worktree_path, main_root)


def _interpreter_runs(command: str, worktree_path: str = '', main_root: str = '') -> list:
    """(site, resolved) of each interpreter the command launches, but a launch of a harness script."""
    return [(site, res) for site, res in _read(command).resolved
            if _interpreter(res.name) and not _harness_launch(res, worktree_path, main_root)]


def _cd_target(res, cwd: str):
    """(directory, known) after a `cd`/`pushd`: unknown for a bare `cd`, `cd -`, `~` or a computed one."""
    ops = [w for w in res.args if not (w.value() or '').startswith('-') or w.value() == '-']
    if not ops:
        return None, False
    v = ops[0].value()
    if v is None or v == '-' or v.startswith('~'):
        return None, False
    return os.path.join(cwd, v), True


def _git_of(site, res) -> list:
    """The git invocations one command runs (with a git alias body it defines), or, for a command
    that is not git, that it hands its words to: from the first word past the command word that
    names git when the parser does not peel the wrapper (`xargs -i git ...`), and the commands a
    string argument or a heredoc / here-string fed to it holds (`echo "git checkout x"`,
    `. /dev/stdin <<< 'git clean -fd'`), read as shell text."""
    one = sp.Script([(sp.Pipeline([site.cmd], ()), None)], site.script.source, site.cmd.span)
    found = sp.git_invocations(one, into=('alias',))
    if found or res.name == 'git':
        return found
    words = list(site.cmd.words)
    for k, w in enumerate(words[1:], 1):
        if os.path.basename(w.value() or '') == 'git':
            return sp.git_invocations(' '.join(x.raw.text for x in words[k:]))
    if res.payload is not None:
        return []
    texts = [w.value() for w in res.args] + [r.hd.body if r.hd is not None else r.target.value()
                                            for r in site.cmd.redirects if r.op in ('<<', '<<-', '<<<')]
    return [inv for t in texts if t and 'git' in t
            for inv in sp.git_invocations(sp.parse(t), strings=True)]


def _git_runs(command: str, payload_cwd: str) -> list:
    """(GitInvocation, cwd, cwd_known) for each git invocation the command runs, or that a command
    other than git names in its words, with the directory a preceding `cd`/`pushd` moved to
    (``cwd`` is None when none did). A wrapper option with a value (`env -C <dir>`, `sudo -D <dir>`)
    may move the directory too, so behind one the directory is not known."""
    out = []
    cwd, known = None, True
    for site, res in _read(command).resolved:
        if res.name in ('cd', 'pushd'):
            cwd, known = _cd_target(res, cwd or payload_cwd)
        moved = any(v is not None for _name, opts in res.wrappers for _o, v in opts)
        out.extend((inv, cwd, known and not moved) for inv in _git_of(site, res))
    return out


def _assigned(command: str, names: tuple) -> list[str]:
    """The values the command gives these environment names: a prefix assignment, or a NAME=value
    argument (`export`, `env`, `declare`); a computed value as written."""
    out = []
    for site, res in _read(command).resolved:
        for a in site.cmd.assignments:
            if a.name in names and a.value is not None:
                out.append(_word_text(a.value))
        for w in site.cmd.words[1:]:
            name, eq, _v = (w.value() or _word_text(w)).partition('=')
            if eq and name in names:
                out.append(_word_text(w).partition('=')[2])
    return out


def is_hooks_path(file_path: str) -> bool:
    """Check if a file path lies in a Claude configuration hooks/ folder, by where it is (lib/locations)."""
    return locations.config_folder(file_path.replace('\\', '/')) == 'hooks'


def is_commands_path(file_path: str) -> bool:
    """Check if a file path lies in a Claude configuration commands/ folder, by where it is."""
    return locations.config_folder(file_path.replace('\\', '/')) == 'commands'


def is_state_file_path(file_path: str) -> bool:
    """Check if a file path targets an overnight state file."""
    normalized = file_path.replace('\\', '/')
    return 'overnight-state-' in normalized and normalized.endswith('.json')


def is_outside_worktree(file_path: str, worktree_path: str) -> bool:
    """Check if a file path is outside the worktree directory."""
    abs_file = os.path.realpath(os.path.abspath(file_path))
    abs_wt = os.path.realpath(os.path.abspath(worktree_path))
    return not abs_file.startswith(abs_wt + os.sep) and abs_file != abs_wt


def check_bash_targets_state(command: str) -> bool:
    """True iff the command writes, moves or deletes an overnight-state file, or names one in a
    command the parser cannot read."""
    r = _read(command)
    if r.unreadable and 'overnight-state-' in command:
        return True
    return any('overnight-state-' in _target_text(t) for t in r.targets)


def _block(message: str) -> None:
    """Write message to stderr and exit 2."""
    sys.stderr.write(message)
    sys.exit(2)


def _check_write_edit_security(tool_name: str, file_path: str) -> None:
    """Block Write/Edit to hooks, commands, or state files during overnight.

    A contract-authorized self_repair grant lets a hooks or commands path through; an
    overnight-state file is never grantable.
    """
    if is_hooks_path(file_path) and not _grant_skips_block(file_path):
        _block(
            '\nOVERNIGHT HOOK PROTECTION: Modifying .claude/hooks/ '
            'is blocked during overnight sessions.\n'
            f'Blocked: {tool_name} to {file_path}\n'
        )
    if is_commands_path(file_path) and not _grant_skips_block(file_path):
        _block(
            '\nOVERNIGHT COMMANDS PROTECTION: Modifying .claude/commands/ '
            'is blocked during overnight sessions.\n'
            f'Blocked: {tool_name} to {file_path}\n'
        )
    if is_state_file_path(file_path):
        _block(
            '\nOVERNIGHT STATE PROTECTION: Direct modification of '
            'overnight-state files is blocked.\n'
            f'Blocked: {tool_name} to {file_path}\n'
        )


def apply_global_security_checks(tool_name: str, tool_input: dict) -> None:
    """Block hooks/commands/state modifications for ALL sessions during any overnight. A Bash write
    to .claude/hooks/ or .claude/commands/ is pretool-claude-config-guard.py's refusal."""
    if tool_name in command_span.EDIT_TOOLS:
        _check_write_edit_security(tool_name, _edit_target(tool_name, tool_input))
    if tool_name == 'Bash' and check_bash_targets_state(tool_input.get('command', '')):
        _block('\nOVERNIGHT STATE PROTECTION: Modifying or deleting '
               'overnight-state-*.json via Bash is blocked.\n')


def _compose_up_redirects(command: str) -> frozenset:
    """The ids of the redirect target words of each `docker compose build|up` command (QA runs them)."""
    out = set()
    for site, res in _read(command).resolved:
        args = res.argv()
        if res.name == 'docker' and args[:1] == ['compose']:
            args = args[1:]
        elif res.name != 'docker-compose':
            continue
        if args[:1] in (['build'], ['up']):
            out.update(id(r.target) for r in site.cmd.redirects if r.target is not None)
    return frozenset(out)


def _block_worktree_string_violation(tool_name: str, path: str) -> None:
    """Block operation on a path outside the session's worktree."""
    _block(
        f'\nWORKTREE STRING ENFORCEMENT: Path does not contain "worktree".\n'
        f'Overnight sessions can only modify files in worktree directories.\n'
        f'Attempted: {tool_name} to {path}\n'
    )


def _check_write_edit_string(tool_name: str, tool_input: dict, worktree_path: str) -> None:
    """Block a Write/Edit outside the session worktree (self_repair-grant aware)."""
    file_path = _edit_target(tool_name, tool_input)
    if not file_path or _is_path_exempt(file_path) or _is_harness_state_exempt(file_path) or _grant_skips_block(file_path):
        return
    if is_outside_worktree(file_path, worktree_path):
        _block_worktree_string_violation(tool_name, file_path)


def _check_bash_string(tool_input: dict, worktree_path: str) -> None:
    """Block a Bash write outside the session worktree (self_repair-grant aware)."""
    for path in _bash_write_paths(tool_input.get('command', '')):
        if _is_path_exempt(path) or _is_harness_state_exempt(path) or _grant_skips_block(path):
            continue
        if is_outside_worktree(path, worktree_path):
            _block_worktree_string_violation('Bash', path)


def apply_worktree_string_check(tool_name: str, tool_input: dict, worktree_path: str) -> None:
    """Block when an overnight session writes outside its worktree_path."""
    if tool_name in command_span.EDIT_TOOLS:
        _check_write_edit_string(tool_name, tool_input, worktree_path)
    if tool_name == 'Bash':
        _check_bash_string(tool_input, worktree_path)


def _parse_hook_input() -> tuple[str, dict, str, dict]:
    """Parse PreToolUse JSON; the full payload is returned too, for grant resolution."""
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    return (data.get('tool_name', ''), data.get('tool_input', {}),
            data.get('session_id', ''), data)


def _payload_cwd(payload: dict) -> str:
    """Effective cwd: payload['cwd'], else $PWD, else os.getcwd()."""
    if isinstance(payload, dict):
        c = payload.get('cwd')
        if isinstance(c, str) and c:
            return c
    env_pwd = os.environ.get('PWD', '')
    if env_pwd:
        return env_pwd
    return os.getcwd()


def _is_cwd_in_worktree(worktree_paths: list[str], cwd: str | None = None) -> bool:
    """True if the effective cwd is inside an overnight worktree."""
    base = cwd if cwd else os.getcwd()
    cwd_real = os.path.realpath(base)
    return any(_path_under_prefix(cwd_real, wt) for wt in worktree_paths)


def _resolve_child_session(payload: dict) -> dict | None:
    """overnight_child: the overnight state of the session that
    dispatched the subagent (payload.session_id), which records its dispatch
    obligation. A pre-pull agent-index.json dev_session_id names it only
    for a dispatch without one (its transcript is read only for such an entry)."""
    if not isinstance(payload, dict):
        return None
    agent_id = payload.get('agent_id')
    if not agent_id:
        return None
    project_dir = str(Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd())))
    session_id = payload.get('session_id') or ''
    try:
        entry = _resolve_dev_registry_entry(agent_id, project_dir) if _resolve_dev_registry_entry else None
        if entry and entry.get('dev_session_id'):
            from lib import obligation
            own = obligation.resolve_own_obligation(session_id=session_id, agent_id=agent_id,
                                                    project_dir=project_dir)
            if not isinstance(own, obligation.Resolved):
                session_id = entry['dev_session_id']
    except Exception:
        return None
    return _load_session_state(session_id)


def _governing_state_for_cwd(cwd: str) -> dict | None:
    """Resolve the live overnight state whose worktree_path
    contains `cwd`. Lets the worktree_context path carry a governing state and
    run the same git enforcement as owner/child."""
    if not cwd:
        return None
    try:
        cwd_real = os.path.realpath(cwd)
    except Exception:
        cwd_real = cwd
    project_dir = Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))
    for sf in (project_dir / '.claude').glob('overnight-state-*.json'):
        state = _load_state(sf)
        if state is None or not _is_session_live(state):
            continue
        # `worktree_context` means the cwd is inside an ISOLATED worktree, a set
        # an in_place record contributes nothing to. Its root IS the main root,
        # so it would otherwise match EVERY cwd under main -- including another
        # session's worktree -- and become that actor's governing state.
        if state.get('isolation_kind') == 'in_place':
            continue
        wt = state.get('worktree_path', '') or ''
        if wt and _path_under_prefix(cwd_real, wt):
            return state
    return None


def _classify_actor(payload: dict, owner_state: dict | None,
                    wt_paths: list[str], cwd: str) -> tuple[str, dict | None]:
    """Classify the actor: overnight_owner | overnight_child | worktree_context
    | normal. Returns (classification, governing_state_or_None).

    A `normal` actor (concurrent user session on main) is NOT enforced, so the
    user's concurrent main session is never false-blocked (an ambiguous
    unregistered subagent falls back to `normal`).

    worktree_context carries the governing overnight state resolved from the
    cwd's worktree, so the enforce gate runs the same git block for an
    in-worktree actor whose owner/child resolution fails."""
    if owner_state is not None and _is_session_live(owner_state):
        return ('overnight_owner', owner_state)
    child_state = _resolve_child_session(payload)
    if child_state is not None and _is_session_live(child_state):
        return ('overnight_child', child_state)
    if _is_cwd_in_worktree(wt_paths, cwd):
        return ('worktree_context', _governing_state_for_cwd(cwd))
    return ('normal', None)


def _apply_session_enforcement(state: dict, tool_name: str, tool_input: dict) -> None:
    """Apply the session's worktree realpath enforcement."""
    apply_worktree_string_check(tool_name, tool_input, state.get('worktree_path', ''))


def _load_session_state(session_id: str) -> dict | None:
    """Load overnight state for the given session_id (None if missing)."""
    project_dir = Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))
    return get_overnight_state_for_session(project_dir, session_id) if session_id else None


_GIT_HOOK_SUPPRESS_RE = re.compile(
    r'(-c\s+core\.hooksPath\s*=|--config-env|'
    r'GIT_CONFIG_(COUNT|KEY|VALUE|GLOBAL|SYSTEM|NOSYSTEM|PARAMETERS)|'
    r'\bGIT_CONFIG\s*=|-c\s+core\.hooksPath=)', re.IGNORECASE)

# The keys whose value redirects or disables the keystone: core.hooksPath directly, and the
# config-include keys (include.path, includeIf.<cond>.path), which load a file that can set it.
# pretool-bash-safety.sh reads these three names from this module.
_HOOKS_REDIRECT_CONFIG_KEYS = ('core.hookspath', 'include.path')


def _config_key_redirects_keystone(key: str) -> bool:
    """True iff a git config KEY (lowercased, quotes already stripped) sets or
    includes a value that can redirect/disable the keystone's core.hooksPath:
    `core.hooksPath` directly, or any config-INCLUDE key (`include.path` /
    `includeIf.<condition>.path`). The includeIf condition may contain dots,
    colons, slashes and glob wildcards, so the match is suffix-anchored on the
    trailing `.path` (NOT the first `.path` substring inside the condition)."""
    k = key.strip().strip('\'"').lower()
    if k in _HOOKS_REDIRECT_CONFIG_KEYS:
        return True
    return k.startswith('includeif.') and k.endswith('.path')


def _git_invocation_injects_keystone_config(subtoks: list[str]) -> bool:
    """Token-aware config-firewall over ONE git invocation's argv (the tokens
    AFTER the `git` word, as pretool-bash-safety.sh passes them). Scans only the
    GLOBAL-OPTION region — the options BEFORE the first subcommand — for a
    keystone-redirecting config injection:
      * `-c <key>=<val>` / `-c<key>=<val>` (glued) where <key> redirects, OR
      * `--config-env[=]<key>=<ENV>` where <key> redirects.
    Value-taking git global options (`-C <dir>`, `--git-dir <d>`, …) have their
    operand skipped so an injection AFTER them is still scanned. A `-c` that
    appears AFTER the subcommand (e.g. `git grep -c PATTERN`) is NOT git's config
    option and is deliberately ignored, so legitimate ops are not over-blocked."""
    j = 0
    n = len(subtoks)
    while j < n:
        raw = subtoks[j]
        t = raw.strip('\'"')
        # `-c <key=val>` (separate token) — only valid as a git GLOBAL option.
        if t == '-c' and j + 1 < n:
            kv = subtoks[j + 1].strip('\'"')
            key = kv.split('=', 1)[0]
            if _config_key_redirects_keystone(key):
                return True
            j += 2
            continue
        # `-c<key=val>` glued form.
        if t.startswith('-c') and len(t) > 2 and not t.startswith('-C'):
            kv = t[2:]
            key = kv.split('=', 1)[0]
            if _config_key_redirects_keystone(key):
                return True
            j += 1
            continue
        # `--config-env <key=ENV>` / `--config-env=<key=ENV>`.
        if t == '--config-env' and j + 1 < n:
            key = subtoks[j + 1].strip('\'"').split('=', 1)[0]
            if _config_key_redirects_keystone(key):
                return True
            j += 2
            continue
        if t.startswith('--config-env='):
            key = t[len('--config-env='):].split('=', 1)[0]
            if _config_key_redirects_keystone(key):
                return True
            j += 1
            continue
        # `--` terminates git's option parsing — no global config option can
        # follow, so stop scanning.
        if t == '--':
            break
        # Any other value-taking git global option (`-C <dir>`, `--git-dir <d>`,
        # …, from the classifier's option table): skip BOTH the option and its
        # operand so a later `-c` injection is still reached. The
        # glued `-C<dir>` / `--git-dir=<d>` forms carry the value in-token and
        # consume no separate operand.
        if t in GIT_GLOBAL_VALUE_OPTS:
            j += 2
            continue
        if (t.startswith('-C') and len(t) > 2) or any(
                t.startswith(o + '=') for o in GIT_GLOBAL_VALUE_OPTS):
            j += 1
            continue
        # Reaching the first non-option token ends the git global-option region:
        # everything after it is the subcommand and its args (a `-c` there is the
        # subcommand's own flag, not git's config option).
        if not t.startswith('-'):
            break
        # Any other lone option flag (e.g. `--no-pager`, `--bare`, `--paginate`)
        # takes no operand → advance one and keep scanning the global region.
        j += 1
    return False


# `git config` reads and the forms that open, remove or rename (a section of) the config.
_CONFIG_READ_FLAGS = git_facts.GIT_CONFIG_READ_OPTIONS
_CONFIG_SECTION_OPS = {'--remove-section', '--rename-section', 'remove-section', 'rename-section'}
_CONFIG_EDIT_OPS = {'-e', '--edit', 'edit'}
_CONFIG_VALUE_OPTS = {'-f', '--file', '--blob', '--type', '--default', '--comment', '--url'}
_EXPANSION_RE = re.compile(r'\$(?:[A-Za-z_0-9]+|[@*#?$!-])|`')


def _key_may_be_keystone(word: str) -> bool:
    """True iff the (unquoted, lowercased) config key operand is, or can expand at run time to, a
    key that redirects the keystone. An expansion (`$K`) matches any text, so `$K` and `core.$K` can
    be `core.hookspath` while `alias.$name` cannot."""
    if not _EXPANSION_RE.search(word):
        return _config_key_redirects_keystone(word)
    pat = '.*'.join(re.escape(part) for part in _EXPANSION_RE.split(word))
    if any(re.fullmatch(pat, key) for key in _HOOKS_REDIRECT_CONFIG_KEYS):
        return True
    return word.startswith('includeif.') or bool(re.fullmatch(pat, 'includeif.x.path'))


def _config_key_operand(args: list[str]) -> str:
    """The key operand of a `git config` write: the first word that is not an option, an
    option's value, or the leading verb (`set`, `unset`, ...); '' when there is none."""
    words: list[str] = []
    skip = False
    for i, a in enumerate(args):
        if skip:
            skip = False
        elif a == '--':
            words += args[i + 1:]
            break
        elif a in _CONFIG_VALUE_OPTS:
            skip = True
        elif not a.startswith('-'):
            words.append(a)
    if words and words[0] in git_facts.GIT_CONFIG_READ_SUBCOMMANDS | git_facts.GIT_CONFIG_WRITE_SUBCOMMANDS:
        words = words[1:]
    return words[0] if words else ''


def _config_args(inv) -> list[str]:
    """The arguments of a `git config` as git compares them: lowercased, each expansion written `$_`."""
    return [''.join(p.text if p.kind == 'lit' else '$_' for p in w.parts).lower() for w in inv.arg_words]


def _config_reads(args: list[str]) -> bool:
    opts = args[:args.index('--')] if '--' in args else args
    words = [a for a in opts if not a.startswith('-')]
    return any(a in _CONFIG_READ_FLAGS for a in opts) or (words[:1] and words[0] in git_facts.GIT_CONFIG_READ_SUBCOMMANDS)


def _config_writes_keystone(inv) -> bool:
    """True iff this git invocation is a `git config` that is not a pure read and names the
    keystone key (core.hooksPath, include.path, includeIf.*.path) or builds the key operand from
    an expansion that could be one, removes or renames the `core` section, or opens the config in
    an editor."""
    if inv.subcommand != 'config':
        return False
    args = _config_args(inv)
    opts = args[:args.index('--')] if '--' in args else args  # after `--` every word is a value
    words = [a for a in opts if not a.startswith('-')]
    verb = words[0] if words else ''  # `git config get|set|unset|edit|remove-section ...`
    if verb in _CONFIG_EDIT_OPS or any(a in _CONFIG_EDIT_OPS for a in opts if a.startswith('-')):
        return True
    if (verb in _CONFIG_SECTION_OPS or any(a in _CONFIG_SECTION_OPS for a in opts if a.startswith('-'))) \
            and 'core' in args:
        return True
    if _config_reads(args):
        return False
    key = _config_key_operand(args)
    return (bool(key) and _key_may_be_keystone(key)) or any(
        _config_key_redirects_keystone(a.split('=', 1)[0]) for a in args)


def _injects_keystone_config(command: str, runs: list) -> bool:
    """True iff a command it runs sets git's config through the environment (GIT_CONFIG_*,
    --config-env) or a git invocation's own config (-c, --config-env, GIT_CONFIG_*) names a key
    that redirects the keystone."""
    for site, _res in _read(command).resolved:
        words = [a.word for a in site.cmd.assignments] + list(site.cmd.words)
        if any(_GIT_HOOK_SUPPRESS_RE.search(w.raw.text) for w in words):
            return True
    return any(key is not None and _config_key_redirects_keystone(key)
               for inv, _c, _k in runs for key, _v in inv.config_pairs)


# The per-worktree config file: with extensions.worktreeConfig on, git reads
# `<gitdir>/config.worktree` after the shared config, so a core.hooksPath or include.path in it
# redirects the keystone for that worktree. bubblewrap's read-only rebind covers `<common>/config`
# and `<common>/hooks` only; the file sits in the per-worktree git dir, which stays writable.
_WORKTREE_CONFIG_LEAF = 'config.worktree'
# The keystone hook dir, `<common>/<leaf>` (scripts/install-git-keystone.sh creates it and points
# core.hooksPath at it): `chmod -x` or a copy onto its reference-transaction turns the keystone off.
_KEYSTONE_HOOKS_LEAF = 'keystone-hooks'
# Commands that write their file operands which the parser's write table does not hold.
_EDITORS = {'touch', 'ed', 'ex', 'vi', 'vim', 'nano', 'emacs', 'awk', 'gawk'}
# a path built from a query for git's own directories (the plain `--show-toplevel` is not one)
_GIT_DIR_QUERY_RE = re.compile(r'git[_-]?(?:common[_-]?)?dir|git[_-]?path', re.I)


def _names_worktree_config(word: str) -> bool:
    """True iff this shell word is, or as a glob can match, the leaf `config.worktree`."""
    w = re.sub(r'[\\\'"]', '', word).lower()
    leaf = w.rsplit('/', 1)[-1]
    return _WORKTREE_CONFIG_LEAF in w or (bool(re.search(r'[*?\[]', leaf)) and fnmatch.fnmatchcase(
        _WORKTREE_CONFIG_LEAF, leaf))


def _builds_git_dir_path(word) -> bool:
    """True iff a word holds an expansion and names a query for git's own directory."""
    return any(p.kind != 'lit' for p in word.parts) and bool(_GIT_DIR_QUERY_RE.search(word.raw.text))


def _command_writes_worktree_config(command: str, runs: list = None) -> bool:
    """True iff the command writes the per-worktree git config file, in any mode: a write target,
    an operand of an interpreter or editor, or a word of a `git config` that is not a read, that
    names `config.worktree` (also as a glob); or a write target built from a query for git's
    directory (`$(git rev-parse --git-dir)/...`), which names it at run time."""
    r = _read(command)
    for t in r.targets:
        if t.word is not None and (_names_worktree_config(t.word.raw.text) or _builds_git_dir_path(t.word)):
            return True
    for site, res in r.resolved:
        if (_interpreter(res.name) or res.name in _EDITORS) and _names_worktree_config(_code_text(site, res)):
            return True
    runs = _git_runs(command, _payload_cwd(_REQUEST_CTX.get('payload') or {})) if runs is None else runs
    return any(inv.subcommand == 'config' and not _config_reads(_config_args(inv))
               and any(_names_worktree_config(w.raw.text) for w in inv.arg_words) for inv, _c, _k in runs)


# Per-request working root of the record governing this actor, for `in_place`
# records only. Two questions are kept apart:
#   which roots are write-confinement targets for EVERY session -- an in_place
#       record must NOT contribute (see `_extract_live_worktree_path`: its root
#       IS the main checkout, and on the shared allow-list it would hand a
#       concurrent isolated session write access to the tree its isolation
#       exists to protect);
#   which root is the legitimate working root of a GIVEN live record, used to
#       decide whether a git op is main-targeting -- an in_place record MUST
#       contribute, or its own session cannot run git at all in the root it was
#       told to work in. in_place is the DEFAULT mode.
# The second is answered PER REQUEST, scoped to the record governing THIS actor,
# so a concurrently running isolated session still sees the main root as fully
# main-targeting.
#
# LAYERING DEPENDENCY, DO NOT ASSUME THIS LAYER COVERS IT. Every protected-branch
# rule in this file is COMMAND-SHAPED: it matches argv and never resolves HEAD,
# so it cannot see that an ordinary permitted `commit` advances the protected
# branch when HEAD is attached to it. Under in_place that STATEFUL case is owned
# by two other layers:
#   * `scripts/create-overnight-state.sh` refuses to launch in-place mode while
#     the checkout is on the protected branch; and
#   * the git-native `hooks/git-keystone/reference-transaction`, which denies
#     the ref move itself (`OVERNIGHT-KEYSTONE-DENY reason=branch_protected`).
# Neither may be removed on the assumption that this PreToolUse guard covers the
# stateful case.
_GOVERNING_OWN_ROOT: str = ''


def _set_governing_own_root(gov_state: dict | None,
                            payload: dict | None = None) -> None:
    """Record the governing state's own working root, for `in_place` only.

    Isolated records already answer it through `_get_active_worktree_paths()`, so they set nothing
    here and the main root stays fully guarded for every isolated actor. The root must lie under the
    record's own `main_root`, so the widest it reaches is the checkout the guard is scoped to.

    The identity must be UNCONTRADICTED: the record the payload's session_id names and the record
    its agent_id maps to (dev_session_id) must, where live, be the same one; otherwise the root stays
    '' (which blocks), so an isolated actor cannot borrow the exemption through a stale index entry
    and the result does not depend on the order `_classify_actor` consults them in.
    """
    global _GOVERNING_OWN_ROOT
    _GOVERNING_OWN_ROOT = ''
    if not isinstance(gov_state, dict) or gov_state.get('isolation_kind') != 'in_place':
        return
    gov_sid = gov_state.get('session_id') or ''
    for ident in (_load_session_state((payload or {}).get('session_id') or ''),
                  _resolve_child_session(payload) if isinstance(payload, dict) else None):
        if ident is None or not _is_session_live(ident):
            continue  # silent identity: no opinion, so nothing to contradict
        ident_sid = ident.get('session_id') or ''
        if not (gov_sid and ident_sid and gov_sid == ident_sid):
            return
    own = gov_state.get('worktree_path', '') or ''
    main = gov_state.get('main_root', '') or ''
    if own and main and _path_under_prefix(own, main):
        _GOVERNING_OWN_ROOT = own


def _path_targets_main(tgt_dir: str, main_real: str) -> bool:
    """True iff tgt_dir resolves UNDER main_root but OUTSIDE every active
    overnight worktree. A worktree physically lives under .claude/worktrees but is an
    independent checkout, so it is NOT main-targeting.

    The governing record's OWN working root is likewise not
    main-targeting FOR THAT RECORD'S ACTOR. Under `in_place` that root IS the
    main root, so without this the actor's own checkout is unreachable.
    """
    if not main_real or not tgt_dir:
        return False
    if not _path_under_prefix(tgt_dir, main_real):
        return False
    if _GOVERNING_OWN_ROOT and _path_under_prefix(tgt_dir, _GOVERNING_OWN_ROOT):
        return False
    for wt in _get_active_worktree_paths():
        if _path_under_prefix(tgt_dir, wt):
            return False
    return True


def _into_main_git_dir(values: list[str], main_real: str, main_git_dir: str) -> bool:
    """True iff one of these --git-dir / GIT_DIR / GIT_COMMON_DIR values names the main repo's git dir."""
    if not main_real:
        return False
    main_gd = os.path.realpath(main_git_dir) if main_git_dir else os.path.join(main_real, '.git')
    for c in values:
        cr = os.path.realpath(c.strip('\'"'))
        if cr == main_gd or cr == main_real or cr.startswith(main_gd.rstrip('/') + os.sep):
            return True
    return False


def _into_main_work_tree(values: list[str], main_real: str) -> bool:
    """True iff one of these --work-tree / GIT_WORK_TREE values is under main_root and outside every
    active worktree: git then writes the main working directory even with an in-worktree -C."""
    return bool(main_real) and any(
        c.strip('\'"') and _path_targets_main(os.path.realpath(c.strip('\'"')), main_real) for c in values)


def _git_option_values(command: str, option: str, env_names: tuple) -> list[str]:
    """The values the command gives a git global option (`--git-dir`, `--work-tree`) and the
    environment names that stand for it."""
    out = _assigned(command, env_names)
    for inv, _c, _k in _git_runs(command, ''):
        out.extend(v for o, v in inv.global_opts if o == option and v is not None)
    return out


_GIT_TOKEN_RE = re.compile(r'(?<![\w./-])(?:/[\w./-]*/)?git\b')
_DANGEROUS_GIT_OP_RE = re.compile(
    r'\b(checkout|switch|reset|restore|clean|stash|update-ref|symbolic-ref|'
    r'branch|merge|rebase|pull|cherry-pick|am|worktree)\b')
_TEXT_GIT_DIR_RE = re.compile(r'(?:--git-dir(?:=|\s+)|GIT_DIR=|GIT_COMMON_DIR=)(\S+)')
_TEXT_WORK_TREE_RE = re.compile(r'(?:--work-tree(?:=|\s+)|GIT_WORK_TREE=)(\S+)')


def _gitdir_into_main(command: str, main_real: str, main_git_dir: str) -> bool:
    """True iff --git-dir / GIT_DIR / GIT_COMMON_DIR redirect a git op into the main repo's git dir."""
    return _into_main_git_dir(_git_option_values(command, '--git-dir', ('GIT_DIR', 'GIT_COMMON_DIR')),
                              main_real, main_git_dir)


def _worktree_into_main(command: str, main_real: str) -> bool:
    """True iff --work-tree / GIT_WORK_TREE point a git op at the main working directory."""
    return _into_main_work_tree(_git_option_values(command, '--work-tree', ('GIT_WORK_TREE',)), main_real)


def _script_hides_main_git(site, res, command: str, main_real: str, worktree_path: str) -> bool:
    """True iff a script file an interpreter runs holds a dangerous git op that names main_root, a
    protected branch, a -C, or a checkout/switch. A script operand it cannot read fails closed
    when the command names main_root."""
    for w in res.args:
        t = _word_path(w)
        if not t or t.startswith('-') or _harness_script(t, worktree_path, main_real):
            continue
        looks_script = bool(re.search(r'\.(py|sh|bash|rb|pl|js|mjs|cjs)$', t))
        is_file = os.path.isfile(t)
        if not (looks_script or is_file):
            continue
        if is_file and os.access(t, os.R_OK):
            body = Path(t).read_text(errors='replace')
            if _GIT_TOKEN_RE.search(body) and _DANGEROUS_GIT_OP_RE.search(body):
                if (main_real and main_real in body) or _body_mentions_protected_branch(body) \
                   or re.search(r'-C\s+\S', body) or 'checkout' in body or 'switch' in body:
                    return True
        elif main_real and main_real in command:
            return True
    return False


def _scan_script_files_for_main_git(command: str, main_real: str, worktree_path: str = '') -> bool:
    """True iff an interpreter the command launches runs a script file that hides a main-targeting
    git op (``_script_hides_main_git``)."""
    return any(_script_hides_main_git(site, res, command, main_real, worktree_path)
               for site, res in _interpreter_runs(command, worktree_path, main_real))


def _interpreter_hides_main_git(command: str, main_real: str, main_git_dir: str,
                                worktree_path: str = '') -> bool:
    """True iff an interpreter the command launches (a harness script's launch aside) is handed
    code with a dangerous git op that targets main: a --git-dir / --work-tree / GIT_DIR into main,
    main_root's path, a protected branch, or a checkout/switch/reset/restore with no -C and no
    worktree path, whose directory is the launcher's and cannot be proven the worktree. Code with
    no git in it is read for the script files it runs."""
    for site, res in _interpreter_runs(command, worktree_path, main_real):
        code = _code_text(site, res)
        if not _GIT_TOKEN_RE.search(code):
            if _script_hides_main_git(site, res, command, main_real, worktree_path):
                return True
            continue
        if not _DANGEROUS_GIT_OP_RE.search(code):
            continue
        if _into_main_git_dir(_TEXT_GIT_DIR_RE.findall(code), main_real, main_git_dir) \
                or _into_main_work_tree(_TEXT_WORK_TREE_RE.findall(code), main_real) \
                or (main_real and main_real in code) or _mentions_protected_branch(code.split()):
            return True
        if re.search(r'\b(checkout|switch|reset|restore)\b', code) \
           and not re.search(r'-C\s+\S', code) and not _mentions_worktree_path(code):
            return True
    return False


def _mentions_worktree_path(command: str) -> bool:
    """True iff the text mentions an active worktree path (so a worktree-qualified op is not
    falsely flagged main-targeting)."""
    return any(wt and wt in command for wt in _get_active_worktree_paths())


_KEYSTONE_CONFIG_BLOCK = (
    '\nOVERNIGHT KEYSTONE CONFIG BLOCK: a git config write that names the keystone '
    '(core.hooksPath, include.path, includeIf.*.path), builds that key from an expansion, removes or '
    'renames the core section, or edits the config is forbidden for overnight actors; the keystone '
    'stays as the launcher set it. Reading it (--get, --list) is allowed.\n')
# git subcommands that move HEAD or write the working tree, refused after a `cd` that cannot be read
_HEAD_MOVERS = ('checkout', 'switch', 'reset', 'restore', 'clean', 'stash', 'update-ref', 'symbolic-ref',
                'branch', 'merge', 'rebase', 'cherry-pick', 'am', 'pull')


def _git_run_dir(inv, cwd: str | None, payload_cwd: str) -> str:
    """The directory a git invocation runs in: its -C values, applied in order, over the directory
    a `cd` moved to, else the actor's cwd (a computed -C is read as a directory below that one)."""
    base = cwd or payload_cwd
    for d in inv.C_dirs:
        base = os.path.join(base or '', d if d is not None else '$')
    return os.path.realpath(base) if base else ''


def _enforce_git_invocation(inv, cwd, cwd_known: bool, main_real: str, payload_cwd: str) -> None:
    """The main-root, ambiguous-cwd, branch-switch, main-write and worktree rules for one git
    invocation of an overnight actor."""
    sub = inv.subcommand
    has_C = bool(inv.C_dirs)
    tgt_dir = _git_run_dir(inv, cwd, payload_cwd)
    work_trees = [v for o, v in inv.global_opts if o == '--work-tree' and v is not None]
    targets_main = _path_targets_main(tgt_dir, main_real) or _into_main_work_tree(work_trees, main_real)
    positionals = [a for a in inv.args if a and not a.startswith('-')]
    switches_protected = _mentions_protected_branch(positionals)
    if _config_writes_keystone(inv):
        _block(_KEYSTONE_CONFIG_BLOCK)
    # `rev-parse` only reads (it runs no hook and writes no file), and Step 1 runs it in the main root.
    if targets_main and sub != 'rev-parse':
        _block(
            '\nOVERNIGHT MAIN-ROOT BLOCK: git op targeting the main '
            'working directory (effective -C/cwd under main_root, outside '
            'the isolated worktree) is forbidden for overnight actors.\n'
        )
    in_worktree = bool(tgt_dir) and any(_path_under_prefix(tgt_dir, w) for w in _get_active_worktree_paths())
    if not cwd_known and not has_C and sub in _HEAD_MOVERS:
        _block(
            f'\nOVERNIGHT AMBIGUOUS-CWD BLOCK: git {sub} after a directory change '
            'that cannot be read (a bare or computed cd, a wrapper\'s option) cannot be '
            'proven to run inside the isolated worktree; refused for '
            'overnight actors (it could target the main working '
            'directory).\n'
        )
    if sub in ('checkout', 'switch') and (targets_main or switches_protected or not in_worktree):
        _block(
            f'\nOVERNIGHT BRANCH-SWITCH BLOCK: git {sub} that could move '
            "the main worktree's HEAD off the protected branch is forbidden for "
            'overnight actors. Branch ops INSIDE the isolated worktree (non-protected target) '
            'are allowed.\n'
        )
    if sub in sp.GIT_WORKTREE_DISCARDERS - {'checkout', 'stash'} and (targets_main or switches_protected or not in_worktree):
        _block(
            f'\nOVERNIGHT MAIN-WRITE BLOCK: git {sub} that could write '
            'the main working directory is forbidden for overnight '
            'actors. Run it inside the isolated worktree instead.\n'
        )
    if sub == 'stash' and any(p in ('apply', 'pop') for p in positionals) and (targets_main or not in_worktree):
        _block(
            '\nOVERNIGHT MAIN-WRITE BLOCK: git stash apply/pop against '
            'the main working directory is forbidden for overnight '
            'actors.\n'
        )
    if sub == 'worktree' and positionals[:1] != ['list']:
        _block(
            '\nOVERNIGHT WORKTREE BLOCK: an overnight actor may not add, move, remove, prune, lock '
            'or repair git worktrees; `git worktree list` reads them.\n'
        )


def _enforce_overnight_git_command(command: str, main_root: str, worktree_path: str,
                                   main_git_dir: str = '') -> None:
    """For an overnight actor's Bash command, refuse: a command the parser cannot read; a git
    config override or keystone config write; a write onto a per-worktree config or onto the
    repository's git config; --git-dir / --work-tree into main; an interpreter hiding a
    main-targeting git op; and each git invocation's main-root, branch-switch and worktree rules."""
    if not command:
        return
    main_real = os.path.realpath(main_root) if main_root else ''
    payload_cwd = _payload_cwd(_REQUEST_CTX.get('payload') or {})
    if _read(command).unreadable:
        _block('\nOVERNIGHT UNREADABLE COMMAND: the shared Bash parser cannot read this command, so '
               'what it runs cannot be checked; refused for overnight actors. Write it in plain '
               'shell syntax.\n')
    runs = _git_runs(command, payload_cwd)
    if _injects_keystone_config(command, runs):
        _block(
            '\nOVERNIGHT CONFIG FIREWALL: git hook-suppression / config-override '
            '(-c core.hooksPath, -c include.path / includeIf.*.path, GIT_CONFIG_* '
            '(incl. GIT_CONFIG_PARAMETERS), --config-env) is forbidden for '
            'overnight actors — it would redirect/disable the reference-transaction '
            'keystone for the invocation (config-include bypass).\n'
        )
    if any(_config_writes_keystone(inv) for inv, _c, _k in runs):
        _block(_KEYSTONE_CONFIG_BLOCK)
    if _command_writes_worktree_config(command, runs):
        _block(
            '\nOVERNIGHT WORKTREE CONFIG BLOCK: a write onto a worktree\'s config.worktree (a redirect, '
            'tee, cp, mv, sed -i, ln, git config --file ...) or onto a path built from `git rev-parse '
            '--git-dir` is forbidden for overnight actors; with extensions.worktreeConfig on, '
            'that file can redirect core.hooksPath for the worktree. Reading it is allowed.\n'
        )
    # The Write/Edit check's paths, for each write target (a relative one against the payload cwd);
    # bubblewrap's read-only rebinds keep the rest off them. The paths are resolved once for the
    # command, so its cost does not grow with its operands.
    write_paths = _bash_write_paths(command)
    git_config_paths = _bash_git_config_paths(main_root, worktree_path, payload_cwd or os.getcwd()) \
        if write_paths else None
    for t in write_paths:
        path = os.path.join(payload_cwd or os.getcwd(), t)
        if not locations.is_device(path) and _targets_git_config(path, git_config_paths):
            _block_git_config('Bash', path)
    if _gitdir_into_main(command, main_real, main_git_dir):
        _block(
            '\nOVERNIGHT GIT-DIR REDIRECT BLOCK: a git op redirected into the '
            'main repo (--git-dir / GIT_DIR / GIT_COMMON_DIR -> main/.git) is '
            'forbidden for overnight actors.\n'
        )
    if _worktree_into_main(command, main_real):
        _block(
            '\nOVERNIGHT WORK-TREE REDIRECT BLOCK: a git op redirected at the '
            'main working directory (--work-tree / GIT_WORK_TREE -> main, '
            'outside the isolated worktree) is forbidden for overnight actors — '
            'it would write the main worktree in place.\n'
        )
    if _interpreter_hides_main_git(command, main_real, main_git_dir, worktree_path):
        _block(
            '\nOVERNIGHT SUBPROCESS GIT BLOCK: an interpreter/subprocess that '
            'could run a main-targeting git op (checkout/switch/reset/protected-branch '
            'ref-move against the main working directory) is forbidden for '
            'overnight actors. The reference-transaction keystone cannot catch a symref '
            'branch-switch, so it is blocked here before execution. Run git ops INSIDE the '
            'isolated worktree instead.\n'
        )
    for inv, cwd, known in runs:
        _enforce_git_invocation(inv, cwd, known, main_real, payload_cwd)


def _fail_closed_worktree_context(command: str) -> None:
    """An in-worktree actor with no resolvable governing overnight state cannot have its main_root
    derived for a targeted block: any command that runs git or an interpreter (or that the parser
    cannot read) is refused; other commands are left to the worktree-boundary enforcement."""
    r = _read(command)
    if r.unreadable or any(res.name == 'git' or _interpreter(res.name) for _s, res in r.resolved) \
            or _git_runs(command, ''):
        _block(
            '\nOVERNIGHT WORKTREE-CONTEXT FAIL-CLOSED: a git/interpreter command '
            'is running inside an overnight worktree but no governing overnight '
            'state could be resolved to scope a targeted main-root block. '
            'Refusing fail-closed — it could move the main HEAD off the protected branch or '
            'write the main working directory. Run from a session whose '
            'overnight state is resolvable.\n'
        )



def _block_invalid_isolation(classification: str) -> None:
    """A null/missing worktree in an owner/child state is INVALID isolation
    and BLOCKS the actor (it must not silently no-op into no-enforcement)."""
    _block(
        '\nOVERNIGHT ISOLATION INVALID: the governing overnight state has no '
        f'valid worktree_path (actor={classification}). Refusing the operation; '
        'the overnight actor must run inside a validated isolated worktree.\n'
    )


# ---------------------------------------------------------------------------
# The write half: a per-Bash-command bwrap execution boundary. For the overnight
# actor, the Bash command is re-exec'd inside a bwrap mount namespace where the
# PROTECTED MAIN working tree (main_root minus the registered worktree_path) is
# bind-mounted READ-ONLY and the overnight worktree READ-WRITE, so the kernel
# refuses every shell write into the main checkout (EROFS), whatever the shell
# expression.
#
# Order: the security and raw-metadata checks (apply_global_security_checks,
# _enforce_overnight_git_command) run FIRST in main(); the bwrap rewrite runs
# after them and ends the hook by emitting hookSpecificOutput.updatedInput.command.
#
# Fail-CLOSED: if bwrap/userns is unavailable, an actor's Bash command that
# cannot be proven entirely worktree-local is DENIED. Isolation/worktree creation
# is never gated on bwrap (the launch already created the worktree); only the
# per-command write boundary is.

_BWRAP_BIN = None  # resolved lazily


def _resolve_bwrap() -> str | None:
    """Resolve the bwrap binary path; None if bubblewrap is not installed."""
    global _BWRAP_BIN
    if _BWRAP_BIN is not None:
        return _BWRAP_BIN or None
    for cand in ('/usr/bin/bwrap', '/bin/bwrap'):
        if os.path.exists(cand):
            _BWRAP_BIN = cand
            return cand
    found = shutil.which('bwrap')
    _BWRAP_BIN = found or ''
    return found


def _userns_available() -> bool:
    """True iff unprivileged user namespaces are usable (the kernel facility the
    bwrap mount namespace depends on). Root with userns=1 -> available."""
    try:
        with open('/proc/sys/kernel/unprivileged_userns_clone') as fh:
            if fh.read().strip() == '0' and os.geteuid() != 0:
                return False
    except OSError:
        pass  # file absent on some kernels; rely on bwrap's own probe
    return True


def _bwrap_boundary_available() -> bool:
    """The per-command write boundary can be built iff bwrap is installed AND a
    user namespace is usable. This gates the WRITE guarantee (not isolation).

    Honors CLAUDE_OVERNIGHT_FORCE_NO_BWRAP=1 — a test/operator seam to simulate a
    bwrap-unavailable host so the fail-closed degradation can be
    exercised deterministically without uninstalling bubblewrap."""
    if os.environ.get('CLAUDE_OVERNIGHT_FORCE_NO_BWRAP') == '1':
        return False
    return bool(_resolve_bwrap()) and _userns_available()


def _git_query(args: list[str], cwd: str) -> str:
    """Run a read-only git query in cwd; return stripped stdout ('' on error)."""
    try:
        import subprocess  # local import: only needed on the boundary path
        e = dict(os.environ)
        e.pop('CLAUDE_OVERNIGHT_ACTOR', None)  # never let the actor gate fire here
        p = subprocess.run(['git', *args], cwd=cwd, env=e,
                           capture_output=True, text=True, timeout=10)
        return p.stdout.strip() if p.returncode == 0 else ''
    except Exception:
        return ''


def _linked_worktree_git_paths(worktree_path: str) -> list[str]:
    """The .git metadata paths a LINKED worktree needs RW so add/commit/status/diff work inside the
    boundary, derived from git itself: the per-worktree gitdir and the shared common-dir. They are
    RW-bound over the RO main tree; `<common>/config` and `<common>/hooks` are re-bound READ-ONLY
    over that bind (`_shared_common_dir_ro_rebinds`). `gc`/`fetch`/`repack` writes under
    common-dir/objects are not refused by this boundary. A raw write to refs/objects/HEAD/
    packed-refs that bypasses git's ref transaction is refused before the boundary
    (`_raw_git_metadata_write_into_main`)."""
    gd = _git_query(['rev-parse', '--path-format=absolute', '--git-dir'], worktree_path)
    gcd = _git_query(['rev-parse', '--path-format=absolute', '--git-common-dir'], worktree_path)
    paths: list[str] = []
    for p in (gd, gcd):
        if p and os.path.exists(p):
            rp = os.path.realpath(p)
            if rp not in paths:
                paths.append(rp)
    return paths


def _shared_common_dir_ro_rebinds(worktree_path: str) -> list[str]:
    """The shared git COMMON-DIR is RW-bound (via `_linked_worktree_git_paths`) so the
    supported add/commit/status/diff surface works — but that ALSO exposes
    `<common>/config` and `<common>/hooks` READ-WRITE, letting an overnight actor
    run `git config --unset core.hooksPath` (writes `<common>/config`) to DISABLE
    the reference-transaction keystone, or drop a malicious default hook, and THEN
    move main HEAD off the protected branch, or `chmod -x` the keystone hook itself. Return
    `--ro-bind` args for the shared common-dir's `config` FILE, `hooks/` DIR and keystone hook DIR
    (`_KEYSTONE_HOOKS_LEAF`; only those that exist) so the caller can nest
    them OVER the RW common-dir bind: those three paths become EROFS while
    `<common>/objects`, `<common>/refs`, `<common>/logs` (which a commit / ref
    update actually writes) stay READ-WRITE. Only the SHARED common-dir is treated
    this way; the per-worktree gitdir is untouched. `git rev-parse --git-common-dir`
    resolves the shared common-dir from a LINKED worktree (whose `.git` is a FILE
    pointing at `<common>/worktrees/<name>`) — never the per-worktree gitdir."""
    gcd = _git_query(['rev-parse', '--path-format=absolute', '--git-common-dir'], worktree_path)
    if not gcd or not os.path.isdir(gcd):
        return []
    common_real = os.path.realpath(gcd)
    args: list[str] = []
    for leaf in GIT_COMMON_DIR_PROTECTED + (_KEYSTONE_HOOKS_LEAF,):
        p = os.path.join(common_real, leaf)
        if os.path.exists(p):
            args += ['--ro-bind', p, p]
    return args


def _build_bwrap_argv(command: str, main_root: str, worktree_path: str,
                      isolation_kind: str, journal: tuple = ()) -> list[str] | None:
    """Build the bwrap argv that re-execs `command` with the PROTECTED MAIN tree
    RO and the overnight worktree RW. Returns None if the layout cannot be built.

    Canonical mount order (no RW alias of main):
      1. --ro-bind / /            entire host RO (so no path reaches main RW via
                                  a second bind, incl. a /dev/shm-resident main)
      2. --dev /dev               private devtmpfs (writable /dev/null git needs);
                                  it shadows the real /dev/shm, so:
      3. --ro-bind /dev/shm /dev/shm   restore the REAL /dev/shm RO (a main_root
                                  resident under /dev/shm must stay RO, not fall
                                  into the private --dev tmpfs)
      4. --proc /proc, --tmpfs /tmp, --unshare-pid   private proc/PID + tmp
      5. --bind <worktree_path>   the ONLY RW path under main (nested over RO)
      6. --bind <git-dir>, <common-dir>   (LINKED worktree only) git-derived RW
                                  exceptions for the supported add/commit surface
      7. --ro-bind <common>/config, <common>/hooks, the keystone hook dir
                                  (LINKED worktree only) RE-bind the shared config
                                  file + default-hooks dir + keystone hook dir READ-
                                  ONLY, nested OVER step 6's RW common-dir bind, so
                                  a keystone-disabling `git config --unset
                                  core.hooksPath` / hook drop hits EROFS while
                                  objects/refs/logs stay RW for commits
    Because every RW bind is applied AFTER the RO binds, and each RW bind targets
    a path UNDER main that is itself an approved exception, no mount exposes a RW
    source/root covering the protected main tree except the worktree + git paths.
    --unshare-pid gives a private PID view; --proc /proc a private /proc so a
    /proc/<pid>/root re-entry cannot reach a RW alias of main."""
    bwrap = _resolve_bwrap()
    if not bwrap or not main_root or not worktree_path:
        return None
    main_real = os.path.realpath(main_root)
    wt_real = os.path.realpath(worktree_path)
    if not os.path.isdir(main_real) or not os.path.isdir(wt_real):
        return None
    argv = [
        bwrap,
        '--ro-bind', '/', '/',          # (1) entire host RO — no RW alias of main
        '--dev', '/dev',                # (2) private /dev (writable /dev/null for git)
    ]
    if os.path.isdir('/dev/shm'):       # (3) restore real /dev/shm RO (un-shadow)
        argv += ['--ro-bind', '/dev/shm', '/dev/shm']
    argv += [
        '--proc', '/proc',              # (4) private /proc (blocks /proc/<pid>/root re-entry)
        '--tmpfs', '/tmp',              # private writable /tmp (never aliases main)
        '--unshare-pid',                # private PID namespace
        '--die-with-parent',
        '--bind', wt_real, wt_real,     # (5) the worktree: RW, nested over RO main
    ]
    # A TMPDIR outside /tmp (settings.json pins one) is private and writable too, as /tmp is, or
    # every mktemp of the command fails on the RO host; never one holding main or the worktree.
    tmp = os.path.realpath(os.environ.get('TMPDIR') or locations.DEFAULT_TEMP_DIR)
    if os.path.isdir(tmp) and not _path_under_prefix(tmp, locations.DEFAULT_TEMP_DIR) and not any(
            _path_under_prefix(r, tmp) or _path_under_prefix(tmp, r) for r in (main_real, wt_real)):
        argv += ['--tmpfs', tmp]
    for d in journal:  # /restart's (_restart_journal): over the private tmps, under step 7's RO rebinds
        if not any(_path_under_prefix(r, d) for r in (main_real, wt_real)):  # never holding main or wt
            argv += ['--bind-try', d, d]
    # (4) LINKED worktree: RW-expose exactly the git-derived metadata paths the
    # supported surface needs. A fresh_clone worktree is self-contained (its .git
    # lives under the RW worktree already) -> ZERO .git exceptions.
    if isolation_kind != 'fresh_clone_checkout':
        for p in _linked_worktree_git_paths(wt_real):
            # Only expose paths OUTSIDE the worktree subtree (those under the
            # worktree are already RW via the worktree bind).
            if not _path_under_prefix(p, wt_real):
                argv += ['--bind', p, p]
        # (7) nest RO binds for
        # <common>/config + <common>/hooks + the keystone hook dir OVER the RW common-dir bind above, so a
        # keystone-disabling `git config --unset core.hooksPath` and default-hook
        # drops hit EROFS, while <common>/objects + <common>/refs + logs stay RW so
        # the legitimate keystone-guarded commit / ref-update path is unaffected.
        argv += _shared_common_dir_ro_rebinds(wt_real)
    argv += ['--', '/bin/bash', '-c', command]
    return argv


def _command_is_worktree_local(command: str, main_root: str, worktree_path: str,
                               main_git_dir: str) -> bool:
    """True iff `command` provably does not target the main tree: the parser reads it, it sends no
    git op into main (-C/--work-tree/--git-dir) and hides none in an interpreter, writes no path
    under main outside the worktree, and launches no interpreter but a harness script. Used when
    bwrap is unavailable: an actor's command that is not provably worktree-local is refused."""
    main_real = os.path.realpath(main_root) if main_root else ''
    if not main_real or _read(command).unreadable:
        return False
    if _worktree_into_main(command, main_real) or _gitdir_into_main(command, main_real, main_git_dir):
        return False
    if _interpreter_hides_main_git(command, main_real, main_git_dir, worktree_path):
        return False
    wt_real = os.path.realpath(worktree_path or '')
    for p in _bash_write_paths(command):
        rp = os.path.realpath(p)
        if _path_under_prefix(rp, main_real) and not _path_under_prefix(rp, wt_real):
            return False
    # an interpreter could write anywhere; one that runs a harness script is the harness's own code
    return not _interpreter_runs(command, worktree_path, main_root)


def _harness_script(operand: str, worktree_path: str, main_root: str = '') -> bool:
    """True iff `operand` (a path as the shell expands it) names a file of this harness's hooks/ or
    scripts/ that lies in neither the worktree nor the main root (there an actor can write it)."""
    t = operand.strip('\'"')
    if not os.path.isabs(t) or any(ch in t for ch in '$`*?[\\'):
        return False
    real = os.path.realpath(t)
    own = os.path.realpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if any(r and _path_under_prefix(real, os.path.realpath(r)) for r in (worktree_path, main_root)):
        return False
    return os.path.isfile(real) and any(
        _path_under_prefix(real, os.path.join(own, d)) for d in ('hooks', 'scripts'))


def _checkout_git_dirs(path: str) -> list[str]:
    """The git dir and, last, the common dir of the checkout `path` (or its nearest existing parent)
    lies in, by one git query; [] outside a checkout."""
    probe = path
    while not os.path.isdir(probe):
        probe = os.path.dirname(probe)
    return _git_query(['rev-parse', '--path-format=absolute', '--git-dir', '--git-common-dir'],
                      probe).splitlines()


class _GitConfigPaths:
    """The protected git paths of some checkouts, resolved once: the config and config.worktree of
    each git dir and common dir, and each common dir's keystone hook dir (`hold` compares a realpath
    with them)."""

    def __init__(self, checkouts):
        self.files: set[str] = set()
        self.hook_dirs: set[str] = set()
        for dirs in checkouts:
            for d in dirs:
                self.files.update(os.path.join(os.path.realpath(d), leaf) for leaf in GIT_DIR_CONFIG_FILES)
            if dirs:
                self.hook_dirs.add(os.path.realpath(os.path.join(os.path.realpath(dirs[-1]), _KEYSTONE_HOOKS_LEAF)))

    def hold(self, real: str) -> bool:
        return real in self.files or any(real == d or real.startswith(d.rstrip('/') + os.sep) for d in self.hook_dirs)


def _bash_git_config_paths(main_root: str, worktree_path: str, cwd: str) -> _GitConfigPaths:
    """The protected git paths for one Bash command's write targets: those of the session's main
    root, its worktree and the command's cwd, one git query per distinct root. Never one per target:
    a query per operand (about 3 ms) takes a command padded with thousands of operands past the rule's
    budget, and an overrun drops both this refusal and the bwrap rewrite."""
    roots = dict.fromkeys(os.path.realpath(r) for r in (main_root, worktree_path, cwd) if r)
    return _GitConfigPaths(_checkout_git_dirs(r) for r in roots)


def _targets_git_config(file_path: str, paths: _GitConfigPaths | None = None) -> bool:
    """file_path is the config or config.worktree of the git dir or common dir of the checkout it
    lies in, or the keystone hook dir of that common dir or a file in it, which the bwrap rebind
    keeps Bash off; an Edit runs outside bwrap. Read for a Write or Edit target (its checkout
    queried) and for each write target of an actor's Bash command (against `paths`,
    _bash_git_config_paths resolved once for the command)."""
    real = os.path.realpath(os.path.abspath(file_path))
    parts = real.lower().split(os.sep)
    # whatever the git dir is (also one that does not exist yet), a file of this name inside a
    # `.git` directory or a `worktrees/<name>` one is a per-worktree git config
    if parts[-1] == _WORKTREE_CONFIG_LEAF and ('.git' in parts[:-1] or 'worktrees' in parts[:-2]):
        return True
    if paths is None:
        paths = _GitConfigPaths([_checkout_git_dirs(os.path.dirname(real))])
    return paths.hold(real)


def _block_git_config(tool_name: str, target: str) -> None:
    _block('\nOVERNIGHT GIT CONFIG PROTECTION: the repository\'s git config holds the keystone '
           '(core.hooksPath) and its keystone hook dir holds the keystone hook; an overnight actor '
           f'leaves both as they are.\nBlocked: {tool_name} to {target}\n')


def _emit_command_rewrite(new_command: str) -> None:
    """Emit the Claude Code PreToolUse command-rewrite and exit 0. The runtime
    replaces tool_input.command with `new_command` (the bwrap re-exec)."""
    out = {
        'hookSpecificOutput': {
            'hookEventName': 'PreToolUse',
            'updatedInput': {'command': new_command},
        }
    }
    sys.stdout.write(json.dumps(out))
    sys.exit(0)


_GIT_META_LEAF_RE = re.compile(
    r'/\.git(?:/|$)|/refs/|/packed-refs|/logs/|/objects/|/HEAD$|/packed-refs$')
_OPEN_FOR_WRITE_RE = re.compile(r"open\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"][wa]")


def _raw_git_metadata_write_into_main(command: str, main_root: str,
                                      worktree_path: str, main_git_dir: str) -> bool:
    """True iff `command` writes, outside git (a redirect, tee, cp, mv ..., or an interpreter's
    open(..., 'w')), a `.git` ref/object/log/packed-refs/HEAD path under main that is not inside
    the isolated worktree. Such a write corrupts the main working-tree view through the RW-exposed
    .git binds, past both the keystone and the RO-bind, so it is refused before the bwrap rewrite."""
    main_real = os.path.realpath(main_root) if main_root else ''
    if not main_real:
        return False
    wt_real = os.path.realpath(worktree_path) if worktree_path else ''
    gitdir_real = os.path.realpath(main_git_dir) if main_git_dir else os.path.realpath(
        os.path.join(main_real, '.git'))
    targets = _bash_write_paths(command)
    for site, res in _read(command).resolved:
        if _interpreter(res.name):
            targets += _OPEN_FOR_WRITE_RE.findall(_code_text(site, res))
    for t in targets:
        rp = os.path.realpath(t)
        under_main = _path_under_prefix(rp, main_real) or _path_under_prefix(rp, gitdir_real)
        in_worktree = wt_real and _path_under_prefix(rp, wt_real)
        if under_main and not in_worktree and _GIT_META_LEAF_RE.search(rp):
            return True
    return False



def _apply_write_boundary(command: str, gov_state: dict, main_git_dir: str,
                          journal: tuple = ()) -> None:
    """For the overnight actor's Bash command: re-exec it inside the bwrap RO-bind
    boundary (emit updatedInput.command) when the boundary is available; FAIL-CLOSED
    (deny non-worktree-local commands) when bwrap is unavailable. No-op only for an
    empty command. Runs AFTER the security checks in main()."""
    if not command:
        return
    main_root = gov_state.get('main_root', '') or ''
    worktree_path = gov_state.get('worktree_path', '') or ''
    isolation_kind = gov_state.get('isolation_kind', '') or ''
    if not main_root or not worktree_path:
        return  # cannot scope a boundary without both roots; the checks already ran
    # A RAW .git-metadata write into main (outside the worktree) is
    # denied FIRST — before any bwrap rewrite — because the RW-exposed .git binds
    # cannot distinguish a git-mediated write from a raw corrupting write.
    if _raw_git_metadata_write_into_main(command, main_root, worktree_path, main_git_dir):
        _block(
            '\nOVERNIGHT RAW .git-METADATA WRITE BLOCK: a raw (non-git) write to '
            'a main-repo .git ref/object/log/packed-refs/HEAD path outside the '
            'isolated worktree is forbidden for overnight actors — it would '
            'corrupt the main working-tree view out-of-band (bypassing the '
            'keystone and the RO-bind). Use git inside the worktree instead.\n'
        )
    if _bwrap_boundary_available():
        argv = _build_bwrap_argv(command, main_root, worktree_path, isolation_kind, journal)
        if argv:
            # shlex-quote the argv into a single re-exec command string.
            import shlex
            _emit_command_rewrite(' '.join(shlex.quote(a) for a in argv))
        # boundary requested but argv could not be built -> fall through to the
        # fail-closed deny below (do not silently allow).
    # FAIL-CLOSED: bwrap unavailable OR argv unbuildable. The write guarantee
    # cannot be honored by the kernel, so an actor's command that is not
    # provably worktree-local is DENIED. Worktree-local commands are allowed
    # (no over-block; isolation is never gated on bwrap).
    if not _command_is_worktree_local(command, main_root, worktree_path, main_git_dir):
        _block(
            '\nOVERNIGHT WRITE-BOUNDARY FAIL-CLOSED: the per-command bwrap '
            'RO-bind boundary that guarantees the main working tree is never '
            'written in place is UNAVAILABLE (bubblewrap / user namespace '
            'missing), and this command cannot be proven to write only inside '
            'the isolated worktree. Refusing it — the write guarantee fails '
            'closed (write_boundary_active=false). Run a command that writes '
            'only inside the worktree, or restore bubblewrap.\n'
        )


def _restart_journal(payload: dict) -> tuple:
    """The dirs /restart's exact helper invocation writes (its state and grant dirs), () otherwise."""
    if 'restart-subagents.py' not in str(payload.get('tool_input')):
        return ()
    from lib import subagent_restart as restart
    if not restart.is_helper_invocation(payload):
        return ()
    return tuple(os.path.realpath(d) for d in (restart.state_dir(), restart.grant_dir()))


_UNATTENDED_DENY = {  # nobody answers a question asked inside /dev-overnight
    False: "Overnight is unattended; nobody answers. Decide (experiment, else the question's default), record the "
           "decision in the cycle log and in the summary's 'Decisions made without the owner', and continue.",
    True: "Nobody answers overnight. Decide by experiment if one can be run, else take the question's default; "
          "record the decision, its options, the evidence or experiment and the chosen option in your report, "
          "and write your report.",
}


def _unattended(payload: dict) -> bool:
    """True while the caller's session is unattended: the latest human-typed
    prompt of its main transcript is /dev-overnight. A subagent's payload
    carries its session's transcript_path (or its own, <sid>/subagents/
    agent-<id>.jsonl, read as <sid>.jsonl), so it needs no registration; no
    state file decides, and another session's transcript has no such prompt."""
    path = Path(str(payload.get('transcript_path') or ''))
    if path.parent.name == 'subagents':
        path = path.parent.parent.parent / f'{path.parent.parent.name}.jsonl'
    latest = None
    try:
        for _number, record in command_span._records(path):
            if stop_contract.is_human_prompt(record):
                latest = record
    except (OSError, ValueError):
        return False
    return stop_contract.span_opener(latest, frozenset({'dev-overnight'})) is not None


def _classify_request() -> tuple[str, dict, dict, list[str], str, dict | None]:
    """main()'s part before it knows the caller is an overnight actor: the AskUserQuestion deny, the
    checks every session gets while an overnight session is live, and the caller's classification.
    A `normal` caller (a concurrent user session on main, never false-blocked) ends here."""
    tool_name, tool_input, session_id, payload = _parse_hook_input()
    if tool_name == 'AskUserQuestion':  # the deny is this hook's only rule for it
        if _unattended(payload):
            _block(_UNATTENDED_DENY[bool(payload.get('agent_id'))] + '\n')
        sys.exit(0)
    state = _load_session_state(session_id)
    _set_request_ctx(state, payload)  # enables the self_repair grant lookup
    if is_overnight_active():
        apply_global_security_checks(tool_name, tool_input)
    cwd = _payload_cwd(payload)
    wt_paths = _get_active_worktree_paths()
    classification, gov_state = _classify_actor(payload, state, wt_paths, cwd)
    if classification == 'normal':
        sys.exit(0)
    return tool_name, tool_input, payload, wt_paths, classification, gov_state


def main():
    """Entry point: apply global + actor-scoped overnight enforcement."""
    # The write gate fails this rule closed (lib/write_gate): an error past the rule's own handlers, or
    # an overrun, refuses the call. That is for the overnight actors classified below; an error before
    # the caller is classified stays a non-blocking error (exit 1), so a malformed state file of the
    # project (a non-string worktree_path raises in is_overnight_active) does not refuse every call of
    # every other session.
    try:
        tool_name, tool_input, payload, wt_paths, classification, gov_state = _classify_request()
    except Exception as exc:
        sys.stderr.write(f'overnight-boundary: {type(exc).__name__}: {exc}; the caller was not yet '
                         'classified, so this rule did not decide this call.\n')
        sys.exit(1)
    # Scope the governing record's own working root to THIS request before any main-targeting
    # predicate runs. in_place only; isolated records leave the main root fully guarded.
    _set_governing_own_root(gov_state, payload)

    # owner/child with a null/missing worktree = invalid isolation = BLOCK.
    if classification in ('overnight_owner', 'overnight_child'):
        wt = (gov_state or {}).get('worktree_path') if gov_state else None
        if not wt:
            _block_invalid_isolation(classification)

    # For overnight actors (also an in-worktree actor whose owner/child resolution
    # failed): the git and write checks first, then the bwrap rewrite.
    if classification in ('overnight_owner', 'overnight_child', 'worktree_context') \
            and tool_name == 'Bash':
        command = tool_input.get('command', '')
        if gov_state is not None:
            main_git_dir = gov_state.get('main_git_dir', '')
            _enforce_overnight_git_command(command, gov_state.get('main_root', ''),
                                           gov_state.get('worktree_path', ''), main_git_dir)
            # /restart's helper (the overnight wake runs it) runs inside the boundary too, with only
            # its journal bound writable: a check of the helper against its blobs at the harness's
            # HEAD cannot see what it runs (its hooks/lib modules load from untracked __pycache__
            # bytecode, and the untracked venv runs any .pth in it).
            _apply_write_boundary(command, gov_state, main_git_dir, _restart_journal(payload))
        elif classification == 'worktree_context':
            # No governing state: the main_root cannot be derived to scope a targeted
            # block, so any git / interpreter command is refused; any other command is
            # left to the worktree-boundary enforcement below.
            _fail_closed_worktree_context(command)
    target = _edit_target(tool_name, tool_input)
    if classification in ('overnight_owner', 'overnight_child', 'worktree_context') and gov_state is not None \
            and target and _targets_git_config(target):
        _block_git_config(tool_name, target)

    if wt_paths:
        apply_global_worktree_enforcement(tool_name, tool_input, wt_paths)
    if classification in ('overnight_owner', 'overnight_child') and gov_state is not None:
        _apply_session_enforcement(gov_state, tool_name, tool_input)
    sys.exit(0)


def _self_test() -> int:
    """Simulated overnight + self_repair-enabled contract grant test."""
    sr = {'enabled': True, 'reason': 'ac8', 'allowed_roles': ['dev'],
          'allowed_path_prefixes': ['/tmp/t24-ac8/'],
          'expires_at': '2099-01-01T00:00:00Z', 'audit_required': False}
    assert _self_repair_block({'self_repair': sr}) is sr, 'enabled grant returns dict'
    assert _self_repair_block({'self_repair': dict(sr, enabled=False)}) is None, 'disabled = None'
    assert _expires_passed('2020-01-01T00:00:00Z') and not _expires_passed('2099-01-01T00:00:00Z')
    assert _path_under_prefix('/tmp/t24-ac8/x', '/tmp/t24-ac8/')
    assert not _path_under_prefix('/etc/passwd', '/tmp/t24-ac8/')
    g, _ = _grant_decision_for('/tmp/t24-ac8/x.py', 'dev', '', sr); assert g, 'dev grant ok'
    g, _ = _grant_decision_for('/tmp/t24-ac8/x.py', 'qa', '', sr); assert not g, 'qa role denied'
    g, _ = _grant_decision_for('/etc/passwd', 'dev', '', sr); assert not g, 'outside-prefix denied'
    g, _ = _grant_decision_for('/tmp/t24-ac8/x.py', 'dev', '',
                               dict(sr, expires_at='2020-01-01T00:00:00Z')); assert not g, 'expired denied'
    print('self-repair grant self-test: PASS (8 grant-logic assertions)'); return 0


if __name__ == '__main__':
    if '--self-test' in sys.argv:
        sys.exit(_self_test())
    main()
