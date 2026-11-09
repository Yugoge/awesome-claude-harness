"""commands/commit.md Step 8's selection trace, through scripts/step7-spec-update.py (P4 R5, R6):
COMMIT_STEP8_TRACE=1 emits the STEP8_* markers on stderr, and stage 4's unlinked spec is printed
and dispatches nothing (exit 0, no dispatch marker)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "step7-spec-update.py"
TASK = "20260101-000000"


def _run(docs: Path, *args: str, trace: bool = True) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("COMMIT_STEP")}
    if trace:
        env["COMMIT_STEP8_TRACE"] = "1"
    return subprocess.run([sys.executable, str(SCRIPT), "--task-id", TASK, "--dev-docs-root", str(docs), *args],
                          capture_output=True, text=True, env=env)


def _docs(tmp_path: Path) -> Path:
    docs = tmp_path / "docs" / "dev"
    docs.mkdir(parents=True)
    (docs / f"close-report-{TASK}.md").write_text("# Close\n\nCLOSE: YES\n", encoding="utf-8")
    return docs


def test_skip_branches_emit_step8_markers(tmp_path: Path) -> None:
    docs = _docs(tmp_path)
    for args, marker in ((("--bulk", "true"), "STEP8_SKIPPED: bulk=true"),
                         (("--dryrun", "true"), "STEP8_SKIPPED: dryrun=true"),
                         (("--changelog-status", "failed"), "STEP8_SKIPPED: changelog_no_real_commit")):
        proc = _run(docs, *args)
        assert proc.returncode == 0 and proc.stderr.strip() == marker, (args, proc.stderr)


def test_stage1_and_no_spec_markers(tmp_path: Path) -> None:
    docs = _docs(tmp_path)
    proc = _run(docs)
    assert proc.returncode == 0 and f"STEP8_NO_SPEC: task-id={TASK}" in proc.stderr
    spec = docs / "specs" / "spec-20260101-000000.md"
    spec.parent.mkdir()
    spec.write_text("# spec\n", encoding="utf-8")
    (docs / f"context-{TASK}.json").write_text('{"spec_path": "%s"}' % spec, encoding="utf-8")
    proc = _run(docs)
    assert f"STEP8_SPEC_UPDATE_DISPATCHED: task-id={TASK} stage=1 spec_path={spec}" in proc.stderr
    assert all(line.startswith("STEP8_") for line in proc.stderr.splitlines() if line.startswith("STEP"))


def test_stage4_unlinked_spec_prints_and_dispatches_nothing(tmp_path: Path) -> None:
    docs = _docs(tmp_path)
    spec = docs / "specs" / "spec-20260101-000001.md"
    spec.parent.mkdir()
    spec.write_text(f"<!-- spec-continuation-of: {TASK} -->\n", encoding="utf-8")
    proc = _run(docs)
    assert proc.returncode == 0
    assert f"STEP8_UNLINKED_SPEC: task-id={TASK} count=1 paths={spec}" in proc.stderr
    assert "spec produced this cycle but not linked in context" in proc.stderr
    assert "DISPATCHED" not in proc.stderr and "dispatch" not in proc.stdout.lower()
