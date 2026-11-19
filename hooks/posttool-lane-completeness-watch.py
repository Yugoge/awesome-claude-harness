#!/usr/bin/env python3
"""PostToolUse Hook (Write|Edit|NotebookEdit|MultiEdit matcher): the one
producer of a fan-out's canonical aggregate dev-report (P1b E5). A write of a
lane report (lib.dev_report_shard_patterns.classify_filename reads it as
("worker", task_id, lane); its own `lane_set` declares the fan-out) runs the
harness's `scripts/aggregate-dev-report.py --task-id <task_id> --project-dir
<project>` (bounded timeout), so the canonical follows the lane reports as they
land and the last lane's write rewrites an earlier one (ticket
20261001-161041-r05). Any other path, a canonical, or a report without a
lane_set (a singular cycle, an overnight pipeline's dev-report-<ts>-<N>.json)
is a no-op. The roster is G3's (hooks/pretool-aggregate-check.py); the
aggregator's refusal is not reported here but at the lane's stop (G2, its
reasons about that lane's report) and the main agent's QA dispatch (G3, all of
them). Fail-open: nothing here blocks or delays the writer's tool call (AC6).
"""
import os, sys  # noqa: E401 -- the harness switch (hooks/lib/harness_switch.py): no harness hook runs while /harness off holds
sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "lib"))
try:  # a hook copied without its lib/ (an old install) is on
    import harness_switch  # noqa: E402
    harness_switch.exit_if_off()
except ImportError:
    pass
finally:
    sys.path.pop(0)

import json
import subprocess
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
    """Best effort: the aggregator's exit 1, a timeout or an exception never reaches this hook's exit (AC6)."""
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
