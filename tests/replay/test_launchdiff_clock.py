"""The launch differential re-runs each hook at the time of its event, on a replay that models the clock.

A driver on the modeled clock (Replay.model_clock) has the launcher's hooks read the model (replay/clock),
which trails the real clock (or, after Replay.advance_clock, runs ahead of it). The launch differential runs
the same hooks again as their own processes; on the real clock a hook that decides by time (a grant's 60 s
expiry, the overnight window) answered differently there, and the replay failed though nothing was wrong.
Now both runs get the event's env and its time. A driver on the real clock is unchanged; a real difference is
still a difference.
"""
from __future__ import annotations

import json

from tests.replay import hookrun, launchdiff, replay as rpl


class _Session:
    sid, tdir = "s", "/nonexistent"

    @staticmethod
    def base(event, agent):
        return {"session_id": "s"}


class _Out:
    def __init__(self):
        self.lines = []

    def write(self, text):
        self.lines.append(text)

    def flush(self):
        pass


def _fire(monkeypatch, tmp_path, modeled):
    """Replay.fire for one event whose launcher has one hook; returns (env of the launcher's run, env of the
    own-process run, clock handed to it, the event's recorded "at")."""
    rp = object.__new__(rpl.Replay)
    lay = type("L", (), {"project": str(tmp_path), "sb": str(tmp_path), "harness": str(tmp_path)})
    rp.__dict__.update(layout=lay, settings={}, parallel=False, env={"PATH": "/usr/bin", "PYTHONPATH": "/p"},
                       clock_at=None, clock_ahead=0.0, launch_differential=True, launch_diffs=[],
                       launch_events=0, n_events=0, n_runs=0, event_names=set(), hook_errors=[], _seq=0,
                       _inv=_Out(), _log=_Out(), window=type("W", (), {"start": 1000.0}))
    rp.mark = lambda kind, value: None
    if modeled:
        rp.model_clock()
    seen = {}
    monkeypatch.setattr(hookrun, "select", lambda settings, event, payload: [{"hook": "hooks/x-launch.py"}])
    monkeypatch.setattr(launchdiff, "launcher_rules", lambda harness, hook: [("x.py", None, 5)])
    monkeypatch.setattr(launchdiff, "old_path", lambda harness, h, event, full: [{"hook": "hooks/x.py"}])
    monkeypatch.setattr(launchdiff, "compare", lambda *a: [])

    def run_old(layout, hooks, payload_raw, env, cwd, clock=None):
        seen["old"], seen["clock"] = env, clock
        return []

    def run_event(settings, event, payload, env, cwd, parallel=False):
        seen["new"] = env
        return {"event": event, "hooks": [], "launched": []}
    monkeypatch.setattr(launchdiff, "run_old", run_old)
    monkeypatch.setattr(hookrun, "run_event", run_event)
    try:
        rp.fire(_Session, "PostToolUse", "step")
    finally:
        if modeled:
            rpl._CLOCK.remove(rp)  # take the modeled clock back: a later test reads the real one
    return seen["new"], seen["old"], seen["clock"], json.loads(rp._inv.lines[0])["at"]


def test_the_own_process_run_gets_the_launchers_clock(monkeypatch, tmp_path):
    new, old, clock, at = _fire(monkeypatch, tmp_path, modeled=True)
    assert float(new["REPLAY_CLOCK_AT"]) == at == clock
    assert old["REPLAY_CLOCK_AT"] == new["REPLAY_CLOCK_AT"]
    assert old["PYTHONPATH"] == new["PYTHONPATH"] and old["PATH"] == new["PATH"]


def test_a_driver_on_the_real_clock_runs_the_own_process_as_before(monkeypatch, tmp_path):
    new, old, clock, _at = _fire(monkeypatch, tmp_path, modeled=False)
    assert clock is None and old == new == {"PATH": "/usr/bin", "PYTHONPATH": "/p"}


class _Rp:
    class layout:
        harness = project = "/nonexistent"

    clock_at = 1_000_000_000.0

    @staticmethod
    def norm_text(text):
        return text


def test_a_real_difference_is_still_found_on_the_modeled_clock(monkeypatch):
    monkeypatch.setattr(launchdiff, "_combine", lambda harness, event, old: (2, "", "refused"))
    hook = "hooks/pretool-x.py"
    launched = {"rules": [{"hook": hook, "rc": 0, "stdout": "", "stderr": ""}], "rc": 0, "stdout": "", "stderr": ""}
    old = [{"hook": hook, "rc": 2, "stdout": "", "stderr": "refused", "started": _Rp.clock_at}]
    diffs = launchdiff.compare(_Rp, "PreToolUse", launched, old)
    assert [d["what"] for d in diffs] == [hook + " rc", hook + " stderr", "answer rc", "answer stderr"]

