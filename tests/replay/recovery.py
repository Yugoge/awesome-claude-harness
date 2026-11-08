"""D25 (2) F5, F5f, F6: a session cut while subagents run, and the owner's /restart (HX).

    --arg fault=cut@<label glob>     F5, F5f: after the first step of a subagent whose label matches
                                     (`agent:dev Edit toy/*`), the session is cut: the CLI process ends
                                     there, so the subagent's call never comes back (no SubagentStop, no
                                     Agent tool_result); every other matching subagent dispatched before
                                     the main agent's next step is cut the same way (both lanes of a
                                     fan-out batch). The owner reopens the session (`claude --resume`,
                                     SessionStart source "resume") and types /restart.
                                     A glob matching a step of the main agent instead (a dispatch,
                                     `Step 13 [[]l2] Agent(qa)`) cuts the session before that step,
                                     with no subagent running (F8q: SessionCut ends the command there;
                                     the owner types /close instead of /restart).
    --arg fault=limit@<label glob>   F6: at that step the subagent's next request meets a usage limit:
                                     its transcript gets the CLI's API-error record, its Agent call ends in
                                     the CLI's error result, the main agent's own request meets the same
                                     limit (its API-error record, StopFailure instead of Stop). The owner
                                     types /restart in the same session after the reset.

Record shapes: the API-error record and the Agent error result are the ones hooks/lib/
interruption_signals.py documents as measured (`isApiErrorMessage`, `error`, `apiErrorStatus`,
`stop_reason: "stop_sequence"`; "Agent terminated early due to an API error: <banner> (error type
rate_limit, HTTP 429)"), and P1's capture (S9). The resumed agent's end reaches the parent as the
CLI's task-notification, queued (the shape tests/test_restart_command.py reads). Nothing here
reads such a record: the harness's own /restart helper does (D4c).

F6o (P1c X8): the same `limit` fault inside /dev-overnight, whose driver models the CLI's scheduler
(tests/replay/wake.py, rp.cron): no human types /restart (D20). The session idles until its wake fires
(the scheduled prompt record, no human event); the wake's hooks must issue the capability and hand over
commands/restart.md's recovery, which the main agent then runs as below. With no wake scheduled (a
text without dev-overnight.md's Step 0), or no hand-over, the cut waits for the owner's /restart: the
replay records it Stuck, never typing /restart for him. The hand-over names restart.md's path: the main
agent Reads it and runs its procedure.
    --arg wake=bad-message | bad-id   the three refusals' first two: in the wake's recovery, one
                                     SendMessage with another message (the resume message behind a
                                     prefix) or to an id no candidate has, before the compliant ones;
                                     its refusal is kept in facts.json ("wake refusal").

The owner's /restart turn follows commands/restart.md of the tree under test as written: its
fenced blocks run as Bash calls (prepare, status, finalize), one SendMessage per pending candidate
with its agent id and its exact resume message, the resumed agent goes on from where it was cut
(first re-reading what its last call wrote, as the message tells it) and ends with the line the
message names; the main agent then goes on with the interrupted command where it stopped. No
replacement Agent call is made. A refused or failed recovery step leaves the replay with no way on
(Stuck, the driver error); so does a refused completion of the interrupted step afterwards.
"""
from __future__ import annotations

import json
import os
import re
import threading

from . import cmdtext
from .faults import _record
from .pipeline import utc_now

BANNER = "You've hit your session limit · resets 5pm (UTC)"
TERMINATED = f"Agent terminated early due to an API error: {BANNER} (error type rate_limit, HTTP 429)"


class Stuck(RuntimeError):
    """The recovery met a refusal or failure the text gives no way past."""


class SessionCut(RuntimeError):
    """A cut between the main agent's own steps (F8q): the CLI process ended before the step it names, with
    no subagent running; the command the driver was playing ends there, and the owner's next command
    (their /close, D7) meets the cycle unfinished."""


class _Abandoned(BaseException):
    """Ends a cut subagent no recovery resumed (its thread unwinds)."""


def api_error(text: str) -> dict:
    return {"type": "assistant", "isApiErrorMessage": True, "error": "rate_limit", "apiErrorStatus": 429,
            "message": {"role": "assistant", "model": "<synthetic>", "stop_reason": "stop_sequence",
                        "content": [{"type": "text", "text": text}]}}


class _Run:
    """One dispatch's subagent, run on its own thread so a cut can leave it mid-run; the threads hand
    control back and forth, never running together."""

    def __init__(self, d, sub, rest, agent_in):
        self.d, self.sub, self.rest, self.agent_in = d, sub, rest, agent_in
        self.go, self.back = threading.Event(), threading.Event()
        self.parked = self.done = self.abandoned = False
        self.error = None
        self.cut_step = None

    def main(self):
        try:
            self.rest()
        except _Abandoned:
            pass
        except BaseException as e:  # noqa: BLE001 - raised again in the dispatching thread
            self.error = e
        finally:
            self.done = True
            self.back.set()

    def wait(self):
        self.back.wait()
        self.back.clear()
        if self.error is not None:
            raise self.error

    def park(self):
        self.parked = True
        self.back.set()
        self.go.wait()
        self.go.clear()
        if self.abandoned:
            raise _Abandoned()

    def resume(self, abandon: bool = False):
        self.abandoned = abandon
        self.go.set()
        self.wait()


class Cuts:
    """The cut (rp.cuts, read by Actor.dispatch) and the owner's /restart after it."""

    def __init__(self, rp, kind: str, glob: str):
        self.rp, self.kind, self.glob = rp, kind, glob
        self.runs: dict = {}
        self.parked: list = []
        self.recovered = False

    # ------------------------------------------------------------ the cut
    def run(self, d, sub, rest, agent_in) -> None:
        r = self.runs[sub.aid] = _Run(d, sub, rest, agent_in)
        threading.Thread(target=r.main, daemon=True).start()
        r.wait()
        if not r.parked:
            return
        d.cut = True
        self.parked.append(r)
        if self.kind == "limit":
            # The CLI ends the call with its error result, then the main agent's own request meets
            # the limit: its API-error record, and StopFailure in place of Stop (D4c).
            s = sub.s
            s.main._result(d.tool_use_id, TERMINATED, error=True)
            s.fire("PostToolUseFailure", d.label, {"tool_name": "Agent", "tool_input": agent_in,
                                                   "tool_use_id": d.tool_use_id, "error": TERMINATED,
                                                   "is_interrupt": False})
            s.append(api_error(BANNER))
            s.fire("StopFailure", "StopFailure rate_limit", {"error": "rate_limit"})

    def at_step(self, rp, phase, step) -> None:
        """The cut point: after the first matching step of a subagent (on its own thread); before a matching
        step of the main agent (a dispatch, or a tool call of its own) when no subagent runs (SessionCut)."""
        r = self.runs.get(getattr(step.get("actor"), "aid", None))
        main = step.get("kind") == "dispatch" or (step.get("kind") == "tool"
                                                  and getattr(step.get("actor"), "agent", 1) is None)
        if phase == "before" and r is None and main and self.kind == "cut" and not self.recovered:
            self.recovered = True  # nothing is parked: no /restart follows
            _record(rp, {"kind": "cut", "label": step["label"], "agent": None, "role": "main", "repaired": False,
                         "rounds": 0, "events_before": rp.n_events})
            raise SessionCut(step["label"])
        if phase != "after" or r is None or r.cut_step is not None or self.recovered:
            return
        r.cut_step = step
        _record(rp, {"kind": self.kind, "label": step["label"], "agent": r.sub.aid, "role": r.sub.role,
                     "repaired": False, "rounds": 0, "at": utc_now()})
        if self.kind == "limit":  # the subagent's next request meets the limit
            r.sub.s.append(api_error(BANNER), r.sub.aid)
        r.park()

    def at_next(self, rp, phase, step) -> None:
        """The main agent's next step after the cut: the owner's /restart runs first. Its completion
        of the interrupted step (that step's own call) must then pass."""
        main = step.get("kind") in ("stop", "prompt", "slash") or (
            step.get("kind") == "tool" and getattr(step.get("actor"), "agent", 1) is None)
        if not main or not self.parked or threading.current_thread() is not threading.main_thread():
            return
        if phase == "after" and step["label"] == self._next:
            self._next = None
            call = step.get("result")
            if getattr(call, "blocked", False):
                raise Stuck(f"{step['label']} was refused after the recovery: "
                            + rp.blocks[-1]["text"][:600])
            return
        if phase != "before" or self.recovered:
            return
        self.recovered = True
        self._next = step["label"]
        try:
            restart_turn(rp, self.parked[0].sub.s, self)
        except Stuck:
            for r in self.parked:
                if not r.done:
                    r.resume(abandon=True)
            raise

    _next = None

    # ------------------------------------------------------------ the owner's /restart
    def resume(self, aid: str, message: str) -> None:
        """The SendMessage-resumed agent: the CLI hands it the message, it re-reads what its last call
        wrote, goes on from there to its stop, and the CLI queues its task-notification."""
        r = next(x for x in self.parked if x.sub.aid == aid)
        sub, s = r.sub, r.sub.s
        s.append({"type": "user", "message": {"role": "user", "content": message}}, aid)
        path = (r.cut_step.get("input") or {}).get("file_path")
        if path:
            sub.read(path, label=f"{sub.role} Read {os.path.relpath(path, self.rp.layout.project)} (resumed)")
        line = re.search(r"otherwise end with `([^`]+)`", message)
        r.d.final_line = line.group(1) if line else ""
        r.resume()
        s._write(s.tpath, {"type": "queue-operation", "operation": "enqueue", "sessionId": s.sid,
                           "content": f"<task-notification><task-id>{aid}</task-id>"
                                      f"<tool-use-id>{r.d.tool_use_id}</tool-use-id><status>completed</status>"
                                      f"<summary>Agent \"{r.agent_in.get('description', '')}\" completed</summary>"
                                      f"<result>{getattr(sub, 'last_final', '')}</result></task-notification>"})
        next(f for f in self.rp.fault_records if f.get("agent") == aid).update(repaired=True, rounds=1)
        _record(self.rp)


def restart_turn(rp, s, cuts: Cuts) -> None:
    """The owner reopens the session (F5, F5f) and types /restart; the main agent runs
    commands/restart.md's procedure, then goes on with the command its subagents were cut in."""
    from .pipeline import Orchestrator
    if cuts.kind == "cut":
        s.end("other")
        s.start("resume")
    o = Orchestrator(rp, "restart", session=s)
    cron = getattr(rp, "cron", None)
    if cron is None:
        o.slash("")
    else:  # inside /dev-overnight nobody types /restart (D20): the session's wake resumes it (X8)
        if not cron.jobs:
            raise Stuck("a usage limit cut the /dev-overnight session and no wake is scheduled: "
                        "it waits for the owner's /restart")
        evs = cron.idle(s, 1, label="wake after the usage limit's reset")
        out = "\n".join(h["stdout"] for ev in evs for h in ev.hooks if h["verdict"] == "ok")
        m = re.search(r"OVERNIGHT WAKE:.*?Read (\S+) now and run its Mandatory procedure", out, re.S)
        if not m:
            raise Stuck("the wake fired but no hook handed over commands/restart.md's recovery: "
                        "the cut waits for the owner's /restart:\n" + out[-600:])
        s.read(m.group(1), label="wake Read restart.md")  # the procedure below is that file's text
    cmds = {}
    for b in cmdtext.blocks(o.text, "Mandatory procedure", "text"):
        m = re.search(r"restart-subagents\.py\"?\s+(\w+)", b.text)  # P2 quotes the channel-spelled path
        if m:
            cmds[m.group(1)] = b.text.strip()

    def run(name: str, description: str, timeout=None) -> dict:
        call = o.run(cmds[name], description, f"/restart Bash {name}", timeout=timeout)
        if not call.ok:
            raise Stuck(f"/restart's {name} command did not run: "
                        + (rp.blocks[-1]["text"] if call.blocked else call.error)[:600])
        return json.loads(call.response.get("stdout") or "{}")

    view = run("prepare", "Prepare the recovery set")
    pending = [c for c in view.get("candidates") or [] if c.get("status") == "pending"]
    if not pending:
        raise Stuck(f"prepare found no pending candidate: {json.dumps(view)[:600]}")
    bad = rp.args.get("wake")
    if cron is not None and bad in ("bad-message", "bad-id"):  # X8's refusals: another message, another id
        c = pending[0]
        to, msg = ((c["agent_id"], "Please resume.\n" + c["resume_message"]) if bad == "bad-message"
                   else ("a" + "0" * 16, c["resume_message"]))
        call = s.tool("SendMessage", {"to": to, "message": msg},
                      perform=lambda: {"success": True, "message": f"Message sent to {to}"},
                      label=f"/restart SendMessage ({bad})")
        from .drivers.close import fact
        fact(rp, "wake refusal", {"case": bad, "refused": call.blocked,
                                  "text": rp.blocks[-1]["text"][:600] if call.blocked else ""})
    sent = []
    for c in pending:  # one batch: a SendMessage per pending candidate, its exact resume message
        msg = c["resume_message"]
        call = s.tool("SendMessage", {"to": c["agent_id"], "message": msg},
                      perform=lambda aid=c["agent_id"]: {"success": True, "message": f"Message sent to {aid}"},
                      label=f"/restart SendMessage {c.get('description') or c.get('agent_type')}")
        if not call.ok:
            raise Stuck(f"SendMessage to {c['agent_id']} was refused: " + rp.blocks[-1]["text"][:600])
        sent.append((c["agent_id"], msg))
    for aid, msg in sent:
        cuts.resume(aid, msg)
    status = run("status", "Wait for every resumed agent's response", timeout=600)
    if not status.get("complete"):
        raise Stuck(f"RESTART_INCOMPLETE: {status.get('incomplete_agent_ids')}")
    run("finalize", "Finalize the recovery")
    s.say("Recovered " + ", ".join(f"{c['agent_id']} ({c['agent_transcript_path']})" for c in pending)
          + ". Continuing the interrupted command from its in-progress step.")


def facts(r) -> dict:
    """What a cut-and-restart replay shows, read from its run's own files (suite.Result `r`): per cut
    agent whether the SendMessage resumed that same agent id with the message the CLI handed it and
    whether it then wrote every artifact its own dispatch's obligation declares; the Agent dispatches
    of the cut role (a replacement would be one more); the first TodoWrite completing the step that
    names the role that no hook refused, and whether it came after finalize; the human prompts and
    AskUserQuestion calls after the cut."""
    from .suite import _json, _jsonl
    rd = r.run_dir
    inv = _jsonl(os.path.join(rd, "invocations.jsonl"))
    cuts = [c for c in _json(os.path.join(rd, "faults.json"), []) if c.get("kind") in ("cut", "limit")]
    out = {"cuts": len(cuts), "agents": {}, "dispatches": 0, "human_after_cut": [], "step_done_after": False}
    if not cuts:
        return out
    role = cuts[0]["role"].split(":", 1)[-1]
    first = min(e["seq"] for e in inv for c in cuts if e["label"] == c["label"]
                and e["payload"].get("agent_id") == c["agent"])
    sent = {}
    finalize = step_done = None
    for e in inv:
        p, ti = e["payload"], e["payload"].get("tool_input") or {}
        if e["event"] != "PreToolUse" or p.get("agent_id"):
            if e["event"] == "UserPromptSubmit" and e["seq"] > first:
                out["human_after_cut"].append(p.get("prompt"))
            continue
        if p.get("tool_name") == "Agent" and ti.get("subagent_type") == role:
            out["dispatches"] += 1
        elif p.get("tool_name") == "SendMessage":
            sent[ti.get("to")] = ti.get("message")
        elif p.get("tool_name") == "AskUserQuestion" and e["seq"] > first:
            out["human_after_cut"].append("AskUserQuestion")
        elif e["label"] == "/restart Bash finalize":
            finalize = e["seq"]
        elif p.get("tool_name") == "TodoWrite" and step_done is None and not any(
                h["verdict"] == "block" for h in e["hooks"]) and any(
                t.get("status") == "completed" and (t.get("subagent_call") or {}).get("subagent_type") == role
                for t in ti.get("todos") or []):
            step_done = e["seq"]
    out["step_done_after"] = bool(finalize and step_done and step_done > finalize)
    tdir = os.path.join(rd, "transcripts")
    for c in cuts:
        path = next(os.path.join(dp, f) for dp, _, fs in os.walk(tdir) for f in fs if f == f"agent-{c['agent']}.jsonl")
        recs = _jsonl(path)
        ob = re.search(r'<obligation v="1">\s*(\{.*?\})\s*</obligation>', str(recs[0]["message"]["content"]), re.S)
        declared = [a["path"] for a in json.loads(ob.group(1))["artifacts"] if a.get("kind") in ("json", "markdown")]
        at = next((k for k, x in enumerate(recs) if k and x.get("type") == "user"
                   and x["message"].get("content") == sent.get(c["agent"])), None)
        written = {b["input"].get("file_path", "") for x in recs[at or len(recs):] if x.get("type") == "assistant"
                   for b in x["message"]["content"] if b.get("type") == "tool_use" and b["name"] in ("Write", "Edit")}
        out["agents"][c["agent"]] = {"resumed": at is not None, "declared": declared,
                                     "written_after_resume": [d for d in declared
                                                              if any(w.endswith("/" + d) for w in written)]}
    return out


def assert_resumed_to_terminal(r, lanes: int) -> None:
    """test_faults.py's F5, F5f, F6 assertions on suite.Result `r` with `lanes` cut subagents."""
    assert not r.error and not r.summary.get("driver_error") and r.rc == 0, r.explain()
    # A recovery that follows restart.md meets no block at all (none to name an artifact and check).
    assert not r.blocks, "the recovery met a block:\n" + r.explain()
    assert not r.hook_errors, "the recovery met a hook error:\n" + r.explain()
    f = facts(r)
    assert f["cuts"] == lanes, f
    for aid, a in f["agents"].items():  # the same agent id, resumed by the SendMessage, wrote its artifacts
        assert a["resumed"] and a["written_after_resume"] == a["declared"], (aid, a)
    assert f["step_done_after"], f"the dev step was not completed after the recovery finalized: {f}"
    assert f["dispatches"] == lanes, f"a replacement Agent call for the cut subagent: {f}"
    assert r.reached(), "/dev did not reach its terminal:\n" + r.explain()
    assert f["human_after_cut"] == ["/restart"], f"human events after the cut other than HX: {f}"


def install(rp, kind: str, glob: str) -> None:
    cuts = rp.cuts = Cuts(rp, kind, glob)
    rp.faults.append((glob, cuts.at_step))
    rp.faults.append(("*", cuts.at_next))
