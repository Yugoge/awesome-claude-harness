"""scripts/steps/test-prepare.py: Steps 1-4 of /test (folder setup, edge-case analysis, migration, cleanup).

Each case runs the real script in a temporary project; nothing touches the runner's home or the network.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "steps" / "test-prepare.py"
ANALYSIS = "docs/test/edge-case-analysis.json"


def run(project: Path, *args: str) -> tuple[dict[str, str], subprocess.CompletedProcess]:
    home = project.parent / (project.name + "-home")
    home.mkdir(exist_ok=True)
    env = {**os.environ, "HOME": str(home), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    proc = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=project, env=env, text=True,
                          capture_output=True, stdin=subprocess.DEVNULL)
    facts = {}
    for line in proc.stdout.splitlines():
        key, sep, value = line.partition("=")
        assert sep and re.fullmatch(r"[a-z_]+", key), f"stdout carries a line that is not key=value: {line!r}"
        facts[key] = value
    return facts, proc


def project(tmp_path: Path, name: str = "proj") -> Path:
    path = tmp_path / name
    path.mkdir()
    return path


def git_project(tmp_path: Path) -> Path:
    path = project(tmp_path)
    for args in (["init", "-q", "."], ["commit", "-q", "--allow-empty", "-m", "fix: EC002 venv usage"]):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True,
                       env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"})
    return path


def write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ------------------------------------------------------------------ Step 1: init
def test_init_without_tests_creates_the_whole_structure_and_the_instruction_templates(tmp_path):
    proj = project(tmp_path)
    facts, proc = run(proj, "init")
    assert proc.returncode == 0
    assert re.fullmatch(r"test-\d{8}-\d{6}", facts["request_id"])
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", facts["timestamp"])
    assert facts["project_root"] == str(proj.resolve())
    assert facts["tests_dir"] == "created"
    for sub in ("scripts", "instructions", "data/fixtures", "data/mocks", "reports"):
        assert (proj / "tests" / sub).is_dir(), sub
    assert facts["created"] == ",".join(f"tests/{s}" for s in ("scripts", "instructions", "data/fixtures", "data/mocks", "reports"))
    copied = sorted(p.name for p in (proj / "tests" / "instructions").iterdir())
    assert copied == sorted(p.name for p in (ROOT / "tests" / "instructions").glob("*.md") if p.name not in ("README.md", "INDEX.md"))
    assert copied and facts["templates_copied"] == str(len(copied))
    assert not (proj / "tests" / "README.md").exists() and not (proj / "tests" / "INDEX.md").exists()


def test_init_with_an_existing_tests_folder_only_adds_reports(tmp_path):
    proj = project(tmp_path)
    write(proj / "tests" / "test_app.py", "def test_ok(): pass\n")
    facts, proc = run(proj, "init")
    assert proc.returncode == 0 and facts["tests_dir"] == "existing"
    assert facts["created"] == "tests/reports" and facts["templates_copied"] == "0"
    assert (proj / "tests" / "reports").is_dir()
    assert not (proj / "tests" / "scripts").exists() and not (proj / "tests" / "instructions").exists()
    assert (proj / "tests" / "test_app.py").read_text() == "def test_ok(): pass\n"


def test_init_full_repairs_an_incomplete_tests_folder_and_is_idempotent(tmp_path):
    proj = project(tmp_path)
    write(proj / "tests" / "test_app.py", "x\n")
    run(proj, "init")
    facts, proc = run(proj, "init", "--full")
    assert proc.returncode == 0 and facts["tests_dir"] == "existing"
    assert facts["created"] == "tests/scripts,tests/instructions,tests/data/fixtures,tests/data/mocks"
    assert int(facts["templates_copied"]) > 0
    again, _ = run(proj, "init", "--full")
    assert again["created"] == "none" and again["templates_copied"] == "0"


def test_init_full_leaves_an_existing_instructions_folder_alone(tmp_path):
    proj = project(tmp_path)
    keep = write(proj / "tests" / "instructions" / "mine.md", "mine\n")
    facts, _ = run(proj, "init", "--full")
    assert facts["templates_copied"] == "0"
    assert sorted(p.name for p in keep.parent.iterdir()) == ["mine.md"]


# ------------------------------------------------------------------ Step 2: edge-cases
def test_edge_cases_writes_the_analysis_and_reports_its_count(tmp_path):
    proj = git_project(tmp_path)
    facts, proc = run(proj, "edge-cases")
    assert proc.returncode == 0 and facts["edge_case_analysis"] == ANALYSIS
    analysis = json.loads((proj / ANALYSIS).read_text())
    assert facts["edge_cases"] == str(analysis["summary"]["total_edge_cases"])
    assert "Analyzing git history since 90.days.ago" in proc.stderr  # the analyzer's own output is on stderr


def test_edge_cases_outside_a_git_repository_is_a_fact_not_a_failure(tmp_path):
    proj = project(tmp_path)
    facts, proc = run(proj, "edge-cases")
    assert proc.returncode == 0
    assert facts["edge_case_analysis"] == "failed" and facts["edge_cases"] == "0" and facts["analyzer_exit"] == "1"
    assert "Not a git repository" in facts["analyzer_error"]
    assert not (proj / ANALYSIS).exists()


# ------------------------------------------------------------------ Step 3: migrate
def test_migrate_with_no_test_folder_is_none(tmp_path):
    proj = project(tmp_path)
    (proj / "tests").mkdir()
    facts, proc = run(proj, "migrate")
    assert proc.returncode == 0 and facts == {"migration": "none"}


def test_migrate_moves_test_into_a_new_tests_and_keeps_test(tmp_path):
    proj = project(tmp_path)
    write(proj / "test" / "scripts" / "validate-a.py", "# EC001\n")
    write(proj / "test" / "data" / "x.json", "{}\n")
    facts, proc = run(proj, "migrate")
    assert proc.returncode == 0 and facts == {"migration": "migrated"}
    assert (proj / "tests" / "scripts" / "validate-a.py").read_text() == "# EC001\n"
    assert (proj / "tests" / "data" / "x.json").is_file()
    assert (proj / "test" / "scripts" / "validate-a.py").is_file(), "test/ is never removed"


def test_migrate_runs_when_test_is_newer_and_backs_up_a_differing_file(tmp_path):
    proj = project(tmp_path)
    write(proj / "tests" / "a.txt", "tests version\n")
    write(proj / "test" / "a.txt", "test version\n")
    os.utime(proj / "tests", (1_000_000, 1_000_000))
    os.utime(proj / "test", (2_000_000, 2_000_000))
    facts, _ = run(proj, "migrate")
    assert facts == {"migration": "migrated"}
    assert (proj / "tests" / "a.txt").read_text() == "tests version\n"
    assert (proj / "tests" / "a.txt.from-test-folder").read_text() == "test version\n"


def test_migrate_with_both_folders_and_tests_newer_only_reports_it(tmp_path):
    proj = project(tmp_path)
    write(proj / "test" / "a.txt", "old\n")
    write(proj / "tests" / "b.txt", "new\n")
    os.utime(proj / "test", (1_000_000, 1_000_000))
    os.utime(proj / "tests", (2_000_000, 2_000_000))
    facts, proc = run(proj, "migrate")
    assert proc.returncode == 0 and facts == {"migration": "both_exist"}
    assert not (proj / "tests" / "a.txt").exists()


# ------------------------------------------------------------------ Step 4: cleanup
def analysis_with(proj: Path, *edge_case_ids: str) -> None:
    write(proj / ANALYSIS, json.dumps({"edge_cases": [{"edge_case_id": i} for i in edge_case_ids]}))


def test_cleanup_is_skipped_without_the_analysis_or_without_tests(tmp_path):
    proj = project(tmp_path, "a")
    (proj / "tests").mkdir()
    facts, proc = run(proj, "cleanup")
    assert proc.returncode == 0 and facts == {"cleanup": "skipped", "cleanup_reason": "no edge case analysis"}
    other = project(tmp_path, "b")
    analysis_with(other, "EC001")
    facts, proc = run(other, "cleanup")
    assert proc.returncode == 0 and facts == {"cleanup": "skipped", "cleanup_reason": "no tests folder"}


def test_cleanup_removes_only_validators_whose_edge_case_is_not_in_the_analysis(tmp_path):
    proj = project(tmp_path)
    analysis_with(proj, "EC002")
    keep = write(proj / "tests" / "scripts" / "validate-keep.py", '"""Edge Case: EC002"""\n')
    drop = write(proj / "tests" / "scripts" / "validate-drop.py", '"""Edge Case: EC009"""\n')
    anon = write(proj / "tests" / "scripts" / "validate-anon.py", '"""no id"""\n')
    keep_md = write(proj / "tests" / "instructions" / "keep.md", "# x\nEdge Case: EC002\n")
    drop_md = write(proj / "tests" / "instructions" / "drop.md", "# x\nEdge Case: EC008\n")
    guide = write(proj / "tests" / "instructions" / "validation-guide.md", "EC009\n")
    report = write(proj / "tests" / "reports" / "r.json", "{}\n")
    facts, proc = run(proj, "cleanup")
    assert proc.returncode == 0 and facts == {"cleanup": "done"}
    assert keep.exists() and anon.exists() and keep_md.exists() and guide.exists() and report.exists()
    assert not drop.exists() and not drop_md.exists()
    assert "Validators removed: 2" in proc.stderr


def test_cleanup_reports_the_helpers_failure_as_a_fact(tmp_path):
    proj = project(tmp_path)
    write(proj / ANALYSIS, "this is not json")
    (proj / "tests").mkdir()
    facts, proc = run(proj, "cleanup")
    assert proc.returncode == 0
    assert facts["cleanup"] == "failed" and int(facts["cleanup_exit"]) != 0


# ------------------------------------------------------------------ usage
def test_an_unknown_step_is_a_usage_error(tmp_path):
    proc = subprocess.run([sys.executable, str(SCRIPT), "bogus"], cwd=tmp_path, text=True, capture_output=True)
    assert proc.returncode == 2 and proc.stdout == ""
