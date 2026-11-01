"""Gate 4 after a /restart recovery (P1c R16; faults F5, F5f, F6).

A dev subagent cut before its Agent call came back (no tool_result, or the CLI's error result after a
usage limit) is resumed by the owner's /restart through SendMessage and finalized (commands/restart.md).
Its original Agent call is then the dev step's dispatch: pretool-todo-validate.py lets the step
complete, reading the span's SendMessage to that agent and the recovery journal
(subagent_restart.finalized_resumes), and asks for no replacement call (Lesson 16). Until the
recovery is finalized the step stays refused, the message naming the step, the role and the cut
call's declared artifact.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOOKS.parent))
from hooks.lib import subagent_restart as restart  # noqa: E402

REPORT = "docs/dev/dev-report-20990101-000001.json"
OBLIGATION = ('<obligation v="1">\n' + json.dumps({
    "task_id": "20990101-000001", "role": "dev", "pipeline": "dev", "profile": "singular",
    "dispatched_at": "2099-01-01T00:00:01Z",
    "artifacts": [{"kind": "json", "path": REPORT, "schema": "dev-report.v2"}]}) + "\n</obligation>")


def _frontier(n):
    out = json.loads(subprocess.run([sys.executable, str(HOOKS.parent / "scripts" / "todo" / "dev.py")],
                                    capture_output=True, text=True, check=True).stdout)
    for i, item in enumerate(out):
        item["status"] = "completed" if i < n else ("in_progress" if i == n else "pending")
    return out


class _Cycle:
    """A /dev span up to Step 10 (index 9) in progress, its earlier dispatches back."""

    def __init__(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_RESTART_STATE_DIR", str(tmp_path / "restart-state"))
        monkeypatch.setenv("CLAUDE_RESTART_GRANT_DIR", str(tmp_path / "grants"))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "home" / ".claude"))
        self.tmp, self.sid, self.ids = tmp_path, str(uuid.uuid4()), 0
        self.path = tmp_path / f"{self.sid}.jsonl"
        self.project = tmp_path / "project"
        (self.project / ".claude").mkdir(parents=True)
        self.add({"type": "user", "message": {"role": "user", "content": "/dev fix the bug"}})
        for n in range(10):
            role = {4: "ba", 7: "qa", 9: "graphify"}.get(n)
            if role:
                self.result(self.use("Agent", {"subagent_type": role, "prompt": "x", "description": role}))
            self.result(self.use("TodoWrite", {"todos": _frontier(n)}))

    def add(self, record):
        with self.path.open("a") as handle:
            handle.write(json.dumps(record) + "\n")

    def use(self, name, tool_input):
        self.ids += 1
        tid = f"toolu_{self.ids:04d}"
        self.add({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tid, "name": name, "input": tool_input}]}})
        return tid

    def result(self, tid, text="ok", error=False):
        block = {"type": "tool_result", "tool_use_id": tid, "content": text}
        if error:
            block["is_error"] = True
        self.add({"type": "user", "message": {"role": "user", "content": [block]}})

    def cut(self, role="dev", error_result=False):
        """A dispatch of `role` cut mid-run: its agent's transcript and meta, no SubagentStop; no
        result (an interrupted session) or the CLI's error result (a usage limit)."""
        tid = self.use("Agent", {"subagent_type": role, "prompt": f"Implement it.\n{OBLIGATION}",
                                 "description": role, "run_in_background": False})
        aid, self.cut_tid = f"a{uuid.uuid4().hex[:16]}", tid
        sub = self.path.with_suffix("") / "subagents"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / f"agent-{aid}.meta.json").write_text(json.dumps({"agentType": role, "toolUseId": tid}))
        (sub / f"agent-{aid}.jsonl").write_text(json.dumps({"type": "assistant", "message": {
            "role": "assistant", "content": [{"type": "text", "text": "partial work"}]}}) + "\n")
        if error_result:
            self.result(tid, "Agent terminated early due to an API error: You've hit your session limit "
                             "(error type rate_limit, HTTP 429)", error=True)
        return aid

    def restart(self, aids, finalize=True, send=True):
        """The owner's /restart: the capability, prepare, a SendMessage per candidate, each agent's
        response (SubagentStop), and finalize."""
        self.add({"type": "user", "message": {"role": "user", "content": "/restart"}})
        restart.mint_grant(self.sid, str(self.path))
        view = restart.prepare_state(self.sid)
        assert sorted(c["agent_id"] for c in view["candidates"]) == sorted(aids)
        for c in view["candidates"]:
            if send:
                self.result(self.use("SendMessage", {"to": c["agent_id"], "message": c["resume_message"]}))
            restart.mark_dispatched(self.sid, c["agent_id"])
            restart.observe_subagent_stop({"session_id": self.sid, "agent_id": c["agent_id"],
                                           "last_assistant_message": "done\n\nRECOVERY_STATUS: completed"})
        if finalize:
            restart.finalize(self.sid)

    def complete_step_10(self):
        todos = _frontier(10)
        tid = self.use("TodoWrite", {"todos": todos})
        payload = {"session_id": self.sid, "transcript_path": str(self.path), "hook_event_name": "PreToolUse",
                   "tool_name": "TodoWrite", "tool_input": {"todos": todos}, "tool_use_id": tid}
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.project), "HOME": str(self.tmp / "home"),
               "CLAUDE_CONFIG_DIR": str(self.tmp / "home" / ".claude"), "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run([sys.executable, str(HOOKS / "pretool-todo-validate.py")], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, cwd=self.project, timeout=60)


@pytest.fixture
def cycle(tmp_path, monkeypatch):
    return _Cycle(tmp_path, monkeypatch)


@pytest.mark.parametrize("error_result", [False, True], ids=["interrupted-no-result", "usage-limit-error-result"])
def test_a_resumed_and_finalized_dev_call_completes_the_dev_step(cycle, error_result):
    aid = cycle.cut(error_result=error_result)
    cycle.restart([aid])
    done = cycle.complete_step_10()
    assert done.returncode == 0, done.stderr


def test_before_finalize_the_step_is_refused_naming_step_role_and_artifact(cycle):
    aid = cycle.cut()
    cycle.restart([aid], finalize=False)
    refused = cycle.complete_step_10()
    assert refused.returncode == 2
    assert '"Step 10: Delegate to dev subagent" (subagent role dev)' in refused.stderr
    assert REPORT in refused.stderr and "never replaced by a new call" in refused.stderr
    restart.finalize(cycle.sid)
    assert cycle.complete_step_10().returncode == 0


def test_a_journal_without_the_resume_in_the_span_meets_nothing(cycle):
    """The journal alone is not the resume: the span must hold the SendMessage to that agent."""
    aid = cycle.cut()
    cycle.restart([aid], send=False)
    assert cycle.complete_step_10().returncode == 2


def test_a_resumed_call_of_another_role_does_not_meet_the_dev_step(cycle):
    aid = cycle.cut(role="qa")
    cycle.restart([aid])
    refused = cycle.complete_step_10()
    assert refused.returncode == 2 and "requires a subagent call (dev) that has not been made" in refused.stderr


def test_finalized_resumes_reads_only_a_finalized_complete_journal(cycle):
    aid = cycle.cut()
    assert restart.finalized_resumes(cycle.sid) == {}
    cycle.restart([aid], finalize=False)
    assert restart.finalized_resumes(cycle.sid) == {}, "the capability is still live: not finalized"
    restart.finalize(cycle.sid)
    assert restart.finalized_resumes(cycle.sid) == {aid: cycle.cut_tid}
    assert restart.finalized_resumes("not a session id!") == {}
