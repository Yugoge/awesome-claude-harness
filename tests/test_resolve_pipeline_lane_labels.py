"""A pipeline's lanes (task <stamp>-1, lane l1: dev-report-<stamp>-1-l1.json) are labelled by the aggregator
(scripts/aggregate-dev-report.py lane_label: '1-l1') in the canonical's parallel_workers; every reader of that
roster takes the label from that one definition. The resolver (scripts/resolve-dev-artifact-chain.py) and the
aggregator's own revision attribution are checked against the aggregator's real output, for a pipeline's fan-out
and for a plain stamp's.

Run with: python3 -m pytest tests/test_resolve_pipeline_lane_labels.py -v
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_resolve_dev_artifact_chain import (
    REPO_ROOT, RESOLVER, _completion, _dev_dir, _dev_document, _error_codes, _materialise, _qa_document, _relative,
    _ticket, _write,
)  # noqa: E402

STAMP = "20260101-120000"
LANES = ["l1", "l2"]
TASKS = [pytest.param(STAMP, id="plain"), pytest.param(f"{STAMP}-1", id="pipeline")]


def _aggregate(root: Path, task: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "aggregate-dev-report.py"), "--task-id", task],
                          capture_output=True, text=True, cwd=str(root), env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)})


def _collected(root: Path, task: str) -> list[str]:
    """Lane reports, tickets, contexts and QA reports of two lanes, the real aggregator's canonical, the completion."""
    dev_dir = _dev_dir(root)
    references = [f"docs/dev/dev-report-{task}.json"]
    for index, lane in enumerate(LANES):
        identity = f"{task}-{lane}"
        _materialise(root, f"scripts/lane-{index}.py")
        dev = {**_dev_document(identity, modified=[f"scripts/lane-{index}.py"]), "lane": lane, "lane_set": LANES}
        _write(dev_dir / f"ticket-{identity}.md", _ticket(identity))
        _write(dev_dir / f"context-{identity}.json", {"request_id": identity, "task_id": identity})
        _write(dev_dir / f"dev-report-{identity}.json", dev)
        _write(dev_dir / f"qa-report-{identity}.json", _qa_document(identity))
        references += [f"docs/dev/{kind}-{identity}.{ext}" for kind, ext in
                       (("ticket", "md"), ("context", "json"), ("dev-report", "json"), ("qa-report", "json"))]
    made = _aggregate(root, task)
    assert made.returncode == 0, made.stderr
    _write(dev_dir / f"completion-{task}.md", _completion(task, references))
    return json.loads((dev_dir / f"dev-report-{task}.json").read_text())["parallel_workers"]


@pytest.mark.parametrize("task", TASKS)
def test_the_resolver_reads_the_aggregators_labels_as_the_lanes_it_scans(tmp_path, task):
    workers = _collected(tmp_path, task)
    result = RESOLVER.resolve_chain(tmp_path, task)
    assert result["parallel_workers"] == workers
    assert result["status"] == "pass", result["errors"]
    assert [lane["task_id"] for lane in result["lanes"]] == [f"{task}-{lane}" for lane in LANES]
    assert [lane["dev_report"] for lane in result["lanes"]] == [f"docs/dev/dev-report-{task}-{lane}.json" for lane in LANES]


@pytest.mark.parametrize("task", TASKS)
def test_a_roster_lane_without_a_shard_is_still_reported(tmp_path, task):
    """The lane_set names bare lanes: a lane whose shard is gone is one mismatch for that lane, whatever the labels."""
    _collected(tmp_path, task)
    (tmp_path / "docs" / "dev" / f"dev-report-{task}-l2.json").unlink()
    result = RESOLVER.resolve_chain(tmp_path, task)
    assert "LANE_SET_MISMATCH" in _error_codes(result)


@pytest.mark.parametrize("task", TASKS)
def test_a_revision_of_a_lane_is_that_lane_not_a_worker(tmp_path, task):
    """A fix round (dev-report-<task>-l1-round2.json, identity <task>-l1) is attributed to its lane by the aggregator."""
    workers = _collected(tmp_path, task)
    dev_dir = tmp_path / "docs" / "dev"
    revision = json.loads((dev_dir / f"dev-report-{task}-l1.json").read_text())
    _write(dev_dir / f"dev-report-{task}-l1-round2.json", revision)
    again = _aggregate(tmp_path, task)
    assert again.returncode == 0, again.stderr
    assert json.loads((dev_dir / f"dev-report-{task}.json").read_text())["parallel_workers"] == workers
    assert "UNDECLARED_LANE_ARTIFACT" not in _error_codes(RESOLVER.resolve_chain(tmp_path, task))
