"""P5 A20: the Stop gate armed in the replays.

Every compliant scenario runs with the gate blocking: test_pipelines.py's armed settings set
CLAUDE_COMMAND_GATE=block (tests/replay/sandbox.py ARM, test-only), and since P5-d the tree's own
settings.json blocks through hooks/stop-launch.py too, so its shipped runs are armed as well. This
file adds the variants A20 names, armed:

* QA never dispatched: /dev plain whose orchestrator ends its turn before Step 13 (the QA dispatch),
  claiming the cycle done (drivers/dev.py `stop_before=13`). That Stop is blocked by the Stop gate,
  naming the command and the missing QA report; the cycle then dispatches QA, and its final Stop
  passes with no other block.
* a question round trip: /dev question (BA's producer question relayed with one AskUserQuestion
  inside the turn): the cycle completes with no blocked Stop between (no Stop at all before its end).
* a main-agent producer write: /dev plain whose main agent itself edits the QA report QA wrote
  (faults.py `foreign`): the D8 deny of pretool-tool-policy.py refuses it, and the cycle completes
  with no other block.

The /dev gate's predicate is P3's disposition (scripts/resolve-dev-artifact-chain.py): the passing
Stops these cases end with wait for P3's merge.
"""
from __future__ import annotations

import json
import os

import pytest

from tests.replay import suite

NOQA = suite.Scenario("/dev QA never dispatched (A20)", "dev", (("variant", "plain"), ("stop_before", "13")),
                      ("dev",), 100)
QUESTION = next(s for s in suite.COMPLIANT if s.name == "/dev clarify")
DEV = next(s for s in suite.COMPLIANT if s.name == "/dev singular")
FOREIGN = (("fault", "foreign@Step 14 Read *=docs/dev/qa-report-*.json"),)


def _key(scn, faults=()):
    return suite.replay_key(scn, "armed", faults)


@pytest.mark.replay(_key(NOQA), NOQA.cost)
def test_a20_qa_never_dispatched_is_held_until_qa_passes(replays):
    r = replays.get(_key(NOQA))
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    term = r.terminal("dev") or {}
    early = term.get("early_stops") or []
    assert len(early) == 1 and early[0]["blocked"] == ["hooks/stop-launch.py"], term
    text = early[0]["text"][0]
    assert text.startswith("COMMAND_GATE /dev: not complete") and "qa-report" in text, text
    assert "AWAITING_INPUT" not in text and "/stop" not in text
    assert [b["step"] for b in r.blocks] == ["Stop before Step 13"], r.explain()
    assert not r.hook_errors and r.reached(), r.explain()


@pytest.mark.replay(_key(QUESTION), QUESTION.cost)
def test_a20_a_question_round_trip_completes_with_no_blocked_stop(replays):
    r = replays.get(_key(QUESTION))
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    # the producer question's relay (Step 5); P13-1's requirement round asks round 1 before it (Step 4b)
    asked = [ev for ev in r.hook_events() if ev.get("event") == "PostToolUse"
             and ev.get("tool") == "AskUserQuestion" and str(ev.get("label", "")).startswith("Step 5")]
    assert len(asked) == 1, [ev.get("label") for ev in r.hook_events()]
    assert not r.blocks and not r.hook_errors and r.reached(), r.explain()


@pytest.mark.replay(_key(DEV, FOREIGN), DEV.cost)
def test_a20_a_main_agent_producer_write_is_denied_and_the_cycle_completes(replays):
    r = replays.get(_key(DEV, FOREIGN))
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    with open(os.path.join(r.run_dir, "faults.json")) as fh:
        done = [f for f in json.load(fh) if f.get("kind") == "foreign"]
    assert len(done) == 1 and done[0]["denied"] and done[0]["hooks"] == ["hooks/pretool-tool-policy.py"], done
    assert done[0]["path"].startswith("docs/dev/qa-report-"), done
    denied = [b for b in r.blocks if b["step"].startswith("foreign ")]
    assert len(denied) == 1 and "(D8)" in (denied[0].get("text") or ""), r.explain()
    assert len(r.blocks) == 1 and not r.hook_errors and r.reached(), r.explain()
