"""OB-L40: a TodoWrite foreign to the command, once its checklist is all completed.

pretool-todo-validate.py held every TodoWrite of a span to the canonical list, so once a command's
checklist was all completed (the span lasts until the next typed command) a list of the session's own,
sharing no step with the command, was refused as "BLOCKED TodoWrite (canonical validation)". Rule 8
lets such a list run, and every reader of the span (lib.todo_canonical.checklist_lists: the lock,
Gate 4, the Stop gate, the step label, the overnight loop) keeps reading the checklist itself, so a
foreign list neither reopens nor stands in for it. A list that reuses a step's text, a list while the
checklist is still open, and a later command's first list stay held to the canonical list.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / "hooks"
sys.path.insert(0, str(HOOKS))
todo_canonical = importlib.import_module("lib.todo_canonical")
command_span = importlib.import_module("lib.command_span")

FOREIGN = [{"content": "Answer the follow-up question", "activeForm": "Answering the follow-up question",
            "status": "in_progress"},
           {"content": "Summarize the answer", "activeForm": "Summarizing the answer", "status": "pending"}]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical(command):
    steps = todo_canonical.run_todo_script(command, "")
    assert steps, command
    return steps


def frontier(steps, done):
    return [{"content": s["content"], "activeForm": s["activeForm"],
             "status": "completed" if k < done else ("in_progress" if k == done else "pending")}
            for k, s in enumerate(steps)]


class TX:
    """A main-session transcript in the CLI's record shapes."""

    def __init__(self, tmp_path):
        self.tmp, self.n = tmp_path, 0
        self.path = tmp_path / "11111111-2222-3333-4444-555555555555.jsonl"
        self.path.write_text("", encoding="utf-8")
        self.project = tmp_path / "project"
        (self.project / ".claude").mkdir(parents=True)

    def add(self, record):
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    def command(self, name, args=""):
        self.add({"type": "user", "message": {"role": "user", "content":
                  f"<command-message>{name} is running…</command-message>\n<command-name>/{name}</command-name>\n"
                  f"<command-args>{args}</command-args>"}})

    def use(self, name, tool_input):
        self.n += 1
        tid = f"toolu_{self.n:04d}"
        self.add({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tid, "name": name, "input": tool_input}]}})
        return tid

    def tool(self, name, tool_input):
        tid = self.use(name, tool_input)
        self.add({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tid, "content": "ok"}]}})
        return tid

    def todos(self, todos):
        return self.tool("TodoWrite", {"todos": todos})

    def walk(self, steps, upto):
        """Every list from Step 0 in progress to ``upto`` steps completed, each one accepted."""
        for done in range(upto + 1):
            self.todos(frontier(steps, done))

    def validate(self, todos):
        """pretool-todo-validate.py on a TodoWrite of ``todos``, already in the record with no result."""
        tid = self.use("TodoWrite", {"todos": todos})
        payload = {"session_id": "11111111-2222-3333-4444-555555555555", "transcript_path": str(self.path),
                   "hook_event_name": "PreToolUse", "tool_name": "TodoWrite", "tool_input": {"todos": todos},
                   "tool_use_id": tid}
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.project), "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run([sys.executable, str(HOOKS / "pretool-todo-validate.py")], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, cwd=self.project, timeout=60)


@pytest.fixture
def tx(tmp_path, monkeypatch):
    t = TX(tmp_path)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(t.project))
    return t


def _spec_done(tx):
    steps = canonical("spec")
    assert len(steps) > 1  # a walk of the whole list, however many steps scripts/todo/spec.py prints
    tx.command("spec", "a new feature")
    tx.walk(steps, len(steps))
    return steps


# ---------------------------------------------------------------- the allow (red on the base, green after)
def test_an_unrelated_two_item_list_after_all_the_spec_steps_runs(tx):
    _spec_done(tx)
    proc = tx.validate(FOREIGN)
    assert proc.returncode == 0, proc.stderr
    assert "BLOCKED" not in proc.stderr


def test_a_second_foreign_list_after_the_first_runs_too(tx):
    _spec_done(tx)
    tx.todos(FOREIGN)
    done = [{**t, "status": "completed"} for t in FOREIGN]
    proc = tx.validate(done)
    assert proc.returncode == 0, proc.stderr


def test_a_foreign_list_leaves_the_checklist_the_completed_canonical_list(tx):
    """Every reader through lib.todo_canonical (the workflow gate's lock, Gate 4, the progress views)
    reads the checklist, never the foreign list after it."""
    steps = _spec_done(tx)
    tx.todos(FOREIGN)
    state = todo_canonical.checklist(str(tx.path))
    assert [t["content"] for t in state.todos] == [s["content"] for s in steps]
    assert all(t["status"] == "completed" for t in state.todos)
    assert state.lock == ""
    assert [t for _c, t in state.lists()][-1] == frontier(steps, len(steps))


# ---------------------------------------------------------------- must still refuse
def test_a_custom_list_while_dev_is_in_progress_is_refused(tx):
    steps = canonical("dev")
    tx.command("dev", "fix the bug")
    tx.walk(steps, 2)
    proc = tx.validate(FOREIGN)
    assert proc.returncode == 2
    assert "BLOCKED TodoWrite (canonical validation)" in proc.stderr


def test_a_custom_list_before_the_checklist_starts_is_refused(tx):
    tx.command("spec", "a new feature")
    proc = tx.validate(FOREIGN)
    assert proc.returncode == 2
    assert "BLOCKED TodoWrite (canonical validation)" in proc.stderr


@pytest.mark.parametrize("field", ["content", "activeForm"])
def test_a_list_after_completion_that_reuses_a_step_text_is_refused(tx, field):
    steps = _spec_done(tx)
    reused = [dict(FOREIGN[0]), dict(FOREIGN[1])]
    reused[1][field] = steps[3][field]
    proc = tx.validate(reused)
    assert proc.returncode == 2
    assert "BLOCKED TodoWrite" in proc.stderr


def test_a_later_commands_first_list_is_held_to_its_canonical_list(tx):
    """A foreign list accepted after /spec completed opens nothing for the /dev typed after it."""
    _spec_done(tx)
    tx.todos(FOREIGN)
    tx.command("dev", "fix the bug")
    proc = tx.validate(FOREIGN)
    assert proc.returncode == 2
    assert "BLOCKED TodoWrite (canonical validation)" in proc.stderr
    state = todo_canonical.checklist(str(tx.path))
    assert state.command == "dev" and state.todos is None and state.lock == "not_started"


# ---------------------------------------------------------------- the Stop gate reads the checklist
@pytest.fixture
def gate(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_ENABLE_TODO_TOOLS", "1")
    monkeypatch.setenv("CLAUDE_CODE_ENABLE_TASKS", "false")
    return _load(HOOKS / "stop-command-gate.py", "stop_command_gate_ob_l40")


def test_stop_gate_a_completed_dev_checklist_then_a_foreign_list_has_no_todo_gap(tx, gate):
    steps = canonical("dev")
    tx.command("dev", "fix the bug")
    tx.walk(steps, len(steps))
    tx.todos(FOREIGN)
    assert gate.todo_gaps(command_span.active_span(str(tx.path))) == []


def test_stop_gate_a_foreign_list_never_stands_in_for_an_open_checklist(tx, gate):
    """A list foreign to /dev, all completed, in the record of an open /dev checklist: the gate reads the
    canonical record and names its open steps."""
    steps = canonical("dev")
    tx.command("dev", "fix the bug")
    tx.walk(steps, 2)
    tx.todos([{**t, "status": "completed"} for t in FOREIGN])
    gaps = gate.todo_gaps(command_span.active_span(str(tx.path)))
    assert f"todo: not completed: {steps[2]['content']}" in gaps
    assert all(t["content"] not in "\n".join(gaps) for t in FOREIGN)


def test_stop_gate_a_later_command_is_not_satisfied_by_an_earlier_foreign_list(tx, gate):
    _spec_done(tx)
    tx.todos([{**t, "status": "completed"} for t in FOREIGN])
    tx.command("dev", "fix the bug")
    assert gate.todo_gaps(command_span.active_span(str(tx.path))) == [
        f"todo: checklist never written ({len(canonical('dev'))} canonical steps)"]


# ---------------------------------------------------------------- the step label and the overnight loop
def test_the_dispatch_step_label_is_never_read_from_a_foreign_list(tx):
    enforce = _load(HOOKS / "pretool-subagent-enforce.py", "subagent_enforce_ob_l40")
    steps = canonical("dev")
    tx.command("dev", "fix the bug")
    tx.walk(steps, len(steps))
    tx.todos([{"content": "Step 3a: Something else", "activeForm": "Doing something else",
               "status": "in_progress"}])
    assert enforce._current_step_label(command_span.active_span(str(tx.path))) is None


def test_the_overnight_loop_ends_no_cycle_on_a_foreign_list(tx):
    loop = _load(HOOKS / "posttool-overnight-loop.py", "overnight_loop_ob_l40")
    steps = canonical("dev-overnight")
    tx.command("dev-overnight", "")
    tx.walk(steps, len(steps))
    done = [{**t, "status": "completed"} for t in FOREIGN]
    tx.todos(done)
    assert loop._foreign({"transcript_path": str(tx.path), "tool_input": {"todos": done}}) is True
    assert loop._foreign({"transcript_path": str(tx.path),
                          "tool_input": {"todos": frontier(steps, len(steps))}}) is False


# ---------------------------------------------------------------- rule 9: a held list older hooks let a reword through
# The recorded shape (neutral values): a /dev whose first list was the canonical one, then a list the hooks of an
# earlier day admitted with a step reworded. The validator holds that text and the Stop gate confirms only the
# canonical or the first list's text, so before rule 9 no rewrite passed both and the todo half could never clear.
def _reworded(tx, done=3):
    steps = todo_canonical.run_todo_script("dev", "fix the bug")
    tx.command("dev", "fix the bug")
    tx.walk(steps, done)
    held = frontier(steps, done)
    held[1] = {**held[1], "content": held[1]["content"] + " (done, all lanes pass)"}
    tx.todos(held)  # admitted by the hooks of its day
    return steps, held


def test_rule_9_the_canonical_text_with_every_status_as_held_is_admitted_and_clears_the_gates_differs_line(tx, gate):
    steps, _held = _reworded(tx)
    assert gate.todo_gaps(command_span.active_span(str(tx.path))) == [
        f"todo: checklist differs from the canonical {len(steps)} steps"]
    proc = tx.validate(frontier(steps, 3))
    assert proc.returncode == 0, proc.stderr
    tx.add({"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": f"toolu_{tx.n:04d}", "content": "ok"}]}})
    gaps = gate.todo_gaps(command_span.active_span(str(tx.path)))
    assert not any("differs" in g for g in gaps) and f"todo: not completed: {steps[3]['content']}" in gaps, gaps


@pytest.mark.parametrize("variant", ["a status changed", "a step dropped", "a step added", "one character of content",
                                     "one character of activeForm", "the held list's own shape reworded again"])
def test_rule_9_every_other_rewrite_of_the_held_list_is_refused_as_before(tx, variant):
    steps, held = _reworded(tx)
    todos = frontier(steps, 3)
    if variant == "a status changed":
        todos = frontier(steps, 4)
    elif variant == "a step dropped":
        todos = todos[:-1]
    elif variant == "a step added":
        todos = todos + [{**todos[-1], "content": "Step 99: More"}]
    elif variant.startswith("one character of"):
        field = variant.split()[-1]
        todos[5] = {**todos[5], field: todos[5][field] + "."}
    else:
        todos = [{**t, "content": t["content"] + "!"} if k == 1 else t for k, t in enumerate(held)]
    proc = tx.validate(todos)  # refused, and the refusal names the one rewrite rule 9 admits
    assert proc.returncode == 2 and json.dumps(frontier(steps, 3), ensure_ascii=False) in proc.stderr, proc.stderr


def test_rule_9_a_refusal_over_such_a_held_list_names_the_one_rewrite_it_admits(tx):
    steps, held = _reworded(tx)
    wanted = json.dumps(frontier(steps, 3), ensure_ascii=False)
    shortened = [{**t, "content": t["content"][:12]} for t in held]
    for todos in (shortened, [{**t, "status": "completed"} if k < 6 else t for k, t in enumerate(held)]):
        proc = tx.validate(todos)
        assert proc.returncode == 2 and "Rewrite it once to the canonical list, every status as held:\n" + wanted \
            in proc.stderr, proc.stderr


def test_rule_9_names_nothing_over_a_held_list_with_the_canonical_text(tx):
    steps = todo_canonical.run_todo_script("dev", "fix the bug")
    tx.command("dev", "fix the bug")
    tx.walk(steps, 3)
    proc = tx.validate([{**t, "content": t["content"] + "!"} for t in frontier(steps, 3)])
    assert proc.returncode == 2 and "Rewrite it once" not in proc.stderr
