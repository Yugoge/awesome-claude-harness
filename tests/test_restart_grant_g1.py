"""Lesson 16 end to end: without a valid /restart grant, G1 refuses the exact recovery message.

prepare (scripts/restart-subagents.py, the command commands/restart.md runs) reads the grant as
data only: with no grant, an expired one or one of another schema it still lists the candidates
and says on stderr that every resume send will be refused until /restart mints one (exit 0). The
one decision on the grant is G1's: the no-background rule (hooks/pretool-block-background-tasks.py,
lib/subagent_restart.authorize_send_message) refuses the candidate's exact resume message. Each case
runs the hooks the way the CLI does, through the launchers settings.json registers
(hooks/userprompt-launch.py for the owner's /restart, hooks/pretool-launch.py for SendMessage), under a
throwaway HOME, config dir and state dirs; with the owner's /restart the same message reaches the same
agent_id the usage limit cut.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(HOOKS))

from lib import subagent_restart as restart  # noqa: E402

PREPARE = ROOT / "scripts" / "restart-subagents.py"
PRETOOL = HOOKS / "pretool-launch.py"
USERPROMPT = HOOKS / "userprompt-launch.py"
CUT = "agent-cut"


def _registered(event: str) -> list[str]:
    settings = json.loads((ROOT / "settings.json").read_text(encoding="utf-8"))
    return [h["command"] for group in settings["hooks"][event] for h in group.get("hooks", [])]


@pytest.fixture()
def session(tmp_path: Path):
    sid = str(uuid.uuid4())
    project = tmp_path / "project"
    project.mkdir()
    config = tmp_path / "config"
    transcript = config / "projects" / restart.project_slug(project) / f"{sid}.jsonl"
    sub = transcript.with_suffix("") / "subagents"
    sub.mkdir(parents=True)
    # one dispatch the usage limit cut: the Agent call never came back, its child stopped mid-turn
    transcript.write_text("".join(json.dumps(r) + "\n" for r in (
        {"type": "user", "isSidechain": False, "origin": {"kind": "human"},
         "message": {"role": "user", "content": "look at the repo"}},
        {"type": "assistant", "isSidechain": False, "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_cut", "name": "Agent", "caller": {"type": "direct"},
             "input": {"subagent_type": "general-purpose", "description": "probe", "prompt": "Reply PONG.",
                       "run_in_background": False}}]}},
    )), encoding="utf-8")
    (sub / f"agent-{CUT}.meta.json").write_text(json.dumps(
        {"agentType": "general-purpose", "description": "probe", "toolUseId": "toolu_cut", "spawnDepth": 1}))
    (sub / f"agent-{CUT}.jsonl").write_text(json.dumps(
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "partial"}]}}) + "\n")
    (tmp_path / "state").mkdir()
    env = {**os.environ, "HOME": str(tmp_path / "home"), "CLAUDE_CONFIG_DIR": str(config),
           "CLAUDE_HOME": str(ROOT), "CLAUDE_STATE_DIR": str(tmp_path / "state"),
           "CLAUDE_RESTART_GRANT_DIR": str(tmp_path / "grants"),
           "CLAUDE_RESTART_STATE_DIR": str(tmp_path / "restart"),
           "CLAUDE_PROJECT_DIR": str(project), "CLAUDE_CODE_SESSION_ID": sid}
    for name in ("CLAUDE_AGENT_ID", "CLAUDE_TASK_ID", "CLAUDE_SESSION_ID"):
        env.pop(name, None)

    class S:
        def run(self, argv, payload=None):
            return subprocess.run([sys.executable, *map(str, argv)], text=True, capture_output=True, env=env,
                                  cwd=str(project), check=False,
                                  input=json.dumps(payload) if payload is not None else None)

        def lib(self, fn, *args, **kw):
            old = {k: os.environ.get(k) for k in ("CLAUDE_RESTART_GRANT_DIR", "CLAUDE_RESTART_STATE_DIR",
                                                  "CLAUDE_CONFIG_DIR")}
            os.environ.update({k: env[k] for k in old})
            try:
                return fn(*args, **kw)
            finally:
                for k, v in old.items():
                    os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

        def restart_prompt(self):
            return self.run([USERPROMPT], {"hook_event_name": "UserPromptSubmit", "session_id": sid,
                                           "transcript_path": str(transcript), "cwd": str(project),
                                           "prompt": "/restart"})

        def prepare(self):
            return self.run([PREPARE, "prepare"])

        def send(self, to, message):
            return self.run([PRETOOL], {"hook_event_name": "PreToolUse", "tool_name": "SendMessage",
                                        "session_id": sid, "transcript_path": str(transcript),
                                        "cwd": str(project), "tool_use_id": f"toolu_{uuid.uuid4().hex[:12]}",
                                        "tool_input": {"to": to, "summary": "resume", "message": message}})

        def grant_file(self):
            return Path(env["CLAUDE_RESTART_GRANT_DIR"]) / f"claude-restart-grant-{sid}.json"

    s = S()
    s.sid, s.transcript = sid, transcript
    return s


def test_the_launchers_these_tests_run_are_the_registered_ones():
    assert any("hooks/pretool-launch.py" in c for c in _registered("PreToolUse"))
    assert any("hooks/userprompt-launch.py" in c for c in _registered("UserPromptSubmit"))
    assert "pretool-block-background-tasks.py" in PRETOOL.read_text(encoding="utf-8")
    assert "userprompt-restart-authorize.py" in USERPROMPT.read_text(encoding="utf-8")


def _expired(grant: dict) -> dict:
    return {**grant, "expires_at": "2000-01-01T00:00:00+00:00"}


def _other_schema(grant: dict) -> dict:
    return {**grant, "schema_version": 999}


@pytest.mark.parametrize("spoil, reason", [
    (None, "no valid /restart capability for this session"),
    (_expired, "restart grant expired"),
    (_other_schema, "restart grant schema mismatch"),
], ids=["no-grant", "expired-grant", "wrong-schema-grant"])
def test_without_a_valid_grant_prepare_only_says_so_and_g1_refuses_the_exact_resume(session, spoil, reason):
    if spoil is not None:
        assert session.restart_prompt().returncode == 0
        path = session.grant_file()
        path.write_text(json.dumps(spoil(json.loads(path.read_text(encoding="utf-8")))), encoding="utf-8")
    p = session.prepare()
    assert p.returncode == 0, p.stderr
    assert restart.NO_GRANT_NOTICE in p.stderr, p.stderr
    view = json.loads(p.stdout)
    assert view["restart_grant"] == restart.NO_GRANT_NOTICE
    cand = next(c for c in view["candidates"] if c["agent_id"] == CUT)
    assert cand["resume_message"] == session.lib(restart.build_resume_message, session.sid, CUT)
    g1 = session.send(CUT, cand["resume_message"])
    assert g1.returncode == 2, g1.stderr
    assert "SendMessage refused" in g1.stderr and reason in g1.stderr, g1.stderr
    # prepare created no grant, and the refused send did not either
    assert (session.grant_file().exists()) is (spoil is not None)


def test_with_the_owners_restart_the_exact_resume_reaches_the_same_agent(session):
    assert session.restart_prompt().returncode == 0
    p = session.prepare()
    assert p.returncode == 0 and restart.NO_GRANT_NOTICE not in p.stderr, p.stderr
    view = json.loads(p.stdout)
    assert "restart_grant" not in view
    [cand] = [c for c in view["candidates"] if c["agent_id"] == CUT]
    assert session.send(CUT, "continue").returncode == 2      # only the exact recovery message
    g1 = session.send(CUT, cand["resume_message"])
    assert g1.returncode == 0, g1.stderr
