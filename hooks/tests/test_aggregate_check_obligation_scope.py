"""G3 (hooks/pretool-aggregate-check.py), its QA-only collection check, decided
from the QA dispatch's own obligation (P3 row 12).

(a) A QA dispatch carrying an obligation is checked against its own task's
    family only: another task's orphan lane reports never block it, and an
    obligation naming no task (a bulk commit-qa) scopes to no family instead of
    falling back to the global scan.
(b) The canonical aggregate of a fan-out in scope must parse, validate against
    dev-report.v2, carry its task's identity, and name in parallel_workers
    exactly the lanes the lane reports record and the obligation's lane_set.
    This check blocks while CLAUDE_OBLIGATION_BARRIER=block and warns (reason on
    stderr, exit 0) otherwise.

Run with: python3 -m pytest hooks/tests/test_aggregate_check_obligation_scope.py -v
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "pretool-aggregate-check.py"
TASK = "20260101-120000"
OTHER = "20260101-110000"
LANES = ["l1", "l2"]


def _lane_report(task, lane, lanes):
    tid = f"{task}-{lane}"
    return {
        "request_id": tid, "task_id": tid, "report_version": 2,
        "timestamp": "2026-01-01T12:00:00Z", "baseline_head_sha": "abc123def456",
        "baseline_dirty_snapshot": "", "lane": lane, "lane_set": lanes,
        "owned_edits": {}, "pre_edit_snapshots": {},
        "dev": {"status": "completed", "files_modified": [], "files_created": [],
                "tasks_completed": [], "scripts_created": [], "permissions_to_add": [],
                "observed_preexisting": []},
        "blocking_issues": [], "recommendations": [],
    }


def _canonical(task, workers):
    """The shape scripts/aggregate-dev-report.py writes for a fan-out."""
    return {
        "request_id": task, "task_id": task, "timestamp": "2026-01-01T12:30:00+00:00",
        "baseline_head_sha": "abc123def456", "baseline_dirty_snapshot": "",
        "dev_report_path": f"docs/dev/dev-report-{task}.json", "parallel_workers": workers,
        "owned_edits": {}, "pre_edit_snapshots": {},
        "dev": {"status": "completed", "files_modified": [], "files_created": [],
                "tasks_completed": [], "scripts_created": [], "permissions_to_add": [],
                "observed_preexisting": []},
        "blocking_issues": [], "recommendations": [],
    }


def _write(path, doc):
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc))
    return path


def _fanout(dev_dir, task, lanes, lane_set=None, workers=None):
    for lane in lanes:
        _write(dev_dir / f"dev-report-{task}-{lane}.json", _lane_report(task, lane, lane_set or lanes))
    if workers is not None:
        return _write(dev_dir / f"dev-report-{task}.json", _canonical(task, workers))
    return dev_dir / f"dev-report-{task}.json"


def _obligation(task_id, profile="final_verification", pipeline="dev", lane=None, lane_set=None):
    doc = {
        "task_id": task_id, "lane": lane, "lane_set": lane_set, "role": "qa",
        "pipeline": pipeline, "profile": profile, "dispatched_at": "2026-01-01T12:00:00Z",
        "artifacts": [{"kind": "json", "path": f"docs/dev/qa-report-{task_id}.json",
                       "schema": "qa-report.v2", "identity": {"task_id": task_id}}],
    }
    if task_id is None:
        doc["artifacts"] = [{"kind": "markdown", "path": "docs/dev/commit-qa-report-bulk.md",
                             "identity_anchor": "bulk", "terminal_line_regex": "^COMMIT: (APPROVE|REJECT)"}]
    return f'<obligation v="1">{json.dumps(doc)}</obligation>\n'


def _run(project, prompt, mode=None):
    """G3 as the CLI runs it, for a QA dispatch with this prompt (no dev-report-,
    context-, ticket- or do-report- path in it unless the test puts one)."""
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project), "HOME": str(project / "home"),
           "CLAUDE_STATE_DIR": str(project / "state"), "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("CLAUDE_OBLIGATION_BARRIER", None)
    if mode:
        env["CLAUDE_OBLIGATION_BARRIER"] = mode
    payload = {"tool_name": "Agent", "session_id": "g3-scope", "agent_id": "qa-dispatch-test",
               "tool_input": {"subagent_type": "qa", "prompt": prompt}}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True,
                          capture_output=True, env=env, cwd=str(project), timeout=60)


def _promoted_exit(mode):
    """Row 12(b) blocks while the barrier is armed and warns otherwise."""
    return 2 if mode == "block" else 0


@pytest.fixture
def dev_dir(tmp_path):
    path = tmp_path / "docs" / "dev"
    path.mkdir(parents=True)
    return path


# --------------------------------------------------------------------------
# (a) scope
# --------------------------------------------------------------------------

@pytest.mark.parametrize("mode", [None, "block"])
def test_another_tasks_orphan_shards_do_not_block_this_tasks_qa(dev_dir, mode):
    _fanout(dev_dir, OTHER, LANES)  # every lane reported, its canonical never written
    result = _run(dev_dir.parents[1], _obligation(TASK), mode)
    assert (result.returncode, result.stderr) == (0, "")


@pytest.mark.parametrize("mode", [None, "block"])
def test_an_obligation_naming_no_task_scopes_to_no_family(dev_dir, mode):
    """/commit --bulk's QA (profile commit-qa, task_id null) collects no
    fan-out: the global scan is only for a dispatch with no obligation."""
    _fanout(dev_dir, OTHER, LANES)
    result = _run(dev_dir.parents[1], _obligation(None, profile="commit-qa", pipeline="commit"), mode)
    assert (result.returncode, result.stderr) == (0, "")


def test_without_an_obligation_the_global_scan_still_demands_the_canonical(dev_dir):
    canonical = _fanout(dev_dir, OTHER, LANES)
    result = _run(dev_dir.parents[1], "Verify the implementation.")
    assert result.returncode == 2
    assert f"[canonical_missing] {canonical}" in result.stderr


@pytest.mark.parametrize("mode", [None, "block"])
def test_this_tasks_missing_canonical_still_blocks(dev_dir, mode):
    canonical = _fanout(dev_dir, TASK, LANES)
    result = _run(dev_dir.parents[1], _obligation(f"{TASK}-l1", lane="l1", lane_set=LANES), mode)
    assert result.returncode == 2
    assert f"[canonical_missing] {canonical}" in result.stderr


# --------------------------------------------------------------------------
# (b) the canonical's content: a block while armed, a warning otherwise
# --------------------------------------------------------------------------

@pytest.mark.parametrize("mode", [None, "block"])
def test_compliant_canonical_passes_without_a_warning(dev_dir, mode):
    """The aggregator lists parallel_workers sorted whatever the lane_set's
    order: the roster is compared as a set of lanes, not as a sequence."""
    _fanout(dev_dir, TASK, ["l1", "l2"], lane_set=["l2", "l1"], workers=["l1", "l2"])
    result = _run(dev_dir.parents[1], _obligation(f"{TASK}-l2", lane="l2", lane_set=["l2", "l1"]), mode)
    assert (result.returncode, result.stderr) == (0, "")


@pytest.mark.parametrize("mode", [None, "block"])
def test_workers_beyond_the_shard_lanes_warn(dev_dir, mode):
    canonical = _fanout(dev_dir, TASK, LANES, workers=["l1", "l2", "l3"])
    result = _run(dev_dir.parents[1], _obligation(TASK), mode)
    assert result.returncode == _promoted_exit(mode)
    assert (f"[canonical_roster_mismatch] {canonical}: its parallel_workers ['l1', 'l2', 'l3'] "
            "differ from the lanes its lane reports record ['l1', 'l2']") in result.stderr


def test_workers_missing_a_lane_warn_while_advisory_and_block_when_armed(dev_dir):
    """The armed stale-canonical rule (P1b) keeps its block; advisory, the
    same canonical is reported by this check instead of passing silently."""
    canonical = _fanout(dev_dir, TASK, LANES, workers=["l1"])
    advisory = _run(dev_dir.parents[1], _obligation(TASK))
    assert advisory.returncode == 0
    assert (f"[canonical_roster_mismatch] {canonical}: its parallel_workers ['l1'] differ from "
            "the lanes its lane reports record ['l1', 'l2']") in advisory.stderr
    armed = _run(dev_dir.parents[1], _obligation(TASK), "block")
    assert armed.returncode == 2
    assert f"[canonical_stale] {canonical}" in armed.stderr
    assert "canonical_roster_mismatch" not in armed.stderr


@pytest.mark.parametrize("mode", [None, "block"])
def test_workers_differing_from_the_obligations_lane_set_warn(dev_dir, mode):
    canonical = _fanout(dev_dir, TASK, LANES, workers=LANES)
    result = _run(dev_dir.parents[1], _obligation(f"{TASK}-l1", lane="l1", lane_set=["l1", "l2", "l3"]), mode)
    assert result.returncode == _promoted_exit(mode)
    assert (f"[canonical_roster_mismatch] {canonical}: its parallel_workers ['l1', 'l2'] "
            "differ from the dispatch obligation's lane_set ['l1', 'l2', 'l3']") in result.stderr
    # Its producer is a hook: the finding names the dispatch that runs it (P1b E5 (a)).
    assert (f"| reached by: dispatching again the dev dispatch that declared docs/dev/dev-report-{TASK}-l1.json "
            "(lane l1), which writes that report again in that dispatch; the write runs it") in result.stderr


@pytest.mark.parametrize("mode", [None, "block"])
def test_canonical_failing_dev_report_v2_warns(dev_dir, mode):
    canonical = _fanout(dev_dir, TASK, LANES, workers=LANES)
    doc = json.loads(canonical.read_text())
    del doc["owned_edits"]
    _write(canonical, doc)
    result = _run(dev_dir.parents[1], _obligation(TASK), mode)
    assert result.returncode == _promoted_exit(mode)
    assert f"[canonical_schema_invalid] {canonical}: schema-invalid under obligation-supplied schema" \
        in result.stderr
    assert "owned_edits" in result.stderr


def test_canonical_that_does_not_parse_warns_while_advisory(dev_dir):
    """Armed, the stale-canonical rule (P1b) already blocks it: it names no lane."""
    canonical = _fanout(dev_dir, TASK, LANES)
    _write(canonical, "{not json")
    advisory = _run(dev_dir.parents[1], _obligation(TASK))
    assert advisory.returncode == 0
    assert f"[canonical_not_valid_json] {canonical}: obligation-named artifact is not valid JSON" \
        in advisory.stderr
    armed = _run(dev_dir.parents[1], _obligation(TASK), "block")
    assert armed.returncode == 2
    assert f"[canonical_stale] {canonical}" in armed.stderr


@pytest.mark.parametrize("mode", [None, "block"])
def test_canonical_carrying_another_identity_warns(dev_dir, mode):
    canonical = _fanout(dev_dir, TASK, LANES, workers=LANES)
    _write(canonical, {**json.loads(canonical.read_text()), "task_id": OTHER})
    result = _run(dev_dir.parents[1], _obligation(TASK), mode)
    assert result.returncode == _promoted_exit(mode)
    assert (f"[canonical_identity_mismatch] {canonical}: its task_id '{OTHER}' and request_id "
            f"'{TASK}' are not its task's '{TASK}'") in result.stderr

