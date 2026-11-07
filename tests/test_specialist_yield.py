"""Unit tests for specialist_yield library.

Tests use a tmp dir for the yield log and the bundled production policy file
(or a tmp policy when overrides are needed). Production state is never touched.

Run (from the repository root): python3 -m unittest tests.test_specialist_yield
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = str(REPO_ROOT / "hooks")
if HOOKS_DIR not in sys.path:
    sys.path.insert(0, HOOKS_DIR)

from lib import specialist_yield  # noqa: E402


PROD_POLICY_PATH = str(REPO_ROOT / "policies" / "specialist-degradation.v1.json")


def _seed_log(path: Path, records: list[dict]) -> None:
    lines = ["// specialist-yield-log v1 (test fixture)\n"]
    for rec in records:
        lines.append(json.dumps(rec, sort_keys=True) + "\n")
    path.write_text("".join(lines), encoding="utf-8")


def _make_record(
    specialist: str,
    classification: str,
    cycle: int,
    action: str = "active",
) -> dict:
    return {
        "timestamp": f"2026-04-26T00:00:{cycle:02d}Z",
        "specialist_type": specialist,
        "session_id": "sess-test",
        "cycle_id": cycle,
        "classification": classification,
        "action": action,
        "source_record_path": f"/tmp/report-{cycle}.json",
    }


def _restore_env(saved: dict) -> None:
    for key, val in saved.items():
        _restore_one(key, val)


def _restore_one(key: str, val: str | None) -> None:
    if val is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = val


class SpecialistYieldTest(unittest.TestCase):
    """Cover the four required scenarios for get_degradation_state."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._log_path = Path(self._tmpdir.name) / "yield-log.jsonl"
        self._saved_env = {
            "SPECIALIST_YIELD_LOG_PATH": os.environ.get("SPECIALIST_YIELD_LOG_PATH"),
            "SPECIALIST_YIELD_POLICY_PATH": os.environ.get("SPECIALIST_YIELD_POLICY_PATH"),
        }
        os.environ["SPECIALIST_YIELD_LOG_PATH"] = str(self._log_path)
        os.environ["SPECIALIST_YIELD_POLICY_PATH"] = PROD_POLICY_PATH

    def tearDown(self) -> None:
        _restore_env(self._saved_env)
        self._tmpdir.cleanup()

    def test_low_yield_3_consecutive(self) -> None:
        """3 prior low_yield records -> state=degraded, action=reduce_budget_50pct."""
        records = [
            _make_record("architect", "low_yield", 1),
            _make_record("architect", "low_yield", 2),
            _make_record("architect", "low_yield", 3),
        ]
        _seed_log(self._log_path, records)
        result = specialist_yield.get_degradation_state("architect")
        self.assertEqual(result["state"], "degraded")
        self.assertEqual(result["action"], "reduce_budget_50pct")
        self.assertEqual(len(result["source_records"]), 3)

    def test_clean_sweep_5_consecutive(self) -> None:
        """5 prior clean_sweep records -> state=skipped."""
        records = [_make_record("architect", "clean_sweep", i) for i in range(1, 6)]
        _seed_log(self._log_path, records)
        result = specialist_yield.get_degradation_state("architect")
        self.assertEqual(result["state"], "skipped")
        self.assertEqual(result["action"], "skip_next_cycle")

    def test_productive_resets(self) -> None:
        """2 low_yield + 1 productive -> active (productive resets the run)."""
        records = [
            _make_record("architect", "low_yield", 1),
            _make_record("architect", "low_yield", 2),
            _make_record("architect", "productive", 3),
        ]
        _seed_log(self._log_path, records)
        result = specialist_yield.get_degradation_state("architect")
        self.assertEqual(result["state"], "active")
        self.assertEqual(result["action"], "active")

    def test_missing_history(self) -> None:
        """Empty log -> active, reason mentions empty history."""
        _seed_log(self._log_path, [])
        result = specialist_yield.get_degradation_state("architect")
        self.assertEqual(result["state"], "active")
        self.assertIn("empty", result["reason"].lower())
        self.assertEqual(result["source_records"], [])

    def test_without_a_project_policy_the_harness_policy_applies(self) -> None:
        """No project policy: the harness's policies/specialist-degradation.v1.json
        decides (its ui-specialist override needs 4 low_yield runs, not 3)."""
        os.environ["SPECIALIST_YIELD_POLICY_PATH"] = str(Path(self._tmpdir.name) / "absent.json")
        declared = json.loads(Path(PROD_POLICY_PATH).read_text(encoding="utf-8"))
        threshold = declared["per_specialist_overrides"]["ui-specialist"]["low_yield_threshold"]
        records = [_make_record("ui-specialist", "low_yield", i) for i in range(1, threshold)]
        _seed_log(self._log_path, records)
        self.assertEqual(specialist_yield.get_degradation_state("ui-specialist")["state"], "active")
        _seed_log(self._log_path, records + [_make_record("ui-specialist", "low_yield", threshold)])
        self.assertEqual(specialist_yield.get_degradation_state("ui-specialist")["state"], "degraded")

    def test_no_readable_policy_is_the_fail_safe_default(self) -> None:
        os.environ["SPECIALIST_YIELD_POLICY_PATH"] = str(Path(self._tmpdir.name) / "absent.json")
        _seed_log(self._log_path, [_make_record("architect", "low_yield", i) for i in range(1, 6)])
        resolve_optional = specialist_yield.claude_home.resolve_optional
        specialist_yield.claude_home.resolve_optional = lambda relpath: None
        try:
            result = specialist_yield.get_degradation_state("architect")
        finally:
            specialist_yield.claude_home.resolve_optional = resolve_optional
        self.assertEqual(result["state"], "active")
        self.assertIn("policy unreadable", result["reason"])


if __name__ == "__main__":
    unittest.main()
