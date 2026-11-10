"""hooks/session-gitignore-propagate.sh (SessionStart): the harness's runtime directories in a
product repo, and the two per-session records it keeps directly in .claude/ (the workflow bookmark
and the overnight state), are listed in the clone's own exclude file, one line each, and nothing
else is written.

A product repo's tracked .gitignore stays byte-identical, a docs/dev artifact /commit stages and a
user's own new docs file stay visible, a linked worktree resolves its exclude file through
`git rev-parse --git-path`, and a project that is not a git repository is left alone.
The harness home keeps its own tracked .gitignore instead: what is written into the home at run
time is ignored there, and a source path of the same name is not.
"""
import hashlib
import os
import subprocess
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "session-gitignore-propagate.sh"
RUNTIME = [".claude/dev-registry/", ".claude/dev-start-replays/", ".claude/overnight-fresh-clones/",
           ".claude/overnight-git-bin/", ".claude/overnight-git-policy-bin/", ".claude/specs/",
           ".claude/workflow-locks/", ".claude/worktrees/",
           ".claude/overnight-state-*.json", ".claude/workflow-*.json"]


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
             f".claude/dev-start-replays/{sid}/d.json", ".claude/specs/t1/cp-state-qa.json",
             f".claude/workflow-locks/{sid}.lock", f".claude/workflow-{sid}.json",
             f".claude/overnight-state-{sid}.json", ".claude/overnight-git-bin/git",
             ".claude/overnight-git-policy-bin/git", ".claude/worktrees/overnight-n1/README.md",
             ".claude/overnight-fresh-clones/overnight-n1/README.md"]
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
    # What Claude Code or a user keeps in .claude/ on purpose stays visible beside the patterns.
    for doc in ("docs/dev/dev-report-t1.json", "docs/dev/ticket-t1.md", "docs/notes/mine.md",
                ".claude/settings.json", ".claude/workflow.json", ".claude/commands/workflow-x.json"):
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
    assert sorted(status) == ["?? .claude/commands/workflow-x.json", "?? .claude/settings.json",
                              "?? .claude/workflow.json", "?? docs/dev/dev-report-t1.json",
                              "?? docs/dev/ticket-t1.md", "?? docs/notes/mine.md"]
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


# The harness home's own tracked .gitignore (row 9). A project-level path <project>/.claude/<name>
# lands at both depths here: this home as the project (.claude/<name>) and $HOME as the project.
HOME_RUNTIME = [
    "logs/checkpoint.log", "logs/lifecycle.jsonl", "state/attribution-journal/journals/s1.jsonl",
    "state/attribution-seals/seal-log.jsonl", "attribution-seals/seal-log.jsonl", "venv/bin/python",
    "venv.bak-20260101-000000/bin/python", "settings.json.bak-20260101-000000",
    "hooks/lib/__pycache__/m.cpython-312.pyc", "projects/-p/s1.jsonl", "todos/s1.json", "cache/c.md",
    "archive/commands/x.md", ".doc-sync-cache.json", ".env", "settings.machine.json", "page-1.png",
    "specs/t1/cp-state-qa.json", ".claude/specs/t1/cp-state-qa.json", ".claude/state/y.jsonl",
    ".claude/dev-registry/dev-t1/dev.json", ".claude/session-resources/s1/r.json",
    ".claude/overnight-fresh-clones/n1/README.md", ".claude/workflow-s1.json", ".claude/paseo-daemon/l.json",
    "docs/dev/dev-report-t1.json", "docs/codex/t1/dev.txt", "docs/clean/context-c1.json",
    "docs/test/edge-case-analysis.json", "docs/INDEX.md", "tests/generated/t1/test_x.py",
    "tests/reports/execution-report-t1.json",
]
HOME_SOURCE = ["hooks/lib/cache/x.py", "scripts/state/x.py", "docs/x.png", "docs/reference/new.md",
               "schemas/specs/x.json", "tests/projects/x.py", ".github/workflows/README.md"]


def test_harness_home_ignores_its_runtime_paths_and_no_source_path(tmp_path):
    env, home = _env(tmp_path / "h"), tmp_path / "harness"
    home.mkdir()
    (home / ".gitignore").write_bytes((HOOK.parent.parent / ".gitignore").read_bytes())
    _git(env, home, "init", "-q")
    p = subprocess.run(["git", "check-ignore", "--no-index", "-v", "-n", "--stdin"], cwd=home, env=env,
                       input="\n".join(HOME_RUNTIME + HOME_SOURCE) + "\n", capture_output=True, text=True)
    rule = {ln.split("\t")[1]: ln.split("\t")[0] for ln in p.stdout.splitlines()}
    assert [r for r in HOME_RUNTIME if not rule[r].startswith(".gitignore:")] == []
    assert {r: rule[r] for r in HOME_SOURCE if rule[r] != "::"} == {}


def test_not_a_git_repository_is_left_alone(tmp_path):
    env, project = dict(_env(tmp_path / "home"), GIT_CEILING_DIRECTORIES=str(tmp_path)), tmp_path / "plain"
    (tmp_path / "home").mkdir()
    project.mkdir()
    (project / ".gitignore").write_text("x\n")
    _hook(env, project)
    assert sorted(p.name for p in project.iterdir()) == [".gitignore"]
    assert (project / ".gitignore").read_text() == "x\n"
