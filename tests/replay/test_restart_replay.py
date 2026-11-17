"""The owner's /restart replayed (tests/replay/drivers/restart.py), shipped and armed (CLAUDE.md lesson 16).

A usage limit cuts a read-only subagent. Before any /restart, restart.md's prepare only says that
every resume send will be refused until /restart mints a grant (exit 0: it reads the grant as data),
and the exact resume message /restart would hand the cut agent is refused by the no-background hook,
the one decision on the grant. Then the owner's /restart: the
authorizer mints the grant, prepare, one SendMessage with the exact resume message per candidate,
the resumed agent's end, status with response evidence for every candidate, finalize. The same
message sent again after finalize consumed the grant is refused. The run meets no hook error, no
block but those two refusals, and the Stop that ends it passes. The same driver is a traced replay
of the artifact check (tests/test_artifact_graph.py).
"""
from __future__ import annotations

import pytest

from tests.replay import suite

RESTART = suite.Scenario("/restart after a usage limit", "restart", (), ("restart",), 40)
G1 = "hooks/pretool-block-background-tasks.py"
BLOCK = "[BLOCK] SendMessage refused for the orchestrator: "
NO_GRANT = "Restart authorization: no valid /restart capability for this session"
REFUSAL = (BLOCK + "the target is a /restart candidate, so only the exact recovery message reaches it\n"
           + NO_GRANT)


@pytest.mark.parametrize("key", [pytest.param(suite.replay_key(RESTART, s), id=s,
                                              marks=pytest.mark.replay(suite.replay_key(RESTART, s), RESTART.cost))
                                 for s in suite.SETTINGS])
def test_restart_without_grant_refused_then_recovered(replays, key):
    r = replays.get(key)
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    assert not r.hook_errors, r.explain()

    no_grant = r.fact("restart no-grant")
    assert no_grant and no_grant["prepare_ok"], f"prepare refused without a grant: {no_grant}"
    assert no_grant["notice"], f"prepare did not say the resume sends will be refused: {no_grant}"
    send = no_grant["send"]
    assert send["refused"] and send["text"].startswith(BLOCK) and NO_GRANT in send["text"], no_grant

    recovered = r.fact("restart")["recovered"]
    assert recovered and all(a["sent"] and a["resumed"] for a in recovered), recovered

    reuse = r.fact("restart reuse")
    assert reuse["refused"] and reuse["text"].startswith(REFUSAL), reuse
    assert reuse["same_message"], "the no-grant send was not the message /restart then sent"

    assert [(b["step"], b["hook"]) for b in r.blocks] == [("no grant SendMessage", G1), ("reuse SendMessage", G1)], \
        r.explain()
    assert r.reached(), r.explain()
