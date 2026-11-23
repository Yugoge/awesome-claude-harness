"""/spec's replay driver (drivers/spec.py) in the ways no other test file runs: variant omission, bad-split,
split-qa-fail and update, each asserted. Before this file only the artifact check's shard jobs replayed them and
nothing asserted how they ended (test_compliant_run reads variant plain; test_requirement_round, round and
text-question). Each case asserts: the replay ends (rc 0, no driver error); the blocks the run meets are exactly the
variant's own (the driver declares no deviation: bad-split meets one block, the spec subagent's stop on a split
that only `spec-verify.py --strict` rejects; the others meet none: omission leaves out qa's Role Mandate where the
monolith has no qa role annotation, the text has it record nothing and the strict check accepts that view; before the
text stopped recording omissions, the variant met a block at the subagent's stop); no hook error; the one failed call the driver
plans (the orchestrator view's machine-generated lines fail Step 6's verbatim check, which re-extracts that view);
the launch differential is on and empty; the variant happened (its own steps ran); the command reached its end,
the last hook event being a Stop no block touched (/spec records its terminal; /spec-update records none, so
the update way reads the end from the last Stop).
"""
from __future__ import annotations

import pytest

from tests.replay import suite

COST = {"omission": 202, "bad-split": 213, "split-qa-fail": 263, "update": 232}
WAYS = {v: suite.Scenario(f"/spec {v}", "spec", (("variant", v),), ("spec",), c) for v, c in COST.items()}
KEYS = {w: suite.replay_key(s, "shipped") for w, s in WAYS.items()}
PLANNED_FAILURE = "spec Bash verbatim orchestrator.md"
# What each variant must have done (labels of the driver's steps in the run's hook events), beyond ending.
DID = {"omission": ["Step 6 Agent(qa) split QA round 1 stop"],
       "bad-split": ["spec Bash strict verify", "Step 6 Agent(spec) stop"],
       "split-qa-fail": ["Step 6 Agent(spec) re-split round 1 stop", "Step 6 Agent(qa) split QA round 2 stop"],
       "update": ["/spec-update Cycle 2 appends", "/spec-update --update appends 5.4"]}


@pytest.mark.parametrize("way", [pytest.param(w, marks=pytest.mark.replay(k, WAYS[w].cost)) for w, k in KEYS.items()])
def test_spec_variant_ends_and_meets_only_its_own_blocks(replays, way):
    r = replays.get(KEYS[way])
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    if way == "bad-split":
        [b] = r.blocks
        assert (b["step"], b["event"]) == ("Step 6 Agent(spec) stop", "SubagentStop"), r.explain()
        assert b["hook"].endswith("subagentstop-producer-gate.py") and "spec_verify_strict_failed" in b["text"], r.explain()
    else:
        assert not r.blocks, "the variant meets no block:\n" + r.explain()
    if way == "omission":
        assert "spec Write mandate-omissions.json" not in {e.get("label") for e in r.hook_events()}, r.explain()
    assert not r.hook_errors, r.explain()
    assert [f["step"] for f in r.failed_calls] == [PLANNED_FAILURE], r.failed_calls
    assert r.summary["launch_differential"]["on"] and r.summary["launch_differential"]["events"], r.summary
    assert r.summary["launch_differential"]["differences"] == 0, r.summary
    events = r.hook_events()
    labels = {e.get("label") for e in events}
    for step in DID[way]:
        assert step in labels, f"the variant did not run {step!r}\n" + r.explain()
    assert events and events[-1]["event"] == "Stop", [(e["event"], e.get("label")) for e in events[-3:]]
    last = events[-1]["label"]
    assert not any(b["step"] == last for b in r.blocks), "the last Stop was blocked\n" + r.explain()
    if way == "update":
        assert last == "/spec-update --update Stop", last
    else:
        assert (r.terminal("spec") or {}).get("reached"), "/spec did not reach its terminal\n" + r.explain()
