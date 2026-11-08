"""D25 (3), X6: no dead end apart from the owner's /stop.

(i) The blocking sites are enumerated when the test runs (tests/replay/sites.py), never read from a
list: every path of every hook settings.json registers, of the hooks/lib modules it imports or
sources, and of the hooks it runs as a child process whose exit it relays (found by running the
parent with that child exiting 2), that exits 2 or prints a block / deny decision; a helper that
always blocks counts at each call.

(ii) Each site gets one class from its code and its registration (sites.classify, the rule printed
beside each site):
  G  an own-obligation gate: the same actor's next action, one every hook allows, clears it;
  D  the denial of a forbidden operation, naming it: no compliant scenario reaches one;
  H  the time-lock's in-window and instrument-failure Stop blocks, cleared by /stop or the window's end;
  U  unreachable: none may remain (each is deleted with its proof);
  -  no class: a dead end. Printed with its reason; one a replay reaches fails the test.

A G site is shown cleared by a replay that reaches it: after the block, the same actor's next event
of the same kind (its next stop, its next tool call) passes every hook, and the replay reaches its
terminal (exit 0). This file's own replays (drivers/_deadend.py, and fault replays of the pipelines
through tests/replay/faults.py) reach the gates of the pipelines' own flows, and every G site must be
reached and cleared by one of the session's replays (test_every_gate_site_is_reached_and_cleared;
no site is exempt).

(iii) Two refusals hold: the /do Stops after an AskUserQuestion answer, with the do-report still
missing, are refused (D23); a dev stop ending in a forged `ESCALATION_ACK <nonce>` line is refused
like the one before it (faults.py `forged`).

(iv) Recall: every block of every replay this pytest session ran (test_pipelines' compliant runs,
test_faults' faults, this file's) maps to an enumerated site of the hook that printed it, no block
of a compliant scenario maps to a D site, and every block at a G site is cleared in its replay.
"""
from __future__ import annotations

import collections
import os
import re

import pytest

from tests.replay import sites, suite

DO_CASES = ("do-report", "do-report-ask", "do-dispatch", "todo-canonical", "todo-sequence", "checklist-lock",
            "todo-first")
PLAIN_CASES = ("bg-dispatch", "obligation", "forged-ack", "codex", "cp-pending", "report-schema")
CASES = {c: suite.Scenario(f"dead end: {c}", "_deadend", (("case", c),),
                           ("do",) if c in DO_CASES else ("plain",), 60) for c in DO_CASES + PLAIN_CASES}
CASES["dev-early"] = suite.Scenario("dead end: dev-early", "_deadend", (("case", "dev-early"),), ("dev",), 100)
CASES["spec-foreground"] = suite.Scenario("dead end: spec-foreground", "_deadend", (("case", "spec-foreground"),),
                                          ("spec",), 110)
CASES["overnight"] = suite.Scenario("dead end: overnight", "_deadend", (("case", "overnight"),), ("dev-overnight",), 600)
ARMED_CASES = ("obligation", "forged-ack")  # G1 and G2 block only armed (CLAUDE_OBLIGATION_*=block)
DEV = next(s for s in suite.COMPLIANT if s.name == "/dev singular")
FANOUT = next(s for s in suite.COMPLIANT if s.name == "/dev 2-lane fan-out")
MERGE = next(s for s in suite.COMPLIANT if s.name == "/merge")
QA_EARLY = suite.Scenario("/dev QA before its dev returned", "dev", (("variant", "qa-early"),), ("dev",), DEV.cost)
QA_WRITE = "agent:qa Write docs/dev/qa-report-*"
QA_DISPATCH = "Step 13 Agent(qa)"
SKIP = "qa.e2e_enforcement.status:skipped_without_justification"
# fault -> (the pipeline's compliant scenario, settings, what the replay injects: tests/replay/faults.py)
FAULTS = {
    "dev report missing": (DEV, "armed", "missing@agent:dev Write docs/dev/dev-report-*"),
    "qa report missing": (DEV, "armed", f"missing@{QA_WRITE}"),
    "qa e2e not an object": (DEV, "shipped", f"invalid@{QA_WRITE}=qa.e2e_enforcement:performed"),
    "qa e2e absent": (DEV, "shipped", f"invalid@{QA_WRITE}=-qa.e2e_enforcement"),
    "qa e2e unjustified skip": (DEV, "shipped", f"invalid@{QA_WRITE}={SKIP}"),
    "qa report missing, no obligation": (DEV, "shipped", f"noblock@{QA_DISPATCH};missing@{QA_WRITE}"),
    "qa e2e unjustified skip, no obligation": (DEV, "shipped", f"noblock@{QA_DISPATCH};invalid@{QA_WRITE}={SKIP}"),
    # The dev's own Write of the listing: P6's G2 file-list check refuses it at the dev's own stop.
    "dev report lists an ignored file": (DEV, "armed", "invalid@agent:dev Write docs/dev/dev-report-*="
                                         'dev.files_created:["toy/__pycache__/__init__.cpython-312.pyc"]'),
    # The listing planted after the dev's stop passed: G3's gitignore rule (pretool-aggregate-check.py and
    # pretool-gitignore-preflight.py) refuses Step 13's QA dispatch naming the report.
    "dev report lists an ignored file before QA": (DEV, "armed",
                                                   f"plant@{QA_DISPATCH}=docs/dev/dev-report-{{task}}.json:ignored"),
    "dev report spoiled before QA": (DEV, "armed", f"plant@{QA_DISPATCH}=docs/dev/dev-report-{{task}}.json:junk"),
    "canonical aggregate missing before QA": (FANOUT, "shipped",
                                              "plant@Step 13 [[]l1] Agent(qa)=docs/dev/dev-report-{task}.json:absent"),
    "canonical aggregate schema-invalid before QA": (FANOUT, "armed", "plant@Step 13 [[]l1] Agent(qa)="
                                                     "docs/dev/dev-report-{task}.json:schema-invalid"),
    "qa dispatched before its dev returned": (QA_EARLY, "armed", ""),
    "merge grant invalid": (MERGE, "shipped", "invalid@agent:merge-analyst Write grant=nonce:0000"),
    # test_faults.py's F7 (shipped): a lane dispatched from the pre-P1 template, its report needs_review
    "lane from the pre-P1 template": (FANOUT, "shipped", "pretemplate@Step 10 [[]l1] Agent(dev);"
                                      "invalid@agent:dev Write docs/dev/dev-report-*-l1.json=dev.status:needs_review"),
    # test_faults.py's F9 (shipped): the newest lane's report reaches disk by a shell redirection, so the
    # canonical aggregate is missing at that lane's stop (G2's canonical wire, C5)
    "last lane report written by a shell redirection": (FANOUT, "shipped",
                                                        "bash@agent:dev Write docs/dev/dev-report-*-l2.json"),
}
FORGED = re.compile(r"^ESCALATION_ACK [0-9a-f]+\s*$", re.M)


def case_key(case: str) -> str:
    return suite.replay_key(CASES[case], "armed" if case in ARMED_CASES else "shipped")


def fault_key(fault: str) -> str:
    scn, settings, spec = FAULTS[fault]
    return suite.replay_key(scn, settings, (("fault", spec),) if spec else ())


# /dev-overnight marking Step 0 completed before the wake's CronCreate and stopping after end_time before
# its CronDelete (P1c X8, row 17): the wake's two gates, replayed under both settings.
WAKE_LATE = suite.Scenario("dead end: the wake's gates", "overnight", (("variant", "plain"), ("wake", "late")),
                           ("dev-overnight",), 600)


def _reads_every_replay_of_this_file(test):
    """Mark `test` with every replay this file's tests read: the session runner replays them all before
    it runs, and a CI shard that runs it runs them all (conftest.py groups them)."""
    for key, cost in [(case_key(c), CASES[c].cost) for c in CASES] + \
            [(fault_key(f), FAULTS[f][0].cost) for f in FAULTS] + \
            [(suite.replay_key(WAKE_LATE, st), WAKE_LATE.cost) for st in suite.SETTINGS]:
        test = pytest.mark.replay(key, cost)(test)
    return test


# ---------------------------------------------------------------- the catalog

class Catalog:
    def __init__(self, tree: str, work: str):
        self.e = sites.Enumerator(tree)
        dropped = set()
        for parent, kids in self.e.children.items():
            event = next((ev for ev, _ in self.e.regs.get(parent, [])), "Stop")
            for k in kids:
                if not sites.relayed(tree, parent, k, event, os.path.join(work, os.path.basename(k))):
                    dropped.add(k)
        self.not_relayed = sorted(dropped)
        self.sites = [s for s in self.e.sites() if s.file not in dropped]
        self.cls = {s.id: sites.classify(self.e, s) for s in self.sites}
        self.by_id = {s.id: s for s in self.sites}

    def of(self, s) -> str:
        return self.cls[s.id][0]

    def table(self) -> str:
        per: dict = collections.defaultdict(collections.Counter)
        for s in self.sites:
            for hook in sorted({r[0] for r in s.regs}):
                per[hook][self.of(s)] += 1
        rows = [{"hook": h, **{c: per[h].get(c, 0) for c in "GDHU-"}, "sites": sum(per[h].values())}
                for h in sorted(per)]
        tot = collections.Counter(self.of(s) for s in self.sites)
        rows.append({"hook": "(distinct sites)", **{c: tot.get(c, 0) for c in "GDHU-"}, "sites": len(self.sites)})
        return suite.table(rows)


@pytest.fixture(scope="module")
def catalog(tmp_path_factory):
    return Catalog(suite.REPO, str(tmp_path_factory.mktemp("relay")))


# ---------------------------------------------------------------- what a replay's files say

def events(r) -> list[dict]:
    """Every hook event of the replay, in order: its payload (invocations.jsonl) and its hooks' runs
    with their text (hooks.jsonl, one line per event in the same order)."""
    inv = suite._jsonl(os.path.join(r.run_dir, "invocations.jsonl"))
    out = []
    for i, (ev, iv) in enumerate(zip(r.hook_events(), inv)):
        p = iv.get("payload") or {}
        out.append({"i": i, "event": ev["event"], "label": ev.get("label"), "payload": p,
                    "actor": (p.get("session_id"), p.get("agent_id")), "hooks": ev.get("hooks", [])})
    return out


def blocks(r, catalog) -> list[dict]:
    """Each block of the replay with the enumerated sites it maps to."""
    out = []
    for ev in events(r):
        for h in ev["hooks"]:
            if h.get("verdict") != "block":
                continue
            text = "\n".join((h.get("refusal_head") or "", h.get("stderr") or "", h.get("stdout") or ""))
            out.append({"ev": ev, "hook": h["hook"], "text": text, "sites": sites.match(h["hook"], text, catalog.sites)})
    return out


def cleared(evs: list[dict], ev: dict) -> dict | None:
    """The same actor's next event of the same kind after `ev` that every hook allowed, if any."""
    for nxt in evs[ev["i"] + 1:]:
        if nxt["actor"] == ev["actor"] and nxt["event"] == ev["event"]:
            if not any(h.get("verdict") == "block" for h in nxt["hooks"]):
                return nxt
    return None


def check_replay(r, catalog, compliant: bool) -> list[str]:
    """The X6 failures one replay shows (empty: none)."""
    bad = []
    evs = events(r)
    for b in blocks(r, catalog):
        where = f"{r.scenario.name} ({r.settings}) at {b['ev']['label']!r}: {b['hook']}"
        if not b["sites"]:
            bad.append(f"{where}: the block maps to no enumerated site (recall): {b['text'][:300]}")
            continue
        classes = {catalog.of(s) for s in b["sites"]}
        ids = ", ".join(s.id for s in b["sites"])
        if compliant and "D" in classes:
            bad.append(f"{where}: a compliant scenario reached the D site {ids}")
        if "-" in classes:
            bad.append(f"{where}: a replay reached {ids}, a site that fits no class (a dead end)")
        if classes & {"G"} and not cleared(evs, b["ev"]):
            bad.append(f"{where}: G site {ids} is not cleared by the same actor's next {b['ev']['event']}")
        if classes & {"G"} and not (r.rc == 0 and not r.summary.get("driver_error") and r.reached()):
            bad.append(f"{where}: the replay reaching G site {ids} does not exit 0 at its terminal:\n{r.explain()}")
    return bad


# ---------------------------------------------------------------- (i), (ii)

def test_every_blocking_site_is_enumerated_and_classified(catalog):
    print("\nsites per hook and class (G gate, D denial, H time-lock, U unreachable, - no class):")
    print(catalog.table())
    if catalog.not_relayed:
        print("child processes whose exit 2 the parent does not relay (their sites are no gate block): "
              + ", ".join(catalog.not_relayed))
    print("\nH sites:")
    for s in catalog.sites:
        if catalog.of(s) == "H":
            print(f"  {s.id} {s.func}: {catalog.cls[s.id][1]}")
    print("\nsites that fit no class (dead ends no replay reaches; outside the D25 scenarios and faults):")
    for s in catalog.sites:
        if catalog.of(s) == "-":
            print(f"  {s.id} {s.func} [{', '.join(sorted({r[0] for r in s.regs}))[:120]}]: {catalog.cls[s.id][1]}")
    assert catalog.sites, "the enumerator found no blocking site"
    every = catalog.e.sites()
    missed = [x for hook in catalog.e.regs for x in sites.unaccounted(catalog.e, hook, every)]
    assert not missed, "exit-2 calls in registered hooks that the enumeration does not account for:\n  " + \
        "\n  ".join(missed)
    unreachable = [(s.id, catalog.cls[s.id][1]) for s in catalog.sites if catalog.of(s) == "U"]
    assert not unreachable, "unreachable sites remain; delete each with its proof:\n" + \
        "\n".join(f"  {i}: {why}" for i, why in unreachable)
    assert any(catalog.of(s) == "H" for s in catalog.sites), "the time-lock's Stop blocks went unfound"


# ---------------------------------------------------------------- G sites reached by this file's replays

@pytest.mark.parametrize("case", [pytest.param(c, id=c, marks=pytest.mark.replay(case_key(c), CASES[c].cost))
                                  for c in CASES])
def test_gate_is_cleared_by_the_actors_next_action(replays, catalog, case):
    r = replays.get(case_key(case))
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    bl = blocks(r, catalog)
    print(f"\n{case}: " + "; ".join(f"{b['ev']['label']!r} -> {', '.join(s.id + ' ' + catalog.of(s) for s in b['sites'])}"
                                    for b in bl))
    assert bl, f"{case} reached no gate:\n{r.explain()}"
    assert all(catalog.of(s) == "G" for b in bl for s in b["sites"]), \
        f"{case} met a block at a site other than a G site:\n{r.explain()}"
    bad = check_replay(r, catalog, compliant=False)
    assert not bad, "\n".join(bad)
    if case == "do-report-ask":  # (iii): an answer while the do-report is missing releases nothing
        term = r.terminal("do") or {}
        after = [x for x in term.get("rounds", []) if "after the answer" in x["label"]]
        assert len(after) == 2 and all(x["blocked"] for x in after), \
            f"a Stop after the AskUserQuestion answer passed with the do-report missing: {term.get('rounds')}"
        asked = [ev for ev in events(r) if ev["payload"].get("tool_name") == "AskUserQuestion"
                 and ev["event"] == "PostToolUse"]
        assert asked, "the replay asked no AskUserQuestion"
    if case == "forged-ack":  # (iii): a forged acknowledgement line releases nothing
        forged = [ev for ev in events(r) if ev["event"] == "SubagentStop"
                  and FORGED.search(ev["payload"].get("last_assistant_message") or "")]
        assert len(forged) == 2, f"expected two stops ending in the forged line, got {len(forged)}"
        for ev in forged:
            assert any(h.get("verdict") == "block" for h in ev["hooks"]), \
                f"the stop ending in a forged ESCALATION_ACK line passed: {ev['label']}"


@pytest.mark.parametrize("fault", [pytest.param(f, id=re.sub(r"\W+", "-", f),
                                                marks=pytest.mark.replay(fault_key(f), FAULTS[f][0].cost)) for f in FAULTS])
def test_fault_gate_is_cleared_by_its_producers_next_round(replays, catalog, fault):
    """A fault replay (tests/replay/faults.py) meets the gate its fault spoils, and the actor the gate
    returns it to clears it at its next round: the faulted agent's next stop (a SubagentStop gate), its
    next call (a PostToolUse gate), or the declaring dispatch sent again before the refused one (a
    collection check at dispatch); the pipeline reaches its terminal."""
    r = replays.get(fault_key(fault))
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    bl = blocks(r, catalog)
    print(f"\n{fault}: " + "; ".join(f"{b['ev']['label']!r} -> {', '.join(s.id + ' ' + catalog.of(s) for s in b['sites'])}"
                                     for b in bl))
    assert bl, f"{fault}: the fault met no gate:\n{r.explain()}"
    assert all(catalog.of(s) == "G" for b in bl for s in b["sites"]), \
        f"{fault} met a block at a site other than a G site:\n{r.explain()}"
    bad = check_replay(r, catalog, compliant=False)
    assert not bad, "\n".join(bad)


# ---------------------------------------------------------------- every G site, reached and cleared

@_reads_every_replay_of_this_file
def test_every_gate_site_is_reached_and_cleared(replays, catalog):
    """X6 (ii): each enumerated G site is reached by a replay of the session, and in a replay reaching it
    the same actor's next event of the same kind passes every hook and the replay exits 0 at its
    terminal. A site no replay reaches fails here: give it a replay, or delete it with its proof (U)."""
    cleared_by, failed = collections.defaultdict(set), collections.defaultdict(set)
    for (key, _settings, _faults), r in replays._results.items():
        if not r.summary:
            continue
        evs = events(r)
        ok = r.rc == 0 and not r.summary.get("driver_error") and r.reached()
        for b in blocks(r, catalog):
            for s in b["sites"]:
                name = f"{r.scenario.name} ({r.settings}{', ' + _faults[0][1] if _faults else ''})"
                (cleared_by if ok and cleared(evs, b["ev"]) else failed)[s.id].add(name)
    rows, unreached = [], []
    for s in catalog.sites:
        if catalog.of(s) != "G":
            continue
        rows.append({"site": s.id, "function": s.func, "cleared by": "; ".join(sorted(cleared_by[s.id])) or "-",
                     "reached, not cleared": "; ".join(sorted(failed[s.id])) or "-"})
        if not cleared_by[s.id]:
            unreached.append(f"{s.id} {s.func}: " + ("reached by " + "; ".join(sorted(failed[s.id])) +
                                                     " but not cleared" if failed[s.id] else "no replay reaches it"))
    print("\nG sites, the replays that reach them and clear them:\n" + suite.table(rows))
    assert not unreached, "G sites with no replay that reaches and clears them:\n  " + "\n  ".join(unreached)


# ---------------------------------------------------------------- (iv) recall over the session

@pytest.mark.every_shard
def test_every_block_of_the_session_maps_to_a_site(replays, catalog):
    results = [(key, r) for key, r in replays._results.items() if r.summary]
    bad, n = [], 0
    for (key, _settings, faults), r in results:
        is_compliant = r.scenario in suite.COMPLIANT and key == r.scenario.key and not faults
        n += len(blocks(r, catalog))
        bad += check_replay(r, catalog, compliant=is_compliant)
    print(f"\nrecall: {n} blocks in {len(results)} replays of this session, each mapped to an enumerated site"
          if not bad else f"\nrecall: {n} blocks in {len(results)} replays")
    assert not bad, "\n".join(bad)


# ---------------------------------------------------------------- the wake's two gates (P1c X8, row 17)

# WAKE_LATE (defined above, beside the cases) is replayed here.


@pytest.mark.parametrize("key", [pytest.param(suite.replay_key(WAKE_LATE, s), id=s,
                                              marks=pytest.mark.replay(suite.replay_key(WAKE_LATE, s), WAKE_LATE.cost))
                                 for s in suite.SETTINGS])
def test_the_wakes_gates_are_cleared_by_the_actors_next_action(replays, catalog, key):
    """/dev-overnight marking Step 0 completed before the wake's CronCreate, and stopping after end_time
    before its CronDelete: each refusal is a G site (pretool-todo-validate.py's wake rule, the time-lock's
    wake check) that the main agent's next action clears, and the session reaches its terminal."""
    r = replays.get(key)
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    bl = blocks(r, catalog)
    assert sorted(s.func for b in bl for s in b["sites"]) == ["check_wake_step", "wake_lock"], r.explain()
    assert all(catalog.of(s) == "G" for b in bl for s in b["sites"]), r.explain()
    bad = check_replay(r, catalog, compliant=False)
    assert not bad, "\n".join(bad)
