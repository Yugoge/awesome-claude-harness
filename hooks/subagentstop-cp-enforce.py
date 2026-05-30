#!/usr/bin/env python3
# Description: SubagentStop hook for spec checkpoint enforcement (W6).
#
# MODE: ADVISORY by default (log-only). This hook ALWAYS exits 0 (never blocks a
# subagent exit) unless CP_ENFORCE_MODE=block is EXPLICITLY set in the hook env.
# When it detects a running spec cp-state with pending checkpoints, it appends an
# advisory record to ~/.claude/logs/cp-enforce-advisory.jsonl so the would-block
# events can be OBSERVED before any decision to enable real blocking.
#
# WHY ADVISORY-FIRST: a buggy *blocking* SubagentStop hook breaks EVERY subagent
# exit in every session (catastrophic blast radius), including the subagents you
# would need to fix it. So the default is observe-only; flipping to blocking
# (CP_ENFORCE_MODE=block) is a deliberate, separately-reviewed decision made AFTER
# the advisory log shows the detection is correct and low-false-positive.
#
# FAIL-SAFE: ANY error -> exit 0 (allow). Bounded filesystem scan, no network,
# no subprocess. The outer try/except guarantees a hook bug can never trap a
# subagent.
#
# Detection: scans $CLAUDE_PROJECT_DIR/.claude/specs/*/cp-state-*.json for files
# with is_running=true AND >=1 checkpoint still in state "pending".
from __future__ import annotations

import datetime
import glob
import json
import os
import sys


def _emit_advisory(records: list) -> None:
    """Best-effort append to the advisory log. Never affects exit."""
    try:
        logdir = os.path.expanduser("~/.claude/logs")
        os.makedirs(logdir, exist_ok=True)
        with open(os.path.join(logdir, "cp-enforce-advisory.jsonl"), "a", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    except Exception:
        pass


def main() -> int:
    mode = (os.environ.get("CP_ENFORCE_MODE", "advisory") or "advisory").strip().lower()

    # Read the SubagentStop payload (best-effort; never required).
    payload = {}
    try:
        raw = sys.stdin.read()
        if raw and raw.strip():
            payload = json.loads(raw)
    except Exception:
        payload = {}
    session_id = payload.get("session_id") or payload.get("sessionId") or ""
    agent_type = payload.get("agent_type") or payload.get("subagent_type") or ""

    project = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    specs_glob = os.path.join(project, ".claude", "specs", "*", "cp-state-*.json")

    pending_hits = []
    try:
        for path in glob.glob(specs_glob):
            try:
                with open(path, encoding="utf-8") as fh:
                    st = json.load(fh)
            except Exception:
                continue
            if not st.get("is_running"):
                continue
            cps = st.get("checkpoints") or []
            pend = [c.get("id") for c in cps if (c.get("state") or "pending") == "pending"]
            if pend:
                pending_hits.append({
                    "cp_state": os.path.relpath(path, project),
                    "spec_id": st.get("spec_id"),
                    "agent_type": st.get("agent_type"),
                    "agent_id": st.get("agent_id"),
                    "pending": pend,
                })
    except Exception:
        pending_hits = []

    if pending_hits:
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        _emit_advisory([{
            "ts": ts,
            "mode": mode,
            "event": "subagent_stop_pending_checkpoints",
            "session_id": session_id,
            "stopping_agent_type": agent_type,
            "would_block": pending_hits,
        }])
        if mode == "block":
            # DELIBERATE opt-in only (CP_ENFORCE_MODE=block). Exit 2 to block.
            sys.stderr.write(
                "subagentstop-cp-enforce: BLOCKED — subagent exiting with pending "
                "checkpoints: " + json.dumps(pending_hits) + "\n"
            )
            return 2

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        # Absolute fail-safe: a hook bug must NEVER trap a subagent exit.
        sys.exit(0)
