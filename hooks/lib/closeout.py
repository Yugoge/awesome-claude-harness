"""Per-cycle closeout: roll trace.jsonl + reports into harness-report.json.

Public API:
    run_cycle_closeout(session_id, cycle_id) -> dict
    has_pending_required_calls(session_id, cycle_id) -> bool

CLI:
    python3 closeout.py --cycle <N> <session_id>
    python3 closeout.py replay <session_id> <cycle_id>

HARD CUTOVER: when no cycle-contract.json exists, ``run_cycle_closeout``
returns an empty diagnostic dict and writes no harness report. Callers
(stop-overnight-timelock.py) treat this as a no-op.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Make sibling lib importable for direct CLI invocation.
_LIB_DIR = Path(__file__).resolve().parent
_HOOKS_DIR = _LIB_DIR.parent
if str(_HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(_HOOKS_DIR))

try:  # pragma: no cover - convenience for direct CLI use
    from lib.contract_runtime import load_contract
except Exception:  # pragma: no cover
    load_contract = None  # type: ignore[assignment]

if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))
import claude_home  # noqa: E402  (shared WS1 harness-home resolver)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _project_dir() -> Path:
    # WS1: resolve via the shared claude_home resolver, never the literal /root.
    return claude_home.project_dir()


def _cycle_dir(session_id: str, cycle_id: int) -> Path:
    return (
        _project_dir() / "docs" / "dev" / "overnight" /
        session_id / f"cycle-{cycle_id}"
    )


def _trace_path(session_id: str, cycle_id: int) -> Path:
    return _cycle_dir(session_id, cycle_id) / "trace.jsonl"


def _harness_report_path(session_id: str, cycle_id: int) -> Path:
    return _cycle_dir(session_id, cycle_id) / "harness-report.json"


def _yield_log_path() -> Path:
    return _project_dir() / ".claude" / "state" / "specialist-yield-log.jsonl"


# ---------------------------------------------------------------------------
# Reading helpers
# ---------------------------------------------------------------------------


def _read_text_safe(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _read_json_safe(path: Path) -> dict | None:
    text = _read_text_safe(path)
    if text is None:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _parse_jsonl_line(raw: str) -> dict | None:
    s = raw.strip()
    if not s:
        return None
    try:
        rec = json.loads(s)
    except json.JSONDecodeError:
        return None
    return rec if isinstance(rec, dict) else None


def _read_jsonl_safe(path: Path) -> list[dict[str, Any]]:
    text = _read_text_safe(path)
    if text is None:
        return []
    out: list[dict[str, Any]] = []
    for raw in text.splitlines():
        rec = _parse_jsonl_line(raw)
        if rec is not None:
            out.append(rec)
    return out


def _load_contract_disk(session_id: str, cycle_id: int) -> dict | None:
    """Load cycle-contract directly from disk (avoids env coupling)."""
    candidate = _cycle_dir(session_id, cycle_id) / "cycle-contract.json"
    return _read_json_safe(candidate)


def _load_contract_anywhere(session_id: str, cycle_id: int) -> dict | None:
    direct = _load_contract_disk(session_id, cycle_id)
    if direct is not None:
        return direct
    if load_contract is None:
        return None
    try:
        return load_contract(session_id, cycle_id)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Per-pipeline report loading
# ---------------------------------------------------------------------------


def _expected_paths(entry: dict) -> list[str]:
    raw = entry.get("expected_output_path")
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [p for p in raw if isinstance(p, str)]
    return []


def _resolve_path(maybe_path: str) -> Path:
    p = Path(maybe_path)
    if p.is_absolute():
        return p
    return _project_dir() / p


def _load_one_entry_reports(entry: dict) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in _expected_paths(entry):
        data = _read_json_safe(_resolve_path(raw))
        if data is not None:
            out.append({"path": raw, "entry": entry, "report": data})
    return out


def _load_pipeline_reports(contract: dict) -> list[dict[str, Any]]:
    """Return parsed JSON for every required_calls expected_output_path."""
    out: list[dict[str, Any]] = []
    rc = contract.get("required_calls") if isinstance(contract, dict) else None
    if not isinstance(rc, list):
        return out
    for entry in rc:
        if isinstance(entry, dict):
            out.extend(_load_one_entry_reports(entry))
    return out


# ---------------------------------------------------------------------------
# Metric 1: role_compliance_rate
# ---------------------------------------------------------------------------


def _required_role_for_step(contract: dict, step: str) -> str | None:
    rc = contract.get("required_calls") if isinstance(contract, dict) else None
    if not isinstance(rc, list):
        return None
    for entry in rc:
        if isinstance(entry, dict) and entry.get("step") == step:
            role = entry.get("role")
            return role if isinstance(role, str) else None
    return None


def _count_role_matches(trace: list[dict], contract: dict) -> tuple[int, int]:
    matched = 0
    total = 0
    for rec in trace:
        if not (rec.get("step") and rec.get("role")):
            continue
        expected = _required_role_for_step(contract, str(rec.get("step")))
        if expected is None:
            continue
        total += 1
        if expected == rec.get("role"):
            matched += 1
    return matched, total


def _role_compliance_rate(trace: list[dict], contract: dict) -> float | None:
    """% trace records whose role matched the contract for that step."""
    matched, total = _count_role_matches(trace, contract)
    if total == 0:
        return None
    return round(matched / total, 4)


# ---------------------------------------------------------------------------
# Metric 2: false_pass_risk_count
# ---------------------------------------------------------------------------


def _is_qa_report(report_obj: dict) -> bool:
    if not isinstance(report_obj, dict):
        return False
    if report_obj.get("report_type") == "qa":
        return True
    return "verdict" in report_obj or "qa_verdict" in report_obj


def _qa_verdict(report_obj: dict) -> str:
    v = report_obj.get("verdict") or report_obj.get("qa_verdict") or ""
    return str(v).lower().strip()


_UI_EVIDENCE_REQUIRED_FIELDS = (
    "target_route",
    "target_element",
    "viewports",
    "evidence_map",
    "trace",
    "captured_at",
)


def _ui_evidence_block(report_obj: dict) -> dict | None:
    """Return the nested ``evidence_summary.ui_evidence`` block, or None."""
    es = report_obj.get("evidence_summary") or {}
    if not isinstance(es, dict):
        return None
    ui = es.get("ui_evidence")
    if not isinstance(ui, dict):
        return None
    return ui


def _ui_evidence_missing_fields(report_obj: dict) -> list[str]:
    """T3.2: list of REQUIRED ui_evidence fields missing in the QA report."""
    ui = _ui_evidence_block(report_obj)
    if ui is None:
        return list(_UI_EVIDENCE_REQUIRED_FIELDS)
    return [k for k in _UI_EVIDENCE_REQUIRED_FIELDS if not ui.get(k)]


def _ui_evidence_complete(report_obj: dict) -> bool:
    """T3.2: True iff ui_evidence is nested AND all 6 required fields present."""
    return not _ui_evidence_missing_fields(report_obj)


def _is_ui_pipeline(entry: dict) -> bool:
    if entry.get("ui_pipeline") is True:
        return True
    return bool(entry.get("ui_evidence_required"))


def _report_says_ui(report_obj: dict) -> bool:
    """A report's own ui_pipeline flag may also indicate UI scope."""
    return report_obj.get("ui_pipeline") is True


def _qualifies_as_ui_pipeline(item: dict[str, Any]) -> bool:
    """Either the contract entry or the report itself flags this as UI."""
    return _is_ui_pipeline(item.get("entry", {})) or _report_says_ui(item.get("report", {}))


def _is_false_pass_risk(item: dict[str, Any]) -> bool:
    """T3.2: QA pass + UI pipeline + missing/incomplete nested ui_evidence."""
    report = item.get("report", {})
    if not _is_qa_report(report):
        return False
    if _qa_verdict(report) != "pass":
        return False
    if not _qualifies_as_ui_pipeline(item):
        return False
    return not _ui_evidence_complete(report)


def _false_pass_risk_count(loaded: list[dict[str, Any]]) -> int:
    return sum(1 for item in loaded if _is_false_pass_risk(item))


# ---------------------------------------------------------------------------
# Metric 3: ui_evidence_coverage
# ---------------------------------------------------------------------------


def _ui_qa_items(loaded: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """T3.2: items that are QA reports AND flagged as UI pipelines."""
    return [
        i for i in loaded
        if _is_qa_report(i.get("report", {})) and _qualifies_as_ui_pipeline(i)
    ]


def _ui_evidence_coverage(loaded: list[dict[str, Any]]) -> float | None:
    """T3.2: fraction of UI pipelines whose nested ui_evidence is fully complete."""
    ui_qa = _ui_qa_items(loaded)
    if not ui_qa:
        return None
    full = sum(1 for i in ui_qa if _ui_evidence_complete(i.get("report", {})))
    return round(full / len(ui_qa), 4)


# ---------------------------------------------------------------------------
# Metric 4: token_per_fixed_issue
# ---------------------------------------------------------------------------


def _sum_estimated_tokens(trace: list[dict]) -> int:
    return sum(int(t.get("estimated_tokens") or 0) for t in trace)


def _count_passed_pipelines(loaded: list[dict[str, Any]]) -> int:
    n = 0
    for item in loaded:
        rep = item.get("report", {})
        if _is_qa_report(rep) and _qa_verdict(rep) == "pass":
            n += 1
    return n


def _token_per_fixed_issue(trace: list[dict], loaded: list[dict[str, Any]]) -> float | None:
    fixed = _count_passed_pipelines(loaded)
    if fixed <= 0:
        return None
    return round(_sum_estimated_tokens(trace) / fixed, 2)


# ---------------------------------------------------------------------------
# Metric 5: retry_count_by_role
# ---------------------------------------------------------------------------


def _retry_count_by_role(trace: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for rec in trace:
        role = rec.get("role")
        retries = rec.get("retry_count") or 0
        if not isinstance(role, str) or not role:
            continue
        if not isinstance(retries, int):
            continue
        out[role] = out.get(role, 0) + retries
    return out


# ---------------------------------------------------------------------------
# Metric 6: skipped_deferred_escalated_reasons
# ---------------------------------------------------------------------------


_DEGRADATION_STATES = {"escalated", "skipped", "deferred", "low_yield", "clean_sweep"}


def _filter_yield_log_for_session(session_id: str) -> list[dict[str, Any]]:
    records = _read_jsonl_safe(_yield_log_path())
    return [r for r in records if r.get("session_id") == session_id]


def _yield_to_reason(rec: dict) -> dict[str, Any] | None:
    classification = rec.get("classification")
    action = rec.get("action")
    if classification not in _DEGRADATION_STATES and action == "active":
        return None
    return {
        "item": rec.get("specialist_type"),
        "reason": classification or action,
        "status": action,
    }


def _skipped_deferred_escalated_reasons(session_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rec in _filter_yield_log_for_session(session_id):
        reason = _yield_to_reason(rec)
        if reason is not None:
            out.append(reason)
    return out


# ---------------------------------------------------------------------------
# Pending-required-calls check
# ---------------------------------------------------------------------------


def _entry_paths_exist(entry: dict) -> bool:
    paths = _expected_paths(entry)
    if not paths:
        return False
    return all(_resolve_path(raw).exists() for raw in paths)


def _entry_validates_via_runtime(entry: dict) -> bool:
    """T3.2: re-run contract_runtime.validate on every expected_output_path.

    Returns True iff every path parses as JSON AND validates against the
    declared schema (or the entry has no schema, in which case existence
    alone suffices).
    """
    schema_name = entry.get("schema_name") or entry.get("expected_schema") or ""
    for raw in _expected_paths(entry):
        record = _read_json_safe(_resolve_path(raw))
        if record is None:
            return False
        if not schema_name:
            continue
        try:
            from lib.contract_runtime import validate as _runtime_validate
        except Exception:
            return False
        result = _runtime_validate(record, schema_name)
        if not result.get("ok"):
            return False
    return True


def _entry_schema_status_ok(entry: dict) -> bool:
    """Honor explicit schema_status if present (legacy fast-path)."""
    schema_status = entry.get("schema_status")
    if schema_status is None:
        return True
    return schema_status == "validated"


def _entry_has_validated_artifact(entry: dict) -> bool:
    if not _entry_paths_exist(entry):
        return False
    if not _entry_schema_status_ok(entry):
        return False
    return _entry_validates_via_runtime(entry)


def has_pending_required_calls(session_id: str, cycle_id: int) -> bool:
    """True if any required_calls entry is missing artifacts or unvalidated.

    T3.2: in addition to the legacy schema_status check, every entry's
    artifact is re-validated via contract_runtime.validate so that a
    schema-invalid artifact (e.g. malformed nested ui_evidence) blocks
    cycle progression even when the entry never had schema_status set.
    """
    contract = _load_contract_anywhere(session_id, cycle_id)
    if contract is None:
        return False
    rc = contract.get("required_calls")
    if not isinstance(rc, list):
        return False
    for entry in rc:
        if not isinstance(entry, dict):
            continue
        if not _entry_has_validated_artifact(entry):
            return True
    return False


# ---------------------------------------------------------------------------
# Main aggregator
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_metrics(
    trace: list[dict],
    contract: dict,
    loaded: list[dict[str, Any]],
    session_id: str,
) -> dict[str, Any]:
    return {
        "role_compliance_rate": _role_compliance_rate(trace, contract),
        "false_pass_risk_count": _false_pass_risk_count(loaded),
        "ui_evidence_coverage": _ui_evidence_coverage(loaded),
        "token_per_fixed_issue": _token_per_fixed_issue(trace, loaded),
        "retry_count_by_role": _retry_count_by_role(trace),
        "skipped_deferred_escalated_reasons": _skipped_deferred_escalated_reasons(session_id),
    }


def _empty_report_diagnostic(session_id: str, cycle_id: int, reason: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "session_id": session_id,
        "cycle_id": cycle_id,
        "computed_at": _now_iso(),
        "status": "no_contract",
        "reason": reason,
        "metrics": {},
    }


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def run_cycle_closeout(session_id: str, cycle_id: int) -> dict[str, Any]:
    """Produce harness-report.json for the given cycle. HARD CUTOVER on no contract."""
    contract = _load_contract_anywhere(session_id, cycle_id)
    if contract is None:
        return _empty_report_diagnostic(
            session_id, cycle_id, "cycle-contract.json absent (legacy session)"
        )
    trace = _read_jsonl_safe(_trace_path(session_id, cycle_id))
    loaded = _load_pipeline_reports(contract)
    metrics = _build_metrics(trace, contract, loaded, session_id)
    payload = {
        "schema_version": 1,
        "session_id": session_id,
        "cycle_id": cycle_id,
        "computed_at": _now_iso(),
        "status": "computed",
        "trace_record_count": len(trace),
        "pipeline_report_count": len(loaded),
        "metrics": metrics,
    }
    _write_report(_harness_report_path(session_id, cycle_id), payload)
    return payload


# ---------------------------------------------------------------------------
# Replay CLI
# ---------------------------------------------------------------------------


def _format_replay_line(rec: dict) -> str:
    ts = rec.get("ts_iso") or rec.get("end_ts") or "?"
    role = rec.get("role") or rec.get("agent_type") or "?"
    step = rec.get("step") or "-"
    pid = rec.get("pipeline_id") or "-"
    status = rec.get("exit_status") or "-"
    return f"  {ts}  step={step:<8}  role={role:<14}  pipeline={pid:<10}  status={status}"


def _replay(session_id: str, cycle_id: int) -> int:
    trace = _read_jsonl_safe(_trace_path(session_id, cycle_id))
    print(f"# Replay: session={session_id} cycle={cycle_id}")
    print(f"# Trace records: {len(trace)}")
    for rec in trace:
        print(_format_replay_line(rec))
    report = run_cycle_closeout(session_id, cycle_id)
    print("\n# Harness report (summary):")
    print(json.dumps(report.get("metrics", {}), indent=2, sort_keys=True))
    return 0


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="closeout", description="Cycle closeout / replay")
    sub = p.add_subparsers(dest="cmd")
    run_p = sub.add_parser("run", help="Compute harness-report for a cycle")
    run_p.add_argument("--cycle", type=int, required=True)
    run_p.add_argument("session_id")
    rep_p = sub.add_parser("replay", help="Print chronological trace + summary")
    rep_p.add_argument("session_id")
    rep_p.add_argument("cycle_id", type=int)
    p.add_argument("--cycle", type=int, default=None)
    p.add_argument("session_id_pos", nargs="?", default=None)
    return p


def _main_cli(argv: list[str]) -> int:
    parser = _build_argparser()
    args = parser.parse_args(argv)
    if args.cmd == "replay":
        return _replay(args.session_id, args.cycle_id)
    if args.cmd == "run":
        report = run_cycle_closeout(args.session_id, args.cycle)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    if args.cycle is not None and args.session_id_pos:
        report = run_cycle_closeout(args.session_id_pos, args.cycle)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main_cli(sys.argv[1:]))
