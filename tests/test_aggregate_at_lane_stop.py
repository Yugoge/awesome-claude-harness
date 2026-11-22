"""A fan-out's canonical aggregate is rebuilt where it is read, whatever wrote a lane report: at a dev lane's
stop (the subagent-stop chain's aggregate-rebuild rule) and at the QA dispatch's check (G3), by the Stop gate's
own staleness test and rebuild (scripts/aggregate-dev-report.py rebuild_if_stale). Neutral values only."""
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"
TID = "20260101-120000"
LANES = ["l1", "l2"]


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _report(lane, note=""):
    tid = f"{TID}-{lane}"
    return {"request_id": tid, "task_id": tid, "report_version": 2, "timestamp": "2026-01-01T12:00:00Z",
            "baseline_head_sha": "abc123def456", "baseline_dirty_snapshot": "", "lane": lane, "lane_set": LANES,
            "owned_edits": {}, "pre_edit_snapshots": {},
            "dev": {"status": "completed", "files_modified": [], "files_created": [], "tasks_completed": [],
                    "scripts_created": [], "permissions_to_add": [], "observed_preexisting": []},
            "blocking_issues": [note] if note else [], "recommendations": []}


def _dev(project):
    return project / "docs" / "dev"


def _canonical(project):
    return _dev(project) / f"dev-report-{TID}.json"


def _shell_write(project, lane, note=""):
    """A lane's report written by a shell command (no file tool), later than the canonical."""
    path = _dev(project) / f"dev-report-{TID}-{lane}.json"
    subprocess.run(["sh", "-c", 'cat > "$1"', "_", str(path)], input=json.dumps(_report(lane, note)), text=True,
                   check=True)
    if _canonical(project).is_file():
        stamp = _canonical(project).stat().st_mtime_ns + 10**9
        os.utime(path, ns=(stamp, stamp))
    return path


@pytest.fixture
def project(tmp_path, monkeypatch):
    project = tmp_path / "product"
    _dev(project).mkdir(parents=True)
    for lane in LANES:
        _shell_write(project, lane, f"an open item of {lane}")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    return project


def _lane_stop(project, tmp_path, lane):
    """The subagent-stop chain's aggregate-rebuild rule on lane `lane`'s stop (its own dispatch transcript)."""
    doc = {"task_id": f"{TID}-{lane}", "role": "dev", "pipeline": "dev", "profile": "fanout-lane",
           "dispatched_at": datetime.now(timezone.utc).isoformat(), "lane": lane, "lane_set": LANES,
           "artifacts": [{"kind": "json", "path": f"docs/dev/dev-report-{TID}-{lane}.json",
                          "schema": "dev-report.v2", "identity": {"task_id": f"{TID}-{lane}"}}]}
    transcript = tmp_path / f"agent-lane-{lane}.jsonl"
    prompt = f'<obligation v="1">\n{json.dumps(doc)}\n</obligation>'
    transcript.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n")
    sys.path.insert(0, str(HOOKS))
    try:
        gate = _load("hooks/subagentstop-producer-gate.py", "producer_gate_at_lane_stop")
        from lib import gate_runner
        rules = [r for r in gate.RULES if r.name == "aggregate-rebuild"]
        payload = {"hook_event_name": "SubagentStop", "session_id": "session-one", "agent_id": f"agent-{lane}",
                   "agent_transcript_path": str(transcript)}
        return rules, gate_runner.evaluate(rules, json.dumps(payload).encode())
    finally:
        sys.path.remove(str(HOOKS))


def test_a_lane_that_wrote_its_report_by_a_shell_command_stops_and_the_aggregate_is_rebuilt(project, tmp_path):
    first, _ = _lane_stop(project, tmp_path, "l2")
    assert first, "the subagent-stop chain has no aggregate-rebuild rule"
    assert json.loads(_canonical(project).read_text())["blocking_issues"] == ["an open item of l1", "an open item of l2"]
    _shell_write(project, "l1")  # l1 clears its item through a shell command, then stops
    _, outcomes = _lane_stop(project, tmp_path, "l1")
    assert [o.code for o in outcomes] == [0]
    assert json.loads(_canonical(project).read_text())["blocking_issues"] == ["an open item of l2"]
    agg = _load("scripts/aggregate-dev-report.py", "aggregate_at_lane_stop")
    assert agg.stale_lane_reports(project, TID) == []


def _qa_dispatch(project):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project), "CLAUDE_OBLIGATION_BARRIER": "block"}
    return subprocess.run([sys.executable, str(HOOKS / "pretool-aggregate-check.py")], input=_qa_payload(),
                          text=True, capture_output=True, env=env, cwd=str(project), timeout=120)


def test_the_qa_dispatch_check_rebuilds_a_stale_aggregate_before_it_judges(project):
    gate = _qa_dispatch(project)  # no canonical yet: the check builds it, and it names both lanes
    assert (gate.returncode, gate.stderr) == (0, "")
    stale = json.loads(_canonical(project).read_text())
    stale["parallel_workers"] = ["l1"]  # what an aggregate built before l2 reported would say
    _canonical(project).write_text(json.dumps(stale))
    _shell_write(project, "l2")
    gate = _qa_dispatch(project)
    assert (gate.returncode, gate.stderr) == (0, "")
    assert sorted(json.loads(_canonical(project).read_text())["parallel_workers"]) == LANES


def test_a_cut_off_rebuild_leaves_the_aggregate_stale_and_the_qa_dispatch_check_judges_nothing_in_it(project):
    assert _qa_dispatch(project).returncode == 0
    old = json.loads(_canonical(project).read_text())
    old["parallel_workers"] = ["l1"]
    _canonical(project).write_text(json.dumps(old))
    before = _canonical(project).read_bytes()
    lane = _shell_write(project, "l2")
    sys.path.insert(0, str(HOOKS))
    try:
        from lib import aggregate_rebuild
        agg = aggregate_rebuild.aggregator()
        assert agg.rebuild_if_stale(project, TID, timeout=0.001) == [str(lane)]  # cut off
    finally:
        sys.path.remove(str(HOOKS))
    assert _canonical(project).read_bytes() == before
    gate = subprocess.run(
        [sys.executable, "-c", "import os,runpy,sys; sys.path.insert(0, sys.argv[1]); "
         "from lib import aggregate_rebuild as a; a.QA_DISPATCH_TIMEOUT_S = 0.001; "
         "sys.argv = sys.argv[2:]; runpy.run_path(sys.argv[0], run_name='__main__')",
         str(HOOKS), str(HOOKS / "pretool-aggregate-check.py")],
        input=_qa_payload(), text=True, capture_output=True, cwd=str(project), timeout=120,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(project), "CLAUDE_OBLIGATION_BARRIER": "block"})
    assert gate.returncode == 2, gate.stderr
    assert f"[stale_canonical] {_canonical(project)}: older than lane report(s) {lane.name}" in gate.stderr
    assert "parallel_workers" not in gate.stderr  # nothing in the stale aggregate is judged
    assert _canonical(project).read_bytes() == before


def _qa_payload():
    block = json.dumps({
        "task_id": f"{TID}-l1", "role": "qa", "pipeline": "dev", "profile": "final_verification",
        "dispatched_at": "2026-01-01T12:00:00Z",
        "artifacts": [{"kind": "json", "path": f"docs/dev/qa-report-{TID}-l1.json",
                       "schema": "qa-report.v2", "identity": {"task_id": f"{TID}-l1"}}]})
    return json.dumps({"tool_name": "Agent", "agent_id": "qa-dispatch-test",
                       "tool_input": {"subagent_type": "qa", "prompt": f'<obligation v="1">{block}</obligation>'}})


def _bad_l1(project):
    """Lane l1's report carries prose where its `git status --porcelain` belongs: the aggregator refuses it."""
    path = _dev(project) / f"dev-report-{TID}-l1.json"
    path.write_text(json.dumps({**_report("l1"), "baseline_dirty_snapshot": "see the lane write manifest"}))
    return path


def test_a_siblings_bad_report_is_named_at_the_qa_dispatch_and_at_the_main_agents_stop(project):
    """The lane whose report is good is not held for l1's (hooks/tests/test_artifact_contract_enforce.py
    test_c5_a_lane_stops_cleanly_while_its_siblings_report_is_bad); the fault reaches the main agent here."""
    _bad_l1(project)
    gate = _qa_dispatch(project)
    assert gate.returncode == 2, gate.stderr
    assert "canonical_missing" in gate.stderr and "shard 'l1': baseline_dirty_snapshot" in gate.stderr
    assert "(lane l1)" in gate.stderr  # the route: the lane whose report it is
    assert not _canonical(project).exists()
    stop_gate = _load("hooks/stop-command-gate.py", "stop_gate_sibling_fault")
    gaps = stop_gate.disposition(project, TID, "dev")
    assert any(f"artifact=docs/dev/dev-report-{TID}.json problem=stale_canonical" in g
               and f"dev-report-{TID}-l1.json" in g for g in gaps), gaps
