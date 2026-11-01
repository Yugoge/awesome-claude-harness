"""scripts/orchestrator.sh's /clean modes meet the files /clean writes and reads.

clean-merge-reports reads the three inspector reports of the request the Step 3 context
names and writes docs/clean/combined-report-<id>.json, the file Steps 13, 14 and 16 read.
record-checkpoint prints the checkpoint record and rewrites no file, the context it reads
included (Step 16 carries the commit into the cleaner's context).
"""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ORCHESTRATOR = Path(__file__).resolve().parents[1] / "scripts" / "orchestrator.sh"
RID = "clean-20261028-060000"

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="orchestrator.sh needs jq")


def project(tmp_path, reports=("cleanliness", "style", "prompt")):
    clean = tmp_path / "docs" / "clean"
    clean.mkdir(parents=True)
    context = clean / f"context-{RID}.json"
    context.write_text(json.dumps({"request_id": RID, "orchestrator": {
        "requirement": "inspect", "analysis": {"project_root": str(tmp_path)}}}))
    bodies = {
        "cleanliness": {"findings": {"misplaced_docs": [{}]}, "summary": {"total_issues": 1, "major": 1}},
        "style": {"violations": [{}, {}], "summary": {"violations_found": 2, "minor": 2}},
        "prompt": {"findings": [{}], "summary": {"critical": 1}},
    }
    for kind in reports:
        (clean / f"{kind}-report-{RID}.json").write_text(json.dumps(bodies[kind]))
    return context


def run(tmp_path, *args):
    return subprocess.run(["bash", str(ORCHESTRATOR), *args], capture_output=True, text=True, cwd=tmp_path,
                          timeout=60)


def test_merge_writes_the_combined_report_clean_reads(tmp_path):
    context = project(tmp_path)

    completed = run(tmp_path, "clean-merge-reports", str(context.relative_to(tmp_path)))

    assert completed.returncode == 0, completed.stderr
    combined = tmp_path / "docs" / "clean" / f"combined-report-{RID}.json"
    assert json.loads(completed.stdout)["combined_report"] == f"docs/clean/combined-report-{RID}.json"
    merged = json.loads(combined.read_text())
    assert merged["request_id"] == RID
    assert merged["prompt_report"] == {"findings": [{}], "summary": {"critical": 1}}
    assert merged["combined_summary"] == {"total_issues": 4, "critical": 1, "major": 1, "minor": 2}


@pytest.mark.parametrize("missing", ["cleanliness", "style", "prompt"])
def test_merge_requires_every_report(tmp_path, missing):
    context = project(tmp_path, [k for k in ("cleanliness", "style", "prompt") if k != missing])

    completed = run(tmp_path, "clean-merge-reports", str(context))

    assert completed.returncode == 1
    assert f"{missing}-report-{RID}.json" in completed.stderr
    assert not (tmp_path / "docs" / "clean" / f"combined-report-{RID}.json").exists()


def test_record_checkpoint_prints_the_record_and_rewrites_nothing(tmp_path):
    context = project(tmp_path)
    before = hashlib.sha256(context.read_bytes()).hexdigest()

    completed = run(tmp_path, "record-checkpoint", str(context), "abc123")

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"status": "recorded", "safety_checkpoint_created": True,
                                            "checkpoint_commit": "abc123"}
    assert hashlib.sha256(context.read_bytes()).hexdigest() == before
    assert sorted(p.name for p in context.parent.iterdir()) == sorted(
        [context.name] + [f"{k}-report-{RID}.json" for k in ("cleanliness", "style", "prompt")])
