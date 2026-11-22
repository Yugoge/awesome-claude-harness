"""hooks/posttool-lane-completeness-watch.py, retired to an exit-0 stub: no registration runs it (its
rule of hooks/posttool-launch.py went), and the file stays for a hook list loaded before its
retirement (D15); a dev lane's stop and the QA dispatch's check rebuild the aggregate
(hooks/lib/aggregate_rebuild.py, tests/test_aggregate_at_lane_stop.py)."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "posttool-lane-completeness-watch.py"
NAME = HOOK.name
sys.path.insert(0, str(ROOT / "hooks"))
from lib import launch_settings  # noqa: E402  (the launchers' static table reader)
TASK = "20260101-120000"
LANES = ["l1", "l2"]


def test_the_unregistered_stub_decides_nothing(tmp_path):
    """One `# STUB:` line; no registration, a launcher's rule included; the last lane report of a
    fan-out it aggregated on, another Write and malformed stdin: exit 0, no output, nothing written."""
    assert sum(line.startswith("# STUB:") for line in HOOK.read_text().splitlines()) == 1
    settings = launch_settings.expand(json.loads((ROOT / "settings.json").read_text()), str(ROOT))
    assert not [h["command"] for groups in settings["hooks"].values() for g in groups for h in g["hooks"]
                if NAME in h["command"]]
    project = tmp_path / "product"
    dev_dir = project / "docs" / "dev"
    dev_dir.mkdir(parents=True)
    lanes = []
    for lane in LANES:
        lanes.append(dev_dir / f"dev-report-{TASK}-{lane}.json")
        lanes[-1].write_text(json.dumps(_lane_report(lane)))
    other = project / "notes.txt"
    other.write_text("x")
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    for written in (lanes[-1], other):
        payload = {"session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Write", "cwd": str(project),
                   "tool_input": {"file_path": str(written), "content": written.read_text()}}
        for raw in (json.dumps(payload), "{not json"):
            done = subprocess.run([sys.executable, str(HOOK)], input=raw, capture_output=True, text=True,
                                  cwd=project, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                                                    "HOME": str(tmp_path), "CLAUDE_PROJECT_DIR": str(project)})
            assert (done.returncode, done.stdout, done.stderr) == (0, "", "")
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before


def _lane_report(lane, lane_set=LANES):
    tid = f"{TASK}-{lane}"
    return {
        "request_id": tid, "task_id": tid, "report_version": 2,
        "timestamp": "2026-01-01T12:00:00Z", "baseline_head_sha": "abc123def456",
        "baseline_dirty_snapshot": "", "lane": lane, "lane_set": lane_set,
        "owned_edits": {}, "pre_edit_snapshots": {},
        "dev": {"status": "completed", "files_modified": [], "files_created": [],
                "tasks_completed": [], "scripts_created": [], "permissions_to_add": [],
                "observed_preexisting": []},
        "blocking_issues": [], "recommendations": [],
    }
