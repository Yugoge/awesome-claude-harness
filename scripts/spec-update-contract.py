#!/usr/bin/env python3
"""Read-only planner, verifier, and response renderer for ``/spec-update``.

The command policy owns all writes.  This module deliberately has no mutation
subcommand: it authorizes a write set, inventories the inputs, verifies the
provider's post-state, and emits the one canonical response that may be shown to
the user.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
from typing import Any


SCHEMA_VERSION = 1
TASK_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
SPEC_NAME_RE = re.compile(r"spec-.+\.md\Z")
CP_NAME_RE = re.compile(r"cp-state-([A-Za-z0-9][A-Za-z0-9_-]*?)(?:-(\d+))?\.json\Z")
PURPOSE_FLAGS = {"--update": "update", "--continue": "continue", "--temp": "temp"}
VALUE_OPTIONS = {"--spec", "--path"}
REVIEW_FLAG = "--codex"
RECOGNIZED_OPTIONS = set(PURPOSE_FLAGS) | VALUE_OPTIONS | {REVIEW_FLAG, "--"}
ROUND_FIELDS = frozenset(
    {
        "role",
        "branch",
        "pre_primary_state",
        "pre_generation",
        "check_in_kind",
        "expected_generation",
        "argv_kind",
        "emitted_cp_state_path",
        "agent_id",
        "before_sha256",
        "after_sha256",
        "population_digest",
        "status_exit",
        "check_out_exit",
        "terminal_sha256",
        "split_round",
    }
)
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class ContractError(Exception):
    """A stable, expected contract rejection."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _reject(code: str, detail: str) -> None:
    raise ContractError(code, detail)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _require_plain_directory(path: Path, code: str) -> Path:
    try:
        metadata = path.lstat()
    except OSError as exc:
        _reject(code, f"directory is unavailable: {path}: {exc}")
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        _reject(code, f"directory must be real and non-symlinked: {path}")
    return path


def _project_roots(value: Any) -> tuple[Path, Path]:
    if not isinstance(value, str) or not value or not os.path.isabs(value):
        _reject("INVALID_PROJECT_ROOT", "project_dir must be an explicit absolute path")
    lexical = Path(os.path.abspath(value))
    try:
        root = lexical.resolve(strict=True)
    except OSError as exc:
        _reject("INVALID_PROJECT_ROOT", f"project_dir cannot be resolved: {exc}")
    _require_plain_directory(root, "INVALID_PROJECT_ROOT")
    current = root
    for component in ("docs", "dev", "specs"):
        current = _require_plain_directory(current / component, "INVALID_SPEC_ROOT")
    return root, current


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, str):
        _reject("INVALID_REQUEST", "raw_arguments must be a string")
    try:
        tokens = shlex.split(raw, posix=True)
    except ValueError as exc:
        _reject("INVALID_ARGUMENT_SYNTAX", str(exc))

    purpose: str | None = None
    values: dict[str, str] = {}
    codex_required = False
    material: list[str] = []
    options_done = False
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if options_done:
            material.append(token)
            index += 1
            continue
        if token == "--":
            options_done = True
            index += 1
            continue
        if token in PURPOSE_FLAGS:
            if purpose is not None:
                _reject("DUPLICATE_PURPOSE", "purpose flags are mutually exclusive")
            purpose = PURPOSE_FLAGS[token]
            index += 1
            continue
        if token in VALUE_OPTIONS:
            if token in values:
                _reject("DUPLICATE_VALUE_OPTION", f"{token} may appear only once")
            if index + 1 >= len(tokens) or tokens[index + 1] in RECOGNIZED_OPTIONS:
                _reject("MISSING_OPTION_VALUE", f"{token} requires a separate nonempty value")
            value = tokens[index + 1]
            if not value:
                _reject("MISSING_OPTION_VALUE", f"{token} requires a nonempty value")
            values[token] = value
            index += 2
            continue
        if token == REVIEW_FLAG:
            if codex_required:
                _reject("DUPLICATE_REVIEW_OPTION", "--codex may appear only once")
            codex_required = True
            index += 1
            continue
        if token.startswith("-"):
            _reject("UNKNOWN_OPTION", f"unsupported option before --: {token}")
        material.append(token)
        index += 1

    mode = purpose or "continue"
    spec_value = values.get("--spec")
    path_value = values.get("--path")
    if mode == "temp":
        if spec_value is not None:
            _reject("INCOMPATIBLE_OPTION", "--temp forbids --spec")
        if codex_required:
            _reject("INCOMPATIBLE_OPTION", "--temp forbids --codex")
        if not material:
            _reject("MATERIAL_REQUIRED", "--temp requires nonempty material")
    else:
        if path_value is not None:
            _reject("INCOMPATIBLE_OPTION", f"--{mode} forbids --path")
        if mode == "update" and not material:
            _reject("MATERIAL_REQUIRED", "--update requires nonempty material")

    return {
        "mode": mode,
        "codex_required": codex_required,
        "material_tokens": material,
        "material_text": " ".join(material),
        "spec_argument": spec_value,
        "path_argument": path_value,
    }


def _existing_regular(path: Path, code: str) -> Path:
    try:
        metadata = path.lstat()
    except OSError as exc:
        _reject(code, f"target is unavailable: {path}: {exc}")
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        _reject(code, f"target must be a non-symlink regular file: {path}")
    if not os.access(path, os.R_OK):
        _reject(code, f"target is not readable: {path}")
    return path


def _canonical_existing_spec(raw: str, root: Path, spec_root: Path) -> Path:
    supplied = Path(raw)
    if ".." in supplied.parts:
        _reject("INVALID_SPEC_TARGET", "spec target may not contain '..'")
    lexical = supplied if supplied.is_absolute() else root / supplied
    lexical = Path(os.path.abspath(lexical))
    if lexical.parent != spec_root or not SPEC_NAME_RE.fullmatch(lexical.name):
        _reject(
            "INVALID_SPEC_TARGET",
            "spec target must be a direct spec-*.md child of docs/dev/specs",
        )
    _existing_regular(lexical, "INVALID_SPEC_TARGET")
    try:
        canonical = lexical.resolve(strict=True)
    except OSError as exc:
        _reject("INVALID_SPEC_TARGET", f"spec target cannot be resolved: {exc}")
    if canonical.parent != spec_root or canonical != lexical:
        _reject("INVALID_SPEC_TARGET", "spec target must not use symlink components")
    return canonical


def _run_json_provider(root: Path, script_name: str, arguments: list[str]) -> tuple[int, dict[str, Any]]:
    script = root / "scripts" / script_name
    _existing_regular(script, "MISSING_PROVIDER")
    completed = subprocess.run(
        [sys.executable, str(script), *arguments],
        cwd=str(root),
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        _reject(
            "INVALID_PROVIDER_OUTPUT",
            f"{script_name} returned non-JSON output (exit {completed.returncode}): {exc}",
        )
    if not isinstance(payload, dict):
        _reject("INVALID_PROVIDER_OUTPUT", f"{script_name} output must be an object")
    return completed.returncode, payload


def _resolve_spec(path: Path, root: Path) -> dict[str, Any]:
    code, result = _run_json_provider(
        root,
        "resolve-spec-artifacts.py",
        ["--spec-path", str(path), "--project-dir", str(root)],
    )
    if code != 0:
        _reject("INVALID_SPEC_ARTIFACTS", f"spec resolver rejected target with exit {code}")
    if not isinstance(result.get("canonical_id"), str) or not result["canonical_id"]:
        _reject("INVALID_SPEC_ARTIFACTS", "spec resolver omitted canonical_id")
    return result


def _context_target(
    root: Path,
    spec_root: Path,
    context_value: Any,
    expected_task_id: str,
) -> Path:
    if not isinstance(context_value, str) or not context_value:
        _reject("INVALID_ACTIVE_CONTEXT", "resolver context path is missing")
    raw = Path(context_value)
    if ".." in raw.parts:
        _reject("INVALID_ACTIVE_CONTEXT", "context path may not contain '..'")
    path = raw if raw.is_absolute() else root / raw
    path = Path(os.path.abspath(path))
    dev_root = root / "docs" / "dev"
    if path.parent != dev_root:
        _reject("INVALID_ACTIVE_CONTEXT", "context must be a direct docs/dev child")
    _existing_regular(path, "INVALID_ACTIVE_CONTEXT")
    if path.resolve(strict=True) != path:
        _reject("INVALID_ACTIVE_CONTEXT", "context must not be symlinked")
    try:
        context = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _reject("INVALID_ACTIVE_CONTEXT", f"context is not valid JSON: {exc}")
    if not isinstance(context, dict) or context.get("schema_version") != 1:
        _reject("INVALID_ACTIVE_CONTEXT", "context schema_version must be 1")
    if context.get("task_id") != expected_task_id:
        _reject("ACTIVE_CONTEXT_IDENTITY_MISMATCH", "context task_id does not match resolver lane")
    parent_spec = context.get("parent_spec")
    if not isinstance(parent_spec, str) or not parent_spec:
        _reject("MISSING_PARENT_SPEC", "active context must declare parent_spec")
    return _canonical_existing_spec(parent_spec, root, spec_root)


def _resolve_active_target(
    active: Any,
    root: Path,
    spec_root: Path,
) -> tuple[Path, str, str]:
    if not isinstance(active, dict) or active.get("state") != "bound":
        _reject("INVALID_ACTIVE_TASK", "active_task must have state=bound")
    task_id = active.get("task_id")
    if not isinstance(task_id, str) or not TASK_ID_RE.fullmatch(task_id):
        _reject("INVALID_ACTIVE_TASK", "bound active_task requires one safe task_id")
    code, result = _run_json_provider(
        root,
        "resolve-dev-artifact-chain.py",
        ["--task-id", task_id, "--project-dir", str(root)],
    )
    mode = result.get("mode")
    selected: list[tuple[str, Any]] = []
    if mode == "singular":
        expected = f"docs/dev/context-{task_id}.json"
        if expected not in result.get("artifact_paths", []):
            _reject("INVALID_ACTIVE_CHAIN", "singular resolver did not declare its exact context")
        selected = [(task_id, expected)]
    elif mode == "fanout":
        lanes = result.get("lanes")
        if not isinstance(lanes, list) or len(lanes) < 2:
            _reject("INVALID_ACTIVE_CHAIN", "fanout resolver did not establish a lane set")
        seen: set[str] = set()
        for lane in lanes:
            if not isinstance(lane, dict):
                _reject("INVALID_ACTIVE_CHAIN", "fanout lane must be an object")
            lane_id = lane.get("task_id")
            context = lane.get("context")
            if (
                not isinstance(lane_id, str)
                or not lane_id.startswith(task_id + "-")
                or lane_id in seen
            ):
                _reject("INVALID_ACTIVE_CHAIN", "fanout lane identity is invalid or duplicated")
            seen.add(lane_id)
            selected.append((lane_id, context))
    else:
        _reject(
            "INVALID_ACTIVE_CHAIN",
            f"resolver did not establish singular/fanout shape (exit {code})",
        )

    targets = [
        _context_target(root, spec_root, context_path, lane_id)
        for lane_id, context_path in selected
    ]
    target_hashes = {_sha256_file(target) for target in targets}
    if len(set(targets)) != 1 or len(target_hashes) != 1:
        _reject("ACTIVE_SPEC_DISAGREEMENT", "active contexts do not name one path and SHA-256")
    return targets[0], task_id, _digest_json(result)


def _stat_observation(metadata: os.stat_result) -> tuple[int, ...]:
    """Return fields that expose an observed object changing during a read."""

    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _readlink_bytes(path: Path, error_code: str) -> bytes:
    try:
        target = os.readlink(os.fsencode(path))
    except OSError as exc:
        _reject(error_code, f"spec symlink cannot be read: {path}: {exc}")
    if not isinstance(target, bytes):
        _reject(error_code, f"spec symlink did not return raw link bytes: {path}")
    return target


def _strict_realpath_bytes(path: Path, error_code: str) -> bytes | None:
    try:
        resolved = os.path.realpath(os.fsencode(path), strict=True)
    except FileNotFoundError:
        return None
    except OSError as exc:
        _reject(error_code, f"spec symlink referent cannot be resolved: {path}: {exc}")
    if not isinstance(resolved, bytes):
        _reject(error_code, f"spec symlink did not resolve to raw path bytes: {path}")
    return resolved


def _require_stable_symlink(
    path: Path,
    initial: os.stat_result,
    raw_target: bytes,
    error_code: str,
) -> None:
    try:
        current = path.lstat()
    except OSError as exc:
        _reject(error_code, f"spec symlink changed while inventoried: {path}: {exc}")
    if not stat.S_ISLNK(current.st_mode) or _stat_observation(current) != _stat_observation(initial):
        _reject(error_code, f"spec symlink changed while inventoried: {path}")
    if _readlink_bytes(path, error_code) != raw_target:
        _reject(error_code, f"spec symlink target changed while inventoried: {path}")


def _symlink_inventory_entry(
    path: Path,
    metadata: os.stat_result,
    error_code: str,
) -> dict[str, Any]:
    raw_target = _readlink_bytes(path, error_code)
    resolved = _strict_realpath_bytes(path, error_code)
    link_identity = {"device": metadata.st_dev, "inode": metadata.st_ino}
    if resolved is None:
        try:
            os.stat(os.fsencode(path), follow_symlinks=True)
        except FileNotFoundError:
            pass
        except OSError as exc:
            _reject(error_code, f"broken spec symlink cannot be verified: {path}: {exc}")
        else:
            _reject(error_code, f"spec symlink referent raced from broken to valid: {path}")
        _require_stable_symlink(path, metadata, raw_target, error_code)
        if _strict_realpath_bytes(path, error_code) is not None:
            _reject(error_code, f"spec symlink referent changed while inventoried: {path}")
        return {
            "path": path.name,
            "type": "symlink",
            "link_text_hex": raw_target.hex(),
            "link_identity": link_identity,
            "referent": {"state": "broken"},
        }

    try:
        pre_open_referent = os.stat(os.fsencode(path), follow_symlinks=True)
    except OSError as exc:
        _reject(error_code, f"spec symlink referent cannot be inspected before open: {path}: {exc}")
    if not stat.S_ISREG(pre_open_referent.st_mode):
        _reject(error_code, f"spec symlink referent must be a regular file: {path}")
    nonblocking_flag = getattr(os, "O_NONBLOCK", None)
    if not isinstance(nonblocking_flag, int) or nonblocking_flag == 0:
        _reject(error_code, "nonblocking spec referent acquisition is unavailable")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nonblocking_flag
    try:
        descriptor = os.open(os.fsencode(path), flags)
    except OSError as exc:
        _reject(error_code, f"spec symlink referent cannot be opened: {path}: {exc}")
    try:
        try:
            before = os.fstat(descriptor)
        except OSError as exc:
            _reject(error_code, f"spec symlink referent cannot be inspected: {path}: {exc}")
        if not stat.S_ISREG(before.st_mode):
            _reject(error_code, f"spec symlink referent must be a regular file: {path}")
        if _stat_observation(pre_open_referent) != _stat_observation(before):
            _reject(error_code, f"spec symlink referent changed before hashing: {path}")
        digest = hashlib.sha256()
        while True:
            try:
                chunk = os.read(descriptor, 65536)
            except OSError as exc:
                _reject(error_code, f"spec symlink referent cannot be hashed: {path}: {exc}")
            if not chunk:
                break
            digest.update(chunk)
        try:
            after = os.fstat(descriptor)
        except OSError as exc:
            _reject(error_code, f"spec symlink referent cannot be re-inspected: {path}: {exc}")
        if _stat_observation(before) != _stat_observation(after):
            _reject(error_code, f"spec symlink referent changed while hashed: {path}")
    except ContractError:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    try:
        os.close(descriptor)
    except OSError as exc:
        _reject(error_code, f"spec symlink referent descriptor cannot be closed: {path}: {exc}")

    try:
        current_referent = os.stat(os.fsencode(path), follow_symlinks=True)
    except OSError as exc:
        _reject(error_code, f"spec symlink referent changed after hashing: {path}: {exc}")
    if _stat_observation(current_referent) != _stat_observation(after):
        _reject(error_code, f"spec symlink referent changed after hashing: {path}")
    if _strict_realpath_bytes(path, error_code) != resolved:
        _reject(error_code, f"spec symlink resolved path changed while inventoried: {path}")
    _require_stable_symlink(path, metadata, raw_target, error_code)
    return {
        "path": path.name,
        "type": "symlink",
        "link_text_hex": raw_target.hex(),
        "link_identity": link_identity,
        "referent": {
            "state": "valid",
            "type": "file",
            "resolved_path_hex": resolved.hex(),
            "device": after.st_dev,
            "inode": after.st_ino,
            "size": after.st_size,
            "sha256": digest.hexdigest(),
        },
    }


def _spec_inventory(
    spec_root: Path,
    error_code: str = "INVALID_SPEC_INVENTORY",
) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    try:
        children = sorted(spec_root.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        _reject(error_code, f"spec inventory cannot be listed: {spec_root}: {exc}")
    for child in children:
        if not SPEC_NAME_RE.fullmatch(child.name):
            continue
        try:
            metadata = child.lstat()
        except OSError as exc:
            _reject(error_code, f"spec inventory entry cannot be inspected: {child}: {exc}")
        entry: dict[str, Any] = {"path": child.name}
        if stat.S_ISLNK(metadata.st_mode):
            entry = _symlink_inventory_entry(child, metadata, error_code)
        elif stat.S_ISREG(metadata.st_mode):
            try:
                entry.update({"type": "file", "sha256": _sha256_file(child)})
            except OSError as exc:
                _reject(error_code, f"spec inventory file cannot be hashed: {child}: {exc}")
        else:
            entry["type"] = "other"
        inventory.append(entry)
    return inventory


def _read_cp_payload(path: Path, artifact_id: str, role: str, instance: int | None) -> dict[str, Any]:
    _existing_regular(path, "INVALID_CHECKPOINT_INVENTORY")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _reject("INVALID_CHECKPOINT_INVENTORY", f"malformed checkpoint {path}: {exc}")
    if not isinstance(payload, dict):
        _reject("INVALID_CHECKPOINT_INVENTORY", f"checkpoint is not an object: {path}")
    generation = payload.get("generation")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation < 1:
        _reject("INVALID_CHECKPOINT_GENERATION", f"invalid generation in {path}")
    if payload.get("is_running") is not False:
        _reject("ACTIVE_CHECKPOINT_SLOT", f"checkpoint is active: {path}")
    if payload.get("spec_id") not in (None, artifact_id):
        _reject("CHECKPOINT_IDENTITY_MISMATCH", f"checkpoint spec_id mismatch: {path}")
    if payload.get("agent_type") not in (None, role):
        _reject("CHECKPOINT_IDENTITY_MISMATCH", f"checkpoint role mismatch: {path}")
    if payload.get("instance_id") != instance:
        _reject("CHECKPOINT_IDENTITY_MISMATCH", f"checkpoint instance mismatch: {path}")
    checkpoints = payload.get("checkpoints")
    if not isinstance(checkpoints, list):
        _reject("INVALID_CHECKPOINT_INVENTORY", f"checkpoints must be a list: {path}")
    return payload


def _checkpoint_inventory(root: Path, artifact_id: str) -> list[dict[str, Any]]:
    cp_dir = root / ".claude" / "specs" / artifact_id
    if not os.path.lexists(cp_dir):
        return []
    _require_plain_directory(cp_dir, "INVALID_CHECKPOINT_INVENTORY")
    inventory: list[dict[str, Any]] = []
    roles_with_primary: set[str] = set()
    numbered_roles: set[str] = set()
    discovered: list[tuple[Path, str, int | None, str | None]] = []
    normalized_slots: dict[tuple[str, int | None], Path] = {}
    for child in sorted(cp_dir.iterdir(), key=lambda item: item.name):
        match = CP_NAME_RE.fullmatch(child.name)
        if not match:
            continue
        role = match.group(1)
        instance_text = match.group(2)
        instance = int(instance_text) if instance_text is not None else None
        slot_key = (role, instance)
        if slot_key in normalized_slots:
            _reject(
                "DUPLICATE_CHECKPOINT_INSTANCE",
                f"checkpoint filenames {normalized_slots[slot_key].name!r} and "
                f"{child.name!r} resolve to the same role/instance",
            )
        normalized_slots[slot_key] = child
        discovered.append((child, role, instance, instance_text))

    for child, role, instance, instance_text in discovered:
        if instance is not None and instance < 2:
            _reject("INVALID_CHECKPOINT_INVENTORY", f"numbered slot must be >=2: {child}")
        if instance_text is not None and instance_text != str(instance):
            _reject(
                "NONCANONICAL_CHECKPOINT_INSTANCE",
                f"numbered checkpoint filename is not canonical: {child.name}",
            )
        payload = _read_cp_payload(child, artifact_id, role, instance)
        if instance is None:
            roles_with_primary.add(role)
        else:
            numbered_roles.add(role)
        inventory.append(
            {
                "path": _relative(child, root),
                "role": role,
                "instance_id": instance,
                "generation": payload["generation"],
                "is_running": False,
                "sha256": _sha256_file(child),
            }
        )
    orphaned = sorted(numbered_roles - roles_with_primary)
    if orphaned:
        _reject(
            "ORPHAN_NUMBERED_WITHOUT_PRIMARY",
            f"numbered slots exist without primaries for: {', '.join(orphaned)}",
        )
    return inventory


def _reject_lexical_parent_symlinks(path: Path, code: str) -> None:
    """Audit existing parent components before any canonicalization can hide them."""

    if not path.is_absolute():
        _reject(code, "target must be absolute before lexical parent audit")
    current = Path(path.anchor)
    for component in path.parent.parts[1:]:
        current = current / component
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            # The immediate-parent check reports the missing tree consistently.
            break
        except OSError as exc:
            _reject(code, f"cannot inspect lexical parent {current}: {exc}")
        if stat.S_ISLNK(metadata.st_mode):
            _reject(code, f"lexical parent component must not be a symlink: {current}")


def _safe_absent_temp_path(raw: str, root: Path, actor_root: Path) -> Path:
    supplied = Path(raw)
    if ".." in supplied.parts:
        _reject("INVALID_TEMP_TARGET", "temp target may not contain '..'")
    lexical = supplied if supplied.is_absolute() else root / supplied
    lexical = Path(os.path.abspath(lexical))
    if lexical.suffix != ".md":
        _reject("INVALID_TEMP_TARGET", "temp target must end in .md")
    if os.path.lexists(lexical):
        _reject("TEMP_TARGET_EXISTS", "temp target must not already exist")
    _reject_lexical_parent_symlinks(lexical, "INVALID_TEMP_TARGET")
    parent = _require_plain_directory(lexical.parent, "INVALID_TEMP_TARGET")
    parent = parent.resolve(strict=True)
    if not (parent == root or root in parent.parents or parent == actor_root or actor_root in parent.parents):
        _reject("INVALID_TEMP_TARGET", "temp target is outside the project and actor scratch roots")
    candidate = parent / lexical.name
    spec_root = root / "docs" / "dev" / "specs"
    if candidate.parent == spec_root or SPEC_NAME_RE.fullmatch(candidate.name) and spec_root in candidate.parents:
        _reject("TEMP_SPEC_ALIAS", "temp target must not alias or occupy the spec tree")
    return candidate


def _new_spec_target(spec_root: Path, material_text: str) -> Path:
    # Purpose spelling is deliberately excluded: explicit and compatibility
    # continue must authorize the same target for the same decoded material.
    suffix = hashlib.sha256(material_text.encode("utf-8")).hexdigest()[:16]
    target = spec_root / f"spec-continuation-{suffix}.md"
    if os.path.lexists(target):
        _reject("NEW_SPEC_COLLISION", f"deterministic continuation target already exists: {target}")
    return target


def build_plan(request: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic, read-only authorization plan."""

    if not isinstance(request, dict):
        _reject("INVALID_REQUEST", "request must be a JSON object")
    root, spec_root = _project_roots(request.get("project_dir"))
    parsed = _parse_arguments(request.get("raw_arguments"))
    mode = parsed["mode"]
    active = request.get("active_task")

    if mode == "temp":
        scratch_value = request.get("actor_scratch_dir")
        if not isinstance(scratch_value, str) or not os.path.isabs(scratch_value):
            _reject("INVALID_ACTOR_SCRATCH", "temp requires an explicit absolute actor_scratch_dir")
        try:
            actor_root = Path(scratch_value).resolve(strict=True)
        except OSError as exc:
            _reject("INVALID_ACTOR_SCRATCH", f"actor_scratch_dir cannot be resolved: {exc}")
        _require_plain_directory(actor_root, "INVALID_ACTOR_SCRATCH")
        if parsed["path_argument"] is None:
            canonical_target: str | None = None
            allocate = True
        else:
            canonical_target = str(
                _safe_absent_temp_path(parsed["path_argument"], root, actor_root)
            )
            allocate = False
        plan: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "record_type": "spec_update_plan.v1",
            "status": "pass",
            "mode": mode,
            "codex_required": False,
            "material_tokens": parsed["material_tokens"],
            "material_text": parsed["material_text"],
            "project_root": str(root),
            "spec_root": str(spec_root),
            "canonical_target": canonical_target,
            "create_new": True,
            "allocate": allocate,
            "temp_parent": str(actor_root),
            "task_id": None,
            "resolver_digest": None,
            "pre_monolith_sha256": None,
            "spec_inventory": _spec_inventory(spec_root),
            "checkpoint_inventory": [],
            "allowed_write_classes": ["temp_note_create"],
            "write_set": [canonical_target] if canonical_target else [str(actor_root) + "/update-*.md"],
        }
    else:
        explicit = parsed["spec_argument"]
        active_state = active.get("state") if isinstance(active, dict) else None
        if active is not None and active_state not in {"bound", "none"}:
            _reject("INVALID_ACTIVE_TASK", "active_task.state must be bound or none")
        resolver_digest: str | None = None
        task_id: str | None = None
        inferred: Path | None = None
        if active_state == "bound":
            inferred, task_id, resolver_digest = _resolve_active_target(active, root, spec_root)
        if explicit is not None:
            target = _canonical_existing_spec(explicit, root, spec_root)
            if inferred is not None:
                if inferred != target or _sha256_file(inferred) != _sha256_file(target):
                    _reject("EXPLICIT_ACTIVE_DISAGREEMENT", "explicit and active targets differ")
            create_new = False
        elif inferred is not None:
            target = inferred
            create_new = False
        elif active_state == "none" and mode == "continue":
            if not parsed["material_tokens"]:
                _reject("MATERIAL_REQUIRED", "new continuation creation requires material")
            target = _new_spec_target(spec_root, parsed["material_text"])
            create_new = True
        elif active_state == "none" and mode == "update":
            _reject("UPDATE_TARGET_REQUIRED", "update never creates a spec")
        else:
            _reject(
                "ACTIVE_TASK_REQUIRED",
                "repository mode without --spec requires explicit active_task evidence",
            )

        if create_new:
            artifact_id = target.stem[len("spec-") :]
            spec_resolution = None
        else:
            spec_resolution = _resolve_spec(target, root)
            artifact_id = spec_resolution["canonical_id"]
            if resolver_digest is None:
                resolver_digest = _digest_json(spec_resolution)
        plan = {
            "schema_version": SCHEMA_VERSION,
            "record_type": "spec_update_plan.v1",
            "status": "pass",
            "mode": mode,
            "codex_required": parsed["codex_required"],
            "material_tokens": parsed["material_tokens"],
            "material_text": parsed["material_text"],
            "project_root": str(root),
            "spec_root": str(spec_root),
            "canonical_target": str(target),
            "create_new": create_new,
            "allocate": False,
            "temp_parent": None,
            "task_id": task_id,
            "resolver_digest": resolver_digest,
            "artifact_id": artifact_id,
            "spec_resolution": spec_resolution,
            "pre_monolith_sha256": None if create_new else _sha256_file(target),
            "spec_inventory": _spec_inventory(spec_root),
            "checkpoint_inventory": _checkpoint_inventory(root, artifact_id),
            "allowed_write_classes": [
                "monolith_create" if create_new else "monolith_append",
                "split_refresh",
                "canonical_checkpoint_refresh",
                "manifest_binding",
                "split_marker",
            ],
            "write_set": [str(target)],
        }

    plan["plan_digest"] = _digest_json(plan)
    return plan


def _validated_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        _reject("INVALID_PLAN", "plan must be an object")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("record_type") != "spec_update_plan.v1"
        or value.get("status") != "pass"
    ):
        _reject("INVALID_PLAN", "plan identity/status is invalid")
    digest = value.get("plan_digest")
    unsigned = dict(value)
    unsigned.pop("plan_digest", None)
    if not isinstance(digest, str) or digest != _digest_json(unsigned):
        _reject("PLAN_DIGEST_MISMATCH", "plan bytes were changed after authorization")
    return value


def _population_digest(payload: dict[str, Any]) -> str:
    return _digest_json(payload.get("checkpoints"))


def _verify_other_specs(plan: dict[str, Any], spec_root: Path, target: Path) -> None:
    before = {entry["path"]: entry for entry in plan["spec_inventory"]}
    after = {entry["path"]: entry for entry in _spec_inventory(spec_root)}
    target_name = target.name
    for name in sorted(set(before) | set(after)):
        if name == target_name:
            continue
        if before.get(name) != after.get(name):
            _reject("UNEXPECTED_SPEC_WRITE", f"unrelated spec inventory changed: {name}")
    if plan["create_new"]:
        if target_name in before or target_name not in after:
            _reject("INVALID_NEW_SPEC_STATE", "new target inventory transition is invalid")
    elif before.get(target_name, {}).get("type") != "file":
        _reject("INVALID_TARGET_BASELINE", "existing target baseline is missing")


def _receipt_rounds(receipt: Any) -> list[dict[str, Any]]:
    if not isinstance(receipt, dict):
        _reject("INVALID_LIFECYCLE_RECEIPT", "split_lifecycle_receipt must be an object")
    if receipt.get("schema_version") != SCHEMA_VERSION:
        _reject("INVALID_LIFECYCLE_RECEIPT", "receipt schema_version is invalid")
    if receipt.get("record_type") != "split_lifecycle_receipt.v1":
        _reject("INVALID_LIFECYCLE_RECEIPT", "receipt record_type is invalid")
    rounds = receipt.get("rounds")
    if not isinstance(rounds, list) or not rounds:
        _reject("INVALID_LIFECYCLE_RECEIPT", "receipt must contain at least one round")
    if not all(isinstance(item, dict) for item in rounds):
        _reject("INVALID_LIFECYCLE_RECEIPT", "every receipt round must be an object")
    return rounds


def _round_binding(item: dict[str, Any]) -> dict[str, Any]:
    """Return the closed per-round object committed by checkpoint_binding.v1."""

    return {key: item[key] for key in sorted(ROUND_FIELDS)}


def _verify_checkpoint_lifecycle(
    plan: dict[str, Any],
    post_hash: str,
    receipt: dict[str, Any],
    binding: dict[str, Any],
) -> None:
    root = Path(plan["project_root"])
    artifact_id = plan["artifact_id"]
    rounds = _receipt_rounds(receipt)
    if receipt.get("post_monolith_sha256") != post_hash:
        _reject("RECEIPT_POST_HASH_MISMATCH", "receipt does not bind the post-monolith")
    if not isinstance(binding, dict):
        _reject("INVALID_CHECKPOINT_BINDING", "manifest binding must be an object")
    if binding.get("record_type") != "checkpoint_binding.v1":
        _reject("INVALID_CHECKPOINT_BINDING", "manifest binding record_type is invalid")
    if binding.get("post_monolith_sha256") != post_hash:
        _reject("BINDING_POST_HASH_MISMATCH", "manifest binding does not bind the post-monolith")
    if binding.get("receipt_digest") != _digest_json(receipt):
        _reject("RECEIPT_BINDING_MISMATCH", "manifest binding does not bind the receipt")

    pre_entries = {entry["path"]: entry for entry in plan["checkpoint_inventory"]}
    pre_by_role = {
        entry["role"]: entry
        for entry in plan["checkpoint_inventory"]
        if entry["instance_id"] is None
    }
    selected_roles: set[str] = set()
    expected_terminal: dict[str, dict[str, Any]] = {}
    split_rounds: list[int] = []
    for item in rounds:
        if set(item) != ROUND_FIELDS:
            _reject(
                "INVALID_LIFECYCLE_RECEIPT",
                "each lifecycle round must contain exactly the required fields",
            )
        role = item.get("role")
        if not isinstance(role, str) or not role or role in selected_roles:
            _reject("INVALID_LIFECYCLE_RECEIPT", "round roles must be nonempty and unique")
        selected_roles.add(role)
        branch = item.get("branch")
        pre = pre_by_role.get(role)
        if pre is None:
            if branch != "create_primary":
                _reject("INVALID_CREATION_RECEIPT", f"{role} must use create_primary")
            expected = {
                "pre_primary_state": "absent",
                "pre_generation": None,
                "check_in_kind": "ordinary",
                "expected_generation": 1,
                "before_sha256": None,
            }
            if any(
                entry["role"] == role and entry["instance_id"] is not None
                for entry in plan["checkpoint_inventory"]
            ):
                _reject("ORPHAN_NUMBERED_WITHOUT_PRIMARY", f"{role} has numbered history without primary")
        else:
            if branch != "refresh_primary":
                _reject("INVALID_REFRESH_RECEIPT", f"{role} must use refresh_primary")
            expected = {
                "pre_primary_state": "terminal",
                "pre_generation": pre["generation"],
                "check_in_kind": "bump",
                "expected_generation": pre["generation"] + 1,
                "before_sha256": pre["sha256"],
            }
        for key, value in expected.items():
            if item.get(key) != value:
                code = "PRIMARY_STATE_CHANGED" if key == "before_sha256" else "INVALID_LIFECYCLE_RECEIPT"
                _reject(code, f"{role} has invalid {key}")
        after_sha = item.get("after_sha256")
        if not isinstance(after_sha, str) or SHA256_RE.fullmatch(after_sha) is None:
            _reject("INVALID_LIFECYCLE_RECEIPT", f"{role} after_sha256 is invalid")
        if after_sha == item.get("before_sha256"):
            _reject("PRIMARY_STATE_CHANGED", f"{role} populated state did not change")
        split_round = item.get("split_round")
        if isinstance(split_round, bool) or not isinstance(split_round, int) or split_round < 1:
            _reject("INVALID_LIFECYCLE_RECEIPT", f"{role} split_round is invalid")
        if split_rounds and split_round < split_rounds[-1]:
            _reject("INVALID_LIFECYCLE_RECEIPT", "split_round values must be nondecreasing")
        split_rounds.append(split_round)
        if item.get("status_exit") != 0 or item.get("check_out_exit") != 0:
            _reject("INCOMPLETE_LIFECYCLE", f"{role} status/check-out did not succeed")
        if not isinstance(item.get("agent_id"), str) or not item["agent_id"]:
            _reject("INVALID_LIFECYCLE_RECEIPT", f"{role} agent_id is missing")
        if item.get("argv_kind") != item.get("check_in_kind"):
            _reject("INVALID_LIFECYCLE_RECEIPT", f"{role} argv kind disagrees with branch")
        expected_path = root / ".claude" / "specs" / artifact_id / f"cp-state-{role}.json"
        emitted = item.get("emitted_cp_state_path")
        if not isinstance(emitted, str):
            _reject("INVALID_LIFECYCLE_RECEIPT", f"{role} emitted path is missing")
        emitted_path = Path(emitted)
        if not emitted_path.is_absolute():
            emitted_path = root / emitted_path
        if Path(os.path.abspath(emitted_path)) != expected_path:
            _reject("WRONG_CHECKPOINT_SLOT", f"{role} did not use the canonical primary")
        payload = _read_cp_payload(expected_path, artifact_id, role, None)
        if payload.get("generation") != item["expected_generation"]:
            _reject("WRONG_CHECKPOINT_GENERATION", f"{role} terminal generation is wrong")
        if payload.get("agent_id") is not None or payload.get("is_running") is not False:
            _reject("ACTIVE_CHECKPOINT_SLOT", f"{role} primary is not terminal")
        checkpoints = payload.get("checkpoints")
        if not 1 <= len(checkpoints) <= 10:
            _reject("INVALID_CHECKPOINT_POPULATION", f"{role} requires 1..10 checkpoints")
        if not all(isinstance(cp, dict) for cp in checkpoints):
            _reject("INVALID_CHECKPOINT_POPULATION", f"{role} checkpoint entry is invalid")
        checkpoint_ids = [cp.get("id") for cp in checkpoints]
        if (
            not all(isinstance(cp_id, str) and cp_id for cp_id in checkpoint_ids)
            or len(set(checkpoint_ids)) != len(checkpoint_ids)
            or any(cp.get("state") != "pending" for cp in checkpoints)
            or any(
                not isinstance(cp.get("action"), str)
                or re.match(r"[A-Za-z]+(?:\b|_)", cp["action"]) is None
                for cp in checkpoints
            )
        ):
            _reject(
                "INVALID_CHECKPOINT_POPULATION",
                f"{role} checkpoints require unique ids, verb-first actions, and pending state",
            )
        population_digest = _population_digest(payload)
        terminal_sha = _sha256_file(expected_path)
        if item.get("population_digest") != population_digest:
            _reject("POPULATION_DIGEST_MISMATCH", f"{role} population digest is wrong")
        if item.get("terminal_sha256") != terminal_sha:
            _reject("TERMINAL_DIGEST_MISMATCH", f"{role} terminal digest is wrong")
        if after_sha == terminal_sha:
            _reject(
                "INVALID_LIFECYCLE_RECEIPT",
                f"{role} populated-running and terminal checkpoint hashes must differ",
            )
        round_binding = _round_binding(item)
        expected_terminal[role] = {
            "role": role,
            "path": _relative(expected_path, root),
            "generation": payload["generation"],
            "population_digest": population_digest,
            "terminal_sha256": terminal_sha,
            "branch": branch,
            "round": round_binding,
            "round_digest": _digest_json(round_binding),
        }

    post_inventory = _checkpoint_inventory(root, artifact_id)
    post_entries = {entry["path"]: entry for entry in post_inventory}
    pre_numbered = {
        path for path, entry in pre_entries.items() if entry["instance_id"] is not None
    }
    post_numbered = {
        path for path, entry in post_entries.items() if entry["instance_id"] is not None
    }
    if pre_numbered != post_numbered:
        _reject("NUMBERED_SLOT_SET_CHANGED", "numbered checkpoint slot set changed")
    for path, entry in pre_entries.items():
        if entry["instance_id"] is not None or entry["role"] not in selected_roles:
            if post_entries.get(path) != entry:
                _reject("HISTORICAL_CHECKPOINT_CHANGED", f"historical checkpoint changed: {path}")

    selected = binding.get("selected_primaries")
    if not isinstance(selected, list):
        _reject("INVALID_CHECKPOINT_BINDING", "selected_primaries must be a list")
    if len(selected) != len(expected_terminal) or not all(isinstance(entry, dict) for entry in selected):
        _reject("INVALID_CHECKPOINT_BINDING", "selected primary cardinality is not exact")
    selected_map = {entry.get("role"): entry for entry in selected}
    if len(selected_map) != len(selected):
        _reject("INVALID_CHECKPOINT_BINDING", "selected primary roles are duplicated")
    if selected_map != expected_terminal:
        _reject("INVALID_CHECKPOINT_BINDING", "selected primary binding is not exact")
    final_round = binding.get("final_round")
    if isinstance(final_round, bool) or not isinstance(final_round, int):
        _reject("INVALID_CHECKPOINT_BINDING", "manifest final_round must be a JSON integer")
    if final_round != max(split_rounds):
        _reject("INVALID_CHECKPOINT_BINDING", "manifest final_round is not exact")
    expected_history = [
        {
            "path": path,
            "generation": pre_entries[path]["generation"],
            "sha256": pre_entries[path]["sha256"],
        }
        for path in sorted(pre_entries)
        if pre_entries[path]["instance_id"] is not None
        or pre_entries[path]["role"] not in selected_roles
    ]
    if binding.get("historical_slots") != expected_history:
        _reject("INVALID_CHECKPOINT_BINDING", "historical slot binding is not exact")


def verify_plan(request: dict[str, Any]) -> dict[str, Any]:
    """Verify a provider-created post-state without mutating it."""

    if not isinstance(request, dict):
        _reject("INVALID_VERIFY_REQUEST", "verify request must be an object")
    plan = _validated_plan(request.get("plan"))
    mode = plan["mode"]
    root = Path(plan["project_root"])
    spec_root = Path(plan["spec_root"])
    if mode == "temp":
        target_value = plan["canonical_target"]
        if plan.get("allocate"):
            target_value = request.get("allocated_target")
        if not isinstance(target_value, str) or not target_value:
            _reject("INVALID_TEMP_POST_STATE", "allocated temp target is required")
        target = Path(os.path.abspath(target_value))
        _existing_regular(target, "INVALID_TEMP_POST_STATE")
        try:
            canonical_target = target.resolve(strict=True)
        except OSError as exc:
            _reject("INVALID_TEMP_POST_STATE", f"temp target cannot be resolved: {exc}")
        if canonical_target != target:
            _reject("INVALID_TEMP_POST_STATE", "temp target must not use symlink components")
        actor_root = Path(plan["temp_parent"])
        allowed_roots = (actor_root,) if plan.get("allocate") else (root, actor_root)
        if not any(target == allowed or allowed in target.parents for allowed in allowed_roots):
            _reject("INVALID_TEMP_POST_STATE", "temp target escaped its planned confinement roots")
        if not plan.get("allocate") and str(target) != plan.get("canonical_target"):
            _reject("INVALID_TEMP_POST_STATE", "explicit temp target differs from the plan")
        if plan.get("allocate") and (
            target.parent != actor_root
            or not target.name.startswith("update-")
            or target.suffix != ".md"
        ):
            _reject("INVALID_TEMP_POST_STATE", "allocated temp target does not match the plan")
        if target.parent == spec_root or spec_root in target.parents:
            _reject("INVALID_TEMP_POST_STATE", "temp target aliases the spec tree")
        current_spec_inventory = _spec_inventory(
            spec_root,
            "TEMP_SPEC_INVENTORY_CHANGED",
        )
        if current_spec_inventory != plan.get("spec_inventory"):
            _reject(
                "TEMP_SPEC_INVENTORY_CHANGED",
                "planned spec inventory changed after temp authorization",
            )
        for entry in current_spec_inventory:
            spec_path = spec_root / entry["path"]
            if entry.get("type") == "symlink" and entry.get("referent") == {
                "state": "broken"
            }:
                continue
            try:
                aliases_spec = os.path.samefile(target, spec_path)
            except OSError as exc:
                _reject(
                    "TEMP_SPEC_INVENTORY_CHANGED",
                    f"cannot compare temp target to planned spec {spec_path}: {exc}",
                )
            if aliases_spec:
                _reject("TEMP_SPEC_ALIAS", f"temp target aliases spec: {spec_path}")
        post_hash = _sha256_file(target)
    else:
        target = Path(plan["canonical_target"])
        _existing_regular(target, "INVALID_POST_MONOLITH")
        post_hash = _sha256_file(target)
        if post_hash == plan.get("pre_monolith_sha256"):
            _reject("MONOLITH_NOT_UPDATED", "repository mode did not change the monolith")
        _verify_other_specs(plan, spec_root, target)
        resolution = _resolve_spec(target, root)
        if resolution.get("views_available") is not True:
            _reject("SPLIT_NOT_FRESH", "post-state has no validated split views")
        manifest_value = resolution.get("manifest_path")
        if not isinstance(manifest_value, str):
            _reject("INVALID_POST_MANIFEST", "resolver omitted manifest path")
        manifest_path = Path(manifest_value)
        if not manifest_path.is_absolute():
            manifest_path = root / manifest_path
        _existing_regular(manifest_path, "INVALID_POST_MANIFEST")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _reject("INVALID_POST_MANIFEST", str(exc))
        if not isinstance(manifest, dict):
            _reject("INVALID_POST_MANIFEST", "manifest must be an object")
        binding = manifest.get("checkpoint_binding")
        receipt = request.get("split_lifecycle_receipt")
        _verify_checkpoint_lifecycle(plan, post_hash, receipt, binding)

    verified = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "verified_spec_update.v1",
        "status": "pass",
        "mode": mode,
        "plan_digest": plan["plan_digest"],
        "canonical_target": str(target),
        "post_target_sha256": post_hash,
        "codex_required": bool(plan.get("codex_required")),
    }
    candidate = canonical_response(verified)
    render_response(verified, candidate)
    verified["canonical_response"] = candidate
    verified["verification_digest"] = _digest_json(verified)
    return verified


def _verified_identity(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        _reject("INVALID_VERIFIED_PLAN", "verified_plan must be an object")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("record_type") != "verified_spec_update.v1"
        or value.get("status") != "pass"
        or value.get("mode") not in {"update", "continue", "temp"}
        or not isinstance(value.get("plan_digest"), str)
        or not isinstance(value.get("canonical_target"), str)
    ):
        _reject("INVALID_VERIFIED_PLAN", "verified plan identity/status is invalid")
    return value


def canonical_lines(verified_plan: dict[str, Any]) -> list[str]:
    verified = _verified_identity(verified_plan)
    target = verified["canonical_target"]
    if verified["mode"] == "update":
        return [f"Updated spec: {target}"]
    if verified["mode"] == "continue":
        return [f"Continuation spec: {target}", f"Next: /dev --spec {target}"]
    return [f"Temp note: {target}"]


def dev_token_at(text: str, i: int) -> bool:
    """Return whether ``/dev`` at *i* is a boundary-safe slash-command token."""

    if text[i : i + 4] != "/dev":
        return False
    pre_ok = i == 0 or not (text[i - 1].isalnum() or text[i - 1] in "_./-")
    j = i + 4
    post_ok = j >= len(text) or text[j].isspace() or text[j] in "`'\"()[]{}<>:;,!?="
    return pre_ok and post_ok


def canonical_response(verified_plan: dict[str, Any]) -> dict[str, Any]:
    verified = _verified_identity(verified_plan)
    lines = canonical_lines(verified)
    handoff = verified["mode"] == "continue"
    next_command = (
        f"/dev --spec {verified['canonical_target']}" if handoff else None
    )
    rendered = "\n".join(lines) + "\n"
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "canonical_response.v1",
        "status": "pass",
        "mode": verified["mode"],
        "plan_digest": verified["plan_digest"],
        "handoff_allowed": handoff,
        "next_command": next_command,
        "lines": lines,
        "rendered": rendered,
    }


def render_response(verified_plan: dict[str, Any], candidate: Any) -> bytes:
    """Validate the closed response object and return its exact stdout bytes."""

    verified = _verified_identity(verified_plan)
    expected = canonical_response(verified)
    lines = candidate.get("lines") if isinstance(candidate, dict) else None
    structurally_safe = isinstance(lines, list) and all(
        isinstance(line, str) for line in lines
    )
    if structurally_safe:
        embedded_line_break = any("\r" in line or "\n" in line for line in lines)
        text = "\n".join(lines)
        unsafe_update_token = verified["mode"] == "update" and any(
            dev_token_at(text, i) for i in range(len(text))
        )
    else:
        embedded_line_break = True
        unsafe_update_token = False
    closed_object_mismatch = candidate != expected
    if embedded_line_break or unsafe_update_token or closed_object_mismatch:
        _reject(
            "INVALID_UPDATE_RESPONSE" if verified["mode"] == "update" else "INVALID_RESPONSE",
            "candidate response is not the exact canonical response",
        )
    return expected["rendered"].encode("utf-8")


def _read_request() -> dict[str, Any]:
    try:
        value = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        _reject("INVALID_JSON", str(exc))
    if not isinstance(value, dict):
        _reject("INVALID_REQUEST", "stdin JSON must be an object")
    return value


def _emit_json(value: dict[str, Any]) -> None:
    sys.stdout.buffer.write(_canonical_json(value) + b"\n")


def _failure(error: ContractError) -> int:
    sys.stderr.write(f"{error.code}: {error.detail}\n")
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    subparsers.add_parser("plan", help="authorize and inventory without writes")
    verify_parser = subparsers.add_parser("verify", help="verify provider post-state")
    verify_parser.add_argument("--emit-response", action="store_true")
    subparsers.add_parser("render-response", help="validate and emit canonical response")
    args = parser.parse_args(argv)
    try:
        request = _read_request()
        if args.operation == "plan":
            _emit_json(build_plan(request))
            return 0
        if args.operation == "verify":
            verified = verify_plan(request)
            if args.emit_response:
                sys.stdout.buffer.write(
                    render_response(verified, verified["canonical_response"])
                )
            else:
                _emit_json(verified)
            return 0
        verified = request.get("verified_plan")
        candidate = request.get("candidate_response")
        sys.stdout.buffer.write(render_response(verified, candidate))
        return 0
    except ContractError as error:
        return _failure(error)
    except (OSError, ValueError, TypeError, KeyError) as error:
        return _failure(ContractError("INVALID_CONTRACT_STATE", str(error)))


if __name__ == "__main__":
    raise SystemExit(main())
