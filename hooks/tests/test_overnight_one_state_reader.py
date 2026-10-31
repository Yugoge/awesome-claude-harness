#!/usr/bin/env python3
"""The overnight state's one reading and one write, its cycle index, and the
cycle contract's one writer (P1b row 13, E13).

- lib/overnight.py `state_verdicts`: each verdict by its base rule (window,
  isolation held, released); `write_state` publishes by rename; `cycle_index`
  reads the session's cycle directories; the script entry the git keystone,
  the policy shim, the launcher and the orchestrator run.
- The cycle contract: written only by the PM TRIAGE handler
  (posttool-subagent-track.py), one path, entries without artifacts; the
  dispatch hook allows steps 2-4 from _STEPS before it exists and refuses a
  wrong role, in every cycle (its step is the checklist the transcript records,
  P1b E7); the collection check validates the dispatch's own obligation.
- The git keystone reads its records through the same function.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
REPO = HOOKS.parent
sys.path.insert(0, str(HOOKS))
from lib import contract_runtime, overnight  # noqa: E402

OVERNIGHT_PY = HOOKS / "lib" / "overnight.py"
SID = "sess-one-reader"


def _iso(delta_minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=delta_minutes)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _record(**fields) -> dict:
    record = {"session_id": SID, "end_time": _iso(60), "current_phase": "exploring",
              "isolation_active_until": _iso(60), "isolation_released_at": None,
              "protected_branch": "main"}
    record.update(fields)
    return record


# --------------------------------------------------------------------------
# state_verdicts: one decision, each verdict by the base's rule for it
# --------------------------------------------------------------------------

@pytest.mark.parametrize("fields, window, held, released", [
    ({}, True, True, False),
    ({"end_time": _iso(-5), "isolation_active_until": _iso(-5)}, False, False, False),
    # current_phase decides the window but never the isolation (round-3 §5).
    ({"current_phase": "completed"}, False, True, False),
    # A malformed window closes the session window and keeps isolation held.
    ({"end_time": "not-a-date", "isolation_active_until": None}, False, True, False),
    ({"end_time": None, "isolation_active_until": None}, False, True, False),
    # The owner's /stop: end_time past, completed, isolation released.
    ({"end_time": _iso(-1), "current_phase": "completed",
      "isolation_active_until": _iso(-1), "isolation_released_at": _iso(0)},
     False, False, True),
])
def test_state_verdicts_rules(fields, window, held, released):
    verdicts = overnight.state_verdicts(_record(**fields))
    assert (verdicts.window_live, verdicts.isolation_held, verdicts.released) == (
        window, held, released)


def test_state_verdicts_of_no_record_are_all_false():
    assert overnight.state_verdicts(None)[:3] == (False, False, False)


def test_read_state_refuses_empty_and_non_object(tmp_path):
    empty = tmp_path / "overnight-state-a.json"
    empty.write_text("")
    listed = tmp_path / "overnight-state-b.json"
    listed.write_text("[]")
    assert overnight.read_state(empty) is None
    assert overnight.read_state(listed) is None


def test_session_state_binds_file_name_and_session_id(tmp_path):
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / f"overnight-state-{SID}.json").write_text(json.dumps(_record()))
    (claude / "overnight-state-other.json").write_text(json.dumps(_record()))
    assert overnight.session_state(SID, tmp_path)["session_id"] == SID
    assert overnight.session_state("other", tmp_path) is None


def test_write_state_publishes_by_rename(tmp_path):
    target = tmp_path / f"overnight-state-{SID}.json"
    target.write_text(json.dumps(_record()))
    inode = target.stat().st_ino
    overnight.write_state(target, _record(current_phase="completed"))
    assert json.loads(target.read_text())["current_phase"] == "completed"
    assert target.stat().st_ino != inode
    assert sorted(p.name for p in tmp_path.iterdir()) == [target.name]


# --------------------------------------------------------------------------
# cycle_index: read from the session's directory, no counter in the state
# --------------------------------------------------------------------------

def test_cycle_index_counts_ended_cycles(tmp_path):
    state = _record(worktree_path=str(tmp_path), cycle_count=7)
    assert overnight.cycle_index(state) == 1
    base = tmp_path / "docs" / "dev" / "overnight" / SID
    base.mkdir(parents=True)
    (base / "retro-report-cycle1.json").write_text("{}")
    assert overnight.cycle_index(state) == 2
    (base / "retro-report-cycle3.json").write_text("{}")  # not consecutive: ignored
    assert overnight.cycle_index(state) == 2


# --------------------------------------------------------------------------
# The script entry the shell callers and the launcher run
# --------------------------------------------------------------------------

def _script(*args, **kw):
    return subprocess.run([sys.executable, "-I", str(OVERNIGHT_PY), *args],
                          capture_output=True, text=True, timeout=30, **kw)


def test_script_protected_branches_skips_released_records(tmp_path):
    live = tmp_path / "overnight-state-live.json"
    live.write_text(json.dumps(_record(protected_branch="trunk")))
    gone = tmp_path / "overnight-state-gone.json"
    gone.write_text(json.dumps(_record(protected_branch="old", isolation_released_at=_iso(0))))
    bare = tmp_path / "overnight-state-bare.json"
    bare.write_text(json.dumps({"session_id": "bare"}))
    broken = tmp_path / "overnight-state-broken.json"
    broken.write_text("{")
    result = _script("protected-branches", str(live), str(gone), str(bare), str(broken))
    assert result.returncode == 0
    assert result.stdout.splitlines() == ["trunk"]


def test_script_write_state_and_cycle_index(tmp_path):
    source = tmp_path / "record.tmp"
    source.write_text(json.dumps(_record(worktree_path=str(tmp_path))))
    target = tmp_path / f"overnight-state-{SID}.json"
    assert _script("write-state", str(target), str(source)).returncode == 0
    assert json.loads(target.read_text())["session_id"] == SID
    assert _script("cycle-index", str(target)).stdout.strip() == "1"
    source.write_text("[]")
    assert _script("write-state", str(target), str(source)).returncode == 1


# --------------------------------------------------------------------------
# The cycle contract: one path, rendered from _STEPS, nothing else read
# --------------------------------------------------------------------------

def test_steps_come_from_the_canonical_todo():
    steps = contract_runtime.overnight_steps()
    assert [e["step"] for e in contract_runtime.exploration_calls(steps)] == ["2", "3", "4"]
    assert [label for label, _call in contract_runtime.post_triage_steps(steps)] == [
        "8", "10", "11g", "12", "15", "20"]
    assert contract_runtime.triage_call(steps)["mode"] == "TRIAGE"


def test_load_contract_reads_only_the_working_root_path(tmp_path, monkeypatch):
    project = tmp_path / "project"
    worktree = tmp_path / "worktree"
    (project / ".claude").mkdir(parents=True)
    state = _record(worktree_path=str(worktree))
    (project / ".claude" / f"overnight-state-{SID}.json").write_text(json.dumps(state))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    contract = {"schema_version": 1, "required_calls": []}
    # The retired copies are never read: the mirror and the main-root path.
    (project / ".claude" / f"overnight-contract-{SID}-cycle1.json").write_text(json.dumps(contract))
    main_copy = project / "docs" / "dev" / "overnight" / SID / "cycle-1"
    main_copy.mkdir(parents=True)
    (main_copy / "cycle-contract.json").write_text(json.dumps(contract))
    assert contract_runtime.load_contract(SID, 1) is None
    path = contract_runtime.contract_path(state, 1)
    assert path == worktree / "docs" / "dev" / "overnight" / SID / "cycle-1" / "cycle-contract.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(contract))
    assert contract_runtime.load_contract(SID, 1) == contract


# --------------------------------------------------------------------------
# Hook runs: the dispatch hook (G1), the PM TRIAGE handler, the file check (G3)
# --------------------------------------------------------------------------

@pytest.fixture
def session(tmp_path):
    """An overnight session in place: state, transcript checklist, triage report."""
    project = tmp_path / "project"
    (project / ".claude").mkdir(parents=True)
    state = _record(worktree_path=str(project), addressed_issues=[])
    (project / ".claude" / f"overnight-state-{SID}.json").write_text(json.dumps(state))
    return project


_LABELS = ("1", "2", "3", "4", "8", "10", "11g", "12", "15", "20")


def _todos(label: str | None, done: str = "") -> list:
    """The checklist with ``label`` in progress, every step before it (or
    every step, with done="all") completed."""
    out, before = [], True
    for n in _LABELS:
        before = before and n != label
        status = "completed" if done == "all" or (before and label) else "pending"
        out.append({"content": f"Step {n}: x", "activeForm": f"Step {n}",
                    "status": "in_progress" if n == label else status})
    return out


def _bookmark(project: Path, label: str, *cycles: list) -> None:
    """The session transcript: /dev-overnight, then its TodoWrites (``cycles``
    earlier lists first), ending with ``label`` in progress."""
    records = [{"type": "user", "message": {"role": "user", "content": "/dev-overnight 2h"}}]
    for n, todos in enumerate([_todos(None), *cycles, _todos(label)]):
        records.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": f"tw{n}", "name": "TodoWrite", "input": {"todos": todos}}]}})
        records.append({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"tw{n}", "content": "ok"}]}})
    (project / "transcript.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))


def _run(hook: str, project: Path, payload: dict):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project)}
    payload = {"session_id": SID, "tool_name": "Agent",
               "transcript_path": str(project / "transcript.jsonl"), **payload}
    return subprocess.run([sys.executable, str(HOOKS / hook)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, cwd=str(project), timeout=60)


def _agent(role: str, prompt: str) -> dict:
    return {"tool_input": {"subagent_type": role, "prompt": prompt, "description": "x"}}


def _triage_report(project: Path, cycle: int, fixes: int) -> None:
    base = project / "docs" / "dev" / "overnight" / SID
    base.mkdir(parents=True, exist_ok=True)
    issues = [{"triage_index": i, "pipeline_recommendation": "fix", "description": f"d{i}",
               "location": f"l{i}"} for i in range(fixes)]
    issues.append({"triage_index": fixes, "pipeline_recommendation": "defer",
                   "description": "later", "location": "x"})
    (base / f"triage-report-cycle{cycle}.json").write_text(json.dumps(
        {"issues": issues, "pipeline_order": list(range(fixes + 1))}))


def test_exploration_steps_pass_and_a_wrong_role_is_refused(session):
    _bookmark(session, "2")
    assert _run("pretool-subagent-enforce.py", session, _agent("pm", "PM_MODE: PLAN")).returncode == 0
    refused = _run("pretool-subagent-enforce.py", session, _agent("dev", "PM_MODE: PLAN"))
    assert refused.returncode == 2
    assert "role mismatch on step '2'" in refused.stderr
    _bookmark(session, "3")
    assert _run("pretool-subagent-enforce.py", session, _agent("architect", "scan")).returncode == 0
    _bookmark(session, "8")
    before_triage = _run("pretool-subagent-enforce.py", session, _agent("ba", "analyse"))
    assert before_triage.returncode == 2 and "Case A" in before_triage.stderr


def test_a_wrong_role_is_refused_in_the_second_cycle_too(session):
    """The cycle-1 checklist all completed, then reset for cycle 2: the step
    is still read, so the dispatch check keeps refusing a wrong role."""
    retro = session / "docs" / "dev" / "overnight" / SID
    retro.mkdir(parents=True)
    (retro / "retro-report-cycle1.json").write_text("{}")
    assert overnight.cycle_index(json.loads(
        (session / ".claude" / f"overnight-state-{SID}.json").read_text())) == 2
    _bookmark(session, "2", _todos("20"), _todos(None, done="all"), _todos(None))
    assert _run("pretool-subagent-enforce.py", session, _agent("pm", "PM_MODE: PLAN")).returncode == 0
    refused = _run("pretool-subagent-enforce.py", session, _agent("dev", "PM_MODE: PLAN"))
    assert refused.returncode == 2
    assert "role mismatch on step '2'" in refused.stderr


def test_triage_handler_writes_the_contract_and_the_dispatch_hook_reads_it(session):
    _triage_report(session, 1, fixes=2)
    written = _run("posttool-subagent-track.py", session, _agent("pm", "PM_MODE: TRIAGE"))
    assert written.returncode == 0, written.stderr
    path = session / "docs" / "dev" / "overnight" / SID / "cycle-1" / "cycle-contract.json"
    contract = json.loads(path.read_text())
    assert [(c["step"], c["role"], c["mode"]) for c in contract["required_calls"]] == [
        ("8", "ba", None), ("8", "ba", None), ("10", "qa", None), ("10", "qa", None),
        ("11g", "graphify", None), ("11g", "graphify", None),
        ("12", "dev", None), ("12", "dev", None), ("15", "qa", None), ("15", "qa", None),
        ("20", "pm", "RETRO")]
    import jsonschema
    jsonschema.validate(contract, json.loads((REPO / "schemas" / "cycle-contract.v1.json").read_text()))
    _bookmark(session, "8")
    assert _run("pretool-subagent-enforce.py", session, _agent("ba", "analyse")).returncode == 0
    assert _run("pretool-subagent-enforce.py", session, _agent("qa", "check")).returncode == 2
    # Another dispatch writes nothing; a re-run TRIAGE re-renders the same path.
    path.unlink()
    assert _run("posttool-subagent-track.py", session, _agent("pm", "PM_MODE: PLAN")).returncode == 0
    assert not path.exists()


def test_triage_handler_writes_nothing_without_a_triage_report(session):
    result = _run("posttool-subagent-track.py", session, _agent("pm", "PM_MODE: TRIAGE"))
    assert result.returncode == 0
    assert not (session / "docs" / "dev" / "overnight" / SID / "cycle-1").exists()


def _dev_dispatch(task_id: str) -> dict:
    obligation = {
        "task_id": task_id, "lane": None, "lane_set": None, "role": "dev",
        "pipeline": "dev-overnight", "profile": "overnight", "dispatched_at": _iso(0),
        "artifacts": [{"kind": "json", "path": f"docs/dev/dev-report-{task_id}.json",
                       "schema": "dev-report.v2", "identity": {"task_id": task_id}}],
    }
    return _agent("dev", f'implement\n<obligation v="1">{json.dumps(obligation)}</obligation>')


def test_collection_checks_the_dispatch_obligation(session):
    task_id = "20261028-010101-0"
    dispatch = _dev_dispatch(task_id)
    # No contract yet: nothing is contracted, nothing is checked.
    assert _run("posttool-overnight-file-check.py", session, dispatch).returncode == 0
    _triage_report(session, 1, fixes=1)
    _run("posttool-subagent-track.py", session, _agent("pm", "PM_MODE: TRIAGE"))
    missing = _run("posttool-overnight-file-check.py", session, dispatch)
    assert missing.returncode == 2 and "missing" in missing.stderr
    report = session / "docs" / "dev" / f"dev-report-{task_id}.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"task_id": task_id, "report_version": 2,
                                  "dev": {"status": "half-done"}}))
    invalid = _run("posttool-overnight-file-check.py", session, dispatch)
    assert invalid.returncode == 2 and "dev-report" in invalid.stderr
    # A dispatch that carries no obligation declares nothing to check.
    assert _run("posttool-overnight-file-check.py", session, _agent("dev", "x")).returncode == 0


# --------------------------------------------------------------------------
# The git keystone reads its records through the same function
# --------------------------------------------------------------------------

def _git(*args, cwd, env=None):
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True,
                          text=True, timeout=30)


@pytest.fixture
def keystone_repo(tmp_path):
    """A repository whose keystone is the harness's, with a linked worktree on
    `work` (the main worktree's own HEAD is never the actor's to move)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp_path)}
    for args in (("init", "-q", "-b", "main"), ("config", "user.name", "t"),
                 ("config", "user.email", "t@example.invalid"),
                 ("commit", "-q", "--allow-empty", "-m", "init"),
                 ("worktree", "add", "-q", "-b", "work", str(tmp_path / "wt"))):
        assert _git(*args, cwd=repo, env=env).returncode == 0
    shutil.copy(HOOKS / "git-keystone" / "reference-transaction",
                repo / ".git" / "hooks" / "reference-transaction")
    (repo / ".claude").mkdir()
    return repo, tmp_path / "wt", env


def _as_actor(env: dict, harness: Path) -> dict:
    return {**env, "CLAUDE_OVERNIGHT_ACTOR": "1", "CLAUDE_HOME": str(harness)}


def test_keystone_resolves_the_protected_branch_through_the_lib(keystone_repo, tmp_path):
    repo, wt, env = keystone_repo
    actor = _as_actor(env, REPO)
    state = repo / ".claude" / "overnight-state-k.json"
    state.write_text(json.dumps(_record(protected_branch="main")))
    assert _git("commit", "-q", "--allow-empty", "-m", "x", cwd=wt, env=actor).returncode == 0
    denied = _git("update-ref", "refs/heads/main", "HEAD", cwd=wt, env=actor)
    assert denied.returncode != 0 and "reason=branch_protected" in denied.stderr
    # A released record contributes nothing: the set is empty, so it fails closed.
    state.write_text(json.dumps(_record(protected_branch="main", isolation_released_at=_iso(0))))
    released = _git("commit", "-q", "--allow-empty", "-m", "y", cwd=wt, env=actor)
    assert released.returncode != 0 and "reason=unresolved_protected_branch" in released.stderr
    # When the function cannot run, nothing is contributed either.
    state.write_text(json.dumps(_record(protected_branch="main")))
    nowhere = _as_actor(env, tmp_path / "no-harness")
    blind = _git("commit", "-q", "--allow-empty", "-m", "z", cwd=wt, env=nowhere)
    assert blind.returncode != 0 and "reason=unresolved_protected_branch" in blind.stderr


# --------------------------------------------------------------------------
# The record's writers: the launcher at launch, the owner's /stop
# --------------------------------------------------------------------------

def test_launcher_record_carries_no_cycle_counter(tmp_path):
    repo = tmp_path / "repo"
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp_path)}
    env.pop("CLAUDE_OVERNIGHT_ACTOR", None)
    for args in (("init", "-q", "-b", "main", str(repo)),):
        assert _git(*args, cwd=tmp_path, env=env).returncode == 0
    for args in (("config", "user.name", "t"), ("config", "user.email", "t@example.invalid"),
                 ("commit", "-q", "--allow-empty", "-m", "init"),
                 ("update-ref", "refs/remotes/origin/main", "HEAD"),
                 ("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main"),
                 ("checkout", "-q", "-b", "work")):
        assert _git(*args, cwd=repo, env=env).returncode == 0
    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "create-overnight-state.sh"), "--emit-record-only",
         "--session-id", SID, "--project-dir", str(repo)],
        capture_output=True, text=True, env=env, cwd=str(repo), timeout=120)
    assert result.returncode == 0, result.stderr
    record = json.loads(result.stdout)
    assert record["protected_branch"] == "main"
    assert not {"cycle_count", "cycle_id", "cycle_contract_path"} & set(record)


def test_stop_writes_through_the_launchers_write_path(tmp_path, monkeypatch):
    import importlib.util
    claude = tmp_path / ".claude"
    claude.mkdir()
    state_file = claude / f"overnight-state-{SID}.json"
    state_file.write_text(json.dumps(_record()))
    inode = state_file.stat().st_ino
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    spec = importlib.util.spec_from_file_location("break_lock_one_writer", REPO / "scripts" / "break-overnight-lock.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    past = _iso(-1)
    assert module._backdate(state_file, past, release_isolation=True) == SID
    after = json.loads(state_file.read_text())
    assert (after["end_time"], after["current_phase"], after["isolation_active_until"]) == (
        past, "completed", past)
    assert after["isolation_released_at"]
    assert state_file.stat().st_ino != inode
    assert sorted(p.name for p in claude.iterdir()) == [state_file.name]
    verdicts = overnight.state_verdicts(after)
    assert (verdicts.window_live, verdicts.isolation_held, verdicts.released) == (False, False, True)
