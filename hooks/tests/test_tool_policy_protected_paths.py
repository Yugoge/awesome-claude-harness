"""P5 R2, R3, R5: what no caller writes, deletes or renames, and the scheduled prompt that types a command.

hooks/pretool-tool-policy.py refuses, before every other rule and for the main agent and every
subagent alike, a write, delete or rename of the harness home's settings.machine.json,
private-literals.txt, scripts/check-public-core.sh, scripts/install/render-settings,
hooks/git-hooks/pre-commit, .git/config, .git/hooks/ and .gitattributes; of a session transcript
(``${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects/**/*.jsonl``) and the agent meta beside it; and of a
/do task sidecar (``claude-do-task-*.json`` in the state dir); and of what the /push Stop reads (P5
review H2): the push-gate token tree (``<state dir>/agentic-commit/push/``, whose one writer is a
script no tool call shows) and a push-analyst grant, which only the push-analyst subagent whose own
dispatch, made from commands/push.md's Step 3 template, binds that grant's path writes. A product
repository's files of the same names, the graphify sidecars and every other path stay writable.
Deleting or renaming a directory that holds one counts: under the projects tree, a directory holding
a transcript or meta; in the state dir, one holding a token or a grant.
A ScheduleWakeup prompt that types a harness command outside CONTROL is refused; a CronCreate
prompt's fired record is measured (P1's COV-7) and excluded from the human's prompts, so it is not.

The harness home is this checkout (the hook resolves it from its own location); only paths are
judged, and nothing is created but the projects tree's files a directory's case puts in tmp_path.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", ".."))
HOOK = os.path.join(ROOT, "hooks", "pretool-tool-policy.py")
SID = "0c1d2e3f-4a5b-4c6d-8e7f-0a1b2c3d4e5f"
R3 = ("scripts/check-public-core.sh", "scripts/install/render-settings", "hooks/git-hooks/pre-commit",
      ".git/config", ".git/hooks/pre-commit", ".gitattributes")
CALLERS = {"main": None, "dev": ("a0dev", "dev"), "ba": ("a0ba", "ba")}
# A product repository outside /tmp and /var/tmp (the scratch rule denies every role there), never created.
PRODUCT = "/nonexistent-p5-protected-paths/product"


def run(tmp_path, tool: str, tool_input: dict, caller=None, state: bool | str = True, cwd=None):
    home = tmp_path / "home"
    payload = {"session_id": SID, "transcript_path": str(home / ".claude" / "projects" / "-p" / f"{SID}.jsonl"),
               "cwd": str(cwd or PRODUCT), "hook_event_name": "PreToolUse", "tool_name": tool,
               "tool_input": tool_input}
    if caller:
        payload.update(agent_id=caller[0], agent_type=caller[1], subagent_type=caller[1])
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), CLAUDE_PROJECT_DIR=PRODUCT,
               PYTHONDONTWRITEBYTECODE="1")
    if state:
        env["CLAUDE_STATE_DIR"] = state if isinstance(state, str) else str(tmp_path / "state")
    return subprocess.run([sys.executable, HOOK], input=json.dumps(payload), capture_output=True, text=True,
                          cwd=str(tmp_path), env=env, timeout=60)


def forms(path: str) -> dict:
    """Each way to write, delete or rename ``path``: tool -> input."""
    return {"Write": ("Write", {"file_path": path, "content": "x"}),
            "Edit": ("Edit", {"file_path": path, "old_string": "a", "new_string": "b"}),
            "echo": ("Bash", {"command": f"echo x > {path}"}),
            "rm": ("Bash", {"command": f"rm -f {path}"}),
            "mv": ("Bash", {"command": f"mv {path} {path}.bak"}),
            "mv-in": ("Bash", {"command": f"mv /elsewhere/x '{path}'"}),
            "sed": ("Bash", {"command": f"sed -i 's/a/b/' {path}"})}


def assert_denied(proc, what: str) -> None:
    assert proc.returncode == 2, proc.stderr
    assert proc.stderr.startswith("BLOCKED by tool-policy.v1: "), proc.stderr
    reason = json.loads(proc.stderr.splitlines()[0].split(": ", 1)[1])["deny_reason"]
    assert reason.endswith(f"is {what}: no agent writes, deletes or renames it (D11/D12)"), reason


def r2_paths(tmp_path) -> dict:
    config = tmp_path / "home" / ".claude" / "projects" / "-p"
    return {"settings.machine.json": (os.path.join(ROOT, "settings.machine.json"), "the harness home's settings.machine.json"),
            "private-literals.txt": (os.path.join(ROOT, "private-literals.txt"), "the harness home's private-literals.txt"),
            "transcript": (str(config / f"{SID}.jsonl"), "a session transcript or its subagent meta"),
            "subagent transcript": (str(config / SID / "subagents" / "agent-a1.jsonl"),
                                    "a session transcript or its subagent meta"),
            "subagent meta": (str(config / SID / "subagents" / "agent-a1.meta.json"),
                              "a session transcript or its subagent meta"),
            "do sidecar": (str(tmp_path / "state" / f"claude-do-task-{SID}.json"), "a /do task sidecar")}


@pytest.mark.parametrize("caller", list(CALLERS))
@pytest.mark.parametrize("form", ["Write", "Edit", "echo", "rm", "mv", "mv-in"])
@pytest.mark.parametrize("name", ["settings.machine.json", "private-literals.txt", "transcript", "subagent transcript",
                                  "subagent meta", "do sidecar"])
def test_r2_paths_are_denied_to_every_caller(tmp_path, caller, form, name):
    path, what = r2_paths(tmp_path)[name]
    assert_denied(run(tmp_path, *forms(path)[form], CALLERS[caller]), what)


@pytest.mark.parametrize("form", ["Write", "echo", "rm", "mv"])
def test_the_do_sidecar_without_a_state_dir_is_the_default_roots(tmp_path, form):
    assert_denied(run(tmp_path, *forms(f"/tmp/claude-do-task-{SID}.json")[form], state=False), "a /do task sidecar")
    # ... and named through the variable the agent's shell holds
    proc = run(tmp_path, "Bash", {"command": f'rm -f "$CLAUDE_STATE_DIR/claude-do-task-{SID}.json"'})
    assert_denied(proc, "a /do task sidecar")


@pytest.mark.parametrize("caller", list(CALLERS))
@pytest.mark.parametrize("form", ["Write", "Edit", "rm", "sed"])
@pytest.mark.parametrize("rel", R3)
def test_r3_engines_and_git_files_of_the_harness_home_are_denied(tmp_path, caller, form, rel):
    proc = run(tmp_path, *forms(os.path.join(ROOT, rel))[form], CALLERS[caller])
    assert_denied(proc, f"the harness home's {rel}")


def test_a_relative_name_is_read_from_the_working_directory(tmp_path):
    assert_denied(run(tmp_path, "Bash", {"command": "sed -i s/a/b/ .gitattributes"}, cwd=ROOT),
                  "the harness home's .gitattributes")
    assert_denied(run(tmp_path, "Bash", {"command": "rm -r .git"}, CALLERS["dev"], cwd=ROOT),
                  "a directory holding the harness home's protected files or the session transcripts")


@pytest.mark.parametrize("form", ["Write", "Edit", "echo", "rm", "mv", "sed"])
@pytest.mark.parametrize("rel", R3 + ("settings.machine.json", "private-literals.txt"))
def test_the_same_names_in_a_product_repository_stay_writable(tmp_path, form, rel):
    proc = run(tmp_path, *forms(os.path.join(PRODUCT, rel))[form], CALLERS["dev"])
    assert proc.returncode == 0, proc.stderr
    assert not os.path.exists(os.path.dirname(PRODUCT))


HELD = "a directory holding the harness home's protected files or the session transcripts"


def sessions(tmp_path):
    """A project of the config's projects tree as the CLI keeps it: the session transcript, a
    subagent's transcript and meta (what the D8 rule reads) and the project's memory."""
    project = tmp_path / "home" / ".claude" / "projects" / "-p"
    (project / SID / "subagents").mkdir(parents=True)
    (project / "memory").mkdir()
    for f in (f"{SID}.jsonl", f"{SID}/subagents/agent-a1.jsonl", f"{SID}/subagents/agent-a1.meta.json",
              "memory/MEMORY.md"):
        (project / f).write_text("{}\n")
    return project


@pytest.mark.parametrize("caller", list(CALLERS))
@pytest.mark.parametrize("command", [
    "rm -rf $CLAUDE_CONFIG_DIR/projects/-p/{sid}/subagents", "mv $CLAUDE_CONFIG_DIR/projects/-p/{sid} /tmp/x",
    "rm -rf $CLAUDE_CONFIG_DIR/projects/-p", "rm -r {project}/{sid}/subagents/", "mv {project}/{sid} {project}/old",
    "git rm -r -q {project}/{sid}",
    # the last word is no destination where xargs appends words or -t names the target directory
    "echo /elsewhere/y | xargs mv /elsewhere/a {project}/{sid}", "mv -t /elsewhere {project}/{sid}"])
def test_a_directory_holding_transcripts_or_metas_is_denied(tmp_path, caller, command):
    project = sessions(tmp_path)
    proc = run(tmp_path, "Bash", {"command": command.format(project=project, sid=SID)}, CALLERS[caller])
    assert_denied(proc, HELD)
    assert (project / SID / "subagents" / "agent-a1.meta.json").is_file()


@pytest.mark.parametrize("command,what", [
    ("mv /elsewhere/{sid}.jsonl {project}/", "a session transcript or its subagent meta"),
    ("mv -f /elsewhere/b /elsewhere/agent-a1.meta.json {project}/{sid}/subagents",
     "a session transcript or its subagent meta"),
    ("mv /elsewhere/settings.machine.json {root}/", "the harness home's settings.machine.json"),
    ("git mv hooks {root}/.git", "the harness home's .git/hooks")])
def test_a_move_into_a_directory_over_a_protected_file_is_denied(tmp_path, command, what):
    """A directory moved into loses the entry of each source's name: that entry is judged."""
    project = sessions(tmp_path)
    assert_denied(run(tmp_path, "Bash", {"command": command.format(project=project, sid=SID, root=ROOT)}), what)


@pytest.mark.parametrize("caller", list(CALLERS))
@pytest.mark.parametrize("command", [
    "rm -rf {project}/memory", "rm -rf {project}/{sid}/tool-results", "mv {project}/memory /elsewhere/memory",
    "mv /elsewhere/x {project}/", "mv -v /elsewhere/x /elsewhere/y {project}/{sid}/", "mv /elsewhere/x {parent}/",
    "git rm -r --cached {project}", "rm -rf /nonexistent-p5-protected-paths/b",
    'd=$(mktemp -d) && touch "$d/a.jsonl" && rm -rf "$d"'])
def test_a_removal_or_move_over_no_protected_file_is_not_denied(tmp_path, caller, command):
    """A directory of the projects tree holding no transcript or meta, a move into a directory (the
    harness home's parent too), `git rm --cached`, a removal outside the config dir and a temp
    directory a command makes are no protected path's business."""
    project = sessions(tmp_path)
    command = command.format(project=project, sid=SID, parent=os.path.dirname(ROOT))
    proc = run(tmp_path, "Bash", {"command": command}, CALLERS[caller])
    assert "D11/D12" not in proc.stderr and (CALLERS[caller] or proc.returncode == 0), proc.stderr


def test_reads_and_other_config_files_stay_allowed(tmp_path):
    for path, _ in r2_paths(tmp_path).values():
        assert run(tmp_path, "Read", {"file_path": path}).returncode == 0
        assert run(tmp_path, "Bash", {"command": f"cat {path} | head"}).returncode == 0
    memory = tmp_path / "home" / ".claude" / "projects" / "-p" / "memory" / "MEMORY.md"
    assert run(tmp_path, "Write", {"file_path": str(memory), "content": "x"}).returncode == 0
    assert run(tmp_path, "Bash", {"command": f"git rm --cached {ROOT}/private-literals.txt"}).returncode == 0


def test_the_graphify_sidecar_commands_stay_allowed(tmp_path):
    # commands/dev-overnight.md's pre-BA hydrator block, its placeholders bound, as the main agent runs it.
    text = open(os.path.join(ROOT, "commands", "dev-overnight.md"), encoding="utf-8").read()
    block = next(b for b in re.findall(r"```bash\n(.*?)```", text, re.S) if "graphify/requirement.txt" in b)
    command = re.sub(r"<DEV_SESSION_ID>", "20261101-091100", block)
    command = re.sub(r"\{pipeline\.(\w+)\}", lambda m: {"index": "1"}.get(m[1], "x"), command)
    assert run(tmp_path, "Bash", {"command": command}).returncode == 0


def _wake_prompt():
    sys.path.insert(0, os.path.join(ROOT, "hooks"))
    try:
        from lib import overnight
    finally:
        sys.path.pop(0)
    return getattr(overnight, "WAKE_PROMPT", None)


@pytest.mark.parametrize("prompt,denied", [
    ("/spec draft the cache spec", True), ("/dev", True), ("/push origin", True), ("/codex review", True),
    ("<command-name>/close</command-name>", True),
    ("/restart", False), ("/checkpoint", False), ("/babysit-prs", False), ("check the build, then /dev", False),
    ("carry on with the checklist", False)])
def test_a_schedulewakeup_prompt_typing_a_harness_command_outside_control_is_denied(tmp_path, prompt, denied):
    proc = run(tmp_path, "ScheduleWakeup", {"prompt": prompt, "delaySeconds": 600, "reason": "r"})
    assert proc.returncode == (2 if denied else 0), proc.stderr
    if denied:
        reason = json.loads(proc.stderr.splitlines()[0].split(": ", 1)[1])["deny_reason"]
        assert reason.startswith("a ScheduleWakeup prompt that types /"), reason
    # The fired CronCreate record is measured and excluded from the human's prompts (COV-7): no rule.
    assert run(tmp_path, "CronCreate", {"cron": "*/5 * * * *", "prompt": prompt, "recurring": True}).returncode == 0


def test_the_overnight_wake_prompt_is_never_denied(tmp_path):
    wake = _wake_prompt() or "carry on with the checklist"  # lib.overnight's own text once it holds one
    for tool in ("ScheduleWakeup", "CronCreate"):
        assert run(tmp_path, tool, {"cron": "3 * * * *", "prompt": wake, "recurring": True}).returncode == 0


# ---------------------------------------------------------------- what the /push Stop reads (P5 review H2)
REPO_HASH, REQUEST = "0123456789abcdef", "ab" * 16
TOKEN = "a push-gate token, whose one writer is scripts/write-push-gate-token.py"
GRANT = "a push-analyst grant, which only the push-analyst dispatched for its request writes"
# A state dir outside /tmp and /var/tmp, where the push-analyst's role rows let it write its grant; never created.
STATE = "/nonexistent-p5-protected-paths/state"


def push_inputs(state: str) -> dict:
    base = os.path.join(state, "agentic-commit")
    return {"token": (os.path.join(base, "push", REPO_HASH, "fedcba9876543210", "topic.json"), TOKEN),
            "legacy token": (os.path.join(base, "push", REPO_HASH, "topic.json"), TOKEN),
            "grant": (os.path.join(base, "push-analyst", REPO_HASH, SID, REQUEST + ".json"), GRANT)}


@pytest.mark.parametrize("caller", list(CALLERS) + ["push-analyst"])
@pytest.mark.parametrize("form", ["Write", "Edit", "echo", "rm", "mv", "mv-in"])
@pytest.mark.parametrize("name", ["token", "legacy token", "grant"])
def test_h2_the_push_stops_inputs_are_denied_to_every_caller_without_their_dispatch(tmp_path, caller, form, name):
    """The main agent, any subagent, and a push-analyst whose session records no dispatch of it."""
    path, what = push_inputs(STATE)[name]
    who = ("a0pa", "push-analyst") if caller == "push-analyst" else CALLERS[caller]
    assert_denied(run(tmp_path, *forms(path)[form], who, state=STATE), what)


def push_session(tmp_path, subagent_type: str = "push-analyst") -> str:
    """commands/push.md Step 3's dispatch, its placeholders bound and its obligation instantiated, in the
    session transcript, and the child the CLI starts for it (its first record and meta); its agent id."""
    text = open(os.path.join(ROOT, "commands", "push.md"), encoding="utf-8").read()
    fence = next(b for b in re.findall(r"^```[^\n]*\n(.*?)^```", text, re.M | re.S) if "REQUEST_ID=<REQUEST_ID>" in b)
    fence = re.sub(r'"<ISO-8601 UTC ending in Z[^"]*>"', '"2026-11-08T07:00:00Z"', fence)
    values = {"BRANCH": "topic", "PRE_HEAD": "1" * 40, "RESOLVED_REMOTE": "origin", "REMOTE_URL": "/elsewhere/o.git",
              "REQUEST_ID": REQUEST, "SESSION_ID": SID, "REPO_HASH": REPO_HASH}
    prompt = re.sub(r"<([A-Z_]+)>", lambda m: values[m[1]], fence).strip()
    project = tmp_path / "home" / ".claude" / "projects" / "-p"
    (project / SID / "subagents").mkdir(parents=True)
    call, agent = "toolu_h2push0001", "a0pa"
    with open(project / f"{SID}.jsonl", "w") as fh:
        fh.write(json.dumps({"type": "user", "message": {"role": "user", "content":
                 "<command-name>/push</command-name>\n<command-args></command-args>"}}) + "\n")
        fh.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": call, "name": "Agent", "input": {
                "description": "pre-push analysis", "prompt": prompt, "subagent_type": subagent_type}}]}}) + "\n")
    (project / SID / "subagents" / f"agent-{agent}.jsonl").write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n")
    (project / SID / "subagents" / f"agent-{agent}.meta.json").write_text(
        json.dumps({"agentType": subagent_type, "toolUseId": call}))
    return agent


def test_h2_the_push_analyst_writes_the_grant_its_own_dispatch_binds_and_nothing_else(tmp_path):
    """Its own dispatch binds the grant's repository hash, session and request id: that grant, and no
    other path of the two trees. The chain-B sentinel and the merge-analyst's grant (no /push Stop
    input), a state dir holding no token or grant, and the token's one writer, whose own write no tool
    call shows, stay allowed."""
    agent = push_session(tmp_path)
    grant, _ = push_inputs(STATE)["grant"]
    me = (agent, "push-analyst")
    proc = run(tmp_path, "Write", {"file_path": grant, "content": "{}"}, me, state=STATE)
    assert proc.returncode == 0 and "D11/D12" not in proc.stderr, proc.stderr
    other = os.path.join(os.path.dirname(grant), "cd" * 16 + ".json")  # another request's grant
    assert_denied(run(tmp_path, "Write", {"file_path": other, "content": "{}"}, me, state=STATE), GRANT)
    assert_denied(run(tmp_path, "Bash", {"command": f"rm -f {grant}"}, me, state=STATE), GRANT)
    assert_denied(run(tmp_path, *forms(push_inputs(STATE)["token"][0])["Write"], me, state=STATE), TOKEN)
    assert_denied(run(tmp_path, "Write", {"file_path": grant, "content": "{}"}, None, state=STATE), GRANT)
    base = tmp_path / "state" / "agentic-commit"
    (base / "merge-analyst" / REPO_HASH / SID).mkdir(parents=True)
    for path in (str(base / "push-analyst" / REPO_HASH / "topic-chainB.validated.sentinel.json"),
                 str(base / "merge-analyst" / REPO_HASH / SID / (REQUEST + ".json"))):
        assert "D11/D12" not in run(tmp_path, "Write", {"file_path": path, "content": "{}"}).stderr
    assert "D11/D12" not in run(tmp_path, "Bash", {"command": f"rm -rf {base}/merge-analyst"}).stderr
    writer = os.path.join(ROOT, "scripts", "write-push-gate-token.py")
    proc = run(tmp_path, "Bash", {"command": f'python3 "{writer}" --repo-root "{PRODUCT}" --branch topic --commit '
                                             f'{"1" * 40}'})
    assert proc.returncode == 0 and "D11/D12" not in proc.stderr, proc.stderr


def test_h2_a_subagent_of_another_type_given_the_same_prompt_is_no_producer(tmp_path):
    agent = push_session(tmp_path, subagent_type="general-purpose")
    grant, _ = push_inputs(STATE)["grant"]
    assert_denied(run(tmp_path, "Write", {"file_path": grant, "content": "{}"}, (agent, "general-purpose"),
                      state=STATE), GRANT)


@pytest.mark.parametrize("command", [
    "rm -rf {state}", "rm -rf {state}/agentic-commit", "rm -rf $CLAUDE_STATE_DIR/agentic-commit/push",
    "mv {state}/agentic-commit/push-analyst/{repo} /elsewhere/x", "rm -r {state}/agentic-commit/push/{repo}/"])
def test_h2_a_directory_holding_a_token_or_a_grant_is_denied(tmp_path, command):
    state = tmp_path / "state"
    for path, _ in push_inputs(str(state)).values():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").write("{}")
    proc = run(tmp_path, "Bash", {"command": command.format(state=state, repo=REPO_HASH)}, CALLERS["dev"])
    assert proc.returncode == 2 and "(D11/D12)" in proc.stderr, proc.stderr
    assert all(os.path.isfile(p) for p, _ in push_inputs(str(state)).values())


# P13-1 R6 (D28): the owner's answers and the score log are hook-owned; every agent's write is refused.
@pytest.mark.parametrize("caller", list(CALLERS))
@pytest.mark.parametrize("form", ["Write", "Edit", "echo", "append"])
@pytest.mark.parametrize("which", ["answers", "producer answer", "score log", "score lock"])
def test_r6_hook_owned_files_are_refused_to_every_agent(tmp_path, caller, form, which):
    logs = tmp_path / "home" / ".claude" / "logs"
    answer = "an owner's answer, which only the PostToolUse AskUserQuestion hook writes"
    score = "the score log or its lock, which only hooks write"
    path, what = {"answers": (f"{PRODUCT}/docs/dev/requirement-answers-20261109-120000-r1.json", answer),
                  "producer answer": (f"{PRODUCT}/docs/dev/producer-answer-20261109-120000-ba-0123abcd.json", answer),
                  "score log": (str(logs / "lifecycle.jsonl"), score),
                  "score lock": (str(logs / "lifecycle.jsonl.lock"), score)}[which]
    tool, tool_input = {**forms(path), "append": ("Bash", {"command": f"echo x >> {path}"})}[form]
    assert_denied(run(tmp_path, tool, tool_input, CALLERS[caller]), what)


def test_r6_the_round_files_and_another_log_stay_writable(tmp_path):
    for path in (f"{PRODUCT}/docs/dev/requirement-round-20261109-120000-r1.json",
                 str(tmp_path / "home" / ".claude" / "logs" / "other.jsonl")):
        assert run(tmp_path, "Write", {"file_path": path, "content": "x"}).returncode == 0
