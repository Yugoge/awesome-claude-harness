"""Actor-exact scratch, terminal receipt, and owned-process lifecycle core.

Every destructive operation is bound to an immutable resource session and a
terminal receipt.  The module never scans for a newest session and never
accepts caller-supplied PIDs for registration or signalling.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence


SCHEMA_VERSION = "lane_b.session-resources/v1"
TRUST_SCHEMA_VERSION = "lane_b.session-resources-trust/v1"
TRUST_KEY_ENV = "LANEB_SESSION_RESOURCE_TRUST_KEY"
TRUST_ROOT_ENV = "LANEB_SESSION_RESOURCE_TRUST_ROOT"
TERMINAL_VALUES = frozenset({"completed", "completed_by_deadline", "cancelled_by_user"})
BINDING_FIELDS = (
    "claude_session_id",
    "resource_session_id",
    "role",
    "dispatch_id",
    "agent_id",
    "command",
    "workflow_instance_id",
    "workflow_generation",
    "spec_id",
)
WORKFLOW_IDENTITY_FIELDS = (
    "command",
    "workflow_instance_id",
    "workflow_generation",
)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,191}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ResourceError(ValueError):
    """Fail-closed resource contract violation."""


@dataclass(frozen=True)
class _TrustAuthority:
    project_root: Path
    trust_root: Path
    project_trust_root: Path
    key: bytes
    project_root_sha256: str
    trust_root_identity: tuple[int, int]
    project_trust_root_identity: tuple[int, int]


def _now_iso_z() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def owner_record_interface_digest() -> str:
    return sha256_json({"schema": SCHEMA_VERSION, "binding_fields": BINDING_FIELDS})


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise ResourceError(f"invalid {field}")
    if value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise ResourceError(f"invalid {field}")
    return value


def normalize_binding(record: Mapping[str, object]) -> dict:
    """Return the provider-neutral immutable owner-record projection."""

    if not isinstance(record, Mapping):
        raise ResourceError("binding must be an object")
    normalized: dict = {
        "claude_session_id": _identifier(
            record.get("claude_session_id"), "claude_session_id"
        ),
        "resource_session_id": _identifier(
            record.get("resource_session_id"), "resource_session_id"
        ),
        "role": _identifier(record.get("role"), "role"),
        "dispatch_id": _identifier(record.get("dispatch_id"), "dispatch_id"),
    }
    agent_id = record.get("agent_id", normalized["dispatch_id"])
    normalized["agent_id"] = _identifier(agent_id, "agent_id")
    for field in ("command", "workflow_instance_id", "spec_id"):
        value = record.get(field)
        normalized[field] = None if value is None else _identifier(value, field)
    generation = record.get("workflow_generation")
    if generation is None:
        normalized["workflow_generation"] = None
    elif type(generation) is int and generation >= 1:
        normalized["workflow_generation"] = generation
    else:
        raise ResourceError("invalid workflow_generation")
    return normalized


def _required_workflow_identity(
    record: Mapping[str, object], label: str
) -> dict:
    """Project the required, type-strict destructive workflow identity."""

    if not isinstance(record, Mapping):
        raise ResourceError(f"{label} must be an object")
    command = _identifier(record.get("command"), f"{label} command")
    workflow_instance_id = _identifier(
        record.get("workflow_instance_id"), f"{label} workflow_instance_id"
    )
    workflow_generation = record.get("workflow_generation")
    if type(workflow_generation) is not int or workflow_generation < 1:
        raise ResourceError(f"invalid {label} workflow_generation")
    return {
        "command": command,
        "workflow_instance_id": workflow_instance_id,
        "workflow_generation": workflow_generation,
    }


def binding_digest(record: Mapping[str, object]) -> str:
    return sha256_json(normalize_binding(record))


def _project_root(project_dir: Path | str) -> Path:
    root = Path(project_dir).absolute()
    if not root.is_dir() or root.is_symlink():
        raise ResourceError("project root must be an existing non-symlink directory")
    return root.resolve()


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _open_absolute_directory(
    path: Path, *, create_leaf: bool = False, private_leaf: bool = False
) -> int:
    """Open an absolute directory one non-symlink component at a time.

    Traversal through a previously validated pathname is not authoritative: an
    ancestor can be exchanged for a symlink before the next filesystem call.
    Component-wise ``openat`` pins each parent and makes such an exchange either
    harmless (the pinned external parent is used) or fail closed.
    """

    if not path.is_absolute() or path == Path(path.anchor):
        raise ResourceError("trusted registry directory path is unsafe")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if not hasattr(os, "O_NOFOLLOW"):
        raise ResourceError("trusted registry requires no-follow directory traversal")
    nofollow_flags = flags | os.O_NOFOLLOW
    descriptor = os.open(path.anchor, flags)
    try:
        parts = path.parts[1:]
        for index, part in enumerate(parts):
            final = index == len(parts) - 1
            try:
                child = os.open(part, nofollow_flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not (create_leaf and final):
                    raise ResourceError(
                        f"trusted registry directory is absent or unsafe: {path}"
                    ) from None
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                try:
                    child = os.open(part, nofollow_flags, dir_fd=descriptor)
                except OSError as exc:
                    raise ResourceError(
                        f"trusted registry directory is unsafe: {path}"
                    ) from exc
            except OSError as exc:
                raise ResourceError(
                    f"trusted registry directory is unsafe: {path}"
                ) from exc
            os.close(descriptor)
            descriptor = child
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode):
            raise ResourceError(f"trusted registry directory is unsafe: {path}")
        try:
            path_info = path.lstat()
        except OSError as exc:
            raise ResourceError(
                f"trusted registry directory changed during validation: {path}"
            ) from exc
        if (
            stat.S_ISLNK(path_info.st_mode)
            or path_info.st_dev != info.st_dev
            or path_info.st_ino != info.st_ino
        ):
            raise ResourceError(
                f"trusted registry directory changed during validation: {path}"
            )
        if private_leaf and info.st_mode & 0o077:
            raise ResourceError(f"trusted registry directory is not private: {path}")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _resolved_open_directory(descriptor: int, path: Path) -> Path:
    """Resolve the pinned directory and reject namespace races."""

    try:
        resolved = Path(os.readlink(f"/proc/self/fd/{descriptor}")).resolve(strict=True)
        current = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ResourceError(
            f"trusted registry directory changed during validation: {path}"
        ) from exc
    if current != resolved:
        raise ResourceError(
            f"trusted registry directory changed during validation: {path}"
        )
    return resolved


def _assert_external_trust_path(path: Path, root: Path) -> None:
    if _path_is_within(path, root) or _path_is_within(root, path):
        raise ResourceError("trusted registry root must be external to project")


def _directory_identity(descriptor: int) -> tuple[int, int]:
    info = os.fstat(descriptor)
    return info.st_dev, info.st_ino


def _private_external_directory(path: Path, root: Path) -> tuple[Path, int]:
    """Securely create and retain one private directory outside the project."""

    descriptor = _open_absolute_directory(
        path, create_leaf=True, private_leaf=True
    )
    try:
        resolved = _resolved_open_directory(descriptor, path)
        _assert_external_trust_path(resolved, root)
        return resolved, descriptor
    except Exception:
        os.close(descriptor)
        raise


def _private_external_child_directory(
    parent: Path,
    parent_descriptor: int,
    name: str,
    root: Path,
) -> tuple[Path, int]:
    """Create/open a child through the exact retained parent authority."""

    _resolved_open_directory(parent_descriptor, parent)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    created = False
    descriptor: int | None = None
    try:
        try:
            descriptor = os.open(name, flags, dir_fd=parent_descriptor)
        except FileNotFoundError:
            os.mkdir(name, mode=0o700, dir_fd=parent_descriptor)
            created = True
            descriptor = os.open(name, flags, dir_fd=parent_descriptor)
        if descriptor is None:
            raise ResourceError(
                f"trusted registry directory is unsafe: {parent / name}"
            )
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
            raise ResourceError(
                f"trusted registry directory is unsafe or not private: {parent / name}"
            )
        child = parent / name
        resolved = _resolved_open_directory(descriptor, child)
        _assert_external_trust_path(resolved, root)
        _resolved_open_directory(parent_descriptor, parent)
        return resolved, descriptor
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        if created:
            try:
                os.rmdir(name, dir_fd=parent_descriptor)
            except OSError:
                pass
        raise


def _trust_configuration(
    root: Path, environment: Mapping[str, str] | None = None
) -> _TrustAuthority:
    """Resolve a keyed registry that is deliberately external to the project."""

    values = os.environ if environment is None else environment
    encoded_key = values.get(TRUST_KEY_ENV)
    configured_root = values.get(TRUST_ROOT_ENV)
    if not isinstance(encoded_key, str) or not _SHA256_RE.fullmatch(encoded_key):
        raise ResourceError(f"missing or invalid {TRUST_KEY_ENV}")
    if encoded_key == "0" * 64:
        raise ResourceError(f"invalid {TRUST_KEY_ENV}")
    if not isinstance(configured_root, str) or not configured_root:
        raise ResourceError(f"missing or invalid {TRUST_ROOT_ENV}")
    configured_path = Path(configured_root)
    if not configured_path.is_absolute():
        raise ResourceError("trusted registry root must be absolute")
    configured_path = configured_path.absolute()
    parent_descriptor = _open_absolute_directory(configured_path.parent)
    try:
        resolved_parent = _resolved_open_directory(
            parent_descriptor, configured_path.parent
        )
        if _path_is_within(resolved_parent, root):
            raise ResourceError("trusted registry parent must be external to project")
    finally:
        os.close(parent_descriptor)
    trust_root, trust_root_descriptor = _private_external_directory(
        configured_path, root
    )
    try:
        trust_root_identity = _directory_identity(trust_root_descriptor)
        _resolved_open_directory(trust_root_descriptor, trust_root)
        project_root_sha256 = hashlib.sha256(str(root).encode("utf-8")).hexdigest()
        try:
            os.stat(
                project_root_sha256,
                dir_fd=trust_root_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            existing_resource_state = root / ".claude" / "session-resources"
            if existing_resource_state.exists():
                raise ResourceError(
                    "trusted per-project registry is absent for existing resource state"
                )
        project_trust_root, project_trust_root_descriptor = (
            _private_external_child_directory(
                trust_root,
                trust_root_descriptor,
                project_root_sha256,
                root,
            )
        )
        try:
            _resolved_open_directory(trust_root_descriptor, trust_root)
            _resolved_open_directory(
                project_trust_root_descriptor, project_trust_root
            )
            return _TrustAuthority(
                project_root=root,
                trust_root=trust_root,
                project_trust_root=project_trust_root,
                key=bytes.fromhex(encoded_key),
                project_root_sha256=project_root_sha256,
                trust_root_identity=trust_root_identity,
                project_trust_root_identity=_directory_identity(
                    project_trust_root_descriptor
                ),
            )
        finally:
            os.close(project_trust_root_descriptor)
    finally:
        os.close(trust_root_descriptor)


def _validate_trust_authority(
    authority: _TrustAuthority, *, project_directory_fd: int | None = None
) -> None:
    """Require the exact configured directory objects at every action boundary."""

    trust_descriptor = _open_absolute_directory(
        authority.trust_root, private_leaf=True
    )
    try:
        _resolved_open_directory(trust_descriptor, authority.trust_root)
        if _directory_identity(trust_descriptor) != authority.trust_root_identity:
            raise ResourceError("trusted registry root identity changed")
        _assert_external_trust_path(authority.trust_root, authority.project_root)
    finally:
        os.close(trust_descriptor)
    owned_project_descriptor = project_directory_fd is None
    if project_directory_fd is None:
        project_directory_fd = _open_absolute_directory(
            authority.project_trust_root, private_leaf=True
        )
    try:
        _resolved_open_directory(
            project_directory_fd, authority.project_trust_root
        )
        if (
            _directory_identity(project_directory_fd)
            != authority.project_trust_root_identity
        ):
            raise ResourceError("trusted per-project registry identity changed")
        _assert_external_trust_path(
            authority.project_trust_root, authority.project_root
        )
    finally:
        if owned_project_descriptor:
            os.close(project_directory_fd)


def _trusted_record_path(project_trust_root: Path, claude_session_id: str) -> Path:
    return project_trust_root / f"{claude_session_id}.json"


def _trusted_record_exists(directory_fd: int, name: str) -> bool:
    try:
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ResourceError("trusted workflow registry is absent or unsafe")
    return True


@contextmanager
def _trusted_registry_lock(authority: _TrustAuthority) -> Iterator[int]:
    directory_fd = _open_absolute_directory(
        authority.project_trust_root, private_leaf=True
    )
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(".registry.lock", flags, 0o600, dir_fd=directory_fd)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "a+") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    _validate_trust_authority(
                        authority, project_directory_fd=directory_fd
                    )
                    yield directory_fd
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
    finally:
        os.close(directory_fd)


def _atomic_trusted_replace(
    path: Path,
    payload: object,
    project_trust_root: Path,
    *,
    directory_fd: int | None = None,
) -> None:
    if path.parent != project_trust_root:
        raise ResourceError("trusted registry target is unsafe")
    encoded = _canonical_bytes(payload) + b"\n"
    owned_directory_fd = directory_fd is None
    if directory_fd is None:
        directory_fd = _open_absolute_directory(
            project_trust_root, private_leaf=True
        )
    try:
        target_info = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        if stat.S_ISLNK(target_info.st_mode) or not stat.S_ISREG(target_info.st_mode):
            if owned_directory_fd:
                os.close(directory_fd)
            raise ResourceError("trusted registry target is unsafe")
    temporary_name = f".{path.name}.{os.getpid()}.{os.urandom(12).hex()}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(temporary_name, flags, 0o600, dir_fd=directory_fd)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(
            temporary_name,
            path.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        os.fsync(directory_fd)
    finally:
        try:
            os.unlink(temporary_name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        if owned_directory_fd:
            os.close(directory_fd)


def _trusted_hmac(payload: Mapping[str, object], key: bytes) -> str:
    return hmac.new(key, _canonical_bytes(payload), hashlib.sha256).hexdigest()


def _sign_trusted_record(payload: Mapping[str, object], key: bytes) -> dict:
    unsigned = dict(payload)
    unsigned.pop("hmac_sha256", None)
    return {**unsigned, "hmac_sha256": _trusted_hmac(unsigned, key)}


def _validate_trusted_record(
    value: Mapping[str, object],
    *,
    key: bytes,
    project_root_sha256: str,
    claude_session_id: str,
    trust_authority: _TrustAuthority | None = None,
) -> dict:
    expected_fields = {
        "schema",
        "project_root_sha256",
        "trust_root_identity",
        "project_trust_root_identity",
        "claude_session_id",
        "resource_session_id",
        "workflow_identity",
        "actor_binding_sha256",
        "state",
        "finalization_authorization_sha256",
        "revision",
        "hmac_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != expected_fields:
        raise ResourceError("trusted workflow registry shape mismatch")
    unsigned = dict(value)
    supplied_hmac = unsigned.pop("hmac_sha256")
    if not isinstance(supplied_hmac, str) or not hmac.compare_digest(
        supplied_hmac, _trusted_hmac(unsigned, key)
    ):
        raise ResourceError("trusted workflow registry authentication mismatch")
    if (
        value.get("schema") != TRUST_SCHEMA_VERSION
        or value.get("project_root_sha256") != project_root_sha256
        or value.get("claude_session_id") != claude_session_id
    ):
        raise ResourceError("trusted workflow registry identity mismatch")
    validated_directory_identities: dict[str, tuple[int, int]] = {}
    for field in ("trust_root_identity", "project_trust_root_identity"):
        raw_identity = value.get(field)
        if (
            not isinstance(raw_identity, list)
            or len(raw_identity) != 2
            or any(type(item) is not int or item < 0 for item in raw_identity)
        ):
            raise ResourceError("trusted registry directory identity is invalid")
        validated_directory_identities[field] = (
            raw_identity[0], raw_identity[1]
        )
    if trust_authority is not None and (
        validated_directory_identities["trust_root_identity"]
        != trust_authority.trust_root_identity
        or validated_directory_identities["project_trust_root_identity"]
        != trust_authority.project_trust_root_identity
    ):
        raise ResourceError("trusted registry directory identity changed")
    resource_session_id = _identifier(
        value.get("resource_session_id"), "trusted resource_session_id"
    )
    raw_identity = value.get("workflow_identity")
    if not isinstance(raw_identity, dict) or set(raw_identity) != set(
        WORKFLOW_IDENTITY_FIELDS
    ):
        raise ResourceError("trusted workflow identity shape mismatch")
    workflow_identity = _required_workflow_identity(
        raw_identity, "trusted workflow registry"
    )
    if _canonical_bytes(raw_identity) != _canonical_bytes(workflow_identity):
        raise ResourceError("trusted workflow identity mismatch")
    actor_digests = value.get("actor_binding_sha256")
    if (
        not isinstance(actor_digests, list)
        or not actor_digests
        or not all(isinstance(item, str) and _SHA256_RE.fullmatch(item) for item in actor_digests)
        or actor_digests != sorted(set(actor_digests))
    ):
        raise ResourceError("trusted workflow actor registry mismatch")
    state = value.get("state")
    authorization = value.get("finalization_authorization_sha256")
    if state == "active":
        if authorization is not None:
            raise ResourceError("active trusted workflow has finalization authorization")
    elif state == "authorized":
        if not isinstance(authorization, str) or not _SHA256_RE.fullmatch(authorization):
            raise ResourceError("trusted finalization authorization is invalid")
    else:
        raise ResourceError("trusted workflow registry state mismatch")
    revision = value.get("revision")
    if type(revision) is not int or revision < 1:
        raise ResourceError("trusted workflow registry revision invalid")
    return {
        **dict(value),
        "resource_session_id": resource_session_id,
        "workflow_identity": workflow_identity,
        "actor_binding_sha256": list(actor_digests),
    }


def _load_trusted_record(
    path: Path,
    *,
    key: bytes,
    project_root_sha256: str,
    claude_session_id: str,
    directory_fd: int | None = None,
    trust_authority: _TrustAuthority | None = None,
) -> dict:
    owned_directory_fd = directory_fd is None
    if directory_fd is None:
        directory_fd = _open_absolute_directory(path.parent, private_leaf=True)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd: int | None = None
    try:
        fd = os.open(path.name, flags, dir_fd=directory_fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ResourceError("trusted workflow registry is absent or unsafe")
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            fd = None
            value = json.load(handle)
    except FileNotFoundError as exc:
        raise ResourceError("trusted workflow registry is absent or unsafe") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ResourceError("trusted workflow registry is corrupt") from exc
    finally:
        if fd is not None:
            os.close(fd)
        if owned_directory_fd:
            os.close(directory_fd)
    return _validate_trusted_record(
        value,
        key=key,
        project_root_sha256=project_root_sha256,
        claude_session_id=claude_session_id,
        trust_authority=trust_authority,
    )


def _write_trusted_record(
    path: Path,
    payload: Mapping[str, object],
    *,
    key: bytes,
    project_trust_root: Path,
    project_root_sha256: str,
    claude_session_id: str,
    directory_fd: int | None = None,
    trust_authority: _TrustAuthority | None = None,
) -> dict:
    signed = _sign_trusted_record(payload, key)
    _atomic_trusted_replace(
        path,
        signed,
        project_trust_root,
        directory_fd=directory_fd,
    )
    loaded = _load_trusted_record(
        path,
        key=key,
        project_root_sha256=project_root_sha256,
        claude_session_id=claude_session_id,
        directory_fd=directory_fd,
        trust_authority=trust_authority,
    )
    if _canonical_bytes(loaded) != _canonical_bytes(signed):
        raise ResourceError("trusted workflow registry durable write mismatch")
    return loaded


def _assert_beneath(path: Path, root: Path, label: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ResourceError(f"{label} escapes project root") from exc


def _ensure_directory(path: Path, root: Path) -> None:
    _assert_beneath(path, root, "resource directory")
    relative = path.relative_to(root)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            cursor.mkdir(mode=0o700)
            info = cursor.lstat()
        if not cursor.is_dir() or os.path.islink(cursor):
            raise ResourceError(f"resource directory is not trusted: {cursor}")
        if info.st_mode & 0o002:
            raise ResourceError(f"resource directory is world-writable: {cursor}")


def _resource_base(root: Path) -> Path:
    return root / ".claude" / "session-resources"


def _resource_root(root: Path, resource_session_id: str) -> Path:
    return _resource_base(root) / resource_session_id


def scratch_path(project_dir: Path | str, binding: Mapping[str, object]) -> Path:
    root = _project_root(project_dir)
    owner = normalize_binding(binding)
    return (
        root
        / ".claude"
        / "scratch"
        / owner["resource_session_id"]
        / owner["role"]
        / owner["dispatch_id"]
    )


def managed_temp_path(project_dir: Path | str, binding: Mapping[str, object]) -> Path:
    return scratch_path(project_dir, binding) / "tmp"


def managed_environment(
    project_dir: Path | str, binding: Mapping[str, object]
) -> dict[str, str]:
    temp = str(managed_temp_path(project_dir, binding))
    return {"TMPDIR": temp, "TMP": temp, "TEMP": temp}


@contextmanager
def _exclusive_lock(path: Path, root: Path) -> Iterator[None]:
    _ensure_directory(path.parent, root)
    if path.is_symlink():
        raise ResourceError(f"lock is a symlink: {path}")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def _atomic_replace(path: Path, payload: object, root: Path) -> None:
    _ensure_directory(path.parent, root)
    if path.is_symlink():
        raise ResourceError(f"refusing symlink target: {path}")
    encoded = _canonical_bytes(payload) + b"\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temporary)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def _create_or_verify(path: Path, payload: object, root: Path) -> None:
    _ensure_directory(path.parent, root)
    encoded = _canonical_bytes(payload) + b"\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        if path.is_symlink() or path.read_bytes() != encoded:
            raise ResourceError(f"immutable resource collision: {path}")
        return
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _load_object(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise ResourceError(f"missing or unsafe resource record: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ResourceError(f"corrupt resource record: {path}") from exc
    if not isinstance(value, dict):
        raise ResourceError(f"resource record is not an object: {path}")
    return value


def _pointer_path(root: Path, claude_session_id: str) -> Path:
    return _resource_base(root) / "by-claude-session" / f"{claude_session_id}.json"


def _session_manifest_path(root: Path, resource_session_id: str) -> Path:
    return _resource_root(root, resource_session_id) / "session.json"


def _actor_manifest_path(root: Path, binding: Mapping[str, object]) -> Path:
    return (
        _resource_root(root, str(binding["resource_session_id"]))
        / "actors"
        / str(binding["role"])
        / f"{binding['dispatch_id']}.json"
    )


def _terminal_path(root: Path, resource_session_id: str) -> Path:
    return _resource_root(root, resource_session_id) / "terminal.json"


def _validate_session_anchor(
    session: Mapping[str, object],
    *,
    claude_session_id: str,
    resource_session_id: str,
) -> dict:
    expected_fields = {
        "schema",
        "claude_session_id",
        "resource_session_id",
        "workflow_identity",
        "workflow_identity_sha256",
    }
    if set(session) != expected_fields:
        raise ResourceError("immutable session workflow anchor shape mismatch")
    if (
        session.get("schema") != SCHEMA_VERSION
        or session.get("claude_session_id") != claude_session_id
        or session.get("resource_session_id") != resource_session_id
    ):
        raise ResourceError("immutable session workflow anchor identity mismatch")
    raw_identity = session.get("workflow_identity")
    if not isinstance(raw_identity, dict) or set(raw_identity) != set(
        WORKFLOW_IDENTITY_FIELDS
    ):
        raise ResourceError("immutable session workflow identity shape mismatch")
    identity = _required_workflow_identity(raw_identity, "session anchor")
    if _canonical_bytes(raw_identity) != _canonical_bytes(identity):
        raise ResourceError("immutable session workflow identity mismatch")
    if session.get("workflow_identity_sha256") != sha256_json(identity):
        raise ResourceError("immutable session workflow identity digest mismatch")
    return identity


def _validate_actor_manifest(
    root: Path,
    claude_session_id: str,
    resource_session_id: str,
    path: Path,
    manifest: Mapping[str, object],
    *,
    session_identity: Mapping[str, object],
    session_manifest_sha256: str,
    expected_role: str,
    expected_dispatch_id: str,
) -> dict:
    expected_fields = {
        "schema",
        "binding",
        "binding_sha256",
        "owner_record_interface_sha256",
        "workflow_identity_sha256",
        "session_manifest_sha256",
        "scratch_path",
        "managed_temp_path",
    }
    if set(manifest) != expected_fields or manifest.get("schema") != SCHEMA_VERSION:
        raise ResourceError("actor manifest anchor shape mismatch")
    raw_binding = manifest.get("binding")
    if not isinstance(raw_binding, dict) or set(raw_binding) != set(BINDING_FIELDS):
        raise ResourceError("actor manifest binding shape mismatch")
    owner = normalize_binding(raw_binding)
    if _canonical_bytes(raw_binding) != _canonical_bytes(owner):
        raise ResourceError("actor manifest binding mismatch")
    if (
        owner["claude_session_id"] != claude_session_id
        or owner["resource_session_id"] != resource_session_id
        or owner["role"] != expected_role
        or owner["dispatch_id"] != expected_dispatch_id
        or path != _actor_manifest_path(root, owner)
    ):
        raise ResourceError("actor manifest path identity mismatch")
    if manifest.get("binding_sha256") != sha256_json(owner):
        raise ResourceError("actor manifest binding digest mismatch")
    if manifest.get("owner_record_interface_sha256") != owner_record_interface_digest():
        raise ResourceError("actor manifest interface mismatch")
    actor_identity = _required_workflow_identity(owner, "actor manifest")
    if _canonical_bytes(actor_identity) != _canonical_bytes(session_identity):
        raise ResourceError("actor manifest workflow identity mismatch")
    if manifest.get("workflow_identity_sha256") != sha256_json(session_identity):
        raise ResourceError("actor manifest workflow identity digest mismatch")
    if manifest.get("session_manifest_sha256") != session_manifest_sha256:
        raise ResourceError("actor manifest session anchor digest mismatch")
    expected_scratch = scratch_path(root, owner)
    if (
        manifest.get("scratch_path") != str(expected_scratch)
        or manifest.get("managed_temp_path") != str(expected_scratch / "tmp")
    ):
        raise ResourceError("actor manifest scratch mismatch")
    return owner


def _load_finalization_actor_anchors(
    root: Path,
    claude_session_id: str,
    resource_session_id: str,
    *,
    session_identity: Mapping[str, object],
    session_manifest_sha256: str,
) -> list[dict]:
    """Validate every actor anchor; never choose one ambiguous candidate."""

    actors = _resource_root(root, resource_session_id) / "actors"
    if actors.is_symlink() or not actors.is_dir():
        raise ResourceError("actor workflow anchor is absent or unsafe")
    try:
        with os.scandir(actors) as entries:
            role_entries = sorted(entries, key=lambda item: item.name)
    except OSError as exc:
        raise ResourceError("actor workflow anchor scan failed") from exc
    validated: list[dict] = []
    for role_entry in role_entries:
        if role_entry.is_symlink() or not role_entry.is_dir(follow_symlinks=False):
            raise ResourceError("actor workflow anchor role is ambiguous")
        role = _identifier(role_entry.name, "actor manifest role")
        try:
            with os.scandir(role_entry.path) as entries:
                dispatch_entries = sorted(entries, key=lambda item: item.name)
        except OSError as exc:
            raise ResourceError("actor workflow anchor scan failed") from exc
        if not dispatch_entries:
            raise ResourceError("actor workflow anchor role is empty")
        for dispatch_entry in dispatch_entries:
            if (
                dispatch_entry.is_symlink()
                or not dispatch_entry.is_file(follow_symlinks=False)
                or not dispatch_entry.name.endswith(".json")
            ):
                raise ResourceError("actor workflow anchor selection is ambiguous")
            dispatch_id = _identifier(
                dispatch_entry.name[:-5], "actor manifest dispatch_id"
            )
            path = Path(dispatch_entry.path)
            manifest = _load_object(path)
            validated.append(
                _validate_actor_manifest(
                    root,
                    claude_session_id,
                    resource_session_id,
                    path,
                    manifest,
                    session_identity=session_identity,
                    session_manifest_sha256=session_manifest_sha256,
                    expected_role=role,
                    expected_dispatch_id=dispatch_id,
                )
            )
    if not validated:
        raise ResourceError("actor workflow anchor is absent")
    return validated


def _trusted_record_identity_matches(
    record: Mapping[str, object],
    *,
    resource_session_id: str,
    workflow_identity: Mapping[str, object],
) -> bool:
    return record.get("resource_session_id") == resource_session_id and _canonical_bytes(
        record.get("workflow_identity")
    ) == _canonical_bytes(workflow_identity)


def _trusted_record_can_advance(root: Path, record: Mapping[str, object]) -> bool:
    """Only a fully authorized and already-cleaned workflow may be superseded."""

    if record.get("state") != "authorized":
        return False
    resource_session_id = str(record["resource_session_id"])
    finalized_path = _resource_root(root, resource_session_id) / "finalized.json"
    authorization = record.get("finalization_authorization_sha256")
    if (
        not finalized_path.is_file()
        or finalized_path.is_symlink()
        or not isinstance(authorization, str)
        or hashlib.sha256(finalized_path.read_bytes()).hexdigest() != authorization
    ):
        return False
    scratch = root / ".claude" / "scratch" / resource_session_id
    process_directory = _process_directory(root, resource_session_id)
    return not scratch.exists() and (
        not process_directory.exists()
        or (
            process_directory.is_dir()
            and not process_directory.is_symlink()
            and not any(process_directory.iterdir())
        )
    )


def provision(
    project_dir: Path | str,
    binding: Mapping[str, object],
    *,
    trust_environment: Mapping[str, str] | None = None,
) -> dict:
    """Atomically provision one exact actor owner and its managed temp."""

    root = _project_root(project_dir)
    owner = normalize_binding(binding)
    workflow_identity = _required_workflow_identity(owner, "provision binding")
    workflow_identity_sha256 = sha256_json(workflow_identity)
    resource_root = _resource_root(root, owner["resource_session_id"])
    trust_authority = _trust_configuration(root, trust_environment)
    project_trust_root = trust_authority.project_trust_root
    trust_key = trust_authority.key
    project_root_sha256 = trust_authority.project_root_sha256
    trust_path = _trusted_record_path(project_trust_root, owner["claude_session_id"])
    with _trusted_registry_lock(trust_authority) as trust_directory_fd:
        trusted: dict | None = None
        if _trusted_record_exists(trust_directory_fd, trust_path.name):
            trusted = _load_trusted_record(
                trust_path,
                key=trust_key,
                project_root_sha256=project_root_sha256,
                claude_session_id=owner["claude_session_id"],
                directory_fd=trust_directory_fd,
                trust_authority=trust_authority,
            )
        same_trusted_workflow = trusted is not None and _trusted_record_identity_matches(
            trusted,
            resource_session_id=owner["resource_session_id"],
            workflow_identity=workflow_identity,
        )
        if trusted is not None and same_trusted_workflow and trusted["state"] != "active":
            raise ResourceError("trusted workflow is already finalization-authorized")
        if (
            trusted is not None
            and not same_trusted_workflow
            and not _trusted_record_can_advance(root, trusted)
        ):
            raise ResourceError("claude session already has a trusted current workflow")

        _validate_trust_authority(
            trust_authority, project_directory_fd=trust_directory_fd
        )
        with _exclusive_lock(resource_root / ".resource.lock", root):
            session_manifest = {
                "schema": SCHEMA_VERSION,
                "claude_session_id": owner["claude_session_id"],
                "resource_session_id": owner["resource_session_id"],
                "workflow_identity": workflow_identity,
                "workflow_identity_sha256": workflow_identity_sha256,
            }
            session_manifest_path = _session_manifest_path(
                root, owner["resource_session_id"]
            )
            _create_or_verify(session_manifest_path, session_manifest, root)
            _validate_session_anchor(
                _load_object(session_manifest_path),
                claude_session_id=owner["claude_session_id"],
                resource_session_id=owner["resource_session_id"],
            )
            session_manifest_sha256 = hashlib.sha256(
                session_manifest_path.read_bytes()
            ).hexdigest()
            scratch = scratch_path(root, owner)
            temp = scratch / "tmp"
            _ensure_directory(temp, root)
            manifest = {
                "schema": SCHEMA_VERSION,
                "binding": owner,
                "binding_sha256": sha256_json(owner),
                "owner_record_interface_sha256": owner_record_interface_digest(),
                "workflow_identity_sha256": workflow_identity_sha256,
                "session_manifest_sha256": session_manifest_sha256,
                "scratch_path": str(scratch),
                "managed_temp_path": str(temp),
            }
            _create_or_verify(_actor_manifest_path(root, owner), manifest, root)

            pointer_path = _pointer_path(root, owner["claude_session_id"])
            pointer = {
                "schema": SCHEMA_VERSION,
                "claude_session_id": owner["claude_session_id"],
                "resource_session_id": owner["resource_session_id"],
                "workflow_instance_id": owner["workflow_instance_id"],
                "workflow_generation": owner["workflow_generation"],
                "command": owner["command"],
            }
            with _exclusive_lock(pointer_path.with_suffix(".lock"), root):
                if pointer_path.exists():
                    current = _load_object(pointer_path)
                    if current != pointer:
                        if trusted is None or same_trusted_workflow:
                            raise ResourceError(
                                "current pointer conflicts with trusted workflow"
                            )
                        _atomic_replace(pointer_path, pointer, root)
                else:
                    _atomic_replace(pointer_path, pointer, root)

            actor_digest = sha256_json(owner)
            actor_digests = (
                sorted(set([*trusted["actor_binding_sha256"], actor_digest]))
                if same_trusted_workflow and trusted is not None
                else [actor_digest]
            )
            trusted_payload = {
                "schema": TRUST_SCHEMA_VERSION,
                "project_root_sha256": project_root_sha256,
                "trust_root_identity": list(trust_authority.trust_root_identity),
                "project_trust_root_identity": list(
                    trust_authority.project_trust_root_identity
                ),
                "claude_session_id": owner["claude_session_id"],
                "resource_session_id": owner["resource_session_id"],
                "workflow_identity": workflow_identity,
                "actor_binding_sha256": actor_digests,
                "state": "active",
                "finalization_authorization_sha256": None,
                "revision": int(trusted["revision"]) + 1 if trusted is not None else 1,
            }
            _write_trusted_record(
                trust_path,
                trusted_payload,
                key=trust_key,
                project_trust_root=project_trust_root,
                project_root_sha256=project_root_sha256,
                claude_session_id=owner["claude_session_id"],
                directory_fd=trust_directory_fd,
                trust_authority=trust_authority,
            )
    return {
        "status": "pass",
        "binding": owner,
        "binding_sha256": manifest["binding_sha256"],
        "scratch_path": str(scratch),
        "managed_temp_path": str(temp),
        "manifest_path": str(_actor_manifest_path(root, owner)),
    }


def load_actor_manifest(
    project_dir: Path | str, binding: Mapping[str, object]
) -> dict:
    root = _project_root(project_dir)
    owner = normalize_binding(binding)
    session_path = _session_manifest_path(root, owner["resource_session_id"])
    session_identity = _validate_session_anchor(
        _load_object(session_path),
        claude_session_id=owner["claude_session_id"],
        resource_session_id=owner["resource_session_id"],
    )
    manifest_path = _actor_manifest_path(root, owner)
    manifest = _load_object(manifest_path)
    validated_owner = _validate_actor_manifest(
        root,
        owner["claude_session_id"],
        owner["resource_session_id"],
        manifest_path,
        manifest,
        session_identity=session_identity,
        session_manifest_sha256=hashlib.sha256(session_path.read_bytes()).hexdigest(),
        expected_role=owner["role"],
        expected_dispatch_id=owner["dispatch_id"],
    )
    if _canonical_bytes(validated_owner) != _canonical_bytes(owner):
        raise ResourceError("actor manifest does not match requested binding")
    return manifest


def classify_target(
    project_dir: Path | str, binding: Mapping[str, object], target: Path | str
) -> dict:
    """Classify a static write target without granting policy authority."""

    root = _project_root(project_dir)
    owner = normalize_binding(binding)
    raw = os.fspath(target)
    if not raw or "\x00" in raw or "$" in raw or "`" in raw:
        return {"status": "unresolved", "owner": False, "path": raw}
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve(strict=False)
    owner_root = scratch_path(root, owner)
    scratch_root = root / ".claude" / "scratch"
    for candidate in (path, *path.parents):
        if candidate.exists() and candidate.is_symlink():
            return {"status": "unresolved", "owner": False, "path": str(path)}
        if candidate == root.parent:
            break
    try:
        resolved.relative_to(owner_root)
        return {"status": "owner", "owner": True, "path": str(resolved)}
    except ValueError:
        pass
    try:
        resolved.relative_to(scratch_root)
        status = "sibling"
    except ValueError:
        status = (
            "system_temp"
            if resolved == Path("/tmp")
            or Path("/tmp") in resolved.parents
            or resolved == Path("/var/tmp")
            or Path("/var/tmp") in resolved.parents
            else "outside"
        )
    return {"status": status, "owner": False, "path": str(resolved)}


def _validate_current_pointer(
    root: Path, session_id: str, trusted: Mapping[str, object]
) -> dict:
    pointer = _load_object(_pointer_path(root, session_id))
    if pointer.get("schema") != SCHEMA_VERSION or pointer.get(
        "claude_session_id"
    ) != session_id:
        raise ResourceError("current resource pointer session mismatch")
    resource_session_id = _identifier(
        pointer.get("resource_session_id"), "resource_session_id"
    )
    session = _load_object(_session_manifest_path(root, resource_session_id))
    _validate_session_anchor(
        session,
        claude_session_id=session_id,
        resource_session_id=resource_session_id,
    )
    pointer_identity = _required_workflow_identity(pointer, "current pointer")
    if not _trusted_record_identity_matches(
        trusted,
        resource_session_id=resource_session_id,
        workflow_identity=pointer_identity,
    ):
        raise ResourceError("current resource pointer trusted identity mismatch")
    return pointer


def resolve_current_resource_session(
    project_dir: Path | str,
    claude_session_id: str,
    *,
    trust_environment: Mapping[str, str] | None = None,
) -> dict:
    root = _project_root(project_dir)
    session_id = _identifier(claude_session_id, "claude_session_id")
    trust_authority = _trust_configuration(root, trust_environment)
    project_trust_root = trust_authority.project_trust_root
    trust_key = trust_authority.key
    project_root_sha256 = trust_authority.project_root_sha256
    trust_path = _trusted_record_path(project_trust_root, session_id)
    with _trusted_registry_lock(trust_authority) as trust_directory_fd:
        trusted = _load_trusted_record(
            trust_path,
            key=trust_key,
            project_root_sha256=project_root_sha256,
            claude_session_id=session_id,
            directory_fd=trust_directory_fd,
            trust_authority=trust_authority,
        )
        return _validate_current_pointer(root, session_id, trusted)


def publish_terminal_receipt(
    project_dir: Path | str,
    *,
    claude_session_id: str,
    resource_session_id: str,
    command: str,
    terminal_status: str,
    workflow_instance_id: str | None = None,
    workflow_generation: int | None = None,
    overnight_identity: Mapping[str, object] | None = None,
    trust_environment: Mapping[str, str] | None = None,
) -> dict:
    """Atomically publish an absorbing, non-destructive terminal receipt."""

    root = _project_root(project_dir)
    claude_session_id = _identifier(claude_session_id, "claude_session_id")
    resource_session_id = _identifier(resource_session_id, "resource_session_id")
    command = _identifier(command, "command")
    if terminal_status not in TERMINAL_VALUES:
        raise ResourceError("invalid terminal_status")
    if workflow_instance_id is not None:
        workflow_instance_id = _identifier(
            workflow_instance_id, "workflow_instance_id"
        )
    if workflow_generation is not None and (
        type(workflow_generation) is not int or workflow_generation < 1
    ):
        raise ResourceError("invalid workflow_generation")
    receipt_identity = _required_workflow_identity(
        {
            "command": command,
            "workflow_instance_id": workflow_instance_id,
            "workflow_generation": workflow_generation,
        },
        "terminal receipt",
    )
    trust_authority = _trust_configuration(root, trust_environment)
    project_trust_root = trust_authority.project_trust_root
    trust_key = trust_authority.key
    project_root_sha256 = trust_authority.project_root_sha256
    trust_path = _trusted_record_path(project_trust_root, claude_session_id)
    resource_root = _resource_root(root, resource_session_id)
    with _trusted_registry_lock(trust_authority) as trust_directory_fd:
        trusted = _load_trusted_record(
            trust_path,
            key=trust_key,
            project_root_sha256=project_root_sha256,
            claude_session_id=claude_session_id,
            directory_fd=trust_directory_fd,
            trust_authority=trust_authority,
        )
        if trusted["state"] != "active" or not _trusted_record_identity_matches(
            trusted,
            resource_session_id=resource_session_id,
            workflow_identity=receipt_identity,
        ):
            raise ResourceError("terminal receipt trusted workflow identity mismatch")
        with _exclusive_lock(resource_root / ".resource.lock", root):
            session_path = _session_manifest_path(root, resource_session_id)
            session_identity = _validate_session_anchor(
                _load_object(session_path),
                claude_session_id=claude_session_id,
                resource_session_id=resource_session_id,
            )
            if _canonical_bytes(receipt_identity) != _canonical_bytes(session_identity):
                raise ResourceError("terminal receipt session workflow anchor mismatch")
            pointer_path = _pointer_path(root, claude_session_id)
            with _exclusive_lock(pointer_path.with_suffix(".lock"), root):
                pointer = _validate_current_pointer(root, claude_session_id, trusted)
                if pointer.get("resource_session_id") != resource_session_id:
                    raise ResourceError("terminal receipt is stale for claude session")
                identity = {
                    "schema": SCHEMA_VERSION,
                    "claude_session_id": claude_session_id,
                    "resource_session_id": resource_session_id,
                    "workflow_instance_id": workflow_instance_id,
                    "workflow_generation": workflow_generation,
                    "command": command,
                    "terminal_status": terminal_status,
                    "overnight_identity": dict(overnight_identity or {}),
                    "session_manifest_sha256": hashlib.sha256(
                        session_path.read_bytes()
                    ).hexdigest(),
                }
                terminal_path = _terminal_path(root, resource_session_id)
                with _exclusive_lock(terminal_path.with_suffix(".lock"), root):
                    if terminal_path.exists():
                        existing = _load_object(terminal_path)
                        comparable = dict(existing)
                        comparable.pop("terminal_at", None)
                        if comparable != identity:
                            raise ResourceError("terminal receipt is absorbing")
                        return {
                            "status": "pass",
                            "receipt": existing,
                            "idempotent": True,
                        }
                    receipt = {**identity, "terminal_at": _now_iso_z()}
                    _create_or_verify(terminal_path, receipt, root)
    return {"status": "pass", "receipt": receipt, "idempotent": False}


def publish_workflow_receipt(
    project_dir: Path | str,
    *,
    claude_session_id: str,
    bookmark: Mapping[str, object],
) -> dict:
    command = bookmark.get("command")
    if not isinstance(command, str):
        raise ResourceError("workflow bookmark command missing")
    resource_session_id = bookmark.get("task_id") or bookmark.get(
        "workflow_instance_id"
    )
    workflow_instance_id = bookmark.get("workflow_instance_id")
    if not isinstance(workflow_instance_id, str):
        raise ResourceError("workflow bookmark instance missing")
    workflow_generation = bookmark.get("workflow_generation")
    if type(workflow_generation) is not int or workflow_generation < 1:
        raise ResourceError("workflow bookmark generation invalid")
    return publish_terminal_receipt(
        project_dir,
        claude_session_id=claude_session_id,
        resource_session_id=_identifier(resource_session_id, "resource_session_id"),
        command=command,
        terminal_status="completed",
        workflow_instance_id=workflow_instance_id,
        workflow_generation=workflow_generation,
    )


def publish_overnight_receipt(
    project_dir: Path | str,
    *,
    claude_session_id: str,
    state: Mapping[str, object],
    terminal_status: str,
) -> dict:
    if state.get("session_id") != claude_session_id:
        raise ResourceError("overnight state session mismatch")
    resource_session_id = _identifier(
        state.get("dev_registry_session_id"), "resource_session_id"
    )
    cycle = state.get("cycle_id", state.get("cycle_count", 0))
    if type(cycle) is not int or cycle < 0:
        raise ResourceError("overnight cycle identity invalid")
    return publish_terminal_receipt(
        project_dir,
        claude_session_id=claude_session_id,
        resource_session_id=resource_session_id,
        command="dev-overnight",
        terminal_status=terminal_status,
        workflow_instance_id=f"overnight:{claude_session_id}",
        workflow_generation=cycle + 1,
        overnight_identity={
            "session_id": claude_session_id,
            "dev_registry_session_id": resource_session_id,
            "cycle": cycle,
        },
    )


def _proc_start_time(pid: int) -> str | None:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
    except (OSError, UnicodeError):
        return None
    return fields[21] if len(fields) > 21 else None


def _process_directory(root: Path, resource_session_id: str) -> Path:
    return _resource_root(root, resource_session_id) / "processes"


def _process_record_path(root: Path, resource_session_id: str, pid: int) -> Path:
    return _process_directory(root, resource_session_id) / f"{pid}.json"


def spawn_owned(
    project_dir: Path | str,
    binding: Mapping[str, object],
    argv: Sequence[str],
    *,
    cwd: Path | str | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> dict:
    """Launch and register one new process group owned by the exact actor."""

    root = _project_root(project_dir)
    owner = normalize_binding(binding)
    manifest = load_actor_manifest(root, owner)
    if not argv or not all(isinstance(value, str) and value for value in argv):
        raise ResourceError("argv must be a non-empty string list")
    workdir = Path(cwd) if cwd is not None else Path(manifest["scratch_path"])
    workdir = workdir.resolve(strict=False)
    if classify_target(root, owner, workdir).get("status") != "owner":
        raise ResourceError("process cwd must remain in owner scratch")
    # The external HMAC key is a hook-side capability, never actor data.
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {TRUST_KEY_ENV, TRUST_ROOT_ENV}
    }
    env.update(managed_environment(root, owner))
    if extra_env:
        for key, value in extra_env.items():
            if not isinstance(key, str) or not isinstance(value, str) or "\x00" in value:
                raise ResourceError("invalid process environment")
            if key in {"TMPDIR", "TMP", "TEMP", TRUST_KEY_ENV, TRUST_ROOT_ENV}:
                raise ResourceError("managed resource variables cannot be overridden")
            env[key] = value
    process = subprocess.Popen(
        list(argv),
        cwd=str(workdir),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        pgid = os.getpgid(process.pid)
        start_time = _proc_start_time(process.pid)
        if pgid != process.pid or start_time is None:
            raise ResourceError("new process identity could not be verified")
        record = {
            "schema": SCHEMA_VERSION,
            "resource_session_id": owner["resource_session_id"],
            "binding_sha256": sha256_json(owner),
            "role": owner["role"],
            "dispatch_id": owner["dispatch_id"],
            "pid": process.pid,
            "pgid": pgid,
            "proc_start_time": start_time,
            "argv_sha256": hashlib.sha256(
                b"\0".join(value.encode("utf-8") for value in argv)
            ).hexdigest(),
            "started_at": _now_iso_z(),
        }
        record_path = _process_record_path(root, owner["resource_session_id"], process.pid)
        _create_or_verify(record_path, record, root)
    except Exception:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        process.wait(timeout=2)
        raise
    return {
        "status": "pass",
        "pid": process.pid,
        "pgid": pgid,
        "proc_start_time": start_time,
        "record_path": str(record_path),
    }


def exec_owned(
    project_dir: Path | str,
    binding: Mapping[str, object],
    argv: Sequence[str],
    *,
    timeout: float | None = None,
) -> dict:
    """Run one foreground owned group and retire its process record on exit."""

    spawned = spawn_owned(project_dir, binding, argv)
    pid = int(spawned["pid"])
    try:
        returncode = os.waitpid(pid, 0)[1]
        exit_code = os.waitstatus_to_exitcode(returncode)
    except ChildProcessError:
        exit_code = 0
    root = _project_root(project_dir)
    owner = normalize_binding(binding)
    try:
        _process_record_path(root, owner["resource_session_id"], pid).unlink()
    except FileNotFoundError:
        pass
    return {"status": "pass" if exit_code == 0 else "fail", "exit_code": exit_code}


def _load_process_records(root: Path, resource_session_id: str) -> list[tuple[Path, dict]]:
    directory = _process_directory(root, resource_session_id)
    if not directory.exists():
        return []
    if directory.is_symlink() or not directory.is_dir():
        raise ResourceError("process registry is unsafe")
    records = []
    for path in sorted(directory.glob("*.json")):
        records.append((path, _load_object(path)))
    return records


def _record_identity(
    record: Mapping[str, object], resource_session_id: str, root: Path | None = None
) -> str:
    if record.get("schema") != SCHEMA_VERSION:
        return "mismatch"
    if record.get("resource_session_id") != resource_session_id:
        return "mismatch"
    if root is not None:
        try:
            role = _identifier(record.get("role"), "role")
            dispatch_id = _identifier(record.get("dispatch_id"), "dispatch_id")
            manifest = _load_object(
                _resource_root(root, resource_session_id)
                / "actors"
                / role
                / f"{dispatch_id}.json"
            )
        except ResourceError:
            return "mismatch"
        if manifest.get("binding_sha256") != record.get("binding_sha256"):
            return "mismatch"
    pid = record.get("pid")
    pgid = record.get("pgid")
    start = record.get("proc_start_time")
    if type(pid) is not int or type(pgid) is not int or pid <= 1 or pgid != pid:
        return "mismatch"
    try:
        waited, _status = os.waitpid(pid, os.WNOHANG)
        if waited == pid:
            return "exited"
    except ChildProcessError:
        # A production coordinator may not be the spawning parent; /proc is
        # authoritative in that case.
        pass
    current_start = _proc_start_time(pid)
    if current_start is None:
        return "exited"
    try:
        current_pgid = os.getpgid(pid)
    except ProcessLookupError:
        return "exited"
    if current_start != start or current_pgid != pgid or pid == os.getpid():
        return "mismatch"
    return "alive"


def _wait_for_exit(
    records: Iterable[Mapping[str, object]], deadline: float, root: Path
) -> list[dict]:
    remaining = [dict(record) for record in records]
    while remaining and time.monotonic() < deadline:
        remaining = [
            record
            for record in remaining
            if _record_identity(record, str(record["resource_session_id"]), root) == "alive"
        ]
        if remaining:
            time.sleep(0.02)
    return remaining


def _contains_symlink(path: Path) -> bool:
    if path.is_symlink():
        return True
    if not path.exists():
        return False
    for current, directories, files in os.walk(path, followlinks=False):
        current_path = Path(current)
        for name in directories + files:
            if (current_path / name).is_symlink():
                return True
    return False


def _stable_file_bytes(path: Path, label: str) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ResourceError(f"missing or unsafe {label}") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ResourceError(f"{label} is not a regular file")
        chunks = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(fd)
        try:
            current = path.lstat()
        except OSError as exc:
            raise ResourceError(f"{label} changed while validating") from exc
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        )
        identity_current = (
            current.st_dev,
            current.st_ino,
            current.st_size,
            current.st_mtime_ns,
        )
        if identity_before != identity_after or identity_after != identity_current:
            raise ResourceError(f"{label} changed while validating")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _object_from_bytes(payload: bytes, label: str) -> dict:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ResourceError(f"corrupt {label}") from exc
    if not isinstance(value, dict):
        raise ResourceError(f"{label} is not an object")
    return value


def _validated_finalization_inputs(
    root: Path,
    *,
    claude_session_id: str,
    resource_session_id: str,
    trusted: Mapping[str, object],
) -> dict:
    """Validate and byte-snapshot every owner-controlled identity record."""

    trusted_identity_record = trusted.get("workflow_identity")
    if not isinstance(trusted_identity_record, Mapping):
        raise ResourceError("trusted workflow identity shape mismatch")
    if not _trusted_record_identity_matches(
        trusted,
        resource_session_id=resource_session_id,
        workflow_identity=trusted_identity_record,
    ):
        raise ResourceError("trusted workflow resource identity mismatch")
    pointer_path = _pointer_path(root, claude_session_id)
    session_path = _session_manifest_path(root, resource_session_id)
    terminal_path = _terminal_path(root, resource_session_id)
    pointer_bytes = _stable_file_bytes(pointer_path, "current pointer")
    session_bytes = _stable_file_bytes(session_path, "session anchor")
    terminal_bytes = _stable_file_bytes(terminal_path, "terminal receipt")
    pointer = _object_from_bytes(pointer_bytes, "current pointer")
    session = _object_from_bytes(session_bytes, "session anchor")
    receipt = _object_from_bytes(terminal_bytes, "terminal receipt")
    expected_pointer_fields = {
        "schema",
        "claude_session_id",
        "resource_session_id",
        *WORKFLOW_IDENTITY_FIELDS,
    }
    if set(pointer) != expected_pointer_fields:
        raise ResourceError("current pointer shape mismatch")
    if (
        pointer.get("schema") != SCHEMA_VERSION
        or pointer.get("claude_session_id") != claude_session_id
        or pointer.get("resource_session_id") != resource_session_id
    ):
        raise ResourceError("terminal receipt current pointer identity mismatch")
    session_identity = _validate_session_anchor(
        session,
        claude_session_id=claude_session_id,
        resource_session_id=resource_session_id,
    )
    try:
        pointer_identity = _required_workflow_identity(pointer, "current pointer")
    except ResourceError as exc:
        raise ResourceError(
            "terminal receipt current pointer identity mismatch"
        ) from exc
    receipt_identity = _required_workflow_identity(receipt, "terminal receipt")
    trusted_identity = _required_workflow_identity(
        trusted_identity_record, "trusted workflow registry"
    )
    if _canonical_bytes(pointer_identity) != _canonical_bytes(trusted_identity):
        raise ResourceError("terminal receipt current pointer identity mismatch")
    if (
        _canonical_bytes(session_identity) != _canonical_bytes(trusted_identity)
        or _canonical_bytes(receipt_identity) != _canonical_bytes(trusted_identity)
    ):
        raise ResourceError("terminal workflow trusted identity mismatch")
    expected_receipt_fields = {
        "schema",
        "claude_session_id",
        "resource_session_id",
        *WORKFLOW_IDENTITY_FIELDS,
        "terminal_status",
        "overnight_identity",
        "session_manifest_sha256",
        "terminal_at",
    }
    if (
        set(receipt) != expected_receipt_fields
        or receipt.get("schema") != SCHEMA_VERSION
        or receipt.get("claude_session_id") != claude_session_id
        or receipt.get("resource_session_id") != resource_session_id
        or receipt.get("terminal_status") not in TERMINAL_VALUES
        or not isinstance(receipt.get("overnight_identity"), dict)
        or not isinstance(receipt.get("terminal_at"), str)
        or not receipt.get("terminal_at")
    ):
        raise ResourceError("terminal receipt identity mismatch")
    session_sha256 = hashlib.sha256(session_bytes).hexdigest()
    if receipt.get("session_manifest_sha256") != session_sha256:
        raise ResourceError("terminal receipt session manifest digest mismatch")
    actor_anchors = _load_finalization_actor_anchors(
        root,
        claude_session_id,
        resource_session_id,
        session_identity=session_identity,
        session_manifest_sha256=session_sha256,
    )
    actor_digests = sorted(sha256_json(actor) for actor in actor_anchors)
    if actor_digests != trusted.get("actor_binding_sha256"):
        raise ResourceError("actor manifests do not match trusted workflow registry")
    record_sha256 = {
        "pointer": hashlib.sha256(pointer_bytes).hexdigest(),
        "session": session_sha256,
        "terminal": hashlib.sha256(terminal_bytes).hexdigest(),
    }
    for actor in actor_anchors:
        path = _actor_manifest_path(root, actor)
        actor_bytes = _stable_file_bytes(path, "actor manifest")
        manifest = _object_from_bytes(actor_bytes, "actor manifest")
        _validate_actor_manifest(
            root,
            claude_session_id,
            resource_session_id,
            path,
            manifest,
            session_identity=session_identity,
            session_manifest_sha256=session_sha256,
            expected_role=actor["role"],
            expected_dispatch_id=actor["dispatch_id"],
        )
        key = f"actor:{actor['role']}/{actor['dispatch_id']}"
        if key in record_sha256:
            raise ResourceError("actor workflow anchor selection is ambiguous")
        record_sha256[key] = hashlib.sha256(actor_bytes).hexdigest()
    return {
        "receipt": receipt,
        "terminal_bytes": terminal_bytes,
        "session_identity": session_identity,
        "actor_anchors": actor_anchors,
        "owner_records_sha256": record_sha256,
    }


def _process_record_snapshot(
    root: Path, resource_session_id: str, records: Sequence[tuple[Path, dict]]
) -> dict[str, str]:
    directory = _process_directory(root, resource_session_id)
    snapshot: dict[str, str] = {}
    for path, _record in records:
        try:
            relative = path.relative_to(directory)
        except ValueError as exc:
            raise ResourceError("process registry path escapes owner directory") from exc
        if len(relative.parts) != 1 or relative.suffix != ".json":
            raise ResourceError("process registry path is ambiguous")
        snapshot[relative.name] = hashlib.sha256(
            _stable_file_bytes(path, "process registry record")
        ).hexdigest()
    return snapshot


def _validate_finalized_record(
    value: Mapping[str, object],
    *,
    key: bytes,
    project_root_sha256: str,
    claude_session_id: str,
    resource_session_id: str,
    workflow_identity_sha256: str,
    actor_binding_sha256: Sequence[str],
    terminal_receipt_sha256: str,
    owner_records_sha256: Mapping[str, str],
    trust_revision: int,
    process_records_sha256: Mapping[str, str] | None,
) -> dict:
    expected_fields = {
        "schema",
        "trust_schema",
        "project_root_sha256",
        "claude_session_id",
        "resource_session_id",
        "workflow_identity_sha256",
        "actor_binding_sha256",
        "terminal_receipt_sha256",
        "owner_records_sha256",
        "process_records_sha256",
        "trust_revision",
        "authorized_at",
        "hmac_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != expected_fields:
        raise ResourceError("finalized record shape mismatch")
    unsigned = dict(value)
    supplied_hmac = unsigned.pop("hmac_sha256")
    if not isinstance(supplied_hmac, str) or not hmac.compare_digest(
        supplied_hmac, _trusted_hmac(unsigned, key)
    ):
        raise ResourceError("finalized record authentication mismatch")
    exact = {
        "schema": SCHEMA_VERSION,
        "trust_schema": TRUST_SCHEMA_VERSION,
        "project_root_sha256": project_root_sha256,
        "claude_session_id": claude_session_id,
        "resource_session_id": resource_session_id,
        "workflow_identity_sha256": workflow_identity_sha256,
        "actor_binding_sha256": list(actor_binding_sha256),
        "terminal_receipt_sha256": terminal_receipt_sha256,
        "owner_records_sha256": dict(owner_records_sha256),
        "trust_revision": trust_revision,
    }
    if any(value.get(field) != expected for field, expected in exact.items()):
        raise ResourceError("finalized record identity mismatch")
    process_snapshot = value.get("process_records_sha256")
    if (
        not isinstance(process_snapshot, dict)
        or not all(
            isinstance(name, str)
            and isinstance(digest, str)
            and _SHA256_RE.fullmatch(digest)
            for name, digest in process_snapshot.items()
        )
    ):
        raise ResourceError("finalized process registry snapshot mismatch")
    if process_records_sha256 is not None and process_snapshot != dict(
        process_records_sha256
    ):
        raise ResourceError("finalized process registry collision")
    if not isinstance(value.get("authorized_at"), str) or not value.get("authorized_at"):
        raise ResourceError("finalized authorization time is invalid")
    return dict(value)


def _load_valid_finalized_record(
    path: Path,
    **validation: object,
) -> tuple[dict, bytes]:
    payload = _stable_file_bytes(path, "finalized record")
    value = _object_from_bytes(payload, "finalized record")
    return _validate_finalized_record(value, **validation), payload  # type: ignore[arg-type]


def _remove_prepared_finalized(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def status(project_dir: Path | str, resource_session_id: str) -> dict:
    """Return exact resource state without pruning or other mutation."""

    root = _project_root(project_dir)
    resource_session_id = _identifier(resource_session_id, "resource_session_id")
    session = _load_object(_session_manifest_path(root, resource_session_id))
    processes = []
    for path, record in _load_process_records(root, resource_session_id):
        processes.append(
            {
                "record_path": str(path),
                "pid": record.get("pid"),
                "identity": _record_identity(record, resource_session_id, root),
            }
        )
    scratch = root / ".claude" / "scratch" / resource_session_id
    receipt_path = _terminal_path(root, resource_session_id)
    return {
        "status": "pass",
        "session": session,
        "scratch_path": str(scratch),
        "scratch_exists": scratch.exists(),
        "terminal_receipt_exists": receipt_path.is_file() and not receipt_path.is_symlink(),
        "processes": processes,
    }


def finalize(
    project_dir: Path | str,
    *,
    claude_session_id: str,
    resource_session_id: str,
    term_timeout: float = 1.0,
    kill_timeout: float = 1.0,
    trust_environment: Mapping[str, str] | None = None,
) -> dict:
    """Receipt-gated exact-session finalization of registered resources only."""

    root = _project_root(project_dir)
    claude_session_id = _identifier(claude_session_id, "claude_session_id")
    resource_session_id = _identifier(resource_session_id, "resource_session_id")
    resource_root = _resource_root(root, resource_session_id)
    trust_authority = _trust_configuration(root, trust_environment)
    project_trust_root = trust_authority.project_trust_root
    trust_key = trust_authority.key
    project_root_sha256 = trust_authority.project_root_sha256
    trust_path = _trusted_record_path(project_trust_root, claude_session_id)
    pointer_lock = _pointer_path(root, claude_session_id).with_suffix(".lock")
    terminal_lock = _terminal_path(root, resource_session_id).with_suffix(".lock")
    finalized_path = resource_root / "finalized.json"
    scratch = root / ".claude" / "scratch" / resource_session_id

    def finalized_validation(
        inputs: Mapping[str, object],
        trusted: Mapping[str, object],
        process_snapshot: Mapping[str, str] | None,
    ) -> dict[str, object]:
        revision_value = trusted.get("revision")
        if type(revision_value) is not int:
            raise ResourceError("trusted workflow registry revision invalid")
        revision = revision_value
        if trusted["state"] == "authorized":
            revision -= 1
        terminal_bytes = inputs.get("terminal_bytes")
        if not isinstance(terminal_bytes, bytes):
            raise ResourceError("terminal receipt byte snapshot missing")
        return {
            "key": trust_key,
            "project_root_sha256": project_root_sha256,
            "claude_session_id": claude_session_id,
            "resource_session_id": resource_session_id,
            "workflow_identity_sha256": sha256_json(inputs["session_identity"]),
            "actor_binding_sha256": trusted["actor_binding_sha256"],
            "terminal_receipt_sha256": hashlib.sha256(
                terminal_bytes
            ).hexdigest(),
            "owner_records_sha256": inputs["owner_records_sha256"],
            "trust_revision": revision,
            "process_records_sha256": process_snapshot,
        }

    # Optimistic read phase: no process inspection occurs until the external,
    # keyed current-workflow record and every owner-controlled record agree.
    with _trusted_registry_lock(trust_authority) as trust_directory_fd:
        trusted_initial = _load_trusted_record(
            trust_path,
            key=trust_key,
            project_root_sha256=project_root_sha256,
            claude_session_id=claude_session_id,
            directory_fd=trust_directory_fd,
            trust_authority=trust_authority,
        )
        with _exclusive_lock(resource_root / ".resource.lock", root):
            with _exclusive_lock(pointer_lock, root):
                with _exclusive_lock(terminal_lock, root):
                    inputs_initial = _validated_finalization_inputs(
                        root,
                        claude_session_id=claude_session_id,
                        resource_session_id=resource_session_id,
                        trusted=trusted_initial,
                    )
                    if finalized_path.exists():
                        _load_valid_finalized_record(
                            finalized_path,
                            **finalized_validation(
                                inputs_initial, trusted_initial, None
                            ),
                        )
                    elif trusted_initial["state"] == "authorized":
                        raise ResourceError(
                            "trusted finalization authorization has no finalized record"
                        )

    _validate_trust_authority(trust_authority)
    if _contains_symlink(scratch):
        return {
            "status": "fail",
            "error_code": "scratch_symlink_detected",
            "signalled": [],
        }
    records_initial = _load_process_records(root, resource_session_id)
    process_snapshot_initial = _process_record_snapshot(
        root, resource_session_id, records_initial
    )
    identities_initial = [
        (path, record, _record_identity(record, resource_session_id, root))
        for path, record in records_initial
    ]
    mismatches = [
        str(path)
        for path, _record, identity in identities_initial
        if identity == "mismatch"
    ]
    if mismatches:
        return {
            "status": "fail",
            "error_code": "process_identity_mismatch",
            "signalled": [],
            "mismatched_records": mismatches,
        }

    # Commit phase: an advance during the optimistic gap is rejected.  The
    # external lock is then held through authorization and cleanup, while the
    # keyed authorization makes the validated snapshot authoritative.
    with _trusted_registry_lock(trust_authority) as trust_directory_fd:
        trusted_current = _load_trusted_record(
            trust_path,
            key=trust_key,
            project_root_sha256=project_root_sha256,
            claude_session_id=claude_session_id,
            directory_fd=trust_directory_fd,
            trust_authority=trust_authority,
        )
        if _canonical_bytes(trusted_current) != _canonical_bytes(trusted_initial):
            raise ResourceError("trusted workflow advanced during finalization")
        with _exclusive_lock(resource_root / ".resource.lock", root):
            with _exclusive_lock(pointer_lock, root):
                with _exclusive_lock(terminal_lock, root):
                    inputs_current = _validated_finalization_inputs(
                        root,
                        claude_session_id=claude_session_id,
                        resource_session_id=resource_session_id,
                        trusted=trusted_current,
                    )
                    if inputs_current["owner_records_sha256"] != inputs_initial[
                        "owner_records_sha256"
                    ]:
                        raise ResourceError(
                            "workflow identity records changed during finalization"
                        )
                    if _contains_symlink(scratch):
                        return {
                            "status": "fail",
                            "error_code": "scratch_symlink_detected",
                            "signalled": [],
                        }
                    records = _load_process_records(root, resource_session_id)
                    process_snapshot = _process_record_snapshot(
                        root, resource_session_id, records
                    )
                    if process_snapshot != process_snapshot_initial:
                        raise ResourceError(
                            "process registry changed during finalization"
                        )
                    identities = [
                        (
                            path,
                            record,
                            _record_identity(record, resource_session_id, root),
                        )
                        for path, record in records
                    ]
                    mismatches = [
                        str(path)
                        for path, _record, identity in identities
                        if identity == "mismatch"
                    ]
                    if mismatches:
                        return {
                            "status": "fail",
                            "error_code": "process_identity_mismatch",
                            "signalled": [],
                            "mismatched_records": mismatches,
                        }
                    inputs_after_process_scan = _validated_finalization_inputs(
                        root,
                        claude_session_id=claude_session_id,
                        resource_session_id=resource_session_id,
                        trusted=trusted_current,
                    )
                    if inputs_after_process_scan["owner_records_sha256"] != inputs_initial[
                        "owner_records_sha256"
                    ]:
                        raise ResourceError(
                            "workflow identity records changed during process inspection"
                        )

                    finalized_created = False
                    trusted_transitioned = False
                    try:
                        validation = finalized_validation(
                            inputs_after_process_scan,
                            trusted_current,
                            (
                                process_snapshot
                                if trusted_current["state"] == "active"
                                or scratch.exists()
                                else None
                            ),
                        )
                        if finalized_path.exists():
                            finalized, finalized_bytes = _load_valid_finalized_record(
                                finalized_path, **validation
                            )
                        else:
                            if trusted_current["state"] == "authorized":
                                raise ResourceError(
                                    "trusted finalization authorization has no finalized record"
                                )
                            unsigned_finalized = {
                                "schema": SCHEMA_VERSION,
                                "trust_schema": TRUST_SCHEMA_VERSION,
                                "project_root_sha256": project_root_sha256,
                                "claude_session_id": claude_session_id,
                                "resource_session_id": resource_session_id,
                                "workflow_identity_sha256": validation[
                                    "workflow_identity_sha256"
                                ],
                                "actor_binding_sha256": validation[
                                    "actor_binding_sha256"
                                ],
                                "terminal_receipt_sha256": validation[
                                    "terminal_receipt_sha256"
                                ],
                                "owner_records_sha256": validation[
                                    "owner_records_sha256"
                                ],
                                "process_records_sha256": process_snapshot,
                                "trust_revision": validation["trust_revision"],
                                "authorized_at": _now_iso_z(),
                            }
                            finalized = _sign_trusted_record(
                                unsigned_finalized, trust_key
                            )
                            _create_or_verify(finalized_path, finalized, root)
                            finalized_created = True
                            finalized, finalized_bytes = _load_valid_finalized_record(
                                finalized_path, **validation
                            )

                        inputs_after_finalized = _validated_finalization_inputs(
                            root,
                            claude_session_id=claude_session_id,
                            resource_session_id=resource_session_id,
                            trusted=trusted_current,
                        )
                        if inputs_after_finalized["owner_records_sha256"] != inputs_initial[
                            "owner_records_sha256"
                        ]:
                            raise ResourceError(
                                "workflow identity records changed while publishing finalization"
                            )
                        finalized_sha256 = hashlib.sha256(finalized_bytes).hexdigest()
                        if trusted_current["state"] == "active":
                            authorized_payload = {
                                key: value
                                for key, value in trusted_current.items()
                                if key != "hmac_sha256"
                            }
                            authorized_payload.update(
                                {
                                    "state": "authorized",
                                    "finalization_authorization_sha256": finalized_sha256,
                                    "revision": int(trusted_current["revision"]) + 1,
                                }
                            )
                            trusted_transitioned = True
                            trusted_authorized = _write_trusted_record(
                                trust_path,
                                authorized_payload,
                                key=trust_key,
                                project_trust_root=project_trust_root,
                                project_root_sha256=project_root_sha256,
                                claude_session_id=claude_session_id,
                                directory_fd=trust_directory_fd,
                                trust_authority=trust_authority,
                            )
                        else:
                            trusted_authorized = trusted_current
                            if trusted_authorized.get(
                                "finalization_authorization_sha256"
                            ) != finalized_sha256:
                                raise ResourceError(
                                    "trusted finalized record digest mismatch"
                                )
                        inputs_authorized = _validated_finalization_inputs(
                            root,
                            claude_session_id=claude_session_id,
                            resource_session_id=resource_session_id,
                            trusted=trusted_authorized,
                        )
                        if inputs_authorized["owner_records_sha256"] != inputs_initial[
                            "owner_records_sha256"
                        ]:
                            raise ResourceError(
                                "workflow identity records changed at destructive boundary"
                            )
                    except Exception:
                        if trusted_transitioned:
                            _atomic_trusted_replace(
                                trust_path,
                                trusted_current,
                                project_trust_root,
                                directory_fd=trust_directory_fd,
                            )
                        if finalized_created:
                            _remove_prepared_finalized(finalized_path)
                        raise

                    def rollback_pre_destructive_authorization() -> None:
                        if trusted_transitioned:
                            _atomic_trusted_replace(
                                trust_path,
                                trusted_current,
                                project_trust_root,
                                directory_fd=trust_directory_fd,
                            )
                        if finalized_created:
                            _remove_prepared_finalized(finalized_path)

                    def validate_destructive_boundary() -> None:
                        _validate_trust_authority(
                            trust_authority,
                            project_directory_fd=trust_directory_fd,
                        )
                        durable_trust = _load_trusted_record(
                            trust_path,
                            key=trust_key,
                            project_root_sha256=project_root_sha256,
                            claude_session_id=claude_session_id,
                            directory_fd=trust_directory_fd,
                            trust_authority=trust_authority,
                        )
                        if _canonical_bytes(durable_trust) != _canonical_bytes(
                            trusted_authorized
                        ):
                            raise ResourceError(
                                "trusted authorization changed before cleanup"
                            )
                        durable_inputs = _validated_finalization_inputs(
                            root,
                            claude_session_id=claude_session_id,
                            resource_session_id=resource_session_id,
                            trusted=durable_trust,
                        )
                        if durable_inputs["owner_records_sha256"] != inputs_initial[
                            "owner_records_sha256"
                        ]:
                            raise ResourceError(
                                "workflow identity records changed before cleanup"
                            )
                        _record, durable_finalized_bytes = (
                            _load_valid_finalized_record(
                                finalized_path,
                                **finalized_validation(
                                    durable_inputs, durable_trust, None
                                ),
                            )
                        )
                        if hashlib.sha256(durable_finalized_bytes).hexdigest() != (
                            durable_trust["finalization_authorization_sha256"]
                        ):
                            raise ResourceError(
                                "finalized authorization changed before cleanup"
                            )

                    alive = [
                        record
                        for _path, record, identity in identities
                        if identity == "alive"
                    ]
                    signalled: list[dict] = []
                    try:
                        validate_destructive_boundary()
                    except Exception:
                        rollback_pre_destructive_authorization()
                        raise
                    for record in alive:
                        if (
                            _record_identity(record, resource_session_id, root)
                            != "alive"
                        ):
                            continue
                        try:
                            validate_destructive_boundary()
                        except Exception:
                            if not signalled:
                                rollback_pre_destructive_authorization()
                            raise
                        try:
                            os.killpg(int(record["pgid"]), signal.SIGTERM)
                            signalled.append(
                                {"pgid": record["pgid"], "signal": "TERM"}
                            )
                        except ProcessLookupError:
                            pass
                    remaining = _wait_for_exit(
                        alive, time.monotonic() + max(term_timeout, 0.0), root
                    )
                    for record in remaining:
                        if (
                            _record_identity(record, resource_session_id, root)
                            != "alive"
                        ):
                            continue
                        validate_destructive_boundary()
                        try:
                            os.killpg(int(record["pgid"]), signal.SIGKILL)
                            signalled.append(
                                {"pgid": record["pgid"], "signal": "KILL"}
                            )
                        except ProcessLookupError:
                            pass
                    remaining = _wait_for_exit(
                        remaining,
                        time.monotonic() + max(kill_timeout, 0.0),
                        root,
                    )
                    if remaining:
                        return {
                            "status": "fail",
                            "error_code": "process_exit_timeout",
                            "signalled": signalled,
                        }
                    try:
                        validate_destructive_boundary()
                    except Exception:
                        if not signalled:
                            rollback_pre_destructive_authorization()
                        raise
                    for path, _record in records:
                        try:
                            path.unlink()
                        except FileNotFoundError:
                            pass
                    if scratch.exists():
                        shutil.rmtree(scratch)
                    return {
                        "status": "pass",
                        "idempotent": (
                            trusted_initial["state"] == "authorized"
                            or not finalized_created
                        ),
                        "signalled": signalled,
                        "finalized": finalized,
                    }


__all__ = [
    "BINDING_FIELDS",
    "ResourceError",
    "SCHEMA_VERSION",
    "TERMINAL_VALUES",
    "TRUST_KEY_ENV",
    "TRUST_ROOT_ENV",
    "TRUST_SCHEMA_VERSION",
    "binding_digest",
    "classify_target",
    "exec_owned",
    "finalize",
    "load_actor_manifest",
    "managed_environment",
    "managed_temp_path",
    "normalize_binding",
    "owner_record_interface_digest",
    "provision",
    "publish_overnight_receipt",
    "publish_terminal_receipt",
    "publish_workflow_receipt",
    "resolve_current_resource_session",
    "scratch_path",
    "spawn_owned",
    "status",
]
