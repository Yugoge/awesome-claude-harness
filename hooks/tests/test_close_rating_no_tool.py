"""/close Step 4 in a session that offers no AskUserQuestion (#27 item 1, D25: no dead end).

The Stop gate cannot know a session's tools: the Stop payload carries none, and the CLI's transcript
records no tool list (only deferred-tool deltas; measured on a CLI 2.1.322 session transcript). What it
can read is what the CLI writes for a call: the CLI answers a call to a tool it does not offer with its
own error tool_result, `<tool_use_error>Error: No such tool available: <name></tool_use_error>`,
is_error true, before any hook runs (static read of the 2.1.322 bundle, the unknown-tool branch of its
tool runner). close_rating.rating_asked counts any tool_result as asked (D9b), so that error is a
complete Step 4, as a denial is.

The dead end was the text: Step 4 named Skip, no answer and a denial, and nothing for a session without
the tool, so its agent made no call (group 3's `rating=none`: it says so in text) and the gate kept
"the close-rating question (AskUserQuestion) was not asked" until /stop. close.md Step 4 now has every
session make the call; the question printed in text instead is still held, so a session WITH the tool
must ask.

Run with: python3 -m pytest hooks/tests/test_close_rating_no_tool.py -q
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TASK = "20261101-090000"
SID = "11111111-2222-3333-4444-555555555555"
# The CLI's answer to a call of a tool it does not offer (CLI 2.1.322, the unknown-tool branch).
NO_SUCH_TOOL = "<tool_use_error>Error: No such tool available: AskUserQuestion</tool_use_error>"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load(REPO / "hooks" / "stop-command-gate.py", "stop_command_gate_no_tool_under_test")
todo_canonical = importlib.import_module("lib.todo_canonical")
close_rating = importlib.import_module("lib.close_rating")
command_span = gate.command_span
STEP4 = (REPO / "commands" / "close.md").read_text(encoding="utf-8").split("### Step 4:", 1)[1].split("\n## ", 1)[0]
RATING = json.loads(STEP4.split("```json", 1)[1].split("```", 1)[0].replace("<task-id>", TASK))


class TX:
    def __init__(self, path: Path):
        self.path, self.n = path, 0
        path.write_text("", encoding="utf-8")

    def add(self, record: dict) -> None:
        record.setdefault("sessionId", SID)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    def tool(self, name: str, tool_input: dict, ok: bool = True, result="ok", own=None) -> None:
        self.n += 1
        ident = f"toolu_{self.n:04d}"
        self.add({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": ident, "name": name, "input": tool_input}]}})
        self.add({"type": "user", **({"toolUseResult": own} if own is not None else {}), "message": {
            "role": "user", "content": [{"type": "tool_result", "tool_use_id": ident, "content": result,
                                         **({} if ok else {"is_error": True})}]}})

    def say(self, text: str) -> None:
        self.add({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}})


@pytest.fixture
def landed(tmp_path, monkeypatch):
    """/close <task> through its landed close QA and Session Summary, every TodoStep completed; the
    disposition is chain_pass (a stand-in resolver), the close rating is P4's real module."""
    project = tmp_path / "project"
    (project / "docs" / "dev").mkdir(parents=True)
    (project / "docs" / "dev" / f"ticket-{TASK}.md").write_text(f"# Ticket\n\n**TASK-ID**: `{TASK}`\n")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CLAUDE_CODE_ENABLE_TODO_TOOLS", "1")
    monkeypatch.delenv("CLAUDE_COMPAT_RUNTIME", raising=False)
    overnight = types.ModuleType("lib.overnight")
    overnight.session_state_file = lambda session_id, starts: (None, None)
    monkeypatch.setitem(sys.modules, "lib.overnight", overnight)
    monkeypatch.setattr(gate, "_SCRIPTS", {"scripts/resolve-dev-artifact-chain.py": types.SimpleNamespace(
        disposition_lines=lambda root, task, stage: [])})
    tx = TX(tmp_path / f"{SID}.jsonl")
    tx.add({"type": "queue-operation", "operation": "enqueue", "content": f"/close {TASK}"})
    tx.add({"type": "user", "message": {"role": "user", "content":
            f"<command-message>close is running…</command-message>\n<command-name>/close</command-name>\n"
            f"<command-args>{TASK}</command-args>"}})
    steps = todo_canonical.run_todo_script("close", TASK)
    tx.tool("TodoWrite", {"todos": [{"content": s["content"], "activeForm": s.get("activeForm", ""),
                                     "status": "completed"} for s in steps]})
    doc = {"task_id": TASK, "role": "qa", "pipeline": "close", "profile": "final_verification",
           "dispatched_at": "2026-11-01T09:00:00Z",
           "artifacts": [{"kind": "markdown", "path": f"docs/dev/close-report-{TASK}.md",
                          "identity_anchor": TASK, "terminal_line_regex": "^CLOSE: YES.*$"}],
           "consistency": "verdict_class"}
    tx.tool("Agent", {"subagent_type": "qa", "description": "close QA",
                      "prompt": f'<obligation v="1">{json.dumps(doc)}</obligation>\njudge'},
            result="Judged.\nCLOSE: YES")
    assert close_rating.rating_required(command_span.active_span(tx.path), TASK)  # the close landed
    tx.say(f"CLOSE: YES\n## Session Summary\n- Accomplished: the change.\nNext: /commit {TASK} -m \"s\"")
    payload = {"session_id": SID, "transcript_path": str(tx.path), "cwd": str(project),
               "hook_event_name": "Stop", "stop_hook_active": False}
    return types.SimpleNamespace(tx=tx, payload=payload)


def test_the_hold_on_a_session_that_made_no_call(landed):
    """The reproduction (group 3's `rating=none`): no call, the reason said in text. Held, and held
    still: the gate has no fact that tells this session from one that offers the tool."""
    landed.tx.say(f"Step 4: AskUserQuestion is not available in this session; the rating question for {TASK} "
                  "cannot be asked.")
    code, text = gate.decide(landed.payload, "block")
    assert code == 2 and f"close {TASK}: the close-rating question (AskUserQuestion) was not asked" in text, text


def test_the_question_printed_in_text_is_not_asked(landed):
    """A session WITH the tool must ask: the question in prose, options and all, does not stand in for it."""
    q = RATING["questions"][0]
    landed.tx.say(q["question"] + "\n" + "\n".join(o["label"] for o in q["options"]))
    assert gate.decide(landed.payload, "block")[0] == 2


def test_the_call_the_cli_answers_with_no_such_tool_completes_step_4(landed):
    """Step 4's own call (its JSON block) in a session that does not offer the tool: the CLI's error,
    which no hook sees, is a complete Step 4."""
    landed.tx.tool("AskUserQuestion", RATING, ok=False, result=NO_SUCH_TOOL,
                   own="Error: No such tool available: AskUserQuestion")
    assert gate.decide(landed.payload, "block") == (0, "")


def test_close_md_step_4_has_a_session_without_the_tool_make_the_call():
    """The text side of the fix: before it, Step 4 named no form for a session without the tool."""
    flat = " ".join(STEP4.split())
    assert ("A session whose tool list has no AskUserQuestion (headless, or a client without it) makes the "
            "same call all the same") in flat
    assert "`No such tool available: AskUserQuestion`, and that error is a complete Step 4 too" in flat
    assert "A deferred AskUserQuestion is offered: load it, then ask." in flat
    assert "The question is never printed in text in its place." in flat
