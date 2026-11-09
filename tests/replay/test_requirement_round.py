"""P13-1: the requirement round in the replays (D28, D29, D32), acceptance A1-A8.

Each variant runs through the shipped settings (G1 and G2 block). The drivers assert what each one shows inside
the run (drivers/dev.py, dev_command.py, spec.py; drivers/_round.py): the refusal's text, the answer file's
answers equal to the replayed tool_response, the contract_refs and assumptions, two producer answers with
distinct q8, no refuted BA's option reaching the owner, Section 5 holding the answer bytes. This file holds each
run to its expected blocks, and only those, with no hook error and its terminal reached.
"""
from __future__ import annotations

import pytest

from tests.replay import suite

# (driver, variant, the steps the variant is expected to block at: label prefixes, in order)
CASES = [
    ("dev", "round", []),                                                      # A2
    ("dev", "round-unasked", ["Step 4c Agent(ba) before round 1 is asked"]),   # A3
    ("dev", "round-paraphrase", ["Step 4c Agent(ba) after a paraphrased round 1"]),
    ("dev", "round-broken", []),  # a malformed round 1 left by an interrupted run: its re-dispatch is not refused
    ("dev", "round-skip", []),                                                 # A4
    ("dev", "round-decline", []),
    ("dev", "round-afk", []),
    ("dev", "devquestion", ["Step 5 Agent(ba) before question 1", "Step 5 Agent(ba) before question 2"]),  # A5
    ("dev", "spec-round", []),                                                 # A6: /dev after /spec
    ("dev", "round-many", ["Step 4c Agent(ba) round r3 repeating an answered question"]),  # A7
    ("dev", "text-question", ["Stop with a question in text"]),                # A8
    ("dev", "panel-disagree", []),                                             # D32
    ("dev", "panel-refuted", ["Step 4a Agent(qa) panel QA offering a refuted option"]),
    ("spec", "round", ["Step 6 Agent(spec) before round 1 is asked"]),         # A6
    ("spec", "text-question", ["Stop with a question in text"]),               # A8
]
SCENARIOS = {(d, v): suite.Scenario(f"P13-1 {d} {v}", d, (("variant", v),), (d,), 110) for d, v, _ in CASES}


def _key(driver: str, variant: str) -> str:
    return suite.replay_key(SCENARIOS[(driver, variant)], "shipped")


@pytest.mark.parametrize("driver,variant,expected", [
    pytest.param(d, v, e, id=f"{d}-{v}", marks=pytest.mark.replay(_key(d, v), SCENARIOS[(d, v)].cost))
    for d, v, e in CASES])
def test_the_round_variant_blocks_only_where_expected(replays, driver, variant, expected):
    r = replays.get(_key(driver, variant))
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    steps = [b["step"] for b in r.blocks]
    assert len(steps) == len(expected) and all(s.startswith(e) for s, e in zip(steps, expected)), r.explain()
    assert not r.hook_errors and r.reached(), r.explain()
