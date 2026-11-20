#!/usr/bin/env python3
"""Stop gate: hold each gated command until it is complete (P5 R7).

The Stop coordinator's completion phase runs it with its mode
(`--mode block|advisory|off`; block when none is given); it reads the hook
payload on stdin and decides, in order:

  (1) a payload with agent_id (a subagent's Stop): allow;
  (2) mode off: allow;
  (3) the active span: command_span.active_span, which only a human-typed
      harness command outside CONTROL opens or replaces (never a Skill
      expansion, a scheduled prompt or a wakeup); a plain prompt continues it;
  (4) the overnight time-lock, whatever the span and the mode: block while
      overnight.window_open(payload), naming the time left; after end_time
      (closeout_gaps empty) or the owner's /stop, block while the wake's
      CronCreate (overnight.WAKE_PROMPT) has no later CronDelete
      (overnight.open_wakes), naming its id; a time-lock it cannot read
      blocks the same way until the human's /stop;
  (5) no gated span (stop-commands.json's GATED_COMMANDS) and no /spec or /dev-family span: allow;
  (5b) a /close or /commit that bound no task and dispatched none, ending on a NO_TARGET: line (no_target_end:
      "Which task?" and refused flag combinations end with the candidates, nobody asked): allow;
  (5c) a gated step whose own call a hook refused, ending on its REFUSED: line (step_refused_end): allow;
  (6) the gaps: in a /spec or /dev-family span the text question (R7, p_text_question: a last line
      ending in "?" with a question the span neither asked with an AskUserQuestion the owner answered
      nor recorded in a spec it wrote through spec-write.py; /spec has no other gap); in a gated span the todo half and the command's predicate, each held to the
      command's text as the span loaded it (_loaded_lacks: a step or the
      close-rating question an update added or reworded after the session
      loaded its text is not asked of it; a cycle whose loaded text names or
      writes its artifacts otherwise than this tree's is asked as that text
      does, COMPATIBILITY below); an exception is the gap
      `gate instrument failure: <type>: <message>`, never an allow but one:
      a /close that stalled at Step 0 as close.md says (close_stalled) while
      the predicate's own reading fails too ends its turn (D25: no agent
      action in the span clears an instrument both read); likewise /push and
      /merge end on Step 5's refusal, reported and never asked about
      (step5_refused), while git still meets it: no remote the push is
      judged on reads, or the source's merge stands in conflict;
  (7) no gap: allow; advisory: `would block` and the gaps on stderr, exit 0;
      else the block text on stderr, exit 2.

Each fact comes from the one producer that writes it: the transcript through
command_span (the CLI's record of typed prompts, tool calls and hook context,
and the command's text it loaded), the command's text on disk (commands/),
git, and the producers' own deciders, called, never copied: P3's disposition
as the chain's own disposition_lines (scripts/resolve-dev-artifact-chain.py,
through the one adapter `disposition`), the do-report's one reading
(hooks/lib/do_report.py) and the chain's do branch, P2's overnight locator and window
(hooks/lib/overnight.py), P4's close rating (hooks/lib/close_rating.py),
dev-lifecycle's --auto target function, the merge-analyst's and push-analyst's
grants (hooks/lib/merge_grant.py) and the push-gate token's path
(scripts/write-push-gate-token.py). No target comes from a dispatch prompt or a
tool result. The gate writes nothing but its own output and /close's probe of docs/dev, one byte to an
unnamed temporary file it drops at once (environment_refusal) (stdout:
the terminal time-lock status of an allowed Stop, see main), keeps no count
and has no release but the work itself: the next compliant step clears each
gap. The human's /stop opens a span that is not gated, and nothing here
offers a stop.
"""
from __future__ import annotations

import errno
import hashlib
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HOOKS = Path(__file__).resolve().parent
HARNESS = HOOKS.parent
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from lib import command_span  # noqa: E402  (the one transcript reader)
from lib.harness_vocabulary import GATE_MODES as MODES  # noqa: E402

_SCRIPTS: dict = {}


def _script(rel: str):
    """A harness script loaded by path, once per process."""
    if rel not in _SCRIPTS:
        spec = importlib.util.spec_from_file_location(f"_gate_script_{len(_SCRIPTS)}", HARNESS / rel)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _SCRIPTS[rel] = module
    return _SCRIPTS[rel]


# Ancestry as the commits record it: no replace object or graft file an agent writes re-parents one (P5-61).
_GIT_ENV = {"GIT_NO_REPLACE_OBJECTS": "1", "GIT_GRAFT_FILE": os.devnull}


def _git(root, *args: str) -> str | None:
    """git's stripped stdout in ``root``; None when it fails."""
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=20,
                          env={**os.environ, **_GIT_ENV})
    return done.stdout.strip() if done.returncode == 0 else None


def _repository(root) -> None:
    """A predicate on git facts reads a repository, else its gap is an instrument failure."""
    if _git(root, "rev-parse", "--git-dir") is None:
        raise RuntimeError(f"{root} is not a git repository")


# ---------------------------------------------------------------- P3's disposition
def disposition(root, task: str, stage: str) -> list[str]:
    """Gap lines at ``stage``, [] for chain_pass: the chain's own disposition_lines (P3's disposition), verbatim;
    its instrument failure raises. The informational completeness run on demand: read here only if it can decide."""
    chain = _script("scripts/resolve-dev-artifact-chain.py")
    chain.FULL_COMPLETENESS_ON_DEMAND = True
    return chain.disposition_lines(root, task, stage)


# ---------------------------------------------------------------- the text the span loaded (D15)
# The source of the /close Step 4 question (lib/close_rating.py SOURCE_RE), as a text that asks it names it.
RATING_SOURCE = "close-rating:"
_STEP_LABEL_RE = re.compile(r"Step ([0-9A-Za-z]+):")


def _texts(span) -> tuple:
    """(the text the span loaded, Span.body; the command's text on disk, commands/<command>.md,
    with the span's arguments where the CLI fills them in, as the loaded text has them), each
    None when there is none."""
    try:
        current = span.args.join(
            (command_span.COMMANDS_DIR / f"{span.command}.md").read_text(encoding="utf-8").split("$ARGUMENTS"))
    except OSError:
        current = None
    return span.body(), current


def _loaded_lacks(span):
    """A test on a regex: the command's text on disk (commands/<command>.md) words a
    demand (the regex's first match there) that the text the span loaded (Span.body:
    the CLI's record of the command as the session took it up) does not hold. The
    demand came with an update after the session loaded its text, added or reworded:
    the session follows the text it loaded, which never makes it as the file now
    does (D15, D25), as a span keeps the list it started with. A span with no
    recorded text, or a demand the text on disk does not word, is held to it."""
    loaded, current = _texts(span)
    if loaded is None or current is None:
        return lambda pattern: False

    def lacks(pattern) -> bool:
        found = re.search(pattern, current, re.M) if pattern else None
        return found is not None and found.group(0) not in loaded
    return lacks


def _step_heading(todo) -> str | None:
    """The pattern of the heading line of a todo step's section (`### Step 4: ...` for
    "Step 4: ..."), None for a step its content labels otherwise."""
    found = _STEP_LABEL_RE.match(str(todo.get("content") or ""))
    return rf"^#+[ \t]+Step[ \t]+{re.escape(found.group(1))}(?![0-9A-Za-z]).*$" if found else None


# ---------------------------------------------------------------- COMPATIBILITY: a cycle its text names otherwise
# COMPATIBILITY for the live landing (P1b acceptance 17; D15, D25), kept until no session predates the
# landing: a session the owner started before this tree landed keeps the command text it loaded
# (origin/master's, 2acc29b) while its hooks become this tree's. Two of the chain's demands are worded by
# this tree's text alone, so a cycle run from a text that lacks them (_loaded_lacks) is held to the chain
# as its own text names and writes it; a cycle on this tree's text, or with no recorded text, exactly as
# before.
#   naming    this tree's /dev and /dev-command name a cycle's artifacts with the id the hook prints as
#             `Task id: …` (obligation.canonical_task_id); a text without that line names them with the id
#             its dispatches carry (origin/master's /dev: DEV_SESSION_ID, dev-<ts>; its /dev-command: the
#             bare <ts>), as its /close and /commit then type it: the chain is asked under that name at
#             each of their Stops in the session (_cycle_names).
#   template  this tree's completion template (COMPLETION_TEMPLATE: dev.md Step 17, dev-command.md Step
#             16) words the completion's identity lines and its Files Generated references as the chain
#             checks them. A completion gap whose demand that template words and the loaded text's template
#             does not (origin/master's and P1b's: no Ticket line; master's /dev-command: `**Request ID**:
#             dev-<timestamp>`) is one that text never writes, and its own closing resolver call refuses
#             that completion on every kit: it is not asked at the cycle's /dev-family Stop (its /close
#             routes it at Step 0, as on train 1); a demand both templates word is asked, and /close and
#             /commit ask every one.
NAMING = re.escape("`Task id: …`")
COMPLETION_TEMPLATE = (r"^#+[ \t]+Development Completion Report\b[^\n]*\n[\s\S]*?"
                       r"^\*\*Save report to\*\*:[ \t]*`docs/dev/completion-[^`\n]*`[^\n]*$")
DEV_TEXTS = ("dev", "dev-command")  # the texts a /dev-family cycle runs; /redev runs the conversation's /dev text
# P3's gap_line (plain tokens and message) and validate_completion's reference message
_GAP_RE = re.compile(r"GAP artifact=(\S+) problem=(\S+): (.*) lane=\S+(?: step=.*)?$")
REFERENCE_MESSAGE = "completion does not reference "
_PLACEHOLDER = r"<[^<>\s`]+>"  # a template's placeholder: <timestamp>, <task-id>, <lane>, ...


def _cycles(span) -> list[tuple[int, int | None, object]]:
    """COMPATIBILITY: (opener line, next opener's line or None, text span) of each /dev-family span of
    the span's session up to and including it; the text span is the one whose loaded text the cycle
    runs: the span itself for /dev and /dev-command, for /redev the conversation's last /dev or
    /dev-command (None when it holds none)."""
    path, found, text = span.transcript_path, [], None
    every = command_span.openers(path)
    for k, (line, command, args) in enumerate(every):
        if line > span.start_line:
            break
        if command in DEV_TEXTS:
            text = command_span.Span(command, args, line, path)
        elif command != "redev":
            continue
        found.append((line, every[k + 1][0] if k + 1 < len(every) else None, text))
    return found


def _cycle_names(span) -> dict:
    """COMPATIBILITY (naming): {canonical task family: {name, ...}} for each cycle of the span's session
    whose loaded text lacks this tree's NAMING line: the family as the cycle's own dispatches spell it
    (their task_id, the lane suffix left out), the name its artifacts carry. {} when no cycle runs such
    a text: every task is asked under its canonical id. The cycles' texts are read only when a dispatch
    spells its task otherwise than canonically (a session on this tree's text reads none of them)."""
    ob = importlib.import_module("lib.obligation")
    spelled = []
    for record in ob.dispatch_obligations(span.transcript_path):
        raw = record["obligation"].get("task_id")
        family = ob.task_family(raw)
        if family:  # the prefix canonical_task_id strips kept, the lane suffix task_family strips left out
            name = raw[:len(raw) - len(ob.canonical_task_id(raw)) + len(family)]
            spelled.append((record.get("line") or 0, family, name))
    if all(name == family for _at, family, name in spelled):
        return {}
    spans = [(lo, hi) for lo, hi, text in _cycles(span) if text is not None and _loaded_lacks(text)(NAMING)]
    names: dict = {}
    for at, family, name in spelled:
        if any(lo < at and (hi is None or at < hi) for lo, hi in spans):
            names.setdefault(family, set()).add(name)
    return names


def _names(names: dict, task: str) -> list[str]:
    """The names the chain is asked under for ``task`` (canonical): its cycle's own (_cycle_names), else it."""
    return sorted(names.get(task) or {task})


def _templates(text) -> tuple | None:
    """COMPATIBILITY (template): (this tree's completion template, the loaded text's; "" for none) of
    a cycle's text span, None when either text is missing."""
    loaded, current = _texts(text) if text is not None else (None, None)
    if loaded is None or current is None:
        return None
    return tuple(found.group(0) if found else "" for found in
                 (re.search(COMPLETION_TEMPLATE, t, re.M) for t in (current, loaded)))


def _identities(template: str) -> list[str]:
    """The identity lines a completion template writes, as the chain reads them (its IDENTITY_RE),
    each placeholder as <>."""
    identity = _script("scripts/resolve-dev-artifact-chain.py").IDENTITY_RE
    # each line cleaned as the chain's validate_markdown_identity cleans it
    lines = (re.sub(r"\*\*|`", "", line.strip()) for line in template.splitlines())
    return sorted(re.sub(_PLACEHOLDER, "<>", line) for line in lines if identity.fullmatch(line))


def _names_reference(template: str, reference: str, name: str) -> bool:
    """Whether a completion template names ``reference`` (a path holding the cycle's ``name``): a
    path it quotes is the reference with a placeholder for the name and one for each label after it
    (a lane's)."""
    head, found, tail = reference.partition(name)
    stem, dot, suffix = tail.rpartition(".")
    if not found or not dot or not re.fullmatch(r"(?:-[A-Za-z0-9]+)*", stem):
        return False
    pattern = re.escape(head) + _PLACEHOLDER + f"-{_PLACEHOLDER}" * stem.count("-") + re.escape("." + suffix)
    return any(re.fullmatch(pattern, quoted) for quoted in re.findall(r"`([^`\n]+)`", template))


def _unwritten(line: str, name: str, templates: tuple | None) -> bool:
    """COMPATIBILITY (template): a gap line of the completion of ``name`` whose demand this tree's
    template words and the loaded template does not: its identity lines differ (IDENTITY_MISMATCH,
    MISSING_IDENTITY), or it names the missing reference and the loaded one does not
    (MISSING_COMPLETION_REFERENCE)."""
    found = _GAP_RE.match(line)
    if templates is None or not found or found.group(1) != f"docs/dev/completion-{name}.md":
        return False
    current, loaded = templates
    if found.group(2) in ("IDENTITY_MISMATCH", "MISSING_IDENTITY"):
        return bool(_identities(current)) and _identities(current) != _identities(loaded)
    reference = found.group(3)[len(REFERENCE_MESSAGE):] if found.group(3).startswith(REFERENCE_MESSAGE) else None
    return found.group(2) == "MISSING_COMPLETION_REFERENCE" and reference is not None and _names_reference(
        current, reference, name) and not _names_reference(loaded, reference, name)


# ---------------------------------------------------------------- the todo half
TASKS_OFF = ("0", "false", "no", "off")  # the CLI's false spellings for an env switch


def todo_gaps(span) -> list[str]:
    """A command with a canonical list (scripts/todo/<command>.py): the span's
    last ok TodoWrite that is its checklist (todo_canonical.checklist_lists: a
    list foreign to the command, which the validator admits only after the
    checklist is all completed, is never read in its place, OB-L40) has its
    contents and every step completed. Any other
    gated command: its last ok TodoWrite, if any, is all completed. A step
    whose section heading, as the command's text on disk words it, the span's
    loaded text does not hold (_loaded_lacks: added or rewritten since) is not
    that text's step and is not asked. Steps complete in order
    (pretool-todo-validate.py), so a later step the text has, completed,
    still holds every step before it."""
    switches = []
    if os.environ.get("CLAUDE_CODE_ENABLE_TODO_TOOLS") != "1":
        switches.append("todo tools disabled (CLAUDE_CODE_ENABLE_TODO_TOOLS)")
    # The CLI offers TodoWrite only while this switch reads false; unset or any other value gives the Task tools.
    if os.environ.get("CLAUDE_CODE_ENABLE_TASKS", "").strip().lower() not in TASKS_OFF:
        switches.append("task tools enabled (CLAUDE_CODE_ENABLE_TASKS is not false)")
    if switches:
        return switches
    todo_canonical = importlib.import_module("lib.todo_canonical")
    script, _project = todo_canonical._find_todo_script(span.command)
    current = span.last_todos()
    if script is not None:
        canonical = todo_canonical.run_todo_script(span.command, span.args)
        if not canonical:
            raise RuntimeError(f"{script} gave no canonical list")
        current = next((todos for _call, todos in todo_canonical.checklist_lists(span, canonical, newest_first=True)),
                       None)
        if current is None:
            return [f"todo: checklist never written ({len(canonical)} canonical steps)"]
        # The list the span is held to: the canonical one, or the span's first list, which
        # pretool-todo-validate admitted only as the canonical list of its time (D15: a span an older
        # harness opened keeps the list it started with when the canonical one has since changed).
        first = next(c.input["todos"] for c in span.calls("TodoWrite")
                     if c.ok and isinstance(c.input.get("todos"), list))
        if [t.get("content") for t in current] not in ([t.get("content") for t in canonical],
                                                        [t.get("content") for t in first]):
            return [f"todo: checklist differs from the canonical {len(canonical)} steps"]
    lacks = _loaded_lacks(span) if current else None
    return [f"todo: not completed: {t.get('content')}" for t in current or ()
            if not isinstance(t, dict) or t.get("status") != "completed" and not lacks(_step_heading(t))]


# ---------------------------------------------------------------- predicates
def _canonical(task: str) -> str:
    return importlib.import_module("lib.obligation").canonical_task_id(task) or task


def _path(arg: str) -> bool:
    return arg.endswith((".md", ".json")) or "/" in arg


def _task_of(path: str) -> str:
    """The id a path names: its basename's, from the timestamp on."""
    name = os.path.basename(path).removesuffix(".md").removesuffix(".json")
    return _canonical(name[name.find(importlib.import_module("lib.obligation").task_stamp(name) or name):])


def _typed(span) -> list[tuple[str, str]]:
    """(argument, task) of each typed task as close.md's Task-id resolution and
    commit.md's Step 1 read them (shell quoting; --reason's value is no task; a
    path names the id its basename holds from the timestamp on)."""
    args = shlex.split(span.args)
    return [(arg, _task_of(arg) if _path(arg) else _canonical(arg))
            for k, arg in enumerate(args) if not arg.startswith("-") and args[k - 1:k] != ["--reason"]]


def _targets(span, root, action: str) -> tuple[list[str] | None, list[str]]:
    """(targets, gaps) of a /close or a /commit, one rule for both (P5 review
    M, P5-4): the typed tasks (_typed), else the families the span's dispatches
    named; None: no task. A typed task that names no task or chain file
    (_resolves; close.md asks for one) yields to the families the span
    dispatched, the task the turn worked on the owner's answer, which no
    predicate reads (D23); with none dispatched, the gaps name it. --auto: the
    parents dev-lifecycle's --auto target function lists at the opener's
    cut-off (a fresh scan) and the families the span walked, which it stops
    listing once done; [] had none."""
    if "--auto" in shlex.split(span.args):
        lifecycle = _script("scripts/dev-lifecycle.py")
        return sorted(set(lifecycle.auto_targets(Path(root), action, span.opened_at())) | span.session_families()), []
    typed = _typed(span)
    held = [arg for arg, task in typed if not _resolves(root, arg, task)]
    if not held:
        return [task for _arg, task in typed] or sorted(span.session_families()) or None, []
    families = span.session_families()
    if not families:
        return None, [f"{action}: {arg} names no task or chain file, and no dispatch of this /{action} names a task"
                      for arg in held]
    return sorted({task for arg, task in typed if arg not in held} | families), []


# close.md's and commit.md's "Which task?": with no task bound and none dispatched, the run lists the candidates in
# one NO_TARGET: line and ends; the owner types the command again with an id. Nobody is asked.
NO_TARGET_LINE = re.compile(r"^NO_TARGET: \S", re.M)


STEP_REFUSED_LINE = re.compile(r"^REFUSED: (Step [0-9][0-9A-Za-z.]*)\b", re.M)  # dev.md, do.md: Hook rejection


def refused_step(span) -> str | None:
    """/dev, /redev, /dev-command, /do, /close: the pending step (the first not completed), when it was set in progress and a
    hook then refused its own call (command_span.refused_calls: a dispatch of its subagent_call's role with none of
    that role after it, or, with no role, the last call but TodoWrite and AskUserQuestion); else None."""
    step = next((t for t in span.last_todos() or () if t.get("status") != "completed"), {})
    if span.command not in ("dev", "redev", "dev-command", "do", "close") or not step.get("content"):
        return None
    denied = command_span.refused_calls(span.transcript_path)
    if not denied:  # no refusal on record: no walk
        return None
    canon = next((c for c in importlib.import_module("lib.todo_canonical").run_todo_script(span.command, span.args)
                  or () if c.get("content") == step["content"]), {}).get("subagent_call") or []
    roles = {c.get("subagent_type") for c in (canon if isinstance(canon, list) else [canon])}
    last = None  # read back from the end to the TodoWrite that last set the step in progress
    for use in span.uses(newest_first=True):
        if use.name == "TodoWrite":
            if use.ok and any((t.get("content"), t.get("status")) == (step["content"], "in_progress")
                              for t in use.input.get("todos") or ()):
                return str(step["content"]) if last else None
        elif last is None and use.name != "AskUserQuestion" and (not roles or use.input.get("subagent_type") in roles):
            last = use.id in denied
    return None  # never set in progress


def step_refused_end(span, step: str | None) -> bool:
    """``step`` (refused_step) is named by the last text's REFUSED: line: the turn ends there; the step stays open."""
    found = STEP_REFUSED_LINE.search(span.last_text() or "") if step else None
    return bool(found) and step.split(":", 1)[0] == found.group(1)


def _flags_refused(span) -> bool:
    """The typed flags combine as close.md and commit.md refuse before any action (dev-lifecycle's
    validate_auto_flag_combination: --auto with a task, --force or --bulk; close.md: --late-repair with --force)."""
    try:
        words = shlex.split(span.args)
    except ValueError:
        return False
    named = [w for k, w in enumerate(words) if not w.startswith("-") and (k == 0 or words[k - 1] not in ("--reason", "-m"))]
    return ("--auto" in words and bool(named or {"--force", "--bulk"} & set(words))) or (
        "--late-repair" in words and "--force" in words)


def no_target_end(span, root) -> bool:
    """A /close or /commit that bound no task and dispatched none ends on its NO_TARGET: line (close.md's and
    commit.md's "Which task?" and refused flag combinations; nobody is asked): the span's last main-agent text holds
    the line, the span dispatched no task, and its flags are refused or _targets binds no task it resolves. A run
    that worked on a task is never released by it. Likewise a /dev or /do typed with no text at all (dev.md Step 1,
    do.md: it ends saying how to type it)."""
    if span.command not in ("close", "commit", "dev", "do") or span.session_families() \
            or not NO_TARGET_LINE.search(span.last_text() or ""):
        return False
    if span.command in ("dev", "do"):
        return not span.args.strip()
    if _flags_refused(span):
        return True
    if "--bulk" in span.args.split():  # a legal --bulk binds no task by design: its own predicate holds it
        return False
    targets, unresolved = _targets(span, root, span.command)
    return bool(unresolved) or targets is None


def _resolves(root, arg: str, task: str) -> bool:
    """A typed task names a task or chain file: a path that exists (close.md
    verifies it), or an id a file under docs/dev holds as a path names it (its
    own or a lane's)."""
    if _path(arg):
        return (Path(root) / arg).is_file()
    try:
        names = os.listdir(Path(root) / "docs" / "dev")
    except OSError:
        return False
    family = importlib.import_module("lib.obligation").task_family
    return any(task in (held, family(held)) for held in map(_task_of, names))


def p_dev(span, root, payload) -> list[str]:
    """/dev, /redev, /dev-command: --stage dev chain_pass for each family the
    span dispatched and the opener's hook-minted id (D22: one predicate), and the extra QA round a low dev or BA owes (D32). A
    cycle on a text that predates this tree's (COMPATIBILITY, above) is asked
    under the name its text gives it, and not for a completion identity or
    reference its template never writes."""
    return _chain_gaps(span, root, payload) + importlib.import_module("lib.score_view").extra_round_gaps(span, root)


def _chain_gaps(span, root, payload) -> list[str]:
    families = span.session_families()
    if not families:
        return ["no pipeline dispatched"]
    minted = importlib.import_module("lib.obligation").task_family(span.minted_id())
    families |= {minted} if minted else set()
    names = _cycle_names(span)
    gaps = [(name, g) for family in sorted(families) for name in _names(names, family)
            for g in disposition(root, name, "dev")]
    if not any(f"GAP artifact=docs/dev/completion-{name}.md " in g for name, g in gaps):
        return [g for _name, g in gaps]
    cycles = _cycles(span)  # the span's own last: the text its cycle runs
    templates = _templates(cycles[-1][2] if cycles else None)
    return [g for name, g in gaps if not _unwritten(g, name, templates)]


def p_do(span, root, payload) -> list[str]:
    """/do: the do-report of the span's hook-minted id is a record (do_report.load, its one
    reading), do.status a terminal status of its schema (obligation.terminal_status, R21), and
    the chain's do branch holds (do_report_gaps: its schema, its lists equal to the write set, R8)."""
    task = span.minted_id()
    if not task:
        return ["do: the /do opener has no hook-minted task id ([/do] task-id minted: <id>)"]
    from lib import do_report  # the report's one reading (E8)
    rel = f"docs/dev/do-report-{task}.json"
    record, problem = do_report.load(Path(root) / rel)
    if record is None:
        return [f"{rel}: {problem}"]
    status = [] if importlib.import_module("lib.obligation").terminal_status("do-report.v1", record) else [
        f"{rel}: do.status is not a terminal status of schemas/do-report.v1.json"]
    chain = _script("scripts/resolve-dev-artifact-chain.py")
    return status + [f"{artifact}: {code}: {detail}" for code, artifact, detail in
                     chain.do_report_gaps(root, task, Path(root) / rel, span.transcript_path)]


def p_overnight(span, root, payload) -> list[str]:
    """/dev-overnight after its window: each family the span dispatched is
    chain_pass at the session's working root (P2's locator), the closeout is
    complete. An unanswered producer question is the disposition's gap."""
    overnight = importlib.import_module("lib.overnight")
    _state_file, record = overnight.locate(payload.get("session_id"), payload)
    if record is None:
        return [f"dev-overnight: no overnight state record for session {payload.get('session_id')}"]
    working = overnight.working_root(record)
    gaps = [g for family in sorted(span.session_families()) for g in disposition(working, family, "dev")]
    return gaps + list(overnight.closeout_gaps(record, working)) + importlib.import_module("lib.score_view").extra_round_gaps(span, working)


def p_close(span, root, payload) -> list[str]:
    """/close: --stage close per target (under its cycle's own name,
    _cycle_names), and the close-rating question asked
    (D9b: asked, not answered) where it is required and the span's loaded text
    asks it (a /close the session took up before the question was added to
    close.md never asks it: _loaded_lacks). Targets: _targets (a typed task
    that names no task or chain file yields to the families the span
    dispatched)."""
    targets, unresolved = _targets(span, root, "close")
    if unresolved:
        return unresolved
    if targets is None:
        return ["close: no target task resolved"]
    close_rating = importlib.import_module("lib.close_rating")  # P4's
    asks = not _loaded_lacks(span)(re.escape(RATING_SOURCE))
    names, gaps = _cycle_names(span), []
    owed = _owed_gap(span, root)
    refused = hook_refused_parents(span)[0] if "--auto" in span.args.split() else set()
    family = importlib.import_module("lib.obligation").task_family
    for task in (t for t in targets if family(t) not in refused):  # a parent a hook refused, reported
        gaps += [g for name in _names(names, task) for g in disposition(root, name, "close") if owed(name, g)]
        if asks and close_rating.rating_required(span, task) and not close_rating.rating_asked(
                span.transcript_path, task):
            gaps.append(f"close {task}: the close-rating question (AskUserQuestion) was not asked")
    return gaps


_GAP_ARTIFACT = re.compile(r'^GAP artifact=("(?:[^"\\]|\\.)*"|\S+) ')
NO_OWNER_LINE = re.compile(r"^NO_OWNER: (\S+)", re.M)


def _owed_gap(span, root):
    """close.md Routes' last bullet: a gap whose artifact no dispatch, lane, step or writer owes (the reader
    obligation.declaring_dispatch, which Routes runs, answers None), reported on a NO_OWNER: <artifact> line of the
    span's last text, is no longer owed by this run; nobody is asked, and the cycle stays unfinished. Every other
    gap is owed."""
    named = set(NO_OWNER_LINE.findall(span.last_text() or ""))
    reader = importlib.import_module("lib.obligation").declaring_dispatch

    def owed(task: str, gap: str) -> bool:
        found = _GAP_ARTIFACT.match(gap)
        path = found and (json.loads(found.group(1)) if found.group(1).startswith('"') else found.group(1))
        return not (path in named and reader(task, path, root) is None)
    return owed


def no_owner_end(span, root) -> bool:
    """A /close or /commit whose every open gap is an artifact nobody owes, reported (_owed_gap), ends there: the
    step that would produce it cannot run, so its checklist stays open and nothing marks it done."""
    if span.command not in ("close", "commit") or not NO_OWNER_LINE.search(span.last_text() or ""):
        return False
    targets, unresolved = _targets(span, root, span.command)
    owed, names = _owed_gap(span, root), _cycle_names(span)
    lines = [(name, g) for task in targets or () for name in _names(names, task) for g in disposition(root, name, span.command)]
    return not unresolved and bool(lines) and not any(owed(name, g) for name, g in lines)


# close.md Round-open: a cause in the environment that persists. The gate's own attempt is the fact, never a line.
ENV_ERRNOS = (errno.ENOSPC, errno.EDQUOT, errno.EROFS, errno.EACCES, errno.EPERM)
ENV_LINE = re.compile(r"^ENVIRONMENT: (E[A-Z]+) (/\S+)", re.M)


def environment_refusal(span, root) -> str | None:
    """/close: the line "ENVIRONMENT: <code> <directory>" when the gate's own attempt at what a close round needs,
    one byte written and synced to an unnamed temporary file in the project's docs/dev (the close report's
    directory; tempfile.TemporaryFile, which leaves no name and is gone on close), fails with the operating system's
    no-space, quota, read-only or permission error; else None (it succeeded, or failed otherwise)."""
    folder = os.path.join(root, "docs", "dev")
    if span.command != "close":
        return None
    try:
        with tempfile.TemporaryFile(dir=folder) as fh:
            fh.write(b"x")
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as exc:
        return f"ENVIRONMENT: {errno.errorcode[exc.errno]} {folder}" if exc.errno in ENV_ERRNOS else None
    return None


def environment_end(span, line: str | None) -> bool:
    """The last text holds the gate's own ENVIRONMENT: line (the same code and directory): the run ends there and
    the cycle stays unfinished; the next round follows once the cause is gone."""
    found, own = ENV_LINE.search(span.last_text() or ""), ENV_LINE.match(line or "")
    return bool(found and own) and found.group(1) == own.group(1) and \
        os.path.realpath(found.group(2)) == os.path.realpath(own.group(2))


# close.md Step 0: a disposition call that exits non-zero runs once more; failing again, the run ends with one
# OPERATION_STALLED: line and nothing else follows.
STALL_CALL = ("resolve-dev-artifact-chain.py", "--disposition")
STALL_LINE = re.compile(r"^OPERATION_STALLED: \S", re.M)


def close_stalled(span) -> bool:
    """A /close span that stalled at Step 0 as close.md says: its last two disposition calls (Bash
    naming STALL_CALL) came back as errors, and a main-agent text after the last one holds an
    OPERATION_STALLED: line. decision ends such a turn only when its own reading of the cycle fails
    as well; a gate that reads the cycle holds the Stop, and the call runs again."""
    if span.command != "close":
        return False
    calls = [use for use in span.uses("Bash", newest_first=True)
             if all(word in str(use.input.get("command") or "") for word in STALL_CALL)][:2]
    if len(calls) < 2 or any(use.ok or use.result_at is None for use in calls):
        return False
    try:  # the lines after the last call's own result (a path read on this rare path only)
        tail = Path(span.transcript_path).read_bytes()[calls[0].result_at:].split(b"\n")[1:]
    except OSError:
        return False
    for record in map(_json, tail):
        message = record.get("message")
        if record.get("type") != "assistant" or record.get("isSidechain") or not isinstance(message, dict):
            continue
        content = message.get("content")
        if any(isinstance(b, dict) and b.get("type") == "text" and STALL_LINE.search(b.get("text") or "")
               for b in (content if isinstance(content, list) else ())):
            return True
    return False


def _json(raw: bytes) -> dict:
    try:
        record = json.loads(raw)
    except ValueError:
        return {}
    return record if isinstance(record, dict) else {}


# push.md's dispatch protocol and merge.md's Refusals: a refusal is reported in the reply, never asked about.
# Step 5's call, by the script it runs.
PUSH_CALL, MERGE_CALL = "execute-push.py", "merge.sh"
_INTERPRETERS = {"python", "python3", "bash", "sh"}
_PUSH_FLAGS = ("--repo-hash", "--branch", "--remote", "--request-id", "--repo-root")  # push.md Step 5's call
_STEP5_PATHS = {PUSH_CALL: HARNESS / "scripts" / PUSH_CALL, MERGE_CALL: HOOKS / MERGE_CALL}  # <HARNESS_ROOT>/...


def step5_call(command: str, call: str, ref: str | None = None) -> bool:
    """``command`` runs Step 5's script ``call`` as push.md / merge.md write it, alone: one simple command (no
    list, pipe, subshell, second line or VAR=value prefix) whose command word, after an interpreter, is this
    harness's own script (<HARNESS_ROOT>/scripts/execute-push.py, <HARNESS_ROOT>/hooks/merge.sh, by a path that
    is absolute once ~, $HOME and ${CLAUDE_HOME:-$HOME/.claude} are expanded; line continuations joined); no --help or -h; execute-push.py with each of its required flags, merge.sh with one ref (and
    --no-commit), ``ref`` where given. Arguments end at a redirect (`2>&1`). A command that only mentions the
    script (`echo merge.sh; false`), another file of its name, or another ref is none."""
    command = re.sub(r"\\\n", " ", command)  # a line continuation, as push.md writes the call
    if "\n" in command.strip():
        return False
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        words = list(lexer)
    except ValueError:
        return False
    operator = lambda word: bool(word) and not word.strip("();<>|&")  # noqa: E731
    if any(operator(w) and any(c in w for c in ";|()") or w in ("&", "&&") for w in words):
        return False
    if words and re.match(r"[A-Za-z_][A-Za-z0-9_]*=", words[0]):
        return False  # GIT_DIR=... and the like run it elsewhere
    if words and os.path.basename(words[0]) in _INTERPRETERS:
        words = words[1:]
        while words and words[0].startswith("-"):
            words = words[1:]
    # the word as the shell expands it: ~, $HOME, ${CLAUDE_HOME:-$HOME/.claude} (claude_home.known_text)
    path = (importlib.import_module("lib.claude_home").known_text(words[0]) or "") if words else ""
    if not os.path.isabs(path) or os.path.realpath(path) != os.path.realpath(_STEP5_PATHS[call]):
        return False
    args = next((words[1:k] for k in range(1, len(words)) if operator(words[k])), words[1:])  # up to a redirect
    if len(args) < len(words) - 1 and args and args[-1].isdigit():
        args = args[:-1]  # the descriptor of `2>&1`
    if "--help" in args or "-h" in args:
        return False
    if call == PUSH_CALL:
        return all(flag in args for flag in _PUSH_FLAGS)
    rest = [a for a in args if a != "--no-commit"]
    return len(rest) == 1 and not rest[0].startswith("-") and (ref is None or rest[0] == ref)


def step5_refused(span, call: str, ref: str | None = None) -> bool:
    """Step 5's last run (a Bash running the script ``call``) came back as an error, and no later run of it came
    back ok. The refusal is reported, never asked about. The transcript's record only: a predicate ends its turn on
    it only where its own reading of git meets the same refusal now (a remote git ls-remote cannot read; the
    source's merge in conflict), as close_stalled does (D25: no agent action in the span clears it)."""
    refused = False
    for use in span.uses("Bash"):
        if use.result_at is not None and step5_call(str(use.input.get("command") or ""), call, ref):
            refused = not use.ok
    return refused


def _bulk_block(span, profile: str = "commit-bulk"):
    """The status block the analyst of the span's last ``profile`` dispatch
    reported when it stopped (its obligation's response_block,
    changelog-status.v1, checked at the analyst's own stop), or None: no such
    dispatch ran, or its analyst has not stopped. Its stop and reply are read
    as G1 reads them (lib/agent_returns.py): its Agent call's result, the
    task-notification of a background or resumed analyst, or a cut analyst's
    own recorded stop. A dispatch refused before it ran started no analyst."""
    blocks = _status_blocks(span, profile)
    return blocks[-1][1] if blocks else None


def _status_blocks(span, profile: str) -> list:
    """(the dispatch's obligation, its analyst's status block or None) for each ``profile`` dispatch whose
    analyst stopped, in order (_bulk_block's reading)."""
    returns, out = importlib.import_module("lib.agent_returns").Returns(span), []
    for call, doc in span.dispatches():
        if doc.get("profile") != profile or not (call.ok or returns.agent(call)):
            continue
        block = next((a for a in doc.get("artifacts") or () if a.get("kind") == "response_block"), {})
        begin, end, text = block.get("begin") or "", block.get("end") or "", returns.reply(call)
        try:
            found = json.loads(text.split(begin, 1)[1].split(end, 1)[0]) if begin and end and begin in text else None
        except ValueError:
            found = None
        out.append((doc, found if isinstance(found, dict) else None))
    return out


REFUSED_LINE = re.compile(r"^REFUSED: .* for task (\S+?)\.?$", re.M)


def hook_refused_tasks(span) -> set:
    """commit.md Step 7 (and its --auto walk): the tasks whose last commit-landing analyst reported `hook_blocked`
    (a hook refused its commit) and that a REFUSED: line of the span's text names (`... for task <id>`). Such a
    commit is not retried and nobody is asked: that task's landing is no longer owed by this run."""
    canon, last = importlib.import_module("lib.obligation").canonical_task_id, {}
    for doc, block in _status_blocks(span, "commit-landing"):
        last[canon(doc.get("task_id"))] = block
    named = {canon(t) for t in REFUSED_LINE.findall("\n".join(span.texts()))}
    return {t for t, block in last.items() if t in named and (block or {}).get("failure_code") == "hook_blocked"}


def hook_refused_parents(span) -> tuple:
    """close.md --auto and commit.md Step 7, a hook rejection: (named, unnamed) parents whose last dispatch (an Agent or Task call whose
    obligation names the parent's task) a hook refused (command_span.refused_calls), as their task families; named
    when a REFUSED: line of the span's text names the parent (`... for task <id>`). A named parent's close is no
    longer owed by the batch; the other parents' results stand."""
    ob = importlib.import_module("lib.obligation")
    denied = command_span.refused_calls(span.transcript_path)
    last = {}
    for call in span.iter_calls("Agent", "Task") if denied else ():
        found = ob.parse_obligation(call.input.get("prompt"))
        if isinstance(found, ob.ParsedObligation):
            last[ob.task_family(ob.canonical_task_id(found.obligation.get("task_id")))] = call.id in denied
    said = {ob.task_family(ob.canonical_task_id(t)) for t in REFUSED_LINE.findall("\n".join(span.texts()))}
    refused = {t for t, was in last.items() if was and t}
    return refused & said, refused - said


def p_commit(span, root, payload) -> list[str]:
    """/commit: --stage commit per target (a Task-id commit reachable from
    HEAD in each plan repository; under its cycle's own name, _cycle_names),
    the targets /close takes (_targets: a typed task that names no task or
    chain file yields to the families the span dispatched, P5-4);
    --bulk: the bulk status block reports a
    landing; --dry-run: nothing beyond the todo half. Modes only if typed."""
    args = span.args.split()
    if "--dry-run" in args:
        return []
    if "--bulk" in args:  # the schema's failure field is present exactly for a failed or partial commit
        block = _bulk_block(span)
        if block is None:
            return ["commit --bulk: no changelog-analyst status block in this /commit"]
        return [f"commit --bulk: changelog-analyst reports {block.get('commit_status')!r}: "
                f"{block.get('failure_code')} {block.get('failure_reason') or ''}".rstrip()] if "failure_code" in block else []
    targets, unresolved = _targets(span, root, "commit")
    if unresolved:
        return unresolved
    if targets is None:
        return ["commit: no target task resolved"]
    # Step 7: reported as refused, nobody asked; the other targets still land. Also a task whose own last dispatch a
    # hook refused (no analyst ran, so no status block), named on its REFUSED: line.
    refused = hook_refused_tasks(span) | hook_refused_parents(span)[0]
    canon, names = importlib.import_module("lib.obligation").canonical_task_id, _cycle_names(span)
    owed = _owed_gap(span, root)  # Routes: an artifact nobody owes, reported on its NO_OWNER: line
    family = importlib.import_module("lib.obligation").task_family
    return [g for task in targets if not {canon(task), family(canon(task))} & refused
            for name in _names(names, task) for g in disposition(root, name, "commit") if owed(name, g)]


# ---------------------------------------------------------------- git facts (merge, push)
def _reflog(root, ref: str) -> list[tuple[str, int, str]]:
    """(new value, time, message) of each reflog entry of ``ref``, newest first."""
    out = _git(root, "reflog", "show", "--date=unix", "--format=%H%x09%gd%x09%gs", ref, "--") or ""
    entries = []
    for line in out.splitlines():
        sha, selector, message = (line.split("\t", 2) + ["", ""])[:3]
        try:
            entries.append((sha, int(selector.rsplit("@{", 1)[1].rstrip("}")), message))
        except (IndexError, ValueError):
            continue
    return entries


def _value_at(entries, when: float) -> str | None:
    return next((sha for sha, t, _m in entries if t <= when), None)


def _ancestor(root, older: str, newer: str) -> bool:
    return subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", older, newer],
                          capture_output=True, timeout=20, env={**os.environ, **_GIT_ENV}).returncode == 0


def _since(span) -> float:
    opened = span.opened_at()
    if opened is None:
        raise ValueError("the opener's record carries no timestamp")
    return int(opened)  # reflog times are whole seconds


def _source_tips(root, ref: str, since: float) -> tuple:
    """The ref's value at the opener (else now), and the values git gives it
    from the opener on: that one, each later reflog value and its value now."""
    full = _git(root, "rev-parse", "--symbolic-full-name", "--verify", "-q", ref) or ref
    entries = _reflog(root, full)
    now = _git(root, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}")
    at = _value_at(entries, since) or now
    return at, {tip for tip in {sha for sha, t, _m in entries if t >= since} | {at, now} if tip}


def _bare_pick(root, since: float) -> str | None:
    """Step 0's pick for a bare /merge, from git's record: the branch HEAD
    was on at the opener (HEAD's reflog), else the current branch."""
    branch = None
    for _sha, t, message in reversed(_reflog(root, "HEAD")):  # oldest first
        if message.startswith("checkout: moving from "):
            source, _to, target = message[len("checkout: moving from "):].partition(" to ")
            branch = target if t <= since else (branch or source)
            if t > since:
                break
    return branch or _git(root, "symbolic-ref", "--short", "-q", "HEAD")


def _session_worktree(root, payload):
    """The worktree the session works in: its cwd when that is a worktree of the project's repository
    (/dev-overnight --worktree's Step 1 cds into the linked one, where /merge's Step 0 picks and merge.sh
    merges; the project dir stays the main checkout), else the project dir."""
    def common(path):
        found = _git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
        return os.path.realpath(found) if found else None
    top = _git(payload["cwd"], "rev-parse", "--show-toplevel") if payload.get("cwd") else None
    shared = common(top) if top else None
    return top if shared and shared == common(root) else root


def p_merge(span, root, payload) -> list[str]:
    """/merge [--no-commit] [<ref>] [INFERRED; A6]. Source: the typed ref, else
    the newest merge-analyst grant this session wrote here since the opener
    (checked against git on that Write; a bare /merge reads it first), else the
    bare pick from git; none if its value at the opener is no commit or
    DEFAULT_BRANCH's (Step 1's missing tip, self-merge). With no unmerged path:
    MERGE_HEAD (--no-commit, while present) is a value of the source; else a merge
    entry in DEFAULT_BRANCH's reflog after the opener has one as its merged parent
    (a fast-forward: as its new value), or the source's value at the opener is in
    DEFAULT_BRANCH ("Already up to date"), or this session's newest merge-analyst grant since the opener is
    `blocked` for the source at its tip now (Step 3 refuses; R14 leaves the risks to the owner, and a
    grant that fault() passed binds branch, source_tip and verdict); no source: no merge entry after it. All read in the
    session's worktree: a linked one keeps its own HEAD reflog, Step 0's pick, after the cleanup. Step 5's
    conflicts reported as refused (step5_refused) end it while MERGE_HEAD is at a value
    of the source, paths are unmerged and git's merge-tree of the two commits conflicts (_conflicts), the
    record being merge.sh on this source: the merge stands in conflict for the owner (aborted, it is owed
    again)."""
    _repository(root)
    root = _session_worktree(root, payload)
    args = span.args.split()
    refs = [a for a in args if not a.startswith("-")]
    since = _since(span)
    default = (subprocess.run(["bash", str(HARNESS / "scripts" / "derive-default-branch.sh")], cwd=str(root),
                              capture_output=True, text=True, timeout=20).stdout.strip())
    base, named = _source_tips(root, f"refs/heads/{default}", since)[0], refs[0] if refs else _bare_pick(root, since)
    grant = importlib.import_module("lib.merge_grant").newest(_git(root, "rev-parse", "--show-toplevel") or str(root),
                                       payload.get("session_id"), since)
    own = [(named, *_source_tips(root, named, since))] if named else []
    granted = [(grant.get("branch"), grant.get("source_tip"), {grant.get("source_tip")})]
    ref, at, tips = next((s for s in (own + granted if refs else granted + own) if s[1] not in (None, base)),
                         (named, None, set()))
    landed = [(sha, m) for sha, t, m in _reflog(root, f"refs/heads/{default}")
              if t >= since and m.startswith(("merge ", "commit (merge)"))]
    head = _git(root, "rev-parse", "--verify", "-q", "MERGE_HEAD") if "--no-commit" in args else None
    if head:
        gaps = [] if head in tips else [f"merge: MERGE_HEAD is {head}, not {ref}'s tip"]
    elif any(tips & {sha, *(_git(root, "rev-list", "--parents", "-n", "1", sha) or "").split()[2:]} if tips
             else m.startswith(f"merge {ref}:") for sha, m in landed) or (
            _ancestor(root, at, f"refs/heads/{default}") if at else not landed):
        gaps = []
    elif at and (grant.get("verdict"), grant.get("branch"), grant.get("source_tip")) == (
            "blocked", ref, _git(root, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}")):
        gaps = []  # Step 3: "merge-analyst blocked the merge"; the risks are the owner's to resolve (R14)
    else:
        gaps = [f"merge: no merge of {ref} into refs/heads/{default} after the /merge opener" if at else
                f"merge: refs/heads/{default} took a merge after the opener; no merge-analyst grant of this "
                "session since the opener names its source"]
    if _git(root, "ls-files", "-u"):
        gaps.append("merge: unmerged paths remain in the index")
    merging = _git(root, "rev-parse", "--verify", "-q", "MERGE_HEAD")
    if gaps and tips and merging in tips and _git(root, "ls-files", "-u") and _conflicts(
            root, f"refs/heads/{default}", merging) and step5_refused(span, MERGE_CALL, ref):
        return []  # Step 5: the source's merge stands in conflict; merge.sh refused, reported
    return gaps


def _conflicts(root, default: str, source: str) -> bool:
    """HEAD is on ``default`` and git's own three-way merge of it with ``source`` conflicts (git merge-tree
    --write-tree exits 1): from the commits alone, so no index entry or MERGE_HEAD an agent writes makes one."""
    if _git(root, "symbolic-ref", "-q", "HEAD") != default:
        return False
    try:
        done = subprocess.run(["git", "-C", str(root), "merge-tree", "--write-tree", "--no-messages", default, source],
                              capture_output=True, timeout=60, env={**os.environ, **_GIT_ENV})
    except subprocess.TimeoutExpired:
        return False
    return done.returncode == 1


def _opener_branch(root, since: float) -> str | None:
    """The branch HEAD was on at the opener, from git's record: the source of
    HEAD's first checkout at or after it (git names a detached HEAD there by its
    full hash; a checkout in the opener's second counts as after it), else
    HEAD's branch now; None: detached."""
    for _sha, t, message in reversed(_reflog(root, "HEAD")):  # oldest first
        if t >= since and message.startswith("checkout: moving from "):
            source = message[len("checkout: moving from "):].partition(" to ")[0]
            return None if len(source) in (40, 64) and not source.strip("0123456789abcdef") else source
    return _git(root, "symbolic-ref", "--short", "-q", "HEAD")


def p_push(span, root, payload) -> list[str]:
    """/push [<remote>] [INFERRED; A6]. BRANCH and the opener's commit: those of
    each HEAD line in the opener's hook context (prompt-workflow.py
    print_push_head, through command_span: a line another hook echoes adds one
    to judge and takes none away); detached there: HEAD's branch now, no commit.
    An opener with none (typed before the hook printed it, D25) takes git's
    record: the branch HEAD was on at the opener (HEAD's reflog), else HEAD's
    branch now. A remote "took" a commit after the opener when its branch
    BRANCH holds it now, as the remote itself lists it (git ls-remote at the
    URL the opener's remote line records, outside the repository's settings),
    and did not by that line's record of its tracking ref (P5-61: no local
    refs/remotes value, reflog entry, upstream setting, replace object or graft
    an agent writes or redirects counts; an opener without remote lines takes
    the URL, tracking ref and upstream from the repository). BRANCH's tip is
    published when a remote (the typed one, else any the opener recorded: a
    typed name that is no remote of the repository, which push.sh refuses,
    ends the run: reported, nobody asked) took it or a value
    the branch had from the opener on; or it is at or behind the typed remote's
    branch (none typed: BRANCH's upstream at the opener; none for such a name);
    or push.md refuses the
    push: HEAD detached at the opener and now (Step 2), no push-gate token names
    an ancestor of it (push.sh's exit 3: its READ side over the path of the
    token's one writer), or this session's newest push-analyst grant here since
    the opener is blocked for BRANCH at it (Step 5: execute-push.py refuses it
    and leaves it unspent). The opener's commit, where the tip does not hold it,
    is published where that branch holds it or a remote took it. The token and
    the grant are protected
    for every caller but their producers (pretool-tool-policy.py), and a detach,
    reset or rewrite after the opener is no refusal: no agent's act makes one true. Step 5 refused
    (step5_refused: push.sh's exit 1) ends it too while git ls-remote reads
    none of the remotes judged at the URLs the opener's remote lines recorded, also with no system or global
    configuration (_unreachable); one that lists, a URL changed since, or an opener without remote lines
    holds it."""
    _repository(root)
    typed = next((a for a in span.args.split() if not a.startswith("-")), None)
    since, now = _since(span), _git(root, "symbolic-ref", "--short", "-q", "HEAD")
    heads = span.opener_heads()
    opened = [(b, c) for b, c in heads if b] or [((None if heads else _opener_branch(root, since)) or now, None)]
    again = step5_refused(span, PUSH_CALL)
    return [gap for branch, commit in dict.fromkeys(opened) if branch  # none: Step 2, "HEAD is detached"
            for gap in _push_gaps(root, payload, typed, since, now, branch, commit, span.opener_remotes(), again)]


# The environment of the reading that confirms an unreachable remote (_unreachable): no git variable of the
# process and no system or global configuration, which an agent can write (protocol.allow=never, an http.proxy,
# core.sshCommand=false), and no prompt.
_ISOLATED = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
             "GIT_ASKPASS": "", "SSH_ASKPASS": "", **_GIT_ENV}
# Its failures that say nothing of the remote's reachability: credentials it cannot give, a prompt it disables.
_NOT_REACH = re.compile(r"terminal prompts disabled|could not read (?:username|password)|authentication failed|"
                        r"permission denied|host key verification failed|access denied|returned error: 40[13]", re.I)


def _remote_tip(top: str, url: str, ref: str, isolated: bool = False) -> tuple:
    """(the commit the remote at ``url`` names ``ref`` by now, None: none; why it could not be read, '')
    as the remote lists it: git ls-remote run outside the repository, so no setting of it (a URL
    rewrite, an upload-pack or ssh command) answers; a local path is taken from the repository's top.
    ``isolated``: with no GIT_* variable of the process and no system or global configuration (_ISOLATED)."""
    if "://" not in url and not re.match(r"[^/]+:", url):
        url = os.path.join(top, url)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")} if isolated else dict(os.environ)
    try:
        done = subprocess.run(["git", "ls-remote", "--", url, ref], cwd="/", capture_output=True, text=True,
                              timeout=20, env={**env, **(_ISOLATED if isolated else _GIT_ENV)})
    except subprocess.TimeoutExpired:
        return None, "git ls-remote timed out"
    if done.returncode:
        said = [line.strip() for line in done.stderr.splitlines() if line.strip()]
        return None, "git ls-remote: " + next((line for line in said if line.startswith(("fatal:", "error:"))),
                                              said[0] if said else "failed")
    return next((line.split("\t")[0] for line in done.stdout.splitlines() if line.endswith("\t" + ref)), None), ""


def _unreachable(top: str, url: str, ref: str) -> bool:
    """git ls-remote, isolated from every configuration an agent writes (_ISOLATED), cannot read the remote at
    ``url`` either, and not for want of credentials or a prompt (_NOT_REACH): Step 5's push.sh exit 1 is the
    remote's, not a setting's."""
    held, why = _remote_tip(top, url, ref, isolated=True)
    return held is None and bool(why) and not _NOT_REACH.search(why)


def _push_gaps(root, payload, typed, since, now, branch, opened, pinned, again=False) -> list[str]:
    """p_push's gaps for BRANCH at its tip and at the opener's commit (``opened``, None: none recorded);
    ``pinned``: the opener's remote lines (None: none printed); ``again``: step5_refused for Step 5."""
    head = _git(root, "rev-parse", "--verify", "-q", f"refs/heads/{branch}^{{commit}}")
    if not head:
        return [f"push: {branch}, the branch HEAD was on at the /push opener, names no commit; nothing of it "
                "is published since the opener"]
    local, remotes = _reflog(root, f"refs/heads/{branch}"), (_git(root, "remote") or "").split()
    unknown = typed if typed and typed not in remotes else None
    considered = [r for r in ([typed] if typed and not unknown else remotes) if pinned is None or r in pinned]
    if typed or pinned is not None:
        up = (typed, f"refs/heads/{branch}") if typed else next(
            ((r, record[3]) for r, record in pinned.items() if record[1] == branch and record[3]), None)
    else:
        up = tuple((_git(root, "for-each-ref", "--format=%(upstream:remotename) %(upstream:remoteref)",
                         f"refs/heads/{branch}") or "").split())
    up = up if up and len(up) == 2 and up[0] in remotes and (pinned is None or up[0] in pinned) else None
    top, gaps, tips, errors = _git(root, "rev-parse", "--show-toplevel") or str(root), [], {}, {}
    unread, urls = set(), {}  # remotes git ls-remote could not read at the URL the opener recorded, and that URL

    def tip(remote, ref):
        if (remote, ref) not in tips:
            url = _git(root, "remote", "get-url", remote) or ""
            if pinned is not None and hashlib.sha256(url.encode()).hexdigest()[:16] != pinned[remote][0]:
                tips[(remote, ref)], errors[remote] = None, "its URL is not the one it had at the /push opener"
            else:
                tips[(remote, ref)], why = _remote_tip(top, url, ref)
                if why and tips[(remote, ref)] is None:
                    unread.add(remote)
                    urls[remote] = url
                if tips[(remote, ref)] and _git(root, "cat-file", "-e", f"{tips[(remote, ref)]}^{{commit}}") is None:
                    why = f"its {ref} is at {tips[(remote, ref)]}, which this repository lacks: fetch {remote}"
                errors.update({remote: why} if why else {})
        return tips[(remote, ref)]

    def took(commit, remote):
        held = tip(remote, f"refs/heads/{branch}")
        at = (pinned[remote][2] if pinned[remote][1] == branch else None) if pinned is not None else _value_at(
            _reflog(root, f"refs/remotes/{remote}/{branch}"), since)
        return bool(held) and _ancestor(root, commit, held) and not (at and _ancestor(root, commit, at))

    values = {head, _value_at(local, since)} | {sha for sha, t, _m in local if t >= since}
    for commit in [head] + ([opened] if opened and not _ancestor(root, opened, head) else []):
        if unknown:
            continue  # push.sh refuses a typed name git lists as no remote; reported, nobody asked (push.md)
        if (up and tip(*up) and _ancestor(root, commit, tip(*up))) or any(
                took(value, remote) for remote in considered for value in (values if commit == head else {commit})
                if value):
            continue
        token = _script("scripts/write-push-gate-token.py").token_path(top, branch, "")  # <repo dir>/<session>/<name>
        for path in [token.parent.parent / token.name, *token.parent.parent.glob(f"*/{token.name}")]:
            try:
                sha = json.loads(path.read_text()).get("commit_sha")
            except (OSError, ValueError, AttributeError):
                continue  # "Malformed/unparseable candidates are skipped"
            if sha and _ancestor(root, str(sha), commit):
                break
        else:
            continue  # Step 5: push.sh's exit 3, "run /commit first"
        grant = importlib.import_module("lib.merge_grant").newest(top, payload.get("session_id"), since, "push-analyst")
        if (grant.get("verdict"), grant.get("branch"), grant.get("head_sha")) == ("blocked", branch, commit):
            continue  # Step 5: "push BLOCKED by push-analyst"
        if again and pinned is not None and considered and all(
                tip(r, f"refs/heads/{branch}") is None and r in unread
                and _unreachable(top, urls[r], f"refs/heads/{branch}") for r in considered):
            continue  # Step 5: push.sh's exit 1, reported; no remote it judges reads now
        ref = up and f"refs/remotes/{up[0]}/{up[1].removeprefix('refs/heads/')}"
        fix = ("" if now == branch else f"; HEAD is not on it: check out {branch}") + (
            "" if commit == head else f"; {branch} is at {head}, which does not hold it: put {branch} back at it")
        gaps.append(f"push: {branch} at {commit} is not published on {ref or 'a remote'} since the /push opener"
                    + "".join(f"; {remote}: {why}" for remote, why in errors.items())
                    + (fix and fix + ", then push it"))
    return gaps


def p_text_question(span, payload) -> list[str]:
    """R7 (D28): in a /spec or /dev-family span, a turn whose last main-agent text ends with a question asks it in
    text, unless every question of that line was already asked or recorded in the span (_settled). The agent
    actions that clear it: asking with AskUserQuestion and getting the owner's answer, recording the question in
    the spec through spec-write.py, or ending without the question."""
    text = payload.get("last_assistant_message")
    text = span.last_text() if text is None else text
    if not _lib_round().ends_with_question(text) or _settled(span, payload, text):
        return []
    return [f"{span.command}: the turn ends with a question in text; end without it (the owner is asked only in a requirement round)."]


SPEC_WRITER = HARNESS / "scripts" / "spec-write.py"
SPECS_DIR = "docs/dev/specs"
_RECORD_LIMIT = 4 << 20  # a spec larger than this is not read for a recorded question
_SHELL_OPS = frozenset(("&&", "||", ";", "|", "&"))
_INTERPRETER = re.compile(r"(?:\S*/)?python3?(?:\.[0-9]+)?")
_WRITER_LINE = command_span.SPEC_WRITER_LINE
_ITEM = re.compile(r"^(?:(?:[-*+]|[0-9]+[.)])\s+)?(?:\[[ xX]\]\s+)?")
_EDIT_TOOLS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path"}
_UNANSWERED = re.compile(r"rejected|doesn't want to proceed|did not answer|skipped", re.I)


def _settled(span, payload, text) -> bool:
    """Every question the text's last line asks (requirement_round.line_questions: each "?" sentence, or the text
    after its last ": " when the label before it asks nothing) is one the span already asked or recorded, so the
    line reports it rather than asks it:
      asked     a form equals a questions[].question of a main-agent AskUserQuestion of this span that the owner
                answered (_answered);
      recorded  a form equals a whole line, or a list item's text, of a spec this span wrote (_span_specs).
    A previous span's AskUserQuestion or write never counts; a line with a bare "?" is never settled."""
    questions = _lib_round().line_questions(text)
    if not questions:
        return False
    asked = _answered(span)
    pending = [forms for forms in questions if not asked.intersection(forms)]
    if not pending:
        return True
    root = os.path.realpath(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd())
    recorded = set()
    for spec in _span_specs(span, root):
        try:
            if os.path.getsize(spec) <= _RECORD_LIMIT:
                recorded |= {_ITEM.sub("", line.strip(), count=1).strip()
                             for line in Path(spec).read_text(encoding="utf-8", errors="replace").splitlines()}
        except OSError:
            continue
    return all(recorded.intersection(forms) for forms in pending)


def _answered(span) -> set:
    """The questions the owner answered in the span: each questions[].question of a main-agent AskUserQuestion with
    an ok tool_result whose recorded response (the CLI's toolUseResult) holds a non-empty answer to it, no
    afkTimeoutMs or followUp, no annotation marking it unanswered, and no rejection in the result text, as
    requirement_round.handle and close_rating.handle read a response; a rejection, Skip, AFK or error answers none."""
    found = set()
    for use in span.uses("AskUserQuestion"):
        if not use.ok or use.result_at is None:
            continue
        response = command_span.recorded_result(span.transcript_path, use)
        answers, notes = response.get("answers"), response.get("annotations")
        if not isinstance(answers, dict) or response.get("afkTimeoutMs") or response.get("followUp") \
                or _UNANSWERED.search(span.result_text(use.id)):
            continue
        for question in use.input.get("questions") or ():
            asked = question.get("question") if isinstance(question, dict) else None
            note = notes.get(asked) if isinstance(notes, dict) and isinstance(asked, str) else None
            if isinstance(asked, str) and isinstance(answers.get(asked), str) and answers[asked].strip() \
                    and not (isinstance(note, dict) and note.get("unanswered")):
                found.add(asked.strip())
    return found


def _in_specs(path: str, root: str) -> str | None:
    """The real path of a spec monolith (a .md file directly in the project's docs/dev/specs/), else None."""
    real = os.path.realpath(path if os.path.isabs(path) else os.path.join(root, path))
    specs = os.path.join(root, SPECS_DIR)
    return real if os.path.dirname(real) == specs and real.endswith(".md") and os.path.isfile(real) else None


def _span_specs(span, root: str) -> set:
    """The specs the span wrote: the --spec of each Bash call of the span with an ok result that runs the harness's
    scripts/spec-write.py (an interpreter at a command's start, then the writer by its real path), named again by
    the writer's own `spec-write: <create|append> <path>` line in that result; and each ok Write, Edit or MultiEdit
    target. Each must resolve, symlinks followed, to a spec in the project's docs/dev/specs/ (_in_specs). A path
    a command merely names is no write."""
    found = set()
    writer = os.path.realpath(SPEC_WRITER)
    for call in span.calls("Bash"):
        command = call.input.get("command")
        if not call.ok or not isinstance(command, str):
            continue
        printed = {os.path.realpath(p.strip()) for p in _WRITER_LINE.findall(span.result_text(call.id))}
        for arg in _spec_args(command, writer):
            real = _in_specs(arg, root)
            if real is not None and real in printed:
                found.add(real)
    for call in span.calls(*_EDIT_TOOLS):
        target = call.input.get(_EDIT_TOOLS[call.name])
        real = _in_specs(target, root) if call.ok and isinstance(target, str) and target else None
        if real is not None:
            found.add(real)
    return found


def _spec_args(command: str, writer: str) -> list[str]:
    """The --spec values of the spec-write.py runs in a shell command's lines up to its first heredoc."""
    found = []
    for line in command.splitlines():
        try:
            tokens = shlex.split(line.split("<<", 1)[0])
        except ValueError:
            tokens = []
        start = True
        for k, token in enumerate(tokens):
            if token in _SHELL_OPS:
                start = True
                continue
            if start and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", token):
                continue
            if start and _INTERPRETER.fullmatch(token) and k + 1 < len(tokens) \
                    and os.path.realpath(os.path.expanduser(tokens[k + 1])) == writer:
                rest = tokens[k + 2:]
                for j, arg in enumerate(rest):
                    if arg in _SHELL_OPS:
                        break
                    if arg == "--spec" and j + 1 < len(rest):
                        found.append(rest[j + 1])
                    elif arg.startswith("--spec="):
                        found.append(arg[len("--spec="):])
            start = False
        if "<<" in line:
            break
    return found


def _lib_round():
    return importlib.import_module("lib.requirement_round")


PREDICATES = {
    "dev": p_dev, "redev": p_dev, "dev-command": p_dev, "do": p_do, "dev-overnight": p_overnight,
    "close": p_close, "commit": p_commit, "merge": p_merge, "push": p_push,
}


# ---------------------------------------------------------------- the time-lock (4)
def window_lock(payload, record):
    """(2, the block text with the time left, None) while the session's overnight
    window is open (P2's overnight.window_open), else None."""
    overnight = importlib.import_module("lib.overnight")
    if overnight.window_open(payload):
        end = overnight.parse_end_time(record.get("end_time"))
        left = max(0, int((end - datetime.now(timezone.utc)).total_seconds()) // 60) if end else 0
        return (2, f"COMMAND_GATE time-lock: overnight window open until "
                   f"{end.strftime('%Y-%m-%dT%H:%M:%SZ') if end else record.get('end_time')}, "
                   f"{left // 60}h {left % 60}m left; continue the remaining pipelines\n", None)
    return None


def wake_lock(transcript: str):
    """(2, the block text naming the job, None) while the session's wake
    (a CronCreate of overnight.WAKE_PROMPT) has no later CronDelete
    (overnight.open_wakes, P1c X8), else None: a wake left scheduled would
    fire into the ended session."""
    jobs = importlib.import_module("lib.overnight").open_wakes(transcript)
    if jobs:
        return (2, f"COMMAND_GATE time-lock: the session's wake, CronCreate job {', '.join(jobs)}, has no later "
                   "CronDelete; call CronDelete with that id, then end the session\n", None)
    return None


def time_lock(payload) -> tuple:
    """Step (4) as (exit code, stderr text, terminal status): a block while
    the window is open, or after it has closed (end_time with the closeout
    complete, or the human's /stop) while the wake is scheduled; else exit 0
    with the session's terminal time-lock status once its window has closed
    (completed_by_deadline, or cancelled_by_user after /stop), None for a
    session with no overnight record or an incomplete closeout. Codex-native
    Stop owns overnight isolation in Codex roots, so the Codex runtime meets
    none."""
    if os.environ.get("CLAUDE_COMPAT_RUNTIME") == "codex":
        return 0, "", None
    overnight, transcript = importlib.import_module("lib.overnight"), payload.get("transcript_path") or ""
    # The session's own record, as P2's overnight.locate finds it (session_state_file from
    # CLAUDE_PROJECT_DIR, then the payload's cwd): a session with none meets no window rule.
    _state_file, record = overnight.session_state_file(
        payload.get("session_id"), (os.environ.get("CLAUDE_PROJECT_DIR"), payload.get("cwd") or os.getcwd()))
    if record is None:
        return 0, "", None
    lock = window_lock(payload, record)
    if lock:
        return lock
    released = command_span.timelock_released(transcript)
    if not released and overnight.closeout_gaps(record, overnight.working_root(record)):
        return 0, "", None
    lock = wake_lock(transcript)
    if lock:
        return lock
    return 0, "", "cancelled_by_user" if released else "completed_by_deadline"


# ---------------------------------------------------------------- the decision
def _mode(argv) -> str:
    for k, arg in enumerate(argv):
        value = arg.split("=", 1)[1] if arg.startswith("--mode=") else (
            argv[k + 1] if arg == "--mode" and k + 1 < len(argv) else None)
        if value in MODES:
            return value
    return "block"


BLOCK_BOUND = 8000  # characters; no cap was seen in the CLI's delivery (14 kB Stop, 38 kB refusals arrived whole)
_GAP_KIND = re.compile(r"^GAP artifact=\S* problem=([A-Z_]+)\b.* lane=(\S+)$")


def _block_text(command: str, gaps: list[str], hint: str = "", session=None) -> str:
    """Today's text when it fits BLOCK_BOUND. Else: the lines that are not GAP lines (the todo lines) and the
    hint, then the GAP lines counted by (problem, lane) with a sample while room is left, then how many lines were
    left out and the call that prints them all. Nothing is written."""
    finish = ("Decide each open question yourself (an experiment, else the default) and record the decision."
              if command == "dev-overnight" else
              "What a rule refuses is reported as refused, with the hook's output; nobody is asked about it.")
    head, tail = f"COMMAND_GATE /{command}: not complete\n", f"Finish the gaps above. {finish}\n"
    listing = "".join(f"- {gap}\n" for gap in gaps)
    if len(head) + len(listing) + len(tail) + len(hint) <= BLOCK_BOUND:
        return head + listing + tail + hint
    groups, other = {}, []
    for gap in gaps:
        kind = _GAP_KIND.match(gap)
        (groups.setdefault(kind.groups(), []) if kind else other).append(gap)
    room = BLOCK_BOUND - len(head) - len(tail) - 400
    out, shown = [head], 0
    for n, line in enumerate(other):  # the non-GAP lines keep at most half the room
        if sum(map(len, out)) + len(line) > room // 2:
            out.append(f"- ... {len(other) - n} more lines\n")
            break
        out.append(f"- {line[:400]}\n")
        shown += 1
    out.append(hint)
    order = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    counts = [f"- {len(lines)} x problem={kind} lane={lane}\n" for (kind, lane), lines in order]
    out.append(f"{sum(map(len, groups.values()))} GAP lines in {len(groups)} groups (problem, lane):\n")
    room -= sum(map(len, out))
    for count, (_key, lines) in zip(counts, order):
        sample = f"    e.g. {lines[0][:300]}\n"
        if room < len(count):
            out.append(f"- ... {len(order) - counts.index(count)} more groups\n")
            break
        shown += bool(room >= len(count) + len(sample))
        out.append(count + (sample if room >= len(count) + len(sample) else ""))
        room -= len(out[-1])
    left = (f"{len(gaps) - shown} of the {len(gaps)} lines were left out above; Step 0's disposition call "
            "(scripts/resolve-dev-artifact-chain.py --disposition) prints every GAP line of a task.\n")
    return "".join(out) + left + tail


def decide(payload: dict, mode: str = "block") -> tuple[int, str]:
    """(exit code, stderr text) of one Stop."""
    return decision(payload, mode)[:2]


def decision(payload: dict, mode: str = "block") -> tuple[int, str, str | None]:
    """(exit code, stderr text, terminal time-lock status of an allowed Stop
    or None) of one Stop."""
    if payload.get("agent_id"):  # (1)
        return 0, "", None
    if mode == "off":  # (2)
        return 0, "", None
    transcript = payload.get("transcript_path") or ""
    span = command_span.active_span(transcript) if transcript else None  # (3)
    gated = span is not None and span.command in command_span.GATED_COMMANDS
    # /spec: R7 alone, never gated; a session whose loaded text asks no round is not held to R7
    asking = span is not None and _lib_round().runs_round(span)
    try:  # (4)
        lock = time_lock(payload)
    except Exception as exc:  # a window it cannot read holds in any span and mode, as an open one does
        if not (transcript and command_span.timelock_released(transcript)):
            return 2, (f"COMMAND_GATE time-lock: gate instrument failure: {type(exc).__name__}: {exc}; "
                       "the human can type /stop\n"), None
        lock = (0, "", None)
    if lock[0] == 2:
        return lock
    terminal = lock[2]
    if not gated and not asking:  # (5)
        return 0, "", terminal
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    refused = env = analyst = None
    try:
        refused = refused_step(span) if gated else None  # one walk: the release below and the block's exit line
        env = environment_refusal(span, root) if gated else None  # the gate's own attempt, read once
        analyst = analyst_refused(span) if gated else None
        if gated and (no_target_end(span, root) or step_refused_end(span, refused) or no_owner_end(span, root)
                      or environment_end(span, env) or analyst_refused_end(span, analyst)):
            return 0, "", terminal
    except Exception:  # an unread record releases nothing: the gaps below decide
        pass
    gaps, unread = [], False
    for predicate, part in (((False, lambda: todo_gaps(span)),
                             (True, lambda: PREDICATES[span.command](span, root, payload))) if gated else ()) \
            + (((False, lambda: p_text_question(span, payload)),) if asking else ()):  # (6)
        try:
            gaps += part()
        except Exception as exc:
            unread = unread or predicate
            gaps.append(f"gate instrument failure: {type(exc).__name__}: {exc}")
    if unread and close_stalled(span):  # the predicate cannot read the cycle the run stalled on
        return 0, "", terminal
    if not gaps:  # (7)
        return 0, "", terminal
    text = _block_text(span.command, gaps, _exit_hint(span, refused, env) + (
        f"A hook refused the {analyst} dispatch. To end the turn, write the line \"REFUSED: <hook> refused the "
        f"{analyst} dispatch; nothing was {'published' if span.command == 'push' else 'merged'}\", then the "
        "hook's own output.\n" if analyst else ""), payload.get("session_id"))
    if mode == "advisory":
        return 0, "would block\n" + text, terminal
    return 2, text, None


def analyst_refused(span) -> str | None:
    """/push, /merge: the command's own analyst (the role of the dispatch template commands/<command>.md declares
    for its own pipeline, read by lib/dispatch_template), when a hook refused its last dispatch
    (command_span.refused_calls): no grant is written and Step 5 cannot run; else None."""
    if span.command not in ("push", "merge"):
        return None
    fences = importlib.import_module("lib.dispatch_template")._parsed_fences(
        (command_span.COMMANDS_DIR / f"{span.command}.md").read_text(encoding="utf-8"))
    roles = {kind for _body, kind, _roles, _profiles, example in fences
             if f'"pipeline": "{span.command}"' in (example or "")}
    last = next((c for c in span.iter_calls("Agent", "Task", newest_first=True)
                 if c.input.get("subagent_type") in roles), None)
    return last.input["subagent_type"] if last is not None and last.id in command_span.refused_calls(
        span.transcript_path) else None


def analyst_refused_end(span, role: str | None) -> bool:
    """``role`` (analyst_refused) is named by a REFUSED: line of the last text: the run ends, nothing published or
    merged."""
    return bool(role) and bool(re.search(rf"^REFUSED: .*\b{role}\b", span.last_text() or "", re.M))


def _exit_hint(span, refused, env) -> str:
    """What the block adds where an exit holds but its line is not yet written: the exact line, filled in."""
    hint = (f"A hook refused this step's own call. To end the turn, write the line \"REFUSED: {refused}\", then the "
            "hook's own output; the step stays open and the next prompt resumes it.\n" if refused else "")
    hint += (f"The gate's own write to the close report's directory failed. To end the turn, write the line "
             f"\"{env}\"; the cycle stays open and the next round follows once the cause is gone.\n" if env else "")
    try:
        unnamed = hook_refused_parents(span)[1] if span.command == "close" and "--auto" in span.args.split() else ()
    except Exception:  # an unread record adds no hint
        unnamed = ()
    return hint + "".join(f"A hook refused the last dispatch for parent {task}. To end its part of the batch, write the "
                          f"line \"REFUSED: <hook> refused <the call> for task {task}\", then the hook's own output; the "
                          "other parents' results stand.\n" for task in sorted(unnamed))


def main(argv=None) -> int:
    """stdin: the Stop payload. stderr: the block text. stdout, on an allowed
    Stop of a session whose overnight window has closed: one JSON line
    {"timelock_terminal": <status>}, the decision the coordinator's terminal
    receipt call takes (R9); nothing otherwise."""
    argv = sys.argv[1:] if argv is None else argv
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        payload = {}
    code, text, terminal = decision(payload if isinstance(payload, dict) else {}, _mode(argv))
    sys.stderr.write(text)
    if terminal:
        sys.stdout.write(json.dumps({"timelock_terminal": terminal}) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
