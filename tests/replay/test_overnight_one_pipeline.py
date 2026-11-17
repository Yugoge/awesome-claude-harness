"""P4 A16: the 1-pipeline /dev-overnight cycle (drivers/overnight.py variant=one-pipeline), shipped and armed.

A16's bar for "arm-overnight, 1 pipeline": a compliant replay with the tree's settings and armed meets
0 false blocks. Here a block counts whether or not a declared deviation passed it (as in
test_pipelines.py: a compliant run needs none), the run has 0 hook errors, /dev-overnight reaches its
terminal (the Stop after end_time with the summary written), and the driver's own ending checks
(out/one-pipeline.json: one pipeline built, each per-pipeline dispatch once and returned, BA-QA and QA
pass, the TIME CHECK after the window, the session's end once retro and summary exist) all hold.
The artifact check replays this variant traced; this pins it in the replay suite, untraced.
"""
from __future__ import annotations

import json
import os

import pytest

from tests.replay import suite

# cost: its untraced wall seconds (drivers/overnight.py COST's note: 667 s on P2's working tree, the
# 10-minute window included).
ONE_PIPELINE = suite.Scenario("/dev-overnight 1 pipeline", "overnight", (("variant", "one-pipeline"),),
                              ("dev-overnight",), 670)


@pytest.mark.parametrize("key", [pytest.param(suite.replay_key(ONE_PIPELINE, s), id=s,
                                              marks=pytest.mark.replay(suite.replay_key(ONE_PIPELINE, s),
                                                                       ONE_PIPELINE.cost))
                                 for s in suite.SETTINGS])
def test_one_pipeline_cycle_meets_no_block(replays, key):
    r = replays.get(key)
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    assert not r.blocks, "the 1-pipeline cycle met a gate block:\n" + r.explain()
    assert not r.hook_errors, "the 1-pipeline cycle met a hook error:\n" + r.explain()
    assert r.reached(), "/dev-overnight did not reach its terminal:\n" + r.explain()
    with open(os.path.join(r.run_dir, "one-pipeline.json")) as fh:
        checks = json.load(fh)["checks"]
    assert checks and all(c["ok"] for c in checks), [c for c in checks if not c["ok"]]
