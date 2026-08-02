#!/usr/bin/env python3
"""PreToolUse capability gate — DEFENSE-IN-DEPTH ONLY.

Blocks (exit 2) any protected-workflow activation route unless the host-capability
handshake published a fresh, binding-matched PASS for this session.

This gate is deliberately NOT the primary enforcement point. It is delivered by
the very mechanism it polices, so a host that silently no-ops PreToolUse also
no-ops this file. The primary, non-circular enforcement point is the in-process
consumer `hooks/lib/capability_state.evaluate_activation()`, invoked from
protected-workflow entrypoints and from `scripts/doctor --strict`.

Output contract: silent + exit 0 when the route is unprotected or the handshake
passes. On refusal, one JSON gate decision record on stderr, exit 2.
Exit codes: 0 = allow / not this gate's business; 2 = block.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

try:
    import capability_state as cs
except Exception as exc:  # library unavailable -> fail closed, never silently open
    sys.stderr.write(
        json.dumps(
            {
                "component": "capability_gate",
                "decision": "REFUSE",
                "failure_reason": f"capability_gate_refused: library_unavailable ({exc})",
            }
        )
        + "\n"
    )
    sys.exit(2)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    tool_name = str(payload.get("tool_name") or "")
    session_id = str(payload.get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or "")
    route = cs.classify_route(tool_name, payload.get("tool_input") or {})

    record = cs.evaluate_activation(
        route,
        session_id=session_id,
        component="capability_gate",
    )
    if record["decision"] in ("PERMIT", "NOT_PROTECTED"):
        return 0

    sys.stderr.write(json.dumps(record) + "\n")
    sys.stderr.write(
        "UNPROTECTED HOST — the capability handshake has not published a valid fresh PASS "
        f"for this session, so the protected route {route!r} is blocked.\n"
        "Run: scripts/doctor --strict   (add --verbose for the full per-check report)\n"
    )
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # any internal error is fail-closed by construction
        sys.stderr.write(
            json.dumps(
                {
                    "component": "capability_gate",
                    "decision": "REFUSE",
                    "failure_reason": f"capability_gate_refused: internal_error ({exc})",
                }
            )
            + "\n"
        )
        sys.exit(2)
