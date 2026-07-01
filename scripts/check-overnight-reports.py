#!/usr/bin/env python3
"""
Description: Validates all overnight required outputs declared by the active
             cycle-contract.json exist and conform to their declared schema.
             Replaces the legacy check-overnight-reports.sh which hardcoded
             4 specialist filenames (product-owner, architect, user, ui-specialist).

Usage: check-overnight-reports.py --session-id <sid> [--cycle <N>]
Exit codes: 0 = all required outputs present and valid; 1 = any missing or invalid
Output: per-entry status lines + summary (N expected, N present, N valid, N missing, N invalid)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Make hooks/lib importable.
_hooks_dir = os.environ.get('CLAUDE_HOOKS_DIR', os.path.join(os.path.dirname(__file__), '..', 'hooks'))
sys.path.insert(0, str(Path(_hooks_dir).resolve()))
from lib import contract_runtime  # noqa: E402


def _list_cycle_dirs(base: Path) -> list[int]:
    """Return integer cycle ids found inside a session base directory."""
    if not base.is_dir():
        return []
    out: list[int] = []
    for child in base.iterdir():
        name = child.name
        if name.startswith('cycle-') and name[6:].isdigit():
            out.append(int(name[6:]))
    return out


def _resolve_cycle(session_id: str, requested: int | None) -> int | None:
    """Return the cycle id to validate. Falls back to highest cycle dir present."""
    if requested is not None:
        return requested
    project_dir = Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))
    candidates = [
        project_dir / 'docs' / 'dev' / 'overnight' / session_id,
    ]
    for base in candidates:
        cycles = _list_cycle_dirs(base)
        if cycles:
            return max(cycles)
    return None


def _expected_paths(entry: dict) -> list[str]:
    """Normalize entry.expected_output_path into a list of strings."""
    eop = entry.get('expected_output_path')
    if isinstance(eop, str):
        return [eop]
    if isinstance(eop, list):
        return [p for p in eop if isinstance(p, str)]
    return []


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None


def _resolve_path(relpath: str, project_dir: Path) -> Path:
    return Path(relpath) if relpath.startswith('/') else project_dir / relpath


def _check_one_path(path: Path, schema_name: str) -> tuple[str, list[str]]:
    if not path.exists():
        return 'missing', [f'file not found: {path}']
    record = _read_json(path)
    if record is None:
        return 'present_invalid', [f'invalid JSON: {path}']
    if not schema_name:
        return 'present_valid', []
    result = contract_runtime.validate(record, schema_name)
    if not result['ok']:
        return 'present_invalid', [f'{path}: {e}' for e in result['errors']]
    return 'present_valid', []


def _check_entry(entry: dict, project_dir: Path) -> tuple[str, str, list[str]]:
    """Return (status, label, errors). status in {present_valid, present_invalid, missing}."""
    label = f"step={entry.get('step')} role={entry.get('role')} pipeline={entry.get('pipeline_id')}"
    paths = _expected_paths(entry)
    if not paths:
        return 'missing', label, ['expected_output_path empty']
    schema_name = entry.get('schema_name') or ''
    for relpath in paths:
        candidate = _resolve_path(relpath, project_dir)
        status, errs = _check_one_path(candidate, schema_name)
        if status != 'present_valid':
            return status, label, errs
    return 'present_valid', label, []


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
                        help='Cycle id to validate; defaults to latest cycle dir.')
    args = parser.parse_args()

    cycle_id = _resolve_cycle(args.session_id, args.cycle)
    if cycle_id is None:
        print(f'ERROR: cannot resolve cycle for session {args.session_id}', file=sys.stderr)
        return 1

    contract = contract_runtime.load_contract(args.session_id, cycle_id)
    if contract is None:
        print(f'ERROR: cycle-contract.json not found for {args.session_id} cycle-{cycle_id}',
              file=sys.stderr)
        return 1

    project_dir = Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))
    rows = [_check_entry(e, project_dir) for e in contract.get('required_calls', [])]
    _print_rows(rows)
    expected, present, valid, missing, invalid = _summarize(rows)
    print(f'SUMMARY: expected={expected} present={present} valid={valid} '
          f'missing={missing} invalid={invalid}')
    return 0 if (missing == 0 and invalid == 0) else 1


if __name__ == '__main__':
    sys.exit(main())
