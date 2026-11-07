"""BA's context rules that /dev's post-BA checks and test-writer gate read, as
schemas/context.v1.json carries them for G2 at BA's stop (P1b rows 4 and 5).

Each fault below is one the command text's consumer-side checks used to catch;
validate_artifact_for_obligation is the call G2 makes on the path BA's
obligation declares.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
sys.path[:] = [entry for entry in sys.path if entry != str(HOOKS)]
sys.path.insert(0, str(HOOKS))

from lib import contract_runtime as runtime  # noqa: E402


# agents/ba.md's JSON Context template, filled for a STANDARD tier.
STANDARD = {
    "request_id": "T1",
    "task_id": "T1",
    "spec_path": None,
    "requirement": {"original": "add() accepts strings", "success_criteria": ["add('1', 2) raises"]},
    "root_cause_analysis": {
        "affected_files": ["toy/__init__.py"],
        "complaint_location_keywords": ["add"],
        "located_source": "toy/__init__.py:1",
        "localization_blocked": None,
    },
    "evidence": {
        "observed": "add('1', 2) returns '12'",
        "measured": {"value": "no type guard", "location": "toy/__init__.py:1"},
        "expected": {"value": "TypeError", "source": "Python data model"},
        "gap": "missing guard",
    },
    "scope_expansion": {"search_pattern": "def add", "all_occurrences": ["toy/__init__.py:1"]},
    "reference_source": {"tier": "tier_1_external", "copy_allowed": True},
    "prior_attempts": {"triggered": False, "attempts": []},
    "development_approach": {"strategy": "type guard", "files_to_modify": ["toy/__init__.py"]},
    "complexity_tier": "STANDARD",
    "risk_level": "low",
    "test_writer_expected": True,
}

# agents/ba.md's MICRO/SMALL output contract: the contracts' fields are skipped.
MICRO = {
    "task_id": "T1",
    "requirement": "fix the typo in the README",
    "root_cause_analysis": {"affected_files": ["README.md"]},
    "development_approach": {"strategy": "edit one word"},
    "complexity_tier": "MICRO",
    "risk_level": "low",
    "test_writer_expected": False,
}


def _check(tmp_path: Path, doc: dict) -> dict:
    path = tmp_path / "docs" / "dev" / "context-T1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return runtime.validate_artifact_for_obligation(str(path), "context.v1")


def _with(doc: dict, change) -> dict:
    out = copy.deepcopy(doc)
    change(out)
    return out


@pytest.mark.parametrize("doc", [STANDARD, MICRO], ids=["standard", "micro"])
def test_compliant_context_passes(tmp_path, doc):
    assert _check(tmp_path, doc)["status"] == "pass"


def test_missing_context_fails(tmp_path):
    result = runtime.validate_artifact_for_obligation(str(tmp_path / "context-T1.json"), "context.v1")
    assert result["status"] == "fail"


FAULTS = {
    # Step 6 sanity checks.
    "development_approach_missing": (lambda d: d.pop("development_approach"), "development_approach"),
    "affected_files_empty": (lambda d: d["root_cause_analysis"].update(affected_files=[]), "affected_files"),
    # Post-BA contract compliance.
    "measured_value_null": (lambda d: d["evidence"]["measured"].update(value=None), "evidence.measured.value"),
    "measured_value_empty": (lambda d: d["evidence"]["measured"].update(value=""), "evidence.measured.value"),
    "expected_source_missing": (lambda d: d["evidence"]["expected"].pop("source"), "evidence.expected"),
    "all_occurrences_empty": (lambda d: d["scope_expansion"].update(all_occurrences=[]), "scope_expansion"),
    "copy_from_tainted": (lambda d: d["reference_source"].update(tier="tier_3_tainted"), "reference_source.tier"),
    "triggered_not_novel": (
        lambda d: d.update(prior_attempts={"triggered": True, "novelty_check": {"differs_from_all_priors": False}}),
        "prior_attempts.novelty_check.differs_from_all_priors",
    ),
    "no_localization": (
        lambda d: [d["root_cause_analysis"].pop(k) for k in ("complaint_location_keywords", "located_source")],
        "root_cause_analysis",
    ),
    # Test-writer gate fields.
    "tier_missing": (lambda d: d.pop("complexity_tier"), "complexity_tier"),
    "risk_out_of_enum": (lambda d: d.update(risk_level="severe"), "risk_level"),
    "expected_contradicts_tier": (lambda d: d.update(test_writer_expected=False), "test_writer_expected"),
    "expected_ignores_skip_reason": (
        lambda d: d.update(_test_writer_skip_reason="acceptance criteria carry an earlier cycle"),
        "test_writer_expected",
    ),
}


@pytest.mark.parametrize("name", sorted(FAULTS))
def test_each_moved_rule_fails_naming_its_field(tmp_path, name):
    change, field = FAULTS[name]
    result = _check(tmp_path, _with(STANDARD, change))
    assert result["status"] == "fail", result
    assert any(field in err for err in result["errors"]), result["errors"]


def _localization_blocked(doc: dict) -> None:
    rca = doc["root_cause_analysis"]
    del rca["complaint_location_keywords"], rca["located_source"]
    rca["localization_blocked"] = {"reason": "sealed environment", "what_would_unblock": "a reproduction"}


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(scope_expansion={"not_applicable": True, "reason": "no search seed"}),
        _localization_blocked,
        lambda d: d["reference_source"].update(tier="tier_3_tainted", copy_allowed=False),
        lambda d: d.update(_test_writer_skip_reason="stale criteria", test_writer_expected=False),
    ],
    ids=["scope_not_applicable", "localization_blocked", "tainted_not_copied", "skip_reason_honoured"],
)
def test_declared_alternatives_pass(tmp_path, change):
    assert _check(tmp_path, _with(STANDARD, change))["status"] == "pass"


def test_high_risk_small_tier_expects_the_test_writer(tmp_path):
    doc = _with(MICRO, lambda d: d.update(complexity_tier="SMALL", risk_level="high"))
    assert _check(tmp_path, doc)["status"] == "fail"
    doc["test_writer_expected"] = True
    assert _check(tmp_path, doc)["status"] == "pass"
