"""Prevent host metadata ceremonies from becoming ordinary lifecycle gates."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_CEREMONY_MARKERS = (
    "validate-lifecycle-close-evidence.py",
    "human_confirmation_reference_sha256_values",
    "receipt_stage\": \"post_live",
    "Lifecycle evidence receipt",
)


def test_active_product_surfaces_do_not_require_human_reload_evidence() -> None:
    roots = (ROOT / "commands", ROOT / "agents", ROOT / "hooks", ROOT / "scripts")
    excluded_parts = {"__pycache__", "tests"}
    product_files = (
        path
        for root in roots
        for path in root.rglob("*")
        if path.is_file() and not excluded_parts.intersection(path.parts)
    )

    violations = []
    for path in product_files:
        text = path.read_text(errors="ignore")
        for marker in FORBIDDEN_CEREMONY_MARKERS:
            if marker in text:
                violations.append(f"{path.relative_to(ROOT)}: {marker}")
    assert violations == []


def test_artificial_close_validator_is_not_a_product_surface() -> None:
    assert not (ROOT / "scripts" / "validate-lifecycle-close-evidence.py").exists()
