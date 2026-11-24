"""A fan-out's canonical aggregate rebuilt where it is read, whatever wrote a lane report.

One staleness test and one rebuild, the aggregator's own (scripts/aggregate-dev-report.py
stale_lane_reports and rebuild_if_stale; its one writer is that script), loaded here for:
- the subagent-stop chain's aggregate-rebuild rule (hooks/subagentstop-producer-gate.py,
  at_lane_stop): a dev lane of a fan-out stops, and its report is newer than the canonical;
- the check at QA dispatch (hooks/pretool-aggregate-check.py, G3), which judges no canonical
  its rebuild leaves stale.
The Stop gate (hooks/stop-command-gate.py disposition) calls the same function.
"""
from __future__ import annotations

import functools
import importlib.util
import os
from pathlib import Path

# The SubagentStop registration names no timeout, so the CLI's 60 s hold the whole chain. A rebuild of a
# 16-lane cycle in a project tracked at its baseline measured 15.7 s: one cut off here leaves the canonical
# stale (never current-looking), and the next reader (G3, the Stop gate) tries again.
LANE_STOP_TIMEOUT_S = 40
QA_DISPATCH_TIMEOUT_S = 40  # the dispatch gate's rule runs under the launcher's 60 s default


@functools.lru_cache(maxsize=1)
def aggregator():
    """The harness's own scripts/aggregate-dev-report.py as a module (a product repository has none)."""
    path = Path(__file__).resolve().parents[2] / "scripts" / "aggregate-dev-report.py"
    spec = importlib.util.spec_from_file_location("aggregate_dev_report", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def at_lane_stop(payload: dict) -> list[str]:
    """Observe rule: the stopping dev lane's own obligation names its report and a lane_set of two or more;
    the canonical of that report's task is rebuilt when a lane report is newer. Never refuses."""
    from lib import obligation
    agent_id = payload.get("agent_id")
    if not agent_id:
        return []
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    resolved = obligation.resolve_own_obligation(
        session_id=payload.get("session_id") or payload.get("sessionId"), agent_id=agent_id,
        project_dir=project_dir, payload_agent_transcript_path=payload.get("agent_transcript_path"),
        expected_role="dev")
    ob = getattr(resolved, "obligation", None)
    if not isinstance(ob, dict) or len(ob.get("lane_set") or []) < 2:
        return []
    tasks = {aggregator().task_of_lane_report(os.path.basename(str(a.get("path", ""))), str(ob.get("lane") or ""))
             for a in ob.get("artifacts", []) if isinstance(a, dict)} - {None}
    for task_id in sorted(tasks):
        aggregator().rebuild_if_stale(project_dir, task_id, timeout=LANE_STOP_TIMEOUT_S)
    return []
