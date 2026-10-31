#!/usr/bin/env python3
"""
Description: Validates that every report a /dev-overnight cycle's dispatches
             declared in the session's report directory exists and conforms to
             the schema its dispatch's obligation names. The reports and their
             schemas are read from the session's own dispatch records (the
             obligation each Agent call carried), so no report or specialist
             name is listed here.

Usage: check-overnight-reports.py --session-id <sid> [--cycle <N>]
Exit codes: 0 = all declared reports present and valid; 1 = any missing or invalid
Output: per-report status lines + summary (N expected, N present, N valid, N missing, N invalid)
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
from pathlib import Path

# Make hooks/lib importable.
_hooks_dir = os.environ.get('CLAUDE_HOOKS_DIR', os.path.join(os.path.dirname(__file__), '..', 'hooks'))
sys.path.insert(0, str(Path(_hooks_dir).resolve()))
from lib import contract_runtime  # noqa: E402
from lib import obligation  # noqa: E402
from lib import overnight  # noqa: E402
from lib.subagent_restart import account_project_roots  # noqa: E402


def _session_dispatches(session_id: str) -> list[dict]:
    """The session's dispatch records, in transcript order: its transcript is the
    CLI's store entry named by the session id, in every account root."""
    seen: set[str] = set()
    records: list[dict] = []
    for root in account_project_roots():
        for transcript in sorted(Path(root).glob(f'*/{glob.escape(session_id)}.jsonl')):
            if not transcript.is_file():
                continue
            for record in obligation.dispatch_obligations(transcript):
                key = str(record.get('tool_use_id'))
                if key not in seen:  # the same session's copy in another account root
                    seen.add(key)
                    records.append(record)
    return records


def _closes_cycle(record: dict, closing: list[dict]) -> bool:
    """A cycle ends with its PM retrospective: the dispatch of the canonical step
    after PM TRIAGE whose call carries a mode (scripts/todo/dev-overnight.py)."""
    mode = contract_runtime.detect_mode(record.get('prompt') or '')
    return any(record.get('subagent_type') == call.get('subagent_type') and mode == call.get('mode')
               for call in closing)


def _by_cycle(records: list[dict]) -> list[tuple[int, dict]]:
    """Each record with the cycle it ran in."""
    steps = contract_runtime.overnight_steps()
    closing = [call for _label, call in contract_runtime.post_triage_steps(steps) if call.get('mode')]
    out: list[tuple[int, dict]] = []
    cycle = 1
    for record in records:
        out.append((cycle, record))
        if _closes_cycle(record, closing):
            cycle += 1
    return out


def _resolve_cycle(cycles: list[tuple[int, dict]], requested: int | None) -> int | None:
    """Return the cycle id to validate. Falls back to the cycle of the latest dispatch."""
    if requested is not None:
        return requested
    return cycles[-1][0] if cycles else None


def _expected_reports(cycles: list[tuple[int, dict]], cycle_id: int, report_dir: str) -> list[tuple[dict, dict]]:
    """(obligation, artifact) per json report the cycle's dispatches declared under
    report_dir, the latest dispatch's declaration for each path."""
    latest: dict[str, tuple[dict, dict]] = {}
    for cycle, record in cycles:
        if cycle != cycle_id:
            continue
        ob = record['obligation']
        for art in ob.get('artifacts') or []:
            path = art.get('path') if isinstance(art, dict) else None
            if art.get('kind') == 'json' and isinstance(path, str) and path.startswith(report_dir + '/'):
                latest[path] = (ob, art)
    return list(latest.values())


def _check_one_path(path: Path, schema_name: str | None) -> tuple[str, list[str]]:
    if not path.exists():
        return 'missing', [f'file not found: {path}']
    if not schema_name:
        return 'present_valid', []
    result = contract_runtime.validate_artifact_for_obligation(path, schema_name)
    if result.get('status') == 'fail':
        return 'present_invalid', [f'{path}: {e}' for e in (result.get('errors') or [result.get('reason')])]
    return 'present_valid', []


def _check_entry(ob: dict, art: dict, root: Path) -> tuple[str, str, list[str]]:
    """Return (status, label, errors). status in {present_valid, present_invalid, missing}."""
    label = f"role={ob.get('role')} task_id={ob.get('task_id')} path={art['path']}"
    status, errs = _check_one_path(root / art['path'], art.get('schema'))
    return status, label, errs


def _summarize(rows: list[tuple[str, str, list[str]]]) -> tuple[int, int, int, int, int]:
    expected = len(rows)
    present = sum(1 for r in rows if r[0] != 'missing')
    valid = sum(1 for r in rows if r[0] == 'present_valid')
    missing = sum(1 for r in rows if r[0] == 'missing')
    invalid = sum(1 for r in rows if r[0] == 'present_invalid')
    return expected, present, valid, missing, invalid


def _print_rows(rows: list[tuple[str, str, list[str]]]) -> None:
    for status, label, errs in rows:
        if status == 'present_valid':
            print(f'OK    {label}')
            continue
        prefix = 'INVALID' if status == 'present_invalid' else 'MISSING'
        print(f'{prefix} {label}')
        for e in errs:
            print(f'        - {e}')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session-id', required=True)
    parser.add_argument('--cycle', type=int, default=None,
                        help='Cycle id to validate; defaults to the cycle of the latest dispatch.')
    args = parser.parse_args()

    cycles = _by_cycle(_session_dispatches(args.session_id))
    cycle_id = _resolve_cycle(cycles, args.cycle)
    if cycle_id is None:
        print(f'ERROR: no dispatch records found for session {args.session_id}', file=sys.stderr)
        return 1

    # The session's directory under the project the reports are written in (the working root
    # the orchestrator runs this from), as lib.overnight lays it out.
    project_dir = Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))
    session_dir = overnight.session_dir({'session_id': args.session_id, 'worktree_path': str(project_dir)})
    report_dir = session_dir.relative_to(project_dir).as_posix()
    rows = [_check_entry(ob, art, project_dir)
            for ob, art in _expected_reports(cycles, cycle_id, report_dir)]
    _print_rows(rows)
    expected, present, valid, missing, invalid = _summarize(rows)
    print(f'SUMMARY: expected={expected} present={present} valid={valid} '
          f'missing={missing} invalid={invalid}')
    return 0 if (missing == 0 and invalid == 0) else 1


if __name__ == '__main__':
    sys.exit(main())
