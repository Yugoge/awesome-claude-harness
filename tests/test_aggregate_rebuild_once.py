"""A stale canonical aggregate is rebuilt at most once for one state of the lane reports, whoever asks
(scripts/aggregate-dev-report.py rebuild_if_stale), and a lane report is never taken for a canonical.
Neutral values only."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TID = "20260101-130000"


def _load():
    spec = importlib.util.spec_from_file_location("aggregate_rebuild_once", ROOT / "scripts" / "aggregate-dev-report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agg = _load()


def _shard(lane):
    return {"request_id": f"{TID}-{lane}", "task_id": f"{TID}-{lane}", "baseline_head_sha": "abc123def456",
            "baseline_dirty_snapshot": "", "lane": lane, "lane_set": ["l1", "l2"],
            "dev": {"status": "completed", "files_modified": [f"src/{lane}.py"]}, "blocking_issues": []}


@pytest.fixture
def stale(tmp_path, monkeypatch):
    """A two-lane fan-out whose canonical is older than both lane reports, and a rebuild that runs and
    fails (it leaves the canonical as it was): the calls are counted."""
    dev = tmp_path / "docs" / "dev"
    dev.mkdir(parents=True)
    (dev / f"dev-report-{TID}.json").write_text("{}")
    os.utime(dev / f"dev-report-{TID}.json", ns=(10**18, 10**18))
    for lane in ("l1", "l2"):
        (dev / f"dev-report-{TID}-{lane}.json").write_text(json.dumps(_shard(lane)))
        os.utime(dev / f"dev-report-{TID}-{lane}.json", ns=(2 * 10**18, 2 * 10**18))
    runs = []
    monkeypatch.setattr(agg.subprocess, "run", lambda argv, **kw: runs.append(argv))
    return tmp_path, runs


def test_one_state_of_the_lane_reports_is_rebuilt_once_whoever_asks(stale):
    project, runs = stale
    for timeout in (40, 40, 240):  # a lane's stop, the check at QA dispatch, the Stop gate
        assert len(agg.rebuild_if_stale(project, TID, timeout=timeout)) == 2  # still stale: the run failed
    assert len(runs) == 1


def test_a_new_state_of_the_lane_reports_is_rebuilt_again(stale):
    project, runs = stale
    agg.rebuild_if_stale(project, TID)
    lane = project / "docs" / "dev" / f"dev-report-{TID}-l1.json"
    os.utime(lane, ns=(3 * 10**18, 3 * 10**18))
    agg.rebuild_if_stale(project, TID)
    agg.rebuild_if_stale(project, TID)
    assert len(runs) == 2


def test_an_asker_during_a_run_does_not_start_a_second(stale):
    project, runs = stale
    with open(project / "docs" / "dev" / f".dev-report-{TID}.rebuild", "a+") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert len(agg.rebuild_if_stale(project, TID)) == 2
    assert runs == []


def test_a_cut_off_run_is_tried_by_the_next_asker(stale, monkeypatch):
    project, runs = stale

    def cut_off(argv, **kw):
        runs.append(argv)
        raise agg.subprocess.TimeoutExpired(argv, kw.get("timeout"))
    monkeypatch.setattr(agg.subprocess, "run", cut_off)
    agg.rebuild_if_stale(project, TID, timeout=1)
    agg.rebuild_if_stale(project, TID, timeout=1)
    assert len(runs) == 2


def test_a_lane_report_is_no_canonical_and_is_never_rebuilt(stale):
    project, runs = stale
    later = project / "docs" / "dev" / f"dev-report-{TID}-l2.json"  # newer than l1's own report
    os.utime(later, ns=(3 * 10**18, 3 * 10**18))
    assert agg.stale_lane_reports(project, f"{TID}-l1") == []
    assert agg.rebuild_if_stale(project, f"{TID}-l1") == []
    assert runs == []
