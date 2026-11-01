"""The checklist hooks read the record, not a copy (P1b E7).

Every TodoWrite and Agent call the CLI ran is in the session transcript, so the
workflow gate, the TodoWrite validators, the progress tracker and the step the
dispatch check uses are read from it (lib.todo_canonical.checklist over
lib.command_span); none of them writes the workflow bookmark or the CLI's todo
file. Each hook runs as the CLI runs it: its own call is already in the
transcript (T1), with its tool_result before PostToolUse.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOOKS.parent))
from hooks.lib import todo_canonical  # noqa: E402

SID = "sess-checklist-record"


def _canonical(command="dev"):
    out = subprocess.run([sys.executable, str(HOOKS.parent / "scripts" / "todo" / f"{command}.py")],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def _frontier(n, done=False, command="dev"):
    """The canonical list with step n in progress (or completed, with done)."""
    out = _canonical(command)
    for i, item in enumerate(out):
        item["status"] = "completed" if i < n or (done and i == n) else (
            "in_progress" if i == n else "pending")
    return out


class _Session:
    def __init__(self, tmp_path):
        self.project = tmp_path / "project"
        (self.project / ".claude").mkdir(parents=True)
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.path = tmp_path / "transcript.jsonl"
        self.path.write_text("")
        self.ids = 0

    def add(self, record):
        with self.path.open("a") as handle:
            handle.write(json.dumps(record) + "\n")

    def command(self, text):
        self.add({"type": "user", "message": {"role": "user", "content": text}})

    def use(self, name, tool_input):
        self.ids += 1
        tid = f"toolu_{self.ids:04d}"
        self.add({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tid, "name": name, "input": tool_input}]}})
        return tid

    def result(self, tid, error=False):
        block = {"type": "tool_result", "tool_use_id": tid, "content": "ok"}
        if error:
            block["is_error"] = True
        self.add({"type": "user", "message": {"role": "user", "content": [block]}})

    def hook(self, name, event, tool_name, tool_input, tid=None):
        payload = {"session_id": SID, "transcript_path": str(self.path), "hook_event_name": event,
                   "tool_name": tool_name, "tool_input": tool_input}
        if tid:
            payload["tool_use_id"] = tid
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.project), "HOME": str(self.home),
               "CLAUDE_CONFIG_DIR": str(self.home / ".claude"), "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run([sys.executable, str(HOOKS / name)], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, cwd=self.project, timeout=60)

    def todo(self, todos):
        """A TodoWrite as the CLI runs it; returns (pre, post) results of the validators."""
        tid = self.use("TodoWrite", {"todos": todos})
        pre = self.hook("pretool-todo-validate.py", "PreToolUse", "TodoWrite", {"todos": todos}, tid)
        self.result(tid, error=pre.returncode == 2)
        post = None
        if pre.returncode != 2:
            post = [self.hook(h, "PostToolUse", "TodoWrite", {"todos": todos}, tid)
                    for h in ("posttool-todo-tracker.py", "posttool-todo-count.py",
                              "posttool-todo-sequence.py")]
        return pre, post

    def agent(self, subagent_type):
        tid = self.use("Agent", {"subagent_type": subagent_type, "prompt": "x", "description": "x"})
        self.result(tid)

    def gate(self):
        return self.hook("pretool-workflow-gate.py", "PreToolUse", "Bash", {"command": "ls"})


@pytest.fixture
def s(tmp_path):
    return _Session(tmp_path)


def test_no_checklist_without_a_command_that_has_one(s):
    assert todo_canonical.checklist(str(s.path)) is None
    s.command("/commit")  # a harness command without a canonical checklist
    assert todo_canonical.checklist(str(s.path)) is None
    assert s.gate().returncode == 0


def test_gate_holds_tools_until_an_ok_todowrite_and_writes_nothing(s):
    s.command("/dev fix the bug")
    held = s.gate()
    assert held.returncode == 2 and "CHECKLIST NOT STARTED" in held.stderr
    pre, post = s.todo(_frontier(0))
    assert pre.returncode == 0 and all(p.returncode == 0 for p in post)
    assert "WORKFLOW PROGRESS (/dev)" in post[0].stdout
    assert s.gate().returncode == 0
    assert list((s.project / ".claude").iterdir()) == []
    assert not (s.home / ".claude").exists()


def test_a_refused_todowrite_does_not_start_the_checklist(s):
    s.command("/dev fix the bug")
    tampered = _frontier(0)
    tampered[0]["content"] += " (mine)"
    pre, _ = s.todo(tampered)
    assert pre.returncode == 2
    assert s.gate().returncode == 2


def test_a_first_list_that_breaks_the_first_call_rule_locks_until_a_valid_one(s):
    s.command("/dev fix the bug")
    skipped = _frontier(1)  # Step 1 completed in the very first list
    pre, post = s.todo(skipped)
    assert pre.returncode == 0 and post[2].returncode == 2
    locked = s.gate()
    assert locked.returncode == 2 and "STEP SKIPPING DETECTED" in locked.stderr
    # Sending it again is still a first call: still refused, still locked.
    _, post = s.todo(skipped)
    assert post[2].returncode == 2 and s.gate().returncode == 2
    _, post = s.todo(_frontier(0))
    assert all(p.returncode == 0 for p in post) and s.gate().returncode == 0


def test_sequence_check_compares_with_the_list_before_its_own_call(s):
    s.command("/dev fix the bug")
    s.todo(_frontier(0))
    pre, post = s.todo(_frontier(1))
    assert pre.returncode == 0 and post[2].returncode == 0
    state = todo_canonical.checklist(str(s.path))
    assert state.accepted == _frontier(1) and state.lock == ""


def test_a_subagent_step_completes_only_after_its_dispatch(s):
    s.command("/dev fix the bug")
    for n in range(4):
        s.todo(_frontier(n))
    # Step 4 (BA) is in progress: completing it without the BA dispatch is refused.
    pre, _ = s.todo(_frontier(4))
    assert pre.returncode == 2 and "requires a subagent call (ba)" in pre.stderr
    s.agent("qa")  # another role's dispatch does not count for it
    assert s.todo(_frontier(4))[0].returncode == 2
    s.agent("ba")
    assert s.todo(_frontier(4))[0].returncode == 0


def test_a_dispatch_counts_for_its_steps_current_run_only(s):
    """A step set back to pending (a new overnight cycle) needs a new dispatch."""
    s.command("/dev fix the bug")
    for n in range(4):
        s.todo(_frontier(n))
    s.agent("ba")
    assert s.todo(_frontier(4))[0].returncode == 0
    pending = _canonical()
    for item in pending:
        item["status"] = "pending"
    s.todo(pending)  # reset: Step 4 pending again
    for n in range(4):
        s.todo(_frontier(n))
    assert s.todo(_frontier(4))[0].returncode == 2


def test_spec_coverage_gate_holds_until_the_spec_checklist_is_done(s):
    """stop-spec-coverage-enforce.py checks the /spec span from its start until
    a TodoWrite with every step completed comes back, as it did while the
    tracker removed the bookmark at that point."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("stop_spec_coverage", HOOKS / "stop-spec-coverage-enforce.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    s.command("/spec an idea")
    assert hook.get_workflow_command(str(s.path)) == "spec"
    steps = _canonical("spec")
    s.todo(_frontier(0, command="spec"))
    assert hook.get_workflow_command(str(s.path)) == "spec"
    refused = s.use("TodoWrite", {"todos": [dict(t, status="completed") for t in steps]})
    s.result(refused, error=True)  # a refused list releases nothing
    assert hook.get_workflow_command(str(s.path)) == "spec"
    done = s.use("TodoWrite", {"todos": [dict(t, status="completed") for t in steps]})
    s.result(done)
    assert hook.get_workflow_command(str(s.path)) == ""
    s.todo(_frontier(0, command="spec"))  # still released for the rest of the span
    assert hook.get_workflow_command(str(s.path)) == ""
    s.command("/spec another idea")
    assert hook.get_workflow_command(str(s.path)) == "spec"
