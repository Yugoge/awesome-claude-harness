"""G3 (hooks/pretool-aggregate-check.py) takes the task of a lane report by the
aggregator's one definition (scripts/aggregate-dev-report.py task_of_lane_report),
not by the stamp its name starts with: two pipelines of one overnight run
(<stamp>-0, <stamp>-1) are two tasks, and a QA dispatch for one is judged by that
pipeline's reports only. A plain fan-out of a bare stamp is judged as before.

Run with: python3 -m pytest hooks/tests/test_aggregate_check_pipelines.py -v
"""

import pytest

from test_aggregate_check_obligation_scope import _fanout, _obligation, _run

STAMP = "20260101-120000"
P0, P1 = f"{STAMP}-0", f"{STAMP}-1"
LANES = ["l1", "l2"]


@pytest.fixture
def dev_dir(tmp_path):
    path = tmp_path / "docs" / "dev"
    path.mkdir(parents=True)
    return path


def _two_pipelines(dev_dir):
    """Pipeline 0 collected (a compliant canonical); pipeline 1's lanes all reported, its canonical missing."""
    _fanout(dev_dir, P0, LANES, workers=LANES)
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
