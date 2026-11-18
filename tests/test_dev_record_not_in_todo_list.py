"""commands/dev.md Steps 9 and 10: what the orchestrator records about graphify's run and the test-writer
gate goes where the hooks let it, never into the todo list.

The /dev todo list is the canonical one (scripts/todo/dev.py), and hooks/pretool-todo-validate.py
refuses a TodoWrite that changes a step's text or the list's length: past the span's first list a call
may change only statuses. A list that carries the graphify status or the test-writer skip reason, in a
step's text or as a step of its own, is refused, so the text must not ask for one. Each case hands
such a list to that hook in a /dev span with Step 9 in progress and asserts on its answer.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "pretool-todo-validate.py"
TEXT = (ROOT / "commands" / "dev.md").read_text(encoding="utf-8")


def _step(n: int) -> str:
    m = re.search(rf"^### Step {n}:.*?(?=^### Step )", TEXT, flags=re.M | re.S)
    assert m, f"commands/dev.md has no Step {n}"
    return m.group(0)


def _canonical() -> list:
    return json.loads(subprocess.run([sys.executable, str(ROOT / "scripts" / "todo" / "dev.py")],
                                     capture_output=True, text=True, check=True).stdout)


def _frontier(n: int) -> list:
    out = _canonical()
    for i, item in enumerate(out):
        item["status"] = "completed" if i < n else ("in_progress" if i == n else "pending")
    return out


def _index(label: str) -> int:
    return next(i for i, item in enumerate(_canonical()) if item["content"].startswith(f"{label}:"))


class _Span:
    """A /dev span whose list stands at Step 9 in progress, every earlier subagent step's dispatch back."""

    def __init__(self, tmp: Path) -> None:
        self.tmp, self.sid, self.ids = tmp, str(uuid.uuid4()), 0
        self.path = tmp / f"{self.sid}.jsonl"
        self.project = tmp / "project"
        (self.project / ".claude").mkdir(parents=True)
        self._add({"type": "user", "message": {"role": "user", "content": "/dev fix the bug"}})
        steps = _frontier(0)
        for n in range(_index("Step 9") + 1):
            role = (steps[n - 1].get("subagent_call") or {}).get("subagent_type") if n else None
            if role:
                self._result(self._use("Agent", {"subagent_type": role, "prompt": "x", "description": role}))
            self._result(self._use("TodoWrite", {"todos": _frontier(n)}))
        self._result(self._use("Agent", {"subagent_type": "graphify", "prompt": "x", "description": "graphify"}))

    def _add(self, record: dict) -> None:
        with self.path.open("a") as handle:
            handle.write(json.dumps(record) + "\n")

    def _use(self, name: str, tool_input: dict) -> str:
        self.ids += 1
        tid = f"toolu_{self.ids:04d}"
        self._add({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tid, "name": name, "input": tool_input}]}})
        return tid

    def _result(self, tid: str) -> None:
        self._add({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tid, "content": "ok"}]}})

    def todo_write(self, todos: list) -> subprocess.CompletedProcess:
        tid = self._use("TodoWrite", {"todos": todos})
        payload = {"session_id": self.sid, "transcript_path": str(self.path), "hook_event_name": "PreToolUse",
                   "tool_name": "TodoWrite", "tool_input": {"todos": todos}, "tool_use_id": tid}
        home = self.tmp / "home"
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.project), "HOME": str(home),
               "CLAUDE_CONFIG_DIR": str(home / ".claude"), "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True,
                              text=True, env=env, cwd=self.project, timeout=60)


@pytest.mark.parametrize("step, record", [
    (9, "graphify status: ok"),
    (10, "test_writer_expected = false: stale acceptance criteria"),
])
def test_the_step_records_where_the_todo_hook_lets_it(tmp_path: Path, step: int, record: str) -> None:
    """The hook takes Step 9's completion as a status change and refuses the record in a step's text or
    as a step of its own; the step's text puts the record in the reply and names that hook."""
    nine = _index("Step 9")
    assert _Span(tmp_path / "status").todo_write(_frontier(nine + 1)).returncode == 0

    in_text = _frontier(nine + 1)
    in_text[nine]["content"] += f" ({record})"
    refused = _Span(tmp_path / "text").todo_write(in_text)
    assert refused.returncode == 2 and "keep the text and the order" in refused.stderr

    as_step = _frontier(nine + 1)
    as_step.insert(nine + 1, {"content": record, "activeForm": "Recording it", "status": "completed"})
    refused = _Span(tmp_path / "step").todo_write(as_step)
    assert refused.returncode == 2 and "count mismatch" in refused.stderr

    text = _step(step)
    assert not re.search(r"\b(?:record|add|write)\b[^.]*\bin the todo list\b", text), text[:60]
    assert "`hooks/pretool-todo-validate.py`" in text
    assert re.search(r"state (?:it|the reason) in your reply", text)
