"""A task with nothing to commit (commands/commit.md Step 5 and `--auto` item 3): the commit plan
(scripts/steps/commit-plan.py) decides it and writes its record; the commit stage of the
disposition (scripts/resolve-dev-artifact-chain.py `_check_commits`) reads the record and verifies
it again against HEAD. Scratch git projects as tests/test_disposition.py builds them; commit-plan
runs for real with a throwaway harness home, state and session."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from tests.test_disposition import (  # noqa: E402
    GIT_ENV, RESOLVER, TASK, Tree, _git, parse_gap, repository, run_cli, write_unit)

PLAN = REPO_ROOT / "scripts" / "steps" / "commit-plan.py"
RECORD = f"nothing-to-commit-{TASK}.json"


def disposition(root: Path) -> tuple[str, str | None, list[tuple[str, str]]]:
    """(disposition, the LANDED line's value or None, [(artifact, problem)]) at the commit stage."""
    proc = run_cli(root, "commit")
    assert proc.returncode == 0, proc.stderr
    lines = [line for line in proc.stdout.splitlines() if not line.startswith("CHAIN=")]
    landed = [line[len("LANDED="):] for line in lines if line.startswith("LANDED=")]
    gaps = [parse_gap(line) for line in lines[1:] if not line.startswith("LANDED=")]
    return lines[0].split()[0].split("=")[1], (landed or [None])[0], [(g["artifact"], g["problem"]) for g in gaps]


def plan(root: Path, tmp_path: Path) -> dict:
    """commit-plan.py run from the project, as /commit Step 5 runs it."""
    home = tmp_path / "harness-home"
    if not home.exists():
        home.mkdir()
        _git(home, "init", "-q", "-b", "main")
        _git(home, "commit", "-q", "--allow-empty", "-m", "seed")
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "CLAUDE_CODE_SESSION_ID")}
    env.update(GIT_ENV, CLAUDE_HOME=str(home), CLAUDE_STATE_DIR=str(tmp_path / "state"),
               ATTRIBUTION_STATE_DIR=str(tmp_path / "attr"), CLAUDE_SESSION_ID="session-under-test")
    proc = subprocess.run([sys.executable, str(PLAN), "--task-id", TASK], cwd=root, env=env,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(proc.stdout)
    assert out["plan_error"] is None, out["plan_error"]
    return out


@pytest.fixture
def landed(tmp_path):
    """A closed task whose two owned files are already landed without a commit of its own: one is
    in HEAD as the work tree holds it, the other is ignored by the repository."""
    tree = Tree(tmp_path / "proj")
    (tree.root / ".gitignore").write_text("*.log\n", encoding="utf-8")
    write_unit(tree, TASK, files=("scripts/one.py", "scripts/run.log"))
    tree.write(f"close-report-{TASK}.md", "# Close\n\nCLOSE: YES\n")
    repository(tree, tmp_path)
    return tree


def test_a_task_whose_files_are_all_in_head_passes_on_the_plans_record_with_its_reason(landed, tmp_path):
    assert disposition(landed.root) == ("incomplete", None, [(".", "MISSING_TASK_TRAILER")])

    out = plan(landed.root, tmp_path)

    reason = ("every path the task owns is in HEAD as the work tree holds it (1) "
              "or ignored by its repository (1)")
    assert out["nothing_to_commit"]["state"] == "nothing_to_commit"
    assert out["nothing_to_commit"]["reason"] == reason
    assert json.loads((landed.dev / RECORD).read_text()) == out["nothing_to_commit"]
    assert disposition(landed.root) == ("chain_pass", f"nothing_to_commit: {reason}", [])


@pytest.mark.parametrize("change", ["edit", "stage", "untracked"])
def test_a_task_with_a_pending_owned_change_is_still_owed_its_commit(landed, tmp_path, change):
    plan(landed.root, tmp_path)  # the record, written while nothing was pending
    one = landed.root / "scripts" / "one.py"
    if change == "untracked":
        _git(landed.root, "rm", "-q", "--cached", "scripts/one.py")
        _git(landed.root, "commit", "-q", "-m", "drop it from HEAD")
    else:
        one.write_text("a change the task owns\n", encoding="utf-8")
        if change == "stage":
            _git(landed.root, "add", "scripts/one.py")

    # the gate verifies the record again at the stop: the pending change keeps the commit owed
    assert disposition(landed.root) == ("incomplete", None, [(".", "MISSING_TASK_TRAILER")])
    # and the plan, run again, has something to commit: no record is left
    assert plan(landed.root, tmp_path)["nothing_to_commit"] is None
    assert not (landed.dev / RECORD).exists()


def test_a_task_with_broken_records_stays_owed_beside_a_nothing_to_commit_record(landed, tmp_path):
    plan(landed.root, tmp_path)
    landed.write(f"qa-report-{TASK}.json", {"request_id": TASK, "task_id": TASK, "qa": {"status": "fail"}})
    landed.write(f"close-report-{TASK}.md", "# Close\n\nCLOSE: NO\n")
    _git(landed.root, "add", "-A")
    _git(landed.root, "commit", "-q", "-m", "historical residue")

    state, _landed, gaps = disposition(landed.root)
    assert state == "incomplete"
    assert {problem for _artifact, problem in gaps} >= {"INVALID_QA_STATUS", "INVALID_CLOSE_VERDICT"}


def test_a_declared_file_that_exists_nowhere_keeps_the_commit_owed(tmp_path):
    tree = Tree(tmp_path / "proj")
    write_unit(tree, TASK, files=("scripts/one.py", "scripts/gone.py"))
    tree.write(f"close-report-{TASK}.md", "# Close\n\nCLOSE: YES\n")
    (tree.root / "scripts" / "gone.py").unlink()
    repository(tree, tmp_path)

    assert plan(tree.root, tmp_path)["nothing_to_commit"] is None
    # a record written by hand changes nothing: the facts are verified again
    record = {"task_id": TASK, "state": "nothing_to_commit", "reason": "said so"}
    tree.write(RECORD, record)
    state, _landed, gaps = disposition(tree.root)
    assert state == "incomplete" and (".", "MISSING_TASK_TRAILER") in gaps


@pytest.mark.parametrize("line", [
    "Nothing to commit (plan computed OK; dry-run found no pending change) — QA gate skipped.\n",
    json.dumps({"task_id": "20260101-000000", "state": "nothing_to_commit"}),
    json.dumps({"task_id": TASK, "state": "committed"}),
])
def test_an_agents_line_changes_nothing(landed, line):
    # every owned file is landed, but the commit plan never recorded it: only its record counts
    (landed.dev / RECORD).write_text(line, encoding="utf-8")
    landed.write(f"agent-notes-{TASK}.md", "nothing_to_commit: every file is already in HEAD\n")
    assert disposition(landed.root) == ("incomplete", None, [(".", "MISSING_TASK_TRAILER")])


def test_the_record_and_the_gate_share_one_test(landed):
    """commit-plan's writer and the gate's reader both call nothing_to_commit; commit.md names it."""
    text = (REPO_ROOT / "commands" / "commit.md").read_text(encoding="utf-8")
    assert "nothing_to_commit" in text and "nothing-to-commit-<task-id>.json" in text
    assert RESOLVER.nothing_to_commit_path(landed.dev, TASK) == landed.dev / RECORD
