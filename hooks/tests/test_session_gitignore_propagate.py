"""hooks/session-gitignore-propagate.sh (SessionStart): the harness's runtime directories in a
product repo are listed in the clone's own exclude file, one line each, and nothing else is written.

A product repo's tracked .gitignore stays byte-identical, a docs/dev artifact /commit stages and a
user's own new docs file stay visible, a linked worktree resolves its exclude file through
`git rev-parse --git-path`, and a project that is not a git repository is left alone.
"""
import hashlib
import os
import subprocess
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "session-gitignore-propagate.sh"
RUNTIME = [".claude/dev-registry/", ".claude/dev-start-replays/", ".claude/workflow-locks/"]


def _env(home):
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "LANG": "C.UTF-8",
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def _git(env, cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True,
                          text=True).stdout


def _hook(env, project):
    p = subprocess.run(["bash", str(HOOK)], input="{}", cwd=project, capture_output=True, text=True,
                       env=dict(env, CLAUDE_PROJECT_DIR=str(project)), timeout=30)
    assert p.returncode == 0, p.stderr
    assert p.stdout == ""


def _toy(tmp_path):
    env, repo = _env(tmp_path / "home"), tmp_path / "toy"
    (tmp_path / "home").mkdir()
    repo.mkdir()
    (repo / ".gitignore").write_text("__pycache__/\n")
    (repo / "README.md").write_text("# toy\n")
    _git(env, repo, "init", "-q", "-b", "master")
    _git(env, repo, "add", "-A")
    _git(env, repo, "commit", "-qm", "init")
    return env, repo


def _runtime_files(root, sid="s1"):
    paths = [".claude/dev-registry/agent-index.json", ".claude/dev-registry/dev-t1/dev.json",
             f".claude/dev-start-replays/{sid}/d.json", f".claude/workflow-locks/{sid}.lock"]
    for rel in paths:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("{}\n")
    return paths


def _exclude_lines(env, root):
    path = Path(root, _git(env, root, "rev-parse", "--git-path", "info/exclude").strip())
    return [ln for ln in path.read_text().splitlines() if ln and not ln.startswith("#")]


def test_product_repo_lists_each_runtime_dir_once_and_writes_no_tracked_file(tmp_path):
    env, repo = _toy(tmp_path)
    before = hashlib.sha256((repo / ".gitignore").read_bytes()).hexdigest()
    paths = _runtime_files(repo)
    for doc in ("docs/dev/dev-report-t1.json", "docs/dev/ticket-t1.md", "docs/notes/mine.md"):
        (repo / doc).parent.mkdir(parents=True, exist_ok=True)
        (repo / doc).write_text("x\n")
    _hook(env, repo)
    _hook(env, repo)  # idempotent
    assert _exclude_lines(env, repo) == RUNTIME
    assert hashlib.sha256((repo / ".gitignore").read_bytes()).hexdigest() == before
    for rel in paths:
        out = _git(env, repo, "check-ignore", "-v", rel)
        assert out.startswith(".git/info/exclude:"), out
    status = _git(env, repo, "status", "--porcelain", "--untracked-files=all").splitlines()
    assert sorted(status) == ["?? docs/dev/dev-report-t1.json", "?? docs/dev/ticket-t1.md",
                              "?? docs/notes/mine.md"]
    _git(env, repo, "add", "docs/dev/dev-report-t1.json", "docs/dev/ticket-t1.md")  # no ignored path


def test_unterminated_last_line_is_kept_apart(tmp_path):
    env, repo = _toy(tmp_path)
    (repo / ".git/info").mkdir(exist_ok=True)
    (repo / ".git/info/exclude").write_text("mine.log")
    _hook(env, repo)
    assert _exclude_lines(env, repo) == ["mine.log"] + RUNTIME


def test_linked_worktree_resolves_its_own_exclude_file(tmp_path):
    env, repo = _toy(tmp_path)
    wt = tmp_path / "wt"
    _git(env, repo, "worktree", "add", "-q", "--detach", str(wt))
    _hook(env, wt)
    assert not (wt / ".git").is_dir()
    assert _exclude_lines(env, wt) == RUNTIME
    paths = _runtime_files(wt)
    assert _git(env, wt, "status", "--porcelain", "--untracked-files=all") == ""
    assert _git(env, wt, "check-ignore", paths[0]).strip() == paths[0]


def test_not_a_git_repository_is_left_alone(tmp_path):
    env, project = dict(_env(tmp_path / "home"), GIT_CEILING_DIRECTORIES=str(tmp_path)), tmp_path / "plain"
    (tmp_path / "home").mkdir()
    project.mkdir()
    (project / ".gitignore").write_text("x\n")
    _hook(env, project)
    assert sorted(p.name for p in project.iterdir()) == [".gitignore"]
    assert (project / ".gitignore").read_text() == "x\n"
