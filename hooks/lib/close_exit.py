"""The /close that code completes at the typed prompt: a cycle with no files, or the owner's --force.

prompt-workflow.py (UserPromptSubmit) calls complete() for a typed /close: when the cycle's reports
declare no changed file and the session's own records attribute it no edit, or the owner typed
--force, it appends the close report's section (scripts/close-report-append.py, the one append
routine) ending on a CLOSE: YES line, and returns the text the hook prints. No inspector, QA or todo
list runs. The Stop gate (stop-command-gate.py code_close_end) reads RESULT_RE only from the hook
context of a human-typed /close opener (command_span), so a line an agent writes or echoes ends
nothing. The writer of the close report at such a close is this module alone: no QA is dispatched.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shlex
import tempfile
import time
from pathlib import Path

from lib import command_span  # both callers have hooks/ on sys.path
from lib.obligation import task_stamp

CYCLE_COMMANDS = ("do", "dev", "redev", "dev-command")
RESULT_RE = re.compile(r"^\[/close\] completed by code: (\S+) (no-files|forced)$", re.M)
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
    lists no file; the dev-report owns no edit."""
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
        if not isinstance(record, dict) or _listed(record.get(key)) != [] or record.get("owned_edits"):
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


def _records_empty(root: Path, task: str, transcript: str) -> bool:
    """The session holds the task's cycle spans, and none of them, nor an agent one of them dispatched,
    wrote a project file (command_span.write_set, the one write-set reader)."""
    openers = command_span.openers(transcript)
    spans = [(openers[k + 1][0] if k + 1 < len(openers) else None, command_span.Span(c, a, line, transcript))
             for k, (line, c, a) in enumerate(openers) if c in CYCLE_COMMANDS]
    spans = [(stop, span) for stop, span in spans if span.minted_id() == task]
    agents = _agent_transcripts(transcript)
    if not spans or None in agents:
        return False
    for stop, span in spans:
        sets = [span.write_set(root, actor=None, stop_line=stop)] + [
            command_span.write_set(agents[c.id], root) for c in span.dispatch_calls()
            if (stop is None or c.line < stop) and c.id in agents]
        if any(s is None or s.written for s in sets):
            return False
    return True


def no_files(root: Path, task: str, transcript: str) -> bool:
    """The cycle's reports declare no changed file and the session's records attribute it no edit."""
    return bool(transcript) and _reports_empty(root / "docs" / "dev", task) and _records_empty(root, task, transcript)


def _append(root: Path, task: str, section: str) -> str | None:
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
        ok, line = module.run(report, Path(handle.name), script.parents[1])
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
    task = _task(args, transcript)
    if not task:
        return None
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if "--force" in args:
        kind, why = "forced", f"forced by the owner at {stamp}"
        reason = args[args.index("--reason") + 1] if "--reason" in args[:-1] else ""
        body = f"The owner typed /close --force at {stamp}.{f' Reason: {reason}' if reason else ''}"
    elif no_files(root, task, transcript):
        kind, why = "no-files", "no files: nothing to inspect"
        body = (f"At {stamp} the cycle's reports declare no changed file and this session's records attribute "
                "it no edit: there is nothing to inspect.")
    else:
        return None
    error = _append(root, task, f"\n## Close by code ({stamp})\n\n{body} No inspector or QA ran.\n\n"
                                f"CLOSE: YES ({why})\n")
    if error:
        return f"[/close] not completed by code: {error}\nReply with exactly this line and nothing else: {error}"
    line = f"CLOSE: YES ({why}) for {task}; next: /commit {task}"
    return (f"[/close] completed by code: {task} {kind}\n"
            f"Reply with exactly this one line, call no tool, write nothing else:\n{line}")
