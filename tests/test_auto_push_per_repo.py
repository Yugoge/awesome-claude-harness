"""harness.autoPush, the per-repository push switch (D1 as amended on 2026-11-07).

A repository's local git config harness.autoPush decides whether automatic pushes run for it;
when the key is unset, the global GIT_AUTO_PUSH decides exactly as before (only "1" pushes). One
function reads it, harness_auto_push in hooks/lib/auto_push.sh, and every automatic push path
calls it:

  checkpoint    hooks/lib/checkpoint-core.sh: write_checkpoint writes refs/checkpoints/<branch>
                and its detached worker pushes it (_checkpoint_rate_limited_push);
  fswatch       hooks/git-fswatch.sh safe_push (its functions are loaded, the watcher never runs);
  session init  hooks/session-git-init.sh, with test_git_auto_push_opt_in.py's stub gh: the
                initial push to the origin that gh repo create makes (--push). The hook creates
                the repository itself, so its harness.autoPush comes from a git init template;
  post_commit   hooks/git-hooks/post-commit-auto-push installed as a post-commit hook: the
                background push of refs/backups/claude/<branch>/<sha12>;
  combined_hook the combined "Git LFS + Auto-Push" post-commit hook body that
                hooks/install-protection-all.sh writes (extracted, the installer never runs): the
                background push of the branch. Both hooks are copies with no path of their own:
                they load the reader from ${CLAUDE_HOME:-$HOME/.claude}/hooks/lib/, and without
                it they push nothing.

Each path runs every row of SWITCHES: global on and repository false (no push), global off or
unset and repository true (push), the key unset (the global switch decides), a repository value
git cannot read as a boolean (no push), and a harness.autoPush in the global git config only (not
read: the global switch stays GIT_AUTO_PUSH). /checkpoint's closing message follows the same
switch. Init (scripts/bootstrap) and the landing (scripts/install/land) set false in a harness
home that lacks the key and keep a value already set. The landing also replaces a post-commit hook
that is a byte-for-byte copy of an earlier version of the template (installed by hand, so it never
read the switch), once per template write, and leaves edited and tracked hooks alone.

Every case has its own scratch HOME and global git config (no system config) and its own
repositories; every origin is a local bare repository, so nothing reaches a network or a real home.
"""

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest

from tests.test_bootstrap_init import Home
from tests.test_git_auto_push_opt_in import (AUTO_PUSH_LIB, BRANCH, CHECKPOINT_CMD,
                                             CHECKPOINT_LIB, CHECKPOINT_NOTE, NEGATIVE_SETTLE,
                                             POLL_INTERVAL, POSITIVE_TIMEOUT, POST_COMMIT_HOOK,
                                             PROJECT_NAME, SKIP_MARKER, Run, _combined_hook_body,
                                             _fswatch_functions, _git, _install_post_commit,
                                             _new_repo, _origin_refs, _run,
                                             _run_session_git_init, _scratch_env)
from tests.test_landing import env  # noqa: F401  (the landing tests' scratch-home fixture)
from tests.test_landing import REPO, assert_landed, git, land, landing_log, make_home


@dataclass(frozen=True)
class Switch:
    id: str
    global_push: Optional[str]  # GIT_AUTO_PUSH; None leaves it out of the environment
    repo: Optional[str]         # the repository's local harness.autoPush; None leaves it unset
    pushes: bool
    gitconfig: str = ""         # the scratch global git config's text


SWITCHES = (
    Switch("global-on-repo-false", "1", "false", False),
    Switch("global-off-repo-true", "0", "true", True),
    Switch("global-unset-repo-true", None, "true", True),
    Switch("global-off-repo-yes", "0", "yes", True),  # git's own boolean spellings count
    Switch("global-on-key-unset", "1", None, True),
    Switch("global-off-key-unset", "0", None, False),
    Switch("global-unset-key-unset", None, None, False),
    Switch("global-on-repo-not-a-boolean", "1", "maybe", False),
    Switch("global-off-gitconfig-true", "0", None, False, "[harness]\n\tautoPush = true\n"),
)
IDS = [s.id for s in SWITCHES]
KEY = "harness.autoPush"


def _env(base: Path, switch: Switch, gitconfig: str = "") -> dict:
    return _scratch_env(base, "unset" if switch.global_push is None else switch.global_push,
                        switch.gitconfig + gitconfig)


def _set_key(env: dict, repo: Path, value: Optional[str]) -> None:
    if value is not None:
        _git(env, "-C", repo, "config", "--local", KEY, value)


def _judge(run: Run, pushes: bool) -> None:
    """A push: the origin's ref reaches the expected commit within POSITIVE_TIMEOUT. No push:
    the origin's refs are unchanged NEGATIVE_SETTLE seconds after the trigger."""
    label = f"{run.path} {run.case}"
    if pushes:
        deadline = time.monotonic() + POSITIVE_TIMEOUT
        got = _git(run.env, f"--git-dir={run.origin}", "rev-parse", "--verify", "-q",
                   run.expected_ref, check=False)
        while got != run.expected_sha and time.monotonic() < deadline:
            time.sleep(POLL_INTERVAL)
            got = _git(run.env, f"--git-dir={run.origin}", "rev-parse", "--verify", "-q",
                       run.expected_ref, check=False)
        assert got == run.expected_sha, (
            f"{label}: origin {run.expected_ref} is {got or 'absent'}, expected "
            f"{run.expected_sha}\n{run.output}")
        return
    remaining = run.triggered_at + NEGATIVE_SETTLE - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)
    after = _origin_refs(run.env, run.origin)
    assert after == run.origin_before, (
        f"{label}: origin changed\nbefore:\n{run.origin_before}\nafter:\n{after}\n{run.output}")


# --------------------------------------------------------------------------- checkpoint


def _trigger_checkpoint(base: Path, switch: Switch) -> Run:
    env = _env(base, switch)
    repo, origin = _new_repo(base, env)
    _set_key(env, repo, switch.repo)
    origin_before = _origin_refs(env, origin)
    (repo / "notes.txt").write_text(CHECKPOINT_NOTE)  # a change, so a checkpoint is written
    script = 'source "$1" || exit 90; write_checkpoint "$2" "per-repo push test" "per-repo push"'
    proc = _run(["bash", "-c", script, "bash", CHECKPOINT_LIB, repo], env, check=False)
    triggered_at = time.monotonic()
    ref = f"refs/checkpoints/{BRANCH}"
    sha = _git(env, "-C", repo, "rev-parse", "--verify", "-q", ref, check=False)
    return Run("checkpoint", switch.id, env, repo, origin, origin_before, ref, sha,
               proc.returncode, proc.stdout + proc.stderr, triggered_at)


def _commit_with_hook(base: Path, env: dict, switch: Switch, path: str) -> Run:
    """One commit in a fresh repository whose post-commit hook is the path's hook body."""
    hook_text = POST_COMMIT_HOOK.read_text(encoding="utf-8") if path == "post_commit" \
        else _combined_hook_body()
    repo, origin = _new_repo(base, env)
    _set_key(env, repo, switch.repo)
    _install_post_commit(repo, hook_text)
    (repo / "change.txt").write_text("plain words for a fresh commit\n")
    _git(env, "-C", repo, "add", "change.txt")
    origin_before = _origin_refs(env, origin)
    proc = _run(["git", "-C", repo, "commit", "-q", "-m", "plain commit under test"], env,
                check=False)
    triggered_at = time.monotonic()
    head = _git(env, "-C", repo, "rev-parse", "HEAD")
    ref = (f"refs/backups/claude/{BRANCH}/{head[:12]}" if path == "post_commit"
           else f"refs/heads/{BRANCH}")
    return Run(path, switch.id, env, repo, origin, origin_before, ref, head, proc.returncode,
               proc.stdout + proc.stderr, triggered_at)


BACKGROUND_PATHS = ("checkpoint", "post_commit", "combined_hook")


@pytest.fixture(scope="module")
def background_runs(tmp_path_factory) -> dict:
    """Every case of the paths that push in the background, triggered up front so that their
    push waits overlap; keyed by (path, switch id)."""
    base = tmp_path_factory.mktemp("per_repo_background")
    runs = {}
    for path in BACKGROUND_PATHS:
        for switch in SWITCHES:
            case = base / f"{path}-{switch.id}"
            case.mkdir()
            runs[(path, switch.id)] = (_trigger_checkpoint(case, switch) if path == "checkpoint"
                                       else _commit_with_hook(case, _env(case, switch), switch,
                                                              path))
    return runs


@pytest.mark.parametrize("switch", SWITCHES, ids=IDS)
def test_checkpoint_push_follows_the_repository_switch(background_runs, switch):
    run = background_runs[("checkpoint", switch.id)]
    assert run.returncode == 0, run.output
    assert run.expected_sha, f"no local {run.expected_ref} was written\n{run.output}"
    _judge(run, switch.pushes)


# --------------------------------------------------------------------------- post-commit hooks


@pytest.mark.parametrize("switch", SWITCHES, ids=IDS)
@pytest.mark.parametrize("path", ("post_commit", "combined_hook"))
def test_post_commit_hook_push_follows_the_repository_switch(background_runs, path, switch):
    run = background_runs[(path, switch.id)]
    assert run.returncode == 0, run.output
    _judge(run, switch.pushes)


@pytest.mark.parametrize("where", ("claude-home", "missing"))
def test_post_commit_hook_reads_the_switch_from_the_harness_home(tmp_path, where):
    """The reader is found under CLAUDE_HOME when it is not under ~/.claude; found nowhere, the
    hook pushes nothing even with GIT_AUTO_PUSH "1" and says why on stderr, which git shows the
    committer (no log file: P1b removed the hook's log as written and never read)."""
    switch = Switch(where, "1", None, where == "claude-home")
    env = _env(tmp_path, switch)
    (Path(env["HOME"]) / ".claude" / "hooks" / "lib" / "auto_push.sh").unlink()
    if where == "claude-home":
        harness = tmp_path / "harness-elsewhere"
        (harness / "hooks" / "lib").mkdir(parents=True)
        shutil.copyfile(AUTO_PUSH_LIB, harness / "hooks" / "lib" / "auto_push.sh")
        env["CLAUDE_HOME"] = str(harness)
    run = _commit_with_hook(tmp_path, env, switch, "post_commit")
    assert run.returncode == 0, run.output
    _judge(run, switch.pushes)
    assert ("no backup push: the switch's reader" in run.output) == (where == "missing"), run.output
    assert not (Path(env["HOME"]) / ".claude" / "logs" / "post-commit-auto-push.log").exists()


# --------------------------------------------------------------------------- git-fswatch


@pytest.mark.parametrize("switch", SWITCHES, ids=IDS)
def test_fswatch_push_follows_the_repository_switch(tmp_path, switch):
    env = _env(tmp_path, switch)
    functions = _fswatch_functions(tmp_path)
    repo, origin = _new_repo(tmp_path, env)
    _set_key(env, repo, switch.repo)
    _git(env, "-C", repo, "fetch", "-q", "origin")
    (repo / "ahead.txt").write_text("plain words one commit ahead of origin\n")
    _git(env, "-C", repo, "add", "ahead.txt")
    _git(env, "-C", repo, "commit", "-q", "-m", "one plain commit ahead")
    head = _git(env, "-C", repo, "rev-parse", "HEAD")
    origin_before = _origin_refs(env, origin)
    script = ('source "$1" "$2"; loaded=$?; trap - EXIT INT TERM; '
              '[ "$loaded" -eq 0 ] || exit 90; safe_push')
    proc = _run(["bash", "-c", script, "bash", functions, repo], env, check=False)
    run = Run("fswatch", switch.id, env, repo, origin, origin_before, f"refs/heads/{BRANCH}",
              head, proc.returncode, proc.stdout + proc.stderr, time.monotonic() - NEGATIVE_SETTLE)
    assert proc.returncode == 0, run.output
    _judge(run, switch.pushes)  # safe_push is synchronous: no settling wait is needed
    log = Path(env["HOME"]) / ".claude" / "logs" / f"git-fswatch-{repo.name}.log"
    text = log.read_text(errors="replace") if log.exists() else ""
    skipped = [ln for ln in text.splitlines() if SKIP_MARKER in ln]
    assert len(skipped) == (0 if switch.pushes else 1), skipped


# --------------------------------------------------------------------------- session-git-init


@pytest.mark.parametrize("switch", SWITCHES, ids=IDS)
def test_session_git_init_push_follows_the_repository_switch(tmp_path, switch):
    gitconfig = ""
    if switch.repo is not None:  # the hook runs git init, so the key comes from its template
        template = tmp_path / "git-template"
        template.mkdir()
        (template / "config").write_text(f"[harness]\n\tautoPush = {switch.repo}\n")
        gitconfig = f"[init]\n\ttemplateDir = {template}\n"
    output, creates, origin_refs = _run_session_git_init(
        tmp_path, "unset" if switch.global_push is None else switch.global_push, create="true",
        gitconfig=switch.gitconfig + gitconfig)
    project_key = _git(_scratch_env(tmp_path / "probe", "unset"), "config", "--file",
                       tmp_path / PROJECT_NAME / ".git" / "config", "--get", KEY, check=False)
    assert project_key == (switch.repo or ""), "the new repository carries the template's key"
    assert len(creates) == 1, f"expected one gh repo create call: {creates}\n{output}"
    assert ("--push" in creates[0]) == switch.pushes, creates[0]
    assert origin_refs is not None and bool(origin_refs) == switch.pushes, (origin_refs, output)
    assert ("not pushed" in output) == (not switch.pushes), output


# --------------------------------------------------------------------------- /checkpoint message


@pytest.mark.parametrize("switch", SWITCHES, ids=IDS)
def test_checkpoint_command_message_follows_the_repository_switch(tmp_path, switch):
    env = _env(tmp_path, switch)
    repo, _origin = _new_repo(tmp_path, env)
    _set_key(env, repo, switch.repo)
    (repo / "notes.txt").write_text(CHECKPOINT_NOTE)
    out = _run(["bash", CHECKPOINT_CMD], env, cwd=repo)
    out = out.stdout + out.stderr
    ref = f"refs/checkpoints/{BRANCH}"
    assert (f"Background push of {ref}" in out) == switch.pushes, out
    assert (f"{ref} is local only" in out) == (not switch.pushes), out


# --------------------------------------------------------------------------- init and landing


@pytest.mark.parametrize("preset", (None, "true", "yes"), ids=("absent", "true", "yes"))
def test_init_sets_false_only_when_the_key_is_absent(tmp_path, preset):
    home = Home(tmp_path)
    assert home.git("config", "--local", "--get", KEY, check=False).returncode == 1
    if preset is not None:
        home.git("config", "--local", KEY, preset)
    out = home.bootstrap("--yes", "--no-doctor").stdout
    assert home.git("config", "--local", "--get", KEY).stdout.strip() == (preset or "false")
    assert ("harness.autoPush set to false" in out) == (preset is None), out


def _home_key(env, home):
    proc = git(env, home, "config", "--local", "--get", KEY, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


@pytest.mark.parametrize("preset", (None, "true"), ids=("absent", "true"))
def test_landing_an_upgraded_home_sets_false_only_when_the_key_is_absent(tmp_path, env, preset):
    home, _rev = make_home(tmp_path, env)
    assert _home_key(env, home) is None
    if preset is not None:
        git(env, home, "config", "--local", KEY, preset)
    land(env, home)
    assert_landed(env, home)
    assert _home_key(env, home) == (preset or "false")


@pytest.mark.parametrize("preset", (None, "true"), ids=("absent", "true"))
def test_a_landed_home_gets_false_at_its_next_turn_end_only_when_the_key_is_absent(
        tmp_path, env, preset):
    """The owner's home landed before this change: the next Stop's landing sets the key, with
    no notice, and leaves a value the owner set."""
    home, _rev = make_home(tmp_path, env)
    land(env, home)
    git(env, home, "config", "--local", "--unset", KEY)
    if preset is not None:
        git(env, home, "config", "--local", KEY, preset)
    log = landing_log(home)
    assert land(env, home) == ""
    assert _home_key(env, home) == (preset or "false")
    assert ("harness.autoPush set" in landing_log(home)[len(log):]) == (preset is None)
    assert_landed(env, home)


# --------------------------------------------------------------------------- installed hook copies

TEMPLATE = "hooks/git-hooks/post-commit-auto-push"
# Earlier versions of the template, as git blob ids: copies of them were installed by hand (`cp`),
# and none reads harness.autoPush.
OLD_COPIES = {"07e3b9d": "pre-P0 legacy, pushes unless GIT_AUTO_PUSH is 0",
              "f0e813d": "P0 opt-in, with a log", "9f4198b": "P1b opt-in, no log"}


def _blob(oid: str) -> bytes:
    return subprocess.run(["git", "-C", str(REPO), "cat-file", "blob", oid], capture_output=True,
                          check=True).stdout


def _ship_history(env, home):
    """Commits (plumbing: no hook, no filter) that give the home's template each old version in
    turn and then its current content again, the history a real home has; the tree, index and
    working copy end as they were."""
    parent = git(env, home, "rev-parse", "HEAD").stdout.strip()
    current = git(env, home, "rev-parse", f"HEAD:{TEMPLATE}").stdout.strip()
    for version in [*OLD_COPIES, None]:
        oid = current if version is None else subprocess.run(
            ["git", "-C", str(home), "hash-object", "-w", "--no-filters", "--stdin"],
            input=_blob(version), env=env, capture_output=True, check=True).stdout.decode().strip()
        index = dict(env, GIT_INDEX_FILE=str(home / ".git" / "ship-index"))
        git(index, home, "read-tree", parent)
        git(index, home, "update-index", "--cacheinfo", f"100755,{oid},{TEMPLATE}")
        tree = git(index, home, "write-tree").stdout.strip()
        (home / ".git" / "ship-index").unlink()
        parent = git(env, home, "commit-tree", tree, "-p", parent, "-m", f"template {version}").stdout.strip()
    git(env, home, "update-ref", "HEAD", parent)


def _a_pull_rewrites_the_template(home):
    template = home / TEMPLATE
    template.write_bytes(template.read_bytes())  # git checkout writes it: a newer mtime


def _product(env, tmp_path, name, hook_bytes):
    """A product repository under the scratch HOME, harness.autoPush false, a local bare origin,
    and hook_bytes as its .git/hooks/post-commit. Returns (repo, origin, hook)."""
    repo = Path(env["HOME"]) / "projects" / name
    origin = tmp_path / f"{name}-origin.git"
    git(env, tmp_path, "init", "-q", "--bare", str(origin))
    git(env, tmp_path, "init", "-q", "-b", "master", str(repo))
    (repo / "a.txt").write_text("plain words\n")
    git(env, repo, "add", "a.txt")
    git(env, repo, "commit", "-q", "-m", "one")
    git(env, repo, "remote", "add", "origin", str(origin))
    git(env, repo, "config", "--local", KEY, "false")
    hook = repo / ".git" / "hooks" / "post-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_bytes(hook_bytes)
    hook.chmod(0o755)
    return repo, origin, hook


def _commit_pushes_a_backup(env, repo, origin, pushes):
    """One commit with GIT_AUTO_PUSH "1" and the reader reachable: does a backup ref reach origin?"""
    e = dict(env, GIT_AUTO_PUSH="1", CLAUDE_HOME=str(REPO))
    stamp = f"{time.monotonic()}\n"
    (repo / "b.txt").write_text(stamp)
    git(e, repo, "add", "b.txt")
    git(e, repo, "commit", "-q", "-m", "plain commit under test")
    head = git(e, repo, "rev-parse", "HEAD").stdout.strip()
    ref = f"refs/backups/claude/master/{head[:12]}"
    deadline = time.monotonic() + (POSITIVE_TIMEOUT if pushes else NEGATIVE_SETTLE)
    while time.monotonic() < deadline:
        got = git(env, origin.parent, "--git-dir", str(origin), "rev-parse", "--verify", "-q", ref,
                  check=False).stdout.strip()
        if got:
            return True
        time.sleep(POLL_INTERVAL)
    return False


@pytest.mark.parametrize("state", ("upgraded", "landed"))
@pytest.mark.parametrize("version", list(OLD_COPIES))
def test_a_landing_replaces_an_installed_copy_of_an_earlier_hook(tmp_path, env, state, version):
    """A product repository whose post-commit hook is a byte-for-byte copy of an earlier
    template follows harness.autoPush after the landing: the first landing of an upgraded home,
    or, on the owner's already-landed home, the turn end after a pull changed the template."""
    home, _rev = make_home(tmp_path, env)
    _ship_history(env, home)
    if state == "landed":
        land(env, home)
        _a_pull_rewrites_the_template(home)
    repo, origin, hook = _product(env, tmp_path, "app", _blob(version))
    land(env, home)
    assert hook.read_bytes() == (home / TEMPLATE).read_bytes(), OLD_COPIES[version]
    assert hook.stat().st_mode & 0o777 == 0o755
    assert "post-commit-refreshed=1" in landing_log(home)
    assert not _commit_pushes_a_backup(env, repo, origin, pushes=False), "harness.autoPush false"
    git(env, repo, "config", "--local", KEY, "true")
    assert _commit_pushes_a_backup(env, repo, origin, pushes=True), "harness.autoPush true"


def test_a_copy_with_edits_and_a_tracked_hook_stay_as_they_are(tmp_path, env):
    home, _rev = make_home(tmp_path, env)
    _ship_history(env, home)
    edited = _blob("9f4198b") + b"# my own line\n"
    _repo, _origin, hook = _product(env, tmp_path, "edited", edited)
    shared, _, _ = _product(env, tmp_path, "shared", b"#!/bin/bash\nexit 0\n")
    (shared / ".githooks").mkdir()
    (shared / ".githooks" / "post-commit").write_bytes(_blob("9f4198b"))
    git(env, shared, "add", ".githooks/post-commit")
    git(env, shared, "commit", "-q", "-m", "a shared hook the repository tracks")
    git(env, shared, "config", "--local", "core.hooksPath", ".githooks")
    land(env, home)
    assert hook.read_bytes() == edited
    assert (shared / ".githooks" / "post-commit").read_bytes() == _blob("9f4198b")
    assert git(env, shared, "status", "--porcelain").stdout == ""


def test_a_landed_home_scans_once_per_template_change(tmp_path, env):
    """The scan of the repositories under $HOME runs once after a pull changed the template, not
    at every turn end: a copy installed after that scan waits for the next template change."""
    home, _rev = make_home(tmp_path, env)
    _ship_history(env, home)
    land(env, home)
    _a_pull_rewrites_the_template(home)
    first, _, first_hook = _product(env, tmp_path, "first", _blob("f0e813d"))
    land(env, home)
    assert first_hook.read_bytes() == (home / TEMPLATE).read_bytes()
    log = landing_log(home)
    _later, _, later_hook = _product(env, tmp_path, "later", _blob("f0e813d"))
    assert land(env, home) == ""
    assert landing_log(home) == log, "no scan at a turn end with the template unchanged"
    assert later_hook.read_bytes() == _blob("f0e813d")
    _a_pull_rewrites_the_template(home)
    land(env, home)
    assert later_hook.read_bytes() == (home / TEMPLATE).read_bytes()
