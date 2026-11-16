"""scripts/ci/diff-mutate.py (P15 decision (b)): mutation of the changed lines only, within its bounds.

Every case builds a scratch git repository under tmp_path, commits a base, changes the working tree and runs the
script there as a process; nothing outside tmp_path is read or written.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci" / "diff-mutate.py"
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]

IMPORT_LIB = "import sys\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'hooks' / 'lib'))\n"


def _write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")


def _repo(tmp_path: Path, base: dict[str, str], head: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run([*GIT, "init", "-q"], cwd=repo, check=True)
    _write(repo, base)
    subprocess.run([*GIT, "add", "-A"], cwd=repo, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", "base"], cwd=repo, check=True)
    _write(repo, head)
    subprocess.run([*GIT, "add", "-A"], cwd=repo, check=True)  # tracked, as a pull request's new files are
    return repo


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, str(SCRIPT), "--base", "HEAD", *args], cwd=repo, env=env,
                          capture_output=True, text=True, timeout=300)


def _mutants(out: str) -> list[tuple[str, int, str]]:
    return [(m[1], int(m[2]), m[3]) for m in re.finditer(r"^(?:MUTANT|KILLED|SURVIVED|TIMEOUT|UNTESTED) +(\S+):(\d+) (\S+)", out, re.M)]


def test_at_most_40_mutants_spread_over_every_changed_line(tmp_path):
    head = {"hooks/lib/many.py": "".join(f"x{k} = {k} == 1\n" for k in range(60))}  # 3 candidates a line, 180 in all
    repo = _repo(tmp_path, {"hooks/lib/many.py": ""}, head)
    done = _run(repo, "--list")
    assert done.returncode == 0, done.stderr
    assert "180 candidate mutant(s), 40 selected (cap 40)" in done.stdout
    lines = [line for _, line, _ in _mutants(done.stdout)]
    assert len(lines) == 40 and len(set(lines)) == 40  # one per line before any line gets two
    assert min(lines) <= 2 and max(lines) >= 58  # thinned across the diff, not cut at its end
    assert len(_mutants(_run(repo, "--list", "--max-mutants", "5").stdout)) == 5


def test_only_changed_lines_of_hooks_and_scripts_code_are_mutated(tmp_path):
    base = {"hooks/lib/m.py": "def f(a):\n    return a == 1\n", "tools/t.py": "A = 1\n", "hooks/tests/test_m.py": "B = 1\n"}
    head = {"hooks/lib/m.py": 'def f(a):\n    return a == 1\n\n\ndef g(a: int = 3) -> bool:\n    """Doc."""\n    return a < 2\n',
            "scripts/s.py": "C = 2 > 1\n", "tools/t.py": "A = 2\n", "hooks/tests/test_m.py": "B = 1 == 1\n"}
    done = _run(_repo(tmp_path, base, head), "--list")
    found = _mutants(done.stdout)
    assert {(path, line) for path, line, _ in found} == {("hooks/lib/m.py", 5), ("hooks/lib/m.py", 7), ("scripts/s.py", 1)}
    # line 5: the default 3 only (not the annotations); line 6, the docstring, never
    assert [op for path, line, op in found if line == 5] == ["constant"]


def test_no_sys_path_index_mutants(tmp_path):
    head = {"hooks/x.py": "import sys\nsys.path.insert(0, 'lib')\nsys.path.pop(0)\nFIRST = sys.path[0]\nY = 0\n"}
    found = _mutants(_run(_repo(tmp_path, {"hooks/x.py": ""}, head), "--list", "--max-mutants", "100").stdout)
    assert ("hooks/x.py", 5, "constant") in found  # the operator works elsewhere
    assert all(line not in (3, 4) for _, line, _ in found)
    assert [op for _, line, op in found if line == 2] == ["constant"]  # 'lib', never the index 0


WIDGET = """\
def ok(x):
    return x > 0


def unchecked(x):
    return x == 3
"""
WIDGET_TEST = IMPORT_LIB + """\
import widget


def test_ok():
    assert widget.ok(1) and not widget.ok(0)
"""


def test_survivors_are_reported_by_line_and_operator_and_the_file_is_restored(tmp_path):
    # a test that uses the word only, without naming the file or importing it, is not run
    prose = "# a widget, in prose only\n\n\ndef test_unrelated():\n    assert False\n"
    repo = _repo(tmp_path, {"hooks/lib/widget.py": "", "tests/test_widget.py": WIDGET_TEST, "tests/test_prose.py": prose},
                 {"hooks/lib/widget.py": WIDGET})
    done = _run(repo)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "1 test file(s) for hooks/lib/widget.py" in done.stdout
    found = _mutants(done.stdout)
    survived = {(line, op) for line, op in re.findall(r"^SURVIVED +hooks/lib/widget.py:(\d+) (\S+)", done.stdout, re.M)}
    assert survived == {("6", "compare"), ("6", "return-value"), ("6", "constant")}
    assert {(line, op) for _, line, op in found if line == 2} == {(2, "compare"), (2, "return-value"), (2, "constant")}
    assert "KILLED   hooks/lib/widget.py:2 compare" in done.stdout
    assert "3 killed, 3 survived" in done.stdout and "(report only)" in done.stdout
    assert (repo / "hooks/lib/widget.py").read_text() == WIDGET


def test_each_mutant_runs_pytest_x(tmp_path):
    counted = WIDGET_TEST + "\n\ndef test_after():\n    with open(Path(__file__).with_name('runs.log'), 'a') as f:\n        f.write('run\\n')\n"
    repo = _repo(tmp_path, {"hooks/lib/widget.py": "", "tests/test_widget.py": counted}, {"hooks/lib/widget.py": WIDGET.split("\n\n\n")[0] + "\n"})
    done = _run(repo)
    assert "3 killed, 0 survived" in done.stdout, done.stdout + done.stderr
    # the unmutated run reached test_after; every mutant stopped at the first failure
    assert (repo / "tests" / "runs.log").read_text() == "run\n"


SPIN = """\
def spin(n):
    i = 0
    while i != n:
        i += 1
    return i
"""
SPIN_TEST = IMPORT_LIB + "import spin\n\n\ndef test_spin():\n    assert spin.spin(3) == 3\n"


def test_a_mutant_that_never_ends_is_stopped_at_4x_the_unmutated_run(tmp_path):
    repo = _repo(tmp_path, {"hooks/lib/spin.py": "", "tests/test_spin.py": SPIN_TEST}, {"hooks/lib/spin.py": SPIN})
    done = _run(repo)
    assert done.returncode == 0, done.stdout + done.stderr
    base, limit = map(float, re.search(r"unmutated run ([\d.]+)s, timeout ([\d.]+)s", done.stdout).groups())
    assert abs(limit - 4 * base) <= 0.3  # both printed to 0.1 s
    assert "TIMEOUT  hooks/lib/spin.py:4 constant (1 -> 2)" in done.stdout  # i += 2 never meets 3
    assert (repo / "hooks/lib/spin.py").read_text() == SPIN


def test_red_unmutated_tests_are_an_error_not_a_report(tmp_path):
    failing = IMPORT_LIB + "import widget\n\n\ndef test_ok():\n    assert widget.ok(0)\n"
    repo = _repo(tmp_path, {"hooks/lib/widget.py": "", "tests/test_widget.py": failing}, {"hooks/lib/widget.py": WIDGET})
    done = _run(repo)
    assert done.returncode == 2 and "the unmutated tests fail" in done.stderr
    assert (repo / "hooks/lib/widget.py").read_text() == WIDGET


def test_a_change_with_no_code_lines_mutates_nothing(tmp_path):
    done = _run(_repo(tmp_path, {"hooks/lib/widget.py": WIDGET}, {"README.md": "x\n"}))
    assert done.returncode == 0 and "0 candidate mutant(s), 0 selected" in done.stdout
