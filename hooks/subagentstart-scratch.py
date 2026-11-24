#!/usr/bin/env python3
"""SubagentStart: makes the starting subagent's own scratch directory, <session scratch directory>/<role>/<agent id>
(lib/locations.py session_scratch_dir; hooks/pretool-tool-policy.py judges it the agent's own), before its first call.
Prints nothing, never blocks, exits 0 on every path."""
import json, os, sys  # noqa: E401 -- the harness switch (hooks/lib/harness_switch.py): no harness hook runs while /harness off holds
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))
try:
    import harness_switch  # noqa: E402
    harness_switch.exit_if_off()
    import locations  # noqa: E402
    data = json.load(sys.stdin)
    own = locations.session_scratch_dir(data.get("session_id"), data.get("agent_type"), data.get("agent_id"))
    if own:
        os.makedirs(own, mode=0o700, exist_ok=True)
except Exception:  # a home without lib/, a payload without ids, a disk that refuses: the agent starts all the same
    pass
