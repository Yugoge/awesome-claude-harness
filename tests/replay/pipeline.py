"""Orchestrator helpers shared by the pipeline drivers.

An Orchestrator plays the main agent of one typed command, following the
command file of the tree under test (commands/<name>.md, read at run time):

* slash(): the typed command; the UserPromptSubmit hooks' output is kept, and
  hook_line() reads a value from it by the line the command text names;
* the canonical TodoWrite list: the array the hook's checklist message hands
  the main agent (checked against scripts/todo/<name>.py of the tree), then one
  completion per TodoWrite call (advance());
* run_block(): a fenced Bash block of a step, extracted at run time (cmdtext),
  its `<...>` placeholders bound by the driver's rules, the shell variables it
  reads but does not set bound to the run's values, row 7 respellings applied
  (each recorded), values it sets captured when the step needs them;
* dispatch(): a "Use Task/Agent tool with:" template of a step, its prompt
  rendered (placeholders, the orchestrator's conditional lines, the obligation
  block instantiated from the worked example or from the template's
  "embed ... here with role=..., artifacts=[...]" sentence, dispatched_at the
  current UTC time), and the subagent played by agents.Player;
* ask(): one AskUserQuestion relaying a producer question artifact.

Every call takes the deviations the driver declares for its step label
(Deviations), so a block passes only where the driver's source quotes it.
"""
from __future__ import annotations

import fnmatch
import importlib.util
import json
import os
import re
import shlex
import sys
import time
from dataclasses import dataclass

from . import agents, cmdtext

_VAR_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)")
_ASSIGN_RE = re.compile(r"(?:^[ \t]*|[;&|(][ \t]*|\bthen[ \t]+|\bexport[ \t]+|\blocal[ \t]+)([A-Za-z_][A-Za-z0-9_]*)=", re.M)
_FOR_RE = re.compile(r"\bfor\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\b")
_SHELL_SPECIAL = {"HOME", "PATH", "PWD", "USER", "SHELL", "TMPDIR", "IFS", "RANDOM", "LINENO"}
DROP, DROP_NEXT = object(), object()


@dataclass
class Respelling:
    """A row 7 respelling: `old` (regex) still present in a line is rewritten to `new` (re.sub template)."""
    name: str
    old: str
    new: str
    where: str = ""

    def apply(self, text: str):
        out, n = re.subn(self.old, self.new, text)
        return out, n


class Deviations:
    """The driver's declared deviations: (step-label glob, Deviation) pairs."""

    def __init__(self, pairs=()):
        self.pairs = list(pairs)

    def at(self, label: str) -> list:
        return [d for pat, d in self.pairs if fnmatch.fnmatchcase(label, pat)]


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _matching_bracket(text: str, start: int) -> int:
    depth, i, instr = 0, start, False
    while i < len(text):
        c = text[i]
        if instr:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                instr = False
        elif c == '"':
            instr = True
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise cmdtext.TextNotFound("unbalanced bracket in obligation instruction")


class Orchestrator:
    def __init__(self, rp, command: str, session=None, deviations: Deviations | None = None,
                 respellings=(), rules=(), line_rules=(), profile: str = "singular", typed: str | None = None):
        self.rp, self.command = rp, command
        # The command the owner types (slash, checklist script) when its steps are another command's
        # text: /redev runs commands/dev.md's steps, already in the conversation (commands/redev.md).
        self.typed = typed or command
        self.harness, self.project = rp.layout.harness, rp.layout.project
        self.cmd_path = os.path.join(self.harness, "commands", command + ".md")
        with rp.acting("driver"):
            with open(self.cmd_path, encoding="utf-8") as fh:
                self.text = fh.read()
        self.s = session or rp.session()
        self.devs = deviations or Deviations()
        self.respellings = list(respellings)
        self.rules = list(rules)            # (regex on a placeholder's inner text, value or fn(match))
        self.line_rules = list(line_rules)  # (regex on a prompt line, fn(line) -> line | DROP | DROP_NEXT)
        self.profile = profile
        self.tree = agents.Tree(rp)
        self.values: dict = {}              # shell variables the run has bound (the main agent's memory)
        self.hook_out = ""
        self.todos: list | None = None
        self.dispatches: list = []

    # ------------------------------------------------------------ text
    def section(self, heading: str) -> str:
        return cmdtext.section(self.text, heading)

    def block(self, heading: str, index=None, anchor=None, lang=None) -> str:
        return cmdtext.block(self.text, heading, index=index, anchor=anchor, lang=lang)

    def inline(self, heading: str, anchor: str, startswith: str = "") -> str:
        codes = [c for c in cmdtext.inline_codes(self.text, heading, anchor) if c.startswith(startswith)]
        if not codes:
            raise cmdtext.TextNotFound(f"no inline code starting {startswith!r} in the {heading!r} item with {anchor!r}")
        return codes[0]

    def step_blocks(self, heading: str, lang: str = "bash") -> list:
        """The step's `lang` blocks in order: (name, block, the paragraph before it). The name is the
        first harness script the block runs, else the first variable it sets, else its first command
        word (stable across trees while the block's text is), suffixed when repeated."""
        sec = self.section(heading)
        lines = sec.split("\n")
        out, names = [], {}
        for b in cmdtext.blocks(sec, None, lang):
            body = _strip_comments(b.text)
            m = re.search(r"([\w.-]+\.(?:py|sh))\b", body)
            a = _ASSIGN_RE.search(body)
            w = re.search(r"^\s*([A-Za-z_][\w.-]*)", body, re.M)
            name = m.group(1) if m else a.group(1) if a else w.group(1) if w else "block"
            names[name] = names.get(name, 0) + 1
            if names[name] > 1:
                name = f"{name}#{names[name]}"
            k = b.line - 2
            while k >= 0 and not lines[k].strip():
                k -= 1
            para = []
            while k >= 0 and lines[k].strip() and not lines[k].startswith("```"):
                para.insert(0, lines[k])
                k -= 1
            out.append((name, b, "\n".join(para)))
        return out

    def run_text(self, text: str, label: str, description: str, capture=(), extra_rules=(), timeout=None):
        """Run a block's text: placeholders bound (all must bind), the shell variables it reads bound,
        respellings applied; `capture` keeps the values of the listed variables the block sets."""
        left: list = []
        text = self.bind(text, extra_rules, left)
        left = [p for p in left if p in cmdtext.placeholders(_strip_comments(text))]
        if left:
            raise cmdtext.TextNotFound(f"{label}: unbound placeholders {sorted(set(left))}")
        sets = set(_ASSIGN_RE.findall(text))
        return self.run(self.shell_bind(text), description, label, capture=[v for v in capture if v in sets],
                        timeout=timeout)

    def run_step_blocks(self, step: int, skip=None, capture=(), extra_rules=(), label: str | None = None):
        """Every Bash block of `Step <step>` in order, except those skip(name, block, paragraph) refuses."""
        calls = []
        for name, b, para in self.step_blocks(f"Step {step}"):
            if skip and skip(name, b, para):
                continue
            calls.append(self.run_text(b.text, f"{label or f'Step {step}'} Bash {name}",
                                       f"Step {step}: {name}", capture=capture, extra_rules=extra_rules))
        return calls

    def has(self, heading: str, anchor: str) -> bool:
        try:
            return anchor in self.section(heading)
        except cmdtext.TextNotFound:
            return False

    # ------------------------------------------------------------ the typed command
    def slash(self, args: str, label: str | None = None):
        label = label or f"/{self.typed}"
        ev = self.s.slash(self.typed, args, label=label, deviation=self.devs.at(label))
        self.hook_out = "\n".join(h["stdout"] for h in ev.hooks if h["verdict"] == "ok")
        return ev

    def hook_line(self, line_code: str) -> str:
        """The value after the prefix of `line_code` (a hook output line the command text quotes)."""
        prefix = re.split(r"\s*(?:…|\.\.\.|<[^>]*>)\s*$", line_code.strip())[0]
        m = re.search(r"^[ \t]*" + re.escape(prefix) + r"[ \t]*(\S+)", self.hook_out, re.M)
        if not m:
            raise cmdtext.TextNotFound(f"hook output has no line {prefix!r}")
        return m.group(1)

    # ------------------------------------------------------------ todos
    def canonical_todos(self) -> list:
        """The array the hook's checklist tells the main agent to pass to its first TodoWrite."""
        lines = self.hook_out.split("\n")
        start = next((i for i, l in enumerate(lines) if "TodoWrite" in l and "FIRST ACTION" in l), None)
        if start is None:
            raise cmdtext.TextNotFound("hook output has no checklist FIRST ACTION line")
        arr = next((l for l in lines[start:] if l.lstrip().startswith("[")), None)
        todos = json.loads(arr)
        script = os.path.join(self.harness, "scripts", "todo", self.typed + ".py")
        if os.path.isfile(script):
            with self.rp.acting("driver"):
                spec = importlib.util.spec_from_file_location("replay_todo_" + self.typed.replace("-", "_"), script)
                mod = importlib.util.module_from_spec(spec)
                # A checklist script may import its sibling (scripts/todo/redev.py: `from dev import ...`).
                sys.path.insert(0, os.path.dirname(script))
                try:
                    spec.loader.exec_module(mod)
                finally:
                    sys.path.remove(os.path.dirname(script))
                want = mod.get_todos()
            if [t.get("content") for t in want] != [t.get("content") for t in todos]:
                raise cmdtext.TextNotFound("the hook's checklist differs from scripts/todo/%s.py" % self.typed)
        return todos

    def todo_start(self, label: str = "TodoWrite canonical list") -> None:
        self.todos = self.canonical_todos()
        self._todo(label)

    def _todo(self, label: str):
        return self.s.todo([dict(t) for t in self.todos], label=label, deviation=self.devs.at(label))

    def current(self) -> int | None:
        return next((i for i, t in enumerate(self.todos) if t.get("status") == "in_progress"), None)

    def step_name(self, i: int) -> str:
        m = re.match(r"(Step \d+)", self.todos[i]["content"])
        return m.group(1) if m else self.todos[i]["content"]

    def advance(self, label: str | None = None):
        """Complete the in_progress step and start the next one: one completion per TodoWrite call."""
        i = self.current()
        self.todos[i]["status"] = "completed"
        if i + 1 < len(self.todos):
            self.todos[i + 1]["status"] = "in_progress"
            label = label or f"TodoWrite {self.step_name(i)} done, {self.step_name(i + 1)} in_progress"
        else:
            label = label or f"TodoWrite {self.step_name(i)} done"
        return self._todo(label)

    def at_step(self, n: int) -> bool:
        i = self.current()
        return i is not None and self.step_name(i) == f"Step {n}"

    # ------------------------------------------------------------ binding
    def bind(self, text: str, extra_rules=(), unbound: list | None = None) -> str:
        """Fill the text's `<...>` placeholders by the first matching rule; the ones no rule
        matches are left as they are and listed in `unbound` (a value filled in is not rescanned)."""
        rules = list(extra_rules) + self.rules

        def sub(m):
            inner = m.group(0)[1:-1]
            for rx, val in rules:
                mm = re.search(rx, inner)
                if mm:
                    v = val(mm) if callable(val) else val
                    return str(v)
            if unbound is not None:
                unbound.append(m.group(0))
            return m.group(0)
        return cmdtext._PLACEHOLDER_RE.sub(sub, text)

    def shell_bind(self, text: str) -> str:
        """Assignments for the variables the block reads but does not set (each Bash call is a new shell)."""
        used = list(dict.fromkeys(_VAR_RE.findall(text)))
        assigned = set(_ASSIGN_RE.findall(text)) | set(_FOR_RE.findall(text))
        lines = [f"{v}={shlex.quote(str(self.values[v]))}" for v in used
                 if v in self.values and v not in assigned and v not in _SHELL_SPECIAL]
        return "\n".join(lines + [text]) if lines else text

    def respell(self, text: str, label: str) -> str:
        for r in self.respellings:
            new, n = r.apply(text)
            if n:
                self.rp.respellings.append({"step": label, "name": r.name, "where": r.where, "count": n})
                text = new
        return text

    # ------------------------------------------------------------ Bash
    def run(self, command: str, description: str, label: str, capture=(), timeout=None, actor=None):
        command = self.respell(command, label)
        if capture:
            command = command.rstrip("\n") + "\ndeclare -p " + " ".join(capture) + " 2>/dev/null\n"
        call = (actor or self.s.main).bash(command, description, label=label, deviation=self.devs.at(label),
                                           timeout=timeout)
        if capture and call.ok:
            self.values.update(parse_declare(call.response.get("stdout", "")))
        return call

    def run_block(self, heading: str, label: str, description: str = "", index=None, anchor=None,
                  lang=None, capture=(), extra_rules=(), timeout=None):
        text = self.block(heading, index=index, anchor=anchor, lang=lang)
        left: list = []
        text = self.bind(text, extra_rules, left)
        left = [p for p in left if p in cmdtext.placeholders(_strip_comments(text))]
        if left:
            raise cmdtext.TextNotFound(f"{label}: unbound placeholders {sorted(set(left))}")
        text = self.shell_bind(text)
        return self.run(text, description or f"{heading}: run the step's block", label, capture=capture,
                        timeout=timeout)

    # ------------------------------------------------------------ dispatch
    def template(self, heading: str, index=None, anchor=None) -> dict:
        return cmdtext.dispatch(self.text, heading, index=index, anchor=anchor)

    def instantiate(self, prompt: str, task_id: str, lane=None, lane_set=None) -> str:
        """The obligation block of a template, instantiated for this dispatch."""
        now = utc_now()
        lit = re.search(r'<obligation\s+v="1"\s*>\s*\{(?!\.\.\.\}).*?</obligation>', prompt, re.S)
        if lit and "embed `<obligation" not in prompt:
            body = self.bind(lit.group(0), [(r"ISO-8601", now), (r"lane-suffix", lane or "")])
            m = re.search(r"\{.*\}", body, re.S)
            ob = json.loads(m.group(0))
            if lane is not None:  # a fan-out lane dispatch: the lane values the template's adapter line names
                ob["lane"], ob["lane_set"], ob["profile"] = lane, lane_set, self.profile
            ob["dispatched_at"] = now
            return prompt[:lit.start()] + self._block(ob) + prompt[lit.end():]
        lines = prompt.split("\n")
        for i, line in enumerate(lines):
            m = re.search(r"embed `<obligation v=\"1\">\{\.\.\.\}</obligation>` here with (.*)$", line)
            if not m:
                continue
            spec = m.group(1)
            a = spec.index("artifacts=")
            j = spec.index("[", a)
            artifacts = json.loads(self.bind(spec[j:_matching_bracket(spec, j) + 1]))
            head = spec[:a]
            fields = {}
            for k, alts in re.findall(r'(\w+)=((?:"[^"]*"/?)+)', head):
                vals = re.findall(r'"([^"]*)"', alts)
                fields[k] = self.profile if k == "profile" and self.profile in vals else vals[0]
            ob = {"task_id": task_id, "lane": lane, "lane_set": lane_set}
            for k in ("role", "pipeline", "profile"):
                if k not in fields:
                    raise cmdtext.TextNotFound(f"obligation instruction lacks {k}=: {line[:120]}")
                ob[k] = fields[k]
            ob["dispatched_at"] = now
            ob["artifacts"] = artifacts
            lines[i] = line[:line.index("embed `<obligation")] + "\n" + self._block(ob)
            return "\n".join(lines)
        return prompt

    @staticmethod
    def _block(ob: dict) -> str:
        return '<obligation v="1">\n' + json.dumps(ob, indent=2) + "\n</obligation>"

    def render(self, fields: dict, task_id: str, extra_rules=(), extra_line_rules=(), lane=None,
               lane_set=None) -> str:
        out, drop_next = [], False
        for line in fields.get("prompt", "").split("\n"):
            if drop_next:
                drop_next = False
                continue
            res = line
            for rx, fn in list(extra_line_rules) + self.line_rules:
                if re.search(rx, line):
                    res = fn(line)
                    break
            if res is DROP_NEXT:
                drop_next = True
                continue
            if res is DROP:
                continue
            out.append(res)
        prompt = "\n".join(out)
        prompt = self.instantiate(prompt, task_id, lane, lane_set)
        left: list = []
        prompt = self.bind(prompt, extra_rules, left)
        if left:
            raise cmdtext.TextNotFound(f"dispatch prompt: unbound placeholders {sorted(set(left))}")
        return prompt

    def dispatch(self, fields: dict, act: agents.Act, label: str, task_id: str, subagent_type=None,
                 extra_rules=(), extra_line_rules=(), actor=None, lane=None, lane_set=None):
        prompt = self.render(fields, task_id, extra_rules, extra_line_rules, lane, lane_set)
        atype = subagent_type or fields.get("subagent_type") or agents.registry_role(prompt)
        if not atype:
            raise cmdtext.TextNotFound(f"{label}: no subagent_type in the template or its FIRST ACTION line")
        description = self.bind(fields.get("description", "") or atype, extra_rules)
        player = agents.Player(self.tree, prompt, act, role=atype)
        d = (actor or self.s.main).dispatch(atype, prompt, description=description, body=player.body,
                                            result=player.final, label=label, deviation=self.devs.at(label))
        d.player = player
        self.dispatches.append(d)
        return d

    # ------------------------------------------------------------ owner questions
    def ask(self, rel_path: str, label: str):
        """Relay a producer question artifact with ONE AskUserQuestion; returns (question doc, answer label)."""
        path = os.path.join(self.project, rel_path)
        self.s.read(path, label=f"{label} Read question", deviation=self.devs.at(f"{label} Read question"))
        q = json.loads(agents.peek(self.rp, "main", path))
        options = [{"label": o["label"] + (" (Recommended)" if o["label"] == q.get("default") else ""),
                    "description": o.get("description", "")} for o in q.get("options", [])]
        tin = {"questions": [{"question": q.get("need", ""), "header": (q.get("role") or "producer")[:12],
                              "options": options, "multiSelect": False}]}
        call = self.s.tool("AskUserQuestion", tin, label=label, deviation=self.devs.at(label))
        ans = (call.response.get("answers") or {}).get(q.get("need", ""), q.get("default", ""))
        return q, ans.replace(" (Recommended)", "")


def _strip_comments(script: str) -> str:
    """The script without its `#` comments (a placeholder in a comment is not one the shell sees)."""
    return "\n".join(re.sub(r"(^|\s)#(?![!{]).*$", r"\1", line) for line in script.split("\n"))


def parse_declare(stdout: str) -> dict:
    """Values from `declare -p` output (declare -- NAME="value", value may span lines)."""
    out = {}
    for m in re.finditer(r'^declare -[-a-zA-Z]* ([A-Za-z_]\w*)="((?:[^"\\]|\\.)*)"', stdout, re.M | re.S):
        out[m.group(1)] = re.sub(r'\\(.)', r'\1', m.group(2))
    for m in re.finditer(r"^declare -[-a-zA-Z]* ([A-Za-z_]\w*)=\$'((?:[^'\\]|\\.)*)'", stdout, re.M):
        out[m.group(1)] = m.group(2).encode().decode("unicode_escape")
    # An indexed array (declare -a NAME=([0]="v" [1]=$'v')): its elements, in index order, as a list.
    for m in re.finditer(r"^declare -[-a-zA-Z]*a[-a-zA-Z]* ([A-Za-z_]\w*)=\((.*?)\)$", stdout, re.M | re.S):
        items = {}
        for e in re.finditer(r"\[(\d+)\]=(?:\"((?:[^\"\\]|\\.)*)\"|\$'((?:[^'\\]|\\.)*)')", m.group(2), re.S):
            items[int(e.group(1))] = (re.sub(r'\\(.)', r'\1', e.group(2)) if e.group(2) is not None
                                      else e.group(3).encode().decode("unicode_escape"))
        out[m.group(1)] = [items[k] for k in sorted(items)]
    return out
