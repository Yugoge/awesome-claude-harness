"""scripts/steps/test-validators.py: Steps 5-6 of /test (structure check, validator discovery).

Step 5 used to end the command with `exit 1` on a missing folder or an empty validator set; the cases here pin
that both are facts with exit 0, and that the repair the command names (test-prepare.py init --full, then
creating validators) leads out of each state.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "steps" / "test-validators.py"
PREPARE = ROOT / "scripts" / "steps" / "test-prepare.py"


def run(project: Path, *args: str, script: Path = SCRIPT) -> tuple[dict[str, str], subprocess.CompletedProcess]:
    env = {**os.environ, "HOME": str(project.parent)}
    proc = subprocess.run([sys.executable, str(script), *args], cwd=project, env=env, text=True,
                          capture_output=True, stdin=subprocess.DEVNULL)
    facts = {}
    for line in proc.stdout.splitlines():
        key, sep, value = line.partition("=")
        assert sep and re.fullmatch(r"[a-z_]+", key), f"stdout carries a line that is not key=value: {line!r}"
        facts[key] = value
    return facts, proc


def write(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def structure(project: Path) -> None:
    (project / "tests" / "scripts").mkdir(parents=True)
    (project / "tests" / "reports").mkdir(parents=True)


# ------------------------------------------------------------------ Step 5: check
def test_an_empty_project_is_structure_incomplete_with_exit_zero(tmp_path):
    facts, proc = run(tmp_path, "check")
    assert proc.returncode == 0
    assert facts == {"status": "structure_incomplete", "missing": "tests/scripts,tests/reports",
                     "script_validators": "0", "instruction_validators": "0", "total_validators": "0"}


def test_one_missing_folder_is_named(tmp_path):
    (tmp_path / "tests" / "scripts").mkdir(parents=True)
    facts, proc = run(tmp_path, "check")
    assert proc.returncode == 0 and facts["status"] == "structure_incomplete" and facts["missing"] == "tests/reports"
    other = tmp_path / "other"
    (other / "tests" / "reports").mkdir(parents=True)
    facts, _ = run(other, "check")
    assert facts["missing"] == "tests/scripts"


def test_a_complete_structure_without_validators_is_no_validators_with_exit_zero(tmp_path):
    structure(tmp_path)
    write(tmp_path / "tests" / "instructions" / "validation-guide.md", "guide\n")
    write(tmp_path / "tests" / "instructions" / "guide.md", "guide\n")
    write(tmp_path / "tests" / "scripts" / "helper.py", "x\n")
    write(tmp_path / "tests" / "scripts" / "validate-notpy.sh", "x\n")
    facts, proc = run(tmp_path, "check")
    assert proc.returncode == 0
    assert facts == {"status": "no_validators", "missing": "none", "script_validators": "0",
                     "instruction_validators": "0", "total_validators": "0"}


def test_validators_are_counted_in_subfolders_and_guides_are_left_out(tmp_path):
    structure(tmp_path)
    write(tmp_path / "tests" / "scripts" / "validate-a.py")
    write(tmp_path / "tests" / "scripts" / "nested" / "validate-b.py")
    write(tmp_path / "tests" / "instructions" / "claude-md-protection.md")
    write(tmp_path / "tests" / "instructions" / "execution-guide.md")
    (tmp_path / "tests" / "scripts" / "validate-dir.py").mkdir()
    facts, proc = run(tmp_path, "check")
    assert proc.returncode == 0
    assert facts == {"status": "ok", "missing": "none", "script_validators": "2",
                     "instruction_validators": "1", "total_validators": "3"}


def test_the_named_repairs_lead_out_of_both_states(tmp_path):
    """structure_incomplete -> test-prepare.py init --full -> no_validators -> a validator is created -> ok."""
    write(tmp_path / "tests" / "test_app.py", "def test_ok(): pass\n")
    facts, _ = run(tmp_path, "check")
    assert facts["status"] == "structure_incomplete"
    _, repaired = run(tmp_path, "init", "--full", script=PREPARE)
    assert repaired.returncode == 0
    facts, _ = run(tmp_path, "check")
    assert facts["status"] == "no_validators" and facts["total_validators"] == "0"
    write(tmp_path / "tests" / "scripts" / "validate-new.py", '"""Edge Case: EC001"""\n')
    facts, _ = run(tmp_path, "check")
    assert facts["status"] == "ok" and facts["total_validators"] == "1"


def test_check_changes_nothing_on_disk(tmp_path):
    run(tmp_path, "check")
    assert list(tmp_path.iterdir()) == []


# ------------------------------------------------------------------ Step 6: discover
def registry(project: Path, request_id: str = "test-20261109-120000") -> dict:
    return json.loads((project / "tests" / "reports" / f"validator-registry-{request_id}.json").read_text())


def test_discover_writes_the_registry_with_the_metadata_of_each_validator(tmp_path):
    structure(tmp_path)
    write(tmp_path / "tests" / "scripts" / "validate-venv-usage.py",
          '#!/usr/bin/env python3\n"""\nValidator: validate-venv-usage\nEdge Case: EC002\nPriority: Critical\n'
          'Purpose: Venv usage violations\n"""\n')
    write(tmp_path / "tests" / "scripts" / "validate-plain.py", "import sys\n")
    write(tmp_path / "tests" / "instructions" / "claude-md-protection.md",
          "# CLAUDE.md protection\n\n**Edge Case**: EC001\n**Priority**: high\n**Purpose**: CLAUDE.md protection\n")
    write(tmp_path / "tests" / "instructions" / "validation-guide.md", "Edge Case: EC009\n")
    facts, proc = run(tmp_path, "discover", "--request-id", "test-20261109-120000")
    assert proc.returncode == 0
    assert facts == {"registry": "tests/reports/validator-registry-test-20261109-120000.json", "validators": "3",
                     "script_validators": "2", "instruction_validators": "1"}
    assert registry(tmp_path)["validators"] == [
        {"type": "script", "path": "tests/scripts/validate-plain.py", "name": "validate-plain",
         "edge_case": "", "priority": "medium", "description": ""},
        {"type": "script", "path": "tests/scripts/validate-venv-usage.py", "name": "validate-venv-usage",
         "edge_case": "EC002", "priority": "critical", "description": "Venv usage violations"},
        {"type": "instruction", "path": "tests/instructions/claude-md-protection.md",
         "name": "claude-md-protection", "edge_case": "EC001", "priority": "high",
         "description": "CLAUDE.md protection"},
    ]


def test_discover_reads_only_the_first_twenty_lines_and_ignores_an_unknown_priority(tmp_path):
    structure(tmp_path)
    late = "\n" * 20 + "Edge Case: EC007\nPriority: critical\nPurpose: too late\n"
    write(tmp_path / "tests" / "scripts" / "validate-late.py", late)
    write(tmp_path / "tests" / "scripts" / "validate-odd.py", "Edge Case: EC003 and EC004\nPriority: urgent\n")
    run(tmp_path, "discover", "--request-id", "r1")
    by_name = {v["name"]: v for v in registry(tmp_path, "r1")["validators"]}
    assert by_name["validate-late"] == {"type": "script", "path": "tests/scripts/validate-late.py",
                                        "name": "validate-late", "edge_case": "", "priority": "medium", "description": ""}
    assert by_name["validate-odd"]["edge_case"] == "EC003" and by_name["validate-odd"]["priority"] == "medium"


def test_discover_with_no_validators_writes_an_empty_registry_and_creates_reports(tmp_path):
    facts, proc = run(tmp_path, "discover", "--request-id", "r2")
    assert proc.returncode == 0 and facts["validators"] == "0"
    assert registry(tmp_path, "r2") == {"validators": []}


def test_discover_needs_a_request_id(tmp_path):
    proc = subprocess.run([sys.executable, str(SCRIPT), "discover"], cwd=tmp_path, text=True, capture_output=True)
    assert proc.returncode == 2 and proc.stdout == ""
