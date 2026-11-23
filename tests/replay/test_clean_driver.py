"""/clean's replay driver (drivers/clean.py) in each way it runs, asserted: the replay ends (rc 0, no driver error),
every gate block it meets is one of the driver's declared deviations (drivers/clean.py DEVIATIONS: none other, none
undeclared), no hook error, no failed call, and the launch differential is on and empty.

Before this file only the artifact check's shard jobs replayed the driver and nothing asserted how it ended.
test_pipelines.py's compliant case cannot read it (it demands 0 blocks, and /clean's text meets six declared ones).
"The run reached its end" is the terminal the driver records (Replay.terminal: the /clean terminal, and for then=push
the /push terminal too), plus the cleaner's commit (its deviation fires at Step 16) and the last hook event, a Stop
with no block. A block counts as declared only when a deviation's step glob, hook and quote all match it. The three ways: gaps=bridged (the default; the text's two gaps bridged), gaps=strict (the text as written),
then=push (the owner types /push after /clean, played by drivers/push.py).
"""
from __future__ import annotations

import pytest

from tests.replay import suite
from tests.replay.drivers import clean

CLEANER_COMMIT = "agent:cleaner Bash commit"
WAYS = {
    "bridged": suite.Scenario("/clean bridged", "clean", (("gaps", "bridged"),), ("clean",), 220),
    "strict": suite.Scenario("/clean strict", "clean", (("gaps", "strict"),), ("clean",), 220),
    "then-push": suite.Scenario("/clean then /push", "clean", (("then", "push"),), ("clean", "push"), 260),
}
KEYS = {w: suite.replay_key(s, "shipped") for w, s in WAYS.items()}


def declared(block) -> bool:
    """Whether one of the driver's declared deviations is the one that passed this block."""
    return clean.declares(block)


def test_a_block_matches_only_its_own_deviation():
    """The pair is the step glob, the hook and the quote together: any one of them wrong, the block is undeclared."""
    own = next(b for b in ({"step": "agent:cleaner Bash commit", "hook": "hooks/pretool-git-privilege-guard.py",
                            "text": "BLOCKED: agent git commit - only the /commit wrapper"},))
    assert declared(own)
    assert not declared({**own, "step": "Step 3 Write context"})
    assert not declared({**own, "hook": "hooks/pretool-orchestrator-gate.py"})
    assert not declared({**own, "text": "BLOCKED: something else"})
    assert not declared({**own, "step": "Step 3 Write context", "hook": "hooks/pretool-orchestrator-gate.py",
                         "text": "Bash used consecutively beyond limit"})


@pytest.mark.parametrize("way", [pytest.param(w, marks=pytest.mark.replay(k, WAYS[w].cost)) for w, k in KEYS.items()])
def test_clean_driver_ends_and_meets_only_its_declared_deviations(replays, way):
    r = replays.get(KEYS[way])
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    assert r.blocks, "no block: the driver's deviations are declared for blocks the text meets\n" + r.explain()
    undeclared = [b for b in r.blocks if not b["passed_by_deviation"] or not declared(b)]
    assert not undeclared, "a block no declared deviation passes:\n" + r.explain()
    assert r.summary["blocks_passed"] == r.summary["blocks"] == r.summary["deviations"] == len(r.blocks), r.summary
    assert not r.hook_errors and not r.failed_calls, r.explain()
    assert r.summary["launch_differential"]["on"] and r.summary["launch_differential"]["events"], r.summary
    assert r.summary["launch_differential"]["differences"] == 0, r.summary
    assert any(b["step"] == CLEANER_COMMIT for b in r.blocks), "the run did not reach the cleaner's commit\n" + r.explain()
    assert r.reached(), "the run did not reach its end\n" + r.explain()
    events = r.hook_events()
    assert events and events[-1]["event"] == "Stop", [(e["event"], e.get("label")) for e in events[-3:]]
    assert not any(b["step"] == events[-1]["label"] for b in r.blocks), "the last Stop was blocked\n" + r.explain()
    if way == "then-push":
        assert events[-1]["label"] == "/push Stop", events[-1]["label"]
        assert any(e.get("label") == "/push Step 5 Bash execute-push" and e["event"] == "PostToolUse" for e in events)
        assert r.fact("before /push")["cleanup commit"], "the cleaner wrote no commit for /push to push"
