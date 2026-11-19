"""D25 X6, the other half: every requirement a gate states has a permitted means, for every role that
meets it and wherever the project lies.

sites.py enumerates the blocking sites and test_no_dead_end.py shows a replay clears each one. A site
is classed once, not per role and finding, and every replay puts the project under the home
directory, so a requirement that one role cannot meet, or that no one can meet on a RAM disk, stays
unseen there. Here the requirements are enumerated from the code, each is crossed with the roles that
meet it and with where the project lies (SITUATIONS), and each means of meeting it is put to the hook
that decides that means, run as the CLI runs it:

  declared artifact  each file artifact (a kind whose fields require a path, hooks/lib/obligation.py)
                     of each obligation template of commands/*.md (the artifact check's own scanner,
                     tests/artifact_graph/mdscan.obligations), for each role the template dispatches
                     (a placeholder role: each agent schemas/test-plan.v1.json assigns, the agents the
                     template says it means). G2 (hooks/subagentstop-artifact-contract-enforce.py)
                     holds the stop until the file exists and passes, so two requirements:
                       create  the file is missing (artifact_missing): Write;
                       repair  the file exists and fails (every other finding on it): Edit in place,
                               or Write over it.
                     Each means is decided by the write gate (hooks/pretool-write-gate.py: its rules,
                     its runner, its combine) on the dispatched subagent's own call, the dispatch
                     recorded as the CLI records one (the call, the child's first record, its meta).
  ordering           G1's order rule (hooks/pretool-obligation-gate.py, R17): a dispatch that names an
                     artifact an earlier dispatch declared waits until that dispatch has returned, and
                     a non-verdict one until a verdict dispatched after that return has returned. For
                     each template's dispatch as the producer: once it has returned, the verdict
                     template's dispatch (the one declaring G1's VERDICT_SCHEMA) naming its artifacts
                     must pass, and once that verdict has returned too, the producer's own template
                     dispatched again naming them must pass. In each transcript shape the CLI writes
                     (TRANSCRIPT_SHAPES).
  wait               G2's canonical wire (_wire_canonical) at the stop of a fan-out lane (a template
                     declaring a lane report, hooks/lib/dev_report_shard_patterns.py): the canonical
                     aggregate has one writer, scripts/aggregate-dev-report.py, which reads every
                     lane's report. For each field of the lane report's schema that takes free text: a
                     sibling lane's report holding prose there, which that sibling's own stop accepts
                     (its schema validation, contract_runtime), and the stopping lane's own means
                     (saving its own report again, which runs the aggregator; an Edit of a field of its own
                     report the finding names, to agree with the sibling's; an Edit of the
                     sibling's report, put to the write gate). If none clears it, the stopping lane
                     waits on a lane that has stopped, which only the main agent can dispatch again,
                     while the main agent waits for the stopping lane: a circular wait.

A requirement with no permitted means in some situation is a contradiction; nothing is exempt.
"""
from __future__ import annotations

import collections
import contextlib
import datetime
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOKS = os.path.join(REPO, "hooks")
PLACEHOLDER = re.compile(r"<[^<>\n]+>|\{[A-Za-z_.]+\}")
CLI_VERSION = "2.1.326"
# Where the project lies. A home path: under the user's home (HARNESS_TEST_PROJECT_ROOT names another directory
# outside /tmp, /var/tmp and /dev, where the write rules treat a project as they treat one under a home);
# a RAM disk: under /dev/shm, the tmpfs a project may live on (and where this harness home lies on the
# machine that found C1).
SITUATIONS = ("home", "ram-disk")
# The transcript shapes the CLI writes around a tool call. recorded: the records of the recorded CLI
# fixtures (tests/fixtures/cli; tests/replay/replay.py writes them so). api-request-blob: CLI 2.1.322 also
# writes, after a tool call's result, a record {"type": "api-request-blob", "sessionId", "hash", "message"}
# that repeats the assistant message that made the call (observed in the sessions in which R17 refused).
TRANSCRIPT_SHAPES = ("recorded", "api-request-blob")


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _lib(name: str):
    if HOOKS not in sys.path:
        sys.path.insert(0, HOOKS)
    return importlib.import_module(f"lib.{name}")


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- the templates

@dataclass
class Template:
    command: str
    line: int
    role: str          # the role this row dispatches (a placeholder role expanded)
    template_role: str
    pipeline: str
    profile: str
    artifacts: list
    profiles: tuple = ()

    @property
    def site(self) -> str:
        return f"commands/{self.command}.md:{self.line}"


def _placeholder_roles() -> list:
    """The agents a placeholder role (role="<specialist.type>") stands for: the template says they are
    the agents the test plan's agent_assignments names, which schemas/test-plan.v1.json requires."""
    with open(os.path.join(REPO, "schemas", "test-plan.v1.json")) as fh:
        return list(json.load(fh)["properties"]["agent_assignments"]["required"])


def templates(repo: str = REPO) -> list:
    """Every obligation template of commands/*.md, one per role it dispatches."""
    sys.path.insert(0, os.path.join(repo, "tests"))
    try:
        from artifact_graph import mdscan
    finally:
        sys.path.pop(0)
    out = []
    for name in sorted(os.listdir(os.path.join(repo, "commands"))):
        if not name.endswith(".md"):
            continue
        with open(os.path.join(repo, "commands", name), encoding="utf-8") as fh:
            text = fh.read()
        for ob in mdscan.obligations(text):
            role = ob.get("role") or ""
            for r in _placeholder_roles() if PLACEHOLDER.fullmatch(role) else [role]:
                out.append(Template(name[:-3], ob.get("line"), r, role, ob.get("pipeline"),
                                    ([p for p in ob.get("profile") or [] if p] or ["singular"])[0],
                                    ob.get("artifacts") or [], tuple(p for p in ob.get("profile") or [] if p)))
    return out


def file_kind(kind) -> bool:
    """A kind whose fields require a path (hooks/lib/obligation.py's file kinds)."""
    return _lib("obligation").FRESHNESS_SLACK_SECONDS_BY_KIND.get(kind) is not None


def bind(value, tid: str, role: str):
    """The template's placeholders bound to one dispatch's values, as an orchestrator fills them."""
    def one(m):
        inner = m.group(0).strip("<>{}").lower()
        return ("A" if "angle" in inner else "g1" if "group" in inner else f"ovn-{tid}" if "session" in inner
                else "1" if inner == "n" else role if "specialist" in inner else "l1" if inner == "lane" else tid)
    if isinstance(value, str):
        return PLACEHOLDER.sub(one, value)
    if isinstance(value, dict):
        return {k: bind(v, tid, role) for k, v in value.items()}
    if isinstance(value, list):
        return [bind(v, tid, role) for v in value]
    return value


def obligation_of(t: Template, tid: str, artifacts=None) -> dict:
    return {"task_id": None if t.profile == "ad_hoc" else tid, "lane": None, "lane_set": None, "role": t.role,
            "pipeline": t.pipeline, "profile": t.profile, "dispatched_at": now(),
            "artifacts": bind(t.artifacts if artifacts is None else artifacts, tid, t.role)}


def prompt_of(ob: dict, extra: str = "") -> str:
    return (f"You are the {ob['role']} subagent. Follow agents/{ob['role']}.md.\n\n<obligation v=\"1\">\n"
            f"{json.dumps(ob)}\n</obligation>\n\n{extra}")


# ---------------------------------------------------------------- a session as the CLI keeps it

class Store:
    """A session transcript and its subagents' files, in the CLI's layout and record shapes."""

    def __init__(self, root: str, project: str, shape: str = "recorded"):
        self.sid = str(uuid.uuid4())
        self.dir = os.path.join(root, self.sid[:8])
        self.transcript = os.path.join(self.dir, f"{self.sid}.jsonl")
        self.subagents = os.path.join(self.dir, self.sid, "subagents")
        os.makedirs(self.subagents)
        self.project, self.shape, self.parent = project, shape, None
        open(self.transcript, "w").close()

    def append(self, rec: dict) -> None:
        rec = {"parentUuid": self.parent, "isSidechain": False, "userType": "external", "cwd": self.project,
               "sessionId": self.sid, "version": CLI_VERSION, "uuid": str(uuid.uuid4()),
               "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"), **rec}
        self.parent = rec["uuid"]
        with open(self.transcript, "a") as fh:
            fh.write(json.dumps(rec) + "\n")

    def slash(self, command: str) -> None:
        self.append({"type": "user", "message": {"role": "user", "content":
                     f"<command-message>{command} is running…</command-message>\n"
                     f"<command-name>/{command}</command-name>\n<command-args>x</command-args>"}})

    def dispatch(self, role: str, prompt: str, returned: bool = True) -> tuple:
        """An Agent call, the child the CLI starts for it, and (``returned``) its completed result;
        (call id, agent id)."""
        call, agent = "toolu_" + uuid.uuid4().hex[:24], "a" + uuid.uuid4().hex[:16]
        use = {"type": "tool_use", "id": call, "name": "Agent",
               "input": {"description": f"{role} dispatch", "subagent_type": role, "prompt": prompt}}
        self.append({"type": "assistant", "message": {"role": "assistant", "content": [use]}})
        with open(os.path.join(self.subagents, f"agent-{agent}.jsonl"), "w") as fh:
            fh.write(json.dumps({"type": "user", "isSidechain": True, "agentId": agent, "sessionId": self.sid,
                                 "message": {"role": "user", "content": prompt}}) + "\n")
        with open(os.path.join(self.subagents, f"agent-{agent}.meta.json"), "w") as fh:
            json.dump({"agentType": role, "toolUseId": call}, fh)
        if returned:
            self.append({"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": call, "content": [{"type": "text", "text": "Done."}]}]},
                "toolUseResult": {"status": "completed", "prompt": prompt, "agentId": agent,
                                  "content": [{"type": "text", "text": "Done."}]}})
            if self.shape == "api-request-blob":
                with open(self.transcript, "a") as fh:
                    fh.write(json.dumps({"type": "api-request-blob", "sessionId": self.sid,
                                         "hash": hashlib.sha256(json.dumps(use).encode()).hexdigest(),
                                         "message": {"role": "assistant", "content": [use]}}) + "\n")
        return call, agent

    def payload(self, tool: str, tool_input: dict, agent: tuple | None = None) -> dict:
        p = {"session_id": self.sid, "transcript_path": self.transcript, "cwd": self.project,
             "hook_event_name": "PreToolUse", "permission_mode": "default", "tool_name": tool,
             "tool_input": tool_input, "tool_use_id": "toolu_" + uuid.uuid4().hex[:24]}
        if agent:
            p.update(agent_id=agent[0], agent_type=agent[1])
        return p


# ---------------------------------------------------------------- the hooks, run as the CLI runs them

# One process per project runs that project's write-gate calls, as the gate runs its rules where it does
# not fork: one after another in its own process (hooks/pretool-write-gate.py _runs, lib/rule_runner), their
# answers combined by its combine; what it prints is the gate's answer.
_WORKER = r"""
import importlib.util, json, os, sys
sys.path.insert(0, sys.argv[1])
from lib.rule_runner import run_rule
from lib.write_gate import RULES, combine
for line in sys.stdin:
    raw = line.strip().encode()
    tool = json.loads(raw).get("tool_name")
    answer = combine([(r, run_rule(r.file, raw, r.budget)) for r in RULES if r.applies(tool)])
    print(json.dumps({"code": answer.code, "stdout": answer.stdout, "stderr": answer.stderr}), flush=True)
"""


class Hooks:
    """The environment every hook run here gets: a throwaway home, config, state and temp directory."""

    def __init__(self, work: str):
        self.work = work
        for d in ("home/.claude", "state", "tmp"):
            os.makedirs(os.path.join(work, d), exist_ok=True)
        self._gates = {}

    def env(self, project: str, **extra) -> dict:
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE") and k not in ("TMPDIR", "HOME")}
        env.update(HOME=os.path.join(self.work, "home"), CLAUDE_CONFIG_DIR=os.path.join(self.work, "home/.claude"),
                   CLAUDE_STATE_DIR=os.path.join(self.work, "state"), TMPDIR=os.path.join(self.work, "tmp"),
                   CLAUDE_PROJECT_DIR=project, PYTHONDONTWRITEBYTECODE="1", **extra)
        return env

    def write_gate(self, payload: dict) -> dict:
        project = payload["cwd"]
        if project not in self._gates:
            self._gates[project] = subprocess.Popen([sys.executable, "-c", _WORKER, HOOKS], stdin=subprocess.PIPE,
                                                    stdout=subprocess.PIPE, text=True, cwd=project,
                                                    env=self.env(project))
        gate = self._gates[project]
        gate.stdin.write(json.dumps(payload) + "\n")
        gate.stdin.flush()
        line = gate.stdout.readline()
        if not line:
            raise RuntimeError("the write-gate worker ended")
        return json.loads(line)

    def run(self, hook: str, payload: dict, **extra) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, os.path.join(HOOKS, hook)], input=json.dumps(payload),
                              capture_output=True, text=True, cwd=payload["cwd"], timeout=120,
                              env=self.env(payload["cwd"], **extra))

    def close(self) -> None:
        for gate in self._gates.values():
            gate.stdin.close()
            gate.wait(timeout=60)
        self._gates = {}


@contextlib.contextmanager
def projects(work: str):
    """situation -> a project directory there, each its own git repository; removed afterwards."""
    bases = {"home": os.environ.get("HARNESS_TEST_PROJECT_ROOT") or os.path.expanduser("~"), "ram-disk": "/dev/shm"}
    made = {}
    try:
        for situation in SITUATIONS:
            root = tempfile.mkdtemp(prefix=".deadend-", dir=bases[situation])
            made[situation] = os.path.join(root, "toyproj")
            os.makedirs(made[situation])
            subprocess.run(["git", "init", "-q", made[situation]], check=True)
        yield made
    finally:
        for project in made.values():
            shutil.rmtree(os.path.dirname(project), ignore_errors=True)


# ---------------------------------------------------------------- cells

@dataclass
class Cell:
    row: str            # the requirement, as the audit's matrix names its rows
    kind: str
    situation: str
    actor: str
    means: dict = field(default_factory=dict)   # means -> "permitted" | the refusal's first line
    detail: str = ""

    @property
    def permitted(self) -> bool:
        return any(v == "permitted" for v in self.means.values())


def _answer(a) -> str:
    if a["code"] == 2 or '"permissionDecision": "deny"' in a["stdout"]:
        return next((ln for ln in a["stderr"].splitlines() if ln.strip()), a["stdout"][:300]).strip()[:400]
    return "permitted"


def artifact_cells(hooks: Hooks, made: dict, tpls: list | None = None) -> list:
    """Every declared file artifact of every template, created and repaired, in every situation (one
    thread per situation, each with its own write-gate process)."""
    tpls = tpls if tpls is not None else templates()
    with ThreadPoolExecutor(len(made)) as pool:
        return [c for part in pool.map(lambda s: _artifact_cells(hooks, s, made[s], tpls), made) for c in part]


def _artifact_cells(hooks: Hooks, situation: str, project: str, tpls: list) -> list:
    cells = []
    for n, t in enumerate(tpls):
        files = [a for a in t.artifacts if file_kind(a.get("kind"))]
        if not files:
            continue
        ob = obligation_of(t, (datetime.datetime(2026, 1, 1) + datetime.timedelta(seconds=n)).strftime("%Y%m%d-%H%M%S"))
        store = Store(os.path.join(hooks.work, "stores"), project)
        _call, agent = store.dispatch(t.role, prompt_of(ob), returned=False)
        for raw, art in zip(files, [a for a in ob["artifacts"] if file_kind(a.get("kind"))]):
            rel = art["path"] if raw.get("kind") != "spec_views" else os.path.join(art["path"], "index.md")
            path, row = os.path.join(project, rel), f"A:{t.site}:{t.role}:{raw.get('kind')}:{raw.get('schema') or ''}"
            os.makedirs(os.path.dirname(path), exist_ok=True)  # an established project
            if os.path.exists(path):
                os.unlink(path)

            def ask(tool, tool_input):
                return _answer(hooks.write_gate(store.payload(tool, {"file_path": path, **tool_input}, (agent, t.role))))
            cells.append(Cell(f"{row}:create", "declared artifact", situation, t.role,
                              {"Write": ask("Write", {"content": "{}\n"})}, rel))
            with open(path, "w") as fh:
                fh.write("{}\n")  # a first version G2 refuses
            means = {"Edit in place": ask("Edit", {"old_string": "{}", "new_string": "{ }"})}
            if means["Edit in place"] != "permitted":
                means["Write over it"] = ask("Write", {"content": "{ }\n"})
            cells.append(Cell(f"{row}:repair", "declared artifact", situation, t.role, means, rel))
            os.unlink(path)
    return cells


def order_cells(hooks: Hooks, made: dict, tpls: list | None = None) -> list:
    """G1's order rule after each template's producer has returned, in every transcript shape."""
    gate = _load("obligation_gate_for_requirements", os.path.join(HOOKS, "pretool-obligation-gate.py"))
    tpls = tpls if tpls is not None else templates()
    verdict = next(t for t in tpls if any(a.get("schema") == gate.VERDICT_SCHEMA for a in t.artifacts))
    cells = []
    project = made["home"]
    for n, t in enumerate(tpls):
        files = [a for a in t.artifacts if file_kind(a.get("kind"))]
        if not files or t is verdict:
            continue
        for shape in TRANSCRIPT_SHAPES:
            base = datetime.datetime(2026, 2, 1) + datetime.timedelta(seconds=10 * n)
            tid, later = (base.strftime("%Y%m%d-%H%M%S"), (base + datetime.timedelta(seconds=1)).strftime("%Y%m%d-%H%M%S"))
            store = Store(os.path.join(hooks.work, "stores"), project, shape)
            store.slash(t.command)
            produced = obligation_of(t, tid)
            names = "Read: " + ", ".join(a["path"] for a in produced["artifacts"] if file_kind(a.get("kind")))
            store.dispatch(t.role, prompt_of(produced))
            for label, consumer, ctid in (("the verdict on its artifacts", verdict, later),
                                          ("its next stage, after that verdict returned", t, later)):
                payload = store.payload("Agent", {"description": label, "subagent_type": consumer.role,
                                                  "prompt": prompt_of(obligation_of(consumer, ctid), names)})
                proc = hooks.run("pretool-obligation-gate.py", payload, CLAUDE_OBLIGATION_GATE="block")
                order = [ln.strip() for ln in proc.stderr.splitlines() if ln.strip().startswith("reason=")]
                cells.append(Cell(f"R17:{t.site}:{t.role}:{label}", "ordering", shape, "main agent",
                                  {"dispatch it once the producer has returned":
                                   order[0][:400] if "OBLIGATION GATE ORDER" in proc.stderr and order else "permitted"}))
                if consumer is verdict:
                    store.dispatch(consumer.role, payload["tool_input"]["prompt"])
    return cells


def _free_text(schema: dict, prefix: str = ""):
    """Dotted paths of the fields a schema lets hold any text (a string with no enum, const, pattern or format)."""
    for key, sub in (schema.get("properties") or {}).items():
        types = sub.get("type") if isinstance(sub.get("type"), list) else [sub.get("type")]
        if "string" in types and not any(k in sub for k in ("enum", "const", "pattern", "format")):
            yield prefix + key
        if "object" in types:
            yield from _free_text(sub, prefix + key + ".")


def wait_cells(hooks: Hooks, made: dict, tpls: list | None = None) -> list:
    """G2's canonical wire at a fan-out lane's stop, a sibling lane's report holding prose in one free-text
    field while that sibling's own stop accepts it: the stopping lane's means of clearing it."""
    from tests.replay import schemagen
    patterns = _lib("dev_report_shard_patterns")
    cells, project = [], made["home"]
    git = ["git", "-C", project, "-c", "user.name=replay", "-c", "user.email=replay@example.invalid"]
    subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "baseline"], check=True)
    head = subprocess.run(git + ["rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    lanes = ["l1", "l2"]
    for n, t in enumerate(tpls if tpls is not None else templates()):
        if not any("lane" in p for p in t.profiles):
            continue
        for raw in [a for a in t.artifacts if str(a.get("schema", "")).startswith("dev-report.v2")]:
            schema = schemagen.load(REPO, raw["schema"])
            for k, prose in enumerate(_free_text(schema)):
                tid = (datetime.datetime(2026, 3, 1) + datetime.timedelta(minutes=n, seconds=k)).strftime("%Y%m%d-%H%M%S")
                store = Store(os.path.join(hooks.work, "stores"), project)
                store.slash(t.command)
                agents, paths = {}, {}
                for lane in lanes:
                    art = bind(dict(raw), tid, t.role)
                    stem, ext = os.path.splitext(art["path"])
                    art["path"] = paths[lane] = f"{stem}-{lane}{ext}"  # the lane's report (commands/dev.md)
                    if (patterns.classify_filename(os.path.basename(art["path"])) or ("",))[0] != "worker":
                        break
                    ob = {**obligation_of(t, tid, [art]), "profile": "fanout-lane", "lane": lane, "lane_set": lanes}
                    agents[lane] = store.dispatch(t.role, prompt_of(ob), returned=lane == "l1")[1]
                if len(agents) < 2:
                    continue
                for lane in lanes:  # the sibling's report first: the stopping lane's is the fan-out's newest
                    doc = schemagen.instance(schema, {"task_id": tid, "baseline_head_sha": head, "lane": lane,
                                                      "lane_set": lanes, "baseline_dirty_snapshot": ""}, seed=lane)
                    if lane == "l1":
                        schemagen.set_path(doc, prose, "see the lane write manifest (3 entries)")
                    os.makedirs(os.path.dirname(os.path.join(project, paths[lane])), exist_ok=True)
                    with open(os.path.join(project, paths[lane]), "w") as fh:
                        json.dump(doc, fh, indent=1)
                    if lane == "l2":  # written a second after the sibling's, after the sibling's lane stopped
                        later = os.stat(os.path.join(project, paths["l1"])).st_mtime + 1
                        os.utime(os.path.join(project, paths[lane]), (later, later))

                def stop(lane):
                    agent = agents[lane]
                    return hooks.run("subagentstop-artifact-contract-enforce.py", {
                        "session_id": store.sid, "transcript_path": store.transcript, "cwd": project,
                        "hook_event_name": "SubagentStop", "stop_hook_active": False, "agent_id": agent,
                        "agent_type": t.role, "last_assistant_message": "Done.",
                        "agent_transcript_path": os.path.join(store.subagents, f"agent-{agent}.jsonl")},
                        CLAUDE_OBLIGATION_STOPGATE="block")
                sibling, own = stop("l1"), stop("l2")
                state = f"lane l1's {prose} holds prose"
                row = f"W:{t.site}:{t.role}:{raw['schema']}:canonical_missing"
                if sibling.returncode != 0:
                    cells.append(Cell(row, "wait", "home", f"{t.role} lane l1", {
                        "repair its own report at its own stop": "permitted"}, state + ": refused at l1's own stop"))
                elif "canonical_missing" not in own.stderr:
                    cells.append(Cell(row, "wait", "home", f"{t.role} lane l2", {
                        "stop": "permitted"}, state + ": no canonical_missing at l2's stop"))
                else:
                    me, own_path = (agents["l2"], t.role), os.path.join(project, paths["l2"])

                    def edit_own(change: dict) -> str:
                        """The lane's Edit of its own report (each changed field, value for value), put to the
                        write gate, made, the watch run on it as on the Edit, and the lane's next stop."""
                        with open(own_path) as fh:
                            before = fh.read()
                        doc = json.loads(before)
                        for dotted, value in change.items():
                            schemagen.set_path(doc, dotted, value)
                        after = json.dumps(doc, indent=1)
                        old, new = (before, after) if change else ("{", "{")
                        edit = {"file_path": own_path, "old_string": old, "new_string": new}
                        verdict = _answer(hooks.write_gate(store.payload("Edit", edit, me)))
                        if verdict != "permitted":
                            return verdict
                        with open(own_path, "w") as fh:
                            fh.write(after)
                        hooks.run("posttool-lane-completeness-watch.py", {**store.payload("Edit", edit, me),
                                  "hook_event_name": "PostToolUse", "tool_response": {"filePath": own_path}})
                        again = stop("l2")
                        if again.returncode == 0:
                            return "permitted"
                        with open(own_path, "w") as fh:
                            fh.write(before)
                        return next((ln.strip() for ln in again.stderr.splitlines() if "canonical_missing" in ln
                                     or "dev-report" in ln), again.stderr.strip()[:300])[:400]
                    # Its own means: save the report again (the watch runs the aggregator), or correct a field
                    # of its own report the finding names to agree with the fan-out (the sibling's value).
                    means = {"save its own report again with Edit (the watch runs the aggregator)": edit_own({})}
                    with open(os.path.join(project, paths["l1"])) as fh:
                        theirs = json.load(fh)
                    finding = own.stderr.partition("canonical_missing")[2]  # the finding's own text
                    named = [f for f in _free_text(schema) if re.search(rf"\b{f.rpartition('.')[2]}\b", finding)]
                    for f in named if not any(v == "permitted" for v in means.values()) else ():
                        means[f"Edit its own {f} to agree with the fan-out"] = edit_own(
                            {f: schemagen.get_path(theirs, f)})
                    sib = {"file_path": os.path.join(project, paths["l1"]), "old_string": "{", "new_string": "{"}
                    means["Edit the sibling lane's report"] = _answer(hooks.write_gate(store.payload("Edit", sib, me)))
                    cells.append(Cell(row, "wait", "home", f"{t.role} lane l2", means, state))
                for lane in lanes:
                    with contextlib.suppress(OSError):
                        os.unlink(os.path.join(project, paths[lane]))
                for left in Path(project, "docs", "dev").glob(f"dev-report-{tid}*.json"):
                    left.unlink()
    return cells
