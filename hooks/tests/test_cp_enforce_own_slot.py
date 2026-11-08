"""subagentstop-cp-enforce.py (CP_ENFORCE_MODE=block): a stopping agent is held only on its own
cp-state slot's pending checkpoints (P1c X6).

A /spec split leaves a running slot per role (agents/spec.md: spec-check.py check-in, then
checkpoints), and a dispatched agent registers its own slot on its cp-state Read (spec-check.py
register). The hook used to refuse any subagent's stop while any running slot of the project held a
pending checkpoint: the spec subagent's own stop, and a dev's stop beside the qa slot or the role's
primary slot /spec registered, waited on checkpoints no hook lets that agent mark, a dead end."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "subagentstop-cp-enforce.py"
SPEC = "20990101-000001"


def _slot(project: Path, name: str, agent_id: str, states: list) -> None:
    d = project / ".claude" / "specs" / SPEC
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps({
        "spec_id": SPEC, "agent_type": name.split("-")[2].split(".")[0], "agent_id": agent_id, "is_running": True,
        "checked_in_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checkpoints": [{"id": f"cp-{i:02d}", "state": s} for i, s in enumerate(states, 1)]}))


def _stop(project: Path, agent_id: str, mode: str = "block") -> subprocess.CompletedProcess:
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project), CP_ENFORCE_MODE=mode)
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"agent_id": agent_id}), env=env,
                          capture_output=True, text=True, timeout=30)


def test_own_pending_checkpoint_refuses_the_stop(tmp_path):
    _slot(tmp_path, "cp-state-dev-2.json", "a1", ["done", "pending"])
    r = _stop(tmp_path, "a1")
    assert r.returncode == 2 and "cp-state-dev-2.json" in r.stderr and "cp-02" in r.stderr


def test_another_agents_pending_checkpoints_do_not(tmp_path):
    _slot(tmp_path, "cp-state-dev.json", f"dev-{SPEC}", ["pending", "pending"])  # /spec's own registration
    _slot(tmp_path, "cp-state-qa.json", "a2", ["pending"])
    _slot(tmp_path, "cp-state-dev-2.json", "a1", ["done", "done"])
    assert _stop(tmp_path, "a1").returncode == 0
    assert _stop(tmp_path, "spec-subagent").returncode == 0


def test_advisory_by_default(tmp_path):
    _slot(tmp_path, "cp-state-dev-2.json", "a1", ["pending"])
    assert _stop(tmp_path, "a1", mode="").returncode == 0
