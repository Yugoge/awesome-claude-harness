"""P7 R7b agent-side denies in hooks/pretool-bash-safety.sh.

Two rules, enforced for the main agent and for subagents alike and ahead of the
/do and /allow bypasses:

* commit-hook-bypass: a command holding a git `commit` invocation may not skip
  the commit hooks (--no-verify and its abbreviations, -n in a short-option
  cluster, a core.hooksPath override, a GIT_CONFIG_* environment assignment).
* unregistered-settings-filter: such a command may not run while a candidate
  repository declares the claude-settings filter for settings.json, has no local
  filter registration, and settings.json differs from HEAD (index or work tree).

Every case drives the real hook as a subprocess with a PreToolUse Bash payload.
HOME, CLAUDE_CONFIG_DIR, the state dir, the grant dir and the protected-runtime
data file all point into the test's temporary directory, and the only git
repositories touched are created there.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "pretool-bash-safety.sh"
sys.path.insert(0, str(REPO / "hooks"))
from lib.runtime_guard.config import REQUIRED_KEYS  # noqa: E402

SID = "commit-guard-test-sid"
CALLERS = {
    "main": {},
    "subagent": {"agent_id": "agent-test-123", "agent_type": "general-purpose"},
}
# Ambient variables that would point the hook or git somewhere other than the sandbox.
SCRUB_PREFIXES = ("GIT_",)
SCRUB_NAMES = ("CLAUDE_HOME", "CLAUDE_PYTHON_BIN", "CLAUDE_TASK_ID", "CLAUDE_SESSION_ID",
               "CLAUDE_PROJECT_DIR")

FILTER_LINE = "/settings.json filter=claude-settings\n"
SETTINGS = '{\n  "env": {}\n}\n'

BYPASS_CASES = [
    # the cases design section 8 lists
    "git commit --no-verify -m x",
    "git commit -n -m x",
    "git commit -nm x",
    "git commit -anm x",
    "git -c core.hooksPath=/dev/null commit -m x",
    "GIT_CONFIG_PARAMETERS=\"'core.hooksPath'='/dev/null'\" git commit -m x",
    # further accepted forms of the same bypass
    "git commit --no-veri -m x",
    "git commit '--no-verify' -m x",
    "git -ccore.hookspath=/dev/null commit -m x",
    "git --config-env=core.hooksPath=HOOKS_DIR commit -m x",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/dev/null git commit -m x",
    "git add -A && /usr/bin/git commit -C HEAD -n",
    "bash -c 'git commit -n -m x'",
]

ALLOWED_CASES = [
    'echo "git commit --no-verify"',
    'git commit -m "-n"',
    "git commit -m x",
    "git commit -m -n",
    "git commit -mn",
    "printf '%s\\n' \"x; git commit -n\"",
]


@pytest.fixture
def sandbox(tmp_path):
    for name in ("home", "config", "state", "grants", "plain", "elsewhere"):
        (tmp_path / name).mkdir()
    runtime = tmp_path / "protected-runtime.json"
    runtime.write_text(json.dumps({"schema_version": 1, **{k: [] for k in REQUIRED_KEYS}}))
    env = {k: v for k, v in os.environ.items()
           if k not in SCRUB_NAMES and not k.startswith(SCRUB_PREFIXES)}
    env.update({
        "HOME": str(tmp_path / "home"),
        "CLAUDE_CONFIG_DIR": str(tmp_path / "config"),
        "CLAUDE_STATE_DIR": str(tmp_path / "state"),
        "CLAUDE_DAEMON_RESTART_GRANT_DIR": str(tmp_path / "grants"),
        "CLAUDE_PROTECTED_RUNTIME_FILE": str(runtime),
        "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.com",
    })
    return tmp_path, env


def git(env, repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], env=env, check=True,
                   capture_output=True, text=True, timeout=60)


def make_repo(env, path, declare_filter):
    path.mkdir(parents=True, exist_ok=True)
    git(env, path, "init", "-q")
    (path / "settings.json").write_text(SETTINGS)
    if declare_filter:
        (path / ".gitattributes").write_text(FILTER_LINE)
    git(env, path, "add", "-A")
    git(env, path, "commit", "-q", "-m", "init")
    return path


def run_hook(sandbox, command, cwd, caller):
    tmp_path, env = sandbox
    payload = {"tool_name": "Bash", "tool_input": {"command": command},
               "session_id": SID, "cwd": str(cwd), **CALLERS[caller]}
    return subprocess.run(["bash", str(HOOK)], input=json.dumps(payload), text=True,
                          capture_output=True, env=env, cwd=str(tmp_path), timeout=120)


def assert_blocked(r, rule, command):
    lines = r.stderr.splitlines()
    assert r.returncode == 2, r.stderr
    assert lines and lines[0].startswith(f"BLOCKED: {rule}"), r.stderr
    assert f"Command: {command}" in lines, r.stderr


def assert_allowed(r):
    assert r.returncode == 0, r.stderr
    assert "BLOCKED" not in r.stderr


@pytest.fixture
def filtered_repo(sandbox):
    tmp_path, env = sandbox
    return make_repo(env, tmp_path / "harness", declare_filter=True)


# ---------------- commit-hook-bypass ----------------

@pytest.mark.parametrize("caller", sorted(CALLERS))
@pytest.mark.parametrize("command", BYPASS_CASES)
def test_commit_hook_bypass_is_blocked(sandbox, caller, command):
    tmp_path, env = sandbox
    repo = make_repo(env, tmp_path / "plain" / "repo", declare_filter=False)
    assert_blocked(run_hook(sandbox, command, repo, caller), "commit-hook-bypass", command)


@pytest.mark.parametrize("caller", sorted(CALLERS))
@pytest.mark.parametrize("command", ALLOWED_CASES)
def test_quoted_text_and_message_values_are_not_a_bypass(sandbox, caller, command):
    tmp_path, env = sandbox
    repo = make_repo(env, tmp_path / "plain" / "repo", declare_filter=False)
    assert_allowed(run_hook(sandbox, command, repo, caller))


# ---------------- unregistered-settings-filter ----------------

def _modify_work_tree(env, repo):
    (repo / "settings.json").write_text('{\n  "env": {"DEMO": "1"}\n}\n')


def _modify_index_only(env, repo):
    _modify_work_tree(env, repo)
    git(env, repo, "add", "settings.json")
    (repo / "settings.json").write_text(SETTINGS)  # work tree equals HEAD again


@pytest.mark.parametrize("caller", sorted(CALLERS))
@pytest.mark.parametrize("modify", [_modify_work_tree, _modify_index_only],
                         ids=["work-tree", "index"])
def test_unregistered_filter_with_changed_settings_is_blocked(sandbox, filtered_repo, caller, modify):
    _, env = sandbox
    modify(env, filtered_repo)
    command = "git commit -m x"
    r = run_hook(sandbox, command, filtered_repo, caller)
    assert_blocked(r, "unregistered-settings-filter", command)
    assert str(filtered_repo) in r.stderr.splitlines()[0]
    assert any("scripts/bootstrap" in line and str(filtered_repo) in line
               for line in r.stderr.splitlines()[1:]), r.stderr


@pytest.mark.parametrize("caller", sorted(CALLERS))
@pytest.mark.parametrize("template", ["git -C {repo} commit -m x", "cd {repo} && git commit -m x"],
                         ids=["dash-C", "cd"])
def test_unregistered_filter_is_found_through_C_and_cd(sandbox, filtered_repo, caller, template):
    tmp_path, env = sandbox
    _modify_work_tree(env, filtered_repo)
    command = template.format(repo=filtered_repo)
    assert_blocked(run_hook(sandbox, command, tmp_path / "elsewhere", caller),
                   "unregistered-settings-filter", command)


@pytest.mark.parametrize("caller", sorted(CALLERS))
def test_unmodified_settings_are_allowed_even_when_only_the_stat_changed(sandbox, filtered_repo, caller):
    settings = filtered_repo / "settings.json"
    later = time.time() + 120
    os.utime(settings, (later, later))  # same content, different stat data
    assert_allowed(run_hook(sandbox, "git commit -m x", filtered_repo, caller))


@pytest.mark.parametrize("caller", sorted(CALLERS))
def test_registered_filter_is_allowed(sandbox, filtered_repo, caller):
    _, env = sandbox
    _modify_work_tree(env, filtered_repo)
    git(env, filtered_repo, "config", "--local", "filter.claude-settings.clean", "cat")
    assert_allowed(run_hook(sandbox, "git commit -m x", filtered_repo, caller))


@pytest.mark.parametrize("caller", sorted(CALLERS))
def test_plain_repository_and_non_repository_commits_are_allowed(sandbox, caller):
    tmp_path, env = sandbox
    repo = make_repo(env, tmp_path / "plain" / "repo", declare_filter=False)
    _modify_work_tree(env, repo)
    assert_allowed(run_hook(sandbox, "git commit -m x", repo, caller))
    assert_allowed(run_hook(sandbox, "git commit -m x", tmp_path / "elsewhere", caller))


# ---------------- neither /do nor /allow bypasses the two rules ----------------

CONTROL = {"main": "git stash", "subagent": "git rebase main"}  # blocked without consent


@pytest.mark.parametrize("caller", sorted(CALLERS))
def test_do_consent_does_not_bypass(sandbox, filtered_repo, caller):
    tmp_path, env = sandbox
    plain = make_repo(env, tmp_path / "plain" / "repo", declare_filter=False)
    assert run_hook(sandbox, CONTROL[caller], plain, caller).returncode == 2
    (tmp_path / "state" / f"claude-orchestrator-consent-{SID}.flag").write_text("true")
    assert_allowed(run_hook(sandbox, CONTROL[caller], plain, caller))  # consent is live
    command = "git commit --no-verify -m x"
    assert_blocked(run_hook(sandbox, command, plain, caller), "commit-hook-bypass", command)
    _modify_work_tree(env, filtered_repo)
    assert_blocked(run_hook(sandbox, "git commit -m x", filtered_repo, caller),
                   "unregistered-settings-filter", "git commit -m x")


@pytest.mark.parametrize("caller", sorted(CALLERS))
def test_allow_grant_does_not_bypass(sandbox, filtered_repo, caller):
    tmp_path, env = sandbox
    plain = make_repo(env, tmp_path / "plain" / "repo", declare_filter=False)
    grants = tmp_path / "state" / "claude-grants"
    grants.mkdir()
    now = int(time.time())

    def grant(target):
        (grants / f"{SID}.json").write_text(json.dumps({
            "task_id": SID, "session_id": SID, "created_at": now, "expires_at": now + 300,
            "allowed_operations": [{"op": "git", "target": target}]}))

    grant("stash")
    assert_allowed(run_hook(sandbox, "git stash", plain, caller))  # the grant is live
    grant("commit")
    command = "git commit -n -m x"
    assert_blocked(run_hook(sandbox, command, plain, caller), "commit-hook-bypass", command)
    _modify_work_tree(env, filtered_repo)
    assert_blocked(run_hook(sandbox, "git commit -m x", filtered_repo, caller),
                   "unregistered-settings-filter", "git commit -m x")
