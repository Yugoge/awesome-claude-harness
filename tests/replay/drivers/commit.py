"""/commit, played compliantly from commands/commit.md of the tree under test, after /close
(drivers/close.py) of a /dev, /do or /dev-command task, or as `/commit --auto`.

The main agent types `/commit <task-id>` (Steps 1-2 bind TASK_ID: no tool call) and runs, as the
tree's text spells each one, read at run time:

* Step 3: the close-report resolution block; check 2 as the text gives it (the one classifier
  call where the text names it, else a Read of the file whose last line the text checks itself);
  check 3's mtime read; check 4 by derivation (no call). Where the text's resolution block itself
  prints check 2's classifier answer and check 3's mtime, that one call is all of it.
* Step 5: the repository-plan block (late-repair state, the chain call, the plan). The block calls
  `route_finding`, which the text describes ("the loop above made concrete") but never defines:
  the driver prepends a stand-in that records the finding on stderr and ends the shell, so a
  finding stops the block at the path the text's call names (the block exits 3), is routed as the
  text's routing section says (its declaring-dispatch reader, as its own Bash call or a helper
  function, acted on as drivers/close.py does; or its `artifact_role` table, whose `orchestrator`
  row is the main agent's own diagnosis and repair: a report path the text fell back to because the
  dev report is gone is diagnosed as that missing dev report and its producer dispatched again),
  the owner dispatched again under the same task id, and the block re-run (at most three rounds).
  A reader call a hook refuses, or a `null` answer outside a QA round, is the text's defined wait:
  the turn ends with its `AWAITING_INPUT:` line. Then the attribution-log slice block; the dispatch-snapshot
  manifest (the state dir and session id read in Bash, each plan entry's `git status
  --porcelain=v1`, then a Write of the fields the text lists); one grant per plan entry with the
  writer block of the step.
* Step 6: the planning dispatch (changelog-analyst with Step 7's prompt, DRYRUN=true), the
  pre-commit QA dispatch from the step's prompt block, the decision read of the
  commit-qa-report's last line (the base text's file cross-check reads the same file).
* Step 7: changelog-analyst from the step's prompt block, the real commit in the toy project and
  the push-gate token as the tree's agent text writes it; the status block read and handled per
  its commit_status.
* Step 8: the selection algorithm as the text orders it (context spec_path, the close-report's
  continuation line, the specs glob), ending in the outcome the text prints.
* `--auto`: the discovery block and each discovered parent walked through Steps 3-8, the batch
  summary; when discovery lists no parent, the task's lifecycle row (dev-lifecycle.py scan, run by
  the driver, no agent call) is recorded as a fact.

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
  variant=commit-route    /close lands, then the lane dev report is removed and /commit is typed in
                          a later session: Step 5's chain call names the report, its owner is
                          dispatched again, the same call re-run (acceptance 7's fourth case)
  variant=full            route, append and commit-route in one cycle: the lane QA report removed
                          after /dev, /close in a later session (Step 0's routing round, then a
                          close-QA finding on the product file, dev again, the appended round), the
                          lane dev report removed after CLOSE: YES, /commit in a later session
  session=same|later      /close and /commit typed in the cycle's session or a later one
                          (default same for plain, later for every routing variant and auto, as
                          acceptance 7 types them)

Respellings: RESPELLINGS below (base-text paths, row 7). Deviations: DEVIATIONS below.
"""
from __future__ import annotations

import json
import os
import re
import shlex

from .. import agents, cmdtext
from ..pipeline import Deviations, Orchestrator, Respelling, utc_now
from ..replay import Deviation
from . import close as closedrv

PIPELINE = "commit"

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
    # DEVIATION: "BLOCKED: removal-policy — UNRESOLVED dynamic_command_head:dev-report*"
    # pretool-bash-safety.sh refuses the base text's artifact_role table as written (its case patterns).
    ("/commit * Bash artifact_role", Deviation(
        "hooks/pretool-bash-safety.sh", "BLOCKED: removal-policy — UNRESOLVED",
        "the role table as the text defines it")),
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
    ("agent:changelog-analyst Bash stage and commit *", Deviation(
        "hooks/pretool-git-privilege-guard.py", "looks like an unresolved shell variable reference",
        "Phase 8's commit line as the agent text spells it")),
    # DEVIATION: "BLOCKED: removal-policy — UNRESOLVED dynamic_command_head:ARTIFACT_CHAIN="$(python3
    # ~/.claude/scripts/resolve-dev-artifact-chain.py ..."
    # pretool-bash-safety.sh refuses Step 5's block as the text spells it (its `until
    # ARTIFACT_CHAIN="$(...)"; do` chain-recheck loop), in both kits.
    ("/commit Step 5 Bash plan *", Deviation(
        "hooks/pretool-bash-safety.sh", "every execution boundary must be provably inert",
        "Step 5's block as the text spells it")),
])

STAND_IN = ('route_finding() { printf "ROUTE_FINDING\\t%s\\t%s\\t%s\\n" "$1" "$2" "$3" >&2; exit 3; }\n')
STATUS_BEGIN, STATUS_END = "--- CHANGELOG-ANALYST-STATUS-BEGIN ---", "--- CHANGELOG-ANALYST-STATUS-END ---"


def _last_json(text: str):
    for line in reversed((text or "").strip().splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


class CommitRun:
    def __init__(self, rp, session, tid: str, producer=None, extra_devs=()):
        self.rp, self.tid, self.producer = rp, tid, producer
        pairs = (list(DEVIATIONS.pairs) + list(closedrv.DEVIATIONS.pairs) + list(extra_devs)
                 + list(getattr(getattr(producer, "devs", None), "pairs", [])))
        self.devs = closedrv.kept_only(rp, Deviations(pairs))
        rp.deviation_at = self.devs.at  # the subagents' own calls take the same deviations by label
        self.o = Orchestrator(rp, "commit", session=session, deviations=self.devs,
                              respellings=RESPELLINGS + closedrv.RESPELLINGS, rules=self._rules())
        self.analyst_text = self.o.tree.agent_text("changelog-analyst")
        self.plan: dict = {}
        self.chain: dict = {}
        self.awaiting = False
        self.plan_files: dict = {}
        self.landed: list = []
        self.status: dict = {}
        self.outcome = ""
        self.rand = 0

    def _rules(self):
        return [(r"^(?:TASK_ID|task-id|task_id)$", lambda m: self.tid),
                (r"^TASK_ID or \\?\"bulk\\?\"$", lambda m: self.tid)]

    def label(self, text: str) -> str:
        return f"/commit {text}"

    def run_text(self, text: str, label: str, desc: str, capture=(), rules=()):
        o = self.o
        text = o.bind(text, list(rules))
        return closedrv.run_captured(o, o.shell_bind(text), desc, label, capture)

    # ------------------------------------------------------------ Step 3
    def step3(self) -> bool:
        o = self.o
        block = o.block("Step 3", anchor="resolve-close-report.sh")
        c = self.run_text(block, self.label("Step 3 Bash resolve-close-report"), "Resolve the close-report path",
                          capture=("CLOSE_REPORT",))
        report = o.values.get("CLOSE_REPORT", "")
        if "close-verdict.py classify-file" in block:
            # The text's block prints check 2's classifier answer and check 3's mtime in the same call.
            out = [l.strip() for l in ((c.response.get("stdout") or "") if c.ok else (c.error or "")).split("\n")]
            return next((l for l in out if l in ("yes", "no", "unknown")), "") == "yes"
        sec = o.section("Step 3")
        m = re.search(r"`(python3 ~/\.claude/hooks/lib/close-verdict\.py classify-file \"\$CLOSE_REPORT\")`", sec)
        if m:
            c = self.run_text(m.group(1), self.label("Step 3 Bash check 2 classify"), "Check 2: the last line classifies yes")
            ok = c.ok and (c.response.get("stdout") or "").strip() == "yes"
        else:  # the text reads the last non-empty line itself
            c = o.s.read(report, label=self.label("Step 3 Read close-report"),
                         deviation=self.devs.at(self.label("Step 3 Read close-report")))
            lines = [l for l in (agents.peek(self.rp, "main", report).split("\n") if c.ok else []) if l.strip()]
            ok = bool(lines) and lines[-1].startswith("CLOSE: YES")
        self.run_text('stat -c %Y "$CLOSE_REPORT"', self.label("Step 3 Bash check 3 mtime"), "Check 3: close-report age")
        return ok

    # ------------------------------------------------------------ Step 5
    def routing_section(self) -> str:
        """The routing section (the reader, or the role table)."""
        for sec in ("Routing to the owing dispatch", "Artifact-to-role routing"):
            try:
                return self.o.section(sec)
            except cmdtext.TextNotFound:
                continue
        return ""

    def routing_defs(self) -> str:
        """The routing section's function definitions (the reader's caller, or the role table)."""
        sec = self.routing_section()
        try:
            return "\n".join(b.text for b in cmdtext.blocks(sec, None, "bash")
                             if re.search(r"^[A-Za-z_]\w*\(\)\s*\{", b.text, re.M))
        except cmdtext.TextNotFound:
            return ""

    def step5_plan(self, rounds: int = 3) -> bool:
        o = self.o
        block = o.block("Step 5", anchor="LATE_REPAIR_JSON")
        caps = ("CONTROL_ROOT", "NESTED_REPO", "TASK_DOCS_ROOT", "TASK_PROJECT_ROOT", "LATE_REPAIR_JSON",
                "LATE_REPAIR_STATE", "TASK_REPORT", "ARTIFACT_CHAIN", "FANOUT_MODE", "CANONICAL_DEV_REPORT",
                "REPOSITORY_PLAN")
        for k in range(rounds + 1):
            c = self.run_text(STAND_IN + block, self.label(f"Step 5 Bash plan {k}"),
                              "Step 5: late-repair state, artifact chain and repository plan", capture=caps)
            err = (c.error or "") if not c.ok else (c.response.get("stderr") or "")
            found = [l.split("\t") for l in err.split("\n") if l.startswith("ROUTE_FINDING\t")]
            if c.ok and not found:
                break
            if not found or k == rounds:
                return False
            _, path, detail, check = (found[0] + ["", "", ""])[:4]
            if self.route_step5(path, detail, k + 1, check) == "awaiting":
                return False
        try:
            self.plan = json.loads(o.values.get("REPOSITORY_PLAN") or "{}")
            self.chain = json.loads(o.values.get("ARTIFACT_CHAIN") or "{}") if o.values.get("ARTIFACT_CHAIN") else {}
        except ValueError:
            return False
        return bool(self.plan.get("repositories"))

    def route_step5(self, path: str, detail: str, k: int, check: str = "") -> str | None:
        """One routing round for a Step 5 finding on the path the text's route_finding call names: its
        owner, as the routing section says (the reader's answer, or the role table), dispatched again.
        "awaiting" when the text holds instead (the reader names no owner outside a QA round)."""
        o = self.o
        lab = f"Step 5 round {k}"
        defs = self.routing_defs()
        call = closedrv.reader_call(defs, self.routing_section(), path)
        if call:
            cmd, fn = call
            cmd = f"{defs}\n{cmd}" if fn != "declaring-dispatch" else cmd
            c = self.run_text(cmd, self.label(f"{lab} Bash {fn}"), "Who owes the artifact")
            ans = closedrv.last_json(c.response.get("stdout") or "") if c.ok else None
            closedrv.fact(self.rp, "owing dispatch", {"label": lab, "path": path, "blocked": c.blocked,
                                                       "answer": closedrv.summarize_answer(ans)})
            if c.blocked:
                # The cause set's "a hook rejection (pause and report per the Subagent Hook Discipline; the
                # rejected operation is never retried, wrapped or bypassed)": the loop waits.
                hook = next((b["hook"] for b in reversed(self.rp.blocks) if b["step"] == self.label(f"{lab} Bash {fn}")), "a hook")
                line = self.awaiting_line(path, detail, check, need=f"a human ruling on the refused {fn} call",
                                          why=f"{hook} refused the {fn} call (hook rejection)")
                self.awaiting = line
                closedrv.fact(self.rp, "commit awaiting input", {"label": lab, "path": path, "line": line})
                return "awaiting"
            if ans is None and not self.do_task():
                # "`null` otherwise: ... outside a QA round, print the awaiting-input line naming the check"
                line = self.awaiting_line(path, detail, check)
                self.awaiting = line  # the single awaiting-input line ends the turn
                closedrv.fact(self.rp, "commit awaiting input", {"label": lab, "path": path, "line": line})
                return "awaiting"
            closedrv.dispatch_answer(self, ans, path, detail, lab)
            return None
        table = closedrv.role_function(defs)
        c = self.run_text(f"{defs}\n{table} {shlex.quote(path)}", self.label(f"{lab} Bash {table}"),
                          "The producer of the implicated artifact")
        role = (c.response.get("stdout") or "").strip() if c.ok else "orchestrator"
        closedrv.fact(self.rp, "routed role", {"label": lab, "path": path, "role": role})
        if role == "orchestrator":
            closedrv.own_work(self, path, detail, lab)
            return
        if self.producer is None or not role:
            raise RuntimeError(f"Step 5 finding on {path} routes to {role!r}, which this driver cannot play")
        self.producer.dispatch(role, o.s, self.devs, self.label(f"{lab} Agent({role})"), note=f"{path}: {detail}")

    def do_task(self) -> bool:
        return isinstance(self.producer, closedrv.DoProducer)

    def awaiting_line(self, path: str, detail: str, check: str, need: str = "", why: str = "") -> str:
        """The text's awaiting-input line (its `AWAITING_INPUT: need=...; why=...; addressee=...` form), naming
        the check that holds."""
        fmt = re.search(r"`(AWAITING_INPUT: need=<[^`]*)`", self.routing_section())
        line = fmt.group(1) if fmt else "AWAITING_INPUT: need=<what input>; why=<reason>; addressee=<human|orchestrator>"
        rel = os.path.relpath(path, self.rp.layout.project) if os.path.isabs(path) else path
        chk = check.split(" ")[0] if check else "the plan computation"
        return (line.replace("<what input>", need or f"a re-run of /close {self.tid} (no dispatch owes {rel})")
                .replace("<reason>", (why + "; " if why else "") + f"{rel}: {detail}; check: {chk}")
                .replace("<human|orchestrator>", "human"))

    def attribution(self) -> None:
        o = self.o
        self.run_text(o.block("Step 5", anchor="ATTRIBUTION_FILES=()"), self.label("Step 5 Bash attribution slice"),
                      "Attribution-log slice", capture=("ATTRIBUTION_LOG",))

    def manifest(self) -> None:
        o = self.o
        repos = [e["repo_root"] for e in self.plan.get("repositories") or []]
        cmd = (". ~/.claude/hooks/lib/harness_state_dir.sh\nharness_state_dir\n"
               'echo "${CLAUDE_CODE_SESSION_ID:-$CLAUDE_SESSION_ID}"\n'
               + "\n".join(f"echo '--- {r}'; git -C {shlex.quote(r)} status --porcelain=v1" for r in repos))
        c = o.run(cmd, "State dir, session id and status per plan entry", self.label("Step 5 Bash manifest inputs"))
        out = (c.response.get("stdout") or "").split("\n") if c.ok else []
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
        o.s.write(path, json.dumps(doc, indent=2) + "\n", label=self.label("Step 5 Write manifest"),
                  deviation=self.devs.at(self.label("Step 5 Write manifest")))

    def mint(self) -> None:
        o = self.o
        writer = next(b.text for b in cmdtext.blocks(o.section("Step 5"), None, "bash")
                      if "write-commit-grant.py" in b.text and "PLANNED_REPO_ROOT" in b.text)
        for k, e in enumerate(self.plan.get("repositories") or []):
            o.values["PLANNED_REPO_ROOT"] = e["repo_root"]
            self.run_text(writer, self.label(f"Step 5 Bash mint {k}"), "Mint the repository's commit grant")

    # ------------------------------------------------------------ the analyst's prompt
    def analyst_prompt(self, dryrun: bool, approved: dict) -> str:
        o = self.o
        tpl = next(b.text for b in cmdtext.blocks(o.section("Step 7")) if "CONTROL_ROOT=<" in b.text)
        tpl = re.sub(r'<"([^"]*)" when BULK=false, else [^>]*>', lambda m: json.dumps(m.group(1).replace("$TASK_ID", self.tid)), tpl)
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
            if status == "failed":
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
        m = re.search(r"into\s+`([^`]*resolve-dev-report\.py)`", sec)
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
        staged = "\n".join(cands)
        script = (f"GIT_ROOT={q}\n" + lock.rstrip("\n") + "\n"
                  f"git -C \"${{GIT_ROOT}}\" diff --cached --name-only\n"
                  + "\n".join(f'git -C "${{GIT_ROOT}}" add -- {shlex.quote(p)}' for p in cands) + "\n"
                  f"ACTUALLY_STAGED_PATHS=\"$(git -C \"${{GIT_ROOT}}\" diff --cached --name-only)\"\n"
                  + commit.replace(tpl, msgfile).replace("<msgfile>", msgfile).replace("${MSGFILE}", msgfile).rstrip("\n") + "\n"
                  + reads.rstrip("\n") + "\n"
                  + 'printf \'{"repo_root": "%s", "branch": "%s", "commit_sha": "%s"}\\n\' "$GIT_ROOT" "$BRANCH" "$COMMIT_SHA"\n')
        c = sub.bash(script, "Phases 3-8: lock, stage, drift check, commit, descriptor",
                     label=f"{sub.role} Bash stage and commit {order}")
        desc = _last_json((c.response.get("stdout") or "") if c.ok else "") or {}
        sha = desc.get("commit_sha", "")
        if not c.ok or not sha or sha == head:
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

    def commit_qa_act(self, groups: list) -> agents.Act:
        def work(sub, brief, player):
            for g in groups:
                for p in g["files"]:
                    sub.bash(f"git -C {shlex.quote(g['repo'])} diff --text HEAD -- {shlex.quote(p)}",
                             f"DIFF of {p}", label=f"{sub.role} Bash diff {p}")
                    full = os.path.join(g["repo"], p)
                    if os.path.isfile(full):
                        sub.read(full, label=f"{sub.role} Read {p}")
            return None
        body = "\n".join(f"- {p}: authored change of this task; no secret, byproduct or scope contamination"
                         for g in groups for p in g["files"])
        return agents.Act(work=work, notes="Per-file findings:\n" + body + "\n\ncodex_status: not run (codex_required false)",
                          terminal={"*commit-qa-report-*": "COMMIT: APPROVE", "response_line": "COMMIT: APPROVE"},
                          final_line="COMMIT: APPROVE", summary="pre-commit QA")

    def step6(self) -> bool:
        o = self.o
        self.dispatch_analyst(True, {}, self.label("Step 6 Agent(changelog-analyst) planning"))
        groups = [{"repo": r, "commit_message": self.subject(), "files": f} for r, f in self.plan_files.items()]
        if not any(g["files"] for g in groups):
            o.s.say("Nothing to commit (plan computed OK; dry-run found no pending change) — QA gate skipped.")
            return False
        prompt = self.qa_prompt(groups)
        player = agents.Player(o.tree, prompt, self.commit_qa_act(groups), role="qa")
        lab = self.label("Step 6 Agent(qa) pre-commit review")
        o.s.dispatch("qa", prompt, description="pre-commit QA", body=player.body, result=player.final, label=lab,
                     deviation=self.devs.at(lab))
        rel = f"docs/dev/commit-qa-report-{self.tid}.md"
        path = os.path.join(o.project, rel)
        c = o.s.read(path, label=self.label("Step 6 Read commit-qa-report"),
                     deviation=self.devs.at(self.label("Step 6 Read commit-qa-report")))
        lines = [l for l in (agents.peek(self.rp, "main", path).split("\n") if c.ok else []) if l.strip()]
        return bool(lines) and lines[-1].startswith("COMMIT: APPROVE")

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

    # ------------------------------------------------------------ one walk, Steps 3-8
    def walk(self) -> str:
        o = self.o
        o.values.update(TASK_ID=self.tid)
        if not self.step3():
            self.outcome = "close-gate check 2 failed"
            return self.outcome
        if not self.step5_plan():
            self.outcome = "awaiting input" if self.awaiting else "no repository plan"
            return self.outcome
        self.attribution()
        self.manifest()
        self.mint()
        if not self.step6():
            self.outcome = "nothing to commit"
            return self.outcome
        approved = dict(self.plan_files)
        self.dispatch_analyst(False, approved, self.label("Step 7 Agent(changelog-analyst)"))
        cs = self.status.get("commit_status", "unknown")
        o.s.say(f"changelog-analyst: commit_status={cs}")
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
        closedrv.fact(self.rp, "commit", {"commit_status": cs, "landed": [(r, s) for r, s in self.landed],
                                          "push_gate_tokens": tokens,
                                          "subject": self.git_log()})
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

    def run(self) -> str:
        self.o.slash(self.tid, label=self.label("typed"))
        out = self.walk()
        text = self.awaiting if isinstance(self.awaiting, str) else f"/commit {self.tid}: {out}"
        self.o.s.stop(text, label="/commit Stop", deviation=self.devs.at("/commit Stop"))
        return out

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

    def run_auto(self) -> list:
        o = self.o
        o.slash("--auto", label="/commit --auto typed")
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
            results.append((self.tid, "success" if out in ("committed", "nothing_to_commit", "push_gate_reconciled",
                                                           "nothing_to_commit_precommitted") else out))
        if not parents:
            self.lifecycle_row()
        o.s.say("\n".join(f"{t}: {r}" for t, r in results) or "no commit_pending parent")
        self.outcome = "; ".join(f"{t}: {r}" for t, r in results)
        o.s.stop(f"/commit --auto: {self.outcome}", label="/commit Stop", deviation=self.devs.at("/commit Stop"))
        return results


def run(rp) -> None:
    after = rp.args.get("after", "dev")
    variant = rp.args.get("variant", "plain")
    if variant not in ("plain", "route", "append", "auto", "commit-route", "full"):
        raise ValueError(f"unknown variant {variant!r}")
    # Acceptance 7 types the /close or /commit of its routing cases in a later session than the /dev.
    session_kind = rp.args.get("session", "same" if variant == "plain" else "later")
    rp.pipeline = (f"{after}+close+commit" + (f"/{variant}" if variant != "plain" else "")
                   + ("/later" if session_kind == "later" else ""))
    producer, tid, s, cyc = closedrv.dev_cycle(rp, after)
    if variant in ("route", "full"):
        closedrv.remove(rp, [p for p in (f"docs/dev/qa-report-{tid}.json",)
                             if os.path.exists(os.path.join(rp.layout.project, p))])
    session = rp.later_session(s) if session_kind == "later" else s
    close_variant = {"commit-route": "plain", "full": "append"}.get(variant, variant)
    cr = closedrv.CloseRun(rp, session, tid, producer=producer, variant=close_variant, auto=variant == "auto")
    if variant == "auto":
        cr.run_auto()
        CommitRun(rp, session, tid, producer=producer).run_auto()
        return
    cr.run()
    if variant in ("commit-route", "full"):
        # The lane dev report removed after /close landed (acceptance 7): Step 5's chain call names it.
        closedrv.remove(rp, [f"docs/dev/dev-report-{tid}.json"])
        session = rp.later_session(session)
    CommitRun(rp, session, tid, producer=producer).run()
