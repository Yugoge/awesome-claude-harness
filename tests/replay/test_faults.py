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

Interrupted session and resume after a usage limit (F5, F5f, F6; tests/replay/recovery.py): the
session is cut while the dev subagent runs, after its Edit; the owner's /restart (HX) resumes that
same agent through commands/restart.md's recovery and finalizes it; the main agent then completes the
dev step with the resumed call (no replacement Agent call) and /dev reaches its terminal. Each runs
with the tree's settings ("shipped") and armed (G1-G3 block).

The held git index.lock (F4, F4c, F4s; R14, X7): the shared-index sync (scripts/session-index.py
sync-shared, the changelog-analyst's step after each commit) waits while a process holds the lock and
removes, once and saying so, a lock no process holds that is older than the sync.

An unfinished cycle the owner's /close or /commit meets (F8, F8q, F8p, F8c; tests/replay/routing.py):
the gap names the artifact's path and its check and no role (D21); /close's one chain call (Step 0),
its close-QA round (F8p) or /commit's chain call (Step 5, F8c) finds it; the routing loop dispatches
again what P1b's E3 reader returns for that path (the same subagent_type, task id, lane and obligation
template, a fresh dispatched_at), that dispatch's own agent writes the repair, and the typed /close or
/commit (HX) is the only human event; /close ends in its Terminal form and F8c's commit lands.
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
}


# the failing check each fault's block must name, beside the artifact's path
CHECK = {
    "F1": r"absent|no such file", "F1q": r"absent|no such file",
    "F2": r"files_modified|'done'", "F2g": r"files_modified|'done'",
    "F2j": r"JSON|[Pp]ars|[Dd]ecod|Expecting|Unterminated",
    "F7": r"needs_review|required_values", "F7b": r"needs_review|missing_block",
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
    found = [f"{ev['event']} at {ev['label']!r}" for ev in events[first:]
             if ev["event"] == "UserPromptSubmit" or ev.get("tool") == "AskUserQuestion"]
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


# ---------------------------------------------------------------- F8, F8q, F8p, F8c: an unfinished cycle met by /close or /commit
def _route_cases(scn: suite.Scenario, faults: tuple = ()) -> list:
    keys = [suite.replay_key(scn, s, faults) for s in suite.SETTINGS]
    return [pytest.param(k, id=s, marks=pytest.mark.replay(k, scn.cost)) for k, s in zip(keys, suite.SETTINGS)]


F8 = suite.Scenario("F8", "close", (("variant", "route"), ("cycle_variant", "fanout")), ("dev", "close"), 400)
F8P = suite.Scenario("F8p", "close", (("variant", "break"), ("cycle_variant", "fanout")), ("dev", "close"), 420)
F8Q = suite.Scenario("F8q", "close", (("cycle_variant", "fanout"),), ("close",), 420)
F8Q_CUT = (("fault", "cut@Step 13 [[]l2] Agent(qa)"),)
F8C = suite.Scenario("F8c", "commit", (("variant", "commit-route"), ("cycle_variant", "fanout")),
                     ("dev", "close", "commit"), 500)


@pytest.mark.parametrize("key", _route_cases(F8))
def test_f8_lane_qa_report_removed_then_close(replays, key):
    r = replays.get(key)
    f = routing.assert_routed(r, typed="close", source="dispatch", check="close-route-select.py")
    assert f["chain"][0]["route_select_rc"] != 0 and [c for c in f["chain"][0]["errors"]
                                                      if c[1] == f["injection"][0]["path"]], f["chain"]
    assert f["chain"][-1]["route_select_rc"] == 0, f["chain"]
    routing.assert_close_form(r)


@pytest.mark.parametrize("key", _route_cases(F8Q, F8Q_CUT))
def test_f8q_fanout_cut_before_a_lane_qa_then_close(replays, key):
    r = replays.get(key)
    assert r.terminal("dev") is None, "the cut /dev reached its own terminal"
    tid = r.terminal("close")["task"]
    f = routing.assert_routed(r, typed="close", source="todo_step", check="close-route-select.py",
                              path=f"docs/dev/qa-report-{tid}-l2.json")
    # Each step still lacking ran by its expected producer: the completion report, the main agent's own step.
    done = f"docs/dev/completion-{tid}.md"
    owing = [o["answer"] for o in f["owing"] if o["path"] == done]
    assert owing and owing[0]["source"] == "todo_step" and owing[0]["subagent_call"] is None, f["owing"]
    close_session = f["dispatches"][f["routed"][0]["tool_use_id"]]["session"]
    assert any(sid == close_session and p.endswith("/" + done) for sid, p in f["main_writes"]), (f["own"], f["main_writes"])
    assert f["chain"][-1]["route_select_rc"] == 0, f["chain"]
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
    f = routing.assert_routed(r, typed="commit", source="dispatch", check="resolve-dev-artifact-chain.py")
    assert r.fact("commit")["commit_status"] == "committed", r.fact("commit")
