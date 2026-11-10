"""A /close that stalls at Step 0 ends its turn (#27 item 2, D25: no dead end).

commands/close.md Step 0: a disposition call that exits non-zero runs once more; failing again, the run
prints one `OPERATION_STALLED:` line and nothing else follows. The resolver that call runs is the
instrument the Stop gate's /close predicate reads too, so a broken resolver failed the gate's reading
as well, and the gate held that Stop (`gate instrument failure: SyntaxError ...` plus every TodoStep
left open): no agent action in the span could clear it, only the owner's /stop
(`--driver close --arg variant=stalled` replays it). The gate now lets that Stop end when its own
reading fails too (stop-command-gate.py close_stalled); when the gate reads the cycle it holds the
Stop as before, and the call runs again.

The resolver is broken as the replay breaks it: a sandbox harness copy whose
scripts/resolve-dev-artifact-chain.py does not compile, loaded by the gate's own loader.

Run with: python3 -m pytest hooks/tests/test_close_stalled_stop.py -q
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
CALL = ('python3 "${CLAUDE_HOME:-$HOME/.claude}"/scripts/resolve-dev-artifact-chain.py --disposition '
        f'--stage dev --task-id "{TASK}" --project-dir "/p"')
FAILED = ('Exit code 1\n  File "/h/scripts/resolve-dev-artifact-chain.py", line 1855\n    )(\n    ^\n'
          "SyntaxError: unmatched ')'")
STALL = f"OPERATION_STALLED: SyntaxError: unmatched ')'\nNext harness-repair item: the Step 0 disposition call for {TASK}."


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load(REPO / "hooks" / "stop-command-gate.py", "stop_command_gate_stalled_under_test")
todo_canonical = importlib.import_module("lib.todo_canonical")


class TX:
    """A main-session transcript in the CLI's record shapes."""

    def __init__(self, path: Path):
        self.path, self.n = path, 0
        path.write_text("", encoding="utf-8")

    def add(self, record: dict) -> None:
        record.setdefault("sessionId", SID)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

    def command(self, name: str, args: str) -> None:
        self.add({"type": "queue-operation", "operation": "enqueue", "content": f"/{name} {args}"})
        self.add({"type": "user", "message": {"role": "user", "content":
                  f"<command-message>{name} is running…</command-message>\n<command-name>/{name}</command-name>\n"
                  f"<command-args>{args}</command-args>"}})

    def tool(self, name: str, tool_input: dict, ok: bool = True, result="ok") -> None:
        self.n += 1
        ident = f"toolu_{self.n:04d}"
        self.add({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": ident, "name": name, "input": tool_input}]}})
        self.add({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": ident, "content": result, **({} if ok else {"is_error": True})}]}})

    def say(self, text: str, sidechain: bool = False) -> None:
        self.add({"type": "assistant", **({"isSidechain": True, "agentId": "a1"} if sidechain else {}),
                  "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}})

    def todos(self, steps, done: int) -> None:
        self.tool("TodoWrite", {"todos": [
            {"content": s["content"], "activeForm": s.get("activeForm", ""),
             "status": "completed" if k < done else ("in_progress" if k == done else "pending")}
            for k, s in enumerate(steps)]})


@pytest.fixture
def env(tmp_path, monkeypatch):
    project = tmp_path / "project"
    (project / "docs" / "dev").mkdir(parents=True)
    (project / "docs" / "dev" / f"ticket-{TASK}.md").write_text(f"# Ticket\n\n**TASK-ID**: `{TASK}`\n")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CLAUDE_CODE_ENABLE_TODO_TOOLS", "1")
    monkeypatch.delenv("CLAUDE_COMPAT_RUNTIME", raising=False)
    overnight = types.ModuleType("lib.overnight")  # no overnight session
    overnight.session_state_file = lambda session_id, starts: (None, None)
    monkeypatch.setitem(sys.modules, "lib.overnight", overnight)
    monkeypatch.setattr(gate, "_SCRIPTS", {})
    tx = TX(tmp_path / f"{SID}.jsonl")
    payload = {"session_id": SID, "transcript_path": str(tx.path), "cwd": str(project),
               "hook_event_name": "Stop", "stop_hook_active": False}
    return types.SimpleNamespace(tmp=tmp_path, tx=tx, payload=payload, monkeypatch=monkeypatch)


def broken_resolver(env) -> None:
    """The gate's harness is a copy whose resolver does not compile (the replay's break_resolver)."""
    harness = env.tmp / "harness"
    (harness / "scripts").mkdir(parents=True)
    source = (REPO / "scripts" / "resolve-dev-artifact-chain.py").read_text(encoding="utf-8")
    (harness / "scripts" / "resolve-dev-artifact-chain.py").write_text(source + "\n)(  # unimportable\n")
    env.monkeypatch.setattr(gate, "HARNESS", harness)


def reading_resolver(env) -> None:
    """The gate reads the cycle: the resolver answers with one gap."""
    module = types.SimpleNamespace(disposition_lines=lambda root, task, stage: [
        f"GAP artifact=docs/dev/close-report-{task}.md problem=MISSING_ARTIFACT: not found lane=-"])
    env.monkeypatch.setitem(gate._SCRIPTS, "scripts/resolve-dev-artifact-chain.py", module)


def stalled_span(env, calls=(False, False), line: str | None = STALL, after: str = "") -> None:
    """/close <task> with its TodoStep list (Step 0 in progress), the Step 0 disposition call per entry
    of ``calls`` (ok or not), then the main agent's text ``line``; ``after`` is one more call's form."""
    steps = todo_canonical.run_todo_script("close", TASK)
    assert steps
    env.tx.command("close", TASK)
    env.tx.todos(steps, 0)
    for ok in calls:
        env.tx.tool("Bash", {"command": CALL, "description": "Step 0 disposition"}, ok=ok,
                    result="DISPOSITION=chain_pass STAGE=dev TASK=x" if ok else FAILED)
    if line is not None:
        env.tx.say(line)
    if after:
        env.tx.tool("Bash", {"command": CALL, "description": "Step 0 disposition"}, ok=after == "ok",
                    result="DISPOSITION=chain_pass STAGE=dev TASK=x" if after == "ok" else FAILED)


def test_the_hold_a_broken_resolver_put_on_a_stalled_close_is_released(env):
    """The reproduction: the stall close.md prescribes, the gate's own reading failing on the same
    resolver. Before close_stalled this was exit 2, `gate instrument failure: SyntaxError` and every
    TodoStep open, which only /stop ended."""
    broken_resolver(env)
    stalled_span(env)
    assert gate.decide(env.payload, "block") == (0, "")


@pytest.mark.parametrize("calls,line,after", [
    ((False,), STALL, ""),  # the call was not run once more
    ((False, False), None, ""),  # no OPERATION_STALLED: line
    ((False, False), "The resolver failed twice; stopping here.", ""),  # the line in another form
    ((True, False), STALL, ""),  # the call before the last came back
    ((False, False), STALL, "ok"),  # the call ran again later and came back
    ((False, False), STALL, "err"),  # the line is not after the last failed call
], ids=["one-failure", "no-line", "other-line", "earlier-ok", "later-ok", "line-before-last"])
def test_a_stall_close_md_does_not_describe_stays_held(env, calls, line, after):
    broken_resolver(env)
    stalled_span(env, calls, line, after)
    code, text = gate.decide(env.payload, "block")
    assert code == 2 and "gate instrument failure: SyntaxError" in text, text


def test_a_subagents_stall_line_is_not_the_main_agents(env):
    broken_resolver(env)
    stalled_span(env, line=None)
    env.tx.say(STALL, sidechain=True)
    assert gate.decide(env.payload, "block")[0] == 2


def test_a_gate_that_reads_the_cycle_holds_the_stall_and_names_the_open_steps(env):
    """The agent's call failed but the gate's reading works: the resolver runs, so the Stop is held,
    naming Step 0 and the cycle's gap; close.md: the call runs once more and the run goes on."""
    reading_resolver(env)
    stalled_span(env)
    code, text = gate.decide(env.payload, "block")
    assert code == 2 and "todo: not completed: Step 0" in text and "problem=MISSING_ARTIFACT" in text, text
    assert "gate instrument failure" not in text, text


def test_the_release_is_close_md_steps_own(env):
    """The text the release follows: close.md Step 0 says the turn ends there, and what a held Stop asks."""
    text = (REPO / "commands" / "close.md").read_text(encoding="utf-8")
    step0 = text.split("### Step 0:", 1)[1].split("\n### ", 1)[0]
    assert "the Stop gate lets it end while its own reading of the cycle fails too" in step0
    assert "When the gate reads the cycle and holds that Stop, the call works again" in step0
    assert "`OPERATION_STALLED: <the stderr reason>`" in step0 and "run the same call once more" in step0
