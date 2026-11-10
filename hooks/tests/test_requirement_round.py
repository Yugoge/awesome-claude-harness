"""The requirement round (P13-1, D28, D29, D32): hooks/lib/requirement_round.py and the PostToolUse AskUserQuestion
hook that calls it.

The predicates read CLI-shaped main-session transcripts through command_span; the hook runs as the CLI runs it, a
subprocess fed a PostToolUse payload, with CLAUDE_PROJECT_DIR at a scratch project. Names: A9 (G2's round checks),
A10 (asked counts an error result, R8), R4 (the answer writer), R5 (ASK_FIRST)."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "posttool-close-rating.py"
sys.path.insert(0, str(REPO))
from hooks.lib import command_span, contract_runtime  # noqa: E402
from hooks.lib import requirement_round as rr  # noqa: E402

TASK, DEV_ID = "20261109-120000", "dev-20261109-120000"
DIMS = ["intent", "scope", "edge_cases", "acceptance"]
T0 = datetime(2026, 11, 9, 12, 0, 0, tzinfo=timezone.utc)


class TX:
    """A main-session transcript: a typed command, its hook context, tool calls."""

    def __init__(self, path: Path):
        self.path, self.clock, self.n = path, T0, 0
        path.write_text("", encoding="utf-8")

    def add(self, record: dict) -> None:
        self.clock += timedelta(seconds=1)
        record.setdefault("timestamp", self.clock.isoformat().replace("+00:00", "Z"))
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    def command(self, name: str, context: str | None = None) -> None:
        self.add({"type": "user", "message": {"role": "user", "content":
                  f"<command-message>{name} is running…</command-message>\n<command-name>/{name}</command-name>\n"
                  "<command-args>a request</command-args>"}})
        self.add({"type": "user", "isMeta": True, "message": {"role": "user", "content": [
            {"type": "text", "text": f"body of {name}: its requirement-round is asked first"}]}})
        if context:
            self.add({"type": "attachment", "attachment": {"type": "hook_additional_context", "content": context,
                                                           "hookName": "UserPromptSubmit"}})

    def tool(self, name: str, tool_input: dict, ok: bool | None = True, sidechain: bool = False) -> str:
        """A tool use and its result; ok None: no result came back yet."""
        self.n += 1
        ident = f"toolu_{self.n:04d}"
        side = {"isSidechain": True, "agentId": "a1"} if sidechain else {}
        self.add({"type": "assistant", **side, "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": ident, "name": name, "input": tool_input}]}})
        if ok is not None:
            self.add({"type": "user", **side, "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": ident, "content": "done", **({} if ok else {"is_error": True})}]}})
        return ident

    def dispatch(self, role: str, paths, ok: bool | None = True, task: str = TASK) -> str:
        doc = obligation_doc(role, paths, task)
        return self.tool("Agent", {"subagent_type": role, "description": role,
                                   "prompt": f'<obligation v="1">{json.dumps(doc)}</obligation>\nwork'}, ok=ok)

    def ask(self, doc: dict, ok: bool = True, source: str | None = None, questions=None) -> str:
        return self.tool("AskUserQuestion", {
            "questions": rr.ask_view(doc) if questions is None else questions,
            "metadata": {"source": source or f"requirement-round:{TASK}:r{doc['round']}"}}, ok=ok)


def obligation_doc(role: str, paths, task: str = TASK) -> dict:
    arts = []
    for path in paths:
        if path.endswith(".md"):
            arts.append({"kind": "markdown", "path": path})
        else:
            schema = "requirement-round.v1" if "round" in path or "ba-panel" in path else "context.v1"
            arts.append({"kind": "json", "path": path, "schema": schema, "identity": {"task_id": task}})
    return {"task_id": task, "lane": None, "lane_set": None, "role": role, "pipeline": "dev", "profile": "singular",
            "dispatched_at": "2026-11-09T12:00:00Z", "artifacts": arts}


def q(i: int, dim: str, text: str | None = None, labels=("Yes", "No"), assume: str | None = None, ba=None) -> dict:
    return {"id": f"q{i}", "dimension": dim, "header": f"Point {i}", "question": text or f"What matters about {dim}?",
            "multiSelect": False, "assume": assume or labels[0], "spec_ref": None,
            "options": [{"label": label, "description": f"{label} means so", **({"ba": ba[k]} if ba else {})}
                        for k, label in enumerate(labels)]}


def round_doc(n: int = 1, questions=None, spec=None, panel=None) -> dict:
    doc = {"task_id": TASK, "round": n, "spec_id": spec,
           "questions": questions if questions is not None else [q(i + 1, d) for i, d in enumerate(DIMS)]}
    return {**doc, "panel": panel} if panel else doc


ROUND1 = rr.ROUND.format(task=TASK, n=1)
ROUND2 = rr.ROUND.format(task=TASK, n=2)
PANEL = rr.PANEL.format(task=TASK)
CONTEXT = f"docs/dev/context-{TASK}.json"


@pytest.fixture
def project(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "project"
    (root / "docs" / "dev" / "specs").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    return root


@pytest.fixture
def tx(tmp_path) -> TX:
    t = TX(tmp_path / "session.jsonl")
    t.command("dev", context=f"DEV_SESSION_ID pre-initialized by hook: {DEV_ID}\n")
    return t


def put(project: Path, rel: str, doc: dict) -> str:
    (project / rel).write_text(json.dumps(doc), encoding="utf-8")
    return rel


def answers(project: Path, n: int, given: dict) -> None:
    put(project, rr.ANSWERS.format(task=TASK, n=n), {"round": n, "answers": given})


def span(tx: TX):
    return command_span.active_span(tx.path)


def check(project, rel, tx, role="ba"):
    return rr.check_round(project, obligation_doc(role, [rel]), rel, span(tx))


# ---------------------------------------------------------------- the schema
def test_a_round_file_is_valid_against_its_registered_schema(project):
    put(project, ROUND1, round_doc())
    assert contract_runtime.validate_artifact_for_obligation(str(project / ROUND1), "requirement-round.v1")["status"] == "pass"
    long_header = round_doc(questions=[dict(q(1, "intent"), header="Thirteen char")])
    put(project, ROUND1, long_header)
    assert contract_runtime.validate_artifact_for_obligation(str(project / ROUND1), "requirement-round.v1")["status"] == "fail"


# ---------------------------------------------------------------- A9: G2 refuses a bad round
def test_a9_a_good_round_1_passes(project, tx):
    put(project, ROUND1, round_doc())
    assert check(project, ROUND1, tx) == []


@pytest.mark.parametrize("questions", [
    [q(1, "intent"), q(2, "scope"), q(3, "edge_cases")],
    [q(1, "intent"), q(2, "scope"), q(3, "edge_cases"), q(4, "intent")]], ids=["three", "repeated_dimension"])
def test_a9_round_1_without_a_spec_asks_one_question_per_dimension(project, tx, questions):
    put(project, ROUND1, round_doc(questions=questions))
    assert any("exactly four questions, one per dimension" in e for e in check(project, ROUND1, tx))


@pytest.mark.parametrize("label,refused", [("Keep docs/dev/x.json as is", True), ("Use `make` first", True),
                                           ("Call run() then", True), ("a::b", True), ("Edit the README.md", True),
                                           ("Keep it, e.g. as today", False)])
def test_a9_a_code_token_in_an_option_fails_the_lint(project, tx, label, refused):
    put(project, ROUND1, round_doc(questions=[q(1, "intent", labels=(label, "No"))] + [
        q(i + 2, d) for i, d in enumerate(DIMS[1:])]))
    assert any("code token" in e for e in check(project, ROUND1, tx)) is refused


def test_a9_an_assume_that_is_not_one_of_its_labels_fails(project, tx):
    put(project, ROUND1, round_doc(questions=[q(1, "intent", assume="Maybe")] + [
        q(i + 2, d) for i, d in enumerate(DIMS[1:])]))
    assert any("assume 'Maybe' is not one of its option labels" in e for e in check(project, ROUND1, tx))


def test_a9_with_a_spec_one_question_is_enough(project, tx):
    """The spec itself is spec-verify's to decide (D24: one decider per artifact); the round reads only its id."""
    put(project, ROUND1, round_doc(questions=[q(1, "scope")], spec="20261108-090000"))
    assert check(project, ROUND1, tx) == []
    put(project, ROUND1, round_doc(questions=[q(1, "scope")]))
    assert any("one per dimension" in e for e in check(project, ROUND1, tx))


def test_a9_a_round_follows_the_asked_one_before_it(project, tx):
    put(project, ROUND1, round_doc())
    put(project, ROUND2, round_doc(2, [q(1, "scope", "How far should it reach?")]))
    assert any("round r1 has not been asked" in e for e in check(project, ROUND2, tx))
    tx.ask(round_doc())
    assert check(project, ROUND2, tx) == []


def test_a9_a_question_already_answered_is_never_asked_again(project, tx):
    first = round_doc()
    put(project, ROUND1, first)
    tx.ask(first)
    answers(project, 1, {first["questions"][1]["question"]: "Yes"})
    put(project, ROUND2, round_doc(2, [q(1, "scope", "  what MATTERS about  scope? ".replace("?", "?"))]))
    assert any("already answered as 20261109-120000 r1.q2" in e for e in check(project, ROUND2, tx))
    put(project, ROUND2, round_doc(2, [q(1, "scope", "What matters about intent?")]))  # asked, never answered
    assert check(project, ROUND2, tx) == []


def test_a9_a_question_answered_in_the_attached_specs_rounds_is_not_asked_again(project, tx):
    spec = "20261108-090000"
    (project / "docs/dev/specs" / f"spec-{spec}.md").write_text("# Spec\n")
    put(project, rr.ROUND.format(task=spec, n=1), dict(round_doc(), task_id=spec))
    put(project, rr.ANSWERS.format(task=spec, n=1), {"answers": {"What matters about scope?": "No"}})
    put(project, ROUND1, round_doc(questions=[q(1, "scope")], spec=spec))
    assert any(f"already answered as {spec} r1.q2" in e for e in check(project, ROUND1, tx))


def test_a9_an_option_from_a_ba_whose_root_cause_panel_qa_did_not_verify_fails(project, tx):
    panel = {"reports": [{"ba": b, "path": f"docs/dev/ba-panel-{TASK}-{b}.md", "root_cause": v, "why": "cited"}
                         for b, v in zip("ABC", ("verified", "refuted", "unsupported"))], "agreements": ["the bug"]}
    scope = q(2, "scope", labels=("Fix the cause", "Smallest change", "Owner view"), ba="ABC")
    put(project, PANEL, round_doc(questions=[q(1, "intent"), scope, q(3, "edge_cases"), q(4, "acceptance")], panel=panel))
    errors = check(project, PANEL, tx, role="qa")
    assert len([e for e in errors if "panel QA did not verify" in e]) == 2 and "'Fix the cause'" not in "".join(errors)
    put(project, PANEL, round_doc(questions=[q(1, "intent"), q(2, "scope", labels=("Fix the cause", "Wait"), ba="AA"),
                                             q(3, "edge_cases"), q(4, "acceptance")], panel=panel))
    assert check(project, PANEL, tx, role="qa") == []


def test_a9_a_ba_tag_without_a_panel_fails_and_task_ids_must_match(project, tx):
    put(project, ROUND1, dict(round_doc(questions=[q(1, "intent", ba="AB")] + [q(i + 2, d) for i, d in enumerate(DIMS[1:])]),
                              task_id="20261109-999999"))
    errors = check(project, ROUND1, tx)
    assert any("panel QA did not verify" in e for e in errors) and any(e.startswith("task_id:") for e in errors)


def test_a9_an_analysis_that_misses_one_answered_id_fails(project):
    put(project, ROUND1, round_doc())
    answers(project, 1, {"What matters about intent?": "Yes", "What matters about scope?": "No"})
    ob = obligation_doc("ba", [CONTEXT])
    full = {"requirement": {"contract_refs": [{"answer_ref": "r1.q1", "criterion_ids": ["AC1"]},
                                              {"answer_ref": "r1.q2", "criterion_ids": ["AC2"]}]},
            "assumptions": [{"question_ref": "r1.q3", "assume": "Yes"}, {"question_ref": "r1.q4", "assume": "Yes"}]}
    assert rr.check_analysis(project, ob, full) == []
    missing = dict(full, requirement={"contract_refs": full["requirement"]["contract_refs"][:1]})
    assert rr.check_analysis(project, ob, missing) == [
        "requirement.contract_refs maps no criterion_ids to the answered question r1.q2"]
    unassumed = dict(full, assumptions=full["assumptions"][:1])
    assert any("unanswered r1.q4" in e for e in rr.check_analysis(project, ob, unassumed))
    assert rr.check_analysis(project, dict(ob, task_id="20261109-555555"), {}) == []  # no round: nothing to map


# ---------------------------------------------------------------- A10: asked, never answered (R8)
@pytest.mark.parametrize("ok", [True, False], ids=["answered", "error_result"])
def test_a10_an_error_tool_result_counts_as_asked(project, tx, ok):
    doc = round_doc()
    put(project, ROUND1, doc)
    tx.ask(doc, ok=ok)
    assert rr.asked(span(tx), f"requirement-round:{TASK}:r1", project / ROUND1)
    assert rr.asked(span(tx), f"requirement-round:dev-{TASK}:r1", project / ROUND1)  # canonical task ids


def test_asked_needs_the_exact_questions_the_source_and_a_result(project, tx):
    doc = round_doc()
    put(project, ROUND1, doc)
    paraphrase = rr.ask_view(doc)
    paraphrase[0] = dict(paraphrase[0], question="What should change, roughly?")
    tx.ask(doc, questions=paraphrase)
    tx.ask(doc, source=f"requirement-round:{TASK}:r2")
    tx.tool("AskUserQuestion", {"questions": rr.ask_view(doc), "metadata": {"source": f"requirement-round:{TASK}:r1"}},
            ok=None)
    tx.tool("AskUserQuestion", {"questions": rr.ask_view(doc), "metadata": {"source": f"requirement-round:{TASK}:r1"}},
            sidechain=True)
    assert not rr.asked(span(tx), f"requirement-round:{TASK}:r1", project / ROUND1)
    tx.ask(doc)
    assert rr.asked(span(tx), f"requirement-round:{TASK}:r1", project / ROUND1)


# ---------------------------------------------------------------- R4: the answer writer
def _hook(project: Path, tool_input: dict, response, **extra) -> subprocess.CompletedProcess:
    payload = {"session_id": "s", "transcript_path": "/nonexistent.jsonl", "cwd": str(project),
               "hook_event_name": "PostToolUse", "tool_name": "AskUserQuestion", "tool_input": tool_input,
               "tool_use_id": "toolu_ask", "tool_response": response, **extra}
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(project.parent),
           "CLAUDE_CONFIG_DIR": str(project.parent / "config"), "CLAUDE_PROJECT_DIR": str(project), "LANG": "C.UTF-8"}
    result = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), env=env, capture_output=True,
                            text=True, timeout=60)
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    return result


def _round_input(doc: dict) -> dict:
    return {"questions": rr.ask_view(doc), "metadata": {"source": f"requirement-round:{TASK}:r{doc['round']}"}}


def test_r4_the_exact_round_writes_the_answer_file_verbatim_and_the_first_ask_wins(project):
    doc = round_doc()
    put(project, ROUND1, doc)
    tin = _round_input(doc)
    given = {tin["questions"][0]["question"]: "Yes", tin["questions"][1]["question"]: "No"}
    _hook(project, tin, {"questions": tin["questions"], "answers": given, "annotations": {"x": {"notes": "n"}}})
    record = json.loads((project / rr.ANSWERS.format(task=TASK, n=1)).read_text())
    assert record["answers"] == given and record["questions"] == tin["questions"]
    assert (record["task_id"], record["round"], record["source"], record["tool_use_id"]) == (
        TASK, 1, f"requirement-round:{TASK}:r1", "toolu_ask")
    assert record["question_file_sha256"] == hashlib.sha256((project / ROUND1).read_bytes()).hexdigest()
    assert record["annotations"] == {"x": {"notes": "n"}} and record["response"] is None
    _hook(project, tin, {"questions": tin["questions"], "answers": {tin["questions"][0]["question"]: "No"}})
    assert json.loads((project / rr.ANSWERS.format(task=TASK, n=1)).read_text())["answers"] == given
    assert not list((project / "docs/dev").glob(".*.tmp"))


@pytest.mark.parametrize("case", ["paraphrase", "skip", "afk", "subagent", "decline", "no_round_file", "other_source"])
def test_r4_no_owner_content_or_another_question_writes_nothing(project, case):
    doc = round_doc()
    put(project, ROUND1, doc)
    tin = _round_input(doc)
    answer = {tin["questions"][0]["question"]: "Yes"}
    response, extra = {"questions": tin["questions"], "answers": answer}, {}
    if case == "paraphrase":
        tin = dict(tin, questions=[dict(tin["questions"][0], header="Other")] + tin["questions"][1:])
    elif case == "skip":
        response = {"questions": tin["questions"], "answers": {}}
    elif case == "afk":
        response = dict(response, afkTimeoutMs=60000)
    elif case == "subagent":
        extra = {"agent_id": "a1"}
    elif case == "decline":
        response = "User declined to answer questions"
    elif case == "no_round_file":
        (project / ROUND1).unlink()
    elif case == "other_source":
        tin = dict(tin, metadata={"source": f"requirement-round:{TASK}:ba"})
    _hook(project, tin, response, **extra)
    assert not list((project / "docs/dev").glob("requirement-answers-*"))


def test_r4_each_producer_question_gets_its_own_answer_file(project):
    """A5's unit half: two producer questions in a row give two producer answers with distinct q8."""
    question = project / rr.QUESTION.format(task=TASK, role="ba")
    tin = {"questions": [{"question": "Which?", "header": "Decision", "multiSelect": False,
                          "options": [{"label": "A", "description": ""}, {"label": "B", "description": ""}]}],
           "metadata": {"source": f"producer-question:{TASK}:ba"}}
    seen = []
    for need in ("first decision", "second decision"):
        question.write_text(json.dumps({"task_id": TASK, "role": "ba", "need": need}))
        seen.append(hashlib.sha256(question.read_bytes()).hexdigest()[:8])
        _hook(project, tin, {"questions": tin["questions"], "answers": {"Which?": "A"}})
    files = sorted(p.name for p in (project / "docs/dev").glob("producer-answer-*.json"))
    assert files == sorted(f"producer-answer-{TASK}-ba-{q8}.json" for q8 in seen) and len(set(seen)) == 2


# ---------------------------------------------------------------- R5: ask first, then dispatch
def test_r5_no_dispatch_but_the_round_1_producers_before_round_1_is_asked(project, tx):
    for paths in ([ROUND1], [f"docs/dev/ba-panel-{TASK}-A.md"], [PANEL]):
        assert rr.ask_first(span(tx), project, obligation_doc("ba", paths)) is None
    refusal = rr.ask_first(span(tx), project, obligation_doc("ba", [CONTEXT]))
    assert refusal.startswith(f"ASK_FIRST: no requirement round r1 of task {TASK} has been asked")
    assert rr.ask_first(span(tx), project, None) is None  # no obligation block


def test_r5_a_valid_unasked_round_refuses_every_other_dispatch_until_asked(project, tx):
    doc = round_doc()
    tx.dispatch("ba", [ROUND1])
    put(project, ROUND1, doc)
    want = (f'ASK_FIRST: ask {ROUND1} with one AskUserQuestion, metadata.source "requirement-round:{TASK}:r1", '
            "questions exactly as written; then dispatch.")
    assert rr.ask_first(span(tx), project, obligation_doc("ba", [CONTEXT])) == want
    assert rr.ask_first(span(tx), project, obligation_doc("ba", [ROUND1])) is None  # its repair passes
    tx.ask(doc, ok=False)  # a denied or skipped ask is asked
    assert rr.ask_first(span(tx), project, obligation_doc("ba", [CONTEXT])) is None


def test_r5_a_malformed_round_or_one_whose_dispatch_did_not_return_ok_asks_nothing(project, tx):
    tx.dispatch("ba", [ROUND1], ok=False)
    put(project, ROUND1, round_doc())
    assert "ASK_FIRST: no requirement round r1" in rr.ask_first(span(tx), project, obligation_doc("ba", [CONTEXT]))
    tx.dispatch("ba", [ROUND1])
    (project / ROUND1).write_text("{not json")
    assert "ASK_FIRST: no requirement round r1" in rr.ask_first(span(tx), project, obligation_doc("ba", [CONTEXT]))


def test_r5_the_dispatch_being_decided_is_not_its_roles_latest(project, tx):
    tx.dispatch("ba", [ROUND1])
    put(project, ROUND1, round_doc())
    current = tx.dispatch("ba", [CONTEXT], ok=None)
    assert rr.ask_first(span(tx), project, obligation_doc("ba", [CONTEXT]), current).startswith(f"ASK_FIRST: ask {ROUND1}")


def test_r5_a_producer_question_is_asked_before_the_next_dispatch(project, tx):
    first = round_doc()
    put(project, ROUND1, first)
    tx.ask(first)
    tx.dispatch("ba", [CONTEXT])
    question = put(project, rr.QUESTION.format(task=TASK, role="ba"), {
        "task_id": TASK, "role": "ba", "need": "n", "why": "w", "default": "A",
        "options": [{"label": "A", "description": "a"}, {"label": "B", "description": "b"}]})
    os.utime(project / question, (tx.clock.timestamp(),) * 2)  # written by the dispatch that just came back
    assert rr.ask_first(span(tx), project, obligation_doc("ba", [CONTEXT])) == (
        f'ASK_FIRST: ask {question} with one AskUserQuestion, metadata.source "producer-question:{TASK}:ba", '
        "questions exactly as written; then dispatch.")
    tx.tool("AskUserQuestion", {"questions": [], "metadata": {"source": f"producer-question:{TASK}:ba"}})
    assert rr.ask_first(span(tx), project, obligation_doc("ba", [CONTEXT])) is None


def test_r5_a_relayed_question_holds_back_no_quick_redispatch_and_a_rewritten_one_does(project, tx):
    """The question's mtime is held to the ask's recorded time, not the dispatch's whole-second dispatched_at: a BA
    re-dispatched within the 2 s freshness slack of its relayed question is not refused (replay CI, /dev clarify
    armed); a question it writes again after the ask is."""
    first = round_doc()
    put(project, ROUND1, first)
    tx.ask(first)
    tx.dispatch("ba", [CONTEXT])
    rel = put(project, rr.QUESTION.format(task=TASK, role="ba"), {
        "task_id": TASK, "role": "ba", "need": "n", "why": "w", "default": "A",
        "options": [{"label": "A", "description": "a"}, {"label": "B", "description": "b"}]})
    stamp = tx.clock.timestamp() + 0.5  # written while the dispatch ran
    os.utime(project / rel, (stamp, stamp))
    tx.tool("AskUserQuestion", {"questions": [], "metadata": {"source": f"producer-question:{TASK}:ba"}})
    tx.dispatch("ba", [CONTEXT])
    assert rr.ask_first(span(tx), project, obligation_doc("qa", [CONTEXT])) is None
    os.utime(project / rel, (tx.clock.timestamp() + 0.5,) * 2)  # the re-dispatched BA wrote it again
    assert rr.ask_first(span(tx), project, obligation_doc("qa", [CONTEXT])).startswith(f"ASK_FIRST: ask {rel} ")


def test_r5_outside_a_spec_or_dev_span_nothing_is_refused(project, tmp_path):
    other = TX(tmp_path / "close.jsonl")
    other.command("close")
    assert rr.ask_first(command_span.active_span(other.path), project, obligation_doc("qa", [CONTEXT])) is None


def test_r5_in_spec_the_task_is_the_dispatchs_own(project, tmp_path):
    spec = TX(tmp_path / "spec.jsonl")
    spec.command("spec")
    assert rr.ask_first(command_span.active_span(spec.path), project, obligation_doc("spec", [CONTEXT])).startswith(
        f"ASK_FIRST: no requirement round r1 of task {TASK}")


# ---------------------------------------------------------------- G2's stand-in: another round, no cap (D29)
def test_a_fresh_valid_next_round_stands_in_for_a_ba_analysis(project, tx):
    first = round_doc()
    put(project, ROUND1, first)
    tx.ask(first)
    ob = obligation_doc("ba", [CONTEXT])
    assert rr.stand_in(project, ob, span(tx)) is None  # r1 is not this dispatch's to stand in with
    put(project, ROUND2, round_doc(2, [q(1, "scope", "How far should it reach?")]))
    assert rr.stand_in(project, ob, span(tx)) == "valid"
    put(project, ROUND2, round_doc(2, [q(1, "scope", "How far should it reach?", assume="Perhaps")]))
    assert rr.stand_in(project, ob, span(tx))["reason"] == "requirement_round_invalid"
    stale = time.mktime((2026, 11, 9, 11, 0, 0, 0, 0, 0)) - time.timezone
    os.utime(project / ROUND2, (stale, stale))
    assert rr.stand_in(project, ob, span(tx)) is None
    assert rr.stand_in(project, obligation_doc("dev", [CONTEXT]), span(tx)) is None


def test_r7_a_text_ending_with_a_question(project):
    assert rr.ends_with_question("Done.\n\nShall I go on?  \n") and rr.ends_with_question("要继续吗？")
    assert not rr.ends_with_question("Is it? Yes, it is.") and not rr.ends_with_question("")


def test_r3_the_spec_window_lets_a_foreground_ba_through():
    import importlib.util
    spec = importlib.util.spec_from_file_location("spec_window", REPO / "hooks" / "pretool-spec-block-foreground-agent.py")
    window = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(window)
    assert [window._tool_is_exempt({"tool_input": {"subagent_type": t}}) for t in ("ba", "spec", "qa", "dev")] == [
        True, True, True, False]


def test_r5_a_second_producer_question_needs_its_own_ask_and_an_old_one_blocks_nothing(project, tx):
    """A5's gate half: the first ask does not cover a second question its producer wrote at the same path;
    a question older than its producer's latest dispatch was relayed already and refuses nothing."""
    first = round_doc()
    put(project, ROUND1, first)
    tx.ask(first)
    question = rr.QUESTION.format(task=TASK, role="ba")
    doc = {"task_id": TASK, "role": "ba", "need": "n", "why": "w", "default": "A",
           "options": [{"label": "A", "description": "a"}, {"label": "B", "description": "b"}]}
    source = {"metadata": {"source": f"producer-question:{TASK}:ba"}}
    def write(body):  # written by the dispatch that just came back, on the transcript's clock
        put(project, question, body)
        os.utime(project / question, (tx.clock.timestamp(),) * 2)

    tx.dispatch("ba", [CONTEXT])
    write(doc)
    tx.tool("AskUserQuestion", dict(source, questions=[]))
    assert rr.ask_first(span(tx), project, obligation_doc("ba", [CONTEXT])) is None
    tx.dispatch("ba", [CONTEXT])  # the re-dispatch writes its second question at the same path
    write(dict(doc, need="a second decision"))
    assert rr.ask_first(span(tx), project, obligation_doc("ba", [CONTEXT])).startswith(f"ASK_FIRST: ask {question}")
    tx.tool("AskUserQuestion", dict(source, questions=[]))
    assert rr.ask_first(span(tx), project, obligation_doc("ba", [CONTEXT])) is None
    tx.dispatch("ba", [CONTEXT])  # BA's report this time: the question file stays from before
    stale = time.mktime((2026, 11, 9, 11, 0, 0, 0, 0, 0)) - time.timezone
    os.utime(project / question, (stale, stale))
    assert rr.ask_first(span(tx), project, obligation_doc("qa", [CONTEXT])) is None
