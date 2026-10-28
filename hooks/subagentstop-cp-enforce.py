#!/usr/bin/env python3
# Description: SubagentStop hook for spec checkpoint enforcement (W6).
#
# MODE: ADVISORY by default. This hook ALWAYS exits 0 (never blocks a
# subagent exit) unless CP_ENFORCE_MODE=block is EXPLICITLY set in the hook env.
#
# WHY ADVISORY-FIRST: a buggy *blocking* SubagentStop hook breaks EVERY subagent
# exit in every session (catastrophic blast radius), including the subagents you
# would need to fix it. So the default never blocks; flipping to blocking
# (CP_ENFORCE_MODE=block) is a deliberate, separately-reviewed decision.
#
# FAIL-SAFE: ANY error -> exit 0 (allow). Bounded filesystem scan, no network,
# no subprocess. The outer try/except guarantees a hook bug can never trap a
# subagent.
#
# Detection: scans $CLAUDE_PROJECT_DIR/.claude/specs/*/cp-state-*.json for files
# with is_running=true AND >=1 checkpoint still in state "pending".
from __future__ import annotations

import glob
import json
import os
import sys


def main() -> int:
    mode = (os.environ.get("CP_ENFORCE_MODE", "advisory") or "advisory").strip().lower()

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
