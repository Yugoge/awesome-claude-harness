"""Ways of the dev, dev-command and dev-overnight replay drivers that no other test file asserts the end of.

test_pipelines.py's compliant case asserts each driver's plain way (and /dev's qa-fail, fanout and question ways);
the artifact check's shard jobs replay every (driver, variant) but assert only the artifact relations. The ways here
had no asserting case: /dev ba-qa-fail (the BA-validation QA fails, BA is dispatched again), /dev fanout-qa-fail (a
fan-out cycle whose first lane's first QA fails), /dev formatter (the dev runs a formatter over a tracked file),
/dev-command qa-fail (the first final-verification QA fails) and /dev-overnight qa-fail (pipeline 0's first QA fails).
Each case asserts what test_clean_driver.py asserts: the replay ends (rc 0, no driver error); every gate block it meets
was passed by one of the driver's declared deviations (a compliant way meets none); no hook error and no failed call;
the launch differential is on and empty; the run reached its end (the terminal the driver recorded for each command
typed), and the last hook event is a Stop that no block touched.
"""
from __future__ import annotations

import pytest

from tests.replay import suite

WAYS = {
    "dev ba-qa-fail": suite.Scenario("/dev ba-qa-fail", "dev", (("variant", "ba-qa-fail"),), ("dev",), 322),
    "dev fanout-qa-fail": suite.Scenario("/dev fanout-qa-fail", "dev", (("variant", "fanout-qa-fail"),), ("dev",), 508),
    "dev formatter": suite.Scenario("/dev formatter", "dev", (("variant", "formatter"),), ("dev",), 310),
    "dev-command qa-fail": suite.Scenario("/dev-command qa-fail", "dev_command", (("variant", "qa-fail"),), ("dev-command",), 236),
    "dev-overnight qa-fail": suite.Scenario("/dev-overnight qa-fail", "overnight", (("variant", "qa-fail"),), ("dev-overnight",), 524),
}
KEYS = {w: suite.replay_key(s, "shipped") for w, s in WAYS.items()}
# The steps whose Bash call a way fails on purpose: the failing QA of a fan-out lane runs the lane's generated test.
FAILS_BY_DESIGN = {"dev fanout-qa-fail": {"agent:qa Bash pytest generated"}}
# The commands whose terminal is the end of a way. /dev-overnight qa-fail runs one cycle and the owner's /stop ends the
# session inside the window (drivers/overnight.py owner_stop): its "dev-overnight" terminal is false by design, "stop" is the end.
ENDS = {"dev-overnight qa-fail": ("stop",)}


@pytest.mark.parametrize("way", [pytest.param(w, id=w, marks=pytest.mark.replay(k, WAYS[w].cost)) for w, k in KEYS.items()])
def test_driver_way_ends_and_meets_only_its_declared_deviations(replays, way):
    r = replays.get(KEYS[way])
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    undeclared = [b for b in r.blocks if not b.get("passed_by_deviation")]
    assert not undeclared, "a block no declared deviation passes:\n" + r.explain()
    assert r.summary["blocks_passed"] == r.summary["blocks"] == r.summary["deviations"] == len(r.blocks), r.summary
    unplanned = [c for c in r.failed_calls if c["step"] not in FAILS_BY_DESIGN.get(way, ())]
    assert not r.hook_errors and not unplanned, r.explain()
    if way in FAILS_BY_DESIGN:
        assert len(unplanned) < len(r.failed_calls), "the QA that fails by design did not fail\n" + r.explain()
    assert r.summary["launch_differential"]["on"] and r.summary["launch_differential"]["events"], r.summary
    assert r.summary["launch_differential"]["differences"] == 0, r.summary
    ends = ENDS.get(way, WAYS[way].pipelines)
    assert all((r.terminal(p) or {}).get("reached") for p in ends), "the run did not reach its end:\n" + r.explain()
    events = r.hook_events()
    assert events and events[-1]["event"] == "Stop", [(e["event"], e.get("label")) for e in events[-3:]]
    assert not any(b["step"] == events[-1]["label"] for b in r.blocks), "the last Stop was blocked\n" + r.explain()
