"""D25 (2) F8, F8q, F8p, F8c, F8r: an unfinished cycle the owner's /close or /commit meets (CC4/D7).

No hook blocks here: the gap is what /close's disposition call (Step 0) or /commit's (Step 3) prints
as a GAP line (the artifact and the failing check, no role: D21), or what a close-QA round finds, and
Routes dispatches again what P1b's E3 reader (hooks/lib/obligation.py declaring_dispatch) returns for
that path. Everything is read from the run's own files: faults.json (the injection), facts.json (the
driver's record of each disposition call's gaps, the reader's answer, the dispatch made, each close-QA
round), invocations.jsonl (every Agent tool_use with its obligation, every typed prompt), the agent
transcripts and their `.meta.json` (who wrote what), terminals.json.
"""
from __future__ import annotations

import json
import os
import re

from .suite import _json, _jsonl

PROBLEM = r"[A-Za-z_][\w:.-]*"   # a GAP line's problem: the failing check's code


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


def facts(r, path: str | None = None) -> dict:
    """What an F8 replay shows (suite.Result `r`); its human events are those after the injection of `path`
    (where one removed or broke it), else after the first injection."""
    rd = r.run_dir
    inj = [f for f in _json(os.path.join(rd, "faults.json"), []) if f.get("kind") in ("remove", "break", "cut")]
    at = next((i.get("events_before", 0) for i in inj if i.get("path") == path),
              inj[0].get("events_before", 0) if inj else 0)
    human = []
    for e in _jsonl(os.path.join(rd, "invocations.jsonl")):
        p = e["payload"]
        if e["seq"] <= at:
            continue
        if e["event"] == "UserPromptSubmit":
            human.append(p.get("prompt"))
        elif e["event"] == "PreToolUse" and p.get("tool_name") == "AskUserQuestion":
            source = ((p.get("tool_input") or {}).get("metadata") or {}).get("source") or ""
            if not source.startswith("close-rating:"):  # the landed /close's own rating question (D9)
                human.append("AskUserQuestion")
    return {"injection": inj, "human": human,
            "gaps": [(c["label"] if "label" in c else f"Step 3 round {c.get('round')}", g)
                     for c in (f["value"] for f in r.facts if f["key"] in ("close Step 0", "commit Step 3"))
                     for g in c.get("gaps") or []],
            "owing": [f["value"] for f in r.facts if f["key"] == "owing dispatch"],
            "routed": [f["value"] for f in r.facts if f["key"] == "routed dispatch"],
            "rounds": [f["value"] for f in r.facts if f["key"] == "close QA round"],
            "chain": [f["value"] for f in r.facts if f["key"] in ("close Step 0", "commit Step 3")],
            "dispatches": dispatches(rd), "writes": agent_writes(rd), "main_writes": main_writes(rd),
            "own": [f["value"] for f in r.facts if f["key"] == "own step"]}


def _same_template(a: dict, b: dict) -> bool:
    strip = (lambda ob: {k: v for k, v in ob.items() if k != "dispatched_at"})
    return strip(a) == strip(b)


CODE_AND_MESSAGE = r"\b[A-Z][A-Z0-9_]+[A-Z0-9]: \S"   # a chain check's error: its code, then its message


def assert_routed(r, *, typed: str, source: str, check: str, path: str | None = None,
                  names: str = CODE_AND_MESSAGE) -> dict:
    """The F8 assertions on suite.Result `r`: `typed` the owner's command after the injection (HX), `source` the
    E3 reader's answer kind for the gap's path (`path`, default the injected one), `check` what found it (the
    disposition call, or `close QA round`), `names` what a close-QA finding says of the failing check. Returns
    the facts."""
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    assert not r.blocks, "an F8 fault met a gate block (it has none to meet):\n" + r.explain()
    assert not r.hook_errors, "an F8 fault met a hook error:\n" + r.explain()
    f = facts(r, path)
    assert f["injection"], f"no injection recorded: {f['injection']}"
    path = path or f["injection"][0]["path"]

    def named(p) -> bool:  # the path, or the project path a check printed for it
        return isinstance(p, str) and (p == path or p.endswith("/" + path))
    if check == "close QA round":
        # The gap: a close-QA round's finding on the path, naming the failing check.
        found = [x for rd in f["rounds"] for x in rd.get("findings") or [] if named(x.get("path"))]
        assert found, f"no close-QA round names {path}: {f['rounds']}"
        assert re.search(names, found[0]["detail"]), f"the finding does not name the failing check ({names}): {found}"
    else:
        # The gap: a GAP line of the disposition call naming the path and its failing check, nothing else (D21).
        gaps = [g for _label, g in f["gaps"] if named(g[0])]
        assert gaps, f"no GAP line names {path}: {f['gaps']}"
        assert len(gaps[0]) == 2 and re.fullmatch(PROBLEM, gaps[0][1]), f"the gap is not (artifact, problem): {gaps}"
    # The loop dispatched again what the reader returned for that path.
    owing = [o for o in f["owing"] if named(o["path"])]
    assert owing and isinstance(owing[0].get("answer"), dict), f"no reader answer for {path}: {f['owing']}"
    ans = owing[0]["answer"]
    assert ans.get("source") == source, f"the reader answered {ans} for {path}, not a {source!r} answer"
    routed = [d for d in f["routed"] if named(d["path"])]
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
        if source == "writer":  # E6: the dispatch whose own agent wrote the product file
            assert any(w.endswith("/" + path) for w in f["writes"].get(ans["tool_use_id"], ())), (ans, path)
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
