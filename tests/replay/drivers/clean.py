"""/clean, played compliantly from commands/clean.md and the agent files it dispatches, of the tree under
test, read at run time, up to the cleaner's commit and the completion report.

Scenario: the toy as the owner left it before typing /clean (SETUP, committed by `prepare`, which
cli.py runs on the reset sandbox before the replay starts, so its files are tracked at replay start): a
root-level `*-guide.md` the text's documentation rules move under docs/, and one script under scripts/
with a bare `python3` call, so the style planner has a file to give an inspector and the style
standards a violation (without one, Step 7's planner finds no file and the text skips to Step 11, whose
merge then has no style or prompt report: see "Text points"). The owner types `/clean` (no `--codex`:
every `codex_required` line is left out), passes the checklist the hook hands it (scripts/todo/clean.py)
to its first TodoWrite and completes one checklist step per TodoWrite call; at Step 13 the owner picks
the first cleanup option (execute all) in one AskUserQuestion, so the approvals are generated
mechanically from every finding.

What each step does is taken from the tree's commands/clean.md:

* Step 1: the checklist script the text names (run as its inline code names it), `docs/clean/` created
  with REQUEST_ID by the text's own assignment and an ISO-8601 TIMESTAMP, in one Bash call.
* Step 2: the scan script the text names; its JSON read for the context.
* Step 3: git status, branch, recent commits and the directory listing the template's fields ask for
  (one Bash call); the step's JSON template filled field by field, Written at the step's `Save to:` path.
* Step 4: the numbered items in order: the folder discovery; the freshness check saved where item 2
  says; the rule-inspector context built at item 3's path from the rule-inspector's own Input Format
  (agents/rule-inspector.md) plus the fields item 3 lists; item 4's `orchestrator.sh rule-inspect`;
  then the rule-inspector dispatch that call's `next_step` and the step's "Run rule-inspector" ask for
  (the checklist names no subagent call here: a driver resolution, see "Text points" below); item 5's
  existence check (Glob) and item 6's README mtime check. The rule-inspector is played from its agent
  file: Step 1's discovery block, Step 2's `git log` per folder, Step 4's index script for the folders
  its text names (the working tree: the `ORCHESTRATOR_KEY_FOLDERS` that exist, the default list read
  from scripts/orchestrator.sh; the base: every discovered folder), Step 5's README script for each
  folder its freshness entry does not mark FRESH, its Output Format as the final message.
* Step 5: the step's Bash block (`clean-inspect`), then the cleanliness-inspector dispatch with the
  step's prompt block (its obligation block, where the text has one, instantiated: dispatched_at the
  current UTC time) and the report path the step says it writes. The inspector reads its context,
  runs the Inspection Checklist calls its text makes over the whole project (`Run`/`MUST execute`
  lines of a section that is not `--changed-files`-only), reads each folder README it finds and Writes
  its Output Format with the scenario's finding.
* Steps 6-10: Step 6 has no call of its own (its text is the heading of Steps 7-10); Step 7's planner,
  saved where the step says, then Read; Step 8 one style-inspector dispatch per plan group from the
  step's prompt block, `run_in_background: true` as the text says; Step 9 each partial Read and the
  merged report Written; Step 10 the plan Read again and the coverage compared.
* Step 10A (no checklist item: done while Step 10 is in progress): the prompt-inspector dispatch with
  the context path, the `command_files:` and `agent_files:` lines (Glob of commands/*.md and
  agents/*.md), the obligation block the step names, where it names one (instantiated as Step 5's),
  and the report path; its report Read for the coverage gate.
* A stop that returns an inspector's declared report (G2 naming that report): the inspector writes the
  report its work drafted again, as the block asks, and stops again (its next round).
* Step 11: the merge call as the text spells it. On a text whose call names a context no step wrote
  and whose helper returns a combined report outside docs/clean/ (the base, A116/A124), see "Gaps".
* Step 12: the combined report Read and presented with the text's options.
* Step 13: one AskUserQuestion (the owner picks option 1); the combined report Read; one approved
  action per finding (cleanliness `findings`, style `violations`, `prompt_report.findings`), the counts
  compared; Written at the step's `Save to:` path.
* Step 14: the two counts Read from their files and compared.
* Step 15: the checkpoint hook, the checkpoint ref read, the step's `record-checkpoint` call.
* Step 16: the step's jq block (the checkpoint commit bound where the text has the placeholder), then
  the cleaner dispatch from the step's `Agent tool invocation:` prompt. The cleaner is played from its
  agent file: the report files the prompt names Read, the checkpoint check (Safety First), each
  approved action by the operation its Action Types table gives (move with `mkdir -p` and `mv`, the
  `fix_style` replacement with the Edit tool; an action the table has no row for is skipped with its
  reason), `git add` of the affected files, one commit with the text's message, the push-gate token as
  the tree's text writes it (the writer's block, or, on the base, the Python script its prose
  describes), and its execution report Written where the prompt says.
* Step 17: the two git calls the step names; Step 18: the completion report from the step's template,
  Written at its `Save to:` path; the last TodoWrite; Stop.

Text points the driver resolves (each also reported as a text defect):
* Step 4's checklist item has no subagent call, but the step says "Run rule-inspector" and
  `orchestrator.sh rule-inspect` prints `next_step: invoke rule-inspector subagent with context`: the
  driver dispatches the rule-inspector after that call.
* The checklist's Step 6 carries the style-inspector subagent call that the text makes at Step 8: the
  driver completes Step 6 when the text's Step 6 has nothing left to do (a block, if a hook refuses
  it, is recorded).
* Step 10A has no checklist item: its dispatch is made while Step 10 is in progress.
* Step 8's `run_in_background: true` is dispatched as written (a hook that refuses it is recorded).
* Step 5's prompt names the report only in its obligation, where it has one (the base's names only the
  context); the report path is the one the step says the inspector writes, added as a `Write your
  report to:` line (likewise for Step 10A's report). Step 5's Bash block
  runs before the dispatch (its output says the inspectors can now be invoked).
* "activate venv" (Step 1; the base cleaner's token script) names no venv a product repository has:
  the call runs without one, as row 7 runs `source venv/bin/activate &&` calls (E5 (b)).
* The cleanliness-inspector includes each MANDATORY script's JSON output in full under the findings key
  its section names; the scripts list the harness install's own files too, and those items name no
  action, so their approvals carry the template's generic `fix`, which the cleaner's Action Types table
  has no operation for: the cleaner skips them with that reason.
* The cleaner's Safety First check (`git log -1 --grep=...`) cannot see Step 15's checkpoint, which
  lives on refs/checkpoints/<branch>, not in HEAD's history: the cleaner goes on, as its context records
  `safety_checkpoint_created: true`.
* Step 7: "If AGENT_COUNT is 0, skip to Step 11" is followed as written (not reached by this scenario).

Gaps (`--arg gaps=bridged|strict`, default bridged). The base text's Step 11 merge reads
`docs/clean/context-with-reports-<id>.json`, which no step creates, and its helper writes the
combined report to `/tmp/combined-report-<epoch>.json`, while Steps 13, 14 and 16 read
`docs/clean/combined-report-<id>.json` (P1b row 17, A116, A124). Run as written (`gaps=strict`), the merge
exits 1 and the replay ends at Step 11 (a failure, not a block, so no DEVIATION passes it). By default
the driver bridges each gap with the smallest step that gives the missing file, recorded in blocks.json
"respellings" at each application, where the text has the gap: "C1 context-with-reports" (one Bash
call merging the context and the three reports under the keys the helper reads) and "C2 combined-report
path" (the text's own amendment, the prompt report added to the combined JSON, written at the path the
later steps read). A text without the gap (the working tree) gets neither.

Respellings (row 7): none; every harness script /clean names is spelled `~/.claude/scripts/...`.

Deviations: DEVIATIONS below, one entry per block the base tree's replay meets, each with a comment
quoting the hook's text; nothing else passes a block. `--arg kept=<JSON>` makes each pass only a kept
base block (drivers/dev.py KeptOnly).

Faults (`--arg fault=<role>:<missing|invalid|notjson>`, none by default): the first Write of that
inspector's report is changed through the framework's fault hook (Replay.step): `missing` skips it,
`invalid` drops the first field the declared schema requires, `notjson` keeps the first half of the
text. Each is meant to be stopped at the inspector's own stop and pass on its next round (above).

Not replayed: options 2-5 at Step 13 (a subset of option 1's relations: fewer approvals, or none and no
cleaner), `--codex`, a coverage miss at Steps 10 and 10A (a re-dispatch of the same templates), and a
/push after the cleaner's commit (push.sh reads the token through the same writer drivers/push.py
replays after /commit).
"""
from __future__ import annotations

import calendar
import json
import os
import re
import shlex
import time

from .. import agents, cmdtext
from ..pipeline import Deviations, Orchestrator, utc_now
from ..replay import Deviation
from ..sandbox import FIXED_DATE

PIPELINE = "clean"
# The artifact check's cost of this driver (tests/artifact_graph/shards.py balances its CI shards by it):
# CPU seconds of the shipped and armed traced replays and their differential runs, measured at 1d42933
# (153 + 156 CPU-s traced, 8 per replay, E1's fallback 151 runs at 0.213 CPU-s each), scaled by dev plain's
# declared/measured replay CPU (118.4/114.8)
COST = 368

RESPELLINGS: list = []

# Blocks the base tree's replay meets, each passed by a deviation at the step it occurs on: the
# refused call is applied as if allowed, so every later step runs and is traced.
DEVIATIONS = Deviations([
    # DEVIATION: "[Orchestrator Gate] BLOCKED: Bash used consecutively beyond limit (6/5)."
    # The text's main-agent Bash calls between two dispatches outnumber the gate's cap of 5 (only an Agent
    # dispatch resets the count): Steps 1-4 before the rule-inspector, Steps 11-16 before the cleaner.
    ("Step * Bash *", Deviation(
        "hooks/pretool-orchestrator-gate.py", "Bash used consecutively beyond limit",
        "the command's own run of Bash calls between dispatches")),
    # DEVIATION: "[Orchestrator Gate] BLOCKED: Write used consecutively beyond limit (2/1)."
    # The gate allows one Write per turn; one /clean turn writes the context (Step 3), the rule-inspector
    # context (Step 4), the merged style report (Step 9), the approvals (Step 13) and the completion report
    # (Step 18), each at the path its step names.
    ("Step * Write *", Deviation(
        "hooks/pretool-orchestrator-gate.py", "Write used consecutively beyond limit",
        "the coordination documents the steps write")),
    # DEVIATION: "BLOCKED: Cannot complete Step 5 ("Step 6: Invoke style inspector"). This step requires a
    # subagent call (style-inspector) that has not been made."
    # The checklist puts the style-inspector call at Step 6; the text makes it at Step 8 (Step 6 is the
    # heading of Steps 7-10).
    ("TodoWrite Step 6 done, Step 7 in_progress", Deviation(
        "hooks/pretool-todo-validate.py", "This step requires a subagent call (style-inspector) that has not been made",
        "Step 6 completed as its text reads: its style-inspector dispatches are Step 8's")),
    # DEVIATION: "[BLOCK] Agent runs in the background by default and is forbidden for the orchestrator."
    # Step 8 launches each style-inspector "with `run_in_background: true`".
    ("Step 8 Agent(*", Deviation(
        "hooks/pretool-block-background-tasks.py", "Agent runs in the background by default and is forbidden",
        "Step 8's dispatch as the text spells it (the replay's dispatch is synchronous)")),
    # DEVIATION: "BLOCKED: agent git commit - only the blessed /merge auto-bulk bridge or the /commit wrapper may
    # commit from an agent context."
    # The cleaner's commit, as agents/cleaner.md's Git Operations make it (P1b acceptance 9: refused on the
    # base too; P1c's).
    ("agent:cleaner Bash commit", Deviation(
        "hooks/pretool-git-privilege-guard.py", "BLOCKED: agent git commit",
        "the cleaner's commit as its agent text makes it")),
])

# The owner's toy before /clean: a root-level guide the documentation rules move under docs/, and a
# script with a bare python3 call (style standard 3) the planner hands an inspector.
SETUP = {
    "usage-guide.md": "# Usage guide\n\nCall `toy.add(a, b)` to add two numbers.\n",
    "scripts/run-tests.sh": "#!/usr/bin/env bash\n# Run the toy's test suite.\nset -euo pipefail\n"
                            "python3 -m pytest -q tests\n",
}


def prepare(project: str, git) -> None:
    """The scenario's starting state, as the owner left it before typing /clean: SETUP committed in the toy
    (run by cli.prepare before the replay starts, so its files are tracked at replay start), their mtimes
    fixed as the sandbox fixes the toy's own (no racily clean index)."""
    stamp = calendar.timegm(time.strptime(FIXED_DATE[:19], "%Y-%m-%dT%H:%M:%S"))
    for rel, text in SETUP.items():
        path = os.path.join(project, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)
        if rel.endswith(".sh"):
            os.chmod(path, 0o755)
        os.utime(path, (stamp, stamp))
    git("add", "--", *SETUP)
    git("commit", "-q", "-m", "docs and test runner")
    git("update-index", "-q", "--really-refresh")


def _finding_key(title: str, keys) -> str | None:
    """The Output Format findings key a checklist section's title names (each word of the key the start of a
    word of the title: "Orphaned Commands Detection" -> orphan_commands)."""
    words = re.findall(r"[a-z]+", title.lower())
    best = [k for k in keys if all(any(w.startswith(p) for w in words) for p in k.split("_"))]
    return max(best, key=len) if best else None


def _action(finding: dict) -> str:
    """The approval's action for a finding: the one it names (an action, a destination, an archive path, a
    safe delete, a recommendation verb), else the template's generic `fix`."""
    if finding.get("action"):
        return finding["action"]
    if finding.get("destination"):
        return "move"
    if finding.get("archive_to"):
        return "archive"
    if finding.get("safe_to_delete") is True:
        return "delete"
    rec = str(finding.get("recommendation") or "").split()
    return rec[0].lower() if rec and rec[0].lower() in ("move", "archive", "delete", "rename") else "fix"


def _json_out(text: str):
    """The last JSON value printed in `text` (an object or array), else None."""
    dec = json.JSONDecoder()
    found = None
    for m in re.finditer(r"[\[{]", text or ""):
        try:
            found, _ = dec.raw_decode(text[m.start():])
            break
        except ValueError:
            continue
    return found


FAULT_KINDS = ("missing", "invalid", "notjson")


def _fault_arg(value: str):
    """`<role>:<kind>` -> (role, kind), or None."""
    if not value:
        return None
    role, _, kind = value.partition(":")
    if not role or kind not in FAULT_KINDS:
        raise ValueError(f"fault must be <role>:<{'|'.join(FAULT_KINDS)}>, not {value!r}")
    return role, kind


class CleanRun:
    def __init__(self, rp, gaps: str = "bridged", fault: str = ""):
        if gaps not in ("bridged", "strict"):
            raise ValueError(f"gaps must be bridged or strict, not {gaps!r}")
        self.rp, self.gaps = rp, gaps
        self.fault = _fault_arg(fault)
        self.reports: dict = {}     # declared report (rel path) -> the text its inspector's work drafted
        from . import close as closedrv
        self.devs = closedrv.kept_only(rp, DEVIATIONS)
        # A subagent's own calls (agents.Player) take the deviations declared for their step labels.
        rp.deviation_at = self.devs.at
        self.o = Orchestrator(rp, "clean", deviations=self.devs, respellings=RESPELLINGS)
        self.project = self.o.project
        self.o.values["PROJECT_ROOT"] = self.project
        self.rid = self.ts = ""
        self.facts: dict = {}
        self.plan: dict = {}
        self.checkpoint = ""
        self.ended = ""

    # ------------------------------------------------------------ text helpers
    def fill(self, text: str) -> str:
        return cmdtext.fill(text, {"${REQUEST_ID}": self.rid, "{REQUEST_ID}": self.rid, "{PROJECT_ROOT}": self.project})

    def codes(self, heading: str, anchor: str) -> list:
        return cmdtext.inline_codes(self.o.text, heading, anchor)

    def code(self, heading: str, anchor: str, startswith: str = "", contains: str = "") -> str:
        for c in self.codes(heading, anchor):
            if c.startswith(startswith) and contains in c:
                return c
        raise cmdtext.TextNotFound(f"{heading}: no inline code {startswith!r}/{contains!r} in the item with {anchor!r}")

    def save_path(self, heading: str) -> str:
        """The rel path of the step's `Save to:` line."""
        m = re.search(r"Save to:\s*`([^`]+)`", self.o.section(heading))
        if not m:
            raise cmdtext.TextNotFound(f"{heading} has no `Save to:` line")
        return self.fill(m.group(1))

    def item(self, heading: str, n: int) -> str:
        """The text of numbered item `n.` of a step."""
        m = re.search(r"^%d\.\s+(.*)$" % n, self.o.section(heading), re.M)
        if not m:
            raise cmdtext.TextNotFound(f"{heading} has no item {n}")
        return m.group(1)

    def role_in(self, heading: str) -> str:
        """The agent the step's own text names (an agents/<name>.md of the tree)."""
        for name in re.findall(r"\b([a-z]+(?:-[a-z]+)+)\b", self.o.section(heading)):
            if os.path.isfile(os.path.join(self.o.harness, "agents", name + ".md")):
                return name
        raise cmdtext.TextNotFound(f"{heading} names no agent")

    def checklist_role(self, step: int) -> str | None:
        todo = next(t for t in self.o.todos if re.match(rf"Step {step}\b", t["content"]))
        return (todo.get("subagent_call") or {}).get("subagent_type")

    def abs(self, rel: str) -> str:
        return rel if os.path.isabs(rel) else os.path.join(self.project, rel)

    def to(self, n: int) -> None:
        while not self.o.at_step(n):
            self.o.advance()

    def bash(self, command: str, label: str, description: str = "", capture=()):
        return self.o.run(self.o.shell_bind(command), description or label, label, capture=capture)

    def read(self, rel: str, label: str):
        return self.o.s.read(self.abs(rel), label=label, deviation=self.devs.at(label))

    def load(self, rel: str, actor: str = "main"):
        return json.loads(agents.peek(self.rp, actor, self.abs(rel)))

    def write(self, rel: str, content: str, label: str):
        return self.o.s.write(self.abs(rel), content, label=label, deviation=self.devs.at(label))

    def say(self, text: str) -> None:
        self.o.s.say(text)

    def respelled(self, name: str, where: str, label: str) -> None:
        self.rp.respellings.append({"step": label, "name": name, "where": where, "count": 1})

    # ------------------------------------------------------------ Steps 1-3
    def step1(self) -> None:
        o = self.o
        o.slash("")
        o.todo_start()
        script = self.code("Step 1", "Load TodoList checklist", contains="scripts/todo/")
        self.bash(script, "Step 1 Bash checklist script", "Load the /clean checklist")
        rid = self.code("Step 1", "Set up working directory", startswith="REQUEST_ID=")
        d = self.code("Step 1", "Set up working directory", startswith="docs/clean")
        c = self.bash(f"mkdir -p {shlex.quote(d)}\n{rid}\nTIMESTAMP=\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"",
                      "Step 1 Bash request id", "Create docs/clean/ and the request id", capture=("REQUEST_ID", "TIMESTAMP"))
        if not c.ok or not o.values.get("REQUEST_ID"):
            raise RuntimeError("Step 1: no REQUEST_ID")
        self.rid, self.ts = o.values["REQUEST_ID"], o.values["TIMESTAMP"]
        self.rp.task(self.rid)

    def step2(self) -> None:
        cmd = self.code("Step 2", "scan-project.sh", contains="scan-project.sh")
        c = self.bash(cmd, "Step 2 Bash scan-project", "Scan the project structure")
        self.facts["scan"] = _json_out(c.response.get("stdout", "")) if c.ok else {}

    def step3(self) -> None:
        c = self.bash('git status --short\necho "---"\ngit branch --show-current\necho "---"\n'
                      'git log --oneline -n 5\necho "---"\nls -R', "Step 3 Bash codebase state",
                      "Git status, branch, recent commits and the directory listing")
        parts = (c.response.get("stdout", "") if c.ok else "").split("---\n")
        parts += [""] * (4 - len(parts))
        scan = self.facts.get("scan") or {}
        counts = scan.get("file_counts") or {}
        self.facts.update(git_status=parts[0].strip(), branch=parts[1].strip(),
                          commits=[l for l in parts[2].split("\n") if l.strip()], listing=parts[3].strip())
        values = {"request_id": self.rid, "timestamp": self.ts, "project_root": self.project,
                  "project_type": scan.get("project_type", "Generic"), "git_status": self.facts["git_status"],
                  "current_branch": self.facts["branch"], "recent_commits": self.facts["commits"],
                  "directory_structure": self.facts["listing"], "total": counts.get("total", 0),
                  "docs": counts.get("docs", 0), "scripts": counts.get("scripts", 0), "tests": counts.get("tests", 0)}
        tpl = json.loads(cmdtext.block(self.o.text, "Step 3", lang="json"))
        self.context_rel = self.save_path("Step 3")
        self.write(self.context_rel, json.dumps(self.filled(tpl, values), indent=2) + "\n", "Step 3 Write context")

    def filled(self, node, values: dict, key: str = ""):
        """A JSON template with each leaf whose key has a run value replaced by it."""
        if isinstance(node, dict):
            return {k: (values[k] if k in values and not isinstance(v, dict) else self.filled(v, values, k))
                    for k, v in node.items()}
        return node

    # ------------------------------------------------------------ Step 4
    def step4(self) -> None:
        o = self.o
        disc = self.code("Step 4", "Discover all folders", contains="discover-folders.sh")
        c = self.bash(disc, "Step 4 Bash discover-folders", "Discover all folders")
        out = c.response.get("stdout", "") if c.ok else ""
        folders = _json_out(out)
        if not isinstance(folders, list):
            folders = [l.strip() for l in out.split("\n") if l.strip()]
        self.facts["folders"] = folders
        fresh_cmd = self.code("Step 4", "Run freshness check", contains="check-readme-freshness.sh")
        fresh_rel = self.code("Step 4", "Run freshness check", startswith="docs/clean/")
        self.bash(f"{fresh_cmd} > {fresh_rel}", "Step 4 Bash freshness", "README freshness check, saved")
        self.read(self.fill(fresh_rel), "Step 4 Read freshness")
        try:
            fresh = self.load(self.fill(fresh_rel))
        except (OSError, ValueError):
            fresh = []
        self.facts["freshness"] = fresh
        # Item 3: the rule-inspector context, in the rule-inspector's own Input Format plus the fields the
        # item lists.
        item3 = self.item("Step 4", 3)
        rule_rel = self.fill(re.search(r"`(docs/clean/rule-context-[^`]+)`", item3).group(1))
        tpl = json.loads(cmdtext.block(self.o.tree.agent_text(self.role_in("Step 4")), "Input Format", lang="json"))
        ctx = self.filled(tpl, {"request_id": self.rid, "timestamp": self.ts, "project_root": self.project,
                                "folders_to_analyze": folders, "discovered_folders": folders,
                                "codebase_state": self.facts.get("git_status", "")})
        ctx["readme_freshness"] = fresh
        ctx["parameters"] = {}
        for code in re.findall(r"`(\w+):\s*(true|false)`", item3):
            ctx["parameters"][code[0]] = code[1] == "true"
        self.rule_rel = rule_rel
        self.write(rule_rel, json.dumps(ctx, indent=2) + "\n", "Step 4 Write rule context")
        o.values["RULE_CONTEXT"] = rule_rel
        inv = self.code("Step 4", "Invoke:", contains="rule-inspect")
        c = self.bash(inv, "Step 4 Bash rule-inspect", "Rule inspection orchestration")
        nxt = (_json_out(c.response.get("stdout", "")) or {}) if c.ok else {}
        role = self.role_in("Step 4")
        if role in str(nxt.get("next_step", "")) or "Run %s" % role in o.section("Step 4"):
            self.dispatch_rule_inspector(role, rule_rel)
        # Item 5: the context's existence; item 6: each stale folder's README mtime.
        self.o.s.tool("Glob", {"pattern": os.path.basename(rule_rel), "path": self.abs(os.path.dirname(rule_rel))},
                      label="Step 4 Glob rule context", deviation=self.devs.at("Step 4 Glob rule context"))
        stale = [e.get("folder") for e in fresh if isinstance(e, dict) and e.get("action") not in (None, "FRESH")]
        if stale:
            paths = " ".join(shlex.quote(os.path.join(f, "README.md") if f != "." else "README.md") for f in stale)
            self.bash(f"stat -c '%Y %n' {paths}", "Step 4 Bash README mtimes", "README mtimes of the stale folders")

    def dispatch_rule_inspector(self, role: str, rule_rel: str) -> None:
        o = self.o
        text = o.tree.agent_text(role)
        prompt = (f"Context file: {rule_rel}\nRequest ID: {self.rid}\nProject root: {self.project}\n\n"
                  "Discover the folder organization rules of this project and update its folder documentation, "
                  "obeying each folder's freshness action in the context.")
        output: dict = {}

        def work(sub, brief, player):
            ctx = json.loads(agents.peek(self.rp, sub.role, self.abs(rule_rel)))
            fresh = ctx.get("readme_freshness") or []
            c = sub.bash(cmdtext.block(text, "Step 1: Discover Folders", lang="bash").replace(
                '"$PROJECT_ROOT"', shlex.quote(self.project)), "Discover folders", label=f"{sub.role} Bash Step 1")
            folders = _json_out(c.response.get("stdout", "")) if c.ok else None
            if not isinstance(folders, list):
                folders = [l.strip() for l in (c.response.get("stdout", "") if c.ok else "").split("\n") if l.strip()]
            folders = [f.rstrip("/") for f in folders]
            log = next(x for x in cmdtext.inline_codes(text, "Step 2: Analyze Each Folder", "Git history")
                       if x.startswith("git log"))
            for f in folders:
                sub.bash(log.replace('"$FOLDER"', shlex.quote(f)), f"Git history of {f}",
                         label=f"{sub.role} Bash Step 2 {f}")
            # Step 4: the folders its text names.
            s4 = cmdtext.section(text, "Step 4: Generate INDEX.md")
            if "ORCHESTRATOR_KEY_FOLDERS" in s4:
                # the folders clean-inspect checks: the script the step names, read for its default list
                orch = os.path.join(o.harness, re.search(r"`~/\.claude/(scripts/[\w.-]+\.sh) clean-inspect`", s4).group(1))
                sub.read(orch, label=f"{sub.role} Read orchestrator.sh")
                dflt = re.search(r"ORCHESTRATOR_KEY_FOLDERS:-([\w,/.-]+)\}", agents.peek(self.rp, sub.role, orch)).group(1)
                index_dirs = [f for f in dflt.split(",") if os.path.isdir(self.abs(f))]
            else:
                index_dirs = folders
            gen_index = cmdtext.block(s4, None, lang="bash")
            for f in index_dirs:
                sub.bash(gen_index.replace('"$FOLDER_PATH"', shlex.quote(self.abs(f))), f"INDEX.md of {f}",
                         label=f"{sub.role} Bash Step 4 {f}")
            gen_readme = cmdtext.block(text, "Step 5: Generate README.md", lang="bash")
            actions = {e.get("folder"): e.get("action") for e in fresh if isinstance(e, dict)}
            readme_dirs = [f for f in folders if actions.get(f, "CREATE_NEW") != "FRESH"]
            for f in readme_dirs:
                purpose, types, naming = self.folder_rules(f)
                cmd = (gen_readme.replace('"$FOLDER_PATH"', shlex.quote(self.abs(f)))
                       .replace('"$PURPOSE"', shlex.quote(purpose)).replace('"$ALLOWED_TYPES"', shlex.quote(types))
                       .replace('"$NAMING_CONVENTION"', shlex.quote(naming)))
                sub.bash(cmd, f"README.md of {f}", label=f"{sub.role} Bash Step 5 {f}")
            output.update({"request_id": self.rid, "timestamp": utc_now(), "inspector": role,
                           "baseline_check": "not_provided",
                           "discoveries": [{"folder": f + "/", "purpose": self.folder_rules(f)[0],
                                            "index_md_generated": f in index_dirs,
                                            "readme_md_generated": f in readme_dirs} for f in folders],
                           "summary": {"folders_analyzed": len(folders), "rules_discovered": len(folders),
                                       "index_files_generated": len(index_dirs),
                                       "readme_files_generated": len(readme_dirs)}})
        player = agents.Player(o.tree, prompt, agents.Act(work=work), role=role)
        label = "Step 4 Agent(rule-inspector)"
        o.s.dispatch(role, prompt, description="Folder rule discovery", body=player.body,
                     result=lambda sub: json.dumps(output, indent=2), label=label, deviation=self.devs.at(label))

    @staticmethod
    def folder_rules(folder: str):
        """The purpose, file types and naming the rule-inspector reads off a toy folder."""
        top = folder.split("/")[0]
        return {"toy": ("Python package source", ".py", "snake_case"),
                "tests": ("Test suite", ".py", "snake_case"),
                "scripts": ("Helper scripts", ".sh", "kebab-case"),
                "docs": ("Project documentation", ".md,.json", "kebab-case")}.get(
            top, (f"{folder} files", "*", "kebab-case"))

    # ------------------------------------------------------------ Step 5
    def step5(self) -> None:
        o = self.o
        for k, (name, b, para) in enumerate(o.step_blocks("Step 5")):
            self.bash(self.fill(b.text), f"Step 5 Bash {name}", "Clean inspection orchestration")
        role = self.checklist_role(5)
        lines = self.prompt_block("Step 5", "Context file:")
        report = self.fill(re.search(r"`(docs/clean/cleanliness-report-[^`]+)`", o.section("Step 5")).group(1))
        prompt = o.instantiate("\n".join(lines + [f"Write your report to: {report}"]), None)
        self.cleanliness_rel = report
        self.dispatch(role, prompt, self.cleanliness_work(role, report), "Step 5 Agent(cleanliness-inspector)",
                      report=report)

    def prompt_block(self, heading: str, anchor: str) -> list:
        """A step's prompt block, placeholders filled, the codex conditional and its line left out."""
        b = cmdtext.block(self.o.text, heading, anchor=anchor)
        out, skip = [], False
        for line in self.fill(b).rstrip("\n").split("\n"):
            if skip:
                skip = False
                continue
            if re.match(r"\s*<If codex_required = true, include the literal next line", line):
                skip = True
                continue
            out.append(line)
        return out

    def dispatch(self, role: str, prompt: str, act_work, label: str, extra_input=None, description: str = "",
                 report: str = ""):
        """A subagent dispatch of /clean. `report`: the report the role's work writes itself (rel path); where
        the prompt's obligation declares it, a stop that returns it gets the inspector's next round."""
        o = self.o
        out: dict = {}
        final: list = []

        def work(sub, brief, player):
            out.update(act_work(sub, brief, player) or {})

        def result(sub):
            final.append(out.pop("_final", None) or json.dumps(out, indent=2))
            return final[-1]
        if report and self.fault and self.fault[0] == role:
            self.inject(role, prompt)
        act = agents.Act(work=work, produced=[report] if report else [])
        player = agents.Player(o.tree, prompt, act, role=role)
        declared = report and any(a.get("path") == report for a in (player.b.obligation or {}).get("artifacts") or [])
        return o.s.dispatch(role, prompt, description=description or role, body=player.body, result=result,
                            label=label, deviation=self.devs.at(label), extra_input=extra_input,
                            on_stop_block=self.next_round(report, final) if declared else None)

    def next_round(self, report: str, final: list):
        """The inspector's next round after a stop that returns its declared report: the block names the
        report, so the inspector writes the report its work drafted again and stops again. A block that
        does not name it is not the inspector's to fix here (the stop stays blocked)."""
        def on_block(sub, ev):
            text = "\n".join(h.get("stderr", "") + h.get("stdout", "") for h in ev.blocks)
            if report not in text or report not in self.reports:
                return None
            sub.s.say(f"My stop returned {report}. Writing the report again, then stopping again.", sub.aid)
            agents.put(sub, self.abs(report), self.reports[report], f"{sub.role} Write report (next round)")
            return final[-1] if final else "Done."
        return on_block

    def inject(self, role: str, prompt: str) -> None:
        """The run's fault on this inspector's report, at the first Write of it (Replay.step's fault hook)."""
        kind = self.fault[1]
        arts = [a for a in (agents.obligation_of(prompt) or {}).get("artifacts") or [] if a.get("kind") == "json"]
        required = (self.o.tree.schema(arts[0]["schema"]).get("required") or []) if arts else []
        done: list = []

        def fn(rp, phase, step):
            if phase != "before" or done or step.get("name") != "Write":
                return
            done.append(kind)
            if kind == "missing":
                step["skip"] = True
                return
            text = step["input"]["content"]
            if kind == "invalid":
                doc = json.loads(text)
                doc.pop(required[0] if required else next(iter(doc)), None)
                text = json.dumps(doc, indent=2) + "\n"
            else:
                text = text[: len(text) // 2]
            step["input"] = dict(step["input"], content=text)
        self.rp.faults.append((f"agent:{role} Write report", fn))

    def cleanliness_work(self, role: str, report: str):
        o = self.o
        text = o.tree.agent_text(role)

        def work(sub, brief, player):
            sec = cmdtext.section(text, "Inspection Checklist")
            findings = {k: [] for k in json.loads(cmdtext.block(text, "Output Format", lang="json"))["findings"]}
            # the whole-project calls of the checklist: `Run`/`MUST execute` a script on "$PROJECT_ROOT", in a
            # section that is not --changed-files-only; a JSON output goes in full into the findings key the
            # section's title names, less the section's exception list
            for part in re.split(r"\n(?=### )", sec):
                title = part.split("\n", 1)[0]
                if "mode only" in title:
                    continue
                key = _finding_key(title, findings)
                exc = re.search(r"\*\*Exception list\*\*[^\n]*\n((?:\s*-\s+`[^`]+`[^\n]*\n?)+)", part)
                skip = set(re.findall(r"`([^`]+)`", exc.group(1))) if exc else set()
                for cmd in re.findall(r"(?:\bRun|\bexecute)\s+`(~/\.claude/scripts/[^`]+\"\$PROJECT_ROOT\")`", part):
                    name = os.path.basename(cmd.split()[0])
                    c = sub.bash(cmd.replace('"$PROJECT_ROOT"', shlex.quote(self.project)), name,
                                 label=f"{sub.role} Bash {name}")
                    out = _json_out(c.response.get("stdout", "") if c.ok else "")
                    if name.startswith("discover-folders"):
                        for f in (out if isinstance(out, list) else []):
                            readme = self.abs(os.path.join(f.rstrip("/"), "README.md"))
                            if os.path.isfile(readme):
                                sub.read(readme, label=f"{sub.role} Read {f.rstrip('/')}/README.md")
                    elif isinstance(out, dict) and key:
                        for v in out.values():
                            if isinstance(v, list):
                                findings[key] += [i for i in v if isinstance(i, dict) and os.path.splitext(
                                    os.path.basename(str(i.get("file", ""))))[0] not in skip]
            for rel in SETUP:
                if "/" not in rel and rel.endswith(".md"):  # a root .md the documentation rules move to docs/
                    dest = f"docs/guides/{rel}" if re.search(r"-guide\.md$", rel) else f"docs/{rel}"
                    findings["misplaced_docs"].append({
                        "file": rel, "reason": "markdown file in the project root outside the allowed set",
                        "severity": "major", "recommendation": "move", "destination": dest})
            items = [f for v in findings.values() if isinstance(v, list) for f in v]
            doc = {"request_id": self.rid, "timestamp": utc_now(), "inspector": role, "baseline_check": "not_provided",
                   "findings": findings, "codex_consult": {"invoked": False, "status": "not_requested", "findings": [],
                                                           "feedback_summary": None, "feedback_incorporated": None},
                   "summary": {"total_issues": len(items), "critical": 0,
                               "major": sum(1 for f in items if f.get("severity") == "major"),
                               "minor": sum(1 for f in items if f.get("severity") == "minor"),
                               "estimated_space_saved": "0 MB"}}
            self.reports[report] = json.dumps(doc, indent=2) + "\n"
            agents.put(sub, self.abs(report), self.reports[report], f"{sub.role} Write report")
            return {"status": "complete", "report": report, "total_issues": len(items)}
        return work

    # ------------------------------------------------------------ Steps 6-10A
    def step7(self) -> bool:
        o = self.o
        planner = self.code("Step 7", "Run the planner script", contains="plan-style-inspection.sh")
        self.plan_rel = self.fill(self.code("Step 7", "Run the planner script", startswith="docs/clean/style-plan"))
        self.bash(f"{planner} > {shlex.quote(self.plan_rel)}", "Step 7 Bash plan-style-inspection",
                  "Plan the style inspection, saved")
        self.read(self.plan_rel, "Step 7 Read style plan")
        try:
            self.plan = self.load(self.plan_rel)
        except (OSError, ValueError):
            self.plan = {}
        self.say(f"Style inspection planned: {self.plan.get('agent_count', 0)} agents for "
                 f"{self.plan.get('total_files', 0)} files")
        return bool(self.plan.get("agent_count"))

    def step8(self) -> None:
        o = self.o
        role = self.checklist_role(6) or self.role_in("Step 8")
        bg = re.search(r"`run_in_background:\s*(true|false)`", o.section("Step 8"))
        extra = {"run_in_background": bg.group(1) == "true"} if bg else None
        self.partials = []
        for g in self.plan.get("groups") or []:
            n = g["group_id"]
            lines = []
            for line in self.prompt_block("Step 8", "You are a style-inspector"):
                line = line.replace("{N}", str(n))
                if re.match(r"\s*\d+\.\s+\{file_path_\d+\}", line):
                    if line.lstrip().startswith("1."):
                        lines += [f"{k}. {os.path.relpath(p, self.project) if os.path.isabs(p) else p}"
                                  for k, p in enumerate(g["files"], 1)]
                    continue
                lines.append(line)
            prompt = "\n".join(lines)
            partial = re.search(r"Write your partial report to:\s*(\S+)", prompt).group(1)
            self.partials.append(partial)
            self.dispatch(role, prompt, self.style_work(role, n, g["files"], partial), f"Step 8 Agent({role}) group {n}",
                          extra_input=extra, description=f"Style inspection group {n}")
        self.say(f"Launched {len(self.partials)} style-inspector agents in parallel")

    def style_work(self, role: str, n: int, files: list, partial: str):
        def work(sub, brief, player):
            violations = []
            for p in files:
                full = self.abs(p)
                sub.read(full, label=f"{sub.role} Read group {n} file")
                with self.rp.acting(sub.role):
                    with open(full, encoding="utf-8", errors="replace") as fh:
                        lines = fh.read().split("\n")
                for k, line in enumerate(lines, 1):
                    if re.match(r"\s*python3\s", line):  # standard 3: a bare python3 invocation
                        rel = os.path.relpath(full, self.project)
                        violations.append({"standard": "use-venv-not-python3", "severity": "major",
                                           "location": f"{rel}:{k}",
                                           "finding": "bare python3 invocation",
                                           "recommendation": "run it with the project venv's python",
                                           "old_line": line, "new_line": line.replace("python3", "python", 1)})
            doc = {"request_id": self.rid, "group_id": n,
                   "files_audited": [os.path.relpath(self.abs(p), self.project) for p in files],
                   "violations": violations, "status": "complete"}
            agents.put(sub, self.abs(partial), json.dumps(doc, indent=2) + "\n", f"{sub.role} Write partial report")
            return {"_final": f"Audited {len(files)} files; {len(violations)} violations.\n\nSTATUS: complete"}
        return work

    def step9(self) -> None:
        merged_v, audited = [], []
        for k, rel in enumerate(self.partials, 1):
            self.read(rel, f"Step 9 Read partial {k}")
            try:
                part = self.load(rel)
            except (OSError, ValueError):
                continue
            merged_v += part.get("violations") or []
            audited += [f for f in part.get("files_audited") or [] if f not in audited]
        m = re.search(r"Write the final merged report to\s+`([^`]+)`", self.o.section("Step 9"))
        self.style_rel = self.fill(m.group(1))
        doc = {"request_id": self.rid, "timestamp": utc_now(), "inspector": "style-inspector",
               "violations": merged_v, "files_audited": audited,
               "summary": {"standards_checked": 11, "violations_found": len(merged_v),
                           "critical": sum(1 for v in merged_v if v.get("severity") == "critical"),
                           "files_audited": len(audited), "files_total": self.plan.get("total_files", len(audited)),
                           "rounds_completed": 1}}
        self.audited = audited
        self.write(self.style_rel, json.dumps(doc, indent=2) + "\n", "Step 9 Write style report")

    def step10(self) -> None:
        self.read(self.plan_rel, "Step 10 Read style plan")
        want = [os.path.relpath(self.abs(p), self.project) for p in self.plan.get("all_files") or []]
        missed = [p for p in want if p not in getattr(self, "audited", [])]
        self.say("Coverage verification: " + ("every planned file audited" if not missed else f"missed {missed}"))

    def step10a(self) -> None:
        o = self.o
        role = self.role_in("Step 10A")
        sec = o.section("Step 10A")
        listed = {}
        for key in re.findall(r"`(\w+_files):\s*<every [^`>]+>`", sec):
            pat = re.search(r"`%s:\s*<every ([^`>]+)>`" % key, sec).group(1)
            g = o.s.tool("Glob", {"pattern": pat, "path": self.project}, label=f"Step 10A Glob {key}",
                         deviation=self.devs.at(f"Step 10A Glob {key}"))
            listed[key] = [os.path.relpath(f, self.project) for f in (g.response.get("filenames") or [])] if g.ok else []
        report = self.fill(re.search(r"`(docs/clean/prompt-report-[^`]+)`", sec).group(1))
        ctx = self.fill(re.search(r"`(docs/clean/context-[^`]+)`", sec).group(1))
        block = re.search(r"`(<obligation v=\"1\">\{.*?\}</obligation>)`", sec)
        prompt = o.instantiate("\n".join(
            [f"Context file: {ctx}"] + [f"{k}: {' '.join(v) if v else '(none)'}" for k, v in listed.items()]
            + ([self.fill(block.group(1))] if block else []) + [f"Write your report to: {report}"]), None)
        self.prompt_rel = report
        files = [f for v in listed.values() for f in v]

        def work(sub, brief, player):
            for f in files:
                sub.read(self.abs(f), label=f"{sub.role} Read {f}")
            doc = {"request_id": self.rid, "timestamp": utc_now(), "inspector": role, "baseline_check": "not_provided",
                   "findings": [], "audited_files": files,
                   "codex_consult": {"invoked": False, "status": "not_requested", "findings": [],
                                     "feedback_summary": None, "feedback_incorporated": None},
                   "summary": {"files_inspected": len(files), "files_with_violations": 0, "critical": 0, "major": 0,
                               "minor": 0, "total_verbose_lines": 0, "estimated_reduction": "0%"}}
            self.reports[report] = json.dumps(doc, indent=2) + "\n"
            agents.put(sub, self.abs(report), self.reports[report], f"{sub.role} Write report")
            return {"status": "complete", "report": report, "findings": 0}
        self.dispatch(role, prompt, work, f"Step 10A Agent({role})", report=report)
        self.read(report, "Step 10A Read prompt report")

    # ------------------------------------------------------------ Steps 11-15
    def step11(self) -> bool:
        o = self.o
        call = self.fill(self.code("Step 11", "clean-merge-reports", contains="clean-merge-reports"))
        ctx_arg = call.split()[-1]
        combined_rel = self.fill(re.search(r"`(docs/clean/combined-report-[^`]+)`", o.section("Step 11")).group(1))
        self.combined_rel = combined_rel
        if not os.path.exists(self.abs(ctx_arg)) and self.gaps == "bridged":
            # C1: the context the merge reads, which no step creates: the context and the three reports
            # under the keys the helper reads.
            self.bridge_context(ctx_arg, "Step 11 Bash context-with-reports")
        c = self.bash(call, "Step 11 Bash clean-merge-reports", "Merge the inspection reports")
        if not c.ok:
            self.ended = "Step 11: the merge failed"
            return False
        out = _json_out(c.response.get("stdout", "")) or {}
        produced = out.get("combined_report", "")
        amend = o.has("Step 11", "MUST add the prompt report")
        if amend or (produced and os.path.abspath(produced) != self.abs(combined_rel)):
            if self.gaps != "bridged":
                self.ended = "Step 11: the combined report is not where the later steps read it"
                return False
            # C2: the text's amendment (the prompt report added as top-level prompt_report and its findings
            # counted), written where Steps 12-16 read the combined report.
            label = "Step 11 Bash amend combined report"
            jq = ("jq --slurpfile p " + shlex.quote(self.prompt_rel) +
                  " '. + {prompt_report: $p[0]} | .combined_summary.total_issues = "
                  "((.combined_summary.total_issues // 0) + ($p[0].findings // [] | length))' "
                  + shlex.quote(produced) + " > " + shlex.quote(combined_rel))
            self.respelled("C2 combined-report path", "commands/clean.md Step 11 (:333-339 at 2acc29b)", label)
            if not self.bash(jq, label, "Add the prompt report to the combined JSON").ok:
                self.ended = "Step 11: the combined report could not be amended"
                return False
        return True

    def bridge_context(self, rel: str, label: str) -> None:
        self.respelled("C1 context-with-reports", "commands/clean.md Steps 11, 15, 16 (:333, :482, :506 at 2acc29b)",
                       label)
        q = shlex.quote
        self.bash(f"jq -s '.[0] * {{cleanliness_report: .[1], style_report: .[2], prompt_report: .[3]}}' "
                  f"{q(self.context_rel)} {q(self.cleanliness_rel)} {q(self.style_rel)} {q(self.prompt_rel)} > {q(rel)}",
                  label, "The context with the three inspection reports")

    def step12(self) -> None:
        self.read(self.combined_rel, "Step 12 Read combined report")
        comb = self.load(self.combined_rel)
        self.combined = comb
        md = cmdtext.block(self.o.text, "Step 12", lang="markdown")
        self.options = re.findall(r"^\d+\.\s+(.+)$", md.split("## Cleanup Options", 1)[-1], re.M)
        self.say(self.report_text(md, comb))

    def findings(self, comb: dict) -> list:
        """(source report, index, finding) in the order Step 13's procedure lists them."""
        out = []
        c = (comb.get("cleanliness_report") or {}).get("findings") or {}
        for k, v in c.items():
            if isinstance(v, list):
                out += [("cleanliness", i, f) for i, f in enumerate(v)]
        out += [("style", i, f) for i, f in enumerate((comb.get("style_report") or {}).get("violations") or [])]
        out += [("prompt", i, f) for i, f in enumerate((comb.get("prompt_report") or {}).get("findings") or [])]
        return out

    def report_text(self, md: str, comb: dict) -> str:
        items = self.findings(comb)
        lines = [l for l in md.split("\n") if not l.startswith("- <")]
        body = "\n".join(lines).replace("<project_name>", os.path.basename(self.project)).replace(
            "<project_type>", (self.facts.get("scan") or {}).get("project_type", "Generic")).replace("<timestamp>", self.ts)
        return body + "\n\nFindings:\n" + "\n".join(
            f"- [{src}] {f.get('file') or f.get('location')}: {f.get('reason') or f.get('finding')}" for src, _, f in items)

    def step13(self) -> bool:
        o = self.o
        opts = [{"label": t[:60], "description": t} for t in self.options] or [{"label": "Execute all", "description": ""}]
        tin = {"questions": [{"question": "Which cleanup option?", "header": "Cleanup", "options": opts,
                              "multiSelect": False}]}
        call = o.s.tool("AskUserQuestion", tin, label="Step 13 AskUserQuestion",
                        deviation=self.devs.at("Step 13 AskUserQuestion"))
        ans = (call.response.get("answers") or {}).get("Which cleanup option?", "")
        if not ans.startswith(opts[0]["label"][:20]):
            self.ended = f"Step 13: the owner chose {ans!r}"
            return False
        self.read(self.combined_rel, "Step 13 Read combined report")
        comb = self.load(self.combined_rel)
        approved = []
        for k, (src, i, f) in enumerate(self.findings(comb), 1):
            # a prompt finding is `fix_style` (item 2); a style violation, the cleaner's own name for a fix
            action = "fix_style" if src in ("style", "prompt") else _action(f)
            entry = {"action_id": f"finding_{k}", "source_report": src, "source_finding_index": i, "action": action,
                     "description": f.get("reason") or f.get("finding") or f.get("recommendation", ""),
                     "location": f.get("location") or f.get("file", ""), "approved": True}
            for key in ("destination", "old_line", "new_line", "file"):
                if key in f:
                    entry[key] = f[key]
            approved.append(entry)
        total = (comb.get("combined_summary") or comb.get("summary") or {}).get("total_issues", len(approved))
        if total != len(approved):
            self.ended = f"Step 13: {len(approved)} approved actions for {total} findings"
            return False
        doc = {"request_id": self.rid, "timestamp": utc_now(), "mode": "execute_all",
               "user_approvals": {"total_issues_in_report": total, "total_approved_actions": len(approved),
                                  "approved_actions": approved, "rejected_actions": []}}
        self.approvals_rel = self.save_path("Step 13")
        self.write(self.approvals_rel, json.dumps(doc, indent=2) + "\n", "Step 13 Write user approvals")
        return True

    def step14(self) -> bool:
        self.read(self.combined_rel, "Step 14 Read combined report")
        self.read(self.approvals_rel, "Step 14 Read user approvals")
        comb, appr = self.load(self.combined_rel), self.load(self.approvals_rel)
        total = (comb.get("combined_summary") or comb.get("summary") or {}).get("total_issues")
        n = (appr.get("user_approvals") or {}).get("total_approved_actions")
        if total != n:
            self.ended = f"COMPLETENESS GATE FAILED: {n} of {total}"
            return False
        self.say(f"Completeness gate PASSED: {n} approved actions match {total} combined report findings")
        return True

    def step15(self) -> None:
        o = self.o
        hook = self.code("Step 15", "checkpoint.sh", startswith="bash ")
        self.bash(hook, "Step 15 Bash checkpoint", "Create the safety checkpoint")
        # "read `refs/checkpoints/<branch>`": the branch Step 3 recorded
        ref = self.code("Step 15", "checkpoint.sh", startswith="refs/checkpoints/").replace(
            "<branch>", self.facts.get("branch") or "master")
        c = self.bash(f"git rev-parse {shlex.quote(ref)}", "Step 15 Bash checkpoint ref", "Read the checkpoint ref")
        self.checkpoint = c.response.get("stdout", "").strip() if c.ok else ""
        o.values["CHECKPOINT_COMMIT"] = self.checkpoint
        rec = self.fill(self.code("Step 15", "checkpoint.sh", contains="record-checkpoint"))
        c = self.bash(rec, "Step 15 Bash record-checkpoint", "Record the checkpoint commit")
        out = (_json_out(c.response.get("stdout", "")) or {}) if c.ok else {}
        self.checkpoint = out.get("checkpoint_commit") or self.checkpoint

    # ------------------------------------------------------------ Step 16: the cleaner
    def step16(self) -> None:
        o = self.o
        block = next(b for _n, b, _p in o.step_blocks("Step 16") if "context-with-approvals" in b.text)
        text = self.fill(block.text)
        text = re.sub(r"<checkpoint_commit from Step 15>", self.checkpoint, text)
        self.bash(text, "Step 16 Bash context-with-approvals", "Merge the approvals into the cleaner's context")
        inv = cmdtext.block(o.text, "Step 16", anchor="Agent tool invocation:")
        m = re.search(r'prompt:\s*"(.*)"\s*$', inv.rstrip("\n"), re.S)
        prompt = self.fill(m.group(1))
        role = self.checklist_role(16) or self.role_in("Step 16")
        self.dispatch(role, prompt, self.cleaner_work(role, prompt), f"Step 16 Agent({role})",
                      description="Execute approved cleanup actions")

    def cleaner_work(self, role: str, prompt: str):
        o = self.o
        text = o.tree.agent_text(role)
        q = shlex.quote

        def work(sub, brief, player):
            out_rel = re.search(r"Write results to\s+(\S+?\.json)", prompt).group(1)
            ctx_rel = re.search(r"is at:\s*(\S+?\.json)", prompt).group(1)
            for rel in re.findall(r"^\s*-\s+[\w ]+:\s*(docs/clean/\S+?\.json)\s*$", prompt, re.M):
                if os.path.isfile(self.abs(rel)):
                    sub.read(self.abs(rel), label=f"{sub.role} Read {os.path.basename(rel).split('-' + self.rid)[0]}")
            ctx = json.loads(agents.peek(self.rp, sub.role, self.abs(ctx_rel)))
            safety = next(c for c in cmdtext.inline_codes(text, "1. Safety First", "Verify git checkpoint")
                          if c.startswith("git "))
            sub.bash(safety, "Verify the git checkpoint", label=f"{sub.role} Bash checkpoint check")
            table = {}
            for line in cmdtext.section(text, "2. Action Types").split("\n"):
                m = re.match(r"\|\s*\*\*(\w+)\*\*\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|", line)
                if m:
                    table[m.group(1)] = (m.group(2), m.group(3))
            order = [l for l in re.findall(r"^\d+\.\s+(.+)$", cmdtext.section(text, "3. Execution Order"), re.M)]
            actions = [a for a in (ctx.get("user_approvals") or {}).get("approved_actions") or [] if a.get("approved")]
            rank = {"rename": 0, "move": 1, "archive": 2, "fix_style": 3, "delete": 4, "update_gitignore": 5,
                    "generate_index": 6}
            if len(order) != len(rank):
                raise agents.PlayError(f"agents/{role}.md's execution order has {len(order)} items")
            done, skipped, failed, staged = [], [], [], []
            for a in sorted(actions, key=lambda a: rank.get(a.get("action"), 99)):
                kind = a.get("action")
                if kind not in table:
                    skipped.append(dict(a, result="skipped", reason=f"no operation for action {kind!r}"))
                    continue
                if kind in ("move", "archive", "rename"):
                    src, dst = a.get("file") or a.get("location"), a.get("destination")
                    if not dst or not os.path.exists(self.abs(src)):
                        skipped.append(dict(a, result="skipped", reason="source or destination missing"))
                        continue
                    c = sub.bash(f"mkdir -p {q(os.path.dirname(dst) or '.')} && mv {q(src)} {q(dst)}",
                                 f"{kind} {src}", label=f"{sub.role} Bash {kind} {a['action_id']}")
                    affected = [src, dst]
                elif kind == "fix_style":
                    rel = (a.get("location") or "").rsplit(":", 1)[0]
                    if not a.get("old_line") or not os.path.isfile(self.abs(rel)):
                        skipped.append(dict(a, result="skipped", reason="no replacement line"))
                        continue
                    sub.read(self.abs(rel), label=f"{sub.role} Read {a['action_id']}")
                    c = sub.edit(self.abs(rel), a["old_line"], a["new_line"], label=f"{sub.role} Edit {a['action_id']}")
                    affected = [rel]
                else:
                    cmd = re.search(r"`([^`]+)`", table[kind][0])
                    if not cmd:
                        skipped.append(dict(a, result="skipped", reason="no command"))
                        continue
                    c = sub.bash(cmd.group(1).replace('"$PROJECT_ROOT', '"' + self.project), kind,
                                 label=f"{sub.role} Bash {a['action_id']}")
                    affected = []
                if c.ok:
                    done.append(dict(a, result="success", git_staged=bool(affected)))
                    staged += [p for p in affected if p not in staged]
                else:
                    failed.append(dict(a, result="failed", error=(c.error or "refused")[:200]))
                if affected:
                    sub.bash("git add -A -- " + " ".join(q(p) for p in affected), "Stage the affected files",
                             label=f"{sub.role} Bash git add {a['action_id']}")
            commit_sha = ""
            if staged:
                tpl = next(b.text for b in cmdtext.blocks(text, "5. Git Operations") if "cleanup:" in b.text)
                subject, _, body = tpl.strip("\n").partition("\n")
                moved = sum(1 for a in done if a.get("action") == "move")
                body = body.strip().replace("X files", f"{moved} files").replace("Y files", "0 files").replace(
                    "Z files", "0 files").replace("W violations", f"{sum(1 for a in done if a.get('action') == 'fix_style')} violations")
                c = sub.bash(f"git commit -q -m {q(subject)} -m {q(body)}", "Commit the cleanup",
                             label=f"{sub.role} Bash commit")
                if c.ok:
                    r = sub.bash("git rev-parse --show-toplevel\ngit branch --show-current\ngit rev-parse HEAD",
                                 "The commit's repository, branch and sha", label=f"{sub.role} Bash commit descriptor")
                    vals = (r.response.get("stdout", "") if r.ok else "").split("\n")
                    if len(vals) >= 3 and vals[2].strip():
                        commit_sha = vals[2].strip()
                        self.token(sub, text, vals[0].strip(), vals[1].strip(), commit_sha)
            status = "completed" if not failed else "partial"
            doc = {"request_id": self.rid, "timestamp": utc_now(), "cleaner": {
                "status": status, "actions_completed": done, "actions_failed": failed, "actions_skipped": skipped,
                "summary": {"total_actions": len(actions), "successful": len(done), "failed": len(failed),
                            "skipped": len(skipped), "files_moved": sum(1 for a in done if a.get("action") == "move"),
                            "files_archived": 0, "files_deleted": 0, "files_renamed": 0,
                            "style_fixes": sum(1 for a in done if a.get("action") == "fix_style"), "index_generated": False},
                "git_status": {"checkpoint_commit": (ctx.get("orchestrator") or {}).get("analysis", {}).get(
                    "checkpoint_commit", self.checkpoint), "cleanup_commit": commit_sha,
                    "files_staged": len(staged), "ready_for_review": bool(commit_sha)}}}
            agents.put(sub, self.abs(out_rel), json.dumps(doc, indent=2) + "\n", f"{sub.role} Write execution report")
            self.execution_rel = out_rel
            self.cleaner_result = doc["cleaner"]
            return doc
        return work

    def token(self, sub, text: str, root: str, branch: str, sha: str) -> None:
        """The push-gate token as the agent text writes it."""
        sec = cmdtext.section(text, "5. Git Operations")
        blocks = [b.text for b in cmdtext.blocks(sec, None, "bash") if "write-push-gate-token" in b.text]
        if blocks:
            cmd = blocks[0].replace("<GIT_ROOT>", root).replace("<BRANCH>", branch).replace("<COMMIT_SHA>", sha)
            sub.bash(cmd, "Write the push-gate token", label=f"{sub.role} Bash push-gate token")
            return
        # The base text's prose: GIT_ROOT, BRANCH, COMMIT_SHA exported, then "a Python script" that computes the
        # repo hash and the session digest, the token dir the text gives, and writes the token unless another
        # session's token is there. "activate the venv": none in a product repository (E5 (b)).
        para = next(p for p in re.split(r"\n\s*\n", sec) if "repo_hash" in p and "token_dir" in p)
        tdir = re.search(r"`token_dir = (/[^`]+)`", para).group(1)
        tdir = tdir.replace("<repo_hash>", "{rh}").replace("<session_digest>", "{sd}")
        script = ("import hashlib,json,os\n"
                  "root=os.environ['GIT_ROOT']; branch=os.environ['BRANCH']; sha=os.environ['COMMIT_SHA']\n"
                  "rh=hashlib.sha256(os.path.realpath(root).encode()).hexdigest()[:16]\n"
                  "sid=os.environ.get('CLAUDE_CODE_SESSION_ID') or os.environ.get('CLAUDE_SESSION_ID') or 'unknown'\n"
                  "sd=hashlib.sha256(sid.encode()).hexdigest()[:16]\n"
                  f"d=f\"{tdir}\"\nos.makedirs(d,exist_ok=True)\n"
                  "p=os.path.join(d,branch.replace('/','__')+'.json')\n"
                  "old=json.load(open(p)) if os.path.exists(p) else None\n"
                  "if old and old.get('session_id')!=sid:\n    print('WARNING: token of another session at '+p)\n"
                  "else:\n    json.dump({'commit_sha':sha,'branch':branch,'repo_root':root,'session_id':sid},open(p,'w'))\n"
                  "    print(p)\n")
        label = f"{sub.role} Bash push-gate token"
        self.respelled("C3 token venv", "agents/cleaner.md Git Operations (:111 at 2acc29b)", label)
        sub.bash(f"export GIT_ROOT={shlex.quote(root)} BRANCH={shlex.quote(branch)} COMMIT_SHA={shlex.quote(sha)}\n"
                 f"python3 -c {shlex.quote(script)}", "Write the push-gate token", label=label)

    # ------------------------------------------------------------ Steps 17-18
    def step17(self) -> None:
        for k, c in enumerate([cmd for cmd in self.codes("Step 17", "Review git changes") if cmd.startswith("git ")], 1):
            self.bash(c, f"Step 17 Bash git {k}", "Review the cleanup's git changes")
        r = getattr(self, "cleaner_result", {}) or {}
        s = r.get("summary") or {}
        self.say(f"# Cleanup Execution Results\n\n**Status**: {r.get('status', 'blocked')}\n**Actions**: "
                 f"{s.get('successful', 0)} successful, {s.get('failed', 0)} failed, {s.get('skipped', 0)} skipped\n\n"
                 f"- Checkpoint commit: {self.checkpoint}\n- Cleanup commit: "
                 f"{(r.get('git_status') or {}).get('cleanup_commit', '')}")

    def step18(self) -> None:
        tpl = cmdtext.block(self.o.text, "Step 18", lang="markdown")
        r = getattr(self, "cleaner_result", {}) or {}
        g = r.get("git_status") or {}
        text = self.fill(tpl).replace("clean-YYYYMMDD-HHMMSS", self.rid)
        for k, v in (("<project_path>", self.project), ("<project_type>", (self.facts.get("scan") or {}).get(
                "project_type", "Generic")), ("<timestamp>", utc_now()), ("<completed|partial|blocked>", r.get("status", "blocked")),
                ("<checkpoint_commit>", self.checkpoint), ("<branch>", self.facts.get("branch", ""))):
            text = text.replace(k, v)
        text = text.replace("Checkpoint commit: <hash>", f"Checkpoint commit: {self.checkpoint}").replace(
            "Cleanup commit: <hash>", f"Cleanup commit: {g.get('cleanup_commit', '')}")
        text = re.sub(r"<list of [^>]+>", "(see the execution report)", text)
        self.write(self.save_path("Step 18"), text, "Step 18 Write completion report")

    # ------------------------------------------------------------ the run
    def stop(self) -> None:
        r = getattr(self, "cleaner_result", {}) or {}
        if self.ended:
            text = f"/clean {self.rid}: stopped. {self.ended}."
        else:
            text = (f"/clean {self.rid} complete: {r.get('summary', {}).get('successful', 0)} actions executed, "
                    f"cleanup commit {(r.get('git_status') or {}).get('cleanup_commit', '')}. "
                    "To publish to the remote: /push")
        self.o.s.stop(text, label="Stop", deviation=self.devs.at("Stop"))

    def run(self) -> None:
        self.step1()
        self.to(2); self.step2()
        self.to(3); self.step3()
        self.to(4); self.step4()
        self.to(5); self.step5()
        self.to(6)   # Step 6's own text is the heading of Steps 7-10: no call of its own
        self.to(7)
        if self.step7():
            self.to(8); self.step8()
            self.to(9); self.step9()
            self.to(10); self.step10()
            self.step10a()   # no checklist item: made while Step 10 is in progress
        self.to(11)
        if not self.step11():
            return self.stop()
        self.to(12); self.step12()
        self.to(13)
        if not self.step13():
            return self.stop()
        self.to(14)
        if not self.step14():
            return self.stop()
        self.to(15); self.step15()
        self.to(16); self.step16()
        self.to(17); self.step17()
        self.to(18); self.step18()
        self.o.advance()
        self.stop()


def run(rp) -> None:
    CleanRun(rp, rp.args.get("gaps", "bridged"), rp.args.get("fault", "")).run()
