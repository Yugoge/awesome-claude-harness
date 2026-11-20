"""A round's AskUserQuestion is compared with what the last landed write of its question file left (the record).

hooks/posttool-close-rating.py runs requirement_round.record_landed after the producer's Write, Edit or MultiEdit of
a round's question file; hooks/pretool-tool-policy.py's question_refusal compares the ask with that record alone and
reads no file of BA's. Each cell runs the two hooks as the CLI does, with the same project and state dir.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(HOOKS))
sys.path.insert(0, str(ROOT))
from lib import requirement_round as rr  # noqa: E402
from hooks.tests.test_requirement_round import TX, obligation_doc, round_doc, span, q  # noqa: E402

TASK = "20261109-120000"  # test_requirement_round's
ROUND1 = rr.ROUND.format(task=TASK, n=1)
PANEL = rr.PANEL.format(task=TASK)
SOURCE = f"requirement-round:{TASK}:r1"


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    (root / "docs" / "dev").mkdir(parents=True)
    (tmp_path / "state").mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(root))
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(tmp_path / "state"))
    return root


def _hook(name: str, payload: dict, project: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project), "PYTHONDONTWRITEBYTECODE": "1"}
    payload = {"session_id": "s", "cwd": str(project), "transcript_path": str(project / "t.jsonl"), **payload}
    return subprocess.run([sys.executable, str(HOOKS / name)], input=json.dumps(payload), capture_output=True,
                          text=True, env=env, timeout=60)


def write(project: Path, rel: str, doc: dict, tool: str = "Write") -> None:
    """The producer's call: the file lands, then its PostToolUse hook runs (a Bash write runs none)."""
    (project / rel).write_text(json.dumps(doc), encoding="utf-8")
    if tool != "Bash":
        tin = {"file_path": str(project / rel), **({"content": json.dumps(doc)} if tool == "Write" else
                                                   {"old_string": "a", "new_string": "b"})}
        done = _hook("posttool-close-rating.py", {"hook_event_name": "PostToolUse", "tool_name": tool,
                                                  "tool_input": tin, "agent_id": "a1", "agent_type": "ba",
                                                  "tool_response": {}}, project)
        assert done.returncode == 0 and not done.stdout, done.stderr


def ask(project: Path, questions) -> subprocess.CompletedProcess:
    (project / "t.jsonl").touch()
    return _hook("pretool-tool-policy.py", {"hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion",
                                            "tool_input": {"questions": questions, "metadata": {"source": SOURCE}}},
                 project)


def test_written_then_asked_verbatim_passes_and_a_paraphrase_is_refused(project):
    doc = round_doc()
    write(project, ROUND1, doc)
    assert ask(project, rr.ask_view(doc)).returncode == 0
    para = [{**rr.ask_view(doc)[0], "question": "Something else?"}] + rr.ask_view(doc)[1:]
    refused = ask(project, para)
    assert refused.returncode == 2 and f"asks otherwise than {ROUND1} holds" in refused.stderr, refused.stderr


def test_asked_before_written_is_refused_naming_write_and_then_passes(project):
    doc = round_doc()
    early = ask(project, rr.ask_view(doc))
    assert early.returncode == 2 and "with the Write tool" in early.stderr and ROUND1 in early.stderr, early.stderr
    write(project, ROUND1, doc)
    assert ask(project, rr.ask_view(doc)).returncode == 0


def test_the_record_follows_the_last_landed_write(project):
    first, second = round_doc(), round_doc(questions=[q(1, "intent", "What changes for you?")])
    write(project, ROUND1, first)
    write(project, ROUND1, second, tool="Edit")
    assert ask(project, rr.ask_view(first)).returncode == 2
    assert ask(project, rr.ask_view(second)).returncode == 0
    (project / ROUND1).write_text("{not json")
    write(project, ROUND1, {}, tool="Bash")  # unseen: the record stays the last landed write's
    assert ask(project, rr.ask_view(second)).returncode == 0
    (project / ROUND1).write_text("{not json")
    _hook("posttool-close-rating.py", {"hook_event_name": "PostToolUse", "tool_name": "Write", "tool_response": {},
                                       "tool_input": {"file_path": str(project / ROUND1), "content": "{not json"}},
          project)
    assert ask(project, rr.ask_view(second)).returncode == 2  # a landed file that does not load records nothing


def test_a_panel_is_round_1s_file_until_a_round_file_lands(project):
    panel, own = round_doc(), round_doc(questions=[q(1, "scope", "Which pages?")])
    write(project, PANEL, panel)
    assert ask(project, rr.ask_view(panel)).returncode == 0
    write(project, ROUND1, own)
    assert ask(project, rr.ask_view(own)).returncode == 0 and ask(project, rr.ask_view(panel)).returncode == 2


def test_a_file_written_through_bash_has_no_record_and_the_write_route_passes(project):
    doc = round_doc()
    write(project, ROUND1, doc, tool="Bash")
    refused = ask(project, rr.ask_view(doc))
    assert refused.returncode == 2 and "written through Bash leaves no record" in refused.stderr, refused.stderr
    write(project, ROUND1, doc)
    assert ask(project, rr.ask_view(doc)).returncode == 0


def test_a_round_answered_before_the_record_existed_is_not_asked_again(project, tmp_path):
    """The later steps read the round file and the transcript as before: G1's ask_first passes a dispatch after
    an ask the transcript holds, with no record (a session from before the record) and no new ask."""
    tx = TX(tmp_path / "session.jsonl")
    tx.command("dev", context="DEV_SESSION_ID pre-initialized by hook: dev-20261109-120000\n")
    doc = round_doc()
    tx.dispatch("ba", [ROUND1])
    (project / ROUND1).write_text(json.dumps(doc), encoding="utf-8")
    tx.ask(doc)
    assert not any(Path(os.environ["CLAUDE_STATE_DIR"]).iterdir())
    assert rr.ask_first(span(tx), project, obligation_doc("ba", [f"docs/dev/context-{TASK}.json"])) is None
