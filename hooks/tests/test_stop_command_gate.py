"""Tests for hooks/stop-command-gate.py, P5 R7 and R8, and R10's move.

The gate calls P3's disposition, P2's overnight locator and window, and P4's
close rating. Most cases fake P3's disposition and P4's close rating with their
signatures (each such test says so), to pin the gate's own logic; P2, P3 and
P4 are merged, so the time-lock cases run P2's lib/overnight (locate,
window_open, closeout_gaps) on the session's own state record
(``real_overnight``), and the cases that rest on P3's and P4's behaviour run
again on their real code at the end (the ``real`` fixture). The rest runs the
real readers:
command_span on CLI-shaped transcripts, git on local repositories, the
do-branch write-set helper and dev-lifecycle's --auto target function.

Run with: python3 -m pytest hooks/tests/test_stop_command_gate.py -q
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOKS = REPO / "hooks"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load(HOOKS / "stop-command-gate.py", "stop_command_gate_under_test")
resolver = _load(REPO / "scripts" / "resolve-dev-artifact-chain.py", "resolver_under_test")
sys.path.insert(0, str(REPO))
from hooks.lib import obligation as chain_obligation  # noqa: E402  (the module the chain's reader imports)
command_span = gate.command_span
# the hooks/lib modules the gate imports by name (it puts hooks/ on sys.path)
obligation = importlib.import_module("lib.obligation")
REAL_OVERNIGHT = importlib.import_module("lib.overnight")
todo_canonical = importlib.import_module("lib.todo_canonical")

T0 = datetime(2026, 11, 1, 9, 0, 0, tzinfo=timezone.utc)
SID = "11111111-2222-3333-4444-555555555555"
DEV_ID = "dev-20261101-090000"
FAMILY = "20261101-090000"
DO_ID = "20261101-091500"


# ---------------------------------------------------------------- transcripts in the CLI's record shapes
class TX:
    """A main-session transcript: typed prompts, hook context, tool calls."""

    def __init__(self, path: Path, start: datetime = T0):
        self.path, self.clock, self.n = path, start, 0
        path.write_text("", encoding="utf-8")

    def add(self, record: dict) -> dict:
        self.clock += timedelta(seconds=1)
        record.setdefault("timestamp", self.clock.isoformat().replace("+00:00", "Z"))
        record.setdefault("sessionId", SID)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        return record

    def typed(self, text: str):
        self.add({"type": "queue-operation", "operation": "enqueue", "content": text})
        self.add({"type": "user", "message": {"role": "user", "content": text}})

    def command(self, name: str, args: str = "", context: str | None = None, body: str | None = None):
        """A typed command; with ``body``, the text the CLI recorded for it, linked to the opener
        (parentUuid, as Span.body reads it); else an unlinked placeholder record."""
        self.add({"type": "queue-operation", "operation": "enqueue", "content": f"/{name} {args}".strip()})
        opener = {"uuid": f"opener-{self.clock.timestamp():.0f}"} if body is not None else {}
        self.add({"type": "user", **opener, "message": {"role": "user", "content":
                  f"<command-message>{name} is running…</command-message>\n<command-name>/{name}</command-name>\n"
                  f"<command-args>{args}</command-args>"}})
        self.add({"type": "user", "isMeta": True, **({"parentUuid": opener["uuid"]} if opener else {}),
                  "message": {"role": "user", "content": [
                      {"type": "text", "text": f"body of {name}" if body is None else body}]}})
        if context:
            self.add({"type": "attachment", "attachment": {"type": "hook_additional_context", "content": context,
                                                           "hookName": "UserPromptSubmit"}})

    def tool(self, name: str, tool_input: dict, ok: bool = True, result="ok", extra: dict | None = None,
             sidechain: bool = False) -> str:
        self.n += 1
        ident = f"toolu_{self.n:04d}"
        side = {"isSidechain": True, "agentId": "a1"} if sidechain else {}
        self.add({"type": "assistant", **side, "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": ident, "name": name, "input": tool_input}]}})
        self.add({"type": "user", **side, **(extra or {}), "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": ident, "content": result, **({} if ok else {"is_error": True})}]}})
        return ident

    def ask(self, answer: str):
        """The main agent's AskUserQuestion in the turn and the owner's answer."""
        question = "Which one did you mean?"
        self.tool("AskUserQuestion", {"questions": [{"question": question, "header": "Argument", "multiSelect": False,
                                                     "options": [{"label": answer, "description": ""},
                                                                 {"label": "Something else", "description": ""}]}]},
                  result=f'User has answered your questions: "{question}"="{answer}".')

    def say(self, text: str):
        self.add({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}})

    def todos(self, steps, done: int):
        self.tool("TodoWrite", {"todos": [
            {"content": s["content"], "activeForm": s.get("activeForm", ""),
             "status": "completed" if k < done else ("in_progress" if k == done else "pending")}
            for k, s in enumerate(steps)]})

    def dispatch(self, task_id: str, role: str = "qa", pipeline: str = "dev", profile: str = "singular",
                 artifacts=None, result="done"):
        doc = {"task_id": task_id, "lane": None, "lane_set": None, "role": role, "pipeline": pipeline,
               "profile": profile, "dispatched_at": "2026-11-01T09:00:00Z",
               "artifacts": artifacts or [{"kind": "json", "path": f"docs/dev/{role}-report-{task_id}.json",
                                           "schema": "qa-report.v2", "identity": {"task_id": task_id}}]}
        return self.tool("Agent", {"subagent_type": role, "description": role,
                                   "prompt": f'<obligation v="1">{json.dumps(doc)}</obligation>\nwork'},
                         result=result)


# ---------------------------------------------------------------- fakes for P2, P3, P4
class Disposition:
    """P3's disposition(project_root, task_id, stage) and gap_line(gap), set
    into the chain's module, whose own disposition_lines the gate calls: a
    table of answers per (task, stage); every call is recorded."""

    def __init__(self, answers=None):
        self.answers, self.calls = dict(answers or {}), []

    def disposition(self, project_root, task_id, stage, **kwargs):
        self.calls.append((str(project_root), task_id, stage, kwargs.get("transcript")))
        gaps = self.answers.get((task_id, stage), [])
        return {"disposition": "incomplete" if gaps else "chain_pass", "stage": stage, "task_id": task_id,
                "gaps": gaps}

    @staticmethod
    def gap_line(gap):
        lane = "-" if gap["lane"] is None else gap["lane"]
        return f"GAP artifact={gap['artifact']} problem={gap['problem']}: {gap['message']} lane={lane}"


def gap(artifact, problem, message, lane=None):
    return {"artifact": artifact, "problem": problem, "message": message, "lane": lane}


def overnight_fake(record=None, window=False, closeout=()):
    """P2's overnight.locate(session_id, payload), window_open(payload),
    closeout_gaps(state, working_root) and working_root(state), and the
    session_state_file locate reads through; the wake's reader (open_wakes,
    P1c X8) is this base's own."""
    module = types.ModuleType("lib.overnight")
    module.locate = lambda session_id, payload=None: (Path("state.json"), record) if record else (None, None)
    module.session_state_file = lambda session_id, starts: module.locate(session_id)
    module.window_open = lambda payload: bool(record) and window
    module.closeout_gaps = lambda state, working_root: list(closeout)
    module.working_root = lambda state: Path(state.get("worktree_path") or ".")
    module.open_wakes = REAL_OVERNIGHT.open_wakes
    return module


def real_overnight(env, monkeypatch, hours=None, **fields):
    """P2's lib/overnight as merged, with the session's own record at
    <project>/.claude/overnight-state-<SID>.json (end_time ``hours`` from now, UTC) when
    ``hours`` is given; the record's end_time as written."""
    monkeypatch.setitem(sys.modules, "lib.overnight", REAL_OVERNIGHT)
    if hours is None:
        return None
    end = (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    claude = env.project / ".claude"
    claude.mkdir(parents=True, exist_ok=True)
    (claude / f"overnight-state-{SID}.json").write_text(json.dumps({"session_id": SID, "end_time": end, **fields}))
    return end


def closeout_on_disk(root: Path) -> None:
    """The overnight closeout P2's closeout_gaps reads: Step 20's PM retrospective and Step
    21's summary under the working root."""
    retro = root / "docs" / "dev" / "overnight" / SID / "retro-report-cycle1.json"
    retro.parent.mkdir(parents=True, exist_ok=True)
    retro.write_text("{}")
    (root / "docs" / "dev" / "overnight-summary-2026-11-01.md").write_text("# Summary\n")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A project, the todo tools on, no overnight session, P3's disposition faked."""
    project = tmp_path / "project"
    (project / "docs" / "dev").mkdir(parents=True)
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("CLAUDE_STATE_DIR", str(state))
    monkeypatch.setenv("CLAUDE_CODE_ENABLE_TODO_TOOLS", "1")
    monkeypatch.delenv("CLAUDE_COMPAT_RUNTIME", raising=False)
    monkeypatch.setitem(sys.modules, "lib.overnight", overnight_fake())
    fake = Disposition()
    for name in ("disposition", "gap_line"):
        monkeypatch.setattr(resolver, name, getattr(fake, name), raising=False)
    monkeypatch.setitem(gate._SCRIPTS, "scripts/resolve-dev-artifact-chain.py", resolver)
    monkeypatch.setattr(chain_obligation, "declaring_dispatch", lambda task, path, root, roots=None: None)
    ns = types.SimpleNamespace(project=project, state=state, fake=fake, tmp=tmp_path,
                               tx=TX(tmp_path / f"{SID}.jsonl"))
    ns.payload = {"session_id": SID, "transcript_path": str(ns.tx.path), "cwd": str(project),
                  "hook_event_name": "Stop", "stop_hook_active": False}
    return ns


def canonical(command: str, args: str = ""):
    steps = todo_canonical.run_todo_script(command, args)
    assert steps, command
    return steps


def run(env, mode="block", **extra):
    return gate.decide({**env.payload, **extra}, mode)


def dev_span(env, done: int, dispatch: bool = True):
    steps = canonical("dev")
    env.tx.command("dev", "fix the build", context=f"DEV_SESSION_ID pre-initialized by hook: {DEV_ID}\n"
                                                    f"Task id: {FAMILY}\n")
    env.tx.todos(steps, done)
    if dispatch:
        env.tx.dispatch(FAMILY, role="ba")
    return steps


# ---------------------------------------------------------------- A2: /dev held until complete
def test_a2_dev_at_one_step_blocks_naming_open_todos_and_the_missing_dispatch(env, monkeypatch):
    steps = dev_span(env, done=1)
    qa = f"docs/dev/qa-report-{FAMILY}.json"
    env.fake.answers[(FAMILY, "dev")] = [gap(qa, "MISSING_ARTIFACT", "absent")]
    monkeypatch.setattr(chain_obligation, "declaring_dispatch", lambda task, path, root, roots=None: {
        "source": "todo_step", "step": "Step 9: QA validation", "command": "dev"})
    code, text = run(env)
    assert code == 2
    assert text.startswith("COMMAND_GATE /dev: not complete\n")
    assert f"- todo: not completed: {steps[1]['content']}" in text
    assert f"GAP artifact={qa} problem=MISSING_ARTIFACT: absent lane=- step=\"Step 9: QA validation\"" in text
    assert "AskUserQuestion only for a real decision" in text
    for word in ("stop", "Stop", "AWAITING_INPUT", "owner"):
        assert word not in text.split("not complete\n", 1)[1].replace("COMMAND_GATE", ""), word


@pytest.mark.parametrize("after", [
    "stop_hook_active", "awaiting_line", "plain_answer", "allow", "model", "skill_spec", "skill_codex",
    "scheduled_spec", "wakeup_spec"])
def test_a2_no_record_but_the_humans_own_command_ends_the_block(env, after):
    dev_span(env, done=1)
    extra = {}
    if after == "stop_hook_active":
        extra = {"stop_hook_active": True}
    elif after == "awaiting_line":
        env.tx.say("I need input.\nAWAITING_INPUT: need=x; why=y; addressee=human")
    elif after == "plain_answer":
        env.tx.typed("yes, go on")
    elif after in ("allow", "model"):
        env.tx.command(after, "git push" if after == "allow" else "opus")
    elif after.startswith("skill_"):  # the Skill tool's expansion of /spec or /codex
        name = after.split("_", 1)[1]
        ident = env.tx.tool("Skill", {"skill": name})
        env.tx.add({"type": "user", "isMeta": True, "sourceToolUseID": ident, "message": {
            "role": "user", "content": f"<command-name>/{name}</command-name><command-args></command-args>"}})
    else:  # a CronCreate or ScheduleWakeup prompt, as the CLI records it (COV-7)
        env.tx.add({"type": "user", "isMeta": True, "turnOrigin": "scheduled", "promptSource": "system",
                    "message": {"role": "user", "content": "/spec"}})
    assert run(env, **extra)[0] == 2


@pytest.mark.parametrize("command", ["stop", "spec"])
def test_a2_the_humans_stop_or_spec_opens_an_ungated_span(env, command):
    dev_span(env, done=1)
    env.tx.command(command)
    assert run(env) == (0, "")


# A2's Esc case (P5-23). Esc interrupts the turn and runs no Stop hook (D4c); the next Stop the gate
# sees follows the human's next prompt. Record shapes, as the CLI wrote them:
# - The interrupt: a user record holding one text block "[Request interrupted by user]", with no
#   origin, turnOrigin or isMeta. Measured on CLI 2.1.319 (a session transcript of the harness host,
#   2026-11-09; that record was a subagent's, isSidechain true, so the main session's is written with
#   isSidechain false); the replay kit writes the same record (tests/replay/drivers/overnight.py).
# - Esc during a tool call: the call's error tool_result, then "[Request interrupted by user for tool
#   use]". Not captured on that host; written from the CLI's interrupt texts.
# - The typed plain prompt: an enqueue and a dequeue queue-operation, then a user record with string
#   content, origin {"kind": "human"}, promptSource "sdk", turnOrigin "human" and turnPosition.
#   Measured on the same host, CLI 2.1.319 (the main session's typed prompts).
# - A typed command: the same human fields on txbuild's slash-command records (tools/proto/txbuild.py).
# The gate reads none of the interrupt's text or fields (D4c): it is a prompt with no command in it,
# so like any plain prompt it continues the span.
CLI_FIELDS = {"userType": "external", "entrypoint": "cli", "isSidechain": False, "version": "2.1.319",
              "gitBranch": "main"}
REJECTED = ("The user doesn't want to proceed with this tool use. The tool use was rejected (eg. if it was a file "
            "edit, the new_string was NOT written to the file). STOP what you are doing and wait for the user to "
            "tell you how to proceed.")


def interrupted_turn(env, during: str):
    """The agent's turn after a blocked Stop, cut by Esc: no Stop runs."""
    if during == "reply":
        env.tx.say("Continuing with step 2: reading the failing build log")
        text = "[Request interrupted by user]"
    else:
        env.tx.tool("Bash", {"command": "make build", "description": "Build"}, ok=False, result=REJECTED)
        text = "[Request interrupted by user for tool use]"
    env.tx.add({"type": "user", **CLI_FIELDS, "cwd": str(env.project), "promptId": "prompt-esc",
                "message": {"role": "user", "content": [{"type": "text", "text": text}]}})


def human_typed(env, text: str, index: int, command: str | None = None):
    """A prompt the human typed (a plain one, or with ``command`` that slash command), as the CLI records it."""
    env.tx.add({"type": "queue-operation", "operation": "enqueue", "content": text})
    env.tx.add({"type": "queue-operation", "operation": "dequeue"})
    content = text if command is None else (f"<command-message>{command} is running…</command-message>\n"
                                            f"<command-name>/{command}</command-name>\n<command-args></command-args>")
    env.tx.add({"type": "user", **CLI_FIELDS, "cwd": str(env.project), "permissionMode": "default",
                "promptId": f"prompt-{index}", "origin": {"kind": "human"}, "promptSource": "sdk",
                "turnOrigin": "human", "turnPosition": {"promptIndex": index, "turnIndex": index},
                "message": {"role": "user", "content": content}})
    if command is not None:
        env.tx.add({"type": "user", "isMeta": True, "message": {"role": "user", "content": [
            {"type": "text", "text": f"body of {command}"}]}})


@pytest.mark.parametrize("during", ["reply", "tool_call"])
@pytest.mark.parametrize("after,code", [("plain", 2), ("stop", 0), ("spec", 0), ("plain_then_complete", 0)])
def test_a2_esc_then_the_humans_next_prompt(env, monkeypatch, during, after, code):
    """/dev at 1 of 17, no QA dispatch, blocked; Esc; then the human types: a plain prompt continues the
    span (the same block), /stop or /spec opens an ungated one, and the completed span then holds."""
    steps = dev_span(env, done=1)
    qa = f"docs/dev/qa-report-{FAMILY}.json"
    env.fake.answers[(FAMILY, "dev")] = [gap(qa, "MISSING_ARTIFACT", "absent")]
    monkeypatch.setattr(chain_obligation, "declaring_dispatch", lambda task, path, root, roots=None: {
        "source": "todo_step", "step": "Step 9: QA validation", "command": "dev"})
    first, before = run(env)
    assert first == 2 and before.startswith("COMMAND_GATE /dev: not complete\n")
    interrupted_turn(env, during)
    if after in ("stop", "spec"):
        human_typed(env, f"/{after}", 2, command=after)
    else:
        human_typed(env, "keep going, but check the build log first", 2)
    if after == "plain_then_complete":
        env.tx.todos(steps, len(steps))
        env.tx.dispatch(FAMILY, role="qa")
        env.fake.answers[(FAMILY, "dev")] = []  # the QA report landed: P3's chain_pass
    got, text = run(env)
    assert got == code
    if code == 2:
        assert text == before  # the span's own gaps, as at the Stop before the Esc
        assert f"- todo: not completed: {steps[1]['content']}" in text
        assert f"GAP artifact={qa} problem=MISSING_ARTIFACT: absent lane=- step=\"Step 9: QA validation\"" in text
    else:
        assert text == ""
    assert command_span.active_span(env.tx.path).command == ("dev" if after.startswith("plain") else after)


def test_a2_all_ticked_without_a_dispatch_is_no_pipeline_dispatched(env):
    steps = dev_span(env, done=0, dispatch=False)
    env.tx.todos(steps, len(steps))
    code, text = run(env)
    assert code == 2 and "- no pipeline dispatched\n" in text


def test_a2_an_older_passing_family_does_not_cover_the_minted_task(env):
    steps = dev_span(env, done=0, dispatch=False)
    env.tx.dispatch("20261031-120000", role="qa")  # an older cycle, chain_pass
    env.tx.todos(steps, len(steps))
    env.fake.answers[(FAMILY, "dev")] = [gap(f"docs/dev/dev-report-{FAMILY}.json", "MISSING_ARTIFACT", "absent")]
    code, text = run(env)
    assert code == 2 and f"dev-report-{FAMILY}.json" in text
    assert {c[1] for c in env.fake.calls} == {FAMILY, "20261031-120000"}


def test_session_families_leave_out_a_dispatch_working_on_no_task(env):
    env.tx.command("dev-overnight", "--hours 1")
    env.tx.dispatch("20261101-095259", role="pm", pipeline="dev-overnight", profile="overnight", artifacts=[
        {"kind": "json", "path": "docs/dev/overnight/s/triage-report-cycle1.json", "schema": "triage-report.v1",
         "identity": {"task_id": "20261101-095259"}}])
    env.tx.dispatch(f"{FAMILY}-0-l1", role="dev", pipeline="dev-overnight")
    env.tx.dispatch(f"dev-{FAMILY}", role="changelog-analyst", pipeline="commit", artifacts=[
        {"kind": "response_block", "begin": "B", "end": "E", "format": "json", "schema": "changelog-status.v1"}])
    env.tx.dispatch("20261101-120000", role="qa", result="failed", pipeline="dev")
    env.tx.add({"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "x", "content": "late"}]}})
    assert command_span.active_span(env.tx.path).session_families() == {f"{FAMILY}-0", FAMILY, "20261101-120000"}


def test_a2_a_subagents_stop_is_allowed(env):
    dev_span(env, done=1)
    assert run(env, agent_id="a1") == (0, "")


def test_a2_no_api_error_or_interrupt_reading():
    for name in ("hooks/stop-command-gate.py", "hooks/lib/command_span.py", "hooks/lib/stop_contract.py"):
        text = (REPO / name).read_text(encoding="utf-8")
        for word in ("isApiErrorMessage", "interruption_signals", "api_error", "apierror", "api error"):
            assert word not in text, (name, word)


def test_a2_no_bound_counter_release_token_or_write():
    source = (HOOKS / "stop-command-gate.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = {getattr(n.func, "attr", getattr(n.func, "id", "")) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert not calls & {"write_text", "write_bytes", "unlink", "remove", "rename", "replace", "mkdir", "touch",
                        "open", "makedirs", "rmtree"}
    for word in ("stop_hook_active", "AWAITING_INPUT", "is_pause", "settings.machine", "private-literal",
                 "claude-do-task-", "terminal_status\")", "derive_state"):
        assert word not in source, word


# ---------------------------------------------------------------- A3: the disposition's gaps, facts only
@pytest.mark.parametrize("answer,code", [
    ([gap(f"docs/dev/qa-report-{FAMILY}.json", "qa.status:fail", "qa.status is 'fail'", "l1")], 2),
    ([gap(f"docs/dev/qa-report-{FAMILY}.json", "qa.status:warning", "qa.status is 'warning'")], 2),
    ([gap(f"docs/dev/ba-qa-report-{FAMILY}.json", "INVALID_BA_QA_VERDICT", "verdict is 'fail'")], 2),
    ([], 0)])
def test_a3_a_complete_checklist_still_needs_chain_pass(env, answer, code):
    """Fake disposition (P3); on the real one: test_a3_real_a_complete_checklist_still_needs_p3s_chain_pass."""
    steps = dev_span(env, done=0)
    env.tx.todos(steps, len(steps))
    env.fake.answers[(FAMILY, "dev")] = answer
    got, text = run(env)
    assert got == code
    for g in answer:
        assert g["artifact"] in text and g["problem"] in text and "owner" not in text


@pytest.mark.parametrize("command", ["dev", "redev", "dev-command"])
def test_a7_redev_and_dev_command_are_held_as_dev(env, command):
    """A2's transcripts with /redev or /dev-command: the same exit code at every Stop (D22)."""
    steps = canonical(command, "fix the build")
    env.tx.command(command, "fix the build", context=f"DEV_SESSION_ID pre-initialized by hook: {DEV_ID}\n")
    env.tx.todos(steps, 1)
    assert run(env)[0] == 2
    env.tx.todos(steps, len(steps))
    assert "- no pipeline dispatched\n" in run(env)[1]
    env.tx.dispatch(FAMILY)
    assert run(env) == (0, "")
    assert gate.PREDICATES[command] is gate.p_dev


# ---------------------------------------------------------------- A4: /do
def do_span(env, context=f"[/do] Consent granted.\n[/do] task-id minted: {DO_ID} — resolve via ..."):
    env.tx.command("do", "rename the helper", context=context)
    env.tx.todos(canonical("do", "rename the helper"), len(canonical("do", "rename the helper")))


def test_a4_a_pending_report_blocks_every_stop_without_a_forced_allow(env):
    do_span(env)
    do_report(env)
    path = env.project / "docs" / "dev" / f"do-report-{DO_ID}.json"
    record = json.loads(path.read_text())
    record["do"]["status"] = "pending"
    path.write_text(json.dumps(record))
    results = [run(env) for _ in range(4)]
    assert all(code == 2 and f"do-report-{DO_ID}.json: do.status is not a terminal status" in text
               and "FORCED" not in text for code, text in results)
    assert env.fake.calls == []  # the do-report's own readers decide it, not P3's disposition


def test_a4_the_task_is_the_hook_minted_id_not_the_sidecar_or_an_echo(env):
    do_span(env)
    env.tx.tool("Bash", {"command": "echo '[/do] task-id minted: 20990101-000000'"},
                result="[/do] task-id minted: 20990101-000000")
    env.tx.say("[/do] task-id minted: 20990101-000001")
    (env.state / f"claude-do-task-{SID}.json").write_text(json.dumps({"task_id": "20990101-000002"}))
    for other in ("20990101-000000", "20990101-000001", "20990101-000002"):
        (env.project / "docs" / "dev" / f"do-report-{other}.json").write_text(json.dumps({
            "task_id": other, "source": "do", "do": {"status": "completed", "summary": "done",
                                                     "files_modified": [], "files_created": []}}))
    for _ in range(2):
        code, text = run(env)
        assert code == 2 and f"docs/dev/do-report-{DO_ID}.json: do-report absent" in text
        (env.state / f"claude-do-task-{SID}.json").unlink(missing_ok=True)


def test_a4_a_do_span_with_no_minted_line_names_the_gap(env):
    do_span(env, context="[/do] Consent granted.")
    code, text = run(env)
    assert code == 2 and "no hook-minted task id" in text


@pytest.mark.parametrize("content,needle", [
    (None, "do-report absent"),
    ("{}", "do.status is not a terminal status of schemas/do-report.v1.json"),
    ("[]", "do-report is not a JSON object"),
    ("#####", "do-report unreadable/unparseable"),
    ("lists", "FILES_NOT_WRITE_SET"),
])
def test_a4_the_do_stop_decides_on_the_do_report_itself(env, monkeypatch, content, needle):
    """The /do Stop takes the do-report's verdict from its own readers (do_report.load, the
    schema's terminal status, the chain's do branch), with P3's disposition absent as on this
    tree: the complete report lets the Stop pass, an absent or invalid one blocks naming it."""
    monkeypatch.delattr(resolver, "disposition")  # never reached for /do
    do_span(env)
    write_files(env, ["src/a.py"])
    path = do_report(env, modified=["src/a.py"])
    assert run(env) == (0, "")
    if content is None:
        path.unlink()
    elif content == "lists":
        do_report(env)
    else:
        path.write_text(content)
    code, text = run(env)
    assert code == 2 and f"docs/dev/do-report-{DO_ID}.json" in text and needle in text, text


def test_a4_the_gate_creates_and_deletes_no_file(env):
    do_span(env)
    before = sorted(p for p in env.tmp.rglob("*"))
    for mode in ("block", "advisory"):
        run(env, mode)
    assert sorted(p for p in env.tmp.rglob("*")) == before


# R8: the do branch's write-set helper and Span.write_set, on the real readers


def do_report(env, modified=(), created=()):
    path = env.project / "docs" / "dev" / f"do-report-{DO_ID}.json"
    path.write_text(json.dumps({"task_id": DO_ID, "source": "do", "do": {
        "status": "completed", "summary": "done", "files_modified": list(modified),
        "files_created": list(created)}}))
    return path


def write_files(env, names):
    for name in names:
        target = env.project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x")
        env.tx.tool("Write", {"file_path": str(target), "content": "x"})


def test_r8_lists_equal_to_the_write_set_pass(env):
    do_span(env)
    write_files(env, ["src/a.py", "src/b.py"])
    env.tx.tool("Write", {"file_path": str(env.project / "docs/dev/do-report-x.json"), "content": "{}"})
    path = do_report(env, modified=["src/a.py"], created=["src/b.py"])
    assert resolver.do_report_gaps(env.project, DO_ID, path, str(env.tx.path)) == []


def test_r8_written_files_missing_from_the_lists_are_named_exactly(env):
    do_span(env)
    write_files(env, ["src/a.py", "src/b.py", "lib/c.py"])
    path = do_report(env)
    [(code, artifact, detail)] = resolver.do_report_gaps(env.project, DO_ID, path, str(env.tx.path))
    assert code == "FILES_NOT_WRITE_SET" and artifact == f"docs/dev/do-report-{DO_ID}.json"
    assert detail.endswith(json.dumps(["lib/c.py", "src/a.py", "src/b.py"]))


def test_r8_a_declared_file_neither_written_nor_named_is_a_gap(env):
    do_span(env)
    write_files(env, ["src/a.py"])
    env.tx.tool("Bash", {"command": "sed -i s/x/y/ src/named.py"})
    path = do_report(env, modified=["src/a.py", "src/named.py", "src/ghost.py"])
    [(_code, _artifact, detail)] = resolver.do_report_gaps(env.project, DO_ID, path, str(env.tx.path))
    assert "ghost" not in detail and detail.endswith(json.dumps(["src/a.py", "src/named.py"]))


def test_r8_failed_writes_subagent_writes_and_other_spans_do_not_count(env):
    env.tx.command("dev", "x")
    write_files(env, ["src/before.py"])
    do_span(env)
    write_files(env, ["src/a.py"])
    env.tx.tool("Write", {"file_path": str(env.project / "src/failed.py"), "content": "x"}, ok=False)
    env.tx.tool("Write", {"file_path": str(env.project / "src/agent.py"), "content": "x"}, sidechain=True)
    env.tx.command("spec")
    write_files(env, ["src/after.py"])
    path = do_report(env, modified=["src/a.py"])
    assert resolver.do_report_gaps(env.project, DO_ID, path, str(env.tx.path)) == []


def test_r8_every_do_span_of_the_task_counts(env):
    do_span(env)
    write_files(env, ["src/a.py"])
    env.tx.command("spec")
    do_span(env)  # the task's /do again, its id printed again
    write_files(env, ["src/b.py"])
    path = do_report(env, modified=["src/a.py"])
    [(_c, _a, detail)] = resolver.do_report_gaps(env.project, DO_ID, path, str(env.tx.path))
    assert detail.endswith(json.dumps(["src/a.py", "src/b.py"]))


def test_r8_a_versioned_report_failing_its_schema_is_a_gap(env):
    """The do-report gate's schema case (stop-do-report-gate.py, a stub after P5), now the do branch's."""
    do_span(env)
    path = do_report(env)
    record = json.loads(path.read_text())
    record["report_version"] = 1
    record["do"]["files_modified"] = "src/a.py"
    path.write_text(json.dumps(record))
    gaps = resolver.do_report_gaps(env.project, DO_ID, path, str(env.tx.path))
    assert {code for code, _a, _d in gaps} == {"SCHEMA_VIOLATION"}
    assert any("files_modified" in detail for _c, _a, detail in gaps)


def test_r8_without_a_transcript_or_a_dev_report_the_lists_stand(env):
    path = do_report(env, modified=["src/never.py"])
    assert resolver.do_report_gaps(env.project, DO_ID, path) == []


def test_r8_without_a_transcript_dev_s_report_lists_the_do_report_s_files(env):
    """The route without a transcript (Q7, a /close or /commit stage; P3's do branch calls it at
    P3's merge), as P5-62 corrects it: where the task's dev-report concludes it, that report must
    hold each file the do-report lists (it may hold more: what dev wrote completing the /do); a
    file it lacks is one gap naming dev's report, which dev repairs, and the files exactly; no
    schema is asked of a do-report that route finds not completed."""
    path = do_report(env, modified=["src/a.py"])
    dev = env.project / "docs" / "dev" / f"dev-report-{DO_ID}.json"
    dev.write_text(json.dumps({"task_id": DO_ID, "dev": {"files_modified": ["src/a.py"], "files_created": ["src/b.py"]}}))
    assert resolver.do_report_gaps(env.project, DO_ID, path) == []
    record = json.loads(path.read_text())
    record["report_version"] = 1
    record["do"].update(status="blocked", files_modified=["src/b.py", "src/c.py"],
                        files_created=[str(env.project / "src/a.py")])
    path.write_text(json.dumps(record))
    [(code, artifact, detail)] = resolver.do_report_gaps(env.project, DO_ID, path)
    assert code == "FILES_NOT_DEV_REPORT" and artifact == f"docs/dev/dev-report-{DO_ID}.json"
    assert detail.endswith(json.dumps(["src/c.py"]))


def test_r8_span_write_set_actor_and_bound(env):
    env.tx.command("do", "x")
    write_files(env, ["src/a.py"])
    env.tx.tool("Write", {"file_path": str(env.project / "src/agent.py"), "content": "x"}, sidechain=True)
    stop = sum(1 for _ in env.tx.path.open()) + 1
    write_files(env, ["src/later.py"])
    span = command_span.active_span(env.tx.path)
    assert span.write_set(env.project, stop_line=stop).written == {"src/a.py"}
    assert span.write_set(env.project, actor=None).written == {"src/a.py", "src/agent.py", "src/later.py"}


# ---------------------------------------------------------------- A6, A7: git facts
GIT_CLOCK = [T0.timestamp() - 600]  # git's clock (its reflog times), apart from the opener's at T0


def git(root, *args, check=True):
    GIT_CLOCK[0] += 1
    environment = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
                   "GIT_COMMITTER_DATE": f"@{int(GIT_CLOCK[0])} +0000"}
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=environment)
    assert done.returncode == 0 or not check, done.stderr
    return done.stdout.strip()


def commit(root, name, message=None):
    (Path(root) / name).write_text(name)
    git(root, "add", name)
    git(root, "commit", "-q", "-m", message or name)
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(env):
    GIT_CLOCK[0] = T0.timestamp() - 600
    root = env.project
    git(root, "init", "-q", "-b", "master")
    git(root, "config", "core.logAllRefUpdates", "true")
    commit(root, "base.txt")
    return root


def opener_now(env, command, args="", context=None):
    """The opener, stamped after every git step so far and before every later one."""
    env.tx.clock = datetime.fromtimestamp(GIT_CLOCK[0] + 8, timezone.utc)
    env.tx.command(command, args, context)
    GIT_CLOCK[0] += 20


def push_opener(env, args="", line=True):
    """The /push opener; with ``line``, with the hook context hooks/prompt-workflow.py prints for it in the
    project (its HEAD line), as the CLI records it. Without: an opener typed before the hook printed one."""
    home = env.tmp / "hook-home"
    environment = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "GIT_"))}
    environment.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), CLAUDE_PROJECT_DIR=str(env.project),
                       CLAUDE_STATE_DIR=str(env.tmp / "hook-state"), PYTHONDONTWRITEBYTECODE="1")
    (env.tmp / "hook-state").mkdir(exist_ok=True)
    payload = {"session_id": SID, "prompt": f"/push {args}".strip(), "cwd": str(env.project),
               "transcript_path": str(env.tx.path), "hook_event_name": "UserPromptSubmit"}
    done = subprocess.run([sys.executable, str(HOOKS / "prompt-workflow.py")], input=json.dumps(payload),
                          capture_output=True, text=True, env=environment, timeout=60)
    assert done.returncode == 0 and "[/push] HEAD at the opener: " in done.stdout, (done.stdout, done.stderr)
    opener_now(env, "push", args, done.stdout if line else None)
    return done.stdout


@pytest.mark.parametrize("typed", [True, False])
def test_a6_merge_holds_once_the_default_branch_merged_the_source(env, repo, typed):
    git(repo, "checkout", "-q", "-b", "feature")
    tip = commit(repo, "f.txt")
    opener_now(env, "merge", "feature" if typed else "")
    assert run(env)[0] == 2  # unmerged
    git(repo, "checkout", "-q", "master")
    git(repo, "merge", "-q", "--no-ff", "--no-edit", "feature")
    assert run(env) == (0, "")
    git(repo, "branch", "-q", "-D", "feature")  # the wrapper's cleanup
    assert run(env) == (0, "")
    assert git(repo, "rev-parse", "HEAD^2") == tip


def test_a6_bare_merge_of_another_branch_than_steps_pick_blocks(env, repo):
    git(repo, "checkout", "-q", "-b", "other")
    commit(repo, "o.txt")
    git(repo, "checkout", "-q", "-b", "pick", "master")
    commit(repo, "p.txt")
    opener_now(env, "merge")
    git(repo, "checkout", "-q", "master")
    git(repo, "merge", "-q", "--no-ff", "--no-edit", "other")
    code, text = run(env)
    assert code == 2 and "no merge of pick" in text


def test_a6_merge_no_commit_needs_merge_head_at_the_source(env, repo):
    git(repo, "checkout", "-q", "-b", "feature")
    commit(repo, "f.txt")
    git(repo, "checkout", "-q", "-b", "other", "master")
    commit(repo, "o.txt")
    git(repo, "checkout", "-q", "master")
    opener_now(env, "merge", "--no-commit feature")
    git(repo, "merge", "-q", "--no-commit", "--no-ff", "other")
    assert run(env)[0] == 2
    git(repo, "merge", "--abort")
    git(repo, "merge", "-q", "--no-commit", "--no-ff", "feature")
    assert run(env) == (0, "")


def test_a6_a7_an_analyst_prompt_naming_a_merged_tip_does_not_count_and_a_later_source_commit_does_not_reblock(
        env, repo):
    git(repo, "checkout", "-q", "-b", "feature")
    commit(repo, "f.txt")
    merged_elsewhere = git(repo, "rev-parse", "master")
    opener_now(env, "merge", "feature")
    env.tx.tool("Agent", {"subagent_type": "merge-analyst", "prompt": f"SOURCE_TIP={merged_elsewhere}\n"
                          "DEFAULT_BRANCH=master\n"})
    assert run(env)[0] == 2
    git(repo, "checkout", "-q", "master")
    git(repo, "merge", "-q", "--no-ff", "--no-edit", "feature")
    git(repo, "checkout", "-q", "feature")
    commit(repo, "g.txt")  # the source moves after the landed merge
    assert run(env) == (0, "")


def branches(repo, *names):
    """A commit of its own on each named branch, cut from master; HEAD back on master."""
    for name in names:
        git(repo, "checkout", "-q", "-b", name, "master")
        commit(repo, f"{name}.txt")
    git(repo, "checkout", "-q", "master")


def write_grant(env, repo, branch, verdict="approved", session=SID):
    """The merge-analyst's grant for ``branch``, as agents/merge-analyst.md Phase 8 writes it, at
    git's clock: one hooks/lib/merge_grant.py's check passes, as at the PostToolUse of that Write."""
    merge_grant, top = importlib.import_module("lib.merge_grant"), os.path.realpath(repo)
    request = f"{int(GIT_CLOCK[0]):032x}"
    path = Path(merge_grant.grant_root(), hashlib.sha256(top.encode()).hexdigest()[:16], session, f"{request}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    expires = (datetime.now(timezone.utc) + timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(json.dumps({
        "verdict": verdict, "risks": ["conflict markers in the diff"] if verdict == "blocked" else [],
        "analysis_summary": "clean", "repo_root": top, "branch": branch,
        "source_tip": git(repo, "rev-parse", branch), "default_branch": "master",
        "default_tip": git(repo, "rev-parse", "master"), "session_id": session, "nonce": request,
        "expires_at": expires}))
    assert merge_grant.fault(str(path)) == ""
    GIT_CLOCK[0] += 1
    os.utime(path, (GIT_CLOCK[0], GIT_CLOCK[0]))


@pytest.mark.parametrize("typed", [True, False])
def test_mg1_a_blocked_merge_analyst_grant_for_the_sources_tip_releases_the_stop(env, repo, typed):
    """/merge Step 3 refuses "merge-analyst blocked the merge" and R14 leaves the risks to the owner: the
    agent cannot merge anyway, so the missing merge is no gap while this session's newest grant is
    blocked for the source at its tip now. Narrow as p_push's: every other grant holds."""
    branches(repo, "feature")
    git(repo, "checkout", "-q", "feature")  # a bare /merge picks the branch HEAD is on
    opener_now(env, "merge", "feature" if typed else "")
    git(repo, "checkout", "-q", "master")
    assert run(env)[0] == 2  # no grant yet
    write_grant(env, repo, "feature", "blocked")
    assert run(env) == (0, "")


@pytest.mark.parametrize("what", ["other-tip", "other-branch", "older-grant", "other-session", "approved",
                                  "approved-after-blocked"])
def test_mg1_every_other_grant_still_holds_the_missing_merge(env, repo, what):
    branches(repo, "feature", "other")
    if what == "older-grant":
        write_grant(env, repo, "feature", "blocked")  # an earlier /merge's, written before the opener
    opener_now(env, "merge", "feature")
    if what == "other-tip":
        write_grant(env, repo, "feature", "blocked")
        git(repo, "checkout", "-q", "feature")
        commit(repo, "g.txt")  # the branch moves on: the grant names the tip before this commit
        git(repo, "checkout", "-q", "master")
    elif what == "other-branch":
        write_grant(env, repo, "other", "blocked")
    elif what == "other-session":
        write_grant(env, repo, "feature", "blocked", session="another-session")
    elif what == "approved":
        write_grant(env, repo, "feature", "approved")
    elif what == "approved-after-blocked":
        write_grant(env, repo, "feature", "blocked")
        write_grant(env, repo, "feature", "approved")
    code, text = run(env)
    assert code == 2 and "no merge of feature into refs/heads/master" in text, (code, text)


@pytest.mark.parametrize("typed", [True, False])
def test_a6_a_source_already_in_the_default_branch_holds(env, repo, typed):
    """merge.sh's conflict text has the human commit the merge and type /merge <ref> again, and a
    re-run after a completed merge is idempotent: git's "Already up to date" writes no reflog entry."""
    branches(repo, "feature")
    git(repo, "merge", "-q", "--no-ff", "--no-edit", "feature")
    git(repo, "checkout", "-q", "feature")  # in place on the source: a bare /merge's tier 3
    opener_now(env, "merge", "feature" if typed else "")
    git(repo, "checkout", "-q", "master")
    git(repo, "merge", "-q", "--no-edit", "feature")
    assert run(env) == (0, "")


@pytest.mark.parametrize("args", ["", "master", "same", "no-such-ref"])
def test_a6_step_1s_refusals_hold_with_nothing_merged_and_a_merge_no_grant_names_blocks(env, repo, args):
    """Bare on the default branch (tier 3 degenerates), a typed ref at the default branch's commit
    (self-merge) or one that resolves to nothing (missing tip): Step 1 refuses and nothing is
    merged. A merge into the default branch after the opener then has no source, and a grant this
    session wrote before the opener (an earlier /merge) names none."""
    git(repo, "branch", "same")
    branches(repo, "other")
    write_grant(env, repo, "other")
    opener_now(env, "merge", args)
    assert run(env) == (0, "")
    git(repo, "merge", "-q", "--no-ff", "--no-edit", "other")
    code, text = run(env)
    assert code == 2 and "no merge-analyst grant" in text


@pytest.mark.parametrize("args", ["", "master", "--no-commit"])
def test_a6_with_no_source_from_git_steps_pick_is_the_merge_analysts_grant(env, repo, args):
    """A bare /merge on the default branch (Step 0's tier 2 from an overnight-state record that
    merge.sh's cleanup removes), or the ref a self-merge refusal's answer named: the source is the
    newest merge-analyst grant this session wrote since the opener."""
    branches(repo, "feature", "other")
    opener_now(env, "merge", args)
    write_grant(env, repo, "feature")
    held = args == "--no-commit"
    flag = "--no-commit" if held else "--no-edit"
    git(repo, "merge", "-q", "--no-ff", flag, "other")
    code, text = run(env)
    assert code == 2 and ("MERGE_HEAD is" if held else "no merge of feature") in text
    if held:
        git(repo, "merge", "--abort")
    git(repo, "merge", "-q", "--no-ff", flag, "feature")
    assert run(env) == (0, "")
    if held:
        git(repo, "commit", "-q", "--no-edit")
    git(repo, "branch", "-q", "-D", "feature")  # the wrapper's cleanup
    assert run(env) == (0, "")


@pytest.mark.parametrize("content", ["#" * 300, "[]"])
@pytest.mark.parametrize("on", ["feature", "master"])
def test_a6_a_grant_that_is_no_json_object_is_none_as_the_check_on_its_write_removes_it(env, repo, on, content):
    """hooks/lib/merge_grant.py's check on the merge-analyst's Write removes a grant that is no JSON
    object (the artifact check's invalid content); the gate reads the grant through that check's own
    load(), so such a grant is none, never a gap or a release of the gate's own. In place on the
    source (the /merge replays) Step 0's pick from git decides; on the default branch the merge stays
    the gap a missing grant leaves until the merge-analyst writes the grant again."""
    branches(repo, "feature")
    git(repo, "checkout", "-q", on)
    opener_now(env, "merge")
    write_grant(env, repo, "feature")
    grant = next(Path(importlib.import_module("lib.merge_grant").grant_root()).rglob("*.json"))
    stamp = grant.stat().st_mtime
    grant.write_text(content)
    os.utime(grant, (stamp, stamp))
    git(repo, "checkout", "-q", "master")
    git(repo, "merge", "-q", "--no-ff", "--no-edit", "feature")
    if on == "master":
        code, text = run(env)
        assert code == 2 and "no merge-analyst grant of this session since the opener names its source" in text
        write_grant(env, repo, "feature")
    assert run(env) == (0, "")


@pytest.mark.parametrize("finish", ["commit", "abort"])
def test_a6_merge_no_commit_finalized_or_aborted_decides_as_a_committed_merge(env, repo, finish):
    branches(repo, "feature")
    opener_now(env, "merge", "--no-commit feature")
    git(repo, "merge", "-q", "--no-commit", "--no-ff", "feature")
    assert run(env) == (0, "")
    if finish == "commit":  # merge.sh's printed finalize
        git(repo, "commit", "-q", "--no-edit")
        assert run(env) == (0, "")
        return
    git(repo, "merge", "--abort")
    code, text = run(env)
    assert code == 2 and "no merge of feature into refs/heads/master" in text
    git(repo, "merge", "-q", "--no-commit", "--no-ff", "feature")  # the merge made again
    assert run(env) == (0, "")


@pytest.fixture(params=["main", "worktree"])
def linked(env, monkeypatch, request):
    """/dev-overnight --worktree's shape: the main checkout (a repository with a local bare origin)
    and the linked worktree the session's cwd is in (Step 1 cds into it), on Step 0's pick, the
    overnight-state record's worktree_branch, which merge.sh's cleanup removes. The session's project
    dir is the main checkout (the CLI's) or the worktree itself. The main checkout is on a working
    branch: merge.sh checks the default branch out in the linked worktree, which git refuses while
    another worktree has it. Branch ``other`` is no pick."""
    GIT_CLOCK[0] = T0.timestamp() - 600
    origin, main, tree = env.tmp / "origin.git", env.project, env.tmp / "overnight-x"
    git(env.tmp, "init", "-q", "--bare", "-b", "master", str(origin))
    git(main, "init", "-q", "-b", "master")
    git(main, "config", "core.logAllRefUpdates", "true")
    git(main, "remote", "add", "origin", str(origin))
    commit(main, "base.txt")
    git(main, "push", "-q", "-u", "origin", "master")
    git(main, "remote", "set-head", "origin", "master")
    branches(main, "other")
    git(main, "checkout", "-q", "-b", "work")
    git(main, "worktree", "add", "-q", "-b", "overnight-x", str(tree), "master")
    commit(tree, "x.txt")
    project = main if request.param == "main" else tree
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    (project / ".claude").mkdir(exist_ok=True)
    (project / ".claude" / f"overnight-state-{SID}.json").write_text(json.dumps({"worktree_branch": "overnight-x"}))
    env.payload["cwd"] = str(tree)
    return tree


def merge_sh(tree, *args):
    """/merge Step 5 in the linked worktree: hooks/merge.sh itself, at git's clock."""
    GIT_CLOCK[0] += 1
    environment = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
                   "GIT_AUTHOR_DATE": f"@{int(GIT_CLOCK[0])} +0000",
                   "GIT_COMMITTER_DATE": f"@{int(GIT_CLOCK[0])} +0000"}
    done = subprocess.run(["bash", str(HOOKS / "merge.sh"), *args], cwd=str(tree), capture_output=True, text=True,
                          env=environment, timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


@pytest.mark.parametrize("grant", [False, True])
@pytest.mark.parametrize("diverged", [False, True])
def test_a6_bare_merge_from_a_linked_worktree_holds_once_steps_pick_merged_also_after_cleanup(
        env, linked, diverged, grant):
    """Bare /merge in the linked worktree: unmerged 2; merged by merge.sh (a fast-forward, or a merge
    commit when the default branch moved) and cleaned up (branch, its reflog and the overnight-state
    record gone) 0; with or without the merge-analyst's grant of Step 2, which names the pick too."""
    if diverged:
        git(env.project, "checkout", "-q", "master")
        commit(env.project, "m.txt")
        git(env.project, "checkout", "-q", "work")
    pick = git(linked, "rev-parse", "HEAD")
    opener_now(env, "merge")
    code, text = run(env)
    assert code == 2 and "no merge of overnight-x" in text  # unmerged
    if grant:
        write_grant(env, linked, "overnight-x")
    merge_sh(linked, "overnight-x")
    assert git(linked, "rev-parse", "--verify", "-q", "refs/heads/overnight-x", check=False) == ""
    assert not list(Path(os.environ["CLAUDE_PROJECT_DIR"], ".claude").glob("overnight-state-*.json"))
    assert run(env) == (0, "")
    assert pick in git(linked, "rev-list", "--parents", "-n", "1", "master").split()


def test_a6_bare_merge_from_a_linked_worktree_of_another_branch_than_steps_pick_blocks(env, linked):
    """Step 0's pick is the branch the worktree's HEAD was on at the opener: git's own record of it
    is the worktree's HEAD reflog (its value at the opener and the checkout entry that left it)."""
    opener_now(env, "merge")
    merge_sh(linked, "other")
    code, text = run(env)
    assert code == 2 and "no merge of overnight-x into refs/heads/master" in text
    assert "checkout: moving from overnight-x to master" in git(linked, "reflog", "show", "--format=%gs", "HEAD")
    merge_sh(linked, "overnight-x")  # the pick merged too: the gap closes
    assert run(env) == (0, "")


def test_a6_bare_merge_no_commit_from_a_linked_worktree_needs_merge_head_at_steps_pick(env, linked):
    opener_now(env, "merge", "--no-commit")
    merge_sh(linked, "--no-commit", "other")
    code, text = run(env)
    assert code == 2 and "MERGE_HEAD is" in text
    git(linked, "merge", "--abort")
    merge_sh(linked, "--no-commit", "overnight-x")
    assert run(env) == (0, "")


def test_a6_a_cwd_in_another_repository_does_not_stand_in_for_the_project(env, repo):
    """Only a worktree of the project's own repository is read in its place: a cwd in a clone of it,
    where Step 0's pick merged, leaves the project's unmerged pick the gap."""
    branches(repo, "feature")
    git(repo, "checkout", "-q", "feature")
    elsewhere = env.tmp / "elsewhere"
    git(env.tmp, "clone", "-q", "-b", "feature", str(repo), str(elsewhere))
    git(elsewhere, "branch", "-q", "master", "origin/master")
    env.payload["cwd"] = str(elsewhere)
    opener_now(env, "merge")
    git(elsewhere, "checkout", "-q", "master")
    git(elsewhere, "merge", "-q", "--no-ff", "--no-edit", "feature")
    code, text = run(env)
    assert code == 2 and "no merge of feature into refs/heads/master" in text
    env.payload["cwd"] = str(repo / "docs")  # the project's own checkout, from a subdirectory
    assert run(env)[0] == 2


def write_token(repo):
    """The push-gate token for the branch at HEAD, by its one writer, as /commit's changelog-analyst runs it."""
    writer = gate._script("scripts/write-push-gate-token.py")
    branch, head = git(repo, "branch", "--show-current"), git(repo, "rev-parse", "HEAD")
    assert writer.main(["--repo-root", str(repo), "--branch", branch, "--commit", head]) == 0


def write_push_grant(env, repo, verdict):
    """The push-analyst's grant for the branch at HEAD, as agents/push-analyst.md Phase 7 writes it, at
    commands/push.md Step 4's path and git's clock."""
    top, request = os.path.realpath(repo), f"{int(GIT_CLOCK[0]):032x}"
    path = Path(env.state, "agentic-commit", "push-analyst", hashlib.sha256(top.encode()).hexdigest()[:16], SID,
                f"{request}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    expires = (datetime.now(timezone.utc) + timedelta(seconds=600)).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(json.dumps({
        "verdict": verdict, "risks": ["sensitive file pattern in commits-to-push: .env"] if verdict == "blocked" else [],
        "analysis_summary": verdict, "branch": git(repo, "branch", "--show-current"),
        "head_sha": git(repo, "rev-parse", "HEAD"), "remote_name": "origin", "remote_url": str(env.tmp / "origin.git"),
        "session_id": SID, "nonce": request, "expires_at": expires}))
    GIT_CLOCK[0] += 1
    os.utime(path, (GIT_CLOCK[0], GIT_CLOCK[0]))


@pytest.fixture
def remotes(env, repo, monkeypatch):
    """topic, pushed to origin with upstream set, after the /commit whose push-gate token names it."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SID)
    for name in ("origin", "fork"):
        bare = env.tmp / f"{name}.git"
        git(env.tmp, "init", "-q", "--bare", str(bare))
        git(repo, "remote", "add", name, str(bare))
    git(repo, "checkout", "-q", "-b", "topic")
    commit(repo, "t1.txt")
    write_token(repo)
    git(repo, "push", "-q", "-u", "origin", "topic")
    return repo


def test_a6_a7_push_ahead_blocks_pushed_holds_and_a_later_commit_does_not_reblock(env, remotes):
    opener_now(env, "push")
    assert run(env)[0] == 0  # nothing ahead of the upstream
    commit(remotes, "t2.txt")
    code, text = run(env)
    assert code == 2 and "not published" in text
    git(remotes, "push", "-q", "origin", "topic")
    assert run(env) == (0, "")
    commit(remotes, "t3.txt")
    assert run(env) == (0, "")


def test_a6_push_tracking_fork_needs_the_fork_even_when_origin_had_head(env, remotes):
    git(remotes, "push", "-q", "fork", "topic")
    git(remotes, "branch", "-q", "--set-upstream-to", "fork/topic")
    commit(remotes, "t2.txt")
    git(remotes, "push", "-q", "origin", "topic")  # origin had HEAD before the opener
    opener_now(env, "push")
    assert run(env)[0] == 2
    git(remotes, "push", "-q", "fork", "topic")
    assert run(env) == (0, "")


def test_a6_typed_push_counts_only_the_typed_remote(env, remotes):
    commit(remotes, "t2.txt")
    opener_now(env, "push", "fork")
    git(remotes, "push", "-q", "origin", "topic")  # only to the upstream, which differs
    assert run(env)[0] == 2
    git(remotes, "push", "-q", "fork", "topic")
    assert run(env) == (0, "")


@pytest.mark.parametrize("typed", ["upstrem", "fork"])
def test_m_a_typed_push_remote_that_is_no_remote_yields_to_the_remote_the_push_took(env, remotes, typed):
    """P5 review M: the owner mistypes the /push remote (`upstrem`, no remote of the repository, which
    push.sh refuses); the agent asks, the owner's answer names origin, and the branch is pushed there.
    The Stop holds naming the typed name and the unpublished commit until a remote's ref takes HEAD
    after the opener (git's reflog; the owner's answer is no fact, D23), then passes with the push-gate
    token still naming HEAD. A typed remote that is one (fork) stays the target: origin does not
    clear it."""
    head = commit(remotes, "t2.txt")
    opener_now(env, "push", typed)
    code, text = run(env)
    named = ("a remote since the /push opener; the typed name upstrem is no remote of this repository"
             if typed == "upstrem" else "refs/remotes/fork/topic since the /push opener")
    assert code == 2 and f"- push: topic at {head} is not published on {named}\n" in text, text
    env.tx.ask("origin")
    assert run(env)[0] == 2
    git(remotes, "push", "-q", "origin", "topic")
    if typed == "fork":
        assert run(env)[0] == 2
        git(remotes, "push", "-q", "fork", "topic")
    assert run(env) == (0, "")


@pytest.mark.parametrize("line", [True, False])
def test_a6_push_from_a_detached_head_holds_as_step_2s_refusal(env, remotes, line):
    """push.md Step 2 refuses a detached HEAD ("check out the branch to push"): no push can be made
    from it, so the run is complete. With the branch checked out, ahead and with a token, the push
    is owed; detached again, it is not (H2 keeps this release for a HEAD detached at the opener: so
    its HEAD line says, else git's record)."""
    commit(remotes, "t2.txt")
    git(remotes, "checkout", "-q", "--detach")
    printed = push_opener(env, line=line)
    assert f"[/push] HEAD at the opener: detached {git(remotes, 'rev-parse', 'HEAD')}\n" in printed, printed
    assert run(env) == (0, "")
    git(remotes, "checkout", "-q", "topic")
    code, text = run(env)
    assert code == 2 and "not published" in text
    git(remotes, "checkout", "-q", "--detach", "HEAD~1")
    assert run(env) == (0, "")


@pytest.mark.parametrize("line", [True, False])
@pytest.mark.parametrize("move", [("checkout", "-q", "--detach"), ("checkout", "-q", "master"),
                                  ("checkout", "-q", "--detach", "topic")])
def test_h2_head_moved_off_the_branch_after_the_opener_holds_that_branch_until_it_is_published(env, remotes, move,
                                                                                              line):
    """P5 review H2: a detach (or a checkout of another branch) after the /push opener is no Step 2
    refusal: the branch HEAD was on at the opener (its HEAD line's; an opener with none, git's record:
    the source of HEAD's first checkout after it) is held, at its tip, naming the branch to check out,
    until the push publishes it."""
    tip = commit(remotes, "t2.txt")
    push_opener(env, line=line)
    git(remotes, *move)
    code, text = run(env)
    assert code == 2 and f"- push: topic at {tip} is not published on refs/remotes/origin/topic" in text, text
    assert "HEAD is not on it: check out topic, then push it" in text
    git(remotes, "checkout", "-q", "topic")
    code, text = run(env)
    assert code == 2 and f"- push: topic at {tip} is not published" in text and "check out" not in text
    git(remotes, *move)
    git(remotes, "push", "-q", "origin", "topic")  # the branch published, wherever HEAD is
    assert run(env) == (0, "")


def backdated(root, *args):
    """git in ``root`` with GIT_COMMITTER_DATE=@1, which any command may set: git's reflog dates the
    entry before every opener."""
    saved, GIT_CLOCK[0] = GIT_CLOCK[0], 0
    try:
        return git(root, *args)
    finally:
        GIT_CLOCK[0] = saved


@pytest.mark.parametrize("move", [("checkout", "-q", "--detach"), ("checkout", "-q", "master")])
def test_h2_a_backdated_move_off_the_branch_holds_the_branch_the_opener_line_names(env, remotes, move):
    """P5 review H2, open after bc51850: `GIT_COMMITTER_DATE=@1 git checkout -q --detach` (or of master)
    dates HEAD's reflog entry before the opener, so git's record had HEAD detached (or on master) at the
    opener and the Stop released. The opener's HEAD line names topic at its commit: the Stop holds on
    it, naming the branch to check out, until the push publishes it. An echo of the line in another
    hook's context, detached, takes nothing away."""
    tip = commit(remotes, "t2.txt")
    assert f"[/push] HEAD at the opener: refs/heads/topic {tip}\n" in push_opener(env)
    env.tx.add({"type": "attachment", "attachment": {"type": "hook_additional_context", "hookName": "UserPromptSubmit",
                                                     "content": f"notice\n[/push] HEAD at the opener: detached {tip}\n"}})
    backdated(remotes, *move)
    code, text = run(env)
    assert code == 2 and (f"- push: topic at {tip} is not published on refs/remotes/origin/topic since the /push "
                          "opener; HEAD is not on it: check out topic, then push it\n") in text, text
    git(remotes, "checkout", "-q", "topic")
    git(remotes, "push", "-q", "origin", "topic")
    assert run(env) == (0, "")


@pytest.mark.parametrize("move", [("--soft", "HEAD~1"), ("HEAD~1",), "recommitted"])
def test_h2_a_reset_after_the_opener_holds_the_opener_commit_until_it_is_published(env, remotes, move):
    """P5 review H2, open after bc51850: `git reset --soft HEAD~1` (allowed) moves topic back to its
    published commit, so topic was at its upstream and the Stop released with the owner's commit
    unpublished, its changes staged. The opener's HEAD line names that commit: where topic does not
    hold it (reset, mixed or soft, or reset and committed again) the Stop holds on it, naming where
    topic is, and a push of topic as it is publishes nothing; put back at it and pushed, it passes."""
    owner = commit(remotes, "t2.txt")
    write_token(remotes)
    push_opener(env)
    git(remotes, "reset", "-q", *(("--soft", "HEAD~1") if move == "recommitted" else move))
    if move == "recommitted":
        git(remotes, "commit", "-q", "-m", "t2 again")
    else:
        git(remotes, "push", "-q", "origin", "topic")  # nothing to push: topic is at its upstream
    tip = git(remotes, "rev-parse", "topic")
    code, text = run(env)
    assert code == 2 and (f"- push: topic at {owner} is not published on refs/remotes/origin/topic since the "
                          f"/push opener; topic is at {tip}, which does not hold it: put topic back at it, then "
                          "push it\n") in text, text
    git(remotes, "reset", "-q", "--soft", owner)
    code, text = run(env)
    assert code == 2 and f"- push: topic at {owner} is not published on refs/remotes/origin/topic since the " \
                         "/push opener\n" in text, text
    git(remotes, "push", "-q", "origin", "topic")
    assert run(env) == (0, "")


def tool_policy(env, tool_input: dict, agent=None):
    """hooks/pretool-tool-policy.py on one Write, as the CLI runs it for the main agent (or `agent`)."""
    payload = {"session_id": SID, "transcript_path": str(env.tx.path), "cwd": str(env.project),
               "hook_event_name": "PreToolUse", "tool_name": "Write", "tool_input": tool_input,
               "tool_use_id": "toolu_h2", **({"agent_id": agent[0], "agent_type": agent[1]} if agent else {})}
    home = env.tmp / "home"
    environment = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    environment.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), CLAUDE_STATE_DIR=str(env.state),
                       CLAUDE_PROJECT_DIR=str(env.project), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, str(HOOKS / "pretool-tool-policy.py")], input=json.dumps(payload),
                          capture_output=True, text=True, env=environment, timeout=60)


@pytest.mark.parametrize("caller", [None, ("a0dev", "dev"), ("a0pa", "push-analyst")])
@pytest.mark.parametrize("attack", ["token", "grant"])
def test_h2_no_caller_but_the_producer_writes_the_push_stops_inputs_so_the_stop_holds(env, remotes, attack, caller):
    """P5 review H2: a Write of `{}` over the push-gate token, or of a `blocked` grant for the branch at
    HEAD into the push-analyst's grant directory, by the main agent or a subagent whose own dispatch is
    not that grant's (none here), is refused by the protected stage; the Stop holds on the token the
    token's writer left and on no blocked grant, until the push."""
    head = commit(remotes, "t2.txt")
    write_token(remotes)
    opener_now(env, "push")
    top = os.path.realpath(remotes)
    if attack == "token":
        writer = gate._script("scripts/write-push-gate-token.py")
        path, content = str(writer.token_path(top, "topic", SID)), "{}"
    else:
        path = str(Path(env.state, "agentic-commit", "push-analyst", hashlib.sha256(top.encode()).hexdigest()[:16],
                        SID, "ab" * 16 + ".json"))
        content = json.dumps({"verdict": "blocked", "branch": "topic", "head_sha": head})
    done = tool_policy(env, {"file_path": path, "content": content}, caller)
    assert done.returncode == 2 and "no agent writes, deletes or renames it (D11/D12)" in done.stderr, done.stderr
    code, text = run(env)
    assert code == 2 and f"- push: topic at {head} is not published" in text
    git(remotes, "push", "-q", "origin", "topic")
    assert run(env) == (0, "")


@pytest.mark.parametrize("token", ["none for the branch", "not in HEAD's history"])
def test_a6_push_with_no_usable_push_gate_token_holds_as_push_shs_refusal(env, remotes, token):
    """push.md Step 5: push.sh refuses (exit 3, "run /commit first") while no push-gate token names an
    ancestor of HEAD: a branch the owner committed to without /commit, or a token whose commit left
    HEAD's history. Once the token's writer names HEAD, the push is owed."""
    if token == "none for the branch":
        git(remotes, "checkout", "-q", "-b", "other", "master")
    else:
        git(remotes, "reset", "-q", "--hard", "master")
    commit(remotes, "t2.txt")
    opener_now(env, "push")
    assert run(env) == (0, "")
    write_token(remotes)
    code, text = run(env)
    assert code == 2 and "not published" in text


def test_a6_push_holds_on_the_push_analysts_blocked_verdict_for_head(env, remotes):
    """push.md Step 5: execute-push.py refuses a blocked grant ("push BLOCKED by push-analyst", action
    "resolve the listed risks first") and leaves it unspent. It holds as this session's newest grant
    since the opener, for the branch at HEAD: not one written before the opener, not once HEAD moved
    past it, not under a newer approved one."""
    commit(remotes, "t2.txt")
    write_push_grant(env, remotes, "blocked")  # an earlier /push's
    opener_now(env, "push")
    assert run(env)[0] == 2
    write_push_grant(env, remotes, "blocked")
    assert run(env) == (0, "")
    commit(remotes, "t3.txt")  # the risks resolved by a commit: the new HEAD's push is owed
    assert run(env)[0] == 2
    write_push_grant(env, remotes, "blocked")
    assert run(env) == (0, "")
    write_push_grant(env, remotes, "approved")
    code, text = run(env)
    assert code == 2 and "not published" in text
    git(remotes, "push", "-q", "origin", "topic")
    assert run(env) == (0, "")


def _forge_file(repo, rel, text, mode="w"):
    path = Path(repo, ".git", rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode) as handle:
        handle.write(text)


def _forge_reflog(repo, _bare=None):
    """An `update by push` entry appended to the tracking ref's reflog file, dated now on git's clock."""
    GIT_CLOCK[0] += 1
    old, new = git(repo, "rev-parse", "refs/remotes/origin/topic"), git(repo, "rev-parse", "HEAD")
    _forge_file(repo, "logs/refs/remotes/origin/topic", f"{old} {new} t <t@example.invalid> {int(GIT_CLOCK[0])} +0000"
                                                         "\tupdate by push\n", "a")


def _forge_packed(repo, _bare=None):
    """The tracking ref moved into packed-refs, there naming HEAD (no loose ref, no reflog entry)."""
    Path(repo, ".git", "refs", "remotes", "origin", "topic").unlink()
    _forge_file(repo, "packed-refs", f"{git(repo, 'rev-parse', 'HEAD')} refs/remotes/origin/topic\n", "a")


# P5-61: the ways an agent writes or redirects what the /push Stop took as published, none of them a push.
# Each value: the forging steps (git argument lists, or a callable on the repository), and the steps that
# undo a redirect of origin itself (or a graft, which corrupts the push too) before the real push (none: the
# push to the bare origin is enough).
FORGES = {
    "fetch-local-refspec": ([["fetch", "-q", ".", "HEAD:refs/remotes/origin/topic"]], []),
    "update-ref": ([["update-ref", "refs/remotes/origin/topic", "HEAD"]], []),
    "pull-refspec": ([["pull", "-q", "--ff-only", ".", "topic:refs/remotes/origin/topic"]], []),
    "fetch-c-refspec": ([["-c", "remote.self.url=.", "-c", "remote.self.fetch=+refs/heads/*:refs/remotes/origin/*",
                          "fetch", "-q", "self"]], []),
    "config-refspec": ([["config", "remote.self.url", "."],
                        ["config", "remote.self.fetch", "+refs/heads/*:refs/remotes/origin/*"],
                        ["fetch", "-q", "self"]], []),
    "config-url": ([["config", "remote.origin.url", "."], ["fetch", "-q", "origin"]],
                   [lambda repo, bare: git(repo, "config", "remote.origin.url", bare)]),
    "config-insteadof": ([lambda repo, bare: git(repo, "config", f"url.{repo}.insteadOf", bare), ["fetch", "-q", "origin"]],
                         [lambda repo, bare: git(repo, "config", "--unset", f"url.{repo}.insteadOf")]),
    "upstream-local": ([["config", "branch.topic.remote", "."]], []),
    "remote-add-self": ([["remote", "add", "self", "."], ["fetch", "-q", "self"]], []),
    "symbolic-ref": ([["symbolic-ref", "refs/remotes/origin/topic", "refs/heads/topic"]], []),
    "ref-file": ([lambda repo, bare: _forge_file(repo, "refs/remotes/origin/topic", git(repo, "rev-parse", "HEAD") + "\n")],
                 []),
    "packed-refs": ([_forge_packed], []),
    "reflog-file": ([_forge_reflog], []),
    "replace-graft": ([["replace", "--graft", "refs/remotes/origin/topic", "HEAD"]], []),
    "grafts-file": ([lambda repo, bare: _forge_file(repo, "info/grafts", "{} {}\n".format(
        git(repo, "rev-parse", "refs/remotes/origin/topic"), git(repo, "rev-parse", "HEAD")))],
                    [lambda repo, bare: Path(repo, ".git", "info", "grafts").unlink()]),  # it re-parents the push too
}


def remote_lines(env, repo):
    """The opener's remote lines (command_span.OPENER_REMOTE_LINE_RE) for the repository as it is now, added
    to the opener's hook context: one per remote, its URL's digest, the branch, its tracking ref's commit
    there and the branch's upstream ref where it is that remote's. P5-61's record of each remote at the
    opener; its printer is the /push opener's UserPromptSubmit hook (not in this change)."""
    branch = git(repo, "branch", "--show-current")
    up = git(repo, "for-each-ref", "--format=%(upstream:remotename) %(upstream:remoteref)", f"refs/heads/{branch}").split()
    text = "".join(
        f"[/push] remote at the opener: {name} {hashlib.sha256(git(repo, 'remote', 'get-url', name).encode()).hexdigest()[:16]} "
        f"{branch} {git(repo, 'rev-parse', '--verify', '-q', f'refs/remotes/{name}/{branch}', check=False) or 'none'}"
        + (f" upstream {up[1]}" if len(up) == 2 and up[0] == name else "") + "\n"
        for name in git(repo, "remote").split())
    env.tx.add({"type": "attachment", "attachment": {"type": "hook_additional_context", "hookName": "UserPromptSubmit",
                                                     "content": text}})


def _steps(repo, bare, steps):
    for step in steps:
        step(repo, bare) if callable(step) else git(repo, *step)


# The routes that redirect the remote itself (its URL, or a remote added): only the opener's remote lines
# date and place the remote; the others hold on the remote's own branch with or without those lines.
REDIRECTS = {"config-refspec", "config-url", "config-insteadof", "remote-add-self"}


@pytest.mark.parametrize("route,lines", [(r, lines) for r in FORGES for lines in (True, False)
                                         if lines or r not in REDIRECTS])
def test_p5_61_a_forged_or_redirected_remote_record_releases_no_push_stop_until_the_push(env, remotes, route, lines):
    """P5-61: the /push Stop took a locally written refs/remotes/<remote>/<branch> (its value or a reflog
    entry of it), the branch's upstream from the repository's config, and git's ancestry through replace
    objects and grafts as published. Every route here writes or redirects one of them after the /push
    opener without a push: the Stop holds, naming the unpublished commit, until a push to the bare
    origin lands (with a redirect of origin itself undone first)."""
    head = commit(remotes, "t2.txt")
    write_token(remotes)
    push_opener(env)
    if lines:
        remote_lines(env, remotes)
    forge, undo = FORGES[route]
    bare = str(env.tmp / "origin.git")
    _steps(remotes, bare, forge)
    code, text = run(env)
    assert code == 2 and f"- push: topic at {head} is not published" in text, (route, text)
    _steps(remotes, bare, undo)
    git(remotes, "push", "-q", "origin", "topic")
    assert run(env) == (0, ""), route


def test_p5_61_an_upstream_moved_to_a_remote_that_had_head_before_the_opener_releases_nothing(env, remotes):
    """P5-61, A6's "tracking fork: unpushed 2 even if origin had HEAD before the opener": after the opener
    the agent sets the branch's upstream to origin, which held HEAD before it. The upstream the opener
    recorded (fork) stays the one judged, until the push to it."""
    git(remotes, "push", "-q", "fork", "topic")
    git(remotes, "branch", "-q", "--set-upstream-to", "fork/topic")
    head = commit(remotes, "t2.txt")
    write_token(remotes)
    git(remotes, "push", "-q", "origin", "topic")
    push_opener(env)
    remote_lines(env, remotes)
    git(remotes, "branch", "-q", "--set-upstream-to", "origin/topic")
    code, text = run(env)
    assert code == 2 and f"- push: topic at {head} is not published on refs/remotes/fork/topic" in text, text
    git(remotes, "push", "-q", "fork", "topic")
    assert run(env) == (0, "")


def test_p5_61_a_remote_branch_ahead_at_a_commit_not_fetched_names_the_fetch(env, remotes):
    """P5-61: the remote's own branch is read, so where it moved past HEAD (another clone pushed) to a commit
    this repository lacks, HEAD's ancestry cannot be told: the gap names the fetch, after which HEAD,
    behind the upstream, is published (A6: "behind it ... 0")."""
    write_token(remotes)
    other = env.tmp / "other"
    git(env.tmp, "clone", "-q", "-b", "topic", str(env.tmp / "origin.git"), str(other))
    ahead = commit(other, "o1.txt")
    git(other, "push", "-q", "origin", "topic")
    push_opener(env)
    code, text = run(env)
    assert code == 2 and (f"; origin: its refs/heads/topic is at {ahead}, which this repository lacks: fetch origin"
                          in text), text
    git(remotes, "fetch", "-q", "origin")
    assert run(env) == (0, "")


@pytest.mark.parametrize("command", ["merge", "push"])
def test_a6_git_predicates_outside_a_repository_are_instrument_failures(env, command):
    env.tx.command(command)
    code, text = run(env)
    assert code == 2 and "gate instrument failure: RuntimeError:" in text and "not a git repository" in text


def test_a6_commit_modes_only_if_typed(env):
    """Fake disposition (P3): --stage commit's Task-id check is P3's; on the real one:
    test_a6_real_commit_needs_p3s_task_id_commit_reachable_from_head."""
    task_file(env)  # a typed id names a task (P5-4)
    env.tx.command("commit", FAMILY)
    env.fake.answers[(FAMILY, "commit")] = [gap(".", "MISSING_TASK_TRAILER", "no commit carries Task-id")]
    assert run(env)[0] == 2
    env.fake.answers[(FAMILY, "commit")] = []
    assert run(env) == (0, "")
    env.tx.command("commit", "--dry-run")
    env.fake.answers.clear()
    assert run(env) == (0, "") and env.fake.calls[-1][1] == FAMILY


def test_a6_commit_bulk_reads_the_status_block_of_its_dispatch(env):
    env.tx.command("commit", "--bulk")
    assert "no changelog-analyst status block" in run(env)[1]
    artifacts = [{"kind": "response_block", "begin": "--- B ---", "end": "--- E ---", "format": "json",
                  "schema": "changelog-status.v1"}]
    env.tx.dispatch(None, role="changelog-analyst", pipeline="commit", profile="commit-bulk", artifacts=artifacts,
                    result='--- B ---\n{"commit_status": "failed", "failure_code": "grant_missing"}\n--- E ---')
    code, text = run(env)
    assert code == 2 and "'failed': grant_missing" in text
    env.tx.dispatch(None, role="changelog-analyst", pipeline="commit", profile="commit-bulk", artifacts=artifacts,
                    result='--- B ---\n{"commit_status": "nothing_to_commit_precommitted"}\n--- E ---')
    assert run(env) == (0, "")


# ---------------------------------------------------------------- A8: /close targets and the rating
def rating_fake(required=True, asked=False):
    module = types.ModuleType("lib.close_rating")
    module.rating_required = lambda span, task_id: required
    module.rating_asked = lambda transcript_path, task_id: asked
    return module


def task_file(env, name=f"ticket-{FAMILY}.md"):
    """A file of a task under docs/dev: a typed /close id names a task (P5 review M)."""
    (env.project / "docs" / "dev" / name).write_text("{}\n" if name.endswith(".json") else "# Ticket\n")


@pytest.mark.parametrize("required,asked,code", [(True, False, 2), (True, True, 0), (False, False, 0)])
def test_a8_close_needs_the_rating_question_asked_where_required(env, monkeypatch, required, asked, code):
    """Fake close_rating (P4) and disposition (P3); on the real ones:
    test_a8_real_close_needs_p4s_rating_question_after_the_landed_close_qa."""
    monkeypatch.setitem(sys.modules, "lib.close_rating", rating_fake(required, asked))
    task_file(env)
    env.tx.command("close", FAMILY)
    env.tx.todos(canonical("close", FAMILY), len(canonical("close", FAMILY)))
    got, text = run(env)
    assert got == code and (code == 0 or "close-rating question" in text)
    assert env.fake.calls[-1][1:3] == (FAMILY, "close")


@pytest.mark.parametrize("command", ["close", "commit"])
def test_a8_auto_targets_come_from_the_lifecycle_function_never_a_tool_result(env, monkeypatch, command):
    monkeypatch.setitem(sys.modules, "lib.close_rating", rating_fake(False))
    lifecycle = types.SimpleNamespace(calls=[])
    lifecycle.auto_targets = lambda root, action, cutoff: lifecycle.calls.append((action, cutoff)) or [FAMILY]
    monkeypatch.setitem(gate._SCRIPTS, "scripts/dev-lifecycle.py", lifecycle)
    env.tx.command(command, "--auto")
    env.tx.tool("Bash", {"command": f"python3 scripts/dev-lifecycle.py list-actionable --next-action {command}"},
                result="20990101-000000")
    env.fake.answers[(FAMILY, command)] = [gap(f"docs/dev/close-report-{FAMILY}.md", "INVALID_CLOSE_VERDICT", "no")]
    code, text = run(env)
    assert code == 2 and "20990101" not in text and "INVALID_CLOSE_VERDICT" in text
    opened = command_span.active_span(env.tx.path).opened_at()
    assert lifecycle.calls == [(command, opened)] and opened is not None
    assert {c[1] for c in env.fake.calls} == {FAMILY}


def test_a8_no_target_names_the_gap(env, monkeypatch):
    monkeypatch.setitem(sys.modules, "lib.close_rating", rating_fake())
    env.tx.command("close")
    code, text = run(env)
    assert code == 2 and "close: no target task resolved" in text


def test_a8_auto_targets_leave_out_a_task_registered_after_the_cut_off():
    lifecycle = _load(REPO / "scripts" / "dev-lifecycle.py", "lifecycle_under_test")
    rows = [{"task_id": t, "kind": "ticket", "next_action": "close"}
            for t in ("20261101-080000", "20261101-100000", "spec-like")]
    cutoff = datetime(2026, 11, 1, 9, 0, 0).timestamp()  # the minting clock's local time
    assert lifecycle.auto_targets(Path("."), "close", cutoff, rows) == ["20261101-080000", "spec-like"]
    assert lifecycle.auto_targets(Path("."), "close", None, rows) == sorted(r["task_id"] for r in rows)


def test_a8_close_auto_targets_pass_over_a_task_whose_gap_nobody_owes():
    """P4 (review 2, D25), at its new place: /close --auto passes over a task the scan marks
    auto_skip (a gap no dispatch record or todo step owes), saying why; the gate's --auto targets
    are that same function's, so the run's Stop does not hold the task it passed over. A task past
    the cut-off is no target and says nothing; /commit --auto still takes an auto_skip row."""
    lifecycle = _load(REPO / "scripts" / "dev-lifecycle.py", "lifecycle_under_test")
    why = "no dispatch record or todo step owes docs/dev/ticket-20261101-070000.md"
    rows = [{"task_id": "20261101-080000", "kind": "ticket", "next_action": "close"},
            {"task_id": "20261101-070000", "kind": "ticket", "next_action": "close", "auto_skip": why},
            {"task_id": "20261101-100000", "kind": "ticket", "next_action": "close", "auto_skip": why},
            {"task_id": "20261101-060000", "kind": "ticket", "next_action": "commit", "auto_skip": why}]
    cutoff = datetime(2026, 11, 1, 9, 0, 0).timestamp()
    skipped = []
    assert lifecycle.auto_targets(Path("."), "close", cutoff, rows, skipped) == ["20261101-080000"]
    assert skipped == [f"20261101-070000: skipped: {why}"]
    assert lifecycle.auto_targets(Path("."), "close", cutoff, rows) == ["20261101-080000"]
    assert lifecycle.auto_targets(Path("."), "commit", cutoff, rows) == ["20261101-060000"]


# Self-check finding: an --auto run's targets were dev-lifecycle's list at the Stop, which no longer
# lists a parent once its step is done (or has left it unlanded), so every run ended `no target task
# resolved`; one with nothing to do as well. These run dev-lifecycle's real scan over the project.
AUTO = "20261031-120000"  # minted before the opener in any time zone


def auto_task(env, command, outcome):
    """A /do parent as the real scan reads it, close_pending (/close) or commit_pending (/commit),
    then, after the --auto opener: `not walked`, or walked (the span's dispatch names it) and
    `landed` (CLOSE: YES; its Task-id commit) or `left unlanded` (CLOSE: NO; a commit with its
    owned file dirty again)."""
    dev = env.project / "docs" / "dev"
    (env.project / "owned.txt").write_text("cycle\n")
    (dev / f"do-report-{AUTO}.json").write_text(json.dumps({"task_id": AUTO, "source": "do", "do": {
        "status": "completed", "summary": "done", "files_modified": ["owned.txt"]}}))
    report = dev / f"close-report-{AUTO}.md"
    if command == "commit":
        report.write_text(f"# Close\nTask-id: {AUTO}\n\nCLOSE: YES\n")
    env.tx.command(command, "--auto")
    if command == "close":
        env.tx.todos(canonical("close", "--auto"), len(canonical("close", "--auto")))
    if outcome == "not walked":
        return
    env.tx.dispatch(AUTO, role="style-inspector" if command == "close" else "changelog-analyst", pipeline=command,
                    profile="singular" if command == "close" else "commit-landing")
    if command == "close":
        report.write_text(f"# Close\nTask-id: {AUTO}\n\n{'CLOSE: YES' if outcome == 'landed' else 'CLOSE: NO - x'}\n")
        return
    git(env.project, "add", "-A")
    git(env.project, "commit", "-q", "-m", f"the cycle\n\nTask-id: {AUTO}")
    if outcome == "left unlanded":
        (env.project / "owned.txt").write_text("changed after the commit\n")


@pytest.mark.parametrize("command", ["close", "commit"])
@pytest.mark.parametrize("outcome,code", [("landed", 0), ("left unlanded", 2), ("not walked", 2)])
def test_a8_auto_targets_the_parents_it_walked_and_those_still_listed(env, repo, monkeypatch, command, outcome, code):
    """Fake disposition (P3): it answers for the targets the gate names; the scan is the real one."""
    monkeypatch.setitem(sys.modules, "lib.close_rating", rating_fake(False))
    auto_task(env, command, outcome)
    listed = gate._script("scripts/dev-lifecycle.py").auto_targets(env.project, command)
    assert listed == ([AUTO] if outcome == "not walked" else [])
    if code:
        env.fake.answers[(AUTO, command)] = [gap(".", "NOT_LANDED", f"the {command} of {AUTO} has not landed")]
    got, text = run(env)
    assert got == code and (code == 0 or f"the {command} of {AUTO} has not landed" in text), text
    assert [c[1:3] for c in env.fake.calls] == [(AUTO, command)]


@pytest.mark.parametrize("command", ["close", "commit"])
def test_a8_an_auto_run_with_nothing_to_do_has_no_gap(env, monkeypatch, command):
    monkeypatch.setitem(sys.modules, "lib.close_rating", rating_fake(False))
    later = "20261102-120000"  # minted after the opener in any time zone: not this run's
    (env.project / "docs" / "dev" / f"do-report-{later}.json").write_text(json.dumps({
        "task_id": later, "source": "do", "do": {"status": "completed", "summary": "x", "files_modified": []}}))
    env.tx.command(command, "--auto")
    if command == "close":
        env.tx.todos(canonical("close", "--auto"), len(canonical("close", "--auto")))
    assert run(env) == (0, "") and env.fake.calls == []


@pytest.mark.parametrize("args", [f"docs/dev/ticket-{FAMILY}.md", f"docs/dev/do-report-{FAMILY}.json",
                                  f'--force --reason "hand edit" {FAMILY}', f"--codex dev-{FAMILY}"])
def test_a8_close_arguments_name_the_task_close_md_resolves(env, monkeypatch, args):
    """Self-check finding: the arguments were split on spaces and each word taken as a task id, so a
    path or a quoted --reason named no task; they are read as close.md's Task-id resolution reads them."""
    monkeypatch.setitem(sys.modules, "lib.close_rating", rating_fake(False))
    task_file(env)
    task_file(env, f"do-report-{FAMILY}.json")
    env.tx.command("close", args)
    env.tx.todos(canonical("close", args), len(canonical("close", args)))
    env.fake.answers[(FAMILY, "close")] = [gap(f"docs/dev/close-report-{FAMILY}.md", "MISSING_ARTIFACT", "absent")]
    code, text = run(env)
    assert code == 2 and f"close-report-{FAMILY}.md" in text
    env.fake.answers.clear()
    assert run(env) == (0, "")
    assert {c[1:3] for c in env.fake.calls} == {(FAMILY, "close")}


# P5 review M: the owner mistypes the /close argument and corrects it in the turn (close.md's
# Task-id resolution asks for it). OTHER: a task the span dispatched that is not the typed one.
TYPO, OTHER = "20261101-095959", "20261101-100000"


@pytest.mark.parametrize("args", [f"docs/dev/ticket-{TYPO}.md", TYPO, FAMILY[:-1]])
def test_m_a_typed_close_task_naming_no_task_yields_to_the_task_the_span_closed(env, monkeypatch, args):
    """P5 review M: a typed path that does not exist, an id no docs/dev file holds, or one a held id
    only begins with names no task. The Stop holds naming it until a dispatch of the span names a
    task; the owner's answer is no fact (D23). Then the families the span dispatched are the targets,
    and the typed id never is."""
    monkeypatch.setitem(sys.modules, "lib.close_rating", rating_fake(False))
    task_file(env)
    env.tx.command("close", args)
    env.tx.todos(canonical("close", args), len(canonical("close", args)))
    code, text = run(env)
    assert code == 2 and f"- close: {args} names no task or chain file, and no dispatch of this /close names a task\n" \
        in text, text
    env.tx.ask(FAMILY)
    assert run(env)[0] == 2 and env.fake.calls == []
    env.tx.dispatch(FAMILY, role="style-inspector", pipeline="close")
    env.fake.answers[(FAMILY, "close")] = [gap(f"docs/dev/close-report-{FAMILY}.md", "MISSING_ARTIFACT", "absent")]
    code, text = run(env)
    assert code == 2 and f"close-report-{FAMILY}.md" in text and "names no task" not in text, text
    env.fake.answers.clear()
    assert run(env) == (0, "")
    assert {c[1:3] for c in env.fake.calls} == {(FAMILY, "close")}


@pytest.mark.parametrize("args,held", [(f"docs/dev/ticket-{FAMILY}.md", f"ticket-{FAMILY}.md"),
                                      (FAMILY, f"do-report-{FAMILY}.json"), (FAMILY, f"dev-report-{FAMILY}-l1.json"),
                                      (f"{FAMILY} {TYPO}", f"ticket-{FAMILY}.md")])
def test_m_a_typed_close_task_naming_a_task_stays_the_target(env, monkeypatch, args, held):
    """P5 review M: a typed task that names a task or chain file (the path exists; a docs/dev file, the
    task's own or a lane's, holds the id) stays the target, whatever the span dispatched; beside one
    that names none, the families the span dispatched join it."""
    monkeypatch.setitem(sys.modules, "lib.close_rating", rating_fake(False))
    task_file(env, held)
    env.tx.command("close", args)
    env.tx.todos(canonical("close", args), len(canonical("close", args)))
    env.tx.ask(OTHER)
    env.tx.dispatch(OTHER, role="style-inspector", pipeline="close")
    env.fake.answers[(FAMILY, "close")] = [gap(f"docs/dev/close-report-{FAMILY}.md", "MISSING_ARTIFACT", "absent")]
    code, text = run(env)
    assert code == 2 and f"close-report-{FAMILY}.md" in text, text
    assert {c[1] for c in env.fake.calls} == ({FAMILY, OTHER} if TYPO in args else {FAMILY})


# P5-4 (finding M's /commit half): /commit takes its typed target through the rule /close takes since
# 4ca4260 (the gate's _targets): a typed id that names no task yields to the families the span dispatched.
def trailer_gap(task):
    return [gap(".", "MISSING_TASK_TRAILER", f"no commit reachable from HEAD carries Task-id: {task}")]


@pytest.mark.parametrize("args", [TYPO, f"docs/dev/ticket-{TYPO}.md", FAMILY[:-1], f"--codex {TYPO}"])
def test_p5_4_a_typed_commit_task_naming_no_task_yields_to_the_task_the_span_committed(env, args):
    """Fake disposition (P3): every task it is asked about lacks its Task-id commit until the case
    lands one. Before P5-4 the /commit Stop held on the typed id whatever the span committed, a hold
    no agent action clears (D25). Now it holds naming the typed value until a dispatch of the span
    names a task (the owner's answer is no fact, D23); then the families the span dispatched are the
    targets, held until their Task-id commit exists, and the typed id never is."""
    task_file(env)
    typed = args.split()[-1]
    task = TYPO if "/" in typed else typed
    env.fake.answers[(task, "commit")] = trailer_gap(task)
    env.fake.answers[(FAMILY, "commit")] = trailer_gap(FAMILY)
    env.tx.command("commit", args)
    code, text = run(env)
    assert code == 2 and text.splitlines()[1:2] == [
        f"- commit: {typed} names no task or chain file, and no dispatch of this /commit names a task"], text
    env.tx.ask(FAMILY)
    assert run(env)[0] == 2 and env.fake.calls == []
    env.tx.dispatch(FAMILY, role="changelog-analyst", pipeline="commit", profile="commit-landing")
    code, text = run(env)
    assert code == 2 and f"Task-id: {FAMILY}" in text and "names no task" not in text, text
    env.fake.answers[(FAMILY, "commit")] = []  # the landing commit
    assert run(env) == (0, "")
    assert {c[1:3] for c in env.fake.calls} == {(FAMILY, "commit")}


@pytest.mark.parametrize("args,held", [(FAMILY, f"ticket-{FAMILY}.md"),
                                      (f"dev-{FAMILY}", f"dev-report-{FAMILY}-l1.json"),
                                      (f"docs/dev/ticket-{FAMILY}.md", f"ticket-{FAMILY}.md"),
                                      (f"{FAMILY} {TYPO}", f"ticket-{FAMILY}.md")])
def test_p5_4_a_typed_commit_task_naming_a_task_stays_the_target(env, args, held):
    """A typed /commit task that names a task or chain file stays the target, whatever the span
    dispatched, held until its Task-id commit exists and then released; beside one that names
    none, the families the span dispatched join it (as /close's, 4ca4260)."""
    task_file(env, held)
    env.tx.command("commit", args)
    env.tx.ask(OTHER)
    env.tx.dispatch(OTHER, role="changelog-analyst", pipeline="commit", profile="commit-landing")
    env.fake.answers[(FAMILY, "commit")] = trailer_gap(FAMILY)
    code, text = run(env)
    assert code == 2 and f"Task-id: {FAMILY}" in text and "names no task" not in text, text
    assert {c[1] for c in env.fake.calls} == ({FAMILY, OTHER} if TYPO in args else {FAMILY})
    env.fake.answers.clear()
    assert run(env) == (0, "")


@pytest.mark.parametrize("mode", ["--dry-run", "--auto", "--bulk"])
def test_p5_4_commit_modes_keep_their_verdicts_beside_a_mistyped_id(env, monkeypatch, mode):
    """--dry-run asks nothing of the chain; --auto takes dev-lifecycle's target function's parents,
    never a typed word; --bulk reads its status block: a mistyped id typed beside them changes none."""
    lifecycle = types.SimpleNamespace(auto_targets=lambda root, action, cutoff: [FAMILY])
    monkeypatch.setitem(gate._SCRIPTS, "scripts/dev-lifecycle.py", lifecycle)
    env.fake.answers[(FAMILY, "commit")] = trailer_gap(FAMILY)
    env.fake.answers[(TYPO, "commit")] = trailer_gap(TYPO)
    env.tx.command("commit", f"{mode} {TYPO}")
    code, text = run(env)
    if mode == "--dry-run":
        assert (code, text) == (0, "") and env.fake.calls == []
    elif mode == "--bulk":
        assert code == 2 and "no changelog-analyst status block" in text and env.fake.calls == []
    else:
        assert code == 2 and f"Task-id: {FAMILY}" in text and TYPO not in text, text
        env.fake.answers.clear()
        assert run(env) == (0, "") and {c[1] for c in env.fake.calls} == {FAMILY}


# ---------------------------------------------------------------- A11: modes
def test_a11_advisory_reports_would_block_and_allows(env):
    dev_span(env, done=1)
    code, text = run(env, "advisory")
    assert code == 0 and text.startswith("would block\nCOMMAND_GATE /dev: not complete\n")


def test_a11_off_allows_everything_and_mode_parsing(env, monkeypatch):
    dev_span(env, done=1)
    real_overnight(env, monkeypatch, hours=1)  # the window open (P2's window_open, real)
    assert run(env)[0] == 2
    assert run(env, "off") == (0, "")
    assert [gate._mode(a) for a in (["--mode", "off"], ["--mode=advisory"], [], ["--mode", "bogus"])] == [
        "off", "advisory", "block", "block"]


def test_a11_todo_tools_disabled_is_one_gap(env, monkeypatch):
    dev_span(env, done=1)
    monkeypatch.delenv("CLAUDE_CODE_ENABLE_TODO_TOOLS")
    code, text = run(env)
    assert code == 2 and "- todo tools disabled (CLAUDE_CODE_ENABLE_TODO_TOOLS)\n" in text
    assert "todo: not completed" not in text


def test_a21_a_span_an_older_harness_opened_keeps_the_list_it_started_with(env):
    """A /dev-overnight span opened before the landing holds the canonical list of its time (22 steps,
    no Step 0 wake) and is resumed under this tree's settings: its completed list is no gap. A list
    that is neither that one nor today's canonical still differs."""
    steps = canonical("dev")
    older = steps[1:]  # the canonical list before a step was added to it
    env.tx.command("dev", "fix the build", context=f"Task id: {FAMILY}\n")
    env.tx.todos(older, 0)
    env.tx.todos(older, len(older))
    assert gate.todo_gaps(command_span.active_span(env.tx.path)) == []
    env.tx.todos(older[1:], len(older) - 1)
    assert gate.todo_gaps(command_span.active_span(env.tx.path)) == [
        f"todo: checklist differs from the canonical {len(steps)} steps"]


@pytest.mark.parametrize("command", ["commit", "merge", "push"])
def test_todo_half_without_a_canonical_list_needs_the_last_list_completed(env, command):
    env.fake.answers.clear()
    env.tx.command(command, FAMILY if command == "commit" else "")
    env.tx.tool("TodoWrite", {"todos": [{"content": "a", "activeForm": "a", "status": "completed"},
                                        {"content": "b", "activeForm": "b", "status": "pending"}]})
    assert "todo: not completed: b" in gate.todo_gaps(command_span.active_span(env.tx.path))[0]


# ---------------------------------------------------------------- instrument failures (step 6)
def test_an_absent_producer_function_is_an_instrument_failure_never_an_allow(env, monkeypatch):
    monkeypatch.delattr(resolver, "disposition")  # P3's function absent from the chain's module
    steps = dev_span(env, done=0)
    env.tx.todos(steps, len(steps))
    code, text = run(env)
    assert code == 2 and "- gate instrument failure: NameError: name 'disposition' is not defined" in text


def test_an_unloadable_close_rating_is_an_instrument_failure(env, monkeypatch):
    monkeypatch.setitem(sys.modules, "lib.close_rating", None)  # P4 absent: the import fails
    task_file(env)
    env.tx.command("close", FAMILY)
    code, text = run(env)
    assert code == 2 and "gate instrument failure: ModuleNotFoundError" in text


# ---------------------------------------------------------------- A12: the overnight time-lock (P2, real)
def test_a12_an_open_window_blocks_any_span_in_any_mode_but_off(env, monkeypatch):
    """P2's window_open on the session's record (end_time an hour ahead, no human /stop since
    the /dev-overnight): any span, block or advisory, is held, naming the end time and the
    time left; off allows, and so does the Codex runtime."""
    end = real_overnight(env, monkeypatch, hours=1)
    env.tx.command("dev-overnight", "--hours 1")
    env.tx.command("spec")
    for mode in ("block", "advisory"):
        assert run(env, mode) == (2, f"COMMAND_GATE time-lock: overnight window open until {end}, 0h 59m left;"
                                     " continue the remaining pipelines\n")
    assert run(env, "off") == (0, "")
    monkeypatch.setenv("CLAUDE_COMPAT_RUNTIME", "codex")
    assert run(env) == (0, "")
    monkeypatch.delenv("CLAUDE_COMPAT_RUNTIME")
    env.tx.command("stop")  # the human's /stop closes the window
    assert run(env) == (0, "")


def overnight_session(env, wake=True, prompt=None):
    env.tx.command("dev-overnight", "--hours 1")
    if wake:
        env.tx.tool("CronCreate", {"cron": "*/30 * * * *", "prompt": prompt or REAL_OVERNIGHT.WAKE_PROMPT,
                                   "recurring": True},
                    extra={"toolUseResult": {"id": "cron-7", "recurring": True}})


def test_a12_a_time_lock_it_cannot_read_blocks_any_span_in_any_mode_until_the_humans_stop(env, monkeypatch):
    """Self-check finding: an exception in the time-lock (P2's window_open absent) was an allow in an
    ungated span and in advisory mode; it holds as an open window does, until the human's /stop."""
    fake = overnight_fake({"session_id": SID, "end_time": "2026-11-01T10:00:00Z"})
    del fake.window_open
    monkeypatch.setitem(sys.modules, "lib.overnight", fake)
    overnight_session(env, wake=False)
    env.tx.command("spec")
    for mode in ("block", "advisory"):
        code, text = run(env, mode)
        assert code == 2 and "time-lock: gate instrument failure: AttributeError" in text and "/stop" in text
    env.tx.command("stop")
    assert run(env) == (0, "")


def test_a12_after_the_window_a_live_wake_blocks_naming_its_id_until_deleted(env, monkeypatch):
    """P2's window_open, real: the human's /stop closes the window before end_time, and the
    wake check holds the Stop while the wake is live."""
    real_overnight(env, monkeypatch, hours=1, worktree_path=str(env.project))
    overnight_session(env)
    env.tx.command("stop")
    code, text = run(env)
    assert code == 2 and "cron-7" in text and "AskUserQuestion" not in text
    env.tx.tool("CronDelete", {"id": "cron-7"})
    assert gate.decision(env.payload) == (0, "", "cancelled_by_user")


def test_a12_only_the_wakes_cron_create_is_the_wake(env, monkeypatch):
    """The wake check reads overnight.open_wakes (a CronCreate of WAKE_PROMPT, P1c X8): another
    recurring job the session scheduled is no wake, and a wake created before the latest
    /dev-overnight opener still counts. P2's window_open, real."""
    real_overnight(env, monkeypatch, hours=1, worktree_path=str(env.project))
    overnight_session(env, prompt="check the deploy")
    env.tx.command("stop")
    assert gate.decision(env.payload) == (0, "", "cancelled_by_user")
    env.tx.tool("CronCreate", {"cron": "3 * * * *", "prompt": REAL_OVERNIGHT.WAKE_PROMPT, "recurring": True},
                extra={"toolUseResult": {"id": "cron-9", "recurring": True}})
    env.tx.command("dev-overnight", "--hours 1")
    env.tx.command("stop")
    code, text = run(env)
    assert code == 2 and "cron-9" in text and "cron-7" not in text


def test_a12_after_end_time_the_families_and_closeout_decide(env, monkeypatch):
    """P2's locator, window and closeout_gaps, real (the record's end_time past, its working
    root tmp/wt); P3's disposition faked; on the real one:
    test_a12_real_after_end_time_the_families_chain_at_the_working_root_and_the_closeout_decide."""
    (env.tmp / "wt" / "docs" / "dev").mkdir(parents=True)
    real_overnight(env, monkeypatch, hours=-1, worktree_path=str(env.tmp / "wt"))
    overnight_session(env, wake=False)
    env.tx.todos(canonical("dev-overnight", "--hours 1"), len(canonical("dev-overnight", "--hours 1")))
    env.tx.dispatch(f"{FAMILY}-1", pipeline="dev-overnight")
    env.fake.answers[(f"{FAMILY}-1", "dev")] = [gap("docs/dev/producer-question-x-ba.json", "unanswered", "open")]
    code, text = run(env)
    assert code == 2 and "unanswered" in text and "no PM retrospective" in text
    assert "AskUserQuestion" not in text and "record the decision" in text
    assert env.fake.calls[-1][0] == str(env.tmp / "wt")
    assert "overnight-summary-*.md: no summary written since start_time" in text
    env.fake.answers.clear()
    closeout_on_disk(env.tmp / "wt")
    assert gate.decision(env.payload) == (0, "", "completed_by_deadline")


def test_a12_after_end_time_the_closeout_is_read_from_disk_and_named_by_path(env, monkeypatch):
    """Moved from test_laneb_stop_overnight_timelock_scoping.py (P1c, P2 R7; the time-lock is a stub):
    after end_time the /dev-overnight Stop is refused until Step 21's summary is on disk, naming it by
    path. Self-declared state fields (final_summary_path, pm_retro_reports,
    artifact_checkpoint_status) release nothing, a summary older than start_time is not this
    session's, and an empty one is no summary; the summary alone still leaves Step 20's PM
    retrospective named. P2's locator and closeout_gaps, real."""
    wt = env.tmp / "wt"
    (wt / "docs" / "dev").mkdir(parents=True)
    start = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    real_overnight(env, monkeypatch, hours=-1, start_time=start, worktree_path=str(wt),
                   final_summary_path=str(wt), pm_retro_reports=["retro-1"],
                   artifact_checkpoint_status="checkpointed")
    overnight_session(env, wake=False)
    env.tx.todos(canonical("dev-overnight", "--hours 1"), len(canonical("dev-overnight", "--hours 1")))
    old = wt / "docs" / "dev" / "overnight-summary-2020-01-01.md"
    old.write_text("an earlier session's")
    os.utime(old, (0, 0))
    code, text = run(env)
    assert code == 2 and text.startswith("COMMAND_GATE /dev-overnight: not complete\n")
    assert f"{wt}/docs/dev/overnight-summary-*.md: no summary written since start_time {start}" in text
    assert f"{wt}/docs/dev/overnight/{SID}/retro-report-cycle*.json: no PM retrospective report" in text
    (wt / "docs" / "dev" / "overnight-summary-2026-01-02.md").write_text("")
    code, text = run(env)
    assert code == 2 and "overnight-summary-*.md: no summary written since start_time" in text
    (wt / "docs" / "dev" / "overnight-summary-2026-01-03.md").write_text("# Overnight Development Summary\n")
    code, text = run(env)
    assert code == 2 and "retro-report-cycle*.json" in text and "overnight-summary-*.md" not in text
    closeout_on_disk(wt)
    assert gate.decision(env.payload) == (0, "", "completed_by_deadline")


def test_a12_no_terminal_status_without_an_overnight_record_or_with_an_open_closeout(env, monkeypatch):
    """P2's locator and closeout_gaps, real: no record, or a record past end_time whose
    closeout is not on disk, gives no terminal status."""
    real_overnight(env, monkeypatch)
    env.tx.command("spec")
    assert gate.decision(env.payload) == (0, "", None)
    real_overnight(env, monkeypatch, hours=-1)
    assert gate.decision(env.payload) == (0, "", None)
    closeout_on_disk(env.project)
    assert gate.decision(env.payload) == (0, "", "completed_by_deadline")


# ---------------------------------------------------------------- the time-lock's state selection
# Moved from test_laneb_stop_overnight_timelock_scoping.py (P5 R11): the time-lock selects only
# the session's own record, the one P2's overnight.locate reads through session_state_file.
def _state(root: Path, name: str, **fields) -> None:
    (root / ".claude").mkdir(parents=True, exist_ok=True)
    (root / ".claude" / f"overnight-state-{name}.json").write_text(json.dumps(fields))


def test_the_locator_selects_only_the_sessions_own_record(tmp_path):
    _state(tmp_path, "session-a", session_id="session-a", end_time="2099-01-01T00:00:00")
    _state(tmp_path, "session-other", session_id="session-other")
    _state(tmp_path, "session-c", session_id="session-d")  # its own session_id disagrees with its name
    assert REAL_OVERNIGHT.session_state_file("session-a", (str(tmp_path),))[1]["session_id"] == "session-a"
    assert REAL_OVERNIGHT.session_state_file("session-mine", (str(tmp_path),)) == (None, None)
    assert REAL_OVERNIGHT.session_state_file("session-c", (str(tmp_path),)) == (None, None)
    assert REAL_OVERNIGHT.session_state_file("", (str(tmp_path),)) == (None, None)


# ---------------------------------------------------------------- R10: the reader's module
def test_r10_command_span_imports_no_harness_module():
    tree = ast.parse((HOOKS / "lib" / "command_span.py").read_text(encoding="utf-8"))
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    names = {a.name.split(".")[0] for n in top if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module.split(".")[0] for n in top if isinstance(n, ast.ImportFrom) and n.module}
    assert not any(n.level for n in top if isinstance(n, ast.ImportFrom))
    assert names <= set(sys.stdlib_module_names) | {"__future__"}


def test_r10_command_span_loads_beside_a_broken_stop_contract(tmp_path):
    lib = tmp_path / "hooks" / "lib"
    lib.mkdir(parents=True)
    for name in ("command_span.py", "stop-commands.json"):
        (lib / name).write_bytes((HOOKS / "lib" / name).read_bytes())
    (lib / "stop_contract.py").write_text("def broken(:\n")
    probe = f"import sys; sys.path.insert(0, {str(lib)!r}); import command_span; print(command_span.GATED_COMMANDS)"
    done = subprocess.run([sys.executable, "-I", "-c", probe], capture_output=True, text=True)
    assert done.returncode == 0 and "dev-overnight" in done.stdout, done.stderr


def test_r10_stop_contract_re_exports_the_readers_rule_and_sets():
    from hooks.lib import command_span as reader, stop_contract
    sets = json.loads((HOOKS / "lib" / "stop-commands.json").read_text())
    assert stop_contract.GATED_COMMANDS == tuple(sets["GATED_COMMANDS"]) == reader.GATED_COMMANDS
    assert stop_contract.CONTROL_COMMANDS == tuple(sets["CONTROL_COMMANDS"]) == reader.CONTROL_COMMANDS
    for name in ("prompt_text", "slash_command", "span_opener", "is_human_prompt", "active_command",
                 "timelock_released", "harness_commands"):
        assert getattr(stop_contract, name) is getattr(reader, name), name


def test_r10_timelock_released_reads_the_humans_stop_after_dev_overnight(env):
    overnight_session(env, wake=False)
    assert command_span.timelock_released(env.tx.path) is False
    env.tx.command("spec")
    assert command_span.timelock_released(env.tx.path) is False
    env.tx.command("stop")
    assert command_span.timelock_released(env.tx.path) is True
    env.tx.add({"type": "user", "isMeta": True, "message": {"role": "user", "content": "/dev-overnight"}})
    assert command_span.timelock_released(env.tx.path) is True


def test_the_gate_runs_as_a_script(env):
    env.tx.command("spec")
    done = subprocess.run([sys.executable, str(HOOKS / "stop-command-gate.py"), "--mode", "block"],
                          input=json.dumps({**env.payload, "agent_id": "x"}), capture_output=True, text=True)
    assert (done.returncode, done.stderr, done.stdout) == (0, "", "")


# ---------------------------------------------------------------- P3's disposition and P4's close rating, real
# P3 and P4 are merged: the A3, A6 (/commit) and A8 (close rating) cases above, which fake them, run
# again on the real chain module (P3's disposition and gap_line through disposition_lines) and P4's
# close-rating library, on the artifacts the chain reads from disk.
REAL_CHAIN = {name: getattr(resolver, name) for name in ("disposition", "gap_line")}


@pytest.fixture
def real(env, monkeypatch):
    """env with P3's disposition and gap_line, real; P4's close rating is the real module unless a
    case fakes it."""
    for name, function in REAL_CHAIN.items():
        monkeypatch.setattr(resolver, name, function)
    return env


def chain_on_disk(root, qa="pass", verdict="pass", close=None, task=FAMILY):
    """The /dev chain P3's disposition reads, in production order (each file newer than the one
    before): ticket, context, BA-QA verdict, dev report, QA report, and with ``close`` a close-report
    ending in that line."""
    dev = Path(root) / "docs" / "dev"
    (Path(root) / "scripts").mkdir(exist_ok=True)
    (Path(root) / "scripts" / "one.py").write_text("one = 1\n")
    rows = [(f"ticket-{task}.md", f"# Ticket\n\n**TASK-ID**: `{task}`\n"),
            (f"context-{task}.json", {"request_id": task, "task_id": task}),
            (f"ba-qa-report-{task}.json", {"task_id": task, "verdict": verdict, "objections": [], "summary": "s"}),
            (f"dev-report-{task}.json", {
                "request_id": task, "task_id": task, "baseline_head_sha": "0123456789abcdef",
                "baseline_dirty_snapshot": "", "blocking_issues": [], "recommendations": [],
                "dev": {"status": "completed", "tasks_completed": ["t"], "scripts_created": [],
                        "permissions_to_add": [], "files_modified": ["scripts/one.py"], "files_created": [],
                        "observed_preexisting": []}}),
            (f"qa-report-{task}.json", {"request_id": task, "task_id": task, "qa": {"status": qa}})]
    rows += [(f"close-report-{task}.md", f"# Close\n\n{close}\n")] if close else []
    clock = datetime.now().timestamp() - 100_000
    for name, value in rows:
        path = dev / name
        path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
        clock += 10
        os.utime(path, (clock, clock))


@pytest.mark.parametrize("qa,verdict,problem", [
    ("fail", "pass", "INVALID_QA_STATUS: qa.status is 'fail'"),
    ("warning", "pass", "INVALID_QA_STATUS: qa.status is 'warning'"),
    ("pass", "fail", "INVALID_BA_QA_VERDICT: verdict is 'fail'"), ("pass", "pass", None)])
def test_a3_real_a_complete_checklist_still_needs_p3s_chain_pass(real, qa, verdict, problem):
    """test_a3_a_complete_checklist_still_needs_chain_pass on P3's real disposition: a QA fail or
    warning and a BA-QA fail are each one gap naming the artifact and the failing check."""
    steps = dev_span(real, done=0)
    real.tx.todos(steps, len(steps))
    chain_on_disk(real.project, qa=qa, verdict=verdict)
    code, text = run(real)
    if problem is None:
        assert (code, text) == (0, "")
    else:
        assert code == 2 and text.startswith("COMMAND_GATE /dev: not complete\n"), text
        assert f"problem={problem}" in text and "owner" not in text, text


def test_a6_real_commit_needs_p3s_task_id_commit_reachable_from_head(real, repo):
    """test_a6_commit_modes_only_if_typed on P3's real --stage commit: a closed chain whose task has
    no Task-id commit reachable from HEAD holds the /commit Stop, naming the repository; the landing
    commit releases it; --dry-run asks nothing of the chain."""
    chain_on_disk(repo, close="CLOSE: YES")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "cycle artifacts")
    real.tx.command("commit", FAMILY)
    code, text = run(real)
    assert code == 2 and "problem=MISSING_TASK_TRAILER" in text, text
    (repo / "scripts" / "one.py").write_text("landed = True\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"land the change\n\nTask-id: {FAMILY}")
    assert run(real) == (0, "")
    real.tx.command("commit", "--dry-run")
    assert run(real) == (0, "")


def test_p5_4_real_a_mistyped_commit_is_released_by_the_landing_of_the_task_the_span_committed(real, repo):
    """test_p5_4_a_typed_commit_task_naming_no_task_yields_to_the_task_the_span_committed on P3's real
    --stage commit: before P5-4 the mistyped id stayed the target, and P3 held it (no chain, no
    Task-id commit) after the corrected task landed."""
    chain_on_disk(repo, close="CLOSE: YES")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "cycle artifacts")
    real.tx.command("commit", TYPO)
    code, text = run(real)
    assert code == 2 and text.splitlines()[1] == (
        f"- commit: {TYPO} names no task or chain file, and no dispatch of this /commit names a task"), text
    real.tx.ask(FAMILY)
    real.tx.dispatch(FAMILY, role="changelog-analyst", pipeline="commit", profile="commit-landing")
    code, text = run(real)
    assert code == 2 and "problem=MISSING_TASK_TRAILER" in text and TYPO not in text, text
    (repo / "scripts" / "one.py").write_text("landed = True\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"land the change\n\nTask-id: {FAMILY}")
    assert run(real) == (0, "")


@pytest.mark.parametrize("qa_line,asked,code", [
    ("CLOSE: YES", False, 2), ("CLOSE: YES", True, 0), ("CLOSE: NO", False, 0)],
    ids=["landed-not-asked", "landed-asked", "not-landed"])
def test_a8_real_close_needs_p4s_rating_question_after_the_landed_close_qa(real, qa_line, asked, code):
    """test_a8_close_needs_the_rating_question_asked_where_required on P4's real close rating and P3's
    real --stage close: the rating is required once the span's close QA landed the task, and asked
    when the main agent's AskUserQuestion with source close-rating:<task> follows that result."""
    chain_on_disk(real.project, close="CLOSE: YES")
    real.tx.command("close", FAMILY)
    real.tx.todos(canonical("close", FAMILY), len(canonical("close", FAMILY)))
    real.tx.dispatch(FAMILY, role="qa", pipeline="close", result=f"Judged.\n{qa_line}")
    if asked:
        real.tx.tool("AskUserQuestion", {"questions": [{"question": "How well?", "header": "Rating",
                                                        "options": [{"label": "5 - Fully met"}]}],
                                         "metadata": {"source": f"close-rating:{FAMILY}"}}, result="Skip")
    got, text = run(real)
    assert got == code and (code == 0 and text == "" or "close-rating question" in text), text


# ---------------------------------------------------------------- D15: an in-flight command, held to the text it loaded
# origin/master before the trains (P8's merge): the text a session of the owner's live home loaded
MASTER = "2acc29b0c8149c32d8e424e58c6af55d073eac20"


def loaded_text(command: str, args: str, rev: str | None = None) -> str:
    """commands/<command>.md as the CLI records it for a typed /<command> <args> (frontmatter left out,
    $ARGUMENTS filled), from this tree or from commit ``rev``."""
    text = (subprocess.run(["git", "-C", str(REPO), "show", f"{rev}:commands/{command}.md"], capture_output=True,
                           text=True, check=True).stdout if rev else (REPO / "commands" / f"{command}.md").read_text())
    if text.startswith("---\n"):
        text = text[text.index("\n---\n", 4) + 5:]
    if "$ARGUMENTS" in text:
        return text.replace("$ARGUMENTS", args)
    return text + (f"\n\nARGUMENTS: {args}" if args else "")


@pytest.mark.parametrize("done", [3, 4], ids=["paced-by-its-three-steps", "steps-0-to-3"])
@pytest.mark.parametrize("loaded", ["master", "this tree", "unrecorded"])
def test_d15_real_an_in_flight_close_is_held_to_the_close_md_it_loaded(real, loaded, done):
    """A /close the session took up from master's close.md before the landing (A17's in-flight close:
    master's text, this tree's hooks, which hand it this tree's five-step list) and whose close QA
    landed. Its text words Steps 1 and 2 as this tree's does, Step 0 and Step 3 otherwise, has no Step
    3b and asks no rating question: following its three TodoSteps it completes Steps 0-2 of this list
    (one completion per step of its text), or 0-3, and neither Step 3, Step 3b nor the rating is asked
    of it. The same span on this tree's own close.md, or with no recorded text, is held exactly as
    before: every open step and the rating question."""
    chain_on_disk(real.project, close="CLOSE: YES")
    body = {"master": lambda: loaded_text("close", FAMILY, MASTER), "this tree": lambda: loaded_text("close", FAMILY),
            "unrecorded": lambda: None}[loaded]()
    assert body is None or ("### Step 1: Agent dispatch" in body and "### Step 2: Delegate close debate" in body)
    real.tx.command("close", FAMILY, body=body)
    steps = canonical("close", FAMILY)
    assert [s["content"].split(":")[0] for s in steps] == ["Step 0", "Step 1", "Step 2", "Step 3", "Step 3b"]
    real.tx.todos(steps, done)
    real.tx.dispatch(FAMILY, role="qa", pipeline="close", result="Judged.\nCLOSE: YES")
    got, text = run(real)
    if loaded == "master":
        assert (got, text) == (0, "")
    else:
        assert got == 2, text
        assert text.splitlines()[1:-1] == [f"- todo: not completed: {s['content']}" for s in steps[done:]] + [
            f"- close {FAMILY}: the close-rating question (AskUserQuestion) was not asked"], text


@pytest.mark.parametrize("done", [1, 2])
def test_d15_real_an_in_flight_close_keeps_every_step_its_text_has(real, done):
    """Master's close.md words Steps 1 and 2 as this tree's does: each of them left open still holds
    the in-flight /close, and only they are named (Steps 3 and 3b, which its text words otherwise or
    not at all, are not asked)."""
    chain_on_disk(real.project, close="CLOSE: YES")
    real.tx.command("close", FAMILY, body=loaded_text("close", FAMILY, MASTER))
    steps = canonical("close", FAMILY)
    real.tx.todos(steps, done)
    code, text = run(real)
    assert code == 2 and text.splitlines()[1:-1] == [f"- todo: not completed: {s['content']}"
                                                     for s in steps[done:3]], text


@pytest.mark.parametrize("command,args", [("close", FAMILY), ("dev", "fix the build"), ("redev", FAMILY),
                                          ("dev-command", "fix the build"), ("do", "fix the build"),
                                          ("dev-overnight", "--hours 1"), ("spec", "a feature")])
def test_d15_a_span_on_this_trees_own_text_is_asked_every_step(env, command, args):
    """The loaded text is this tree's own: no canonical step is left out, whatever its text names
    (/spec's `### Step 1: Parse $ARGUMENTS` too, read with the arguments the CLI filled in)."""
    env.tx.command(command, args, body=loaded_text(command, args))
    steps = canonical(command, args)
    env.tx.todos(steps, 0)
    assert gate.todo_gaps(command_span.active_span(env.tx.path)) == [
        f"todo: not completed: {step['content']}" for step in steps]


def test_d15_the_rating_source_is_close_ratings_and_this_trees_close_md_asks_it():
    close_rating = importlib.import_module("lib.close_rating")
    assert close_rating.SOURCE_RE.fullmatch(f"{gate.RATING_SOURCE}{FAMILY}")
    assert f'"source": "{gate.RATING_SOURCE}<task-id>"' in (REPO / "commands" / "close.md").read_text()


# ---------------------------------------------------------------- A17: an in-flight cycle, asked as its text names and writes it
# P1b acceptance 17 (the live landing): a session that loaded origin/master's text runs its /dev cycle, /close and
# /commit on this tree's hooks. Master's /dev names the cycle's files with DEV_SESSION_ID (dev-<ts>) and its
# /dev-command with the bare <ts>; neither template writes a Ticket line, and master's /dev-command writes
# `**Request ID**: dev-<timestamp>` (the gate's COMPATIBILITY block).
def completion_on_disk(root, task: str, identity: tuple = ("Request ID", "Task ID"), name: str | None = None,
                       ticket: bool = True, qa: bool = True):
    """docs/dev/completion-<task>.md as a completion template writes it: one metadata line per ``identity``
    key naming ``name`` (default the task), and the single-lane Files Generated list, with or without its
    Ticket and QA Report lines."""
    refs = ([f"- Ticket: `docs/dev/ticket-{task}.md`"] if ticket else []) + [
        f"- Context: `docs/dev/context-{task}.json`", f"- Dev Report: `docs/dev/dev-report-{task}.json`"] + (
        [f"- QA Report: `docs/dev/qa-report-{task}.json`"] if qa else [])
    (Path(root) / "docs" / "dev" / f"completion-{task}.md").write_text(
        "# Development Completion Report\n\n" + "".join(f"**{key}**: {name or task}\n" for key in identity)
        + "\n## Files Generated\n\n" + "\n".join(refs) + "\n", encoding="utf-8")


def cycle_span(env, command: str, rev: str | None, name: str, minted: str = DEV_ID, args: str = "fix the build"):
    """A /dev-family span on commands/<command>.md of ``rev`` (None: this tree's), with the hook's start lines,
    every canonical step ticked, and its BA, QA and dev dispatches naming the cycle ``name``."""
    steps = canonical(command)
    env.tx.command(command, args, context=f"DEV_SESSION_ID pre-initialized by hook: {minted}\nTask id: {FAMILY}\n",
                   body=loaded_text(command, args, rev))
    env.tx.todos(steps, len(steps))
    for role in ("ba", "qa", "dev"):
        env.tx.dispatch(name, role=role)


@pytest.mark.parametrize("command,minted,name,identity", [
    ("dev", DEV_ID, DEV_ID, ("Request ID", "Task ID")),
    ("dev-command", f"dev-command-{FAMILY}", FAMILY, ("Request ID",))], ids=["dev", "dev-command"])
def test_a17_real_an_in_flight_cycle_meets_no_gap_its_text_never_produces(real, command, minted, name, identity):
    """master's /dev names its files dev-<ts> and its /dev-command the bare <ts>; each writes its completion
    from its template, with no Ticket line, master's /dev-command with `**Request ID**: dev-<ts>`. Its Stop
    is asked the chain under the name its dispatches carry and not the completion identity or reference
    that template never writes: allowed (P1b A17's in-flight /dev and /dev-command Stops)."""
    chain_on_disk(real.project, task=name)
    completion_on_disk(real.project, name, identity, name=f"dev-{FAMILY}", ticket=False)
    cycle_span(real, command, MASTER, name, minted)
    assert run(real) == (0, "")


def test_a17_real_an_in_flight_redev_runs_the_dev_text_its_conversation_holds(real):
    """(a) of the live landing: /redev after a /dev, both typed on master's text; the /redev cycle runs that
    /dev text (its own text only says so), so it is asked under its own dev-<ts> name."""
    old = "20261101-080000"
    chain_on_disk(real.project, task=f"dev-{old}")
    cycle_span(real, "dev", MASTER, f"dev-{old}", f"dev-{old}")
    chain_on_disk(real.project, task=DEV_ID)
    completion_on_disk(real.project, DEV_ID, ticket=False)
    cycle_span(real, "redev", MASTER, DEV_ID)
    assert run(real) == (0, "")


def test_a17_real_an_in_flight_cycle_is_held_for_a_report_its_text_names(real):
    """The in-flight cycle is asked the whole chain under its own name: its own dev report missing (or its QA
    report failing) still holds its Stop, naming dev-report-dev-<ts>.json."""
    chain_on_disk(real.project, task=DEV_ID)
    (real.project / "docs" / "dev" / f"dev-report-{DEV_ID}.json").unlink()
    cycle_span(real, "dev", MASTER, DEV_ID)
    code, text = run(real)
    assert code == 2 and f"GAP artifact=docs/dev/dev-report-{DEV_ID}.json problem=MISSING_ARTIFACT" in text, text
    chain_on_disk(real.project, task=DEV_ID, qa="fail")
    code, text = run(real)
    assert code == 2 and f"artifact=docs/dev/qa-report-{DEV_ID}.json problem=INVALID_QA_STATUS" in text, text


@pytest.mark.parametrize("rev,name,missing,held", [
    (MASTER, DEV_ID, "ticket", False), (MASTER, DEV_ID, "qa-report", True), ("722ffdf", FAMILY, "ticket", True)],
    ids=["master-ticket", "master-qa-report", "train-1-ticket"])
def test_a17_real_an_in_flight_completion_is_asked_each_reference_its_template_writes(real, rev, name, missing, held):
    """An in-flight completion is excused only what its own template never writes: master's names no
    ticket, but names the QA report, and train 1's (722ffdf, a text differing from this tree's in other
    words) names the ticket as this tree's does: a completion missing either still holds the Stop."""
    chain_on_disk(real.project, task=name)
    completion_on_disk(real.project, name, ticket=missing != "ticket", qa=missing != "qa-report")
    cycle_span(real, "dev", rev, name)
    code, text = run(real)
    gap_line = (f"- GAP artifact=docs/dev/completion-{name}.md problem=MISSING_COMPLETION_REFERENCE: completion "
                f"does not reference docs/dev/{missing}-{name}.{'md' if missing == 'ticket' else 'json'} lane=-")
    assert (code, text.splitlines()[1:-1]) == ((2, [gap_line]) if held else (0, [])), text


@pytest.mark.parametrize("named", [FAMILY, DEV_ID], ids=["named-task-id", "named-dev-session-id"])
def test_a17_real_a_cycle_on_this_trees_text_missing_its_dev_report_is_held_as_before(real, named):
    """This tree's /dev names a cycle's artifacts with its Task id: on that text the cycle is asked under the
    canonical id whatever its dispatches carry. Its dev report missing holds the Stop, as before, and so
    does a cycle that named its files dev-<ts> against that text."""
    chain_on_disk(real.project, task=named)
    completion_on_disk(real.project, named)
    (real.project / "docs" / "dev" / f"dev-report-{named}.json").unlink(missing_ok=named == DEV_ID)
    cycle_span(real, "dev", None, named)
    code, text = run(real)
    assert code == 2 and f"GAP artifact=docs/dev/dev-report-{FAMILY}.json problem=MISSING_ARTIFACT" in text, text


@pytest.mark.parametrize("command,identity", [("dev", ("Request ID", "Task ID")), ("dev-command", ("Request ID",))])
def test_a17_real_a_cycle_on_this_trees_text_is_held_for_its_completion_as_before(real, command, identity):
    """On this tree's text, whose template writes the Ticket line and `**Request ID**: <timestamp>`, a
    completion without them still holds the /dev-family Stop: the reference and the identity gaps."""
    chain_on_disk(real.project)
    completion_on_disk(real.project, FAMILY, identity, name=f"dev-{FAMILY}", ticket=False)
    cycle_span(real, command, None, FAMILY, DEV_ID if command == "dev" else f"dev-command-{FAMILY}")
    code, text = run(real)
    completion = f"docs/dev/completion-{FAMILY}.md"
    assert code == 2, text
    assert f"GAP artifact={completion} problem=MISSING_COMPLETION_REFERENCE: completion does not reference " \
           f"docs/dev/ticket-{FAMILY}.md" in text, text
    assert f"GAP artifact={completion} problem=IDENTITY_MISMATCH" in text, text


def test_a17_real_an_in_flight_close_and_commit_take_the_cycles_own_name(real, repo):
    """/close dev-<ts> and /commit dev-<ts> after master's /dev, typed on master's text: the close report
    master's /close writes (close-report-dev-<ts>.md) and the Task-id line its commit carries (dev-<ts>) are
    the chain's under that name. /close still asks the completion's references (master's Step 0 routes
    them: the /close Stop holds until the completion names its ticket), and a /commit with no such commit
    is still held, naming it."""
    chain_on_disk(repo, task=DEV_ID, close="CLOSE: YES")
    completion_on_disk(repo, DEV_ID, ticket=False)
    cycle_span(real, "dev", MASTER, DEV_ID)
    real.tx.command("close", DEV_ID, body=loaded_text("close", DEV_ID, MASTER))
    real.tx.todos(canonical("close", DEV_ID), len(canonical("close", DEV_ID)))
    real.tx.dispatch(DEV_ID, role="qa", pipeline="close", result="Judged.\nCLOSE: YES")
    code, text = run(real)
    assert code == 2 and text.splitlines()[1] == (
        f"- GAP artifact=docs/dev/completion-{DEV_ID}.md problem=MISSING_COMPLETION_REFERENCE: completion does not "
        f"reference docs/dev/ticket-{DEV_ID}.md lane=-"), text
    completion_on_disk(repo, DEV_ID)  # as Step 0's route leaves it
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "cycle artifacts")
    assert run(real) == (0, "")
    real.tx.command("commit", DEV_ID, body=loaded_text("commit", DEV_ID, MASTER))
    code, text = run(real)
    assert code == 2 and f"no commit reachable from HEAD carries the line 'Task-id: {DEV_ID}'" in text, text
    (repo / "scripts" / "one.py").write_text("landed = True\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"land the change\n\nTask-id: {DEV_ID}")
    assert run(real) == (0, "")


def test_a17_the_two_demands_are_this_trees_text_and_not_masters():
    """The COMPATIBILITY block's two demands, as this tree's /dev and /dev-command word them: each text on
    disk words both; master's lacks both; P1b's (3f0b7a2) names by Task id and lacks this template."""
    for command in gate.DEV_TEXTS:
        current = (REPO / "commands" / f"{command}.md").read_text(encoding="utf-8")
        for pattern in (gate.NAMING, gate.COMPLETION_TEMPLATE):
            found = gate.re.search(pattern, current, gate.re.M)
            assert found and found.group(0) in loaded_text(command, ""), (command, pattern)
            assert found.group(0) not in loaded_text(command, "", MASTER), (command, pattern)
        assert gate.re.search(gate.NAMING, current).group(0) in loaded_text(command, "", "3f0b7a2")
        assert gate.re.search(gate.COMPLETION_TEMPLATE, current, gate.re.M).group(0) not in loaded_text(
            command, "", "3f0b7a2")


def test_a12_real_after_end_time_the_families_chain_at_the_working_root_and_the_closeout_decide(real, monkeypatch):
    """test_a12_after_end_time_the_families_and_closeout_decide on P3's real disposition: after
    end_time the /dev-overnight Stop holds while a family the span dispatched is not chain_pass at
    the session's working root (P2's locator), and its terminal status follows once the chain and
    the closeout are on disk there."""
    wt = real.tmp / "wt"
    (wt / "docs" / "dev").mkdir(parents=True)
    real_overnight(real, monkeypatch, hours=-1, worktree_path=str(wt))
    overnight_session(real, wake=False)
    real.tx.todos(canonical("dev-overnight", "--hours 1"), len(canonical("dev-overnight", "--hours 1")))
    real.tx.dispatch(FAMILY, pipeline="dev-overnight")
    chain_on_disk(wt, qa="fail")
    closeout_on_disk(wt)
    code, text = run(real)
    assert code == 2 and "problem=INVALID_QA_STATUS: qa.status is 'fail'" in text, text
    assert not (real.project / "docs" / "dev" / f"qa-report-{FAMILY}.json").exists()
    chain_on_disk(wt)
    assert gate.decision(real.payload) == (0, "", "completed_by_deadline")
