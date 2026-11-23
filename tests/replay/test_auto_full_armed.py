"""Ways of the close, commit and clean replay drivers that no other test file asserts the end of (close --auto with one
parent, with two and with a task-id; commit full; clean under the armed setting in its three ways).

/close --auto (drivers/close.py variant=auto, run on its own: the cycle's task discovered as close_pending, the batch
walked, one rating question), /commit full (drivers/commit.py variant=full: route, append and commit-route in one cycle)
and /clean under the armed setting (test_clean_driver.py runs the driver's three ways under the shipped setting only).
test_pipelines.py's compliant /commit scenario walks close --auto inside a commit replay, but asserts no more than
"no block, no hook error, terminal reached"; the artifact check's shard jobs replay close auto and commit full and
assert only the artifact relations.
Each case asserts what test_clean_driver.py asserts: the replay ends (rc 0, no driver error); every block it meets was
passed by one of the driver's declared deviations (a compliant way meets none); no hook error; no failed call but the
ones the way plans; the launch differential is on and empty; the run reached its end (the terminal the driver recorded
for each command typed, /clean's included, and for the /clean ways the cleaner's commit step too); the last hook event is a
Stop that no block touched.
"""
from __future__ import annotations

import pytest

from tests.replay import suite
from tests.replay.drivers import clean

CLEANER_COMMIT = "agent:cleaner Bash commit"
WAYS = {
    "close auto": (suite.Scenario("/close --auto", "close", (("variant", "auto"),), ("dev", "close"), 462), "shipped"),
    "close auto two parents": (suite.Scenario("/close --auto two", "close", (("variant", "auto"), ("parents", "2")), ("dev", "close"), 700), "shipped"),
    "close auto-task": (suite.Scenario("/close --auto task", "close", (("variant", "auto-task"),), ("dev", "close"), 462), "shipped"),
    "commit full": (suite.Scenario("/commit full", "commit", (("variant", "full"),), ("dev", "close", "commit"), 796), "shipped"),
    "clean bridged armed": (suite.Scenario("/clean bridged", "clean", (("gaps", "bridged"),), ("clean",), 220), "armed"),
    "clean strict armed": (suite.Scenario("/clean strict", "clean", (("gaps", "strict"),), ("clean",), 220), "armed"),
    "clean then-push armed": (suite.Scenario("/clean then /push", "clean", (("then", "push"),), ("clean", "push"), 260), "armed"),
}
KEYS = {w: suite.replay_key(s, st) for w, (s, st) in WAYS.items()}
# The steps whose call a way fails on purpose (none known: a way listed here is one whose run showed one).
FAILS_BY_DESIGN: dict = {}
# /clean's blocks are its declared deviations and must be some; the others meet none.
BLOCKS_PLANNED = {w for w in WAYS if w.startswith("clean")}


def declared(block) -> bool:
    return clean.declares(block)


@pytest.mark.parametrize("way", [pytest.param(w, id=w.replace(" ", "-"), marks=pytest.mark.replay(k, WAYS[w][0].cost)) for w, k in KEYS.items()])
def test_way_ends_and_meets_only_its_declared_deviations(replays, way):
    scn = WAYS[way][0]
    r = replays.get(KEYS[way])
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    undeclared = [b for b in r.blocks if not b.get("passed_by_deviation") or (way in BLOCKS_PLANNED and not declared(b))]
    assert not undeclared, "a block no declared deviation passes:\n" + r.explain()
    if way in BLOCKS_PLANNED:
        assert r.blocks, "no block: the driver's deviations are declared for blocks the text meets\n" + r.explain()
    assert r.summary["blocks_passed"] == r.summary["blocks"] == r.summary["deviations"] == len(r.blocks), r.summary
    unplanned = [c for c in r.failed_calls if c["step"] not in FAILS_BY_DESIGN.get(way, ())]
    assert not r.hook_errors and not unplanned, r.explain()
    assert r.summary["launch_differential"]["on"] and r.summary["launch_differential"]["events"], r.summary
    assert r.summary["launch_differential"]["differences"] == 0, r.summary
    events = r.hook_events()
    assert events and events[-1]["event"] == "Stop", [(e["event"], e.get("label")) for e in events[-3:]]
    assert not any(b["step"] == events[-1]["label"] for b in r.blocks), "the last Stop was blocked\n" + r.explain()
    if way in BLOCKS_PLANNED:
        assert any(b["step"] == CLEANER_COMMIT for b in r.blocks), "the run did not reach the cleaner's commit\n" + r.explain()
    assert all((r.terminal(p) or {}).get("reached") for p in scn.pipelines), "the run did not reach its end:\n" + r.explain()
    if way == "clean then-push armed":
        assert events[-1]["label"] == "/push Stop", events[-1]["label"]
        assert any(e.get("label") == "/push Step 5 Bash execute-push" and e["event"] == "PostToolUse" for e in events)
        assert r.fact("before /push")["cleanup commit"], "the cleaner wrote no commit for /push to push"
    if way == "close auto two parents":
        assert r.fact("close --auto parents") == 2, r.fact("close --auto parents")
    if way == "close auto-task":
        c = r.fact("close --auto conflict")
        assert c["line"].startswith("NO_TARGET: --auto cannot take <task>") and not c["still_blocked"], c
        assert r.fact("close --auto parents") is None, "the conflict ran the discovery"
