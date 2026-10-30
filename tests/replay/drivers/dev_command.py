"""/dev-command, a singular cycle, played compliantly from commands/dev-command.md of the tree under test.

The main agent types `/dev-command <requirement>`: a new project slash command, the kind of
development the command's text lists first among its Agent Development Use Cases ("Slash
Commands (`.claude/commands/`)", agents/dev.md "Slash Commands (`.claude/commands/xxx.md`)").
It reads the ids the item "Read `DEV_SESSION_ID` [and `TASK_ID`] from the hook output above"
names from the hook lines the step quotes, passes the hook's checklist (checked against
scripts/todo/dev-command.py) to its first TodoWrite, then completes one step per TodoWrite call.
Each step does what the tree's text says, read at run time:

* Step 1: the spec as the tree decides it (the hook's `Spec:` line where the text says the hook
  decided it; else the text's own auto-detect, a Glob of the pattern it names, newest first; a
  `--spec` is never passed), the Read of the command-development patterns document the text
  says to read before authoring a slash command, and every Bash block of the step but the
  fallback the text keeps for a missing hook output;
* Step 2: the graphify hydrator block of commands/dev.md the step points to;
* Step 3: the four specialists assessed (all SKIP, each with a reason), no dispatch;
* Step 4: the pre-BA retry signals (the text's `git log --grep` and the ticket Glob), then BA
  from the step's template (its literal obligation instantiated);
* Steps 6, 11 and 13: the Reads of the files the step names;
* Steps 7 and 12: the step's Bash blocks (the base's qa_mode flips), then QA from the template;
* Step 9: graphify from commands/dev.md's enrichment template (the step mirrors it), and the run
  record's status read where the step says the `Graph context file:` line follows it;
* Step 10: dev from the template, writing the command file (Write, as the agent text allows);
* Step 14: the step's Bash blocks (the base's per-permission jq edit only once per validated
  permission: none here);
* Step 15 (variant qa-fail): the step's Bash blocks (the base's refined context), then dev again
  from Step 10's template with the context file or the added line the step names, Steps 11-14
  again with a passing QA;
* Step 16: the completion report from the step's template (its `**Request ID**: dev-<timestamp>`
  and its Files Generated list as written), the resolver block, whose exit and status decide whether
  the summary calls the cycle complete, and the `/spec-update --temp` note where the step still
  asks for one; the summary; Stop.

Subagents are played by agents.Player (role work from roles.py): everything they write comes
from their obligation, the schemas and their agent files.

Driver arguments (cli.py --arg K=V):
  variant=plain     BA ready, BA-QA pass, dev writes the command, QA pass (default)
  variant=qa-fail   the first final-verification QA fails (the command runs the whole tree,
                    not `-q tests/`); Step 15 iterates: dev edits the command, the next QA passes

Respellings (P1b Scope row 7), applied by the driver only and only where the text still has the
old form; each application is recorded in blocks.json "respellings":
  R1 resolver      `python3 scripts/resolve-dev-artifact-chain.py` -> `python3 ~/.claude/scripts/...`
                   (Step 16, dev-command.md:889 at 2acc29b): a product repository has no scripts/.
  R2 qa_mode flip  `bash ~/.claude/scripts/write-qa-mode.sh` gains
                   `CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"` as a
                   prefix (Steps 7 and 12, dev-command.md:437, :627 at 2acc29b): the CLI's Bash does not
                   export the variable and write-qa-mode.sh:35 exits without it (E5).
Not respelled (row 7): BA's and QA's blast-radius tool calls (ba.md Step 9, qa.md Phase 6) run as
written and fail; the replay goes on.

Deviations: DEVIATIONS below, one entry per block the base tree's (2acc29b) replay meets, each with
a comment quoting the hook's text; nothing else passes a block. On another tree an entry whose
block no longer occurs is a no-op. The subagents' own calls reach them through rp.deviation_at.
"""
from __future__ import annotations

import json
import os
import re

from .. import agents, cmdtext, roles
from ..pipeline import DROP, DROP_NEXT, Deviations, Orchestrator, Respelling, utc_now
from ..replay import Deviation
from .dev import with_lines

PIPELINE = "dev-command"
# The artifact check's cost of each variant (tests/artifact_graph/shards.py balances its CI shards by it):
# CPU seconds of the shipped and armed traced replays and their differential runs, measured at b8e34f4
COST = {"plain": 187, "qa-fail": 236}
COMMAND = "dev-command"

CMD_REL = ".claude/commands/test.md"
REQUIREMENT = ("add a project slash command named test (.claude/commands/test.md) that runs the toy "
               "package tests with python3 -m pytest -q tests/ and reports the result")
KEYWORD = "test"  # the retry-signal keyword the orchestrator takes from the request

PROJECT_ROOT_PREFIX = 'CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}" '
RESPELLINGS = [
    Respelling("R1 resolver", r"(?<![\w/~.-])python3 scripts/resolve-dev-artifact-chain\.py",
               "python3 ~/.claude/scripts/resolve-dev-artifact-chain.py", "commands/dev-command.md Step 16"),
    Respelling("R2 qa_mode flip", r"(?<!\" )(?<![\w=])bash ~/\.claude/scripts/write-qa-mode\.sh",
               PROJECT_ROOT_PREFIX + "bash ~/.claude/scripts/write-qa-mode.sh",
               "commands/dev-command.md Steps 7, 12"),
]

# Blocks the base tree's replay meets, each passed by a deviation at the step it occurs on: the
# refused call is applied as if allowed, so every later step runs and is traced.
DEVIATIONS = Deviations([
    # DEVIATION: "BLOCKED: removal-policy — UNRESOLVED census_fatal:unbalanced:single_quote"
    # pretool-bash-safety.sh refuses Step 1's cp-state block (the apostrophe in its comment "resolver's").
    ("Step 1 Bash SPEC_ID", Deviation(
        "hooks/pretool-bash-safety.sh", "UNRESOLVED census_fatal:unbalanced:single_quote",
        "Step 1's cp-state block as the text spells it")),
    # DEVIATION: "[Write Guard] BLOCKED: File already exists: /var/tmp/claude-scratch/update-<rand>.md"
    # /spec-update --temp (which Step 16 runs) creates the note with mktemp, reads it, then writes it.
    ("Step 16 Write update note", Deviation(
        "hooks/pretool-write-guard.sh", "[Write Guard] BLOCKED: File already exists",
        "the temp note mktemp created, written as /spec-update --temp says")),
    # DEVIATION: "BLOCKED: claude config guard: agent Write to .claude/commands/ is forbidden outside an
    # explicit refactor session." pretool-claude-config-guard.py refuses dev's Write (and, on the
    # qa-fail iteration, its Edit) of the command file the request asks for, which the command's text
    # lists as its first development type; the guard's sentinel is one "the user creates by hand".
    ("agent:dev * .claude/commands/*", Deviation(
        "hooks/pretool-claude-config-guard.py", "BLOCKED: claude config guard",
        "dev writes the command file the request asks for")),
])

# ---------------------------------------------------------------- the scenario

CMD_PARTIAL = ("---\ndescription: Run the toy package tests and report the result\n---\n\n"
               "Run the project's tests from the repository root and report the summary line:\n\n"
               "```bash\npython3 -m pytest\n```\n")
CMD_FINAL = CMD_PARTIAL.replace("python3 -m pytest\n", "python3 -m pytest -q tests/\n")
AC = {"id": "AC-01", "type": "data", "given": "the toy project", "when": "the test command file is read",
      "then": "its body runs python3 -m pytest -q tests/ from the repository root",
      "check": {"file": CMD_REL, "contains": "python3 -m pytest -q tests/"}}
LAYER = "L5"  # infrastructure: developer tooling (the text's layer vocabulary)
QA_FAILURE = {"severity": "critical", "primary_cause": "dev_implementation",
              "description": "the command runs python3 -m pytest over the whole tree, not -q tests/ (AC-01)"}


def _ba_content(tid: str) -> dict:
    return {"context.v1": {
        "requirement": {"original": REQUIREMENT, "clarified": REQUIREMENT, "what": "a project slash command named test",
                        "why": "running the tests takes a typed shell command each time",
                        "where": [CMD_REL], "success_criteria": [AC["then"]]},
        "root_cause_analysis": {"symptom": "the project has no test command",
                                "root_cause": f"no {CMD_REL} exists", "affected_files": [CMD_REL],
                                "complaint_location_keywords": ["test command"], "located_source": [".claude/commands/"]},
        "development_approach": {"summary": f"create {CMD_REL} with a description and the pytest call",
                                 "files_to_create": [CMD_REL], "files_to_modify": []},
        "waves": [{"wave_id": 1, "tasks": [{"task_id": "T1", "title": "create the test command",
                                            "files_to_modify": [CMD_REL]}]}],
        "complexity_tier": "SMALL", "risk_level": "low", "test_writer_expected": False,
        "diagnosis_layer": LAYER, "affected_files": [CMD_REL], "located_source": [".claude/commands/"],
        "complaint_location_keywords": ["test command"],
        "acceptance_criteria": roles.acceptance_criteria([AC]),
        "evidence": {"measured": {"value": "ls .claude/commands/test.md: no such file"},
                     "expected": {"source": "the request"}},
        "scope_expansion": {"all_occurrences": [CMD_REL]},
    }}


# ---------------------------------------------------------------- the cycle

class DevCommandCycle:
    def __init__(self, rp, variant: str):
        self.rp, self.variant = rp, variant
        self.spec_path = self.spec_id = ""
        self.iteration = 0
        self.commits: list = []
        self.specs: list = []
        self.graph_lines: list = []
        self.chain_ok = False
        self.o = Orchestrator(rp, COMMAND, deviations=DEVIATIONS, respellings=RESPELLINGS,
                              rules=self._rules(), line_rules=self._line_rules())
        rp.deviation_at = self.o.devs.at  # the subagents' own calls take the same deviations by label
        # commands/dev.md, which Steps 2 and 9 point to for the canonical block and template.
        self.ref = Orchestrator(rp, "dev", session=self.o.s, deviations=self.o.devs)
        self.tid = self.reg = self.digits = ""

    # ------------------------------------------------------------ binding rules
    def _rules(self):
        return [
            (r"^DEV_SESSION_ID$", lambda m: self.reg),
            (r"^(?:timestamp|task_id|task-id)$", lambda m: self.tid),
            (r"^(?:YYYYMMDD-HHMMSS|same timestamp)$", lambda m: self.digits),
            (r"^(?:requirement from Step 1|original requirement|requirement)$", REQUIREMENT),
            (r"^spec_path or null$", lambda m: self.spec_path or "null"),
            (r"any file paths mentioned by user", CMD_REL),
            (r"^accumulated hints$", CMD_REL),
            (r"^matched phrase or null$", "null"),
            (r"^keyword$", KEYWORD),
            (r"^context_json_path$", lambda m: self.context_rel),
        ]

    def _line_rules(self):
        return [
            (r"^\s*View file: <view_paths", lambda l: l[:l.index("<")] + "null"),
            (r"^\s*SECOND ACTION", lambda l: l if self.spec_id else DROP),
            (r"^\s*<If codex_required = true, include the literal next line", lambda l: DROP_NEXT),
            (r"^\s*recent_commits: \[", lambda l: l[:l.index("[")] + json.dumps(self.commits)),
            (r"^\s*existing_specs: \[", lambda l: l[:l.index("[")] + json.dumps(self.specs)),
        ]

    # ------------------------------------------------------------ helpers
    def to(self, n: int) -> None:
        """Advance the checklist until Step n is in_progress (one completion per TodoWrite)."""
        while not self.o.at_step(n):
            self.o.advance()

    def step_role(self, step: int):
        todo = next(t for t in self.o.todos if re.match(rf"Step {step}\b", t["content"]))
        return (todo.get("subagent_call") or {}).get("subagent_type")

    def text_paths(self, step: int, anchor: str) -> list[str]:
        """The repository paths (inline code) of the item of Step <step> from the line holding `anchor`
        to the next blank line, placeholders bound; legacy names left out."""
        lines = self.o.section(f"Step {step}").split("\n")
        i = next((k for k, l in enumerate(lines) if anchor in l), None)
        if i is None:
            raise cmdtext.TextNotFound(f"Step {step} has no line with {anchor!r}")
        out = []
        for l in lines[i:]:
            if not l.strip() and out:
                break
            l = re.sub(r"\(legacy:[^)]*\)", "", l)
            out.extend(c for c in re.findall(r"`([^`\s]+)`", l) if "/" in c and re.search(r"\.[A-Za-z]+$", c))
        return [self.o.bind(c) for c in out]

    def read(self, rel: str, label: str):
        return self.o.s.read(os.path.join(self.o.project, rel), label=label, deviation=self.o.devs.at(label))

    def load(self, rel: str) -> dict:
        return json.loads(agents.peek(self.rp, "main", os.path.join(self.o.project, rel)))

    @property
    def context_rel(self) -> str:
        return next(p for p in self.ba_outputs if p.endswith(".json"))

    # ------------------------------------------------------------ start and Step 1
    def start(self) -> None:
        o = self.o
        o.slash(REQUIREMENT)
        sec = o.section("Step 1")
        # The names the item tells the main agent to read, and the hook lines the step quotes for them.
        item = next(c for c in re.split(r"\n\s*\n", sec) if re.search(r"Read `[A-Z_]+`.*from the hook output", c))
        names = re.findall(r"`([A-Z_]+)`", item.split("from the hook output")[0])
        lines = [c for c in re.findall(r"`([^`\n]+)`", sec) if c.rstrip().endswith(("…", "...")) and ":" in c]
        got = {}
        for n in names:
            line = next((l for l in lines if re.sub(r"\W+", "_", l.split(":")[0]).lower().startswith(n.lower())), None)
            if line is None:
                raise cmdtext.TextNotFound(f"Step 1 quotes no hook line for {n}")
            got[n] = o.hook_line(line)
        self.reg = got["DEV_SESSION_ID"]
        self.digits = re.sub(r"^[A-Za-z-]*?(?=\d{8}-\d{6})", "", self.reg)
        # The id the artifacts are named with: the hook's task id where the text names one, else the
        # text's `<timestamp>` (the registry name's timestamp: "$DEV_SESSION_ID without its prefix").
        self.tid = got.get("TASK_ID", self.digits)
        for v in {self.reg, self.tid}:
            self.rp.task(v)
        req = re.search(r"User requirement document:\s*(\S+)", o.template("Step 4")["prompt"]).group(1)
        o.values.update(DEV_SESSION_ID=self.reg, TASK_ID=self.tid, REQUIREMENT_DOC=o.bind(req))
        o.todo_start()

    def step1(self) -> None:
        o = self.o
        sec = o.section("Step 1")
        line = re.search(r"`(Spec: <[^`]*>)`", sec)
        if line:  # the text has the hook decide the spec and print it as `Spec: <path>` / `Spec: none`
            v = o.hook_line(line.group(1))
            self.spec_path = "" if v == "none" else v
        elif "Auto-detect spec" in sec:  # the text's own detection: the pattern it names, newest first
            para = next(p for p in re.split(r"\n\s*\n", sec) if "Auto-detect spec" in p)
            pattern = next(c for c in re.findall(r"`([^`\s]+)`", para) if "*" in c)
            g = o.s.tool("Glob", {"pattern": pattern, "path": o.project}, label="Step 1 Glob auto-detect spec",
                         deviation=o.devs.at("Step 1 Glob auto-detect spec"))
            found = g.response.get("filenames", []) if g.ok else []
            found = sorted(found, key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0, reverse=True)
            self.spec_path = os.path.relpath(found[0], o.project) if found else ""
        if self.spec_path:
            o.s.say(f"Spec: {self.spec_path}")
        o.values["spec_path"] = self.spec_path
        # "Read that document before authoring or editing slash commands" (Command Development Best Practices).
        doc = next(c for c in re.findall(r"`([^`\s]+\.md)`", o.section("Command Development Best Practices"))
                   if c.startswith("~/"))
        o.s.read(os.path.join(self.rp.layout.home, doc[2:]), label="Read command-development patterns",
                 deviation=o.devs.at("Read command-development patterns"))
        fallback = re.compile(r"(?i)\*\*fallback\*\*|hook output (?:is )?absent|not in your context")
        o.run_step_blocks(1, skip=lambda name, b, para: bool(fallback.search(para)),
                          capture=("SPEC_ID",))
        self.spec_id = o.values.get("SPEC_ID", "")

    def step2(self) -> None:
        # "See `commands/dev.md` graphify hydrator block for the canonical Bash invocation."
        text = self.ref.block("Step 2", anchor="graphify-query.py", lang="bash")
        self.o.run_text(text, "Step 2 Bash graphify-query.py", "Step 2: graphify pre-BA hydrator")

    def step3(self) -> None:
        self.o.s.say("ui-specialist: SKIP — a command file, no UI\n"
                     "architect: SKIP — one new file, no cross-module change\n"
                     "product-owner: SKIP — the request states the behaviour\n"
                     "user: SKIP — no end-to-end flow involved")

    # ------------------------------------------------------------ BA, BA-QA
    def step4(self) -> None:
        o = self.o
        # Pre-BA: surface retry signals (Four Contracts Awareness), as the text spells each.
        cmd = o.bind(o.inline("Pre-BA: surface retry signals", "Recent related commits", startswith="git log"))
        c = o.run(cmd, "Recent related commits", "Step 4 Bash recent commits")
        self.commits = [l for l in c.response.get("stdout", "").split("\n") if l.strip()] if c.ok else []
        item = next(l for l in o.section("Pre-BA: surface retry signals").split("\n") if "Existing BA specs" in l)
        pattern = re.findall(r"`([^`]+)`", re.sub(r"\(legacy[^)]*\)", "", item))[0]
        g = o.s.tool("Glob", {"pattern": pattern, "path": o.project}, label="Step 4 Glob prior tickets",
                     deviation=o.devs.at("Step 4 Glob prior tickets"))
        self.specs = [os.path.relpath(p, o.project) for p in g.response.get("filenames", [])] if g.ok else []
        calls = [("Run Blast-Radius Tool Phase 1", {"<comma-separated files_to_modify>": CMD_REL})]
        act = agents.Act(content=_ba_content(self.tid), status="ready", text_calls=calls, respell=o.respell,
                         summary="a project slash command named test runs the toy package tests")
        o.dispatch(o.template("Step 4"), act, "Step 4 Agent(ba)", self.tid, subagent_type=self.step_role(4))

    def step6(self) -> None:
        self.ba_outputs = self.text_paths(6, "Read BA output files")
        for rel in self.ba_outputs:
            self.read(rel, f"Step 6 Read {rel}")
        ctx = self.load(self.context_rel)
        # Post-BA: verify contract compliance (the fields the text lists), from what was read.
        missing = [k for k, v in (("evidence.measured.value", ((ctx.get("evidence") or {}).get("measured") or {}).get("value")),
                                  ("evidence.expected.source", ((ctx.get("evidence") or {}).get("expected") or {}).get("source")),
                                  ("scope_expansion.all_occurrences", (ctx.get("scope_expansion") or {}).get("all_occurrences")))
                   if not v]
        if missing:
            raise AssertionError(f"BA context lacks {missing}")

    def step7(self) -> dict:
        o = self.o
        o.run_step_blocks(7)
        act = agents.Act(verdict="pass", summary="BA analysis checked")
        d = o.dispatch(o.template("Step 7"), act, "Step 7 Agent(qa) ba_validation", self.tid)
        rel = next(a["path"] for a in d.player.b.obligation["artifacts"] if a.get("kind") == "json")
        self.read(rel, f"Step 7 Read {rel}")
        return self.load(rel)

    # ------------------------------------------------------------ graphify
    def step9(self) -> None:
        o, ref = self.o, self.ref
        # The step dispatches graphify from commands/dev.md's enrichment template.
        fields = ref.template("Step 9")
        o.dispatch(fields, agents.Act(), "Step 9 Agent(graphify)", self.tid)
        if "Graph context file:" not in o.section("Step 9"):
            o.s.say("graphify dispatched (advisory); proceeding to Step 10")
            return
        # The run record dev.md names, and the line its status puts into the dev and QA dispatches.
        sec = ref.section("Step 9")
        status = None
        for code in re.findall(r"`(\.claude/dev-registry/<DEV_SESSION_ID>/graphify/[\w.-]+\.json)`", sec):
            path = os.path.join(o.project, o.bind(code))
            if os.path.isfile(path):
                o.s.read(path, label=f"Step 9 Read {os.path.basename(path)}")
                status = json.loads(agents.peek(self.rp, "main", path)).get("status")
                break
        o.s.say(f"graphify_status={status}")
        add = re.search(r"`(Graph context file:[^`]+)`", sec)
        if add and status in ("ok", "degraded"):
            self.graph_lines = [o.bind(add.group(1))]

    # ------------------------------------------------------------ dev, QA
    def dispatch_dev(self, label: str, context_rel: str | None = None, add_lines=(), iteration: bool = False):
        o = self.o
        fields = with_lines(o.template("Step 10"), list(add_lines) + self.graph_lines, context_rel)
        if iteration:  # QA's finding: the command runs the whole tree; dev narrows it to -q tests/
            work = roles.dev([(CMD_REL, "python3 -m pytest\n", "python3 -m pytest -q tests/\n")], baseline_fallback=True)
        else:
            work = roles.dev([], creates=[(CMD_REL, CMD_PARTIAL if self.variant == "qa-fail" else CMD_FINAL)],
                             baseline_fallback=True)
        content = {"*": {"baseline_head_sha": "", "baseline_dirty_snapshot": "",  # none in the dispatch payload
                         "dev": {"fix_layer": LAYER}}}
        act = agents.Act(work=work, content=content, summary="the test command runs the toy package tests")
        return o.dispatch(fields, act, label, self.tid, subagent_type=self.step_role(10))

    def step11(self, label: str = "Step 11") -> None:
        rel = self.text_paths(11, "Read dev implementation report")[0]
        self.read(rel, f"{label} Read {rel}")
        dev = self.load(rel).get("dev") or {}
        # "Files exist that were reported as created/modified".
        for f in sorted(set(dev.get("files_created") or []) | set(dev.get("files_modified") or [])):
            self.read(f, f"{label} Read {f}")

    def step12(self, label: str = "Step 12", verdict: str = "pass") -> None:
        o = self.o
        o.run_step_blocks(12, label=label)
        extra = {}
        if verdict == "fail":
            extra = {"qa": {"failures": [QA_FAILURE], "overall_assessment": "AC-01 not met",
                            "refined_context": {"must": "run python3 -m pytest -q tests/ in the command body"}}}
        qa_work = roles.qa(e2e={"status": "legitimately_skipped",
                                "blocking_reason": "no user-facing surface: a command file"}, extra=extra)

        def work(sub, b, player):  # QA reads the files the dev report lists before its verdict
            rep = next((p for name, p in b.inputs if name.lower().startswith("dev report")), None)
            if rep and os.path.isfile(rep):
                dev = json.loads(agents.peek(self.rp, sub.role, rep)).get("dev") or {}
                for f in sorted(set(dev.get("files_created") or []) | set(dev.get("files_modified") or [])):
                    sub.read(os.path.join(o.project, f), label=f"{sub.role} Read {f}")
            return qa_work(sub, b, player)
        act = agents.Act(verdict=verdict, work=work, summary=f"QA {verdict}", respell=o.respell,
                         text_calls=[("Phase 6: Blast-Radius Phase 2 Verification", {})])
        o.dispatch(with_lines(o.template("Step 12"), self.graph_lines), act, f"{label} Agent(qa)", self.tid)

    def step13(self, label: str = "Step 13") -> str:
        rel = self.qa_report_rel = self.text_paths(13, "Read QA report")[0]
        self.read(rel, f"{label} Read {rel}")
        return (self.load(rel).get("qa") or {}).get("status")

    def step14(self, label: str = "Step 14") -> None:
        perms = ((self.load(self.qa_report_rel).get("qa") or {}).get("permissions_verification")
                 or {}).get("validated_permissions") or []
        # The text's per-permission jq edit (an example entry) runs once per validated permission: none here.
        self.o.run_step_blocks(14, label=label,
                               skip=lambda name, b, para: "permissions.allow +=" in b.text and not perms)

    def step15(self) -> None:
        o = self.o
        self.iteration += 1
        rules = [(r"^N$", str(self.iteration))]
        o.run_step_blocks(15, extra_rules=rules)
        # "Return to Step 10 with new context JSON": the context file a Step 15 block writes, if any.
        ctx_tpl = re.search(r"Context file:\s*(\S+)", o.template("Step 10")["prompt"]).group(1)
        ctx_rx = re.escape(ctx_tpl.split("<", 1)[0]) + r"\S*\.json"
        new_ctx = None
        for _name, b, _para in o.step_blocks("Step 15"):
            for t in re.findall(r">\s*(" + ctx_rx + ")", o.bind(b.text, rules)):
                new_ctx = t
        # Lines the text adds to Step 10's template for the re-dispatch ("adding the line `X: path`").
        add = [o.bind(c) for c in re.findall(r"`([A-Z][\w ]* file:\s*[^`\s]+)`", o.section("Step 15"))]
        self.dispatch_dev(f"Step 15 Agent(dev) iteration {self.iteration}", new_ctx, add, iteration=True)
        self.step11("Step 15 (Step 11 again)")
        self.step12("Step 15 (Step 12 again)", "pass")
        status = self.step13("Step 15 (Step 13 again)")
        assert status == "pass", status
        self.step14("Step 15 (Step 14 again)")

    # ------------------------------------------------------------ completion
    def step16(self, status: str) -> None:
        o = self.o
        tpl = o.block("Step 16", anchor="Development Completion Report")
        fill = {"original user request": REQUIREMENT, "final clarified requirement": REQUIREMENT,
                "criterion 1": AC["then"], "what user reported": "the project has no test command",
                "underlying issue": f"no {CMD_REL} exists", "how root cause was addressed": f"created {CMD_REL}",
                "why this fixes root cause": "the command file is what makes the test command exist",
                "what changed": "new command file"}
        lines = []
        for l in tpl.split("\n"):
            if "{criterion 2}" in l or "Scripts Created" in l or "script-name.sh" in l or "Parameters:" in l:
                continue  # no second criterion and no script in this cycle
            lines.append(re.sub(r"\{([^{}\n]+)\}", lambda m: fill.get(m.group(1), "none"), l))
        report = "\n".join(lines).replace("`path/to/file`", f"`{CMD_REL}`")
        report = o.bind(report, [(r"^ISO-8601$", utc_now()), (r"^N$", str(self.iteration)),
                                 (r"^hash$", "none"), (r"^message$", "no prior commit: the file is new")])
        rel = self.text_paths(16, "Save report to")[0]
        o.s.write(os.path.join(o.project, rel), report, label="Step 16 Write completion report",
                  deviation=o.devs.at("Step 16 Write completion report"))
        calls = o.run_step_blocks(16, capture=("ARTIFACT_CHAIN",))
        # "Completion requires process exit 0 and top-level status == pass": the resolver block's own result.
        self.chain_ok = bool(calls) and all(c.ok for c in calls) and \
            json.loads(o.values.get("ARTIFACT_CHAIN") or "{}").get("status") == "pass"
        if "/spec-update --temp" not in o.section("Step 16"):
            return
        # Workflow update: all requested work is complete -> /spec-update --temp, as that command's text says.
        su = Orchestrator(self.rp, "spec-update", session=o.s, deviations=o.devs)
        mk = su.inline("Temp-note mode", "mktemp", startswith="mktemp")
        c = o.run(mk, "Create the temp update note", "Step 16 Bash mktemp update note")
        path = c.response.get("stdout", "").strip() if c.ok else ""
        if not path:
            return
        m = re.search(r"update-([A-Za-z0-9]+)\.md$", path)
        if m:
            self.rp.rand(m.group(1))
        o.s.read(path, label="Step 16 Read update note", deviation=o.devs.at("Step 16 Read update note"))
        paths = ", ".join(self.ba_outputs + [f"docs/dev/dev-report-{self.tid}.json", self.qa_report_rel, rel])
        note = su.block("Temp-note mode", anchor="# Update")
        note = su.bind(note, [(r"^ISO-8601$", utc_now()), (r'id or "unknown"', self.tid),
                              (r"^spec\|dev\|close", "dev"), (r"exact next command", f"/close {self.tid}"),
                              (r"^paths$", paths), (r"^path or URL$", self.ba_outputs[0]),
                              (r"3-8 sentences", f"/dev-command {self.tid} is complete: QA {status} after "
                                                 f"{self.iteration} iteration(s). Close it, then commit and push."),
                              (r".", "see the completion report")])
        o.s.write(path, note, label="Step 16 Write update note", deviation=o.devs.at("Step 16 Write update note"))

    # ------------------------------------------------------------ the whole cycle
    def run(self) -> None:
        o = self.o
        self.start()
        self.step1()
        self.to(2); self.step2()
        self.to(3); self.step3()
        self.to(4); self.step4()
        self.to(5)  # BA wrote its report (status ready): no clarification round
        self.to(6); self.step6()
        self.to(7)
        report = self.step7()
        assert report.get("verdict") == "pass", report
        self.to(8)  # QA passed BA: no BA-QA iteration
        self.to(9); self.step9()
        self.to(10); self.dispatch_dev("Step 10 Agent(dev)")
        self.to(11); self.step11()
        self.to(12); self.step12(verdict="fail" if self.variant == "qa-fail" else "pass")
        self.to(13)
        status = self.step13()
        self.to(14)
        if status == "pass":
            self.step14()
        self.to(15)
        if status != "pass":
            self.step15()
            status = "pass"
        self.to(16); self.step16(status)
        o.advance()
        if self.chain_ok:
            text = (f"/dev-command {self.tid} complete: {CMD_REL} runs the toy package tests; QA passed. "
                    f"Next: /close {self.tid}")
        else:  # the postcondition blocks completion; the block's `|| exit 2` printed no errors[]
            text = (f"/dev-command {self.tid}: QA passed and {CMD_REL} runs the toy package tests, but the "
                    "artifact-chain postcondition (Step 16) exited 2, so the cycle is not complete.")
        o.s.stop(text, label="Stop", deviation=o.devs.at("Stop"))


def run(rp) -> None:
    variant = rp.args.get("variant", "plain")
    if variant not in ("plain", "qa-fail"):
        raise ValueError(f"unknown variant {variant!r}")
    rp.pipeline = f"{PIPELINE}/{variant}" if variant != "plain" else PIPELINE
    DevCommandCycle(rp, variant).run()
