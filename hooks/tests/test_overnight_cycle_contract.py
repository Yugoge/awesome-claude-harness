#!/usr/bin/env python3
"""The /dev-overnight cycle contract with no seed (P2 R12, R13; acceptance A11).

- No seed file: the exploration (steps 2-4) passes the dispatch hook in cycles
  1 and 2, a wrong role at step 2 is refused.
- The PM TRIAGE handler renders `_STEPS` labels and each compliant re-dispatch
  (BA at steps 9 and 11, dev at 13, dev and QA at 17); no entry names a schema,
  a path or max_retries; the contract validates against cycle-contract.v1.json.
- A contract that holds no JSON object is Case M (exit 2) at dispatch and at
  collection, the PM TRIAGE dispatch still passes and its return replaces it;
  a contract that lists calls (an old-prose one) stays byte for byte.
- A session rooted in a linked worktree or a fresh clone finds the main
  root's state and its own working root's contract.
- E1 for the dev and the QA pair: a report shaped like the agents/dev.md and
  agents/qa.md templates passes the collection check and G2; one invalid
  against its obligation's schema is refused by both.
- A producer question (BA at Step 8, dev at Step 12) is decided at collection
  by G2's one rule: fresh and valid it stands in, invalid it is refused, stale
  it stands in for nothing.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
REPO = HOOKS.parent
sys.path.insert(0, str(HOOKS))
from lib import contract_runtime  # noqa: E402

SID = "sess-p2-contract"
TASK = "20261101-010101-0"
LABELS = [label for label, _call in contract_runtime.overnight_steps()]
GIT_ENV = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def _iso(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(*args, cwd):
    result = subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, capture_output=True,
                            text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return result


@pytest.fixture
def main_root(tmp_path):
    root = tmp_path / "main"
    root.mkdir()
    _git("init", "-q", "-b", "trunk", cwd=root)
    _git("commit", "-q", "--allow-empty", "-m", "init", cwd=root)
    (root / ".claude").mkdir()
    return root


def _session(main: Path, working: Path) -> Path:
    """The state record at the main root, naming ``working`` as the working root."""
    record = {"session_id": SID, "end_time": _iso(60), "current_phase": "exploring",
              "isolation_active_until": _iso(60), "isolation_released_at": None,
              "protected_branch": "trunk", "main_root": str(main),
              "worktree_path": str(working), "addressed_issues": []}
    (main / ".claude" / f"overnight-state-{SID}.json").write_text(json.dumps(record))
    return working


def _cycle_dir(working: Path, cycle: int = 1) -> Path:
    return working / "docs" / "dev" / "overnight" / SID / f"cycle-{cycle}"


def _checklist(working: Path, label: str, cycles: int = 1) -> Path:
    """The transcript: /dev-overnight, then a checklist per cycle, the last with
    ``label`` in progress and every step before it completed."""
    def todos(current, done_all=False):
        out, before = [], True
        for n in LABELS:
            before = before and n != current
            status = "completed" if done_all or (before and current) else "pending"
            out.append({"content": f"Step {n}: x", "activeForm": f"Step {n}",
                        "status": "in_progress" if n == current else status})
        return out
    lists = [todos(None)]
    for _ in range(cycles - 1):
        lists += [todos(LABELS[-1]), todos(None, done_all=True), todos(None)]
    lists.append(todos(label))
    records = [{"type": "user", "message": {"role": "user", "content": "/dev-overnight 2h"}}]
    for n, item in enumerate(lists):
        records.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": f"tw{n}", "name": "TodoWrite", "input": {"todos": item}}]}})
        records.append({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"tw{n}", "content": "ok"}]}})
    path = working / "transcript.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def _run(hook: str, working: Path, payload: dict, **env):
    """One hook run as the session runs it: its project dir and cwd the working root."""
    payload = {"session_id": SID, "tool_name": "Agent", "cwd": str(working),
               "transcript_path": str(working / "transcript.jsonl"), **payload}
    return subprocess.run([sys.executable, str(HOOKS / hook)], input=json.dumps(payload),
                          capture_output=True, text=True, cwd=str(working), timeout=60,
                          env={**os.environ, "CLAUDE_PROJECT_DIR": str(working), **env})


def _agent(role: str, prompt: str = "x") -> dict:
    return {"tool_input": {"subagent_type": role, "prompt": prompt, "description": "x"}}


def _enforce(working: Path, label: str, role: str, prompt: str = "x", cycles: int = 1):
    _checklist(working, label, cycles)
    return _run("pretool-subagent-enforce.py", working, _agent(role, prompt))


def _triage(working: Path, cycle: int = 1, fixes: int = 2):
    """PM TRIAGE returns: its report on disk, then the handler's run."""
    base = working / "docs" / "dev" / "overnight" / SID
    base.mkdir(parents=True, exist_ok=True)
    issues = [{"triage_index": i, "pipeline_recommendation": "fix", "description": f"d{i}",
               "location": f"l{i}"} for i in range(fixes)]
    (base / f"triage-report-cycle{cycle}.json").write_text(
        json.dumps({"issues": issues, "pipeline_order": list(range(fixes))}))
    return _run("posttool-subagent-track.py", working, _agent("pm", "PM_MODE: TRIAGE"))


# --------------------------------------------------------------------------
# No seed: steps 2-4 from _STEPS, in every cycle
# --------------------------------------------------------------------------

def test_without_a_seed_the_exploration_passes_in_cycles_one_and_two(main_root):
    working = _session(main_root, main_root)
    for cycles in (1, 2):
        if cycles == 2:
            (working / "docs" / "dev" / "overnight" / SID).mkdir(parents=True, exist_ok=True)
            (working / "docs" / "dev" / "overnight" / SID / "retro-report-cycle1.json").write_text("{}")
        assert not _cycle_dir(working, cycles).exists()
        assert _enforce(working, "2", "pm", "PM_MODE: PLAN", cycles).returncode == 0
        assert _enforce(working, "3", "security-auditor", "scan", cycles).returncode == 0
        assert _enforce(working, "4", "pm", "PM_MODE: TRIAGE", cycles).returncode == 0
        refused = _enforce(working, "2", "dev", "PM_MODE: PLAN", cycles)
        assert refused.returncode == 2 and "role mismatch on step '2'" in refused.stderr


# --------------------------------------------------------------------------
# The rendered contract
# --------------------------------------------------------------------------

def test_the_rendered_contract_and_its_re_dispatches(main_root):
    import jsonschema
    working = _session(main_root, main_root)
    assert _triage(working).returncode == 0
    contract = json.loads((_cycle_dir(working) / "cycle-contract.json").read_text())
    jsonschema.validate(contract, json.loads((REPO / "schemas" / "cycle-contract.v1.json").read_text()))
    entries = contract["required_calls"]
    assert {e["step"] for e in entries} == {"8", "9", "10", "11", "11g", "12", "13", "15", "17", "20"}
    assert {e["step"] for e in entries} <= set(LABELS)
    for entry in entries:
        assert set(entry) == {"step", "role", "mode", "pipeline_id"}
    assert [e["role"] for e in entries if e["step"] == "17"] == ["dev", "dev", "qa", "qa"]
    # A compliant re-dispatch passes at its own step; another role there is refused.
    for label, role in (("9", "ba"), ("11", "ba"), ("13", "dev"), ("17", "dev"), ("17", "qa")):
        result = _enforce(working, label, role)
        assert result.returncode == 0, (label, role, result.stderr)
    for label, role in (("11", "dev"), ("17", "ba")):
        refused = _enforce(working, label, role)
        assert refused.returncode == 2 and "Case B" in refused.stderr, (label, role)


# --------------------------------------------------------------------------
# A contract that holds no JSON object; a contract already there
# --------------------------------------------------------------------------

def _dispatch(role: str, schema: str, report: str) -> dict:
    """An overnight dev or QA dispatch whose obligation declares its v2 report."""
    identity = {"task_id": TASK} if role == "dev" else {"task_id": TASK, "request_id": TASK}
    obligation = {"task_id": TASK, "lane": None, "lane_set": None, "role": role,
                  "pipeline": "dev-overnight",
                  "profile": "overnight" if role == "dev" else "final_verification",
                  "dispatched_at": _iso(0),
                  "artifacts": [{"kind": "json", "path": report, "schema": schema, "identity": identity}]}
    return _agent(role, f'You are the {role} subagent.\n<obligation v="1">{json.dumps(obligation)}</obligation>')


DEV = ("dev", "dev-report.v2", f"docs/dev/dev-report-{TASK}.json")
QA = ("qa", "qa-report.v2", f"docs/dev/qa-report-{TASK}.json")


@pytest.mark.parametrize("text", ["{not json", "[]", '"a string"'])
def test_a_contract_that_holds_no_json_object_is_case_m(main_root, text):
    working = _session(main_root, main_root)
    path = _cycle_dir(working) / "cycle-contract.json"
    path.parent.mkdir(parents=True)
    path.write_text(text)
    refused = _enforce(working, "8", "ba")
    assert refused.returncode == 2 and "Case M" in refused.stderr
    collected = _run("posttool-overnight-file-check.py", working, _dispatch(*DEV))
    assert collected.returncode == 2 and "Case M" in collected.stderr and str(path) in collected.stderr
    # The way out: PM TRIAGE passes, and its return replaces the file with a rendered contract.
    assert _enforce(working, "4", "pm", "PM_MODE: TRIAGE").returncode == 0
    assert _triage(working).returncode == 0
    assert json.loads(path.read_text())["required_calls"]
    assert _enforce(working, "8", "ba").returncode == 0


def test_a_contract_already_there_is_kept_and_a_seed_is_replaced(main_root):
    working = _session(main_root, main_root)
    path = _cycle_dir(working) / "cycle-contract.json"
    path.parent.mkdir(parents=True)
    # What the prose before P1b had the orchestrator write: kept byte for byte, and read.
    old = json.dumps({"schema_version": 1, "session_id": SID, "cycle_id": 1, "required_calls": [
        {"step": "8", "role": "ba", "pipeline_id": None, "schema_name": None, "max_retries": 3},
        {"step": "12", "role": "dev", "pipeline_id": None, "schema_name": "dev-report.v1",
         "max_retries": 3}]}, indent=2)
    path.write_text(old)
    kept = _triage(working)
    assert kept.returncode == 0 and "CYCLE CONTRACT KEPT" in kept.stdout
    assert path.read_text() == old
    assert _enforce(working, "8", "ba").returncode == 0
    assert _enforce(working, "8", "qa").returncode == 2
    # The launcher's seed before P1b lists no call: the handler renders over it.
    path.write_text(json.dumps({"schema_version": 1, "required_calls": [], "pipelines": {}}))
    assert _triage(working).returncode == 0
    assert len(json.loads(path.read_text())["required_calls"]) == 21


# --------------------------------------------------------------------------
# Worktree-rooted and fresh-clone sessions
# --------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["registered_worktree", "fresh_clone_checkout"])
def test_a_session_rooted_in_its_working_root_finds_the_main_root_state(main_root, kind):
    if kind == "registered_worktree":
        working = main_root / ".claude" / "worktrees" / "overnight-1"
        _git("worktree", "add", "-q", "-b", "overnight-1", str(working), cwd=main_root)
    else:
        working = main_root / ".claude" / "overnight-fresh-clones" / "overnight-1"
        _git("clone", "-q", "--local", str(main_root / ".git"), str(working), cwd=main_root)
    _session(main_root, working)
    assert _triage(working).returncode == 0
    assert (_cycle_dir(working) / "cycle-contract.json").is_file()
    assert not _cycle_dir(main_root).exists()
    # The dispatch hook reads that contract: the step-8 BA passes, a QA there is refused.
    assert _enforce(working, "8", "ba").returncode == 0
    assert _enforce(working, "8", "qa").returncode == 2
    _checklist(working, "12")
    missing = _run("posttool-overnight-file-check.py", working, _dispatch(*DEV))
    assert missing.returncode == 2 and DEV[2] in missing.stderr


# --------------------------------------------------------------------------
# E1: template-shaped v2 reports, the collection check and G2
# --------------------------------------------------------------------------

def _template_report(agent_file: str) -> dict:
    """The report an agent file's v2 template describes, its placeholders filled."""
    text = (REPO / "agents" / agent_file).read_text()
    block = next(b for b in re.findall(r"```json\n(.*?)```", text, re.S) if '"report_version": 2' in b)
    for pattern, value in ((r"<integer>", "1"), (r"\btrue\|false\b", "true"),
                           (r'"L1"( \| "L\d")+', '"L1"'), (r"<boolean[^>]*>", "false"),
                           (r"\[[^\]]*\] or \[\]", "[]"), (r'"<[^"]*>" or null', "null")):
        block = re.sub(pattern, value, block)

    def first_option(value):
        if isinstance(value, dict):
            return {k: first_option(v) for k, v in value.items()}
        if isinstance(value, list):
            return [first_option(v) for v in value]
        if isinstance(value, str) and re.fullmatch(r"[a-z_-]+( ?\| ?[a-z_-]+)+", value):
            return value.split("|")[0].strip()
        return value
    report = first_option(json.loads(block))
    report["task_id"] = report["request_id"] = TASK
    return report


def _g2(project: Path, home: Path, role: str, prompt: str):
    """G2 at the producer's stop, armed: the producer registered, its dispatch in the
    transcript store the hook reads."""
    agent_id = f"agent-{role}-e1"
    registry = project / ".claude" / "dev-registry"
    registry.mkdir(parents=True, exist_ok=True)
    (registry / "agent-index.json").write_text(json.dumps(
        {agent_id: {"agent_type": role, "dev_session_id": f"dev-overnight-{TASK}"}}))
    subagents = (home / ".claude" / "projects" / str(project.resolve()).replace("/", "-")
                 / SID / "subagents")
    subagents.mkdir(parents=True, exist_ok=True)
    (subagents / f"agent-{agent_id}.jsonl").write_text(
        json.dumps({"type": "user", "message": {"content": prompt}}) + "\n")
    (subagents / f"agent-{agent_id}.meta.json").write_text(json.dumps({"toolUseId": "tu-e1"}))
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project), "HOME": str(home),
           "CLAUDE_CONFIG_DIR": str(home / ".claude"), "CLAUDE_OBLIGATION_STOPGATE": "block"}
    return subprocess.run([sys.executable, str(HOOKS / "subagentstop-artifact-contract-enforce.py")],
                          input=json.dumps({"agent_id": agent_id, "session_id": SID}),
                          capture_output=True, text=True, env=env, cwd=str(project), timeout=60)


@pytest.mark.parametrize("role, schema, report, agent_file, label", [
    (*DEV, "dev.md", "12"), (*QA, "qa.md", "15")])
def test_e1_template_shaped_reports_pass_and_invalid_ones_stop_at_g2(
        main_root, tmp_path, role, schema, report, agent_file, label):
    working = _session(main_root, main_root)
    assert _triage(working).returncode == 0
    _checklist(working, label)
    dispatch = _dispatch(role, schema, report)
    prompt = dispatch["tool_input"]["prompt"]
    assert _run("pretool-subagent-enforce.py", working, dispatch).returncode == 0
    path = working / report
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_template_report(agent_file)))
    passed = _run("posttool-overnight-file-check.py", working, dispatch)
    assert passed.returncode == 0, passed.stderr
    assert _g2(working, tmp_path / "home", role, prompt).returncode == 0
    invalid = _template_report(agent_file)
    invalid[role]["status"] = "half-done"
    path.write_text(json.dumps(invalid))
    stopped = _g2(working, tmp_path / "home", role, prompt)
    assert stopped.returncode == 2 and "OBLIGATION_STOPGATE_BLOCKED" in stopped.stderr
    assert report in stopped.stderr
    refused = _run("posttool-overnight-file-check.py", working, dispatch)
    assert refused.returncode == 2 and report in refused.stderr


# --------------------------------------------------------------------------
# R12: a producer question at collection, by G2's one rule
# --------------------------------------------------------------------------

def _ba_dispatch() -> dict:
    """An overnight Step 8 BA dispatch whose obligation declares its context and ticket."""
    obligation = {"task_id": TASK, "lane": None, "lane_set": None, "role": "ba", "pipeline": "dev-overnight",
                  "profile": "overnight", "dispatched_at": _iso(0), "artifacts": [
                      {"kind": "json", "path": f"docs/dev/context-{TASK}.json", "schema": "context.v1",
                       "identity": {"task_id": TASK}},
                      {"kind": "markdown", "path": f"docs/dev/ticket-{TASK}.md", "identity_anchor": TASK}]}
    return _agent("ba", f'You are the ba subagent.\n<obligation v="1">{json.dumps(obligation)}</obligation>')


@pytest.mark.parametrize("role, label, declared", [
    ("ba", "8", f"docs/dev/context-{TASK}.json"), ("dev", "12", DEV[2])])
def test_a_producer_question_is_decided_at_collection_as_at_g2(main_root, tmp_path, role, label, declared):
    """A fresh, valid question the dispatch's role wrote in place of its report stands in for
    the declared artifacts at collection and at G2; an invalid one is refused by both, naming
    why; a stale one stands in for nothing, so both name the declared artifact it lacks."""
    working = _session(main_root, main_root)
    assert _triage(working).returncode == 0
    _checklist(working, label)
    dispatch = _ba_dispatch() if role == "ba" else _dispatch(*DEV)
    prompt = dispatch["tool_input"]["prompt"]
    question = working / f"docs/dev/producer-question-{TASK}-{role}.json"
    question.parent.mkdir(parents=True, exist_ok=True)
    record = {"task_id": TASK, "role": role, "need": "whether bool counts as a number",
              "options": [{"label": "accept", "description": "a"}, {"label": "reject", "description": "r"}],
              "default": "reject", "why": "the request does not say"}
    question.write_text(json.dumps(record))
    collected = _run("posttool-overnight-file-check.py", working, dispatch)
    assert collected.returncode == 0 and "producer question valid" in collected.stdout, collected.stderr
    assert _g2(working, tmp_path / "home", role, prompt).returncode == 0
    question.write_text(json.dumps(dict(record, default="maybe")))
    for refused in (_run("posttool-overnight-file-check.py", working, dispatch),
                    _g2(working, tmp_path / "home", role, prompt)):
        assert refused.returncode == 2, refused.stderr
        assert f"{question.relative_to(working)}: " in refused.stderr
        assert "default 'maybe' is not one of the option labels" in refused.stderr
    question.write_text(json.dumps(record))
    earlier = datetime.now(timezone.utc).timestamp() - 3600
    os.utime(question, (earlier, earlier))
    for refused in (_run("posttool-overnight-file-check.py", working, dispatch),
                    _g2(working, tmp_path / "home", role, prompt)):
        assert refused.returncode == 2 and declared in refused.stderr, refused.stderr
        assert "producer-question" not in refused.stderr
