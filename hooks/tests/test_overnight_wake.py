"""P1c row 17 (X8, F6o): the /dev-overnight session's wake, and the todo-list comparison rule.

The wake is one recurring CronCreate of lib/overnight.py's WAKE_PROMPT, scheduled at Step 0 and deleted
where the session ends (dev-overnight.md Step 21's session-ending branch, stop.md). Each hook runs as a
subprocess with a payload shaped as the CLI sends it, against a transcript in tmp_path; HOME,
CLAUDE_CONFIG_DIR, CLAUDE_STATE_DIR and CLAUDE_PROJECT_DIR are tmp_path's own.

* pretool-todo-validate.py completes Step 0 only after an ok recurring CronCreate of the wake's prompt in
  the span;
* userprompt-restart-authorize.py issues the /restart capability to the wake's text only inside an open
  /dev-overnight span, never after the owner's /stop, and to every prompt starting with /restart as before
  (X8: the hook cannot tell a scheduled prompt from a typed one);
* prompt-workflow.py hands over commands/restart.md's recovery for the wake inside that span only;
* the Stop gate's time-lock (stop-command-gate.py's step 4, P5) refuses a Stop after end_time, its closeout
  met, while the transcript's wake has no later CronDelete, naming the id, whatever span is active; a
  transcript with no wake meets nothing (P2's locator and window, faked from this base's own readers);
* past a command's first list and with the length unchanged, the hooks pair todos by content, never by
  index: a session that started with the list before Step 0 (one step shorter) keeps running.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(ROOT))
from hooks.lib import overnight, todo_canonical  # noqa: E402

WAKE = overnight.WAKE_PROMPT
JOB = "5a5e0c1d"


def _canonical():
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "todo" / "dev-overnight.py")],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def _frontier(todos, n):
    return [dict(t, status="completed" if i < n else "in_progress" if i == n else "pending")
            for i, t in enumerate(todos)]


class Session:
    def __init__(self, tmp_path):
        self.tmp, self.sid, self.ids = tmp_path, str(uuid.uuid4()), 0
        self.home = tmp_path / "home"
        self.project = tmp_path / "project"
        (self.project / ".claude").mkdir(parents=True)
        tdir = self.home / ".claude" / "projects" / "-project"
        tdir.mkdir(parents=True)
        self.path = tdir / f"{self.sid}.jsonl"
        self.path.write_text("")

    def add(self, record):
        with self.path.open("a") as handle:
            handle.write(json.dumps(record) + "\n")

    def typed(self, text):
        self.add({"type": "user", "message": {"role": "user", "content": text}})

    def use(self, name, tool_input, result="ok", error=False, tool_use_result=None):
        self.ids += 1
        tid = f"toolu_{self.ids:04d}"
        self.add({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tid, "name": name, "input": tool_input}]}})
        if result is not None:
            block = {"type": "tool_result", "tool_use_id": tid, "content": result}
            if error:
                block["is_error"] = True
            rec = {"type": "user", "message": {"role": "user", "content": [block]}}
            if tool_use_result is not None:
                rec["toolUseResult"] = tool_use_result
            self.add(rec)
        return tid

    def wake(self, job=JOB, **over):
        tinput = dict({"cron": "3,13,23,33,43,53 * * * *", "recurring": True, "prompt": WAKE}, **over)
        return self.use("CronCreate", tinput, tool_use_result={"id": job, "recurring": tinput["recurring"],
                                                               "durable": False})

    def env(self):
        return {"PATH": os.environ["PATH"], "HOME": str(self.home), "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
                "CLAUDE_STATE_DIR": str(self.tmp / "state"), "TMPDIR": str(self.tmp),
                "CLAUDE_PROJECT_DIR": str(self.project), "PYTHONDONTWRITEBYTECODE": "1"}

    def hook(self, name, event, **payload):
        body = {"session_id": self.sid, "transcript_path": str(self.path), "cwd": str(self.project),
                "hook_event_name": event, "permission_mode": "default", **payload}
        return subprocess.run([sys.executable, str(HOOKS / name)], input=json.dumps(body), capture_output=True,
                              text=True, env=self.env(), cwd=self.project, timeout=60)

    def todo(self, todos, hook="pretool-todo-validate.py", event="PreToolUse"):
        """A TodoWrite: its tool_use, then the hook (PreToolUse before its result, PostToolUse after)."""
        tid = self.use("TodoWrite", {"todos": todos}, result=None)
        if event == "PostToolUse":
            self.add({"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tid, "content": "ok"}]}})
        p = self.hook(hook, event, tool_name="TodoWrite", tool_input={"todos": todos}, tool_use_id=tid)
        if event == "PreToolUse" and p.returncode == 0:
            self.add({"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tid, "content": "ok"}]}})
        return p


@pytest.fixture
def night(tmp_path):
    s = Session(tmp_path)
    s.typed("/dev-overnight 1h harden the toy package")
    return s


# ---------------------------------------------------------------- Step 0: the wake's completion rule

def test_wake_step_completes_only_after_the_wake_cron_create(night):
    todos = _canonical()
    assert todos[0]["content"] == "Step 0: Schedule the wake" and todos[0].get("wake_call") is True
    assert night.todo(_frontier(todos, 0)).returncode == 0
    refused = night.todo(_frontier(todos, 1))
    assert refused.returncode == 2 and "Step 0: Schedule the wake" in refused.stderr and "CronCreate" in refused.stderr
    night.wake()
    assert night.todo(_frontier(todos, 1)).returncode == 0


@pytest.mark.parametrize("over", [{"recurring": False}, {"prompt": WAKE + " "}, {"prompt": "/restart"}])
def test_wake_step_refused_for_another_cron_create(night, over):
    todos = _canonical()
    night.todo(_frontier(todos, 0))
    night.wake(**over)
    assert night.todo(_frontier(todos, 1)).returncode == 2


def test_wake_step_refused_when_the_cron_create_failed(night):
    todos = _canonical()
    night.todo(_frontier(todos, 0))
    night.use("CronCreate", {"cron": "3 * * * *", "recurring": True, "prompt": WAKE}, result="error", error=True)
    assert night.todo(_frontier(todos, 1)).returncode == 2


def test_loop_reset_completes_step_0_again_with_no_second_cron_create(night):
    todos = _canonical()
    night.todo(_frontier(todos, 0))
    night.wake()
    for n in range(1, len(todos) + 1):
        role = (todos[n - 1].get("subagent_call") or {}).get("subagent_type")
        if role:
            night.use("Agent", {"subagent_type": role, "prompt": "x", "description": role})
        assert night.todo(_frontier(todos, n)).returncode == 0, n
    assert night.todo(_frontier(todos, 0)).returncode == 0  # the loop hook's reset
    assert night.todo(_frontier(todos, 1)).returncode == 0  # the wake of the launch still runs


# ---------------------------------------------------------------- the widened /restart capability

def _issued(p):
    return p.returncode == 0 and "capability issued" in p.stdout


def test_wake_gets_the_capability_inside_its_span(night):
    assert _issued(night.hook("userprompt-restart-authorize.py", "UserPromptSubmit", prompt=WAKE))


def test_wake_after_the_owners_stop_gets_nothing(night):
    night.typed("/stop")
    p = night.hook("userprompt-restart-authorize.py", "UserPromptSubmit", prompt=WAKE)
    assert p.returncode == 0 and not p.stdout.strip()
    assert not list((night.home / ".claude" / "restart-state").glob("grants/*"))


def test_wake_outside_a_dev_overnight_span_gets_nothing(tmp_path):
    s = Session(tmp_path)
    s.typed("/dev fix the bug")
    assert not s.hook("userprompt-restart-authorize.py", "UserPromptSubmit", prompt=WAKE).stdout.strip()


@pytest.mark.parametrize("prompt", [WAKE + " now", "resume the cut work", "/restarts"])
def test_other_prompts_get_nothing(night, prompt):
    assert not night.hook("userprompt-restart-authorize.py", "UserPromptSubmit", prompt=prompt).stdout.strip()


def test_every_restart_prompt_keeps_the_capability(night):
    # X8: the hook cannot tell a scheduled /restart from a typed one, so both keep it, as before.
    night.typed("/stop")
    assert _issued(night.hook("userprompt-restart-authorize.py", "UserPromptSubmit", prompt="/restart"))


def test_prompt_workflow_hands_over_restart_md_for_the_wake_in_its_span(night):
    p = night.hook("prompt-workflow.py", "UserPromptSubmit", prompt=WAKE)
    assert p.returncode == 0 and "OVERNIGHT WAKE" in p.stdout and "restart.md now and run its Mandatory procedure" in p.stdout
    night.typed("/stop")
    p = night.hook("prompt-workflow.py", "UserPromptSubmit", prompt=WAKE)
    assert "OVERNIGHT WAKE" not in p.stdout and "Mandatory procedure" not in p.stdout


# ---------------------------------------------------------------- the time-lock's wake check

def _ended(night, summary=True):
    past = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
    start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 7200))
    (night.project / ".claude" / f"overnight-state-{night.sid}.json").write_text(json.dumps(
        {"session_id": night.sid, "start_time": start, "end_time": past, "current_phase": "exploring"}))
    if summary:
        (night.project / "docs" / "dev").mkdir(parents=True, exist_ok=True)
        (night.project / "docs" / "dev" / "overnight-summary-2099-01-01.md").write_text("# Summary\n")


def _gate():
    import importlib.util
    spec = importlib.util.spec_from_file_location("stop_command_gate_wake", HOOKS / "stop-command-gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GATE = _gate()


@pytest.fixture
def lock(night, monkeypatch):
    """The gate's time-lock on the night's payload. P2's overnight.window_open and
    closeout_gaps(state, working_root) are not on this base: a fake with their signatures over
    this base's readers (re-run once P2 merges); session_state_file and open_wakes are real."""
    import types
    fake = types.ModuleType("lib.overnight")
    fake.session_state_file = overnight.session_state_file
    fake.window_open = lambda payload: False  # every case here is past end_time
    fake.closeout_gaps = lambda state, root: overnight.closeout_gaps(state)
    fake.working_root = overnight.working_root
    fake.open_wakes = overnight.open_wakes
    monkeypatch.setitem(sys.modules, "lib.overnight", fake)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(night.project))
    monkeypatch.delenv("CLAUDE_COMPAT_RUNTIME", raising=False)
    payload = {"session_id": night.sid, "transcript_path": str(night.path), "cwd": str(night.project)}
    return lambda: GATE.time_lock(payload)


def test_stop_after_end_time_refused_while_the_wake_is_live(night, lock):
    _ended(night)
    night.wake()
    code, text, _terminal = lock()
    assert code == 2 and JOB in text and "CronDelete" in text
    night.use("CronDelete", {"id": JOB})
    assert lock() == (0, "", "completed_by_deadline")


def test_closeout_comes_first(night, lock):
    """The closeout incomplete, the time-lock names no wake: the closeout is the gate's
    /dev-overnight predicate gap (test_stop_command_gate.py)."""
    _ended(night, summary=False)
    night.wake()
    assert lock() == (0, "", None)


def test_after_the_owners_stop_the_wake_check_still_holds(night, lock):
    _ended(night)
    night.wake()
    night.typed("/stop")
    assert lock()[0] == 2
    night.use("CronDelete", {"id": JOB}, result="No scheduled job", error=True)  # deleted is deleted
    assert lock() == (0, "", "cancelled_by_user")


def test_a_transcript_without_the_wake_meets_nothing_new(night, lock):
    _ended(night)
    night.use("CronCreate", {"cron": "7 * * * *", "recurring": True, "prompt": "check the deploy"},
              tool_use_result={"id": "other"})
    assert lock()[0] == 0


def test_a_cron_delete_before_the_wake_does_not_end_it(night):
    night.use("CronDelete", {"id": JOB})
    night.wake()
    assert overnight.open_wakes(night.path) == [JOB]
    night.use("CronDelete", {"id": JOB})
    assert overnight.open_wakes(night.path) == []


# ---------------------------------------------------------------- pairing by content, never by index

def test_a_list_started_before_step_0_keeps_running(night):
    """A session running at the merge holds the list of the base (no Step 0): its hooks pair each todo
    with the canonical step of its content; Gate 4 still guards its subagent steps."""
    old = _canonical()[1:]
    assert night.todo(_frontier(old, 0)).returncode == 2  # a first list is compared whole (as before)
    s = Session(night.tmp / "live")
    s.typed("/dev-overnight 1h harden the toy package")
    s.add({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "toolu_base", "name": "TodoWrite", "input": {"todos": _frontier(old, 0)}}]}})
    s.add({"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "toolu_base", "content": "ok"}]}})  # written on the base
    assert s.todo(_frontier(old, 1)).returncode == 0
    refused = s.todo(_frontier(old, 2))  # Step 2, PM Plan, a subagent step: Gate 4 by content
    assert refused.returncode == 2 and "pm" in refused.stderr
    s.use("Agent", {"subagent_type": "pm", "prompt": "PLAN", "description": "pm plan"})
    assert s.todo(_frontier(old, 2)).returncode == 0  # its length, shorter than the canonical list, holds
    assert todo_canonical.checklist(str(s.path)).lock == ""


def test_codex_plan_pairs_by_text_past_its_first_plan():
    import importlib.util
    spec = importlib.util.spec_from_file_location("wf_gate", HOOKS / "pretool-workflow-gate.py")
    gate = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(HOOKS))
    spec.loader.exec_module(gate)
    canonical = _canonical()
    old = canonical[1:]
    plan = [{"step": t["content"], "status": t["status"]} for t in _frontier(old, 1)]
    todos, violations = gate.codex_plan_to_todos(plan, canonical, last=_frontier(old, 0))
    assert not violations and [t["content"] for t in todos] == [t["content"] for t in old]
    assert gate.codex_plan_to_todos(plan, canonical)[1]  # a first plan is compared whole


def test_by_content_pairs_each_todo_with_its_own_step():
    canonical = _canonical()
    shorter = list(reversed(canonical[1:]))
    assert [s["content"] for s in todo_canonical.by_content(canonical, shorter)] == [t["content"] for t in shorter]
    assert todo_canonical.by_content(canonical, [{"content": "Step 99: not a step"}]) == [{}]


def test_subagent_tracker_records_the_step_of_the_todos_content(night):
    """posttool-subagent-track.py (the Codex plan's bookmark) pairs the in-progress todo with the canonical
    step of its content: in a list without Step 0, PM Plan is index 1, and its call is recorded there."""
    old = _frontier(_canonical()[1:], 1)
    bookmark = night.project / ".claude" / f"workflow-{night.sid}.json"
    bookmark.write_text(json.dumps({"command": "dev-overnight", "arguments": "", "last_todos": old}))
    p = night.hook("posttool-subagent-track.py", "PostToolUse", tool_name="Agent",
                   tool_input={"subagent_type": "pm", "prompt": "PLAN: the test plan", "description": "pm plan"},
                   tool_response={"content": "done"})
    assert p.returncode == 0, p.stderr
    assert json.loads(bookmark.read_text()).get("subagent_calls") == {"1": True}, p.stdout


# ---------------------------------------------------------------- the write boundary and /restart's helper

HELPER = "~/.claude/venv/bin/python ~/.claude/scripts/restart-subagents.py"


@pytest.mark.parametrize("sub", ["prepare", "status --wait-seconds 540", "finalize"])
def test_overnight_write_boundary_leaves_the_restart_helper_alone(tmp_path, sub):
    """X4 (b): the boundary keeps the main working tree from being written in place; /restart's helper
    writes only its own journal under the harness home, so the wake's recovery runs it outside the
    boundary (no bwrap re-exec, no fail-closed refusal). Anything chained to it is still bounded."""
    main = tmp_path / "main"
    (main / ".git").mkdir(parents=True)
    (main / ".claude").mkdir()
    sid = "sid-overnight"
    (main / ".claude" / f"overnight-state-{sid}.json").write_text(json.dumps({
        "schema_version": 9, "session_id": sid, "isolation_kind": "in_place", "main_root": str(main),
        "main_git_dir": str(main / ".git"), "worktree_path": str(main), "worktree_branch": "work-branch",
        "protected_branch": "master", "end_time": "2099-01-01T00:00:00Z",
        "isolation_active_until": "2099-01-01T00:00:00Z", "current_cycle": 1}))

    def guard(command):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(main), PWD=str(main))
        return subprocess.run([sys.executable, str(HOOKS / "pretool-overnight-hook-guard.py")], input=json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": sid, "cwd": str(main)}),
            capture_output=True, text=True, env=env, cwd=main, timeout=120)

    plain = guard(f"{HELPER} {sub}")
    assert plain.returncode == 0 and "updatedInput" not in plain.stdout, (plain.stdout, plain.stderr)
    chained = guard(f"{HELPER} {sub} && touch {tmp_path / 'outside'}")
    assert chained.returncode == 2 or "updatedInput" in chained.stdout, (chained.stdout, chained.stderr)


def test_the_command_texts_carry_the_wake_and_its_deletions():
    """dev-overnight.md's Step 0 block is the one recurring CronCreate of WAKE_PROMPT; Step 21's
    session-ending branch and stop.md end with its CronDelete."""
    sys.path.insert(0, str(ROOT))
    from tests.replay import cmdtext
    night = (ROOT / "commands" / "dev-overnight.md").read_text()
    spec = json.loads(cmdtext.block(night, "Step 0", lang="json"))
    assert spec["prompt"] == WAKE and spec["recurring"] is True
    assert "CronDelete" in cmdtext.section(night, "Step 21") and "Delete the wake" in night
    assert "CronDelete" in cmdtext.section((ROOT / "commands" / "stop.md").read_text(), "Implementation")
