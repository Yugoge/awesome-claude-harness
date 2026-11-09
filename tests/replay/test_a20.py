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
* the rerun without AskUserQuestion: /dev question again, its Step 5 question left unanswered in
  each form a session meets (pipeline.Orchestrator.ask's `ask` argument): `none`, a session that
  offers no AskUserQuestion (no call is made); `skip`, the dialog closed with no answer; `decline`,
  the call refused (an error tool_result, as a headless session's permission refusal). The
  orchestrator takes the question's `default` as an assumption and says so; the re-dispatched BA's
  prompt carries it in `Previous answers` and BA records it in its context (`clarification_answers`).
  The cycle completes with no block at all, a blocked Stop included, and asks nothing again.

The /dev gate's predicate is P3's disposition (scripts/resolve-dev-artifact-chain.py): the passing
Stops these cases end with wait for P3's merge.
"""
from __future__ import annotations

import glob
import json
import os

import pytest

from tests.replay import suite
from tests.replay.drivers import dev as devdrv

NOQA = suite.Scenario("/dev QA never dispatched (A20)", "dev", (("variant", "plain"), ("stop_before", "13")),
                      ("dev",), 100)
QUESTION = next(s for s in suite.COMPLIANT if s.name == "/dev clarify")
DEV = next(s for s in suite.COMPLIANT if s.name == "/dev singular")
FOREIGN = (("fault", "foreign@Step 14 Read *=docs/dev/qa-report-*.json"),)
NO_ANSWER = ("none", "skip", "decline")
QUESTION_DOC = devdrv.QUESTION  # the producer question BA writes in /dev question


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
    asked = [ev for ev in r.hook_events() if ev.get("event") == "PostToolUse"
             and ev.get("tool") == "AskUserQuestion"]
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


def _payloads(r, event: str, tool: str) -> list[dict]:
    """The payloads of the run's `event` hook invocations for `tool` (invocations.jsonl: what each hook saw)."""
    out = []
    with open(os.path.join(r.run_dir, "invocations.jsonl")) as fh:
        for line in fh:
            rec = json.loads(line)
            if rec.get("event") == event and rec["payload"].get("tool_name") == tool:
                out.append(dict(rec["payload"], label=rec.get("label")))
    return out


@pytest.mark.parametrize("form, key", [pytest.param(f, _key(QUESTION, (("ask", f),)), id=f,
                                                    marks=pytest.mark.replay(_key(QUESTION, (("ask", f),)), QUESTION.cost))
                                       for f in NO_ANSWER])
def test_a20_rerun_without_askuserquestion_completes_with_the_assumption_recorded(form, key, replays):
    r = replays.get(key)
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    asked = _payloads(r, "PreToolUse", "AskUserQuestion")
    assert len(asked) == (0 if form == "none" else 1), [a["label"] for a in asked]
    after = {ev.get("event") for ev in r.hook_events() if ev.get("tool") == "AskUserQuestion"}
    assert after == ({"PostToolUseFailure", "PreToolUse"} if form == "decline" else
                     {"PostToolUse", "PreToolUse"} if form == "skip" else set()), after
    q = QUESTION_DOC
    redispatch = [p for p in _payloads(r, "PreToolUse", "Agent")
                  if "Clarification round: 1" in (p["tool_input"].get("prompt") or "")]
    assert len(redispatch) == 1, [p["label"] for p in _payloads(r, "PreToolUse", "Agent")]
    prev = next(line for line in redispatch[0]["tool_input"]["prompt"].split("\n")
                if line.strip().startswith("Previous answers:"))
    entries = json.loads(prev.split("Previous answers:", 1)[1])
    assert [(e["question"], e["answer"]) for e in entries] == [(q["need"], q["default"])], prev
    assert "no answer" in entries[0].get("assumption", ""), prev
    context = [json.loads(p["tool_input"]["content"]) for p in _payloads(r, "PreToolUse", "Write")
               if p.get("agent_type") == "ba" and "/context-" in p["tool_input"]["file_path"]]
    assert context and context[-1].get("clarification_answers") == entries, context[-1:]
    said = [line for f in glob.glob(os.path.join(r.run_dir, "transcripts", "*", "*.jsonl")) for line in open(f)
            if "Assumption: " + q["default"] in line]
    assert said, "the main agent did not say which assumption it took"
    assert not r.blocks and not r.hook_errors and r.reached(), r.explain()
    stops = [ev for ev in r.hook_events() if ev.get("event") == "Stop"]
    assert len(stops) == 1, [ev.get("label") for ev in stops]
