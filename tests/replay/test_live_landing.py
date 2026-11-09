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

Per transition, with CLAUDE_OBLIGATION_STOPGATE=block in every hook's environment, and the base's
settings.json as the session loaded it:
  pre-merge  /dev singular in the toy repository, and a plain session in the harness home, each in a
             session that loaded the base's settings.json, the home landed before it (base
             settings.json, this tree's hooks and text): every Stop hook of every Stop exits 0;
  (a)        /redev after a /dev whose dev lane met the base G2's no-progress round (F2g's shape: the
             same invalid report rewritten, a forged ESCALATION_ACK line, then the repair): the /redev
             cycle runs on the base files through its first TodoWrite and its hooks, then on this tree's;
             every stop of it exits 0 in every hook;
  (b)        /dev-overnight, two cycles: base files through the first TodoWrite and its hooks, then this
             tree's: cycle 1 inside the window, Step 21's loop reset of a list without this tree's Step 0,
             cycle 2 to the Stop after end_time, each of whose hooks exits 0.
Each landed replay of (a) and (b) runs beside the same replay on the base files throughout (the base
replay). Both pass every block, recorded (landing.py `blocks=pass`; a stop block naming the artifact
(a)'s fault left unrepaired goes back to its agent, as on the base), so each runs to its end. Then each
block of the landed replay is matched to one of the base replay's (_match): the same hook, step (a todo
step by its content) and refusal first line; the orchestrator gate's same per-turn rule at the same
step with another write tool or count; the same hook and step with a message a row rewrote; or the
same call refused at the same step by another hook. None may be left over (new), no hook errs and G2
blocks nothing after the landing, and the landed replay reaches every terminal the base replay reaches.
A base replay shows what the base itself refuses (P1b's hand-off items on the master base, kept base
blocks); none of those is new.

Again with your settings.json (A11's last clause). P5 registers otherwise than both bases: the Stop
group is one entry, hooks/stop-launch.py (it runs the coordinator armed), for the coordinator, the
do-report gate and the obligation gate; posttool-todo-sequence.py and posttool-todo-count.py leave
PostToolUse TodoWrite. settings.json lands with the files it registers, in the one fast-forward, so
the session that has this tree's list is the one (re)loaded on the landed home: each replay above runs
again with landing.py's hooklist=landed, the base list and files before the landing, this tree's list,
its env and files from it on (pre-merge and harness-home sessions: the whole session). Checked: from
the landing on every event ran the hooks this tree's settings.json selects for it, the events where
that differs from the base's list exercise each differing registration (the scenarios together cover
all of them), and A11's assertions: no hook error and no G2 block after the landing; each block the
base replay shows (_match), one a P5 row introduces by design (DESIGNED: none so far), or held by a
phase this tree's Stop gate calls into before it merges (WAITS: P3's disposition, P2's overnight
locator and window), each listed with hook and text; every compliant stop exits 0 in every hook and
the terminal is reached, a stop held by WAITS aside (a block whose every gap is a WAITS failure). Each
block naming a WAITS failure, whole or beside gaps of its own, is its own failing check
(test_again_with_your_settings[<case>-<transition>-dependencies]), naming the phase, until it merges.

Master only, a fault whose consumer copy P1b deleted: F2 written after the landing in a session whose
environment has no STOPGATE (master's settings.json sets none) is stopped by G2 at the dev's stop,
through the landed settings.json's switch, with and without CLAUDE_HOME.

REPLAY_WORK keeps the runs (default: pytest's temp dir); the report of each transition, with the
A11 table, is written there as live-landing-<transition>.md.
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
import subprocess
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.replay import hookrun, landing, suite

TRANSITIONS = {"master": "2acc29b0c8149c32d8e424e58c6af55d073eac20",
               "p1b": "3f0b7a23ee9145c573678775dc67b0a230c228f4"}
ENV = {"CLAUDE_OBLIGATION_STOPGATE": "block"}
# P2 arms G1 and G3 beside P1b's STOPGATE, and the overnight guard's matcher gains AskUserQuestion (its
# unattended deny); a landed replay loads the base's settings.json, which has neither.
P2_ENV = {"CLAUDE_OBLIGATION_GATE": "block", "CLAUDE_OBLIGATION_BARRIER": "block"}
# P10 (R9) added PYTHONDONTWRITEBYTECODE; P10-42 dropped it from the clean form, so P10 adds no env
# entry, and the environment check below names no P10 entry: any env entry P10 adds fails it.
# P9: settings.json's env arms subagentstop-cp-enforce.py as shipped (CP_ENFORCE_MODE=block); the
# base's settings.json leaves it advisory.
P9_ENV = {"CP_ENFORCE_MODE": "block"}
P2_MATCHER = ("Write|Edit|MultiEdit|Bash", "Write|Edit|MultiEdit|Bash|AskUserQuestion")
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
PASS = (("blocks", "pass"),)
HOOKLIST = (("hooklist", "landed"),)  # the session's hook list is this tree's settings.json from the landing on


class LiveRunner(suite.Runner):
    """A Runner whose sandboxes hold the base tree (`rev` of this checkout) and, as branch `landed` of
    the harness home's git, the tree under test (this checkout's working tree)."""

    def __init__(self, work: str, rev: str, env=None, **kw):
        base = landing.base_tree(suite.REPO, rev, os.path.join(os.path.abspath(work), "base-tree"))
        super().__init__(work, tree=base, env=ENV if env is None else env, **kw)
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
        base = (scn, "shipped", PASS, "~base")
        live = (scn, "shipped", PASS + (("land", LAND[scn.name]),), "~landed")
        if scn in (PRE, HOME):  # the base replay of a session that never meets the base files: none
            return None, self.run_all([live])[0]
        return tuple(self.run_all([base, live]))

    def yours(self, scn: suite.Scenario) -> tuple[suite.Result | None, suite.Result]:
        """(the base replay, the replay whose session has this tree's settings.json from the landing on),
        side by side; the pre-merge and harness-home sessions have no base replay (pair)."""
        items = [(scn, "shipped", PASS + (("land", LAND[scn.name]),) + HOOKLIST, "~yours")]
        if scn not in (PRE, HOME):
            items.insert(0, (scn, "shipped", PASS, "~base"))
        got = self.run_all(items)
        return (None, got[0]) if len(got) == 1 else tuple(got)


_RUNNERS: dict = {}


def _runner(request, tmp_path_factory, name: str, env=None, tag: str = "") -> LiveRunner:
    """The transition's LiveRunner (one per transition, env and pytest session), its runs under REPLAY_WORK."""
    if (name, tag) not in _RUNNERS:
        missing = suite.preconditions()
        if missing:
            pytest.fail("the replay suite cannot run here: " + "; ".join(missing), pytrace=False)
        root = os.environ.get("REPLAY_WORK") or str(tmp_path_factory.mktemp("live"))
        r = LiveRunner(os.path.join(root, f"live-{name}{tag}"), TRANSITIONS[name], env=env, workers=2,
                       log=lambda *a: print(*a, flush=True))
        r.name = name + tag
        request.session.addfinalizer(r.guard.close)
        _RUNNERS[(name, tag)] = r
    return _RUNNERS[(name, tag)]


@pytest.fixture
def live(request, tmp_path_factory):
    return _runner(request, tmp_path_factory, request.param)


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
      "step refused on base"  the same event of the same step refused on the base by another hook: the
                   call the base refuses is refused (nothing the base lets through); listed with the
                   base's hook and text;
      "NEW"        anything else."""
    pool = list(base.blocks if base else [])
    found: dict = {}
    tests = (("same", lambda x, b: _key(x) == _key(b)),
             ("same rule", lambda x, b: x["hook"] == b["hook"] and _step(x) == _step(b)
              and _TOOL_COUNT.sub("#", x.get("first", "")) == _TOOL_COUNT.sub("#", b.get("first", ""))),
             ("rewritten", lambda x, b: x["hook"] == b["hook"] and _step(x) == _step(b)),
             ("step refused on base", lambda x, b: x["event"] == b["event"] and _step(x) == _step(b)))
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


def _stops(r: suite.Result, events=None, kinds=("Stop",)) -> list[dict]:
    """Every stop event of `kinds` (of `events`, default all): its label and each hook's exit code."""
    return [{"label": ev.get("label"), "rcs": {h["hook"]: h["rc"] for h in ev.get("hooks", [])}}
            for ev in (r.hook_events() if events is None else events) if ev.get("event") in kinds]


def _row(name: str, live: suite.Result, base: suite.Result | None) -> dict:
    """The A11 table's row; a replay with no base replay beside it compares nothing ("-")."""
    hows = Counter(how for _, how, _ in _match(live, base)) if base is not None else {}
    cols = ("same in base", "same rule", "rewritten", "step refused on base", "new")
    keys = ("same", "same rule", "rewritten", "step refused on base", "NEW")
    return {"replay": name, "hook events (after landing)": f"{live.summary.get('hook_events', 0)} ({len(_after(live))})",
            "blocks": len(live.blocks), **{c: hows.get(k, 0) if base is not None else "-" for c, k in zip(cols, keys)},
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
                   f"{b.get('first') or b['text'][:200]}" + (f" [base: {was['hook']}: {was.get('first')}]" if was else ""))
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
    # every terminal the base replay reaches (the base's own text may stop short of one: (a) on master's
    # text, whose Step 17 report the resolver refuses in both replays)
    assert live.reached() or (base is not None and not base.reached()), \
        "the landed replay did not reach its terminal:\n" + live.explain()


# ---------------------------------------------------------------- the tests

def _base_settings(name: str) -> dict:
    return json.loads(subprocess.run(["git", "-C", suite.REPO, "show", f"{TRANSITIONS[name]}:settings.json"],
                                     capture_output=True, text=True, check=True).stdout)


@pytest.mark.parametrize("name", sorted(TRANSITIONS))
def test_every_hook_a_base_session_registered_is_on_disk(name):
    """D15: a session running across the landing runs every hook command its base settings.json
    registered, at its path; each file such a command names is in this tree (stubbed, never deleted)."""
    named, missing = 0, []
    for event, groups in (_base_settings(name).get("hooks") or {}).items():
        for group in groups:
            for h in group.get("hooks", []):
                for rel in re.findall(r"""/((?:hooks|scripts)/[^"'\s]+)""", h.get("command", "")):
                    named += 1
                    if not os.path.isfile(os.path.join(suite.REPO, rel)):
                        missing.append((event, rel))
    assert named and not missing, (named, missing)


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
    stops = _stops(r, _after(r), ("Stop", "SubagentStop"))  # every stop of the /redev cycle is compliant
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


# ---------------------------------------------------------------- again with your settings.json

STOP, TODO = ("Stop", None), ("PostToolUse", "TodoWrite")
# The registrations (event, matcher) where this tree's settings.json differs from the base's that each
# scenario's events after the landing reach (the harness-home session writes no todo list); together
# they must be every one that differs (test_your_settings_differs_only_where_a_replay_runs_it).
EXERCISES = {PRE.name: {STOP, TODO}, HOME.name: {STOP}, A.name: {STOP, TODO}, B.name: {STOP, TODO}}
# The registrations two phases ahead of P5 change, which those phases name and no scenario here reaches
# after the landing (none asks with AskUserQuestion after it): P2's overnight guard on AskUserQuestion
# too (P2_MATCHER: its registration under the old matcher goes, the new one comes) and P4's close-rating
# hook (PostToolUse AskUserQuestion). Each is held to exactly that change; a replay that reaches one
# fails test_again_with_your_settings's `hooklist` part.
ELSEWHERE = {("PreToolUse", P2_MATCHER[0]): (["hooks/pretool-overnight-hook-guard.py"], []),
             ("PreToolUse", P2_MATCHER[1]): ([], ["hooks/pretool-overnight-hook-guard.py"]),
             ("PostToolUse", "AskUserQuestion"): ([], ["hooks/posttool-close-rating.py"])}

# Blocks a P5 row introduces by design in a compliant A11 replay: (row, hook, regex on the block's text).
# None: P5's Arming has every change accept old state and transcripts, so a compliant session that
# started on the base meets no block of P5's making.
DESIGNED: tuple = ()

# The phases this tree's Stop gate calls into before they merge (P5's base lacks them): a gap naming one
# is an instrument failure that phase's merge removes, never a P5 block. (phase, what is missing, gap).
WAITS = (
    ("P3", "P3's disposition(project_root, task_id, stage) is not merged: the gate's one adapter calls it "
           "through scripts/resolve-dev-artifact-chain.py's disposition_lines",
     re.compile(r"gate instrument failure: NameError: name 'disposition' is not defined")),
    ("P2", "P2's overnight locator and window are not merged: hooks/lib/overnight.py's locate and "
           "window_open, closeout_gaps(state, working_root)",
     re.compile(r"gate instrument failure: (?:AttributeError: module 'lib\.overnight' has no attribute "
                r"'(?:locate|window_open)'"
                r"|TypeError: closeout_gaps\(\) takes 1 positional argument but 2 were given)")),
)


def _head_settings() -> dict:
    with open(os.path.join(suite.REPO, "settings.json")) as fh:
        return json.load(fh)


def _registrations(settings: dict) -> dict:
    """(event, matcher) -> the (command, timeout) of each hook its groups register, in order."""
    out: dict = {}
    for event, groups in (settings.get("hooks") or {}).items():
        for group in groups:
            out.setdefault((event, group.get("matcher")), []).extend(
                (h.get("command"), h.get("timeout")) for h in group.get("hooks", []))
    return out


def _differing(name: str) -> dict:
    """(event, matcher) -> (the base's hooks, this tree's) of each registration that differs."""
    base, head = _registrations(_base_settings(name)), _registrations(_head_settings())
    return {k: ([hookrun.hook_name(c) for c, _ in base.get(k, [])], [hookrun.hook_name(c) for c, _ in head.get(k, [])])
            for k in set(base) | set(head) if base.get(k) != head.get(k)}


def _gaps(text: str) -> list[tuple[str, str | None]]:
    """Each gap a COMMAND_GATE block names, with the WAITS phase it waits for (None: a gap of its own);
    a time-lock the gate cannot read is one gap; [] for any other text."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if lines and lines[0].startswith("COMMAND_GATE time-lock: gate instrument failure: "):
        gaps = [lines[0][len("COMMAND_GATE time-lock: "):].split("; the human can type /stop")[0]]
    elif lines and lines[0].startswith("COMMAND_GATE /"):
        gaps = [line[2:] for line in lines[1:] if line.startswith("- ")]
    else:
        return []
    return [(gap, next((ph for ph, _, rx in WAITS if rx.fullmatch(gap)), None)) for gap in gaps]


def _waits(text: str) -> list[str] | None:
    """The phases a COMMAND_GATE block is held by when every gap it names is a WAITS instrument failure;
    None for any other text (a block of its own)."""
    phases = [ph for _, ph in _gaps(text)]
    return sorted(set(phases)) if phases and None not in phases else None


def _pending(text: str) -> list[str]:
    """The phases any gap of a COMMAND_GATE block waits for (a block may hold gaps of its own beside)."""
    return sorted({ph for _, ph in _gaps(text) if ph})


def _own(text: str) -> str:
    """A block's text without its WAITS gaps: the gaps of its own, else its first line."""
    gaps = _gaps(text)
    return "; ".join(gap for gap, ph in gaps if not ph) if gaps else hookrun.first_line(text)


def _hooklist(name: str, r: suite.Result) -> tuple[list, set, int]:
    """(each event after the landing whose hooks are not those this tree's settings.json selects for
    it, the differing registrations the events after the landing ran, the number of those events)."""
    base, head, differing = _base_settings(name), _head_settings(), _differing(name)
    land, bad, hit, n = _landing(r).get("event", 0), [], set(), 0
    for inv in suite._jsonl(os.path.join(r.run_dir, "invocations.jsonl")):
        if inv["seq"] <= land:
            continue
        ran = [h["command"] for h in inv["hooks"]]
        want = [h["command"] for h in hookrun.select(head, inv["event"], inv["payload"])]
        if ran != want:
            bad.append({"step": inv["label"], "event": inv["event"], "ran": [hookrun.hook_name(c) for c in ran],
                        "this tree's": [hookrun.hook_name(c) for c in want]})
        if [h["command"] for h in hookrun.select(base, inv["event"], inv["payload"])] != want:
            n += 1
            mv = hookrun.match_value(inv["event"], inv["payload"])
            hit |= {(e, m) for e, m in differing if e == inv["event"] and (mv is None or hookrun.matches(m, mv))}
    return bad, hit, n


def _classified(r: suite.Result, base: suite.Result | None) -> list[tuple]:
    """Each block of `r` with how it is explained: _match's classes against the base replay, "by
    design" (a DESIGNED row), "waits for <phases>" (every gap a WAITS failure), or "NEW"."""
    held = [(b, "waits for " + "+".join(ph), None) for b in r.blocks if (ph := _waits(b["text"]))]
    out = []
    for b, how, was in _match(dataclasses.replace(r, blocks=[b for b in r.blocks if not _waits(b["text"])]), base):
        row = next((d for d in DESIGNED if d[1] == b["hook"] and d[2].search(b["text"])), None) \
            if how == "NEW" else None
        out.append((b, "by design" if row else how, row or was))
    return out + held


def _stops_not_0(events: list[dict], kinds=("Stop",)) -> list[dict]:
    """Each hook of a stop of `kinds` that did not exit 0, a block held by WAITS aside; with the text
    of its own (its gaps that wait for no phase)."""
    return [{"step": ev.get("label"), "hook": h["hook"], "rc": h["rc"], "own": _own(hookrun.refusal(h)),
             "waits for": _pending(hookrun.refusal(h))}
            for ev in events if ev.get("event") in kinds for h in ev.get("hooks", [])
            if h["rc"] != 0 and not (h["verdict"] == "block" and _waits(hookrun.refusal(h)))]


def _terminals_missed(r: suite.Result, base: suite.Result | None) -> list:
    """Each pipeline whose terminal the replay missed (the base replay reaching its own), unless its
    terminal Stop was blocked and every Stop block after the landing is held by WAITS."""
    if r.reached() or (base is not None and not base.reached()):
        return []
    blocked = [h for ev in _after(r) if ev.get("event") == "Stop"
               for h in ev.get("hooks", []) if h["verdict"] == "block"]
    held = bool(blocked) and all(_waits(hookrun.refusal(h)) for h in blocked)
    return [(p, r.terminal(p)) for p in r.scenario.pipelines if not (r.terminal(p) or {}).get("reached")
            and not (held and (r.terminal(p) or {}).get("condition") and r.terminal(p).get("stop") == "blocked")]


def _yours_row(name: str, r: suite.Result, base: suite.Result | None) -> dict:
    """The A11 table's row of a replay with your settings.json: _row's columns, the blocks counted by
    _classified (by design, held by WAITS, new)."""
    hows = Counter("waits" if how.startswith("waits for ") else how for _, how, _ in _classified(r, base))
    counts = {col: hows.get(key, 0) if base is not None else "-" for col, key in (
        ("same in base", "same"), ("same rule", "same rule"), ("rewritten", "rewritten"),
        ("step refused on base", "step refused on base"))}
    counts.update({"by design": hows.get("by design", 0), "held (WAITS)": hows.get("waits", 0),
                   "new": hows.get("NEW", 0)})
    row = _row(name, r, base)
    head = {k: row[k] for k in ("replay", "hook events (after landing)", "blocks")}
    return {**head, **counts, **{k: v for k, v in row.items() if k not in head and k not in counts}}


def _yours_lines(name: str, scn: suite.Scenario, r: suite.Result, base: suite.Result | None) -> list[str]:
    land = _landing(r)
    bad, hit, n = _hooklist(name, r)
    out = [f"{scn.name}, your settings.json: landed at {land.get('at')!r}, hook list {land.get('hooklist')} "
           f"(env changed: {land.get('env_changed')}); {len(_after(r))} events after the landing, {n} where the "
           f"base list differs, differing registrations run: {sorted(map(str, hit))}; hook lists not this "
           f"tree's: {len(bad)}"]
    for b, how, was in _classified(r, base):
        was_text = f" [base: {was['hook']}: {was.get('first')}]" if isinstance(was, dict) else \
            f" [{was[0]}]" if was else ""
        gaps = "; ".join(gap for gap, _ in _gaps(b["text"]))
        out.append(f"- {how}: {b['hook']} at {b['step']!r} ({b['event']}, {b['how']}): "
                   f"{b.get('first') or b['text'][:200]}" + (f" | {gaps[:600]}" if gaps else "") + was_text)
    return out


YOURS = {"pre-merge": (PRE, HOME), "a": (A,), "b": (B,)}
# for the CI split: the scenario's replays go to one shard under the key its other test names, whose cost
# is the largest a test gives it; so each is that test's cost plus the wall seconds of this test's own
# replays (the base replay that test runs is cached)
YOURS_COST = {"pre-merge": 320, "a": 550, "b": 2400}
PARTS = ("hooklist", "a11", "dependencies")


def _yours_params():
    return [pytest.param(n, case, part, id=f"{case}-{n}-{part}",
                         marks=pytest.mark.replay(f"{scns[0].name} [{n}]", YOURS_COST[case]))
            for case, scns in YOURS.items() for n in sorted(TRANSITIONS) for part in PARTS]


@pytest.mark.parametrize("name", sorted(TRANSITIONS))
def test_your_settings_differs_only_where_a_replay_runs_it(name):
    """This tree's settings.json registers otherwise than the base's exactly at the registrations the
    scenarios below declare they run after the landing (EXERCISES), each checked in its replay, and at
    P2's and P4's own (ELSEWHERE); its environment differs by STOPGATE=block, P2's arming of G1 and
    G3 (P2_ENV) and P9's CP_ENFORCE_MODE (P9_ENV) alone."""
    differing = _differing(name)
    assert differing, "this tree registers as the base does: the replays with your settings.json are the replays"
    assert {k: differing.get(k) for k in ELSEWHERE} == ELSEWHERE, differing
    assert set(differing) - set(ELSEWHERE) == set().union(*EXERCISES.values()), differing
    head = _head_settings()
    assert hookrun.settings_env(_base_settings(name)) | ENV | P2_ENV | P9_ENV == \
        hookrun.settings_env(head) | ENV


@pytest.mark.parametrize("live,case,part", _yours_params(), indirect=["live"])
def test_again_with_your_settings(live, case, part):
    """A11 again with your settings.json: each replay with the session's hook list this tree's from the
    landing on (hooklist=landed). Parts: `hooklist`, the events after the landing ran this tree's list
    and reached the registrations EXERCISES names; `a11`, A11's assertions, a stop held by WAITS aside;
    `dependencies`, no block names a WAITS failure (fails, naming the phase, until that phase merges)."""
    scns = YOURS[case]
    if case == "pre-merge":  # side by side
        live.run_all([(scn, "shipped", PASS + (("land", LAND[scn.name]),) + HOOKLIST, "~yours") for scn in scns])
    runs = [(scn,) + tuple(live.yours(scn)) for scn in scns]
    reported = live.__dict__.setdefault("yours_reported", set())
    if case not in reported:
        reported.add(case)
        _report(live, [_yours_row(scn.name + " (your settings.json)", r, base) for scn, base, r in runs],
                [line for scn, base, r in runs for line in _yours_lines(live.name, scn, r, base)])
    for scn, base, r in runs:
        assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
        land = _landing(r)
        assert land.get("rc") == 0 and land.get("after") and land["after"] != land.get("before"), land
        if part == "hooklist":
            assert land.get("hooklist") == "landed", land
            bad, hit, _n = _hooklist(live.name, r)
            assert not bad, f"{scn.name}: events after the landing that did not run this tree's hook list: {bad}"
            assert hit == EXERCISES[scn.name], (scn.name, sorted(map(str, hit)), _differing(live.name))
        elif part == "a11":
            listed = "\n".join(_yours_lines(live.name, scn, r, base))
            new = [b for b, how, _ in _classified(r, base) if how == "NEW"]
            assert not new, f"{scn.name}: a block neither the base replay's, by design nor held:\n{listed}"
            assert not _verdicts_after(r, "error"), f"a hook error after the landing: {_verdicts_after(r, 'error')}"
            assert not _verdicts_after(r, "block", G2), \
                f"a G2 block after the landing: {_verdicts_after(r, 'block', G2)}"
            assert not _terminals_missed(r, base), f"terminal not reached: {_terminals_missed(r, base)}\n{r.explain()}"
            if scn in (PRE, HOME):  # every Stop hook of every Stop exits 0
                assert _stops(r), r.explain()
                bad = _stops_not_0(r.hook_events())
                assert not bad, f"{scn.name}: a Stop hook not exiting 0: {bad}"
            elif scn is A:  # every stop of the /redev cycle
                if live.name == "master":
                    assert land.get("no_progress_stores"), land
                assert _stops(r, _after(r), ("Stop", "SubagentStop")), r.explain()
                bad = _stops_not_0(_after(r), ("Stop", "SubagentStop"))
                assert not bad, f"a stop of the /redev cycle, a hook not exiting 0: {bad}"
            else:  # the todo reset after the landing, the Stop after end_time
                assert any("TodoWrite reset (loop)" in (ev.get("label") or "") for ev in _after(r)), \
                    "no todo reset after the landing"
                stop = [ev for ev in r.hook_events() if ev.get("event") == "Stop"
                        and "Stop after end_time" in (ev.get("label") or "")]
                assert stop, "no Stop after end_time"
                bad = _stops_not_0(stop[-1:])
                assert not bad, f"the Stop after end_time, a hook not exiting 0: {bad}"
        else:  # every block naming a WAITS failure, held whole or beside gaps of its own (the a11 part's)
            held = [b for b in r.blocks if _pending(b["text"])]
            phases = sorted({ph for b in held for ph in _pending(b["text"])})
            assert not held, (
                f"{scn.name}, your settings.json: waits for {' and '.join(phases)}: "
                + "; ".join(why for ph, why, _ in WAITS if ph in phases) + ". Blocks naming it:\n"
                + "\n".join(f"- {b['hook']} at {b['step']!r} ({b['event']}): {b.get('first')} | "
                             + "; ".join(gap for gap, _ in _gaps(b["text"])) for b in held))


# ---------------------------------------------------------------- a fault whose consumer copy P1b deleted

F2 = "invalid@agent:dev Write docs/dev/dev-report-*=dev.status:done,-dev.files_modified"
F2_LANDED = suite.Scenario("A11 F2 after the landing, the session's env without STOPGATE", "dev",
                           (("variant", "plain"), ("fault", F2)), ("dev",), 150)


@pytest.mark.replay("A11 F2 after the landing [master]", F2_LANDED.cost)
def test_g2_stops_a_deleted_copys_fault_through_the_landed_switch(request, tmp_path_factory):
    """P1b deleted /close's re-check of dev reports once G2 blocked (its E4). A session on master loaded a
    settings.json without CLAUDE_OBLIGATION_STOPGATE; after the landing G2 reads its switch from the
    landed settings.json at each stop (claude_home.settings_switch), with and without CLAUDE_HOME. So F2's
    invalid dev report, written after the landing, is stopped at the dev's own stop, the block naming
    the report and the failing check, and the dev's next round passes."""
    runners = [_runner(request, tmp_path_factory, "master", env={}, tag="-noenv"),
               _runner(request, tmp_path_factory, "master", env={"CLAUDE_HOME": "{harness}"}, tag="-claude-home")]
    land = PASS + (("land", "after:TodoWrite canonical list"),)
    rows, lines = [], []
    with ThreadPoolExecutor(max_workers=2) as ex:
        results = list(ex.map(lambda rr: rr.run(F2_LANDED, "shipped", faults=land, tag="~landed"), runners))
    for rr, res in zip(runners, results):
        g2 = [b for b in res.blocks if b["hook"] == G2]
        with open(os.path.join(res.run_dir, "faults.json")) as fh:
            fault = json.load(fh)[0]
        rows.append(dict(_row(F2_LANDED.name, res, None), **{"CLAUDE_HOME": "CLAUDE_HOME" in rr.env,
                                                             "repaired, rounds": (fault["repaired"], fault["rounds"])}))
        lines += _listed(res, None)
        assert not res.error and not res.summary.get("driver_error") and res.rc == 0, res.explain()
        assert _landing(res).get("rc") == 0, _landing(res)
        # the fault's one round, returned to the dev (the other blocks are the base text's, which (a) compares)
        assert len(g2) == 1 and g2[0]["event"] == "SubagentStop" and not g2[0]["passed_by_deviation"], res.explain()
        named = re.sub(r"\d{8}-\d{6}", "<ts>", fault["path"])  # the recorded text's ids are normalised
        assert named in g2[0]["text"] and re.search(r"files_modified|'done'", g2[0]["text"]), g2[0]["text"]
        assert fault["repaired"] and fault["rounds"] == 1, fault
        # master's /dev text stops short of its terminal at Step 17's resolver in every replay of it, the
        # base replay of (a) included; what is asked here is the fault's round at its producer
        assert not _verdicts_after(res, "error"), res.explain()
    _report(runners[0], rows, lines)
