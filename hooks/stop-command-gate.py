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
      overnight.window_open(payload); after end_time (closeout_gaps empty) or
      the owner's /stop, block while the wake's CronCreate has no later
      CronDelete, naming its id;
  (5) no gated span (stop-commands.json's GATED_COMMANDS): allow;
  (6) the gaps: the todo half and the command's predicate; an exception is
      the gap `gate instrument failure: <type>: <message>`, never an allow;
  (7) no gap: allow; advisory: `would block` and the gaps on stderr, exit 0;
      else the block text on stderr, exit 2.

Each fact comes from the one producer that writes it: the transcript through
command_span (the CLI's record of typed prompts, tool calls and hook context),
git, and the producers' own deciders, called, never copied: P3's disposition
(scripts/resolve-dev-artifact-chain.py, through the one adapter
`disposition`), P2's overnight locator and window (hooks/lib/overnight.py),
P4's close rating (hooks/lib/close_rating.py), the DDR
(obligation.declaring_dispatch) and dev-lifecycle's --auto target function.
No target comes from a dispatch prompt or a tool result. The gate writes
nothing, keeps no count and has no release but the work itself: the next
compliant step clears each gap. The human's /stop opens a span that is not
gated, and nothing here offers a stop.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
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
def disposition(root, task: str, stage: str, transcript: str | None = None) -> list[str]:
    """The task's disposition at ``stage`` as gap lines, [] for chain_pass:
    the one adapter, the chain's own disposition_lines (over P3's
    `disposition(project_root, task_id, stage)`), used verbatim; the do
    branch also takes the session transcript (R8). Its instrument failure
    raises."""
    return _script("scripts/resolve-dev-artifact-chain.py").disposition_lines(root, task, stage, transcript)


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
        if [t.get("content") for t in current] != [t.get("content") for t in canonical]:
            return [f"todo: checklist differs from the canonical {len(canonical)} steps"]
    return [f"todo: not completed: {t.get('content')}" for t in current or ()
            if not isinstance(t, dict) or t.get("status") != "completed"]


# ---------------------------------------------------------------- predicates
def _canonical(task: str) -> str:
    return _lib("obligation").canonical_task_id(task) or task


def _targets(span, root, action: str) -> list[str]:
    """The typed task; with --auto, dev-lifecycle's --auto target function at
    the opener's cut-off (a fresh scan, no cached listing); else the families
    the span's dispatches named."""
    args = span.args.split()
    if "--auto" in args:
        lifecycle = _script("scripts/dev-lifecycle.py")
        return lifecycle.auto_targets(Path(root), action, span.opened_at())
    typed = [_canonical(a) for a in args if not a.startswith("-")]
    return typed or sorted(span.session_families())


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
    """/do: the hook-minted id of the span, --stage dev through P3's do branch
    with the transcript (R8: schema-valid, do.status completed, lists equal to
    the write set)."""
    task = span.minted_id()
    if not task:
        return ["do: the /do opener has no hook-minted task id ([/do] task-id minted: <id>)"]
    return disposition(root, task, "dev", transcript=span.transcript_path)


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
    if not targets:
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
    if not targets:
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


def _source_tips(root, ref: str, since: float) -> set:
    """The values git gives the typed ref from the opener on: its value at
    the opener, each later reflog value and its value now."""
    full = _git(root, "rev-parse", "--symbolic-full-name", "--verify", "-q", ref) or ref
    entries = _reflog(root, full)
    tips = {sha for sha, t, _m in entries if t >= since}
    tips |= {_value_at(entries, since), _git(root, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}")}
    return {tip for tip in tips if tip}


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
    """/merge [--no-commit] [<ref>] [INFERRED; A6]: a merge entry in
    DEFAULT_BRANCH's reflog after the opener has a value of the source as its
    merged parent (a fast-forward: as its new value), and no unmerged path;
    --no-commit: MERGE_HEAD is a value of the source."""
    _repository(root)
    args = span.args.split()
    refs = [a for a in args if not a.startswith("-")]
    since = _since(span)
    ref = refs[0] if refs else _bare_pick(root, since)
    if not ref:
        return ["merge: Step 0's pick has no git record (no current branch at the opener)"]
    tips = _source_tips(root, ref, since)
    if "--no-commit" in args:
        head = _git(root, "rev-parse", "--verify", "-q", "MERGE_HEAD")
        return [] if head and head in tips else [f"merge: MERGE_HEAD is {head or 'absent'}, not {ref}'s tip"]
    default = (subprocess.run(["bash", str(HARNESS / "scripts" / "derive-default-branch.sh")], cwd=str(root),
                              capture_output=True, text=True, timeout=20).stdout.strip())
    merged = False
    for sha, t, message in _reflog(root, f"refs/heads/{default}"):
        if t < since or not message.startswith(("merge ", "commit (merge)")):
            continue
        parents = (_git(root, "rev-list", "--parents", "-n", "1", sha) or "").split()[2:]
        if (tips & ({sha} | set(parents)) if tips else message.startswith(f"merge {ref}:")):
            merged = True
            break
    gaps = [] if merged else [f"merge: no merge of {ref} into refs/heads/{default} after the /merge opener"]
    if _git(root, "ls-files", "-u"):
        gaps.append("merge: unmerged paths remain in the index")
    return gaps


def p_push(span, root, payload) -> list[str]:
    """/push [<remote>] [INFERRED; A6]: refs/remotes/<remote>/<BRANCH> (the
    typed remote, else any) took HEAD, or the branch's value at that time,
    after the opener; or HEAD is at or behind the typed remote's ref (none
    typed: the upstream's)."""
    _repository(root)
    typed = next((a for a in span.args.split() if not a.startswith("-")), None)
    branch = _git(root, "symbolic-ref", "--short", "-q", "HEAD")
    if not branch:
        return ["push: HEAD is detached (no current branch to push)"]
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
    return [f"push: HEAD {head} of {branch} is not published on {ref or 'a remote'} since the /push opener"]


PREDICATES = {
    "dev": p_dev, "redev": p_dev, "dev-command": p_dev, "do": p_do, "dev-overnight": p_overnight,
    "close": p_close, "commit": p_commit, "merge": p_merge, "push": p_push,
}


# ---------------------------------------------------------------- the time-lock (4)
def _open_wake(transcript: str) -> str | None:
    """The id of a recurring CronCreate after the latest /dev-overnight opener
    with no later CronDelete of it (P1c X8), else None."""
    starts = [line for line, command, _args in command_span.openers(transcript) if command == "dev-overnight"]
    if not starts:
        return None
    scheduled = {}
    for use, record in command_span.Span("dev-overnight", "", starts[-1], transcript).returns("CronCreate", "CronDelete"):
        if use.name == "CronCreate" and use.ok and use.input.get("recurring"):
            ident = ((record or {}).get("toolUseResult") or {}).get("id")
            scheduled.update({ident: True} if ident else {})
        elif use.name == "CronDelete" and use.ok:
            scheduled.pop(use.input.get("id"), None)
    return next(iter(scheduled), None)


def timelock(payload) -> tuple[str | None, str | None]:
    """Step (4): (its block line, None), or (None, the session's terminal
    time-lock status once its window has closed: completed_by_deadline after
    end_time with the closeout complete, cancelled_by_user after the human's
    /stop), or (None, None) for a session with no overnight record or an
    incomplete closeout. Codex-native Stop owns overnight isolation in Codex
    roots, so the Codex runtime meets none."""
    if os.environ.get("CLAUDE_COMPAT_RUNTIME") == "codex":
        return None, None
    overnight, transcript = _lib("overnight"), payload.get("transcript_path") or ""
    _state_file, record = overnight.locate(payload.get("session_id"), payload)
    if record is None:
        return None, None
    if overnight.window_open(payload):
        return f"overnight window open until {record.get('end_time')}; continue the remaining pipelines", None
    released = command_span.timelock_released(transcript)
    if not released and overnight.closeout_gaps(record, overnight.working_root(record)):
        return None, None
    wake = _open_wake(transcript)
    if wake:
        return f"overnight wake {wake} is still scheduled; delete it (CronDelete id {wake})", None
    return None, "cancelled_by_user" if released else "completed_by_deadline"


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
        lock, terminal = timelock(payload)
    except Exception as exc:
        if not gated:
            return 0, f"COMMAND_GATE time-lock: gate instrument failure: {type(exc).__name__}: {exc}\n", None
        lock, terminal, failure = None, None, [f"gate instrument failure: {type(exc).__name__}: {exc}"]
    else:
        failure = []
    if lock:
        return 2, f"COMMAND_GATE time-lock: {lock}\n", None
    if not gated:  # (5)
        return 0, "", terminal
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    gaps = list(failure)
    for part in (lambda: todo_gaps(span), lambda: PREDICATES[span.command](span, root, payload)):  # (6)
        try:
            gaps += part()
        except Exception as exc:
            gaps.append(f"gate instrument failure: {type(exc).__name__}: {exc}")
    if not gaps:  # (7)
        return 0, "", terminal
    text = _block_text(span.command, gaps)
    return (0, "would block\n" + text, terminal) if mode == "advisory" else (2, text, None)


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
