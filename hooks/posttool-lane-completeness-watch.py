#!/usr/bin/env python3
"""PostToolUse Hook (Write|Edit|NotebookEdit|MultiEdit matcher): detect the
instant a lane-shard dev-report write completes its declared lane_set
roster, and durably record that fact -- closing the detection-window gap
that otherwise depends on the orchestrator's NEXT Agent/Task dispatch
(hooks/pretool-aggregate-check.py) or a later /close invocation ever
happening in the same session (ticket 20261001-161041-r05).

Trigger: tool_input.file_path's basename matches a per-worker ("lane")
dev-report shard filename (lib.dev_report_shard_patterns.classify_filename
returns ("worker", task_id, lane)). Canonical-aggregate writes and every
other file path are a zero-cost no-op with zero filesystem I/O beyond
reading stdin (AC1).

M3: the just-written shard's OWN `lane_set` field (schema v2, required
non-null when `lane` is a string -- schemas/dev-report.v2.json) is the
authoritative expected roster. A legacy/v1 shard (`lane_set` absent/null)
carries no authoritative roster -- this hook never guesses one; it logs an
advisory-only record and exits 0, attempting no completeness detection
(AC4).

M4: when `lane_set` is authoritative, scan docs/dev/ (via the shared
lib.dev_report_shard_patterns module) for a shard for every declared lane.
An incomplete roster is the normal mid-cycle state for every write before
the last one -- exit 0, zero side effects (AC3).

M5: a complete roster with no fresh canonical aggregate on disk writes a
durable, idempotent marker at
.claude/dev-registry/dev-<task_id>/aggregate-pending.json (AC2, AC7).
"Fresh" means the canonical's own mtime is not older than the newest
roster shard's mtime -- the same staleness notion
hooks/pretool-aggregate-check.py / scripts/resolve-dev-artifact-chain.py
apply when deciding whether an existing canonical still covers the current
shard set.

S1: in addition to the marker, the hook attempts
`python3 scripts/aggregate-dev-report.py --task-id <task_id>` (bounded
timeout). Both of the aggregator's own legitimate outcomes -- exit 0, or
exit 1 with its own R29 blocked-canonical write -- count as "invocation
completed," never as a hook malfunction. Any exception/timeout/non-zero
exit is swallowed and advisory-logged; the hook's own exit code is
unaffected (AC6).

lane_set trust boundary: a shard's self-declared lane_set is cross-checked
for verbatim equality (lib.obligation.lane_sets_identical, design
Â§1.3-G1 check 4) against every OTHER on-disk shard found for the same
task_id. Any mismatch makes the roster non-authoritative for this event
(advisory log, exit 0) rather than risking a false-positive completeness
signal from a malformed or adversarial lane_set.

Fail-open contract (universal in this codebase): parsing failures, missing
stdin, missing project dir, unexpected exceptions -> exit 0. This hook
NEVER blocks or delays the writer's own tool call on a self-bug.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib import obligation as obligation_lib  # noqa: E402
from lib.dev_report_shard_patterns import classify_filename  # noqa: E402

ADVISORY_LOG = os.path.join(
    "~", ".claude", "logs", "lane-completeness-watch-advisory.jsonl"
)
AGGREGATOR_TIMEOUT_SECONDS = 30


def _load_stdin():
    try:
        return json.load(sys.stdin)
    except Exception:
        return None


def _file_path(data):
    if not isinstance(data, dict):
        return None
    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return None
    path = tool_input.get("file_path")
    return path if isinstance(path, str) and path else None


def _resolve_project_dir():
    return os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def _log_advisory(record):
    """Best-effort append to the advisory log. Never raises."""
    try:
        log_path = os.path.expanduser(ADVISORY_LOG)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
    except Exception:
        pass


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def _dev_session_dir_name(task_id):
    """Map a filename-derived task_id to its .claude/dev-registry/ session
    directory name. The active /dev adapter's own task_id already carries a
    literal "dev-" prefix (e.g. "dev-20260427-130000"); a bare timestamp
    (e.g. "20261001-161041") gets one prepended -- matching the convention
    observed on disk for both families (never double-prefixed)."""
    return task_id if task_id.startswith("dev-") else f"dev-{task_id}"


def _canonical_filename(task_id):
    return f"dev-report-{task_id}.json"


def _marker_path(project_dir, task_id):
    return (
        Path(project_dir) / ".claude" / "dev-registry"
        / _dev_session_dir_name(task_id) / "aggregate-pending.json"
    )


def _scan_roster(dev_dir, task_id, lane_set):
    """Scan docs/dev/ for this task_id's roster.

    Returns (present_lanes: set, canonical_mtime: float|None,
    latest_shard_mtime: float|None, sibling_lane_sets: list).
    """
    present = set()
    sibling_lane_sets = []
    latest_mtime = None
    try:
        children = list(dev_dir.iterdir())
    except OSError:
        return present, None, None, sibling_lane_sets
    for child in children:
        if not child.is_file():
            continue
        result = classify_filename(child.name)
        if result is None or result[0] != "worker":
            continue
        _, c_task_id, label = result
        if c_task_id != task_id or label not in lane_set:
            continue
        present.add(label)
        try:
            mtime = child.stat().st_mtime
        except OSError:
            mtime = None
        if mtime is not None and (latest_mtime is None or mtime > latest_mtime):
            latest_mtime = mtime
        shard = _read_json(child)
        if isinstance(shard, dict):
            sibling_lane_sets.append(shard.get("lane_set"))
    canonical_path = dev_dir / _canonical_filename(task_id)
    canonical_mtime = None
    try:
        if canonical_path.exists():
            canonical_mtime = canonical_path.stat().st_mtime
    except OSError:
        canonical_mtime = None
    return present, canonical_mtime, latest_mtime, sibling_lane_sets


def _roster_authoritative(lane_set, sibling_lane_sets):
    """False iff any sibling shard's own lane_set diverges from the
    just-written shard's lane_set (G1-style verbatim-equality trust
    boundary); a sibling that is itself legacy (lane_set is None) carries
    no opinion and is not a divergence."""
    for other in sibling_lane_sets:
        if other is None:
            continue
        if not obligation_lib.lane_sets_identical(lane_set, other):
            return False
    return True


def _write_marker_if_absent(marker_path, task_id, lane_set):
    """Idempotent: a marker that already exists is left untouched (AC2 --
    replay of the completing event must not duplicate or corrupt it)."""
    if marker_path.exists():
        return False
    try:
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = marker_path.with_name(marker_path.name + ".tmp")
        document = {
            "task_id": task_id,
            "lane_set": lane_set,
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp_path, marker_path)
        return True
    except Exception:
        return False


def _invoke_aggregator(project_dir, task_id):
    """S1: best-effort aggregator auto-invocation. The aggregator's own
    non-zero R29 blocked-canonical exit, a timeout, or any unexpected
    exception are all swallowed here -- never raised into this hook's own
    exit code (AC6)."""
    try:
        script = Path(project_dir) / "scripts" / "aggregate-dev-report.py"
        if not script.exists():
            return
        result = subprocess.run(
            ["python3", str(script), "--task-id", task_id],
            cwd=project_dir,
            capture_output=True,
            timeout=AGGREGATOR_TIMEOUT_SECONDS,
            check=False,
        )
        _log_advisory({
            "reason": "aggregator_invoked",
            "task_id": task_id,
            "returncode": result.returncode,
        })
    except Exception as exc:
        _log_advisory({
            "reason": "aggregator_invocation_failed",
            "task_id": task_id,
            "error": str(exc),
        })


def main():
    data = _load_stdin()
    if data is None:
        sys.exit(0)

    path = _file_path(data)
    if not path:
        sys.exit(0)

    basename = os.path.basename(path)
    result = classify_filename(basename)
    if result is None or result[0] != "worker":
        sys.exit(0)

    _, task_id, lane = result

    project_dir = _resolve_project_dir()
    dev_dir = Path(project_dir) / "docs" / "dev"
    candidate_paths = [Path(path)]
    if not os.path.isabs(path):
        candidate_paths.insert(0, Path(project_dir) / path)
    candidate_paths.append(dev_dir / basename)

    shard = None
    for candidate in candidate_paths:
        if candidate.exists():
            shard = _read_json(candidate)
            break
    if not isinstance(shard, dict):
        sys.exit(0)

    lane_set = shard.get("lane_set")
    if lane_set is None:
        _log_advisory({
            "reason": "legacy_shard_no_lane_set",
            "task_id": task_id,
            "lane": lane,
            "path": path,
        })
        sys.exit(0)
    if not isinstance(lane_set, list) or not lane_set:
        sys.exit(0)

    try:
        present, canonical_mtime, latest_mtime, siblings = _scan_roster(
            dev_dir, task_id, set(lane_set)
        )
    except Exception:
        sys.exit(0)

    if not _roster_authoritative(lane_set, siblings):
        _log_advisory({
            "reason": "lane_set_mismatch_non_authoritative",
            "task_id": task_id,
            "lane": lane,
        })
        sys.exit(0)

    missing = [member for member in lane_set if member not in present]
    if missing:
        sys.exit(0)

    canonical_fresh = (
        canonical_mtime is not None
        and (latest_mtime is None or canonical_mtime >= latest_mtime)
    )
    if canonical_fresh:
        sys.exit(0)

    marker_path = _marker_path(project_dir, task_id)
    written = _write_marker_if_absent(marker_path, task_id, lane_set)
    if written:
        _log_advisory({
            "reason": "aggregate_pending_marker_written",
            "task_id": task_id,
            "marker_path": str(marker_path),
        })
    _invoke_aggregator(project_dir, task_id)

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
