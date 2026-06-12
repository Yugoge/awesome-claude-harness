#!/usr/bin/env python3
"""PreToolUse Hook: user-intent sentinel guard for the /stop release wrapper.

fix-4 (Cycle-2, spec-20260604-204954 §7.4). The /stop slash command releases
overnight isolation by running `scripts/break-overnight-lock.py` (via
`hooks/stop.sh`), the ONLY sanctioned setter of `isolation_released_at`. An
overnight ACTOR must NOT be able to self-release isolation by invoking that
helper directly from a Bash tool call.

Mechanism (mirrors the commit/push/merge sentinel-grant model):
  * The UserPromptSubmit hook (`prompt-workflow.py::_write_userintent_sentinel`)
    writes `/tmp/claude-stop-userintent-<sid>.flag` ONLY when the user actually
    typed `/stop`.
  * THIS PreToolUse hook fires on every Bash command. When the command invokes
    `break-overnight-lock.py` (or `hooks/stop.sh`), it REQUIRES a live sentinel
    for the calling session; absent -> BLOCK (exit 2). Present -> CONSUME it
    one-shot (unlink) and ALLOW (exit 0), so a replayed/stale sentinel is
    rejected on the next attempt.

This is the PreTool surface. The helper itself ALSO validates the sentinel
before mutating state (defense in depth), so a bypass of this hook still cannot
release isolation.

Exit codes:
  0: allow (not a guarded wrapper, or a valid live sentinel was consumed)
  2: block (guarded wrapper invoked without a valid live user-intent sentinel)
"""

import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from lib.bash_write_targets import command_without_heredoc_bodies
except Exception:  # pragma: no cover - fail-soft when lib missing
    def command_without_heredoc_bodies(command: str) -> str:  # type: ignore
        return command

# Wrapper scripts whose direct EXECUTION requires a matching user-intent
# sentinel. The key is the sentinel command-name (/tmp/claude-<name>-userintent-).
#
# IMPORTANT (no over-block): match only an actual EXECUTION of the wrapper, NOT a
# mere mention (so read-only `git cat-file … break-overnight-lock.py`, `grep`,
# `echo`, etc. are NOT blocked — this MUST NOT break a normal session's git ops).
# Execution forms covered:
#   * an interpreter/`.`/`source`/`exec` followed by the script path
#     (python3 …/break-overnight-lock.py ; bash …/stop.sh ; . …/stop.sh), OR
#   * the script invoked directly as the command (a path ending in the script
#     name appearing at a command position: line start, after ; | & or `&&`/`||`).
# An interpreter token only counts as an EXECUTION prefix when it stands at a
# command position — i.e. NOT preceded by a path char (so `create-overnight-
# state.sh <wrapper>` does NOT match via the trailing `sh`). The `(?<![\w./-])`
# look-behind on the interpreter rejects a filename-suffix match; the wrapper
# itself is recognized only at a command position (start / after ; & | ( nl).
_EXEC_PREFIX = (
    r'(?:'
    r'^|[;&|(\n]\s*'  # the wrapper itself at a command position
    r'|(?<![\w./-])(?:python3?|bash|sh|zsh|dash|env|exec|command|source)\s+(?:-\S+\s+)*'
    r'|(?<![\w./-])\.\s+'
    r')')
_GUARDED_WRAPPERS = {
    'stop': (
        re.compile(_EXEC_PREFIX + r'(?:\S*/)?break-overnight-lock\.py\b'),
        re.compile(_EXEC_PREFIX + r'(?:\S*/)?stop\.sh\b'),
    ),
}

# Directory holding the user-intent sentinels (overridable for sandbox tests).
_SENTINEL_DIR = os.environ.get('CLAUDE_USERINTENT_SENTINEL_DIR', '/tmp')


def _read_payload() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        sys.exit(0)


def _get_session_id(data: dict) -> str:
    try:
        return str(data.get('session_id', '') or '')
    except Exception:
        return ''


def _command_text(data: dict) -> str:
    ti = data.get('tool_input', {}) if isinstance(data, dict) else {}
    if not isinstance(ti, dict):
        return ''
    return ti.get('command', '') or ''


def _matched_wrapper(command: str) -> str | None:
    """Return the sentinel command-name if the command EXECUTES a guarded
    wrapper, else None.

    Heredoc bodies are stripped first so a heredoc that merely mentions the
    wrapper path as data (test fixtures, documentation, JSON) is not a false
    positive — this MUST NOT break normal sessions' read-only commands that
    happen to reference break-overnight-lock.py / stop.sh."""
    scan = command_without_heredoc_bodies(command)
    for name, patterns in _GUARDED_WRAPPERS.items():
        for pat in patterns:
            if pat.search(scan):
                return name
    return None


def _sentinel_path(cmd_name: str, sid: str) -> Path:
    return Path(_SENTINEL_DIR) / f'claude-{cmd_name}-userintent-{sid}.flag'


# Short-lived helper-authorization token. When THIS PreTool hook consumes a
# valid user-intent sentinel it mints this token; break-overnight-lock.py
# validates + consumes it before mutating isolation_released_at (defense in
# depth: the helper never trusts being reached, only a fresh PreTool grant).
_HELPER_AUTH_TTL_SECONDS = 30


def _helper_auth_path(cmd_name: str, sid: str) -> Path:
    return Path(_SENTINEL_DIR) / f'claude-{cmd_name}-helper-auth-{sid}.json'


def _mint_helper_auth(cmd_name: str, sid: str) -> None:
    try:
        _helper_auth_path(cmd_name, sid).write_text(json.dumps({
            'cmd': cmd_name,
            'session_id': sid,
            'expires_at': int(time.time()) + _HELPER_AUTH_TTL_SECONDS,
        }))
    except OSError:
        pass


def _consume_sentinel(path: Path) -> bool:
    """One-shot consume: True iff the sentinel existed with value 'true' and was
    successfully unlinked. A stale/already-consumed sentinel returns False."""
    try:
        if not path.exists():
            return False
        ok = path.read_text().strip() == 'true'
        # Unlink regardless (one-shot): a second invocation finds nothing.
        try:
            path.unlink()
        except OSError:
            return False
        return ok
    except OSError:
        return False


def _block(cmd_name: str, command: str) -> None:
    sys.stderr.write(
        f'\nUSER-INTENT GUARD: direct invocation of the /{cmd_name} release '
        'wrapper is blocked. This wrapper (break-overnight-lock.py / stop.sh) '
        'is the only sanctioned setter of isolation_released_at and may run '
        f'ONLY via the /{cmd_name} slash command, which writes a single-use '
        'user-intent sentinel. No live sentinel was found for this session, so '
        'an overnight actor cannot self-release isolation.\n'
        f'Blocked command: {command[:200]}\n'
    )
    sys.exit(2)


def main() -> None:
    data = _read_payload()
    if data.get('tool_name', '') != 'Bash':
        sys.exit(0)
    command = _command_text(data)
    if not command:
        sys.exit(0)
    cmd_name = _matched_wrapper(command)
    if cmd_name is None:
        sys.exit(0)
    sid = _get_session_id(data)
    sentinel = _sentinel_path(cmd_name, sid)
    if _consume_sentinel(sentinel):
        # Valid live user-intent sentinel: mint a fresh helper-auth token so the
        # helper can validate it (defense in depth), then allow.
        _mint_helper_auth(cmd_name, sid)
        sys.exit(0)
    _block(cmd_name, command)


if __name__ == '__main__':
    main()
