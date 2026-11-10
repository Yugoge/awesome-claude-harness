"""/close, played compliantly from commands/close.md of the tree under test, after /dev
(drivers/dev.py), after /do (drivers/do.py) or after /dev-command (drivers/dev_command.py, when
that driver exists).

The main agent types `/close <task-id>` (or `/close --auto`), passes the checklist the hook hands
it (scripts/todo/close.py: Step 0 to Step 4) to its first TodoWrite and completes one step per
TodoWrite call. What each step does is read from the tree's own text at run time:

* Task-id resolution: the timestamp argument binds TASK_ID; on the /do path the do-report is
  found (Glob) and DO_REPORT bound.
* Step 0: the step's one Bash block (the disposition call), its output read as the text says: the
  DISPOSITION line, each GAP line, the CHAIN line (ARTIFACT_CHAIN, the data Steps 1-3 use). Each gap
  is routed (Routes) and the call run again until it prints chain_pass; a non-zero exit is run once
  more, then one `OPERATION_STALLED:` line ends the run. The optional cp-state handoff (a Glob for
  .claude/specs/<TASK_ID>/cp-state-qa.json).
* Routes: the declaring-dispatch reader (the section's Bash block, the path for `<path>`) and its
  answer acted on as the text lists: a `dispatch`, `lane` or `writer` answer runs that dispatch again
  (its recorded prompt, a fresh dispatched_at); a `todo_step` with a subagent call is a fresh dispatch
  of its role from the cycle command's template; one with none is the main agent's own step
  (own_work); the /do bullet dispatches dev with the obligation it spells; a null answer for a
  close-QA finding, and an answer that is close QA itself, run the round's own QA dispatch again,
  which names the artifact, routed in turn.
* Step 1: the cycle-diff file list (the canonical report's dev.files_modified, Read; or the
  do-report's do.files_modified), the registry name (the step's Bash block), and the three
  inspectors, each prompt built from its bullet (FIRST ACTION line, obligation, `--changed-files`,
  report path); each inspector played from its agent file (agents.Player).
* Step 2: one close-QA dispatch per judging round from the step's prompt block (placeholders bound,
  the SECOND ACTION line left out with SPEC_ID empty, the Input artifacts bullets filled from the
  chain or the do-report). QA writes the close-report: a first report with the Player, a later
  round's section appended through the append helper the Overwrite policy names. A round-open
  return is echoed and routed (Routes), Step 0's call runs again, then a fresh round.
* Step 3: the verdict echo, the Session Summary and the next step. Step 4: the step's
  AskUserQuestion (its JSON block, the task id bound), answered as the `rating` argument says; the
  orchestrator does nothing with the answer. Stop.
* `--auto`: the discovery block, then each step walked over every parent before it is completed;
  the batch line; one rating question per landed parent. `--auto <task>` first asks the Close mode
  question (the dialog picks `/close --auto`).

Driver arguments (cli.py --arg K=V), when run on its own (`--driver close`):
  after=dev|dev-command   the cycle closed (default dev; /do is drivers/do.py)
  variant=plain           close QA lands CLOSE: YES in its first round (default; acceptance 4 (a))
  variant=route           the qa-report is removed after the cycle's terminal; Step 0 names it, its
                          declaring QA dispatch runs again (4 (b))
  variant=lane-qa         the /dev session is interrupted before Step 13 (QA never dispatched); the
                          reader returns its todo step, a fresh QA dispatch from its template (4 (c))
  variant=append          close QA's first round names the product file the dev wrote; that dev runs
                          again; Step 0 again; the fresh round appends and lands (4 (h))
  variant=stray           close QA's first round names a product file no dispatch of the task wrote;
                          its own QA runs again and names the dev report; that dev runs again (4 (i))
  variant=noart           close QA's first finding cites no artifact; its own QA runs again and names
                          the dev's file; that dev runs again (4 (j))
  variant=stalled         the sandbox copy's resolver is unimportable: one retry, one
                          OPERATION_STALLED: line, no question, no verdict (4 (k))
  variant=auto            `/close --auto` (the cycle's task discovered as close_pending; parents=2 runs a
                          second /dev first: acceptance 9)
  variant=auto-task       `/close --auto <task>`: the Close mode question first (acceptance 5)
  variant=late-repair     BA's stage (ticket, context, acceptance criteria) is removed after the cycle's
                          terminal and `/close --late-repair <task-id>` is typed: the R4 section's
                          controller calls as it spells them (init; BA, dev and QA from the cycle's
                          templates, record-stage after each; finalize; verify-disclosure), then what its
                          `admitted` item says, Steps 1-4 (acceptance 14's route)
  variant=late-repair-drift   late-repair, its dev making the documentation change and reporting the ledger's
                          final_source_hashes, then a peer's line landing on that file before finalize:
                          the reconcilable drift (tests/test_late_repair_route.py's shape) for which
                          finalize writes the effective report
  variant=late-repair-declined   the qa-report is removed after the cycle's terminal and
                          `/close --late-repair <task-id>` is typed: init declines (a QA-only gap), the
                          reason is recorded and Step 0's disposition call runs (the ordinary route)
  variant=break           the product file the cycle's last lane's dev wrote is put back to an incomplete
                          fix after the cycle's terminal; close QA's first round names it, its writer runs
                          again and restores its fix, a fresh round lands (F8p)
  variant=auto-skip       `/close --auto` over the cycle and an old task docs/dev holds (a completed dev-report,
                          no ticket, context or QA report, no dispatch record in the store): the discovery
                          passes the old task over, its `skipped:` line on stderr and in the batch line, and
                          the cycle lands (review finding 2)
  variant=noba            route's /close, then the /dev session gone from the store and BA's ticket removed,
                          and /close typed again: the reader names no owner for the ticket (never /close's own
                          rating step), Routes asks the owner (header Request), the turn ends there (finding 1)
  variant=codex-flip-items   `/close --codex`: a stub Codex answers one blocker and five style and edge items; QA's
                          Codex review follows the text's CODEX REVIEW rules (drivers/_codex.py reads each from the
                          sentence that states it): the producer is dispatched again once, round 2 is a re-review of
                          the blocker, the close lands with the rest on the follow-up list (D31 replay 1)
  variant=codex-endless   `/close --codex`: the stub reports a new item at every call; the text's round cap, not
                          Codex, ends it: the close lands after round 3 (D31 replay 2)
  parents=1|2             --auto: the number of /dev cycles closed
  cycle_variant=V         the /dev variant closed (drivers/dev.py; fanout and fanout-qa-fail run the
                          fan-out cycle with `lanes` lanes)
  rating=label|4|skip|afk|decline|free[,...]   Step 4's answer, per landed task in order (default label:
                          the dialog's first option)
  session=same|later      /close typed in the /dev's session or a later one (default same for plain,
                          later otherwise)

P1b's acceptance 7 names three of these cases otherwise; each name plays its case (ALIASES): qa-never
is lane-qa, noartifact is noart, unwritten is stray.

Deviations: DEVIATIONS below, one entry per block the replays meet, each with a comment quoting
the hook's text; nothing else passes a block.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shlex

from .. import agents, cmdtext, roles, schemagen
from ..pipeline import Deviations, Orchestrator, Respelling, parse_declare, utc_now
from ..replay import Deviation
from . import _codex

PIPELINE = "close"
# The artifact check's cost of each variant (tests/artifact_graph/shards.py balances its CI shards by it):
# CPU seconds of the shipped and armed traced replays and their differential runs, measured at b8e34f4
COST = {"plain": 448, "route": 485, "append": 530, "auto": 462}

# Respellings (P1b Scope row 7) of base-text forms; the tree's text spells every harness call through
# the CLAUDE_HOME channel, so none applies to it. Kept for drivers that compose this one.
RESPELLINGS = [
    Respelling("C3 append helper", r'python3 "\$PROJECT_ROOT/scripts/close-report-append\.py"',
               "python3 ~/.claude/scripts/close-report-append.py", "commands/close.md Step 2 (:776 at 2acc29b)"),
]

# Blocks the replays meet, each passed at the step it occurs on by a deviation whose comment quotes
# the hook's text; the refused call is applied as if allowed, so every later step runs and is traced.
DEVIATIONS = Deviations([
    # DEVIATION: "[Orchestrator Gate] BLOCKED: Bash used consecutively beyond limit (6/5)."
    # A run of Bash blocks between two dispatches outnumbering the gate's cap of 5 (drivers composing this
    # one meet it; /close's own text keeps its Bash calls apart).
    ("*Bash*", Deviation("hooks/pretool-orchestrator-gate.py", "Bash used consecutively beyond limit",
                         "a run of Bash blocks between dispatches")),
    # DEVIATION: "E2E_ENFORCE_BLOCKED: agent <agent> (type=qa) has no qa-report-*.json in <project>/docs/dev/
    # under session dev-<ts>." subagentstop-e2e-enforce.py refuses close QA's stop on a /do task where the
    # e2e flag's session holds no qa-report.
    ("/close Step 2 Agent(qa) close round *", Deviation(
        "hooks/subagentstop-e2e-enforce.py", "E2E_ENFORCE_BLOCKED",
        "close QA of a /do task writes the close-report its obligation declares, no qa-report")),
])

CLOSE_YES_PLAIN = "CLOSE: YES — codex disabled by user"
# The Codex review variants (D31's replays): QA runs the `--codex` path against a stub Codex (drivers/_codex.py).
# They are not in VARIANTS, so the artifact check's shards do not replay them; tests/replay/test_codex_loop.py does.
CODEX_SCRIPTS = {"codex-flip-items": _codex.FLIP_ITEMS, "codex-endless": _codex.ENDLESS}
CODEX_VARIANTS = tuple(CODEX_SCRIPTS)
FINDING = {"path": "toy/__init__.py", "detail": "add() states no contract: its docstring does not say it raises "
                                                "TypeError naming a non-number argument (AC-01's behaviour is undocumented)"}
PEER_LINE = "\n\nPEER = 1  # another task's line\n"
TOY_DOC = ('    """Return a + b; raise TypeError naming the argument that is not a number."""\n')


def fact(rp, key: str, value) -> None:
    """A fact of the replay the report quotes (verdicts, chain status, routing, commits), kept in
    out/facts.json beside blocks.json."""
    path = os.path.join(rp.layout.out, "facts.json")
    with rp.acting("driver"):
        try:
            with open(path) as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            doc = []
        doc.append({"key": key, "value": value})
        with open(path, "w") as fh:
            json.dump(doc, fh, indent=1)


def resolved_role(rp, agent_id: str):
    """hooks/lib/agent_resolver.py resolve_agent_type on a payload carrying this agent's id (acceptance 4:
    close QA's calls resolve the role qa), as the tree under test decides it."""
    import importlib.util
    import sys
    lib = os.path.join(rp.layout.harness, "hooks", "lib")
    with rp.acting("driver"):
        saved = os.environ.get("CLAUDE_PROJECT_DIR")
        os.environ["CLAUDE_PROJECT_DIR"] = rp.layout.project
        sys.path.insert(0, lib)
        try:
            spec = importlib.util.spec_from_file_location("replay_agent_resolver", os.path.join(lib, "agent_resolver.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.resolve_agent_type({"agent_id": agent_id, "tool_name": "Write"})
        except Exception as e:  # noqa: BLE001 (a fact, not a step)
            return f"error: {type(e).__name__}: {e}"
        finally:
            sys.path.remove(lib)
            if saved is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = saved


def run_captured(o, command: str, desc: str, label: str, capture=()):
    """One Bash call of a block; the values it sets that the run keeps are printed after it with
    `declare -p`, the call keeping the block's own exit status (an unset variable is not a failure)."""
    if not capture:
        return o.run(command, desc, label)
    tail = ("\n__rc=$?\nfor __v in " + " ".join(capture) + '; do declare -p "$__v" 2>/dev/null; done\nexit $__rc\n')
    call = o.run(command.rstrip("\n") + tail, desc, label)
    out = call.response.get("stdout", "") if call.ok else (call.error or "")
    o.values.update(parse_declare(out))
    return call


def with_functions(defs: str, text: str) -> str:
    """`text` preceded by the definitions (from `defs`) of the functions it calls, transitively."""
    funcs = {m.group(1): m.group(0) for m in re.finditer(r"^(?:#[^\n]*\n)*?([A-Za-z_]\w*)\(\)\s*\{.*?^\}\n?",
                                                       defs or "", re.M | re.S)}
    bodies = {name: re.sub(r"^(?:#[^\n]*\n)*", "", src) for name, src in funcs.items()}
    defined = set(re.findall(r"^([A-Za-z_]\w*)\(\)\s*\{", text, re.M))
    need, todo = [], [text]
    while todo:
        src = todo.pop()
        for name in funcs:
            if name not in need and name not in defined and re.search(r"(?<![\w-])%s\b" % re.escape(name),
                                                                      re.sub(r"^%s\(\)" % re.escape(name), "", src)):
                need.append(name)
                todo.append(bodies[name])
    if not need:
        return text
    order = [n for n in funcs if n in need]  # the text's own definition order
    return "".join(funcs[n].rstrip("\n") + "\n" for n in order) + text


def last_json(text: str):
    for line in reversed((text or "").strip().splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def _functions(defs: str):
    return re.finditer(r"^([A-Za-z_]\w*)\(\)\s*\{(.*?)^\}", defs or "", re.M | re.S)


def reader_function(defs: str) -> str | None:
    """The function of the text's helper definitions that calls the declaring-dispatch reader."""
    return next((m.group(1) for m in _functions(defs) if "declaring-dispatch" in m.group(2)), None)


def reader_block(section: str) -> str | None:
    """The declaring-dispatch reader as a text spells it as its own Bash call: the bash block of `section`
    that runs `obligation.py declaring-dispatch` with a `<path>` placeholder."""
    try:
        blocks = cmdtext.blocks(section, None, "bash")
    except cmdtext.TextNotFound:
        return None
    return next((b.text for b in blocks if "declaring-dispatch" in b.text and "<path>" in b.text
                 and not re.search(r"^[A-Za-z_]\w*\(\)\s*\{", b.text, re.M)), None)


def reader_call(defs: str, section: str, path: str):
    """(command, name) of the text's reader on `path`: its helper function called with the path, or its
    standalone block with the path for `<path>`; None when the text has no reader."""
    fn = reader_function(defs)
    if fn:
        return f"{fn} {shlex.quote(path)}", fn
    blk = reader_block(section)
    if blk:
        return blk.replace('"<path>"', shlex.quote(path)).replace("<path>", shlex.quote(path)), "declaring-dispatch"
    return None


def role_function(defs: str) -> str | None:
    """The role-table function of a text that maps an artifact path to its producing role."""
    return next((m.group(1) for m in _functions(defs)
                 if "case" in m.group(2) and re.search(r"echo (?:dev|qa|ba|orchestrator)\b", m.group(2))), None)


def summarize_answer(ans, session=None):
    """The answer's fields the report quotes; with `session` (the asking session), whether the dispatch it names
    was made in an earlier session than the one asking (the reader keys records by task id, never by session)."""
    if not isinstance(ans, dict):
        return ans
    out = {k: ans.get(k) for k in ("source", "role", "subagent_type", "lane", "step", "command", "subagent_call",
                                   "tool_use_id") if k in ans}
    if session is not None and ans.get("session_id"):
        out["dispatched_in"] = "this session" if ans["session_id"] == getattr(session, "sid", None) else "an earlier session"
    if isinstance(ans.get("template"), dict):
        out["template_role"] = ans["template"].get("role")
        out["template"] = {k: ans["template"].get(k) for k in ("role", "pipeline", "artifacts")}
    return out


def act_for(run, role: str, edits=None):
    """What a dispatch that runs again does: its role's work on the task as it now stands."""
    o = run.o
    if role == "qa":
        return agents.Act(verdict="pass", work=roles.qa(e2e={"status": "legitimately_skipped",
                                                             "blocking_reason": "no user-facing surface: a library function"},
                                                        guard_respell=o.respell),
                          summary="QA pass", respell=o.respell,
                          text_calls=[("Phase 6: Blast-Radius Phase 2 Verification", {})])
    if role == "dev":
        return agents.Act(work=roles.dev(list(edits or [])),
                          summary="the finding is fixed" if edits else "no change: the work is in place")
    return agents.Act(summary=f"{role}: the finding is addressed")


def dispatch_answer(run, ans, path: str, detail: str, label: str, edits=None):
    """_dispatch_answer, its dispatch recorded (P1c's suite reads the `routed dispatch` facts)."""
    d, role = _dispatch_answer(run, ans, path, detail, label, edits=edits)
    if d is not None and getattr(d, "tool_use_id", ""):
        fact(run.rp, "routed dispatch", {"label": label, "path": path, "role": role,
                                         "agent_id": getattr(d, "agent_id", ""), "tool_use_id": d.tool_use_id})
    return d, role


def _dispatch_answer(run, ans, path: str, detail: str, label: str, edits=None):
    """The reader's answer acted on as the routing text says: a declaring, lane or writing dispatch runs again
    (the same subagent_type and obligation, a fresh dispatched_at, scoped to the finding); a canonical todo
    step with a template is a fresh dispatch of its role from the cycle's template. (dispatch, role)."""
    o = run.o
    if isinstance(ans, dict) and ans.get("source") in ("dispatch", "lane", "writer") and ans.get("prompt"):
        role = ans.get("subagent_type") or ans.get("role")
        now = utc_now()
        prompt = re.sub(r'("dispatched_at"\s*:\s*)"[^"]*"', lambda m: m.group(1) + json.dumps(now), ans["prompt"])
        prompt = prompt.rstrip("\n") + f"\n\nRouting finding: {path}: {detail}\n"
        player = agents.Player(o.tree, prompt, act_for(run, role, edits), role=role)
        lab = run.label(f"{label} Agent({role})")
        d = o.s.dispatch(role, prompt, description=role, body=player.body, result=player.final, label=lab,
                         deviation=run.devs.at(lab))
        return d, role
    call = (ans or {}).get("subagent_call") if isinstance(ans, dict) else None
    if isinstance(ans, dict) and ans.get("source") == "todo_step" and (call or {}).get("subagent_type"):
        # "a fresh dispatch of that role under the same task id, from the template": the id the template's
        # artifacts carry (a lane's, in a fan-out cycle)
        role = call["subagent_type"]
        tid = next((a.get("identity", {}).get("task_id") for a in (ans.get("template") or {}).get("artifacts") or []
                    if isinstance(a, dict) and a.get("identity", {}).get("task_id")), None)
        return run.producer.dispatch(role, o.s, run.devs, run.label(f"{label} Agent({role})"),
                                     note=f"{path}: {detail}", edits=edits, task_id=tid), role
    if isinstance(ans, dict) and ans.get("source") == "todo_step" and not call and not ans.get("template"):
        # "with none, the step is the main agent's own: run it yourself under the same task id"
        if ans.get("command") != run.o.typed and getattr(run.producer, "plays_step", lambda a: False)(ans):
            # a step of the cycle's own command (/dev Step 17, the completion report): its text, run here
            return run.producer.run_step(ans, o.s, run.devs, run.label(label)), "orchestrator"
        return own_work(run, path, detail, label)
    raise RuntimeError(f"the reader's answer for {path} is not one this driver plays: {summarize_answer(ans)}")


def _chain_errors(run, path: str) -> list:
    """The resolver's errors on `path` in the chain the run holds (close's ARTIFACT_CHAIN, or the value the
    last block set)."""
    docs = [getattr(run, "chain", None)]
    try:
        docs.append(json.loads(run.o.values.get("ARTIFACT_CHAIN") or "{}"))
    except ValueError:
        pass
    rel = os.path.relpath(path, run.o.project) if os.path.isabs(path) else path
    for doc in docs:
        errs = [e for e in ((doc or {}).get("errors") or []) if e.get("path") in (rel, path)]
        if errs:
            return errs
    return []


def own_work(run, path: str, detail: str, label: str):
    """The main agent's own work on a finding: the role table's orchestrator row ("the orchestrator does
    the work itself" / "row 8 diagnoses and repairs") and a reader's todo step with no subagent call ("run
    it yourself"). It reads what the finding names and repairs that:
    - an artifact the main agent wrote that the chain resolver reports errors on: each error fixed where it
      says (the identity line it names; the reference it says is missing, added to the artifact's list of
      generated files);
    - a report path that does not exist, which the text fell back to because the task's dev report is gone
      (the /commit Step 5 report selection): its diagnosis is the missing dev report, whose producer is
      dispatched again with the finding.
    (dispatch or None, role)."""
    o, tid = run.o, run.tid
    target = os.path.join(o.project, path) if not os.path.isabs(path) else path
    if not os.path.exists(target):
        docs = os.path.dirname(target)
        g = o.s.tool("Glob", {"pattern": f"*{tid}*", "path": docs}, label=run.label(f"{label} Glob diagnose"))
        listed = (g.response.get("filenames") or []) if g.ok and isinstance(g.response, dict) else []
        dev_report = os.path.join(docs, f"dev-report-{tid}.json")
        if dev_report not in listed and not os.path.exists(dev_report) and run.producer is not None:
            fact(run.rp, "orchestrator diagnosis", {"label": label, "finding": path,
                                                    "diagnosis": f"missing {os.path.relpath(dev_report, o.project)}"})
            note = (f"{path}: {detail}. Diagnosis: {os.path.relpath(dev_report, o.project)} is missing; the "
                    "repository plan derives from it")
            return run.producer.dispatch("dev", o.s, run.devs, run.label(f"{label} Agent(dev)"), note=note), "dev"
        raise RuntimeError(f"no own repair for the missing {path} ({detail})")
    errs = _chain_errors(run, path)
    if not errs:
        raise RuntimeError(f"no own repair for {path}: the chain names no error on it ({detail})")
    o.s.read(target, label=run.label(f"{label} Read {os.path.basename(path)}"))
    with open(target) as fh:
        text = fh.read()
    edits = []
    for e in errs:
        code, d = e.get("code"), e.get("detail") or ""
        m = re.search(r"identity is '([^']*)'; expected '([^']*)'", d)
        if code == "IDENTITY_MISMATCH" and m:
            for line in text.split("\n"):
                if m.group(1) in line and re.search(r"(?i)(task[- ]id|request[- ]id)", line):
                    edits.append((line, line.replace(m.group(1), m.group(2))))
            continue
        m = re.search(r"does not reference (\S+)", d)
        if code == "MISSING_COMPLETION_REFERENCE" and m:
            ref = m.group(1)
            kind = os.path.basename(ref).split("-")[0].capitalize()
            h = re.search(r"(?m)^## Files Generated\n\n(.*)$", text)
            if h:
                edits.append((h.group(0), h.group(0) + f"\n- {kind}: `{ref}`"))
            else:
                last = text.rstrip("\n").split("\n")[-1]
                edits.append((last, last + f"\n\n- {kind}: `{ref}`"))
            continue
        raise RuntimeError(f"no own repair for {code} on {path}: {d}")
    fixed = text
    for old, new in dict.fromkeys(edits):
        fixed = fixed.replace(old, new, 1)
    # One Edit call (the orchestrator gate allows the main agent one Edit per turn): the whole lines spanning
    # every change.
    lines_old, lines_new = text.split("\n"), fixed.split("\n")
    a = 0
    while a < min(len(lines_old), len(lines_new)) and lines_old[a] == lines_new[a]:
        a += 1
    b = 0
    while b < min(len(lines_old), len(lines_new)) - a and lines_old[-1 - b] == lines_new[-1 - b]:
        b += 1
    old_s = "\n".join(lines_old[a:len(lines_old) - b])
    new_s = "\n".join(lines_new[a:len(lines_new) - b])
    if not old_s or text.count(old_s) != 1:
        old_s, new_s = text, fixed
    c = o.s.edit(target, old_s, new_s, label=run.label(f"{label} Edit {os.path.basename(path)}"))
    fact(run.rp, "orchestrator repair", {"label": label, "path": path, "errors": [e.get("code") for e in errs],
                                         "changes": len(dict.fromkeys(edits)), "edit_ok": c.ok})
    return None, "orchestrator"


def with_final_hashes(work):
    """roles.dev's work, its report also carrying final_source_hashes: the sha256 of each file it owns."""
    import hashlib

    def wrapped(sub, brief, player):
        out = work(sub, brief, player) or {}
        doc = out.get("*") or {}
        hashes = {}
        for rel in doc.get("owned_edits") or {}:
            text = agents.peek(sub.rp, sub.role, os.path.join(brief.project, rel))
            hashes[rel] = hashlib.sha256(text.encode()).hexdigest()
        doc["final_source_hashes"] = hashes
        return out
    return wrapped


# ---------------------------------------------------------------- producers (routing targets)

class DevProducer:
    """The cycle's producers, dispatched again under the same task id from the cycle command's own
    templates (the /close and /commit texts name no template of their own for them): the step is the
    one whose canonical checklist item calls the role (the last such step for QA, the final
    verification; the first for BA), the template the one of that step dispatching the role."""

    def __init__(self, cyc):
        self.cyc = cyc
        self.tid = cyc.tid
        self.devs = cyc.o.devs

    @contextlib.contextmanager
    def on(self, session, devs):
        o = self.cyc.o
        saved = o.s, o.devs
        o.s, o.devs = session, devs
        try:
            yield o
        finally:
            o.s, o.devs = saved

    def step_of(self, role: str) -> int:
        steps = [int(m.group(1)) for t in self.cyc.o.todos
                 if (t.get("subagent_call") or {}).get("subagent_type") == role
                 for m in [re.match(r"Step (\d+)", t.get("content", ""))] if m]
        if not steps:
            raise cmdtext.TextNotFound(f"no checklist step of the cycle calls {role!r}")
        return steps[-1] if role == "qa" else steps[0]

    def template(self, role: str) -> dict:
        o, n = self.cyc.o, self.step_of(role)
        k, found = 0, []
        while True:
            try:
                t = o.template(f"Step {n}", index=k)
            except cmdtext.TextNotFound:
                break
            found.append(t)
            k += 1
        for t in found:
            if (t.get("subagent_type") or agents.registry_role(t["prompt"])) == role:
                return t
        if len(found) == 1:
            return found[0]
        raise cmdtext.TextNotFound(f"Step {n} has no template dispatching {role!r}")

    @contextlib.contextmanager
    def lane(self, task_id: str | None):
        """Work on the lane whose id is `task_id` (a fan-out cycle's), else on the cycle itself."""
        lane = next((l for l in getattr(self.cyc, "lanes", None) or [] if l.tid == task_id), None)
        if lane is None:
            yield
            return
        with self.cyc.on(lane):
            yield

    def dispatch(self, role: str, session, devs, label: str, note: str = "", edits=None, hashes: bool = False,
                 task_id=None):
        """`hashes`: dev's report also carries the ledger's final_source_hashes (owned-edits-ledger.v1) of
        each file it owns, as they stand when it reports; `task_id`: the lane of a fan-out cycle it works on."""
        from . import dev as devdrv
        cyc = self.cyc
        with self.on(session, devs) as o, self.lane(task_id):
            extra = [f"Close routing finding: {note}"] if note else []
            if role == "ba" and hasattr(cyc, "dispatch_ba"):
                # BA's artifacts are its analysis template's (P13-1: Step 4c; Step 4 before the requirement round)
                return cyc.dispatch_ba(getattr(cyc, "ba_heading", None) or f"Step {self.step_of('ba')}", label)
            fields = self.template(role)
            add = extra + list(getattr(cyc, "graph_lines", []))
            if any(l.strip().startswith("Context file:") for l in fields["prompt"].split("\n")):
                fields = devdrv.with_lines(fields, add)
            elif add:
                fields = dict(fields, prompt=fields["prompt"].rstrip("\n") + "\n" + "\n".join(add))
            if role == "qa":
                work = roles.qa(e2e={"status": "legitimately_skipped",
                                     "blocking_reason": "no user-facing surface: a library function"},
                                guard_respell=o.respell)
                act = agents.Act(verdict="pass", work=work, summary="QA pass", respell=o.respell,
                                 text_calls=[("Phase 6: Blast-Radius Phase 2 Verification", {})])
                return o.dispatch(fields, act, label, cyc.tid, subagent_type="qa")  # the lane's id on a lane
            if role == "dev":
                baseline = {"baseline_head_sha": o.values.get("baseline_head_sha", ""),
                            "baseline_dirty_snapshot": o.values.get("baseline_dirty_snapshot", "")}
                act = agents.Act(work=with_final_hashes(roles.dev(list(edits or []))) if hashes else
                                 roles.dev(list(edits or [])), content={"*": baseline},
                                 summary="the close finding is fixed" if edits else "no change: the work is in place")
                return o.dispatch(fields, act, label, cyc.tid, subagent_type="dev")  # the lane's id on a lane
        raise NotImplementedError(f"no cycle template for role {role!r}")

    @staticmethod
    def plays_step(ans: dict) -> bool:
        """The main-agent step run_step plays: /dev Step 17."""
        m = re.match(r"Step (\d+)", str(ans.get("step") or ""))
        return ans.get("command") == "dev" and bool(m) and m.group(1) == "17"

    def run_step(self, ans: dict, session, devs, label: str):
        """A canonical step of the cycle's command that is the main agent's own (the reader's todo_step with
        neither subagent call nor template), run by the asking command's main agent under the same task id:
        /dev Step 17, which writes the completion report, as the cycle's text spells it."""
        if not self.plays_step(ans):
            raise NotImplementedError(f"no main-agent step {ans.get('command')} {ans.get('step')!r} in this driver")
        with self.on(session, devs):
            self.cyc.step17(prefix=label)
        return None


class DoProducer:
    """A /do task: its only producer is the main agent's /do work. close.md routes an unfinished
    do-report, and a file the /do main agent wrote, to dev under the same task id (its Routes /do
    bullet), with the obligation that bullet spells; /do itself has no dev template."""

    def __init__(self, turn):
        self.turn = turn
        self.tid = turn.tid

    def dispatch(self, role: str, session, devs, label: str, note: str = "", edits=None, task_id=None):
        raise NotImplementedError(f"/do has no dispatch template for role {role!r} ({note})")

    def pending_edits(self) -> list:
        """The /do turn's changes not yet on disk (the user abandoned the task before them): the work dev,
        dispatched along the do-report's route, completes."""
        turn, out = self.turn, []
        with turn.rp.acting("driver"):
            for rel, old, new in turn.edits:
                with open(os.path.join(turn.o.project, rel), encoding="utf-8") as fh:
                    if old in fh.read():
                        out.append((rel, old, new))
        return out


# ---------------------------------------------------------------- the close run

# What one task of a close holds on its own (an --auto batch walks each step over its parents).
PER_TASK = ("tid", "do_report", "producer", "chain", "spec_id", "session_id", "files", "inspector_reports",
            "round", "repairs", "routed", "verdicts", "outcome", "landed")

# The rating answers the owner may give (Step 4's question), as the dialog returns them.
RATINGS = ("label", "4", "skip", "afk", "decline", "free")


class CloseRun:
    def __init__(self, rp, session, tid: str, do_report: str | None = None, producer=None, variant: str = "plain",
                 auto: bool = False, extra_devs=(), producers=None, typed: str = "", codex=None):
        self.rp, self.tid, self.do_report, self.typed = rp, tid, do_report, typed
        self.producer, self.variant, self.auto = producer, variant, auto
        self.late = variant.startswith("late-repair")  # `/close --late-repair <task-id>` (the R4 section)
        self.producers = dict(producers or {})   # --auto: each parent's producer, by task id
        pairs = list(DEVIATIONS.pairs) + list(extra_devs) + list(getattr(getattr(producer, "devs", None), "pairs", []))
        self.devs = kept_only(rp, Deviations(pairs))
        rp.deviation_at = self.devs.at  # the subagents' own calls take the same deviations by label
        self.o = Orchestrator(rp, "close", session=session, deviations=self.devs, respellings=RESPELLINGS,
                              rules=self._rules())
        self.chain: dict = {}
        self.spec_id = ""
        self.session_id = ""
        self.files: list = []
        self.inspector_reports: list = []
        self.round = 0
        self.repairs: list = []        # repairs close QA records as ## Disclosures (its own rounds' findings)
        self.routed: list = []         # every dispatch routing made
        self.verdicts: list = []       # (round, last line)
        self.outcome = ""
        self.landed = False
        self.stalled = ""
        self.ratings = [r.strip() for r in str(rp.args.get("rating", "label")).split(",") if r.strip()] or ["label"]
        self.asked: list = []          # (task id, answer) of each rating question
        # `--codex`: QA runs the text's Codex review against the stub of `codex` = (rules, script); its landed
        # form is branch 1's, not the codex-disabled one
        self.codex = _codex.CloseCodex(self, codex[0], codex[1], lambda k, v: fact(rp, k, v)) if codex else None
        self.yes_plain = codex[0].yes_line if codex else CLOSE_YES_PLAIN

    # ------------------------------------------------------------ text helpers
    def _rules(self):
        return [
            (r"^(?:TASK_ID|task-id|task_id)$", lambda m: self.tid),
            (r"^SESSION_ID$", lambda m: self.session_id),
            (r"^cycle-diff-file-list$", lambda m: " ".join(self.files)),
            (r"^true\|false$", lambda m: "true" if self.codex else "false"),
        ]

    def label(self, text: str) -> str:
        return f"/close {text}"

    def routing_section(self) -> str:
        return self.o.section("Routes")

    def run_text(self, text: str, label: str, desc: str, capture=(), rules=()):
        o = self.o
        text = o.bind(text, list(rules), [])
        return run_captured(o, o.shell_bind(text), desc, label, capture)

    def read(self, rel_or_abs: str, label: str):
        path = rel_or_abs if os.path.isabs(rel_or_abs) else os.path.join(self.o.project, rel_or_abs)
        return self.o.s.read(path, label=label, deviation=self.devs.at(label))

    def load(self, rel_or_abs: str):
        path = rel_or_abs if os.path.isabs(rel_or_abs) else os.path.join(self.o.project, rel_or_abs)
        return json.loads(agents.peek(self.rp, "main", path))

    def state(self) -> dict:
        return {k: getattr(self, k) for k in PER_TASK}

    def use(self, st: dict) -> None:
        for k, v in st.items():
            setattr(self, k, v)
        self.o.values.update(TASK_ID=self.tid)
        self.rp.task(self.tid)

    # ------------------------------------------------------------ start
    def start(self, args: str) -> None:
        o = self.o
        o.slash(args, label=self.label("typed") if not self.auto else "/close --auto typed")
        os.environ["CLAUDE_TODO_PROMPT"] = f"/close {args}"
        try:
            o.todo_start(label=self.label("TodoWrite canonical list"))
        finally:
            os.environ.pop("CLAUDE_TODO_PROMPT", None)
        o.values.update(TASK_ID=self.tid)
        o.values.setdefault("PROJECT_ROOT", o.project)

    # ------------------------------------------------------------ task-id resolution
    def resolve_typed(self) -> None:
        """A typed path (P5 review M): "Verify it exists"; one that does not is awaiting-input cause (iii)
        naming it, asked in the turn with ONE AskUserQuestion (D23), this conversation's task recommended.
        The owner picks it, and the resolution resumes in place on that id (TASK_ID, as typed)."""
        o = self.o
        lab = self.label("Task-id resolution Glob typed path")
        g = o.s.tool("Glob", {"pattern": os.path.basename(self.typed),
                              "path": os.path.join(o.project, os.path.dirname(self.typed))},
                     label=lab, deviation=self.devs.at(lab))
        if not g.ok or g.response.get("filenames"):
            raise agents.PlayError(f"Task-id resolution: the typed {self.typed} exists, or Glob failed")
        question = f"{self.typed} does not exist, so no spec is identified. Which task do I close?"
        lab = self.label("Task-id resolution AskUserQuestion")
        options = [{"label": f"{self.tid} (Recommended)", "description": "the task this conversation ran"},
                   {"label": "I name another task", "description": ""}]
        call = o.s.tool("AskUserQuestion", {"questions": [{"question": question, "header": "Task id",
                                                           "multiSelect": False, "options": options}]},
                        label=lab, deviation=self.devs.at(lab))
        answer = (call.response.get("answers") or {}).get(question, "").replace(" (Recommended)", "") if call.ok else ""
        fact(self.rp, "close typed", {"typed": self.typed, "asked": question, "answer": answer})
        if answer != self.tid:
            raise agents.PlayError(f"Task-id resolution: the owner's answer {answer!r} is not {self.tid}")

    def resolve_task(self) -> None:
        o = self.o
        if not self.do_report:
            return
        g = o.s.tool("Glob", {"pattern": f"d*-report-{self.tid}.json", "path": os.path.join(o.project, "docs/dev")},
                     label=self.label("Task-id resolution Glob reports"),
                     deviation=self.devs.at(self.label("Task-id resolution Glob reports")))
        names = [os.path.basename(p) for p in (g.response.get("filenames") or [])] if g.ok else []
        if f"dev-report-{self.tid}.json" in names and "a dev-report takes precedence" in o.section("Task-id resolution"):
            self.do_report = None
            return
        o.values.update(DO_REPORT=self.do_report)

    # ------------------------------------------------------------ Step 0
    def disposition(self, label: str) -> dict:
        """Step 0's one call (its block), its output read as the text says: the DISPOSITION line, the GAP
        lines, the CHAIN line; a non-zero exit is an instrument failure (its reason on stderr)."""
        c = self.run_text(self.o.block("Step 0", lang="bash", index=0), self.label(f"{label} Bash disposition"),
                          "Step 0: the task's disposition")
        if not c.ok:
            text = (c.error or "").strip()
            reason = next((l for l in reversed(text.splitlines()) if l.strip()), text)
            return {"ok": False, "reason": reason, "blocked": c.blocked}
        out = {"ok": True, "disposition": "", "gaps": [], "chain": {}}
        for line in (c.response.get("stdout") or "").splitlines():
            m = re.match(r"DISPOSITION=(\S+)", line)
            if m:
                out["disposition"] = m.group(1)
            m = re.match(r'GAP artifact=("(?:[^"\\]|\\.)*"|\S+) problem=("(?:[^"\\]|\\.)*"|\S+): (.*) '
                         r'lane=("(?:[^"\\]|\\.)*"|\S+)$', line)
            if m:
                art, prob, msg, lane = (json.loads(v) if v.startswith('"') else v for v in m.groups())
                out["gaps"].append({"artifact": art, "problem": prob, "message": msg,
                                    "lane": None if lane == "-" else lane})
            if line.startswith("CHAIN="):
                out["chain"] = json.loads(line[len("CHAIN="):])
        return out

    def step0(self, label: str = "Step 0", rounds: int = 4) -> bool:
        """Step 0 as the text says: one call; incomplete -> each gap routed (Routes), the call run again;
        a non-zero exit run once more, then one OPERATION_STALLED: line. False when stalled."""
        out = self.disposition(label)
        k = 0
        while True:
            if not out["ok"]:
                again = self.disposition(f"{label} retry")
                if not again["ok"]:
                    self.stalled = again["reason"]
                    self.o.s.say(f"OPERATION_STALLED: {again['reason']}\nNext harness-repair item: the Step 0 "
                                 f"disposition call for {self.tid}.")
                    fact(self.rp, "close Step 0", {"label": label, "stalled": self.rp.norm_text(again["reason"])[:300]})
                    return False
                out = again
            fact(self.rp, "close Step 0", {"label": label, "disposition": out["disposition"],
                                            "gaps": [(g["artifact"], g["problem"]) for g in out["gaps"]],
                                            "mode": out["chain"].get("mode")})
            if out["disposition"] == "chain_pass":
                self.chain = out["chain"] or {}
                self.o.values.update(ARTIFACT_CHAIN=json.dumps(self.chain))
                return True
            if out["disposition"] != "incomplete" or k >= rounds:
                raise agents.PlayError(f"Step 0 still {out['disposition'] or 'unread'} after {k} routing round(s): "
                                       f"{[(g['artifact'], g['problem']) for g in out['gaps']]}")
            k += 1
            # what the main agent's own step reads when the reader names one (own_work): the gaps as errors
            self.chain = {"errors": [{"code": g["problem"], "path": g["artifact"], "detail": g["message"]}
                                     for g in out["gaps"]]}
            by_artifact: dict = {}
            for g in out["gaps"]:  # each artifact the GAP lines name, with all of its problems at once
                by_artifact.setdefault(g["artifact"], []).append(f"{g['problem']}: {g['message']}")
            n = len(self.routed)
            for art, problems in by_artifact.items():
                self.route_path(art, "; ".join(problems), f"Step 0 round {k}")
            self.repairs.extend(self.routed[n:])  # a repair Routes completed: a `## Disclosures` line
            out = self.disposition(f"{label} round {k} re-run")

    def cp_state(self) -> None:
        o = self.o
        g = o.s.tool("Glob", {"pattern": "cp-state-qa.json", "path": os.path.join(o.project, ".claude/specs", self.tid)},
                     label=self.label("Step 0 Glob cp-state"), deviation=self.devs.at(self.label("Step 0 Glob cp-state")))
        self.spec_id = self.tid if g.ok and g.response.get("filenames") else ""

    # ------------------------------------------------------------ the late-repair route (R4)
    def lr_section(self) -> str:
        return self.o.section("Late-repair route")

    def lr_code(self, verb: str) -> str:
        """The R4 section's own spelling of one controller call (its first inline code naming the verb)."""
        for code in re.findall(r"`([^`]+)`", self.lr_section()):
            if re.search(r'late-repair-controller\.py"? %s(?![\w-])' % re.escape(verb), code):
                return code
        raise cmdtext.TextNotFound(f"the late-repair route names no {verb} call")

    def lr_run(self, verb: str, label: str, desc: str, binds=()) -> dict:
        """One controller call as the section spells it, its placeholders bound; its JSON line ({} if none).
        A refusal exits non-zero: its line is in the failed call's output."""
        c = self.run_text(self.lr_code(verb), self.label(label), desc, rules=binds)
        got = last_json((c.response.get("stdout") or "") if c.ok else (c.error or "")) or {}
        shown = {k: ("<id>" if k == "repair_run_id" else v) for k, v in got.items() if k != "sha256"}
        fact(self.rp, f"late-repair {verb}", {"label": label, "ok": c.ok, "blocked": c.blocked, "result": shown})
        return got

    def lr_stage(self, stage: str) -> str:
        """One stage of the route: its role dispatched again under the same task id from the cycle's own
        template (no template of /close declares BA, or dev outside the /do route), against the work as it
        stands; returns the chain report its obligation declares (record-stage's --report-path)."""
        tid = self.tid
        lab = self.label(f"Step 0 late-repair Agent({stage})")
        kw = {}
        if stage == "dev" and self.variant == "late-repair-drift":
            kw = {"edits": [(FINDING["path"], self.current(FINDING["path"]), self.fixed(FINDING["path"]))],
                  "hashes": True}
        d = self.producer.dispatch(stage, self.o.s, self.devs, lab,
                                   note=f"late repair: {stage} again against the current state of the work", **kw)
        ob = d.player.b.obligation if getattr(d, "player", None) else None
        chain = {f"docs/dev/ticket-{tid}.md", f"docs/dev/context-{tid}.json", f"docs/dev/dev-report-{tid}.json",
                 f"docs/dev/qa-report-{tid}.json"}
        rel = next((a["path"] for a in (ob or {}).get("artifacts") or [] if a.get("path") in chain), "")
        fact(self.rp, "late-repair stage", {"stage": stage, "pipeline": (ob or {}).get("pipeline"),
                                             "task_id": (ob or {}).get("task_id") == tid, "blocked": d.blocked,
                                             "stop_blocked": bool(d.stop and d.stop.still_blocked),
                                             "report": rel.replace(tid, "<task>")})
        return rel

    def late_repair(self) -> bool:
        """`--late-repair`, as the R4 section spells it: init once; a decline is recorded and Step 0's
        disposition call runs (the ordinary route). Otherwise BA, then dev, then QA dispatched again with
        record-stage after each, finalize (Step 0, the main agent's own step), verify-disclosure (a refusal
        routed on the path it names, then verify-disclosure again); admitted goes on as the section's
        `admitted` item says. False when Step 0 stalls."""
        o, tid = self.o, self.tid
        o.values["LATE_REPAIR"] = "true"
        init = self.lr_run("init", "Step 0 late-repair Bash init", "Late repair: eligibility and the run record")
        with self.rp.acting("driver"):
            recorded = os.path.exists(os.path.join(o.project, f"docs/dev/late-repair-run-{tid}.json"))
        fact(self.rp, "late-repair run record", recorded)
        if init.get("outcome") == "refuse":
            o.s.say(f"Late repair declined for {tid}: {init.get('reason')}. Step 0's disposition call runs "
                    "(the ordinary route).")
            o.values["LATE_REPAIR"] = "false"
            return self.step0()
        if init.get("outcome") not in ("initialized", "already_initialized"):
            raise agents.PlayError(f"late-repair init printed {init}")
        run_id = init.get("repair_run_id") or ""
        for stage in ("ba", "dev", "qa"):
            rel = self.lr_stage(stage)
            got = self.lr_run("record-stage", f"Step 0 late-repair Bash record-stage {stage}",
                              f"Late repair: record the {stage} stage",
                              [(r"^ba\|dev\|qa$", stage), (r"^path$", rel), (r"^id$", run_id)])
            if got.get("outcome") != "recorded":
                raise agents.PlayError(f"record-stage {stage} printed {got}")
        if self.variant == "late-repair-drift":
            # Driver setup: a peer's line lands on the dev's file after the stages (the unit fixture's PEER).
            with self.rp.acting("driver"):
                with open(os.path.join(o.project, FINDING["path"]), "a") as fh:
                    fh.write(PEER_LINE)
        fin = self.lr_run("finalize", "Step 0 late-repair Bash finalize", "Late repair: drift detection",
                          [(r"^id$", run_id)])
        if fin.get("outcome") != "finalized_pending_verification":
            raise agents.PlayError(f"finalize printed {fin}")
        for k in range(4):
            ver = self.lr_run("verify-disclosure", f"Step 0 late-repair Bash verify-disclosure {k}",
                              "Late repair: verify the disclosure")
            if ver.get("outcome") == "admitted":
                break
            if not ver.get("path") or k == 3:
                raise agents.PlayError(f"verify-disclosure printed {ver}")
            self.route_path(ver["path"], ver.get("reason", ""), f"Step 0 late-repair verify round {k + 1}")
        item = next((it for it in re.split(r"\n(?=- )", self.lr_section()) if it.startswith("- `admitted`")), "")
        chain_call = "disposition call" in item
        fact(self.rp, "late-repair admitted", {"admitted item runs Step 0's disposition call": chain_call})
        if chain_call:
            return self.step0("Step 0 late-repair admitted")
        return True

    def late_inputs(self, where: str, **extra) -> None:
        """What Steps 1-3 hold of the chain on the late-repair route (a fact): whether ARTIFACT_CHAIN is
        bound, the canonical report it names, and the report's own files_modified beside what was passed."""
        tid = self.tid
        with self.rp.acting("driver"):
            try:
                with open(os.path.join(self.o.project, f"docs/dev/dev-report-{tid}.json")) as fh:
                    declared = (json.load(fh).get("dev") or {}).get("files_modified") or []
            except (OSError, ValueError):
                declared = None
        fact(self.rp, f"late-repair {where}", dict({
            "ARTIFACT_CHAIN bound": bool(self.chain.get("mode")),
            "canonical_dev_report": (self.chain.get("canonical_dev_report") or "").replace(tid, "<task>"),
            "dev-report files_modified": declared}, **extra))

    # ------------------------------------------------------------ Routes
    def reader(self, path: str, label: str):
        call = reader_call("", self.routing_section(), path)
        if not call:
            raise cmdtext.TextNotFound("Routes has no declaring-dispatch block")
        cmd, fn = call
        c = self.run_text(cmd, self.label(f"{label} Bash {fn}"), "Who owes the artifact")
        ans = last_json(c.response.get("stdout") or "") if c.ok else None
        fact(self.rp, "owing dispatch", {"label": label, "path": path, "answer": summarize_answer(ans, self.o.s)})
        return ans

    @staticmethod
    def is_close_qa(ans) -> bool:
        ob = (ans or {}).get("obligation") or {} if isinstance(ans, dict) else {}
        return ob.get("pipeline") == "close" and ob.get("role") == "qa"

    def route_path(self, path: str, detail: str, label: str, edits=None, close_finding: bool = False):
        """Routes: the reader's answer on `path` dispatched again under the same task id (the /do bullet
        first); a null answer for a close-QA finding goes to that round's own QA dispatch, which names the
        artifact, routed in turn."""
        if self.do_report:
            return self.do_dev(path, detail, label, edits)
        ans = self.reader(path, label)
        if ans is None and close_finding:
            own = self.reader(self.report_rel(), f"{label} own QA")
            named = self.rerun_close_qa(own, path, detail, label)
            return self.route_path(named["path"], named["detail"], f"{label} named", edits=edits)
        if ans is None:
            raise agents.PlayError(f"the reader names no owner for {path}: the text asks the owner (header Request)")
        if self.is_close_qa(ans):
            named = self.rerun_close_qa(ans, path, detail, label)
            return self.route_path(named["path"], named["detail"], f"{label} named", edits=edits)
        n = len(self.routed)
        d, role = dispatch_answer(self, ans, path, detail, label, edits=edits)
        if d is not None and getattr(d, "agent_id", ""):
            self.routed.append({"path": path, "problem": detail, "role": role})
        fact(self.rp, "routed", {"label": label, "path": path, "role": role, "new": len(self.routed) - n})
        return d, role

    def do_template(self) -> str:
        """The obligation Routes' /do bullet spells (its inline `<obligation v="1">` block)."""
        item = next((it for it in re.split(r"\n(?=- )", self.routing_section()) if it.startswith("- A `/do` task")), "")
        m = re.search(r'`(<obligation v="1">\{.*?\}</obligation>)`', item)
        if not m:
            raise cmdtext.TextNotFound("Routes' /do bullet spells no obligation")
        return m.group(1)

    def do_dev(self, path: str, detail: str, label: str, edits=None):
        """The Routes /do bullet: dev under the same task id with the obligation the bullet spells. With
        `--arg dev_stop=unwritten` the first such dev stops leaving that artifact as it is, with
        `dev_stop=uncompleted` having written it with its terminal field short of completed; on G2's block it
        writes it completed and stops again."""
        o = self.o
        prompt = o.instantiate(self.do_template() + f"\n\nComplete the /do work of task {self.tid}: {path}: {detail}\n",
                               self.tid)
        arts = agents.obligation_of(prompt)["artifacts"]
        short = self.rp.args.get("dev_stop") if not any(r["role"] == "dev" for r in self.routed) else None
        done: dict = {}
        if edits is None and hasattr(self.producer, "pending_edits"):
            edits = self.producer.pending_edits()
        dev_work = roles.dev(list(edits or []), baseline_fallback=True)

        def work(sub, brief, player):
            done.update(dev_work(sub, brief, player) or {})
            for art in arts if short == "uncompleted" else ():
                doc = player.json_doc(art, done)
                for dotted in player.tree.terminal_vocabulary().get(art["schema"], {}):
                    schemagen.set_path(doc, dotted, "blocked")
                agents.put(sub, os.path.join(o.project, art["path"]), json.dumps(doc, indent=2) + "\n",
                           f"{sub.role} Write {art['path']}")
            return done
        # no baseline was captured for a /do task: the agent text's fallback (empty values, git status)
        act = agents.Act(work=work, content={"do-report.v1": {"do": {"status": "completed"}},
                                             "dev-report.v2": {"baseline_head_sha": "", "baseline_dirty_snapshot": ""}},
                         faults={a["path"]: "missing" for a in arts} if short else {},
                         summary="the /do work is complete")
        player = agents.Player(o.tree, prompt, act, role="dev")

        def finish(sub, ev):
            fact(self.rp, "routed dev stop blocked", {"label": label, "hooks": sorted({b["hook"] for b in ev.blocks})})
            act.faults = {}
            for art in arts:
                player._write_artifact(sub, art, done)
            return player.final(sub)
        lab = self.label(f"{label} Agent(dev)")
        d = o.s.dispatch("dev", prompt, description="dev", body=player.body, result=player.final, label=lab,
                         deviation=self.devs.at(lab), on_stop_block=finish if short else None)
        fact(self.rp, "routed dev", {"label": label, "task_id": self.tid == agents.obligation_of(prompt)["task_id"],
                                     "pipeline": agents.obligation_of(prompt).get("pipeline"),
                                     "artifacts": [a["path"].replace(self.tid, "<task>") for a in arts],
                                     "written": [p.replace(self.tid, "<task>") for p in player.written],
                                     "stop_blocked": bool(d.stop and d.stop.still_blocked)})
        self.routed.append({"path": path, "problem": detail, "role": "dev"})
        return d, "dev"

    # ------------------------------------------------------------ Step 1
    def do_conclusion(self) -> str | None:
        """The dev-report dev wrote along the do-report's route, where the text has it conclude the /do task
        (Q7) and it exists."""
        rel = f"docs/dev/dev-report-{self.tid}.json"
        said = "dev-report-<TASK_ID>.json" in self.o.section("Step 1")
        return rel if said and os.path.exists(os.path.join(self.o.project, rel)) else None

    def cycle_files(self) -> list:
        if self.do_report:
            files = list((self.load(self.do_report).get("do") or {}).get("files_modified") or [])
            rel = self.do_conclusion()
            if rel:
                self.read(rel, self.label("Step 1 Read the /do task's dev-report"))
                files += [f for f in (self.load(rel).get("dev") or {}).get("files_modified") or [] if f not in files]
            return files
        rel = self.chain.get("canonical_dev_report") or ""
        if not rel:
            return []
        self.read(rel, self.label("Step 1 Read canonical dev report"))
        return list((self.load(rel).get("dev") or {}).get("files_modified") or [])

    def no_registry(self) -> bool:
        """Whether the text has a /do task leave out Step 1's registry call and the FIRST ACTION line of every
        dispatch of Steps 1 and 2 (a /do task has no registry directory)."""
        return bool(self.do_report) and "leave the FIRST ACTION line out" in self.o.section("Step 1")

    def registry_name(self) -> None:
        if self.no_registry():
            return
        c = self.run_text(self.o.block("Step 1", lang="bash", index=0), self.label("Step 1 Bash registry-dir"),
                          "The task's registry directory")
        self.session_id = (c.response.get("stdout") or "").strip() if c.ok else ""

    def inspector_bullets(self) -> list:
        """(subagent_type, FIRST ACTION line, obligation, report path) of each of Step 1's three Agent calls."""
        out = []
        for line in self.o.section("Step 1").split("\n"):
            m = re.match(r"\s*-\s+Agent (?:tool )?call \d+:\s*`subagent_type:\s*([\w-]+)`", line)
            if not m:
                continue
            first = re.search(r"`(FIRST ACTION:[^`]+)`", line).group(1)
            ob = re.search(r"`(<obligation v=\"1\">\{.*?\}</obligation>)`", line).group(1)
            report = re.search(r"writes? its report to `([^`]+)`", line).group(1)
            out.append((m.group(1), first, ob, report))
        if len(out) != 3:
            raise cmdtext.TextNotFound(f"Step 1 lists {len(out)} inspector dispatches, not three")
        return out

    def inspector_act(self, role: str) -> agents.Act:
        project = self.o.project
        text = self.o.tree.agent_text(role)
        final = re.search(r"`(STATUS: complete)`", text)

        def work(sub, brief, player):
            for rel in self.files:
                p = os.path.join(project, rel)
                if os.path.isfile(p):
                    sub.read(p, label=f"{sub.role} Read {rel}")
            # Standard 6's unconditional scan of the prompt directories, where the agent text keeps it.
            m = re.search(r"Scan all existing paths among: (.*?)\.", text)
            if m:
                for pat in re.findall(r"`([^`]+)`", m.group(1)):
                    sub.tool("Glob", {"pattern": pat, "path": project}, label=f"{sub.role} Glob {pat}")
            return {"*": {"inspector": role, "violations": [], "codex_consult": {"status": "disabled_by_user"}}}
        return agents.Act(work=work, final_line=final.group(1) if final else "",
                          summary=f"{role}: no violation introduced by this diff")

    def step1(self) -> None:
        o = self.o
        self.files = self.cycle_files()
        if self.late:
            self.late_inputs("Step 1 inputs", **{"--changed-files": list(self.files)})
        self.registry_name()
        self.inspector_reports = []
        for role, first, ob, report in self.inspector_bullets():
            prompt = "\n".join(([] if self.no_registry() else [first]) + [ob, f"--changed-files {' '.join(self.files)}",
                                                                          f"Write your report to: {report}"])
            prompt = o.bind(o.instantiate(prompt, self.tid))
            left = cmdtext.placeholders(prompt)
            if left:
                raise cmdtext.TextNotFound(f"inspector prompt keeps placeholders {left}")
            act = self.inspector_act(role)
            player = agents.Player(o.tree, prompt, act, role=role)
            lab = self.label(f"Step 1 Agent({role})")
            o.s.dispatch(role, prompt, description=role, body=player.body, result=player.final, label=lab,
                         deviation=self.devs.at(lab))
            self.inspector_reports.append(o.bind(report))

    # ------------------------------------------------------------ Step 2
    def input_lines(self, prompt: str) -> str:
        """The Input artifacts bullets, each `<...>` filled from the chain Step 0 printed or the do-report; a
        bullet whose description says "otherwise omit" and has no value here is left out."""
        lines = prompt.split("\n")
        try:
            i = next(k for k, l in enumerate(lines) if l.strip().startswith("Input artifacts"))
        except StopIteration:
            return prompt
        out, k = lines[:i + 1], i + 1
        chain = self.chain
        while k < len(lines) and lines[k].startswith("- "):
            j = k + 1
            while j < len(lines) and lines[j].startswith("  ") and not lines[j].startswith("- "):
                j += 1
            item = "\n".join(lines[k:j])
            name, _, desc = item[2:].partition(":")
            desc = desc.strip()
            value = None
            if "<" not in desc:
                value = desc
            elif "complete ARTIFACT_CHAIN JSON" in desc:
                value = json.dumps(chain) if not self.do_report else "none"
            else:
                f = re.search(r"ARTIFACT_CHAIN\.(\w+)", desc)
                if f and not ("parent ticket" in desc or "lanes[] row" in desc):
                    if self.do_report:
                        value = "do" if f.group(1) == "mode" else "[]"
                    else:
                        v = chain.get(f.group(1))
                        value = v if isinstance(v, str) else json.dumps(v if v is not None else [])
                elif "do-report" in desc and "/do work" in desc:
                    concluded = self.do_conclusion() if self.do_report and "dev-report" in desc else None
                    value = ", ".join(p for p in (self.do_report, concluded) if p) or None
                elif "parent ticket" in desc and chain.get("mode") == "singular" and not self.do_report:
                    value = json.dumps(chain.get("artifact_paths"))
                elif name.strip() == "Completed repairs":  # what Routes completed in this /close so far
                    value = json.dumps([f"{r['path']}: {r['problem']} | 归因: {r['role']} | 修复: dispatched again"
                                        for r in self.repairs], ensure_ascii=False)
            if value is not None:
                out.append(f"- {name.strip()}: {value}")
            elif "omit" not in desc:
                out.append(item)
            k = j
        return "\n".join(out + lines[k:])

    def qa_prompt(self) -> str:
        o = self.o
        tpl = next(b.text for b in cmdtext.blocks(o.section("Step 2")) if "<obligation" in b.text)
        lines = [line for line in tpl.split("\n")
                 if (self.spec_id or not line.strip().startswith("SECOND ACTION (only if SPEC_ID is non-empty"))
                 and not (self.no_registry() and line.startswith("FIRST ACTION:"))]
        prompt = self.input_lines("\n".join(lines))
        if self.late:
            self.late_inputs("Step 2 inputs", **{"Input artifacts": [
                l.replace(self.tid, "<task>")[:160] for l in prompt.split("\n")
                if l.startswith(("- Artifact-chain result:", "- Mode:", "- Report paths:", "- QA inputs:"))]})
        prompt = o.instantiate(prompt, self.tid)
        return o.bind(prompt)  # QA's own instruction placeholders (<n>, <error detail>, ...) stay as written

    def report_rel(self) -> str:
        return f"docs/dev/close-report-{self.tid}.md"

    def close_qa_act(self, verdict: str, finding: dict | None, append: bool) -> agents.Act:
        if self.codex:
            return self.codex.act(append)
        o, tid = self.o, self.tid
        project = o.project
        inputs = ([self.do_report] if self.do_report else list(self.chain.get("report_paths") or [])) + self.inspector_reports
        mode = "do" if self.do_report else self.chain.get("mode", "singular")
        rounds = self.round
        lines = [f"Task-id: {tid}", f"Artifact-chain mode: {mode}", "Input files: " + ", ".join(inputs),
                 f"Rounds run: 1 (judging round {rounds} of this close)",
                 "Workflow Integrity Dimension:",
                 "1. Downstream consumability: " + ("N/A — /do path: the do-report is changelog-analyst's whitelist source"
                                                    if self.do_report else "PASS — Step 0's chain_pass covers the chain /commit consumes"),
                 "2. task-id chain consistency: " + ("N/A — /do path: do-report -> close-report under one task id"
                                                     if self.do_report else "PASS — Step 0's chain_pass covers every identity"),
                 "3. Pre-existing-defect rule: PASS — nothing pre-existing raised",
                 "4. Self-deployability: PASS — (i) PASS citing chain_pass, (ii) PASS (local bare origin), (iii) PASS, (iv) N/A",
                 "Codex consultation: codex_status: disabled_by_user",
                 "[Codex] consultation skipped: --codex flag not passed; QA-only assessment performed"]
        if finding:
            lines += ["", "## Findings", f"- {finding.get('path') or self.report_rel()}: {finding['detail']}"]
        if self.repairs and not finding:
            lines += ["", "## Disclosures"] + [f"{r['path']}: {r['problem']} | 归因: {r['role']} | 修复: dispatched again, "
                                               f"re-judged clean in round {rounds}" for r in self.repairs]
        body = "\n".join(lines)

        def work(sub, brief, player):
            for rel in inputs:
                p = os.path.join(project, rel)
                if os.path.isfile(p):
                    sub.read(p, label=f"{sub.role} Read {rel}")
            if self.files:
                sub.bash("git diff -- " + " ".join(shlex.quote(f) for f in self.files),
                         "Inspect the cycle diff", label=f"{sub.role} Bash git diff")
            if not append:
                return None
            # Overwrite policy: the section to a temp file, then the append helper the text names.
            section = os.path.join("/tmp/claude-scratch/qa", f"close-section-{tid}-r{rounds}.md")
            text = f"## Close attempt (round {rounds}) {utc_now()}\n\n{body}\n\n{verdict}\n"
            sub.write(section, text, label=f"{sub.role} Write section")
            code = self.append_call()
            code = code.replace('"<absolute-temp-section-path>"', shlex.quote(section)).replace(
                "<absolute-temp-section-path>", section)
            code = o.bind(code)
            c = sub.bash(o.respell(code, f"{sub.role} Bash append helper"), "Append this attempt's section",
                         label=f"{sub.role} Bash append helper")
            out = (c.response.get("stdout") or "") if c.ok else (c.error or "")
            line = out.strip().splitlines()[-1] if out.strip() else ""
            try:
                got = json.loads(line).get("verdict_line") if c.ok else None
            except ValueError:
                got = None
            act.terminal["response_line"] = got or (line if line.startswith("CLOSE_REPORT_APPEND_") else verdict)
            return None

        act = agents.Act(work=work, notes=body, terminal={self.report_rel(): verdict, "response_line": verdict},
                         produced=[self.report_rel()] if append else [], summary="close debate")
        return act

    def append_call(self) -> str:
        m = re.search(r"`([^`]*close-report-append\.py[^`]*)`", self.o.section("Step 2"))
        if not m:
            raise cmdtext.TextNotFound("Step 2 names no append helper call")
        return m.group(1)

    def close_round(self, verdict: str, finding=None, prompt: str | None = None, label: str | None = None) -> str:
        """One close-QA dispatch: a fresh round from Step 2's prompt, or (prompt given) the round's own QA
        dispatch run again as Routes says."""
        o = self.o
        self.round += 1
        append = os.path.exists(os.path.join(o.project, self.report_rel()))
        prompt = prompt or self.qa_prompt()
        act = self.close_qa_act(verdict, finding, append)
        player = agents.Player(o.tree, prompt, act, role="qa")
        lab = label or self.label(f"Step 2 Agent(qa) close round {self.round}")
        d = o.s.dispatch("qa", prompt, description="close debate", body=player.body, result=player.final, label=lab,
                         deviation=self.devs.at(lab))
        text = ((d.response.get("content") or [{}])[0].get("text") or "") if d.response else ""
        last = text.strip().splitlines()[-1] if text.strip() else ""
        self.verdicts.append((self.round, last))
        fact(self.rp, "close QA round", {"task": "<task>", "round": self.round, "verdict": last, "append": append,
                                          "findings": [{k: finding.get(k) for k in ("path", "detail")}] if finding else [],
                                          "resolved_role": resolved_role(self.rp, d.agent_id) if d.agent_id else None,
                                          "stop_blocked": bool(d.stop and d.stop.still_blocked)})
        return last

    def rerun_close_qa(self, ans, path: str, detail: str, label: str) -> dict:
        """Routes' null-for-a-close-QA-finding bullet: that round's own QA dispatch (the reader's answer for
        the close-report) runs again under the same task id and names the artifact; returns its finding."""
        if not self.is_close_qa(ans) or not ans.get("prompt"):
            raise agents.PlayError(f"the reader's answer for the close-report is not close QA: {summarize_answer(ans)}")
        named = NAMED.get(self.variant, FINDING)
        named = {"path": named["path"].replace("<task>", self.tid), "detail": named["detail"]}
        prompt = re.sub(r'("dispatched_at"\s*:\s*)"[^"]*"', lambda m: m.group(1) + json.dumps(utc_now()), ans["prompt"])
        prompt = prompt.rstrip("\n") + f"\n\nRouting finding: {path}: {detail}. Name the artifact it concerns.\n"
        self.close_round(CLOSE_FINDINGS_ONE, named, prompt=prompt,
                         label=self.label(f"{label} Agent(qa) own QA names the artifact"))
        self.o.s.say(CLOSE_FINDINGS_ONE)
        fact(self.rp, "own QA named", {"label": label, "finding": path, "named": named["path"]})
        return named

    def step2(self) -> str:
        """Close QA rounds until one lands; a round-open return is echoed and routed (Routes), Step 0's call
        runs again, then a fresh round."""
        o = self.o
        if self.codex:
            return self.codex.step2()
        first = getattr(self, "broken", None) or FIRSTS.get(self.variant)
        if first:
            first = {"path": first["path"], "detail": first["detail"], "new": first.get("new")}
        plain = f"CLOSE: YES - with disclosures: {len(self.repairs)} items" if self.repairs else CLOSE_YES_PLAIN
        last = self.close_round(CLOSE_FINDINGS_ONE if first else plain, first)
        k = 0
        while last.startswith("CLOSE_FINDINGS") and k < 3:
            k += 1
            o.s.say(last)
            self.read(self.report_rel(), self.label(f"Step 2 Read close-report round {self.round}"))
            path = (first or {}).get("path") or self.report_rel()
            edits = [(FINDING["path"], self.current(FINDING["path"]), self.fixed(FINDING["path"]))]
            if (first or {}).get("new") is not None:  # break: the writer puts its own fix back
                edits = [(first["path"], self.current(first["path"]), first["new"])]
            n = len(self.routed)
            self.route_path(path, (first or FINDING)["detail"], f"Step 2 round {k}", edits=edits, close_finding=True)
            self.repairs.extend(self.routed[n:])
            if not self.step0(f"Step 2 round {k} Step 0"):
                return ""
            verdict = f"CLOSE: YES - with disclosures: {len(self.repairs)} items" if self.repairs else CLOSE_YES_PLAIN
            last = self.close_round(verdict)
            first = None
        return last

    def current(self, rel: str) -> str:
        return agents.peek(self.rp, "main", os.path.join(self.o.project, rel))

    def fixed(self, rel: str) -> str:
        cur = self.current(rel)
        return cur if TOY_DOC in cur else cur.replace("def add(a, b):\n", "def add(a, b):\n" + TOY_DOC, 1)

    # ------------------------------------------------------------ Step 3
    def step3(self, last: str) -> None:
        o = self.o
        o.s.say(last)
        self.landed = last.startswith("CLOSE: YES")
        self.outcome = last
        if not self.landed:
            return
        ever = False
        for item in (self.chain.get("qa_inputs") or []) if not self.do_report else []:
            rel = item if isinstance(item, str) else (item.get("path") or item.get("qa_report") or "")
            if rel and os.path.isfile(os.path.join(o.project, rel)):
                self.read(rel, self.label(f"Step 3 Read {rel}"))
        # The scoring helper runs where the text names it; a close.md without the
        # scoring section (moved to P4, design.md section 6.1) runs none.
        try:
            decide = o.block("Step 3", anchor="close-scoring-decide.py").strip()
        except cmdtext.TextNotFound:
            decide = ""
        if decide:
            c = self.run_text(decide, self.label("Step 3 Bash close-scoring-decide"), "Which close_success event",
                              rules=[(r"^true\|false$", "true" if ever else "false")])
            try:
                events = json.loads((c.response.get("stdout") or "").strip().splitlines()[-1]).get("events") or [] if c.ok else []
            except (ValueError, IndexError):
                events = []
            example = o.block("Step 3", anchor="score-update.sh --agent dev")
            ex_event = re.search(r"--event (\w+)", example).group(1)
            for ev in events:
                for k, line in enumerate(l for l in example.split("\n") if l.strip()):
                    self.run_text(line.replace(ex_event, ev), self.label(f"Step 3 Bash score-update {ev} {k + 1}"),
                                  "Mascot score update")
        o.s.say("## Session Summary\n- Accomplished: toy.add validates its arguments.\n- Not accomplished: none.\n"
                "- User needs satisfied: non-numbers raise TypeError naming the argument.\n"
                "- User needs not satisfied: none.\n- Bugs encountered: none.\n- Improvement opportunities: none.")
        o.s.say(f"Next: /commit {self.tid} -m \"toy.add validates its arguments\"")

    # ------------------------------------------------------------ Step 4
    def rating_input(self) -> dict:
        block = next(b.text for b in cmdtext.blocks(self.o.section("Step 4")) if '"questions"' in b.text)
        return json.loads(block.replace("<task-id>", self.tid))

    def step4(self, answer: str = "label") -> None:
        """Step 4's one AskUserQuestion (its JSON block, the task id bound), answered as `answer` says; the
        orchestrator does nothing with the answer."""
        tin = self.rating_input()
        q = tin["questions"][0]
        labels = [opt["label"] for opt in q["options"]]

        def perform():
            if answer == "decline":
                raise RuntimeError("User declined to answer questions")
            base = {"questions": tin["questions"]}
            if answer == "skip":
                return dict(base, answers={})
            if answer == "afk":
                return dict(base, answers={}, afkTimeoutMs=60000)
            if answer == "free":
                return dict(base, answers={q["question"]: "it mostly worked"}, response="it mostly worked")
            pick = next((l for l in labels if l.startswith(answer + " ")), labels[0])
            return dict(base, answers={q["question"]: pick})
        lab = self.label("Step 4 AskUserQuestion")
        c = self.o.s.tool("AskUserQuestion", tin, perform=perform, label=lab, deviation=self.devs.at(lab))
        self.asked.append((self.tid, answer))
        fact(self.rp, "close Step 4", {"task": "<task>", "header": q.get("header"), "labels": labels,
                                        "multiSelect": q.get("multiSelect"), "source": (tin.get("metadata") or {}).get("source"),
                                        "answer": answer, "ok": c.ok, "blocked": c.blocked})

    # ------------------------------------------------------------ one close, Steps 0-4
    def body(self) -> str:
        o = self.o
        self.resolve_task()
        if not (self.late_repair() if self.late else self.step0()):
            return ""
        self.cp_state()
        o.advance(label=self.label("TodoWrite Step 0 done, Step 1 in_progress"))
        self.step1()
        o.advance(label=self.label("TodoWrite Step 1 done, Step 2 in_progress"))
        last = self.step2()
        if not last:
            return ""
        o.advance(label=self.label("TodoWrite Step 2 done, Step 3 in_progress"))
        self.step3(last)
        o.advance(label=self.label("TodoWrite Step 3 done, Step 4 in_progress"))
        if self.landed:
            self.step4(self.ratings[0])
        o.advance(label=self.label("TodoWrite Step 4 done"))
        return last

    def steps_1_2(self) -> str:
        """close.md Steps 1-2 for a task whose disposition passed (the chain Step 0's call printed bound):
        what /commit runs for a close-stage gap."""
        self.step1()
        return self.step2()

    def run(self) -> str:
        self.start(f"--late-repair {self.tid}" if self.late else f"--codex {self.tid}" if self.codex
                   else self.typed or self.tid)
        if self.typed:
            self.resolve_typed()
        last = self.body()
        self.outcome = last or ("stalled at Step 0 (the line above)" if self.stalled else "")
        ev = self.o.s.stop(f"/close {self.tid}: {self.outcome}", label="/close Stop",
                           deviation=self.devs.at("/close Stop"))
        report_last, n = self.report_form()
        # /close's terminal form (P1c's suite): the report's last non-empty line is the disclosures form when
        # routing completed a repair (<n> its `## Disclosures` lines), else the plain form.
        form = f"CLOSE: YES - with disclosures: {len(self.repairs)} items" if self.repairs else self.yes_plain
        ok = report_last == form and n == len(self.repairs)
        self.rp.terminal("close", (last or "").startswith("CLOSE: YES") and ok, ev, task=self.tid,
                         last_line=last, report_last_line=report_last, disclosures=n, repairs=len(self.routed))
        if self.codex:
            self.codex.finish()
        return last

    def report_form(self) -> tuple:
        """The close report's last non-empty line and the line count of its last `## Disclosures` section."""
        with self.rp.acting("driver"):
            try:
                with open(os.path.join(self.o.project, self.report_rel())) as fh:
                    text = fh.read()
            except OSError:
                return "", 0
        lines = text.split("\n")
        last = next((l for l in reversed(lines) if l.strip()), "")
        at = max((k for k, l in enumerate(lines) if l.strip() == "## Disclosures"), default=None)
        n = 0
        while at is not None and at + 1 + n < len(lines) and lines[at + 1 + n].strip() \
                and not lines[at + 1 + n].startswith(("#", "CLOSE")):
            n += 1
        return last, n

    def run_noba(self) -> None:
        """Finding 1 (D8): Step 0 names BA's missing ticket in a /close span whose task has dispatch records of
        an earlier /close but no /dev span left. Each gap goes to the reader as Routes says; one it names no
        owner for is Routes' last bullet: one owner question (header Request), the owner's decision, where the
        turn ends; nothing here writes BA's artifact."""
        o = self.o
        self.start(self.tid)
        out = self.disposition("Step 0")
        fact(self.rp, "close Step 0", {"label": "Step 0", "disposition": out["disposition"],
                                        "gaps": [(g["artifact"], g["problem"]) for g in out["gaps"]],
                                        "mode": (out["chain"] or {}).get("mode")})
        for art in dict.fromkeys(g["artifact"] for g in out["gaps"]):
            if self.reader(art, "Step 0 round 1") is not None:
                self.route_path(art, "the artifact Step 0 names", "Step 0 round 1 routed")
                continue
            q = {"question": f"Task {self.tid}: no dispatch or request exists to re-run for {art}. "
                             "What should the cycle deliver?",
                 "header": "Request", "multiSelect": False,
                 "options": [{"label": "The user requirement",
                              "description": "the request the task's user-requirement file states"},
                             {"label": "/close --auto", "description": "the other close_pending tasks"}]}
            lab = self.label("Step 0 AskUserQuestion Request")
            c = o.s.tool("AskUserQuestion", {"questions": [q]}, label=lab, deviation=self.devs.at(lab))
            fact(self.rp, "close Request question", {"artifact": art.replace(self.tid, "<task>"), "header": "Request",
                                                      "ok": c.ok, "blocked": c.blocked})
            o.s.end("other", label="/close interrupted at the Request question")
            return

    # ------------------------------------------------------------ --auto
    def mode_question(self, extra: str) -> str:
        """The --auto illegal combination (`--auto <extra>`): one AskUserQuestion, header Close mode."""
        tin = {"questions": [{"question": f"/close --auto cannot take {extra}. Which close should run?",
                              "header": "Close mode", "multiSelect": False,
                              "options": [{"label": "/close --auto", "description": "every close_pending parent"},
                                          {"label": f"/close {extra}", "description": "this task only"}]}]}
        lab = "/close --auto AskUserQuestion Close mode"
        c = self.o.s.tool("AskUserQuestion", tin, label=lab, deviation=self.devs.at(lab))
        ans = (c.response.get("answers") or {}).get(tin["questions"][0]["question"], "") if c.ok else ""
        fact(self.rp, "close --auto mode question", {"header": "Close mode", "answer": ans.replace(extra, "<task>"),
                                                      "ok": c.ok, "blocked": c.blocked})
        return ans

    def run_auto(self, extra: str = "") -> list:
        o = self.o
        self.start(f"--auto {extra}".strip())
        if extra:
            self.mode_question(extra)
        disc = o.block("`--auto` mode", lang="bash", index=0)
        c = self.run_text(disc, "/close --auto Bash discovery", "Discover the close_pending parents")
        skipped = [l for l in ((c.response.get("stderr") or "") if c.ok else (c.error or "")).splitlines()
                   if ": skipped: " in l]
        fact(self.rp, "close --auto skipped", skipped)
        # each stdout line's first word is a parent's task-id (the text's own reading of the call)
        lines = ((c.response.get("stdout") or "") if c.ok else "").splitlines()
        parents = [line.split()[0] for line in lines if line.strip()]
        fact(self.rp, "close --auto parents", len(parents))
        states = []
        for tid in parents:
            st = self.state()
            st.update(tid=tid, producer=self.producers.get(tid, self.producer), chain={}, spec_id="", session_id="",
                      files=[], inspector_reports=[], round=0, repairs=[], routed=[], verdicts=[], outcome="",
                      landed=False, do_report=None)
            states.append(st)

        def each(fn):
            for k, st in enumerate(states):
                self.use(st)
                fn(k)
                states[k] = self.state()

        def step0(k):
            self.resolve_task()
            if not self.step0():
                raise agents.PlayError(f"Step 0 stalled for {self.tid}")
            self.cp_state()
        each(step0)
        o.advance(label="/close --auto TodoWrite Step 0 done, Step 1 in_progress")
        each(lambda k: self.step1())
        o.advance(label="/close --auto TodoWrite Step 1 done, Step 2 in_progress")
        lasts = {}
        each(lambda k: lasts.__setitem__(k, self.step2()))
        o.advance(label="/close --auto TodoWrite Step 2 done, Step 3 in_progress")
        each(lambda k: self.step3(lasts[k]))
        o.s.say("\n".join([f"{st['tid']}: {st['outcome']}" for st in states] + skipped) or "no close_pending parent")
        o.advance(label="/close --auto TodoWrite Step 3 done, Step 4 in_progress")
        each(lambda k: self.step4(self.ratings[k % len(self.ratings)]) if self.landed else None)
        o.advance(label="/close --auto TodoWrite Step 4 done")
        results = [(st["tid"], st["outcome"]) for st in states]
        self.outcome = "; ".join(f"{t}: {oc}" for t, oc in results)
        ev = o.s.stop(f"/close --auto: {self.outcome}", label="/close Stop", deviation=self.devs.at("/close Stop"))
        self.rp.terminal("close", bool(results) and all(oc.startswith("CLOSE: YES") for _, oc in results), ev,
                         outcome=self.outcome)
        return results


CLOSE_FINDINGS_ONE = "CLOSE_FINDINGS: 1 items"
# The first close-QA round's finding, per variant: on the lane dev's own file (append); on a product file no
# dispatch of the task wrote (stray); citing no artifact (noart).
FIRSTS = {
    "append": FINDING,
    "stray": {"path": "README.md", "detail": "README.md says nothing of add()'s TypeError (AC-01's behaviour)"},
    "noart": {"path": None, "detail": "AC-01's behaviour is undocumented"},
}
# What the round's own QA dispatch, run again, names (the artifact a finding concerns).
NAMED = {
    "stray": {"path": "docs/dev/dev-report-<task>.json",
              "detail": "the dev work leaves add()'s TypeError undocumented (toy/__init__.py)"},
    "noart": FINDING,
}


# ---------------------------------------------------------------- composition

class _Interrupted(Exception):
    pass


def dev_cycle(rp, after: str, scenario=None, stop_before: int | None = None):
    """Run the cycle /close follows; returns (producer, task id, its session, the cycle object). With
    `stop_before`, the session is interrupted before that step of /dev (no Stop: an interrupt)."""
    if after == "dev-command":
        try:
            from . import dev_command as dcdrv  # another lane's driver
        except ImportError as e:
            raise RuntimeError("drivers/dev_command.py does not exist yet: the /dev-command scenario is not run") from e
        cyc = dcdrv.DevCommandCycle(rp, rp.args.get("cycle_variant", "plain"))
        cyc.run()
        return DevProducer(cyc), cyc.tid, cyc.o.s, cyc
    from . import dev as devdrv
    cv = rp.args.get("cycle_variant", "plain")
    if cv.startswith("fanout"):
        cyc = devdrv.FanoutCycle(rp, cv, rp.args.get("tier", "STANDARD"), int(rp.args.get("lanes", "2")),
                                 rp.args.get("lane_id", "text"))
    else:
        kw = {"scenario": scenario} if scenario is not None else {}
        cyc = devdrv.DevCycle(rp, cv, rp.args.get("tier", "STANDARD"), **kw)
    if stop_before:
        to = cyc.to

        def interrupted(n, *a, **k):
            if n == stop_before:
                raise _Interrupted
            return to(n, *a, **k)
        cyc.to = interrupted
        try:
            cyc.run()
        except _Interrupted:
            fact(rp, "/dev interrupted", {"before": f"Step {stop_before}"})
    else:
        from ..recovery import SessionCut
        try:
            cyc.run()
        except SessionCut:  # F8q: the cycle's session cut (fault cut@<a main-agent step>); the owner types /close
            cyc.cut = True
    return DevProducer(cyc), cyc.tid, cyc.o.s, cyc


def kept_only(rp, devs: Deviations) -> Deviations:
    """On a tree other than the base, `--arg kept=<JSON [hook, step, text] list>` (the base kit's replay's
    blocks) makes each deviation pass only a kept base block (drivers/dev.py KeptOnly)."""
    from .dev import KeptOnly
    if not rp.args.get("kept") or isinstance(devs, KeptOnly):
        return devs
    return KeptOnly(Deviations(devs.pairs), json.loads(rp.args["kept"]))


def remove(rp, rels) -> None:
    """The fault between commands (D25 (2) F8, F8c): an artifact removed after the command before reached
    its terminal; recorded in faults.json."""
    from ..faults import _record
    with rp.acting("fault"):
        for rel in rels:
            os.remove(os.path.join(rp.layout.project, rel))
    for rel in rels:
        _record(rp, {"kind": "remove", "path": rel, "after": rp.terminals[-1]["pipeline"] if rp.terminals else None,
                     "events_before": rp.n_events})


def damage(rp, cyc) -> dict:
    """The fault between commands (D25 (2) F8p): the product file one lane's dev wrote (a fan-out cycle's last
    lane's, else the cycle's own) put back to an incomplete fix that fails its acceptance criterion; recorded in
    faults.json. Returns close QA's finding on it, with the text its writer restores."""
    from ..faults import _record
    sc = (getattr(cyc, "lanes", None) or [cyc])[-1].sc
    with rp.acting("fault"):
        with open(os.path.join(rp.layout.project, sc.rel), "w") as fh:
            fh.write(sc.partial)
    _record(rp, {"kind": "break", "path": sc.rel, "after": rp.terminals[-1]["pipeline"] if rp.terminals else None,
                 "events_before": rp.n_events})
    return {"path": sc.rel, "detail": f"AC-01 fails: {sc.ac['then']} ({sc.rel} holds an incomplete fix)",
            "new": sc.final}


def plant_old_task(rp, tid: str) -> None:
    """Driver setup (finding 2): an old task docs/dev holds, its dev-report the cycle's with the old id, and no
    ticket, context, QA report or dispatch record."""
    with rp.acting("driver"):
        with open(os.path.join(rp.layout.project, f"docs/dev/dev-report-{tid}.json")) as fh:
            text = fh.read().replace(tid, OLD_TASK)
        with open(os.path.join(rp.layout.project, f"docs/dev/dev-report-{OLD_TASK}.json"), "w") as fh:
            fh.write(text)


def forget_session(rp, s) -> None:
    """Driver setup (finding 1): a session's transcript and its agents' gone from the project's store."""
    import shutil
    with rp.acting("driver"):
        os.remove(s.tpath)
        shutil.rmtree(os.path.join(s.tdir, s.sid), ignore_errors=True)


def break_resolver(rp) -> None:
    """Driver setup (acceptance 4 (k)): a syntax error in the sandbox copy's resolver, after the cycle."""
    with rp.acting("driver"):
        with open(os.path.join(rp.layout.harness, "scripts", "resolve-dev-artifact-chain.py"), "a") as fh:
            fh.write("\n)(  # the sandbox copy only: an unimportable resolver\n")


# The variants the artifact check replays (tests/artifact_graph/runtime.drivers reads VARIANTS); the
# acceptance variants of P4 run on demand only (`--arg variant=...`).
VARIANTS = ("plain", "route", "append", "auto")
ACCEPTANCE_VARIANTS = ("auto-task", "lane-qa", "stray", "noart", "stalled", "late-repair", "late-repair-drift",
                       "late-repair-declined", "auto-skip", "noba", "break")
OLD_TASK = "20250101-000001"  # auto-skip's old task: older than any session the store holds
# P1b's acceptance 7 names of three of those cases.
ALIASES = {"qa-never": "lane-qa", "noartifact": "noart", "unwritten": "stray"}


def lane_report(cyc, kind: str) -> str:
    """The report of `kind` (dev, qa) one lane of the cycle wrote: a fan-out cycle's first lane's, else the
    cycle's own (the singular cycle is one implicit lane)."""
    lanes = getattr(cyc, "lanes", None)
    return f"docs/dev/{kind}-report-{lanes[0].tid if lanes else cyc.tid}.json"


def removed_after_cycle(variant: str, cyc) -> list:
    """The artifacts a variant removes after the cycle reached its terminal: the lane qa-report (route, F8:
    a fan-out cycle's first lane's, lane_report; and the QA-only gap late-repair init declines); BA's whole
    stage, its ticket, context and acceptance criteria (the stage gaps late-repair init admits; BA, dispatched
    again, writes each of its declared artifacts afresh)."""
    tid = cyc.tid
    return {"route": [lane_report(cyc, "qa")],
            "late-repair-declined": [f"docs/dev/qa-report-{tid}.json"],
            "late-repair": [f"docs/dev/ticket-{tid}.md", f"docs/dev/context-{tid}.json",
                            f"docs/dev/acceptance-criteria-{tid}.json"]}.get(variant.replace("-drift", ""), [])


def pipeline_name(after: str, rp) -> str:
    cv = rp.args.get("cycle_variant", "plain")
    if cv.startswith("fanout") and rp.args.get("lanes", "2") != "2":
        cv += "-" + rp.args["lanes"]
    return after + (f"/{cv}" if cv != "plain" else "")


def run(rp) -> None:
    after = rp.args.get("after", "dev")
    variant = ALIASES.get(rp.args.get("variant", "plain"), rp.args.get("variant", "plain"))
    if variant not in VARIANTS + ACCEPTANCE_VARIANTS + CODEX_VARIANTS:
        raise ValueError(f"unknown variant {variant!r}")
    codex = None
    if variant in CODEX_VARIANTS:
        # The text's rules first, before any pipeline runs: a text without them (or at odds with the scripted
        # run) stops the replay here, naming the sentence.
        codex = (_codex.close_rules(rp), CODEX_SCRIPTS[variant])
        _codex.check_script(*codex)
        fact(rp, "codex rules", codex[0].to_fact())
    session_kind = rp.args.get("session", "same" if variant == "plain" else "later")
    rp.pipeline = (pipeline_name(after, rp) + "+close" + (f"/{variant}" if variant != "plain" else "")
                   + ("/later" if session_kind == "later" else ""))
    producer, tid, s, cyc = dev_cycle(rp, after, stop_before=13 if variant == "lane-qa" else None)
    end = "prompt_input_exit"
    if getattr(cyc, "cut", False):  # F8q: /close is typed in a later session, in place of /restart
        session_kind, end = "later", "other"
    producers = {tid: producer}
    if variant == "auto" and int(rp.args.get("parents", "1")) > 1:
        from . import dev as devdrv
        p2, tid2, s, _cyc2 = dev_cycle(rp, after, scenario=devdrv.SCENARIO_SUB)
        producers[tid2] = p2
    remove(rp, [p for p in removed_after_cycle(variant, cyc) if os.path.exists(os.path.join(rp.layout.project, p))])
    if variant == "stalled":
        break_resolver(rp)
    if variant == "auto-skip":
        plant_old_task(rp, tid)
    broken = damage(rp, cyc) if variant == "break" else None
    if variant == "noba":  # /close once along route: its QA dispatched again from /close's own span
        remove(rp, removed_after_cycle("route", cyc))
        first = CloseRun(rp, rp.later_session(s, end), tid, producer=producer, variant="route")
        first.run()
        forget_session(rp, s)  # the /dev session gone from the store (cleaned up, or another account's)
        remove(rp, [f"docs/dev/ticket-{tid}.md"])
        CloseRun(rp, rp.later_session(first.o.s), tid, producer=producer, variant="noba").run_noba()
        return
    session = rp.later_session(s, end) if session_kind == "later" else s
    cr = CloseRun(rp, session, tid, producer=producer, variant=variant, auto=variant.startswith("auto"),
                  producers=producers, codex=codex)
    cr.broken = broken
    if variant in ("auto", "auto-skip"):
        cr.run_auto()
    elif variant == "auto-task":
        cr.run_auto(extra=tid)
    else:
        cr.run()
