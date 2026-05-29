"""AC4: guard manifest-mode rejects vacuous reports of every observed shape (regression matrix).

Source: docs/dev/acceptance-criteria-20260529-081014.json AC4.
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


VACUOUS_FIXTURES = [
    pytest.param({"active_tests_count": 0, "pytest_collected_ok": True, "pytest_failures": []},
                 id="smoking_gun_shape"),
    pytest.param({"active_tests_count": 0, "pytest_collected_ok": True,
                  "pytest_failures": [{"test": "foo", "reason": "bar"}]},
                 id="true_with_nonempty_failures_still_vacuous"),
    pytest.param({"active_tests_count": 0, "pytest_collected_ok": True},
                 id="true_with_missing_failures_field"),
    pytest.param({"active_tests_count": 0, "pytest_collected_ok": None, "pytest_failures": []},
                 id="null_but_vacuity_undeclared"),
]


@pytest.mark.parametrize("fixture", VACUOUS_FIXTURES)
def test_vacuous_shape_rejected(fixture: dict):
    rc, stdout, stderr = _run_guard(fixture)
    assert rc == 2, f"expected exit 2, got {rc}; stdout={stdout!r} stderr={stderr!r}"
    payload = json.loads(stderr.strip())
    assert payload["verdict"] == "vacuous_rejected"
