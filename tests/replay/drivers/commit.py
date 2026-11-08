"""/commit, played compliantly from commands/commit.md of the tree under test, after /close
(drivers/close.py) of a /dev, /do or /dev-command task, after a /dev that was never closed, or as
`/commit --auto`.

The main agent types `/commit <task-id>` (Steps 1-2 bind TASK_ID: no tool call) and runs, as the
tree's text spells each one, read at run time:

* Step 3: the step's one Bash block (the close-report path, its mtime, the `--disposition --stage
  close` call), its output read as data: `DISPOSITION=`, the `GAP` lines, the `CHAIN=` line bound as
  ARTIFACT_CHAIN. `incomplete`: each gap on an artifact other than the close-report is routed (the
  Routes section: its declaring-dispatch reader on the gap's path, its own Bash call, the answer acted
  on as drivers/close.py does); with no such gap left, commands/close.md Steps 1-2 run for the task
  (drivers/close.py's Step 1 and Step 2, in /commit's session); the block runs again until it prints
  `chain_pass` (at most four rounds). A run with no DISPOSITION line is run once more, then the text's
  `OPERATION_STALLED:` line ends the turn.
* Step 5: the repository-plan block once; the late-repair state `invalid` or an empty plan is routed
  on the path the text names and the block run again. Then the attribution-log slice block; the
  dispatch-snapshot manifest (the state dir and session id read in Bash, each plan entry's `git status
  --porcelain=v1`, then a Write of the fields the text lists); one grant per plan entry with the
  writer block of the step.
* Step 6: the planning dispatch (changelog-analyst with Step 7's prompt, DRYRUN=true), the
  pre-commit QA dispatch from the step's prompt block, the decision read of the commit-qa-report's
  last line. A `COMMIT: REJECT` (variant reject) revokes the grant with the text's revoke call, routes
  its finding (Routes) and runs a fresh round from Step 5.
* Step 7: changelog-analyst from the step's prompt block, the real commit in the toy project and
  the push-gate token as the tree's agent text writes it; the status block read and handled per
  its commit_status (a `hook_blocked` failure: the text's one AskUserQuestion, then Steps 5-7 again).
* Step 8: the selection algorithm as the text orders it (context spec_path, the close-report's
  continuation line, the specs glob), ending in the outcome the text prints.
* `--auto`: the discovery block and each discovered parent walked through Steps 3-8, the batch
  summary; when discovery lists no parent, the task's lifecycle row (dev-lifecycle.py scan, run by
  the driver, no agent call) is recorded as a fact.
* The waits (variant waits): each one AskUserQuestion with the options the text names (the stub owner
  picks the first), as AskUserQuestion tool calls the hooks see.

The changelog-analyst is played from agents/changelog-analyst.md of the tree (agents.Player plus
the role work below): Phase 1's plan checks (the three equality reads and the status read), Phase
2's dev-report resolution (the resolve-dev-report.py call as the text spells it, the report Read,
the provenance diff), the candidate set the whitelist items name (the report's files, the chain's
commit_whitelist_artifacts, the anchored post-chain artifacts of the task) intersected with git
status and with QA_APPROVED_FILES; in a dry run Phase 4's index save and restore around the
staging; in a real run the message written with the Write tool at the path the text gives
(Phase 8 step 1's `MSGFILE=` path, its placeholders bound), then one Bash process holding the Phase 3 lock block
(lock and session-index init as written) that runs Phase 4's pre-staged check, Phase 5's
individual `git add -- <path>`, the Phase 8 drift re-check and commit block and the SHA/branch
reads, printing the descriptor; then Phase 10 as the tree spells it (the token writer's call; or,
on a text that writes the token with the Write tool, the descriptor values computed in Bash, the
pre-write HEAD check, the Write, the post-write HEAD check). Driver resolution of one textual
conflict: the text asks the MSGFILE Write to happen while the fd-9 lock is held by the staging
Bash process, which a tool call cannot do; the driver stages and commits in one process after
the Write (the lock covers stage→commit), and records the staged set it wrote the message from.

Commit QA is played from Step 6's prompt: the diff vs HEAD and the on-disk contents of every
planned path, the transcript at the obligation's path ending `COMMIT: APPROVE`.

Driver arguments (cli.py --arg K=V), when run on its own (`--driver commit`):
  after=dev|dev-command   the cycle committed (default dev; /do is drivers/do.py)
  variant=plain|route|append   the /close before it (drivers/close.py's variants)
  variant=auto            /dev, then `/close --auto`, then `/commit --auto`
  variant=commit-route    /close lands, then the lane dev report (a fan-out cycle's first lane's) is
                          removed and /commit is typed in a later session: Step 3's call names the
                          report, its owner is dispatched again, the same call re-run (acceptance 7's
                          fourth case; F8c)
  removed=lane|aggregate  with variant=commit-route and a fan-out cycle, the report removed after
                          /close: the first lane's dev report (lane, the default; F8c) or the canonical
                          aggregate (aggregate)
  variant=full            route, append and commit-route in one cycle: the lane QA report removed
                          after /dev, /close in a later session (Step 0's routing round, then a
                          close-QA finding on the product file, dev again, the appended round), the
                          lane dev report removed after CLOSE: YES, /commit in a later session
  variant=unclosed        /dev lands, no /close; /commit in a later session: Step 3's call names the
                          close gap, close.md Steps 1-2 run, it commits (P4 acceptance 4 (d))
  variant=laneqa          /dev stops after its dev (Step 12; its QA never dispatched), no /close;
                          /commit in a later session: the qa-report gap first (the reader's todo step,
                          a fresh QA dispatch), then the close gap (close.md Steps 1-2), it commits
                          (P4 acceptance 4 (c))
  variant=aggregate       a 2-lane /dev, /close lands, the canonical aggregate removed; /commit in a
                          later session: Step 3's call names it, its owner reruns, it commits (P4
                          acceptance 4 (e))
  variant=reject          commit QA's first round rejects citing no artifact: its own QA reruns and
                          names the product file, its writer (dev) reruns, a fresh round from Step 5
                          approves, it commits (P4 acceptance 4 (f))
  variant=waits           /dev lands, no /close; a later session types `/commit` (no task context:
                          the Task question lists the close_pending task, the stub picks it; Step 3
                          closes it), its first Step 7 commit is refused by a hook (the
                          Authorize question, then Steps 5-7 again); then `/commit --auto --force`
                          (the Flags question) (P4 acceptance 5's /commit cases)
  variant=late-repair     BA's stage removed after /dev, `/close --late-repair` in a later
                          session (drivers/close.py's late-repair case: the route admitted, Steps 1-4),
                          then /commit in a later session: Step 3's call, Step 5's late-repair state and
                          the plan from the report it names, the commit (P4 acceptance 14's landing)
  variant=late-repair-drift   the same with drivers/close.py's late-repair-drift route: finalize writes the
                          effective report, Step 5's state is verified and the plan comes from that report
  variant=late-repair-qa  the late-repair case to CLOSE: YES, then the task's QA report removed and
                          /commit typed in a later session (F8r): Step 3's call names the report, its
                          QA dispatch runs again, the commit lands
  cycle_variant=V         the /dev variant (drivers/dev.py; fanout runs the fan-out cycle)
  session=same|later      /close and /commit typed in the cycle's session or a later one
                          (default same for plain, later for every other variant)

Respellings: RESPELLINGS below (base-text paths, row 7). Deviations: DEVIATIONS below.
"""
from __future__ import annotations

import json
import os
import re
import shlex

from .. import agents, cmdtext
from ..pipeline import Deviations, Respelling, Orchestrator, utc_now
from ..replay import Deviation
from . import close as closedrv

PIPELINE = "commit"
# The artifact check's cost of each variant (tests/artifact_graph/shards.py balances its CI shards by it):
# CPU seconds of the shipped and armed traced replays and their differential runs, measured at b8e34f4
COST = {"auto": 482, "commit-route": 694, "full": 796}
# The variants the artifact check replays (tests/artifact_graph/runtime.py): the docstring's others are run
# on their own (`--arg variant=...`).
VARIANTS = ["auto", "commit-route", "full"]

RESPELLINGS = [
    Respelling("M1 controller", r"source venv/bin/activate && python3 scripts/late-repair-controller\.py",
               "python3 ~/.claude/scripts/late-repair-controller.py", "commands/commit.md Step 5 (:313, :320 at 2acc29b)"),
    Respelling("M2 resolver", r"(?<![\w/~.-])python3 scripts/resolve-dev-artifact-chain\.py",
               "python3 ~/.claude/scripts/resolve-dev-artifact-chain.py", "commands/commit.md Step 5 (:334 at 2acc29b)"),
    Respelling("M3 grant writer", r"source venv/bin/activate && python3 ~/\.claude/scripts/write-commit-grant\.py",
               "python3 ~/.claude/scripts/write-commit-grant.py",
               "commands/commit.md Steps 5-7 (:459, :486, :570, :821 at 2acc29b)"),
    Respelling("M4 discovery", r"(?<![\w/~.-])python3 scripts/dev-lifecycle\.py",
               "python3 ~/.claude/scripts/dev-lifecycle.py", "commands/commit.md --auto (:965 at 2acc29b)"),
    # agents/changelog-analyst.md:399 at 2acc29b: the dev-report resolution by a .claude/scripts path a
    # product repository lacks, with CLAUDE_PROJECT_DIR unset in the CLI's Bash (E5), mode 100644.
    Respelling("M5 dev-report resolution", r'"?\$\{CLAUDE_PROJECT_DIR\}/\.claude/scripts/resolve-dev-report\.py"?',
               "python3 ~/.claude/scripts/resolve-dev-report.py", "agents/changelog-analyst.md Phase 2 (:399 at 2acc29b)"),
]

PRIVILEGE_DEVIATION = ("agent:changelog-analyst Bash stage and commit *", Deviation(
    "hooks/pretool-git-privilege-guard.py", "looks like an unresolved shell variable reference",
    "Phase 8's commit line as the agent text spells it"))
DEVIATIONS = Deviations([
    # DEVIATION: "[Orchestrator Gate] BLOCKED: Bash used consecutively beyond limit (6/5)."
    # The command's own run of Bash blocks between two dispatches outnumbers the gate's cap of 5.
    ("*Bash*", Deviation("hooks/pretool-orchestrator-gate.py", "Bash used consecutively beyond limit",
                         "the command's own run of Bash blocks between dispatches")),
    # DEVIATION: "BLOCKED: removal-policy — UNRESOLVED census_fatal:unbalanced:single_quote"
    # pretool-bash-safety.sh refuses the analyst's Phase 3 lock block as its agent text spells it (the
    # apostrophe of "the repo's .git/" in its comment).
    # DEVIATION: "BLOCKED: removal-policy — UNRESOLVED unproven_boundary_with_removal_reference:mkdir:"
    # pretool-bash-safety.sh refuses the base text's Phase 10 descriptor step (its `mkdir -p
    # "/tmp/agentic-commit/push/..."`, the form that text calls the accepted one).
    ("agent:changelog-analyst Bash token descriptor *", Deviation(
        "hooks/pretool-bash-safety.sh", "unproven_boundary_with_removal_reference:mkdir",
        "Phase 10 steps 1-5 as the base agent text spells them")),
    # (hookrun keeps the last 4000 characters of a hook's output: for this long block the quote is its REASON line)
    ("agent:changelog-analyst Bash stage and commit *", Deviation(
        "hooks/pretool-bash-safety.sh", "every execution boundary must be provably inert",
        "Phase 3's lock block as the agent text spells it")),
    # DEVIATION: "BLOCKED: agent git commit - the -C argument '${GIT_ROOT}' looks like an unresolved shell
    # variable reference, not a concrete path."
    # pretool-git-privilege-guard.py refuses Phase 8's commit line as the agent text spells it
    # (`git -C "${GIT_ROOT}" commit -F "<msgfile>"`, CP-2's permitted form).
    # DEVIATION: "BLOCKED: removal-policy — FORBIDDEN_REMOVAL filesystem_removal:rm"
    # pretool-bash-safety.sh refuses Phase 8's cleanup of the message file (`rm -f "${MSGFILE}"`).
    ("agent:changelog-analyst Bash rm MSGFILE *", Deviation(
        "hooks/pretool-bash-safety.sh", "FORBIDDEN_REMOVAL filesystem_removal:rm",
        "Phase 8's separate cleanup step as the agent text spells it")),
    PRIVILEGE_DEVIATION,
])

STATUS_BEGIN, STATUS_END = "--- CHANGELOG-ANALYST-STATUS-BEGIN ---", "--- CHANGELOG-ANALYST-STATUS-END ---"
# /commit's success outcomes (Step 7's commit_status, as the --auto walk counts them).
COMMITTED = ("committed", "nothing_to_commit", "push_gate_reconciled", "nothing_to_commit_precommitted")
GAP_RE = re.compile(r'^GAP artifact=("(?:[^"\\]|\\.)*"|\S+) problem=("(?:[^"\\]|\\.)*"|\S+): (.*) lane=(\S+)$')


def _last_json(text: str):
    for line in reversed((text or "").strip().splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def _token(value: str) -> str:
    return json.loads(value) if value.startswith('"') else value


def parse_disposition(stdout: str) -> dict:
    """The disposition call's output as data: its DISPOSITION line, GAP lines and CHAIN line."""
    out = {"disposition": None, "gaps": [], "chain": None}
    for line in (stdout or "").split("\n"):
        m = re.match(r"^DISPOSITION=(\S+)", line)
        if m:
            out["disposition"] = m.group(1)
            continue
        if line.startswith("CHAIN="):
            try:
                out["chain"] = json.loads(line[len("CHAIN="):])
            except ValueError:
                pass
            continue
        m = GAP_RE.match(line)
        if m:
            msg = m.group(3)
            out["gaps"].append({"artifact": _token(m.group(1)), "problem": _token(m.group(2)),
                                "message": _token(msg) if msg.startswith('"') else msg, "lane": m.group(4)})
    return out


class CommitRun:
    def __init__(self, rp, session, tid: str, producer=None, extra_devs=(), variant: str = "plain"):
        self.rp, self.tid, self.producer, self.variant = rp, tid, producer, variant
        pairs = (list(DEVIATIONS.pairs) + list(closedrv.DEVIATIONS.pairs) + list(extra_devs)
                 + list(getattr(getattr(producer, "devs", None), "pairs", [])))
        self.devs = closedrv.kept_only(rp, Deviations(pairs))
        rp.deviation_at = self.devs.at  # the subagents' own calls take the same deviations by label
        self.o = Orchestrator(rp, "commit", session=session, deviations=self.devs,
                              respellings=RESPELLINGS + closedrv.RESPELLINGS, rules=self._rules())
        self.analyst_text = self.o.tree.agent_text("changelog-analyst")
        self.plan: dict = {}
        self.chain: dict = {}
        self.stalled = ""
        self.plan_files: dict = {}
        self.landed: list = []
        self.status: dict = {}
        self.outcome = ""
        self.rand = 0
        self.rounds = 0              # Step 6 rounds
        self.hook_block = None       # (hook, text) of a refusal the analyst's commit met
        self.refuse_commit = variant == "waits"  # the first Step 7 commit meets the privilege guard's refusal
        self.reject_first = variant == "reject"

    def _rules(self):
        return [(r"^(?:TASK_ID|task-id|task_id)$", lambda m: self.tid),
                (r"^TASK_ID or \\?\"bulk\\?\"$", lambda m: self.tid)]

    def label(self, text: str) -> str:
        return f"/commit {text}"

    def run_text(self, text: str, label: str, desc: str, capture=(), rules=()):
        o = self.o
        text = o.bind(text, list(rules))
        return closedrv.run_captured(o, o.shell_bind(text), desc, label, capture)

    def ask(self, header: str, question: str, options: list, label: str) -> str:
        """One AskUserQuestion with the options the text names; the stub owner picks the first."""
        tin = {"questions": [{"question": question, "header": header[:12], "multiSelect": False,
                              "options": [{"label": l, "description": d} for l, d in options]}]}
        call = self.o.s.tool("AskUserQuestion", tin, label=self.label(label), deviation=self.devs.at(self.label(label)))
        ans = (call.response.get("answers") or {}).get(question, "") if call.ok else ""
        closedrv.fact(self.rp, "commit question", {"label": label, "header": header, "question": question,
                                                   "options": [l for l, _ in options], "answer": ans,
                                                   "blocked": call.blocked})
        return ans

    # ------------------------------------------------------------ Step 3
    def disposition(self, label: str) -> tuple:
        o = self.o
        block = o.block("Step 3", anchor="--disposition")
        c = self.run_text(block, self.label(f"{label} Bash disposition"),
                          "Step 3: the close-report path, its age and the task's disposition", capture=("CLOSE_REPORT",))
        out = (c.response.get("stdout") or "") if c.ok else (c.error or "")
        return c, parse_disposition(out)

    def step3(self, rounds: int = 4) -> bool:
        for k in range(rounds + 1):
            c, d = self.disposition(f"Step 3 round {k}")
            if d["disposition"] is None:  # an instrument failure: run once more, then the stalled line
                c, d = self.disposition(f"Step 3 round {k} again")
                if d["disposition"] is None:
                    err = ((c.response.get("stderr") or "") if c.ok else (c.error or "")).strip().split("\n")[-1]
                    self.stalled = f"OPERATION_STALLED: {err}"
                    self.o.s.say(self.stalled)
                    return False
            if d["chain"] is not None:
                self.chain = d["chain"]
            closedrv.fact(self.rp, "commit Step 3", {"round": k, "disposition": d["disposition"],
                                                     "gaps": [(g["artifact"], g["problem"]) for g in d["gaps"]],
                                                     "chain_line": d["chain"] is not None})
            if d["disposition"] == "chain_pass":
                return True
            if k == rounds:
                return False
            close_rel = f"docs/dev/close-report-{self.tid}.md"
            dev_gaps = [g for g in d["gaps"] if g["artifact"] != close_rel]
            if dev_gaps:
                for n, g in enumerate(dev_gaps, 1):
                    self.route(g["artifact"], f"{g['problem']}: {g['message']}", f"Step 3 round {k + 1} gap {n}")
            else:
                self.close_steps(f"Step 3 round {k + 1}")
        return False

    def close_steps(self, label: str) -> str:
        """commands/close.md Steps 1-2 for this task, as /close runs them (drivers/close.py), in /commit's
        session, its labels under /commit."""
        cr = closedrv.CloseRun(self.rp, self.o.s, self.tid, producer=self.producer)
        cr.label = lambda text: self.label(f"{label} close.md {text}")
        cr.chain = dict(self.chain)
        cr.o.values.update(TASK_ID=self.tid, PROJECT_ROOT=self.o.project,
                           ARTIFACT_CHAIN=json.dumps(self.chain) if self.chain else "")
        if hasattr(cr, "steps_1_2"):
            last = cr.steps_1_2()
        else:
            cr.step1()
            last = cr.step2()
        self.rp.deviation_at = self.devs.at
        closedrv.fact(self.rp, "commit close.md Steps 1-2", {"label": label, "verdict": last})
        return last

    # ------------------------------------------------------------ Routes
    def route(self, path: str, detail: str, label: str, edits=None):
        """The Routes section: the reader on the path, its answer acted on (drivers/close.py)."""
        o = self.o
        sec = o.section("Routes")
        call = closedrv.reader_call("", sec, path)
        if not call:
            raise cmdtext.TextNotFound("the Routes section has no declaring-dispatch reader")
        cmd, fn = call
        c = self.run_text(cmd, self.label(f"{label} Bash {fn}"), "Who owes the artifact")
        ans = closedrv.last_json(c.response.get("stdout") or "") if c.ok else None
        closedrv.fact(self.rp, "owing dispatch", {"label": label, "path": path, "blocked": c.blocked,
                                                   "answer": closedrv.summarize_answer(ans, o.s)})
        if self.commit_qa_answer(ans, path):
            return self.rerun_commit_qa(ans, label)
        d, role = closedrv.dispatch_answer(self, ans, path, detail, label, edits=edits)
        self.rp.deviation_at = self.devs.at
        return d, role

    def commit_qa_answer(self, ans, path: str) -> bool:
        return (isinstance(ans, dict) and ans.get("source") == "dispatch"
                and os.path.basename(path) == f"commit-qa-report-{self.tid}.md")

    # ------------------------------------------------------------ Step 5
    def step5_plan(self, rounds: int = 3) -> bool:
        o = self.o
        block = o.block("Step 5", anchor="LATE_REPAIR_JSON")
        caps = ("CONTROL_ROOT", "NESTED_REPO", "TASK_DOCS_ROOT", "TASK_PROJECT_ROOT", "LATE_REPAIR_JSON",
                "LATE_REPAIR_STATE", "TASK_REPORT", "REPOSITORY_PLAN")
        for k in range(rounds + 1):
            c = self.run_text(block, self.label(f"Step 5 Bash plan {k}"),
                              "Step 5: late-repair state and repository plan", capture=caps)
            closedrv.fact(self.rp, "commit Step 5", {
                "label": f"Step 5 Bash plan {k}", "ok": c.ok,
                "late_repair_state": o.values.get("LATE_REPAIR_STATE") if c.ok else None,
                "late_repair_json": o.values.get("LATE_REPAIR_JSON"),
                "task_report": os.path.basename(o.values.get("TASK_REPORT") or "").replace(self.tid, "<task>")})
            try:
                late = json.loads(o.values.get("LATE_REPAIR_JSON") or "{}")
                self.plan = json.loads(o.values.get("REPOSITORY_PLAN") or "{}")
            except ValueError:
                late, self.plan = {}, {}
            if late.get("state") == "invalid" and k < rounds:
                self.route(late.get("path") or "", "late-repair state invalid (State C)", f"Step 5 round {k + 1}")
                continue
            if not self.plan.get("repositories") and k < rounds:
                self.route(o.values.get("TASK_REPORT") or "", "the repository plan could not be built",
                           f"Step 5 round {k + 1}")
                continue
            break
        return bool(self.plan.get("repositories"))

    def attribution(self) -> None:
        """The attribution slice's block; one that also prints the manifest's inputs is the call manifest()
        reads them from."""
        o = self.o
        block = o.block("Step 5", anchor="ATTRIBUTION_FILES=()")
        c = self.run_text(block, self.label("Step 5 Bash attribution slice"), "Attribution-log slice",
                          capture=("ATTRIBUTION_LOG",))
        self.snapshot = c if "status --porcelain" in block else None

    def manifest(self) -> None:
        o = self.o
        c = getattr(self, "snapshot", None)
        if c is None:  # a text whose attribution block prints no manifest input: the inputs in a call of their own
            repos = [e["repo_root"] for e in self.plan.get("repositories") or []]
            cmd = (". ~/.claude/hooks/lib/harness_state_dir.sh\nharness_state_dir\n"
                   'echo "${CLAUDE_CODE_SESSION_ID:-$CLAUDE_SESSION_ID}"\n'
                   + "\n".join(f"echo '--- {r}'; git -C {shlex.quote(r)} status --porcelain=v1" for r in repos))
            c = o.run(cmd, "State dir, session id and status per plan entry", self.label("Step 5 Bash manifest inputs"))
        # (the values the snapshot call kept follow its output as `declare -p` lines)
        out = (c.response.get("stdout") or "").split("\ndeclare -")[0].split("\n") if c.ok else []
        state, sid = (out + ["", ""])[:2]
        files, cur = {}, None
        for line in out[2:]:
            if line.startswith("--- "):
                cur = line[4:]
                files[cur] = []
            elif cur and line.strip():
                files[cur].append(line[3:])
        doc = {"session_id": sid, "task_id": self.tid, "dispatched_at": utc_now(), "repository_plan": self.plan,
               "artifact_chain": self.chain or None, "files_at_dispatch": files}
        path = os.path.join(state or self.rp.layout.state, f"claude-commit-manifest-{sid or o.s.sid}.json")
        # A later round of the same session finds its own manifest: Read, then edit in place (the write guard).
        agents.put(o.s.main, path, json.dumps(doc, indent=2) + "\n", self.label("Step 5 Write manifest"))

    def mint(self) -> None:
        o = self.o
        writer = next(b.text for b in cmdtext.blocks(o.section("Step 5"), None, "bash")
                      if "write-commit-grant.py" in b.text and "PLANNED_REPO_ROOT" in b.text)
        for k, e in enumerate(self.plan.get("repositories") or []):
            o.values["PLANNED_REPO_ROOT"] = e["repo_root"]
            self.run_text(writer, self.label(f"Step 5 Bash mint {k}"), "Mint the repository's commit grant")

    def revoke(self, label: str) -> None:
        """Grant hygiene: the text's revoke call."""
        o = self.o
        cmd = next(b.text for b in cmdtext.blocks(o.section("Step 6"), None, "bash") if "--revoke-only" in b.text)
        self.run_text(cmd, self.label(f"{label} Bash revoke grant"), "Revoke the Step 5 commit grant")

    # ------------------------------------------------------------ the analyst's prompt
    def analyst_prompt(self, dryrun: bool, approved: dict) -> str:
        o = self.o
        tpl = next(b.text for b in cmdtext.blocks(o.section("Step 7")) if "CONTROL_ROOT=<" in b.text)
        tpl = re.sub(r'<"([^"]*)" when BULK=false, else [^>]*>', lambda m: json.dumps(m.group(1).replace("$TASK_ID", self.tid)), tpl)
        # The obligation's plan roots, where the text declares them: the plan's repo_root values in order.
        roots = [e["repo_root"] for e in self.plan.get("repositories") or []]
        tpl = re.sub(r"<the JSON array of REPOSITORY_PLAN\.repositories\[\]\.repo_root\b[^>]*>",
                     lambda m: json.dumps(roots), tpl)
        values = {"CONTROL_ROOT": o.values.get("CONTROL_ROOT", ""), "NESTED_REPO": o.values.get("NESTED_REPO", ""),
                  "REPOSITORY_PLAN": json.dumps(self.plan), "ARTIFACT_CHAIN": json.dumps(self.chain) if self.chain else "",
                  "ATTRIBUTION_LOG": o.values.get("ATTRIBUTION_LOG", ""), "TASK_ID": self.tid, "BULK": "false",
                  "DRYRUN": "true" if dryrun else "false", "FORCE": "false",
                  "QA_APPROVED_FILES": json.dumps(approved) if approved else ""}
        lines = []
        for line in tpl.split("\n"):
            m = re.match(r"^([A-Z_]+)=<.*>$", line)
            lines.append(f"{m.group(1)}={values[m.group(1)]}" if m and m.group(1) in values else line)
        prompt = o.instantiate("\n".join(lines), self.tid)
        return o.bind(prompt, [(r"^(?:TASK_ID|task-id)$", self.tid)])

    def dispatch_analyst(self, dryrun: bool, approved: dict, label: str):
        o = self.o
        prompt = self.analyst_prompt(dryrun, approved)
        act = agents.Act(work=self.analyst_work(dryrun, approved), summary="commit workflow")
        player = agents.Player(o.tree, prompt, act, role="changelog-analyst")
        d = o.s.dispatch("changelog-analyst", prompt, description="changelog-analyst", body=player.body,
                         result=player.final, label=label, deviation=self.devs.at(label))
        text = ((d.response.get("content") or [{}])[0].get("text") or "") if d.response else ""
        m = re.search(re.escape(STATUS_BEGIN) + r"\s*(\{.*?\})\s*" + re.escape(STATUS_END), text, re.S)
        try:
            self.status = json.loads(m.group(1)) if m else {}
        except ValueError:
            self.status = {}
        return d

    # ------------------------------------------------------------ the analyst's work
    def candidates(self, sub, repo: dict, report_rel: str | None, status_paths: list) -> list:
        """The whitelist items the agent text names for this repository, intersected with git status."""
        tid, project = self.tid, self.rp.layout.project
        owned = list(repo.get("owned_paths") or [])
        want = set(owned)
        if repo.get("cycle_artifact_repo") or os.path.realpath(repo["repo_root"]) == os.path.realpath(project):
            want.update(self.chain.get("commit_whitelist_artifacts") or [])
            report = self.plan.get("report_path") or ""  # item 4's late-repair addition: the plan's effective report
            if os.path.basename(report) == f"dev-report-{tid}.effective.json":
                want.add(os.path.relpath(report, repo["repo_root"]) if os.path.isabs(report) else report)
        # `git status --porcelain=v1` names an untracked directory once (`?? docs/`): every path under it is in it.
        files = {p for p in status_paths if not p.endswith("/")}
        dirs = [p for p in status_paths if p.endswith("/")]
        if dirs:  # the untracked files under them, as Phase 2's own `git ls-files --others --exclude-standard` lists them
            c = sub.bash(f"git -C {shlex.quote(repo['repo_root'])} ls-files --others --exclude-standard -- "
                         + " ".join(shlex.quote(d) for d in dirs), "Phase 2: the untracked files",
                         label=f"{sub.role} Bash untracked {repo.get('order', 0)}")
            files.update(l for l in (c.response.get("stdout") or "").split("\n") if l.strip()) if c.ok else None
        out = set()
        for p in files:
            b = os.path.basename(p)
            if p in want:
                out.add(p)
            elif p.startswith("docs/dev/") and (b in (f"close-report-{tid}.md", f"acceptance-criteria-{tid}.json")
                                                or ("-inspector-report-" in b and tid in b)):
                out.add(p)
            elif (not self.chain and p.startswith("docs/dev/") and any(b.startswith(f"{k}-{tid}") for k in (
                    "ticket", "context", "dev-report", "do-report", "qa-report", "completion"))):
                out.add(p)
        return sorted(out)

    def analyst_work(self, dryrun: bool, approved: dict):
        def work(sub, brief, player):
            o, tid = self.o, self.tid
            results, plan_groups = [], []
            for order, repo in enumerate(self.plan.get("repositories") or []):
                root, branch, head = repo["repo_root"], repo.get("branch", ""), repo.get("expected_head", "")
                q = shlex.quote(root)
                # Phase 1: the three live equality reads, then the authoritative status read.
                sub.bash(f"git -C {q} rev-parse --show-toplevel\ngit -C {q} branch --show-current\n"
                         f"git -C {q} rev-parse HEAD", "Phase 1: live repo, branch and HEAD",
                         label=f"{sub.role} Bash phase 1 {order}")
                st = sub.bash(f'git -C {q} status --porcelain=v1', "Phase 1: repository status",
                              label=f"{sub.role} Bash status {order}")
                lines = [l for l in (st.response.get("stdout") or "").split("\n") if l.strip()] if st.ok else []
                if order == 0:
                    self.snapshot_check(sub)
                status_paths = [l[3:].split(" -> ")[-1] for l in lines]
                # Phase 2: the dev-report resolution as the text spells it.
                report_rel = self.resolve_report(sub, root, order)
                if report_rel:
                    sub.read(os.path.join(root, report_rel) if not os.path.isabs(report_rel) else report_rel,
                             label=f"{sub.role} Read report {order}")
                    self.provenance(sub, root, report_rel, order)
                cands = self.candidates(sub, repo, report_rel, status_paths)
                if approved:
                    cands = [p for p in cands if p in (approved.get(root) or [])]
                if dryrun:
                    self.dry_stage(sub, root, cands, order)
                    plan_groups.append({"repo": root, "commit_message": self.subject(), "files": cands})
                    results.append({"order": order, "repo_root": root, "status": "not_attempted",
                                    "expected_head": head, "push_gate_written": False})
                    continue
                results.append(self.commit_repo(sub, repo, cands, order))
            self.plan_files = {g["repo"]: g["files"] for g in plan_groups} if dryrun else self.plan_files
            committed = [r for r in results if r["status"] == "committed"]
            status = "dryrun" if dryrun else ("committed" if committed and len(committed) == len(results) else
                                              "partially_committed" if committed else "failed")
            content = {"commit_status": status, "repository_results": results,
                       "baseline_check": {"verdict": "not_provided"}}
            if status == "failed" and self.hook_block:
                content.update(failure_code="hook_blocked", failure_reason=": ".join(self.hook_block))
            elif status == "failed":
                content.update(failure_code="git_error", failure_reason="no repository commit landed")
            player.act.content["changelog-status.v1"] = content
            from ..schemagen import errors, instance
            schema = player.tree.schema("changelog-status.v1")
            bad = errors(schema, instance(schema, content))
            if bad:
                raise agents.PlayError(f"the status block is invalid against changelog-status.v1: {bad}")
            if dryrun:
                player.act.final_line = ""
                player.b.literal_lines.append("PLAN_GROUPS: " + json.dumps(plan_groups))
            return None
        return work

    def snapshot_check(self, sub) -> None:
        """The Dispatch-snapshot check (warn-only) where the agent text keeps it: the manifest at the path it
        names for this session, then the glob it falls back to."""
        try:
            para = next(p for p in re.split(r"\n\s*\n", self.analyst_text) if "Dispatch-snapshot check" in p)
        except StopIteration:
            return
        sid = re.search(r"`(SID=\"\$\{CLAUDE_CODE_SESSION_ID[^`]*)`", para)
        path = re.search(r"check for `(/[^`]*claude-commit-manifest-\$\{SID\}\.json)`", para)
        pattern = re.search(r"glob `(/[^`]*claude-commit-manifest-\*\.json)`", para)
        if sid and path:
            sub.bash(f'{sid.group(1)}\ncat "{path.group(1)}"', "Phase 1: the dispatch-snapshot manifest",
                     label=f"{sub.role} Bash dispatch snapshot")
        if pattern:
            sub.tool("Glob", {"pattern": os.path.basename(pattern.group(1)), "path": os.path.dirname(pattern.group(1))},
                     label=f"{sub.role} Glob dispatch manifests")

    def resolve_report(self, sub, root: str, order: int) -> str:
        """Phase 2's dev-report resolution: git status piped into resolve-dev-report.py with the three flags."""
        sec = cmdtext.section(self.analyst_text, "Phase 2: File classification")
        m = re.search(r"into\s+`([^`]*resolve-dev-report\.py\"?)`", sec)
        if not m:
            return ""
        script = m.group(1)
        cmd = (f"git -C {shlex.quote(root)} status --porcelain=v1 | {script} --task-id {shlex.quote(self.tid)} "
               f"--git-root {shlex.quote(root)} --control-root {shlex.quote(self.o.values.get('CONTROL_ROOT', root))}")
        cmd = self.o.respell(cmd, f"{sub.role} Bash resolve-dev-report {order}")
        c = sub.bash(cmd, "Phase 2: resolve the dev-report path", label=f"{sub.role} Bash resolve-dev-report {order}")
        path = (c.response.get("stdout") or "").strip() if c.ok else ""
        if path:
            return os.path.relpath(path, root) if os.path.isabs(path) else path
        # No dev-report: the do-report path of the text (same walk, control-root fallback).
        do = f"docs/dev/do-report-{self.tid}.json"
        return do if os.path.isfile(os.path.join(root, do)) else ""

    def provenance(self, sub, root: str, report_rel: str, order: int) -> None:
        try:
            doc = json.loads(agents.peek(self.rp, sub.role, os.path.join(root, report_rel)))
        except (OSError, ValueError):
            return
        base = doc.get("baseline_head_sha") or ""
        if base:
            sub.bash(f"git -C {shlex.quote(root)} cat-file -e {base}^{{commit}} && "
                     f"git -C {shlex.quote(root)} diff --name-only {base}", "Phase 2: provenance diff since baseline",
                     label=f"{sub.role} Bash provenance {order}")

    def subject(self) -> str:
        """The message's subject line the analyst authors from the plan's owned paths."""
        owned = [p for r in self.plan.get("repositories") or [] for p in r.get("owned_paths") or []]
        if any(p.startswith(".claude/commands/") for p in owned):
            return "feat(commands): add the project test command"
        return "fix(toy): add validates its arguments"

    def dry_stage(self, sub, root: str, cands: list, order: int) -> None:
        """A dry run (Phase 4): the exact index bytes saved, an exit trap restoring them, the candidate set
        staged and its staged stat read."""
        q = shlex.quote(root)
        idx = os.path.join(root, ".git", "index")
        saved = f"/tmp/claude-scratch/changelog-analyst/index-{self.tid}-{order}.bak"
        add = "\n".join(f"git -C {q} add -- {shlex.quote(p)}" for p in cands)
        sub.bash(f"mkdir -p /tmp/claude-scratch/changelog-analyst\ncp -p {shlex.quote(idx)} {saved}\n"
                 f"trap 'cp -p {saved} {shlex.quote(idx)}' EXIT\n{add}\ngit -C {q} diff --cached --stat",
                 "Dry run: stage the candidate set, then restore the index", label=f"{sub.role} Bash dry-run stage {order}")

    def commit_repo(self, sub, repo: dict, cands: list, order: int) -> dict:
        o, tid = self.o, self.tid
        root, head = repo["repo_root"], repo.get("expected_head", "")
        q = shlex.quote(root)
        result = {"order": order, "repo_root": root, "status": "nothing_to_commit", "expected_head": head,
                  "push_gate_written": False}
        if not cands:
            return result
        self.rand += 1
        rand = f"r{self.rand:04d}x"
        self.rp.rand(rand)
        # Phase 8 step 1's message path as the agent text gives it (`MSGFILE=...`), its placeholders bound.
        p8 = cmdtext.section(self.analyst_text, "Phase 8: Execute commit")
        tpl = re.search(r"`MSGFILE=([^`]+)`", p8)
        if not tpl:
            raise cmdtext.TextNotFound("Phase 8 names no `MSGFILE=` message path")
        tpl = tpl.group(1)
        msgfile = (tpl.replace("<TASK_ID-or-bulk>", tid).replace("<short-rand>", rand)
                   .replace("<unique>", f"{tid}-{rand}"))
        stat = sub.bash(f"git -C {q} diff --stat HEAD -- " + " ".join(shlex.quote(p) for p in cands),
                        "Phase 6: the diff stat of the candidate set", label=f"{sub.role} Bash diff stat {order}")
        message = f"{self.subject()}\n\nTask-id: {tid}\n{(stat.response.get('stdout') or '') if stat.ok else ''}"
        sub.write(msgfile, message, label=f"{sub.role} Write MSGFILE {order}")
        lock = cmdtext.block(self.analyst_text, "Phase 3: Serialization", lang="bash", index=0)
        commit = next(b.text for b in cmdtext.blocks(self.analyst_text, "Phase 8: Execute commit", "bash")
                      if "commit -F" in b.text)
        reads = next(b.text for b in cmdtext.blocks(self.analyst_text, "Phase 8: Execute commit", "bash")
                     if "COMMIT_SHA=" in b.text)
        # After each group's commit, the shared-index sync as Phase 3's text spells it (inline code).
        sync = re.search(r"`(python3 [^`]*session-index\.py\"? sync-shared [^`]*)`",
                         cmdtext.section(self.analyst_text, "Phase 3: Serialization"))
        sync = " ".join(sync.group(1).split()) + "\n" if sync else ""
        staged = "\n".join(cands)
        script = (f"GIT_ROOT={q}\n" + lock.rstrip("\n") + "\n"
                  f"git -C \"${{GIT_ROOT}}\" diff --cached --name-only\n"
                  + "\n".join(f'git -C "${{GIT_ROOT}}" add -- {shlex.quote(p)}' for p in cands) + "\n"
                  f"ACTUALLY_STAGED_PATHS=\"$(git -C \"${{GIT_ROOT}}\" diff --cached --name-only)\"\n"
                  + commit.replace(tpl, msgfile).replace("<msgfile>", msgfile).replace("${MSGFILE}", msgfile)
                  .replace("<GIT_ROOT>", root).rstrip("\n") + "\n"
                  + reads.rstrip("\n") + "\n" + sync
                  + 'printf \'{"repo_root": "%s", "branch": "%s", "commit_sha": "%s"}\\n\' "$GIT_ROOT" "$BRANCH" "$COMMIT_SHA"\n')
        lab = f"{sub.role} Bash stage and commit {order}"
        devs = [d for d in self.devs.at(lab) if d is not PRIVILEGE_DEVIATION[1]] if self.refuse_commit else None
        c = sub.bash(script, "Phases 3-8: lock, stage, drift check, commit, descriptor", label=lab,
                     deviation=devs)
        desc = _last_json((c.response.get("stdout") or "") if c.ok else "") or {}
        sha = desc.get("commit_sha", "")
        if not c.ok or not sha or sha == head:
            if c.blocked:  # Error handling: a hook refusing the commit is hook_blocked, its output quoted
                b = next((b for b in reversed(self.rp.blocks) if b["step"] == lab and not b["passed_by_deviation"]), {})
                self.hook_block = (b.get("hook", "a hook"), b.get("first") or "")
            result.update(status="failed")
            return result
        result.update(status="committed", commit_sha=sha,
                      commits=[{"commit_sha": sha, "source_key": "PRIMARY", "sources": [tid], "paths": cands}])
        self.landed.append((root, sha))
        rm = re.search(r"clean up:\s*`(rm -f \"\$\{MSGFILE\}\")`", cmdtext.section(self.analyst_text, "Phase 8: Execute commit"))
        if rm:
            sub.bash(f"MSGFILE={shlex.quote(msgfile)}\n{rm.group(1)}", "Clean up the message file",
                     label=f"{sub.role} Bash rm MSGFILE {order}")
        result["push_gate_written"] = self.token(sub, root, desc.get("branch") or repo.get("branch", ""), sha, order)
        return result

    def token(self, sub, root: str, branch: str, sha: str, order: int) -> bool:
        """Phase 10 as the tree spells it: the token writer's call, or the Write-tool token of the descriptor."""
        sec = cmdtext.section(self.analyst_text, "Phase 10: Push-gate write")
        blocks = [b.text for b in cmdtext.blocks(sec, None, "bash") if "write-push-gate-token.py" in b.text]
        if blocks:
            cmd = blocks[0].replace("<GIT_ROOT>", root).replace("<BRANCH>", branch).replace("<COMMIT_SHA>", sha)
            c = sub.bash(cmd, "Phase 10: write the push-gate token", label=f"{sub.role} Bash push-gate token {order}")
            return c.ok
        q = shlex.quote(root)
        d = sub.bash('PUSH_GATE_SID="${CLAUDE_CODE_SESSION_ID:-${CLAUDE_SESSION_ID:-unknown}}"\n'
                     "PUSH_GATE_SID_DIGEST=\"$(printf '%s' \"$PUSH_GATE_SID\" | sha256sum | cut -c1-16)\"\n"
                     f"REPO_HASH=\"$(printf '%s' \"$(realpath {q})\" | sha256sum | cut -c1-16)\"\n"
                     'mkdir -p "/tmp/agentic-commit/push/${REPO_HASH}/${PUSH_GATE_SID_DIGEST}"\n'
                     'printf \'{"session_id": "%s", "token_dir": "/tmp/agentic-commit/push/%s/%s"}\\n\' '
                     '"$PUSH_GATE_SID" "$REPO_HASH" "$PUSH_GATE_SID_DIGEST"',
                     "Phase 10 steps 1-5: the token descriptor", label=f"{sub.role} Bash token descriptor {order}")
        desc = _last_json((d.response.get("stdout") or "") if d.ok else "") or {}
        if not desc.get("token_dir"):
            return False
        path = os.path.join(desc["token_dir"], branch.replace("/", "__") + ".json")
        sub.bash(f"git -C {q} rev-parse HEAD", "Phase 10: pre-write HEAD check", label=f"{sub.role} Bash pre-write HEAD {order}")
        w = sub.write(path, json.dumps({"commit_sha": sha, "branch": branch, "repo_root": root,
                                        "session_id": desc.get("session_id")}) + "\n",
                      label=f"{sub.role} Write push-gate token {order}")
        sub.bash(f"git -C {q} rev-parse HEAD", "Phase 10: post-write HEAD check", label=f"{sub.role} Bash post-write HEAD {order}")
        return w.ok

    # ------------------------------------------------------------ Step 6
    def qa_prompt(self, groups: list) -> str:
        o = self.o
        tpl = next(b.text for b in cmdtext.blocks(o.section("Step 6")) if "<obligation" in b.text)
        tpl = re.sub(r'<"([^"]*)" when BULK=false, else [^>]*>', lambda m: json.dumps(m.group(1).replace("$TASK_ID", self.tid)), tpl)
        prompt = o.instantiate(tpl, self.tid)
        rules = [(r"^PLAN_GROUPS$", json.dumps(groups)), (r"^QA_CODEX$", "false"), (r"^true\|false$", "false"),
                 (r"^TASK_ID or ", self.tid)]
        return o.bind(prompt, rules)

    def commit_qa_act(self, groups: list, verdict: str = "COMMIT: APPROVE", finding: str = "") -> agents.Act:
        def work(sub, brief, player):
            for g in groups:
                for p in g["files"]:
                    sub.bash(f"git -C {shlex.quote(g['repo'])} diff --text HEAD -- {shlex.quote(p)}",
                             f"DIFF of {p}", label=f"{sub.role} Bash diff {p}")
                    full = os.path.join(g["repo"], p)
                    if os.path.isfile(full):
                        sub.read(full, label=f"{sub.role} Read {p}")
            return None
        body = finding or "\n".join(f"- {p}: authored change of this task; no secret, byproduct or scope contamination"
                                    for g in groups for p in g["files"])
        notes = f"Round {self.rounds}, {utc_now()}. Per-file findings:\n{body}\n\ncodex_status: not run (codex_required false)"
        return agents.Act(work=work, notes=notes,
                          terminal={"*commit-qa-report-*": verdict, "response_line": verdict},
                          final_line=verdict, summary="pre-commit QA")

    def commit_qa(self, groups: list, label: str, verdict: str = "COMMIT: APPROVE", finding: str = "", prompt=None):
        o = self.o
        prompt = prompt or self.qa_prompt(groups)
        player = agents.Player(o.tree, prompt, self.commit_qa_act(groups, verdict, finding), role="qa")
        lab = self.label(label)
        return o.s.dispatch("qa", prompt, description="pre-commit QA", body=player.body, result=player.final, label=lab,
                            deviation=self.devs.at(lab))

    def rerun_commit_qa(self, ans: dict, label: str):
        """Routes: a commit-QA finding citing no artifact goes back to that round's own QA dispatch (the reader's
        answer for its report), which runs again and names a path: here the product file the round judged."""
        groups = [{"repo": r, "commit_message": self.subject(), "files": f} for r, f in self.plan_files.items()]
        files = [p for g in groups for p in g["files"]]
        product = closedrv.FINDING["path"] if closedrv.FINDING["path"] in files else next(
            (p for p in files if not p.startswith("docs/")), "")
        now = utc_now()
        prompt = re.sub(r'("dispatched_at"\s*:\s*)"[^"]*"', lambda m: m.group(1) + json.dumps(now), ans["prompt"])
        prompt = prompt.rstrip("\n") + "\n\nRouting finding: your verdict cites no artifact: name the file it concerns.\n"
        verdict = f"COMMIT: REJECT - {product} lacks the docstring its change needs"
        self.commit_qa(groups, f"{label} Agent(qa) names the artifact", verdict,
                       f"- {product}: the change adds behaviour with no docstring", prompt=prompt)
        self.qa_finding = (product, "the change adds behaviour with no docstring")
        return None, "qa"

    def step6(self) -> bool:
        """Planning dispatch, then commit QA rounds until one approves (a REJECT is routed, Step 5 rebuilt)."""
        o = self.o
        for k in range(4):
            self.dispatch_analyst(True, {}, self.label(f"Step 6 Agent(changelog-analyst) planning {k}"))
            groups = [{"repo": r, "commit_message": self.subject(), "files": f} for r, f in self.plan_files.items()]
            if not any(g["files"] for g in groups):
                o.s.say("Nothing to commit (plan computed OK; dry-run found no pending change) — QA gate skipped.")
                return False
            self.rounds += 1
            if self.reject_first and self.rounds == 1:
                self.commit_qa(groups, f"Step 6 Agent(qa) pre-commit review {k}",
                               "COMMIT: REJECT - the change is not ready to land", "- the change is not ready to land")
            else:
                self.commit_qa(groups, f"Step 6 Agent(qa) pre-commit review {k}")
            rel = f"docs/dev/commit-qa-report-{self.tid}.md"
            path = os.path.join(o.project, rel)
            c = o.s.read(path, label=self.label(f"Step 6 Read commit-qa-report {k}"),
                         deviation=self.devs.at(self.label(f"Step 6 Read commit-qa-report {k}")))
            lines = [l for l in (agents.peek(self.rp, "main", path).split("\n") if c.ok else []) if l.strip()]
            last = lines[-1] if lines else ""
            closedrv.fact(self.rp, "commit QA round", {"round": self.rounds, "verdict": last})
            if last.startswith("COMMIT: APPROVE"):
                return True
            if k == 3:
                return False
            o.s.say(last)
            self.revoke(f"Step 6 round {k}")
            # The finding names no file: its own report, whose QA runs again and names the path; then that path.
            self.qa_finding = None
            self.route(rel, last, f"Step 6 round {k + 1}")
            if self.qa_finding:
                path_, why = self.qa_finding
                cur = agents.peek(self.rp, "main", os.path.join(o.project, path_))
                fixed = cur.replace("def add(a, b):\n", "def add(a, b):\n" + closedrv.TOY_DOC, 1)
                self.route(path_, why, f"Step 6 round {k + 1} file", edits=[(path_, cur, fixed)])
            self.reject_first = False
            if not self.step5_plan():
                return False
            self.attribution()
            self.manifest()
            self.mint()
        return False

    # ------------------------------------------------------------ Step 8
    def step8(self) -> None:
        o = self.o
        docs = os.path.join(o.values.get("CONTROL_ROOT") or o.project, "docs/dev")
        ctx = os.path.join(docs, f"context-{self.tid}.json")
        spec = None
        if os.path.isfile(ctx):
            o.s.read(ctx, label=self.label("Step 8 Read context"), deviation=self.devs.at(self.label("Step 8 Read context")))
            spec = json.loads(agents.peek(self.rp, "main", ctx)).get("spec_path")
        if not spec:
            cr = os.path.join(docs, f"close-report-{self.tid}.md")
            o.s.read(cr, label=self.label("Step 8 Read close-report"),
                     deviation=self.devs.at(self.label("Step 8 Read close-report")))
            o.s.tool("Glob", {"pattern": "spec-*.md", "path": os.path.join(o.project, "docs/dev/specs")},
                     label=self.label("Step 8 Glob specs"), deviation=self.devs.at(self.label("Step 8 Glob specs")))
            o.s.say(f"No spec associated with task-id {self.tid}")

    # ------------------------------------------------------------ Step 7
    def hook_question(self) -> None:
        """Step 7's hook-rejection question: the operation and the command to authorize, from the text."""
        sec = self.o.section("Step 7")
        para = next(p for p in re.split(r"\n\s*\n", sec) if "**A hook rejection**" in p)
        header = re.search(r"header `([^`]+)`", para).group(1)
        labels = re.findall(r"options `([^`]+)` \(description: ([^)]*)\) and `([^`]+)` \(description: ([^)]*)\)",
                            re.sub(r"\s+", " ", para))
        hook, text = self.hook_block
        question = f"{hook} refused the analyst's `git commit` for task {self.tid}: authorize it? ({text})"
        opts = ([(labels[0][0], f"/allow git commit for {self.tid}; /commit runs it again once the grant exists"),
                 (labels[0][2], labels[0][3])] if labels else [("Authorize it", ""), ("Do not authorize", "")])
        ans = self.ask(header, question, opts, "Step 7 AskUserQuestion hook block")
        closedrv.fact(self.rp, "owner authorizes", {"answer": ans, "operation": "git commit", "hook": hook})

    def landing(self) -> str:
        """Steps 5-7 once; a hook_blocked failure asks, then Steps 5-7 run again."""
        o = self.o
        for k in range(3):
            if not self.step5_plan():
                return "no repository plan"
            self.attribution()
            self.manifest()
            self.mint()
            if not self.step6():
                return "nothing to commit"
            approved = dict(self.plan_files)
            self.hook_block = None
            self.dispatch_analyst(False, approved, self.label(f"Step 7 Agent(changelog-analyst) {k}"))
            self.refuse_commit = False
            cs = self.status.get("commit_status", "unknown")
            o.s.say(f"changelog-analyst: commit_status={cs}")
            if cs == "failed" and self.status.get("failure_code") == "hook_blocked" and self.hook_block:
                o.s.say(f"ERROR: changelog-analyst failed with failure_code: hook_blocked. "
                        f"Reason: {self.status.get('failure_reason')}.")
                self.hook_question()
                continue
            return cs
        return "failed"

    # ------------------------------------------------------------ one walk, Steps 3-8
    def walk(self) -> str:
        o = self.o
        o.values.update(TASK_ID=self.tid)
        if not self.step3():
            self.outcome = "stalled" if self.stalled else "incomplete after the routing rounds"
            return self.outcome
        cs = self.landing()
        tokens = []
        for root, sha in self.landed:
            with self.rp.acting("driver"):
                found = [os.path.join(dp, f) for dp, _, fs in os.walk(self.rp.layout.state) for f in fs
                         if "agentic-commit/push" in dp] + [os.path.join(dp, f) for dp, _, fs in os.walk("/tmp/agentic-commit/push")
                                                              for f in fs]
                for f in found:
                    try:
                        if json.load(open(f)).get("commit_sha") == sha:
                            tokens.append(f)
                    except (OSError, ValueError):
                        pass
        self.tokens = tokens
        closedrv.fact(self.rp, "commit", {"commit_status": cs, "landed": [(r, s) for r, s in self.landed],
                                          "push_gate_tokens": tokens,
                                          "subject": self.git_log(), "task_id_trailer": self.trailer()})
        if cs == "committed":
            self.step8()
        self.outcome = cs
        return cs

    def git_log(self) -> str:
        import subprocess
        with self.rp.acting("driver"):
            p = subprocess.run(["git", "-C", self.rp.layout.project, "log", "-3", "--format=%s"], capture_output=True,
                               text=True)
        return p.stdout.strip()

    def trailer(self) -> bool:
        """Whether HEAD's message carries the `Task-id: <task>` line."""
        import subprocess
        with self.rp.acting("driver"):
            p = subprocess.run(["git", "-C", self.rp.layout.project, "log", "-1", "--format=%B"], capture_output=True,
                               text=True)
        return f"Task-id: {self.tid}" in p.stdout

    def run(self, typed: str | None = None) -> str:
        self.o.slash(self.tid if typed is None else typed, label=self.label("typed"))
        out = self.walk()
        text = self.stalled or f"/commit {self.tid}: {out}"
        ev = self.o.s.stop(text, label="/commit Stop", deviation=self.devs.at("/commit Stop"))
        self.rp.terminal("commit", out in COMMITTED and self.clean(), ev, task=self.tid, outcome=out)
        return out

    def clean(self) -> bool:
        """The terminal's git half (P1c's suite): each landed commit on its repository's HEAD, a push-gate token
        for it, and none of its paths left in `git status --porcelain`."""
        import subprocess
        def git(root, *args):
            return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True)
        if not self.landed or len(getattr(self, "tokens", [])) < len(self.landed):
            return False
        with self.rp.acting("driver"):
            for root, sha in self.landed:
                if git(root, "merge-base", "--is-ancestor", sha, "HEAD").returncode:
                    return False
                paths = set(git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", sha).stdout.split())
                left = {l[3:].split(" -> ")[-1] for l in git(root, "status", "--porcelain").stdout.splitlines()}
                if paths & left:
                    return False
        return True

    def lifecycle_row(self) -> None:
        """Driver diagnostics, no agent call: the task's lifecycle row when discovery listed no parent."""
        import subprocess
        env = dict(self.rp.bash_env)
        script = os.path.join(env.get("HOME") or os.path.expanduser("~"), ".claude", "scripts", "dev-lifecycle.py")
        with self.rp.acting("driver"):
            p = subprocess.run(["python3", script, "scan", "--format", "json", "--project-dir", self.rp.layout.project],
                               capture_output=True, text=True, env=env, cwd=self.rp.layout.project)
        try:
            rows = [r for r in json.loads(p.stdout) if r.get("task_id") == self.tid]
        except ValueError:
            rows = [{"rc": p.returncode, "stderr": p.stderr[-400:]}]
        closedrv.fact(self.rp, "commit --auto: lifecycle row", [
            {k: r.get(k) for k in ("task_id", "kind", "state", "next_action", "blocker", "commit_evidence", "rc", "stderr")
             if k in r} for r in rows])

    def run_auto(self, typed: str = "--auto") -> list:
        o = self.o
        o.slash(typed, label="/commit --auto typed")
        if typed != "--auto":
            self.flags_question(typed)
        self.run_text(o.block("`--auto` mode", lang="bash", index=0), "/commit --auto Bash discovery",
                      "Discover the commit_pending parents", capture=("COMMIT_PENDING_PARENTS",))
        parents = o.values.get("COMMIT_PENDING_PARENTS") or []
        if isinstance(parents, str):
            parents = [parents] if parents else []
        results = []
        for line in parents:
            self.tid = line.split()[0]
            self.rp.task(self.tid)
            out = self.walk()
            results.append((self.tid, out))
        if not parents:
            self.lifecycle_row()
        o.s.say("\n".join(f"{t}: {r}" for t, r in results) or "no commit_pending parent")
        self.outcome = "; ".join(f"{t}: {r}" for t, r in results)
        ev = o.s.stop(f"/commit --auto: {self.outcome}", label="/commit Stop", deviation=self.devs.at("/commit Stop"))
        self.rp.terminal("commit", bool(results) and all(r in COMMITTED for _, r in results) and self.clean(), ev,
                         outcome=self.outcome)
        return results

    # ------------------------------------------------------------ the waits
    def flags_question(self, typed: str) -> str:
        """Step 1's --auto flag-combination question, its options as the text lists them (one the text
        offers only when its flag was typed, only then)."""
        para = self.o.section("Step 1")
        para = para[para.index("**`--auto` flag combination**"):]
        header = re.search(r"header `([^`]+)`", para).group(1)
        question = re.sub(r"\s+", " ", re.search(r"question `([^`]+)`", para, re.S).group(1))
        opts = [(re.sub(r"<task-id>", self.tid, m.group(1)), re.sub(r"\s+", " ", m.group(3)).strip())
                for m in re.finditer(r"^- `([^`]+)`( \([^)]*\))?: (.*?)(?=^- `|\n\n)", para, re.M | re.S)
                if not m.group(2) or m.group(1) in typed.split()]
        return self.ask(header, question, opts, "Step 1 AskUserQuestion flags")

    def task_question(self) -> str:
        """Step 2's no-unambiguous-candidate question: the text's discovery calls, then the question."""
        o = self.o
        sec = re.sub(r"\s+", " ", o.section("Step 2"))
        call = re.search(r"`(python3 \"\$\{CLAUDE_HOME:-\$HOME/\.claude\}/scripts/dev-lifecycle\.py\" list-actionable "
                         r"--next-action commit --project-dir \"<PROJECT_ROOT>\")`", sec).group(1)
        cands = []
        for action in ("commit", "close"):
            c = self.run_text(call.replace("--next-action commit", f"--next-action {action}"),
                              self.label(f"Step 2 Bash list-actionable {action}"), f"The {action}_pending parents")
            cands += [l.split()[0] for l in (c.response.get("stdout") or "").split("\n") if l.strip()] if c.ok else []
        if not cands:  # "When neither list names a parent, print ... and end."
            self.o.s.say(re.search(r"print `(No task to commit:[^`]*)`", sec).group(1))
            return ""
        header = re.search(r"header `([^`]+)`", sec).group(1)
        question = re.search(r"question `([^`]+)`", sec).group(1)
        opts = [(t, "the task to land") for t in cands[:3]] + [("/commit --auto", "every commit_pending parent")]
        return self.ask(header, question, opts, "Step 2 AskUserQuestion task")


def fanout_dev(rp):
    from . import dev as devdrv
    cyc = devdrv.FanoutCycle(rp, "fanout", rp.args.get("tier", "STANDARD"), 2)
    cyc.run()
    return closedrv.DevProducer(cyc), cyc.tid, cyc.o.s, cyc


VARIANT_NAMES = ("plain", "route", "append", "auto", "commit-route", "full", "unclosed", "laneqa", "aggregate",
                 "reject", "waits", "late-repair", "late-repair-drift", "late-repair-qa")


def run(rp) -> None:
    after = rp.args.get("after", "dev")
    variant = rp.args.get("variant", "plain")
    if variant not in VARIANT_NAMES:
        raise ValueError(f"unknown variant {variant!r}")
    # Acceptance 7 types the /close or /commit of its routing cases in a later session than the /dev.
    session_kind = rp.args.get("session", "same" if variant in ("plain", "reject") else "later")
    rp.pipeline = (closedrv.pipeline_name(after, rp) + "+close+commit" + (f"/{variant}" if variant != "plain" else "")
                   + ("/later" if session_kind == "later" else ""))
    if variant == "laneqa":  # the /dev session interrupted before its QA (Step 13) was ever dispatched
        producer, tid, s, cyc = closedrv.dev_cycle(rp, after, stop_before=13)
    elif variant == "aggregate":
        producer, tid, s, cyc = fanout_dev(rp)
    else:
        producer, tid, s, cyc = closedrv.dev_cycle(rp, after)
    if variant in ("route", "full", "late-repair", "late-repair-drift", "late-repair-qa"):
        removed = {"full": "route", "late-repair-qa": "late-repair"}.get(variant, variant)
        closedrv.remove(rp, [p for p in closedrv.removed_after_cycle(removed, cyc)
                             if os.path.exists(os.path.join(rp.layout.project, p))])
    session = rp.later_session(s) if session_kind == "later" else s
    if variant not in ("unclosed", "laneqa", "waits"):
        close_variant = {"commit-route": "plain", "full": "append", "aggregate": "plain",
                         "reject": "plain", "late-repair-qa": "late-repair"}.get(variant, variant)
        cr = closedrv.CloseRun(rp, session, tid, producer=producer, variant=close_variant, auto=variant == "auto")
        if variant == "auto":
            cr.run_auto()
            CommitRun(rp, session, tid, producer=producer).run_auto()
            return
        cr.run()
    if variant in ("commit-route", "full"):
        # The lane dev report (a fan-out cycle's first lane's; with removed=aggregate its canonical aggregate)
        # removed after /close landed (acceptance 7, F8c): Step 3's call names it.
        closedrv.remove(rp, [f"docs/dev/dev-report-{tid}.json" if rp.args.get("removed") == "aggregate"
                             else closedrv.lane_report(cyc, "dev")])
    if variant == "late-repair-qa":
        # The task's QA report removed after /close --late-repair landed (acceptance 7, F8r).
        closedrv.remove(rp, [f"docs/dev/qa-report-{tid}.json"])
    if variant == "aggregate":
        closedrv.remove(rp, [f"docs/dev/dev-report-{tid}.json"])  # the canonical aggregate
    if (variant in ("commit-route", "full", "aggregate", "waits", "late-repair", "late-repair-drift",
                    "late-repair-qa") and session_kind == "later"):
        session = rp.later_session(session)
    run_ = CommitRun(rp, session, tid, producer=producer, variant=variant)
    if variant == "waits":
        # `/commit` with no task context: the Task question; the stub owner picks the first candidate.
        run_.o.slash("", label=run_.label("typed (no task)"))
        ans = run_.task_question()
        if not ans or ans.startswith("/"):
            raise RuntimeError(f"the Task question offered no task: {ans!r}")
        run_.tid = ans
        out = run_.walk()
        run_.o.s.stop(run_.stalled or f"/commit {run_.tid}: {out}", label="/commit Stop",
                      deviation=run_.devs.at("/commit Stop"))
        # `/commit --auto --force`: the Flags question, then --auto as the answer names it.
        CommitRun(rp, rp.later_session(session), tid, producer=producer).run_auto("--auto --force")
        return
    run_.run()
