#!/usr/bin/env python3
"""Resolve dev-report path for a task by walking up from changed files' common ancestor.

Usage:
  git status --porcelain=v1 | python3 resolve-dev-report.py \
      --task-id TASK_ID --git-root GIT_ROOT --control-root CONTROL_ROOT

Reads repo-relative changed paths from stdin (one per line, porcelain=v1 format accepted).
For rename/copy records (lines starting with R or C), uses the destination path (after " -> ").
Prints the resolved dev-report path to stdout, or nothing if not found.
Exit 0 in both cases; non-zero only on argument errors.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from sibling_loader import load_sibling_module  # noqa: E402


def _load_late_repair_controller():
    """Load late-repair-controller.py (R4 tri-state guard).

    Delegates to the single canonical implementation in
    scripts/lib/sibling_loader.py.
    """
    return load_sibling_module("late-repair-controller.py", __file__)


_FAIL_CLOSED = object()


def _tri_state_guard(candidate_root, task_id):
    """R4 tri-state guard for one candidate project root.

    Returns the verified effective report path (State B), the sentinel
    _FAIL_CLOSED (State C -- a run record/effective report exists but
    corroboration fails; caller MUST NOT fall back to stale canonical), or
    None (State A -- no late-repair state at all; caller's existing
    canonical/fallback resolution is unaffected).
    """
    controller = _load_late_repair_controller()
    state, effective_path = controller.resolve_effective_report_state(
        Path(candidate_root), task_id
    )
    if state == "verified" and effective_path is not None and effective_path.is_file():
        return str(effective_path)
    if state == "invalid":
        return _FAIL_CLOSED
    return None


def parse_changed_paths(lines):
    paths = []
    for line in lines:
        line = line.rstrip("\n")
        if not line:
            continue
        # porcelain=v1: "XY path" or "XY orig -> dest"
        if len(line) > 3 and line[2] == " ":
            rest = line[3:]
        else:
            rest = line
        if " -> " in rest:
            rest = rest.split(" -> ", 1)[1]
        paths.append(rest.strip())
    return paths


def resolve(task_id, git_root, control_root, changed_paths):
    if not changed_paths:
        dev_report_path = None
    else:
        abs_paths = [os.path.realpath(os.path.join(git_root, p)) for p in changed_paths]
        parent_dirs = [os.path.dirname(p) for p in abs_paths]

        control_docs_dev = os.path.realpath(os.path.join(control_root, "docs", "dev"))
        filtered_dirs = [d for d in parent_dirs if not d.startswith(control_docs_dev)]
        search_dirs = filtered_dirs if filtered_dirs else parent_dirs

        common = os.path.commonpath(search_dirs)

        candidate = common
        dev_report_path = None
        while True:
            if os.path.isdir(os.path.join(candidate, "docs", "dev")):
                guard = _tri_state_guard(candidate, task_id)
                if guard is _FAIL_CLOSED:
                    return None
                if guard is not None:
                    dev_report_path = guard
                    break
                path = os.path.join(candidate, "docs", "dev", f"dev-report-{task_id}.json")
                if os.path.isfile(path):
                    dev_report_path = path
                    break
            parent = os.path.dirname(candidate)
            if parent == candidate:
                break
            candidate = parent

    if dev_report_path is None:
        guard = _tri_state_guard(control_root, task_id)
        if guard is _FAIL_CLOSED:
            return None
        if guard is not None:
            dev_report_path = guard
        else:
            fallback = os.path.join(control_root, "docs", "dev", f"dev-report-{task_id}.json")
            if os.path.isfile(fallback):
                dev_report_path = fallback

    return dev_report_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--git-root", required=True)
    parser.add_argument("--control-root", required=True)
    args = parser.parse_args()

    changed_paths = parse_changed_paths(sys.stdin.read().splitlines())
    result = resolve(args.task_id, args.git_root, args.control_root, changed_paths)
    if result:
        print(result)


if __name__ == "__main__":
    main()
