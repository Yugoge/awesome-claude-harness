#!/usr/bin/env python3
"""iterate-failed-pipelines.py — emit per-pipeline iteration plan for failed pipelines.
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
