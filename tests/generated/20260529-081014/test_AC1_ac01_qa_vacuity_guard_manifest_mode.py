"""AC1: QA empty-active vacuity guard rejects smoking-gun fixture at runtime (manifest mode).

Source: docs/dev/acceptance-criteria-20260529-081014.json AC1.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
GUARD = REPO / "scripts" / "qa-manifest-guard.py"


def _run_guard(stdin_payload: dict) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["python3", str(GUARD)],
        input=json.dumps(stdin_payload),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_smoking_gun_rejected():
    fixture = {
        "manifest_exists": False,
        "active_tests_count": 0,
        "active_tests_importable": True,
        "pytest_collected_ok": True,
        "pytest_failures": [],
    }
    rc, stdout, stderr = _run_guard(fixture)
    assert rc == 2, f"expected exit 2, got {rc}; stdout={stdout!r} stderr={stderr!r}"
    payload = json.loads(stderr.strip())
    assert payload["verdict"] == "vacuous_rejected"
    assert payload["reason"]


def test_valid_non_vacuous_ok():
    fixture = {
        "manifest_exists": True,
        "active_tests_count": 3,
        "active_tests_importable": True,
        "pytest_collected_ok": True,
        "pytest_failures": [],
    }
    rc, stdout, stderr = _run_guard(fixture)
    assert rc == 0, f"expected exit 0, got {rc}; stderr={stderr!r}"
    payload = json.loads(stdout.strip())
    assert payload["verdict"] == "ok"


def test_explicit_vacuous_acknowledged():
    fixture = {
        "manifest_exists": False,
        "active_tests_count": 0,
        "active_tests_importable": True,
        "pytest_collected_ok": None,
        "pytest_failures": [],
        "vacuous_due_to_empty_active_set": True,
        "vacuous_reason": "cycle modified no pytest-collectable files",
    }
    rc, stdout, stderr = _run_guard(fixture)
    assert rc == 0, f"expected exit 0, got {rc}; stderr={stderr!r}"
    payload = json.loads(stdout.strip())
    assert payload["verdict"] == "ok_vacuous_acknowledged"
