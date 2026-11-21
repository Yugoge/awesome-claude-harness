"""The gitignore preflight decides within its budget on a dispatch citing many ignored paths.

Dev dispatches ended the PreToolUse launcher with a RuleOverrun traceback after 60 s: each
cited lane reports listing 20-34 gitignored generated tests, and for every path (twice: task and parent) the preflight asked
obligation.declaring_dispatch, which read the whole transcript store again and then built
the write set of every dispatch of the task (command_span.write_set) for a "writer" answer
the preflight discards. The preflight now asks without the writer and inside one
transcript_scan, so each transcript is read once; its decision is unchanged.
"""

import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from hooks.lib import obligation  # noqa: E402
from hooks.lib.subagent_restart import project_slug  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / "hooks" / "pretool-gitignore-preflight.py"
TASK = "20260101-120000"
LANE = TASK + "-l1"
PATHS = [f"build/{LANE}/out{i:02d}.js" for i in range(1, 6)]
REPORT = f"docs/dev/dev-report-{LANE}.json"


def _dispatch(use_id, task_id, artifacts):
    doc = {"task_id": task_id, "lane": None, "lane_set": None, "role": "dev", "pipeline": "dev",
           "profile": "singular", "dispatched_at": "2026-01-01T12:00:00Z", "artifacts": artifacts}
    prompt = "FIRST ACTION: register.\n" + obligation.serialize_obligation(doc) + "\nDo the work."
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": use_id, "name": "Agent", "input": {"subagent_type": "dev", "prompt": prompt}}]}}


@pytest.fixture
def store(tmp_path):
    """A project whose lane report lists gitignored build outputs its own dev dispatch
    wrote, and the account root holding that session."""
    project = tmp_path / "proj"
    (project / "docs" / "dev").mkdir(parents=True)
    (project / ".gitignore").write_text("build/\n")
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    (project / REPORT).write_text(json.dumps({"dev": {"files_modified": [], "files_created": PATHS}}))
    root = tmp_path / "projects"
    slug = root / project_slug(project)
    sub = slug / "s1" / "subagents"
    sub.mkdir(parents=True)
    report = {"kind": "json", "path": REPORT, "schema": "dev-report.v2", "identity": {"task_id": LANE}}
    (slug / "s1.jsonl").write_text(json.dumps(_dispatch("toolu_dev_l1", LANE, [report])) + "\n")
    writes = []
    for i, path in enumerate(PATHS):
        writes.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": f"w{i}", "name": "Write",
             "input": {"file_path": str(project / path), "content": "x = 1\n"}}]}})
        writes.append({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"w{i}", "content": "written"}]}})
    (sub / "agent-a-dev-l1.meta.json").write_text(json.dumps({"toolUseId": "toolu_dev_l1"}))
    (sub / "agent-a-dev-l1.jsonl").write_text("".join(json.dumps(r) + "\n" for r in writes))
    return project, root


def test_declaring_dispatch_without_the_writer_reads_no_write_set(store, monkeypatch):
    project, root = store
    assert obligation.declaring_dispatch(LANE, PATHS[0], project, roots=[root])["source"] == "writer"
    monkeypatch.setattr(obligation, "_writer", lambda *a: pytest.fail("the writer was sought"))
    assert obligation.declaring_dispatch(LANE, PATHS[0], project, roots=[root], writer=False) is None


def test_the_preflight_refuses_reading_each_transcript_once_and_no_write_set(store, monkeypatch):
    project, root = store
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.chdir(project)
    spec = importlib.util.spec_from_file_location("gitignore_preflight_speed", HOOK)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    ob = gate.obligation
    monkeypatch.setattr(ob, "account_project_roots", lambda: [root])
    monkeypatch.setattr(ob, "_writer", lambda *a: pytest.fail("the preflight built a write set it discards"))
    reads = []
    real = ob.dispatch_obligations
    monkeypatch.setattr(ob, "dispatch_obligations", lambda path, *a, **k: reads.append(Path(path).name)
                        or real(path, *a, **k))
    payload = {"tool_name": "Agent", "tool_input": {"subagent_type": "dev", "description": "lane l2",
                                                   "prompt": f"Upstream lane report: {REPORT}\nBuild l2.\n"}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    err = io.StringIO()
    monkeypatch.setattr(sys, "stderr", err)
    with pytest.raises(SystemExit) as stop:
        gate.main()
    assert stop.value.code == 2
    assert err.getvalue().splitlines()[0] == "BLOCKED: gitignored deliverables detected: " + ", ".join(PATHS)
    assert reads == ["s1.jsonl"], reads
