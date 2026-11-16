"""lib/bash_safety_rules.py through the real hook: the rules bash-safety gave up, the survivors that refuse
their cases, the over-blocks fixed, the bulk-commit writer closed from Bash, and the release wording.

Every call runs with a scratch HOME, state dir and git config, an empty protected-runtime file, and a
throwaway repository as its working directory. No command is ever executed.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / "hooks"
SAFETY = "pretool-bash-safety.sh"
PRIVILEGE = "pretool-git-privilege-guard.py"
sys.path.insert(0, str(HOOKS))
from lib.runtime_guard.config import REQUIRED_KEYS  # noqa: E402


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    base = tmp_path_factory.mktemp("bash-safety-rules")
    home, state, repo, tmp = base / "home", base / "state", base / "repo", base / "tmp"
    for d in (home / ".claude", state, repo, tmp):
        d.mkdir(parents=True)
    (base / "gitconfig").write_text("[user]\n\tname = sandbox\n\temail = sandbox@example.invalid\n")
    runtime = base / "protected-runtime.json"
    runtime.write_text(json.dumps({"schema_version": 1, **{k: [] for k in REQUIRED_KEYS}}))
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
           "CLAUDE_STATE_DIR": str(state), "GIT_CONFIG_GLOBAL": str(base / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1",
           "TMPDIR": str(tmp), "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8",
           "CLAUDE_PROTECTED_RUNTIME_FILE": str(runtime)}
    (repo / "README.md").write_text("toy\n")
    for step in (["init", "-q", "-b", "master"], ["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run(["git", *step], cwd=repo, env=env, check=True, capture_output=True)
    return {"env": env, "repo": str(repo), "tmp": str(tmp)}


def run(sandbox, hook, command, subagent=False):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": "bash-safety-rules",
               "cwd": sandbox["repo"], "hook_event_name": "PreToolUse"}
    if subagent:
        payload.update(agent_id="agent-bash-safety-rules", agent_type="dev")
    argv = ["bash" if hook.endswith(".sh") else sys.executable, str(HOOKS / hook)]
    return subprocess.run(argv, input=json.dumps(payload), capture_output=True, text=True, env=sandbox["env"],
                          cwd=sandbox["repo"], timeout=120)


# Each rule bash-safety no longer holds, with the cases its own refusal covered and the hook that refuses them.
MERGED = {
    "BS-40 git reset --hard": (PRIVILEGE, ["git reset --hard HEAD", "/usr/bin/git reset --hard HEAD~1",
                                           "bash -c 'git reset --hard HEAD'"]),
    "BS-41 force/delete/mirror/refspec push": (PRIVILEGE, [
        "git push --force origin master", "git push -f origin master", "git push --force-with-lease origin master",
        "git push --force-with-lease=master origin master", "git push --delete origin feature",
        "git push -d origin feature", "git push --mirror origin", "git push origin +master",
        "git push origin :feature", "/usr/bin/git push --force origin master", "bash -c 'git push --force origin x'"]),
    "BS-42 direct ref mutation": (PRIVILEGE, [
        "git update-ref refs/heads/x HEAD", "git branch -D feature", "git branch -d feature", "git branch -f x HEAD",
        "git branch -m a b", "git branch -M a b", "git branch --delete feature", "git branch --force x HEAD",
        "git branch --move a b", "git symbolic-ref HEAD refs/heads/x", "git symbolic-ref -m why HEAD refs/heads/x",
        "/usr/bin/git branch -D feature", "bash -c 'git update-ref refs/heads/x HEAD'"]),
    "BS-45 git revert of a ref modifier": (PRIVILEGE, [
        "git revert abc1234", "git revert HEAD^", "git revert HEAD~2", "git revert HEAD@{1}",
        "git revert --no-edit master^", "/usr/bin/git revert HEAD^"]),
}
SUBAGENT_MERGED = {
    "BS-44 subagent history rewrite": (PRIVILEGE, ["git rebase master", "git cherry-pick abc1234",
                                                   "git revert HEAD", "/usr/bin/git rebase master"]),
}


@pytest.mark.parametrize("rule,hook,command", [(r, h, c) for r, (h, cs) in MERGED.items() for c in cs])
def test_a_merged_rule_case_is_refused_by_its_survivor(sandbox, rule, hook, command):
    assert run(sandbox, hook, command).returncode == 2, (rule, command)


@pytest.mark.parametrize("rule,hook,command", [(r, h, c) for r, (h, cs) in SUBAGENT_MERGED.items() for c in cs])
def test_a_merged_subagent_rule_case_is_refused_by_its_survivor(sandbox, rule, hook, command):
    assert run(sandbox, hook, command, subagent=True).returncode == 2, (rule, command)


@pytest.mark.parametrize("command", ["git reset --hard HEAD", "git push --force origin master",
                                     "git branch -D feature", "git revert abc1234"])
def test_bash_safety_leaves_the_merged_git_rules_to_the_privilege_guard(sandbox, command):
    assert run(sandbox, SAFETY, command).returncode == 0, command


@pytest.mark.parametrize("command", ["systemctl restart docker", "systemctl stop docker",
                                     "systemctl restart docker.service"])
def test_the_docker_daemon_rule_merged_into_the_systemctl_rule(sandbox, command):
    """BS-22 merged into BS-30, which refuses every non-whitelisted systemctl stop/restart target."""
    r = run(sandbox, SAFETY, command)
    assert r.returncode == 2 and "refused for production services" in r.stderr, (command, r.stderr)


def test_the_docker_daemon_disable_is_the_settings_deny():
    """BS-22's `systemctl disable docker` is refused by settings.json's permissions.deny."""
    deny = json.loads((REPO / "settings.json").read_text())["permissions"]["deny"]
    assert {"Bash(systemctl restart:*)", "Bash(systemctl stop:*)", "Bash(systemctl disable:*)"} <= set(deny)


def test_session_dirs_ban_is_the_settings_deny():
    """BS-18 merged into settings.json's permissions.deny, which refuses it for Bash, Read and Edit."""
    deny = json.loads((REPO / "settings.json").read_text())["permissions"]["deny"]
    assert {"Bash(*session_dirs.txt*)", "Read(**/session_dirs.txt)", "Edit(**/session_dirs.txt)"} <= set(deny)


@pytest.mark.parametrize("script", ["/tmp/x.sh", "/var/tmp/x.sh", "/dev/shm/x.sh", "{tmp}/x.sh"])
def test_a_script_under_a_temporary_directory_is_no_longer_refused(sandbox, script):
    """O6: BS-11 stopped one spelling (`bash /tmp/x.sh`; `sh -x /tmp/x.sh` and `/tmp/x.sh` passed) and refused the
    session scratchpad, while protecting nothing; it is deleted."""
    command = "bash " + script.format(tmp=sandbox["tmp"])
    assert run(sandbox, SAFETY, command).returncode == 0, command


@pytest.mark.parametrize("command", [
    "source venv/bin/activate && python3 {repo}/scripts/write-bulk-commit-sentinel.py",
    "python3 {repo}/scripts/write-bulk-commit-sentinel.py",
    "python3 scripts/write-bulk-commit-sentinel.py --session x",
])
def test_the_bulk_commit_writer_is_refused_from_bash(sandbox, command):
    """Q6: the userprompt-bulk-commit-capability hook is the only minter of the bulk-commit sentinel."""
    r = run(sandbox, SAFETY, command.format(repo=REPO))
    assert r.returncode == 2 and "bulk-commit-sentinel-write" in r.stderr, r.stderr


def test_a_bare_read_of_the_bulk_sentinel_passes(sandbox):
    state = sandbox["env"]["CLAUDE_STATE_DIR"]
    assert run(sandbox, SAFETY, f"cat {state}/claude-bulk-commit-sentinel-x.json").returncode == 0


# One command per rule the /do and /allow releases reach, with its refusal label.
RELEASED = [
    ("echo hi > .env", "Attempting to write to sensitive file"),
    ("cp a /etc/docker/daemon.json", "Modifying Docker daemon config"),
    ("docker compose down", "docker-compose down/stop/restart"),
    ("docker system prune -a", "docker system prune -a"),
    ("dd if=/dev/zero of=/dev/null", "Destructive disk operation"),
    ("systemctl restart nginx", "refused for production services"),
    ("mv workflow-x.json /tmp/", "workflow state files"),
    ("rm -rf build", "removal-policy"),
    ("git stash", "bare 'git stash'"),
    ("git stash push -m x", "git stash push/save"),
    ("git checkout HEAD -- .", "git checkout <ref> -- ."),
    ("git restore --source=HEAD -- .", "git restore --source=<ref> -- ."),
    ("bash session-recovery.sh", "hard-banned script"),
    ("python3 scripts/write-bulk-commit-sentinel.py", "bulk-commit-sentinel-write"),
    ("curl -X POST http://localhost:8080/stop", "daemon-restart-http-stop"),
]


@pytest.mark.parametrize("command,label", RELEASED)
def test_a_released_rule_says_it_is_released_and_not_forbidden(sandbox, command, label):
    """Q7: a rule /do or a matching /allow releases does not call itself forbidden; it names the release."""
    r = run(sandbox, SAFETY, command)
    assert r.returncode == 2 and label in r.stderr, (command, r.stderr)
    assert "FORBIDDEN" not in r.stderr.upper().replace("FORBIDDEN_REMOVAL", ""), r.stderr
    assert "Release: the user can authorize this command with /do or a matching /allow grant." in r.stderr \
        or "via /do consent or an /allow grant" in r.stderr, r.stderr


def test_the_git_clean_rule_names_its_release(sandbox):
    r = run(sandbox, SAFETY, "git clean -fd")
    assert r.returncode == 2 and "/do consent or an /allow grant" in r.stderr


def test_a_rule_neither_release_reaches_still_says_so(sandbox):
    r = run(sandbox, SAFETY, "git commit --no-verify -m x")
    assert r.returncode == 2 and "commit-hook-bypass" in r.stderr and "FORBIDDEN for every caller" in r.stderr
