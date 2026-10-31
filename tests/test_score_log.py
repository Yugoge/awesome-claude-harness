"""The score log's one reader (scripts/lib/score_log.py) and its two callers.

scripts/score-update.sh and scripts/score-inject.sh both call read_lines in place
of a parse of their own and keep their own exit code for a refused log: 2 and 1.
The callers run from a scratch copy whose venv/bin/activate is empty, so the
test needs no installed venv and runs the python3 on PATH."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
import score_log  # noqa: E402

LINE = (
    '{"ts":"2026-05-2%dT10:00:00Z","agent":"dev","event":"close_success_qa_pass",'
    '"prev_score":50,"new_score":52,"delta":2,"unclamped_score":52,"actor":"orchestrator","reason":"test"}'
)
# tests/score-inject-contract/test-inject-branches.sh's malformed ledger.
MALFORMED = (
    '{"ts":"2026-05-20T10:00:00Z","agent":"dev","event":"score_baseline_import","prev_score":50,'
    '"new_score":50,"delta":0,"unclamped_score":50,"actor":"migration","reason":"baseline import"}\n'
    "{invalid: not, json,,\n" + LINE % 1 + "\n"
)


def _log(tmp_path: Path, text: str | bytes) -> str:
    path = tmp_path / "lifecycle.jsonl"
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    return str(path)


def test_entries_keep_their_line_numbers_and_a_partial_last_line_is_skipped(
    tmp_path: Path,
) -> None:
    path = _log(tmp_path, LINE % 1 + "\n\n" + LINE % 2 + '\n{"ts": "2026-05-2')
    assert [(number, entry["ts"]) for number, entry in score_log.read_lines(path)] == [
        (1, "2026-05-21T10:00:00Z"),
        (3, "2026-05-22T10:00:00Z"),
    ]


@pytest.mark.parametrize("bad", ["{invalid: not, json,,", "[1, 2]", "7"])
def test_a_malformed_line_before_the_last_is_refused(tmp_path: Path, bad: str) -> None:
    path = _log(tmp_path, LINE % 1 + "\n" + bad + "\n" + LINE % 2 + "\n")
    with pytest.raises(score_log.ScoreLogError, match="line 2 .*not final line"):
        score_log.read_lines(path)


@pytest.mark.parametrize("kind", ["directory", "undecodable"])
def test_an_unreadable_log_is_refused(tmp_path: Path, kind: str) -> None:
    if kind == "directory":
        path = tmp_path / "lifecycle.jsonl"
        path.mkdir()
        path = str(path)
    else:
        path = _log(tmp_path, b"\xff\xfe" + (LINE % 1).encode())
    with pytest.raises(score_log.ScoreLogError, match="cannot read"):
        score_log.read_lines(path)


@pytest.fixture()
def scratch_scripts(tmp_path: Path) -> Path:
    root = tmp_path / "home"
    (root / "scripts" / "lib").mkdir(parents=True)
    (root / "venv" / "bin").mkdir(parents=True)
    (root / "venv" / "bin" / "activate").write_text("", encoding="utf-8")
    for name in ("score-update.sh", "score-inject.sh"):
        shutil.copy2(REPO_ROOT / "scripts" / name, root / "scripts" / name)
    shutil.copy2(REPO_ROOT / "scripts" / "lib" / "score_log.py", root / "scripts" / "lib")
    # score-update.sh's agents are the roster: hooks/lib/roster.py over agents/.
    (root / "hooks" / "lib").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "hooks" / "lib" / "roster.py", root / "hooks" / "lib")
    shutil.copytree(REPO_ROOT / "agents", root / "agents")
    return root


@pytest.mark.skipif(shutil.which("flock") is None, reason="needs util-linux flock")
@pytest.mark.parametrize(
    ("script", "arguments", "refused_exit"),
    [
        ("score-inject.sh", ["--agent", "dev"], 1),
        ("score-update.sh", ["--agent", "dev", "--event", "qa_first_pass"], 2),
    ],
)
def test_each_caller_keeps_its_exit_code_and_its_use_of_the_lines(
    tmp_path: Path, scratch_scripts: Path, script: str, arguments: list, refused_exit: int
) -> None:
    def run(text: str) -> subprocess.CompletedProcess:
        path = _log(tmp_path, text)
        return subprocess.run(
            ["bash", str(scratch_scripts / "scripts" / script), *arguments, "--lifecycle-file", path],
            capture_output=True,
            text=True,
            timeout=60,
        )

    refused = run(MALFORMED)
    assert refused.returncode == refused_exit, refused.stderr
    assert "malformed JSONL at line 2" in refused.stderr and "INJECTION_PROOF" not in refused.stdout

    accepted = run(LINE % 1 + "\n" + '{"ts": "partial')
    assert accepted.returncode == 0, accepted.stderr
    if script == "score-inject.sh":
        assert "Recent events: close_success_qa_pass(+2)" in accepted.stdout
    else:
        assert accepted.stdout.strip() == "dev:qa_first_pass:52->52 (delta=0, unclamped=52)"


@pytest.mark.skipif(shutil.which("flock") is None, reason="needs util-linux flock")
def test_score_update_agents_are_the_roster(tmp_path: Path, scratch_scripts: Path) -> None:
    # P1b row 18: an agent is scored because agents/<agent>.md declares it, so
    # the script keeps no list: graphify scores, an undeclared name is refused
    # until its agent file exists.
    log = tmp_path / "lifecycle.jsonl"

    def run(agent: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(scratch_scripts / "scripts" / "score-update.sh"), "--agent", agent,
             "--event", "qa_first_pass", "--lifecycle-file", str(log)],
            capture_output=True, text=True, timeout=60,
        )

    assert run("graphify").returncode == 0
    refused = run("wizard")
    assert refused.returncode == 1 and "unknown agent 'wizard'" in refused.stderr
    (scratch_scripts / "agents" / "wizard.md").write_text("---\nname: wizard\n---\n", encoding="utf-8")
    assert run("wizard").returncode == 0
