"""commands/dev.md: a relayed producer question has one route when it goes unanswered, and the dev
re-dispatch carries the answer the same way as Step 5's BA re-dispatch (group 3 findings on #27:
c6735512020 item 2, c6737075938 item 2). Since P13-1 (#38) the answer of record is the file the
AskUserQuestion hook writes, so an unanswered question, which writes none, is carried as
`Previous answers: none`.

Each case runs that hook (hooks/posttool-close-rating.py, lib/requirement_round.py's handle) with the
question file, `metadata.source` and answer path that Step 5 (BA) and Step 12 (dev) spell: an answered
relay writes the answer file the step names, and a skipped or declined one writes none. Where the
re-dispatch lines sit (`Clarification round:` / `Previous answers:` after `Context file:`) is played by
the replay's /dev devquestion run (tests/replay/drivers/dev.py), and agents/dev.md's sentence about that
line is read by no code, so neither has a test here."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "posttool-close-rating.py"
TASK = "20261109-120000"
UNANSWERED = {"skipped": {"answers": {}}, "declined": "User declined to answer questions"}


def _step(text: str, n: int) -> str:
    m = re.search(rf"^### Step {n}:.*?(?=^### Step )", text, flags=re.M | re.S)
    assert m, f"commands/dev.md has no Step {n}"
    return m.group(0)


def _spelled(step: str, role: str) -> dict:
    """The question file, the relay's metadata.source and the answer file the step spells for `role`."""
    bind = {"<timestamp>": TASK}
    found = {
        "question": re.search(rf"`(docs/dev/producer-question-<timestamp>-{role}\.json)`", step),
        "source": re.search(rf"`(producer-question:<timestamp>:{role})`", step),
        "answer": re.search(rf"`(docs/dev/producer-answer-<timestamp>-{role}-<q8>\.json)`", step),
    }
    assert all(found.values()), {k: bool(v) for k, v in found.items()}
    spelled = {}
    for key, match in found.items():
        value = match.group(1)
        for slot, bound in bind.items():
            value = value.replace(slot, bound)
        spelled[key] = value
    return spelled


def _relay(project: Path, source: str, questions: list, response) -> None:
    payload = {"session_id": "s", "transcript_path": "/nonexistent.jsonl", "cwd": str(project),
               "hook_event_name": "PostToolUse", "tool_name": "AskUserQuestion",
               "tool_input": {"questions": questions, "metadata": {"source": source}},
               "tool_use_id": "toolu_ask", "tool_response": response}
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(project.parent),
           "CLAUDE_CONFIG_DIR": str(project.parent / "config"), "CLAUDE_PROJECT_DIR": str(project),
           "LANG": "C.UTF-8"}
    run = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), env=env, capture_output=True,
                         text=True, timeout=60)
    assert (run.returncode, run.stdout, run.stderr) == (0, "", "")


@pytest.mark.parametrize("role,n", [("ba", 5), ("dev", 12)])
def test_the_relay_writes_the_answer_file_the_step_names_and_none_unanswered(tmp_path, role, n):
    spelled = _spelled(_step((ROOT / "commands" / "dev.md").read_text(encoding="utf-8"), n), role)
    project = tmp_path / "project"
    question = project / spelled["question"]
    question.parent.mkdir(parents=True)
    question.write_text(json.dumps({"task_id": TASK, "role": role, "need": "one decision", "default": "A"}))
    q8 = hashlib.sha256(question.read_bytes()).hexdigest()[:8]
    asked = [{"question": "Which?", "header": "Decision", "multiSelect": False,
              "options": [{"label": "A", "description": ""}, {"label": "B", "description": ""}]}]

    for response in UNANSWERED.values():
        _relay(project, spelled["source"], asked, response)
    assert sorted(p.name for p in question.parent.iterdir()) == [question.name]

    _relay(project, spelled["source"], asked, {"questions": asked, "answers": {"Which?": "B"}})
    answer = project / spelled["answer"].replace("<q8>", q8)
    record = json.loads(answer.read_text(encoding="utf-8"))
    assert (record["source"], record["answers"]) == (spelled["source"], {"Which?": "B"})
    assert sorted(p.name for p in question.parent.iterdir()) == sorted([question.name, answer.name])
