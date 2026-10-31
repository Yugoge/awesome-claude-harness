"""hooks/posttool-overnight-trace.py: a trace record's evidence_completeness
(P1b E3). Which report is inspected and which of its fields are required is
what the Agent call's own obligation declares (its json artifact and that
artifact's schema), not a table from agent types to field names: the same
dispatch type counts the fields its declared schema requires, and a dispatch
that declares no json report has none.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "posttool-overnight-trace.py"
SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"
SID = "sess-trace-evidence"
TS = "20261028-120000"


def _project(tmp_path: Path) -> Path:
    (tmp_path / ".claude").mkdir()
    end = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / ".claude" / f"overnight-state-{SID}.json").write_text(json.dumps(
        {"session_id": SID, "end_time": end, "current_phase": "exploring", "worktree_path": str(tmp_path)}))
    contract = tmp_path / "docs" / "dev" / "overnight" / SID / "cycle-1" / "cycle-contract.json"
    contract.parent.mkdir(parents=True)
    contract.write_text(json.dumps({"cycle_id": 1, "required_calls": []}))
    return contract.parent


def _trace(tmp_path: Path, subagent_type: str, prompt: str) -> dict:
    payload = {"session_id": SID, "tool_name": "Agent",
               "tool_input": {"subagent_type": subagent_type, "prompt": prompt},
               "tool_response": {"output": "done"}}
    run = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                         text=True, timeout=60, cwd=tmp_path,
                         env={**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path),
                              "SPECIALIST_YIELD_LOG_PATH": str(tmp_path / "yield.jsonl"),
                              "PYTHONDONTWRITEBYTECODE": "1"})
    assert run.returncode == 0, run.stderr
    lines = (tmp_path / "docs/dev/overnight" / SID / "cycle-1" / "trace.jsonl").read_text().splitlines()
    return json.loads(lines[-1])["evidence_completeness"]


def _obligation(role: str, path: str, schema: str) -> str:
    doc = {"task_id": TS, "lane": None, "lane_set": None, "role": role, "pipeline": "dev-overnight",
           "profile": "overnight", "dispatched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "artifacts": [{"kind": "json", "path": path, "schema": schema, "identity": {"task_id": TS}}]}
    return f'<obligation v="1">{json.dumps(doc)}</obligation>'


def test_the_declared_report_and_its_schema_decide_the_required_fields(tmp_path):
    _project(tmp_path)
    required = json.loads((SCHEMAS / "dev-report.v2.json").read_text())["required"]
    report = f"docs/dev/dev-report-{TS}.json"
    (tmp_path / report).write_text(json.dumps({required[0]: "x"}))
    evidence = _trace(tmp_path, "dev", _obligation("dev", report, "dev-report.v2"))
    assert evidence["required_count"] == len(required)
    assert evidence["present_count"] == 1
    assert evidence["missing_fields"] == required[1:]


def test_no_declared_report_counts_no_fields(tmp_path):
    _project(tmp_path)
    evidence = _trace(tmp_path, "dev", "no obligation in this prompt")
    assert (evidence["required_count"], evidence["present_count"]) == (0, None)
