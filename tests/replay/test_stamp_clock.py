"""A replay's own stamps (pipeline.utc_now: the cut's and the stop's, the records' timestamps) are on the replay's clock:
the modeled one when a driver turned it on (Replay.model_clock), else the real one. Counted, never timed."""
from __future__ import annotations

import calendar
import time
from types import SimpleNamespace

from tests.replay import pipeline, replay as R


def _epoch(stamp: str) -> int:
    return calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ"))


def test_a_stamp_is_the_modeled_time_when_the_replay_has_a_clock():
    at = 1_700_000_000 + 7200  # two hours past a real-clock reading: a window end the model has passed
    R._CLOCK.append(SimpleNamespace(clock_at=at))
    try:
        assert _epoch(pipeline.utc_now()) == at
        assert R.now_iso().startswith(time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(at)))
    finally:
        R._CLOCK.pop()


def test_a_stamp_is_the_real_time_when_the_replay_runs_on_the_real_clock():
    assert not R._CLOCK
    assert _epoch(pipeline.utc_now()) == _epoch(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(R.clock_now())))
    assert abs(R.clock_now() - time.time()) < 5  # the real clock is what clock_now returns (a bound, not a duration)
