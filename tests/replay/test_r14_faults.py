"""P5 A26 for R14: a fault replay of each /merge and /push refusal test_refusals.py does not reach.

Each replay (drivers/_r14.py) injects one fault at the step it names and plays commands/merge.md or
commands/push.md compliantly from there (drivers/merge.py, drivers/push.py): Step 3 with no grant and
with a blocked verdict, Step 4 with moved tips, a missing session id at /merge Step 1 and at /push Step 2,
and /push's blocked verdict at Step 5. D25's shape, for every case:

* the refusal is ONE AskUserQuestion naming the action that clears it (the text's own action,
  recommended), asked once, and the owner picks it;
* that action clears it with no other human step: the agent's own next steps where the action is the
  agent's (the analysis or the snapshot run again), or, where it is the owner's ("resolve the listed
  risks first"), his resolution in his terminal and his own command typed again;
* the command then reaches its terminal (merged into master / published on the origin), and the replay
  meets no gate block and no hook error.
"""
from __future__ import annotations

import os

import pytest

from tests.replay import suite

# case, the command typed, the refusal asked (step, action), the times the owner types the command,
# the cost (untraced wall seconds, for the CI split)
R14 = (
    ("merge-nogrant", "merge", ("Step 3", "re-run the analysis now"), 1, 45),
    ("merge-blocked", "merge", ("Step 3", "resolve the listed risks first"), 2, 60),
    ("merge-moved", "merge", ("Step 4", "re-run the analysis now"), 1, 45),
    ("merge-nosession", "merge", ("Step 1", "re-run the snapshot now"), 1, 40),
    ("push-nosession", "push", ("Step 2", "re-run the snapshot now"), 1, 60),
    ("push-blocked", "push", ("Step 5", "resolve the listed risks first"), 2, 90),
)
SCENARIOS = {c: suite.Scenario(f"R14 fault {c}", "_r14", (("case", c),), (cmd,), cost) for c, cmd, _a, _n, cost in R14}
CASES = [pytest.param(c, cmd, asked, typed, id=c,
                      marks=pytest.mark.replay(suite.replay_key(SCENARIOS[c], "shipped"), SCENARIOS[c].cost))
         for c, cmd, asked, typed, _cost in R14]


@pytest.mark.parametrize("case,cmd,asked,typed", CASES)
def test_a_refusal_is_cleared_by_the_action_it_names(replays, case, cmd, asked, typed):
    r = replays.get(suite.replay_key(SCENARIOS[case], "shipped"))
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    if case == "merge-nogrant":  # faults.py's own record (faults.json): the first grant Write not made
        injected = [(f["kind"], f["label"]) for f in suite._json(os.path.join(r.run_dir, "faults.json"), [])]
        assert injected == [("missing", "agent:merge-analyst Write grant")], injected
    else:
        injected = [f["value"]["case"] for f in r.facts if f.get("key") == "r14 fault"]
        assert injected == [case], injected
    refusals = [f["value"] for f in r.facts if f.get("key") == f"{cmd} refusal"]
    step, action = asked
    assert [(a["step"], a["action"], a["answer"]) for a in refusals] == [(step, action, action)], r.explain() + \
        f"\nrefusals asked: {refusals}"
    events = r.hook_events()
    questions = [ev["label"] for ev in events if ev["event"] == "PreToolUse" and ev.get("tool") == "AskUserQuestion"]
    prompts = [ev["label"] for ev in events if ev["event"] == "UserPromptSubmit"]
    assert len(questions) == 1, questions
    assert len(prompts) == typed, prompts
    assert not r.blocks, "a refusal's fault replay met a gate block:\n" + r.explain()
    assert not r.hook_errors, "a refusal's fault replay met a hook error:\n" + r.explain()
    assert r.reached(), r.explain()
