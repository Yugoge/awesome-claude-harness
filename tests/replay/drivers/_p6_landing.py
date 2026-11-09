"""P6 A17 (P6-3): subagents a cycle of the base master dispatched, still running when the merge lands.

The session runs on the base tree (tests/replay/landing.py: the sandbox is built from it, the session
loaded its settings.json) and plays the base's command text (drivers/dev.py, drivers/overnight.py), so
the toy project holds what the base's own /dev left there: agent-index.json, the dev-registry sentinels,
the enforcement flags. One subagent of that cycle is dispatched and makes its FIRST ACTION read on the
base's hooks; then the harness home fast-forwards to the tree under test (landing._land) and that
subagent goes on, its next calls and its stop meeting this tree's hooks. With `hooklist=landed` the
session's hook list is this tree's settings.json from the landing on (A17's "Repeat with your
settings.json"); without it the session keeps the base's (D15).

    --arg case=<name> [--arg hooklist=landed]

The leading underscore keeps it out of the artifact check's driver set (tests/artifact_graph/
runtime.py drivers()): some of its subagents meet a block on purpose (A6's probes), and the suite
(tests/replay/test_live_landing_p6.py) runs it, not the check.

  untracked   /dev (the base's text through Step 10's pre-dispatch block); `gen.py` committed by the
              owner before the session. Another session leaves `scratch.txt`; the dev Writes
              `src/new.py`, runs `python3 gen.py > generated.txt` and declares its files as
              the base's agents/dev.md derives them (`git diff --name-only <baseline_head_sha>`; `git
              ls-files --others --exclude-standard` plus staged additions, minus the baseline's dirty
              paths): every untracked file. Its stop meets this tree's G2 (P6 A9/A10's promotion);
              its next round sets the lists to what the refusal names and stops again.
  codex       /dev --codex: every dispatch whose template carries `codex_required: true` keeps the
              line and its subagent calls the codex skill (agents' own text); the dev registered under
              the base stops without calling it (A6: no ledger entry), then calls it and stops again.
  qa          /dev through Step 12, Step 13's QA: its report's e2e_enforcement.status is
              skipped_without_justification (A6); it stops, then Reads the registry's dev.json and
              stops again, then records a justified skip and stops.
  explore     /dev through Step 4 (BA registered and returned); in a second session of the project, a
              plain question: an Explore subagent (Read, then the landing, then Grep, Glob, Bash `ls`)
              and a plugin subagent `demo-plugin:reviewer` (Read, Grep, Bash `ls`, Write `src/y.py`),
              the Stop.
  overnight   /dev-overnight (the base's text, one cycle, in place) through Step 12: the dev child of
              the overnight session registered on the base's hooks, then its work, its stop, and one
              probe Write outside the session's working root (A6: the child resolves the base's
              session state, so the overnight guard holds it to that root).

The changelog-analyst case (a commit grant minted before the pull, spent after it) runs the base's own
/dev -> /close -> /commit drivers, which play the base's /close and /commit text (this tree's play this
tree's): tests/replay/base_driver/_p6_grant.py. facts.json "p6" records the case, its probes' labels
and what the subagent declared or set.
"""
from __future__ import annotations

import json
import os
import re
import subprocess

from .. import agents, hookrun, landing, roles
from ..agents import peek, put
from . import dev as devdrv
from .close import fact

PIPELINE = "p6-landing"
CASES = ("untracked", "codex", "qa", "explore", "overnight")
GEN_PY = "print('generated')\n"
NEW_PY = "def new():\n    return 'new'\n"


def _land(rp, label: str) -> None:
    landing._land(rp, label)


def _loaded(player) -> None:
    """What a running subagent loaded at its start: its agent file and the schemas of its obligation."""
    player.tree.agent_text(player.role)
    for art in (player.b.obligation or {}).get("artifacts") or []:
        if art.get("schema"):
            player.tree.schema(art["schema"])


def landing_work(inner=None):
    """Act.work that lands the harness home first (after the subagent's FIRST ACTION read and its input
    reads, all on the base's hooks), then does `inner`."""
    def work(sub, brief, player):
        _loaded(player)
        _land(sub.rp, f"{sub.role} after its FIRST ACTION")
        return inner(sub, brief, player) if inner else None
    return work


def dispatch(o, fields: dict, act, label: str, task_id: str, subagent_type=None, on_stop_block=None,
             stop_rounds: int = 2):
    """pipeline.Orchestrator.dispatch with the subagent's next rounds after a stop block. The role is the
    explicit subagent_type, else the rendered prompt's obligation block's (never its FIRST ACTION sentinel)."""
    prompt = o.render(fields, task_id)
    atype = subagent_type or fields.get("subagent_type") or o.tree.obligation_role(prompt)
    if not atype:
        raise agents.PlayError(f"{label}: no subagent_type in the template and no role in its obligation block")
    player = agents.Player(o.tree, prompt, act, role=atype)
    d = o.s.main.dispatch(atype, prompt, description=o.bind(fields.get("description", "") or atype),
                          body=player.body, result=player.final, label=label, deviation=o.devs.at(label),
                          on_stop_block=on_stop_block, stop_rounds=stop_rounds)
    d.player = player
    o.dispatches.append(d)
    return d


def _owner(rp, project: str, *args: str) -> None:
    """The owner's own git in the project, before the session (no hook sees it)."""
    with rp.acting("owner"):
        subprocess.run(["git", "-C", project, *args], check=True, capture_output=True,
                       env={k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")})


def _lines(call) -> list:
    return [l.strip() for l in ((call.response or {}).get("stdout") or "").splitlines() if l.strip()] if call.ok else []


def _refusal(ev) -> str:
    return "\n".join(hookrun.refusal(h) for h in ev.blocks)


class Codex(devdrv.DevCycle):
    """/dev --codex on the base's text: the `codex_required: true` line kept, each such dispatch's
    subagent calling the codex skill first (its agent file activates codex on the line)."""

    def __init__(self, rp):
        super().__init__(rp, "plain", "STANDARD")
        self.o.line_rules = [(rx, fn) for rx, fn in self.o.line_rules if "codex_required" not in rx] + [
            (r"^\s*<If codex_required = true, include the literal next line", lambda l: devdrv.DROP)]

    def _dispatch(self, fields, act, label, subagent_type=None):
        if "codex_required: true" in fields.get("prompt", ""):
            act.work = _with_codex(act.work)
        return super()._dispatch(fields, act, label, subagent_type=subagent_type)


def _with_codex(inner):
    def work(sub, brief, player):
        codex(sub)
        return inner(sub, brief, player) if inner else None
    return work


def codex(sub, label: str = ""):
    return sub.tool("Skill", {"skill": "codex", "args": "Review the change against the requirement."},
                    perform=lambda: {"success": True, "commandName": "codex"},
                    label=label or f"{sub.role} Skill(codex)")


def _dev_fields(cyc) -> dict:
    tpl = next(t for t in cyc.templates(10)
               if cyc.o.template_role(t, cyc.tid) == cyc.step_role(10))
    return devdrv.with_lines(tpl, list(cyc.graph_lines))


def _through(cyc, last: int) -> None:
    """The base's /dev from the typed command through Step `last` (Step 10: its pre-dispatch block)."""
    steps = {2: cyc.step2, 3: cyc.step3, 4: cyc.step4, 5: cyc.step5, 6: cyc.step6}
    cyc.start(getattr(cyc, "typed_args", None))
    cyc.step1()
    for n in range(2, min(last, 6) + 1):
        cyc.to(n)
        steps[n]()
    if last < 7:
        return
    cyc.to(7)
    cyc.step7()
    cyc.to(8)
    cyc.to(9)
    cyc.step9()
    cyc.to(10)
    cyc.step10_tw()
    cyc.step10_pre()


def _baseline(cyc) -> dict:
    return {"baseline_head_sha": cyc.o.values.get("baseline_head_sha", ""),
            "baseline_dirty_snapshot": cyc.o.values.get("baseline_dirty_snapshot", "")}


# ---------------------------------------------------------------- the cases

def case_untracked(rp) -> None:
    project = rp.layout.project
    with rp.acting("owner"):
        with open(os.path.join(project, "gen.py"), "w") as fh:
            fh.write(GEN_PY)
    _owner(rp, project, "add", "gen.py")
    _owner(rp, project, "-c", "user.name=owner", "-c", "user.email=owner@example.invalid", "commit", "-qm",
           "add the generator")
    cyc = devdrv.DevCycle(rp, "plain", "STANDARD")
    _through(cyc, 10)
    base = _baseline(cyc)
    dirty = {l[3:].strip() for l in str(base["baseline_dirty_snapshot"]).split("\n") if len(l) > 3}
    seen: dict = {"rounds": 0}

    def work(sub, brief, player):
        seen["report"] = brief.obligation["artifacts"][0]["path"]
        with rp.acting("other-session"):  # another session's file, in the same checkout, before the dev's calls
            with open(os.path.join(project, "scratch.txt"), "w") as fh:
                fh.write("another session's notes\n")
        put(sub, os.path.join(project, "src", "new.py"), NEW_PY, f"{sub.role} Write src/new.py")
        sub.bash("python3 gen.py > generated.txt", "Generate the output file", label=f"{sub.role} Bash gen.py")
        # The base's agents/dev.md "Git-diff derivation (MANDATORY)".
        mod = sub.bash(f"git diff --name-only {base['baseline_head_sha']}", "files_modified: the diff since baseline",
                       label=f"{sub.role} Bash git diff --name-only")
        new = sub.bash("git ls-files --others --exclude-standard", "files_created: untracked files",
                       label=f"{sub.role} Bash git ls-files --others")
        staged = sub.bash("git diff --cached --name-only --diff-filter=A", "files_created: staged additions",
                          label=f"{sub.role} Bash git diff --cached")
        lists = {"files_modified": sorted(set(_lines(mod))),
                 "files_created": sorted((set(_lines(new)) | set(_lines(staged))) - dirty)}
        seen["declared"] = lists
        return {"*": {"dev": lists}}

    def rewrite(sub, ev):
        text = _refusal(ev)
        m = re.search(r"to exactly: files_modified: (.*?); files_created: (.*?)\s*$", text, re.M)
        if seen["rounds"] or not m:
            return None
        seen["rounds"] += 1
        lists = {k: [] if v.strip() == "[]" else [p.strip() for p in v.split(",") if p.strip()]
                 for k, v in (("files_modified", m.group(1)), ("files_created", m.group(2)))}
        seen["rewritten"] = lists
        rel = seen["report"]
        path = os.path.join(project, rel)
        sub.read(path, label=f"{sub.role} Read {rel} (next round)")
        doc = json.loads(peek(rp, sub.role, path))
        doc.setdefault("dev", {}).update(lists)
        put(sub, path, json.dumps(doc, indent=2) + "\n", f"{sub.role} Write {rel} (next round)")
        return sub.last_final

    act = agents.Act(work=landing_work(work), content={"*": base}, summary="src/new.py and generated.txt")
    d = dispatch(cyc.o, _dev_fields(cyc), act, "Step 10 Agent(dev)", cyc.tid, subagent_type=cyc.step_role(10),
                 on_stop_block=rewrite)
    fact(rp, "p6", {"case": "untracked", "dispatch": d.label, "stop": f"{d.label} stop", **seen})
    rp.terminal(PIPELINE, d.ok, d.stop, case="untracked")


def case_codex(rp) -> None:
    cyc = Codex(rp)
    cyc.typed_args = "--codex " + cyc.sc.requirement
    _through(cyc, 10)
    rounds = {"n": 0}

    def again(sub, ev):  # its next round: the codex call the refusal names, then the same final message
        if rounds["n"]:
            return None
        rounds["n"] += 1
        codex(sub, label=f"{sub.role} Skill(codex) (next round)")
        return sub.last_final

    sc = cyc.sc
    work = roles.dev([(sc.rel, sc.old, sc.final)])
    act = agents.Act(work=landing_work(work), content={"*": _baseline(cyc)}, summary=sc.dev_summary)
    fields = _dev_fields(cyc)
    if "codex_required: true" not in cyc.o.render(fields, cyc.tid):
        raise agents.PlayError("the base's Step 10 dev dispatch under --codex carries no codex_required line")
    d = dispatch(cyc.o, fields, act, "Step 10 Agent(dev)", cyc.tid, subagent_type=cyc.step_role(10),
                 on_stop_block=again)
    fact(rp, "p6", {"case": "codex", "dispatch": d.label, "stop": f"{d.label} stop"})
    rp.terminal(PIPELINE, d.ok, d.stop, case="codex")


def case_qa(rp) -> None:
    cyc = devdrv.DevCycle(rp, "plain", "STANDARD")
    _through(cyc, 10)
    cyc.step10_dev()
    cyc.to(11)
    cyc.o.s.say("Step 11 waived: single-dev cycle (N == 1); the dev writes the canonical report itself.")
    cyc.to(12)
    cyc.step12()
    cyc.to(13)
    cyc.step13_blocks()
    cyc.score_header(13, "qa")
    project, sc = rp.layout.project, cyc.sc
    rounds = {"n": 0}

    def again(sub, ev):
        rounds["n"] += 1
        if rounds["n"] == 1:  # A6: the QA reads the dev's sentinel, and is still judged as a QA
            sub.read(os.path.join(project, ".claude", "dev-registry", cyc.reg, "dev.json"),
                     label=f"{sub.role} Read dev.json (next round)")
            return sub.last_final
        if rounds["n"] == 2:  # then the skip it can justify
            rel = rounds["report"]
            path = os.path.join(project, rel)
            sub.read(path, label=f"{sub.role} Read {rel} (last round)")
            doc = json.loads(peek(rp, sub.role, path))
            doc["qa"]["e2e_enforcement"] = {"status": "legitimately_skipped", "blocking_reason": sc.no_e2e}
            put(sub, path, json.dumps(doc, indent=2) + "\n", f"{sub.role} Write {rel} (last round)")
            return sub.last_final
        return None

    qa_work = roles.qa(e2e={"status": "skipped_without_justification"}, guard_respell=cyc.o.respell)

    def work(sub, brief, player):
        rounds["report"] = next(a["path"] for a in brief.obligation["artifacts"] if a.get("kind") == "json")
        return qa_work(sub, brief, player)
    act = agents.Act(verdict="pass", work=landing_work(work), summary="QA pass", respell=cyc.o.respell)
    fields = devdrv.with_lines(cyc.o.template("Step 13"), cyc.graph_lines)
    d = dispatch(cyc.o, fields, act, "Step 13 Agent(qa)", cyc.tid, on_stop_block=again, stop_rounds=3)
    fact(rp, "p6", {"case": "qa", "dispatch": d.label, "stop": f"{d.label} stop", "rounds": rounds["n"]})
    rp.terminal(PIPELINE, d.ok, d.stop, case="qa")


def case_explore(rp) -> None:
    cyc = devdrv.DevCycle(rp, "plain", "STANDARD")
    _through(cyc, 4)  # BA registered under the base and returned; the cycle stays open in that session
    project = rp.layout.project
    s = rp.session()
    s.prompt("Which toy functions exist, and what does a reviewer make of them? Look; change only src/y.py.",
             label="prompt")
    task = ("Problem: a reader needs to know which functions the toy package defines.\n"
            "Acceptance criteria: the answer names each function.\n"
            "DO NOT: modify, create or delete any file; DO NOT run tests, builds or version-control commands.")

    def explore(sub):
        sub.read(f"{project}/toy/__init__.py", label="agent:Explore Read")
        _land(rp, "agent:Explore after its first Read")
        sub.tool("Grep", {"pattern": "def ", "path": f"{project}/toy", "output_mode": "files_with_matches"},
                 label="agent:Explore Grep")
        sub.tool("Glob", {"pattern": "**/*.py", "path": project}, label="agent:Explore Glob")
        sub.bash(f"ls {project}/toy", "List the package", label="agent:Explore Bash ls")

    e = s.dispatch("Explore", task, description="List toy's functions", body=explore,
                   result="toy defines add and sub.", label="main Agent(Explore)")
    review = ("Problem: a reviewer's note on the toy package is wanted.\n"
              "Acceptance criteria: src/y.py holds one comment line naming add and sub.\n"
              "DO NOT: modify or delete any other file; DO NOT run version-control commands.")

    def plugin(sub):
        sub.read(f"{project}/toy/util.py", label="agent:demo-plugin:reviewer Read")
        sub.tool("Grep", {"pattern": "return", "path": f"{project}/toy", "output_mode": "files_with_matches"},
                 label="agent:demo-plugin:reviewer Grep")
        sub.bash(f"ls {project}/toy", "List the package", label="agent:demo-plugin:reviewer Bash ls")
        sub.write(f"{project}/src/y.py", "# reviewed: add and sub\n", label="agent:demo-plugin:reviewer Write src/y.py")

    p = s.dispatch("demo-plugin:reviewer", review, description="Review toy", body=plugin,
                   result="src/y.py holds the note.", label="main Agent(demo-plugin:reviewer)")
    ev = s.stop("toy defines add and sub; the reviewer's note is in src/y.py.", label="Stop")
    fact(rp, "p6", {"case": "explore", "dispatches": [e.label, p.label]})
    rp.terminal(PIPELINE, e.ok and p.ok and not getattr(ev, "still_blocked", False), ev, case="explore")


def case_overnight(rp) -> None:
    from . import overnight
    night = overnight.Night(rp, "plain")
    probe: dict = {}
    plain = night.dispatch

    def child(inner):  # Step 12's dev child: the landing after its FIRST ACTION, its work, then the probe
        def work(sub, brief, player):
            _loaded(player)
            _land(rp, f"{sub.role} after its FIRST ACTION")
            out = inner(sub, brief, player) if inner else None
            probe.update(label=f"{sub.role} Write outside the working root",
                         path=os.path.join(rp.layout.home, "notes", "overnight-probe.md"))
            sub.write(probe["path"], "a note\n", label=probe["label"])
            return out
        return work

    def dispatch_child(fields, act, label, task_id, atype=None, pipe=None):
        if atype == "dev" and "Step 12 Agent(dev)" in label and not probe:
            act.work = child(act.work)
        return plain(fields, act, label, task_id, atype=atype, pipe=pipe)

    night.dispatch = dispatch_child
    night.launch()
    night.step0()
    night.step1()
    night.run_cycle(until=12)
    fact(rp, "p6", {"case": "overnight", "probe": probe, "worktree": night.worktree})
    d = next((x for x in reversed(night.o.dispatches) if x.agent_type == "dev"), None)
    rp.terminal(PIPELINE, bool(d and d.ok), d.stop if d else None, case="overnight")


def run(rp) -> None:
    case = rp.args.get("case", "")
    if case not in CASES:
        raise ValueError(f"case wants one of {CASES}, not {case!r}")
    rp.pipeline = f"{PIPELINE}/{case}"
    globals()[f"case_{case}"](rp)
