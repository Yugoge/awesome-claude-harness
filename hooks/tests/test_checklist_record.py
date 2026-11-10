"""The checklist hooks read the record, not a copy (P1b E7).

Every TodoWrite and Agent call the CLI ran is in the session transcript, so the
workflow gate, the TodoWrite validator, the progress tracker and the step the
dispatch check uses are read from it (lib.todo_canonical.checklist over
lib.command_span); none of them writes the workflow bookmark or the CLI's todo
file. Each hook runs as the CLI runs it: its own call is already in the
transcript (T1), with its tool_result before PostToolUse. pretool-todo-validate.py
is the TodoWrite rules' one decider (P5 R18, R19): a list that breaks one never
runs, so the PostToolUse TodoWrite group holds only the tracker and the overnight
loop.
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
            post = [self.hook("posttool-todo-tracker.py", "PostToolUse", "TodoWrite", {"todos": todos}, tid)]
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
    progress = json.loads(post[0].stdout)["hookSpecificOutput"]  # the model's channel at PostToolUse
    assert progress["hookEventName"] == "PostToolUse"
    assert progress["additionalContext"].startswith("WORKFLOW PROGRESS (/dev)")
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


def test_a_first_list_with_an_item_completed_is_refused_before_it_runs(s):
    """A18: a first list with an item completed is blocked (the first-call rule, P5 R18)."""
    s.command("/dev fix the bug")
    skipped = _frontier(1)  # Step 1 completed in the very first list
    pre, post = s.todo(skipped)
    assert pre.returncode == 2 and post is None
    assert "Initial TodoWrite cannot have completed steps" in pre.stderr
    assert "Call TodoWrite with:" in pre.stderr  # the canonical first call, Step 0 in progress
    held = s.gate()
    assert held.returncode == 2 and "CHECKLIST NOT STARTED" in held.stderr
    # Sending it again is still a first call: still refused.
    assert s.todo(skipped)[0].returncode == 2
    second = _frontier(0)
    second[0]["status"], second[1]["status"] = "pending", "in_progress"  # in progress past Step 0
    assert s.todo(second)[0].returncode == 2
    pre, post = s.todo(_frontier(0))
    assert pre.returncode == 0 and post[0].returncode == 0 and s.gate().returncode == 0


def test_a_short_first_list_is_refused_with_no_bookmark(s):
    """A18: a 5-of-20 list is refused by pretool-todo-validate.py, which reads no bookmark."""
    s.command("/dev fix the bug")
    pre, _ = s.todo(_frontier(0)[:5])
    assert pre.returncode == 2 and "Todo count mismatch: canonical has 20, submitted has 5" in pre.stderr
    assert s.gate().returncode == 2
    assert list((s.project / ".claude").iterdir()) == []


def test_a_two_step_skip_is_refused_with_no_bookmark(s):
    """A18: completing two steps in one call (a 2-step skip) is refused before it runs."""
    s.command("/dev fix the bug")
    s.todo(_frontier(0))
    skip = _frontier(2)  # Steps 1 and 2 completed at once, Step 3 in progress
    pre, post = s.todo(skip)
    assert pre.returncode == 2 and post is None
    assert "Completed 2 steps in one call (max 1)" in pre.stderr
    assert todo_canonical.checklist(str(s.path)).todos == _frontier(0)
    assert list((s.project / ".claude").iterdir()) == []


def test_the_in_flight_todowrite_is_compared_with_the_previous_ok_call(s):
    """A18: the hook's own call is already the last TodoWrite of the record, with no result yet;
    the list it is checked against is the previous ok call's, a refused one in between left out."""
    s.command("/dev fix the bug")
    s.todo(_frontier(0))
    assert s.todo(_frontier(2))[0].returncode == 2  # refused: an error result, not a previous list
    pending = s.use("TodoWrite", {"todos": _frontier(1)})  # in flight, the newest TodoWrite record
    pre = s.hook("pretool-todo-validate.py", "PreToolUse", "TodoWrite", {"todos": _frontier(1)}, pending)
    assert pre.returncode == 0, pre.stderr
    s.result(pending)
    assert todo_canonical.checklist(str(s.path)).todos == _frontier(1)


def test_a_list_the_step_rules_refuse_never_runs(s):
    """P1c X6 (the proof of the class-U sites deleted from posttool-todo-count.py and
    posttool-todo-sequence.py): a list shorter than the canonical one, one off the canonical
    content, or one breaking a step rule against the accepted list is refused at PreToolUse,
    as a first call and later, so no PostToolUse hook ever sees it."""
    s.command("/dev fix the bug")
    tampered = _frontier(0)
    tampered[1]["content"] += " (mine)"
    for todos in (_frontier(0)[:-1], tampered):
        pre, post = s.todo(todos)
        assert pre.returncode == 2 and post is None
    s.todo(_frontier(0))
    tampered = _frontier(1)
    tampered[3]["activeForm"] += " (mine)"
    for todos in (_frontier(1)[:-1], _frontier(2), tampered):
        pre, post = s.todo(todos)
        assert pre.returncode == 2 and post is None


def test_sequence_check_compares_with_the_list_before_its_own_call(s):
    s.command("/dev fix the bug")
    s.todo(_frontier(0))
    pre, post = s.todo(_frontier(1))
    assert pre.returncode == 0 and post[0].returncode == 0
    state = todo_canonical.checklist(str(s.path))
    assert state.todos == _frontier(1) and state.lock == ""


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


def test_a_dispatch_before_the_step_went_in_progress_does_not_count(s):
    """A18 (Gate 4): completing a subagent step needs a matching ok Agent call after the TodoWrite
    that set it in_progress; a BA call made while the step before it was in progress does not."""
    s.command("/dev fix the bug")
    for n in range(3):
        s.todo(_frontier(n))
    s.agent("ba")  # Step 3 in progress, BA's Step 4 still pending
    s.todo(_frontier(3))  # Step 4 (BA) in progress
    pre, _ = s.todo(_frontier(4))
    assert pre.returncode == 2 and "requires a subagent call (ba) made after the step went in_progress" in pre.stderr
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


@pytest.mark.parametrize("name", ["posttool-todo-sequence.py", "posttool-todo-count.py"])
def test_the_retired_todo_hooks_are_unregistered_exit_0_stubs(name):
    """P5 R19: both leave the PostToolUse TodoWrite group and stay as tracked stubs (a running
    session keeps the hook list it loaded); their rules are pretool-todo-validate.py's."""
    text = (HOOKS / name).read_text()
    assert sum(line.startswith("# STUB:") for line in text.splitlines()) == 1
    assert name not in (HOOKS.parent / "settings.json").read_text()
    for payload in ("", json.dumps({"tool_name": "TodoWrite", "tool_input": {"todos": _frontier(1)}})):
        p = subprocess.run([sys.executable, str(HOOKS / name)], input=payload, capture_output=True, text=True,
                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=60)
        assert (p.returncode, p.stdout, p.stderr) == (0, "", "")
