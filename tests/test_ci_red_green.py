"""scripts/ci/red-green.py: a change's tests fail on its merge base and pass on its head.

The acceptance cases run the script on this repository's own history, in a scratch clone; the rest build a
small repository so each verdict is shown on a case made for it.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "ci" / "red-green.py"
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def run(repo: Path, base: str, head: str, body: str | None = None, tmp: Path | None = None):
    cmd = [sys.executable, str(SCRIPT), "--repo", str(repo), "--base", base, "--head", head,
           "--python", sys.executable]
    if body is not None:
        assert tmp is not None
        (tmp / "body.md").write_text(body, encoding="utf-8")
        cmd += ["--body-file", str(tmp / "body.md")]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=3600,
                          env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))


@pytest.fixture(scope="module")
def history(tmp_path_factory) -> Path:
    """A scratch clone of this repository that shares its objects, so every commit of its history is there."""
    dest = tmp_path_factory.mktemp("history") / "repo"
    subprocess.run(["git", "clone", "--quiet", "--shared", "--no-checkout", str(REPO), str(dest)], check=True)
    return dest


# --- acceptance, on this repository's history ------------------------------------------------------

def test_036d1ed_reports_its_two_red_then_green_tests(history):
    r = run(history, "036d1ed^1", "036d1ed")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "**PASS**: 2 test id(s) red then green." in r.stdout
    for nodeid in (
        "hooks/tests/test_command_span.py::test_the_openers_context_is_read_in_the_cli_2_1_322_record_forms",
        "hooks/tests/test_stop_command_gate.py::"
        "test_a4_a_do_whose_minted_line_cli_2_1_322_records_as_hook_success_can_end",
    ):
        assert f"| `{nodeid}` | failed | passed | red then green |" in r.stdout


def test_6bf06147_red_test_trailer_names_the_existing_switch_first_guard(history, tmp_path):
    body = "Red-test: tests/test_harness_switch.py::test_every_registered_hook_asks_the_switch_first\n"
    r = run(history, "f0e4d9c", "6bf0614", body, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "merge base `f0e4d9ca9bf8`" in r.stdout and "head `6bf06147c1d2`" in r.stdout
    for hook in ("hooks/posttool-failure-launch.py", "hooks/subagentstart-record.py"):
        assert (f"| `tests/test_harness_switch.py::test_every_registered_hook_asks_the_switch_first[{hook}]` "
                "| failed | passed | red then green |") in r.stdout


def test_6bf06147_without_a_trailer_has_no_red(history):
    r = run(history, "f0e4d9c", "6bf0614")
    assert r.returncode == 1
    assert "no changed test_*.py and no Red-test: <nodeid> trailer" in r.stdout


def test_a_docs_only_commit_is_exempt(history):
    # bd2b555 changes docs/status.md only.
    r = run(history, "bd2b555^", "bd2b555")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "**PASS**: exempt: the diff changes only tests and docs." in r.stdout


def test_a_commit_whose_changed_test_passes_on_base_exits_1(history):
    # 281f382 deletes scripts/close-scoring-decide.py and drops its name from a forbidden-word list in
    # tests/test_close_command_text.py; that test already passes on its parent.
    r = run(history, "281f382^", "281f382")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "**FAIL**: no red: no test id fails on red and passes on green." in r.stdout
    assert "7 other test id(s) pass on red and on green." in r.stdout
    assert "red then green |" not in r.stdout


# --- verdicts, on a repository made for each ---------------------------------------------------------

def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          env=dict(os.environ, **GIT_ENV)).stdout.strip()


def commit(repo: Path, files: dict[str, str], message: str) -> str:
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def small(tmp_path) -> tuple[Path, str]:
    repo = tmp_path / "small"
    repo.mkdir()
    git(repo, "init", "-q")
    base = commit(repo, {"pytest.ini": "[pytest]\ntestpaths = tests\n", "lib.py": "def f():\n    return 1\n",
                         "tests/helper.py": "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path("
                                            "__file__).resolve().parents[1]))\n",
                         "tests/test_f.py": "import helper\nfrom lib import f\n\ndef test_f():\n"
                                            "    assert f() == 1\n"}, "base")
    return repo, base


def test_a_fix_with_its_test_goes_red_then_green(small, tmp_path):
    repo, base = small
    head = commit(repo, {"lib.py": "def f():\n    return 2\n",
                         "tests/test_f.py": "import helper\nfrom lib import f\n\ndef test_f():\n"
                                            "    assert f() == 2\n"}, "fix")
    r = run(repo, base, head)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "| `tests/test_f.py::test_f` | failed | passed | red then green |" in r.stdout


def test_a_collection_error_on_red_counts_as_red_and_is_listed_apart(small):
    repo, base = small
    head = commit(repo, {"lib.py": "def f():\n    return 1\n\ndef g():\n    return 3\n",
                         "tests/test_g.py": "import helper\nfrom lib import g\n\ndef test_g():\n"
                                            "    assert g() == 3\n"}, "add g")
    r = run(repo, base, head)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "| `tests/test_g.py::test_g` | collection error | passed | red then green (collection error on red) |" \
        in r.stdout
    errors = r.stdout.split("Collection errors on red (counted as red, apart from a failing assertion):")
    assert len(errors) == 2 and "`tests/test_g.py`" in errors[1] and "ImportError" in errors[1]


def test_test_helpers_stay_the_bases(small):
    # The head changes a helper and the test that needs it; only the test is laid over the base, so it goes
    # red, and a helper change is not exempt.
    repo, base = small
    head = commit(repo, {"tests/helper.py": "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path("
                                            "__file__).resolve().parents[1]))\nVALUE = 1\n",
                         "tests/test_f.py": "import helper\nfrom lib import f\n\ndef test_f():\n"
                                            "    assert f() == helper.VALUE\n"}, "helper")
    r = run(repo, base, head)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "| `tests/test_f.py::test_f` | failed | passed | red then green |" in r.stdout


def test_a_test_only_diff_is_exempt(small):
    repo, base = small
    head = commit(repo, {"tests/test_f.py": "import helper\nfrom lib import f\n\ndef test_f():\n"
                                            "    assert f() >= 1\n", "README.md": "x\n"}, "tests")
    r = run(repo, base, head)
    assert r.returncode == 0 and "exempt: the diff changes only tests and docs" in r.stdout


def test_none_trailer_reason_is_printed_first_and_exits_0(small):
    repo, base = small
    head = commit(repo, {"lib.py": "def f():\n    return 1  # timing\n"},
                  "change\n\nRed-test: none: the fault is a race no test can order\n")
    r = run(repo, base, head)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.splitlines()[0] == "**Red-test: none:** the fault is a race no test can order"


def test_a_red_test_line_inside_a_commit_body_is_not_a_trailer(small):
    # Only the last paragraph's trailers count: a wrapped sentence that starts with "Red-test:" names no id.
    repo, base = small
    head = commit(repo, {"lib.py": "def f():\n    return 1  # same\n"},
                  "change\n\nThe job reads a\nRed-test: trailer from the end of the message.\n\n"
                  "Signed-off-by: t <t@example.invalid>\n")
    r = run(repo, base, head)
    assert r.returncode == 1
    assert "Red-test trailers:" not in r.stdout and "Collection errors" not in r.stdout
    assert "no changed test_*.py and no Red-test: <nodeid> trailer" in r.stdout


def test_a_red_test_trailer_in_a_commit_runs_that_id(small):
    repo, base = small
    head = commit(repo, {"lib.py": "def f():\n    return 1\n\n\ndef h():\n    return 0\n"},
                  "keep f\n\nRed-test: tests/test_f.py::test_f\n")
    r = run(repo, base, head)
    assert r.returncode == 1  # the guard passes on the base too: no red
    assert "Red-test trailers: `tests/test_f.py::test_f`" in r.stdout
    assert "1 other test id(s) pass on red and on green." in r.stdout


def test_a_failing_green_is_not_red_then_green(small):
    repo, base = small
    head = commit(repo, {"lib.py": "def f():\n    return 3\n",
                         "tests/test_f.py": "import helper\nfrom lib import f\n\ndef test_f():\n"
                                            "    assert f() == 2\n"}, "broken")
    r = run(repo, base, head)
    assert r.returncode == 1
    assert "| `tests/test_f.py::test_f` | failed | failed | not green (failed) |" in r.stdout


def test_the_merge_base_is_the_red_side(small):
    # The base branch moved on after the head forked; red is still the fork point.
    repo, base = small
    head = commit(repo, {"lib.py": "def f():\n    return 2\n",
                         "tests/test_f.py": "import helper\nfrom lib import f\n\ndef test_f():\n"
                                            "    assert f() == 2\n"}, "fix")
    git(repo, "checkout", "-q", "--detach", base)
    moved = commit(repo, {"other.py": "X = 1\n"}, "unrelated")
    r = run(repo, moved, head)
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"merge base `{base[:12]}`" in r.stdout
