"""D25 (4): regression replays of defects already met, both settings.

R-P1, P1's fan-out wedge: one lane of a 2-lane /dev fan-out was dispatched from an earlier template
(its obligation unparseable, F7's shape, or no obligation block at all, F7b's) and left a report
dev-report.v2 refuses (dev.status needs_review); the compliant sibling lane stops in the same round,
while that report is on disk (tests/replay/faults.py `defer`: the faulted lane's stop comes after the
sibling's). The wedge was the sibling's stop blocked by the other lane's report in every round. Now:
the sibling's stop passes; the faulted lane's own stop is returned to it naming its own report, it
repairs at its next round, and the cycle reaches its terminal. Armed, G1 refuses the earlier
template at dispatch, so the lane never starts from it: the orchestrator's next round is the
declaring dispatch from the tree's template, and the sibling still stops with no block.
"""
from __future__ import annotations

import pytest

from tests.replay import suite
from tests.replay import test_faults as tf

SHAPES = {
    "F7": f"pretemplate@{tf.L1_DEV_DISPATCH}=defer;invalid@{tf.L1_DEV}=dev.status:needs_review",
    "F7b": f"noblock@{tf.L1_DEV_DISPATCH}=defer;invalid@{tf.L1_DEV}=dev.status:needs_review",
}


def key(shape: str, settings: str) -> str:
    return suite.replay_key(tf.FANOUT, settings, (("fault", SHAPES[shape]),), tag="~R-P1")


CASES = [pytest.param(shape, s, id=f"R-P1-{shape}-{s}", marks=pytest.mark.replay(key(shape, s), tf.FANOUT.cost))
         for shape in SHAPES for s in suite.SETTINGS]


def _dispatched(r, label: str) -> str:
    """The agent id the Agent call labelled `label` started (its PostToolUse result)."""
    for ev in tf.invocations(r):
        p = ev["payload"]
        if ev["event"] == "PostToolUse" and p.get("tool_name") == "Agent" and ev["label"] == label:
            return (p.get("tool_response") or {}).get("agentId")
    return ""


@pytest.mark.parametrize("shape,settings", CASES)
def test_fanout_wedge(replays, shape, settings):
    r = replays.get(key(shape, settings))
    assert not r.error and not r.summary.get("driver_error"), r.explain()
    assert not r.hook_errors, "a hook error:\n" + r.explain()
    sibling = _dispatched(r, "Step 10 [l2] Agent(dev)")
    assert sibling, "the sibling lane's dev never ran:\n" + r.explain()
    sib_stops = tf.stops(r, sibling)
    assert sib_stops and not any(s["blocked"] for s in sib_stops), \
        f"the compliant sibling's stop was blocked (the wedge): {sib_stops}\n" + r.explain()
    dispatch = next(f for f in tf.fault_records(r) if f.get("kind") in ("pretemplate", "noblock"))
    if dispatch.get("refused_at_dispatch"):
        tf._refused_at_dispatch(shape, r, dispatch)
    else:
        report = next(f for f in tf.fault_records(r) if f.get("path"))
        own = tf.stops(r, report["agent"])
        written = [i for i, a in tf.writers(r, report["path"]) if a == report["agent"]]
        # the shape happened: the sibling stopped after the faulted report was written, before its
        # writer's own first stop
        assert written and own and written[0] < sib_stops[0]["i"] < own[0]["i"], \
            f"the sibling did not stop while the faulted report was on disk: {written} {sib_stops} {own}"
        tf._returned_and_repaired(shape, r)
    assert r.reached(), "the pipeline did not reach its terminal:\n" + r.explain()
