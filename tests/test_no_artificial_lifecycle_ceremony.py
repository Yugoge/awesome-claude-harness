"""Prevent host metadata ceremonies from becoming ordinary lifecycle gates."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_close_and_qa_do_not_require_human_reload_evidence() -> None:
    close_contract = (ROOT / "commands" / "close.md").read_text()
    qa_contract = (ROOT / "agents" / "qa.md").read_text()

    forbidden = (
        "validate-lifecycle-close-evidence.py",
        "human_confirmation_reference_sha256_values",
        "receipt_stage\": \"post_live",
        "Lifecycle evidence receipt",
    )
    for marker in forbidden:
        assert marker not in close_contract
        assert marker not in qa_contract


def test_artificial_close_validator_is_not_a_product_surface() -> None:
    assert not (ROOT / "scripts" / "validate-lifecycle-close-evidence.py").exists()


def test_superseded_ceremony_tests_are_not_active() -> None:
    manifest = (ROOT / "tests" / "generated" / "manifest.json").read_text()
    assert '"task_id": "dev-20260722-081638"' not in manifest
