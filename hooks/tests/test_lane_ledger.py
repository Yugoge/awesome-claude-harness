"""A dev lane's file bookkeeping kept by code (hooks/lib/lane_ledger.py): the record its tool calls write, the
report its stop completes. Throwaway repositories and state directories only."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOOKS))

from lib import lane_ledger  # noqa: E402


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.invalid")
    git(root, "config", "user.name", "t")
    (root / ".gitignore").write_text("tests/generated/\n")
    for name in ("a.py", "b.py", "gone.py", "keep.py"):
        (root / name).write_text(f"{name} v1\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    return root


def call(root: Path, tool: str, agent: str = "lane-1", role: str = "dev", **tool_input) -> None:
    lane_ledger.record({"session_id": "s-1", "agent_id": agent, "agent_type": role, "tool_name": tool,
                        "tool_use_id": f"tu-{tool}", "cwd": str(root), "tool_input": tool_input})


def rec(agent: str = "lane-1") -> dict:
    return json.loads(lane_ledger._path("s-1", agent).read_text())


def lane_work(root: Path) -> None:
    """Edit a.py, create new.py, delete gone.py by Bash: each recorded before it happens, then done."""
    call(root, "Edit", file_path=str(root / "a.py"), old_string="a.py v1\n", new_string="a.py v2\n")
    (root / "a.py").write_text("a.py v2\n")
    call(root, "Write", file_path=str(root / "new.py"), content="new\n")
    (root / "new.py").write_text("new\n")
    call(root, "Bash", command="rm gone.py")
    (root / "gone.py").unlink()


def report(modified=(), created=(), snaps=None) -> dict:
    return {"dev": {"status": "completed", "files_modified": list(modified), "files_created": list(created)},
            "pre_edit_snapshots": dict(snaps or {}), "owned_edits": {}}


def test_lane_writing_no_file_list_ends_with_correct_report(repo):
    lane_work(repo)
    rep = report()
    added = lane_ledger.complete(rep, rec(), str(repo))
    assert sorted(rep["dev"]["files_modified"]) == ["a.py", "gone.py"]  # a deletion is a change (agents/dev.md)
    assert rep["dev"]["files_created"] == ["new.py"]
    assert git(repo, "cat-file", "blob", rep["pre_edit_snapshots"]["a.py"]) == "a.py v1\n"
    assert git(repo, "cat-file", "blob", rep["pre_edit_snapshots"]["gone.py"]) == "gone.py v1\n"
    assert "new.py" not in rep["pre_edit_snapshots"] and any("gone.py (deleted)" in a for a in added)


def test_correct_hand_written_report_passes_unchanged(repo):
    lane_work(repo)
    base = {p: git(repo, "rev-parse", f"HEAD:{p}").strip() for p in ("a.py", "gone.py")}
    rep = report(["a.py", "gone.py"], ["new.py"], base)
    rep["owned_edits"] = {"a.py": [{"old": "a.py v1\n", "new": "a.py v2\n"}], "new.py": [{"old": "", "new": "new\n"}]}
    before = copy.deepcopy(rep)
    assert lane_ledger.complete(rep, rec(), str(repo)) == [] and rep == before


def test_hand_written_report_omitting_an_edited_file_is_completed(repo):
    lane_work(repo)
    rep = report(["gone.py", "./not-recorded.py"], ["new.py"])
    added = lane_ledger.complete(rep, rec(), str(repo))
    assert rep["dev"]["files_modified"] == ["gone.py", "./not-recorded.py", "a.py"]  # nothing taken away
    assert "dev.files_modified +a.py" in added


def test_baseline_is_taken_before_the_first_change_only(repo):
    call(repo, "Edit", file_path=str(repo / "a.py"))
    (repo / "a.py").write_text("a.py v2\n")
    call(repo, "Edit", file_path=str(repo / "a.py"))
    assert git(repo, "cat-file", "blob", rec()["files"][str(repo / "a.py")]["pre"]) == "a.py v1\n"


# The file bookkeeping failures of that day, rebuilt as cases.

def test_git_rm_deletion_is_declared_in_files_modified(repo):
    call(repo, "Bash", command="git rm -q b.py")
    git(repo, "rm", "-q", "b.py")
    rep = report()
    lane_ledger.complete(rep, rec(), str(repo))
    assert rep["dev"]["files_modified"] == ["b.py"] and rep["dev"]["files_created"] == []


def test_program_writes_are_named_unattributed_not_guessed(repo):
    call(repo, "Bash", command="python3 build.py --out fixtures")
    (repo / "keep.py").write_text("rewritten by a program\n")
    r = rec()
    assert r["unattributed"][0]["command"].startswith("python3 build.py") and str(repo / "keep.py") not in r["files"]
    rep = report()
    assert lane_ledger.complete(rep, r, str(repo)) == [] and rep["dev"]["files_modified"] == []


def test_scratch_ignored_and_unchanged_paths_are_not_declared(repo):
    (repo / ".claude" / "scratch").mkdir(parents=True)
    (repo / "tests" / "generated").mkdir(parents=True)
    for p in (".claude/scratch/n.txt", "tests/generated/test_x.py", "keep.py"):
        call(repo, "Write", file_path=str(repo / p))
    (repo / ".claude/scratch/n.txt").write_text("x")
    (repo / "tests/generated/test_x.py").write_text("x")
    rep = report()  # keep.py: baseline taken, the call then refused or a no-op
    assert lane_ledger.complete(rep, rec(), str(repo)) == []


def test_only_dev_lanes_are_recorded(repo):
    call(repo, "Edit", agent="qa-1", role="qa", file_path=str(repo / "a.py"))
    call(repo, "Bash", command="ls -l a.py")  # read-only: nothing to record
    assert not lane_ledger._path("s-1", "qa-1").exists() and not lane_ledger._path("s-1", "lane-1").exists()


def test_at_stop_rewrites_the_report_and_says_so_in_one_line(repo, monkeypatch):
    lane_work(repo)
    path = repo / "docs" / "dev" / "dev-report-t.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(report()))
    monkeypatch.setattr(lane_ledger, "_report_path", lambda payload, project_dir: path)
    lines = lane_ledger.at_stop({"session_id": "s-1", "agent_id": "lane-1"})
    assert len(lines) == 1 and lines[0].startswith("lane-ledger: ")
    assert json.loads(path.read_text())["dev"]["files_created"] == ["new.py"]
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name]  # replaced whole: no temp file of its own
    record = lane_ledger._path("s-1", "lane-1")
    assert record.exists()  # kept until the stop stands: a refused stop and the next share one record
    call(repo, "Edit", file_path=str(repo / "a.py"), old_string="v2", new_string="v3")  # after a refused stop
    (repo / "a.py").write_text("a.py v3\n")
    before = path.read_text()
    again = lane_ledger.at_stop({"session_id": "s-1", "agent_id": "lane-1"})  # already declared: no change
    assert path.read_text() == before and record.exists()
    assert not any("completed" in line for line in again)  # only what is still the lane's to write is named
    assert lane_ledger.end({"session_id": "s-1", "agent_id": "lane-1"}) == []  # the stop stands: removed
    assert not record.exists() and not record.with_suffix(".lock").exists()


def test_a_stop_with_no_readable_report_keeps_the_record(repo, monkeypatch):
    lane_work(repo)
    monkeypatch.setattr(lane_ledger, "_report_path", lambda payload, project_dir: repo / "docs" / "dev" / "none.json")
    assert lane_ledger.at_stop({"session_id": "s-1", "agent_id": "lane-1"}) == []
    assert set(rec()["files"]) == {str(repo / n) for n in ("a.py", "new.py", "gone.py")}


# owned_edits: the lane's own edits inside a file other writers also change, derived where the record proves them.

def edit(root: Path, name: str, old: str, new: str, apply: bool = True) -> None:
    call(root, "Edit", file_path=str(root / name), old_string=old, new_string=new)
    if apply:
        (root / name).write_text((root / name).read_text().replace(old, new, 1))


def shared(root: Path) -> None:
    """a.py already carries another cycle's uncommitted line when the lane starts: a shared file."""
    (root / "a.py").write_text("a.py v1\nforeign line\ntail\n")


def replay(snapshot: str, edits: list) -> str:
    """The commit plan's own replay (scripts/stage-owned-hunks.py _replay_live): forward from the snapshot."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("soh", HOOKS.parent / "scripts" / "stage-owned-hunks.py")
    soh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(soh)
    out, error = soh._replay_live(snapshot.encode(), edits, "a.py")
    assert out is not None, error
    return out.decode()


def test_lane_editing_a_shared_file_without_owned_edits_ends_with_a_correct_one(repo):
    shared(repo)
    edit(repo, "a.py", "a.py v1\n", "a.py v2\n")
    edit(repo, "a.py", "tail\n", "tail\nmine\n")
    edit(repo, "a.py", "absent text", "x", apply=False)  # the tool refused it: nothing changed, nothing owned
    call(repo, "Write", file_path=str(repo / "new.py"), content="new\n")
    (repo / "new.py").write_text("new\n")
    rep = report()
    added = lane_ledger.complete(rep, rec(), str(repo))
    assert rep["owned_edits"]["a.py"] == [{"old": "a.py v1\n", "new": "a.py v2\n"}, {"old": "tail\n", "new": "tail\nmine\n"}]
    assert rep["owned_edits"]["new.py"] == [{"old": "", "new": "new\n"}]
    snapshot = git(repo, "cat-file", "blob", rep["pre_edit_snapshots"]["a.py"])
    assert snapshot == "a.py v1\nforeign line\ntail\n" and replay(snapshot, rep["owned_edits"]["a.py"]) == (repo / "a.py").read_text()
    assert "owned_edits +a.py" in added and "owned_edits +new.py" in added


def test_a_correct_hand_written_owned_edits_passes_unchanged(repo):
    shared(repo)
    edit(repo, "a.py", "a.py v1\n", "a.py v2\n")
    rep = report(["a.py"], snaps={"a.py": rec()["files"][str(repo / "a.py")]["pre"]})
    rep["owned_edits"] = {"a.py": [{"old": "a.py v1\nforeign", "new": "a.py v2\nforeign"}]}  # its own correct form
    before = copy.deepcopy(rep)
    notes: list = []
    assert lane_ledger.complete(rep, rec(), str(repo), notes) == [] and rep == before and notes == []


def test_an_interleaved_foreign_change_is_named_not_provable(repo):
    shared(repo)
    edit(repo, "a.py", "a.py v1\n", "a.py v2\n")
    (repo / "a.py").write_text((repo / "a.py").read_text().replace("foreign line", "foreign line 2"))  # another lane
    edit(repo, "a.py", "tail\n", "tail\nmine\n")
    edit(repo, "b.py", "b.py v1\n", "b.py v2\n")
    (repo / "b.py").write_text("b.py v2\nafter the lane's last edit\n")  # another writer, before the stop
    call(repo, "Bash", command="sed -i s/v1/v9/ keep.py")  # a program wrote it
    (repo / "keep.py").write_text("keep.py v9\n")
    rep, notes = report(), []
    lane_ledger.complete(rep, rec(), str(repo), notes)
    assert rep["owned_edits"] == {} and sorted(rep["dev"]["files_modified"]) == ["a.py", "b.py", "keep.py"]
    assert [n.split(":")[0] for n in notes] == ["a.py", "b.py", "keep.py"]
    assert all("another writer" in n for n in notes[:2]) and "shell command" in notes[2]


def test_at_stop_names_what_it_cannot_prove(repo, monkeypatch):
    shared(repo)
    call(repo, "Bash", command="sed -i s/tail/end/ a.py")
    (repo / "a.py").write_text("a.py v1\nforeign line\nend\n")
    path = repo / "docs" / "dev" / "dev-report-t.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(report()))
    monkeypatch.setattr(lane_ledger, "_report_path", lambda payload, project_dir: path)
    lines = lane_ledger.at_stop({"session_id": "s-1", "agent_id": "lane-1"})
    assert json.loads(path.read_text())["owned_edits"] == {}
    assert any("owned_edits" in line and "a.py" in line and "yours to write" in line for line in lines)


def test_rules_are_registered_and_the_stop_rule_runs_before_g2():
    sys.path.insert(0, str(HOOKS))
    import importlib.util
    spec = importlib.util.spec_from_file_location("gate", HOOKS / "subagentstop-producer-gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    names = [r.name for r in gate.RULES]
    assert names.index("lane-ledger") < names.index("aggregate-rebuild") < names.index("g2-artifact-contract")
    end = gate.RULES[names.index("lane-ledger-end")]  # removes the record only on a stop that stands
    assert end.kind == "witness" and end.call == "lib.lane_ledger:end" and names.index("lane-ledger-end") > max(
        i for i, r in enumerate(gate.RULES) if r.kind == "refuse")
    assert "'lane-ledger', 'pretool-lane-ledger.py'" in (HOOKS / "pretool-launch.py").read_text()
