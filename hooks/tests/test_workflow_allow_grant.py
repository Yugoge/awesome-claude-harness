"""/allow Workflow lets exactly one refused Workflow call through (T5).

pretool-block-background-tasks.py refuses every Workflow call of the main agent. The owner's
`/allow Workflow` (hooks/userprompt-consent-allowlist.sh) makes a grant that the pre-tool launcher
(lib/hook_launch.release_refused) spends on the next refused Workflow call, so a second call is
refused again and no other tool's refusal is released by it. Each test runs the hooks as the CLI
does, under a throwaway HOME and state directory.
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
PROMPT = HOOKS / "userprompt-consent-allowlist.sh"
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
        def grant(self, text):
            """The owner types `/allow <text>`."""
            prompt = {"hook_event_name": "UserPromptSubmit", "session_id": sid, "prompt": f"/allow {text}",
                      "cwd": str(ROOT), "transcript_path": str(transcript)}
            p = subprocess.run(["bash", str(PROMPT)], input=json.dumps(prompt), text=True, capture_output=True,
                               env=env, check=False)
            assert p.returncode == 0 and "Grant recorded" in p.stdout, p.stdout + p.stderr

        def do_consent(self):
            (state / f"claude-orchestrator-consent-{sid}.flag").write_text("true")

        def payload(self, tool="Workflow", tool_input=None, **extra):
            return {"tool_name": tool, "session_id": sid, "transcript_path": str(transcript),
                    "hook_event_name": "PreToolUse", "tool_use_id": f"toolu_{uuid.uuid4().hex[:12]}",
                    "tool_input": WORKFLOW_INPUT if tool_input is None else tool_input, **extra}

        def run(self, hook, payload):
            return subprocess.run([sys.executable, str(hook)], input=json.dumps(payload), text=True,
                                  capture_output=True, env=env, cwd=str(ROOT), check=False)

        def call(self, pre=PRETOOL, post=POSTTOOL, **kw):
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
    agent = session.run(PRETOOL, session.payload("Agent", {"prompt": "x", "subagent_type": "general-purpose"}))
    assert agent.returncode == 0, agent.stderr  # a background dispatch passes without any grant
    bash = session.run(PRETOOL, session.payload("Bash", {"command": "true", "run_in_background": True}))
    assert bash.returncode == 2
    assert list((session.state / "claude-grants").glob("*.json")), "the Workflow grant is not spent by them"


def test_do_consent_still_lifts_workflow(session):
    session.do_consent()
    assert session.call(pre=BACKGROUND).returncode == 0
    assert session.call(pre=BACKGROUND).returncode == 0


def test_a_subagent_workflow_call_passes_as_before(session):
    assert session.call(pre=BACKGROUND, agent_id="a1234567890abcdef").returncode == 0

