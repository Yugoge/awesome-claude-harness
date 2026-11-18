"""T2-10: a subagent reading its own role's sentinel writes its agent-index entry.

cc3077f1's rule in hooks/pretool-cp-checkin.py (_handle_dev_sentinel): a PreToolUse
Read of <project>/.claude/dev-registry/<sid>/<role>.json whose payload carries an
agent_id and names the sentinel's own role as agent_type (every payload of the current
CLI carries agent_type) writes agent-index.json[agent_id] = {"agent_type": <role>,
"dev_session_id": <sid>}. P6-30 (D18) kept that rule over R2's "only without
agent_type": the entry is the cycle of a dispatch with no obligation, which
lib/agent_cycle.py's registry_dir(payload, {}, project) reads.

The neighbouring cases stay where they are: a payload without agent_type
(test_cp_checkin.py's AC3) and one naming another role (test_role_from_cli.py's A3).

The hook runs as a process against a scratch project and HOME, as /dev arms the cycle
(the registry directory exists, the sentinel does not until the Read asks for it).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "pretool-cp-checkin.py"
SID = "dev-20261109-000000"
SESSION = "t2-10-session"

sys.path.insert(0, str(ROOT))
from hooks.lib import agent_cycle  # noqa: E402


def _env(tmp_path: Path, project: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update({"HOME": str(tmp_path / "home"), "CLAUDE_CONFIG_DIR": str(tmp_path / "home" / ".claude"),
                "CLAUDE_STATE_DIR": str(tmp_path / "state"), "CLAUDE_PROJECT_DIR": str(project),
                "PYTHONDONTWRITEBYTECODE": "1"})
    return env


def _read_sentinel(tmp_path: Path, project: Path, sentinel: Path, agent: dict) -> subprocess.CompletedProcess:
    payload = {"session_id": SESSION, "hook_event_name": "PreToolUse", "cwd": str(project),
               "tool_name": "Read", "tool_input": {"file_path": str(sentinel)}, **agent}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                          text=True, cwd=str(tmp_path), env=_env(tmp_path, project), timeout=60)


@pytest.fixture
def project(tmp_path) -> Path:
    path = tmp_path / "toyproj"
    (path / ".claude" / "dev-registry" / SID).mkdir(parents=True)
    return path


@pytest.mark.parametrize("role", ["dev", "qa"])
def test_own_role_sentinel_read_writes_the_index_entry_and_names_the_cycle(tmp_path, project, role):
    agent_id = f"a-{role}-own"
    agent = {"agent_id": agent_id, "agent_type": role}
    sentinel = project / ".claude" / "dev-registry" / SID / f"{role}.json"

    read = _read_sentinel(tmp_path, project, sentinel, agent)
    assert read.returncode == 0, read.stderr
    assert "Traceback" not in read.stderr, read.stderr
    assert sentinel.is_file(), "the hook creates the sentinel the read asks for"

    index = project / ".claude" / "dev-registry" / "agent-index.json"
    assert index.is_file(), "a Read of the payload role's own sentinel writes agent-index.json"
    assert json.loads(index.read_text(encoding="utf-8")).get(agent_id) == {
        "agent_type": role, "dev_session_id": SID}

    cycle = agent_cycle.registry_dir({"session_id": SESSION, **agent}, {}, str(project))
    assert cycle is not None and cycle.name == SID, cycle
