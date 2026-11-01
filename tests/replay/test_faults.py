"""D25 (2): each injected fault goes back to its own producer, named by artifact and failing check,
and the next round passes with no human action except HX (the owner's /restart, /close, /commit).

Interrupted session and resume after a usage limit (F5, F5f, F6; tests/replay/recovery.py): the
session is cut while the dev subagent runs, after its Edit; the owner's /restart (HX) resumes that
same agent through commands/restart.md's recovery and finalizes it; the main agent then completes the
dev step with the resumed call (no replacement Agent call) and /dev reaches its terminal. Each runs
with the tree's settings ("shipped") and armed (G1-G3 block).
"""
from __future__ import annotations

import pytest

from tests.replay import recovery, suite


def _restart_cases(scenario: str, fault: str) -> list:
    scn = next(s for s in suite.COMPLIANT if s.name == scenario)
    keys = [suite.replay_key(scn, s, (("fault", fault),)) for s in suite.SETTINGS]
    return [pytest.param(k, id=s, marks=pytest.mark.replay(k, scn.cost * 3)) for k, s in zip(keys, suite.SETTINGS)]


@pytest.mark.parametrize("key", _restart_cases("/dev singular", "cut@agent:dev Edit toy/__init__.py"))
def test_f5_single_lane_cut_after_its_edit_resumed_by_restart(replays, key):
    recovery.assert_resumed_to_terminal(replays.get(key), lanes=1)


@pytest.mark.parametrize("key", _restart_cases("/dev 2-lane fan-out", "cut@agent:dev Edit toy/*"))
def test_f5f_both_lanes_cut_resumed_by_one_restart(replays, key):
    recovery.assert_resumed_to_terminal(replays.get(key), lanes=2)


@pytest.mark.parametrize("key", _restart_cases("/dev singular", "limit@agent:dev Edit toy/__init__.py"))
def test_f6_usage_limit_mid_subagent_resumed_by_restart(replays, key):
    recovery.assert_resumed_to_terminal(replays.get(key), lanes=1)
