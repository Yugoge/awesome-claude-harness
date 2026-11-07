"""scripts/size-ratchet.py on scratch git repositories (P10 row 15, acceptance 15).

`--measure` counts the six metrics of a committed tree; `--check --budget-ref <rev>` holds HEAD to
the budget committed at <rev>, never the work tree's, and lets a budget raise pass only as a change
of its own.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "size-ratchet.py"
BUDGET = "policies/size-budget.v1.json"
METRICS = ("tracked_files", "tracked_lines", "hooks_lines", "registered_hooks", "prompt_bytes",
           "docs_reference_bytes")
SETTINGS = {"hooks": {
    "Stop": [{"hooks": [{"type": "command", "command": "python3 a.py"}]}],
    "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "b.sh"},
                                                 {"type": "command", "command": "c.sh", "timeout": 5}]}],
}}


def _env(home: Path) -> dict:
    env = dict(os.environ, HOME=str(home), GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="sandbox", GIT_AUTHOR_EMAIL="sandbox@example.invalid",
               GIT_COMMITTER_NAME="sandbox", GIT_COMMITTER_EMAIL="sandbox@example.invalid")
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    return env


class Repo:
    def __init__(self, root: Path):
        self.root, self.env = root, _env(root.parent)
        root.mkdir()
        self.git("init", "-q", "-b", "master")

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.root, env=self.env, check=True,
                              capture_output=True, text=True).stdout

    def write(self, files: dict) -> None:
        for rel, content in files.items():
            path = self.root / rel
            if content is None:
                path.unlink()
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            (path.write_bytes if isinstance(content, bytes) else path.write_text)(content)

    def commit(self, files: dict, msg: str = "change") -> str:
        self.write(files)
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", msg)
        return self.git("rev-parse", "HEAD").strip()

    def run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.root, env=self.env,
                              capture_output=True, text=True)

    def measure(self, *args: str) -> dict:
        proc = self.run("--measure", *args)
        assert proc.returncode == 0, proc.stderr
        return {k: int(v) for k, v in (line.split() for line in proc.stdout.splitlines())}


BASE_FILES = {
    "CLAUDE.md": "# rules\n",                                 # 8 bytes, prompt
    "commands/dev.md": "dev\n",                               # 4 bytes, prompt
    "commands/sub/x.md": "not a command file\n",              # not commands/*.md
    "agents/ba.md": "ba\n",                                   # 3 bytes, prompt
    "docs/reference/note.md": "abc\n",                        # 4 bytes
    "docs/reference/harness-issues-backlog.md": "backlog\n",  # 8 bytes, the backlog counts
    "docs/other.md": "outside\n",
    "hooks/h.py": "a = 1\nb = 2\nc = 3",                      # 3 lines, no final newline
    "hooks/tests/test_h.py": "def test(): pass\n",            # 1 line
    "tests/generated/test_g.py": "x\ny\n",                    # excluded from tracked_lines
    "img.bin": b"\x00\x01\n\n\n",                             # binary: a file, no lines
    "settings.json": json.dumps(SETTINGS, indent=1) + "\n",
}


@pytest.fixture
def repo(tmp_path):
    r = Repo(tmp_path / "repo")
    r.commit(BASE_FILES, "base")
    return r


def _with_budget(repo: Repo, values: dict, extra: dict | None = None, msg: str = "budget") -> str:
    return repo.commit({BUDGET: json.dumps(dict(values), indent=1) + "\n", **(extra or {})}, msg)


def _budget_at_head(repo: Repo) -> dict:
    """The budget equal to HEAD's own measurement after it is committed (its own file counted)."""
    _with_budget(repo, {m: 0 for m in METRICS}, msg="budget placeholder")
    values = repo.measure()
    _with_budget(repo, values, msg="budget = measured")
    assert repo.measure() == values
    return values


def test_measure_counts_the_six_metrics(repo):
    settings_lines = len((json.dumps(SETTINGS, indent=1) + "\n").splitlines())
    assert repo.measure() == {
        "tracked_files": 12,
        "tracked_lines": 1 + 1 + 1 + 1 + 1 + 1 + 1 + 3 + 1 + settings_lines,
        "hooks_lines": 4,
        "registered_hooks": 3,
        "prompt_bytes": 8 + 4 + 3,
        "docs_reference_bytes": 4 + 8,
    }


def test_measure_reads_the_ref_not_the_work_tree(repo):
    before = repo.measure()
    repo.commit({"hooks/new.py": "x\n" * 10, "agents/qa.md": "qa\n"})
    repo.write({"hooks/h.py": "edited\n" * 50, "commands/dev.md": "x" * 100})  # not committed
    after = repo.measure()
    assert after["hooks_lines"] == before["hooks_lines"] + 10
    assert after["prompt_bytes"] == before["prompt_bytes"] + 3
    assert after["tracked_files"] == before["tracked_files"] + 2
    assert repo.measure("--ref", "HEAD~1") == before


def test_check_without_budget_at_ref_prints_and_passes(repo):
    _budget_at_head(repo)
    proc = repo.run("--check", "--budget-ref", "HEAD~2")  # the base commit: no budget file
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "no budget at HEAD~2" in proc.stdout
    assert "tracked_files " in proc.stdout and "docs_reference_bytes " in proc.stdout


def test_check_at_the_budget_passes(repo):
    _budget_at_head(repo)
    proc = repo.run("--check", "--budget-ref", "HEAD")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OVER" not in proc.stdout and "FAIL" not in proc.stdout


def test_adding_2000_hook_lines_fails_naming_top_growers(repo):
    _budget_at_head(repo)
    budget_rev = repo.git("rev-parse", "HEAD").strip()
    repo.commit({"hooks/big.py": "pass\n" * 1990, "hooks/lib/more.py": "x = 1\n" * 10, "agents/ba.md": None})
    proc = repo.run("--check", "--budget-ref", budget_rev)
    assert proc.returncode == 1, proc.stdout
    assert "hooks_lines" in proc.stdout.split("above the budget", 1)[1].splitlines()[0]
    growers = proc.stdout.split("top growers", 1)[1]
    assert "+1990 hooks/big.py" in growers and "+10 hooks/lib/more.py" in growers
    assert growers.index("hooks/big.py") < growers.index("hooks/lib/more.py")
    assert "agents/ba.md" not in growers  # a shrinking path is no grower


def test_same_commit_also_raising_the_budget_still_fails(repo):
    values = _budget_at_head(repo)
    budget_rev = repo.git("rev-parse", "HEAD").strip()
    raised = {m: v + 100_000 for m, v in values.items()}
    _with_budget(repo, raised, {"hooks/big.py": "pass\n" * 2000})
    proc = repo.run("--check", "--budget-ref", budget_rev)
    assert proc.returncode == 1, proc.stdout
    assert "budget raised at HEAD" in proc.stdout
    assert "a budget raise must be its own change" in proc.stdout
    assert "+2000 hooks/big.py" in proc.stdout


def test_raise_with_a_change_inside_the_old_budget_still_fails(repo):
    values = _budget_at_head(repo)
    budget_rev = repo.git("rev-parse", "HEAD").strip()
    _with_budget(repo, dict(values, hooks_lines=values["hooks_lines"] + 500), {"docs/other.md": None})
    proc = repo.run("--check", "--budget-ref", budget_rev)
    assert proc.returncode == 1, proc.stdout
    assert "OVER" not in proc.stdout
    assert "a budget raise must be its own change; 1 other path(s) changed" in proc.stdout


def test_commit_only_raising_the_budget_passes_and_names_the_raise(repo):
    values = _budget_at_head(repo)
    budget_rev = repo.git("rev-parse", "HEAD").strip()
    grown = {m: values[m] + n for m, n in (("tracked_files", 1), ("tracked_lines", 2000), ("hooks_lines", 2000))}
    _with_budget(repo, dict(values, **grown))
    proc = repo.run("--check", "--budget-ref", budget_rev)
    assert proc.returncode == 0, proc.stdout
    assert "budget raised at HEAD: tracked_files" in proc.stdout
    assert f"hooks_lines {values['hooks_lines']} -> {grown['hooks_lines']}" in proc.stdout
    # the raise lands first; the growth then checks against it
    raise_rev = repo.git("rev-parse", "HEAD").strip()
    repo.commit({"hooks/big.py": "pass\n" * 2000})
    assert repo.run("--check", "--budget-ref", raise_rev).returncode == 0


def test_a_range_carrying_a_raise_and_growth_fails(repo):
    values = _budget_at_head(repo)
    budget_rev = repo.git("rev-parse", "HEAD").strip()
    _with_budget(repo, dict(values, hooks_lines=values["hooks_lines"] + 2000), msg="raise")
    repo.commit({"hooks/big.py": "pass\n" * 2000}, "growth")
    proc = repo.run("--check", "--budget-ref", budget_rev)  # the whole pull request or push
    assert proc.returncode == 1, proc.stdout
    assert "a budget raise must be its own change" in proc.stdout


@pytest.mark.parametrize("budget_text", [None, "not json\n", "[]\n"])
def test_removing_or_breaking_the_budget_counts_as_a_raise(repo, budget_text):
    _budget_at_head(repo)
    budget_rev = repo.git("rev-parse", "HEAD").strip()
    repo.commit({BUDGET: budget_text, "docs/other.md": None})
    proc = repo.run("--check", "--budget-ref", budget_rev)
    assert proc.returncode == 1, proc.stdout
    assert "a budget raise must be its own change" in proc.stdout
    alone = Repo(repo.root.parent / "alone")
    alone.commit(BASE_FILES)
    _budget_at_head(alone)
    alone_rev = alone.git("rev-parse", "HEAD").strip()
    alone.commit({BUDGET: budget_text})
    proc = alone.run("--check", "--budget-ref", alone_rev)
    assert proc.returncode == 0, proc.stdout
    assert "budget raised at HEAD" in proc.stdout


def test_the_work_tree_budget_is_never_read(repo):
    values = _budget_at_head(repo)
    budget_rev = repo.git("rev-parse", "HEAD").strip()
    repo.commit({"hooks/big.py": "pass\n" * 2000})
    repo.write({BUDGET: json.dumps({m: v * 10 for m, v in values.items()})})  # uncommitted raise
    proc = repo.run("--check", "--budget-ref", budget_rev)
    assert proc.returncode == 1 and "hooks_lines" in proc.stdout.split("above the budget", 1)[1]
    assert "budget raised" not in proc.stdout


def test_an_unresolvable_ref_fails(repo):
    proc = repo.run("--check", "--budget-ref", "0" * 40)
    assert proc.returncode == 1 and "size-ratchet: git rev-parse" in proc.stderr
    assert repo.run("--measure", "--ref", "no-such-ref").returncode == 1
    assert repo.run("--check").returncode == 2  # --budget-ref is required
