"""hooks/posttool-overnight-trace.py: which dispatches have their yield recorded
(P1b row 18).

A specialist is whatever dispatch's own obligation declares a specialist
report (schemas/specialist-report.v1.json; /dev-overnight Step 3's template),
not a role list in the hook: such a dispatch's report is classified and its
yield logged under the dispatch's type, every other dispatch only traced.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "posttool-overnight-trace.py"
SID = "sess-trace-yield"
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


def _obligation(role: str, schema: str) -> str:
    doc = {"task_id": TS, "lane": None, "lane_set": None, "role": role, "pipeline": "dev-overnight",
           "profile": "overnight", "dispatched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "artifacts": [{"kind": "json", "path": f"docs/dev/overnight/{SID}/{role}-report.json",
                          "schema": schema, "identity": {"task_id": TS}}]}
    return f'<obligation v="1">{json.dumps(doc)}</obligation>'


def _dispatch(tmp_path: Path, subagent_type: str, prompt: str) -> Path:
    report = f"docs/dev/overnight/{SID}/{subagent_type}-report.json"
    (tmp_path / report).write_text(json.dumps({"findings": [], "verdict": "pass"}))
    log = tmp_path / "yield.jsonl"
    payload = {"session_id": SID, "tool_name": "Agent",
               "tool_input": {"subagent_type": subagent_type, "prompt": prompt},
               "tool_response": {"output": f"Report written to {tmp_path / report}"}}
    run = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                         text=True, timeout=60, cwd=tmp_path,
                         env={**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path),
                              "SPECIALIST_YIELD_LOG_PATH": str(log),
                              "SPECIALIST_YIELD_POLICY_PATH": str(tmp_path / "absent-policy.json"),
                              "PYTHONDONTWRITEBYTECODE": "1"})
    assert run.returncode == 0, run.stderr
    return log


@pytest.mark.parametrize("subagent_type", ["architect", "ui-specialist", "user", "product-owner"])
def test_a_dispatch_declaring_a_specialist_report_records_its_yield(tmp_path, subagent_type):
    cycle = _project(tmp_path)
    log = _dispatch(tmp_path, subagent_type, _obligation(subagent_type, "specialist-report.v1"))
    records = [json.loads(line) for line in log.read_text().splitlines()]
    assert [r["specialist_type"] for r in records] == [subagent_type]
    assert (cycle / "trace.jsonl").is_file()


@pytest.mark.parametrize("subagent_type,prompt", [
    ("architect", "Provide your observations; no obligation"),
    ("pm", _obligation("pm", "triage-report.v1")),
    ("qa", _obligation("qa", "qa-report.v2")),
])
def test_any_other_dispatch_is_only_traced(tmp_path, subagent_type, prompt):
    cycle = _project(tmp_path)
    log = _dispatch(tmp_path, subagent_type, prompt)
    assert not log.exists()
    assert [json.loads(line)["agent_type"] for line in (cycle / "trace.jsonl").read_text().splitlines()] \
        == [subagent_type]
