"""Prevent host metadata ceremonies from becoming ordinary lifecycle gates."""

import json
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


def test_installed_projections_do_not_reintroduce_the_ceremony() -> None:
    installed_surfaces = (
        Path.home() / ".agents" / "skills" / "close" / "SKILL.md",
        Path.home() / ".codex" / "agents" / "qa.toml",
        Path.home() / ".codex" / "claude-compat" / "command-registry.json",
        Path.home() / ".codex" / "hooks" / "codex_native_harness.py",
        Path.home() / ".codex" / "hooks.json",
    )

    violations = []
    for path in installed_surfaces:
        if not path.is_file():
            continue
        text = path.read_text(errors="ignore")
        for marker in FORBIDDEN_CEREMONY_MARKERS:
            if marker in text:
                violations.append(f"{path}: {marker}")
    assert violations == []


def test_artificial_close_validator_is_not_a_product_surface() -> None:
    assert not (ROOT / "scripts" / "validate-lifecycle-close-evidence.py").exists()


def test_superseded_ceremony_tests_are_not_active() -> None:
    manifest = json.loads(
        (ROOT / "tests" / "generated" / "manifest.json").read_text()
    )
    active_task_ids = {task["task_id"] for task in manifest["tasks"]}

    # This was the artificial proof-ceremony task. The r03 task is its corrected,
    # configured-entrypoint replacement and intentionally remains active.
    assert "dev-20260722-081638" not in active_task_ids
