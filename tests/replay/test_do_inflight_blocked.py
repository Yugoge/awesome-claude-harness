"""P4 A4 (g) on this tree (P10-51, D18): a /do task without a completed do-report, the case that can occur.

Since P5 a /do has one terminal (commands/do.md Step 5): the Stop gate holds a /do until its do-report is
completed, so no compliant /do of this tree ends with another status. A do-report short of completed is
left only by a session that wrote it before the landing: the /do text of a7d3a9f (the master before
train 2) names a second terminal, "blocked", for a task that could not be finished. So A4 (g) runs as a
live landing (tests/replay/landing.py): the session loads a7d3a9f's settings.json and plays its /do text
(drivers/do.py variant=blocked; the case's left= says how much of the change the /do made),
the /do Stop passes on the base's hooks with do.status "blocked", the harness home lands after that Stop,
and `/close <task>` plays this tree's text. Each case runs with the base's settings.json kept for the
whole session (D15, `kept`) and with this tree's from the landing on (`landed`, hooklist=landed).

The other candidate, a /do cut off before Step 5 with no do-report, is not A4 (g): Step 0 names the
missing do-report, the reader returns null and close.md asks the owner (header Request; P4-20).

Checked per case and settings file:
  - the /do Stop exits 0 in every hook, its do-report says do.status "blocked", the home lands after it;
  - Step 0's first disposition is incomplete on the do-report alone (do.status:blocked);
  - Routes' /do bullet dispatches exactly one dev: the task's id, pipeline do, the dev-report declared;
  - the /close main agent writes no file (no Write, Edit, MultiEdit or NotebookEdit) and no subagent
    writes the do-report; dev edits exactly the files the /do left changes in (toy/__init__.py where
    the /do left part of the change, none where it left none); dev's report (dev.status completed)
    lists those and, beside them, each file the do-report lists (commands/close.md's Routes /do
    bullet, P5-62: dev names each in one of its Bash commands so G2 counts it, and the chain's Q7
    check holds dev's report to them, since /commit plans from it): toy/__init__.py in every case;
  - Step 0 again: chain_pass (the G2-verified dev-report concludes the task, Q7); one close-QA round;
    `CLOSE: YES` as the close report's last line; the only question is Step 4's rating;
  - no hook error, no network attempt; no block other than the case's own and the host's below.
The host's block: the session starts on the base, so its SessionStart runs a7d3a9f's
scripts/canary-verify.sh, which reads the host's own /etc and /usr/local/sbin (the sandbox's namespace
gives a replay its own HOME and temp dirs only, and this tree's hooks read the host's /etc in every
replay). That canary fails (exit 2) on any file at a cleanup artifact's deploy path that differs from
the tree's copy, the host's own file included (#54 since: a file lacking the copy's line naming its deploy
target is the host's, an advisory), as the CI runner image's /etc/tmpfiles.d/tmp.conf has been since
2026-11-16. Where this host holds such a file (_host_own, read from the host and the base tree, not from
the replay), the blocks expected are that canary's one block at `SessionStart startup`, before the
landing, its failure lines exactly one per such file, then the case's own; elsewhere none. The harness's
own copy drifted (the line present) is never the host's: its failure line fails the case.
The cases (left= of drivers/do.py; every one is a /do ending a compliant /do of a7d3a9f's text produces):
  plain  left=half: toy.add checks argument a only, the user stops the task; dev adds b. No block.
  g2     left=half, and the routed dev's first stop, its dev-report written with dev.status short of
         completed (drivers/close.py dev_stop=uncompleted), is refused by G2; its second stop exits 0.
  none   left=none: the user abandons the task before the change (P1b's acceptance 7 /do case); dev
         makes it. Fails on the base at scripts/resolve-dev-artifact-chain.py:1750 (group 2): Step 0
         prints FILES_NOT_DEV_REPORT on the do-report (it lists [], dev's report ["toy/__init__.py"])
         and is still incomplete after 4 routing rounds, since no dispatch may rewrite the do-report.
  all    left=all: the change is made, the toy tests stayed unauthorized (A4 (g) as P4 first ran it);
         dev edits nothing and its report takes over the do-report's toy/__init__.py. Fails on the base
         at scripts/resolve-dev-artifact-chain.py:1750 (group 2): Step 0 prints FILES_NOT_DEV_REPORT on
         the do-report (it lists ["toy/__init__.py"], dev's report []) and is still incomplete after 4
         routing rounds; since P5-62 the gap names dev's report, and a dev that lists only the files it
         edited leaves it, round after round.
And on this tree's own text the driver refuses variant=blocked before typing the /do.
REPLAY_WORK keeps the runs.
"""
from __future__ import annotations

import glob
import json
import os
import threading

import pytest

from tests.replay import sites, suite

OLD = "a7d3a9fec736c0e64b5a822ba5da788d4f178bda"
G2 = "hooks/subagentstop-artifact-contract-enforce.py"
# The hook that reports G2's refusal under each settings file: G2 itself under the base's list (kept),
# the merged gate that runs it as a rule under this tree's (landed: hooks/subagentstop-producer-gate.py
# since P12, sites.reporter).
G2_REPORTER = {"kept": G2, "landed": sites.reporter(suite.REPO, G2)}
LAND = "after:/do Stop"
SETTINGS = ("kept", "landed")
WRITES = ("Write", "Edit", "MultiEdit", "NotebookEdit")
# case -> its driver arguments beside variant=blocked (the module text says what each plays)
CASES = {"plain": (("left", "half"),), "g2": (("left", "half"), ("dev_stop", "uncompleted")),
         "none": (("left", "none"),), "all": (("left", "all"),)}
# case -> the product files dev edits: the rest of the change the /do left
DEV_FILES = {"plain": ["toy/__init__.py"], "g2": ["toy/__init__.py"], "none": ["toy/__init__.py"], "all": []}
# case -> the files dev's report lists: the ones it edited and each file the do-report lists (Routes' /do
# bullet, P5-62), so toy/__init__.py where the /do made all of the change too
REPORT_FILES = {"plain": ["toy/__init__.py"], "g2": ["toy/__init__.py"], "none": ["toy/__init__.py"],
                "all": ["toy/__init__.py"]}
# (case, cost: the wall seconds of its two replays side by side, for conftest.py's CI split)
COSTS = {"plain": 70, "g2": 80, "none": 70, "all": 70}
CANARY = "scripts/canary-verify.sh"
# a7d3a9f's verify_cleanup_drift: (deploy path, the tree's copy under scripts/install/)
CLEANUP = (("/usr/local/sbin/tmp-cleanup.sh", "tmp-cleanup-install.sh"),
           ("/etc/tmpfiles.d/claude-scratch.conf", "tmpfiles-claude-scratch.conf"),
           ("/etc/tmpfiles.d/tmp.conf", "tmpfiles-tmp-override.conf"),
           ("/etc/tmpfiles.d/var-tmp-claude.conf", "tmpfiles-var-tmp-override.conf"))

_LOCK = threading.Lock()
_STATE: dict = {}


def _host_own(base: str) -> list[str]:
    """The failure lines a7d3a9f's canary prints at this host's own files (the module text): one per
    deploy path in CLEANUP whose file differs from the base tree's copy and lacks the copy's first line
    naming that path, the line #54's canary reads as the harness's own. A differing file with that line
    is the harness's copy drifted and is left out, so its failure line is never expected."""
    lines = []
    for deployed, name in CLEANUP:
        copy = os.path.join(base, "scripts", "install", name)
        if not (os.path.isfile(copy) and os.path.isfile(deployed)):
            continue  # the base canary skips the pair, or prints an advisory only
        with open(copy, "rb") as fh:
            ours = fh.read()
        with open(deployed, "rb") as fh:
            theirs = fh.read()
        if ours == theirs:
            continue
        marker = next((ln for ln in ours.decode(errors="replace").splitlines() if deployed in ln), "")
        if marker and marker not in theirs.decode(errors="replace").splitlines():
            lines.append(f"canary-verify[FAIL]: cleanup artifact drift: {deployed} differs from "
                         f"<harness>/scripts/install/{name}")
    return lines


def _results(request, tmp_path_factory, case: str) -> dict:
    """{settings: Result} of the case, both replays side by side (run once per pytest session)."""
    with _LOCK:
        if case in _STATE:
            return _STATE[case]
        missing = suite.preconditions()
        if missing:
            pytest.fail("the replay suite cannot run here: " + "; ".join(missing), pytrace=False)
        if "runner" not in _STATE:
            from tests.replay.test_live_landing import LiveRunner
            root = os.environ.get("REPLAY_WORK") or str(tmp_path_factory.mktemp("do-inflight"))
            r = LiveRunner(os.path.join(root, "do-inflight-blocked"), OLD, env={}, workers=2,
                           log=lambda *a: print(*a, flush=True))
            request.session.addfinalizer(r.guard.close)
            _STATE["runner"], _STATE["host"] = r, _host_own(r.tree)
        scn = suite.Scenario(f"A4 (g) in-flight blocked do-report, {case}", "do",
                             (("variant", "blocked"),) + CASES[case], ("do", "close"), COSTS[case])
        extra = {"kept": (), "landed": (("hooklist", "landed"),)}
        items = [(scn, "shipped", (("land", LAND),) + extra[s], f"~{s}") for s in SETTINGS]
        _STATE[case] = dict(zip(SETTINGS, _STATE["runner"].run_all(items)))
        return _STATE[case]


def _transcripts(r: suite.Result) -> tuple[list, dict]:
    """(the main transcript's records, {agent transcript name: its records}) of the replay's session."""
    main, agents = [], {}
    for path in sorted(glob.glob(os.path.join(r.run_dir, "transcripts", "**", "*.jsonl"), recursive=True)):
        with open(path) as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        if os.sep + "subagents" + os.sep in path:
            agents[os.path.basename(path)] = rows
        else:
            main = rows
    return main, agents


def _tool_uses(rows: list) -> list[dict]:
    return [x for e in rows if e.get("type") == "assistant"
            for x in (e.get("message") or {}).get("content") or [] if isinstance(x, dict) and x.get("type") == "tool_use"]


def _after_close(main: list) -> list:
    """The main transcript's records from the /close prompt on."""
    for i, e in enumerate(main):
        c = (e.get("message") or {}).get("content") if e.get("type") == "user" else None
        if isinstance(c, str) and "<command-name>/close</command-name>" in c:
            return main[i:]
    return []


def _written(uses: list, suffix: str) -> list[dict]:
    """The JSON documents a Write of a path ending in `suffix` wrote."""
    return [json.loads(u["input"]["content"]) for u in uses
            if u.get("name") == "Write" and str(u["input"].get("file_path", "")).endswith(suffix)]


def _final(uses: list, suffix: str) -> dict:
    """The JSON document a path ending in `suffix` holds after these calls: its last Write, then each
    Edit after it applied."""
    text = None
    for u in uses:
        inp = u.get("input") or {}
        if not str(inp.get("file_path", "")).endswith(suffix):
            continue
        if u.get("name") == "Write":
            text = inp.get("content")
        elif u.get("name") == "Edit" and text is not None:
            text = text.replace(inp["old_string"], inp["new_string"], -1 if inp.get("replace_all") else 1)
    return json.loads(text) if text else {}


def _verdict(case: str, r: suite.Result, settings: str, host: list[str]) -> list[str]:
    """Every way the replay departs from what the module text checks; `host`: _host_own's lines."""
    bad = []
    if r.error:
        return [r.error]
    if r.summary.get("driver_error"):
        bad.append("driver error: " + r.summary["driver_error"][-1500:])
    do, close = r.terminal("do"), r.terminal("close")
    tid = (do or {}).get("task", "")
    if not do or do.get("stop") != "ok":
        bad.append(f"the /do Stop is not clean: {do}")
    land = r.fact("landing") or {}
    if land.get("at") != "/do Stop" or land.get("rc") != 0 or land.get("before") == land.get("after"):
        bad.append(f"the home did not land after the /do Stop: {land}")
    main, agents = _transcripts(r)
    do_docs = _written(_tool_uses(main), f"do-report-{tid}.json")
    if [d.get("do", {}).get("status") for d in do_docs] != ["blocked"]:
        bad.append(f"the /do wrote no single blocked do-report: {[d.get('do') for d in do_docs]}")
    steps = [f["value"] for f in r.facts if f.get("key") == "close Step 0"]
    if [s.get("disposition") for s in steps] != ["incomplete", "chain_pass"]:
        bad.append(f"Step 0's dispositions: {steps}")
    elif steps[0].get("gaps") != [[f"docs/dev/do-report-{tid}.json", "do.status:blocked"]]:
        bad.append(f"Step 0's first gaps: {steps[0].get('gaps')}")
    routed = [f["value"] for f in r.facts if f.get("key") == "routed dev"]
    if len(routed) != 1 or not routed[0].get("task_id") or routed[0].get("pipeline") != "do" \
            or routed[0].get("artifacts") != ["docs/dev/dev-report-<task>.json"] or routed[0].get("stop_blocked"):
        bad.append(f"Routes' /do bullet: {routed}")
    own = [u for u in _tool_uses(_after_close(main)) if u.get("name") in WRITES]
    if own:
        bad.append(f"the /close main agent wrote: {[(u['name'], u['input'].get('file_path')) for u in own]}")
    sub = [(name, u["name"], u["input"].get("file_path")) for name, rows in agents.items() for u in _tool_uses(rows)
           if u.get("name") in WRITES]
    if any(str(p).endswith(f"do-report-{tid}.json") for _n, _t, p in sub):
        bad.append(f"a subagent wrote the do-report: {sub}")
    # the project root as the replay's processes see it: where the /do wrote its do-report
    project = next((str(u["input"]["file_path"])[:-len(f"/docs/dev/do-report-{tid}.json")]
                    for u in _tool_uses(main) if u.get("name") == "Write"
                    and str(u["input"].get("file_path", "")).endswith(f"/docs/dev/do-report-{tid}.json")), "")
    edited = sorted({os.path.relpath(str(p), project) for _n, t, p in sub
                     if not str(p).startswith((f"{project}/docs/dev/", f"{project}/.claude/"))})
    if edited != DEV_FILES[case]:
        bad.append(f"the product files subagents wrote: {edited}, expected {DEV_FILES[case]}")
    order = sorted((n for n in agents if agents[n]), key=lambda n: (agents[n][0].get("timestamp", ""), n))
    dev_uses = [u for n in order for u in _tool_uses(agents[n])]
    last = _final(dev_uses, f"dev-report-{tid}.json").get("dev") or {}
    if last.get("status") != "completed" or (last.get("files_modified") or []) + (last.get("files_created") or []) \
            != REPORT_FILES[case]:
        bad.append(f"dev's last report: {last}")
    rounds = [f["value"] for f in r.facts if f.get("key") == "close QA round"]
    if len(rounds) != 1:
        bad.append(f"close-QA rounds: {rounds}")
    if not close or not close.get("reached") or not str(close.get("report_last_line", "")).startswith("CLOSE: YES"):
        bad.append(f"/close did not land: {close}")
    asked = [u["input"]["questions"][0].get("header") for u in _tool_uses(main) if u.get("name") == "AskUserQuestion"]
    if asked != ["Rating"]:
        bad.append(f"questions asked: {asked}")
    if r.hook_errors:
        bad.append(f"hook errors: {[(e['hook'], e['step'], e['how']) for e in r.hook_errors]}")
    if r.connections:
        bad.append(f"{r.connections} network attempt(s)")
    blocks = [(b["hook"], b["step"]) for b in r.blocks]
    g2 = G2_REPORTER[settings]
    want = [(CANARY, "SessionStart startup")] if host else []
    want += [(g2, "/close Step 0 round 1 Agent(dev) stop")] if case == "g2" else []
    if blocks != want:
        bad.append(f"blocks {blocks}, expected {want}")
    elif host:  # the host's block: the base canary's at the session's start, failing on the host's files only
        b = r.blocks[0]
        fails = [ln for ln in b["text"].splitlines() if ln.startswith("canary-verify[FAIL]")]
        expected = host + [f"canary-verify[FAIL]: {len(host)} hook(s) broken — see preceding lines"]
        if b["event"] != "SessionStart" or b["how"] != "exit2" or fails != expected:
            bad.append(f"the host's block {(b['event'], b['how'])}: failure lines {fails}, expected {expected}")
        before = [ev for ev in r.hook_events()[:land.get("event", 0)] if ev["event"] == "SessionStart"
                  and any(h["hook"] == CANARY and h["verdict"] == "block" for h in ev["hooks"])]
        if [ev["label"] for ev in before] != ["SessionStart startup"]:
            bad.append(f"the base canary's refusal is not the one SessionStart before the landing: "
                       f"{[ev['label'] for ev in before]}")
    if case == "g2" and not any(f.get("key") == "routed dev stop blocked" and g2 in f["value"].get("hooks", [])
                                for f in r.facts):
        bad.append("G2 did not refuse the routed dev's first stop")
    return bad


@pytest.mark.parametrize("settings", SETTINGS)
@pytest.mark.parametrize("case", [pytest.param(c, marks=pytest.mark.replay(f"A4 (g) in-flight {c}", COSTS[c]))
                                  for c in CASES])
def test_inflight_blocked_do_report_lands_through_dev(request, tmp_path_factory, case, settings):
    r = _results(request, tmp_path_factory, case)[settings]
    bad = _verdict(case, r, settings, _STATE["host"])
    assert not bad, f"{case} ({settings} settings), {r.out}:\n  " + "\n  ".join(bad) + "\n" + r.explain()


TREE_BLOCKED = suite.Scenario("A4 (g) variant=blocked on this tree's /do", "do", (("variant", "blocked"),),
                              ("do",), 20)


@pytest.mark.replay(suite.replay_key(TREE_BLOCKED, "armed"), TREE_BLOCKED.cost)
def test_this_trees_do_cannot_end_blocked(runner):
    """variant=blocked on this tree's /do text, which names one terminal: the driver refuses it before
    the /do is typed (no prompt, no do-report)."""
    r = runner.run(TREE_BLOCKED, "armed")
    err = r.summary.get("driver_error") or r.error
    assert "names one terminal" in err and "TextNotFound" in err, r.explain()
    assert not r.terminal("do") and not any(e.get("event") == "UserPromptSubmit" for e in r.hook_events()), \
        r.explain()
