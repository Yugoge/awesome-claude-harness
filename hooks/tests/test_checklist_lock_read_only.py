"""The checklist-not-started lock lets read-only tools through (OB-L39).

pretool-workflow-gate.py holds every tool but TodoWrite/TodoRead while the
active span is a checklist command's and holds no ok TodoWrite yet. Read, Grep
and Glob change nothing, so they pass that lock: after `/dev` before the first
TodoWrite (search-04), and after an abandoned `/test` span that a plain prompt
continues (WF-ABANDONED-SPAN). Every other tool stays held, Bash included, and
the Stop gate still requires the checklist (test_stop_command_gate.py,
test_ob_l39_stop_still_requires_the_checklist_after_read_only_calls).

Each hook runs as the CLI runs it: its own call is already in the transcript,
with no tool_result yet. HOME is the per-test scratch home of conftest.py.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
SID = "sess-ob-l39"

READ_ONLY = [
    ("Read", {"file_path": "toy/__init__.py"}),
    ("Grep", {"pattern": "def"}),
    ("Glob", {"pattern": "**/*.py"}),
]
STILL_HELD = [
    ("Write", {"file_path": "toy/new.py", "content": "x = 1\n"}),
    ("Edit", {"file_path": "toy/__init__.py", "old_string": "a", "new_string": "b"}),
    ("Agent", {"subagent_type": "dev", "prompt": "x", "description": "x"}),
    ("Bash", {"command": "ls"}),
    ("Bash", {"command": "cat toy/__init__.py"}),
]


class _Session:
    def __init__(self, tmp_path):
        self.project = tmp_path / "project"
        (self.project / ".claude").mkdir(parents=True)
        (self.project / "toy").mkdir()
        (self.project / "toy" / "__init__.py").write_text("a = 1\n")
        self.path = tmp_path / "transcript.jsonl"
        self.path.write_text("")
        self.ids = 0

    def add(self, record):
        with self.path.open("a") as handle:
            handle.write(json.dumps(record) + "\n")

    def prompt(self, text):
        self.add({"type": "user", "message": {"role": "user", "content": text}})

    def gate(self, tool_name, tool_input):
        """The workflow gate on a call the CLI has recorded (tool_use, no result yet)."""
        self.ids += 1
        tid = f"toolu_{self.ids:04d}"
        self.add({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tid, "name": tool_name, "input": tool_input}]}})
        payload = {"session_id": SID, "transcript_path": str(self.path),
                   "hook_event_name": "PreToolUse", "tool_name": tool_name,
                   "tool_input": tool_input, "tool_use_id": tid}
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.project), "PYTHONDONTWRITEBYTECODE": "1"}
        env.pop("CLAUDE_COMPAT_RUNTIME", None)
        done = subprocess.run([sys.executable, str(HOOKS / "pretool-workflow-gate.py")],
                              input=json.dumps(payload), capture_output=True, text=True,
                              env=env, cwd=self.project, timeout=60)
        self.add({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tid, "content": "ok",
             **({"is_error": True} if done.returncode == 2 else {})}]}})
        return done


@pytest.fixture
def s(tmp_path):
    return _Session(tmp_path)


def _abandoned_test_span(s):
    s.prompt("/test toy")
    s.prompt("never mind the tests; what does toy/__init__.py define?")


@pytest.mark.parametrize("tool_name,tool_input", READ_ONLY, ids=[t for t, _ in READ_ONLY])
def test_read_only_tools_pass_after_dev_before_the_first_todowrite(s, tool_name, tool_input):
    s.prompt("/dev fix the bug")
    done = s.gate(tool_name, tool_input)
    assert done.returncode == 0, done.stderr
    assert "CHECKLIST NOT STARTED" not in done.stderr


def test_read_passes_after_an_abandoned_test_span_and_a_plain_prompt(s):
    _abandoned_test_span(s)
    done = s.gate("Read", {"file_path": "toy/__init__.py"})
    assert done.returncode == 0, done.stderr
    assert "CHECKLIST NOT STARTED" not in done.stderr


@pytest.mark.parametrize("tool_name,tool_input", STILL_HELD,
                         ids=[f"{t}-{i}" for i, (t, _) in enumerate(STILL_HELD)])
def test_other_tools_stay_held_after_dev_before_the_first_todowrite(s, tool_name, tool_input):
    s.prompt("/dev fix the bug")
    held = s.gate(tool_name, tool_input)
    assert held.returncode == 2
    assert "CHECKLIST NOT STARTED: /dev workflow is active." in held.stderr


@pytest.mark.parametrize("tool_name,tool_input", STILL_HELD,
                         ids=[f"{t}-{i}" for i, (t, _) in enumerate(STILL_HELD)])
def test_other_tools_stay_held_after_an_abandoned_test_span(s, tool_name, tool_input):
    _abandoned_test_span(s)
    held = s.gate(tool_name, tool_input)
    assert held.returncode == 2
    assert "CHECKLIST NOT STARTED: /test workflow is active." in held.stderr


def test_read_only_calls_do_not_start_the_checklist(s):
    """Reads that passed the lock leave it closed: the next write or Bash is still held."""
    s.prompt("/dev fix the bug")
    for name, args in READ_ONLY:
        assert s.gate(name, args).returncode == 0
    for name, args in STILL_HELD:
        held = s.gate(name, args)
        assert held.returncode == 2, name
        assert "CHECKLIST NOT STARTED: /dev workflow is active." in held.stderr
