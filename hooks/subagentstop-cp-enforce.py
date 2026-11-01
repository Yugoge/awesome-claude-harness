#!/usr/bin/env python3
# Description: SubagentStop hook for spec checkpoint enforcement (W6).
#
# MODE: blocking as shipped: settings.json's env sets CP_ENFORCE_MODE=block. Any
# other value, or none, is advisory: the hook exits 0 and never blocks.
#
# WHY SCOPED: a blocking SubagentStop hook that judged every running slot would
# block bystanders (a parallel agent, the /spec subagent whose Phase 2 registers
# slots for agents not yet dispatched). It judges only the stopping subagent's
# own slots, so the only stop it blocks is an agent leaving its own checkpoints
# pending; marking or waiving them (spec-check.py) always clears it.
#
# FAIL-SAFE: ANY error -> exit 0 (allow). Bounded filesystem scan, no network,
# no subprocess. The outer try/except guarantees a hook bug can never trap a
# subagent.
#
# Detection: scans $CLAUDE_PROJECT_DIR/.claude/specs/*/cp-state-*.json for the
# stopping subagent's own slots (agent_id = the stdin payload's agent_id, the id
# pretool-cp-checkin.py registered when it Read its cp-state file) that are
# running (hooks/lib/agent_resolver.py cp_state_running, the one rule role
# resolution also takes) AND have >=1 checkpoint still in state "pending". A
# slot another agent holds, or one the spec subagent registered for an agent
# not yet dispatched, never blocks this stop.
from __future__ import annotations

import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))


def main() -> int:
    from agent_resolver import cp_state_running  # inside main: an import error fails safe

    mode = (os.environ.get("CP_ENFORCE_MODE", "advisory") or "advisory").strip().lower()
    try:
        agent_id = (json.load(sys.stdin) or {}).get("agent_id")
    except Exception:
        agent_id = None
    if not agent_id:
        return 0  # the main agent's stop, or no id: no slot of its own

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
            if st.get("agent_id") != agent_id or not cp_state_running(st):
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

    if pending_hits and mode == "block":
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
