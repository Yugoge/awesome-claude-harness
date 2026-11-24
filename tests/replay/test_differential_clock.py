"""E1's differential re-runs a unit on the clock of its event, not on the clock at the end of the replay.

A hook that compares a recorded time with the clock (the merge-analyst grant's `expires_at`, 60 s after
it was written, read by hooks/lib/merge_grant.py at the merge.sh call) decided in the replay inside the
window; re-run by the differential after the whole replay, a slower machine had let the window pass, the
intact run blocked, and the unit was "reproduced False" and never measured. Here the event lies an hour
before the differential: the unit is measured all the same (its intact run gives the recorded decision,
the grant's removal changes it), whatever the time between the replay and the differential.

It needs a mount namespace the way the replays get theirs (root, or passwordless sudo: sandbox._priv,
suite.preconditions); without one it fails with the reason, never skips.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

import pytest

from tests.replay import differential as D
from tests.replay import suite

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = '''import json, sys
from datetime import datetime, timezone
try:
    g = json.load(open(sys.argv[1]))
except (OSError, ValueError):
    sys.exit(2)
exp = datetime.fromisoformat(g["expires_at"].replace("Z", "+00:00"))
sys.exit(2 if exp <= datetime.now(timezone.utc) else 0)
'''


def _require():
    missing = suite.preconditions()  # the replay folder's own check (its runner fixture, tests/replay/conftest.py)
    if missing:
        pytest.fail("the differential cannot run here: " + "; ".join(missing), pytrace=False)


def _iso(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _work(tmp, at: float | None) -> str:
    sb = os.path.join(tmp, "sb")
    lay = {k: os.path.join(sb, k) for k in ("home", "state", "project")}
    for d in lay.values():
        os.makedirs(d)
    shutil.copytree(os.path.join(HERE, "clock"), os.path.join(sb, "replay", "clock"))
    with open(os.path.join(sb, "hook.py"), "w") as fh:
        fh.write(HOOK)
    grant = os.path.join(lay["state"], "grant.json")
    event = at if at is not None else time.time()
    with open(grant, "w") as fh:
        json.dump({"expires_at": _iso(event + 60)}, fh)
    work = os.path.join(sb, "differential")
    os.makedirs(work)
    unit = {"seq": 1, "origin": "hooks/toy-grant-reader.py", "kind": "hook", "event": "PreToolUse",
            "command": f"{sys.executable} {os.path.join(sb, 'hook.py')} {grant}", "original": [0, "ok", ""],
            "reads": [{"raw": grant, "pattern": "<state>/grant.json", "comp": "hooks/toy-grant-reader.py"}]}
    inv = {"seq": 1, "event": "PreToolUse", "payload": {}, "transcripts": {}}
    if at is not None:
        inv["at"] = at
    for name, data in (("env.json", {"PATH": "/usr/bin:/bin"}), ("bash-env.json", {"PATH": "/usr/bin:/bin"})):
        with open(os.path.join(work, name), "w") as fh:
            json.dump(data, fh)
    with open(os.path.join(work, "invocations.jsonl"), "w") as fh:
        fh.write(json.dumps(inv) + "\n")
    path = os.path.join(work, "units.json")
    with open(path, "w") as fh:
        json.dump({"units": [unit], "schemas": {}, "workers": 1,
                   "layout": dict(lay, sb=sb, temp_dirs=[])}, fh)
    return path


def _result(units_path: str) -> dict:
    assert D.run_inner(units_path) == 0
    with open(os.path.join(os.path.dirname(units_path), "results.json")) as fh:
        return json.load(fh)["units"][0]


def test_unit_measured_on_its_events_clock(tmp_path):
    _require()
    rec = _result(_work(str(tmp_path), time.time() - 3600))  # the event an hour before the differential
    assert rec["reproduced"], rec
    assert rec["intact"] == [0, "ok", ""], rec
    assert [r["changed"] for r in rec["runs"] if r["how"] == "removed"] == [True], rec


def test_modeled_clock_advances_by_steps_not_by_elapsed_time():
    """A replay on the modeled clock (Replay.model_clock, the merge driver's): each process started reads
    the previous time plus CLOCK_STEP_S however long the machine took in between, never past the real clock."""
    from types import SimpleNamespace

    from tests.replay import replay as R
    start = time.time() - 3600
    rp = SimpleNamespace(clock_at=start, layout=SimpleNamespace(sb="/sb"))
    seen = []
    for _ in range(3):
        env = R.Replay.clock_env(rp, {"PATH": "/usr/bin"})
        seen.append(float(env["REPLAY_CLOCK_AT"]))
        time.sleep(0.3)  # a slow machine between two events
    assert seen == [start + R.CLOCK_STEP_S * n for n in (1, 2, 3)], seen
    assert env["PYTHONPATH"] == os.path.join("/sb", "replay", "clock")
    rp.clock_at = time.time() + 3600  # never ahead of the real clock (file mtimes stay real)
    assert float(R.Replay.clock_env(rp, {})["REPLAY_CLOCK_AT"]) <= time.time()
    real = SimpleNamespace(clock_at=None)
    assert R.Replay.clock_env(real, {"A": "1"}) == {"A": "1"}  # every other driver: the real clock


def test_clock_shift_reaches_python_children(tmp_path):
    at = 1_000_000_000.0
    env = {"PATH": "/usr/bin:/bin", "REPLAY_CLOCK_AT": repr(at), "PYTHONPATH": os.path.join(HERE, "clock")}
    code = ("import time, datetime, subprocess, sys; print(time.time()); "
            "print(datetime.datetime.now(datetime.timezone.utc).timestamp()); "
            "print(subprocess.run([sys.executable, '-c', 'import time; print(time.time())'], "
            "capture_output=True, text=True).stdout.strip())")
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
    for v in out.stdout.split():
        assert at <= float(v) < at + 30, out.stdout
    plain = subprocess.run([sys.executable, "-c", "import time; print(time.time())"],
                           env={"PATH": "/usr/bin:/bin", "PYTHONPATH": os.path.join(HERE, "clock")},
                           capture_output=True, text=True, check=True)
    assert abs(float(plain.stdout) - time.time()) < 30  # no REPLAY_CLOCK_AT: the real clock
