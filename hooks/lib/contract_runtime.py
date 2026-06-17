"""Contract runtime for the cycle-contract.json driven hook chain.

This module is the single shared engine consumed by every contract-aware
hook (pretool-subagent-enforce, posttool-subagent-track,
posttool-overnight-file-check) plus check-overnight-reports.py and
lib/closeout.py.

Public surface:
    load_contract(session_id, cycle_id) -> dict | None
    validate(record, schema_name) -> Result
    validate_required_call(contract, role, pipeline_id, mode, step) -> Result
    iter_matching_required_calls(contract, step, role, pipeline_id, mode)
        -> Iterator[dict]   # T2.3: multi-dimension contract matching
    validate_artifact(record, schema_name) -> Result   # T2.3: alias of validate
    lookup_required_call(contract, step) -> dict | None  # legacy (T2.3 kept for back-compat)

A Result is a plain dict ``{ok, errors, severity}``. Severity is one of
``'pass'``, ``'warn'``, ``'fail'``. Hooks should treat ``severity == 'fail'``
as exit-2 worthy; ``'warn'`` is informational; ``'pass'`` means clean.

HARD CUTOVER convention: when no cycle-contract.json exists for the given
session/cycle, ``load_contract`` returns ``None`` so callers can short-circuit
with ``sys.exit(0)`` (legacy /spec, /dev single-cycle sessions are unaffected).

Custom keyword ``required_when_ui``: if the validated record has
``ui_pipeline == True``, every key listed in
``schema['properties']['evidence_summary']['required_when_ui']`` must be
present inside the record's ``evidence_summary`` block. This rule is
applied as a pre-pass before invoking the standard jsonschema Draft7
validator.

T3.1 (BUG-A-UI-REQUIRED-WHEN-UI-NESTING): the canonical qa-report.v1
schema now declares ``required_when_ui = ["ui_evidence"]`` so this
pre-pass requires ``evidence_summary.ui_evidence`` to be present as
an object; the nested 6-key required list inside ``ui_evidence`` is
then enforced by Draft7Validator (target_route, target_element,
viewports {desktop, mobile}, evidence_map, trace, captured_at, plus
nested dom_measurement on each viewport entry). Backward-compat: if
a project schema still lists multiple required_when_ui keys, the
per-key presence check still applies (each listed key must exist as
a direct evidence_summary property).
"""

from __future__ import annotations

import json
import os
import fcntl
from pathlib import Path
from typing import Optional

try:  # jsonschema 4.25.1 is installed system-wide; degrade gracefully if not.
    from jsonschema import Draft7Validator
except ImportError:  # pragma: no cover - architect confirmed availability
    Draft7Validator = None  # type: ignore[assignment]

# Importable from sibling lib module (already on the same hooks/lib/ path).
try:
    from . import schema_registry
    from . import claude_home
except ImportError:  # pragma: no cover - direct spec import in focused tests
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from lib import schema_registry  # type: ignore
    import claude_home  # type: ignore


def _result(ok: bool, errors: list, severity: str) -> dict:
    return {'ok': ok, 'errors': list(errors), 'severity': severity}


# ---------------------------------------------------------------------------
# Contract loading
# ---------------------------------------------------------------------------


def _candidate_contract_paths(session_id: str, cycle_id: int) -> list[Path]:
    """Return ordered candidate paths for the cycle contract.

    WS1: the third (home-level docs) candidate is derived from the resolved
    harness home's PARENT (``<home>/../docs/dev/overnight``) — matching the
    author's ``/root/docs`` sibling-of-``/root/.claude`` layout portably —
    rather than the hardcoded author literal ``/root/docs``.
    """
    project_dir = Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))
    cycle_dirname = f'cycle-{cycle_id}'
    candidates = [
        project_dir / 'docs' / 'dev' / 'overnight' / session_id / cycle_dirname / 'cycle-contract.json',
        project_dir / '.claude' / f'overnight-contract-{session_id}-cycle{cycle_id}.json',
    ]
    home = claude_home.resolve()
    if home is not None:
        candidates.append(
            home.parent / 'docs' / 'dev' / 'overnight' / session_id / cycle_dirname / 'cycle-contract.json'
        )
    return candidates


def _try_read_contract(path: Path) -> Optional[dict]:
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None


def load_contract_path(session_id: str, cycle_id: int) -> Optional[Path]:
    """Return the active cycle-contract path for ``session_id``/``cycle_id``."""
    for path in _candidate_contract_paths(session_id, cycle_id):
        if path.exists():
            return path
    return None


def load_contract(session_id: str, cycle_id: int) -> Optional[dict]:
    """Return the parsed cycle contract for ``session_id``/``cycle_id``."""
    if not session_id or cycle_id is None:
        return None
    for path in _candidate_contract_paths(session_id, cycle_id):
        data = _try_read_contract(path)
        if data is not None:
            return data
    return None


# ---------------------------------------------------------------------------
# Schema validation (with required_when_ui pre-pass)
# ---------------------------------------------------------------------------


def _required_when_ui_keys(schema: dict) -> list[str]:
    """Return the ``required_when_ui`` key list declared on the schema, if any."""
    if not isinstance(schema, dict):
        return []
    es = schema.get('properties', {}).get('evidence_summary', {})
    if not isinstance(es, dict):
        return []
    keys = es.get('required_when_ui')
    return list(keys) if isinstance(keys, list) else []


def _check_required_when_ui(record: dict, required_keys: list[str]) -> list[str]:
    """Pre-pass for the custom ``required_when_ui`` keyword."""
    if not isinstance(record, dict) or not record.get('ui_pipeline') or not required_keys:
        return []
    es = record.get('evidence_summary', {})
    if not isinstance(es, dict):
        return [f"required_when_ui: evidence_summary missing (need keys: {sorted(required_keys)})"]
    return [
        f"required_when_ui: evidence_summary.{k} is required when ui_pipeline=true"
        for k in required_keys if k not in es
    ]


_EVIDENCE_LEVELS = {
    'rendered_cached',
    'fresh_scan_triggered',
    'fresh_scan_completed',
    'extraction_verified',
}


def _iter_focus_results(record: dict) -> list[dict]:
    focus = record.get('focus_criteria_results')
    if not isinstance(focus, dict):
        return []
    results = focus.get('results')
    return [item for item in results if isinstance(item, dict)] if isinstance(results, list) else []


def _criterion_requires_extraction_verified(item: dict) -> bool:
    text = str(item.get('criterion', '')).lower().replace('_', ' ')
    return 'fresh extraction' in text or 'extraction verified' in text or 'extraction verification' in text


def _check_evidence_taxonomy(record: dict) -> list[str]:
    """Enforce fresh-extraction evidence levels for focus criteria results."""
    errors: list[str] = []
    for idx, item in enumerate(_iter_focus_results(record)):
        level = item.get('evidence_level')
        if level not in _EVIDENCE_LEVELS:
            errors.append(
                f"focus_criteria_results.results[{idx}].evidence_level must be one of {sorted(_EVIDENCE_LEVELS)}"
            )
            continue
        required = item.get('required_evidence_level')
        if required and required not in _EVIDENCE_LEVELS:
            errors.append(
                f"focus_criteria_results.results[{idx}].required_evidence_level is not recognized: {required}"
            )
            continue
        if not required and _criterion_requires_extraction_verified(item):
            required = 'extraction_verified'
        if required == 'extraction_verified' and level != 'extraction_verified':
            errors.append(
                f"focus_criteria_results.results[{idx}].evidence_level={level} cannot satisfy extraction_verified"
            )
    return errors


def _run_jsonschema(record: dict, schema: dict) -> list[str]:
    """Run Draft7Validator and collect formatted errors."""
    errors: list[str] = []
    try:
        validator = Draft7Validator(schema)
        for err in validator.iter_errors(record):
            path = '.'.join(str(p) for p in err.absolute_path) or '<root>'
            errors.append(f'{path}: {err.message}')
    except Exception as exc:
        errors.append(f'validator raised: {exc}')
    return errors


def validate(record: dict, schema_name: str) -> dict:
    """Validate ``record`` against the schema registered as ``schema_name``."""
    try:
        schema = schema_registry.get_schema(schema_name)
    except Exception as exc:  # pragma: no cover - defensive
        return _result(False, [f'schema_registry error: {exc}'], 'fail')

    if schema is None:
        return _result(False, [f"schema '{schema_name}' not registered"], 'fail')

    errors = _check_required_when_ui(record, _required_when_ui_keys(schema))
    errors.extend(_check_evidence_taxonomy(record))

    if Draft7Validator is None:
        if errors:
            return _result(False, errors, 'fail')
        return _result(True, ['jsonschema unavailable; only pre-pass ran'], 'warn')

    errors.extend(_run_jsonschema(record, schema))
    if errors:
        return _result(False, errors, 'fail')
    return _result(True, [], 'pass')


# ---------------------------------------------------------------------------
# required_calls lookup + match validation
# ---------------------------------------------------------------------------


def _iter_required_calls(contract: dict) -> list[dict]:
    """Return contract['required_calls'] as a list (defensive copy)."""
    if not isinstance(contract, dict):
        return []
    rc = contract.get('required_calls')
    return rc if isinstance(rc, list) else []


def lookup_required_call(contract: dict, step: str) -> Optional[dict]:
    """Find first required_calls entry whose ``step`` matches (legacy)."""
    if not step:
        return None
    return next(
        (e for e in _iter_required_calls(contract)
         if isinstance(e, dict) and e.get('step') == step),
        None,
    )


def _entry_matches_dim(entry: dict, key: str, value: Optional[str]) -> bool:
    """T2.3: True iff entry[key] matches value with wildcard rules."""
    if not value:
        return True
    declared = entry.get(key)
    if not declared:
        return True
    return declared == value


def _entry_matches_all(entry: dict, step: str, role, pipeline_id, mode) -> bool:
    """T2.3: True iff entry matches step + role + pipeline_id + mode."""
    if not isinstance(entry, dict) or entry.get('step') != step:
        return False
    return (_entry_matches_dim(entry, 'role', role)
            and _entry_matches_dim(entry, 'pipeline_id', pipeline_id)
            and _entry_matches_dim(entry, 'mode', mode))


def iter_matching_required_calls(
    contract: dict,
    step: str,
    role: Optional[str] = None,
    pipeline_id: Optional[str] = None,
    mode: Optional[str] = None,
):
    """T2.3: yield required_calls entries matching ALL supplied dimensions.

    Matching rule (BUG-A-CONTRACT-CALL-MATCHING-TOO-WEAK fix):
        - ``step`` is mandatory; entries with a different ``step`` skipped.
        - For each of role/pipeline_id/mode: matches if entry's declared
          value equals the supplied value, OR entry omits that field
          (legacy/wildcard compat), OR caller supplied None/empty.
    """
    if not step:
        return
    for entry in _iter_required_calls(contract):
        if _entry_matches_all(entry, step, role, pipeline_id, mode):
            yield entry


def _entry_specificity(entry: dict) -> int:
    """Count declared dimensions on an entry (role/pipeline_id/mode)."""
    return sum(1 for k in ('role', 'pipeline_id', 'mode')
               if entry.get(k) not in (None, ''))


def _select_matched_entry(contract, role, pipeline_id, mode, step):
    """T2.3: best multi-dim match (most specific entry wins; ties: first)."""
    matches = list(iter_matching_required_calls(
        contract, step, role, pipeline_id, mode))
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    matches.sort(key=_entry_specificity, reverse=True)
    return matches[0]


def _check_role_pipeline(entry: dict, role: str, pipeline_id, step: str) -> list[str]:
    """Return list of role/pipeline_id mismatch error strings."""
    errors: list[str] = []
    expected_role = entry.get('role')
    if expected_role and expected_role != role:
        errors.append(
            f"role mismatch on step '{step}': expected '{expected_role}', got '{role}'"
        )
    expected_pipeline = entry.get('pipeline_id')
    if expected_pipeline is not None and expected_pipeline != pipeline_id:
        errors.append(
            f"pipeline_id mismatch on step '{step}': expected '{expected_pipeline}', "
            f"got '{pipeline_id}'"
        )
    return errors


def _attach_entry(result: dict, entry: Optional[dict]) -> dict:
    """T2.3: tag the matched entry on a Result so callers can bookmark it."""
    if entry is not None:
        result['entry'] = entry
    return result


def _no_match_result(contract, role, pipeline_id, mode, step) -> dict:
    """T2.3: build a fail Result when no multi-dim match exists."""
    legacy = lookup_required_call(contract, step)
    if legacy is None:
        return _result(False, [f"no required_calls entry for step '{step}'"], 'fail')
    errors = _check_role_pipeline(legacy, role, pipeline_id, step)
    if not errors:
        errors.append(
            f"no required_calls entry matches step='{step}' "
            f"role='{role}' pipeline_id='{pipeline_id or ''}' mode='{mode or ''}'"
        )
    return _attach_entry(_result(False, errors, 'fail'), legacy)


def _check_mode(entry: dict, mode: Optional[str], step: str) -> Optional[dict]:
    """T2.3: returns a fail Result on mode mismatch, else None."""
    expected_mode = entry.get('mode')
    if not expected_mode:
        return None
    if not mode:
        msg = (f"mode missing on step '{step}': contract requires "
               f"mode='{expected_mode}', got '<none>'")
        return _attach_entry(_result(False, [msg], 'fail'), entry)
    if expected_mode != mode:
        msg = (f"mode mismatch on step '{step}': "
               f"expected '{expected_mode}', got '{mode}'")
        return _attach_entry(_result(False, [msg], 'fail'), entry)
    return None


def validate_required_call(
    contract: dict,
    role: str,
    pipeline_id: Optional[str],
    mode: Optional[str],
    step: str,
) -> dict:
    """Verify the about-to-fire Agent matches the contract for ``step``.

    T2.3 changes:
        - Multi-dimension matching (step + role + pipeline_id + mode).
        - Mode mismatch with declared expected_mode is severity='fail'
          (was 'warn').
        - Missing mode when entry requires one is severity='fail'.
        - Matched entry is attached on the Result under ``'entry'``.
    """
    if not isinstance(contract, dict):
        return _result(False, ['contract missing or non-dict'], 'fail')

    entry = _select_matched_entry(contract, role, pipeline_id, mode, step)
    if entry is None:
        return _no_match_result(contract, role, pipeline_id, mode, step)

    errors = _check_role_pipeline(entry, role, pipeline_id, step)
    if errors:
        return _attach_entry(_result(False, errors, 'fail'), entry)

    mode_fail = _check_mode(entry, mode, step)
    if mode_fail is not None:
        return mode_fail

    return _attach_entry(_result(True, [], 'pass'), entry)


# ---------------------------------------------------------------------------
# Artifact validation (T2.3)
# ---------------------------------------------------------------------------


def validate_artifact(record: dict, schema_name: str) -> dict:
    """T2.3: validate a produced artifact against ``schema_name``.

    Thin alias of :func:`validate` — gives posttool-subagent-track and
    the file-check sidecar a clearly-named entry point matching the
    BA-specified contract surface ("validate_artifact"). Returns the
    same Result shape so the existing severity contract is preserved.
    """
    return validate(record, schema_name)


# ---------------------------------------------------------------------------
# Atomic accepted-artifact reconciliation
# ---------------------------------------------------------------------------


def _project_dir() -> Path:
    return Path(os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()))


def _lock_path(session_id: str, cycle_id: int) -> Path:
    lock_dir = _project_dir() / '.claude' / 'locks'
    lock_dir.mkdir(parents=True, exist_ok=True)
    return lock_dir / f'contract-reconcile-{session_id}-cycle{cycle_id}.lock'


def _json_text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + '\n'


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    json.loads(tmp.read_text(encoding='utf-8'))
    tmp.replace(path)


def _restore_text(path: Path, text: str | None) -> None:
    if text is None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    _atomic_write_text(path, text)


def _expected_path_value(entry: dict):
    raw = entry.get('expected_output_path')
    if isinstance(raw, list):
        return raw[0] if raw else None
    return raw if isinstance(raw, str) else None


def _expected_paths(entry: dict) -> list[str]:
    raw = entry.get('expected_output_path')
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, str)]
    return []


def _resolve_artifact_path(path_str: str) -> Path:
    path = Path(path_str)
    return path if path.is_absolute() else _project_dir() / path


def _artifact_valid_for_entry(entry: dict) -> tuple[bool, str]:
    paths = _expected_paths(entry)
    if not paths:
        return True, ''
    schema_name = entry.get('schema_name') or entry.get('expected_schema') or ''
    for raw in paths:
        path = _resolve_artifact_path(raw)
        if not path.exists():
            return False, f'expected artifact missing: {raw}'
        if not schema_name:
            continue
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return False, f'expected artifact is not valid JSON: {raw}'
        result = validate_artifact(record, schema_name)
        if not result.get('ok'):
            return False, '; '.join(str(e) for e in result.get('errors', []))
    return True, ''


def _same_required_call(left: dict, right: dict) -> bool:
    for key in ('step', 'role', 'pipeline_id', 'mode'):
        if (left.get(key) or None) != (right.get(key) or None):
            return False
    return True


def _mark_required_call(contract: dict, matched_entry: dict) -> None:
    for entry in contract.get('required_calls', []) or []:
        if isinstance(entry, dict) and _same_required_call(entry, matched_entry):
            entry['schema_status'] = 'validated'
            entry['artifact_path'] = _expected_path_value(matched_entry)
            return


def _mark_pipeline(contract: dict, matched_entry: dict) -> None:
    role = matched_entry.get('role')
    pipeline_id = matched_entry.get('pipeline_id')
    if role not in {'ba', 'dev', 'qa'} or not pipeline_id:
        return
    pipelines = contract.get('pipelines')
    if not isinstance(pipelines, dict):
        return
    pipeline = pipelines.setdefault(str(pipeline_id), {})
    pipeline[f'{role}_status'] = 'done'
    artifact_paths = pipeline.setdefault('artifact_paths', {})
    if isinstance(artifact_paths, dict):
        artifact_paths[str(role)] = _expected_path_value(matched_entry)


def _mark_workflow(workflow: dict, step_index: int) -> None:
    calls = workflow.get('subagent_calls')
    if not isinstance(calls, dict):
        calls = {}
    calls[str(step_index)] = True
    workflow['subagent_calls'] = calls
    workflow.setdefault('contract_reconciliation', []).append(
        {'step_index': step_index, 'status': 'validated'}
    )


def reconcile_accepted_artifact(
    session_id: str,
    cycle_id: int,
    workflow_path: Path,
    step_index: int,
    matched_entry: dict,
    *,
    fail_after: str | None = None,
) -> dict:
    """Atomically reconcile accepted artifact status across contract + workflow state.

    The function holds one file lock, computes every target mutation in memory,
    writes by temp-file replacement, and rolls back earlier replacements if a
    later write fails. ``fail_after`` exists only for regression tests that
    prove partial-write rollback; production callers leave it unset.
    """
    contract_path = load_contract_path(session_id, cycle_id)
    if contract_path is None:
        return {'ok': False, 'reason': 'contract missing'}
    artifact_ok, artifact_reason = _artifact_valid_for_entry(matched_entry)
    if not artifact_ok:
        return {'ok': False, 'reason': artifact_reason}
    lock_file = _lock_path(session_id, cycle_id).open('w', encoding='utf-8')
    with lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        original_contract = contract_path.read_text(encoding='utf-8')
        original_workflow = workflow_path.read_text(encoding='utf-8') if workflow_path.exists() else None
        contract = json.loads(original_contract)
        workflow = json.loads(original_workflow) if original_workflow is not None else {}
        _mark_required_call(contract, matched_entry)
        _mark_pipeline(contract, matched_entry)
        _mark_workflow(workflow, step_index)
        try:
            _atomic_write_text(contract_path, _json_text(contract))
            if fail_after == 'contract':
                raise RuntimeError('injected failure after contract write')
            _atomic_write_text(workflow_path, _json_text(workflow))
        except Exception:
            _restore_text(contract_path, original_contract)
            _restore_text(workflow_path, original_workflow)
            raise
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    return {'ok': True, 'contract_path': str(contract_path), 'workflow_path': str(workflow_path)}
