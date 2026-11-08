"""/clean's discards (P10 R14): the cleaner removes a tracked byproduct with the non-forced git rm its
Action Types table gives and prints a DISCARDED line whose recover command restores the file. The
command is taken from agents/cleaner.md and run through the real bash-safety hook, so the text and the
enforcement cannot drift apart: allowed in a product repository, refused in the harness home (where the
text has the cleaner skip the path).
"""
import json
import os
import re
import subprocess

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(REPO, "hooks", "pretool-bash-safety.sh")
CLEANER = os.path.join(REPO, "agents", "cleaner.md")
CLEAN = os.path.join(REPO, "commands", "clean.md")
DISCARDED = "DISCARDED <path> - recover: git checkout <sha> -- <path>"


def _text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _row(action):
    """The Operation cell of the cleaner's Action Types row for `action`."""
    m = re.search(r"^\|\s*\*\*%s\*\*\s*\|\s*(.*?)\s*\|" % action, _text(CLEANER), re.M)
    assert m, action
    return m.group(1)


def _codes(cell):
    return re.findall(r"`([^`]+)`", cell)


def _git(cwd, *args):
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=cwd,
                          env=env, capture_output=True, text=True)


def _hook(command, cwd):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd})
    return subprocess.run(["bash", HOOK], input=payload, text=True, capture_output=True, cwd=cwd).returncode


@pytest.fixture
def product_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "run.sh.bak").write_text("#!/bin/sh\necho old\n")
    (repo / "README.md").write_text("# repo\n")
    for step in (("init", "-q"), ("add", "-A"), ("commit", "-qm", "init")):
        assert _git(str(repo), *step).returncode == 0, step
    return str(repo)


def test_both_texts_give_the_discarded_line_and_no_rm_or_archive_rule():
    for path in (CLEANER, CLEAN):
        text = _text(path)
        assert DISCARDED in text, path
        assert "Bash (rm)" not in text and "archive docs rather than delete" not in text, path


def test_delete_is_a_non_forced_git_rm_and_archive_discards_the_same_way():
    codes = _codes(_row("delete"))
    rm = [c for c in codes if c.startswith("git rm")]
    assert rm and not re.search(r"(^|\s)-\w*f|--force", rm[0]), codes
    assert "git rev-parse HEAD" in codes and DISCARDED in codes
    assert "**delete**" in _row("archive") and "mv" not in _row("archive")


def test_the_cleaners_discard_passes_bash_safety_and_its_recover_command_restores_the_file(product_repo):
    rm, line = next(c for c in _codes(_row("delete")) if c.startswith("git rm")), DISCARDED
    path = "scripts/run.sh.bak"
    before = _text(os.path.join(product_repo, path))
    sha = _git(product_repo, "rev-parse", "HEAD").stdout.strip()
    command = rm.replace("<path>", path)
    assert _hook(command, product_repo) == 0, command
    assert subprocess.run(command, shell=True, cwd=product_repo).returncode == 0
    assert not os.path.exists(os.path.join(product_repo, path))
    recover = line.replace("<path>", path).replace("<sha>", sha).split(" - recover: ", 1)[1]
    assert _hook(recover, product_repo) == 0, recover
    assert subprocess.run(recover, shell=True, cwd=product_repo).returncode == 0
    assert _text(os.path.join(product_repo, path)) == before
    assert _git(product_repo, "status", "--porcelain").stdout == ""


def test_the_cleaners_discard_is_refused_in_the_harness_home_where_the_text_skips_it(product_repo):
    rm = next(c for c in _codes(_row("delete")) if c.startswith("git rm"))
    assert "harness home" in _text(CLEANER)
    assert _hook(rm.replace("<path>", "README.md"), REPO) == 2
    assert _hook("git -C %s %s" % (REPO, rm[len("git "):].replace("<path>", "README.md")), product_repo) == 2

