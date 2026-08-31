from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ACCOUNTING = ROOT / "scripts/check-todo-accounting.py"
FIXTURE = ROOT / "tests/fixtures/dev-todo-canonical-before.v1.json"


def _run_accounting() -> dict:
    result = subprocess.run(
        [sys.executable, str(ACCOUNTING), "--project-root", str(ROOT)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert result.stderr == ""
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def report() -> dict:
    return _run_accounting()


def test_accounting_cli_passes_deterministically(report: dict):
    assert report["validator"] == "dev-todo-accounting.v1"
    assert report["status"] == "pass"
    assert report["violations"] == []
    assert _run_accounting() == report


def test_exact_17_item_before_fixture_is_bound(report: dict):
    fixture = json.loads(FIXTURE.read_text())
    assert fixture["$schema"] == "dev-todo-canonical-before.v1"
    assert fixture["schema_version"] == 1
    assert fixture["item_count"] == 17
    assert len(fixture["todos"]) == 17
    assert (
        fixture["source_sha256"]
        == "1148d94f6d7b144547e0d1e2a5dd7bb829af511ca5dcc06e1af60cb82c640bad"
    )
    assert (
        fixture["stdout_sha256"]
        == "e630d7b7c0c7ad150c5420d3be56d2b94317c47d9b1d88b33d85c8ae849fc544"
    )
    compact = json.dumps(
        fixture["todos"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    assert (
        hashlib.sha256(compact).hexdigest()
        == fixture["canonical_compact_sort_keys_sha256"]
    )
    assert report["before"]["items"] == 17


@pytest.mark.parametrize("lanes", [1, 10])
def test_current_17_items_account_for_18_calls(report: dict, lanes: int):
    formula = report["formulas"]["before"]
    assert formula["initial"] + formula["combined_boundaries"] + formula["final"] == 18
    assert formula["fanout_multiplier"] == 1
    assert formula["one_lane_total" if lanes == 1 else "ten_lane_total"] == 18
    assert report["before_validator"]["accepted_call_count"] == 18


@pytest.mark.parametrize("lanes", [1, 10])
def test_nine_phases_account_for_10_calls(report: dict, lanes: int):
    formula = report["formulas"]["after"]
    assert formula["initial"] + formula["combined_boundaries"] + formula["final"] == 10
    assert formula["fanout_multiplier"] == 1
    assert formula["one_lane_total" if lanes == 1 else "ten_lane_total"] == 10
    assert report["after_validator"]["accepted_call_count"] == 10
    assert report["after"]["items"] == 9


def test_old_steps_1_through_17_are_covered_exactly_once(report: dict):
    assert report["old_step_coverage_once"] is True
    assert sorted(report["old_step_coverage"]) == list(range(1, 18))
    assert len(report["old_step_coverage"]) == 17


def test_real_generic_validators_accept_every_projected_transition(report: dict):
    assert report["before_validator"]["valid_transition_errors"] == []
    assert report["after_validator"]["valid_transition_errors"] == []


@pytest.mark.parametrize(
    "guard",
    [
        "max_one_completion",
        "pending_to_completed",
        "multiple_in_progress",
        "out_of_order",
        "content_immutable",
        "full_list",
    ],
)
def test_generic_invalid_transitions_remain_rejected(report: dict, guard: str):
    assert report["before_validator"]["invalid_cases"][guard] is True
    assert report["after_validator"]["invalid_cases"][guard] is True
    assert report["after_validator"]["invalid_details"][guard]


def test_five_real_subagent_guards_remain(report: dict):
    assert report["subagent_guard_sequence"] == ["ba", "qa", "graphify", "dev", "qa"]
    guards = report["after_validator"]["subagent_guards"]
    assert len(guards) == 5
    assert [item["role"] for item in guards] == ["ba", "qa", "graphify", "dev", "qa"]
    assert all(item["missing_call_rejected"] for item in guards)
    assert all(item["recorded_call_accepted"] for item in guards)


def test_dev_command_remains_exact_16_item_control(report: dict):
    control = report["controls"]["dev_command"]
    assert control == {
        "canonical_compact_sort_keys_sha256": "2cd3eb2064e51717036e8777526501d3756a63b52b43a6b4f29dbd36d6f3e748",
        "exit_code": 0,
        "items": 16,
        "mode": "0755",
        "path": "scripts/todo/dev-command.py",
        "source_bytes": 2778,
        "source_sha256": "8e0fb9df1e6b40bfcf67a0cca61ca8fced04e5563ea653dfb0e48dd83ba10300",
        "stderr_bytes": 0,
        "stdout_bytes": 2818,
        "stdout_sha256": "8e308ca4f997e1cc5b1c5706a93ac15a776f5c021c3e3b1323db1062035fc8c6",
    }


def test_actual_dev_overnight_remains_exact_22_item_control(report: dict):
    control = report["controls"]["dev_overnight"]
    assert control == {
        "canonical_compact_sort_keys_sha256": "132f9b0b1e149a984498321b2870572f9373fbab562e38c026877ef028084bb0",
        "exit_code": 0,
        "items": 22,
        "mode": "0644",
        "path": "scripts/todo/dev-overnight.py",
        "source_bytes": 4189,
        "source_sha256": "414ce617a3010b52d8d0d1434083ba30ab3bb6edc1b239dd7a736d52df50fdd8",
        "stderr_bytes": 0,
        "stdout_bytes": 4168,
        "stdout_sha256": "9e22b88b2839b682456b85eda1f0801f3d146cf06f8f544bd40c4cc4f9591105",
    }


def test_commands_and_generic_hooks_are_exact_read_only_controls(report: dict):
    expected = {
        "hooks/lib/todo_canonical.py": "a6725b02fe6bd255308df8a9bcf59153bdb90c89d3962ea22d529ba6f347a5ec",
        "hooks/pretool-todo-validate.py": "57a0319cf259b5e5d716388b091e4f2895e1cbf155849543faf821ec93da9d80",
        "hooks/posttool-todo-sequence.py": "d25d9326ae317eccda6c3514531fe00483467a4b66a189b96e4b5d7a76d3fb41",
        "hooks/posttool-todo-count.py": "7f8ec8a794c36c26fcce13577728e3c77a08a1bca8b8c9154b3c6f28e4f6c918",
        "hooks/prompt-workflow.py": "c27c35e457b93455d0e52cea09f1f9b5593ab1df681b2e14826305eed6830f65",
        "hooks/posttool-todo-tracker.py": "ceb22264bbf3216d630b67676c282bb8818f40469a549b8932690a35546c8511",
        "hooks/pretool-workflow-gate.py": "a5b1cd36da1311dd08c590619417d5c0e773ce872125f5218ad0e77adbbac781",
        "hooks/posttool-subagent-track.py": "746916ac148fd09346e06bf15b8c2b3eba9c9936058f553b5077be2327942c68",
        "commands/dev.md": "a5dd14cd9c57e1e444c81dbd41f7153db73b19e245119cf9531ee52a9926e7f0",
        "commands/dev-command.md": "46a0ba2c4f8fff73aee6e16ed7c3a7d8b0bd611340a7dc04a9d47b40a0d5ff7f",
        "commands/dev-overnight.md": "413703685d76cb5620e5a00d852aa7a9d6c48c43a845519a5b959fed11566898",
    }
    assert report["read_only_sha256"] == expected


def test_historical_accounting_nonclaims_are_explicit(report: dict):
    assert report["historical_nonclaims"] == [
        "no exact-eight sequence",
        "no per-lane Todo multiplier",
        "no subagent Todo calls",
    ]
