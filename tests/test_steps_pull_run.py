"""scripts/steps/pull-run.py: /pull's Steps 0-4 (HEAD before and after, the pull hook's call, the exit phase)
and its Graphify update, run for real against temporary git repositories with a local bare remote (no
network, nothing read from the runner's home, no real remote touched).

OLD_FENCES are the shell fences commands/pull.md ran at d64fa96 for Steps 0 and 2 and the rebase check of
Step 4; old_decision() is that step's pseudo-code (Steps 3 and 4) written out. The script's values must
equal what they compute for the same repository, so the move changed no value and no decision.
"""
from __future__ import annotations

import importlib.util
import itertools
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "steps" / "pull-run.py"
MARKER = "--- pull-run ---"
KEYS = ["PRE_PULL_HEAD", "POST_PULL_HEAD", "BRANCH", "PULL_EXIT_CODE", "REBASE_STATE", "PULL_EXIT_PHASE", "ACTION"]

OLD_FENCES = r"""
PRE_PULL_HEAD=$(git rev-parse HEAD)
BRANCH=$(git rev-parse --abbrev-ref HEAD)
POST_PULL_HEAD=$(git rev-parse HEAD)
REBASE_MERGE=$(git rev-parse --git-path rebase-merge 2>/dev/null || echo ".git/rebase-merge")
REBASE_APPLY=$(git rev-parse --git-path rebase-apply 2>/dev/null || echo ".git/rebase-apply")
if test -d "${REBASE_MERGE}" || test -d "${REBASE_APPLY}"; then REBASE=yes; else REBASE=no; fi
echo "PRE_PULL_HEAD=${PRE_PULL_HEAD}"; echo "BRANCH=${BRANCH}"; echo "POST_PULL_HEAD=${POST_PULL_HEAD}"
echo "REBASE_STATE=${REBASE}"
"""


def old_decision(exit_code: int, rebase_state_exists: bool, pre: str, post: str) -> tuple[str, str]:
    """Steps 3 and 4 of commands/pull.md at d64fa96: (pull_exit_phase, what the prompt did)."""
    if exit_code == 0 and pre == post:
        return ("success", "no_change")  # "No HEAD change ... Skipping pull-analyst. Stop."
    if exit_code == 0:
        return ("success", "analyze")
    if rebase_state_exists:
        return ("rebase_conflict", "stop")
    if pre != post:
        return ("stash_restoration_failed", "analyze")
    return ("rebase_conflict", "stop")


def _env(**extra: str) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_", "GRAPHIFY"))}
    env.update(HOME="/nonexistent-home", PYTHONDONTWRITEBYTECODE="1", GIT_CONFIG_NOSYSTEM="1",
               GIT_CONFIG_GLOBAL="/dev/null", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid", GIT_TERMINAL_PROMPT="0")
    env.update(extra)
    return env


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True, env=_env())
    return done.stdout.strip()


def commit_file(repo: Path, name: str, text: str, message: str | None = None) -> str:
    (repo / name).write_text(text, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", message or f"{name}: {text.strip()}")
    return git(repo, "rev-parse", "HEAD")


class World:
    """origin.git (bare), `work` (a clone, the repository /pull runs in) and `other` (a second clone that
    pushes what upstream gains)."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.origin = tmp / "origin.git"
        seed = tmp / "seed"
        seed.mkdir()
        git(seed, "init", "-q", "-b", "main")
        commit_file(seed, "a.txt", "one\ntwo\nthree\n")
        commit_file(seed, "b.txt", "bee\n")
        (seed / "sub").mkdir()
        commit_file(seed, "sub/s.txt", "s\n")
        git(tmp, "clone", "-q", "--bare", str(seed), str(self.origin))
        self.work = tmp / "work"
        self.other = tmp / "other"
        git(tmp, "clone", "-q", str(self.origin), str(self.work))
        git(tmp, "clone", "-q", str(self.origin), str(self.other))

    def upstream_commit(self, name: str, text: str) -> str:
        """A commit another clone pushes to origin/main."""
        commit_file(self.other, name, text)
        git(self.other, "push", "-q", "origin", "main")
        return git(self.other, "rev-parse", "HEAD")


@pytest.fixture
def world(tmp_path) -> World:
    return World(tmp_path)


def run_script(cwd: Path, *args: str, script: Path = SCRIPT, stdin: str | None = "", **env: str):
    return subprocess.run([sys.executable, str(script), *args], cwd=cwd, env=_env(**env), text=True,
                          capture_output=True, input=stdin)


def pull(cwd: Path, script: Path = SCRIPT, stdin: str | None = ""):
    """(facts, text pull.sh printed before the marker, process)."""
    proc = run_script(cwd, "run", script=script, stdin=stdin)
    assert proc.returncode == 0, proc.stderr
    head, sep, tail = proc.stdout.partition(MARKER + "\n")
    assert sep, f"no marker line in stdout: {proc.stdout!r}"
    facts: dict[str, str] = {}
    for line in tail.splitlines():
        key, eq, value = line.partition("=")
        assert eq and re.fullmatch(r"[A-Z_]+", key), f"a line after the marker is not KEY=value: {line!r}"
        facts[key] = value
    assert list(facts) == KEYS
    return facts, head, proc


# ------------------------------------------------------------------ the real hooks/pull.sh
def test_up_to_date_is_a_no_change(world):
    head = git(world.work, "rev-parse", "HEAD")
    facts, out, proc = pull(world.work)
    assert facts == {"PRE_PULL_HEAD": head, "POST_PULL_HEAD": head, "BRANCH": "main", "PULL_EXIT_CODE": "0",
                     "REBASE_STATE": "no", "PULL_EXIT_PHASE": "success", "ACTION": "no_change"}
    assert "Pull completed successfully" in out


def test_fast_forward_is_analyzed(world):
    pre = git(world.work, "rev-parse", "HEAD")
    new = world.upstream_commit("c.txt", "see\n")
    facts, out, _ = pull(world.work)
    assert (facts["PRE_PULL_HEAD"], facts["POST_PULL_HEAD"]) == (pre, new)
    assert (facts["PULL_EXIT_CODE"], facts["REBASE_STATE"], facts["PULL_EXIT_PHASE"], facts["ACTION"]) == (
        "0", "no", "success", "analyze")
    assert "Pull complete!" in out and "New commits: 1" in out


def test_fast_forward_with_a_clean_stash_pop_is_still_success(world):
    (world.work / "b.txt").write_text("bee\nmine\n", encoding="utf-8")
    new = world.upstream_commit("c.txt", "see\n")
    facts, out, _ = pull(world.work)
    assert facts["POST_PULL_HEAD"] == new and facts["PULL_EXIT_PHASE"] == "success" and facts["ACTION"] == "analyze"
    assert (world.work / "b.txt").read_text(encoding="utf-8") == "bee\nmine\n"
    assert "Stashed changes restored" in out


def test_non_conflicting_divergence_is_rebased_and_analyzed(world):
    local = commit_file(world.work, "local.txt", "mine\n")
    world.upstream_commit("c.txt", "see\n")
    facts, _, _ = pull(world.work)
    assert facts["PRE_PULL_HEAD"] == local and facts["POST_PULL_HEAD"] != local
    assert (facts["PULL_EXIT_CODE"], facts["PULL_EXIT_PHASE"], facts["ACTION"]) == ("0", "success", "analyze")
    assert git(world.work, "log", "-1", "--format=%s") == "local.txt: mine"


def test_conflicting_divergence_stops_with_a_rebase_in_progress(world):
    pre = commit_file(world.work, "a.txt", "one\nLOCAL\nthree\n")
    world.upstream_commit("a.txt", "one\nUPSTREAM\nthree\n")
    facts, out, _ = pull(world.work)
    assert facts["PRE_PULL_HEAD"] == pre
    assert facts["PULL_EXIT_CODE"] == "1" and facts["REBASE_STATE"] == "yes"
    assert (facts["PULL_EXIT_PHASE"], facts["ACTION"]) == ("rebase_conflict", "stop")
    assert "Conflicts detected during rebase" in out and "a.txt" in out
    assert git(world.work, "rev-parse", "--git-path", "rebase-merge") and (world.work / ".git" / "rebase-merge").is_dir()


def test_a_conflict_is_found_from_a_subdirectory_of_the_repository(world):
    commit_file(world.work, "a.txt", "one\nLOCAL\nthree\n")
    world.upstream_commit("a.txt", "one\nUPSTREAM\nthree\n")
    facts, _, _ = pull(world.work / "sub")
    assert (facts["PULL_EXIT_CODE"], facts["REBASE_STATE"], facts["ACTION"]) == ("1", "yes", "stop")


def test_a_conflict_in_a_linked_worktree_is_found_through_the_worktree_aware_path(world):
    linked = world.tmp / "linked"
    git(world.work, "worktree", "add", "-q", "-b", "side", str(linked), "main")
    git(linked, "push", "-q", "origin", "side")
    commit_file(linked, "a.txt", "one\nLOCAL\nthree\n")
    commit_file(world.other, "a.txt", "one\nUPSTREAM\nthree\n")
    git(world.other, "push", "-q", "origin", "HEAD:refs/heads/side")
    facts, _, _ = pull(linked)
    assert facts["BRANCH"] == "side" and facts["PULL_EXIT_CODE"] == "1"
    assert facts["REBASE_STATE"] == "yes" and facts["ACTION"] == "stop"
    assert not (linked / ".git").is_dir()  # a linked worktree has a .git file, its rebase state lives elsewhere


def test_a_failed_stash_pop_after_a_finished_rebase_is_stash_restoration_failed(world):
    (world.work / "a.txt").write_text("one\nLOCAL\nthree\n", encoding="utf-8")
    pre = git(world.work, "rev-parse", "HEAD")
    new = world.upstream_commit("a.txt", "one\nUPSTREAM\nthree\n")
    facts, out, _ = pull(world.work)
    assert (facts["PRE_PULL_HEAD"], facts["POST_PULL_HEAD"]) == (pre, new)
    assert facts["PULL_EXIT_CODE"] == "1" and facts["REBASE_STATE"] == "no"
    assert (facts["PULL_EXIT_PHASE"], facts["ACTION"]) == ("stash_restoration_failed", "analyze")
    assert "Stash conflicts detected" in out
    assert git(world.work, "stash", "list")  # pull.sh keeps the entry; the analyst's warning points at it


def test_no_upstream_remote_stops_with_the_heads_unchanged(world):
    lonely = world.tmp / "lonely"
    lonely.mkdir()
    git(lonely, "init", "-q", "-b", "main")
    head = commit_file(lonely, "a.txt", "one\n")
    facts, out, _ = pull(lonely)
    assert (facts["PRE_PULL_HEAD"], facts["POST_PULL_HEAD"], facts["BRANCH"]) == (head, head, "main")
    assert facts["PULL_EXIT_CODE"] == "1" and facts["REBASE_STATE"] == "no"
    assert (facts["PULL_EXIT_PHASE"], facts["ACTION"]) == ("rebase_conflict", "stop")
    assert "origin" in out


def test_a_branch_the_remote_does_not_have_stops_the_same_way(world):
    git(world.work, "checkout", "-q", "-b", "local-only")
    head = git(world.work, "rev-parse", "HEAD")
    facts, _, _ = pull(world.work)
    assert (facts["BRANCH"], facts["POST_PULL_HEAD"]) == ("local-only", head)
    assert (facts["PULL_EXIT_CODE"], facts["PULL_EXIT_PHASE"], facts["ACTION"]) == ("1", "rebase_conflict", "stop")


def test_detached_head_stops_and_reports_the_branch_as_head(world):
    git(world.work, "checkout", "-q", "--detach")
    head = git(world.work, "rev-parse", "HEAD")
    facts, out, _ = pull(world.work)
    assert (facts["BRANCH"], facts["PRE_PULL_HEAD"], facts["POST_PULL_HEAD"]) == ("HEAD", head, head)
    assert (facts["PULL_EXIT_CODE"], facts["PULL_EXIT_PHASE"], facts["ACTION"]) == ("1", "rebase_conflict", "stop")
    assert "Not on a branch" in out


def test_the_values_equal_what_the_old_fences_computed(world):
    """Steps 0 and 2's fences and Step 4's rebase check, run by bash in the same repository."""
    commit_file(world.work, "a.txt", "one\nLOCAL\nthree\n")
    world.upstream_commit("a.txt", "one\nUPSTREAM\nthree\n")
    facts, _, _ = pull(world.work)  # leaves a rebase in progress, so the old fences see it too
    done = subprocess.run(["bash", "-c", OLD_FENCES], cwd=world.work, env=_env(), text=True, capture_output=True)
    old = dict(line.split("=", 1) for line in done.stdout.splitlines())
    assert old["BRANCH"] == "HEAD"  # mid-rebase HEAD is detached, so only the after-values are comparable here
    assert (facts["POST_PULL_HEAD"], facts["REBASE_STATE"]) == (old["POST_PULL_HEAD"], old["REBASE_STATE"])


def test_the_before_values_equal_the_old_fences_on_a_branch(world):
    done = subprocess.run(["bash", "-c", OLD_FENCES], cwd=world.work, env=_env(), text=True, capture_output=True)
    old = dict(line.split("=", 1) for line in done.stdout.splitlines())
    facts, _, _ = pull(world.work)
    assert (facts["PRE_PULL_HEAD"], facts["BRANCH"], facts["REBASE_STATE"]) == (
        old["PRE_PULL_HEAD"], old["BRANCH"], old["REBASE_STATE"]) == (git(world.work, "rev-parse", "HEAD"), "main", "no")


# ------------------------------------------------------------------ a stand-in hooks/pull.sh
def harness_with_hook(tmp: Path, body: str | None) -> Path:
    """A copy of the script under a temporary harness root whose hooks/pull.sh is `body` (none: no file);
    the script finds the hook through its own location, so the real hook is never involved."""
    root = tmp / "harness"
    (root / "scripts" / "steps").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "scripts" / "steps" / "pull-run.py")
    if body is not None:
        (root / "hooks").mkdir()
        (root / "hooks" / "pull.sh").write_text(body, encoding="utf-8")
    return root / "scripts" / "steps" / "pull-run.py"


def plain_repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit_file(repo, "a.txt", "one\n")
    return repo


def test_a_hook_failure_before_anything_changed_stops(tmp_path):
    repo = plain_repo(tmp_path)
    script = harness_with_hook(tmp_path, "echo 'hook says no'\nexit 7\n")
    facts, out, proc = pull(repo, script)
    assert out == "hook says no\n"
    assert facts["PULL_EXIT_CODE"] == "7" and facts["PRE_PULL_HEAD"] == facts["POST_PULL_HEAD"]
    assert (facts["PULL_EXIT_PHASE"], facts["ACTION"], facts["REBASE_STATE"]) == ("rebase_conflict", "stop", "no")
    assert proc.returncode == 0  # a stopped pull is a fact, not a failure of the script


def test_a_hook_that_moves_head_and_fails_is_stash_restoration_failed(tmp_path):
    repo = plain_repo(tmp_path)
    script = harness_with_hook(tmp_path, "git commit -q --allow-empty -m moved\nexit 1\n")
    facts, _, _ = pull(repo, script)
    assert facts["PRE_PULL_HEAD"] != facts["POST_PULL_HEAD"] == git(repo, "rev-parse", "HEAD")
    assert (facts["PULL_EXIT_PHASE"], facts["ACTION"]) == ("stash_restoration_failed", "analyze")


def test_a_hook_that_exits_zero_without_moving_head_is_a_no_change(tmp_path):
    """The lock-file prompt answered "no" ends pull.sh with exit 0 and nothing pulled."""
    repo = plain_repo(tmp_path)
    script = harness_with_hook(tmp_path, "echo 'Operation cancelled.'\nexit 0\n")
    facts, out, _ = pull(repo, script)
    assert (facts["PULL_EXIT_PHASE"], facts["ACTION"]) == ("success", "no_change") and "cancelled" in out


def test_a_missing_hook_file_is_a_stop_with_bash_s_127(tmp_path):
    repo = plain_repo(tmp_path)
    facts, out, _ = pull(repo, harness_with_hook(tmp_path, None))
    assert facts["PULL_EXIT_CODE"] == "127" and (facts["PULL_EXIT_PHASE"], facts["ACTION"]) == ("rebase_conflict", "stop")


def test_the_hook_output_comes_first_and_in_order_then_only_the_marker_and_the_facts(tmp_path):
    repo = plain_repo(tmp_path)
    script = harness_with_hook(tmp_path, "echo first\necho second >&2\necho third\nexit 0\n")
    proc = run_script(repo, "run", script=script)
    assert proc.stdout.startswith("first\n") and "third\n" + MARKER + "\n" in proc.stdout
    assert "second" in proc.stderr
    assert proc.stdout.split(MARKER + "\n")[1].count("\n") == len(KEYS)


def test_the_hook_reads_this_calls_stdin(tmp_path):
    """pull.sh's stale-lock question reads the answer from stdin; the script hands its own stdin on."""
    repo = plain_repo(tmp_path)
    script = harness_with_hook(tmp_path, 'read -r ANSWER\necho "answer=$ANSWER"\nexit 0\n')
    _, out, _ = pull(repo, script, stdin="y\n")
    assert out == "answer=y\n"


def test_no_commit_at_all_leaves_the_heads_empty(tmp_path):
    repo = tmp_path / "unborn"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    facts, _, _ = pull(repo, harness_with_hook(tmp_path, "exit 0\n"))
    assert (facts["PRE_PULL_HEAD"], facts["POST_PULL_HEAD"]) == ("", "")
    assert facts["ACTION"] == "no_change"


# ------------------------------------------------------------------ the decision
def load_module():
    spec = importlib.util.spec_from_file_location("pull_run", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("code,rebasing,same", list(itertools.product([0, 1, 2, 127], [False, True], [False, True])))
def test_classify_is_the_old_decision_on_every_input(code, rebasing, same):
    module = load_module()
    pre, post = "a" * 40, ("a" if same else "b") * 40
    assert module.classify(code, pre, post, rebasing) == old_decision(code, rebasing, pre, post)


def test_a_success_never_stops_and_a_rebase_in_progress_always_does():
    module = load_module()
    for rebasing, same in itertools.product([False, True], [False, True]):
        assert module.classify(0, "a", "a" if same else "b", rebasing)[0] == "success"
    for same in (False, True):
        assert module.classify(1, "a", "a" if same else "b", True) == ("rebase_conflict", "stop")


def test_wrong_arguments_are_a_usage_error():
    for args in ((), ("pull",), ("run", "extra"), ("graphify", "now")):
        proc = run_script(REPO, *args)
        assert proc.returncode == 2 and proc.stdout == "" and "usage:" in proc.stderr


# ------------------------------------------------------------------ the Graphify update
FAKE_MAINTAIN = r"""#!/usr/bin/env python3
import os, sys
print("maintain argv=" + " ".join(sys.argv[1:]))
print("maintain cwd=" + os.getcwd())
print("maintain path0=" + os.environ.get("PATH", "").split(os.pathsep)[0])
print("maintain venv=" + os.environ.get("VIRTUAL_ENV", ""))
print("maintain python=" + os.environ.get("FAKE_PYTHON_MARK", "system"))
print("maintain pythonhome=" + os.environ.get("PYTHONHOME", ""))
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
"""


def fake_home(tmp: Path, venv: bool, maintain: bool = True) -> Path:
    home = tmp / "home"
    (home / "scripts").mkdir(parents=True)
    if maintain:
        (home / "scripts" / "graphify-maintain.py").write_text(FAKE_MAINTAIN, encoding="utf-8")
    if venv:
        (home / "venv" / "bin").mkdir(parents=True)
    return home


def maintain_facts(proc) -> dict:
    return dict(line[len("maintain "):].split("=", 1) for line in proc.stdout.splitlines() if line.startswith("maintain "))


def test_graphify_runs_update_from_the_harness_home_in_the_callers_directory(tmp_path):
    home = fake_home(tmp_path, venv=False)
    cwd = tmp_path / "project"
    cwd.mkdir()
    proc = run_script(cwd, "graphify", CLAUDE_HOME=str(home))
    facts = maintain_facts(proc)
    assert proc.returncode == 0 and proc.stderr == ""
    assert facts["argv"] == "update" and Path(facts["cwd"]).resolve() == cwd.resolve()
    assert facts["venv"] == "" and facts["path0"] != str(home / "venv" / "bin")


def test_graphify_puts_the_homes_venv_first_on_path_as_activating_it_did(tmp_path):
    home = fake_home(tmp_path, venv=True)
    marker = home / "venv" / "bin" / "python3"
    marker.write_text('#!/bin/sh\nFAKE_PYTHON_MARK=venv exec %s "$@"\n' % sys.executable, encoding="utf-8")
    marker.chmod(0o755)
    proc = run_script(tmp_path, "graphify", CLAUDE_HOME=str(home), PYTHONHOME=sys.base_prefix)
    facts = maintain_facts(proc)
    assert proc.returncode == 0, proc.stderr
    assert facts["path0"] == str(home / "venv" / "bin") and facts["venv"] == str(home / "venv")
    assert facts["python"] == "venv"  # python3 resolved through the venv, the interpreter `source activate` selected
    assert facts["pythonhome"] == ""  # activate unsets PYTHONHOME


def test_graphify_never_fails(tmp_path):
    home = fake_home(tmp_path, venv=False)
    assert run_script(tmp_path, "graphify", CLAUDE_HOME=str(home), FAKE_EXIT="5").returncode == 0
    gone = fake_home(tmp_path / "gone", venv=False, maintain=False)
    proc = run_script(tmp_path, "graphify", CLAUDE_HOME=str(gone))
    assert proc.returncode == 0 and proc.stdout == ""


def test_graphify_defaults_the_home_to_dot_claude_under_home(tmp_path):
    home = tmp_path / "userhome"
    (home / ".claude" / "scripts").mkdir(parents=True)
    (home / ".claude" / "scripts" / "graphify-maintain.py").write_text(FAKE_MAINTAIN, encoding="utf-8")
    proc = run_script(tmp_path, "graphify", HOME=str(home))
    assert maintain_facts(proc)["argv"] == "update"


def test_the_real_graphify_maintain_needs_no_virtual_environment(tmp_path):
    """The experiment behind dropping `source .../venv/bin/activate` from the prompt: the maintain script
    imports only the standard library and its sibling module, and with no graphify CLI it ends with an
    advisory no-op and exit status 0, in a directory that is not the harness. (The CLI itself is installed
    in that venv, which is why the script puts the venv first on PATH when the home has one.)"""
    project = tmp_path / "project"
    project.mkdir()
    git(project, "init", "-q")
    absent = str(tmp_path / "no-such-graphify")  # GRAPHIFY_BIN names a CLI that is not there
    done = subprocess.run([sys.executable, str(REPO / "scripts" / "graphify-maintain.py"), "update"], cwd=project,
                          env=_env(GRAPHIFY_BIN=absent, CLAUDE_GRAPHIFY_CACHE_ROOT=str(tmp_path / "cache")), text=True,
                          capture_output=True, stdin=subprocess.DEVNULL)
    assert done.returncode == 0 and "advisory no-op" in done.stdout + done.stderr
    through = run_script(project, "graphify", CLAUDE_HOME=str(REPO), GRAPHIFY_BIN=absent,
                         CLAUDE_GRAPHIFY_CACHE_ROOT=str(tmp_path / "cache"))
    assert through.returncode == 0 and "advisory no-op" in through.stdout + through.stderr


# ------------------------------------------------------------------ the command text
def pull_md_calls() -> list[str]:
    """Every shell command commands/pull.md tells the session to run (its bash fences), the printed root
    filled in as the session fills it."""
    text = (REPO / "commands" / "pull.md").read_text(encoding="utf-8")
    calls = [line for block in re.findall(r"```bash\n(.*?)```", text, re.S) for line in block.splitlines() if line.strip()]
    return [call.replace("<HARNESS_ROOT>", str(REPO)) for call in calls]


def test_the_command_runs_the_script_twice_and_nothing_else():
    calls = pull_md_calls()
    assert calls == [f'python3 "{REPO}/scripts/steps/pull-run.py" run', f'python3 "{REPO}/scripts/steps/pull-run.py" graphify']
    assert not any("venv" in call or "source" in call for call in calls)
    assert (REPO / "hooks" / "pull.sh").is_file()


def test_every_bash_call_in_pull_md_is_allowed_by_the_analyzer_and_the_hook():
    sys.path.insert(0, str(REPO / "hooks" / "lib"))
    sys.path.insert(0, str(REPO / "hooks" / "tests"))
    import bash_execution_boundary as eb
    from pol_replay_harness import run_hook_command
    for command in pull_md_calls():
        result = eb.analyze(command)
        assert result["allowed"] is True, (command, result["verdict"], result.get("reason"))
        code, _out, err = run_hook_command(command)
        assert code == 0, (command, err)


def test_the_steps_the_replay_and_sync_tools_locate_are_all_still_there():
    text = (REPO / "commands" / "pull.md").read_text(encoding="utf-8")
    headings = re.findall(r"^### (.+)$", text, re.M)
    assert headings == ["Step 0: Capture pre-pull HEAD", "Step 1: Execute the pull script",
                        "Step 2: Capture post-pull HEAD", "Step 3: No-op check (exit 0, HEAD unchanged)",
                        "Step 4: Determine pull_exit_phase", "Step 5: Dispatch pull-analyst subagent",
                        "Step 6: Display pull-analyst report", "Post-pull Graphify update (advisory, non-blocking)"]


def test_every_fact_and_phase_the_command_names_is_one_the_script_prints():
    text = (REPO / "commands" / "pull.md").read_text(encoding="utf-8")
    source = SCRIPT.read_text(encoding="utf-8")
    for name in KEYS:
        assert name in text, name
    for value in ("success", "stash_restoration_failed", "rebase_conflict", "no_change", "analyze", "stop"):
        assert f"`{value}`" in text or f"={value}" in text, value
        assert f'"{value}"' in source, value
