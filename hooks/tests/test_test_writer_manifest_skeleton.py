"""The test-writer's manifest carries each test's skeleton; dev writes the test file
(agents/test-writer.md, agents/dev.md "Generated tests"). schemas/test-writer-manifest.v1.json
holds the rule for G2 at the test-writer's stop: validate_artifact_for_obligation is the
call G2 makes on the path the test-writer's obligation declares.

A 1.1 manifest is the earlier contract's (its test-writer wrote the skeleton files
itself): a session still running that text must pass unchanged (acceptance 17).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
sys.path[:] = [entry for entry in sys.path if entry != str(HOOKS)]
sys.path.insert(0, str(HOOKS))

from lib import contract_runtime as runtime  # noqa: E402

ENTRY = {"task_id": "T1", "ac_id": "AC-01", "ac_uid": "b0fdbbdc0bece29b", "type": "api",
         "file": "tests/generated/T1/test_AC01_b0fdbbdc0bece29b.py", "status": "active", "hook_check": {}}


def _check(tmp_path: Path, version: str, **entry) -> dict:
    path = tmp_path / "tests" / "generated" / "T1" / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": version, "task_id": "T1", "generated_at": "2026-10-30T00:00:00Z",
                                "active_tests": [dict(ENTRY, **entry)], "archived_tests": []}), encoding="utf-8")
    return runtime.validate_artifact_for_obligation(str(path), "test-writer-manifest.v1")


def test_an_entry_with_its_skeleton_passes(tmp_path):
    assert _check(tmp_path, "1.2", skeleton="import pytest\n")["status"] == "pass"


@pytest.mark.parametrize("skeleton", [None, ""])
def test_an_entry_without_its_skeleton_is_returned_to_the_test_writer(tmp_path, skeleton):
    result = _check(tmp_path, "1.2", **({} if skeleton is None else {"skeleton": skeleton}))
    assert result["status"] == "fail"
    assert any("skeleton" in e or "non-empty" in e for e in result["errors"]), result


def test_a_manifest_of_the_earlier_contract_passes_without_skeletons(tmp_path):
    assert _check(tmp_path, "1.1")["status"] == "pass"
