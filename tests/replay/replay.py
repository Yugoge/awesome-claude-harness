"""Session, transcript and tool-call model of the CLI (P1 "Scenario drivers").

A driver gets a Replay and works through Sessions and Actors (the main agent,
or a subagent inside a dispatch):

* a main transcript starts with two queue-operation records;
* a typed slash command is UserPromptSubmit, then the command-name user record,
  then an isMeta record carrying the command body from the tree under test;
* a tool call is the T1 order: assistant tool_use appended, PreToolUse, the
  call performed only if not blocked, then the tool_result and PostToolUse
  (PostToolUseFailure and an error tool_result when the call fails; a failing
  call never raises);
* a dispatch is the Agent tool_use, PreToolUse, the subagent transcript
  (projects/<slug>/<sid>/subagents/agent-<id>.jsonl, first record the prompt,
  agent-<id>.meta.json beside it), the subagent's own calls through the same
  helpers attributed to it, its final text, SubagentStop, the Agent tool_result
  and PostToolUse.

Every block is recorded (hook, step, normalised refusal text). A block passes
only through a Deviation the driver declares on that step, quoting the hook's
text; the call is then applied as if allowed and the deviation recorded.
Anything else blocked stays blocked and is reported.

Every step goes through Replay.step(), which runs the faults registered for its
label (fnmatch patterns) before and after it, so a later phase can inject a
fault at any step without editing the driver. Writes the driver performs on an
agent's behalf run inside Replay.acting(role), which leaves a marker the trace
uses to attribute them to that role.
"""
from __future__ import annotations

import fnmatch
import glob as _glob
import json
import os
import pwd
import re
import subprocess
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field

from . import cmdtext, hookrun, norm

MODEL = "claude-opus-5-5"
CLI_VERSION = "2.1.295"
BASH_TIMEOUT_S = 120


class ToolError(Exception):
    """A tool call that fails the way the CLI's tool would (recorded as an error tool_result)."""


@dataclass
class Deviation:
    """Pass one block: `hook` is the registered hook file (or its basename), `quote` an excerpt of its text."""
    hook: str
    quote: str
    why: str = ""

    def covers(self, block_hook: str, raw: str, text: str) -> bool:
        same = block_hook == self.hook or block_hook.endswith("/" + self.hook)
        return same and (self.quote in raw or self.quote in text)


class Event:
    def __init__(self, rec: dict):
        self.rec = rec
        self.event = rec["event"]
        self.hooks = rec["hooks"]
        self.blocks = [h for h in self.hooks if h["verdict"] == "block"]
        self.still_blocked = bool(self.blocks)

    @property
    def blocked(self) -> bool:
        return self.still_blocked


@dataclass
class Call:
    label: str
    name: str
    tool_use_id: str = ""
    pre: Event | None = None
    post: Event | None = None
    blocked: bool = False
    ok: bool = False
    error: str = ""
    response: dict = field(default_factory=dict)
    skipped: bool = False


@dataclass
class Dispatch(Call):
    agent_id: str = ""
    agent_type: str = ""
    stop: Event | None = None
    actor: "Actor | None" = None


def now_iso() -> str:
    t = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".%03dZ" % (int(t * 1000) % 1000)


def _as_list(dev):
    return [] if dev is None else list(dev) if isinstance(dev, (list, tuple)) else [dev]


class Replay:
    def __init__(self, layout, settings_path: str, *, pipeline: str, settings_label: str,
                 env_extra: dict | None = None, faults=(), parallel_hooks: bool = False):
        self.layout = layout
        with open(settings_path) as fh:
            self.settings = json.load(fh)
        self.pipeline, self.settings_label = pipeline, settings_label
        self.faults = list(faults)
        self.parallel = parallel_hooks
        self.window = norm.Window(time.time())
        self.ids = norm.Ids()
        self.slug = re.sub(r"[^A-Za-z0-9]", "-", layout.project)
        self.ids.add("slug", self.slug)
        self.roots = norm.Roots([(layout.harness, "<harness>"), (layout.project, "<project>"),
                                 (layout.origin, "<origin>"), (layout.state, "<state>"),
                                 (layout.home, "<home>"), (layout.sb, "<sb>")])
        self.env = self._env(env_extra or {})
        # E5: the CLI exports CLAUDE_PROJECT_DIR to hooks only; its Bash tool leaves it unset.
        self.bash_env = {k: v for k, v in self.env.items() if k != "CLAUDE_PROJECT_DIR"}
        self.args: dict = {}  # the driver's arguments (cli.py --arg K=V)
        self.respellings: list = []  # row 7 respellings a driver applied, one record per call
        # Optional fn(step label) -> deviations, consulted for a tool call or dispatch whose caller passes
        # none (a subagent's own calls, made by agents.Player): a driver sets it to reach those steps.
        self.deviation_at = None
        os.makedirs(layout.out, exist_ok=True)
        os.makedirs(layout.markers, exist_ok=True)
        self._log = open(os.path.join(layout.out, "hooks.jsonl"), "w")
        self._markers = open(os.path.join(layout.out, "markers.jsonl"), "w")
        self._inv = open(os.path.join(layout.out, "invocations.jsonl"), "w")
        self._seq = 0
        self.blocks, self.deviations, self.hook_errors, self.failed_calls = [], [], [], []
        self.n_events = self.n_runs = 0
        self.event_names: set[str] = set()
        self.step_label = ""
        self._actors: list[str] = []

    # ------------------------------------------------------------ environment
    def _env(self, extra: dict) -> dict:
        lay = self.layout
        user = pwd.getpwuid(os.getuid()).pw_name
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": lay.home, "USER": user,
               "LOGNAME": user, "SHELL": "/bin/bash", "LANG": "C.UTF-8", "TERM": "xterm-256color",
               "CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli", "CLAUDE_PROJECT_DIR": lay.project,
               "PYTHONDONTWRITEBYTECODE": "1"}
        if lay.config_dir:
            env["CLAUDE_CONFIG_DIR"] = lay.config_dir
        env.update(hookrun.settings_env(self.settings))
        env["CLAUDE_STATE_DIR"] = lay.state
        paths = {"{home}": lay.home, "{harness}": lay.harness, "{project}": lay.project, "{state}": lay.state,
                 "{sb}": lay.sb}
        for k, v in extra.items():
            v = str(v)
            for name, path in paths.items():
                v = v.replace(name, path)
            env[k] = v
        st = env["CLAUDE_STATE_DIR"]
        if not os.path.isabs(st) or os.path.normpath(st) == "/tmp":  # rule 8: never the shared default
            raise ValueError(f"CLAUDE_STATE_DIR must be an absolute directory other than /tmp, not {st!r}")
        return env

    # ------------------------------------------------------------ ids, markers, steps
    def new_tool_id(self) -> str:
        tid = "toolu_" + uuid.uuid4().hex[:24]
        self.ids.add("tool", tid)
        return tid

    def task(self, value) -> None:
        self.ids.add("task", value)

    def lane(self, value) -> None:
        self.ids.add("lane", value)

    def rand(self, value) -> None:
        """A random name part the replay learned (a mktemp suffix a later step names)."""
        self.ids.add("rand", value)

    def mark(self, kind: str, value: str) -> None:
        """A step or actor marker: a file the trace sees created, its value kept in markers.jsonl."""
        self._seq += 1
        self._markers.write(json.dumps({"seq": self._seq, "kind": kind, "value": value}) + "\n")
        self._markers.flush()
        try:
            os.close(os.open(os.path.join(self.layout.markers, f"{self._seq:07d}.{kind}"),
                             os.O_WRONLY | os.O_CREAT, 0o644))
        except OSError:
            pass

    @contextmanager
    def acting(self, role: str):
        """Attribute what the driver process does inside to `role` (restores the enclosing role after)."""
        self._actors.append(role)
        self.mark("actor", role)
        try:
            yield
        finally:
            self._actors.pop()
            self.mark("actor", self._actors[-1] if self._actors else "")

    def step(self, kind: str, label: str, data: dict) -> dict:
        data = dict(data, kind=kind, label=label)
        self.step_label = label
        self.mark("step", label)
        self._fault("before", data)
        return data

    def after(self, data: dict, result) -> None:
        self._fault("after", dict(data, result=result))

    def _fault(self, phase: str, data: dict) -> None:
        for pattern, fn in self.faults:
            if fnmatch.fnmatchcase(data["label"], pattern):
                fn(self, phase, data)

    # ------------------------------------------------------------ hooks
    def fire(self, session: "Session", event: str, label: str, extra=None, agent=None) -> Event:
        payload = session.base(event, agent)
        payload.update(extra or {})
        # The event's own marker: the trace attributes each hook process's file operations to this
        # event, and invocations.jsonl keeps what re-running it needs (E1's differential).
        self.mark("event", str(self.n_events + 1))
        rec = hookrun.run_event(self.settings, event, payload, self.env, self.layout.project, self.parallel)
        self._inv.write(json.dumps({"seq": self.n_events + 1, "event": event, "label": label,
                                    "payload": dict(payload, hook_event_name=event),
                                    "hooks": [{k: h[k] for k in ("hook", "command", "matcher", "timeout", "rc",
                                                                 "verdict", "how")} for h in rec["hooks"]]})
                        + "\n")
        self._inv.flush()
        rec.update(label=label, session=session.sid, tool=payload.get("tool_name"),
                   agent_type=(agent[1] if agent else payload.get("agent_type")),
                   t=round(time.time() - self.window.start, 3))
        self.n_events += 1
        self.n_runs += len(rec["hooks"])
        self.event_names.add(event)
        for h in rec["hooks"]:
            if h["verdict"] == "error":
                self.hook_errors.append({"step": label, "event": event, "hook": h["hook"], "how": h["how"],
                                         "stderr": self.norm_text(h["stderr"])[-600:]})
        self._log.write(json.dumps(rec) + "\n")
        self._log.flush()
        return Event(rec)

    def norm_text(self, text: str) -> str:
        return norm.refusal_text(text, self.roots, self.ids, self.window)

    def settle(self, ev: Event | None, label: str, deviation=None) -> bool:
        """Record the event's blocks; pass those a declared deviation covers. True if still blocked."""
        if ev is None or not ev.blocks:
            return False
        devs, left = _as_list(deviation), []
        for b in ev.blocks:
            raw = hookrun.refusal(b)
            text = self.norm_text(raw)
            dev = next((d for d in devs if d.covers(b["hook"], raw, text)), None)
            # step_norm: the label with the run's own ids normalised (a label naming an artifact path
            # holds the session id or a task id), so kept-block comparisons hold across runs.
            self.blocks.append({"step": label, "event": ev.event, "hook": b["hook"], "how": b["how"],
                                "text": text, "passed_by_deviation": dev is not None,
                                "step_norm": self.norm_text(label)})
            if dev:
                self.deviations.append({"step": label, "event": ev.event, "hook": b["hook"],
                                        "quote": dev.quote, "why": dev.why, "text": text})
            else:
                left.append(b)
        ev.still_blocked = bool(left)
        return ev.still_blocked

    # ------------------------------------------------------------ sessions
    def session(self, sid: str | None = None, start: str | None = "startup") -> "Session":
        s = Session(self, sid)
        if start:
            s.start(start)
        return s

    def later_session(self, previous: "Session | None" = None, end_reason: str = "prompt_input_exit") -> "Session":
        """A later session on the same project (for /close or /commit typed after /dev)."""
        if previous is not None:
            previous.end(end_reason)
        return self.session()

    # ------------------------------------------------------------ results
    def summary(self, wall_s: float) -> dict:
        return {"pipeline": self.pipeline, "settings": self.settings_label,
                "hook_events": self.n_events, "hook_runs": self.n_runs,
                "events": sorted(self.event_names), "blocks": len(self.blocks),
                "blocks_passed": sum(b["passed_by_deviation"] for b in self.blocks),
                "deviations": len(self.deviations), "hook_errors": len(self.hook_errors),
                "failed_calls": len(self.failed_calls), "respellings": len(self.respellings),
                "args": self.args, "wall_s": round(wall_s, 2)}

    def finish(self, wall_s: float, driver_error: str = "") -> dict:
        self.window.end = time.time()
        out = self.layout.out
        summ = self.summary(wall_s)
        summ["driver_error"] = driver_error
        with open(os.path.join(out, "blocks.json"), "w") as fh:
            json.dump({"blocks": self.blocks, "deviations": self.deviations, "hook_errors": self.hook_errors,
                       "failed_calls": self.failed_calls, "respellings": self.respellings}, fh, indent=1)
        with open(os.path.join(out, "ids.json"), "w") as fh:
            json.dump({"ids": self.ids.to_json(), "window": [self.window.start, self.window.end],
                       "layout": self.layout.to_json()}, fh, indent=1)
        with open(os.path.join(out, "summary.json"), "w") as fh:
            json.dump(summ, fh, indent=1)
        with open(os.path.join(out, "env.json"), "w") as fh:
            json.dump(self.env, fh, indent=1, sort_keys=True)  # what every hook got
        with open(os.path.join(out, "bash-env.json"), "w") as fh:
            json.dump(self.bash_env, fh, indent=1, sort_keys=True)  # what every Bash call got, with its session's id
        self._log.close()
        self._markers.close()
        self._inv.close()
        return summ


class Session:
    def __init__(self, rp: Replay, sid: str | None = None):
        self.rp = rp
        self.sid = sid or str(uuid.uuid4())
        rp.ids.add("sid", self.sid)
        self.tdir = f"{rp.layout.harness}/projects/{rp.slug}"
        self.tpath = f"{self.tdir}/{self.sid}.jsonl"
        self.parent = None
        self._agent_parent: dict[str, str | None] = {}
        self._queued = False
        self.main = Actor(self, None)

    def agent_tpath(self, agent_id: str) -> str:
        return f"{self.tdir}/{self.sid}/subagents/agent-{agent_id}.jsonl"

    def _write(self, path: str, rec: dict) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as fh:
            fh.write(json.dumps(rec) + "\n")

    def append(self, rec: dict, agent_id: str | None = None) -> dict:
        rec = dict(rec)
        rec.setdefault("uuid", str(uuid.uuid4()))
        if agent_id:
            rec.setdefault("parentUuid", self._agent_parent.get(agent_id))
            rec["isSidechain"], rec["agentId"] = True, agent_id
            self._agent_parent[agent_id] = rec["uuid"]
            path = self.agent_tpath(agent_id)
        else:
            rec.setdefault("parentUuid", self.parent)
            rec.setdefault("isSidechain", False)
            self.parent = rec["uuid"]
            path = self.tpath
        for k, v in (("userType", "external"), ("cwd", self.rp.layout.project), ("sessionId", self.sid),
                     ("version", CLI_VERSION), ("timestamp", now_iso())):
            rec.setdefault(k, v)
        self._write(path, rec)
        return rec

    def base(self, event: str, agent=None) -> dict:
        p = {"session_id": self.sid, "transcript_path": self.tpath, "cwd": self.rp.layout.project,
             "hook_event_name": event, "permission_mode": "default"}
        if agent:
            p["agent_id"], p["agent_type"] = agent
        return p

    def fire(self, event: str, label: str, extra=None, agent=None) -> Event:
        return self.rp.fire(self, event, label, extra, agent)

    # ------------------------------------------------------------ session events
    def start(self, source: str = "startup", label: str | None = None) -> Event:
        label = label or f"SessionStart {source}"
        self.rp.step("event", label, {"event": "SessionStart"})
        ev = self.fire("SessionStart", label, {"source": source, "model": MODEL})
        self.rp.settle(ev, label)
        return ev

    def end(self, reason: str = "prompt_input_exit", label: str | None = None) -> Event:
        label = label or f"SessionEnd {reason}"
        self.rp.step("event", label, {"event": "SessionEnd"})
        ev = self.fire("SessionEnd", label, {"reason": reason})
        self.rp.settle(ev, label)
        return ev

    def _queue(self, text: str) -> None:
        if not self._queued:
            for op in ({"operation": "enqueue", "content": text}, {"operation": "dequeue"}):
                self._write(self.tpath, {"type": "queue-operation", **op, "timestamp": now_iso(),
                                         "sessionId": self.sid})
            self._queued = True

    def _context(self, ev: Event) -> None:
        for h in ev.hooks:
            out = h["stdout"].strip()
            if h["verdict"] != "ok" or not out:
                continue
            try:
                j = json.loads(out)
            except ValueError:
                j = None
            if isinstance(j, dict):
                out = (j.get("hookSpecificOutput") or {}).get("additionalContext") or ""
            if out:
                self.append({"type": "attachment", "attachment": {"type": "hook_additional_context",
                                                                  "content": out, "hookName": ev.event}})

    def prompt(self, text: str, label: str | None = None, deviation=None) -> Event:
        """A plain human prompt."""
        label = label or "prompt"
        step = self.rp.step("prompt", label, {"text": text, "deviation": deviation})
        self._queue(step["text"])
        ev = self.fire("UserPromptSubmit", label, {"prompt": step["text"]})
        if not self.rp.settle(ev, label, step["deviation"]):
            self.append({"type": "user", "message": {"role": "user", "content": step["text"]}})
            self._context(ev)
        self.rp.after(step, ev)
        return ev

    def slash(self, name: str, args: str = "", label: str | None = None, deviation=None) -> Event:
        """A typed slash command: UserPromptSubmit, the command-name record, the isMeta command body."""
        label = label or f"/{name}"
        step = self.rp.step("slash", label, {"name": name, "args": args, "deviation": deviation})
        name, args = step["name"], step["args"]
        text = f"/{name} {args}".strip()
        self._queue(text)
        ev = self.fire("UserPromptSubmit", label, {"prompt": text})
        if not self.rp.settle(ev, label, step["deviation"]):
            self.append({"type": "user", "message": {"role": "user", "content":
                         f"<command-message>{name} is running…</command-message>\n"
                         f"<command-name>/{name}</command-name>\n<command-args>{args}</command-args>"}})
            body = cmdtext.command_body(self.rp.layout.harness, name, args)
            self.append({"type": "user", "isMeta": True,
                         "message": {"role": "user", "content": [{"type": "text", "text": body}]}})
            self._context(ev)
        self.rp.after(step, ev)
        return ev

    def say(self, text: str, agent_id: str | None = None) -> None:
        self.append({"type": "assistant", "message": {"role": "assistant", "model": MODEL,
                                                      "content": [{"type": "text", "text": text}]}}, agent_id)

    def stop(self, text: str | None = None, label: str = "Stop", deviation=None, on_block=None,
             rounds: int = 2) -> Event:
        """The main agent's final text, then Stop. on_block(session, event) may continue and return True to stop again."""
        step = self.rp.step("stop", label, {"text": text, "deviation": deviation})
        if step["text"]:
            self.say(step["text"])
        active = False
        for _ in range(max(1, rounds)):
            ev = self.fire("Stop", label, {"stop_hook_active": active})
            if not self.rp.settle(ev, label, step["deviation"]) or not on_block or not on_block(self, ev):
                break
            active = True
        self.rp.after(step, ev)
        return ev

    # ------------------------------------------------------------ main-agent shorthands
    def tool(self, *a, **k) -> Call:
        return self.main.tool(*a, **k)

    def bash(self, *a, **k) -> Call:
        return self.main.bash(*a, **k)

    def read(self, *a, **k) -> Call:
        return self.main.read(*a, **k)

    def write(self, *a, **k) -> Call:
        return self.main.write(*a, **k)

    def edit(self, *a, **k) -> Call:
        return self.main.edit(*a, **k)

    def todo(self, *a, **k) -> Call:
        return self.main.todo(*a, **k)

    def dispatch(self, *a, **k) -> Dispatch:
        return self.main.dispatch(*a, **k)


class Actor:
    """The main agent (agent=None) or one subagent (agent=(agent_id, agent_type)) of a session."""

    def __init__(self, session: Session, agent):
        self.s, self.rp, self.agent = session, session.rp, agent
        self.role = f"agent:{agent[1]}" if agent else "main"
        self.calls = 0
        self.todos: list = []

    @property
    def aid(self):
        return self.agent[0] if self.agent else None

    # ------------------------------------------------------------ tool calls
    def tool(self, name: str, tinput: dict, perform=None, label: str | None = None, deviation=None) -> Call:
        label = label or f"{self.role} {name}"
        if deviation is None and self.rp.deviation_at is not None:
            deviation = self.rp.deviation_at(label)
        step = self.rp.step("tool", label, {"name": name, "input": tinput, "perform": perform,
                                            "deviation": deviation, "actor": self})
        call = Call(label, step["name"])
        if step.get("skip"):
            call.skipped = True
            return call
        name, tinput = step["name"], step["input"]
        call.tool_use_id = tid = self.rp.new_tool_id()
        self.calls += 1
        self.s.append({"type": "assistant", "message": {"role": "assistant", "model": MODEL, "content": [
            {"type": "tool_use", "id": tid, "name": name, "input": tinput}]}}, self.aid)
        call.pre = self.s.fire("PreToolUse", label, {"tool_name": name, "tool_input": tinput, "tool_use_id": tid},
                               self.agent)
        if self.rp.settle(call.pre, label, step["deviation"]):
            call.blocked = True
            text = "\n".join(hookrun.refusal(b) for b in call.pre.blocks)
            self._result(tid, f"PreToolUse:{name} hook error: {text}", error=True)
            self.rp.after(step, call)
            return call
        perform = step["perform"] or _default_perform(self, name, tinput)
        try:
            with self.rp.acting(self.role):
                call.response = perform() or {}
            call.ok = True
        except Exception as e:  # a failing call is an error tool_result; the replay goes on
            call.error = str(e) or type(e).__name__
            self.rp.failed_calls.append({"step": label, "tool": name, "error": self.rp.norm_text(call.error)[:600]})
        if call.ok:
            self._result(tid, _result_text(call.response), resp=call.response)
            call.post = self.s.fire("PostToolUse", label, {"tool_name": name, "tool_input": tinput,
                                                           "tool_response": call.response, "tool_use_id": tid},
                                    self.agent)
        else:
            self._result(tid, call.error, error=True)
            call.post = self.s.fire("PostToolUseFailure", label, {"tool_name": name, "tool_input": tinput,
                                                                  "tool_use_id": tid, "error": call.error,
                                                                  "is_interrupt": False}, self.agent)
        self.rp.settle(call.post, label, step["deviation"])
        self.rp.after(step, call)
        return call

    def _result(self, tid: str, content, error: bool = False, resp=None) -> None:
        block = {"type": "tool_result", "tool_use_id": tid, "content": content}
        if error:
            block["is_error"] = True
        rec = {"type": "user", "message": {"role": "user", "content": [block]}}
        if resp is not None:
            rec["toolUseResult"] = resp
        self.s.append(rec, self.aid)

    def bash(self, command: str, description: str = "", label: str | None = None, deviation=None,
             timeout: int | None = None) -> Call:
        tinput = {"command": command, "description": description or command[:60]}
        if timeout:
            tinput["timeout"] = timeout * 1000
        return self.tool("Bash", tinput, label=label or f"{self.role} Bash", deviation=deviation)

    def read(self, path: str, label: str | None = None, deviation=None, **opts) -> Call:
        return self.tool("Read", {"file_path": path, **opts}, label=label, deviation=deviation)

    def write(self, path: str, content: str, label: str | None = None, deviation=None) -> Call:
        return self.tool("Write", {"file_path": path, "content": content}, label=label, deviation=deviation)

    def edit(self, path: str, old: str, new: str, label: str | None = None, deviation=None,
             replace_all: bool = False) -> Call:
        return self.tool("Edit", {"file_path": path, "old_string": old, "new_string": new,
                                  "replace_all": replace_all}, label=label, deviation=deviation)

    def todo(self, todos: list, label: str | None = None, deviation=None) -> Call:
        return self.tool("TodoWrite", {"todos": todos}, label=label, deviation=deviation)

    # ------------------------------------------------------------ dispatch
    def dispatch(self, subagent_type: str, prompt: str, description: str = "", body=None, result: str = "Done.",
                 label: str | None = None, deviation=None, extra_input: dict | None = None,
                 on_stop_block=None, stop_rounds: int = 2) -> Dispatch:
        """A foreground Agent dispatch; body(sub_actor) performs the subagent's own calls."""
        label = label or f"{self.role} Agent({subagent_type})"
        if deviation is None and self.rp.deviation_at is not None:
            deviation = self.rp.deviation_at(label)
        step = self.rp.step("dispatch", label, {"subagent_type": subagent_type, "prompt": prompt,
                                                "description": description, "body": body, "result": result,
                                                "deviation": deviation, "extra_input": extra_input or {}})
        d = Dispatch(label, "Agent", agent_type=step["subagent_type"])
        if step.get("skip"):
            d.skipped = True
            return d
        atype, prompt = step["subagent_type"], step["prompt"]
        agent_in = {"description": step["description"] or atype, "prompt": prompt, "subagent_type": atype,
                    "run_in_background": False, **step["extra_input"]}
        d.tool_use_id = tid = self.rp.new_tool_id()
        self.calls += 1
        self.s.append({"type": "assistant", "message": {"role": "assistant", "model": MODEL, "content": [
            {"type": "tool_use", "id": tid, "name": "Agent", "input": agent_in}]}}, self.aid)
        d.pre = self.s.fire("PreToolUse", label, {"tool_name": "Agent", "tool_input": agent_in, "tool_use_id": tid},
                            self.agent)
        if self.rp.settle(d.pre, label, step["deviation"]):
            d.blocked = True
            text = "\n".join(hookrun.refusal(b) for b in d.pre.blocks)
            self._result(tid, f"PreToolUse:Agent hook error: {text}", error=True)
            self.rp.after(step, d)
            return d
        d.agent_id = aid = "a" + uuid.uuid4().hex[:16]
        self.rp.ids.add("agent", aid)
        sub = d.actor = Actor(self.s, (aid, atype))
        t0 = time.monotonic()
        self.s.append({"type": "user", "message": {"role": "user", "content": prompt}}, aid)
        meta = os.path.join(os.path.dirname(self.s.agent_tpath(aid)), f"agent-{aid}.meta.json")
        with open(meta, "w") as fh:
            json.dump({"agentType": atype, "description": agent_in["description"], "toolUseId": tid}, fh)
        if step["body"]:
            step["body"](sub)
        final = step["result"](sub) if callable(step["result"]) else step["result"]
        active = False
        for _ in range(max(1, stop_rounds)):
            self.s.say(final, aid)
            d.stop = self.s.fire("SubagentStop", f"{label} stop", {
                "stop_hook_active": active, "agent_id": aid, "agent_type": atype,
                "agent_transcript_path": self.s.agent_tpath(aid), "last_assistant_message": final})
            if not self.rp.settle(d.stop, f"{label} stop", step["deviation"]) or not on_stop_block:
                break
            nxt = on_stop_block(sub, d.stop)
            if not nxt:
                break
            final, active = nxt, True
        d.response = {"status": "completed", "prompt": prompt, "agentId": aid,
                      "content": [{"type": "text", "text": final}],
                      "totalDurationMs": int((time.monotonic() - t0) * 1000), "totalTokens": 0,
                      "totalToolUseCount": sub.calls, "usage": {"input_tokens": 0, "output_tokens": 0}}
        self._result(tid, [{"type": "text", "text": final}], resp=d.response)
        d.post = self.s.fire("PostToolUse", label, {"tool_name": "Agent", "tool_input": agent_in,
                                                    "tool_response": d.response, "tool_use_id": tid}, self.agent)
        self.rp.settle(d.post, label, step["deviation"])
        d.ok = not d.stop.still_blocked
        self.rp.after(step, d)
        return d


# ---------------------------------------------------------------- tool effects

def _result_text(resp) -> str:
    if isinstance(resp, dict):
        if "stdout" in resp:
            return (resp.get("stdout", "") + resp.get("stderr", "")).strip() or "(no output)"
        if "file" in resp:
            return resp["file"].get("content", "")
    return json.dumps(resp)[:4000]


def _default_perform(actor: Actor, name: str, ti: dict):
    """What the CLI's own tool does; raises ToolError where the CLI's tool would fail."""
    project = actor.rp.layout.project

    def read():
        path = ti["file_path"]
        if not os.path.isfile(path):
            raise ToolError(f"File does not exist. Current working directory: {project}")
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().split("\n")
        start = max(int(ti.get("offset") or 1), 1)
        chunk = lines[start - 1:start - 1 + int(ti.get("limit") or 2000)]
        return {"type": "text", "file": {"filePath": path, "content": "\n".join(chunk), "numLines": len(chunk),
                                         "startLine": start, "totalLines": len(lines)}}

    def write():
        path, content = ti["file_path"], ti["content"]
        kind = "update" if os.path.exists(path) else "create"
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return {"type": kind, "filePath": path, "content": content, "structuredPatch": []}

    def edit():
        path, old, new = ti["file_path"], ti["old_string"], ti["new_string"]
        if not os.path.isfile(path):
            raise ToolError("File does not exist.")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        n = text.count(old) if old else 0
        if n == 0:
            raise ToolError("String to replace not found in file.")
        if n > 1 and not ti.get("replace_all"):
            raise ToolError(f"Found {n} matches of the string to replace, but replace_all is false.")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace(old, new) if ti.get("replace_all") else text.replace(old, new, 1))
        return {"filePath": path, "oldString": old, "newString": new, "originalFile": text,
                "structuredPatch": [], "userModified": False, "replaceAll": bool(ti.get("replace_all"))}

    def bash():
        timeout = (ti.get("timeout") or BASH_TIMEOUT_S * 1000) / 1000
        # The CLI's Bash exports the session id (landscape B-breakages.md:45), the one a subagent's calls share.
        env = dict(actor.rp.bash_env, CLAUDE_CODE_SESSION_ID=actor.s.sid)
        try:
            p = subprocess.run(["bash", "-c", ti["command"]], cwd=project, env=env, capture_output=True,
                               text=True, timeout=timeout, errors="replace")
        except subprocess.TimeoutExpired:
            raise ToolError(f"Command timed out after {timeout:.0f}s")
        if p.returncode:
            raise ToolError(f"Exit code {p.returncode}\n{p.stderr}{p.stdout}".strip())
        return {"stdout": p.stdout, "stderr": p.stderr, "interrupted": False, "isImage": False}

    def glob():
        base = ti.get("path") or project
        found = sorted(f for f in _glob.glob(os.path.join(base, ti["pattern"]), recursive=True) if os.path.isfile(f))
        return {"filenames": found, "durationMs": 1, "numFiles": len(found), "truncated": False}

    def grep():
        base, rx = ti.get("path") or project, re.compile(ti["pattern"])
        hits = []
        for dp, dns, fns in os.walk(base):
            dns[:] = sorted(d for d in dns if d != ".git")
            for fn in sorted(fns):
                p = os.path.join(dp, fn)
                try:
                    with open(p, encoding="utf-8", errors="ignore") as fh:
                        if rx.search(fh.read()):
                            hits.append(os.path.relpath(p, base))
                except OSError:
                    pass
        return {"mode": "files_with_matches", "filenames": hits, "numFiles": len(hits)}

    def todo():
        old, actor.todos = actor.todos, ti["todos"]
        return {"oldTodos": old, "newTodos": ti["todos"]}

    def ask():
        """The owner picks each question's recommended option (else its first)."""
        answers = {}
        for q in ti.get("questions") or []:
            opts = [o.get("label", "") for o in q.get("options") or []]
            answers[q.get("question", "")] = next((o for o in opts if "(Recommended)" in o), opts[0] if opts else "")
        return {"questions": ti.get("questions") or [], "answers": answers}

    return {"Read": read, "Write": write, "Edit": edit, "Bash": bash, "Glob": glob, "Grep": grep,
            "TodoWrite": todo, "AskUserQuestion": ask}.get(name, lambda: {})
