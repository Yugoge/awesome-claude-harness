"""D5 / B3.c: the tool streak and the /do consent flag have one clearer, the UserPromptSubmit hook.

hooks/prompt-workflow.py ``_clear_turn_state`` runs at every UserPromptSubmit: it removes
``claude-tool-streak-<sid>.json`` and, unless the prompt is /do, also
``claude-orchestrator-consent-<sid>.flag``, both in the hook state dir (CLAUDE_STATE_DIR,
hooks/lib/harness_state_dir.py). The Stop-time clearers in hooks/stop-cleanup-allowlist.sh and
hooks/stop-do-report-gate.py are gone, so /do consent lasts exactly one turn: a Stop (blocked or
not) and an AskUserQuestion answered inside the turn keep it, and the next UserPromptSubmit ends
it, whether the human typed it or the CLI fired it for a scheduled task or a task notification.

Every hook runs as a subprocess with a UserPromptSubmit / PreToolUse / PostToolUse / Stop payload
shaped as the CLI sends it, against a transcript that starts with the two queue-operation records.
CLAUDE_STATE_DIR, HOME, CLAUDE_CONFIG_DIR, CLAUDE_PROJECT_DIR and TMPDIR point at the test's own
tmp_path (the project a git-less directory); a second session's streak and flag in the same
state dir must survive everything.

Also here (acceptance 19, row 16): hooks/pretool-tool-policy.py lets a BA subagent write its own
question artifact docs/dev/producer-question-<task>-ba.json, which its dispatch's obligation names
(the permission derived from the dispatch record, P1b E3), and refuses dev's
docs/dev/producer-question-<task>-dev.json. hooks/tests/test_tool_policy_contracts.py calls
policy_registry in process, so its helpers do not fit a subprocess run of the hook.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "hooks"
PROMPT_WORKFLOW = HOOKS / "prompt-workflow.py"
ORCHESTRATOR_GATE = HOOKS / "pretool-orchestrator-gate.py"
DO_REPORT_GATE = HOOKS / "stop-do-report-gate.py"
CLEANUP = HOOKS / "stop-cleanup-allowlist.sh"
TOOL_POLICY = HOOKS / "pretool-tool-policy.py"
SETTINGS = ROOT / "settings.json"
OTHER_SID = "other-session-0000"
# Every hook command in settings.json has this form.
_COMMAND_RE = re.compile(r'^(python3|bash) "\$\{CLAUDE_HOME:-\$HOME/\.claude\}/(hooks/[^"]+)"$')
# Environment a hook could take a session, a mode or a home from instead of the payload.
_INHERITED_DROP = ("DO_REPORT_GATE_MODE", "LANEB_SESSION_RESOURCE_TRUST_KEY",
                   "LANEB_SESSION_RESOURCE_TRUST_ROOT", "ARTIFACT_CONTRACT_ENFORCE_MODE")

ASK_INPUT = {"questions": [{
    "question": "Which heading should be renamed?",
    "header": "Heading",
    "options": [{"label": "Title", "description": "The top-level heading"},
                {"label": "Usage", "description": "The usage section heading"}],
    "multiSelect": False,
}]}
ASK_RESPONSE = {"questions": ASK_INPUT["questions"],
                "answers": {"Which heading should be renamed?": "Title"}}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


class Session:
    """One main session: a git-less project, a transcript and a private hook state dir."""

    def __init__(self, tmp_path: Path):
        self.state = tmp_path / "state"
        self.home = tmp_path / "home"
        self.config = self.home / ".claude"
        self.project = tmp_path / "project"
        for d in (self.state, self.config, self.project, tmp_path / "tmp"):
            d.mkdir(parents=True, exist_ok=True)
        self.sid = str(uuid.uuid4())
        slug = str(self.project).replace("/", "-")
        self.transcript = self.config / "projects" / slug / f"{self.sid}.jsonl"
        self.transcript.parent.mkdir(parents=True)
        self.transcript.write_text("")
        self._parent = None
        env = {k: v for k, v in os.environ.items()
               if not (k.startswith("CLAUDE") and k != "CLAUDE_PYTHON_BIN")
               and k not in _INHERITED_DROP}
        env.update({
            "HOME": str(self.home),
            "CLAUDE_CONFIG_DIR": str(self.config),
            "CLAUDE_STATE_DIR": str(self.state),
            "CLAUDE_PROJECT_DIR": str(self.project),
            "TMPDIR": str(tmp_path / "tmp"),
            "GIT_CEILING_DIRECTORIES": str(tmp_path),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        self.env = env
        # T1: the main transcript starts with two queue-operation records.
        for operation in ("enqueue", "dequeue"):
            self._write({"type": "queue-operation", "operation": operation,
                         "timestamp": _now(), "sessionId": self.sid})
        # A concurrent session's turn state shares the state dir and must never be touched.
        self.streak(OTHER_SID).write_text(json.dumps(_streak_state(4)))
        self.flag(OTHER_SID).write_text("true")

    # -- state files -------------------------------------------------------------------
    def streak(self, sid: str | None = None) -> Path:
        return self.state / f"claude-tool-streak-{self.sid if sid is None else sid}.json"

    def flag(self, sid: str | None = None) -> Path:
        return self.state / f"claude-orchestrator-consent-{self.sid if sid is None else sid}.flag"

    def assert_other_session_untouched(self) -> None:
        assert json.loads(self.streak(OTHER_SID).read_text()) == _streak_state(4)
        assert self.flag(OTHER_SID).read_text() == "true"

    # -- transcript --------------------------------------------------------------------
    def _write(self, record: dict) -> None:
        with self.transcript.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def append(self, record: dict) -> None:
        record.setdefault("sessionId", self.sid)
        record.setdefault("cwd", str(self.project))
        record.setdefault("timestamp", _now())
        record.setdefault("uuid", str(uuid.uuid4()))
        record.setdefault("parentUuid", self._parent)
        record.setdefault("isSidechain", False)
        self._parent = record["uuid"]
        self._write(record)

    # -- hooks -------------------------------------------------------------------------
    def payload(self, event: str, **extra) -> dict:
        payload = {"session_id": self.sid, "transcript_path": str(self.transcript),
                   "cwd": str(self.project), "hook_event_name": event,
                   "permission_mode": "default"}
        payload.update(extra)
        return payload

    def run(self, argv: list, payload: dict, extra_env: dict | None = None):
        return subprocess.run(
            argv, input=json.dumps(payload), capture_output=True, text=True,
            cwd=str(self.project), env={**self.env, **(extra_env or {})}, timeout=120)

    def prompt(self, text: str, drop_session_id: bool = False, session_id: str | None = None):
        """UserPromptSubmit through prompt-workflow.py, then the user record(s) the CLI writes."""
        payload = self.payload("UserPromptSubmit", prompt=text)
        if drop_session_id:
            del payload["session_id"]
        elif session_id is not None:
            payload["session_id"] = session_id
        proc = self.run([sys.executable, str(PROMPT_WORKFLOW)], payload)
        stripped = text.strip()
        if stripped.startswith("/"):
            name, _, args = stripped[1:].partition(" ")
            self.append({"type": "user", "origin": {"kind": "human"}, "message": {
                "role": "user",
                "content": (f"<command-message>{name}</command-message>\n"
                            f"<command-name>/{name}</command-name>\n"
                            f"<command-args>{args.strip()}</command-args>")}})
            self.append({"type": "user", "isMeta": True, "message": {
                "role": "user", "content": [{"type": "text", "text": f"Body of /{name}."}]}})
        else:
            self.append({"type": "user", "origin": {"kind": "human"},
                         "message": {"role": "user", "content": text}})
        return proc

    def tool(self, name: str, tool_input: dict, response: dict, perform=None, after_hook=None):
        """One main-agent tool call as the CLI runs it: the tool_use record, every PreToolUse
        hook settings.json registers for `name`, the tool itself (`perform`), the tool_result
        record, every registered PostToolUse hook. Returns [(event, hook, CompletedProcess)]."""
        tool_use_id = "toolu_" + uuid.uuid4().hex[:24]
        self.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tool_use_id, "name": name, "input": tool_input}]}})
        results = []
        pre = self.payload("PreToolUse", tool_name=name, tool_input=tool_input,
                           tool_use_id=tool_use_id)
        for argv in _registered_hooks("PreToolUse", name):
            results.append(("PreToolUse", Path(argv[1]).name, self.run(argv, pre)))
            if after_hook:
                after_hook(*results[-1])
        if perform:
            perform()
        self.append({"type": "user", "toolUseResult": response, "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tool_use_id, "content": json.dumps(response)}]}})
        post = self.payload("PostToolUse", tool_name=name, tool_input=tool_input,
                            tool_response=response, tool_use_id=tool_use_id)
        for argv in _registered_hooks("PostToolUse", name):
            results.append(("PostToolUse", Path(argv[1]).name, self.run(argv, post)))
            if after_hook:
                after_hook(*results[-1])
        return results

    def todos_file(self) -> Path:
        return self.config / "todos" / f"{self.sid}-agent-{self.sid}.json"

    def stop(self, argv: list, extra_env: dict | None = None):
        return self.run(argv, self.payload("Stop", stop_hook_active=False,
                                           last_assistant_message="Renamed the heading."),
                        extra_env)

    def do_task_id(self) -> str:
        return json.loads((self.state / f"claude-do-task-{self.sid}.json").read_text())["task_id"]

    def do_report(self) -> Path:
        return self.project / "docs" / "dev" / f"do-report-{self.do_task_id()}.json"


def _streak_state(count: int) -> dict:
    """The schema-2 state pretool-orchestrator-gate.py writes after `count` Bash calls."""
    return {"schema_version": 2, "per_tool_counts": {},
            "bash_consecutive": {"last_tool": "Bash", "count": count}}


def _complete_do_report(sess: Session) -> None:
    """The /do main agent writes the whole report (commands/do.md Step 5); no hook pre-writes it."""
    task_id = sess.do_task_id()
    report = sess.do_report()
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({
        "report_version": 1, "task_id": task_id, "request_id": task_id, "source": "do",
        "request": "rename heading", "profile": "do",
        "expected_absent": ["qa-report", "dev-report", "ticket", "context", "completion"],
        "do": {"status": "completed", "summary": "Renamed the README heading.",
               "files_modified": ["README.md"], "files_created": []},
    }, indent=2))


def _matcher_applies(matcher, tool_name: str) -> bool:
    """Claude Code matcher semantics: absent, "" and "*" match every tool; a plain
    name list (letters, digits, _ and |) matches exactly; anything else is a regex."""
    if matcher in (None, "", "*"):
        return True
    if re.fullmatch(r"[A-Za-z0-9_|]+", matcher):
        return tool_name in matcher.split("|")
    return re.search(matcher, tool_name) is not None


def _registered_hooks(event: str, tool_name: str) -> list:
    """argv for every hook settings.json registers for `event` whose matcher applies to
    `tool_name`, in registration order. A command of an unknown form fails the test, so no
    registered hook is skipped."""
    settings = json.loads(SETTINGS.read_text())
    out = []
    for group in settings["hooks"].get(event, []):
        if not _matcher_applies(group.get("matcher"), tool_name):
            continue
        for hook in group["hooks"]:
            command = hook.get("command", "")
            match = _COMMAND_RE.match(command)
            assert match, f"{event} hook command of an unknown form: {command!r}"
            interpreter, rel = match.groups()
            script = ROOT / rel
            assert script.is_file(), f"{event} hook {rel} is registered but absent"
            out.append([sys.executable if interpreter == "python3" else "bash", str(script)])
    return out


@pytest.fixture
def sess(tmp_path: Path) -> Session:
    return Session(tmp_path)


# -- (a) a blocked Stop keeps the streak; the next human prompt removes it -----------------

def test_plain_prompt_after_a_blocked_stop_removes_the_streak(sess):
    assert sess.prompt("/do rename heading").returncode == 0
    assert not sess.do_report().exists(), "the /do hook writes no do-report"
    # Next turn: consent is gone, so the orchestrator gate counts the main agent's Bash calls.
    assert sess.prompt("go on, list the files first").returncode == 0
    assert not sess.flag().exists()
    for _ in range(2):
        bash = {"command": "ls", "description": "List files"}
        tool_use_id = "toolu_" + uuid.uuid4().hex[:24]
        sess.append({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": tool_use_id, "name": "Bash", "input": bash}]}})
        gate = sess.run([sys.executable, str(ORCHESTRATOR_GATE)], sess.payload(
            "PreToolUse", tool_name="Bash", tool_input=bash, tool_use_id=tool_use_id))
        assert gate.returncode == 0, gate.stderr
    assert json.loads(sess.streak().read_text())["bash_consecutive"] == {
        "last_tool": "Bash", "count": 2}
    # The Stop is blocked: the /do report is still absent.
    stop = sess.stop([sys.executable, str(DO_REPORT_GATE)])
    assert stop.returncode == 2 and "DO_REPORT_GATE_BLOCKED" in stop.stderr, stop.stderr
    assert sess.streak().exists(), "a blocked Stop must not be what clears the streak"

    proc = sess.prompt("why did it stop?")
    assert proc.returncode == 0, proc.stderr
    assert not sess.streak().exists(), "the next UserPromptSubmit must remove the streak file"
    sess.assert_other_session_untouched()


# -- (b) /do keeps (writes) the flag for its own turn; any other prompt removes it ---------

@pytest.mark.parametrize("do_prompt", ["/do rename heading", "/do", "  /do rename heading"])
def test_do_prompt_writes_the_flag_and_still_clears_the_streak(sess, do_prompt):
    sess.streak().write_text(json.dumps(_streak_state(3)))
    proc = sess.prompt(do_prompt)
    assert proc.returncode == 0, proc.stderr
    assert sess.flag().read_text() == "true", "/do must leave its consent flag present"
    assert not sess.streak().exists(), "/do is a human prompt too: the streak resets"
    sess.assert_other_session_untouched()


@pytest.mark.parametrize("next_prompt", [
    "thanks, now update the changelog",
    "please /do the same for the next heading",  # not a slash command: starts with text
    "/document the rename",  # a different command that merely starts with "/do"
])
def test_the_prompt_after_do_removes_the_flag(sess, next_prompt):
    assert sess.prompt("/do rename heading").returncode == 0
    assert sess.flag().exists()
    sess.streak().write_text(json.dumps(_streak_state(1)))
    proc = sess.prompt(next_prompt)
    assert proc.returncode == 0, proc.stderr
    assert not sess.flag().exists(), f"{next_prompt!r} must end the /do turn's consent"
    assert not sess.streak().exists()
    sess.assert_other_session_untouched()


# -- (c) an AskUserQuestion round trip inside the /do turn keeps the flag ------------------

def test_ask_user_question_round_trip_keeps_the_flag(sess):
    proc = sess.prompt("/do rename heading")
    assert proc.returncode == 0, proc.stderr
    assert sess.flag().exists()
    hooks = {Path(argv[1]).name for event in ("PreToolUse", "PostToolUse")
             for argv in _registered_hooks(event, "AskUserQuestion")}
    # Non-vacuity: the hooks that read the flag, and those registered for every tool, are in.
    assert {"pretool-orchestrator-gate.py", "pretool-do-block-subagents.py",
            "pretool-block-background-tasks.py", "pretool-subagent-enforce.py",
            "pretool-tool-policy.py", "posttool-allowlist-consume.py"} <= hooks, hooks

    def flag_kept(event, hook, proc):
        assert proc.returncode == 0, (event, hook, proc.returncode, proc.stderr)
        assert sess.flag().read_text() == "true", f"{event} {hook} removed the /do consent flag"

    # The workflow's FIRST ACTION: TodoWrite with the canonical list the hook just printed.
    # The CLI holds no list before it (no hook writes the CLI's todo file).
    todos = json.loads(proc.stdout.strip().splitlines()[-1])
    assert not sess.todos_file().exists()

    def cli_writes_its_todo_file():
        sess.todos_file().parent.mkdir(parents=True, exist_ok=True)
        sess.todos_file().write_text(json.dumps(todos))

    sess.tool("TodoWrite", {"todos": todos}, {"oldTodos": [], "newTodos": todos},
              perform=cli_writes_its_todo_file, after_hook=flag_kept)
    ran = sess.tool("AskUserQuestion", ASK_INPUT, ASK_RESPONSE, after_hook=flag_kept)
    assert {hook for _event, hook, _proc in ran} == hooks
    sess.assert_other_session_untouched()


# -- (d) the former Stop-time clearers leave the flag and the streak ----------------------

def test_do_report_gate_with_a_completed_report_keeps_the_flag_and_streak(sess):
    assert sess.prompt("/do rename heading").returncode == 0
    sess.streak().write_text(json.dumps(_streak_state(2)))
    blocked = sess.stop([sys.executable, str(DO_REPORT_GATE)])
    assert blocked.returncode == 2, "the gate must see this /do cycle (no report yet)"
    _complete_do_report(sess)
    proc = sess.stop([sys.executable, str(DO_REPORT_GATE)])
    assert proc.returncode == 0, proc.stderr
    assert not (sess.state / f"claude-do-report-gate-{sess.sid}.json").exists(), \
        "the compliant branch ran (it removes the block counter)"
    assert sess.flag().read_text() == "true"
    assert json.loads(sess.streak().read_text()) == _streak_state(2)
    sess.assert_other_session_untouched()


def test_do_report_gate_forced_allow_keeps_the_flag(sess):
    assert sess.prompt("/do rename heading").returncode == 0
    for _ in range(2):
        assert sess.stop([sys.executable, str(DO_REPORT_GATE)]).returncode == 2
    forced = sess.stop([sys.executable, str(DO_REPORT_GATE)])
    assert forced.returncode == 0 and "FORCED ALLOW" in forced.stderr, forced.stderr
    assert sess.flag().read_text() == "true"
    sess.assert_other_session_untouched()


def test_stop_cleanup_keeps_the_flag_and_streak(sess):
    assert sess.prompt("/do rename heading").returncode == 0
    sess.streak().write_text(json.dumps(_streak_state(2)))
    # An expired /allow grant: the cleanup still reaps it, which shows it ran.
    grant = sess.state / "claude-grants" / f"{sess.sid}.json"
    grant.parent.mkdir(exist_ok=True)
    grant.write_text(json.dumps({"task_id": sess.sid, "session_id": sess.sid,
                                 "allowed_operations": [{"op": "git"}],
                                 "created_at": 0, "expires_at": 1}))
    proc = sess.stop(["bash", str(CLEANUP)])
    assert proc.returncode == 0, proc.stderr
    assert not grant.exists(), "stop-cleanup-allowlist.sh did not run its grant reap"
    assert sess.flag().read_text() == "true"
    assert json.loads(sess.streak().read_text()) == _streak_state(2)
    sess.assert_other_session_untouched()


# -- (e) no session identity: nothing is removed -----------------------------------------

@pytest.mark.parametrize("identity", ["absent", "empty"])
def test_prompt_without_session_id_removes_nothing(sess, identity):
    seeded = {
        sess.streak(): json.dumps(_streak_state(2)),
        sess.flag(): "true",
        sess.streak(""): json.dumps(_streak_state(1)),
        sess.flag(""): "true",
    }
    for path, text in seeded.items():
        path.write_text(text)
    if identity == "absent":
        proc = sess.prompt("hello", drop_session_id=True)
    else:
        proc = sess.prompt("hello", session_id="")
    assert proc.returncode == 0, proc.stderr
    for path, text in seeded.items():
        assert path.read_text() == text, f"{path.name} changed without a session_id"
    sess.assert_other_session_untouched()


# -- (f) a UserPromptSubmit the human did not type starts a turn too ---------------------

_TASK_NOTIFICATION = (
    "<task-notification>\n<task-id>b7c1e20</task-id>\n<status>completed</status>\n"
    "<summary>Background command \"Run the test suite\" completed (exit code 0)</summary>\n"
    "</task-notification>")


@pytest.mark.parametrize("kind", ["task_notification", "scheduled_prompt"])
def test_a_prompt_the_human_did_not_type_also_ends_the_turn_state(sess, kind):
    """Row 25 reads "at every UserPromptSubmit": the CLI also fires the event for a scheduled
    task, a background task or subagent reporting back and a peer message (hooks reference), and
    each starts a new turn, so it ends the /do turn's consent and resets the streak like a typed
    prompt does."""
    assert sess.prompt("/do rename heading").returncode == 0
    assert sess.flag().exists()
    sess.streak().write_text(json.dumps(_streak_state(2)))
    if kind == "task_notification":
        text = _TASK_NOTIFICATION
        # The queued_command attachment shape measured for a hand-back (CLI 2.1.303).
        record = {"type": "attachment", "attachment": {
            "type": "queued_command", "prompt": text, "commandMode": "prompt", "isMeta": True}}
    else:
        text = "check whether the nightly build finished"
        # The scheduled-prompt record measured for a CronCreate firing (CLI 2.1.303).
        record = {"type": "user", "isMeta": True, "turnOrigin": "scheduled",
                  "promptSource": "system", "message": {"role": "user", "content": text}}
    proc = sess.run([sys.executable, str(PROMPT_WORKFLOW)],
                    sess.payload("UserPromptSubmit", prompt=text))
    sess.append(record)
    assert proc.returncode == 0, proc.stderr
    assert not sess.flag().exists(), f"a {kind} UserPromptSubmit must end the /do turn's consent"
    assert not sess.streak().exists(), f"a {kind} UserPromptSubmit must reset the streak"
    sess.assert_other_session_untouched()


# -- acceptance 19 (row 16): BA may write its own question artifact, not dev's -------------

# A BA write is denied anywhere under /tmp or /var/tmp (the actor-exact scratch rule), so the
# project path must lie outside both. The hook only inspects the path; nothing is created.
_POLICY_PROJECT = Path("/nonexistent-p1-tool-policy-probe") / "proj"


@pytest.mark.parametrize("name, expected_rc", [
    ("producer-question-dev-20261019-101010-ba.json", 0),
    ("producer-question-dev-20261019-101010-dev.json", 2),
    ("producer-question-dev-20261019-101010-ba.json.bak", 2),
])
def test_ba_write_of_a_producer_question_artifact(tmp_path, name, expected_rc):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    target = _POLICY_PROJECT / "docs" / "dev" / name
    content = json.dumps({"task_id": "dev-20261019-101010", "role": "ba"})
    agent_id = "a" + uuid.uuid4().hex[:16]
    # The BA dispatch record the CLI keeps: the session's Agent call, the child's
    # first record (its prompt) and the meta naming the call.
    obligation = {"task_id": "dev-20261019-101010", "role": "ba", "pipeline": "dev",
                  "profile": "singular", "dispatched_at": "2026-10-19T10:10:10Z",
                  "artifacts": [{"kind": "markdown", "path": "docs/dev/ticket-dev-20261019-101010.md",
                                 "identity_anchor": "dev-20261019-101010"}]}
    prompt = f'You are the BA subagent.\n<obligation v="1">\n{json.dumps(obligation)}\n</obligation>\n'
    transcript = tmp_path / "sess-tool-policy.jsonl"
    call = {"type": "tool_use", "id": "toolu_ba", "name": "Agent",
            "input": {"description": "BA", "prompt": prompt}}
    transcript.write_text(json.dumps({"type": "assistant", "message": {"role": "assistant",
                                                                       "content": [call]}}) + "\n")
    subagents = tmp_path / "sess-tool-policy" / "subagents"
    subagents.mkdir(parents=True)
    (subagents / f"agent-{agent_id}.jsonl").write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": prompt}}) + "\n")
    (subagents / f"agent-{agent_id}.meta.json").write_text(json.dumps({"toolUseId": "toolu_ba"}))
    payload = {
        "session_id": "sess-tool-policy", "transcript_path": str(transcript),
        "cwd": str(_POLICY_PROJECT), "hook_event_name": "PreToolUse",
        "permission_mode": "default", "tool_name": "Write",
        "tool_input": {"file_path": str(target), "content": content},
        "tool_use_id": "toolu_" + uuid.uuid4().hex[:24],
        # agent_id/agent_type as the CLI sends them for a subagent's call; the role label
        # resolve_agent_type reads first (payload.subagent_type), as in
        # tests/test_tool_policy_note_fail_closed.py.
        "agent_id": agent_id, "agent_type": "ba", "subagent_type": "ba",
    }
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("CLAUDE") and k != "CLAUDE_PYTHON_BIN")}
    env.update({"HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
                "CLAUDE_STATE_DIR": str(tmp_path / "state"),
                "CLAUDE_PROJECT_DIR": str(_POLICY_PROJECT), "PYTHONDONTWRITEBYTECODE": "1"})
    proc = subprocess.run([sys.executable, str(TOOL_POLICY)], input=json.dumps(payload),
                          capture_output=True, text=True, cwd=str(tmp_path), env=env, timeout=60)
    assert proc.returncode == expected_rc, proc.stderr
    if expected_rc == 0:
        assert "BLOCKED" not in proc.stderr, proc.stderr
    else:
        first = proc.stderr.splitlines()[0]
        prefix = "BLOCKED by tool-policy.v1: "
        assert first.startswith(prefix), proc.stderr
        assert json.loads(first[len(prefix):]) == {
            "role": "ba", "tool": "Write", "target": str(target),
            "deny_reason": f"write target {target} not in allowed_write_path_prefixes"}
    assert not _POLICY_PROJECT.parent.exists(), "the policy check must not create the project"
