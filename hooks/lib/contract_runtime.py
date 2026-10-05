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
import re
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
# schema name. Version-gating still applies: an unversioned legacy record (no
# report_version) skips, so pre-schema do-reports are never retro-rejected.
_INTERACTIVE_REPORT_SCHEMAS = {
    'dev-report': 'dev-report.v1',
    'qa-report': 'qa-report.v1',
    'do-report': 'do-report.v1',
}

# Versioned overlay (zero-failure design §1.6, rollout S1): report kinds with a
# registered v2 schema. Selection is by the record's DECLARED report_version:
#   - 2 -> the kind's .v2 name (nested producer shape);
#   - 1 -> the kind's .v1 name (today's path, byte-identical);
#   - any OTHER declared version (e.g. 3), and every do-report version, falls
#     through to the kind's v1 schema, whose report_version const then fails —
#     preserving today's observed behavior for alien versions. Mapping unknown
#     versions to SKIP was deliberately REJECTED (ticket 20260929-104216-a M5):
#     it would silently turn today's fail into a pass-through and weaken the
#     gate. Unversioned records never reach selection: the version gate in
#     validate_report_artifact returns skip first, so the measured unversioned
#     legacy corpus is never retro-rejected.
_INTERACTIVE_REPORT_SCHEMAS_V2 = {
    'dev-report': 'dev-report.v2',
    'qa-report': 'qa-report.v2',
}


def _versioned_schema_name(kind: str, record: dict) -> str:
    """Select the registered schema name for ``kind`` by declared report_version."""
    v2_name = _INTERACTIVE_REPORT_SCHEMAS_V2.get(kind)
    if v2_name is not None and record.get('report_version') == 2:
        return v2_name
    return _INTERACTIVE_REPORT_SCHEMAS[kind]


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


# Tell-tale substrings that mark a :func:`validate` ok=False result as a
# schema-INFRASTRUCTURE failure (validator could not run) rather than a genuine
# schema violation. Sourced verbatim from validate()'s own error strings:
#   - 'schema_registry error:'  -> registry raised (validate() line ~220)
#   - 'not registered'          -> schema not registered (validate() line ~223)
#   - 'validator raised:'       -> Draft7Validator threw (_run_jsonschema line ~211)
_INFRA_ERROR_TELLS = (
    'schema_registry error:',
    'not registered',
    'validator raised:',
)


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
        joined = ' '.join(str(e) for e in (result.get('errors') or []))
        if any(tell in joined for tell in _INFRA_ERROR_TELLS):
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
        schema for the kind, unparseable JSON, unversioned legacy
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
    schema_name = _versioned_schema_name(kind, record)
    result = validate(record, schema_name)
    skip_reason = _skip_reason_if_unvalidatable(result)
    if skip_reason is not None:
        return _gate_result('skip', schema_name, [], skip_reason)
    if result.get('ok'):
        return _gate_result('pass', schema_name, [], 'valid against versioned schema')
    return _gate_result('fail', schema_name, result.get('errors', []), 'schema-invalid versioned artifact')


def _normalize_version_for_obligation(record, schema_id: str):
    """Override the record's self-declared report_version under obligation authority.

    The obligation's schema id is the sole authority (design §1.2; AC-5): a
    mismatching or ABSENT self-declared report_version must not fail an
    otherwise shape-valid artifact against the obligation's schema. When the
    supplied schema pins ``properties.report_version.const``, a shallow copy
    of the record is validated with that const in place of the
    self-declaration; every other field is validated verbatim. No-op when the
    schema pins no report_version const, or on any schema-load problem —
    :func:`validate` then reports the infra condition itself (fail-safe skip).
    """
    if not isinstance(record, dict):
        return record
    try:
        schema = schema_registry.get_schema(schema_id)
    except Exception:  # pragma: no cover — validate() reports this infra path
        return record
    if not isinstance(schema, dict):
        return record
    declared = schema.get('properties', {}).get('report_version', {})
    const = declared.get('const') if isinstance(declared, dict) else None
    if const is None:
        return record
    normalized = dict(record)
    normalized['report_version'] = const
    return normalized


def validate_artifact_for_obligation(path, schema_id: str) -> dict:
    """Obligation-authority schema gate (zero-failure design §1.2, rollout S1).

    Validates the artifact at ``path`` against the OBLIGATION-supplied
    ``schema_id``, ignoring the record's self-declared ``report_version``
    entirely (present, absent, or mismatching): authority comes from the
    obligation, never from the artifact's self-declaration (the version field
    itself is normalized to the obligation schema's pinned const via
    :func:`_normalize_version_for_obligation`; all other fields validate
    verbatim).

    Deliberate differences from :func:`validate_report_artifact`
    (self-declared authority):
      - absent file -> ``'fail'`` — the obligation names an exact expected
        path, so "missing is blocking" (design §1.3 G2), unlike the
        self-declared gate where an absent optional artifact skips;
      - unparseable JSON -> ``'fail'``;
      - unversioned record -> validated anyway (no version gate under
        obligation authority; non-obligated reads keep the version-gated
        skip, so the unversioned legacy corpus is untouched).

    Preserved fail-safe (C5): infra unavailability — unregistered schema id,
    registry error, missing Draft7Validator, validator exception — returns
    ``'skip'`` with a named reason via the same
    :func:`_skip_reason_if_unvalidatable` split. A hook infra failure must
    never trap a producer; G1 validates schema-id registration at dispatch.

    Purely additive this cycle: NOT wired into any hook, command, or template
    (G2 wiring is rollout S4). Returns the same ``{status, schema, errors,
    reason}`` shape as :func:`validate_report_artifact`.
    """
    p = Path(path)
    if not p.exists():
        return _gate_result(
            'fail', schema_id, [f'expected artifact missing: {p}'],
            'obligation-named artifact absent (missing is blocking under obligation authority)',
        )
    try:
        record = json.loads(p.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        return _gate_result(
            'fail', schema_id, [f'unparseable JSON: {exc}'],
            'obligation-named artifact is not valid JSON',
        )
    result = validate(_normalize_version_for_obligation(record, schema_id), schema_id)
    skip_reason = _skip_reason_if_unvalidatable(result)
    if skip_reason is not None:
        return _gate_result('skip', schema_id, [], skip_reason)
    if result.get('ok'):
        return _gate_result('pass', schema_id, [], 'valid against obligation-supplied schema')
    return _gate_result(
        'fail', schema_id, result.get('errors', []),
        'schema-invalid under obligation-supplied schema',
    )


def validate_markdown_artifact_for_obligation(
    path, identity_anchor: Optional[str], terminal_line_regex: Optional[str]
) -> dict:
    """Obligation-authority markdown-artifact gate (ticket 20261001-161041-r01).

    Sibling of :func:`validate_artifact_for_obligation` for ``kind=="markdown"``
    obligation artifacts (e.g. BA's own ``ticket-<task_id>.md``): verifies
    existence, the declared ``identity_anchor`` substring, and the declared
    ``terminal_line_regex`` against the artifact's last non-empty line.
    Returns the same ``{status, schema, errors, reason}`` shape (via
    :func:`_gate_result`) as the json-kind sibling, called from both
    ``hooks/pretool-aggregate-check.py::_verify_prior_artifact`` (G3) and
    ``hooks/subagentstop-artifact-contract-enforce.py`` (producer-side Stop,
    this ticket's new wiring).

    Extracted verbatim (logic, not shape) from
    ``hooks/pretool-aggregate-check.py::_verify_prior_artifact``'s pre-existing
    markdown branch — this function is the single source of truth both call
    sites now share; neither re-implements the check inline.

    Status values:
      - ``'pass'`` — file exists, ``identity_anchor`` substring present (or
        not declared), and the last non-empty line matches
        ``terminal_line_regex`` (or the regex is empty/absent/malformed —
        malformed regex fails SAFE: ``except re.error: matched = True``,
        "our own bug, never fails the artifact", same polarity as the
        pre-existing logic this extracts).
      - ``'fail'`` — file missing/unreadable (``reason`` contains
        ``"artifact_missing"``), ``identity_anchor`` substring absent
        (``reason`` contains ``"identity_anchor_missing"``), or the last
        non-empty line fails to match ``terminal_line_regex`` (``reason``
        contains ``"terminal_line_mismatch"``). The three reasons are
        mutually distinguishable by substring, mirroring
        ``_verify_prior_artifact``'s own ``code`` vocabulary.

    ``identity_anchor`` is a plain substring (``in``) check, NOT a regex —
    upgrading it to ``re.search`` would silently change already-tested G3
    behavior (Edge Case 3, this ticket's BA spec).
    """
    p = Path(path)
    if not p.exists():
        return _gate_result(
            'fail', None, [f'obligation-named markdown artifact absent: {p}'],
            'artifact_missing: obligation-named markdown artifact absent',
        )
    try:
        text = p.read_text(encoding='utf-8')
    except Exception as exc:  # matches _verify_prior_artifact's pre-existing broad catch
        return _gate_result(
            'fail', None, [f'obligation-named markdown artifact unreadable: {exc}'],
            'artifact_missing: obligation-named markdown artifact unreadable',
        )
    if isinstance(identity_anchor, str) and identity_anchor and identity_anchor not in text:
        return _gate_result(
            'fail', None,
            [f'identity_anchor substring not found: {identity_anchor!r}'],
            'identity_anchor_missing: declared identity_anchor substring not found in markdown artifact',
        )
    if isinstance(terminal_line_regex, str) and terminal_line_regex:
        non_empty = [ln for ln in text.splitlines() if ln.strip()]
        last_line = non_empty[-1] if non_empty else ''
        try:
            matched = re.search(terminal_line_regex, last_line) is not None
        except re.error:
            matched = True  # malformed regex: our own bug, never fails the artifact
        if not matched:
            return _gate_result(
                'fail', None,
                [f'last non-empty line {last_line!r} does not match terminal_line_regex {terminal_line_regex!r}'],
                'terminal_line_mismatch: last non-empty line does not match declared terminal_line_regex',
            )
    return _gate_result('pass', None, [], 'valid against obligation-supplied markdown shape')


def validate_response_line_for_obligation(
    last_assistant_message, terminal_line_regex: Optional[str]
) -> dict:
    """Obligation-authority response_line gate (ticket 20261001-161041-r12).

    Sibling of :func:`validate_markdown_artifact_for_obligation` for
    ``kind=="response_line"`` obligation artifacts (e.g. close-QA's own
    final verdict line): no file I/O -- validates the PRODUCER'S OWN final
    response text (the SubagentStop payload's ``last_assistant_message``
    field) against the declared ``terminal_line_regex``, using the
    identical last-non-empty-line + fail-open-on-malformed-regex semantics
    as the markdown-kind sibling above (same
    ``except re.error: matched = True`` polarity). Returns the same
    ``{status, schema, errors, reason}`` shape via :func:`_gate_result`;
    ``status`` is always ``'pass'`` or ``'fail'`` (there is no file that
    can be missing).
    """
    text = last_assistant_message if isinstance(last_assistant_message, str) else ''
    if isinstance(terminal_line_regex, str) and terminal_line_regex:
        non_empty = [ln for ln in text.splitlines() if ln.strip()]
        last_line = non_empty[-1] if non_empty else ''
        try:
            matched = re.search(terminal_line_regex, last_line) is not None
        except re.error:
            matched = True  # malformed regex: our own bug, never fails the artifact
        if not matched:
            return _gate_result(
                'fail', None,
                [f'last non-empty line {last_line!r} does not match terminal_line_regex {terminal_line_regex!r}'],
                'terminal_line_mismatch: last non-empty line of response does not match declared terminal_line_regex',
            )
    return _gate_result('pass', None, [], 'valid against obligation-supplied response_line shape')


def validate_response_block_for_obligation(
    last_assistant_message, begin: Optional[str], end: Optional[str], schema_id: str
) -> dict:
    """Obligation-authority response_block gate (ticket 20261001-161041-r21, M2).

    Sibling of :func:`validate_response_line_for_obligation` for
    ``kind=="response_block"`` obligation artifacts (e.g. changelog-analyst's
    own BEGIN/END-delimited JSON status block, commands/commit.md:463-480):
    no file I/O and no transcript scan -- the SubagentStop payload already
    carries the producer's own final response text as ``last_assistant_message``
    (the same field ``validate_response_line_for_obligation`` and the
    ``waived_by_response`` markdown-waiver check already key off, ticket
    20261001-161041-r12); this function locates the ``begin``/``end``
    sentinel-delimited substring within that text, parses it as JSON, and
    validates the result against the obligation-supplied ``schema_id`` via
    the EXISTING :func:`validate` engine -- no second jsonschema call path.

    Status values (``errors``/``reason`` distinguish the three failure
    modes per ticket AC3):
      - ``'fail'`` -- the ``begin`` or ``end`` sentinel substring is not
        found in the response text (``reason`` contains
        ``'sentinel_missing'``), the delimited substring is not valid JSON
        (``reason`` contains ``'unparseable_json'``), or the parsed JSON
        violates ``schema_id`` (``reason`` contains ``'schema-invalid'``).
      - ``'skip'`` -- the obligation itself did not declare both sentinels
        (malformed declaration, not a producer failure) or the schema
        validator could not run (:func:`_skip_reason_if_unvalidatable`,
        same infra fail-safe every obligation-authority gate shares).
      - ``'pass'`` -- the delimited substring parses as JSON and validates
        against ``schema_id``.
    """
    if not isinstance(begin, str) or not begin or not isinstance(end, str) or not end:
        return _gate_result(
            'skip', schema_id, [],
            'obligation_declaration_malformed: begin/end sentinels not declared',
        )
    text = last_assistant_message if isinstance(last_assistant_message, str) else ''
    begin_idx = text.find(begin)
    if begin_idx == -1:
        return _gate_result(
            'fail', schema_id, [f'begin sentinel not found in response: {begin!r}'],
            'sentinel_missing: begin sentinel not found in producer response',
        )
    end_idx = text.find(end, begin_idx + len(begin))
    if end_idx == -1:
        return _gate_result(
            'fail', schema_id, [f'end sentinel not found in response: {end!r}'],
            'sentinel_missing: end sentinel not found in producer response',
        )
    block_text = text[begin_idx + len(begin):end_idx].strip()
    try:
        record = json.loads(block_text)
    except json.JSONDecodeError as exc:
        return _gate_result(
            'fail', schema_id, [f'unparseable JSON between sentinels: {exc}'],
            'unparseable_json: response_block content between sentinels is not valid JSON',
        )
    result = validate(record, schema_id)
    skip_reason = _skip_reason_if_unvalidatable(result)
    if skip_reason is not None:
        return _gate_result('skip', schema_id, [], skip_reason)
    if result.get('ok'):
        return _gate_result('pass', schema_id, [], 'valid against obligation-supplied response_block schema')
    return _gate_result(
        'fail', schema_id, result.get('errors', []),
        'schema-invalid under obligation-supplied response_block schema',
    )


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
