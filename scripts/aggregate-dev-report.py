#!/usr/bin/env python3
"""Canonical aggregate writer for parallel-dev cycles.

Scans docs/dev/ for per-worker shard dev-reports matching a given task-id,
validates consistency across shards, and writes a canonical aggregate
docs/dev/dev-report-<task-id>.json.

Classification logic (NON_WORKER_LABELS, NON_WORKER_LABEL_RE, and all filename
patterns) mirrors hooks/pretool-aggregate-check.py exactly — do NOT diverge.

Shard scanning uses the bare YYYYMMDD-HHMMSS timestamp as the scan key for
the standard shard patterns (PER_WORKER_ROLE_FIRST_RE, PER_WORKER_TASK_FIRST_RE).
The active adapter's `dev-<timestamp>` IDs use explicit prefixed-worker patterns;
the canonical prefixed filename is excluded before legacy role-first matching.
Bare timestamp role-first/task-first behavior remains unchanged.

Usage:
    python3 scripts/aggregate-dev-report.py --task-id <TASK_ID>
    python3 scripts/aggregate-dev-report.py --task-id <TASK_ID> --dry-run

Exit codes:
    0   Success (action: aggregated | validated | skipped)
    1   Validation failure or I/O error (descriptive message on stderr)
    2   Bad arguments

stdout (on exit 0):
    JSON: {"status": "ok", "action": "aggregated"|"validated"|"skipped",
           "output_path": "<path>", "reason": "<human-readable>"}
stderr (on non-zero exit):
    Human-readable error describing the failure.
"""

import argparse
import copy
import errno
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Filename patterns — MUST mirror hooks/pretool-aggregate-check.py exactly.
# ---------------------------------------------------------------------------

# Active /dev adapter naming: dev-report-dev-<task-id>-<lane>.json.
PREFIXED_WORKER_RE = re.compile(
    r"^dev-report-(?P<task_id>dev-\d{8}-\d{6})-(?P<worker>[A-Za-z0-9][A-Za-z0-9.\-]*)\.json$"
)

# Active /dev canonical: dev-report-dev-<task-id>.json.
PREFIXED_CANONICAL_RE = re.compile(
    r"^dev-report-(?P<task_id>dev-\d{8}-\d{6})\.json$"
)

# Per-worker filename — role-first naming: dev-report-<role>-<task-id>.json
PER_WORKER_ROLE_FIRST_RE = re.compile(
    r"^dev-report-(?P<role>[A-Za-z0-9]+)-(?P<task_id>\d{8}-\d{6})\.json$"
)

# Per-worker filename — task-first naming: dev-report-<task-id>-<worker>.json
PER_WORKER_TASK_FIRST_RE = re.compile(
    r"^dev-report-(?P<task_id>\d{8}-\d{6})-(?P<worker>[A-Za-z0-9][A-Za-z0-9.\-]*)\.json$"
)

# Canonical singleton: dev-report-<task-id>.json
CANONICAL_RE = re.compile(
    r"^dev-report-(?P<task_id>\d{8}-\d{6})\.json$"
)

# NON_WORKER_LABELS — MUST mirror pretool-aggregate-check.py exactly.
NON_WORKER_LABELS = frozenset({
    "draft", "final", "fix", "continuation", "wip",
})

# NON_WORKER_LABEL_RE — MUST mirror pretool-aggregate-check.py exactly.
NON_WORKER_LABEL_RE = re.compile(
    r"^(?:iter|retry|attempt)\d*$",
    re.IGNORECASE,
)

# Explicit orchestrator-written shape declaration — MUST mirror
# scripts/resolve-dev-artifact-chain.py exactly.
DECLARATION_KEY = "artifact_chain_declaration"
DECLARATION_VERSION = 1
SHAPE_PARALLEL_DEV = "parallel_dev"
SHAPE_REQUIREMENT_FANOUT = "requirement_fanout"
DECLARED_SHAPES = (SHAPE_PARALLEL_DEV, SHAPE_REQUIREMENT_FANOUT)
WORKER_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]*$")

# The frozen baseline is a cycle-owned authority.  Shards only carry exact
# projections of it; they never select the expected value by being first, by
# being non-empty, or by agreeing with one another.
BASELINE_CONTRACT_VERSION = 1
BASELINE_AUTHORITY_FILENAME = "baseline-authority.json"
BASELINE_SNAPSHOT_FILENAME = "baseline-dirty.txt"
BASELINE_CAPTURE_PHASE = "pre_dev_fanout"
BASELINE_SERIALIZATION = "git_status_porcelain_v1_raw_text"
BASELINE_ORIGINS = frozenset({
    "legacy_migration_from_existing_frozen_artifact",
    "pre_dispatch_native",
})
BASELINE_REPORT_KEYS = frozenset({
    "baseline_contract",
    "baseline_head_sha",
    "baseline_dirty_snapshot",
    "baseline_dirty_snapshot_sha256",
})

# A report's path is never allowed to delegate its aggregation role to a loose
# boolean.  New reports carry this complete, versioned discriminator; legacy
# suffix reports are admitted only by the two closed profiles below.
DEV_REPORT_ROLE_KEY = "dev_report_role"
DEV_REPORT_ROLE_VERSION = 1
ROLE_ACTIVE_LANE_SHARD = "active_lane_shard"
ROLE_ITERATION_HISTORY = "iteration_history"
NEW_HISTORY_RE = re.compile(
    r"^dev-report-iter(?P<iteration>[1-9][0-9]*)-"
    r"(?P<parent>(?:dev-)?\d{8}-\d{6})-"
    r"(?P<lane>[A-Za-z0-9][A-Za-z0-9.\-]*)\.json$"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_project_root() -> Path:
    """Derive project root from CLAUDE_PROJECT_DIR env var or script location.

    Never hardcodes an absolute path.
    """
    env_root = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if env_root:
        return Path(env_root)
    # Fall back: this script lives at <project-root>/scripts/aggregate-dev-report.py
    return Path(__file__).resolve().parent.parent


def _resolve_dev_dir(project_root: Path) -> Path:
    return project_root / "docs" / "dev"


def _baseline_error(code: str, detail: str) -> str:
    """Return one stable, machine-distinguishable baseline diagnostic."""
    return f"[{code}] {detail}"


def _authority_locations(project_root: Path, task_id: str) -> tuple[str, Path, Path, str]:
    """Derive authority paths only from the normalized cycle id.

    No shard field participates in this calculation.  The returned relative
    snapshot path is the sole path value accepted inside the descriptor.
    """
    cycle_id = _bare_task_id(task_id)
    registry = project_root / ".claude" / "dev-registry" / cycle_id
    relative_snapshot = (
        Path(".claude") / "dev-registry" / cycle_id / BASELINE_SNAPSHOT_FILENAME
    ).as_posix()
    return (
        cycle_id,
        registry / BASELINE_AUTHORITY_FILENAME,
        registry / BASELINE_SNAPSHOT_FILENAME,
        relative_snapshot,
    )


def _stable_regular_read(path: Path) -> tuple[bytes | None, str | None]:
    """Read one non-symlink regular file and detect identity/content races."""
    try:
        path_before = os.lstat(path)
    except FileNotFoundError:
        return None, "missing"
    except OSError as exc:
        return None, f"io:{exc}"
    if stat.S_ISLNK(path_before.st_mode) or not stat.S_ISREG(path_before.st_mode):
        return None, "file_type"

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return None, "changed"
    except OSError as exc:
        # A swap to a symlink between lstat and open commonly surfaces as
        # ELOOP under O_NOFOLLOW and is a file-type failure, not a retry cue.
        if getattr(exc, "errno", None) == errno.ELOOP:
            return None, "file_type"
        return None, f"io:{exc}"

    try:
        opened_before = os.fstat(descriptor)
        if not stat.S_ISREG(opened_before.st_mode):
            return None, "file_type"
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        opened_after = os.fstat(descriptor)
    except OSError as exc:
        return None, f"io:{exc}"
    finally:
        os.close(descriptor)

    try:
        path_after = os.lstat(path)
    except OSError:
        return None, "changed"

    identity_before = (
        path_before.st_dev,
        path_before.st_ino,
        path_before.st_size,
        path_before.st_mtime_ns,
        path_before.st_ctime_ns,
    )
    identity_opened_before = (
        opened_before.st_dev,
        opened_before.st_ino,
        opened_before.st_size,
        opened_before.st_mtime_ns,
        opened_before.st_ctime_ns,
    )
    identity_opened_after = (
        opened_after.st_dev,
        opened_after.st_ino,
        opened_after.st_size,
        opened_after.st_mtime_ns,
        opened_after.st_ctime_ns,
    )
    identity_after = (
        path_after.st_dev,
        path_after.st_ino,
        path_after.st_size,
        path_after.st_mtime_ns,
        path_after.st_ctime_ns,
    )
    if not (
        identity_before
        == identity_opened_before
        == identity_opened_after
        == identity_after
    ):
        return None, "changed"
    return b"".join(chunks), None


def _snapshot_properties(raw: bytes) -> tuple[dict[str, object] | None, str | None]:
    """Recompute all snapshot properties from the same stable raw-byte read."""
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        return None, f"snapshot is not valid UTF-8: {exc}"
    properties: dict[str, object] = {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
        "line_count": len(raw.splitlines()),
        "encoding": "utf-8",
        "trailing_lf": raw.endswith(b"\n"),
        "state": "clean" if not raw else "dirty",
        "serialization": BASELINE_SERIALIZATION,
        "text": text,
    }
    return properties, None


def _load_baseline_authority(
    project_root: Path, task_id: str
) -> tuple[dict[str, object] | None, list[str]]:
    """Load and independently verify the task-derived frozen authority."""
    cycle_id, descriptor_path, snapshot_path, expected_relative = _authority_locations(
        project_root, task_id
    )
    descriptor_raw, descriptor_problem = _stable_regular_read(descriptor_path)
    if descriptor_problem is not None:
        code = (
            "BASELINE_AUTHORITY_MISSING"
            if descriptor_problem == "missing"
            else "BASELINE_FILE_TYPE_INVALID"
            if descriptor_problem == "file_type"
            else "BASELINE_CHANGED_DURING_READ"
            if descriptor_problem == "changed"
            else "BASELINE_AUTHORITY_SCHEMA_INVALID"
        )
        return None, [_baseline_error(code, f"authority descriptor {descriptor_path}: {descriptor_problem}")]
    assert descriptor_raw is not None
    try:
        descriptor = json.loads(descriptor_raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, [_baseline_error(
            "BASELINE_AUTHORITY_SCHEMA_INVALID",
            f"authority descriptor {descriptor_path} is not UTF-8 JSON: {exc}",
        )]
    if not isinstance(descriptor, dict):
        return None, [_baseline_error(
            "BASELINE_AUTHORITY_SCHEMA_INVALID",
            "authority descriptor root must be an object",
        )]

    errors: list[str] = []
    if descriptor.get("version") != BASELINE_CONTRACT_VERSION:
        errors.append(_baseline_error(
            "BASELINE_AUTHORITY_SCHEMA_INVALID",
            f"authority version must be {BASELINE_CONTRACT_VERSION}",
        ))
    if descriptor.get("cycle_id") != cycle_id:
        errors.append(_baseline_error(
            "BASELINE_CYCLE_MISMATCH",
            f"authority cycle_id {descriptor.get('cycle_id')!r} != task-derived {cycle_id!r}",
        ))
    if descriptor.get("capture_phase") != BASELINE_CAPTURE_PHASE:
        errors.append(_baseline_error(
            "BASELINE_AUTHORITY_SCHEMA_INVALID",
            f"capture_phase must be {BASELINE_CAPTURE_PHASE!r}",
        ))
    if descriptor.get("descriptor_origin") not in BASELINE_ORIGINS:
        errors.append(_baseline_error(
            "BASELINE_AUTHORITY_SCHEMA_INVALID",
            "descriptor_origin is missing or unsupported",
        ))
    if not isinstance(descriptor.get("descriptor_created_by_task"), str) or not descriptor.get(
        "descriptor_created_by_task"
    ):
        errors.append(_baseline_error(
            "BASELINE_AUTHORITY_SCHEMA_INVALID",
            "descriptor_created_by_task must be a non-empty string",
        ))
    if not isinstance(descriptor.get("head_sha"), str) or not descriptor.get("head_sha"):
        errors.append(_baseline_error(
            "BASELINE_HEAD_MISMATCH", "authority head_sha is missing or empty"
        ))

    dirty = descriptor.get("dirty_snapshot")
    if not isinstance(dirty, dict):
        errors.append(_baseline_error(
            "BASELINE_AUTHORITY_SCHEMA_INVALID",
            "authority dirty_snapshot must be an object",
        ))
        return None, errors
    if dirty.get("path") != expected_relative:
        errors.append(_baseline_error(
            "BASELINE_PATH_INVALID",
            f"snapshot path {dirty.get('path')!r} != task-derived {expected_relative!r}",
        ))

    snapshot_raw, snapshot_problem = _stable_regular_read(snapshot_path)
    if snapshot_problem is not None:
        code = (
            "BASELINE_AUTHORITY_MISSING"
            if snapshot_problem == "missing"
            else "BASELINE_FILE_TYPE_INVALID"
            if snapshot_problem == "file_type"
            else "BASELINE_CHANGED_DURING_READ"
            if snapshot_problem == "changed"
            else "BASELINE_AUTHORITY_SCHEMA_INVALID"
        )
        errors.append(_baseline_error(code, f"authority snapshot {snapshot_path}: {snapshot_problem}"))
        return None, errors
    assert snapshot_raw is not None
    properties, property_error = _snapshot_properties(snapshot_raw)
    if property_error is not None:
        errors.append(_baseline_error("BASELINE_SNAPSHOT_METADATA_MISMATCH", property_error))
        return None, errors
    assert properties is not None

    if dirty.get("sha256") != properties["sha256"]:
        errors.append(_baseline_error(
            "BASELINE_SNAPSHOT_DIGEST_MISMATCH",
            f"descriptor digest {dirty.get('sha256')!r} != recomputed {properties['sha256']!r}",
        ))
    metadata_fields = (
        "size_bytes", "line_count", "encoding", "trailing_lf", "state", "serialization"
    )
    metadata_mismatches = [
        field for field in metadata_fields if dirty.get(field) != properties[field]
    ]
    if metadata_mismatches:
        errors.append(_baseline_error(
            "BASELINE_SNAPSHOT_METADATA_MISMATCH",
            f"descriptor snapshot metadata differs for {metadata_mismatches}",
        ))
    if errors:
        return None, errors

    # The normalized contract remains descriptor-shaped and intentionally
    # includes honest descriptor provenance.  Same-user tamper resistance is
    # not claimed; the guarantee is only shard-independent selection.
    contract = copy.deepcopy(descriptor)
    return {
        "cycle_id": cycle_id,
        "descriptor_path": descriptor_path,
        "descriptor_raw": descriptor_raw,
        "snapshot_path": snapshot_path,
        "snapshot_raw": snapshot_raw,
        "snapshot_text": properties["text"],
        "contract": contract,
    }, []


def _baseline_projections(authority: dict[str, object]) -> dict[str, object]:
    contract = copy.deepcopy(authority["contract"])
    assert isinstance(contract, dict)
    dirty = contract["dirty_snapshot"]
    assert isinstance(dirty, dict)
    return {
        "baseline_contract": contract,
        "baseline_head_sha": contract["head_sha"],
        "baseline_dirty_snapshot": authority["snapshot_text"],
        "baseline_dirty_snapshot_sha256": dirty["sha256"],
    }


def _is_worker_for_task(filename: str, target_bare_tid: str, original_task_id: str) -> tuple[bool, str | None]:
    """Return (is_worker, label) for a filename scoped to the given task.

    target_bare_tid is the YYYYMMDD-HHMMSS portion of original_task_id.
    original_task_id may have a prefix or suffix (e.g. "dev-20260524-170335").

    Shard isolation rule:
    - When original_task_id == target_bare_tid (pure bare timestamp), match
      both role-first and task-first patterns using the bare timestamp.
    - When original_task_id has a suffix beyond the bare timestamp (e.g.
      "20260524-125300-push"), only match task-first shards whose worker
      label cannot be confused with unrelated tasks sharing the bare timestamp.
      Specifically we require the shard's task_id group to equal target_bare_tid
      AND the shard filename to NOT match any bare-timestamp-only canonical name
      that could belong to a different suffixed task.
    - When original_task_id has a prefix (e.g. "dev-20260524-170335"), the
      role-first pattern dev-report-<role>-<bare_tid>.json is still a valid
      shard naming for this task (role acts as prefix), so we allow it.
    """
    # Prefixed canonical must be excluded before legacy role-first matching,
    # where its `dev` prefix would otherwise look like a worker role.
    m_prefixed_canonical = PREFIXED_CANONICAL_RE.match(filename)
    if m_prefixed_canonical is not None:
        return False, None

    m_prefixed_worker = PREFIXED_WORKER_RE.match(filename)
    if m_prefixed_worker is not None:
        if m_prefixed_worker.group("task_id") != original_task_id:
            return False, None
        worker = m_prefixed_worker.group("worker")
        worker_lc = worker.lower()
        if worker_lc in NON_WORKER_LABELS or NON_WORKER_LABEL_RE.match(worker_lc):
            return False, None
        return True, worker

    # Bare canonical must be excluded from worker matches.
    if CANONICAL_RE.match(filename):
        return False, None

    # Role-first: dev-report-<role>-<task-id>.json
    m_role = PER_WORKER_ROLE_FIRST_RE.match(filename)
    if m_role is not None:
        if m_role.group("task_id") == target_bare_tid:
            return True, m_role.group("role")
        return False, None

    # Task-first: dev-report-<task-id>-<worker>.json
    m_task = PER_WORKER_TASK_FIRST_RE.match(filename)
    if m_task is None:
        return False, None
    if m_task.group("task_id") != target_bare_tid:
        return False, None
    worker = m_task.group("worker")
    worker_lc = worker.lower()
    if worker_lc in NON_WORKER_LABELS:
        return False, None
    if NON_WORKER_LABEL_RE.match(worker_lc):
        return False, None
    # Extra isolation when original_task_id has a suffix:
    # "20260524-125300-push" has suffix "-push"; shards of the plain
    # "20260524-125300" task (e.g. dev-report-20260524-125300-B.json) share
    # the bare timestamp but belong to a different task.  Reject them if the
    # original task_id has a suffix by requiring the worker not to be a
    # single uppercase letter (likely a different parallel task's worker label)
    # — this is a best-effort heuristic.  The recommended fix from codex is to
    # validate the loaded shard's task_id field in _validate_shards, which we do.
    return True, worker


def _scan_shards(dev_dir: Path, bare_tid: str, original_task_id: str) -> list[tuple[str, Path]]:
    """Return legacy/declaration-less active shards for ``original_task_id``.

    Valid versioned or closed-profile history is audited and excluded.  An
    invalid history blocks callers that use :func:`_discover_dev_reports`; this
    compatibility wrapper intentionally returns only the active set.
    """
    return _discover_dev_reports(dev_dir, original_task_id, None)["active"]


def _report_rel(path: Path, dev_dir: Path) -> str:
    """Return the stable repository-relative spelling used by report metadata."""
    return f"docs/dev/{path.name}"


def _classification_error(code: str, path: str, detail: str) -> dict[str, str]:
    return {"code": code, "path": path, "detail": detail}


def _new_history_parts(name: str, task_id: str) -> tuple[str, int] | None:
    match = NEW_HISTORY_RE.fullmatch(name)
    if match is None or match.group("parent") != task_id:
        return None
    return match.group("lane"), int(match.group("iteration"))


def _new_history_like(name: str, task_id: str) -> bool:
    marker = f"-{task_id}-"
    return (
        name.startswith("dev-report-iter")
        and marker in name
        and name.endswith(".json")
    )


def _legacy_history_like(name: str, task_id: str) -> bool:
    return (
        name.startswith(f"dev-report-{task_id}-")
        and "-iteration-" in name
        and name.endswith(".json")
    )


def _legacy_history_parts(
    name: str, task_id: str, lanes: list[str] | None = None
) -> list[tuple[str, int]]:
    """Return every lane/iteration parse allowed by the suffix spelling.

    With a declaration, matching every lane explicitly makes a compound lane
    collision observable instead of letting greedy regex behavior choose a
    role.  Declaration-less compatibility uses the final ``-iteration-``
    separator and therefore preserves the historical flat role-first rule.
    """
    prefix = f"dev-report-{task_id}-"
    suffix = ".json"
    if not name.startswith(prefix) or not name.endswith(suffix):
        return []
    body = name[len(prefix) : -len(suffix)]
    matches: list[tuple[str, int]] = []
    candidates = lanes or []
    if candidates:
        for lane in candidates:
            marker = f"{lane}-iteration-"
            if not body.startswith(marker):
                continue
            token = body[len(marker) :]
            if re.fullmatch(r"[1-9][0-9]*", token):
                matches.append((lane, int(token)))
        return matches
    if "-iteration-" not in body:
        return []
    lane, token = body.rsplit("-iteration-", 1)
    if WORKER_LABEL_RE.fullmatch(lane) and re.fullmatch(r"[1-9][0-9]*", token):
        matches.append((lane, int(token)))
    return matches


def _contains_exact_string(value: object, expected: str) -> bool:
    if isinstance(value, str):
        return value == expected
    if isinstance(value, list):
        return any(_contains_exact_string(item, expected) for item in value)
    if isinstance(value, dict):
        return any(_contains_exact_string(item, expected) for item in value.values())
    return False


def _expected_role(
    *, kind: str, parent_task_id: str, lane: str, iteration: int
) -> dict[str, object]:
    return {
        "version": DEV_REPORT_ROLE_VERSION,
        "kind": kind,
        "aggregation_eligible": kind == ROLE_ACTIVE_LANE_SHARD,
        "parent_task_id": parent_task_id,
        "lane": lane,
        "iteration": iteration,
        "canonical_shard_path": f"docs/dev/dev-report-{parent_task_id}-{lane}.json",
    }


def _validate_active_role(
    data: dict | None, task_id: str, lane: str, relative: str
) -> list[dict[str, str]]:
    if data is None or DEV_REPORT_ROLE_KEY not in data:
        return []  # Closed backward compatibility for existing active roots.
    role = data.get(DEV_REPORT_ROLE_KEY)
    expected = _expected_role(
        kind=ROLE_ACTIVE_LANE_SHARD,
        parent_task_id=task_id,
        lane=lane,
        iteration=0,
    )
    if role != expected:
        return [
            _classification_error(
                "AMBIGUOUS_DEV_REPORT_ROLE",
                relative,
                f"declared active root carries contradictory {DEV_REPORT_ROLE_KEY}: {role!r}",
            )
        ]
    identity = (data.get("request_id"), data.get("task_id"))
    expected_identity = (f"{task_id}-{lane}", f"{task_id}-{lane}")
    if identity != expected_identity or data.get("dev_report_path") != relative:
        return [
            _classification_error(
                "INVALID_ACTIVE_SHARD_IDENTITY",
                relative,
                f"identity/self path is {identity!r}/{data.get('dev_report_path')!r}; "
                f"expected {expected_identity!r}/{relative!r}",
            )
        ]
    return []


def _history_lineage_error(
    root_data: dict | None, root_path: Path | None, history_relative: str
) -> dict[str, str] | None:
    if root_path is None or root_data is None:
        return _classification_error(
            "HISTORY_WITHOUT_ACTIVE_SHARD",
            history_relative,
            "history has no readable exact active root",
        )
    if not _contains_exact_string(root_data, history_relative):
        return _classification_error(
            "HISTORY_WITHOUT_ACTIVE_SHARD",
            history_relative,
            f"active root {_report_rel(root_path, root_path.parent)} does not reference this exact history path",
        )
    return None


def _validate_new_history(
    data: dict | None,
    task_id: str,
    lane: str,
    iteration: int,
    relative: str,
    root_path: Path | None,
    root_data: dict | None,
) -> tuple[list[dict[str, str]], dict[str, object] | None]:
    if data is None:
        return [
            _classification_error(
                "INVALID_HISTORY_METADATA", relative, "history JSON is malformed or unreadable"
            )
        ], None
    expected_role = _expected_role(
        kind=ROLE_ITERATION_HISTORY,
        parent_task_id=task_id,
        lane=lane,
        iteration=iteration,
    )
    identity = (data.get("request_id"), data.get("task_id"))
    expected_identity = (f"{task_id}-{lane}", f"{task_id}-{lane}")
    if (
        data.get(DEV_REPORT_ROLE_KEY) != expected_role
        or identity != expected_identity
        or data.get("dev_report_path") != relative
    ):
        return [
            _classification_error(
                "INVALID_HISTORY_METADATA",
                relative,
                "filename, identity, self path, and version-1 iteration_history metadata must agree exactly",
            )
        ], None
    lineage = _history_lineage_error(root_data, root_path, relative)
    if lineage is not None:
        return [lineage], None
    return [], {
        "path": relative,
        "lane": lane,
        "iteration": iteration,
        "profile": "versioned_iteration_history",
    }


def _validate_legacy_history(
    data: dict | None,
    task_id: str,
    lane: str,
    iteration: int,
    relative: str,
    root_path: Path | None,
    root_data: dict | None,
) -> tuple[list[dict[str, str]], dict[str, object] | None]:
    if data is None:
        return [
            _classification_error(
                "INVALID_HISTORY_METADATA", relative, "legacy history JSON is malformed or unreadable"
            )
        ], None
    lane_identity = f"{task_id}-{lane}"
    d_identity = f"{lane_identity}-iteration-{iteration}"
    common = data.get("lane") == lane and data.get("requirement_id") == lane
    d_profile = (
        common
        and data.get("request_id") == d_identity
        and data.get("task_id") == d_identity
        and data.get("parent_task_id") == lane_identity
    )
    e_profile = (
        common
        and data.get("request_id") == lane_identity
        and data.get("task_id") == lane_identity
        and data.get("parent_task_id") == task_id
        and type(data.get("iteration")) is int
        and data.get("iteration") == iteration
        and data.get("dev_report_path") == relative
        and data.get("main_dev_report_path")
        == f"docs/dev/dev-report-{task_id}-{lane}.json"
    )
    if d_profile == e_profile:  # neither or both are invalid/ambiguous.
        return [
            _classification_error(
                "INVALID_HISTORY_METADATA",
                relative,
                "legacy suffix report does not satisfy exactly one closed D/E compatibility profile",
            )
        ], None
    lineage = _history_lineage_error(root_data, root_path, relative)
    if lineage is not None:
        return [lineage], None
    return [], {
        "path": relative,
        "lane": lane,
        "iteration": iteration,
        "profile": (
            "legacy_suffix_identity_profile"
            if d_profile
            else "legacy_lane_identity_with_iteration_field_profile"
        ),
    }


def _load_candidate(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _looks_correlated(name: str, task_id: str, bare_tid: str) -> bool:
    if name == f"dev-report-{task_id}.json":
        return True
    if name.startswith(f"dev-report-{task_id}-") and name.endswith(".json"):
        return True
    new = NEW_HISTORY_RE.fullmatch(name)
    if new is not None and new.group("parent") == task_id:
        return True
    if _new_history_like(name, task_id):
        return True
    role = PER_WORKER_ROLE_FIRST_RE.fullmatch(name)
    return bool(role is not None and role.group("task_id") == bare_tid)


def _discover_dev_reports(
    dev_dir: Path, task_id: str, declaration: dict | None
) -> dict[str, object]:
    """Classify every top-level report structurally correlated to ``task_id``.

    ``requirement_fanout`` is declaration-driven: only the exact root for each
    declared lane may vote.  Other shapes retain legacy filename discovery,
    except that complete versioned/closed-profile histories are audited and do
    not vote.  Every ambiguity is returned as a deterministic path-bearing
    error; callers must fail rather than silently drop it.
    """
    bare_tid = _bare_task_id(task_id)
    shape = declaration.get("shape") if isinstance(declaration, dict) else None
    declared_lanes = (
        list(declaration.get("declared_lanes") or [])
        if shape == SHAPE_REQUIREMENT_FANOUT
        else None
    )
    result: dict[str, object] = {"active": [], "history": [], "errors": []}
    if not dev_dir.is_dir():
        if declared_lanes is not None:
            result["errors"] = [
                _classification_error(
                    "MISSING_DECLARED_SHARD",
                    f"docs/dev/dev-report-{task_id}-{lane}.json",
                    f"declared lane {lane!r} has no exact active root",
                )
                for lane in declared_lanes
            ]
        return result
    try:
        children = sorted(dev_dir.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        result["errors"] = [
            _classification_error(
                "UNREADABLE_DEV_DIRECTORY", "docs/dev", str(exc)
            )
        ]
        return result

    entries: dict[str, tuple[Path, dict | None]] = {}
    seen_files: dict[tuple[int, int], str] = {}
    errors: list[dict[str, str]] = []
    for child in children:
        if not _looks_correlated(child.name, task_id, bare_tid):
            continue
        relative = _report_rel(child, dev_dir)
        try:
            mode = child.lstat().st_mode
        except OSError as exc:
            errors.append(
                _classification_error(
                    "DUPLICATE_OR_UNSAFE_DEV_REPORT", relative, str(exc)
                )
            )
            continue
        if child.is_symlink() or not stat.S_ISREG(mode):
            errors.append(
                _classification_error(
                    "DUPLICATE_OR_UNSAFE_DEV_REPORT",
                    relative,
                    "task-correlated candidate must be one non-symlink regular file",
                )
            )
            if declared_lanes and child.name in {
                f"dev-report-{task_id}-{lane}.json" for lane in declared_lanes
            }:
                errors.append(
                    _classification_error(
                        "DUPLICATE_ACTIVE_SHARD", relative, "declared root is unsafe or aliased"
                    )
                )
            continue
        inode = (child.stat().st_dev, child.stat().st_ino)
        if inode in seen_files:
            errors.append(
                _classification_error(
                    "DUPLICATE_OR_UNSAFE_DEV_REPORT",
                    relative,
                    f"aliases task-correlated candidate {seen_files[inode]}",
                )
            )
        else:
            seen_files[inode] = relative
        entries[child.name] = (child, _load_candidate(child))

    canonical_name = f"dev-report-{task_id}.json"
    active: list[tuple[str, Path]] = []
    histories: list[dict[str, object]] = []
    consumed = {canonical_name}

    if declared_lanes is not None:
        root_data: dict[str, tuple[Path | None, dict | None]] = {}
        for lane in declared_lanes:
            name = f"dev-report-{task_id}-{lane}.json"
            entry = entries.get(name)
            if entry is None:
                errors.append(
                    _classification_error(
                        "MISSING_DECLARED_SHARD",
                        f"docs/dev/{name}",
                        f"declared lane {lane!r} has no exact active root",
                    )
                )
                root_data[lane] = (None, None)
                continue
            path, data = entry
            active.append((lane, path))
            root_data[lane] = (path, data)
            consumed.add(name)
            other_history_roles = [
                match
                for match in _legacy_history_parts(name, task_id, declared_lanes)
                if match[0] != lane
            ]
            if other_history_roles:
                errors.append(
                    _classification_error(
                        "AMBIGUOUS_DEV_REPORT_ROLE",
                        _report_rel(path, dev_dir),
                        "exact declared root also parses as another declared lane's suffix history",
                    )
                )
            errors.extend(_validate_active_role(data, task_id, lane, _report_rel(path, dev_dir)))
            identity = (
                (data.get("request_id"), data.get("task_id")) if data is not None else None
            )
            expected_identity = (f"{task_id}-{lane}", f"{task_id}-{lane}")
            if data is not None and identity != expected_identity:
                errors.append(
                    _classification_error(
                        "INVALID_ACTIVE_SHARD_IDENTITY",
                        _report_rel(path, dev_dir),
                        f"identity is {identity!r}; expected {expected_identity!r}",
                    )
                )

        for name, (path, data) in entries.items():
            if name in consumed:
                continue
            relative = _report_rel(path, dev_dir)
            new_parts = _new_history_parts(name, task_id)
            legacy_parts = _legacy_history_parts(name, task_id, declared_lanes)
            generic_legacy_parts = _legacy_history_parts(name, task_id)
            if new_parts is not None:
                lane, iteration = new_parts
                if lane not in root_data:
                    errors.append(
                        _classification_error(
                            "UNDECLARED_SHARD", relative, f"history lane {lane!r} is not declared"
                        )
                    )
                    continue
                root_path, root = root_data[lane]
                found_errors, history = _validate_new_history(
                    data, task_id, lane, iteration, relative, root_path, root
                )
                errors.extend(found_errors)
                if history is not None:
                    histories.append(history)
                continue
            if _new_history_like(name, task_id):
                errors.append(
                    _classification_error(
                        "INVALID_HISTORY_METADATA",
                        relative,
                        "new history filename has an invalid iteration, parent, or lane token",
                    )
                )
                continue
            if legacy_parts:
                if len(legacy_parts) != 1:
                    errors.append(
                        _classification_error(
                            "AMBIGUOUS_DEV_REPORT_ROLE", relative, "multiple declared lanes parse this history path"
                        )
                    )
                    continue
                lane, iteration = legacy_parts[0]
                root_path, root = root_data[lane]
                found_errors, history = _validate_legacy_history(
                    data, task_id, lane, iteration, relative, root_path, root
                )
                errors.extend(found_errors)
                if history is not None:
                    histories.append(history)
                continue
            if generic_legacy_parts:
                errors.append(
                    _classification_error(
                        "UNDECLARED_SHARD",
                        relative,
                        f"history lane {generic_legacy_parts[0][0]!r} is not declared",
                    )
                )
                continue
            if _legacy_history_like(name, task_id):
                errors.append(
                    _classification_error(
                        "INVALID_HISTORY_METADATA",
                        relative,
                        "legacy history filename has an invalid lane or positive iteration token",
                    )
                )
                continue
            if name != canonical_name:
                errors.append(
                    _classification_error(
                        "UNDECLARED_SHARD",
                        relative,
                        "task-correlated root is absent from declared_lanes; role metadata cannot hide it",
                    )
                )
    else:
        history_names: set[str] = set()
        for name, (path, data) in entries.items():
            relative = _report_rel(path, dev_dir)
            parts = _new_history_parts(name, task_id)
            legacy = _legacy_history_parts(name, task_id)
            if parts is None and not legacy and not (
                _new_history_like(name, task_id) or _legacy_history_like(name, task_id)
            ):
                continue
            if parts is None and not legacy:
                errors.append(
                    _classification_error(
                        "INVALID_HISTORY_METADATA",
                        relative,
                        "history filename has an invalid lane or positive iteration token",
                    )
                )
                history_names.add(name)
                continue
            lane, iteration = parts if parts is not None else legacy[0]
            root_name = f"dev-report-{task_id}-{lane}.json"
            root_entry = entries.get(root_name)
            root_path, root = root_entry if root_entry is not None else (None, None)
            if parts is not None:
                found_errors, history = _validate_new_history(
                    data, task_id, lane, iteration, relative, root_path, root
                )
            else:
                found_errors, history = _validate_legacy_history(
                    data, task_id, lane, iteration, relative, root_path, root
                )
            errors.extend(found_errors)
            history_names.add(name)
            if history is not None:
                histories.append(history)
        for name, (path, data) in entries.items():
            if name == canonical_name or name in history_names:
                continue
            is_worker, label = _is_worker_for_task(name, bare_tid, task_id)
            if is_worker and label is not None:
                active.append((label, path))
                errors.extend(
                    _validate_active_role(data, task_id, label, _report_rel(path, dev_dir))
                )
        active.sort(key=lambda item: item[0])

    # Stable, duplicate-free diagnostics are part of the public failure contract.
    unique_errors = {
        (item["path"], item["code"], item["detail"]): item for item in errors
    }
    result["active"] = active
    result["history"] = sorted(histories, key=lambda item: str(item["path"]))
    result["errors"] = [
        unique_errors[key] for key in sorted(unique_errors, key=lambda item: (item[0], item[1], item[2]))
    ]
    return result


def _load_shard(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"aggregate-dev-report: cannot load shard {path}: {exc}\n")
        return None


def _validate_shards(
    shards: list[tuple[str, dict]],
    task_id: str,
    authority: dict[str, object] | None = None,
) -> list[str]:
    """Return list of validation error strings (empty = all pass).

    Baseline expectations come only from ``authority``.  Agreement among
    shards has no evidentiary value and is never used as a fallback.
    """
    errors = []
    expected = _baseline_projections(authority) if authority is not None else None
    m_target = re.search(r"(\d{8}-\d{6})", task_id)
    normalized_target = m_target.group(1) if m_target else task_id
    labels = [label for label, _ in shards]
    duplicate_labels = sorted({label for label in labels if labels.count(label) > 1})
    if duplicate_labels:
        errors.append(f"duplicate worker labels are ambiguous: {duplicate_labels}")

    for label, data in shards:
        # Require non-empty task_id or request_id.
        shard_task_id = (data.get("task_id") or data.get("request_id") or "").strip()
        if not shard_task_id:
            errors.append(
                f"shard '{label}': missing or empty task_id / request_id field"
            )
        else:
            m = re.search(r"(\d{8}-\d{6})", shard_task_id)
            normalized_shard = m.group(1) if m else shard_task_id
            if normalized_shard != normalized_target:
                errors.append(
                    f"shard '{label}': task_id {shard_task_id!r} does not match target {task_id!r}"
                )

        # Check dev.status == completed
        dev = data.get("dev", {})
        status = dev.get("status") if isinstance(dev, dict) else None
        if status != "completed":
            errors.append(_baseline_error(
                "SHARD_STATUS_NOT_COMPLETED",
                f"shard '{label}': dev.status is {status!r}, expected 'completed'",
            ))

        contract = data.get("baseline_contract")
        schema_fields = (
            "baseline_contract",
            "baseline_head_sha",
            "baseline_dirty_snapshot",
            "baseline_dirty_snapshot_sha256",
        )
        missing = [field for field in schema_fields if field not in data]
        nulls = [field for field in schema_fields if data.get(field) is None]
        if missing or nulls or not isinstance(contract, dict):
            errors.append(_baseline_error(
                "BASELINE_SHARD_SCHEMA_INVALID",
                f"shard '{label}': missing={missing}, null={nulls}, "
                f"baseline_contract_type={type(contract).__name__}",
            ))
            continue
        if not isinstance(data.get("baseline_head_sha"), str) or not isinstance(
            data.get("baseline_dirty_snapshot"), str
        ) or not isinstance(data.get("baseline_dirty_snapshot_sha256"), str):
            errors.append(_baseline_error(
                "BASELINE_SHARD_SCHEMA_INVALID",
                f"shard '{label}': compatibility projections must all be strings",
            ))
            continue
        if expected is None:
            # The independently loaded authority error is emitted by main.
            # Never infer an expected value from this otherwise well-shaped shard.
            continue

        mismatched_fields = [
            field for field, expected_value in expected.items()
            if data.get(field) != expected_value
        ]
        if mismatched_fields:
            current_observation = data.get("current_dirty_observation")
            current_values: list[object] = []
            if isinstance(current_observation, dict):
                current_values.extend(
                    current_observation.get(key)
                    for key in ("snapshot", "raw_text", "value")
                    if key in current_observation
                )
            elif current_observation is not None:
                current_values.append(current_observation)
            if (
                "baseline_dirty_snapshot" in mismatched_fields
                and data.get("baseline_dirty_snapshot") in current_values
            ):
                code = "BASELINE_CURRENT_TREE_SUBSTITUTION"
            elif mismatched_fields == ["baseline_head_sha"]:
                code = "BASELINE_HEAD_MISMATCH"
            else:
                code = "BASELINE_SHARD_MISMATCH"
            errors.append(_baseline_error(
                code,
                f"shard '{label}': authority mismatch at {mismatched_fields}",
            ))

    return errors


def _union_list(shards: list[tuple[str, dict]], key_path: list[str]) -> list:
    """Return ordered union of list-typed fields across shards (no dedup by value)."""
    seen_json = set()
    result = []
    for _, data in shards:
        obj = data
        for key in key_path:
            if not isinstance(obj, dict):
                obj = None
                break
            obj = obj.get(key)
        if not isinstance(obj, list):
            continue
        for item in obj:
            item_json = json.dumps(item, sort_keys=True)
            if item_json not in seen_json:
                seen_json.add(item_json)
                result.append(item)
    return result


def _canonical_projection(document: dict) -> dict:
    """Select deterministic aggregate fields; timestamp is intentionally excluded."""
    keys = (
        "request_id",
        "task_id",
        "baseline_contract",
        "baseline_head_sha",
        "baseline_dirty_snapshot",
        "baseline_dirty_snapshot_sha256",
        "dev_report_path",
        "parallel_workers",
        DECLARATION_KEY,
        "dev",
        "blocking_issues",
        "recommendations",
    )
    return {key: document.get(key) for key in keys}


def _declaration_from_arguments(shape: str | None, lanes_argument: str | None) -> tuple[dict | None, str | None]:
    """Build the shape declaration from CLI arguments.

    Returns ``(declaration, error)``; exactly one of the two is None.  A missing
    ``--shape`` with a supplied roster is rejected rather than silently ignored.
    """
    if shape is None:
        if lanes_argument is not None:
            return None, "--declared-lanes requires --shape"
        return None, None
    lanes = [item.strip() for item in (lanes_argument or "").split(",") if item.strip()]
    if shape == SHAPE_PARALLEL_DEV:
        if lanes:
            return None, (
                f"--declared-lanes must be empty for --shape {SHAPE_PARALLEL_DEV}; "
                f"the parallel-dev shape has no lanes (got {lanes})"
            )
    else:
        if len(lanes) < 2:
            return None, (
                f"--shape {SHAPE_REQUIREMENT_FANOUT} requires --declared-lanes "
                f"naming at least two lanes (got {lanes})"
            )
        if len(set(lanes)) != len(lanes):
            return None, f"--declared-lanes contains duplicate lane labels: {lanes}"
        invalid = [item for item in lanes if not WORKER_LABEL_RE.match(item)]
        if invalid:
            return None, f"--declared-lanes contains invalid worker labels: {invalid}"
    return {
        "version": DECLARATION_VERSION,
        "shape": shape,
        "declared_lanes": lanes,
    }, None


def _atomic_write_json(path: Path, document: dict) -> None:
    """Durably replace path without deleting a stale canonical first."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _write_temp_bytes(path: Path, payload: bytes) -> Path:
    """Write and fsync a sibling temporary file without publishing it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return temporary_path


def _replace_path(source: Path, destination: Path) -> None:
    """Indirection used by migration rollback tests."""
    os.replace(source, destination)


def _write_migration_ledger(handle, payload: bytes) -> None:
    """Indirection used to exercise ledger-write rollback deterministically."""
    handle.write(payload)


def _fsync_migration_ledger(handle) -> None:
    """Indirection used to exercise ledger-fsync rollback deterministically."""
    os.fsync(handle.fileno())


def _without_baseline_fields(document: dict) -> dict:
    return {key: copy.deepcopy(value) for key, value in document.items() if key not in BASELINE_REPORT_KEYS}


def _migrate_baseline_reports(
    project_root: Path,
    task_id: str,
    migration_task_id: str,
    plan: dict[str, dict[str, object]],
) -> dict[str, object]:
    """Apply one exact-preimage, baseline-only migration transaction.

    ``plan`` is deliberately explicit and caller-owned: unknown report bytes
    are rejected rather than normalized by consensus.  Exact preimages live
    outside ``docs/dev`` discovery and are the rollback source of truth.
    """
    authority, authority_errors = _load_baseline_authority(project_root, task_id)
    if authority_errors or authority is None:
        raise ValueError("; ".join(authority_errors))
    if not isinstance(plan, dict) or not plan:
        raise ValueError("migration plan must be a non-empty lane mapping")
    cycle_id = str(authority["cycle_id"])
    migration_root = (
        project_root
        / ".claude"
        / "dev-registry"
        / cycle_id
        / "baseline-migrations"
        / migration_task_id
    )
    preimage_root = migration_root / "preimages"
    ledger_path = migration_root / "migration-ledger.jsonl"
    if ledger_path.exists() or ledger_path.is_symlink():
        raise ValueError(f"append-only migration ledger already exists: {ledger_path}")

    dev_dir = _resolve_dev_dir(project_root)
    projections = _baseline_projections(authority)
    snapshot_raw = authority["snapshot_raw"]
    assert isinstance(snapshot_raw, bytes)
    snapshot_sha_before = hashlib.sha256(snapshot_raw).hexdigest()
    descriptor_raw = authority["descriptor_raw"]
    assert isinstance(descriptor_raw, bytes)
    descriptor_sha_before = hashlib.sha256(descriptor_raw).hexdigest()
    prepared: list[dict[str, object]] = []

    # Validate every preimage and every semantic invariant before the first
    # report or ledger byte is published.
    for lane in sorted(plan):
        entry = plan[lane]
        if not isinstance(entry, dict):
            raise ValueError(f"lane {lane!r} migration plan entry must be an object")
        path = dev_dir / f"dev-report-{task_id}-{lane}.json"
        raw, problem = _stable_regular_read(path)
        if problem is not None or raw is None:
            raise ValueError(f"lane {lane!r} report is unavailable or unsafe: {problem}")
        path_stat = os.lstat(path)
        actual_mode = stat.S_IMODE(path_stat.st_mode)
        actual_sha = hashlib.sha256(raw).hexdigest()
        expected_sha = entry.get("sha256")
        if actual_sha != expected_sha:
            raise ValueError(
                f"lane {lane!r} preimage sha256 {actual_sha} != planned {expected_sha}"
            )
        if "size_bytes" in entry and len(raw) != entry["size_bytes"]:
            raise ValueError(
                f"lane {lane!r} preimage size {len(raw)} != planned {entry['size_bytes']}"
            )
        expected_mode = entry.get("mode_octal")
        if expected_mode is not None:
            try:
                planned_mode = int(str(expected_mode), 8)
            except ValueError as exc:
                raise ValueError(
                    f"lane {lane!r} planned mode {expected_mode!r} is not octal"
                ) from exc
            if actual_mode != planned_mode:
                raise ValueError(
                    f"lane {lane!r} preimage mode {actual_mode:04o} != planned {planned_mode:04o}"
                )
        if "trailing_lf" in entry and raw.endswith(b"\n") is not entry["trailing_lf"]:
            raise ValueError(
                f"lane {lane!r} preimage trailing-LF state is not the planned value"
            )
        try:
            original = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"lane {lane!r} preimage is not UTF-8 JSON: {exc}") from exc
        if not isinstance(original, dict):
            raise ValueError(f"lane {lane!r} preimage root must be an object")
        status = original.get("dev", {}).get("status") if isinstance(original.get("dev"), dict) else None
        if status != entry.get("dev_status"):
            raise ValueError(
                f"lane {lane!r} dev.status {status!r} != planned {entry.get('dev_status')!r}"
            )
        if entry.get("require_active_lane_identity"):
            expected_identity = f"{task_id}-{lane}"
            role = original.get(DEV_REPORT_ROLE_KEY)
            if (
                original.get("request_id") != expected_identity
                or original.get("task_id") != expected_identity
                or original.get("parent_task_id") != task_id
                or original.get("lane") != lane
                or not isinstance(role, dict)
                or role.get("kind") != ROLE_ACTIVE_LANE_SHARD
                or role.get("aggregation_eligible") is not True
                or role.get("parent_task_id") != task_id
                or role.get("lane") != lane
            ):
                raise ValueError(f"lane {lane!r} active-root identity or role drifted")
        expected_existing = entry.get("existing_baseline_values", {})
        if not isinstance(expected_existing, dict):
            raise ValueError(
                f"lane {lane!r} existing_baseline_values must be an object"
            )
        existing_mismatches = [
            field
            for field, expected_value in expected_existing.items()
            if original.get(field) != expected_value
        ]
        if existing_mismatches:
            raise ValueError(
                f"lane {lane!r} existing baseline projections drifted at {existing_mismatches}"
            )
        migrated = copy.deepcopy(original)
        migrated.update(copy.deepcopy(projections))
        if _without_baseline_fields(original) != _without_baseline_fields(migrated):
            raise AssertionError(f"lane {lane!r} non-baseline decoded JSON changed")
        changed_json_pointers = [
            f"/{field}"
            for field in sorted(BASELINE_REPORT_KEYS)
            if field not in original or original.get(field) != migrated.get(field)
        ]
        expected_pointers = entry.get("changed_json_pointers")
        if expected_pointers is not None and changed_json_pointers != expected_pointers:
            raise ValueError(
                f"lane {lane!r} changed pointers {changed_json_pointers} "
                f"!= planned {expected_pointers}"
            )
        post_raw = (
            json.dumps(migrated, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
        )
        prepared.append({
            "lane": lane,
            "path": path,
            "raw": raw,
            "mode": actual_mode,
            "preimage_sha256": actual_sha,
            "post_raw": post_raw,
            "postimage_sha256": hashlib.sha256(post_raw).hexdigest(),
            "legacy_representation": entry.get("legacy"),
            "changed_json_pointers": changed_json_pointers,
        })

    preimage_root.mkdir(parents=True, exist_ok=True)
    for item in prepared:
        path = item["path"]
        raw = item["raw"]
        assert isinstance(path, Path) and isinstance(raw, bytes)
        saved = preimage_root / path.name
        if saved.exists() or saved.is_symlink():
            saved_raw, problem = _stable_regular_read(saved)
            if problem is not None or saved_raw != raw:
                raise ValueError(f"existing preimage preservation file conflicts: {saved}")
        else:
            descriptor = os.open(saved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
            except BaseException:
                saved.unlink(missing_ok=True)
                raise

    ledger_rows: list[dict[str, object]] = []
    authority_contract = authority["contract"]
    assert isinstance(authority_contract, dict)
    authority_dirty = authority_contract["dirty_snapshot"]
    assert isinstance(authority_dirty, dict)
    for item in prepared:
        path = item["path"]
        assert isinstance(path, Path)
        ledger_rows.append({
            "schema_version": 1,
            "cycle_id": cycle_id,
            "migration_task_id": migration_task_id,
            "lane": item["lane"],
            "preimage_path": str((preimage_root / path.name).relative_to(project_root)),
            "preimage_sha256": item["preimage_sha256"],
            "postimage_path": str(path.relative_to(project_root)),
            "postimage_sha256": item["postimage_sha256"],
            "legacy_representation": item["legacy_representation"],
            "changed_json_pointers": item["changed_json_pointers"],
            "authority_sha256": authority_dirty["sha256"],
            "current_tree_read": False,
            "nonbaseline_json_deep_equal": True,
            "rollback_preimage_path": str((preimage_root / path.name).relative_to(project_root)),
            "rollback_source_sha256": item["preimage_sha256"],
        })
    ledger_payload = b"".join(
        json.dumps(row, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
        for row in ledger_rows
    )

    temporary_reports: list[tuple[dict[str, object], Path]] = []
    replaced: list[dict[str, object]] = []
    ledger_created = False
    try:
        for item in prepared:
            path = item["path"]
            post_raw = item["post_raw"]
            assert isinstance(path, Path) and isinstance(post_raw, bytes)
            temp_path = _write_temp_bytes(path, post_raw)
            os.chmod(temp_path, int(item["mode"]))
            temporary_reports.append((item, temp_path))
        for item, temp_path in temporary_reports:
            path = item["path"]
            assert isinstance(path, Path)
            _replace_path(temp_path, path)
            replaced.append(item)

        migration_root.mkdir(parents=True, exist_ok=True)
        ledger_fd = os.open(ledger_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
        ledger_created = True
        try:
            with os.fdopen(ledger_fd, "wb") as handle:
                _write_migration_ledger(handle, ledger_payload)
                handle.flush()
                _fsync_migration_ledger(handle)
        except BaseException:
            ledger_path.unlink(missing_ok=True)
            ledger_created = False
            raise
    except BaseException:
        for _item, temporary_path in temporary_reports:
            temporary_path.unlink(missing_ok=True)
        if ledger_created:
            ledger_path.unlink(missing_ok=True)
        rollback_errors: list[str] = []
        for item in reversed(replaced):
            path = item["path"]
            raw = item["raw"]
            assert isinstance(path, Path) and isinstance(raw, bytes)
            try:
                restore = _write_temp_bytes(path, raw)
                os.chmod(restore, int(item["mode"]))
                os.replace(restore, path)
            except BaseException as exc:  # pragma: no cover - catastrophic filesystem failure
                rollback_errors.append(f"{path}: {exc}")
        if rollback_errors:
            raise RuntimeError(f"migration failed and rollback was incomplete: {rollback_errors}")
        raise

    # Prove the complete frozen authority and every published report match the
    # prepared identities.  This reads no live working-tree status.
    try:
        authority_after, authority_after_errors = _load_baseline_authority(
            project_root, task_id
        )
        if authority_after_errors or authority_after is None:
            raise RuntimeError(
                "frozen authority became invalid after migration: "
                + "; ".join(authority_after_errors)
            )
        snapshot_after = authority_after["snapshot_raw"]
        descriptor_after = authority_after["descriptor_raw"]
        assert isinstance(snapshot_after, bytes) and isinstance(descriptor_after, bytes)
        snapshot_sha_after = hashlib.sha256(snapshot_after).hexdigest()
        if snapshot_sha_after != snapshot_sha_before:
            raise RuntimeError("frozen snapshot bytes changed during migration")
        descriptor_sha_after = hashlib.sha256(descriptor_after).hexdigest()
        if descriptor_sha_after != descriptor_sha_before:
            raise RuntimeError("frozen authority descriptor bytes changed during migration")
        for item in prepared:
            path = item["path"]
            assert isinstance(path, Path)
            published, problem = _stable_regular_read(path)
            if problem is not None or published is None:
                raise RuntimeError(f"postimage became unavailable for {path}: {problem}")
            if hashlib.sha256(published).hexdigest() != item["postimage_sha256"]:
                raise RuntimeError(f"postimage verification failed for {path}")
            if stat.S_IMODE(os.lstat(path).st_mode) != item["mode"]:
                raise RuntimeError(f"postimage mode verification failed for {path}")
    except BaseException:
        ledger_path.unlink(missing_ok=True)
        rollback_errors = []
        for item in reversed(prepared):
            path = item["path"]
            raw = item["raw"]
            assert isinstance(path, Path) and isinstance(raw, bytes)
            try:
                restore = _write_temp_bytes(path, raw)
                os.chmod(restore, int(item["mode"]))
                os.replace(restore, path)
            except BaseException as exc:  # pragma: no cover - catastrophic filesystem failure
                rollback_errors.append(f"{path}: {exc}")
        if rollback_errors:
            raise RuntimeError(f"post-verification failed and rollback was incomplete: {rollback_errors}")
        raise

    return {
        "status": "completed",
        "cycle_id": cycle_id,
        "migration_task_id": migration_task_id,
        "lanes": [item["lane"] for item in prepared],
        "ledger_path": str(ledger_path.relative_to(project_root)),
        "preimage_root": str(preimage_root.relative_to(project_root)),
        "authority_sha256_before": snapshot_sha_before,
        "authority_sha256_after": snapshot_sha_after,
        "authority_descriptor_sha256_before": descriptor_sha_before,
        "authority_descriptor_sha256_after": descriptor_sha_after,
        "current_tree_read": False,
        "rollback_preimages_preserved": True,
    }


def _build_aggregate(
    shards: list[tuple[str, dict]],
    task_id: str,
    authority: dict[str, object],
    declaration: dict | None = None,
) -> dict:
    """Construct the canonical aggregate document from validated shards.

    Called ONLY after shard and authority validation passes.  Therefore
    aggregate dev.status is always 'completed' here.

    ``declaration`` is the orchestrator-written shape declaration; it is carried
    forward verbatim so a rebuild cannot silently drop it.
    """
    worker_ids = [label for label, _ in shards]
    now_iso = datetime.now(timezone.utc).isoformat()

    aggregate = {
        "request_id": task_id,
        "task_id": task_id,
        "timestamp": now_iso,
        **_baseline_projections(authority),
        "dev_report_path": f"docs/dev/dev-report-{task_id}.json",
        "parallel_workers": worker_ids,
        "dev": {
            "status": "completed",
            "tasks_completed": _union_list(shards, ["dev", "tasks_completed"]),
            "scripts_created": _union_list(shards, ["dev", "scripts_created"]),
            "permissions_to_add": _union_list(shards, ["dev", "permissions_to_add"]),
            "files_modified": _union_list(shards, ["dev", "files_modified"]),
            "files_created": _union_list(shards, ["dev", "files_created"]),
            "observed_preexisting": _union_list(shards, ["dev", "observed_preexisting"]),
        },
        "blocking_issues": _union_list(shards, ["blocking_issues"]),
        "recommendations": _union_list(shards, ["recommendations"]),
    }
    if declaration is not None:
        aggregate[DECLARATION_KEY] = declaration
    return aggregate


def _bare_task_id(task_id: str) -> str:
    """Extract YYYYMMDD-HHMMSS portion from a potentially-prefixed task-id."""
    m = re.search(r"(\d{8}-\d{6})", task_id)
    return m.group(1) if m else task_id


def _emit_ok(action: str, output_path: str, reason: str) -> None:
    print(json.dumps({
        "status": "ok",
        "action": action,
        "output_path": output_path,
        "reason": reason,
    }))


def _emit_error(reason: str) -> None:
    sys.stderr.write(f"aggregate-dev-report: {reason}\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aggregate-dev-report.py",
        description="Write canonical aggregate dev-report for parallel-dev cycles.",
    )
    parser.add_argument(
        "--task-id",
        required=True,
        help="Task-id for the parallel-dev cycle (e.g. dev-20260524-170335 or 20260524-170335).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Validate shards without writing the canonical aggregate.",
    )
    parser.add_argument(
        "--shape",
        choices=DECLARED_SHAPES,
        default=None,
        help=(
            "Artifact-chain shape declared by the orchestrator at decomposition "
            "time. Omit for legacy declaration-less behaviour."
        ),
    )
    parser.add_argument(
        "--declared-lanes",
        default=None,
        help=(
            "Comma-separated lane suffixes for --shape requirement_fanout "
            "(one-to-one with the decomposition-time requirements[]). Must be "
            "omitted or empty for --shape parallel_dev."
        ),
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    task_id = args.task_id.strip()
    if not task_id:
        _emit_error("--task-id must be non-empty")
        return 2

    declaration, declaration_error = _declaration_from_arguments(
        args.shape, args.declared_lanes
    )
    if declaration_error is not None:
        _emit_error(declaration_error)
        return 2

    # Bare timestamp needed for shard filename matching (patterns use YYYYMMDD-HHMMSS).
    bare_tid = _bare_task_id(task_id)

    project_root = _resolve_project_root()
    dev_dir = _resolve_dev_dir(project_root)
    # Canonical path uses the FULL task_id (not bare timestamp) so that
    # dev-report-dev-20260524-170335.json ≠ dev-report-20260524-170335.json.
    canonical_path = dev_dir / f"dev-report-{task_id}.json"

    # Discovery is declaration-driven for requirement fan-out and audits every
    # task-correlated history/alias before active-shard validation.
    discovery = _discover_dev_reports(dev_dir, task_id, declaration)
    shards_info: list[tuple[str, Path]] = discovery["active"]  # type: ignore[assignment]
    classification_errors: list[dict[str, str]] = discovery["errors"]  # type: ignore[assignment]

    if declaration is None and len(shards_info) < 2 and not classification_errors:
        # ≤1 shard — not a declaration-less parallel cycle; preserve legacy skip.
        _emit_ok(
            action="skipped",
            output_path=str(canonical_path),
            reason=f"Found {len(shards_info)} worker shard(s) for task-id {task_id!r}; parallel aggregation requires >=2.",
        )
        return 0

    if (
        declaration is not None
        and declaration.get("shape") == SHAPE_PARALLEL_DEV
        and len(shards_info) < 2
    ):
        classification_errors.append(
            _classification_error(
                "MISSING_DECLARED_SHARD",
                "docs/dev",
                "parallel_dev requires at least two real active worker roots",
            )
        )

    # Load all shards.
    loaded: list[tuple[str, dict]] = []
    for label, path in shards_info:
        data = _load_shard(path)
        if data is None:
            _emit_error(f"Failed to load shard '{label}' at {path}")
            return 1
        loaded.append((label, data))

    # The expected baseline is loaded independently from the task-derived
    # registry location.  Shards cannot supply or repair this authority.
    authority, authority_errors = _load_baseline_authority(project_root, task_id)

    # Validate identity, baseline, and status together so a baseline defect can
    # never suppress a genuine non-completed shard status (or vice versa).
    errors = [
        f"[{item['code']}] {item['path']}: {item['detail']}"
        for item in classification_errors
    ]
    errors.extend(authority_errors)
    errors.extend(_validate_shards(loaded, task_id, authority))
    if errors:
        _emit_error("Shard validation failed:\n  " + "\n  ".join(errors))
        return 1
    assert authority is not None

    if canonical_path.exists():
        # Existing canonical baseline bytes are evidence, not a refresh hint.
        # A legacy/mismatching canonical is a baseline failure and remains
        # byte-identical; only non-baseline aggregate content may be refreshed.
        try:
            existing = json.loads(canonical_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            _emit_error(f"Cannot read existing canonical {canonical_path}: {exc}")
            return 1
        canonical_baseline_errors = _validate_shards(
            [("canonical", existing)], task_id, authority
        )
        if canonical_baseline_errors:
            _emit_error(
                "Existing canonical baseline validation failed:\n  "
                + "\n  ".join(canonical_baseline_errors)
            )
            return 1
        expected_workers = [label for label, _ in loaded]
        existing_workers = list(existing.get("parallel_workers") or [])
        expected_sha = _baseline_projections(authority)["baseline_head_sha"]
        existing_sha = existing.get("baseline_head_sha", "")
        if existing_workers != expected_workers or existing_sha != expected_sha:
            _emit_error(
                f"Existing canonical {canonical_path} is stale: "
                f"workers {existing_workers} (expected {expected_workers}), "
                f"baseline_sha {existing_sha!r} (expected {expected_sha!r})"
            )
            return 1
        existing_declaration = existing.get(DECLARATION_KEY)
        if (
            declaration is not None
            and existing_declaration is not None
            and existing_declaration != declaration
        ):
            _emit_error(
                f"Declaration disagreement for {canonical_path}: canonical carries "
                f"{json.dumps(existing_declaration, sort_keys=True)} but this invocation "
                f"supplied {json.dumps(declaration, sort_keys=True)}; "
                f"refusing to silently overwrite the declaration."
            )
            return 1
        effective_declaration = (
            declaration if declaration is not None else existing_declaration
        )
        expected = _build_aggregate(loaded, task_id, authority, effective_declaration)
        if _canonical_projection(existing) != _canonical_projection(expected):
            if args.dry_run:
                _emit_ok(
                    action="skipped",
                    output_path=str(canonical_path),
                    reason=(
                        f"Dry-run: existing canonical is stale and would be refreshed "
                        f"from {len(loaded)} current shards for task-id {task_id!r}."
                    ),
                )
                return 0
            try:
                _atomic_write_json(canonical_path, expected)
            except OSError as exc:
                _emit_error(f"Cannot refresh canonical aggregate at {canonical_path}: {exc}")
                return 1
            _emit_ok(
                action="aggregated",
                output_path=str(canonical_path),
                reason=(
                    f"Refreshed stale canonical from {len(loaded)} current shards "
                    f"for task-id {task_id!r}."
                ),
            )
            return 0
        _emit_ok(
            action="validated",
            output_path=str(canonical_path),
            reason=f"Canonical aggregate already exists and matches {len(loaded)} shards for task-id {task_id!r}.",
        )
        return 0

    if args.dry_run:
        _emit_ok(
            action="skipped",
            output_path=str(canonical_path),
            reason=f"Dry-run: would aggregate {len(loaded)} shards for task-id {task_id!r}.",
        )
        return 0

    # Build and write canonical aggregate.
    aggregate = _build_aggregate(loaded, task_id, authority, declaration)
    try:
        _atomic_write_json(canonical_path, aggregate)
    except OSError as exc:
        _emit_error(f"Cannot write canonical aggregate to {canonical_path}: {exc}")
        return 1

    _emit_ok(
        action="aggregated",
        output_path=str(canonical_path),
        reason=f"Aggregated {len(loaded)} worker shards into {canonical_path}.",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
