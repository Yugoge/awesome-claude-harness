"""The modeled clock when the replay lets time pass (Replay.advance_clock: overnight's idle until its window's end).

The model jumps to the time the replay names, at once, and the processes started after it read that time:
Python (tests/replay/clock/sitecustomize.py) and `date` named without a time of its own
(tests/replay/clock/bin/date, first on their PATH). A file the session's Write writes carries the modeled
time as its mtime, so a rule comparing it with a time the session recorded on the model (a dispatch's
`dispatched_at`) sees both on one clock after the jump. Without the model nothing changes.
"""
from __future__ import annotations

import os
import subprocess
import time
from types import SimpleNamespace

from tests.replay import replay as R

HERE = os.path.dirname(os.path.abspath(__file__))


def _rp(start: float):
    rp = SimpleNamespace(clock_at=start, clock_ahead=0.0, layout=SimpleNamespace(sb=os.path.dirname(HERE)))
    rp.clock_env = lambda env: R.Replay.clock_env(rp, env)
    return rp


def _sandboxed(env: dict) -> dict:
    # the sandbox's replay/ is this directory: point the env at it, not at <sb>/replay
    clock = os.path.join(HERE, "clock")
    return dict(env, PATH=os.path.join(clock, "bin") + os.pathsep + "/usr/bin:/bin", PYTHONPATH=clock)


def test_the_model_jumps_where_the_replay_lets_time_pass_and_the_processes_after_it_read_it():
    start = time.time() - 60
    rp = _rp(start)
    R.Replay.advance_clock(rp, start + 3600)  # the window's end, an hour ahead of the real clock
    env = _sandboxed(rp.clock_env({"PATH": "/usr/bin:/bin"}))
    at = float(env["REPLAY_CLOCK_AT"])
    assert start + 3600 <= at <= start + 3600 + 1, at
    py = subprocess.run(["python3", "-c", "import time; print(time.time())"], env=env, capture_output=True,
                        text=True, check=True).stdout
    sh = subprocess.run(["date", "+%s"], env=env, capture_output=True, text=True, check=True).stdout
    for v in (py, sh):
        assert abs(float(v) - at) < 30, (v, at)
    given = subprocess.run(["date", "-u", "-d", "@5", "+%s"], env=env, capture_output=True, text=True).stdout
    assert given.strip() == "5"  # a date with its own time is the real date's


def test_a_session_write_carries_the_modeled_time(tmp_path):
    p = tmp_path / "report.json"
    p.write_text("{}")
    rp = _rp(time.time() - 60)
    R.Replay.advance_clock(rp, rp.clock_at + 3600)
    R._stamp(rp, str(p))
    assert abs(os.path.getmtime(p) - rp.clock_at) < 1
    real = SimpleNamespace(clock_at=None)
    before = os.path.getmtime(p)
    R._stamp(real, str(p))  # no model: the file keeps its own mtime
    assert os.path.getmtime(p) == before


def test_an_isolated_python_reads_the_modeled_clock_too():
    """scripts/overnight-status.sh runs `python3 -I -` (the TIME CHECK): -I ignores PYTHONPATH, so without the
    clock's python3 on PATH it read the real clock while the rest of the replay read the model."""
    clock = os.path.join(HERE, "clock")
    env = {"PATH": os.path.join(clock, "bin") + os.pathsep + "/usr/bin:/bin", "PYTHONPATH": clock,
           "REPLAY_CLOCK_AT": "1000000000"}
    code = "import time; print(int(time.time()))\n"
    out = subprocess.run(["python3", "-I", "-"], input=code, env=env, capture_output=True, text=True, check=True).stdout
    assert 1000000000 <= int(out) < 1000000030, out
    plain = subprocess.run(["python3", "-I", "-"], input=code, env=dict(env, PATH="/usr/bin:/bin"),
                           capture_output=True, text=True, check=True).stdout
    assert abs(int(plain) - time.time()) < 30  # the real interpreter alone: the real clock (the defect shown)


def test_after_the_jump_the_model_steps_by_events_alone():
    """Counted, not timed: N processes started in a burst move the model by exactly N steps. A cap by the
    real time since the jump made it depend on how fast the burst ran (a fast machine ended earlier)."""
    rp = _rp(time.time() - 60)
    R.Replay.advance_clock(rp, rp.clock_at + 3600)
    to = rp.clock_at
    for _ in range(40):
        rp.clock_env({"PATH": "/usr/bin:/bin"})
    assert rp.clock_at == to + 40 * R.CLOCK_STEP_S, rp.clock_at - to


def test_the_model_starts_on_a_whole_minute_so_a_rounded_clock_time_does_not_follow_the_start():
    for second in (0.5, 7.0, 31.4, 59.9):
        rp = SimpleNamespace(clock_at=None, window=SimpleNamespace(start=1_800_000_000 + second))
        R.Replay.model_clock(rp)
        R._CLOCK.pop()
        assert rp.clock_at % 60 == 0 and 0 <= rp.window.start - rp.clock_at < 60, (second, rp.clock_at)
