#!/usr/bin/env python3
"""SubagentStop: the producer stop gate, one process for the checks on a producer's own artifacts.

The rules run in this order, each as its own hook would run alone (its switch, its
exemptions, its failure direction; hooks/lib/gate_runner.py):

1. subagentstop-codex-enforce.py: a cycle that asked for Codex finds this agent's
   Codex ledger;
2. subagentstop-e2e-enforce.py: a QA's report exists and states an accepted
   e2e_enforcement status;
2a. lib/aggregate_rebuild.py at_lane_stop, an observer: a dev lane of a fan-out stops and
   the canonical aggregate older than a lane report is rebuilt, whatever wrote the report;
3. subagentstop-artifact-contract-enforce.py (G2): every artifact the agent's own
   obligation declares exists, validates and carries its identity;
3a. subagentstop-lane-blockers.py: a dev lane whose report lists blocking issues is
   held once per dispatch, shown the list;
4. subagentstop-cp-enforce.py: the agent leaves no pending checkpoint in its own
   cp-state slot;
5. subagentstop-restart-track.py, an observer: the response evidence /restart reads,
   recorded whatever the rules above decided;
6. lib/lane_ledger.py end, a witness: on the stop that stands, the lane's record (which
   G2 read for the report's entries at dispatch start) is removed.

Every refusal is returned to this producer at its own stop; the reasons of all
refusing rules are reported together, once, with exit 2, so one round repairs them.

A QA's declared report that does not exist is refused by both the e2e rule (which
has no switch) and G2 (under CLAUDE_OBLIGATION_STOPGATE): when G2 states that path
absent, the e2e rule's line for the same path is left out of the report. Both still
refuse, and with G2 advisory or off the e2e rule states it alone, as before.
"""
from __future__ import annotations
import os, sys  # noqa: E401 -- the harness switch (hooks/lib/harness_switch.py): no harness hook runs while /harness off holds
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))
try:  # a hook copied without its lib/ (an old install) is on
    import harness_switch  # noqa: E402
    harness_switch.exit_if_off()
except ImportError:
    pass
finally:
    sys.path.pop(0)

import re
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parent
sys.path.insert(0, str(HOOKS))

from lib.gate_runner import OBSERVE, REFUSE, WITNESS, Outcome, Rule, main  # noqa: E402

RULES = [
    Rule("codex-ledger", str(HOOKS / "subagentstop-codex-enforce.py"), REFUSE),
    Rule("qa-e2e", str(HOOKS / "subagentstop-e2e-enforce.py"), REFUSE),
    Rule("lane-ledger", kind=OBSERVE, call="lib.lane_ledger:at_stop"),  # completes the report the next two read
    Rule("aggregate-rebuild", kind=OBSERVE, call="lib.aggregate_rebuild:at_lane_stop"),  # before G2, which reads it
    Rule("g2-artifact-contract", str(HOOKS / "subagentstop-artifact-contract-enforce.py"), REFUSE),
    Rule("lane-blockers", str(HOOKS / "subagentstop-lane-blockers.py"), REFUSE),
    Rule("cp-pending", str(HOOKS / "subagentstop-cp-enforce.py"), REFUSE),
    Rule("restart-track", str(HOOKS / "subagentstop-restart-track.py"), OBSERVE),
    # a background dispatch's end: what its return runs, on the stop the rules above let stand
    Rule("lane-ledger-end", kind=WITNESS, call="lib.lane_ledger:end"),  # the record lives until its dispatch ends
    Rule("dispatch-end", str(HOOKS / "posttool-dispatch-record.py"), WITNESS),
]

_E2E_ABSENT = re.compile(r"declared a qa-report\.v2 obligation \(task_id=[^)]*\) at (\S+) but no such file exists")


def one_reason(outcomes: list[Outcome]) -> None:
    by_name = {o.rule.name: o for o in outcomes}
    e2e, g2 = by_name.get("qa-e2e"), by_name.get("g2-artifact-contract")
    if not (e2e and g2 and e2e.refused and g2.refused):
        return
    found = _E2E_ABSENT.search(e2e.stderr)
    if found and f"  - {found.group(1)}: obligation-named artifact absent" in g2.stderr:
        e2e.superseded_by = g2.rule.name


if __name__ == "__main__":
    sys.exit(main(RULES, one_reason))
