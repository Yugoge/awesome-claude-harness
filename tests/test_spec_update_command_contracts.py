"""Executable contracts for the three-purpose ``/spec-update`` policy."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "spec-update-contract.py"
SPEC = importlib.util.spec_from_file_location("spec_update_contract", SCRIPT)
assert SPEC and SPEC.loader
contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contract)


def _json_digest(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_digest(root: Path) -> str:
    entries: list[tuple[str, str, str]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries.append((relative, "link", os.readlink(path)))
        elif path.is_file():
            entries.append((relative, "file", _sha(path)))
        else:
            entries.append((relative, "dir", ""))
    return _json_digest(entries)


def _project(tmp_path: Path, names: tuple[str, ...] = ("spec-x.md",)) -> Path:
    root = tmp_path / "project"
    specs = root / "docs" / "dev" / "specs"
    scripts = root / "scripts"
    hook_lib = root / "hooks" / "lib"
    specs.mkdir(parents=True)
    scripts.mkdir()
    hook_lib.mkdir(parents=True)
    for source in ("resolve-spec-artifacts.py", "spec-check.py"):
        shutil.copy2(ROOT / "scripts" / source, scripts / source)
    for source in ("__init__.py", "checkpoint_resources.py"):
        shutil.copy2(ROOT / "hooks" / "lib" / source, hook_lib / source)
    for name in names:
        (specs / name).write_text(f"# {name}\n", encoding="utf-8")
    return root


def _plan(root: Path, raw: str, **extra: object) -> dict:
    request = {"project_dir": str(root), "raw_arguments": raw, **extra}
    return contract.build_plan(request)


def _verified(mode: str, target: str) -> dict:
    return {
        "schema_version": 1,
        "record_type": "verified_spec_update.v1",
        "status": "pass",
        "mode": mode,
        "plan_digest": "a" * 64,
        "canonical_target": target,
        "post_target_sha256": "b" * 64,
        "codex_required": False,
    }


def _cli(
    operation: str,
    request: dict,
    *arguments: str,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), operation, *arguments],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        timeout=timeout,
    )


def _spec_check(root: Path, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(root / "scripts" / "spec-check.py"), *arguments],
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "CLAUDE_PROJECT_DIR": str(root),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )


def _populate_running_primary(path: Path, role: str, generation: int) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["is_running"] is True
    assert payload["generation"] == generation
    payload["checkpoints"] = [
        {
            "id": f"{role.upper()}-1",
            "action": "Verify the command contract",
            "state": "pending",
            "waived_reason": None,
        }
    ]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return contract._population_digest(payload)


def _write_split(
    root: Path,
    target: Path,
    receipt: dict,
    selected: list[dict],
    history: list[dict],
) -> None:
    artifact_id = target.stem.removeprefix("spec-")
    spec_dir = root / "docs" / "dev" / "specs" / artifact_id
    views = spec_dir / "views"
    views.mkdir(parents=True)
    (views / "dev.md").write_text("# Dev view\n", encoding="utf-8")
    binding = {
        "record_type": "checkpoint_binding.v1",
        "post_monolith_sha256": _sha(target),
        "receipt_digest": _json_digest(receipt),
        "final_round": max(item["split_round"] for item in receipt["rounds"]),
        "selected_primaries": selected,
        "historical_slots": history,
    }
    manifest = {
        "schema_version": 1,
        "spec_id": artifact_id,
        "monolith_path": target.relative_to(root).as_posix(),
        "sha256": _sha(target),
        "views": {"dev": "views/dev.md"},
        "checkpoint_binding": binding,
    }
    (views / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (spec_dir / ".split-complete").write_text("complete\n", encoding="utf-8")


def _finish_primary(
    root: Path,
    plan: dict,
    role: str = "dev",
) -> tuple[dict, dict]:
    artifact_id = plan["artifact_id"]
    primary = root / ".claude" / "specs" / artifact_id / f"cp-state-{role}.json"
    pre = next(
        (
            item
            for item in plan["checkpoint_inventory"]
            if item["role"] == role and item["instance_id"] is None
        ),
        None,
    )
    arguments = [
        "check-in",
        "--spec-id",
        artifact_id,
        "--agent",
        role,
        "--agent-id",
        "spec-provider-1",
    ]
    if pre is not None:
        arguments.append("--bump-generation")
    checked_in = _spec_check(root, *arguments)
    assert checked_in.returncode == 0, checked_in.stderr
    assert f"cp-state-path: {primary}" in checked_in.stdout
    generation = 1 if pre is None else pre["generation"] + 1
    population_digest = _populate_running_primary(primary, role, generation)
    status = _spec_check(root, "status", "--spec-id", artifact_id, "--agent", role)
    assert status.returncode == 0
    assert "running:      True" in status.stdout
    after_sha = _sha(primary)
    checked_out = _spec_check(
        root,
        "check-out",
        "--spec-id",
        artifact_id,
        "--agent",
        role,
        "--agent-id",
        "spec-provider-1",
    )
    assert checked_out.returncode == 0, checked_out.stderr
    terminal_sha = _sha(primary)
    branch = "create_primary" if pre is None else "refresh_primary"
    check_in_kind = "ordinary" if pre is None else "bump"
    round_receipt = {
        "role": role,
        "branch": branch,
        "pre_primary_state": "absent" if pre is None else "terminal",
        "pre_generation": None if pre is None else pre["generation"],
        "check_in_kind": check_in_kind,
        "expected_generation": generation,
        "argv_kind": check_in_kind,
        "emitted_cp_state_path": str(primary),
        "agent_id": "spec-provider-1",
        "before_sha256": None if pre is None else pre["sha256"],
        "after_sha256": after_sha,
        "population_digest": population_digest,
        "status_exit": status.returncode,
        "check_out_exit": checked_out.returncode,
        "terminal_sha256": terminal_sha,
        "split_round": 1,
    }
    round_binding = contract._round_binding(round_receipt)
    selected = {
        "role": role,
        "path": primary.relative_to(root).as_posix(),
        "generation": generation,
        "population_digest": population_digest,
        "terminal_sha256": terminal_sha,
        "branch": branch,
        "round": round_binding,
        "round_digest": _json_digest(round_binding),
    }
    return round_receipt, selected


def _final_update_fixture(root: Path, plan: dict) -> tuple[dict, str]:
    target = Path(plan["canonical_target"])
    target.write_text(target.read_text(encoding="utf-8") + "\nEnrichment.\n", encoding="utf-8")
    round_receipt, selected = _finish_primary(root, plan)
    receipt = {
        "schema_version": 1,
        "record_type": "split_lifecycle_receipt.v1",
        "post_monolith_sha256": _sha(target),
        "rounds": [round_receipt],
    }
    history = [
        {
            "path": item["path"],
            "generation": item["generation"],
            "sha256": item["sha256"],
        }
        for item in sorted(plan["checkpoint_inventory"], key=lambda item: item["path"])
        if item["instance_id"] is not None or item["role"] != "dev"
    ]
    _write_split(root, target, receipt, [selected], history)
    return {"plan": plan, "split_lifecycle_receipt": receipt}, f"Updated spec: {target}\n"


@pytest.mark.parametrize(
    "name",
    (
        "spec-20260808-035658.md",
        "spec-continuation-gitclean-20260809.md",
        "spec-dev-cross-sid-grant-leak.md",
    ),
)
def test_plan_accepts_every_resolver_valid_direct_spec_name(tmp_path: Path, name: str) -> None:
    root = _project(tmp_path, (name,))
    before = _tree_digest(root)
    plan = _plan(root, f"--update --spec docs/dev/specs/{name} new evidence")
    assert plan["mode"] == "update"
    assert plan["canonical_target"] == str(root / "docs" / "dev" / "specs" / name)
    assert plan["material_tokens"] == ["new", "evidence"]
    assert _tree_digest(root) == before


@pytest.mark.parametrize(
    ("raw", "code"),
    (
        ("--update --continue facts", "DUPLICATE_PURPOSE"),
        ("--temp --codex facts", "INCOMPATIBLE_OPTION"),
        ("--update --path note.md facts", "INCOMPATIBLE_OPTION"),
        ("--update --spec --codex facts", "MISSING_OPTION_VALUE"),
        ("--update --spec=x facts", "UNKNOWN_OPTION"),
        ("--update", "MATERIAL_REQUIRED"),
        ('--update --spec "unterminated', "INVALID_ARGUMENT_SYNTAX"),
    ),
)
def test_invalid_grammar_is_stable_and_read_only(tmp_path: Path, raw: str, code: str) -> None:
    root = _project(tmp_path)
    before = _tree_digest(root)
    with pytest.raises(contract.ContractError) as caught:
        _plan(root, raw, active_task={"state": "none"})
    assert caught.value.code == code
    assert _tree_digest(root) == before


def test_delimiter_makes_flag_looking_tokens_material(tmp_path: Path) -> None:
    root = _project(tmp_path)
    plan = _plan(
        root,
        "--update --spec docs/dev/specs/spec-x.md -- --codex --spec --update",
    )
    assert plan["codex_required"] is False
    assert plan["material_tokens"] == ["--codex", "--spec", "--update"]


@pytest.mark.parametrize(
    "target",
    ("README.md", "INDEX.md", "notes.md", "nested/spec-x.md", "../spec-x.md"),
)
def test_noncanonical_targets_reject_without_writes(tmp_path: Path, target: str) -> None:
    root = _project(tmp_path)
    nested = root / "docs" / "dev" / "specs" / "nested"
    nested.mkdir()
    (nested / "spec-x.md").write_text("nested\n", encoding="utf-8")
    before = _tree_digest(root)
    with pytest.raises(contract.ContractError) as caught:
        _plan(root, f"--update --spec {target} evidence")
    assert caught.value.code == "INVALID_SPEC_TARGET"
    assert _tree_digest(root) == before


def test_symlink_spec_rejects_without_writes(tmp_path: Path) -> None:
    root = _project(tmp_path)
    target = root / "docs" / "dev" / "specs" / "spec-x.md"
    link = target.with_name("spec-link.md")
    link.symlink_to(target.name)
    before = _tree_digest(root)
    with pytest.raises(contract.ContractError) as caught:
        _plan(root, "--update --spec docs/dev/specs/spec-link.md evidence")
    assert caught.value.code == "INVALID_SPEC_TARGET"
    assert _tree_digest(root) == before


def test_default_and_explicit_continue_are_identical(tmp_path: Path) -> None:
    root = _project(tmp_path)
    implicit = _plan(root, "--spec docs/dev/specs/spec-x.md focus")
    explicit = _plan(root, "--continue --spec docs/dev/specs/spec-x.md focus")
    assert implicit == explicit


def test_no_active_creation_is_deterministic_and_update_never_creates(tmp_path: Path) -> None:
    root = _project(tmp_path, ())
    request = {"active_task": {"state": "none"}}
    first = _plan(root, "--continue unfinished work", **request)
    second = _plan(root, "unfinished work", **request)
    assert first == second
    assert first["create_new"] is True
    assert Path(first["canonical_target"]).name.startswith("spec-continuation-")
    with pytest.raises(contract.ContractError) as caught:
        _plan(root, "--update evidence", **request)
    assert caught.value.code == "UPDATE_TARGET_REQUIRED"


def test_codex_is_a_review_modifier_not_material(tmp_path: Path) -> None:
    root = _project(tmp_path)
    plan = _plan(
        root,
        "--update --codex --spec docs/dev/specs/spec-x.md evidence",
    )
    assert plan["codex_required"] is True
    assert plan["material_tokens"] == ["evidence"]


def test_explicit_temp_targets_verify_under_project_and_actor_scratch(tmp_path: Path) -> None:
    root = _project(tmp_path)
    actor_scratch = tmp_path / "actor-scratch"
    actor_scratch.mkdir()
    project_notes = root / "notes"
    project_notes.mkdir()
    targets = (
        ("notes/project-handoff.md", project_notes / "project-handoff.md"),
        (str(actor_scratch / "actor-handoff.md"), actor_scratch / "actor-handoff.md"),
    )
    for argument, expected in targets:
        plan = _plan(
            root,
            f"--temp --path {argument} resume focus",
            actor_scratch_dir=str(actor_scratch),
        )
        assert plan["canonical_target"] == str(expected)
        expected.write_text("# Temp note\n", encoding="utf-8")
        verified = contract.verify_plan({"plan": plan})
        assert verified["canonical_target"] == str(expected)
        assert verified["canonical_response"]["lines"] == [f"Temp note: {expected}"]


def test_explicit_temp_nonterminal_symlink_parent_rejects_before_mutation(tmp_path: Path) -> None:
    root = _project(tmp_path)
    actor_scratch = tmp_path / "actor-scratch"
    actor_scratch.mkdir()
    real_subdir = root / "real" / "sub"
    real_subdir.mkdir(parents=True)
    (root / "link").symlink_to(root / "real", target_is_directory=True)
    before = _tree_digest(root)
    with pytest.raises(contract.ContractError) as caught:
        _plan(
            root,
            "--temp --path link/sub/handoff.md resume",
            actor_scratch_dir=str(actor_scratch),
        )
    assert caught.value.code == "INVALID_TEMP_TARGET"
    assert _tree_digest(root) == before


def test_allocator_temp_note_success_is_confined_and_read_only(tmp_path: Path) -> None:
    root = _project(tmp_path)
    actor_scratch = tmp_path / "actor-scratch"
    actor_scratch.mkdir()
    plan = _plan(
        root,
        "--temp resume focus",
        actor_scratch_dir=str(actor_scratch),
    )
    target = actor_scratch / "update-valid.md"
    target.write_text("# Temp note\n", encoding="utf-8")
    before = _tree_digest(tmp_path)
    verified = contract.verify_plan({"plan": plan, "allocated_target": str(target)})
    assert verified["canonical_response"]["lines"] == [f"Temp note: {target}"]
    assert _tree_digest(tmp_path) == before


@pytest.mark.parametrize("mode", ("explicit", "allocator"))
def test_temp_post_state_rejects_hardlink_alias_of_spec_without_response(
    tmp_path: Path,
    mode: str,
) -> None:
    root = _project(tmp_path)
    actor_scratch = tmp_path / "actor-scratch"
    actor_scratch.mkdir()
    spec = root / "docs" / "dev" / "specs" / "spec-x.md"
    if mode == "explicit":
        notes = root / "notes"
        notes.mkdir()
        target = notes / "hardlink.md"
        plan = _plan(
            root,
            "--temp --path notes/hardlink.md resume",
            actor_scratch_dir=str(actor_scratch),
        )
        request = {"plan": plan}
    else:
        target = actor_scratch / "update-alias.md"
        plan = _plan(root, "--temp resume", actor_scratch_dir=str(actor_scratch))
        request = {"plan": plan, "allocated_target": str(target)}
    os.link(spec, target)
    assert os.path.samefile(spec, target)
    before = _tree_digest(tmp_path)
    result = _cli("verify", request, "--emit-response")
    assert result.returncode == 2
    assert result.stdout == ""
    assert "TEMP_SPEC_ALIAS" in result.stderr
    assert "Traceback" not in result.stderr
    assert _tree_digest(tmp_path) == before


@pytest.mark.parametrize("drift", ("create", "change", "delete", "type", "symlink"))
def test_temp_verify_rejects_every_planned_spec_inventory_drift(
    tmp_path: Path,
    drift: str,
) -> None:
    root = _project(tmp_path)
    actor_scratch = tmp_path / "actor-scratch"
    actor_scratch.mkdir()
    notes = root / "notes"
    notes.mkdir()
    plan = _plan(
        root,
        "--temp --path notes/note.md resume",
        actor_scratch_dir=str(actor_scratch),
    )
    (notes / "note.md").write_text("# Temp note\n", encoding="utf-8")
    spec = root / "docs" / "dev" / "specs" / "spec-x.md"
    if drift == "create":
        spec.with_name("spec-new.md").write_text("# New spec\n", encoding="utf-8")
    elif drift == "change":
        spec.write_text("# Changed spec\n", encoding="utf-8")
    elif drift == "delete":
        spec.unlink()
    elif drift == "type":
        spec.unlink()
        spec.mkdir()
    else:
        alias_target = root / "not-a-spec.md"
        alias_target.write_text("# Alias target\n", encoding="utf-8")
        spec.unlink()
        spec.symlink_to(alias_target)
    before = _tree_digest(root)
    result = _cli("verify", {"plan": plan}, "--emit-response")
    assert result.returncode == 2
    assert result.stdout == ""
    assert "TEMP_SPEC_INVENTORY_CHANGED" in result.stderr
    assert "Traceback" not in result.stderr
    assert _tree_digest(root) == before


SYMLINK_INVENTORY_CASES = (
    "retarget_a_to_b",
    "target_bytes_changed",
    "broken_to_valid",
    "valid_to_broken",
    "relative_to_absolute_equivalent",
    "absolute_to_relative_equivalent",
    "relative_to_absolute_different",
    "absolute_to_relative_different",
    "control_no_change",
)


@pytest.mark.parametrize("mode", ("explicit", "allocator"))
@pytest.mark.parametrize("case", SYMLINK_INVENTORY_CASES)
def test_temp_spec_symlink_inventory_exact_matrix(
    tmp_path: Path,
    mode: str,
    case: str,
) -> None:
    root = _project(tmp_path, names=())
    specs = root / "docs" / "dev" / "specs"
    actor_scratch = tmp_path / "actor-scratch"
    actor_scratch.mkdir()
    target_a = root / "target-a.md"
    target_b = root / "target-b.md"
    missing = root / "missing.md"
    target_a.write_text("# Target A\n", encoding="utf-8")
    target_b.write_text("# Target B\n", encoding="utf-8")
    relative_a = os.path.relpath(target_a, specs)
    relative_b = os.path.relpath(target_b, specs)
    initial_targets = {
        "retarget_a_to_b": str(target_a),
        "target_bytes_changed": str(target_a),
        "broken_to_valid": str(missing),
        "valid_to_broken": str(target_a),
        "relative_to_absolute_equivalent": relative_a,
        "absolute_to_relative_equivalent": str(target_a),
        "relative_to_absolute_different": relative_a,
        "absolute_to_relative_different": str(target_a),
        "control_no_change": str(target_a),
    }
    link = specs / "spec-link.md"
    link.symlink_to(initial_targets[case])

    if mode == "explicit":
        notes = root / "notes"
        notes.mkdir()
        note = notes / "note.md"
        plan = _plan(
            root,
            "--temp --path notes/note.md resume",
            actor_scratch_dir=str(actor_scratch),
        )
        request = {"plan": plan}
    else:
        note = actor_scratch / "update-note.md"
        plan = _plan(root, "--temp resume", actor_scratch_dir=str(actor_scratch))
        request = {"plan": plan, "allocated_target": str(note)}
    note.write_text("# Temp note\n", encoding="utf-8")

    replacement_targets = {
        "retarget_a_to_b": str(target_b),
        "broken_to_valid": str(target_a),
        "valid_to_broken": str(missing),
        "relative_to_absolute_equivalent": str(target_a),
        "absolute_to_relative_equivalent": relative_a,
        "relative_to_absolute_different": str(target_b),
        "absolute_to_relative_different": relative_b,
    }
    if case == "target_bytes_changed":
        target_a.write_text("# Target A changed\n", encoding="utf-8")
    elif case in replacement_targets:
        link.unlink()
        link.symlink_to(replacement_targets[case])

    current_inventory = contract._spec_inventory(specs)
    if case == "control_no_change":
        assert current_inventory == plan["spec_inventory"]
    else:
        assert current_inventory != plan["spec_inventory"]
    before = _tree_digest(tmp_path)
    result = _cli("verify", request, "--emit-response")
    if case == "control_no_change":
        assert result.returncode == 0
        assert result.stdout == f"Temp note: {note}\n"
        assert result.stderr == ""
    else:
        assert result.returncode == 2
        assert result.stdout == ""
        assert "TEMP_SPEC_INVENTORY_CHANGED" in result.stderr
        assert "Traceback" not in result.stderr
    assert _tree_digest(tmp_path) == before


@pytest.mark.parametrize("mode", ("explicit", "allocator"))
def test_unchanged_broken_spec_symlink_inventory_is_valid(
    tmp_path: Path,
    mode: str,
) -> None:
    root = _project(tmp_path, names=())
    specs = root / "docs" / "dev" / "specs"
    actor_scratch = tmp_path / "actor-scratch"
    actor_scratch.mkdir()
    (specs / "spec-broken.md").symlink_to(root / "missing.md")
    if mode == "explicit":
        notes = root / "notes"
        notes.mkdir()
        note = notes / "note.md"
        plan = _plan(
            root,
            "--temp --path notes/note.md resume",
            actor_scratch_dir=str(actor_scratch),
        )
        request = {"plan": plan}
    else:
        note = actor_scratch / "update-note.md"
        plan = _plan(root, "--temp resume", actor_scratch_dir=str(actor_scratch))
        request = {"plan": plan, "allocated_target": str(note)}
    note.write_text("# Temp note\n", encoding="utf-8")
    before = _tree_digest(tmp_path)
    result = _cli("verify", request, "--emit-response")
    assert result.returncode == 0
    assert result.stdout == f"Temp note: {note}\n"
    assert result.stderr == ""
    assert _tree_digest(tmp_path) == before


def test_spec_inventory_keeps_regular_file_shape_and_rejects_symlink_directory(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    specs = root / "docs" / "dev" / "specs"
    regular = specs / "spec-x.md"
    assert contract._spec_inventory(specs) == [
        {"path": "spec-x.md", "type": "file", "sha256": _sha(regular)}
    ]
    directory = root / "referent-directory"
    directory.mkdir()
    link = specs / "spec-directory.md"
    link.symlink_to(directory, target_is_directory=True)
    before = _tree_digest(root)
    with pytest.raises(contract.ContractError) as caught:
        contract._spec_inventory(specs)
    assert caught.value.code == "INVALID_SPEC_INVENTORY"
    assert _tree_digest(root) == before


@pytest.mark.parametrize("failure", ("type", "readlink", "open", "read", "race"))
def test_temp_spec_symlink_inventory_errors_and_races_fail_closed_before_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    root = _project(tmp_path, names=())
    specs = root / "docs" / "dev" / "specs"
    actor_scratch = tmp_path / "actor-scratch"
    actor_scratch.mkdir()
    referent = root / "referent.md"
    referent.write_text("# Referent\n", encoding="utf-8")
    link = specs / "spec-link.md"
    link.symlink_to(referent)
    notes = root / "notes"
    notes.mkdir()
    note = notes / "note.md"
    plan = _plan(
        root,
        "--temp --path notes/note.md resume",
        actor_scratch_dir=str(actor_scratch),
    )
    note.write_text("# Temp note\n", encoding="utf-8")
    if failure == "type":
        referent.unlink()
        referent.mkdir()
    before = _tree_digest(tmp_path)
    real_readlink = os.readlink
    real_open = os.open
    real_read = os.read
    real_fstat = os.fstat

    with monkeypatch.context() as patched:
        if failure == "type":
            pass
        elif failure == "readlink":
            def denied_readlink(path: object) -> object:
                if os.fsdecode(path) == str(link):
                    raise PermissionError("synthetic readlink denial")
                return real_readlink(path)

            patched.setattr(contract.os, "readlink", denied_readlink)
        elif failure == "open":
            def denied_open(path: object, flags: int, *args: object) -> int:
                if os.fsdecode(path) == str(link):
                    raise PermissionError("synthetic referent open denial")
                return real_open(path, flags, *args)

            patched.setattr(contract.os, "open", denied_open)
        elif failure == "read":
            def denied_read(fd: int, size: int) -> bytes:
                raise OSError("synthetic referent read denial")

            patched.setattr(contract.os, "read", denied_read)
        else:
            calls = 0

            def racing_fstat(fd: int) -> object:
                nonlocal calls
                calls += 1
                result = real_fstat(fd)
                if calls == 2:
                    values = {
                        name: getattr(result, name)
                        for name in dir(result)
                        if name.startswith("st_")
                    }
                    values["st_mtime_ns"] = result.st_mtime_ns + 1
                    return type("RacingStat", (), values)()
                return result

            patched.setattr(contract.os, "fstat", racing_fstat)
        patched.setattr(
            contract,
            "_sha256_file",
            lambda path: pytest.fail("target hashing ran after inventory failure"),
        )
        patched.setattr(
            contract,
            "canonical_response",
            lambda verified: pytest.fail("response rendering ran after inventory failure"),
        )
        with pytest.raises(contract.ContractError) as caught:
            contract.verify_plan({"plan": plan})
    assert caught.value.code == "TEMP_SPEC_INVENTORY_CHANGED"
    assert _tree_digest(tmp_path) == before


def test_temp_symlink_inventory_drift_rejects_before_target_hash_or_renderer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _project(tmp_path, names=())
    specs = root / "docs" / "dev" / "specs"
    actor_scratch = tmp_path / "actor-scratch"
    actor_scratch.mkdir()
    referent = root / "referent.md"
    referent.write_text("# Before\n", encoding="utf-8")
    (specs / "spec-link.md").symlink_to(referent)
    notes = root / "notes"
    notes.mkdir()
    note = notes / "note.md"
    plan = _plan(
        root,
        "--temp --path notes/note.md resume",
        actor_scratch_dir=str(actor_scratch),
    )
    note.write_text("# Temp note\n", encoding="utf-8")
    referent.write_text("# After\n", encoding="utf-8")
    before = _tree_digest(tmp_path)
    monkeypatch.setattr(
        contract,
        "_sha256_file",
        lambda path: pytest.fail("target hashing ran after inventory drift"),
    )
    monkeypatch.setattr(
        contract,
        "canonical_response",
        lambda verified: pytest.fail("response rendering ran after inventory drift"),
    )
    with pytest.raises(contract.ContractError) as caught:
        contract.verify_plan({"plan": plan})
    assert caught.value.code == "TEMP_SPEC_INVENTORY_CHANGED"
    assert _tree_digest(tmp_path) == before


def _temp_symlink_request(
    tmp_path: Path,
    mode: str,
) -> tuple[Path, Path, Path, Path, dict]:
    root = _project(tmp_path, names=())
    specs = root / "docs" / "dev" / "specs"
    actor_scratch = tmp_path / "actor-scratch"
    actor_scratch.mkdir()
    referent = root / "referent.md"
    referent.write_text("# Referent\n", encoding="utf-8")
    link = specs / "spec-link.md"
    link.symlink_to(referent)
    if mode == "explicit":
        notes = root / "notes"
        notes.mkdir()
        note = notes / "note.md"
        plan = _plan(
            root,
            "--temp --path notes/note.md resume",
            actor_scratch_dir=str(actor_scratch),
        )
        request = {"plan": plan}
    else:
        note = actor_scratch / "update-note.md"
        plan = _plan(root, "--temp resume", actor_scratch_dir=str(actor_scratch))
        request = {"plan": plan, "allocated_target": str(note)}
    note.write_text("# Temp note\n", encoding="utf-8")
    return root, referent, link, note, request


@pytest.mark.parametrize("mode", ("explicit", "allocator"))
def test_temp_fifo_referent_drift_rejects_promptly_without_writer(
    tmp_path: Path,
    mode: str,
) -> None:
    root, referent, _link, _note, request = _temp_symlink_request(tmp_path, mode)
    referent.unlink()
    os.mkfifo(referent)
    before = _tree_digest(tmp_path)
    try:
        result = _cli("verify", request, "--emit-response", timeout=1.0)
    except subprocess.TimeoutExpired:
        pytest.fail("no-writer FIFO referent blocked verification")
    assert result.returncode == 2
    assert result.stdout == ""
    assert "TEMP_SPEC_INVENTORY_CHANGED" in result.stderr
    assert "Traceback" not in result.stderr
    assert _tree_digest(tmp_path) == before
    assert stat.S_ISFIFO(referent.lstat().st_mode)
    assert root.is_dir()


@pytest.mark.parametrize("mode", ("explicit", "allocator"))
def test_temp_directory_referent_drift_rejects_promptly(
    tmp_path: Path,
    mode: str,
) -> None:
    _root, referent, _link, _note, request = _temp_symlink_request(tmp_path, mode)
    referent.unlink()
    referent.mkdir()
    before = _tree_digest(tmp_path)
    try:
        result = _cli("verify", request, "--emit-response", timeout=1.0)
    except subprocess.TimeoutExpired:
        pytest.fail("directory referent blocked verification")
    assert result.returncode == 2
    assert result.stdout == ""
    assert "TEMP_SPEC_INVENTORY_CHANGED" in result.stderr
    assert "Traceback" not in result.stderr
    assert _tree_digest(tmp_path) == before


@pytest.mark.parametrize("mode", ("explicit", "allocator"))
@pytest.mark.parametrize(
    ("referent_type", "mode_bits"),
    (("socket", stat.S_IFSOCK), ("device", stat.S_IFCHR)),
)
def test_temp_injected_nonregular_referent_type_rejects_before_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    referent_type: str,
    mode_bits: int,
) -> None:
    _root, referent, link, note, request = _temp_symlink_request(tmp_path, mode)
    real_stat = os.stat

    def nonregular_stat(path: object, *args: object, **kwargs: object) -> object:
        result = real_stat(path, *args, **kwargs)
        if os.fsdecode(path) != str(link) or kwargs.get("follow_symlinks") is not True:
            return result
        values = {
            name: getattr(result, name)
            for name in dir(result)
            if name.startswith("st_")
        }
        values["st_mode"] = mode_bits | 0o600
        return type(f"Synthetic{referent_type.title()}Stat", (), values)()

    before = _tree_digest(tmp_path)
    with monkeypatch.context() as patched:
        patched.setattr(contract.os, "stat", nonregular_stat)
        patched.setattr(
            contract.os,
            "open",
            lambda *args, **kwargs: pytest.fail(f"{referent_type} referent reached open"),
        )
        patched.setattr(
            contract,
            "_sha256_file",
            lambda path: pytest.fail("target hashing ran after nonregular referent"),
        )
        patched.setattr(
            contract,
            "canonical_response",
            lambda verified: pytest.fail("response rendering ran after nonregular referent"),
        )
        with pytest.raises(contract.ContractError) as caught:
            contract.verify_plan(request)
    assert caught.value.code == "TEMP_SPEC_INVENTORY_CHANGED"
    assert _tree_digest(tmp_path) == before
    assert link.is_symlink()
    assert referent.is_file()
    assert note.read_text(encoding="utf-8") == "# Temp note\n"


@pytest.mark.parametrize("mode", ("explicit", "allocator"))
def test_temp_referent_type_race_uses_nonblocking_open_and_rejects_before_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    _root, referent, link, note, request = _temp_symlink_request(tmp_path, mode)
    real_stat = os.stat
    real_open = os.open
    raced = False
    observed_open_flags: list[int] = []

    def racing_stat(path: object, *args: object, **kwargs: object) -> object:
        nonlocal raced
        result = real_stat(path, *args, **kwargs)
        if not raced and os.fsdecode(path) == str(link) and kwargs.get("follow_symlinks") is True:
            referent.unlink()
            os.mkfifo(referent)
            raced = True
        return result

    def guarded_open(path: object, flags: int, *args: object) -> int:
        if os.fsdecode(path) == str(link):
            observed_open_flags.append(flags)
            assert flags & os.O_NONBLOCK
        return real_open(path, flags, *args)

    with monkeypatch.context() as patched:
        patched.setattr(contract.os, "stat", racing_stat)
        patched.setattr(contract.os, "open", guarded_open)
        patched.setattr(
            contract,
            "_sha256_file",
            lambda path: pytest.fail("target hashing ran after referent type race"),
        )
        patched.setattr(
            contract,
            "canonical_response",
            lambda verified: pytest.fail("response rendering ran after referent type race"),
        )
        with pytest.raises(contract.ContractError) as caught:
            contract.verify_plan(request)
    assert caught.value.code == "TEMP_SPEC_INVENTORY_CHANGED"
    assert raced
    assert observed_open_flags
    assert stat.S_ISFIFO(referent.lstat().st_mode)
    assert link.is_symlink()
    assert note.read_text(encoding="utf-8") == "# Temp note\n"


def test_numeric_checkpoint_filename_aliases_reject_before_mutation(tmp_path: Path) -> None:
    root = _project(tmp_path)
    artifact_id = "x"
    cp_dir = root / ".claude" / "specs" / artifact_id
    cp_dir.mkdir(parents=True)
    payload = {
        "spec_id": artifact_id,
        "agent_type": "dev",
        "instance_id": None,
        "generation": 1,
        "agent_id": None,
        "is_running": False,
        "checkpoints": [{"id": "DEV-1", "action": "Verify aliases", "state": "pending"}],
    }
    (cp_dir / "cp-state-dev.json").write_text(json.dumps(payload), encoding="utf-8")
    numbered = {**payload, "instance_id": 2}
    (cp_dir / "cp-state-dev-2.json").write_text(json.dumps(numbered), encoding="utf-8")
    (cp_dir / "cp-state-dev-02.json").write_text(json.dumps(numbered), encoding="utf-8")
    before = _tree_digest(root)
    with pytest.raises(contract.ContractError) as caught:
        _plan(root, "--update --spec docs/dev/specs/spec-x.md evidence")
    assert caught.value.code == "DUPLICATE_CHECKPOINT_INSTANCE"
    assert _tree_digest(root) == before


def test_exact_tail_safe_dev_token_matrix() -> None:
    canonical_updates = (
        "Updated spec: /tmp/project/docs/dev/specs/spec-x.md",
        "Updated spec: /dev/shm/project/docs/dev/specs/spec-x.md",
    )
    path_non_tokens = (
        "docs/dev/specs/spec-x.md",
        "/dev/shm/project/docs/dev/specs/spec-x.md",
    )
    empty_short = ("", "/", "/d", "/de")
    for text in (*canonical_updates, *path_non_tokens, *empty_short):
        assert not any(contract.dev_token_at(text, i) for i in range(len(text)))


@pytest.mark.parametrize(
    "target",
    (
        "/tmp/project/docs/dev/specs/spec-x.md",
        "/dev/shm/project/docs/dev/specs/spec-x.md",
    ),
)
def test_two_canonical_update_responses_exit_zero(target: str) -> None:
    verified = _verified("update", target)
    candidate = contract.canonical_response(verified)
    result = _cli(
        "render-response",
        {"verified_plan": verified, "candidate_response": candidate},
    )
    assert result.returncode == 0
    assert result.stdout == f"Updated spec: {target}\n"
    assert result.stderr == ""
    assert candidate["handoff_allowed"] is False
    assert candidate["next_command"] is None


def _tampered_candidate(kind: str, quote: str = '"') -> tuple[dict, dict]:
    verified = _verified("update", "/tmp/project/docs/dev/specs/spec-x.md")
    candidate = copy.deepcopy(contract.canonical_response(verified))
    suffixes = {
        "backtick": " Run `/dev --spec x`",
        "parenthesis": " Run (/dev --spec x)",
        "quote": f" Run {quote}/dev --spec x{quote}",
        "next_equals": " Next=/dev --spec x",
        "embedded_break": "\r\n/dev --spec x",
    }
    if kind == "extra_line":
        candidate["lines"].append("Unexpected response prose")
    else:
        candidate["lines"][0] += suffixes[kind]
    candidate["rendered"] = "\n".join(candidate["lines"]) + "\n"
    return verified, candidate


@pytest.mark.parametrize(
    "kind",
    ("backtick", "parenthesis", "quote", "next_equals", "embedded_break", "extra_line"),
)
def test_six_update_tamper_classes_exit_two_normally(kind: str) -> None:
    quote_variants = ("'", '"') if kind == "quote" else ('"',)
    for quote in quote_variants:
        verified, candidate = _tampered_candidate(kind, quote)
        result = _cli(
            "render-response",
            {"verified_plan": verified, "candidate_response": candidate},
        )
        assert result.returncode == 2
        assert result.stdout == ""
        assert "INVALID_UPDATE_RESPONSE" in result.stderr
        assert "Traceback" not in result.stderr


def test_missing_primary_provider_failure_is_fail_closed(tmp_path: Path) -> None:
    root = _project(tmp_path, ("spec-continuation-gitclean-20260809.md",))
    plan = _plan(
        root,
        "--update --spec docs/dev/specs/spec-continuation-gitclean-20260809.md evidence",
    )
    result = _spec_check(
        root,
        "check-in",
        "--spec-id",
        plan["artifact_id"],
        "--agent",
        "dev",
        "--agent-id",
        "spec-provider-1",
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)["error_code"] == "checkpoint_template_missing"
    assert not (root / ".claude" / "specs" / plan["artifact_id"] / "cp-state-dev.json").exists()


def test_verify_real_refresh_preserves_numbered_history(tmp_path: Path) -> None:
    root = _project(tmp_path, ("spec-dev-cross-sid-grant-leak.md",))
    artifact_id = "dev-cross-sid-grant-leak"
    cp_dir = root / ".claude" / "specs" / artifact_id
    cp_dir.mkdir(parents=True)
    primary_payload = {
        "spec_id": artifact_id,
        "agent_type": "dev",
        "instance_id": None,
        "generation": 2,
        "agent_id": None,
        "is_running": False,
        "checked_in_at": "2026-08-10T00:00:00Z",
        "checked_out_at": "2026-08-10T00:01:00Z",
        "checkpoints": [{"id": "DEV-OLD", "description": "Retain history", "state": "pending"}],
        "terminal_artifact": {"path": None, "exists": False, "validated_at": None},
    }
    numbered_payload = {**primary_payload, "instance_id": 2, "generation": 1}
    primary = cp_dir / "cp-state-dev.json"
    numbered = cp_dir / "cp-state-dev-2.json"
    primary.write_text(json.dumps(primary_payload), encoding="utf-8")
    numbered.write_text(json.dumps(numbered_payload), encoding="utf-8")
    numbered_before = numbered.read_bytes()
    plan = _plan(
        root,
        "--update --spec docs/dev/specs/spec-dev-cross-sid-grant-leak.md evidence",
    )
    request, _expected = _final_update_fixture(root, plan)
    verified = contract.verify_plan(request)
    assert verified["status"] == "pass"
    result = _cli("verify", request, "--emit-response")
    assert result.returncode == 0, result.stderr
    assert result.stdout == _expected
    assert numbered.read_bytes() == numbered_before
    round_receipt = request["split_lifecycle_receipt"]["rounds"][0]
    assert round_receipt["branch"] == "refresh_primary"
    assert round_receipt["pre_generation"] == 2
    assert round_receipt["expected_generation"] == 3


@pytest.mark.parametrize(
    ("field", "tampered_value"),
    (("after_sha256", "f" * 64), ("split_round", 2)),
)
def test_receipt_round_field_tampering_rejects_after_digest_rebind(
    tmp_path: Path,
    field: str,
    tampered_value: object,
) -> None:
    root = _project(tmp_path, ("spec-receipt-tamper.md",))
    artifact_id = "receipt-tamper"
    cp_dir = root / ".claude" / "specs" / artifact_id
    cp_dir.mkdir(parents=True)
    primary_payload = {
        "spec_id": artifact_id,
        "agent_type": "dev",
        "instance_id": None,
        "generation": 2,
        "agent_id": None,
        "is_running": False,
        "checked_in_at": "2026-08-10T00:00:00Z",
        "checked_out_at": "2026-08-10T00:01:00Z",
        "checkpoints": [{"id": "DEV-OLD", "action": "Retain history", "state": "pending"}],
        "terminal_artifact": {"path": None, "exists": False, "validated_at": None},
    }
    (cp_dir / "cp-state-dev.json").write_text(json.dumps(primary_payload), encoding="utf-8")
    plan = _plan(
        root,
        "--update --spec docs/dev/specs/spec-receipt-tamper.md evidence",
    )
    request, _expected = _final_update_fixture(root, plan)
    request["split_lifecycle_receipt"]["rounds"][0][field] = tampered_value
    manifest_path = root / "docs" / "dev" / "specs" / artifact_id / "views" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["checkpoint_binding"]["receipt_digest"] = _json_digest(
        request["split_lifecycle_receipt"]
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    before = _tree_digest(root)
    with pytest.raises(contract.ContractError):
        contract.verify_plan(request)
    assert _tree_digest(root) == before


@pytest.mark.parametrize("invalid_final_round", (True, False, 1.0, "1", None))
def test_final_round_requires_json_integer_not_bool_or_adjacent_scalar(
    tmp_path: Path,
    invalid_final_round: object,
) -> None:
    root = _project(tmp_path, ("spec-final-round-type.md",))
    artifact_id = "final-round-type"
    cp_dir = root / ".claude" / "specs" / artifact_id
    cp_dir.mkdir(parents=True)
    primary_payload = {
        "spec_id": artifact_id,
        "agent_type": "dev",
        "instance_id": None,
        "generation": 2,
        "agent_id": None,
        "is_running": False,
        "checked_in_at": "2026-08-10T00:00:00Z",
        "checked_out_at": "2026-08-10T00:01:00Z",
        "checkpoints": [{"id": "DEV-OLD", "action": "Retain history", "state": "pending"}],
        "terminal_artifact": {"path": None, "exists": False, "validated_at": None},
    }
    (cp_dir / "cp-state-dev.json").write_text(json.dumps(primary_payload), encoding="utf-8")
    plan = _plan(
        root,
        "--update --spec docs/dev/specs/spec-final-round-type.md evidence",
    )
    request, _expected = _final_update_fixture(root, plan)
    manifest_path = root / "docs" / "dev" / "specs" / artifact_id / "views" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["checkpoint_binding"]["final_round"] = invalid_final_round
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    before = _tree_digest(root)
    result = _cli("verify", request, "--emit-response")
    assert result.returncode == 2
    assert result.stdout == ""
    assert "INVALID_CHECKPOINT_BINDING" in result.stderr
    assert "Traceback" not in result.stderr
    assert _tree_digest(root) == before


def test_command_policy_and_history_placement() -> None:
    command = (ROOT / "commands" / "spec-update.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "disable-model-invocation: true" in command
    assert all(flag in command for flag in ("--update", "--continue", "--temp"))
    assert "scripts/spec-update-contract.py" in command
    assert "Migration note" not in command
    assert "refresh-checkpoints" not in (SCRIPT.read_text(encoding="utf-8"))
    assert "/spec-continue" in changelog and "/spec-update" in changelog
