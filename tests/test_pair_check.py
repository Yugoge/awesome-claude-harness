"""scripts/ci/pair-check.sh judges two open PRs together, and its workflow never writes a ref.

#44 required every registered hook to ask the harness switch first and #45 registered two hooks
that did not. Each PR's CI was green; the conflict showed only on the merge train. The pair check
builds the mechanical merge of two heads, runs the union of both PRs' changed test files on it and
reports the result. These tests replay that shape in a throwaway repository: a rule added by one
side, a case added by the other, each green alone and red together.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "ci" / "pair-check.sh"
WORKFLOW = REPO / ".github" / "workflows" / "pair-check.yml"

RULE_TEST = (
    "import json, pathlib\n"
    "REG = json.loads((pathlib.Path(__file__).parent / 'registry.json').read_text())\n"
    "\n"
    "def test_every_registered_hook_asks_the_switch_first():\n"
    "    for name in REG:\n"
    "        src = (pathlib.Path(__file__).parent / name).read_text()\n"
    "        assert 'ask_switch()' in src, name\n"
)


def _env(tmp_path):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {"PATH": os.environ["PATH"], "HOME": str(home), "TMPDIR": str(tmp_path),
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def _git(repo, env, *args):
    return subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True,
                          text=True).stdout.strip()


def _commit(repo, env, files, message):
    for name, text in files.items():
        (repo / name).write_text(text)
    _git(repo, env, "add", "-A")
    _git(repo, env, "commit", "-q", "-m", message)
    return _git(repo, env, "rev-parse", "HEAD")


def _repo(tmp_path):
    env = _env(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, env, "init", "-q", "-b", "master")
    base = _commit(repo, env, {"registry.json": '["a.py"]\n', "a.py": "ask_switch()\n",
                               "notes.txt": "one\n"}, "base")
    return repo, env, base


def _branch(repo, env, base, name, files):
    _git(repo, env, "checkout", "-q", "-b", name, base)
    return _commit(repo, env, files, name)


def _pair(repo, env, base, a, b, out):
    refs_before = _git(repo, env, "for-each-ref")
    proc = subprocess.run(["bash", str(SCRIPT), "--base", base, "--python", sys.executable,
                           "--out", str(out), a, b], cwd=repo, env=env, capture_output=True,
                          text=True, timeout=300)
    assert _git(repo, env, "for-each-ref") == refs_before, "the pair check wrote a ref"
    return proc, json.loads((out / "result.json").read_text())


def test_a_rule_from_one_pr_and_a_case_from_the_other_fail_together(tmp_path):
    repo, env, base = _repo(tmp_path)
    rule = _branch(repo, env, base, "rule", {"test_switch.py": RULE_TEST})
    case = _branch(repo, env, base, "case", {
        "registry.json": '["a.py", "b.py"]\n', "b.py": "print('no switch')\n",
        "test_b.py": "def test_b_exists():\n    assert True\n"})
    proc, result = _pair(repo, env, base, rule, case, tmp_path / "out")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert result["status"] == "failed"
    assert result["failed"] == ["test_switch.py::test_every_registered_hook_asks_the_switch_first"]
    assert result["tests_run"] == ["test_b.py", "test_switch.py"]
    assert "test_every_registered_hook_asks_the_switch_first" in proc.stdout


def test_two_independent_prs_are_green(tmp_path):
    repo, env, base = _repo(tmp_path)
    one = _branch(repo, env, base, "one", {"test_one.py": "def test_one():\n    assert 1\n"})
    two = _branch(repo, env, base, "two", {"two.py": "X = 2\n",
                                           "test_two.py": "def test_two():\n    assert 2\n"})
    proc, result = _pair(repo, env, base, one, two, tmp_path / "out")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert result["status"] == "green"
    assert result["failed"] == [] and result["conflicts"] == []
    assert result["tests_run"] == ["test_one.py", "test_two.py"]


def test_a_textual_conflict_is_reported_and_its_test_file_not_run(tmp_path):
    repo, env, base = _repo(tmp_path)
    left = _branch(repo, env, base, "left", {"notes.txt": "left\n",
                                             "test_same.py": "def test_left():\n    assert 1\n"})
    right = _branch(repo, env, base, "right", {"notes.txt": "right\n",
                                               "test_same.py": "def test_right():\n    assert 1\n",
                                               "test_other.py": "def test_other():\n    assert 1\n"})
    proc, result = _pair(repo, env, base, left, right, tmp_path / "out")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert result["status"] == "conflict"
    assert result["conflicts"] == ["notes.txt", "test_same.py"]
    assert result["conflicted_tests"] == ["test_same.py"]
    assert result["tests_run"] == ["test_other.py"]


def test_a_conflict_never_hides_a_failure(tmp_path):
    repo, env, base = _repo(tmp_path)
    left = _branch(repo, env, base, "left", {"notes.txt": "left\n",
                                             "test_bad.py": "def test_bad():\n    assert 0\n"})
    right = _branch(repo, env, base, "right", {"notes.txt": "right\n"})
    proc, result = _pair(repo, env, base, left, right, tmp_path / "out")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert result["status"] == "failed" and result["conflicts"] == ["notes.txt"]
    assert result["failed"] == ["test_bad.py::test_bad"]


def test_the_merged_tree_is_a_git_checkout_and_parametrized_ids_keep_their_spaces(tmp_path):
    repo, env, base = _repo(tmp_path)
    one = _branch(repo, env, base, "one", {"test_git.py": (
        "import subprocess\n"
        "def test_tracked():\n"
        "    out = subprocess.run(['git', 'ls-files'], capture_output=True, text=True, check=True).stdout\n"
        "    assert 'test_git.py' in out.split()\n")})
    two = _branch(repo, env, base, "two", {"test_param.py": (
        "import pytest\n"
        "@pytest.mark.parametrize('x', ['a b - c'])\n"
        "def test_p(x):\n"
        "    assert 0\n")})
    proc, result = _pair(repo, env, base, one, two, tmp_path / "out")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert result["failed"] == ["test_param.py::test_p[a b - c]"]


def test_a_failing_shell_test_fails_the_pair(tmp_path):
    repo, env, base = _repo(tmp_path)
    one = _branch(repo, env, base, "one", {"test_fail.sh": "exit 1\n"})
    two = _branch(repo, env, base, "two", {"test_ok.sh": "exit 0\n"})
    proc, result = _pair(repo, env, base, one, two, tmp_path / "out")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert result["failed"] == ["test_fail.sh"]


def _workflow():
    doc = yaml.safe_load(WORKFLOW.read_text())
    # PyYAML reads the bare key `on` as the boolean True.
    return doc, doc.get("on", doc.get(True))


def test_the_workflow_runs_daily_and_on_a_label_never_on_push():
    doc, on = _workflow()
    assert set(on) == {"schedule", "pull_request", "workflow_dispatch"}, on
    assert on["schedule"][0]["cron"].split()[2:] == ["*", "*", "*"], "daily"
    assert on["pull_request"]["types"] == ["labeled"]
    assert doc["permissions"] == {}, "no token rights unless a job asks"


def test_the_workflow_writes_no_ref_and_runs_pr_code_without_write_rights():
    doc, _ = _workflow()
    text = WORKFLOW.read_text()
    for forbidden in ("git push", "update-ref", "git tag", "git commit", "/git/refs", "issues/comments",
                      "pull_request_target"):
        assert forbidden not in text, forbidden
    for name, job in doc["jobs"].items():
        perms = job.get("permissions", {})
        assert perms.get("contents", "read") == "read", (name, perms)
        assert "pull-requests" not in perms or perms["pull-requests"] == "read", (name, perms)
        if perms.get("checks") == "write":
            assert not any("pair-check.sh" in str(step.get("run", "")) for step in job["steps"]), (
                f"{name} holds checks: write and runs PR code")
    run_jobs = [j for j in doc["jobs"].values()
                if any("pair-check.sh" in str(s.get("run", "")) for s in j["steps"])]
    assert len(run_jobs) == 1
    checkout = [s for s in run_jobs[0]["steps"] if str(s.get("uses", "")).startswith("actions/checkout@")]
    assert checkout and checkout[0]["with"]["persist-credentials"] is False


def test_the_workflow_states_and_applies_a_pair_cap():
    doc, _ = _workflow()
    cap = int(doc["env"]["MAX_PAIRS"])
    assert 1 <= cap <= 20
    assert "MAX_PAIRS" in WORKFLOW.read_text().split("jobs:", 1)[1]
