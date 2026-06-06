#!/usr/bin/env python3
"""
PreToolUse Hook: Agent git-privilege guard.

Scope: Runs on EVERY Bash tool call in agent (subagent + main-agent
orchestrator) contexts, regardless of whether the session is overnight
or interactive. The b5d447e regression (2026-04-21 17:45 UTC) which
this guard exists to prevent - a 93-file `git commit` + `git push`
sweep authored by the orchestrator with no human signoff - happened in
an INTERACTIVE session (JSONL message 293 of session
962de59f-fe0b-416e-b88b-7345fdf569e2, prompt `全部commit push`,
no overnight-state-*.json present). Gating this hook on overnight-
context only would let that exact regression class pass through; the
guard must be always-on per spec 5.2.4 line 240-241.

The whitelists below preserve the legitimate paths:
  - `^auto-bulk: end-of-cycle commit for ` blessed bridge from /merge
  - CLAUDE_MERGE_COMMAND_ACTIVE=1 env exemption for git merge
  - reset to HEAD (non-destructive)
  - human-driven commits: the human exits the agent context and runs
    git commit at their own shell; this hook does not see those calls.

Forbidden agent operations:
  - git commit -m '<msg>' whose message does NOT match
    `^auto-bulk: end-of-cycle commit for ` (the blessed bridge from
    /merge per spec section 5.2.1.2 R2). Stderr literal:
    `BLOCKED: agent git commit`.
  - git merge unless the env var `CLAUDE_MERGE_COMMAND_ACTIVE=1` is
    set by /merge at start. Stderr literal: `BLOCKED: agent git merge`.
  - git push (any form). Stderr literal:
    `BLOCKED: agent git push`.
  - every hard reset form. Stderr literal:
    `BLOCKED: agent git reset --hard`.
  - direct ref mutation (`git update-ref`, branch force/delete/rename,
    or writable HEAD symbolic-ref changes).

Allowed: git add, git status, git log, git diff, git show, git blame,
git ls-files, git ls-tree, git restore (working-tree only), git branch
(list), git rev-list, git rev-parse, git symbolic-ref, git for-each-ref,
and git stash list/show/pop (non-destructive forms). Hard reset and direct
ref mutation are not agent-accessible.

Spec: spec-20260424-233926 section 5.2.4 (R4.3) line 233-249.

Revision history:
  2026-04-25 (Scheme 6 manifest-validation): added two narrow
  authorized-exemption paths for `git push` and `git commit` driven by
  the new `/push` and `/commit` slash-command wrappers. Each path
  requires BOTH:
    1. an OS-level env var (`CLAUDE_PUSH_COMMAND_ACTIVE=1` for push,
       `CLAUDE_COMMIT_COMMAND_ACTIVE=1` for commit) set by the wrapper
       in the child's environment (NOT inline-prepended on the agent
       command line), AND
    2. a single-use grant manifest at
       `/tmp/claude-{push|commit}-grant-<sid>.json` whose contents
       bind the operation to a specific branch + expected_head + remote
       (push) or task_id + allowed_files + expected_message_sha256
       (commit).
  Inline-env injection (e.g. `CLAUDE_PUSH_COMMAND_ACTIVE=1 git push ...`
  on a single Bash call) is rejected by literal-substring scan of the
  raw command text BEFORE the env-var check, defeating the b5d447e
  attack class even if the agent learns the env name. The grant file
  is unlinked on first valid consumption (single-use); validation
  failures DO NOT consume the grant (forensics + brute-force resistance).
  Cross-bypass is blocked: the push env name does NOT bypass commit,
  and vice versa.  Authority: spec ba-spec-20260425-redev2.md §4.1
  (AC-A1..AC-A17), close-report-20260425-push-commit-debate.md
  (Scheme 6 verdict CLOSE: YES).
  2026-04-25 (Option alpha): made always-on. Removed the overnight-
  context gate after confirming b5d447e occurred in an interactive
  session - the gate would have let the regression through. The
  `_is_overnight_active()` helper is retained as dead code for
  reference but is no longer consulted by main().
  2026-04-25 (earlier): replaced the dead-code `CLAUDE_OVERNIGHT_ACTIVE`
  env-var path with the canonical state-file probe.

Exit codes:
  0: Allow tool use
  2: Block tool use
"""

import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.allowlist import read_grant_for_git_command, match_sentinel_grant_for_bash_command  # noqa: E402


BLESSED_BRIDGE_RE = re.compile(r'auto-bulk:\s*end-of-cycle commit for\b')

GIT_GLOBAL_OPTION_RE = (
    r'(?:\s+(?:-[Cc]\s+\S+|-[Cc]\S+|'
    r'--(?:git-dir|work-tree|namespace|exec-path|super-prefix|config-env)'
    r'(?:=\S+|\s+\S+)|'
    r'--(?:bare|no-pager|paginate|no-replace-objects|literal-pathspecs|'
    r'glob-pathspecs|noglob-pathspecs|icase-pathspecs|no-optional-locks)|'
    r'-[pP]))*'
)
GIT_COMMAND_RE = r'(?:^|[\s;&|()`])git' + GIT_GLOBAL_OPTION_RE + r'\s+'


def _block(message):
    sys.stderr.write(message)
    sys.exit(2)


# ---------------------------------------------------------------------------
# Scheme 6 manifest-validation helpers (added 2026-04-25)
# ---------------------------------------------------------------------------

def _get_session_id(data):
    """Extract session_id from the parsed PreToolUse stdin payload.

    Returns empty string when missing.  Used to compute the per-session
    grant-file path /tmp/claude-{kind}-grant-<sid>.json.
    """
    try:
        sid = data.get('session_id', '') or ''
        return str(sid)
    except Exception:
        return ''


def _has_do_consent(data: dict) -> bool:
    """Return True if main agent has /do consent for this turn."""
    if data.get('agent_id'):  # subagents cannot use /do
        return False
    sid = _get_session_id(data)
    if not sid:
        return False
    try:
        flag = Path(f'/tmp/claude-orchestrator-consent-{sid}.flag')
        return flag.exists() and flag.read_text().strip() == 'true'
    except Exception:
        return False


def _check_git_allowlist(command: str, data: dict) -> bool:
    """Check /allow grant for non-push git operations. Read-only.

    Main-agent only for LEGACY grants. Sentinel grants (task 20260524-133650):
    extend to subagents — mirrors M2 decision in pretool-bash-safety.sh:484.
    IS_SUBAGENT check preserved for legacy path only.
    """
    sid = _get_session_id(data)
    if not sid:
        return False
    # Sentinel grant check (task 20260524-133650): NOT gated by subagent firewall.
    # User-granted sentinels must be honored in subagent context per M2 (20260521-090200).
    task_id = os.environ.get('CLAUDE_TASK_ID') or sid
    if match_sentinel_grant_for_bash_command(task_id, command) is not None:
        return True
    # Legacy grant check: subagent firewall preserved (original behavior).
    if data.get('agent_id'):
        return False
    return read_grant_for_git_command(command, sid)


def _inline_env_present(command, var_name):
    """True iff the raw command string contains literal `<var_name>=`.

    This is the literal-substring defense against the inline-env
    injection attack (e.g. `CLAUDE_PUSH_COMMAND_ACTIVE=1 git push ...`
    on a single Bash call).  We deliberately use plain substring
    matching on the raw command text - not a regex, not a normalized
    form - so that any encoding of the literal `VAR=` token in the
    command is caught.
    """
    if not command or not var_name:
        return False
    needle = var_name + '='
    return needle in command


def _find_grant(kind, sid):
    """Return (resolved_path, grant_dict) or (None, None) on miss/invalid.

    Per close-report-20260425-push-commit-debate.md §1-2, wrappers write
    per-nonce filenames `/tmp/claude-{kind}-grant-<sid>-<nonce>.json` so
    that two concurrent wrapper invocations under the same SID cannot
    collide on a single shared file.  The guard discovers the grant by
    glob, sorts by mtime descending, and returns the most recent
    JSON-parseable candidate.  The caller is responsible for unlinking
    the resolved path (single-use) on validation success.
    """
    pattern = '/tmp/claude-%s-grant-%s-*.json' % (kind, sid)
    try:
        candidates = glob.glob(pattern)
    except Exception:
        return (None, None)
    try:
        candidates.sort(key=lambda p: os.stat(p).st_mtime, reverse=True)
    except Exception:
        # If stat() races a concurrent unlink, fall back to lexical order.
        candidates.sort(reverse=True)
    for path in candidates:
        grant = _load_grant(path)
        if grant is not None:
            return (path, grant)
    return (None, None)


def _load_grant(grant_path):
    """Read and JSON-parse a grant file.

    Returns the parsed dict on success, or None on missing / empty /
    malformed / unreadable.  Catches all exceptions and fails closed
    (caller treats None as "no valid grant -> block").
    """
    try:
        with open(grant_path, 'r') as fp:
            text = fp.read()
        if not text.strip():
            return None
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            return None
        return parsed
    except Exception:
        return None


def _find_grant_any(kind):
    """Fallback grant search ignoring SID.

    Used when the subagent's session_id (from PreToolUse payload) differs
    from the orchestrator's CLAUDE_SESSION_ID used when writing the grant.
    Searches all grants of the given kind, returns the most recent valid one.
    """
    pattern = '/tmp/claude-%s-grant-*-*.json' % kind
    try:
        candidates = glob.glob(pattern)
    except Exception:
        return (None, None)
    try:
        candidates.sort(key=lambda p: os.stat(p).st_mtime, reverse=True)
    except Exception:
        candidates.sort(reverse=True)
    for path in candidates:
        grant = _load_grant(path)
        if grant is not None:
            return (path, grant)
    return (None, None)


def _unlink_grant(grant_path):
    """Remove the grant file, swallowing all errors.

    Single-use grant unlink: called ONLY on successful validation paths,
    NEVER on validation-failure paths (so failure does not consume the
    grant - this preserves forensic visibility and resists brute-force
    confirm/deny probing).
    """
    try:
        os.unlink(grant_path)
    except Exception:
        pass


# Pointer-file path template for deferred commit-grant consumption (Fix B).
# PreToolUse locks the grant (rename → .lck) and writes this pointer so
# PostToolUse can locate it for finalization.
_COMMIT_GRANT_ACTIVE_TEMPLATE = '/tmp/claude-commit-grant-active-{sid}.json'


def _lock_grant_for_posttool(grant_path, effective_sid):
    """Lock a commit grant for deferred PostToolUse consumption (Fix B).

    Renames grant_path → grant_path + ".lck" to atomically remove it from
    _find_grant / _find_grant_any searches (prevents double-use), then writes
    a pointer at _COMMIT_GRANT_ACTIVE_TEMPLATE so posttool-allowlist-consume.py
    can finalize:
      - exit 0  → unlink the .lck file (consumed)
      - non-zero → rename .lck back to original (grant preserved for retry)

    Falls back to immediate _unlink_grant if the rename fails (e.g., cross-
    device move or permission error) so the guard stays fail-closed.
    """
    locked_path = grant_path + '.lck'
    try:
        os.rename(grant_path, locked_path)
    except OSError:
        _unlink_grant(grant_path)
        return
    pointer_key = effective_sid or 'any'
    pointer_path = _COMMIT_GRANT_ACTIVE_TEMPLATE.format(sid=pointer_key)
    try:
        with open(pointer_path, 'w') as fp:
            json.dump({'locked_path': locked_path, 'original_path': grant_path}, fp)
    except OSError:
        pass


def _git_output(args):
    """Run `git <args...>` and return stripped stdout, or '' on any error.

    Used to read the current branch / HEAD / staged-set inside the
    guard.  Always runs in the agent's CWD (no `-C` override) so that
    the resolved values match what the agent's `git push|commit` call
    would see.
    """
    try:
        result = subprocess.run(
            ['git'] + list(args),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return ''
        return (result.stdout or '').strip()
    except Exception:
        return ''


def _extract_push_remote(command):
    """Best-effort extraction of the explicit remote argument from a
    `git push` invocation.  Returns the first positional token after
    `push` that is not a flag (does not start with `-`), or '' when
    not found (typical for plain `git push` with upstream tracking).
    """
    m = re.search(GIT_COMMAND_RE + r'push\b(.*)', command)
    if not m:
        return ''
    tail = m.group(1)
    # Stop at shell separators so trailing pipelines do not pollute.
    tail = re.split(r'[;&|`]', tail, maxsplit=1)[0]
    for tok in tail.strip().split():
        if tok.startswith('-'):
            continue
        return tok
    return ''


def _looks_like_git_commit(command):
    return bool(re.search(GIT_COMMAND_RE + r'commit\b', command))


def _looks_like_git_merge(command):
    return bool(re.search(GIT_COMMAND_RE + r'merge(?!-base|tool)\b', command))


def _looks_like_git_push(command):
    return bool(re.search(GIT_COMMAND_RE + r'push\b', command))


def _looks_like_git_reset_hard(command):
    return bool(re.search(
        GIT_COMMAND_RE + r"reset\s+(?:[^;|&]*\s+)?--hard\b",
        command,
    ))


def _looks_like_git_direct_ref_mutation(command):
    if re.search(GIT_COMMAND_RE + r'update-ref\b', command):
        return True
    if re.search(GIT_COMMAND_RE + r'symbolic-ref\s+(?:-m\s+\S+\s+)*HEAD\s+refs/', command):
        return True
    return bool(re.search(
        GIT_COMMAND_RE + r'branch\s+(?:-[fDdMm]+\b|--delete\b|--force\b|--move\b)',
        command,
    ))


def _push_has_forbidden_ref_mutation(command):
    m = re.search(GIT_COMMAND_RE + r'push\b(.*)', command)
    if not m:
        return False
    tail = re.split(r'[;&|`]', m.group(1), maxsplit=1)[0]
    tokens = tail.strip().split()
    for tok in tokens:
        if tok in ('--force', '-f', '--force-with-lease', '--delete', '-d', '--mirror'):
            return True
        if tok.startswith('--force-with-lease='):
            return True
        if tok.startswith('+') or tok.startswith(':'):
            return True
    return False


def _extract_commit_message(command):
    patterns = [
        r"-m\s*=?\s*'([^']*)'",
        r'-m\s*=?\s*"([^"]*)"',
        r'--message\s*=?\s*"([^"]*)"',
        r"--message\s*=?\s*'([^']*)'",
    ]
    for p in patterns:
        m = re.search(p, command)
        if m:
            return m.group(1)
    m = re.search(r'-m\s+(\S+)', command)
    if m:
        return m.group(1)
    # -F / --file: changelog-analyst always uses git commit -F <tmpfile>.
    # Read the subject line from the file so BLESSED_BRIDGE_RE can match.
    for p in [r'(?:^|\s)-F\s+(\S+)', r'--file[= ](\S+)']:
        m = re.search(p, command)
        if m:
            try:
                with open(m.group(1)) as fh:
                    return fh.readline().strip()
            except OSError:
                pass
    return ''


def _extract_reset_target(command):
    m = re.search(
        GIT_COMMAND_RE + r"reset\s+(?:[^;|&]*?\s+)?--hard\s+([^\s;|&]+)",
        command,
    )
    return m.group(1) if m else ''


def _is_head_ref(ref):
    if not ref:
        return True
    return ref == 'HEAD'


def _end_time_passed(end_str):
    try:
        end = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
    except (ValueError, TypeError, AttributeError):
        return True
    if end.tzinfo is None:
        return datetime.now() > end
    return datetime.now(timezone.utc) > end


def _state_file_is_live(sf):
    try:
        if sf.stat().st_size == 0:
            return False
        state = json.loads(sf.read_text())
    except (OSError, ValueError):
        return False
    if state.get('current_phase', '') in ('complete', 'completed'):
        return False
    if _end_time_passed(state.get('end_time', '')):
        return False
    return True


def _is_overnight_active():
    """True iff a live overnight-state-*.json exists in <project>/.claude/."""
    try:
        project_dir = Path(os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd())
        state_files = list((project_dir / '.claude').glob('overnight-state-*.json'))
        return any(_state_file_is_live(sf) for sf in state_files)
    except Exception:
        return False


def _block_default_deny_commit(msg):
    """AC-A13: default-deny block when commit env is unset."""
    _block(
        '\nBLOCKED: agent git commit - only the blessed /merge '
        'auto-bulk bridge or the /commit wrapper may commit from an '
        'agent context.\n'
        'Commit message excerpt: %r\n' % msg[:200]
        + 'Allowed pattern: ^auto-bulk: end-of-cycle commit for <branch>\n'
        'For closed dev tasks, use /commit <task-id>.\n'
        'For human-driven commits, exit the agent context and run '
        'git commit directly.\n'
        'Main agent may bypass with /allow <pattern> before the git commit command.\n'
        'Spec: spec-20260424-233926 section 5.2.4 (R4.3); '
        'ba-spec-20260425-redev2.md AC-A13.\n'
    )


def _has_bulk_commit_sentinel(data):
    """Return True if a valid non-expired bulk-commit sentinel exists.

    Written by /commit --bulk (scripts/write-bulk-commit-sentinel.py) before
    dispatching changelog-analyst. Multi-use: NOT consumed on validation so
    that multiple auto-bulk commits in a single session all succeed.
    Expires 30 minutes after creation (SENTINEL_TTL_MINUTES in the writer).

    SID fallback rationale (mirrors _find_grant_any for regular commits):
    changelog-analyst subagents carry a different session_id than the
    orchestrator that wrote the sentinel. The SID-specific glob is tried
    first (fast path); the global glob is the fallback so subagents can
    always find the sentinel written by the user's orchestrator session.
    Acceptable because: (a) sentinels require user-invoked /commit --bulk
    to be created at all; (b) 30-min TTL bounds exposure; (c) kind=
    'bulk-commit' check prevents other JSON files in /tmp from matching.
    """
    sid = _get_session_id(data)
    patterns = []
    if sid:
        patterns.append('/tmp/claude-bulk-commit-sentinel-%s-*.json' % sid)
    # Global fallback — see docstring above for rationale.
    patterns.append('/tmp/claude-bulk-commit-sentinel-*-*.json')
    seen = set()
    for pattern in patterns:
        try:
            candidates = glob.glob(pattern)
        except Exception:
            continue
        try:
            candidates.sort(key=lambda p: os.stat(p).st_mtime, reverse=True)
        except Exception:
            candidates.sort(reverse=True)
        for path in candidates:
            if path in seen:
                continue
            seen.add(path)
            sentinel = _load_grant(path)
            if sentinel is None:
                continue
            if sentinel.get('kind') != 'bulk-commit':
                continue
            if sentinel.get('origin') != 'userpromptsubmit-hook':
                continue
            if not _end_time_passed(sentinel.get('expires_at', '')):
                return True
    return False


def _has_active_commit_grant():
    """Return True if any single-use commit grant is pending or in-flight (Fix E).

    Used to defer auto-bulk commits while a concurrent /commit cycle is active.
    Checks .json (written, not yet locked) and .lck (locked by PreToolUse;
    git commit subprocess is running) grant files.
    """
    for pattern in ('/tmp/claude-commit-grant-*.json',
                    '/tmp/claude-commit-grant-*.lck'):
        try:
            for path in glob.glob(pattern):
                grant = _load_grant(path)
                if grant is not None and not _end_time_passed(
                        grant.get('expires_at', '')):
                    return True
        except Exception:
            pass
    return False


def _evaluate_commit(command, data):
    msg = _extract_commit_message(command)
    if msg and BLESSED_BRIDGE_RE.search(msg):
        # Require a valid bulk-commit sentinel (written by /commit --bulk).
        # Without it, any agent that knows the prefix could bypass the guard.
        if _has_bulk_commit_sentinel(data):
            # Fix E: defer auto-bulk if a single-use /commit grant is active.
            # A concurrent /commit cycle is in progress; let it finish first.
            if _has_active_commit_grant():
                _block(
                    '\nDEFERRED: auto-bulk commit skipped — an active single-use '
                    'commit grant exists (/tmp/claude-commit-grant-*.json or *.lck).\n'
                    'A /commit cycle is in progress; auto-bulk will retry on the '
                    'next scheduled cycle.\n'
                )
            return
        _block(
            '\nBLOCKED: auto-bulk commit requires a bulk-commit sentinel.\n'
            'The `auto-bulk:` prefix is only authorized when changelog-analyst '
            'is dispatched by the user via /commit --bulk, which writes '
            '/tmp/claude-bulk-commit-sentinel-<sid>-<nonce>.json (30 min TTL).\n'
            'To run bulk commits: invoke /commit --bulk from your Claude session.\n'
        )
    if _check_git_allowlist(command, data):
        return
    # Grant-file mechanism: SID-specific search first, then any-SID fallback.
    # Fallback handles subagent SID propagation gaps where changelog-analyst's
    # session_id (PreToolUse payload) differs from orchestrator's CLAUDE_SESSION_ID.
    sid = _get_session_id(data)
    if sid:
        grant_path, grant = _find_grant('commit', sid)
        if grant is not None:
            if not _end_time_passed(grant.get('expires_at', '')):
                _lock_grant_for_posttool(grant_path, sid)
                return
    # Fallback: any valid unexpired commit grant (written by /commit close-gate).
    grant_path, grant = _find_grant_any('commit')
    if grant is not None:
        if not _end_time_passed(grant.get('expires_at', '')):
            effective_sid = grant.get('sid') or sid or 'any'
            _lock_grant_for_posttool(grant_path, effective_sid)
            return
    # AC-A13: default-deny all other agent git commit calls.
    _block_default_deny_commit(msg)


def _evaluate_merge(command, data):
    if os.environ.get('CLAUDE_MERGE_COMMAND_ACTIVE') == '1':
        return
    if _check_git_allowlist(command, data):
        return
    _block(
        '\nBLOCKED: agent git merge - only the /merge slash command '
        'may run git merge from an overnight context.\n'
        'Command excerpt: %s\n' % command[:200]
        + 'To bypass: set env var CLAUDE_MERGE_COMMAND_ACTIVE=1.\n'
        'Spec: spec-20260424-233926 section 5.2.4 (R4.3).\n'
    )


def _block_inline_env_push(command):
    """AC-A1: literal-substring inline-env injection block for push."""
    _block(
        '\nBLOCKED: agent git push - inline-env injection blocked.\n'
        'Detected literal substring `CLAUDE_PUSH_COMMAND_ACTIVE=` in '
        'the raw command text; agents are not permitted to set this '
        'env var inline.  Only the /push wrapper may set it via '
        'subprocess + os.environ.\n'
        'Command excerpt: %s\n' % command[:200]
        + 'Spec: ba-spec-20260425-redev2.md AC-A1.\n'
    )


def _block_default_deny_push(command):
    """AC-A5: default-deny block when push env is unset."""
    _block(
        '\nBLOCKED: agent git push - agents are not authorized to push '
        'to remote from an agent context.\n'
        'Command excerpt: %s\n' % command[:200]
        + 'For automated push, use the /push slash command (which sets '
        'CLAUDE_PUSH_COMMAND_ACTIVE=1 and writes a single-use grant).\n'
        'For human-driven push, exit the agent context and run '
        'git push directly.\n'
        'Spec: spec-20260424-233926 section 5.2.4 (R4.3); '
        'ba-spec-20260425-redev2.md AC-A5.\n'
    )


def _validate_push_grant_branch(grant):
    """AC-A7: grant.branch must match current branch."""
    grant_branch = grant.get('branch') or ''
    current_branch = _git_output(['branch', '--show-current'])
    if not grant_branch or grant_branch != current_branch:
        _block(
            '\nBLOCKED: agent git push - branch mismatch.\n'
            'Grant branch  : %r\n' % grant_branch
            + 'Current branch: %r\n' % current_branch
            + 'Spec: ba-spec-20260425-redev2.md AC-A7.\n'
        )


def _validate_push_grant_head(grant):
    """AC-A6: grant.expected_head must match current HEAD sha."""
    grant_head = grant.get('expected_head') or ''
    current_head = _git_output(['rev-parse', 'HEAD'])
    if not grant_head or grant_head != current_head:
        _block(
            '\nBLOCKED: agent git push - expected_head mismatch.\n'
            'Grant expected_head: %r\n' % grant_head
            + 'Current HEAD       : %r\n' % current_head
            + 'Spec: ba-spec-20260425-redev2.md AC-A6.\n'
        )


def _validate_push_grant_remote(grant, command):
    """AC-A6 (remote binding): explicit cmd remote must match grant.remote."""
    grant_remote = grant.get('remote') or ''
    cmd_remote = _extract_push_remote(command)
    if cmd_remote and grant_remote and cmd_remote != grant_remote:
        _block(
            '\nBLOCKED: agent git push - remote mismatch.\n'
            'Grant remote  : %r\n' % grant_remote
            + 'Command remote: %r\n' % cmd_remote
            + 'Spec: ba-spec-20260425-redev2.md AC-A6.\n'
        )


def _block_missing_push_grant(sid):
    """AC-A4: env present but no on-disk grant for this SID."""
    pattern = '/tmp/claude-push-grant-%s-*.json' % sid
    _block(
        '\nBLOCKED: agent git push - CLAUDE_PUSH_COMMAND_ACTIVE=1 '
        'is set but no valid grant manifest matching %s.\n' % pattern
        + 'Single-use grants are unlinked on first valid consumption; '
        'a missing grant means it was already used or never written.\n'
        'Spec: ba-spec-20260425-redev2.md AC-A4; '
        'close-report-20260425-push-commit-debate.md §1-2.\n'
    )


def _evaluate_push(command, data):
    sid = _get_session_id(data)
    # AC-A1: literal-substring inline-env injection (precedes env check).
    if _inline_env_present(command, 'CLAUDE_PUSH_COMMAND_ACTIVE'):
        _block_inline_env_push(command)
    if _push_has_forbidden_ref_mutation(command):
        _block(
            '\nBLOCKED: agent git push - force/delete/ref-rewrite push is forbidden.\n'
            'Command excerpt: %s\n' % command[:200]
            + 'Safety policy allows normal /push branch publication only; '
            'automatic backup must use namespaced recovery refs.\n'
        )
    if _check_git_allowlist(command, data):
        return
    # AC-A5: default-deny when env unset.
    if os.environ.get('CLAUDE_PUSH_COMMAND_ACTIVE') != '1':
        _block_default_deny_push(command)
    # AC-A4: env present but no grant -> block.  Per close-report §1-2,
    # filename is `<sid>-<nonce>.json` (per-nonce); glob+match.
    grant_path, grant = _find_grant('push', sid)
    if grant is None:
        _block_missing_push_grant(sid)
    # AC-A7 + AC-A6: branch / head / remote binding.
    _validate_push_grant_branch(grant)
    _validate_push_grant_head(grant)
    _validate_push_grant_remote(grant, command)
    # All validations passed.  Consume grant (single-use), then allow.
    _unlink_grant(grant_path)


def _evaluate_reset_hard(command, data):
    if _check_git_allowlist(command, data):
        return
    target = _extract_reset_target(command)
    _block(
        '\nBLOCKED: agent git reset --hard - hard reset is forbidden '
        'from agent flow.\n'
        + 'Command excerpt: %s\n' % command[:200]
        + 'Target: %r\n' % target
        + 'Spec: 2026-05-09 commit/push loss-prevention policy.\n'
    )


def _evaluate_direct_ref_mutation(command, data):
    if _check_git_allowlist(command, data):
        return
    _block(
        '\nBLOCKED: agent direct git ref mutation - update-ref and '
        'branch force/delete/rename are forbidden.\n'
        'Command excerpt: %s\n' % command[:200]
        + 'Branch movement must go through expected-parent CAS wrappers.\n'
    )


def _looks_like_git_forbidden_plumbing(command):
    """R6: Ban agent direct invocation of git plumbing that creates commit objects.

    Defense-in-depth: most are already indirectly blocked (they call git commit
    or git update-ref internally). These explicit bans close the gap for R6.
    Uses GIT_COMMAND_RE anchor so string literals in python -c code are not matched.
    """
    forbidden_suffixes = [
        r'commit-tree\b',
        r'cherry-pick\b',
        r'rebase\b',
        r'pull\b',
        r'filter-branch\b',
        r'filter-repo\b',
        r'replace\s+(-e|--edit)\b',
        r'fast-import\b',
        r'revert\b',
        r'am\b',
    ]
    return any(re.search(GIT_COMMAND_RE + s, command) for s in forbidden_suffixes)


def _evaluate_forbidden_plumbing(command, data):
    if _check_git_allowlist(command, data):
        return
    _block(
        '\nBLOCKED: agent direct git plumbing is forbidden (R6).\n'
        'Command excerpt: %s\n' % command[:200]
        + 'Commit creation must go through the /commit slash command.\n'
    )


def _evaluate_command(command, data):
    # Fast path: if /allow grant matches for non-push commands, allow immediately.
    # Push is excluded: its allowlist check must come AFTER _push_has_forbidden_ref_mutation
    # (force-push must stay blocked even with a broad /allow grant).
    if not _looks_like_git_push(command) and _check_git_allowlist(command, data):
        return
    if _looks_like_git_forbidden_plumbing(command):
        _evaluate_forbidden_plumbing(command, data)
    if _looks_like_git_reset_hard(command):
        _evaluate_reset_hard(command, data)
    if _looks_like_git_direct_ref_mutation(command):
        _evaluate_direct_ref_mutation(command, data)
    if _looks_like_git_push(command):
        _evaluate_push(command, data)
    if _looks_like_git_merge(command):
        _evaluate_merge(command, data)
    if _looks_like_git_commit(command):
        _evaluate_commit(command, data)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    try:
        if data.get('tool_name', '') != 'Bash':
            sys.exit(0)
        # Always-on per spec 5.2.4 line 240-241; overnight gate removed
        # 2026-04-25 (Option alpha) after b5d447e proved interactive
        # sessions need this guard too.
        command = (data.get('tool_input', {}) or {}).get('command', '') or ''
        if not command:
            sys.exit(0)
        # /do bypass: main-agent-only; subagents never benefit from consent flag.
        if _has_do_consent(data):
            sys.exit(0)
        _evaluate_command(command, data)
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
    sys.exit(0)


if __name__ == '__main__':
    main()
