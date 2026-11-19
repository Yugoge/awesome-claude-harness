"""Every reader of a session or agent transcript answers the same with the CLI's api-request-blob records in
it as without them (C3).

CLI 2.1.322 writes, before each model request, an api-request-blob record for each message of the request
not written before: the message as sent, its tool_use and tool_result blocks with their ids
(tests/fixtures/cli-request-copies, a real excerpt). A call's copy follows its result; the messages of a
turn no request followed (an agent's last run), the next prompt. A reader that took the content of any
record read each call twice: G1's order rule took a returned dispatch's copy for a dispatch with no result
(test_obligation_gate_returns.py). Calls and results are read through one reading,
lib/command_span._blocks: the content of a user or assistant record, never of another record.

Each case below builds one session (a /commit span: a close QA dispatch that returned, a background one
that ended in its notification, a Write, then the planning dispatch in flight) and the first QA's own
transcript (two runs, each ending in a SubagentHandback), copies both, writes the CLI's copies into the
copy (tests/cli_shapes.with_request_copies), and asks one reader the same question of both. A line a
reader gives is compared by the kind of record it names, the lines themselves having moved.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

import test_obligation_gate_returns as g1  # noqa: E402  (hooks/tests on sys.path)

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "hooks"))
from tests import cli_shapes  # noqa: E402
from tests.cli_shapes import synthesize  # noqa: E402
from lib import (agent_returns, command_span, dispatch_template, final_report, obligation,  # noqa: E402
                 report_provenance, score_events, send_policy, subagent_restart)

REPORTS = ("the first run's report", "the second run's report")


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _agent_records(qa_agent: str, cwd: Path) -> list:
    """The QA's own transcript: its dispatch prompt, a Write, a handback; resumed, a second handback."""
    prompt = cli_shapes.recording("subagent")[0]
    out = [prompt]
    for n, report in enumerate(REPORTS):
        if n:
            out.append(dict(prompt, uuid=f"resume-{n}"))
        for name, tool_input in (("Write", {"file_path": f"docs/dev/note-{n}.md", "content": report}),
                                 ("SubagentHandback", {"message": report})):
            use = synthesize("subagent:assistant", "tool_use")
            g1._block_of(use, "tool_use").update(id=f"toolu_own_{n}_{name}", name=name, input=tool_input)
            result = synthesize("subagent:user", "tool_result")
            g1._block_of(result, "tool_result").update(tool_use_id=f"toolu_own_{n}_{name}", content="ok",
                                                       is_error=False)
            out += [use, result]
    return [dict(rec, agentId=qa_agent, cwd=str(cwd)) if "cwd" in rec else dict(rec, agentId=qa_agent) for rec in out]


def _world(root: Path) -> dict:
    project = root / "project"
    project.mkdir(parents=True)
    s = g1.Session(project)
    s.command("commit")
    s.say()
    qa = s.qa()
    s.returned(qa)
    background = s.qa(background=True)
    s.launched(background)
    s.say()
    s.notified(background)
    s.result(s.use("Write", {"file_path": str(project / "docs" / "dev" / "plan.md"), "content": "plan"}),
             "tool_result")
    s.say()
    s.agent_files(qa, _agent_records(g1.QA_AGENT, project))
    payload = s.payload()
    return {"main": Path(payload["transcript_path"]), "project": project, "qa": qa, "background": background,
            "agent": next(project.glob("*/subagents/*.jsonl"))}


@pytest.fixture(scope="module")
def worlds(tmp_path_factory):
    root = tmp_path_factory.mktemp("copies")
    plain = _world(root / "plain")
    shutil.copytree(root / "plain", root / "copied")
    copied = {k: (root / "copied" / v.relative_to(root / "plain")) if isinstance(v, Path) else v
              for k, v in plain.items()}
    for path in (copied["main"], copied["agent"]):  # the same records, at the copy's paths, with the CLI's copies
        path.write_text(path.read_text().replace(str(root / "plain"), str(root / "copied")))
        cli_shapes.add_request_copies(path)
    return plain, copied


def _kind(path: Path, line) -> str | None:
    """The type of the record on 1-based line ``line`` of ``path`` (None for no line)."""
    if not line:
        return None
    return json.loads(path.read_text().splitlines()[line - 1]).get("type")


def span_calls(w):
    span = command_span.active_span(str(w["main"]))
    return [(c.id, c.name, c.ok, _kind(w["main"], c.line), _kind(w["main"], c.result_line)) for c in span.calls()]


def span_texts(w):
    span = command_span.active_span(str(w["main"]))
    return (span.last_text(), [(e.tool_use_id, e.status) for e in span.agent_ends()],
            [(c, a) for _n, c, a in command_span.openers(str(w["main"]))])


def agent_returns_lines(w):
    span = command_span.active_span(str(w["main"]))
    returns = agent_returns.Returns(span, g1.SID, g1.DISPATCH, str(w["main"]))
    return [(c.id, _kind(w["main"], returns.line(c))) for c in span.calls("Agent")], \
        agent_returns._final_reply(w["agent"]) is not None


def write_set(w):
    return (command_span.write_set(str(w["main"]), w["project"]),
            command_span.write_set(str(w["agent"]), w["project"], main_only=False))


def tool_policy_dispatches(w):
    policy = _load("tool_policy_copies", "hooks/pretool-tool-policy.py")
    record = policy._Record(str(w["main"]))
    try:
        calls = policy._dispatch_calls(record)
        found = record.find_call(w["qa"], calls[0].input["prompt"])
        return [c.id for c in calls], _kind_at_offset(w["main"], found.line)
    finally:
        record.close()


def _kind_at_offset(path: Path, offset: int) -> str:
    data = path.read_bytes()
    return json.loads(data[offset:data.index(b"\n", offset)]).get("type")


def aggregate_prior_stages(w):
    check = _load("aggregate_check_copies", "hooks/pretool-aggregate-check.py")
    found = check._scan_transcript_for_prior_obligations(str(w["main"]), obligation.task_family(g1.TASK), g1.DISPATCH)
    return [(e["obligation"]["role"], _kind(w["main"], e["line"])) for e in found]


def artifact_contract_call_texts(w):
    return _load("contract_copies", "hooks/subagentstop-artifact-contract-enforce.py")._tool_call_texts(str(w["agent"]))


def dispatch_template_of(w):
    return dispatch_template.dispatch_of(w["agent"])


def handback(w):
    return final_report.handback_message(w["agent"])


def first_prompt(w):
    return obligation.read_first_record_prompt(w["agent"])


def restart_parent_calls(w):
    calls, results, notes = subagent_restart._read_parent_calls(w["main"])
    return ({k: _kind(w["main"], v["line"]) for k, v in calls.items()}, {k: len(v) for k, v in results.items()},
            {k: (v["status"], _kind(w["main"], v["line"])) for k, v in notes.items()})


def dispatch_obligations(w):
    return [(d["tool_use_id"], _kind(w["main"], d["line"])) for d in obligation.dispatch_obligations(w["main"])]


def provenance_session(w):
    reading = report_provenance._session_reading(str(w["main"]))
    return reading["notified"], {k: (v[0], v[2] is not None) for k, v in reading["calls"].items()}, reading["order"]


def provenance_own_write(w):
    (w["project"] / "docs" / "dev").mkdir(parents=True, exist_ok=True)
    (w["project"] / "docs" / "dev" / "note-1.md").write_text(REPORTS[1])
    return report_provenance.own_write(str(w["agent"]), w["project"], "docs/dev/note-1.md")


def score_walk(w):
    return [(b.get("type"), b.get("id") or b.get("tool_use_id")) for b in score_events._walk({"sub": str(w["agent"])})]


def send_children(w):
    kids, names = send_policy.children(str(w["main"]))
    return {k: (v.get("tool_use_id"), v.get("finished")) for k, v in kids.items()}, names


def orchestrator_refused_results(w):
    gate = _load("orchestrator_copies", "hooks/pretool-orchestrator-gate.py")
    return gate.refused_results(str(w["main"]), {w["qa"], w["background"]})


def execute_push_commit_span(w):
    sys.path.insert(0, str(REPO / "hooks" / "lib"))
    return _load("execute_push_copies", "scripts/execute-push.py")._in_commit_span(w["main"], w["qa"])


READERS = [span_calls, span_texts, agent_returns_lines, write_set, tool_policy_dispatches, aggregate_prior_stages,
           artifact_contract_call_texts, dispatch_template_of, handback, first_prompt, restart_parent_calls,
           dispatch_obligations, provenance_session, provenance_own_write, score_walk, send_children,
           orchestrator_refused_results, execute_push_commit_span]


@pytest.mark.parametrize("reader", READERS, ids=lambda r: r.__name__)
def test_a_reader_answers_the_same_with_the_cli_s_request_copies(worlds, reader):
    plain, copied = worlds
    assert '"api-request-blob"' in copied["main"].read_text() and '"api-request-blob"' in copied["agent"].read_text()
    assert reader(copied) == reader(plain)


def test_the_cases_ask_what_they_mean_to(worlds):
    """The plain world holds what the readers are asked about: each call once, the second run's report."""
    plain, _copied = worlds
    assert [c[0] for c in span_calls(plain)] == [plain["qa"], plain["background"], "toolu_0003", g1.DISPATCH]
    assert handback(plain) == REPORTS[1]
    assert [role for role, _kind in aggregate_prior_stages(plain)] == ["qa", "qa"]
    assert provenance_own_write(plain) is True
