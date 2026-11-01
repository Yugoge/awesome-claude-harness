"""hooks/subagentstop-cp-enforce.py: the producer's own pending checkpoints block its stop (P9 E4).

Armed as shipped (settings.json's env sets CP_ENFORCE_MODE=block), the hook blocks
a stopping subagent only for its own running cp-state slot (the agent_id
pretool-cp-checkin.py recorded when it Read the file) that still has a pending
checkpoint. A slot another agent holds, such as the slots the /spec subagent's
Phase 2 registers for agents not yet dispatched, never blocks a bystander's stop;
any other mode is advisory.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "subagentstop-cp-enforce.py"
SPEC = "20990101-000001"


def _slot(project: Path, role: str, owner: str, states: list[str], running: bool = True) -> None:
    d = project / ".claude" / "specs" / SPEC
    d.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (d / f"cp-state-{role}.json").write_text(json.dumps({
        "spec_id": SPEC, "agent_type": role, "agent_id": owner, "is_running": running,
        "checked_in_at": now, "checked_out_at": None,
        "checkpoints": [{"id": f"cp-{i:02d}", "state": s} for i, s in enumerate(states, 1)],
    }), encoding="utf-8")


def _stop(project: Path, agent_id: str | None, mode: str | None = "block"):
    env = {k: v for k, v in os.environ.items() if k != "CP_ENFORCE_MODE"}
    env.update(CLAUDE_PROJECT_DIR=str(project), PYTHONDONTWRITEBYTECODE="1")
    if mode is not None:
        env["CP_ENFORCE_MODE"] = mode
    payload = {"session_id": "s", "hook_event_name": "SubagentStop"}
    if agent_id:
        payload["agent_id"] = agent_id
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, timeout=60)


def test_own_pending_checkpoint_blocks_the_producer(tmp_path):
    _slot(tmp_path, "dev", "agent-dev", ["done", "pending"])
    r = _stop(tmp_path, "agent-dev")
    assert r.returncode == 2
    assert '"pending": ["cp-02"]' in r.stderr


def test_another_agents_pending_slot_never_blocks_a_bystander(tmp_path):
    # The /spec subagent's Phase 2 registration: dev and qa slots running under ids
    # no dispatched agent holds; the spec subagent and the split QA stop past them.
    _slot(tmp_path, "dev", "dev-20990101-000001", ["pending", "pending"])
    _slot(tmp_path, "qa", "qa-20990101-000001", ["pending"])
    assert _stop(tmp_path, "agent-spec").returncode == 0
    assert _stop(tmp_path, "agent-split-qa").returncode == 0


def test_marked_or_waived_slot_lets_the_producer_stop(tmp_path):
    _slot(tmp_path, "qa", "agent-qa", ["done", "waived"])
    assert _stop(tmp_path, "agent-qa").returncode == 0


def test_main_agent_stop_and_advisory_mode_never_block(tmp_path):
    _slot(tmp_path, "dev", "agent-dev", ["pending"])
    assert _stop(tmp_path, None).returncode == 0
    assert _stop(tmp_path, "agent-dev", mode=None).returncode == 0
    assert _stop(tmp_path, "agent-dev", mode="advisory").returncode == 0


def test_shipped_settings_arm_the_hook():
    env = json.loads((REPO / "settings.json").read_text(encoding="utf-8"))["env"]
    assert env.get("CP_ENFORCE_MODE") == "block"
