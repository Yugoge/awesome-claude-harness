"""Per-cycle closeout replay: print one cycle's Agent trace in order.

CLI:
    python3 closeout.py replay <session_id> <cycle_id>

The trace is ``docs/dev/overnight/<session_id>/cycle-<N>/trace.jsonl``, one
record per Agent call, appended by hooks/posttool-overnight-trace.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_LIB_DIR = Path(__file__).resolve().parent
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
