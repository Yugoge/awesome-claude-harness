#!/usr/bin/env python3
"""Step 5 of /commit (normal mode): the repository plan and every fact the next steps read, in one call.

    commit-plan.py --task-id <TASK_ID>

Run from the product repository (the control checkout). Prints ONE JSON object on stdout; the exit
status is 0 unless the arguments are wrong (2), because every state below is a fact for the command
to route, not a failure of this script. Keys:

control_root      git top level of the working directory (the control checkout).
nested_repo       git top level of $CLAUDE_HOME (else of the harness this script lives in): the
                  harness checkout, the one supported repository besides the control checkout.
close_report      scripts/resolve-close-report.sh's path for the task (the file when it exists,
                  else its fallback path).
late_repair       scripts/late-repair-controller.py resolve-effective-report's {"state", "path"}
                  for the project that holds the close-report's docs/dev; null when the controller
                  printed none. "verified" names the effective report, "none" keeps the dev or do
                  report, "invalid" (State C) names the artifact of a finding.
task_report       the report the plan is built from: the effective report when late_repair is
                  verified; else, in the docs/dev directory that supplied close_report, the report
                  the task's disposition plans from (resolve-dev-artifact-chain.py --disposition):
                  the do-report of a /do task whose do-report is completed, the dev-report
                  otherwise (the do-report only when there is no dev-report).
repository_plan   scripts/resolve-commit-repos.py's plan for task_report, with the control
                  checkout and nested_repo as the supported repositories; null when it printed
                  none, and plan_error then holds its reason (its stderr).
attribution_log   scripts/verify-attribution-chain.py --json over the plan's owned paths; the empty
                  object {"results": [], "no_events": [], "discarded_lines": []} when the plan owns
                  no path or the verifier printed nothing (exit 2, no journaled event, is no failure).
session_id        $CLAUDE_CODE_SESSION_ID, else $CLAUDE_SESSION_ID ("" when neither is set).
manifest_path     the dispatch-snapshot manifest's path (hooks/lib/commit_pipeline.manifest_path);
                  null without a session id.
files_at_dispatch every plan entry's repo_root -> its `git status --porcelain=v1` lines.
unclaimed         present only when the plan owns no path (a cycle that declares no file): the
                  control checkout's changed paths that no open cycle claims, which this /commit
                  lands. {"repo_root", "paths", "claimed_by_open_cycles" (path -> the open task ids
                  whose dev or do report in docs/dev lists it: left for them),
                  "claimed_by_open_commands" (path -> the other sessions whose open command the
                  attribution journal credits with an edit to it, report or none: left for them),
                  "left" (the --leave-unclaimed paths), "unreadable_reports", "unresolved_sessions"
                  (journaled sessions with no transcript found: all their edits claimed)}. An open
                  cycle is one with no `Task-id:` line of its own reachable from HEAD; docs/dev is
                  never swept.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parents[2]
EMPTY_ATTRIBUTION = {"results": [], "no_events": [], "discarded_lines": []}

def run(cmd: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              errors="replace")
    except OSError as exc:  # a directory or program that does not exist is a failed command, as in a shell
        return 127, "", str(exc)
    return proc.returncode, proc.stdout, proc.stderr


def git_top(directory: str | None = None) -> str:
    code, out, _ = run(["git", "rev-parse", "--show-toplevel"], cwd=directory)
    return out.strip() if code == 0 else ""


def as_json(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return None


def helper(name: str) -> str:
    return str(HARNESS_ROOT / "scripts" / name)


def do_report_is_completed(do_report: Path) -> bool:
    """A /do task's completed do-report: the one condition under which the disposition plans from it
    although a dev-report exists (resolve-dev-artifact-chain.py `disposition`)."""
    sys.path.insert(0, str(HARNESS_ROOT))
    from hooks.lib import do_report as do_report_lib, obligation  # noqa: E402
    record, _problem = do_report_lib.load(do_report)
    return (record is not None and record.get("source") == "do"
            and obligation.terminal_status("do-report.v1", record) == "completed")


def choose_report(docs_root: Path, task_id: str, late: dict | None) -> str:
    if late and late.get("state") == "verified" and late.get("path"):
        return str(late["path"])
    dev = docs_root / f"dev-report-{task_id}.json"
    do = docs_root / f"do-report-{task_id}.json"
    if dev.is_file() and do.is_file():
        return str(do if do_report_is_completed(do) else dev)
    return str(dev if dev.is_file() or not do.is_file() else do)


def listed_paths(doc: dict) -> list[str]:
    """Every path a report lists: its owned_edits keys and each section's files_modified/files_created."""
    listed = list(doc["owned_edits"]) if isinstance(doc.get("owned_edits"), dict) else []
    for section in (value for value in doc.values() if isinstance(value, dict)):
        for field in ("files_modified", "files_created"):
            values = section.get(field)
            listed += [p for p in values if isinstance(p, str)] if isinstance(values, list) else []
    return listed


def landed_ids(control_root: str) -> set[str]:
    _code, out, _ = run(["git", "-C", control_root, "log", "HEAD", "--format=%B"])
    return {line.strip()[8:].strip() for line in out.splitlines() if line.strip().startswith("Task-id:")}


def command_claims(control_root: str, landed: set[str], own_session: str) -> tuple[dict[str, list[str]], list[str]]:
    """Repo-relative path -> the other sessions whose open command the attribution journal (the edits the hooks
    record per session) credits with an edit to it, report or none; and the sessions no configuration directory
    holds a transcript of, whose edits are all claimed. A session's open command is its last cycle command
    (else its last harness command) whose minted task id has no `Task-id:` line in HEAD; it claims the
    session's edits from its opener's time on. A session with no harness command open claims nothing."""
    sys.path.insert(0, str(HARNESS_ROOT / "hooks"))
    from lib import attribution_journal, close_exit, command_span, subagent_restart  # noqa: E402
    root, edits = Path(control_root), {}
    for event in attribution_journal.read_all_journals()[0]:
        path, session = Path(str(event["path"])), str(event["session_id"])
        if session != own_session and path.is_absolute() and path.is_relative_to(root):
            edits.setdefault(session, []).append((event["ts"], os.path.normpath(path.relative_to(root))))
    claims: dict[str, list[str]] = {}
    unresolved: list[str] = []
    for session, done in sorted(edits.items()):
        transcript = next((t for d in subagent_restart.config_projects() for t in d.glob(f"*/{session}.jsonl")), None)
        unresolved += [session] if transcript is None else []
        span = None if transcript is None else next(
            (s for s in open_spans(command_span, close_exit.CYCLE_COMMANDS, transcript)
             if s.minted_id() not in landed), False)
        since = span.opened_at() if span else None
        for ts, path in done if span is not False else []:
            if since is None or not isinstance(ts, (int, float)) or ts >= since:
                claims.setdefault(path, []).append(session)
    return claims, unresolved


def open_spans(command_span, cycle_commands: tuple, transcript: Path) -> list:
    """The session's last cycle command's span, then its last harness command's (the active one)."""
    found = command_span.openers(transcript)
    return [command_span.Span(c, a, line, str(transcript))
            for line, c, a in [o for o in found if o[1] in cycle_commands][-1:] + found[-1:]]


def open_claims(docs_root: Path, control_root: str, task_id: str) -> tuple[dict[str, list[str]], list[str]]:
    """Repo-relative path -> the open tasks whose dev or do report lists it, and the unreadable reports."""
    landed = landed_ids(control_root)
    claims: dict[str, list[str]] = {}
    unreadable: list[str] = []
    for report in sorted([*docs_root.glob("dev-report-*.json"), *docs_root.glob("do-report-*.json")]):
        doc = as_json(report.read_text(encoding="utf-8", errors="replace")) if report.is_file() else None
        owner = doc.get("task_id") if isinstance(doc, dict) else None
        if not isinstance(owner, str) or not owner:
            unreadable.append(report.name)
            continue
        if owner == task_id or any(owner == t or owner.startswith(t + "-") for t in landed):
            continue
        for raw in listed_paths(doc):
            path = Path(raw)
            path = path.relative_to(control_root) if path.is_absolute() and path.is_relative_to(control_root) else path
            if not path.is_absolute():
                claims.setdefault(os.path.normpath(path), []).append(owner)
    return claims, unreadable


def unclaimed(control_root: str, docs_root: Path, task_id: str, leave: list[str], session_id: str) -> dict:
    """The control checkout's changed paths (renames: both sides) outside docs/dev that no open cycle claims."""
    _code, out, _err = run(["git", "-C", control_root, "status", "--porcelain=v1", "-z", "--untracked-files=all"])
    records, changed = out.split("\0"), []
    while records:
        record = records.pop(0)
        if len(record) > 3:
            changed.append(record[3:])
            if record[0] in "RC" and records:
                changed.append(records.pop(0))
    claims, unreadable = open_claims(docs_root, control_root, task_id)
    working, unresolved = command_claims(control_root, landed_ids(control_root), session_id)
    candidates = sorted({p for p in changed if not p.endswith("/") and not p.startswith("docs/dev/")})
    return {"repo_root": control_root,
            "paths": [p for p in candidates if p not in claims and p not in working and p not in leave],
            "claimed_by_open_cycles": {p: sorted(set(claims[p])) for p in candidates if p in claims},
            "claimed_by_open_commands": {p: sorted(set(working[p])) for p in candidates if p in working},
            "left": sorted(set(leave)), "unreadable_reports": unreadable, "unresolved_sessions": unresolved}


def attribution_log(plan: dict | None, extra: list[str] = ()) -> dict:
    files = [f"{entry['repo_root']}/{path}" for entry in (plan or {}).get("repositories") or []
             for path in entry.get("owned_paths") or []] + list(extra)
    if not files:  # no --file would make the verifier read the whole journal
        return dict(EMPTY_ATTRIBUTION)
    cmd = [sys.executable, helper("verify-attribution-chain.py"), "--json"]
    for path in files:
        cmd += ["--file", path]
    _code, out, _err = run(cmd)
    return as_json(out) if out.strip() and isinstance(as_json(out), dict) else dict(EMPTY_ATTRIBUTION)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--leave-unclaimed", action="append", default=[], metavar="PATH",
                        help="an unclaimed path commit QA rejected: left in the tree, not swept (repeatable)")
    args = parser.parse_args(argv)
    task_id = args.task_id

    control_root = git_top()
    home = os.environ.get("CLAUDE_HOME") or str(HARNESS_ROOT)
    nested_repo = git_top(os.path.realpath(home))
    _code, close_out, _err = run(["bash", helper("resolve-close-report.sh"), task_id])
    close_report = close_out.strip()
    # The close report is <project>/docs/dev/close-report-<id>.md and the task's dev and do reports sit
    # beside it: the same <project>/docs/dev join their writers use.
    report_project = Path(close_report).parent.parent.parent if close_report else Path(control_root)
    docs_root = report_project / "docs" / "dev"
    project_root = docs_root.resolve().parent.parent

    code, out, _err = run([sys.executable, helper("late-repair-controller.py"), "resolve-effective-report",
                           "--task-id", task_id, "--project-dir", str(project_root)])
    late = as_json(out) if code == 0 and isinstance(as_json(out), dict) else None
    task_report = choose_report(docs_root, task_id, late)

    cmd = [sys.executable, helper("resolve-commit-repos.py"), "--task-id", task_id,
           "--control-root", control_root, "--report", task_report]
    if nested_repo:
        cmd += ["--supported-repo", nested_repo]
    code, out, err = run(cmd)
    plan = as_json(out) if code == 0 and isinstance(as_json(out), dict) else None
    plan_error = None if plan is not None else (err.strip() or f"resolve-commit-repos.py exited {code}")

    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID") or ""
    manifest = None
    if session_id:
        sys.path.insert(0, str(HARNESS_ROOT / "hooks" / "lib"))
        from commit_pipeline import manifest_path  # noqa: E402
        manifest = manifest_path(session_id)
    status = {}
    for entry in (plan or {}).get("repositories") or []:
        _code, out, _err = run(["git", "-C", entry["repo_root"], "status", "--porcelain=v1"])
        status[entry["repo_root"]] = out.splitlines()
    owns_none = plan is not None and not any(e.get("owned_paths") for e in plan.get("repositories") or [])
    sweep = unclaimed(control_root, docs_root, task_id, args.leave_unclaimed, session_id) if owns_none else None
    extra = {"unclaimed": sweep} if sweep is not None else {}

    print(json.dumps({
        "task_id": task_id,
        "control_root": control_root,
        "nested_repo": nested_repo,
        "close_report": close_report,
        "late_repair": late,
        "task_report": task_report,
        "plan_error": plan_error,
        "repository_plan": plan,
        "attribution_log": attribution_log(plan, [f"{control_root}/{p}" for p in (sweep or {}).get("paths", [])]),
        "session_id": session_id,
        "manifest_path": manifest,
        "files_at_dispatch": status,
        **extra,
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
