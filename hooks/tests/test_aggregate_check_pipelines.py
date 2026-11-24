"""G3 (hooks/pretool-aggregate-check.py) takes the task of a lane report by the
aggregator's one definition (scripts/aggregate-dev-report.py task_of_lane_report),
not by the stamp its name starts with: two pipelines of one overnight run
(<stamp>-0, <stamp>-1) are two tasks, and a QA dispatch for one is judged by that
pipeline's reports only. A plain fan-out of a bare stamp is judged as before.

Run with: python3 -m pytest hooks/tests/test_aggregate_check_pipelines.py -v
"""

import importlib.util
import json

import pytest

from test_aggregate_check_obligation_scope import HOOK, _canonical, _fanout, _obligation, _run, _write

STAMP = "20260101-120000"
P0, P1 = f"{STAMP}-0", f"{STAMP}-1"
LANES = ["l1", "l2"]
# The aggregator labels a pipeline's lane <suffix>-<lane> and lists those labels in parallel_workers.
LABELS0, LABELS1 = [f"0-{lane}" for lane in LANES], [f"1-{lane}" for lane in LANES]


@pytest.fixture
def dev_dir(tmp_path):
    path = tmp_path / "docs" / "dev"
    path.mkdir(parents=True)
    return path


def _two_pipelines(dev_dir):
    """Pipeline 0 collected (a compliant canonical); pipeline 1's lanes all reported, its canonical missing."""
    _fanout(dev_dir, P0, LANES, workers=LABELS0)
    return _fanout(dev_dir, P1, LANES)


@pytest.mark.parametrize("mode", [None, "block"])
def test_a_pipelines_qa_is_not_judged_by_the_other_pipelines_reports(dev_dir, mode):
    _two_pipelines(dev_dir)
    result = _run(dev_dir.parents[1], _obligation(f"{P0}-l1", lane="l1", lane_set=LANES), mode)
    assert (result.returncode, result.stderr) == (0, "")
    assert not (dev_dir / f"dev-report-{STAMP}.json").exists()  # no aggregate of every pipeline together


@pytest.mark.parametrize("mode", [None, "block"])
def test_the_other_pipelines_qa_is_judged_by_its_own_reports(dev_dir, mode):
    canonical = _two_pipelines(dev_dir)
    result = _run(dev_dir.parents[1], _obligation(P1, lane_set=LANES), mode)
    assert result.returncode == 2
    assert f"[canonical_missing] {canonical}" in result.stderr
    assert P0 not in result.stderr
    assert not (dev_dir / f"dev-report-{STAMP}.json").exists()


def test_the_global_scan_names_the_pipeline_whose_canonical_is_missing(dev_dir):
    canonical = _two_pipelines(dev_dir)
    result = _run(dev_dir.parents[1], "Verify the implementation.")
    assert result.returncode == 2
    assert f"[canonical_missing] {canonical}" in result.stderr
    assert f"dev-report-{STAMP}.json" not in result.stderr


@pytest.mark.parametrize("lanes", [["l1", "l2"], ["lane-a", "lane-b"]])
def test_a_plain_fan_out_is_judged_as_before(dev_dir, lanes):
    """A bare stamp's fan-out, lane names with a dash included: missing canonical blocks, a compliant one passes."""
    project = dev_dir.parents[1]
    canonical = _fanout(dev_dir, STAMP, lanes)
    result = _run(project, _obligation(f"{STAMP}-{lanes[0]}", lane=lanes[0], lane_set=lanes), "block")
    assert result.returncode == 2
    assert f"[canonical_missing] {canonical}" in result.stderr
    _fanout(dev_dir, STAMP, lanes, workers=lanes)
    result = _run(project, _obligation(f"{STAMP}-{lanes[0]}", lane=lanes[0], lane_set=lanes), "block")
    assert (result.returncode, result.stderr) == (0, "")


def _without_lane(path):
    """The lane report at path, naming neither its lane nor a lane_set."""
    report = json.loads(path.read_text())
    report.pop("lane"), report.pop("lane_set")
    path.write_text(json.dumps(report))


def _hook():
    spec = importlib.util.spec_from_file_location("pretool_aggregate_check", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_report_naming_no_lane_is_its_pipelines_not_the_stamps(dev_dir):
    """A lane report that names no lane belongs to the task the definition accepts it for, never to the bare stamp
    that every pipeline shares: two pipelines' such reports are two tasks' lanes."""
    _fanout(dev_dir, P0, LANES)
    _fanout(dev_dir, P1, LANES)
    for task in (P0, P1):
        _without_lane(dev_dir / f"dev-report-{task}-l2.json")
    lane_reports, _ = _hook()._scan_dev_dir(dev_dir)
    assert {task: sorted(reports) for task, reports in lane_reports.items()} == {P0: LANES, P1: LANES}


@pytest.mark.parametrize("mode", [None, "block"])
def test_a_pipelines_lane_report_naming_no_lane_is_reported(dev_dir, mode):
    """Pipeline 1 collected; its lane l2's report names no lane: the lane has reported, nothing is missing.
    The canonical is written after the last lane report (the order of a collected fan-out): rewritten before it, a
    lane report is never newer, so no rebuild (the aggregator's, which refuses this fixture's lane names) is asked."""
    _fanout(dev_dir, P1, LANES)
    _without_lane(dev_dir / f"dev-report-{P1}-l2.json")
    _write(dev_dir / f"dev-report-{P1}.json", _canonical(P1, LABELS1))
    result = _run(dev_dir.parents[1], _obligation(f"{P1}-l1", lane="l1", lane_set=LANES), mode)
    assert (result.returncode, result.stderr) == (0, "")


def test_the_aggregators_refusal_of_a_pipelines_lane_names_that_lane(dev_dir):
    """The aggregator labels a pipeline's lane <suffix>-<lane> (1-l2); the canonical_missing hint still names the
    lane whose own report it refuses, l2, not the dispatch's own lane l1."""
    _fanout(dev_dir, P1, LANES, workers=LABELS1)
    (dev_dir / f"dev-report-{P1}.json").unlink()
    refused = dev_dir / f"dev-report-{P1}-l2.json"
    report = json.loads(refused.read_text())
    report["dev"]["status"] = "blocked"
    refused.write_text(json.dumps(report))
    result = _run(dev_dir.parents[1], _obligation(f"{P1}-l1", lane="l1", lane_set=LANES), "block")
    assert result.returncode == 2
    assert "[canonical_missing]" in result.stderr and "shard '1-l2': dev.status is 'blocked'" in result.stderr
    assert f"declared docs/dev/dev-report-{P1}-l2.json (lane l2)" in result.stderr
