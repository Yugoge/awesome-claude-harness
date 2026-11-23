"""The smoke driver (drivers/smoke.py), asserted. launch_cost.py replays it for its measurement and the artifact
check's shard jobs replay it, but nothing asserted how it ended. It runs one session: a prompt, ordinary main-agent
calls (one of which fails by design, `test -f CHANGELOG.md`), one foreground Explore dispatch and a Stop. The case
asserts: the replay ends (rc 0, no driver error); no block (the driver declares no deviation); no hook error; the
one failed call is the planned one; the launch differential is on and empty; the subagent ran its two calls; the
last hook event is a Stop no block touched.
"""
from __future__ import annotations

import pytest

from tests.replay import suite

SMOKE = suite.Scenario("smoke", "smoke", (), ("smoke",), 51)
KEY = suite.replay_key(SMOKE, "shipped")


@pytest.mark.replay(KEY, SMOKE.cost)
def test_smoke_driver_ends_with_no_block_and_its_one_planned_failure(replays):
    r = replays.get(KEY)
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    assert not r.blocks and not r.hook_errors, r.explain()
    assert [f["step"] for f in r.failed_calls] == ["main Bash failing"], r.failed_calls
    assert r.summary["launch_differential"]["on"] and r.summary["launch_differential"]["events"], r.summary
    assert r.summary["launch_differential"]["differences"] == 0, r.summary
    events = r.hook_events()
    labels = {e.get("label") for e in events}
    assert {"sub Read", "sub Grep", "main Agent(Explore)"} <= labels, sorted(l for l in labels if l)
    assert events and events[-1]["event"] == "Stop" and events[-1]["label"] == "Stop", events[-1]
