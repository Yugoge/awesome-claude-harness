"""scripts/steps/merge-snapshot.py: /merge Step 1's snapshot and Step 4's tip re-read, run for real
against temporary git repositories (no network, nothing read from the owner's home)."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "steps" / "merge-snapshot.py"
SNAPSHOT_KEYS = ["RESOLVED_REF", "SOURCE_TIP", "DEFAULT_BRANCH", "DEFAULT_TIP", "REQUEST_ID", "SESSION_ID",
                 "REPO_HASH", "REPO_ROOT"]
SESSION = "session-under-test"

# The block commands/merge.md ran at Step 1 before the step moved into the script, with the harness root
# filled in and the random request id left out (a nonce has no value to compare).
OLD_STEP1_BLOCK = """\
SOURCE_TIP=$(git rev-parse --verify --quiet "${RESOLVED_REF}^{commit}" || echo "MISSING")
DEFAULT_BRANCH=$(bash "%(harness)s/scripts/derive-default-branch.sh")
DEFAULT_TIP=$(git rev-parse --verify --quiet "refs/heads/${DEFAULT_BRANCH}^{commit}" || echo "MISSING")
REPO_ROOT=$(realpath "$(git rev-parse --show-toplevel)")
REPO_HASH=$(printf '%%s' "$REPO_ROOT" | sha256sum | cut -c1-16)
SESSION_ID="${CLAUDE_CODE_SESSION_ID}"
"""
OLD_STEP4_BLOCK = """\
CURRENT_SOURCE_TIP=$(git rev-parse --verify --quiet "${RESOLVED_REF}^{commit}")
CURRENT_DEFAULT_TIP=$(git rev-parse --verify --quiet "refs/heads/${DEFAULT_BRANCH}^{commit}")
"""


def _env(**extra: str) -> dict:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE", "GIT_")) and k not in ("DEFAULT_BRANCH_FALLBACK", "RESOLVED_REF")}
    env.update(HOME="/nonexistent-home", CLAUDE_CODE_SESSION_ID=SESSION, PYTHONDONTWRITEBYTECODE="1",
               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null", GIT_AUTHOR_NAME="t",
               GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    env.update(extra)
    return env


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True, env=_env())
    return done.stdout.strip()


def commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name + "\n", encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", name)
    return git(repo, "rev-parse", "HEAD")


def make_repo(tmp_path: Path, name: str = "work") -> Path:
    """main with two commits; feature one commit ahead of main."""
    repo = tmp_path / name
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, "a.txt")
    commit(repo, "b.txt")
    git(repo, "checkout", "-q", "-b", "feature")
    commit(repo, "c.txt")
    git(repo, "checkout", "-q", "main")
    return repo


def run(repo: Path, *args: str, session: str | None = SESSION, **env: str):
    """The script's stdout as a dict (every line must be KEY=value), plus the finished process."""
    environ = _env(**env)
    if session is None:
        environ.pop("CLAUDE_CODE_SESSION_ID")
    else:
        environ["CLAUDE_CODE_SESSION_ID"] = session
    proc = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=repo, env=environ, text=True,
                          capture_output=True, stdin=subprocess.DEVNULL)
    facts: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        key, sep, value = line.partition("=")
        assert sep and re.fullmatch(r"[A-Z_]+", key), f"stdout carries a line that is not KEY=value: {line!r}"
        facts[key] = value
    return facts, proc


def snapshot(repo: Path, ref: str, **kw):
    return run(repo, "snapshot", ref, **kw)


# ------------------------------------------------------------------ the snapshot
def test_snapshot_prints_the_eight_dispatch_lines_in_order(tmp_path):
    repo = make_repo(tmp_path)
    facts, proc = snapshot(repo, "feature")
    assert proc.returncode == 0 and proc.stderr == ""
    assert list(facts) == SNAPSHOT_KEYS
    assert proc.stdout.count("\n") == len(SNAPSHOT_KEYS)
    assert facts["RESOLVED_REF"] == "feature"
    assert facts["SOURCE_TIP"] == git(repo, "rev-parse", "feature")
    assert facts["DEFAULT_BRANCH"] == "master"  # no remote names one: the script's fallback
    assert facts["SESSION_ID"] == SESSION
    assert facts["REPO_ROOT"] == os.path.realpath(repo)
    assert facts["REPO_HASH"] == hashlib.sha256(facts["REPO_ROOT"].encode()).hexdigest()[:16]


def test_request_id_is_32_hex_characters_and_new_on_every_call(tmp_path):
    repo = make_repo(tmp_path)
    ids = [snapshot(repo, "feature")[0]["REQUEST_ID"] for _ in range(3)]
    assert all(re.fullmatch(r"[0-9a-f]{32}", i) for i in ids)
    assert len(set(ids)) == 3


@pytest.mark.parametrize("shape", ["branch", "remote-tracking", "full-remote-tracking", "lightweight-tag",
                                   "annotated-tag", "bare-hash", "head-relative"])
def test_every_ref_shape_that_names_a_commit_resolves(tmp_path, shape):
    repo = make_repo(tmp_path)
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(repo), str(clone))
    tip = git(clone, "rev-parse", "origin/feature")
    git(clone, "tag", "light", "origin/feature")
    git(clone, "tag", "-a", "-m", "annotated", "annotated", "origin/feature")
    ref = {"branch": "main", "remote-tracking": "origin/feature", "full-remote-tracking": "refs/remotes/origin/feature",
           "lightweight-tag": "light", "annotated-tag": "annotated", "bare-hash": tip, "head-relative": "HEAD~1"}[shape]
    expected = {"branch": git(clone, "rev-parse", "main"), "head-relative": git(clone, "rev-parse", "HEAD~1")}.get(shape, tip)
    facts, proc = snapshot(clone, ref)
    assert proc.returncode == 0
    assert facts["SOURCE_TIP"] == expected
    if shape == "annotated-tag":  # peeled: the commit, not the tag object
        assert facts["SOURCE_TIP"] != git(clone, "rev-parse", "annotated")


def test_a_ref_that_does_not_resolve_is_missing_and_the_rest_is_still_printed(tmp_path):
    repo = make_repo(tmp_path)
    facts, proc = snapshot(repo, "no-such-ref")
    assert proc.returncode == 0 and proc.stderr == ""
    assert list(facts) == SNAPSHOT_KEYS
    assert facts["SOURCE_TIP"] == "MISSING"
    assert (facts["DEFAULT_BRANCH"], facts["DEFAULT_TIP"]) == ("master", "MISSING")


def test_a_name_that_is_no_commit_is_missing(tmp_path):
    repo = make_repo(tmp_path)
    tree = git(repo, "rev-parse", "main^{tree}")
    blob = git(repo, "rev-parse", "main:a.txt")
    assert snapshot(repo, tree)[0]["SOURCE_TIP"] == "MISSING"
    assert snapshot(repo, blob)[0]["SOURCE_TIP"] == "MISSING"
    assert snapshot(repo, "")[0]["SOURCE_TIP"] == "MISSING"


def test_a_ref_that_starts_with_a_dash_is_looked_up_like_any_name(tmp_path):
    repo = make_repo(tmp_path)
    for ref in ("--help", "-x", "--"):
        facts, proc = snapshot(repo, ref)
        assert proc.returncode == 0, ref
        assert facts["RESOLVED_REF"] == ref and facts["SOURCE_TIP"] == "MISSING"


def test_a_ref_with_shell_characters_is_data_not_code(tmp_path):
    repo = make_repo(tmp_path)
    facts, proc = snapshot(repo, "feature; touch pwned $(touch pwned2)")
    assert proc.returncode == 0 and facts["SOURCE_TIP"] == "MISSING"
    assert not (repo / "pwned").exists() and not (repo / "pwned2").exists()


# ------------------------------------------------------------------ the default branch
def test_the_default_branch_is_the_fallback_when_nothing_names_one(tmp_path):
    repo = make_repo(tmp_path)  # no remote: derive-default-branch.sh falls back to "master"
    facts, _ = snapshot(repo, "feature")
    assert facts["DEFAULT_BRANCH"] == "master"
    assert facts["DEFAULT_TIP"] == "MISSING"  # the repository has main, not master
    assert facts["SOURCE_TIP"] == git(repo, "rev-parse", "feature")


def test_the_fallback_variable_names_the_default_branch(tmp_path):
    repo = make_repo(tmp_path)
    facts, _ = snapshot(repo, "feature", DEFAULT_BRANCH_FALLBACK="main")
    assert facts["DEFAULT_BRANCH"] == "main"
    assert facts["DEFAULT_TIP"] == git(repo, "rev-parse", "main")


def test_the_default_branch_is_the_one_origin_head_names(tmp_path):
    origin = make_repo(tmp_path, "origin-src")
    git(origin, "branch", "trunk", "main")
    git(origin, "symbolic-ref", "HEAD", "refs/heads/trunk")
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(origin), str(clone))
    facts, _ = snapshot(clone, "origin/feature")
    assert facts["DEFAULT_BRANCH"] == "trunk"
    assert facts["DEFAULT_TIP"] == git(clone, "rev-parse", "refs/heads/trunk")
    assert facts["SOURCE_TIP"] == git(clone, "rev-parse", "origin/feature")


def test_a_default_branch_with_no_local_ref_is_missing(tmp_path):
    origin = make_repo(tmp_path, "origin-src")
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", "-b", "feature", str(origin), str(clone))  # only a local feature exists
    facts, _ = snapshot(clone, "feature")
    assert facts["DEFAULT_BRANCH"] == "main"
    assert facts["DEFAULT_TIP"] == "MISSING"
    assert facts["SOURCE_TIP"] != "MISSING"


# ------------------------------------------------------------------ repository shapes
def test_a_detached_head_resolves_and_shows_a_self_merge_as_equal_tips(tmp_path):
    repo = make_repo(tmp_path)
    git(repo, "checkout", "-q", "--detach", "main")
    facts, proc = snapshot(repo, "HEAD", DEFAULT_BRANCH_FALLBACK="main")
    assert proc.returncode == 0
    assert facts["SOURCE_TIP"] == facts["DEFAULT_TIP"] == git(repo, "rev-parse", "main")
    git(repo, "checkout", "-q", "--detach", "feature")
    facts, _ = snapshot(repo, "HEAD", DEFAULT_BRANCH_FALLBACK="main")
    assert facts["SOURCE_TIP"] == git(repo, "rev-parse", "feature") != facts["DEFAULT_TIP"]


def test_a_subdirectory_reports_the_top_level(tmp_path):
    repo = make_repo(tmp_path)
    sub = repo / "deep" / "er"
    sub.mkdir(parents=True)
    facts, _ = run(sub, "snapshot", "feature")
    assert facts["REPO_ROOT"] == os.path.realpath(repo)


def test_a_linked_worktree_reports_its_own_top_level(tmp_path):
    repo = make_repo(tmp_path)
    linked = tmp_path / "linked"
    git(repo, "worktree", "add", "-q", str(linked), "feature")
    facts, _ = snapshot(linked, "feature", DEFAULT_BRANCH_FALLBACK="main")
    main_facts, _ = snapshot(repo, "feature", DEFAULT_BRANCH_FALLBACK="main")
    assert facts["REPO_ROOT"] == os.path.realpath(linked) != main_facts["REPO_ROOT"]
    assert facts["REPO_HASH"] != main_facts["REPO_HASH"]
    assert facts["SOURCE_TIP"] == main_facts["SOURCE_TIP"] and facts["DEFAULT_TIP"] == main_facts["DEFAULT_TIP"]


def test_outside_a_repository_both_tips_are_missing(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    facts, proc = snapshot(plain, "feature", GIT_CEILING_DIRECTORIES=str(tmp_path))
    assert proc.returncode == 0
    assert (facts["SOURCE_TIP"], facts["DEFAULT_TIP"], facts["REPO_ROOT"]) == ("MISSING", "MISSING", "")
    assert facts["REPO_HASH"] == hashlib.sha256(b"").hexdigest()[:16]


def test_session_id_is_empty_when_the_variable_is_unset(tmp_path):
    repo = make_repo(tmp_path)
    facts, _ = snapshot(repo, "feature", session=None)
    assert facts["SESSION_ID"] == "" and list(facts) == SNAPSHOT_KEYS
    facts, _ = snapshot(repo, "feature", session="")
    assert facts["SESSION_ID"] == ""


# ------------------------------------------------------------------ the old block, value for value
def _old(repo: Path, script: str, ref: str, **env: str) -> dict:
    """The variables the old shell block set, after it ran in `repo` with RESOLVED_REF bound."""
    names = ["SOURCE_TIP", "DEFAULT_BRANCH", "DEFAULT_TIP", "REPO_HASH", "REPO_ROOT", "SESSION_ID",
             "CURRENT_SOURCE_TIP", "CURRENT_DEFAULT_TIP"]
    done = subprocess.run(["bash", "-c", script + 'for v in "$@"; do printf "%s=%s\\n" "$v" "${!v}"; done', "x", *names],
                          cwd=repo, text=True, capture_output=True, check=True, env=_env(RESOLVED_REF=ref, **env))
    return dict(line.split("=", 1) for line in done.stdout.splitlines())


@pytest.mark.parametrize("scenario", ["branch", "missing-ref", "no-default-branch", "detached", "remote-default",
                                      "tag"])
def test_snapshot_equals_the_block_it_replaced(tmp_path, scenario):
    repo = make_repo(tmp_path)
    ref, env = "feature", {}
    if scenario == "missing-ref":
        ref = "no-such-ref"
    elif scenario == "no-default-branch":
        git(repo, "branch", "-m", "main", "other")
    elif scenario == "detached":
        git(repo, "checkout", "-q", "--detach")
        ref = "HEAD"
    elif scenario == "remote-default":
        clone = tmp_path / "clone"
        git(tmp_path, "clone", "-q", str(repo), str(clone))
        repo, ref = clone, "origin/feature"
    elif scenario == "tag":
        git(repo, "tag", "-a", "-m", "v", "v1", "feature")
        ref = "v1"
    new, proc = snapshot(repo, ref, **env)
    assert proc.returncode == 0
    old = _old(repo, OLD_STEP1_BLOCK % {"harness": REPO_ROOT}, ref, **env)
    for key in ("SOURCE_TIP", "DEFAULT_BRANCH", "DEFAULT_TIP", "REPO_HASH", "REPO_ROOT", "SESSION_ID"):
        assert new[key] == old[key], key


# ------------------------------------------------------------------ Step 4: the tips again
def test_tips_prints_the_two_current_tips(tmp_path):
    repo = make_repo(tmp_path)
    facts, proc = run(repo, "tips", "feature", "main")
    assert proc.returncode == 0 and proc.stderr == ""
    assert facts == {"CURRENT_SOURCE_TIP": git(repo, "rev-parse", "feature"),
                     "CURRENT_DEFAULT_TIP": git(repo, "rev-parse", "main")}
    assert list(facts) == ["CURRENT_SOURCE_TIP", "CURRENT_DEFAULT_TIP"]


def test_tips_follow_a_branch_that_moved_since_the_snapshot(tmp_path):
    repo = make_repo(tmp_path)
    before, _ = snapshot(repo, "feature", DEFAULT_BRANCH_FALLBACK="main")
    git(repo, "checkout", "-q", "feature")
    moved = commit(repo, "d.txt")
    git(repo, "checkout", "-q", "main")
    after, _ = run(repo, "tips", "feature", before["DEFAULT_BRANCH"])
    assert after["CURRENT_SOURCE_TIP"] == moved != before["SOURCE_TIP"]
    assert after["CURRENT_DEFAULT_TIP"] == before["DEFAULT_TIP"]
    tip = commit(repo, "e.txt")
    after, _ = run(repo, "tips", "feature", before["DEFAULT_BRANCH"])
    assert after["CURRENT_DEFAULT_TIP"] == tip != before["DEFAULT_TIP"]


def test_tips_of_a_ref_that_vanished_are_missing(tmp_path):
    repo = make_repo(tmp_path)
    git(repo, "branch", "-D", "feature")
    facts, proc = run(repo, "tips", "feature", "gone")
    assert proc.returncode == 0
    assert facts == {"CURRENT_SOURCE_TIP": "MISSING", "CURRENT_DEFAULT_TIP": "MISSING"}


@pytest.mark.parametrize("scenario", ["branch", "tag", "missing"])
def test_tips_agree_with_the_block_they_replaced_where_it_printed_a_tip(tmp_path, scenario):
    repo = make_repo(tmp_path)
    ref = {"branch": "feature", "tag": "v1", "missing": "nope"}[scenario]
    if scenario == "tag":
        git(repo, "tag", "-a", "-m", "v", "v1", "feature")
    new, _ = run(repo, "tips", ref, "main")
    old = _old(repo, 'DEFAULT_BRANCH=main\n' + OLD_STEP4_BLOCK, ref)
    for key in new:
        assert new[key] == (old[key] or "MISSING"), key  # the old block printed "" where this prints MISSING


# ------------------------------------------------------------------ arguments
@pytest.mark.parametrize("args", [(), ("snapshot",), ("snapshot", "a", "b"), ("tips",), ("tips", "a"),
                                  ("tips", "a", "b", "c"), ("nonsense", "a"), ("--help",)])
def test_wrong_arguments_exit_2_with_a_usage_line_and_no_facts(tmp_path, args):
    repo = make_repo(tmp_path)
    proc = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=repo, env=_env(), text=True,
                          capture_output=True, stdin=subprocess.DEVNULL)
    assert proc.returncode == 2 and proc.stdout == "" and "usage: merge-snapshot.py" in proc.stderr


# ------------------------------------------------------------------ the command text's calls
def _merge_md_calls() -> list[str]:
    """Every shell command commands/merge.md tells the session to run (its bash fences, one per line),
    the placeholders filled as the session fills them."""
    text = (REPO_ROOT / "commands" / "merge.md").read_text(encoding="utf-8")
    calls = [line for block in re.findall(r"```bash\n(.*?)```", text, re.S) for line in block.splitlines()
             if line.strip()]
    fill = {"<HARNESS_ROOT>": str(REPO_ROOT), "<resolved-ref>": "feature/x", "<RESOLVED_REF>": "feature/x",
            "<DEFAULT_BRANCH>": "main", "<default-branch>": "main"}
    return [re.sub(r"<[A-Za-z_-]+>", lambda m: fill.get(m.group(0), "x"), call) for call in calls]


def test_the_text_calls_the_script_with_the_shapes_the_script_takes():
    calls = _merge_md_calls()
    shapes = [c for c in calls if "merge-snapshot.py" in c]
    assert len(shapes) == 2, shapes
    for call in shapes:
        words = call.split()
        assert words[0] == "python3" and words[1].strip('"').endswith("/scripts/steps/merge-snapshot.py"), call
        assert words[2] in ("snapshot", "tips"), call
        assert Path(words[1].strip('"')).is_file()
    assert any(" tips " in c for c in shapes) and any(" snapshot " in c for c in shapes)


def test_every_bash_call_in_merge_md_is_allowed_by_the_bash_safety_hook():
    sys.path[:0] = [str(REPO_ROOT / "hooks" / "lib"), str(REPO_ROOT / "hooks" / "tests")]
    try:
        import bash_execution_boundary as eb
        from pol_replay_harness import run_hook_command
    finally:
        del sys.path[:2]
    calls = _merge_md_calls()
    assert len(calls) >= 3 and any("hooks/merge.sh" in c for c in calls), calls
    for command in calls:
        result = eb.analyze(command)
        assert result["allowed"] is True, (command, result["verdict"], result.get("reason"))
        code, _out, err = run_hook_command(command)
        assert code == 0, (command, err)
