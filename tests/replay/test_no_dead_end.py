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
terminal (exit 0). This file's own replays (drivers/_deadend.py, and fault replays of /dev through
tests/replay/faults.py) reach the gates of the pipelines' own flows.

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

DO_CASES = ("do-report", "do-report-ask", "do-dispatch", "todo-canonical", "todo-sequence", "checklist-lock")
PLAIN_CASES = ("bg-dispatch", "stale-worktree", "obligation", "forged-ack")
CASES = {c: suite.Scenario(f"dead end: {c}", "_deadend", (("case", c),),
                           ("do",) if c in DO_CASES else ("plain",), 60) for c in DO_CASES + PLAIN_CASES}
CASES["dev-early"] = suite.Scenario("dead end: dev-early", "_deadend", (("case", "dev-early"),), ("dev",), 100)
ARMED_CASES = ("obligation", "forged-ack")  # G1 and G2 block only armed (CLAUDE_OBLIGATION_*=block)
DEV = next(s for s in suite.COMPLIANT if s.name == "/dev singular")
FAULTS = {"dev report missing": "missing@agent:dev Write docs/dev/dev-report-*",
          "qa report missing": "missing@agent:qa Write docs/dev/qa-report-*"}
FORGED = re.compile(r"^ESCALATION_ACK [0-9a-f]+\s*$", re.M)


def case_key(case: str) -> str:
    return suite.replay_key(CASES[case], "armed" if case in ARMED_CASES else "shipped")


def fault_key(fault: str) -> str:
    return suite.replay_key(DEV, "armed", (("fault", FAULTS[fault]),))


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


@pytest.mark.parametrize("fault", [pytest.param(f, id=f.replace(" ", "-"),
                                                marks=pytest.mark.replay(fault_key(f), DEV.cost)) for f in FAULTS])
def test_fault_gate_is_cleared_by_its_producers_next_stop(replays, catalog, fault):
    r = replays.get(fault_key(fault))
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    bl = blocks(r, catalog)
    print(f"\n{fault}: " + "; ".join(f"{b['ev']['label']!r} -> {', '.join(s.id + ' ' + catalog.of(s) for s in b['sites'])}"
                                     for b in bl))
    assert bl and all(b["ev"]["event"] == "SubagentStop" for b in bl), \
        f"{fault}: expected the faulted agent's stop to be refused:\n{r.explain()}"
    bad = check_replay(r, catalog, compliant=False)
    assert not bad, "\n".join(bad)


# ---------------------------------------------------------------- (iv) recall over the session

@pytest.mark.every_shard
def test_every_block_of_the_session_maps_to_a_site(replays, catalog):
    results = [(key, r) for key, r in replays._results.items() if r.summary]
    bad, reached = [], collections.defaultdict(set)
    n = 0
    for (key, _settings, faults), r in results:
        is_compliant = r.scenario in suite.COMPLIANT and key == r.scenario.key and not faults
        for b in blocks(r, catalog):
            n += 1
            for s in b["sites"]:
                ok = cleared(events(r), b["ev"]) is not None and r.rc == 0 and r.reached()
                reached[s.id].add(f"{r.scenario.name} ({r.settings}){'' if ok else ' NOT CLEARED'}")
        bad += check_replay(r, catalog, compliant=is_compliant)
    print(f"\nrecall: {n} blocks in {len(results)} replays of this session, each mapped to an enumerated site"
          if not bad else f"\nrecall: {n} blocks in {len(results)} replays")
    print("G sites with the replays that reach and clear them:")
    for s in catalog.sites:
        if catalog.of(s) == "G":
            print(f"  {s.id} {s.func}: {'; '.join(sorted(reached.get(s.id, ()))) or 'no replay of this session reaches it'}")
    assert not bad, "\n".join(bad)


# ---------------------------------------------------------------- the wake's two gates (P1c X8, row 17)

WAKE_LATE = suite.Scenario("dead end: the wake's gates", "overnight", (("variant", "plain"), ("wake", "late")),
                           ("dev-overnight",), 600)


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
    assert sorted(s.func for b in bl for s in b["sites"]) == ["_block_open_wake", "check_wake_step"], r.explain()
    assert all(catalog.of(s) == "G" for b in bl for s in b["sites"]), r.explain()
    bad = check_replay(r, catalog, compliant=False)
    assert not bad, "\n".join(bad)
