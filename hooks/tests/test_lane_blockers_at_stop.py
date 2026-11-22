"""A dev lane's blocking issues at its own stop (hooks/subagentstop-lane-blockers.py, in the producer gate).

- a non-empty list holds the stop once, with the list shown;
- the next stop of the same dispatch passes with what remains;
- an empty list is never held;
- a lane resumed by a new dispatch (a coordinator's message) gets one hold again.
Run with: python3 -m pytest hooks/tests/test_lane_blockers_at_stop.py -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
RULE = HOOKS / "subagentstop-lane-blockers.py"
GATE = HOOKS / "subagentstop-producer-gate.py"
MARK = "LANE_BLOCKERS_HOLD"
SESSION, AGENT, TASK = "sess-1", "alane01", "20990101-000000"
REPORT = f"docs/dev/dev-report-{TASK}.json"
OBLIGATION = {"task_id": TASK, "role": "dev", "pipeline": "dev", "profile": "singular",
              "artifacts": [{"kind": "json", "path": REPORT, "schema": "dev-report.v2", "identity": {"task_id": TASK}}]}
PROMPT = f'Do the lane.\n<obligation v="1">{json.dumps(OBLIGATION)}</obligation>'


@pytest.fixture
def lane(tmp_path):
    project, store = tmp_path / "project", tmp_path / "store" / "proj"
    (project / "docs" / "dev").mkdir(parents=True)
    (store / SESSION / "subagents").mkdir(parents=True)
    (tmp_path / "home").mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "CP_ENFORCE"))}
    env.update(HOME=str(tmp_path / "home"), TMPDIR=str(tmp_path), CLAUDE_STATE_DIR=str(tmp_path / "state"),
               CLAUDE_CONFIG_DIR=str(tmp_path / "home"), XDG_STATE_HOME=str(tmp_path / "xdg"),
               CLAUDE_PROJECT_DIR=str(project))
    transcript = store / SESSION / "subagents" / f"agent-{AGENT}.jsonl"
    parent = store / f"{SESSION}.jsonl"
    parent.write_text("")
    _append(transcript, {"type": "user", "message": {"role": "user", "content": PROMPT}})

    class Lane:
        def report(self, blockers):
            (project / REPORT).write_text(json.dumps({"task_id": TASK, "blocking_issues": blockers}))

        def stop(self, script=RULE):
            payload = {"session_id": SESSION, "hook_event_name": "SubagentStop", "agent_id": AGENT,
                       "agent_type": "dev", "agent_transcript_path": str(transcript), "stop_hook_active": False,
                       "last_assistant_message": "done"}
            proc = subprocess.run([sys.executable, str(script)], input=json.dumps(payload), capture_output=True,
                                  text=True, env=env, timeout=120)
            if proc.returncode == 2:  # the CLI shows the agent the hold as a stop-hook feedback record
                _append(transcript, {"type": "user", "isMeta": True,
                                     "message": {"role": "user", "content": f"Stop hook feedback:\n{proc.stderr}"}})
            return proc

        def resume(self, message):
            _append(parent, {"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "SendMessage", "input": {"to": AGENT, "message": message}}]}})
            _append(transcript, {"type": "user", "origin": {"kind": "coordinator"}, "message": {
                "role": "user", "content": f"The coordinator sent a message while you were working:\n{message}"}})

    return Lane()


def _append(path: Path, record: dict) -> None:
    with path.open("a") as handle:
        handle.write(json.dumps(record) + "\n")


def test_a_non_empty_list_is_held_once_with_the_list_shown(lane):
    lane.report(["needs the owner's decision on X", {"id": 2, "what": "already fixed"}])
    first = lane.stop()
    assert first.returncode == 2, first.stderr
    assert MARK in first.stderr and "2 blocking issue(s)" in first.stderr
    assert "needs the owner's decision on X" in first.stderr and "already fixed" in first.stderr
    assert "resolved or only informational" in first.stderr


def test_the_next_stop_of_the_dispatch_passes_with_what_remains(lane):
    lane.report(["needs the owner's decision on X"])
    assert lane.stop().returncode == 2
    second = lane.stop()
    assert (second.returncode, second.stderr) == (0, "")


def test_an_empty_list_is_not_held(lane):
    lane.report([])
    proc = lane.stop()
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


def test_a_lane_resumed_by_a_new_dispatch_is_held_once_again(lane):
    lane.report(["needs the owner's decision on X"])
    assert lane.stop().returncode == 2
    assert lane.stop().returncode == 0
    lane.resume("Continue the lane: one more fix.")  # restates no obligation: the first one stands
    assert lane.stop().returncode == 2
    assert lane.stop().returncode == 0


def test_the_producer_gate_holds_through_its_rule_once(lane):
    lane.report(["needs the owner's decision on X"])
    first = lane.stop(GATE)
    assert first.returncode == 2 and MARK in first.stderr, first.stderr
    assert MARK not in lane.stop(GATE).stderr
