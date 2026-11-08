"""/close, played compliantly from commands/close.md of the tree under test, after /dev
(drivers/dev.py), after /do (drivers/do.py) or after /dev-command (drivers/dev_command.py, when
that driver exists).

The main agent types `/close <task-id>` (or `/close --auto`), passes the checklist the hook hands
it (scripts/todo/close.py) to its first TodoWrite and completes one step per TodoWrite call. What
each step does is read from the tree's own text at run time:

* Task-id resolution: the timestamp argument binds TASK_ID; on the /do path the do-report the text
  names is found (Glob) and Read, and DO_REPORT is bound.
* Step 0 (the /dev path): the step's Bash block, preceded by the late-repair section's selector
  array precompute (`LATE_REPAIR_SELECTOR_ARGS=()...`, the inline code that section tells Step 0
  to append) and by the routing helpers' function definitions when the block calls one (the text
  defines them "once"; every Bash call is a new shell). A non-zero ROUTE_SELECT_RC is worked as the
  "Resolver-error routing rule" says: one finding per element of the chain's errors[] (recorded by
  the block itself where the text's block makes the rule's close_route_finding calls, else by one
  Bash call of the text's helper), routed (below) and the same block re-run as the source_check.
* The do-report lite preflight (the /do path): the DO_STATUS block where the text has one; on a
  text that runs the Artifact schema gate over $DO_REPORT, that gate's block with $DO_REPORT as
  its sole argument, as the text says.
* The base text's Artifact schema gate over the chain's report_paths, where the text has one; the
  optional cp-state handoff (the spec resolver only when a spec_path is found; a Glob for
  .claude/specs/<TASK_ID>/cp-state-qa.json).
* Step 1: the cycle-diff file list (the canonical report's dev.files_modified, Read; or the
  do-report's do.files_modified), the registry name where the text prints it with a call, and
  the three inspectors of the branch the chain's mode selects, each prompt built from its bullet
  (FIRST ACTION line, obligation, `--changed-files`, report path); each inspector played from its
  agent file (agents.Player: FIRST ACTION Read, the changed files Read, the Standard 6 scan of the
  prompt directories where its text keeps that exception, its report from the obligation and the
  schema, its `STATUS: complete` line). The base text's orchestrator re-validation of the three
  reports (contract_runtime.validate_artifact_for_obligation, as it names) where the text has it.
* Step 2: the SESSION_ID block; the base text's QA-arming rule (its three scripts, in order); one
  close-QA dispatch per judging round from the step's prompt block (placeholders the orchestrator
  substitutes bound, the SECOND ACTION line left out with SPEC_ID empty, the Input artifacts
  bullets filled from the retained chain or the do-report, an "otherwise omit" bullet left out;
  QA's own instruction placeholders left as written; a `Completed repairs` input, where the text
  has one, the routing loop's completed repairs of this /close). QA reads its inputs and the cycle
  diff, runs each acceptance criterion's own check that names a call (one per lane; a failing one
  is its round's finding on that file) and writes the close-report: a first report with the
  Player, a later round's section appended through the append helper the Overwrite policy names
  (its call as the text spells it, the section written first to QA's scratch directory); its
  `## Disclosures` lines are its `Completed repairs` input (on a text without one, the repairs of
  this /close's earlier rounds, which the report's earlier sections show).
* A round-open return is echoed and routed (the Routing loop): each finding is recorded with the
  text's own `close_route_finding`, its owner found as the tree's text says, dispatched again
  scoped to the finding, the source_check re-run and the progress measured with `close_progress`
  (a fresh QA round after a close-QA finding; on a text that measures it only when the re-check
  still fails, only then). On a text with the declaring-dispatch reader
  (hooks/lib/obligation.py declaring-dispatch: its own Bash call with the path for `<path>`, or a
  helper function that runs it) the reader is run on the path and its answer acted on as the text
  lists: a `dispatch`, `lane` or `writer` answer runs that dispatch again (its recorded prompt, a
  fresh dispatched_at); a `todo_step` with a template is a fresh dispatch of its role from the
  cycle command's template, under the task id the template's artifacts carry (a fan-out lane's
  dispatch with its lane fields); a `todo_step` with neither template nor subagent call is the main
  agent's own step (own_work: the cycle's `Step N` run in the /close session where the artifact is
  missing). On a role-table text (`close_artifact_role`) the role the table
  prints is dispatched again from the cycle command's template for that role (the checklist step
  that calls it), a product file going through the dev report that claims it, as that text routes
  dev work; its `orchestrator` row is the main agent's own work (own_work: the errors the chain
  names on an artifact it wrote, fixed in one Edit, as the orchestrator gate allows one Edit per
  turn). Once a re-run of an entry's source_check passes, the later entries of that check are
  closed with it. Step 0 never proceeds on a failing chain (the driver stops after its rounds).
* Step 3: the verdict echo; the scoring helper and its score-update calls; the Session Summary
  and the rating block (no rating is chosen: the turn ends there); the workflow update the text
  names (/spec-update --temp where the base text asks for it, played as spec-update.md's
  Temp-note mode); Stop.
* `--auto`: the flag check, the discovery block, and each discovered parent walked through Steps
  0-3 (on a text whose discovery line carries the parent's chain, Step 0 takes it with
  ROUTE_SELECT_RC=0 in place of its selector call), the outcome classified, the batch summary.

Driver arguments (cli.py --arg K=V), when run on its own (`--driver close`):
  after=dev|dev-command   the cycle closed (default dev; /do is drivers/do.py)
  cycle_variant=V         drivers/dev.py's variant of that cycle (default plain; fanout and
                          fanout-qa-fail run the fan-out cycle with lanes=N lanes)
  variant=plain           close QA lands CLOSE: YES in its first round (default)
  variant=route           the lane QA report (a fan-out cycle's first lane's) is removed after the
                          cycle's terminal; Step 0's chain call reports it, it is routed and its
                          producer dispatched again (F8)
  variant=break           the product file the cycle's last lane's dev wrote is put back to an
                          incomplete fix after the cycle's terminal; close QA's own run of its
                          acceptance criterion's check names it, its writer is dispatched again and a
                          fresh round re-judges (F8p)
  variant=append          close QA's first round opens a finding on the product file the lane's
                          dev wrote; dev is dispatched again; the fresh round appends its section
                          through the append helper and lands CLOSE: YES
  variant=auto            `/close --auto` (the cycle's task discovered as close_pending)
  session=same|later      /close typed in the /dev's session or a later one (default same for
                          plain, later for every other variant, as acceptance 7 types them)
  fault=cut@<step glob>   (tests/replay/recovery.py) the cycle's session cut before a main-agent
                          step (`Step 13 [[]l2] Agent(qa)`): /close is typed in a later session,
                          in place of /restart (F8q)

Acceptance 7's other routing cases, run by name (`--arg variant=<name>`); the artifact check's job
list (tests/artifact_graph/runtime.py drivers(): the `variant=` lines above) leaves them out:
  qa-never                the /dev turn is interrupted after Step 12 (drivers/dev.py variant=qa-never):
                          the lane QA was never dispatched; Step 0's chain call reports it, the reader
                          returns the canonical todo step and its role is dispatched from the cycle's
                          template; a gap on the completion report is /dev Step 17, the main agent's
                          own, which /close's main agent runs itself (acceptance 7's second case)
  noartifact              close QA's first round raises a finding that cites no artifact: the entry's
                          path is that round's own report, the reader returns that round's QA dispatch,
                          which runs again and names the product file; its writer runs again and a
                          fresh round lands CLOSE: YES (acceptance 7's fifth case)
  unwritten               close QA's first round names only a product file no dispatch of the task
                          wrote (toy/util.py): the reader names no owner, the entry's path becomes the
                          round's own report, its QA dispatch runs again and names the cycle's dev
                          report, whose declaring dev dispatch runs again, and a fresh round lands
                          CLOSE: YES (acceptance 7's sixth case)
  late-repair             the ticket and context are removed after the cycle's terminal and
                          `/close --late-repair <task-id>` is typed: the late-repair route (selector,
                          BA, dev and QA dispatched again with record-stage after each, finalize,
                          verify-disclosure), then Steps 1-3 (acceptance 7's late-repair case)

The terminal: Stop with no block, and the close report's last non-empty line exactly
`CLOSE: YES - with disclosures: <n> items` (<n> its last `## Disclosures` section's lines, at least
one) when the routing loop completed a repair, else exactly `CLOSE: YES — codex disabled by user`.

Respellings (P1b Scope row 7), driver only, each application recorded in blocks.json: see
RESPELLINGS (base-text paths that do not resolve in a product repository, and the base text's
QA-arming scripts with CLAUDE_PROJECT_DIR set in their environment).

Deviations: none. DEVIATIONS stays empty: a compliant run meets no block, and none passes one.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shlex

from .. import agents, cmdtext, roles
from ..pipeline import Deviations, Orchestrator, Respelling, parse_declare, utc_now

PIPELINE = "close"
# The artifact check's cost of each variant (tests/artifact_graph/shards.py balances its CI shards by it):
# CPU seconds of the shipped and armed traced replays and their differential runs, measured at b8e34f4
COST = {"plain": 448, "route": 485, "append": 530, "auto": 462}

PROJECT_ROOT_PREFIX = 'CLAUDE_PROJECT_DIR="${PROJECT_ROOT:-$(git rev-parse --show-toplevel)}" '
RESPELLINGS = [
    Respelling("C1 selector", r"(?<![\w/~.-])python3 scripts/close-route-select\.py",
               "python3 ~/.claude/scripts/close-route-select.py", "commands/close.md Step 0 (:345 at 2acc29b)"),
    # Step 0's aggregator re-run (close.md:338 at 2acc29b): the path, and CLAUDE_PROJECT_DIR exported
    # for it (an env prefix inside `$(cd ... && ...)` is itself refused as a dynamic command head).
    Respelling("C2 aggregator", r"(?<![\w/~.-])python3 scripts/aggregate-dev-report\.py",
               "python3 ~/.claude/scripts/aggregate-dev-report.py", "commands/close.md Step 0 (:338 at 2acc29b)"),
    Respelling("C2 aggregator root",
               r'(?m)^PROJECT_ROOT="\$\{CLAUDE_PROJECT_DIR:-\$\(pwd\)\}"\n(?=source ~/\.claude/venv/bin/activate[^\n]*\nif ! AGGREGATE_RESULT)',
               'PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"\nexport CLAUDE_PROJECT_DIR="$PROJECT_ROOT"\n',
               "commands/close.md Step 0 (:338 at 2acc29b)"),
    Respelling("C3 append helper", r'python3 "\$PROJECT_ROOT/scripts/close-report-append\.py"',
               "python3 ~/.claude/scripts/close-report-append.py", "commands/close.md Step 2 (:776 at 2acc29b)"),
    Respelling("C4 discovery", r"(?<![\w/~.-])python3 scripts/dev-lifecycle\.py",
               "python3 ~/.claude/scripts/dev-lifecycle.py", "commands/close.md --auto (:950 at 2acc29b)"),
    # The QA-arming rule's three scripts (close.md:246-249 at 2acc29b, deleted on the branch): named
    # by their repository path in prose; run as the harness's copy with `bash`, CLAUDE_PROJECT_DIR set.
    Respelling("C6 QA arming", r"(?m)^(?:bash )?(?:~/\.claude/)?scripts/(write-[\w-]+\.sh)",
               PROJECT_ROOT_PREFIX + r"bash ~/.claude/scripts/\1", "commands/close.md QA-arming rule (:246-249 at 2acc29b)"),
    # The late-repair route's controller calls (close.md:141-143 at 2acc29b): named by their repository path,
    # without the --task-id and --project-dir its argparse requires (late-repair-controller.py build_parser).
    Respelling("C7 late-repair controller",
               r"(?<![\w/~.-])scripts/late-repair-controller\.py (record-stage|finalize|verify-disclosure)(?! --task-id)",
               r'python3 ~/.claude/scripts/late-repair-controller.py \1 --task-id "$TASK_ID" --project-dir "$PROJECT_ROOT"',
               "commands/close.md Late-repair route (:141-143 at 2acc29b)"),
]

# Blocks the replays meet: none (a compliant run needs no deviation).
DEVIATIONS = Deviations([])

CLOSE_YES_PLAIN = "CLOSE: YES — codex disabled by user"
FINDING = {"path": "toy/__init__.py", "detail": "add() states no contract: its docstring does not say it raises "
                                                "TypeError naming a non-number argument (AC-01's behaviour is undocumented)"}
TOY_DOC = ('    """Return a + b; raise TypeError naming the argument that is not a number."""\n')
# Acceptance 7's fifth case: a close-QA finding that cites no artifact.
FINDING_NO_ARTIFACT = {"path": "", "detail": "the behaviour change is undocumented: nothing the cycle delivered states "
                                             "that a non-number argument raises TypeError naming it"}
# Acceptance 7's sixth case: a finding whose only path is a product file no dispatch of the task wrote.
FINDING_UNWRITTEN = {"path": "toy/util.py", "detail": "sub() still accepts a non-number: toy's other arithmetic "
                                                      "helper lacks the argument check the cycle added to add()"}
UTIL_OLD = "def sub(a,b): return a-b\n"
UTIL_NEW = ("def sub(a, b):\n    for name, x in ((\"a\", a), (\"b\", b)):\n"
            "        if not isinstance(x, (int, float)):\n"
            "            raise TypeError(f\"sub(): argument {name} must be a number\")\n    return a - b\n")


def _sha(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:16]
    except OSError:
        return "absent"


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
    out = {k: ans.get(k) for k in ("source", "role", "subagent_type", "task_id", "lane", "step", "command",
                                   "session_id", "tool_use_id", "subagent_call", "template") if k in ans}
    if session is not None and ans.get("session_id"):
        out["dispatched_in"] = "this session" if ans["session_id"] == getattr(session, "sid", None) else "an earlier session"
    if isinstance(ans.get("template"), dict):
        out["template_role"] = ans["template"].get("role")
    return out


def _declares(ans, rel: str) -> bool:
    """The answer's obligation declares `rel`."""
    ob = (ans or {}).get("obligation") or {}
    return any(isinstance(a, dict) and a.get("path") == rel for a in ob.get("artifacts") or [])


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
    """The reader's answer acted on as the routing text says: a declaring, lane or writing dispatch runs again
    (the same subagent_type and obligation, a fresh dispatched_at, scoped to the finding); a canonical todo
    step with a template is a fresh dispatch of its role from the cycle's template. (dispatch, role)."""
    o = run.o
    if (isinstance(ans, dict) and ans.get("source") == "dispatch" and ans.get("prompt") and hasattr(run, "rerun_close_qa")
            and _declares(ans, run.report_rel())):
        # The round's own report: "that round's QA dispatch runs again and names an artifact".
        return run.rerun_close_qa(ans, path, detail, label), "qa"
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
        # "a fresh dispatch of its role under the same task id from that template": the id the template's
        # artifacts carry (a lane's, in a fan-out cycle)
        role = call["subagent_type"]
        tid = next((a.get("identity", {}).get("task_id") for a in (ans.get("template") or {}).get("artifacts") or []
                    if isinstance(a, dict) and a.get("identity", {}).get("task_id")), None)
        return run.producer.dispatch(role, o.s, run.devs, run.label(f"{label} Agent({role})"),
                                     note=f"{path}: {detail}", edits=edits, task_id=tid), role
    if isinstance(ans, dict) and ans.get("source") == "todo_step" and not call and not ans.get("template"):
        # "with none, the step is the main agent's own: run it yourself under the same task id"
        # A step of the cycle's own command (/dev Step 17, the completion report) is that command's text, run here.
        return own_work(run, path, detail, label, step=ans.get("step") if ans.get("command") != o.typed else None)
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


def own_work(run, path: str, detail: str, label: str, step: str | None = None):
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
    if getattr(run, "do_report", None) and path == run.do_report and run.producer is not None:
        # The base text's do-report lite preflight: "worked by the orchestrator row ...: it re-dispatches dev to
        # complete the /do work".
        return run.producer.dispatch("dev", o.s, run.devs, run.label(f"{label} Agent(dev)"),
                                     note=f"{path}: {detail}"), "dev"
    if not os.path.exists(target) and step and hasattr(run.producer, "own_step"):
        # the canonical todo step that owes the missing artifact, the main agent's own: it runs that step
        run.producer.own_step(step, o.s, run.devs, run.label(label))
        fact(run.rp, "own step", {"label": label, "path": path, "step": step, "written": os.path.exists(target)})
        return None, "main"
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

    def own_step(self, step: str, session, devs, label: str = "") -> None:
        """The main agent's own canonical step of the cycle (its `Step N`: the reader's todo_step with neither
        subagent call nor template), run in `session` by the asking command's main agent under the same task
        id; /dev Step 17, which writes the completion report, as the cycle's text spells it, its calls
        labelled with `label`."""
        n = int(re.match(r"Step (\d+)", step).group(1))
        with self.on(session, devs):
            if n == 17:
                self.cyc.step17(prefix=label)
            else:
                getattr(self.cyc, f"step{n}")()

    def dispatch(self, role: str, session, devs, label: str, note: str = "", edits=None, task_id=None):
        from . import dev as devdrv
        cyc = self.cyc
        with self.on(session, devs) as o, self.lane(task_id):
            extra = [f"Close routing finding: {note}"] if note else []
            if role == "ba" and hasattr(cyc, "dispatch_ba"):
                return cyc.dispatch_ba(f"Step {self.step_of('ba')}", label)
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
                return cyc._dispatch(fields, act, label, subagent_type="qa")
            if role == "dev":
                baseline = {"baseline_head_sha": o.values.get("baseline_head_sha", ""),
                            "baseline_dirty_snapshot": o.values.get("baseline_dirty_snapshot", "")}
                act = agents.Act(work=roles.dev(list(edits or [])), content={"*": baseline},
                                 summary="the close finding is fixed" if edits else "no change: the work is in place")
                return cyc._dispatch(fields, act, label, subagent_type="dev")
        raise NotImplementedError(f"no cycle template for role {role!r}")


class DoProducer:
    """A /do task: its only producer is the main agent's /do work; close.md routes an unfinished
    do-report to dev ("re-dispatches dev to complete the /do work"), which /do has no template for."""

    def __init__(self, turn):
        self.turn = turn
        self.tid = turn.tid

    def dispatch(self, role: str, session, devs, label: str, note: str = "", edits=None):
        """Dev dispatched again under the same task id to complete the /do work (close.md's do-report lite
        preflight: its own step on the branch, the orchestrator row at 2acc29b). /do has no dispatch template:
        the prompt states the task, the do-report and the finding; dev finishes the change, runs the tests
        and rewrites the do-report to `completed` (no /close orchestrator writes it)."""
        if role != "dev":
            raise NotImplementedError(f"/do has no dispatch template for role {role!r} ({note})")
        turn = self.turn
        project = turn.o.project
        report = os.path.join(project, turn.report_rel)
        try:
            doc = json.loads(agents.peek(turn.rp, "main", report))
        except (OSError, ValueError):
            doc = {}
        do = doc.get("do") or {}
        prompt = (f"Task-id: {self.tid}\n"
                  f"Complete the /do work of this task under the same task id: {turn.task}.\n"
                  f"Do-report: {turn.report_rel}\n"
                  f"It records the work unfinished (do.status '{do.get('status')}': {do.get('summary')}). Make the "
                  "change, run the project's tests, then rewrite the do-report with do.status \"completed\", "
                  "do.summary, and do.files_modified naming the files you changed.\n"
                  f"Close routing finding: {note}\n")

        def work(sub, brief, player):
            changed = []
            for rel, old, new in turn.edits:
                path = os.path.join(project, rel)
                sub.read(path, label=f"{sub.role} Read {rel}")
                if old in agents.peek(sub.rp, sub.role, path):
                    c = sub.edit(path, old, new, label=f"{sub.role} Edit {rel}")
                    if c.ok:
                        changed.append(rel)
                else:
                    changed.append(rel)  # already in place
            sub.bash("python3 -m pytest -q -p no:cacheprovider", "Run the toy tests", label=f"{sub.role} Bash pytest")
            cur = json.loads(agents.peek(sub.rp, sub.role, report))
            cur.setdefault("do", {}).update(status="completed", files_modified=sorted(set(
                list(cur["do"].get("files_modified") or []) + changed)),
                summary="toy.add now raises TypeError naming the argument that is not a number "
                        "(completed by dev, dispatched again from /close).")
            agents.put(sub, report, json.dumps(cur, indent=2) + "\n", f"{sub.role} Write {turn.report_rel}")
            return None

        act = agents.Act(work=work, summary="the /do work is complete; the do-report is completed")
        player = agents.Player(turn.o.tree, prompt, act, role="dev")
        return session.dispatch("dev", prompt, description="dev", body=player.body, result=player.final,
                                label=label, deviation=devs.at(label))


# ---------------------------------------------------------------- the close run

class CloseRun:
    def __init__(self, rp, session, tid: str, do_report: str | None = None, producer=None, variant: str = "plain",
                 auto: bool = False, extra_devs=()):
        self.rp, self.tid, self.do_report = rp, tid, do_report
        self.producer, self.variant, self.auto = producer, variant, auto
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
        self.routed: list = []         # every dispatch the routing loop made
        self.round_findings: list = []  # what the last close-QA round found
        self.verdicts: list = []       # (round, last line)
        self.findings_routed = 0
        self.helpers = self._helpers()
        self.outcome = ""

    # ------------------------------------------------------------ text helpers
    def _rules(self):
        return [
            (r"^(?:TASK_ID|task-id|task_id)$", lambda m: self.tid),
            (r"^SESSION_ID$", lambda m: self.session_id),
            (r"^cycle-diff-file-list$", lambda m: " ".join(self.files)),
            (r"^true\|false$", "false"),
        ]

    def _helpers(self) -> str:
        try:
            sec = self.o.section("Routing helpers")
        except cmdtext.TextNotFound:
            return ""
        bl = cmdtext.blocks(sec, None, "bash")
        return bl[0].text if bl else ""

    def routing_section(self) -> str:
        try:
            return self.o.section("Routing loop")
        except cmdtext.TextNotFound:
            return ""

    def with_helpers(self, text: str) -> str:
        """The definitions of the routing helpers a block calls, and of those they call, before it (the text
        defines them "once"; every Bash call is a new shell). Only the functions the call needs."""
        return with_functions(self.helpers, text)

    def label(self, text: str) -> str:
        return f"/close {text}"

    def run_text(self, text: str, label: str, desc: str, capture=(), rules=()):
        o = self.o
        left: list = []
        text = o.bind(text, list(rules), left)
        return run_captured(o, o.shell_bind(self.with_helpers(text)), desc, label, capture)

    def read(self, rel_or_abs: str, label: str):
        path = rel_or_abs if os.path.isabs(rel_or_abs) else os.path.join(self.o.project, rel_or_abs)
        return self.o.s.read(path, label=label, deviation=self.devs.at(label))

    def load(self, rel_or_abs: str):
        path = rel_or_abs if os.path.isabs(rel_or_abs) else os.path.join(self.o.project, rel_or_abs)
        return json.loads(agents.peek(self.rp, "main", path))

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

    # ------------------------------------------------------------ task-id resolution (the /do path)
    def resolve_task(self) -> None:
        o = self.o
        if not self.do_report:
            return
        g = o.s.tool("Glob", {"pattern": f"d*-report-{self.tid}.json", "path": os.path.join(o.project, "docs/dev")},
                     label=self.label("Task-id resolution Glob reports"),
                     deviation=self.devs.at(self.label("Task-id resolution Glob reports")))
        names = [os.path.basename(p) for p in (g.response.get("filenames") or [])] if g.ok else []
        if f"dev-report-{self.tid}.json" in names:
            self.do_report = None  # a canonical dev-report takes precedence (resolved as a dev chain)
            return
        self.read(self.do_report, self.label("Task-id resolution Read do-report"))
        o.values.update(DO_REPORT=self.do_report)

    # ------------------------------------------------------------ Step 0
    def step0_text(self, late: bool = False) -> str:
        o = self.o
        pre = next((c for c in cmdtext.inline_codes(o.text, "Late-repair route", "LATE_REPAIR_SELECTOR_ARGS=()")
                    if c.startswith("LATE_REPAIR_SELECTOR_ARGS=()")), "")
        return f"LATE_REPAIR={'true' if late else 'false'}\n" + pre + "\n" + o.block("Step 0", lang="bash", index=0)

    def step0_records(self) -> bool:
        """The text's Step 0 block records the Resolver-error routing rule's findings itself (its
        close_route_finding calls over the chain's errors[])."""
        block = self.o.block("Step 0", lang="bash", index=0)
        return "close_route_finding" in block and ".errors[]" in block

    def step0(self, label: str = "Step 0", late: bool = False) -> int:
        o = self.o
        caps = ("PROJECT_ROOT", "ROUTE_SELECT_RESULT", "ROUTE_SELECT_RC", "ARTIFACT_CHAIN", "CLOSE_CANONICAL_REPORT",
                "REQUIRED_ACTIONS_JSON", "AGGREGATE_RESULT", "LATE_REPAIR")
        self.run_text(self.step0_text(late), self.label(f"{label} Bash route select"), "Step 0: resolve the artifact chain",
                      capture=caps)
        try:
            self.chain = json.loads(o.values.get("ARTIFACT_CHAIN") or "{}")
        except ValueError:
            self.chain = {}
        try:
            rc = int(o.values.get("ROUTE_SELECT_RC") or 0)
        except ValueError:
            rc = 1
        fact(self.rp, "close Step 0", {"label": label, "route_select_rc": rc, "status": self.chain.get("status"),
                                        "mode": self.chain.get("mode"),
                                        "errors": [(e.get("code"), e.get("path")) for e in self.chain.get("errors") or []]})
        return rc

    def step0_loop(self, rounds: int = 3) -> None:
        """Step 0, and the Resolver-error routing rule's findings worked by the routing loop until the
        same source_check (the Step 0 block) passes."""
        rc = self.step0()
        k = 0
        pending = json.loads(self.o.values.get("REQUIRED_ACTIONS_JSON") or "[]") if self.o.values.get(
            "REQUIRED_ACTIONS_JSON") else []
        while (rc != 0 or pending) and k < rounds:
            k += 1
            errs = self.chain.get("errors") or []
            if rc != 0 and self.step0_records():
                # The text's Step 0 block makes the rule's close_route_finding calls itself, in its own Bash call.
                pending = json.loads(self.o.values.get("REQUIRED_ACTIONS_JSON") or "[]")
            elif rc != 0:
                # An element naming no path: the chain's dev report where the text says so, else $TASK_ID.
                default = (f"docs/dev/dev-report-{self.tid}.json" if "the chain's dev report" in self.o.section("Step 0")
                           else self.tid)
                found = [((e.get("path") or e.get("artifact") or default),
                          f"resolver reported {e.get('code') or 'an error'} (rc={rc})") for e in errs] or [
                    (default, f"close-route-select.py returned non-zero (rc={rc}) with no parseable errors[] "
                               "and LATE_REPAIR=false")]
                pending = self.record(found, "close-route-select.py", f"Step 0 round {k}")
            self.route(pending, f"Step 0 round {k}", recheck=lambda lab: self.step0(lab) == 0)
            pending = []
            rc = int(self.o.values.get("ROUTE_SELECT_RC") or 0)
        if rc != 0:
            # Step 0 never proceeds on a failing chain; the driver plays a bounded number of rounds.
            raise agents.PlayError(f"Step 0 still fails after {k} routing round(s): "
                                   f"{[(e.get('code'), e.get('path')) for e in self.chain.get('errors') or []]}")

    # ------------------------------------------------------------ the late-repair route
    def lr_code(self, verb: str) -> str:
        """The late-repair section's own spelling of a controller call (its first inline code naming the verb)."""
        sec = self.o.section("Late-repair route")
        for code in re.findall(r"`([^`]+)`", sec):
            if re.search(r"late-repair-controller\.py %s\b" % re.escape(verb), code):
                return code
        raise cmdtext.TextNotFound(f"the late-repair route names no {verb} call")

    def lr_run(self, verb: str, label: str, desc: str, binds: dict):
        """One controller call as the section spells it, its placeholders bound, its JSON line back."""
        code = self.lr_code(verb)
        for k, v in binds.items():
            code = code.replace(k, v)
        lab = self.label(label)
        code = self.o.respell(code, lab)
        c = self.run_text(code, lab, desc)
        out = (c.response.get("stdout") or "") if c.ok else (c.error or "")
        got = last_json(out) or {}
        fact(self.rp, f"late-repair {verb}", {"label": label, "ok": c.ok, "result": got})
        return got

    def lr_stage(self, stage: str) -> str:
        """One stage of the route, dispatched again from the cycle's template under the same task id; the
        path of its report (BA's context, the dev report, the QA report)."""
        o, tid = self.o, self.tid
        lab = self.label(f"Late-repair Agent({stage})")
        note = f"late repair: {stage} again against the current state of the work"
        self.producer.dispatch(stage, o.s, self.devs, lab, note=note)
        return {"ba": f"docs/dev/context-{tid}.json", "dev": f"docs/dev/dev-report-{tid}.json",
                "qa": f"docs/dev/qa-report-{tid}.json"}[stage]

    def late_repair(self) -> None:
        """`--late-repair`: Step 0's selector with the flag (init, the run record), BA then dev then QA dispatched
        again with `record-stage` after each, finalize (the canonical list's Step 0 where it has one), then
        verify-disclosure; admitted goes on to Step 1 as the normal path does."""
        o, tid = self.o, self.tid
        self.step0(late=True)
        try:
            sel = json.loads(o.values.get("ROUTE_SELECT_RESULT") or "{}")
        except ValueError:
            sel = {}
        fact(self.rp, "late-repair selector", {"outcome": sel.get("outcome"), "late_repair": sel.get("late_repair"),
                                               "route_select_rc": o.values.get("ROUTE_SELECT_RC")})
        if sel.get("outcome") not in ("initialized", "already_initialized"):
            raise agents.PlayError(f"the late-repair selector printed {sel.get('outcome')!r}")
        run_id = sel.get("repair_run_id") or ""
        for stage in ("ba", "dev", "qa"):
            rel = self.lr_stage(stage)
            self.lr_run("record-stage", f"Late-repair Bash record-stage {stage}", f"Record the {stage} stage",
                        {"<ba|dev|qa>": stage, "<path>": rel, "<id>": run_id})
        self.lr_run("finalize", "Step 0 Bash finalize" if self.o.todos and self.o.todos[0]["content"].startswith(
            "Step 0") else "Late-repair Bash finalize", "Finalize the late repair", {"<id>": run_id})
        if o.todos and o.todos[0]["content"].startswith("Step 0"):
            o.advance(label=self.label("TodoWrite Step 0 done, Step 1 in_progress"))
        got = self.lr_run("verify-disclosure", "Late-repair Bash verify-disclosure", "Verify the disclosure", {})
        blocks = {}
        with self.rp.acting("driver"):
            for rel in (f"docs/dev/ticket-{tid}.md", f"docs/dev/context-{tid}.json", f"docs/dev/dev-report-{tid}.json",
                        f"docs/dev/qa-report-{tid}.json"):
                try:
                    with open(os.path.join(o.project, rel)) as fh:
                        blocks[rel] = "retrospective_disclosure" in fh.read()
                except OSError:
                    blocks[rel] = "absent"
        fact(self.rp, "retrospective_disclosure block carried", blocks)
        if got.get("outcome") != "admitted":
            raise agents.PlayError(f"verify-disclosure printed {got}")

    # ------------------------------------------------------------ routing
    def record(self, found, source_check: str, label: str) -> list:
        """The findings recorded the way the text records one (its close_route_finding), entries back."""
        if not self.helpers or "close_route_finding" not in self.helpers:
            return [{"path": p, "detail": d, "source_check": source_check} for p, d in found]
        calls = "\n".join(f"close_route_finding {shlex.quote(p)} {shlex.quote(d)} {shlex.quote(source_check)}"
                          for p, d in found)
        c = self.run_text(f"REQUIRED_ACTIONS_JSON='[]'\n{calls}\nprintf '%s\\n' \"$REQUIRED_ACTIONS_JSON\"",
                          self.label(f"{label} Bash close_route_finding"), "Record the findings for the routing loop")
        try:
            got = json.loads((c.response.get("stdout") or "[]").strip().splitlines()[-1]) if c.ok else None
        except (ValueError, IndexError):
            got = None
        # A refused or failed call leaves the entries the main agent was building ({path, detail, source_check}).
        return got if isinstance(got, list) else [{"path": p, "detail": d, "source_check": source_check}
                                                  for p, d in found]

    def claiming_report(self, path: str) -> str:
        """The report that claims a product file (the role-table text routes dev work to the dev lane whose
        report claims it)."""
        if self.do_report:
            return self.do_report
        for rel in self.chain.get("report_paths") or []:
            if "dev-report" not in os.path.basename(rel):
                continue
            try:
                doc = self.load(rel)
            except (OSError, ValueError):
                continue
            if path in ((doc.get("dev") or {}).get("files_modified") or []):
                return rel
        return path

    def owner(self, e: dict, label: str) -> dict:
        """Who owes the entry's path, as the tree's text decides it: its reader function (declaring-dispatch),
        else its role table (the entry's producer_role, or the table function on the path)."""
        call = reader_call(self.helpers, self.routing_section(), e["path"])
        if call:
            cmd, fn = call
            c = self.run_text(cmd, self.label(f"{label} Bash {fn}"), "Who owes the artifact")
            ans = last_json(c.response.get("stdout") or "") if c.ok else None
            fact(self.rp, "owing dispatch", {"label": label, "path": e["path"],
                                             "answer": summarize_answer(ans, self.o.s)})
            return {"reader": True, "answer": ans}
        role = e.get("producer_role")
        if not role:
            table = role_function(self.helpers)
            if table:
                c = self.run_text(f"{table} {shlex.quote(e['path'])}", self.label(f"{label} Bash {table}"),
                                  "The producer of the implicated artifact")
                role = (c.response.get("stdout") or "").strip() if c.ok else "orchestrator"
        return {"reader": False, "role": role}

    def route(self, entries: list, label: str, recheck) -> None:
        """The Routing loop: per entry, its owner dispatched again (scoped to the finding); the source_check
        re-run and the progress measured with close_progress, after each entry, or, on a text that works the
        round's entries first, once per distinct source_check of the round."""
        o = self.o
        per_round = "once every entry of the round is dispatched" in " ".join(self.routing_section().split())
        passed_checks, worked = set(), []
        for e in entries:
            path, detail = e.get("path") or self.tid, e.get("detail") or ""
            if e.get("source_check") and e.get("source_check") in passed_checks:
                # an earlier entry's re-run of this same source_check passed: this finding is closed too
                fact(self.rp, "routing entry closed by an earlier re-check", {"label": label, "path": path,
                                                                              "detail": detail})
                continue
            target = os.path.join(o.project, path) if not os.path.isabs(path) else path
            before = _sha(target)
            fact(self.rp, "routing entry", {"label": label, "entry": {k: v for k, v in e.items() if k != "edits"}})
            own = self.owner(e, label)
            if (own["reader"] and own["answer"] is None and not self.do_report
                    and e.get("source_check") == "close QA round" and path != self.report_rel()):
                # "`null` otherwise, and a close-QA finding that cites no artifact: the entry's path becomes that
                # round's own report, docs/dev/close-report-$TASK_ID.md, with the finding's path and detail as
                # its detail; that round's QA dispatch runs again and names an artifact."
                detail, path = f"{path}: {detail}", self.report_rel()
                e = dict(e, path=path, detail=detail)
                target = os.path.join(o.project, path)
                before = _sha(target)
                own = self.owner(e, label)
            if self.do_report and path == self.do_report:
                # The do-report keeps the preflight's own step (the branch's text) or the orchestrator row
                # (2acc29b): dev dispatched again under the same task id to complete the /do work.
                d, role = (self.producer.dispatch("dev", o.s, self.devs, self.label(f"{label} Agent(dev)"),
                                                  note=f"{path}: {detail}"), "dev")
            elif own["reader"]:
                d, role = dispatch_answer(self, own["answer"], path, detail, label, edits=e.get("edits"))
            elif own["role"] == "orchestrator":
                d, role = own_work(self, path, detail, label)
            else:
                role = own["role"]
                d = self.producer.dispatch(role, o.s, self.devs, self.label(f"{label} Agent({role})"),
                                           note=f"{path}: {detail}", edits=e.get("edits"))
            ans = own.get("answer") if isinstance(own.get("answer"), dict) else {}
            lane = ans.get("lane") or next((l.name for l in getattr(getattr(self.producer, "cyc", None), "lanes", None) or []
                                            if l.tid in {a.get("identity", {}).get("task_id")
                                                         for a in (ans.get("template") or {}).get("artifacts") or []}), None)
            if role == "main":  # the main agent ran its own canonical step
                self.routed.append({"path": path, "problem": detail, "role": role, "lane": lane, "agent": "main",
                                    "check": e.get("source_check") or ""})
            if d is not None and getattr(d, "agent_id", ""):
                self.routed.append({"path": path, "problem": detail, "role": role, "lane": lane,
                                    "agent": d.agent_id, "check": e.get("source_check") or ""})
                fact(self.rp, "routed dispatch", {"label": label, "path": path, "role": role, "lane": lane,
                                                  "agent_id": d.agent_id, "tool_use_id": d.tool_use_id})
            worked.append((e.get("source_check"), path, target, before))
            if not per_round:
                if self.recheck(worked, label, recheck) and e.get("source_check"):
                    passed_checks.add(e["source_check"])
                worked = []
        for check in dict.fromkeys(c for c, *_ in worked):
            self.recheck([w for w in worked if w[0] == check], label, recheck)

    def recheck(self, worked: list, label: str, recheck) -> bool:
        """The source_check re-run once for the entries `worked` [(check, path, target, hash before)], and
        close_progress over their artifacts' bytes and paths where the text measures it."""
        passed = recheck(f"{label} re-check")
        if passed and "`close_progress` when the re-check still fails" in self.routing_section():
            return passed  # the text measures progress only on a re-check that still fails
        if self.helpers and "close_progress" in self.helpers:
            # before/after hash of the entries' artifact bytes; before/after unresolved finding ids (their paths)
            def h(parts):
                return parts[0] if len(parts) == 1 else hashlib.sha256("".join(parts).encode()).hexdigest()[:16]
            paths = "\n".join(w[1] for w in worked)
            self.run_text(f"close_progress {h([w[3] for w in worked])} {h([_sha(w[2]) for w in worked])} "
                          f"{shlex.quote(paths)} " + ("''" if passed else shlex.quote(paths)),
                          self.label(f"{label} Bash close_progress"), "Measure the round's progress")
        return passed

    # ------------------------------------------------------------ preflights
    def do_status(self, label: str = "lite preflight") -> str:
        """The preflight's status check: the text's DO_STATUS block where it has one, else a Read of $DO_REPORT
        and its do.status (the text's "Read `$DO_REPORT`. Verify ... `do.status == \"completed\"`")."""
        o = self.o
        try:
            blocks = o.step_blocks("do-report lite preflight")
        except cmdtext.TextNotFound:
            blocks = []
        for name, b, _para in blocks:
            self.run_text(b.text, self.label(f"{label} Bash {name}"), "do-report lite preflight",
                          capture=("DO_STATUS",))
        if blocks:
            status = o.values.get("DO_STATUS") or ""
        else:
            self.read(self.do_report, self.label(f"{label} Read do-report"))
            status = str((self.load(self.do_report).get("do") or {}).get("status") or "")
        fact(self.rp, "do-report lite preflight", {"label": label, "do_status": status})
        return status

    def do_preflight(self) -> None:
        o = self.o
        status, k = self.do_status(), 0
        while status != "completed" and k < 3:
            # "a finding on $DO_REPORT: close_route_finding "$DO_REPORT" "do-report status is '<observed>', not
            # 'completed'" "do-report lite preflight"", worked until the re-read status is completed.
            k += 1
            lab = f"lite preflight round {k}"
            entries = self.record([(self.do_report, f"do-report status is '{status}', not 'completed'")],
                                  "do-report lite preflight", lab)
            got = []
            self.route(entries, lab, recheck=lambda l: got.append(self.do_status(l)) or got[-1] == "completed")
            status = got[-1] if got else status
        if status != "completed":
            raise agents.PlayError(f"the do-report is still {status!r} after {k} routing round(s)")
        if "Artifact schema gate" in o.section("do-report lite preflight"):
            self.schema_gate([self.do_report], "lite preflight")

    def schema_gate(self, paths: list, where: str) -> None:
        """The base text's Artifact schema gate: its first block, over `paths` (the chain's report_paths,
        or $DO_REPORT as its sole argument)."""
        o = self.o
        try:
            first = o.block("Artifact schema gate", lang="bash", index=0)
        except cmdtext.TextNotFound:
            return
        if not paths:
            pass
        text = re.sub(r"(?s)^mapfile -t REPORT_PATHS < <\(.*?\"\$ARTIFACT_CHAIN\"\)\n",
                      "REPORT_PATHS=(" + " ".join(shlex.quote(p) for p in paths) + ")\n", first) if self.do_report else first
        self.run_text(text, self.label(f"{where} Bash schema gate"), "Artifact schema gate",
                      capture=("SCHEMA_GATE_RC",))

    def cp_state(self) -> None:
        o = self.o
        g = o.s.tool("Glob", {"pattern": "cp-state-qa.json", "path": os.path.join(o.project, ".claude/specs", self.tid)},
                     label=self.label("preflight Glob cp-state"), deviation=self.devs.at(self.label("preflight Glob cp-state")))
        self.spec_id = self.tid if g.ok and g.response.get("filenames") else ""

    # ------------------------------------------------------------ Step 1
    def cycle_files(self) -> list:
        if self.do_report:
            return list((self.load(self.do_report).get("do") or {}).get("files_modified") or [])
        rel = self.chain.get("canonical_dev_report") or ""
        if not rel:
            return []
        self.read(rel, self.label("Step 1 Read canonical dev report"))
        return list((self.load(rel).get("dev") or {}).get("files_modified") or [])

    def registry_name(self) -> None:
        o = self.o
        sec = o.section("Step 1")
        m = re.search(r"`(python3 (?:~/\.claude|\"\$\{CLAUDE_HOME:-\$HOME/\.claude\})/hooks/prompt-workflow\.py\"?"
                      r" registry-dir \"\$TASK_ID\")`", sec)
        if m:
            c = o.run(o.shell_bind(m.group(1)), "The task's registry directory", self.label("Step 1 Bash registry-dir"))
            self.session_id = (c.response.get("stdout") or "").strip() if c.ok else ""

    def inspector_bullets(self) -> list:
        """(subagent_type, FIRST ACTION line, obligation, report path) of each bullet of the branch the chain selects."""
        sec = self.o.section("Step 1")
        fanout = self.chain.get("mode") == "fanout"
        anchor = "**If a parallel cycle is detected**" if fanout else "**If no parallel cycle is detected**"
        part = sec[sec.index(anchor):]
        nxt = part.find("\n**", len(anchor))
        part = part[:nxt] if nxt > 0 else part
        out = []
        for line in part.split("\n"):
            m = re.match(r"\s*-\s+Agent (?:tool )?call \d+:\s*`subagent_type:\s*([\w-]+)`", line)
            if not m:
                continue
            first = re.search(r"`(FIRST ACTION:[^`]+)`", line).group(1)
            ob = re.search(r"`(<obligation v=\"1\">\{.*?\}</obligation>)`", line).group(1)
            report = re.search(r"write its report to `([^`]+)`", line).group(1)
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
        self.registry_name()
        if not self.session_id:  # the base text spells the registry name in the FIRST ACTION line itself
            self.session_id = self.registry_from_text()
        self.inspector_reports = []
        for role, first, ob, report in self.inspector_bullets():
            prompt = "\n".join([first, ob, f"--changed-files {' '.join(self.files)}",
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
        self.revalidate()

    def registry_from_text(self) -> str:
        m = re.search(r"\.claude/dev-registry/([^/`\s]+)/style-inspector\.json", self.o.section("Step 1"))
        return self.o.bind(m.group(1)).replace("<TASK_ID>", self.tid) if m else ""

    def revalidate(self) -> None:
        """The base text's orchestrator check of the three reports (Missing/invalid-report re-dispatch)."""
        o = self.o
        sec = o.section("Step 1")
        if "validate_artifact_for_obligation" not in sec:
            return
        py = ("import os, sys; sys.path.insert(0, os.path.expanduser('~/.claude/hooks')); "
              "from lib import contract_runtime as cr; r = cr.validate_artifact_for_obligation(sys.argv[1], sys.argv[2]); "
              "print(r.get('status'), sys.argv[1]); sys.exit(0 if r.get('status') != 'fail' else 2)")
        for rel in self.inspector_reports:
            schema = re.sub(r"-report-.*$", "-report.v1", os.path.basename(rel))
            o.run(f"python3 -c {shlex.quote(py)} {shlex.quote(rel)} {schema}", "Inspector report validation",
                  self.label(f"Step 1 Bash validate {schema}"))

    # ------------------------------------------------------------ Step 2
    def step2_session(self) -> None:
        o = self.o
        try:
            text = o.block("Step 2", lang="bash", index=0)
        except cmdtext.TextNotFound:
            return
        if "SESSION_ID=" in text:
            self.run_text(text, self.label("Step 2 Bash SESSION_ID"), "Bind this dispatch's QA sentinel session",
                          capture=("SESSION_ID",))
            self.session_id = o.values.get("SESSION_ID") or self.session_id
        self.qa_arming()

    def qa_arming(self) -> None:
        """The base text's QA-arming rule: its three scripts, in the rule's fixed order, each until it exits 0."""
        o = self.o
        try:
            sec = o.section("Routing helpers")
        except cmdtext.TextNotFound:
            return
        para = next((p for p in re.split(r"\n\s*\n", sec) if "**QA-arming rule" in p), None)
        if not para:
            return
        cmds = [re.sub(r"\s+", " ", c).strip() for c in re.findall(r"`([^`]+)`", para) if re.search(r"write-[\w-]+\.sh", c)]
        o.values.update(SESSION_ID=self.session_id, PROJECT_ROOT=o.values.get("PROJECT_ROOT") or o.project)
        for k, cmd in enumerate(cmds, 1):
            self.run_text(cmd, self.label(f"Step 2 Bash QA arming {k}"), "QA-arming rule")

    def input_lines(self, prompt: str) -> str:
        """The Input artifacts bullets, each `<...>` filled from the retained chain or the do-report; a bullet
        whose description says "otherwise omit" and has no value here is left out."""
        lines = prompt.split("\n")
        try:
            i = next(k for k, l in enumerate(lines) if l.strip().startswith("Input artifacts"))
        except StopIteration:
            return prompt
        out, k = lines[:i + 1], i + 1
        chain = self.chain
        while k < len(lines) and (lines[k].startswith("- ") or (lines[k].startswith("  ") and out and not lines[k].strip() == "")):
            j = k + 1
            while j < len(lines) and lines[j].startswith("  ") and not lines[j].startswith("- "):
                j += 1
            item = "\n".join(lines[k:j])
            name, _, desc = item[2:].partition(":")
            desc = desc.strip()
            value = None
            if "complete retained ARTIFACT_CHAIN" in desc:
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
                    value = self.do_report if self.do_report else None
                elif "parent ticket" in desc and chain.get("mode") == "singular" and not self.do_report:
                    value = json.dumps(chain.get("artifact_paths"))
                elif "repair" in desc and "Disclosures" in desc:
                    value = json.dumps([self.disclosure(r) for r in self.routed], ensure_ascii=False)
            if value is not None:
                out.append(f"- {name.strip()}: {value}")
            elif "omit" not in desc:
                out.append(item)
            k = j
        return "\n".join(out + lines[k:])

    def qa_prompt(self) -> str:
        o = self.o
        tpl = next(b.text for b in cmdtext.blocks(o.section("Step 2")) if "<obligation" in b.text)
        lines = []
        for line in tpl.split("\n"):
            if line.strip().startswith("SECOND ACTION (only if SPEC_ID is non-empty") and not self.spec_id:
                continue
            lines.append(line)
        prompt = self.input_lines("\n".join(lines))
        prompt = o.instantiate(prompt, self.tid)
        return o.bind(prompt)  # QA's own instruction placeholders (<n>, <error detail>, ...) stay as written

    def report_rel(self) -> str:
        return f"docs/dev/close-report-{self.tid}.md"

    def close_qa_act(self, finding: dict | None, append: bool, disclosures: list) -> agents.Act:
        """Close QA's round: it reads its inputs and the cycle diff, runs each acceptance criterion's own check
        on the files as they stand (evidence, not code review), and returns the round-open line when it
        found anything (each finding naming the file and the failing check), else the landed form its
        `Completed repairs` input decides (one `## Disclosures` line per repair)."""
        o, tid = self.o, self.tid
        project = o.project
        inputs = ([self.do_report] if self.do_report else list(self.chain.get("report_paths") or [])) + self.inspector_reports
        mode = "do" if self.do_report else self.chain.get("mode", "singular")
        rounds = self.round
        head = [f"Task-id: {tid}", f"Artifact-chain mode: {mode}", "Input files: " + ", ".join(inputs),
                f"Rounds run: 1 (judging round {rounds} of this close)",
                "Workflow Integrity Dimension:",
                "1. Downstream consumability: " + ("N/A — /do path: the do-report is changelog-analyst's whitelist source"
                                                   if self.do_report else "PASS — the resolver passed and /commit can admit the whitelist as is"),
                "2. task-id chain consistency: " + ("N/A — /do path: do-report -> close-report under one task id"
                                                    if self.do_report else "PASS — one task id across the chain"),
                "3. Pre-existing-defect rule: PASS — nothing pre-existing raised",
                "4. Self-deployability: PASS — (i) PASS, (ii) PASS (local bare origin), (iii) PASS, (iv) N/A",
                "Codex consultation: codex_status: disabled_by_user",
                "[Codex] consultation skipped: --codex flag not passed; QA-only assessment performed"]

        def judge(found: list) -> str:
            lines = list(head)
            if found:
                lines += ["", "## Findings"] + [f"- {f['path']}: {f['detail']}" if f.get("path")
                                                else f"- (no artifact cited): {f['detail']}" for f in found]
            elif disclosures:
                lines += ["", "## Disclosures"] + list(disclosures)
            verdict = (f"CLOSE_FINDINGS: {len(found)} items" if found else
                       f"CLOSE: YES - with disclosures: {len(disclosures)} items" if disclosures else CLOSE_YES_PLAIN)
            act.notes = "\n".join(lines)
            act.terminal.update({self.report_rel(): verdict, "response_line": verdict})
            self.round_findings = found
            return verdict

        def work(sub, brief, player):
            for rel in inputs:
                p = os.path.join(project, rel)
                if os.path.isfile(p):
                    sub.read(p, label=f"{sub.role} Read {rel}")
            if self.files:
                sub.bash("git diff -- " + " ".join(shlex.quote(f) for f in self.files),
                         "Inspect the cycle diff", label=f"{sub.role} Bash git diff")
            verdict = judge(([finding] if finding else []) + self.ac_findings(sub))
            if not append:
                return None
            # Overwrite policy: the section to a temp file, then the append helper the text names.
            section = os.path.join("/tmp/claude-scratch/qa", f"close-section-{tid}-r{rounds}.md")
            text = f"## Close attempt (round {rounds}) {utc_now()}\n\n{act.notes}\n\n{verdict}\n"
            sub.write(section, text, label=f"{sub.role} Write section")
            code = self.append_call()
            code = code.replace('"<absolute-temp-section-path>"', shlex.quote(section)).replace(
                "<absolute-temp-section-path>", section)
            code = o.bind(code)
            cmd = f"PROJECT_ROOT={shlex.quote(project)}\n" + o.respell(code, f"{sub.role} Bash append helper")
            c = sub.bash(cmd, "Append this attempt's section", label=f"{sub.role} Bash append helper")
            out = (c.response.get("stdout") or "") if c.ok else (c.error or "")
            line = out.strip().splitlines()[-1] if out.strip() else ""
            try:
                got = json.loads(line).get("verdict_line") if c.ok else None
            except ValueError:
                got = None
            act.terminal["response_line"] = got or (line if line.startswith("CLOSE_REPORT_APPEND_") else verdict)
            return None

        act = agents.Act(work=work, produced=[self.report_rel()] if append else [], summary="close debate")
        judge([finding] if finding else [])
        return act

    def ac_checks(self) -> list:
        """(file, AC id, python check, the producer's fixed text) of each acceptance criterion of the cycle that
        names a call (`check.call` raising `check.raises` matching `check.match`): one per lane."""
        cyc = getattr(self.producer, "cyc", None)
        scs = [l.sc for l in getattr(cyc, "lanes", None) or []] or ([cyc.sc] if getattr(cyc, "sc", None) else [])
        out = []
        for sc in scs:
            chk = (sc.ac or {}).get("check") or {}
            if not chk.get("call") or not chk.get("raises"):
                continue
            call = chk["call"].replace("'", '"')
            mod = call.split("(", 1)[0].rsplit(".", 1)[0]
            py = (f"import re, sys\nsys.path.insert(0, sys.argv[1])\nimport {mod}\ntry:\n    {call}\n"
                  f"except {chk['raises']} as e:\n"
                  f"    print(\"PASS\" if re.search({json.dumps(chk.get('match') or '')}, str(e)) else "
                  f"\"FAIL {chk['raises']} raised: \" + repr(e))\n"
                  f"else:\n    print(\"FAIL no {chk['raises']} raised\")\n")
            out.append((sc.rel, sc.ac.get("id") or "AC", f"{chk['call']} raises {chk['raises']} matching "
                        f"{chk.get('match')!r}", f"python3 -c {shlex.quote(py)} {shlex.quote(self.o.project)}", sc.final))
        return out

    def ac_findings(self, sub) -> list:
        """Close QA's own run of each acceptance criterion's check: a failing one is a finding on its file."""
        found = []
        for rel, ac, what, cmd, final in self.ac_checks():
            c = sub.bash(cmd, f"{ac}: {what}", label=f"{sub.role} Bash {ac} {rel}")
            out = ((c.response.get("stdout") or "") if c.ok else (c.error or "")).strip()
            if out != "PASS":
                found.append({"path": rel, "detail": f"{ac} fails: {what}; observed: {out[-300:]}", "new": final})
        return found

    def append_call(self) -> str:
        sec = self.o.section("Step 2")
        m = re.search(r"`([^`]*close-report-append\.py[^`]*)`", sec)
        if not m:
            raise cmdtext.TextNotFound("Step 2 names no append helper call")
        return m.group(1)

    def disclosures(self, prompt: str) -> list:
        """The `## Disclosures` lines close QA writes: its prompt's `Completed repairs` input where the text gives
        it one; else the repairs of this /close's earlier rounds, which the report's earlier sections show."""
        m = re.search(r"^- Completed repairs: (\[.*\])$", prompt, re.M)
        if m:
            return json.loads(m.group(1))
        return [self.disclosure(r) for r in self.repairs]

    @staticmethod
    def disclosure(r: dict) -> str:
        return (f"{r['path']}: {r['problem']} | 归因: {r['role']}({r.get('lane') or '-'}) | 修复: dispatched again "
                f"({r.get('agent') or '-'}); {r.get('check') or 'the check'} re-run clean")

    def close_round(self, finding=None) -> str:
        o = self.o
        self.round += 1
        append = os.path.exists(os.path.join(o.project, self.report_rel()))
        prompt = self.qa_prompt()
        act = self.close_qa_act(finding, append, self.disclosures(prompt))
        player = agents.Player(o.tree, prompt, act, role="qa")
        lab = self.label(f"Step 2 Agent(qa) close round {self.round}")
        d = o.s.dispatch("qa", prompt, description="close debate", body=player.body, result=player.final, label=lab,
                         deviation=self.devs.at(lab))
        text = ((d.response.get("content") or [{}])[0].get("text") or "") if d.response else ""
        last = text.strip().splitlines()[-1] if text.strip() else ""
        self.verdicts.append((self.round, last))
        fact(self.rp, "close QA round", {"task": "<task>", "round": self.round, "verdict": last, "append": append,
                                          "findings": [{k: f[k] for k in ("path", "detail")} for f in self.round_findings],
                                          "agent_id": d.agent_id,
                                          "resolved_role": resolved_role(self.rp, d.agent_id) if d.agent_id else None,
                                          "stop_blocked": bool(d.stop and d.stop.still_blocked)})
        return last

    def has_reader(self) -> bool:
        return reader_call(self.helpers, self.routing_section(), "x") is not None

    def close_entry(self, finding: dict):
        """(path, detail) of the routing entry for a close-QA finding, as the text builds it: on a text with the
        reader, the path the finding names (that round's own report for a finding that cites none); on a
        role-table text, the dev report that claims a product file, or $TASK_ID for a finding with no path."""
        path, detail = finding.get("path") or "", finding["detail"]
        if self.has_reader():
            if not path:
                return self.report_rel(), f"(no artifact cited): {detail}"
            return path, detail
        if not path:
            return self.tid, detail
        return self.claiming_report(path), f"{path}: {detail}"

    def edits_for(self, finding: dict) -> list:
        """The change the dispatch that fixes `finding` makes when it runs again: the fixed text a finding carries
        (`new`: close QA's own run of an acceptance check, the append round's finding), else by its path."""
        path = finding.get("path") or ""
        if finding.get("new") is not None:
            return [(path, self.current(path), finding["new"])]
        if path == FINDING["path"]:
            return [(path, self.current(path), self.fixed(path))]
        if path == f"docs/dev/dev-report-{self.tid}.json":
            return [("toy/util.py", UTIL_OLD, UTIL_NEW)]
        return []

    def named_by_rerun(self) -> dict:
        """What the round's QA dispatch names when it runs again on a finding that its report alone holds."""
        if self.variant == "unwritten":
            return {"path": f"docs/dev/dev-report-{self.tid}.json",
                    "detail": "the cycle's dev report claims the requirement met, yet toy/util.py's sub() still "
                              "accepts a non-number (the earlier round's finding on a file no dispatch of this task "
                              "wrote): the dev work owes that file's argument check"}
        return dict(FINDING)

    def rerun_close_qa(self, ans: dict, path: str, detail: str, label: str):
        """That round's QA dispatch runs again (its recorded prompt, a fresh dispatched_at, scoped to the entry)
        and names an artifact: a new judging round whose return the routing loop takes next."""
        o = self.o
        self.round += 1
        now = utc_now()
        prompt = re.sub(r'("dispatched_at"\s*:\s*)"[^"]*"', lambda m: m.group(1) + json.dumps(now), ans["prompt"])
        prompt = prompt.rstrip("\n") + f"\n\nRouting finding: {path}: {detail}\n"
        named = self.named_by_rerun()
        act = self.close_qa_act(named, os.path.exists(os.path.join(o.project, self.report_rel())), self.disclosures(prompt))
        player = agents.Player(o.tree, prompt, act, role="qa")
        lab = self.label(f"{label} Agent(qa)")
        d = o.s.dispatch("qa", prompt, description="close debate", body=player.body, result=player.final, label=lab,
                         deviation=self.devs.at(lab))
        text = ((d.response.get("content") or [{}])[0].get("text") or "") if d.response else ""
        last = text.strip().splitlines()[-1] if text.strip() else ""
        self.verdicts.append((self.round, last))
        self.rerun_finding = named
        fact(self.rp, "close QA round", {"task": "<task>", "round": self.round, "verdict": last, "append": True,
                                          "rerun_of": "the round's own QA dispatch", "names": named["path"],
                                          "findings": [{k: f[k] for k in ("path", "detail")} for f in self.round_findings],
                                          "agent_id": d.agent_id,
                                          "resolved_role": resolved_role(self.rp, d.agent_id) if d.agent_id else None,
                                          "stop_blocked": bool(d.stop and d.stop.still_blocked)})
        return d

    def step2(self) -> str:
        """Close QA rounds until one lands; a round-open return is echoed and each finding routed first. When the
        routing loop runs the round's own QA dispatch again, that run's return is the next round routed."""
        o = self.o
        self.step2_session()
        first = {"noartifact": FINDING_NO_ARTIFACT, "unwritten": FINDING_UNWRITTEN}.get(self.variant)
        if self.variant == "append":
            first = dict(FINDING, new=self.fixed(FINDING["path"]))
        last = self.close_round(first)
        k = 0
        while last.startswith("CLOSE_FINDINGS") and k < 4:
            k += 1
            o.s.say(last)
            self.read(self.report_rel(), self.label(f"Step 2 Read close-report round {self.round}"))
            entries = []
            for f in list(self.round_findings):
                for e in self.record([self.close_entry(f)], "close QA round", f"Step 2 round {k}"):
                    e["edits"] = self.edits_for(f)
                    entries.append(e)
            n = len(self.routed)
            self.rerun_finding = None
            # The re-check is a fresh, independent QA round (below); the repair is QA's to disclose.
            self.route(entries, f"Step 2 round {k}", recheck=lambda lab: True)
            self.repairs.extend(self.routed[n:])
            if self.rerun_finding is not None:
                last = self.verdicts[-1][1]  # the re-run round's return: its findings are routed next
                continue
            last = self.close_round()
        return last

    def current(self, rel: str) -> str:
        return agents.peek(self.rp, "main", os.path.join(self.o.project, rel))

    def fixed(self, rel: str) -> str:
        cur = self.current(rel)
        return cur.replace("def add(a, b):\n", "def add(a, b):\n" + TOY_DOC, 1)

    # ------------------------------------------------------------ Step 3
    def step3(self, last: str) -> None:
        o = self.o
        o.s.say(last)
        if not last.startswith("CLOSE: YES"):
            return
        ever = False
        for item in (self.chain.get("qa_inputs") or []) if not self.do_report else []:
            rel = item if isinstance(item, str) else (item.get("path") or item.get("qa_report") or "")
            if rel and os.path.isfile(os.path.join(o.project, rel)):
                self.read(rel, self.label(f"Step 3 Read {rel}"))
        decide = o.block("Step 3", anchor="close-scoring-decide.py").strip()
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
        o.s.say(o.block("Step 3", anchor="<options>").strip())
        self.workflow_update()

    def workflow_update(self) -> None:
        """The workflow update the text names: the base text's /spec-update --temp note, else the next action."""
        o = self.o
        sec = o.section("Step 3")
        if "/spec-update --temp" not in sec:
            o.s.say(f"Next: /commit {self.tid} -m \"toy.add validates its arguments\"")
            return
        su = Orchestrator(self.rp, "spec-update", session=o.s, deviations=self.devs)
        mk = su.inline("Temp-note mode", "mktemp", startswith="mktemp")
        c = o.run(mk, "Create the temp update note", self.label("Step 3 Bash mktemp update note"))
        path = c.response.get("stdout", "").strip() if c.ok else ""
        if not path:
            return
        m = re.search(r"update-([A-Za-z0-9]+)\.md$", path)
        if m:
            self.rp.rand(m.group(1))
        o.s.read(path, label=self.label("Step 3 Read update note"), deviation=self.devs.at(self.label("Step 3 Read update note")))
        note = su.block("Temp-note mode", anchor="# Update")
        refs = [self.report_rel()] + (list(self.chain.get("artifact_paths") or []) if not self.do_report else [self.do_report])
        rules = [(r"^ISO-8601$", utc_now()), (r'id or "unknown"', self.tid), (r"^spec\|dev\|close", "close"),
                 (r"^short focus$", f"commit {self.tid}"), (r"^what the next session should do$", f"/commit {self.tid}"),
                 (r"exact next command", f"/commit {self.tid}"), (r"^paths$", ", ".join(refs + self.inspector_reports)),
                 (r"^path or URL$", (self.chain.get("artifact_paths") or {}).get("ticket", "none")
                  if isinstance(self.chain.get("artifact_paths"), dict) else (self.do_report or "none")),
                 (r"3-8 sentences", f"/close {self.tid} landed CLOSE: YES. Commit it next with /commit {self.tid}."),
                 (r".", "none")]
        note = su.bind(note, rules)
        o.s.write(path, note, label=self.label("Step 3 Write update note"),
                  deviation=self.devs.at(self.label("Step 3 Write update note")))

    # ------------------------------------------------------------ one close, Steps 0-3
    def body(self) -> str:
        o = self.o
        self.resolve_task()
        if self.do_report:
            self.do_preflight()
            self.chain = {}
        elif self.variant == "late-repair":
            self.late_repair()
        else:
            self.step0_loop()
            if self.chain.get("report_paths") is not None:
                self.schema_gate(list(self.chain.get("report_paths") or []), "Step 0")
            self.cp_state()
        self.step1()
        o.advance(label=self.label("TodoWrite Step 1 done, Step 2 in_progress"))
        last = self.step2()
        o.advance(label=self.label("TodoWrite Step 2 done, Step 3 in_progress"))
        self.step3(last)
        o.advance(label=self.label("TodoWrite Step 3 done"))
        return last

    def run(self) -> str:
        self.start(f"--late-repair {self.tid}" if self.variant == "late-repair" else self.tid)
        last = self.body()
        self.outcome = last
        ev = self.o.s.stop(f"/close {self.tid}: {last}", label="/close Stop", deviation=self.devs.at("/close Stop"))
        report_last, n = self.report_form()
        # /close's terminal form: the report's last non-empty line is the disclosures form when the routing loop
        # completed a repair (<n> its `## Disclosures` lines), else the plain form.
        form = f"CLOSE: YES - with disclosures: {n} items" if self.routed else CLOSE_YES_PLAIN
        ok = report_last == form and (n > 0 or not self.routed)
        self.rp.terminal("close", last.startswith("CLOSE: YES") and ok, ev, task=self.tid,
                         last_line=last, report_last_line=report_last, disclosures=n, repairs=len(self.routed))
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

    # ------------------------------------------------------------ --auto
    def run_auto(self) -> list:
        o = self.o
        self.start("--auto")
        # The flag combination: `--auto` typed alone is legal by the section's rule; a text that spells
        # the rule as a Bash check (the base) has it run.
        for flag in cmdtext.blocks(o.section("Argument parsing: `--auto` flag"), None, "bash")[:1]:
            self.run_text(flag.text, "/close --auto Bash flag check", "--auto flag-combination check",
                          rules=[(r"^explicit-task-id-or-empty$", ""), (r"^force_bool$", "False")])
        disc = o.block("`--auto` mode", lang="bash", index=0)
        self.run_text(disc, "/close --auto Bash discovery", "Discover the close_pending parents",
                      capture=("CLOSE_PENDING_PARENTS",))
        parents = o.values.get("CLOSE_PENDING_PARENTS") or []
        if isinstance(parents, str):
            parents = [parents] if parents else []
        walk = o.section("`--auto` mode")
        results = []
        for line in parents:
            tid, _, chain = line.partition(" ")
            self.tid = tid
            self.rp.task(tid)
            o.values.update(TASK_ID=tid)
            if chain and "ROUTE_SELECT_RC=0" in walk:
                # Step 0 takes the discovery line's chain (the parent's one chain call) with ROUTE_SELECT_RC=0.
                o.values.update(ARTIFACT_CHAIN=chain, ROUTE_SELECT_RC="0")
                self.chain = json.loads(chain)
                self.step0_loop = lambda rounds=3: None  # noqa: E731 (this walk's Step 0 makes no call)
            last = self.body()
            outcome = "success" if last.startswith("CLOSE: YES") else "ordinary_reject"
            results.append((tid, outcome))
        o.s.say("\n".join(f"{t}: {oc}" for t, oc in results) or "no close_pending parent")
        self.outcome = "; ".join(f"{t}: {oc}" for t, oc in results)
        ev = o.s.stop(f"/close --auto: {self.outcome}", label="/close Stop", deviation=self.devs.at("/close Stop"))
        self.rp.terminal("close", bool(results) and all(oc == "success" for _, oc in results), ev,
                         outcome=self.outcome)
        return results


# ---------------------------------------------------------------- composition

def dev_cycle(rp, after: str):
    """Run the cycle /close follows; returns (producer, task id, its session, the cycle object)."""
    cyc = cycle(rp, after)
    cyc.run()
    return DevProducer(cyc), cyc.tid, cyc.o.s, cyc


def cycle(rp, after: str):
    """The cycle /close follows, not yet run."""
    if after == "dev-command":
        try:
            from . import dev_command as dcdrv  # another lane's driver
        except ImportError as e:
            raise RuntimeError("drivers/dev_command.py does not exist yet: the /dev-command scenario is not run") from e
        return dcdrv.DevCommandCycle(rp, rp.args.get("cycle_variant", "plain"))
    from . import dev as devdrv
    variant, tier = rp.args.get("cycle_variant", "plain"), rp.args.get("tier", "STANDARD")
    if variant.startswith("fanout"):
        return devdrv.FanoutCycle(rp, variant, tier, int(rp.args.get("lanes", "2")), rp.args.get("lane_id", "text"))
    return devdrv.DevCycle(rp, variant, tier)


def lane_report(cyc, kind: str) -> str:
    """The report of `kind` (dev, qa) one lane of the cycle wrote: a fan-out cycle's first lane's, else the
    cycle's own (the singular cycle is one implicit lane)."""
    lanes = getattr(cyc, "lanes", None)
    return f"docs/dev/{kind}-report-{lanes[0].tid if lanes else cyc.tid}.json"


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


def damage(rp, cyc) -> str:
    """The fault between commands (D25 (2) F8p): the product file one lane's dev wrote (a fan-out cycle's last
    lane's, else the cycle's own) put back to an incomplete fix that fails its acceptance criterion; recorded in
    faults.json."""
    from ..faults import _record
    sc = (getattr(cyc, "lanes", None) or [cyc])[-1].sc
    with rp.acting("fault"):
        with open(os.path.join(rp.layout.project, sc.rel), "w") as fh:
            fh.write(sc.partial)
    _record(rp, {"kind": "break", "path": sc.rel, "after": rp.terminals[-1]["pipeline"] if rp.terminals else None,
                 "events_before": rp.n_events})
    return sc.rel


# Every variant run() plays (the artifact check reads only the docstring's `variant=` lines: no VARIANTS here).
PLAYED = ("plain", "route", "append", "auto", "break", "qa-never", "noartifact", "unwritten", "late-repair")


def removed_after_cycle(variant: str, cyc) -> list:
    """The artifacts a variant removes after the cycle reached its terminal (acceptance 7; F8): route the lane
    QA report (lane_report), late-repair the ticket and context."""
    tid = cyc.tid
    return {"route": [lane_report(cyc, "qa")],
            "late-repair": [f"docs/dev/ticket-{tid}.md", f"docs/dev/context-{tid}.json"]}.get(variant, [])


def pipeline_name(after: str, rp) -> str:
    cv = rp.args.get("cycle_variant", "plain")
    if cv.startswith("fanout") and rp.args.get("lanes", "2") != "2":
        cv += "-" + rp.args["lanes"]
    return after + (f"/{cv}" if cv != "plain" else "")


def run(rp) -> None:
    after = rp.args.get("after", "dev")
    variant = rp.args.get("variant", "plain")
    if variant not in PLAYED:
        raise ValueError(f"unknown variant {variant!r}")
    if variant == "qa-never":
        rp.args.setdefault("cycle_variant", "qa-never")
    session_kind = rp.args.get("session", "same" if variant == "plain" else "later")
    rp.pipeline = (pipeline_name(after, rp) + "+close" + (f"/{variant}" if variant != "plain" else "")
                   + ("/later" if session_kind == "later" else ""))
    from ..recovery import SessionCut
    cyc = cycle(rp, after)
    try:
        cyc.run()
    except SessionCut:  # F8q: the cycle's session was cut (fault cut@<a main-agent step>); the owner types /close
        session_kind, end = "later", "other"
    else:
        end = "prompt_input_exit"
    producer, tid, s = DevProducer(cyc), cyc.tid, cyc.o.s
    remove(rp, [p for p in removed_after_cycle(variant, cyc) if os.path.exists(os.path.join(rp.layout.project, p))])
    if variant == "break":
        damage(rp, cyc)
    session = rp.later_session(s, end) if session_kind == "later" else s
    cr = CloseRun(rp, session, tid, producer=producer, variant=variant, auto=variant == "auto")
    if variant == "auto":
        cr.run_auto()
    else:
        cr.run()
