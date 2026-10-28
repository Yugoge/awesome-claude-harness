"""Per-cycle closeout: are the cycle contract's required_calls still pending?

Public API:
    has_pending_required_calls(session_id, cycle_id) -> bool

CLI:
    python3 closeout.py replay <session_id> <cycle_id>

HARD CUTOVER: when no cycle-contract.json exists, ``has_pending_required_calls``
returns False. Callers (stop-overnight-timelock.py) treat this as a no-op.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
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
    return 0


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="closeout", description="Cycle closeout / replay")
    sub = p.add_subparsers(dest="cmd")
    rep_p = sub.add_parser("replay", help="Print chronological trace")
    rep_p.add_argument("session_id")
    rep_p.add_argument("cycle_id", type=int)
    return p


def _main_cli(argv: list[str]) -> int:
    parser = _build_argparser()
    args = parser.parse_args(argv)
    if args.cmd == "replay":
        return _replay(args.session_id, args.cycle_id)
    parser.print_help()
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main_cli(sys.argv[1:]))
