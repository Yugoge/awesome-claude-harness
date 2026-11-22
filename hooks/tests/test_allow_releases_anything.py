"""/allow is a one-time switch-off of the harness for one refused call of one session.

The grant is decided in one place, where the pre-tool verdicts meet (lib/hook_launch.release_refused):
these tests run the pre-tool launcher (hooks/pretool-launch.py) and the prompt hook
(hooks/userprompt-consent-allowlist.sh) as the CLI does, against a throwaway state directory and a
throwaway refusal record (HOME), with neutral values.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
SID = "sess-0001"


@pytest.fixture
def env(tmp_path, monkeypatch):
    state = tmp_path / "state"
    home = tmp_path / "home"
    state.mkdir()
    home.mkdir()
    e = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "CODEX_"))}
    e.update(CLAUDE_STATE_DIR=str(state), HOME=str(home), CLAUDE_SESSION_ID=SID,
             CLAUDE_PROJECT_DIR=str(tmp_path / "proj"), PYTHONDONTWRITEBYTECODE="1")
    (tmp_path / "proj").mkdir()
    return {"env": e, "state": state, "home": home, "tmp": tmp_path}


def prompt(env, text, agent_id=None):
    payload = {"hook_event_name": "UserPromptSubmit", "session_id": SID, "prompt": text,
               "cwd": str(env["tmp"] / "proj")}
    if agent_id:
        payload["agent_id"] = agent_id
    p = subprocess.run(["bash", str(HOOKS / "userprompt-consent-allowlist.sh")], input=json.dumps(payload),
                       capture_output=True, text=True, env=env["env"], timeout=60)
    assert p.returncode == 0, p.stderr
    return p.stdout + p.stderr


def call(env, tool, tool_input, n=1, agent_id=None):
    payload = {"hook_event_name": "PreToolUse", "session_id": SID, "tool_name": tool, "tool_input": tool_input,
               "tool_use_id": f"toolu_{tool}_{n}", "cwd": str(env["tmp"] / "proj"),
               "transcript_path": str(env["tmp"] / "none.jsonl")}
    if agent_id:
        payload.update(agent_id=agent_id, agent_type="dev")
    p = subprocess.run([sys.executable, str(HOOKS / "pretool-launch.py")], input=json.dumps(payload),
                       capture_output=True, text=True, env=env["env"], timeout=600)
    return p


def grant_file(env):
    return env["state"] / "claude-grants" / f"{SID}.json"


def records(env):
    out = []
    for f in sorted(env["home"].rglob("refusals-*.jsonl")):
        out += [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
    return out


# Calls the harness refuses, each by a different rule, with neutral values.
COMPOUND = {"command": "echo one && git -C /nonexistent-repo push origin main"}
SCRIPT = None  # built per test: a script that makes a commit, run through a filter


def script_call(env):
    script = env["tmp"] / "land.sh"
    script.write_text("#!/bin/bash\ngit commit -m 'neutral message'\n")
    return {"command": f"bash {script} 2>&1 | grep -v noise | tail -5"}


def test_refused_without_grant(env):
    assert call(env, "Bash", COMPOUND).returncode == 2
    assert call(env, "Bash", script_call(env)).returncode == 2


def test_bare_grant_releases_compound_command_and_is_spent(env):
    out = prompt(env, "/allow")
    assert "whatever it is" in out and grant_file(env).exists()
    p = call(env, "Bash", COMPOUND)
    assert p.returncode == 0, p.stderr
    msg = json.loads(p.stdout)
    assert "RELEASED" in msg["systemMessage"] and "grant is spent" in msg["systemMessage"]
    assert "RELEASED" in msg["hookSpecificOutput"]["additionalContext"]
    assert not grant_file(env).exists()
    assert call(env, "Bash", COMPOUND, n=2).returncode == 2  # the second refused call


def test_script_making_a_commit_through_a_filter(env):
    prompt(env, "/allow")
    assert call(env, "Bash", script_call(env)).returncode == 0


def test_refused_send_message(env):
    # The orchestrator gate's once-per-tool-per-turn limit refuses the second send of the turn.
    send = {"to": "someone-else", "message": "neutral text", "summary": "neutral"}
    assert call(env, "SendMessage", send).returncode == 0
    (env["state"] / f"claude-tool-ran-{SID}.log").write_text("toolu_SendMessage_1\n")
    refused = call(env, "SendMessage", send, n=2)
    assert refused.returncode == 2, refused.stderr
    prompt(env, "/allow")
    (env["state"] / f"claude-tool-ran-{SID}.log").write_text("toolu_SendMessage_1\n")
    assert call(env, "SendMessage", send, n=3).returncode == 0


def test_refused_write(env):
    target = env["tmp"] / "proj" / "exists.txt"
    target.write_text("old\n")
    w = {"file_path": str(target), "content": "new\n"}
    assert call(env, "Write", w).returncode == 2
    prompt(env, "/allow")
    assert call(env, "Write", w, n=2).returncode == 0


def test_subagent_refused_call(env):
    assert call(env, "Bash", COMPOUND, agent_id="agent-01").returncode == 2
    prompt(env, "/allow")
    assert call(env, "Bash", COMPOUND, n=2, agent_id="agent-01").returncode == 0


def test_subagent_prompt_makes_no_grant(env):
    prompt(env, "/allow", agent_id="agent-01")
    assert not grant_file(env).exists()


def test_passing_calls_do_not_spend(env):
    prompt(env, "/allow")
    assert call(env, "Bash", {"command": "echo neutral"}).returncode == 0
    assert call(env, "Read", {"file_path": str(env["tmp"] / "none.txt")}).returncode == 0
    assert grant_file(env).exists()
    assert call(env, "Bash", COMPOUND, n=3).returncode == 0


def test_free_text_behaves_as_bare(env):
    out = prompt(env, "/allow please let the next one through, it is fine")
    assert "whatever it is" in out
    assert call(env, "Bash", COMPOUND).returncode == 0


def test_tool_name_restricts(env):
    out = prompt(env, "/allow SendMessage")
    assert "restricted" in out and "SendMessage" in out
    assert call(env, "Bash", COMPOUND).returncode == 2  # another tool: refused, grant kept
    assert grant_file(env).exists()
    assert call(env, "SendMessage", {"to": "someone-else", "message": "x"}, n=2).returncode == 0


def test_command_restricts(env):
    out = prompt(env, "/allow echo one")
    assert "restricted" in out and "echo one" in out
    assert call(env, "Bash", script_call(env)).returncode == 2
    assert call(env, "Bash", COMPOUND, n=2).returncode == 0


def test_grant_ends_at_next_prompt(env):
    prompt(env, "/allow")
    assert grant_file(env).exists()
    prompt(env, "an ordinary prompt")
    assert not grant_file(env).exists()
    assert call(env, "Bash", COMPOUND).returncode == 2


def test_release_line_in_record(env):
    prompt(env, "/allow")
    assert call(env, "Bash", COMPOUND).returncode == 0
    rows = [r for r in records(env) if r.get("tool_use_id") == "toolu_Bash_1"]
    assert rows and all(r["kind"] == "released" for r in rows), rows
    assert rows[0]["rules"]
    reader = subprocess.run([sys.executable, str(ROOT / "scripts" / "refusals"), "--json"], capture_output=True,
                            text=True, env=env["env"], timeout=60)
    if reader.returncode == 0 and reader.stdout.strip().startswith("{"):
        s = json.loads(reader.stdout)
        found = s.get("summary", s)
        assert found.get("released") == 1 and found.get("refusals") == 0


def test_stop_gate_is_not_released(env):
    sys.path.insert(0, str(HOOKS))
    try:
        from lib import allowlist
    finally:
        sys.path.pop(0)
    for event in ("Stop", "SubagentStop", "UserPromptSubmit"):
        assert allowlist.release({"hook_event_name": event, "session_id": SID}) is None
    from lib.hook_launch import release_refused  # noqa: E402
    assert release_refused("Stop", [], b"{}", 2, "", "blocked\n") == (2, "", "blocked\n")


def test_released_destructive_clean_is_snapshotted_first(env):
    """A destructive `git clean` a grant releases gets the pre-clean snapshot /do's release takes."""
    proj = env["tmp"] / "proj"

    def git(*args):
        return subprocess.run(["git", "-C", str(proj), *args], capture_output=True, text=True, env=env["env"],
                              timeout=60)
    for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@example.invalid"),
                 ("config", "user.name", "t"), ("config", "commit.gpgsign", "false")):
        git(*args)
    (proj / "kept.txt").write_text("kept\n")
    git("add", "kept.txt")
    git("commit", "-q", "-m", "base")
    (proj / "wip.txt").write_text("untracked work\n")
    clean = {"command": "git clean -fd"}
    assert call(env, "Bash", clean).returncode == 2
    prompt(env, "/allow")
    p = call(env, "Bash", clean, n=2)
    assert p.returncode == 0, p.stderr
    assert git("show", "refs/checkpoints/main:wip.txt").stdout == "untracked work\n"
    assert "refs/checkpoints/main" in json.loads(p.stdout)["systemMessage"]


def test_recognise_is_narrow():
    sys.path.insert(0, str(HOOKS))
    try:
        from lib.allowlist import recognise
    finally:
        sys.path.pop(0)
    assert recognise("") == {"kind": "any"}
    assert recognise("Write")["kind"] == "tool"
    assert recognise("mcp__srv__do_thing")["kind"] == "tool"
    assert recognise("sendmessage")["kind"] == "any"
    assert recognise("ls -la")["kind"] == "command"
    assert recognise("no-such-program-x1 arg")["kind"] == "any"
    assert recognise("ls\nmore")["kind"] == "any"
    assert recognise("ls 中")["kind"] == "any"
