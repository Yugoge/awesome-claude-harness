#!/usr/bin/env python3
"""PostToolUse:Agent observability hook.

Writes one JSONL trace record per Agent invocation to:
    docs/dev/overnight/<session_id>/cycle-<cycle_id>/trace.jsonl

For specialist agents (architect, ui-specialist, product-owner, user) it
also classifies the produced report and records the yield via
``lib.specialist_yield``.

HARD CUTOVER: when no overnight-state-*.json or cycle-contract.json is
present (legacy /spec, single-shot /dev sessions) the hook exits 0
immediately so it never blocks.

Fail-soft: ANY exception is swallowed and reported on stderr. Exit code
is always 0 -- this hook is observability, never a gate.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Make sibling lib importable regardless of cwd.
_HOOKS_DIR = Path(__file__).resolve().parent
if str(_HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(_HOOKS_DIR))

try:
    from lib.specialist_yield import classify_report, record_yield  # noqa: E402
except Exception:  # pragma: no cover - fail-soft if lib missing
    classify_report = None  # type: ignore[assignment]
    record_yield = None  # type: ignore[assignment]

try:
    from lib.contract_runtime import load_contract  # noqa: E402
except Exception:  # pragma: no cover
    load_contract = None  # type: ignore[assignment]

try:
    from lib import claude_home  # noqa: E402  (shared WS1 resolver)
except Exception:  # pragma: no cover - fail-soft if lib missing
    claude_home = None  # type: ignore[assignment]


_SPECIALIST_TYPES = {"architect", "ui-specialist", "product-owner", "user"}


# ---------------------------------------------------------------------------
# stdin + project-dir helpers
# ---------------------------------------------------------------------------


def _read_stdin_json() -> dict:
    try:
        if sys.stdin.isatty():
            return {}
        return json.load(sys.stdin)
    except Exception:
        return {}


def _project_dir() -> Path:
    # WS1: resolve via the shared claude_home resolver (CLAUDE_PROJECT_DIR ->
    # harness home -> cwd), never the author literal /root.
    if claude_home is not None:
        return claude_home.project_dir()
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _try_load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# session/cycle resolution
# ---------------------------------------------------------------------------


def _scan_state_dir(claude_dir: Path, session_id: str) -> dict | None:
    for path in sorted(claude_dir.glob("overnight-state-*.json")):
        data = _try_load_json(path)
        if data is None:
            continue
        if not session_id or data.get("session_id") == session_id:
            return data
    return None


def _read_overnight_state(project_dir: Path, session_id: str) -> dict | None:
    """Return the matching overnight-state-*.json contents, or None."""
    claude_dir = project_dir / ".claude"
    if not claude_dir.is_dir():
        return None
    if session_id:
        exact_data = _try_load_json(claude_dir / f"overnight-state-{session_id}.json")
        if exact_data is not None:
            return exact_data
    return _scan_state_dir(claude_dir, session_id)


def _coerce_cycle_id(state: dict) -> int | None:
    cid_raw = state.get("cycle_count")
    try:
        return int(cid_raw) if cid_raw is not None else None
    except (TypeError, ValueError):
        return None


def _resolve_session_cycle(stdin_ctx: dict) -> tuple[str | None, int | None, dict | None]:
    """Return (session_id, cycle_id, state_dict) from env + state files."""
    session_id = stdin_ctx.get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or ""
    state = _read_overnight_state(_project_dir(), session_id)
    if state is None:
        return (session_id or None, None, None)
    sid = session_id or state.get("session_id")
    return (sid, _coerce_cycle_id(state), state)


# ---------------------------------------------------------------------------
# Field extractors -- all defensive, all fail-safe to None/0/[]
# ---------------------------------------------------------------------------


def _agent_type(stdin_ctx: dict) -> str | None:
    tool_input = stdin_ctx.get("tool_input") or {}
    if isinstance(tool_input, dict):
        st = tool_input.get("subagent_type")
        if isinstance(st, str) and st:
            return st
    return None


def _agent_id() -> str | None:
    aid = os.environ.get("CLAUDE_AGENT_ID")
    return aid if aid else None


def _current_step(state: dict | None) -> str | None:
    if not isinstance(state, dict):
        return None
    step = state.get("current_step") or state.get("current_phase")
    return str(step) if step is not None else None


def _mode_from_input(stdin_ctx: dict) -> str | None:
    """Sniff DESIGN_MODE / AUDIT_MODE / UI_MODE / etc. from agent prompt."""
    ti = stdin_ctx.get("tool_input") or {}
    if not isinstance(ti, dict):
        return None
    prompt = ti.get("prompt") or ti.get("description") or ""
    if not isinstance(prompt, str):
        return None
    for tag in ("DESIGN_MODE", "AUDIT_MODE", "UI_MODE", "PLAN", "TRIAGE", "RETRO"):
        if tag in prompt:
            return tag
    return None


def _pipeline_id_from_input(ti: dict) -> str | None:
    for key in ("pipeline_id", "pipelineId"):
        v = ti.get(key)
        if isinstance(v, str) and v:
            return v
    return None


def _pipeline_id_from_contract(contract: dict | None) -> str | None:
    if not isinstance(contract, dict):
        return None
    pl = contract.get("pipelines")
    if isinstance(pl, dict) and len(pl) == 1:
        return next(iter(pl.keys()))
    return None


def _pipeline_id_from(stdin_ctx: dict, contract: dict | None) -> str | None:
    ti = stdin_ctx.get("tool_input") or {}
    if isinstance(ti, dict):
        from_input = _pipeline_id_from_input(ti)
        if from_input is not None:
            return from_input
    return _pipeline_id_from_contract(contract)


def _tool_response(stdin_ctx: dict) -> dict | None:
    tr = stdin_ctx.get("tool_response")
    return tr if isinstance(tr, dict) else None


def _tool_call_count(tool_response: dict | None) -> int | None:
    if not isinstance(tool_response, dict):
        return None
    for key in ("tool_call_count", "num_tool_calls", "tool_calls"):
        v = tool_response.get(key)
        if isinstance(v, int):
            return v
        if isinstance(v, list):
            return len(v)
    return None


def _estimated_tokens(tool_response: dict | None) -> int | None:
    if not isinstance(tool_response, dict):
        return None
    usage = tool_response.get("usage")
    if not isinstance(usage, dict):
        return None
    v = usage.get("total_tokens")
    if isinstance(v, int):
        return v
    in_t = usage.get("input_tokens") or 0
    out_t = usage.get("output_tokens") or 0
    if isinstance(in_t, int) and isinstance(out_t, int) and (in_t or out_t):
        return in_t + out_t
    return None


def _looks_like_artifact(token: str) -> bool:
    if "/" not in token:
        return False
    if "/docs/" not in token and "/.claude/" not in token:
        return False
    return token.endswith((".json", ".md", ".jsonl", ".py"))


def _artifact_paths_from_response(tool_response: dict | None) -> list[str]:
    if not isinstance(tool_response, dict):
        return []
    out = tool_response.get("output") or tool_response.get("text") or ""
    if not isinstance(out, str) or not out:
        return []
    seen: set[str] = set()
    unique: list[str] = []
    for token in out.split():
        stripped = token.strip().strip(",.;:'\"()[]")
        if not _looks_like_artifact(stripped):
            continue
        if stripped not in seen:
            seen.add(stripped)
            unique.append(stripped)
    return unique


_AGENT_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    # T3.2: schema-required field presence per agent_type, used to compute
    # evidence_completeness from the actual just-completed agent report
    # (NOT a placeholder).
    "qa": ("verdict", "evidence_summary", "ui_pipeline", "task_id", "report_version"),
    "dev": ("status", "files_modified", "files_created",
            "root_cause_addressed", "ac_status", "task_id", "report_version"),
    "ba": ("requirement", "root_cause_analysis"),
    "architect": ("recommendations",),
    "ui-specialist": ("ui_evidence",),
    "product-owner": ("decision",),
    "pm": ("plan",),
    "user": (),
}

_UI_EVIDENCE_REQUIRED = (
    "target_route", "target_element", "viewports",
    "evidence_map", "trace", "captured_at",
)


def _required_fields_for(agent_type: str | None) -> tuple[str, ...]:
    if not agent_type:
        return ()
    return _AGENT_REQUIRED_FIELDS.get(agent_type, ())


def _pick_json_artifact(artifact_paths: list[str]) -> Path | None:
    """Return the first .json artifact path resolved against project_dir."""
    for raw in artifact_paths:
        if not isinstance(raw, str) or not raw.endswith(".json"):
            continue
        p = Path(raw) if raw.startswith("/") else _project_dir() / raw
        if p.exists():
            return p
    return None


def _read_report(path: Path) -> dict | None:
    return _try_load_json(path)


def _missing_top_level_fields(report: dict, required: tuple[str, ...]) -> list[str]:
    """Schema-required field presence — key absence counts as missing.

    Empty list / empty dict / 0 / False / "" all count as PRESENT because
    the schema only requires the key to exist. Semantic emptiness is
    surfaced separately via the nested ui_evidence sub-check.
    """
    return [k for k in required if k not in report]


def _ui_evidence_status(report: dict) -> tuple[str, list[str]]:
    """Classify nested evidence_summary.ui_evidence completeness.

    Returns (status, missing_fields).
    status ∈ {complete, partial, missing, not_applicable}.
    """
    if report.get("ui_pipeline") is not True:
        return "not_applicable", []
    es = report.get("evidence_summary") or {}
    if not isinstance(es, dict):
        return "missing", list(_UI_EVIDENCE_REQUIRED)
    ui = es.get("ui_evidence")
    if not isinstance(ui, dict):
        return "missing", list(_UI_EVIDENCE_REQUIRED)
    missing = [k for k in _UI_EVIDENCE_REQUIRED if not ui.get(k)]
    if not missing:
        return "complete", []
    if len(missing) == len(_UI_EVIDENCE_REQUIRED):
        return "missing", missing
    return "partial", missing


def _citations_present(report: dict) -> bool | None:
    """Best-effort detection of citations/sources in BA/architect reports."""
    for key in ("citations", "sources", "evidence", "reference_source"):
        v = report.get(key)
        if isinstance(v, list) and v:
            return True
        if isinstance(v, dict) and v:
            return True
    return None


def _evidence_completeness_from_report(
    report: dict, agent_type: str | None,
) -> dict[str, Any]:
    """T3.2: compute evidence_completeness from actual report inspection."""
    required = _required_fields_for(agent_type)
    missing = _missing_top_level_fields(report, required)
    ui_status, ui_missing = _ui_evidence_status(report)
    return {
        "ui_evidence": ui_status,
        "ui_evidence_missing_fields": ui_missing,
        "citations": _citations_present(report),
        "required_count": len(required),
        "present_count": len(required) - len(missing),
        "missing_fields": missing,
    }


def _evidence_completeness_unknown(agent_type: str | None) -> dict[str, Any]:
    required = _required_fields_for(agent_type)
    return {
        "ui_evidence": None,
        "ui_evidence_missing_fields": [],
        "citations": None,
        "required_count": len(required),
        "present_count": None,
        "missing_fields": [],
    }


def _compute_evidence_completeness(
    artifact_paths: list[str], agent_type: str | None,
) -> dict[str, Any]:
    """T3.2: real measurement — replaces the previous None-only placeholder.

    Reads the first JSON artifact emitted by the just-completed agent and
    reports schema-required field presence + nested ui_evidence status.
    Fail-soft: any read/parse error returns the unknown payload so the
    trace hook never blocks observability.
    """
    if not artifact_paths:
        return _evidence_completeness_unknown(agent_type)
    report_path = _pick_json_artifact(artifact_paths)
    if report_path is None:
        return _evidence_completeness_unknown(agent_type)
    report = _read_report(report_path)
    if not isinstance(report, dict):
        return _evidence_completeness_unknown(agent_type)
    return _evidence_completeness_from_report(report, agent_type)


def _start_ts_from_bookmark(project_dir: Path, session_id: str | None) -> str | None:
    if not session_id:
        return None
    bookmark = project_dir / ".claude" / f"agent-bookmark-{session_id}.json"
    if not bookmark.exists():
        return None
    data = _try_load_json(bookmark)
    if not isinstance(data, dict):
        return None
    ts = data.get("start_ts") or data.get("started_at")
    return ts if isinstance(ts, str) and ts else None


def _duration_ms(start_ts: str | None, end_ts: str) -> int | None:
    if not start_ts:
        return None
    try:
        s = datetime.fromisoformat(start_ts.replace("Z", "+00:00"))
        e = datetime.fromisoformat(end_ts.replace("Z", "+00:00"))
        delta = (e - s).total_seconds() * 1000.0
        return int(delta) if delta >= 0 else None
    except Exception:
        return None


def _exit_status(tool_response: dict | None) -> str:
    if not isinstance(tool_response, dict):
        return "success"
    if tool_response.get("error") or tool_response.get("is_error"):
        return "error"
    return "success"


# ---------------------------------------------------------------------------
# Trace record assembly + write
# ---------------------------------------------------------------------------


def _build_record(
    *,
    session_id: str,
    cycle_id: int,
    stdin_ctx: dict,
    contract: dict | None,
    state: dict | None,
) -> dict[str, Any]:
    end_ts = _now_iso()
    start_ts = _start_ts_from_bookmark(_project_dir(), session_id)
    tool_response = _tool_response(stdin_ctx)
    agent_type = _agent_type(stdin_ctx)
    artifact_paths = _artifact_paths_from_response(tool_response)
    return {
        "ts_iso": end_ts,
        "session_id": session_id,
        "cycle_id": cycle_id,
        "agent_type": agent_type,
        "agent_id": _agent_id(),
        "step": _current_step(state),
        "role": agent_type,
        "mode": _mode_from_input(stdin_ctx),
        "pipeline_id": _pipeline_id_from(stdin_ctx, contract),
        "start_ts": start_ts,
        "end_ts": end_ts,
        "duration_ms": _duration_ms(start_ts, end_ts),
        "tool_call_count": _tool_call_count(tool_response),
        "estimated_tokens": _estimated_tokens(tool_response),
        "estimated_cost_usd": None,
        "artifact_paths": artifact_paths,
        "schema_status": "unchecked",
        "evidence_completeness": _compute_evidence_completeness(
            artifact_paths, agent_type
        ),
        "retry_count": 0,
        "exit_status": _exit_status(tool_response),
        "blocked_reason": None,
        "notes": None,
    }


def _trace_path(project_dir: Path, session_id: str, cycle_id: int) -> Path:
    return (
        project_dir / "docs" / "dev" / "overnight" / session_id /
        f"cycle-{cycle_id}" / "trace.jsonl"
    )


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)


def _pick_report_path(artifacts: list[str]) -> str | None:
    json_artifacts = [p for p in artifacts if isinstance(p, str) and p.endswith(".json")]
    if json_artifacts:
        return json_artifacts[0]
    if artifacts and isinstance(artifacts[0], str):
        return artifacts[0]
    return None


def _maybe_record_yield(
    record: dict[str, Any], session_id: str, cycle_id: int
) -> None:
    """If this Agent was a specialist, classify+record its report."""
    agent_type = record.get("agent_type")
    if agent_type not in _SPECIALIST_TYPES:
        return
    if classify_report is None or record_yield is None:
        return
    artifacts = record.get("artifact_paths") or []
    report_path = _pick_report_path(artifacts) if artifacts else None
    if not report_path:
        return
    try:
        classification = classify_report(report_path)
        record_yield(
            report_path, agent_type, session_id, cycle_id, classification, "active"
        )
    except Exception as exc:  # pragma: no cover - fail-soft
        sys.stderr.write(
            f"[posttool-overnight-trace] yield record failed: {exc}\n"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _resolve_contract(sid: str, cid: int) -> dict | None:
    if load_contract is None:
        return None
    try:
        return load_contract(sid, cid)
    except Exception:
        return None


def _process(stdin_ctx: dict) -> None:
    tool_name = stdin_ctx.get("tool_name") or ""
    if tool_name and tool_name != "Agent":
        return
    sid, cid, state = _resolve_session_cycle(stdin_ctx)
    if state is None or sid is None or cid is None:
        return
    contract = _resolve_contract(sid, cid)
    if contract is None:
        return
    record = _build_record(
        session_id=sid, cycle_id=cid, stdin_ctx=stdin_ctx,
        contract=contract, state=state,
    )
    _append_jsonl(_trace_path(_project_dir(), sid, cid), record)
    _maybe_record_yield(record, sid, cid)


def main() -> int:
    try:
        stdin_ctx = _read_stdin_json()
        if isinstance(stdin_ctx, dict):
            _process(stdin_ctx)
    except Exception as exc:  # pragma: no cover - fail-soft observability
        sys.stderr.write(
            f"[posttool-overnight-trace] fail-soft error: {exc}\n"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
