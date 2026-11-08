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
                the repository itself, so its harness.autoPush comes from a git init template.

Each path runs every row of SWITCHES: global on and repository false (no push), global off or
unset and repository true (push), the key unset (the global switch decides), a repository value
git cannot read as a boolean (no push), and a harness.autoPush in the global git config only (not
read: the global switch stays GIT_AUTO_PUSH). /checkpoint's closing message follows the same
switch. Init (scripts/bootstrap) and the landing (scripts/install/land) set false in a harness
home that lacks the key and keep a value already set.

Every case has its own scratch HOME and global git config (no system config) and its own
repositories; every origin is a local bare repository, so nothing reaches a network or a real home.
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest

from tests.test_bootstrap_init import Home
from tests.test_git_auto_push_opt_in import (BRANCH, CHECKPOINT_CMD, CHECKPOINT_LIB,
                                             CHECKPOINT_NOTE, NEGATIVE_SETTLE, POLL_INTERVAL,
                                             POSITIVE_TIMEOUT, PROJECT_NAME, SKIP_MARKER, Run,
                                             _fswatch_functions, _git, _new_repo, _origin_refs,
                                             _run, _run_session_git_init, _scratch_env)
from tests.test_landing import env  # noqa: F401  (the landing tests' scratch-home fixture)
from tests.test_landing import assert_landed, git, land, landing_log, make_home


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


@pytest.fixture(scope="module")
def checkpoint_runs(tmp_path_factory) -> dict:
    """Every checkpoint case triggered up front, so their push waits overlap."""
    base = tmp_path_factory.mktemp("per_repo_checkpoint")
    runs = {}
    for switch in SWITCHES:
        (base / switch.id).mkdir()
        runs[switch.id] = _trigger_checkpoint(base / switch.id, switch)
    return runs


@pytest.mark.parametrize("switch", SWITCHES, ids=IDS)
def test_checkpoint_push_follows_the_repository_switch(checkpoint_runs, switch):
    run = checkpoint_runs[switch.id]
    assert run.returncode == 0, run.output
    assert run.expected_sha, f"no local {run.expected_ref} was written\n{run.output}"
    _judge(run, switch.pushes)


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
