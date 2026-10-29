"""/do, played compliantly from commands/do.md of the tree under test, then /close of its do-report
(drivers/close.py) and /commit of it (drivers/commit.py).

The main agent types `/do <task>`. The UserPromptSubmit hook mints the task id and prints the
line `[/do] task-id minted: <id> ... → <state dir>/claude-do-task-<sid>.json`; the hook's checklist
(scripts/todo/do.py) goes to the first TodoWrite and one step is completed per TodoWrite call.
Step 1 states the change in one sentence; Step 2 does the work (gate bypass: the main agent
reads and edits toy/__init__.py itself and runs the toy tests); Step 3 is skipped (no --codex);
Step 4 states what changed; Step 5 resolves TASK_ID as the text's numbered list says (SID from
the Bash environment, the session-keyed sidecar the text names: in the state dir the hook
printed on a tree whose text says so, at the text's own path otherwise) and writes the
do-report from the text's JSON template: on a text that says the hook pre-writes a skeleton,
the existing report is Read and rewritten whole (Write) to a terminal state; on a text that says
the agent writes the whole report, it is written (Write). Then Stop, where the do-report gate
runs.

Driver arguments (cli.py --arg K=V):
  then=close-commit   after the /do turn: /close <task-id> (drivers/close.py), then /commit
                      <task-id> (drivers/commit.py), both in the same session (default)
  then=close          /close only
  then=none           the /do turn only
  session=same|later  the session /close and /commit are typed in (default same)

Respellings: no harness-script call of the /do text needs one (row 7). One path is recorded in
blocks.json "respellings" as "do sidecar dir": the base text reads the sidecar at the literal
`/tmp/claude-do-task-$SID.json`, the historical state root; under rule 8 the replay's
CLAUDE_STATE_DIR is another directory and the hook prints where it wrote the sidecar, so the driver
reads it there. /close's and /commit's respellings are listed in those drivers.

Deviations: DEVIATIONS below (none for the /do turn itself on 2acc29b or on the working tree at the
time of writing); /close's and /commit's are in those drivers. `--arg kept=<JSON>` makes every
deviation pass only a kept base block (drivers/dev.py KeptOnly).
"""
from __future__ import annotations

import json
import os
import re

from .. import cmdtext
from ..pipeline import Deviations, Orchestrator

PIPELINE = "do"

TASK = ("make toy.add raise TypeError naming the offending argument when an argument is not a number")
TOY_OLD = "def add(a, b):\n    return a + b\n"
TOY_NEW = ("def add(a, b):\n    for name, x in ((\"a\", a), (\"b\", b)):\n"
           "        if not isinstance(x, (int, float)):\n"
           "            raise TypeError(f\"add(): argument {name} must be a number\")\n    return a + b\n")

DEVIATIONS = Deviations([])


class DoTurn:
    """One /do turn: the main agent works directly and writes the do-report."""

    def __init__(self, rp, session=None, deviations: Deviations | None = None, task: str = TASK,
                 edits=(("toy/__init__.py", TOY_OLD, TOY_NEW),)):
        self.rp, self.task, self.edits = rp, task, list(edits)
        from .close import kept_only
        self.o = Orchestrator(rp, "do", session=session, deviations=kept_only(rp, deviations or DEVIATIONS))
        self.tid = ""
        self.report_rel = ""
        self.files_modified: list = []
        self.files_created: list = []

    def label(self, text: str) -> str:
        return f"/do {text}"

    def call(self, fn, *a, label: str, **k):
        return fn(*a, label=label, deviation=self.o.devs.at(label), **k)

    # ------------------------------------------------------------ steps
    def start(self) -> None:
        o = self.o
        o.slash(self.task, label="/do")
        m = re.search(r"task-id minted:\s*(\S+)", o.hook_out)
        if not m:
            raise cmdtext.TextNotFound("the /do hook output names no minted task id")
        self.tid = m.group(1)
        self.rp.task(self.tid)
        d = re.search(r"→\s*(\S+)/claude-do-task-<sid>\.json", o.hook_out)
        self.printed_dir = d.group(1) if d else ""
        o.todo_start(label=self.label("TodoWrite canonical list"))

    def step1(self) -> None:
        self.o.s.say("Changing toy.add so that a non-number argument raises TypeError naming that argument; "
                     "afterwards add(1, '2') raises TypeError mentioning argument b.")

    def step2(self) -> None:
        o, s = self.o, self.o.s
        for rel, old, new in self.edits:
            path = os.path.join(o.project, rel)
            self.call(s.read, path, label=self.label(f"Step 2 Read {rel}"))
            c = self.call(s.edit, path, old, new, label=self.label(f"Step 2 Edit {rel}"))
            if c.ok:
                self.files_modified.append(rel)
        self.call(s.bash, "python3 -m pytest -q -p no:cacheprovider", "Run the toy tests",
                  label=self.label("Step 2 Bash pytest"))

    def step3(self) -> None:
        self.o.s.say("Step 3 skipped: --codex was not passed.")

    def step4(self) -> None:
        self.o.s.say(f"Changed toy.add: a non-number argument now raises TypeError naming it. "
                     f"Files modified: {', '.join(self.files_modified)}. Codex audit not run.")

    def sidecar_command(self) -> str:
        """Step 5's TASK_ID resolution as the text's numbered list spells it: SID from the
        environment, then the sidecar the text names (in the state dir where the text says so)."""
        sec = self.o.section("Step 5")
        codes = re.findall(r"`([^`\n]+)`", sec)
        # "1. `SID = $X` (fallback `$Y`)": the variables in the order the item names them.
        sid_vars = [v for c in cmdtext.inline_codes(self.o.text, "Step 5", "SID = ") for v in re.findall(r"\$([A-Z_]+)", c)]
        sidecar = next(c for c in codes if "claude-do-task-$SID.json" in c)
        sid = "SID=\"${%s}\"" % ":-$".join(sid_vars)
        if sidecar.startswith("/"):
            # The text's literal /tmp is the historical state root; under rule 8 the replay's
            # CLAUDE_STATE_DIR is another directory, and the hook printed where it wrote the sidecar.
            where = os.path.dirname(sidecar)
            if self.printed_dir and where != self.printed_dir:
                self.rp.respellings.append({"step": self.label("Step 5 Bash sidecar"), "name": "do sidecar dir",
                                            "where": "commands/do.md Step 5 (the hook's printed state dir)",
                                            "count": 1})
                sidecar = os.path.join(self.printed_dir, os.path.basename(sidecar))
            return f'{sid}\ncat "{sidecar}"'
        state = next((c for c in codes if "harness_state_dir" in c and c.startswith(".")), None)
        if state is None:
            raise cmdtext.TextNotFound("Step 5 names the sidecar by name but no state-dir resolution")
        return f'{sid}\n{state.split(";")[0].strip()}\ncat "$(harness_state_dir)/{sidecar}"'

    def step5(self) -> None:
        o, s = self.o, self.o.s
        c = self.call(s.bash, self.sidecar_command(), "Read the session-keyed do sidecar",
                      label=self.label("Step 5 Bash sidecar"))
        try:
            got = json.loads(c.response.get("stdout", "")).get("task_id") if c.ok else None
        except ValueError:
            got = None
        if got and got != self.tid:
            raise RuntimeError(f"the sidecar names task id {got}, the hook printed {self.tid}")
        sec = o.section("Step 5")
        paths = [p for p in re.findall(r"`(docs/dev/do-report-<TASK_ID>\.json)`", sec)]
        self.report_rel = (paths[0] if paths else "docs/dev/do-report-<TASK_ID>.json").replace("<TASK_ID>", self.tid)
        doc = json.loads(o.block("Step 5", lang="json"))
        for k, v in list(doc.items()):
            if v == "<TASK_ID>":
                doc[k] = self.tid
        doc["request"] = self.task
        doc["do"].update(status="completed", files_modified=list(self.files_modified),
                         files_created=list(self.files_created),
                         summary="toy.add now raises TypeError naming the argument that is not a number.")
        text = json.dumps(doc, indent=2) + "\n"
        path = os.path.join(o.project, self.report_rel)
        # A text that has the hook pre-write a skeleton tells the agent to rewrite it; else the agent
        # writes the whole report.
        if "skeleton" in sec and os.path.exists(path):
            self.call(s.read, path, label=self.label("Step 5 Read do-report skeleton"))
        self.call(s.write, path, text, label=self.label("Step 5 Write do-report"))

    def run(self) -> str:
        o = self.o
        self.start()
        self.step1()
        for n, fn in ((2, self.step2), (3, self.step3), (4, self.step4), (5, self.step5)):
            o.advance(label=self.label(f"TodoWrite Step {n - 1} done, Step {n} in_progress"))
            fn()
        o.advance(label=self.label("TodoWrite Step 5 done"))
        o.s.stop(f"/do {self.tid} done: toy.add rejects non-numbers; do-report {self.report_rel}. "
                 f"Next: /close {self.tid}", label="/do Stop", deviation=o.devs.at("/do Stop"))
        return self.tid


def run(rp) -> None:
    then = rp.args.get("then", "close-commit")
    rp.pipeline = "do" if then == "none" else f"do+{then}"
    turn = DoTurn(rp)
    tid = turn.run()
    if then == "none":
        return
    from . import close as close_drv
    session = rp.later_session(turn.o.s) if rp.args.get("session") == "later" else turn.o.s
    cr = close_drv.CloseRun(rp, session, tid, do_report=turn.report_rel, producer=close_drv.DoProducer(turn))
    cr.run()
    if then == "close":
        return
    from . import commit as commit_drv
    commit_drv.CommitRun(rp, session, tid, producer=cr.producer).run()
