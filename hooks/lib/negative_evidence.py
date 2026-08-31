"""Authority-bound, bounded ``find -L`` negative-evidence receipts.

The scan root is never an authority source.  A parent-published immutable
admission, supplied with its externally computed digest, binds the only root,
repository, HEAD, context, spec, cycle contract, and ownership ledger that may
be scanned.  Every unsafe or incomplete state is represented as ``unknown``;
only a clean target/control result may be ``present`` or ``absent``.
"""

from __future__ import annotations

import base64
import collections
import datetime as _dt
import hashlib
import json
import os
import re
import selectors
import stat
import subprocess
import time
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

SCHEMA_NAME = "negative-evidence.v1"
SCHEMA_VERSION = 1
SCHEMA_DOCUMENT_SHA256 = (
    "afd5389e59fd523a75ba02868ce79e81eedf509d3bbc02926bc452e098636d32"
)
CONCLUSIVE_EXIT = 0
USAGE_OR_SCHEMA_EXIT = 2
INCONCLUSIVE_EXIT = 3
VERIFY_FAILURE_EXIT = 4
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


class EvidenceError(RuntimeError):
    """Base error for deterministic evidence failures."""


class SchemaContractError(EvidenceError):
    """The registered receipt schema/runtime is missing or inconsistent."""


class UsageContractError(EvidenceError):
    """A caller supplied a malformed, unbounded, or ambiguous request."""


class DuplicateKeyError(ValueError):
    """A JSON object contains a duplicate key."""


class _NonFiniteConstantError(ValueError):
    """A JSON document contains a non-standard numeric constant."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_constant(token: str) -> None:
    raise _NonFiniteConstantError(f"non-finite JSON constant: {token}")


def strict_json_loads(raw: bytes) -> Any:
    """Parse strict UTF-8 JSON, rejecting duplicate keys and non-finite values."""
    try:
        text = raw.decode("utf-8", errors="strict")
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        DuplicateKeyError,
        _NonFiniteConstantError,
    ) as exc:
        raise EvidenceError(f"invalid strict JSON: {exc}") from exc


def canonical_json_bytes(value: Any, *, newline: bool = False) -> bytes:
    """Return UTF-8, sorted-key, compact JSON bytes."""
    suffix = "\n" if newline else ""
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + suffix
    ).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_external_digest(value: str) -> bool:
    return bool(_HEX64.fullmatch(value or "")) and value != "0" * 64


def _utc_now() -> str:
    return (
        _dt.datetime.now(_dt.timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _read_nofollow(
    path: str,
    *,
    max_bytes: int = 64 * 1024 * 1024,
    required_mode: int | None = None,
    required_nlink: int | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Read one stable regular file descriptor without following its final link."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise EvidenceError(f"not a regular file: {path}")
        if required_mode is not None and stat.S_IMODE(before.st_mode) != required_mode:
            raise EvidenceError(
                f"wrong mode for {path}: {stat.S_IMODE(before.st_mode):04o} "
                f"!= {required_mode:04o}"
            )
        if required_nlink is not None and before.st_nlink != required_nlink:
            raise EvidenceError(
                f"wrong link count for {path}: {before.st_nlink} != {required_nlink}"
            )
        if before.st_size > max_bytes:
            raise EvidenceError(f"file exceeds read limit ({max_bytes} bytes): {path}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(1024 * 1024, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise EvidenceError(
                    f"file exceeds read limit ({max_bytes} bytes): {path}"
                )
        after = os.fstat(fd)
        stable_fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if any(getattr(before, name) != getattr(after, name) for name in stable_fields):
            raise EvidenceError(f"file changed during stable descriptor read: {path}")
        raw = b"".join(chunks)
        if len(raw) != before.st_size:
            raise EvidenceError(f"short descriptor read: {path}")
        return raw, {
            "bytes": len(raw),
            "mode": f"{stat.S_IMODE(before.st_mode):04o}",
            "nlink": before.st_nlink,
            "regular_file": True,
            "symlink": False,
        }
    finally:
        os.close(fd)


def _empty_file_binding(path: str, expected_sha256: str) -> dict[str, Any]:
    return {
        "path": path,
        "expected_sha256": expected_sha256,
        "observed_sha256": None,
        "bytes": None,
        "mode": None,
        "nlink": None,
        "regular_file": None,
        "symlink": None,
    }


def _load_bound_json(
    path: str,
    expected_sha256: str,
    *,
    required_mode: int | None = None,
    required_nlink: int | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any], str | None]:
    binding = _empty_file_binding(path, expected_sha256)
    if not Path(path).is_absolute():
        return None, binding, f"bound path is not absolute: {path}"
    if not _valid_external_digest(expected_sha256):
        return None, binding, f"invalid or placeholder external SHA-256 for {path}"
    try:
        raw, identity = _read_nofollow(
            path, required_mode=required_mode, required_nlink=required_nlink
        )
        observed = sha256_bytes(raw)
        binding.update(identity)
        binding["observed_sha256"] = observed
        if observed != expected_sha256:
            return None, binding, f"raw SHA-256 mismatch for {path}"
        parsed = strict_json_loads(raw)
        if not isinstance(parsed, dict):
            return None, binding, f"JSON root is not an object: {path}"
        return parsed, binding, None
    except (OSError, EvidenceError) as exc:
        try:
            binding["symlink"] = stat.S_ISLNK(os.lstat(path).st_mode)
        except OSError:
            pass
        return None, binding, f"cannot read bound JSON {path}: {exc}"


def _get(mapping: Any, *keys: str) -> Any:
    current = mapping
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _record_check(
    checks: dict[str, bool | None],
    errors: list[str],
    name: str,
    actual: Any,
    expected: Any,
) -> None:
    ok = actual == expected
    checks[name] = ok
    if not ok:
        errors.append(f"{name} mismatch: observed={actual!r} expected={expected!r}")


def _run_git(root: str, *args: str) -> tuple[str | None, str | None]:
    try:
        result = subprocess.run(
            ["git", "-C", root, *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"git {' '.join(args)} execution failed: {exc}"
    if result.returncode != 0 or result.stderr:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        return None, f"git {' '.join(args)} failed ({result.returncode}): {stderr}"
    try:
        return result.stdout.decode("utf-8", errors="strict").strip(), None
    except UnicodeDecodeError as exc:
        return None, f"git {' '.join(args)} emitted non-UTF-8 output: {exc}"


def _inside(root: str, path: str) -> bool:
    try:
        return os.path.commonpath([root, path]) == root
    except ValueError:
        return False


def _join_bound_source(root: str, rel: Any) -> str | None:
    if not isinstance(rel, str):
        return None
    try:
        normalized = normalize_relative(rel, allow_dot=False)
    except UsageContractError:
        return None
    return os.path.join(root, normalized)


def _verify_bound_source(
    root: str,
    item: Any,
    label: str,
    checks: dict[str, bool | None],
    errors: list[str],
) -> None:
    if not isinstance(item, dict):
        checks[label] = False
        errors.append(f"{label} binding missing")
        return
    path = _join_bound_source(root, item.get("path"))
    expected = item.get("sha256")
    if path is None or not _valid_external_digest(expected):
        checks[label] = False
        errors.append(f"{label} path/digest binding invalid")
        return
    try:
        raw, _identity = _read_nofollow(path)
        actual = sha256_bytes(raw)
    except (OSError, EvidenceError) as exc:
        checks[label] = False
        errors.append(f"{label} read failed: {exc}")
        return
    _record_check(checks, errors, label, actual, expected)


def _parse_expiry(value: Any) -> _dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(_dt.timezone.utc)


def validate_external_authority(
    *,
    contract_context: str,
    expected_context_sha256: str,
    authority_file: str,
    expected_authority_sha256: str,
    expected_authority_projection_sha256: str,
    scan_root: str,
) -> dict[str, Any]:
    """Validate the parent authority before any scan path is derived."""
    errors: list[str] = []
    checks: dict[str, bool | None] = {}
    authority: dict[str, Any] = {
        "contract_context": _empty_file_binding(
            contract_context, expected_context_sha256
        ),
        "authority_file": _empty_file_binding(
            authority_file, expected_authority_sha256
        ),
        "expected_authority_projection_sha256": expected_authority_projection_sha256,
        "observed_authority_projection_sha256": None,
        "authority_projection": {},
        "registered_root": None,
        "registered_root_realpath": None,
        "scan_root_realpath": (
            os.path.realpath(scan_root) if Path(scan_root).is_absolute() else None
        ),
        "repository": {
            "top_level": None,
            "git_common_dir_realpath": None,
            "remote_origin_url": None,
            "object_format": None,
            "head": None,
            "worktree_registration_count": None,
            "identity_canonical_sha256": None,
        },
        "checks": checks,
        "errors": errors,
    }

    if not _valid_external_digest(expected_authority_projection_sha256):
        checks["external_projection_digest_shape"] = False
        errors.append("invalid or placeholder external authority projection SHA-256")
    else:
        checks["external_projection_digest_shape"] = True

    context, context_binding, context_error = _load_bound_json(
        contract_context, expected_context_sha256
    )
    authority["contract_context"] = context_binding
    checks["context_raw_binding"] = context_error is None
    if context_error:
        errors.append(context_error)

    admission, admission_binding, admission_error = _load_bound_json(
        authority_file,
        expected_authority_sha256,
        required_mode=0o444,
        required_nlink=1,
    )
    authority["authority_file"] = admission_binding
    checks["admission_raw_immutable_binding"] = admission_error is None
    if admission_error:
        errors.append(admission_error)

    if admission is None:
        return authority

    projection = _get(admission, "root_authority", "authority_projection")
    if not isinstance(projection, dict):
        checks["authority_projection_present"] = False
        errors.append("admission root_authority.authority_projection is missing")
        return authority
    checks["authority_projection_present"] = True
    observed_projection_digest = sha256_bytes(canonical_json_bytes(projection))
    authority["authority_projection"] = projection
    authority["observed_authority_projection_sha256"] = observed_projection_digest
    _record_check(
        checks,
        errors,
        "authority_projection_digest",
        observed_projection_digest,
        expected_authority_projection_sha256,
    )
    _record_check(
        checks,
        errors,
        "admission_projection_digest_claim",
        _get(admission, "root_authority", "authority_projection_canonical_sha256"),
        expected_authority_projection_sha256,
    )
    _record_check(
        checks,
        errors,
        "authority_chain_projection_digest_claim",
        _get(admission, "authority_chain", "root_authority_projection_sha256"),
        expected_authority_projection_sha256,
    )

    declared_root = _get(projection, "registered_worktree", "declared_absolute")
    declared_real = _get(projection, "registered_worktree", "realpath")
    authority["registered_root"] = (
        declared_root if isinstance(declared_root, str) else None
    )
    authority["registered_root_realpath"] = (
        declared_real if isinstance(declared_real, str) else None
    )
    if not isinstance(declared_root, str) or not Path(declared_root).is_absolute():
        checks["registered_root_absolute"] = False
        errors.append("authority registered root is not an absolute path")
        return authority
    checks["registered_root_absolute"] = True
    _record_check(
        checks,
        errors,
        "registered_root_realpath_claim",
        os.path.realpath(declared_root),
        declared_real,
    )
    _record_check(
        checks,
        errors,
        "authority_chain_registered_root",
        _get(admission, "authority_chain", "registered_worktree_root"),
        declared_root,
    )
    _record_check(
        checks,
        errors,
        "authority_chain_registered_realpath",
        _get(admission, "authority_chain", "registered_worktree_realpath"),
        declared_real,
    )

    admission_rel = _get(projection, "admission_source", "path")
    expected_admission_abs = _join_bound_source(declared_root, admission_rel)
    _record_check(
        checks,
        errors,
        "authority_file_lexical_path",
        authority_file,
        expected_admission_abs,
    )
    context_rel = projection.get("contract_context_path")
    expected_context_abs = _join_bound_source(declared_root, context_rel)
    _record_check(
        checks,
        errors,
        "context_lexical_path",
        contract_context,
        expected_context_abs,
    )
    _record_check(
        checks,
        errors,
        "admission_context_raw_digest_claim",
        _get(admission, "authority_chain", "context", "sha256"),
        expected_context_sha256,
    )
    _record_check(
        checks,
        errors,
        "dispatch_context_raw_digest_claim",
        _get(
            admission,
            "root_authority",
            "external_dispatch_inputs",
            "expected_context_sha256",
        ),
        expected_context_sha256,
    )
    _record_check(
        checks,
        errors,
        "dispatch_context_absolute_claim",
        _get(
            admission,
            "root_authority",
            "external_dispatch_inputs",
            "contract_context_absolute",
        ),
        contract_context,
    )
    _record_check(
        checks,
        errors,
        "dispatch_authority_absolute_claim",
        _get(
            admission,
            "root_authority",
            "external_dispatch_inputs",
            "authority_file_absolute",
        ),
        authority_file,
    )
    _record_check(
        checks,
        errors,
        "dispatch_projection_digest_claim",
        _get(
            admission,
            "root_authority",
            "external_dispatch_inputs",
            "expected_authority_projection_sha256",
        ),
        expected_authority_projection_sha256,
    )

    if context is not None:
        _record_check(
            checks,
            errors,
            "context_authority_projection",
            _get(context, "root_authority_contract", "authority_projection"),
            projection,
        )
        _record_check(
            checks,
            errors,
            "context_authority_projection_digest_claim",
            _get(
                context,
                "root_authority_contract",
                "authority_projection_canonical_sha256",
            ),
            expected_authority_projection_sha256,
        )
        projection_keys = _get(context, "contract_projection", "keys")
        projection_claim = _get(
            context, "contract_projection", "canonical_compact_sha256"
        )
        if (
            isinstance(projection_keys, list)
            and projection_keys
            and all(isinstance(key, str) and key in context for key in projection_keys)
        ):
            semantic_projection = {key: context[key] for key in projection_keys}
            semantic_digest = sha256_bytes(canonical_json_bytes(semantic_projection))
            _record_check(
                checks,
                errors,
                "context_semantic_projection_digest",
                semantic_digest,
                projection_claim,
            )
            _record_check(
                checks,
                errors,
                "admission_context_semantic_projection_digest",
                _get(
                    admission, "authority_chain", "context_semantic_projection_sha256"
                ),
                semantic_digest,
            )
        else:
            checks["context_semantic_projection_digest"] = False
            errors.append(
                "context semantic projection key contract is missing or invalid"
            )

        ticket_binding = _get(context, "ticket_binding")
        admission_ticket = _get(admission, "authority_chain", "ticket")
        _record_check(
            checks,
            errors,
            "context_ticket_path_binding",
            _get(ticket_binding, "path"),
            _get(admission_ticket, "path"),
        )
        _record_check(
            checks,
            errors,
            "context_ticket_digest_binding",
            _get(ticket_binding, "sha256"),
            _get(admission_ticket, "sha256"),
        )

    _verify_bound_source(
        declared_root,
        _get(admission, "authority_chain", "ticket"),
        "ticket_raw_digest",
        checks,
        errors,
    )
    for label, chain_key in (
        ("spec_raw_digest", "spec"),
        ("cycle_contract_raw_digest", "cycle_contract"),
        ("ownership_ledger_raw_digest", "ownership_ledger"),
    ):
        _verify_bound_source(
            declared_root,
            _get(admission, "authority_chain", chain_key),
            label,
            checks,
            errors,
        )

    projection_spec = _get(projection, "spec")
    chain_spec = _get(admission, "authority_chain", "spec")
    _record_check(
        checks,
        errors,
        "projection_spec_path",
        _get(chain_spec, "path"),
        _get(projection_spec, "path"),
    )
    _record_check(
        checks,
        errors,
        "projection_spec_digest",
        _get(chain_spec, "sha256"),
        _get(projection_spec, "sha256"),
    )
    projection_cycle = _get(projection, "cycle")
    chain_cycle = _get(admission, "authority_chain", "cycle_contract")
    chain_ledger = _get(admission, "authority_chain", "ownership_ledger")
    _record_check(
        checks,
        errors,
        "projection_cycle_path",
        _get(chain_cycle, "path"),
        _get(projection_cycle, "contract_path"),
    )
    _record_check(
        checks,
        errors,
        "projection_cycle_digest",
        _get(chain_cycle, "sha256"),
        _get(projection_cycle, "contract_sha256"),
    )
    _record_check(
        checks,
        errors,
        "projection_ledger_path",
        _get(chain_ledger, "path"),
        _get(projection_cycle, "ownership_ledger_path"),
    )
    _record_check(
        checks,
        errors,
        "projection_ledger_digest",
        _get(chain_ledger, "sha256"),
        _get(projection_cycle, "ownership_ledger_sha256"),
    )

    # A lexical alias is deliberately invalid even if it resolves to the root.
    _record_check(
        checks, errors, "scan_root_lexical_equality", scan_root, declared_root
    )
    _record_check(
        checks,
        errors,
        "scan_root_realpath_equality",
        os.path.realpath(scan_root) if Path(scan_root).is_absolute() else None,
        declared_real,
    )
    checks["scan_root_not_symlink"] = not os.path.islink(scan_root)
    if not checks["scan_root_not_symlink"]:
        errors.append("scan root itself is a symbolic link")

    # Do not let Git metadata from any other cwd or root establish authority.
    if scan_root != declared_root or os.path.realpath(scan_root) != declared_real:
        return authority

    expected_repo = _get(projection, "repository", "identity")
    expected_head = _get(projection, "repository", "base_head")
    actual_repo = authority["repository"]
    for field, git_args in (
        ("top_level", ("rev-parse", "--show-toplevel")),
        ("git_common_dir_realpath", ("rev-parse", "--git-common-dir")),
        ("remote_origin_url", ("config", "--get", "remote.origin.url")),
        ("object_format", ("rev-parse", "--show-object-format")),
        ("head", ("rev-parse", "HEAD")),
    ):
        value, error = _run_git(declared_root, *git_args)
        if error:
            errors.append(error)
            checks[f"repository_{field}"] = False
            continue
        if field == "git_common_dir_realpath" and value is not None:
            if not os.path.isabs(value):
                value = os.path.join(declared_root, value)
            value = os.path.realpath(value)
        actual_repo[field] = value

    expected_common = _get(expected_repo, "git_common_dir_realpath")
    expected_remote = _get(expected_repo, "remote_origin_url")
    expected_format = _get(expected_repo, "object_format")
    _record_check(
        checks, errors, "repository_top_level", actual_repo["top_level"], declared_root
    )
    _record_check(
        checks,
        errors,
        "repository_git_common_dir",
        actual_repo["git_common_dir_realpath"],
        expected_common,
    )
    _record_check(
        checks,
        errors,
        "repository_remote_origin",
        actual_repo["remote_origin_url"],
        expected_remote,
    )
    _record_check(
        checks,
        errors,
        "repository_object_format",
        actual_repo["object_format"],
        expected_format,
    )
    _record_check(checks, errors, "repository_head", actual_repo["head"], expected_head)
    _record_check(
        checks,
        errors,
        "authority_chain_head",
        _get(admission, "authority_chain", "base_HEAD"),
        expected_head,
    )
    _record_check(
        checks,
        errors,
        "authority_chain_repository_identity",
        _get(admission, "authority_chain", "repository_identity"),
        expected_repo,
    )

    if isinstance(expected_repo, dict):
        expected_identity_digest = sha256_bytes(canonical_json_bytes(expected_repo))
        actual_repo["identity_canonical_sha256"] = (
            sha256_bytes(
                canonical_json_bytes(
                    {
                        "git_common_dir_realpath": actual_repo[
                            "git_common_dir_realpath"
                        ],
                        "object_format": actual_repo["object_format"],
                        "remote_origin_url": actual_repo["remote_origin_url"],
                    }
                )
            )
            if all(
                actual_repo[name] is not None
                for name in (
                    "git_common_dir_realpath",
                    "object_format",
                    "remote_origin_url",
                )
            )
            else None
        )
        _record_check(
            checks,
            errors,
            "projection_repository_identity_digest",
            _get(projection, "repository", "identity_canonical_sha256"),
            expected_identity_digest,
        )
        _record_check(
            checks,
            errors,
            "authority_chain_repository_identity_digest",
            _get(admission, "authority_chain", "repository_identity_canonical_sha256"),
            expected_identity_digest,
        )
        _record_check(
            checks,
            errors,
            "repository_identity_digest",
            actual_repo["identity_canonical_sha256"],
            expected_identity_digest,
        )

    worktree_output, worktree_error = _run_git(
        declared_root, "worktree", "list", "--porcelain"
    )
    if worktree_error:
        checks["unique_worktree_registration"] = False
        errors.append(worktree_error)
    else:
        worktrees = [
            line[len("worktree ") :]
            for line in (worktree_output or "").splitlines()
            if line.startswith("worktree ")
        ]
        count = sum(
            1
            for item in worktrees
            if item == declared_root and os.path.realpath(item) == declared_real
        )
        actual_repo["worktree_registration_count"] = count
        _record_check(checks, errors, "unique_worktree_registration", count, 1)
        _record_check(
            checks,
            errors,
            "authority_chain_unique_worktree_registration",
            _get(admission, "authority_chain", "unique_worktree_registration"),
            True,
        )

    expiry_value = _get(
        admission, "freshness_and_release", "expires_at"
    ) or admission.get("expires_at")
    expiry = _parse_expiry(expiry_value)
    active = expiry is not None and _dt.datetime.now(_dt.timezone.utc) < expiry
    checks["admission_unexpired"] = active
    if not active:
        errors.append("parent authority/admission is expired or has invalid expiry")
    _record_check(checks, errors, "admission_verdict", admission.get("verdict"), "PASS")
    _record_check(
        checks,
        errors,
        "admission_record_status",
        admission.get("record_status"),
        "PASS_ONE_FRESH_DEV_ACTOR_EXACT_12_IMPLEMENTATION_PATHS",
    )
    _record_check(
        checks,
        errors,
        "admission_dev_dispatch_allowed",
        _get(admission, "authorization", "Dev_dispatch_allowed"),
        True,
    )
    return authority


def normalize_relative(value: str, *, allow_dot: bool) -> str:
    """Return one exact portable root-relative lexical path or fail."""
    if not isinstance(value, str) or not value or "\x00" in value:
        raise UsageContractError("relative path is empty or contains NUL")
    if value.startswith("/"):
        raise UsageContractError(
            f"absolute path is forbidden in relative field: {value}"
        )
    pure = PurePosixPath(value)
    if any(part == ".." for part in pure.parts):
        raise UsageContractError(f"path escapes authority root: {value}")
    normalized = pure.as_posix()
    if normalized == "." and allow_dot:
        return normalized
    if normalized == "." or normalized != value or value.endswith("/"):
        raise UsageContractError(f"path is not canonical root-relative form: {value}")
    return normalized


def _relative_within(candidate: str, parent: str) -> bool:
    if parent == ".":
        return True
    return candidate == parent or candidate.startswith(parent + "/")


def _derive_scan_request(
    *,
    scan_root: str,
    scopes: Iterable[str],
    prunes: Iterable[str],
    target_kind: str,
    target: str,
    positive_control: str,
    timeout_ms: int,
    max_output_bytes: int,
    max_files: int,
    authority: dict[str, Any],
) -> tuple[dict[str, Any], list[str], bool]:
    errors: list[str] = []
    if target_kind not in {"exact-path", "basename"}:
        raise UsageContractError("target kind must be exact-path or basename")
    if not isinstance(timeout_ms, int) or not 1 <= timeout_ms <= 600_000:
        raise UsageContractError("timeout_ms must be in [1, 600000]")
    if (
        not isinstance(max_output_bytes, int)
        or not 1 <= max_output_bytes <= 1_073_741_824
    ):
        raise UsageContractError("max_output_bytes must be in [1, 1073741824]")
    if not isinstance(max_files, int) or not 1 <= max_files <= 10_000_000:
        raise UsageContractError("max_files must be in [1, 10000000]")

    normalized_scopes = [normalize_relative(item, allow_dot=True) for item in scopes]
    normalized_prunes = [normalize_relative(item, allow_dot=False) for item in prunes]
    if not normalized_scopes:
        raise UsageContractError("at least one explicit scope is required")
    if len(set(normalized_scopes)) != len(normalized_scopes):
        raise UsageContractError("duplicate scope arguments are forbidden")
    if len(set(normalized_prunes)) != len(normalized_prunes):
        raise UsageContractError("duplicate prune arguments are forbidden")

    control = normalize_relative(positive_control, allow_dot=False)
    if target_kind == "exact-path":
        normalized_target = normalize_relative(target, allow_dot=False)
    else:
        if (
            not isinstance(target, str)
            or not target
            or target in {".", ".."}
            or "/" in target
            or "\x00" in target
        ):
            raise UsageContractError(
                "basename target must be one nonempty literal basename"
            )
        normalized_target = target

    root = authority.get("registered_root")
    if not isinstance(root, str):
        # Keep a schema-valid request while authority errors force unknown.
        root = scan_root
    scope_paths = [
        root if item == "." else os.path.join(root, item) for item in normalized_scopes
    ]
    prune_paths = [os.path.join(root, item) for item in normalized_prunes]

    if authority.get("registered_root"):
        root_real = authority.get("registered_root_realpath")
        for label, rel, absolute in (
            [("scope", r, p) for r, p in zip(normalized_scopes, scope_paths)]
            + [("prune", r, p) for r, p in zip(normalized_prunes, prune_paths)]
            + [("control", control, os.path.join(root, control))]
            + (
                [("target", normalized_target, os.path.join(root, normalized_target))]
                if target_kind == "exact-path"
                else []
            )
        ):
            real = os.path.realpath(absolute)
            if not isinstance(root_real, str) or not _inside(root_real, real):
                errors.append(f"{label} path resolves outside authority root: {rel}")
        for rel, absolute in zip(normalized_scopes, scope_paths):
            if not os.path.exists(absolute):
                errors.append(f"scope does not exist: {rel}")
            elif not os.path.isdir(absolute):
                errors.append(f"scope is not a directory: {rel}")

    control_in_scope = any(
        _relative_within(control, scope) for scope in normalized_scopes
    )
    control_pruned = any(
        _relative_within(control, prune) for prune in normalized_prunes
    )
    if not control_in_scope:
        errors.append("positive control is outside every explicit scope")
    if control_pruned:
        errors.append("positive control is excluded by a prune")

    if target_kind == "exact-path":
        target_in_scope = any(
            _relative_within(normalized_target, scope) for scope in normalized_scopes
        )
        target_pruned = any(
            _relative_within(normalized_target, prune) for prune in normalized_prunes
        )
        target_excluded = not target_in_scope or target_pruned
    else:
        # A basename claim ranges over every included namespace.  If anything is
        # pruned, absence cannot prove the excluded namespaces do not contain it.
        target_excluded = bool(normalized_prunes)

    core = {
        "scan_root": scan_root,
        "scopes": normalized_scopes,
        "scope_paths": scope_paths,
        "prunes": normalized_prunes,
        "prune_paths": prune_paths,
        "target": {"kind": target_kind, "value": normalized_target},
        "positive_control": control,
        "timeout_ms": timeout_ms,
        "max_output_bytes": max_output_bytes,
        "max_files": max_files,
    }
    request = dict(core)
    request["scan_config_sha256"] = sha256_bytes(canonical_json_bytes(core))
    return request, errors, target_excluded


def _find_argv(request: dict[str, Any]) -> list[str]:
    argv = ["find", "-L", *request["scope_paths"]]
    prune_paths = request["prune_paths"]
    if prune_paths:
        argv.append("(")
        for index, path in enumerate(prune_paths):
            if index:
                argv.append("-o")
            argv.extend(["-path", path, "-o", "-path", path + "/*"])
        argv.extend([")", "-prune", "-o"])
    argv.extend(["-type", "f", "-print0"])
    return argv


def _terminate(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is None:
        proc.kill()


def _run_find(
    argv: list[str], timeout_ms: int, max_bytes: int, max_files: int
) -> dict[str, Any]:
    started_wall = _utc_now()
    started = time.monotonic()
    stdout = bytearray()
    stderr = bytearray()
    stdout_truncated = False
    stderr_truncated = False
    max_files_exceeded = False
    timed_out = False
    execution_error: str | None = None
    exit_code: int | None = None
    proc: subprocess.Popen[bytes] | None = None
    selector = selectors.DefaultSelector()
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
        )
        assert proc.stdout is not None and proc.stderr is not None
        selector.register(proc.stdout, selectors.EVENT_READ, ("stdout", stdout))
        selector.register(proc.stderr, selectors.EVENT_READ, ("stderr", stderr))
        deadline = started + timeout_ms / 1000.0
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                _terminate(proc)
                remaining = 0
            events = selector.select(min(max(remaining, 0), 0.05))
            if not events and proc.poll() is not None:
                # Pipes can still hold buffered bytes; loop until EOF events.
                events = selector.select(0)
            for key, _mask in events:
                stream_name, buffer = key.data
                try:
                    chunk = os.read(key.fd, 65536)
                except OSError as exc:
                    execution_error = f"{stream_name} read failed: {exc}"
                    selector.unregister(key.fileobj)
                    _terminate(proc)
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                remaining_capacity = max_bytes - len(buffer)
                if remaining_capacity > 0:
                    buffer.extend(chunk[:remaining_capacity])
                if len(chunk) > remaining_capacity:
                    if stream_name == "stdout":
                        stdout_truncated = True
                    else:
                        stderr_truncated = True
                    _terminate(proc)
                if stream_name == "stdout" and stdout.count(0) > max_files:
                    max_files_exceeded = True
                    _terminate(proc)
            if timed_out and proc.poll() is not None and not selector.get_map():
                break
        exit_code = proc.wait(timeout=1)
    except (OSError, subprocess.SubprocessError) as exc:
        execution_error = f"find execution failed: {exc}"
        if proc is not None:
            _terminate(proc)
            try:
                exit_code = proc.wait(timeout=1)
            except subprocess.SubprocessError:
                exit_code = None
    finally:
        selector.close()
    finished = time.monotonic()
    stdout_raw = bytes(stdout)
    stderr_raw = bytes(stderr)
    return {
        "argv": argv,
        "symlink_policy": "find_-L_follow",
        "started_at": started_wall,
        "finished_at": _utc_now(),
        "duration_ms": max(0, int(round((finished - started) * 1000))),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stdout": {
            "base64": base64.b64encode(stdout_raw).decode("ascii"),
            "sha256": sha256_bytes(stdout_raw),
            "bytes": len(stdout_raw),
        },
        "stderr": {
            "base64": base64.b64encode(stderr_raw).decode("ascii"),
            "sha256": sha256_bytes(stderr_raw),
            "bytes": len(stderr_raw),
        },
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "max_files_exceeded": max_files_exceeded,
        "decode_error": None,
        "execution_error": execution_error,
    }


def _decode_paths(raw: bytes, root: str) -> tuple[list[str], str | None]:
    if raw and not raw.endswith(b"\0"):
        return [], "find stdout is not terminated by NUL"
    chunks = raw[:-1].split(b"\0") if raw else []
    decoded: list[str] = []
    for chunk in chunks:
        try:
            absolute = chunk.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            return [], f"find stdout path is not UTF-8: {exc}"
        if not os.path.isabs(absolute):
            return [], f"find emitted non-absolute path: {absolute}"
        normalized = os.path.normpath(absolute)
        if not _inside(root, normalized):
            return [], f"find emitted path outside authority root: {absolute}"
        relative = os.path.relpath(normalized, root).replace(os.sep, "/")
        if relative == "." or relative.startswith("../"):
            return [], f"find emitted invalid root-relative path: {absolute}"
        decoded.append(relative)
    return decoded, None


def _manifest_entry(root: str, relative: str) -> dict[str, Any]:
    absolute = os.path.join(root, relative)
    real = os.path.realpath(absolute)
    root_real = os.path.realpath(root)
    if not _inside(root_real, real):
        raise EvidenceError(
            f"manifest path resolves outside authority root: {relative}"
        )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(absolute, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise EvidenceError(f"manifest path is not a regular file: {relative}")
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
        after = os.fstat(fd)
        stable = (
            before.st_dev == after.st_dev
            and before.st_ino == after.st_ino
            and before.st_size == after.st_size
            and before.st_mtime_ns == after.st_mtime_ns
            and before.st_ctime_ns == after.st_ctime_ns
        )
        if not stable or total != before.st_size:
            raise EvidenceError(f"manifest file changed during read: {relative}")
        return {"path": relative, "bytes": total, "sha256": digest.hexdigest()}
    finally:
        os.close(fd)


def _receipt_schema_modules():
    # This module lives in hooks/lib beside the real runtime/registry modules.
    try:
        from . import contract_runtime, schema_registry  # type: ignore
    except ImportError:
        import sys

        hooks_dir = str(Path(__file__).resolve().parent.parent)
        if hooks_dir not in sys.path:
            sys.path.insert(0, hooks_dir)
        from lib import contract_runtime, schema_registry  # type: ignore
    return contract_runtime, schema_registry


def validate_receipt_schema(receipt: dict[str, Any]) -> dict[str, Any]:
    """Validate using the repository's actual registry and contract runtime."""
    contract_runtime, schema_registry = _receipt_schema_modules()
    registry_path = Path(schema_registry.REGISTRY_PATH)
    try:
        registry_raw, _ = _read_nofollow(str(registry_path))
        registry = strict_json_loads(registry_raw)
    except (OSError, EvidenceError) as exc:
        raise SchemaContractError(f"schema registry read failed: {exc}") from exc
    mapping = _get(registry, "schemas", SCHEMA_NAME)
    if mapping != "negative-evidence.v1.json":
        raise SchemaContractError(
            "schema registry must map negative-evidence.v1 to negative-evidence.v1.json"
        )
    schema_path = Path(schema_registry.SCHEMAS_DIR) / mapping
    try:
        schema_raw, _ = _read_nofollow(str(schema_path))
        schema = strict_json_loads(schema_raw)
    except (OSError, EvidenceError) as exc:
        raise SchemaContractError(f"registered schema read failed: {exc}") from exc
    if sha256_bytes(schema_raw) != SCHEMA_DOCUMENT_SHA256:
        raise SchemaContractError(
            "registered negative-evidence schema raw digest drift"
        )
    if not isinstance(schema, dict):
        raise SchemaContractError(
            "registered negative-evidence schema is not an object"
        )
    if schema.get("$id") != SCHEMA_NAME:
        raise SchemaContractError("registered negative-evidence schema has wrong $id")
    if schema.get("$schema") != "http://json-schema.org/draft-07/schema#":
        raise SchemaContractError(
            "registered negative-evidence schema has wrong $schema"
        )
    # Force this exact schema into the real loader cache in case a caller had
    # imported the registry before a fixture/runtime change.
    schema_registry._CACHE.pop(SCHEMA_NAME, None)
    schema_registry._REGISTRY_LOADED = False
    loaded = schema_registry.get_schema(SCHEMA_NAME)
    if loaded != schema:
        raise SchemaContractError("real schema_registry resolved wrong file/version")
    result = contract_runtime.validate(receipt, SCHEMA_NAME)
    if (
        not isinstance(result, dict)
        or result.get("ok") is not True
        or result.get("severity") != "pass"
    ):
        errors = result.get("errors") if isinstance(result, dict) else [repr(result)]
        raise SchemaContractError(f"contract_runtime rejected receipt: {errors}")
    return result


def _empty_execution(argv: list[str]) -> dict[str, Any]:
    now = _utc_now()
    return {
        "argv": argv,
        "symlink_policy": "find_-L_follow",
        "started_at": now,
        "finished_at": now,
        "duration_ms": 0,
        "exit_code": None,
        "timed_out": False,
        "stdout": {"base64": "", "sha256": _EMPTY_SHA256, "bytes": 0},
        "stderr": {"base64": "", "sha256": _EMPTY_SHA256, "bytes": 0},
        "stdout_truncated": False,
        "stderr_truncated": False,
        "max_files_exceeded": False,
        "decode_error": None,
        "execution_error": None,
    }


def scan_evidence(
    *,
    contract_context: str,
    expected_context_sha256: str,
    authority_file: str,
    expected_authority_sha256: str,
    expected_authority_projection_sha256: str,
    scan_root: str,
    scopes: Iterable[str],
    prunes: Iterable[str] = (),
    target_kind: str,
    target: str,
    positive_control: str,
    timeout_ms: int,
    max_output_bytes: int,
    max_files: int,
) -> dict[str, Any]:
    """Run an authority-bound bounded scan and return a schema-valid receipt."""
    # Unknown/unregistered schema is infrastructure failure, never evidence of
    # absence.  Validate schema identity before doing authority or find work.
    _contract_runtime, schema_registry = _receipt_schema_modules()
    if schema_registry.get_schema(SCHEMA_NAME) is None:
        raise SchemaContractError(f"schema '{SCHEMA_NAME}' not registered")

    authority = validate_external_authority(
        contract_context=contract_context,
        expected_context_sha256=expected_context_sha256,
        authority_file=authority_file,
        expected_authority_sha256=expected_authority_sha256,
        expected_authority_projection_sha256=expected_authority_projection_sha256,
        scan_root=scan_root,
    )
    request, scope_errors, target_excluded = _derive_scan_request(
        scan_root=scan_root,
        scopes=scopes,
        prunes=prunes,
        target_kind=target_kind,
        target=target,
        positive_control=positive_control,
        timeout_ms=timeout_ms,
        max_output_bytes=max_output_bytes,
        max_files=max_files,
        authority=authority,
    )
    argv = _find_argv(request)
    preflight_errors = list(authority["errors"]) + scope_errors
    if preflight_errors:
        execution = _empty_execution(argv)
    else:
        execution = _run_find(argv, timeout_ms, max_output_bytes, max_files)

    root = authority.get("registered_root") or scan_root
    stdout_raw = base64.b64decode(execution["stdout"]["base64"], validate=True)
    paths: list[str] = []
    if not execution["stdout_truncated"] and not execution["max_files_exceeded"]:
        paths, decode_error = _decode_paths(stdout_raw, root)
        execution["decode_error"] = decode_error
    counts = collections.Counter(paths)
    duplicates = sorted(path for path, count in counts.items() if count > 1)
    target_value = request["target"]["value"]
    if request["target"]["kind"] == "exact-path":
        target_hits = [path for path in paths if path == target_value]
    else:
        target_hits = [
            path for path in paths if PurePosixPath(path).name == target_value
        ]
    control_hits = [path for path in paths if path == request["positive_control"]]

    manifest: list[dict[str, Any]] = []
    manifest_errors: list[str] = []
    if execution["decode_error"] is None:
        for relative in sorted(counts):
            try:
                manifest.append(_manifest_entry(root, relative))
            except (OSError, EvidenceError) as exc:
                manifest_errors.append(f"{relative}: {exc}")
    manifest_sha256 = sha256_bytes(canonical_json_bytes(manifest))

    reasons = list(preflight_errors)
    if execution["execution_error"]:
        reasons.append(execution["execution_error"])
    if execution["timed_out"]:
        reasons.append("find timed out")
    if execution["exit_code"] != 0:
        reasons.append(f"find exit code is {execution['exit_code']!r}, not 0")
    if execution["stderr"]["bytes"]:
        reasons.append("find emitted stderr")
    if execution["stdout_truncated"]:
        reasons.append("find stdout exceeded max_output_bytes")
    if execution["stderr_truncated"]:
        reasons.append("find stderr exceeded max_output_bytes")
    if execution["max_files_exceeded"]:
        reasons.append("find output exceeded max_files")
    if execution["decode_error"]:
        reasons.append(execution["decode_error"])
    if duplicates:
        reasons.append("find emitted duplicate logical paths")
    if len(target_hits) > 1:
        reasons.append("target matched more than once")
    if len(control_hits) != 1:
        reasons.append(
            f"positive control matched {len(control_hits)} times, expected 1"
        )
    if target_excluded:
        reasons.append("target is outside included scope or could be hidden by a prune")
    reasons.extend(manifest_errors)
    # Stable deterministic ordering and no duplicate messages.
    reasons = list(dict.fromkeys(reasons))

    if not reasons and len(target_hits) == 1:
        conclusion = "present"
    elif not reasons and len(target_hits) == 0:
        conclusion = "absent"
    else:
        conclusion = "unknown"

    receipt = {
        "$schema": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "receipt_type": "authority_bound_bounded_find",
        "created_at": _utc_now(),
        "authority": authority,
        "request": request,
        "execution": execution,
        "evidence": {
            "paths": paths,
            "file_count": len(paths),
            "duplicates": duplicates,
            "target_hits": target_hits,
            "control_hits": control_hits,
            "target_excluded": target_excluded,
            "manifest": manifest,
            "manifest_sha256": manifest_sha256,
            "manifest_errors": manifest_errors,
        },
        "conclusion": conclusion,
        "inconclusive_reasons": reasons,
        "schema_validation": {
            "schema_name": SCHEMA_NAME,
            "ok": True,
            "severity": "pass",
            "errors": [],
        },
    }
    validate_receipt_schema(receipt)
    return receipt


def _semantic_projection(receipt: dict[str, Any]) -> dict[str, Any]:
    """Fields that must remain equal across verification re-execution."""
    execution = receipt["execution"]
    return {
        "authority": receipt["authority"],
        "request": receipt["request"],
        "execution": {
            "argv": execution["argv"],
            "symlink_policy": execution["symlink_policy"],
            "exit_code": execution["exit_code"],
            "timed_out": execution["timed_out"],
            "stdout": execution["stdout"],
            "stderr": execution["stderr"],
            "stdout_truncated": execution["stdout_truncated"],
            "stderr_truncated": execution["stderr_truncated"],
            "max_files_exceeded": execution["max_files_exceeded"],
            "decode_error": execution["decode_error"],
            "execution_error": execution["execution_error"],
        },
        "evidence": receipt["evidence"],
        "conclusion": receipt["conclusion"],
        "inconclusive_reasons": receipt["inconclusive_reasons"],
    }


def verify_receipt(
    *,
    receipt_path: str,
    expected_receipt_sha256: str,
    contract_context: str,
    expected_context_sha256: str,
    authority_file: str,
    expected_authority_sha256: str,
    expected_authority_projection_sha256: str,
    scan_root: str,
    target_kind: str,
    target: str,
    expected_conclusion: str,
) -> dict[str, Any]:
    """Validate schema/digest/bindings, re-run scan, and reject any drift."""
    errors: list[str] = []
    if not Path(receipt_path).is_absolute():
        errors.append("receipt path must be absolute")
    if not _valid_external_digest(expected_receipt_sha256):
        errors.append("expected receipt SHA-256 is invalid or a placeholder")
    try:
        raw, _identity = _read_nofollow(
            receipt_path, required_mode=0o444, required_nlink=1
        )
    except (OSError, EvidenceError) as exc:
        return {
            "ok": False,
            "receipt_path": receipt_path,
            "expected_receipt_sha256": expected_receipt_sha256,
            "observed_receipt_sha256": None,
            "conclusion": None,
            "errors": errors + [f"receipt read failed: {exc}"],
        }
    observed = sha256_bytes(raw)
    if observed != expected_receipt_sha256:
        errors.append("receipt raw SHA-256 mismatch")
    try:
        receipt = strict_json_loads(raw)
    except EvidenceError as exc:
        return {
            "ok": False,
            "receipt_path": receipt_path,
            "expected_receipt_sha256": expected_receipt_sha256,
            "observed_receipt_sha256": observed,
            "conclusion": None,
            "errors": errors + [str(exc)],
        }
    if not isinstance(receipt, dict):
        errors.append("receipt JSON root is not an object")
        return {
            "ok": False,
            "receipt_path": receipt_path,
            "expected_receipt_sha256": expected_receipt_sha256,
            "observed_receipt_sha256": observed,
            "conclusion": None,
            "errors": errors,
        }

    # Consumer order is binding: real schema/runtime validation first, then
    # semantic/authority verification.  A schema failure is a hard failure.
    try:
        validate_receipt_schema(receipt)
    except SchemaContractError as exc:
        errors.append(str(exc))
        return {
            "ok": False,
            "receipt_path": receipt_path,
            "expected_receipt_sha256": expected_receipt_sha256,
            "observed_receipt_sha256": observed,
            "conclusion": receipt.get("conclusion"),
            "errors": errors,
        }

    expected_bindings = {
        "contract_context.path": contract_context,
        "contract_context.expected_sha256": expected_context_sha256,
        "authority_file.path": authority_file,
        "authority_file.expected_sha256": expected_authority_sha256,
        "expected_authority_projection_sha256": expected_authority_projection_sha256,
        "request.scan_root": scan_root,
        "request.target.kind": target_kind,
        "request.target.value": target,
        "conclusion": expected_conclusion,
    }
    observed_bindings = {
        "contract_context.path": _get(receipt, "authority", "contract_context", "path"),
        "contract_context.expected_sha256": _get(
            receipt, "authority", "contract_context", "expected_sha256"
        ),
        "authority_file.path": _get(receipt, "authority", "authority_file", "path"),
        "authority_file.expected_sha256": _get(
            receipt, "authority", "authority_file", "expected_sha256"
        ),
        "expected_authority_projection_sha256": _get(
            receipt, "authority", "expected_authority_projection_sha256"
        ),
        "request.scan_root": _get(receipt, "request", "scan_root"),
        "request.target.kind": _get(receipt, "request", "target", "kind"),
        "request.target.value": _get(receipt, "request", "target", "value"),
        "conclusion": receipt.get("conclusion"),
    }
    for key, expected in expected_bindings.items():
        if observed_bindings[key] != expected:
            errors.append(
                f"external receipt binding {key} mismatch: "
                f"observed={observed_bindings[key]!r} expected={expected!r}"
            )

    request = receipt["request"]
    config_core = {
        key: value for key, value in request.items() if key != "scan_config_sha256"
    }
    if sha256_bytes(canonical_json_bytes(config_core)) != request["scan_config_sha256"]:
        errors.append("receipt scan_config_sha256 mismatch")

    if errors:
        return {
            "ok": False,
            "receipt_path": receipt_path,
            "expected_receipt_sha256": expected_receipt_sha256,
            "observed_receipt_sha256": observed,
            "conclusion": receipt.get("conclusion"),
            "errors": errors,
        }

    try:
        fresh = scan_evidence(
            contract_context=contract_context,
            expected_context_sha256=expected_context_sha256,
            authority_file=authority_file,
            expected_authority_sha256=expected_authority_sha256,
            expected_authority_projection_sha256=expected_authority_projection_sha256,
            scan_root=scan_root,
            scopes=request["scopes"],
            prunes=request["prunes"],
            target_kind=target_kind,
            target=target,
            positive_control=request["positive_control"],
            timeout_ms=request["timeout_ms"],
            max_output_bytes=request["max_output_bytes"],
            max_files=request["max_files"],
        )
    except (EvidenceError, KeyError, TypeError) as exc:
        errors.append(f"verification re-scan failed: {exc}")
        fresh = None
    if fresh is not None and _semantic_projection(fresh) != _semantic_projection(
        receipt
    ):
        errors.append(
            "receipt semantic projection differs from fresh authority-bound scan"
        )

    return {
        "ok": not errors and receipt.get("conclusion") in {"present", "absent"},
        "receipt_path": receipt_path,
        "expected_receipt_sha256": expected_receipt_sha256,
        "observed_receipt_sha256": observed,
        "conclusion": receipt.get("conclusion"),
        "errors": errors,
    }


def publish_receipt(path: str, receipt: dict[str, Any]) -> None:
    """Publish canonical immutable receipt bytes without following links."""
    destination = Path(path)
    if not destination.is_absolute():
        raise UsageContractError("receipt output path must be absolute")
    raw = canonical_json_bytes(receipt, newline=True)
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    fd = os.open(str(destination), flags, 0o444)
    try:
        total = 0
        while total < len(raw):
            total += os.write(fd, raw[total:])
        os.fchmod(fd, 0o444)
        os.fsync(fd)
    except Exception:
        try:
            os.unlink(destination)
        except OSError:
            pass
        raise
    finally:
        os.close(fd)
    directory_fd = os.open(
        str(destination.parent), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    )
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
