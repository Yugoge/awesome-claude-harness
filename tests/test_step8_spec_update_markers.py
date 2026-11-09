"""commands/commit.md Step 8's selection trace, through scripts/step7-spec-update.py (P4 R5, R6):
COMMIT_STEP8_TRACE=1 emits the STEP8_* markers on stderr, and stage 4's unlinked spec is printed
and dispatches nothing (exit 0, no dispatch marker). The script is the tested reference of the
selection the text orders: the text's markers and continuation pattern are the script's, and Step 8
makes the selection itself, with no call of the script."""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "step7-spec-update.py"
COMMIT_MD = ROOT / "commands" / "commit.md"
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


def _step8_text() -> str:
    text = COMMIT_MD.read_text(encoding="utf-8")
    start = text.index("### Step 8:")
    return text[start:text.index("\n## ", start)]


def test_the_text_names_the_markers_the_script_emits() -> None:
    source, step = SCRIPT.read_text(encoding="utf-8"), re.sub(r"\s+", " ", _step8_text())
    emitted = set(re.findall(r"STEP8_[A-Z_]+:", source))
    assert emitted and set(re.findall(r"STEP8_[A-Z_]+:", step)) == emitted
    skips = set(re.findall(r'STEP8_SKIPPED: (\w+)', source))
    assert skips and set(re.findall(r"STEP8_SKIPPED: (\w+)", step)) == skips


def test_the_text_orders_the_scripts_continuation_pattern_and_window() -> None:
    spec = importlib.util.spec_from_file_location("step7_spec_update", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    step = re.sub(r"\s+", " ", _step8_text())
    assert re.search(r"match each line against ``(.+?)`` \(", step).group(1) == module.CONTINUATION_RE.pattern
    assert "modified between 24 hours before and 1 hour after the close report's modification time" in step
    assert "`<!-- spec-continuation-of: <TASK_ID> -->`" in step


def test_step8_makes_the_selection_itself_and_runs_no_script() -> None:
    """A script run from Step 8 reads the close report as a second decider of it, which the artifact check
    (tests/artifact_graph/, rules 4 and 6) refuses: the four stages are the orchestrator's own reads."""
    step = _step8_text()
    assert len(re.findall(r"^[1-4]\. \*\*", step, re.M)) == 4
    assert "```bash" not in step and "python3" not in step
    assert "it is not a call of this step" in re.sub(r"\s+", " ", step)

