"""The native close rating (P4 R7, P13-2 S4; D9, D9b): hooks/lib/close_rating.py and
hooks/posttool-close-rating.py, the rating row's one writer and the owner summary it prints (through score_log).

The hook runs as the CLI runs it: a subprocess fed a PostToolUse payload on
stdin, with CLAUDE_CONFIG_DIR at a scratch directory. The AskUserQuestion
tool_response is the CLI's output record ({questions, answers, response?,
annotations?, afkTimeoutMs?}); the predicates read transcripts in the CLI's
record shapes (an Agent result's toolUseResult carries the agent's own text,
the tool_result block also carries the CLI's agentId trailer)."""
from __future__ import annotations

import fcntl
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / "hooks" / "posttool-close-rating.py"
sys.path.insert(0, str(REPO_ROOT))
from hooks.lib import close_rating, command_span, obligation, score_log  # noqa: E402
from hooks.lib.subagent_restart import project_slug  # noqa: E402

TASK, OTHER = "20261101-120000", "20261101-130000"
LABELS = ["5 - Fully met", "4 - Minor gaps", "3 - Major gaps", "1-2 - Not met"]
KEY = score_log.project_key("/tmp")  # the project key of the payloads' default working directory


def _question(task: str = TASK) -> str:
    return f"How well did cycle {task} meet what you asked for?"


def _input(task: str = TASK, source: str | None = None) -> dict:
    return {"questions": [{"question": _question(task), "header": "Rating", "multiSelect": False,
                           "options": [{"label": label, "description": "d"} for label in LABELS]}],
            "metadata": {"source": source if source is not None else f"close-rating:{task}"}}


def _payload(answer=None, task: str = TASK, tool_use_id: str = "toolu_rate", cwd: str = "/tmp", **response) -> dict:
    tool_input = _input(task)
    answers = {} if answer is None else {_question(task): answer}
    return {"session_id": "sess", "transcript_path": "/nonexistent.jsonl", "cwd": cwd,
            "permission_mode": "default", "hook_event_name": "PostToolUse", "tool_name": "AskUserQuestion",
            "tool_input": tool_input, "tool_use_id": tool_use_id,
            "tool_response": {"questions": tool_input["questions"], "answers": answers, **response}}


@pytest.fixture()
def config(tmp_path: Path) -> Path:
    return tmp_path / "config"


def _log(config: Path) -> Path:
    return config / "logs" / "lifecycle.jsonl"


def _rows(config: Path) -> list:
    log = _log(config)
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def _run(payload, config: Path, path: str | None = None, python: str | None = None,
         **env_extra: str) -> subprocess.CompletedProcess:
    env = {"PATH": path or os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(config.parent),
           "CLAUDE_CONFIG_DIR": str(config), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", **env_extra}
    return subprocess.run([python or sys.executable, str(HOOK)],
                          input=payload if isinstance(payload, str) else json.dumps(payload), env=env,
                          capture_output=True, text=True, timeout=60)


def _silent(result: subprocess.CompletedProcess) -> None:
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def _summary(result: subprocess.CompletedProcess) -> str:
    """The owner summary a run printed: exit 0, no stderr, one JSON line whose only key is systemMessage."""
    assert (result.returncode, result.stderr) == (0, ""), result.stderr
    [line] = result.stdout.splitlines()
    [(name, text)] = json.loads(line).items()
    assert name == "systemMessage" and 1 <= len(text.splitlines()) <= 5
    return text


def _event(role: str, event: str, points: int, why: str, task: str = TASK, **fields) -> dict:
    return {"kind": "event", "ts": "2026-11-01T12:30:00Z", "project": KEY, "task_id": task, "role": role,
            "event": event, "points": points, "key": f"{task}:{role}:{event}", "why": why, "ref": "r", **fields}


def _seed(config: Path, *rows: dict) -> None:
    _log(config).parent.mkdir(parents=True, exist_ok=True)
    _log(config).write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


# dev lost 12 points over two cycles: the worst identity of every seeded log below
SEEDED = (_event("dev", "qa_fail", -6, "edge case not tested", task=OTHER), _event("dev", "qa_fail", -6, "edge case not tested"),
          _event("qa", "qa_catch", 1, "caught the missing edge case"))


# --------------------------------------------------------------------------
# The producer: exactly one row for an exact label, nothing otherwise (A7)
# --------------------------------------------------------------------------

def test_an_exact_label_writes_exactly_one_row(config: Path) -> None:
    text = _summary(_run(_payload("4 - Minor gaps"), config))
    [row] = _rows(config)
    assert set(row) == {"kind", "ts", "project", "task_id", "rating", "roles", "tool_use_id"}
    assert (row["kind"], row["project"], row["task_id"], row["rating"], row["roles"], row["tool_use_id"]) == (
        "rating", KEY, TASK, 4, [], "toolu_rate")  # no dispatch record of the task: no role but main's
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", row["ts"])
    assert "main 51 Skilled Craftsman" in text and "rating 4: +1 each" in text


@pytest.mark.parametrize(("label", "rating"), zip(LABELS, [5, 4, 3, 1]))
def test_each_label_maps_to_its_rating_and_1_2_is_stored_as_1(config: Path, label: str, rating: int) -> None:
    _summary(_run(_payload(label), config))
    assert [row["rating"] for row in _rows(config)] == [rating]


NON_ANSWERS = ["skip", "free_text", "typed_response", "afk", "follow_up", "multi_select", "label_case", "decline",
               "error_result", "no_response", "unanswered"]


def _non_answer(case: str) -> dict:
    return {
        "skip": _payload(None),
        "free_text": _payload("great"),
        "typed_response": _payload("4 - Minor gaps", response="wait, explain the gaps first"),
        "afk": _payload("4 - Minor gaps", afkTimeoutMs=60000),
        "follow_up": _payload("4 - Minor gaps", followUp=True),
        "multi_select": _payload(["4 - Minor gaps"]),
        "label_case": _payload("4 - minor gaps"),
        "decline": dict(_payload(None), tool_response="User declined to answer questions"),
        "error_result": dict(_payload(None), tool_response={"error": "Tool permission request failed"}),
        "no_response": {k: v for k, v in _payload("4 - Minor gaps").items() if k != "tool_response"},
        "unanswered": _payload("4 - Minor gaps", annotations={_question(): {"unanswered": "skipped"}}),
    }[case]


@pytest.mark.parametrize("case", NON_ANSWERS)
def test_no_answer_writes_no_row(config: Path, case: str) -> None:
    _silent(_run(_non_answer(case), config))  # no log to read either: nothing to show
    assert not _log(config).exists()


@pytest.mark.parametrize("case", NON_ANSWERS)
def test_no_answer_writes_no_row_but_the_scores_are_still_shown(config: Path, case: str) -> None:
    # B4 / D9b: Skip, free text, AFK, a decline, an error and a missing label write no rating row; the summary of
    # the log as it stands is still returned, without this cycle's rating line.
    _seed(config, *SEEDED)
    text = _summary(_run(_non_answer(case), config))
    assert _rows(config) == list(SEEDED)
    assert text == score_log.render_owner_summary(list(SEEDED), KEY, "9999-12-31T23:59:59Z", TASK)
    assert "rating" not in text and text.splitlines()[1] == f"This cycle {TASK}: dev -6 (edge case not tested), qa +1 (caught the missing edge case)"


def test_a_re_rating_writes_no_second_row(config: Path) -> None:
    _summary(_run(_payload("4 - Minor gaps"), config))
    again = _summary(_run(_payload("5 - Fully met", tool_use_id="toolu_again"), config))  # still shown, nothing written
    _summary(_run(_payload("3 - Major gaps", task=OTHER), config))
    assert [(row["task_id"], row["rating"]) for row in _rows(config)] == [(TASK, 4), (OTHER, 3)]
    assert "rating 4: +1 each" in again and "rating 5" not in again


def test_a_rating_sourced_with_the_minted_prefix_and_one_without_are_one_task(config: Path) -> None:
    # First rating wins per canonical task id, as the predicates compare them.
    _summary(_run(_payload("4 - Minor gaps", task=f"dev-{TASK}"), config))
    _summary(_run(_payload("5 - Fully met", tool_use_id="toolu_again"), config))
    _summary(_run(_payload("3 - Major gaps", task=f"dev-command-{TASK}", tool_use_id="toolu_third"), config))
    assert [(row["task_id"], row["rating"]) for row in _rows(config)] == [(f"dev-{TASK}", 4)]


def test_an_event_row_or_a_kindless_row_of_the_same_task_does_not_stop_the_rating(config: Path) -> None:
    # P4's defect: the old writer let any row holding the task id (an event row, a score-update.sh row) stop the
    # owner's rating. Only a rating row of the same canonical task id does, and a kindless P4 rating row is not one.
    kindless = {"ts": "2026-11-01T12:00:00Z", "task_id": TASK, "rating": 5, "tool_use_id": "toolu_p4"}
    _seed(config, *SEEDED, kindless, dict(_event("dev", "qa_first_pass", 2, "first pass"), task_id=f"dev-{TASK}"))
    _summary(_run(_payload("4 - Minor gaps"), config))
    assert [r["rating"] for r in _rows(config) if r.get("kind") == "rating"] == [4]
    _summary(_run(_payload("3 - Major gaps", task=f"dev-{TASK}", tool_use_id="toolu_again"), config))  # another spelling
    assert [r["rating"] for r in _rows(config) if r.get("kind") == "rating"] == [4] and len(_rows(config)) == 6


@pytest.mark.parametrize("source", ["remember", f"close-rating:{TASK}/x", "close-rating:ab", f"close-rating:{TASK}\n",
                                    f"Close-rating:{TASK}", ""])
def test_another_source_is_a_no_op(config: Path, source: str) -> None:
    payload = _payload("4 - Minor gaps")
    payload["tool_input"]["metadata"]["source"] = source
    _silent(_run(payload, config))
    no_metadata = _payload("4 - Minor gaps")
    del no_metadata["tool_input"]["metadata"]
    _silent(_run(no_metadata, config))
    assert not _log(config).exists()


def test_a_subagent_caller_is_a_no_op(config: Path) -> None:
    _silent(_run(dict(_payload("4 - Minor gaps"), agent_id="a1b2c3", agent_type="qa"), config))
    assert not _log(config).exists()


def test_a_question_set_with_more_than_the_rating_is_a_no_op(config: Path) -> None:
    payload = _payload("4 - Minor gaps")
    payload["tool_input"]["questions"].append(dict(payload["tool_input"]["questions"][0], question="Anything else?"))
    _silent(_run(payload, config))
    assert not _log(config).exists()


@pytest.mark.parametrize("case", ["subagent", "another_source", "no_metadata", "two_questions", "another_tool"])
def test_nothing_for_another_call_even_with_a_readable_log(config: Path, case: str) -> None:
    # Not a main-agent close-rating call: no row and no summary, whatever the log holds.
    _seed(config, *SEEDED)
    payload = _payload("4 - Minor gaps")
    if case == "subagent":
        payload.update(agent_id="a1b2c3", agent_type="qa")
    elif case == "another_source":
        payload["tool_input"]["metadata"]["source"] = "remember"
    elif case == "no_metadata":
        del payload["tool_input"]["metadata"]
    elif case == "two_questions":
        payload["tool_input"]["questions"].append(dict(payload["tool_input"]["questions"][0], question="Anything else?"))
    else:
        payload["tool_name"] = "Bash"
    _silent(_run(payload, config))
    assert _rows(config) == list(SEEDED)


@pytest.mark.parametrize("raw", ["", "not json", "null", "[]", '"AskUserQuestion"', "{}", '{"tool_name": "AskUserQuestion"}',
                                 '{"tool_name": "AskUserQuestion", "tool_input": "x"}',
                                 '{"tool_name": "AskUserQuestion", "tool_input": {"metadata": {"source": "close-rating:' + TASK + '"}}}',
                                 '{"tool_name": 7}'])
def test_garbage_input_gives_nothing_and_exits_0(config: Path, raw: str) -> None:
    _seed(config, *SEEDED)
    _silent(_run(raw, config))
    assert _rows(config) == list(SEEDED)


@pytest.mark.parametrize("tool", ["Agent", "Task"])
def test_a_dispatch_payload_through_the_hook_as_the_cli_runs_it_is_silent_and_writes_nothing_without_a_span(config: Path, tool: str) -> None:
    # The Agent branch of the real hook with whatever hooks/lib/score_events.py is there: a dispatch in a session that
    # holds no harness command span records nothing and prints nothing.
    payload = {"session_id": "sess", "transcript_path": "/nonexistent.jsonl", "cwd": "/tmp", "hook_event_name": "PostToolUse",
               "tool_name": tool, "tool_input": {"subagent_type": "dev", "prompt": "p"}, "tool_use_id": "toolu_d",
               "tool_response": {"status": "completed"}}
    _silent(_run(payload, config))
    assert not _log(config).exists()


@pytest.mark.parametrize("cwd", [None, 7, ""])
def test_a_payload_without_a_usable_working_directory_gives_nothing(config: Path, cwd) -> None:
    payload = _payload("4 - Minor gaps")
    payload["cwd"] = cwd
    _seed(config, *SEEDED)
    _silent(_run(payload, config))
    assert _rows(config) == list(SEEDED)


# --- the roles of a rating row: the scored identities of the task's dispatches, read when the row is written

def _typed(text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}}


def _json(path: str, schema: str, task: str = TASK) -> dict:
    return {"kind": "json", "path": path, "schema": schema, "identity": {"task_id": task}}


def _dispatch(use_id: str, subagent_type: str, task: str, artifacts: list, pipeline: str = "dev",
              profile: str = "singular", lane: str | None = None, **more) -> dict:
    doc = {"task_id": task, "lane": lane, "lane_set": [lane] if lane else None, "role": subagent_type,
           "pipeline": pipeline, "profile": "fanout-lane" if lane else profile,
           "dispatched_at": "2026-11-01T12:00:00Z", "artifacts": artifacts, **more}
    prompt = "FIRST ACTION: register.\n" + obligation.serialize_obligation(doc) + "\nDo the work."
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": use_id, "name": "Agent", "input": {"subagent_type": subagent_type, "prompt": prompt}}]}}


def _store(config: Path, project: Path) -> Path:
    """The project's transcript store under the throwaway config directory, filled with the sessions of one task
    (dev, a lane's dev and the lane's QA in one session, close QA in a later one) and a dispatch of another task."""
    folder = config / "projects" / project_slug(project)
    folder.mkdir(parents=True)
    lane = f"{TASK}-l1"
    sessions = {
        "s-dev": [_typed("/dev build it"),
                  _dispatch("toolu_ba", "ba", TASK, [_json(f"docs/dev/context-{TASK}.json", "context.v1"),
                                                      {"kind": "markdown", "path": f"docs/dev/ticket-{TASK}.md",
                                                       "identity_anchor": TASK}]),
                  _dispatch("toolu_dev", "dev", lane, [_json(f"docs/dev/dev-report-{lane}.json", "dev-report.v2")], lane="l1"),
                  _dispatch("toolu_dev2", "dev", lane, [_json(f"docs/dev/dev-report-{lane}.json", "dev-report.v2")], lane="l1"),
                  _dispatch("toolu_qa", "qa", lane, [_json(f"docs/dev/qa-report-{lane}.json", "qa-report.v2")], lane="l1")],
        "s-close": [_typed(f"/close {TASK}"),
                    _dispatch("toolu_cqa", "qa", TASK, [{"kind": "markdown", "path": f"docs/dev/close-report-{TASK}.md",
                                                         "identity_anchor": TASK, "terminal_line_regex": "^CLOSE: YES.*$"}],
                              pipeline="close", profile="final_verification", consistency="verdict_class")],
        "s-other": [_typed("/dev another"),
                    _dispatch("toolu_arch", "architect", OTHER, [_json("docs/dev/x.json", "dev-report.v2", OTHER)])],
    }
    for sid, records in sessions.items():
        (folder / f"{sid}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return folder


def test_a_4_rating_writes_one_row_with_its_roles_and_the_summary_names_the_worst_identity(config: Path, tmp_path: Path) -> None:
    # B4: the rating row holds the sorted, distinct scored identities of the TASK's dispatches (its lanes, every
    # session of the project; qa in the close pipeline is close-qa; main is not listed; another task's dispatch is not
    # the task's); the hook output is score_log's owner summary, which names the worst identity and why.
    project = tmp_path / "proj"
    project.mkdir()
    _store(config, project)
    key = score_log.project_key(project)
    seeded = [dict(row, project=key) for row in SEEDED]
    _seed(config, *seeded)
    text = _summary(_run(_payload("4 - Minor gaps", cwd=str(project)), config))
    rows = _rows(config)
    assert rows[:3] == seeded and len(rows) == 4
    assert rows[3] == {"kind": "rating", "ts": rows[3]["ts"], "project": key, "task_id": TASK, "rating": 4,
                       "roles": ["ba", "close-qa", "dev", "qa"], "tool_use_id": "toolu_rate"}
    assert text == score_log.render_owner_summary(rows, key, "9999-12-31T23:59:59Z", TASK)  # includes the row just written
    first, cycle, worst = text.splitlines()
    assert first == ("Scores (this project): ba 51 Skilled Craftsman (+1) | close-qa 51 Skilled Craftsman (+1) | "
                     "dev 39 Journeyman (-11) | main 51 Skilled Craftsman (+1) | qa 52 Skilled Craftsman (+2)")
    assert cycle == f"This cycle {TASK}: dev -6 (edge case not tested), qa +1 (caught the missing edge case), rating 4: +1 each"
    assert worst == 'Worst: dev (Journeyman, 39); last miss: "edge case not tested"'
    assert "hook" not in text.lower() and "PostToolUse" not in text


def test_the_dispatch_store_is_the_project_dir_the_cli_names(config: Path, tmp_path: Path) -> None:
    # A session whose shell moved into a subdirectory still finds its project's transcripts (CLAUDE_PROJECT_DIR).
    project = tmp_path / "proj"
    (project / "sub").mkdir(parents=True)
    _store(config, project)
    _summary(_run(_payload("5 - Fully met", cwd=str(project / "sub")), config, CLAUDE_PROJECT_DIR=str(project)))
    assert [row["roles"] for row in _rows(config)] == [["ba", "close-qa", "dev", "qa"]]
    _summary(_run(_payload("5 - Fully met", cwd=str(project / "sub"), task=OTHER), config, CLAUDE_PROJECT_DIR=str(project)))
    assert [row["roles"] for row in _rows(config)][1] == ["architect"]


def test_append_row_hands_a_legacy_row_to_the_score_log_writer(config: Path) -> None:
    # score-update.sh's heredoc calls it under its own lock; a row with neither kind nor key is written as is, every time.
    legacy = {"ts": "2026-11-01T00:00:00Z", "agent": "dev", "event": "qa_first_pass", "task_id": TASK, "reason": "na\u00efve"}
    _log(config).parent.mkdir(parents=True)
    close_rating.append_row(str(_log(config)), legacy)
    close_rating.append_row(_log(config), legacy)
    assert _log(config).read_text(encoding="utf-8") == (json.dumps(legacy, ensure_ascii=False) + "\n") * 2
    assert not hasattr(close_rating, "append_rating")


# --- the dispatcher: AskUserQuestion goes to close_rating.handle, Agent and Task to score_events.observe

def _dispatch_run(monkeypatch, capsys, payload: dict, score_events) -> tuple[str, str]:
    """main() of the hook in this process, fed `payload`, with `score_events` standing in for hooks/lib/score_events.py
    (None: the module is absent). Returns what it printed on stdout and stderr."""
    monkeypatch.setattr(sys, "path", list(sys.path))  # the hook puts hooks/lib on the path
    monkeypatch.setitem(sys.modules, "score_events", score_events)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    spec = importlib.util.spec_from_file_location("posttool_close_rating_under_test", HOOK)
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    hook.main()
    out = capsys.readouterr()
    return out.out, out.err


def _stand_in(returns=None, raises: Exception | None = None):
    module, module.calls = types.ModuleType("score_events"), []

    def observe(payload):
        module.calls.append(payload)
        if raises:
            raise raises
        return returns

    module.observe = observe
    return module


@pytest.mark.parametrize("tool", ["Agent", "Task"])
def test_the_dispatch_tools_go_to_the_observer_and_its_dict_is_printed_as_one_json_line(monkeypatch, capsys, tool: str) -> None:
    stand_in = _stand_in({"systemMessage": "seen \u00e9"})
    payload = {"tool_name": tool, "tool_input": {"subagent_type": "dev"}, "tool_use_id": "toolu_x"}
    assert _dispatch_run(monkeypatch, capsys, payload, stand_in) == ('{"systemMessage": "seen \\u00e9"}\n', "")
    assert stand_in.calls == [payload]


@pytest.mark.parametrize("tool", ["Bash", "Write", ""])
def test_no_other_tool_reaches_the_observer_or_the_rating_handler(monkeypatch, capsys, tool: str) -> None:
    stand_in = _stand_in({"systemMessage": "must not be printed"})
    rated = types.ModuleType("close_rating")
    rated.handle = lambda payload: pytest.fail("close_rating.handle is for the question tool")
    monkeypatch.setitem(sys.modules, "close_rating", rated)
    assert _dispatch_run(monkeypatch, capsys, dict(_payload("4 - Minor gaps"), tool_name=tool), stand_in) == ("", "")
    assert stand_in.calls == []


def test_the_question_tool_goes_to_the_rating_handler_and_not_to_the_observer(monkeypatch, capsys) -> None:
    stand_in, seen = _stand_in({"systemMessage": "must not be printed"}), []
    rated = types.ModuleType("close_rating")
    rated.handle = lambda payload: seen.append(payload) or {"systemMessage": "rated"}
    monkeypatch.setitem(sys.modules, "close_rating", rated)
    payload = _payload("4 - Minor gaps")
    assert _dispatch_run(monkeypatch, capsys, payload, stand_in) == ('{"systemMessage": "rated"}\n', "")
    assert seen == [payload] and stand_in.calls == []


@pytest.mark.parametrize("returns", [None, [], "text", {"decision": "block", "reason": "x"}, {"continue": False},
                                     {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": "x"}}])
def test_the_dispatcher_prints_nothing_for_no_output_or_a_decision(monkeypatch, capsys, returns) -> None:
    assert _dispatch_run(monkeypatch, capsys, {"tool_name": "Agent"}, _stand_in(returns)) == ("", "")


@pytest.mark.parametrize("fault", ["absent", "crash"])
def test_the_dispatcher_survives_the_observer_missing_or_failing(monkeypatch, capsys, fault: str) -> None:
    stand_in = None if fault == "absent" else _stand_in(raises=RuntimeError("boom"))
    assert _dispatch_run(monkeypatch, capsys, {"tool_name": "Agent", "tool_input": {}}, stand_in) == ("", "")


def test_answers_the_model_wrote_into_its_input_are_never_read(config: Path) -> None:
    # TC-29 (pre-fill): the CLI drops `answers` from the model's input before
    # the dialog (AskUserQuestion.checkPermissions' updatedInput keeps title,
    # questions and metadata), so the hook reads only the CLI's tool_response.
    prefilled = _payload(None)
    prefilled["tool_input"]["answers"] = {_question(): "5 - Fully met"}
    prefilled["tool_input"]["annotations"] = {_question(): {"notes": "n"}}
    _silent(_run(prefilled, config))
    assert not _log(config).exists()
    prefilled["tool_response"]["answers"] = {_question(): "3 - Major gaps"}
    _summary(_run(prefilled, config))
    assert [row["rating"] for row in _rows(config)] == [3]


def test_twenty_parallel_invocations_for_twenty_tasks_give_twenty_rows(config: Path) -> None:
    tasks = [f"20261101-1200{n:02d}" for n in range(20)]
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda t: _run(_payload("4 - Minor gaps", task=t, tool_use_id=f"toolu_{t}"), config),
                                tasks))
    for result in results:
        _summary(result)
    lines = _log(config).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 20
    assert sorted(json.loads(line)["task_id"] for line in lines) == tasks


def test_the_hook_waits_for_the_score_scripts_lock(config: Path) -> None:
    _log(config).parent.mkdir(parents=True)
    _log(config).write_text('{"ts": "2026-11-01T00:00:00Z", "agent": "dev", "event": "qa_first_pass"}\n',
                            encoding="utf-8")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(config.parent),
           "CLAUDE_CONFIG_DIR": str(config)}
    with open(f"{_log(config)}.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        hook = subprocess.Popen([sys.executable, str(HOOK)], stdin=subprocess.PIPE, env=env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        hook.stdin.write(json.dumps(_payload("4 - Minor gaps")))
        hook.stdin.close()
        time.sleep(1.0)
        assert hook.poll() is None and len(_rows(config)) == 1
    assert hook.wait(timeout=60) == 0
    assert "main 51 Skilled Craftsman" in json.loads(hook.stdout.read())["systemMessage"]
    assert [row.get("rating") for row in _rows(config)] == [None, 4]


def test_no_venv_on_path_still_records(config: Path) -> None:
    system = shutil.which("python3", path="/usr/bin:/bin")
    assert system, "a system python3 under /usr/bin or /bin"
    _summary(_run(_payload("4 - Minor gaps"), config, path="/usr/bin:/bin", python=system))
    assert [row["rating"] for row in _rows(config)] == [4]


def test_the_shipped_settings_register_the_hook_once_for_askuserquestion_and_agent() -> None:
    settings = json.loads((REPO_ROOT / "settings.json").read_text(encoding="utf-8"))
    found = [(event, group.get("matcher"), hook["command"]) for event, groups in settings["hooks"].items()
             for group in groups for hook in group["hooks"] if "posttool-close-rating.py" in hook["command"]]
    assert found == [("PostToolUse", "AskUserQuestion|Agent",
                      'python3 "${CLAUDE_HOME:-$HOME/.claude}/hooks/posttool-close-rating.py"')]


def test_the_score_scripts_pass_over_rating_rows(tmp_path: Path, config: Path) -> None:
    # The score scripts read rows by their `agent` field; rating rows have none.
    root = tmp_path / "home"
    (root / "scripts" / "lib").mkdir(parents=True)
    (root / "venv" / "bin").mkdir(parents=True)
    (root / "venv" / "bin" / "activate").write_text("", encoding="utf-8")
    for name in ("score-update.sh", "score-inject.sh"):
        shutil.copy2(REPO_ROOT / "scripts" / name, root / "scripts" / name)
    shutil.copy2(REPO_ROOT / "scripts" / "lib" / "score_log.py", root / "scripts" / "lib")
    (root / "hooks" / "lib").mkdir(parents=True)
    for name in ("roster.py", "close_rating.py", "score_log.py"):
        shutil.copy2(REPO_ROOT / "hooks" / "lib" / name, root / "hooks" / "lib")
    shutil.copytree(REPO_ROOT / "agents", root / "agents")
    _summary(_run(_payload("4 - Minor gaps"), config))
    _summary(_run(_payload("1-2 - Not met", task=OTHER), config))

    def score(script: str, *arguments: str, log: Path = _log(config)) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(root / "scripts" / script), *arguments,
                               "--lifecycle-file", str(log)], capture_output=True, text=True, timeout=60)

    inject = score("score-inject.sh", "--agent", "dev")
    assert inject.returncode == 0 and "INJECTION_PROOF" in inject.stdout, inject.stderr
    update = score("score-update.sh", "--agent", "dev", "--event", "qa_first_pass")
    assert update.returncode == 0, update.stderr
    rows = _rows(config)
    assert [row.get("rating") for row in rows[:2]] == [4, 1] and rows[2]["agent"] == "dev" and len(rows) == 3
    # score-update.sh appends through the rating's writer (append_row): no log yet, its row as before
    fresh = tmp_path / "fresh" / "lifecycle.jsonl"
    update = score("score-update.sh", "--agent", "dev", "--event", "qa_first_pass", "--note", "naïve", log=fresh)
    assert update.returncode == 0, update.stderr
    [line] = fresh.read_text(encoding="utf-8").splitlines()
    assert '"reason": "naïve"' in line and json.loads(line)["prev_score"] == 50 and len(json.loads(line)) == 9


# --------------------------------------------------------------------------
# The predicates P5 imports (A8)
# --------------------------------------------------------------------------

class _Tx:
    """A main-session transcript in the CLI's record shapes."""

    def __init__(self):
        self.records, self._ids = [], 0

    def add(self, kind: str, content, **fields) -> None:
        self.records.append({"type": kind, "isSidechain": False, "sessionId": "sess", "uuid": f"u{len(self.records)}",
                             "message": {"role": kind, "content": content}, **fields})

    def typed(self, text: str) -> None:
        self.add("user", text)

    def call(self, name: str, tool_input: dict, result=None, is_error: bool = False, own=None) -> str:
        self._ids += 1
        ident = f"toolu_{self._ids:03d}"
        self.add("assistant", [{"type": "tool_use", "id": ident, "name": name, "input": tool_input}])
        if result is not None:
            block = {"type": "tool_result", "tool_use_id": ident, "content": result}
            if is_error:
                block["is_error"] = True
            self.add("user", [block], toolUseResult=own if own is not None else {"result": "x"})
        return ident

    def close_qa(self, task: str = TASK, final: str = "CLOSE: YES") -> str:
        doc = {"task_id": task, "role": "qa", "pipeline": "close", "profile": "final_verification",
               "dispatched_at": "2026-11-01T12:00:00Z",
               "artifacts": [{"kind": "markdown", "path": f"docs/dev/close-report-{task}.md",
                              "identity_anchor": task, "terminal_line_regex": "^CLOSE: YES.*$"}],
               "consistency": "verdict_class"}
        reply = f"Round 1 judged.\n\n{final}"
        return self.call("Agent", {"subagent_type": "qa", "description": "close QA",
                                   "prompt": "FIRST ACTION: register.\n" + obligation.serialize_obligation(doc)},
                         result=[{"type": "text", "text": reply},
                                 {"type": "text", "text": "agentId: a1\n<usage>total_tokens: 1</usage>"}],
                         own={"status": "completed", "agentId": "a1", "content": [{"type": "text", "text": reply}]})

    def rating(self, task: str = TASK, result="The user did not answer the questions.", is_error: bool = False):
        return self.call("AskUserQuestion", _input(task), result=result, is_error=is_error)

    def write(self, path: Path) -> Path:
        path.write_text("".join(json.dumps(r) + "\n" for r in self.records), encoding="utf-8")
        return path


def _required(tx: _Tx, path: Path, task: str = TASK) -> bool:
    return close_rating.rating_required(command_span.active_span(tx.write(path)), task)


@pytest.mark.parametrize("result,is_error", [
    ('Your questions have been answered: "q"="4 - Minor gaps".', False),
    ("The user did not answer the questions.", False),
    ("No response after 60s \u2014 the user may be away from keyboard.", False),
    ("User declined to answer questions", True),
])
def test_asked_after_the_landed_yes_whatever_the_result(tmp_path: Path, result: str, is_error: bool) -> None:
    tx = _Tx()
    tx.typed(f"/close {TASK}")
    tx.close_qa()
    tx.rating(result=result, is_error=is_error)
    path = tx.write(tmp_path / "t.jsonl")
    assert _required(tx, path) and close_rating.rating_asked(path, TASK)


def test_a_re_close_without_close_qa_requires_no_rating(tmp_path: Path) -> None:
    tx = _Tx()
    tx.typed(f"/close {TASK}")
    tx.close_qa()
    tx.rating()
    tx.typed(f"/close {TASK}")
    tx.call("Bash", {"command": "tail -1 docs/dev/close-report.md"}, result="CLOSE: YES")
    path = tx.write(tmp_path / "t.jsonl")
    assert not _required(tx, path) and not close_rating.rating_asked(path, TASK)


@pytest.mark.parametrize("final", ["CLOSE_FINDINGS: 2 items", "CLOSE_REPORT_APPEND_ERROR: append: disk full"])
def test_a_round_that_did_not_land_requires_no_rating(tmp_path: Path, final: str) -> None:
    tx = _Tx()
    tx.typed(f"/close {TASK}")
    tx.close_qa(final=final)
    assert not _required(tx, tmp_path / "t.jsonl")


def test_asked_before_the_landed_yes_or_for_another_task_is_not_asked(tmp_path: Path) -> None:
    tx = _Tx()
    tx.typed(f"/close {TASK}")
    tx.rating()
    tx.close_qa()
    tx.rating(task=OTHER)
    tx.call("AskUserQuestion", _input(source="remember"), result="The user did not answer the questions.")
    tx.call("AskUserQuestion", _input())  # the dialog is still open: no tool_result yet
    path = tx.write(tmp_path / "t.jsonl")
    assert _required(tx, path) and not close_rating.rating_asked(path, TASK)


def test_a_subagent_question_is_not_the_main_agent_asking(tmp_path: Path) -> None:
    tx = _Tx()
    tx.typed(f"/close {TASK}")
    tx.close_qa()
    tx.rating()
    for record in tx.records[-2:]:
        record["isSidechain"] = True
    assert not close_rating.rating_asked(tx.write(tmp_path / "t.jsonl"), TASK)


def test_auto_rates_each_landed_parent_with_its_own_source(tmp_path: Path) -> None:
    tx = _Tx()
    tx.typed("/close --auto")
    tx.close_qa(task=TASK)
    tx.rating(task=TASK)  # Skip on this parent: asked, no row
    tx.close_qa(task=OTHER)
    path = tx.write(tmp_path / "t.jsonl")
    assert _required(tx, path, TASK) and _required(tx, path, OTHER)
    assert close_rating.rating_asked(path, TASK) and not close_rating.rating_asked(path, OTHER)
    tx.rating(task=OTHER, result='Your questions have been answered: "q"="5 - Fully met".')
    assert close_rating.rating_asked(tx.write(path), OTHER)


def test_commit_running_close_steps_requires_no_rating(tmp_path: Path) -> None:
    # TC-27: /commit completes an unclosed task through close.md Steps 1-2 and asks no rating.
    tx = _Tx()
    tx.typed(f"/commit {TASK}")
    tx.close_qa()
    path = tx.write(tmp_path / "t.jsonl")
    assert not _required(tx, path) and not close_rating.rating_asked(path, TASK)


def test_task_ids_compare_canonically(tmp_path: Path) -> None:
    # The close-QA obligation may carry the minted dev- prefix the question's source leaves out.
    tx = _Tx()
    tx.typed(f"/close {TASK}")
    tx.close_qa(task=f"dev-{TASK}")
    tx.rating(task=TASK)
    path = tx.write(tmp_path / "t.jsonl")
    assert _required(tx, path, TASK) and _required(tx, path, f"dev-{TASK}")
    assert close_rating.rating_asked(path, TASK) and close_rating.rating_asked(path, f"dev-{TASK}")
    assert not _required(tx, path, "") and not close_rating.rating_asked(path, "")
