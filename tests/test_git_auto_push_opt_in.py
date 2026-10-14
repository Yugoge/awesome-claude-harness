"""GIT_AUTO_PUSH is the single opt-in switch for every automatic push.

Guards D1: nothing pushes outside /push unless GIT_AUTO_PUSH=1. Four code paths
push on their own, and before the opt-in change some of them pushed when the
variable was unset or even "0":

  1a  hooks/lib/checkpoint-core.sh: write_checkpoint writes the local
      refs/checkpoints/<branch> and then pushes it in a detached background
      worker (_checkpoint_rate_limited_push).
  1b  hooks/git-hooks/post-commit-auto-push, installed as a post-commit hook:
      background push of refs/backups/claude/<branch>/<sha12>.
  1c  the combined "Git LFS + Auto-Push" post-commit hook body that
      hooks/install-protection-all.sh writes from its heredoc (the text is
      extracted from the file; the installer itself is never run): background
      push of the branch.
  1e  hooks/git-fswatch.sh safe_push: synchronous push of refs/heads/<branch>
      (the watcher is never started; only its functions are loaded).

Each path runs with GIT_AUTO_PUSH unset, set but empty, "0", the near misses
"true", "yes", " 1" and "01", and "1". Every case has its own scratch
repository whose origin is a local bare repository, and every subprocess gets
an explicit environment (scratch HOME, state and log dirs, no system or global
git config). Every value except "1" must leave origin exactly as it was; "1"
must push. The near misses are what tell an exact guard from a loose one (a
non-empty, numeric or truthy-word test passes unset/"0"/"1" just as well).

All cases are triggered once, up front, by one module fixture. A "1" case then
polls its origin for up to POSITIVE_TIMEOUT seconds; any other case is only
concluded NEGATIVE_SETTLE seconds after its own trigger. Every case is judged
against its own origin, while the waits of different cases overlap.

Also pinned here: the shipped settings.json and settings.template.json set
GIT_AUTO_PUSH to "0"; hooks/checkpoint.sh (/checkpoint) tells the truth about
the push in both switch states; and hooks/session-git-init.sh (SessionStart),
which can create a GitHub repository, runs with a stub gh on PATH that logs its
arguments: it passes --push only when GIT_AUTO_PUSH is "1", and creates a
repository only when CLAUDE_AUTO_CREATE_REPO is one of its truthy values.
"""

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"
CHECKPOINT_LIB = HOOKS / "lib" / "checkpoint-core.sh"
STATE_DIR_LIB = HOOKS / "lib" / "harness_state_dir.sh"
POST_COMMIT_HOOK = HOOKS / "git-hooks" / "post-commit-auto-push"
INSTALLER = HOOKS / "install-protection-all.sh"
FSWATCH = HOOKS / "git-fswatch.sh"
CHECKPOINT_CMD = HOOKS / "checkpoint.sh"
SESSION_GIT_INIT = HOOKS / "session-git-init.sh"
SHIPPED_SETTINGS = ("settings.json", "settings.template.json")

# "unset" leaves the variable out of the environment; every other entry is the
# literal value. Only "1" may push.
CASES = ("unset", "", "0", "true", "yes", " 1", "01", "1")
_CASE_IDS = {"": "empty", " 1": "space-1"}
BRANCH = "master"
POSITIVE_TIMEOUT = 20.0
NEGATIVE_SETTLE = 5.0
POLL_INTERVAL = 0.25

# A clearly fake identity. It only ever lands in commit metadata, never in a
# blob, so the checkpoint push gate (which blocks blobs that look like an
# email address, a UUID or a token) is not tripped. Fixture content below is
# plain words for the same reason.
IDENTITY_NAME = "Push Opt In Test"
IDENTITY_EMAIL = "push-opt-in@example.invalid"
CHECKPOINT_NOTE = "plain words for a fresh checkpoint change\n"
SKIP_MARKER = "skipped"


def _case_id(case: str) -> str:
    """Test id and directory name: no empty or space-carrying names."""
    return _CASE_IDS.get(case, case)


@dataclass
class Run:
    path: str
    case: str
    env: dict
    repo: Path
    origin: Path
    origin_before: str
    expected_ref: str
    expected_sha: str
    returncode: int
    output: str
    triggered_at: float
    facts: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------


def _scratch_env(base: Path, case: str) -> dict:
    home = base / "home"
    checkpoint_logs = base / "checkpoint-logs"
    state = base / "state"
    tmp = base / "tmp"
    # ~/.claude/logs is where git-fswatch.sh logs; the checkpoint library
    # redirects plumbing stderr into CHECKPOINT_LOG_DIR, which must exist.
    for directory in (home / ".claude" / "logs", checkpoint_logs, state, tmp):
        directory.mkdir(parents=True, exist_ok=True)
    global_config = home / ".gitconfig"
    global_config.write_text("")
    env = {
        "PATH": os.environ.get("PATH") or os.defpath,
        "LANG": "C",
        "LC_ALL": "C",
        "HOME": str(home),
        "USER": "tester",
        "TMPDIR": str(tmp),
        "CHECKPOINT_LOG_DIR": str(checkpoint_logs),
        "CLAUDE_STATE_DIR": str(state),
        "CHECKPOINT_PUSH_MIN_INTERVAL": "0",
        "CLAUDE_BACKUP_LOG": str(base / "post-commit-auto-push.log"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": str(global_config),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": IDENTITY_NAME,
        "GIT_AUTHOR_EMAIL": IDENTITY_EMAIL,
        "GIT_COMMITTER_NAME": IDENTITY_NAME,
        "GIT_COMMITTER_EMAIL": IDENTITY_EMAIL,
    }
    if case == "unset":
        env.pop("GIT_AUTO_PUSH", None)
    else:
        env["GIT_AUTO_PUSH"] = case
    return env


def _run(args, env: dict, check: bool = True, cwd=None) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        [str(arg) for arg in args],
        env=env,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if check and proc.returncode != 0:
        raise AssertionError(
            f"{args!r} exited {proc.returncode}\n{proc.stdout}{proc.stderr}"
        )
    return proc


def _git(env: dict, *args, check: bool = True) -> str:
    return _run(["git", *args], env, check=check).stdout.strip()


def _origin_refs(env: dict, origin: Path) -> str:
    return _git(env, f"--git-dir={origin}", "for-each-ref",
                "--format=%(objectname) %(refname)")


def _origin_sha(run: Run) -> str:
    return _git(run.env, f"--git-dir={run.origin}", "rev-parse", "--verify",
                "-q", run.expected_ref, check=False)


def _new_repo(base: Path, env: dict):
    """A repo with one plain commit, already pushed to a local bare origin."""
    origin = base / "origin.git"
    repo = base / "repo"
    _git(env, "init", "-q", "--bare", origin)
    _git(env, "-c", f"init.defaultBranch={BRANCH}", "init", "-q", repo)
    _git(env, "-C", repo, "symbolic-ref", "HEAD", f"refs/heads/{BRANCH}")
    (repo / "README.md").write_text("plain words for a scratch repository\n")
    _git(env, "-C", repo, "add", "README.md")
    _git(env, "-C", repo, "commit", "-q", "-m", "initial plain commit")
    _git(env, "-C", repo, "remote", "add", "origin", origin)
    _git(env, "-C", repo, "push", "-q", "origin", BRANCH)
    return repo, origin


def _install_post_commit(repo: Path, text: str) -> None:
    hook = repo / ".git" / "hooks" / "post-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(text)
    hook.chmod(0o755)


def _combined_hook_body() -> str:
    """The heredoc text between the line ending in <<'EOF' and the line EOF."""
    lines = INSTALLER.read_text(encoding="utf-8").splitlines(keepends=True)
    bodies = []
    for i, line in enumerate(lines):
        if line.rstrip("\n").endswith("<<'EOF'"):
            end = next(j for j in range(i + 1, len(lines))
                       if lines[j].rstrip("\n") == "EOF")
            bodies.append("".join(lines[i + 1:end]))
    combined = [b for b in bodies if "Git LFS + Auto-Push" in b]
    assert len(combined) == 1, (
        f"expected one combined LFS + auto-push heredoc in {INSTALLER}, "
        f"found {len(combined)}")
    return combined[0]


def _fswatch_functions(base: Path) -> Path:
    """git-fswatch.sh minus its final `main "$@"` line, so sourcing it defines
    the functions without starting the watcher. Its sibling lib/ helper is
    copied next to it so its state paths resolve into CLAUDE_STATE_DIR."""
    lines = FSWATCH.read_text(encoding="utf-8").splitlines(keepends=True)
    while lines and not lines[-1].strip():
        lines.pop()
    assert lines and lines[-1].strip() == 'main "$@"', (
        f"final line of {FSWATCH} is no longer the call to main")
    hooks_dir = base / "fswatch-functions" / "hooks"
    (hooks_dir / "lib").mkdir(parents=True)
    shutil.copyfile(STATE_DIR_LIB, hooks_dir / "lib" / "harness_state_dir.sh")
    functions = hooks_dir / "git-fswatch-functions.sh"
    functions.write_text("".join(lines[:-1]))
    return functions


# ---------------------------------------------------------------------------
# triggers: one per push path, each on a fresh repo
# ---------------------------------------------------------------------------


def _trigger_checkpoint(base: Path, env: dict, case: str) -> Run:
    repo, origin = _new_repo(base, env)
    head = _git(env, "-C", repo, "rev-parse", "HEAD")
    origin_before = _origin_refs(env, origin)
    # A fresh change, so the snapshot differs from HEAD and a checkpoint is
    # actually written (an unchanged tree writes and pushes nothing).
    (repo / "notes.txt").write_text(CHECKPOINT_NOTE)
    script = ('source "$1" || exit 90; '
              'write_checkpoint "$2" "push opt-in test" "push opt-in checkpoint"')
    proc = _run(["bash", "-c", script, "bash", CHECKPOINT_LIB, repo], env,
                check=False)
    triggered_at = time.monotonic()
    ref = f"refs/checkpoints/{BRANCH}"
    local_sha = _git(env, "-C", repo, "rev-parse", "--verify", "-q", ref,
                     check=False)
    return Run("checkpoint", case, env, repo, origin, origin_before, ref,
               local_sha, proc.returncode, proc.stdout + proc.stderr,
               triggered_at, {"head": head})


def _trigger_commit_hook(path: str, hook_text: str):
    def trigger(base: Path, env: dict, case: str) -> Run:
        repo, origin = _new_repo(base, env)
        _install_post_commit(repo, hook_text)
        (repo / "change.txt").write_text("plain words for a fresh commit\n")
        _git(env, "-C", repo, "add", "change.txt")
        origin_before = _origin_refs(env, origin)
        proc = _run(["git", "-C", repo, "commit", "-q", "-m",
                     "plain commit under test"], env, check=False)
        triggered_at = time.monotonic()
        head = _git(env, "-C", repo, "rev-parse", "HEAD")
        if path == "post_commit":
            ref = f"refs/backups/claude/{BRANCH}/{head[:12]}"
        else:
            ref = f"refs/heads/{BRANCH}"
        return Run(path, case, env, repo, origin, origin_before, ref, head,
                   proc.returncode, proc.stdout + proc.stderr, triggered_at)
    return trigger


def _trigger_fswatch(base: Path, env: dict, case: str) -> Run:
    functions = _fswatch_functions(base)
    repo, origin = _new_repo(base, env)
    _git(env, "-C", repo, "fetch", "-q", "origin")
    (repo / "ahead.txt").write_text("plain words one commit ahead of origin\n")
    _git(env, "-C", repo, "add", "ahead.txt")
    _git(env, "-C", repo, "commit", "-q", "-m", "one plain commit ahead")
    ahead = _git(env, "-C", repo, "rev-list", "--count",
                 f"origin/{BRANCH}..HEAD")
    head = _git(env, "-C", repo, "rev-parse", "HEAD")
    origin_before = _origin_refs(env, origin)
    # Sourcing installs an EXIT trap that exits 0 and writes a state file:
    # clear it before calling safe_push so the exit status is safe_push's own.
    script = ('source "$1" "$2"; loaded=$?; trap - EXIT INT TERM; '
              '[ "$loaded" -eq 0 ] || exit 90; safe_push')
    proc = _run(["bash", "-c", script, "bash", functions, repo], env,
                check=False)
    triggered_at = time.monotonic()
    log_file = Path(env["HOME"]) / ".claude" / "logs" / f"git-fswatch-{repo.name}.log"
    return Run("fswatch", case, env, repo, origin, origin_before,
               f"refs/heads/{BRANCH}", head, proc.returncode,
               proc.stdout + proc.stderr, triggered_at,
               {"ahead": ahead, "log_file": str(log_file)})


@pytest.fixture(scope="module")
def runs(tmp_path_factory) -> dict:
    triggers = {
        "checkpoint": _trigger_checkpoint,
        "post_commit": _trigger_commit_hook(
            "post_commit", POST_COMMIT_HOOK.read_text(encoding="utf-8")),
        "combined_hook": _trigger_commit_hook(
            "combined_hook", _combined_hook_body()),
        "fswatch": _trigger_fswatch,
    }
    base = tmp_path_factory.mktemp("git_auto_push")
    triggered = {}
    for path, trigger in triggers.items():
        for case in CASES:
            case_dir = base / f"{path}-{_case_id(case)}"
            case_dir.mkdir()
            triggered[(path, case)] = trigger(case_dir, _scratch_env(case_dir, case), case)
    return triggered


def _assert_push_follows_opt_in(run: Run) -> None:
    label = f"{run.path} with GIT_AUTO_PUSH {_case_id(run.case)}"
    if run.case == "1":
        deadline = time.monotonic() + POSITIVE_TIMEOUT
        got = _origin_sha(run)
        while got != run.expected_sha and time.monotonic() < deadline:
            time.sleep(POLL_INTERVAL)
            got = _origin_sha(run)
        assert got == run.expected_sha, (
            f"{label}: origin {run.expected_ref} is {got or 'absent'} after "
            f"{POSITIVE_TIMEOUT:.0f}s, expected {run.expected_sha}\n{run.output}")
        return
    remaining = run.triggered_at + NEGATIVE_SETTLE - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)
    after = _origin_refs(run.env, run.origin)
    assert after == run.origin_before, (
        f"{label}: origin changed without opt-in "
        f"(watched {run.expected_ref} for {run.expected_sha})\n"
        f"before:\n{run.origin_before}\nafter:\n{after}")


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_checkpoint_writes_locally_and_pushes_only_on_opt_in(runs, case):
    run = runs[("checkpoint", case)]
    assert run.returncode == 0, run.output
    # The local checkpoint is written whatever the push setting.
    assert run.expected_sha, f"no local {run.expected_ref} was written\n{run.output}"
    assert run.expected_sha != run.facts["head"]
    note = _git(run.env, "-C", run.repo, "show", f"{run.expected_sha}:notes.txt")
    assert note == CHECKPOINT_NOTE.strip()
    _assert_push_follows_opt_in(run)


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_post_commit_backup_push_only_on_opt_in(runs, case):
    run = runs[("post_commit", case)]
    assert run.returncode == 0, run.output
    _assert_push_follows_opt_in(run)


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_combined_lfs_hook_push_only_on_opt_in(runs, case):
    run = runs[("combined_hook", case)]
    assert run.returncode == 0, run.output
    _assert_push_follows_opt_in(run)


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_fswatch_safe_push_only_on_opt_in(runs, case):
    run = runs[("fswatch", case)]
    assert run.facts["ahead"] == "1", "fixture must be one commit ahead of origin"
    assert run.returncode == 0, run.output
    _assert_push_follows_opt_in(run)
    log_file = Path(run.facts["log_file"])
    log = log_file.read_text(encoding="utf-8", errors="replace") if log_file.exists() else ""
    skipped = [line for line in log.splitlines() if SKIP_MARKER in line]
    if case == "1":
        assert not skipped, log
    else:
        assert len(skipped) == 1, f"expected one '{SKIP_MARKER}' line\n{log}"


# ---------------------------------------------------------------------------
# shipped settings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", SHIPPED_SETTINGS)
def test_shipped_settings_keep_auto_push_off(name):
    env = json.loads((ROOT / name).read_text(encoding="utf-8")).get("env", {})
    assert env.get("GIT_AUTO_PUSH") == "0", (
        f"{name} ships GIT_AUTO_PUSH={env.get('GIT_AUTO_PUSH')!r}, expected '0'")


# ---------------------------------------------------------------------------
# /checkpoint (hooks/checkpoint.sh): the closing message matches the switch
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_checkpoint_command_message_matches_the_switch(tmp_path, case):
    env = _scratch_env(tmp_path, case)
    # checkpoint.sh sources $HOME/.claude/hooks/lib/checkpoint-core.sh.
    lib = Path(env["HOME"]) / ".claude" / "hooks" / "lib"
    lib.mkdir(parents=True)
    for source in (CHECKPOINT_LIB, STATE_DIR_LIB):
        shutil.copyfile(source, lib / source.name)
    repo, _origin = _new_repo(tmp_path, env)
    (repo / "notes.txt").write_text(CHECKPOINT_NOTE)
    proc = _run(["bash", CHECKPOINT_CMD], env, cwd=repo)
    out = proc.stdout + proc.stderr
    ref = f"refs/checkpoints/{BRANCH}"
    assert f"on {ref}" in out, out
    pushing = f"Background push of {ref}"
    local = f"{ref} is local only"
    if case == "1":
        assert pushing in out and local not in out, out
    else:
        assert local in out and "GIT_AUTO_PUSH=1" in out and pushing not in out, out


# ---------------------------------------------------------------------------
# hooks/session-git-init.sh: the remote step, with a stub gh on PATH
# ---------------------------------------------------------------------------

# The stub logs one line per call, arguments NUL-separated, and succeeds, so
# `gh auth status` passes and nothing ever reaches GitHub.
GH_STUB = """#!/bin/bash
printf '%s\\0' "$@" >> "$GH_STUB_LOG"
printf '\\n' >> "$GH_STUB_LOG"
if [ "$1" = "api" ]; then echo stub-user; fi
exit 0
"""
PROJECT_NAME = "proj"
CREATE_VALUES = ("1", "true", "TRUE", "yes", "YES")
NO_CREATE_VALUES = ("0", "no", "FALSE", "false")
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _run_session_git_init(base: Path, push_case: str, create=None):
    """Run the hook in a fresh non-git directory; return (output, gh calls
    that create a repository)."""
    env = _scratch_env(base, push_case)
    stub_dir = base / "stub-bin"
    stub_dir.mkdir()
    stub = stub_dir / "gh"
    stub.write_text(GH_STUB)
    stub.chmod(0o755)
    log = base / "gh-calls.log"
    env["PATH"] = f"{stub_dir}{os.pathsep}{env['PATH']}"
    env["GH_STUB_LOG"] = str(log)
    env["CLAUDE_SESSION_GIT_INIT"] = "1"
    if create is not None:
        env["CLAUDE_AUTO_CREATE_REPO"] = create
    project = base / PROJECT_NAME
    project.mkdir()
    proc = _run(["bash", SESSION_GIT_INIT], env, check=False, cwd=project)
    output = ANSI.sub("", proc.stdout + proc.stderr)
    assert proc.returncode == 0, output
    assert _git(env, "-C", project, "rev-parse", "--verify", "-q", "HEAD"), (
        f"no initial commit was made\n{output}")
    lines = log.read_text().split("\n") if log.exists() else []
    calls = [line.split("\0")[:-1] for line in lines if line]
    creates = [call for call in calls if call[:2] == ["repo", "create"]]
    return output, creates


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_session_git_init_creates_repo_and_pushes_only_on_opt_in(tmp_path, case):
    output, creates = _run_session_git_init(tmp_path, case, create="true")
    assert len(creates) == 1, f"expected one gh repo create call: {creates}\n{output}"
    args = creates[0]
    assert args[:3] == ["repo", "create", PROJECT_NAME], args
    assert ("--push" in args) == (case == "1"), (
        f"GIT_AUTO_PUSH {_case_id(case)}: gh called with {args}")
    if case != "1":
        assert "not pushed" in output and "/push" in output, output


@pytest.mark.parametrize("create", CREATE_VALUES)
def test_session_git_init_creates_for_each_truthy_value(tmp_path, create):
    _output, creates = _run_session_git_init(tmp_path, "unset", create=create)
    assert len(creates) == 1 and "--push" not in creates[0], creates


@pytest.mark.parametrize("create", NO_CREATE_VALUES)
def test_session_git_init_never_creates_for_a_falsy_value(tmp_path, create):
    output, creates = _run_session_git_init(tmp_path, "1", create=create)
    assert creates == [], f"CLAUDE_AUTO_CREATE_REPO={create!r} created: {creates}"
    assert "Auto-create disabled" in output, output


@pytest.mark.parametrize("case", ("unset", "1"), ids=_case_id)
@pytest.mark.parametrize("create", (None, "ask"), ids=("create-unset", "ask"))
def test_session_git_init_ask_prints_the_command_it_would_run(tmp_path, create, case):
    output, creates = _run_session_git_init(tmp_path, case, create=create)
    assert creates == [], creates
    expected = (f'Run manually: gh repo create "{PROJECT_NAME}" --private '
                f'--source=. --remote=origin' + (" --push" if case == "1" else ""))
    hint = [line.strip() for line in output.splitlines() if "Run manually:" in line]
    assert len(hint) == 1 and hint[0].endswith(expected), output
    assert ("/push" in output) == (case != "1"), output
