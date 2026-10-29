"""/dev-overnight, played compliantly from commands/dev-overnight.md of the tree under test: two cycles of
a 2-pipeline session (P1b acceptance 4, E13), and the owner's /stop (commands/stop.md).

Before the session the owner points origin/HEAD at the protected branch and checks out a working
branch (the in-place launch refuses a checkout on the protected branch or with no origin/HEAD, as
the Arguments section says); that setup is the owner's, outside any session, so no hook sees it.
Then, in one session, the main agent:

* types `/dev-overnight <end-time> <focus>` (in place: no --worktree); the UserPromptSubmit hook's
  launcher writes the state record; the checklist the hook hands over (checked against
  scripts/todo/dev-overnight.py) goes to the first TodoWrite and one step is completed per
  TodoWrite call;
* Step 1: lists the state records (Glob), reads its own, runs the SESSION BINDING + ONE-CALL
  INITIALIZATION block as one Bash call (values bound from its KEY=VALUE output and the
  variables it sets), the WORKING-ROOT GUARD's `cd`, the announcement;
* each cycle, as the tree's text says, read at run time:
  - Step 2: PM PLAN from the step's template (its obligation instantiated where the template has
    one), the plan Read, the priority context built from it;
  - Step 3: the specialists the plan's recommended_specialists narrow the exploration-mode set to,
    one at a time, each prompt built from the text's bullet list ("Each subagent receives ..."),
    the report validation the text asks for (the base's check-overnight-reports.sh and its sanity
    Reads), the core-flow gate Read of the user report;
  - Step 4: the cycle number as the text reads it (`overnight.py cycle-index <STATE_FILE>`, or the
    state record's cycle_count), PM TRIAGE from the template, the pipeline_blocked Read; on a text
    with the "Cycle Contract Manifest" (the base), the orchestrator's contract: its primary and
    mirror Writes and the cycle-current.json symlink, its fields from the section's bullets, its
    BA/dev/QA/graphify entries from the section's inline examples, the entries of the other
    dispatches the cycle commits to from those dispatches' own templates;
  - Step 5: the template Read and one spec copy per pipeline, the text's replacements made;
  - Step 6: the pipeline builder block; Step 7: the focus criteria;
  - Step 8 per pipeline: the pre-BA retry signals (Four Contracts Awareness), the graphify
    hydrator block, BA from the step's Agent(...) block; Step 9: the BA outputs Read;
  - Step 10 per pipeline: the block's pre-dispatch shell lines (the base's qa_mode flip), QA in
    BA-validation mode, the report Read; Step 11: no objection, nothing to iterate;
  - Steps 11g/12 per pipeline: Step 11g in_progress, graphify from the 11g template, its run
    record Read, Step 12 in_progress again, dev; Step 13: the dev reports Read;
  - Step 14: the docker-compose lookup (none: nothing to rebuild), the base's QA verification
    plans Write; Step 15 per pipeline: pre-dispatch shell lines, QA final verification;
    Step 16: the QA reports Read; Step 17: every pipeline passed, nothing to iterate;
  - Step 18: the permissions block; Step 19: the cycle log, the TIME CHECK, the per-cycle commit
    (its failure logged); Step 20: PM RETRO, the retro Read; Step 21: marked completed, the loop
    hook's reset (a fresh checklist, Step 1 done, Step 2 in progress);
* the owner interrupts and types /stop; the main agent runs stop.md's Implementation block once
  and stops.

Subagents are played by agents.Player: PM (PLAN, TRIAGE, RETRO), the specialists, BA, QA, graphify
and dev, each from its dispatch prompt and its agent file (roles.py for dev's and QA's work). Where
a dispatch's obligation declares its report (the working tree's PM and specialist templates), the
Player writes it from the schema; where none does (the base's), the role writes the file its
prompt's "Output ... to:" / "Write ... to:" line names, with the same content. On the base text the
subagents also write the overnight spec sections their prompts tell them to update.

The scenario: cycle 1's specialists find toy.add and toy.util.sub accepting non-numbers (dev.py's
two scenarios), cycle 2's a README with no usage line and a package that does not export sub; PM
triages each pair into two `fix` pipelines; BA-QA and QA pass every pipeline.

Driver arguments (cli.py --arg K=V):
  variant=plain   two cycles, then the owner's /stop inside cycle 3's window (default)
  variant=stop    the owner's /stop inside cycle 1's window, once Step `stop_at` (default 12) is done
  stop_at=N       the step after which variant=stop interrupts
  kit=base        the replay of the base kit's text: row 7's respellings below are applied
  kept=<JSON>     [[hook, step, normalised text], ...]: a declared deviation passes only a block in
                  that list (drivers/dev.py KeptOnly); without it every declared deviation passes
  until=N         development aid only (not a compliant replay): end after cycle 1's Step N

Respellings (row 7), driver only, each application recorded in blocks.json "respellings":
drivers/dev.py's list, applied only where the text still has the old form (the /dev-overnight text
of either tree has none of those forms), and, in a replay of the base kit's text (kit=base),
STOP_RESPELLINGS below: /stop's wrapper call, whose failure (it unlocks nothing) leaves the
time-lock refusing the session's end. Step 19's repository-relative `scripts/commit.sh` is not
respelled: the text logs its failure and goes on (row 7 respells only a call whose failure ends the
replay short of its terminal); nor are the agents' blast-radius tool calls (row 7: left to TC-44).

Deviations: DEVIATIONS below, one entry per block the base tree's (2acc29b) replay meets, each with
a comment quoting the hook's text; nothing else passes a block.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass, field

from .. import agents, cmdtext, roles, schemagen
from ..pipeline import Deviations, Orchestrator, Respelling, utc_now
from ..replay import Deviation
from . import dev as devdrv

PIPELINE = "dev-overnight"
FOCUS = "harden the toy package's public functions"
END_TIME = "8h"
WORK_BRANCH = "night-work"

# Blocks the base tree's replay meets, each passed by a deviation at the step it occurs on: the
# refused call is applied as if allowed, so every later step runs and is traced.
DEVIATIONS = Deviations([
    # DEVIATION: "BLOCKED: removal-policy — UNRESOLVED census_fatal:unbalanced:single_quote"
    # pretool-bash-safety.sh refuses Step 1's SESSION BINDING + ONE-CALL INITIALIZATION block (the
    # apostrophes of its comments, "session's").
    ("C* Step 1 Bash session binding + init", Deviation(
        "hooks/pretool-bash-safety.sh", "UNRESOLVED census_fatal:unbalanced:single_quote",
        "Step 1's binding block as the text spells it")),
    # DEVIATION: "BLOCKED: removal-policy — UNRESOLVED census_fatal:unbalanced:single_quote"
    # The same refusal of the base text's qa_mode flip before each QA dispatch (the apostrophe of its
    # comment, "hook's").
    ("C* Step 1[05] Bash qa_mode *", Deviation(
        "hooks/pretool-bash-safety.sh", "UNRESOLVED census_fatal:unbalanced:single_quote",
        "the base text's qa_mode flip as it spells it")),
    # DEVIATION: "CONTRACT BLOCK (pretool-subagent-enforce): ... no required_calls entry for step '2'"
    # The launcher's seed contract (required_calls: []) switches the hook into enforce mode, so the
    # dispatches the text makes before its own contract exists (PM PLAN, the specialists, PM TRIAGE)
    # are refused (E13).
    ("C* Step [234] Agent(*", Deviation(
        "hooks/pretool-subagent-enforce.py", "CONTRACT BLOCK (pretool-subagent-enforce)",
        "the Steps 2-4 dispatches the text makes before its contract exists")),
    # DEVIATION: "OVERNIGHT FILE CHECK BLOCK (contract): ... projection dev-report.v1: flat field
    # 'report_version' must be literal integer 1 ..." posttool-overnight-file-check.py checks each
    # collected report against the contract entry's schema_name, which the base text's manifest
    # example names v1 while the dispatch's own obligation names v2 (E13).
    ("C* Step 1[25] Agent(*", Deviation(
        "hooks/posttool-overnight-file-check.py", "OVERNIGHT FILE CHECK BLOCK (contract)",
        "the dev / QA report its obligation declares, collected")),
    # DEVIATION: "BLOCKED Agent dispatch (qa): canonical aggregate dev-report missing. ... per-worker
    # reports present: 0, 1 ..." pretool-aggregate-check.py reads the pipelines' dev reports
    # (dev-report-<ts>-0/-1, one Step 6 timestamp) as a fan-out's lane reports and refuses QA.
    ("C* Step 15 Agent(qa) *", Deviation(
        "hooks/pretool-aggregate-check.py", "canonical aggregate dev-report missing",
        "Step 15's QA dispatch of an overnight pipeline")),
    # DEVIATION: "OVERNIGHT WRITE-BOUNDARY FAIL-CLOSED: the per-command bwrap RO-bind boundary that
    # guarantees the main working tree is never written in place is UNAVAILABLE (bubblewrap / user
    # namespace missing) ..." pretool-overnight-hook-guard.py refuses every Bash call of the session
    # (main agent's and subagents') that writes, in place, while the sandbox has no bubblewrap.
    ("*Bash*", Deviation(
        "hooks/pretool-overnight-hook-guard.py", "OVERNIGHT WRITE-BOUNDARY FAIL-CLOSED",
        "a Bash call the text makes, in an in-place session on a host without bubblewrap")),
    # DEVIATION: "OVERNIGHT SUBPROCESS GIT BLOCK: an interpreter/subprocess that could run a
    # main-targeting git op ... is forbidden for overnight actors." The same guard refuses the
    # text's interpreter calls (Step 6's pipeline builder, a python3 script).
    ("*Bash*", Deviation(
        "hooks/pretool-overnight-hook-guard.py", "OVERNIGHT SUBPROCESS GIT BLOCK",
        "a harness script the text runs through python3")),
    # DEVIATION: "[Orchestrator Gate] BLOCKED: Bash used consecutively beyond limit (n/5)."
    ("*Bash*", Deviation(
        "hooks/pretool-orchestrator-gate.py", "Bash used consecutively beyond limit",
        "the text's own run of Bash calls between two dispatches")),
    # DEVIATION: "[Orchestrator Gate] BLOCKED: Write used consecutively beyond limit (n/1)." and the
    # same for Edit: the gate allows the main agent one Write and one Edit per turn, and the whole
    # overnight session is one turn while the text has the orchestrator write a spec copy per
    # pipeline, the cycle log each cycle (and, on the base text, the cycle contract).
    ("*Write*", Deviation(
        "hooks/pretool-orchestrator-gate.py", "Write used consecutively beyond limit",
        "an orchestrator write the text asks for after the turn's first Write")),
    ("*Edit*", Deviation(
        "hooks/pretool-orchestrator-gate.py", "Edit used consecutively beyond limit",
        "an orchestrator edit the text asks for after the turn's first Edit")),
    # DEVIATION: "failed_phase=timelock ... CLOSEOUT GATE: final overnight artifacts are incomplete."
    # (or "... cycle still has unresolved required_calls."): after /stop backdates the end time, the
    # time-lock's closeout rule (landscape B2.b, P2 row 9's) refuses the main agent's Stop on state
    # fields no session step writes.
    ("/stop Stop", Deviation(
        "hooks/stop-workflow-coordinator.py", "CLOSEOUT GATE",
        "the main agent's Stop after the owner's /stop")),
])


# Row 7 respellings of the base text's own calls whose failure in a product repository ends the
# replay short of its terminal, applied in a replay of the base kit's text only (kit=base):
#   R5 stop wrapper  `bash ~/.claude/hooks/stop.sh` (commands/stop.md, Implementation) gains the
#                    CLAUDE_PROJECT_DIR prefix: break-overnight-lock.py finds the project only through
#                    that variable (hooks/lib/claude_home.py project_dir, else the harness home), which
#                    the CLI's Bash does not export (E5), so /stop unlocks nothing and the time-lock
#                    keeps the session from ending.
STOP_RESPELLINGS = [
    Respelling("R5 stop wrapper", r"(?<![\w=\"] )(?<![\w=])bash ~/\.claude/hooks/stop\.sh",
               devdrv.PROJECT_ROOT_PREFIX + "bash ~/.claude/hooks/stop.sh", "commands/stop.md Implementation"),
]


# ---------------------------------------------------------------- the scenario

SCENARIO_EXPORT = devdrv.Scenario(
    "export toy.util.sub from the toy package: `from toy import sub` raises ImportError",
    "toy/__init__.py", "def add(a, b):\n", "from toy.util import sub\n\n\ndef add(a, b):\n",
    "from toy.util import sub  # noqa: F401  (re-exported)\n\n\ndef add(a, b):\n",
    {"id": "AC-01", "type": "api", "given": "the toy package", "when": "sub is imported from toy",
     "then": "the import succeeds and sub(3, 1) returns 2", "check": {"call": "from toy import sub; sub(3, 1)",
                                                                     "returns": 2}},
    "import os, sys\nsys.path.insert(0, os.getcwd())\nfrom toy import sub\nassert sub(3, 1) == 2",
    what="sub re-exported from the toy package", why="the package exports add but not sub",
    symptom="`from toy import sub` raises ImportError", root_cause="toy/__init__.py does not import sub",
    keyword="toy.sub", title="export sub from toy", measured="from toy import sub -> ImportError",
    before="`from toy import sub` raised ImportError", ba_summary="toy re-exports sub",
    dev_summary="toy/__init__.py re-exports sub", objection=devdrv.BA_QA_OBJECTION, qa_failure=devdrv.QA_FAILURE,
    question=devdrv.QUESTION, no_e2e="no user-facing surface: a package import")

# What each cycle's specialists find, one pipeline each (dev.py's scenarios plus the export one).
CYCLE_SCENARIOS = {1: (devdrv.SCENARIO, devdrv.SCENARIO_SUB), 2: (devdrv.SCENARIO_README, SCENARIO_EXPORT)}
# The specialists PM PLAN recommends (the rest of agent_assignments not called this cycle).
CALLED = {"architect": "code review of the package's two modules", "user": "the core flow: import toy, call add"}
SKIPPED = {"product-owner": "the README is the only product document; the architect covers it",
           "ui-specialist": "a library package: no user interface"}


def _issue(sc: devdrv.Scenario, k: int, role: str) -> dict:
    return {"id": f"{role[:4]}-{k}", "title": sc.title, "description": sc.symptom, "severity": "major",
            "location": {"file": sc.rel, "line": 1, "url": None}, "category": "input-validation",
            "estimated_effort": "small", "measured": sc.measured, "expected": sc.ac["then"],
            "observation_notes": sc.before}


# ---------------------------------------------------------------- dispatch text helpers

_AGENT_LINE = re.compile(r'^\s*Agent\(subagent_type:\s*"?([\w.-]+)"?\)\s*$')


def agent_block(text: str) -> dict:
    """The fields of a fenced `Agent(subagent_type: "x")` block: subagent_type, description, prompt (a
    value of a lone `"` runs to a line `"`), and `pre`, the lines before the Agent( line after the
    block's last "For each ...:" line (the shell the text runs before each dispatch, if any)."""
    lines = text.split("\n")
    at = next((i for i, l in enumerate(lines) if _AGENT_LINE.match(l)), None)
    if at is None:
        raise cmdtext.TextNotFound("no Agent(subagent_type: ...) line")
    head = lines[:at]
    last_for = max((i for i, l in enumerate(head) if l.rstrip().endswith(":")), default=-1)
    pre = "\n".join(head[last_for + 1:]).strip("\n")
    shell = pre if any(l.strip() and not l.lstrip().startswith("#") for l in pre.split("\n")) else ""
    fields, i = {"subagent_type": _AGENT_LINE.match(lines[at]).group(1), "pre": shell}, at + 1
    while i < len(lines):
        m = re.match(r"^\s+(\w+):\s*(.*)$", lines[i])
        if not m:
            i += 1
            continue
        key, val = m.group(1), m.group(2).rstrip()
        if val == '"':
            body, i = [], i + 1
            while i < len(lines) and lines[i].strip() != '"':
                body.append(lines[i])
                i += 1
            ind = min((len(l) - len(l.lstrip()) for l in body if l.strip()), default=0)
            fields[key] = "\n".join(l[ind:] for l in body).strip("\n")
        else:
            fields[key] = val[1:-1] if len(val) >= 2 and val[0] == val[-1] == '"' else val
        i += 1
    if "prompt" not in fields:
        raise cmdtext.TextNotFound("Agent(...) block has no prompt")
    return fields


_IF_RE = re.compile(r"^\s*<If (.+?), include:>\s*$")
_PARA_STOP = re.compile(r"^\s*(?:<If |You are |Write |[A-Z][A-Za-z ]*: \S)")


def conditional_paragraphs(prompt: str, truth) -> str:
    """Resolve the template's `<If <condition>, include:>` markers: the marked paragraph and the
    paragraphs after it up to one that starts a new field, role line, output line or marker are kept
    (marker dropped) when truth(condition) holds, else dropped."""
    lines = prompt.split("\n")
    out, i = [], 0
    while i < len(lines):
        m = _IF_RE.match(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        keep = truth(m.group(1))
        j, first = i + 1, True
        while j < len(lines):
            if not lines[j].strip():
                k = j
                while k < len(lines) and not lines[k].strip():
                    k += 1
                if k >= len(lines) or _PARA_STOP.match(lines[k]) or lines[k].strip() == '"':
                    break
                first = False
            elif not first and _IF_RE.match(lines[j]):
                break
            j += 1
        if keep:
            out.extend(lines[i + 1:j])
        i = j
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text)


_FOR_BLOCK = re.compile(r"^([ \t]*)<For each (\w+) in (\w+) where value starts with '([^']+)':>[ \t]*\n(.*?)^[ \t]*</For>[ \t]*\n",
                        re.M | re.S)
_FOR_LINE = re.compile(r"^([ \t]*)<For each (\w+) in (\w+): (.*)>[ \t]*$", re.M)


def expand_loops(prompt: str, collections: dict, fill_item) -> str:
    """`<For each X in Y where value starts with 'P':>` ... `</For>` blocks and one-line
    `<For each X in Y: <line>>` loops, expanded over the run's collections."""
    def block(m):
        var, coll, prefix, body = m.group(2), m.group(3), m.group(4), m.group(5)
        items = collections[coll]
        out = []
        for key, value in items.items():
            if str(value).startswith(prefix):
                out.append(fill_item(body, var, key, value))
        return "".join(out)
    prompt = _FOR_BLOCK.sub(block, prompt)

    def line(m):
        indent, var, coll, body = m.group(1), m.group(2), m.group(3), m.group(4)
        items = collections[coll]
        seq = items.items() if isinstance(items, dict) else enumerate(items)
        return "\n".join(indent + fill_item(body, var, k, v).strip() for k, v in seq)
    return _FOR_LINE.sub(line, prompt)


_CURLY_RE = re.compile(r"(?<!\$)\{([A-Za-z_][^{}\"\n]*)\}")  # `${VAR}` is a shell variable, not a slot


def fill_curly(text: str, pipeline: dict | None, values: dict) -> str:
    """The text's `{pipeline.x}`, `{i}` and `{<expr> or null ...}` placeholders."""
    def sub(m):
        expr = m.group(1).strip()
        if expr.startswith("pipeline.") and pipeline is not None:
            return str(pipeline[expr.split(".", 1)[1]])
        if expr == "i" and pipeline is not None:
            return str(pipeline["index"])
        if " or null" in expr:
            left = expr.split(" or null", 1)[0].strip()
            name = re.match(r"(\w+)", left).group(1)
            val = values.get(name)
            if isinstance(val, dict):
                key = re.search(r"\[([^\]]+)\]", left)
                val = val.get(key.group(1).strip("'\"")) if key else None
            return "null" if val in (None, "") else str(val)
        if expr in values:
            return str(values[expr])
        raise cmdtext.TextNotFound(f"unbound placeholder {{{expr}}}")
    return _CURLY_RE.sub(sub, text)


def bullets_prompt(block: str) -> tuple[list, str]:
    """The specialist prompt the text's "Each subagent receives, at the TOP of its prompt" bullet list
    composes: `- X line: "<text>"` becomes `X: <text>`, `- Label: value` stays `Label: value`.
    Returns (lines, the "Write report to:" path under the Agent( line)."""
    lines = block.split("\n")
    start = next(i for i, l in enumerate(lines) if "Each subagent receives" in l)
    out = []
    for l in lines[start + 1:]:
        if not l.strip():
            break
        m = re.match(r"^\s*-\s+(.*)$", l)
        if not m:
            break
        item = m.group(1)
        q = re.match(r'^([A-Z][A-Z ]+) line:\s*"(.*?)"', item)
        out.append(f"{q.group(1)}: {q.group(2)}" if q else item)
    path = re.search(r"^\s*Write report to:\s*(\S+)", block, re.M).group(1)
    return out, path


# ---------------------------------------------------------------- role work

def _out_path(prompt: str) -> str | None:
    m = re.search(r"^\s*(?:Output [\w ]*?to|Write [\w ]*?to):\s*(\S+)", prompt, re.M)
    return m.group(1) if m else None


def _spec_updates(sub, brief, sections: dict, verdict: str = "pass") -> None:
    """The base text's "update the (overnight) spec: Section N ..." instructions of a dispatch prompt:
    each Section N named on such a line gets the role's content in place of its first
    `_Not yet populated._`; a "write ... if empty" line writes only empty sections."""
    lines = [l for l in brief.prompt.split("\n") if re.search(r"(?i)update (?:the|its) (?:overnight )?spec:", l)]
    if not lines:
        return
    spec = re.search(r"^\s*(?:Overnight spec file|Spec file):\s*(\S+\.md)", brief.prompt, re.M)
    if not spec:
        return
    path = agents.expand(spec.group(1), brief.project)
    if not os.path.isfile(path):
        return
    text = agents.peek(sub.rp, sub.role, path)
    new = text
    for line in lines:
        for n in re.findall(r"Section (\d+)", line):
            body = sections.get(n) or f"Recorded by {sub.role}."
            head = re.search(r"^## Section %s:.*$" % n, new, re.M)
            if not head:
                continue
            at = new.find("_Not yet populated._", head.end())
            nxt = re.search(r"^## Section ", new[head.end():], re.M)
            if at < 0 or (nxt and at > head.end() + nxt.start()):
                continue
            new = new[:at] + body + new[at + len("_Not yet populated._"):]
    if new != text:
        sub.read(path, label=f"{sub.role} Read spec (update)")
        a, b = agents.edit_span(text, new)
        sub.edit(path, a, b, label=f"{sub.role} Edit spec sections")


def report_work(content, reads=(), globs=(), extra=None):
    """A PM or specialist run: Reads of what its agent text has it read (project files, Globbed
    reports), then its report: content for the declared artifact where its obligation names the
    path, else the file its prompt's output line names, written by the role itself."""
    def work(sub, brief, player):
        project = brief.project
        for rel in reads:
            p = os.path.join(project, rel)
            if os.path.isfile(p):
                sub.read(p, label=f"{sub.role} Read {rel}")
        for pattern, base in globs:
            g = sub.tool("Glob", {"pattern": pattern, "path": os.path.join(project, base)},
                         label=f"{sub.role} Glob {pattern}")
            for f in (g.response.get("filenames") or []) if g.ok else []:
                sub.read(f, label=f"{sub.role} Read {os.path.relpath(f, project)}")
        if extra:
            extra(sub, brief, player)
        doc = content() if callable(content) else content
        rel = _out_path(brief.prompt)
        declared = [a["path"] for a in (brief.obligation or {}).get("artifacts") or []]
        if rel in declared or rel is None:
            return {rel or "*": doc}
        path = agents.expand(rel, project)
        agents.put(sub, path, json.dumps(doc, indent=2) + "\n", f"{sub.role} Write {rel}")
        player.written.append(rel)
        return {}
    return work


# ---------------------------------------------------------------- the orchestrator

class NightOrchestrator(Orchestrator):
    """Orchestrator whose canonical steps carry a letter suffix (Step 11g)."""

    def step_name(self, i: int) -> str:
        m = re.match(r"(Step \d+[a-z]?)\b", self.todos[i]["content"])
        return m.group(1) if m else self.todos[i]["content"]

    def at_step(self, n) -> bool:
        i = self.current()
        return i is not None and self.step_name(i) == f"Step {n}"

    def set_in_progress(self, n, label: str):
        """Step n in progress again (the 11g precondition's "mark ... in_progress" and "restore the
        surrounding step"): the step in progress before it completed when it comes earlier, pending
        when it comes later."""
        i = next(k for k in range(len(self.todos)) if self.step_name(k) == f"Step {n}")
        for k, t in enumerate(self.todos):
            if k == i:
                t["status"] = "in_progress"
            elif t.get("status") == "in_progress":
                t["status"] = "completed" if k < i else "pending"
        return self._todo(label)


@dataclass
class Pipe:
    index: int
    sc: devdrv.Scenario
    rec: dict = field(default_factory=dict)  # the builder's record for it

    @property
    def sfx(self) -> str:
        return self.rec["timestamp_suffix"]


class Night:
    def __init__(self, rp, variant: str):
        self.rp, self.variant = rp, variant
        devs = DEVIATIONS
        if rp.args.get("kept"):
            devs = devdrv.KeptOnly(DEVIATIONS, json.loads(rp.args["kept"]))
        self.project = rp.layout.project
        self.base_kit = rp.args.get("kit") == "base"
        self.owner_setup()  # before the session starts (the Orchestrator starts it)
        self.o = NightOrchestrator(rp, "dev-overnight", deviations=devs, respellings=devdrv.RESPELLINGS,
                                   rules=self._rules())
        rp.deviation_at = self.o.devs.at  # the subagents' own calls take the same deviations by label
        self.project = rp.layout.project
        self.sid = self.o.s.sid
        self.cycle = 0
        self.state: dict = {}
        self.init: dict = {}
        self.ts = ""                    # the <TS> of the dispatch being rendered
        self.pts = ""                   # the cycle's pipeline timestamp (Step 6's <timestamp>)
        self.n = 1                      # the cycle number the text reads
        self.plan: dict = {}
        self.assessed: dict = {}
        self.priority = ""
        self.criteria: list = []
        self.pipes: list[Pipe] = []
        self.spec_name = ""             # the specialist being rendered
        self.report_rel = ""
        self.final_cycle = False
        self.read_paths: set = set()
        self.log_rel = ""

    # ------------------------------------------------------------ values
    @property
    def L(self) -> str:
        return f"C{self.cycle} "

    def _rules(self):
        return [
            (r"^TS$", lambda m: self.ts),
            (r"^ISO-8601", lambda m: utc_now()),
            (r"^(?:session_id|DEV_SESSION_ID)$", lambda m: self.sid),
            (r"^MAIN_ROOT$", lambda m: self.main_root),
            (r"^(?:PROJECT_ROOT|validated worktree_path from state file|worktree_path(?: from state file)?)$",
             lambda m: self.worktree),
            (r"^(?:STATE_FILE|path to overnight-state-\*\.json)$", lambda m: self.state_file),
            (r"^(?:N|cycle_count \+ 1|current cycle_count)$", lambda m: str(self.n)),
            (r"^specialist(?:\.type)?$", lambda m: self.spec_name),
            (r"^addressed_issues array from state file$", lambda m: json.dumps(self.state.get("addressed_issues") or [])),
            (r"^focus string from state file", lambda m: self.state.get("focus") or "none"),
            (r"^the priority context block", lambda m: self.priority),
            (r"^path above$", lambda m: self.report_rel),
            (r"^core_flow_completed from user report$", lambda m: json.dumps(self.user_gate.get("core_flow_completed"))),
            (r"^core_flow_reliability from user report", lambda m: json.dumps(self.user_gate.get("core_flow_reliability"))),
            (r"^calculated time remaining in minutes$", lambda m: str(self.minutes_left())),
            (r"^true\|false$", lambda m: "true" if self.final_cycle else "false"),
            (r"^worktree_branch(?: from state file)?$", lambda m: self.state.get("worktree_branch", "")),
            (r"^list each criterion from focus_verification_criteria array$",
             lambda m: "\n".join(json.dumps(c) for c in self.criteria)),
            (r"^the context file Dev will consume", lambda m: self.ctx_rel),
            (r"^resolved \$REQUIREMENT_DOC path$", lambda m: self.init.get("REQUIREMENT_DOC", "")),
            (r"^(?:start_time|end_time|isolation_kind)$", lambda m: str(self.state.get(m.group(0)))),
            (r"^date$", lambda m: time.strftime("%Y-%m-%d", time.gmtime())),
            # A prompt's prose naming a concept, not a slot: graphify's "`<task-id>`-derived default".
            (r"^task-id$", lambda m: "<task-id>"),
        ]

    @property
    def main_root(self) -> str:
        return self.o.values.get("PROJECT_DIR") or self.state.get("main_root") or self.project

    @property
    def worktree(self) -> str:
        return self.state.get("worktree_path") or self.project

    @property
    def state_file(self) -> str:
        return self.o.values.get("STATE_FILE") or os.path.join(self.project, ".claude", f"overnight-state-{self.sid}.json")

    @property
    def sdir(self) -> str:
        return f"docs/dev/overnight/{self.sid}"

    user_gate: dict = {}
    ctx_rel = ""

    def minutes_left(self) -> int:
        try:
            end = time.mktime(time.strptime(self.state["end_time"][:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
            return max(0, int((end - time.time()) // 60))
        except (KeyError, ValueError):
            return 0

    def stamp(self) -> str:
        """A UTC second distinct from the previous dispatch's (its task id)."""
        while True:
            ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
            if ts != getattr(self, "_last_ts", ""):
                self._last_ts = ts
                return ts
            time.sleep(0.2)

    def truth(self, cond: str) -> bool:
        values = {"spec_mode": self.state.get("spec_mode"), "codex_required": bool(self.state.get("codex_required")),
                  "view_paths": self.state.get("view_paths"), "focus_verification_criteria": self.criteria}
        out = True
        for atom in re.split(r"\s+AND\s+", cond):
            atom = atom.strip()
            m = re.fullmatch(r"(\w+) == '([^']*)'", atom)
            if m:
                out &= values.get(m.group(1)) == m.group(2)
                continue
            m = re.fullmatch(r"(\w+) == (true|false)", atom)
            if m:
                out &= bool(values.get(m.group(1))) == (m.group(2) == "true")
                continue
            m = re.fullmatch(r"(\w+)\['(\w+)'\] is non-null", atom)
            if m:
                v = values.get(m.group(1))
                out &= isinstance(v, dict) and v.get(m.group(2)) is not None
                continue
            m = re.fullmatch(r"(\w+) array exists(?: from Step \d+)?", atom)
            if m:
                out &= bool(values.get(m.group(1)))
                continue
            raise cmdtext.TextNotFound(f"conditional the driver cannot evaluate: {atom!r}")
        return out

    def prep(self, prompt: str, pipe: Pipe | None = None) -> str:
        """A template's prompt with the orchestrator's own substitutions: conditionals, loops, the
        `{...}` placeholders, and the literal values the BINDING-EVAPORATION RULE asks for."""
        prompt = conditional_paragraphs(prompt, self.truth)

        def item(body, var, key, value):
            body = body.replace(f"<{var}>", str(key))
            body = re.sub(r"<skip reason from [^>]*>", str(value).split("—", 1)[-1].strip(), body)
            return fill_curly(body, value if isinstance(value, dict) else None, {})
        colls = {"specialists_assessed": self.assessed,
                 "current_issues": [p.rec for p in self.pipes]}
        prompt = expand_loops(prompt, colls, item)
        prompt = fill_curly(prompt, pipe.rec if pipe else None,
                            {"view_paths": self.state.get("view_paths"), "user_spec_path": self.state.get("user_spec_path")})
        return cmdtext.fill(prompt, {"$CLAUDE_PROJECT_DIR": self.main_root, "${CLAUDE_PROJECT_DIR}": self.main_root,
                                     "$DEV_SESSION_ID": self.sid, "${DEV_SESSION_ID}": self.sid,
                                     "$REQUIREMENT_DOC": self.init.get("REQUIREMENT_DOC", "")})

    # ------------------------------------------------------------ tool shorthands
    def read(self, rel: str, label: str):
        path = rel if os.path.isabs(rel) else os.path.join(self.project, rel)
        self.read_paths.add(path)
        return self.o.s.read(path, label=self.L + label, deviation=self.o.devs.at(self.L + label))

    def load(self, rel: str) -> dict:
        path = rel if os.path.isabs(rel) else os.path.join(self.project, rel)
        return json.loads(agents.peek(self.rp, "main", path))

    def bash(self, cmd: str, desc: str, label: str, capture=()):
        return self.o.run(cmd, desc, self.L + label, capture=capture)

    def write(self, rel: str, text: str, label: str):
        """A file the main agent writes: Write when new; an existing one is Read and edited in place
        (the write guard refuses a Write over an existing file)."""
        path = rel if os.path.isabs(rel) else os.path.join(self.project, rel)
        lab = self.L + label
        if not os.path.exists(path):
            return self.o.s.write(path, text, label=lab, deviation=self.o.devs.at(lab))
        if path not in self.read_paths:
            self.o.s.read(path, label=lab + " (Read before edit)", deviation=self.o.devs.at(lab + " (Read before edit)"))
            self.read_paths.add(path)
        old = agents.peek(self.rp, "main", path)
        if old == text:
            return None
        a, b = agents.edit_span(old, text)
        return self.o.s.edit(path, a, b, label=lab + " (Edit)", deviation=self.o.devs.at(lab + " (Edit)"))

    def todo_to(self, n) -> None:
        while not self.o.at_step(n):
            i = self.o.current()
            self.o.advance(f"{self.L}TodoWrite {self.o.step_name(i)} done"
                           + (f", {self.o.step_name(i + 1)} in_progress" if i + 1 < len(self.o.todos) else ""))

    def dispatch(self, fields: dict, act: agents.Act, label: str, task_id: str, atype=None, pipe: Pipe | None = None):
        fields = dict(fields, prompt=self.prep(fields["prompt"], pipe),
                      description=fill_curly(fields.get("description", ""), pipe.rec if pipe else None, {}))
        return self.o.dispatch(fields, act, self.L + label, task_id, subagent_type=atype)

    def git(self, cmd: str) -> str:
        """A command that runs git, composed as the ACTOR GIT-ENV GUARD says: the env helper the record
        names sourced first and joined with `&&` (with --worktree in an isolated mode)."""
        env = self.state.get("actor_git_env") or {}
        helper = env.get("env_helper")
        if not helper:
            return cmd
        pre = f"source {shlex.quote(helper)} --main-root {shlex.quote(self.main_root)}"
        if env.get("marker_only") is False:
            pre += f" --worktree {shlex.quote(self.worktree)}"
        return f"{pre} && {cmd}"

    # ------------------------------------------------------------ launch and Step 1
    def owner_setup(self) -> None:
        """Before the session: origin/HEAD set, a working branch checked out (the owner's own git)."""
        with self.rp.acting("owner"):
            for args in (["remote", "set-head", "origin", "master"], ["checkout", "-q", "-b", WORK_BRANCH]):
                subprocess.run(["git", "-C", self.project, *args], check=True, capture_output=True,
                               env={k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")})

    def launch(self) -> None:
        o = self.o
        o.slash(f"{END_TIME} {FOCUS}")
        o.todo_start("C1 TodoWrite canonical list")

    def step1(self) -> None:
        o, s = self.o, self.o.s
        self.cycle = 1
        # "List `.claude/overnight-state-*.json` and read the file matching the current session."
        g = s.tool("Glob", {"pattern": ".claude/overnight-state-*.json", "path": self.project},
                   label="C1 Step 1 Glob state records", deviation=o.devs.at("C1 Step 1 Glob state records"))
        mine = [f for f in (g.response.get("filenames") or []) if self.sid in os.path.basename(f)] if g.ok else []
        path = mine[0] if mine else self.state_file
        self.read(path, "Step 1 Read state record")
        self.state = self.load(path)
        # The SESSION BINDING + ONE-CALL INITIALIZATION block, one Bash call.
        name, b, _ = o.step_blocks("Step 1")[0]
        keep = [(r"^(?:unset|empty)$", lambda m: f"<{m.group(0)}>")]
        call = o.run_text(b.text, "C1 Step 1 Bash session binding + init", "Step 1: session binding and one-call init",
                          capture=("PROJECT_DIR", "STATE_FILE", "DEV_SESSION_ID", "REGISTRY_DIR"), extra_rules=keep)
        out = call.response.get("stdout", "") if call.ok else ""
        self.init = dict(re.findall(r"^([A-Z][A-Z_]+)=(.*)$", out, re.M))
        if "OVERNIGHT_INIT_OK" not in out:
            s.say("Step 1: the initialization's last line is not OVERNIGHT_INIT_OK; continuing with the record's values.")
        if not self.init.get("REQUIREMENT_DOC"):
            self.init["REQUIREMENT_DOC"] = self.state.get("requirement_doc", "")
        # WORKING-ROOT GUARD: cd into worktree_path.
        self.bash(f"cd {shlex.quote(self.worktree)} && pwd", "Enter the working root", "Step 1 Bash cd working root")
        ann = o.block("Step 1", anchor="Overnight development session initialized")
        s.say(o.bind(ann, [(r"^isolation_kind$", str(self.state.get("isolation_kind")))]))

    # ------------------------------------------------------------ Steps 2-4
    def step2(self) -> None:
        o = self.o
        self.todo_to(2)
        self.ts = self.stamp()
        self.rp.task(self.ts)
        plan_rel = f"{self.sdir}/test-plan.json"
        n = self.n

        def content():
            plan = {"plan_id": f"tp-{self.ts}", "version": 1, "timestamp": utc_now(), "session_id": self.sid,
                    "cycle_number": n,
                    "app_context": {"url": "none: CLAUDE.md and README.md name no running application",
                                    "test_email": None, "test_password": None, "credentials_available": False,
                                    "project_type": "Python library",
                                    "core_flow_steps": ["Step 1: import toy", "Step 2: call toy.add(2, 3) and read 5"],
                                    "core_flow_source": "docs"},
                    "pm_experience": {"app_not_running": True, "credentials_verified": False,
                                      "notes": "no application URL in CLAUDE.md or README.md: doc-based planning"},
                    "previously_tested": self.state.get("addressed_issues") or [], "focus": FOCUS,
                    "agent_assignments": {
                        "user": {"mandatory": ["core_flow_execution"], "secondary": ["error_recovery"]},
                        "product-owner": {"mandatory": ["feature_inventory"], "secondary": []},
                        "architect": {"mandatory": ["code_architecture"], "secondary": ["error_handling"]},
                        "ui-specialist": {"mandatory": [], "secondary": []}},
                    "core_flow_gate": {"owner": "user", "required": True, "failure_is_cycle_failure": True},
                    "recommended_specialists": [
                        {"specialist_type": t, "decision": "call", "reason": why, "scope": {"target_components": ["toy"]},
                         "budget": {"max_pages": 0, "max_viewports": 0, "max_minutes": 8, "max_screenshots": 0},
                         "degradation_check": {"pre_check_state": "active", "action_taken": "active",
                                               "rationale": "no yield history for this session"}}
                        for t, why in CALLED.items()],
                    "strategic_notes": "a library package: findings come from reading the code and its tests"}
            if n > 1:
                plan["priority_tiers"] = {"tier_1_blockers": [], "tier_2_major": [], "tier_3_minor": []}
                plan["unresolved_from_previous"] = []
            return plan
        reads = ("CLAUDE.md", "README.md")
        globs = [("retro-report-cycle*.json", self.sdir)] if n > 1 else []
        act = agents.Act(work=report_work(content, reads, globs), summary="test plan written", status="completed")
        self.dispatch(o.template("Step 2"), act, "Step 2 Agent(pm) PLAN", self.ts, atype="pm")
        # After PM-Plan: the plan Read and the priority context built from it.
        self.read(plan_rel, "Step 2 Read test plan")
        self.plan = self.load(plan_rel)
        tiers = self.plan.get("priority_tiers")
        if tiers:
            tpl = cmdtext.block(o.section("After PM-Plan Completes"), None, anchor="Priority context from PM:")

            def lst(key):
                return json.dumps([t.get("description") for t in tiers.get(key) or []])
            self.priority = o.bind(tpl, [(r"tier_1_blockers", lst("tier_1_blockers")),
                                         (r"tier_2_major", lst("tier_2_major")),
                                         (r"tier_3_minor", lst("tier_3_minor")),
                                         (r"unresolved_from_previous", json.dumps(self.plan.get("unresolved_from_previous") or []))]).strip()
        else:
            m = re.search(r'set the priority context to:\s*\n?`"?([^`]+?)"?`', o.section("After PM-Plan Completes"))
            self.priority = m.group(1)
        o.s.say(self.priority)

    def specialists(self) -> list:
        """Exploration mode: every specialist of agent_assignments, narrowed to the plan's
        recommended_specialists (decision call) when it names any."""
        rec = [r["specialist_type"] for r in self.plan.get("recommended_specialists") or [] if r.get("decision") == "call"]
        every = list((self.plan.get("agent_assignments") or {}).keys())
        launch = rec or every
        self.assessed = {}
        for t in every:
            self.assessed[t] = (f"RELEVANT — {CALLED.get(t, 'recommended by PM')}" if t in launch
                                else f"SKIP — {SKIPPED.get(t, 'not recommended by PM this cycle')}")
        return launch

    def step3(self) -> None:
        o = self.o
        self.todo_to(3)
        launch = self.specialists()
        o.s.say("specialists_assessed: " + json.dumps(self.assessed, indent=1, ensure_ascii=False))
        ann = cmdtext.block(o.section("Specialist Calling Rule"), None, anchor="Launching specialist subagents")
        ann = "\n".join(l for l in ann.split("\n") if "If fallback" not in l)
        o.s.say(ann.replace("{N}", str(len(launch))).replace("{list of specialist types}", ", ".join(launch)))
        blk = next(b.text for b in cmdtext.blocks(o.section("Specialist Calling Rule"), None)
                   if "Each subagent receives" in b.text)
        lines, out_tpl = bullets_prompt(blk)
        scs = CYCLE_SCENARIOS[self.cycle]
        for role in launch:
            self.spec_name = role
            self.ts = self.stamp()
            self.rp.task(self.ts)
            self.report_rel = o.bind(out_tpl)
            issues = [_issue(sc, k, role) for k, sc in enumerate(scs, 1)]
            doc = {"role": role, "timestamp": utc_now(), "issues": issues,
                   "summary": f"{len(issues)} issues found by reading the package"}
            if role == "user":
                doc["live_testing"] = {"performed": False, "core_flow_completed": True,
                                       "core_flow_completion_depth": "full",
                                       "core_flow_steps": [{"action": "import toy; toy.add(2, 3)", "result": "5"}]}
            else:
                doc["app_understanding"] = {"e2e_flow_executed": True, "flow_completed_successfully": True,
                                            "app_not_running": True}
            reads = [sc.rel for sc in scs] + ["tests/test_add.py"]
            act = agents.Act(work=report_work(doc, reads), summary=doc["summary"], status="completed")
            self.dispatch({"subagent_type": role, "description": f"{role} specialist scan",
                           "prompt": "\n".join(lines)}, act, f"Step 3 Agent({role})", self.ts, atype=role)
        self.validate_reports(launch)

    def validate_reports(self, launch: list) -> None:
        o = self.o
        sec = o.section("Specialist Calling Rule")
        check = re.search(r"run `(~/\.claude/scripts/check-overnight-reports\.sh[^`]*)`", sec)
        if check:  # the base text: the report check script, then the sanity checks (each report Read)
            self.bash(o.bind(check.group(1)), "Validate the specialist reports", "Step 3 Bash check-overnight-reports")
        if "Sanity checks on each report" in sec:
            for role in launch:
                self.read(f"{self.sdir}/{role}-report.json", f"Step 3 Read {role} report")
        # Core Flow Gate Check: the user report's core_flow_completed.
        rel = f"{self.sdir}/user-report.json"
        if self.assessed.get("user", "").startswith("RELEVANT"):
            if "Sanity checks on each report" not in sec:
                self.read(rel, "Step 3 Read user report (core flow gate)")
            rep = self.load(rel)
            lt = rep.get("live_testing") or {}
            self.user_gate = {"core_flow_completed": lt.get("core_flow_completed", rep.get("core_flow_completed")),
                              "core_flow_reliability": lt.get("core_flow_reliability")}
            o.s.say(f"Core flow gate: core_flow_completed={self.user_gate['core_flow_completed']}; "
                    f"route_map_file={'present' if rep.get('route_map_file') else 'absent'}")

    def cycle_number(self) -> None:
        o = self.o
        sec = o.section("Step 4")
        m = re.search(r"`(~/\.claude/hooks/lib/overnight\.py cycle-index <STATE_FILE>)`", sec)
        if m:
            c = self.bash(o.bind(m.group(1)), "Read the cycle number", "Step 4 Bash cycle-index")
            out = c.response.get("stdout", "").strip() if c.ok else ""
            self.n = int(out) if out.isdigit() else self.cycle
        else:  # the base text: Cycle number <cycle_count + 1>, from the state record
            self.read(self.state_file, "Step 4 Read state record (cycle_count)")
            self.state = self.load(self.state_file)
            self.n = int(self.state.get("cycle_count") or 0) + 1

    def step4(self) -> None:
        o = self.o
        self.todo_to(4)
        self.cycle_number()
        self.ts = self.stamp()
        self.rp.task(self.ts)
        scs = CYCLE_SCENARIOS[self.cycle]
        tri_rel = f"{self.sdir}/triage-report-cycle{self.n}.json"
        flagged = [r for r, v in self.assessed.items() if v.startswith("RELEVANT")]
        doc = {"triage_id": f"tr-{self.ts}", "plan_id": self.plan.get("plan_id"), "session_id": self.sid,
               "cycle_number": self.n, "timestamp": utc_now(), "mode": "focus", "mode_reason": f"focus: {FOCUS}",
               "core_flow_status": "passed",
               "issues": [{"triage_index": k, "tier": 1, "description": sc.requirement, "location": sc.rel,
                           "severity": "major", "category": "input-validation", "agents_flagged": flagged,
                           "estimated_effort": "small", "details": sc.symptom, "observation_notes": sc.before,
                           "pipe_category": "user_need", "pipeline_recommendation": "fix", "skip_reason": None,
                           "unresolved_cycles": 0} for k, sc in enumerate(scs)],
               "pipeline_order": list(range(len(scs))), "pipeline_blocked": False, "block_reasons": [],
               "skipped_issues": [], "out_of_scope_observations": [], "pm_notes": [],
               "strategic_notes": "both findings flagged by every launched specialist"}
        reads = []
        act = agents.Act(work=report_work(doc, reads), summary="triage written", status="completed")
        self.dispatch(o.template("Step 4"), act, "Step 4 Agent(pm) TRIAGE", self.ts, atype="pm")
        self.read(tri_rel, "Step 4 Read triage report (pipeline_blocked)")
        self.triage = self.load(tri_rel)
        self.tri_rel = tri_rel
        self.pts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        self.pipes = []
        fixes = [i for i in self.triage.get("pipeline_order") or []
                 if next(x for x in self.triage["issues"] if x["triage_index"] == i).get("pipeline_recommendation") == "fix"]
        for j, ti in enumerate(fixes):
            sfx = f"{self.pts}-{j}"
            self.rp.task(sfx)
            self.pipes.append(Pipe(j, scs[ti], {"index": j, "timestamp_suffix": sfx, "iteration": 0,
                                                "description": scs[ti].requirement, "location": scs[ti].rel,
                                                "spec_path": f"{self.sdir}/spec-pipeline-{j}.md"}))
        if self.o.has("Cycle Contract Manifest", "orchestrator writes the per-cycle contract manifest"):
            self.contract()

    # ------------------------------------------------------------ the base's contract manifest
    def _entry_examples(self) -> dict:
        """The section's inline `{step: "8", role: ...}` examples, keyed by step."""
        sec = self.o.section("Cycle Contract Manifest")
        out = {}
        for code in re.findall(r"`(\{step: [^`]+\})`", sec):
            body = re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', code)
            out.setdefault(json.loads(body)["step"], json.loads(body))
        return out

    def contract(self) -> None:
        o = self.o
        sec = o.section("Cycle Contract Manifest")
        paths = re.findall(r"^- (?:Primary|Stable symlink for hooks|Colocated mirror): (.+)$", sec, re.M)
        primary, link, mirror = (o.bind(p) for p in paths)
        primary, mirror = (re.search(r"`([^`]+)`", x).group(1) for x in (primary, mirror))
        link_path, link_target = re.findall(r"`([^`]+)`", link)[:2]
        ex = self._entry_examples()
        sdir = self.sdir

        def entry(step, role, mode, path, schema):
            return {"step": step, "role": role, "mode": mode, "pipeline_id": None, "expected_output_path": path,
                    "schema_name": schema, "max_retries": 2}

        def mode(heading):  # the mode keyword the step's own template puts in its prompt, else null
            m = re.search(r"^\s*PM_MODE:\s*(\w+)", o.template(heading)["prompt"], re.M)
            return m.group(1) if m else None
        calls = [entry("2", "pm", mode("Step 2"), f"{sdir}/test-plan.json", None)]
        calls += [entry(f"3-{r}", r, None, f"{sdir}/{r}-report.json", None)
                  for r, v in self.assessed.items() if v.startswith("RELEVANT")]
        calls.append(entry("4", "pm", mode("Step 4"), self.tri_rel, None))
        # Step 10's dispatch (QA in BA-validation mode): its own obligation's artifact and schema; its
        # prompt carries no mode keyword.
        qa10 = agent_block(next(b.text for b in cmdtext.blocks(o.section("Step 10"), None) if "Agent(" in b.text))
        m10 = re.search(r'artifacts=\[\{"kind":"json","path":"([^"]+)","schema":"([^"]+)"', qa10["prompt"])
        for p in self.pipes:
            for step in ("8", "10", "12", "15"):
                if step in ex:
                    e = json.loads(fill_curly(json.dumps(ex[step]), p.rec, {}))
                else:
                    e = entry(step, "qa", None, fill_curly(m10.group(1), p.rec, {}), m10.group(2))
                calls.append(e)
        if "11g" in ex:
            calls.append(json.loads(json.dumps(ex["11g"]).replace("<session_id>", self.sid).replace("<N>", str(self.n))))
        calls.append(entry("20", "pm", mode("Step 20"), f"{sdir}/retro-report-cycle{self.n}.json", None))
        doc = {"schema_version": 1, "spec_id": f"autonomous-{self.sid}", "session_id": self.sid, "cycle_id": self.n,
               "created_at": utc_now(), "monolith_sha256": None, "spec_mode": self.state.get("spec_mode"),
               "required_calls": calls,
               "pipelines": {f"pipeline-{p.index}": {"ba_status": "pending", "dev_status": "pending",
                                                    "qa_status": "pending",
                                                    "artifact_paths": {"ba": f"docs/dev/context-{p.sfx}.json",
                                                                       "dev": f"docs/dev/dev-report-{p.sfx}.json",
                                                                       "qa": f"docs/dev/qa-report-{p.sfx}.json"}}
                             for p in self.pipes},
               "specialist_selection": {r["specialist_type"]: {"decision": r.get("decision"), "reason": r.get("reason"),
                                                              "scope": r.get("scope") or {},
                                                              "budget": r.get("budget") or {}}
                                        for r in self.plan.get("recommended_specialists") or []}}
        body = json.dumps(doc, indent=2) + "\n"
        self.write(primary, body, "Step 4 Write cycle contract")
        self.bash(f"ln -sfn {shlex.quote(link_target.replace(sdir + '/', ''))} {shlex.quote(link_path)}",
                  "Link cycle-current.json to this cycle's contract", "Step 4 Bash cycle-current symlink")
        self.write(mirror, body, "Step 4 Write contract mirror")

    # ------------------------------------------------------------ Steps 5-7
    def step5(self) -> None:
        o = self.o
        self.todo_to(5)
        sec = o.section("Step 5")
        tpl = re.search(r"Copy the template from `([^`]+)`", sec).group(1)
        tpl_path = tpl.replace("~", self.rp.layout.home, 1)
        self.read(tpl_path, "Step 5 Read spec template")
        text = agents.peek(self.rp, "main", tpl_path)
        sec5 = "Replace Section 5's `_Not yet populated._`" in sec
        for p in self.pipes:
            t = (text.replace("<issue_description>", p.rec["description"]).replace("<pipeline_index>", str(p.index))
                 .replace("<session_id>", self.sid).replace("<ISO-8601>", utc_now()))
            if sec5:
                head = re.search(r"^## Section 5:.*$", t, re.M)
                at = t.find("_Not yet populated._", head.end())
                t = t[:at] + p.rec["description"] + t[at + len("_Not yet populated._"):]
            self.write(p.rec["spec_path"], t, f"Step 5 Write spec-pipeline-{p.index}")

    def step6(self) -> None:
        o = self.o
        self.todo_to(6)
        name, b, _ = o.step_blocks("Step 6")[0]
        rules = [(r"^triage-report$", self.tri_rel),
                 (r"^addressed-issues$", f"<(jq -c '.addressed_issues // []' {shlex.quote(self.state_file)})"),
                 (r"^timestamp$", self.pts)]
        call = o.run_text(b.text, f"{self.L}Step 6 Bash {name}", "Create the pipeline definitions", extra_rules=rules)
        out = call.response.get("stdout", "") if call.ok else ""
        try:
            recs = json.loads(out)
        except ValueError:
            recs = []
        for p in self.pipes:  # the builder's records, where it printed them
            rec = next((r for r in recs if r.get("index") == p.index), None)
            if rec:
                p.rec = dict(rec)
        ann = cmdtext.block(o.section("Step 6"), None, anchor="Proceeding to parallel BA phase")
        tier = {k: sum(1 for p in self.pipes if p.rec.get("tier", 1) == k) for k in (1, 2, 3)}
        out = []
        for l in ann.rstrip("\n").split("\n"):
            if l.strip().startswith("Pipeline 0 "):  # the example lines become one line per pipeline
                ind = l[:len(l) - len(l.lstrip())]
                out += [f"{ind}Pipeline {p.index} [T{p.rec.get('tier', 1)}]: {p.rec['description']} "
                        f"({p.rec.get('severity', 'major')}, {p.rec['location']})" for p in self.pipes]
            elif not l.strip().startswith("Pipeline ") and l.strip() != "...":
                out.append(l)
        text = "\n".join(out)
        for k, v in (("{mode}", self.triage.get("mode", "")), ("{mode_reason}", self.triage.get("mode_reason", "")),
                     ("{N}", str(len(self.pipes))), ("{tier1_count}", str(tier[1])), ("{tier2_count}", str(tier[2])),
                     ("{tier3_count}", str(tier[3]))):
            text = text.replace(k, v)
        o.s.say(text)

    def step7(self) -> None:
        self.todo_to(7)
        focus = self.state.get("focus")
        if focus:
            self.criteria = [
                {"criterion": "each public function of toy raises TypeError naming the argument for a non-number "
                              "(2 of 2 functions checked)", "required_evidence_level": "fresh_scan_completed"},
                {"criterion": "python -m pytest -q exits 0 with 0 failures", "required_evidence_level": "fresh_scan_completed"},
                {"criterion": "README.md shows at least 1 runnable usage line", "required_evidence_level": "rendered_cached"}]
            self.o.s.say("focus_verification_criteria: " + json.dumps(self.criteria))

    # ------------------------------------------------------------ Steps 8-11
    def step8(self) -> None:
        o = self.o
        self.todo_to(8)
        sec = o.section("Step 8")
        hyd = o.step_blocks("Step 8")[0][1].text
        tpl = agent_block(next(b.text for b in cmdtext.blocks(sec, None) if "Agent(" in b.text))
        # The existing-specs pattern Four Contracts Awareness names (its legacy name left out).
        pattern = cmdtext.inline_codes(o.text, "Pre-BA: surface retry signals", "Existing BA specs")[0]
        for p in self.pipes:
            sc = p.sc
            # Existing BA specs "with keywords from the current issue": the pattern's files holding the keyword.
            lab = f"{self.L}Step 8 Grep prior tickets {p.index}"
            g = o.s.tool("Grep", {"pattern": re.escape(sc.keyword), "path": os.path.join(self.project, os.path.dirname(pattern)),
                                  "glob": os.path.basename(pattern), "output_mode": "files_with_matches"},
                         label=lab, deviation=o.devs.at(lab))
            prior = sorted(os.path.join(os.path.dirname(pattern), f) for f in (g.response.get("filenames") or [])
                           if fnmatch.fnmatch(os.path.basename(f), os.path.basename(pattern))) if g.ok else []
            # Pre-BA retry signals: recent related commits (a command that runs git: the actor env first).
            c = self.bash(self.git(f"git log --oneline -n 30 --grep={shlex.quote(sc.keyword)}"),
                          "Recent related commits", f"Step 8 Bash git log {p.index}")
            commits = [l for l in c.response.get("stdout", "").split("\n") if l.strip()] if c.ok else []
            hyd_text = fill_curly(hyd, p.rec, {})
            o.run_text(hyd_text, f"{self.L}Step 8 Bash graphify hydrator {p.index}", "Graphify pre-BA hydrator")
            gdir = f".claude/dev-registry/{self.sid}-pipeline-{p.index}/graphify"
            gq = o.s.tool("Glob", {"pattern": "pre_query.json", "path": os.path.join(self.project, gdir)},
                          label=f"{self.L}Step 8 Glob pre_query {p.index}",
                          deviation=o.devs.at(f"{self.L}Step 8 Glob pre_query {p.index}"))
            extra_line = None
            if gq.ok and gq.response.get("filenames"):
                self.read(f"{gdir}/pre_query.json", f"Step 8 Read pre_query {p.index}")
                if self.load(f"{gdir}/pre_query.json").get("status") in ("ok", "degraded"):
                    extra_line = f"Pre-query context file: {gdir}/pre_query.json"
            fields = dict(tpl)
            pr = fields["prompt"]
            pr = re.sub(r"(recent_commits: )\[[^\]]*\][^\n]*", lambda m: m.group(1) + json.dumps(commits), pr)
            pr = re.sub(r"(existing_specs: )\[[^\]]*\][^\n]*", lambda m: m.group(1) + json.dumps(prior), pr)
            pr = re.sub(r"(prior_qa_failures: )\[[^\]]*\][^\n]*", lambda m: m.group(1) + "[]", pr)
            pr = re.sub(r"(retry_phrase: )<[^>\n]*>", lambda m: m.group(1) + "null", pr)
            if extra_line:
                pr = re.sub(r"^(\s*)(Codebase hints:.*)$", lambda m: f"{m.group(1)}{m.group(2)}\n{m.group(1)}{extra_line}",
                            pr, count=1, flags=re.M)
            fields["prompt"] = pr
            self.dispatch_ba(fields, p, f"Step 8 Agent(ba) pipeline {p.index}")

    def dispatch_ba(self, fields, p: Pipe, label: str):
        sc = p.sc
        content = devdrv._ba_content(p.sfx, "SMALL", sc)
        content["context.v1"]["development_approach"] = f"edit {sc.rel}: {sc.what}"
        sections = {"5": sc.requirement, "1": sc.before}
        act = agents.Act(content=content, status="ready", summary=sc.ba_summary, respell=self.o.respell,
                         work=lambda sub, b, pl: (_spec_updates(sub, b, sections), {})[1],
                         text_calls=[("Run Blast-Radius Tool Phase 1", {"<comma-separated files_to_modify>": sc.rel})])
        return self.dispatch(fields, act, label, p.sfx, atype="ba", pipe=p)

    def step9(self) -> None:
        self.todo_to(9)
        for p in self.pipes:
            for rel in (f"docs/dev/ticket-{p.sfx}.md", f"docs/dev/context-{p.sfx}.json"):
                self.read(rel, f"Step 9 Read {os.path.basename(rel).split('-')[0]} {p.index}")

    def pre_shell(self, tpl: dict, p: Pipe, label: str) -> None:
        """The shell lines a dispatch block runs before its Agent( line (the base's qa_mode flip)."""
        if tpl.get("pre"):
            self.o.run_text(fill_curly(tpl["pre"], p.rec, {}), self.L + label, "Pre-dispatch step of the block")

    def step10(self) -> None:
        o = self.o
        self.todo_to(10)
        tpl = agent_block(next(b.text for b in cmdtext.blocks(o.section("Step 10"), None) if "Agent(" in b.text))
        for p in self.pipes:
            self.pre_shell(tpl, p, f"Step 10 Bash qa_mode {p.index}")
            act = agents.Act(verdict="pass", summary="BA analysis checked")
            self.dispatch(dict(tpl), act, f"Step 10 Agent(qa) ba_validation pipeline {p.index}", p.sfx, atype="qa", pipe=p)
        for p in self.pipes:  # Process QA results per pipeline
            rel = f"docs/dev/ba-qa-report-{p.sfx}.json"
            self.read(rel, f"Step 10 Read ba-qa-report {p.index}")
            assert self.load(rel).get("verdict") == "pass"

    # ------------------------------------------------------------ Steps 11g-13
    def steps11g_12(self) -> None:
        o = self.o
        self.todo_to(11)
        g_tpl = o.template("Step 11g")
        d_tpl = agent_block(next(b.text for b in cmdtext.blocks(o.section("Step 12"), None) if "Agent(" in b.text))
        for k, p in enumerate(self.pipes):
            # Step 11g in progress before the graphify call (the next step in the list the first time).
            if k == 0:
                self.todo_to("11g")
            else:
                o.set_in_progress("11g", f"{self.L}TodoWrite Step 11g in_progress (pipeline {p.index})")
            self.ctx_rel = f"docs/dev/context-{p.sfx}.json"
            self.dispatch(g_tpl, agents.Act(summary="graphify enrichment"), f"Step 11g Agent(graphify) pipeline {p.index}",
                          p.sfx, atype="graphify", pipe=p)
            run_rel = f".claude/dev-registry/{self.sid}-pipeline-{p.index}/graphify/graphify-run.json"
            status = None
            if os.path.isfile(os.path.join(self.project, run_rel)):
                self.read(run_rel, f"Step 11g Read graphify-run {p.index}")
                status = self.load(run_rel).get("status")
            o.s.say(f"pipeline {p.index}: graphify status={status}")
            o.set_in_progress(12, f"{self.L}TodoWrite Step 12 in_progress (pipeline {p.index})")
            fields = dict(d_tpl)
            add = re.search(r"`(Graph context file: [^`]+)`", o.section("Step 11g"))
            if add and status in ("ok", "degraded"):
                fields = devdrv.with_lines(fields, [fill_curly(add.group(1).replace("${DEV_SESSION_ID}", self.sid), p.rec, {})])
            self.pre_shell(d_tpl, p, f"Step 12 Bash pre-dispatch {p.index}")
            sc = p.sc
            work = roles.dev([(sc.rel, sc.old, sc.final)], baseline_fallback=True)

            def dev_work(sub, b, pl, work=work):
                out = work(sub, b, pl)
                _spec_updates(sub, b, {"2": f"Attempt 1: {sc.what}", "3": f"{sc.rel}: {sc.dev_summary}"})
                return out
            act = agents.Act(work=dev_work, summary=sc.dev_summary)
            self.dispatch(fields, act, f"Step 12 Agent(dev) pipeline {p.index}", p.sfx, atype="dev", pipe=p)

    def step13(self) -> None:
        self.todo_to(13)
        for p in self.pipes:
            self.read(f"docs/dev/dev-report-{p.sfx}.json", f"Step 13 Read dev-report {p.index}")

    # ------------------------------------------------------------ Steps 14-18
    def step14(self) -> None:
        o = self.o
        self.todo_to(14)
        g = o.s.tool("Glob", {"pattern": "docker-compose.y*ml", "path": self.worktree},
                     label=self.L + "Step 14 Glob docker-compose", deviation=o.devs.at(self.L + "Step 14 Glob docker-compose"))
        found = g.response.get("filenames") if g.ok else []
        o.s.say("Step 14: " + ("docker-compose services found" if found else
                               "no docker-compose.yml: no project services to rebuild"))
        sec = o.section("Step 14")
        m = re.search(r"Output: `([\w.-]+\.json)` with per-pipeline steps", sec)
        if m:  # the base text: the orchestrator writes the QA verification plans itself
            plans = {"docker": {"rebuilt": False, "reason": "no docker-compose.yml"},
                     "pipelines": {str(p.index): {"timestamp_suffix": p.sfx, "steps": [
                         {"action": f"python3 -c \"{p.sc.ac['check'].get('call', '')}\"", "assert": p.sc.ac["then"]}]}
                         for p in self.pipes}}
            self.write(f"{self.sdir}/{m.group(1)}", json.dumps(plans, indent=2) + "\n", "Step 14 Write QA verification plans")

    def step15(self) -> None:
        o = self.o
        self.todo_to(15)
        tpl = agent_block(next(b.text for b in cmdtext.blocks(o.section("Step 15"), None) if "Agent(" in b.text))
        for p in self.pipes:
            self.pre_shell(tpl, p, f"Step 15 Bash qa_mode {p.index}")
            sc = p.sc
            work = roles.qa(e2e={"status": "legitimately_skipped", "blocking_reason": sc.no_e2e},
                            guard_respell=o.respell)

            def qa_work(sub, b, pl, work=work, sc=sc):
                out = work(sub, b, pl)
                _spec_updates(sub, b, {"4": f"{sc.measured.split(' ')[0]}: {sc.ac['then']} (measured after the change)"})
                return out
            act = agents.Act(verdict="pass", work=qa_work, summary="QA pass", respell=o.respell,
                             text_calls=[("Phase 6: Blast-Radius Phase 2 Verification", {})])
            self.dispatch(dict(tpl), act, f"Step 15 Agent(qa) pipeline {p.index}", p.sfx, atype="qa", pipe=p)

    def step16(self) -> None:
        self.todo_to(16)
        passed = 0
        for p in self.pipes:
            rel = f"docs/dev/qa-report-{p.sfx}.json"
            self.read(rel, f"Step 16 Read qa-report {p.index}")
            passed += (self.load(rel).get("qa") or {}).get("status") == "pass"
        self.o.s.say(f"Pipelines passed: {passed} of {len(self.pipes)}\nPipelines needing iteration: "
                     f"{len(self.pipes) - passed}\nPipelines parked: 0")
        if passed != len(self.pipes):
            raise RuntimeError("a QA did not pass: this driver plays no Step 17 iteration")

    def step18(self) -> None:
        o = self.o
        self.todo_to(17)
        o.s.say("Step 17: every pipeline passed QA; no iteration.")
        self.todo_to(18)
        for name, b, _ in o.step_blocks("Step 18"):
            o.run_text(b.text, f"{self.L}Step 18 Bash {name}", "Aggregate and apply the pipelines' permissions")

    # ------------------------------------------------------------ Steps 19-21
    def step19(self) -> None:
        o = self.o
        self.todo_to(19)
        sec = o.section("Step 19")
        log = re.search(r"running log\*\* at `([^`]+)`", sec).group(1)
        self.log_rel = o.bind(log)
        tpl = cmdtext.block(sec, None, lang="markdown")
        rows = "\n".join(f"| {p.index} | {p.rec['description']} | Fixed | 1 |" for p in self.pipes)
        entry = []
        for l in tpl.split("\n"):
            if re.match(r"^\| (?:0|1|\.\.\.) \|", l):
                if l.startswith("| 0 |"):
                    entry.append(rows)
                continue
            entry.append(l)
        entry = "\n".join(entry)
        entry = (entry.replace("<N>", str(self.n)).replace("{total_pipelines}", str(len(self.pipes)))
                 .replace("{fixed_count}", str(len(self.pipes))).replace("{parked_count}", "0"))
        entry = re.sub(r"^\*\*Assumptions \(Clause A\)\*\*:.*$", "**Assumptions (Clause A)**: none", entry, flags=re.M)
        entry = re.sub(r"^\*\*Parked\*\*:.*$", "**Parked**: none", entry, flags=re.M)
        entry = entry.replace("<timestamp>", utc_now())
        path = os.path.join(self.project, self.log_rel)
        old = agents.peek(self.rp, "main", path) if os.path.exists(path) else ""
        self.write(self.log_rel, (old.rstrip("\n") + "\n\n" if old else "") + entry.strip("\n") + "\n", "Step 19 Write cycle log")
        # TIME CHECK.
        code = next(c for c in cmdtext.inline_codes(o.text, "Step 19", "TIME CHECK")
                    if c.startswith("~/.claude/scripts/overnight-status.sh"))
        cmd = o.bind(code)
        if cmd.strip() == "~/.claude/scripts/overnight-status.sh" and "against the state file" in sec:
            cmd += " " + shlex.quote(self.state_file)
        tc = self.bash(cmd, "TIME CHECK", "Step 19 Bash TIME CHECK")
        self.expired = not tc.ok
        o.s.say(tc.response.get("stdout", "").strip() if tc.ok else f"TIME CHECK: {tc.error[:300]}")
        # Per-cycle commit (a command that runs git: the actor env first).
        commit = next(c for c in cmdtext.inline_codes(o.text, "Step 19", "chore(overnight)")
                      if "commit.sh" in c and "chore(overnight)" in c)
        cc = self.bash(self.git(o.bind(commit)), "End-of-cycle commit", "Step 19 Bash end-of-cycle commit")
        if not cc.ok:  # "log the failure to the cycle log and continue"
            path = os.path.join(self.project, self.log_rel)
            old = agents.peek(self.rp, "main", path)
            self.write(self.log_rel, old.rstrip("\n") + f"\n\n**End-of-cycle commit**: failed ({cc.error.splitlines()[0][:200]}); "
                       "refs/checkpoints/* snapshots remain.\n", "Step 19 Edit cycle log (commit failure)")

    def step20(self) -> None:
        o = self.o
        self.todo_to(20)
        self.final_cycle = bool(getattr(self, "expired", False))
        self.ts = self.stamp()
        self.rp.task(self.ts)
        retro_rel = f"{self.sdir}/retro-report-cycle{self.n}.json"
        doc = {"retro_id": f"rr-{self.ts}", "session_id": self.sid, "cycle_number": self.n, "timestamp": utc_now(),
               "is_final_cycle": self.final_cycle,
               "plan_vs_outcome": [{"triage_index": k, "description": p.rec["description"], "tier": 1,
                                    "pipeline_recommendation": "fix", "actual_outcome": "fixed", "iterations_used": 1,
                                    "failure_reason": None} for k, p in enumerate(self.pipes)],
               "cycle_stats": {"issues_triaged": len(self.pipes), "issues_attempted": len(self.pipes),
                               "issues_fixed": len(self.pipes), "issues_failed": 0, "issues_skipped": 0,
                               "fix_rate": 1.0, "focus_mode_used": True},
               "unresolved_issues": [], "patterns_noticed": ["unchecked argument types in the package's functions"],
               "recommendations_for_next_cycle": [], "qa_rerun_required": False, "qa_rerun_reasons": [],
               "final_summary": None}
        globs = [(f"qa-report-{self.pts}-*.json", "docs/dev"), (f"dev-report-{self.pts}-*.json", "docs/dev"),
                 ("retro-report-cycle*.json", self.sdir)]
        act = agents.Act(work=report_work(doc, (), globs), summary="retro written", status="completed")
        self.dispatch(o.template("Step 20"), act, "Step 20 Agent(pm) RETRO", self.ts, atype="pm")
        self.read(retro_rel, "Step 20 Read retro report (qa_rerun_required)")
        assert self.load(retro_rel).get("qa_rerun_required") is False

    def step21(self) -> None:
        o = self.o
        self.todo_to(21)
        if getattr(self, "expired", False):
            raise RuntimeError("the window closed before the owner's /stop: this driver plays no session-ending summary")
        # "Simply mark this step as completed via TodoWrite": every step completed, the loop hook fires.
        i = o.current()
        o.todos[i]["status"] = "completed"
        call = o._todo(f"{self.L}TodoWrite Step 21 done (all completed)")
        hook = "\n".join(h["stdout"] for h in (call.post.hooks if call.post else []) if h["verdict"] == "ok")
        if "Reset your todo list" in hook:
            # A fresh checklist (all pending, the first step in progress), then Step 1 done: the
            # working root is already established; resume from Step 2.
            self.cycle += 1
            o.todos = [dict(t, status="in_progress" if k == 0 else "pending") for k, t in enumerate(o.todos)]
            o._todo(f"{self.L}TodoWrite reset (loop)")
            self.read_paths = set()
        else:
            raise RuntimeError(f"the loop hook printed no reset after cycle {self.cycle}: {hook[-400:]!r}")

    # ------------------------------------------------------------ the cycle and the owner's /stop
    def run_cycle(self, until=None) -> bool:
        steps = [self.step2, self.step3, self.step4, self.step5, self.step6, self.step7, self.step8, self.step9,
                 self.step10, self.steps11g_12, self.step13, self.step14, self.step15, self.step16, self.step18,
                 self.step19, self.step20, self.step21]
        nums = [2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 14, 15, 16, 18, 19, 20, 21]
        for n, fn in zip(nums, steps):
            fn()
            if until is not None and n >= until:
                return False
        return True

    def owner_stop(self) -> None:
        """The owner interrupts the running turn and types /stop; the main agent runs stop.md's
        Implementation block once and ends its turn."""
        s = self.o.s
        s.append({"type": "user", "message": {"role": "user", "content": [
            {"type": "text", "text": "[Request interrupted by user]"}]}})
        st = Orchestrator(self.rp, "stop", session=s, deviations=self.o.devs,
                          respellings=STOP_RESPELLINGS if self.base_kit else ())
        st.slash("", label="/stop")
        for name, b, _ in st.step_blocks("Implementation"):
            st.run_text(b.text, f"/stop Bash {name}", "Release the overnight time-lock")
        s.stop("Overnight time-lock released (/stop). The working branch, the state record and the cycle log "
               "are left for review.", label="/stop Stop", deviation=self.o.devs.at("/stop Stop"))

    def run(self) -> None:
        self.launch()
        self.step1()
        until = int(self.rp.args["until"]) if self.rp.args.get("until") else None
        if self.variant == "stop":
            stop_at = int(self.rp.args.get("stop_at", "12"))
            self.run_cycle(until=stop_at)
            self.owner_stop()
            return
        if not self.run_cycle(until=until):
            return
        self.run_cycle()
        self.owner_stop()


VARIANTS = ("plain", "stop")


def run(rp) -> None:
    variant = rp.args.get("variant", "plain")
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}")
    rp.pipeline = "dev-overnight" if variant == "plain" else f"dev-overnight/{variant}"
    Night(rp, variant).run()
