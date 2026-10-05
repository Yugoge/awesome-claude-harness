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
# AC3 -- live_store positive control (read-only, dynamic discovery)
# --------------------------------------------------------------------------

def test_live_store_positive_control():
    """>=1 REAL (session, agent) pair on this machine must resolve its
    verbatim first-record dispatch prompt with a successful meta toolUseId
    cross-check and the typed no_obligation_in_prompt outcome. Zero
    discovered pairs is a test FAILURE, never a skip."""
    roots = account_project_roots()
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
        "positive control violated: zero real (session, agent) pairs "
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
        "positive control violated: no live pair resolved with cross_check=ok "
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
