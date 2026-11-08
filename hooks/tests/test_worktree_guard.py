"""hooks/pretool-worktree-guard.sh against scratch repositories that hold stale
agent worktrees.

The guard runs before every tool. Until 2026-11-08 it exited 2 (block) on every
tool while an agent worktree was behind the main branch. That blocked its own
advice: `git worktree remove` is a Bash call, so the guard refused it, and the
other half of the advice, `git branch -D`, is refused by pretool-bash-safety.sh
and pretool-git-privilege-guard.py. Reads, AskUserQuestion and Agent calls were
refused too, so only the human could end the state.

These tests pin the fix:
  * no stale-worktree state makes the guard exit 2, for any tool;
  * the cleanup it recommends passes every PreToolUse hook settings.json
    registers for Bash, really removes the worktree, and leaves the guard quiet;
  * the lesson, "a stale worktree causes merge conflicts", still reaches Claude
    (PreToolUse additionalContext) and the user (systemMessage) on every call.

Each test builds its own repository under tmp_path and its own guard cache
(CLAUDE_STATE_DIR), and drives the real hook process the way Claude Code does:
JSON on stdin, exit code and stdout read back.

Run with: python3 -m pytest hooks/tests/test_worktree_guard.py -v
"""

import json
import os
import re
import shutil
import stat
import subprocess
import uuid
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
ROOT = HOOKS.parent
GUARD = HOOKS / "pretool-worktree-guard.sh"
LESSON = "a stale worktree causes merge conflicts"

# Every kind of stale agent worktree the guard can meet.
STATES = ("clean", "dirty", "untracked", "missing", "locked", "detached", "spaced", "two")


def _git(repo, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=check, capture_output=True, text=True)


def _scratch_repo(tmp_path, state):
    """A repository whose agent worktree(s) are one commit behind master."""
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "master", str(repo)],
                   check=True, capture_output=True)
    (repo / "f").write_text("one\n")
    _git(repo, "add", "f")
    _git(repo, "commit", "-qm", "one")
    names = {"two": ["agent-a1", "agent-a2"], "spaced": ["agent-a 1"]}.get(state, ["agent-a1"])
    worktrees = []
    for name in names:
        wt = repo / ".claude" / "worktrees" / name
        if state == "detached":
            _git(repo, "worktree", "add", "-q", "--detach", str(wt))
        else:
            _git(repo, "worktree", "add", "-q", "-b",
                 "worktree-" + name.replace(" ", "-"), str(wt))
        worktrees.append(wt)
    wt = worktrees[0]
    if state == "dirty":
        (wt / "f").write_text("unsaved edit\n")
    elif state == "untracked":
        (wt / "notes.txt").write_text("unsaved file\n")
    elif state == "missing":
        shutil.rmtree(wt)
    elif state == "locked":
        _git(repo, "worktree", "lock", "--reason", "running agent", str(wt))
    (repo / "f").write_text("one\ntwo\n")
    _git(repo, "commit", "-qam", "two")
    return repo, worktrees


def _env(tmp_path, **extra):
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    env = dict(os.environ)
    env.pop("CLAUDE_HOME", None)
    env["CLAUDE_STATE_DIR"] = str(state)  # this test's own guard cache
    env.update(extra)
    return env


def _payload(repo, tool, tool_input):
    # A fresh session id per call keeps per-session counters in other hooks
    # (the orchestrator gate's Bash streak) out of these results.
    return json.dumps({"session_id": "wt-guard-" + uuid.uuid4().hex,
                       "hook_event_name": "PreToolUse", "cwd": str(repo),
                       "tool_name": tool, "tool_input": tool_input})


def _guard(repo, env, tool="Bash", tool_input=None):
    return subprocess.run(["bash", str(GUARD)],
                          input=_payload(repo, tool, tool_input or {}),
                          text=True, capture_output=True, cwd=str(repo), env=env, timeout=60)


def _hook_output(proc):
    """The guard's PreToolUse JSON: (additionalContext, whole document)."""
    doc = json.loads(proc.stdout)
    hso = doc["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    return hso["additionalContext"], doc


def _tool_calls(repo, wt):
    """Calls an agent makes while it checks and removes a stale worktree."""
    return [
        ("Bash", {"command": f"git worktree remove '{wt}'"}),
        ("Bash", {"command": f"git -C '{wt}' status --short"}),
        ("Read", {"file_path": str(wt / "f")}),
        ("Edit", {"file_path": str(repo / "f"), "old_string": "two", "new_string": "2"}),
        ("AskUserQuestion", {"questions": []}),
        ("TodoWrite", {"todos": []}),
        ("Agent", {"description": "d", "prompt": "p", "subagent_type": "general-purpose"}),
    ]


@pytest.mark.parametrize("state", STATES)
def test_no_stale_state_blocks_any_tool(tmp_path, state):
    repo, worktrees = _scratch_repo(tmp_path, state)
    env = _env(tmp_path)
    for tool, tool_input in _tool_calls(repo, worktrees[0]):
        proc = _guard(repo, env, tool, tool_input)
        assert proc.returncode == 0, (state, tool, proc.returncode, proc.stderr)
        # The warning is on every call, not only the first: the cache holds the
        # stale count and re-checks rather than going quiet.
        context, _ = _hook_output(proc)
        assert LESSON in context.lower(), (state, tool)


@pytest.mark.parametrize("state", STATES)
def test_lesson_reaches_claude_and_user(tmp_path, state):
    repo, worktrees = _scratch_repo(tmp_path, state)
    proc = _guard(repo, _env(tmp_path), "Read", {"file_path": str(repo / "f")})
    assert proc.returncode == 0
    context, doc = _hook_output(proc)
    lowered = context.lower()
    assert LESSON in lowered
    assert "remove stale worktrees before they cause merge conflicts" in lowered
    assert "never use isolation:worktree for dev subagents" in lowered
    assert f"{len(worktrees)} agent worktree(s) behind master" in context
    for wt in worktrees:
        assert wt.name in context
    assert "merge conflicts" in doc["systemMessage"]
    # Advisory only: no allow/deny/ask for the permission system, so the hook
    # neither blocks a tool nor approves one that would otherwise prompt.
    assert "permissionDecision" not in doc["hookSpecificOutput"]
    assert set(doc) == {"hookSpecificOutput", "systemMessage"}


def test_flags_tell_the_agent_what_it_is_looking_at(tmp_path):
    repo, _ = _scratch_repo(tmp_path / "locked", "locked")
    context, _ = _hook_output(_guard(repo, _env(tmp_path / "locked")))
    assert "[locked: running agent]" in context
    repo, _ = _scratch_repo(tmp_path / "missing", "missing")
    context, _ = _hook_output(_guard(repo, _env(tmp_path / "missing")))
    assert "[directory missing]" in context
    repo, _ = _scratch_repo(tmp_path / "detached", "detached")
    context, _ = _hook_output(_guard(repo, _env(tmp_path / "detached")))
    assert "detached HEAD" in context


def _bash_pretool_hooks():
    """Every PreToolUse command settings.json runs before a Bash call."""
    settings = json.loads((ROOT / "settings.json").read_text())
    commands = []
    for block in settings["hooks"]["PreToolUse"]:
        matcher = block.get("matcher")
        if matcher in (None, "", "*") or re.fullmatch(matcher, "Bash"):
            commands += [h["command"] for h in block["hooks"] if h.get("type") == "command"]
    return commands


def _chain_env(tmp_path, env):
    # The harness home is this checkout; any state the other hooks write goes
    # under tmp_path, never into the checkout.
    chain = dict(env, CLAUDE_HOME=str(ROOT),
                 ATTRIBUTION_STATE_DIR=str(tmp_path / "attribution-journal"))
    chain.pop("CLAUDE_PROJECT_DIR", None)
    return chain


def _run_cleanup_step(repo, tmp_path, env, command):
    """One Bash call, end to end: every PreToolUse hook for Bash, then the call."""
    hooks = _bash_pretool_hooks()
    assert any("pretool-worktree-guard.sh" in h for h in hooks)
    assert any("pretool-bash-safety.sh" in h for h in hooks)
    chain_env = _chain_env(tmp_path, env)
    for hook in hooks:
        proc = subprocess.run(["bash", "-c", hook],
                              input=_payload(repo, "Bash", {"command": command}),
                              text=True, capture_output=True, cwd=str(repo),
                              env=chain_env, timeout=120)
        assert proc.returncode != 2, (command, hook, proc.stderr)
    done = subprocess.run(["bash", "-c", command], cwd=str(repo), env=env,
                          text=True, capture_output=True, timeout=60)
    assert done.returncode == 0, (command, done.stderr)


def _recommended_commands(context):
    """The per-worktree command lines of the guard's advice."""
    return re.findall(r"^ +(git worktree remove .+)$", context, flags=re.M)


def _assert_cleaned(repo, env):
    listing = _git(repo, "worktree", "list", "--porcelain").stdout
    assert "worktrees/agent-" not in listing
    after = _guard(repo, env)
    assert after.returncode == 0
    assert after.stdout == ""


@pytest.mark.parametrize("state", ("clean", "missing", "detached", "spaced", "two"))
def test_recommended_cleanup_passes_every_hook_and_runs(tmp_path, state):
    repo, worktrees = _scratch_repo(tmp_path, state)
    env = _env(tmp_path)
    context, _ = _hook_output(_guard(repo, env))
    commands = _recommended_commands(context)
    assert len(commands) == len(worktrees)
    for command in commands:
        _run_cleanup_step(repo, tmp_path, env, command)
    _assert_cleaned(repo, env)


@pytest.mark.parametrize("state", ("dirty", "untracked"))
def test_unsaved_work_can_be_checked_before_removal(tmp_path, state):
    """git refuses the plain remove; the agent looks, asks, then forces it."""
    repo, (wt,) = _scratch_repo(tmp_path, state)
    env = _env(tmp_path)
    context, _ = _hook_output(_guard(repo, env))
    (command,) = _recommended_commands(context)
    refused = subprocess.run(["bash", "-c", command], cwd=str(repo), env=env,
                             text=True, capture_output=True)
    assert refused.returncode != 0  # git protects the unsaved work
    for tool, tool_input in [
            ("Bash", {"command": f"git -C '{wt}' status --short"}),
            ("Read", {"file_path": str(wt / "f")}),
            ("AskUserQuestion", {"questions": []})]:
        assert _guard(repo, env, tool, tool_input).returncode == 0
    _run_cleanup_step(repo, tmp_path, env, command.replace("remove ", "remove --force ", 1))
    _assert_cleaned(repo, env)


def test_locked_worktree_can_be_unlocked_then_removed(tmp_path):
    repo, (wt,) = _scratch_repo(tmp_path, "locked")
    env = _env(tmp_path)
    context, _ = _hook_output(_guard(repo, env))
    (command,) = _recommended_commands(context)
    assert _guard(repo, env, "AskUserQuestion", {"questions": []}).returncode == 0
    _run_cleanup_step(repo, tmp_path, env, f"git worktree unlock '{wt}'")
    _run_cleanup_step(repo, tmp_path, env, command)
    _assert_cleaned(repo, env)


def test_advice_never_asks_the_agent_for_a_blocked_command(tmp_path):
    """The old advice ended in `git branch -D <branch>`, which pretool-bash-safety.sh
    refuses. Branch deletion is now handed to the user, and the branch is left."""
    repo, _ = _scratch_repo(tmp_path, "clean")
    env = _env(tmp_path)
    context, _ = _hook_output(_guard(repo, env))
    assert "&& git branch -D" not in context
    assert "ask the user" in context
    for command in _recommended_commands(context):
        _run_cleanup_step(repo, tmp_path, env, command)
    assert "worktree-agent-a1" in _git(repo, "branch", "--list").stdout


def test_cleanup_steps_leave_nothing_in_the_checkout(tmp_path):
    before = _git(ROOT, "status", "--porcelain", "--ignored", "--untracked-files=all").stdout
    repo, (wt,) = _scratch_repo(tmp_path, "clean")
    _run_cleanup_step(repo, tmp_path, _env(tmp_path), f"git worktree remove '{wt}'")
    after = _git(ROOT, "status", "--porcelain", "--ignored", "--untracked-files=all").stdout
    new = [line for line in after.splitlines()
           if line not in before.splitlines() and "__pycache__" not in line]
    assert new == []


@pytest.mark.parametrize("state", ("none", "fresh", "outside"))
def test_quiet_without_a_stale_agent_worktree(tmp_path, state):
    repo, _ = _scratch_repo(tmp_path, "clean")
    if state == "none":
        _git(repo, "worktree", "remove", str(repo / ".claude/worktrees/agent-a1"))
    elif state == "fresh":
        _git(repo, "-C", str(repo / ".claude/worktrees/agent-a1"), "merge", "-q", "master")
    else:
        _git(repo, "worktree", "remove", str(repo / ".claude/worktrees/agent-a1"))
        _git(repo, "worktree", "add", "-q", "-b", "side", str(tmp_path / "side"), "master~1")
    proc = _guard(repo, _env(tmp_path))
    assert (proc.returncode, proc.stdout) == (0, "")


def test_internal_failure_still_exits_zero(tmp_path):
    """Exit 2 means block: an unexpected error must not become one."""
    repo, _ = _scratch_repo(tmp_path, "clean")
    env = _env(tmp_path)
    (tmp_path / "state" / "worktree-guard-cache").write_text("1\n")
    shim = tmp_path / "shim"
    shim.mkdir()
    fake = shim / "stat"
    fake.write_text("#!/bin/sh\necho 1.5\n")  # breaks the cache-age arithmetic
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    proc = _guard(repo, dict(env, PATH=f"{shim}{os.pathsep}{env['PATH']}"))
    assert proc.returncode == 0, proc.stderr


def test_unwritable_cache_does_not_hide_the_lesson(tmp_path):
    repo, _ = _scratch_repo(tmp_path, "clean")
    env = _env(tmp_path)
    (tmp_path / "state" / "worktree-guard-cache").mkdir()  # cannot be written
    proc = _guard(repo, env)
    assert proc.returncode == 0
    context, _ = _hook_output(proc)
    assert LESSON in context.lower()


def test_guard_still_runs_before_every_tool():
    """The lesson stays visible because settings.json still runs the guard,
    with no matcher, before every tool call."""
    settings = json.loads((ROOT / "settings.json").read_text())
    blocks = [b for b in settings["hooks"]["PreToolUse"]
              if any("pretool-worktree-guard.sh" in h["command"] for h in b["hooks"])]
    assert len(blocks) == 1
    assert blocks[0].get("matcher") in (None, "", "*")
