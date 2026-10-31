"""Tests for hooks/lib/obligation.py -- task 20260929-104216-b (rollout S2).

Covers the four implementation ACs of ticket-20260929-104216-b:
- AC1 (-k roundtrip): the pinned §1.2 normalized_example round-trips
  losslessly on all TEN top-level fields;
- AC2 (-k 'reject or failclosed or null'): fail-closed suite with distinct
  named reasons + the task_id-null profile matrix;
- AC3 (-k live_store): REAL-store positive control with dynamic discovery
  (zero discovered pairs is a FAILURE, never a skip);
- AC4 (-k fixture): tmpdir fixture store, both persisted content shapes,
  rungs L0 and L1, distinct unresolvable reasons, role mismatch.

Phase P1 (terminal grammar): TERMINAL_VOCABULARY and PROFILES read from the
schemas (an unreadable schema is no import error), P1b row 18: role and
pipeline read from the agent and command files, artifact kinds and null
task_id profiles from the schema, terminal_status, TASK_ID_RE / schema pattern parity, the closed json kind (no required_values,
no waived_by_response), producer-question.v1 option bounds, the task-id family
helpers and read_first_record_prompt skipping non-message records.

Run with: python3 -m pytest hooks/tests/test_obligation.py -v
"""

import copy
import json
import re
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

# Add repo root to path so we can import hooks.lib.obligation as a module,
# matching hooks/tests/test_agent_resolver.py's convention.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from hooks.lib import obligation  # noqa: E402
from hooks.lib.subagent_restart import (  # noqa: E402
    account_project_roots,
    project_slug,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE_CRITERIA_FILE = (
    REPO_ROOT / "docs" / "dev" / "acceptance-criteria-20260929-104216-b.json"
)

# Byte-identical literal of the canonical machine copy pinned at
# docs/dev/acceptance-criteria-20260929-104216-b.json ->
# acceptance_criteria[0].normalized_example (AC1: "that document or a
# byte-identical literal, never a reinvented concretization").
# test_roundtrip_normalized_example cross-checks equality against the file
# whenever the file is present.
NORMALIZED_EXAMPLE = {
    "task_id": "20260928-153000",
    "lane": "b",
    "lane_set": ["a", "b", "c"],
    "role": "qa",
    "pipeline": "close",
    "profile": "do-close",
    "dispatched_at": "2026-09-28T15:30:05Z",
    "artifacts": [
        {"kind": "json", "path": "docs/dev/dev-report-20260928-153000-b.json",
         "schema": "dev-report.v2",
         "identity": {"task_id": "20260928-153000-b",
                      "request_id": "20260928-153000-b"}},
        {"kind": "markdown", "path": "docs/dev/close-report-20260928-153000.md",
         "identity_anchor": "20260928-153000",
         "terminal_line_regex": "^CLOSE: (YES|NO)",
         "waived_by_response": "^CLOSE_REPORT_APPEND_(ERROR|CRITICAL): "},
        {"kind": "response_block",
         "begin": "--- CHANGELOG-ANALYST-STATUS-BEGIN ---",
         "end": "--- CHANGELOG-ANALYST-STATUS-END ---",
         "format": "json",
         "schema": "changelog-status.v1"},
        {"kind": "response_line",
         "terminal_line_regex": "^COMMIT: (APPROVE|REJECT)"},
    ],
    "consistency": "verdict_class",
    "expected_absent": ["docs/dev/qa-report-20260928-153000.json"],
}


def _example():
    return copy.deepcopy(NORMALIZED_EXAMPLE)


def _prompt_for(doc):
    return (
        "Dispatch preamble text before the block.\n"
        + obligation.serialize_obligation(doc)
        + "\nTrailing dispatch text after the block."
    )


def _parse(doc, **kwargs):
    return obligation.parse_obligation(_prompt_for(doc), **kwargs)


# --------------------------------------------------------------------------
# AC1 -- roundtrip
# --------------------------------------------------------------------------

def test_roundtrip_normalized_example():
    # The embedded literal must stay byte-identical to the canonical machine
    # copy while that file is in the tree.
    if ACCEPTANCE_CRITERIA_FILE.is_file():
        canonical = json.loads(ACCEPTANCE_CRITERIA_FILE.read_text(encoding="utf-8"))
        pinned = canonical["acceptance_criteria"][0]["normalized_example"]
        assert NORMALIZED_EXAMPLE == pinned

    parsed = obligation.parse_obligation(_prompt_for(NORMALIZED_EXAMPLE))
    assert isinstance(parsed, obligation.ParsedObligation)
    assert parsed.undischarged == ()
    doc = parsed.obligation
    assert set(doc) == set(NORMALIZED_EXAMPLE) and len(doc) == 10
    # All TEN top-level field values equal to the pin (AC1 THEN clause).
    assert doc["task_id"] == "20260928-153000"
    assert doc["lane"] == "b"
    assert doc["lane_set"] == ["a", "b", "c"]
    assert doc["role"] == "qa"
    assert doc["pipeline"] == "close"
    assert doc["profile"] == "do-close"
    assert doc["dispatched_at"] == "2026-09-28T15:30:05Z"
    assert doc["artifacts"] == NORMALIZED_EXAMPLE["artifacts"]
    assert doc["consistency"] == "verdict_class"
    assert doc["expected_absent"] == ["docs/dev/qa-report-20260928-153000.json"]
    assert doc == NORMALIZED_EXAMPLE
    # Top-level task_id and the json artifact's identity task_id differ by
    # the lane suffix BY DESIGN -- no equality is imposed between them.
    assert doc["artifacts"][0]["identity"]["task_id"] == "20260928-153000-b"
    assert doc["artifacts"][0]["identity"]["task_id"] != doc["task_id"]


def test_roundtrip_serialize_lossless():
    first = obligation.parse_obligation(_prompt_for(NORMALIZED_EXAMPLE))
    assert isinstance(first, obligation.ParsedObligation)
    # parse(serialize(x)) == x
    again = obligation.parse_obligation(
        obligation.serialize_obligation(first.obligation)
    )
    assert isinstance(again, obligation.ParsedObligation)
    assert again.obligation == first.obligation == NORMALIZED_EXAMPLE


# --------------------------------------------------------------------------
# AC2 -- fail-closed suite (reject / failclosed / null)
# --------------------------------------------------------------------------

def _assert_rejected(result, reason, field=None):
    assert isinstance(result, obligation.Rejection), result
    assert result.reason == reason, (result.reason, result.field, result.detail)
    if field is not None:
        assert result.field == field, (result.reason, result.field)
    return result


def test_reject_wrong_version_v2():
    prompt = _prompt_for(_example()).replace(
        '<obligation v="1">', '<obligation v="2">'
    )
    _assert_rejected(obligation.parse_obligation(prompt), "unsupported_version")


def test_reject_missing_version_attribute():
    prompt = _prompt_for(_example()).replace('<obligation v="1">', "<obligation>")
    _assert_rejected(obligation.parse_obligation(prompt), "unsupported_version")


def test_reject_multiple_blocks():
    block = obligation.serialize_obligation(_example())
    _assert_rejected(
        obligation.parse_obligation(block + "\n" + block), "multiple_blocks"
    )


def test_reject_unterminated_block():
    prompt = obligation.serialize_obligation(_example()).replace(
        "</obligation>", ""
    )
    _assert_rejected(obligation.parse_obligation(prompt), "unterminated_block")


def test_reject_comment_bearing_json():
    # The §1.2 example's // annotations are documentation, NOT grammar.
    prompt = (
        '<obligation v="1">\n'
        '{"task_id": "20260928-153000" // lane-suffix annotation\n'
        "}\n</obligation>"
    )
    _assert_rejected(obligation.parse_obligation(prompt), "malformed_json")


def test_reject_unknown_top_level_field():
    doc = _example()
    doc["surprise"] = "x"
    _assert_rejected(_parse(doc), "unknown_field", field="surprise")


def test_reject_unknown_artifact_field():
    doc = _example()
    doc["artifacts"][0]["bogus"] = "x"
    _assert_rejected(_parse(doc), "unknown_field", field="artifacts[0].bogus")


def test_reject_task_id_null_profile_singular():
    doc = _example()
    doc["task_id"] = None
    doc["profile"] = "singular"
    _assert_rejected(_parse(doc), "task_id_null_illegal", field="task_id")


def test_reject_bad_task_id_shape():
    doc = _example()
    doc["task_id"] = "not-a-task-id"
    _assert_rejected(_parse(doc), "bad_task_id", field="task_id")


def test_reject_lane_outside_lane_set():
    doc = _example()
    doc["lane"] = "z"
    _assert_rejected(_parse(doc), "lane_not_in_lane_set", field="lane")


def test_reject_duplicate_lane_set_members():
    doc = _example()
    doc["lane_set"] = ["a", "a", "b"]
    _assert_rejected(_parse(doc), "lane_set_duplicate", field="lane_set")


def test_reject_unknown_role():
    doc = _example()
    doc["role"] = "wizard"
    _assert_rejected(_parse(doc), "unknown_enum_value", field="role")


def test_reject_unknown_pipeline():
    doc = _example()
    doc["pipeline"] = "ship"
    _assert_rejected(_parse(doc), "unknown_enum_value", field="pipeline")


def test_role_is_an_agent_of_the_roster(tmp_path, monkeypatch):
    # P1b row 18: a role is legal because agents/<role>.md exists with front
    # matter, read when the block is validated; no list here names the roles.
    for role in ("pm", "architect", "ui-specialist", "graphify", "style-inspector"):
        doc = _example()
        doc["role"] = role
        assert isinstance(_parse(doc), obligation.ParsedObligation), role
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "wizard.md").write_text("---\nname: wizard\n---\n", encoding="utf-8")
    (agents / "README.md").write_text("# agents\n", encoding="utf-8")
    monkeypatch.setattr(obligation.roster, "AGENTS_DIR", agents)
    doc = _example()
    doc["role"] = "wizard"
    assert isinstance(_parse(doc), obligation.ParsedObligation)
    for role in ("qa", "README"):
        doc["role"] = role
        _assert_rejected(_parse(doc), "unknown_enum_value", field="role")


def test_pipeline_is_a_command_file(tmp_path, monkeypatch):
    # A pipeline is legal because commands/<pipeline>.md exists with front
    # matter (the roster's rule on the command files), never a literal list.
    for pipeline in ("spec", "redev", "do", "dev-overnight"):
        doc = _example()
        doc["pipeline"] = pipeline
        assert isinstance(_parse(doc), obligation.ParsedObligation), pipeline
    commands = tmp_path / "commands"
    commands.mkdir()
    (commands / "ship.md").write_text("---\ndescription: ship\n---\n", encoding="utf-8")
    (commands / "INDEX.md").write_text("# commands\n", encoding="utf-8")
    monkeypatch.setattr(obligation, "_COMMANDS_DIR", commands)
    doc = _example()
    doc["pipeline"] = "ship"
    assert isinstance(_parse(doc), obligation.ParsedObligation)
    for pipeline in ("close", "INDEX"):
        doc["pipeline"] = pipeline
        _assert_rejected(_parse(doc), "unknown_enum_value", field="pipeline")


def test_missing_agent_or_command_directory_refuses_the_block(tmp_path, monkeypatch):
    # An unreadable roster or command directory makes nothing legal: the gate
    # that validates the block refuses it; nothing raises.
    monkeypatch.setattr(obligation, "_COMMANDS_DIR", tmp_path / "no-commands")
    _assert_rejected(_parse(_example()), "unknown_enum_value", field="pipeline")
    monkeypatch.setattr(obligation.roster, "AGENTS_DIR", tmp_path / "no-agents")
    _assert_rejected(_parse(_example()), "unknown_enum_value", field="role")


def test_artifact_kinds_and_null_task_id_profiles_read_the_schema(tmp_path, monkeypatch):
    # The per-kind field sets and the profiles that may carry a null task_id
    # are the schema's: another schema gives other sets, none gives none.
    schema = json.loads((REPO_ROOT / "schemas" / "obligation.v1.json").read_text(encoding="utf-8"))
    items = schema["properties"]["artifacts"]["items"]
    items["properties"]["kind"]["enum"].append("blob")
    items["allOf"].append({"if": {"properties": {"kind": {"const": "blob"}}, "required": ["kind"]},
                           "then": {"required": ["path"], "properties": {"path": {}, "note": {}}}})
    schema["allOf"][0]["if"]["properties"]["profile"]["not"]["enum"] = ["ad_hoc", "commit-qa"]
    (tmp_path / "obligation.v1.json").write_text(json.dumps(schema), encoding="utf-8")
    monkeypatch.setattr(obligation, "_SCHEMAS_DIR", tmp_path)
    fields = obligation._artifact_fields_by_kind()
    assert fields["blob"] == (("kind", "path"), ("note",))
    assert fields["markdown"] == (("kind", "path", "identity_anchor"),
                                  ("terminal_line_regex", "waived_by_response"))
    assert obligation._null_task_id_profiles() == {"ad_hoc", "commit-qa"}
    monkeypatch.setattr(obligation, "_SCHEMAS_DIR", tmp_path / "absent")
    assert obligation._artifact_fields_by_kind() == {}
    assert obligation._null_task_id_profiles() == frozenset()
    # The shipped schema gives the grammar the design states.
    assert obligation.ARTIFACT_FIELDS_BY_KIND["json"] == (("kind", "path", "schema", "identity"), ())
    assert obligation.NULL_TASK_ID_PROFILES == {"ad_hoc", "commit-bulk"}
    # A file kind (its fields require a path) has the file slack, a response
    # kind none: every declared kind has an entry, spec_views included.
    assert obligation.FRESHNESS_SLACK_SECONDS_BY_KIND == {
        "json": 2, "markdown": 2, "spec_views": 2, "response_block": None, "response_line": None}
    assert obligation.artifact_freshness_satisfied("spec_views", 10**10, "2026-10-28T00:00:00Z") is True


def test_reject_unknown_profile():
    doc = _example()
    doc["profile"] = "mystery"
    _assert_rejected(_parse(doc), "unknown_enum_value", field="profile")


def test_reject_unknown_kind():
    doc = _example()
    doc["artifacts"][0]["kind"] = "binary"
    _assert_rejected(_parse(doc), "unknown_kind", field="artifacts[0].kind")


def test_reject_unknown_format():
    doc = _example()
    doc["artifacts"][2]["format"] = "yaml"
    _assert_rejected(_parse(doc), "unknown_enum_value", field="artifacts[2].format")


def test_reject_unknown_consistency():
    doc = _example()
    doc["consistency"] = "strict"
    _assert_rejected(_parse(doc), "unknown_consistency", field="consistency")


def test_reject_traversal_path():
    doc = _example()
    doc["artifacts"][0]["path"] = "../x"
    _assert_rejected(_parse(doc), "illegal_path", field="artifacts[0].path")


def test_reject_absolute_path():
    doc = _example()
    doc["artifacts"][1]["path"] = "/abs/close-report.md"
    _assert_rejected(_parse(doc), "illegal_path", field="artifacts[1].path")


def test_reject_uncompilable_regex():
    doc = _example()
    doc["artifacts"][3]["terminal_line_regex"] = "([unclosed"
    _assert_rejected(
        _parse(doc), "bad_regex", field="artifacts[3].terminal_line_regex"
    )


def test_reject_empty_identity():
    doc = _example()
    doc["artifacts"][0]["identity"] = {}
    _assert_rejected(_parse(doc), "empty_identity", field="artifacts[0].identity")


def test_reject_unknown_identity_key():
    doc = _example()
    doc["artifacts"][0]["identity"] = {
        "task_id": "20260928-153000-b", "lane": "b",
    }
    _assert_rejected(
        _parse(doc), "unknown_identity_key", field="artifacts[0].identity.lane"
    )


def test_reject_unregistered_schema_with_caller_registry():
    # Membership only against the CALLER-supplied set; None skips it and the
    # library never reads schemas/registry.json itself.
    doc = _example()
    result = _parse(doc, known_schema_ids={"dev-report.v2"})
    _assert_rejected(result, "unregistered_schema", field="artifacts[2].schema")
    assert isinstance(_parse(doc), obligation.ParsedObligation)


def test_reject_reasons_distinct():
    """AC2: every enumerated case carries a distinct (reason, field) pair."""
    cases = {}

    def record(name, result):
        assert isinstance(result, obligation.Rejection), (name, result)
        cases[name] = (result.reason, result.field)

    record("v2", obligation.parse_obligation(
        _prompt_for(_example()).replace('<obligation v="1">', '<obligation v="2">')))
    record("multiple", obligation.parse_obligation(
        obligation.serialize_obligation(_example()) * 2))
    record("comments", obligation.parse_obligation(
        '<obligation v="1">\n{"a": 1 // c\n}\n</obligation>'))
    for name, mutate in (
        ("unknown_top_level", lambda d: d.__setitem__("surprise", "x")),
        ("unknown_artifact_field", lambda d: d["artifacts"][0].__setitem__("bogus", "x")),
        ("task_id_null_singular", lambda d: (d.__setitem__("task_id", None),
                                             d.__setitem__("profile", "singular"))),
        ("bad_task_id", lambda d: d.__setitem__("task_id", "nope")),
        ("lane_outside", lambda d: d.__setitem__("lane", "z")),
        ("lane_set_dup", lambda d: d.__setitem__("lane_set", ["a", "a", "b"])),
        ("role", lambda d: d.__setitem__("role", "wizard")),
        ("pipeline", lambda d: d.__setitem__("pipeline", "ship")),
        ("profile", lambda d: d.__setitem__("profile", "mystery")),
        ("kind", lambda d: d["artifacts"][0].__setitem__("kind", "binary")),
        ("format", lambda d: d["artifacts"][2].__setitem__("format", "yaml")),
        ("consistency", lambda d: d.__setitem__("consistency", "strict")),
        ("traversal", lambda d: d["artifacts"][0].__setitem__("path", "../x")),
        ("absolute", lambda d: d["artifacts"][1].__setitem__("path", "/abs")),
        ("regex", lambda d: d["artifacts"][3].__setitem__(
            "terminal_line_regex", "([unclosed")),
        ("empty_identity", lambda d: d["artifacts"][0].__setitem__("identity", {})),
        ("identity_key", lambda d: d["artifacts"][0].__setitem__(
            "identity", {"task_id": "20260928-153000-b", "lane": "b"})),
    ):
        doc = _example()
        mutate(doc)
        record(name, _parse(doc))
    assert len(cases) >= 15
    assert len(set(cases.values())) == len(cases), cases


def test_null_task_id_commit_qa_accepted_with_undischarged_flag():
    doc = _example()
    doc["task_id"] = None
    doc["profile"] = "commit-qa"
    parsed = _parse(doc)
    assert isinstance(parsed, obligation.ParsedObligation)
    assert parsed.undischarged == ("task_id_null_requires_bulk_context",)


def test_null_task_id_ad_hoc_accepted_cleanly():
    doc = _example()
    doc["task_id"] = None
    doc["profile"] = "ad_hoc"
    parsed = _parse(doc)
    assert isinstance(parsed, obligation.ParsedObligation)
    assert parsed.undischarged == ()


def test_null_task_id_commit_bulk_accepted_cleanly():
    doc = _example()
    doc["task_id"] = None
    doc["profile"] = "commit-bulk"
    parsed = _parse(doc)
    assert isinstance(parsed, obligation.ParsedObligation)
    assert parsed.undischarged == ()


def test_failclosed_no_block_vs_multiple_blocks_distinct():
    # Zero blocks is the TYPED NoBlock outcome, not a rejection; more than
    # one opener is the multiple_blocks rejection. Never conflated.
    none = obligation.parse_obligation("plain dispatch prompt, no block")
    assert isinstance(none, obligation.NoBlock)
    many = obligation.parse_obligation(
        obligation.serialize_obligation(_example()) * 2
    )
    assert isinstance(many, obligation.Rejection)
    assert many.reason == "multiple_blocks"


# --------------------------------------------------------------------------
# Pure helper coverage (S1)
# --------------------------------------------------------------------------

def test_dispatch_clock_bound_is_pure_and_parameterized():
    dispatched = "2026-09-28T15:30:05Z"
    now = datetime(2026, 9, 28, 15, 30, 5, tzinfo=timezone.utc)
    assert obligation.dispatch_clock_within_bound(dispatched, now) is True
    assert obligation.dispatch_clock_within_bound(
        dispatched, now + timedelta(seconds=300)) is True
    assert obligation.dispatch_clock_within_bound(
        dispatched, now + timedelta(seconds=301)) is False
    assert obligation.dispatch_clock_within_bound(
        dispatched, now - timedelta(seconds=301)) is False
    assert obligation.dispatch_clock_within_bound(
        dispatched, now + timedelta(seconds=301), bound_seconds=400) is True
    assert obligation.dispatch_clock_within_bound("garbage", now) is None
    assert obligation.DISPATCH_CLOCK_BOUND_SECONDS == 300


def test_artifact_freshness_per_kind():
    dispatched = "2026-09-28T15:30:05Z"
    base = datetime(2026, 9, 28, 15, 30, 5, tzinfo=timezone.utc)
    for kind in ("json", "markdown"):
        assert obligation.artifact_freshness_satisfied(
            kind, base - timedelta(seconds=1), dispatched) is True  # within 2s slack
        assert obligation.artifact_freshness_satisfied(
            kind, base - timedelta(seconds=3), dispatched) is False
        assert obligation.artifact_freshness_satisfied(
            kind, (base + timedelta(seconds=60)).timestamp(), dispatched) is True
    for kind in ("response_block", "response_line"):
        assert obligation.artifact_freshness_satisfied(
            kind, base - timedelta(days=365), dispatched) is True
    assert obligation.artifact_freshness_satisfied("binary", base, dispatched) is None
    assert obligation.FILE_FRESHNESS_SLACK_SECONDS == 2


def test_lane_set_roster_equality_helper():
    assert obligation.lane_sets_identical(["a", "b"], ["a", "b"]) is True
    assert obligation.lane_sets_identical(["a", "b"], ["b", "a"]) is False
    assert obligation.lane_sets_identical(None, None) is True
    assert obligation.lane_sets_identical(["a"], None) is False


# --------------------------------------------------------------------------
# P1 grammar: vocabulary read from the schemas, task-id parity, closed json kind
# --------------------------------------------------------------------------

SCHEMAS_DIR = REPO_ROOT / "schemas"
TS = "20261019-104500"
TASK_IDS_ACCEPTED = (
    f"dev-{TS}", f"dev-{TS}-l6", f"dev-command-{TS}-l2", TS, f"{TS}-3",
)
TASK_IDS_REJECTED = ("not-a-task-id", "dev-command-x", f"dev-{TS[:8]}")


def _schema(schema_id):
    return json.loads(
        (SCHEMAS_DIR / f"{schema_id}.json").read_text(encoding="utf-8")
    )


def _enum_at(schema, dotted):
    """The enum at a dotted path, walked through ``properties``."""
    node = schema
    for part in dotted.split("."):
        node = node["properties"][part]
    return node["enum"]


def test_schema_enum_reads_the_schema_file_it_names(tmp_path, monkeypatch):
    # The values come from the schema on disk, not from a copy: a schema with
    # another enum gives another set, a missing file or path gives none.
    (tmp_path / "x.v1.json").write_text(json.dumps({"properties": {"a": {
        "type": "object", "properties": {"b": {"enum": ["one", "two", 3]}}}}}))
    (tmp_path / "broken.v1.json").write_text("{not json")
    monkeypatch.setattr(obligation, "_SCHEMAS_DIR", tmp_path)
    assert obligation._schema_enum("x.v1", "a.b") == {"one", "two"}
    assert obligation._schema_enum("x.v1", "a.c") == frozenset()
    assert obligation._schema_enum("broken.v1", "a.b") == frozenset()
    assert obligation._schema_enum("absent.v1", "a.b") == frozenset()


def test_unreadable_schemas_are_no_import_error(tmp_path):
    # A harness tree without its schemas: the module still imports, nothing is
    # terminal and no profile is legal, so the gate that reads one refuses it.
    import shutil
    import subprocess

    lib = tmp_path / "hooks" / "lib"
    lib.mkdir(parents=True)
    for source in (REPO_ROOT / "hooks" / "lib").glob("*.py"):
        shutil.copy(source, lib / source.name)
    probe = (
        "import json, sys; sys.path.insert(0, sys.argv[1]); import obligation as o; "
        "r = o.validate_obligation(json.loads(sys.argv[2])); "
        "print(json.dumps({'vocabulary': {k: {p: sorted(v) for p, v in d.items()} "
        "for k, d in o.TERMINAL_VOCABULARY.items()}, 'profiles': sorted(o.PROFILES), "
        "'kinds': sorted(o.ARTIFACT_KINDS), 'null': sorted(o.NULL_TASK_ID_PROFILES), "
        "'refusal': [r.reason, r.field], "
        "'status': o.terminal_status('do-report.v1', {'do': {'status': 'completed'}})}))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe, str(lib), json.dumps(NORMALIZED_EXAMPLE)],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=60)
    assert proc.returncode == 0, proc.stderr
    seen = json.loads(proc.stdout)
    assert seen["vocabulary"] and all(
        paths == {dotted: [] for dotted in paths} for paths in seen["vocabulary"].values())
    assert seen["profiles"] == [] and seen["status"] is None
    # Nor any agent or command directory: no kind, no null task_id profile,
    # and the block's role is refused by the gate that validates it.
    assert seen["kinds"] == [] and seen["null"] == []
    assert seen["refusal"] == ["unknown_enum_value", "role"]


@pytest.mark.parametrize("record, expected", [
    ({"do": {"status": "completed"}}, "completed"),
    ({"do": {"status": "blocked"}}, "blocked"),
    ({"do": {"status": "pending"}}, None),
    ({"do": {"status": "in_progress"}}, None),
    ({"do": {}}, None),
    ({"do": "completed"}, None),
    ({"status": "completed"}, None),
    ("not a record", None),
])
def test_terminal_status_of_a_do_report(record, expected):
    assert obligation.terminal_status("do-report.v1", record) == expected


def test_terminal_status_reads_each_declared_field():
    assert obligation.terminal_status("dev-report.v2", {"dev": {"status": "completed"}}) == "completed"
    assert obligation.terminal_status("dev-report.v2", {"dev": {"status": "blocked"}}) is None
    assert obligation.terminal_status("dev-report.v1", {"status": "completed"}) == "completed"
    assert obligation.terminal_status("qa-report.v2", {"qa": {"status": "warning"}}) == "warning"
    assert obligation.terminal_status("ba-qa-report.v1", {"verdict": "fail"}) == "fail"
    assert obligation.terminal_status("no-such-report.v1", {"status": "completed"}) is None


def test_do_report_vocabulary_has_no_pending():
    # E8: nothing writes a pending do-report, so the schema declares no pending.
    assert "pending" not in obligation.TERMINAL_VOCABULARY["do-report.v1"]["do.status"]
    assert "pending" not in _enum_at(_schema("do-report.v1"), "do.status")


def test_terminal_vocabulary_dev_report_single_completed_status():
    v2 = obligation.TERMINAL_VOCABULARY["dev-report.v2"]["dev.status"]
    v1 = obligation.TERMINAL_VOCABULARY["dev-report.v1"]["status"]
    assert v2 == v1 == {"completed"}
    assert (
        set(_enum_at(_schema("dev-report.v2"), "dev.status"))
        == set(_enum_at(_schema("dev-report.v1"), "status"))
        == {"completed"}
    )


def test_task_id_pattern_parity_with_schema():
    import jsonschema

    task_id_schema = _schema("obligation.v1")["properties"]["task_id"]
    assert obligation.TASK_ID_RE.pattern == task_id_schema["pattern"]
    validator = jsonschema.Draft7Validator(task_id_schema)
    for value in TASK_IDS_ACCEPTED:
        assert obligation.TASK_ID_RE.fullmatch(value), value
        assert validator.is_valid(value), value
        doc = _example()
        doc["task_id"] = value
        assert isinstance(_parse(doc), obligation.ParsedObligation), value
    for value in TASK_IDS_REJECTED:
        assert not obligation.TASK_ID_RE.fullmatch(value), value
        assert not validator.is_valid(value), value
        doc = _example()
        doc["task_id"] = value
        _assert_rejected(_parse(doc), "bad_task_id", field="task_id")


def test_reject_json_artifact_required_values():
    import jsonschema

    doc = _example()
    doc["artifacts"][0]["required_values"] = {"dev.status": ["completed"]}
    _assert_rejected(
        _parse(doc), "unknown_field", field="artifacts[0].required_values"
    )
    validator = jsonschema.Draft7Validator(_schema("obligation.v1"))
    assert validator.is_valid(_example())
    assert not validator.is_valid(doc)


def test_reject_json_artifact_waived_by_response():
    doc = _example()
    doc["artifacts"][0]["waived_by_response"] = (
        "^CLOSE_REPORT_APPEND_(ERROR|CRITICAL): "
    )
    _assert_rejected(
        _parse(doc), "unknown_field", field="artifacts[0].waived_by_response"
    )
    # The markdown kind keeps it as its optional field.
    assert "waived_by_response" in NORMALIZED_EXAMPLE["artifacts"][1]
    assert isinstance(_parse(_example()), obligation.ParsedObligation)


def test_producer_question_options_two_to_four():
    import jsonschema

    registry = json.loads(
        (SCHEMAS_DIR / "registry.json").read_text(encoding="utf-8")
    )["schemas"]
    assert registry.get("producer-question.v1") == "producer-question.v1.json"
    schema = _schema("producer-question.v1")
    options = schema["properties"]["options"]
    assert options["minItems"] == 2
    assert options["maxItems"] == 4
    validator = jsonschema.Draft7Validator(schema)

    def question(count):
        return {
            "task_id": TS,
            "role": "dev",
            "need": "which default applies",
            "options": [
                {"label": f"option-{n}", "description": f"choice {n}"}
                for n in range(count)
            ],
            "default": "option-0",
            "why": "the request and the code leave it open",
        }

    assert [validator.is_valid(question(n)) for n in (1, 2, 3, 4, 5)] == [
        False, True, True, True, False,
    ]


def test_canonical_task_id_strips_minted_prefix():
    canonical = obligation.canonical_task_id
    assert canonical(f"dev-{TS}") == TS
    assert canonical(f"dev-{TS}-l6") == f"{TS}-l6"
    assert canonical(f"dev-command-{TS}") == TS
    assert canonical(f"dev-command-{TS}-l2") == f"{TS}-l2"
    assert canonical(TS) == TS
    assert canonical(f"{TS}-3") == f"{TS}-3"
    assert canonical(f"{TS}-l1") == f"{TS}-l1"
    # A dev- prefix not followed by a stamp is not a minted prefix.
    assert canonical("dev-command-x") == "dev-command-x"
    assert canonical("dev-fix") == "dev-fix"
    for value in (None, "", 7, [f"dev-{TS}"]):
        assert canonical(value) is None, value


def test_task_family_drops_lane_suffix_only():
    family = obligation.task_family
    assert family(TS) == TS
    assert family(f"dev-{TS}") == TS
    assert family(f"dev-{TS}-l2") == TS
    assert family(f"dev-command-{TS}-l3") == TS
    assert family(f"{TS}-l1") == family(f"dev-{TS}-l2")
    # Overnight pipelines <ts>-1 / <ts>-2 stay separate families.
    assert family(f"{TS}-1") == f"{TS}-1"
    assert family(f"{TS}-2") == f"{TS}-2"
    assert family(f"{TS}-1") != family(f"{TS}-2")
    assert family(f"{TS}-b") == f"{TS}-b"
    for value in (None, "", 7):
        assert family(value) is None, value


def test_registry_dir_for_every_branch(tmp_path):
    registry_dir_for = obligation.registry_dir_for
    root = tmp_path / ".claude" / "dev-registry"
    dev_dir = root / f"dev-{TS}"
    command_dir = root / f"dev-command-{TS}"

    # No timestamp, or not a string: None.
    for value in (None, 42, "", "not-a-task-id", "dev-command-x", "dev-fix"):
        assert registry_dir_for(tmp_path, value) is None, value

    # Nothing on disk: a minted prefix keeps its directory (lane suffix is not
    # part of the name); a bare <ts> id defaults to dev-<ts>.
    assert registry_dir_for(tmp_path, f"dev-command-{TS}") == command_dir
    assert registry_dir_for(tmp_path, f"dev-command-{TS}-l2") == command_dir
    assert registry_dir_for(tmp_path, f"dev-{TS}") == dev_dir
    assert registry_dir_for(tmp_path, f"dev-{TS}-l2") == dev_dir
    assert registry_dir_for(tmp_path, TS) == dev_dir
    assert registry_dir_for(tmp_path, f"{TS}-3") == dev_dir

    # A regular file is not a registry directory.
    root.mkdir(parents=True)
    command_dir.write_text("", encoding="utf-8")
    assert registry_dir_for(tmp_path, TS) == dev_dir
    command_dir.unlink()

    # Only dev-command-<ts> exists: a bare id resolves to it; dev- keeps dev-.
    command_dir.mkdir()
    assert registry_dir_for(tmp_path, TS) == command_dir
    assert registry_dir_for(tmp_path, f"{TS}-l2") == command_dir
    assert registry_dir_for(str(tmp_path), TS) == command_dir
    assert registry_dir_for(tmp_path, f"dev-{TS}") == dev_dir
    assert registry_dir_for(tmp_path, f"dev-{TS}-l2") == dev_dir

    # Both exist: dev- first; dev-command- ids keep their own directory.
    dev_dir.mkdir()
    assert registry_dir_for(tmp_path, TS) == dev_dir
    assert registry_dir_for(tmp_path, f"dev-command-{TS}") == command_dir

    # Only dev-<ts> exists.
    command_dir.rmdir()
    assert registry_dir_for(tmp_path, TS) == dev_dir
    assert registry_dir_for(tmp_path, f"dev-command-{TS}-l1") == command_dir


# --------------------------------------------------------------------------
# AC3 -- live_store positive control (read-only, dynamic discovery)
# --------------------------------------------------------------------------

def _build_live_store(config_dir, project_dir):
    """Write a session store under ``<config_dir>/projects`` in the persisted
    shapes (see _build_fixture_store): parent session JSONL whose Agent
    tool_use carries the prompt, and subagents/agent-*.jsonl with its
    .meta.json. The dispatch prompts carry no obligation block."""
    slug_dir = Path(config_dir) / "projects" / project_slug(project_dir)
    for session_n, agent_n in ((1, 1), (1, 2), (2, 1)):
        session_id = "sess-live-%04d" % session_n
        agent_id = "liveagent%04d%04d" % (session_n, agent_n)
        tool_use_id = "toolu_live_%04d_%04d" % (session_n, agent_n)
        prompt = "FIRST ACTION: live-shape dispatch %s with no obligation block." % agent_id
        subagents = slug_dir / session_id / "subagents"
        subagents.mkdir(parents=True, exist_ok=True)
        parent_record = {
            "type": "assistant",
            "message": {"content": [{
                "type": "tool_use",
                "id": tool_use_id,
                "name": "Agent",
                "input": {"prompt": prompt, "subagent_type": "dev"},
            }]},
        }
        with open(slug_dir / f"{session_id}.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(parent_record) + "\n")
        content = prompt if agent_n % 2 else [{"type": "text", "text": prompt}]
        transcript = subagents / f"agent-{agent_id}.jsonl"
        transcript.write_text(
            json.dumps({"type": "user", "message": {"content": content}}) + "\n",
            encoding="utf-8",
        )
        meta = {
            "agentType": "dev",
            "description": "live-shape",
            "requestNonInteractive": True,
            "requestShape": "prompt",
            "spawnDepth": 1,
            "toolUseId": tool_use_id,
        }
        transcript.with_name(f"agent-{agent_id}.meta.json").write_text(
            json.dumps(meta), encoding="utf-8"
        )


def test_live_store_positive_control(tmp_path, monkeypatch):
    """>=1 (session, agent) pair in the store under the configuration
    directory must resolve its verbatim first-record dispatch prompt with a
    successful meta toolUseId cross-check and the typed
    no_obligation_in_prompt outcome. Zero discovered pairs is a test
    FAILURE, never a skip. The store is synthetic, written under the
    hermetic CLAUDE_CONFIG_DIR; the sibling-account root (read at import)
    is pinned to an empty tmp_path so only that store is discovered."""
    config_dir = tmp_path / "config"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    accounts_root = tmp_path / "accounts"
    accounts_root.mkdir()
    monkeypatch.setenv("CLAUDE_RESTART_ACCOUNTS_ROOT", str(accounts_root))
    monkeypatch.setitem(account_project_roots.__globals__, "ACCOUNTS_ROOT", accounts_root)
    _build_live_store(config_dir, REPO_ROOT)
    roots = account_project_roots()
    assert roots == [config_dir / "projects"]
    assert roots, (
        "positive control violated: account_project_roots() returned no "
        "roots on this machine"
    )
    slug = project_slug(REPO_ROOT)
    pairs = []
    for root in roots:
        slug_dir = Path(root) / slug
        if not slug_dir.is_dir():
            continue
        try:
            session_dirs = sorted(p for p in slug_dir.iterdir() if p.is_dir())
        except OSError:
            continue
        for session_dir in session_dirs:
            subagents = session_dir / "subagents"
            if not subagents.is_dir():
                continue
            try:
                transcripts = sorted(subagents.glob("agent-*.jsonl"))
            except OSError:
                continue
            for transcript in transcripts:
                meta = transcript.with_name(transcript.stem + ".meta.json")
                if meta.is_file():
                    agent_id = transcript.stem[len("agent-"):]
                    pairs.append((session_dir.name, agent_id))
    assert pairs, (
        "positive control violated: zero (session, agent) pairs "
        "discovered under %r across %d roots" % (slug, len(roots))
    )
    max_attempts = 25  # live store races live sessions; first pairs suffice
    successes = 0
    outcomes_seen = []
    for session_id, agent_id in pairs[:max_attempts]:
        outcome = obligation.resolve_own_obligation(session_id, agent_id, REPO_ROOT)
        outcomes_seen.append((session_id, agent_id, getattr(outcome, "outcome", "?"),
                              getattr(outcome, "reason", "")))
        if not isinstance(outcome, obligation.NoObligationInPrompt):
            continue
        if outcome.cross_check != obligation.CROSS_CHECK_OK:
            continue
        assert outcome.rung == "L1"
        # Verbatim first-record check: independent re-read must equal the
        # prompt the resolver returned.
        reread = obligation.read_first_record_prompt(outcome.transcript_path)
        assert reread == outcome.prompt
        assert outcome.prompt.strip()
        successes += 1
        break
    assert successes >= 1, (
        "positive control violated: no store pair resolved with cross_check=ok "
        "within the first %d of %d discovered pairs; outcomes: %r"
        % (max_attempts, len(pairs), outcomes_seen)
    )


# --------------------------------------------------------------------------
# AC4 -- fixture store (both content shapes, L0/L1, fail-closed reasons)
# --------------------------------------------------------------------------

def _build_fixture_store(
    tmp_path,
    content_shape="string",
    meta_tool_use_id=None,
    include_block=True,
):
    """Replicate the measured live store shapes byte-shape-for-byte-shape:
    parent JSONL with an Agent tool_use carrying input.prompt; subagents dir;
    meta.json with toolUseId; first record type=user with the prompt as
    string or as content-block list."""
    tool_use_id = "toolu_fixture_0001"
    project = tmp_path / "proj"
    project.mkdir(parents=True)
    root = tmp_path / "store-root"
    slug_dir = root / project_slug(project)
    session_id = "sess-fixture-0001"
    agent_id = "fixtureagent0001"
    subagents = slug_dir / session_id / "subagents"
    subagents.mkdir(parents=True)
    doc = copy.deepcopy(NORMALIZED_EXAMPLE)
    if include_block:
        prompt = (
            "FIRST ACTION: fixture dispatch preamble.\n"
            + obligation.serialize_obligation(doc)
            + "\nFixture trailer."
        )
    else:
        prompt = "FIRST ACTION: fixture dispatch with no obligation block."
    parent_record = {
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_use",
            "id": tool_use_id,
            "name": "Agent",
            "input": {"prompt": prompt, "subagent_type": "qa"},
        }]},
    }
    (slug_dir / f"{session_id}.jsonl").write_text(
        json.dumps(parent_record) + "\n", encoding="utf-8"
    )
    if content_shape == "string":
        content = prompt
    else:
        content = [{"type": "text", "text": prompt}]
    first_record = {"type": "user", "message": {"content": content}}
    transcript = subagents / f"agent-{agent_id}.jsonl"
    transcript.write_text(json.dumps(first_record) + "\n", encoding="utf-8")
    meta = {
        "agentType": "qa",
        "description": "fixture",
        "requestNonInteractive": True,
        "requestShape": "prompt",
        "spawnDepth": 1,
        "toolUseId": meta_tool_use_id or tool_use_id,
    }
    transcript.with_name(f"agent-{agent_id}.meta.json").write_text(
        json.dumps(meta), encoding="utf-8"
    )
    return SimpleNamespace(
        project=project, root=root, session_id=session_id,
        agent_id=agent_id, transcript=transcript, prompt=prompt, doc=doc,
    )


def test_fixture_resolves_string_shape_at_rung_l1(tmp_path):
    fx = _build_fixture_store(tmp_path, content_shape="string")
    outcome = obligation.resolve_own_obligation(
        fx.session_id, fx.agent_id, fx.project, roots=[fx.root]
    )
    assert isinstance(outcome, obligation.Resolved)
    assert outcome.rung == "L1"
    assert outcome.cross_check == obligation.CROSS_CHECK_OK
    assert outcome.obligation == fx.doc
    assert outcome.prompt == fx.prompt
    assert outcome.undischarged == ()


def test_fixture_resolves_blocklist_shape_at_rung_l1(tmp_path):
    fx = _build_fixture_store(tmp_path, content_shape="blocks")
    outcome = obligation.resolve_own_obligation(
        fx.session_id, fx.agent_id, fx.project, roots=[fx.root]
    )
    assert isinstance(outcome, obligation.Resolved)
    assert outcome.rung == "L1"
    assert outcome.cross_check == obligation.CROSS_CHECK_OK
    assert outcome.obligation == fx.doc
    assert outcome.prompt == fx.prompt


def test_fixture_resolves_at_rung_l0_with_direct_path(tmp_path):
    fx = _build_fixture_store(tmp_path)
    outcome = obligation.resolve_own_obligation(
        fx.session_id, fx.agent_id, fx.project,
        payload_agent_transcript_path=fx.transcript, roots=[fx.root],
    )
    assert isinstance(outcome, obligation.Resolved)
    assert outcome.rung == "L0"
    assert outcome.cross_check == obligation.CROSS_CHECK_OK
    assert outcome.obligation == fx.doc


def test_fixture_nonexistent_agent_unresolvable(tmp_path):
    fx = _build_fixture_store(tmp_path)
    outcome = obligation.resolve_own_obligation(
        fx.session_id, "missingagent9999", fx.project, roots=[fx.root]
    )
    assert isinstance(outcome, obligation.Unresolvable)
    assert outcome.reason == "agent_transcript_not_found"


def test_fixture_wrong_session_unresolvable(tmp_path):
    fx = _build_fixture_store(tmp_path)
    outcome = obligation.resolve_own_obligation(
        "sess-absent-9999", fx.agent_id, fx.project, roots=[fx.root]
    )
    assert isinstance(outcome, obligation.Unresolvable)
    assert outcome.reason == "session_not_found"


def test_fixture_meta_tool_use_mismatch_unresolvable(tmp_path):
    fx = _build_fixture_store(tmp_path, meta_tool_use_id="toolu_absent_9999")
    outcome = obligation.resolve_own_obligation(
        fx.session_id, fx.agent_id, fx.project, roots=[fx.root]
    )
    assert isinstance(outcome, obligation.Unresolvable)
    assert outcome.reason == "meta_tool_use_mismatch"


def test_fixture_unresolvable_reasons_are_distinct(tmp_path):
    fx = _build_fixture_store(tmp_path)
    reasons = {
        obligation.resolve_own_obligation(
            fx.session_id, "missingagent9999", fx.project, roots=[fx.root]
        ).reason,
        obligation.resolve_own_obligation(
            "sess-absent-9999", fx.agent_id, fx.project, roots=[fx.root]
        ).reason,
    }
    fx_mismatch = _build_fixture_store(
        tmp_path / "second", meta_tool_use_id="toolu_absent_9999"
    )
    reasons.add(obligation.resolve_own_obligation(
        fx_mismatch.session_id, fx_mismatch.agent_id, fx_mismatch.project,
        roots=[fx_mismatch.root],
    ).reason)
    assert len(reasons) == 3, reasons


def test_fixture_role_mismatch_rejected(tmp_path):
    fx = _build_fixture_store(tmp_path)  # obligation role is "qa"
    outcome = obligation.resolve_own_obligation(
        fx.session_id, fx.agent_id, fx.project,
        expected_role="dev", roots=[fx.root],
    )
    assert isinstance(outcome, obligation.Unresolvable)
    assert outcome.reason == "role_mismatch"
    matching = obligation.resolve_own_obligation(
        fx.session_id, fx.agent_id, fx.project,
        expected_role="qa", roots=[fx.root],
    )
    assert isinstance(matching, obligation.Resolved)


def test_fixture_no_obligation_prompt_is_distinct_outcome(tmp_path):
    # No-block and no-correlation MUST be distinct (binding contract).
    fx = _build_fixture_store(tmp_path, include_block=False)
    outcome = obligation.resolve_own_obligation(
        fx.session_id, fx.agent_id, fx.project, roots=[fx.root]
    )
    assert isinstance(outcome, obligation.NoObligationInPrompt)
    assert not isinstance(outcome, obligation.Unresolvable)
    assert outcome.cross_check == obligation.CROSS_CHECK_OK
    assert outcome.prompt == fx.prompt


# --------------------------------------------------------------------------
# P1: read_first_record_prompt skips records that carry no message
# --------------------------------------------------------------------------

_CLI_SESSION_ID = "5d0c6e2a-7f3b-4c1e-9a52-1f0e8d4b2c77"
_CLI_AGENT_ID = "a3f1c2d4e5b6a7980"


def _cli_record(record_type, index, **fields):
    """A subagent-transcript record in the CLI 2.1.303 envelope."""
    record = {
        "parentUuid": None if index == 0 else f"uuid-{index - 1:04d}",
        "isSidechain": True,
        "agentId": _CLI_AGENT_ID,
        "type": record_type,
        "uuid": f"uuid-{index:04d}",
        "timestamp": f"2026-10-19T10:45:{index:02d}.000Z",
        "userType": "external",
        "entrypoint": "cli",
        "cwd": "/opt/demo/toyproj",
        "sessionId": _CLI_SESSION_ID,
        "version": "2.1.303",
        "gitBranch": "master",
    }
    record.update(fields)
    return record


def _queue_operation(operation, **fields):
    return {
        "type": "queue-operation",
        "operation": operation,
        "timestamp": "2026-10-19T10:44:59.000Z",
        "sessionId": _CLI_SESSION_ID,
        **fields,
    }


def _attachment(index):
    return _cli_record(
        "attachment", index,
        attachment={
            "type": "deferred_tools_delta",
            "addedNames": ["WebFetch"],
            "addedLines": ["WebFetch"],
            "removedNames": [],
        },
    )


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def test_read_first_record_prompt_skips_queue_operation_and_attachment(tmp_path):
    prompt = "FIRST ACTION: read the brief.\nDispatch body."
    leading = [
        _queue_operation("enqueue", content=prompt),
        _queue_operation("dequeue"),
        _attachment(0),
        _attachment(1),
    ]
    user_record = _cli_record(
        "user", 2, promptId="prompt-0001",
        message={"role": "user", "content": prompt},
    )
    later = [
        _attachment(3),
        _cli_record("user", 4, isMeta=True,
                    message={"role": "user", "content": "meta body"}),
        _cli_record("assistant", 5, message={
            "role": "assistant",
            "content": [{"type": "text", "text": "working"}],
        }),
    ]
    string_shape = _write_jsonl(
        tmp_path / "string.jsonl", leading + [user_record] + later
    )
    assert obligation.read_first_record_prompt(string_shape) == prompt

    block_record = copy.deepcopy(user_record)
    block_record["message"]["content"] = [{"type": "text", "text": prompt}]
    block_shape = _write_jsonl(
        tmp_path / "blocks.jsonl", leading + [block_record] + later
    )
    assert obligation.read_first_record_prompt(block_shape) == prompt

    # The resolver reads the same first message record at rung L1.
    fx = _build_fixture_store(tmp_path / "store")
    records = [json.loads(line) for line in
               fx.transcript.read_text(encoding="utf-8").splitlines()]
    _write_jsonl(fx.transcript, leading + records)
    outcome = obligation.resolve_own_obligation(
        fx.session_id, fx.agent_id, fx.project, roots=[fx.root]
    )
    assert isinstance(outcome, obligation.Resolved)
    assert outcome.rung == "L1"
    assert outcome.prompt == fx.prompt
    assert outcome.obligation == fx.doc


def test_read_first_record_prompt_assistant_first_message_is_none(tmp_path):
    transcript = _write_jsonl(tmp_path / "assistant-first.jsonl", [
        _queue_operation("enqueue", content="queued"),
        _queue_operation("dequeue"),
        _attachment(0),
        _cli_record("assistant", 1, message={
            "role": "assistant",
            "content": [{"type": "text", "text": "I start without a prompt."}],
        }),
        _cli_record("user", 2, message={
            "role": "user", "content": "a later user prompt",
        }),
    ])
    assert obligation.read_first_record_prompt(transcript) is None
    only_leading = _write_jsonl(tmp_path / "no-message.jsonl", [
        _queue_operation("enqueue", content="queued"),
        _attachment(0),
    ])
    assert obligation.read_first_record_prompt(only_leading) is None


# --------------------------------------------------------------------------
# dispatch_obligations: the dispatch-record walk (P1b row 3)
# --------------------------------------------------------------------------

def test_dispatch_obligations_walks_the_records_and_judges_nothing(tmp_path):
    """Each Agent/Task dispatch record whose prompt carries a well-formed
    obligation, in record order, with its call's id, line and subagent_type.
    A malformed block, a dispatch without one, another tool's call and an
    unreadable transcript contribute nothing; no declared artifact is read
    (none of the declared paths exists)."""
    good = _example()
    second = dict(_example(), task_id="20260928-153000-c")
    malformed = dict(_example())
    del malformed["profile"]

    def dispatch(use_id, name, prompt, subagent_type="dev"):
        return {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": use_id, "name": name,
             "input": {"subagent_type": subagent_type, "prompt": prompt}}]}}

    transcript = tmp_path / "session.jsonl"
    _write_jsonl(transcript, [
        {"type": "user", "message": {"role": "user", "content": "/dev build it"}},
        dispatch("toolu_a", "Agent", _prompt_for(good)),
        dispatch("toolu_b", "Agent", "no block in this prompt"),
        dispatch("toolu_c", "Agent", _prompt_for(malformed)),
        dispatch("toolu_d", "Bash", _prompt_for(good)),
        dispatch("toolu_e", "Task", _prompt_for(second), subagent_type="qa"),
    ])

    found = obligation.dispatch_obligations(transcript)

    assert [(f["tool_use_id"], f["line"], f["subagent_type"]) for f in found] == [
        ("toolu_a", 2, "dev"), ("toolu_e", 6, "qa")]
    assert [f["obligation"]["task_id"] for f in found] == [good["task_id"], "20260928-153000-c"]
    assert obligation.dispatch_obligations(tmp_path / "absent.jsonl") == []


# --------------------------------------------------------------------------
# AC6 residual (QA round-2 advisory): bare import-form confinement
# --------------------------------------------------------------------------

def test_bare_import_form_confined_to_own_test():
    """The binding AC6 grep covers packaged/relative import forms; this
    covers the residual bare forms reachable after a sys.path insertion
    (the hooks/prompt-workflow.py:36 pattern). Patterns are assembled from
    fragments so this file never matches itself."""
    module_word = "obligation"
    bare_patterns = [
        re.compile(r"^\s*import\s+" + module_word + r"\b"),
        re.compile(r"^\s*from\s+" + module_word + r"\s+import\b"),
    ]
    own_path = Path(__file__).resolve()
    offenders = []
    for base in ("hooks", "scripts", "tests"):
        base_dir = REPO_ROOT / base
        if not base_dir.is_dir():
            continue
        for path in sorted(base_dir.rglob("*.py")):
            if path.resolve() == own_path:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                if any(pattern.search(line) for pattern in bare_patterns):
                    offenders.append(str(path))
                    break
    assert offenders == [], offenders
