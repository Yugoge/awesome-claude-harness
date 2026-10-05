"""LANE-B actor scratch, receipt, and owned-process broker tests."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
HOOKS = ROOT / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))
from lib import session_resources as resources


@pytest.fixture(autouse=True)
def _external_trusted_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trust_root = tmp_path.parent / f"{tmp_path.name}-laneb-trust"
    trust_root.mkdir(mode=0o700)
    monkeypatch.setenv(resources.TRUST_ROOT_ENV, str(trust_root))
    monkeypatch.setenv(resources.TRUST_KEY_ENV, "ab" * 32)
    yield
    shutil.rmtree(trust_root, ignore_errors=True)


def _binding(session: str, dispatch: str, *, role: str = "qa") -> dict:
    return {
        "claude_session_id": f"claude-{session}",
        "resource_session_id": f"resource-{session}",
        "role": role,
        "dispatch_id": dispatch,
        "agent_id": dispatch,
        "command": "dev",
        "workflow_instance_id": f"workflow-{session}",
        "workflow_generation": 1,
        "spec_id": "20260808-035658",
    }


def _receipt(root: Path, binding: dict, status: str = "completed") -> dict:
    return resources.publish_terminal_receipt(
        root,
        claude_session_id=binding["claude_session_id"],
        resource_session_id=binding["resource_session_id"],
        command=binding["command"],
        terminal_status=status,
        workflow_instance_id=binding["workflow_instance_id"],
        workflow_generation=binding["workflow_generation"],
    )


def _digest_tree(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    snapshot: dict[str, str] = {}
    for item in sorted(path.rglob("*")):
        relative = str(item.relative_to(path))
        if item.is_symlink():
            snapshot[relative] = f"symlink:{os.readlink(item)}"
        elif item.is_dir():
            snapshot[relative] = "directory"
        elif item.is_file():
            snapshot[relative] = (
                f"file:{hashlib.sha256(item.read_bytes()).hexdigest()}"
            )
        else:
            snapshot[relative] = "other"
    return snapshot


def _wait_for(path: Path, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {path}")


def _resource_record_paths(root: Path, binding: dict) -> tuple[Path, Path, Path]:
    base = root / ".claude/session-resources"
    resource = base / binding["resource_session_id"]
    return (
        resource / "session.json",
        resource / "terminal.json",
        base / "by-claude-session" / f"{binding['claude_session_id']}.json",
    )


def _trust_record_path(root: Path, binding: dict) -> Path:
    project_sha256 = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()
    return (
        Path(os.environ[resources.TRUST_ROOT_ENV])
        / project_sha256
        / f"{binding['claude_session_id']}.json"
    )


def _combined_snapshot(root: Path, binding: dict) -> dict[str, dict[str, str]]:
    return {
        "project": _digest_tree(root / ".claude"),
        "trust": _digest_tree(_trust_record_path(root, binding).parent),
    }


def _finalized_fixture(root: Path, binding: dict) -> tuple[dict, bytes]:
    authority = resources._trust_configuration(root)
    assert authority.trust_root == Path(os.environ[resources.TRUST_ROOT_ENV])
    trusted = resources._load_trusted_record(
        _trust_record_path(root, binding),
        key=authority.key,
        project_root_sha256=authority.project_root_sha256,
        claude_session_id=binding["claude_session_id"],
    )
    inputs = resources._validated_finalization_inputs(
        root,
        claude_session_id=binding["claude_session_id"],
        resource_session_id=binding["resource_session_id"],
        trusted=trusted,
    )
    unsigned = {
        "schema": resources.SCHEMA_VERSION,
        "trust_schema": resources.TRUST_SCHEMA_VERSION,
        "project_root_sha256": authority.project_root_sha256,
        "claude_session_id": binding["claude_session_id"],
        "resource_session_id": binding["resource_session_id"],
        "workflow_identity_sha256": resources.sha256_json(
            inputs["session_identity"]
        ),
        "actor_binding_sha256": trusted["actor_binding_sha256"],
        "terminal_receipt_sha256": hashlib.sha256(
            inputs["terminal_bytes"]
        ).hexdigest(),
        "owner_records_sha256": inputs["owner_records_sha256"],
        "process_records_sha256": {},
        "trust_revision": trusted["revision"],
        "authorized_at": "2026-08-10T00:00:00Z",
    }
    return resources._sign_trusted_record(unsigned, authority.key), authority.key


def _forbid_process_scan(*_args: object) -> list:
    raise AssertionError("process scan reached before workflow-anchor rejection")


def test_external_trust_root_with_ancestor_alias_into_project_is_rejected_before_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inside_trust = tmp_path / "owner-visible" / "ordinary-parent" / "trust"
    inside_trust.mkdir(parents=True, mode=0o700)
    inside_trust.chmod(0o700)
    alias_parent = tmp_path.parent / f"{tmp_path.name}-ancestor-alias"
    alias_parent.mkdir()
    (alias_parent / "project-alias").symlink_to(tmp_path, target_is_directory=True)
    configured = (
        alias_parent
        / "project-alias"
        / "owner-visible"
        / "ordinary-parent"
        / "trust"
    )
    monkeypatch.setenv(resources.TRUST_ROOT_ENV, str(configured))
    before = _digest_tree(tmp_path)

    with pytest.raises(resources.ResourceError, match="unsafe"):
        resources.provision(tmp_path, _binding("alias-provision", "one"))

    assert _digest_tree(tmp_path) == before
    assert not (tmp_path / ".claude").exists()


def test_ancestor_alias_registry_copy_is_rejected_before_finalization_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding = _binding("alias-finalize", "one")
    provisioned = resources.provision(tmp_path, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "evidence").write_bytes(b"alias-finalize")
    _receipt(tmp_path, binding)
    original_trust = Path(os.environ[resources.TRUST_ROOT_ENV])
    mirrored_trust = tmp_path / "owner-visible" / "mirrored-trust"
    mirrored_trust.parent.mkdir()
    shutil.copytree(original_trust, mirrored_trust)
    alias_parent = tmp_path.parent / f"{tmp_path.name}-finalize-alias"
    alias_parent.mkdir()
    (alias_parent / "project-alias").symlink_to(tmp_path, target_is_directory=True)
    monkeypatch.setenv(
        resources.TRUST_ROOT_ENV,
        str(alias_parent / "project-alias" / "owner-visible" / "mirrored-trust"),
    )
    before = _digest_tree(tmp_path)
    monkeypatch.setattr(resources, "_load_process_records", _forbid_process_scan)

    with pytest.raises(resources.ResourceError, match="unsafe"):
        resources.finalize(
            tmp_path,
            claude_session_id=binding["claude_session_id"],
            resource_session_id=binding["resource_session_id"],
        )

    assert _digest_tree(tmp_path) == before
    assert scratch.exists()


def test_ancestor_swap_during_trust_configuration_creates_no_project_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    external_parent = tmp_path.parent / f"{tmp_path.name}-race-parent"
    external_parent.mkdir()
    configured = external_parent / "trust"
    configured.mkdir(mode=0o700)
    alias_target = tmp_path / "race-alias-target"
    alias_target.mkdir()
    parked_parent = tmp_path.parent / f"{tmp_path.name}-race-parent-parked"
    monkeypatch.setenv(resources.TRUST_ROOT_ENV, str(configured))
    original_private_directory = resources._private_external_directory
    calls = 0

    def swap_after_root_validation(path: Path, root: Path) -> tuple[Path, int]:
        nonlocal calls
        resolved = original_private_directory(path, root)
        calls += 1
        if calls == 1:
            external_parent.rename(parked_parent)
            external_parent.symlink_to(alias_target, target_is_directory=True)
        return resolved

    monkeypatch.setattr(
        resources, "_private_external_directory", swap_after_root_validation
    )
    before = _digest_tree(tmp_path)

    with pytest.raises(resources.ResourceError, match="unsafe|changed"):
        resources.provision(tmp_path, _binding("alias-race-provision", "one"))

    assert _digest_tree(tmp_path) == before
    assert not (alias_target / "trust").exists()
    assert not (tmp_path / ".claude").exists()


def test_validated_trust_root_ordinary_replacement_rejects_before_any_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    external_parent = tmp_path.parent / f"{tmp_path.name}-replacement-parent"
    external_parent.mkdir()
    configured = external_parent / "trust"
    configured.mkdir(mode=0o700)
    parked = external_parent / "validated-trust"
    monkeypatch.setenv(resources.TRUST_ROOT_ENV, str(configured))
    original_private_directory = resources._private_external_directory
    replaced = False

    def replace_after_validation(path: Path, root: Path) -> tuple[Path, int]:
        nonlocal replaced
        resolved = original_private_directory(path, root)
        if not replaced:
            replaced = True
            configured.rename(parked)
            configured.mkdir(mode=0o700)
        return resolved

    monkeypatch.setattr(
        resources, "_private_external_directory", replace_after_validation
    )
    before = _digest_tree(tmp_path)

    with pytest.raises(resources.ResourceError, match="changed|identity"):
        resources.provision(tmp_path, _binding("ordinary-replacement", "one"))

    assert replaced is True
    assert _digest_tree(tmp_path) == before
    assert not (tmp_path / ".claude").exists()
    assert list(configured.iterdir()) == []
    assert list(parked.iterdir()) == []


@pytest.mark.parametrize("replacement", ["fresh", "copied"])
def test_post_provision_trust_root_replacement_rejects_before_finalization_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
) -> None:
    binding = _binding(f"post-provision-replacement-{replacement}", "one")
    provisioned = resources.provision(tmp_path, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "evidence").write_bytes(b"post-provision-replacement")
    _receipt(tmp_path, binding)
    trust_root = Path(os.environ[resources.TRUST_ROOT_ENV])
    parked = trust_root.with_name(f"{trust_root.name}-validated")
    trust_root.rename(parked)
    if replacement == "fresh":
        trust_root.mkdir(mode=0o700)
    else:
        shutil.copytree(parked, trust_root)
        trust_root.chmod(0o700)
    project_before = _digest_tree(tmp_path)
    replacement_before = _digest_tree(trust_root)
    monkeypatch.setattr(resources, "_load_process_records", _forbid_process_scan)

    with pytest.raises(resources.ResourceError, match="absent|identity"):
        resources.finalize(
            tmp_path,
            claude_session_id=binding["claude_session_id"],
            resource_session_id=binding["resource_session_id"],
        )

    assert _digest_tree(tmp_path) == project_before
    assert _digest_tree(trust_root) == replacement_before
    assert scratch.exists()
    if replacement == "fresh":
        assert list(trust_root.iterdir()) == []


def test_ancestor_swap_after_finalize_configuration_rejects_before_process_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    external_parent = tmp_path.parent / f"{tmp_path.name}-finalize-race-parent"
    external_parent.mkdir()
    configured = external_parent / "trust"
    configured.mkdir(mode=0o700)
    monkeypatch.setenv(resources.TRUST_ROOT_ENV, str(configured))
    binding = _binding("alias-race-finalize", "one")
    provisioned = resources.provision(tmp_path, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "evidence").write_bytes(b"alias-race-finalize")
    _receipt(tmp_path, binding)
    alias_target = tmp_path / "race-alias-target"
    alias_target.mkdir()
    shutil.copytree(configured, alias_target / "trust")
    parked_parent = tmp_path.parent / f"{tmp_path.name}-finalize-race-parked"
    original_child_directory = resources._private_external_child_directory

    def swap_after_registry_validation(
        parent: Path, parent_descriptor: int, name: str, root: Path
    ) -> tuple[Path, int]:
        resolved = original_child_directory(
            parent, parent_descriptor, name, root
        )
        external_parent.rename(parked_parent)
        external_parent.symlink_to(alias_target, target_is_directory=True)
        return resolved

    monkeypatch.setattr(
        resources,
        "_private_external_child_directory",
        swap_after_registry_validation,
    )
    monkeypatch.setattr(resources, "_load_process_records", _forbid_process_scan)
    before = _digest_tree(tmp_path)

    with pytest.raises(resources.ResourceError, match="unsafe|changed"):
        resources.finalize(
            tmp_path,
            claude_session_id=binding["claude_session_id"],
            resource_session_id=binding["resource_session_id"],
        )

    assert _digest_tree(tmp_path) == before
    assert scratch.exists()


def test_resolved_external_registry_exact_success_and_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trust_root = tmp_path.parent / f"{tmp_path.name}-resolved-trust" / "registry"
    trust_root.parent.mkdir()
    trust_root.mkdir(mode=0o700)
    monkeypatch.setenv(resources.TRUST_ROOT_ENV, str(trust_root))
    binding = _binding("resolved-success", "one")
    provisioned = resources.provision(tmp_path, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "evidence").write_bytes(b"resolved-success")
    _receipt(tmp_path, binding)

    first = resources.finalize(
        tmp_path,
        claude_session_id=binding["claude_session_id"],
        resource_session_id=binding["resource_session_id"],
    )
    replay = resources.finalize(
        tmp_path,
        claude_session_id=binding["claude_session_id"],
        resource_session_id=binding["resource_session_id"],
    )

    assert first["status"] == replay["status"] == "pass"
    assert first["idempotent"] is False
    assert replay["idempotent"] is True
    assert replay["finalized"] == first["finalized"]
    assert trust_root.resolve() not in (tmp_path.resolve(), *tmp_path.resolve().parents)
    assert not scratch.exists()


def test_four_normalized_bindings_have_actor_exact_directories(tmp_path: Path) -> None:
    manifests = []
    for session in ("A", "B"):
        for dispatch in ("one", "two"):
            manifests.append(resources.provision(tmp_path, _binding(session, dispatch)))
    scratch = {item["scratch_path"] for item in manifests}
    assert len(scratch) == 4
    assert len({item["binding_sha256"] for item in manifests}) == 4
    for item in manifests:
        owner = item["binding"]
        assert Path(item["managed_temp_path"]).parent == Path(item["scratch_path"])
        assert resources.load_actor_manifest(tmp_path, owner)["binding"] == owner
        assert resources.classify_target(tmp_path, owner, Path(item["managed_temp_path"]) / "x")["status"] == "owner"
    first = manifests[0]["binding"]
    sibling = Path(manifests[1]["scratch_path"]) / "x"
    assert resources.classify_target(tmp_path, first, sibling)["status"] == "sibling"
    assert resources.classify_target(tmp_path, first, "/tmp/collision")["status"] == "system_temp"
    assert resources.classify_target(tmp_path, first, "$TMPDIR/dynamic")["status"] == "unresolved"
    assert resources.managed_environment(tmp_path, first) == {
        key: str(Path(manifests[0]["managed_temp_path"]))
        for key in ("TMPDIR", "TMP", "TEMP")
    }


@pytest.mark.parametrize("field", ["claude_session_id", "resource_session_id", "role", "dispatch_id"])
def test_binding_rejects_path_components(tmp_path: Path, field: str) -> None:
    binding = _binding("A", "one")
    binding[field] = "../escape"
    with pytest.raises(resources.ResourceError):
        resources.provision(tmp_path, binding)
    assert not (tmp_path.parent / "escape").exists()


def test_receipt_is_absorbing_idempotent_and_non_destructive(tmp_path: Path) -> None:
    binding = _binding("A", "one")
    provisioned = resources.provision(tmp_path, binding)
    scratch = Path(provisioned["scratch_path"])
    evidence = scratch / "evidence.bin"
    evidence.write_bytes(b"unchanged")
    before = _digest_tree(scratch)
    first = _receipt(tmp_path, binding)
    second = _receipt(tmp_path, binding)
    assert first["status"] == second["status"] == "pass"
    assert second["idempotent"] is True
    assert _digest_tree(scratch) == before
    with pytest.raises(resources.ResourceError):
        _receipt(tmp_path, binding, "cancelled_by_user")
    assert _digest_tree(scratch) == before


def test_missing_or_mismatched_receipt_never_deletes_scratch(tmp_path: Path) -> None:
    binding = _binding("A", "one")
    provisioned = resources.provision(tmp_path, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "keep").write_text("yes")
    before = _digest_tree(scratch)
    with pytest.raises(resources.ResourceError):
        resources.finalize(
            tmp_path,
            claude_session_id=binding["claude_session_id"],
            resource_session_id=binding["resource_session_id"],
        )
    assert _digest_tree(scratch) == before
    _receipt(tmp_path, binding)
    with pytest.raises(resources.ResourceError):
        resources.finalize(
            tmp_path,
            claude_session_id="claude-wrong",
            resource_session_id=binding["resource_session_id"],
        )
    assert _digest_tree(scratch) == before


@pytest.mark.parametrize(
    ("field", "tampered"),
    [
        ("schema", "lane_b.session-resources/v0"),
        ("command", "redev"),
        ("workflow_instance_id", "workflow-stale"),
        ("workflow_generation", 2),
        ("workflow_generation", True),
        ("claude_session_id", "claude-other"),
        ("resource_session_id", "resource-other"),
        ("terminal_status", "not-terminal"),
        ("session_manifest_sha256", "0" * 64),
    ],
)
def test_finalize_rejects_receipt_identity_tamper_before_destructive_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    tampered: object,
) -> None:
    binding = _binding("A", "one")
    provisioned = resources.provision(tmp_path, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "keep").write_bytes(b"receipt-evidence")
    before = _digest_tree(scratch)
    _receipt(tmp_path, binding)
    terminal_path = (
        tmp_path
        / ".claude/session-resources"
        / binding["resource_session_id"]
        / "terminal.json"
    )
    terminal = json.loads(terminal_path.read_text())
    terminal[field] = tampered
    terminal_path.write_text(json.dumps(terminal), encoding="utf-8")

    def destructive_boundary_reached(*_args: object) -> list:
        raise AssertionError("process scan reached before receipt rejection")

    monkeypatch.setattr(resources, "_load_process_records", destructive_boundary_reached)
    with pytest.raises(resources.ResourceError):
        resources.finalize(
            tmp_path,
            claude_session_id=binding["claude_session_id"],
            resource_session_id=binding["resource_session_id"],
        )
    assert _digest_tree(scratch) == before


@pytest.mark.parametrize(
    ("field", "tampered"),
    [
        ("schema", "lane_b.session-resources/v0"),
        ("command", "redev"),
        ("workflow_instance_id", "workflow-stale"),
        ("workflow_generation", 2),
        ("workflow_generation", True),
    ],
)
def test_finalize_rejects_current_pointer_identity_tamper_before_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    tampered: object,
) -> None:
    binding = _binding("A", "one")
    provisioned = resources.provision(tmp_path, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "keep").write_bytes(b"pointer-evidence")
    before = _digest_tree(scratch)
    _receipt(tmp_path, binding)
    pointer_path = (
        tmp_path
        / ".claude/session-resources/by-claude-session"
        / f"{binding['claude_session_id']}.json"
    )
    pointer = json.loads(pointer_path.read_text())
    pointer[field] = tampered
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")

    def destructive_boundary_reached(*_args: object) -> list:
        raise AssertionError("process scan reached before pointer rejection")

    monkeypatch.setattr(resources, "_load_process_records", destructive_boundary_reached)
    with pytest.raises(
        resources.ResourceError,
        match="terminal receipt current pointer identity mismatch",
    ):
        resources.finalize(
            tmp_path,
            claude_session_id=binding["claude_session_id"],
            resource_session_id=binding["resource_session_id"],
        )
    assert _digest_tree(scratch) == before


def test_finalize_accepts_exact_current_workflow_identity(tmp_path: Path) -> None:
    binding = _binding("A", "one")
    binding["workflow_generation"] = 7
    provisioned = resources.provision(tmp_path, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "evidence").write_bytes(b"current-generation")
    _receipt(tmp_path, binding)

    result = resources.finalize(
        tmp_path,
        claude_session_id=binding["claude_session_id"],
        resource_session_id=binding["resource_session_id"],
    )

    assert result["status"] == "pass"
    assert result["signalled"] == []
    assert not scratch.exists()


@pytest.mark.parametrize(
    ("field", "mutation", "value"),
    [
        pytest.param("command", "replace", "redev", id="command-stale"),
        pytest.param("command", "delete", None, id="command-missing"),
        pytest.param("command", "replace", {}, id="command-object"),
        pytest.param(
            "workflow_instance_id",
            "replace",
            "workflow-stale",
            id="instance-stale",
        ),
        pytest.param(
            "workflow_instance_id", "delete", None, id="instance-missing"
        ),
        pytest.param(
            "workflow_instance_id", "replace", {}, id="instance-object"
        ),
        pytest.param("workflow_generation", "replace", 6, id="generation-stale"),
        pytest.param(
            "workflow_generation", "delete", None, id="generation-missing"
        ),
        pytest.param(
            "workflow_generation", "replace", True, id="generation-boolean"
        ),
        pytest.param(
            "workflow_generation", "replace", {}, id="generation-object"
        ),
        pytest.param(
            "workflow_generation", "replace", "7", id="generation-string"
        ),
    ],
)
def test_finalize_rejects_shared_pointer_receipt_identity_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    mutation: str,
    value: object,
) -> None:
    binding = _binding("shared", "one")
    binding["workflow_generation"] = 7
    provisioned = resources.provision(tmp_path, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "evidence").write_bytes(b"shared-mutation-evidence")
    _receipt(tmp_path, binding)
    _session_path, terminal_path, pointer_path = _resource_record_paths(
        tmp_path, binding
    )
    for path in (terminal_path, pointer_path):
        payload = json.loads(path.read_text())
        if mutation == "delete":
            payload.pop(field)
        else:
            payload[field] = value
        path.write_text(json.dumps(payload), encoding="utf-8")
    before = _digest_tree(tmp_path / ".claude")
    monkeypatch.setattr(resources, "_load_process_records", _forbid_process_scan)

    with pytest.raises(resources.ResourceError):
        resources.finalize(
            tmp_path,
            claude_session_id=binding["claude_session_id"],
            resource_session_id=binding["resource_session_id"],
        )

    assert _digest_tree(tmp_path / ".claude") == before
    assert scratch.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("command", None, id="command-missing"),
        pytest.param("workflow_instance_id", None, id="instance-missing"),
        pytest.param("workflow_generation", None, id="generation-missing"),
        pytest.param("workflow_generation", True, id="generation-boolean"),
        pytest.param("workflow_generation", {}, id="generation-object"),
        pytest.param("workflow_generation", "1", id="generation-string"),
    ],
)
def test_provision_requires_type_strict_workflow_anchor_before_mutation(
    tmp_path: Path, field: str, value: object
) -> None:
    binding = _binding("required", "one")
    if value is None:
        binding.pop(field)
    else:
        binding[field] = value
    before = _digest_tree(tmp_path)

    with pytest.raises(resources.ResourceError):
        resources.provision(tmp_path, binding)

    assert _digest_tree(tmp_path) == before
    assert not (tmp_path / ".claude").exists()


@pytest.mark.parametrize(
    ("mutation", "field", "value"),
    [
        pytest.param("delete-anchor", "workflow_identity", None, id="anchor-absent"),
        pytest.param(
            "delete-anchor", "workflow_identity_sha256", None, id="digest-absent"
        ),
        pytest.param("identity", "command", "redev", id="command-tamper"),
        pytest.param(
            "identity", "workflow_instance_id", "stale", id="instance-tamper"
        ),
        pytest.param(
            "identity", "workflow_generation", True, id="generation-type-tamper"
        ),
        pytest.param(
            "replace", "workflow_identity_sha256", "0" * 64, id="digest-tamper"
        ),
    ],
)
def test_finalize_rejects_session_anchor_tamper_with_exact_tree_preservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    field: str,
    value: object,
) -> None:
    binding = _binding("anchor", "one")
    binding["workflow_generation"] = 7
    provisioned = resources.provision(tmp_path, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "evidence").write_bytes(b"anchor-evidence")
    _receipt(tmp_path, binding)
    session_path, _terminal_path, _pointer_path = _resource_record_paths(
        tmp_path, binding
    )
    session = json.loads(session_path.read_text())
    if mutation == "delete-anchor":
        session.pop(field)
    elif mutation == "identity":
        session["workflow_identity"][field] = value
    else:
        session[field] = value
    session_path.write_text(json.dumps(session), encoding="utf-8")
    before = _digest_tree(tmp_path / ".claude")
    monkeypatch.setattr(resources, "_load_process_records", _forbid_process_scan)

    with pytest.raises(resources.ResourceError):
        resources.finalize(
            tmp_path,
            claude_session_id=binding["claude_session_id"],
            resource_session_id=binding["resource_session_id"],
        )

    assert _digest_tree(tmp_path / ".claude") == before
    assert scratch.exists()


def test_finalize_rejects_fully_rebound_mutable_records_against_actor_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding = _binding("rebound", "one")
    binding["workflow_generation"] = 7
    provisioned = resources.provision(tmp_path, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "evidence").write_bytes(b"rebound-evidence")
    _receipt(tmp_path, binding)
    session_path, terminal_path, pointer_path = _resource_record_paths(
        tmp_path, binding
    )
    session = json.loads(session_path.read_text())
    stale_identity = {
        "command": "redev",
        "workflow_instance_id": "workflow-stale",
        "workflow_generation": 6,
    }
    session["workflow_identity"] = stale_identity
    session["workflow_identity_sha256"] = resources.sha256_json(stale_identity)
    session_path.write_text(json.dumps(session), encoding="utf-8")
    session_digest = hashlib.sha256(session_path.read_bytes()).hexdigest()
    terminal = json.loads(terminal_path.read_text())
    pointer = json.loads(pointer_path.read_text())
    for payload in (terminal, pointer):
        payload.update(stale_identity)
    terminal["session_manifest_sha256"] = session_digest
    terminal_path.write_text(json.dumps(terminal), encoding="utf-8")
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    before = _digest_tree(tmp_path / ".claude")
    monkeypatch.setattr(resources, "_load_process_records", _forbid_process_scan)

    with pytest.raises(resources.ResourceError):
        resources.finalize(
            tmp_path,
            claude_session_id=binding["claude_session_id"],
            resource_session_id=binding["resource_session_id"],
        )

    assert _digest_tree(tmp_path / ".claude") == before
    assert scratch.exists()


@pytest.mark.parametrize(
    "case",
    [
        "binding",
        "binding_digest",
        "binding_and_digest",
        "workflow_digest",
        "session_digest",
        "scratch_path",
        "managed_temp_path",
        "interface_digest",
    ],
)
def test_finalize_rejects_actor_anchor_integrity_tamper_before_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    binding = _binding("actor", "one")
    binding["workflow_generation"] = 7
    provisioned = resources.provision(tmp_path, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "evidence").write_bytes(b"actor-evidence")
    _receipt(tmp_path, binding)
    manifest_path = Path(provisioned["manifest_path"])
    manifest = json.loads(manifest_path.read_text())
    if case in {"binding", "binding_and_digest"}:
        manifest["binding"]["command"] = "redev"
    if case == "binding_digest":
        manifest["binding_sha256"] = "0" * 64
    elif case == "binding_and_digest":
        manifest["binding_sha256"] = resources.sha256_json(manifest["binding"])
    elif case == "workflow_digest":
        manifest["workflow_identity_sha256"] = "0" * 64
    elif case == "session_digest":
        manifest["session_manifest_sha256"] = "0" * 64
    elif case == "scratch_path":
        manifest["scratch_path"] = str(tmp_path / "other")
    elif case == "managed_temp_path":
        manifest["managed_temp_path"] = str(tmp_path / "other/tmp")
    elif case == "interface_digest":
        manifest["owner_record_interface_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    before = _digest_tree(tmp_path / ".claude")
    monkeypatch.setattr(resources, "_load_process_records", _forbid_process_scan)

    with pytest.raises(resources.ResourceError):
        resources.finalize(
            tmp_path,
            claude_session_id=binding["claude_session_id"],
            resource_session_id=binding["resource_session_id"],
        )

    assert _digest_tree(tmp_path / ".claude") == before
    assert scratch.exists()


def test_finalize_rejects_ambiguous_actor_manifest_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding = _binding("ambiguous", "one")
    provisioned = resources.provision(tmp_path, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "evidence").write_bytes(b"ambiguous-evidence")
    _receipt(tmp_path, binding)
    manifest_path = Path(provisioned["manifest_path"])
    duplicate = manifest_path.with_name("shadow.json")
    duplicate.write_bytes(manifest_path.read_bytes())
    before = _digest_tree(tmp_path / ".claude")
    monkeypatch.setattr(resources, "_load_process_records", _forbid_process_scan)

    with pytest.raises(resources.ResourceError):
        resources.finalize(
            tmp_path,
            claude_session_id=binding["claude_session_id"],
            resource_session_id=binding["resource_session_id"],
        )

    assert _digest_tree(tmp_path / ".claude") == before
    assert scratch.exists()


def test_finalize_rejects_absent_actor_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding = _binding("absent", "one")
    provisioned = resources.provision(tmp_path, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "evidence").write_bytes(b"absent-evidence")
    _receipt(tmp_path, binding)
    Path(provisioned["manifest_path"]).unlink()
    before = _digest_tree(tmp_path / ".claude")
    monkeypatch.setattr(resources, "_load_process_records", _forbid_process_scan)

    with pytest.raises(resources.ResourceError):
        resources.finalize(
            tmp_path,
            claude_session_id=binding["claude_session_id"],
            resource_session_id=binding["resource_session_id"],
        )

    assert _digest_tree(tmp_path / ".claude") == before
    assert scratch.exists()


def test_exact_current_multi_actor_anchor_finalizes_idempotently(
    tmp_path: Path,
) -> None:
    first_binding = _binding("multi", "one")
    second_binding = _binding("multi", "two", role="dev")
    first = resources.provision(tmp_path, first_binding)
    second = resources.provision(tmp_path, second_binding)
    assert first_binding["resource_session_id"] == second_binding["resource_session_id"]
    assert first["manifest_path"] != second["manifest_path"]
    resource_scratch = tmp_path / ".claude/scratch" / first_binding["resource_session_id"]
    Path(first["scratch_path"], "first").write_bytes(b"first")
    Path(second["scratch_path"], "second").write_bytes(b"second")
    _receipt(tmp_path, first_binding)

    initial = resources.finalize(
        tmp_path,
        claude_session_id=first_binding["claude_session_id"],
        resource_session_id=first_binding["resource_session_id"],
    )
    replay = resources.finalize(
        tmp_path,
        claude_session_id=first_binding["claude_session_id"],
        resource_session_id=first_binding["resource_session_id"],
    )

    assert initial["status"] == replay["status"] == "pass"
    assert initial["idempotent"] is False
    assert replay["idempotent"] is True
    assert len(initial["finalized"]["actor_binding_sha256"]) == 2
    assert replay["finalized"] == initial["finalized"]
    assert not resource_scratch.exists()


def test_complete_owner_record_and_process_registry_rebind_cannot_replace_trusted_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding = _binding("complete-rebind", "one")
    binding["workflow_generation"] = 7
    provisioned = resources.provision(tmp_path, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "evidence").write_bytes(b"complete-rebind")
    _receipt(tmp_path, binding)
    process_dir = (
        tmp_path
        / ".claude/session-resources"
        / binding["resource_session_id"]
        / "processes"
    )
    process_dir.mkdir()
    process_record = {
        "schema": resources.SCHEMA_VERSION,
        "resource_session_id": binding["resource_session_id"],
        "binding_sha256": resources.sha256_json(resources.normalize_binding(binding)),
        "role": binding["role"],
        "dispatch_id": binding["dispatch_id"],
        "pid": 99999991,
        "pgid": 99999991,
        "proc_start_time": "1",
        "argv_sha256": "1" * 64,
        "started_at": "2026-08-10T00:00:00Z",
    }
    process_path = process_dir / "99999991.json"
    process_path.write_text(json.dumps(process_record), encoding="utf-8")

    session_path, terminal_path, pointer_path = _resource_record_paths(
        tmp_path, binding
    )
    stale_identity = {
        "command": "redev",
        "workflow_instance_id": "workflow-stale",
        "workflow_generation": 8,
    }
    session = json.loads(session_path.read_text())
    session["workflow_identity"] = stale_identity
    session["workflow_identity_sha256"] = resources.sha256_json(stale_identity)
    session_path.write_text(json.dumps(session), encoding="utf-8")
    session_sha256 = hashlib.sha256(session_path.read_bytes()).hexdigest()
    for path in (terminal_path, pointer_path):
        value = json.loads(path.read_text())
        value.update(stale_identity)
        if path == terminal_path:
            value["session_manifest_sha256"] = session_sha256
        path.write_text(json.dumps(value), encoding="utf-8")
    manifest_path = Path(provisioned["manifest_path"])
    manifest = json.loads(manifest_path.read_text())
    manifest["binding"].update(stale_identity)
    manifest["binding_sha256"] = resources.sha256_json(manifest["binding"])
    manifest["workflow_identity_sha256"] = resources.sha256_json(stale_identity)
    manifest["session_manifest_sha256"] = session_sha256
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    process_record["binding_sha256"] = manifest["binding_sha256"]
    process_path.write_text(json.dumps(process_record), encoding="utf-8")
    before = _combined_snapshot(tmp_path, binding)
    monkeypatch.setattr(resources, "_load_process_records", _forbid_process_scan)

    with pytest.raises(resources.ResourceError, match="trusted|current pointer"):
        resources.finalize(
            tmp_path,
            claude_session_id=binding["claude_session_id"],
            resource_session_id=binding["resource_session_id"],
        )

    assert _combined_snapshot(tmp_path, binding) == before
    assert scratch.exists() and process_path.exists()


def test_external_trusted_registry_rewrite_with_unkeyed_digest_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding = _binding("forged-trust", "one")
    provisioned = resources.provision(tmp_path, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "evidence").write_bytes(b"forged-trust")
    _receipt(tmp_path, binding)
    trust_path = _trust_record_path(tmp_path, binding)
    forged = json.loads(trust_path.read_text())
    forged["workflow_identity"] = {
        "command": "redev",
        "workflow_instance_id": "workflow-forged",
        "workflow_generation": 9,
    }
    unsigned = {key: value for key, value in forged.items() if key != "hmac_sha256"}
    forged["hmac_sha256"] = resources.sha256_json(unsigned)
    trust_path.write_text(json.dumps(forged), encoding="utf-8")
    before = _combined_snapshot(tmp_path, binding)
    monkeypatch.setattr(resources, "_load_process_records", _forbid_process_scan)

    with pytest.raises(resources.ResourceError, match="authentication mismatch"):
        resources.finalize(
            tmp_path,
            claude_session_id=binding["claude_session_id"],
            resource_session_id=binding["resource_session_id"],
        )

    assert _combined_snapshot(tmp_path, binding) == before
    assert scratch.exists()


@pytest.mark.parametrize("record", ["pointer", "session", "terminal", "actor"])
def test_post_validation_identity_rewrite_is_rejected_before_destructive_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record: str,
) -> None:
    binding = _binding(f"race-{record}", "one")
    provisioned = resources.provision(tmp_path, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "evidence").write_bytes(b"race-preserve")
    _receipt(tmp_path, binding)
    session_path, terminal_path, pointer_path = _resource_record_paths(
        tmp_path, binding
    )
    target = {
        "pointer": pointer_path,
        "session": session_path,
        "terminal": terminal_path,
        "actor": Path(provisioned["manifest_path"]),
    }[record]
    original_loader = resources._load_process_records
    injected: dict[str, dict[str, dict[str, str]]] = {}

    def rewrite_after_validation(root: Path, resource_session_id: str) -> list:
        if not injected:
            value = json.loads(target.read_text())
            if record == "session":
                value["workflow_identity"]["command"] = "redev"
            elif record == "actor":
                value["binding"]["command"] = "redev"
            else:
                value["command"] = "redev"
            target.write_text(json.dumps(value), encoding="utf-8")
            injected["snapshot"] = _combined_snapshot(tmp_path, binding)
        return original_loader(root, resource_session_id)

    monkeypatch.setattr(resources, "_load_process_records", rewrite_after_validation)
    with pytest.raises(resources.ResourceError):
        resources.finalize(
            tmp_path,
            claude_session_id=binding["claude_session_id"],
            resource_session_id=binding["resource_session_id"],
        )

    assert _combined_snapshot(tmp_path, binding) == injected["snapshot"]
    assert scratch.exists()
    assert not (
        tmp_path
        / ".claude/session-resources"
        / binding["resource_session_id"]
        / "finalized.json"
    ).exists()


def test_post_validation_trusted_workflow_advance_is_rejected_without_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding = _binding("trusted-race", "one")
    provisioned = resources.provision(tmp_path, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "evidence").write_bytes(b"trusted-race")
    _receipt(tmp_path, binding)
    trust_path = _trust_record_path(tmp_path, binding)
    original_loader = resources._load_process_records
    injected: dict[str, dict[str, dict[str, str]]] = {}

    def advance_after_validation(root: Path, resource_session_id: str) -> list:
        if not injected:
            current = json.loads(trust_path.read_text())
            current["revision"] += 1
            current["workflow_identity"] = {
                "command": "redev",
                "workflow_instance_id": "workflow-next",
                "workflow_generation": 2,
            }
            signed = resources._sign_trusted_record(
                current, bytes.fromhex(os.environ[resources.TRUST_KEY_ENV])
            )
            trust_path.write_bytes(resources._canonical_bytes(signed) + b"\n")
            injected["snapshot"] = _combined_snapshot(tmp_path, binding)
        return original_loader(root, resource_session_id)

    monkeypatch.setattr(resources, "_load_process_records", advance_after_validation)
    with pytest.raises(resources.ResourceError, match="advanced during finalization"):
        resources.finalize(
            tmp_path,
            claude_session_id=binding["claude_session_id"],
            resource_session_id=binding["resource_session_id"],
        )

    assert _combined_snapshot(tmp_path, binding) == injected["snapshot"]
    assert scratch.exists()


@pytest.mark.parametrize("collision", ["corrupt", "forged", "conflicting"])
def test_finalized_record_collision_rejects_before_process_inspection_or_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    collision: str,
) -> None:
    binding = _binding(f"finalized-{collision}", "one")
    provisioned = resources.provision(tmp_path, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "evidence").write_bytes(b"finalized-collision")
    _receipt(tmp_path, binding)
    finalized_path = (
        tmp_path
        / ".claude/session-resources"
        / binding["resource_session_id"]
        / "finalized.json"
    )
    valid, key = _finalized_fixture(tmp_path, binding)
    if collision == "corrupt":
        finalized_path.write_text("{", encoding="utf-8")
    else:
        valid["resource_session_id"] = "resource-conflict"
        if collision == "conflicting":
            valid = resources._sign_trusted_record(valid, key)
        finalized_path.write_bytes(resources._canonical_bytes(valid) + b"\n")
    before = _combined_snapshot(tmp_path, binding)
    monkeypatch.setattr(resources, "_load_process_records", _forbid_process_scan)

    with pytest.raises(resources.ResourceError):
        resources.finalize(
            tmp_path,
            claude_session_id=binding["claude_session_id"],
            resource_session_id=binding["resource_session_id"],
        )

    assert _combined_snapshot(tmp_path, binding) == before
    assert scratch.exists()


def test_authorized_trust_with_missing_finalized_record_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding = _binding("missing-finalized", "one")
    provisioned = resources.provision(tmp_path, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "evidence").write_bytes(b"missing-finalized")
    _receipt(tmp_path, binding)
    trust_path = _trust_record_path(tmp_path, binding)
    trusted = json.loads(trust_path.read_text())
    trusted.update(
        {
            "state": "authorized",
            "finalization_authorization_sha256": "1" * 64,
            "revision": trusted["revision"] + 1,
        }
    )
    trusted = resources._sign_trusted_record(
        trusted, bytes.fromhex(os.environ[resources.TRUST_KEY_ENV])
    )
    trust_path.write_bytes(resources._canonical_bytes(trusted) + b"\n")
    before = _combined_snapshot(tmp_path, binding)
    monkeypatch.setattr(resources, "_load_process_records", _forbid_process_scan)

    with pytest.raises(resources.ResourceError, match="no finalized record"):
        resources.finalize(
            tmp_path,
            claude_session_id=binding["claude_session_id"],
            resource_session_id=binding["resource_session_id"],
        )

    assert _combined_snapshot(tmp_path, binding) == before
    assert scratch.exists()


@pytest.mark.parametrize("failure", ["publish", "validate"])
def test_finalized_record_publish_or_validation_failure_precedes_cleanup_and_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    binding = _binding(f"finalized-failure-{failure}", "one")
    provisioned = resources.provision(tmp_path, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "evidence").write_bytes(b"finalized-failure")
    _receipt(tmp_path, binding)
    before = _combined_snapshot(tmp_path, binding)
    if failure == "publish":
        original_create = resources._create_or_verify

        def fail_publish(path: Path, payload: object, root: Path) -> None:
            if path.name == "finalized.json":
                raise OSError("injected finalized publish failure")
            original_create(path, payload, root)

        monkeypatch.setattr(resources, "_create_or_verify", fail_publish)
    else:
        original_validate = resources._load_valid_finalized_record

        def fail_validation(path: Path, **validation: object) -> tuple[dict, bytes]:
            if path.name == "finalized.json":
                raise resources.ResourceError("injected finalized validation failure")
            return original_validate(path, **validation)

        monkeypatch.setattr(
            resources, "_load_valid_finalized_record", fail_validation
        )

    with pytest.raises((OSError, resources.ResourceError)):
        resources.finalize(
            tmp_path,
            claude_session_id=binding["claude_session_id"],
            resource_session_id=binding["resource_session_id"],
        )

    assert _combined_snapshot(tmp_path, binding) == before
    assert scratch.exists()


@pytest.mark.parametrize("stage", ["finalized_publish", "trust_transition"])
def test_identity_rewrite_during_authorization_rolls_back_before_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    binding = _binding(f"authorization-race-{stage}", "one")
    provisioned = resources.provision(tmp_path, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "evidence").write_bytes(b"authorization-race")
    _receipt(tmp_path, binding)
    _session_path, terminal_path, pointer_path = _resource_record_paths(
        tmp_path, binding
    )
    trust_path = _trust_record_path(tmp_path, binding)
    trusted_before = trust_path.read_bytes()
    injected: dict[str, dict[str, str]] = {}

    def mutate(path: Path) -> None:
        value = json.loads(path.read_text())
        value["command"] = "redev"
        path.write_text(json.dumps(value), encoding="utf-8")
        injected["project"] = _digest_tree(tmp_path / ".claude")

    if stage == "finalized_publish":
        original_create = resources._create_or_verify

        def publish_then_rewrite(path: Path, payload: object, root: Path) -> None:
            original_create(path, payload, root)
            if path.name == "finalized.json":
                mutate(pointer_path)

        monkeypatch.setattr(resources, "_create_or_verify", publish_then_rewrite)
    else:
        original_trust_write = resources._write_trusted_record

        def authorize_then_rewrite(
            path: Path, payload: object, **configuration: object
        ) -> dict:
            result = original_trust_write(path, payload, **configuration)
            if result["state"] == "authorized":
                mutate(terminal_path)
            return result

        monkeypatch.setattr(
            resources, "_write_trusted_record", authorize_then_rewrite
        )

    with pytest.raises(resources.ResourceError):
        resources.finalize(
            tmp_path,
            claude_session_id=binding["claude_session_id"],
            resource_session_id=binding["resource_session_id"],
        )

    expected_project = {
        path: digest
        for path, digest in injected["project"].items()
        if not path.endswith("/finalized.json")
    }
    assert _digest_tree(tmp_path / ".claude") == expected_project
    assert trust_path.read_bytes() == trusted_before
    assert scratch.exists()
    assert not (
        tmp_path
        / ".claude/session-resources"
        / binding["resource_session_id"]
        / "finalized.json"
    ).exists()


@pytest.mark.parametrize("tamper", ["missing", "corrupt", "forged"])
def test_finalized_record_tamper_at_cleanup_boundary_rolls_back_without_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    binding = _binding(f"cleanup-finalized-{tamper}", "one")
    provisioned = resources.provision(tmp_path, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "evidence").write_bytes(b"cleanup-finalized")
    _receipt(tmp_path, binding)
    before = _combined_snapshot(tmp_path, binding)
    finalized_path = (
        tmp_path
        / ".claude/session-resources"
        / binding["resource_session_id"]
        / "finalized.json"
    )
    original_wait = resources._wait_for_exit
    injected = False

    def tamper_before_cleanup(
        records: object, deadline: float, root: Path
    ) -> list[dict]:
        nonlocal injected
        result = original_wait(records, deadline, root)
        if not injected:
            injected = True
            if tamper == "missing":
                finalized_path.unlink()
            elif tamper == "corrupt":
                finalized_path.write_text("{", encoding="utf-8")
            else:
                forged = json.loads(finalized_path.read_text())
                forged["hmac_sha256"] = "0" * 64
                finalized_path.write_text(json.dumps(forged), encoding="utf-8")
        return result

    monkeypatch.setattr(resources, "_wait_for_exit", tamper_before_cleanup)
    with pytest.raises(resources.ResourceError):
        resources.finalize(
            tmp_path,
            claude_session_id=binding["claude_session_id"],
            resource_session_id=binding["resource_session_id"],
        )

    assert _combined_snapshot(tmp_path, binding) == before
    assert scratch.exists()


def test_absent_external_trust_anchor_rejects_with_resource_tree_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binding = _binding("absent-trust", "one")
    provisioned = resources.provision(tmp_path, binding)
    scratch = Path(provisioned["scratch_path"])
    (scratch / "evidence").write_bytes(b"absent-trust")
    _receipt(tmp_path, binding)
    _trust_record_path(tmp_path, binding).unlink()
    before = _digest_tree(tmp_path / ".claude")
    monkeypatch.setattr(resources, "_load_process_records", _forbid_process_scan)

    with pytest.raises(resources.ResourceError, match="absent or unsafe"):
        resources.finalize(
            tmp_path,
            claude_session_id=binding["claude_session_id"],
            resource_session_id=binding["resource_session_id"],
        )

    assert _digest_tree(tmp_path / ".claude") == before
    assert scratch.exists()


def test_owned_process_never_receives_external_trust_capability(tmp_path: Path) -> None:
    binding = _binding("trust-capability", "one")
    provisioned = resources.provision(tmp_path, binding)
    evidence = Path(provisioned["scratch_path"]) / "trust-environment.json"
    code = (
        "import json,os,pathlib;"
        f"pathlib.Path({str(evidence)!r}).write_text(json.dumps(["
        f"os.getenv({resources.TRUST_KEY_ENV!r}),"
        f"os.getenv({resources.TRUST_ROOT_ENV!r})]))"
    )

    result = resources.exec_owned(tmp_path, binding, [sys.executable, "-c", code])

    assert result["status"] == "pass"
    assert json.loads(evidence.read_text()) == [None, None]


@pytest.mark.parametrize("ignore_term", [False, True])
def test_broker_term_then_bounded_kill_and_sibling_preservation(
    tmp_path: Path, ignore_term: bool
) -> None:
    actor_a = _binding("A", "one")
    actor_b = _binding("B", "one")
    a = resources.provision(tmp_path, actor_a)
    b = resources.provision(tmp_path, actor_b)
    b_scratch = Path(b["scratch_path"])
    (b_scratch / "sibling-evidence").write_bytes(b"B")
    b_before = _digest_tree(b_scratch)
    ready = Path(a["scratch_path"]) / "ready"
    handler = "signal.SIG_IGN" if ignore_term else "lambda *_: sys.exit(0)"
    code = (
        "import pathlib,signal,sys,time;"
        f"signal.signal(signal.SIGTERM,{handler});"
        f"pathlib.Path({str(ready)!r}).write_text('ready');"
        "time.sleep(60)"
    )
    spawned = resources.spawn_owned(
        tmp_path, actor_a, [sys.executable, "-c", code]
    )
    _wait_for(ready)
    _receipt(tmp_path, actor_a)
    result = resources.finalize(
        tmp_path,
        claude_session_id=actor_a["claude_session_id"],
        resource_session_id=actor_a["resource_session_id"],
        term_timeout=0.15,
        kill_timeout=1.0,
    )
    assert result["status"] == "pass"
    signals = [item["signal"] for item in result["signalled"]]
    assert signals[0] == "TERM"
    assert ("KILL" in signals) is ignore_term
    assert not Path(a["scratch_path"]).exists()
    assert _digest_tree(b_scratch) == b_before
    assert not Path(f"/proc/{spawned['pid']}").exists()


def test_mismatched_process_identity_receives_no_signal(tmp_path: Path) -> None:
    actor = _binding("A", "one")
    provisioned = resources.provision(tmp_path, actor)
    ready = Path(provisioned["scratch_path"]) / "ready"
    code = (
        "import pathlib,signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        f"pathlib.Path({str(ready)!r}).write_text('ready');time.sleep(60)"
    )
    spawned = resources.spawn_owned(tmp_path, actor, [sys.executable, "-c", code])
    _wait_for(ready)
    record_path = Path(spawned["record_path"])
    record = json.loads(record_path.read_text())
    original = dict(record)
    record["proc_start_time"] = "mismatch"
    record_path.write_text(json.dumps(record))
    _receipt(tmp_path, actor)
    result = resources.finalize(
        tmp_path,
        claude_session_id=actor["claude_session_id"],
        resource_session_id=actor["resource_session_id"],
        term_timeout=0.05,
        kill_timeout=0.05,
    )
    assert result["status"] == "fail"
    assert result["signalled"] == []
    assert Path(f"/proc/{spawned['pid']}").exists()
    # Restore the trusted record and use the broker itself for fixture cleanup.
    record_path.write_text(json.dumps(original))
    assert resources.finalize(
        tmp_path,
        claude_session_id=actor["claude_session_id"],
        resource_session_id=actor["resource_session_id"],
        term_timeout=0.05,
        kill_timeout=1.0,
    )["status"] == "pass"


def test_unregistered_process_is_never_signalled(tmp_path: Path) -> None:
    actor = _binding("A", "one")
    resources.provision(tmp_path, actor)
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
    )
    try:
        _receipt(tmp_path, actor)
        result = resources.finalize(
            tmp_path,
            claude_session_id=actor["claude_session_id"],
            resource_session_id=actor["resource_session_id"],
        )
        assert result["status"] == "pass" and result["signalled"] == []
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=3)


def test_symlink_in_scratch_fails_closed_without_following(tmp_path: Path) -> None:
    actor = _binding("A", "one")
    provisioned = resources.provision(tmp_path, actor)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "evidence").write_text("preserve")
    (Path(provisioned["scratch_path"]) / "link").symlink_to(outside, target_is_directory=True)
    _receipt(tmp_path, actor)
    result = resources.finalize(
        tmp_path,
        claude_session_id=actor["claude_session_id"],
        resource_session_id=actor["resource_session_id"],
    )
    assert result["status"] == "fail"
    assert result["error_code"] == "scratch_symlink_detected"
    assert (outside / "evidence").read_text() == "preserve"
