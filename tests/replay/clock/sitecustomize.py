"""The replay's clock for a re-run: Python started with this directory on PYTHONPATH and REPLAY_CLOCK_AT
set (an epoch, a float) reads a wall clock that starts at that time and runs at the real rate.

E1's differential (tests/replay/differential.py) re-runs a hook event after the whole replay, on its final
state. A hook that compares a recorded time with the clock (a grant's `expires_at`, 60 s after it was
written: hooks/lib/merge_grant.py) would decide by how long the replay took, so the differential re-runs a
unit whose intact run does not give its recorded decision with the clock set back to its event (as it cuts
the transcripts back to it). Only what Python reads is shifted: time.time / time.time_ns, datetime.now,
datetime.utcnow, datetime.today and date.today; a file's mtime, `date` and git keep the real clock.
Subprocesses inherit the environment, so Python they start reads the same clock.
"""
import datetime as _dt
import os
import time as _time

try:
    _AT = float(os.environ.get("REPLAY_CLOCK_AT", ""))
except ValueError:
    _AT = None

if _AT is not None:
    _real_time, _real_ns = _time.time, _time.time_ns
    _OFF = _AT - _real_time()
    if os.environ.get("REPLAY_CLOCK_OFF"):  # a child: the offset its parent computed, not a new start
        _OFF = float(os.environ["REPLAY_CLOCK_OFF"])
    os.environ["REPLAY_CLOCK_OFF"] = repr(_OFF)

    def _now() -> float:
        return _real_time() + _OFF

    _time.time = _now
    _time.time_ns = lambda: _real_ns() + int(_OFF * 1e9)

    class _datetime(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromtimestamp(_now(), tz)

        @classmethod
        def utcnow(cls):
            return cls.fromtimestamp(_now(), _dt.timezone.utc).replace(tzinfo=None)

        @classmethod
        def today(cls):
            return cls.fromtimestamp(_now())

    class _date(_dt.date):
        @classmethod
        def today(cls):
            return cls.fromtimestamp(_now())

    _dt.datetime, _dt.date = _datetime, _date
