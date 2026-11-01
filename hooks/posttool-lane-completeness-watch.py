#!/usr/bin/env python3
"""PostToolUse Hook (Write|Edit|NotebookEdit|MultiEdit matcher): the one
producer of a fan-out's canonical aggregate dev-report (P1b E5). Every write
of a lane report runs the harness's aggregator for its task, so the canonical
follows the lane reports as they land, without waiting for the orchestrator's
next dispatch or a later /close (ticket 20261001-161041-r05).

Trigger: tool_input.file_path's basename matches a per-worker ("lane")
dev-report shard filename (lib.dev_report_shard_patterns.classify_filename
returns ("worker", task_id, lane)) and the report's own `lane_set` declares
the fan-out (schema v2 requires it non-null when `lane` is a string --
schemas/dev-report.v2.json). Canonical-aggregate writes, a report without a
lane_set (a singular cycle, an overnight pipeline's dev-report-<ts>-<N>.json)
and every other file path are a no-op with no filesystem I/O beyond reading
stdin and that report.

This hook decides nothing about the roster: whether every lane the lane_set
declares has reported, and whether the canonical names them all, is G3's
collection check before QA (hooks/pretool-aggregate-check.py). A canonical
written before the last lane lands is rewritten by that lane's write.

S1: the hook runs the harness's own
`scripts/aggregate-dev-report.py --task-id <task_id> --project-dir <project>`
(bounded timeout). Both of the aggregator's own legitimate outcomes -- exit 0, or
exit 1 with its own R29 blocked-canonical write -- count as "invocation
completed," never as a hook malfunction. Any exception/timeout/non-zero
exit is swallowed; the hook's own exit code is unaffected (AC6).

Fail-open contract (universal in this codebase): parsing failures, missing
stdin, missing project dir, unexpected exceptions -> exit 0. This hook
NEVER blocks or delays the writer's own tool call on a self-bug.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.dev_report_shard_patterns import classify_filename  # noqa: E402

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


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def _invoke_aggregator(project_dir, task_id):
    """S1: best-effort aggregator auto-invocation. The aggregator's own
    non-zero R29 blocked-canonical exit, a timeout, or any unexpected
    exception are all swallowed here -- never raised into this hook's own
    exit code (AC6)."""
    try:
        # The harness's own copy, next to this hook: a product repository has
        # no scripts/ of its own.
        script = Path(__file__).resolve().parent.parent / "scripts" / "aggregate-dev-report.py"
        if not script.exists():
            return
        subprocess.run(
            ["python3", str(script), "--task-id", task_id, "--project-dir", str(project_dir)],
            cwd=project_dir,
            capture_output=True,
            timeout=AGGREGATOR_TIMEOUT_SECONDS,
            check=False,
        )
    except Exception:
        pass


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

    _, task_id, _ = result

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
    if not isinstance(lane_set, list) or not lane_set:
        sys.exit(0)

    _invoke_aggregator(project_dir, task_id)

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
