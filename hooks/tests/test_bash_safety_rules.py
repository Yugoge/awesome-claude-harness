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


# O1 and O6: over-blocks of raw-text co-occurrence, now read from the parser. Each pairs the fixed command with
# the command the rule still refuses.
OVER_BLOCKS_FIXED = [
    ('git -c x=y commit -m "fix(session-recovery)"', "bash session-recovery.sh", "hard-banned script"),
    ('echo "see secret > file"', "cat .env > out.txt", "redirect from/to sensitive file"),
    ('git commit -m "fix: avoid npm install -g"', 'bash -c "npm i -g foo"', "global package install"),
    ('echo "npm install -g foo"', "sh -c 'npm install -g foo'", "global package install"),
]


@pytest.mark.parametrize("fixed,refused,label", OVER_BLOCKS_FIXED)
def test_an_over_block_is_fixed_and_its_rule_still_refuses(sandbox, fixed, refused, label):
    assert run(sandbox, SAFETY, fixed).returncode == 0, fixed
    r = run(sandbox, SAFETY, refused)
    assert r.returncode == 2 and label in r.stderr, (refused, r.stderr)


@pytest.mark.parametrize("namespace,label", [
    ("{state}/claude-commit-userintent-", "commit-userintent-sentinel-write"),
    ("{tmp}/claude-allow-daemon-restart-", "daemon-restart-sentinel-write"),
])
def test_a_read_of_a_grant_namespace_passes_and_a_write_is_refused(sandbox, namespace, label):
    """O6: reading the /commit user-intent flag or the daemon-restart grant flag is not a write of it."""
    ns = namespace.format(state=sandbox["env"]["CLAUDE_STATE_DIR"], tmp=sandbox["env"]["TMPDIR"])
    for read in (f"ls {ns}x.flag 2>/dev/null", f"cat {ns}x.flag", f"cat {ns}x.flag | cat"):
        assert run(sandbox, SAFETY, read).returncode == 0, read
    for write in (f"echo x > {ns}x.flag", f"touch {ns}x.flag", f"cp /etc/hostname {ns}x.flag"):
        r = run(sandbox, SAFETY, write)
        assert r.returncode == 2 and label in r.stderr, (write, r.stderr)



DAEMON = {"CLAUDE_PROTECTED_DAEMON_PREFIX": "demo-daemon", "CLAUDE_PROTECTED_DAEMON_TARGETS": "acct-a|acct-b"}


def run_env(sandbox, command, extra):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": "bash-safety-rules",
               "cwd": sandbox["repo"]}
    return subprocess.run(["bash", str(HOOKS / SAFETY)], input=json.dumps(payload), capture_output=True, text=True,
                          env={**sandbox["env"], **extra}, cwd=sandbox["repo"], timeout=120)


@pytest.mark.parametrize("command,refused", [
    ("systemctl restart demo-daemon-acct-a", True),
    ("sudo systemctl restart demo-daemon", True),
    ("bash -c 'systemctl stop demo-daemon-acct-b'", True),
    ("systemctl --now restart demo-daemon", True),     # the runtime guard reads the verb past an option
    ("echo systemctl restart demo-daemon", False),     # data, not a restart
    ("systemctl status demo-daemon-acct-a", False),
])
def test_the_daemon_restart_rule_reads_the_runtime_guards_service_matcher(sandbox, command, refused):
    """BS-09: the daemon family is the runtime guard's protected service; a restart verb of the rule refuses."""
    r = run_env(sandbox, command, DAEMON)
    assert ("daemon-restart-prohibition" in r.stderr) == refused, (command, r.stderr)


def test_the_daemon_restart_rule_is_inert_without_its_variables(sandbox):
    r = run_env(sandbox, "systemctl --now restart demo-daemon", {})
    assert "daemon-restart-prohibition" not in r.stderr


@pytest.mark.parametrize("command", ["npm install -g foo", "npm i --global foo", 'bash -c "npm i -g foo"',
                                     "sh -c 'npm install -g foo'", "sudo npm install -g foo"])
def test_a_global_npm_install_is_the_runtime_guards(sandbox, command):
    """BS-34 merged into the runtime guard's global-install primitive, which refuses each form first."""
    r = run(sandbox, SAFETY, command)
    assert r.returncode == 2 and "protected-runtime-guard" in r.stderr, (command, r.stderr)


# OB-L13: the sentinel and commit-artifact rules bind a protected name to the simple command that writes it or runs
# it. Each command is read through the real hook; {state} is the sandbox state dir.
OB_L13_PASSES = [
    "python3 -m json.tool {state}/claude-commit-dispatch-a.json",
    "touch /tmp/marker && cat {state}/claude-commit-grant-a-n1.json",
    "rg -n write-bulk-commit-sentinel.py",
    "grep -rn write-bulk-commit-sentinel.py commands/ | head -20",
    "git diff -- scripts/write-bulk-commit-sentinel.py | head -40",
    "grep -n argv scripts/write-bulk-commit-sentinel.py # don't edit",
    "ls {state}/claude-bulk-commit-sentinel-* 2>/dev/null",
]


@pytest.mark.parametrize("command", OB_L13_PASSES)
def test_a_read_naming_a_protected_artifact_in_another_command_passes(sandbox, command):
    cmd = command.format(state=sandbox["env"]["CLAUDE_STATE_DIR"])
    r = run(sandbox, SAFETY, cmd)
    assert r.returncode == 0, (cmd, r.stderr)


OB_L13_REFUSALS = [
    ("python3 -m json.tool a.json {state}/claude-commit-dispatch-a.json", "commit-dispatch-attestation-write"),
    ("python3 -m json.tool a.json {state}/claude-commit-grant-a.json", "commit-grant-raw-write"),
    ("python3 -m json.tool a.json {state}/claude-bulk-commit-sentinel-a.json", "bulk-commit-sentinel-write"),
    ("echo {{}} > {state}/claude-commit-dispatch-a.json", "commit-dispatch-attestation-write"),
    ("echo {{}} > {state}/claude-commit-grant-a.json", "commit-grant-raw-write"),
    ("echo {{}} > {state}/claude-bulk-commit-sentinel-a.json", "bulk-commit-sentinel-write"),
    ("python3 scripts/write-bulk-commit-sentinel.py", "bulk-commit-sentinel-write"),
    ("rg --pre ./x {state}/claude-bulk-commit-sentinel-a.json", "bulk-commit-sentinel-write"),
    ("echo {state}/claude-commit-grant-a.json | xargs cp src", "commit-grant-raw-write"),
    ("echo {state}/claude-commit-dispatch-a.json | xargs cp src", "commit-dispatch-attestation-write"),
    ("echo {state}/claude-bulk-commit-sentinel-a.json | xargs cp src", "bulk-commit-sentinel-write"),
    # Section 5 under-defence: both passed bash-safety before OB-L13.
    ("git -c alias.x='!python3 scripts/write-bulk-commit-sentinel.py' x", "bulk-commit-sentinel-write"),
    ("sed -n '1w {state}/claude-bulk-commit-sentinel-x.json' /tmp/forged.json", "bulk-commit-sentinel-write"),
    # The same shapes through other routes the binding must keep closed.
    ("git -c core.pager='python3 scripts/write-bulk-commit-sentinel.py' log", "bulk-commit-sentinel-write"),
    ("sed -n 's/a/b/w {state}/claude-bulk-commit-sentinel-x.json' /tmp/forged.json", "bulk-commit-sentinel-write"),
    ("python3 <<< \"open('{state}/claude-bulk-commit-sentinel-x.json','w')\"", "bulk-commit-sentinel-write"),
    ("python3 - <<'E'\nopen('{state}/claude-bulk-commit-sentinel-x.json','w')\nE", "bulk-commit-sentinel-write"),
    ("cp /tmp/f \"$(ls {state}/claude-bulk-commit-sentinel-*)\"", "bulk-commit-sentinel-write"),
    ("find {state} -name 'claude-bulk-commit-sentinel-*' -fprint /tmp/list", "bulk-commit-sentinel-write"),
    ("cat {state}/claude-bulk-commit-sentinel-x | python3 -c 'pass'", "bulk-commit-sentinel-write"),
    ("touch /tmp/marker && touch {state}/claude-commit-grant-a-n1.json", "commit-grant-raw-write"),
]


@pytest.mark.parametrize("command,label", OB_L13_REFUSALS)
def test_a_write_or_run_of_a_protected_artifact_is_refused(sandbox, command, label):
    cmd = command.format(state=sandbox["env"]["CLAUDE_STATE_DIR"])
    r = run(sandbox, SAFETY, cmd)
    assert r.returncode == 2 and label in r.stderr, (cmd, r.stderr)


# OB-L13 verifier round: routes that carry a protected name into another simple command (a for/select word list,
# a declaration builtin, an env wrapper's assignment, `$_`) and git or reader options that run or write, each
# refused through the real hook. {S} is the sandbox state dir.
_W = "scripts/write-bulk-commit-sentinel.py"
_SENT = "{S}/claude-bulk-commit-sentinel-x.json"
_GRANT = "{S}/claude-commit-grant-a.json"
OB_L13_ROUND2_BULK_REFUSALS = [
    f"for f in {_W}; do python3 $f; done",
    f"for f in {_W}; do . $f; done",
    f"select f in {_W}; do python3 $f; break; done",
    f"for f in {_SENT}; do touch $f; done",
    f"for f in {_SENT}; do python3 /tmp/w.py $f; done",
    f"for f in $(ls {_SENT}); do touch $f; done",
    "export f=write-bulk-commit-sentinel.py; cd scripts; python3 $f",
    "declare f=Xwrite-bulk-commit-sentinel.py; cd scripts; python3 ${{f#X}}",
    "local f=Xwrite-bulk-commit-sentinel.py; cd scripts; python3 ${{f#X}}",
    "readonly f=Xwrite-bulk-commit-sentinel.py; cd scripts; python3 ${{f#X}}",
    "typeset f=Xwrite-bulk-commit-sentinel.py; cd scripts; python3 ${{f#X}}",
    f"env GIT_SSH_COMMAND='python3 {_W}' git fetch origin",
    f"env GIT_EXTERNAL_DIFF='python3 {_W}' git diff",
    f"nice env GIT_EDITOR='python3 {_W}' git commit --amend",
    f"env PYTHONSTARTUP={_W} python3 -i",
    f"[ -f {_SENT} ] || touch \"$_\"",
    f"file {_SENT} && python3 /tmp/w.py \"$_\"",
    f"ls -d {_SENT} && touch $_",
    f"ls -d {_SENT} && python3 /tmp/w.py ${{{{_}}}}",
    f"git diff --output={_SENT}",
    f"git log -1 --format='{{{{}}}}' --output={_SENT}",
    f"git diff --output {_SENT} HEAD",
    f"git difftool -x 'python3 {_W}'",
    f"git difftool --extcmd='python3 {_W}'",
    f"git bisect run python3 {_W}",
    f"git submodule foreach python3 {_W}",
    f"git grep -O'python3 {_W}' x",
    f"git grep --open-files-in-pager='python3 {_W}' x",
    f"rg --hostname-bin={_W} x",
    f"file -C -m {_SENT}",
]


@pytest.mark.parametrize("command", OB_L13_ROUND2_BULK_REFUSALS)
def test_a_protected_name_carried_into_a_run_or_write_is_refused(sandbox, command):
    cmd = command.format(S=sandbox["env"]["CLAUDE_STATE_DIR"])
    r = run(sandbox, SAFETY, cmd)
    assert r.returncode == 2 and "bulk-commit-sentinel-write" in r.stderr, (cmd, r.stderr)


OB_L13_ROUND2_GRANT_REFUSALS = [
    f"python3 -m json.tool {_GRANT}; cp /tmp/g $_",
    f"PYTHONPATH=/tmp/evil python3 -m json.tool {_GRANT}",
    f"env PYTHONPATH=/tmp/evil python3 -m json.tool {_GRANT}",
    f"cat {_GRANT} && python3 /tmp/w.py \"${{{{_}}}}\"",
    f"for f in {_GRANT}; do cp /tmp/g $f; done",
]


@pytest.mark.parametrize("command", OB_L13_ROUND2_GRANT_REFUSALS)
def test_a_grant_name_carried_into_a_write_is_refused(sandbox, command):
    cmd = command.format(S=sandbox["env"]["CLAUDE_STATE_DIR"])
    r = run(sandbox, SAFETY, cmd)
    assert r.returncode == 2 and "commit-grant-raw-write" in r.stderr, (cmd, r.stderr)


OB_L13_ROUND2_PASSES = [
    f"git log --oneline -- {_W}",
    f"git show HEAD:{_W} | head -20",
    f"git grep -n argv -- {_W}",
    f"git diff --stat -- {_W}",
    f"git add {_W}",
    "git commit -m 'fix write-bulk-commit-sentinel.py fallback'",
    f"git log -1 --format='%H' -- {_W}",
    f"cat {_SENT}",
    f"[ -f {_SENT} ] && echo present",
    f"file {_SENT}",
    f"python3 -m json.tool {_GRANT}",
    f"for f in a b; do echo $f; done; ls {_SENT}",
]


@pytest.mark.parametrize("command", OB_L13_ROUND2_PASSES)
def test_a_plain_read_of_a_protected_name_still_passes(sandbox, command):
    cmd = command.format(S=sandbox["env"]["CLAUDE_STATE_DIR"])
    r = run(sandbox, SAFETY, cmd)
    assert r.returncode == 0, (cmd, r.stderr)
