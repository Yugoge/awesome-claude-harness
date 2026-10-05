"""Linearizable checkpoint-slot allocation shared by production providers.

The directory lock is the transaction boundary: primary-template validation,
owner lookup, slot selection, reset-cloning, and durable publication all happen
while it is held.  Callers never need to duplicate allocation policy.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator


CHECKPOINT_TEMPLATE_MISSING = "checkpoint_template_missing"
CHECKPOINT_TEMPLATE_CORRUPT = "checkpoint_template_corrupt"
CHECKPOINT_TEMPLATE_EMPTY = "checkpoint_template_empty"

_SLOT_RE = re.compile(
    r"^(?P<stem>cp-state-.+)-(?P<slot>(?:[2-9]|[1-9][0-9]+))\.json$"
)


def _now_iso_z() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _failure(error_code: str) -> dict:
    return {"status": "fail", "numbered_path": None, "error_code": error_code}


def _success(path: Path, instance_id: int | None, *, existing: bool = False) -> dict:
    return {
        "status": "pass",
        "numbered_path": str(path) if instance_id is not None else None,
        "path": str(path),
        "instance_id": instance_id,
        "existing_owner": existing,
        "error_code": None,
    }


def _load_populated_template(primary_path: Path) -> tuple[dict | None, str | None]:
    if not primary_path.is_file() or primary_path.is_symlink():
        return None, CHECKPOINT_TEMPLATE_MISSING
    try:
        payload = json.loads(primary_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, CHECKPOINT_TEMPLATE_CORRUPT
    if not isinstance(payload, dict):
        return None, CHECKPOINT_TEMPLATE_CORRUPT
    checkpoints = payload.get("checkpoints")
    if not isinstance(checkpoints, list):
        return None, CHECKPOINT_TEMPLATE_CORRUPT
    if not checkpoints:
        return None, CHECKPOINT_TEMPLATE_EMPTY
    for checkpoint in checkpoints:
        if (
            not isinstance(checkpoint, dict)
            or not isinstance(checkpoint.get("id"), str)
            or not checkpoint["id"]
            or not isinstance(checkpoint.get("action"), str)
            or not checkpoint["action"]
        ):
            return None, CHECKPOINT_TEMPLATE_CORRUPT
    return payload, None


def reset_clone(
    template: dict,
    *,
    instance_id: int,
    agent_id: str,
    artifact: str | None = None,
    now_iso: str | None = None,
) -> dict:
    """Create a populated fresh-resource clone from a validated primary.

    Only checkpoint identity/action cross the resource boundary.  Terminal,
    waiver, mark, and audit data are intentionally not copied.
    """

    now = now_iso or _now_iso_z()
    checkpoints = [
        {
            "id": checkpoint["id"],
            "action": checkpoint["action"],
            "state": "pending",
            "waived_reason": None,
            "updated_at": now,
        }
        for checkpoint in template["checkpoints"]
    ]
    return {
        "spec_id": template.get("spec_id"),
        "agent_type": template.get("agent_type"),
        "instance_id": instance_id,
        "generation": int(template.get("generation", 1) or 1),
        "agent_id": agent_id,
        "is_running": True,
        "checked_in_at": now,
        "checked_out_at": None,
        "updated_at": now,
        "checkpoints": checkpoints,
        "terminal_artifact": {
            "path": artifact,
            "exists": False,
            "validated_at": None,
        },
    }


def _lock_path(primary_path: Path) -> Path:
    return primary_path.parent / ".cp-checkin.lock"


@contextmanager
def directory_transaction(primary_path: Path) -> Iterator[None]:
    """Hold the shared checkpoint-directory lock without mutating JSON first."""

    primary_path = Path(primary_path)
    primary_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _lock_path(primary_path)
    if lock_path.is_symlink():
        raise OSError("checkpoint directory lock is a symlink")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(lock_path, flags, 0o600)
    try:
        with os.fdopen(fd, "a+") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    except Exception:
        # fdopen owns fd once constructed; close only if construction failed.
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def _slot_path(primary_path: Path, instance_id: int) -> Path:
    return primary_path.with_name(f"{primary_path.stem}-{instance_id}.json")


def _numbered_paths(primary_path: Path) -> list[tuple[int, Path]]:
    stem = primary_path.stem
    found: list[tuple[int, Path]] = []
    for child in primary_path.parent.glob(f"{stem}-*.json"):
        match = _SLOT_RE.match(child.name)
        if match and match.group("stem") == stem:
            found.append((int(match.group("slot")), child))
    return sorted(found)


def _load_json_object(path: Path) -> dict | None:
    if not path.is_file() or path.is_symlink():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _find_owner(primary_path: Path, agent_id: str) -> tuple[int | None, Path] | None:
    primary = _load_json_object(primary_path)
    if primary and primary.get("is_running") and primary.get("agent_id") == agent_id:
        return None, primary_path
    for instance_id, path in _numbered_paths(primary_path):
        payload = _load_json_object(path)
        if payload and payload.get("is_running") and payload.get("agent_id") == agent_id:
            return instance_id, path
    return None


def _atomic_write_json(path: Path, payload: dict) -> None:
    if path.is_symlink():
        raise OSError(f"refusing symlink checkpoint target: {path}")
    encoded = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def _next_available_slot(primary_path: Path) -> int:
    instance_id = 2
    while True:
        payload = _load_json_object(_slot_path(primary_path, instance_id))
        if not payload or not payload.get("is_running"):
            return instance_id
        instance_id += 1


def allocate_numbered(
    primary_path: Path | str,
    *,
    agent_id: str,
    artifact: str | None = None,
    now_iso: str | None = None,
) -> dict:
    """Allocate/reset one numbered slot from a populated primary template."""

    primary_path = Path(primary_path)
    # Invalid templates must not even create the directory lock artifact.
    _template, preflight_error = _load_populated_template(primary_path)
    if preflight_error:
        return _failure(preflight_error)
    try:
        with directory_transaction(primary_path):
            template, error = _load_populated_template(primary_path)
            if error:
                return _failure(error)
            assert template is not None
            owner = _find_owner(primary_path, agent_id)
            if owner is not None:
                instance_id, path = owner
                return _success(path, instance_id, existing=True)
            instance_id = _next_available_slot(primary_path)
            path = _slot_path(primary_path, instance_id)
            payload = reset_clone(
                template,
                instance_id=instance_id,
                agent_id=agent_id,
                artifact=artifact,
                now_iso=now_iso,
            )
            _atomic_write_json(path, payload)
            return _success(path, instance_id)
    except OSError:
        return _failure("checkpoint_lock_failed")


def claim_slot(
    primary_path: Path | str,
    *,
    agent_id: str,
    artifact: str | None = None,
    primary_updater: Callable[[dict], dict] | None = None,
) -> dict:
    """Claim the primary if idle, otherwise allocate a reset numbered clone.

    The optional updater lets the CLI retain its established primary takeover
    semantics while the shared directory lock still covers scan through write.
    """

    primary_path = Path(primary_path)
    # Invalid templates must not even create the directory lock artifact.
    _template, preflight_error = _load_populated_template(primary_path)
    if preflight_error:
        return _failure(preflight_error)
    try:
        with directory_transaction(primary_path):
            template, error = _load_populated_template(primary_path)
            if error:
                return _failure(error)
            assert template is not None
            owner = _find_owner(primary_path, agent_id)
            if owner is not None:
                instance_id, path = owner
                return _success(path, instance_id, existing=True)
            if not template.get("is_running"):
                payload = primary_updater(dict(template)) if primary_updater else dict(template)
                _atomic_write_json(primary_path, payload)
                return _success(primary_path, None)
            instance_id = _next_available_slot(primary_path)
            path = _slot_path(primary_path, instance_id)
            payload = reset_clone(
                template,
                instance_id=instance_id,
                agent_id=agent_id,
                artifact=artifact,
            )
            _atomic_write_json(path, payload)
            return _success(path, instance_id)
    except OSError:
        return _failure("checkpoint_lock_failed")


def allocate_checkpoint_slot(*args, **kwargs) -> dict:
    """Stable provider-neutral alias used by future hook integrations."""

    return allocate_numbered(*args, **kwargs)


__all__ = [
    "CHECKPOINT_TEMPLATE_MISSING",
    "CHECKPOINT_TEMPLATE_CORRUPT",
    "CHECKPOINT_TEMPLATE_EMPTY",
    "allocate_checkpoint_slot",
    "allocate_numbered",
    "claim_slot",
    "directory_transaction",
    "reset_clone",
]
