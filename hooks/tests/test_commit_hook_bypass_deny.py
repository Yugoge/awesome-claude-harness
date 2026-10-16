"""P7 R7b agent-side denies in hooks/pretool-bash-safety.sh.

Two rules, enforced for the main agent and for subagents alike and ahead of the
/do and /allow bypasses:

* commit-hook-bypass: a command holding a git `commit` invocation may not skip
  the commit hooks (--no-verify and its abbreviations, -n in a short-option
  cluster, a core.hooksPath override, a GIT_CONFIG_* environment assignment).
* unregistered-settings-filter: such a command may not run while a candidate
  repository declares the claude-settings filter for settings.json, has no local
  filter registration, and settings.json differs from HEAD (index or work tree).
  Candidates are the cwd, cd and -C targets, and the repository a commit names
  with --git-dir/--work-tree or a GIT_DIR/GIT_WORK_TREE prefix or export.

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
    # item 4 (review R7b): quoting/escaping inside `commit` or `git`, and a
    # `-c alias.*` whose value — normal or a `!`-shell alias — commits with a skip.
    "git co''mmit -n -m x",
    "git comm\\it -n -m x",
    "g''it commit -n -m x",
    "gi\\t commit --no-verify",
    "git -c alias.ci='commit --no-verify' ci -m x",
    "git -c alias.p='!git commit -n' p",
    # review round 2, R1: git expands an alias together with the arguments that
    # follow its name, so the skip may come after the alias word (also quoted,
    # in a chain of aliases, or inside a `!`-shell alias that defines one).
    "git -c alias.ci=commit ci -n -m x",
    "git -c alias.ci=commit ci --no-verify -m x",
    "git -c \"alias.ci=!git commit\" ci -n -m x",
    "g''it -c 'alias.ci=commit' ci '--no-verify' -m x",
    "git -c alias.ci=co''mmit ci -anm x",
    "git -calias.ci=commit ci --no-veri -m x",
    "git -c \"alias.ci=!g''it commit\" ci -n -m x",
    "git -c alias.a=ci -c alias.ci=commit a -n -m x",
    "git -c \"alias.p=!git -c alias.ci=commit ci\" p -n -m x",
    # the one-off include override on a commit (its persistent write is R2 below)
    "git -c include.path=inc.cfg commit -m x",
    "git -c 'includeIf.gitdir:/srv/repo/.path=inc.cfg' commit -m x",
]

# item 4: git config WRITES to a keystone key (core.hooksPath / alias.* /
# filter.claude-settings.*), in both the classic-option and the newer-subcommand
# syntax, are denied for every caller.
CONFIG_WRITE_CASES = [
    "git config alias.ci 'commit --no-verify'",
    "git config core.hooksPath /dev/null",
    "git config --unset filter.claude-settings.clean",
    "git config --add alias.ci 'commit -n'",
    "git config --replace-all core.hooksPath /dev/null",
    "git config --unset-all filter.claude-settings.smudge",
    "git config --remove-section alias",
    "git config --rename-section alias myalias",
    "git config set core.hooksPath x",
    "git config unset filter.claude-settings.required",
    "git config remove-section alias",
    "g''it config core.hooksPath x",
    # review round 2, R2: a persistent include loads a config file that may set
    # any key above (a hooks path, say) for every later plain commit, so the
    # include section, include.path and every includeIf.<condition>.path key are
    # keystone keys too. Section and variable names match case-insensitively;
    # the condition keeps its case and may hold dots, colons, slashes or globs.
    "git config include.path /home/acct-test-123/inc.cfg",
    "git config --global include.path inc.cfg",
    "git config --local include.path inc.cfg",
    "git config --add include.path inc.cfg",
    "git config --replace-all include.path inc.cfg",
    "git config --unset include.path",
    "git config --unset-all include.path",
    "git config --remove-section include",
    "git config --rename-section include other",
    "git config set include.path inc.cfg",
    "git config set --append include.path inc.cfg",
    "git config unset include.path",
    "git config unset --all include.path",
    "git config add include.path inc.cfg",
    "git config replace-all include.path inc.cfg",
    "git config unset-all include.path",
    "git config remove-section include",
    "git config rename-section include other",
    "git config Include.PATH inc.cfg",
    "git config 'include.path' inc.cfg",
    "git config \"include.path\" inc.cfg",
    "g''it config incl''ude.path inc.cfg",
    "git con\\fig include.pa\\th inc.cfg",
    "git config includeIf.gitdir:/home/acct-test-123/proj/.path inc.cfg",
    "git config --global includeIf.gitdir:~/work/.path inc.cfg",
    "git config --add includeIf.gitdir/i:/srv/Repo/.path inc.cfg",
    "git config --replace-all includeIf.onbranch:main.path inc.cfg",
    "git config --unset includeIf.gitdir:/srv/repo/.path",
    "git config set includeIf.hasconfig:remote.*.url:https://example.invalid/**.path inc.cfg",
    "git config unset includeIf.gitdir:/srv/repo/.path",
    "git config INCLUDEIF.gitdir:/srv/Repo/.Path inc.cfg",
    "git config 'includeIf.gitdir:/srv/a b/.path' inc.cfg",
    "git config \"includeIf.gitdir:/srv/repo/.path\" inc.cfg",
    "g''it config includ''eIf.gitdir:/srv/repo/.pa''th inc.cfg",
]

ALLOWED_CASES = [
    'echo "git commit --no-verify"',
    'git commit -m "-n"',
    "git commit -m x",
    "git commit -m -n",
    "git commit -mn",
    "printf '%s\\n' \"x; git commit -n\"",
    # item 4: config reads, a non-keystone write, the one-argument read form, and
    # commands whose text merely mentions commit/config are not a bypass.
    "git config --get core.hooksPath",
    "git config --get-all alias.ci",
    "git config --list",
    "git config core.hooksPath",
    "git config get core.hooksPath",
    "git config list",
    "git config alias.ci",
    "git config user.name acct-test-123",
    "git log --grep commit",
    "echo commit",
    "echo 'a config change'",
    # R1 controls: an alias plus arguments that skip nothing, an alias whose
    # value is not commit, and an alias loop (git refuses it) ending at the
    # guard's recursion limit.
    "git -c alias.ci=commit ci -m x",
    "git -c alias.ci=commit ci -m '-n' --author acct-test-123",
    "git -c \"alias.ci=!git commit\" ci -m x",
    "git -c alias.l=log l -n 3",
    "git -c alias.ci=ci ci -n -m x",
    # R2 controls: reads of the include keys, and writes to keys that only
    # mention include elsewhere (another section, a longer name, the value).
    "git config --get include.path",
    "git config --get-all include.path",
    "git config --get-regexp '^includeif\\.'",
    "git config -l --show-origin",
    "git config get include.path",
    "git config get --all includeIf.gitdir:/srv/repo/.path",
    "git config list --show-origin",
    "git config include.path",
    "git config includeIf.gitdir:/srv/repo/.path",
    "git config includes.path inc.cfg",
    "git config acct-test.include inc.cfg",
    "git config core.includePath inc.cfg",
    "git config acct-include.path inc.cfg",
    "git config remote.origin.url https://example.invalid/include.path",
    "git config user.name include",
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


# ---------------- config-keystone-write ----------------

@pytest.mark.parametrize("caller", sorted(CALLERS))
@pytest.mark.parametrize("command", CONFIG_WRITE_CASES)
def test_config_keystone_write_is_blocked(sandbox, caller, command):
    tmp_path, env = sandbox
    repo = make_repo(env, tmp_path / "plain" / "repo", declare_filter=False)
    assert_blocked(run_hook(sandbox, command, repo, caller), "config-keystone-write", command)


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


# Forms that name the repository without cwd, cd or -C: --git-dir/--work-tree
# (attached or separate value, relative values against the final directory, a
# command-line option over the environment) and GIT_DIR/GIT_WORK_TREE as an
# assignment prefix, through `env`, or exported earlier in the same command.
GIT_DIR_FORMS = {
    "git-dir-attached": "git --git-dir={gitdir} --work-tree={repo} commit -m x",
    "git-dir-separate": "git --git-dir {gitdir} --work-tree {repo} commit -m x",
    "git-dir-relative": "cd {top} && git --git-dir={rel_gitdir} --work-tree={rel_repo} commit -m x",
    "option-over-env": "GIT_DIR={top}/none GIT_WORK_TREE={top}/none "
                       "git --git-dir={gitdir} --work-tree={repo} commit -m x",
    "env-prefix": "GIT_DIR={gitdir} GIT_WORK_TREE={repo} git commit -m x",
    "env-wrapper": "env GIT_DIR={gitdir} GIT_WORK_TREE={repo} git commit -m x",
    "exported": "export GIT_DIR={gitdir} GIT_WORK_TREE={repo} && git commit -m x",
    "exported-separately": "export GIT_DIR={gitdir}; export GIT_WORK_TREE={repo}; git commit -m x",
}
# The git dir inside the work tree, or moved out of it (then the work tree holds
# no .git, so neither the cwd nor a cd or -C target can lead to the repository).
LAYOUTS = ("embedded", "separate")


def layout_repo(env, tmp_path, name, layout, declare_filter):
    repo = make_repo(env, tmp_path / name, declare_filter)
    gitdir = repo / ".git"
    if layout == "separate":
        (tmp_path / "store").mkdir(exist_ok=True)
        gitdir = gitdir.rename(tmp_path / "store" / f"{name}.git")
    return repo, gitdir


def form_command(form, tmp_path, repo, gitdir):
    return GIT_DIR_FORMS[form].format(repo=repo, gitdir=gitdir, top=tmp_path,
                                      rel_repo=repo.relative_to(tmp_path),
                                      rel_gitdir=gitdir.relative_to(tmp_path))


@pytest.mark.parametrize("caller", sorted(CALLERS))
@pytest.mark.parametrize("layout", LAYOUTS)
@pytest.mark.parametrize("form", sorted(GIT_DIR_FORMS))
def test_unregistered_filter_is_found_through_git_dir_and_environment(sandbox, caller, layout, form):
    tmp_path, env = sandbox
    repo, gitdir = layout_repo(env, tmp_path, "harness", layout, declare_filter=True)
    _modify_work_tree(env, repo)
    command = form_command(form, tmp_path, repo, gitdir)
    r = run_hook(sandbox, command, tmp_path / "elsewhere", caller)
    assert_blocked(r, "unregistered-settings-filter", command)
    assert str(repo) in r.stderr.splitlines()[0]


@pytest.mark.parametrize("caller", sorted(CALLERS))
@pytest.mark.parametrize("layout", LAYOUTS)
@pytest.mark.parametrize("form", sorted(GIT_DIR_FORMS))
def test_git_dir_and_environment_forms_pass_for_a_clean_target(sandbox, caller, layout, form):
    """The same forms pass when the repository they name has the filter
    registered, declares no filter, or has settings.json unchanged."""
    tmp_path, env = sandbox
    registered, reg_gitdir = layout_repo(env, tmp_path, "registered", layout, declare_filter=True)
    subprocess.run(["git", f"--git-dir={reg_gitdir}", "config", "--local",
                    "filter.claude-settings.clean", "cat"],
                   env=env, check=True, capture_output=True, text=True, timeout=60)
    plain, plain_gitdir = layout_repo(env, tmp_path, "plain-repo", layout, declare_filter=False)
    unchanged, unchanged_gitdir = layout_repo(env, tmp_path, "unchanged", layout, declare_filter=True)
    _modify_work_tree(env, registered)
    _modify_work_tree(env, plain)
    for repo, gitdir in ((registered, reg_gitdir), (plain, plain_gitdir), (unchanged, unchanged_gitdir)):
        command = form_command(form, tmp_path, repo, gitdir)
        assert_allowed(run_hook(sandbox, command, tmp_path / "elsewhere", caller))


@pytest.mark.parametrize("caller", sorted(CALLERS))
def test_git_dir_of_another_command_does_not_retarget_the_commit(sandbox, caller):
    """An assignment prefix binds only its own command, and a git dir named by a
    non-commit invocation is not a commit target."""
    tmp_path, env = sandbox
    repo, gitdir = layout_repo(env, tmp_path, "harness", "separate", declare_filter=True)
    _modify_work_tree(env, repo)
    for command in (f"GIT_DIR={gitdir} GIT_WORK_TREE={repo} git status; git commit -m x",
                    f"git --git-dir={gitdir} --work-tree={repo} log --grep commit"):
        assert_allowed(run_hook(sandbox, command, tmp_path / "elsewhere", caller))


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
    cw = "git config core.hooksPath /dev/null"
    assert_blocked(run_hook(sandbox, cw, plain, caller), "config-keystone-write", cw)
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
    grant("config")
    cw = "git config --unset filter.claude-settings.clean"
    assert_blocked(run_hook(sandbox, cw, plain, caller), "config-keystone-write", cw)
    _modify_work_tree(env, filtered_repo)
    assert_blocked(run_hook(sandbox, "git commit -m x", filtered_repo, caller),
                   "unregistered-settings-filter", "git commit -m x")
