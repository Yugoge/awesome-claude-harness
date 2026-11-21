"""The owner's /restart (CLAUDE.md lesson 16), traced: a usage limit cuts a subagent, then three cases.

One session: a plain prompt, one foreground dispatch of a read-only subagent, which a usage limit cuts
after its first call (recovery.py's `limit`: its API-error record, the CLI's error result for the Agent
call, the main agent's StopFailure). Then, in order:

  no-grant  before any /restart, the main agent runs commands/restart.md's prepare and sends the
            cut agent the exact resume message /restart would hand it: prepare reads the grant as data
            only, so it lists the candidates and says on stderr that every resume send will be refused
            until /restart mints one (exit 0), and the no-background hook refuses the send
            (send_policy.decide: the cut agent resumes only through /restart; no valid /restart
            capability), the one decision on the grant
  restart   the owner types /restart: the authorizer (hooks/userprompt-restart-authorize.py) mints the
            grant and prepares the recovery set, and the main agent runs restart.md's procedure as
            written (recovery.restart_turn): reads that set, one SendMessage per pending candidate
            with its exact resume message, the resumed agent's end, status with response evidence
            for every candidate, finalize
  reuse     the same SendMessage again after finalize consumed the grant: refused

then a Stop. What each case showed is kept in out/facts.json ("restart no-grant", "restart",
"restart reuse"); the terminal ("restart") is reached when the three held and the Stop met no block.
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys

from .. import cmdtext, recovery
from ..pipeline import Orchestrator
from .close import fact

PIPELINE = "restart"
# The artifact check's cost of this driver (tests/artifact_graph/shards.py balances its CI shards by it):
# CPU seconds of the shipped and armed traced replays and their differential runs: smoke's 51 scaled by the
# two drivers' replay and differential sums in `check --only` on one runner (74.7 s against 67.0 s)
COST = 57

TASK = (
    "Problem: a reader needs to know what the add function of the toy package returns.\n"
    "Acceptance criteria: the answer names the value add returns for two numbers.\n"
    "Constraints: look only at the toy package.\n"
    "DO NOT: modify, create or delete any file; DO NOT run tests, builds or version-control commands."
)
# The subagent's first call, after which the usage limit cuts it
CUT = "restart-sub Read *"
# What prepare says without a valid grant (hooks/lib/subagent_restart.py NO_GRANT_NOTICE)
NO_GRANT_NOTICE = "no valid restart grant: every resume send will be refused until /restart mints one"


def _explore(sub):
    project = sub.rp.layout.project
    sub.read(f"{project}/toy/__init__.py", label="restart-sub Read toy/__init__.py")
    sub.tool("Grep", {"pattern": "return", "path": f"{project}/toy", "output_mode": "files_with_matches"},
             label="restart-sub Grep")


def _send(s, rp, to: str, message: str, label: str) -> dict:
    call = s.tool("SendMessage", {"to": to, "message": message},
                  perform=lambda: {"success": True, "message": f"Message sent to {to}"}, label=label)
    return {"refused": bool(call.blocked), "text": rp.blocks[-1]["text"][:600] if call.blocked else ""}


def _resume_message(rp, sid: str, aid: str) -> str:
    """The exact resume message a bare /restart hands `aid`: the tree's own builder
    (hooks/lib/subagent_restart.py build_resume_message), read before any grant exists."""
    lib = os.path.join(rp.layout.harness, "hooks", "lib")
    with rp.acting("driver"):
        spec = importlib.util.spec_from_file_location("replay_tree_subagent_restart",
                                                      os.path.join(lib, "subagent_restart.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.path.insert(0, lib)
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.path.remove(lib)
        return mod.build_resume_message(sid, aid)


def run(rp) -> None:
    cuts = rp.cuts = recovery.Cuts(rp, "limit", CUT)
    rp.faults.append((CUT, cuts.at_step))       # the cut only: this driver plays the recovery itself
    s = rp.session()
    s.prompt("What does the add function in the toy package return? Have a subagent look.", label="prompt")
    d = s.dispatch("Explore", TASK, description="Describe toy.add", body=_explore,
                   result="add(a, b) returns a + b.", label="main Agent(Explore)")
    if not d.cut:
        raise recovery.Stuck("the usage limit did not cut the subagent")

    # no-grant: restart.md's own prepare block, run before any /restart
    o = Orchestrator(rp, "restart", session=s)
    prepare = next(b.text.strip() for b in cmdtext.blocks(o.text, "Mandatory procedure", "text")
                   if re.search(r"restart-subagents\.py\"?\s+prepare", b.text))
    call = o.run(prepare, "Prepare the recovery set", "no grant Bash prepare")
    out = (call.response.get("stdout", "") + call.response.get("stderr", "")) if call.ok else ""
    no_grant = {"prepare_ok": bool(call.ok), "prepare_error": "" if call.ok else (call.error or "")[:600],
                "notice": NO_GRANT_NOTICE in out}
    cut = cuts.parked[0].sub.aid
    message = _resume_message(rp, s.sid, cut)
    no_grant["send"] = _send(s, rp, cut, message, "no grant SendMessage")
    fact(rp, "restart no-grant", no_grant)

    # restart: the owner's /restart, restart.md's procedure as written
    sent: dict = {}
    rp.faults.append(("/restart SendMessage *", lambda _rp, phase, step: phase == "before" and sent.setdefault(
        step["input"]["to"], step["input"]["message"])))
    cuts.recovered = True
    recovery.restart_turn(rp, s, cuts)
    recovered = [{"agent_id": r.sub.aid, "sent": r.sub.aid in sent, "resumed": r.done} for r in cuts.parked]
    fact(rp, "restart", {"recovered": recovered})

    # reuse: the same exact message once more, the grant consumed by finalize
    aid = cuts.parked[0].sub.aid
    reuse = dict(_send(s, rp, aid, sent[aid], "reuse SendMessage"), same_message=sent[aid] == message)
    fact(rp, "restart reuse", reuse)

    stop = s.stop("add(a, b) returns a + b.", label="Stop")
    reached = (no_grant["prepare_ok"] and no_grant["notice"] and no_grant["send"]["refused"]
               and all(r["sent"] and r["resumed"] for r in recovered) and reuse["refused"])
    rp.terminal("restart", reached, stop)

