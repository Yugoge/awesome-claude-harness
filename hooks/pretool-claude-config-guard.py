#!/usr/bin/env python3
"""
PreToolUse Hook: Claude config (.claude/hooks + .claude/commands) protection.

Scope: Runs in EVERY session (NOT scoped to /dev-overnight). Closes the gap
that allowed b5d447e (2026-04-21 17:45 UTC) to silently rewrite four
checkpoint hooks as part of a 93-file sweep. Blocks Edit/Write/Bash
modifications targeting `.claude/hooks/*` and `.claude/commands/*` unless
the per-project sentinel `.claude/.hook-refactor-allow` exists at the
active project root.

Why exists:
  - The orchestrator-gate in `pretool-orchestrator-gate.py` is RATE-based
    (consecutive same-name tool count) and was bypassed at 2026-04-21
    17:44:54 with a Grep streak-reset before commit b5d447e succeeded.
  - This hook is SEMANTIC: it refuses ANY agent-driven edit to the
    config surface unless the user has affirmatively opted in by
    creating the sentinel file.
  - Spec reference: spec-20260424-233926 §5.2.4 (R4.2).
  - Note: Bash redirect regex tightened to ``\\S*`` per spec-20260424-233926
    §5.2.4 Mystery 4 to eliminate false-positives on read-only Bash
    containing `2>&1` together with `.claude/hooks/` in a non-redirect
    position (e.g. a path argument).

Allow-list mechanism: The sentinel file `.claude/.hook-refactor-allow` at
`$CLAUDE_PROJECT_DIR` (or cwd fallback). When present, this hook exits 0
and lets the underlying tool run. The user creates this file by hand
when they want to refactor hooks/commands; deleting it re-engages the
guard. Without it, two writes pass: /dev-command's dev writing the project
command file the cycle develops (_dev_command_product_file), and the cleaner
of an active /clean writing what that /clean's owner approved for it under
commands/ (_clean_approved_edit, _clean_approved_bash; hooks/pretool-tool-policy.py
holds the rule and refuses every other caller's write of those paths).

Exit codes:
  0: Allow tool use
  2: Block tool use

Fail-open: Any uncaught exception during hook evaluation results in
exit 0 — the hook never wedges the harness, even at the cost of skipping
its own check.
"""

import json
import os
import re
import sys
from pathlib import Path


SENTINEL_NAME = '.hook-refactor-allow'
BLOCK_LITERAL = 'BLOCKED: claude config guard'

_HOOK_PATTERNS = [
    r'(?:echo|printf)\s+.*>\s*\S*\.claude/hooks/',
    r'cat\s+.*>\s*\S*\.claude/hooks/',
    r'cp\s+.*\.claude/hooks/',
    r'mv\s+.*\.claude/hooks/',
    r'tee\s+.*\.claude/hooks/',
    r'>\s*\S*\.claude/hooks/',
    r'>>\s*\S*\.claude/hooks/',
]
_CMD_PATTERNS = [
    r'(?:echo|printf)\s+.*>\s*\S*\.claude/commands/',
    r'cat\s+.*>\s*\S*\.claude/commands/',
    r'cp\s+.*\.claude/commands/',
    r'mv\s+.*\.claude/commands/',
    r'tee\s+.*\.claude/commands/',
    r'>\s*\S*\.claude/commands/',
    r'>>\s*\S*\.claude/commands/',
]


def _project_dir() -> Path:
    """Return the active project directory."""
    return Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))


def _sentinel_present() -> bool:
    """True iff the allow-list sentinel exists at the project root."""
    return (_project_dir() / '.claude' / SENTINEL_NAME).exists()


def _is_hooks_path(file_path: str) -> bool:
    """True iff file_path targets .claude/hooks/."""
    if not file_path:
        return False
    return '.claude/hooks/' in file_path.replace('\\', '/')


def _is_commands_path(file_path: str) -> bool:
    """True iff file_path targets .claude/commands/."""
    if not file_path:
        return False
    return '.claude/commands/' in file_path.replace('\\', '/')


def _matches_any(command: str, patterns: list) -> bool:
    """True iff command matches any of the regex patterns."""
    return any(re.search(p, command) for p in patterns)


# The harness home and the CLI's config dir named through a variable. The patterns above read raw
# text, so `"${CLAUDE_HOME:-$HOME/.claude}/commands/x.md"` (the spelling the prompts use) or
# `$CLAUDE_HOME/hooks/x.py` names no `.claude/<dir>/` and went through, where `~/.claude/...` is
# refused. Either variable may hold a protected root in the shell that runs the command (an
# assignment earlier in the same command, a profile), whatever the hook's own environment says,
# so each spelling of them counts as the home (fails closed), as an unknown prefix before a
# written-out `.claude/hooks/` is refused today.
_HOME = '~/.claude'
_HOME_VARS = ('CLAUDE_HOME', 'CLAUDE_CONFIG_DIR')
_BARE_HOME_VAR = re.compile(r'\$(?:CLAUDE_HOME|CLAUDE_CONFIG_DIR)(?![A-Za-z0-9_])')
_BRACE = re.compile(r'\$\{|\}')
_PARAMETER = re.compile(r'([A-Za-z_][A-Za-z0-9_]*|[0-9]+)(:?[-=?+])?(.*)\Z', re.S)


def _resolve_parameter(body: str) -> str:
    """The text a `${body}` expansion (its inner expansions resolved) may stand for, as far as it is
    known without running it: a home variable is the home (its `+` forms: the word used when it is
    set); another variable's `-`, `=` and `+` forms are their word (the branch readable here)."""
    found = _PARAMETER.match(body)
    if not found:
        return '${' + body + '}'
    name, op, word = found.groups()
    if name in _HOME_VARS:
        return word if op and op.endswith('+') else _HOME
    if op and op[-1] in '-=+':
        return word
    return '${' + body + '}'


def _expand_parameters(text: str) -> str:
    """``text`` with each balanced `${...}` replaced by _resolve_parameter, innermost first, in one
    pass without recursion (a deep nesting cannot raise and so fail open); an unclosed one stays."""
    stack, i = [[]], 0
    for mark in _BRACE.finditer(text):
        stack[-1].append(text[i:mark.start()])
        i = mark.end()
        if mark.group() == '${':
            stack.append([])
        elif len(stack) > 1:
            body = ''.join(stack.pop())
            stack[-1].append(_resolve_parameter(body))
        else:
            stack[-1].append('}')
    stack[-1].append(text[i:])
    while len(stack) > 1:
        body = ''.join(stack.pop())
        stack[-1].append('${' + body)
    return ''.join(stack[0])


def _home_spelled_out(command: str) -> str:
    """``command`` with the home variables written as ~/.claude and its quotes removed, so a
    home spelling reaches the patterns as `~/.claude/<dir>/` (`"$HOME/.claude"/commands/` too)."""
    text = _BARE_HOME_VAR.sub(lambda _m: _HOME, _expand_parameters(command))
    return text.replace('"', '').replace("'", '')


def _classify_bash_target(command: str) -> str:
    """Return 'hooks', 'commands', or '' for a Bash command, as written or with the home spelled out."""
    if not command:
        return ''
    for text in dict.fromkeys((command, _home_spelled_out(command))):
        if _matches_any(text, _HOOK_PATTERNS):
            return 'hooks'
        if _matches_any(text, _CMD_PATTERNS):
            return 'commands'
    return ''


def _block(message: str) -> None:
    """Write message to stderr and exit 2."""
    sys.stderr.write(message)
    sys.exit(2)


def _block_path(tool_name: str, file_path: str, kind: str) -> None:
    """Emit a block for a Write/Edit to a protected path."""
    _block(
        f'\n{BLOCK_LITERAL}: agent {tool_name} to .claude/{kind}/ '
        f'is forbidden outside an explicit refactor session.\n'
        f'Attempted: {tool_name} -> {file_path}\n'
        f'To override: create the sentinel file '
        f'`.claude/{SENTINEL_NAME}` at the project root, perform the '
        f'edit, then delete the sentinel.\n'
        f'Spec: spec-20260424-233926 §5.2.4 (R4.2). Closes the gap '
        f'that allowed b5d447e to rewrite checkpoint hooks during a '
        f'sweep commit.\n'
    )


def _block_bash(command: str, kind: str) -> None:
    """Emit a block for a Bash write to a protected path."""
    _block(
        f'\n{BLOCK_LITERAL}: agent Bash write to .claude/{kind}/ '
        f'is forbidden outside an explicit refactor session.\n'
        f'Command excerpt: {command[:200]}\n'
        f'To override: create the sentinel file '
        f'`.claude/{SENTINEL_NAME}` at the project root.\n'
        f'Spec: spec-20260424-233926 §5.2.4 (R4.2).\n'
    )


def _dev_command_product_file(file_path: str, data: dict) -> bool:
    """The write /dev-command exists for (X4 (b)): its dev, a subagent whose own
    dispatch (subagent_type dev, an obligation of role dev) lies in the span a
    human-typed /dev-command opened, writes <project>/.claude/commands/<name>.md,
    not the harness home's. Anything unread or unmatched is False (blocked)."""
    try:
        project = os.path.realpath(_project_dir())
        target = os.path.realpath(os.path.join(project, file_path))
        home = os.path.realpath(os.path.expanduser(os.environ.get('CLAUDE_HOME') or '~/.claude'))
        if (not data.get('agent_id') or not target.endswith('.md') or home == os.path.join(project, '.claude')
                or os.path.dirname(target) != os.path.join(project, '.claude', 'commands')):
            return False
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from lib import command_span, declared_paths, obligation
        transcript = Path(data['transcript_path'])
        if transcript.parent.name == 'subagents':  # <sid>/subagents/agent-x.jsonl -> <sid>.jsonl
            transcript = transcript.parent.parent.with_suffix('.jsonl')
        span = command_span.active_span(transcript)
        if span is None or span.command != 'dev-command':
            return False
        agent_transcript = declared_paths._agent_files(transcript, data['agent_id'])[0]
        prompt = obligation.read_first_record_prompt(agent_transcript)
        # the CLI's meta of the subagent, read by the one reader every gate takes its call id from
        call_id = obligation._read_meta_tool_use_id(agent_transcript)
        parsed = obligation.parse_obligation(prompt)
        return (isinstance(parsed, obligation.ParsedObligation) and parsed.obligation.get('role') == 'dev'
                and any(c.id == call_id and c.input.get('prompt') == prompt
                        and c.input.get('subagent_type') == 'dev' for c in span.iter_calls('Agent', 'Task')))
    except Exception:
        return False


def _clean_grant(data: dict) -> tuple:
    """(paths written, paths removed) the caller may write as the producer of what a
    human-typed /clean's owner approved (P9-4): the cleaner's approved moves, renames and
    fix_style edits of the active /clean span, read by hooks/pretool-tool-policy.py's one rule
    (clean_grant), which also refuses every other caller's write of them. A /clean run in the
    harness home approves moves and edits under commands/ (and agents/); nothing else is
    exempted here. Anything unread is empty (blocked)."""
    try:
        if not data.get('agent_id'):
            return frozenset(), frozenset()
        import importlib.util
        here = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, here)
        spec = importlib.util.spec_from_file_location('_tool_policy_clean', os.path.join(here, 'pretool-tool-policy.py'))
        policy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(policy)
        project = os.path.abspath(str(_project_dir()))
        return policy.clean_grant(data, project)
    except Exception:
        return frozenset(), frozenset()


def _forms(path: str) -> set:
    path = os.path.join(str(_project_dir()), os.path.expanduser(path))
    forms = {os.path.normpath(path)}
    try:
        forms.add(os.path.realpath(path))
    except (OSError, ValueError):
        pass
    return forms


def _clean_approved_edit(file_path: str, data: dict) -> bool:
    """Whether file_path is a file /clean's owner approved for this caller to edit (above)."""
    written, _removed = _clean_grant(data)
    return bool(file_path) and bool(_forms(file_path) & written)


def _clean_approved_bash(command: str, data: dict) -> bool:
    """Whether every `.claude/commands/` the guard reads in ``command`` is spelled by a path
    /clean's owner approved for this caller (a move's source or destination, a fixed file):
    with each of those paths, as written absolute, real or below the home's spellings, taken
    out of the command and of its home-spelled-out text, neither names a protected directory."""
    written, removed = _clean_grant(data)
    paths = written | removed
    if not paths:
        return False
    home = os.path.realpath(os.path.expanduser(os.environ.get('CLAUDE_HOME') or '~/.claude'))
    spellings = set()
    for path in paths:
        spellings.add(path)
        rel = os.path.relpath(path, home)
        if rel != os.pardir and not rel.startswith(os.pardir + os.sep):
            spellings.update(f'{root}/{rel}' for root in (_HOME, '$HOME/.claude', '${HOME}/.claude'))
    for text in dict.fromkeys((command, _home_spelled_out(command))):
        for spelling in sorted(spellings, key=len, reverse=True):
            text = text.replace(spelling, ' ')
        if _matches_any(text, _HOOK_PATTERNS) or _matches_any(text, _CMD_PATTERNS):
            return False
    return True


def _evaluate_write_edit(tool_name: str, tool_input: dict, data: dict) -> None:
    """Apply guard for Write/Edit/MultiEdit/NotebookEdit tools."""
    file_path = tool_input.get('file_path', '') or ''
    if _is_hooks_path(file_path):
        _block_path(tool_name, file_path, 'hooks')
    if (_is_commands_path(file_path) and not _dev_command_product_file(file_path, data)
            and not _clean_approved_edit(file_path, data)):
        _block_path(tool_name, file_path, 'commands')


def _evaluate_bash(tool_input: dict, data: dict) -> None:
    """Apply guard for Bash tool."""
    command = tool_input.get('command', '') or ''
    kind = _classify_bash_target(command)
    if kind and not (kind == 'commands' and _clean_approved_bash(command, data)):
        _block_bash(command, kind)


def _evaluate(tool_name: str, tool_input: dict, data: dict) -> None:
    """Dispatch evaluation by tool_name."""
    if tool_name in ('Edit', 'Write', 'MultiEdit', 'NotebookEdit'):
        _evaluate_write_edit(tool_name, tool_input, data)
    elif tool_name == 'Bash':
        _evaluate_bash(tool_input, data)


def main() -> None:
    """Entry point: read JSON-from-stdin, evaluate, exit 0/2."""
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    try:
        if _sentinel_present():
            sys.exit(0)
        tool_name = data.get('tool_name', '') or ''
        tool_input = data.get('tool_input', {}) or {}
        _evaluate(tool_name, tool_input, data)
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
    sys.exit(0)


if __name__ == '__main__':
    main()
