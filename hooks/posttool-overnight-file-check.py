#!/usr/bin/env python3
"""
PostToolUse:Agent Hook — Contract-driven overnight file check (G3).

At collection of a dispatch that the cycle's contract governs (a
required_calls entry of the cycle contract matches the returned Agent's role,
and its mode when the entry declares one), the artifacts the dispatch's OWN
obligation declares are checked where its producer wrote them, the session's
working root: a ``json`` artifact against the obligation's schema
(contract_runtime.validate_artifact_for_obligation), a ``markdown`` artifact
against its identity anchor and terminal line
(contract_runtime.validate_markdown_artifact_for_obligation). The contract
names no artifact and no schema: the obligation is the one declaration, so a
contract and a dispatch can never disagree on a schema version. A dispatch
that carries no obligation declares nothing to check here.

The session is the one whose overnight state record the returned call's
session owns; whether its window is live is lib.overnight.state_verdicts's
verdict, and the cycle is lib.overnight.cycle_index.

HARD CUTOVER: when the cycle has no ``cycle-contract.json`` (before PM TRIAGE
returns, or outside /dev-overnight), exit 0 silently.

Exit codes:
  0 — Not an overnight session, window closed, no contract, no matching
      entry, no obligation, or every declared artifact valid.
  2 — A declared artifact missing or invalid (hard gate).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib import contract_runtime  # noqa: E402
from lib import obligation  # noqa: E402
from lib import overnight  # noqa: E402


def _entry_for_dispatch(contract: dict, role: str, mode: str) -> dict | None:
    """The contract entry the returned dispatch answers, if any."""
    for entry in contract_runtime._iter_required_calls(contract):
        if not isinstance(entry, dict) or entry.get('role') != role:
            continue
        declared = entry.get('mode')
        if declared and mode and declared != mode:
            continue
        return entry
    return None


def _artifact_errors(artifact: dict, root: Path) -> list[str]:
    """Why one obligation artifact fails its declaration (empty when it passes)."""
    path = artifact.get('path')
    if not isinstance(path, str) or not path:
        return []
    kind = artifact.get('kind')
    if kind == 'json':
        result = contract_runtime.validate_artifact_for_obligation(
            root / path, artifact.get('schema'))
    elif kind == 'markdown':
        result = contract_runtime.validate_markdown_artifact_for_obligation(
            root / path, artifact.get('identity_anchor'), artifact.get('terminal_line_regex'))
    else:
        return []  # response kinds have no file; the producer's own stop checks them
    if result.get('status') != 'fail':
        return []
    return [f'{path}: {e}' for e in (result.get('errors') or [result.get('reason')])]


def _emit_block(agent_type: str, session_id: str, cycle_id: int, errors: list[str]) -> None:
    sys.stderr.write(
        '\nOVERNIGHT FILE CHECK BLOCK (contract):\n'
        f'  agent={agent_type} session={session_id} cycle={cycle_id}\n'
        '  errors:\n'
    )
    for item in errors:
        sys.stderr.write(f'    - {item}\n')
    sys.stderr.write('  Required artifact missing or schema-invalid. '
                     'Re-run the subagent or escalate.\n\n')


def _run_check(data: dict) -> int:
    ti = data.get('tool_input') or {}
    if not isinstance(ti, dict):
        return 0
    agent_type = ti.get('subagent_type', '')
    prompt = ti.get('prompt', '')
    session_id = data.get('session_id', '')
    state = overnight.session_state(session_id)
    if state is None or not overnight.state_verdicts(state).window_live:
        return 0
    cycle_id = overnight.cycle_index(state)
    contract = contract_runtime.load_contract(session_id, cycle_id, state)
    if not isinstance(contract, dict):
        # Hard cutover: no contract for this cycle yet — silent passthrough.
        return 0
    entry = _entry_for_dispatch(contract, agent_type, contract_runtime.detect_mode(prompt))
    if entry is None:
        return 0
    parsed = obligation.parse_obligation(prompt)
    if not isinstance(parsed, obligation.ParsedObligation):
        return 0
    root = overnight.working_root(state)
    errors = [error
              for artifact in parsed.obligation.get('artifacts') or []
              if isinstance(artifact, dict)
              for error in _artifact_errors(artifact, root)]
    if errors:
        _emit_block(agent_type, session_id, cycle_id, errors)
        return 2
    print(f'OVERNIGHT FILE CHECK: {agent_type} obligation artifacts valid '
          f'(step={entry.get("step")}).')
    return 0


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    sys.exit(_run_check(data))


if __name__ == '__main__':
    main()
