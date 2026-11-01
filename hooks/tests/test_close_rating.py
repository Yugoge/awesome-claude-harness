"""The native close rating (P4 R7; D9, D9a, D9b): hooks/lib/close_rating.py and
hooks/posttool-close-rating.py, the rating log's one writer.

The hook runs as the CLI runs it: a subprocess fed a PostToolUse payload on
stdin, with CLAUDE_CONFIG_DIR at a scratch directory. The AskUserQuestion
tool_response is the CLI's output record ({questions, answers, response?,
annotations?, afkTimeoutMs?}); the predicates read transcripts in the CLI's
record shapes (an Agent result's toolUseResult carries the agent's own text,
the tool_result block also carries the CLI's agentId trailer)."""
from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / "hooks" / "posttool-close-rating.py"
sys.path.insert(0, str(REPO_ROOT))
from hooks.lib import close_rating, command_span, obligation  # noqa: E402

TASK, OTHER = "20261101-120000", "20261101-130000"
LABELS = ["5 - Fully met", "4 - Minor gaps", "3 - Major gaps", "1-2 - Not met"]


def _question(task: str = TASK) -> str:
    return f"How well did cycle {task} meet what you asked for?"


def _input(task: str = TASK, source: str | None = None) -> dict:
    return {"questions": [{"question": _question(task), "header": "Rating", "multiSelect": False,
                           "options": [{"label": label, "description": "d"} for label in LABELS]}],
            "metadata": {"source": source if source is not None else f"close-rating:{task}"}}


def _payload(answer=None, task: str = TASK, tool_use_id: str = "toolu_rate", **response) -> dict:
    tool_input = _input(task)
    answers = {} if answer is None else {_question(task): answer}
    return {"session_id": "sess", "transcript_path": "/nonexistent.jsonl", "cwd": "/tmp",
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


def _run(payload, config: Path, path: str | None = None, python: str | None = None) -> subprocess.CompletedProcess:
    env = {"PATH": path or os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(config.parent),
           "CLAUDE_CONFIG_DIR": str(config), "LANG": "C.UTF-8"}
    return subprocess.run([python or sys.executable, str(HOOK)], input=json.dumps(payload), env=env,
                          capture_output=True, text=True, timeout=60)


def _silent(result: subprocess.CompletedProcess) -> None:
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


# --------------------------------------------------------------------------
# The producer: exactly one row for an exact label, nothing otherwise (A7)
# --------------------------------------------------------------------------

def test_an_exact_label_writes_exactly_one_row(config: Path) -> None:
    _silent(_run(_payload("4 - Minor gaps"), config))
    rows = _rows(config)
    assert len(rows) == 1 and set(rows[0]) == {"ts", "task_id", "rating", "tool_use_id"}
    assert (rows[0]["task_id"], rows[0]["rating"], rows[0]["tool_use_id"]) == (TASK, 4, "toolu_rate")
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", rows[0]["ts"])


@pytest.mark.parametrize(("label", "rating"), zip(LABELS, [5, 4, 3, 1]))
def test_each_label_maps_to_its_rating_and_1_2_is_stored_as_1(config: Path, label: str, rating: int) -> None:
    _silent(_run(_payload(label), config))
    assert [row["rating"] for row in _rows(config)] == [rating]


@pytest.mark.parametrize("case", ["skip", "free_text", "typed_response", "afk", "follow_up", "multi_select",
                                  "label_case", "decline", "error_result", "no_response"])
def test_no_answer_writes_no_row(config: Path, case: str) -> None:
    payload = {
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
    }[case]
    _silent(_run(payload, config))
    assert not _log(config).exists()


def test_a_re_rating_writes_no_second_row(config: Path) -> None:
    _silent(_run(_payload("4 - Minor gaps"), config))
    _silent(_run(_payload("5 - Fully met", tool_use_id="toolu_again"), config))
    _silent(_run(_payload("3 - Major gaps", task=OTHER), config))
    assert [(row["task_id"], row["rating"]) for row in _rows(config)] == [(TASK, 4), (OTHER, 3)]


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
    _silent(_run(prefilled, config))
    assert [row["rating"] for row in _rows(config)] == [3]


def test_twenty_parallel_invocations_for_twenty_tasks_give_twenty_rows(config: Path) -> None:
    tasks = [f"20261101-1200{n:02d}" for n in range(20)]
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda t: _run(_payload("4 - Minor gaps", task=t, tool_use_id=f"toolu_{t}"), config),
                                tasks))
    for result in results:
        _silent(result)
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
    assert hook.wait(timeout=60) == 0 and hook.stdout.read() == ""
    assert [row.get("rating") for row in _rows(config)] == [None, 4]


def test_no_venv_on_path_still_records(config: Path) -> None:
    system = shutil.which("python3", path="/usr/bin:/bin")
    assert system, "a system python3 under /usr/bin or /bin"
    _silent(_run(_payload("4 - Minor gaps"), config, path="/usr/bin:/bin", python=system))
    assert [row["rating"] for row in _rows(config)] == [4]


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
    shutil.copy2(REPO_ROOT / "hooks" / "lib" / "roster.py", root / "hooks" / "lib")
    shutil.copytree(REPO_ROOT / "agents", root / "agents")
    _silent(_run(_payload("4 - Minor gaps"), config))
    _silent(_run(_payload("1-2 - Not met", task=OTHER), config))

    def score(script: str, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(root / "scripts" / script), *arguments,
                               "--lifecycle-file", str(_log(config))], capture_output=True, text=True, timeout=60)

    inject = score("score-inject.sh", "--agent", "dev")
    assert inject.returncode == 0 and "INJECTION_PROOF" in inject.stdout, inject.stderr
    update = score("score-update.sh", "--agent", "dev", "--event", "qa_first_pass")
    assert update.returncode == 0, update.stderr
    rows = _rows(config)
    assert [row.get("rating") for row in rows[:2]] == [4, 1] and rows[2]["agent"] == "dev" and len(rows) == 3


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
