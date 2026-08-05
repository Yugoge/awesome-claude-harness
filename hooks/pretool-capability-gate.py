#!/usr/bin/env python3
"""PreToolUse capability gate — DEFENSE-IN-DEPTH ONLY.

Blocks (exit 2) any protected-workflow activation route unless the host-capability
handshake published a fresh, binding-matched PASS for this session.

This gate is deliberately NOT the primary enforcement point. It is delivered by
the very mechanism it polices, so a host that silently no-ops PreToolUse also
no-ops this file. The primary, non-circular enforcement point is the in-process
consumer `hooks/lib/capability_state.evaluate_activation()`, invoked by
`scripts/capability-doctor-strict.py --route <route>` (the per-route preflight)
and by `scripts/doctor --strict` (the all-routes sweep) — neither of which
involves hook dispatch. See that module's docstring for the full callsite list
and for the one claim it does NOT make.

Two routes are permitted by design even with no handshake state: the human
consent escape hatches (/do, /allow), flagged in the manifest. Blocking them
would leave a human on an unprotected host with no way to authorise a repair.
Fail-closed must not mean fail-sealed.

Output contract: silent + exit 0 when the route is unprotected or the handshake
passes. On refusal, one JSON gate decision record on stderr, exit 2.
Exit codes: 0 = allow / not this gate's business; 2 = block.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# HUMAN CONSENT ESCAPE HATCHES, recognised BEFORE the capability library is
# imported and before any manifest is read. A recovery path that lives inside the
# failure domain it exists to recover from is not a recovery path: a corrupt
# library, an unreadable manifest or any internal error must not be able to take
# these two routes down with it. Kept in lockstep with the manifest's
# `human_consent_escape_hatch` flags and with capability_state's constant by a
# drift test in hooks/tests/test_capability_gate.py — this literal may not be
# edited alone.
ESCAPE_HATCH_COMMANDS = ("/do", "/allow")

# THE REPAIR FLOOR, as a pre-import literal for exactly the same reason as the
# hatches above: `hooks/lib/capability_state.py` is itself a bound artifact, so a
# floor declared only there cannot help in the one state where THAT file is what
# failed to load. Without this copy an unresolvable library refuses every route
# but the two hatches — and the hatches record consent, they do not perform the
# Edit that would repair the library. Kept in lockstep with capability_state's
# REPAIR_FLOOR_ROUTES by a drift test; this literal may not be edited alone, and
# it is CLOSED — asserted by set equality, never widened to admit whatever tool
# a repair happened to reach for.
REPAIR_FLOOR_TOOLS = ("Read", "Edit", "Write", "Bash", "Glob", "Grep")


def _is_repair_floor(payload: dict) -> bool:
    """True only for the six declared repair-floor tool routes.

    `classify_route()` maps every non-SlashCommand, non-Skill envelope to
    `tool:<tool_name>`, so exact `tool_name` membership here is exactly route
    membership there. A Skill or SlashCommand named like a floor tool carries
    tool_name "Skill"/"SlashCommand" and so cannot reach this branch.
    """
    return str(payload.get("tool_name") or "") in REPAIR_FLOOR_TOOLS


def _is_escape_hatch(payload: dict) -> bool:
    """True only for an exact, single-command /do or /allow SlashCommand call.

    Control characters are disqualifying: `/do\\n/dev` would otherwise classify on
    its first token and smuggle a protected command in behind an exempt one. Any
    such payload falls through to the full state-based evaluation instead.
    """
    if str(payload.get("tool_name") or "") != "SlashCommand":
        return False
    raw = str((payload.get("tool_input") or {}).get("command") or "")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in raw):
        return False
    parts = raw.strip().split()
    return bool(parts) and parts[0] in ESCAPE_HATCH_COMMANDS


def _load_capability_state():
    sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
    import capability_state as cs  # noqa: PLC0415 — deliberately lazy; see above
    return cs


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    # Checked first, on purpose. Everything below this line can fail; this cannot.
    if _is_escape_hatch(payload):
        return 0

    try:
        cs = _load_capability_state()
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
        return 2

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
