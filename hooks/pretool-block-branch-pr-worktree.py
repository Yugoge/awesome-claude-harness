#!/usr/bin/env python3
"""PreToolUse hook: refuse worktree creation on the Bash surface outside /dev-overnight.

Refused: every `git worktree add` the command runs, in command position, inside
a shell `-c` string, behind a wrapper or a git global option. Text that only
mentions it (`echo git worktree add x`) runs nothing and passes. Creating a
branch or a pull request is allowed; deleting or renaming a branch is refused as
a direct ref mutation by pretool-bash-safety.sh and pretool-git-privilege-guard.py.
The EnterWorktree tool is governed by pretool-block-enterworktree.sh.

Bypasses (any one allows):
  1. a live /dev-overnight session   (lib.overnight.is_overnight_active)
  2. /do consent                     (lib.allowlist.has_do_consent: main agent only)
  3. an /allow grant                 (sentinel grant: main agent and subagent)

Exit codes: 0 = allow, 2 = block (stderr shown to the agent).

Fails closed. An error the hook does not expect, a hooks/lib import that fails at
module load included, refuses a Bash call that may run `git worktree` (exit 2,
naming the hook and the error) unless a bypass is confirmed; it is not a policy
refusal. A call that cannot run it (_may_create) and another tool's call still
exit 0, so a broken hook does not refuse ordinary commands. Unreadable input (not
a JSON object) is judged on its raw text the same way.
"""
import os, sys  # noqa: E401 -- the harness switch (hooks/lib/harness_switch.py): no harness hook runs while /harness off holds
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))
try:  # a hook copied without its lib/ (an old install) is on
    import harness_switch  # noqa: E402
    harness_switch.exit_if_off()
except ImportError:
    pass
finally:
    sys.path.pop(0)

import json
import os
import sys
from pathlib import Path


# Fail closed. The code from here to the first hooks/lib import uses the standard
# library alone, so it still decides when a lib module fails to load or anything
# later raises; Python's own exit 1 there is a non-blocking hook error, and the
# harness would run the command unjudged.
_HOOK_NAME = 'pretool-block-branch-pr-worktree.py'
_STDIN = None


def _read_stdin():
    """The raw hook payload, read once, by main or by the load-failure hook."""
    global _STDIN
    if _STDIN is None:
        try:
            stream = getattr(sys.stdin, 'buffer', None)
            if stream is not None:
                _STDIN = stream.read().decode('utf-8', 'replace')
            else:
                _STDIN = sys.stdin.read()
        except Exception:
            _STDIN = ''
    return _STDIN


def _spells(text, word):
    """True when `word` (lower case) can be read in text with, between two of its
    letters, only text the hook's reading may delete: white space, a backslash,
    a quote (with its `$` prefix), a quoted span and a comment up to a newline
    (`gi'a b't` reads as `git`). Any letter case. A quoted span may end at any
    later same quote and a comment at any later newline, which covers every way
    of pairing them. One right-to-left pass, linear in len(text) * len(word)."""
    n, m = len(text), len(word)
    # reach[k][p]: from p, past deletable text only, word[k:] follows.
    reach = [[False] * (n + 1) for _ in range(m)]
    # later[c][k]: reach[k] just past a later quote c, or at a later newline.
    later = {c: [False] * m for c in '\'"\n'}
    for p in range(n - 1, -1, -1):
        ch = text[p]
        low = ch.lower()
        for k in range(m):
            own = low == word[k] and (k == m - 1 or reach[k + 1][p + 1])
            reach[k][p] = (own
                           or ((ch.isspace() or ch in '\\\'"') and reach[k][p + 1])
                           or (ch == '$' and text[p + 1:p + 2] in ('\'', '"') and reach[k][p + 1])
                           or (ch in '\'"' and later[ch][k])
                           or (ch == '#' and later['\n'][k]))
        if ch in '\'"':
            later[ch] = [later[ch][k] or reach[k][p + 1] for k in range(m)]
        elif ch == '\n':
            later[ch] = [later[ch][k] or reach[k][p] for k in range(m)]
    return any(reach[0][p] and text[p].lower() == word[0] for p in range(n))


def _may_create(text):
    """False only when text cannot run `git worktree` as this hook reads a
    command: the hook refuses only a command whose name is `git` with the
    subcommand `worktree`, and a run-time value spells neither word. An ANSI-C
    escape (`$'\\147'`) may spell any letter, so text holding one may create."""
    if "$'" in text and '\\' in text:
        return True
    return _spells(text, 'git') and _spells(text, 'worktree')


def _payload(raw):
    """The payload as a dict, or None when raw does not read as a JSON object."""
    try:
        data = json.loads(raw)
    except Exception:  # ValueError, or RecursionError for deep nesting
        return None
    return data if isinstance(data, dict) else None


def _judged_text(raw, data):
    """What an error is judged on: None for another tool's call, a Bash call's
    command, and the raw payload when it does not read as a tool call."""
    if data is None:
        return raw
    if data.get('tool_name', '') != 'Bash':
        return None
    tool_input = data.get('tool_input')
    command = tool_input.get('command') if isinstance(tool_input, dict) else None
    return command if isinstance(command, str) else raw


def _bypassed(text, data):
    """(confirmed, problems): confirmed is True only when a bypass is confirmed
    for this call; problems names each bypass check that is missing or raised,
    which confirms nothing."""
    checks = (
        ('is_overnight_active', lambda f: f(data.get('cwd'))),
        ('has_do_consent', lambda f: f(data)),
        ('_allow_grant_matches', lambda f: f(text, data)),
    )
    problems = []
    for name, call in checks:
        func = globals().get(name)
        if func is None:
            problems.append(f'{name} did not load')
            continue
        try:
            if call(func):
                return True, problems
        except Exception as exc:
            problems.append(f'{name} raised {type(exc).__name__}')
    return False, problems


_PROCEED = ('To proceed: run it inside a live /dev-overnight session, or (main agent) '
            'use /do, or /allow the specific command first.')
_PAUSE = ('You are a subagent: PAUSE and report this block to the user per '
          'Subagent Hook Discipline — do NOT attempt to work around it.')


def _internal_error_exit(exc, what='internal error'):
    """2, naming the hook and exc on stderr, when the call may create a worktree
    and no bypass is confirmed; else 0."""
    raw = _read_stdin()
    data = _payload(raw)
    text = _judged_text(raw, data)
    if text is None or not _may_create(text):
        return 0
    if data is not None:
        confirmed, problems = _bypassed(text, data)
        if confirmed:
            return 0
    lines = [
        '',
        f'BLOCKED: {_HOOK_NAME} {what}, not a policy refusal: '
        f'{type(exc).__name__}: {str(exc)[:300]}',
        'The hook could not judge this command, which may create a worktree, so it refuses it.',
        _PROCEED + ' Report the error.',
    ]
    if data is None:
        lines.append('Its input is not a JSON object, so no bypass can be read for it.')
    elif problems:
        lines.append('Bypass checks that could not run: ' + '; '.join(problems) + '.')
    if data is not None and data.get('agent_id'):
        lines.append(_PAUSE)
    sys.stderr.write('\n'.join(lines) + '\n')
    return 2


def _fail_closed_exit(exc, what='internal error'):
    """_internal_error_exit's code; 2 when judging the error raises too."""
    try:
        return _internal_error_exit(exc, what)
    except BaseException:
        return 2


def _refuse_on_load_failure(exc_type, exc, tb):
    """sys.excepthook while this file runs as the hook: an exception escaping the
    module (a hooks/lib import that fails, any module-level error) exits through
    _internal_error_exit instead of Python's exit 1."""
    code = _fail_closed_exit(exc)
    try:
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(code)


if __name__ == '__main__':
    sys.excepthook = _refuse_on_load_failure

sys.path.insert(0, str(Path(__file__).parent))
from lib.allowlist import (  # noqa: E402
    has_do_consent,
    match_sentinel_grant_for_bash_command,
)
from lib.overnight import is_overnight_active  # noqa: E402
from lib.shell_parse import git_invocations  # noqa: E402


def _detect(command):
    """True when command runs `git worktree add`, read by the shared parser."""
    for inv in git_invocations(command):
        if inv.subcommand == 'worktree':
            first = next((a for a in inv.args if a is None or not a.startswith('-')), None)
            if first == 'add':
                return True
    return False


def _allow_grant_matches(command, data):
    """True iff a /allow grant authorizes this command (main agent and subagent)."""
    try:
        sid = str(data.get('session_id', '') or '')
    except Exception:
        sid = ''
    task_id = os.environ.get('CLAUDE_TASK_ID') or sid
    try:
        return bool(task_id) and match_sentinel_grant_for_bash_command(task_id, command) is not None
    except Exception:
        return False


def _block(command, data):
    lines = ['', 'BLOCKED: worktree creation is forbidden outside /dev-overnight.']
    if command:
        lines.append(f'Command excerpt: {command[:200]}')
    lines += ['', _PROCEED]
    if data.get('agent_id'):
        lines.append(_PAUSE)
    sys.stderr.write('\n'.join(lines) + '\n')
    sys.exit(2)


def main():
    try:
        data = json.loads(_read_stdin())
    except Exception as exc:
        # No tool or command to read: 0, unless the raw text may create a worktree
        # (the hook is registered for Bash calls alone).
        sys.exit(_fail_closed_exit(exc, 'could not read its input'))
    try:
        if data.get('tool_name', '') != 'Bash':
            sys.exit(0)
        command = (data.get('tool_input', {}) or {}).get('command', '') or ''
        if not command.strip() or not _detect(command):
            sys.exit(0)
        if is_overnight_active(data.get('cwd')) or has_do_consent(data) or _allow_grant_matches(command, data):
            sys.exit(0)
        _block(command, data)
    except SystemExit:
        raise
    except Exception as exc:
        # An error is no verdict: refuse what may create one (_internal_error_exit).
        sys.exit(_fail_closed_exit(exc))
    sys.exit(0)


if __name__ == '__main__':
    main()
