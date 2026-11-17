"""/allow Workflow lets exactly one Workflow call through the no-background hook (T5).

The orchestrator gate already passed a Workflow call under `/allow Workflow`, but
pretool-block-background-tasks.py refused every Workflow call whatever the grant, so the grant
did nothing. The hook now reads the same named-tool grant (lib.allowlist.match_sentinel_grant_for_tool)
and posttool-allowlist-consume.py spends it after the call, so a second call is refused again.
Each test runs the hooks as the CLI does, under a throwaway HOME and state directory.
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
ROOT = HOOKS.parent
sys.path.insert(0, str(HOOKS))

BACKGROUND = HOOKS / "pretool-block-background-tasks.py"
CONSUME = HOOKS / "posttool-allowlist-consume.py"
PRETOOL = HOOKS / "pretool-launch.py"
POSTTOOL = HOOKS / "posttool-launch.py"
WORKFLOW_INPUT = {"script": "export default async () => {}", "name": "probe"}


@pytest.fixture()
def session(tmp_path: Path):
    sid = str(uuid.uuid4())
    state = tmp_path / "state"
    state.mkdir()
    transcript = tmp_path / f"{sid}.jsonl"
    transcript.write_text(json.dumps({"type": "user", "isSidechain": False, "origin": {"kind": "human"},
                                      "message": {"role": "user", "content": "run the probe"}}) + "\n")
    env = {**os.environ, "HOME": str(tmp_path / "home"), "CLAUDE_STATE_DIR": str(state),
           "CLAUDE_HOME": str(ROOT), "CLAUDE_CODE_SESSION_ID": sid}
    for name in ("CLAUDE_AGENT_ID", "CLAUDE_TASK_ID", "CLAUDE_SESSION_ID"):
        env.pop(name, None)

    class S:
        def grant(self, *ops):
            code = ("import sys; sys.path.insert(0, sys.argv[1]);"
                    "from lib.allowlist import write_sentinel_grant;"
                    "write_sentinel_grant(sys.argv[2], sys.argv[2], [{'op': o} for o in sys.argv[3:]])")
            subprocess.run([sys.executable, "-c", code, str(HOOKS), sid, *ops], env=env, check=True)

        def do_consent(self):
            (state / f"claude-orchestrator-consent-{sid}.flag").write_text("true")

        def payload(self, tool="Workflow", tool_input=None, **extra):
            return {"tool_name": tool, "session_id": sid, "transcript_path": str(transcript),
                    "hook_event_name": "PreToolUse", "tool_use_id": f"toolu_{uuid.uuid4().hex[:12]}",
                    "tool_input": WORKFLOW_INPUT if tool_input is None else tool_input, **extra}

        def run(self, hook, payload):
            return subprocess.run([sys.executable, str(hook)], input=json.dumps(payload), text=True,
                                  capture_output=True, env=env, cwd=str(ROOT), check=False)

        def call(self, pre=BACKGROUND, post=CONSUME, **kw):
            """One Workflow call: the PreToolUse verdict, and PostToolUse when it ran."""
            payload = self.payload(**kw)
            pre_run = self.run(pre, payload)
            if pre_run.returncode == 0:
                done = {**payload, "hook_event_name": "PostToolUse",
                        "tool_response": {"status": "async_launched", "runId": "wf_1"}}
                assert self.run(post, done).returncode == 0
            return pre_run

    s = S()
    s.sid, s.state = sid, state
    return s


def _refused(p) -> bool:
    return p.returncode == 2 and "Workflow" in p.stderr


def test_workflow_without_a_grant_is_refused(session):
    assert _refused(session.call())


def test_a_workflow_grant_passes_exactly_one_call(session):
    session.grant("Workflow")
    first = session.call()
    assert first.returncode == 0, first.stderr
    assert _refused(session.call()), "the grant is spent by the call it let through"
    assert not list((session.state / "claude-grants").glob("*.json"))


def test_a_grant_for_another_tool_does_not_unlock_workflow(session):
    session.grant("Agent")
    assert _refused(session.call())
    session.grant("SendMessage")
    assert _refused(session.call())


def test_a_grant_for_workflow_unlocks_nothing_else(session):
    session.grant("Workflow")
    agent = session.run(BACKGROUND, session.payload("Agent", {"prompt": "x", "subagent_type": "general-purpose"}))
    assert agent.returncode == 2, "a background dispatch stays refused"
    send = session.run(BACKGROUND, session.payload("SendMessage", {"to": "a0000000000000000", "message": "x"}))
    assert send.returncode == 2
    bash = session.run(BACKGROUND, session.payload("Bash", {"command": "true", "run_in_background": True}))
    assert bash.returncode == 2


def test_do_consent_still_lifts_workflow(session):
    session.do_consent()
    assert session.call().returncode == 0
    assert session.call().returncode == 0


def test_a_subagent_workflow_call_passes_as_before(session):
    assert session.call(agent_id="a1234567890abcdef").returncode == 0


def test_the_registered_launchers_pass_one_granted_call_and_refuse_the_next(session):
    """Through the PreToolUse and PostToolUse launchers the CLI runs, every gate included."""
    assert _refused(session.call(pre=PRETOOL, post=POSTTOOL))
    session.grant("Workflow")
    first = session.call(pre=PRETOOL, post=POSTTOOL)
    assert first.returncode == 0, first.stderr
    assert _refused(session.call(pre=PRETOOL, post=POSTTOOL))
