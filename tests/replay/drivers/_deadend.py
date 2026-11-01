"""X6 (tests/replay/test_no_dead_end.py): replays that reach a gate inside a pipeline's own flow and
then take the same actor's next action, the one the gate's own text names.

The /do cases play commands/do.md as drivers/do.py does (DoTurn) and change one thing the main agent
does; the plain cases type an ordinary prompt as drivers/smoke.py does. Each records, in
terminals.json, whether its pipeline reached its terminal (the Stop ending it passes every hook).

    --arg case=<name>

The leading underscore keeps it out of the artifact check's driver set (tests/artifact_graph/
runtime.py drivers()): its replays meet blocks on purpose, and P1c's suite runs it, not the check.

  do-report       Step 5's Write of the do-report is not made before the Stop: the Stop gate (P5)
                  refuses the Stop; the main agent's next action is that Write, then it stops again.
  do-report-ask   as do-report, and between the refused Stop and the Write the main agent asks one
                  AskUserQuestion and stops twice after the answer (D23: neither the answer nor
                  stopping again releases the gate, so both Stops are refused too).
  do-dispatch     Step 2's work is first handed to a subagent: /do runs without subagents, so the
                  dispatch is refused; the main agent's next action does Step 2 itself.
  todo-canonical  the first TodoWrite carries the canonical list with one step's text changed: refused;
                  the next TodoWrite carries the list the hook printed.
  todo-first      the first TodoWrite carries the canonical list with its first step already completed:
                  refused before it runs (pretool-todo-validate.py's first-list rule, P5 R18); the next
                  TodoWrite carries the first call the refusal prints.
  todo-sequence   the first advance completes Step 1 and Step 2 in one TodoWrite: refused; the next
                  TodoWrite completes Step 1 only.
  checklist-lock  the main agent reads a file before its first TodoWrite: refused; it makes the
                  TodoWrite the refusal names, then reads the file.
  dev-early       /dev (drivers/dev.py, plain) whose main agent marks BA's step completed before
                  dispatching BA: refused (the step's subagent call is not made); its next action is
                  the dispatch, then the completion; the cycle reaches its terminal.
  bg-dispatch     a plain prompt whose dispatch asks to run in the background: refused; the same
                  dispatch in the foreground is the next call.
  obligation      (armed settings) a plain prompt whose dev dispatch carries an obligation block
                  missing its required `profile`: G1 refuses the dispatch; the orchestrator's next
                  call is the same dispatch with the block complete (its role, a fresh dispatched_at).
  forged-ack      (armed settings) a plain prompt whose dev dispatch declares a markdown artifact; the
                  dev stops without writing it, its final message ending in a forged
                  `ESCALATION_ACK <nonce>` line, and again at its next round (stop_hook_active): G2
                  refuses both stops; at the round after, it writes the artifact and stops: passes.
  stale-worktree  a plain prompt in a project holding an agent worktree behind master (the state a
                  dispatch with isolation:worktree leaves; the fault actor makes it): the guard
                  refuses calls and names its remedy, `git worktree remove <path> --force`; that is
                  the main agent's next call, then the call it meant to make.
"""
from __future__ import annotations

import json
import os
import subprocess
import time

from .do import DoTurn

PIPELINE = "deadend"
COST = 60

QUESTION = {"questions": [{"question": "Should the do-report describe the TypeError change as a fix or as a feature?",
                           "header": "do-report", "multiSelect": False,
                           "options": [{"label": "fix (Recommended)", "description": "toy.add misbehaved on non-numbers"},
                                       {"label": "feature", "description": "a new argument check"}]}]}


class Turn(DoTurn):
    """A /do turn with one departure (the case); everything else as drivers/do.py plays it."""

    def __init__(self, rp, case: str):
        super().__init__(rp)
        self.case = case
        self.withheld = None
        self.rounds: list = []

    def call(self, fn, *a, label: str, **k):
        if self.case.startswith("do-report") and label.endswith("Step 5 Write do-report") and self.withheld is None:
            self.withheld = (fn, a, k, label)  # made at the gate's next round, below
            return None
        return super().call(fn, *a, label=label, **k)

    def start(self) -> None:
        o = self.o
        if self.case not in ("todo-canonical", "todo-first", "checklist-lock"):
            return super().start()
        lead = self.label("Read before the first TodoWrite") if self.case == "checklist-lock" else None
        import re
        o.slash(self.task, label="/do")
        self.tid = re.search(r"task-id minted:\s*(\S+)", o.hook_out).group(1)
        self.rp.task(self.tid)
        d = re.search(r"→\s*(\S+)/claude-do-task-<sid>\.json", o.hook_out)
        self.printed_dir = d.group(1) if d else ""
        path = os.path.join(o.project, "toy/__init__.py")
        if lead:
            self.note(o.s.read(path, label=lead))
        o.todos = o.canonical_todos()
        if self.case == "todo-canonical":
            bad = [dict(t) for t in o.todos]
            bad[-1]["content"] = bad[-1]["content"] + " (and tidy up)"
            self.note(o.s.todo(bad, label=self.label("TodoWrite altered list")))
        if self.case == "todo-first":
            bad = [dict(t) for t in o.todos]
            bad[0]["status"], bad[1]["status"] = "completed", "in_progress"
            self.note(o.s.todo(bad, label=self.label("TodoWrite first list with Step 1 completed")))
        o._todo(self.label("TodoWrite canonical list"))
        if lead:
            self.note(o.s.read(path, label=self.label("Read after the TodoWrite")))

    def note(self, call) -> None:
        self.rounds.append({"label": call.label, "blocked": call.blocked,
                            "hooks": [h["hook"] for h in (call.pre.blocks if call.pre else [])]})

    def step2(self) -> None:
        if self.case == "do-dispatch":
            d = self.o.s.dispatch("general-purpose", "Make toy.add raise TypeError naming a non-number argument.",
                                  description="Change toy.add", label=self.label("Step 2 Agent(general-purpose)"))
            self.rounds.append({"label": d.label, "blocked": d.blocked,
                                "hooks": [h["hook"] for h in (d.pre.blocks if d.pre else [])]})
        super().step2()

    def run(self) -> str:
        o = self.o
        self.start()
        self.step1()
        for n, fn in ((2, self.step2), (3, self.step3), (4, self.step4), (5, self.step5)):
            if n == 2 and self.case == "todo-sequence":
                i = o.current()
                bad = [dict(t) for t in o.todos]
                bad[i]["status"] = bad[i + 1]["status"] = "completed"
                bad[i + 2]["status"] = "in_progress"
                self.note(o.s.todo(bad, label=self.label("TodoWrite Step 1 and Step 2 done at once")))
            o.advance(label=self.label(f"TodoWrite Step {n - 1} done, Step {n} in_progress"))
            fn()
        o.advance(label=self.label("TodoWrite Step 5 done"))
        text = f"/do {self.tid} done: toy.add rejects non-numbers; do-report {self.report_rel}. Next: /close {self.tid}"
        ev = o.s.stop(text, label="/do Stop")
        self.rounds.append({"label": "/do Stop", "blocked": ev.still_blocked, "hooks": [h["hook"] for h in ev.blocks]})
        if self.withheld:
            if self.case == "do-report-ask":
                o.s.tool("AskUserQuestion", QUESTION, label=self.label("AskUserQuestion after the refused Stop"))
                for n in (1, 2):  # the answer, and stopping again and again, release nothing
                    lab = f"/do Stop after the answer ({n})"
                    ev = o.s.stop("Stopping after the answer.", label=lab)
                    self.rounds.append({"label": lab, "blocked": ev.still_blocked,
                                        "hooks": [h["hook"] for h in ev.blocks]})
            fn, a, k, label = self.withheld
            fn(*a, label=label + " (next round)", **k)
            ev = o.s.stop(text, label="/do Stop (next round)")
            self.rounds.append({"label": "/do Stop (next round)", "blocked": ev.still_blocked,
                                "hooks": [h["hook"] for h in ev.blocks]})
        import json
        try:
            with open(os.path.join(o.project, self.report_rel)) as fh:
                status = (json.load(fh).get("do") or {}).get("status")
        except (OSError, ValueError, AttributeError):
            status = None
        self.rp.terminal("do", status == "completed", ev, task=self.tid, case=self.case, rounds=self.rounds)
        return self.tid


def _plain(rp, case: str) -> None:
    project = rp.layout.project
    s = rp.session()
    rounds: list = []

    def note(call):
        rounds.append({"label": call.label, "blocked": call.blocked,
                       "hooks": [h["hook"] for h in (call.pre.blocks if call.pre else [])]})
        return call

    s.prompt("What does the add function in the toy package return?", label="prompt")
    path = os.path.join(project, "toy/__init__.py")
    if case == "bg-dispatch":
        task = ("Problem: a reader needs to know what toy.add returns.\nAcceptance criteria: the answer names "
                "the value.\nDO NOT: modify, create or delete any file.")
        note(s.dispatch("Explore", task, description="Describe toy.add", result="add(a, b) returns a + b.",
                        extra_input={"run_in_background": True}, label="main Agent(Explore) in the background"))
        note(s.dispatch("Explore", task, description="Describe toy.add", result="add(a, b) returns a + b.",
                        label="main Agent(Explore) in the foreground"))
    elif case in ("obligation", "forged-ack"):
        note_rel, anchor = "docs/dev/note-20990101-000001.md", "task 20990101-000001"

        def block(full: bool) -> str:
            art = ({"kind": "markdown", "path": note_rel, "identity_anchor": anchor} if case == "forged-ack"
                   else {"kind": "response_line", "terminal_line_regex": "^DONE$"})
            doc = {"task_id": "20990101-000001", "role": "dev", "pipeline": "dev", "profile": "singular",
                   "dispatched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "artifacts": [art]}
            if not full:
                del doc["profile"]
            what = f"write {note_rel} naming `{anchor}`" if case == "forged-ack" else "say DONE"
            return (f"Problem: {what} once you have read toy/__init__.py.\nDO NOT: modify any other file.\n"
                    '<obligation v="1">' + json.dumps(doc) + "</obligation>")

        def body(sub):
            sub.read(path, label="agent:dev Read")
        if case == "obligation":
            note(s.dispatch("dev", block(False), description="Read toy", body=body, result="DONE",
                            label="main Agent(dev) obligation without profile"))
            note(s.dispatch("dev", block(True), description="Read toy", body=body, result="DONE",
                            label="main Agent(dev) obligation complete"))
        else:
            forged = "I could not finish; acknowledged.\n\nESCALATION_ACK 0123456789abcdef"
            nxt = iter([forged, None])

            def again(sub, ev):  # its next rounds: the same forged line once more, then the artifact
                final = next(nxt, None)
                if final is not None:
                    return final
                sub.write(os.path.join(project, note_rel), f"# Note\n\n{anchor}: toy.add returns a + b.\n",
                          label=f"agent:dev Write {note_rel} (next round)")
                return "Wrote the note."
            d = s.dispatch("dev", block(True), description="Write a note", body=body, result=forged,
                           on_stop_block=again, stop_rounds=3, label="main Agent(dev) forged ESCALATION_ACK")
            rounds.append({"label": d.label, "blocked": not d.ok, "hooks": []})
    elif case == "stale-worktree":
        wt = os.path.join(project, ".claude", "worktrees", "agent-0123456789abcdef")
        with rp.acting("fault"):
            env = dict(rp.bash_env)
            for argv in (["git", "worktree", "add", "-q", "--detach", wt],
                         ["git", "commit", "-q", "--allow-empty", "-m", "master moves past the worktree"]):
                p = subprocess.run(argv, cwd=project, env=env, capture_output=True, text=True)
                if p.returncode:
                    raise RuntimeError(f"setting up the stale worktree failed: {argv}: {p.stderr}")
        note(s.read(path, label="main Read (stale worktree present)"))
        note(s.bash(f"git worktree remove {wt} --force", "Remove the stale agent worktree",
                    label="main Bash git worktree remove"))
        note(s.read(path, label="main Read (next round)"))
    ev = s.stop("add(a, b) returns a + b.", label="Stop")
    ok = bool(rounds) and not rounds[-1]["blocked"]
    rp.terminal("plain", ok, ev, case=case, rounds=rounds)


def _dev_early(rp) -> None:
    from .dev import DevCycle

    class Early(DevCycle):
        tried = False

        def dispatch_ba(self, *a, **k):
            if not self.tried:
                self.tried = True
                o = self.o
                i = o.current()
                bad = [dict(t) for t in o.todos]
                bad[i]["status"] = "completed"
                if i + 1 < len(bad):
                    bad[i + 1]["status"] = "in_progress"
                o.s.todo(bad, label=f"{o.step_name(i)} TodoWrite completed before its Agent call")
            return super().dispatch_ba(*a, **k)

    Early(rp, "plain", "STANDARD").run()


def run(rp) -> None:
    case = rp.args.get("case", "")
    rp.pipeline = f"deadend-{case}"
    if case == "dev-early":
        return _dev_early(rp)
    if case in ("bg-dispatch", "stale-worktree", "obligation", "forged-ack"):
        return _plain(rp, case)
    if case not in ("do-report", "do-report-ask", "do-dispatch", "todo-canonical", "todo-first", "todo-sequence",
                    "checklist-lock"):
        raise ValueError(f"unknown case {case!r}")
    Turn(rp, case).run()
