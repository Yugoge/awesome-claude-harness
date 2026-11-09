"""scripts/steps/push-snapshot.py: /push Steps 0 and 2 (the push remote and the pre-push snapshot).

Every test runs the real script in a temporary git repository (no network, nothing read from the runner's
home). OLD_SNAPSHOT is the pair of shell blocks the prompt ran before the script existed (Step 0's
remote resolution and Step 2's capture, minus the openssl nonce): the script's values must equal what
that shell computes for the same repository, so the move changed no value.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "steps" / "push-snapshot.py"
COMMAND = REPO / "commands" / "push.md"
KEYS = ["BRANCH", "PRE_HEAD", "RESOLVED_REMOTE", "DEFAULT_REMOTE", "REMOTE_URL", "REQUEST_ID", "SESSION_ID",
        "REPO_ROOT", "REPO_HASH"]

# Step 0's and Step 2's shell blocks of commands/push.md at d64fa96, openssl line left out.
OLD_SNAPSHOT = r"""
if git remote get-url fork >/dev/null 2>&1; then
    RESOLVED_REMOTE="fork"
else
    RESOLVED_REMOTE="origin"
fi
[ -z "$TYPED_REMOTE" ] || RESOLVED_REMOTE="$TYPED_REMOTE"
PRE_HEAD=$(git rev-parse HEAD)
BRANCH=$(git rev-parse --abbrev-ref HEAD)
REMOTE_URL=$(git remote get-url "${RESOLVED_REMOTE}" 2>/dev/null || echo "unknown")
REPO_ROOT=$(realpath "$(git rev-parse --show-toplevel)")
REPO_HASH=$(printf '%s' "${REPO_ROOT}" | sha256sum | cut -c1-16)
SESSION_ID="${CLAUDE_SESSION_ID:-${CLAUDE_CODE_SESSION_ID:-}}"
for v in BRANCH PRE_HEAD RESOLVED_REMOTE REMOTE_URL SESSION_ID REPO_ROOT REPO_HASH; do
    printf '%s=%s\n' "$v" "${!v}"
done
"""


def _env(**extra: str) -> dict:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE", "GIT_")) and k not in ("TYPED_REMOTE",)}
    env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1", PYTHONDONTWRITEBYTECODE="1",
               GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.com",
               GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.com")
    env.update(extra)
    return env


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=_env())
    assert done.returncode == 0, (args, done.stderr)
    return done.stdout.strip()


def make_repo(path: Path, branch: str = "main", remotes: dict | None = None) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q")
    git(path, "symbolic-ref", "HEAD", f"refs/heads/{branch}")
    (path / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(path, "add", "seed.txt")
    git(path, "commit", "-q", "-m", "seed")
    for name, url in (remotes or {}).items():
        git(path, "remote", "add", name, url)
    return path.resolve()


def snapshot(cwd: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True,
                          env=env or _env())


def facts(cwd: Path, *args: str, env: dict | None = None) -> dict:
    done = snapshot(cwd, *args, env=env)
    assert done.returncode == 0, done.stdout + done.stderr
    lines = done.stdout.splitlines()
    assert [line.split("=", 1)[0] for line in lines] == KEYS, done.stdout
    return dict(line.split("=", 1) for line in lines)


def old_facts(cwd: Path, typed: str = "", env: dict | None = None) -> dict:
    done = subprocess.run(["bash", "-c", OLD_SNAPSHOT], cwd=cwd, capture_output=True, text=True,
                          env=dict(env or _env(), TYPED_REMOTE=typed))
    assert done.returncode == 0, done.stderr
    return dict(line.split("=", 1) for line in done.stdout.splitlines())


def test_a_repository_with_only_origin(tmp_path):
    repo = make_repo(tmp_path / "r", remotes={"origin": "https://example.com/o.git"})
    got = facts(repo)
    assert got["BRANCH"] == "main" and got["PRE_HEAD"] == git(repo, "rev-parse", "HEAD")
    assert (got["RESOLVED_REMOTE"], got["DEFAULT_REMOTE"], got["REMOTE_URL"]) == (
        "origin", "origin", "https://example.com/o.git")
    assert got["REPO_ROOT"] == str(repo)
    assert got["REPO_HASH"] == hashlib.sha256(str(repo).encode()).hexdigest()[:16]


def test_a_fork_remote_is_preferred_to_origin(tmp_path):
    repo = make_repo(tmp_path / "r", remotes={"origin": "https://example.com/o.git", "fork": "https://example.com/f.git"})
    got = facts(repo)
    assert (got["RESOLVED_REMOTE"], got["DEFAULT_REMOTE"], got["REMOTE_URL"]) == (
        "fork", "fork", "https://example.com/f.git")


def test_a_typed_remote_overrides_the_fork_but_not_the_default(tmp_path):
    repo = make_repo(tmp_path / "r", remotes={"origin": "https://example.com/o.git", "fork": "https://example.com/f.git"})
    got = facts(repo, "--remote", "origin")
    assert (got["RESOLVED_REMOTE"], got["DEFAULT_REMOTE"], got["REMOTE_URL"]) == (
        "origin", "fork", "https://example.com/o.git")


def test_a_typed_remote_that_does_not_exist_is_reported_not_refused(tmp_path):
    repo = make_repo(tmp_path / "r", remotes={"origin": "https://example.com/o.git"})
    done = snapshot(repo, "--remote", "upstrem")
    assert done.returncode == 0, done.stderr  # hooks/push.sh refuses it later: exit 1, "remote 'upstrem' not found"
    got = dict(line.split("=", 1) for line in done.stdout.splitlines())
    assert (got["RESOLVED_REMOTE"], got["DEFAULT_REMOTE"], got["REMOTE_URL"]) == ("upstrem", "origin", "unknown")


def test_a_repository_without_remotes_resolves_origin_with_an_unknown_url(tmp_path):
    repo = make_repo(tmp_path / "r")
    got = facts(repo)
    assert (got["RESOLVED_REMOTE"], got["DEFAULT_REMOTE"], got["REMOTE_URL"]) == ("origin", "origin", "unknown")


def test_an_empty_remote_argument_is_no_remote(tmp_path):
    repo = make_repo(tmp_path / "r", remotes={"fork": "https://example.com/f.git"})
    assert facts(repo, "--remote", "")["RESOLVED_REMOTE"] == "fork"


def test_a_detached_head_prints_head_as_the_branch(tmp_path):
    repo = make_repo(tmp_path / "r", remotes={"origin": "https://example.com/o.git"})
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "--detach")
    got = facts(repo)
    assert got["BRANCH"] == "HEAD" and got["PRE_HEAD"] == head


def test_a_branch_name_with_a_slash_is_kept(tmp_path):
    repo = make_repo(tmp_path / "r", branch="feature/x")
    assert facts(repo)["BRANCH"] == "feature/x"


def test_the_session_id_is_claude_session_id_else_claude_code_session_id_else_empty(tmp_path):
    repo = make_repo(tmp_path / "r")
    assert facts(repo)["SESSION_ID"] == ""
    assert facts(repo, env=_env(CLAUDE_CODE_SESSION_ID="code-sid"))["SESSION_ID"] == "code-sid"
    assert facts(repo, env=_env(CLAUDE_SESSION_ID="plain-sid", CLAUDE_CODE_SESSION_ID="code-sid"))["SESSION_ID"] == "plain-sid"
    # `${A:-${B:-}}`: an empty A falls through to B
    assert facts(repo, env=_env(CLAUDE_SESSION_ID="", CLAUDE_CODE_SESSION_ID="code-sid"))["SESSION_ID"] == "code-sid"


def test_the_request_id_is_a_fresh_32_hex_nonce_each_call(tmp_path):
    repo = make_repo(tmp_path / "r")
    ids = {facts(repo)["REQUEST_ID"] for _ in range(3)}
    assert len(ids) == 3 and all(re.fullmatch(r"[0-9a-f]{32}", i) for i in ids)


def test_the_repo_root_is_the_real_top_level_from_a_subdirectory_or_a_symlink(tmp_path):
    repo = make_repo(tmp_path / "real")
    (repo / "sub" / "dir").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(repo, target_is_directory=True)
    for cwd in (repo / "sub" / "dir", link, link / "sub"):
        got = facts(cwd)
        assert got["REPO_ROOT"] == str(repo)
        assert got["REPO_HASH"] == hashlib.sha256(str(repo).encode()).hexdigest()[:16]


@pytest.mark.parametrize("typed", ["", "origin", "upstrem"])
@pytest.mark.parametrize("shape", ["origin", "fork", "none", "detached", "slash", "link"])
def test_every_value_equals_what_the_old_shell_blocks_computed(tmp_path, shape, typed):
    remotes = {"origin": "https://example.com/o.git"}
    if shape == "fork":
        remotes["fork"] = "git@example.com:me/f.git"
    if shape == "none":
        remotes = {}
    repo = make_repo(tmp_path / "real", branch="feature/y" if shape == "slash" else "main", remotes=remotes)
    cwd = repo
    if shape == "detached":
        git(repo, "checkout", "-q", "--detach")
    if shape == "link":
        cwd = tmp_path / "link"
        cwd.symlink_to(repo, target_is_directory=True)
    env = _env(CLAUDE_CODE_SESSION_ID="sid-1")
    new = facts(cwd, *(["--remote", typed] if typed else []), env=env)
    old = old_facts(cwd, typed, env=env)
    assert {k: new[k] for k in old if k != "DEFAULT_REMOTE"} == {k: v for k, v in old.items() if k != "DEFAULT_REMOTE"}


def test_the_repo_hash_is_the_key_hooks_and_the_executor_use(tmp_path):
    """hooks/push.sh and scripts/execute-push.py key the state directories by sha256(realpath(root))[:16]."""
    repo = make_repo(tmp_path / "r")
    key = hashlib.sha256(os.path.realpath(str(repo)).encode()).hexdigest()[:16]
    assert facts(repo)["REPO_HASH"] == key
    assert "hashlib.sha256(os.path.realpath(" in (REPO / "hooks" / "push.sh").read_text(encoding="utf-8")


def test_outside_a_work_tree_it_prints_nothing_and_exits_1(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    done = snapshot(plain)
    assert (done.returncode, done.stdout) == (1, "") and "not inside a git work tree" in done.stderr


def test_a_bare_repository_is_not_a_work_tree(tmp_path):
    bare = tmp_path / "bare.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, env=_env())
    done = snapshot(bare)
    assert (done.returncode, done.stdout) == (1, "")


def test_an_unknown_argument_is_a_usage_error(tmp_path):
    repo = make_repo(tmp_path / "r")
    done = snapshot(repo, "--auto")
    assert done.returncode == 2 and done.stdout == ""


# ------------------------------------------------------------------ the prompt and the script agree
def _step(name: str) -> str:
    text = COMMAND.read_text(encoding="utf-8")
    m = re.search(r"^\*\*%s\b[^\n]*\*\*$" % re.escape(name), text, re.M)
    assert m, f"commands/push.md has no {name}"
    nxt = re.search(r"^\*\*Step \d+\b[^\n]*\*\*$|^## ", text[m.end():], re.M)
    return text[m.start():m.end() + (nxt.start() if nxt else len(text))]


def test_step_2_names_every_key_the_script_prints_and_runs_it_through_both_forms():
    step = _step("Step 2")
    for key in KEYS:
        assert f"`{key}`" in step, key
    assert step.count("scripts/steps/push-snapshot.py") == 2 and "--remote <remote>" in step


def test_the_placeholders_of_step_3_and_step_5_are_keys_the_script_prints():
    used = set()
    for name in ("Step 3", "Step 5"):
        for block in re.findall(r"```[^\n]*\n(.*?)```", _step(name), re.S):
            used |= {p for p in re.findall(r"<([A-Z][A-Z_]*)>", block) if p != "HARNESS_ROOT"}
    # Step 3 names the analyst's input REMOTE_NAME after RESOLVED_REMOTE; every placeholder is a printed key
    assert used and used <= set(KEYS), sorted(used - set(KEYS))
    assert {"BRANCH", "PRE_HEAD", "RESOLVED_REMOTE", "REMOTE_URL", "REQUEST_ID", "SESSION_ID", "REPO_HASH",
            "REPO_ROOT"} <= used


def test_every_bash_call_in_push_md_is_allowed_by_the_bash_safety_hook_and_the_analyzer():
    hooks_tests = REPO / "hooks" / "tests"
    sys.path[:0] = [str(REPO / "hooks" / "lib"), str(hooks_tests)]
    try:
        import bash_execution_boundary as eb
        from pol_replay_harness import run_hook_command
    finally:
        del sys.path[:2]
    text = COMMAND.read_text(encoding="utf-8")
    calls = []
    for block in re.findall(r"```bash\n(.*?)```", text, re.S):
        body = "\n".join(line for line in block.splitlines() if not line.lstrip().startswith("#"))
        # one command per form: split where a new `python3` starts
        calls += [c.strip() for c in re.split(r"\n\s*\n", body) if c.strip()]
    assert len(calls) == 4, calls  # two snapshot forms, two execute-push forms
    fill = {"<HARNESS_ROOT>": str(REPO), "<remote>": "upstrem", "<REPO_HASH>": "0123456789abcdef",
            "<BRANCH>": "feature/x", "<RESOLVED_REMOTE>": "origin", "<REQUEST_ID>": "a" * 32,
            "<REPO_ROOT>": "/work/repo"}
    for call in calls:
        command = re.sub("|".join(map(re.escape, fill)), lambda m: fill[m.group(0)], call)
        verdict = eb.analyze(command)
        assert verdict["allowed"] is True, (command, verdict.get("verdict"), verdict.get("reason"))
        code, _out, err = run_hook_command(command)
        assert code == 0, (command, err)
