"""No gate judges a fan-out from a canonical aggregate older than a lane report (scripts/aggregate-dev-report.py
stale_lane_reports and rebuild_if_stale; hooks/stop-command-gate.py disposition). Neutral values only."""
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TID = "20260101-120000"


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agg = _load("scripts/aggregate-dev-report.py", "aggregate_never_stale")


def _shard(lane, note):
    return {"task_id": f"{TID}-{lane}", "baseline_head_sha": "abc123def456", "baseline_dirty_snapshot": "",
            "lane": lane, "lane_set": ["l1", "l2"],
            "dev": {"status": "completed", "tasks_completed": [], "scripts_created": [], "permissions_to_add": [],
                    "files_modified": [f"src/{lane}.py"], "files_created": [], "observed_preexisting": []},
            "blocking_issues": [note] if note else [], "recommendations": []}


@pytest.fixture
def project(tmp_path):
    dev = tmp_path / "docs" / "dev"
    dev.mkdir(parents=True)
    for lane in ("l1", "l2"):
        (dev / f"dev-report-{TID}-{lane}.json").write_text(json.dumps(_shard(lane, "an open item")))
    assert agg.rebuild_if_stale(tmp_path, TID) == []
    return tmp_path


def _canonical(project):
    return project / "docs" / "dev" / f"dev-report-{TID}.json"


def _later(path):  # a write after the canonical's, whatever the clock's granularity
    stamp = _canonical(path.parents[2]).stat().st_mtime_ns + 10**9
    os.utime(path, ns=(stamp, stamp))


def test_a_lane_report_newer_than_the_aggregate_is_rebuilt_before_it_is_read(project):
    lane = project / "docs" / "dev" / f"dev-report-{TID}-l1.json"
    lane.write_text(json.dumps(_shard("l1", "")))
    _later(lane)
    assert agg.stale_lane_reports(project, TID) == [str(lane)]
    assert agg.rebuild_if_stale(project, TID) == []
    assert json.loads(_canonical(project).read_text())["blocking_issues"] == ["an open item"]  # l2's only


def test_a_report_written_by_a_shell_command_is_seen(project):
    lane = project / "docs" / "dev" / f"dev-report-{TID}-l2.json"
    subprocess.run(["sh", "-c", 'cat > "$1"', "_", str(lane)], input=json.dumps(_shard("l2", "")), text=True,
                   check=True)
    _later(lane)
    assert agg.rebuild_if_stale(project, TID) == []
    assert json.loads(_canonical(project).read_text())["blocking_issues"] == ["an open item"]  # l1's only


def test_a_rebuild_cut_off_leaves_the_old_aggregate_stale(project):
    before = _canonical(project).read_bytes()
    lane = project / "docs" / "dev" / f"dev-report-{TID}-l1.json"
    lane.write_text(json.dumps(_shard("l1", "")))
    _later(lane)
    assert agg.rebuild_if_stale(project, TID, timeout=0.001) == [str(lane)]
    assert _canonical(project).read_bytes() == before
    assert agg.stale_lane_reports(project, TID) == [str(lane)]


def test_the_gates_verdict_with_a_fresh_aggregate_is_unchanged(project, monkeypatch):
    gate = _load("hooks/stop-command-gate.py", "stop_gate_never_stale")
    chain = gate._script("scripts/resolve-dev-artifact-chain.py")
    monkeypatch.setattr(chain, "disposition_lines", lambda root, task, stage: [
        f"GAP artifact=docs/dev/dev-report-{task}.json problem=unresolved_blockers: x lane=-",
        f"GAP artifact=docs/dev/dev-report-{task}-l1.json problem=unresolved_blockers: y lane=l1"])
    fresh = gate.disposition(project, TID, "dev")
    assert fresh == chain.disposition_lines(project, TID, "dev")
    monkeypatch.setattr(gate._script("scripts/aggregate-dev-report.py"), "rebuild_if_stale",
                        lambda root, task: [f"/p/docs/dev/dev-report-{task}-l1.json"])
    stale = gate.disposition(project, TID, "dev")
    assert stale[0] == fresh[1] and len(stale) == 2 and "problem=stale_canonical" in stale[1]
