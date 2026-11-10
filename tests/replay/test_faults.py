"""D25 (2): each injected fault goes back to its own producer, named by artifact and failing check, and
is repaired at that producer's next round with no human action; the pipeline reaches its terminal.

Each fault is a replay of the compliant 2-lane /dev fan-out (suite.COMPLIANT) with one driver argument
`fault` (tests/replay/faults.py), under the tree's settings ("shipped") and armed. What a test checks
is read from the replay's own files (invocations.jsonl: every hook event with its payload; blocks.json;
faults.json; terminals.json), never from a list kept here:

* every block's text names the faulted artifact's path and the failing check, and no hook errs;
* the block lands on the expected producer: the agent whose dispatch declared that path in its
  obligation (the Agent call's prompt and the agent id its result carries), or, for a dispatch that
  declares nothing (F7b), the agent that wrote the report; a dispatch refused at its PreToolUse goes back
  to the orchestrator, whose next round is the declaring dispatch again;
* that same agent writes the repair and its next stop passes; the pipeline reaches its terminal;
* no human event between the injection and the terminal (no prompt typed after /dev, no
  AskUserQuestion answer);
* F2g: the stop that ends with the forged ESCALATION_ACK line is blocked like the one before it;
* F3b (a stale report nothing in the pipeline produced): no block names it, the terminal is reached.
* F9 (the last lane writes its report by a shell redirection, which the canonical aggregate's
  producer, the lane-completeness watch on Write and Edit, never sees): the block lands on that
  lane's own stop and names the canonical aggregate and `canonical_missing`; the lane's repair runs
  the watch, so no QA dispatch is refused and none is sent again (C5 for G3's canonical).

Interrupted session and resume after a usage limit (F5, F5f, F6; tests/replay/recovery.py): the
session is cut while the dev subagent runs, after its Edit; the owner's /restart (HX) resumes that
same agent through commands/restart.md's recovery and finalizes it; the main agent then completes the
dev step with the resumed call (no replacement Agent call) and /dev reaches its terminal. Each runs
with the tree's settings ("shipped") and armed (G1-G3 block).

The held git index.lock (F4, F4c, F4s; R14, X7): the shared-index sync (scripts/session-index.py
sync-shared, the changelog-analyst's step after each commit) waits while a process holds the lock and
removes, once and saying so, a lock no process holds that is older than the sync.

An unfinished cycle the owner's /close or /commit meets (F8, F8q, F8p, F8c, F8r; tests/replay/routing.py):
the gap names the artifact's path and its check and no role (D21); /close's one chain call (Step 0),
its close-QA round (F8p) or /commit's chain call (Step 5: F8c, and F8r, the QA report of a `/close
--late-repair` removed after CLOSE: YES, which the late-repair state compares no longer) finds it; the
routing loop dispatches again what P1b's E3 reader returns for that path (the same subagent_type, task
id, lane and obligation template, a fresh dispatched_at), that dispatch's own agent writes the repair,
and the typed /close or /commit (HX) is the only human event; /close ends in its Terminal form and
F8c's and F8r's commits land.

What /close does where no agent can produce a gap's artifact (P4's review, findings 1 and 2): F8n, BA's
ticket missing in a /close whose task's /dev session is gone from the store while an earlier /close's
re-dispatch survives: the reader names no owner for it (never /close's own rating step, which runs no
dispatch, D8), Routes asks the owner (header Request), and nothing writes BA's artifact; F8a, `/close
--auto` over the cycle and an old task docs/dev holds with no record of its dispatches: the discovery passes
the old task over, its reason on stderr and in the batch line, and the cycle lands (D25).
"""
from __future__ import annotations

import json
import os
import re

import pytest

from tests.replay import recovery, routing, suite

FANOUT = next(s for s in suite.COMPLIANT if s.name == "/dev 2-lane fan-out")
L1_DEV = "agent:dev Write docs/dev/dev-report-*-l1.json"
L2_QA = "agent:qa Write docs/dev/qa-report-*-l2.json"
L1_DEV_DISPATCH = "Step 10 [[]l1] Agent(dev)"
L1_QA_DISPATCH = "Step 13 [[]l1] Agent(qa)"

# fault -> (what the replay injects, what kind of outcome the test asserts)
FAULTS = {
    "F1": f"missing@{L1_DEV}",
    "F1q": f"missing@{L2_QA}",
    "F2": f"invalid@{L1_DEV}=dev.status:done,-dev.files_modified",
    "F2j": f"notjson@{L1_DEV}",
    "F2g": f"forged@{L1_DEV}=dev.status:done,-dev.files_modified",
    "F3b": f"plant@{L1_QA_DISPATCH}=docs/dev/qa-report-{{task}}.json:qa-report.v1",
    "F7": f"pretemplate@{L1_DEV_DISPATCH};invalid@{L1_DEV}=dev.status:needs_review",
    "F7b": f"noblock@{L1_DEV_DISPATCH};invalid@{L1_DEV}=dev.status:needs_review",
    "F9": "bash@agent:dev Write docs/dev/dev-report-*-l2.json",
}


# the failing check each fault's block must name, beside the artifact's path
CHECK = {
    "F1": r"absent|no such file", "F1q": r"absent|no such file",
    "F2": r"files_modified|'done'", "F2g": r"files_modified|'done'",
    "F2j": r"JSON|[Pp]ars|[Dd]ecod|Expecting|Unterminated",
    "F7": r"needs_review|required_values", "F7b": r"needs_review|missing_block",
    "F9": r"canonical_missing",
}


def key(fault: str, settings: str) -> str:
    return suite.replay_key(FANOUT, settings, (("fault", FAULTS[fault]),))


CASES = [pytest.param(fault, s, id=f"{fault}-{s}", marks=pytest.mark.replay(key(fault, s), FANOUT.cost))
         for fault in FAULTS for s in suite.SETTINGS]


# ---------------------------------------------------------------- what the run's files say

def invocations(r) -> list[dict]:
    return suite._jsonl(os.path.join(r.run_dir, "invocations.jsonl"))


def fault_records(r) -> list[dict]:
    return suite._json(os.path.join(r.run_dir, "faults.json"), [])


_OB = re.compile(r'<obligation\s+v="1"\s*>\s*(\{.*?\})\s*</obligation>', re.S)


def declaring_agents(r, path: str) -> list[str]:
    """The agents whose Agent call's prompt carries an obligation declaring `path` (its tool_use id ->
    the agent id the call's result carries)."""
    tool_to_agent, declaring = {}, []
    for ev in invocations(r):
        p = ev["payload"]
        if ev["event"] != "PreToolUse" and p.get("tool_name") == "Agent":
            resp = p.get("tool_response") or {}
            if resp.get("agentId"):
                tool_to_agent[p.get("tool_use_id")] = resp["agentId"]
        if ev["event"] == "PreToolUse" and p.get("tool_name") == "Agent":
            m = _OB.search((p.get("tool_input") or {}).get("prompt") or "")
            try:
                arts = json.loads(m.group(1)).get("artifacts") or [] if m else []
            except ValueError:
                arts = []
            if any(a.get("path") == path for a in arts):
                declaring.append(p.get("tool_use_id"))
    return [tool_to_agent[t] for t in declaring if t in tool_to_agent]


def writers(r, path: str) -> list[tuple[int, str]]:
    """(event index, agent id) of every Write or Edit of `path` that ran (PostToolUse)."""
    out = []
    for i, ev in enumerate(invocations(r)):
        p = ev["payload"]
        if ev["event"] == "PostToolUse" and p.get("tool_name") in ("Write", "Edit") and \
                ((p.get("tool_input") or {}).get("file_path") or "").endswith("/" + path):
            out.append((i, p.get("agent_id")))
    return out


def stops(r, agent: str) -> list[dict]:
    """The agent's SubagentStop events in order: index, round flag, blocked, the hooks' text."""
    out = []
    for i, ev in enumerate(invocations(r)):
        p = ev["payload"]
        if ev["event"] == "SubagentStop" and p.get("agent_id") == agent:
            blocked = [h for h in ev["hooks"] if h["verdict"] == "block"]
            out.append({"i": i, "active": p.get("stop_hook_active"), "blocked": bool(blocked),
                        "hooks": [h["hook"] for h in blocked], "message": p.get("last_assistant_message") or "",
                        "label": ev["label"]})
    return out


def human_events(r, after: int) -> list[str]:
    """Prompts typed and AskUserQuestion answers after event index `after`."""
    out = []
    for i, ev in enumerate(invocations(r)):
        if i <= after:
            continue
        p = ev["payload"]
        if ev["event"] == "UserPromptSubmit" or (ev["event"] == "PostToolUse"
                                                 and p.get("tool_name") == "AskUserQuestion"):
            out.append(f"{ev['event']} {ev['label']}")
    return out


def blocks(r) -> list[dict]:
    """Every block of the run with its hook's own text (blocks.json keeps it normalised: ids and paths
    replaced), from the hook events: event, label, hook, the agent whose event it was, text."""
    out = []
    for ev, inv in zip(r.hook_events(), invocations(r)):  # one line per event in both, in order
        for h in ev.get("hooks", []):
            if h.get("verdict") == "block":
                out.append({"event": ev["event"], "step": ev["label"], "hook": h["hook"],
                            "agent": inv["payload"].get("agent_id"),
                            "text": (h.get("stderr") or "") + (h.get("stdout") or "")})
    return out


def first_index(r, label: str) -> int:
    return next((i for i, ev in enumerate(invocations(r)) if ev["label"] == label), -1)


def injected_at(r, f: dict) -> int:
    """The event index of the fault's injection: its step's first event; a write that never ran (missing)
    has none, so the faulted agent's first event, which comes after /dev was typed."""
    i = first_index(r, f.get("label") or "")
    if i < 0:
        i = next((k for k, ev in enumerate(invocations(r)) if ev["payload"].get("agent_id") == f.get("agent")), -1)
    assert i > 0, f"the injection of {f} is not in the run's events"
    return i


def row(fault: str, settings: str, r) -> dict:
    """The fault table's row (A4), read from the run's files."""
    recs = fault_records(r)
    refused = next((f for f in recs if f.get("refused_at_dispatch")), None)
    f = refused or next((f for f in reversed(recs) if f.get("path")), {})
    bl = blocks(r)
    if refused:
        named, receiver = refused["label"], all(b["agent"] is None for b in bl)  # the orchestrator's call
    elif f.get("kind") == "plant":  # nothing produced it: no producer, no block expected
        named, receiver = f.get("path"), "none (no block)" if not bl else False
    else:
        named = f.get("path") or "-"
        producers = declaring_agents(r, f.get("path", "")) or [a for _, a in writers(r, f.get("path", ""))][:1]
        receiver = bool(bl) and all(b["agent"] == f.get("agent") for b in bl) and f.get("agent") in producers
    check = "; ".join(sorted({re.search(CHECK[fault], b["text"]).group(0) for b in bl
                              if fault in CHECK and re.search(CHECK[fault], b["text"])})) or "-"
    return {"fault": fault, "mode": settings,
            "blocking hook": ", ".join(sorted({os.path.basename(b["hook"]) for b in bl})) or "-",
            "artifact named": named, "check named": check, "receiving actor = expected producer": receiver,
            "rounds to pass": f.get("rounds", 0), "human events": len(human_events(r, injected_at(r, f)))}


# ---------------------------------------------------------------- the assertions

def _refused_at_dispatch(fault: str, r, d: dict) -> None:
    """A dispatch from an earlier template refused at its PreToolUse (G1): the block lands on the
    orchestrator's Agent call, names the obligation's failing check, and the orchestrator's next
    round, the declaring dispatch from the tree's template, starts and stops with no block."""
    assert d["repaired"] and d["rounds"] == 1, f"{fault}: the refused dispatch was not sent again: {d}"
    for b in blocks(r):
        assert b["event"] == "PreToolUse" and b["agent"] is None and b["step"] == d["label"], \
            f"{fault}: a block other than the refused dispatch's: {b['hook']} at {b['step']}: {b['text'][:300]}"
        assert re.search(CHECK[fault], b["text"]), f"{fault}: the block names no failing check: {b['text'][:400]}"
    again = stops(r, d["agent"])
    assert again and not any(s["blocked"] for s in again), f"{fault}: the next round's stop was blocked: {again}"
    assert not human_events(r, injected_at(r, d)), f"{fault}: human events after the injection"


def _returned_and_repaired(fault: str, r) -> None:
    dispatch = next((f for f in fault_records(r) if f.get("refused_at_dispatch")), None)
    if dispatch is not None:
        return _refused_at_dispatch(fault, r, dispatch)
    recs = [f for f in fault_records(r) if f.get("path")]
    assert recs, f"{fault}: the fault was never injected (faults.json)\n" + r.explain()
    f = recs[-1]
    path, agent = f["path"], f["agent"]
    injected = injected_at(r, f)
    assert r.blocks, f"{fault}: no gate returned {path} to its producer\n" + r.explain()
    for b in blocks(r):
        assert path in b["text"], f"{fault}: a block does not name {path}: {b['hook']} at {b['step']}: {b['text'][:400]}"
        assert re.search(CHECK[fault], b["text"]), f"{fault}: the block names no failing check: {b['text'][:400]}"
        assert b["event"] == "SubagentStop", f"{fault}: a block outside its producer's stop: {b}"
    expected = declaring_agents(r, path) or [a for _, a in writers(r, path)][:1]
    assert agent in expected, f"{fault}: the faulted agent {agent} is not {path}'s producer {expected}"
    mine = stops(r, agent)
    assert mine and mine[0]["blocked"], f"{fault}: the producer's first stop was not returned: {mine}"
    others = [b for b in blocks(r) if b["agent"] != agent]
    assert not others, f"{fault}: a block landed on another actor than the producer: {others}"
    assert not mine[-1]["blocked"] and mine[-1]["active"], f"{fault}: the producer's next round did not pass: {mine}"
    repaired = [i for i, a in writers(r, path) if a == agent and i > mine[0]["i"]]
    assert repaired, f"{fault}: no repair of {path} by {agent} after its returned stop"
    assert f["repaired"], f"{fault}: the faulted agent did not repair ({f})"
    assert not human_events(r, injected), f"{fault}: human events after the injection: {human_events(r, injected)}"


@pytest.mark.parametrize("fault,settings", CASES)
def test_fault_returns_to_its_producer(replays, fault, settings):
    r = replays.get(key(fault, settings))
    assert not r.error and not r.summary.get("driver_error"), r.explain()
    assert not r.hook_errors, f"{fault}: a hook error:\n" + r.explain()
    if fault == "F3b":
        planted = next(f["path"] for f in fault_records(r) if f.get("kind") == "plant")
        named = [b for b in blocks(r) if planted in b["text"]]
        assert not named, f"F3b: the stale {planted}, which no producer wrote, blocked a stop:\n" + r.explain()
        assert not r.blocks, "F3b: a block:\n" + r.explain()
    else:
        _returned_and_repaired(fault, r)
    if fault == "F9":
        lane = next(f["path"] for f in fault_records(r) if f.get("kind") == "bash")
        canonical = re.sub(r"-l2\.json$", ".json", lane)
        assert all(canonical in b["text"] for b in blocks(r)), f"F9: a block does not name {canonical}"
        again = [ev["label"] for ev in invocations(r) if ev["event"] == "PreToolUse"
                 and ev["payload"].get("tool_name") == "Agent" and "(next round)" in ev["label"]]
        assert not again, f"F9: a dispatch was sent again: {again}"
    if fault == "F2g":
        f = next(f for f in fault_records(r) if f.get("kind") == "forged")
        forged = [s for s in stops(r, f["agent"]) if "ESCALATION_ACK" in s["message"]]
        assert forged and all(s["blocked"] for s in forged), f"F2g: the forged line admitted a stop: {forged}"
        assert f["rounds"] == 2, f"F2g: the repair did not follow the forged round: {f}"
    assert r.reached(), f"{fault}: the pipeline did not reach its terminal:\n" + r.explain()
    print(json.dumps(row(fault, settings, r)))


def _restart_cases(scenario: str, fault: str) -> list:
    scn = next(s for s in suite.COMPLIANT if s.name == scenario)
    keys = [suite.replay_key(scn, s, (("fault", fault),)) for s in suite.SETTINGS]
    return [pytest.param(k, id=s, marks=pytest.mark.replay(k, scn.cost * 3)) for k, s in zip(keys, suite.SETTINGS)]


@pytest.mark.parametrize("key", _restart_cases("/dev singular", "cut@agent:dev Edit toy/__init__.py"))
def test_f5_single_lane_cut_after_its_edit_resumed_by_restart(replays, key):
    recovery.assert_resumed_to_terminal(replays.get(key), lanes=1)


@pytest.mark.parametrize("key", _restart_cases("/dev 2-lane fan-out", "cut@agent:dev Edit toy/*"))
def test_f5f_both_lanes_cut_resumed_by_one_restart(replays, key):
    recovery.assert_resumed_to_terminal(replays.get(key), lanes=2)


@pytest.mark.parametrize("key", _restart_cases("/dev singular", "limit@agent:dev Edit toy/__init__.py"))
def test_f6_usage_limit_mid_subagent_resumed_by_restart(replays, key):
    recovery.assert_resumed_to_terminal(replays.get(key), lanes=1)


# ---------------------------------------------------------------- F4, F4c, F4s: a held git index.lock
_DEV = next(s for s in suite.COMPLIANT if s.name == "/dev singular")
_COMMIT = next(s for s in suite.COMPLIANT if s.name == "/commit")

# F4: a live holder takes the lock at /dev's first tool call and releases it after /dev's Stop.
# F4c: a live holder takes it before the changelog-analyst's commit and releases it 20 s after the
#      shared-index sync starts (its commit modifies a tracked path and adds the cycle's files).
# F4s: a stale lock (no process, an hour old) is in place from /commit's first tool call.
_LOCK = {
    "F4": (_DEV, "lock@TodoWrite canonical list=live"),
    "F4c": (_COMMIT, "lock@agent:changelog-analyst Bash stage and commit*=live"),
    "F4s": (_COMMIT, "lock@/commit --auto Bash discovery=stale"),
}


def _lock_key(fault: str, settings: str) -> str:
    scn, spec = _LOCK[fault]
    return suite.replay_key(scn, settings, (("fault", spec),), tag="~" + fault)


def _cases(fault: str) -> list:
    return [pytest.param(_lock_key(fault, s), id=f"{fault}-{s}",
                         marks=pytest.mark.replay(_lock_key(fault, s), _LOCK[fault][0].cost + 30))
            for s in suite.SETTINGS]


def _lock_record(r) -> dict:
    with open(os.path.join(r.run_dir, "faults.json")) as fh:
        recs = [f for f in json.load(fh) if f.get("kind") == "lock"]
    assert len(recs) == 1, f"one lock injection expected, faults.json has {recs}\n" + r.explain()
    return recs[0]


def _human_events_after(r, label: str) -> list:
    """Human events from the injection's step on: a typed prompt, an AskUserQuestion, or an action by an
    actor that is none of the agents, the driver (the replay's own records) and the fault."""
    events = r.hook_events()
    first = next(i for i, ev in enumerate(events) if ev.get("label") == label)
    # The requirement round's ask (P13-1: /dev Step 4b, /spec Step 3a) is every cycle's own step, not a repair.
    found = [f"{ev['event']} at {ev['label']!r}" for ev in events[first:]
             if ev["event"] == "UserPromptSubmit" or ev.get("tool") == "AskUserQuestion"
             and not str(ev.get("label", "")).startswith(("Step 4b AskUserQuestion", "Step 3a AskUserQuestion"))]
    with open(os.path.join(r.run_dir, "markers.jsonl")) as fh:
        marks = [json.loads(line) for line in fh]
    start = next(m["seq"] for m in marks if m["kind"] == "step" and m["value"] == label)
    found += [f"actor {m['value']!r}" for m in marks if m["seq"] > start and m["kind"] == "actor"
              and m["value"] not in ("", "main", "driver", "fault") and not m["value"].startswith("agent:")]
    return found


def _completed(r, rec: dict) -> None:
    """0 gate blocks, 0 hook errors, the terminal reached with no committed path left in `git status
    --porcelain` after the last Stop, nothing reported synced that update-index did not write, and no
    human event between the injection and the terminal."""
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    assert not r.blocks, "the held lock met a gate block:\n" + r.explain()
    assert not r.hook_errors, "the held lock met a hook error:\n" + r.explain()
    assert r.reached(), "the pipeline did not reach its terminal:\n" + r.explain()
    left = {line.split(maxsplit=1)[-1].split(" -> ")[-1] for line in rec["porcelain"]}
    assert not left & set(rec["head_paths"]), f"git status lists committed paths: {sorted(left & set(rec['head_paths']))}"
    assert rec["synced_not_written"] == [], f"reported synced but not written: {rec['synced_not_written']}"
    assert _human_events_after(r, rec["label"]) == []


@pytest.mark.parametrize("key", _cases("F4"))
def test_f4_lock_held_through_dev(replays, key):
    """F4: index.lock held by a live process through a /dev cycle's checkpoints and its Stop: 0 blocks,
    the checkpoint ref advances, and the holder's own release finds its lock (nothing removed it)."""
    r = replays.get(key)
    rec = _lock_record(r)
    _completed(r, rec)
    assert rec["held"] and rec["release"]["holder_unlink"] == "unlinked", rec
    assert rec["checkpoint_after"] and rec["checkpoint_after"] != rec["checkpoint_before"], rec


@pytest.mark.parametrize("key", _cases("F4c"))
def test_f4c_live_lock_at_commit(replays, key):
    """F4c: a live holder from before /commit's commit until 20 s after the shared-index sync starts:
    the sync waits (its wait line names the holder), removes nothing, and completes after the release."""
    r = replays.get(key)
    rec = _lock_record(r)
    _completed(r, rec)
    assert rec["sync_seen"] and rec["release"]["holder_unlink"] == "unlinked", rec
    assert any("SESSION-INDEX WAIT" in line and f"pid {rec['holder_pid']}" in line for line in rec["sync_lines"]), rec
    assert not any("removed" in line for line in rec["sync_lines"]), rec
    assert rec["sync_reports"] and rec["sync_reports"][-1]["synced"], rec


@pytest.mark.parametrize("key", _cases("F4s"))
def test_f4s_stale_lock_at_commit(replays, key):
    """F4s: a stale index.lock at /commit (no process, older than the sync): the sync removes it once,
    says so on stdout, and completes; no lock is left."""
    r = replays.get(key)
    rec = _lock_record(r)
    _completed(r, rec)
    assert sum("removed" in line for line in rec["sync_lines"]) == 1, rec
    assert rec["sync_reports"] and not rec["lock_left_after_stop"], rec


# ---------------------------------------------------------------- F8, F8q, F8p, F8c, F8r: an unfinished cycle met by /close or /commit
def _route_cases(scn: suite.Scenario, faults: tuple = ()) -> list:
    keys = [suite.replay_key(scn, s, faults) for s in suite.SETTINGS]
    return [pytest.param(k, id=s, marks=pytest.mark.replay(k, scn.cost)) for k, s in zip(keys, suite.SETTINGS)]


F8 = suite.Scenario("F8", "close", (("variant", "route"), ("cycle_variant", "fanout")), ("dev", "close"), 400)
F8P = suite.Scenario("F8p", "close", (("variant", "break"), ("cycle_variant", "fanout")), ("dev", "close"), 420)
CHAIN_CALL = "resolve-dev-artifact-chain.py"  # the disposition call: /close's Step 0, /commit's Step 3
F8Q = suite.Scenario("F8q", "close", (("cycle_variant", "fanout"),), ("close",), 420)
F8Q_CUT = (("fault", "cut@Step 13 [[]l2] Agent(qa)"),)
F8C = suite.Scenario("F8c", "commit", (("variant", "commit-route"), ("cycle_variant", "fanout")),
                     ("dev", "close", "commit"), 500)


@pytest.mark.parametrize("key", _route_cases(F8))
def test_f8_lane_qa_report_removed_then_close(replays, key):
    r = replays.get(key)
    f = routing.assert_routed(r, typed="close", source="dispatch", check=CHAIN_CALL)
    assert f["chain"][0]["disposition"] == "incomplete" and [g for g in f["chain"][0]["gaps"]
                                                             if g[0] == f["injection"][0]["path"]], f["chain"]
    assert f["chain"][-1]["disposition"] == "chain_pass", f["chain"]
    routing.assert_close_form(r)


@pytest.mark.parametrize("key", _route_cases(F8Q, F8Q_CUT))
def test_f8q_fanout_cut_before_a_lane_qa_then_close(replays, key):
    r = replays.get(key)
    assert r.terminal("dev") is None, "the cut /dev reached its own terminal"
    tid = r.terminal("close")["task"]
    f = routing.assert_routed(r, typed="close", source="todo_step", check=CHAIN_CALL,
                              path=f"docs/dev/qa-report-{tid}-l2.json")
    # The lane's QA ran in /close's session, from /dev Step 13's template for that lane.
    assert f["dispatches"][f["routed"][0]["tool_use_id"]]["session"] != f["dispatches"][next(iter(f["dispatches"]))]["session"]
    # The disposition owes no completion report (P3's --disposition leaves the chain's completion out): the cut
    # /dev's Step 17 is no gap of /close's (the reader's answer for that path: test_declaring_dispatch.py).
    done = f"docs/dev/completion-{tid}.md"
    assert not [g for _label, g in f["gaps"] if g[0] == done], f["gaps"]
    assert f["chain"][-1]["disposition"] == "chain_pass", f["chain"]
    routing.assert_close_form(r)


@pytest.mark.parametrize("key", _route_cases(F8P))
def test_f8p_lane_product_file_broken_then_close(replays, key):
    r = replays.get(key)
    f = routing.assert_routed(r, typed="close", source="writer", check="close QA round", names=r"\bAC-\d+ fails: \S")
    path = f["injection"][0]["path"]
    first = f["rounds"][0]
    assert first["verdict"].startswith("CLOSE_FINDINGS") and [x for x in first["findings"] if x["path"] == path], first
    assert f["dispatches"][f["routed"][0]["tool_use_id"]]["subagent_type"] == "dev", f["routed"]
    assert len(f["rounds"]) == 2 and not f["rounds"][1]["findings"], f["rounds"]
    routing.assert_close_form(r)


@pytest.mark.parametrize("key", _route_cases(F8C))
def test_f8c_lane_dev_report_removed_then_commit(replays, key):
    r = replays.get(key)
    f = routing.assert_routed(r, typed="commit", source="dispatch", check=CHAIN_CALL)
    assert r.fact("commit")["commit_status"] == "committed", r.fact("commit")


F8R = suite.Scenario("F8r", "commit", (("variant", "late-repair-qa"),), ("dev", "close", "commit"), 200)


@pytest.mark.parametrize("key", _route_cases(F8R))
def test_f8r_late_repair_qa_report_removed_then_commit(replays, key):
    """Acceptance 7's late-repair-qa case: `/close --late-repair` lands CLOSE: YES, the task's QA report is removed
    and /commit typed in a later session. Step 3's disposition call names the removed report, the QA dispatch
    that declared it runs again and writes it, the call run again passes, and Step 5's late-repair state, which
    compares no stage report (P1b row 6), lets the commit land."""
    r = replays.get(key)
    tid = r.terminal("commit")["task"]
    f = routing.assert_routed(r, typed="commit", source="dispatch", check=CHAIN_CALL,
                              path=f"docs/dev/qa-report-{tid}.json")
    assert f["chain"][-1]["disposition"] == "chain_pass", f["chain"]
    plans = [p["value"] for p in r.facts if p["key"] == "commit Step 5"]
    assert plans and plans[-1]["ok"] and plans[-1]["late_repair_state"] != "invalid", plans
    assert plans[-1]["late_repair_state"] == "none", plans
    assert r.fact("commit")["commit_status"] == "committed", r.fact("commit")


# ---------------------------------------------------------------- F6o: a usage limit inside /dev-overnight (X8)

OVERNIGHT = next(s for s in suite.COMPLIANT if s.name == "/dev-overnight")
F6O_BEFORE = "limit@agent:dev Edit toy/*"  # Step 12's dev, inside the window
F6O_AFTER = "limit@agent:pm Glob retro-report-cycle*"  # Step 20's PM RETRO: after end_time, before the summary
STOP_WAKE = suite.Scenario("/dev-overnight /stop, wake refusals", "overnight", (("variant", "stop"), ("then", "idle")),
                           ("dev-overnight",), 120)
REFUSALS = {"bad-message": (("stop_at", "3"), ("fault", "limit@agent:pm Read README.md"), ("wake", "bad-message")),
            "bad-id": (("stop_at", "3"), ("fault", "limit@agent:pm Read README.md"), ("wake", "bad-id")),
            "after-stop": (("wake", "after-stop"),)}


def _cases(scn, extra: tuple, name: str = "") -> list:
    keys = [suite.replay_key(scn, s, extra) for s in suite.SETTINGS]
    return [pytest.param(k, id=name + s, marks=pytest.mark.replay(k, scn.cost)) for k, s in zip(keys, suite.SETTINGS)]


def _non_human(r, prompts: list) -> list:
    """Of `prompts` (recovery.facts' prompts and AskUserQuestion calls after the cut), the human events:
    an AskUserQuestion, or a prompt with a main-transcript record stop_contract.is_human_prompt accepts."""
    import sys
    sys.path.insert(0, os.path.join(suite.REPO, "hooks", "lib"))
    import stop_contract
    recs = [x for dp, _, fs in os.walk(os.path.join(r.run_dir, "transcripts")) if "subagents" not in dp
            for f in fs if f.endswith(".jsonl") for x in suite._jsonl(os.path.join(dp, f))]
    typed = {stop_contract.prompt_text(x) for x in recs} - {None}
    return [p for p in prompts if p == "AskUserQuestion" or p in typed]


def _assert_woken_to_terminal(r) -> dict:
    """F6o: the cut agent resumed by the wake's recovery, with no human event; the terminal reached."""
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    assert not r.blocks, "the wake's recovery met a block:\n" + r.explain()
    assert not r.hook_errors, "the wake's recovery met a hook error:\n" + r.explain()
    f = recovery.facts(r)
    assert f["cuts"] == 1, f
    for aid, a in f["agents"].items():  # the same agent id, resumed by the SendMessage, wrote its artifacts
        assert a["resumed"] and a["written_after_resume"] == a["declared"], (aid, a)
    cut = next(c for c in fault_records(r) if c.get("kind") == "limit")
    at = first_index(r, cut["label"])
    role = cut["role"].split(":", 1)[-1]
    again = [ev["label"] for ev in invocations(r)[at:] if ev["event"] == "PreToolUse"
             and ev["payload"].get("tool_name") == "Agent" and not ev["payload"].get("agent_id")
             and (ev["payload"].get("tool_input") or {}).get("subagent_type") == role]
    assert not again, f"a replacement Agent call for the cut {role}: {again}"
    assert not _non_human(r, f["human_after_cut"]), f"human events after the cut: {f['human_after_cut']}"
    woke = [ev for ev in r.hook_events() if ev["event"] == "UserPromptSubmit" and ev["label"].startswith("wake after")]
    assert len(woke) == 1 and any("capability issued" in h["stdout"] for h in woke[0]["hooks"]), woke
    term = r.terminal("dev-overnight") or {}
    assert term.get("wake_live_at_stop") == [] and term.get("wakes_fired_after") == 0, term
    assert r.reached(), "/dev-overnight did not reach its terminal:\n" + r.explain()
    return {"cut": cut, "terminal": term}


@pytest.mark.parametrize("key", _cases(OVERNIGHT, (("fault", F6O_BEFORE),)))
def test_f6o_usage_limit_before_end_time_resumed_by_the_wake(replays, key):
    got = _assert_woken_to_terminal(replays.get(key))
    assert got["cut"]["at"] < got["terminal"]["end_time"], got


@pytest.mark.parametrize("key", _cases(OVERNIGHT, (("fault", F6O_AFTER),)))
def test_f6o_usage_limit_after_end_time_before_the_summary_resumed_by_the_wake(replays, key):
    got = _assert_woken_to_terminal(replays.get(key))
    assert got["terminal"]["end_time"] < got["cut"]["at"] <= got["terminal"]["stopped_at"], got


# ---------------------------------------------------------------- X8's refusals of the widened exception

@pytest.mark.parametrize("key", _cases(STOP_WAKE, REFUSALS["bad-message"], "bad-message-")
                         + _cases(STOP_WAKE, REFUSALS["bad-id"], "bad-id-"))
def test_the_wakes_capability_refuses_any_other_message_or_id(replays, key):
    r = replays.get(key)
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    assert not r.hook_errors, r.explain()
    refusal = r.fact("wake refusal")
    assert refusal and refusal["refused"], refusal
    want = {"bad-message": "does not begin with the exact restart-v1 recovery message",
            "bad-id": "not a recoverable interrupted subagent"}[refusal["case"]]
    bl = blocks(r)
    assert bl and all(b["step"] == f"/restart SendMessage ({refusal['case']})" for b in bl), r.explain()
    assert any(want in b["text"] for b in bl), r.explain()
    f = recovery.facts(r)  # the compliant SendMessage after it resumed the cut agent
    assert all(a["resumed"] and a["written_after_resume"] == a["declared"] for a in f["agents"].values()), f


@pytest.mark.parametrize("key", _cases(STOP_WAKE, REFUSALS["after-stop"]))
def test_a_wake_after_the_owners_stop_gets_no_capability(replays, key):
    r = replays.get(key)
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    assert not r.blocks and not r.hook_errors, r.explain()
    late = r.fact("wake after /stop")
    assert late == {"fired": 1, "issued": False, "recovery": False}, late
    wake = r.fact("wake")
    assert wake["deleted"] == wake["created"] and len(wake["created"]) == 1 and len(wake["fired"]) == 1, wake


# ---------------------------------------------------------------- F8n, F8a: a gap no agent can produce (P4 review 1, 2)
F8N = suite.Scenario("F8n", "close", (("variant", "noba"),), ("dev", "close"), 190)
F8A = suite.Scenario("F8a", "close", (("variant", "auto-skip"),), ("dev", "close"), 170)


@pytest.mark.parametrize("key", _route_cases(F8N))
def test_f8n_a_ticket_nobody_owes_goes_to_the_owner_never_to_the_rating_step(replays, key):
    r = replays.get(key)
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    assert not r.blocks and not r.hook_errors, r.explain()
    tid = r.terminal("close")["task"]
    ticket = f"docs/dev/ticket-{tid}.md"
    gaps = [g for f in r.facts if f["key"] == "close Step 0" for g in f["value"].get("gaps") or []]
    assert [ticket, "MISSING_ARTIFACT"] in gaps, gaps
    owing = [f["value"] for f in r.facts if f["key"] == "owing dispatch" and f["value"]["path"] == ticket]
    assert owing and all(o["answer"] is None for o in owing), owing
    asked = [f["value"] for f in r.facts if f["key"] == "close Request question"]
    assert asked == [{"artifact": "docs/dev/ticket-<task>.md", "header": "Request", "ok": True, "blocked": False}], asked
    assert not [p for _sid, p in routing.main_writes(r.run_dir) if p.endswith("/" + ticket)], \
        "the /close orchestrator wrote BA's ticket"


@pytest.mark.parametrize("key", _route_cases(F8A))
def test_f8a_auto_passes_over_a_task_nobody_can_complete_and_lands_the_rest(replays, key):
    r = replays.get(key)
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    assert not r.blocks and not r.hook_errors, r.explain()
    skipped = r.fact("close --auto skipped")
    assert len(skipped) == 1 and re.fullmatch(
        r"20250101-000001: skipped: no dispatch record or todo step owes docs/dev/\S+", skipped[0]), skipped
    assert r.fact("close --auto parents") == 1
    assert r.reached(), "the cycle /close --auto walked did not land:\n" + r.explain()
