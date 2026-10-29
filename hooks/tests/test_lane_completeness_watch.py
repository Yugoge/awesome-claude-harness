"""Tests for hooks/posttool-lane-completeness-watch.py, the one producer of a
fan-out's canonical aggregate (P1b E5): every lane report write runs the
harness's aggregator, next to the hook, on the project the hook ran in -- a
product repository has no scripts/ of its own. The roster (has every declared
lane reported, does the canonical name them all) is G3's check before QA.

Run with: python3 -m pytest hooks/tests/test_lane_completeness_watch.py -v
"""

import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "posttool-lane-completeness-watch.py"
TASK = "20260101-120000"
LANES = ["l1", "l2"]


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


def _run(project, written):
    payload = {"tool_name": "Write", "cwd": str(project),
               "tool_input": {"file_path": str(written), "content": written.read_text()}}
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True,
                          capture_output=True, env=env, cwd=str(project), timeout=120)


def _write_lanes(project, lane_set=LANES):
    dev_dir = project / "docs" / "dev"
    dev_dir.mkdir(parents=True)
    paths = []
    for lane in LANES:
        path = dev_dir / f"dev-report-{TASK}-{lane}.json"
        path.write_text(json.dumps(_lane_report(lane, lane_set)))
        paths.append(path)
    return dev_dir, paths


def test_last_lane_report_writes_canonical_in_a_project_without_scripts(tmp_path):
    project = tmp_path / "product"
    dev_dir, paths = _write_lanes(project)
    assert not (project / "scripts").exists()
    result = _run(project, paths[-1])
    assert result.returncode == 0, result.stderr
    canonical = json.loads((dev_dir / f"dev-report-{TASK}.json").read_text())
    assert sorted(canonical["parallel_workers"]) == LANES
    assert canonical["dev"]["status"] == "completed"


def test_report_without_lane_set_declares_no_roster(tmp_path):
    project = tmp_path / "product"
    dev_dir, paths = _write_lanes(project, lane_set=None)
    result = _run(project, paths[-1])
    assert result.returncode == 0, result.stderr
    assert not (dev_dir / f"dev-report-{TASK}.json").exists()


G3 = Path(__file__).resolve().parents[1] / "pretool-aggregate-check.py"


def _qa_dispatch(project, task_id):
    block = json.dumps({
        "task_id": task_id, "role": "qa", "pipeline": "dev", "profile": "final_verification",
        "dispatched_at": "2026-01-01T12:00:00Z",
        "artifacts": [{"kind": "json", "path": f"docs/dev/qa-report-{task_id}.json",
                       "schema": "qa-report.v2", "identity": {"task_id": task_id}}],
    })
    payload = {"tool_name": "Agent", "agent_id": "qa-dispatch-test",
               "tool_input": {"subagent_type": "qa", "prompt": f'<obligation v="1">{block}</obligation>'}}
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    env.pop("CLAUDE_OBLIGATION_BARRIER", None)
    return subprocess.run([sys.executable, str(G3)], input=json.dumps(payload), text=True,
                          capture_output=True, env=env, cwd=str(project), timeout=60)


def test_every_lane_write_runs_the_aggregator_and_g3_checks_the_roster(tmp_path):
    """No roster decision here: the second of three lane writes already
    aggregates the two lanes on disk, and G3 refuses QA until the third lands
    and its own write refreshes the canonical."""
    project = tmp_path / "product"
    dev_dir = project / "docs" / "dev"
    dev_dir.mkdir(parents=True)
    lanes = ["l1", "l2", "l3"]
    canonical = dev_dir / f"dev-report-{TASK}.json"
    for count, lane in enumerate(lanes, 1):
        path = dev_dir / f"dev-report-{TASK}-{lane}.json"
        path.write_text(json.dumps(_lane_report(lane, lanes)))
        assert _run(project, path).returncode == 0
        gate = _qa_dispatch(project, f"{TASK}-l1")
        if count == 1:
            assert not canonical.exists()
        else:
            assert sorted(json.loads(canonical.read_text())["parallel_workers"]) == lanes[:count]
        if count < len(lanes):
            assert gate.returncode == 2
            assert f"[lane_report_missing] {dev_dir / f'dev-report-{TASK}-l3.json'}" in gate.stderr
        else:
            assert gate.returncode == 0, gate.stderr
