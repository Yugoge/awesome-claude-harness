#!/usr/bin/env python3
# STUB: the Stop coordinator's coverage phase runs it, but its rule (spec-verify.py on the /spec split) is G2's at the spec subagent's own stop.
"""Stop hook (the /spec split's coverage), retired to a no-op.

It ran spec-verify.py on the views of the spec the /spec session last wrote, at
the orchestrator's Stop, and blocked that Stop below 100% coverage: a block that
landed on the orchestrator, which wrote no view. The rule moved into the spec
subagent's dispatch obligation (`spec_views`), which G2
(subagentstop-artifact-contract-enforce.py) checks at that subagent's own stop
with `spec-verify.py --strict` and returns to it (P1b row 8, Correction 9).
hooks/stop-workflow-coordinator.py still runs this file as its coverage phase,
and a running session runs the current hook files (D15), so the file stays as an
exit-0 stub that reads nothing and decides nothing: P5's coverage phase blocks
nothing."""
import sys

sys.exit(0)
