"""The owner's /restart replayed (tests/replay/drivers/restart.py), shipped and armed (CLAUDE.md lesson 16).

A usage limit cuts a read-only subagent. Before any /restart, restart.md's prepare says the grant is no
permission (exit 0: it reads the grant as data), and the exact resume message /restart would hand the cut
agent is not refused: a send to an own subagent is judged as a dispatch of its type
(hooks/lib/send_policy.py). Then the owner's /restart: the authorizer mints the grant and hands over the
prepared recovery set (no prepare call follows), one SendMessage with the exact resume message per
candidate, the resumed agent's end; the hooks finalize (restart.md step 4 runs nothing). The same message
sent again afterwards is judged the same way. The run meets no hook error and no block, and the Stop that
ends it passes. The same driver is a traced replay
of the artifact check (tests/test_artifact_graph.py).
"""
from __future__ import annotations

import pytest

from tests.replay import suite

RESTART = suite.Scenario("/restart after a usage limit", "restart", (), ("restart",), 40)


@pytest.mark.parametrize("key", [pytest.param(suite.replay_key(RESTART, s), id=s,
                                              marks=pytest.mark.replay(suite.replay_key(RESTART, s), RESTART.cost))
                                 for s in suite.SETTINGS])
def test_restart_without_grant_refused_then_recovered(replays, key):
    r = replays.get(key)
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    assert not r.hook_errors, r.explain()

    no_grant = r.fact("restart no-grant")
    assert no_grant and no_grant["prepare_ok"], f"prepare refused without a grant: {no_grant}"
    assert no_grant["notice"], f"prepare did not say the grant is no permission: {no_grant}"
    assert not no_grant["send"]["refused"], no_grant  # a send to an own subagent is judged as its dispatch

    assert r.fact("restart set") == {"handed_over": True}, "the typed /restart's issuer prepared no set"
    recovered = r.fact("restart")["recovered"]
    assert recovered and all(a["sent"] and a["resumed"] for a in recovered), recovered

    reuse = r.fact("restart reuse")
    assert not reuse["refused"], reuse
    assert reuse["same_message"], "the no-grant send was not the message /restart then sent"

    assert [(b["step"], b["hook"]) for b in r.blocks] == [], r.explain()
    assert r.reached(), r.explain()
