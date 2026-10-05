#!/usr/bin/env python3
"""
PostToolUse:Agent Hook — Contract-driven overnight file check.

T3.2: validates ONLY the just-completed Agent's matched required_calls
entry (the entry that pretool-subagent-enforce bookmarked at dispatch
time), not all entries for that role. This prevents false-fail when a
multi-pipeline cycle has not yet produced sibling pipelines' artifacts.

The matched_entry is read from
``/tmp/contract-bookmark-<sid>-<cycle>.json`` (written by
pretool-subagent-enforce per T2.3). When the bookmark is unusable, the
hook falls back to entries explicitly matching the just-completed
agent's role + pipeline_id + mode (sniffed from tool_input). Sibling
pipelines are NEVER validated on behalf of the just-completed agent.

Per-call sidecar (T3.2): writes
``/tmp/artifact-status-<sid>-<cycle>.json`` recording the schema_status
of the validated artifact so posttool-subagent-track.py (T2.3 path A)
can consult it before marking the step done. The sidecar is the source
of truth for closeout's pending-required-calls progression.

Variable specialist count (AC12): zero specialists is valid; the hook
honors whatever required_calls the orchestrator wrote. There is no
codename allowlist.

Timezone safety (preserved from T1.1): the live-session check uses
``datetime.now(timezone.utc)`` against an aware end_time produced by
``_parse_end_time_aware`` (auto-promotes naive strings to UTC). Removing
this would re-introduce the TypeError observed on Python 3.11+ when a
naive ``datetime.now()`` was compared to ``fromisoformat('...Z')``.

HARD CUTOVER: when ``cycle-contract.json`` is absent, exit 0 silently.

Exit codes:
  0 — Contract absent, session not live, agent type out of scope, no
      matched entry to validate, or matched entry's artifact valid.
  2 — Matched entry's artifact missing or schema-invalid (hard gate).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib import contract_runtime  # noqa: E402
from lib.harness_state_dir import harness_state_dir  # noqa: E402

OVERNIGHT_AGENTS = {
    'pm', 'user', 'product-owner', 'architect',
    'ui-specialist', 'ba', 'dev', 'qa',
}


def _try_load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return None


def _load_overnight_state(session_id: str) -> tuple[dict | None, Path | None]:
    project_dir = Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))
    claude_dir = project_dir / '.claude'
    if session_id:
        exact = claude_dir / f'overnight-state-{session_id}.json'
        state = _try_load_json(exact)
        if state:
            return state, exact
    for p in sorted(claude_dir.glob('overnight-state-*.json')):
        state = _try_load_json(p)
        if state:
            return state, p
    return None, None


def _parse_end_time_aware(et_str: str) -> datetime | None:
    """Parse ISO end_time string into a UTC-aware datetime.

    Naive strings (no offset, no Z) are auto-promoted to UTC so callers
    can always compare against ``datetime.now(timezone.utc)`` safely.
    Returns None on parse failure. Preserved verbatim from T1.1's fix.
    """
    try:
        et = datetime.fromisoformat(et_str.replace('Z', '+00:00'))
    except (ValueError, TypeError, AttributeError):
        return None
    if et.tzinfo is None:
        et = et.replace(tzinfo=timezone.utc)
    return et


def _is_live(state: dict) -> bool:
    if state.get('current_phase') in ('complete', 'completed'):
        return False
    et_str = state.get('end_time', '')
    if not et_str:
        return True
    et = _parse_end_time_aware(et_str)
    if et is None:
        return True
    return datetime.now(timezone.utc) <= et


def _cycle_id_from_state(state: dict) -> int:
    val = state.get('cycle_id') or state.get('cycle_count')
    try:
        return int(val) if val else 1
    except (TypeError, ValueError):
        return 1


def _resolve_artifact_path(relpath: str) -> Path:
    project_dir = Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))
    return Path(relpath) if relpath.startswith('/') else project_dir / relpath


def _expected_paths(entry: dict) -> list[str]:
    eop = entry.get('expected_output_path')
    if isinstance(eop, str):
        return [eop]
    if isinstance(eop, list):
        return [p for p in eop if isinstance(p, str)]
    return []


_SEVERITY = {'pass': 0, 'unchecked': 1, 'fail': 2, 'invalid_json': 3, 'missing': 4}


def _validate_one_artifact(candidate: Path, schema_name: str) -> tuple[str, list[str]]:
    """Return (status, errors). status ∈ {missing, invalid_json, fail, pass, unchecked}."""
    if not candidate.exists():
        return 'missing', [f'artifact missing: {candidate}']
    record = _try_load_json(candidate)
    if record is None:
        return 'invalid_json', [f'{candidate}: invalid JSON']
    if not schema_name:
        return 'unchecked', []
    result = contract_runtime.validate_artifact(record, schema_name)
    if not result.get('ok'):
        return 'fail', [f'{candidate}: {e}' for e in result.get('errors', [])]
    return 'pass', []


# ---------------------------------------------------------------------------
# Bookmark + matched-entry lookup (T3.2)
# ---------------------------------------------------------------------------


def _contract_bookmark_path(session_id: str, cycle_id: int) -> Path:
    """Where pretool-subagent-enforce (T2.3) writes step -> matched_entry."""
    return Path(f'{harness_state_dir()}/contract-bookmark-{session_id}-{cycle_id}.json')


def _artifact_status_sidecar_path(session_id: str, cycle_id: int) -> Path:
    """Where this hook writes per-call schema_status for downstream consumers."""
    return Path(f'{harness_state_dir()}/artifact-status-{session_id}-{cycle_id}.json')


def _ts_float(payload: dict) -> float:
    try:
        return float(payload.get('ts') or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _bookmark_candidates(bm: dict) -> list[tuple]:
    """Extract (ts, step, matched_entry) tuples from the bookmark file."""
    out: list[tuple] = []
    for step, payload in bm.items():
        if not isinstance(payload, dict):
            continue
        matched = payload.get('matched_entry')
        if isinstance(matched, dict):
            out.append((_ts_float(payload), step, matched))
    return out


def _load_matched_entry(session_id: str, cycle_id: int) -> dict | None:
    """Return the most-recently-bookmarked matched_entry, or None."""
    bm = _try_load_json(_contract_bookmark_path(session_id, cycle_id))
    if not isinstance(bm, dict) or not bm:
        return None
    candidates = _bookmark_candidates(bm)
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0], reverse=True)
    return candidates[0][2]


def _entry_role_match(entry: dict, agent_type: str) -> bool:
    return isinstance(entry, dict) and entry.get('role') == agent_type


def _entry_dim_compat(entry: dict, key: str, value: str | None) -> bool:
    """True iff entry[key] is unset OR matches value (or value is None/empty)."""
    declared = entry.get(key)
    if not declared or not value:
        return True
    return declared == value


def _entries_matching_dispatch(
    contract: dict, agent_type: str, pipeline_id: str | None, mode: str | None
) -> list[dict]:
    """Fallback: entries explicitly matching this agent's dispatch dims."""
    out: list[dict] = []
    for entry in contract.get('required_calls', []) or []:
        if not _entry_role_match(entry, agent_type):
            continue
        if not _entry_dim_compat(entry, 'pipeline_id', pipeline_id):
            continue
        if not _entry_dim_compat(entry, 'mode', mode):
            continue
        out.append(entry)
    return out


def _scan_prompt_for_mode(prompt: str) -> str | None:
    for tag in ('DESIGN_MODE', 'AUDIT_MODE', 'UI_MODE', 'PLAN', 'TRIAGE', 'RETRO'):
        if tag in prompt:
            return tag
    return None


def _agent_dispatch_dims(data: dict) -> tuple[str | None, str | None]:
    """Sniff pipeline_id + mode from the just-completed agent's tool_input."""
    ti = data.get('tool_input', {}) or {}
    if not isinstance(ti, dict):
        return None, None
    pipeline_id = None
    for key in ('pipeline_id', 'pipelineId'):
        v = ti.get(key)
        if isinstance(v, str) and v:
            pipeline_id = v
            break
    prompt = ti.get('prompt') or ti.get('description') or ''
    mode = _scan_prompt_for_mode(prompt) if isinstance(prompt, str) else None
    return pipeline_id, mode


def _entry_specificity(entry: dict) -> int:
    return sum(1 for k in ('pipeline_id', 'mode', 'step') if entry.get(k))


def _select_entry_to_validate(
    contract: dict, agent_type: str,
    session_id: str, cycle_id: int, data: dict,
) -> dict | None:
    """Pick the single entry whose artifact represents the just-completed agent."""
    matched = _load_matched_entry(session_id, cycle_id)
    if isinstance(matched, dict) and matched.get('role') == agent_type:
        return matched
    pipeline_id, mode = _agent_dispatch_dims(data)
    fallback = _entries_matching_dispatch(contract, agent_type, pipeline_id, mode)
    if not fallback:
        return None
    if len(fallback) == 1:
        return fallback[0]
    fallback.sort(key=_entry_specificity, reverse=True)
    return fallback[0]


def _merge_path_validation(
    candidate: Path, schema_name: str,
    worst: str, all_errors: list[str], present: bool,
) -> tuple[str, bool]:
    """Validate a single path and merge into worst-status accumulator."""
    if candidate.exists():
        present = True
    status, errors = _validate_one_artifact(candidate, schema_name)
    all_errors.extend(errors)
    if _SEVERITY.get(status, 0) > _SEVERITY.get(worst, 0):
        worst = status
    return worst, present


def _validate_entry(entry: dict) -> tuple[str, list[str], bool]:
    """Validate a single contract entry. Returns (worst_status, errors, present)."""
    schema_name = entry.get('schema_name') or entry.get('expected_schema') or ''
    paths = _expected_paths(entry)
    if not paths:
        return 'unchecked', [], False
    worst = 'pass'
    all_errors: list[str] = []
    present = False
    for relpath in paths:
        candidate = _resolve_artifact_path(relpath)
        worst, present = _merge_path_validation(
            candidate, schema_name, worst, all_errors, present,
        )
    return worst, all_errors, present


def _build_sidecar_payload(
    entry: dict | None, status: str, errors: list[str], artifact_present: bool,
) -> dict:
    e = entry or {}
    return {
        'schema_status': status,
        'errors': errors,
        'artifact_present': artifact_present,
        'matched_entry_step': e.get('step'),
        'matched_entry_role': e.get('role'),
        'matched_entry_pipeline_id': e.get('pipeline_id'),
        'matched_entry_mode': e.get('mode'),
        'expected_output_paths': _expected_paths(e),
        'ts': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    }


def _write_sidecar(
    session_id: str, cycle_id: int, entry: dict | None,
    status: str, errors: list[str], artifact_present: bool,
) -> None:
    """Per-call artifact-status sidecar consumed by posttool-subagent-track."""
    try:
        path = _artifact_status_sidecar_path(session_id, cycle_id)
        payload = _build_sidecar_payload(entry, status, errors, artifact_present)
        path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    except OSError:
        pass


def _emit_block(agent_type: str, state: dict, errors: list[str]) -> None:
    sid = state.get('session_id', '?')
    cycle = state.get('cycle_count', state.get('cycle_id', 0))
    sys.stderr.write(
        '\nOVERNIGHT FILE CHECK BLOCK (contract):\n'
        f'  agent={agent_type} session={sid} cycle={cycle}\n'
        '  errors:\n'
    )
    for item in errors:
        sys.stderr.write(f'    - {item}\n')
    sys.stderr.write('  Required artifact missing or schema-invalid. '
                     'Re-run the subagent or escalate.\n\n')


def _run_check(data: dict) -> int:
    agent_type = data.get('tool_input', {}).get('subagent_type', '')
    if agent_type not in OVERNIGHT_AGENTS:
        return 0
    session_id = data.get('session_id', '')
    state, _ = _load_overnight_state(session_id)
    if state is None or not _is_live(state):
        return 0
    cycle_id = _cycle_id_from_state(state)
    contract_sid = state.get('session_id', session_id)
    contract = contract_runtime.load_contract(contract_sid, cycle_id)
    if contract is None:
        # Hard cutover: legacy session without a contract — silent passthrough.
        return 0
    entry = _select_entry_to_validate(
        contract, agent_type, contract_sid, cycle_id, data,
    )
    if entry is None:
        # AC12: zero-specialist / not-required — valid; do not warn.
        return 0
    status, errors, present = _validate_entry(entry)
    _write_sidecar(contract_sid, cycle_id, entry, status, errors, present)
    if status in ('missing', 'invalid_json', 'fail'):
        _emit_block(agent_type, state, errors)
        return 2
    print(f'OVERNIGHT FILE CHECK: {agent_type} contract artifact valid '
          f'(step={entry.get("step")}, status={status}).')
    return 0


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    sys.exit(_run_check(data))


if __name__ == '__main__':
    main()
