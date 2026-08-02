#!/usr/bin/env python3
"""Nonce-bound lifecycle canary for the host-capability handshake.

Registered once per relied-upon lifecycle event, each registration carrying its
own event label as argv[1]. The per-event nonce it emits is therefore bound to
exactly ONE lifecycle-event key, which is what lets the handshake establish event
identity even on a host that does not supply `hook_event_name` on the envelope.

The canary is observational only: it NEVER blocks and always exits 0, so a
mis-registration can never wedge a session. Enforcement lives in the gate and in
the in-process consumer, never here.

Usage: capability-canary.py <EventLabel>
Exit codes: 0 always (observational canary; must never block a session).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))


def main() -> int:
    try:
        import capability_state as cs
    except Exception:
        return 0

    event_label = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    session_id = str(payload.get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or "")
    try:
        probe_file = cs.state_dir() / f"probe-{cs.state_path(session_id).stem}.json"
        probe = json.loads(probe_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0  # no active probe run — nothing to record

    event_nonce = (probe.get("event_nonces") or {}).get(event_label)
    if not event_nonce:
        return 0

    # host_receipt: verified-core fields required; tier-3 fields recorded if
    # present and EXPLICITLY marked absent otherwise, never silently omitted.
    receipt = {f: payload.get(f) for f in cs.RECEIPT_CORE_FIELDS}
    for f in cs.RECEIPT_TIER3_FIELDS:
        receipt[f] = payload.get(f, cs.ABSENT) if payload.get(f) is not None else cs.ABSENT

    record = {
        "event_label": event_label,
        "nonce": event_nonce,
        "run_id": probe.get("run_id"),
        "host_receipt": receipt,
        "observed_at": cs.now_iso(),
        "argv_event_key": event_label,
    }
    try:
        out = cs.state_dir() / f"receipts-{probe.get('run_id')}.jsonl"
        with open(out, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
        os.chmod(out, 0o600)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
