"""AC5: guard cycle-diff mode computes active_tests_count from per-file pytest-collectable subset; fail-closed on environment failure.

Source: docs/dev/acceptance-criteria-20260529-081014.json AC5.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
GUARD = REPO / "scripts" / "qa-manifest-guard.py"


def _run_guard(args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["python3", str(GUARD), *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


@pytest.fixture
def synthetic_diff(tmp_path: Path):
    test_file = tmp_path / "test_force_include_synthetic.py"
    test_file.write_text("def test_x():\n    assert True\n")
    mod_file = tmp_path / "some_module.py"
    mod_file.write_text("VALUE = 1\n")
    return test_file, mod_file


def test_force_include_one_collectable(synthetic_diff):
    test_file, mod_file = synthetic_diff
    rc, stdout, stderr = _run_guard([
        "--cycle-diff-files", f"{test_file},{mod_file}",
        "--collect-only-cmd", "pytest --collect-only",
    ])
    assert rc == 0, f"expected exit 0, got {rc}; stderr={stderr!r}"
    payload = json.loads(stdout.strip())
    assert payload["verdict"] == "ok"
    assert payload["active_tests_count"] == 1


def test_empty_diff_vacuous_acknowledged():
    rc, stdout, stderr = _run_guard([
        "--cycle-diff-files", "",
        "--collect-only-cmd", "pytest --collect-only",
    ])
    assert rc == 0
    payload = json.loads(stdout.strip())
    assert payload["verdict"] == "ok_vacuous_acknowledged"
    assert "no pytest-collectable files in cycle diff" in payload["vacuous_reason"]


def test_no_py_files_vacuous_acknowledged():
    rc, stdout, stderr = _run_guard([
        "--cycle-diff-files", "docs/foo.md,README.md",
        "--collect-only-cmd", "pytest --collect-only",
    ])
    assert rc == 0
    payload = json.loads(stdout.strip())
    assert payload["verdict"] == "ok_vacuous_acknowledged"
    assert "no pytest-collectable files in cycle diff" in payload["vacuous_reason"]


def test_missing_collect_only_cmd_flag(synthetic_diff):
    test_file, _ = synthetic_diff
    rc, stdout, stderr = _run_guard([
        "--cycle-diff-files", str(test_file),
    ])
    assert rc == 3, f"expected exit 3, got {rc}; stdout={stdout!r}"
    payload = json.loads(stderr.strip())
    assert payload["verdict"] == "guard_blocked"
    assert payload["guard_reason"]


def test_missing_cycle_diff_files_flag():
    rc, stdout, stderr = _run_guard([
        "--collect-only-cmd", "pytest --collect-only",
    ])
    assert rc == 3, f"expected exit 3, got {rc}; stdout={stdout!r}"
    payload = json.loads(stderr.strip())
    assert payload["verdict"] == "guard_blocked"
    assert payload["guard_reason"]


def test_bogus_collect_only_command_fail_closed(synthetic_diff):
    test_file, _ = synthetic_diff
    rc, stdout, stderr = _run_guard([
        "--cycle-diff-files", str(test_file),
        "--collect-only-cmd", "this-binary-does-not-exist --collect-only",
    ])
    assert rc == 3, f"expected exit 3, got {rc}; stdout={stdout!r}"
    payload = json.loads(stderr.strip())
    assert payload["verdict"] == "guard_blocked"
    reason = payload["guard_reason"].lower()
    assert any(k in reason for k in ("not found", "no such file", "errno")), \
        f"expected command-not-found indicator, got: {payload['guard_reason']!r}"
