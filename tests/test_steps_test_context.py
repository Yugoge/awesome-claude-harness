"""scripts/steps/test-context.py: Steps 7, 10 and 11 of /test (validation context, execution context, checkpoint).

The contexts must keep the shape the two agents document as their Input Format; the shape cases read that
block from agents/test-validator.md and agents/test-executor.md, so a change to either side shows here.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "steps" / "test-context.py"
RID = "test-20261109-120000"
TS = "2026-11-09T12:00:00Z"
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def run(project: Path, *args: str) -> tuple[dict[str, str], subprocess.CompletedProcess]:
    home = project.parent / (project.name + "-home")
    home.mkdir(exist_ok=True)
    env = {**os.environ, **GIT_ENV, "HOME": str(home)}
    proc = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=project, env=env, text=True,
                          capture_output=True, stdin=subprocess.DEVNULL)
    facts = {}
    for line in proc.stdout.splitlines():
        key, sep, value = line.partition("=")
        assert sep and re.fullmatch(r"[a-z_]+", key), f"stdout carries a line that is not key=value: {line!r}"
        facts[key] = value
    return facts, proc


def git(project: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=project, check=True, capture_output=True, text=True,
                         env={**os.environ, **GIT_ENV})
    return out.stdout.strip()


def project_with_registry(tmp_path: Path, name: str = "proj") -> Path:
    proj = tmp_path / name
    (proj / "tests" / "reports").mkdir(parents=True)
    registry = {"validators": [
        {"type": "script", "path": "tests/scripts/validate-venv-usage.py", "name": "validate-venv-usage",
         "edge_case": "EC002", "priority": "critical", "description": "Venv usage violations"},
        {"type": "instruction", "path": "tests/instructions/claude-md-protection.md", "name": "claude-md-protection",
         "edge_case": "EC001", "priority": "high", "description": "CLAUDE.md protection"},
    ]}
    (proj / "tests" / "reports" / f"validator-registry-{RID}.json").write_text(json.dumps(registry))
    return proj


def write_report(proj: Path, document: dict) -> None:
    (proj / "tests" / "reports" / f"validation-report-{RID}.json").write_text(json.dumps(document))


def load(proj: Path, kind: str) -> dict:
    return json.loads((proj / "tests" / "reports" / f"{kind}-context-{RID}.json").read_text())


def agent_input_format(agent: str) -> dict:
    """The JSON block under '## Input Format' of an agent file."""
    text = (ROOT / "agents" / agent).read_text(encoding="utf-8")
    section = text[text.index("## Input Format"):]
    return json.loads(re.search(r"```json\n(.*?)```", section, re.S).group(1))


def shape(value):
    if isinstance(value, dict):
        return {key: shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    return "value"


# ------------------------------------------------------------------ Step 7: validation
def test_validation_context_has_the_documented_shape_and_the_registry_validators(tmp_path):
    proj = project_with_registry(tmp_path)
    facts, proc = run(proj, "validation", "--request-id", RID, "--timestamp", TS)
    assert proc.returncode == 0
    assert facts == {"status": "ok", "context": f"tests/reports/validation-context-{RID}.json", "validators": "2"}
    context = load(proj, "validation")
    documented = agent_input_format("test-validator.md")
    assert shape(context) == shape(documented)
    assert context["orchestrator"] == documented["orchestrator"]
    assert context["validation_criteria"] == documented["validation_criteria"]
    assert context["request_id"] == RID and context["timestamp"] == TS
    assert context["context"]["project_root"] == str(proj.resolve())
    assert context["context"]["test_directory"] == str(proj.resolve() / "tests")
    assert context["context"]["venv_path"] == str(ROOT / "venv")
    assert context["context"]["validators"] == [
        {"type": "script", "path": "tests/scripts/validate-venv-usage.py", "edge_case": "EC002", "priority": "critical"},
        {"type": "instruction", "path": "tests/instructions/claude-md-protection.md", "edge_case": "EC001",
         "priority": "high"},
    ]


def test_validation_context_without_the_registry_is_a_fact_and_writes_nothing(tmp_path):
    proj = tmp_path / "proj"
    (proj / "tests" / "reports").mkdir(parents=True)
    facts, proc = run(proj, "validation", "--request-id", RID)
    assert proc.returncode == 0 and facts == {"status": "missing_registry"}
    assert list((proj / "tests" / "reports").iterdir()) == []


def test_a_damaged_registry_counts_as_missing(tmp_path):
    proj = project_with_registry(tmp_path)
    (proj / "tests" / "reports" / f"validator-registry-{RID}.json").write_text("{not json")
    facts, _ = run(proj, "validation", "--request-id", RID)
    assert facts == {"status": "missing_registry"}


def test_the_timestamp_defaults_to_now_in_iso_8601(tmp_path):
    proj = project_with_registry(tmp_path)
    run(proj, "validation", "--request-id", RID)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", load(proj, "validation")["timestamp"])


# ------------------------------------------------------------------ Step 10: execution
def test_execution_context_has_the_documented_shape(tmp_path):
    proj = project_with_registry(tmp_path)
    write_report(proj, {"request_id": RID, "validator": {"status": "pass", "validators_checked": 2}})
    facts, proc = run(proj, "execution", "--request-id", RID, "--timestamp", TS)
    assert proc.returncode == 0
    assert facts == {"status": "ok", "context": f"tests/reports/execution-context-{RID}.json", "validators": "2",
                     "validation_status": "pass"}
    context = load(proj, "execution")
    documented = agent_input_format("test-executor.md")
    assert shape({**context, "context": {**context["context"], "checkpoint_commit": "x"}}) == shape(documented)
    assert context["orchestrator"] == documented["orchestrator"]
    assert context["parameters"] == {"fail_fast": False, "verbose": True,
                                     "report_path": f"tests/reports/execution-report-{RID}.json"}
    assert context["validation_report"] == {"status": "pass", "validators_checked": 2, "all_valid": True}
    assert "checkpoint_commit" not in context["context"]
    assert context["context"]["validators"][0]["edge_case"] == "EC002"


def test_execution_context_reads_a_top_level_report_and_a_failed_status(tmp_path):
    proj = project_with_registry(tmp_path)
    write_report(proj, {"status": "fail", "validators_checked": 2})
    facts, _ = run(proj, "execution", "--request-id", RID)
    assert facts["validation_status"] == "fail"
    assert load(proj, "execution")["validation_report"] == {"status": "fail", "validators_checked": 2, "all_valid": False}


def test_execution_context_without_a_validation_report_or_registry_is_a_fact(tmp_path):
    proj = project_with_registry(tmp_path)
    facts, proc = run(proj, "execution", "--request-id", RID)
    assert proc.returncode == 0 and facts == {"status": "missing_validation_report"}
    write_report(proj, {"unrelated": True})
    assert run(proj, "execution", "--request-id", RID)[0] == {"status": "missing_validation_report"}
    assert not (proj / "tests" / "reports" / f"execution-context-{RID}.json").exists()
    empty = tmp_path / "empty"
    empty.mkdir()
    assert run(empty, "execution", "--request-id", RID)[0] == {"status": "missing_registry"}


# ------------------------------------------------------------------ Step 11: checkpoint
def repo_with_context(tmp_path: Path, branch: str = "main") -> Path:
    proj = project_with_registry(tmp_path)
    git(proj, "init", "-q", "-b", branch, ".")
    git(proj, "commit", "-q", "--allow-empty", "-m", "base")
    write_report(proj, {"validator": {"status": "pass", "validators_checked": 2}})
    run(proj, "execution", "--request-id", RID)
    (proj / "work.txt").write_text("changed\n")
    return proj


def test_checkpoint_records_the_commit_of_the_checkpoint_ref_in_the_execution_context(tmp_path):
    proj = repo_with_context(tmp_path)
    facts, proc = run(proj, "checkpoint", "--request-id", RID)
    assert proc.returncode == 0
    commit = git(proj, "rev-parse", "refs/checkpoints/main")
    assert facts == {"checkpoint_exit": "0", "checkpoint_ref": "refs/checkpoints/main", "checkpoint_commit": commit,
                     "rollback_file": "git checkout refs/checkpoints/main -- <path>",
                     "rollback_tree": "git reset --hard refs/checkpoints/main", "context": "ok"}
    context = load(proj, "execution")
    assert context["context"]["checkpoint_commit"] == commit
    assert shape(context) == shape(agent_input_format("test-executor.md"))
    assert git(proj, "rev-parse", "HEAD") != commit, "the checkpoint never moves HEAD"
    assert not list((proj / "tests" / "reports").glob("*.tmp"))


def test_checkpoint_ref_for_a_branch_with_a_slash_is_the_one_the_library_writes(tmp_path):
    proj = repo_with_context(tmp_path, "feature/x")
    facts, _ = run(proj, "checkpoint", "--request-id", RID)
    assert facts["checkpoint_ref"] == "refs/checkpoints/feature-x"
    assert facts["checkpoint_commit"] == git(proj, "rev-parse", "refs/checkpoints/feature-x")
    assert load(proj, "execution")["context"]["checkpoint_commit"] == facts["checkpoint_commit"]


def test_checkpoint_on_a_detached_head_uses_the_detached_ref(tmp_path):
    proj = repo_with_context(tmp_path)
    git(proj, "checkout", "-q", "--detach")
    short = git(proj, "rev-parse", "--short", "HEAD")
    facts, _ = run(proj, "checkpoint", "--request-id", RID)
    assert facts["checkpoint_ref"] == f"refs/checkpoints/detached-{short}"
    assert facts["checkpoint_commit"] == git(proj, "rev-parse", facts["checkpoint_ref"])


def test_checkpoint_with_nothing_to_snapshot_records_none_and_still_exits_zero(tmp_path):
    proj = project_with_registry(tmp_path)
    git(proj, "init", "-q", "-b", "main", ".")
    (proj / ".gitignore").write_text("*\n")
    git(proj, "add", "-f", ".gitignore")
    git(proj, "commit", "-q", "-m", "base")
    write_report(proj, {"validator": {"status": "pass", "validators_checked": 2}})
    run(proj, "execution", "--request-id", RID)
    facts, proc = run(proj, "checkpoint", "--request-id", RID)
    assert proc.returncode == 0 and facts["checkpoint_exit"] == "0"
    assert facts["checkpoint_commit"] == "none" and load(proj, "execution")["context"]["checkpoint_commit"] == "none"


def test_checkpoint_without_an_execution_context_still_takes_the_snapshot(tmp_path):
    proj = repo_with_context(tmp_path)
    (proj / "tests" / "reports" / f"execution-context-{RID}.json").unlink()
    facts, proc = run(proj, "checkpoint", "--request-id", RID)
    assert proc.returncode == 0 and facts["context"] == "missing"
    assert facts["checkpoint_commit"] == git(proj, "rev-parse", "refs/checkpoints/main")


def test_checkpoint_outside_a_git_repository_is_a_fact_not_a_failure(tmp_path):
    proj = project_with_registry(tmp_path)
    write_report(proj, {"validator": {"status": "pass", "validators_checked": 2}})
    run(proj, "execution", "--request-id", RID)
    facts, proc = run(proj, "checkpoint", "--request-id", RID)
    assert proc.returncode == 0
    assert facts["checkpoint_commit"] == "none" and facts["context"] == "ok"
    assert load(proj, "execution")["context"]["checkpoint_commit"] == "none"


# ------------------------------------------------------------------ usage
def test_a_request_id_is_required(tmp_path):
    proc = subprocess.run([sys.executable, str(SCRIPT), "validation"], cwd=tmp_path, text=True, capture_output=True)
    assert proc.returncode == 2 and proc.stdout == ""
