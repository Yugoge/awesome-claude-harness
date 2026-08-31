"""LANE-B core seams for the later POL/BIND single-writer integration."""

from __future__ import annotations

import copy
import random
import shlex
import shutil
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
HOOKS = ROOT / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))
from lib import agent_temp_targets, session_resources


@pytest.fixture(autouse=True)
def _external_trusted_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trust_root = tmp_path.parent / f"{tmp_path.name}-laneb-trust"
    trust_root.mkdir(mode=0o700)
    monkeypatch.setenv(session_resources.TRUST_ROOT_ENV, str(trust_root))
    monkeypatch.setenv(session_resources.TRUST_KEY_ENV, "bc" * 32)
    yield
    shutil.rmtree(trust_root, ignore_errors=True)


def _binding() -> dict:
    return {
        "claude_session_id": "claude-a",
        "resource_session_id": "resource-a",
        "role": "dev",
        "dispatch_id": "dispatch-a",
        "agent_id": "dispatch-a",
        "command": "dev",
        "workflow_instance_id": "workflow-a",
        "workflow_generation": 1,
        "spec_id": "20260808-035658",
    }


def _synthetic_bind_transform(root: Path, binding: dict, tool_input: dict) -> dict:
    """Model the BIND-owned seam without editing or claiming its production hook."""
    managed = session_resources.managed_environment(root, binding)
    prefix = " ".join(f"{key}={shlex.quote(value)}" for key, value in managed.items())
    updated = copy.deepcopy(tool_input)
    updated["command"] = f"env {prefix} {tool_input['command']}"
    return {"hookSpecificOutput": {"updatedInput": updated}}


def test_lane_b_cores_emit_no_updated_input_and_preserve_provider_boundary(tmp_path: Path) -> None:
    binding = _binding()
    session_resources.provision(tmp_path, binding)
    assert "updatedInput" not in session_resources.managed_environment(tmp_path, binding)
    assert "updatedInput" not in agent_temp_targets.analyze_command("touch /tmp/x")
    assert "pretool-overnight-hook-guard.py" not in {
        "hooks/lib/session_resources.py",
        "hooks/lib/agent_temp_targets.py",
    }


def test_complete_tool_input_copy_changes_only_command(tmp_path: Path) -> None:
    binding = _binding()
    provisioned = session_resources.provision(tmp_path, binding)
    original = {
        "command": "python -c 'import tempfile; print(tempfile.mkstemp()[1])'",
        "timeout": 12345,
        "description": "retain me",
        "run_in_background": False,
        "nested": {"unchanged": [1, True, None]},
    }
    response = _synthetic_bind_transform(tmp_path, binding, original)
    updated = response["hookSpecificOutput"]["updatedInput"]
    assert {key: value for key, value in updated.items() if key != "command"} == {
        key: value for key, value in original.items() if key != "command"
    }
    for name in ("TMPDIR", "TMP", "TEMP"):
        assert f"{name}={provisioned['managed_temp_path']}" in updated["command"]
    assert original["command"] in updated["command"]
    assert original == {
        "command": "python -c 'import tempfile; print(tempfile.mkstemp()[1])'",
        "timeout": 12345,
        "description": "retain me",
        "run_in_background": False,
        "nested": {"unchanged": [1, True, None]},
    }


def test_randomized_merge_has_exactly_one_synthetic_complete_producer(tmp_path: Path) -> None:
    binding = _binding()
    session_resources.provision(tmp_path, binding)
    original = {"command": "pytest -q", "timeout": 99, "description": "matrix"}
    responses = [
        {"decision": "allow", "owner": "POL", "updated_input_count": 0},
        {"decision": "allow", "owner": "other", "updated_input_count": 0},
        _synthetic_bind_transform(tmp_path, binding, original),
    ]
    for seed in range(32):
        shuffled = list(responses)
        random.Random(seed).shuffle(shuffled)
        producers = [
            item
            for item in shuffled
            if isinstance(item.get("hookSpecificOutput"), dict)
            and "updatedInput" in item["hookSpecificOutput"]
        ]
        assert len(producers) == 1
        merged = producers[0]["hookSpecificOutput"]["updatedInput"]
        assert merged["timeout"] == 99 and merged["description"] == "matrix"


def test_overnight_bwrap_and_managed_env_share_one_command_owner(tmp_path: Path) -> None:
    binding = _binding()
    provisioned = session_resources.provision(tmp_path, binding)
    original = {
        "command": "bwrap --ro-bind / / -- pytest -q",
        "timeout": 10,
        "description": "overnight",
    }
    updated = _synthetic_bind_transform(tmp_path, binding, original)["hookSpecificOutput"]["updatedInput"]
    assert "bwrap --ro-bind / / -- pytest -q" in updated["command"]
    assert provisioned["managed_temp_path"] in updated["command"]
    assert updated["timeout"] == original["timeout"]
