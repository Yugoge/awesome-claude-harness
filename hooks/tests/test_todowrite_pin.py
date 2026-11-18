"""T1 (design A): the harness keeps TodoWrite, so both CLI switches that pick it are pinned.

settings.json's env carries CLAUDE_CODE_ENABLE_TASKS=false and CLAUDE_CODE_ENABLE_TODO_TOOLS=1; the
CLI offers TodoWrite only while the first reads false and the second true. A session where the
first is anything else has the Task tools instead: SessionStart (hooks/session-info.sh) says so in
one warning line, and the Stop gate names it as a gap (test_stop_command_gate.py, test_a11_task_tools_*).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WARNING = "WARNING: CLAUDE_CODE_ENABLE_TASKS is"


def test_settings_pins_both_switches():
    env = json.loads((ROOT / "settings.json").read_text(encoding="utf-8"))["env"]
    assert env["CLAUDE_CODE_ENABLE_TASKS"] == "false"
    assert env["CLAUDE_CODE_ENABLE_TODO_TOOLS"] == "1"


def test_session_info_is_registered_at_session_start():
    hooks = json.loads((ROOT / "settings.json").read_text(encoding="utf-8"))["hooks"]["SessionStart"]
    assert any("hooks/session-info.sh" in h["command"] for entry in hooks for h in entry["hooks"])


def _session_info(tmp_path: Path, value: str | None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")}
    (tmp_path / "home").mkdir(exist_ok=True)
    (tmp_path / "state").mkdir(exist_ok=True)
    env.update(HOME=str(tmp_path / "home"), CLAUDE_STATE_DIR=str(tmp_path / "state"))
    if value is not None:
        env["CLAUDE_CODE_ENABLE_TASKS"] = value
    return subprocess.run(["bash", str(ROOT / "hooks" / "session-info.sh")], input="{}", capture_output=True,
                          text=True, env=env, cwd=tmp_path, timeout=60)


@pytest.mark.parametrize("value", [None, "", "1", "true", "garbage", "fal se"])
def test_session_start_warns_once_when_tasks_not_false(tmp_path, value):
    p = _session_info(tmp_path, value)
    assert p.returncode == 0 and p.stderr == ""
    assert p.stdout.startswith("Session info:\n")
    lines = [line for line in p.stdout.splitlines() if line.startswith(WARNING)]
    assert len(lines) == 1 and "not false" in lines[0]
    assert p.stdout.count("CLAUDE_CODE_ENABLE_TASKS") == 1


@pytest.mark.parametrize("value", ["false", "0", " FALSE ", "no", "off"])
def test_session_start_is_silent_when_tasks_false(tmp_path, value):
    p = _session_info(tmp_path, value)
    assert p.returncode == 0 and p.stderr == "" and "CLAUDE_CODE_ENABLE_TASKS" not in p.stdout
