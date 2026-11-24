"""Two tasks sharing a stamp (an overnight run's pipelines <stamp>-0 and <stamp>-1, or <stamp>-c1-0 and
<stamp>-c2-0 when the stamp is the run's) are not each other's lanes: the aggregation's one definition of a
task's lane reports (scripts/aggregate-dev-report.py _is_worker_for_task), which stale_lane_reports and the
lane-stop rebuild (task_of_lane_report) use too. A real fan-out's lane reports are still found. Neutral values."""
import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STAMP = "20260101-120000"


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agg = _load("scripts/aggregate-dev-report.py", "aggregate_pipelines_not_lanes")


def _write(project, task_id, lane=None, lane_set=None, newer=0):
    doc = {"request_id": task_id, "task_id": task_id, "baseline_head_sha": "abc123def456",
           "dev": {"status": "completed", "files_modified": [], "files_created": []},
           "blocking_issues": [], "recommendations": []}
    if lane:
        doc.update(lane=lane, lane_set=lane_set)
    path = project / "docs" / "dev" / f"dev-report-{task_id}.json"
    path.write_text(json.dumps(doc))
    stamp = 1_700_000_000_000_000_000 + newer * 10**9
    os.utime(path, ns=(stamp, stamp))
    return path


@pytest.fixture
def project(tmp_path):
    (tmp_path / "docs" / "dev").mkdir(parents=True)
    return tmp_path


def _lanes(project, task_id):
    dev = project / "docs" / "dev"
    return sorted(p.name for _, p in agg._scan_shards(dev, agg._bare_task_id(task_id), task_id))


@pytest.mark.parametrize("pipelines", [[f"{STAMP}-0", f"{STAMP}-1"],
                                       [f"{STAMP}-c1-0", f"{STAMP}-c1-1", f"{STAMP}-c2-0"]],
                         ids=["old-stamp", "run-stamp"])
def test_pipelines_sharing_a_stamp_are_not_each_others_lanes(project, pipelines):
    for newer, task_id in enumerate(pipelines):
        _write(project, task_id, newer=newer)  # each later pipeline's report is newer than the one before
    for task_id in pipelines:
        assert _lanes(project, task_id) == []
        assert agg.stale_lane_reports(project, task_id) == []


@pytest.mark.parametrize("pipeline", [f"{STAMP}-0", f"{STAMP}-c1-0"], ids=["old-stamp", "run-stamp"])
def test_a_pipelines_own_fan_out_is_still_found_and_no_other_pipeline_joins_it(project, pipeline):
    other = pipeline[:-1] + "1"
    _write(project, other, newer=5)
    lanes = [_write(project, f"{pipeline}-{lane}", lane=lane, lane_set=["l1", "l2"], newer=1) for lane in ("l1", "l2")]
    _write(project, f"{pipeline}-iter2", newer=2)  # a round of the pipeline's own report, not a lane
    assert _lanes(project, pipeline) == sorted(p.name for p in lanes)
    assert agg.stale_lane_reports(project, pipeline) == [str(p) for p in lanes]  # no canonical yet
    _write(project, pipeline, newer=3)
    assert agg.stale_lane_reports(project, pipeline) == []
    assert _lanes(project, other) == []


def test_a_plain_fan_out_is_unchanged(project):
    lanes = [_write(project, f"{STAMP}-{lane}", lane=lane, lane_set=["l1", "l2"], newer=1) for lane in ("l1", "l2")]
    assert agg.stale_lane_reports(project, STAMP) == [str(p) for p in lanes]


@pytest.mark.parametrize("name, lane, task", [
    (f"dev-report-{STAMP}-l1.json", "l1", STAMP),
    (f"dev-report-{STAMP}-0-l1.json", "l1", f"{STAMP}-0"),
    (f"dev-report-{STAMP}-c2-0-l1.json", "l1", f"{STAMP}-c2-0"),
    (f"dev-report-dev-{STAMP}-l1.json", "l1", f"dev-{STAMP}"),
    (f"dev-report-{STAMP}-0-l1.json", "l2", None),
    (f"dev-report-{STAMP}-0.json", "", None),
])
def test_a_lane_reports_task_is_the_name_less_its_lane(name, lane, task):
    assert agg.task_of_lane_report(name, lane) == task
