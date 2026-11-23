"""The /close that code completes at the typed prompt: a cycle with no files, the owner's --force, or
the owner's --retire.

prompt-workflow.py (UserPromptSubmit) calls complete() for a typed /close: when the cycle's reports
say it finished and declare no changed file and the session's own records attribute it no edit, or the
owner typed --force, it appends the close report's section (scripts/close-report-append.py, the one append
routine) ending on a CLOSE: YES line, and returns the text the hook prints. No inspector, QA or todo
list runs. The Stop gate (stop-command-gate.py code_close_end) reads RESULT_RE only from the hook
context of a human-typed /close opener (command_span), so a line an agent writes or echoes ends
nothing. The writer of the close report at such a close is this module alone: no QA is dispatched.

/close --retire --reason "<text>" <task-id> gives up a cycle that will never be finished: its section names
the time, the reason and the session's transcript and ends `CLOSE: RETIRED (by the owner at <UTC>): <reason>`,
a line no other caller of the append routine may write. scripts/dev-lifecycle.py derives the state `retired`
from it only when that transcript holds the human-typed opener with this module's retired result line in
its hook context (command_span), the same evidence code_close_end reads.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shlex
import tempfile
import time
from pathlib import Path

try:  # hooks.lib.close_exit (the commit check, scripts/resolve-dev-artifact-chain.py) or lib.close_exit (the hooks)
    from . import command_span, subagent_restart
    from .obligation import task_stamp
except ImportError:
    from lib import command_span, subagent_restart  # type: ignore[no-redef]
    from lib.obligation import task_stamp  # type: ignore[no-redef]

CYCLE_COMMANDS = ("do", "dev", "redev", "dev-command")
RESULT_RE = re.compile(r"^\[/close\] completed by code: (\S+) (no-files|forced|retired)$", re.M)
_CHAIN_RULE = ("--auto", "--late-repair")  # close.md answers these with NO_TARGET or its own route


def names_path(arg: str) -> bool:
    """A typed /close or /commit argument that names a report path, not a task id (also stop-command-gate.py's)."""
    return arg.endswith((".md", ".json")) or "/" in arg


def _task(args: list, transcript: str) -> str | None:
    """The typed task id, else the minted id of the session's latest cycle opener (close.md's
    Task-id resolution); None for a path, several ids, or none."""
    typed = [a for k, a in enumerate(args) if not a.startswith("-") and args[k - 1:k] != ["--reason"]]
    if typed:
        return typed[0] if len(typed) == 1 and task_stamp(typed[0]) and not names_path(typed[0]) else None
    for line, command, cargs in reversed(command_span.openers(transcript) if transcript else []):
        if command in CYCLE_COMMANDS:
            return command_span.Span(command, cargs, line, transcript).minted_id()
    return None


def _listed(section) -> list | None:
    if not isinstance(section, dict):
        return None
    lists = [section.get(k, []) for k in ("files_modified", "files_created")]
    return [e for l in lists for e in l] if all(isinstance(l, list) for l in lists) else None


def _reports_empty(dev_dir: Path, task: str) -> bool:
    """At least one report of the task (do-report's do, dev-report's dev; no lane shard), and each
    says the task finished (status completed, the one terminal: a blocked or unfinished task is work
    left for dev, not an empty success) and lists no file; the dev-report owns no edit."""
    if any(dev_dir.glob(f"dev-report-{task}-*.json")):
        return False
    found = 0
    for name, key in ((f"do-report-{task}.json", "do"), (f"dev-report-{task}.json", "dev")):
        try:
            record = json.loads((dev_dir / name).read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            return False
        if (not isinstance(record, dict) or _listed(record.get(key)) != [] or record.get("owned_edits")
                or record[key].get("status") != "completed"):
            return False
        found += 1
    return found > 0


def _agent_transcripts(transcript: str) -> dict:
    """{dispatching tool_use id: the agent's transcript} of the session's subagents (their meta files)."""
    found = {}
    for meta in (Path(transcript).with_suffix("") / "subagents").glob("agent-*.meta.json"):
        try:
            found[json.loads(meta.read_text(encoding="utf-8")).get("toolUseId")] = \
                meta.with_name(meta.name[:-len(".meta.json")] + ".jsonl")
        except (OSError, ValueError, AttributeError):
            found[None] = None  # an unread meta: the records cannot be shown empty
    return found


def _spans_wrote(root: Path, task: str, transcript) -> bool | None:
    """None when the transcript holds no cycle span of the task; else whether one of them, or an agent one
    of them dispatched, wrote a project file (command_span.write_set, the one write-set reader; a record
    that cannot be read counts as written)."""
    openers = command_span.openers(transcript)
    spans = [(openers[k + 1][0] if k + 1 < len(openers) else None, command_span.Span(c, a, line, str(transcript)))
             for k, (line, c, a) in enumerate(openers) if c in CYCLE_COMMANDS]
    spans = [(stop, span) for stop, span in spans if span.minted_id() == task]
    if not spans:
        return None
    agents = _agent_transcripts(transcript)
    for stop, span in spans if None not in agents else ():
        sets = [span.write_set(root, actor=None, stop_line=stop)] + [
            command_span.write_set(agents[c.id], root) for c in span.dispatch_calls()
            if (stop is None or c.line < stop) and c.id in agents]
        if any(s is None or s.written for s in sets):
            return True
    return None in agents


def nothing_written(root: Path, task: str, transcripts: list) -> bool:
    """The one no-files test: the cycle's reports declare no changed file, the transcripts hold at least one
    cycle span of the task, and no span of it there wrote a project file. /close reads the session's own
    transcript (no_files), the commit check every session of the project that names the task (nothing_to_land)."""
    found = [_spans_wrote(root, task, t) for t in transcripts]
    return _reports_empty(root / "docs" / "dev", task) and False in found and True not in found


def no_files(root: Path, task: str, transcript: str) -> bool:
    """The cycle's reports declare no changed file and the session's records attribute it no edit."""
    return bool(transcript) and nothing_written(root, task, [transcript])


def task_transcripts(root: Path, task: str) -> list | None:
    """Every session transcript of the project, in every account root, whose bytes name the task; None when
    one cannot be read (the records cannot be shown empty)."""
    found = []
    for base in subagent_restart.account_project_roots():
        for path in sorted((base / subagent_restart.project_slug(root)).glob("*.jsonl")):
            try:
                found += [path] if task.encode() in path.read_bytes() else []
            except OSError:
                return None
    return found


def nothing_to_land(root: Path, task: str) -> bool:
    """The commit check's no-files: nothing_written over every session of the project that names the task."""
    transcripts = task_transcripts(root, task)
    return transcripts is not None and nothing_written(root, task, transcripts)


def _append(root: Path, task: str, section: str, allow: tuple = ()) -> str | None:
    """The section appended to docs/dev/close-report-<task>.md; the append routine's error line, or None."""
    script = Path(__file__).resolve().parents[2] / "scripts" / "close-report-append.py"
    spec = importlib.util.spec_from_file_location("close_report_append", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = root / "docs" / "dev" / f"close-report-{task}.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=report.parent, prefix=".close-exit-", suffix=".md") as handle:
        handle.write(section)
        handle.flush()
        ok, line = module.run(report, Path(handle.name), script.parents[1], allow)
    return None if ok else line


def complete(prompt: str, transcript: str, root: Path) -> str | None:
    """The text to print when code completed this typed /close, else None (the ordinary route)."""
    found = command_span.slash_command(prompt)
    try:
        args = shlex.split(found[1]) if found and found[0] == "close" else None
    except ValueError:
        return None
    if args is None or any(a in _CHAIN_RULE for a in args):
        return None
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if "--retire" in args:
        return _retire(args, transcript, root, stamp)
    task = _task(args, transcript)
    if not task:
        return None
    if "--force" in args:
        kind, why = "forced", f"forced by the owner at {stamp}"
        reason = args[args.index("--reason") + 1] if "--reason" in args[:-1] else ""
        body = f"The owner typed /close --force at {stamp}.{f' Reason: {reason}' if reason else ''}"
    elif no_files(root, task, transcript):
        kind, why = "no-files", "no files: nothing to inspect"
        body = (f"At {stamp} the cycle's reports say it finished, declare no changed file, and this session's "
                "records attribute it no edit: there is nothing to inspect.")
    else:
        return None
    error = _append(root, task, f"\n## Close by code ({stamp})\n\n{body} No inspector or QA ran.\n\n"
                                f"CLOSE: YES ({why})\n")
    if error:
        return f"[/close] not completed by code: {error}\nReply with exactly this line and nothing else: {error}"
    line = f"CLOSE: YES ({why}) for {task}; next: /commit {task}"
    return (f"[/close] completed by code: {task} {kind}\n"
            f"Reply with exactly this one line, call no tool, write nothing else:\n{line}")


def _retire(args: list, transcript: str, root: Path, stamp: str) -> str:
    """The owner's /close --retire --reason "<text>" <task-id>: exactly one typed task id and a reason, else
    nothing is written and the text says what is missing."""
    reason = " ".join(args[args.index("--reason") + 1].split()) if "--reason" in args[:-1] else ""
    typed = [a for k, a in enumerate(args) if not a.startswith("-") and args[k - 1:k] != ["--reason"]]
    task = typed[0] if len(typed) == 1 and task_stamp(typed[0]) and not names_path(typed[0]) else None
    error = ("--retire takes no --force" if "--force" in args else
             "--retire names exactly one task id" if not task else
             '--retire needs --reason "<text>"' if not reason else None)
    if not error:
        body = (f"The owner typed /close --retire at {stamp}. Reason: {reason}\nTranscript: {transcript}\n"
                "The cycle is given up: nothing of it is inspected or committed.")
        error = _append(root, task, f"\n## Retired by the owner ({stamp})\n\n{body}\n\n"
                                    f"CLOSE: RETIRED (by the owner at {stamp}): {reason}\n", ("retired",))
    if error:
        return f"[/close] not completed by code: {error}\nReply with exactly this line and nothing else: {error}"
    return (f"[/close] completed by code: {task} retired\n"
            f"Reply with exactly this one line, call no tool, write nothing else:\n"
            f"CLOSE: RETIRED for {task}: {reason}; it leaves every --auto list")
