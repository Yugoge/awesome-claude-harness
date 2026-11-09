#!/usr/bin/env python3
"""Compatibility entry point: /dev-overnight Step 17's iteration plan as origin/master's command text runs it.

COMPATIBILITY CODE (live landing, D15/D25), kept like the old permission spellings of D14:
delete this file and tests/test_iterate_failed_pipelines_compat.py together once no session
predates merge train 2's landing. Nothing in this tree calls it. P9 (666bac17) deleted it because
this tree's /dev-overnight Step 17 re-dispatches a failed lane's dev from its QA report and builds
no iteration plan, and that stands; but a session that took up origin/master's /dev-overnight text
before the landing keeps running, at Step 17 once a pipeline is qa_failed,

    python3 ~/.claude/scripts/iterate-failed-pipelines.py docs/dev/overnight/<session_id>/pipelines.json > docs/dev/overnight/<session_id>/iteration-plan.json

(commands/dev-overnight.md:1384 on a7d3a9f, :1487 on 2acc29b). Without this file that call exits
2 (can't open file) and leaves iteration-plan.json empty, and the unattended session has no plan
to iterate: a dead end for a running session (D25).

Below this docstring it is origin/master's script (a7d3a9f) line for line, so the call gets
master's answer: the same stdout, the same exit codes, the same usage error. Master's docstring:

iterate-failed-pipelines.py — emit per-pipeline iteration plan for failed pipelines.
Reads pipelines JSON path; outputs iteration plan JSON to stdout. The orchestrator
consumes the plan and dispatches Dev+QA per item.
Usage: iterate-failed-pipelines.py <pipelines.json>
"""
import json, os, sys

if len(sys.argv) < 2:
    sys.exit("Usage: iterate-failed-pipelines.py <pipelines.json>")
pipes = json.load(open(sys.argv[1]))
SEV = {"critical": 0, "major": 1, "minor": 2, "cosmetic": 3}
failed = [p for p in pipes if p.get("phase") == "qa_failed"]
failed.sort(key=lambda p: (SEV.get(p.get("severity"), 3), -len(p.get("agents_flagged", []))))
plan = [{"index": p["index"], "timestamp_suffix": p["timestamp_suffix"],
         "spec_path": p.get("spec_path"), "current_iteration": p.get("iteration", 0),
         "next_action": "ba_dev_qa_loop"} for p in failed]
project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
if not project_dir:
    sys.exit("Error: cannot determine project directory; set CLAUDE_PROJECT_DIR")
json.dump({"project_dir": project_dir, "iteration_plan": plan}, sys.stdout, indent=2)
