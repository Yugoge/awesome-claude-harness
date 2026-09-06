"""Regression coverage for the owned-edits ledger contract checker.

Every negative fixture here is REDUCED FROM AN ARTIFACT THAT ACTUALLY SHIPPED --
not from an invented shape. A checker that only rejects shapes someone imagined is
worthless; these four are the shapes real lanes really emitted, each of which rode
all the way to a replay-time failure in scripts/stage-owned-hunks.py because the
contract had no schema and no write-time validation.

Fixture provenance (path, sha256 of the artifact as measured 2026-09-06, and the
exact field the fixture is reduced from):

  M1a  digest-instead-of-content, bare 64-hex
       docs/dev/dev-report-20260720-132338.json
       dbf81978eab1b10483f497a0154b6045ec1c99f320ae396075663d0ac70d1cf0
       pre_edit_snapshots["/root/AGENTS.md"]

  M1b  digest-instead-of-content, algorithm-prefixed
       docs/dev/dev-report-20260717-105214-active-plan-bridge.json
       f067017118c42cdcfa4fb7eb1c6eeff1469065cef47c2eb4c5d32e2838a7726f
       pre_edit_snapshots["hooks/codex_native_harness.py"]

  M2   ledger entries keyed with a prose summary instead of old+new
       docs/dev/parent-iteration-evidence-dev-20260722-081544.json
       467bbb20ce94a1ef42dc73a47001e94ad08c7ff1f7a2e175e6cc68e732f8db6a
       owned_edits[*] (all three entries) and pre_edit_snapshots[*] (object form)

  M3   untracked_modified_provenance missing required fields, lane-only
       docs/dev/dev-report-dev-20260722-081544-r01.json
       0ee7317a811c9352e328fd3ace3d50c713e41126de7f3dcfdaa0782263d26c98
       untracked_modified_provenance["hooks/tests/test_dual_runtime_lifecycle_e2e.py"]
       (its cycle canonical, docs/dev/dev-report-dev-20260722-081544.json
        sha256 878d0eeba94b4d915cf412e97a152ebd5912e0591e8b4f57ca1548808f8be9d1,
        carries no untracked_modified_provenance at all)

  M4   empty 'old' -- shape-valid, semantically unexecutable
       docs/dev/dev-report-dev-20260722-081638.json
       f5c96f12236e83410abc44fd4df7dc2caf869164caea60d10221ff7ffba1e86b
       owned_edits["/root/bin/sync-claude-to-codex.py"][0..2]

Positive controls are likewise real:

  P1   correct nested untracked_modified_provenance with all sibling bindings
       docs/dev/dev-report-20260720-211059-g2.json
  P2   literal-content snapshot whose ledger replays uniquely
       docs/dev/dev-report-20260705-113208-W3.json
"""

import hashlib
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKER = os.path.join(REPO, "scripts", "check-owned-edits-ledger.py")
SCHEMA = os.path.join(REPO, "schemas", "owned-edits-ledger.v1.json")
CONSUMER = os.path.join(REPO, "scripts", "stage-owned-hunks.py")

TASK = "20260906-ledger-fixture"


def run_raw(*paths, **kwargs):
    """Run the checker and return the CompletedProcess, whatever the exit code.

    Separate from run_checker because exits 0/1 and exit 2 are now DIFFERENT
    KINDS of answer -- 0/1 is a verdict about a ledger, 2 is "no verdict was
    reached". Tests about the second kind must not go through a helper that
    asserts the first.
    """
    args = [sys.executable, CHECKER, *paths]
    args += list(kwargs.get("extra", ["--no-discover"]))
    if kwargs.get("as_json", True):
        args.append("--json")
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          env=kwargs.get("env"))


def run_checker(*paths, **kwargs):
    """Run the checker; return (returncode, parsed --json payload)."""
    proc = run_raw(*paths, **kwargs)
    assert proc.returncode in (0, 1), (
        "checker hard-errored (rc=%d):\n%s" % (proc.returncode, proc.stderr.decode())
    )
    return proc.returncode, json.loads(proc.stdout.decode())


def rules(payload):
    return sorted({f["rule"] for f in payload["findings"]})


def findings_for(payload, rule):
    return [f for f in payload["findings"] if f["rule"] == rule]


def write_report(directory, name, **fields):
    doc = {"task_id": TASK, "request_id": TASK}
    doc.update(fields)
    path = os.path.join(str(directory), name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    return path


# A minimal ledger the consumer genuinely accepts: literal-content snapshot, and an
# 'old' that occurs exactly once in the replay buffer.
GOOD_SNAPSHOT = "alpha\nbeta\ngamma\n"
GOOD_LEDGER = [{"old": "beta\n", "new": "beta-edited\n"}]


# --------------------------------------------------------------------------
# Deliverable sanity: the schema is real and machine-readable.
# --------------------------------------------------------------------------


def test_schema_is_valid_json_schema():
    jsonschema = pytest.importorskip("jsonschema")
    with open(SCHEMA, "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    jsonschema.Draft202012Validator.check_schema(schema)


def test_schema_documents_the_rules_it_cannot_express():
    """The uniqueness-during-replay rule depends on evolving state, so it cannot
    live in the schema. The schema must SAY so, and name the checker rule that
    covers it instead."""
    with open(SCHEMA, "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    block = schema["x-unexpressible-in-schema"]
    ids = {rule["id"] for rule in block["rules"]}
    assert "REPLAY-UNIQUE" in ids
    for rule in block["rules"]:
        assert rule["why_unexpressible"].strip()
        assert rule["checker_rule_id"].strip()
        assert rule["consumer_source"].strip()


# --------------------------------------------------------------------------
# POSITIVE CONTROLS -- these must PASS. A checker that rejects everything would
# satisfy every negative test below and still be broken.
# --------------------------------------------------------------------------


def test_positive_minimal_valid_ledger_passes(tmp_path):
    path = write_report(
        tmp_path, "dev-report-%s.json" % TASK,
        owned_edits={"src/app.py": GOOD_LEDGER},
        pre_edit_snapshots={"src/app.py": GOOD_SNAPSHOT},
    )
    rc, payload = run_checker(path)
    assert rc == 0, "valid ledger rejected: %s" % payload["findings"]


def test_positive_empty_new_is_a_legal_deletion(tmp_path):
    """'new' may be empty (a pure deletion replays fine); only 'old' may not."""
    path = write_report(
        tmp_path, "dev-report-%s.json" % TASK,
        owned_edits={"src/app.py": [{"old": "beta\n", "new": ""}]},
        pre_edit_snapshots={"src/app.py": GOOD_SNAPSHOT},
    )
    rc, payload = run_checker(path)
    assert rc == 0, payload["findings"]


def test_positive_real_untracked_modified_provenance_passes():
    """P1: the real, correctly-shaped adoption contract, with every sibling
    binding the consumer checks (pre_edit_provenance.files/statuses,
    final_source_hashes, files_modified claim)."""
    real = os.path.join(REPO, "docs", "dev", "dev-report-20260720-211059-g2.json")
    if not os.path.isfile(real):
        pytest.skip("real artifact not present: %s" % real)
    rc, payload = run_checker(real, extra=["--no-discover", "--git-root", REPO])
    assert rc == 0, "real accepted UMP shape rejected: %s" % payload["findings"]


def test_positive_real_literal_content_snapshot_replays():
    """P2: a real report whose snapshot is literal pre-edit content and whose
    ledger replays uniquely against it."""
    real = os.path.join(REPO, "docs", "dev", "dev-report-20260705-113208-W3.json")
    if not os.path.isfile(real):
        pytest.skip("real artifact not present: %s" % real)
    rc, payload = run_checker(real, extra=["--no-discover", "--git-root", REPO])
    assert rc == 0, "real literal-content ledger rejected: %s" % payload["findings"]


# --------------------------------------------------------------------------
# MALFORMATION 1 -- snapshot holds a digest instead of literal content.
# Two mutually inconsistent real forms; both must be rejected AT WRITE TIME,
# because at replay time they only surface as "not uniquely locatable".
# --------------------------------------------------------------------------


def test_m1a_bare_64_hex_snapshot_rejected(tmp_path):
    path = write_report(
        tmp_path, "dev-report-%s.json" % TASK,
        owned_edits={"/root/AGENTS.md": [
            {"old": "> Last updated: 2026-07-17\n", "new": "> Last updated: 2026-07-20\n"},
        ]},
        pre_edit_snapshots={
            "/root/AGENTS.md":
                "8fa05f78058181bea33d3080c1fd4a6994a5cb0fc824461605f9d4d549282648",
        },
    )
    rc, payload = run_checker(path, extra=["--no-discover", "--git-root", REPO])
    assert rc == 1
    assert "SCHEMA" in rules(payload)
    schema_hit = [f for f in findings_for(payload, "SCHEMA")
                  if "pre_edit_snapshots" in f["field"]]
    assert schema_hit, "schema did not flag the 64-hex snapshot: %s" % payload["findings"]
    assert "len=64" in schema_hit[0]["found"]

    # And the checker must reproduce the downstream consequence, so a reader can
    # connect the write-time rejection to the replay-time failure they remember.
    replay = findings_for(payload, "REPLAY-UNIQUE")
    assert replay, "checker did not simulate the replay failure"
    assert "0 occurrences" in replay[0]["found"]
    assert "64 bytes" in replay[0]["found"]


def test_m1b_algorithm_prefixed_snapshot_rejected(tmp_path):
    path = write_report(
        tmp_path, "dev-report-%s.json" % TASK,
        owned_edits={"hooks/codex_native_harness.py": [
            {"old": "DEV_STEPS: list[dict[str, Any]] = [",
             "new": "LEGACY_DEV_STEPS: list[dict[str, Any]] = ["},
        ]},
        pre_edit_snapshots={
            "hooks/codex_native_harness.py":
                "sha256:bd32e18cc86f64396505b53f8a450f0c85fd5143f8d332213f95040bde56980f",
        },
    )
    rc, payload = run_checker(path, extra=["--no-discover", "--git-root", REPO])
    assert rc == 1
    schema_hit = [f for f in findings_for(payload, "SCHEMA")
                  if "pre_edit_snapshots" in f["field"]]
    assert schema_hit, "schema did not flag the sha256:-prefixed snapshot"
    assert "sha256:" in schema_hit[0]["found"]
    assert findings_for(payload, "REPLAY-UNIQUE")


def test_m1_both_forms_flagged_by_the_same_rule(tmp_path):
    """The two lanes disagreed with each other; the contract must not."""
    path = write_report(
        tmp_path, "dev-report-%s.json" % TASK,
        owned_edits={
            "a.py": [{"old": "x\n", "new": "y\n"}],
            "b.py": [{"old": "x\n", "new": "y\n"}],
        },
        pre_edit_snapshots={
            "a.py": "8fa05f78058181bea33d3080c1fd4a6994a5cb0fc824461605f9d4d549282648",
            "b.py": "sha256:bd32e18cc86f64396505b53f8a450f0c85fd5143f8d332213f95040bde56980f",
        },
    )
    rc, payload = run_checker(path, extra=["--no-discover", "--git-root", REPO])
    assert rc == 1
    flagged = {f["field"] for f in findings_for(payload, "SCHEMA")}
    assert any("'a.py'" in f for f in flagged)
    assert any("'b.py'" in f for f in flagged)


def test_m1_valid_blob_ref_is_not_confused_with_a_digest(tmp_path):
    """Discrimination check: a 40-hex blob ref is the ONE non-literal form the
    materializer accepts, so it must not be swept up by the digest rule. It is
    reported as unresolved (it is not in this repo) -- never as a digest."""
    path = write_report(
        tmp_path, "dev-report-%s.json" % TASK,
        owned_edits={"src/app.py": GOOD_LEDGER},
        pre_edit_snapshots={"src/app.py": "0" * 40},
    )
    rc, payload = run_checker(path, extra=["--no-discover", "--git-root", REPO])
    assert rc == 1
    assert rules(payload) == ["SNAPSHOT-BLOB-UNRESOLVED"], (
        "a 40-hex blob ref must fail only as unresolved, not as a digest: %s"
        % rules(payload)
    )


# --------------------------------------------------------------------------
# MALFORMATION 2 -- ledger entries keyed with a prose summary, not old+new.
# --------------------------------------------------------------------------


REAL_SUMMARY_ENTRIES = [
    {
        "operation": "modify",
        "before_sha256": "ebfa0761a47ea50f631bc0519b09af07597a4196b4c1ed1765b7befe391626e5",
        "after_sha256": "6b019e2bfb10740e8b81a5e6a786e019da5954909c683bd834cbc4fc3e12eace",
        "summary": "Added canonical-JSON SHA-256 provenance for whole shard documents",
    },
    {
        "operation": "modify",
        "before_sha256": "9ee8191e2a4002f3017a2acc6740015866fea372a85e276c59aa1842f071c240",
        "after_sha256": "450afa70be733d3226ccb85f8ad4c0839c40b3848e90366c75ee91a8161f9dd6",
        "summary": "Added focused legacy migration and owned-content drift coverage",
    },
    {
        "operation": "atomic_regenerate_from_current_completed_shards",
        "before_sha256": "4331084c230d9faf9956887fbefc6642b02af4db57c4c79ce64badd16fafd1fb",
        "after_sha256": "878d0eeba94b4d915cf412e97a152ebd5912e0591e8b4f57ca1548808f8be9d1",
        "summary": "Refreshed the stale canonical without deletion",
    },
]


def test_m2_summary_keyed_entries_rejected(tmp_path):
    path = write_report(
        tmp_path, "dev-report-%s.json" % TASK,
        owned_edits={"scripts/aggregate-dev-report.py": REAL_SUMMARY_ENTRIES},
        pre_edit_snapshots={"scripts/aggregate-dev-report.py": GOOD_SNAPSHOT},
    )
    rc, payload = run_checker(path)
    assert rc == 1
    hits = [f for f in findings_for(payload, "SCHEMA") if "owned_edits" in f["field"]]
    assert len(hits) >= 3, (
        "all three real summary-keyed entries must be flagged, got: %s" % hits
    )
    # The message must be actionable without opening the source.
    joined = " ".join(h["required"] for h in hits)
    assert "old" in joined and "new" in joined
    assert any("summary" in h["found"] for h in hits), (
        "the finding must show the shape actually found: %s" % hits
    )


def test_m2_object_form_snapshot_rejected(tmp_path):
    """The same real artifact also wrote pre_edit_snapshots values as OBJECTS
    (snapshot_path + sha256 + size_bytes). The consumer type-gates on str."""
    path = write_report(
        tmp_path, "dev-report-%s.json" % TASK,
        owned_edits={"scripts/aggregate-dev-report.py": GOOD_LEDGER},
        pre_edit_snapshots={"scripts/aggregate-dev-report.py": {
            "snapshot_path": "/var/tmp/dev-20260722-081544-parent-aggregate-preedit/"
                             "aggregate-dev-report.py",
            "sha256": "ebfa0761a47ea50f631bc0519b09af07597a4196b4c1ed1765b7befe391626e5",
            "size_bytes": 18379,
            "capture_method": "exact_inverse_patch_reconstruction",
        }},
    )
    rc, payload = run_checker(path)
    assert rc == 1
    hits = [f for f in findings_for(payload, "SCHEMA")
            if "pre_edit_snapshots" in f["field"]]
    assert hits, payload["findings"]
    assert "object with keys" in hits[0]["found"]


# --------------------------------------------------------------------------
# MALFORMATION 3 -- untracked_modified_provenance missing required fields, and
# present only in a lane rather than in the digest-bound canonical.
# --------------------------------------------------------------------------


REAL_FLAT_CONTRACT = {
    "admission": "authenticated_preexisting_untracked_whole_file",
    "pre_git_status": "??",
    "pre_sha256": "e94667302c5325d793a90ffbd02d7454781a5cf61434ce5b4e5f2a8e0f355623",
    "final_git_status": "??",
    "final_sha256": "b58c5a50cdc3c8a7f7113803180250674028c94d6e12807a76c8e6290e84e897",
    "evidence": "retained exact pre-edit bytes plus exact owned-edits reconstruction",
}
UMP_PATH = "hooks/tests/test_dual_runtime_lifecycle_e2e.py"


def test_m3_flat_contract_missing_required_fields_rejected(tmp_path):
    path = write_report(
        tmp_path, "dev-report-%s.json" % TASK,
        untracked_modified_provenance={UMP_PATH: REAL_FLAT_CONTRACT},
        dev={"files_modified": [UMP_PATH], "files_created": []},
    )
    rc, payload = run_checker(path)
    assert rc == 1
    hits = [f for f in findings_for(payload, "SCHEMA")
            if "untracked_modified_provenance" in f["field"]]
    assert hits, payload["findings"]
    # The three structural fields the real artifact omitted.
    missing = " ".join(h["required"] for h in hits)
    for field in ("path", "pre_edit", "final", "evidence_source"):
        assert field in missing, (
            "checker must name the missing field %r; said: %s" % (field, missing)
        )


def test_m3_contract_in_lane_but_not_canonical_rejected(tmp_path):
    """The consumer only ever reads this contract out of dev-report-<task>.json.
    A lane-only contract is inert, which is exactly why it went unnoticed."""
    write_report(tmp_path, "dev-report-%s.json" % TASK,
                 dev={"files_modified": [UMP_PATH], "files_created": []})
    lane = write_report(
        tmp_path, "dev-report-%s-r01.json" % TASK,
        untracked_modified_provenance={UMP_PATH: REAL_FLAT_CONTRACT},
        dev={"files_modified": [UMP_PATH], "files_created": []},
    )
    rc, payload = run_checker(lane, extra=[])  # discovery ON
    assert rc == 1
    lane_only = findings_for(payload, "UMP-LANE-ONLY")
    assert lane_only, "lane-only contract not flagged: %s" % rules(payload)
    assert lane_only[0]["lane"] == "r01", (
        "the finding must name WHICH lane it came from, got %r" % lane_only[0]["lane"]
    )
    checked = {entry["lane"] for entry in payload["checked"]}
    assert {"canonical", "r01"} <= checked, (
        "both the canonical and the lane must be validated, got %s" % checked
    )


def test_m3_sibling_binding_violations_are_reported_individually(tmp_path):
    """Shape-correct but unbound: the consumer also requires pre_edit_provenance
    and final_source_hashes to agree with the contract's own hashes."""
    pre = "e94667302c5325d793a90ffbd02d7454781a5cf61434ce5b4e5f2a8e0f355623"
    fin = "b58c5a50cdc3c8a7f7113803180250674028c94d6e12807a76c8e6290e84e897"
    path = write_report(
        tmp_path, "dev-report-%s.json" % TASK,
        untracked_modified_provenance={UMP_PATH: {
            "path": UMP_PATH,
            "admission": "authenticated_preexisting_untracked_whole_file",
            "pre_edit": {"git_status": "??", "sha256": pre},
            "final": {"git_status": "??", "sha256": fin},
            "evidence_source": "context observed_evidence.current_file_hashes",
        }},
        dev={"files_modified": [UMP_PATH], "files_created": []},
    )
    rc, payload = run_checker(path)
    assert rc == 1
    assert "UMP-PREEDIT-PROV-MISSING" in rules(payload), rules(payload)
    assert "UMP-FINAL-HASH-MISMATCH" in rules(payload), rules(payload)


def test_m3_identical_hashes_rejected(tmp_path):
    same = "e94667302c5325d793a90ffbd02d7454781a5cf61434ce5b4e5f2a8e0f355623"
    path = write_report(
        tmp_path, "dev-report-%s.json" % TASK,
        untracked_modified_provenance={UMP_PATH: {
            "path": UMP_PATH,
            "admission": "authenticated_preexisting_untracked_whole_file",
            "pre_edit": {"git_status": "??", "sha256": same},
            "final": {"git_status": "??", "sha256": same},
            "evidence_source": "context observed_evidence",
        }},
        pre_edit_provenance={
            "verified_before_edit": True, "source": "context current_file_hashes",
            "files": {UMP_PATH: same}, "statuses": {UMP_PATH: "??"},
        },
        final_source_hashes={UMP_PATH: same},
        dev={"files_modified": [UMP_PATH], "files_created": []},
    )
    rc, payload = run_checker(path)
    assert rc == 1
    assert "UMP-HASH-IDENTICAL" in rules(payload), rules(payload)


def test_m3_adopted_path_in_files_created_rejected(tmp_path):
    """Adoption records a pre-existing file as MODIFIED; listing it as created is
    the relabelling the admission mode exists to prevent."""
    pre = "e94667302c5325d793a90ffbd02d7454781a5cf61434ce5b4e5f2a8e0f355623"
    fin = "b58c5a50cdc3c8a7f7113803180250674028c94d6e12807a76c8e6290e84e897"
    path = write_report(
        tmp_path, "dev-report-%s.json" % TASK,
        untracked_modified_provenance={UMP_PATH: {
            "path": UMP_PATH,
            "admission": "authenticated_preexisting_untracked_whole_file",
            "pre_edit": {"git_status": "??", "sha256": pre},
            "final": {"git_status": "??", "sha256": fin},
            "evidence_source": "context observed_evidence",
        }},
        pre_edit_provenance={
            "verified_before_edit": True, "source": "context current_file_hashes",
            "files": {UMP_PATH: pre}, "statuses": {UMP_PATH: "??"},
        },
        final_source_hashes={UMP_PATH: fin},
        dev={"files_modified": [], "files_created": [UMP_PATH]},
    )
    rc, payload = run_checker(path)
    assert rc == 1
    assert "UMP-IN-CREATED" in rules(payload), rules(payload)
    assert "UMP-NOT-CLAIMED" in rules(payload), rules(payload)


# --------------------------------------------------------------------------
# MALFORMATION 4 -- empty 'old'. Shape-plausible, never executable.
# The runtime now signals this distinctly: the consumer's _count_occurrences
# raises EmptyOwnedOldStringError and both replay sites report "has an empty
# old_string", separate from the "not uniquely locatable during replay" message
# used for real content drift. This contract rejects the shape at WRITE time,
# which is independent of how the runtime reports it.
# --------------------------------------------------------------------------


def test_m4_empty_old_rejected(tmp_path):
    path = write_report(
        tmp_path, "dev-report-%s.json" % TASK,
        owned_edits={"/root/bin/sync-claude-to-codex.py": [
            {"old": "", "new": "import copy\n"},
            {"old": "", "new": "import gzip\n"},
            {"old": "", "new": "import io\n"},
        ]},
        pre_edit_snapshots={"/root/bin/sync-claude-to-codex.py": GOOD_SNAPSHOT},
    )
    rc, payload = run_checker(path)
    assert rc == 1
    schema_hits = [f for f in findings_for(payload, "SCHEMA")
                   if f["field"].endswith(".old") or "owned_edits" in f["field"]]
    assert len(schema_hits) >= 3, (
        "each empty-old entry must be flagged, got %d: %s"
        % (len(schema_hits), schema_hits)
    )
    semantic = findings_for(payload, "REPLAY-EMPTY-OLD")
    assert len(semantic) == 3
    assert "pure insertion" in semantic[0]["found"]
    assert "non-empty" in semantic[0]["required"]


def test_m4_empty_old_is_not_reported_as_a_uniqueness_failure(tmp_path):
    """An empty needle and a genuinely absent string are different faults, and
    conflating them is precisely why this shape once went undiagnosed. The
    consumer now separates them (EmptyOwnedOldStringError vs "not uniquely
    locatable"), and the checker must keep them separate too."""
    path = write_report(
        tmp_path, "dev-report-%s.json" % TASK,
        owned_edits={"src/app.py": [{"old": "", "new": "import io\n"}]},
        pre_edit_snapshots={"src/app.py": GOOD_SNAPSHOT},
    )
    rc, payload = run_checker(path)
    assert rc == 1
    assert "REPLAY-EMPTY-OLD" in rules(payload)
    assert "REPLAY-UNIQUE" not in rules(payload), (
        "empty-old must not be conflated with a real uniqueness failure"
    )


# --------------------------------------------------------------------------
# Cross-cutting: findings must be actionable, and the checker must exit non-zero.
# --------------------------------------------------------------------------


def test_every_finding_names_lane_field_found_and_required(tmp_path):
    path = write_report(
        tmp_path, "dev-report-%s-r09.json" % TASK,
        owned_edits={"a.py": [{"old": "", "new": "x\n"}]},
        pre_edit_snapshots={
            "a.py": "8fa05f78058181bea33d3080c1fd4a6994a5cb0fc824461605f9d4d549282648",
        },
    )
    rc, payload = run_checker(path, extra=[])
    assert rc == 1
    assert payload["findings"]
    for f in payload["findings"]:
        for key in ("rule", "lane", "file", "field", "found", "required",
                    "requirement", "consumer_source"):
            assert f.get(key), "finding missing %r: %s" % (key, f)
        assert f["lane"] == "r09"
        assert ".py" in f["field"] or "snapshot" in f["field"] or "owned_edits" in f["field"]


def test_orphan_ledger_without_snapshot_rejected(tmp_path):
    path = write_report(
        tmp_path, "dev-report-%s.json" % TASK,
        owned_edits={"src/app.py": GOOD_LEDGER},
    )
    rc, payload = run_checker(path)
    assert rc == 1
    assert "LEDGER-SNAPSHOT-ORPHAN" in rules(payload), rules(payload)


def test_replay_non_unique_old_rejected(tmp_path):
    """A duplicated 'old' is ambiguous at that replay step -- the permutation hole
    the consumer's forward replay exists to close."""
    path = write_report(
        tmp_path, "dev-report-%s.json" % TASK,
        owned_edits={"src/app.py": [{"old": "dup\n", "new": "x\n"}]},
        pre_edit_snapshots={"src/app.py": "dup\ndup\n"},
    )
    rc, payload = run_checker(path)
    assert rc == 1
    hits = findings_for(payload, "REPLAY-UNIQUE")
    assert hits and "2 occurrences" in hits[0]["found"], payload["findings"]


# --------------------------------------------------------------------------
# ENVIRONMENT vs VERDICT. A broken environment must never be able to produce
# exit 1, because the documented wire-in reads exit 1 as "re-dispatch the lane
# the findings name" -- so a missing git would have blamed an innocent lane
# while emitting no evidence whatsoever.
#
# Measured before the fix, same invocation and same inputs, differing only in
# whether git was on PATH:
#     git present : rc=1, 712 bytes of findings on stdout
#     git absent  : rc=1, 0 bytes on stdout, uncaught FileNotFoundError
# --------------------------------------------------------------------------


BLOBREF_REPORT = dict(
    owned_edits={"src/app.py": [{"old": "beta\n", "new": "beta-edited\n"}]},
    pre_edit_snapshots={"src/app.py": "0" * 40},
)


def _path_without_git(tmp_path):
    """A PATH on which git cannot be found. python is invoked absolutely."""
    empty = os.path.join(str(tmp_path), "empty-bin")
    os.makedirs(empty, exist_ok=True)
    env = dict(os.environ)
    env["PATH"] = empty
    return env


def test_git_absent_is_exit_2_not_a_contract_violation(tmp_path):
    path = write_report(tmp_path, "dev-report-%s.json" % TASK, **BLOBREF_REPORT)
    proc = run_raw(path, extra=["--no-discover", "--git-root", REPO],
                   env=_path_without_git(tmp_path))
    assert proc.returncode == 2, (
        "a missing git must be exit 2 (infrastructure), never exit 1 (violation); "
        "got rc=%d\nstdout=%r\nstderr=%r"
        % (proc.returncode, proc.stdout.decode(), proc.stderr.decode())
    )


def test_git_absent_says_so_loudly_and_leaks_no_traceback(tmp_path):
    """The original failure was SILENT: empty stdout plus a raw traceback. Both
    halves matter -- a traceback is not a diagnosis, and an empty stdout under
    exit 1 is a verdict nobody can check."""
    path = write_report(tmp_path, "dev-report-%s.json" % TASK, **BLOBREF_REPORT)
    proc = run_raw(path, extra=["--no-discover", "--git-root", REPO],
                   env=_path_without_git(tmp_path))
    err = proc.stderr.decode()
    assert "INFRASTRUCTURE FAILURE" in err, err
    assert "cannot execute git" in err, err
    assert "Traceback (most recent call last)" not in err, (
        "an uncaught traceback escaped; the failure must be diagnosed, not dumped:\n%s"
        % err
    )
    assert "do NOT re-dispatch any lane" in err, (
        "the operator must be told explicitly not to act on this as a violation"
    )


def test_git_present_and_absent_differ_in_the_right_direction(tmp_path):
    """The defect was that the two environments were INDISTINGUISHABLE. This
    asserts the distinction directly rather than each side in isolation."""
    path = write_report(tmp_path, "dev-report-%s.json" % TASK, **BLOBREF_REPORT)
    present = run_raw(path, extra=["--no-discover", "--git-root", REPO])
    absent = run_raw(path, extra=["--no-discover", "--git-root", REPO],
                     env=_path_without_git(tmp_path))

    assert present.returncode == 1 and absent.returncode == 2, (
        "same inputs must yield a verdict with git and a hard error without it; "
        "got present=%d absent=%d" % (present.returncode, absent.returncode)
    )
    # With git: a real, non-empty finding naming the rule.
    payload = json.loads(present.stdout.decode())
    assert payload["findings"], "git-present run produced no evidence"
    assert "SNAPSHOT-BLOB-UNRESOLVED" in rules(payload)
    # Without git: no findings are claimed at all.
    assert b"SNAPSHOT-BLOB-UNRESOLVED" not in absent.stdout, (
        "the git-absent run must not assert any finding it could not evaluate"
    )


def test_git_root_that_is_not_a_repository_is_exit_2(tmp_path):
    """Same class: a --git-root pointing outside any repo cannot resolve blob
    refs, so every SNAPSHOT-BLOB-UNRESOLVED it would emit is environmental noise
    rather than a lane's fault."""
    path = write_report(tmp_path, "dev-report-%s.json" % TASK, **BLOBREF_REPORT)
    outside = os.path.join(str(tmp_path), "not-a-repo")
    os.makedirs(outside, exist_ok=True)
    proc = run_raw(path, extra=["--no-discover", "--git-root", outside])
    assert proc.returncode == 2, proc.stdout.decode() + proc.stderr.decode()
    assert "not a git repository" in proc.stderr.decode()


# --------------------------------------------------------------------------
# EXIT 2 FOR UNREADABLE INPUT. Documented from the start, but unreachable for
# the case it named: unparseable reports were recorded as SCHEMA findings and
# exited 1, conflating "this file is not JSON" with "this lane's ledger is wrong".
# --------------------------------------------------------------------------


def test_unparseable_json_is_exit_2(tmp_path):
    bad = os.path.join(str(tmp_path), "dev-report-%s.json" % TASK)
    with open(bad, "w", encoding="utf-8") as fh:
        fh.write('{"task_id": "x", "owned_edits": {,,,}')
    proc = run_raw(bad)
    assert proc.returncode == 2, (
        "malformed JSON must be an input error, not a contract violation; rc=%d"
        % proc.returncode
    )
    err = proc.stderr.decode()
    assert "INPUT ERROR" in err, err
    assert "unparseable-json" in err, err
    assert "no lane may be blamed" in err, err


def test_unparseable_json_is_not_reported_as_a_violation(tmp_path):
    """Discrimination, not just exit code: the JSON payload must carry the file
    under input_errors and must NOT invent findings against it."""
    bad = os.path.join(str(tmp_path), "dev-report-%s.json" % TASK)
    with open(bad, "w", encoding="utf-8") as fh:
        fh.write("not json at all")
    proc = run_raw(bad)
    assert proc.returncode == 2
    payload = json.loads(proc.stdout.decode())
    assert payload["input_errors"], payload
    assert payload["input_errors"][0]["kind"] == "unparseable-json"
    assert payload["findings"] == [], (
        "a file that could not be parsed must yield no contract findings: %s"
        % payload["findings"]
    )


@pytest.mark.parametrize("name", [
    "dev-report-20260524-101700-B.json",
    "dev-report-20260727-214105.json",
])
def test_real_unparseable_corpus_reports_exit_2(name):
    """Proven on the real files, not only on a synthetic one. These two shipped
    unparseable and both exited 1 before this fix."""
    real = os.path.join(REPO, "docs", "dev", name)
    if not os.path.isfile(real):
        pytest.skip("real artifact not present: %s" % real)
    with open(real, "rb") as fh:
        raw = fh.read()
    try:
        json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        pass
    else:
        pytest.skip("%s is parseable now; the premise no longer holds" % name)
    proc = run_raw(real, extra=["--no-discover", "--git-root", REPO])
    assert proc.returncode == 2, (
        "%s is unparseable JSON and must exit 2, got %d" % (name, proc.returncode)
    )
    assert "INPUT ERROR" in proc.stderr.decode()


def test_a_real_violation_still_exits_1(tmp_path):
    """Guard against over-correcting: making exit 2 reachable must not swallow
    genuine violations into it."""
    path = write_report(
        tmp_path, "dev-report-%s.json" % TASK,
        owned_edits={"src/app.py": [{"old": "", "new": "x\n"}]},
        pre_edit_snapshots={"src/app.py": GOOD_SNAPSHOT},
    )
    proc = run_raw(path)
    assert proc.returncode == 1, proc.stderr.decode()
    assert "REPLAY-EMPTY-OLD" in rules(json.loads(proc.stdout.decode()))


# --------------------------------------------------------------------------
# TOP-LEVEL LEDGER-PRESENCE CONSTRAINT. Without it a document carrying no
# ledger validated, so the corpus pass-rate counted silence as compliance:
# 208 of 308 "passed", but 151 carried no ledger field at all and 12 more
# carried only empty {} maps. Measured after the constraint: 45 conforming
# ledgers against 111 violating ones, 151 ledger-less, 2 unreadable.
# --------------------------------------------------------------------------


def test_empty_document_does_not_validate(tmp_path):
    path = write_report(tmp_path, "dev-report-%s.json" % TASK)
    rc, payload = run_checker(path)
    assert rc == 1, "a document with no ledger must not pass"
    assert "LEDGER-ABSENT" in rules(payload), rules(payload)


def test_ledgerless_report_is_named_not_buried_in_schema_noise(tmp_path):
    """It must be legible as its own act: 'no ledger emitted' is a different
    thing from 'a malformed ledger emitted', and the operator has to tell them
    apart to know whether a lane misbehaved."""
    path = write_report(
        tmp_path, "dev-report-%s.json" % TASK,
        dev={"files_modified": ["src/app.py"], "files_created": []},
    )
    rc, payload = run_checker(path)
    assert rc == 1
    hits = findings_for(payload, "LEDGER-ABSENT")
    assert hits, rules(payload)
    assert "no ledger to check" in hits[0]["found"]
    assert "owned_edits" in hits[0]["required"]


@pytest.mark.parametrize("fields", [
    {"owned_edits": {}, "pre_edit_snapshots": {}},
    {"owned_edits": {}},
    {"pre_edit_snapshots": {}},
    {"untracked_modified_provenance": {}},
    {"owned_edits": {"a.py": [{"old": "x", "new": "y"}]}},   # snapshot half missing
    {"pre_edit_snapshots": {"a.py": "content"}},             # ledger half missing
])
def test_empty_or_half_ledgers_do_not_validate(tmp_path, fields):
    """12 corpus reports carried {} for both maps and were counted as conforming.
    A half-ledger is equally unusable: the consumer needs --ledger AND --snapshot."""
    path = write_report(tmp_path, "dev-report-%s.json" % TASK, **fields)
    rc, payload = run_checker(path)
    assert rc == 1, "empty/half ledger %s was accepted" % fields
    assert "LEDGER-ABSENT" in rules(payload), (
        "expected LEDGER-ABSENT for %s, got %s" % (fields, rules(payload))
    )


def test_constraint_still_admits_the_two_real_ledger_shapes(tmp_path):
    """Positive control for the constraint itself. Both shipped shapes must
    still pass, or the constraint would just be a way to fail everything."""
    hunk = write_report(
        tmp_path, "dev-report-%s.json" % TASK,
        owned_edits={"src/app.py": GOOD_LEDGER},
        pre_edit_snapshots={"src/app.py": GOOD_SNAPSHOT},
    )
    rc, payload = run_checker(hunk)
    assert rc == 0, payload["findings"]

    adoption = os.path.join(REPO, "docs", "dev", "dev-report-20260720-211059-g2.json")
    if os.path.isfile(adoption):
        rc, payload = run_checker(adoption,
                                  extra=["--no-discover", "--git-root", REPO])
        assert rc == 0, (
            "the real adoption-only shape must still satisfy the constraint: %s"
            % payload["findings"]
        )


def test_schema_declares_the_top_level_constraint():
    with open(SCHEMA, "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    assert "anyOf" in schema, "the schema must constrain the document top level"
    required = [set(branch.get("required", [])) for branch in schema["anyOf"]]
    assert {"owned_edits", "pre_edit_snapshots"} in required
    assert {"untracked_modified_provenance"} in required
    for name in ("ownedEditsMap", "preEditSnapshotsMap",
                 "untrackedModifiedProvenanceMap"):
        assert schema["$defs"][name].get("minProperties") == 1, (
            "%s must reject an empty map" % name
        )


# --------------------------------------------------------------------------
# CONSUMER BINDING. The rules here are derived from the consumer's code, so the
# binding to that code must be ACTIVE -- something that fails when the consumer
# moves, not a comment nobody checks. Two layers: a digest (catches any change)
# and a behavioural self-check inside the checker (catches semantic drift).
# --------------------------------------------------------------------------


def _sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def test_consumer_digest_binding_is_active():
    """The schema records the digest of the consumer its rules were derived from.
    If the consumer changes, this FAILS -- which is the entire point. Do not
    re-pin the digest without re-reading the consumer's replay primitives and
    _load_untracked_modified_contract and confirming the rules still hold."""
    with open(SCHEMA, "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    recorded = schema["x-consumer"]["sha256"]
    actual = _sha256(CONSUMER)
    assert recorded == actual, (
        "consumer digest binding broken.\n"
        "  schema x-consumer.sha256 : %s\n"
        "  %s : %s\n"
        "The rules in this schema were derived from the recorded revision. "
        "Re-derive them against the delivered file, then update x-consumer."
        % (recorded, CONSUMER, actual)
    )
    assert schema["x-consumer"]["lines"] == len(
        open(CONSUMER, encoding="utf-8").read().splitlines())


def test_checker_calls_the_consumer_rather_than_mirroring_it():
    """Design decision, enforced. The empty-needle semantics were previously a
    hand-copied reimplementation, and the copy drifted from its original. The
    checker must now IMPORT the consumer's primitives so the drift class cannot
    recur."""
    with open(CHECKER, "r", encoding="utf-8") as fh:
        source = fh.read()
    assert "spec_from_file_location" in source, (
        "the checker must load the consumer, not restate it"
    )
    assert "_count_occurrences" in source and "EmptyOwnedOldStringError" in source
    # A DEFINITION at column 0 -- not a mention. The RULES table legitimately
    # quotes "def _count_occurrences()" as a citation anchor, so a bare substring
    # test would fail on the very citation policy this change introduced.
    import re
    redefinition = re.search(r"^def _count_occurrences", source, re.MULTILINE)
    assert not redefinition, (
        "the checker re-declares _count_occurrences at module level; that private "
        "copy is exactly what drifted from the consumer and must not come back"
    )


def test_consumer_still_raises_on_the_empty_needle():
    """The behaviour every REPLAY-EMPTY-OLD message now asserts to the operator.
    Imported the same way the checker imports it."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("stage_owned_hunks_probe", CONSUMER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(module.EmptyOwnedOldStringError):
        module._count_occurrences(b"abc", b"")
    assert module._count_occurrences(b"aXbXc", b"X") == 2
    with pytest.raises(module.EmptyOwnedOldStringError):
        module._locate_unique(b"abc", b"")


def test_no_artifact_still_describes_the_deleted_minus_one_sentinel():
    """PRIORITY TWO regression guard. The consumer stopped returning -1 and began
    raising; these artifacts kept describing the sentinel in six places, one of
    which is printed to the operator on every empty-old finding (182 of them
    across this corpus). Measured with Python string search over the three files
    below, rooted at the repo, so no ignore-file rule can hide a hit.

    The forbidden strings are the ASSERTIONS of the deleted behaviour, not the
    word 'sentinel' itself: saying the consumer moved FROM a -1 sentinel TO
    raising is accurate history and worth keeping. What must not survive is any
    claim that the sentinel is what happens NOW.
    """
    stale_claims = (
        "returns the -1 sentinel",
        "return the -1 sentinel",
        "returns -1",
        "reported identically to a genuinely absent",
        "reports it identically to a genuinely absent",
        "identically to a genuinely absent string",
        "collapses any count != 1 to None",
        "sentinel included",
    )
    offenders = []
    for rel in ("scripts/check-owned-edits-ledger.py",
                "schemas/owned-edits-ledger.v1.json",
                "tests/test_owned_edits_ledger_contract.py"):
        with open(os.path.join(REPO, rel), "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        in_own_literals = False
        for n, line in enumerate(lines, 1):
            # Skip this test's own list of forbidden literals.
            if "stale_claims = (" in line:
                in_own_literals = True
                continue
            if in_own_literals:
                if line.strip() == ")":
                    in_own_literals = False
                continue
            for token in stale_claims:
                if token in line:
                    offenders.append("%s:%d %s" % (rel, n, line.strip()[:100]))
    assert not offenders, (
        "these sites still assert the DELETED -1 sentinel as current behaviour:\n  "
        + "\n  ".join(offenders)
    )


def test_replay_empty_old_message_states_what_the_consumer_now_does(tmp_path):
    """Positive control for the above: absence of the old wording is only half
    the repair. The operator-visible string must state the CURRENT behaviour.

    This is the string printed on every one of the 182 empty-old findings this
    corpus produces, so it is the site where being wrong was most expensive."""
    path = write_report(
        tmp_path, "dev-report-%s.json" % TASK,
        owned_edits={"src/app.py": [{"old": "", "new": "x\n"}]},
        pre_edit_snapshots={"src/app.py": GOOD_SNAPSHOT},
    )
    rc, payload = run_checker(path)
    assert rc == 1
    hit = findings_for(payload, "REPLAY-EMPTY-OLD")[0]
    assert "EmptyOwnedOldStringError" in hit["required"], hit["required"]
    assert "raise" in hit["required"] or "raises" in hit["required"], hit["required"]
    assert "EmptyOwnedOldStringError" in hit["consumer_source"], hit["consumer_source"]


def test_no_artifact_cites_a_bare_line_number():
    """CITATION POLICY guard. ~33 distinct consumer line ranges were pinned here;
    when the consumer grew from 1087 to 1110 lines at least 18 provably no longer
    contained the construct they named. A rotted line number still resolves, so it
    misleads silently -- symbols and quoted anchors fail loudly instead."""
    import re
    pattern = re.compile(
        r"(?:scripts/stage-owned-hunks\.py|agents/changelog-analyst\.md|"
        r"agents/dev\.md):(\d+)(?:-(\d+))?|(?<![\w/]):(\d+)-(\d+)\b")
    offenders = []
    for rel in ("scripts/check-owned-edits-ledger.py",
                "schemas/owned-edits-ledger.v1.json"):
        with open(os.path.join(REPO, rel), "r", encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                if pattern.search(line):
                    offenders.append("%s:%d %s" % (rel, n, line.strip()[:100]))
    assert not offenders, (
        "line-number citations reintroduced (cite by symbol or quoted anchor):\n  "
        + "\n  ".join(offenders))


def test_every_cited_anchor_actually_resolves():
    """A citation policy is only worth having if the anchors are real. Each of
    these is quoted by the checker's RULES table or the schema; a positive
    control with a negative control alongside it."""
    anchors = {
        os.path.join(REPO, "scripts", "stage-owned-hunks.py"): [
            "def _replay_live", "def _count_occurrences", "def _locate_unique",
            "class EmptyOwnedOldStringError", "def _load_untracked_modified_contract",
            "def _valid_sha256", "def _is_binary", "def _encode_edit_value",
            "def _load_provenance_plan", "not uniquely locatable during replay",
            "has an empty old_string", "owned-edits ledger empty/invalid",
            "malformed (need old+new)", "values must be strings/bytes",
            "expected_name",
        ],
        os.path.join(REPO, "agents", "changelog-analyst.md"): [
            "2. Snapshot materialization (REQUIRED",
            "Fail-closed for ambiguous shared dirty files",
        ],
    }
    for path, needles in anchors.items():
        if not os.path.isfile(path):
            pytest.skip("cited file absent: %s" % path)
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        # Negative control: absence must be detectable by this same method.
        assert "THIS_ANCHOR_SHOULD_NEVER_EXIST_4c1f" not in text
        for needle in needles:
            assert needle in text, (
                "cited anchor %r no longer resolves in %s" % (needle, path))


def test_checker_is_wired_into_no_blocking_path():
    """This deliverable must remain standalone: another cycle is committing, and a
    new gate would interrupt it. The wire-in point is DOCUMENTED, not performed."""
    for rel in ("commands/commit.md", "settings.json", "agents/changelog-analyst.md"):
        target = os.path.join(REPO, rel)
        if not os.path.isfile(target):
            continue
        with open(target, "r", encoding="utf-8") as fh:
            assert "check-owned-edits-ledger" not in fh.read(), (
                "%s references the checker; it must not be wired into a blocking "
                "path yet" % rel
            )
    with open(CHECKER, "r", encoding="utf-8") as fh:
        doc = fh.read()
    assert "FUTURE WIRE-IN" in doc
    assert "commands/commit.md" in doc, "the wire-in point must name the command"
