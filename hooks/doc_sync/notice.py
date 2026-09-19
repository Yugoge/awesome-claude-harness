#!/usr/bin/env python3
"""Notices for skipped README regeneration: text, per-audience dedupe state, hook JSON output.

A skipped README is a deliberate outcome (regeneration is opt-in through the AUTO
markers), but a silent skip looks exactly like a hook that did nothing, so every skip is
reported to the caller once per audience and README state.
"""

import hashlib
import json
import os
import re
import sys
import tempfile

from .regen_readme import README_CLOSE_MARKER, README_OPEN_MARKER, RegenStatus

HOOK_EVENT_NAME = 'PostToolUse'
NOTIFY_STATUSES = (RegenStatus.SKIPPED_NO_OPENING_MARKER, RegenStatus.SKIPPED_NO_CLOSING_MARKER)
# The documented cap for hook output strings is 10,000 characters; a notice is a pointer,
# not a report, so it stays far below it.
MAX_NOTICE_CHARS = 2000
TRUNCATION_SUFFIX = '...'
# session_id becomes a path component of the state directory, so it gets the same
# charset guard as hooks/session-scratch-init.sh (no separators, no traversal).
SESSION_ID_PATTERN = re.compile(r'[A-Za-z0-9_.-]{1,128}')
# Written by hooks/session-scratch-init.sh; only a directory that carries it is a
# registered session directory that hooks/sessionend-scratch-sweep.sh removes at SessionEnd.
OWNER_FILE = '.owner'
STATE_FILE_TEMPLATE = 'doc-sync-notices-{audience}.json'
AGENT_AUDIENCE_HASH_CHARS = 16
# Test seam, never set in production: tempfile.gettempdir() raises under RLIMIT_FSIZE=0
# (it probes each candidate by writing), which would make the state-write failure path
# unreachable from a test because directory resolution fails first.
STATE_ROOT_ENV = 'CLAUDE_DOC_SYNC_STATE_ROOT'

_NOTICE_PARTS = {
    RegenStatus.SKIPPED_NO_OPENING_MARKER: (
        f'opening marker {README_OPEN_MARKER} not found, so the README is treated as '
        'hand-written and left untouched',
        f'add {README_OPEN_MARKER} and {README_CLOSE_MARKER} to let doc-sync manage its '
        'stats section, or ignore this notice if the README is meant to stay hand-written',
    ),
    RegenStatus.SKIPPED_NO_CLOSING_MARKER: (
        'closing marker missing or placed before the opening marker, so the README was '
        'left untouched',
        f'place {README_CLOSE_MARKER} after {README_OPEN_MARKER} so the stats section can '
        'be regenerated',
    ),
}


def notifiable(results):
    """(resolved README path, status) pairs that deserve a notice, one per README."""
    unique = {}
    for readme_path, status in results:
        if status in NOTIFY_STATUSES:
            unique.setdefault(os.path.realpath(readme_path), status)
    return list(unique.items())


def build_notice_text(entries):
    lines = []
    for readme_path, status in entries:
        reason, action = _NOTICE_PARTS[status]
        lines.append(
            f'doc-sync: README not regenerated ({status.value}). '
            f'Reason: {reason}. Action: {action}. README: {readme_path}'
        )
    text = '\n'.join(lines)
    if len(text) > MAX_NOTICE_CHARS:
        text = text[:MAX_NOTICE_CHARS - len(TRUNCATION_SUFFIX)] + TRUNCATION_SUFFIX
    return text


def build_hook_output(text):
    """The one JSON object the harness reads from a PostToolUse hook's stdout.

    additionalContext reaches the agent, systemMessage the user; both carry the same text.
    """
    return {
        'systemMessage': text,
        'hookSpecificOutput': {'hookEventName': HOOK_EVENT_NAME, 'additionalContext': text},
    }


def audience_of(payload):
    """'main' for the top-level session, a stable per-subagent token otherwise.

    A subagent never saw the notice its parent received, so the two must not share state.
    """
    agent_id = payload.get('agent_id')
    if not agent_id:
        return 'main'
    digest = hashlib.sha256(str(agent_id).encode('utf-8', 'replace')).hexdigest()
    return 'agent-' + digest[:AGENT_AUDIENCE_HASH_CHARS]


def _state_root():
    override = os.environ.get(STATE_ROOT_ENV, '')
    if override and os.path.isabs(override):
        return override
    return tempfile.gettempdir()


def state_path_for(payload):
    """State file of this audience, or None when dedupe must stay off (notify every time).

    Dedupe needs a session directory that already exists and is registered by
    session-scratch-init.sh. The hook never creates it: a directory without an .owner
    record cannot be classified by the SessionEnd sweep and would linger for days.
    """
    try:
        session_id = payload.get('session_id')
        if not isinstance(session_id, str) or session_id in ('.', '..'):
            return None
        if not SESSION_ID_PATTERN.fullmatch(session_id):
            return None
        session_dir = os.path.join(_state_root(), session_id)
        if os.path.islink(session_dir) or not os.path.isdir(session_dir):
            return None
        if not os.path.isfile(os.path.join(session_dir, OWNER_FILE)):
            return None
        return os.path.join(session_dir, STATE_FILE_TEMPLATE.format(audience=audience_of(payload)))
    except Exception:
        # Includes a state root that cannot be resolved: no session directory, notify.
        return None


def read_state(path):
    """{state key: README digest}; anything unreadable or malformed counts as empty.

    Catches Exception, not only OSError and ValueError: a deeply nested file raises
    RecursionError, and any failure to read the state must mean "notify", never silence.
    """
    try:
        with open(path, encoding='utf-8') as handle:
            state = json.load(handle)
    except Exception:
        return {}
    return state if isinstance(state, dict) else {}


def write_state(path, state):
    """Atomically replace the state file; raises OSError when the write fails."""
    descriptor, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(path), prefix='.doc-sync-notices-', suffix='.tmp')
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump(state, handle)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _state_key(readme_path, status):
    return f'{readme_path}|{status.value}'


def _readme_digest(readme_path):
    """SHA-256 of the README, or None when it cannot be hashed (which always notifies)."""
    try:
        with open(readme_path, 'rb') as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except Exception:
        return None


def _detach_stdout():
    """Point fd 1 at devnull after a failed write.

    The text that could not be written stays in the stdout buffer and is flushed again at
    interpreter exit; on a broken pipe that second flush turns the exit code into 120.
    """
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull, sys.stdout.fileno())
        finally:
            os.close(devnull)
    except Exception:
        pass


def emit_post_tool_notice(results, payload):
    """Print one PostToolUse JSON object for skipped READMEs this audience has not seen.

    Never raises and never changes the exit code of the edit that triggered the hook.
    Every state problem (missing, corrupt, unreadable, unwritable) resolves to "notify":
    a lost notice is worse than a repeated one. The state key is recorded only after the
    notice was printed, so a failed print is retried on the next edit.
    """
    try:
        entries = notifiable(results)
        if not entries:
            return
        state_path = state_path_for(payload)
        state = read_state(state_path) if state_path else {}
        digests = {_state_key(path, status): _readme_digest(path) for path, status in entries}
        unseen = [
            (path, status) for path, status in entries
            if digests[_state_key(path, status)] is None
            or state.get(_state_key(path, status)) != digests[_state_key(path, status)]
        ]
        if not unseen:
            return
        print(json.dumps(build_hook_output(build_notice_text(unseen)), ensure_ascii=True))
        sys.stdout.flush()
    except Exception:
        _detach_stdout()
        return
    if not state_path:
        return
    try:
        for path, status in unseen:
            key = _state_key(path, status)
            if digests[key] is not None:
                state[key] = digests[key]
        write_state(state_path, state)
    except Exception:
        pass
