"""P10-14 (P10 R8, A11): a command start in a product repo leaves no runtime file in `git status`.

The real SessionStart exclude step runs first, then the real UserPromptSubmit start
(hooks/prompt-workflow.py) of /dev, and of /dev-overnight --worktree. Every file the start
writes under the product repo's .claude/ (the workflow bookmark `.claude/workflow-<sid>.json`,
the overnight state `.claude/overnight-state-<sid>.json`, the overnight git bins, the overnight
worktree, the start lock and replays) is ignored through the clone's own `.git/info/exclude`; the
tracked .gitignore stays byte-identical; the only path `git status` shows is the docs/dev
requirement artifact /commit stages; and a checkpoint snapshot (hooks/lib/checkpoint-core.sh's
write_checkpoint, which adds what git status shows) holds no .claude/ path. SessionEnd then
removes the session's own bookmark.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROPAGATE = ROOT / "hooks" / "session-gitignore-propagate.sh"
START = ROOT / "hooks" / "prompt-workflow.py"
SWEEP = ROOT / "hooks" / "sessionend-scratch-sweep.sh"
CHECKPOINT = ROOT / "hooks" / "lib" / "checkpoint-core.sh"
SID = "sid-p1014"
REQUIREMENT = re.compile(r"\?\? docs/dev/user-requirement-[A-Za-z0-9-]+\.md")


def _env(tmp_path, project):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_"))}
    env.update(HOME=str(tmp_path / "home"), TMPDIR=str(tmp_path / "tmp"),
               CLAUDE_STATE_DIR=str(tmp_path / "state"), CLAUDE_PROJECT_DIR=str(project),
               PYTHONDONTWRITEBYTECODE="1", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null",
               GIT_AUTO_PUSH="0", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    for d in ("home", "tmp", "state"):
        (tmp_path / d).mkdir()
    return env


def _git(env, cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True,
                          text=True).stdout


def _run(env, cwd, argv, payload):
    p = subprocess.run(argv, cwd=cwd, env=env, input=json.dumps(payload), capture_output=True,
                       text=True, timeout=120)
    assert p.returncode == 0, p.stderr
    return p


def _toy(tmp_path):
    repo = tmp_path / "toy"
    repo.mkdir()
    env = _env(tmp_path, repo)
    (repo / ".gitignore").write_text("__pycache__/\n")
    (repo / "README.md").write_text("# toy\n")
    _git(env, repo, "init", "-q", "-b", "master")
    _git(env, repo, "add", "-A")
    _git(env, repo, "commit", "-qm", "init")
    # /dev-overnight resolves the protected branch from origin/HEAD.
    _git(env, tmp_path, "init", "-q", "--bare", "origin.git")
    _git(env, repo, "remote", "add", "origin", str(tmp_path / "origin.git"))
    _git(env, repo, "push", "-q", "origin", "master")
    _git(env, repo, "remote", "set-head", "origin", "-a")
    return env, repo


def _start(tmp_path, env, repo, prompt):
    before = hashlib.sha256((repo / ".gitignore").read_bytes()).hexdigest()
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("")
    _run(env, repo, ["bash", str(PROPAGATE)], {})
    _run(env, repo, [sys.executable, str(START)],
         {"session_id": SID, "prompt": prompt, "transcript_path": str(transcript),
          "cwd": str(repo), "hook_event_name": "UserPromptSubmit"})
    assert hashlib.sha256((repo / ".gitignore").read_bytes()).hexdigest() == before


def _runtime_files(repo):
    return sorted(str(p.relative_to(repo)) for p in (repo / ".claude").rglob("*") if p.is_file())


def _rule(env, repo, rel):
    p = subprocess.run(["git", "check-ignore", "-v", rel], cwd=repo, env=env, capture_output=True,
                       text=True)
    return p.stdout.split("\t")[0]


def _assert_clean(env, repo):
    runtime = _runtime_files(repo)
    assert runtime, "the start wrote no runtime file; the probe no longer reaches the producer"
    assert {rel: _rule(env, repo, rel) for rel in runtime
            if not _rule(env, repo, rel).startswith(".git/info/exclude:")} == {}
    status = _git(env, repo, "status", "--porcelain", "--untracked-files=all").splitlines()
    assert [ln for ln in status if not REQUIREMENT.fullmatch(ln)] == []
    branch = _git(env, repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    p = subprocess.run(["bash", "-c", f'. "{CHECKPOINT}"; write_checkpoint "" "p10-14 probe" "probe"'],
                       cwd=repo, env=env, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr
    snapshot = _git(env, repo, "ls-tree", "-r", "--name-only", f"refs/checkpoints/{branch}")
    assert [rel for rel in snapshot.splitlines() if rel.startswith(".claude/")] == []
    return runtime


def test_dev_start_leaves_no_runtime_file_in_git_status_or_the_checkpoint(tmp_path):
    env, repo = _toy(tmp_path)
    _start(tmp_path, env, repo, "/dev fix the readme")
    runtime = _assert_clean(env, repo)
    assert f".claude/workflow-{SID}.json" in runtime

    _run(env, repo, ["bash", str(SWEEP)], {"session_id": SID, "hook_event_name": "SessionEnd"})
    assert not (repo / ".claude" / f"workflow-{SID}.json").exists()


def test_overnight_start_leaves_no_runtime_file_in_git_status_or_the_checkpoint(tmp_path):
    env, repo = _toy(tmp_path)
    _start(tmp_path, env, repo, "/dev-overnight --worktree 06:00 fix the readme")
    runtime = _assert_clean(env, repo)
    assert f".claude/overnight-state-{SID}.json" in runtime
    assert any(rel.startswith(".claude/worktrees/") for rel in runtime)
