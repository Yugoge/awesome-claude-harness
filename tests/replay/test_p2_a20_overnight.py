"""P2 A20 (b): three of P2's process classes on a fault replay of the replay suite.

* the AskUserQuestion deny (hooks/pretool-overnight-hook-guard.py's AskUserQuestion branch, R10) and
  D20's unattended decision: drivers/overnight.py variant=unattended, shipped and armed. Its pipeline 0
  meets, inside the window, a producer question an experiment settles (BA, Step 8), a stand-in
  spec-declared user gate and a producer question no experiment settles (dev, Step 12); an
  AskUserQuestion is injected for the main agent at Step 8, for dev at Step 12 and for the main agent
  after end_time. Each injected AskUserQuestion is denied, exit 2, with the deny's decide text (the
  main agent's or the subagent's), read from the run's hook records; the three decisions are recorded
  in the cycle log and in the summary's "Decisions made without the owner", the gate first; the
  session's Stop after end_time passes once retro and summary exist, and /dev-overnight reaches its
  terminal. The artifact check replays this variant traced; this pins it in the replay suite, untraced.
* the time-lock in a non-UTC zone: drivers/overnight.py variant=plain with tz=Asia/Shanghai and
  tz=America/Los_Angeles, armed: TZ in every hook's and Bash call's environment, the end time typed as
  the zone's local clock time. The record's end_time is that time in UTC; the main agent's Stop inside
  the window is held by the time-lock naming it; after end_time, the Stop before the summary is held by
  the closeout naming the summary, and the session's Stop passes once retro and summary exist.

Any block on a compliant step fails the test (as in test_pipelines.py), and so does a hook error.
"""
from __future__ import annotations

import json
import os

import pytest

from tests.replay import suite
from tests.replay.drivers import overnight as night

GUARD = "pretool-overnight-hook-guard.py"
# cost: its untraced wall seconds, as test_overnight_one_pipeline.py declares its windowed sibling's
# (the 10-minute window, the launch and the closeout).
UNATTENDED = suite.Scenario("/dev-overnight unattended decision (D20)", "overnight", (("variant", "unattended"),),
                            ("dev-overnight",), 670)
PLAIN = next(s for s in suite.COMPLIANT if s.name == "/dev-overnight")
ZONES = ("Asia/Shanghai", "America/Los_Angeles")
# variant plain's window (twice CYCLE_WALL_S, rounded up to the typed clock minute) and its closeout
TZ_COST = 660


def _unattended_key(settings: str) -> str:
    return suite.replay_key(UNATTENDED, settings)


def _tz_key(zone: str) -> str:
    return suite.replay_key(PLAIN, "armed", (("tz", zone),))


def _out(r, name: str) -> dict:
    with open(os.path.join(r.run_dir, name)) as fh:
        return json.load(fh)


def _clean(r) -> None:
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    assert not r.blocks, "a compliant step met a gate block:\n" + r.explain()
    assert not r.hook_errors, "a hook erred:\n" + r.explain()
    assert r.reached(), "/dev-overnight did not reach its terminal:\n" + r.explain()


def _injected(r, event: str, tool: str | None = None) -> list:
    """The hook records of the calls the driver injected outside the compliant transcript."""
    return [ev for ev in r.hook_events() if ev.get("event") == event and (tool is None or ev.get("tool") == tool)
            and "(injected)" in (ev.get("label") or "")]


@pytest.mark.parametrize("settings", [pytest.param(s, id=s, marks=pytest.mark.replay(_unattended_key(s),
                                                                                       UNATTENDED.cost))
                                      for s in suite.SETTINGS])
def test_unattended_overnight_denies_every_question_and_decides_without_the_owner(replays, settings):
    r = replays.get(_unattended_key(settings))
    _clean(r)
    out = _out(r, "unattended.json")
    assert out["checks"] and all(c["ok"] for c in out["checks"]), [c for c in out["checks"] if not c["ok"]]
    # each injected AskUserQuestion denied, exit 2, by the overnight guard with the decide text, read from
    # the hook records: the main agent at Step 8, dev at Step 12, the main agent after end_time
    asked = _injected(r, "PreToolUse", "AskUserQuestion")
    where = [(ev["label"].split(" (injected)")[0].split(" ", 1)[1], "subagent" if ev.get("agent_type") else "main")
             for ev in asked]
    assert len(asked) == 3 and [who for _w, who in where] == ["main", "subagent", "main"], where
    assert where[0][0].startswith("Step 8") and where[1][0].startswith("Step 12") and where[2][0] == "Step 21", where
    for ev, (_w, who) in zip(asked, where):
        denied = [h for h in ev["hooks"] if h["hook"].endswith(GUARD)]
        assert len(denied) == 1 and denied[0]["rc"] == 2, (ev["label"], [(h["hook"], h["rc"]) for h in ev["hooks"]])
        assert night.DECIDE_TEXT[who] in denied[0]["stderr"], (ev["label"], denied[0]["stderr"])
    probes = [pr for pr in out["probes"] if pr["kind"] == "AskUserQuestion"]
    assert [pr["in_window"] for pr in probes] == [True, True, False], probes
    # the decisions, recorded in the summary's "Decisions made without the owner" and in the cycle log,
    # the gate first: their rows as the run's checks read them from the two files
    rows = next(c for c in out["checks"] if c["check"].startswith("the summary's 'Decisions made"))["detail"]
    assert [row[2] for row in rows] == [f"User gate: {night.GATE['gate']}", night.DECISION_EXPERIMENT["need"],
                                        night.DECISION_DEFAULT["need"]], rows
    assert [row[5] for row in rows] == [night.GATE["default"], "accept bool", night.DECISION_DEFAULT["default"]], rows
    log = next(c for c in out["checks"] if c["check"].startswith("the cycle log lists"))["detail"]
    assert len(log) == 3 and log[0].startswith("- 0 ") and "User gate:" in log[0], log
    assert len(out["decisions"]) == 3 and out["summary"] and out["log"], out["decisions"]
    # the session ends after end_time: its Stop passes once retro and summary exist
    term = r.terminal("dev-overnight")
    assert term["reached"] and term["stopped_at"] > term["end_time"], term
    ended = next(c for c in out["checks"] if c["check"].startswith("the session ends after end_time"))
    assert ended["ok"] and ended["detail"]["stopped"], ended


@pytest.mark.parametrize("zone", [pytest.param(z, id=z.replace("/", "-"),
                                               marks=pytest.mark.replay(_tz_key(z), TZ_COST)) for z in ZONES])
def test_overnight_time_lock_holds_and_releases_in_a_non_utc_zone(replays, zone):
    r = replays.get(_tz_key(zone))
    _clean(r)
    out = _out(r, "timezone.json")
    assert out["checks"] and all(c["ok"] for c in out["checks"]), [c for c in out["checks"] if not c["ok"]]
    launch = out["launch"]
    assert launch["zone"] == zone and launch["utc_offset"] not in ("+0000", "") and launch["ok"], launch
    assert launch["end_time"] == launch["expected_end_time"], launch
    # the zone in what every hook and every Bash call got
    assert _out(r, "env.json").get("TZ") == zone and _out(r, "bash-env.json").get("TZ") == zone
    stops = _injected(r, "Stop")
    assert len(stops) == 2, [ev.get("label") for ev in r.hook_events() if ev.get("event") == "Stop"]
    inside, after = stops
    lock = [h for h in inside["hooks"] if h["rc"] == 2 and night.WINDOW_LOCK in (h.get("stderr") or "")]
    assert lock and f"until {launch['expected_end_time']}," in lock[0]["stderr"], inside["hooks"]
    held = [h for h in after["hooks"] if h["rc"] == 2]
    assert held and all(night.WINDOW_LOCK not in (h.get("stderr") or "") for h in held), after["hooks"]
    assert any(night.OVERNIGHT_INCOMPLETE in h["stderr"] and "overnight-summary" in h["stderr"] for h in held), held
    term = r.terminal("dev-overnight")
    assert term["reached"] and term["stopped_at"] > term["end_time"] == launch["expected_end_time"], term
