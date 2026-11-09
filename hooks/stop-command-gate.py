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
  (6) the gaps: in a /spec or /dev-family span the text question (R7, p_text_question; /spec has no
      other gap); in a gated span the todo half and the command's predicate, each held to the
      command's text as the span loaded it (_loaded_lacks: a step or the
      close-rating question an update added or reworded after the session
      loaded its text is not asked of it; a cycle whose loaded text names or
      writes its artifacts otherwise than this tree's is asked as that text
      does, COMPATIBILITY below); an exception is the gap
      `gate instrument failure: <type>: <message>`, never an allow;
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
tool result. The gate writes nothing but its own output (stdout:
the terminal time-lock status of an allowed Stop, see main), keeps no count
and has no release but the work itself: the next compliant step clears each
gap. The human's /stop opens a span that is not gated, and nothing here
offers a stop.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HOOKS = Path(__file__).resolve().parent
HARNESS = HOOKS.parent
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from lib import command_span  # noqa: E402  (the one transcript reader)

MODES = ("block", "advisory", "off")
_SCRIPTS: dict = {}


def _script(rel: str):
    """A harness script loaded by path, once per process."""
    if rel not in _SCRIPTS:
        spec = importlib.util.spec_from_file_location(f"_gate_script_{len(_SCRIPTS)}", HARNESS / rel)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _SCRIPTS[rel] = module
    return _SCRIPTS[rel]


def _git(root, *args: str) -> str | None:
    """git's stripped stdout in ``root``; None when it fails."""
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=20)
    return done.stdout.strip() if done.returncode == 0 else None


def _repository(root) -> None:
    """A predicate on git facts reads a repository, else its gap is an instrument failure."""
    if _git(root, "rev-parse", "--git-dir") is None:
        raise RuntimeError(f"{root} is not a git repository")


# ---------------------------------------------------------------- P3's disposition
def disposition(root, task: str, stage: str) -> list[str]:
    """The task's disposition at ``stage`` as gap lines, [] for chain_pass:
    the one adapter, the chain's own disposition_lines (over P3's
    `disposition(project_root, task_id, stage)`), used verbatim. Its
    instrument failure raises."""
    return _script("scripts/resolve-dev-artifact-chain.py").disposition_lines(root, task, stage)


# ---------------------------------------------------------------- the text the span loaded (D15)
# The source of the /close Step 3b question (lib/close_rating.py SOURCE_RE), as a text that asks it names it.
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
    """The pattern of the heading line of a todo step's section (`### Step 3b: ...` for
    "Step 3b: ..."), None for a step its content labels otherwise."""
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
def todo_gaps(span) -> list[str]:
    """A command with a canonical list (scripts/todo/<command>.py): the span's
    last ok TodoWrite has its contents and every step completed. Any other
    gated command: its last ok TodoWrite, if any, is all completed. A step
    whose section heading, as the command's text on disk words it, the span's
    loaded text does not hold (_loaded_lacks: added or rewritten since) is not
    that text's step and is not asked. Steps complete in order
    (pretool-todo-validate.py), so a later step the text has, completed,
    still holds every step before it."""
    if os.environ.get("CLAUDE_CODE_ENABLE_TODO_TOOLS") != "1":
        return ["todo tools disabled (CLAUDE_CODE_ENABLE_TODO_TOOLS)"]
    todo_canonical = importlib.import_module("lib.todo_canonical")
    script, _project = todo_canonical._find_todo_script(span.command)
    current = span.last_todos()
    if script is not None:
        canonical = todo_canonical.run_todo_script(span.command, span.args)
        if not canonical:
            raise RuntimeError(f"{script} gave no canonical list")
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


def _targets(span, root, action: str) -> list[str] | None:
    """The typed tasks (_typed), else the families the span's dispatches named;
    None: no task. --auto: the parents dev-lifecycle's --auto target function
    lists at the opener's cut-off (a fresh scan) and the families the span
    walked, which it stops listing once done; [] had none."""
    if "--auto" in shlex.split(span.args):
        lifecycle = _script("scripts/dev-lifecycle.py")
        return sorted(set(lifecycle.auto_targets(Path(root), action, span.opened_at())) | span.session_families())
    return [task for _arg, task in _typed(span)] or sorted(span.session_families()) or None


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
    span dispatched and the opener's hook-minted id (D22: one predicate). A
    cycle on a text that predates this tree's (COMPATIBILITY, above) is asked
    under the name its text gives it, and not for a completion identity or
    reference its template never writes."""
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
    return gaps + list(overnight.closeout_gaps(record, working))


def p_close(span, root, payload) -> list[str]:
    """/close: --stage close per target (under its cycle's own name,
    _cycle_names), and the close-rating question asked
    (D9b: asked, not answered) where it is required and the span's loaded text
    asks it (a /close the session took up before the question was added to
    close.md never asks it: _loaded_lacks). A typed task that names no
    task or chain file (_resolves; close.md asks for one) yields to the families
    the span dispatched, the task the turn closed on the owner's answer, which
    no predicate reads (D23); with none dispatched, its gap names it."""
    typed = [] if "--auto" in shlex.split(span.args) else _typed(span)
    held = [arg for arg, task in typed if not _resolves(root, arg, task)]
    families = span.session_families() if held else set()
    if held and not families:
        return [f"close: {arg} names no task or chain file, and no dispatch of this /close names a task"
                for arg in held]
    targets = sorted({t for a, t in typed if a not in held} | families) if held else _targets(span, root, "close")
    if targets is None:
        return ["close: no target task resolved"]
    close_rating = importlib.import_module("lib.close_rating")  # P4's
    asks = not _loaded_lacks(span)(re.escape(RATING_SOURCE))
    names, gaps = _cycle_names(span), []
    for task in targets:
        gaps += [g for name in _names(names, task) for g in disposition(root, name, "close")]
        if asks and close_rating.rating_required(span, task) and not close_rating.rating_asked(
                span.transcript_path, task):
            gaps.append(f"close {task}: the close-rating question (AskUserQuestion) was not asked")
    return gaps


def _bulk_block(span):
    """The status block of the span's last ok commit-bulk dispatch (its
    obligation's response_block, changelog-status.v1, checked at the
    analyst's own stop), or None."""
    found = None
    for call, doc in span.obligations():
        if doc.get("profile") != "commit-bulk":
            continue
        block = next((a for a in doc.get("artifacts") or () if a.get("kind") == "response_block"), {})
        begin, end, text = block.get("begin") or "", block.get("end") or "", span.result_text(call.id)
        try:
            found = json.loads(text.split(begin, 1)[1].split(end, 1)[0]) if begin and end and begin in text else None
        except ValueError:
            found = None
    return found if isinstance(found, dict) else None


def p_commit(span, root, payload) -> list[str]:
    """/commit: --stage commit per target (a Task-id commit reachable from
    HEAD in each plan repository; under its cycle's own name, _cycle_names);
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
    targets = _targets(span, root, "commit")
    if targets is None:
        return ["commit: no target task resolved"]
    names = _cycle_names(span)
    return [g for task in targets for name in _names(names, task) for g in disposition(root, name, "commit")]


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
                          capture_output=True, timeout=20).returncode == 0


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


def p_merge(span, root, payload) -> list[str]:
    """/merge [--no-commit] [<ref>] [INFERRED; A6]. Source: the typed ref, else
    the newest merge-analyst grant this session wrote here since the opener
    (checked against git on that Write; a bare /merge reads it first), else the
    bare pick from git; none if its value at the opener is no commit or
    DEFAULT_BRANCH's (Step 1's missing tip, self-merge). With no unmerged path:
    MERGE_HEAD (--no-commit, while present) is a value of the source; else a merge
    entry in DEFAULT_BRANCH's reflog after the opener has one as its merged parent
    (a fast-forward: as its new value), or the source's value at the opener is in
    DEFAULT_BRANCH ("Already up to date"); no source: no merge entry after it."""
    _repository(root)
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
    else:
        gaps = [f"merge: no merge of {ref} into refs/heads/{default} after the /merge opener" if at else
                f"merge: refs/heads/{default} took a merge after the opener; no merge-analyst grant of this "
                "session since the opener names its source"]
    if _git(root, "ls-files", "-u"):
        gaps.append("merge: unmerged paths remain in the index")
    return gaps


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
    branch now. At BRANCH's tip,
    refs/remotes/<remote>/<BRANCH> (the typed remote, else any: a typed name
    that is no remote of the repository, which push.sh refuses, yields to the
    remote the push on the owner's answer took) took it, or the branch's value
    at that time, after the opener; or it is at or behind the typed remote's
    ref (none typed: BRANCH's upstream; none for such a name); or push.md refuses the
    push: HEAD detached at the opener and now (Step 2), no push-gate token names
    an ancestor of it (push.sh's exit 3: its READ side over the path of the
    token's one writer), or this session's newest push-analyst grant here since
    the opener is blocked for BRANCH at it (Step 5: execute-push.py refuses it
    and leaves it unspent). The opener's commit, where the tip does not hold it,
    is judged the same way, published where that ref holds it now or took a
    value holding it after the opener. The token and the grant are protected
    for every caller but their producers (pretool-tool-policy.py), and a detach,
    reset or rewrite after the opener is no refusal: no agent's act makes one true."""
    _repository(root)
    typed = next((a for a in span.args.split() if not a.startswith("-")), None)
    since, now = _since(span), _git(root, "symbolic-ref", "--short", "-q", "HEAD")
    heads = span.opener_heads()
    opened = [(b, c) for b, c in heads if b] or [((None if heads else _opener_branch(root, since)) or now, None)]
    return [gap for branch, commit in dict.fromkeys(opened) if branch  # none: Step 2, "HEAD is detached"
            for gap in _push_gaps(root, payload, typed, since, now, branch, commit)]


def _push_gaps(root, payload, typed, since, now, branch, opened) -> list[str]:
    """p_push's gaps for BRANCH at its tip and at the opener's commit (``opened``, None: none recorded)."""
    head = _git(root, "rev-parse", "--verify", "-q", f"refs/heads/{branch}^{{commit}}")
    if not head:
        return [f"push: {branch}, the branch HEAD was on at the /push opener, names no commit; nothing of it "
                "is published since the opener"]
    local, remotes = _reflog(root, f"refs/heads/{branch}"), (_git(root, "remote") or "").split()
    unknown = typed if typed and typed not in remotes else None
    took = [(sha, t) for remote in ([typed] if typed and not unknown else remotes)
            for sha, t, _m in _reflog(root, f"refs/remotes/{remote}/{branch}") if t >= since]
    ref = None if unknown else (f"refs/remotes/{typed}/{branch}" if typed else _git(
        root, "rev-parse", "--symbolic-full-name", "--verify", "-q", f"{branch}@{{upstream}}"))
    holds = {sha for sha, _t in took} | {_git(root, "rev-parse", "--verify", "-q", ref) or "" if ref else ""}
    top, gaps = _git(root, "rev-parse", "--show-toplevel") or str(root), []
    for commit in [head] + ([opened] if opened and not _ancestor(root, opened, head) else []):
        if commit == head:
            published = any(sha in (head, _value_at(local, t)) for sha, t in took) or bool(ref) and _ancestor(
                root, head, ref)
        else:
            published = any(sha and _ancestor(root, commit, sha) for sha in holds)
        if published:
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
        fix = ("" if now == branch else f"; HEAD is not on it: check out {branch}") + (
            "" if commit == head else f"; {branch} is at {head}, which does not hold it: put {branch} back at it")
        gaps.append(f"push: {branch} at {commit} is not published on {ref or 'a remote'} since the /push opener"
                    + (f"; the typed name {unknown} is no remote of this repository" if unknown else "")
                    + (fix and fix + ", then push it"))
    return gaps


def p_text_question(span, payload) -> list[str]:
    """R7 (D28): in a /spec or /dev-family span, a turn whose last main-agent text ends with a question asks it in
    text; the one agent action that clears it is asking with AskUserQuestion, or ending without the question."""
    text = payload.get("last_assistant_message")
    if not _lib_round().ends_with_question(span.last_text() if text is None else text):
        return []
    return [f"{span.command}: the turn ends with a question in text; ask it with AskUserQuestion, or end without it."]


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


def _block_text(command: str, gaps: list[str]) -> str:
    finish = ("Decide each open question yourself (an experiment, else the default) and record the decision."
              if command == "dev-overnight" else
              "Ask with AskUserQuestion only for a real decision the user must make.")
    return (f"COMMAND_GATE /{command}: not complete\n" + "".join(f"- {gap}\n" for gap in gaps)
            + f"Finish the gaps above. {finish}\n")


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
    asking = span is not None and span.command in _lib_round().ASK_COMMANDS and _lib_round().runs_round(span)
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
    gaps = []
    for part in ((lambda: todo_gaps(span), lambda: PREDICATES[span.command](span, root, payload)) if gated else ()) \
            + ((lambda: p_text_question(span, payload),) if asking else ()):  # (6)
        try:
            gaps += part()
        except Exception as exc:
            gaps.append(f"gate instrument failure: {type(exc).__name__}: {exc}")
    if not gaps:  # (7)
        return 0, "", terminal
    text = _block_text(span.command, gaps)
    if mode == "advisory":
        return 0, "would block\n" + text, terminal
    return 2, text, None


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
