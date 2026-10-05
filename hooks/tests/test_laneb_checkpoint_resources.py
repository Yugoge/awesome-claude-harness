"""LANE-B checkpoint transaction and CLI provider tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
HOOKS = ROOT / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))
from lib import checkpoint_resources as resources

CLI = ROOT / "scripts" / "spec-check.py"


def _checkpoint(index: int, state: str) -> dict:
    return {
        "id": f"cp-{index:02d}",
        "action": f"action-{index}",
        "state": state,
        "waived_reason": "old-waiver" if state.startswith("waived") else None,
        "updated_at": "old",
        "marked_by": "old-owner",
        "audit_history": [{"old": True}],
    }


def _primary(root: Path, *, running: bool = True) -> Path:
    path = root / ".claude/specs/spec-lb/cp-state-dev.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "spec_id": "spec-lb",
                "agent_type": "dev",
                "instance_id": None,
                "generation": 4,
                "agent_id": "primary-owner",
                "is_running": running,
                "checked_in_at": "old",
                "checked_out_at": None,
                "checkpoints": [
                    _checkpoint(1, "done"),
                    _checkpoint(2, "waived-with-reason"),
                ],
                "terminal_artifact": {
                    "path": "old-report",
                    "exists": True,
                    "validated_at": "old",
                },
                "audit_history": [{"primary": True}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _run_cli(root: Path, owner: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(CLI),
            "check-in",
            "--spec-id",
            "spec-lb",
            "--agent",
            "dev",
            "--agent-id",
            owner,
        ],
        text=True,
        capture_output=True,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)},
        timeout=30,
    )


def _assert_fresh_clone(payload: dict, owner: str) -> None:
    assert payload["agent_id"] == owner
    assert payload["is_running"] is True
    assert [item["id"] for item in payload["checkpoints"]] == ["cp-01", "cp-02"]
    assert [item["action"] for item in payload["checkpoints"]] == ["action-1", "action-2"]
    assert {item["state"] for item in payload["checkpoints"]} == {"pending"}
    assert {item["waived_reason"] for item in payload["checkpoints"]} == {None}
    for item in payload["checkpoints"]:
        assert "marked_by" not in item
        assert "audit_history" not in item
    assert payload["terminal_artifact"] == {
        "path": None,
        "exists": False,
        "validated_at": None,
    }
    assert "audit_history" not in payload


def test_populated_reset_clone_preserves_primary_bytes(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    before = primary.read_bytes()
    result = resources.allocate_numbered(primary, agent_id="fresh-owner")
    assert result["status"] == "pass" and result["instance_id"] == 2
    _assert_fresh_clone(json.loads(Path(result["path"]).read_text()), "fresh-owner")
    assert primary.read_bytes() == before


@pytest.mark.parametrize(
    ("mode", "error"),
    [
        ("missing", resources.CHECKPOINT_TEMPLATE_MISSING),
        ("corrupt", resources.CHECKPOINT_TEMPLATE_CORRUPT),
        ("empty", resources.CHECKPOINT_TEMPLATE_EMPTY),
    ],
)
def test_invalid_primary_fails_exactly_and_mutates_no_json(
    tmp_path: Path, mode: str, error: str
) -> None:
    primary = tmp_path / ".claude/specs/spec-lb/cp-state-dev.json"
    primary.parent.mkdir(parents=True)
    if mode == "corrupt":
        primary.write_text("{", encoding="utf-8")
    elif mode == "empty":
        primary.write_text(json.dumps({"checkpoints": []}), encoding="utf-8")
    before = {path: path.read_bytes() for path in primary.parent.glob("*.json")}
    result = resources.allocate_numbered(primary, agent_id="owner")
    assert result == {"status": "fail", "numbered_path": None, "error_code": error}
    assert {path: path.read_bytes() for path in primary.parent.glob("*.json")} == before
    assert not list(primary.parent.glob("cp-state-dev-[0-9]*.json"))
    assert not (primary.parent / ".cp-checkin.lock").exists()


@pytest.mark.parametrize(
    ("mode", "error"),
    [
        ("missing", resources.CHECKPOINT_TEMPLATE_MISSING),
        ("corrupt", resources.CHECKPOINT_TEMPLATE_CORRUPT),
        ("empty", resources.CHECKPOINT_TEMPLATE_EMPTY),
    ],
)
def test_cli_emits_exact_failure_and_exit_one(
    tmp_path: Path, mode: str, error: str
) -> None:
    primary = tmp_path / ".claude/specs/spec-lb/cp-state-dev.json"
    primary.parent.mkdir(parents=True)
    if mode == "corrupt":
        primary.write_text("{", encoding="utf-8")
    elif mode == "empty":
        primary.write_text(json.dumps({"checkpoints": []}), encoding="utf-8")
    before = {path: path.read_bytes() for path in primary.parent.glob("*.json")}
    result = _run_cli(tmp_path, "owner")
    assert result.returncode == 1
    assert json.loads(result.stdout) == {
        "status": "fail",
        "numbered_path": None,
        "error_code": error,
    }
    assert {path: path.read_bytes() for path in primary.parent.glob("*.json")} == before


def test_core_48_way_allocation_is_linearizable_and_populated(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    before = primary.read_bytes()
    owners = [f"core-owner-{index}" for index in range(48)]
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(
            pool.map(lambda owner: resources.allocate_numbered(primary, agent_id=owner), owners)
        )
    assert all(result["status"] == "pass" for result in results)
    assert len({result["path"] for result in results}) == 48
    observed = {
        json.loads(Path(result["path"]).read_text())["agent_id"] for result in results
    }
    assert observed == set(owners)
    for result in results:
        _assert_fresh_clone(json.loads(Path(result["path"]).read_text()), json.loads(Path(result["path"]).read_text())["agent_id"])
    assert primary.read_bytes() == before


@pytest.mark.parametrize("run", range(2))
def test_cli_48_way_allocation_is_linearizable_repeated(tmp_path: Path, run: int) -> None:
    root = tmp_path / f"run-{run}"
    primary = _primary(root)
    before = primary.read_bytes()
    owners = [f"cli-owner-{index}" for index in range(48)]
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda owner: _run_cli(root, owner), owners))
    assert all(result.returncode == 0 for result in results), [
        result.stderr for result in results if result.returncode
    ]
    numbered = sorted(primary.parent.glob("cp-state-dev-[0-9]*.json"))
    assert len(numbered) == 48
    payloads = [json.loads(path.read_text()) for path in numbered]
    assert {payload["agent_id"] for payload in payloads} == set(owners)
    assert all(payload["checkpoints"] and {cp["state"] for cp in payload["checkpoints"]} == {"pending"} for payload in payloads)
    assert primary.read_bytes() == before


def test_same_owner_is_idempotent_under_directory_transaction(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    first = resources.allocate_numbered(primary, agent_id="same")
    before = Path(first["path"]).read_bytes()
    second = resources.allocate_numbered(primary, agent_id="same")
    assert second["status"] == "pass" and second["existing_owner"] is True
    assert second["path"] == first["path"]
    assert Path(first["path"]).read_bytes() == before


def test_slot_ten_owner_replay_is_concurrently_idempotent(tmp_path: Path) -> None:
    primary = _primary(tmp_path)
    allocated = [
        resources.allocate_numbered(primary, agent_id=f"owner-{index}")
        for index in range(2, 11)
    ]
    slot_ten = allocated[-1]
    assert slot_ten["instance_id"] == 10
    before = Path(slot_ten["path"]).read_bytes()

    with ThreadPoolExecutor(max_workers=12) as pool:
        replayed = list(
            pool.map(
                lambda _index: resources.allocate_numbered(
                    primary, agent_id="owner-10"
                ),
                range(24),
            )
        )

    assert all(result["status"] == "pass" for result in replayed)
    assert all(result["existing_owner"] is True for result in replayed)
    assert {result["instance_id"] for result in replayed} == {10}
    assert {result["path"] for result in replayed} == {slot_ten["path"]}
    assert Path(slot_ten["path"]).read_bytes() == before
    assert len(list(primary.parent.glob("cp-state-dev-[0-9]*.json"))) == 9


@pytest.mark.parametrize("slot", [10, 19, 99, 100, 199, 1000])
def test_owner_lookup_recognizes_canonical_wide_slots(
    tmp_path: Path, slot: int
) -> None:
    primary = _primary(tmp_path)
    template = json.loads(primary.read_text())
    owner = f"wide-owner-{slot}"
    slot_path = primary.with_name(f"{primary.stem}-{slot}.json")
    slot_path.write_text(
        json.dumps(
            resources.reset_clone(
                template,
                instance_id=slot,
                agent_id=owner,
                now_iso="2026-08-10T00:00:00Z",
            )
        ),
        encoding="utf-8",
    )
    before = slot_path.read_bytes()

    result = resources.allocate_numbered(primary, agent_id=owner)

    assert result["status"] == "pass"
    assert result["existing_owner"] is True
    assert result["instance_id"] == slot
    assert result["path"] == str(slot_path)
    assert slot_path.read_bytes() == before
    assert not primary.with_name(f"{primary.stem}-2.json").exists()


def test_slot_recognition_is_canonical_for_every_integer_at_least_two() -> None:
    for slot in range(2, 2049):
        match = resources._SLOT_RE.fullmatch(f"cp-state-dev-{slot}.json")
        assert match is not None
        assert int(match.group("slot")) == slot

    for alias in (
        "cp-state-dev-0.json",
        "cp-state-dev-1.json",
        "cp-state-dev-00.json",
        "cp-state-dev-01.json",
        "cp-state-dev-02.json",
        "cp-state-dev-0002.json",
        "cp-state-dev-+2.json",
        "cp-state-dev-2.0.json",
        "cp-state-dev-2.json.bak",
    ):
        assert resources._SLOT_RE.fullmatch(alias) is None
