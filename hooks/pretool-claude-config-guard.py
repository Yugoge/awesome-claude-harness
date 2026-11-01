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
guard. Without it, one write passes: /dev-command's dev writing the project
command file the cycle develops (_dev_command_product_file).

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


def _classify_bash_target(command: str) -> str:
    """Return 'hooks', 'commands', or '' for a Bash command."""
    if not command:
        return ''
    if _matches_any(command, _HOOK_PATTERNS):
        return 'hooks'
    if _matches_any(command, _CMD_PATTERNS):
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
        agent_transcript, meta = declared_paths._agent_files(transcript, data['agent_id'])
        prompt = obligation.read_first_record_prompt(agent_transcript)
        call_id = json.loads(meta.read_text()).get('toolUseId')
        parsed = obligation.parse_obligation(prompt)
        return (isinstance(parsed, obligation.ParsedObligation) and parsed.obligation.get('role') == 'dev'
                and any(c.id == call_id and c.input.get('prompt') == prompt
                        and c.input.get('subagent_type') == 'dev' for c in span.iter_calls('Agent', 'Task')))
    except Exception:
        return False


def _evaluate_write_edit(tool_name: str, tool_input: dict, data: dict) -> None:
    """Apply guard for Write/Edit/MultiEdit/NotebookEdit tools."""
    file_path = tool_input.get('file_path', '') or ''
    if _is_hooks_path(file_path):
        _block_path(tool_name, file_path, 'hooks')
    if _is_commands_path(file_path) and not _dev_command_product_file(file_path, data):
        _block_path(tool_name, file_path, 'commands')


def _evaluate_bash(tool_input: dict) -> None:
    """Apply guard for Bash tool."""
    command = tool_input.get('command', '') or ''
    kind = _classify_bash_target(command)
    if kind:
        _block_bash(command, kind)


def _evaluate(tool_name: str, tool_input: dict, data: dict) -> None:
    """Dispatch evaluation by tool_name."""
    if tool_name in ('Edit', 'Write', 'MultiEdit', 'NotebookEdit'):
        _evaluate_write_edit(tool_name, tool_input, data)
    elif tool_name == 'Bash':
        _evaluate_bash(tool_input)


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
