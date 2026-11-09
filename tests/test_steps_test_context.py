"""scripts/steps/test-context.py: Steps 7, 10 and 11 of /test (validation context, execution context, checkpoint).

The validation context keeps the shape agents/test-validator.md documents as its Input Format. The execution
context keeps the template under Step 10 of commands/test.md, which agents/test-executor.md names as the home
of its input, and holds every key that agent says it reads; the cases read those texts, so a change to either
side shows here. The validation context is printed for the validator's dispatch (no file); the validator
report's status and validators_checked are passed to the execution step as arguments (the script reads no
report file).
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


def execution(proj: Path, status: str = "pass", checked: int = 2, *more: str):
    return run(proj, "execution", "--request-id", RID, "--timestamp", TS, "--validation-status", status,
               "--validators-checked", str(checked), *more)


def load(proj: Path, kind: str) -> dict:
    return json.loads((proj / "tests" / "reports" / f"{kind}-context-{RID}.json").read_text())


def agent_input_format(agent: str) -> dict:
    """The JSON block under '## Input Format' of an agent file."""
    text = (ROOT / "agents" / agent).read_text(encoding="utf-8")
    section = text[text.index("## Input Format"):]
    return json.loads(re.search(r"```json\n(.*?)```", section, re.S).group(1))


def step10_template() -> dict:
    """The JSON template under '### Step 10' of commands/test.md: the home of the executor's input."""
    text = (ROOT / "commands" / "test.md").read_text(encoding="utf-8")
    section = text[text.index("### Step 10:"):text.index("### Step 11:")]
    return json.loads(re.search(r"```json\n(.*?)```", section, re.S).group(1))


def executor_input_section() -> str:
    """The '## Input' section of agents/test-executor.md, which lists the keys the executor reads."""
    text = (ROOT / "agents" / "test-executor.md").read_text(encoding="utf-8")
    section = text[text.index("\n## Input\n"):]
    return section[:section.index("\n## ", 1)]


def has_path(document: dict, dotted: str) -> bool:
    node = document
    for key in dotted.removesuffix("[]").split("."):
        if not isinstance(node, dict) or key not in node:
            return False
        node = node[key]
    return True


def shape(value):
    if isinstance(value, dict):
        return {key: shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return [shape(value[0])] if value else []
    return "value"


# ------------------------------------------------------------------ Step 7: validation
def printed_context(facts: dict) -> dict:
    return json.loads(facts["context"])


def test_validation_context_has_the_documented_shape_and_the_registry_validators(tmp_path):
    proj = project_with_registry(tmp_path)
    facts, proc = run(proj, "validation", "--request-id", RID, "--timestamp", TS)
    assert proc.returncode == 0
    assert list(facts) == ["status", "validators", "context"]
    assert facts["status"] == "ok" and facts["validators"] == "2"
    context = printed_context(facts)
    documented = agent_input_format("test-validator.md")
    assert shape(context) == shape(documented)
    assert "orchestrator" not in context, "the documented block has no orchestrator object"
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


def test_validation_context_is_printed_for_the_dispatch_and_writes_no_file(tmp_path):
    proj = project_with_registry(tmp_path)
    before = sorted(p.name for p in (proj / "tests" / "reports").iterdir())
    facts, proc = run(proj, "validation", "--request-id", RID, "--timestamp", TS)
    assert proc.returncode == 0 and "\n" not in facts["context"]
    assert sorted(p.name for p in (proj / "tests" / "reports").iterdir()) == before
    assert not list(proj.rglob("validation-context-*"))


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
    facts, _ = run(proj, "validation", "--request-id", RID)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", printed_context(facts)["timestamp"])


# ------------------------------------------------------------------ Step 10: execution
def test_execution_context_has_the_documented_shape(tmp_path):
    proj = project_with_registry(tmp_path)
    facts, proc = execution(proj)
    assert proc.returncode == 0
    assert facts == {"status": "ok", "context": f"tests/reports/execution-context-{RID}.json", "validators": "2",
                     "validation_status": "pass"}
    context = load(proj, "execution")
    assert shape(context) == shape(step10_template())
    assert "orchestrator" not in context
    assert context["parameters"] == {"fail_fast": False, "verbose": True,
                                     "report_path": f"tests/reports/execution-report-{RID}.json"}
    assert context["validation_report"] == {"status": "pass", "validators_checked": 2, "all_valid": True}
    assert "checkpoint_commit" not in context["context"]
    assert context["context"]["validators"][0]["edge_case"] == "EC002"


def test_the_execution_context_holds_every_key_the_executor_says_it_reads(tmp_path):
    proj = project_with_registry(tmp_path)
    execution(proj)
    context = load(proj, "execution")
    section = executor_input_section()
    keys = [token for token in re.findall(r"`([^`]+)`", section)
            if token == "request_id" or re.fullmatch(r"[a-z_]+(\.[a-z_]+)+(\[\])?", token)]
    assert len(keys) >= 8, f"the Input section lists the keys in backticks; found {keys}"
    for key in keys:
        assert has_path(context, key), f"agents/test-executor.md reads {key}, which the execution context lacks"
    for field in ("type", "path", "edge_case", "priority"):
        assert f"`{field}`" in section
        assert all(field in validator for validator in context["context"]["validators"])
    assert "commands/test.md" in section, "the agent must keep naming the command as the home of its input"


def test_no_path_in_test_md_ends_in_a_placeholder():
    """hooks/lib/declared_paths reads every "path" in the command files as a path a dispatch may declare. A value
    that ends in a placeholder and a suffix ("tests/scripts/<name>.py") makes every target with that suffix
    declarable, so every such write reads the session transcript (hooks/tests/test_tool_policy_derived_permission.py).
    The Step 10 template therefore names its validator path in full, as the base template did."""
    text = (ROOT / "commands" / "test.md").read_text(encoding="utf-8")
    values = re.findall(r'"path"\s*:\s*"([^"]*)"', text)
    assert values, "the Step 10 template carries a validator path"
    for value in values:
        assert not re.search(r"[<{][^<>{}]*[>}][^/]*$", value), f'"path": "{value}" ends in a placeholder'


def test_execution_context_takes_the_passed_status_and_a_failed_status_is_not_all_valid(tmp_path):
    proj = project_with_registry(tmp_path)
    facts, _ = execution(proj, "fail", 7)
    assert facts["validation_status"] == "fail"
    assert load(proj, "execution")["validation_report"] == {"status": "fail", "validators_checked": 7, "all_valid": False}


def test_execution_context_reads_no_report_file(tmp_path):
    """The passed values are the only source: a report on disk that says otherwise is not read."""
    proj = project_with_registry(tmp_path)
    (proj / "tests" / "reports" / f"validation-report-{RID}.json").write_text(
        json.dumps({"validator": {"status": "fail", "validators_checked": 99}}))
    execution(proj, "pass", 2)
    assert load(proj, "execution")["validation_report"] == {"status": "pass", "validators_checked": 2, "all_valid": True}


def test_execution_context_without_the_registry_is_a_fact_and_writes_nothing(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    facts, proc = execution(empty)
    assert proc.returncode == 0 and facts == {"status": "missing_registry"}
    assert not list(empty.rglob("execution-context-*"))


def test_execution_needs_the_status_and_the_count_from_the_validation_report(tmp_path):
    proj = project_with_registry(tmp_path)
    for args in (["--validation-status", "pass"], ["--validators-checked", "2"], []):
        facts, proc = run(proj, "execution", "--request-id", RID, *args)
        assert proc.returncode == 2 and facts == {}
    proc = subprocess.run([sys.executable, str(SCRIPT), "execution", "--request-id", RID, "--validation-status",
                           "pass", "--validators-checked", "many"], cwd=proj, text=True, capture_output=True)
    assert proc.returncode == 2 and proc.stdout == ""
    assert not (proj / "tests" / "reports" / f"execution-context-{RID}.json").exists()


# ------------------------------------------------------------------ Step 11: checkpoint
def repo_with_context(tmp_path: Path, branch: str = "main") -> Path:
    proj = project_with_registry(tmp_path)
    git(proj, "init", "-q", "-b", branch, ".")
    git(proj, "commit", "-q", "--allow-empty", "-m", "base")
    execution(proj)
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
    expected = step10_template()
    expected["context"]["checkpoint_commit"] = commit
    assert shape(context) == shape(expected), "Step 11 adds context.checkpoint_commit and nothing else"
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
    execution(proj)
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
    execution(proj)
    facts, proc = run(proj, "checkpoint", "--request-id", RID)
    assert proc.returncode == 0
    assert facts["checkpoint_commit"] == "none" and facts["context"] == "ok"
    assert load(proj, "execution")["context"]["checkpoint_commit"] == "none"


# ------------------------------------------------------------------ usage
def test_a_request_id_is_required(tmp_path):
    proc = subprocess.run([sys.executable, str(SCRIPT), "validation"], cwd=tmp_path, text=True, capture_output=True)
    assert proc.returncode == 2 and proc.stdout == ""
