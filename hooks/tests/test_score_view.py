"""P13-3 (D29, D32): what a score shows at a dispatch and what a low one costs.

hooks/lib/score_log.py renders the views (dispatch view, main line) and hooks/lib/score_view.py reads the log for the hooks:
hooks/subagentstart-record.py (run here as a process), the Stop gate's extra-round gaps and the Codex gate's forced debate."""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from hooks.lib import obligation, score_log, score_view  # noqa: E402

HOOK = REPO / "hooks" / "subagentstart-record.py"
CODEX_HOOK = REPO / "hooks" / "subagentstop-codex-enforce.py"
PROJECT, END = "a" * 12, "2999-01-01T00:00:00Z"
TASK = "20261101-100000"
COST = {role: text for role, text, _ in score_log.CONSEQUENCES}  # what a low record costs each role, as the agent is told
RANKS = [(-1, "Disgraced"), (0, "Apprentice"), (20, "Apprentice"), (21, "Journeyman"), (40, "Journeyman"), (41, "Skilled Craftsman"),
         (60, "Skilled Craftsman"), (61, "Senior Craftsman"), (80, "Senior Craftsman"), (81, "Master"), (100, "Master")]


def _event(role, points, why="edge case not tested", n=1, task=TASK, project=PROJECT) -> dict:
    return {"kind": "event", "ts": f"2026-11-01T00:00:{n:02d}Z", "project": project, "task_id": task, "role": role, "event": "qa_fail" if points < 0 else "qa_first_pass",
            "points": points, "key": f"{role}:{n}", "why": why, "ref": ""}


def _at(role, value, **kw) -> list:
    """Rows that put the role at the score (from the start of 50, capped at 100)."""
    return [_event(role, value - 50, **kw)]


def _view(rows, role="dev") -> str:
    return score_log.render_dispatch_line(rows, role, PROJECT, END)


# ---------------------------------------------------------------- the dispatch view (C-A2)

@pytest.mark.parametrize(("value", "rank"), RANKS)
def test_each_score_lands_in_its_rank_with_that_ranks_reminder(value: int, rank: str) -> None:
    text = _view(_at("dev", value))
    lines = text.split("\n")
    assert f"{value} [Rank: {rank}," in lines[0] and score_log.REMINDERS[rank] in lines[-1]
    assert len(lines) <= 3 and len(text.encode()) <= 400
    assert [r for r in score_log.REMINDERS if r != rank and score_log.REMINDERS[r] in text] == []


def test_the_six_ranks_have_six_different_reminders() -> None:
    assert [name for name, *_ in score_log.RANKS] == list(score_log.REMINDERS) and len(set(score_log.REMINDERS.values())) == 6


def test_an_identity_with_no_rows_gets_one_line() -> None:
    text = _view([], "qa")
    assert "\n" not in text and "No record yet for qa" in text and "Skilled Craftsman" in text and score_log.REMINDERS["Skilled Craftsman"] in text
    assert _view(_at("dev", 10, project="b" * 12), "dev") == _view([], "dev")  # another project's rows are no record here


def test_the_view_gives_the_good_facts_and_the_miss_never_a_task_id() -> None:
    rows = [_event("dev", 2, "lane QA passed at the first round", 1), {"kind": "rating", "ts": "2026-11-01T00:00:02Z", "project": PROJECT, "task_id": TASK,
            "rating": 5, "roles": ["dev"], "tool_use_id": "t"}, _event("dev", -6, f"QA failed {TASK}: edge case not tested", 3)]
    text = _view(rows)
    assert "Recent good: the owner rated a cycle 5 stars; lane QA passed at the first round." in text
    assert "Recent miss: QA failed : edge case not tested." in text or "edge case not tested" in text
    assert TASK not in text


@pytest.mark.parametrize("value", [v for v, _ in RANKS])
def test_no_view_threatens(value: int) -> None:
    text = _view(_at("dev", value)).lower()
    assert not any(word in text for word in ("punish", "irreversible", "threat", "penalt"))


def test_the_facts_give_way_first_when_the_400_bytes_are_short() -> None:
    long = "x" * 80
    text = _view([_event("qa", -60, long, 1), _event("qa", 2, long, 2)], "qa")
    assert len(text.encode()) <= 400 and COST["qa"] in text and "[Rank: Disgraced" in text


def test_the_view_of_a_row_without_kind_or_of_a_rating_alone_is_still_one_view() -> None:
    legacy = {"ts": "2026-11-01T00:00:01Z", "agent": "dev", "event": "x", "delta": -40, "new_score": 10}
    assert _view([legacy]) == _view([])  # a row without kind is read and never scored
    rated = [{"kind": "rating", "ts": "2026-11-01T00:00:02Z", "project": PROJECT, "task_id": TASK, "rating": 1, "roles": ["dev"], "tool_use_id": "t"}]
    assert "the owner rated a cycle 1-2 stars" in _view(rated) and len(_view(rated).split("\n")) <= 3


# ---------------------------------------------------------------- what a low record costs (D32)

@pytest.mark.parametrize(("value", "low"), [(-1, True), (0, True), (20, True), (21, False), (50, False), (100, False)])
def test_a_record_is_low_in_the_two_lowest_ranks(value: int, low: bool) -> None:
    assert score_log.low(_at("dev", value), "dev", PROJECT, END) is low
    assert (COST["dev"] in _view(_at("dev", value))) is low


def test_the_consequence_is_the_roles_own() -> None:
    assert "independent QA round" in _view(_at("dev", 10), "dev") and "independent QA round" in _view(_at("ba", 10), "ba")
    assert "Codex debate" in _view(_at("qa", 10), "qa") and "Codex" not in _view(_at("dev", 10), "dev")
    assert "QA round" not in _view(_at("graphify", 10), "graphify")  # a role with no consequence gets its reminder alone


def test_climbing_back_ends_the_consequence() -> None:
    rows = _at("dev", 10) + [_event("dev", 15, "lane QA passed at the first round", 5)]
    assert score_log.low(rows, "dev", PROJECT, END) is False and score_log.low(rows, "dev", PROJECT, "2026-11-01T00:00:03Z") is True


def test_the_main_line_names_the_roles_on_notice() -> None:
    rows = _at("dev", 10) + _at("qa", -5)
    line = score_log.render_main_line(rows, PROJECT, END)
    assert line.startswith("Your record (main): 50 [Rank: Skilled Craftsman") and "\n" not in line
    assert "dev: one more independent QA round" in line and "qa: a Codex debate every round" in line and "ba" not in line.split("Low record:")[1].replace("debate", "")
    assert "Low record" not in score_log.render_main_line(_at("dev", 90), PROJECT, END)
    assert "Recent miss: edge case not tested." in score_log.render_main_line(_at("main", 30), PROJECT, END)


# ---------------------------------------------------------------- the SubagentStart hook, run as a process

def _tx(path: Path, command: str | None) -> Path:
    records = [] if command is None else [{"type": "user", "isSidechain": False, "sessionId": "s", "uuid": "u1", "timestamp": "2026-11-01T12:00:00.000Z",
                                           "message": {"role": "user", "content": f"/{command} fix the toy"}}]
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def _start(tmp_path: Path, agent_type: str, command: str | None, rows=(), raw: str | None = None) -> subprocess.CompletedProcess:
    project, config = tmp_path / "project", tmp_path / "cfg"
    project.mkdir(exist_ok=True)
    (config / "logs").mkdir(parents=True, exist_ok=True)
    key = score_log.project_key(project)
    (config / "logs" / "lifecycle.jsonl").write_text("".join(json.dumps({**r, "project": key}) + "\n" for r in rows), encoding="utf-8")
    payload = {"agent_id": "a1", "agent_type": agent_type, "cwd": str(project), "session_id": "s", "transcript_path": str(_tx(tmp_path / "t.jsonl", command))}
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(config), "CLAUDE_PROJECT_DIR": str(project), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, str(HOOK)], input=raw if raw is not None else json.dumps(payload), capture_output=True, text=True, env=env, timeout=60)


def _context(done: subprocess.CompletedProcess) -> str:
    assert done.returncode == 0 and not done.stderr, done.stderr
    return json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"] if done.stdout.strip() else ""


def test_the_hook_prints_the_agents_view_as_start_context(tmp_path: Path) -> None:
    done = _start(tmp_path, "dev", "dev", _at("dev", 38))
    out = json.loads(done.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "SubagentStart" and out["additionalContext"].startswith("Your record (dev, this project): 38 [Rank: Journeyman, 21-40]")
    assert len(out["additionalContext"].split("\n")) <= 3 and len(out["additionalContext"].encode()) <= 400


@pytest.mark.parametrize("command", ["spec", "dev", "redev", "dev-command", "dev-overnight", None])
def test_the_hook_runs_outside_the_close_commit_merge_and_push_spans(tmp_path: Path, command) -> None:
    assert "Your record (qa" in _context(_start(tmp_path, "qa", command, _at("qa", 30)))


@pytest.mark.parametrize("command", ["close", "commit", "merge", "push"])
def test_the_hook_prints_nothing_in_a_close_commit_merge_or_push_span(tmp_path: Path, command: str) -> None:
    assert _context(_start(tmp_path, "qa", command, _at("qa", 30))) == ""


def test_the_hook_prints_nothing_for_an_agent_outside_the_roster_and_nothing_on_an_error(tmp_path: Path) -> None:
    assert _context(_start(tmp_path, "Explore", "dev", _at("qa", 30))) == ""
    for raw in ("", "not json", "{}", json.dumps({"agent_type": "dev"})):
        done = _start(tmp_path, "dev", "dev", raw=raw)
        assert done.returncode == 0 and done.stdout == "" and done.stderr == ""


def test_the_hook_reads_the_record_as_of_the_span_opener(tmp_path: Path) -> None:
    after = _event("dev", -45, n=1)  # earned after the opener (12:00:00): it counts from the next command
    after["ts"] = "2026-11-01T12:00:01Z"
    assert "No record yet for dev" in _context(_start(tmp_path, "dev", "dev", [after]))
    before = dict(after, ts="2026-11-01T11:59:59Z")
    assert "[Rank: Apprentice" in _context(_start(tmp_path, "dev", "dev", [before]))


# ---------------------------------------------------------------- the Stop gate's extra round (D32)

def _span(*dispatches, pipeline="dev"):
    """A span holding ok dispatches (line, role, profile, lane): the shapes extra_round_gaps reads."""
    calls = [(types.SimpleNamespace(line=line, ok=True), {"task_id": TASK + (f"-{lane}" if lane else ""), "lane": lane, "role": role,
                                                          "pipeline": pipeline, "profile": profile}) for line, role, profile, lane in dispatches]
    return types.SimpleNamespace(obligations=lambda: calls)


@pytest.fixture()
def low(monkeypatch):
    def only(*roles):
        monkeypatch.setattr(score_view, "is_low", lambda role, cwd, span: role in roles)
    return only


def test_a_low_dev_owes_a_second_final_verification_after_its_last_dispatch(low) -> None:
    low("dev")
    first = _span((1, "dev", "singular", None), (2, "qa", "final_verification", None))
    assert len(score_view.extra_round_gaps(first, "/p")) == 1 and "owes one more independent final_verification QA dispatch" in score_view.extra_round_gaps(first, "/p")[0]
    assert score_view.extra_round_gaps(_span((1, "dev", "singular", None), (2, "qa", "final_verification", None), (3, "qa", "final_verification", None)), "/p") == []
    assert score_view.extra_round_gaps(_span((1, "dev", "singular", None)), "/p") == []  # no QA yet: the chain's own gap, not this one
    # a QA before the dev's last dispatch is the earlier round: both rounds run again after it
    again = _span((1, "dev", "singular", None), (2, "qa", "final_verification", None), (3, "qa", "final_verification", None), (4, "dev", "singular", None),
                  (5, "qa", "final_verification", None))
    assert len(score_view.extra_round_gaps(again, "/p")) == 1


@pytest.mark.parametrize(("pipeline", "owes"), [("dev", 1), ("dev-command", 1), ("dev-overnight", 1), ("close", 0), ("commit", 0)])
def test_the_extra_round_is_owed_in_the_dev_family_pipelines_only(low, pipeline: str, owes: int) -> None:
    low("dev")
    span = _span((1, "dev", "singular", None), (2, "qa", "final_verification", None), pipeline=pipeline)
    assert len(score_view.extra_round_gaps(span, "/p")) == owes


def test_a_low_ba_owes_a_second_ba_validation_and_only_its_own_profile_counts(low) -> None:
    low("ba")
    one = _span((1, "ba", "singular", None), (2, "qa", "ba_validation", None), (3, "qa", "final_verification", None))
    assert "ba_validation" in score_view.extra_round_gaps(one, "/p")[0]
    assert score_view.extra_round_gaps(_span((1, "ba", "singular", None), (2, "qa", "ba_validation", None), (3, "qa", "ba_validation", None)), "/p") == []
    panel = _span((1, "ba", "singular", None), (2, "qa", "ba_validation", None), (3, "ba", "singular", None), (4, "qa", "ba_validation", None), (5, "qa", "ba_validation", None))
    assert score_view.extra_round_gaps(panel, "/p") == []  # the panel QA before the final BA is not a round of the final context


def test_each_lane_owes_its_own_second_round_and_a_record_that_is_not_low_owes_none(low) -> None:
    low("dev")
    lanes = _span((1, "dev", "fanout-lane", "l1"), (2, "dev", "fanout-lane", "l2"), (3, "qa", "final_verification", "l1"), (4, "qa", "final_verification", "l2"),
                  (5, "qa", "final_verification", "l1"))
    assert [("l2" in gap) for gap in score_view.extra_round_gaps(lanes, "/p")] == [True]
    low()
    assert score_view.extra_round_gaps(lanes, "/p") == []


def test_a_dispatch_that_did_not_return_ok_is_no_round(low) -> None:
    low("dev")
    calls = [(types.SimpleNamespace(line=1, ok=True), {"task_id": TASK, "role": "dev", "pipeline": "dev", "profile": "singular"}),
             (types.SimpleNamespace(line=2, ok=True), {"task_id": TASK, "role": "qa", "pipeline": "dev", "profile": "final_verification"}),
             (types.SimpleNamespace(line=3, ok=False), {"task_id": TASK, "role": "qa", "pipeline": "dev", "profile": "final_verification"})]
    assert len(score_view.extra_round_gaps(types.SimpleNamespace(obligations=lambda: calls), "/p")) == 1


def test_the_stop_gate_adds_the_gaps_to_the_dev_predicate(monkeypatch) -> None:
    import importlib.util
    spec = importlib.util.spec_from_file_location("stop_command_gate_for_score_view", REPO / "hooks" / "stop-command-gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    lib = importlib.import_module("lib.score_view")
    monkeypatch.setattr(gate, "_chain_gaps", lambda span, root, payload: ["chain gap"])
    monkeypatch.setattr(lib, "extra_round_gaps", lambda span, root: ["extra round gap"])
    assert gate.p_dev(None, "/p", {}) == ["chain gap", "extra round gap"]
    assert gate.PREDICATES["dev"] is gate.p_dev and gate.PREDICATES["redev"] is gate.p_dev and gate.PREDICATES["dev-command"] is gate.p_dev


# ---------------------------------------------------------------- the Codex gate's forced debate (D32)

QA_PROMPT = "FIRST ACTION: Read the sentinel.\n" + obligation.serialize_obligation(
    {"task_id": TASK, "role": "qa", "pipeline": "dev", "profile": "final_verification", "dispatched_at": "2026-11-01T12:00:00Z",
     "artifacts": [{"kind": "json", "path": f"docs/dev/qa-report-{TASK}.json", "schema": "qa-report.v2", "identity": {"task_id": TASK, "request_id": TASK}}]})


def _codex_stop(tmp_path: Path, rows, *, flag=None, ledger=False, role="qa", command="dev", prompt=QA_PROMPT, again=False, failed_attempt=False) -> subprocess.CompletedProcess:
    project, config = tmp_path / "project", tmp_path / "cfg"
    registry = project / ".claude" / "dev-registry" / f"dev-{TASK}"
    registry.mkdir(parents=True)
    if flag is not None:
        (registry / "codex-enforce.json").write_text(json.dumps({"enabled": flag}), encoding="utf-8")
    if ledger:
        (registry / "codex-ledger").mkdir()
        (registry / "codex-ledger" / "aqa.json").write_text("{}", encoding="utf-8")
    (project / ".claude" / "dev-registry" / "agent-index.json").write_text(json.dumps({"aqa": {"agent_type": role, "dev_session_id": f"dev-{TASK}"}}), encoding="utf-8")
    sub = tmp_path / "store" / "s" / "subagents" / "agent-aqa.jsonl"
    sub.parent.mkdir(parents=True)
    sub.write_text(json.dumps({"type": "user", "message": {"content": prompt}}) + "\n", encoding="utf-8")
    (config / "logs").mkdir(parents=True)
    key = score_log.project_key(project)
    (config / "logs" / "lifecycle.jsonl").write_text("".join(json.dumps({**r, "project": key}) + "\n" for r in rows), encoding="utf-8")
    payload = {"stop_hook_active": again, "agent_id": "aqa", "agent_type": role, "session_id": "s", "cwd": str(project), "transcript_path": str(_tx(tmp_path / "t.jsonl", command)),
               "agent_transcript_path": str(sub)}
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project), "CLAUDE_CONFIG_DIR": str(config), "HOME": str(tmp_path / "home"), "PYTHONDONTWRITEBYTECODE": "1"}
    if failed_attempt:
        attempted = {**payload, "hook_event_name": "PostToolUseFailure", "tool_name": "Skill",
                     "tool_input": {"skill": "codex"}, "error": "Unknown skill: codex", "tool_use_id": "failed-codex"}
        recorded = subprocess.run([sys.executable, str(REPO / "hooks" / "posttool-failure-launch.py")],
                                  input=json.dumps(attempted), capture_output=True, text=True, env=env, timeout=60)
        assert recorded.returncode == 0, recorded.stderr
        entry = json.loads((registry / "codex-ledger" / "aqa.json").read_text())
        assert entry["status"] == "failed" and entry["tool_call_id"] == "failed-codex"
    return subprocess.run([sys.executable, str(CODEX_HOOK)], input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=60)


def test_a_low_qa_debates_codex_without_the_flag_and_its_ledger_entry_lets_it_stop(tmp_path: Path) -> None:
    blocked = _codex_stop(tmp_path, _at("qa", 10))
    assert blocked.returncode == 2 and "CODEX_ENFORCE_BLOCKED: agent aqa (type=qa)" in blocked.stderr, blocked.stderr
    assert _codex_stop(tmp_path / "b", _at("qa", 10), ledger=True).returncode == 0  # any codex call, failed or not, is the entry


def test_a_low_qa_cannot_skip_its_debate_by_stopping_twice(tmp_path: Path) -> None:
    # A second stop is not a Codex attempt. Failed Skill calls must release it instead (D25).
    assert _codex_stop(tmp_path, _at("qa", 10), again=True).returncode == 2
    flagged = _codex_stop(tmp_path / "b", _at("qa", 10), flag=True, prompt=QA_PROMPT + "\ncodex_required: true\n", again=True)
    assert flagged.returncode == 2 and "CODEX_ENFORCE_BLOCKED" in flagged.stderr


@pytest.mark.parametrize(("rows", "case"), [(_at("qa", 30), "a record that is not low"), ([], "no record"), (_at("dev", 10), "another role's low record")])
def test_a_qa_that_is_not_low_is_not_bound_without_the_flag(tmp_path: Path, rows, case: str) -> None:
    assert _codex_stop(tmp_path, rows).returncode == 0, case


@pytest.mark.parametrize("command", ["dev-command", "dev-overnight"])
def test_a_dev_family_qa_is_bound_like_a_dev_qa(tmp_path: Path, command) -> None:
    prompt = QA_PROMPT.replace('"pipeline": "dev"', f'"pipeline": "{command}"')
    assert prompt != QA_PROMPT and _codex_stop(tmp_path, _at("qa", 10), command=command, prompt=prompt).returncode == 2


def test_the_forced_debate_binds_only_a_dev_family_qa(tmp_path: Path) -> None:
    close = QA_PROMPT.replace('"pipeline":"dev"', '"pipeline":"close"').replace('"pipeline": "dev"', '"pipeline": "close"')
    assert _codex_stop(tmp_path, _at("qa", 10), prompt=close).returncode == 0  # close QA is "close-qa", scored apart
    assert _codex_stop(tmp_path / "b", _at("dev", 10), role="dev").returncode == 0


def test_the_flag_still_binds_a_qa_that_is_not_low(tmp_path: Path) -> None:
    assert _codex_stop(tmp_path, _at("qa", 60), flag=True, prompt=QA_PROMPT + "\ncodex_required: true\n").returncode == 2


def test_an_error_reading_the_record_is_no_debate(tmp_path: Path) -> None:
    assert score_view.codex_forced({}, {"role": "qa", "pipeline": "dev"}) is False
    assert score_view.codex_forced({"cwd": "/p", "transcript_path": "/nonexistent"}, {"role": "qa", "pipeline": "dev"}) is False


@pytest.mark.parametrize("role,profile", score_view.ROUNDS)
def test_overnight_holds_each_lanes_extra_round_at_its_working_root(monkeypatch, low, role, profile):
    import importlib.util
    spec = importlib.util.spec_from_file_location("overnight_gate_for_score_view", REPO / "hooks" / "stop-command-gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    low(role)
    lib = importlib.import_module("lib.score_view")
    monkeypatch.setattr(lib, "is_low", score_view.is_low)
    overnight = importlib.import_module("lib.overnight")
    monkeypatch.setattr(overnight, "locate", lambda *args: (None, {"worktree_path": "/working"}))
    monkeypatch.setattr(overnight, "closeout_gaps", lambda *args: [])
    monkeypatch.setattr(gate, "disposition", lambda *args: [])
    span = _span((1, role, "overnight", "l1"), (2, role, "overnight", "l2"),
                 (3, "qa", profile, "l1"), (4, "qa", profile, "l2"),
                 (5, "qa", profile, "l1"), pipeline="dev-overnight")
    span.session_families = lambda: {TASK}
    gaps = gate.p_overnight(span, "/main", {"session_id": "s"})
    assert len(gaps) == 1 and "l2" in gaps[0] and profile in gaps[0]
    calls = span.obligations()
    calls.append((types.SimpleNamespace(line=6, ok=True), dict(calls[3][1])))
    assert gate.p_overnight(span, "/main", {"session_id": "s"}) == []


def test_overnight_opener_tells_the_orchestrator_which_roles_owe_rounds(monkeypatch):
    monkeypatch.setattr(score_view, "_rows", lambda: _at("dev", 10, project=score_log.project_key("/p")))
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    assert "Low record: dev: one more independent QA round" in (score_view.main_line("dev-overnight", "/p") or "")


@pytest.mark.parametrize("command", ["dev", "dev-command", "dev-overnight"])
def test_a_low_qa_can_stop_after_a_failed_codex_skill_attempt_without_a_flag(tmp_path, command):
    prompt = QA_PROMPT.replace('"pipeline": "dev"', f'"pipeline": "{command}"')
    done = _codex_stop(tmp_path, _at("qa", 10), command=command, prompt=prompt, again=True, failed_attempt=True)
    assert done.returncode == 0, done.stderr
