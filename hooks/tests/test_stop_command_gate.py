"""Tests for hooks/stop-command-gate.py, P5 R7 and R8, and R10's move.

The gate calls P3's disposition, P2's overnight locator and window, and P4's
close rating; where those phases are not on this base the tests use fakes
with their signatures (each such test says so), so the cases that rest on
their behaviour are re-run once they merge. The rest runs the real readers:
command_span on CLI-shaped transcripts, git on local repositories, the
do-branch write-set helper and dev-lifecycle's --auto target function.

Run with: python3 -m pytest hooks/tests/test_stop_command_gate.py -q
"""
from __future__ import annotations

import ast
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
command_span = gate.command_span
obligation = gate._lib("obligation")
todo_canonical = gate._lib("todo_canonical")

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

    def command(self, name: str, args: str = "", context: str | None = None):
        self.add({"type": "queue-operation", "operation": "enqueue", "content": f"/{name} {args}".strip()})
        self.add({"type": "user", "message": {"role": "user", "content":
                  f"<command-message>{name} is running…</command-message>\n<command-name>/{name}</command-name>\n"
                  f"<command-args>{args}</command-args>"}})
        self.add({"type": "user", "isMeta": True, "message": {"role": "user", "content": [
            {"type": "text", "text": f"body of {name}"}]}})
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
    """P3's disposition(project_root, task_id, stage) and gap_line(gap): a
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
    closeout_gaps(state, working_root) and working_root(state)."""
    module = types.ModuleType("lib.overnight")
    module.locate = lambda session_id, payload=None: (Path("state.json"), record) if record else (None, None)
    module.window_open = lambda payload: bool(record) and window
    module.closeout_gaps = lambda state, working_root: list(closeout)
    module.working_root = lambda state: Path(state.get("worktree_path") or ".")
    return module


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
    monkeypatch.setitem(gate._SCRIPTS, "scripts/resolve-dev-artifact-chain.py", fake)
    monkeypatch.setattr(obligation, "declaring_dispatch", lambda task, path, root, roots=None: None)
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
    monkeypatch.setattr(obligation, "declaring_dispatch", lambda task, path, root, roots=None: {
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
    """Fake disposition (P3): re-run once P3 merges."""
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
    env.fake.answers[(DO_ID, "dev")] = [gap(f"docs/dev/do-report-{DO_ID}.json", "do.status:pending", "pending")]
    results = [run(env) for _ in range(4)]
    assert all(code == 2 and "do.status:pending" in text and "FORCED" not in text for code, text in results)
    assert {c[3] for c in env.fake.calls} == {str(env.tx.path)}  # the do branch takes the transcript (R8)


def test_a4_the_task_is_the_hook_minted_id_not_the_sidecar_or_an_echo(env):
    do_span(env)
    env.tx.tool("Bash", {"command": "echo '[/do] task-id minted: 20990101-000000'"},
                result="[/do] task-id minted: 20990101-000000")
    env.tx.say("[/do] task-id minted: 20990101-000001")
    (env.state / f"claude-do-task-{SID}.json").write_text(json.dumps({"task_id": "20990101-000002"}))
    run(env)
    (env.state / f"claude-do-task-{SID}.json").unlink()
    run(env)
    assert [c[1] for c in env.fake.calls] == [DO_ID, DO_ID]


def test_a4_a_do_span_with_no_minted_line_names_the_gap(env):
    do_span(env, context="[/do] Consent granted.")
    code, text = run(env)
    assert code == 2 and "no hook-minted task id" in text


def test_a4_the_gate_creates_and_deletes_no_file(env):
    do_span(env)
    env.fake.answers[(DO_ID, "dev")] = [gap("docs/dev/do-report-x.json", "MISSING_ARTIFACT", "absent")]
    before = sorted(p for p in env.tmp.rglob("*"))
    for mode in ("block", "advisory"):
        run(env, mode)
    assert sorted(p for p in env.tmp.rglob("*")) == before


# R8: the do branch's write-set helper and Span.write_set, on the real readers
resolver = _load(REPO / "scripts" / "resolve-dev-artifact-chain.py", "resolver_under_test")


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


def test_r8_without_a_transcript_the_lists_stand(env):
    path = do_report(env, modified=["src/never.py"])
    assert resolver.do_report_gaps(env.project, DO_ID, path) == []


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


def opener_now(env, command, args=""):
    """The opener, stamped after every git step so far and before every later one."""
    env.tx.clock = datetime.fromtimestamp(GIT_CLOCK[0] + 8, timezone.utc)
    env.tx.command(command, args)
    GIT_CLOCK[0] += 20


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


@pytest.fixture
def remotes(env, repo):
    for name in ("origin", "fork"):
        bare = env.tmp / f"{name}.git"
        git(env.tmp, "init", "-q", "--bare", str(bare))
        git(repo, "remote", "add", name, str(bare))
    git(repo, "checkout", "-q", "-b", "topic")
    commit(repo, "t1.txt")
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


def test_a6_push_from_a_detached_head_names_it(env, remotes):
    git(remotes, "checkout", "-q", "--detach")
    opener_now(env, "push")
    code, text = run(env)
    assert code == 2 and "detached" in text


@pytest.mark.parametrize("command", ["merge", "push"])
def test_a6_git_predicates_outside_a_repository_are_instrument_failures(env, command):
    env.tx.command(command)
    code, text = run(env)
    assert code == 2 and "gate instrument failure: RuntimeError:" in text and "not a git repository" in text


def test_a6_commit_modes_only_if_typed(env):
    """Fake disposition (P3): --stage commit's Task-id check is P3's; re-run once it merges."""
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


@pytest.mark.parametrize("required,asked,code", [(True, False, 2), (True, True, 0), (False, False, 0)])
def test_a8_close_needs_the_rating_question_asked_where_required(env, monkeypatch, required, asked, code):
    """Fake close_rating (P4) and disposition (P3): re-run once they merge."""
    monkeypatch.setitem(sys.modules, "lib.close_rating", rating_fake(required, asked))
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


# ---------------------------------------------------------------- A11: modes
def test_a11_advisory_reports_would_block_and_allows(env):
    dev_span(env, done=1)
    code, text = run(env, "advisory")
    assert code == 0 and text.startswith("would block\nCOMMAND_GATE /dev: not complete\n")


def test_a11_off_allows_everything_and_mode_parsing(env, monkeypatch):
    dev_span(env, done=1)
    monkeypatch.setitem(sys.modules, "lib.overnight", overnight_fake({"end_time": "x"}, window=True))
    assert run(env, "off") == (0, "")
    assert [gate._mode(a) for a in (["--mode", "off"], ["--mode=advisory"], [], ["--mode", "bogus"])] == [
        "off", "advisory", "block", "block"]


def test_a11_todo_tools_disabled_is_one_gap(env, monkeypatch):
    dev_span(env, done=1)
    monkeypatch.delenv("CLAUDE_CODE_ENABLE_TODO_TOOLS")
    code, text = run(env)
    assert code == 2 and "- todo tools disabled (CLAUDE_CODE_ENABLE_TODO_TOOLS)\n" in text
    assert "todo: not completed" not in text


@pytest.mark.parametrize("command", ["commit", "merge", "push"])
def test_todo_half_without_a_canonical_list_needs_the_last_list_completed(env, command):
    env.fake.answers.clear()
    env.tx.command(command, FAMILY if command == "commit" else "")
    env.tx.tool("TodoWrite", {"todos": [{"content": "a", "activeForm": "a", "status": "completed"},
                                        {"content": "b", "activeForm": "b", "status": "pending"}]})
    assert "todo: not completed: b" in gate.todo_gaps(command_span.active_span(env.tx.path))[0]


# ---------------------------------------------------------------- instrument failures (step 6)
def test_an_absent_producer_function_is_an_instrument_failure_never_an_allow(env, monkeypatch):
    monkeypatch.setitem(gate._SCRIPTS, "scripts/resolve-dev-artifact-chain.py", types.SimpleNamespace())
    steps = dev_span(env, done=0)
    env.tx.todos(steps, len(steps))
    code, text = run(env)
    assert code == 2 and "- gate instrument failure: AttributeError:" in text


def test_an_unloadable_close_rating_is_an_instrument_failure(env, monkeypatch):
    monkeypatch.setitem(sys.modules, "lib.close_rating", None)  # P4 absent: the import fails
    env.tx.command("close", FAMILY)
    code, text = run(env)
    assert code == 2 and "gate instrument failure: ModuleNotFoundError" in text


# ---------------------------------------------------------------- A12: the overnight time-lock (P2 faked)
def test_a12_an_open_window_blocks_any_span_in_any_mode_but_off(env, monkeypatch):
    """Fake window_open (P2): re-run once P2 merges."""
    monkeypatch.setitem(sys.modules, "lib.overnight", overnight_fake(
        {"session_id": SID, "end_time": "2026-11-01T10:00:00Z"}, window=True))
    env.tx.command("spec")
    for mode in ("block", "advisory"):
        assert run(env, mode) == (2, "COMMAND_GATE time-lock: overnight window open until 2026-11-01T10:00:00Z;"
                                     " continue the remaining pipelines\n")
    assert run(env, "off") == (0, "")
    monkeypatch.setenv("CLAUDE_COMPAT_RUNTIME", "codex")
    assert run(env) == (0, "")


def overnight_session(env, wake=True):
    env.tx.command("dev-overnight", "--hours 1")
    if wake:
        env.tx.tool("CronCreate", {"cron": "*/30 * * * *", "prompt": "resume", "recurring": True},
                    extra={"toolUseResult": {"id": "cron-7", "recurring": True}})


def test_a12_after_the_window_a_live_wake_blocks_naming_its_id_until_deleted(env, monkeypatch):
    monkeypatch.setitem(sys.modules, "lib.overnight", overnight_fake({"session_id": SID, "worktree_path":
                                                                      str(env.project)}, window=False))
    overnight_session(env)
    env.tx.command("stop")
    code, text = run(env)
    assert code == 2 and "cron-7" in text and "AskUserQuestion" not in text
    env.tx.tool("CronDelete", {"id": "cron-7"})
    assert gate.decision(env.payload) == (0, "", "cancelled_by_user")


def test_a12_after_end_time_the_families_and_closeout_decide(env, monkeypatch):
    """Fake overnight and disposition (P2, P3): re-run once they merge."""
    record = {"session_id": SID, "worktree_path": str(env.tmp / "wt")}
    monkeypatch.setitem(sys.modules, "lib.overnight", overnight_fake(record, closeout=["no PM retrospective"]))
    overnight_session(env, wake=False)
    env.tx.todos(canonical("dev-overnight", "--hours 1"), len(canonical("dev-overnight", "--hours 1")))
    env.tx.dispatch(f"{FAMILY}-1", pipeline="dev-overnight")
    env.fake.answers[(f"{FAMILY}-1", "dev")] = [gap("docs/dev/producer-question-x-ba.json", "unanswered", "open")]
    code, text = run(env)
    assert code == 2 and "unanswered" in text and "no PM retrospective" in text
    assert "AskUserQuestion" not in text and "record the decision" in text
    assert env.fake.calls[-1][0] == str(env.tmp / "wt")
    env.fake.answers.clear()
    monkeypatch.setitem(sys.modules, "lib.overnight", overnight_fake(record))
    assert gate.decision(env.payload) == (0, "", "completed_by_deadline")


def test_a12_no_terminal_status_without_an_overnight_record_or_with_an_open_closeout(env, monkeypatch):
    env.tx.command("spec")
    assert gate.decision(env.payload) == (0, "", None)
    monkeypatch.setitem(sys.modules, "lib.overnight", overnight_fake({"session_id": SID}, closeout=["no summary"]))
    assert gate.decision(env.payload) == (0, "", None)


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
