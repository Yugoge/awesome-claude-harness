"""/dev, played compliantly from commands/dev.md of the tree under test: the singular cycle (N == 1)
and the fan-out cycle (N > 1 lanes, "Requirement Decomposition & Fan-Out").

The main agent types `/dev <requirement>`, reads DEV_SESSION_ID from the line of
the UserPromptSubmit hook's output the command text names, passes the checklist
the hook hands it (checked against scripts/todo/dev.py) to its first TodoWrite and
then completes one step per TodoWrite call. Each step does what the tree's text
for it says, read at run time: every Bash block of the step (cmdtext; the
fallback the text keeps for a missing hook output left out), placeholders bound to
the run's values and the shell variables a block reads bound as assignments;
every dispatch from its step's template (BA; QA in BA-validation mode; graphify,
when its sentinel exists if the text checks one; test-writer when
test_writer_expected; dev; QA), its obligation instantiated from the template;
the reads of the artifacts the step names; Step 11 completed without an
aggregate, as a single-dev cycle does; the completion report Step 17 names, its
resolver block, and the /spec-update --temp note where Step 17 still asks for
one; the summary; Stop. Where the tree's text differs (a hook-decided `Spec:`
line, a Step 16 that adds `QA report file:` instead of building a new context, no
temp note), the driver follows the tree it runs on. Subagents are played by
agents.Player (role work from roles.py); everything they write comes from their
obligation, the schemas and their agent files.

Fan-out (variants fanout, fanout-qa-fail): the typed requirement carries N outcomes. After Step 1's
parse the orchestrator decomposes them into a coverage map, one lane per outcome, and the
section's lane-execution adapter governs Steps 4-16: every dispatch of those steps is made once per
lane (BA, QA in BA-validation mode, graphify, test-writer where the lane's context expects it, dev,
QA), its placeholders bound per lane (`<timestamp>` / `<task_id>` / `$TASK_ID` become the lane's id,
`<requirement>` its text), its prompt carrying the three lane fields the section names, its
obligation the lane, the lane set and the profile the template's adapter line names; validation
and retry steps run per lane, retries on the affected lane only. Taken from the text at run time:
the lane suffix form (the adapter line's example), the lane id's base (the placeholder the adapter
line names), the fan-out profile, the three field names. The canonical aggregate's producer is
the one the tree's Step 11 names: where Step 11 has the orchestrator run the aggregator (the base
text), the driver runs that call (respelled, R3); where it names the lane-completeness hook, the
orchestrator runs none and marks the step completed. Step 17 indexes every lane's artifacts and the
canonical. When Step 17's resolver postcondition does not pass (a failed or refused call), the
Stop text reports the cycle not complete, as the step says. The framework's dispatch is synchronous, so a stage's "single parallel batch" is
played as consecutive dispatches, lane by lane, each lane's own pre-dispatch block (the base's
qa_mode flip) right before its dispatch; a stage's score header is computed once per stage.

Driver arguments (cli.py --arg K=V):
  variant=plain        BA ready, BA-QA pass, dev, QA pass (default)
  variant=qa-fail      the first final-verification QA fails; Step 16 refines the context and
                       the lane's dev is dispatched again; the next QA passes
  variant=question     BA writes its producer question; the orchestrator relays it with one
                       AskUserQuestion inside the turn and re-dispatches BA (Step 5) with the answer
  variant=ba-qa-fail   QA in BA-validation mode fails; BA is re-dispatched (Step 8); QA passes
  variant=fanout       a fan-out cycle of `lanes` lanes (default 2, at most 3), every lane passing
  variant=fanout-qa-fail  a fan-out cycle whose first lane's first QA fails; Step 16 re-dispatches
                       that lane's dev only and its QA passes; the other lanes are untouched
  lanes=N              fan-out lane count (2 or 3)
  lane_id=text|task    fan-out lane id base: `text` (default) the placeholder the adapter line
                       names (`<DEV_SESSION_ID>-<lane-suffix>` at 2acc29b and in the working tree);
                       `task` the cycle's task id where the tree's Step 1 names one apart from
                       DEV_SESSION_ID (`Task id:`), the id Step 17's resolver call takes. The two are
                       one id on the base text; where they differ the default follows the adapter line
  tier=STANDARD        BA's complexity_tier (STANDARD or COMPLEX: test-writer expected; SMALL or
                       MICRO: not)
  kept=<JSON>          [[hook, step, normalised text], ...]: the blocks the base kit's replay of the
                       same variant and settings recorded. Given, a declared deviation passes only a
                       block in that list (a kept base block); without it every declared deviation
                       passes (the base kit's own runs)

Respellings (P1b Scope row 7), applied by the driver only and only where the text still has
the old form; each application is recorded in blocks.json "respellings":
  R1 resolver      `python3 scripts/resolve-dev-artifact-chain.py` -> `python3 ~/.claude/scripts/...`
                   (Step 17, dev.md:1322 at 2acc29b): a product repository has no scripts/.
  R2 qa_mode flip  `bash ~/.claude/scripts/write-qa-mode.sh` gains
                   `CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"` as a
                   prefix when it has none (Steps 7 and 13, dev.md:609, :978): the CLI's Bash does
                   not export the variable and write-qa-mode.sh:35 exits without it (E5).
  R3 aggregator    `source venv/bin/activate && python3 scripts/aggregate-dev-report.py` ->
                   `CLAUDE_PROJECT_DIR=... python3 ~/.claude/scripts/aggregate-dev-report.py`
                   (Step 11, dev.md:885): the fan-out cycle's Step 11 call on the base text, with no
                   venv and CLAUDE_PROJECT_DIR in the call's environment (E5 (b)).
  R4 QA guard      `python3 scripts/qa-manifest-guard.py` -> `python3 ~/.claude/scripts/qa-manifest-guard.py`
                   (agents/qa.md:1137-1138, Phase 5 on a lane with test_writer_expected).
Not respelled (row 7): BA's and QA's blast-radius tool calls (ba.md:789, qa.md:1155) run as
written and fail; the replay goes on.

Deviations: DEVIATIONS below, one entry per block the base tree's (2acc29b) replay meets, each
with a comment quoting the hook's text; nothing else passes a block. On another tree an entry
whose block no longer occurs is a no-op.
"""
from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass, field

from .. import agents, cmdtext, roles
from ..pipeline import DROP, DROP_NEXT, Deviations, Orchestrator, Respelling, utc_now
from ..replay import Deviation

PIPELINE = "dev"

REQUIREMENT = ("add input validation to toy.add: raise TypeError naming the offending argument "
               "when an argument is not a number")

PROJECT_ROOT_PREFIX = 'CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}" '
RESPELLINGS = [
    Respelling("R1 resolver", r"(?<![\w/~.-])python3 scripts/resolve-dev-artifact-chain\.py",
               "python3 ~/.claude/scripts/resolve-dev-artifact-chain.py", "commands/dev.md Step 17"),
    Respelling("R2 qa_mode flip", r"(?<!\" )(?<![\w=])bash ~/\.claude/scripts/write-qa-mode\.sh",
               PROJECT_ROOT_PREFIX + "bash ~/.claude/scripts/write-qa-mode.sh", "commands/dev.md Steps 7, 13"),
    Respelling("R3 aggregator", r"source venv/bin/activate && python3 scripts/aggregate-dev-report\.py",
               PROJECT_ROOT_PREFIX + "python3 ~/.claude/scripts/aggregate-dev-report.py", "commands/dev.md Step 11"),
    Respelling("R4 QA guard", r"(?<![\w/~.-])python3 scripts/qa-manifest-guard\.py",
               "python3 ~/.claude/scripts/qa-manifest-guard.py", "agents/qa.md Phase 5"),
]

# Blocks the base tree's replay meets, each passed by a deviation at the step it occurs on: the
# refused call is applied as if allowed, so every later step runs and is traced.
DEVIATIONS = Deviations([
    # DEVIATION: "BLOCKED: removal-policy — UNRESOLVED option_value_removal_reference:date:-d=..."
    # pretool-bash-safety.sh refuses Step 1's auto-detect block (its `date -d` option value).
    ("Step 1 Bash SESSION_TS", Deviation(
        "hooks/pretool-bash-safety.sh", "UNRESOLVED option_value_removal_reference:date:-d",
        "Step 1's auto-detect block as the text spells it")),
    # DEVIATION: "BLOCKED: removal-policy — UNRESOLVED census_fatal:unbalanced:single_quote"
    # pretool-bash-safety.sh refuses Step 1's SPEC_ID block (the apostrophe in its comment).
    ("Step 1 Bash SPEC_ID", Deviation(
        "hooks/pretool-bash-safety.sh", "UNRESOLVED census_fatal:unbalanced:single_quote",
        "Step 1's SPEC_ID block as the text spells it")),
    # DEVIATION: "[Orchestrator Gate] BLOCKED: Bash used consecutively beyond limit (6/5)."
    # The text's Bash blocks between two dispatches outnumber the gate's cap of 5 (only an Agent
    # dispatch resets the count): Steps 1-4 before BA, Steps 14-17 after the last QA.
    ("*Bash*", Deviation(
        "hooks/pretool-orchestrator-gate.py", "Bash used consecutively beyond limit",
        "the command's own run of Bash blocks between dispatches")),
    # DEVIATION: "BLOCKED: Cannot complete Step 8 (\"Step 9: Graphify enrichment: dispatch graphify
    # subagent (advisory)\"). This step requires a subagent call (graphify) that has not been made."
    # Step 9 tells the orchestrator not to dispatch graphify when its sentinel is absent.
    ("TodoWrite Step 9 done, Step 10 in_progress", Deviation(
        "hooks/pretool-todo-validate.py", "This step requires a subagent call (graphify) that has not been made",
        "Step 9 skipped as the text says (graphify sentinel absent)")),
    # DEVIATION: "[Write Guard] BLOCKED: File already exists: /var/tmp/claude-scratch/update-<rand>.md"
    # /spec-update --temp (which Step 17 runs) creates the note with mktemp, reads it, then writes it.
    ("Step 17 Write update note", Deviation(
        "hooks/pretool-write-guard.sh", "[Write Guard] BLOCKED: File already exists",
        "the temp note mktemp created, written as /spec-update --temp says")),
])


class _KeptDeviation:
    """A declared deviation bound to its step label that passes only a kept base block."""

    def __init__(self, dev, label: str, kept: set):
        self.dev, self.label, self.kept = dev, label, kept
        self.hook, self.quote, self.why = dev.hook, dev.quote, dev.why

    def covers(self, block_hook: str, raw: str, text: str) -> bool:
        return self.dev.covers(block_hook, raw, text) and any(
            (block_hook, step, text) in self.kept for step in (self.label, self.label + " stop"))


class KeptOnly(Deviations):
    """The driver's deviations on a tree other than the base: each passes only a kept base block (the
    base kit's replay records the same hook, step and normalised text); any other block stays."""

    def __init__(self, inner: Deviations, kept):
        super().__init__(inner.pairs)
        self.kept = {tuple(k) for k in kept}

    def at(self, label: str) -> list:
        return [_KeptDeviation(d, label, self.kept) for d in super().at(label)]


# ---------------------------------------------------------------- the scenario

TOY_OLD = "def add(a, b):\n    return a + b\n"
TOY_PARTIAL = ("def add(a, b):\n    if not all(isinstance(x, (int, float)) for x in (a, b)):\n"
               "        raise TypeError()\n    return a + b\n")
TOY_FINAL = ("def add(a, b):\n    for name, x in ((\"a\", a), (\"b\", b)):\n"
             "        if not isinstance(x, (int, float)):\n"
             "            raise TypeError(f\"add(): argument {name} must be a number\")\n    return a + b\n")
AC = {"id": "AC-01", "type": "api", "given": "the toy package",
      "when": "add is called with a non-number second argument",
      "then": "it raises TypeError naming argument b",
      "check": {"call": "toy.add(1, '2')", "raises": "TypeError", "match": "argument b"}}
TEST_BODY = ("import os, sys\nsys.path.insert(0, os.getcwd())\nfrom toy import add\n"
             "with pytest.raises(TypeError, match=\"argument b\"):\n    add(1, \"2\")")

BA_QA_OBJECTION = {"dimension": "evidence_quality", "claim": "add has no input check",
                   "problem": "no reproduction is recorded",
                   "required_evidence": "the observed result of add('1', '2')"}
QA_FAILURE = {"severity": "critical", "primary_cause": "dev_implementation",
              "description": "TypeError carries no message naming the argument (AC-01)"}
QUESTION = {"need": "Which exception should add raise for a non-number argument?",
            "options": [{"label": "TypeError", "description": "the Python convention for a wrong type"},
                        {"label": "ValueError", "description": "treat it as a bad value"}],
            "default": "TypeError", "why": "the request names TypeError but a caller may expect ValueError"}


@dataclass(frozen=True)
class Scenario:
    """One requested outcome: the change, its acceptance criterion and the words its producers use."""
    requirement: str
    rel: str            # the one file the change touches
    old: str
    partial: str        # the first, incomplete fix of a QA-fail run
    final: str
    ac: dict
    test_body: str      # the generated test's body dev writes
    what: str
    why: str
    symptom: str
    root_cause: str
    keyword: str
    title: str
    measured: str
    before: str         # the reproduction BA records when QA objects to its evidence
    ba_summary: str
    dev_summary: str
    objection: dict
    qa_failure: dict
    question: dict
    no_e2e: str = "no user-facing surface: a library function"


SCENARIO = Scenario(
    REQUIREMENT, "toy/__init__.py", TOY_OLD, TOY_PARTIAL, TOY_FINAL, AC, TEST_BODY,
    what="type check in toy.add", why="non-numbers are added silently", symptom="add('1', '2') returns '12'",
    root_cause="add has no input check", keyword="toy.add", title="validate add's arguments",
    measured="add('1', '2') == '12'", before="add('1', '2') returned '12'",
    ba_summary="toy.add gets an argument type check", dev_summary="toy.add validates its arguments",
    objection=BA_QA_OBJECTION, qa_failure=QA_FAILURE, question=QUESTION)

SCENARIO_SUB = Scenario(
    "add input validation to toy.util.sub: raise TypeError naming the offending argument "
    "when an argument is not a number",
    "toy/util.py", "def sub(a,b): return a-b\n",
    "def sub(a, b):\n    if not all(isinstance(x, (int, float)) for x in (a, b)):\n"
    "        raise TypeError()\n    return a - b\n",
    "def sub(a, b):\n    for name, x in ((\"a\", a), (\"b\", b)):\n"
    "        if not isinstance(x, (int, float)):\n"
    "            raise TypeError(f\"sub(): argument {name} must be a number\")\n    return a - b\n",
    {"id": "AC-01", "type": "api", "given": "the toy package",
     "when": "sub is called with a non-number second argument", "then": "it raises TypeError naming argument b",
     "check": {"call": "toy.util.sub(1, '2')", "raises": "TypeError", "match": "argument b"}},
    "import os, sys\nsys.path.insert(0, os.getcwd())\nfrom toy.util import sub\n"
    "with pytest.raises(TypeError, match=\"argument b\"):\n    sub(1, \"2\")",
    what="type check in toy.util.sub", why="a non-number fails with an unrelated operand error",
    symptom="sub(1, '2') raises an unsupported-operand TypeError", root_cause="sub has no input check",
    keyword="toy.util.sub", title="validate sub's arguments",
    measured="sub(1, '2') raises TypeError: unsupported operand type(s)",
    before="sub(1, '2') raised an unsupported-operand TypeError",
    ba_summary="toy.util.sub gets an argument type check", dev_summary="toy.util.sub validates its arguments",
    objection={"dimension": "evidence_quality", "claim": "sub has no input check",
               "problem": "no reproduction is recorded", "required_evidence": "the observed result of sub(1, '2')"},
    qa_failure=QA_FAILURE,
    question={"need": "Which exception should sub raise for a non-number argument?",
              "options": QUESTION["options"], "default": "TypeError",
              "why": "the request names TypeError but a caller may expect ValueError"})

SCENARIO_README = Scenario(
    "document toy.add in README.md: add a usage line showing that add(2, 3) returns 5",
    "README.md", "# toy\n", "# toy\n\nUsage: add numbers with toy.add.\n",
    "# toy\n\nUsage: `from toy import add`; `add(2, 3)` returns 5.\n",
    {"id": "AC-01", "type": "data", "given": "the toy repository", "when": "README.md is read",
     "then": "it shows add(2, 3) returning 5", "check": {"file": "README.md", "contains": "add(2, 3)"}},
    "import os\nwith open(os.path.join(os.getcwd(), \"README.md\")) as fh:\n    assert \"add(2, 3)\" in fh.read()",
    what="a usage line for toy.add in README.md", why="README.md names no function",
    symptom="README.md holds only its title", root_cause="README.md has no usage line", keyword="README.md",
    title="document add in README.md", measured="README.md == '# toy'", before="README.md held only its title",
    ba_summary="README.md gets a usage line for toy.add", dev_summary="README.md shows how to call toy.add",
    objection={"dimension": "evidence_quality", "claim": "README.md has no usage line",
               "problem": "no reading of the file is recorded", "required_evidence": "README.md's content"},
    qa_failure={"severity": "critical", "primary_cause": "dev_implementation",
                "description": "the usage line does not show add(2, 3) (AC-01)"},
    question={"need": "Where should the usage line go?",
              "options": [{"label": "README.md", "description": "the file the request names"},
                          {"label": "docs/usage.md", "description": "a separate usage page"}],
              "default": "README.md", "why": "the request names README.md"},
    no_e2e="no user-facing surface: a documentation line")

# The fan-out scenario's outcomes, one per lane, each touching its own file.
FANOUT_SCENARIOS = (SCENARIO, SCENARIO_SUB, SCENARIO_README)


def _ba_content(tid: str, tier: str, sc: Scenario = SCENARIO) -> dict:
    return {
        "context.v1": {
            "requirement": {"original": sc.requirement, "clarified": sc.requirement,
                            "what": sc.what, "why": sc.why,
                            "where": [sc.rel], "success_criteria": [sc.ac["then"]]},
            "root_cause_analysis": {"symptom": sc.symptom, "root_cause": sc.root_cause,
                                    "affected_files": [sc.rel], "complaint_location_keywords": [sc.keyword],
                                    "located_source": [f"{sc.rel}:1"]},
            "waves": [{"wave_id": 1, "tasks": [{"task_id": "T1", "title": sc.title,
                                                "files_to_modify": [sc.rel]}]}],
            "complexity_tier": tier, "risk_level": "low", "diagnosis_layer": "L4",
            "affected_files": [sc.rel], "located_source": [f"{sc.rel}:1"],
            "complaint_location_keywords": [sc.keyword],
            "evidence": {"measured": {"value": sc.measured},
                         "expected": {"source": "the requirement"}},
            "scope_expansion": {"all_occurrences": [f"{sc.rel}:1"]},
        },
        "acceptance-criteria.v1": {"acceptance_criteria": roles.acceptance_criteria([sc.ac])},
    }


def with_lines(fields: dict, add_lines, context_rel: str | None = None) -> dict:
    """A template whose prompt gains lines the text adds after its `Context file:` line (Step 9's graph
    context line, Step 16's QA report line), or whose context file is replaced (Step 16 at 2acc29b)."""
    if not add_lines and not context_rel:
        return fields
    lines = fields["prompt"].split("\n")
    at = next(i for i, l in enumerate(lines) if l.strip().startswith("Context file:"))
    if context_rel:
        lines[at] = re.sub(r"(Context file:\s*)\S+", lambda m: m.group(1) + context_rel, lines[at])
    indent = lines[at][:len(lines[at]) - len(lines[at].lstrip())]
    lines[at + 1:at + 1] = [indent + l for l in add_lines]
    return dict(fields, prompt="\n".join(lines))


# ---------------------------------------------------------------- the cycle

# What one lane of a fan-out cycle holds on its own (the singular cycle is one implicit lane).
_LANE_STATE = {"tid": str, "sc": lambda: SCENARIO, "tag": str, "lane": lambda: None, "ba_outputs": list,
               "objections": list, "answers": list, "ba_question": lambda: None, "tw_expected": bool,
               "qa_report_rel": str, "iteration": int, "qa_round": int, "graph_lines": list}


@dataclass
class Lane:
    name: str           # the lane suffix
    rid: str            # its requirement_id in the coverage map
    sc: Scenario
    tid: str = ""       # the id its artifacts and obligations carry
    state: dict = field(default_factory=dict)


class DevCycle:
    def __init__(self, rp, variant: str, tier: str, scenario: Scenario = SCENARIO, typed: str | None = None,
                 session=None):
        self.rp, self.variant, self.tier = rp, variant, tier
        self.spec_id = ""
        self.score: dict = {}
        self.answers: list = []
        self.objections: list = []
        self.iteration = 0
        self.qa_round = 0
        self.sc, self.tag, self.lane = scenario, "", None
        self.ba_outputs: list = []
        self.ba_question = None
        self.tw_expected = False
        self.qa_report_rel = ""
        devs = DEVIATIONS
        if rp.args.get("kept"):
            devs = KeptOnly(DEVIATIONS, json.loads(rp.args["kept"]))
        self.o = Orchestrator(rp, "dev", session=session, deviations=devs, respellings=RESPELLINGS,
                              rules=self._rules(), line_rules=self._line_rules(), typed=typed)
        self.tid = self.reg = self.digits = ""   # the task id artifacts are named with; the registry id
        self.graph_lines: list = []

    # ------------------------------------------------------------ binding rules
    def _rules(self):
        return [
            (r"^DEV_SESSION_ID$", lambda m: self.reg),
            (r"^(?:timestamp|task_id|task-id)$", lambda m: self.tid),
            (r"^(?:YYYYMMDD-HHMMSS|same timestamp)$", lambda m: self.digits),
            (r"^(?:requirement from Step 1|original requirement|requirement)$", lambda m: self.sc.requirement),
            (r"^spec_path or null$", "null"),
            (r"^view_paths\.\w+ or null", "null"),
            (r"any file paths mentioned by user", lambda m: self.sc.rel),
            (r"one-line semantic summary", "null"),
            (r"^COMPLEX\|STANDARD\|SMALL\|MICRO", lambda m: self.tier),
            (r"^high\|medium\|low", "low"),
            (r"^baseline_head_sha captured", lambda m: self.o.values.get("baseline_head_sha", "")),
            (r"^baseline_dirty_snapshot captured",
             lambda m: json.dumps(self.o.values.get("baseline_dirty_snapshot", ""))),
            (r"^(\w+)_SCORE_HEADER prepended here", lambda m: self.score.get(m.group(1).lower(), "")),
            (r"^N$", lambda m: str(len(self.answers))),
            (r"JSON array of \{question, answer\} pairs", lambda m: json.dumps(self.answers)),
            (r"^accumulated hints$", lambda m: self.sc.rel),
            (r"JSON array of objections", lambda m: json.dumps(self.objections)),
            (r"^context_json_path$", lambda m: self.context_rel),
        ]

    def _line_rules(self):
        return [
            (r"^\s*SECOND ACTION \(only if SPEC_ID is non-empty", lambda l: l if self.spec_id else DROP),
            (r"fan-out Lane-execution adapter is active", lambda l: DROP),
            (r"^\s*<If codex_required = true, include the literal next line", lambda l: DROP_NEXT),
            (r"^\s*recent_commits: \[", lambda l: l[:l.index("[")] + json.dumps(self.commits)),
            (r"^\s*existing_specs: \[", lambda l: l[:l.index("[")] + "[]"),
        ]

    # ------------------------------------------------------------ helpers
    def step(self, n: int) -> str:
        return f"Step {n}"

    def L(self, label: str) -> str:
        """A step label carrying the current lane (`Step 7 [l1] ...`); unchanged in a singular cycle."""
        return re.sub(r"^(Step \d+)", lambda m: m.group(1) + self.tag, label, count=1) if self.tag else label

    def to(self, n: int) -> None:
        """Advance the checklist until Step n is in_progress (one completion per TodoWrite)."""
        while not self.o.at_step(n):
            self.o.advance()

    def score_header(self, step: int, agent: str) -> None:
        cmd = self.o.inline(f"Step {step}", "score-inject.sh", startswith="bash ")
        call = self.o.run(cmd, f"Mascot score header for {agent}", f"Step {step} Bash score-inject {agent}")
        self.score[agent] = call.response.get("stdout", "").rstrip("\n") if call.ok else ""

    def step_role(self, step: int):
        """The subagent_type the canonical checklist's item for Step <step> names (its subagent_call)."""
        todo = next(t for t in self.o.todos if re.match(rf"Step {step}\b", t["content"]))
        return (todo.get("subagent_call") or {}).get("subagent_type")

    def templates(self, step: int) -> list[dict]:
        """Every dispatch template of Step <step>, in order."""
        out, k = [], 0
        while True:
            try:
                out.append(self.o.template(f"Step {step}", index=k))
            except cmdtext.TextNotFound:
                return out
            k += 1

    def text_paths(self, step: int, anchor: str) -> list[str]:
        """The repository paths (inline code) of the paragraph of Step <step> that starts at the line
        holding `anchor`, placeholders bound; legacy names left out."""
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
        """A file the main agent has Read (its content, read again on the main agent's behalf)."""
        return json.loads(agents.peek(self.rp, "main", os.path.join(self.o.project, rel)))

    def _dispatch(self, fields: dict, act: agents.Act, label: str, subagent_type=None):
        """Every dispatch of the cycle: the task id the current lane carries (the cycle's own in a
        singular cycle)."""
        return self.o.dispatch(fields, act, label, self.tid, subagent_type=subagent_type)

    def iterations(self) -> int:
        return self.iteration

    # ------------------------------------------------------------ steps
    def start(self, typed_args: str | None = None) -> None:
        o = self.o
        o.slash(typed_args or self.sc.requirement)
        # "Read `DEV_SESSION_ID` [and `TASK_ID`] from the hook output above (line[s] `...: …`)":
        # the names and the hook lines the item quotes, in the same order.
        codes = cmdtext.inline_codes(o.text, "Step 1", "from the hook output")
        names = [c for c in codes if re.fullmatch(r"[A-Z_]+", c)]
        lines = [c for c in codes if c.rstrip().endswith(("…", "...")) and ":" in c]
        got = {n: o.hook_line(l) for n, l in zip(names, lines)}
        self.reg = got["DEV_SESSION_ID"]
        self.tid = got.get("TASK_ID", self.reg)  # one id unless the text names a separate task id
        for v in {self.reg, self.tid}:
            self.rp.task(v)
        self.digits = re.sub(r"^[A-Za-z-]*?(?=\d{8}-\d{6})", "", self.tid)
        req = re.search(r"User requirement document:\s*(\S+)", o.template("Step 4")["prompt"]).group(1)
        o.values.update(DEV_SESSION_ID=self.reg, TASK_ID=self.tid, timestamp=self.tid,
                        REQUIREMENT_DOC=o.bind(req), orchestrator_resolved_spec_path="")
        o.todo_start()

    def step1(self) -> None:
        o = self.o
        line = re.search(r"`(Spec: <[^`]*>)`", o.section("Step 1"))
        if line:  # the text has the hook decide the spec and print it as `Spec: <path>` / `Spec: none`
            v = o.hook_line(line.group(1))
            o.values["spec_path"] = "" if v == "none" else v
        # Every Bash block of Step 1 except the fallback the text keeps for a missing hook output.
        fallback = re.compile(r"(?i)\*\*fallback\*\*|hook output is absent|not in your context")
        o.run_step_blocks(1, skip=lambda name, b, para: bool(fallback.search(para)),
                          capture=("spec_path", "SPEC_ID", "CP_STATE_DIR"))
        self.spec_id = o.values.get("SPEC_ID", "")
        if not o.values.get("spec_path"):
            o.s.say("auto-detect skipped: newest spec predates this session")

    def step2(self) -> None:
        self.o.run_step_blocks(2)

    def step3(self) -> None:
        o = self.o
        o.s.say("ui-specialist: SKIP — a library function, no UI\narchitect: SKIP — one function in one module\n"
                "product-owner: SKIP — the request states the behaviour\nuser: SKIP — no end-to-end flow involved")
        c = o.s.bash("git log --oneline -n 5", "Recent commits touching the area", label="Step 3 Bash recent commits",
                     deviation=o.devs.at("Step 3 Bash recent commits"))
        self.commits = [l for l in c.response.get("stdout", "").split("\n") if l.strip()] if c.ok else []
        sec = o.section("Four Contracts Awareness")
        item = next(l for l in sec.split("\n") if "Existing BA specs" in l)
        pattern = re.findall(r"`([^`]+)`", re.sub(r"\(legacy:[^)]*\)", "", item))[0]
        o.s.tool("Glob", {"pattern": pattern, "path": o.project}, label="Step 3 Glob prior tickets",
                 deviation=o.devs.at("Step 3 Glob prior tickets"))

    def dispatch_ba(self, heading: str, label: str, question: bool = False, addressed=None):
        o, sc = self.o, self.sc
        content, notes = _ba_content(self.tid, self.tier, sc), ""
        if addressed:  # Step 8: BA answers each QA objection with evidence and updates its deliverables
            content["context.v1"]["qa_objections_addressed"] = [
                dict(ob, evidence=f"{sc.before} before the change") for ob in addressed]
            notes = "## QA objections addressed\n\n" + "\n".join(
                f"- {ob['dimension']}: {ob['required_evidence']} -> {sc.before}" for ob in addressed)
        if self.answers:
            content["context.v1"]["clarification_answers"] = list(self.answers)
        def ac_path(sub, b, player):  # the context names BA's own acceptance-criteria artifact
            return {"context.v1": {"acceptance_criteria_path": next(
                a["path"] for a in b.obligation["artifacts"] if a.get("schema") == "acceptance-criteria.v1")}}
        # ba.md Step 9: the blast-radius tool's Phase 1 run, as the agent text spells it (not respelled, row 7).
        calls = [("Run Blast-Radius Tool Phase 1", {"<comma-separated files_to_modify>": sc.rel})]
        act = agents.Act(question=dict(sc.question, schema=self.question_schema()) if question else None,
                         content=content, status="ready", notes=notes, work=ac_path,
                         text_calls=[] if question else calls, respell=o.respell,
                         summary=sc.ba_summary)
        return self._dispatch(o.template(heading), act, label, subagent_type=self.ba_type)

    def question_schema(self) -> str:
        m = re.search(r"\(schema ([\w.-]+\.v\d+)", self.o.section("Step 5"))
        if not m:
            raise cmdtext.TextNotFound("Step 5 names no question schema")
        return m.group(1)

    def step4_pre(self) -> None:
        self.score_header(4, "ba")
        self.ba_type = self.step_role(4)

    def step4_lane(self) -> None:
        d = self.dispatch_ba("Step 4", self.L("Step 4 Agent(ba)"), question=self.variant == "question")
        self.ba_question = d.player.question_written

    def step4(self) -> None:
        self.step4_pre()
        self.step4_lane()

    def step5(self) -> None:
        if not self.ba_question:
            return
        o = self.o
        q, answer = o.ask(self.ba_question, self.L("Step 5 AskUserQuestion"))
        self.answers.append({"question": q.get("need"), "answer": answer})
        d = self.dispatch_ba("Step 5", self.L("Step 5 Agent(ba) clarification round 1"))
        self.ba_question = d.player.question_written

    def step6(self, label: str = "Step 6") -> None:
        o = self.o
        self.ba_outputs = self.text_paths(6, "Read BA output files")
        for rel in self.ba_outputs:
            self.read(rel, f"{label} Read {rel}")
        o.run_step_blocks(6, label=label)

    @property
    def context_rel(self) -> str:
        """BA's context JSON: the JSON file among the BA outputs Step 6 names."""
        return next(p for p in self.ba_outputs if p.endswith(".json"))

    def step7(self, label: str = "Step 7", verdict: str = "pass") -> dict:
        o = self.o
        o.run_step_blocks(7, label=label)
        content = {}
        if verdict == "fail":
            content = {"*": {"objections": [self.sc.objection], "summary": "BA's root cause lacks evidence"}}
        act = agents.Act(verdict=verdict, content=content, summary="BA analysis checked")
        d = self._dispatch(o.template("Step 7"), act, f"{label} Agent(qa) ba_validation")
        rel = next(a["path"] for a in d.player.b.obligation["artifacts"] if a.get("kind") == "json")
        self.read(rel, f"{label} Read {rel}")
        return self.load(rel)

    def step8(self) -> None:
        o = self.o
        o.s.say(f"BA-QA iteration 1: QA found {len(self.objections)} objections in BA analysis. "
                "Re-invoking BA to address objections.")
        self.dispatch_ba("Step 8", self.L("Step 8 Agent(ba) BA-QA iteration 1"), addressed=self.objections)
        self.step6(self.L("Step 8 (Step 6 again)"))
        report = self.step7(self.L("Step 8 (Step 7 again)"), "pass")
        assert report.get("verdict") == "pass", report

    def step9_check(self) -> bool:
        """Whether graphify is dispatched: always, unless the text checks a sentinel the registry lacks."""
        o = self.o
        check = re.search(r"check whether the sentinel file exists at `([^`]+)`", o.section("Step 9"))
        if not check:
            return True
        path = re.sub(r"\$\{?CLAUDE_PROJECT_DIR\}?", o.project, check.group(1)).replace("$DEV_SESSION_ID", self.reg)
        g = o.s.tool("Glob", {"pattern": os.path.basename(path), "path": os.path.dirname(path)},
                     label="Step 9 Glob graphify sentinel", deviation=o.devs.at("Step 9 Glob graphify sentinel"))
        return bool(g.ok and g.response.get("filenames"))

    def step9_lane(self, dispatch: bool) -> None:
        o = self.o
        if dispatch:
            self._dispatch(o.template("Step 9"), agents.Act(), self.L("Step 9 Agent(graphify)"))
            # The record the text says to take graphify's status from, and the line it adds to the
            # dev and QA prompts when that status is ok or degraded.
            sec = o.section("Step 9")
            status = None
            for code in re.findall(r"`(\.claude/dev-registry/<DEV_SESSION_ID>/graphify/[\w.-]+\.json)`", sec):
                path = os.path.join(o.project, o.bind(code))
                if os.path.isfile(path):
                    o.s.read(path, label=self.L(f"Step 9 Read {os.path.basename(path)}"))
                    status = json.loads(agents.peek(self.rp, "main", path)).get("status")
                    break
            o.s.say(f"graphify_status={status}")
            add = re.search(r"`(Graph context file:[^`]+)`", sec)
            if add and status in ("ok", "degraded"):
                self.graph_lines = [o.bind(add.group(1))]
        else:
            o.s.say("graphify_status=skipped/sentinel_absent")

    def step9(self) -> None:
        self.step9_lane(self.step9_check())

    def step10_tw(self) -> None:
        """Step 10's test-writer gate and, when the context expects it, the test-writer dispatch and
        the on-disk check of what it wrote."""
        o = self.o
        ctx = self.load(self.context_rel)
        skip = ctx.get("_test_writer_skip_reason")
        self.tw_expected = (not skip) and (ctx.get("complexity_tier") in ("STANDARD", "COMPLEX")
                                          or ctx.get("risk_level") == "high")
        if self.tw_expected:  # the Step 10 template other than the dev dispatch's: the test-writer pre-dispatch
            fields = next(t for t in self.templates(10)
                          if (t.get("subagent_type") or agents.registry_role(t["prompt"])) != self.step_role(10))
            self._dispatch(fields, agents.Act(work=roles.test_writer()), self.L("Step 10 Agent(test-writer)"))
            for rel in self.text_paths(10, "After the test-writer subagent completes, verify on disk"):
                self.read(rel, self.L(f"Step 10 Read {rel}"))

    def step10_pre(self) -> None:
        """Step 10's score header and its pre-dispatch baseline capture."""
        self.score_header(10, "dev")
        self.o.run_step_blocks(10, capture=("baseline_head_sha", "baseline_dirty_snapshot"))

    def step10_dev(self) -> None:
        sc = self.sc
        self.dispatch_dev(self.L("Step 10 Agent(dev)"),
                          sc.partial if self.variant in ("qa-fail", "fanout-qa-fail") and self.fails_first() else sc.final,
                          sc.old)

    def fails_first(self) -> bool:
        """Whether this lane's first final-verification QA fails (a qa-fail run)."""
        return True

    def step10(self) -> None:
        self.step10_tw()
        self.step10_pre()
        self.step10_dev()

    def dispatch_dev(self, label: str, new_code: str, old_code: str, context_rel: str | None = None,
                     add_lines=()):
        o, sc = self.o, self.sc
        tpl = next(t for t in self.templates(10)
                   if (t.get("subagent_type") or agents.registry_role(t["prompt"])) == self.step_role(10))
        fields = with_lines(tpl, list(add_lines) + self.graph_lines, context_rel)
        baseline = {"baseline_head_sha": o.values.get("baseline_head_sha", ""),
                    "baseline_dirty_snapshot": o.values.get("baseline_dirty_snapshot", "")}
        work = roles.dev([(sc.rel, old_code, new_code)], test_bodies={"*": sc.test_body} if self.tw_expected
                         else None)
        act = agents.Act(work=work, content={"*": baseline}, summary=sc.dev_summary)
        return self._dispatch(fields, act, label, subagent_type=self.step_role(10))

    def step12(self, label: str = "Step 12") -> None:
        for rel in self.text_paths(12, "Read dev implementation report"):
            self.read(rel, f"{label} Read {rel}")

    def step13_blocks(self, label: str = "Step 13") -> None:
        self.qa_round += 1
        self.o.run_step_blocks(13, label=label)

    def step13_dispatch(self, label: str = "Step 13", verdict: str = "pass") -> None:
        o, sc = self.o, self.sc
        extra = {}
        if verdict == "fail":
            extra = {"qa": {"failures": [sc.qa_failure], "overall_assessment": "AC-01 not met",
                            "refined_context": {"must": "name the offending argument in the TypeError message"}}}
        work = roles.qa(e2e={"status": "legitimately_skipped", "blocking_reason": sc.no_e2e},
                        guard_respell=o.respell, extra=extra)
        # qa.md Phase 6: the blast-radius tool's Phase 2 run, as the agent text spells it (not respelled, row 7).
        act = agents.Act(verdict=verdict, work=work, summary=f"QA {verdict}", respell=o.respell,
                         text_calls=[("Phase 6: Blast-Radius Phase 2 Verification", {})])
        self._dispatch(with_lines(o.template("Step 13"), self.graph_lines), act, f"{label} Agent(qa)")

    def step13(self, label: str = "Step 13", verdict: str = "pass") -> None:
        self.step13_blocks(label)
        self.score_header(13, "qa")
        self.step13_dispatch(label, verdict)

    def step14(self, label: str = "Step 14") -> str:
        o = self.o
        rel = self.qa_report_rel = self.text_paths(14, "Read QA report")[0]
        self.read(rel, f"{label} Read {rel}")
        status = (self.load(rel).get("qa") or {}).get("status")
        sec = o.section("Step 14")
        first = next(c for c in re.findall(r"`([^`\n]+)`", sec) if c.startswith("bash ") and "score-update.sh" in c)
        script = first.split(" --", 1)[0]
        if status == "pass":
            item = "Second-or-later-round PASS" if self.iteration else "First-round PASS"
            codes = cmdtext.inline_codes(o.text, "Step 14", item)
            cmds = [c if c.startswith("bash ") else f"{script} {c}" for c in codes if "--agent" in c]
        else:
            codes = cmdtext.inline_codes(o.text, "Step 14", '`primary_cause = "dev_implementation"`')
            cmds = [c if c.startswith("bash ") else "bash ~/.claude/scripts/" + c for c in codes if "--agent" in c]
        for k, cmd in enumerate(cmds, 1):
            o.run(o.bind(cmd), "Mascot score update", f"{label} Bash score-update {k}")
        return status

    def step15(self, label: str = "Step 15") -> None:
        o = self.o
        perms = ((self.load(self.qa_report_rel).get("qa") or {}).get("permissions_verification")
                 or {}).get("validated_permissions") or []
        # The text's per-permission jq edit (an example entry) runs once per validated permission: none here.
        o.run_step_blocks(15, skip=lambda name, b, para: "permissions.allow +=" in b.text and not perms,
                          label=label)

    def step16(self) -> None:
        o, sc = self.o, self.sc
        self.iteration += 1
        o.values["N"] = str(self.iteration)
        rules = [(r"^N$", str(self.iteration))]
        o.run_step_blocks(16, extra_rules=rules, label=self.L("Step 16"))
        # "Return to Step 10 with new context JSON": the context file a Step 16 block writes, if any.
        ctx_tpl = re.search(r"Context file:\s*(\S+)", next(
            t["prompt"] for t in self.templates(10) if "Context file:" in t["prompt"])).group(1)
        ctx_rx = re.escape(ctx_tpl.split("<", 1)[0]) + r"\S*\.json"
        new_ctx = None
        for _name, b, _para in o.step_blocks("Step 16"):
            for t in re.findall(r">\s*(" + ctx_rx + ")", o.bind(b.text, rules)):
                new_ctx = t
        # Lines the text adds to Step 10's template for the re-dispatch ("adding the line `X: path`").
        add = [o.bind(c) for c in re.findall(r"`([A-Z][\w ]* file:\s*[^`\s]+)`", o.section("Step 16"))]
        self.dispatch_dev(self.L(f"Step 16 Agent(dev) iteration {self.iteration}"), sc.final, sc.partial,
                          new_ctx, add)
        self.step12(self.L("Step 16 (Step 12 again)"))
        self.step13(self.L("Step 16 (Step 13 again)"), "pass")
        status = self.step14(self.L("Step 16 (Step 14 again)"))
        assert status == "pass", status
        self.step15(self.L("Step 15"))

    def files_generated(self, lines: list) -> list:
        """Step 17's template lines, the "Files Generated" list as a single-lane cycle fills it."""
        out = []
        for l in lines:  # a single-lane cycle lists its own artifacts, not the fan-out ones
            if "Fan-out cycle" in l or "Per lane `<lane>`" in l or "Aggregate Dev Report" in l:
                continue
            out.append(l)
            if l.startswith("- Context:"):  # the five-artifact contract Step 17 states includes the ticket
                ticket = next(p for p in self.ba_outputs if p.endswith(".md"))
                out.insert(len(out) - 1, f"- Ticket: `{ticket}`")
        return out

    def step17(self) -> None:
        o = self.o
        tpl = o.block("Step 17", anchor="Development Completion Report")
        report = o.bind("\n".join(self.files_generated(tpl.split("\n"))),
                        [(r"^ISO-8601$", utc_now()), (r"^N$", str(self.iterations()))])
        rel = self.text_paths(17, "Save report to")[0]
        o.s.write(os.path.join(o.project, rel), report, label="Step 17 Write completion report",
                  deviation=o.devs.at("Step 17 Write completion report"))
        # The resolver postcondition: completion needs its exit 0 (a refused or failed call is not one).
        calls = o.run_step_blocks(17, capture=("ARTIFACT_CHAIN",))
        self.chain_ok = all(c.ok for c in calls)
        if "/spec-update --temp" not in o.section("Step 17"):
            return
        # Workflow update: all requested work is complete -> /spec-update --temp, as that command's text says.
        su = Orchestrator(self.rp, "spec-update", session=o.s, deviations=o.devs)
        mk = su.inline("Temp-note mode", "mktemp", startswith="mktemp")
        c = o.run(mk, "Create the temp update note", "Step 17 Bash mktemp update note")
        path = c.response.get("stdout", "").strip() if c.ok else ""
        if path:
            m = re.search(r"update-([A-Za-z0-9]+)\.md$", path)
            if m:
                self.rp.rand(m.group(1))
            o.s.read(path, label="Step 17 Read update note", deviation=o.devs.at("Step 17 Read update note"))
            note = su.block("Temp-note mode", anchor="# Update")
            note = su.bind(note, [(r"^ISO-8601$", utc_now()), (r'id or "unknown"', self.tid),
                                  (r"^spec\|dev\|close", "dev"), (r"exact next command", f"/close {self.tid}"),
                                  (r".", "see the completion report")])
            o.s.write(path, note, label="Step 17 Write update note", deviation=o.devs.at("Step 17 Write update note"))

    def not_complete(self) -> str:
        """The Stop text when Step 17's resolver postcondition did not pass ("exit 2 or any other status
        blocks"): the cycle is not reported complete."""
        return (f"/{self.o.typed} {self.tid}: QA passed, but the completion postcondition "
                "(resolve-dev-artifact-chain.py) did not pass, so the cycle is not complete.")

    def stop(self) -> None:
        o = self.o
        text = (f"/{o.typed} {self.tid} complete: {self.sc.dev_summary}; QA passed. Next: /close {self.tid}"
                if getattr(self, "chain_ok", True) else self.not_complete())
        o.s.stop(text, label="Stop", deviation=o.devs.at("Stop"))

    # ------------------------------------------------------------ the whole cycle
    def run(self) -> None:
        o = self.o
        self.start()
        self.step1()
        self.to(2); self.step2()
        self.to(3); self.step3()
        self.to(4); self.step4()
        self.to(5); self.step5()
        self.to(6); self.step6()
        self.to(7)
        report = self.step7(verdict="fail" if self.variant == "ba-qa-fail" else "pass")
        self.to(8)
        if report.get("verdict") == "fail":
            self.objections = report.get("objections") or []
            self.step8()
        self.to(9); self.step9()
        self.to(10); self.step10()
        self.to(11)
        o.s.say("Step 11 waived: single-dev cycle (N == 1); the dev writes the canonical report itself.")
        self.to(12); self.step12()
        self.to(13); self.step13(verdict="fail" if self.variant == "qa-fail" else "pass")
        self.to(14)
        status = self.step14()
        self.to(15)
        if status == "pass":
            self.step15()
        self.to(16)
        if status != "pass":
            self.step16()
        self.to(17); self.step17()
        o.advance()
        self.stop()


# ---------------------------------------------------------------- the fan-out cycle

class FanoutCycle(DevCycle):
    """N > 1 lanes in one cycle, as the "Requirement Decomposition & Fan-Out" section and the steps it
    changes say."""

    def __init__(self, rp, variant: str, tier: str, n: int, lane_id: str = "text"):
        super().__init__(rp, variant, tier)
        if not 2 <= n <= len(FANOUT_SCENARIOS):
            raise ValueError(f"lanes must be 2..{len(FANOUT_SCENARIOS)}, not {n}")
        if lane_id not in ("text", "task"):
            raise ValueError(f"lane_id must be text or task, not {lane_id!r}")
        self.n, self.lane_id = n, lane_id
        self.lanes: list[Lane] = []
        self.typed_args = f"{n} independent changes in one cycle: " + "; ".join(
            f"({k}) {sc.requirement}" for k, sc in enumerate(FANOUT_SCENARIOS[:n], 1))
        self.read_fanout_text()

    # ------------------------------------------------------------ the text's fan-out rules
    def read_fanout_text(self) -> None:
        o = self.o
        adapter = next((l for l in o.template("Step 4")["prompt"].split("\n")
                        if "Lane-execution adapter is active" in l), None)
        if adapter is None:
            raise cmdtext.TextNotFound("Step 4's template has no fan-out lane-execution adapter line")
        self.o.profile = re.search(r'profile="([^"]+)"', adapter).group(1)
        self.suffix = re.search(r'lane="<lane-suffix>"\s*\(e\.g\.\s*"([A-Za-z]+)\d+"\)', adapter).group(1)
        self.base_name = re.search(r'becomes\s+"<([A-Za-z_]+)>-<lane-suffix>"', adapter).group(1)
        sec = o.section("Requirement Decomposition")
        para = next(p for p in re.split(r"\n\s*\n", sec) if "explicit fields" in p)
        fields = re.search(r"explicit fields\s*[—-]+\s*(.*?)\s+[—-]+\s", para, re.S).group(1)
        self.lane_fields = re.findall(r"`([^`]+)`", fields)
        if len(self.lane_fields) != 3:
            raise cmdtext.TextNotFound(f"the fan-out section names {self.lane_fields} as the lane fields")

    # ------------------------------------------------------------ lanes
    @contextmanager
    def on(self, lane: Lane):
        """Work on one lane: its own state in place of the cycle's, its id for `<timestamp>`, `<task_id>`
        and `$TASK_ID`, its text for `<requirement>`."""
        outer = {k: getattr(self, k) for k in _LANE_STATE}
        for k, fresh in _LANE_STATE.items():
            setattr(self, k, lane.state[k] if k in lane.state else fresh())
        self.tid, self.sc, self.tag, self.lane = lane.tid, lane.sc, f" [{lane.name}]", lane
        values = {k: self.o.values.get(k) for k in ("timestamp", "TASK_ID")}
        self.o.values.update(timestamp=lane.tid, TASK_ID=lane.tid)
        try:
            yield lane
        finally:
            lane.state = {k: getattr(self, k) for k in _LANE_STATE}
            for k, v in outer.items():
                setattr(self, k, v)
            self.o.values.update(values)

    def each(self, fn, lanes=None) -> dict:
        out = {}
        for lane in lanes if lanes is not None else self.lanes:
            with self.on(lane):
                out[lane.name] = fn()
        return out

    @property
    def lane_set(self) -> list:
        return [l.name for l in self.lanes]

    def _dispatch(self, fields: dict, act: agents.Act, label: str, subagent_type=None):
        if self.lane is None:
            return super()._dispatch(fields, act, label, subagent_type)
        # The three lane fields every lane dispatch carries, after the requirement document line (or the
        # FIRST ACTION line where the template has none).
        lines = fields["prompt"].split("\n")
        at = next((i for i, l in enumerate(lines) if l.strip().startswith("User requirement document:")),
                  next(i for i, l in enumerate(lines) if "FIRST ACTION" in l))
        indent = lines[at][:len(lines[at]) - len(lines[at].lstrip())]
        rid, text, parent = self.lane_fields
        lines[at + 1:at + 1] = [f"{indent}{rid}: {self.lane.rid}", f"{indent}{text}: {self.sc.requirement}",
                                f"{indent}{parent}: {self.o.values['REQUIREMENT_DOC']}"]
        return self.o.dispatch(dict(fields, prompt="\n".join(lines)), act, label, self.tid,
                               subagent_type=subagent_type, lane=self.lane.name, lane_set=self.lane_set)

    def fails_first(self) -> bool:
        return self.lane is self.lanes[0]

    def iterations(self) -> int:
        return max((l.state.get("iteration", 0) for l in self.lanes), default=0)

    # ------------------------------------------------------------ steps
    def decompose(self) -> None:
        """The coverage-mapped lane set: one lane per separately requested outcome, its suffix in the
        form the adapter line shows, its id the adapter line's base (or the cycle's task id) and suffix."""
        o = self.o
        base = o.values[self.base_name] if self.lane_id == "text" else self.tid
        for k, sc in enumerate(FANOUT_SCENARIOS[:self.n], 1):
            lane = Lane(f"{self.suffix}{k}", f"R{k}", sc, f"{base}-{self.suffix}{k}")
            self.rp.lane(lane.name)
            self.rp.task(lane.tid)
            self.lanes.append(lane)
        o.s.say("Requirement decomposition (coverage map):\n" + json.dumps({
            "requirements": [{"requirement_id": l.rid, "text": l.sc.requirement} for l in self.lanes],
            "coverage_map": {f"outcome {k}": l.rid for k, l in enumerate(self.lanes, 1)},
            "lanes": {l.rid: l.name for l in self.lanes}}, indent=2))

    def step11(self) -> None:
        """The canonical aggregate's producer as the tree's Step 11 names it."""
        o = self.o
        calls = [c for c in re.findall(r"`([^`\n]+)`", o.section("Step 11"))
                 if re.search(r"aggregate-dev-report\.py\s+--task-id", c)]
        if calls:  # the base text: the orchestrator runs the aggregator once every lane's dev has returned
            o.run_text(calls[0], "Step 11 Bash aggregate-dev-report.py",
                       "Write the canonical aggregate dev-report from the lane reports")
        else:
            o.s.say("Step 11: every lane's dev has returned; the canonical aggregate's producer is the "
                    "lane-completeness hook, so the orchestrator runs no aggregator.")

    def files_generated(self, lines: list) -> list:
        """The fan-out form of "Files Generated": every lane's artifacts (each with its directory), then
        the aggregate; the single-lane entries left out."""
        out, single = [], False
        for l in lines:
            if "Single-lane cycle" in l:
                single = True
                continue
            if single:
                if l.startswith("- "):
                    continue
                single = False
            if "Per lane `<lane>`" in l:
                for lane in self.lanes:
                    row = l.replace("<timestamp>-<lane>", lane.tid).replace("<lane>", lane.name)
                    codes = re.findall(r"`([^`]+)`", row)
                    d = next((os.path.dirname(c) for c in codes if "/" in c), "")
                    out.append(re.sub(r"`([^`/]+\.(?:md|json))`", lambda m: f"`{d}/{m.group(1)}`", row))
                continue
            out.append(l)
        return out

    def stop(self) -> None:
        o = self.o
        text = (f"/{o.typed} {self.tid} complete: " + "; ".join(
            f"lane {l.name}: {l.sc.dev_summary}" for l in self.lanes) + "; every lane's QA passed. "
            f"Next: /close {self.tid}") if getattr(self, "chain_ok", True) else self.not_complete()
        o.s.stop(text, label="Stop", deviation=o.devs.at("Stop"))

    def run(self) -> None:
        o = self.o
        self.start(self.typed_args)
        self.step1()
        self.decompose()
        self.to(2); self.step2()
        self.to(3); self.step3()
        self.to(4); self.step4_pre(); self.each(self.step4_lane)
        self.to(5); self.each(self.step5)
        self.to(6); self.each(lambda: self.step6(self.L("Step 6")))
        self.to(7)
        reports = self.each(lambda: self.step7(self.L("Step 7"), "pass"))
        self.to(8)
        failed = [l for l in self.lanes if reports[l.name].get("verdict") == "fail"]
        for lane in failed:  # retry only the affected lanes
            with self.on(lane):
                self.objections = reports[lane.name].get("objections") or []
                self.step8()
        self.to(9)
        dispatch = self.step9_check()
        self.each(lambda: self.step9_lane(dispatch))
        self.to(10)
        self.each(self.step10_tw)
        self.step10_pre()
        self.each(self.step10_dev)
        self.to(11); self.step11()
        self.to(12); self.each(lambda: self.step12(self.L("Step 12")))
        self.to(13)
        self.score_header(13, "qa")
        def qa():
            self.step13_blocks(self.L("Step 13"))
            self.step13_dispatch(self.L("Step 13"), "fail" if self.variant == "fanout-qa-fail" and self.fails_first()
                                 else "pass")
        self.each(qa)
        self.to(14)
        status = self.each(lambda: self.step14(self.L("Step 14")))
        self.to(15)
        self.each(lambda: self.step15(self.L("Step 15")), [l for l in self.lanes if status[l.name] == "pass"])
        self.to(16)
        self.each(self.step16, [l for l in self.lanes if status[l.name] != "pass"])  # the failed lanes only
        self.to(17); self.step17()
        o.advance()
        self.stop()


VARIANTS = ("plain", "qa-fail", "question", "ba-qa-fail", "fanout", "fanout-qa-fail")


def run(rp) -> None:
    variant = rp.args.get("variant", "plain")
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}")
    tier = rp.args.get("tier", "STANDARD")
    if variant.startswith("fanout"):
        n = int(rp.args.get("lanes", "2"))
        rp.pipeline = f"dev/{variant}" + (f"-{n}" if n != 2 else "")
        FanoutCycle(rp, variant, tier, n, rp.args.get("lane_id", "text")).run()
        return
    rp.pipeline = f"dev/{variant}" if variant != "plain" else "dev"
    DevCycle(rp, variant, tier).run()
