"""Gate 4 in a span whose command text is older than the harness's (train 2, P1b acceptance 17, D15).

The owner cannot stop his sessions: one that took up origin/master's /close before train 2 landed
keeps that text while the hooks and the checklist scripts become the train's. origin/master's
/close has three TodoSteps (1, 2, 3); the train's checklist has five (0, 1, 2, 3, 3b), so that
session marks each step in_progress one step late: close QA is dispatched, and comes back, while
Step 1 is in progress, and Step 2 goes in_progress after it. pretool-todo-validate.py reads the
text the session loaded (command_span.Span.body): for such a span the returned call counts as Gate 4
counted it before train 2 (with step ip in progress, for the first step of ip..ip+2 naming its
type that has no call yet), and a refusal reads as origin/master's. A span whose text is the
file's keeps P5's rule (a call after the step went in_progress; test_checklist_record.py), and in
either span a step whose call never came back is refused.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
ROOT = HOOKS.parent
SID = "sess-todo-in-flight"
TASK = "20261108-120000"
# A /close or /dev text other than the harness's: the one an in-flight session loaded.
OLD_TEXT = "# /{command}\n\nThe text this session took up before the update.\n\nARGUMENTS: {args}"


def _canonical(command):
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "todo" / f"{command}.py")],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def _at(steps, n):
    """``steps`` with step n in progress and the ones before it completed."""
    return [dict(s, status="completed" if i < n else "in_progress" if i == n else "pending")
            for i, s in enumerate(steps)]


def _i(steps, label):
    """The position of the step labelled ``label`` (``Step 9``, ``Step 4c``) in ``steps``."""
    return next(i for i, s in enumerate(steps) if s["content"].startswith(f"{label}:"))


def _done(steps, n):
    """The TodoWrite that completes step n and starts the next one."""
    out = _at(steps, n + 1) if n + 1 < len(steps) else _at(steps, n)
    out[n]["status"] = "completed"
    return out


def _current_text(command, args):
    """The isMeta body the CLI records for the harness's own commands/<command>.md."""
    lines = (ROOT / "commands" / f"{command}.md").read_text(encoding="utf-8").split("\n")
    if lines[0].strip() == "---":
        lines = lines[lines.index("---", 1) + 1:]
    text = "\n".join(lines)
    return text.replace("$ARGUMENTS", args) if "$ARGUMENTS" in text else f"{text}\n\nARGUMENTS: {args}"


class _Session:
    """A main-session transcript in the CLI's record shapes (uuid, parentUuid), each hook run as
    the CLI runs it: its own call is in the transcript, with no result yet."""

    def __init__(self, tmp_path):
        self.project = tmp_path / "project"
        (self.project / ".claude").mkdir(parents=True)
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.path = tmp_path / "transcript.jsonl"
        self.path.write_text("")
        self.n = 0
        self.steps = None

    def add(self, record):
        self.n += 1
        record = dict(record, uuid=f"uuid-{self.n:04d}", parentUuid=f"uuid-{self.n - 1:04d}" if self.n > 1 else None,
                      isSidechain=False, sessionId=SID)
        with self.path.open("a") as handle:
            handle.write(json.dumps(record) + "\n")

    def command(self, command, args, text):
        """A typed /command, then the isMeta record of the text the session loaded."""
        self.add({"type": "user", "message": {"role": "user", "content":
                  f"<command-message>{command} is running…</command-message>\n<command-name>/{command}</command-name>\n"
                  f"<command-args>{args}</command-args>"}})
        self.add({"type": "user", "isMeta": True, "message": {"role": "user", "content": [{"type": "text", "text": text}]}})
        self.steps = _canonical(command)

    def use(self, name, tool_input):
        tid = f"toolu_{self.n + 1:04d}"
        self.add({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tid, "name": name, "input": tool_input}]}})
        return tid

    def result(self, tid, error=False):
        block = {"type": "tool_result", "tool_use_id": tid, "content": "ok"}
        if error:
            block["is_error"] = True
        self.add({"type": "user", "message": {"role": "user", "content": [block]}})

    def todo(self, todos):
        """A TodoWrite as the CLI runs it: the validator's result (refused: an error result)."""
        tid = self.use("TodoWrite", {"todos": todos})
        payload = {"session_id": SID, "transcript_path": str(self.path), "hook_event_name": "PreToolUse",
                   "tool_name": "TodoWrite", "tool_input": {"todos": todos}, "tool_use_id": tid}
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.project), "HOME": str(self.home),
               "CLAUDE_CONFIG_DIR": str(self.home / ".claude"), "PYTHONDONTWRITEBYTECODE": "1"}
        pre = subprocess.run([sys.executable, str(HOOKS / "pretool-todo-validate.py")], input=json.dumps(payload),
                             capture_output=True, text=True, env=env, cwd=self.project, timeout=60, check=False)
        self.result(tid, error=pre.returncode == 2)
        return pre

    def agent(self, subagent_type, returned=True):
        tid = self.use("Agent", {"subagent_type": subagent_type, "prompt": "x", "description": "x"})
        if returned:
            self.result(tid)

    def walk(self, upto, calls=()):
        """The checklist's first list, then each step through ``upto`` started, each accepted; each
        step of ``calls`` (indexes) dispatches its canonical role while it is in progress."""
        assert self.todo(_at(self.steps, 0)).returncode == 0
        for n in range(upto):
            if n in calls:
                self.agent(self.steps[n]["subagent_call"]["subagent_type"])
            pre = self.todo(_done(self.steps, n))
            assert pre.returncode == 0, pre.stderr


@pytest.fixture
def s(tmp_path):
    return _Session(tmp_path)


def _close_one_step_late(s, text, qa=True, returned=True):
    """/close as origin/master's text paces the train's checklist: the inspectors while Step 0 is in
    progress, close QA while Step 1 is (Step 2 started only after it), then Step 2 completed."""
    s.command("close", TASK, text)
    assert [t["content"].split(":")[0] for t in s.steps] == ["Step 0", "Step 1", "Step 2", "Step 3", "Step 3b"]
    s.walk(0)
    for role in ("style-inspector", "cleanliness-inspector", "prompt-inspector"):
        s.agent(role)
    assert s.todo(_done(s.steps, 0)).returncode == 0  # its "Step 1 in_progress": the checklist's Step 0 done
    if qa:
        s.agent("qa", returned=returned)
    assert s.todo(_done(s.steps, 1)).returncode == 0  # its "Step 2 in_progress": Step 1 done, Step 2 started
    return s.todo(_done(s.steps, 2))  # its "Step 3 done": Step 2 (close QA) completed


def test_an_in_flight_close_completes_its_qa_step_with_the_qa_call_that_came_back(s):
    pre = _close_one_step_late(s, OLD_TEXT.format(command="close", args=TASK))
    assert pre.returncode == 0, pre.stderr


def test_the_same_close_on_the_harness_text_keeps_p5s_rule(s):
    """The span's text is the file's: the QA call came back before Step 2 went in_progress, so it
    does not count (P5 A18), with the train's wording."""
    pre = _close_one_step_late(s, _current_text("close", TASK))
    assert pre.returncode == 2
    assert pre.stderr.startswith('\nBLOCKED: Cannot complete "Step 2: Delegate close debate to QA subagent" '
                                 '(subagent role qa).\n'), pre.stderr
    assert "made after the step went in_progress, and none has come back" in pre.stderr


def test_an_in_flight_close_without_its_qa_call_is_refused_as_origin_master_refuses_it(s):
    pre = _close_one_step_late(s, OLD_TEXT.format(command="close", args=TASK), qa=False)
    assert pre.returncode == 2
    assert pre.stderr == ('\nBLOCKED: Cannot complete Step 2 ("Step 2: Delegate close debate to QA subagent").\n'
                          'This step requires a subagent call (qa) that has not been made.\n'
                          'Call the Agent tool first, then mark completed.\n\n')


def test_an_in_flight_close_whose_qa_call_never_came_back_is_refused(s):
    pre = _close_one_step_late(s, OLD_TEXT.format(command="close", args=TASK), returned=False)
    assert pre.returncode == 2
    assert pre.stderr.startswith('\nBLOCKED: Cannot complete Step 2 ("Step 2: Delegate close debate to QA subagent").\n')
    assert "Its qa call has not come back" in pre.stderr and "never replaced by a new call" in pre.stderr


def test_the_in_flight_dev_step_9_refusal_is_origin_masters(s):
    """origin/master's /dev Step 9 dispatches graphify only when its sentinel is there; completing
    the step without that call is refused with origin/master's text, which the base kit shows."""
    s.command("dev", "fix the bug", OLD_TEXT.format(command="dev", args="fix the bug"))
    nine = _i(s.steps, "Step 9")
    s.walk(nine, calls=tuple(_i(s.steps, label) for label in ("Step 4", "Step 4c", "Step 7")))  # BA, BA, QA
    pre = s.todo(_done(s.steps, nine))
    assert pre.returncode == 2
    assert pre.stderr == (f'\nBLOCKED: Cannot complete Step {nine} ("Step 9: Graphify enrichment: dispatch graphify '
                          'subagent (advisory)").\nThis step requires a subagent call (graphify) that has not been '
                          'made.\nCall the Agent tool first, then mark completed.\n\n')


def test_an_in_flight_call_counts_for_one_step_of_its_window_only(s):
    """In flight, a call counts for one step: QA's call for Step 7 does not complete Step 13 too, and a
    BA call made more than two steps before Step 4 does not count for it."""
    s.command("dev", "fix the bug", OLD_TEXT.format(command="dev", args="fix the bug"))
    i = {label: _i(s.steps, label) for label in ("Step 4", "Step 4c", "Step 5", "Step 7", "Step 8", "Step 9",
                                                   "Step 10", "Step 13")}
    s.walk(0)
    s.agent("ba")  # Step 1 in progress: Step 4 lies outside the window 1..3
    for n in range(3):
        assert s.todo(_done(s.steps, n)).returncode == 0
    assert s.todo(_done(s.steps, i["Step 4"])).returncode == 2  # Step 4 (BA)
    s.agent("ba")
    assert s.todo(_done(s.steps, i["Step 4"])).returncode == 0
    for n in range(i["Step 4"] + 1, i["Step 4c"]):  # Steps 4a and 4b: no subagent of their own
        assert s.todo(_done(s.steps, n)).returncode == 0
    assert s.todo(_done(s.steps, i["Step 4c"])).returncode == 2  # Step 4c (BA): Step 4's call is spent
    s.agent("ba")
    assert s.todo(_done(s.steps, i["Step 4c"])).returncode == 0
    for n in range(i["Step 5"], i["Step 7"]):
        assert s.todo(_done(s.steps, n)).returncode == 0
    s.agent("qa")  # Step 7 in progress
    assert s.todo(_done(s.steps, i["Step 7"])).returncode == 0
    s.todo(_done(s.steps, i["Step 8"]))
    s.agent("graphify")
    assert s.todo(_done(s.steps, i["Step 9"])).returncode == 0
    s.agent("dev")
    for n in range(i["Step 10"], i["Step 13"]):
        assert s.todo(_done(s.steps, n)).returncode == 0, n
    pre = s.todo(_done(s.steps, i["Step 13"]))  # Step 13 (QA): Step 7's call is spent
    assert pre.returncode == 2 and f'Cannot complete Step {i["Step 13"]} ("Step 13: Delegate to QA subagent")' in pre.stderr
    s.agent("qa")
    assert s.todo(_done(s.steps, i["Step 13"])).returncode == 0
