"""Focused contract tests for deterministic Dev/QA v1 report projections."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
# Put THIS checkout's hooks/ at the front, dropping any duplicate entry.  The
# former "insert only if absent" form let a hooks/ directory already on sys.path
# (an installed harness, say) win the import race, so the suite could certify a
# runtime it never shipped.  The provenance assertions below make that failure
# loud instead of silent.
sys.path[:] = [entry for entry in sys.path if entry != str(HOOKS)]
sys.path.insert(0, str(HOOKS))

from lib import contract_runtime as runtime  # noqa: E402
from lib import schema_registry as _schema_registry  # noqa: E402


def _assert_resolved_under_root(module, label: str) -> None:
    resolved = Path(module.__file__).resolve()
    assert resolved.is_relative_to(ROOT), (
        f"{label} resolved to {resolved}, outside this checkout ({ROOT}); the "
        "suite would be certifying a different installation"
    )


_assert_resolved_under_root(runtime, "contract_runtime")
_assert_resolved_under_root(_schema_registry, "schema_registry")
assert Path(_schema_registry.SCHEMAS_DIR).resolve() == (ROOT / "schemas").resolve(), (
    f"schema registry resolved {_schema_registry.SCHEMAS_DIR}, not {ROOT / 'schemas'}"
)


def _load_module(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


aggregate = _load_module("projection_aggregate", "scripts/aggregate-dev-report.py")
resolver = _load_module("projection_resolver", "scripts/resolve-dev-artifact-chain.py")
closeout = _load_module("projection_closeout", "hooks/lib/closeout.py")
file_check = _load_module(
    "projection_file_check", "hooks/posttool-overnight-file-check.py"
)
gitignore_reader = _load_module(
    "projection_gitignore_reader", "hooks/pretool-gitignore-preflight.py"
)
e2e_reader = _load_module(
    "projection_e2e_reader", "hooks/subagentstop-e2e-enforce.py"
)


@pytest.fixture(autouse=True)
def _use_checkout_schemas(monkeypatch: pytest.MonkeyPatch) -> None:
    schemas = {
        name: json.loads((ROOT / "schemas" / f"{name}.json").read_text(encoding="utf-8"))
        for name in ("dev-report.v1", "qa-report.v1")
    }
    monkeypatch.setattr(runtime.schema_registry, "get_schema", schemas.get)


def _dev_report(status: str = "completed") -> dict:
    top_status = {
        "completed": "completed",
        "blocked": "blocked",
        "needs_review": "partial",
    }[status]
    files_modified = ["hooks/lib/example.py"]
    files_created = ["hooks/tests/test_example.py"]
    ac_status = {"AC-01": "met", "AC-02": "n/a"}
    root_text = "The shared boundary now enforces the canonical producer contract."
    return {
        "report_version": 1,
        "request_id": "20260101-120000-projection",
        "task_id": "20260101-120000-projection",
        "status": top_status,
        "files_modified": copy.deepcopy(files_modified),
        "files_created": copy.deepcopy(files_created),
        "root_cause_addressed": root_text,
        "ac_status": copy.deepcopy(ac_status),
        "baseline_head_sha": "abc123",
        "baseline_dirty_snapshot": "",
        "blocking_issues": [],
        "dev": {
            "status": status,
            "files_modified": files_modified,
            "files_created": files_created,
            "ac_status": ac_status,
            "tasks_completed": [],
            "scripts_created": [],
            "permissions_to_add": [],
            "observed_preexisting": [],
            "git_rationale": {"how_fix_addresses_root": root_text},
        },
    }


def _ui_evidence() -> dict:
    return {
        "target_route": "/projection",
        "target_element": {
            "selector": "[data-testid='projection']",
            "selector_type": "data-testid",
        },
        "viewports": {
            "desktop": {
                "viewport": {"width": 1440, "height": 900},
                "screenshot": "evidence/desktop.png",
                "dom_measurement": {"width": 800},
            },
            "mobile": {
                "viewport": {"width": 390, "height": 844},
                "screenshot": "evidence/mobile.png",
                "dom_measurement": {"width": 360},
            },
        },
        "evidence_map": {"AC-01": ["evidence/desktop.png", "evidence/mobile.png"]},
        "trace": "evidence/trace.zip",
        "captured_at": "2026-08-10T00:00:00Z",
    }


def _qa_report(status: str = "pass", *, ui: bool = False) -> dict:
    evidence = {
        "verification": "Focused contract tests passed.",
        "checks": ["projection", "nested-consumer"],
    }
    if ui:
        evidence["ui_evidence"] = _ui_evidence()
    ac_status = {"AC-01": "met"}
    return {
        "report_version": 1,
        "request_id": "20260101-120000-projection",
        "task_id": "20260101-120000-projection",
        "verdict": status,
        "evidence_summary": copy.deepcopy(evidence),
        "ui_pipeline": ui,
        "ac_status": copy.deepcopy(ac_status),
        "qa": {
            "status": status,
            "evidence_summary": evidence,
            "ui_pipeline": ui,
            "ac_status": ac_status,
            "permissions_verification": {
                "validated_permissions": [
                    {"pattern": "Bash(example:*)", "reason": "fixture"}
                ]
            },
            "e2e_enforcement": {
                "status": "performed",
                "blocking_reason": None,
            },
        },
    }


# Canonical singular-projection producer examples, OWNED BY THIS SUITE.
#
# An earlier revision scraped these out of agents/dev.md and agents/qa.md by
# substring search.  That coupled a runtime contract test to two prompt
# documents: the suite raised ValueError on any checkout whose agent docs lack
# the marker (which is every checkout of the committed head), and it would
# break again on any future edit to that prose.  The projection contract is the
# subject under test, not a document, so the examples live here and are
# exercised through the real gate below.
_DEV_PRODUCER_EXAMPLE = {
    "report_version": 1,
    "request_id": "20260101-120000-example",
    "task_id": "20260101-120000-example",
    "status": "completed",
    "files_modified": ["hooks/lib/example.py"],
    "files_created": [],
    "root_cause_addressed": (
        "The shared contract boundary now enforces the producer invariant."
    ),
    "ac_status": {"AC-01": "met"},
    "dev": {
        "status": "completed",
        "files_modified": ["hooks/lib/example.py"],
        "files_created": [],
        "ac_status": {"AC-01": "met"},
        "git_rationale": {
            "how_fix_addresses_root": (
                "The shared contract boundary now enforces the producer invariant."
            )
        },
    },
}

_QA_PRODUCER_EXAMPLE = {
    "report_version": 1,
    "request_id": "20260101-120000-example",
    "task_id": "20260101-120000-example",
    "verdict": "pass",
    "evidence_summary": {"verification": "Focused contract tests passed."},
    "ui_pipeline": False,
    "ac_status": {"AC-01": "met"},
    "qa": {
        "status": "pass",
        "evidence_summary": {"verification": "Focused contract tests passed."},
        "ui_pipeline": False,
        "ac_status": {"AC-01": "met"},
    },
}

_PRODUCER_EXAMPLES = {
    "dev-report.v1": _DEV_PRODUCER_EXAMPLE,
    "qa-report.v1": _QA_PRODUCER_EXAMPLE,
}


def _producer_example(schema_name: str) -> dict:
    return copy.deepcopy(_PRODUCER_EXAMPLES[schema_name])


def _assert_fail(result: dict, *fragments: str) -> None:
    assert result["ok"] is False
    assert result["severity"] == "fail"
    joined = "\n".join(result["errors"])
    for fragment in fragments:
        assert fragment in joined


def _apply_mutations(report: dict, mutations: tuple[tuple, ...]) -> None:
    for operation, path, value in mutations:
        parent = report
        for key in path[:-1]:
            parent = parent[key]
        if operation == "delete":
            del parent[path[-1]]
        else:
            parent[path[-1]] = copy.deepcopy(value)


def _assert_both_entry_points_fail(
    report: dict, schema_name: str, *fragments: str
) -> None:
    before = copy.deepcopy(report)
    _assert_fail(runtime.validate(report, schema_name), *fragments)
    _assert_fail(runtime.validate_artifact(report, schema_name), *fragments)
    assert report == before


DEV_NEGATIVE_CASES = [
    pytest.param((("delete", ("report_version",), None),), ("report_version",), id="version-missing"),
    pytest.param((("set", ("report_version",), 2),), ("report_version",), id="version-wrong-value"),
    pytest.param((("set", ("report_version",), True),), ("report_version",), id="version-bool"),
    pytest.param((("delete", ("task_id",), None),), ("task_id",), id="task-id-missing"),
    pytest.param((("set", ("task_id",), ""),), ("task_id",), id="task-id-empty"),
    pytest.param((("set", ("task_id",), 1),), ("task_id",), id="task-id-wrong-type"),
    pytest.param((("delete", ("status",), None),), ("status", "dev.status"), id="status-flat-missing"),
    pytest.param((("delete", ("dev", "status"), None),), ("status", "dev.status"), id="status-source-missing"),
    pytest.param((("set", ("status",), "blocked"),), ("status", "dev.status"), id="status-contradiction"),
    pytest.param((("set", ("dev", "status"), "success"),), ("status", "dev.status"), id="status-unsupported"),
    pytest.param((("delete", ("files_modified",), None),), ("files_modified", "dev.files_modified"), id="modified-flat-missing"),
    pytest.param((("delete", ("dev", "files_modified"), None),), ("files_modified", "dev.files_modified"), id="modified-source-missing"),
    pytest.param((("set", ("files_modified",), []),), ("files_modified", "dev.files_modified"), id="modified-contradiction"),
    pytest.param((("delete", ("files_created",), None),), ("files_created", "dev.files_created"), id="created-flat-missing"),
    pytest.param((("delete", ("dev", "files_created"), None),), ("files_created", "dev.files_created"), id="created-source-missing"),
    pytest.param((("set", ("files_created",), []),), ("files_created", "dev.files_created"), id="created-contradiction"),
    pytest.param((("delete", ("root_cause_addressed",), None),), ("root_cause_addressed", "dev.git_rationale.how_fix_addresses_root"), id="root-flat-missing"),
    pytest.param((("delete", ("dev", "git_rationale", "how_fix_addresses_root"), None),), ("root_cause_addressed", "dev.git_rationale.how_fix_addresses_root"), id="root-source-missing"),
    pytest.param((("set", ("root_cause_addressed",), "contradiction"),), ("root_cause_addressed", "dev.git_rationale.how_fix_addresses_root"), id="root-contradiction"),
    pytest.param((("set", ("dev", "git_rationale", "how_fix_addresses_root"), ""),), ("root_cause_addressed", "dev.git_rationale.how_fix_addresses_root"), id="root-source-empty"),
    pytest.param((("delete", ("ac_status",), None),), ("ac_status", "dev.ac_status"), id="ac-flat-missing"),
    pytest.param((("delete", ("dev", "ac_status"), None),), ("ac_status", "dev.ac_status"), id="ac-source-missing"),
    pytest.param((("set", ("ac_status",), {"AC-01": "not_met"}),), ("ac_status", "dev.ac_status"), id="ac-contradiction"),
]


QA_NEGATIVE_CASES = [
    pytest.param((("delete", ("report_version",), None),), ("report_version",), id="version-missing"),
    pytest.param((("set", ("report_version",), 2),), ("report_version",), id="version-wrong-value"),
    pytest.param((("set", ("report_version",), True),), ("report_version",), id="version-bool"),
    pytest.param((("delete", ("task_id",), None),), ("task_id",), id="task-id-missing"),
    pytest.param((("set", ("task_id",), ""),), ("task_id",), id="task-id-empty"),
    pytest.param((("set", ("task_id",), 1),), ("task_id",), id="task-id-wrong-type"),
    pytest.param((("delete", ("verdict",), None),), ("verdict", "qa.status"), id="verdict-flat-missing"),
    pytest.param((("delete", ("qa", "status"), None),), ("verdict", "qa.status"), id="verdict-source-missing"),
    pytest.param((("set", ("verdict",), "fail"),), ("verdict", "qa.status"), id="verdict-contradiction"),
    pytest.param((("set", ("qa", "status"), "success"),), ("verdict", "qa.status"), id="verdict-unsupported"),
    pytest.param((("set", ("status",), "pass"),), ("status", "verdict", "qa.status"), id="top-status-forbidden"),
    pytest.param((("delete", ("evidence_summary",), None),), ("evidence_summary", "qa.evidence_summary"), id="evidence-flat-missing"),
    pytest.param((("delete", ("qa", "evidence_summary"), None),), ("evidence_summary", "qa.evidence_summary"), id="evidence-source-missing"),
    pytest.param((("set", ("evidence_summary",), {"checks": ["nested-consumer", "projection"], "verification": "Focused contract tests passed."}),), ("evidence_summary", "qa.evidence_summary"), id="evidence-list-order"),
    pytest.param((("set", ("qa", "evidence_summary"), {"nested": {"count": 1}}), ("set", ("evidence_summary",), {"nested": {"count": 1.0}})), ("evidence_summary", "qa.evidence_summary"), id="evidence-int-float"),
    pytest.param((("delete", ("ui_pipeline",), None),), ("ui_pipeline", "qa.ui_pipeline"), id="ui-flat-missing"),
    pytest.param((("delete", ("qa", "ui_pipeline"), None),), ("ui_pipeline", "qa.ui_pipeline"), id="ui-source-missing"),
    pytest.param((("set", ("ui_pipeline",), True),), ("ui_pipeline", "qa.ui_pipeline"), id="ui-boolean-contradiction"),
    pytest.param((("set", ("qa", "ui_pipeline"), 1), ("set", ("ui_pipeline",), True)), ("ui_pipeline", "qa.ui_pipeline"), id="ui-canonical-int-flat-true"),
    pytest.param((("set", ("ui_pipeline",), 0),), ("ui_pipeline", "qa.ui_pipeline"), id="ui-flat-int-source-false"),
    pytest.param((("delete", ("qa", "ac_status"), None),), ("ac_status", "qa.ac_status"), id="ac-source-missing"),
    pytest.param((("set", ("ac_status",), {"AC-01": "not_met"}),), ("ac_status", "qa.ac_status"), id="ac-contradiction"),
]


def test_producer_examples_are_valid_singular_projections() -> None:
    dev = _producer_example("dev-report.v1")
    qa = _producer_example("qa-report.v1")
    before_dev = copy.deepcopy(dev)
    before_qa = copy.deepcopy(qa)

    assert runtime.validate(dev, "dev-report.v1") == {
        "ok": True,
        "errors": [],
        "severity": "pass",
    }
    assert runtime.validate(qa, "qa-report.v1") == {
        "ok": True,
        "errors": [],
        "severity": "pass",
    }
    assert runtime.validate_artifact(dev, "dev-report.v1")["ok"]
    assert runtime.validate_artifact(qa, "qa-report.v1")["ok"]

    # Singularity: a flat alias is never duplicated inside the nested block it
    # projects from, and it agrees with that canonical source exactly.
    assert "root_cause_addressed" not in dev["dev"]
    assert (
        dev["root_cause_addressed"]
        == dev["dev"]["git_rationale"]["how_fix_addresses_root"]
    )
    assert "status" not in qa
    assert qa["verdict"] == qa["qa"]["status"]

    assert dev == before_dev
    assert qa == before_qa


def test_producer_examples_pass_the_report_artifact_gate(tmp_path: Path) -> None:
    for schema_name, basename in (
        ("dev-report.v1", "dev-report-producer-example.json"),
        ("qa-report.v1", "qa-report-producer-example.json"),
    ):
        path = tmp_path / basename
        path.write_text(json.dumps(_producer_example(schema_name)), encoding="utf-8")
        result = runtime.validate_report_artifact(path)
        assert result["status"] == "pass"
        assert result["schema"] == schema_name
        assert result["errors"] == []


def test_type_strict_json_equal_is_recursive_and_non_mutating() -> None:
    left = {"b": [1, {"flag": True}], "a": None}
    same_different_key_order = {"a": None, "b": [1, {"flag": True}]}
    before = copy.deepcopy(left)

    assert runtime.type_strict_json_equal(left, same_different_key_order)
    assert not runtime.type_strict_json_equal(True, 1)
    assert not runtime.type_strict_json_equal(False, 0)
    assert not runtime.type_strict_json_equal(1, 1.0)
    assert not runtime.type_strict_json_equal(["a", "b"], ["b", "a"])
    assert not runtime.type_strict_json_equal(
        {"nested": {"count": 1}}, {"nested": {"count": 1.0}}
    )
    assert left == before


@pytest.mark.parametrize("status", ["completed", "blocked", "needs_review"])
def test_dev_status_projection_positive_and_non_mutating(status: str) -> None:
    report = _dev_report(status)
    before = copy.deepcopy(report)
    assert runtime.validate(report, "dev-report.v1")["ok"]
    assert runtime.validate_artifact(report, "dev-report.v1")["ok"]
    assert report == before


@pytest.mark.parametrize(("mutations", "fragments"), DEV_NEGATIVE_CASES)
def test_dev_projection_negative_matrix(
    mutations: tuple[tuple, ...], fragments: tuple[str, ...]
) -> None:
    report = _dev_report()
    _apply_mutations(report, mutations)
    _assert_both_entry_points_fail(report, "dev-report.v1", *fragments)


@pytest.mark.parametrize("status", ["pass", "warning", "fail"])
def test_qa_status_projection_positive_and_non_mutating(status: str) -> None:
    report = _qa_report(status)
    # Object insertion order is not part of JSON equality.
    report["evidence_summary"] = {
        "checks": ["projection", "nested-consumer"],
        "verification": "Focused contract tests passed.",
    }
    before = copy.deepcopy(report)
    assert runtime.validate(report, "qa-report.v1")["ok"]
    assert runtime.validate_artifact(report, "qa-report.v1")["ok"]
    assert report == before


@pytest.mark.parametrize(("mutations", "fragments"), QA_NEGATIVE_CASES)
def test_qa_projection_negative_matrix(
    mutations: tuple[tuple, ...], fragments: tuple[str, ...]
) -> None:
    report = _qa_report()
    _apply_mutations(report, mutations)
    _assert_both_entry_points_fail(report, "qa-report.v1", *fragments)


def test_qa_optional_ac_status_alias_may_be_omitted() -> None:
    report = _qa_report()
    del report["ac_status"]
    assert runtime.validate(report, "qa-report.v1")["ok"]


# ---------------------------------------------------------------------------
# Diagnostic-shape contract.
#
# The negative matrices above assert on error FRAGMENTS, which several distinct
# diagnoses share.  The four checks below pin the parts of the public error
# output that consumers actually depend on: the schema-qualified prefix (the
# corpus differential attributes every flip by it), the missing-vs-mistyped
# distinction, and the JSON type names.
# ---------------------------------------------------------------------------


def test_projection_errors_are_schema_qualified_and_prefixed() -> None:
    for schema_name, report, flat_field in (
        ("dev-report.v1", _dev_report(), "status"),
        ("qa-report.v1", _qa_report(), "verdict"),
    ):
        del report[flat_field]
        result = runtime.validate(report, schema_name)
        assert result["ok"] is False
        assert result["errors"]
        for error in result["errors"]:
            assert error.startswith(f"projection {schema_name}: "), error


def test_missing_canonical_source_is_diagnosed_as_missing_not_mistyped() -> None:
    shallow = _dev_report()
    del shallow["dev"]["files_modified"]
    assert runtime.validate(shallow, "dev-report.v1")["errors"] == [
        "projection dev-report.v1: canonical source 'dev.files_modified' "
        "missing for flat field 'files_modified'"
    ]

    mapped = _dev_report()
    del mapped["dev"]["status"]
    assert runtime.validate(mapped, "dev-report.v1")["errors"] == [
        "projection dev-report.v1: canonical source 'dev.status' missing for "
        "flat field 'status'"
    ]

    deep = _dev_report()
    del deep["dev"]["git_rationale"]["how_fix_addresses_root"]
    assert runtime.validate(deep, "dev-report.v1")["errors"] == [
        "projection dev-report.v1: canonical source "
        "'dev.git_rationale.how_fix_addresses_root' missing for flat field "
        "'root_cause_addressed'"
    ]

    qa = _qa_report()
    del qa["qa"]["evidence_summary"]
    assert runtime.validate(qa, "qa-report.v1")["errors"] == [
        "projection qa-report.v1: canonical source 'qa.evidence_summary' "
        "missing for flat field 'evidence_summary'"
    ]


JSON_TYPE_NAME_CASES = [
    pytest.param(
        "dev-report.v1", ("dev", "files_modified"), "not-a-list",
        "projection dev-report.v1: canonical source 'dev.files_modified' must "
        "be an exact JSON array for flat field 'files_modified'",
        id="array",
    ),
    pytest.param(
        "dev-report.v1", ("dev", "ac_status"), ["AC-01"],
        "projection dev-report.v1: canonical source 'dev.ac_status' must be an "
        "exact JSON object for flat field 'ac_status'",
        id="object",
    ),
    pytest.param(
        "dev-report.v1", ("dev", "git_rationale", "how_fix_addresses_root"), 7,
        "projection dev-report.v1: canonical source "
        "'dev.git_rationale.how_fix_addresses_root' must be an exact non-empty "
        "JSON string for flat field 'root_cause_addressed'",
        id="string",
    ),
    pytest.param(
        "qa-report.v1", ("qa", "ui_pipeline"), 1,
        "projection qa-report.v1: canonical source 'qa.ui_pipeline' must be an "
        "exact JSON boolean for flat field 'ui_pipeline'",
        id="boolean",
    ),
]


@pytest.mark.parametrize(
    ("schema_name", "source_path", "bad_value", "expected"), JSON_TYPE_NAME_CASES
)
def test_canonical_source_type_names_are_exact(
    schema_name: str, source_path: tuple[str, ...], bad_value, expected: str
) -> None:
    report = (
        _dev_report() if schema_name == "dev-report.v1" else _qa_report()
    )
    _apply_mutations(report, (("set", source_path, bad_value),))
    assert expected in runtime.validate(report, schema_name)["errors"]


# ---------------------------------------------------------------------------
# Header guards on the validator-unavailable axis.
#
# report_version and task_id have no canonical nested source, so the projection
# header is their only pre-pass defence.  Draft7 numeric equality treats 1.0 as
# 1, so even with the validator PRESENT the header is the sole guard against a
# JSON float; with the validator ABSENT it is the sole guard for every invalid
# value.  That is the exact axis this landing exists to close, so it is pinned.
# ---------------------------------------------------------------------------

_VERSION_ERROR = (
    "projection dev-report.v1: flat field 'report_version' must be literal integer 1"
)
_TASK_ID_ERROR = (
    "projection qa-report.v1: flat field 'task_id' must be a non-empty string"
)


def _assert_draft7_unbound() -> None:
    """Positive control: prove the validator really is unbound.

    Without this the Draft7-absent cases below would also be satisfied by a run
    in which Draft7 was still bound and doing the rejecting.
    """
    assert runtime.Draft7Validator is None
    assert runtime.validate(_dev_report(), "dev-report.v1")["severity"] == "warn"


def test_projection_header_rejects_json_float_version_with_draft7_present() -> None:
    assert runtime.Draft7Validator is not None
    report = _dev_report()
    report["report_version"] = 1.0
    _assert_fail(runtime.validate(report, "dev-report.v1"), _VERSION_ERROR)


@pytest.mark.parametrize("bad_version", [2, "1", True, 1.0, None])
def test_projection_header_version_guard_holds_without_draft7(
    monkeypatch: pytest.MonkeyPatch, bad_version
) -> None:
    monkeypatch.setattr(runtime, "Draft7Validator", None)
    _assert_draft7_unbound()
    report = _dev_report()
    report["report_version"] = bad_version
    _assert_fail(runtime.validate(report, "dev-report.v1"), _VERSION_ERROR)


@pytest.mark.parametrize("bad_task_id", ["", 7, None, True])
def test_projection_header_task_id_guard_holds_without_draft7(
    monkeypatch: pytest.MonkeyPatch, bad_task_id
) -> None:
    monkeypatch.setattr(runtime, "Draft7Validator", None)
    _assert_draft7_unbound()
    report = _qa_report()
    report["task_id"] = bad_task_id
    _assert_fail(runtime.validate(report, "qa-report.v1"), _TASK_ID_ERROR)


def test_qa_ui_evidence_prepass_remains_enforced_after_projection() -> None:
    report = _qa_report(ui=True)
    assert runtime.validate(report, "qa-report.v1")["ok"]

    incomplete = copy.deepcopy(report)
    del incomplete["qa"]["evidence_summary"]["ui_evidence"]
    del incomplete["evidence_summary"]["ui_evidence"]
    _assert_fail(
        runtime.validate(incomplete, "qa-report.v1"),
        "required_when_ui",
        "evidence_summary.ui_evidence",
    )


def test_interactive_gate_matrix(tmp_path: Path) -> None:
    matching = tmp_path / "dev-report-match.json"
    matching.write_text(json.dumps(_dev_report()), encoding="utf-8")
    assert runtime.validate_report_artifact(matching)["status"] == "pass"

    mismatch = _dev_report()
    mismatch["root_cause_addressed"] = "contradiction"
    mismatch_path = tmp_path / "dev-report-mismatch.json"
    mismatch_path.write_text(json.dumps(mismatch), encoding="utf-8")
    assert runtime.validate_report_artifact(mismatch_path)["status"] == "fail"

    wrong_version = _dev_report()
    wrong_version["report_version"] = 2
    wrong_path = tmp_path / "dev-report-wrong-version.json"
    wrong_path.write_text(json.dumps(wrong_version), encoding="utf-8")
    assert runtime.validate_report_artifact(wrong_path)["status"] == "fail"

    legacy = _dev_report()
    del legacy["report_version"]
    legacy_path = tmp_path / "dev-report-legacy.json"
    legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
    assert runtime.validate_report_artifact(legacy_path)["status"] == "skip"

    invalid = tmp_path / "qa-report-invalid.json"
    invalid.write_text("{", encoding="utf-8")
    assert runtime.validate_report_artifact(invalid)["status"] == "skip"
    assert runtime.validate_report_artifact(tmp_path / "qa-report-absent.json")["status"] == "skip"

    do_report = tmp_path / "do-report-example.json"
    do_report.write_text(json.dumps({"report_version": 1}), encoding="utf-8")
    assert runtime.validate_report_artifact(do_report)["status"] == "skip"


@pytest.mark.parametrize(
    "tell", ["not registered", "validator raised: synthetic", "schema_registry error: synthetic"]
)
@pytest.mark.parametrize("kind", ["dev", "qa"])
def test_infrastructure_words_in_user_failures_never_cause_skip(
    tmp_path: Path, tell: str, kind: str
) -> None:
    if kind == "dev":
        report = _dev_report()
        report["dev"]["status"] = tell
    else:
        report = _qa_report()
        report["qa"]["status"] = tell
    path = tmp_path / f"{kind}-report-status-tell.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    assert runtime.validate_report_artifact(path)["status"] == "fail"

    schema_invalid = _dev_report()
    value = [{"note": tell}]
    schema_invalid["dev"]["files_modified"] = copy.deepcopy(value)
    schema_invalid["files_modified"] = copy.deepcopy(value)
    invalid_path = tmp_path / f"dev-report-schema-tell-{kind}.json"
    invalid_path.write_text(json.dumps(schema_invalid), encoding="utf-8")
    assert runtime.validate_report_artifact(invalid_path)["status"] == "fail"


def test_exact_schema_infrastructure_failures_still_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "dev-report-infrastructure.json"
    path.write_text(json.dumps(_dev_report()), encoding="utf-8")

    monkeypatch.setattr(runtime.schema_registry, "get_schema", lambda name: None)
    assert runtime.validate_report_artifact(path)["status"] == "skip"

    def _raise_registry(name):
        raise RuntimeError("synthetic registry outage")

    monkeypatch.setattr(runtime.schema_registry, "get_schema", _raise_registry)
    assert runtime.validate_report_artifact(path)["status"] == "skip"

    schema = json.loads((ROOT / "schemas/dev-report.v1.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(runtime.schema_registry, "get_schema", lambda name: schema)

    class BrokenValidator:
        def __init__(self, value):
            raise RuntimeError("synthetic validator outage")

    monkeypatch.setattr(runtime, "Draft7Validator", BrokenValidator)
    assert runtime.validate_report_artifact(path)["status"] == "skip"


def test_projection_failure_precedes_draft7_unavailability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    matching = _qa_report()
    contradiction = _qa_report()
    contradiction["evidence_summary"] = {"verification": "different"}
    missing_source = _qa_report()
    del missing_source["qa"]["evidence_summary"]
    monkeypatch.setattr(runtime, "Draft7Validator", None)

    matching_path = tmp_path / "qa-report-matching.json"
    matching_path.write_text(json.dumps(matching), encoding="utf-8")
    assert runtime.validate_report_artifact(matching_path)["status"] == "skip"
    direct = runtime.validate_artifact(matching, "qa-report.v1")
    assert direct["ok"] is True and direct["severity"] == "warn"

    for name, report in (("contradiction", contradiction), ("missing", missing_source)):
        path = tmp_path / f"qa-report-{name}.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        assert runtime.validate_report_artifact(path)["status"] == "fail"
        _assert_fail(runtime.validate_artifact(report, "qa-report.v1"), "qa.evidence_summary")


def test_direct_caller_keeps_invalid_json_and_projection_fail_closed(tmp_path: Path) -> None:
    valid = tmp_path / "dev-report-valid.json"
    valid.write_text(json.dumps(_dev_report()), encoding="utf-8")
    assert file_check._validate_one_artifact(valid, "dev-report.v1") == ("pass", [])

    missing_version = _dev_report()
    del missing_version["report_version"]
    _assert_fail(runtime.validate_artifact(missing_version, "dev-report.v1"), "report_version")

    mismatch = _dev_report()
    mismatch["files_created"] = []
    mismatch_path = tmp_path / "dev-report-mismatch.json"
    mismatch_path.write_text(json.dumps(mismatch), encoding="utf-8")
    status, errors = file_check._validate_one_artifact(mismatch_path, "dev-report.v1")
    assert status == "fail" and any("dev.files_created" in error for error in errors)

    invalid = tmp_path / "dev-report-invalid.json"
    invalid.write_text("not-json", encoding="utf-8")
    assert file_check._validate_one_artifact(invalid, "dev-report.v1")[0] == "invalid_json"
    assert file_check._validate_one_artifact(tmp_path / "missing.json", "dev-report.v1")[0] == "missing"


@pytest.mark.parametrize(("ui", "coverage"), [(False, None), (True, 1.0)])
def test_projected_qa_activates_correct_closeout_metrics(ui: bool, coverage) -> None:
    report = _qa_report(ui=ui)
    assert runtime.validate(report, "qa-report.v1")["ok"]
    loaded = [{"entry": {"ui_pipeline": ui}, "report": report}]

    assert closeout._count_passed_pipelines(loaded) == 1
    assert closeout._false_pass_risk_count(loaded) == 0
    assert closeout._ui_evidence_coverage(loaded) == coverage


def test_projected_dev_preserves_aggregate_and_resolver_nested_semantics(
    tmp_path: Path,
) -> None:
    first = _dev_report()
    second = _dev_report()
    second["dev"]["files_modified"] = ["hooks/lib/second.py"]
    second["files_modified"] = ["hooks/lib/second.py"]
    shards = [("a", first), ("b", second)]

    assert runtime.validate(first, "dev-report.v1")["ok"]
    assert runtime.validate(second, "dev-report.v1")["ok"]
    assert aggregate._validate_shards(shards, first["task_id"]) == []
    combined = aggregate._build_aggregate(shards, first["task_id"])
    assert combined["dev"]["status"] == "completed"
    assert combined["dev"]["files_modified"] == [
        "hooks/lib/example.py",
        "hooks/lib/second.py",
    ]

    checker = resolver.ChainValidator(tmp_path, first["task_id"])
    checker.validate_dev(first, first["task_id"], tmp_path / "dev-report.json")
    assert checker.errors == []


def test_projected_dev_is_accepted_by_nested_file_claim_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _dev_report()
    assert runtime.validate(report, "dev-report.v1")["ok"]
    report_path = tmp_path / "docs" / "dev" / "dev-report-projection.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(json.dumps(report), encoding="utf-8")
    hook_input = {
        "tool_name": "Agent",
        "tool_input": {"prompt": "Read docs/dev/dev-report-projection.json"},
    }
    observed_claims: list[str] = []

    def _record_claim(path: str, root: str) -> bool:
        assert root == str(tmp_path)
        observed_claims.append(path)
        return False

    monkeypatch.setattr(gitignore_reader, "get_repo_root", lambda: str(tmp_path))
    monkeypatch.setattr(gitignore_reader, "is_gitignored", _record_claim)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(hook_input)))

    with pytest.raises(SystemExit) as exc:
        gitignore_reader.main()
    assert exc.value.code == 0
    assert observed_claims == (
        report["dev"]["files_modified"] + report["dev"]["files_created"]
    )


def test_projected_qa_is_accepted_by_permission_and_e2e_readers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _qa_report()
    docs = tmp_path / "docs" / "dev"
    docs.mkdir(parents=True)
    report_path = docs / "qa-report-20260101-120000-projection.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "aggregate-permissions.py"), str(docs)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(proc.stdout) == [
        {"pattern": "Bash(example:*)", "reason": "fixture"}
    ]

    session_id = "dev-20260101-120000-projection"
    enforce = tmp_path / ".claude" / "dev-registry" / session_id / "e2e-enforce.json"
    enforce.parent.mkdir(parents=True)
    enforce.write_text('{"enabled": true}', encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(e2e_reader, "_load_stdin", lambda: {"agent_id": "qa-agent"})
    monkeypatch.setattr(
        e2e_reader,
        "resolve_dev_registry_entry",
        lambda agent_id, project_dir: {
            "dev_session_id": session_id,
            "agent_type": "qa",
        },
    )
    with pytest.raises(SystemExit) as exc:
        e2e_reader.main()
    assert exc.value.code == 0


HISTORICAL_QA_ARTIFACTS = {
    "qa-report-dev-20260719-150041-c.json": "dev-20260719-150041-c",
    "qa-report-dev-20260720-150632-a.json": "dev-20260720-150632-a",
    "qa-report-iter1-dev-20260720-150632-a.json": "dev-20260720-150632-a",
}


def _historical_qa_record(name: str, task_id: str) -> dict:
    """Build a REPRESENTATIVE legacy qa-report shape: no evidence_summary source.

    This is a synthetic stand-in for the shape, NOT a claim about the exact
    bytes of the three named artifacts — those live under the gitignored
    docs/dev tree, absent from every clean checkout and mutable in every dirty
    one.  An earlier revision searched ROOT *and its parent directories* for
    them, which made the outcome depend on paths outside the repository and
    skipped silently when they were missing.  The policy under test is about
    the shape, so the suite owns the shape and enforces the policy
    unconditionally; claims about the real corpus belong to the pinned
    snapshot differential, not to this suite.
    """
    record = _qa_report("pass" if "20260719" in name else "fail")
    record["request_id"] = task_id
    record["task_id"] = task_id
    del record["qa"]["evidence_summary"]
    del record["qa"]["ui_pipeline"]
    del record["qa"]["ac_status"]
    del record["ac_status"]
    return record


def test_historical_required_qa_policy_is_always_enforced() -> None:
    task_ids = set()
    for name, task_id in HISTORICAL_QA_ARTIFACTS.items():
        record = _historical_qa_record(name, task_id)
        task_ids.add(record["task_id"])
        _assert_fail(
            runtime.validate_artifact(record, "qa-report.v1"),
            "evidence_summary",
            "qa.evidence_summary",
        )
        _assert_fail(
            runtime.validate(record, "qa-report.v1"),
            "evidence_summary",
            "qa.evidence_summary",
        )
    assert len(HISTORICAL_QA_ARTIFACTS) == 3
    assert task_ids == {"dev-20260719-150041-c", "dev-20260720-150632-a"}


def test_historical_qa_shape_is_blocked_at_the_gate_without_mutation(
    tmp_path: Path,
) -> None:
    """The historical shape must be BLOCKED by the public gate, not merely by
    ``validate``; and neither the artifact bytes nor the record may change."""
    for name, task_id in HISTORICAL_QA_ARTIFACTS.items():
        record = _historical_qa_record(name, task_id)
        before_record = copy.deepcopy(record)
        path = tmp_path / name
        path.write_text(json.dumps(record), encoding="utf-8")
        before_bytes = hashlib.sha256(path.read_bytes()).hexdigest()

        result = runtime.validate_report_artifact(path)
        assert result["status"] == "fail"
        assert result["schema"] == "qa-report.v1"
        assert any("qa.evidence_summary" in error for error in result["errors"])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before_bytes

        # validate_report_artifact re-parses the file and never receives
        # `record`, so asserting on `record` after it alone would be vacuous.
        # Hand the SAME object to the in-memory entry point, which does take it,
        # and only then is non-mutation an assertion about anything.
        _assert_fail(
            runtime.validate_artifact(record, "qa-report.v1"),
            "evidence_summary",
            "qa.evidence_summary",
        )
        assert record == before_record
