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


# -- in-flight compatibility: the message file of 2acc29b's changelog-analyst (train 2, A17) ------
# COMPATIBILITY: these cases go with pretool-tool-policy.py's _check_inflight_msg_writes, once no
# session predates train 2's landing. A session started on origin/master's text before train 1
# landed keeps 2acc29b's agents/changelog-analyst.md (D15), whose Write tool writes its `git commit
# -F` message file at these names (:1099 Phase 8, :557 bulk groups, :71 CP-1), placeholders bound.
INFLIGHT_MSGFILES = [
    "/tmp/commit-msg-<TASK_ID-or-bulk>-<short-rand>.txt".replace("<TASK_ID-or-bulk>", "20260101-000000")
    .replace("<short-rand>", "r0001x"),
    "/tmp/commit-msg-<TASK_ID-or-bulk>-<short-rand>.txt".replace("<TASK_ID-or-bulk>", "bulk")
    .replace("<short-rand>", "a1b2"),
    "/tmp/commit-msg-<unique>-<group index>.txt".replace("<unique>", "dev-20260101-000000").replace("<group index>", "2"),
    "/tmp/commit-msg-<unique>.txt".replace("<unique>", "1767225600.x9"),
]
INFLIGHT_REFUSED = "only the changelog-analyst writes it (D8)"


def test_an_in_flight_changelog_analyst_writes_its_commit_message_file(tmp_path, state):
    home = tmp_path / "home"
    for path in INFLIGHT_MSGFILES:
        assert run("Write", {"file_path": path, "content": "fix(toy): x\n\nTask-id: 1\n"}, "changelog-analyst",
                   home, state) == (0, ""), path


@pytest.mark.parametrize("caller", [MAIN, DEV, "qa", "push-analyst", PLUGIN, "general-purpose"])
def test_no_other_caller_writes_the_in_flight_message_file(tmp_path, caller):
    home = tmp_path / "home"
    for path in INFLIGHT_MSGFILES:
        for tool, tool_input in [*_writes(path), ("Edit", {"file_path": path, "old_string": "a", "new_string": "b"})]:
            denial = _denial(*run(tool, tool_input, caller, home))
            assert denial["role"] == (caller or "main") and denial["target"] == path, (tool, path)
            assert denial["deny_reason"].endswith(INFLIGHT_REFUSED), denial


def test_the_in_flight_message_file_widens_nothing_else(tmp_path):
    """The analyst gains that one name, by the Write tool, directly in /tmp and resolving to itself;
    every other write keeps its role row (its scratch directory and the rest refused as before)."""
    home, path = tmp_path / "home", INFLIGHT_MSGFILES[0]
    near = ["/tmp/commit-msg-1-r.txt.sh", "/tmp/commit-msg-1-r.json", "/tmp/sub/commit-msg-1-r.txt",
            "/var/tmp/commit-msg-1-r.txt", "/tmp/commit-msgx.txt", "/tmp/commit-msg-.txt", "/tmp/commit-msg-1/../x.txt",
            "/tmp/x-commit-msg-1-r.txt", f"{PROJECT}/commit-msg-1-r.txt"]
    for target in near:
        denial = _denial(*run("Write", {"file_path": target, "content": "x"}, "changelog-analyst", home))
        assert INFLIGHT_REFUSED not in denial["deny_reason"], target
    for tool, tool_input, reason in [("Bash", {"command": f"cat > {path} <<EOF\nx\nEOF"},
                                      "not in allowed_write_path_prefixes"),
                                     ("Edit", {"file_path": path, "old_string": "a", "new_string": "b"},
                                      "tool Edit not in allowed_tools")]:
        assert reason in _denial(*run(tool, tool_input, "changelog-analyst", home))["deny_reason"], tool
    # A link of that name leads the Write elsewhere: no message file, the role row refuses it.
    link = Path(f"/tmp/commit-msg-{uuid.uuid4().hex}.txt")
    link.symlink_to(tmp_path / "elsewhere.txt")
    try:
        denial = _denial(*run("Write", {"file_path": str(link), "content": "x"}, "changelog-analyst", home))
        assert "not in allowed_write_path_prefixes" in denial["deny_reason"]
    finally:
        link.unlink()


# COMPATIBILITY (T2-11), with the cases above: the same text's nothing_to_commit_precommitted recovery route
# (Recovery step 3, :1887) has the Write tool write its `git commit --allow-empty -F` message file at
# /tmp/recovery-commit-<TASK_ID>-<short-rand>.txt, placeholders bound (a /dev and a /do task id).
INFLIGHT_RECOVERY_MSGFILES = [
    "/tmp/recovery-commit-<TASK_ID>-<short-rand>.txt".replace("<TASK_ID>", "20260101-000000")
    .replace("<short-rand>", "r0001x"),
    "/tmp/recovery-commit-<TASK_ID>-<short-rand>.txt".replace("<TASK_ID>", "do-20260101-000000-ab12")
    .replace("<short-rand>", "a1b2"),
]


def test_an_in_flight_changelog_analyst_writes_its_recovery_commit_message_file(tmp_path, state):
    home = tmp_path / "home"
    for path in [*INFLIGHT_RECOVERY_MSGFILES, INFLIGHT_MSGFILES[0]]:
        assert run("Write", {"file_path": path, "content": "chore(toy): recovery commit\n\nTask-id: 1\n"},
                   "changelog-analyst", home, state) == (0, ""), path


@pytest.mark.parametrize("caller", [MAIN, DEV, "qa", "push-analyst", PLUGIN, "general-purpose"])
def test_no_other_caller_writes_the_in_flight_recovery_message_file(tmp_path, caller):
    home = tmp_path / "home"
    for path in INFLIGHT_RECOVERY_MSGFILES:
        for tool, tool_input in [*_writes(path), ("Edit", {"file_path": path, "old_string": "a", "new_string": "b"})]:
            denial = _denial(*run(tool, tool_input, caller, home))
            assert denial["role"] == (caller or "main") and denial["target"] == path, (tool, path)
            assert denial["deny_reason"].endswith(INFLIGHT_REFUSED), denial


def test_the_in_flight_recovery_message_file_widens_nothing_else(tmp_path):
    """The recovery name is that one name too: by the Write tool, directly in /tmp, resolving to itself."""
    home, path = tmp_path / "home", INFLIGHT_RECOVERY_MSGFILES[0]
    near = ["/tmp/recovery-commit-1-r.txt.sh", "/tmp/recovery-commit-1-r.json", "/tmp/sub/recovery-commit-1-r.txt",
            "/var/tmp/recovery-commit-1-r.txt", "/tmp/recovery-commitx.txt", "/tmp/recovery-commit-.txt",
            "/tmp/recovery-commit-1/../x.txt", "/tmp/x-recovery-commit-1-r.txt", "/tmp/Recovery-commit-1-r.txt",
            "/tmp/recovery-commit-msg-1.txt.bak", f"{PROJECT}/recovery-commit-1-r.txt"]
    for target in near:
        denial = _denial(*run("Write", {"file_path": target, "content": "x"}, "changelog-analyst", home))
        assert INFLIGHT_REFUSED not in denial["deny_reason"], target
    for tool, tool_input, reason in [("Bash", {"command": f"cat > {path} <<EOF\nx\nEOF"},
                                      "not in allowed_write_path_prefixes"),
                                     ("Edit", {"file_path": path, "old_string": "a", "new_string": "b"},
                                      "tool Edit not in allowed_tools")]:
        assert reason in _denial(*run(tool, tool_input, "changelog-analyst", home))["deny_reason"], tool
    link = Path(f"/tmp/recovery-commit-{uuid.uuid4().hex}.txt")
    link.symlink_to(tmp_path / "elsewhere.txt")
    try:
        denial = _denial(*run("Write", {"file_path": str(link), "content": "x"}, "changelog-analyst", home))
        assert "not in allowed_write_path_prefixes" in denial["deny_reason"]
    finally:
        link.unlink()


def test_this_trees_recovery_route_writes_its_message_file_under_its_prefixes(tmp_path):
    """The tree's own Recovery step 3 names its message file in the role's scratch directory, not the in-flight
    name: its role row lets it through, with no compatibility rule."""
    text = (ROOT / "agents" / "changelog-analyst.md").read_text(encoding="utf-8")
    step = text[text.index("**Recovery step 3"):text.index("**Recovery step 4")]
    names = re.findall(r"MSGFILE=(\S+?)`", step)
    assert names and not any(re.search(r"/tmp/recovery-commit-", n) for n in names), names
    for name in names:
        path = name.replace("<unique>", "20260101-000000-r0001x")
        assert path.startswith("/tmp/claude-scratch/changelog-analyst/"), path
        assert run("Write", {"file_path": path, "content": "x"}, "changelog-analyst", tmp_path / "home") == (0, "")


# -- in-flight compatibility: the registry entry 2acc29b's test-writer creates (train 2, A17) -----
# COMPATIBILITY: these cases go with pretool-tool-policy.py's _check_inflight_entry_writes, once no
# session predates train 2's landing. A session that took up origin/master's /dev text keeps its
# test-writer dispatch (2acc29b commands/dev.md:799, D15), whose FIRST ACTION line is quoted below;
# the train arms the registry with no sentinel in it (hooks/pretool-cp-checkin.py creates one at the
# FIRST ACTION Read), so that test-writer may find its entry absent and create it. Here the project
# and its armed registries exist; the session store is the CLI's (the dispatch record, the child's
# first record and its meta).
ENTRY_TASK, OTHER_TASK = "dev-20261108-150427", "dev-20261108-160000"
MASTER_FIRST = ("FIRST ACTION: Read $CLAUDE_PROJECT_DIR/.claude/dev-registry/<DEV_SESSION_ID>/test-writer.json "
                "(or create if absent with {agent_type:'test-writer', session_id:'<DEV_SESSION_ID>'}).")
ENTRY_REFUSED = "only that test-writer writes it (D8, D24)"


def _train_first() -> str:
    """The FIRST ACTION line of this tree's test-writer dispatch (commands/dev.md Step 10)."""
    text = (ROOT / "commands" / "dev.md").read_text(encoding="utf-8")
    return next(l.strip() for l in text.splitlines() if "FIRST ACTION" in l and "/test-writer.json" in l)


def _test_writer_prompt(first: str, task: str = ENTRY_TASK, named: str = ENTRY_TASK) -> str:
    """A test-writer dispatch prompt as the orchestrator renders it: ``first`` with its registry
    named for ``named``, and the obligation of cycle ``task`` (2acc29b commands/dev.md:799-819)."""
    obligation = {"task_id": task, "lane": None, "lane_set": None, "role": "test-writer", "pipeline": "dev",
                  "profile": "singular", "dispatched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "artifacts": [{"kind": "json", "path": f"docs/dev/test-writer-report-{task}.json",
                                 "schema": "test-writer-report.v1", "identity": {"task_id": task}},
                                {"kind": "json", "path": f"tests/generated/{task}/manifest.json",
                                 "schema": "test-writer-manifest.v1", "identity": {"task_id": task}}]}
    return (first.replace("<DEV_SESSION_ID>", named) + "\n\nYou are the test-writer subagent. Follow "
            "agents/test-writer.md instructions precisely.\n\n<obligation v=\"1\">\n"
            + json.dumps(obligation, indent=2) + "\n</obligation>\n\nInputs:\n  task_id: " + task + "\n")


class _Cycle:
    """A project whose cycles' registries are armed, and a session that dispatched subagents in it."""

    def __init__(self, tmp_path: Path):
        self.home, self.project = tmp_path / "home", tmp_path / "proj"
        for task in (ENTRY_TASK, OTHER_TASK):
            (self.project / ".claude" / "dev-registry" / task).mkdir(parents=True)
        self.store = self.home / ".claude" / "projects" / "-inflight-entry"
        (self.store / SID / "subagents").mkdir(parents=True)
        self.session = self.store / f"{SID}.jsonl"
        self.session.write_text(json.dumps({"type": "user", "message": {"role": "user", "content":
                                "<command-name>/dev</command-name>\n<command-args>x</command-args>"}}) + "\n")

    def entry(self, task: str = ENTRY_TASK, name: str = "test-writer") -> str:
        return str(self.project / ".claude" / "dev-registry" / task / f"{name}.json")

    def dispatch(self, prompt: str, subagent_type: str = "test-writer") -> str:
        call, agent = "toolu_" + uuid.uuid4().hex[:20], "a" + uuid.uuid4().hex[:16]
        with self.session.open("a") as fh:
            fh.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": call, "name": "Agent", "input": {
                    "description": "d", "prompt": prompt, "subagent_type": subagent_type}}]}}) + "\n")
        sub = self.store / SID / "subagents"
        (sub / f"agent-{agent}.jsonl").write_text(
            json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n")
        (sub / f"agent-{agent}.meta.json").write_text(json.dumps({"agentType": subagent_type, "toolUseId": call}))
        return agent

    def run(self, tool: str, tool_input: dict, role, agent: str | None = None):
        payload = {"session_id": SID, "transcript_path": str(self.session), "cwd": str(self.project),
                   "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}
        if role:
            payload.update(agent_id=agent or "a" + uuid.uuid4().hex[:16], agent_type=role)
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
        env.update(HOME=str(self.home), CLAUDE_CONFIG_DIR=str(self.home / ".claude"),
                   CLAUDE_PROJECT_DIR=str(self.project), PYTHONDONTWRITEBYTECODE="1")
        proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                              text=True, env=env, timeout=60)
        return proc.returncode, proc.stderr


def _entry_writes(path: str):
    yield "Write", {"file_path": path, "content": "{}\n"}
    yield "Bash", {"command": f"cat > {path} <<EOF\n{{}}\nEOF"}
    yield "Edit", {"file_path": path, "old_string": "a", "new_string": "b"}


def test_an_in_flight_test_writer_creates_its_own_cycles_registry_entry(tmp_path):
    cycle = _Cycle(tmp_path)
    agent = cycle.dispatch(_test_writer_prompt(MASTER_FIRST))
    content = json.dumps({"agent_type": "test-writer", "session_id": ENTRY_TASK}) + "\n"
    assert cycle.run("Write", {"file_path": cycle.entry(), "content": content}, "test-writer", agent) == (0, "")


def test_the_in_flight_test_writer_writes_no_other_entry(tmp_path):
    """Its own cycle's entry, by the Write tool, while absent, its dispatch naming that create: every
    other write keeps its role row (another cycle's entry or another role's, the entry once the
    hook created it, its Bash or Edit write, a dispatch from this tree's text, a prompt naming another
    cycle's registry, an unarmed cycle)."""
    cycle = _Cycle(tmp_path)
    agent = cycle.dispatch(_test_writer_prompt(MASTER_FIRST))
    write = {"content": "{}\n"}
    for target in [cycle.entry(OTHER_TASK), cycle.entry(name="ba"), cycle.entry(name="dev"),
                   cycle.entry(name="test-writer-2"), str(cycle.project / ".claude" / "dev-registry" / "test-writer.json")]:
        denial = _denial(*cycle.run("Write", dict(write, file_path=target), "test-writer", agent))
        assert denial["deny_reason"].endswith("not in allowed_write_path_prefixes"), target
    for tool, tool_input in list(_entry_writes(cycle.entry()))[1:]:
        assert ENTRY_REFUSED not in _denial(*cycle.run(tool, tool_input, "test-writer", agent))["deny_reason"], tool
    for prompt, target in [(_test_writer_prompt(_train_first()), cycle.entry()),
                           (_test_writer_prompt(MASTER_FIRST, named=OTHER_TASK), cycle.entry(OTHER_TASK)),
                           (_test_writer_prompt(MASTER_FIRST, named=OTHER_TASK), cycle.entry()),
                           (_test_writer_prompt(MASTER_FIRST, task="dev-20261108-170000",
                                                named="dev-20261108-170000"), cycle.entry("dev-20261108-170000"))]:
        denial = _denial(*cycle.run("Write", dict(write, file_path=target), "test-writer", cycle.dispatch(prompt)))
        assert denial["deny_reason"].endswith("not in allowed_write_path_prefixes"), (prompt[:120], target)
    Path(cycle.entry()).write_text("{}\n")  # the sentinel hooks/pretool-cp-checkin.py creates at a Read
    denial = _denial(*cycle.run("Write", dict(write, file_path=cycle.entry()), "test-writer", agent))
    assert denial["deny_reason"].endswith("not in allowed_write_path_prefixes")


@pytest.mark.parametrize("caller", [MAIN, DEV, "qa", "ba", PLUGIN, "general-purpose"])
def test_no_other_caller_writes_the_test_writer_entry(tmp_path, caller):
    """Not the main agent, dev (whose row allows '*'), qa, BA, a plugin or built-in role; also when
    it was dispatched with the in-flight test-writer's own prompt."""
    cycle = _Cycle(tmp_path)
    agent = cycle.dispatch(_test_writer_prompt(MASTER_FIRST), caller or "test-writer") if caller else None
    for task in (ENTRY_TASK, OTHER_TASK):
        for tool, tool_input in _entry_writes(cycle.entry(task)):
            denial = _denial(*cycle.run(tool, tool_input, caller, agent))
            assert denial["role"] == (caller or "main") and denial["target"] == cycle.entry(task), (tool, task)
            assert denial["deny_reason"].endswith(ENTRY_REFUSED), denial


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
