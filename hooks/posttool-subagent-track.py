#!/usr/bin/env python3
"""
PostToolUse:Agent Hook: write the /dev-overnight cycle contract when PM TRIAGE returns.

PM TRIAGE handler (/dev-overnight): when the returned Agent call is the PM
TRIAGE step's dispatch, write the cycle's contract,
`<working root>/docs/dev/overnight/<sid>/cycle-<N>/cycle-contract.json`
(lib.contract_runtime.contract_path, N = lib.overnight.cycle_index). It
renders the dispatches after PM TRIAGE from scripts/todo/dev-overnight.py
_STEPS, each step's and each re-dispatch's (contract_runtime.post_triage_steps):
once per pipeline the cycle's triage report (_triage_report) creates (counted by
scripts/build-pipelines-from-triage.py, the Step-6 builder), except a step
whose dispatch carries a mode (PM RETRO), which runs once per cycle. This hook
is the contract's only writer and publishes it by rename; a contract the cycle
already has that lists calls (an earlier PM TRIAGE's, or one an orchestrator
wrote before this hook did) is kept as it is, so nothing edits a contract
after it is written.

It writes no workflow bookmark: Gate 4 reads a Claude session's Agent calls
from the transcript (pretool-todo-validate.py), and the Codex plan path reads
its subagent steps from Codex's own records (pretool-workflow-gate.py,
native_subagent_evidence_for_transition). Whether the dispatch produced its
artifact is decided by posttool-overnight-file-check.py at the same
PostToolUse (G3) and by the producer's own stop (G2), not here.

Exit codes:
  0: Always (never blocks).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib import contract_runtime
from lib import obligation
from lib import overnight


# ---------------------------------------------------------------------------
# Stdin parsing
# ---------------------------------------------------------------------------

def _parse_stdin() -> tuple:
    """Parse PostToolUse stdin JSON. Returns (data, session_id)."""
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    return data, data.get('session_id', 'default')


# ---------------------------------------------------------------------------
# PM TRIAGE handler — the cycle contract's one writer (/dev-overnight)
# ---------------------------------------------------------------------------

_BUILD_PIPELINES = Path(__file__).resolve().parent.parent / 'scripts' / 'build-pipelines-from-triage.py'


def _is_triage_dispatch(stdin_data: dict, steps: list) -> bool:
    """True iff the returned Agent call is the PM TRIAGE step's dispatch."""
    triage = contract_runtime.triage_call(steps)
    ti = stdin_data.get('tool_input') if isinstance(stdin_data, dict) else None
    if not triage or not isinstance(ti, dict):
        return False
    role = ti.get('subagent_type')
    return (isinstance(role, str) and role.strip().lower() == triage.get('subagent_type')
            and contract_runtime.detect_mode(ti.get('prompt', ''), role) == triage.get('mode'))


def _triage_report(state: dict, cycle_id: int, prompt: str) -> Path:
    """This cycle's triage report: triage-report-cycle<cycle_id>.json in the
    session's directory. A PM TRIAGE dispatch that embeds no obligation is
    origin/master's Step 4, held by a session started before the pull: that prose
    numbers the cycle by the record's cycle_count, which no hook advances any
    more, so from its second cycle on its report is the one its own "Write triage
    report to:" line names, else the last one its prompt names (P1c)."""
    base = overnight.session_dir(state)
    triage = base / f'triage-report-cycle{cycle_id}.json'
    if triage.is_file() or not isinstance(obligation.extract_obligation_block(prompt), obligation.NoBlock):
        return triage
    named = re.search(r'^\s*Write triage report to:.*?\b(triage-report-cycle\d+\.json)', prompt, re.M)
    anywhere = re.findall(r'triage-report-cycle\d+\.json', prompt)
    return base / (named.group(1) if named else anywhere[-1]) if (named or anywhere) else triage


def _pipeline_count(state: dict, cycle_id: int, prompt: str = '') -> int | None:
    """How many pipelines this cycle's triage report creates, counted by the
    Step-6 builder itself so the count and the pipelines cannot disagree."""
    triage = _triage_report(state, cycle_id, prompt if isinstance(prompt, str) else '')
    if not triage.is_file():
        return None
    try:
        result = subprocess.run(
            [sys.executable, str(_BUILD_PIPELINES), str(triage), '/dev/stdin',
             f'cycle{cycle_id}', str(state.get('session_id'))],
            input=json.dumps(state.get('addressed_issues') or []),
            capture_output=True, text=True, timeout=30,
        )
        pipelines = json.loads(result.stdout) if result.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return len(pipelines) if isinstance(pipelines, list) else None


def _write_cycle_contract(stdin_data: dict, session_id: str) -> None:
    """Render the cycle contract when PM TRIAGE returns; otherwise do nothing."""
    state = contract_runtime.session_record(session_id, stdin_data)
    if state is None:
        return
    steps = contract_runtime.overnight_steps()
    if not _is_triage_dispatch(stdin_data, steps):
        return
    cycle_id = overnight.cycle_index(state)
    path = contract_runtime.contract_path(state, cycle_id)
    if contract_runtime._iter_required_calls(contract_runtime.load_contract(session_id, cycle_id, state)):
        print(f'CYCLE CONTRACT KEPT: cycle {cycle_id} already has one: {path}')
        return
    count = _pipeline_count(state, cycle_id, str((stdin_data.get('tool_input') or {}).get('prompt') or ''))
    if count is None:
        sys.stderr.write(
            f'CYCLE CONTRACT NOT WRITTEN: cycle {cycle_id} has no readable triage '
            'report; the next PM TRIAGE dispatch writes it.\n')
        return
    calls = []
    for label, call in contract_runtime.post_triage_steps(steps):
        copies = 1 if call.get('mode') else count
        calls += [contract_runtime.call_entry(label, call) for _ in range(copies)]
    contract = {
        'schema_version': 1,
        'session_id': session_id,
        'cycle_id': cycle_id,
        'created_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'required_calls': calls,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
        tmp.write_text(json.dumps(contract, indent=2) + '\n', encoding='utf-8')
        os.replace(tmp, path)
    except OSError as exc:
        sys.stderr.write(f'CYCLE CONTRACT NOT WRITTEN: {path}: {exc}\n')
        return
    print(f'CYCLE CONTRACT: cycle {cycle_id}, {count} pipeline(s), '
          f'{len(calls)} required call(s): {path}')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _main() -> None:
    stdin_data, session_id = _parse_stdin()
    _write_cycle_contract(stdin_data, session_id)
    sys.exit(0)


if __name__ == '__main__':
    _main()
