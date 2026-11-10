"""P6 A17 (P6-3): this tree's hooks run with the base master's settings.json, and then with this tree's,
against a toy project holding what the base master's own /dev left there (agent-index.json, the
dev-registry sentinels, the enforcement flags), each subagent registered under the base master and
still running when the merge lands.

The base master is a7d3a9f, the master before train 2 (the first parent of the train's merge,
d64fa96): the one P6 landed on. Each replay is a live landing (tests/replay/landing.py, as
test_live_landing.py runs it): the sandbox is built from the base tree, the session loads the base's
settings.json and plays the base's command text, and the harness home fast-forwards to the tree under
test while one subagent of the base's cycle is running (drivers/_p6_landing.py names the moment per
case). `master` keeps the base's settings.json for the whole session (D15); `base` reloads this tree's
from the landing on (landing.py `hooklist=landed`, A17's "Repeat with your settings.json").

The cases (A17, the A6 resolutions it names):

  untracked   an in-flight dev of the base's /dev declaring every untracked file, as the base's
              agents/dev.md derives its lists. P6's promotion has landed on this tree, so A17's
              "after the warning commit 0 with the warning" has no commit to run on here: the stop
              is refused (G2, exit 2) naming exactly `files_modified: []; files_created:
              generated.txt, src/new.py`, no `A3.a would block` line is printed, and after the dev
              sets those lists its stop exits 0.
  codex       the dev of `/dev --codex`: its stop without a codex call exits 2 (codex-enforce,
              A6), after its Skill(codex) call 0.
  qa          Step 13's QA with e2e_enforcement.status skipped_without_justification: its stop exits
              2 (e2e-enforce), again 2 after it Read the registry's dev.json (A6), 0 once it records a
              justified skip.
  explore     an Explore subagent across the landing and a plugin subagent after it, ordinary calls
              (and the plugin's Write of src/y.py, A5): no exit 2 anywhere.
  overnight   the dev child of a base /dev-overnight session (in place): its own work and stop exit
              0; its Write outside the session's working root exits 2 at the overnight guard, so it
              is bound to the base's session state (A6).
  grant       the base's /dev -> /close -> /commit, its commit grant minted before the landing (Step
              5), the analyst's message-file Write, its lock + stage + commit Bash (the grant spent)
              and its push-gate token step after it: each exits 0 and the commit lands with its token.
              The base's /close and /commit text is no longer played by this tree's drivers, so this
              case runs the base's own replay framework (tests/replay/base_driver/_p6_grant.py).

A probe's refusing hook is read from the hook that reports it under the settings file that runs the event:
the hook itself under the base's (`master`), the merged gate that runs it as a rule under this tree's
(`base`: G2, codex-enforce and e2e-enforce are rules of the producer gate, the overnight guard of the
write gate since P12, sites.reporter).

Every case, with either settings file: no hook error and no Python traceback after the landing, and no
exit 2 after it other than the case's own probes above. REPLAY_WORK keeps the runs; the table of each
case is written there as live-landing-p6.md.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time

import pytest

from tests.replay import hookrun, landing, sites, suite

OLD = "a7d3a9fec736c0e64b5a822ba5da788d4f178bda"
SETTINGS = ("master", "base")
G2 = "hooks/subagentstop-artifact-contract-enforce.py"
CODEX = "hooks/subagentstop-codex-enforce.py"
E2E = "hooks/subagentstop-e2e-enforce.py"
GUARD = "hooks/pretool-overnight-hook-guard.py"
EXPECTED_LISTS = "files_modified: []; files_created: generated.txt, src/new.py"
BASE_DRIVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "base_driver", "_p6_grant.py")
GRANT_LAND = "before:agent:changelog-analyst Write MSGFILE *"

# (case, cost: the wall seconds of its two replays side by side, for conftest.py's CI split)
COSTS = {"untracked": 100, "codex": 90, "qa": 110, "explore": 60, "overnight": 140, "grant": 340}
# Each probe: (event, label, the n-th event with that label after the landing (1-based), the blocks it
# must show as {hook: first-line regex}; {} for none). Every other event after the landing blocks nothing.
PROBES = {
    "untracked": [("SubagentStop", "Step 10 Agent(dev) stop", 1, {G2: r"^OBLIGATION_STOPGATE_BLOCKED: .*role=dev"}),
                  ("SubagentStop", "Step 10 Agent(dev) stop", 2, {})],
    "codex": [("SubagentStop", "Step 10 Agent(dev) stop", 1, {CODEX: r"^CODEX_ENFORCE_BLOCKED: .*\(type=dev\)"}),
              ("PostToolUse", "agent:dev Skill(codex) (next round)", 1, {}),
              ("SubagentStop", "Step 10 Agent(dev) stop", 2, {})],
    "qa": [("SubagentStop", "Step 13 Agent(qa) stop", 1, {E2E: r"^E2E_ENFORCE_BLOCKED: .*\(type=qa\).*skipped_without_justification"}),
           ("PostToolUse", "agent:qa Read dev.json (next round)", 1, {}),
           ("SubagentStop", "Step 13 Agent(qa) stop", 2, {E2E: r"^E2E_ENFORCE_BLOCKED: .*\(type=qa\).*skipped_without_justification"}),
           ("SubagentStop", "Step 13 Agent(qa) stop", 3, {})],
    "explore": [("PreToolUse", "agent:Explore Grep", 1, {}), ("PreToolUse", "agent:Explore Glob", 1, {}),
                ("PreToolUse", "agent:Explore Bash ls", 1, {}), ("SubagentStop", "main Agent(Explore) stop", 1, {}),
                ("PreToolUse", "main Agent(demo-plugin:reviewer)", 1, {}),
                ("PreToolUse", "agent:demo-plugin:reviewer Read", 1, {}),
                ("PreToolUse", "agent:demo-plugin:reviewer Grep", 1, {}),
                ("PreToolUse", "agent:demo-plugin:reviewer Bash ls", 1, {}),
                ("PreToolUse", "agent:demo-plugin:reviewer Write src/y.py", 1, {}),
                ("SubagentStop", "main Agent(demo-plugin:reviewer) stop", 1, {}), ("Stop", "Stop", 1, {})],
    "overnight": [("PreToolUse", "agent:dev Write outside the working root", 1, {GUARD: r"WORKTREE"}),
                  ("SubagentStop", "C1 Step 12 Agent(dev) pipeline 0 stop", 1, {})],
    "grant": [("PreToolUse", "agent:changelog-analyst Write MSGFILE 0", 1, {}),
              ("PreToolUse", "agent:changelog-analyst Bash stage and commit 0", 1, {}),
              ("PreToolUse", "agent:changelog-analyst Bash push-gate token 0", 1, {}),
              ("SubagentStop", "/commit Step 7 Agent(changelog-analyst) stop", 1, {}), ("Stop", "/commit Stop", 1, {})],
}


# ---------------------------------------------------------------- the runners

class _BaseFramework:
    """Replays of a driver run by the base master's own replay framework (its tests/replay, in the base
    tree from git history), in a sandbox it builds, with this tree as branch `landed` of the harness
    home (landing.add_landed, the same in both frameworks)."""

    def __init__(self, work: str, rev: str, guard: suite.ProxyGuard):
        self.work, self.guard = os.path.abspath(work), guard
        self.base = landing.base_tree(suite.REPO, rev, os.path.join(self.work, "base-tree"))
        shutil.copy(BASE_DRIVER, os.path.join(self.base, "tests", "replay", "drivers"))
        self.tpl = os.path.join(self.work, "template")
        self._py("from tests.replay import landing, sandbox\n"
                 f"sandbox.build({self.base!r}, {self.tpl!r}, log=lambda *a: None)\n"
                 f"landing.add_landed({self.tpl!r}, {suite.REPO!r})\n")

    def _env(self) -> dict:
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        return dict(env, PYTHONDONTWRITEBYTECODE="1")

    def _py(self, code: str) -> None:
        p = subprocess.run([sys.executable, "-c", code], cwd=self.base, env=self._env(), capture_output=True,
                           text=True)
        if p.returncode:
            raise RuntimeError(f"the base framework failed: {p.stdout}{p.stderr}"[-3000:])

    def run(self, scn: suite.Scenario, label: str, args: tuple) -> suite.Result:
        out, sb = os.path.join(self.work, "runs", label), os.path.join(self.work, "sb", label)
        for d in (out, sb):
            shutil.rmtree(d, ignore_errors=True)
        self._py(f"from tests.replay import sandbox\nsandbox.clone({self.tpl!r}, {sb!r})\n")
        argv = [sys.executable, "-m", "tests.replay", "run", "--tree", self.base, "--out", out, "--sandbox", sb,
                "--driver", scn.driver, "--settings", "shipped", "--runs", "plain"]
        for k, v in tuple(scn.args) + tuple(args):
            argv += ["--arg", f"{k}={v}"]
        for k, v in self.guard.env().items():
            argv += ["--env", f"{k}={v}"]
        before, t0 = self.guard.count, time.monotonic()
        p = subprocess.run(argv, cwd=self.base, env=self._env(), capture_output=True, text=True)
        wall = time.monotonic() - t0
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "replay.log"), "w") as fh:
            fh.write(p.stdout + p.stderr)
        shutil.rmtree(sb, ignore_errors=True)
        rd = os.path.join(out, "run1-plain")
        bl = suite._json(os.path.join(rd, "blocks.json"), {})
        res = suite.Result(scn, label, out, p.returncode, wall, summary=suite._json(os.path.join(rd, "summary.json"), {}),
                           blocks=bl.get("blocks", []), hook_errors=suite.hook_errors(rd),
                           failed_calls=bl.get("failed_calls", []), terminals=suite._json(os.path.join(rd, "terminals.json"), []),
                           facts=suite._json(os.path.join(rd, "facts.json"), []))
        res.connections = self.guard.count - before
        if not res.summary:
            res.error = f"the replay left no summary (rc {p.returncode}); see {out}/replay.log:\n" + (p.stdout + p.stderr)[-2000:]
        return res


def _scenario(case: str) -> suite.Scenario:
    if case == "grant":
        return suite.Scenario("P6 A17 grant", "_p6_grant", (("variant", "plain"), ("land", GRANT_LAND)),
                              ("dev", "close", "commit"), COSTS[case])
    return suite.Scenario(f"P6 A17 {case}", "_p6_landing", (("case", case),), ("p6-landing",), COSTS[case])


_LOCK = threading.Lock()
_STATE: dict = {}


def _root(tmp_path_factory) -> str:
    if "root" not in _STATE:
        _STATE["root"] = os.environ.get("REPLAY_WORK") or str(tmp_path_factory.mktemp("live-p6"))
    return _STATE["root"]


def _results(request, tmp_path_factory, case: str) -> dict:
    """{settings: Result} of the case, both replays side by side (run once per pytest session)."""
    with _LOCK:
        if case in _STATE:
            return _STATE[case]
        missing = suite.preconditions()
        if missing:
            pytest.fail("the replay suite cannot run here: " + "; ".join(missing), pytrace=False)
        root, scn = _root(tmp_path_factory), _scenario(case)
        if case == "grant":
            if "base_fw" not in _STATE:
                guard = suite.ProxyGuard()
                request.session.addfinalizer(guard.close)
                _STATE["base_fw"] = _BaseFramework(os.path.join(root, "live-p6-base-framework"), OLD, guard)
            fw = _STATE["base_fw"]
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=2) as ex:
                futs = {s: ex.submit(fw.run, scn, f"grant~{s}", () if s == "master" else (("hooklist", "landed"),))
                        for s in SETTINGS}
                got = {s: f.result() for s, f in futs.items()}
        else:
            if "runner" not in _STATE:
                from tests.replay.test_live_landing import LiveRunner
                r = LiveRunner(os.path.join(root, "live-p6"), OLD, env={}, workers=2,
                               log=lambda *a: print(*a, flush=True))
                request.session.addfinalizer(r.guard.close)
                _STATE["runner"] = r
            r = _STATE["runner"]
            items = [(scn, "shipped", () if s == "master" else (("hooklist", "landed"),), f"~{s}") for s in SETTINGS]
            got = dict(zip(SETTINGS, r.run_all(items)))
        _STATE[case] = got
        _report(root)
        return got


# ---------------------------------------------------------------- reading a replay

def _landing(r: suite.Result) -> dict:
    return r.fact("landing") or {}


def _after(r: suite.Result) -> list[dict]:
    land = _landing(r)
    return r.hook_events()[land["event"]:] if "event" in land else []


def _blocks(ev: dict) -> dict:
    return {h["hook"]: hookrun.refusal_first(h) for h in ev["hooks"] if h["verdict"] == "block"}


def _errors(events: list[dict]) -> list[str]:
    out = []
    for ev in events:
        for h in ev["hooks"]:
            text = (h.get("stderr") or "") + "\n" + (h.get("stdout") or "")
            if h["verdict"] == "error" or suite.TRACEBACK in (h.get("stderr") or "") or suite.GATE_TEXT.search(text):
                out.append(f"{ev['label']}: {h['hook']} ({h.get('how') or 'traceback'}): {(h.get('stderr') or '')[-300:]}")
    return out


def _probe_events(case: str, events: list[dict]) -> dict:
    """{probe index: the event it names, or None}."""
    found = {}
    for i, (event, label, nth, _want) in enumerate(PROBES[case]):
        same = [ev for ev in events if ev["event"] == event and ev["label"] == label]
        found[i] = same[nth - 1] if len(same) >= nth else None
    return found


def _reporter(hook: str, settings: str) -> str:
    """The hook that reports `hook`'s refusals after the landing: `hook` under the base's settings.json
    (master), else the hook this tree's settings.json reports it by (sites.reporter)."""
    return hook if settings == "master" else sites.reporter(suite.REPO, hook)


def _verdict(case: str, r: suite.Result, settings: str) -> list[str]:
    """Every way the replay departs from what A17 expects of the case (empty: as expected)."""
    bad = []
    if r.error or r.summary.get("driver_error"):
        return [f"the replay did not run: {r.error or r.summary['driver_error'][-1500:]}"]
    land = _landing(r)
    if land.get("rc") != 0 or "event" not in land:
        return [f"the harness home did not land: {land}"]
    events = _after(r)
    bad += [f"hook error after the landing: {e}" for e in _errors(events)]
    if r.connections:
        bad.append(f"{r.connections} network connection(s)")
    probes = _probe_events(case, events)
    probe_ids = {id(ev) for ev in probes.values() if ev is not None}
    for i, (event, label, nth, want) in enumerate(PROBES[case]):
        ev = probes[i]
        if ev is None:
            bad.append(f"no {event} {label!r} #{nth} after the landing")
            continue
        got = _blocks(ev)
        want = {_reporter(h, settings): rx for h, rx in want.items()}
        if set(got) != set(want) or any(not re.search(rx, got[h]) for h, rx in want.items()):
            bad.append(f"{event} {label!r} #{nth}: blocks {got}, expected {want or 'none'}")
    for ev in events:
        if id(ev) not in probe_ids and _blocks(ev):
            bad.append(f"unexpected block after the landing: {ev['event']} {ev['label']!r}: {_blocks(ev)}")
    for p in r.scenario.pipelines:
        if not (r.terminal(p) or {}).get("reached"):
            bad.append(f"terminal {p} not reached: {r.terminal(p)}")
    bad += _case_checks(case, r, events, probes)
    return bad


def _case_checks(case: str, r: suite.Result, events: list[dict], probes: dict) -> list[str]:
    bad = []
    if case == "untracked":
        p6 = r.fact("p6") or {}
        declared = (p6.get("declared") or {}).get("files_created") or []
        if "scratch.txt" not in declared or not any(p.startswith(".claude/dev-registry/") for p in declared):
            bad.append(f"the dev did not declare every untracked file (the base's derivation): {declared}")
        stop = probes[0]
        text = "\n".join(hookrun.refusal(h) for h in stop["hooks"] if h["verdict"] == "block") if stop else ""
        if "to exactly: " + EXPECTED_LISTS not in text:
            bad.append(f"G2's refusal does not name the expected lists ({EXPECTED_LISTS}): {text[-800:]}")
        if p6.get("rewritten") != {"files_modified": [], "files_created": ["generated.txt", "src/new.py"]}:
            bad.append(f"the dev's next round set {p6.get('rewritten')}")
        warned = [ev["label"] for ev in events for h in ev["hooks"] if "would block" in (h.get("stderr") or "")]
        if warned:
            bad.append(f"a warning line after the promotion: {warned}")
    if case == "grant":
        commit = r.fact("commit") or {}
        if commit.get("commit_status") != "committed" or not commit.get("push_gate_tokens"):
            bad.append(f"the commit did not land with its push-gate token: {commit}")
    return bad


def _row(case: str, r: suite.Result) -> str:
    events = _after(r)
    probes = _probe_events(case, events)
    cells = []
    for i, (event, label, nth, _want) in enumerate(PROBES[case]):
        ev = probes[i]
        got = _blocks(ev) if ev else None
        cells.append(f"{label} #{nth}: " + ("missing" if ev is None else
                                             ", ".join(f"2 {os.path.basename(h)}" for h in got) or "0"))
    return "; ".join(cells)


def _report(root: str) -> None:
    rows = []
    for case in COSTS:
        got = _STATE.get(case)
        if not got:
            continue
        rows.append({"case": case, **{f"{s} settings": _row(case, got[s]) for s in SETTINGS},
                     "as A17 expects": "yes" if not any(_verdict(case, got[s], s) for s in SETTINGS) else "NO"})
    with open(os.path.join(root, "live-landing-p6.md"), "w") as fh:
        fh.write("# P6 A17 (P6-3) on the base\n\n" + suite.table(rows) + "\n")


# ---------------------------------------------------------------- the tests

@pytest.mark.parametrize("settings", SETTINGS)
@pytest.mark.parametrize("case", [pytest.param(c, marks=pytest.mark.replay(f"P6 A17 {c}", COSTS[c])) for c in COSTS])
def test_inflight_subagent_meets_this_tree(request, tmp_path_factory, case, settings):
    r = _results(request, tmp_path_factory, case)[settings]
    bad = _verdict(case, r, settings)
    assert not bad, f"{case} ({settings} settings), {r.out}:\n  " + "\n  ".join(bad) + "\n" + r.explain()


@pytest.mark.parametrize("case", [pytest.param(c, marks=pytest.mark.replay(f"P6 A17 {c}", COSTS[c])) for c in COSTS])
def test_the_landed_settings_are_this_trees(request, tmp_path_factory, case):
    """`base` runs every event after the landing with this tree's settings.json, `master` with the base's."""
    got = _results(request, tmp_path_factory, case)
    land = {s: _landing(got[s]) for s in SETTINGS}
    reload = (got["base"].fact("hooklist") or {}) if case == "grant" else land["base"]
    assert reload.get("hooklist") == "landed" and "CLAUDE_OBLIGATION_GATE" in reload.get("env_changed", []), reload
    assert not land["master"].get("hooklist") and not got["master"].fact("hooklist"), land["master"]
