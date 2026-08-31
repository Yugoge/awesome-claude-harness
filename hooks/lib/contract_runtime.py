"""Contract runtime for the cycle-contract.json driven hook chain.

This module is the single shared engine consumed by every contract-aware
hook (pretool-subagent-enforce, posttool-subagent-track,
posttool-overnight-file-check) plus check-overnight-reports.py and
lib/closeout.py.

Public surface:
    load_contract(session_id, cycle_id) -> dict | None
    type_strict_json_equal(left, right) -> bool
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
# Schema validation (with deterministic report-projection pre-pass)
# ---------------------------------------------------------------------------


_MISSING = object()


def type_strict_json_equal(left, right) -> bool:
    """Compare JSON-shaped values without Python's scalar coercions.

    ``bool`` is a subclass of ``int`` in Python and ``1 == 1.0`` is true, so a
    plain equality check is not a faithful JSON contract comparison.  Require
    the exact node type at every level before recursively comparing objects
    and arrays.  Object key order is irrelevant; array order is significant.
    The inputs are only read and are never normalized or mutated.
    """
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return (
            left.keys() == right.keys()
            and all(type_strict_json_equal(left[key], right[key]) for key in left)
        )
    if isinstance(left, list):
        return (
            len(left) == len(right)
            and all(type_strict_json_equal(a, b) for a, b in zip(left, right))
        )
    return left == right


def _nested_value(record: dict, path: tuple[str, ...]):
    value = record
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return _MISSING
        value = value[key]
    return value


def _json_type_name(expected_type: type) -> str:
    return {
        bool: 'boolean',
        dict: 'object',
        list: 'array',
        str: 'string',
    }.get(expected_type, expected_type.__name__)


def _projection_prefix(schema_name: str) -> str:
    return f'projection {schema_name}'


def _check_projection_header(record: dict, schema_name: str) -> list[str]:
    """Check the two source-free fields shared by both v1 report contracts."""
    errors: list[str] = []
    prefix = _projection_prefix(schema_name)
    version = record.get('report_version', _MISSING)
    if type(version) is not int or version != 1:
        errors.append(
            f"{prefix}: flat field 'report_version' must be literal integer 1"
        )
    task_id = record.get('task_id', _MISSING)
    if type(task_id) is not str or not task_id:
        errors.append(
            f"{prefix}: flat field 'task_id' must be a non-empty string "
            "(top-level identity; no nested alias)"
        )
    return errors


def _check_projected_field(
    record: dict,
    schema_name: str,
    flat_field: str,
    source_path: tuple[str, ...],
    source_type: type,
    *,
    source_must_be_non_empty: bool = False,
    projected_value=_MISSING,
) -> list[str]:
    """Validate one flat alias against its canonical nested source."""
    prefix = _projection_prefix(schema_name)
    source_name = '.'.join(source_path)
    source = _nested_value(record, source_path)
    if source is _MISSING:
        return [
            f"{prefix}: canonical source '{source_name}' missing for flat field "
            f"'{flat_field}'"
        ]
    if type(source) is not source_type or (source_must_be_non_empty and not source):
        qualifier = 'non-empty ' if source_must_be_non_empty else ''
        return [
            f"{prefix}: canonical source '{source_name}' must be an exact "
            f"{qualifier}JSON {_json_type_name(source_type)} for flat field "
            f"'{flat_field}'"
        ]
    if flat_field not in record:
        return [
            f"{prefix}: flat field '{flat_field}' missing for canonical source "
            f"'{source_name}'"
        ]
    expected = source if projected_value is _MISSING else projected_value
    actual = record[flat_field]
    if not type_strict_json_equal(actual, expected):
        return [
            f"{prefix}: flat field '{flat_field}' must type-strictly equal "
            f"canonical source '{source_name}'"
        ]
    return []


def _check_dev_report_projection(record: dict) -> list[str]:
    """Validate the deterministic dev-report.v1 compatibility projection."""
    schema_name = 'dev-report.v1'
    errors = _check_projection_header(record, schema_name)

    source_status = _nested_value(record, ('dev', 'status'))
    status_map = {
        'completed': 'completed',
        'blocked': 'blocked',
        'needs_review': 'partial',
    }
    if source_status is _MISSING:
        errors.append(
            f"{_projection_prefix(schema_name)}: canonical source 'dev.status' "
            "missing for flat field 'status'"
        )
    elif type(source_status) is not str or source_status not in status_map:
        errors.append(
            f"{_projection_prefix(schema_name)}: canonical source 'dev.status' "
            f"has unsupported value {source_status!r} for flat field 'status'"
        )
    else:
        errors.extend(_check_projected_field(
            record,
            schema_name,
            'status',
            ('dev', 'status'),
            str,
            projected_value=status_map[source_status],
        ))

    for flat_field, source_path, source_type, non_empty in (
        ('files_modified', ('dev', 'files_modified'), list, False),
        ('files_created', ('dev', 'files_created'), list, False),
        (
            'root_cause_addressed',
            ('dev', 'git_rationale', 'how_fix_addresses_root'),
            str,
            True,
        ),
        ('ac_status', ('dev', 'ac_status'), dict, False),
    ):
        errors.extend(_check_projected_field(
            record,
            schema_name,
            flat_field,
            source_path,
            source_type,
            source_must_be_non_empty=non_empty,
        ))
    return errors


def _check_qa_report_projection(record: dict) -> list[str]:
    """Validate the deterministic qa-report.v1 compatibility projection."""
    schema_name = 'qa-report.v1'
    errors = _check_projection_header(record, schema_name)
    if 'status' in record:
        errors.append(
            f"{_projection_prefix(schema_name)}: top-level field 'status' is "
            "forbidden; flat field 'verdict' projects canonical source 'qa.status'"
        )

    source_status = _nested_value(record, ('qa', 'status'))
    accepted_statuses = {'pass', 'warning', 'fail'}
    if source_status is _MISSING:
        errors.append(
            f"{_projection_prefix(schema_name)}: canonical source 'qa.status' "
            "missing for flat field 'verdict'"
        )
    elif type(source_status) is not str or source_status not in accepted_statuses:
        errors.append(
            f"{_projection_prefix(schema_name)}: canonical source 'qa.status' "
            f"has unsupported value {source_status!r} for flat field 'verdict'"
        )
    else:
        errors.extend(_check_projected_field(
            record,
            schema_name,
            'verdict',
            ('qa', 'status'),
            str,
        ))

    for flat_field, source_path, source_type in (
        ('evidence_summary', ('qa', 'evidence_summary'), dict),
        ('ui_pipeline', ('qa', 'ui_pipeline'), bool),
    ):
        errors.extend(_check_projected_field(
            record,
            schema_name,
            flat_field,
            source_path,
            source_type,
        ))

    # ac_status is an optional QA schema alias.  Once emitted, however, its
    # canonical nested source is mandatory and must match exactly.
    if 'ac_status' in record:
        errors.extend(_check_projected_field(
            record,
            schema_name,
            'ac_status',
            ('qa', 'ac_status'),
            dict,
        ))
    return errors


def _check_report_projection(record: dict, schema_name: str) -> list[str]:
    """Dispatch the v1 report projection pre-pass in a stable field order."""
    if not isinstance(record, dict):
        return [f'{_projection_prefix(schema_name)}: report must be a JSON object']
    if schema_name == 'dev-report.v1':
        return _check_dev_report_projection(record)
    if schema_name == 'qa-report.v1':
        return _check_qa_report_projection(record)
    return []


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

    # A projection contradiction is a self-contained report-contract failure,
    # not validator infrastructure.  Return it before the optional Draft7
    # engine so jsonschema unavailability can never turn known drift into SKIP.
    errors = _check_report_projection(record, schema_name)
    if errors:
        return _result(False, errors, 'fail')

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
# Interactive-mode report schema gate (spec-20260716 §13 asymmetry closure)
# ---------------------------------------------------------------------------
#
# The contract-aware hooks (pretool-subagent-enforce, posttool-overnight-file-
# check) only fire when a per-cycle cycle-contract.json exists — i.e. only in
# /dev-overnight sessions. Interactive /dev + /do never write a contract, so
# their produced report artifacts were NEVER run through jsonschema. This gate
# closes that mechanism asymmetry at /close using the SAME validate() engine the
# overnight path uses (Draft7Validator), without touching the overnight
# machinery.
#
# It is deliberately VERSION-GATED. The v1 report schemas make ``report_version``
# a required const (dev-report.v1 / qa-report.v1 both require report_version==1),
# so an artifact that does NOT declare report_version is, by the schema's own
# contract, not claiming to be a v1 report. Validating such a record against v1
# would be a category error that mass-rejects every current nested (``dev.*`` /
# ``do.*``) report. The gate therefore validates ONLY records that opt in via
# report_version, and is a no-op (skip, NEVER fail-closed) for:
#   - a missing/optional artifact,
#   - an artifact kind with no registered schema (e.g. do-report),
#   - an unparseable artifact (upstream /close preflight already blocks on that),
#   - an unversioned legacy artifact (still covered by /close's structural
#     preflight of dev.status / qa.status).

# Map an interactive report-artifact kind (by filename prefix) to its registered
# schema name. ``do-report`` is intentionally ABSENT: no do-report schema exists,
# so the gate no-ops for it rather than fail-closing.
_INTERACTIVE_REPORT_SCHEMAS = {
    'dev-report': 'dev-report.v1',
    'qa-report': 'qa-report.v1',
}


def _report_kind_for_path(path: Path) -> Optional[str]:
    """Return the report-kind key for ``path`` (by ``<kind>-`` basename prefix)."""
    name = path.name
    for kind in _INTERACTIVE_REPORT_SCHEMAS:
        if name.startswith(kind + '-'):
            return kind
    return None


def _gate_result(status: str, schema, errors, reason: str) -> dict:
    """Shape a report-gate result. status ∈ {'pass', 'fail', 'skip'}."""
    return {
        'status': status,
        'schema': schema,
        'errors': list(errors),
        'reason': reason,
    }


# Exact forms that mark a :func:`validate` ok=False result as a
# schema-INFRASTRUCTURE failure (validator could not run) rather than a genuine
# schema violation. They are matched only when the result has one error and the
# complete error has one of these forms; user-controlled schema/projection
# diagnostics containing the same words remain authoritative failures.
#   - 'schema_registry error:'  -> registry raised (validate() line ~220)
#   - 'not registered'          -> schema not registered (validate() line ~223)
#   - 'validator raised:'       -> Draft7Validator threw (_run_jsonschema line ~211)


def _is_exact_infrastructure_error(error) -> bool:
    text = str(error)
    if text.startswith('schema_registry error:'):
        return True
    if text.startswith("schema '") and text.endswith("' not registered"):
        return True
    return text.startswith('validator raised:')


def _skip_reason_if_unvalidatable(result: dict) -> Optional[str]:
    """Return a skip reason iff :func:`validate` could not actually validate.

    Distinguishes a real schema VERDICT (genuine pass / genuine violation) from
    the two "validator could not run" conditions, so the gate is fail-SAFE:
      - missing validator: validate() returns ok=True + severity='warn' (the
        Draft7Validator-is-None / pre-pass-only path) -> skip, NOT pass. This
        closes the fail-OPEN where an unvalidated versioned report was authorized.
      - schema-infra error: validate() returns ok=False whose errors are the
        registry/not-registered/validator-raised tells (not a schema violation)
        -> skip, NOT fail. This closes the false fail-CLOSE.
    Returns ``None`` when validate() produced a genuine pass or genuine violation.
    """
    if result.get('ok') and result.get('severity') == 'warn':
        return 'validator unavailable (jsonschema/Draft7Validator missing) — cannot validate'
    if not result.get('ok'):
        errors = result.get('errors') or []
        if len(errors) == 1 and _is_exact_infrastructure_error(errors[0]):
            return 'schema infra error (registry/schema-load/validator exception) — cannot validate'
    return None


def validate_report_artifact(path) -> dict:
    """Version-gated schema gate for an interactive dev/qa/do report artifact.

    Returns ``{status, schema, errors, reason}`` where ``status`` is:
      - ``'pass'`` — record declares report_version AND passes its versioned schema.
      - ``'fail'`` — record declares report_version but VIOLATES its versioned
        schema; ``errors`` names the offending field(s). This is the only
        blocking status.
      - ``'skip'`` — no-op (never fail-closed): artifact absent, no registered
        schema for the kind (do-report), unparseable JSON, unversioned legacy
        record (no report_version), OR the validator could not actually run
        (jsonschema/Draft7Validator unavailable, or a schema-infra error such as
        registry failure / unregistered schema / validator exception). The gate
        never BLOCKS on an infra problem and never PASSES an unvalidated
        versioned report.

    Uses the same :func:`validate` (Draft7Validator) engine as the overnight
    contract path, so an interactive artifact that CLAIMS a schema version is now
    validated identically to an overnight one — closing the enforcement asymmetry
    without re-rejecting the current unversioned nested reports.
    """
    p = Path(path)
    if not p.exists():
        return _gate_result('skip', None, [], 'artifact absent (optional — not fail-closed)')
    kind = _report_kind_for_path(p)
    if kind is None:
        return _gate_result('skip', None, [], 'no registered schema for this artifact kind')
    schema_name = _INTERACTIVE_REPORT_SCHEMAS[kind]
    try:
        record = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return _gate_result('skip', schema_name, [], 'unparseable JSON (parse errors handled by /close preflight)')
    if not isinstance(record, dict) or 'report_version' not in record:
        return _gate_result(
            'skip', schema_name, [],
            'unversioned artifact (no report_version); covered by /close structural preflight',
        )
    result = validate(record, schema_name)
    skip_reason = _skip_reason_if_unvalidatable(result)
    if skip_reason is not None:
        return _gate_result('skip', schema_name, [], skip_reason)
    if result.get('ok'):
        return _gate_result('pass', schema_name, [], 'valid against versioned schema')
    return _gate_result('fail', schema_name, result.get('errors', []), 'schema-invalid versioned artifact')


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
