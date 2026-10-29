"""hooks/lib/contract_runtime.py reads the vocabularies it checks from the
schema that declares them (P1b row 19 rule 7): the QA statuses the v1
projection accepts are qa-report.v1's verdict enum, and the focus-criteria
evidence levels are qa-report.v1's evidence_level enums. No copy of either
list stays in the code.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "hooks"))

from lib import contract_runtime as cr  # noqa: E402
from lib import schema_registry  # noqa: E402

QA_V1 = schema_registry.get_schema("qa-report.v1")
LEVELS_PATH = ("properties", "focus_criteria_results", "properties", "results", "items", "properties")


def _levels(schema: dict) -> dict:
    node = schema
    for key in LEVELS_PATH:
        node = node[key]
    return node


def _focus(level: str, required: str | None = None) -> dict:
    item = {"criterion": "toy check", "result": "pass", "evidence": "x", "severity": "minor",
            "evidence_level": level}
    if required:
        item["required_evidence_level"] = required
    return {"focus_criteria_results": {"results": [item]}}


def test_the_evidence_levels_are_the_schemas(monkeypatch):
    declared = _levels(QA_V1)["evidence_level"]["enum"]
    errors = cr._check_evidence_taxonomy(_focus("bogus"))
    assert errors == [f"focus_criteria_results.results[0].evidence_level must be one of {sorted(declared)}"]
    assert cr._check_evidence_taxonomy(_focus(declared[0])) == []
    # A level the schema adds is accepted with no code change.
    widened = copy.deepcopy(QA_V1)
    for key in ("evidence_level", "required_evidence_level"):
        _levels(widened)[key]["enum"].append("operator_attested")
    real = schema_registry.get_schema
    monkeypatch.setattr(schema_registry, "get_schema",
                        lambda sid: widened if sid == "qa-report.v1" else real(sid))
    assert cr._check_evidence_taxonomy(_focus("operator_attested", "operator_attested")) == []


def test_without_the_declaration_nothing_is_judged(monkeypatch):
    monkeypatch.setattr(schema_registry, "get_schema", lambda sid: None)
    assert cr._check_evidence_taxonomy(_focus("bogus")) == []


def test_the_accepted_qa_statuses_are_the_schemas_verdict_enum():
    record = {"qa": {"status": "warning"}}
    unsupported = "has unsupported value 'warning' for flat field 'verdict'"
    assert not any(unsupported in e for e in cr._check_qa_report_projection(record, QA_V1))
    narrowed = copy.deepcopy(QA_V1)
    narrowed["properties"]["verdict"]["enum"] = ["pass", "fail"]
    assert any(unsupported in e for e in cr._check_qa_report_projection(record, narrowed))
