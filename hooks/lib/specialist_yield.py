"""Specialist yield classification and auto-degradation policy.

Public API:
    classify_report(report_path) -> "productive" | "low_yield" | "clean_sweep"
    compute_yield(specialist_type, current_report_path, history_window=5) -> dict
    record_yield(report_artifact_path, specialist_type, session_id, cycle_id,
                 classification, action) -> None
    get_degradation_state(specialist_type, session_id=None) -> dict

Policy: $CLAUDE_PROJECT_DIR/.claude/policies/specialist-degradation.v1.json
Log:    $CLAUDE_PROJECT_DIR/.claude/state/specialist-yield-log.jsonl

Env overrides for tests:
    SPECIALIST_YIELD_POLICY_PATH
    SPECIALIST_YIELD_LOG_PATH
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claude_home  # noqa: E402  (shared WS1 harness-home resolver)

try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:  # pragma: no cover
    _HAS_FCNTL = False


_FALLBACK_POLICY: dict[str, Any] = {
    "policy_version": 1,
    "defaults": {
        "low_yield_threshold": 3,
        "clean_sweep_threshold": 5,
        "degradation_actions": ["reduce_budget_50pct", "skip_next_cycle"],
        "history_window": 5,
        "escalation_after_actions": [
            "reduce_budget_50pct",
            "skip_next_cycle",
            "skip_next_2_cycles",
            "escalate_to_user",
        ],
    },
    "per_specialist_overrides": {
        "ui-specialist": {"low_yield_threshold": 4, "clean_sweep_threshold": 7},
        "user": {"low_yield_threshold": 5, "clean_sweep_threshold": 10},
    },
}

_DEGRADED_ACTION_LABELS = {
    "reduce_budget_50pct",
    "skip_next_cycle",
    "skip_next_2_cycles",
    "escalated",
}


def _project_dir() -> Path:
    # WS1: resolve via the shared claude_home resolver, never the literal /root.
    return claude_home.project_dir()


def _policy_path() -> Path:
    override = os.environ.get("SPECIALIST_YIELD_POLICY_PATH")
    if override:
        return Path(override)
    return _project_dir() / ".claude" / "policies" / "specialist-degradation.v1.json"


def _log_path() -> Path:
    override = os.environ.get("SPECIALIST_YIELD_LOG_PATH")
    if override:
        return Path(override)
    return _project_dir() / ".claude" / "state" / "specialist-yield-log.jsonl"


def _read_text_safe(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _load_policy() -> dict[str, Any]:
    text = _read_text_safe(_policy_path())
    if text is None:
        return _FALLBACK_POLICY
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return _FALLBACK_POLICY
    if not isinstance(data, dict) or "defaults" not in data:
        return _FALLBACK_POLICY
    return data


def _resolve_policy_for(specialist_type: str) -> dict[str, Any]:
    policy = _load_policy()
    defaults = dict(policy.get("defaults", _FALLBACK_POLICY["defaults"]))
    overrides = (policy.get("per_specialist_overrides") or {}).get(specialist_type, {})
    if isinstance(overrides, dict):
        defaults.update(overrides)
    return defaults


def _parse_log_line(line: str) -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("//"):
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def _parse_log_text(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in text.splitlines():
        rec = _parse_log_line(raw)
        if rec is not None:
            out.append(rec)
    return out


def _read_log_lines() -> list[dict[str, Any]]:
    path = _log_path()
    if not path.exists():
        return []
    text = _read_text_safe(path)
    if text is None:
        return []
    return _parse_log_text(text)


def _filter_history(
    records: list[dict[str, Any]],
    specialist_type: str,
    history_window: int,
) -> list[dict[str, Any]]:
    matched = [r for r in records if r.get("specialist_type") == specialist_type]
    if history_window <= 0:
        return matched
    return matched[-history_window:]


def _signature_of(item: Any) -> str | None:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        sig = item.get("id") or item.get("signature")
        return str(sig) if sig is not None else None
    return None


def _extract_prior_signatures(report: dict[str, Any]) -> set[str]:
    prior = report.get("prior_findings") or report.get("known_findings") or []
    if not isinstance(prior, list):
        return set()
    sigs = {_signature_of(p) for p in prior}
    return {s for s in sigs if s is not None}


def _count_new_findings(findings: list[Any], prior_signatures: set[str]) -> int:
    new_count = 0
    for f in findings:
        sig = _signature_of(f)
        if sig is None or sig not in prior_signatures:
            new_count += 1
    return new_count


def _load_report(report_path: str) -> dict[str, Any] | None:
    text = _read_text_safe(Path(report_path))
    if text is None:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def classify_report(report_path: str) -> str:
    """Classify a specialist report. Fail-safe defaults to 'productive'."""
    report = _load_report(report_path)
    if report is None:
        return "productive"
    findings = report.get("findings") or []
    if not isinstance(findings, list):
        return "productive"
    verdict = str(report.get("verdict", "")).lower().strip()
    if len(findings) == 0 and verdict in {"pass", "no_issues"}:
        return "clean_sweep"
    new_count = _count_new_findings(findings, _extract_prior_signatures(report))
    return "low_yield" if new_count <= 1 else "productive"


def _trailing_run(sequence: list[Any], label: str) -> int:
    n = 0
    for c in reversed(sequence):
        if c == label:
            n += 1
        else:
            break
    return n


def _decide_next_action(
    classification: str,
    history: list[dict[str, Any]],
    policy: dict[str, Any],
) -> str:
    low_t = int(policy.get("low_yield_threshold", 3))
    cs_t = int(policy.get("clean_sweep_threshold", 5))
    sequence = [r.get("classification") for r in history] + [classification]
    if _trailing_run(sequence, "clean_sweep") >= cs_t:
        return "skip_next_cycle"
    if _trailing_run(sequence, "low_yield") >= low_t:
        return "reduce_budget_50pct"
    return "active"


def compute_yield(
    specialist_type: str,
    current_report_path: str,
    history_window: int = 5,
) -> dict[str, Any]:
    classification = classify_report(current_report_path)
    policy = _resolve_policy_for(specialist_type)
    window = int(policy.get("history_window", history_window))
    history = _filter_history(_read_log_lines(), specialist_type, window)
    return {
        "classification": classification,
        "history": history,
        "next_action": _decide_next_action(classification, history, policy),
    }


def _build_record(
    report_artifact_path: str,
    specialist_type: str,
    session_id: str,
    cycle_id: int,
    classification: str,
    action: str,
) -> dict[str, Any]:
    return {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "specialist_type": specialist_type,
        "session_id": session_id,
        "cycle_id": cycle_id,
        "classification": classification,
        "action": action,
        "source_record_path": report_artifact_path,
    }


def _safe_unlock(fh) -> None:
    if not _HAS_FCNTL:  # pragma: no cover
        return
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def _write_one(fh, line: str) -> None:
    fh.write(line)
    fh.flush()
    if _HAS_FCNTL:
        os.fsync(fh.fileno())


def _locked_append(path: Path, line: str) -> None:
    fh = path.open("a", encoding="utf-8")
    try:
        if _HAS_FCNTL:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        _write_one(fh, line)
    finally:
        _safe_unlock(fh)
        fh.close()


def record_yield(
    report_artifact_path: str,
    specialist_type: str,
    session_id: str,
    cycle_id: int,
    classification: str,
    action: str,
) -> None:
    """Append one JSONL record to the yield log."""
    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = _build_record(
        report_artifact_path, specialist_type, session_id, cycle_id, classification, action
    )
    line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    _locked_append(path, line)


def _trailing_degraded_actions(history: list[dict[str, Any]]) -> list[str]:
    actions = [r.get("action") for r in history]
    trailing: list[str] = []
    for a in reversed(actions):
        if a not in _DEGRADED_ACTION_LABELS:
            break
        trailing.append(a)
    trailing.reverse()
    return trailing


def _check_escalation(
    history: list[dict[str, Any]], escalation_chain: list[str]
) -> dict[str, Any] | None:
    trailing = _trailing_degraded_actions(history)
    if len(trailing) < len(escalation_chain):
        return None
    return {
        "state": "escalated",
        "reason": (
            f"escalation chain exhausted "
            f"({len(trailing)} consecutive degraded actions >= "
            f"{len(escalation_chain)} chain length)"
        ),
        "action": "escalate_to_user",
        "source_records": history,
    }


def _check_clean_sweep(
    history: list[dict[str, Any]], threshold: int
) -> dict[str, Any] | None:
    classifications = [r.get("classification") for r in history]
    cs_run = _trailing_run(classifications, "clean_sweep")
    if cs_run < threshold:
        return None
    return {
        "state": "skipped",
        "reason": (
            f"{cs_run} consecutive clean_sweep classifications "
            f">= threshold {threshold}"
        ),
        "action": "skip_next_cycle",
        "source_records": history,
    }


def _check_low_yield(
    history: list[dict[str, Any]], threshold: int
) -> dict[str, Any] | None:
    classifications = [r.get("classification") for r in history]
    ly_run = _trailing_run(classifications, "low_yield")
    if ly_run < threshold:
        return None
    return {
        "state": "degraded",
        "reason": (
            f"{ly_run} consecutive low_yield classifications "
            f">= threshold {threshold}"
        ),
        "action": "reduce_budget_50pct",
        "source_records": history,
    }


def _active_state(
    history: list[dict[str, Any]], ly_t: int, cs_t: int
) -> dict[str, Any]:
    classifications = [r.get("classification") for r in history]
    ly_run = _trailing_run(classifications, "low_yield")
    cs_run = _trailing_run(classifications, "clean_sweep")
    return {
        "state": "active",
        "reason": (
            f"trailing low_yield run={ly_run}/{ly_t}, "
            f"clean_sweep run={cs_run}/{cs_t}; both below threshold"
        ),
        "action": "active",
        "source_records": history,
    }


def _empty_history_response() -> dict[str, Any]:
    return {
        "state": "active",
        "reason": "no history records found for specialist (empty history)",
        "action": "active",
        "source_records": [],
    }


def _failsafe_response(reason: str) -> dict[str, Any]:
    return {"state": "active", "reason": reason, "action": "active", "source_records": []}


def _resolve_policy_safe(specialist_type: str) -> dict[str, Any] | None:
    try:
        return _resolve_policy_for(specialist_type)
    except Exception:
        return None


def _read_log_safe() -> list[dict[str, Any]] | None:
    try:
        return _read_log_lines()
    except Exception:
        return None


def _evaluate_history(
    history: list[dict[str, Any]],
    low_t: int,
    cs_t: int,
    chain: list[str],
) -> dict[str, Any]:
    for check in (
        _check_escalation(history, chain),
        _check_clean_sweep(history, cs_t),
        _check_low_yield(history, low_t),
    ):
        if check is not None:
            return check
    return _active_state(history, low_t, cs_t)


def get_degradation_state(
    specialist_type: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Determine current degradation state for a specialist."""
    policy = _resolve_policy_safe(specialist_type)
    if policy is None:
        return _failsafe_response("policy unreadable, fail-safe default")
    all_records = _read_log_safe()
    if all_records is None:
        return _failsafe_response("yield-log unreadable, fail-safe")

    window = int(policy.get("history_window", 5))
    history = _filter_history(all_records, specialist_type, window)
    if not history:
        return _empty_history_response()

    low_t = int(policy.get("low_yield_threshold", 3))
    cs_t = int(policy.get("clean_sweep_threshold", 5))
    chain = list(
        policy.get(
            "escalation_after_actions",
            _FALLBACK_POLICY["defaults"]["escalation_after_actions"],
        )
    )
    return _evaluate_history(history, low_t, cs_t, chain)
