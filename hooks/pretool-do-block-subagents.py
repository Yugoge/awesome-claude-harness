#!/usr/bin/env python3
"""
PreToolUse hook: block Agent/Task dispatch from the MAIN agent while a /do
cycle is active.

WHY THIS HOOK EXISTS:
  During an active /do cycle the orchestrator gate is bypassed, so the main
  agent can (and must) do the work directly. If it dispatches a dev-type
  subagent anyway, that subagent writes docs/dev/dev-report-<TASK_ID>.json
  alongside the cycle's do-report-<TASK_ID>.json. /close (commands/close.md)
  and /commit (scripts/resolve-commit-repos.py) route purely on the existence
  of the canonical dev-report filename, so the cycle is switched onto the
  five-artifact /dev chain, immediately fails MISSING_ARTIFACT x4 in
  scripts/resolve-dev-artifact-chain.py, and becomes uncommittable. Backlog
  entry (2026-09-03, docs/reference/harness-issues-backlog.md): a stray
  dev-report coexisting with the do-report under one task-id misroutes
  /close onto the wrong chain.

  The existing hooks make this WORSE, not better: both
  pretool-subagent-enforce.py and pretool-block-background-tasks.py treat the
  /do consent flag as a bypass that LOOSENS Agent dispatch. Those bypasses
  stay as they are (single responsibility); this hook simply blocks earlier /
  independently — any exit-2 PreToolUse hook blocks the call.

SEMANTICS (decision table, first match wins):
  1. tool_name not Agent/Task ................................ exit 0
  2. caller is a subagent context (lib.subagent) ............. exit 0
  3. no active /do consent flag for this session ............. exit 0
  4. structured /allow grant for the Agent tool exists ....... exit 0
     (human escape hatch — same read_grant("Agent", sid) lookup
      pretool-subagent-enforce.py already uses)
  5. otherwise (main agent, /do active) ...................... exit 2

  Active-/do detection reuses the EXACT same source of truth as the existing
  consent bypasses: /tmp/claude-orchestrator-consent-<session_id>.flag exists
  AND its content is the string "true" (mirrors _has_consent in
  pretool-subagent-enforce.py). No new sentinel, no second convention.

FAIL-OPEN, never-wedge:
  Malformed or empty stdin, unreadable flag, unexpected exceptions -> exit 0.
  Matching neighboring hooks: absence of signal must never block unrelated
  sessions.

Exit codes:
  0 — Allow.
  2 — Reject (main-agent Agent/Task dispatch during an active /do cycle).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.subagent import is_subagent_context  # noqa: E402
from lib.allowlist import read_grant          # noqa: E402


def _parse_stdin() -> dict:
    try:
        data = json.load(sys.stdin)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _has_consent(session_id: str) -> bool:
    """Mirror of _has_consent in pretool-subagent-enforce.py — same flag path,
    same content check. This MUST stay byte-equivalent in semantics so the
    block window of this hook is exactly the bypass window of the others."""
    try:
        flag = Path(f'/tmp/claude-orchestrator-consent-{session_id}.flag')
        return flag.exists() and flag.read_text().strip() == 'true'
    except Exception:
        return False


def _emit_block(tool_name: str, session_id: str) -> None:
    sys.stderr.write(
        '\nDO-CYCLE BLOCK (pretool-do-block-subagents):\n'
        f'  tool={tool_name} session={session_id}\n'
        '  reason: an active /do cycle forbids subagent dispatch from the main agent.\n'
        '  no-delegation-needed: /do means the main agent does the work DIRECTLY —\n'
        '    the orchestrator gate bypass is already active for this session, so\n'
        '    every tool the work needs is available without dispatching a subagent.\n'
        '  why-forbidden: a dispatched dev/qa subagent writes its report file\n'
        '    (docs/dev/dev-report-<TASK_ID>.json) alongside the /do cycle\'s\n'
        '    do-report-<TASK_ID>.json under the same task id; /close and /commit\n'
        '    route purely on the canonical dev-report filename, flip the cycle onto\n'
        '    the five-artifact /dev chain, and it fails MISSING_ARTIFACT x4 — the\n'
        '    cycle becomes uncommittable. Backlog entry (2026-09-03,\n'
        '    docs/reference/harness-issues-backlog.md): a stray dev-report coexisting\n'
        '    with the do-report under one task-id misroutes /close onto the wrong chain.\n'
        '  way-forward: do the work directly in this /do cycle, or finish /do (write\n'
        '    the terminal do-report) and start a normal /dev cycle in a fresh turn.\n'
        '    A human may override this block with an /allow grant for the Agent tool.\n'
        '\n'
    )


def _main() -> None:
    try:
        stdin_data = _parse_stdin()
        if not stdin_data:
            sys.exit(0)
        if stdin_data.get('tool_name') not in ('Agent', 'Task'):
            sys.exit(0)
        # Only the MAIN agent is blocked; subagent contexts pass through.
        if is_subagent_context(stdin_data):
            sys.exit(0)
        session_id = stdin_data.get('session_id', 'default')
        if not _has_consent(session_id):
            sys.exit(0)
        # Human escape hatch: an explicit /allow grant for the Agent tool
        # overrides the block (read-only; consumption stays in PostToolUse).
        if read_grant('Agent', session_id):
            sys.exit(0)
        _emit_block(stdin_data.get('tool_name'), session_id)
        sys.exit(2)
    except SystemExit:
        raise
    except Exception:
        # Fail open: this hook's absence of signal must never wedge a session.
        sys.exit(0)


if __name__ == '__main__':
    _main()
