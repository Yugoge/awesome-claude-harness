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


def attribution_log(plan: dict | None) -> dict:
    files = [f"{entry['repo_root']}/{path}" for entry in (plan or {}).get("repositories") or []
             for path in entry.get("owned_paths") or []]
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
    args = parser.parse_args(argv)
    task_id = args.task_id

    control_root = git_top()
    home = os.environ.get("CLAUDE_HOME") or str(HARNESS_ROOT)
    nested_repo = git_top(os.path.realpath(home))
    _code, close_out, _err = run(["bash", helper("resolve-close-report.sh"), task_id])
    close_report = close_out.strip()
    docs_root = Path(close_report).parent if close_report else Path(control_root) / "docs" / "dev"
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

    print(json.dumps({
        "task_id": task_id,
        "control_root": control_root,
        "nested_repo": nested_repo,
        "close_report": close_report,
        "late_repair": late,
        "task_report": task_report,
        "plan_error": plan_error,
        "repository_plan": plan,
        "attribution_log": attribution_log(plan),
        "session_id": session_id,
        "manifest_path": manifest,
        "files_at_dispatch": status,
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
