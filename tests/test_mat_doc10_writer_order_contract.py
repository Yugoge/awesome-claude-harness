"""Validation tests for the MAT-DOC10 SU->DOC->generator->QA writer/order contract v2.

Published by task 20260819-124121-r03 (LANE-SU, spec 20260808-035658).

These tests hard-fail (never skip) when the contract artifact is missing: an
absent contract means LANE-DOC's SU-side precondition is unevaluable, which is
exactly the MAT-DOC10 circular gate this contract exists to dissolve.
"""

import hashlib
import itertools
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
# Authoritative home. The iteration-1 draft lived under the gitignored docs/dev/
# tree, so it could not be staged and would be absent from a fresh clone; the
# contract LANE-DOC's gate binds to must be clone-durable.
CONTRACT_REL = "docs/reference/mat-doc10-writer-order.v2.json"
CONTRACT_PATH = REPO_ROOT / CONTRACT_REL
SUPERSEDED_DRAFT_REL = "docs/dev/mat-doc10-writer-order-contract.v2.json"
SUPERSEDED_DRAFT_SHA256 = (
    "f2fd35c8a31284713a07758c846ea5f7a46af7754fa1999adadaacd03d1ea585"
)

EXPECTED_PHASES = ["SU_PUBLISH", "DOC_CONSUME", "GENERATE", "SU_QA"]

# M2 writer map, re-published from the previously-accepted single-writer map.
EXPECTED_WRITES = {
    "SU_PUBLISH": {
        "commands/spec-update.md",
        "scripts/spec-update-contract.py",
        "tests/test_spec_update_command_contracts.py",
        "CHANGELOG.md",
    },
    "DOC_CONSUME": {"commands/dev.md", "commands/dev-command.md"},
    "GENERATE": {"README.md", "INDEX.md", "commands/README.md", "commands/INDEX.md"},
    "SU_QA": set(),
}

CEREMONY_OFFER_SHA256 = "f20776d9bc31f1f974f4c84632357ffa8f7d3947bc37ddc96b3dab95d99d4512"
MAT_DOC10_V1_DIGEST = "2157e04b5f3051f4e58b3168ed444acd052836181122b6300d153e53154a0bb9"
USER_DIRECTIVE = "仪式是codex发明的话就不要管了，我们按照claude正式harness走"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def contract() -> dict:
    if not CONTRACT_PATH.is_file():
        pytest.fail(
            f"MAT-DOC10 writer/order contract absent at {CONTRACT_PATH} — "
            "LANE-DOC's SU-side precondition is unevaluable without it"
        )
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_contract_parses_and_carries_identity_fields(contract):
    assert contract["schema"] == "mat-doc10-writer-order.v2"
    assert contract["spec_id"] == "20260808-035658"
    assert contract["published_by_task_id"] == "20260819-124121-r03"


def test_phase_order_is_exact_and_ordered(contract):
    assert contract["phases"] == EXPECTED_PHASES
    smap = contract["single_writer_map"]
    assert list(smap.keys()) == EXPECTED_PHASES
    assert [smap[p]["order"] for p in EXPECTED_PHASES] == [1, 2, 3, 4]


def test_writer_map_matches_m2_exactly(contract):
    smap = contract["single_writer_map"]
    for phase, expected in EXPECTED_WRITES.items():
        assert set(smap[phase]["writes"]) == expected, f"{phase} write set drifted from M2"
        assert len(smap[phase]["writes"]) == len(expected), f"{phase} has duplicate paths"


def test_writer_map_sets_are_pairwise_disjoint(contract):
    smap = contract["single_writer_map"]
    for a, b in itertools.combinations(EXPECTED_PHASES, 2):
        overlap = set(smap[a]["writes"]) & set(smap[b]["writes"])
        assert not overlap, f"{a} and {b} both claim {sorted(overlap)} — single-writer violated"
    assert contract["writer_map_invariants"]["pairwise_disjoint"] is True


def test_su_publish_complete_with_hashes_matching_live_bytes(contract):
    su = contract["single_writer_map"]["SU_PUBLISH"]
    assert su["status"] == "complete"
    recorded = su["evidence"]["file_sha256"]
    assert set(recorded) == EXPECTED_WRITES["SU_PUBLISH"]
    for rel, expected_hash in recorded.items():
        live = REPO_ROOT / rel
        assert live.is_file(), f"SU evidence path missing from worktree: {rel}"
        assert _sha256(live) == expected_hash, f"SU evidence hash drifted for {rel}"


def test_qa_iter7_evidence_resolves_and_passes(contract):
    qa = contract["single_writer_map"]["SU_PUBLISH"]["evidence"]["qa_report"]
    qa_path = REPO_ROOT / qa["path"]
    assert qa_path.is_file(), f"QA evidence report missing: {qa['path']}"
    assert _sha256(qa_path) == qa["sha256"]
    assert json.loads(qa_path.read_text(encoding="utf-8"))[qa["field"]] == qa["value"] == "PASS"


def test_generate_phase_is_constrained_to_one_admitted_pass(contract):
    gen = contract["single_writer_map"]["GENERATE"]
    assert gen["pass_constraint"]["admitted_passes"] == 1
    surface = gen["pass_constraint"]["surface"]
    for rel in [surface["driver"], surface["entrypoint"], *surface["writers"]]:
        assert (REPO_ROOT / rel).is_file(), f"declared generator surface missing: {rel}"


def test_su_qa_phase_is_read_only(contract):
    su_qa = contract["single_writer_map"]["SU_QA"]
    assert su_qa["writes"] == []
    assert su_qa["mode"] == "read-only"
    assert "SU_QA" in contract["writer_map_invariants"]["read_only_phases"]


def test_no_forward_phase_output_is_claimed(contract):
    smap = contract["single_writer_map"]
    for phase in ["DOC_CONSUME", "GENERATE", "SU_QA"]:
        assert smap[phase]["status"] == "pending", f"{phase} must not claim completion"
        assert smap[phase]["evidence"] is None, f"{phase} must not carry outcome evidence"
    assert contract["no_forward_output_claim"]["asserted"] is True


def test_supersedes_names_both_v1_contract_and_ceremony_chain(contract):
    sup = contract["supersedes"]
    by_identity = {entry["identity"]: entry for entry in sup["superseded"]}

    v1 = by_identity["MAT-DOC10.v1"]
    assert v1["canonical_digest"] == MAT_DOC10_V1_DIGEST

    offer = by_identity["cycle-routing-offer.v2.json"]
    assert offer["sha256"] == CEREMONY_OFFER_SHA256

    assert sup["user_directive_verbatim"] == USER_DIRECTIVE


def test_lane_doc_precondition_is_ceremony_free_and_evaluates_true(contract):
    pre = contract["lane_doc_precondition"]
    assert pre["ceremony_free"] is True
    assert pre["ceremony_artifacts_read"] == 0

    # Evaluate the published predicate using repository state only.
    assert CONTRACT_PATH.is_file()
    live = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    su = live["single_writer_map"]["SU_PUBLISH"]
    assert su["status"] == "complete"
    assert all(
        _sha256(REPO_ROOT / rel) == digest
        for rel, digest in su["evidence"]["file_sha256"].items()
    )


def test_contract_does_not_recreate_a_handshake_ceremony(contract):
    """W4: exactly one declarative artifact — no offer/acceptance/admission chain."""
    inventory = contract["abolished_ceremony_inventory"]
    assert "historical evidence only" in inventory["status"]

    # The precondition LANE-DOC actually evaluates must reference no ceremony path.
    predicate_text = " ".join(contract["lane_doc_precondition"]["predicate"])
    assert "overnight/" not in predicate_text
    assert "cycle-1" not in predicate_text

    # Every ceremony artifact named for auditability must live under the
    # abolished-inventory base dir, never in the live phase map.
    assert inventory["base_dir"].startswith("docs/dev/overnight/")
    assert "overnight/" not in json.dumps(contract["single_writer_map"])


def test_durability_block_records_the_tracked_home_and_superseded_draft(contract):
    dur = contract["durability"]
    assert dur["contract_path"] == CONTRACT_REL
    assert dur["tracked_eligible"] is True
    assert dur["superseded_draft_path"] == SUPERSEDED_DRAFT_REL
    assert dur["superseded_draft_sha256"] == SUPERSEDED_DRAFT_SHA256

    # The declared path is where the contract actually lives, and the predicate
    # LANE-DOC evaluates binds to that same path — no split-brain.
    assert (REPO_ROOT / dur["contract_path"]).is_file()
    assert any(
        dur["contract_path"] in clause
        for clause in contract["lane_doc_precondition"]["predicate"]
    ), "lane_doc_precondition must bind to durability.contract_path"


def test_superseded_draft_is_preserved_byte_for_byte(contract):
    """The gitignored draft is non-authoritative evidence: keep it, never amend it."""
    draft = REPO_ROOT / contract["durability"]["superseded_draft_path"]
    assert draft.is_file(), "superseded draft must be preserved as evidence"
    assert _sha256(draft) == SUPERSEDED_DRAFT_SHA256, "superseded draft bytes drifted"


def test_contract_path_is_clone_durable(contract):
    """git must be able to stage the contract: no ignore rule may match it."""
    import subprocess

    ignored = subprocess.run(
        ["git", "check-ignore", "-v", "--", contract["durability"]["contract_path"]],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert ignored.returncode != 0, (
        "contract path is gitignored and cannot be staged: " + ignored.stdout.strip()
    )

    # Control: the superseded draft IS ignored — this is precisely why it moved.
    draft_ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--", SUPERSEDED_DRAFT_REL],
        cwd=REPO_ROOT,
    )
    assert draft_ignored.returncode == 0, (
        "expected the superseded draft to be gitignored; if it is not, the "
        "durability rationale needs revisiting"
    )
