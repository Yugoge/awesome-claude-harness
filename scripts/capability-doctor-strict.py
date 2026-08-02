#!/usr/bin/env python3
"""`doctor --strict` implementation: fresh handshake + short compatibility report.

Two properties this file exists to guarantee:

  1. EVERY invocation starts a FRESH live-host handshake with a new nonce. A
     preseeded or cached PASS is never accepted as proof — it is overwritten by
     the PENDING that opens the fresh run, which is asserted, not assumed.
  2. It is an INDEPENDENT enforcement point. It reads and validates the state
     file in-process and never depends on hook dispatch, so it still refuses on a
     host that silently no-ops PreToolUse (and therefore no-ops the gate hook).

Brevity bound: the DEFAULT report is capped at 20 lines — one line per lifecycle
event (7), one aggregate verdict line, and actionable reasons only for FAILING
components. Full per-check detail moves behind --verbose; the information is
relocated, never lost.

Usage: capability-doctor-strict.py [--home <dir>] [--session-id <id>] [--verbose]
Exit codes: 0 = fresh handshake PASS; 1 = UNPROTECTED.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_HOME = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HOME / "hooks" / "lib"))
sys.path.insert(0, str(_HOME / "scripts"))

import capability_state as cs  # noqa: E402

MAX_DEFAULT_LINES = 20


def _component_reasons(state: dict, consumer_records: list[dict]) -> list[str]:
    out: list[str] = []
    binding = state.get("binding") or {}
    breason = cs.binding_failure(binding)
    if breason:
        out.append(f"binding: {breason}")
    elif not cs.binding_matches(binding, cs.canonical_binding(None)):
        out.append("binding: binding_mismatch — settings/VERSION/host build changed since the run")
    bad = [e for e in state.get("events", []) if e.get("outcome") != "PASS"]
    if bad:
        out.append(f"events: {len(bad)}/{len(cs.RELIED_UPON_EVENTS)} lifecycle probes not PASS "
                   f"({bad[0].get('failure_reason')})")
    deep = state.get("deep_checks") or {}
    baddeep = [n for n in cs.DEEP_CHECKS if (deep.get(n) or {}).get("status") != "pass"]
    if baddeep:
        out.append(f"deep-checks: {','.join(baddeep)} not pass")
    surface = state.get("status_surface") or {}
    if surface.get("status") != "observed":
        out.append(f"status-surface: {surface.get('reason') or surface.get('status')}")
    refused = [r for r in consumer_records if r.get("decision") == "REFUSE"]
    if refused:
        out.append(f"independent-consumer: {len(refused)} manifested route(s) refused "
                   f"({refused[0].get('failure_reason')})")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--home", default=None)
    ap.add_argument("--session-id", default=None)
    ap.add_argument("--verbose", action="store_true",
                    default=os.environ.get("STRICT_VERBOSE") == "1")
    ap.add_argument("--timeout", type=int, default=5)
    args = ap.parse_args(argv)

    home = cs.harness_home(args.home)
    session_id = (args.session_id or os.environ.get("CLAUDE_SESSION_ID")
                  or f"noninteractive-{os.getpid()}")
    state_file = cs.state_path(session_id)

    # Assert-not-assume: record whether a preseeded PASS existed, then run fresh
    # anyway. The fresh run's PENDING write is what actually invalidates it.
    preseeded, _ = cs.load_state(state_file)
    preseeded_status = (preseeded or {}).get("status")

    # The orchestrator's filename is hyphenated, so load it by path rather than
    # by import name.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "capability_handshake", home / "scripts" / "capability-handshake.py")
    hs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hs)

    state = hs.run_handshake(session_id, home, state_file, args.timeout)

    # INDEPENDENT consumer pass over every manifested route (no hook dispatch).
    manifest, merr = cs.load_manifest(home)
    consumer_records: list[dict] = []
    if not merr:
        for entry in manifest.get("routes", []):
            consumer_records.append(
                cs.evaluate_activation(entry.get("route", ""), home=home,
                                       session_id=session_id, state_file=state_file)
            )

    overall = state.get("overall")
    if args.verbose:
        print(json.dumps({
            "overall": overall,
            "failure_reason": state.get("failure_reason"),
            "fresh_run": {"run_id": state.get("run_id"), "nonce_prefix": str(state.get("nonce"))[:8],
                          "preseeded_status_ignored": preseeded_status},
            "binding": state.get("binding"),
            "events": state.get("events"),
            "deep_checks": state.get("deep_checks"),
            "status_surface": state.get("status_surface"),
            "independent_consumer": consumer_records,
        }, indent=1, sort_keys=True))
        return 0 if overall == "PASS" else 1

    lines: list[str] = []
    for ev in state.get("events", []):
        lines.append(f"{ev.get('event_label',''):<17}{ev.get('outcome','?'):<11}"
                     f"{ev.get('failure_reason') or ''}")
    b = state.get("binding") or {}
    lines.append(f"VERDICT {overall}  host={b.get('host_build')} harness={b.get('harness_version')}"
                 f"  reason={state.get('failure_reason') or 'none'}")
    lines.extend(_component_reasons(state, consumer_records))
    for line in lines[:MAX_DEFAULT_LINES]:
        print(line)
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
