"""/commit lands its commit while the system temp volume is full (drivers/commit.py, driver argument tmp=full).

The replay's private /tmp is a 64 KiB tmpfs with no block left (tests/replay/sandbox.py, REPLAY_TMP=full);
/dev, /close and /commit run as the tree's texts spell them. The changelog-analyst writes its message in its
drafts directory under the session root and takes its fd-9 lock under the state root (agents/changelog-analyst.md
Rule CP-5), neither in /tmp, so the commit lands, the push-gate token is written, and the run reaches its
terminal with no hook error.
"""
from __future__ import annotations

import pytest

from tests.replay import suite

FULL = suite.Scenario("/commit, /tmp full", "commit", (("variant", "plain"), ("tmp", "full")),
                      ("dev", "close", "commit"), 200)
KEY = suite.replay_key(FULL, "armed")


@pytest.mark.replay(KEY, FULL.cost)
def test_the_commit_lands_with_the_system_temp_volume_full(replays):
    r = replays.get(KEY)
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    done = r.fact("commit")
    assert done and done["commit_status"] == "committed" and done["landed"], done
    assert not r.hook_errors, r.explain()
    assert r.reached(), r.explain()
