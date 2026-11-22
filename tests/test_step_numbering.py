"""Standing check: every step of every command in the harness's own commands/ folder has an integer
number (agents/style-inspector.md rule 4, integer-step-numbering): no decimal (Step 1.1) and no
lettered (Step 4a) step, in a heading or in a reference to one. The validator is
tests/scripts/validate-step-numbering.py; each command file is its own case.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("validate_step_numbering",
                                               REPO / "tests" / "scripts" / "validate-step-numbering.py")
validator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validator)


@pytest.mark.parametrize("name", sorted(p.name for p in (REPO / "commands").glob("*.md")))
def test_a_command_numbers_its_steps_with_integers(name):
    found = [v for v in validator.validate(REPO)["violations"] if v["file"] == f"commands/{name}"]
    assert found == [], "\n".join(f'{v["file"]}:{v["line"]}: {v["pattern"]}' for v in found)


@pytest.mark.parametrize("line", ["### Step 4a: Panel QA", "As `/dev` Step 10A says", "Steps 3.5 and 4"])
def test_the_validator_refuses_a_lettered_or_decimal_step(tmp_path, line):
    (tmp_path / "commands").mkdir()
    (tmp_path / "commands" / "x.md").write_text(f"### Step 4: Fine\n\n{line}\n", encoding="utf-8")
    result = validator.validate(tmp_path)
    assert result["status"] == "fail" and [v["line"] for v in result["violations"]] == [3]
