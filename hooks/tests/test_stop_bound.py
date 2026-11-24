"""The Stop gate's work at one stop is bounded.

1. An --auto run's task list is fixed when the owner's command arrives (hooks/userprompt-auto-targets.py runs
   dev-lifecycle's freeze_auto_targets) and the gate reads it (read_frozen): it scans no ticket for that run.
2. A task's disposition is kept while every fact it read holds (lib/fact_cache): a second Stop with nothing
   changed computes nothing again; a changed report, a new file in a directory it listed, a new commit or a
   program other than git it ran computes it again.
3. A Stop the limit cuts off keeps the tasks it finished: the next attempt computes only the rest.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / "hooks"
SID = "stopbound-session"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load(HOOKS / "stop-command-gate.py", "stop_command_gate_bound_under_test")


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True,
                          env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}).stdout


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    (root / "docs" / "dev").mkdir(parents=True)
    (root / "owned.txt").write_text("one\n")
    (root / ".gitignore").write_text("records/\n")  # git's status never sees a record there: only its read does
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "start")
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(state))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    return root


# ------------------------------------------------------------------ 1. the list fixed at the command's arrival
def _span(tmp_path, opened: float, args: str = "--auto"):
    return types.SimpleNamespace(args=args, transcript_path=str(tmp_path / f"{SID}.jsonl"),
                                 opened_at=lambda: opened, session_families=lambda: set())


def test_the_gate_reads_the_list_fixed_at_the_command_and_scans_no_ticket(project, tmp_path, monkeypatch):
    lifecycle = gate._script("scripts/dev-lifecycle.py")
    rows = [{"task_id": t, "kind": "ticket", "next_action": "commit"} for t in ("20261101-080000", "20261101-090000")]
    monkeypatch.setattr(lifecycle, "scan", lambda root, owners=True, progress=None: rows)
    arrived = time.time()
    lifecycle.freeze_auto_targets(project, "commit", SID, arrived)
    scans = []
    monkeypatch.setattr(lifecycle, "scan", lambda *a, **k: scans.append(a) or [])
    assert gate._targets(_span(tmp_path, arrived + 2), project, "commit") == (
        ["20261101-080000", "20261101-090000"], [])
    assert scans == []
    # not this run's list: another action, a far opener (the session's earlier command), another project
    assert gate._targets(_span(tmp_path, arrived + 2), project, "close") == ([], [])
    assert gate._targets(_span(tmp_path, arrived + 3600), project, "commit") == ([], [])
    assert len(scans) == 2  # with no list fixed for the run, the gate lists as before


def _prompt(project, prompt: str):
    payload = {"session_id": SID, "prompt": prompt, "cwd": str(project), "hook_event_name": "UserPromptSubmit"}
    return subprocess.run([sys.executable, str(HOOKS / "userprompt-auto-targets.py")], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=120, env=dict(os.environ))


def test_the_owner_s_auto_command_fixes_the_list_once_at_its_arrival(project):
    (project / "docs" / "dev" / "do-report-20261101-080000.json").write_text(json.dumps({"status": "completed"}))
    lifecycle = gate._script("scripts/dev-lifecycle.py")
    done = _prompt(project, "/close --auto and the owner's words")
    assert done.returncode == 0 and done.stdout == "", done.stderr
    path = lifecycle.frozen_path(SID)
    doc = json.loads(path.read_text())
    assert doc["action"] == "close" and abs(doc["arrived_at"] - time.time()) < 120
    assert doc["targets"] == lifecycle.auto_targets(project, "close", doc["arrived_at"])
    assert lifecycle.read_frozen(SID, project, "close", doc["arrived_at"]) == doc["targets"]
    assert _prompt(project, "/commit 20261101-080000").returncode == 0
    assert json.loads(path.read_text()) == doc  # a command without --auto fixes nothing
    _prompt(project, "/commit --auto")
    assert json.loads(path.read_text())["action"] == "commit"  # the session's next --auto command replaces it


def test_a_listing_that_does_not_finish_leaves_no_older_list(project, monkeypatch):
    lifecycle = gate._script("scripts/dev-lifecycle.py")
    monkeypatch.setattr(lifecycle, "scan", lambda root, owners=True, progress=None: [])
    lifecycle.freeze_auto_targets(project, "commit", SID, time.time())
    assert lifecycle.frozen_path(SID).exists()

    def cut(*_a, **_k):
        raise TimeoutError("the rule's limit")

    monkeypatch.setattr(lifecycle, "scan", cut)
    with pytest.raises(TimeoutError):
        lifecycle.freeze_auto_targets(project, "commit", SID, time.time())
    assert not lifecycle.frozen_path(SID).exists()


def test_the_arrival_rule_is_registered_on_the_prompt_launcher():
    text = (HOOKS / "userprompt-launch.py").read_text()
    assert "Rule('auto-targets', 'userprompt-auto-targets.py'" in text


# ------------------------------------------------------------------ 2. kept while the facts it read hold
@pytest.fixture
def chain(project, monkeypatch):
    """The chain's disposition_lines, faked: it reads the task's report, lists docs/dev and asks git for HEAD."""
    calls = []

    def lines(root, task, stage):
        calls.append(task)
        report = Path(root) / "docs" / "dev" / f"dev-report-{task}.json"
        body = report.read_text() if report.exists() else "absent"
        listed = sorted(p.name for p in (Path(root) / "docs" / "dev").glob("*"))
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True).stdout
        try:  # a record read as the chain reads the commit plan's nothing-to-commit record: absent is a fact too
            record = (Path(root) / "records" / f"nothing-to-commit-{task}.json").read_text()
        except OSError:
            record = "no record"
        return [f"GAP {task} {stage} {body.strip()} {len(listed)} {head.strip()[:7]} {record}"]

    resolver = types.SimpleNamespace(disposition_lines=lines)
    monkeypatch.setitem(gate._SCRIPTS, "scripts/resolve-dev-artifact-chain.py", resolver)
    monkeypatch.setitem(gate._SCRIPTS, "scripts/aggregate-dev-report.py",
                        types.SimpleNamespace(rebuild_if_stale=lambda root, task: []))
    return calls


def test_a_second_stop_with_nothing_changed_computes_nothing_again(project, chain):
    (project / "docs" / "dev" / "dev-report-T1.json").write_text('{"v": 1}')
    first = gate.disposition(project, "T1", "commit")
    assert gate.disposition(project, "T1", "commit") == first
    assert chain == ["T1"]


@pytest.mark.parametrize("change", ["report edited", "new file listed", "record appears", "new commit",
                                    "worktree edited"])
def test_a_changed_input_computes_the_task_again(project, chain, change):
    report = project / "docs" / "dev" / "dev-report-T1.json"
    report.write_text('{"v": 1}')
    first = gate.disposition(project, "T1", "commit")
    getattr(sys.modules.get("lib.fact_cache"), "_REPOS", {}).clear()  # a later Stop is a new process
    if change == "report edited":
        report.write_text('{"v": 22}')
    elif change == "new file listed":
        (project / "docs" / "dev" / "nothing-to-commit-T1.json").write_text("{}")
    elif change == "record appears":
        (project / "records").mkdir()
        (project / "records" / "nothing-to-commit-T1.json").write_text('{"reason": "all in HEAD"}')
    elif change == "new commit":
        git(project, "commit", "-q", "--allow-empty", "-m", "Task-id: T1")
    else:
        (project / "owned.txt").write_text("two\n")
    again = gate.disposition(project, "T1", "commit")
    assert chain == ["T1", "T1"]
    assert change == "worktree edited" or again != first


def test_a_computation_that_runs_another_program_is_never_kept(project, chain, monkeypatch):
    def lines(root, task, stage):
        chain.append(task)
        subprocess.run(["true"], check=True)
        return []

    monkeypatch.setitem(gate._SCRIPTS, "scripts/resolve-dev-artifact-chain.py",
                        types.SimpleNamespace(disposition_lines=lines))
    gate.disposition(project, "T1", "commit")
    gate.disposition(project, "T1", "commit")
    assert chain == ["T1", "T1"]


# ------------------------------------------------------------------ 3. a Stop cut off keeps what it finished
class Cut(BaseException):
    """The limit's kill: nothing of the gate's own runs after it."""


def test_a_stop_the_limit_cuts_off_keeps_the_tasks_it_finished(project, chain, monkeypatch):
    tasks = ["T1", "T2", "T3", "T4"]
    budget = {"left": 2}
    fake = gate._SCRIPTS["scripts/resolve-dev-artifact-chain.py"].disposition_lines

    def limited(root, task, stage):
        if budget["left"] == 0:
            raise Cut()
        budget["left"] -= 1
        return fake(root, task, stage)

    monkeypatch.setitem(gate._SCRIPTS, "scripts/resolve-dev-artifact-chain.py",
                        types.SimpleNamespace(disposition_lines=limited))
    verdict = None
    for attempts in range(1, 6):  # each attempt has room for two computations
        budget["left"] = 2
        try:
            verdict = [g for t in tasks for g in gate.disposition(project, t, "commit")]
            break
        except Cut:
            continue
    assert verdict is not None and len(verdict) == 4, "no attempt decided"
    assert attempts == 2 and chain == tasks
