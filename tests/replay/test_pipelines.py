"""D25 (1): a compliant run of each of the ten pipelines meets 0 gate blocks and 0 hook errors and
reaches its terminal, with the tree's settings ("shipped") and armed (G1-G3 block).

Each scenario is one of P1b's drivers (tests/replay/drivers/) following the tree's own command and
agent text (suite.COMPLIANT). A block counts whether or not a driver's declared deviation passed it:
a compliant run needs none. A hook error is any hook exiting other than 0 or 2, timing out, printing
a Python traceback or GATE_ERROR / GATE_FAULT, or a connection the proxy guard counted. The terminal
is what the driver recorded for each command the scenario typed (Replay.terminal): /spec the spec
written; /dev, /redev, /dev-command the completion step's resolver passing; /dev-overnight the Stop
after end_time with the summary written; /do the do-report completed; /close the close report's
last line `CLOSE: YES ...`; /commit the cycle's commit on HEAD with nothing of it left in
`git status`; /merge the topic commit reachable from the default branch; /push the bare origin's
branch equal to HEAD; and the Stop that ends each with no block.
"""
from __future__ import annotations

import pytest

from tests.replay import suite

CASES = [pytest.param(suite.replay_key(scn, s), id=f"{scn.name}-{s}",
                      marks=pytest.mark.replay(suite.replay_key(scn, s), scn.cost))
         for scn in suite.COMPLIANT for s in suite.SETTINGS]


def test_every_pipeline_has_a_compliant_scenario():
    covered = {p for scn in suite.COMPLIANT for p in scn.pipelines}
    assert set(suite.TEN) <= covered, f"no compliant scenario types {sorted(set(suite.TEN) - covered)}"


@pytest.mark.parametrize("key", CASES)
def test_compliant_run(replays, key):
    r = replays.get(key)
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    assert not r.blocks, "a compliant run met a gate block:\n" + r.explain()
    assert not r.hook_errors, "a compliant run met a hook error:\n" + r.explain()
    assert r.reached(), "a pipeline did not reach its terminal:\n" + r.explain()
