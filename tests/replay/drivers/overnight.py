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
  - Step 4: the cycle number as the text reads it (`overnight.py cycle-index <STATE_FILE>`, the `Cycle:`
    line of overnight-status.sh, or the state record's cycle_count), PM TRIAGE from the template, the
    pipeline_blocked Read; on a text with the "Cycle Contract Manifest" (the base), the
    orchestrator's contract: its primary and mirror Writes and the cycle-current.json symlink, its
    fields from the section's bullets, its BA/dev/QA/graphify entries from the section's inline
    examples, the entries of the other dispatches the cycle commits to from those dispatches' own
    templates;
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
    Step 16: the QA reports Read; Step 17: every pipeline passed, nothing to iterate (variant
    qa-fail: Step 16 marks each pipeline's phase in the pipelines file the iteration plan reads, and
    Step 17 iterates, see below);
  - Step 18: the permissions block; Step 19: the cycle log, the TIME CHECK, the per-cycle commit
    where the text has one (the base's; its failure logged); Step 20: PM RETRO, the retro Read;
    Step 21: marked completed, the loop hook's reset (a fresh checklist, Step 1 done, Step 2 in
    progress);
* the owner interrupts and types /stop; the main agent runs stop.md's Implementation block once
  and stops.

A dispatch the hooks refuse that no declared deviation passes (on the working tree: any block that
is not a kept base block) leaves the orchestrator no compliant way on; the driver records it, the
cycle stops there, and the owner's /stop ends the session.

Subagents are played by agents.Player: PM (PLAN, TRIAGE, RETRO), the specialists, BA, QA, graphify
and dev, each from its dispatch prompt and its agent file (roles.py for dev's and QA's work). Where
a dispatch's obligation declares its report (the working tree's PM and specialist templates), the
Player writes it from the schema; where none does (the base's), the role writes the file its
prompt's "Output ... to:" / "Write ... to:" line names, with the same content. On the base text the
subagents also write the overnight spec sections their prompts tell them to update.

The scenario: cycle 1's specialists find toy.add and toy.util.sub accepting non-numbers (dev.py's
two scenarios), cycle 2's a README with no usage line and a package that does not export sub; PM
triages each pair into two `fix` pipelines; BA-QA and QA pass every pipeline (variant qa-fail: pipeline 0's
first fix leaves the TypeError without the argument's name, its QA fails, and its Step 17 iteration fixes it).

Driver arguments (cli.py --arg K=V):
  variant=plain   two cycles, then the owner's /stop inside cycle 3's window (default)
  variant=stop    the owner's /stop inside cycle 1's window, once Step `stop_at` (default 12) is done
  variant=qa-fail one cycle whose pipeline 0 fails its first QA (its dev's first fix is incomplete),
                  then the owner's /stop inside cycle 2's window. Step 16 marks each pipeline's phase
                  (done and fixed, or qa_failed) in the pipelines file; Step 17, as the tree's text
                  says: the iteration plan's block, the plan Read, and for each entry the pipeline's
                  iteration incremented in the pipelines file, the text's per-iteration blocks (the
                  base's context refinement), the Step 11g precondition at the new iteration, dev from
                  Step 12's template with the lines Step 17 adds (the base's iteration context in place
                  of the context file), the qa_mode write the text has before QA (the base's), QA from
                  Step 15's template, its report Read, and the pipeline marked done and fixed on a pass
  variant=unattended  D20's unattended decision: one cycle in a window of `window` minutes (default
                  10) typed as the end time; pipeline 0 meets, inside the window, a producer question an
                  experiment settles (its BA, Step 8), a stand-in spec-declared user gate (its dev
                  dispatch, Step 12) and a producer question no experiment settles (its dev, Step 12).
                  Each is decided without the owner as Hard Rule 5 and Clause B say: BA is re-dispatched
                  with the decision, its options and the experiment, runs it and records decision,
                  options, experiment, result and chosen option in its context JSON (Step 9 copies it);
                  the gate and dev's question take their default, written as the text's `Decision
                  without the owner:` line into the dev dispatch and Step 13's dev re-dispatch (after
                  Step 11g's fingerprint check). Both pipelines pass QA; the cycle log and the summary
                  list the three decisions, the gate first. The window's end is waited for before Step
                  19's TIME CHECK (the replay's cycle is shorter than a real one), so Steps 20 and 21
                  take the session-ending branch: the final retro, the summary, the announcement, then
                  the main agent's Stop, which the time-lock lets through once retro and summary exist.
                  Injected, outside the compliant transcript: an AskUserQuestion of the main agent (in
                  the window and after it) and of dev (in the window), and a Stop after a forged
                  ESCALATION_ACK line (in the window, and after it before the summary). The checks
                  (Night.unattended_checks, out/unattended.json) raise when one fails
  window=N        variant=unattended only: the end time typed, in minutes from the launch
  stop_at=N       the step after which variant=stop interrupts
  kit=base        the replay of the base kit's text: row 7's respellings below are applied
  kept=<JSON>     [[hook, step_norm, normalised text], ...]: a declared deviation passes only a block
                  in that list (drivers/dev.py KeptOnly, the step compared with the run's own ids
                  normalised, blocks.json "step_norm"); without it every declared deviation passes
  until=N         development aid only (not a compliant replay): end after cycle 1's Step N
  diagnose=pass-all  development aid only (not a compliant replay): every block is passed (recorded
                  with why "diagnose=pass-all"), to see what lies behind a new block

Respellings (row 7), driver only, each application recorded in blocks.json "respellings":
drivers/dev.py's list, applied only where the text still has the old form (the /dev-overnight text
of either tree has none of those forms), and, in a replay of the base kit's text (kit=base),
STOP_RESPELLINGS below: /stop's wrapper call, whose failure (it unlocks nothing) leaves the
time-lock refusing the session's end. The base text's Step 19 repository-relative
`scripts/commit.sh` is not respelled: the text logs its failure and goes on (row 7 respells only a
call whose failure ends the replay short of its terminal); nor are the agents' blast-radius tool
calls (row 7: left to TC-44).

Deviations: DEVIATIONS below, one entry per block the base tree's (2acc29b) replay meets, each with
a comment quoting the hook's text; nothing else passes a block.
"""
from __future__ import annotations

import calendar
import fnmatch
import hashlib
import json
import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass, field

from .. import agents, cmdtext, hookrun, roles
from ..pipeline import Deviations, Orchestrator, Respelling, utc_now
from ..replay import Deviation
from . import dev as devdrv

PIPELINE = "dev-overnight"
# The artifact check's cost of each variant (tests/artifact_graph/shards.py balances its CI shards by it):
# CPU seconds of the shipped and armed traced replays and their differential runs, measured at b8e34f4
# (qa-fail: measured beside plain on the P1b working tree at effa0ec, scaled by plain's 813; unattended:
# its untraced runs beside plain's on P2's working tree, scaled the same way; it also holds its slot for
# its `window`, about the time a traced replay of its one cycle takes on CI)
COST = {"plain": 813, "stop": 345, "qa-fail": 524, "unattended": 520}
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
    # DEVIATION: "BLOCKED: removal-policy — UNRESOLVED census_obligation_undischarged:substitution@143"
    # The same hook refuses the base text's Step 15 qa_mode flip (its `|| { echo ... >&2; exit 1; }`
    # after the flip's line continuation).
    ("C* Step 15 Bash qa_mode *", Deviation(
        "hooks/pretool-bash-safety.sh", "UNRESOLVED census_obligation_undischarged:substitution",
        "the base text's Step 15 qa_mode flip as it spells it")),
    # DEVIATION: "CONTRACT BLOCK (pretool-subagent-enforce): ... no required_calls entry for step '2'"
    # The launcher's seed contract (required_calls: []) switches the hook into enforce mode, so the
    # dispatches the text makes before its own contract exists (PM PLAN, the specialists, PM TRIAGE)
    # are refused (E13).
    ("C* Step [234] Agent(*", Deviation(
        "hooks/pretool-subagent-enforce.py", "CONTRACT BLOCK (pretool-subagent-enforce)",
        "the Steps 2-4 dispatches the text makes before its contract exists")),
    # DEVIATION: "CONTRACT BLOCK (pretool-subagent-enforce): step=17 ... errors: - no required_calls entry for
    # step '17'" The cycle contract has entries for the dispatches of Steps 2-4, 8, 10, 11g, 12, 15 and 20
    # only, so Step 17's iteration dispatches of dev and QA (the step in progress, as Step 11g's
    # precondition says to restore it) are refused (variant qa-fail).
    ("C* Step 17 Agent(*", Deviation(
        "hooks/pretool-subagent-enforce.py", "no required_calls entry for step '17'",
        "Step 17's iteration dispatches, which the cycle contract names no entry for")),
    # DEVIATION: "OVERNIGHT FILE CHECK BLOCK (contract): ... projection dev-report.v1: flat field
    # 'report_version' must be literal integer 1 ..." The Step 12 refusal below, again at Step 17's dev
    # re-dispatch, which Step 17 says takes Step 12's template (variant qa-fail).
    ("C* Step 17 Agent(dev) *", Deviation(
        "hooks/posttool-overnight-file-check.py", "OVERNIGHT FILE CHECK BLOCK (contract)",
        "the dev report Step 17's re-dispatch's obligation declares, collected")),
    # DEVIATION: "BLOCKED Agent dispatch (qa): canonical aggregate dev-report missing. ... per-worker
    # reports present: 0, 1 ..." The Step 15 refusal below, again at Step 17's QA dispatch, which Step 17
    # says takes Step 15's template (variant qa-fail).
    ("C* Step 17 Agent(qa) *", Deviation(
        "hooks/pretool-aggregate-check.py", "canonical aggregate dev-report missing",
        "Step 17's QA dispatch of an overnight pipeline")),
    # DEVIATION: "E2E_ENFORCE_BLOCKED: agent <agent> (type=qa) has no qa-report-*.json in <project>/docs/dev/
    # under session <sid>." The Step 15 refusal below, again at the stop of Step 17's QA, once the base
    # text's Step 17 qa_mode write has set final_verification (variant qa-fail).
    ("C* Step 17 Agent(qa) *", Deviation(
        "hooks/subagentstop-e2e-enforce.py", "E2E_ENFORCE_BLOCKED",
        "the stop of Step 17's QA, which wrote the report its obligation declares")),
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
    # DEVIATION: "E2E_ENFORCE_BLOCKED: agent <agent> (type=qa) has no qa-report-*.json in
    # <project>/docs/dev/ under session <sid>." subagentstop-e2e-enforce.py, once the base text's Step 15
    # qa_mode flip has set final_verification, finds the QA report by a YYYYMMDD-HHMMSS timestamp in
    # the registry's session id; an overnight registry is named by the session's UUID, so the report
    # the QA's obligation declares (and it wrote) is never found and its stop is refused.
    ("C* Step 15 Agent(qa) *", Deviation(
        "hooks/subagentstop-e2e-enforce.py", "E2E_ENFORCE_BLOCKED",
        "the stop of a final-verification QA that wrote the report its obligation declares")),
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
    # DEVIATION: 'BLOCKED by tool-policy.v1: {"role":"architect","tool":"Edit", ...
    # "deny_reason":"tool Edit not in allowed_tools"}' pretool-tool-policy.py refuses a specialist's Edit
    # of its report from the previous cycle: the report path names no cycle and the write guard refuses
    # a Write over an existing file, so the cycle-2 report is the cycle-1 file edited in place.
    ("agent:* Write *(Edit)", Deviation(
        "hooks/pretool-tool-policy.py", "tool Edit not in allowed_tools",
        "a specialist's report of an earlier cycle, rewritten in place")),
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
#   R6 stop sentinel dir  the same call gains CLAUDE_USERINTENT_SENTINEL_DIR (the helper's own override)
#                    set to the replay's state root: the base's break-overnight-lock.py reads the
#                    helper-auth token from the literal /tmp (the historical state root), while the
#                    user-intent guard writes it under CLAUDE_STATE_DIR, which rule 8 moves off /tmp;
#                    without it the base's /stop withholds isolation_released_at in every replay.
STOP_RESPELLINGS = [
    Respelling("R5 stop wrapper", r"(?<![\w=\"] )(?<![\w=])bash ~/\.claude/hooks/stop\.sh",
               devdrv.PROJECT_ROOT_PREFIX + "bash ~/.claude/hooks/stop.sh", "commands/stop.md Implementation"),
    Respelling("R6 stop sentinel dir", r"(?m)^(?!CLAUDE_USERINTENT_SENTINEL_DIR=)(.*\bbash ~/\.claude/hooks/stop\.sh)",
               'CLAUDE_USERINTENT_SENTINEL_DIR="${CLAUDE_STATE_DIR:-/tmp}" \\1', "commands/stop.md Implementation"),
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

# variant=unattended (D20): what pipeline 0 of cycle 1 (toy.add) meets inside the window. Each choice
# the decision lands on is what devdrv.SCENARIO's final change already does, so the cycle's outcome is
# the plain variant's.
UNATTENDED_WINDOW_MIN = 10
# BA's producer question, settled by the experiment the orchestrator names (Hard Rule 5, first bullet).
# The question's default (BA's recommendation) is not what the experiment supports, so the summary
# shows which of the two decided.
DECISION_EXPERIMENT = {
    "need": "Should toy.add's number check accept bool arguments (True, False)?",
    "options": [{"label": "accept bool", "description": "bool passes the check as the int subclass it is"},
                {"label": "reject bool", "description": "bool raises TypeError like any other non-number"}],
    "default": "reject bool",
    "why": "the requirement says 'not a number' without saying whether bool counts; toy/__init__.py and "
           "tests/test_add.py show no caller passing one"}
# What the orchestrator asks to be measured (WHAT, not HOW: the producer picks the command, `run`).
EXPERIMENT = {"measure": "whether Python's own arithmetic counts bool as a number (True + 2 gives 3 when it does)",
              "run": "python3 -c 'print(True + 2)'", "supports": {"3": "accept bool"}, "otherwise": "reject bool"}
# dev's producer question, which no experiment settles: the question's default (second bullet).
DECISION_DEFAULT = {
    "need": "Should add's TypeError message name the offending argument by its parameter name or by its position?",
    "options": [{"label": "parameter name", "description": "add(): argument b must be a number"},
                {"label": "position", "description": "add(): argument 2 must be a number"}],
    "default": "parameter name",
    "why": "the requirement says 'naming the offending argument'; a name and a position both name it and no "
           "file of the repository shows a convention"}
# A stand-in for a user gate a user spec's orchestrator view declares (Hard Rule 1, Clause B): this
# variant runs the autonomous mode, so no view carries it; the orchestrator meets it at pipeline 0's dev
# dispatch as if its view declared it there, and decides it as Hard Rule 5 decides a producer question
# (no experiment settles what the owner would choose: its default).
GATE = {"gate": "the owner confirms a change to a public function's behaviour before dev makes it",
        "options": [{"label": "change now", "description": "dev changes toy.add's behaviour in this cycle"},
                    {"label": "deprecate first", "description": "dev only warns on non-numbers in this cycle"}],
        "default": "change now"}
# The record stores the old escalation path wrote; nothing in an unattended session may write them.
RECORD_STORES = ("escalations", "escalation-admissions", "progress", "deferred-checks")
# The deny's answer to an AskUserQuestion inside /dev-overnight (P2 row R10), main agent and subagent.
DECIDE_TEXT = {
    "main": "Overnight is unattended; nobody answers. Decide (experiment, else the question's default), record the "
            "decision in the cycle log and in the summary's 'Decisions made without the owner', and continue.",
    "subagent": "Nobody answers overnight. Decide by experiment if one can be run, else take the question's default; "
                "record the decision, its options, the evidence or experiment and the chosen option in your report, "
                "and write your report."}


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


def report_work(content, reads=(), globs=()):
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


def run_experiment(sub, exp: dict) -> dict:
    """variant=unattended: the producer runs the experiment its re-dispatch names, takes the option the
    result supports and records the decision, its options, the experiment, its result and the chosen
    option (Hard Rule 5); `exp["question"]` is the question the producer itself wrote."""
    c = sub.bash(exp["run"], "Run the experiment the decision names", label=f"{sub.role} Bash experiment")
    out = (c.response.get("stdout", "") if c.ok else c.error).strip()
    q = exp["question"]
    return {"decision": q["need"], "options": [o["label"] for o in q["options"]], "experiment": exp["run"],
            "result": f"printed {out}" if c.ok else f"failed: {out[:200]}",
            "chosen": exp["supports"].get(out, exp["otherwise"]) if c.ok else q["default"]}


def _probe_blocks(ev) -> list:
    """The blocks of an injected call's event: hook, how, exit code, refusal text."""
    return [{"hook": h["hook"], "how": h["how"], "rc": h["rc"], "text": hookrun.refusal(h)[:800]}
            for h in ev.hooks if h["verdict"] == "block"]


# ---------------------------------------------------------------- deviations on another tree

class _NormKept:
    """A declared deviation bound to its step that passes only a kept base block, the step compared
    with the run's own ids normalised (blocks.json "step_norm")."""

    def __init__(self, dev, step_norm: str, kept: set):
        self.dev, self.step_norm, self.kept = dev, step_norm, kept
        self.hook, self.quote, self.why = dev.hook, dev.quote, dev.why

    def covers(self, block_hook: str, raw: str, text: str) -> bool:
        return self.dev.covers(block_hook, raw, text) and any(
            (block_hook, step, text) in self.kept for step in (self.step_norm, self.step_norm + " stop"))


class NormKeptOnly(Deviations):
    """drivers/dev.py KeptOnly, with steps compared normalised: a label naming an artifact path holds
    the session id or a task id, which differ from run to run (kept=[[hook, step_norm, text], ...])."""

    def __init__(self, inner: Deviations, kept, rp):
        super().__init__(inner.pairs)
        self.kept, self.rp = {tuple(k) for k in kept}, rp

    def at(self, label: str) -> list:
        return [_NormKept(d, self.rp.norm_text(label), self.kept) for d in super().at(label)]


class PassAll(Deviations):
    """diagnose=pass-all (development aid, not a compliant replay): the declared deviations, and every
    other block passed too, recorded with why "diagnose=pass-all", to see what lies behind a new block."""

    def __init__(self, inner: Deviations):
        super().__init__(inner.pairs)
        self.inner = inner

    def at(self, label: str) -> list:
        return self.inner.at(label) + [_Any()]


class _Any:
    hook, quote, why = "*", "(any block)", "diagnose=pass-all: not a compliant replay"

    def covers(self, block_hook: str, raw: str, text: str) -> bool:
        return True


class Refused(Exception):
    """A dispatch the hooks refused and no declared deviation passes: the text gives the orchestrator
    no compliant way on, so the cycle ends there and the owner's /stop ends the session."""


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
            devs = NormKeptOnly(DEVIATIONS, json.loads(rp.args["kept"]), rp)
        if rp.args.get("diagnose") == "pass-all":
            devs = PassAll(devs)
        self.project = rp.layout.project
        self.base_kit = rp.args.get("kit") == "base"
        self.owner_setup()  # before the session starts (the Orchestrator starts it)
        self.o = NightOrchestrator(rp, "dev-overnight", deviations=devs, respellings=devdrv.RESPELLINGS,
                                   rules=self._rules())
        rp.deviation_at = self.o.devs.at  # the subagents' own calls take the same deviations by label
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
        # variant=unattended: the decisions as recorded when made (the gate's flagged), the injected
        # probes' outcomes, the prompts that carried a decision, the question each producer wrote
        self.unattended = variant == "unattended"
        self.window_min = int(rp.args.get("window", UNATTENDED_WINDOW_MIN))
        self.decisions: list = []
        self.probes: list = []
        self.carried: list = []
        self.questions: dict = {}
        self.own: set = set()           # the labels of the variant's own dispatches (no base deviation is theirs)
        self.summary_rel = ""
        self.ended: dict = {}

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

    def end_epoch(self) -> float:
        """The record's end_time (UTC) as an epoch, 0 when unreadable."""
        try:
            return float(calendar.timegm(time.strptime(self.state["end_time"][:19], "%Y-%m-%dT%H:%M:%S")))
        except (KeyError, TypeError, ValueError):
            return 0.0

    def minutes_left(self) -> int:
        end = self.end_epoch()
        return max(0, int((end - time.time()) // 60)) if end else 0

    def in_window(self) -> bool:
        return time.time() < self.end_epoch()

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
                      description=fill_curly(fields.get("description", ""), pipe.rec if pipe else None,
                                             {"N": self.n}))
        d = self.o.dispatch(fields, act, self.L + label, task_id, subagent_type=atype)
        if d.blocked:  # refused, and no declared deviation passes the refusal
            raise Refused(self.L + label)
        return d

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
        o.slash(f"{f'{self.window_min}m' if self.unattended else END_TIME} {FOCUS}")
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
        n = self.cycle  # what PM learns from the session history it reads (the retro reports)

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
            c = self.bash(o.bind(check.group(1)), "Validate the specialist reports", "Step 3 Bash check-overnight-reports")
            bad = [l for l in (c.error if not c.ok else "").split("\n") if l.startswith("INVALID")]
            if bad:  # "Log which reports failed and why"; no specialist report is among them: proceed
                o.s.say("check-overnight-reports: " + "; ".join(bad)[:600] + "\nNone of these is a report a "
                        "specialist of this cycle wrote; proceeding with the specialist reports.")
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
        # `overnight.py cycle-index <STATE_FILE>`, or the `Cycle:` line overnight-status.sh prints for it
        m = re.search(r"`(~/\.claude/hooks/lib/overnight\.py cycle-index <STATE_FILE>)`", sec) or re.search(
            r"the `Cycle:` line of `(bash \"\$\{CLAUDE_HOME:-\$HOME/\.claude\}/scripts/overnight-status\.sh\" <STATE_FILE>)`", sec)
        if m:
            c = self.bash(o.bind(m.group(1)), "Read the cycle number", "Step 4 Bash cycle-index")
            out = c.response.get("stdout", "").strip() if c.ok else ""
            line = re.search(r"^\s*Cycle:\s*(\d+)\s*$", out, re.M)
            out = line.group(1) if line else out
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
        tpl_path = tpl.replace("~", self.rp.layout.home, 1) if tpl.startswith("~/") else o.bind(tpl)
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
            if self.meets_decisions(p):
                self.ba_decided_by_experiment(fields, p, f"Step 8 Agent(ba) pipeline {p.index}")
            else:
                self.dispatch_ba(fields, p, f"Step 8 Agent(ba) pipeline {p.index}")

    def dispatch_ba(self, fields, p: Pipe, label: str, question: dict | None = None, experiment: dict | None = None):
        """BA from the step's template; with `question`, BA writes that producer question instead of its
        report; with `experiment`, BA runs the experiment its re-dispatch names first and records the
        decision it settles in its context."""
        sc = p.sc
        if question:
            return self.dispatch(fields, agents.Act(question=dict(question, schema=self.question_schema()),
                                                    summary="producer question written"), label, p.sfx, atype="ba", pipe=p)
        content = devdrv._ba_content(p.sfx, "SMALL", sc)
        content["context.v1"]["development_approach"] = f"edit {sc.rel}: {sc.what}"
        sections = {"5": sc.requirement, "1": sc.before}

        def work(sub, b, pl):
            _spec_updates(sub, b, sections)
            return {"context.v1": {"decisions_without_owner": [run_experiment(sub, experiment)]}} if experiment else {}
        act = agents.Act(content=content, status="ready", summary=sc.ba_summary, respell=self.o.respell, work=work,
                         text_calls=[("Run Blast-Radius Tool Phase 1", {"<comma-separated files_to_modify>": sc.rel})])
        return self.dispatch(fields, act, label, p.sfx, atype="ba", pipe=p)

    # ------------------------------------------------------------ variant=unattended: decisions
    def meets_decisions(self, p: Pipe) -> bool:
        return self.unattended and self.cycle == 1 and p.index == 0

    def question_schema(self) -> str:
        m = re.search(r"\(schema (producer-question\.v\d+)", self.o.section("IMPORTANT RULES"))
        if not m:
            raise cmdtext.TextNotFound("Hard Rule 5 names no producer question schema")
        return m.group(1)

    def default_line(self, need: str, q: dict) -> str:
        """Hard Rule 5's re-dispatch line for a decision taken by the question's default."""
        code = next((c for c in cmdtext.inline_codes(self.o.text, "IMPORTANT RULES", "else by the question's `default`")
                     if c.startswith("Decision without the owner:")), None)
        if code is None:
            raise cmdtext.TextNotFound("Hard Rule 5 gives no `Decision without the owner:` line")
        labels = ", ".join(o["label"] for o in q["options"])
        return self.o.bind(code, [(r"^need$", need), (r"^labels$", labels), (r"^default label$", q["default"])])

    def experiment_line(self, q: dict, exp: dict) -> str:
        """The re-dispatch line of a decision an experiment settles, in the default line's form with
        Hard Rule 5's first bullet in place of its default: the decision, its options, the experiment
        (what to measure), and what the producer records."""
        head, sep, _ = self.default_line(q["need"], q).partition("; the question's default")
        if not sep:
            raise cmdtext.TextNotFound("Hard Rule 5's line has no \"the question's default\" part")
        return (f"{head}; decide by experiment: {exp['measure']}; take the option its result supports and record "
                "the decision, the options, the experiment, its result and the chosen option in your report")

    def record(self, p: Pipe, decision: str, options: list, evidence: str, chosen: str, gate: bool = False) -> None:
        """A decision as recorded when it was made (Hard Rule 5): the cycle log and the summary copy it."""
        self.decisions.append({"cycle": self.cycle, "pipeline": p.index, "task_id": p.sfx, "gate": gate,
                               "decision": decision, "options": options, "evidence": evidence, "chosen": chosen,
                               "in_window": self.in_window()})

    def decision_rows(self) -> list:
        """The session's decisions, spec-declared user gates first, each as recorded when it was made."""
        return [d for d in self.decisions if d["gate"]] + [d for d in self.decisions if not d["gate"]]

    @staticmethod
    def decision_rules(d: dict) -> list:
        """Placeholder rules of the cycle log's decision line and the summary's decision rows."""
        return [(r"^(?:pipeline|index)$", str(d["pipeline"])), (r"^task_id$", d["task_id"]),
                (r"^gate$", d["decision"].split("User gate: ", 1)[-1]), (r"^decision$", d["decision"]),
                (r"^labels$", ", ".join(d["options"])), (r"^experiment and its result", d["evidence"]),
                (r"^label$", d["chosen"])]

    def meet_question(self, rel: str, where: str) -> dict:
        """A producer question the orchestrator meets: Read; nobody is asked (an injected AskUserQuestion
        of the main agent, at the first one, shows the deny)."""
        self.read(rel, f"{where} Read producer question")
        q = self.load(rel)
        if not any(pr["who"] == "main" for pr in self.probes):
            self.probe_ask(f"{self.L}{where} (injected) AskUserQuestion", q)
        return q

    def ba_decided_by_experiment(self, fields: dict, p: Pipe, label: str) -> None:
        """BA writes its producer question; the orchestrator decides it by experiment (one can settle it)
        and re-dispatches BA, fresh, with the decision, its options and the experiment; BA runs it and
        records the decision in its context, which Step 9 copies."""
        d = self.dispatch_ba(fields, p, label, question=DECISION_EXPERIMENT)
        rel = d.player.question_written
        if not rel:
            raise RuntimeError(f"{label}: BA wrote no producer question")
        q = self.questions[("ba", p.index)] = self.meet_question(rel, f"Step 8 pipeline {p.index}")
        line = self.experiment_line(q, EXPERIMENT)
        self.o.s.say(f"Pipeline {p.index}: BA asks: {q['need']} Nobody answers overnight (Hard Rule 5); an "
                     f"experiment settles it: {EXPERIMENT['measure']}. Re-dispatching BA with the decision.")
        pr = re.sub(r"^(\s*Clarification round:\s*)\d+", r"\g<1>1", fields["prompt"], count=1, flags=re.M)
        prev = json.dumps([{"question": q["need"], "answer": line}])
        pr, n = re.subn(r"^(\s*)Previous answers:.*$", lambda m: f"{m.group(1)}Previous answers: {prev}\n{m.group(1)}{line}",
                        pr, count=1, flags=re.M)
        if not n:
            raise cmdtext.TextNotFound("Step 8's BA template has no `Previous answers:` line")
        d2 = self.dispatch_ba(dict(fields, prompt=pr), p, label + " (decision)", experiment=dict(EXPERIMENT, question=q))
        self.carried.append({"where": label + " (decision)", "line": line, "prompt": d2.player.b.prompt})
        self.own |= {self.L + label, self.L + label + " (decision)"}

    def gate_line(self, p: Pipe) -> str:
        """The stand-in user gate at pipeline 0's dev dispatch, decided once (Clause B: as Hard Rule 5
        decides a producer question; no experiment settles the owner's preference: its default)."""
        if not any(d["gate"] for d in self.decisions):
            self.o.s.say(f"Pipeline {p.index}: user gate before dev (Hard Rule 1, Clause B): {GATE['gate']}. Nobody "
                         "answers overnight; no experiment settles it, so it takes its default, and the pipeline "
                         "continues with it.")
            self.record(p, f"User gate: {GATE['gate']}", [o["label"] for o in GATE["options"]],
                        "the question's default", GATE["default"], gate=True)
        return self.default_line(f"User gate: {GATE['gate']}", GATE)

    def dev_question_round(self, fields: dict, p: Pipe, label: str):
        """dev writes its producer question (an injected AskUserQuestion of dev first shows the deny)."""
        def ask_first(sub, b, pl):
            self.probe_ask(f"{self.L}{label} (injected) AskUserQuestion", DECISION_DEFAULT, actor=sub)
            return {}
        act = agents.Act(question=dict(DECISION_DEFAULT, schema=self.question_schema()), work=ask_first,
                         summary="producer question written")
        d = self.dispatch(fields, act, label, p.sfx, atype="dev", pipe=p)
        if not d.player.question_written:
            raise RuntimeError(f"{label}: dev wrote no producer question")
        return d

    def dev_decided_by_default(self, p: Pipe) -> None:
        """Step 13 for a dev that wrote its producer question: decided by the question's default (no
        experiment settles it), Step 11g's precondition (the run record's fingerprint against the
        context dev consumes), dev re-dispatched fresh from Step 12's template with the decision."""
        o = self.o
        rel = f"docs/dev/producer-question-{p.sfx}-dev.json"
        q = self.questions[("dev", p.index)] = self.meet_question(rel, f"Step 13 pipeline {p.index}")
        line = self.default_line(q["need"], q)
        self.record(p, q["need"], [x["label"] for x in q["options"]], "the question's default", q["default"])
        o.s.say(f"Pipeline {p.index}: dev asks: {q['need']} Nobody answers overnight (Hard Rule 5); no experiment "
                f"settles it, so it takes the question's default ({q['default']}). Re-dispatching dev with the decision.")
        # Step 11g's precondition at the Step 13 site: the run record's fingerprint against the context.
        self.ctx_rel = f"docs/dev/context-{p.sfx}.json"
        run_rel = f".claude/dev-registry/{self.sid}-pipeline-{p.index}/graphify/graphify-run.json"
        status, same = None, False
        if os.path.isfile(os.path.join(self.project, run_rel)):
            self.read(run_rel, f"Step 13 Read graphify-run {p.index} (fingerprint)")
            rec = self.load(run_rel)
            status = rec.get("status")
            c = self.bash(f"sha256sum {shlex.quote(self.ctx_rel)}", "Fingerprint the context dev consumes",
                          f"Step 13 Bash context fingerprint {p.index}")
            sha = (c.response.get("stdout", "").split() or [""])[0] if c.ok else ""
            same = (rec.get("context_sha256") == sha and rec.get("context_path") == self.ctx_rel
                    and int(rec.get("iteration") or 0) == int(p.rec.get("iteration") or 0))
        if not same:
            o.set_in_progress("11g", f"{self.L}TodoWrite Step 11g in_progress (pipeline {p.index}, Step 13)")
            self.dispatch(o.template("Step 11g"), agents.Act(summary="graphify enrichment"),
                          f"Step 11g Agent(graphify) pipeline {p.index} (Step 13)", p.sfx, atype="graphify", pipe=p)
            if os.path.isfile(os.path.join(self.project, run_rel)):
                self.read(run_rel, f"Step 11g Read graphify-run {p.index} (Step 13)")
                status = self.load(run_rel).get("status")
            o.set_in_progress(13, f"{self.L}TodoWrite Step 13 in_progress (pipeline {p.index})")
        d_tpl = agent_block(next(b.text for b in cmdtext.blocks(o.section("Step 12"), None) if "Agent(" in b.text))
        add = [self.gate_line(p), line]
        g_add = re.search(r"`(Graph context file: [^`]+)`", o.section("Step 11g"))
        if g_add and status in ("ok", "degraded"):
            add.append(fill_curly(g_add.group(1).replace("${DEV_SESSION_ID}", self.sid), p.rec, {}))
        label = f"Step 13 Agent(dev) pipeline {p.index} (decision)"
        self.pre_shell(d_tpl, p, f"Step 13 Bash pre-dispatch {p.index}")
        d = self.dispatch_dev(devdrv.with_lines(dict(d_tpl), add), p, p.sc.old, p.sc.final, label, attempt=1)
        self.carried.append({"where": label, "line": line, "prompt": d.player.b.prompt})
        self.own.add(self.L + label)

    # ------------------------------------------------------------ variant=unattended: injected probes
    def probe_ask(self, label: str, q: dict, actor=None) -> None:
        """An AskUserQuestion the compliant transcript does not hold: its PreToolUse alone, fired the way the
        CLI fires it for the main agent or the subagent `actor`, recorded with its outcome."""
        tin = {"questions": [{"question": q.get("need") or q.get("gate", ""), "header": "decision",
                              "options": [{"label": o["label"], "description": o["description"]} for o in q["options"]],
                              "multiSelect": False}]}
        ev = self.o.s.fire("PreToolUse", label, {"tool_name": "AskUserQuestion", "tool_input": tin,
                                                 "tool_use_id": self.rp.new_tool_id()}, actor.agent if actor else None)
        self.probes.append({"kind": "AskUserQuestion", "label": label, "who": actor.role if actor else "main",
                            "in_window": self.in_window(), "blocks": _probe_blocks(ev)})

    def probe_stop(self, label: str) -> None:
        """The main agent's Stop after a forged ESCALATION_ACK line it wrote into the transcript."""
        nonce = hashlib.sha256(f"{self.sid} {label}".encode()).hexdigest()[:32]
        text = f"The pipeline needs the owner; escalating.\nESCALATION_ACK {nonce}"
        self.o.s.say(text)
        ev = self.o.s.fire("Stop", label, {"stop_hook_active": False, "last_assistant_message": text})
        self.probes.append({"kind": "Stop after a forged ESCALATION_ACK", "label": label, "who": "main",
                            "in_window": self.in_window(), "blocks": _probe_blocks(ev)})

    def step9(self) -> None:
        self.todo_to(9)
        for p in self.pipes:
            for rel in (f"docs/dev/ticket-{p.sfx}.md", f"docs/dev/context-{p.sfx}.json"):
                self.read(rel, f"Step 9 Read {os.path.basename(rel).split('-')[0]} {p.index}")
            if ("ba", p.index) in self.questions:  # the decision BA recorded, copied as it was made
                for rec in self.load(f"docs/dev/context-{p.sfx}.json").get("decisions_without_owner") or []:
                    self.record(p, rec["decision"], rec["options"],
                                f"experiment `{rec['experiment']}`: {rec['result']}", rec["chosen"])

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
            if self.meets_decisions(p):  # variant=unattended: the user gate, then dev's producer question
                label = f"Step 12 Agent(dev) pipeline {p.index}"
                line = self.gate_line(p)
                d = self.dev_question_round(devdrv.with_lines(fields, [line]), p, label)
                self.carried.append({"where": label, "line": line, "prompt": d.player.b.prompt})
                self.own.add(self.L + label)
                continue
            self.dispatch_dev(fields, p, sc.old, sc.partial if self.fails_first(p) else sc.final,
                              f"Step 12 Agent(dev) pipeline {p.index}", attempt=1)

    def fails_first(self, p: Pipe) -> bool:
        """Whether this pipeline's first QA fails (variant qa-fail: pipeline 0, in cycle 1)."""
        return self.variant == "qa-fail" and self.cycle == 1 and p.index == 0

    def dispatch_dev(self, fields: dict, p: Pipe, old: str, new: str, label: str, attempt: int):
        sc = p.sc
        work = roles.dev([(sc.rel, old, new)], baseline_fallback=True)

        def dev_work(sub, b, pl, work=work):
            out = work(sub, b, pl)
            _spec_updates(sub, b, {"2": f"Attempt {attempt}: {sc.what}", "3": f"{sc.rel}: {sc.dev_summary}"})
            return out
        act = agents.Act(work=dev_work, summary=sc.dev_summary)
        return self.dispatch(fields, act, label, p.sfx, atype="dev", pipe=p)

    def step13(self) -> None:
        self.todo_to(13)
        for p in self.pipes:
            if self.meets_decisions(p):  # dev wrote its producer question instead of its report
                self.dev_decided_by_default(p)
            self.read(f"docs/dev/dev-report-{p.sfx}.json", f"Step 13 Read dev-report {p.index}")
        if self.unattended and self.cycle == 1:  # every decision made: a Stop after a forged line, in the window
            self.probe_stop(f"{self.L}Step 13 (injected) Stop after a forged ESCALATION_ACK line")

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
            self.dispatch_qa(dict(tpl), p, "fail" if self.fails_first(p) else "pass",
                             f"Step 15 Agent(qa) pipeline {p.index}")

    def dispatch_qa(self, fields: dict, p: Pipe, verdict: str, label: str):
        o, sc = self.o, p.sc
        extra = sections = None
        if verdict == "fail":  # the dev report's change leaves AC-01 unmet (drivers/dev.py's QA fail)
            extra = {"qa": {"failures": [sc.qa_failure], "overall_assessment": "AC-01 not met"}}
            sections = {"6": sc.qa_failure["description"], "7": "name the offending argument in the TypeError message"}
        work = roles.qa(e2e={"status": "legitimately_skipped", "blocking_reason": sc.no_e2e},
                        guard_respell=o.respell, extra=extra)

        def qa_work(sub, b, pl, work=work, sc=sc):
            out = work(sub, b, pl)
            _spec_updates(sub, b, dict({"4": f"{sc.measured.split(' ')[0]}: {sc.ac['then']} (measured after the change)"},
                                       **(sections or {})))
            return out
        act = agents.Act(verdict=verdict, work=qa_work, summary=f"QA {verdict}", respell=o.respell,
                         text_calls=[("Phase 6: Blast-Radius Phase 2 Verification", {})])
        return self.dispatch(fields, act, label, p.sfx, atype="qa", pipe=p)

    def step16(self) -> None:
        self.todo_to(16)
        self.failed = []
        for p in self.pipes:
            rel = f"docs/dev/qa-report-{p.sfx}.json"
            self.read(rel, f"Step 16 Read qa-report {p.index}")
            if (self.load(rel).get("qa") or {}).get("status") != "pass":
                self.failed.append(p)
        passed = len(self.pipes) - len(self.failed)
        self.o.s.say(f"Pipelines passed: {passed} of {len(self.pipes)}\nPipelines needing iteration: "
                     f"{len(self.failed)}")
        if self.failed and self.variant != "qa-fail":
            raise RuntimeError("a QA did not pass outside variant qa-fail")
        if self.failed:
            # The decision tree's marks, in the pipelines file Step 6 wrote (the file Step 17's
            # iteration plan selects the qa_failed pipelines from).
            self.mark({p.index: ({"phase": "qa_failed"} if p in self.failed else {"phase": "done", "status": "fixed"})
                       for p in self.pipes}, "Step 16 Write pipelines.json (phases)")

    # ------------------------------------------------------------ Step 17 (variant qa-fail)
    @property
    def pipes_rel(self) -> str:
        """The pipelines file Step 6's block writes (`... | tee <path>`)."""
        name, b, _ = self.o.step_blocks("Step 6")[0]
        return self.o.bind(re.search(r"\btee\s+(\S+\.json)", b.text).group(1))

    def mark(self, changes: dict, label: str) -> None:
        """Pipeline records updated in the pipelines file: Read, then edited in place (its own format)."""
        rel = self.pipes_rel
        path = os.path.join(self.project, rel)
        if path not in self.read_paths:
            self.read(rel, label.replace(" Write ", " Read "))
        old = agents.peek(self.rp, "main", path)
        recs = json.loads(old)
        for r in recs:
            r.update(changes.get(r.get("index"), {}))
        for p in self.pipes:
            p.rec.update(changes.get(p.index, {}))
        new = json.dumps(recs, indent=2) + ("\n" if old.endswith("\n") else "")
        self.write(rel, new, label)

    def step17(self) -> None:
        """Step 17 as the tree's text says: the iteration plan's block, the plan Read, and each entry's
        Dev+QA inner loop until its QA passes."""
        o = self.o
        once, per = [], []
        for name, b, _ in o.step_blocks("Step 17"):
            (per if "<new-iter>" in b.text else once).append((name, b))
        plan_rel = None
        for name, b in once:
            o.run_text(b.text, f"{self.L}Step 17 Bash {name}", "Build the iteration plan")
            m = re.search(r">\s*(\S+\.json)\s*$", o.bind(b.text).strip())
            plan_rel = m.group(1) if m else plan_rel
        if plan_rel is None:
            raise cmdtext.TextNotFound("Step 17 has no block writing the iteration plan")
        self.read(plan_rel, "Step 17 Read iteration plan")
        plan = self.load(plan_rel).get("iteration_plan") or []
        sec = o.section("Step 17")
        g_tpl = o.template("Step 11g")
        d_tpl = agent_block(next(b.text for b in cmdtext.blocks(o.section("Step 12"), None) if "Agent(" in b.text))
        q_tpl = agent_block(next(b.text for b in cmdtext.blocks(o.section("Step 15"), None) if "Agent(" in b.text))
        qa_mode = [c for c in re.findall(r"`([^`\n]+)`", sec) if "write-qa-mode.sh" in c]
        for entry in plan:
            p = next(x for x in self.pipes if x.index == entry["index"])
            while True:
                it = int(p.rec.get("iteration") or entry.get("current_iteration") or 0) + 1
                self.mark({p.index: {"iteration": it}}, f"Step 17 Write pipelines.json (iteration {it} of {p.index})")
                # The text's per-iteration blocks (the base's context refinement); a block that writes a
                # context file gives the context dev consumes this iteration.
                self.ctx_rel = f"docs/dev/context-{p.sfx}.json"
                rules = [(r"^new-iter$", str(it)), (r"^timestamp_suffix$", p.sfx)]
                for name, b in per:
                    o.run_text(b.text, f"{self.L}Step 17 Bash {name} {p.index}", "Refine the context", extra_rules=rules)
                    m = re.search(r">\s*(\S*context\S*\.json)\s*$", o.bind(b.text, rules).strip())
                    if m:
                        self.ctx_rel = m.group(1)
                # Step 11g's precondition at the new iteration, then Step 17 in progress again.
                o.set_in_progress("11g", f"{self.L}TodoWrite Step 11g in_progress (pipeline {p.index} iteration {it})")
                self.dispatch(g_tpl, agents.Act(summary="graphify enrichment"),
                              f"Step 11g Agent(graphify) pipeline {p.index} iteration {it}", p.sfx, atype="graphify", pipe=p)
                run_rel = f".claude/dev-registry/{self.sid}-pipeline-{p.index}/graphify/graphify-run.json"
                status = None
                if os.path.isfile(os.path.join(self.project, run_rel)):
                    self.read(run_rel, f"Step 11g Read graphify-run {p.index} iteration {it}")
                    status = self.load(run_rel).get("status")
                o.s.say(f"pipeline {p.index} iteration {it}: graphify status={status}")
                o.set_in_progress(17, f"{self.L}TodoWrite Step 17 in_progress (pipeline {p.index} iteration {it})")
                # Dev from Step 12's template: the lines Step 17 adds that it does not carry yet, the
                # context it consumes this iteration.
                fields = dict(d_tpl)
                labels = {l.split(":", 1)[0].strip() for l in fields["prompt"].split("\n") if ":" in l}
                add = [fill_curly(c, p.rec, {}) for c in re.findall(r"`([A-Z][\w ]* file:\s*[^`\s]+)`", sec)
                       if c.split(":", 1)[0].strip() not in labels]
                g_add = re.search(r"`(Graph context file: [^`]+)`", o.section("Step 11g"))
                if g_add and status in ("ok", "degraded"):
                    add.append(fill_curly(g_add.group(1).replace("${DEV_SESSION_ID}", self.sid), p.rec, {}))
                ctx = self.ctx_rel if self.ctx_rel != f"docs/dev/context-{p.sfx}.json" else None
                fields = devdrv.with_lines(fields, add, ctx)
                self.dispatch_dev(fields, p, p.sc.partial, p.sc.final,
                                  f"Step 17 Agent(dev) pipeline {p.index} iteration {it}", attempt=it + 1)
                for k, code in enumerate(qa_mode, 1):  # the qa_mode write the text has before QA (the base's)
                    o.run_text(code, f"{self.L}Step 17 Bash qa_mode {p.index} iteration {it}" + (f" #{k}" if k > 1 else ""),
                               "Set qa_mode before the QA dispatch")
                self.dispatch_qa(dict(q_tpl), p, "pass", f"Step 17 Agent(qa) pipeline {p.index} iteration {it}")
                rel = f"docs/dev/qa-report-{p.sfx}.json"
                self.read(rel, f"Step 17 Read qa-report {p.index} iteration {it}")
                if (self.load(rel).get("qa") or {}).get("status") == "pass":  # the only exit
                    self.mark({p.index: {"phase": "done", "status": "fixed"}},
                              f"Step 17 Write pipelines.json (pipeline {p.index} fixed)")
                    break
        self.failed = []

    def step18(self) -> None:
        o = self.o
        self.todo_to(17)
        if getattr(self, "failed", None):
            self.step17()
        else:
            o.s.say("Step 17: every pipeline passed QA; no iteration.")
        self.todo_to(18)
        for name, b, _ in o.step_blocks("Step 18"):
            o.run_text(b.text, f"{self.L}Step 18 Bash {name}", "Aggregate and apply the pipelines' permissions")

    # ------------------------------------------------------------ Steps 19-21
    @staticmethod
    def attempts(p: Pipe) -> int:
        """Dev+QA attempts of a pipeline this cycle: the first, plus each Step 17 iteration."""
        return 1 + int(p.rec.get("iteration") or 0)

    def step19(self) -> None:
        o = self.o
        self.todo_to(19)
        sec = o.section("Step 19")
        log = re.search(r"running log\*\* at `([^`]+)`", sec).group(1)
        self.log_rel = o.bind(log)
        tpl = cmdtext.block(sec, None, lang="markdown")
        rows = "\n".join(f"| {p.index} | {p.rec['description']} | Fixed | {self.attempts(p)} |" for p in self.pipes)
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
        # One line per decision of this cycle, spec-declared user gates first, in the template's form.
        made = [d for d in self.decision_rows() if d["cycle"] == self.cycle]
        m = re.search(r"^(\*\*Decisions made without the owner\*\*:) (.*?) \(one line per decision.*$", entry, re.M)
        if made and not m:
            raise cmdtext.TextNotFound("Step 19's log template has no `Decisions made without the owner` line form")
        if made:
            lines = [m.group(1)] + ["- " + self.o.bind(m.group(2), self.decision_rules(d)) for d in made]
            entry = entry[:m.start()] + "\n".join(lines) + entry[m.end():]
        else:
            entry = re.sub(r"^\*\*Decisions made without the owner\*\*:.*$", "**Decisions made without the owner**: none",
                           entry, flags=re.M)
        entry = entry.replace("<timestamp>", utc_now())
        path = os.path.join(self.project, self.log_rel)
        old = agents.peek(self.rp, "main", path) if os.path.exists(path) else ""
        self.write(self.log_rel, (old.rstrip("\n") + "\n\n" if old else "") + entry.strip("\n") + "\n", "Step 19 Write cycle log")
        # TIME CHECK.
        code = next(c for c in cmdtext.inline_codes(o.text, "Step 19", "TIME CHECK")
                    if c.startswith(("~/.claude/scripts/overnight-status.sh",
                                     'bash "${CLAUDE_HOME:-$HOME/.claude}/scripts/overnight-status.sh"')))
        cmd = o.bind(code)
        if cmd.strip() == "~/.claude/scripts/overnight-status.sh" and "against the state file" in sec:
            cmd += " " + shlex.quote(self.state_file)
        if self.unattended:  # a real cycle outlasts this window: its end comes before the TIME CHECK
            while time.time() <= self.end_epoch() + 1:
                time.sleep(min(5.0, max(0.2, self.end_epoch() + 1.5 - time.time())))
        tc = self.bash(cmd, "TIME CHECK", "Step 19 Bash TIME CHECK")
        self.expired = not tc.ok
        o.s.say(tc.response.get("stdout", "").strip() if tc.ok else f"TIME CHECK: {tc.error[:300]}")
        # Per-cycle commit, where the text has one (the base's; a text without it keeps the cycle's
        # work in refs/checkpoints/<branch> until the owner's post-loop flow). A command that runs
        # git: the actor env first.
        try:
            codes = cmdtext.inline_codes(o.text, "Step 19", "chore(overnight)")
        except cmdtext.TextNotFound:
            codes = []
        commit = next((c for c in codes if "commit.sh" in c and "chore(overnight)" in c), None)
        if commit is None:
            return
        cc = self.bash(self.git(o.bind(commit)), "End-of-cycle commit", "Step 19 Bash end-of-cycle commit")
        if not cc.ok:  # "log the failure to the cycle log and continue"
            path = os.path.join(self.project, self.log_rel)
            old = agents.peek(self.rp, "main", path) if os.path.exists(path) else ""  # (its Write refused)
            line = f"**End-of-cycle commit**: failed ({cc.error.splitlines()[0][:200]}); refs/checkpoints/* snapshots remain.\n"
            self.write(self.log_rel, (old.rstrip("\n") + "\n\n" if old else "") + line,
                       "Step 19 Write cycle log (commit failure)")

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
                                    "pipeline_recommendation": "fix", "actual_outcome": "fixed",
                                    "iterations_used": self.attempts(p),
                                    "failure_reason": None} for k, p in enumerate(self.pipes)],
               "cycle_stats": {"issues_triaged": len(self.pipes), "issues_attempted": len(self.pipes),
                               "issues_fixed": len(self.pipes), "issues_failed": 0, "issues_skipped": 0,
                               "fix_rate": 1.0, "focus_mode_used": True},
               "unresolved_issues": [], "patterns_noticed": ["unchecked argument types in the package's functions"],
               "recommendations_for_next_cycle": [], "qa_rerun_required": False, "qa_rerun_reasons": [],
               "final_summary": None}
        if self.final_cycle:  # agents/pm.md's Final Summary Schema
            doc["final_summary"] = {"total_cycles": self.n, "total_issues_found": len(self.pipes),
                                    "total_issues_fixed": len(self.pipes), "total_issues_unresolved": 0,
                                    "overall_fix_rate": 1.0, "goals_achieved": [FOCUS], "goals_not_achieved": [],
                                    "needs_human_attention": [], "session_quality_assessment": "good"}
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
            if not self.unattended:
                raise RuntimeError("the window closed before the owner's /stop: only variant=unattended plays the "
                                   "session-ending summary")
            self.closeout()
            return
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

    # ------------------------------------------------------------ Step 21, time expired (variant=unattended)
    def summary_text(self, tpl: str) -> str:
        """The summary from Step 21's template: its decision rows one per decision (gates first), its
        cycle details one per pipeline, every other placeholder from the state, the cycle and the retro."""
        rows = self.decision_rows()
        out, lines, i = [], tpl.split("\n"), 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("| <index> | <task_id> | User gate:"):
                out += [self.o.bind(line, self.decision_rules(d)) for d in rows if d["gate"]]
            elif line.startswith("| <index> | <task_id> | <decision>"):
                out += [self.o.bind(line, self.decision_rules(d)) for d in rows if not d["gate"]]
            elif re.match(r"^### Cycle \d+: <issue>", line):  # one entry per pipeline of the cycle
                body = [line]
                while i + 1 < len(lines) and lines[i + 1].startswith("- "):
                    i += 1
                    body.append(lines[i])
                for p in self.pipes:
                    rules = [(r"^issue$", p.rec["description"]), (r"^file$", p.rec["location"]),
                             (r"^summary$", p.sc.dev_summary), (r"^N$", str(self.attempts(p)))]
                    out += [self.o.bind(b, rules) for b in body] + [""]
                if out and not out[-1]:
                    out.pop()
            else:
                out.append(line)
            i += 1
        text = "\n".join(out)
        if not rows:  # "Write "None" under the heading when the session made none"
            text = re.sub(r"(## Decisions made without the owner\n\n)(?:\|.*\n)+", r"\1None\n", text)
        retro = self.load(f"{self.sdir}/retro-report-cycle{self.n}.json")
        left: list = []
        text = self.o.bind(text, self.end_rules() + [
            (r"^Patterns noticed", "; ".join(retro.get("patterns_noticed") or []) or "none")], left)
        if left:
            raise cmdtext.TextNotFound(f"Step 21's summary template: unbound placeholders {sorted(set(left))}")
        return text.rstrip("\n") + "\n"

    def end_rules(self) -> list:
        """The session-ending placeholders the summary and the announcement share."""
        try:
            start = calendar.timegm(time.strptime(str(self.state.get("start_time"))[:19], "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            start = time.time()
        mins = max(0, int((time.time() - start) // 60))
        fixed = len(self.pipes)
        return [(r"^actual_end$", utc_now()), (r"^hours$", str(mins // 60)), (r"^minutes$", str(mins % 60)),
                (r"^cycle index - 1$", str(self.n)), (r"^issues_found$", str(len(self.triage.get("issues") or []))),
                (r"^issues_fixed$", str(fixed)), (r"^issues_triage_deferred$", str(len(self.triage.get("skipped_issues") or []))),
                (r"^percentage$", str(round(100 * fixed / max(1, len(self.pipes))))),
                (r"^decision_count$", str(len(self.decisions))), (r"^main_root$", self.main_root)]

    def announcement(self, text: str) -> str:
        """The announcement block with its `<If isolation_kind ...>` lines resolved for this session."""
        kind = str(self.state.get("isolation_kind"))

        def holds(cond):
            m = re.fullmatch(r"isolation_kind (==|!=) '([^']*)'", cond.strip())
            if not m:
                raise cmdtext.TextNotFound(f"announcement condition the driver cannot evaluate: {cond!r}")
            return (kind == m.group(2)) == (m.group(1) == "==")
        out, keep = [], True
        for line in text.split("\n"):
            one = re.match(r'^\s*<If (.+?), add the line: "(.*)">\s*$', line)
            mark = re.match(r"^\s*<If (.+?), include(?: instead)?:>\s*$", line)
            if one:
                if holds(one.group(1)):
                    out.append(one.group(2))
            elif mark:
                keep = holds(mark.group(1))
            elif keep:
                out.append(line)
            elif not line.strip():  # an excluded paragraph ends at its blank line
                keep = True
        left: list = []
        said = self.o.bind("\n".join(out), self.end_rules(), left)
        if left:
            raise cmdtext.TextNotFound(f"Step 21's announcement: unbound placeholders {sorted(set(left))}")
        return said

    def closeout(self) -> None:
        """Step 21's session-ending branch: the state Read, the summary, the default-branch resolver, Step
        21 completed (no loop reset after end_time), the announcement, the main agent's Stop. Injected
        first: an AskUserQuestion after end_time and a Stop after a forged line, the summary not yet written."""
        o = self.o
        self.probe_ask(f"{self.L}Step 21 (injected) AskUserQuestion after end_time", DECISION_DEFAULT)
        self.probe_stop(f"{self.L}Step 21 (injected) Stop after a forged ESCALATION_ACK line, summary missing")
        self.read(self.state_file, "Step 21 Read state record (session ending)")
        self.state = self.load(self.state_file)
        sec = o.section("Step 21")
        m = re.search(r"Generate summary report\*\* at `([^`]+)`", sec)
        if not m:
            raise cmdtext.TextNotFound("Step 21 names no summary path")
        self.summary_rel = o.bind(m.group(1))
        self.write(self.summary_rel, self.summary_text(cmdtext.block(sec, None, lang="markdown")),
                   "Step 21 Write overnight summary")
        for name, b, _ in o.step_blocks("Step 21"):  # the default-branch resolver, a command that runs git
            o.run(self.git(o.shell_bind(o.bind(b.text))), "Resolve the default branch", f"{self.L}Step 21 Bash {name}")
        i = o.current()
        o.todos[i]["status"] = "completed"
        call = o._todo(f"{self.L}TodoWrite Step 21 done (session ending)")
        hook = "\n".join(h["stdout"] for h in (call.post.hooks if call.post else []) if h["verdict"] == "ok")
        self.ended["loop_reset_after_end"] = "Reset your todo list" in hook
        said = self.announcement(cmdtext.block(sec, None, anchor="Overnight development session complete"))
        label = f"{self.L}Stop (session end)"
        ev = o.s.stop(said, label=label, deviation=o.devs.at(label))
        self.ended.update(stopped=not ev.blocked, blocks=_probe_blocks(ev))

    # ------------------------------------------------------------ variant=unattended: the checks
    def unattended_checks(self) -> None:
        """D20's unattended decision, checked on what the run left: out/unattended.json, and an error
        naming every check that failed."""
        rp, res = self.rp, []

        def check(name, ok, detail=None):
            res.append({"check": name, "ok": bool(ok), "detail": detail})

        def read(path):
            with rp.acting("driver"):
                try:
                    with open(path, encoding="utf-8") as fh:
                        return fh.read()
                except OSError:
                    return ""
        # 0 AskUserQuestion tool_use records in the session's transcripts (the main one, every subagent's)
        tdir = os.path.dirname(self.o.s.tpath)
        paths = [self.o.s.tpath]
        with rp.acting("driver"):
            sub = os.path.join(tdir, self.sid, "subagents")
            paths += sorted(os.path.join(sub, f) for f in (os.listdir(sub) if os.path.isdir(sub) else [])
                            if f.endswith(".jsonl"))
        asks = 0
        for path in paths:
            for line in read(path).splitlines():
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                content = (rec.get("message") or {}).get("content") if isinstance(rec, dict) else None
                asks += sum(1 for c in content if isinstance(c, dict) and c.get("type") == "tool_use"
                            and c.get("name") == "AskUserQuestion") if isinstance(content, list) else 0
        check("0 AskUserQuestion tool_use records in the compliant transcripts", asks == 0,
              {"transcripts": len(paths), "AskUserQuestion": asks})
        # the three decisions, made in the window, in the summary in order (the gate first), fields named
        p0 = next((p for p in self.pipes if p.index == 0), None)
        sfx = p0.sfx if p0 else ""
        want = [(f"User gate: {GATE['gate']}", GATE["options"], lambda e: e == "the question's default", GATE["default"]),
                (DECISION_EXPERIMENT["need"], DECISION_EXPERIMENT["options"],
                 lambda e: EXPERIMENT["run"] in e and "printed 3" in e, "accept bool"),
                (DECISION_DEFAULT["need"], DECISION_DEFAULT["options"], lambda e: e == "the question's default",
                 DECISION_DEFAULT["default"])]
        check("every decision made inside the window", self.decisions and all(d["in_window"] for d in self.decisions),
              [{"decision": d["decision"], "in_window": d["in_window"]} for d in self.decisions])
        summary = read(os.path.join(self.project, self.summary_rel)) if self.summary_rel else ""
        sec = re.search(r"^## Decisions made without the owner\n(.*?)(?=^## |\Z)", summary, re.M | re.S)
        rows = [[c.strip() for c in l.strip().strip("|").split("|")]
                for l in (sec.group(1) if sec else "").splitlines()
                if l.startswith("|") and not re.match(r"^\|\s*-", l) and not l.startswith("| Pipeline")]
        ok = len(rows) == len(want) and all(
            r[0] == "0" and r[1] == sfx and r[2] == dec and r[3] == ", ".join(o["label"] for o in opts) and ev(r[4])
            and r[5] == chosen for r, (dec, opts, ev, chosen) in zip(rows, want))
        check("the summary's 'Decisions made without the owner': gate, experiment (its run and result), default "
              "(the question's default); pipeline, task id, decision, options, evidence, chosen option", ok, rows)
        log = read(os.path.join(self.project, self.log_rel)) if self.log_rel else ""
        lm = re.search(r"^\*\*Decisions made without the owner\*\*:\n((?:- .*\n?)+)", log, re.M)
        items = lm.group(1).splitlines() if lm else []
        check("the cycle log lists the same decisions in the same order",
              len(items) == len(want) and all(f"0 {sfx}: {dec};" in it and it.endswith(f"chosen {chosen}")
                                              for it, (dec, _o, _e, chosen) in zip(items, want)), items)
        ctx = read(os.path.join(self.project, f"docs/dev/context-{sfx}.json"))
        try:
            rec = (json.loads(ctx).get("decisions_without_owner") or [{}])[0]
        except (ValueError, AttributeError):
            rec = {}
        check("BA's report records the experiment's decision, options, experiment, result and chosen option",
              rec.get("decision") == DECISION_EXPERIMENT["need"] and rec.get("experiment") == EXPERIMENT["run"]
              and rec.get("result") == "printed 3" and rec.get("chosen") == "accept bool"
              and rec.get("options") == [o["label"] for o in DECISION_EXPERIMENT["options"]], rec)
        check("each re-dispatch and the gated dispatch carry their decision line",
              len(self.carried) == 3 and all(c["line"] in c["prompt"] for c in self.carried)
              and GATE["gate"] in self.carried[-1]["prompt"], [c["where"] for c in self.carried])
        # the injected calls
        def probe(pred):
            return [pr for pr in self.probes if pred(pr)]

        def denied(pr, text):
            return any(b["hook"].endswith("pretool-overnight-hook-guard.py") and b["rc"] == 2 and text in b["text"]
                       for b in pr["blocks"])
        main_in = probe(lambda pr: pr["kind"] == "AskUserQuestion" and pr["who"] == "main" and pr["in_window"])
        sub_in = probe(lambda pr: pr["kind"] == "AskUserQuestion" and pr["who"] != "main" and pr["in_window"])
        main_after = probe(lambda pr: pr["kind"] == "AskUserQuestion" and pr["who"] == "main" and not pr["in_window"])
        check("an injected AskUserQuestion is denied (exit 2) with the decide text: main agent in the window, dev in "
              "the window, main agent after end_time",
              main_in and sub_in and main_after and all(denied(pr, DECIDE_TEXT["main"]) for pr in main_in + main_after)
              and all(denied(pr, DECIDE_TEXT["subagent"]) for pr in sub_in),
              [{"label": pr["label"], "blocks": [(b["hook"], b["rc"]) for b in pr["blocks"]]} for pr in main_in + sub_in + main_after])
        stops = probe(lambda pr: pr["kind"].startswith("Stop"))
        check("a forged ESCALATION_ACK line releases nothing: the Stop after it is blocked in the window (time-lock) "
              "and after end_time while the summary is missing (closeout)",
              len(stops) == 2 and any("TIME-LOCK ACTIVE" in b["text"] for b in stops[0]["blocks"])
              and any("CLOSEOUT GATE" in b["text"] and "overnight-summary" in b["text"] for b in stops[1]["blocks"]),
              [{"label": pr["label"], "blocks": [(b["hook"], b["rc"], b["text"][:160]) for b in pr["blocks"]]}
               for pr in stops])
        check("the session ends after end_time once retro and summary exist (the main agent's Stop passes), and the "
              "loop hook resets nothing after end_time",
              self.ended.get("stopped") and not self.ended.get("loop_reset_after_end"), self.ended)
        def qa_status(p):
            try:
                return (json.loads(read(os.path.join(self.project, f"docs/dev/qa-report-{p.sfx}.json"))).get("qa")
                        or {}).get("status")
            except (ValueError, AttributeError):
                return None
        verdicts = {p.index: qa_status(p) for p in self.pipes}
        check("both pipelines reach a QA pass", len(verdicts) == 2 and set(verdicts.values()) == {"pass"}, verdicts)
        stores = []
        with rp.acting("driver"):  # the sandbox's own roots (a scratch-mode run: the sandbox alone)
            for root in sorted(set(rp.layout.scratch)):
                for dp, dns, fns in os.walk(root):
                    dns[:] = [d for d in dns if d not in (".git", "venv", "__pycache__", "node_modules")]
                    if any(part in RECORD_STORES for part in dp.split(os.sep)):
                        stores += [os.path.join(dp, f) for f in fns]
        check("no file under an escalations/, escalation-admissions/, progress/ or deferred-checks/ directory",
              not stores, sorted(set(stores))[:20])
        check("0 hook errors", not rp.hook_errors, rp.hook_errors[:5])
        # a block at one of the variant's own dispatches is false even where a base kit's deviation quotes
        # its hook's words: no base replay has those steps
        left = [b for b in rp.blocks if not b["passed_by_deviation"] or re.sub(r" stop$", "", b["step"]) in self.own]
        check("no compliant step blocked (a declared base kit deviation aside)", not left,
              [(b["hook"], b["step"], b["text"][:200]) for b in left])
        with rp.acting("driver"):
            with open(os.path.join(rp.layout.out, "unattended.json"), "w") as fh:
                json.dump({"checks": res, "decisions": self.decision_rows(), "probes": self.probes,
                           "carried": [{"where": c["where"], "line": c["line"]} for c in self.carried],
                           "summary": self.summary_rel, "log": self.log_rel}, fh, indent=1)
        failed = [r["check"] for r in res if not r["ok"]]
        if failed:
            raise RuntimeError("variant=unattended: " + "; ".join(failed) + " (out/unattended.json)")

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
        out = []
        for name, b, _ in st.step_blocks("Implementation"):
            c = st.run_text(b.text, f"/stop Bash {name}", "Release the overnight time-lock")
            out.append((c.response.get("stdout", "") if c.ok else c.error).strip())
        said = "\n".join(x for x in out if x)
        s.stop(f"/stop ran the release wrapper:\n{said}\nThe working branch, the state record and the cycle log "
               "are left for review.", label="/stop Stop", deviation=self.o.devs.at("/stop Stop"))

    def run(self) -> None:
        self.launch()
        self.step1()
        until = int(self.rp.args["until"]) if self.rp.args.get("until") else None
        try:
            if self.variant == "stop":
                self.run_cycle(until=int(self.rp.args.get("stop_at", "12")))
            elif self.variant in ("qa-fail", "unattended"):
                self.run_cycle(until=until)
            else:
                if not self.run_cycle(until=until):
                    return
                self.run_cycle()
        except Refused as r:
            self.o.s.say(f"{r}: the dispatch was refused and the text gives no way on; the cycle stops here.")
        if "stopped" not in self.ended:  # variant=unattended ends at end_time; else the owner's /stop
            self.owner_stop()
        if self.unattended:
            self.unattended_checks()


VARIANTS = ("plain", "stop", "qa-fail", "unattended")


def run(rp) -> None:
    variant = rp.args.get("variant", "plain")
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}")
    rp.pipeline = "dev-overnight" if variant == "plain" else f"dev-overnight/{variant}"
    Night(rp, variant).run()
