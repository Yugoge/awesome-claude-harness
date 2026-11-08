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
  (5) no gated span (stop-commands.json's GATED_COMMANDS): allow;
  (6) the gaps: the todo half and the command's predicate; an exception is
      the gap `gate instrument failure: <type>: <message>`, never an allow;
  (7) no gap: allow; advisory: `would block` and the gaps on stderr, exit 0;
      else the block text on stderr, exit 2.

Each fact comes from the one producer that writes it: the transcript through
command_span (the CLI's record of typed prompts, tool calls and hook context),
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


def _lib(name: str):
    """A hooks/lib module, imported when a predicate first needs it."""
    import importlib
    return importlib.import_module(f"lib.{name}")


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


# ---------------------------------------------------------------- the todo half
def todo_gaps(span) -> list[str]:
    """A command with a canonical list (scripts/todo/<command>.py): the span's
    last ok TodoWrite has its contents and every step completed. Any other
    gated command: its last ok TodoWrite, if any, is all completed."""
    if os.environ.get("CLAUDE_CODE_ENABLE_TODO_TOOLS") != "1":
        return ["todo tools disabled (CLAUDE_CODE_ENABLE_TODO_TOOLS)"]
    todo_canonical = _lib("todo_canonical")
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
    return [f"todo: not completed: {t.get('content')}" for t in current or ()
            if not isinstance(t, dict) or t.get("status") != "completed"]


# ---------------------------------------------------------------- predicates
def _canonical(task: str) -> str:
    return _lib("obligation").canonical_task_id(task) or task


def _targets(span, root, action: str) -> list[str] | None:
    """The typed tasks as close.md's Task-id resolution and commit.md's Step 1
    read them (shell quoting; --reason's value is no task; a path names the id
    its basename holds from the timestamp on), else the families the span's
    dispatches named; None: no task. --auto: the parents dev-lifecycle's --auto
    target function lists at the opener's cut-off (a fresh scan) and the
    families the span walked, which it stops listing once done; [] had none."""
    args = shlex.split(span.args)
    if "--auto" in args:
        lifecycle = _script("scripts/dev-lifecycle.py")
        return sorted(set(lifecycle.auto_targets(Path(root), action, span.opened_at())) | span.session_families())
    typed = []
    for k, arg in enumerate(args):
        if arg.startswith("-") or args[k - 1:k] == ["--reason"]:
            continue
        if arg.endswith((".md", ".json")) or "/" in arg:
            name = os.path.basename(arg).removesuffix(".md").removesuffix(".json")
            arg = name[name.find(_lib("obligation").task_stamp(name) or name):]
        typed.append(_canonical(arg))
    return typed or sorted(span.session_families()) or None


def p_dev(span, root, payload) -> list[str]:
    """/dev, /redev, /dev-command: --stage dev chain_pass for each family the
    span dispatched and the opener's hook-minted id (D22: one predicate)."""
    families = span.session_families()
    if not families:
        return ["no pipeline dispatched"]
    minted = _lib("obligation").task_family(span.minted_id())
    families |= {minted} if minted else set()
    return [g for family in sorted(families) for g in disposition(root, family, "dev")]


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
    status = [] if _lib("obligation").terminal_status("do-report.v1", record) else [
        f"{rel}: do.status is not a terminal status of schemas/do-report.v1.json"]
    chain = _script("scripts/resolve-dev-artifact-chain.py")
    return status + [f"{artifact}: {code}: {detail}" for code, artifact, detail in
                     chain.do_report_gaps(root, task, Path(root) / rel, span.transcript_path)]


def p_overnight(span, root, payload) -> list[str]:
    """/dev-overnight after its window: each family the span dispatched is
    chain_pass at the session's working root (P2's locator), the closeout is
    complete. An unanswered producer question is the disposition's gap."""
    overnight = _lib("overnight")
    _state_file, record = overnight.locate(payload.get("session_id"), payload)
    if record is None:
        return [f"dev-overnight: no overnight state record for session {payload.get('session_id')}"]
    working = overnight.working_root(record)
    gaps = [g for family in sorted(span.session_families()) for g in disposition(working, family, "dev")]
    return gaps + list(overnight.closeout_gaps(record, working))


def p_close(span, root, payload) -> list[str]:
    """/close: --stage close per target, and the close-rating question asked
    (D9b: asked, not answered) where it is required."""
    targets = _targets(span, root, "close")
    if targets is None:
        return ["close: no target task resolved"]
    close_rating = _lib("close_rating")  # P4's
    gaps = []
    for task in targets:
        gaps += disposition(root, task, "close")
        if close_rating.rating_required(span, task) and not close_rating.rating_asked(span.transcript_path, task):
            gaps.append(f"close {task}: the close-rating question (AskUserQuestion) was not asked")
    return gaps


def _result_text(record) -> str:
    """The text of the tool_result blocks of a result record."""
    texts = []
    for block in ((record or {}).get("message") or {}).get("content") or ():
        content = block.get("content") if isinstance(block, dict) and block.get("type") == "tool_result" else ""
        texts.append(content if isinstance(content, str) else
                     "\n".join(c.get("text", "") for c in content or () if isinstance(c, dict)))
    return "\n".join(texts)


def _bulk_block(span):
    """The status block of the span's last ok commit-bulk dispatch (its
    obligation's response_block, changelog-status.v1, checked at the
    analyst's own stop), or None."""
    obligation, found = _lib("obligation"), None
    for use, record in span.returns("Agent", "Task"):
        parsed = obligation.parse_obligation(str(use.input.get("prompt") or "")) if use.ok else None
        if not isinstance(parsed, obligation.ParsedObligation) or parsed.obligation.get("profile") != "commit-bulk":
            continue
        block = next((a for a in parsed.obligation.get("artifacts") or () if a.get("kind") == "response_block"), {})
        begin, end, text = block.get("begin") or "", block.get("end") or "", _result_text(record)
        try:
            found = json.loads(text.split(begin, 1)[1].split(end, 1)[0]) if begin and end and begin in text else None
        except ValueError:
            found = None
    return found if isinstance(found, dict) else None


def p_commit(span, root, payload) -> list[str]:
    """/commit: --stage commit per target (a Task-id commit reachable from
    HEAD in each plan repository); --bulk: the bulk status block reports a
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
    return [g for task in targets for g in disposition(root, task, "commit")]


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
    grant = _lib("merge_grant").newest(_git(root, "rev-parse", "--show-toplevel") or str(root),
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


def p_push(span, root, payload) -> list[str]:
    """/push [<remote>] [INFERRED; A6]: refs/remotes/<remote>/<BRANCH> (the
    typed remote, else any) took HEAD, or the branch's value at that time,
    after the opener; or HEAD is at or behind the typed remote's ref (none
    typed: the upstream's); or push.md refuses the push: no current branch
    (Step 2), no push-gate token names an ancestor of HEAD (push.sh's exit 3:
    its READ side over the path of the token's one writer), or this session's
    newest push-analyst grant here since the opener is blocked for BRANCH at
    HEAD (Step 5: execute-push.py refuses it and leaves it unspent)."""
    _repository(root)
    typed = next((a for a in span.args.split() if not a.startswith("-")), None)
    branch = _git(root, "symbolic-ref", "--short", "-q", "HEAD")
    if not branch:
        return []  # Step 2: "HEAD is detached"; no push can be made from it
    head, since = _git(root, "rev-parse", "HEAD"), _since(span)
    local = _reflog(root, f"refs/heads/{branch}")
    for remote in [typed] if typed else (_git(root, "remote") or "").split():
        for sha, t, _m in _reflog(root, f"refs/remotes/{remote}/{branch}"):
            if t >= since and sha in (head, _value_at(local, t)):
                return []
    ref = (f"refs/remotes/{typed}/{branch}" if typed
           else _git(root, "rev-parse", "--symbolic-full-name", "--verify", "-q", "@{upstream}"))
    if ref and _git(root, "rev-parse", "--verify", "-q", ref) and _ancestor(root, "HEAD", ref):
        return []
    top = _git(root, "rev-parse", "--show-toplevel") or str(root)
    token = _script("scripts/write-push-gate-token.py").token_path(top, branch, "")  # <repo dir>/<session>/<name>
    for path in [token.parent.parent / token.name, *token.parent.parent.glob(f"*/{token.name}")]:
        try:
            sha = json.loads(path.read_text()).get("commit_sha")
        except (OSError, ValueError, AttributeError):
            continue  # "Malformed/unparseable candidates are skipped"
        if sha and _ancestor(root, str(sha), "HEAD"):
            break
    else:
        return []  # Step 5: push.sh's exit 3, "run /commit first"
    grant = _lib("merge_grant").newest(top, payload.get("session_id"), since, "push-analyst")
    if (grant.get("verdict"), grant.get("branch"), grant.get("head_sha")) == ("blocked", branch, head):
        return []  # Step 5: "push BLOCKED by push-analyst"
    return [f"push: HEAD {head} of {branch} is not published on {ref or 'a remote'} since the /push opener"]


PREDICATES = {
    "dev": p_dev, "redev": p_dev, "dev-command": p_dev, "do": p_do, "dev-overnight": p_overnight,
    "close": p_close, "commit": p_commit, "merge": p_merge, "push": p_push,
}


# ---------------------------------------------------------------- the time-lock (4)
def window_lock(payload, record):
    """(2, the block text with the time left, None) while the session's overnight
    window is open (P2's overnight.window_open), else None."""
    overnight = _lib("overnight")
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
    jobs = _lib("overnight").open_wakes(transcript)
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
    overnight, transcript = _lib("overnight"), payload.get("transcript_path") or ""
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
    if not gated:  # (5)
        return 0, "", terminal
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    gaps = []
    for part in (lambda: todo_gaps(span), lambda: PREDICATES[span.command](span, root, payload)):  # (6)
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
