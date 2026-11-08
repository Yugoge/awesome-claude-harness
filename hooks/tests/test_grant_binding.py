"""Grants bind to their analyst; a role the policy does not list gets no role row (P6 R9, A5, A8).

hooks/pretool-tool-policy.py, beside the derived write permission and for every caller alike:
a file under <state dir>/agentic-commit/merge-analyst/ is created or overwritten by the
merge-analyst only, by Write, Edit, MultiEdit, NotebookEdit or a Bash write target; removing it is
no write. A push-analyst grant is one of the /push Stop's inputs (P5 review H2, its protected
stage, which runs first): only the push-analyst whose own dispatch (commands/push.md Step 3's,
in the session transcript) binds the grant's repository hash, session and request id writes it,
and no caller removes it; every other caller, a push-analyst with no dispatch record of its own
too, is refused in that stage's words, and so is any write of the push-gate token tree. A role the
policy does not list (a built-in or plugin agent type, general-purpose under the "Keep today's
behaviour" outcome) has no role row. The never-registered analysts' documented steps, read from
their agent files, all pass under their CLI role, the push-analyst's from its own dispatch.

Each case runs the real hook as a subprocess with the payload's agent_id and agent_type as the CLI
sends them. The project lies outside /tmp and is never created; only paths are judged.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "pretool-tool-policy.py"
PROJECT = "/nonexistent-p6-grant-binding/proj"
BLOCK = "BLOCKED by tool-policy.v1: "
REPO_HASH, SID, NONCE = "0123456789abcdef", "sess-p6-grants", "ab" * 16
MAIN, DEV, PLUGIN = None, "dev", "demo-plugin:reviewer"


def run(tool: str, tool_input: dict, role, home: Path, state=None, dispatch=None):
    """The hook's exit code and stderr for one call; role None is the main agent. ``dispatch`` is the
    caller's own dispatch record (_dispatched): its agent id and the session transcript."""
    payload = {"session_id": SID, "cwd": PROJECT, "hook_event_name": "PreToolUse",
               "tool_name": tool, "tool_input": tool_input}
    if role:
        payload.update(agent_id=dispatch[0] if dispatch else "a" + uuid.uuid4().hex[:16], agent_type=role)
    if dispatch:
        payload["transcript_path"] = str(dispatch[1])
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), CLAUDE_PROJECT_DIR=PROJECT,
               PYTHONDONTWRITEBYTECODE="1")
    if state:
        env["CLAUDE_STATE_DIR"] = str(state)
    proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                          text=True, env=env, timeout=60)
    assert not Path(PROJECT).parent.exists(), "the policy check must not create the project"
    return proc.returncode, proc.stderr


def _denial(code: int, stderr: str) -> dict:
    assert code == 2, stderr
    return json.loads(stderr.splitlines()[0][len(BLOCK):])


# State dirs: the default /tmp, one outside the temp roots, one below /tmp (pytest's tmp_path).
@pytest.fixture(params=["default", "outside", "below-tmp"])
def state(request, tmp_path):
    return {"default": None, "outside": "/nonexistent-p6-grant-binding/state",
            "below-tmp": str(tmp_path / "state")}[request.param]


def _grant(analyst: str, state) -> str:
    return f"{state or '/tmp'}/agentic-commit/{analyst}/{REPO_HASH}/{SID}/{NONCE}.json"


def _writes(path: str):
    yield "Write", {"file_path": path, "content": "{}"}
    yield "Bash", {"command": f"cat > {path} <<EOF\n{{}}\nEOF"}


# The refusal of another caller's write: P6's grant binding (D8) for the merge-analyst's grant; for a
# push-analyst grant and the push-gate token, P5's protected stage (review H2), which decides first.
REFUSED = {"merge-analyst": "only the merge-analyst creates or overwrites a file there",
           "push-analyst": "is a push-analyst grant, which only the push-analyst dispatched for its request writes: "
                           "no agent writes, deletes or renames it (D11/D12)",
           "push": "is a push-gate token, whose one writer is scripts/write-push-gate-token.py: "
                   "no agent writes, deletes or renames it (D11/D12)"}


def _dispatched(home: Path, repo_hash: str = REPO_HASH) -> tuple:
    """commands/push.md Step 3's dispatch of the push-analyst, its placeholders bound to the grant's
    repository hash, session and request id and its obligation instantiated, in the session
    transcript, and the child the CLI starts for it (its first record and meta): (agent id, session
    transcript), for run's ``dispatch``. The grant's one writer (P5 review H2)."""
    text = (ROOT / "commands" / "push.md").read_text(encoding="utf-8")
    fence = next(b for b in re.findall(r"^```[^\n]*\n(.*?)^```", text, re.M | re.S) if "REQUEST_ID=<REQUEST_ID>" in b)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fence = re.sub(r'"<ISO-8601 UTC ending in Z[^"]*>"', f'"{now}"', fence)
    values = {"BRANCH": "main", "PRE_HEAD": "1" * 40, "RESOLVED_REMOTE": "origin", "REMOTE_URL": "/elsewhere/o.git",
              "REQUEST_ID": NONCE, "SESSION_ID": SID, "REPO_HASH": repo_hash}
    prompt = re.sub(r"<([A-Z_]+)>", lambda m: values[m[1]], fence).strip()
    store, call, agent = home / ".claude" / "projects" / "-p6-grant-binding", "toolu_p6grant0001", "a0p6push"
    (store / SID / "subagents").mkdir(parents=True, exist_ok=True)
    session = store / f"{SID}.jsonl"
    session.write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content":
                    "<command-name>/push</command-name>\n<command-args></command-args>"}}) + "\n"
        + json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": call, "name": "Agent", "input": {
                "description": "pre-push analysis", "prompt": prompt, "subagent_type": "push-analyst"}}]}}) + "\n",
        encoding="utf-8")
    (store / SID / "subagents" / f"agent-{agent}.jsonl").write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n", encoding="utf-8")
    (store / SID / "subagents" / f"agent-{agent}.meta.json").write_text(
        json.dumps({"agentType": "push-analyst", "toolUseId": call}), encoding="utf-8")
    return agent, session


@pytest.mark.parametrize("analyst", ["push-analyst", "merge-analyst"])
@pytest.mark.parametrize("caller", [MAIN, DEV, PLUGIN], ids=["main", "dev", "plugin"])
def test_only_the_analyst_writes_its_grant(tmp_path, state, analyst, caller):
    home, path = tmp_path / "home", _grant(analyst, state)
    for tool, tool_input in _writes(path):
        denial = _denial(*run(tool, tool_input, caller, home, state))
        assert denial["role"] == (caller or "main") and denial["target"] == path
        assert REFUSED[analyst] in denial["deny_reason"]
    # A push-analyst grant's analyst is the one its own dispatch binds (P5 review H2): a push-analyst
    # whose session records no dispatch of it is refused as any other caller.
    own = _dispatched(home) if analyst == "push-analyst" else None
    if own:
        for tool, tool_input in _writes(path):
            denial = _denial(*run(tool, tool_input, analyst, home, state))
            assert denial["role"] == analyst and REFUSED[analyst] in denial["deny_reason"]
    for tool, tool_input in _writes(path):
        assert run(tool, tool_input, analyst, home, state, own) == (0, "")


def test_every_write_tool_and_an_unexpanded_word_are_bound(tmp_path):
    home, path = tmp_path / "home", _grant("push-analyst", None)
    for tool, tool_input in [("Edit", {"file_path": path, "old_string": "a", "new_string": "b"}),
                             ("MultiEdit", {"file_path": path, "edits": []}),
                             ("NotebookEdit", {"notebook_path": path, "new_source": "x"}),
                             ("Bash", {"command": 'echo x > "${STATE}/agentic-commit/push-analyst/h/s/n.json"'})]:
        assert run(tool, tool_input, DEV, home)[0] == 2, tool
    # One analyst does not write the other's grant, nor the chain-B sentinel execute-push.py writes.
    assert run("Write", {"file_path": _grant("merge-analyst", None), "content": "{}"}, "push-analyst", home)[0] == 2
    sentinel = f"/tmp/agentic-commit/push-analyst/{REPO_HASH}/main-chainB.validated.sentinel.json"
    assert run("Write", {"file_path": sentinel, "content": "{}"}, MAIN, home)[0] == 2


def test_removal_and_the_rest_of_the_state_dir_are_not_bound(tmp_path):
    home = tmp_path / "home"
    # /merge Step 3's removal by the main agent (the base text), and any unlink, is no write.
    path = _grant("merge-analyst", None)
    assert run("Bash", {"command": f'rm -f "{path}"'}, MAIN, home) == (0, "")
    # A push-analyst grant is a /push Stop input, which no caller removes (P5 review H2).
    path = _grant("push-analyst", None)
    denial = _denial(*run("Bash", {"command": f'rm -f "{path}"'}, MAIN, home))
    assert denial["target"] == path and REFUSED["push-analyst"] in denial["deny_reason"]
    # A directory under agentic-commit/ that names no role binds nobody: the lock. The push-gate token
    # is no grant either: only the protected stage (review H2) refuses its write, never the binding.
    assert run("Bash", {"command": f'exec 9>"/tmp/agentic-commit/locks/{REPO_HASH}.lock"'}, MAIN, home) == (0, "")
    token = f"/tmp/agentic-commit/push/{REPO_HASH}/{SID}/main.json"
    reason = _denial(*run("Write", {"file_path": token, "content": "{}"}, MAIN, home))["deny_reason"]
    assert REFUSED["push"] in reason and "grant directory" not in reason


# -- roles the policy does not list ------------------------------------------------------------

@pytest.mark.parametrize("role", ["Explore", "Plan", "claude-code-guide", "statusline-setup", PLUGIN,
                                  "general-purpose"])
def test_an_unlisted_role_gets_no_role_row(tmp_path, role):
    home = tmp_path / "home"
    calls = [("Read", {"file_path": f"{PROJECT}/src/app.py"}), ("Grep", {"pattern": "x", "path": PROJECT}),
             ("Bash", {"command": "ls"}), ("Write", {"file_path": f"{PROJECT}/src/y.py", "content": "x"}),
             ("Edit", {"file_path": f"{PROJECT}/src/app.py", "old_string": "a", "new_string": "b"}),
             ("NotebookEdit", {"notebook_path": f"{PROJECT}/nb/a.ipynb", "new_source": "x"}),
             ("mcp__github__get_me", {})]
    for tool, tool_input in calls:
        assert run(tool, tool_input, role, home) == (0, ""), (role, tool)


@pytest.mark.parametrize("role", ["Explore", PLUGIN, "general-purpose"])
def test_an_unlisted_role_still_meets_the_derived_permission(tmp_path, role):
    """No role row is not no check: a path another dispatch declares stays that dispatch's (A5)."""
    import test_tool_policy_derived_permission as derived  # noqa: PLC0415 (hooks/tests on sys.path)

    s = derived.Session(tmp_path / "projects")
    s.command("dev")
    s.dispatch("You are the BA subagent.\n" + derived._block(derived._obligation("ba", "singular", derived.CONTEXT)))
    other = s.dispatch("Look around the toy package.", role)
    denial = derived._denial(s.run(tmp_path, "Write", derived._write(derived.CONTEXT), (other, role)))
    assert denial["role"] == role and denial["deny_reason"].endswith("only ba writes this artifact (D8)")


def test_general_purpose_keeps_todays_behaviour_and_a_listed_role_keeps_its_row(tmp_path):
    policy = json.loads((ROOT / "policies" / "tool-policy.v1.json").read_text())
    assert "general-purpose" not in policy["roles"]
    home = tmp_path / "home"
    assert run("Write", {"file_path": f"{PROJECT}/src/z.py", "content": "x"}, "general-purpose", home) == (0, "")
    assert run("Write", {"file_path": f"{PROJECT}/src/y.py", "content": "x"}, DEV, home) == (0, "")
    denial = _denial(*run("Edit", {"file_path": f"{PROJECT}/src/app.py", "old_string": "a", "new_string": "b"},
                          "qa", home))
    assert denial["role"] == "qa" and "write_path_prefixes" in denial["deny_reason"]


# -- the never-registered analysts' documented steps -------------------------------------------

FENCE = re.compile(r"^[ \t]*```([A-Za-z]*)[^\n]*\n(.*?)^[ \t]*```", re.M | re.S)


def _bash_blocks(agent: str, kind: str = "agents"):
    text = (ROOT / kind / f"{agent}.md").read_text(encoding="utf-8")
    return [m.group(2) for m in FENCE.finditer(text) if m.group(1) in ("bash", "sh")]


def _documented_writes(agent: str, state) -> list:
    """The Write targets the agent file names, its placeholders bound."""
    text = (ROOT / "agents" / f"{agent}.md").read_text(encoding="utf-8")
    sd = state or "/tmp"
    if agent == "changelog-analyst":
        msgfiles = set(re.findall(r"MSGFILE=(\S+?commit-msg-<unique>\.txt)", text))
        annotation = re.findall(r'CLOSE_ANNOTATION="\$\{CONTROL_ROOT\}(/docs/dev/close-report-bulk-)', text)
        assert msgfiles and annotation, "the CP-1 message file and the bulk close annotation are documented"
        return [m.replace("<unique>", "p6") for m in msgfiles] + [f"{PROJECT}{annotation[0]}bulk-1.md"]
    grant_dir = re.search(r"^GRANT_DIR=\$\{STATE_DIR\}(/agentic-commit/[a-z-]+/)<REPO_HASH>/<SESSION_ID>$",
                          text, re.M)
    return [f"{sd}{grant_dir.group(1)}{REPO_HASH}/{SID}/{NONCE}.json"] if grant_dir else []


# Steps of the text a running agent may still hold: the fd-9 lock spelled with the hash expanded,
# the push-gate token's one writer, the analysts' former audit log (mkdir and append).
OLDER = {
    "changelog-analyst": [f'exec 9>"/tmp/agentic-commit/locks/{REPO_HASH}.lock"',
                          'python3 ~/.claude/scripts/write-push-gate-token.py --repo-root "/r" --branch "main" '
                          '--commit "0123abc"'],
    "push-analyst": ["mkdir -p /tmp/agentic-commit/push-analyst/audit/",
                     f"printf 'x\\n' >> /tmp/agentic-commit/push-analyst/audit/{REPO_HASH}.log"],
    "merge-analyst": ["mkdir -p /tmp/agentic-commit/merge-analyst/audit/",
                      f"printf 'x\\n' >> /tmp/agentic-commit/merge-analyst/audit/{REPO_HASH}.log"],
    "pull-analyst": [],
}


@pytest.mark.parametrize("agent", sorted(OLDER))
def test_a_never_registered_analyst_keeps_every_documented_step(tmp_path, state, agent):
    home = tmp_path / "home"
    blocks = _bash_blocks(agent)
    assert blocks
    if agent == "changelog-analyst":
        assert any('exec 9>"/tmp/agentic-commit/locks/${REPO_HASH}.lock"' in b for b in blocks)
    # The push-analyst runs from its /push dispatch, whose record binds the grant it writes (P5 review H2).
    own = _dispatched(home) if agent == "push-analyst" else None
    refused = []
    for command in blocks + OLDER[agent]:
        code, err = run("Bash", {"command": command}, agent, home, state, own)
        refused += [(command[:80], err)] if code else []
    for path in _documented_writes(agent, state):
        code, err = run("Write", {"file_path": path, "content": "{}"}, agent, home, state, own)
        refused += [(path, err)] if code else []
    assert not refused


@pytest.mark.parametrize("command", ["push", "merge"])
def test_the_main_agents_push_and_merge_steps_pass(tmp_path, command):
    """The main agent's own Bash steps of /push and /merge (execute-push.py, merge.sh) write no grant."""
    blocks = _bash_blocks(command, "commands")
    assert blocks
    for block in blocks:
        assert run("Bash", {"command": block}, MAIN, tmp_path / "home") == (0, ""), block[:80]


# -- /push end to end: the grant its analyst wrote, execute-push.py, a local bare origin --------

def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


def test_execute_push_completes_with_its_chain_b_sentinel(tmp_path):
    home, state = tmp_path / "home", tmp_path / "state"
    origin, repo = tmp_path / "origin.git", tmp_path / "toy"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    for key, value in (("user.email", "t@example.invalid"), ("user.name", "t"), ("commit.gpgsign", "false")):
        _git(repo, "config", key, value)
    (repo / "f.txt").write_text("x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "remote", "add", "origin", str(origin))
    head, top = _git(repo, "rev-parse", "HEAD"), _git(repo, "rev-parse", "--show-toplevel")
    repo_hash = hashlib.sha256(os.path.realpath(top).encode()).hexdigest()[:16]
    # The push-gate token /commit's changelog-analyst left (its writer's product).
    token = state / "agentic-commit" / "push" / repo_hash / "sid-digest" / "main.json"
    token.parent.mkdir(parents=True)
    token.write_text(json.dumps({"commit_sha": head}))
    # The push-analyst's grant Write passes the hook, then lands as the Write tool would land it.
    grant = state / "agentic-commit" / "push-analyst" / repo_hash / SID / f"{NONCE}.json"
    body = {"verdict": "approved", "risks": [], "analysis_summary": "ok", "branch": "main", "head_sha": head,
            "remote_name": "origin", "remote_url": str(origin), "session_id": SID, "nonce": NONCE,
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=600)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    own = _dispatched(home, repo_hash)  # the /push dispatch whose record binds this grant (P5 review H2)
    assert run("Write", {"file_path": str(grant), "content": json.dumps(body)}, "push-analyst", home, state,
               own) == (0, "")
    grant.parent.mkdir(parents=True)
    grant.write_text(json.dumps(body))
    command = (f'python3 ~/.claude/scripts/execute-push.py --repo-hash "{repo_hash}" --branch "main" '
               f'--remote "origin" --request-id "{NONCE}" --repo-root "{top}"')
    assert run("Bash", {"command": command}, MAIN, home, state) == (0, "")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_"))}
    env.update(CLAUDE_STATE_DIR=str(state), CLAUDE_SESSION_ID=SID, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "execute-push.py"), "--repo-hash", repo_hash,
                           "--branch", "main", "--remote", "origin", "--request-id", NONCE, "--repo-root", top],
                          capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "execute-push: sentinel written" in proc.stdout
    assert _git(origin, "rev-parse", "refs/heads/main") == head
    assert not grant.exists(), "execute-push.py spends the grant"
