"""D25 (2) F8, F8q, F8p, F8c: an unfinished cycle the owner's /close or /commit meets (CC4/D7).

No hook blocks here: the gap is what /close's chain call (Step 0), its close-QA round, or /commit's
chain call (Step 5) finds, recorded as the routing loop's entry, and the loop dispatches again what
P1b's E3 reader (hooks/lib/obligation.py declaring_dispatch) returns for the entry's path. Everything
is read from the run's own files: faults.json (the injection), facts.json (the driver's record of
each routing entry as the text's own call recorded it, the reader's answer, the dispatch made, each
close-QA round), invocations.jsonl (every Agent tool_use with its obligation, every typed prompt),
the agent transcripts and their `.meta.json` (who wrote what), terminals.json.
"""
from __future__ import annotations

import json
import os
import re

from .suite import _json, _jsonl

ENTRY_KEYS = {"path", "detail", "source_check"}


def obligation(prompt: str) -> dict:
    m = re.search(r'<obligation v="1">\s*(\{.*?\})\s*</obligation>', prompt or "", re.S)
    return json.loads(m.group(1)) if m else {}


def dispatches(rd: str) -> dict:
    """Every Agent tool_use of a main agent, by tool_use id: seq, session, label, subagent_type, obligation."""
    out = {}
    for e in _jsonl(os.path.join(rd, "invocations.jsonl")):
        p = e["payload"]
        if e["event"] == "PreToolUse" and p.get("tool_name") == "Agent" and not p.get("agent_id"):
            ti = p.get("tool_input") or {}
            out[p["tool_use_id"]] = {"seq": e["seq"], "session": p.get("session_id"), "label": e["label"],
                                     "subagent_type": ti.get("subagent_type"),
                                     "obligation": obligation(ti.get("prompt", ""))}
    return out


def main_writes(rd: str) -> list:
    """(session, path) of every Write and Edit call of a main agent."""
    return [(e["payload"].get("session_id"), (e["payload"].get("tool_input") or {}).get("file_path", ""))
            for e in _jsonl(os.path.join(rd, "invocations.jsonl"))
            if e["event"] == "PreToolUse" and e["payload"].get("tool_name") in ("Write", "Edit")
            and not e["payload"].get("agent_id")]


def agent_writes(rd: str) -> dict:
    """tool_use id of each dispatch -> the paths its agent's own Write and Edit calls name."""
    tdir = os.path.join(rd, "transcripts")
    out = {}
    for dp, _, fs in os.walk(tdir):
        for f in fs:
            if not f.endswith(".meta.json"):
                continue
            meta = _json(os.path.join(dp, f), {})
            paths = set()
            for rec in _jsonl(os.path.join(dp, f[:-len(".meta.json")] + ".jsonl")):
                if rec.get("type") != "assistant":
                    continue
                for b in rec["message"].get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in ("Write", "Edit"):
                        paths.add(b["input"].get("file_path", ""))
            out[meta.get("toolUseId")] = paths
    return out


def facts(r) -> dict:
    """What an F8 replay shows (suite.Result `r`)."""
    rd = r.run_dir
    inj = [f for f in _json(os.path.join(rd, "faults.json"), []) if f.get("kind") in ("remove", "break", "cut")]
    at = inj[0].get("events_before", 0) if inj else 0
    human = []
    for e in _jsonl(os.path.join(rd, "invocations.jsonl")):
        p = e["payload"]
        if e["seq"] <= at:
            continue
        if e["event"] == "UserPromptSubmit":
            human.append(p.get("prompt"))
        elif e["event"] == "PreToolUse" and p.get("tool_name") == "AskUserQuestion":
            human.append("AskUserQuestion")
    return {"injection": inj, "human": human,
            "entries": [f["value"] for f in r.facts if f["key"] == "routing entry"],
            "owing": [f["value"] for f in r.facts if f["key"] == "owing dispatch"],
            "routed": [f["value"] for f in r.facts if f["key"] == "routed dispatch"],
            "rounds": [f["value"] for f in r.facts if f["key"] == "close QA round"],
            "chain": [f["value"] for f in r.facts if f["key"] == "close Step 0"],
            "dispatches": dispatches(rd), "writes": agent_writes(rd), "main_writes": main_writes(rd),
            "own": [f["value"] for f in r.facts if f["key"] == "own step"]}


def _same_template(a: dict, b: dict) -> bool:
    strip = (lambda ob: {k: v for k, v in ob.items() if k != "dispatched_at"})
    return strip(a) == strip(b)


CODE_AND_MESSAGE = r"\b[A-Z][A-Z0-9_]+[A-Z0-9]: \S"   # a chain check's error: its code, then its message


def assert_routed(r, *, typed: str, source: str, check: str, path: str | None = None,
                  names: str = CODE_AND_MESSAGE) -> dict:
    """The F8 assertions on suite.Result `r`: `typed` the owner's command after the injection (HX), `source` the
    E3 reader's answer kind for the gap's path (`path`, default the injected one), `check` the source_check
    that found it, `names` what the gap's detail says of the failing check. Returns the facts."""
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    assert not r.blocks, "an F8 fault met a gate block (it has none to meet):\n" + r.explain()
    assert not r.hook_errors, "an F8 fault met a hook error:\n" + r.explain()
    f = facts(r)
    assert f["injection"], f"no injection recorded: {f['injection']}"
    path = path or f["injection"][0]["path"]
    # The gap: the routing loop's entry for the injected path, as the text's own call recorded it.
    gaps = [e for e in f["entries"] if e["entry"].get("path") == path]
    assert gaps, f"no routing entry names {path}: {f['entries']}"
    gap = gaps[0]["entry"]
    assert set(gap) == ENTRY_KEYS, f"the gap carries more than path, detail and check (D21): {gap}"
    assert gap["source_check"].startswith(check), f"the gap's check is not {check}: {gap}"
    assert re.search(names, gap["detail"]), f"the gap does not name the failing check ({names}): {gap}"
    assert not re.search(r"\b(producer|owner|role|fix)\b", gap["detail"], re.I), f"the gap names a role: {gap}"
    # The loop dispatched again what the reader returned for that path.
    owing = [o for o in f["owing"] if o["path"] == path]
    assert owing and isinstance(owing[0].get("answer"), dict), f"no reader answer for {path}: {f['owing']}"
    ans = owing[0]["answer"]
    assert ans.get("source") == source, f"the reader answered {ans} for {path}, not a {source!r} answer"
    routed = [d for d in f["routed"] if d["path"] == path]
    assert len(routed) == 1, f"not exactly one dispatch for {path}: {f['routed']}"
    new = f["dispatches"][routed[0]["tool_use_id"]]
    if source == "todo_step":
        # No dispatch declared the path: a fresh dispatch of the canonical step's role from the template the
        # reader returns, under the task id that template's artifacts carry.
        tpl, ob = ans.get("template") or {}, new["obligation"]
        assert new["subagent_type"] == (ans.get("subagent_call") or {}).get("subagent_type"), (ans, new)
        assert {k: ob.get(k) for k in ("role", "pipeline")} == {k: tpl.get(k) for k in ("role", "pipeline")}, (tpl, ob)
        tids = {a.get("identity", {}).get("task_id") for a in tpl.get("artifacts") or []}
        assert ob.get("task_id") in tids and path in [a.get("path") for a in ob.get("artifacts") or []], (tpl, ob)
    else:
        old = f["dispatches"].get(ans.get("tool_use_id"))
        assert old is not None, f"the reader's dispatch {ans.get('tool_use_id')} is no Agent call of the replay"
        assert new["subagent_type"] == old["subagent_type"], (old, new)
        assert _same_template(new["obligation"], old["obligation"]), \
            f"the re-dispatch's obligation differs beyond dispatched_at:\n{old['obligation']}\n{new['obligation']}"
        assert new["obligation"]["dispatched_at"] > old["obligation"]["dispatched_at"], (old, new)
        assert new["session"] != old["session"], "the re-dispatch is not the later session's"
    # The repair was written by that dispatch's own agent.
    wrote = f["writes"].get(routed[0]["tool_use_id"], set())
    assert any(w.endswith("/" + path) for w in wrote), f"the re-dispatch did not write {path}: {sorted(wrote)}"
    # Only the owner's typed command between injection and terminal (HX).
    assert f["human"] == [f"/{typed} {r.terminal(typed)['task']}"], f"human events other than HX: {f['human']}"
    assert r.reached(), "a pipeline did not reach its terminal:\n" + r.explain()
    return f


def assert_close_form(r) -> None:
    """/close's Terminal form after a repair: the report's last line names its `## Disclosures` line count."""
    t = r.terminal("close")
    assert t["repairs"] and t["disclosures"] >= 1, t
    assert t["report_last_line"] == f"CLOSE: YES - with disclosures: {t['disclosures']} items", t
