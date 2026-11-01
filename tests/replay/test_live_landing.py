"""P1c A11, the live landing (D15, D19): the merge reaches the owner's harness home while its sessions
keep running with the hook list they loaded; nothing new may block a running session or an in-flight
cycle, and the home takes the change with no step of the owner's.

One replay models a session across the landing (tests/replay/landing.py): the sandbox is built from a
base tree taken from git history, the session loads the base's settings.json, and the harness home
fast-forwards to the tree under test between two events, as the owner's pull of the merge does. The
CLI keeps the hook commands it loaded; each event runs whatever file is on disk at that path.

Two transitions (the base tree each time from this checkout's history; CI fetches it whole):
  master  origin/master before P1b merges (2acc29b, P8's merge): the owner's live home today;
  p1b     P1b's head (3f0b7a2), which P1c builds on.

Per transition, with CLAUDE_OBLIGATION_STOPGATE=block in every hook's environment (the base's
settings.json as the session loaded it; this tree's settings.json registers the same hooks with the
same environment, checked below, so the replay with it is the same replay):
  pre-merge  /dev singular in the toy repository typed in a session that loaded the base's
             settings.json, the home landed before it (base settings.json, this tree's hooks and text):
             every Stop hook of every Stop exits 0;
  (a)        /redev after a /dev whose dev lane met the base G2's no-progress round (F2g's shape: the
             same invalid report rewritten, a forged ESCALATION_ACK line, then the repair): the /redev
             cycle runs on the base files through its first TodoWrite and its hooks, then on this tree's;
  (b)        /dev-overnight, two cycles: base files through the first TodoWrite and its hooks, then this
             tree's: cycle 1 inside the window, Step 21's loop reset of a list without this tree's Step 0,
             cycle 2 to the Stop after end_time.
Each landed replay runs beside the same replay on the base files throughout (the base replay). Both
pass every block, recorded (landing.py `blocks=pass`; in (a) a G2 block at a stop goes back to its
agent as on the base: the fault's own rounds), so each runs to its end; then every block of the landed replay must be one the
base replay shows at the same hook, the same step (a todo step by its content) and the same refusal
(first line), and no hook errs after the landing. A base replay shows what the base itself refuses
(P1b's hand-off items on the master base, kept base blocks); none of those is new.

REPLAY_WORK keeps the runs (default: pytest's temp dir); the report of each transition, with the
A11 table, is written there as live-landing-<transition>.md.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from collections import Counter

import pytest

from tests.replay import hookrun, landing, suite

TRANSITIONS = {"master": "2acc29b0c8149c32d8e424e58c6af55d073eac20",
               "p1b": "3f0b7a23ee9145c573678775dc67b0a230c228f4"}
ENV = {"CLAUDE_OBLIGATION_STOPGATE": "block"}
G2 = "hooks/subagentstop-artifact-contract-enforce.py"
FORGED = "forged@agent:dev Write docs/dev/dev-report-*=dev.status:done,-dev.files_modified"

# cost: the test's wall seconds (its base and landed replays side by side), for conftest.py's CI split
PRE = suite.Scenario("A11 pre-merge /dev", "dev", (("variant", "plain"),), ("dev",), 200)
HOME = suite.Scenario("A11 pre-merge session in the harness home", "_home", (), ("home",), 30)
A = suite.Scenario("A11 (a) /redev after a no-progress round", "redev", (("fault", FORGED),), ("dev", "redev"), 300)
B = suite.Scenario("A11 (b) /dev-overnight, two cycles", "overnight", (("variant", "plain"), ("cycles", "2")),
                   ("dev-overnight",), 1250)
LAND = {PRE.name: "start", HOME.name: "start", A.name: "after:TodoWrite canonical list#2",
        B.name: "after:C1 TodoWrite canonical list"}
PASS = {PRE.name: (("blocks", "pass"),), HOME.name: (("blocks", "pass"),),
        A.name: (("blocks", "pass"), ("blocks_keep", G2)),
        B.name: (("blocks", "pass"),)}


class LiveRunner(suite.Runner):
    """A Runner whose sandboxes hold the base tree (`rev` of this checkout) and, as branch `landed` of
    the harness home's git, the tree under test (this checkout's working tree)."""

    def __init__(self, work: str, rev: str, **kw):
        base = landing.base_tree(suite.REPO, rev, os.path.join(os.path.abspath(work), "base-tree"))
        super().__init__(work, tree=base, env=ENV, **kw)
        self.rev, self.landed = rev, None
        self._landing_lock = threading.Lock()

    def template(self) -> str:
        with self._landing_lock:
            tpl = super().template()
            if self.landed is None:
                self.landed = landing.add_landed(tpl, suite.REPO)
            return tpl

    def pair(self, scn: suite.Scenario) -> tuple[suite.Result, suite.Result]:
        """(the base replay, the landed replay) of `scn`, side by side."""
        base = (scn, "shipped", PASS[scn.name], "~base")
        live = (scn, "shipped", PASS[scn.name] + (("land", LAND[scn.name]),), "~landed")
        if scn in (PRE, HOME):  # the base replay of a session that never meets the base files: none
            return None, self.run_all([live])[0]
        return tuple(self.run_all([base, live]))


_RUNNERS: dict = {}


@pytest.fixture
def live(request, tmp_path_factory):
    """The transition's LiveRunner (one per transition and pytest session), its runs under REPLAY_WORK."""
    name = request.param
    if name not in _RUNNERS:
        missing = suite.preconditions()
        if missing:
            pytest.fail("the replay suite cannot run here: " + "; ".join(missing), pytrace=False)
        root = os.environ.get("REPLAY_WORK") or str(tmp_path_factory.mktemp("live"))
        r = LiveRunner(os.path.join(root, "live-" + name), TRANSITIONS[name], workers=2,
                       log=lambda *a: print(*a, flush=True))
        r.name = name
        request.session.addfinalizer(r.guard.close)
        _RUNNERS[name] = r
    return _RUNNERS[name]


def _each(scn: suite.Scenario, cost: int):
    """One test per transition, each its own replay key (conftest.py's CI split by cost)."""
    return pytest.mark.parametrize("live", [pytest.param(n, id=n, marks=pytest.mark.replay(f"{scn.name} [{n}]", cost))
                                            for n in sorted(TRANSITIONS)], indirect=True)


# ---------------------------------------------------------------- reading a replay

def _landing(r: suite.Result) -> dict:
    return r.fact("landing") or {}


def _after(r: suite.Result) -> list[dict]:
    """The landed replay's hook events after the landing (hooks.jsonl, in order)."""
    return r.hook_events()[_landing(r).get("event", 0):]


def _key(b: dict) -> tuple:
    return b["hook"], b.get("step_norm", b["step"]), b.get("first", "")


_WRITE_MODE = re.compile(r" \((?:Edit|Read before edit)\)$")
_TOOL_COUNT = re.compile(r"\b(?:Write|Edit|MultiEdit)\b|\d+")


def _step(b: dict) -> str:
    """The block's step without the driver's write mode: a file the main agent writes at a step is a
    Write when it is new and an Edit when it exists (drivers/overnight.py Night.write)."""
    return _WRITE_MODE.sub("", b.get("step_norm", b["step"]))


def _match(live: suite.Result, base: suite.Result | None) -> list[tuple]:
    """Each block of the landed replay with how the base replay shows it, each base block matched once
    (a step label both cycles of one replay share counts once per occurrence), exact matches first:
      "same"       the same hook, step and refusal first line;
      "same rule"  the same hook and step, the first lines differing only in the write tool's name and
                   in counts (the orchestrator gate's per-turn tool limit met by an Edit of a file the
                   base writes new); listed with the base's text;
      "rewritten"  the same hook and step, another first line (a row rewrote the message); listed with
                   the base's text;
      "NEW"        anything else."""
    pool = list(base.blocks if base else [])
    found: dict = {}
    tests = (("same", lambda x, b: _key(x) == _key(b)),
             ("same rule", lambda x, b: x["hook"] == b["hook"] and _step(x) == _step(b)
              and _TOOL_COUNT.sub("#", x.get("first", "")) == _TOOL_COUNT.sub("#", b.get("first", ""))),
             ("rewritten", lambda x, b: x["hook"] == b["hook"] and _step(x) == _step(b)))
    for how, ok in tests:
        for i, b in enumerate(live.blocks):
            hit = None if i in found else next((x for x in pool if ok(x, b)), None)
            if hit is not None:
                pool.remove(hit)
                found[i] = (how, None if how == "same" else hit)
    return [(b,) + found.get(i, ("NEW", None)) for i, b in enumerate(live.blocks)]


def _new_blocks(live: suite.Result, base: suite.Result | None) -> list[dict]:
    return [b for b, how, _ in _match(live, base) if how == "NEW"]


def _verdicts_after(r: suite.Result, verdict: str, hook: str | None = None) -> list[dict]:
    """Hook runs after the landing with `verdict` (error: also a traceback or GATE_ERROR/GATE_FAULT text)."""
    out = []
    for ev in _after(r):
        for h in ev.get("hooks", []):
            text = (h.get("stderr") or "") + "\n" + (h.get("stdout") or "")
            hit = h["verdict"] == verdict or (verdict == "error" and (suite.TRACEBACK in (h.get("stderr") or "")
                                                                       or suite.GATE_TEXT.search(text)))
            if hit and (hook is None or h["hook"] == hook):
                out.append({"step": ev.get("label"), "event": ev.get("event"), "hook": h["hook"], "rc": h["rc"],
                            "text": (h.get("stderr") or h.get("stdout") or "")[-400:]})
    return out + [e for e in r.hook_errors if e.get("hook") == "network"]


def _stops(r: suite.Result, events=None) -> list[dict]:
    """Every Stop event (of `events`, default all): its label and each hook's exit code."""
    return [{"label": ev.get("label"), "rcs": {h["hook"]: h["rc"] for h in ev.get("hooks", [])}}
            for ev in (r.hook_events() if events is None else events) if ev.get("event") == "Stop"]


def _row(name: str, live: suite.Result, base: suite.Result | None) -> dict:
    new = _new_blocks(live, base)
    hows = Counter(how for _, how, _ in _match(live, base))
    return {"replay": name, "hook events (after landing)": f"{live.summary.get('hook_events', 0)} ({len(_after(live))})",
            "blocks": len(live.blocks), "same in base": hows["same"], "same rule": hows["same rule"],
            "rewritten": hows["rewritten"], "new": len(new),
            "G2 blocks after landing": len(_verdicts_after(live, "block", G2)),
            "hook errors after landing": len(_verdicts_after(live, "error")),
            "terminal": "yes" if live.reached() else "no",
            "base replay: blocks / hook errors / terminal": "-" if base is None else
            f"{len(base.blocks)} / {len(base.hook_errors)} / {'yes' if base.reached() else 'no'}"}


def _listed(live: suite.Result, base: suite.Result | None) -> list[str]:
    """Each block of the landed replay with its hook text, and how the base replay shows it."""
    out = []
    for b, how, was in _match(live, base):
        out.append(f"- {how if base else 'landed only'}: {b['hook']} at {b['step']!r} ({b['event']}, {b['how']}): "
                   f"{b.get('first') or b['text'][:200]}" + (f" [base: {was.get('first')}]" if was else ""))
    return out


def _report(runner: LiveRunner, rows: list, lines: list) -> None:
    path = os.path.join(runner.work, f"live-landing-{runner.name}.md")
    with open(path, "a") as fh:
        fh.write("\n".join([suite.table(rows)] + lines) + "\n\n")
    print(suite.table(rows), *lines, sep="\n")


def _common(live: suite.Result, base: suite.Result | None) -> None:
    assert not live.error and not live.summary.get("driver_error") and live.rc == 0, live.explain()
    land = _landing(live)
    assert land.get("rc") == 0 and land.get("after") and land["after"] != land.get("before"), land
    assert not _new_blocks(live, base), "a block the base replay does not show:\n" + "\n".join(_listed(live, base))
    assert not _verdicts_after(live, "error"), f"a hook error after the landing: {_verdicts_after(live, 'error')}"
    assert not _verdicts_after(live, "block", G2), f"a G2 block after the landing: {_verdicts_after(live, 'block', G2)}"
    assert live.reached(), "the landed replay did not reach its terminal:\n" + live.explain()


# ---------------------------------------------------------------- the tests

@pytest.mark.parametrize("name", sorted(TRANSITIONS))
def test_this_trees_settings_replay_as_the_base_settings(name, tmp_path):
    """The landed replays load the base's settings.json; this tree's registers the same hooks with the
    same environment once STOPGATE=block is set, so a replay with it is the same replay (A11's "again with
    your settings.json")."""
    base = json.loads(subprocess.run(["git", "-C", suite.REPO, "show", f"{TRANSITIONS[name]}:settings.json"],
                                     capture_output=True, text=True, check=True).stdout)
    with open(os.path.join(suite.REPO, "settings.json")) as fh:
        head = json.load(fh)
    assert base.get("hooks") == head.get("hooks")
    assert hookrun.settings_env(base) | ENV == hookrun.settings_env(head) | ENV


@_each(PRE, PRE.cost)
def test_pre_merge_session_stops_exit_0(live):
    """A session that loaded the base's settings.json, the home landed: /dev in the toy repository, and a
    session in the harness home; every Stop hook of every Stop exits 0, no block, no hook error."""
    rows, lines, bad = [], [], []
    for scn in (PRE, HOME):
        _, r = live.pair(scn)
        stops = _stops(r)
        rows.append(_row(scn.name, r, None))
        lines += [f"{scn.name}: {len(stops)} Stops, every Stop hook exit 0: "
                  f"{all(rc == 0 for st in stops for rc in st['rcs'].values())}"] + _listed(r, None)
        bad += [(scn.name, st) for st in stops if any(rc != 0 for rc in st["rcs"].values())]
        assert stops, r.explain()
        assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
        assert not r.blocks and not r.hook_errors, r.explain()
        assert r.reached(), r.explain()
    _report(live, rows, lines)
    assert not bad, bad


@_each(A, A.cost)
def test_a_redev_after_a_no_progress_round(live):
    base, r = live.pair(A)
    land = _landing(r)
    _report(live, [_row(A.name, r, base)],
            [f"landed at {land.get('at')!r}; the base G2's stores on disk then: {land.get('no_progress_stores')}"]
            + _listed(r, base))
    _common(r, base)
    if live.name == "master":  # d625284's G2 wrote its no-progress round's records (P1b deleted the writer)
        assert land.get("no_progress_stores"), land
    stops = _stops(r, _after(r))
    assert stops and all(rc == 0 for st in stops for rc in st["rcs"].values()), stops


@_each(B, B.cost)
def test_b_overnight_through_its_todo_reset_to_the_stop_after_end_time(live):
    base, r = live.pair(B)
    after = [ev.get("label") for ev in _after(r)]
    _report(live, [_row(B.name, r, base)], [f"landed at {_landing(r).get('at')!r}"] + _listed(r, base))
    _common(r, base)
    assert any("TodoWrite reset (loop)" in (x or "") for x in after), "no todo reset after the landing"
    stop = [s for s in _stops(r) if "Stop after end_time" in (s["label"] or "")]
    assert stop and all(rc == 0 for rc in stop[-1]["rcs"].values()), stop
