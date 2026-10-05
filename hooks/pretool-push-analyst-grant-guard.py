#!/usr/bin/env python3
"""
PreToolUse Hook: independent re-validation of the push-analyst Chain-B grant.

Scope: runs on every Bash tool call (matcher "Bash"). Chain-B's validation
(grant field checks, HEAD-drift check, single-use consumption, sentinel
write) today lives ENTIRELY inside two editable plain scripts --
scripts/execute-push.py and hooks/push.sh -- with zero independent hook-layer
cross-check, unlike every other git-privilege control in this harness, which
hooks/pretool-git-privilege-guard.py enforces as an always-on registered
hook that never trusts the invoked command alone.

Detection is by SCRIPT-BASENAME TOKEN (execute-push.py / push.sh), NOT by
scanning for a literal "git push" substring: empirically, neither sanctioned
invocation ("python3 .../execute-push.py ...", "bash .../push.sh ...")
contains a "git" token at the Bash-tool-call surface -- the real `git push`
only happens as a subprocess nested two levels inside ONE Bash tool call
(os.execv from execute-push.py into push.sh, which then forks `git push`),
which no PreToolUse hook observes as a separate event. See
docs/dev/ticket-20261001-161041-r17.md for the full evidence trail.

When a target invocation is detected, this hook independently re-derives
repo_hash/branch/session_id from live git state and the hook's own trusted
PreToolUse payload (never trusting the command's own --repo-hash/--branch
argument text for the LOOKUP/BINDING), then re-validates the push-analyst
grant at /tmp/agentic-commit/push-analyst/<repo_hash>/<session_id>/<request_id>.json
against the SAME binding fields scripts/execute-push.py checks: nonce,
branch, remote_name, session_id, verdict != "blocked", expires_at in the
future, and head_sha == current `git rev-parse HEAD` -- BEFORE allowing the
Bash tool call through.

Purely ADDITIVE: does not modify, and is not modified by, scripts/execute-push.py,
hooks/push.sh, or pretool-git-privilege-guard.py's existing _evaluate_push logic.
Never unlinks/consumes the grant file on any path (success or failure) --
scripts/execute-push.py remains the sole consumer, preserving its single-use/
retry semantics with no double-consumption race.

Mirrors hooks/pretool-git-privilege-guard.py's fail-closed style (_block()
writes stderr + sys.exit(2)).  Fail-open applies ONLY to the cheap detection
step on a command that does not match (keeps this hook a no-op for the
overwhelming majority of Bash calls); once a target invocation is positively
detected, an internal error during validation fails CLOSED (sys.exit(2)) --
this hook only reaches that risky code path after already proving the
command is push-related, so staying permissive there would defeat the
guard's purpose.

Revision history:
  2026-10-02 (task 20261001-161041-r17): initial hook, closing the gap that
  Chain-B validation lived entirely inside two editable plain scripts with no
  independent hook-layer cross-check.

Exit codes (PreToolUse convention):
  0: Allow tool use
  2: Block tool use
"""

import glob
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
# Reused READ-ONLY from the existing classifier -- no modification to that
# shared module (scope: this is a new, additive hook only).
from lib.git_command_classifier import (  # noqa: E402
    _basename, _segments, _command_token_index, _unquote_token)
from lib.harness_state_dir import harness_state_dir  # noqa: E402

_SENTINEL_BASE = harness_state_dir() + "/agentic-commit/push-analyst"
_TARGET_BASENAMES = {"execute-push.py", "push.sh"}
_INTERPRETERS = {"python3", "python", "bash", "sh", "dash"}


def _block(message):
    sys.stderr.write(message)
    sys.exit(2)


def _git_output(args, cwd=None):
    """Run `git <args...>` and return stripped stdout, or '' on any error."""
    try:
        result = subprocess.run(
            ['git'] + list(args),
            capture_output=True,
            text=True,
            timeout=5,
            cwd=cwd,
        )
        if result.returncode != 0:
            return ''
        return (result.stdout or '').strip()
    except Exception:
        return ''


def _locate_invocation(command):
    """Scan every shell segment for a Bash-tool-call invocation of
    execute-push.py or push.sh, detected by SCRIPT-BASENAME TOKEN.

    Two shapes only (per the ticket's evidence -- these are the two commands
    the sanctioned /push flow actually issues):
      direct exec:          <path>/execute-push.py --repo-hash ...
      interpreter-invoked:  python3|python|bash|sh|dash <path>/execute-push.py ...

    Returns (target_basename, args_tokens) for the first matching segment,
    or (None, None) when no segment matches.
    """
    for seg in _segments(command):
        toks = seg.split()
        if not toks:
            continue
        idx = _command_token_index(toks)
        if idx is None or idx >= len(toks):
            continue
        head = _basename(_unquote_token(toks[idx]))
        if head in _TARGET_BASENAMES:
            return head, toks[idx + 1:]
        if head in _INTERPRETERS:
            for j in range(idx + 1, len(toks)):
                t = toks[j]
                if t.startswith('-'):
                    continue
                cand = _basename(_unquote_token(t))
                if cand in _TARGET_BASENAMES:
                    return cand, toks[j + 1:]
                break
    return None, None


def _extract_flag(args, flag_name):
    """Return the value of `--flag value` or `--flag=value`, or None."""
    prefix = flag_name + '='
    for i, t in enumerate(args):
        tu = _unquote_token(t)
        if tu == flag_name:
            return _unquote_token(args[i + 1]) if i + 1 < len(args) else None
        if tu.startswith(prefix):
            return _unquote_token(tu[len(prefix):])
    return None


def _derive_repo_context():
    """Independently re-derive repo_hash/branch/head from live git state --
    mirrors commands/push.md Step 2's REPO_ROOT/REPO_HASH/BRANCH computation
    and hooks/push.sh's _CHAIN_B_REPO_HASH/_CHAIN_B_BRANCH_RAW, so the grant
    lookup path and the branch binding check never trust the invoked
    command's own --repo-hash/--branch argument text.
    """
    toplevel = _git_output(['rev-parse', '--show-toplevel'])
    if not toplevel:
        return None
    repo_root = os.path.realpath(toplevel)
    repo_hash = hashlib.sha256(repo_root.encode()).hexdigest()[:16]
    branch = _git_output(['rev-parse', '--abbrev-ref', 'HEAD'], cwd=repo_root)
    head_sha = _git_output(['rev-parse', 'HEAD'], cwd=repo_root)
    if not branch or not head_sha:
        return None
    return {
        'repo_root': repo_root,
        'repo_hash': repo_hash,
        'branch': branch,
        'head_sha': head_sha,
    }


def _derive_session_id(data):
    """session_id comes from the hook's own trusted PreToolUse payload
    (same field hooks/pretool-git-privilege-guard.py's _get_session_id reads),
    not from the command text, which carries no session_id argument at all.
    """
    sid = data.get('session_id') or ''
    if sid:
        return str(sid)
    return os.environ.get('CLAUDE_SESSION_ID') or os.environ.get('CLAUDE_CODE_SESSION_ID') or ''


def _resolve_default_remote(repo_root):
    """Mirrors push.sh/commands/push.md's fork-preferred-over-origin default."""
    try:
        r = subprocess.run(
            ['git', 'remote', 'get-url', 'fork'],
            cwd=repo_root, capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            return 'fork'
    except Exception:
        pass
    return 'origin'


def _load_grant(grant_path):
    """Read and JSON-parse a grant file; None on missing/empty/malformed."""
    try:
        text = Path(grant_path).read_text()
        if not text.strip():
            return None
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            return None
        return parsed
    except Exception:
        return None


def _validate_grant_fields(grant, expected):
    """Re-validate grant against the SAME binding fields scripts/execute-push.py
    checks: nonce, branch, remote_name, session_id, verdict, expires_at,
    head_sha. Returns None on success, or a human-readable reason string on
    failure. Never mutates or unlinks `grant` -- read-only re-check.
    """
    for field in ('nonce', 'branch', 'remote_name', 'session_id'):
        actual = grant.get(field)
        exp = expected.get(field)
        if not isinstance(actual, str) or not actual:
            return "grant field '%s' is missing or empty" % field
        if actual != exp:
            return "grant field '%s' mismatch -- grant has %r, expected %r" % (
                field, actual, exp)
    verdict = grant.get('verdict')
    if verdict not in ('approved', 'warn', 'blocked'):
        return "grant field 'verdict' is invalid: %r" % (verdict,)
    if verdict == 'blocked':
        return "push-analyst grant verdict is 'blocked'"
    expires_at_raw = grant.get('expires_at', '')
    try:
        expires_at = datetime.fromisoformat(str(expires_at_raw).replace('Z', '+00:00'))
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise ValueError('tz-naive')
        expires_at = expires_at.astimezone(timezone.utc)
    except Exception:
        return "grant field 'expires_at' is not a valid timezone-aware ISO-8601 datetime: %r" % (
            expires_at_raw,)
    if expires_at <= datetime.now(timezone.utc):
        return "grant field 'expires_at' is in the past (%s)" % (expires_at_raw,)
    head_sha_from_grant = grant.get('head_sha', '')
    if not isinstance(head_sha_from_grant, str) or not head_sha_from_grant:
        return "grant field 'head_sha' is missing or empty"
    if head_sha_from_grant != expected.get('head_sha'):
        return "HEAD drift detected -- grant.head_sha is %r but current HEAD is %r" % (
            head_sha_from_grant, expected.get('head_sha'))
    return None


def _evaluate_execute_push(args, data):
    ctx = _derive_repo_context()
    if ctx is None:
        _block(
            '\nBLOCKED: push-analyst grant guard could not independently derive '
            'repo state (git rev-parse failed); refusing execute-push.py invocation.\n'
        )
    session_id = _derive_session_id(data)
    if not session_id:
        _block(
            '\nBLOCKED: push-analyst grant guard could not resolve a session_id; '
            'refusing execute-push.py invocation.\n'
        )
    request_id = _extract_flag(args, '--request-id')
    remote = _extract_flag(args, '--remote')
    if not request_id or not remote:
        _block(
            '\nBLOCKED: push-analyst grant guard: execute-push.py invocation is '
            'missing --request-id/--remote; cannot locate or bind a push-analyst grant.\n'
        )
    grant_path = Path(_SENTINEL_BASE) / ctx['repo_hash'] / session_id / ('%s.json' % request_id)
    grant = _load_grant(grant_path) if grant_path.exists() else None
    if grant is None:
        _block(
            '\nBLOCKED: push-analyst grant guard: no push-analyst grant found at %s.\n'
            'execute-push.py invocation refused before it could start.\n' % grant_path
        )
    expected = {
        'nonce': request_id,
        'branch': ctx['branch'],
        'remote_name': remote,
        'session_id': session_id,
        'head_sha': ctx['head_sha'],
    }
    err = _validate_grant_fields(grant, expected)
    if err:
        _block(
            '\nBLOCKED: push-analyst grant guard: %s.\n'
            'Grant at %s left untouched (not consumed).\n' % (err, grant_path)
        )
    # Valid, matching grant -- allow. scripts/execute-push.py performs its own
    # (unmodified) internal validation, verdict handling, and consumption.


def _evaluate_push_sh(args, data):
    ctx = _derive_repo_context()
    if ctx is None:
        _block(
            '\nBLOCKED: push-analyst grant guard could not independently derive '
            'repo state (git rev-parse failed); refusing push.sh invocation.\n'
        )
    session_id = _derive_session_id(data)
    if not session_id:
        _block(
            '\nBLOCKED: push-analyst grant guard could not resolve a session_id; '
            'refusing push.sh invocation.\n'
        )
    explicit_remote = None
    for t in args:
        tu = _unquote_token(t)
        if tu == '--auto' or tu.startswith('-'):
            continue
        explicit_remote = tu
        break
    remote = explicit_remote or _resolve_default_remote(ctx['repo_root'])
    grant_dir = Path(_SENTINEL_BASE) / ctx['repo_hash'] / session_id
    candidates = glob.glob(str(grant_dir / '*.json'))
    try:
        candidates.sort(key=lambda p: os.stat(p).st_mtime, reverse=True)
    except Exception:
        candidates.sort(reverse=True)
    for cand_path in candidates:
        grant = _load_grant(cand_path)
        if grant is None:
            continue
        # push.sh (invoked directly, bypassing execute-push.py) carries no
        # --request-id argument, so the nonce cannot be bound to anything the
        # command states -- bind it to itself (still enforcing "present and
        # non-empty") and validate every OTHER field independently derived.
        expected = {
            'nonce': grant.get('nonce'),
            'branch': ctx['branch'],
            'remote_name': remote,
            'session_id': session_id,
            'head_sha': ctx['head_sha'],
        }
        if _validate_grant_fields(grant, expected) is None:
            return  # a still-valid, matching grant exists -- allow
    _block(
        '\nBLOCKED: push-analyst grant guard: no push-analyst grant found under %s.\n'
        'hooks/push.sh invocation refused before it could start -- push.sh must only '
        'ever be reached via scripts/execute-push.py (which os.execv replaces itself '
        'with push.sh), never as a direct Bash call.\n' % grant_dir
    )


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    if data.get('tool_name', '') != 'Bash':
        sys.exit(0)
    command = (data.get('tool_input', {}) or {}).get('command', '') or ''
    if not command:
        sys.exit(0)
    try:
        target, args = _locate_invocation(command)
    except Exception:
        # Detection crashed on an ORDINARY command -- stay permissive; this
        # hook must not become a universal Bash blocker on a parsing bug.
        sys.exit(0)
    if target is None:
        sys.exit(0)
    try:
        if target == 'execute-push.py':
            _evaluate_execute_push(args, data)
        else:
            _evaluate_push_sh(args, data)
    except SystemExit:
        raise
    except Exception:
        # A target invocation WAS positively detected -- an internal error
        # validating it must fail CLOSED, not silently let a push through.
        _block(
            '\nBLOCKED: push-analyst grant guard internal error while validating '
            'a detected execute-push.py/push.sh invocation -- failing closed '
            '(see docs/dev/ticket-20261001-161041-r17.md).\n'
        )
    sys.exit(0)


if __name__ == '__main__':
    main()
