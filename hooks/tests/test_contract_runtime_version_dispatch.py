#!/usr/bin/env python3
"""Tests for report_version dispatch + obligation-authority validation in
hooks/lib/contract_runtime.py (ticket 20260929-104216-a, zero-failure design
rollout S1 — docs/reference/close-commit-zero-failure-mechanism-20260928.md
§1.2/§1.6).

Covers the lane's acceptance criteria:
  AC-1  valid nested v2 dev report passes as dev-report.v2
  AC-2  v2-declared-but-invalid fails naming the offending field
  AC-3  unversioned records skip exactly as today (+ full-corpus regression)
  AC-4  report_version 1 behaves byte-identically to the pre-change engine
        (the "full pre-existing suite green" clause of AC-4 is verified by
        actually running the suite, which this file is part of)
  AC-5  validate_artifact_for_obligation: obligation-supplied schema id
        overrides self-declaration; absent file fails; unregistered id skips
  AC-6  qa-report.v2 nested contract incl. the EXACT 5-value e2e enum
  AC-7  obligation.v1 validates the design §1.2 grammar
  AC-8  lane/lane_set conditional
  AC-9  registry registration purely additive

Import pattern matches the live consumer
hooks/subagentstop-artifact-contract-enforce.py (sys.path insert of hooks/,
then ``from lib import contract_runtime``).
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "hooks"))

from lib import contract_runtime as cr  # noqa: E402
from lib import schema_registry  # noqa: E402

E2E_ENUM = {
    "performed",
    "ran",
    "blocked_app_unavailable",
    "legitimately_skipped",
    "skipped_without_justification",
}

# The 10 registry entries as they existed at the pre-cycle baseline
# (baseline_head_sha 025f4c8a — schemas/registry.json was clean in the
# dispatch-time git status snapshot, so the blob IS the pre-cycle content).
PREEXISTING_REGISTRY_ENTRIES = [
    ("cycle-contract.v1", "cycle-contract.v1.json"),
    ("qa-report.v1", "qa-report.v1.json"),
    ("dev-report.v1", "dev-report.v1.json"),
    ("do-report.v1", "do-report.v1.json"),
    ("context.v1", "context.v1.json"),
    ("test-plan.v1", "test-plan.v1.json"),
    ("graphify-prequery.v1", "graphify-prequery.v1.json"),
    ("graphify-run.v1", "graphify-run.v1.json"),
    ("graphify-focused-subgraph.v1", "graphify-focused-subgraph.v1.json"),
    ("paseo-dossier.v1", "paseo-dossier.v1.json"),
]

NEW_REGISTRY_ENTRIES = ["dev-report.v2", "qa-report.v2", "obligation.v1"]


def _valid_v2_dev_record(**overrides) -> dict:
    record = {
        "report_version": 2,
        "request_id": "20260929-104216-a",
        "task_id": "20260929-104216-a",
        "timestamp": "2026-09-29T12:00:00Z",
        "baseline_head_sha": "025f4c8ace1bd6e80b91761e18bf50b343297a67",
        "baseline_dirty_snapshot": "",
        "owned_edits": {},
        "pre_edit_snapshots": {},
        "dev": {
            "status": "completed",
            "files_modified": [],
            "files_created": [],
        },
    }
    record.update(overrides)
    return record


def _valid_v2_qa_record(**overrides) -> dict:
    record = {
        "report_version": 2,
        "request_id": "20260929-104216-a",
        "task_id": "20260929-104216-a",
        "timestamp": "2026-09-29T12:00:00Z",
        "qa": {
            "status": "pass",
            "e2e_enforcement": {"status": "performed"},
        },
    }
    record.update(overrides)
    return record


def _obligation_example() -> dict:
    """Design §1.2 example payload, schema ids adjusted to ones this lane
    registers (changelog-status.v1 is a sibling/later lane) and the
    placeholder terminal rule replaced with a concrete regex."""
    return {
        "task_id": "20260928-153000",
        "lane": "b",
        "lane_set": ["a", "b", "c"],
        "role": "dev",
        "pipeline": "dev",
        "profile": "fanout-lane",
        "dispatched_at": "2026-09-28T15:30:05Z",
        "artifacts": [
            {
                "kind": "json",
                "path": "docs/dev/dev-report-20260928-153000-b.json",
                "schema": "dev-report.v2",
                "identity": {
                    "task_id": "20260928-153000-b",
                    "request_id": "20260928-153000-b",
                },
            },
            {
                "kind": "markdown",
                "path": "docs/dev/close-report-20260928-153000.md",
                "identity_anchor": "20260928-153000",
                "terminal_line_regex": "^(CLOSED|NOT-CLOSED): ",
                "waived_by_response": "^CLOSE_REPORT_APPEND_(ERROR|CRITICAL): ",
            },
            {
                "kind": "response_block",
                "begin": "--- CHANGELOG-ANALYST-STATUS-BEGIN ---",
                "end": "--- CHANGELOG-ANALYST-STATUS-END ---",
                "format": "json",
                "schema": "qa-report.v2",
            },
            {
                "kind": "response_line",
                "terminal_line_regex": "^COMMIT: (APPROVE|REJECT)",
            },
        ],
        "consistency": "verdict_class",
        "expected_absent": ["docs/dev/qa-report-20260928-153000.json"],
    }


def _write_report(tmp_path: Path, name: str, record) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(record), encoding="utf-8")
    return str(path)


def _joined_errors(result: dict) -> str:
    return " ".join(str(e) for e in result.get("errors", []))


# ---------------------------------------------------------------------------
# AC-1 / AC-2 — v2 dev-report dispatch
# ---------------------------------------------------------------------------


def test_valid_v2_dev_report_passes(tmp_path):
    path = _write_report(tmp_path, "dev-report-actest.json", _valid_v2_dev_record())
    result = cr.validate_report_artifact(path)
    assert result["status"] == "pass"
    assert result["schema"] == "dev-report.v2"


def test_v2_missing_baseline_keys_fail_named(tmp_path):
    for missing in ("baseline_head_sha", "baseline_dirty_snapshot"):
        record = _valid_v2_dev_record()
        del record[missing]
        result = cr.validate_report_artifact(
            _write_report(tmp_path, "dev-report-actest.json", record)
        )
        assert result["status"] == "fail"
        assert result["schema"] == "dev-report.v2"
        assert missing in _joined_errors(result)


def test_v2_needs_review_without_rationale_fails_named(tmp_path):
    record = _valid_v2_dev_record()
    record["dev"]["status"] = "needs_review"
    result = cr.validate_report_artifact(
        _write_report(tmp_path, "dev-report-actest.json", record)
    )
    assert result["status"] == "fail"
    assert "status_rationale" in _joined_errors(result)


# ---------------------------------------------------------------------------
# AC-3 — unversioned skip + corpus regression
# ---------------------------------------------------------------------------

UNVERSIONED_REASON = "unversioned artifact (no report_version)"


def test_unversioned_record_skips_with_existing_reason(tmp_path):
    record = _valid_v2_dev_record()
    del record["report_version"]
    result = cr.validate_report_artifact(
        _write_report(tmp_path, "dev-report-actest.json", record)
    )
    assert result["status"] == "skip"
    assert UNVERSIONED_REASON in result["reason"]


def _pre_change_engine_status(path: Path) -> str:
    """The pre-change (v1-only) gate, reproduced verbatim from its documented
    behavior: unversioned -> skip; versioned -> validate against the kind's
    v1 schema with the fail-safe infra split."""
    kinds = {
        "dev-report": "dev-report.v1",
        "qa-report": "qa-report.v1",
        "do-report": "do-report.v1",
    }
    kind = next((k for k in kinds if path.name.startswith(k + "-")), None)
    if kind is None:
        return "skip"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "skip"
    if not isinstance(record, dict) or "report_version" not in record:
        return "skip"
    result = cr.validate(record, kinds[kind])
    if cr._skip_reason_if_unvalidatable(result) is not None:
        return "skip"
    return "pass" if result.get("ok") else "fail"


def test_legacy_corpus_never_retro_rejected():
    corpus = sorted(
        list((REPO_ROOT / "docs" / "dev").glob("dev-report-*.json"))
        + list((REPO_ROOT / "docs" / "dev").glob("qa-report-*.json"))
    )
    assert corpus, "legacy corpus unexpectedly empty"
    changes = []
    v2_declared = 0
    for path in corpus:
        new_status = cr.validate_report_artifact(str(path))["status"]
        old_status = _pre_change_engine_status(path)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(record, dict) and record.get("report_version") == 2:
                v2_declared += 1
                continue  # v2-declared records are the NEW opt-in surface
        except (OSError, json.JSONDecodeError):
            pass
        if new_status != old_status:
            changes.append((str(path), old_status, new_status))
    assert changes == [], f"corpus status regressions: {changes}"
    # Measured at landing time (2026-09-29): v2_declared == 0, so the
    # equivalence was total. v2-declared records are the NEW opt-in surface
    # (post-S6 producers), excluded from the legacy-corpus equivalence by
    # definition rather than pinned to zero forever.
    del v2_declared


# ---------------------------------------------------------------------------
# AC-4 — v1 path byte-identical
# ---------------------------------------------------------------------------


def _valid_flat_v1_record() -> dict:
    return {
        "report_version": 1,
        "task_id": "20260929-104216-a",
        "status": "completed",
        "files_modified": [],
        "files_created": [],
        "root_cause_addressed": "x",
        "ac_status": {"AC-1": "met"},
    }


def test_v1_records_behave_exactly_as_today(tmp_path):
    valid = _valid_flat_v1_record()
    result = cr.validate_report_artifact(
        _write_report(tmp_path, "dev-report-actest.json", valid)
    )
    assert result["status"] == "pass"
    assert result["schema"] == "dev-report.v1"

    invalid = _valid_flat_v1_record()
    del invalid["status"]
    result = cr.validate_report_artifact(
        _write_report(tmp_path, "dev-report-actest.json", invalid)
    )
    assert result["status"] == "fail"
    assert result["schema"] == "dev-report.v1"
    # Error TEXT identity with the underlying v1 engine (same validate() path).
    assert result["errors"] == cr.validate(invalid, "dev-report.v1")["errors"]


def test_alien_report_version_keeps_todays_v1_const_fail(tmp_path):
    """Declared version 3 (and any non-1/2 value) follows today's exact path:
    validate against the kind's v1 schema, whose report_version const fails.
    Mapping alien versions to SKIP was explicitly rejected (ticket M5)."""
    record = _valid_v2_dev_record(report_version=3)
    result = cr.validate_report_artifact(
        _write_report(tmp_path, "dev-report-actest.json", record)
    )
    assert result["status"] == "fail"
    assert result["schema"] == "dev-report.v1"


def test_do_report_version_2_falls_through_to_v1(tmp_path):
    """No do-report.v2 exists; every do-report version keeps today's path."""
    result = cr.validate_report_artifact(
        _write_report(tmp_path, "do-report-x.json", {"report_version": 2})
    )
    assert result["schema"] == "do-report.v1"


# ---------------------------------------------------------------------------
# AC-5 — obligation-supplied schema id overrides self-declaration
# ---------------------------------------------------------------------------


def test_obligation_override_ignores_self_declaration(tmp_path):
    v1_declared = _valid_v2_dev_record(report_version=1)
    path = _write_report(tmp_path, "dev-report-actest.json", v1_declared)
    result = cr.validate_artifact_for_obligation(path, "dev-report.v2")
    assert result["status"] == "pass"
    assert result["schema"] == "dev-report.v2"

    unversioned = _valid_v2_dev_record()
    del unversioned["report_version"]
    result = cr.validate_artifact_for_obligation(
        _write_report(tmp_path, "dev-report-unversioned.json", unversioned),
        "dev-report.v2",
    )
    assert result["status"] == "pass"


def test_obligation_override_still_fails_genuine_violations(tmp_path):
    record = _valid_v2_dev_record(report_version=1)
    del record["baseline_head_sha"]
    result = cr.validate_artifact_for_obligation(
        _write_report(tmp_path, "dev-report-actest.json", record), "dev-report.v2"
    )
    assert result["status"] == "fail"
    assert "baseline_head_sha" in _joined_errors(result)


def test_obligation_absent_file_is_blocking(tmp_path):
    missing = tmp_path / "dev-report-never-written.json"
    result = cr.validate_artifact_for_obligation(str(missing), "dev-report.v2")
    assert result["status"] == "fail"
    assert str(missing) in _joined_errors(result)


def test_obligation_unregistered_schema_id_fail_safe_skips(tmp_path):
    path = _write_report(tmp_path, "dev-report-actest.json", _valid_v2_dev_record())
    result = cr.validate_artifact_for_obligation(path, "no-such-schema.v9")
    assert result["status"] == "skip"
    assert result["reason"]


def test_obligation_unparseable_json_fails(tmp_path):
    path = tmp_path / "dev-report-broken.json"
    path.write_text("{not json", encoding="utf-8")
    result = cr.validate_artifact_for_obligation(str(path), "dev-report.v2")
    assert result["status"] == "fail"


def test_self_declared_gate_unchanged_by_obligation_normalization(tmp_path):
    """The version-override applies ONLY under obligation authority: the
    self-declared gate still routes a report_version:1 record to v1."""
    path = _write_report(
        tmp_path, "dev-report-actest.json", _valid_v2_dev_record(report_version=1)
    )
    result = cr.validate_report_artifact(path)
    assert result["schema"] == "dev-report.v1"


# ---------------------------------------------------------------------------
# AC-6 — qa-report.v2 nested contract
# ---------------------------------------------------------------------------


def test_qa_v2_base_and_all_five_e2e_values_pass():
    assert cr.validate(_valid_v2_qa_record(), "qa-report.v2")["ok"]
    for value in sorted(E2E_ENUM):
        record = _valid_v2_qa_record()
        record["qa"]["e2e_enforcement"]["status"] = value
        assert cr.validate(record, "qa-report.v2")["ok"], value


def test_qa_v2_failing_variants_name_offender():
    top_status = _valid_v2_qa_record()
    top_status["status"] = "pass"
    result = cr.validate(top_status, "qa-report.v2")
    assert not result["ok"] and "status" in _joined_errors(result)

    top_verdict = _valid_v2_qa_record()
    top_verdict["verdict"] = "pass"
    result = cr.validate(top_verdict, "qa-report.v2")
    assert not result["ok"] and "verdict" in _joined_errors(result)

    no_e2e = _valid_v2_qa_record()
    del no_e2e["qa"]["e2e_enforcement"]
    result = cr.validate(no_e2e, "qa-report.v2")
    assert not result["ok"] and "e2e_enforcement" in _joined_errors(result)

    bad_e2e = _valid_v2_qa_record()
    bad_e2e["qa"]["e2e_enforcement"]["status"] = "unrecognized_value"
    result = cr.validate(bad_e2e, "qa-report.v2")
    assert not result["ok"] and "e2e_enforcement.status" in _joined_errors(result)


def test_qa_v2_e2e_enum_set_equality_exact():
    schema = schema_registry.get_schema("qa-report.v2")
    enum = schema["properties"]["qa"]["properties"]["e2e_enforcement"][
        "properties"
    ]["status"]["enum"]
    assert set(enum) == E2E_ENUM
    assert len(enum) == len(E2E_ENUM)


# ---------------------------------------------------------------------------
# AC-7 — obligation.v1 grammar
# ---------------------------------------------------------------------------


def test_obligation_example_payload_passes():
    result = cr.validate(_obligation_example(), "obligation.v1")
    assert result["ok"], result["errors"]


def test_obligation_variants_fail_named():
    cases = []
    v = _obligation_example()
    v["role"] = "wizard"
    cases.append((v, "role"))
    v = _obligation_example()
    v["profile"] = "unrecognized"
    cases.append((v, "profile"))
    v = _obligation_example()
    del v["artifacts"][0]["schema"]
    cases.append((v, "schema"))
    v = _obligation_example()
    v["artifacts"][0]["path"] = "docs/../etc/passwd"
    cases.append((v, "path"))
    v = _obligation_example()
    v["unexpected_top_level_key"] = 1
    cases.append((v, "unexpected_top_level_key"))
    for record, offender in cases:
        result = cr.validate(copy.deepcopy(record), "obligation.v1")
        assert not result["ok"], offender
        assert offender in _joined_errors(result), offender


def test_obligation_null_task_id_gate():
    """Expressible half of the null-task_id gate (ticket M3)."""
    v = _obligation_example()
    v["task_id"] = None
    v["profile"] = "singular"
    assert not cr.validate(v, "obligation.v1")["ok"]
    v = _obligation_example()
    v["task_id"] = None
    v["profile"] = "ad_hoc"
    assert cr.validate(v, "obligation.v1")["ok"]


def test_obligation_absolute_path_rejected():
    v = _obligation_example()
    v["artifacts"][0]["path"] = "/etc/passwd"
    assert not cr.validate(v, "obligation.v1")["ok"]


# ---------------------------------------------------------------------------
# AC-8 — lane/lane_set conditional (dev-report.v2; same construct in qa v2)
# ---------------------------------------------------------------------------


def test_lane_set_conditional():
    result = cr.validate(_valid_v2_dev_record(lane="b"), "dev-report.v2")
    assert not result["ok"]
    assert "lane_set" in _joined_errors(result)

    assert cr.validate(
        _valid_v2_dev_record(lane="b", lane_set=["a", "b", "c"]), "dev-report.v2"
    )["ok"]

    assert cr.validate(_valid_v2_dev_record(), "dev-report.v2")["ok"]

    result = cr.validate(
        _valid_v2_dev_record(lane="b", lane_set=[]), "dev-report.v2"
    )
    assert not result["ok"]
    assert "lane_set" in _joined_errors(result)


def test_lane_null_with_null_lane_set_passes():
    assert cr.validate(
        _valid_v2_dev_record(lane=None, lane_set=None), "dev-report.v2"
    )["ok"]


# ---------------------------------------------------------------------------
# AC-9 — registry registration purely additive
# ---------------------------------------------------------------------------


def test_registry_preexisting_entries_unchanged_and_new_entries_present():
    registry = json.loads(
        (REPO_ROOT / "schemas" / "registry.json").read_text(encoding="utf-8")
    )
    entries = list(registry["schemas"].items())
    assert entries[: len(PREEXISTING_REGISTRY_ENTRIES)] == PREEXISTING_REGISTRY_ENTRIES
    for name in NEW_REGISTRY_ENTRIES:
        assert registry["schemas"][name] == f"{name}.json"
        assert isinstance(schema_registry.get_schema(name), dict), name


# ---------------------------------------------------------------------------
# AC-10 (ticket 20261001-161041-r01, this ticket's own AC8) --
# validate_markdown_artifact_for_obligation: direct unit coverage of the
# shared markdown-kind obligation validator both
# hooks/pretool-aggregate-check.py (G3) and
# hooks/subagentstop-artifact-contract-enforce.py (producer-side Stop) call.
# ---------------------------------------------------------------------------


def test_markdown_obligation_file_absent_fails():
    missing = "/nonexistent/path/does-not-exist-ticket.md"
    result = cr.validate_markdown_artifact_for_obligation(missing, "anchor text", "^END$")
    assert result["status"] == "fail"
    assert "artifact_missing" in result["reason"]


def test_markdown_obligation_identity_anchor_absent_fails(tmp_path):
    path = tmp_path / "ticket.md"
    path.write_text("# Doc\nSTATUS: ready\n", encoding="utf-8")
    result = cr.validate_markdown_artifact_for_obligation(
        str(path), "Request ID: 20261001-161041-r01", "^STATUS: ready$"
    )
    assert result["status"] == "fail"
    assert "identity_anchor_missing" in result["reason"]


def test_markdown_obligation_terminal_line_mismatch_fails(tmp_path):
    path = tmp_path / "ticket.md"
    anchor = "Request ID: 20261001-161041-r01"
    path.write_text(f"# Doc\n{anchor}\nNOT-THE-RIGHT-LAST-LINE\n", encoding="utf-8")
    result = cr.validate_markdown_artifact_for_obligation(str(path), anchor, "^STATUS: ready$")
    assert result["status"] == "fail"
    assert "terminal_line_mismatch" in result["reason"]
    assert "identity_anchor" not in result["reason"]


def test_markdown_obligation_all_pass(tmp_path):
    path = tmp_path / "ticket.md"
    anchor = "Request ID: 20261001-161041-r01"
    path.write_text(f"# Doc\n{anchor}\nSTATUS: ready\n", encoding="utf-8")
    result = cr.validate_markdown_artifact_for_obligation(str(path), anchor, "^STATUS: ready$")
    assert result["status"] == "pass"
    assert result["errors"] == []


def test_markdown_obligation_malformed_regex_fail_safe_passes(tmp_path):
    """Fail-safe polarity (Edge Case 2): a malformed terminal_line_regex is
    our own bug, never the artifact's -- matched=True, status stays
    'pass', mirroring _verify_prior_artifact's `except re.error: matched =
    True` precedent exactly (not the opposite polarity)."""
    path = tmp_path / "ticket.md"
    anchor = "Request ID: 20261001-161041-r01"
    path.write_text(f"# Doc\n{anchor}\nANYTHING AT ALL\n", encoding="utf-8")
    result = cr.validate_markdown_artifact_for_obligation(str(path), anchor, "[unclosed(")
    assert result["status"] == "pass"


def test_markdown_obligation_no_identity_anchor_or_regex_declared_passes(tmp_path):
    """Neither identity_anchor nor terminal_line_regex declared (both
    None/absent) -> pass; existence alone is the only enforced condition."""
    path = tmp_path / "ticket.md"
    path.write_text("# Doc\nanything\n", encoding="utf-8")
    result = cr.validate_markdown_artifact_for_obligation(str(path), None, None)
    assert result["status"] == "pass"
