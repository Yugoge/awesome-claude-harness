#!/usr/bin/env python3
"""build-pipelines-from-triage.py — emit pipeline definitions JSON to stdout.
Consumes PM triage schema (issues[] keyed by triage_index + pipeline_order[] +
pipeline_recommendation). Honors the addressed_issues filter.
Usage: build-pipelines-from-triage.py <triage.json> <addressed.json> <ts> [session_id] [output_root]

ts: the stem of the pipelines' task ids (<ts>-<index>). "-": the cycle's own stamp, the created_at of its
    cycle contract beside the triage report (<dir>/cycle-<N>/cycle-contract.json for
    <dir>/triage-report-cycle<N>.json), which hooks/posttool-subagent-track.py writes once per cycle when PM
    TRIAGE returns: the same for every reader of the cycle, another for every cycle; no agent reads a clock.
output_root: base directory for spec paths (default: docs/dev/overnight, override via
             OUTPUT_ROOT env var or positional arg 5)
"""
import json, os, re, sys

if len(sys.argv) < 4:
    sys.exit("Usage: build-pipelines-from-triage.py <triage> <addressed> <ts|-> [sid] [output_root]")


def cycle_stamp(triage_path: str) -> str:
    """The YYYYMMDD-HHMMSS of the created_at of the cycle contract beside ``triage_path``; exits without one."""
    m = re.fullmatch(r"triage-report-cycle(\d+)\.json", os.path.basename(triage_path))
    contract = os.path.join(os.path.dirname(triage_path), f"cycle-{m.group(1)}", "cycle-contract.json") if m else ""
    try:
        at = json.load(open(contract)).get("created_at") if contract else None
    except (OSError, ValueError, AttributeError):
        at = None
    t = re.fullmatch(r"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)Z", at) if isinstance(at, str) else None
    if not t:
        sys.exit(f"no cycle stamp: {contract or triage_path} has no readable created_at (the cycle contract is "
                 "written when PM TRIAGE returns; the triage report must be triage-report-cycle<N>.json)")
    return "".join(t.groups()[:3]) + "-" + "".join(t.groups()[3:])


triage = json.load(open(sys.argv[1]))
addressed = set(json.load(open(sys.argv[2])) or [])
ts = cycle_stamp(sys.argv[1]) if sys.argv[3] == "-" else sys.argv[3]
sid = sys.argv[4] if len(sys.argv) > 4 else "overnight"
output_root = sys.argv[5] if len(sys.argv) > 5 else os.environ.get("OUTPUT_ROOT", "docs/dev/overnight")
by_idx = {i["triage_index"]: i for i in triage.get("issues", []) if "triage_index" in i}
order = triage.get("pipeline_order") or sorted(by_idx)
pipes, j = [], 0
for ti in order:
    x = by_idx.get(ti)
    if not x or x.get("pipeline_recommendation") != "fix": continue
    key = f"{x.get('location','')}|{x.get('description','')}"
    if key in addressed: continue
    pipes.append({"index": j, "triage_index": ti, "description": x.get("description"), "location": x.get("location"),
                  "severity": x.get("severity"), "category": x.get("category"),
                  "agents_flagged": x.get("agents_flagged", []), "phase": "pending", "iteration": 0,
                  "status": "active", "timestamp_suffix": f"{ts}-{j}", "tier": x.get("tier", 2),
                  "pm_recommended": True, "spec_path": f"{output_root}/{sid}/spec-pipeline-{j}.md"})
    j += 1
json.dump(pipes, sys.stdout, indent=2)
