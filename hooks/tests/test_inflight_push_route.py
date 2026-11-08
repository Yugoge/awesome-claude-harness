"""Train 2 (A17): an in-flight /commit's refused token Write names its route, and the route completes.

COMPATIBILITY TESTS, kept only as long as hooks/pretool-tool-policy.py's _note_inflight_token_route and
scripts/execute-push.py's Step 9b (D15: until no running session predates train 2's landing).

2acc29b's changelog-analyst text (Phase 10) writes the push-gate token with the Write tool at
/tmp/agentic-commit/push/<repo hash>/<session digest>/<branch>.json. On the train only
scripts/write-push-gate-token.py writes that token: the tool policy refuses the Write, by P5's protected
stage (review H2) where the state dir is /tmp and by the analyst's role row where it is not, and the
refusal stays (D18). Its stderr names the route instead: /push, whose Step 3 push-analyst dispatch binds
the grant and whose Step 5 execute-push.py, once the grant passes, has the token's one writer write the
token for that commit while it is HEAD and no token names an ancestor of HEAD.

The route test runs the real scripts in a scratch HOME, config dir and state dir: an in-flight /commit
landed its commit with no token, and the session transcript and the analyst's own transcript record its
Write and the refusal the real hook printed for it, as the CLI records them. Then a /push: the grant its
push-analyst writes, and execute-push.py, which validates it, has the writer write the token and execs
hooks/push.sh, which pushes to a local bare origin and deletes the token. Where the record is not that
refusal for HEAD, push.sh refuses as before (exit 3) and no token is written.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "pretool-tool-policy.py"
EXECUTE = ROOT / "scripts" / "execute-push.py"
BLOCK = "BLOCKED by tool-policy.v1: "
SID = "7d0c4a52-a17f-4c0e-9b1e-0a1b2c3d4e5f"
ROUTE = ("reaches its push through /push", "push-analyst, whose own dispatch binds its grant",
         "scripts/execute-push.py", "scripts/write-push-gate-token.py", "while it is HEAD")


def _hook(tmp_path: Path, tool: str, tool_input: dict, role, state) -> subprocess.CompletedProcess:
    home = tmp_path / "hookhome"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    payload = {"session_id": SID, "cwd": "/nonexistent-a17-route/proj", "hook_event_name": "PreToolUse",
               "tool_name": tool, "tool_input": tool_input}
    if role:
        payload.update(agent_id="a" + uuid.uuid4().hex[:16], agent_type=role)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"),
               CLAUDE_PROJECT_DIR="/nonexistent-a17-route/proj", PYTHONDONTWRITEBYTECODE="1")
    if state:
        env["CLAUDE_STATE_DIR"] = str(state)
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                          text=True, env=env, timeout=60)


def _token_word(repo_hash: str, branch: str) -> str:
    """The path 2acc29b's Phase 10 Writes: literal /tmp, the session digest, the branch encoded."""
    digest = hashlib.sha256(SID.encode()).hexdigest()[:16]
    return f"/tmp/agentic-commit/push/{repo_hash}/{digest}/{branch.replace('/', '__')}.json"


# ---------------------------------------------------------------- the refusal names the route
@pytest.mark.parametrize("layout", ["default state dir", "replay layout"])
def test_the_in_flight_token_writes_refusal_names_the_push_analyst_route(tmp_path, layout):
    """Under the default state dir the protected stage refuses it, in its words (review H2); with the state
    dir elsewhere the analyst's role row does. Either way the refusal's first line is the one it was, and
    the next line names the route; no other caller's refusal of a token write gains it."""
    state = None if layout == "default state dir" else tmp_path / "state"
    word = _token_word("60229693667929e5", "master")
    content = json.dumps({"commit_sha": "1" * 40, "branch": "master", "repo_root": str(tmp_path / "toyproj"),
                          "session_id": SID})
    proc = _hook(tmp_path, "Write", {"file_path": word, "content": content}, "changelog-analyst", state)
    assert proc.returncode == 2, proc.stderr
    first, *rest = proc.stderr.splitlines()
    denial = json.loads(first[len(BLOCK):])
    assert denial["role"] == "changelog-analyst" and denial["target"] == word, denial
    if state is None:
        assert denial["deny_reason"].endswith(
            "is a push-gate token, whose one writer is scripts/write-push-gate-token.py: "
            "no agent writes, deletes or renames it (D11/D12)"), denial
    else:
        assert denial["deny_reason"] == f"write target {word} not in allowed_write_path_prefixes", denial
    note = "\n".join(rest)
    assert all(part in note for part in ROUTE), proc.stderr
    assert "stays refused" in note and "do not write the token any other way" in note, note
    for tool, tool_input, role in [("Write", {"file_path": word, "content": content}, None),
                                   ("Write", {"file_path": word, "content": content}, "dev"),
                                   ("Bash", {"command": f"cat > {word} <<EOF\n{content}\nEOF"}, "changelog-analyst")]:
        other = _hook(tmp_path, tool, tool_input, role, state)
        assert "reaches its push through /push" not in other.stderr, (tool, role, other.stderr)


# ---------------------------------------------------------------- the route completes
def _git(repo: Path, *args: str, env: dict) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], env=env, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def world(tmp_path):
    """A product repository one commit ahead of its bare origin, as the in-flight /commit left it: the commit
    landed, no token. Returns (tmp_path, env, repo, head, repo_hash)."""
    home = tmp_path / "home"
    (home / ".claude" / "projects").mkdir(parents=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "CLAUDE_"))}
    env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), CLAUDE_STATE_DIR=str(tmp_path / "state"),
               CLAUDE_SESSION_ID=SID, CLAUDE_CODE_SESSION_ID=SID, GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@example.com", PYTHONDONTWRITEBYTECODE="1")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "master", str(tmp_path / "origin.git")], env=env, check=True)
    repo = tmp_path / "toyproj"
    subprocess.run(["git", "init", "-q", "-b", "master", str(repo)], env=env, check=True)
    _git(repo, "remote", "add", "origin", str(tmp_path / "origin.git"), env=env)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "init toy", env=env)
    _git(repo, "push", "-q", "-u", "origin", "master", env=env)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "fix(toy): add validates its arguments\n\nTask-id: 20261108-162044",
         env=env)
    head = _git(repo, "rev-parse", "HEAD", env=env)
    repo_hash = hashlib.sha256(os.path.realpath(repo).encode()).hexdigest()[:16]
    return tmp_path, env, repo, head, repo_hash


def _record(world, *, commit=None, opener="commit", refused=True, agent_type="changelog-analyst") -> None:
    """The CLI's record of the in-flight /commit: the session transcript (the typed command, the analyst's
    dispatch) and the analyst's own transcript (its Write of the token as 2acc29b's Phase 10 spells it and
    what came back: the real hook's refusal of it, with the state dir of ``world``) and meta."""
    tmp_path, env, repo, head, repo_hash = world
    word = _token_word(repo_hash, "master")
    content = json.dumps({"commit_sha": commit or head, "branch": "master", "repo_root": str(repo),
                          "session_id": SID}) + "\n"
    if refused:
        proc = _hook(tmp_path, "Write", {"file_path": word, "content": content}, "changelog-analyst",
                     tmp_path / "state")
        assert proc.returncode == 2 and "reaches its push through /push" in proc.stderr, proc.stderr
        result = {"type": "tool_result", "tool_use_id": "toolu_a17write", "is_error": True,
                  "content": "PreToolUse:Write hook error: " + proc.stderr.strip()}
    else:
        result = {"type": "tool_result", "tool_use_id": "toolu_a17write",
                  "content": f"File created successfully at: {word}"}
    project = Path(env["CLAUDE_CONFIG_DIR"]) / "projects" / "-a17-toyproj"
    (project / SID / "subagents").mkdir(parents=True, exist_ok=True)
    with open(project / f"{SID}.jsonl", "w") as fh:
        for record in ({"type": "user", "message": {"role": "user", "content":
                        f"<command-name>/{opener}</command-name>\n<command-args></command-args>"}},
                       {"type": "assistant", "message": {"role": "assistant", "content": [
                           {"type": "tool_use", "id": "toolu_a17dispatch", "name": "Agent", "input": {
                               "description": "commit", "prompt": "TASK_ID=20261108-162044",
                               "subagent_type": agent_type}}]}}):
            fh.write(json.dumps(record) + "\n")
    agent = project / SID / "subagents" / "agent-a17analyst"
    with open(agent.with_suffix(".jsonl"), "w") as fh:
        for record in ({"type": "user", "isSidechain": True, "message": {"role": "user", "content": "TASK_ID=20261108-162044"}},
                       {"type": "assistant", "isSidechain": True, "message": {"role": "assistant", "content": [
                           {"type": "tool_use", "id": "toolu_a17write", "name": "Write",
                            "input": {"file_path": word, "content": content}}]}},
                       {"type": "user", "isSidechain": True, "message": {"role": "user", "content": [result]}}):
            fh.write(json.dumps(record) + "\n")
    agent.with_suffix(".meta.json").write_text(json.dumps({"agentType": agent_type, "toolUseId": "toolu_a17dispatch"}))


def _push(world, verdict: str = "warn") -> tuple[subprocess.CompletedProcess, str]:
    """/push Steps 3-5: the grant the push-analyst writes (agents/push-analyst.md Phase 7), then Step 5's call.
    Returns the call and the origin's master after it."""
    tmp_path, env, repo, head, repo_hash = world
    request = uuid.uuid4().hex
    grant = tmp_path / "state" / "agentic-commit" / "push-analyst" / repo_hash / SID / f"{request}.json"
    grant.parent.mkdir(parents=True, exist_ok=True)
    expires = (datetime.now(timezone.utc) + timedelta(seconds=600)).strftime("%Y-%m-%dT%H:%M:%SZ")
    grant.write_text(json.dumps({"verdict": verdict, "risks": ["Direct push to protected branch `master`"],
                                 "analysis_summary": "one commit", "branch": "master", "head_sha": head,
                                 "remote_name": "origin", "remote_url": str(tmp_path / "origin.git"),
                                 "session_id": SID, "nonce": request, "expires_at": expires}))
    proc = subprocess.run([sys.executable, str(EXECUTE), "--repo-hash", repo_hash, "--branch", "master",
                           "--remote", "origin", "--request-id", request, "--repo-root", str(repo)],
                          cwd=str(repo), env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                          timeout=180)
    tip = subprocess.run(["git", "--git-dir", str(tmp_path / "origin.git"), "rev-parse", "-q", "--verify",
                          "refs/heads/master"], env=env, capture_output=True, text=True).stdout.strip()
    return proc, tip


def _tokens(world) -> list:
    tmp_path, _env, _repo, _head, repo_hash = world
    return sorted((tmp_path / "state" / "agentic-commit" / "push" / repo_hash).glob("**/*.json"))


def test_the_route_pushes_the_in_flight_commit_and_spends_the_token(world):
    _tmp, _env, _repo, head, _hash = world
    _record(world)
    proc, tip = _push(world)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert f"no push-gate token named HEAD {head}; an in-flight /commit's token Write was refused" in out, out
    assert tip == head, out
    assert _tokens(world) == [], "push.sh spends the token it pushed on"


@pytest.mark.parametrize("record", [
    None,                                   # the owner's own commit: no /commit, no record
    {"commit": "1" * 40},                   # the refused Write named another commit
    {"opener": "do"},                       # the analyst's dispatch is in a /do span, not a /commit one
    {"refused": False},                     # the Write came back written, not refused
    {"agent_type": "general-purpose"},      # another agent type Wrote it
], ids=["no-record", "other-commit", "other-span", "not-refused", "other-agent"])
def test_without_that_refusal_for_head_push_sh_refuses_as_before(world, record):
    _tmp, _env, _repo, head, _hash = world
    if record is not None:
        _record(world, **record)
    proc, tip = _push(world)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 3 and "no push-gate token" in out, out
    assert tip != head and _tokens(world) == [], out


def test_a_blocked_grant_writes_no_token(world):
    _record(world)
    proc, tip = _push(world, verdict="blocked")
    assert proc.returncode == 1 and "push BLOCKED by push-analyst" in proc.stderr, proc.stderr
    assert _tokens(world) == []
