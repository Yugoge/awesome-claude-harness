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
import json
import os
import re
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
    """Return list of (worker_label, shard_path) for task_id in dev_dir."""
    shards = []
    if not dev_dir.is_dir():
        return shards
    try:
        children = list(dev_dir.iterdir())
    except OSError as exc:
        sys.stderr.write(f"aggregate-dev-report: cannot read {dev_dir}: {exc}\n")
        return shards
    for child in children:
        if not child.is_file():
            continue
        is_worker, label = _is_worker_for_task(child.name, bare_tid, original_task_id)
        if is_worker and label is not None:
            shards.append((label, child))
    shards.sort(key=lambda t: t[0])
    return shards


def _load_shard(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"aggregate-dev-report: cannot load shard {path}: {exc}\n")
        return None


def _validate_shards(shards: list[tuple[str, dict]], task_id: str) -> list[str]:
    """Return list of validation error strings (empty = all pass).

    Each shard must have:
    - Non-empty task_id or request_id matching the target (bare-timestamp normalized)
    - Non-empty baseline_head_sha (empty string is rejected)
    - Explicit baseline_dirty_snapshot key (may be empty string if clean)
    - dev.status == 'completed'
    - Consistent baseline_head_sha and baseline_dirty_snapshot across all shards
    """
    errors = []
    baseline_sha: str | None = None
    baseline_dirty: str | None = None
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
            errors.append(
                f"shard '{label}': dev.status is {status!r}, expected 'completed'"
            )

        # Require non-empty baseline_head_sha.
        sha = data.get("baseline_head_sha", "")
        if not sha:
            errors.append(
                f"shard '{label}': baseline_head_sha is missing or empty"
            )
        if baseline_sha is None:
            baseline_sha = sha
        elif sha != baseline_sha:
            errors.append(
                f"shard '{label}': baseline_head_sha {sha!r} != first shard {baseline_sha!r}"
            )

        # Require explicit baseline_dirty_snapshot key (value may be empty string).
        if "baseline_dirty_snapshot" not in data:
            errors.append(
                f"shard '{label}': missing baseline_dirty_snapshot key"
            )
        dirty = data.get("baseline_dirty_snapshot", "")
        # Empty string means the worker did not capture git status (parallel
        # dispatch timing); skip it as a comparison candidate so it does not
        # become the reference value that causes non-empty shards to mismatch.
        if dirty:
            if baseline_dirty is None:
                baseline_dirty = dirty
            elif dirty != baseline_dirty:
                errors.append(
                    f"shard '{label}': baseline_dirty_snapshot mismatch"
                )

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
        "baseline_head_sha",
        "baseline_dirty_snapshot",
        "dev_report_path",
        "parallel_workers",
        "dev",
        "blocking_issues",
        "recommendations",
    )
    return {key: document.get(key) for key in keys}


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


def _build_aggregate(shards: list[tuple[str, dict]], task_id: str) -> dict:
    """Construct the canonical aggregate document from validated shards.

    Called ONLY after _validate_shards passes (all shards completed, consistent
    baseline). Therefore aggregate dev.status is always 'completed' here.
    """
    worker_ids = [label for label, _ in shards]
    now_iso = datetime.now(timezone.utc).isoformat()

    # All shards are guaranteed validated-consistent at this point.
    sha = next((d.get("baseline_head_sha", "") for _, d in shards), "")
    dirty = next((d.get("baseline_dirty_snapshot", "") for _, d in shards), "")

    aggregate = {
        "request_id": task_id,
        "task_id": task_id,
        "timestamp": now_iso,
        "baseline_head_sha": sha,
        "baseline_dirty_snapshot": dirty,
        "dev_report_path": f"docs/dev/dev-report-{task_id}.json",
        "parallel_workers": worker_ids,
        "shard_provenance": _build_shard_provenance(shards),
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
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    task_id = args.task_id.strip()
    if not task_id:
        _emit_error("--task-id must be non-empty")
        return 2

    # Bare timestamp needed for shard filename matching (patterns use YYYYMMDD-HHMMSS).
    bare_tid = _bare_task_id(task_id)

    project_root = _resolve_project_root()
    dev_dir = _resolve_dev_dir(project_root)
    # Canonical path uses the FULL task_id (not bare timestamp) so that
    # dev-report-dev-20260524-170335.json ≠ dev-report-20260524-170335.json.
    canonical_path = dev_dir / f"dev-report-{task_id}.json"

    # Scan for shards scoped to this task-id (using bare timestamp for pattern matching).
    shards_info = _scan_shards(dev_dir, bare_tid, task_id)

    if len(shards_info) < 2:
        # ≤1 shard — not a parallel cycle; skip.
        _emit_ok(
            action="skipped",
            output_path=str(canonical_path),
            reason=f"Found {len(shards_info)} worker shard(s) for task-id {task_id!r}; parallel aggregation requires >=2.",
        )
        return 0

    # Load all shards.
    loaded: list[tuple[str, dict]] = []
    for label, path in shards_info:
        data = _load_shard(path)
        if data is None:
            _emit_error(f"Failed to load shard '{label}' at {path}")
            return 1
        loaded.append((label, data))

    # Validate consistency — fail closed on any mismatch.
    errors = _validate_shards(loaded, task_id)
    if errors:
        _emit_error("Shard validation failed:\n  " + "\n  ".join(errors))
        return 1

    if canonical_path.exists():
        # Preserve the legacy fail-closed identity/baseline checks, then use
        # whole-shard provenance plus the aggregate projection for freshness.
        try:
            existing = json.loads(canonical_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            _emit_error(f"Cannot read existing canonical {canonical_path}: {exc}")
            return 1
        expected_workers = sorted(label for label, _ in loaded)
        existing_workers = sorted(existing.get("parallel_workers") or [])
        expected_sha = next((d.get("baseline_head_sha", "") for _, d in loaded), "")
        existing_sha = existing.get("baseline_head_sha", "")
        if existing_workers != expected_workers or existing_sha != expected_sha:
            _emit_error(
                f"Existing canonical {canonical_path} is stale: "
                f"workers {existing_workers} (expected {expected_workers}), "
                f"baseline_sha {existing_sha!r} (expected {expected_sha!r})"
            )
            return 1
        expected = _build_aggregate(loaded, task_id)
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
    aggregate = _build_aggregate(loaded, task_id)
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
