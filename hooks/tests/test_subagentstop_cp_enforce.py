"""hooks/subagentstop-cp-enforce.py: the producer's own pending checkpoints block its stop (P9 E4).

Armed as shipped (settings.json's env sets CP_ENFORCE_MODE=block), the hook blocks
a stopping subagent only for its own running cp-state slot (the CLI agent_id
pretool-cp-checkin.py binds to the slot file the agent Read) that still has a
pending checkpoint. A slot another agent holds, or one the /spec subagent's Phase 2
set for an agent not yet dispatched (left idle), never blocks a bystander's stop;
any other mode is advisory. The last test plays /spec + /dev with CLI-shaped ids.
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
CHECKIN = REPO / "hooks" / "pretool-cp-checkin.py"
SPEC_CHECK = REPO / "scripts" / "spec-check.py"
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


def _env(project: Path, mode: str | None = "block") -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("CP_ENFORCE_MODE", "CLAUDE_AGENT_ID")}
    env.update(CLAUDE_PROJECT_DIR=str(project), PYTHONDONTWRITEBYTECODE="1")
    if mode is not None:
        env["CP_ENFORCE_MODE"] = mode
    return env


def _stop(project: Path, agent_id: str | None, mode: str | None = "block", agent_type: str | None = None):
    payload = {"session_id": "s", "hook_event_name": "SubagentStop", "stop_hook_active": False}
    if agent_id:
        payload.update(agent_id=agent_id, agent_type=agent_type or "dev")
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                          capture_output=True, text=True, env=_env(project, mode), timeout=60)


def test_own_pending_checkpoint_blocks_the_producer(tmp_path):
    _slot(tmp_path, "dev", "agent-dev", ["done", "pending"])
    r = _stop(tmp_path, "agent-dev")
    assert r.returncode == 2
    assert '"pending": ["cp-02"]' in r.stderr


def test_another_agents_pending_slot_never_blocks_a_bystander(tmp_path):
    # Slots running under ids no stopping agent holds; the spec subagent and the split QA stop past them.
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


def _spec_check(project: Path, *args: str) -> str:
    r = subprocess.run([sys.executable, str(SPEC_CHECK), *args], capture_output=True, text=True,
                       env=_env(project), timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _second_action_read(project: Path, agent_id: str, role: str, read_role: str | None = None) -> str:
    """A dispatched subagent's Read of cp-state-<role>.json; returns the agent_id the file shows."""
    path = project / ".claude" / "specs" / SPEC / f"cp-state-{read_role or role}.json"
    payload = {"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": "Read",
               "tool_input": {"file_path": str(path)}, "agent_id": agent_id, "agent_type": role}
    subprocess.run([sys.executable, str(CHECKIN)], input=json.dumps(payload), capture_output=True,
                   text=True, env=_env(project), timeout=60, check=True)
    return json.loads(path.read_text(encoding="utf-8"))["agent_id"]


def _mark(project: Path, role: str, shown: str, *cps: str) -> None:
    for cp in cps:
        _spec_check(project, "mark", "--spec-id", SPEC, "--agent", role, "--agent-id", shown, "--cp-id", cp)


def test_spec_and_dev_with_cli_ids_block_only_a_pending_producer(tmp_path):
    """P9 F-E4, following agents/spec.md Phase 2 and checkpoint-marking.md literally with
    CLI-shaped ids: Phase 2 passes the spec subagent's own id; each dispatched agent marks
    with the id the file it Read shows."""
    spec_agent = "a0000000000000001"
    for role in ("dev", "qa"):
        _spec_check(tmp_path, "check-in", "--spec-id", SPEC, "--agent", role, "--agent-id", spec_agent)
        _spec_check(tmp_path, "checkpoints", "--spec-id", SPEC, "--agent", role, "--agent-id", spec_agent,
                    "--action", "Do one", "--action", "Do two")
    assert _second_action_read(tmp_path, spec_agent, "spec", read_role="dev") == spec_agent  # binds nothing
    assert _stop(tmp_path, spec_agent, agent_type="spec").returncode == 0
    # Two parallel dev lanes, then QA: each file shows its reader's own id; marking clears every stop.
    lanes = ["a00000000000000d1", "a00000000000000d2"]
    shown = [_second_action_read(tmp_path, lane, "dev") for lane in lanes]
    assert shown == lanes
    _mark(tmp_path, "dev", shown[0], "cp-01", "cp-02")
    _mark(tmp_path, "dev", shown[1], "cp-01")
    assert _stop(tmp_path, lanes[0]).returncode == 0
    blocked = _stop(tmp_path, lanes[1])
    assert blocked.returncode == 2 and '"pending": ["cp-02"]' in blocked.stderr and lanes[1] in blocked.stderr
    _mark(tmp_path, "dev", shown[1], "cp-02")
    assert _stop(tmp_path, lanes[1]).returncode == 0
    qa = "a00000000000000q1"
    _mark(tmp_path, "qa", _second_action_read(tmp_path, qa, "qa"), "cp-01", "cp-02")
    assert _stop(tmp_path, qa, agent_type="qa").returncode == 0
