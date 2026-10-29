"""Compliant subagents: play one dispatched subagent from the prompt the orchestrator sent it.

A pipeline driver renders a dispatch prompt from the tree under test (its
obligation block, FIRST ACTION and SECOND ACTION lines, input paths) and hands
it to Player, which does what a compliant subagent of that dispatch does, in
the CLI's order, through the framework's tool helpers (so every hook sees every
call):

1. its FIRST ACTION (the registry Read, or the create-if-absent the line allows)
   and its SECOND ACTION Read when the prompt carries one;
2. Reads of the input files the prompt names ("<label>: <path>" lines, output
   instructions such as "Write your report to:" left out);
3. the commands the prompt tells it to run ("Run: <command>" lines) and the
   calls of its agent file the driver names by section (Act.text_calls: the
   section's blocks, placeholders bound, the driver's respellings applied);
4. its own work (Act.work, see roles.py: the edits its role makes, for example
   dev's code change or test-writer's skeletons, with the role's own commands from
   its agent file), which may return content for its artifacts;
5. one Write per artifact its obligation declares, generated from the schema the
   obligation names (schemagen) with the identity the obligation declares, the
   identity fields the role's agent text names for every artifact JSON, the
   values the prompt passes for schema fields (`name: value` lines) and the score
   header's INJECTION_PROOF fields; markdown artifacts from the agent file's
   template for that path, carrying the identity anchor; or, instead of all of
   them, the producer question artifact its agent text names (Act.question). An
   artifact that already exists (a re-dispatch) is Read and edited in place, as
   the harness refuses a wholesale Write over an existing file;
6. its final message: the literal lines the prompt asks for, a JSON status object,
   and the response block or response line the obligation declares.

Act parameterises the outcome: a verdict for the terminal field of every
artifact whose schema has one (obligation.TERMINAL_VOCABULARY of the tree under
test, else the schema's enum), a producer question, extra content per schema id
or path glob, and faults (missing, schema-invalid, stale artifact) for P1c.

Nothing here names an artifact, a role or a hook: artifacts come from the
obligation, schemas from schemas/, templates and identity fields from the role's
agent file, all of the tree under test, read at run time.
"""
from __future__ import annotations

import fnmatch
import importlib.util
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field

from . import cmdtext, schemagen

_OBLIGATION_RE = re.compile(r'<obligation\s+v="1"\s*>\s*(\{.*?\})\s*</obligation>', re.S)
_FIRST_RE = re.compile(r"FIRST ACTION:\s*Read\s+(\S+?)[.,;]?(?:\s|$)(.*)")
_SECOND_RE = re.compile(r"SECOND ACTION[^:]*:\s*Read\s+(\S+?)[.,;]?(?:\s|$)")
_CREATE_RE = re.compile(r"or create if absent with (\{.*?\})\)")
_INPUT_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 _()./-]*?):\s+([A-Za-z0-9_.$/{}-][^\s,;]*\.(?:json|md|py|txt))\b")
_LITERAL_RE = re.compile(r"literal line `([^`]+)`")
_RUN_RE = re.compile(r"^\s*Run:\s*(\S.*)$", re.M)
_REGISTRY_RE = re.compile(r"\.claude/dev-registry/[^/\s]+/([A-Za-z0-9_-]+)\.json")


class PlayError(RuntimeError):
    """The player cannot act compliantly on this prompt (a driver or text change to look at)."""


def peek(rp, role: str, path: str) -> str:
    """Content of a file `role` has already Read through a tool call, read again by the driver
    process on its behalf (attributed to `role` in the trace, not to the CLI)."""
    with rp.acting(role):
        with open(path, encoding="utf-8") as fh:
            return fh.read()


def edit_span(old: str, new: str) -> tuple[str, str]:
    """The smallest whole-line span of `old` that is unique in it and, replaced, gives `new`."""
    if old == new:
        raise PlayError("an update that changes nothing")
    p = 0
    while p < min(len(old), len(new)) and old[p] == new[p]:
        p += 1
    s = 0
    while s < min(len(old), len(new)) - p and old[-1 - s] == new[-1 - s]:
        s += 1
    start = old.rfind("\n", 0, p) + 1
    end = old.find("\n", len(old) - s)
    end = len(old) if end < 0 else end
    while True:
        chunk = old[start:end]
        if chunk and old.count(chunk) == 1:
            break
        if start == 0 and end == len(old):
            break
        start = old.rfind("\n", 0, max(start - 1, 0)) + 1 if start > 0 else 0
        nxt = old.find("\n", end + 1)
        end = len(old) if nxt < 0 or end >= len(old) else nxt
    tail = len(old) - end
    return old[start:end], new[start:len(new) - tail]


def put(sub, path: str, text: str, label: str):
    """Write a file the subagent creates; a file that exists is Read, then edited in place (the
    harness refuses a wholesale Write over an existing file)."""
    if not os.path.exists(path):
        return sub.write(path, text, label=f"{label}")
    sub.read(path, label=f"{label} (Read before edit)")
    old = peek(sub.rp, sub.role, path)
    if old == text:
        return None
    a, b = edit_span(old, text)
    return sub.edit(path, a, b, label=f"{label} (Edit)")


def obligation_of(prompt: str) -> dict | None:
    m = _OBLIGATION_RE.search(prompt or "")
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError as e:
        raise PlayError(f"obligation block is not JSON: {e}")


def registry_role(prompt: str) -> str | None:
    """The agent whose dev-registry sentinel the FIRST ACTION line reads (the dispatched role)."""
    m = _FIRST_RE.search(prompt or "")
    r = _REGISTRY_RE.search(m.group(1)) if m else None
    return r.group(1) if r else None


def expand(path: str, project: str) -> str:
    path = re.sub(r"\$\{?CLAUDE_PROJECT_DIR\}?", project, path.strip("`'\""))
    return path if os.path.isabs(path) else os.path.join(project, path)


@dataclass
class Brief:
    """What the dispatch prompt tells the subagent."""
    prompt: str
    project: str
    obligation: dict | None
    first: str | None
    first_create: dict | None
    second: str | None
    inputs: list
    literal_lines: list
    role: str | None
    runs: list = field(default_factory=list)

    @property
    def task_id(self):
        return (self.obligation or {}).get("task_id")


def brief(prompt: str, project: str) -> Brief:
    ob = obligation_of(prompt)
    first = create = second = None
    m = _FIRST_RE.search(prompt)
    if m:
        first = expand(m.group(1), project)
        c = _CREATE_RE.search(m.group(2))
        if c:
            # The line's own object literal: {agent_type:'x', session_id:'y'} (unquoted keys).
            body = re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', c.group(1)).replace("'", '"')
            try:
                create = json.loads(body)
            except ValueError:
                create = None
    m = _SECOND_RE.search(prompt)
    if m:
        second = expand(m.group(1), project)
    inputs, seen = [], set()
    for line in prompt.split("\n"):
        im = _INPUT_RE.match(line)
        if not im or im.group(1).lower().startswith("write"):  # an output instruction, not an input
            continue
        path = expand(im.group(2), project)
        if path not in seen and path != first:
            seen.add(path)
            inputs.append((im.group(1).strip(), path))
    role = (ob or {}).get("role") or registry_role(prompt)
    return Brief(prompt, project, ob, first, create, second, inputs, _LITERAL_RE.findall(prompt), role,
                 [r.strip() for r in _RUN_RE.findall(prompt)])


# ---------------------------------------------------------------- the tree's declarations

class Tree:
    """Declarations of the tree under test the player reads (cached; read as the driver)."""

    def __init__(self, rp):
        self.rp = rp
        self.harness = rp.layout.harness
        self._schemas: dict = {}
        self._agent: dict = {}
        self._terminal = None

    def schema(self, sid: str) -> dict:
        if sid not in self._schemas:
            with self.rp.acting("driver"):
                self._schemas[sid] = schemagen.load(self.harness, sid)
        return self._schemas[sid]

    def agent_text(self, role: str) -> str:
        if role not in self._agent:
            path = os.path.join(self.harness, "agents", role + ".md")
            with self.rp.acting("driver"):
                try:
                    with open(path, encoding="utf-8") as fh:
                        self._agent[role] = fh.read()
                except OSError:
                    self._agent[role] = ""
        return self._agent[role]

    def terminal_vocabulary(self) -> dict:
        """obligation.TERMINAL_VOCABULARY of the tree (schema id -> dotted path -> legal values)."""
        if self._terminal is None:
            lib = os.path.join(self.harness, "hooks", "lib")
            self._terminal = {}
            with self.rp.acting("driver"):
                spec = importlib.util.spec_from_file_location("replay_tree_obligation", os.path.join(lib, "obligation.py"))
                if spec and spec.loader:
                    sys.path.insert(0, lib)
                    try:
                        mod = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(mod)
                        self._terminal = {k: {p: set(v) for p, v in d.items()}
                                          for k, d in getattr(mod, "TERMINAL_VOCABULARY", {}).items()}
                    except Exception:
                        self._terminal = {}
                    finally:
                        sys.path.remove(lib)
        return self._terminal

    def prefixed_forms(self, role: str) -> set[str]:
        """The id prefixes the role's Task-ID convention forbids in new artifacts (`dev-`, ...)."""
        m = re.search(r"No prefixed forms \(([^)]*)\)", self.agent_text(role))
        return set(re.findall(r"`([^`]+)`", m.group(1))) if m else set()

    def identity_fields(self, role: str) -> list[str]:
        """Fields the role's agent text says every artifact JSON carries the task id in."""
        return sorted(set(re.findall(r"`(\w+)` field of every artifact JSON", self.agent_text(role))))

    def template(self, role: str, rel_path: str) -> str | None:
        """The agent file's template for an artifact path: the blocks under the heading naming that path."""
        text = self.agent_text(role)
        if not text:
            return None
        for line in text.split("\n"):
            h = re.match(r"^#{2,6}\s+(.*)$", line)
            if not h:
                continue
            for span in re.findall(r"`([^`]+)`", h.group(1)):
                rx = "^" + re.sub(r"<[^<>]+>", ".+", re.escape(span).replace(r"\<", "<").replace(r"\>", ">")) + "$"
                if "/" in span and re.match(rx, rel_path):
                    try:
                        bl = cmdtext.blocks(text, h.group(1))
                    except cmdtext.TextNotFound:
                        continue
                    if bl:
                        return "\n".join(b.text for b in bl)
        return None

    def section_commands(self, role: str, heading: str, binds: dict) -> list[str]:
        """The fenced blocks under `heading` of the role's agent file, placeholders filled from
        `binds`; [] when the file has no such section (the text no longer asks for the call)."""
        try:
            blocks = cmdtext.blocks(self.agent_text(role), heading)
        except cmdtext.TextNotFound:
            return []
        out = []
        for b in blocks:
            text = cmdtext.fill(b.text, binds)
            left = cmdtext.placeholders(text)
            if left:
                raise PlayError(f"agents/{role}.md {heading!r}: unbound placeholders {left}")
            out.append(text)
        return out

    def question_path(self, role: str, schema_id: str, task_id: str) -> str:
        """The question artifact path the role's agent text gives in the paragraph naming the schema file."""
        text = self.agent_text(role)
        for para in re.split(r"\n\s*\n", text):
            if f"schemas/{schema_id}.json" not in para:
                continue
            for span in re.findall(r"`([^`]+\.json)`", para):
                if not span.startswith("schemas/"):
                    return re.sub(r"<task[_-]id>|<timestamp>", task_id, span)
        raise PlayError(f"agents/{role}.md names no artifact path beside schemas/{schema_id}.json")


# ---------------------------------------------------------------- the subagent's decisions

@dataclass
class Act:
    """What the simulated subagent decides on one dispatch."""
    verdict: str | None = None              # terminal value for every artifact whose schema has a terminal field
    question: dict | None = None            # {"schema", "need", "options", "default", "why"}: ask instead
    content: dict = field(default_factory=dict)   # schema id or path glob -> content merged into that artifact
    work: object = None                     # work(sub, brief, player) -> {schema id or glob: content}
    calls: list = field(default_factory=list)     # [(label, command)] Bash calls, already bound
    text_calls: list = field(default_factory=list)  # [(heading, {placeholder: value})]: run the blocks of that
                                                    # section of the role's agent file, task id bound
    respell: object = None                  # respell(command, label) -> command (the driver's row 7 respellings)
    faults: dict = field(default_factory=dict)    # path glob -> "missing" | "invalid" | "stale"
    status: str | None = None               # the status word of the final message
    summary: str = ""
    notes: str = ""                         # text appended to every markdown artifact (an update's own section)
    terminal: dict = field(default_factory=dict)  # path glob, or "response_line" -> the terminal line the role's
                                                  # outcome takes (checked against the declared regex), in place
                                                  # of one sampled from it
    final_line: str = ""                    # the line the role's agent text says its response ends with
    produced: list = field(default_factory=list)  # path globs of declared artifacts the role's work writes itself


class Player:
    def __init__(self, tree: Tree, prompt: str, act: Act | None = None, role: str | None = None):
        self.tree, self.act = tree, act or Act()
        self.b = brief(prompt, tree.rp.layout.project)
        self.role = role or self.b.role
        self.written: list[str] = []
        self.unchanged: list[str] = []
        self.question_written: str | None = None

    # ------------------------------------------------------------ helpers
    def rel(self, path: str) -> str:
        p = self.b.project
        return path[len(p) + 1:] if path.startswith(p + "/") else path

    def _match(self, mapping: dict, key_schema: str | None, rel: str):
        out = {}
        for k, v in mapping.items():
            if k == key_schema or fnmatch.fnmatchcase(rel, k):
                out = schemagen.deep_merge(out, v)
        return out

    # ------------------------------------------------------------ the run
    def body(self, sub) -> None:
        b, label = self.b, sub.role
        if b.first:
            if b.first_create is not None and not os.path.exists(b.first):
                sub.write(b.first, json.dumps(b.first_create) + "\n", label=f"{label} FIRST ACTION Write")
            else:
                sub.read(b.first, label=f"{label} FIRST ACTION Read")
        if b.second and os.path.exists(b.second):
            sub.read(b.second, label=f"{label} SECOND ACTION Read")
        for _name, path in b.inputs:
            if os.path.isfile(path):
                sub.read(path, label=f"{label} Read {self.rel(path)}")
        for k, command in enumerate(b.runs, 1):  # "Run: <command>" lines of the prompt
            sub.bash(command, f"Run the command the dispatch names ({k})", label=f"{label} Bash Run {k}")
        for clabel, command in self.act.calls:
            sub.bash(command, clabel, label=f"{label} Bash {clabel}")
        for heading, binds in self.act.text_calls:
            for k, cmd in enumerate(self.tree.section_commands(self.role, heading, dict(binds, **self._id_binds())), 1):
                clabel = f"{label} Bash {heading}" + (f" #{k}" if k > 1 else "")
                if self.act.respell:
                    cmd = self.act.respell(cmd, clabel)
                sub.bash(cmd, heading, label=clabel)
        extra = self.act.work(sub, b, self) if self.act.work else None
        if self.act.question:
            self._write_question(sub)
            return
        for art in (b.obligation or {}).get("artifacts") or []:
            if art.get("kind") in ("json", "markdown"):
                self._write_artifact(sub, art, extra or {})

    def _id_binds(self) -> dict:
        tid = self.b.task_id or ""
        return {"<task_id>": tid, "<task-id>": tid}

    def _write_question(self, sub) -> None:
        q = dict(self.act.question)
        sid = q.pop("schema")
        tid = self.b.task_id
        rel = self.tree.question_path(self.role, sid, tid)
        doc = schemagen.instance(self.tree.schema(sid), dict(q, task_id=tid, role=self.role))
        errs = schemagen.errors(self.tree.schema(sid), doc)
        if errs:
            raise PlayError(f"question artifact invalid against {sid}: {errs}")
        path = os.path.join(self.b.project, rel)
        put(sub, path, json.dumps(doc, indent=2) + "\n", f"{sub.role} Write {rel}")
        self.question_written = rel

    def json_doc(self, art: dict, extra: dict) -> dict:
        sid, rel = art["schema"], art["path"]
        schema = self.tree.schema(sid)
        tid = self.b.task_id
        content = schemagen.deep_merge(self._match(self.act.content, sid, rel), self._match(extra, sid, rel))
        props = schema.get("properties") or {}
        open_ = schema.get("additionalProperties", True) is not False
        for f in self.tree.identity_fields(self.role):
            if f in props or open_:
                content[f] = tid
        content.update(art.get("identity") or {})
        for k, v in self._prompt_fields(props).items():
            content.setdefault(k, v)
        for k in ("lane", "lane_set"):
            if k in props and k in (self.b.obligation or {}):
                content.setdefault(k, self.b.obligation[k])
        jsons = [a for a in (self.b.obligation or {}).get("artifacts") or [] if a.get("kind") == "json"]
        if open_ and jsons and jsons[0] is art:
            content.update(self._injection_echo())
        doc = schemagen.instance(schema, content, seed=rel)
        self._apply_verdict(sid, schema, doc)
        return doc

    def _injection_echo(self) -> dict:
        """The fields an injected score header's INJECTION_PROOF clause asks the primary artifact to
        carry: copied values, the digest recomputed over the header's Recent events text, and an
        action line citing the injected rank."""
        p = self.b.prompt
        i = p.find("INJECTION_PROOF:")
        if i < 0:
            return {}
        out = {}
        for k, v in re.findall(r'^\s*"(\w+)":\s*"(.*)"\s*$', p[i:], re.M):
            out[k] = v
        events = re.search(r"Recent events:[ \t]*(.*)$", p, re.M)
        for k in list(out):
            if "digest" in k and events:
                import hashlib
                out[k] = hashlib.sha256(events.group(1).strip().encode()).hexdigest()[:8]
            elif out[k].startswith("<"):
                rank = next((v for kk, v in out.items() if "rank" in kk), "the injected rank")
                out[k] = f"Rank {rank} noted: kept the change to the one file the requirement names"
        return out

    def _prompt_fields(self, props: dict) -> dict:
        """`name: value` lines of the prompt whose name is a top-level schema property (values the
        orchestrator passed in for the report, for example a baseline it captured)."""
        out = {}
        for m in re.finditer(r"^\s*([a-z][a-z0-9_]*):[ \t]*(.*)$", self.b.prompt, re.M):
            k, v = m.group(1), m.group(2).strip()
            if v.startswith('"'):
                try:
                    v = json.loads(v)
                except ValueError:
                    pass
            if k in props and props[k].get("type") == "string":
                out[k] = v
        return out

    def _apply_verdict(self, sid: str, schema: dict, doc: dict) -> None:
        if not self.act.verdict:
            return
        voc = self.tree.terminal_vocabulary().get(sid)
        paths = [p for p, legal in (voc or {}).items() if self.act.verdict in legal]
        if voc is None:
            paths = schemagen.enum_paths(schema, self.act.verdict)
        for p in paths:
            schemagen.set_path(doc, p, self.act.verdict)

    def markdown(self, art: dict) -> str:
        anchor = art.get("identity_anchor") or self.b.task_id or ""
        tpl = self.tree.template(self.role, art["path"])
        text = tpl if tpl else f"# {os.path.basename(art['path'])}\n"
        # The template's <timestamp> stands for the task id. A prefix the role's Task-ID convention
        # forbids (`dev-<timestamp>`) is not kept: the identity is the task id itself.
        forms = self.tree.prefixed_forms(self.role)
        text = re.sub(r"<task[_-]id>", anchor, text)
        text = re.sub(r"([A-Za-z][\w]*-)?<timestamp>",
                      lambda m: anchor if (m.group(1) or "") in forms or not m.group(1) else m.group(1) + anchor,
                      text)
        if anchor and anchor not in text:
            text = f"Task ID: {anchor}\n\n" + text
        text = text.rstrip("\n") + "\n"
        if self.act.notes:
            text += "\n" + self.act.notes.rstrip("\n") + "\n"
        rx = art.get("terminal_line_regex")
        if rx:
            text += "\n" + self.terminal_line(art["path"], rx, art["path"]) + "\n"
        return text

    def terminal_line(self, key: str, rx: str, seed: str) -> str:
        """The Act's terminal line for `key` (a path, or "response_line"), else one sampled from `rx`."""
        line = next((v for k, v in self.act.terminal.items() if k == key or fnmatch.fnmatchcase(key, k)), None)
        if line is None:
            import random
            return schemagen.sample_pattern(rx, random.Random(seed))
        if not re.search(rx, line):
            raise PlayError(f"terminal line {line!r} for {key} does not match its declared regex {rx!r}")
        return line

    def _write_artifact(self, sub, art: dict, extra: dict) -> None:
        rel = art["path"]
        fault = next((v for k, v in self.act.faults.items() if fnmatch.fnmatchcase(rel, k)), None)
        if fault == "missing":
            return
        if any(fnmatch.fnmatchcase(rel, g) for g in self.act.produced):
            self.written.append(rel)  # the role's own work wrote it (for example through a helper script)
            return
        if art["kind"] == "json":
            doc = self.json_doc(art, extra)
            if fault == "invalid":
                req = (self.tree.schema(art["schema"]).get("required") or [None])[0]
                doc.pop(req, None)
            else:
                errs = schemagen.errors(self.tree.schema(art["schema"]), doc)
                if errs:
                    raise PlayError(f"{rel}: generated content invalid against {art['schema']}: {errs}")
            text = json.dumps(doc, indent=2) + "\n"
        else:
            text = self.markdown(art)
        path = os.path.join(self.b.project, rel)
        if put(sub, path, text, f"{sub.role} Write {rel}") is None:
            self.unchanged.append(rel)  # a re-dispatch that has nothing to change in this artifact
            return
        self.written.append(rel)
        if fault == "stale":
            old = time.time() - 3600
            os.utime(path, (old, old))

    # ------------------------------------------------------------ final message
    def final(self, sub=None) -> str:
        lines = list(self.b.literal_lines)
        tid = self.b.task_id
        if self.question_written:
            obj = {"status": "needs_clarification", "task_id": tid, "question_path": self.question_written}
        else:
            obj = {"status": self.act.status or self.act.verdict or "completed", "task_id": tid,
                   "artifacts": self.written}
            if self.act.summary:
                obj["summary"] = self.act.summary
        lines.append(json.dumps(obj, indent=2))
        tail = None
        for art in (self.b.obligation or {}).get("artifacts") or []:
            if art.get("kind") == "response_block":
                doc = schemagen.instance(self.tree.schema(art["schema"]),
                                         self._match(self.act.content, art["schema"], "<response_block>"))
                self._apply_verdict(art["schema"], self.tree.schema(art["schema"]), doc)
                lines.append(f"{art['begin']}\n{json.dumps(doc, indent=2)}\n{art['end']}")
            elif art.get("kind") == "response_line":
                tail = self.terminal_line("response_line", art["terminal_line_regex"], tid or "")
        if tail:
            lines.append(tail)
        elif self.act.final_line:
            lines.append(self.act.final_line)
        return "\n\n".join(lines)
