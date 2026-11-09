"""The routing record a bundled BA or QA dispatch writes (agents/ba.md, agents/qa.md No-Multitasking Rule).

A BA or QA handed several issues stops before any analysis and replies `multi_issue_fanout_requested`;
the producer stop gate (subagentstop-artifact-contract-enforce.py) still refuses that stop until the
artifacts the dispatch declares are valid, and subagentstop-e2e-enforce.py refuses a final QA without a
justified E2E status. These tests write exactly the record each agent file describes, for the obligations
commands/dev.md Steps 4, 7 and 13 declare, and run both hooks as Claude Code calls them at SubagentStop.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
G2 = REPO / "hooks" / "subagentstop-artifact-contract-enforce.py"
E2E = REPO / "hooks" / "subagentstop-e2e-enforce.py"
TS = "20990101-000001"
LANE = TS + "-l1"
REQDOC = f"docs/dev/user-requirement-dev-{TS}.md"
PAYLOAD = {"issues": [{"requirement_id": "r1", "text": "fix A"}, {"requirement_id": "r2", "text": "fix B"}]}
REPLY = {"ba": f"TASK-ID: {TS}\nstatus: multi_issue_fanout_requested\n{json.dumps(PAYLOAD)}",
         "qa": f"verdict: multi_issue_fanout_requested\n{json.dumps(PAYLOAD)}"}


def _rule(role: str) -> str:
    text = (REPO / "agents" / f"{role}.md").read_text(encoding="utf-8")
    return next(line for line in text.splitlines() if line.startswith("**No-Multitasking Rule**"))


def _json(kind, task, schema, identity):
    return {"kind": "json", "path": f"docs/dev/{kind}-{task}.json", "schema": schema,
            "identity": {key: task for key in identity}}


def _obligation(role, profile, task, artifacts):
    lane = profile == "fanout-lane"
    return {"task_id": task, "lane": "l1" if lane else None, "lane_set": ["l1", "l2"] if lane else None,
            "role": role, "pipeline": "dev", "profile": profile,
            "dispatched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "artifacts": artifacts}


def _ba(task, profile):
    ob = _obligation("ba", profile, task, [
        _json("context", task, "context.v1", ("task_id", "request_id")),
        {"kind": "markdown", "path": f"docs/dev/ticket-{task}.md", "identity_anchor": task},
        _json("acceptance-criteria", task, "acceptance-criteria.v1", ("task_id", "request_id"))])
    ids = {"task_id": task, "request_id": task}
    return ob, {  # agents/ba.md: the routing record
        f"docs/dev/context-{task}.json": dict(
            ids, requirement="fix A; also fix B", root_cause_analysis={"affected_files": [REQDOC]},
            development_approach={}, complexity_tier="MICRO", risk_level="low", test_writer_expected=False,
            multi_issue_fanout_requested=PAYLOAD),
        f"docs/dev/ticket-{task}.md": f"{task} multi_issue_fanout_requested: r1 fix A; r2 fix B\n",
        f"docs/dev/acceptance-criteria-{task}.json": dict(ids, acceptance_criteria=[])}


def _ba_qa(task, profile):
    ob = _obligation("qa", profile, task, [_json("ba-qa-report", task, "ba-qa-report.v1", ("task_id",))])
    return ob, {f"docs/dev/ba-qa-report-{task}.json": {  # agents/qa.md: the routing record, BA validation
        "task_id": task, "verdict": "fail", "objections": [],
        "summary": "multi_issue_fanout_requested: two issues, nothing validated",
        "multi_issue_fanout_requested": PAYLOAD}}


def _qa(task, profile):
    ob = _obligation("qa", profile, task, [_json("qa-report", task, "qa-report.v2", ("task_id", "request_id"))])
    report = {"report_version": 2, "task_id": task, "request_id": task, "timestamp": "2099-01-01T00:00:01Z",
              "multi_issue_fanout_requested": PAYLOAD,
              "qa": {"status": "fail", "e2e_enforcement": {
                  "status": "legitimately_skipped", "blocking_reason": "multi_issue_fanout_requested"}}}
    if ob["lane"]:
        report.update(lane=ob["lane"], lane_set=ob["lane_set"])
    return ob, {f"docs/dev/qa-report-{task}.json": report}  # agents/qa.md: the routing record, final QA


CASES = {"ba singular": ("ba", _ba, TS, "singular"), "ba fanout-lane": ("ba", _ba, LANE, "fanout-lane"),
         "qa ba_validation": ("qa", _ba_qa, TS, "ba_validation"),
         "qa final_verification": ("qa", _qa, TS, "final_verification"),
         "qa fanout-lane": ("qa", _qa, LANE, "fanout-lane")}


def _stop(tmp_path: Path, role: str, ob: dict, files: dict) -> list[subprocess.CompletedProcess]:
    """Write the dispatch transcript and the agent's files, then run the hooks Claude Code runs at its stop."""
    home, project, session, agent = tmp_path / "home", tmp_path / "project", "session-routing-1", "a0routing01"
    registry = project / ".claude" / "dev-registry" / f"dev-{TS}"
    registry.mkdir(parents=True)
    for flag in ("e2e-enforce.json", "artifact-contract-enforce.json"):
        (registry / flag).write_text('{"enabled": true}', encoding="utf-8")
    prompt = f"User requirement document: {REQDOC}\n<obligation v=\"1\">\n{json.dumps(ob)}\n</obligation>\n"
    transcript = home / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(project)) / session
    transcript = transcript / "subagents" / f"agent-{agent}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n",
                          encoding="utf-8")
    for rel, body in files.items():
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
    payload = {"session_id": session, "hook_event_name": "SubagentStop", "stop_hook_active": False,
               "agent_id": agent, "agent_type": role, "agent_transcript_path": str(transcript),
               "cwd": str(project), "last_assistant_message": REPLY[role]}
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "ARTIFACT_CONTRACT"))}
    env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), CLAUDE_PROJECT_DIR=str(project),
               CLAUDE_STATE_DIR=str(tmp_path / "state"), CLAUDE_OBLIGATION_STOPGATE="block")
    return [subprocess.run([sys.executable, str(hook)], input=json.dumps(payload), capture_output=True,
                           text=True, env=env, cwd=project, timeout=60)
            for hook in ((G2, E2E) if role == "qa" else (G2,))]


@pytest.mark.parametrize("case", CASES)
def test_the_routing_record_each_agent_file_describes_lets_it_stop(tmp_path, case):
    role, build, task, profile = CASES[case]
    for result in _stop(tmp_path, role, *build(task, profile)):
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("case", CASES)
def test_the_reply_alone_is_refused(tmp_path, case):
    role, build, task, profile = CASES[case]
    ob, _files = build(task, profile)
    assert _stop(tmp_path, role, ob, {})[0].returncode == 2


def test_a_qa_question_stands_in_for_nothing(tmp_path):
    ob, _files = _ba_qa(TS, "ba_validation")
    question = {"task_id": TS, "role": "qa", "need": "n", "options": [{"label": "a", "description": "a"},
                {"label": "b", "description": "b"}], "default": "a", "why": "w"}
    result = _stop(tmp_path, "qa", ob, {f"docs/dev/producer-question-{TS}-qa.json": question})[0]
    assert result.returncode == 2 and "producer_question_invalid" in result.stderr


@pytest.mark.parametrize("role, phrases", [
    ("ba", ("`status: multi_issue_fanout_requested`", "`requirement` (the bundled text verbatim)",
            "`root_cause_analysis.affected_files` holds your dispatch's requirement document",
            "`development_approach` `{}`", "`complexity_tier` `MICRO`", "`risk_level` `low`",
            "`test_writer_expected` `false`", "an empty `acceptance_criteria`",
            "a top-level `multi_issue_fanout_requested`", "this routing asks nobody")),
    ("qa", ("`verdict: multi_issue_fanout_requested`", "`verdict` `fail`, empty `objections`",
            "`qa.status` `fail`", "`qa.e2e_enforcement` `{status: legitimately_skipped",
            "a top-level `multi_issue_fanout_requested`", "`lane` and `lane_set`",
            "schemas/producer-question.v1.json")),
])
def test_the_agent_file_names_the_record(role, phrases):
    rule = _rule(role)
    assert [p for p in phrases if p not in rule] == []
    assert "STOP before doing any analysis" in rule
