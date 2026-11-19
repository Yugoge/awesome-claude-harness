"""A snapshot before an unproven command is let through (lib/bash_safety_rules.py::let_through_unproven).

The owner's rules: a command the removal policy cannot prove safe runs and is recorded (2026-11-19); a removal must
be recoverable (2026-10-04); a snapshot is taken before such a command runs (2026-11-19, "可以"). The snapshot is
lib/checkpoint-core.sh's write_checkpoint, of the repository at the payload's cwd; the entry handed to the record
names it, or says why there is none. Every repository here is a throwaway one under the test's own directory, and
GIT_CEILING_DIRECTORIES is that directory, so "no repository" never finds one further up. No command is executed.
"""
import json
import os
import subprocess
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS_DIR = os.path.abspath(os.path.join(HERE, ".."))
UNPROVEN = "PY=venv/bin/python; $PY --version"  # a program name in a variable: unproven, no removal word

# decide() as the hook's process runs it; the seam runs for real and its entries are printed.
_DECIDE = r"""
import json, os, sys
sys.path.insert(0, os.path.join(sys.argv[1], "lib"))
out = os.fdopen(os.dup(1), "w")
os.dup2(os.open(os.devnull, os.O_WRONLY), 1)
sys.stdout = open(os.devnull, "w")
import bash_safety_rules as R
calls, seam = [], R.let_through_unproven
R.let_through_unproven = lambda entry, payload: (seam(entry, payload), calls.append(entry))
try:
    verdict, code = R.decide(sys.stdin.read()), 0
except SystemExit as exc:
    verdict, code = None, exc.code
out.write(json.dumps({"verdict": verdict, "code": code, "calls": calls}) + "\n")
"""

# snapshot_before() alone, started at a shared moment: the two-at-once case.
_AT_ONCE = r"""
import json, os, sys, time
sys.path.insert(0, os.path.join(sys.argv[1], "lib"))
import bash_safety_rules as R
start, cwd, mine = float(sys.argv[2]), sys.argv[3], sys.argv[4]
with open(os.path.join(cwd, mine), "w") as fh:
    fh.write(mine)
time.sleep(max(0.0, start - time.time()))
print(json.dumps(R.snapshot_before({"cwd": cwd})))
"""


def git(cwd, *args, **kw):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True, **kw).stdout


@pytest.fixture
def env(tmp_path):
    return {**os.environ, "GIT_CEILING_DIRECTORIES": str(tmp_path), "CHECKPOINT_LOG_DIR": str(tmp_path / "logs"),
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid", "CLAUDE_HOOK_BOUNDARY_TIMEOUT": "120s",
            "CLAUDE_STATE_DIR": str(tmp_path / "state")}


@pytest.fixture
def repo(tmp_path, env):
    os.makedirs(env["CLAUDE_STATE_DIR"])
    """A repository with a modified tracked file and an untracked one: the state before the call."""
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main", env=env)
    (r / "tracked.txt").write_bytes(b"committed\n")
    git(r, "add", "tracked.txt", env=env)
    git(r, "commit", "-q", "-m", "c", env=env)
    (r / "tracked.txt").write_bytes(b"modified \x00 before the call\n")
    (r / "untracked.bin").write_bytes(bytes(range(256)))
    return r


def slow(repo, env):
    """A snapshot that runs past a 1 s limit, as one of a very large repository does: `git add -A` runs a clean
    filter that sleeps, so the time goes where it goes in a large tree, in the snapshot's staging."""
    git(repo, "config", "filter.slow.clean", "sleep 20; cat", env=env)
    (repo / ".gitattributes").write_text("*.txt filter=slow\n")
    return {**env, "CLAUDE_HOOK_SNAPSHOT_TIMEOUT": "1s"}


def decide(command, cwd, env):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": "presnap", "cwd": str(cwd)}
    p = subprocess.run([sys.executable, "-c", _DECIDE, HOOKS_DIR], input=json.dumps(payload), capture_output=True,
                       text=True, cwd=str(cwd), env=env, timeout=180)
    assert p.stdout.strip(), p.stderr
    return json.loads(p.stdout)


def checkpoint_refs(r):
    return git(r, "for-each-ref", "--format=%(refname) %(objectname)", "refs/checkpoints").split()


def test_an_unproven_command_leaves_a_snapshot_of_the_state_before_it_and_the_entry_names_it(repo, env):
    index = (repo / ".git" / "index").read_bytes()
    result = decide(UNPROVEN, repo, env)
    assert result["verdict"] == "ALLOW" and len(result["calls"]) == 1, result
    shot = result["calls"][0]["snapshot"]
    assert shot["ref"] == "refs/checkpoints/main" and checkpoint_refs(repo) == [shot["ref"], shot["commit"]], shot
    blob = subprocess.run(["git", "-C", str(repo), "show", f"{shot['commit']}:untracked.bin"], capture_output=True).stdout
    assert blob == bytes(range(256))
    blob = subprocess.run(["git", "-C", str(repo), "show", f"{shot['commit']}:tracked.txt"], capture_output=True).stdout
    assert blob == b"modified \x00 before the call\n"
    assert shot["commit"] in shot["restore"] and str(repo) in shot["restore"]
    # The user's index, HEAD and branch are untouched; no push was started (none is configured either way).
    assert (repo / ".git" / "index").read_bytes() == index
    assert git(repo, "rev-parse", "HEAD") == git(repo, "rev-parse", "refs/heads/main")
    assert not list((repo / ".git").glob("checkpoint-index.*"))


def test_the_restore_line_brings_back_removed_and_overwritten_files_byte_for_byte(repo, env):
    shot = decide(UNPROVEN, repo, env)["calls"][0]["snapshot"]
    os.remove(repo / "untracked.bin")
    (repo / "tracked.txt").write_bytes(b"overwritten\n")
    restore = shot["restore"].split(", or ")[0].replace("<path>", "untracked.bin tracked.txt")
    subprocess.run(restore.split(), check=True, env=env)
    assert (repo / "untracked.bin").read_bytes() == bytes(range(256))
    assert (repo / "tracked.txt").read_bytes() == b"modified \x00 before the call\n"


@pytest.mark.parametrize("command,snapshot", [
    (UNPROVEN, True),                       # unproven and let through: the one case that snapshots
    ("ls -la", False),                      # proven harmless
    ("git status --short", False),          # proven harmless
    ("$TOOL remove pkg", False),            # unproven and refused: it names a removal
    ("rm -rf build", False),                # a removal the analyzer finds: refused
    ("$TOOL --version; git clean -fdx", False),  # let through by the removal policy, refused by a later rule
])
def test_only_an_unproven_command_that_runs_takes_a_snapshot(repo, env, command, snapshot):
    result = decide(command, repo, env)
    assert bool(checkpoint_refs(repo)) is snapshot, (command, result)
    assert bool(result["calls"]) is snapshot
    assert (result["code"] == 0) is (snapshot or command in ("ls -la", "git status --short")), result


def test_without_a_repository_the_command_runs_and_the_entry_says_there_is_none(tmp_path, env):
    plain = tmp_path / "plain"
    plain.mkdir()
    result = decide(UNPROVEN, plain, env)
    assert result["verdict"] == "ALLOW", result
    assert result["calls"][0]["snapshot"] == {"none": "not inside a git repository"}


def test_without_a_working_directory_in_the_payload_there_is_no_snapshot(tmp_path, env):
    payload = {"tool_name": "Bash", "tool_input": {"command": UNPROVEN}}
    p = subprocess.run([sys.executable, "-c", _DECIDE, HOOKS_DIR], input=json.dumps(payload), capture_output=True,
                       text=True, cwd=str(tmp_path), env=env, timeout=180)
    result = json.loads(p.stdout)
    assert result["verdict"] == "ALLOW" and result["calls"][0]["snapshot"] == {
        "none": "the call names no working directory"}


def test_a_failed_snapshot_lets_the_command_run_and_says_why(repo, env):
    # A ref lock left behind by a killed git: update-ref of the checkpoint ref fails.
    (repo / ".git" / "refs" / "checkpoints").mkdir(parents=True)
    (repo / ".git" / "refs" / "checkpoints" / "main.lock").write_text("")
    result = decide(UNPROVEN, repo, env)
    assert result["verdict"] == "ALLOW", result
    assert result["calls"][0]["snapshot"] == {"none": "write_checkpoint failed (rc=1); see the checkpoint log"}
    with open(os.path.join(env["CHECKPOINT_LOG_DIR"], "checkpoint.log")) as fh:
        assert "update-ref failed" in fh.read()


def test_a_snapshot_past_its_time_limit_is_abandoned_and_the_command_runs(repo, env):
    index = (repo / ".git" / "index").read_bytes()
    start = time.monotonic()
    result = decide(UNPROVEN, repo, slow(repo, env))
    assert result["verdict"] == "ALLOW", result
    assert result["calls"][0]["snapshot"] == {
        "none": "the snapshot took longer than 1 s (CLAUDE_HOOK_SNAPSHOT_TIMEOUT)"}
    assert time.monotonic() - start < 60
    assert (repo / ".git" / "index").read_bytes() == index and checkpoint_refs(repo) == []


def test_two_snapshots_at_the_same_moment_damage_neither_each_other_nor_the_index(repo, env):
    index = (repo / ".git" / "index").read_bytes()
    status = git(repo, "status", "--porcelain")
    start = time.time() + 1.5
    procs = [subprocess.Popen([sys.executable, "-c", _AT_ONCE, HOOKS_DIR, str(start), str(repo), f"mine-{i}.txt"],
                              stdout=subprocess.PIPE, text=True, env=env) for i in range(4)]
    shots = [json.loads(p.communicate(timeout=120)[0]) for p in procs]
    assert all("commit" in s for s in shots), shots
    tip = git(repo, "rev-parse", "refs/checkpoints/main").strip()
    for i, shot in enumerate(shots):
        # Each holds its own file, and each is on the ref's one line of history.
        assert git(repo, "show", f"{shot['commit']}:mine-{i}.txt") == f"mine-{i}.txt"
        subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", shot["commit"], tip], check=True)
    assert (repo / ".git" / "index").read_bytes() == index
    assert git(repo, "status", "--porcelain").replace("".join(f"?? mine-{i}.txt\n" for i in range(4)), "") == status
    subprocess.run(["git", "-C", str(repo), "fsck", "--no-dangling"], check=True, capture_output=True)
    assert not list((repo / ".git").glob("checkpoint-index.*"))


def test_after_a_snapshot_past_its_time_limit_the_repository_gets_none_for_a_period_then_one_again(repo, env):
    """A repository too big to snapshot: one wait per period, not one per command."""
    first = decide(UNPROVEN, repo, slow(repo, env))["calls"][0]["snapshot"]
    assert first["none"].startswith("the snapshot took longer than"), first
    marks = os.listdir(env["CLAUDE_STATE_DIR"])
    assert len(marks) == 1
    start = time.monotonic()
    second = decide(UNPROVEN, repo, env)  # the ordinary limit would now let it finish: the pause decides
    assert second["verdict"] == "ALLOW" and checkpoint_refs(repo) == [], second
    assert second["calls"][0]["snapshot"]["none"].startswith(
        "the last snapshot of this repository ran past its time limit at "), second
    assert time.monotonic() - start < 30
    # The same repository reached from a subdirectory and through a link shares the mark.
    (repo / "sub").mkdir()
    os.symlink(repo, os.path.join(os.path.dirname(repo), "link"))
    for cwd in (repo / "sub", os.path.join(os.path.dirname(repo), "link")):
        assert "ran past its time limit" in decide(UNPROVEN, cwd, env)["calls"][0]["snapshot"]["none"]
    # After the period it tries again (the filter no longer sleeps).
    git(repo, "config", "filter.slow.clean", "cat", env=env)
    mark = os.path.join(env["CLAUDE_STATE_DIR"], marks[0])
    os.utime(mark, (time.time() - 1801, time.time() - 1801))
    third = decide(UNPROVEN, repo, env)["calls"][0]["snapshot"]
    assert "commit" in third and checkpoint_refs(repo) == [third["ref"], third["commit"]], third


def test_the_library_snapshots_a_repository_whose_path_holds_a_space(tmp_path, env):
    """write_checkpoint's ordinary entry, called with the work directory from elsewhere."""
    r = tmp_path / "a dir" / "my repo"
    r.mkdir(parents=True)
    git(r, "init", "-q", "-b", "main", env=env)
    (r / "f.txt").write_text("committed\n")
    git(r, "add", "f.txt", env=env)
    git(r, "commit", "-q", "-m", "c", env=env)
    (r / "f.txt").write_text("changed\n")
    (r / "new file.txt").write_text("new\n")
    lib = os.path.join(HOOKS_DIR, "lib", "checkpoint-core.sh")
    p = subprocess.run(["bash", "-c", '. "$1"; CHECKPOINT_NO_PUSH=1 write_checkpoint "$2" "test"; echo "$? $checkpoint_commit"',
                        "t", lib, str(r)], capture_output=True, text=True, cwd=str(tmp_path), env=env, timeout=60)
    rc, commit = p.stdout.split()
    assert rc == "0" and git(r, "rev-parse", "refs/checkpoints/main").strip() == commit, p
    assert git(r, "show", f"{commit}:f.txt") == "changed\n" and git(r, "show", f"{commit}:new file.txt") == "new\n"
