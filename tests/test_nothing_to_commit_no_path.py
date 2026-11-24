"""A task that owns no path (a cycle whose reports declare no file: an investigation, a report, commands
only) and the commit check: it has nothing to commit only on /close's no-files facts
(hooks/lib/close_exit.nothing_written, read over every session of the project by nothing_to_land),
which commit-plan records and the Stop gate's disposition verifies again. A span that wrote a project
file leaves the task to the unclaimed route or owed; broken or missing records keep it owed. Scratch
git projects and transcripts as tests/test_disposition.py builds them, with the runner's throwaway
configuration directory."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from tests.test_disposition import TASK, Tree, _git, minted, repository, session, typed  # noqa: E402
from tests.test_nothing_to_commit import RECORD, disposition, plan  # noqa: E402

SID = "00000000-0000-4000-8000-0000000000a1"
TRAILER = ("incomplete", None, [(".", "MISSING_TASK_TRAILER")])
REASON = ("nothing_to_commit: the task owns no path, its reports declare no changed file and no span of it "
          "in the project's session records wrote a project file")


def _write(root: Path, name: str, n: int) -> list[dict]:
    """A Write of a project file and its result, as test_close_exit records them."""
    use = f"toolu_w{n}"
    return [{"type": "assistant", "uuid": f"w{n}", "isSidechain": False,
             "message": {"role": "assistant", "content": [{"type": "tool_use", "id": use, "name": "Write",
                                                           "input": {"file_path": str(root / name), "content": "x"}}]}},
            {"type": "user", "uuid": f"r{n}", "isSidechain": False, "toolUseResult": {},
             "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": use, "content": "ok"}]}}]


def _span(root: Path, *writes: str) -> Path:
    """The /do span of the task in a session transcript of the project, writing the named files."""
    records = [typed("do", "a neutral request"), minted()]
    for n, name in enumerate(writes):
        records += _write(root, name, n)
    return session(root, SID, records)


@pytest.fixture
def no_path(tmp_path):
    """A closed /do task whose do-report declares no file, its project a repository on main."""
    tree = Tree(tmp_path / "proj")
    tree.write(f"do-report-{TASK}.json", {
        "report_version": 1, "task_id": TASK, "request_id": TASK, "source": "do", "request": "a neutral request",
        "profile": "do", "do": {"status": "completed", "summary": "an investigation", "files_modified": [],
                                "files_created": []}})
    tree.write(f"close-report-{TASK}.md", "# Close\n\nCLOSE: YES (no files: nothing to inspect)\n")
    repository(tree, tmp_path)
    return tree


def test_a_task_whose_spans_wrote_nothing_has_nothing_to_commit(no_path, tmp_path):
    _span(no_path.root)
    assert disposition(no_path.root) == TRAILER  # before the plan ran: no record

    out = plan(no_path.root, tmp_path)

    assert out["unclaimed"]["paths"] == []
    assert out["nothing_to_commit"]["state"] == "nothing_to_commit"
    assert disposition(no_path.root) == ("chain_pass", REASON, [])
    # verified again at the stop: a write recorded after the plan ran keeps the task owed
    _span(no_path.root, "src/late.py")
    assert disposition(no_path.root) == TRAILER


def test_a_task_whose_span_wrote_a_file_is_landed_by_the_unclaimed_route_or_owed(no_path, tmp_path):
    _span(no_path.root, "src/found.py")
    (no_path.root / "src").mkdir()
    (no_path.root / "src" / "found.py").write_text("x", encoding="utf-8")

    out = plan(no_path.root, tmp_path)
    assert out["unclaimed"]["paths"] == ["src/found.py"] and out["nothing_to_commit"] is None
    assert disposition(no_path.root) == TRAILER
    # a hand-written record changes nothing: the facts are verified again
    no_path.write(RECORD, {"task_id": TASK, "state": "nothing_to_commit", "reason": "said so"})
    assert disposition(no_path.root) == TRAILER

    # the change landed some other way, without the task's commit: nothing is unclaimed, the task is owed
    _git(no_path.root, "add", "src/found.py")
    _git(no_path.root, "commit", "-q", "-m", "landed elsewhere")
    out = plan(no_path.root, tmp_path)
    assert out["unclaimed"]["paths"] == [] and out["nothing_to_commit"] is None
    assert disposition(no_path.root) == TRAILER

    # the unclaimed route's commit carries the task's line: the task has landed by its commit
    (no_path.root / "src" / "found.py").write_text("y", encoding="utf-8")
    _git(no_path.root, "commit", "-q", "-am", f"land it\n\nTask-id: {TASK}")
    assert disposition(no_path.root) == ("chain_pass", None, [])


@pytest.mark.parametrize("broken", ["no transcript", "unread agent record", "a report that lists a file"])
def test_a_task_with_broken_or_missing_records_stays_owed(no_path, tmp_path, broken):
    if broken != "no transcript":
        transcript = _span(no_path.root)
    if broken == "unread agent record":
        agents = transcript.with_suffix("") / "subagents"
        agents.mkdir(parents=True)
        (agents / "agent-a1.meta.json").write_text("{not json", encoding="utf-8")
    if broken == "a report that lists a file":  # a dev-report beside the do-report declares a file
        no_path.write(f"dev-report-{TASK}.json", {"task_id": TASK, "dev": {"files_modified": ["src/a.py"],
                                                                         "files_created": []}})
    plan(no_path.root, tmp_path)
    assert not (no_path.dev / RECORD).exists()
    no_path.write(RECORD, {"task_id": TASK, "state": "nothing_to_commit", "reason": "said so"})
    state, landed, gaps = disposition(no_path.root)
    assert state == "incomplete" and landed is None and (".", "MISSING_TASK_TRAILER") in gaps


def test_close_and_the_commit_check_call_one_definition():
    sys.path.insert(0, str(REPO_ROOT / "hooks"))
    from lib import close_exit  # noqa: E402
    text = (REPO_ROOT / "scripts" / "resolve-dev-artifact-chain.py").read_text(encoding="utf-8")
    assert "close_exit\").nothing_to_land(" in text
    source = Path(close_exit.__file__).read_text(encoding="utf-8")
    assert "nothing_written(root, task, [transcript])" in source  # /close's no_files
    assert "nothing_written(root, task, transcripts)" in source  # the commit check's nothing_to_land
    assert "nothing_to_land" in (REPO_ROOT / "commands" / "commit.md").read_text(encoding="utf-8")
