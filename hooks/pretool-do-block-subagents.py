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
     (human escape hatch — same match_sentinel_grant_for_tool lookup
      pretool-subagent-enforce.py already uses)
  5. tool_input.subagent_type names a role allowed below ..... exit 0
     (_read_only_role)
  6. otherwise (main agent, /do active) ...................... exit 2

  Rule 5 is decided from structure, never from the dispatch prompt's wording,
  and fails closed. The collision above comes only from a role whose contract
  writes docs/dev/dev-report-<TASK_ID>.json (dev, qa, ba, changelog-analyst:
  agents/<role>.md), so these pass:
    - a built-in role with no Write, Edit or NotebookEdit tool and no
      dev-report duty: subagent_type equal, byte for byte (no case folding, no
      trimming), to Explore, Plan or claude-code-guide
      (READ_ONLY_BUILTIN_TYPES). Explore and Plan do hold Bash, so they are not
      strictly unable to write; what keeps them out of the collision is that
      no contract of theirs names a dev report. The built-in name counts only
      when no agent definition the runtime may load declares it, since a
      custom definition could shadow the built-in with write tools
      (_definition_declares: the harness home's agents/, ~/.claude/agents/,
      and .claude/agents/ of CLAUDE_PROJECT_DIR, of the payload cwd and of
      every directory above them; subdirectories and symlinks followed with a
      cycle guard; frontmatter read with a YAML loader after a BOM; a file
      whose stem or `name` matches case-insensitively, or any candidate file
      that cannot be read or parsed, keeps the call blocked);
    - a policies/tool-policy.v1.json role whose allowed_tools is non-empty
      and lies wholly inside READ_ONLY_TOOLS (no write tool, no Bash, no
      wildcard such as mcp__playwright__*): it cannot write at all.
    An omitted subagent_type (the runtime's general-purpose), general-purpose
    itself, any other role, an unknown type, a policy that cannot be read, a
    missing YAML loader, and any error while deciding all stay blocked.

  Active-/do detection is the one decision every consent bypass takes:
  lib.allowlist.has_do_consent, so the block window of this hook is exactly
  the bypass window of the others. No new sentinel, no second convention.

FAIL-OPEN, never-wedge:
  Malformed or empty stdin, unreadable flag, unexpected exceptions -> exit 0.
  Matching neighboring hooks: absence of signal must never block unrelated
  sessions.

Exit codes:
  0 — Allow.
  2 — Reject (main-agent Agent/Task dispatch of a role that can write during
      an active /do cycle).
"""

from __future__ import annotations
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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.subagent import is_subagent_context      # noqa: E402
from lib.allowlist import has_do_consent, match_sentinel_grant_for_tool  # noqa: E402


def _parse_stdin() -> dict:
    try:
        data = json.load(sys.stdin)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# Built-in agent types the runtime gives no Write, Edit or NotebookEdit tool and
# no dev-report duty (Explore and Plan hold Bash; no contract of theirs names
# docs/dev/dev-report-<TASK_ID>.json, the file the collision needs).
READ_ONLY_BUILTIN_TYPES = frozenset({"Explore", "Plan", "claude-code-guide"})
# Tools that cannot write a file. Bash is absent on purpose: it writes.
READ_ONLY_TOOLS = frozenset({"Read", "Glob", "Grep", "WebSearch", "WebFetch"})
_POLICY_RELPATH = "policies/tool-policy.v1.json"


def _agent_dirs(stdin_data: dict) -> list:
    """Every directory the runtime may load agent definitions from."""
    dirs = []
    try:
        from lib import claude_home
        home = claude_home.resolve()
        if home is not None:
            dirs.append(Path(home) / "agents")
    except Exception:
        pass
    dirs.append(Path.home() / ".claude" / "agents")
    for project in (os.environ.get("CLAUDE_PROJECT_DIR"), stdin_data.get("cwd")):
        if isinstance(project, str) and project:
            start = Path(os.path.abspath(project))
            for directory in (start, *start.parents):
                dirs.append(directory / ".claude" / "agents")
    return dirs


_MAX_DEFINITION_FILES = 5000


def _agent_files(directory: Path):
    """Every *.md under `directory`, following symlinked subdirectories once
    (a real-path cycle guard); more than _MAX_DEFINITION_FILES raises."""
    seen = set()
    count = 0
    for root, subdirs, files in os.walk(directory, followlinks=True, onerror=_raise):
        real = os.path.realpath(root)
        if real in seen:
            subdirs[:] = []
            continue
        seen.add(real)
        for name in files:
            if name.lower().endswith(".md"):
                count += 1
                if count > _MAX_DEFINITION_FILES:
                    raise OSError("too many agent definition files")
                yield Path(root) / name


def _raise(error):
    raise error


def _declared_name(text: str):
    """The frontmatter `name` of a definition (None when it has none).
    Raises on frontmatter a YAML loader cannot parse."""
    import yaml
    text = text.lstrip("\ufeff")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            data = yaml.safe_load("\n".join(lines[1:index]))
            break
    else:
        raise ValueError("unterminated frontmatter")
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError("frontmatter is not a mapping")
    return data.get("name")


def _definition_declares(name: str, stdin_data: dict) -> bool:
    """True when an agent definition declares `name` (case-insensitively), or
    any candidate definition cannot be read or parsed: either may shadow the
    built-in type."""
    wanted = name.strip().casefold()
    for directory in _agent_dirs(stdin_data):
        try:
            if not directory.is_dir():
                continue
            for path in _agent_files(directory):
                if path.stem.strip().casefold() == wanted:
                    return True
                declared = _declared_name(path.read_text(encoding="utf-8"))
                if declared is not None and str(declared).strip().casefold() == wanted:
                    return True
        except Exception:
            return True
    return False


def _policy_role_read_only(name: str) -> bool:
    """True when policies/tool-policy.v1.json lists `name` with only read tools."""
    from lib import claude_home
    path = claude_home.resolve_optional(_POLICY_RELPATH)
    if path is None:
        return False
    roles = json.loads(Path(path).read_text(encoding="utf-8")).get("roles")
    row = roles.get(name) if isinstance(roles, dict) else None
    tools = row.get("allowed_tools") if isinstance(row, dict) else None
    if not isinstance(tools, list) or not tools:
        return False
    return all(isinstance(t, str) and t in READ_ONLY_TOOLS for t in tools)


def _read_only_role(stdin_data: dict) -> bool:
    """Rule 5: the dispatched role is allowed during /do. Any doubt is False."""
    try:
        tool_input = stdin_data.get("tool_input")
        if not isinstance(tool_input, dict):
            return False
        name = tool_input.get("subagent_type")
        if not isinstance(name, str) or not name:
            return False
        if name in READ_ONLY_BUILTIN_TYPES:
            return not _definition_declares(name, stdin_data)
        return _policy_role_read_only(name)
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
        '  roles that pass: the built-ins with no Write/Edit/NotebookEdit tool\n'
        '    and no dev-report duty (Explore, Plan, claude-code-guide), or a\n'
        '    policies/tool-policy.v1.json role with no write tool and no Bash.\n'
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
        if not has_do_consent(stdin_data):
            sys.exit(0)
        # Human escape hatch: an explicit /allow grant for the Agent tool
        # overrides the block (read-only; consumption stays in PostToolUse).
        if match_sentinel_grant_for_tool(session_id, 'Agent') is not None:
            sys.exit(0)
        # A role with no dev-report duty and no Write/Edit tool cannot leave
        # the colliding dev-report.
        if _read_only_role(stdin_data):
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
