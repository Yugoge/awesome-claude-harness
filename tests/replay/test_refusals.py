"""P5 R14: each /merge and /push refusal is ONE AskUserQuestion in the turn, never an exit.

Each replay reaches one refusal of commands/merge.md or commands/push.md, played by its driver from
the text's Refusals rule (drivers/merge.py ask_refusal): the question offers the action the refusal
names, recommended, and the owner picks it. Every replay meets no gate block and no hook error, and
asks the refusal once; the conflict replay goes on from Step 1 after the owner's resolution and
reaches the merge.
"""
from __future__ import annotations

import pytest

from tests.replay import suite

REFUSALS = (
    (suite.Scenario("/merge self-merge", "merge", (("variant", "plain"), ("ref", "master")), ("merge",), 30),
     "merge refusal", "Step 1", "name the ref to merge", False),
    (suite.Scenario("/merge missing ref", "merge", (("variant", "plain"), ("ref", "no-such-ref")), ("merge",), 30),
     "merge refusal", "Step 1", "name the ref to merge", False),
    (suite.Scenario("/merge conflict", "merge", (("variant", "conflict"),), ("merge",), 90),
     "merge refusal", "Step 5", "I resolve the conflicts myself, then you continue", True),
    (suite.Scenario("/push no token", "push", (("after", "none"),), ("push",), 60),
     "push refusal", "Step 5", "run /commit first", False),
    (suite.Scenario("/push detached HEAD", "push", (("after", "none"), ("detached", "1")), ("push",), 40),
     "push refusal", "Step 2", "check out the branch to push", False),
)
CASES = [pytest.param(suite.replay_key(scn, "shipped"), key, step, action, reached, id=scn.name,
                      marks=pytest.mark.replay(suite.replay_key(scn, "shipped"), scn.cost))
         for scn, key, step, action, reached in REFUSALS]


@pytest.mark.parametrize("replay_key,fact,step,action,reached", CASES)
def test_a_refusal_is_one_question_with_its_named_action(replays, replay_key, fact, step, action, reached):
    r = replays.get(replay_key)
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    assert not r.blocks, "a refusal replay met a gate block:\n" + r.explain()
    assert not r.hook_errors, "a refusal replay met a hook error:\n" + r.explain()
    asked = [f["value"] for f in r.facts if f.get("key") == fact]
    assert [(a["step"], a["action"], a["answer"]) for a in asked] == [(step, action, action)], r.explain()
    assert r.reached() is reached, r.explain()
